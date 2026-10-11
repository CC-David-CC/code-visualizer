"""P5-02/03: real grouped transfer, immutable resources and bounded lazy reads."""

from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from fixtures.field_worker_fixture import BACKEND_ID, field_output, fixture_registry, worker_profile
from test_computation_publications import publication_context as publication_context

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import (
    execute_computation,
    export_computation_plan,
    run_computation_plan,
)
from code_visualizer.application.computation_process import _Resources
from code_visualizer.application.computation_publications import (
    PublicationBudget,
    seal_publication,
    seal_resource,
)
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.worker import WorkerResourceEvent
from code_visualizer.execution.backends import ProducedResourceEvent
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.fields.arrays import array_resource, read_array
from code_visualizer.extensions.fields.codec import encode_record
from code_visualizer.extensions.fields.history import FieldHistory
from code_visualizer.extensions.fields.records import INTERPRETATION_TYPE, SERIES_TYPE, SUPPORT_TYPE
from code_visualizer.extensions.foundations.units_si import si_catalog
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.resource_transfer import resource_transfer_frames


def test_grouped_seal_publishes_one_root_receipt_and_all_children(publication_context):
    snapshot, plan, resources, evidence, _, _ = publication_context
    registry = builtin_registry()
    output = field_output()
    event = seal_publication(
        snapshot,
        ProducedResourceEvent("session", 0, output),
        plan.model,
        resources,
        evidence,
        registry,
        budget=PublicationBudget(),
    )
    assert len(evidence.publication_identities()) == 1
    closure = registry.resource_closure((event.publication.artifact.resource,), resources)
    assert len(closure) == len(output.dependencies) + 1 == 7
    history = FieldHistory(
        event.publication.artifact.resource,
        lambda ref: resolve_computation_resource(resources, ref, file_backed=True),
    )
    assert history.decoded_chunks == 0
    assert history.slice(11).values[16] == pytest.approx(np.exp(-0.11))
    assert history.decoded_chunks == 1
    assert history.slice(9).values[16] == pytest.approx(np.exp(-0.09))
    assert history.decoded_chunks == 1
    assert not history.slice(11).values.flags.writeable
    history.close()


def test_grouped_failure_never_acknowledges_an_incomplete_root(publication_context, monkeypatch):
    snapshot, plan, resources, evidence, _, _ = publication_context
    output = field_output()
    original = resources.put

    def fail_root(data, *args, **kwargs):
        if data == output.data:
            raise OSError("root admission unavailable")
        return original(data, *args, **kwargs)

    monkeypatch.setattr(resources, "put", fail_root)
    with pytest.raises(ValueError):
        seal_publication(
            snapshot,
            ProducedResourceEvent("session", 0, output),
            plan.model,
            resources,
            evidence,
            builtin_registry(),
            budget=PublicationBudget(),
        )
    assert evidence.publication_identities() == ()
    assert len(resources.descriptors()) > 1  # orphan bytes are inert, never a receipt


@pytest.mark.parametrize("cached_children", (False, True))
def test_unclaimed_child_and_missing_transfer_are_rejected(
    publication_context, tmp_path, cached_children
):
    snapshot, _, resources, _, _, _ = publication_context
    registry = builtin_registry()
    output = field_output()
    extra = array_resource("unclaimed", np.array([19.0, 20.0, 21.0]))
    with pytest.raises(ValueError, match="undeclared"):
        seal_resource(
            snapshot,
            replace(output, dependencies=(*output.dependencies, extra)),
            resources,
            registry,
        )
    artifact = seal_resource(snapshot, output, resources, registry)
    destination = ResourceStore(tmp_path / "destination")
    children = registry.resource_closure((artifact.resource,), resources)[:-1]
    if cached_children:
        for ref in children:
            destination.import_reference(resources, ref)
    transfers = _Resources(destination, SimpleNamespace(registry=registry))
    for frame in resource_transfer_frames(resources, artifact.resource, "root"):
        transfers.accept(WorkerResourceEvent("run", frame))
    with pytest.raises(ValueError, match="omitted a complete resource transfer"):
        transfers.claim_transferred((artifact.resource,))
    assert not transfers.claimed
    for ref in children:
        for frame in resource_transfer_frames(resources, ref, ref.id):
            transfers.accept(WorkerResourceEvent("run", frame))
    transfers.claim_transferred((artifact.resource,))
    transfers.complete((artifact.resource,))
    transfers.close()


