"""Explicit embedding and the existing managed Python child execution strategies."""

from __future__ import annotations

from dataclasses import replace
from threading import Event, RLock

from code_visualizer.domain.computation import BackendDefinition, CancelRequest
from code_visualizer.domain.evidence import ComputationOutcome, EvidenceDiagnostic
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import BackendResult, PreparedComputation, RegisteredBackend
from code_visualizer.execution.lifecycle import BackendExecution
from code_visualizer.execution.python_artifacts import PythonArtifactContext
from code_visualizer.execution.runner import RunSession, TraceResult
from code_visualizer.execution.runtime import RuntimeBindingSpec, program_binding_specs
from code_visualizer.generation.emitter import GeneratedProject
from code_visualizer.generation.transformation import TransformationError


def managed_driver(
    session_id: str,
    definition: BackendDefinition,
    snapshot: PreparedComputation,
    generated: GeneratedProject,
    *,
    binding_specs: tuple[RuntimeBindingSpec, ...] | None = None,
    computation: PythonArtifactContext | None = None,
) -> ManagedPythonDriver:
    """Resolve only a host-registered, exact managed execution strategy."""
    from code_visualizer.execution.python_backend import publishing_python_backend, python_backend

    if (
        definition not in (python_backend().definition, publishing_python_backend().definition)
        or (snapshot.request.backend_id, snapshot.request.backend_version)
        != (definition.id, definition.version)
        or snapshot.representation != definition.input_representation
        or not isinstance(snapshot.value, ProgramModel)
    ):
        raise TransformationError(
            "COMPUTATION_MANAGED_STRATEGY",
            "No managed artifact execution strategy matches this exact backend contract",
        )
    if definition.version == "2" and computation is None:
        raise TransformationError(
            "COMPUTATION_HOST_REQUIRED", "Python artifact execution requires a host context"
        )
    return ManagedPythonDriver(
        session_id, snapshot, generated, binding_specs=binding_specs, computation=computation
    )


class InProcessDriver:
    """Opt-in, demand-driven execution for an embedding or an identity-sensitive test.

    This class provides no process isolation. It is never inferred from a backend
    callback, registry composition, or a missing production worker registration.
    """

    demand_driven = True

    def start(
        self,
        session_id: str,
        backend: RegisteredBackend,
        snapshot: PreparedComputation,
        terminal: ResourceReference | None = None,
    ) -> BackendExecution:
        return BackendExecution(session_id, backend, snapshot, terminal)


class ManagedPythonDriver:
    """Supervise the established Python trace child without another worker layer.

    Python retains its published batch contract. Its trace is accumulated by the
    established runner; final evidence uses the same collector as embedding.
    Preparation and lowering have already completed before this driver starts.
    """

    demand_driven = False

    def __init__(
        self,
        session_id: str,
        snapshot: PreparedComputation,
        generated: GeneratedProject,
        *,
        binding_specs: tuple[RuntimeBindingSpec, ...] | None = None,
        computation: PythonArtifactContext | None = None,
    ) -> None:
        if not session_id or not isinstance(snapshot.value, ProgramModel):
            raise ValueError("Managed Python requires a session and prepared ProgramModel")
        self.session_id = session_id
        self.snapshot = snapshot
        self.generated = generated
        self.binding_specs = binding_specs
        self.computation = computation
        self._session = RunSession()
        self._lock = RLock()
        self._completed = Event()
        self._started = False
        self._closed = False
        self._cancelled = False
        self._trace: TraceResult | None = None
        self._result: BackendResult | None = None
        self._delivered = False

    @property
    def forced_termination(self) -> bool:
        return self._session.forced_termination

    def start(self) -> None:
        from code_visualizer.execution.python_backend import python_timeout

        with self._lock:
            if self._started or self._closed:
                raise ValueError("Managed Python starts exactly once")
            self._started = True
            if self._cancelled:
                self._result = BackendResult(ComputationOutcome.CANCELLED)
                self._completed.set()
                return
            assert isinstance(self.snapshot.value, ProgramModel)
            self._session.start_project_trace(
                self.generated,
                timeout=python_timeout(self.snapshot),
                project_revision=self.snapshot.request.revision,
                artifact_revision=self.snapshot.request.revision,
                binding_specs=(
                    program_binding_specs(self.snapshot.value)
                    if self.binding_specs is None
                    else self.binding_specs
                ),
                completed=self._complete,
                computation=self.computation,
            )

    def _complete(self, trace: TraceResult) -> None:
        with self._lock:
            self._trace = trace
            self._completed.set()

    def advance(self) -> BackendResult:
        from code_visualizer.execution.python_backend import result_from_python_trace

        with self._lock:
            if self._delivered:
                raise ValueError("Managed Python has already completed")
            if not self._started:
                self.start()
        self._completed.wait()
        # Do not hold the driver command lock across host filesystem admission:
        # cancellation must still reach a child waiting for its receipt.
        missing = self.computation.finish() if self.computation else ()
        with self._lock:
            if self._result is None:
                if self._trace is None:
                    raise ValueError("Managed Python closed before producing a result")
                self._result = result_from_python_trace(self.snapshot, self.generated, self._trace)
                if missing and self._result.outcome == ComputationOutcome.SUCCEEDED:
                    self._result = replace(
                        self._result,
                        outcome=ComputationOutcome.FAILED,
                        diagnostics=(
                            *self._result.diagnostics,
                            EvidenceDiagnostic(
                                "COMPUTATION_OUTPUT_MISSING",
                                "Required outputs were not published: " + ", ".join(missing),
                            ),
                        ),
                    )
            self._delivered = True
            return self._result

    def cancel(self, request: CancelRequest) -> None:
        if request.session_id != self.session_id:
            raise ValueError("Cancellation belongs to another Python session")
        with self._lock:
            if self._result is not None or self._closed:
                return
            self._cancelled = True
        self._session.stop()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._session.stop()
        if not self._session.wait():
            raise TimeoutError("Managed Python did not finish its requested shutdown")
        self._completed.set()
        if self.computation is not None:
            self.computation.close()
