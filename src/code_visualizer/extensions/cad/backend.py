"""Independent CAD computations consume sealed geometry through the normal host."""

from dataclasses import replace

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.computation import BackendCapabilities, BackendDefinition
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
)
from code_visualizer.domain.intentional import DomainModel, IntentionalNode
from code_visualizer.domain.values import QuantityValue, ResourceReference, UnitReference
from code_visualizer.execution.backends import (
    BackendResult,
    PreparedComputation,
    ProducedResource,
    RegisteredBackend,
)
from code_visualizer.extensions.cad.domain import REPRESENTATION, SCHEMA_ID, identity
from code_visualizer.extensions.cad.native import (
    decode_solid,
    encode_mesh,
    encode_solid,
    tessellate,
)
from code_visualizer.extensions.cad.resources import (
    BREP,
    MEASUREMENT,
    MEDIA_TYPE,
    MESH,
    REGION,
    CadError,
    CadOrigins,
    real,
)
from code_visualizer.extensions.cad.units import cad_catalog
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.values import canonical_value_to_data


def _root(snapshot: PreparedComputation, concept: str) -> IntentionalNode:
    if not isinstance(snapshot.value, DomainModel):
        raise CadError("CAD_INPUT", "CAD consumers require a domain model")
    candidates = [
        n
        for n in snapshot.value.nodes
        if n.id in snapshot.value.roots and n.concept_id == identity(concept)
    ]
    options = {p.name: p.value for p in snapshot.request.configuration}
    if set(options) - {"request_id"}:
        raise CadError(
            "CAD_CONFIGURATION", "Only an explicit request_id may select a CAD operation"
        )
    if "request_id" in options:
        candidates = [n for n in candidates if n.id == options["request_id"]]
    if len(candidates) != 1:
        raise CadError("CAD_REQUEST", "Select exactly one matching CAD operation root")
    return candidates[0]


def _source(
    snapshot: PreparedComputation, node: IntentionalNode
) -> tuple[ResourceReference, bytes]:
    reference = node.property(node.concept_id + ":geometry")
    resource = next((r for r in snapshot.resources if r.descriptor.reference == reference), None)
    if not isinstance(reference, ResourceReference) or resource is None:
        raise CadError("CAD_RESOURCE_UNAVAILABLE", "Exact geometry resource is unavailable")
    if resource.descriptor.logical_type != BREP:
        raise CadError("CAD_TYPE_MISMATCH", "Geometry input requires the BREP logical type/version")
    from code_visualizer.extensions.cad.resources import MAX_HEADER_BYTES, MAX_PAYLOAD_BYTES

    limit = MAX_HEADER_BYTES + MAX_PAYLOAD_BYTES + 20
    if resource.descriptor.byte_size > limit:
        raise CadError("CAD_SIZE", "Geometry exceeds its envelope bound")
    with resource.open() as stream:
        return reference, stream.read(limit + 1)


def _length(node: IntentionalNode, name: str, unit: UnitReference) -> float:
    value = node.property(node.concept_id + ":" + name)
    if not isinstance(value, QuantityValue) or type(value.magnitude) not in (int, float):
        raise CadError("CAD_QUANTITY", f"{name} requires a real length quantity")
    return real(cad_catalog().convert(value, unit).magnitude)


