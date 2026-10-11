"""Recoverable Git freeze/run operations on the existing session and computation host."""

from __future__ import annotations

import json
from concurrent.futures import Future
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, cast

from code_visualizer.application.experiment_checkpoints import ResumeCheckpoint, bind_checkpoint
from code_visualizer.application.experiment_inputs import (
    INPUT_MANIFEST,
    MAX_SOURCE_BYTES,
    CapturedSource,
    SourceInput,
    capture_inputs,
    definition_state,
    read_sources,
    verify_sources,
)
from code_visualizer.application.git import (
    GitError,
    GitExpectedState,
    GitOperationResult,
    GitRepository,
    record_git_checkpoint,
)
from code_visualizer.application.messages import (
    CommandAccepted,
    CommandDeferred,
    CommandRejected,
    CommandResult,
)
from code_visualizer.application.retained_computation import RetainedComputation
from code_visualizer.application.session import ExperimentContext, ProjectSession
from code_visualizer.config import PRODUCT
from code_visualizer.domain.common import JsonValue, new_id
from code_visualizer.domain.computation import ComputationRequest, ComputationSession
from code_visualizer.domain.project import Project
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation import computation_request_from_data
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.experiment_store import ExperimentStore, RetainedAttempt, now
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resources import resource_from_data
from code_visualizer.persistence.store import JournalRecord, ProjectStore
from code_visualizer.persistence.values import array_data, object_data, text_data

if TYPE_CHECKING:
    from code_visualizer.application.git_service import GitProjectController


@dataclass(frozen=True, slots=True)
class FrozenRun:
    attempt: RetainedAttempt
    computation: ComputationSession
    editor: ProjectSession
    warning: str = ""


@dataclass(frozen=True, slots=True)
class ForkedEdit:
    editor: ProjectSession
    result: CommandResult
    variant_id: str
    recovery_required: str = ""


