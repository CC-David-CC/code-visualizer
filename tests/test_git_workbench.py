import asyncio
import json
import shutil
import subprocess
from argparse import Namespace
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread

import pytest

from code_visualizer.application.git import GitError, GitRepository, GitStatus
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.headless import HeadlessService
from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.application.session import ProjectSession
from code_visualizer.automation.mcp import McpServerAdapter
from code_visualizer.automation.protocol import RpcError
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.cli import _load_project, _serve_project
from code_visualizer.config import PRODUCT
from code_visualizer.persistence import ProjectStore
from code_visualizer.persistence.store import JournalRecord
from code_visualizer.sdk import AsyncRemoteClient
from code_visualizer.ui_qt.git_workbench import GitWorkbenchWidget
from code_visualizer.ui_qt.main_window import MainWindow

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Real Git is required")


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_project_root():
    # The source checkout may itself belong to a repository; these are isolated real repos.
    with TemporaryDirectory(prefix="code-visualizer-git-") as directory:
        yield Path(directory) / "project"


@pytest.fixture
def repo(git_project_root):
    session = ProjectSession.new()
    session.save_as(git_project_root)
    controller = GitProjectController(session)
    controller.execute("initialize", {})
    root = session.root
    git(root, "config", "user.name", "Workbench Test")
    git(root, "config", "user.email", "test@example.invalid")
    repository = GitRepository(root)
    controller.execute("stage", {"paths": ["project.json"], "expected_head": ""})
    controller.execute(
        "commit",
        {
            "message": "Initial project",
            "expected_head": "",
            "expected_index": repository.status().index_fingerprint,
        },
    )
    yield controller, repository
    controller.session.close()
    session.close()


def commit(controller, repository, message):
    status = repository.status()
    controller.execute("stage", {"paths": ["project.json"], "expected_head": status.head})
    controller.execute(
        "commit",
        {
            "message": message,
            "expected_head": status.head,
            "expected_index": repository.status().index_fingerprint,
        },
    )


@pytest.mark.parametrize("read_only", (False, True))
def test_session_reuses_git_discovery_while_status_and_storage_guards_stay_fresh(
    repo, qtbot, monkeypatch, read_only
):
    controller, repository = repo
    controller.session.close()
    discovered = []
    initialize = GitRepository.__init__

    def observe_discovery(self, project_root, *, executable=None):
        discovered.append(project_root.resolve())
        initialize(self, project_root, executable=executable)

    monkeypatch.setattr(GitRepository, "__init__", observe_discovery)
    controller.session = ProjectSession.open(repository.project_root, read_only=read_only)
    widget = GitWorkbenchWidget()
    qtbot.addWidget(widget)
    widget.attach(controller)
    try:
        assert discovered == [repository.project_root]
        assert widget.snapshot is not None
        previous_head = widget.snapshot.head
        git(repository.root, "commit", "--allow-empty", "-m", "External fresh head")
        widget.refresh()
        assert widget.snapshot is not None and widget.snapshot.head != previous_head
        assert "Git HEAD changed" in widget.status_label.text()
        assert "Git HEAD changed" in controller.session.storage_problem()
        assert discovered == [repository.project_root]
    finally:
        widget.attach(None)


def test_git_controller_uses_the_replacement_sessions_project_scope(repo):
    controller, repository = repo
    previous_repository = controller.session.git_repository()
    nested = repository.project_root / "nested"
    ProjectStore(nested).initialize(create_default_project(title="Nested project"))
    controller.session.close()
    controller.session = ProjectSession.open(nested)
    status = controller.execute("status", {})
    assert isinstance(status, GitStatus)
    assert status.project_prefix == "nested"
    assert controller.session.git_repository() is not previous_repository
    with pytest.raises(GitError, match="another project"):
        controller.session.acknowledge_storage(repository=previous_repository)
    assert controller.session.git_repository().project_root == nested


