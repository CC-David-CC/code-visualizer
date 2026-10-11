"""Public generation exports without eagerly loading unrelated artifact services."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from code_visualizer.generation.artifacts import (
        ArtifactInspection,
        GenerationResult,
        atomic_promote_directory,
        expected_artifact_contents,
        generate_to_disk,
        inspect_generation,
        load_generation_manifest,
    )
    from code_visualizer.generation.emitter import GeneratedProject, GenerationError, SourceSpan
    from code_visualizer.generation.python import (
        BuildBlockedError,
        GeneratedPython,
        generate_python,
        generate_python_project,
        generated_module_for_diagram,
    )

__all__ = [
    "ArtifactInspection",
    "BuildBlockedError",
    "GeneratedProject",
    "GeneratedPython",
    "GenerationError",
    "GenerationResult",
    "SourceSpan",
    "atomic_promote_directory",
    "expected_artifact_contents",
    "generate_python",
    "generate_python_project",
    "generate_to_disk",
    "generated_module_for_diagram",
    "inspect_generation",
    "load_generation_manifest",
]

_EXPORTS = {
    **dict.fromkeys(
        (
            "ArtifactInspection",
            "GenerationResult",
            "atomic_promote_directory",
            "expected_artifact_contents",
            "generate_to_disk",
            "inspect_generation",
            "load_generation_manifest",
        ),
        "code_visualizer.generation.artifacts",
    ),
    **dict.fromkeys(
        ("GeneratedProject", "GenerationError", "SourceSpan"),
        "code_visualizer.generation.emitter",
    ),
    **dict.fromkeys(
        (
            "BuildBlockedError",
            "GeneratedPython",
            "generate_python",
            "generate_python_project",
            "generated_module_for_diagram",
        ),
        "code_visualizer.generation.python",
    ),
}


def __getattr__(name: str) -> object:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value: object = getattr(import_module(module), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
