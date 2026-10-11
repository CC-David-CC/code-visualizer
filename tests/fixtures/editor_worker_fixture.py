"""Explicit author-language proof composition with no handwritten domain bundles."""

import sys
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[2] / "src"
if str(_SOURCE) not in sys.path:
    sys.path.insert(0, str(_SOURCE))


def fixture_registry():
    from code_visualizer.extensions.builtin import (
        computation_bundle,
        intentional_bundle,
        program_bundle,
    )
    from code_visualizer.extensions.publication import FIRST_PARTY_OWNERSHIP
    from code_visualizer.extensions.registry import DomainExtensionRegistry

    return DomainExtensionRegistry(
        (computation_bundle(), program_bundle(), intentional_bundle()),
        namespace_ownership=FIRST_PARTY_OWNERSHIP,
    )


def worker_profile():
    from code_visualizer.execution.worker_process import WorkerProfile

    return WorkerProfile(
        "test-authored-editor-composition",
        "1",
        (sys.executable, "-I", str(Path(__file__).resolve())),
        (("code_visualizer.python", "1"),),
    )


if __name__ == "__main__":
    from code_visualizer.application.computation_worker import serve

    raise SystemExit(serve(fixture_registry))
