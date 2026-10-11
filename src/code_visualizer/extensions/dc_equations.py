"""Deterministic DC topology lowering; there is no divider formula or circuit solver."""

from __future__ import annotations

from code_visualizer.domain.intentional import (
    DomainModel,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.transformation import OriginLink, OriginMap, derived_id
from code_visualizer.domain.values import CanonicalValue, QuantityValue
from code_visualizer.extensions.dc import TRANSFORMATION, identity, parameter, validate_dc
from code_visualizer.extensions.foundations.equations import REPRESENTATION
from code_visualizer.extensions.foundations.math import SCHEMA_ID
from code_visualizer.extensions.foundations.math import identity as math_id
from code_visualizer.generation.transformation import (
    TransformationError,
    TransformationInput,
    TransformationResult,
)


class _Builder:
    def __init__(self) -> None:
        self.nodes: dict[str, IntentionalNode] = {}
        self.origins: dict[str, tuple[str, ...]] = {}

    def identity(self, source: str, role: str, origins: tuple[str, ...] = ()) -> str:
        node_id = derived_id(TRANSFORMATION.key, source, role)
        self.origins[node_id] = tuple(sorted(set(origins or (source,))))
        return node_id

    def node(
        self,
        source: str,
        role: str,
        concept: str,
        properties: tuple[tuple[str, CanonicalValue], ...] = (),
        children: tuple[tuple[str, tuple[str, ...]], ...] = (),
        references: tuple[tuple[str, tuple[str, ...]], ...] = (),
        origins: tuple[str, ...] = (),
    ) -> str:
        node_id = self.identity(source, role, origins)
        if node_id in self.nodes:
            raise TransformationError(
                "DC_DERIVATION_ID", "A derived semantic role was emitted twice"
            )
        self.nodes[node_id] = IntentionalNode(
            node_id,
            math_id(concept),
            tuple(PropertyValue(math_id(concept, field), value) for field, value in properties),
            tuple(RoleBinding(math_id(concept, field), values) for field, values in children),
            tuple(RoleBinding(math_id(concept, field), values) for field, values in references),
        )
        return node_id

    def ref(self, source: str, role: str, target: str, origins: tuple[str, ...] = ()) -> str:
        return self.node(
            source, role, "SymbolReference", references=(("symbol", (target,)),), origins=origins
        )

    def quantity(self, source: str, role: str, value: QuantityValue) -> str:
        return self.node(source, role, "QuantityLiteral", (("value", value),))

    def op(
        self,
        source: str,
        role: str,
        operator: str,
        operands: tuple[str, ...],
        origins: tuple[str, ...] = (),
    ) -> str:
        return self.node(
            source,
            role,
            "OperatorApplication",
            (("operator", operator),),
            (("operands", operands),),
            origins=origins,
        )


def lower_dc(snapshot: TransformationInput) -> TransformationResult:
    if not isinstance(snapshot.value, DomainModel):
        raise TransformationError("DC_INPUT", "DC lowering requires an intentional circuit model")
    model = snapshot.value
    findings = validate_dc(snapshot.project, model)
    if findings:
        raise TransformationError(findings[0].code, findings[0].message)
    nodes = {node.id: node for node in model.nodes}
    circuit = nodes[model.roots[0]]
    net_ids = tuple(sorted(circuit.child_ids(identity("Circuit", "nets"))))
    component_ids = tuple(sorted(circuit.child_ids(identity("Circuit", "components"))))
    reference = circuit.reference_ids(identity("Circuit", "reference"))[0]
    voltage_scale, current_scale = (
        parameter(circuit, "voltage_scale"),
        parameter(circuit, "current_scale"),
    )
    builder = _Builder()
    symbols: list[str] = []
    equations: list[str] = []
    relations: list[str] = []

    def label(node_id: str) -> str:
        node = nodes[node_id]
        return str(node.property(node.concept_id + ":name") or node_id)

    potentials = {}
    for net_id in net_ids:
        potentials[net_id] = builder.node(
            net_id,
            "potential",
            "Symbol",
            (
                ("name", "Potential at " + label(net_id)),
                ("scale", voltage_scale),
                ("quantity_kind", "linear"),
            ),
        )
        symbols.append(potentials[net_id])
    currents = {}
    incidence: dict[str, list[tuple[str, str, int]]] = {net_id: [] for net_id in net_ids}

    def relation(
        source: str,
        role: str,
        name: str,
        left: str,
        right: str,
        scale: QuantityValue,
        origins: tuple[str, ...],
    ) -> None:
        equation = builder.node(
            source,
            role,
            "Equation",
            (("name", name),),
            (("left", (left,)), ("right", (right,))),
            origins=origins,
        )
        equations.append(equation)
        relations.append(
            builder.node(
                source,
                role + ":use",
                "RelationUse",
                (("residual_scale", scale),),
                references=(("equation", (equation,)),),
                origins=origins,
            )
        )

    for component_id in component_ids:
        component = nodes[component_id]
        terminals = tuple(
            component.child_ids(component.concept_id + ":" + side)
            for side in ("positive", "negative")
        )
        if any(len(ids) != 1 for ids in terminals):
            raise TransformationError(
                "DC_TERMINALS", "Each component owns one positive and one negative terminal"
            )
        positive, negative = (nodes[ids[0]] for ids in terminals)
        endpoints = tuple(
            terminal.reference_ids(identity("Terminal", "net"))[0]
            for terminal in (positive, negative)
        )
        origins = tuple(sorted({component.id, positive.id, negative.id, *endpoints}))
        current = builder.node(
            component.id,
            "current",
            "Symbol",
            (
                ("name", "Current through " + label(component.id)),
                ("scale", current_scale),
                ("quantity_kind", "linear"),
            ),
            origins=(component.id, positive.id, negative.id),
        )
        symbols.append(current)
        currents[component.id] = current
        for terminal, net, sign in zip((positive, negative), endpoints, (1, -1), strict=True):
            incidence[net].append((terminal.id, component.id, sign))
        drop = builder.op(
            component.id,
            "potential-difference",
            "subtract",
            (
                builder.ref(
                    component.id,
                    "positive-potential",
                    potentials[endpoints[0]],
                    (positive.id, endpoints[0]),
                ),
                builder.ref(
                    component.id,
                    "negative-potential",
                    potentials[endpoints[1]],
                    (negative.id, endpoints[1]),
                ),
            ),
            origins,
        )
        if component.concept_id == identity("Resistor"):
            right = builder.op(
                component.id,
                "ohmic-drop",
                "multiply",
                (
                    builder.quantity(
                        component.id, "resistance", parameter(component, "resistance")
                    ),
                    builder.ref(component.id, "current-occurrence", current),
                ),
                origins,
            )
            relation(
                component.id,
                "constitutive",
                label(component.id) + " voltage-current relation",
                drop,
                right,
                voltage_scale,
                origins,
            )
        elif component.concept_id == identity("VoltageSource"):
            relation(
                component.id,
                "constitutive",
                label(component.id) + " imposed voltage",
                drop,
                builder.quantity(component.id, "voltage", parameter(component, "voltage")),
                voltage_scale,
                origins,
            )
        else:
            raise TransformationError("DC_COMPONENT", "Unsupported component in this DC contract")

    # A reference is an explicit equation, so its zero potential remains observable.
    relation(
        reference,
        "reference",
        label(reference) + " reference potential",
        builder.ref(reference, "reference-occurrence", potentials[reference]),
        builder.quantity(reference, "reference-zero", QuantityValue(0.0, voltage_scale.unit)),
        voltage_scale,
        (reference, circuit.id),
    )
    for net_id in net_ids:
        if net_id == reference:
            continue  # One dependent conservation equation is omitted by the reference choice.
        terms = []
        net_origins = {net_id}
        for terminal_id, component_id, sign in sorted(incidence[net_id]):
            net_origins.update((terminal_id, component_id))
            term = builder.ref(
                net_id,
                "current:" + terminal_id,
                currents[component_id],
                (net_id, terminal_id, component_id),
            )
            if sign == -1:
                term = builder.op(
                    net_id,
                    "incoming:" + terminal_id,
                    "negate",
                    (term,),
                    (net_id, terminal_id, component_id),
                )
            terms.append((terminal_id, term))
        if not terms:
            raise TransformationError("DC_ISOLATED_NET", "An isolated net has no defined potential")
        left = terms[0][1]
        for terminal_id, term in terms[1:]:
            left = builder.op(
                net_id,
                "sum-through:" + terminal_id,
                "add",
                (left, term),
                tuple(sorted(net_origins)),
            )
        relation(
            net_id,
            "conservation",
            label(net_id) + " current conservation",
            left,
            builder.quantity(net_id, "conservation-zero", QuantityValue(0.0, current_scale.unit)),
            current_scale,
            tuple(sorted(net_origins)),
        )
    request = builder.node(
        circuit.id,
        "request",
        "SolveRequest",
        (("name", "DC operating point"), ("problem_class", "linear")),
        (("relations", tuple(sorted(relations))),),
        (("unknowns", tuple(sorted(symbols))),),
    )
    problem = builder.node(
        circuit.id,
        "problem",
        "Problem",
        (("name", label(circuit.id)),),
        (
            ("symbols", tuple(sorted(symbols))),
            ("equations", tuple(sorted(equations))),
            ("requests", (request,)),
        ),
        (
            (
                "unit_definitions",
                tuple(sorted(circuit.reference_ids(identity("Circuit", "unit_definitions")))),
            ),
        ),
    )
    model_id = builder.identity(model.id, "model")
    result = DomainModel(
        model_id,
        SCHEMA_ID,
        "2",
        (problem,),
        tuple(builder.nodes[key] for key in sorted(builder.nodes)),
        label(circuit.id) + " equations",
    )
    return TransformationResult(
        REPRESENTATION,
        result,
        OriginMap(
            snapshot.project.id,
            snapshot.project.revision,
            tuple(OriginLink(key, builder.origins[key]) for key in sorted(builder.origins)),
        ),
    )