def test_array_reader_rejects_shape_nonfinite_and_keeps_mappings_readonly(tmp_path):
    resource = array_resource("values", np.arange(12, dtype=np.float64).reshape(3, 4))
    store = ResourceStore(tmp_path)
    descriptor = store.put(
        resource.data,
        resource.media_type,
        tensor=resource.tensor,
        logical_type=resource.logical_type,
    )
    resolved = resolve_computation_resource(store, descriptor.reference, file_backed=True)
    values = read_array(resolved, (3, 4))
    assert isinstance(values, np.memmap) and not values.flags.writeable
    with pytest.raises(ValueError):
        read_array(resolved, (4, 3))
    with pytest.raises(ValueError):
        array_resource("invalid", np.array([np.nan]))


@pytest.mark.parametrize(
    "role,unit,valid",
    (
        ("coordinates", "meter", True),
        ("coordinates", "millimeter", False),
        ("coordinates", "second", False),
        ("samples", "kelvin", False),
    ),
)
def test_field_roles_reject_conflicting_array_unit_metadata(publication_context, role, unit, valid):
    snapshot, _, store, _, _, _ = publication_context
    root = seal_resource(snapshot, field_output(), store, builtin_registry()).resource

    def resolve(ref):
        return resolve_computation_resource(store, ref, file_backed=True)

    original = FieldHistory(root, resolve)
    try:
        target = (
            original.support.coordinates if role == "coordinates" else original.chunks[0].resource
        )
        descriptor = store.describe(target)
        assert descriptor.tensor is not None
        array = store.put(
            store.read(target),
            descriptor.media_type,
            logical_type=descriptor.logical_type,
            tensor=replace(
                descriptor.tensor, unit=si_catalog().unit("foundation.units.si:" + unit)
            ),
        ).reference
        series = original.series
        if role == "coordinates":
            support = store.put(
                encode_record(replace(original.support, coordinates=array)),
                "application/json",
                logical_type=SUPPORT_TYPE,
            ).reference
            interpretation = store.put(
                encode_record(replace(original.interpretation, support=support)),
                "application/json",
                logical_type=INTERPRETATION_TYPE,
            ).reference
            series = replace(series, interpretation=interpretation)
        else:
            series = replace(
                series, chunks=(replace(series.chunks[0], resource=array), *series.chunks[1:])
            )
        changed = store.put(
            encode_record(series), "application/json", logical_type=SERIES_TYPE
        ).reference
        reader = FieldHistory(changed, resolve)
        try:
            operation = reader.coordinates if role == "coordinates" else lambda: reader.slice(0)
            if valid:
                np.testing.assert_array_equal(operation(), original.coordinates())
            else:
                with pytest.raises(ValueError, match="unit"):
                    operation()
                if role == "samples":
                    with pytest.raises(ValueError, match="unit"):
                        tuple(reader.iter_chunks())
        finally:
            reader.close()
    finally:
        original.close()


@contextmanager
def host(path):
    service = ComputationService(profiles=(worker_profile(),))
    kernel = ProjectKernel(
        ProjectAuthority(create_default_project()),
        extensions=fixture_registry(),
        computations=service,
        resource_store=ResourceStore(path),
        evidence_store=EvidenceStore(path),
    )
    try:
        yield kernel
    finally:
        kernel.close()
        service.close()


def request(kernel, **values):
    project = kernel.authority.snapshot()
    return ComputationRequest(
        project.id,
        project.revision,
        BACKEND_ID,
        "1",
        configuration=tuple(ComputationParameter(name, value) for name, value in values.items()),
    )


def test_real_worker_transfers_complete_root_and_fresh_host_replays_lazy_portable_input(tmp_path):
    with host(tmp_path / "producer") as kernel:
        result = execute_computation(kernel, request(kernel))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert len(result.artifacts) == 1
        root = result.artifacts[0].resource
        closure = kernel.extensions.resource_closure((root,), kernel.resource_store)
        copied = ResourceStore(tmp_path / "consumer")
        for ref in closure:
            copied.import_reference(kernel.resource_store, ref)
    # The fresh host has only the declared resource closure, never producer data paths.
    with host(tmp_path / "consumer") as kernel:
        result = execute_computation(kernel, request(kernel, input=root))
        assert result.outcome is ComputationOutcome.SUCCEEDED, result.diagnostics
        assert result.observations[0].value == pytest.approx(np.exp(-0.11))
        assert set(result.provenance.resources) == set(closure)
        plan = export_computation_plan(kernel, request(kernel, input=root))
        replay = run_computation_plan(
            plan, kernel.extensions, kernel.resource_store, kernel.evidence_store
        )
        assert replay.observations == result.observations
        assert all(
            item.data is None
            for item in kernel.computations.job(
                kernel.computations.attempts()[-1].session.id
            ).snapshot.resources
        )