class GitExperiments:
    """Serialized by GitProjectController; call from a host worker, never a Qt slot."""

    def __init__(self, controller: GitProjectController) -> None:
        self.controller = controller
        self.repository = controller.session.git_repository()
        project = controller.session.authority.snapshot()
        key = sha256(project.id.encode("utf-8")).hexdigest()[:16]
        self.store = ExperimentStore(self.repository.common_directory / "cv-experiments" / key)
        self._pending: tuple[str, str] | None = None
        self.edits: dict[str, Future[ForkedEdit]] = {}
        self.inspections: list[ProjectSession] = []
        self._freezing = False

    @property
    def variant_id(self) -> str | None:
        context = self.controller.session.experiment_context
        return context.variant_id if context is not None else None

    @property
    def frozen_attempt(self) -> str | None:
        context = self.controller.session.experiment_context
        return context.attempt_id if context is not None else None

    @property
    def _expected(self) -> GitExpectedState | None:
        context = self.controller.session.experiment_context
        return context.expected if context is not None else None

    def restore_context(self) -> None:
        editor = self.controller.session
        if not editor.read_only:
            self._install_gate(editor)

    def recovery_report(self) -> tuple[dict[str, JsonValue], ...]:
        """Inspect publication boundaries; never automatically replay computation or edits."""
        reports: list[dict[str, JsonValue]] = []
        for path in sorted((self.store.root / "operations").glob("*.json")):
            operation = self.store.read("operations", path.stem)
            if operation.get("phase") in {"submitted", "published"} and not operation.get("error"):
                continue
            report: dict[str, JsonValue] = {
                "operation_id": path.stem,
                "phase": operation.get("phase"),
                "error": operation.get("error"),
                "commit": operation.get("commit"),
                "execution_replayed": False,
            }
            if operation.get("kind") == "freeze":
                try:
                    attempt = self.store.attempt(path.stem)
                    report.update(attempt_id=attempt.id, attempt_phase=attempt.phase)
                except FileNotFoundError:
                    report["attempt_phase"] = "not_admitted"
            else:
                variant_id = text_data(operation.get("variant_id"))
                try:
                    variant = self.store.read("variants", variant_id)
                    root = (
                        Path(text_data(variant["worktree"])) / text_data(variant["project_path"])
                    ).parent
                    records = ProjectStore(root).read_journal()
                    report["root"] = str(root)
                    report["command_in_native_journal"] = any(
                        item.operation_id == operation.get("command_id") for item in records
                    )
                except FileNotFoundError:
                    report["command_in_native_journal"] = False
            reports.append(report)
        return tuple(reports)

    def reopen_run(self, attempt_id: str) -> ProjectSession:
        """Historical browsing uses the ordinary loader and retained resource store."""
        attempt = self.verify_run(attempt_id)
        identity = new_id("inspection")
        worktree = self.store.root / "worktrees" / identity
        self.repository.inspect_input_worktree(worktree, attempt.commit)
        self.store.write(
            "variants",
            identity,
            {
                "version": 1,
                "id": identity,
                "branch": "",
                "worktree": str(worktree),
                "project_path": attempt.project_path,
                "base_commit": attempt.commit,
                "frozen_commit": attempt.commit,
                "attempt_id": attempt_id,
            },
        )
        editor = ProjectSession.open(
            (worktree / attempt.project_path).parent,
            read_only=True,
            computations=self.controller.session.kernel.computations,
            extensions=self.controller.session.kernel.host_extensions,
            retention_root=self.store.root,
        )
        if attempt.evidence_id:
            evidence = EvidenceStore(self.store.root).get(attempt.evidence_id)
            if evidence.provenance.input_digest != attempt.input_digest:
                editor.close()
                raise GitError("GIT_RUN_EVIDENCE", "Evidence belongs to another input")
            editor.kernel.runtime.record_evidence(attempt.id, evidence)
        self.inspections.append(editor)
        return editor

    def verify_run(self, attempt_id: str) -> RetainedAttempt:
        """Validate immutable Git/resource claims independently of editing labels."""
        attempt = self.store.attempt(attempt_id)
        if self.repository.resolve_ref(attempt.reference) != attempt.commit:
            raise GitError("GIT_RUN_REF_CHANGED", "The retained run reference no longer matches")
        source = json.loads(self.repository.read_input(attempt.commit, attempt.project_path))
        manifest = object_data(
            json.loads(self.repository.read_input(attempt.commit, INPUT_MANIFEST)),
            {
                "version",
                "project_path",
                "definition_digest",
                "request",
                "sources",
                "resources",
                "environment",
                "closure_digest",
                "source_digest",
            },
        )
        if (
            manifest.get("version") != 1
            or manifest.get("project_path") != attempt.project_path
            or manifest.get("source_digest") != attempt.source_digest
            or sha256(canonical_data_bytes(source)).hexdigest() != attempt.source_digest
            or manifest.get("definition_digest") != attempt.definition_digest
        ):
            raise GitError("GIT_RUN_INPUT", "Retained source claims do not match the input commit")
        closure = {
            key: value
            for key, value in manifest.items()
            if key not in {"closure_digest", "source_digest"}
        }
        request = computation_request_from_data(manifest["request"])
        from code_visualizer.persistence.computation import computation_request_to_data

        normalized = computation_request_to_data(request)
        normalized["revision"] = 0
        closure["request"] = normalized
        if (
            manifest.get("closure_digest") != attempt.closure_digest
            or sha256(canonical_data_bytes(cast(JsonValue, closure))).hexdigest()
            != attempt.closure_digest
        ):
            raise GitError("GIT_RUN_INPUT", "Retained closure claims changed")
        for raw in array_data(manifest["sources"]):
            item = object_data(raw, {"path", "destination", "sha256", "byte_size"})
            payload = self.repository.read_input(attempt.commit, text_data(item.get("path")))
            if len(payload) != item.get("byte_size") or sha256(payload).hexdigest() != item.get(
                "sha256"
            ):
                raise GitError("GIT_RUN_INPUT", "A captured source file changed")
        resources = ResourceStore(self.store.root)
        for raw in array_data(manifest["resources"]):
            descriptor = resource_from_data(raw)
            if resources.describe(descriptor.reference) != descriptor:
                raise GitError("GIT_RUN_INPUT", "An input resource descriptor changed")
            resources.verified_path(descriptor.reference)
        return attempt

    def remove_worktree(self, variant_id: str) -> None:
        variant = self.store.read("variants", variant_id)
        worktree = Path(str(variant["worktree"])).resolve()
        owned = (self.store.root / "worktrees" / variant_id).resolve()
        if worktree != owned or not worktree.is_relative_to(self.store.root / "worktrees"):
            raise GitError(
                "GIT_WORKTREE_OWNERSHIP", "Only registered owned worktrees can be removed"
            )
        project_root = (worktree / str(variant["project_path"])).parent
        active = self.controller.session
        if not active.closed and active.root == project_root:
            raise GitError(
                "GIT_WORKTREE_ACTIVE", "Detach the active editor before removing its worktree"
            )
        if any(not session.closed and session.root == project_root for session in self.inspections):
            raise GitError("GIT_WORKTREE_ACTIVE", "Close the historical inspector before removal")
        if not worktree.is_dir():
            raise GitError("GIT_WORKTREE_MISSING", "The registered worktree is already absent")
        from code_visualizer.persistence.lease import ProjectLease

        # A real native lease also catches editors owned by another process.
        lease = ProjectLease.acquire(project_root, owner_id="experiment-cleanup")
        try:
            repository = GitRepository(project_root)
            if (
                repository.root != worktree
                or repository.common_directory != self.repository.common_directory
            ):
                raise GitError(
                    "GIT_WORKTREE_OWNERSHIP", "The worktree no longer belongs to this repository"
                )
            status = repository.status()
            if status.files:
                raise GitError("GIT_WORKTREE_DIRTY", "Dirty experiment worktrees are never removed")
        finally:
            lease.release()
        exclude = self.store.root / "cleanup-exclude"
        prefix = str(variant["project_path"]).removesuffix("project.json")
        exclude.write_text(f"/{prefix}{PRODUCT.state_directory}/\n", encoding="utf-8")
        self.repository.remove_input_worktree(worktree, exclude)
        variant["removed"] = True
        self.store.write("variants", variant_id, variant)

    def _open_variant(
        self,
        variant_id: str,
        commit: str,
        original: ProjectSession,
        before: Project,
        sources: tuple[CapturedSource, ...],
    ) -> ProjectSession:
        repository = original.git_repository()
        worktree = self.store.root / "worktrees" / variant_id
        branch = f"experiment/{variant_id}"
        repository.add_input_worktree(worktree, branch, commit)
        self.store.write(
            "variants",
            variant_id,
            {
                "version": 1,
                "id": variant_id,
                "branch": branch,
                "worktree": str(worktree),
                "project_path": repository.project_path,
                "base_commit": commit,
                "frozen_commit": "",
                "attempt_id": "",
            },
        )
        # Explicitly carry history only from the captured predecessor, never a
        # journal encountered by branch checkout. The native checkpoint anchors it.
        assert original.root is not None
        records = ProjectStore(original.root).read_journal()
        if original.authority.snapshot() is not before:
            raise GitError("GIT_INPUT_CHANGED", "Fork predecessor changed while history was read")
        if records and records[-1].project != before:
            raise GitError(
                "GIT_HISTORY_CHANGED", "Local history does not match the fork predecessor"
            )
        store = ProjectStore(worktree / repository.prefix)
        # The Git base supplies history; the captured predecessor supplies the
        # entire current declared input, including accepted auxiliary file edits.
        for source in sources:
            target = worktree / source.definition.path
            if target.read_bytes() != source.content:
                store._atomic_write(
                    target, source.content.decode("utf-8"), max_bytes=MAX_SOURCE_BYTES
                )
        if store.load() != before:
            store.save(before)
        store.write_snapshot(before)
        for record in records:
            store.append(record)
        target_repository = GitRepository(store.root)
        record_git_checkpoint(target_repository, commit)
        return ProjectSession.open(
            store.root,
            actor_id=original.client.actor_id,
            computations=original.kernel.computations,
            retention_root=self.store.root,
            extensions=original.kernel.host_extensions,
        )

    def _arm(self, editor: ProjectSession, variant_id: str, attempt_id: str | None) -> None:
        context = ExperimentContext(
            variant_id, attempt_id, editor.git_repository().expected_state()
        )
        self._install_gate(editor)
        editor.experiment_context = context

    def _install_gate(self, editor: ProjectSession) -> None:
        editor.authority.set_commit_admission(
            lambda before, record: self._admit_edit(editor, before, record)
        )

    def _admit_edit(
        self, editor: ProjectSession, before: Project, record: JournalRecord
    ) -> CommandRejected | CommandDeferred | None:
        # Called under the authority lock: immutable comparison + enqueue only.
        if editor is not self.controller.session:
            return CommandRejected(
                "EXPERIMENT_SESSION_REPLACED",
                "Reconnect to the active experiment editor",
                before.revision,
                {},
            )
        if self._freezing:
            return CommandRejected(
                "EXPERIMENT_FREEZING",
                "Input capture is in progress; retry this edit",
                before.revision,
                {},
            )
        if self._pending is not None:
            identity, command_id = self._pending
            if command_id == record.operation_id:
                return CommandDeferred(
                    "EXPERIMENT_EDIT_PENDING",
                    "Preparing experiment branch",
                    before.revision,
                    {"operation_id": identity},
                )
            return CommandRejected(
                "EXPERIMENT_EDIT_PENDING",
                "Wait for the pending experiment edit",
                before.revision,
                {"operation_id": identity},
            )
        if self.frozen_attempt is None or definition_state(before) == definition_state(
            record.project
        ):
            return None
        identity = new_id("fork")
        self._pending = (identity, record.operation_id)
        self.edits[identity] = self.controller._background.submit(
            self._fork_edit, identity, before, record
        )
        return CommandDeferred(
            "EXPERIMENT_EDIT_PENDING",
            "Preparing experiment branch",
            before.revision,
            {"operation_id": identity},
        )

    def _fork_edit(self, identity: str, before: Project, record: JournalRecord) -> ForkedEdit:
        with self.controller._lock:
            original = self.controller.session
            variant_id = new_id("variant")
            editor: ProjectSession | None = None
            operation: dict[str, JsonValue] = {
                "version": 1,
                "id": identity,
                "kind": "fork",
                "variant_id": variant_id,
                "command_id": record.operation_id,
                "parent_attempt": self.frozen_attempt,
                "error": "",
            }
            accepted: CommandResult | None = None
            try:
                original.require_writable_storage()
                if original.authority.snapshot() is not before or self._expected is None:
                    raise GitError("GIT_INPUT_CHANGED", "Fork predecessor changed")
                repository = original.git_repository()
                repository.require_state(self._expected)
                assert self.frozen_attempt is not None
                parent = self.store.attempt(self.frozen_attempt)
                if repository.resolve_ref(parent.reference) != parent.commit:
                    raise GitError("GIT_RUN_REF_CHANGED", "Retained input reference changed")
                operation["commit"] = parent.commit
                self._phase(identity, operation, "planned")
                manifest = json.loads(repository.read_input(parent.commit, INPUT_MANIFEST))
                declarations = tuple(
                    SourceInput(text_data(item["path"]), text_data(item["destination"]))
                    for raw in array_data(manifest["sources"])
                    for item in [object_data(raw, {"path", "destination", "sha256", "byte_size"})]
                )
                sources = read_sources(repository, declarations)
                operation["sources"] = [
                    {"path": item.definition.path, "sha256": item.digest} for item in sources
                ]
                editor = self._open_variant(variant_id, parent.commit, original, before, sources)
                self._phase(identity, operation, "worktree_ready")
                repository.require_state(self._expected)
                verify_sources(repository, sources)
                verify_sources(editor.git_repository(), sources)
                original.require_writable_storage()
                if original.authority.snapshot() is not before:
                    raise GitError("GIT_INPUT_CHANGED", "Fork predecessor changed")
                accepted = editor.authority.apply_transferred(record, expected_project=before)
                if not isinstance(accepted, CommandAccepted):
                    raise GitError(accepted.code, accepted.message)
                self._phase(identity, operation, "edit_persisted")
                self._arm(editor, variant_id, None)
                repository.require_state(self._expected)
                verify_sources(repository, sources)
                verify_sources(editor.git_repository(), sources)
                # All fallible preparation precedes the single active-session
                # pointer change. Experiment policy belongs to that session.
                assert editor.experiment_context is not None
                editor.git_repository().require_state(editor.experiment_context.expected)
                self.controller.session = editor
                original.block_storage("Editing continued in a new experiment worktree")
                self._phase(identity, operation, "published")
                self.controller.prepare_review()
                self.controller.changed(
                    GitOperationResult(
                        "experiment.edit", str(editor.root), parent.commit, reload_required=True
                    )
                )
                return ForkedEdit(editor, accepted, variant_id)
            except Exception as exc:
                operation["error"] = str(exc)
                try:
                    self.store.write("operations", identity, operation)
                except Exception as metadata_error:
                    exc.add_note(f"Recovery metadata could not be written: {metadata_error}")
                try:
                    if editor is not None and self.controller.session is not editor:
                        editor.close()
                except Exception as close_error:
                    exc.add_note(f"Unpublished editor cleanup requires recovery: {close_error}")
                message = "\n".join((str(exc), *getattr(exc, "__notes__", ())))
                try:
                    self.controller.changed(GitOperationResult("experiment.error", message, ""))
                except Exception as notification_error:
                    message += f"\nError notification failed: {notification_error}"
                # A native journal already containing the command is recoverable;
                # it is never called an unaccepted edit simply because UI publication failed.
                if isinstance(accepted, CommandAccepted) and editor is not None:
                    return ForkedEdit(editor, accepted, variant_id, message)
                raise
            finally:
                self._pending = None

    def _phase(self, operation_id: str, data: dict[str, JsonValue], phase: str) -> None:
        data["phase"] = phase
        self.store.write("operations", operation_id, data)

    def freeze_and_run(
        self,
        request: ComputationRequest,
        *,
        sources: tuple[SourceInput, ...] = (),
        resume: ResumeCheckpoint | None = None,
    ) -> FrozenRun:
        original = self.controller.session
        original.require_writable_storage()
        repository = original.git_repository()
        expected = repository.expected_state()
        self._freezing = True
        self._install_gate(original)
        project = original.authority.snapshot()
        attempt_id = new_id("run")
        variant_id = self.variant_id or new_id("variant")
        operation: dict[str, JsonValue] = {
            "version": 1,
            "id": attempt_id,
            "kind": "freeze",
            "variant_id": variant_id,
            "expected": asdict(expected),
            "project_revision": project.revision,
            "commit": "",
            "error": "",
        }
        replacement: ProjectSession | None = None
        submitted: FrozenRun | None = None
        try:
            self._phase(attempt_id, operation, "planned")
            retained = ResourceStore(self.store.root)
            captured = capture_inputs(
                repository,
                project,
                request,
                sources,
                original.kernel.host_extensions,
                original.kernel.resource_store,
                retained,
            )
            request = captured.request
            compatibility_digest = captured.closure_digest
            if resume is not None:
                request = bind_checkpoint(
                    captured, resume, original.kernel.host_extensions, self.store
                )
                captured = capture_inputs(
                    repository,
                    project,
                    request,
                    sources,
                    original.kernel.host_extensions,
                    retained,
                    retained,
                )
                request = captured.request
            self._phase(attempt_id, operation, "inputs_retained")
            previous = self.store.attempt(self.frozen_attempt) if self.frozen_attempt else None
            create_variant = self.variant_id is None or (
                previous is not None and previous.closure_digest != captured.closure_digest
            )
            if create_variant and self.variant_id is not None:
                variant_id = new_id("variant")
                operation["variant_id"] = variant_id
            if previous is not None and previous.closure_digest == captured.closure_digest:
                commit = previous.commit
                project = project_from_json(
                    repository.read_input(commit, previous.project_path).decode("utf-8")
                )
                manifest = json.loads(repository.read_input(commit, INPUT_MANIFEST))
                request = computation_request_from_data(manifest["request"])
                source_digest = previous.source_digest
            else:
                commit = repository.input_commit(
                    captured.files, parent=previous.commit if previous else expected.head
                )
                source_digest = captured.source_digest
            operation["commit"] = commit
            self._phase(attempt_id, operation, "commit_created")
            repository.require_state(expected)
            verify_sources(repository, captured.sources)
            if original.authority.snapshot() is not captured.project or original.storage_problem():
                raise GitError("GIT_INPUT_CHANGED", "The accepted project changed during capture")
            if create_variant:
                replacement = self._open_variant(
                    variant_id, commit, original, captured.project, captured.sources
                )
            # Existing editing HEAD/index remain untouched, even in an owned
            # worktree. The retained run ref identifies this exact input commit;
            # the next fork starts there, independently of its editing branch tip.
            self._phase(attempt_id, operation, "worktree_ready")
            repository.require_state(expected)
            verify_sources(repository, captured.sources)
            reference = f"refs/code-visualizer/runs/{attempt_id}"
            repository.retain_ref(reference, commit)
            self._phase(attempt_id, operation, "run_retained")
            attempt = RetainedAttempt(
                attempt_id,
                commit,
                reference,
                variant_id,
                repository.project_path,
                source_digest,
                captured.closure_digest,
                captured.definition_digest,
                now(),
                parent_attempt=resume.attempt_id if resume else "",
                checkpoint_id=resume.publication_id if resume else "",
                compatibility_digest=compatibility_digest,
            )
            editor = replacement or original
            # Prepare fallible state while the temporary capture gate still
            # protects the editor. The durable attempt is the freeze binding;
            # subsequent status/cache failures cannot grant editing permission.
            context = ExperimentContext(
                variant_id, attempt_id, editor.git_repository().expected_state()
            )
            self._install_gate(editor)
            try:
                self.store.create_attempt(attempt)
            except Exception:
                editor.block_storage(
                    "Freeze binding could not be confirmed. Reopen to reconcile retained "
                    "attempts before accepting semantic edits; execution was not submitted"
                )
                raise
            editor.experiment_context = context
            self._phase(attempt_id, operation, "attempt_ready")
            repository.require_state(expected)
            verify_sources(repository, captured.sources)
            if original.authority.snapshot() is not captured.project or original.storage_problem():
                raise GitError(
                    "GIT_INPUT_CHANGED", "The accepted snapshot changed before admission"
                )
            adapter = RetainedComputation(
                attempt_id,
                repository,
                self.store,
            )
            computation = editor.kernel.computations.submit(
                editor.kernel.computation_attachment,
                project,
                request,
                editor.kernel.host_extensions,
                retained,
                EvidenceStore(self.store.root),
                retention=adapter,
            )
            submitted = FrozenRun(attempt, computation, editor)
            if replacement is not None:
                # Admission may take time. Validate an unpublished worktree
                # before handing it to the editor; its run is already protected
                # and recoverable even if the predecessor must remain active.
                editor.git_repository().require_state(context.expected)
            self.controller.session = editor
            if replacement is not None:
                original.block_storage("Editing continued in the captured experiment worktree")
            variant = self.store.read("variants", variant_id)
            variant.update(frozen_commit=commit, attempt_id=attempt_id)
            self.store.write("variants", variant_id, variant)
            self._phase(attempt_id, operation, "submitted")
            return submitted
        except Exception as exc:
            operation["error"] = str(exc)
            try:
                self.store.write("operations", attempt_id, operation)
            except Exception as metadata_error:
                # A previous durable phase still names every established input/ref.
                exc.add_note(f"Recovery metadata could not be written: {metadata_error}")
            if replacement is not None and self.controller.session is not replacement:
                try:
                    replacement.close()
                except Exception as close_error:
                    exc.add_note(f"Unpublished editor cleanup failed: {close_error}")
            if submitted is not None:
                message = "\n".join((str(exc), *getattr(exc, "__notes__", ())))
                return FrozenRun(
                    submitted.attempt,
                    submitted.computation,
                    submitted.editor,
                    f"Run was submitted; recover its metadata update: {message}",
                )
            raise
        finally:
            self._freezing = False
