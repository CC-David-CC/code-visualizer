"""Exact consumers need only canonical probe authoring and immutable retained resources."""

import numpy as np
import pytest
from fixtures.adaptive_history import HistoryFixture
from test_adaptive_computation import host

from code_visualizer.application.adaptive_artifacts import prepare_probe
from code_visualizer.application.computation import execute_computation
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.values import QuantityValue
from code_visualizer.extensions.adaptive_fields.history import AdaptiveHistory
from code_visualizer.extensions.adaptive_fields.probe import BACKEND_ID
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk.client import CodeVisualizerClient


def fixture(path, *, cells=16):
    source = HistoryFixture(cells=cells)
    store = ResourceStore(path)
    for resource in source.resources.values():
        descriptor = resource.descriptor
        store.put(
            resource.data,
            descriptor.media_type,
            tensor=descriptor.tensor,
            logical_type=descriptor.logical_type,
        )
    return source, store


def test_exact_cell_probe_roundtrip_undo_and_real_worker_after_producer_disappears(tmp_path):
    source, store = fixture(tmp_path / "producer")
    history = AdaptiveHistory(source.root, source.resolve)
    selected = history.slice(3)
    cell = selected.mesh.cell_ids[8]
    expected = history.probe(3, selected.epoch, cell, "concentration")
    project = create_default_project()
    target = ResourceStore(tmp_path / "consumer")
    prepared = prepare_probe(
        project,
        builtin_registry(),
        store,
        target,
        source.root,
        3,
        selected.epoch,
        cell,
        "concentration",
    )
    history.close()
    with host(project, tmp_path / "consumer") as kernel:
        client = CodeVisualizerClient(kernel.authority, actor_id="p7-consumer")
        accepted = client.transaction(prepared.commands, expected_revision=prepared.revision)
        assert isinstance(accepted, CommandAccepted)
        assert kernel.authority.snapshot().domain_workspace.model(prepared.model_id) is not None
        assert isinstance(client.undo(), CommandAccepted)
        assert kernel.authority.snapshot().domain_workspace.model(prepared.model_id) is None
        assert isinstance(client.redo(), CommandAccepted)
        saved = normalized_project_json(kernel.authority.snapshot())
    # Removing only this test's producing fixture makes accidental read-through fail.
    import shutil

    producing_root = (tmp_path / "producer").resolve()
    assert (
        producing_root.is_relative_to(tmp_path.resolve()) and producing_root != tmp_path.resolve()
    )
    shutil.rmtree(producing_root)
    restored = project_from_json(saved)
    with host(restored, tmp_path / "consumer") as fresh:
        evidence = execute_computation(
            fresh,
            ComputationRequest(
                restored.id, restored.revision, BACKEND_ID, "1", model_id=prepared.model_id
            ),
        )
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        value = next(item.value for item in evidence.observations if item.id == "value")
        assert isinstance(value, QuantityValue)
        assert value.unit == expected.unit
        np.testing.assert_equal(value.magnitude, expected.magnitude)


def test_a_parent_array_position_never_substitutes_for_an_exact_cell_identity(tmp_path):
    source, store = fixture(tmp_path / "producer")
    history = AdaptiveHistory(source.root, source.resolve)
    child = next(
        identity
        for identity in history.slice(3).mesh.cell_ids
        if identity not in history.slice(5).mesh.cell_ids
    )
    with pytest.raises(ValueError, match="does not exist"):
        prepare_probe(
            create_default_project(),
            builtin_registry(),
            store,
            ResourceStore(tmp_path / "target"),
            source.root,
            5,
            2,
            child,
            "concentration",
        )
    history.close()