def test_real_index_diff_history_and_review_fingerprint(repo):
    controller, repository = repo
    assert isinstance(
        controller.session.client.rename_project("A real Git change"), CommandAccepted
    )
    changed = repository.status()
    assert [(item.index, item.worktree, item.path) for item in changed.files] == [
        (" ", "M", "project.json")
    ]
    assert "A real Git change" in repository.diff("project.json").patch
    stale_index = changed.index_fingerprint
    repository.stage(("project.json",))
    with pytest.raises(GitError, match="staged files changed"):
        repository.commit("stale", expected_index=stale_index)
    controller.execute(
        "commit",
        {
            "message": "Reviewed change\n\nLiteral `code` and $(not a shell)",
            "expected_head": changed.head,
            "expected_index": repository.status().index_fingerprint,
        },
    )
    assert len(repository.history()) == 2
    assert repository.history()[0].subject == "Reviewed change"
    assert "A real Git change" in repository.commit_diff(repository.head())
    assert controller.session.storage_problem() is None


def test_checkout_older_revision_does_not_resurrect_recovery_history(repo):
    controller, repository = repo
    base = controller.session.authority.snapshot()
    main = repository.status().branch
    repository.create_branch("earlier")
    for number in range(3):
        controller.session.client.rename_project(f"Later revision {number}")
    commit(controller, repository, "Later revisions")
    old_authority = controller.session.authority
    result = controller.execute("switch", {"branch": "earlier", "expected_head": repository.head()})
    assert result.reload_required
    assert isinstance(
        controller.session.client.rename_project("must not overwrite checkout"), CommandRejected
    )
    assert not controller.session.autosave(old_authority.revision)
    reloaded = controller.reload_session()
    assert reloaded.authority.snapshot() == base
    assert tuple((repository.project_root / PRODUCT.state_directory / "git-history").iterdir())
    assert repository.status().branch == "earlier"
    controller.execute("switch", {"branch": main, "expected_head": repository.head()})
    assert controller.reload_session().authority.snapshot().title == "Later revision 2"


def test_external_checkout_and_external_file_edit_block_command_undo_autosave(repo):
    controller, repository = repo
    repository.create_branch("base")
    controller.session.client.rename_project("newer")
    commit(controller, repository, "Newer")
    git(repository.root, "switch", "base")
    disk = (repository.project_root / "project.json").read_bytes()
    assert isinstance(controller.session.client.rename_project("stale editor"), CommandRejected)
    assert isinstance(controller.session.client.undo(), CommandRejected)
    assert not controller.session.autosave(controller.session.authority.revision)
    assert (repository.project_root / "project.json").read_bytes() == disk
    controller.reload_session()
    path = repository.project_root / "project.json"
    path.write_text("<<<<<<< unresolved Git contents", encoding="utf-8")
    assert isinstance(controller.session.client.rename_project("overwrite"), CommandRejected)
    with pytest.raises(GitError):
        controller.reload_session()
    assert path.read_text(encoding="utf-8").startswith("<<<<<<<")


def test_real_merge_conflicts_require_valid_native_result_and_explicit_commit(repo):
    controller, repository = repo
    main = repository.status().branch
    repository.create_branch("feature")
    controller.session.client.rename_project("Main title")
    commit(controller, repository, "Main title")
    controller.execute("switch", {"branch": "feature", "expected_head": repository.head()})
    controller.reload_session()
    controller.session.client.rename_project("Feature title")
    commit(controller, repository, "Feature title")
    controller.execute("switch", {"branch": main, "expected_head": repository.head()})
    controller.reload_session()
    merged = controller.execute("merge", {"branch": "feature", "expected_head": repository.head()})
    assert merged.conflicts == ("project.json",)
    with pytest.raises(GitError, match="conflicts"):
        controller.reload_session()
    with pytest.raises(GitError, match="valid project"):
        controller.execute(
            "resolve_conflict",
            {
                "path": "project.json",
                "choice": "edited",
                "text": "{}",
                "expected_head": repository.head(),
            },
        )
    versions = repository.conflict("project.json")
    assert "Main title" in versions.ours and "Feature title" in versions.theirs
    controller.execute(
        "resolve_conflict",
        {"path": "project.json", "choice": "theirs", "expected_head": repository.head()},
    )
    controller.reload_session()
    assert controller.session.authority.snapshot().title == "Feature title"
    assert repository.status().merging
    controller.execute(
        "commit",
        {
            "message": "Reviewed Git merge",
            "expected_head": repository.head(),
            "expected_index": repository.status().index_fingerprint,
        },
    )
    assert len(repository.history()[0].parents) == 2


