"""Units are ordinary intentions; conversion never guesses physical equivalence."""

from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_installation import bundle_installation
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    ValueKind,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import ComplexValue, Dimension, QuantityValue, UnitReference
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.units import (
    SCHEMA_ID,
    UnitCatalog,
    UnitError,
    identity,
    units_schema,
    validate_units,
)
from code_visualizer.extensions.foundations.units_si import BUNDLE as SI_BUNDLE
from code_visualizer.extensions.foundations.units_si import (
    si_catalog,
    si_contracts,
    si_model,
    validate_si_reference,
    validate_si_value,
    validate_si_workspace,
)
from code_visualizer.extensions.registry import validate_extension_requirements
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.persistence.store import ProjectStore
from code_visualizer.protocol.domain import (
    model_from_proto,
    model_to_proto,
    schema_from_proto,
    schema_to_proto,
)
from code_visualizer.protocol.values import canonical_value_from_proto, canonical_value_to_proto
from code_visualizer.sdk import CodeVisualizerClient


def _project(model=None):
    return Project(
        "units-project",
        "Units",
        (),
        domain_workspace=DomainWorkspace((units_schema(),), (model or si_model(),)),
    )


def _change(model, node_id, field, value):
    node = model.node(node_id)
    assert node is not None
    property_id = node.concept_id + ":" + field
    changed = replace(
        node,
        properties=tuple(
            PropertyValue(prop.property_id, value) if prop.property_id == property_id else prop
            for prop in node.properties
        ),
    )
    return replace(
        model, nodes=tuple(changed if node.id == node_id else node for node in model.nodes)
    )


def _unit(name):
    return si_catalog().unit("foundation.units.si:" + name)


def _custom_model(*, context=None, scale=0.0254):
    """A third party reuses the same schema and SI basis through normal references."""

    def prop(concept, field, value):
        return PropertyValue(identity(concept, field), value)

    inch = IntentionalNode(
        "custom:inch",
        identity("UnitDefinition"),
        (
            prop("UnitDefinition", "name", "inch"),
            prop("UnitDefinition", "symbol", "in"),
            prop("UnitDefinition", "contract_id", "org.example.units:inch"),
            prop("UnitDefinition", "version", "1"),
        ),
        (RoleBinding(identity("UnitDefinition", "dimension"), ("custom:factor",)),),
    )
    factor = IntentionalNode(
        "custom:factor",
        identity("DimensionFactor"),
        (prop("DimensionFactor", "exponent", 1),),
        references=(RoleBinding(identity("DimensionFactor", "basis"), ("si-v1:basis:length",)),),
    )
    properties = (
        prop("Conversion", "name", "inch to meter"),
        prop("Conversion", "scale", scale),
        prop("Conversion", "offset", 0),
    )
    if context is not None:
        properties += (prop("Conversion", "context", context),)
    conversion = IntentionalNode(
        "custom:conversion",
        identity("Conversion"),
        properties,
        references=(
            RoleBinding(identity("Conversion", "source"), (inch.id,)),
            RoleBinding(identity("Conversion", "target"), ("si-v1:unit:meter",)),
        ),
    )
    return DomainModel(
        "custom:units",
        SCHEMA_ID,
        "1",
        (inch.id, conversion.id),
        (inch, factor, conversion),
        "Example unit vocabulary",
    )


def test_si_is_one_ordinary_model_with_qualified_unit_and_shared_basis_contracts():
    project = _project()
    assert not validate_domain_workspace(project.domain_workspace)
    assert not validate_units(project, si_model())
    assert not validate_si_workspace(project)
    assert len(si_catalog().units) == 28
    assert len(si_contracts()) == 35
    assert {power.basis_id for power in _unit("volt").dimension.powers} == {
        "foundation.units.si:basis.mass",
        "foundation.units.si:basis.length",
        "foundation.units.si:basis.time",
        "foundation.units.si:basis.electric_current",
    }
    assert {power.basis_id: power.exponent for power in _unit("newton").dimension.powers} == {
        "foundation.units.si:basis.mass": 1,
        "foundation.units.si:basis.length": 1,
        "foundation.units.si:basis.time": -2,
    }
    assert _unit("millivolt").dimension == _unit("volt").dimension
    assert _unit("one").dimension == Dimension()


@pytest.mark.parametrize(
    ("source", "target", "value", "expected"),
    [
        ("millimeter", "meter", 1200, 1.2),
        ("meter", "millimeter", 3, 3000),
        ("centimeter", "kilometer", 100000, 1),
        ("milliampere", "ampere", 2500, 2.5),
        ("degree_celsius", "kelvin", 0, 273.15),
        ("kelvin", "degree_celsius", 273.15, 0.0),
        ("millivolt", "volt", 1200, 1.2),
    ],
)
def test_declared_affine_conversion_is_composable_bidirectional_and_typed(
    source, target, value, expected
):
    result = si_catalog().convert(QuantityValue(value, _unit(source)), _unit(target))
    assert result == QuantityValue(expected, _unit(target))


