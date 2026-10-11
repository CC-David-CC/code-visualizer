"""Git-resolved layout remains correct across worktrees and fresh state changes."""

import hashlib
import shutil
from pathlib import Path

import pytest
from test_git_experiments import git

from code_visualizer.application.git import GitError, GitRepository

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="Real Git is required")


@pytest.mark.parametrize("layout", ("nested", "linked", "separate"))
def test_discovered_layout_preserves_live_head_branch_and_physical_index(tmp_path, layout):
    root = tmp_path / "repository"
    root.mkdir()
    if layout == "separate":
        git(root, "init", "--separate-git-dir", str(tmp_path / "metadata"))
    else:
        git(root, "init")
    git(root, "config", "user.name", "Layout proof")
    git(root, "config", "user.email", "layout@example.invalid")
    (root / "content.txt").write_text("initial", encoding="utf-8")
    git(root, "add", "content.txt")
    git(root, "commit", "-m", "Initial")
    original = GitRepository(root)
    original_state = original.expected_state()
    if layout == "linked":
        working = tmp_path / "linked"
        git(root, "worktree", "add", "-b", "linked-proof", str(working))
    else:
        working = root
    nested = working / "nested project"
    nested.mkdir()
    repository = GitRepository(nested)
    assert repository.root == working
    assert repository.prefix == "nested project"
    assert repository.common_directory == original.common_directory
    before = repository.expected_state()
    assert before.head == git(working, "rev-parse", "HEAD")
    assert before.symbolic_head == git(working, "symbolic-ref", "HEAD")
    index = Path(git(working, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    assert before.index_digest == hashlib.sha256(index.read_bytes()).hexdigest()

    # Same commit, different branch: admission must still detect the change.
    git(working, "switch", "-c", "another-branch")
    switched = repository.expected_state()
    assert switched.head == before.head
    assert switched.symbolic_head != before.symbolic_head
    with pytest.raises(GitError, match="HEAD or index changed"):
        repository.require_state(before)

    (working / "content.txt").write_text("externally staged", encoding="utf-8")
    git(working, "add", "content.txt")
    staged = repository.expected_state()
    assert staged.head == switched.head and staged.index_digest != switched.index_digest
    with pytest.raises(GitError, match="HEAD or index changed"):
        repository.require_state(switched)
    git(working, "commit", "-m", "External commit")
    assert repository.expected_state().head != staged.head
    git(working, "switch", "--detach")
    assert repository.expected_state().symbolic_head == ""
    if layout == "linked":
        assert original.expected_state() == original_state


def test_unborn_repository_state_observes_first_index_and_commit(tmp_path):
    git(tmp_path, "init")
    repository = GitRepository(tmp_path)
    unborn = repository.expected_state()
    assert unborn.head == "" and unborn.symbolic_head.startswith("refs/heads/")
    assert unborn.index_digest == hashlib.sha256(b"").hexdigest()
    (tmp_path / "source.txt").write_text("source", encoding="utf-8")
    git(tmp_path, "add", "source.txt")
    assert repository.expected_state().index_digest != unborn.index_digest
    git(
        tmp_path,
        "-c",
        "user.name=Layout proof",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "First commit",
    )
    assert repository.expected_state().head
