"""Read-only comparison of retained evidence, independent of an editor worktree."""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_visualizer.application.git import GitError
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.computation import ComputationPlan, ComputationRequest
from code_visualizer.domain.evidence import ComputationEvidence, EvidenceObservation
from code_visualizer.domain.values import (
    CanonicalValue,
    QuantityValue,
    canonical_value_key,
    validate_canonical_value,
)
from code_visualizer.extensions.foundations.unit_algebra import UnitAlgebra
from code_visualizer.extensions.foundations.units import UnitCatalog, UnitError
from code_visualizer.persistence.computation_terminal import decode_terminal
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.values import canonical_value_to_data

if TYPE_CHECKING:
    from code_visualizer.application.git_experiments import GitExperiments
    from code_visualizer.extensions.registry import DomainExtensionRegistry


def _catalog(
    evidence: ComputationEvidence, resources: ResourceStore, registry: DomainExtensionRegistry
) -> UnitCatalog | None:
    provenance = evidence.provenance
    backend = registry.backend(provenance.backend_id, provenance.backend_version)
    if backend is None or provenance.terminal_resource is None:
        return None
    request = ComputationRequest(
        provenance.project_id,
        provenance.revision,
        provenance.backend_id,
        provenance.backend_version,
        provenance.source_model_id,
        provenance.configuration,
        provenance.seed,
        provenance.resources,
    )
    plan = ComputationPlan(
        request,
        backend.definition.input_representation,
        provenance.terminal_resource,
        provenance.transformations,
        provenance.origins,
        provenance.input_digest,
    )
    snapshot = decode_terminal(plan, resources, registry)
    return UnitCatalog.from_models(snapshot.project.domain_workspace.models)


def _text(value: CanonicalValue | None, catalog: UnitCatalog | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, QuantityValue):
        unit = (
            next(
                (item.symbol for item in catalog.units if item.reference == value.unit),
                value.unit.id,
            )
            if catalog
            else value.unit.id
        )
        magnitude = (
            f"{value.magnitude:.8g}"
            if type(value.magnitude) in (int, float)
            else str(value.magnitude)
        )
        return f"{magnitude} {unit}"
    return f"{value:.8g}" if type(value) in (int, float) else str(value)[:240]


def _difference(
    left: CanonicalValue,
    right: CanonicalValue,
    left_catalog: UnitCatalog | None,
    right_catalog: UnitCatalog | None,
) -> tuple[CanonicalValue | None, str]:
    if type(left) in (int, float) and type(right) in (int, float):
        assert isinstance(left, (int, float)) and isinstance(right, (int, float))
        difference = right - left
        try:
            validate_canonical_value(difference)
        except ValueError:
            return None, "The difference exceeds the bounded canonical value range"
        return difference, ""
    if isinstance(left, QuantityValue) and isinstance(right, QuantityValue):
        if type(left.magnitude) not in (int, float) or type(right.magnitude) not in (int, float):
            return None, "A real scalar difference is not available for these values"
        if left.unit != right.unit:
            if left_catalog is None or right_catalog is None:
                return None, "Unit conversion needs both retained unit vocabularies"
            try:
                # Both frozen catalogs must authorize the same linear conversion.
                # Affine point/interval or other undeclared semantics are not guessed.
                first = UnitAlgebra(left_catalog).convert(right, left.unit)
                second = UnitAlgebra(right_catalog).convert(right, left.unit)
                if first != second:
                    return None, "The retained unit contexts define different conversions"
                right = first
            except UnitError as exc:
                return None, exc.issue.message
        assert isinstance(left.magnitude, (int, float)) and isinstance(
            right.magnitude, (int, float)
        )
        try:
            return QuantityValue(right.magnitude - left.magnitude, left.unit), ""
        except ValueError:
            return None, "The difference exceeds the bounded canonical value range"
    return None, "Values can be inspected without a numeric difference"


