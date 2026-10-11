"""Saved-source adaptive experiment; execution never imports this authoring helper."""

from math import comb

from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue
from code_visualizer.extensions.adaptive_diffusion.domain import (
    BUNDLE,
    SCHEMA_ID,
    adaptive_schema,
    identity,
)
from code_visualizer.extensions.adaptive_fields.domain import SCHEMA_ID as FIELD_SCHEMA
from code_visualizer.extensions.adaptive_fields.domain import identity as field_id
from code_visualizer.extensions.adaptive_fields.units import quantity
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.space import ALGEBRA_SCHEMA_ID
from code_visualizer.extensions.foundations.space import identity as space_id


def _node(
    node_id: str,
    concept: str,
    properties: tuple[tuple[str, CanonicalValue], ...],
    children: tuple[tuple[str, tuple[str, ...]], ...] = (),
    references: tuple[tuple[str, tuple[str, ...]], ...] = (),
) -> IntentionalNode:
    return IntentionalNode(
        node_id,
        concept,
        tuple(PropertyValue(concept + ":" + key, value) for key, value in properties),
        tuple(RoleBinding(concept + ":" + key, ids) for key, ids in children),
        tuple(RoleBinding(concept + ":" + key, ids) for key, ids in references),
    )


def adaptive_diffusion_project() -> Project:
    policy_definition = next(
        concept for concept in adaptive_schema().concepts if concept.id == identity("Policy")
    )
    policy = IntentionalNode(
        "adaptive:policy",
        policy_definition.id,
        (
            PropertyValue(identity("Policy", "name"), "Error-controlled conservative adaptation"),
            *(
                PropertyValue(prop.id, prop.default)
                for prop in policy_definition.properties
                if prop.default is not None
            ),
        ),
    )
    space = DomainModel(
        "adaptive:space-model",
        ALGEBRA_SCHEMA_ID,
        "2",
        ("adaptive:space", "adaptive:frame"),
        (
            _node(
                "adaptive:space",
                space_id("Space"),
                (("name", "Periodic laboratory interval"), ("dimension", 1)),
                (("axes", ("adaptive:x",)),),
            ),
            _node("adaptive:x", space_id("Axis"), (("name", "x"), ("ordinal", 0))),
            _node(
                "adaptive:frame",
                space_id("Frame"),
                (("name", "Laboratory frame"),),
                references=(("space", ("adaptive:space",)),),
            ),
        ),
        "Physical frame",
    )
    field = DomainModel(
        "adaptive:field-model",
        FIELD_SCHEMA,
        "1",
        ("adaptive:region", "adaptive:field"),
        (
            _node(
                "adaptive:region",
                field_id("Interval"),
                (
                    ("name", "One metre periodic region"),
                    ("length", quantity(1, "meter")),
                    ("area", quantity(1, "square_meter")),
                ),
                references=(("frame", ("adaptive:frame",)), ("axis", ("adaptive:x",))),
            ),
            _node(
                "adaptive:field",
                field_id("Field"),
                (
                    ("name", "Conserved concentration"),
                    ("scale", quantity(1, "kilogram_per_cubic_meter")),
                    ("quantity_kind", "linear"),
                ),
                references=(("region", ("adaptive:region",)),),
            ),
        ),
        "Concentration field",
    )
    modes = tuple(
        _node(
            f"adaptive:mode:{harmonic}",
            identity("Mode"),
            (
                ("name", f"Cosine mode {harmonic}"),
                ("mode", harmonic),
                ("amplitude", quantity(comb(16, 8 - harmonic) / 32768, "kilogram_per_cubic_meter")),
            ),
        )
        for harmonic in range(1, 9)
    )
    model = DomainModel(
        "adaptive:experiment",
        SCHEMA_ID,
        "1",
        ("adaptive:problem",),
        (
            _node(
                "adaptive:problem",
                identity("Problem"),
                (
                    ("name", "Adaptive periodic diffusion pulse"),
                    ("diffusivity", quantity(0.001, "square_meter_per_second")),
                    ("boundary", "periodic"),
                ),
                (("initial", ("adaptive:initial",)), ("policy", ("adaptive:policy",))),
                (("field", ("adaptive:field",)),),
            ),
            _node(
                "adaptive:initial",
                identity("FourierInitial"),
                (
                    ("name", "Localized positive pulse"),
                    ("mean", quantity(1 + comb(16, 8) / 65536, "kilogram_per_cubic_meter")),
                    ("center", quantity(0.5, "meter")),
                ),
                (("modes", tuple(mode.id for mode in modes)),),
            ),
            policy,
            *modes,
        ),
        "Adaptive continuum experiment",
    )
    closure = builtin_registry().bundle_closure(BUNDLE)
    return Project(
        "physical:adaptive-diffusion",
        "Adaptive periodic diffusion pulse",
        (),
        description="A conserved concentration on a fixed 1 m interval. Error-driven refinement "
        "and coarsening produce disposable cell supports; field and policy identity stay authored.",
        domain_workspace=DomainWorkspace(
            tuple(schema for bundle in closure for schema in bundle.schemas),
            (
                model,
                field,
                space,
                *(reference for bundle in closure for reference in bundle.reference_models),
            ),
            tuple(BundleReference(bundle.id, bundle.version) for bundle in closure),
        ),
    )
