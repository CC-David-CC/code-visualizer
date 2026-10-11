"""Project-session lifecycle shared by the desktop composition root."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.capabilities import CapabilityDescriptor, CapabilityKind
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.git import (
    GitError,
    GitExpectedState,
    GitRepository,
    archive_git_recovery,
    first_untracked_adoption,
    git_checkpoint,
    has_git_ancestor,
    record_git_checkpoint,
)
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.execution import DebugLaunch, DebugSession, run_source
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation import GenerationResult, generate_to_disk
from code_visualizer.persistence import ProjectLease, ProjectStore
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.invocation import invocation_from_data
from code_visualizer.persistence.project_resources import copy_project_resources
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.rendering import export_document, layout_drakon
from code_visualizer.sdk import CodeVisualizerClient


@dataclass(frozen=True, slots=True)
class ExperimentContext:
    """One editor's Git admission policy, prepared before session publication."""

    variant_id: str
    attempt_id: str | None
    expected: GitExpectedState


@dataclass(slots=True)
class ProjectSession:
    authority: ProjectAuthority
    client: CodeVisualizerClient
    root: Path | None
    initial_revision: int
    lease: ProjectLease | None = None
    read_only: bool = False
    computations: ComputationService | None = field(default=None, kw_only=True, repr=False)
    retention_root: Path | None = field(default=None, kw_only=True, repr=False)
    extensions: DomainExtensionRegistry | None = field(default=None, kw_only=True, repr=False)
    experiment_context: ExperimentContext | None = field(default=None, init=False, repr=False)
    kernel: ProjectKernel = field(init=False)
    _git_head: str | None = field(default=None, init=False)
    _git_repository: GitRepository | None = field(default=None, kw_only=True, repr=False)
    _git_token: tuple[bytes, bytes, int, int] | None = field(default=None, init=False)
    _blocked_reason: str | None = field(default=None, init=False)
    _saved_stamp: tuple[int, int] | None = field(default=None, init=False)
    _checkpoint_revision: int | None = field(default=None, init=False)
    _storage_unsubscribe: Callable[[], None] | None = field(default=None, init=False)
    closed: bool = field(default=False, init=False)
    _publication_lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.acknowledge_storage()
        repository = self._git_repository
        if repository is not None:
            worktree = repository.root
            retained = worktree.parent.parent
            if (
                worktree.parent.name == "worktrees"
                and retained.parent == repository.common_directory / "cv-experiments"
            ):
                from code_visualizer.application.experiment_recovery import (
                    frozen_session_admission,
                    recover_frozen_attempt,
                )
                from code_visualizer.persistence.experiment_store import ExperimentStore

                experiments = ExperimentStore(retained)
                try:
                    marker = experiments.read("variants", worktree.name)
                except (OSError, ValueError) as exc:
                    raise GitError(
                        "GIT_EXPERIMENT_RECOVERY",
                        f"Restore ownership marker for variant {worktree.name} in {retained} "
                        "before reopening; frozen status cannot be inferred without ownership",
                    ) from exc
                if (
                    marker.get("worktree") != str(worktree)
                    or marker.get("project_path") != repository.project_path
                ):
                    raise GitError("GIT_WORKTREE_OWNERSHIP", "Experiment worktree identity changed")
                self.retention_root = retained
                self.experiment_context = ExperimentContext(
                    worktree.name,
                    recover_frozen_attempt(
                        repository,
                        experiments,
                        marker,
                        self.authority.snapshot(),
                        read_only=self.read_only,
                    ),
                    repository.expected_state(),
                )
                if self.experiment_context.attempt_id is not None:
                    self.authority.set_commit_admission(frozen_session_admission)
        self.authority.set_write_guard(self.storage_problem)
        self._storage_unsubscribe = self.authority.subscribe(lambda _event: self._capture_stamp())
        self.kernel = ProjectKernel(
            self.authority,
            extensions=self.extensions,
            computations=self.computations,
            resource_store=None
            if self.root is None
            else ResourceStore(self.retention_root or self.root),
            evidence_store=None
            if self.root is None
            else EvidenceStore(self.retention_root or self.root),
        )
        self.kernel.capabilities.register(
            CapabilityDescriptor(
                "python.generator",
                "Generate Python project",
                CapabilityKind.GENERATOR,
                "Lower the current semantic revision and atomically write owned artifacts.",
                {"type": "object"},
                {"type": "object"},
            ),
            lambda _inputs: self.generate(),
        )
        self.kernel.capabilities.register(
            CapabilityDescriptor(
                "layout.drakon",
                "Calculate DRAKON layout",
                CapabilityKind.LAYOUT,
                "Build a disposable vector scene for one semantic diagram revision.",
                {"required": ["diagram_id"], "type": "object"},
                {"type": "object"},
            ),
            self._layout_capability,
        )
        self.kernel.capabilities.register(
            CapabilityDescriptor(
                "export.svg",
                "Export visual document",
                CapabilityKind.EXPORT,
                "Render one document to an explicitly supplied output path.",
                {"required": ["document_id", "path"], "type": "object"},
                {"type": "object"},
            ),
            self._export_capability,
        )
        self.kernel.capabilities.register(
            CapabilityDescriptor(
                "execution.run",
                "Run Python snapshot",
                CapabilityKind.EXECUTION,
                "Execute an explicit in-memory Python snapshot in a bounded child process.",
                {"required": ["source", "invocation"], "type": "object"},
                {"type": "object"},
            ),
            self._run_capability,
        )
        self.kernel.capabilities.register(
            CapabilityDescriptor(
                "execution.debugger",
                "Start interactive debugger",
                CapabilityKind.EXECUTION,
                "Start a revision-pinned isolated debugger session.",
                {"required": ["source", "invocation"], "type": "object"},
                {"type": "object"},
            ),
            self._debugger_capability,
        )

    @staticmethod
    def _required_text(inputs: Mapping[str, object], key: str) -> str:
        value = inputs.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Capability input {key!r} must be non-empty text")
        return value

    def _layout_capability(self, inputs: Mapping[str, object]) -> object:
        diagram_id = self._required_text(inputs, "diagram_id")
        diagram = next(
            (
                item
                for item in self.authority.snapshot().documents
                if isinstance(item, DrakonDiagram) and item.id == diagram_id
            ),
            None,
        )
        if diagram is None:
            raise ValueError(f"DRAKON diagram {diagram_id!r} does not exist")
        return layout_drakon(diagram)

    def _export_capability(self, inputs: Mapping[str, object]) -> object:
        document_id = self._required_text(inputs, "document_id")
        output_path = Path(self._required_text(inputs, "path"))
        document = next(
            (item for item in self.authority.snapshot().documents if item.id == document_id),
            None,
        )
        if document is None:
            raise ValueError(f"Document {document_id!r} does not exist")
        return export_document(document, output_path)

    def _run_capability(self, inputs: Mapping[str, object]) -> object:
        source = self._required_text(inputs, "source")
        invocation = invocation_from_data(inputs.get("invocation"))
        return run_source(source, invocation=invocation)

    def _debugger_capability(self, inputs: Mapping[str, object]) -> object:
        source = self._required_text(inputs, "source")
        invocation = invocation_from_data(inputs.get("invocation"))
        revision = self.authority.revision
        session = DebugSession()
        session.start(
            DebugLaunch(
                source,
                invocation,
                project_revision=revision,
                artifact_revision=revision,
            )
        )
        return session

    @classmethod
    def new(
        cls, *, actor_id: str = "desktop", computations: ComputationService | None = None
    ) -> ProjectSession:
        authority = ProjectAuthority(create_default_project())
        return cls(
            authority=authority,
            client=CodeVisualizerClient(authority, actor_id=actor_id),
            root=None,
            initial_revision=authority.revision,
            computations=computations,
        )

    @classmethod
    def open(
        cls,
        root: Path,
        *,
        actor_id: str = "desktop",
        read_only: bool = False,
        computations: ComputationService | None = None,
        retention_root: Path | None = None,
        extensions: DomainExtensionRegistry | None = None,
    ) -> ProjectSession:
        store = ProjectStore(root)
        lease = None if read_only else ProjectLease.acquire(store.root, owner_id=actor_id)
        repository: GitRepository | None = None
        try:
            if has_git_ancestor(store.root):
                repository = GitRepository(store.root)
                ordinary_recovery = first_untracked_adoption(repository)
                if not ordinary_recovery:
                    repository.load_project()
                if not read_only:
                    git_checkpoint(repository, prepare=True)
                else:
                    # Read-only browsing must never promote another branch's recovery journal.
                    project = (
                        store.recover(promote=False)
                        if ordinary_recovery
                        else repository.load_project()
                    )
                    authority = ProjectAuthority(project, read_only=True)
                    return cls(
                        authority,
                        CodeVisualizerClient(authority, actor_id=actor_id),
                        store.root,
                        project.revision,
                        read_only=True,
                        _git_repository=repository,
                        computations=computations,
                        retention_root=retention_root,
                        extensions=extensions,
                    )
            project = store.recover(promote=not read_only)
            authority = ProjectAuthority(project, store=store, read_only=read_only)
            return cls(
                authority=authority,
                client=CodeVisualizerClient(authority, actor_id=actor_id),
                root=store.root,
                initial_revision=project.revision,
                lease=lease,
                read_only=read_only,
                _git_repository=repository,
                computations=computations,
                retention_root=retention_root,
                extensions=extensions,
            )
        except BaseException:
            if lease is not None:
                lease.release()
            raise

    @property
    def is_unsaved(self) -> bool:
        return self.root is None

    @property
    def is_dirty(self) -> bool:
        return self.root is None and self.authority.revision != self.initial_revision

    def save_as(self, root: Path) -> Path:
        self.require_writable_storage()
        if self.read_only:
            raise RuntimeError("A read-only project must be saved as an explicit editable copy")
        resolved = root.resolve()
        if self.root is not None and self.root != resolved:
            raise RuntimeError("Use an explicit project move/copy workflow for a saved project")
        if self.root is None:
            project = self.authority.snapshot()
            store = ProjectStore(resolved)
            lease = ProjectLease.acquire(resolved, owner_id=self.client.actor_id)
            try:
                store.initialize(project)
            except BaseException:
                lease.release()
                raise
            self.authority.attach_store(store)
            self.root = resolved
            self.kernel.resource_store = ResourceStore(resolved)
            self.kernel.evidence_store = EvidenceStore(resolved)
            self.lease = lease
            self.acknowledge_storage()
            if project.title == "Untitled Project":
                result = self.client.rename_project(resolved.name)
                if not hasattr(result, "revision"):
                    raise RuntimeError("Could not adopt the project-folder title")
                project = self.authority.snapshot()
            self.initial_revision = project.revision
        else:
            if not self.authority.checkpoint(self.authority.revision):
                raise GitError(
                    "PROJECT_STORAGE_CHANGED", "The saved revision changed before checkpoint"
                )
        self.acknowledge_storage()
        return resolved

    def generate(
        self,
        *,
        revision_provider: Callable[[], int] | None = None,
    ) -> GenerationResult:
        with self._publication_lock:
            return self._generate(revision_provider=revision_provider)

    def _generate(self, *, revision_provider: Callable[[], int] | None) -> GenerationResult:
        self.require_writable_storage()
        if self.read_only:
            raise RuntimeError("Read-only projects cannot generate into their owned folder")
        if self.root is None:
            raise RuntimeError("Save the project before generating to disk")
        snapshot = self.authority.snapshot()
        provider = revision_provider or (lambda: self.authority.revision)
        return generate_to_disk(
            snapshot,
            self.root,
            current_revision=lambda: provider() if self.storage_problem() is None else -1,
            extensions=self.kernel.extensions,
        )

    def autosave(self, revision: int) -> bool:
        """Publish the native checkpoint and Git recovery marker as one owned write."""

        with self._publication_lock:
            if self.root is None or self.authority.revision != revision:
                return False
            if self.read_only:
                return False
            if self.storage_problem() is not None:
                return False
            if not self.authority.checkpoint(revision):
                return False
            self._capture_stamp()
            return self.authority.revision == revision

    def _capture_stamp(self) -> None:
        if self.root is None:
            self._saved_stamp = None
            return
        try:
            value = (self.root / "project.json").stat()
            previous_stamp = self._saved_stamp
            self._saved_stamp = (value.st_mtime_ns, value.st_size)
            if (
                (
                    self._saved_stamp != previous_stamp
                    or self._checkpoint_revision != self.authority.revision
                )
                and not self.read_only
                and self._git_repository is not None
                and self._git_head is not None
            ):
                record_git_checkpoint(self._git_repository, self._git_head)
                self._checkpoint_revision = self.authority.revision
        except OSError:
            self._saved_stamp = None

    def git_repository(self) -> GitRepository:
        """Reuse repository discovery for this session, never its changing Git state."""
        if self.root is None:
            raise GitError("GIT_SAVE_REQUIRED", "Save this project before using Git")
        if self._git_repository is None or self._git_repository.project_root != self.root.resolve():
            self._git_repository = GitRepository(self.root)
        return self._git_repository

    def acknowledge_storage(self, *, repository: GitRepository | None = None) -> None:
        """Called only after this host's successful save or index-only Git commit."""
        if repository is not None:
            if self.root is None or repository.project_root != self.root.resolve():
                raise GitError("GIT_SCOPE", "Git repository belongs to another project")
            self._git_repository = repository
        if self.root is not None and has_git_ancestor(self.root):
            current_repository = self.git_repository()
            self._git_head = current_repository.head()
            self._git_token = current_repository.head_token()
        else:
            self._git_head = None
            self._git_repository = None
            self._git_token = None
        self._capture_stamp()

    def storage_problem(self) -> str | None:
        if self._blocked_reason is not None:
            return self._blocked_reason
        if self.root is None:
            return None
        if self._git_repository is not None:
            try:
                token = self._git_repository.head_token()
                if token != self._git_token:
                    if self._git_repository.head() != self._git_head:
                        return (
                            "Git HEAD changed outside this session. Reload from Git before editing."
                        )
                    self._git_token = token
            except (GitError, OSError) as exc:
                return str(exc)
        try:
            value = (self.root / "project.json").stat()
            stamp = (value.st_mtime_ns, value.st_size)
        except OSError:
            return "The saved project moved or disappeared. Reload before editing."
        if self._saved_stamp != stamp:
            return "project.json changed outside this authority. Reload before editing or saving."
        return None

    def require_writable_storage(self) -> None:
        if self.read_only:
            raise RuntimeError("This project is read-only")
        if (problem := self.storage_problem()) is not None:
            raise GitError("PROJECT_STORAGE_CHANGED", problem)

    def block_storage(self, reason: str) -> None:
        self._blocked_reason = reason
        # Wait for an already-entered semantic commit/checkpoint to finish before Git writes.
        self.authority.set_write_guard(self.storage_problem)
        # Drain complete owned publications, including autosave's Git recovery marker,
        # before Git changes files or close releases the lease. Generation also observes
        # the blocked revision before publishing its derived artifacts.
        with self._publication_lock:
            pass

    def reload_from_git(self) -> ProjectSession:
        """Admit a validated Git result through a fresh ordinary project session."""
        if self.root is None or self.read_only:
            raise GitError("GIT_SAVE_REQUIRED", "Open an editable saved project first")
        self.block_storage(
            "Git changed this working tree. Reload its validated project to continue."
        )
        repository = GitRepository(self.root)
        repository.load_project()
        archive_git_recovery(repository)
        git_checkpoint(repository)
        root, actor = self.root, self.client.actor_id
        self.close()
        return type(self).open(
            root, actor_id=actor, computations=self.computations, extensions=self.extensions
        )

    def save_recovery_copy(self, root: Path) -> Path:
        """Write an independent exact snapshot without changing session ownership."""

        destination = root.resolve()
        if self.root == destination:
            raise RuntimeError("A recovery copy must use a separate project directory")
        store = ProjectStore(destination)
        if store.project_file.exists():
            raise FileExistsError(f"Project already exists at {store.project_file}")
        project = self.authority.snapshot()
        resource_store = self.kernel.resource_store
        copy_project_resources(
            project,
            self.kernel.resource_store,
            self.kernel.evidence_store,
            destination,
            resolve_closure=(
                lambda references: self.kernel.host_extensions.resource_closure(
                    references, resource_store
                )
            )
            if resource_store is not None
            else None,
        )
        store.initialize(project)
        return store.root

    def close(self) -> None:
        self.closed = True
        self.block_storage("This project session is closed")
        if self._storage_unsubscribe is not None:
            self._storage_unsubscribe()
            self._storage_unsubscribe = None
        self.kernel.close()
        self.client.close()
        if self.lease is not None:
            self.lease.release()
            self.lease = None

    def update_authority_endpoint(self, endpoint: str | None) -> None:
        if self.lease is not None:
            self.lease.update_endpoint(endpoint)
