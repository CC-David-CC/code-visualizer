"""Atomic, manifest-backed whole-project artifact generation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Lock, RLock
from typing import TYPE_CHECKING
from uuid import uuid4
from weakref import WeakValueDictionary

from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.module_paths import python_module_file_path
from code_visualizer.domain.program import ProgramFunction
from code_visualizer.domain.project import Project, ProjectDocument
from code_visualizer.generation.emitter import SourceSpan
from code_visualizer.generation.python import GenerationError, generate_python_project
from code_visualizer.validation import Diagnostic, Severity, assess_project

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionRegistry


class ArtifactGenerationError(RuntimeError):
    pass


class StaleGenerationError(ArtifactGenerationError):
    pass


_artifact_locks: WeakValueDictionary[Path, RLock] = WeakValueDictionary()
_artifact_lock_registry_guard = Lock()


def _artifact_lock(root: Path) -> RLock:
    """Share a short filesystem admission boundary without retaining project state."""

    key = root.resolve()
    with _artifact_lock_registry_guard:
        lock = _artifact_locks.get(key)
        if lock is None:
            lock = RLock()
            _artifact_locks[key] = lock
        return lock


def read_artifact_text(
    project_root: Path, relative_path: str, *, maximum_bytes: int = 2_000_000
) -> str | None:
    """Read a bounded immutable preview; return None when the file exceeds its limit.

    Readers release all file handles before artifact promotion can start. External
    programs do not participate in this boundary and their sharing errors remain
    explicit generation failures.
    """

    if type(maximum_bytes) is not int or maximum_bytes < 1:
        raise ValueError("Artifact preview limit must be a positive integer")
    relative = PurePosixPath(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.split("/"))
        or any(character in relative_path for character in ("\\", ":", "\0"))
    ):
        raise ValueError("Artifact preview requires a normalized relative file path")
    root = project_root.resolve() / "generated"
    with _artifact_lock(root):
        candidate = root.joinpath(*relative.parts).resolve()
        if not candidate.is_relative_to(root):
            raise ValueError("Artifact preview escaped the generated directory")
        with candidate.open("rb") as stream:
            data = stream.read(maximum_bytes + 1)
        return data.decode("utf-8") if len(data) <= maximum_bytes else None


@dataclass(frozen=True, slots=True)
class GenerationResult:
    root: Path
    revision: int
    files: tuple[Path, ...]
    manifest: Path


@dataclass(frozen=True, slots=True)
class ArtifactInspection:
    """Read-only comparison between a manifest, disk, and the active revision."""

    manifest_found: bool
    manifest_revision: int | None = None
    files: tuple[tuple[str, str], ...] = ()
    missing: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()
    revision_stale: bool = False
    invalid_manifest: bool = False

    @property
    def externally_changed(self) -> bool:
        return bool(self.missing or self.modified or self.unexpected or self.invalid_manifest)

    @property
    def clean(self) -> bool:
        return self.manifest_found and not self.revision_stale and not self.externally_changed


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _span_data(span: SourceSpan) -> dict[str, object]:
    return {
        "end_column": span.end_column,
        "end_line": span.end_line,
        "field": span.field,
        "file_path": span.file_path,
        "map_id": span.map_id,
        "presentation_id": span.presentation_id,
        "project_id": span.project_id,
        "semantic_id": span.semantic_id,
        "start_column": span.start_column,
        "start_line": span.start_line,
    }


def _source_map(spans: tuple[SourceSpan, ...], entrypoint: str | None) -> str:
    data = {
        "entrypoint": entrypoint,
        "spans": [_span_data(span) for span in spans],
        "version": 3,
    }
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _diagnostic_data(diagnostic: Diagnostic) -> dict[str, object]:
    return {
        "category": diagnostic.category.value,
        "code": diagnostic.code,
        "diagram_id": diagnostic.diagram_id,
        "field": diagnostic.field,
        "message": diagnostic.message,
        "object_id": diagnostic.object_id,
        "severity": diagnostic.severity.value,
        "suggested_repair": diagnostic.suggested_repair,
    }


def _document_function(project: Project, document: DrakonDiagram) -> ProgramFunction:
    view = next((item for item in project.drakon_views if item.document_id == document.id), None)
    function = project.program_model.function(view.function_id) if view is not None else None
    if function is None:
        raise ArtifactGenerationError(
            f"DRAKON view {document.id!r} has no canonical program function"
        )
    return function


def _program_file_path(project: Project, function: ProgramFunction) -> str:
    module = project.program_model.module_for(function.id)
    if module is None:
        raise ArtifactGenerationError(f"Program function {function.id!r} has no owning module")
    return python_module_file_path(project.program_model.package, module.path, kind=module.kind)


def _diagram_artifact_path(project: Project, document: ProjectDocument) -> str:
    if isinstance(document, DrakonDiagram):
        function = _document_function(project, document)
        code_path = _program_file_path(project, function)
        module_directory = code_path.removesuffix(".py")
        owning_class = project.program_model.class_name_for(function.id)
        callable_parts = (
            (*owning_class.split("."), function.identifier)
            if owning_class is not None
            else (function.identifier,)
        )
        return f"diagrams/{module_directory}/{'/'.join(callable_parts)}.svg"
    return f"diagrams/design/{document.kind.value}/{document.id}.svg"


def _graph_index(project: Project) -> str:
    documents: list[dict[str, object]] = []
    for document in project.documents:
        graph_path = _diagram_artifact_path(project, document)
        if isinstance(document, DrakonDiagram):
            function = _document_function(project, document)
            documents.append(
                {
                    "code_path": _program_file_path(project, function),
                    "diagram_id": document.id,
                    "function": function.identifier,
                    "graph_path": graph_path,
                    "kind": document.kind.value,
                    "module": project.program_model.module_path_for(function.id),
                    "owning_class": project.program_model.class_name_for(function.id),
                    "title": document.title,
                }
            )
        else:
            documents.append(
                {
                    "code_path": None,
                    "diagram_id": document.id,
                    "function": None,
                    "graph_path": graph_path,
                    "kind": document.kind.value,
                    "module": None,
                    "owning_class": None,
                    "title": document.title,
                }
            )
    data = {
        "documents": documents,
        "package": project.program_model.package,
        "project_id": project.id,
        "schema_version": 1,
    }
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_promote_directory(temporary: Path, target: Path) -> None:
    """Atomically replace one sibling directory while retaining rollback recovery."""

    temporary = temporary.resolve()
    target = target.resolve()
    if temporary == target or temporary.parent != target.parent:
        raise ArtifactGenerationError("Directory promotion requires distinct sibling paths")
    if not temporary.is_dir():
        raise ArtifactGenerationError(f"Promotion source is not a directory: {temporary}")
    backup = target.parent / f".{target.name}.backup-{uuid4().hex}"
    had_target = target.exists()
    try:
        if had_target:
            os.replace(target, backup)
        os.replace(temporary, target)
    except OSError:
        if had_target and backup.exists() and not target.exists():
            os.replace(backup, target)
        raise
    finally:
        # If rollback itself failed, retain the backup as an explicit recovery
        # set instead of deleting the last complete generation.
        if backup.exists() and target.exists():
            with suppress(OSError):
                shutil.rmtree(backup)


def _active_profile_data(project: Project) -> dict[str, object]:
    setup = project.runtime_settings
    profile = next(
        (item for item in setup.run_profiles if item.name == setup.active_run_profile),
        setup.run_profiles[0] if setup.run_profiles else None,
    )
    return {
        "active_profile": setup.active_run_profile,
        "arguments": profile.arguments if profile else "",
        "environment": ({item.name: item.value for item in profile.environment} if profile else {}),
        "interpreter": profile.interpreter if profile else "",
        "working_directory": profile.working_directory if profile else ".",
    }


def expected_artifact_contents(
    project: Project,
    *,
    project_root: Path | None = None,
    extensions: DomainExtensionRegistry | None = None,
) -> dict[str, str]:
    """Build the exact deterministic artifact set without touching the filesystem."""

    # Rendering belongs to the optional on-disk SVG export, not Python preparation.
    from code_visualizer.rendering import ExportOptions, document_to_svg

    assessment = assess_project(project, extensions=extensions)
    diagnostics = assessment.diagnostics
    errors = assessment.blocking_diagnostics
    if not assessment.buildable:
        raise ArtifactGenerationError(
            f"Generation blocked by {errors[0].code}: {errors[0].message}"
        )
    try:
        generated = generate_python_project(project, extensions=extensions)
    except GenerationError as exc:
        raise ArtifactGenerationError(str(exc)) from exc
    contents: dict[str, str] = {item.path: item.source for item in generated.files}
    contents["project.source-map.json"] = _source_map(generated.spans, generated.entrypoint)
    if generated.origins is not None:
        contents["project.origin-map.json"] = (
            json.dumps(
                {
                    "project_id": generated.origins.project_id,
                    "revision": generated.origins.revision,
                    "version": 1,
                    "links": [
                        {"generated_id": item.generated_id, "source_ids": list(item.source_ids)}
                        for item in generated.origins.links
                    ],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    report = {
        "diagnostics": [_diagnostic_data(item) for item in diagnostics],
        "entrypoint": generated.entrypoint,
        "entrypoint_module": generated.entrypoint_module,
        "error_count": len(errors),
        "project_id": project.id,
        "revision": project.revision,
        "status": "complete",
        "warning_count": sum(item.severity is Severity.WARNING for item in diagnostics),
    }
    contents["generation-report.json"] = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    contents["run-config.json"] = (
        json.dumps(
            _active_profile_data(project),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    contents["project.graph-index.json"] = _graph_index(project)
    for document in project.documents:
        contents[_diagram_artifact_path(project, document)] = document_to_svg(
            document,
            options=ExportOptions(
                asset_root=project_root,
                managed_assets=project.managed_assets,
            ),
        )
    if not contents:
        raise ArtifactGenerationError("Generation produced no files")
    hashes = {
        path: hashlib.sha256(source.encode("utf-8")).hexdigest()
        for path, source in sorted(contents.items())
    }
    manifest = {
        "entrypoint": generated.entrypoint,
        "entrypoint_module": generated.entrypoint_module,
        "files": hashes,
        "project_id": project.id,
        "revision": project.revision,
        "schema_version": 2,
        "status": "complete",
    }
    contents["generation.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    return contents


def generate_to_disk(
    project: Project,
    project_root: Path,
    *,
    current_revision: Callable[[], int] | None = None,
    extensions: DomainExtensionRegistry | None = None,
) -> GenerationResult:
    contents = expected_artifact_contents(project, project_root=project_root, extensions=extensions)
    root = project_root.resolve()
    target = root / "generated"
    temporary = root / f".generated-{uuid4().hex}.tmp"
    if temporary.exists():
        raise ArtifactGenerationError(f"Temporary output already exists: {temporary}")
    temporary.mkdir(parents=True)
    relative_files: list[Path] = []
    try:
        for relative_path, source in contents.items():
            relative = Path(relative_path)
            _write_text(temporary / relative, source)
            relative_files.append(relative)
        # Lowering and staged writes remain outside the reader admission boundary.
        # Ordinary Windows file readers deny renaming their containing directory.
        with _artifact_lock(target):
            if current_revision is not None and current_revision() != project.revision:
                raise StaleGenerationError(
                    f"Revision {project.revision} was superseded before artifact promotion"
                )
            atomic_promote_directory(temporary, target)
    except Exception as exc:
        if temporary.exists():
            shutil.rmtree(temporary)
        if isinstance(exc, ArtifactGenerationError):
            raise
        raise ArtifactGenerationError(str(exc)) from exc
    promoted = tuple(target / path for path in relative_files)
    return GenerationResult(target, project.revision, promoted, target / "generation.json")


def inspect_generation(
    project_root: Path,
    *,
    current_revision: int | None = None,
) -> ArtifactInspection:
    """Detect missing, changed, and untracked generated files without mutating them."""

    root = project_root.resolve() / "generated"
    with _artifact_lock(root):
        return _inspect_generation(root, current_revision=current_revision)


def _inspect_generation(root: Path, *, current_revision: int | None) -> ArtifactInspection:
    manifest_path = root / "generation.json"
    if not manifest_path.is_file():
        return ArtifactInspection(False)
    try:
        raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ArtifactInspection(True, invalid_manifest=True)
    if not isinstance(raw, dict) or raw.get("status") != "complete":
        return ArtifactInspection(True, invalid_manifest=True)
    raw_files = raw.get("files")
    if not isinstance(raw_files, dict) or not raw_files:
        return ArtifactInspection(True, invalid_manifest=True)
    files: list[tuple[str, str]] = []
    missing: list[str] = []
    modified: list[str] = []
    for raw_path, raw_digest in raw_files.items():
        if not isinstance(raw_path, str) or not isinstance(raw_digest, str):
            return ArtifactInspection(True, invalid_manifest=True)
        candidate = (root / raw_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return ArtifactInspection(True, invalid_manifest=True)
        files.append((raw_path, raw_digest))
        if not candidate.is_file():
            missing.append(raw_path)
        elif hashlib.sha256(candidate.read_bytes()).hexdigest() != raw_digest:
            modified.append(raw_path)
    tracked = {path for path, _digest in files} | {"generation.json"}
    unexpected = tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.relative_to(root).as_posix() not in tracked
        )
    )
    manifest_revision = raw.get("revision")
    typed_revision = manifest_revision if isinstance(manifest_revision, int) else None
    return ArtifactInspection(
        True,
        typed_revision,
        tuple(sorted(files)),
        tuple(sorted(missing)),
        tuple(sorted(modified)),
        unexpected,
        current_revision is not None and typed_revision != current_revision,
    )


def load_generation_manifest(project_root: Path) -> dict[str, object] | None:
    """Load only a complete, non-empty manifest suitable for Reveal/preview."""

    root = project_root.resolve() / "generated"
    with _artifact_lock(root):
        return _load_generation_manifest(root)


def _load_generation_manifest(root: Path) -> dict[str, object] | None:
    path = root / "generation.json"
    if not path.is_file():
        return None
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("status") != "complete":
        return None
    files = value.get("files")
    if not isinstance(files, dict) or not files:
        return None
    for raw_path, raw_hash in files.items():
        if not isinstance(raw_path, str) or not isinstance(raw_hash, str):
            return None
        candidate = (root / raw_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        if not candidate.is_file():
            return None
    return {str(key): item for key, item in value.items()}