def _observations(
    evidence: ComputationEvidence,
) -> dict[tuple[str, tuple[str, ...]], EvidenceObservation]:
    result = {}
    for item in evidence.observations:
        sources = tuple(
            sorted(
                {
                    source
                    for semantic_id in item.semantic_ids
                    for source in evidence.provenance.origins.sources(semantic_id)
                }
            )
        )
        key = item.id, sources
        if key in result:
            raise GitError(
                "EXPERIMENT_COMPARISON", "Observation identities are not unique in this evidence"
            )
        result[key] = item
    return result


def compare_retained_runs(
    experiments: GitExperiments, left_id: str, right_id: str
) -> dict[str, JsonValue]:
    """Call on the existing Git worker; validation and resource reads may be expensive."""
    try:
        attempts = tuple(experiments.verify_run(identity) for identity in (left_id, right_id))
        if any(not item.evidence_id or not item.input_digest for item in attempts):
            raise GitError(
                "EXPERIMENT_COMPARISON",
                "Both attempts need admitted evidence; inspect recovery for unfinished reporting",
            )
        store = EvidenceStore(experiments.store.root)
        resources = ResourceStore(experiments.store.root)
        evidence = tuple(store.get(item.evidence_id) for item in attempts)
        expected_project = experiments.controller.session.authority.snapshot().id
        verified = set()
        for attempt, record in zip(attempts, evidence, strict=True):
            if (
                record.provenance.input_digest != attempt.input_digest
                or record.provenance.project_id != expected_project
            ):
                raise GitError(
                    "EXPERIMENT_COMPARISON",
                    "Evidence does not match the retained attempt's project and input",
                )
            references = (
                *record.provenance.resources,
                *(item.resource for item in record.artifacts),
                *(
                    (record.provenance.terminal_resource,)
                    if record.provenance.terminal_resource
                    else ()
                ),
            )
            for reference in references:
                if reference not in verified:
                    resources.verified_path(reference)
                    verified.add(reference)
        left, right = evidence
        if (left.provenance.backend_id, left.provenance.backend_version) != (
            right.provenance.backend_id,
            right.provenance.backend_version,
        ):
            raise GitError(
                "EXPERIMENT_COMPARISON", "Choose attempts using the same declared backend version"
            )
        registry = experiments.controller.session.kernel.host_extensions
        catalogs = tuple(_catalog(item, resources, registry) for item in evidence)
        first, second = _observations(left), _observations(right)
        rows: list[JsonValue] = []
        keys = sorted(
            first.keys() | second.keys(),
            key=lambda key: ((second.get(key) or first[key]).sequence, key),
        )
        for key in keys:
            earlier, later = first.get(key), second.get(key)
            old_value, new_value = (
                earlier.value if earlier else None,
                later.value if later else None,
            )
            delta, note = None, ""
            if old_value is not None and new_value is not None:
                delta, note = _difference(old_value, new_value, *catalogs)
            label = later.label if later else earlier.label if earlier else key[0]
            rows.append(
                {
                    "observation_id": key[0],
                    "semantic_ids": list(key[1]),
                    "label": label,
                    "status": "added"
                    if earlier is None
                    else "removed"
                    if later is None
                    else "unchanged"
                    if canonical_value_key(earlier.value) == canonical_value_key(later.value)
                    else "changed",
                    "left": canonical_value_to_data(old_value) if old_value is not None else None,
                    "right": canonical_value_to_data(new_value) if new_value is not None else None,
                    "difference": canonical_value_to_data(delta) if delta is not None else None,
                    "left_text": _text(old_value, catalogs[0]),
                    "right_text": _text(new_value, catalogs[1]),
                    "difference_text": _text(delta, catalogs[0]),
                    "note": note,
                }
            )
        return {
            "comparison": True,
            "left_attempt": attempts[0].id,
            "right_attempt": attempts[1].id,
            "left_commit": attempts[0].commit,
            "right_commit": attempts[1].commit,
            "left_evidence": left.id,
            "right_evidence": right.id,
            "left_outcome": left.outcome.value,
            "right_outcome": right.outcome.value,
            "rows": rows,
        }
    except (ValueError, OverflowError) as exc:
        raise GitError("EXPERIMENT_COMPARISON", str(exc)) from exc
