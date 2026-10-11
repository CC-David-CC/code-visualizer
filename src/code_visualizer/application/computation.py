"""Execute registered computation backends and return evidence to the shared runtime plane."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import TYPE_CHECKING

from code_visualizer.application.computation_publications import (
    PublicationBudget,
    seal_publication,
    seal_resource,
)
from code_visualizer.application.resource_admission import (
    validate_resource_contracts,
    validate_resource_descriptor,
    validate_value_contracts,
)
from code_visualizer.domain.common import new_id
from code_visualizer.domain.computation import (
    BackendDefinition,
    CancelRequest,
    ComputationPlan,
    ComputationRequest,
    ComputationSession,
    ProgressEvent,
)
from code_visualizer.domain.evidence import (
    ComputationEvidence,
    ComputationOutcome,
    EvidenceDiagnostic,
    ObservationEvent,
)
from code_visualizer.domain.intentional import DomainModel, IntentionalNode
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.resources import TERMINAL_LOGICAL_TYPE
from code_visualizer.domain.transformation import OriginLink, OriginMap
from code_visualizer.domain.values import ResourceReference
from code_visualizer.execution.backends import (
    BackendResult,
    PreparedComputation,
    ProducedResourceEvent,
    ResolvedResource,
    resource_references,
    terminal_context,
)
from code_visualizer.execution.lifecycle import BackendExecution
from code_visualizer.execution.publication_budget import computation_provenance
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.generation.transformation import TransformationError, value_identities
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.computation import computation_request_to_data
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.evidence import evidence_content_hash
from code_visualizer.persistence.serialization import project_to_data

if TYPE_CHECKING:
    from code_visualizer.application.computation_service import ComputationUpdate
    from code_visualizer.application.kernel import ProjectKernel
    from code_visualizer.extensions.registry import DomainExtensionRegistry
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore


def available_backends(kernel: ProjectKernel) -> tuple[BackendDefinition, ...]:
    return tuple(item.definition for item in kernel.extensions.backends())


def _resolve_resources(
    resource_store: ResourceStore | None,
    snapshot: PreparedComputation,
    registry: DomainExtensionRegistry | None = None,
) -> PreparedComputation:
    dependencies = _dependency_models(snapshot)
    references = resource_references(
        (snapshot.value, dependencies, snapshot.request.configuration, snapshot.request.resources)
    )
    resources: list[ResolvedResource] = []
    if registry is None:
        from code_visualizer.extensions.builtin import builtin_registry

        registry = builtin_registry()
    backend = registry.backend(snapshot.request.backend_id, snapshot.request.backend_version)
    if references and resource_store is not None:
        references = tuple(
            sorted(registry.resource_closure(references, resource_store), key=lambda r: r.id)
        )
    for reference in references:
        if resource_store is None:
            raise TransformationError(
                "COMPUTATION_RESOURCE_STORE", "This computation requires an explicit resource store"
            )
        try:
            resources.append(
                resolve_computation_resource(
                    resource_store,
                    reference,
                    file_backed=backend.file_backed_inputs if backend is not None else False,
                )
            )
        except (ValueError, OSError) as exc:
            raise TransformationError("COMPUTATION_RESOURCE_UNAVAILABLE", str(exc)) from exc
    request = replace(snapshot.request, resources=references)
    digest = sha256(
        canonical_data_bytes(
            {
                "project": project_to_data(snapshot.project),
                "request": computation_request_to_data(request),
            }
        )
    ).hexdigest()
    links = {item.generated_id: item for item in snapshot.origins.links}
    for model in dependencies:
        for node in model.nodes:
            links.setdefault(node.id, OriginLink(node.id, (node.id,)))
    resolved = replace(
        snapshot,
        request=request,
        input_digest=digest,
        resources=tuple(resources),
        dependency_models=dependencies,
        origins=OriginMap(
            request.project_id, request.revision, tuple(links[key] for key in sorted(links))
        ),
    )
    return replace(resolved, project=terminal_context(resolved))


def _dependency_models(snapshot: PreparedComputation) -> tuple[DomainModel, ...]:
    """Follow explicit domain references; unrelated workspace data is not an input."""
    if not isinstance(snapshot.value, DomainModel):
        return ()
    owners = {
        node.id: (model, node)
        for model in snapshot.project.domain_workspace.models
        for node in model.nodes
    }
    visited = {node.id for node in snapshot.value.nodes}
    pending = [
        target
        for node in snapshot.value.nodes
        for role in (*node.children, *node.references)
        for target in role.node_ids
    ]
    selected: dict[str, list[IntentionalNode]] = {}
    while pending:
        identity = pending.pop()
        if identity in visited:
            continue
        visited.add(identity)
        pair = owners.get(identity)
        if pair is None:
            raise TransformationError(
                "COMPUTATION_REFERENCE", "A computation input reference cannot be resolved"
            )
        owner, node = pair
        selected.setdefault(owner.id, []).append(node)
        pending.extend(
            target for role in (*node.children, *node.references) for target in role.node_ids
        )
    models = []
    for model_id in sorted(selected):
        nodes = tuple(sorted(selected[model_id], key=lambda item: item.id))
        original = snapshot.project.domain_workspace.model(model_id)
        assert original is not None
        if {node.id for node in nodes} == {node.id for node in original.nodes}:
            models.append(original)
            continue
        owned = {identity for node in nodes for role in node.children for identity in role.node_ids}
        models.append(
            replace(
                original,
                nodes=nodes,
                roots=tuple(node.id for node in nodes if node.id not in owned),
            )
        )
    return tuple(models)


def _evidence(
    snapshot: PreparedComputation,
    result: BackendResult,
    resource_store: ResourceStore | None,
    terminal_resource: ResourceReference | None = None,
    *,
    registry: DomainExtensionRegistry,
) -> ComputationEvidence:
    if not isinstance(result, BackendResult):
        raise TransformationError(
            "COMPUTATION_RESULT", "A backend must return a typed BackendResult"
        )
    available = value_identities(snapshot.value) | {
        node.id for model in snapshot.dependency_models for node in model.nodes
    }
    identities = (
        [item.semantic_ids for item in result.observations]
        + [item.semantic_ids for item in result.artifacts]
        + [item.semantic_ids for item in result.diagnostics]
        + [item.semantic_ids for item in result.produced_resources]
    )
    for semantic_ids in identities:
        if set(semantic_ids) - available:
            raise TransformationError(
                "COMPUTATION_ORIGIN_UNKNOWN",
                "Backend evidence names an object absent from its terminal input",
            )
    artifacts = list(result.artifacts)
    for produced in result.produced_resources:
        artifacts.append(seal_resource(snapshot, produced, resource_store, registry))
    for artifact in artifacts:
        if resource_store is None:
            raise TransformationError(
                "COMPUTATION_RESOURCE_STORE", "Evidence resources require a verified resource store"
            )
        resource_store.verified_path(artifact.resource)
    evidence = ComputationEvidence(
        "pending",
        computation_provenance(snapshot, terminal_resource),
        result.outcome,
        result.observations,
        tuple(artifacts),
        result.diagnostics,
    )
    return replace(evidence, id="evidence:" + evidence_content_hash(evidence))


def execute_computation(kernel: ProjectKernel, request: ComputationRequest) -> ComputationEvidence:
    """Headless wait over the same host-owned lifecycle submitted by the editor."""
    session = start_computation(kernel, request)
    return kernel.computations.wait(session.id)


def start_computation(kernel: ProjectKernel, request: ComputationRequest) -> ComputationSession:
    """Capture an immutable snapshot and acknowledge; production prepares off-thread."""
    return kernel.computations.submit(
        kernel.computation_attachment,
        kernel.authority.snapshot(),
        request,
        kernel.host_extensions,
        kernel.resource_store,
        kernel.evidence_store,
    )


def advance_computation(kernel: ProjectKernel, session_id: str) -> ComputationUpdate:
    """Wait for an admitted update; production backend work never runs on this stack."""
    return kernel.computations.advance(session_id)


def _run_prepared(
    snapshot: PreparedComputation,
    registry: DomainExtensionRegistry,
    resource_store: ResourceStore | None,
    evidence_store: EvidenceStore | None,
    terminal_resource: ResourceReference | None = None,
) -> ComputationEvidence:
    _validate_input_values(snapshot, registry)
    terminal_resource = terminal_resource or _publish_input(
        snapshot, resource_store, evidence_store, registry
    )
    request = snapshot.request
    backend = registry.backend(request.backend_id, request.backend_version)
    assert backend is not None  # prepare_computation admitted this exact implementation.
    execution = BackendExecution(
        new_id("computation-session"), backend, snapshot, terminal_resource
    )
    publication_budget = PublicationBudget()
    try:
        while True:
            update = _advance_backend(execution)
            if isinstance(update, BackendResult):
                return _admit_evidence(
                    snapshot,
                    update,
                    resource_store,
                    evidence_store,
                    terminal_resource,
                    registry,
                    execution,
                )
            if isinstance(update, ObservationEvent):
                validate_value_contracts(update.observation.value, registry)
                _validate_resource_values(
                    resource_references(update.observation.value), resource_store, registry
                )
            elif isinstance(update, ProducedResourceEvent):
                admitted = seal_publication(
                    snapshot,
                    update,
                    terminal_resource,
                    resource_store,
                    evidence_store,
                    registry,
                    budget=publication_budget,
                )
                execution.acknowledge_publication(admitted)
    finally:
        execution.close()


def _publish_input(
    snapshot: PreparedComputation,
    resource_store: ResourceStore | None,
    evidence_store: EvidenceStore | None,
    registry: DomainExtensionRegistry,
) -> ResourceReference | None:
    if evidence_store is not None and resource_store is None:
        raise TransformationError(
            "COMPUTATION_RESOURCE_STORE",
            "Durable evidence requires a resource store for its reproducible terminal input",
        )
    if resource_store is not None:
        from code_visualizer.persistence.computation_terminal import publish_terminal

        validate_resource_contracts(TERMINAL_LOGICAL_TYPE, None, registry)
        return publish_terminal(snapshot, resource_store).model
    return None


def _advance_backend(
    execution: BackendExecution,
) -> BackendResult | ProgressEvent | ObservationEvent | ProducedResourceEvent | PreviewEvent:
    try:
        return execution.advance()
    except TransformationError:
        raise
    except Exception as exc:
        execution.close()
        return execution.finish(
            BackendResult(
                ComputationOutcome.FAILED,
                diagnostics=(
                    EvidenceDiagnostic(
                        "COMPUTATION_BACKEND_FAILED", f"{type(exc).__name__}: {exc}"
                    ),
                ),
            )
        )


def _admit_evidence(
    snapshot: PreparedComputation,
    result: BackendResult,
    resource_store: ResourceStore | None,
    evidence_store: EvidenceStore | None,
    terminal_resource: ResourceReference | None,
    registry: DomainExtensionRegistry,
    execution: BackendExecution,
) -> ComputationEvidence:
    from code_visualizer.persistence.evidence_store import validate_portable_evidence

    for observation in result.observations:
        validate_value_contracts(observation.value, registry)
    evidence = _evidence(snapshot, result, resource_store, terminal_resource, registry=registry)
    _validate_resource_values(
        resource_references((evidence.observations, evidence.artifacts)), resource_store, registry
    )
    validate_portable_evidence(evidence)
    try:
        execution.verify_completion()
    except Exception as exc:
        raise TransformationError("COMPUTATION_BACKEND_PROTOCOL", str(exc)) from exc
    if evidence_store is not None:
        evidence_store.put(evidence)
    return evidence


def _validate_resource_values(
    references: tuple[ResourceReference, ...],
    resource_store: ResourceStore | None,
    registry: DomainExtensionRegistry,
) -> None:
    for reference in references:
        if resource_store is None:
            raise TransformationError(
                "COMPUTATION_RESOURCE_STORE",
                "Observed resources require an explicit resource store",
            )
        try:
            resource_store.verified_path(reference)
            descriptor = resource_store.describe(reference)
        except (ValueError, OSError) as exc:
            raise TransformationError("COMPUTATION_RESOURCE_UNAVAILABLE", str(exc)) from exc
        validate_resource_descriptor(descriptor, registry)


def _validate_input_values(
    snapshot: PreparedComputation, registry: DomainExtensionRegistry
) -> None:
    for parameter in snapshot.request.configuration:
        validate_value_contracts(parameter.value, registry)
    for resource in snapshot.resources:
        validate_resource_descriptor(resource.descriptor, registry)


def export_computation_plan(kernel: ProjectKernel, request: ComputationRequest) -> ComputationPlan:
    from code_visualizer.persistence.computation_terminal import publish_terminal

    if kernel.resource_store is None:
        raise TransformationError(
            "COMPUTATION_RESOURCE_STORE",
            "Portable computation plans require an explicit resource store",
        )
    snapshot = _resolve_resources(
        kernel.resource_store,
        prepare_computation(kernel.authority.snapshot(), request, kernel.extensions),
        kernel.extensions,
    )
    _validate_input_values(snapshot, kernel.extensions)
    validate_resource_contracts(TERMINAL_LOGICAL_TYPE, None, kernel.extensions)
    return publish_terminal(snapshot, kernel.resource_store)


def run_computation_plan(
    plan: ComputationPlan,
    registry: DomainExtensionRegistry,
    resource_store: ResourceStore,
    evidence_store: EvidenceStore | None = None,
) -> ComputationEvidence:
    """Worker entrypoint: a portable terminal and static registry, with no editor authority."""
    from code_visualizer.persistence.computation_terminal import load_terminal

    _validate_resource_values((plan.model,), resource_store, registry)
    snapshot = load_terminal(plan, resource_store, registry)
    return _run_prepared(snapshot, registry, resource_store, evidence_store, plan.model)


def computation_sessions(kernel: ProjectKernel) -> tuple[ComputationSession, ...]:
    return tuple(
        sorted(
            (
                item.session
                for item in kernel.computations.attempts()
                if item.attachment_id == kernel.computation_attachment.id
            ),
            key=lambda item: item.id,
        )
    )


def cancel_computation(kernel: ProjectKernel, request: CancelRequest) -> ComputationSession:
    return kernel.computations.cancel(request)


def get_evidence(kernel: ProjectKernel, evidence_id: str) -> ComputationEvidence | None:
    evidence = kernel.runtime.evidence(evidence_id)
    if evidence is not None:
        return evidence
    if kernel.evidence_store is None:
        return None
    try:
        evidence = kernel.evidence_store.get(evidence_id)
    except FileNotFoundError:
        return None
    if evidence.provenance.project_id != kernel.authority.snapshot().id:
        raise ValueError("Evidence belongs to another project")
    return evidence