def _evaluate(snapshot: PreparedComputation, concept: str) -> BackendResult:
    node = _root(snapshot, concept)
    reference, data = _source(snapshot, node)
    header, shape = decode_solid(data)
    catalog = cad_catalog()
    meter = catalog.unit("foundation.units.si:meter")
    factor = real(catalog.convert(QuantityValue(1.0, header.frame.unit), meter).magnitude)
    origins = (node.id,)
    if concept == "Measurement":
        values = [
            (
                "volume",
                QuantityValue(
                    float(shape.volume) * factor**3,
                    catalog.unit("code_visualizer.cad.units:cubic_meter"),
                ),
            ),
            (
                "area",
                QuantityValue(
                    float(shape.area) * factor**2,
                    catalog.unit("code_visualizer.cad.units:square_meter"),
                ),
            ),
        ]
        bounds = shape.bounding_box()
        values += [
            ("extent_" + axis, QuantityValue(float(value) * factor, meter))
            for axis, value in zip("xyz", bounds.size, strict=True)
        ]
        values += [
            ("min_" + axis, QuantityValue(float(value) * factor, meter))
            for axis, value in zip("xyz", bounds.min, strict=True)
        ]
        report: dict[str, JsonValue] = {
            "version": 1,
            "geometry": canonical_value_to_data(reference),
            "frame_id": header.frame.frame_id,
            "method": "analytic-brep",
            "native": header.serializer_version,
            "source_origins": {
                "project_id": header.origins.project_id,
                "revision": header.origins.revision,
                "input_digest": header.origins.input_digest,
                "semantic_ids": list(header.origins.semantic_ids),
            },
            "measurements": {name: canonical_value_to_data(value) for name, value in values},
        }
        return BackendResult(
            observations=tuple(
                EvidenceObservation(node.id + ":" + name, origins, value, name, i)
                for i, (name, value) in enumerate(values)
            ),
            produced_resources=(
                ProducedResource(
                    node.id + ":report",
                    canonical_data_bytes(report),
                    "application/json",
                    origins,
                    "Exact geometry measurements",
                    logical_type=MEASUREMENT,
                ),
            ),
        )
    if concept == "Tessellation":
        angular = node.property(identity(concept, "angular"))
        if type(angular) not in (int, float):
            raise CadError("CAD_TOLERANCE", "Angular tolerance requires a finite number")
        mesh = tessellate(
            data,
            reference,
            chordal=_length(node, "chordal", header.frame.unit),
            angular=real(angular),
        )
        return BackendResult(
            produced_resources=(
                ProducedResource(
                    node.id + ":mesh",
                    encode_mesh(mesh),
                    MEDIA_TYPE,
                    origins,
                    "Display mesh",
                    logical_type=MESH,
                ),
            )
        )
    if concept == "GeometryInput":
        from build123d import Pos

        translation = tuple(_length(node, "translate_" + axis, header.frame.unit) for axis in "xyz")
        moved = Pos(*translation) * shape
        new_header = replace(
            header,
            parent=reference,
            origins=CadOrigins(
                snapshot.request.project_id,
                snapshot.request.revision,
                snapshot.input_digest,
                origins,
            ),
        )
        return BackendResult(
            produced_resources=(
                ProducedResource(
                    node.id + ":geometry",
                    encode_solid(moved, new_header),
                    MEDIA_TYPE,
                    origins,
                    "Independently edited solid",
                    logical_type=BREP,
                ),
            )
        )
    from code_visualizer.extensions.cad.regions import resolve_region

    result = resolve_region(node, reference, header, shape)
    return BackendResult(
        produced_resources=(
            ProducedResource(
                node.id + ":region",
                canonical_data_bytes(result),
                "application/json",
                origins,
                "Resolved region",
                logical_type=REGION,
            ),
        )
    )


def evaluate(snapshot: PreparedComputation, concept: str) -> BackendResult:
    try:
        return _evaluate(snapshot, concept)
    except (ValueError, ImportError, OSError) as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(getattr(exc, "code", "CAD_COMPUTATION_FAILED"), str(exc)),
            ),
        )


def backends() -> tuple[RegisteredBackend, ...]:
    def make(concept: str) -> RegisteredBackend:
        def execute(snapshot: PreparedComputation) -> BackendResult:
            return evaluate(snapshot, concept)

        return RegisteredBackend(
            BackendDefinition(
                "code_visualizer.cad." + concept.lower(),
                "1",
                concept,
                REPRESENTATION,
                SCHEMA_ID,
                "1",
                capabilities=BackendCapabilities(),
            ),
            execute,
        )

    return tuple(
        make(c) for c in ("Measurement", "Tessellation", "RegionSelection", "GeometryInput")
    )