def test_git_scope_untracked_names_and_tracked_recovery_protection(repo):
    _controller, repository = repo
    path = repository.project_root / "literal [x] $(name).txt"
    path.write_text("literal\n", encoding="utf-8")
    repository.stage((path.name,))
    assert "literal" in repository.diff(path.name, staged=True).patch
    repository.unstage((path.name,))
    assert path.read_text() == "literal\n"
    with pytest.raises(GitError):
        repository.stage(("../outside.txt",))
    with pytest.raises(GitError):
        repository.stage((f"{PRODUCT.state_directory}/git-checkpoint.json",))
    git(repository.root, "add", "-f", "--", f"{PRODUCT.state_directory}/git-checkpoint.json")
    with pytest.raises(GitError, match="tracked by Git"):
        repository.ensure_untracked_recovery()


def test_git_local_remote_fetch_pull_push_and_divergence(repo, tmp_path):
    controller, repository = repo
    bare = tmp_path / "upstream.git"
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    repository.add_remote("origin", str(bare))
    branch = repository.status().branch
    repository.push("origin", branch)
    peer = tmp_path / "peer"
    subprocess.run(["git", "clone", str(bare), str(peer)], capture_output=True, check=True)
    git(peer, "config", "user.name", "Peer")
    git(peer, "config", "user.email", "peer@example.invalid")
    store = ProjectStore(peer)
    store.save(replace(store.load(), title="Peer title", revision=10))
    git(peer, "add", "project.json")
    git(peer, "commit", "-m", "Peer change")
    git(peer, "push", "origin", branch)
    repository.fetch("origin")
    controller.execute(
        "pull", {"remote": "origin", "branch": branch, "expected_head": repository.head()}
    )
    assert controller.reload_session().authority.snapshot().title == "Peer title"
    controller.session.client.rename_project("Locally authored")
    commit(controller, repository, "Local")
    store.save(replace(store.load(), title="Diverged peer", revision=11))
    git(peer, "add", "project.json")
    git(peer, "commit", "-m", "Peer diverges")
    git(peer, "push", "origin", branch)
    before = (repository.project_root / "project.json").read_bytes()
    with pytest.raises(GitError):
        controller.execute(
            "pull", {"remote": "origin", "branch": branch, "expected_head": repository.head()}
        )
    assert (repository.project_root / "project.json").read_bytes() == before


def test_git_rpc_permissions_and_proposal_mode(repo):
    controller, repository = repo
    service = AutomationService(
        controller.session.authority, kernel=controller.session.kernel, git=controller
    )
    reader = AutomationContext(
        "reader", "read", AccessMode.COMMIT, frozenset({AutomationCapability.READ})
    )
    assert service.dispatch("git.status", {}, reader)["head"] == repository.head()
    for method in (
        "stage",
        "commit",
        "switch",
        "merge",
        "fetch",
        "push",
        "initialize",
        "resolve_conflict",
        "add_remote",
    ):
        with pytest.raises(RpcError, match="lacks"):
            service.dispatch(f"git.{method}", {}, reader)
    proposal = AutomationContext(
        "proposal", "proposal", AccessMode.PROPOSAL, frozenset(AutomationCapability)
    )
    for method in ("stage", "commit", "switch", "fetch", "reload"):
        with pytest.raises(RpcError, match="Proposal-mode"):
            service.dispatch(f"git.{method}", {}, proposal)
    service.close()


def test_git_dock_reviews_same_files_and_stages_explicit_selection(repo, qtbot):
    controller, repository = repo
    controller.session.client.rename_project("Visible Git edit")
    widget = GitWorkbenchWidget()
    qtbot.addWidget(widget)
    widget.attach(controller)
    assert isinstance(widget.snapshot, GitStatus)
    assert widget.files.topLevelItemCount() == 1
    widget.files.topLevelItem(0).setSelected(True)
    assert "Visible Git edit" in widget.diff.toPlainText()
    widget._paths("stage")
    qtbot.waitUntil(lambda: not widget._busy, timeout=10_000)
    assert repository.status().files[0].staged
    widget.staged.setChecked(True)
    assert "Visible Git edit" in repository.diff("project.json", staged=True).patch