def test_third_party_units_use_same_schema_and_shared_basis_without_kernel_changes():
    catalog = UnitCatalog.from_models((si_model(), _custom_model()))
    inch = catalog.unit("org.example.units:inch")
    assert inch.dimension == _unit("meter").dimension
    assert catalog.convert(QuantityValue(12, inch), _unit("centimeter")).magnitude == 30.48
    assert catalog == UnitCatalog.from_models((_custom_model(), si_model()))
    assert catalog == UnitCatalog.from_models(
        (replace(si_model(), nodes=tuple(reversed(si_model().nodes))), _custom_model())
    )


def test_equal_dimensions_do_not_invent_a_conversion_and_context_is_explicit():
    model = _custom_model(context="org.example.calibration:bench_a")
    catalog = UnitCatalog.from_models((si_model(), model))
    quantity = QuantityValue(1, catalog.unit("org.example.units:inch"))
    with pytest.raises(UnitError) as caught:
        catalog.convert(quantity, _unit("meter"))
    assert caught.value.issue.code == "UNIT_CONVERSION_UNAVAILABLE"
    assert (
        catalog.convert(
            quantity, _unit("meter"), context="org.example.calibration:bench_a"
        ).magnitude
        == 0.0254
    )
    with pytest.raises(UnitError, match="different declared dimensions"):
        catalog.convert(quantity, _unit("second"))


@pytest.mark.parametrize(
    ("node_id", "field", "value", "code"),
    [
        ("si-v1:conversion:millimeter:meter", "scale", 0, "UNIT_CONVERSION_SCALE"),
        ("si-v1:meter:dimension:length", "exponent", 0, "UNIT_DIMENSION_EXPONENT"),
        ("si-v1:unit:meter", "contract_id", "meter", "UNIT_CONTRACT_ID"),
        (
            "si-v1:unit:meter",
            "contract_id",
            "foundation.units.si:second",
            "UNIT_DUPLICATE_CONTRACT",
        ),
    ],
)
def test_invalid_definition_states_report_deterministic_diagnostics(node_id, field, value, code):
    with pytest.raises(UnitError) as caught:
        UnitCatalog.from_models((_change(si_model(), node_id, field, value),))
    assert caught.value.issue.code == code


def test_conflicting_or_redundant_conversion_paths_are_rejected_before_execution():
    model = si_model()
    original = model.node("si-v1:conversion:millimeter:meter")
    copied = replace(original, id="si-v1:redundant-conversion")
    model = replace(model, roots=(*model.roots, copied.id), nodes=(*model.nodes, copied))
    with pytest.raises(UnitError) as caught:
        UnitCatalog.from_models((model,))
    assert caught.value.issue.code == "UNIT_CONVERSION_AMBIGUOUS"


def test_incompatible_conversion_dimensions_are_rejected():
    model = si_model()
    original = model.node("si-v1:conversion:millimeter:meter")
    changed = replace(
        original,
        references=(
            original.references[0],
            RoleBinding(identity("Conversion", "target"), ("si-v1:unit:second",)),
        ),
    )
    model = replace(
        model, nodes=tuple(changed if node.id == changed.id else node for node in model.nodes)
    )
    with pytest.raises(UnitError) as caught:
        UnitCatalog.from_models((model,))
    assert caught.value.issue.code == "UNIT_DIMENSION_MISMATCH"


def test_published_si_unit_cannot_claim_another_dimension_version_or_definition():
    forged = UnitReference(_unit("meter").id, "1", _unit("second").dimension)
    assert validate_si_reference(forged)[0].code == "UNIT_REFERENCE_DIMENSION"
    assert (
        validate_si_reference(replace(_unit("meter"), version="99"))[0].code
        == "UNIT_DEFINITION_MISSING"
    )
    with pytest.raises(UnitError, match="registered dimension"):
        validate_si_value(QuantityValue(1, forged))
    altered = _change(si_model(), "si-v1:unit:meter", "symbol", "s")
    assert validate_si_workspace(_project(altered))[0].code == "UNIT_IMMUTABLE_DEFINITION"
    altered = _change(si_model(), "si-v1:basis:length", "name", "Time")
    assert validate_si_workspace(_project(altered))[0].code == "UNIT_IMMUTABLE_BASIS"
    altered = _change(si_model(), "si-v1:conversion:degree_celsius:kelvin", "offset", 12)
    assert validate_si_workspace(_project(altered))[0].code == "UNIT_IMMUTABLE_CONVERSION"


