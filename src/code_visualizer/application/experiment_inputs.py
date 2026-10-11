"""Declared, bounded Git inputs. These are derived capture records, not author state."""

from __future__ import annotations

import inspect
import platform
import sys
from dataclasses import dataclass, replace
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, distributions, version
from pathlib import Path

from code_visualizer.application.git import GitError, GitRepository
from code_visualizer.config import PRODUCT
from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
from code_visualizer.domain.project import Project
from code_visualizer.execution.backends import resource_references
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation import computation_request_to_data
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resources import resource_to_data
from code_visualizer.persistence.serialization import normalized_project_json, project_to_data

INPUT_MANIFEST = "code-visualizer-input.json"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_CLOSURE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SourceInput:
    path: str
    destination: str

    def __post_init__(self) -> None:
        GitRepository.input_path(self.path)
        GitRepository.input_path(self.destination)


@dataclass(frozen=True, slots=True)
class CapturedSource:
    definition: SourceInput
    content: bytes

    @property
    def digest(self) -> str:
        return sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class CapturedInputs:
    project: Project
    request: ComputationRequest
    sources: tuple[CapturedSource, ...]
    manifest: dict[str, JsonValue]
    files: tuple[tuple[str, bytes], ...]
    definition_digest: str
    closure_digest: str
    source_digest: str


def definition_state(project: Project) -> Project:
    """Typed policy separation; no command-name or rendered-view heuristics.

    Program/schema/domain contents are conservative semantic inputs. Native view
    objects and language notations are presentation, including accepted geometry.
    """
    workspace = project.domain_workspace
    return replace(
        project,
        revision=0,
        title="",
        description="",
        documents=(),
        drakon_views=(),
        projection_definitions=(),
        managed_assets=(),
        shape_packs=(),
        domain_workspace=replace(
            workspace,
            language_definitions=tuple(
                replace(language, notations=(), title="")
                for language in workspace.language_definitions
            ),
        ),
    )


def read_sources(
    repository: GitRepository, sources: tuple[SourceInput, ...]
) -> tuple[CapturedSource, ...]:
    if len(sources) > 1000:
        raise GitError("GIT_INPUT_CLOSURE", "At most 1000 additional source files can be captured")
    captured = []
    total = 0
    paths: set[str] = {repository.project_path.casefold(), INPUT_MANIFEST.casefold()}
    destinations: set[str] = set()
    for source in sorted(sources, key=lambda item: item.path):
        if source.path.casefold() in paths or source.destination.casefold() in destinations:
            raise GitError("GIT_INPUT_CLOSURE", "Source paths and destinations must be unique")
        paths.add(source.path.casefold())
        destinations.add(source.destination.casefold())
        path = repository.root / source.path
        resolved = path.resolve(strict=True)
        if (
            not resolved.is_relative_to(repository.root)
            or not path.is_file()
            or any(part.is_symlink() for part in (path, *path.parents))
            or PRODUCT.state_directory.casefold() in source.path.casefold().split("/")
            # A linked editing worktree can itself live beneath the common Git
            # directory. Exclude metadata inside this worktree, not its ancestors.
            or (
                repository.common_directory.is_relative_to(repository.root)
                and resolved.is_relative_to(repository.common_directory)
            )
        ):
            raise GitError(
                "GIT_INPUT_PATH", "Source inputs must be ordinary files inside the repository"
            )
        with path.open("rb") as stream:
            content = stream.read(MAX_SOURCE_BYTES + 1)
        total += len(content)
        if len(content) > MAX_SOURCE_BYTES or total > MAX_CLOSURE_BYTES:
            raise GitError("GIT_INPUT_SIZE", "Large input data must be declared as resources")
        content.decode("utf-8")
        captured.append(CapturedSource(source, content))
    return tuple(captured)


def implementation_identity(implementation: object) -> dict[str, JsonValue]:
    """Hash installed implementation bytes, without recording ambient env/secrets."""
    package = Path(__file__).resolve().parents[1]
    digest = sha256()
    count = 0
    paths: tuple[Path, ...]
    if getattr(sys, "frozen", False):
        paths = (Path(sys.executable),)
    else:
        paths = tuple(sorted(package.rglob("*.py")))
    for path in paths:
        name = path.name if getattr(sys, "frozen", False) else path.relative_to(package).as_posix()
        digest.update(name.encode("utf-8") + b"\0")
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        count += 1
    try:
        application_version = version("code-visualizer")
    except PackageNotFoundError:
        application_version = "uninstalled-source"
    try:
        implementation_file = (
            inspect.getsourcefile(implementation) if callable(implementation) else None
        )
    except TypeError:
        implementation_file = None
    implementation_digest = "unavailable"
    if implementation_file is not None and Path(implementation_file).is_file():
        with Path(implementation_file).open("rb") as source:
            backend_digest = sha256()
            while chunk := source.read(1024 * 1024):
                backend_digest.update(chunk)
        implementation_digest = backend_digest.hexdigest()
    return {
        "application_version": application_version,
        "installed_code_sha256": digest.hexdigest(),
        "installed_code_files": count,
        "backend_source_sha256": implementation_digest,
        # Capture implementation versions without treating ambient packages as
        # canonical domain meaning or pretending this is a hermetic environment.
        "distributions": [
            {"name": name, "version": release}
            for name, release in sorted(
                {
                    (str(d.metadata["Name"]).lower().replace("_", "-"), d.version)
                    for d in distributions()
                    if d.metadata["Name"]
                }
            )
        ],
    }