def test_git_headless_cli_reopen_selects_checked_out_file(repo):
    controller, repository = repo
    before = controller.session.authority.snapshot()
    repository.create_branch("earlier")
    controller.session.client.rename_project("Later session")
    commit(controller, repository, "Later session")
    git(repository.root, "switch", "earlier")
    assert _load_project(repository.project_root) == before
    controller.session.close()
    headless = HeadlessService.open(repository.project_root)
    try:
        assert headless.authority.snapshot() == before
        assert isinstance(
            headless.client("headless").rename_project("Headless edit"), CommandAccepted
        )
        (repository.project_root / "project.json").write_text("<<<<<<< conflict", encoding="utf-8")
        assert isinstance(headless.client("headless").rename_project("blocked"), CommandRejected)
    finally:
        headless.close()


def test_git_nested_project_never_commits_an_unrelated_staged_file(repo):
    _controller, repository = repo
    nested = repository.project_root / "nested"
    ProjectStore(nested).initialize(create_default_project(title="Nested"))
    outside = repository.project_root / "outside.txt"
    outside.write_text("unrelated user change", encoding="utf-8")
    git(repository.root, "add", "outside.txt")
    inner = GitRepository(nested)
    inner.stage(("nested/project.json",))
    with pytest.raises(GitError, match="outside this project"):
        inner.commit("Must not include outside", expected_index=inner.status().index_fingerprint)
    assert outside.read_text(encoding="utf-8") == "unrelated user change"


def test_main_window_git_checkout_uses_normal_session_replacement(repo, qtbot):
    controller, repository = repo
    before = controller.session.authority.snapshot()
    repository.create_branch("earlier")
    controller.session.client.rename_project("Later shown project")
    commit(controller, repository, "Later shown project")
    window = MainWindow()
    qtbot.addWidget(window)
    window._install_session(controller.session)
    window._pipeline.attach(None)
    old_authority = window._session.authority
    window._git_controller.execute(
        "switch", {"branch": "earlier", "expected_head": repository.head()}
    )
    qtbot.waitUntil(lambda: window._session.authority is not old_authority, timeout=20_000)
    assert window._session.authority.snapshot() == before
    assert window.git_workbench.controller.session is window._session
    assert window._automation_host.service.authority is window._session.authority
    window._release_session()


def test_headless_git_rpc_switch_restarts_endpoint_and_mcp_forwards_same_grants(repo, monkeypatch):
    controller, repository = repo
    before = controller.session.authority.snapshot()
    repository.create_branch("earlier")
    controller.session.client.rename_project("RPC later")
    commit(controller, repository, "RPC later")
    controller.session.close()
    published = []

    def record_print(value, **_kwargs):
        published.append(json.loads(value))

    monkeypatch.setattr("code_visualizer.cli.print", record_print, raising=False)

    async def scenario():
        task = asyncio.create_task(
            _serve_project(
                Namespace(
                    path=str(repository.project_root),
                    token="git-test-token",
                    host="127.0.0.1",
                    port=0,
                    allow_remote=False,
                )
            )
        )
        try:
            for _ in range(300):
                if published:
                    break
                await asyncio.sleep(0.02)
            assert published
            async with AsyncRemoteClient(
                published[0]["endpoint"], "git-test-token", actor_id="git-client"
            ) as remote:
                adapter = McpServerAdapter(remote)
                response = await adapter.call_tool("git_operation", {"operation": "status"})
                assert not response["isError"]
                status = json.loads(response["content"][0]["text"])
                await remote.call(
                    "git.switch", {"branch": "earlier", "expected_head": status["head"]}
                )
            for _ in range(500):
                if len(published) >= 2:
                    break
                await asyncio.sleep(0.02)
            assert len(published) >= 2
            async with AsyncRemoteClient(
                published[-1]["endpoint"], "git-test-token", actor_id="reconnected"
            ) as remote:
                snapshot = await remote.call("project.snapshot")
                assert snapshot["title"] == before.title
                assert snapshot["revision"] == before.revision
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())


@pytest.mark.parametrize("has_checkpoint", [True, False])
def test_same_head_external_restore_does_not_resurrect_discarded_journal_on_reopen(
    repo, has_checkpoint
):
    controller, repository = repo
    before = controller.session.authority.snapshot()
    head = repository.head()
    assert isinstance(
        controller.session.client.rename_project("Deliberately discarded"), CommandAccepted
    )
    git(repository.root, "restore", "--source=HEAD", "--worktree", "--", "project.json")
    if not has_checkpoint:
        (repository.project_root / PRODUCT.state_directory / "git-checkpoint.json").unlink()
    assert repository.head() == head
    controller.session.close()
    controller.session = ProjectSession.open(repository.project_root)
    assert controller.session.authority.snapshot() == before
    assert ProjectStore(repository.project_root).load() == before


