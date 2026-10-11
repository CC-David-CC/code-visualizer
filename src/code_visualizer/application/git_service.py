"""Session-aware Git use cases shared by desktop and automation adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from threading import RLock
from typing import TYPE_CHECKING

from code_visualizer.application.git import (
    GitError,
    GitOperationResult,
    GitRepository,
    git_checkpoint,
)
from code_visualizer.domain.common import JsonValue

if TYPE_CHECKING:
    from code_visualizer.application.computation_service import ComputationService
    from code_visualizer.application.experiment_checkpoints import ResumeCheckpoint
    from code_visualizer.application.experiment_inputs import SourceInput
    from code_visualizer.application.git_experiments import FrozenRun, GitExperiments
    from code_visualizer.application.session import ProjectSession
    from code_visualizer.domain.computation import ComputationRequest

GIT_READ_METHODS = frozenset(
    {
        "status",
        "diff",
        "history",
        "branches",
        "remotes",
        "conflict",
        "commit_diff",
        "experiment_runs",
        "experiment_operation",
        "compare_runs",
        "experiment_checkpoints",
    }
)
GIT_WORKTREE_METHODS = frozenset(
    {"switch", "merge", "pull", "abort_merge", "resolve_conflict", "reload"}
)
GIT_WRITE_METHODS = frozenset(
    {
        "initialize",
        "stage",
        "unstage",
        "commit",
        "create_branch",
        "fetch",
        "push",
        "add_remote",
        "freeze_run",
        "resume_checkpoint",
        "reopen_run",
        "remove_experiment_worktree",
        "recover_experiments",
        *GIT_WORKTREE_METHODS,
    }
)


class GitProjectController:
    """Git changes files; the existing authority still owns all semantic commands."""

    def __init__(
        self,
        session: ProjectSession,
        *,
        changed: Callable[[GitOperationResult], None] | None = None,
    ) -> None:
        self.session = session
        self.changed = changed or (lambda _result: None)
        self._lock = RLock()
        self._experiments: GitExperiments | None = None
        self._background = ThreadPoolExecutor(max_workers=1, thread_name_prefix="git-experiment")
        self.prepared_review: dict[str, object] | None = None
        self._freezes: dict[str, Future[FrozenRun]] = {}
        self._owned_computations: ComputationService | None = None
        if session.experiment_context is not None:
            # The ordinary loader already resolved this context off the UI path.
            self.experiments.restore_context()

    @property
    def experiments(self) -> GitExperiments:
        if self._experiments is None:
            from code_visualizer.application.git_experiments import GitExperiments

            self._experiments = GitExperiments(self)
        return self._experiments

    def freeze_and_run(
        self,
        request: ComputationRequest,
        *,
        sources: tuple[SourceInput, ...] = (),
        resume: ResumeCheckpoint | None = None,
    ) -> FrozenRun:
        with self._lock:
            transferred = self.session.kernel.transfer_computation_ownership()
            if transferred is not None:
                self._owned_computations = transferred
                self.session.computations = transferred
            result = self.experiments.freeze_and_run(request, sources=sources, resume=resume)
            try:
                self.prepare_review()
            except (GitError, OSError):
                self.prepared_review = None  # Review failure cannot un-submit a durable run.
            return result

    def prepare_review(self) -> dict[str, object]:
        """Materialize Git review on the host worker before a GUI session handoff."""
        with self._lock:
            repository = self.session.git_repository()
            self.prepared_review = {
                "status": repository.status(),
                "history": repository.history(),
                "branches": repository.branches(),
                "remotes": repository.remotes(),
                "problem": self.session.storage_problem() or "",
                "runs": (
                    () if self._experiments is None else self.experiments.store.attempts()[-256:]
                ),
            }
            return self.prepared_review

    def submit_freeze_and_run(
        self,
        request: ComputationRequest,
        *,
        sources: tuple[SourceInput, ...] = (),
        resume: ResumeCheckpoint | None = None,
    ) -> Future[FrozenRun]:
        """Bounded GUI admission; Git/resource work uses the serialized host worker."""
        future = self._background.submit(
            self.freeze_and_run, request, sources=sources, resume=resume
        )

        def completed(result: Future[FrozenRun]) -> None:
            try:
                run = result.result()
                if run.editor.closed or self.session is not run.editor:
                    raise GitError("GIT_RUN_RECOVERY", run.warning or "Run requires recovery")
                event = GitOperationResult(
                    "experiment.freeze",
                    str(run.editor.root),
                    run.attempt.commit,
                    reload_required=True,
                )
            except Exception as exc:
                event = GitOperationResult("experiment.error", str(exc), "")
            self.changed(event)

        future.add_done_callback(completed)
        return future

    def close_background(self, *, wait: bool = False) -> None:
        if self._owned_computations is not None:
            self._background.submit(self._owned_computations.close)
            self._owned_computations = None
        self._background.shutdown(wait=wait, cancel_futures=False)

    @staticmethod
    def _text(params: Mapping[str, object], key: str, *, empty: bool = False) -> str:
        value = params.get(key)
        if not isinstance(value, str) or (not empty and not value):
            raise GitError("GIT_PARAMS", f"{key} must be {'text' if empty else 'non-empty text'}")
        return value

    def execute(self, method: str, params: Mapping[str, object]) -> object:
        with self._lock:
            return self._execute(method.removeprefix("git."), params)

    def _execute(self, method: str, params: Mapping[str, object]) -> object:
        if method not in GIT_READ_METHODS | GIT_WRITE_METHODS:
            raise GitError("GIT_METHOD", f"Unknown Git operation {method!r}")
        if self.session.closed and method in GIT_WRITE_METHODS:
            raise GitError("GIT_SESSION_CLOSED", "Reconnect to the current project session")
        root = self.session.root
        if root is None:
            raise GitError("GIT_SAVE_REQUIRED", "Save this project before using Git")
        if method == "experiment_checkpoints":
            from code_visualizer.application.checkpoint_selection import checkpoint_choices

            return {
                "checkpoints": checkpoint_choices(
                    self.experiments, self._text(params, "attempt_id")
                )
            }
        if method == "resume_checkpoint":
            from code_visualizer.application.checkpoint_selection import checkpoint_request
            from code_visualizer.application.experiment_checkpoints import ResumeCheckpoint
            from code_visualizer.persistence.computation import computation_request_to_data

            resume_choice = ResumeCheckpoint(
                self._text(params, "attempt_id"), self._text(params, "publication_id")
            )
            resume_request, resume_sources = checkpoint_request(self.experiments, resume_choice)
            method = "freeze_run"
            params = {
                "request": computation_request_to_data(resume_request),
                "sources": [
                    {"path": source.path, "destination": source.destination}
                    for source in resume_sources
                ],
                "resume": {
                    "attempt_id": resume_choice.attempt_id,
                    "publication_id": resume_choice.publication_id,
                },
            }
        if method == "freeze_run":
            from code_visualizer.application.experiment_checkpoints import ResumeCheckpoint
            from code_visualizer.application.experiment_inputs import SourceInput
            from code_visualizer.domain.common import new_id
            from code_visualizer.persistence.computation import computation_request_from_data

            request = computation_request_from_data(params.get("request"))
            values = params.get("sources", [])
            if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
                raise GitError(
                    "GIT_PARAMS", "sources must contain explicit path/destination records"
                )
            sources = tuple(
                SourceInput(self._text(item, "path"), self._text(item, "destination"))
                for item in values
            )
            resume = None
            raw_resume = params.get("resume")
            if raw_resume is not None:
                if not isinstance(raw_resume, dict):
                    raise GitError("GIT_PARAMS", "resume must identify a retained checkpoint")
                resume = ResumeCheckpoint(
                    self._text(raw_resume, "attempt_id"), self._text(raw_resume, "publication_id")
                )
            identity = new_id("freeze")
            self._freezes[identity] = self.submit_freeze_and_run(
                request, sources=sources, resume=resume
            )
            return {"status": "pending", "operation_id": identity}
        if method == "experiment_operation":
            return self.experiment_operation(self._text(params, "operation_id"))
        if method == "experiment_runs":
            from dataclasses import asdict

            return tuple(asdict(item) for item in self.experiments.store.attempts())
        if method == "compare_runs":
            from code_visualizer.application.experiment_comparison import compare_retained_runs

            return compare_retained_runs(
                self.experiments, self._text(params, "left_id"), self._text(params, "right_id")
            )
        if method == "reopen_run":
            editor = self.experiments.reopen_run(self._text(params, "attempt_id"))
            self.session = editor
            self.prepare_review()
            result = GitOperationResult(
                "experiment.reopen",
                str(editor.root),
                editor.git_repository().head(),
                reload_required=True,
            )
            self.changed(result)
            return result
        if method == "remove_experiment_worktree":
            self.experiments.remove_worktree(self._text(params, "variant_id"))
            return {"removed": True}
        if method == "recover_experiments":
            active = frozenset(
                item.session.id
                for item in self.session.kernel.computations.attempts()
                if item.phase != "finished"
            )
            return {
                "interrupted": list(self.experiments.store.interrupted(active)),
                "operations": self.experiments.recovery_report(),
            }
        if method == "initialize":
            self.session.require_writable_storage()
            repository = GitRepository.initialize(root)
            git_checkpoint(repository)
            self.session.acknowledge_storage(repository=repository)
            return repository.status()
        repository = self.session.git_repository()
        if method in {"status", "branches", "remotes"}:
            return getattr(repository, method)()
        if method == "history":
            limit = params.get("limit", 50)
            if not isinstance(limit, int) or isinstance(limit, bool):
                raise GitError("GIT_PARAMS", "limit must be an integer")
            return repository.history(limit=limit)
        if method == "diff":
            staged = params.get("staged", False)
            if not isinstance(staged, bool):
                raise GitError("GIT_PARAMS", "staged must be a boolean")
            return repository.diff(self._text(params, "path"), staged=staged)
        if method == "conflict":
            return repository.conflict(self._text(params, "path"))
        if method == "commit_diff":
            return repository.commit_diff(self._text(params, "oid"))
        if self.session.read_only:
            raise GitError("GIT_READ_ONLY", "Git writes require an editable project session")
        if method == "reload":
            repository.load_project()
            result = GitOperationResult(
                "reload",
                "Validated Git working tree ready to reload",
                repository.head(),
                reload_required=True,
            )
            self.session.block_storage("Reloading the Git working tree")
            self.changed(result)
            return result
        if method not in {
            "abort_merge",
            "resolve_conflict",
            "stage",
            "unstage",
            "commit",
            "fetch",
            "push",
        }:
            self.session.require_writable_storage()
        if method not in {"fetch", "push"}:
            repository.ensure_head(self._text(params, "expected_head", empty=True))
        if method in {"switch", "merge", "pull"}:
            self.session.block_storage(
                "Git is changing the working tree. Validate and reload before editing."
            )
            repository.require_saved(self.session.authority.snapshot())
            repository.ensure_clean()
        if method in {"stage", "unstage"}:
            paths = params.get("paths")
            if not isinstance(paths, (tuple, list)) or not all(
                isinstance(item, str) for item in paths
            ):
                raise GitError("GIT_PARAMS", "paths must be a list of project-relative file paths")
            result = getattr(repository, method)(tuple(paths))
        elif method == "commit":
            result = repository.commit(
                self._text(params, "message"), expected_index=self._text(params, "expected_index")
            )
            if (
                self.session.storage_problem() is None
                or repository.load_project() == self.session.authority.snapshot()
            ):
                git_checkpoint(repository)
                self.session.acknowledge_storage()
        elif method in {"switch", "merge", "create_branch"}:
            result = getattr(repository, method)(self._text(params, "branch"))
        elif method == "abort_merge":
            self.session.block_storage("Git is aborting this merge. Reload before editing.")
            result = repository.abort_merge()
        elif method == "resolve_conflict":
            self.session.block_storage(
                "Git conflict resolution is being reviewed. Reload before editing."
            )
            raw_text = params.get("text")
            if raw_text is not None and not isinstance(raw_text, str):
                raise GitError("GIT_PARAMS", "text must be a string")
            result = repository.resolve_conflict(
                self._text(params, "path"), self._text(params, "choice"), text=raw_text
            )
        elif method == "fetch":
            result = repository.fetch(self._text(params, "remote"))
        elif method == "add_remote":
            result = repository.add_remote(self._text(params, "name"), self._text(params, "url"))
        elif method in {"pull", "push"}:
            result = getattr(repository, method)(
                self._text(params, "remote"), self._text(params, "branch")
            )
        else:
            raise GitError("GIT_METHOD", method)
        self.changed(result)
        return result

    def reload_session(self) -> ProjectSession:
        with self._lock:
            self.session = self.session.reload_from_git()
            self._experiments = None
            if self.session.experiment_context is not None:
                self.experiments.restore_context()
            return self.session

    def experiment_operation(self, identity: str) -> dict[str, JsonValue]:
        from code_visualizer.application.messages import CommandAccepted

        if identity in self._freezes:
            future = self._freezes[identity]
            if not future.done():
                return {"status": "pending", "operation_id": identity}
            try:
                run = future.result()
                return {
                    "status": "submitted",
                    "attempt_id": run.attempt.id,
                    "commit": run.attempt.commit,
                    "root": str(run.editor.root),
                    "warning": run.warning,
                }
            except Exception as exc:
                return {"status": "failed", "message": str(exc)}
        edit = self.experiments.edits.get(identity)
        if edit is None:
            raise GitError("GIT_OPERATION_UNKNOWN", "No operation has that identity")
        if not edit.done():
            return {"status": "pending", "operation_id": identity}
        try:
            result = edit.result()
            command = result.result
            if not isinstance(command, CommandAccepted):
                return {"status": "failed", "message": command.message}
            return {
                "status": "recovery_required" if result.recovery_required else "completed",
                "operation_id": identity,
                "variant_id": result.variant_id,
                "message": result.recovery_required,
                "root": str(result.editor.root),
                "revision": command.revision,
                "affected_ids": list(command.affected_ids),
                "command_operation_id": command.undo_group_id,
            }
        except Exception as exc:
            return {"status": "failed", "message": str(exc)}
