"""Epoch-zero resolution retains the actual authored integral/indicator chain."""

from dataclasses import replace

import numpy as np
from test_adaptive_domain import problem
from test_adaptive_writer import admitted, snapshot

from code_visualizer.application.adaptive_examples import adaptive_diffusion_project
from code_visualizer.application.computation_publications import seal_resource
from code_visualizer.extensions.adaptive_diffusion.adaptation import indicator
from code_visualizer.extensions.adaptive_diffusion.controller import initialize
from code_visualizer.extensions.adaptive_diffusion.initialization import (
    decode_initialization,
    initialization_resource,
)
from code_visualizer.extensions.adaptive_diffusion.problem import definition_digest
from code_visualizer.extensions.adaptive_fields.history import mixed_array, record, support_mesh
from code_visualizer.extensions.adaptive_fields.records import (
    INTERPRETATION_TYPE,
    SUPPORT_TYPE,
    CellInterpretation,
    CellSupport,
)
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.resource_store import ResourceStore


def test_initial_resolution_audit_replays_each_authored_partition_and_its_actual_marks(tmp_path):
    project = adaptive_diffusion_project()
    p, source = problem(project), snapshot(project)
    result = initialize(p)
    assert len(result.passes) > 1
    output = initialization_resource(p, definition_digest(source), result)
    store = ResourceStore(tmp_path)
    root = seal_resource(source, output, store, builtin_registry()).resource
    audit = decode_initialization(store.read(root))
    resources = {
        item.descriptor.reference: item for item in admitted(source, root, store).resources
    }
    visits = work = 0
    previous = None
    for part in audit.partitions:
        meaning = record(
            resources.__getitem__, part.interpretation, CellInterpretation, INTERPRETATION_TYPE
        )
        support = record(resources.__getitem__, meaning.support, CellSupport, SUPPORT_TYPE)
        mesh = support_mesh(resources.__getitem__, support)
        values = mixed_array(resources.__getitem__, part.values, (len(mesh.cells), 1))[:, 0]
        eta = mixed_array(resources.__getitem__, part.indicators, (len(mesh.cells),))
        np.testing.assert_array_equal(values, p.initial_values(mesh))
        np.testing.assert_array_equal(eta, indicator(p, mesh, values))
        assert abs(p.area * (mesh.widths @ values) - audit.mass.magnitude) < 1e-12
        if previous is not None:
            old_mesh, old_eta = previous
            assert all(
                cell not in mesh.cells
                for cell, mark in zip(old_mesh.cells, old_eta, strict=True)
                if mark > 1
            )
            work += len(old_mesh.cells) + len(mesh.cells)
        visits += len(mesh.cells)
        previous = mesh, eta
    assert np.max(eta) <= 1
    assert mesh == result.state.mesh
    assert (visits, work) == (audit.indicator_visits, audit.remeshed_cells)
    assert audit.method == "authored_fourier_cell_integrals"
    # Uniform comparison does not fabricate spatial measurements.
    uniform = replace(p, policy=replace(p.policy, mesh_mode="uniform"))
    plain = initialize(uniform)
    assert len(plain.passes) == 1 and plain.passes[0].indicators is None
    assert plain.state.indicator_visits == plain.state.transferred_cells == 0