def test_untracked_first_adoption_preserves_journal_recovery_in_every_host(repo):
    _controller, repository = repo
    for adapter in ("desktop", "headless", "cli", "readonly"):
        root = repository.project_root / f"legacy-{adapter}"
        original = create_default_project(title="Legacy untracked project")
        recovered = replace(original, revision=1, title=f"Recovered {adapter}")
        store = ProjectStore(root)
        store.initialize(original)
        store.append(
            JournalRecord(1, "prior-version", f"recover-{adapter}", "project.rename", recovered)
        )
        if adapter != "headless":
            store.project_file.write_text(
                "damaged before native-file publication", encoding="utf-8"
            )
        assert not GitRepository(root).tracks_project()
        if adapter == "desktop":
            session = ProjectSession.open(root)
            try:
                assert session.authority.snapshot() == recovered
            finally:
                session.close()
        elif adapter == "headless":
            service = HeadlessService.open(root)
            try:
                assert service.authority.snapshot() == recovered
            finally:
                service.close()
        elif adapter == "cli":
            assert _load_project(root) == recovered
        else:
            session = ProjectSession.open(root, read_only=True)
            try:
                assert session.authority.snapshot() == recovered
                assert store.project_file.read_text(encoding="utf-8").startswith("damaged")
                assert not (store.state_root / "git-checkpoint.json").exists()
            finally:
                session.close()
        assert store.read_journal()[-1].project == recovered
        assert not (store.state_root / "git-history").exists()


def test_same_head_unpublished_durable_journal_still_recovers_after_crash(repo):
    controller, repository = repo
    before = controller.session.authority.snapshot()
    recovered = replace(
        before, title="Durable journal before publication", revision=before.revision + 1
    )
    store = ProjectStore(repository.project_root)
    store.append(
        JournalRecord(recovered.revision, "desktop", "crash-window", "project.rename", recovered)
    )
    # Simulate process death after durable append, before native-file publication/checkpoint.
    controller.session.close()
    controller.session = ProjectSession.open(repository.project_root)
    assert controller.session.authority.snapshot() == recovered
    assert store.load() == recovered


def test_git_freezes_semantic_commands_before_reviewing_saved_switch_input(repo, monkeypatch):
    controller, repository = repo
    repository.create_branch("earlier")
    observed = []
    require_saved = GitRepository.require_saved

    def interleave(active, snapshot):
        # An editor gesture arriving exactly during Git admission must already be rejected.
        observed.append(controller.session.client.rename_project("interleaved edit"))
        require_saved(active, snapshot)

    monkeypatch.setattr(GitRepository, "require_saved", interleave)
    controller.execute("switch", {"branch": "earlier", "expected_head": repository.head()})
    assert len(observed) == 1 and isinstance(observed[0], CommandRejected)
    assert controller.reload_session().authority.snapshot().title != "interleaved edit"


def test_storage_boundary_drains_in_flight_generation_before_worktree_changes(
    git_project_root, monkeypatch
):
    session = ProjectSession.new()
    session.save_as(git_project_root)
    entered, release, blocking, drained = Event(), Event(), Event(), Event()
    observed = []

    def generate(_project, _root, *, current_revision, **_kwargs):
        entered.set()
        assert release.wait(5)
        observed.append(current_revision())

    monkeypatch.setattr("code_visualizer.application.session.generate_to_disk", generate)
    worker = Thread(target=session.generate)

    def block():
        blocking.set()
        session.block_storage("worktree replacement")
        drained.set()

    blocker = Thread(target=block)
    try:
        worker.start()
        assert entered.wait(5)
        blocker.start()
        assert blocking.wait(5)
        assert not drained.wait(0.05)
        release.set()
        worker.join(5)
        blocker.join(5)
        assert drained.is_set()
        assert observed == [-1]
    finally:
        release.set()
        worker.join(5)
        blocker.join(5)
        session.close()