def test_conversion_handles_complex_scaling_and_reports_unsupported_offsets_and_overflow():
    value = QuantityValue(ComplexValue(1000.0, 2000.0), _unit("millivolt"))
    assert si_catalog().convert(value, _unit("volt")).magnitude == ComplexValue(1.0, 2.0)
    with pytest.raises(UnitError) as caught:
        si_catalog().convert(
            QuantityValue(ComplexValue(1.0, 2.0), _unit("degree_celsius")), _unit("kelvin")
        )
    assert caught.value.issue.code == "UNIT_COMPLEX_OFFSET_UNSUPPORTED"
    with pytest.raises(UnitError) as caught:
        si_catalog().convert(QuantityValue(1e308, _unit("kilometer")), _unit("millimeter"))
    assert caught.value.issue.code == "UNIT_NUMERIC_RANGE"


def test_model_schema_and_quantity_reuse_existing_json_and_protobuf_boundaries_losslessly():
    project = _project()
    encoded = normalized_project_json(project)
    restored = project_from_json(encoded)
    assert restored.domain_workspace == project.domain_workspace
    assert normalized_project_json(restored) == encoded
    model_message = model_to_proto(si_model())
    schema_message = schema_to_proto(units_schema())
    assert (
        model_from_proto(
            type(model_message).FromString(model_message.SerializeToString(deterministic=True))
        )
        == si_model()
    )
    assert (
        schema_from_proto(
            type(schema_message).FromString(schema_message.SerializeToString(deterministic=True))
        )
        == units_schema()
    )
    quantity = QuantityValue(12.8, _unit("volt"))
    message = canonical_value_to_proto(quantity)
    assert (
        canonical_value_from_proto(
            type(message).FromString(message.SerializeToString(deterministic=True))
        )
        == quantity
    )
    assert UnitCatalog.from_models(restored.domain_workspace.models) == si_catalog()


def test_si_installation_uses_existing_authority_history_and_native_recovery(tmp_path):
    empty = Project("unit-authority-project", "Units", ())
    registry = builtin_registry()
    store = ProjectStore(tmp_path / "unit-project")
    store.initialize(empty)
    authority = ProjectAuthority(empty, store=store)
    client = CodeVisualizerClient(authority, actor_id="unit-author")
    operations = bundle_installation(empty.domain_workspace, registry, SI_BUNDLE)
    result = client.transaction(operations)
    assert isinstance(result, CommandAccepted)
    assert authority.revision == 1
    installed = authority.snapshot()
    assert installed.domain_workspace.models == (si_model(),)
    assert installed.domain_workspace.schemas == (units_schema(),)
    assert not validate_extension_requirements(installed, registry)
    assert bundle_installation(installed.domain_workspace, registry, SI_BUNDLE) == ()
    recovered = ProjectAuthority(store.recover(), store=store)
    recovery_client = CodeVisualizerClient(recovered, actor_id="unit-author")
    assert recovered.snapshot().domain_workspace == installed.domain_workspace
    assert isinstance(recovery_client.undo(), CommandAccepted)
    assert recovered.snapshot().domain_workspace == DomainWorkspace()
    assert isinstance(recovery_client.redo(), CommandAccepted)
    assert recovered.snapshot().domain_workspace == installed.domain_workspace
    assert UnitCatalog.from_models(recovered.snapshot().domain_workspace.models) == si_catalog()
    changed = _project(_change(si_model(), "si-v1:unit:meter", "symbol", "seconds"))
    assert "DOMAIN_EXTENSION_REFERENCE_MISMATCH" in {
        issue.code for issue in validate_extension_requirements(changed, registry)
    }


def test_registered_si_contract_validation_covers_arbitrary_domains_and_external_values():
    forged = QuantityValue(1, replace(_unit("meter"), dimension=_unit("second").dimension))
    concept = ConceptDefinition(
        "org.example.testing:QuantityHolder",
        "Quantity holder",
        (
            PropertyDefinition(
                "org.example.testing:value",
                "Value",
                ValueKind.QUANTITY,
                default=forged,
                choices=(forged,),
            ),
        ),
    )
    schema = DomainSchema("org.example.testing:schema", "org.example.testing", "1", (concept,))
    node = IntentionalNode(
        "local-quantity-holder", concept.id, (PropertyValue(concept.properties[0].id, forged),)
    )
    model = DomainModel("quantity-model", schema.id, "1", (node.id,), (node,))
    project = replace(_project(), domain_workspace=DomainWorkspace((schema,), (model,)))
    issues = validate_si_workspace(project)
    dimension_issues = [issue for issue in issues if issue.code == "UNIT_REFERENCE_DIMENSION"]
    assert len(dimension_issues) == 3
    assert {issue.field for issue in dimension_issues} == {
        concept.properties[0].id,
        "default",
        "choices",
    }
    registry = builtin_registry()
    registry.validate_value(QuantityValue(7, _unit("meter")))
    with pytest.raises(UnitError) as caught:
        registry.validate_value(forged)
    assert caught.value.issue.code == "UNIT_REFERENCE_DIMENSION"
