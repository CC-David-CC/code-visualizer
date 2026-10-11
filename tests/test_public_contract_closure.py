"""Every inert published use must resolve in its exact declared ownership scope."""

from dataclasses import dataclass, replace

import pytest

from code_visualizer.domain.computation import BackendDefinition
from code_visualizer.domain.identifiers import (
    BundlePublication,
    ContractDefinition,
    ContractKind,
    ContractReference,
    NamespaceGrant,
    NamespaceOwnership,
    resolve_contract_references,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.notation_syntax import NotationObjects, VisualRepeat, VisualText
from code_visualizer.domain.resources import (
    DataResource,
    ResourceLogicalTypeReference,
    TensorDescriptor,
)
from code_visualizer.domain.transformation import Representation, TransformationDefinition
from code_visualizer.domain.values import (
    Dimension,
    DimensionPower,
    QuantityValue,
    TensorDType,
    UnitReference,
    ValueConstraints,
)
from code_visualizer.execution.backends import RegisteredBackend
from code_visualizer.extensions.publication import (
    derive_public_contract_references,
    publication_manifest,
)
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.generation.transformation import RegisteredTransformation

OWNER = "org.example.publisher"
PUBLICATION = BundlePublication(OWNER)
OWNERSHIP = NamespaceOwnership((NamespaceGrant("org.example", OWNER),))
UNIT = ContractDefinition(ContractKind.UNIT, "org.example.units:meter", "1")
BASIS = ContractDefinition(ContractKind.DIMENSION_BASIS, "org.example.units:basis.length", "1")
DIMENSION = Dimension((DimensionPower(BASIS.id, 1),))
QUANTITY = QuantityValue(7, UnitReference(UNIT.id, UNIT.version, DIMENSION))
UNIT_DEPENDENCIES = (BundleReference("org.example.units", "1"),)


def _never_run(*_args):
    pytest.fail("Reference discovery must never execute an implementation")


def _bundle(identity, **kwargs):
    return DomainExtensionBundle(identity, "1", publication=PUBLICATION, **kwargs)


def _registry(*bundles):
    return DomainExtensionRegistry(bundles, namespace_ownership=OWNERSHIP)


def _provider(*contracts):
    return _bundle("org.example.units", contracts=contracts or (UNIT, BASIS))


def _consumer(surface, *, quantity=QUANTITY, dependencies=UNIT_DEPENDENCIES):
    identity = "org.example.consumer"
    prop = PropertyDefinition("property-object", "Length", ValueKind.QUANTITY)
    if surface == "default":
        prop = replace(prop, default=quantity)
    elif surface == "choice":
        prop = replace(prop, choices=(quantity,))
    elif surface == "constraint":
        prop = replace(prop, value_constraints=ValueConstraints(dimension=quantity.unit.dimension))
    schema = DomainSchema(
        "schema-object",
        identity,
        "1",
        (ConceptDefinition("concept-object", "Thing", (prop,)),),
        bundle=BundleReference(identity, "1"),
    )
    models = ()
    if surface == "model":
        models = (
            DomainModel(
                "model-object",
                schema.id,
                "1",
                ("node-object",),
                (
                    IntentionalNode(
                        "node-object", "concept-object", (PropertyValue(prop.id, quantity),)
                    ),
                ),
            ),
        )
    return _bundle(
        identity, schemas=(schema,), reference_models=models, required_bundles=dependencies
    )


@pytest.mark.parametrize(
    "kind", [kind for kind in ContractKind if kind is not ContractKind.DIMENSION_BASIS]
)
def test_only_immutable_dimension_basis_references_may_omit_exact_version(kind):
    with pytest.raises(ValueError, match="Only immutable dimension basis"):
        ContractReference(kind, "org.example.contract", None)


def test_definition_is_not_a_reference_and_empty_bundle_does_not_consume_its_exports():
    bundle = _provider()
    assert derive_public_contract_references(bundle) == ()
    assert publication_manifest(_registry(bundle), bundle.id, bundle.version).references == ()


@pytest.mark.parametrize("surface", ("default", "choice", "constraint", "model"))
def test_all_schema_and_reference_model_values_derive_resolved_exact_contracts(surface):
    provider, consumer = _provider(), _consumer(surface)
    registry = _registry(consumer, provider)  # Composition order does not grant ownership.
    manifest = publication_manifest(registry, consumer.id, "1")
    assert BASIS in manifest.references
    if surface != "constraint":
        assert UNIT in manifest.references
    assert all(isinstance(reference, ContractDefinition) for reference in manifest.references)
    assert (
        manifest.references
        == publication_manifest(_registry(provider, consumer), consumer.id, "1").references
    )


@pytest.mark.parametrize("surface", ("default", "choice", "constraint", "model"))
@pytest.mark.parametrize("fault", ("absent", "unrelated", "wrong_version"))
def test_typed_values_cannot_borrow_unavailable_or_undeclared_contracts(surface, fault):
    if fault == "absent":
        provider = _provider(ContractDefinition(ContractKind.UNIT, "org.example.units:other", "1"))
        consumer = _consumer(surface)
    elif fault == "unrelated":
        provider, consumer = _provider(), _consumer(surface, dependencies=())
    else:
        provider = replace(_provider(), version="2")
        consumer = _consumer(surface)
    registry = _registry(provider, consumer)
    with pytest.raises(ValueError, match=r"Missing public contract|unavailable"):
        publication_manifest(registry, consumer.id, "1")


@pytest.mark.parametrize("surface", ("default", "choice", "model"))
def test_unit_references_require_exact_definition_version(surface):
    consumer = _consumer(
        surface, quantity=replace(QUANTITY, unit=replace(QUANTITY.unit, version="2"))
    )
    with pytest.raises(ValueError, match=r"unit .*@2"):
        publication_manifest(_registry(_provider(), consumer), consumer.id, "1")


def test_unversioned_basis_resolves_exactly_one_declared_definition_never_latest():
    reference = ContractReference(ContractKind.DIMENSION_BASIS, BASIS.id, None)
    assert resolve_contract_references((reference,), (BASIS,)) == (BASIS,)
    with pytest.raises(ValueError, match=r"Ambiguous.*dimension_basis"):
        resolve_contract_references((reference,), (BASIS, replace(BASIS, version="2")))
    consumer = _consumer("constraint")
    with pytest.raises(ValueError, match=r"Ambiguous.*dimension_basis"):
        publication_manifest(
            _registry(_provider(UNIT, BASIS, replace(BASIS, version="2")), consumer),
            consumer.id,
            "1",
        )
    unrelated = _bundle("org.example.other", contracts=(replace(BASIS, version="2"),))
    registry = _registry(_provider(), consumer, unrelated)
    assert BASIS in publication_manifest(registry, consumer.id, "1").references
    with pytest.raises(ValueError, match="Ambiguous"):
        registry.resolve_registered_contract_references((reference,))


def test_transitive_provider_must_validate_inside_its_own_closure():
    provider = _consumer("default", dependencies=())
    root = _bundle(
        "org.example.root",
        required_bundles=(
            BundleReference(provider.id, "1"),
            BundleReference("org.example.units", "1"),
        ),
    )
    with pytest.raises(ValueError, match="Missing public contract"):
        publication_manifest(_registry(_provider(), provider, root), root.id, "1")


def test_global_runtime_resolution_uses_published_suppliers_and_validates_their_dependencies():
    provider = _provider()
    registry = _registry(provider)
    reference = ContractReference(UNIT.kind, UNIT.id, UNIT.version)
    assert registry.resolve_registered_contract_references((reference,)) == (UNIT,)
    broken = replace(provider, required_bundles=(BundleReference("org.example.missing", "1"),))
    with pytest.raises(ValueError, match="unavailable"):
        _registry(broken).resolve_registered_contract_references((reference,))
    private = DomainExtensionBundle(
        "private",
        "1",
        backends=(
            RegisteredBackend(
                BackendDefinition("org.private.backend", "1", "Private", Representation("local")),
                _never_run,
            ),
        ),
    )
    with pytest.raises(ValueError, match="Missing public contract"):
        _registry(private).resolve_registered_contract_references(
            (ContractReference(ContractKind.BACKEND, "org.private.backend", "1"),)
        )


@dataclass(frozen=True, slots=True)
class _BackendWithResourceMetadata(BackendDefinition):
    resource: DataResource | None = None


def test_inert_registered_definition_metadata_discovers_resource_type_and_nested_units():
    logical_type = ContractDefinition(
        ContractKind.RESOURCE_LOGICAL_TYPE, "org.example.data:field", "1"
    )
    representation = ContractDefinition(ContractKind.REPRESENTATION, "org.example.ir", "1")
    metadata = DataResource(
        "opaque-resource",
        "a" * 64,
        0,
        "application/octet-stream",
        tensor=TensorDescriptor(TensorDType.FLOAT64, (0,), unit=QUANTITY.unit),
        logical_type=ResourceLogicalTypeReference(logical_type.id, "1"),
    )
    definition = _BackendWithResourceMetadata(
        "org.example.backend",
        "1",
        "Backend",
        Representation(representation.id, "1"),
        resource=metadata,
    )
    bundle = _bundle(
        "org.example.backend_bundle",
        contracts=(representation, UNIT, BASIS),
        backends=(RegisteredBackend(definition, _never_run),),
    )
    assert ContractReference(
        logical_type.kind, logical_type.id, "1"
    ) in derive_public_contract_references(bundle)
    assert ContractReference(UNIT.kind, UNIT.id, UNIT.version) in derive_public_contract_references(
        bundle
    )
    assert ContractReference(BASIS.kind, BASIS.id, None) in derive_public_contract_references(
        bundle
    )
    with pytest.raises(ValueError, match="resource_logical_type"):
        publication_manifest(_registry(bundle), bundle.id, "1")
    supplied = replace(bundle, contracts=(representation, UNIT, BASIS, logical_type))
    assert logical_type in publication_manifest(_registry(supplied), bundle.id, "1").references


def test_callbacks_and_their_captured_values_are_not_executed_or_treated_as_declarations():
    def callback(*_args):
        assert QUANTITY
        pytest.fail("The implementation is not publication data")

    bundle = _bundle(
        "org.example.callbacks",
        validators=(callback,),
        workspace_validators=(callback,),
        canonical_value_validators=(callback,),
    )
    assert derive_public_contract_references(bundle) == ()
    assert publication_manifest(_registry(bundle), bundle.id, "1").references == ()


def test_nested_notation_and_cross_domain_roles_resolve_opaque_schema_ownership():
    foreign_id = "org.example.foreign"
    foreign_schema = DomainSchema(
        "opaque-foreign-schema",
        foreign_id,
        "3",
        (ConceptDefinition("opaque-foreign-concept", "Foreign"),),
        bundle=BundleReference(foreign_id, "1"),
    )
    foreign = _bundle(foreign_id, schemas=(foreign_schema,))
    consumer = _consumer(
        "constraint",
        dependencies=(BundleReference("org.example.units", "1"), BundleReference(foreign.id, "1")),
    )
    concept = replace(
        consumer.schemas[0].concepts[0],
        reference_roles=(
            RoleDefinition("opaque-role", "Foreign reference", ("opaque-foreign-concept",)),
        ),
    )
    consumer = replace(
        consumer,
        schemas=(replace(consumer.schemas[0], concepts=(concept,)),),
        notations=(
            NotationDefinition(
                "opaque-notation",
                "Foreign notation",
                NotationKind.COMPOSED,
                body=VisualRepeat(
                    "repeat",
                    NotationObjects("query", "opaque-foreign-concept", foreign_schema.id, "3"),
                    "item",
                    VisualText("label", "Nothing is a namespace here"),
                ),
            ),
        ),
    )
    namespace = ContractDefinition(ContractKind.SCHEMA_NAMESPACE, foreign_id, "3")
    assert (
        namespace
        in publication_manifest(
            _registry(_provider(), foreign, consumer), consumer.id, "1"
        ).references
    )
    missing = replace(consumer, required_bundles=(BundleReference("org.example.units", "1"),))
    with pytest.raises(ValueError, match="Missing published schema scope"):
        publication_manifest(_registry(_provider(), foreign, missing), missing.id, "1")


def test_transformation_prerequisites_are_exact_public_references():
    representation = ContractDefinition(ContractKind.REPRESENTATION, "org.example.ir", "1")
    dependency = ContractDefinition(ContractKind.TRANSFORMATION, "org.example.transform.first", "1")
    definition = TransformationDefinition(
        "org.example.transform.second",
        "1",
        Representation(representation.id),
        Representation(representation.id),
        depends_on=(dependency.id + "@1",),
    )
    bundle = _bundle(
        "org.example.transform",
        contracts=(representation,),
        transformations=(RegisteredTransformation(definition, _never_run),),
    )
    with pytest.raises(ValueError, match="transformation"):
        publication_manifest(_registry(bundle), bundle.id, "1")
    supplied = replace(bundle, contracts=(representation, dependency))
    assert dependency in publication_manifest(_registry(supplied), bundle.id, "1").references


@pytest.mark.parametrize("surface", ("default", "choice", "constraint", "model"))
def test_registration_and_publication_share_contract_syntax_discovery(surface):
    quantity = replace(
        QUANTITY,
        unit=replace(QUANTITY.unit, dimension=Dimension((DimensionPower("unqualified_basis", 1),))),
    )
    registry = _registry()
    with pytest.raises(ValueError, match="Global contract"):
        registry.register(_consumer(surface, quantity=quantity))
    assert registry.bundles() == ()


def test_unit_reference_version_syntax_is_validated_during_registration():
    quantity = replace(QUANTITY, unit=replace(QUANTITY.unit, version="bad@version"))
    with pytest.raises(ValueError, match="version"):
        _registry(_consumer("default", quantity=quantity))
