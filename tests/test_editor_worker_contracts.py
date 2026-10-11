"""Editor preparation transports immutable intent and typed derived runtime bindings."""

import json
from dataclasses import replace

import pytest

from code_visualizer.domain.invocation_arguments import (
    EMPTY_INVOCATION_ARGUMENTS,
    InvocationArguments,
    parse_invocation_arguments,
)
from code_visualizer.domain.values import ResourceReference
from code_visualizer.domain.worker import WorkerEditorPreparationRequest, WorkerEditorPrepared
from code_visualizer.execution.runtime import RuntimeBindingSpec
from code_visualizer.generation.emitter import GeneratedFile, GeneratedProject, SourceSpan
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.python_execution import (
    PYTHON_EXECUTION_MEDIA_TYPE,
    PythonExecutionArtifact,
    load_python_execution,
    load_python_execution_artifact,
    publish_python_execution,
)
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.protocol.invocation import (
    invocation_arguments_from_proto,
    invocation_arguments_to_proto,
)
from code_visualizer.protocol.v1 import worker_pb2 as wire
from code_visualizer.protocol.worker import (
    worker_control_from_bytes,
    worker_control_to_bytes,
    worker_event_from_bytes,
    worker_event_to_bytes,
)

REFERENCE = ResourceReference("resource:project", "a" * 64)


@pytest.mark.parametrize(
    "arguments",
    (
        None,
        EMPTY_INVOCATION_ARGUMENTS,
        parse_invocation_arguments(
            "None, True, 340282366920938463463374607431768211456, -2.5, "
            "[], (), {'items': [1, (2,)]}, named='value'"
        ),
    ),
)
def test_editor_request_roundtrip_keeps_literal_override_presence_and_value_variants(arguments):
    request = WorkerEditorPreparationRequest(
        "editor-session", REFERENCE, "project", 3, "diagram", arguments=arguments
    )
    encoded = worker_control_to_bytes(request)
    assert worker_control_from_bytes(encoded) == request
    assert worker_control_to_bytes(worker_control_from_bytes(encoded)) == encoded
    prepared = WorkerEditorPrepared("editor-session", REFERENCE.content_hash, REFERENCE)
    assert worker_event_from_bytes(worker_event_to_bytes(prepared)) == prepared


@pytest.mark.parametrize(
    "changes",
    (
        {"model_id": "model"},
        {"focus_diagram_id": ""},
        {"revision": True},
        {"revision": -1},
        {"project_id": ""},
        {"project": {}},
        {"arguments": "7"},
        {"focus_diagram_id": None, "arguments": EMPTY_INVOCATION_ARGUMENTS},
    ),
)
def test_editor_request_rejects_ambiguous_or_untyped_targets(changes):
    original = WorkerEditorPreparationRequest("session", REFERENCE, "project", 0, "diagram")
    with pytest.raises(ValueError):
        replace(original, **changes)


@pytest.mark.parametrize(
    "literal", ({}, {"null": False}, {"integer_decimal": "01"}, {"real": float("nan")})
)
def test_worker_literal_decoding_rejects_missing_noncanonical_or_nonfinite_values(literal):
    arguments = wire.InvocationArguments(positional=[wire.InvocationLiteral(**literal)])
    with pytest.raises(ValueError):
        invocation_arguments_from_proto(arguments)


def test_worker_literal_contract_preserves_empty_structures_and_rejects_unknown_fields():
    arguments = parse_invocation_arguments("[], (), {}, x=None")
    wire_arguments = invocation_arguments_to_proto(arguments)
    assert invocation_arguments_from_proto(wire_arguments) == arguments
    unknown = wire.InvocationArguments.FromString(
        wire_arguments.SerializeToString() + b"\xa0\x06\x01"
    )
    with pytest.raises(ValueError, match="fields"):
        invocation_arguments_from_proto(unknown)
    nested = wire.InvocationLiteral(null=True)
    for _ in range(34):
        nested = wire.InvocationLiteral(list=wire.InvocationSequence(items=[nested]))
    with pytest.raises(ValueError, match="structural"):
        invocation_arguments_from_proto(wire.InvocationArguments(positional=[nested]))
    with pytest.raises(ValueError):
        invocation_arguments_to_proto("unsafe()")


def _generated():
    return GeneratedProject((GeneratedFile("run_project.py", "print('ok')\n", ()),), None, None)


