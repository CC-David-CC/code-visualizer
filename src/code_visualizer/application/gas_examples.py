"""Author the bounded gas study from ordinary schemas and an explicit input resource."""

from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, ResourceReference
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.space import ALGEBRA_SCHEMA_ID
from code_visualizer.extensions.foundations.space import identity as space_id
from code_visualizer.extensions.hybrid_gas.domain import (
    BUNDLE,
    COMPONENTS,
    SCHEMA_ID,
    gas_schema,
    identity,
)
from code_visualizer.extensions.hybrid_gas.units import quantity


def hybrid_gas_project(calibration: ResourceReference) -> Project:
    """The input reference is authored; the fitted transport coefficient is derived."""
    definitions = {concept.id: concept for concept in gas_schema().concepts}

    def node(
        key: str,
        concept: str,
        name: str,
        properties: tuple[tuple[str, CanonicalValue], ...] = (),
        children: tuple[tuple[str, tuple[str, ...]], ...] = (),
        references: tuple[tuple[str, tuple[str, ...]], ...] = (),
    ) -> IntentionalNode:
        definition = definitions[identity(concept)]
        values = {p.id: p.default for p in definition.properties if p.default is not None}
        values[identity(concept, "name")] = name
        values.update((identity(concept, k), value) for k, value in properties)
        return IntentionalNode(
            "gas:" + key,
            definition.id,
            tuple(PropertyValue(k, v) for k, v in values.items()),
            tuple(
                RoleBinding(identity(concept, k), tuple("gas:" + v for v in ids))
                for k, ids in children
            ),
            tuple(
                RoleBinding(identity(concept, k), tuple("gas:" + v for v in ids))
                for k, ids in references
            ),
        )

    def space_node(
        key: str,
        kind: str,
        props: tuple[tuple[str, CanonicalValue], ...],
        children: tuple[RoleBinding, ...] = (),
        references: tuple[RoleBinding, ...] = (),
    ) -> IntentionalNode:
        return IntentionalNode(
            "gas:" + key,
            space_id(kind),
            tuple(PropertyValue(space_id(kind, k), v) for k, v in props),
            children,
            references,
        )

    space = DomainModel(
        "gas:space-model",
        ALGEBRA_SCHEMA_ID,
        "2",
        ("gas:space", "gas:frame"),
        (
            space_node(
                "space",
                "Space",
                (("name", "Three-dimensional channel"), ("dimension", 3)),
                (RoleBinding(space_id("Space", "axes"), ("gas:x", "gas:y", "gas:z")),),
            ),
            *(
                space_node(axis, "Axis", (("name", axis), ("ordinal", index)))
                for index, axis in enumerate("xyz")
            ),
            space_node(
                "frame",
                "Frame",
                (("name", "Laboratory Cartesian frame"),),
                references=(RoleBinding(space_id("Frame", "space"), ("gas:space",)),),
            ),
        ),
        "Channel space and frame",
    )
    model = DomainModel(
        "gas:experiment",
        SCHEMA_ID,
        "1",
        ("gas:problem",),
        (
            node(
                "problem",
                "Problem",
                "Argon Couette state/flux experiment",
                children=(
                    *((key, (key,)) for key in ("gas", "channel", "slab", "initial", "policy")),
                    ("walls", ("wall:lower", "wall:upper")),
                    ("interfaces", ("face:lower", "face:upper")),
                    ("fields", tuple("field:" + v for v in COMPONENTS)),
                ),
            ),
            node(
                "gas",
                "Gas",
                "Argon with independently measured transport",
                (("calibration", calibration),),
            ),
            node(
                "channel",
                "Channel",
                "Two millimetre planar channel",
                references=(("frame", ("frame",)), ("axis", ("y",))),
            ),
            node("slab", "Slab", "Central quarter-height particle region"),
            node("initial", "Initial", "Uniform gas initially at rest"),
            node("policy", "Policy", "Bounded fixed-interface mean-flow study"),
            *(
                node(
                    "wall:" + side,
                    "Wall",
                    side.title() + " diffuse wall",
                    (("side", side), ("velocity_x", quantity(speed, "meter_per_second"))),
                )
                for side, speed in (("lower", -40), ("upper", 40))
            ),
            *(
                node(
                    "face:" + side,
                    "Interface",
                    side.title() + " state/flux face",
                    (("side", side),),
                )
                for side in ("lower", "upper")
            ),
            *(
                node(
                    "field:" + component,
                    "Field",
                    component.replace("_", " ").title(),
                    (("component", component),),
                )
                for component in COMPONENTS
            ),
        ),
        "Particle / continuum mean-flow experiment",
    )
    closure = builtin_registry().bundle_closure(BUNDLE)
    return Project(
        "physical:hybrid-gas",
        "Argon particle / continuum shear",
        (),
        description="A bounded mean-flow study with disjoint volume ownership, actual particle "
        "crossing fluxes and retained independent transport observations. "
        "It does not claim fluctuation-sensitive or arbitrary rarefied predictions.",
        domain_workspace=DomainWorkspace(
            tuple(schema for bundle in closure for schema in bundle.schemas),
            (model, space, *(m for bundle in closure for m in bundle.reference_models)),
            tuple(BundleReference(bundle.id, bundle.version) for bundle in closure),
        ),
    )
