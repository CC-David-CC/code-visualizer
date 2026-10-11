"""Explicit local callback composition for deterministic lifecycle unit fixtures.

These fixtures deliberately own an in-process host, including its cleanup. They
prove callback semantics and ordered stepping, not process isolation or GUI safety.
"""

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.execution.computation_driver import InProcessDriver


class InProcessTestKernel(ProjectKernel):
    def __init__(self, authority, **options):
        service = ComputationService(in_process=InProcessDriver())
        try:
            super().__init__(authority, computations=service, **options)
        except Exception:
            service.close()
            raise

    def close(self):
        try:
            super().close()
        finally:
            self.computations.close()
