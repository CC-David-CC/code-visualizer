"""Disposable emitted Python files handed from preparation to its managed child.

This resource contains already generated files and their maps, never another
canonical program. Loading does not lower, regenerate, import, or execute them.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import cast

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.transformation import OriginLink, OriginMap
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.project_files import _relative_file
from code_visualizer.execution.runtime import RuntimeBindingSpec
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject, SourceSpan
from code_visualizer.persistence.canonical import canonical_data_bytes, canonical_data_chunks
from code_visualizer.persistence.invocation import invocation_from_data, invocation_to_data
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.values import array_data, integer_data, object_data, text_data

PYTHON_EXECUTION_MEDIA_TYPE = "application/vnd.code-visualizer.python-execution+json;version=1"


@dataclass(frozen=True, slots=True)
class PythonExecutionArtifact:
    generated: GeneratedProject
    binding_specs: tuple[RuntimeBindingSpec, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.generated, GeneratedProject)
            or type(self.binding_specs) is not tuple
        ):
            raise ValueError("Prepared execution requires typed generated files and bindings")
        seen: set[tuple[str | None, str | None, str, str]] = set()
        for binding in self.binding_specs:
            if not isinstance(binding, RuntimeBindingSpec):
                raise ValueError("Prepared runtime bindings must be typed")
            for value in (binding.function, binding.name, binding.semantic_symbol_id):
                if not isinstance(value, str) or not value:
                    raise ValueError("Prepared runtime binding identities must be nonempty text")
            for scope in (binding.module, binding.qualname):
                if scope is not None and (not isinstance(scope, str) or not scope):
                    raise ValueError("Prepared runtime binding scopes must be text or absent")
            key = (binding.module, binding.qualname, binding.function, binding.name)
            if key in seen:
                raise ValueError("Prepared runtime binding names must resolve unambiguously")
            seen.add(key)


def publish_python_execution(
    project: GeneratedProject,
    store: ResourceStore,
    *,
    binding_specs: tuple[RuntimeBindingSpec, ...] = (),
) -> ResourceReference:
    PythonExecutionArtifact(project, binding_specs)
    data: dict[str, JsonValue] = {
        "version": 1,
        "files": [
            cast(
                JsonValue,
                {
                    "path": file.path,
                    "source": file.source,
                    "spans": [asdict(span) for span in file.spans],
                },
            )
            for file in project.files
        ],
        "invocation": invocation_to_data(project.invocation) if project.invocation else None,
        "entrypoint_module": project.entrypoint_module,
        "launcher_path": project.launcher_path,
        "origins": cast(JsonValue, asdict(project.origins))
        if project.origins is not None
        else None,
    }
    if binding_specs:
        data["binding_specs"] = cast(JsonValue, [asdict(item) for item in binding_specs])
    return store.put(canonical_data_bytes(data), PYTHON_EXECUTION_MEDIA_TYPE).reference


def load_python_execution(reference: ResourceReference, store: ResourceStore) -> GeneratedProject:
    return load_python_execution_artifact(reference, store).generated


def load_python_execution_artifact(
    reference: ResourceReference, store: ResourceStore
) -> PythonExecutionArtifact:
    if store.describe(reference).media_type != PYTHON_EXECUTION_MEDIA_TYPE:
        raise ValueError("Resource is not the supported prepared Python execution format")
    payload = store.read(reference)
    raw = json.loads(payload)
    if b"".join(canonical_data_chunks(raw)) != payload:
        raise ValueError("Prepared Python execution must use deterministic canonical JSON")
    data = object_data(
        raw,
        {
            "version",
            "files",
            "invocation",
            "entrypoint_module",
            "launcher_path",
            "origins",
            "binding_specs",
        },
    )
    if integer_data(data.get("version")) != 1:
        raise ValueError("Unsupported prepared Python execution version")
    files = []
    for item in array_data(data.get("files")):
        file = object_data(item, {"path", "source", "spans"})
        path = text_data(file.get("path"))
        _relative_file(path)
        source = text_data(file.get("source"))
        line_count = max(1, len(source.splitlines()))
        spans = []
        for value in array_data(file.get("spans")):
            span = object_data(
                value,
                {
                    "map_id",
                    "file_path",
                    "project_id",
                    "semantic_id",
                    "presentation_id",
                    "field",
                    "start_line",
                    "start_column",
                    "end_line",
                    "end_column",
                },
            )
            result = SourceSpan(
                text_data(span.get("map_id")),
                text_data(span.get("file_path")),
                text_data(span.get("project_id")),
                text_data(span.get("semantic_id")),
                None if span.get("presentation_id") is None else text_data(span["presentation_id"]),
                text_data(span.get("field")),
                integer_data(span.get("start_line")),
                integer_data(span.get("start_column")),
                integer_data(span.get("end_line")),
                integer_data(span.get("end_column")),
            )
            if result.file_path != path or not (
                1 <= result.start_line <= result.end_line <= line_count
                and result.start_column >= 0
                and result.end_column >= 0
            ):
                raise ValueError("Prepared Python source mapping is outside its emitted file")
            spans.append(result)
        files.append(GeneratedFile(path, source, tuple(spans)))
    paths = [file.path.casefold() for file in files]
    launcher = text_data(data.get("launcher_path"))
    _relative_file(launcher)
    if len(paths) != len(set(paths)) or launcher not in [file.path for file in files]:
        raise ValueError("Prepared Python files collide or omit their launcher")
    origins = None
    if data.get("origins") is not None:
        origin = object_data(data["origins"], {"project_id", "revision", "links"})
        links = [
            object_data(item, {"generated_id", "source_ids"})
            for item in array_data(origin.get("links"))
        ]
        origins = OriginMap(
            text_data(origin.get("project_id")),
            integer_data(origin.get("revision")),
            tuple(
                OriginLink(
                    text_data(link.get("generated_id")),
                    tuple(text_data(identity) for identity in array_data(link.get("source_ids"))),
                )
                for link in links
            ),
        )
    generated = GeneratedProject(
        tuple(files),
        None if data.get("invocation") is None else invocation_from_data(data["invocation"]),
        None if data.get("entrypoint_module") is None else text_data(data["entrypoint_module"]),
        origins,
        launcher,
    )
    bindings = []
    for item in array_data(data.get("binding_specs", [])):
        binding = object_data(
            item, {"function", "name", "semantic_symbol_id", "module", "qualname"}
        )
        bindings.append(
            RuntimeBindingSpec(
                text_data(binding.get("function")),
                text_data(binding.get("name")),
                text_data(binding.get("semantic_symbol_id")),
                None if binding.get("module") is None else text_data(binding["module"]),
                None if binding.get("qualname") is None else text_data(binding["qualname"]),
            )
        )
    return PythonExecutionArtifact(generated, tuple(bindings))