def test_runtime_binding_artifact_is_typed_disposable_and_preserves_old_empty_bytes(tmp_path):
    store = ResourceStore(tmp_path)
    generated = _generated()
    reference = publish_python_execution(generated, store)
    raw = json.loads(store.read(reference))
    assert "binding_specs" not in raw
    assert reference == publish_python_execution(generated, store, binding_specs=())
    assert load_python_execution_artifact(reference, store) == PythonExecutionArtifact(generated)
    bindings = (
        RuntimeBindingSpec("run", "_Inner__n", "symbol:n", "app.main", "Outer.__Inner.__run"),
    )
    bound = publish_python_execution(generated, store, binding_specs=bindings)
    assert bound != reference
    assert load_python_execution(bound, store) == generated
    assert load_python_execution_artifact(bound, store) == PythonExecutionArtifact(
        generated, bindings
    )
    assert publish_python_execution(generated, store, binding_specs=bindings) == bound


@pytest.mark.parametrize(
    "binding",
    (
        {"function": "run", "name": "n", "semantic_symbol_id": "n", "callback": "unsafe"},
        {"function": "run", "name": "n", "semantic_symbol_id": "n", "module": 7},
        {"function": "run", "name": "", "semantic_symbol_id": "n"},
    ),
)
def test_runtime_binding_artifact_rejects_unknown_or_invalid_fields(tmp_path, binding):
    store = ResourceStore(tmp_path)
    reference = publish_python_execution(_generated(), store)
    raw = json.loads(store.read(reference))
    raw["binding_specs"] = [binding]
    invalid = store.put(canonical_data_bytes(raw), PYTHON_EXECUTION_MEDIA_TYPE).reference
    with pytest.raises(ValueError):
        load_python_execution_artifact(invalid, store)


def test_runtime_binding_artifact_rejects_ambiguous_names():
    binding = RuntimeBindingSpec("run", "n", "symbol:n", "app.main", "run")
    with pytest.raises(ValueError, match="unambiguously"):
        PythonExecutionArtifact(
            _generated(), (binding, replace(binding, semantic_symbol_id="other"))
        )
    with pytest.raises(ValueError):
        PythonExecutionArtifact(_generated(), ("untyped",))
    assert InvocationArguments() == EMPTY_INVOCATION_ARGUMENTS


@pytest.mark.parametrize("source,last_line", (("", 1), ("x = 1\n", 1), ("x = 1\r\ny = 2\r\n", 2)))
def test_prepared_source_maps_keep_exact_file_line_boundaries(tmp_path, source, last_line):
    store = ResourceStore(tmp_path)
    span = SourceSpan(
        "map:line", "module.py", "project", "node", None, "source", 1, 0, last_line, 0
    )
    generated = replace(
        _generated(), files=(*_generated().files, GeneratedFile("module.py", source, (span,)))
    )
    reference = publish_python_execution(generated, store)
    assert load_python_execution_artifact(reference, store).generated == generated
    invalid = replace(span, end_line=last_line + 1)
    outside = replace(
        generated,
        files=(*_generated().files, GeneratedFile("module.py", source, (invalid,))),
    )
    with pytest.raises(ValueError, match="mapping is outside"):
        load_python_execution_artifact(publish_python_execution(outside, store), store)


@pytest.mark.parametrize(
    "changes",
    (
        {"file_path": "other.py"},
        {"start_line": 0},
        {"start_line": 2, "end_line": 1},
        {"start_column": -1},
        {"end_column": -1},
    ),
)
def test_prepared_source_maps_reject_wrong_file_reversed_lines_and_negative_columns(
    tmp_path, changes
):
    store = ResourceStore(tmp_path)
    span = SourceSpan("map:line", "module.py", "project", "node", None, "source", 1, 0, 2, 0)
    generated = replace(
        _generated(),
        files=(
            *_generated().files,
            GeneratedFile("module.py", "x = 1\ny = 2\n", (replace(span, **changes),)),
        ),
    )
    with pytest.raises(ValueError, match="mapping is outside"):
        load_python_execution_artifact(publish_python_execution(generated, store), store)


def test_prepared_artifact_rejects_noncanonical_json_without_changing_resource_hashes(tmp_path):
    store = ResourceStore(tmp_path)
    generated = _generated()
    canonical = publish_python_execution(generated, store)
    raw = json.loads(store.read(canonical))
    alternate = store.put(
        json.dumps(raw, indent=2).encode("utf-8"), PYTHON_EXECUTION_MEDIA_TYPE
    ).reference
    assert alternate != canonical
    with pytest.raises(ValueError, match="deterministic canonical JSON"):
        load_python_execution_artifact(alternate, store)
    assert publish_python_execution(load_python_execution(canonical, store), store) == canonical