def capture_inputs(
    repository: GitRepository,
    project: Project,
    request: ComputationRequest,
    sources: tuple[SourceInput, ...],
    registry: DomainExtensionRegistry,
    source_resources: ResourceStore | None,
    retained_resources: ResourceStore,
) -> CapturedInputs:
    if (project.id, project.revision) != (request.project_id, request.revision):
        raise GitError("GIT_INPUT_REVISION", "Freeze request does not match the accepted snapshot")
    captured = read_sources(repository, sources)
    backend = registry.backend(request.backend_id, request.backend_version)
    if backend is None:
        raise GitError("GIT_INPUT_BACKEND", "The exact registered backend is unavailable")
    source_references = set()
    if captured:
        prefix = backend.source_file_parameter_prefix
        if prefix is None:
            raise GitError(
                "GIT_INPUT_BACKEND", "This backend consumes resources, not source-file bindings"
            )
        parameters = {item.name: item for item in request.configuration}
        for source in captured:
            resource = retained_resources.put(source.content, "text/plain;charset=utf-8")
            source_references.add(resource.reference)
            name = prefix + source.definition.destination
            parameter = ComputationParameter(name, resource.reference)
            if name in parameters and parameters[name] != parameter:
                raise GitError(
                    "GIT_INPUT_BINDING", "A source file conflicts with configured inputs"
                )
            parameters[name] = parameter
        request = replace(
            request, configuration=tuple(parameters[key] for key in sorted(parameters))
        )
    references = resource_references((project, request))
    external = tuple(reference for reference in references if reference not in source_references)
    if external:
        if source_resources is None:
            raise GitError("GIT_INPUT_RESOURCE", "Declared input resources have no readable store")
        closure_references = registry.resource_closure(external, source_resources)
        references = tuple(
            sorted(set(closure_references) | source_references, key=lambda item: item.id)
        )
    if len(references) > 1024:
        raise GitError("GIT_INPUT_CLOSURE", "At most 1024 resource inputs can be captured")
    descriptors: list[JsonValue] = []
    for reference in references:
        if reference in source_references:
            descriptors.append(resource_to_data(retained_resources.describe(reference)))
            continue
        if source_resources is None:
            raise GitError("GIT_INPUT_RESOURCE", "Declared input resources have no readable store")
        descriptors.append(
            resource_to_data(retained_resources.import_reference(source_resources, reference))
        )
    request = replace(request, resources=references)
    definition_digest = sha256(
        canonical_data_bytes(project_to_data(definition_state(project)))
    ).hexdigest()
    source_digest = sha256(canonical_data_bytes(project_to_data(project))).hexdigest()
    request_data = computation_request_to_data(request)
    request_data["revision"] = 0  # Local presentation/history revisions do not allocate variants.
    closure: dict[str, JsonValue] = {
        "version": 1,
        "project_path": repository.project_path,
        "definition_digest": definition_digest,
        "request": request_data,
        "sources": [
            {
                "path": item.definition.path,
                "destination": item.definition.destination,
                "sha256": item.digest,
                "byte_size": len(item.content),
            }
            for item in captured
        ],
        "resources": descriptors,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "implementation": platform.python_implementation(),
            "application": implementation_identity(backend.execute or backend.stream),
            "bundles": [
                {"id": bundle.id, "version": bundle.version}
                for bundle in sorted(registry.bundles(), key=lambda item: (item.id, item.version))
            ],
            "reproducibility": "declared-inputs; ambient dependencies are not hermetic",
        },
    }
    closure_digest = sha256(canonical_data_bytes(closure)).hexdigest()
    manifest = {
        **closure,
        "closure_digest": closure_digest,
        "source_digest": source_digest,
        "request": computation_request_to_data(request),
    }
    if len(canonical_data_bytes(manifest)) > MAX_PORTABLE_ENVELOPE_BYTES:
        raise GitError("GIT_INPUT_SIZE", "Input metadata exceeds the portable envelope limit")
    files = (
        (repository.project_path, normalized_project_json(project).encode("utf-8")),
        (INPUT_MANIFEST, canonical_data_bytes(manifest)),
        *((item.definition.path, item.content) for item in captured),
    )
    return CapturedInputs(
        project,
        request,
        captured,
        manifest,
        files,
        definition_digest,
        closure_digest,
        source_digest,
    )


def verify_sources(repository: GitRepository, sources: tuple[CapturedSource, ...]) -> None:
    current = read_sources(repository, tuple(item.definition for item in sources))
    if current != sources:
        raise GitError("GIT_INPUT_CHANGED", "A declared source changed during capture")
