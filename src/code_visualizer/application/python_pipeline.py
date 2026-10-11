"""Revision-aware autosave, validation, and artifact-generation coordinator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from code_visualizer.application.session import ProjectSession
from code_visualizer.generation import (
    GenerationResult,
    inspect_generation,
    load_generation_manifest,
)
from code_visualizer.generation.artifacts import StaleGenerationError
from code_visualizer.validation import (
    BuildabilityStatus,
    Diagnostic,
    Severity,
    assess_project,
    validate_project,
)


class ScheduledCall(Protocol):
    def cancel(self) -> None: ...


class Scheduler(Protocol):
    def call_later(self, delay_ms: int, callback: Callable[[], None]) -> ScheduledCall: ...


class PipelineState(StrEnum):
    UNSAVED = "unsaved"
    PENDING = "pending"
    VALIDATING = "validating"
    VALIDATED = "validated"
    BLOCKED = "blocked"
    GENERATING = "generating"
    UP_TO_DATE = "up_to_date"
    FAILED = "failed"
    STALE_OUTPUT = "stale_output"


@dataclass(frozen=True, slots=True)
class PipelineStatus:
    state: PipelineState
    revision: int
    diagnostics: tuple[Diagnostic, ...] = ()
    result: GenerationResult | None = None
    message: str = ""
    artifact_revision: int | None = None

    @property
    def buildability(self) -> BuildabilityStatus:
        return (
            BuildabilityStatus.BLOCKED
            if any(item.severity is Severity.ERROR for item in self.diagnostics)
            else BuildabilityStatus.BUILDABLE
        )


StatusListener = Callable[[PipelineStatus], None]


class DebouncedPythonPipeline:
    """Coalesces rapid edits and promotes only the latest durable valid revision."""

    def __init__(
        self,
        scheduler: Scheduler,
        *,
        debounce_ms: int = 750,
        listener: StatusListener | None = None,
    ) -> None:
        if debounce_ms < 0:
            raise ValueError("debounce_ms must not be negative")
        self._scheduler = scheduler
        self._debounce_ms = debounce_ms
        self._listener = listener or (lambda _status: None)
        self._session: ProjectSession | None = None
        self._scheduled: ScheduledCall | None = None
        self._status = PipelineStatus(PipelineState.UNSAVED, 0)

    @property
    def status(self) -> PipelineStatus:
        return self._status

    def attach(self, session: ProjectSession | None) -> None:
        self.cancel()
        self._session = session
        if session is None:
            self._publish(PipelineStatus(PipelineState.UNSAVED, 0, message="No project open"))
            return
        project = session.authority.snapshot()
        if session.root is None:
            self._publish(
                PipelineStatus(
                    PipelineState.UNSAVED,
                    project.revision,
                    validate_project(project),
                    message="Save and Generate to create project artifacts",
                )
            )
            return
        manifest = load_generation_manifest(session.root)
        manifest_revision = manifest.get("revision") if manifest is not None else None
        artifact_revision = manifest_revision if isinstance(manifest_revision, int) else None
        inspection = inspect_generation(
            session.root,
            current_revision=project.revision,
        )
        if inspection.externally_changed:
            changed = (
                len(inspection.missing) + len(inspection.modified) + len(inspection.unexpected)
            )
            self._publish(
                PipelineStatus(
                    PipelineState.STALE_OUTPUT,
                    project.revision,
                    validate_project(project),
                    message=(
                        f"Generated artifacts changed outside Code Visualizer ({changed} file"
                        f"{'s' if changed != 1 else ''}); inspect the diff and explicitly "
                        "Generate Project to replace them"
                    ),
                    artifact_revision=artifact_revision,
                )
            )
        elif artifact_revision == project.revision:
            self._publish(
                PipelineStatus(
                    PipelineState.UP_TO_DATE,
                    project.revision,
                    validate_project(project),
                    message=f"Up to date at revision {project.revision}",
                    artifact_revision=artifact_revision,
                )
            )
        elif artifact_revision is not None:
            self._publish(
                PipelineStatus(
                    PipelineState.STALE_OUTPUT,
                    project.revision,
                    validate_project(project),
                    message=f"Stale output from revision {artifact_revision}",
                    artifact_revision=artifact_revision,
                )
            )
            self.project_changed()
        else:
            self.project_changed()

    def project_changed(self) -> None:
        session = self._session
        if session is None:
            return
        revision = session.authority.revision
        if session.root is None:
            self.cancel()
            self._publish(
                PipelineStatus(
                    PipelineState.UNSAVED,
                    revision,
                    validate_project(session.authority.snapshot()),
                    message="Unsaved — use Save and Generate",
                )
            )
            return
        if self._scheduled is not None:
            self._scheduled.cancel()
        self._publish(
            PipelineStatus(
                PipelineState.PENDING,
                revision,
                self._status.diagnostics,
                message=f"Pending changes at revision {revision}",
                artifact_revision=self._status.artifact_revision,
            )
        )

        def process() -> None:
            self._process(revision, allow_external_overwrite=False)

        self._scheduled = self._scheduler.call_later(self._debounce_ms, process)

    def generate_now(self) -> GenerationResult | None:
        session = self._session
        if session is None or session.root is None:
            return None
        self.cancel()
        return self._process(session.authority.revision, allow_external_overwrite=True)

    def generate_in_background(self) -> bool:
        """Schedule explicit validation/generation without blocking the desktop thread."""

        session = self._session
        if session is None or session.root is None:
            return False
        self.cancel()
        revision = session.authority.revision
        self._publish(
            PipelineStatus(
                PipelineState.PENDING,
                revision,
                self._status.diagnostics,
                message=f"Explicit generation queued for revision {revision}",
                artifact_revision=self._status.artifact_revision,
            )
        )

        def process() -> None:
            self._process(revision, allow_external_overwrite=True)

        self._scheduled = self._scheduler.call_later(0, process)
        return True

    def validate_in_background(self) -> bool:
        """Validate a stable snapshot on a worker and publish only that revision."""

        session = self._session
        if session is None:
            return False
        revision = session.authority.revision
        self._publish(
            PipelineStatus(
                PipelineState.VALIDATING,
                revision,
                self._status.diagnostics,
                message=f"Validating revision {revision} in the background",
                artifact_revision=self._status.artifact_revision,
            )
        )

        def validate() -> None:
            project = session.authority.snapshot()
            assessment = assess_project(project)
            diagnostics = assessment.diagnostics
            if self._session is not session or session.authority.revision != revision:
                return
            errors = sum(item.severity is Severity.ERROR for item in diagnostics)
            warnings = sum(item.severity is Severity.WARNING for item in diagnostics)
            self._publish(
                PipelineStatus(
                    (PipelineState.VALIDATED if assessment.buildable else PipelineState.BLOCKED),
                    revision,
                    diagnostics,
                    message=(
                        f"Validated revision {revision}: {errors} errors, {warnings} warnings"
                    ),
                    artifact_revision=self._status.artifact_revision,
                )
            )

        self._scheduler.call_later(0, validate)
        return True

    def cancel(self) -> None:
        if self._scheduled is not None:
            self._scheduled.cancel()
            self._scheduled = None

    def _process(
        self,
        revision: int,
        *,
        allow_external_overwrite: bool = False,
    ) -> GenerationResult | None:
        self._scheduled = None
        session = self._session
        if session is None or session.root is None:
            return None
        if session.authority.revision != revision:
            return None
        inspection = inspect_generation(session.root, current_revision=revision)
        if inspection.externally_changed and not allow_external_overwrite:
            self._publish(
                PipelineStatus(
                    PipelineState.STALE_OUTPUT,
                    revision,
                    validate_project(session.authority.snapshot()),
                    message=(
                        "Generated files were modified, removed, or added outside Code Visualizer; "
                        "automatic generation paused. Inspect the artifact diff, then use Generate "
                        "Project to explicitly replace the generated set."
                    ),
                    artifact_revision=inspection.manifest_revision,
                )
            )
            return None
        self._publish(
            PipelineStatus(
                PipelineState.VALIDATING,
                revision,
                self._status.diagnostics,
                message=f"Validating revision {revision}",
                artifact_revision=self._status.artifact_revision,
            )
        )
        try:
            if not session.autosave(revision):
                return None
            project = session.authority.snapshot()
            assessment = assess_project(project)
            diagnostics = assessment.diagnostics
            errors = assessment.blocking_diagnostics
            if not assessment.buildable:
                self._publish(
                    PipelineStatus(
                        PipelineState.BLOCKED,
                        revision,
                        diagnostics,
                        message=(
                            f"Blocked — {len(errors)} error"
                            f"{'s' if len(errors) != 1 else ''}; prior artifacts preserved"
                        ),
                        artifact_revision=self._status.artifact_revision,
                    )
                )
                return None
            self._publish(
                PipelineStatus(
                    PipelineState.GENERATING,
                    revision,
                    diagnostics,
                    message=f"Generating revision {revision}",
                    artifact_revision=self._status.artifact_revision,
                )
            )
            result = session.generate(
                revision_provider=lambda: (
                    session.authority.revision if self._session is session else -1
                )
            )
        except StaleGenerationError:
            if session.authority.revision != revision:
                self.project_changed()
            return None
        except Exception as exc:
            self._publish(
                PipelineStatus(
                    PipelineState.FAILED,
                    revision,
                    validate_project(session.authority.snapshot()),
                    message=f"Generation failed: {exc}",
                    artifact_revision=self._status.artifact_revision,
                )
            )
            return None
        if session.authority.revision != revision:
            self.project_changed()
            return None
        self._publish(
            PipelineStatus(
                PipelineState.UP_TO_DATE,
                revision,
                diagnostics,
                result=result,
                message=f"Up to date at revision {revision}",
                artifact_revision=revision,
            )
        )
        return result

    def _publish(self, status: PipelineStatus) -> None:
        self._status = status
        self._listener(status)
