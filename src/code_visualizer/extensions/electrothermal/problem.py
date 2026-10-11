"""Validate the actual source/dependency closure before numerical preparation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil, isfinite

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.intentional import DomainIssue, DomainModel, IntentionalNode
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, QuantityValue
from code_visualizer.execution.backends import PreparedComputation
from code_visualizer.extensions.dc import identity as dc_id
from code_visualizer.extensions.dc import validate_dc
from code_visualizer.extensions.electrothermal.domain import MAPPING_ID, METHOD_ID, identity
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind, UnitAlgebra
from code_visualizer.extensions.foundations.units import UnitCatalog
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.intentional import domain_model_to_data


class CouplingError(ValueError):
    def __init__(self, code: str, message: str, object_id: str):
        super().__init__(message)
        self.code, self.object_id = code, object_id


@dataclass(frozen=True, slots=True)
class ElectrothermalProblem:
    id: str
    circuit_model_id: str
    circuit_id: str
    resistor_id: str
    source_id: str
    resistor_body_id: str
    sink_body_id: str
    law_id: str
    contact_id: str
    ambient_id: str
    policy_id: str
    exchange_ids: tuple[str, ...]
    resistance: float
    alpha: float
    reference_temperature: float
    ambient_temperature: float
    initial_resistor_temperature: float
    initial_sink_temperature: float
    resistor_capacity: float
    sink_capacity: float
    contact_conductance: float
    ambient_conductance: float
    duration: float
    windows: int
    max_iterations: int
    evaluation_order: str
    sample_every: int
    checkpoint_every: int
    preview_every: int
    chunk_rows: int
    temperature_scale: float
    power_scale: float
    energy_scale: float

    @property
    def dt(self) -> float:
        return self.duration / self.windows

    def time(self, step: int) -> float:
        return step * self.dt

    @property
    def origins(self) -> tuple[str, ...]:
        return (
            self.id,
            self.resistor_id,
            self.source_id,
            self.resistor_body_id,
            self.sink_body_id,
            self.law_id,
            self.contact_id,
            self.ambient_id,
            self.policy_id,
            *self.exchange_ids,
        )


def definition_digest(snapshot: PreparedComputation) -> str:
    if not isinstance(snapshot.value, DomainModel):
        raise ValueError("Coupling requires intentional source")
    data: dict[str, JsonValue] = {
        "version": 1,
        "backend": [snapshot.request.backend_id, snapshot.request.backend_version],
        "models": [
            domain_model_to_data(model)
            for model in sorted(
                (snapshot.value, *snapshot.dependency_models), key=lambda item: item.id
            )
        ],
    }
    return sha256(canonical_data_bytes(data)).hexdigest()


def derive_problem(project: Project, model: DomainModel) -> ElectrothermalProblem:
    nodes = {node.id: node for item in project.domain_workspace.models for node in item.nodes}
    root = model.node(model.roots[0]) if len(model.roots) == 1 else None
    if root is None or root.concept_id != identity("Experiment"):
        raise CouplingError("COUPLING_ROOT", "Select one electrothermal experiment", model.id)

    def target(
        node: IntentionalNode, name: str, concept: str | None = None, *, child: bool = False
    ) -> IntentionalNode:
        ids = (node.child_ids if child else node.reference_ids)(node.concept_id + ":" + name)
        result = nodes.get(ids[0]) if len(ids) == 1 else None
        if result is None or (concept is not None and result.concept_id != concept):
            raise CouplingError("COUPLING_REFERENCE", f"Missing typed {name}", node.id)
        return result

    def value(node: IntentionalNode, name: str) -> CanonicalValue:
        key = node.concept_id + ":" + name
        result = node.property(key)
        if result is None:
            prop = next(
                (
                    concept.property(key)
                    for schema in project.domain_workspace.schemas
                    for concept in schema.concepts
                    if concept.id == node.concept_id
                ),
                None,
            )
            result = prop.default if prop is not None else None
        if result is None:
            raise CouplingError("COUPLING_PARAMETER", f"Missing {name}", node.id)
        return result

    algebra = UnitAlgebra(UnitCatalog.from_models(project.domain_workspace.models))

    def amount(
        node: IntentionalNode,
        name: str,
        unit: str,
        kind: QuantityKind = QuantityKind.LINEAR,
        low: float = -float("inf"),
        high: float = float("inf"),
    ) -> float:
        actual = value(node, name)
        if not isinstance(actual, QuantityValue) or type(actual.magnitude) not in (int, float):
            raise CouplingError("COUPLING_UNIT", f"{name} requires a real quantity", node.id)
        try:
            converted = algebra.convert(actual, quantity(1, unit).unit, kind=kind)
            result = float(converted.magnitude)  # type: ignore[arg-type]
        except ValueError as exc:
            raise CouplingError("COUPLING_UNIT", str(exc), node.id) from exc
        if not isfinite(result) or not low <= result <= high:
            raise CouplingError("COUPLING_RANGE", f"{name} outside [{low}, {high}] {unit}", node.id)
        return result

    def point(node: IntentionalNode, name: str) -> float:
        if value(node, "temperature_kind") != "point":
            raise CouplingError(
                "COUPLING_QUANTITY_KIND", "Absolute temperatures are points", node.id
            )
        return amount(node, name, "kelvin", QuantityKind.POINT, 200, 1000)

    def count(node: IntentionalNode, name: str, maximum: int = 100000) -> int:
        result = value(node, name)
        if type(result) is not int or not 1 <= result <= maximum:
            raise CouplingError("COUPLING_POLICY", f"{name} requires 1..{maximum}", node.id)
        return result

    law = target(root, "law", identity("ResistanceLaw"), child=True)
    resistor = target(law, "resistor", dc_id("Resistor"))
    body = target(law, "body", identity("ThermalBody"))
    contact = target(root, "contact", identity("ThermalContact"), child=True)
    sink = target(contact, "target", identity("ThermalBody"))
    if (
        target(contact, "source").id != body.id
        or sink.id == body.id
        or set(root.child_ids(identity("Experiment", "bodies"))) != {body.id, sink.id}
    ):
        raise CouplingError(
            "COUPLING_SUPPORT", "Contact must join the two owned bodies", contact.id
        )
    ambient = target(root, "ambient", identity("AmbientSink"), child=True)
    if target(ambient, "body").id != sink.id:
        raise CouplingError("COUPLING_SUPPORT", "Ambient loss must belong to the sink", ambient.id)
    circuit = target(root, "circuit", dc_id("Circuit"))
    dc_model = next(item for item in project.domain_workspace.models if item.node(circuit.id))
    issues = validate_dc(project, dc_model)
    if issues:
        raise CouplingError(issues[0].code, issues[0].message, issues[0].object_id)
    components = circuit.child_ids(dc_id("Circuit", "components"))
    sources = [
        nodes[item] for item in components if nodes[item].concept_id == dc_id("VoltageSource")
    ]
    if len(components) != 2 or resistor.id not in components or len(sources) != 1:
        raise CouplingError(
            "COUPLING_CIRCUIT", "This fragment requires one source and one resistor", circuit.id
        )
    source = sources[0]
    nets = circuit.child_ids(dc_id("Circuit", "nets"))
    for component in (resistor, source):
        connected = {
            target(target(component, side, dc_id("Terminal"), child=True), "net").id
            for side in ("positive", "negative")
        }
        if len(nets) != 2 or connected != set(nets):
            raise CouplingError(
                "COUPLING_CIRCUIT", "The two components must span the same two nets", component.id
            )
    amount(source, "voltage", "volt", low=-100, high=100)
    exchanges = root.child_ids(identity("Experiment", "exchanges"))
    seen = set()
    for exchange_id in exchanges:
        exchange = nodes[exchange_id]
        source_port, target_port = value(exchange, "source_port"), value(exchange, "target_port")
        if not isinstance(source_port, str) or not isinstance(target_port, str):
            raise CouplingError("COUPLING_PORT", "Port identities require text", exchange.id)
        key = (source_port, target_port)
        expected = {
            ("temperature", "temperature"): (body.id, resistor.id, "kelvin", QuantityKind.POINT),
            ("dissipation", "heat_input"): (resistor.id, body.id, "watt", QuantityKind.LINEAR),
        }.get(key)
        if expected is None or key in seen:
            raise CouplingError(
                "COUPLING_PORT", "Unknown or duplicated deposition/temperature port", exchange.id
            )
        seen.add(key)
        start, end, unit, kind = expected
        if target(exchange, "source").id != start or target(exchange, "target").id != end:
            raise CouplingError(
                "COUPLING_PORT", "Port belongs to a different component", exchange.id
            )
        if (
            target(exchange, "source_support").id != body.id
            or target(exchange, "target_support").id != body.id
            or value(exchange, "support_kind") != "lumped_body"
        ):
            raise CouplingError(
                "COUPLING_SUPPORT", "Identity exchange requires the same lumped body", exchange.id
            )
        if (
            value(exchange, "mapping_id") != MAPPING_ID
            or value(exchange, "mapping_version") != "1"
            or value(exchange, "time_policy") != "same_endpoint"
            or value(exchange, "sign") != 1
        ):
            raise CouplingError(
                "COUPLING_MAPPING", "Unsupported mapping, version, time or sign", exchange.id
            )
        for end_name in ("source", "target"):
            if value(exchange, end_name + "_kind") != kind.value:
                raise CouplingError(
                    "COUPLING_QUANTITY_KIND", "Exchange quantity kinds disagree", exchange.id
                )
            # Scales are intervals even when the transferred physical values are points.
            amount(
                exchange,
                end_name + "_scale",
                unit,
                QuantityKind.INTERVAL if kind == QuantityKind.POINT else kind,
                1e-12,
                1e12,
            )
    if len(seen) != 2:
        raise CouplingError("COUPLING_PORT", "Both physical exchanges must be declared", root.id)
    policy = target(root, "policy", identity("WindowPolicy"), child=True)
    order = value(policy, "evaluation_order")
    if (
        order not in ("electrical_first", "thermal_first")
        or value(policy, "method_id") != METHOD_ID
        or value(policy, "method_version") != "1"
    ):
        raise CouplingError("COUPLING_METHOD", "Unsupported fixed-window method/order", policy.id)
    assert isinstance(order, str)
    ambient_temperature = point(ambient, "temperature")
    initial_r, initial_s = point(body, "initial_temperature"), point(sink, "initial_temperature")
    if min(initial_r, initial_s) < ambient_temperature:
        raise CouplingError(
            "COUPLING_RANGE", "Initial temperatures must be at least ambient", root.id
        )
    result = ElectrothermalProblem(
        root.id,
        dc_model.id,
        circuit.id,
        resistor.id,
        source.id,
        body.id,
        sink.id,
        law.id,
        contact.id,
        ambient.id,
        policy.id,
        tuple(sorted(exchanges)),
        amount(resistor, "resistance", "ohm", low=0.1, high=100000),
        amount(law, "alpha", "per_kelvin", low=0, high=0.1),
        point(law, "reference_temperature"),
        ambient_temperature,
        initial_r,
        initial_s,
        amount(body, "capacity", "joule_per_kelvin", low=0.1, high=100000),
        amount(sink, "capacity", "joule_per_kelvin", low=0.1, high=100000),
        amount(contact, "conductance", "watt_per_kelvin", low=0.001, high=1000),
        amount(ambient, "conductance", "watt_per_kelvin", low=0.001, high=1000),
        amount(policy, "duration", "second", low=1e-6, high=100000),
        count(policy, "windows"),
        count(policy, "max_iterations", 50),
        order,
        count(policy, "sample_every"),
        count(policy, "checkpoint_every"),
        count(policy, "preview_every"),
        count(policy, "chunk_rows", 10000),
        amount(policy, "temperature_scale", "kelvin", QuantityKind.INTERVAL, 1e-6, 1e6),
        amount(policy, "power_scale", "watt", low=1e-6, high=1e6),
        amount(policy, "energy_scale", "joule", low=1e-6, high=1e6),
    )
    if 1 + result.alpha * (initial_r - result.reference_temperature) <= 0:
        raise CouplingError("COUPLING_RESISTANCE", "Initial resistance is not positive", law.id)
    samples = (
        ceil(result.windows / result.sample_every)
        + ceil(result.windows / result.checkpoint_every)
        + 2
    )
    chunks = ceil(samples / result.chunk_rows) + ceil(result.windows / result.checkpoint_every) + 2
    if chunks > 256 or 2 * chunks + 3 * ceil(result.windows / result.checkpoint_every) + 8 > 1024:
        raise CouplingError(
            "COUPLING_OUTPUT_LIMIT", "History exceeds its bounded closure", policy.id
        )
    return result


def validate_problem(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    try:
        derive_problem(project, model)
    except CouplingError as exc:
        return (DomainIssue(exc.code, str(exc), exc.object_id, incomplete=True),)
    return ()
