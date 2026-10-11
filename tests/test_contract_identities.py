"""Publication owns public vocabulary; project IDs and private drafts stay local."""

from dataclasses import replace

import pytest

from code_visualizer.domain.identifiers import (
    BundlePublication,
    ContractDefinition,
    ContractKind,
    NamespaceGrant,
    NamespaceOwnership,
    validate_global_contract_id,
)
from code_visualizer.domain.intentional import BundleReference, DomainSchema
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.publication import publication_manifest
from code_visualizer.extensions.registry import DomainExtensionBundle, DomainExtensionRegistry
from code_visualizer.protocol.identity import publication_from_proto, publication_to_proto
from code_visualizer.protocol.v1 import identity_pb2


@pytest.mark.parametrize(
    "identity",
    [
        "org.example.control.pid",
        "com.mycompany.solver.fem",
        "foundation.math",
        "foundation.units.si:meter",
        "org.example.math:TensorSymbol",
        "code_visualizer.program",
    ],
)
def test_qualified_contract_names(identity):
    validate_global_contract_id(identity)


@pytest.mark.parametrize(
    "identity",
    [
        "spice",
        "meter",
        "field",
        "Org.example.unit",
        "org..example",
        "org.example@1",
        " org.example",
        "org.example ",
        "org.ex\u0430mple",
        "org.example:",
        "org.example:a:b",
        "org.example/a",
        "org." + "a" * 252,
    ],
)
def test_unowned_or_noncanonical_public_names_rejected(identity):
    with pytest.raises(ValueError, match="Global contract"):
        validate_global_contract_id(identity)


def _registry():
    return DomainExtensionRegistry(
        namespace_ownership=NamespaceOwnership(
            (
                NamespaceGrant("org.example", "org.example.publisher"),
                NamespaceGrant("com.other", "com.other.publisher"),
            )
        )
    )


def _bundle(identity="org.example.domain", **changes):
    return replace(
        DomainExtensionBundle(
            identity, "1", publication=BundlePublication("org.example.publisher")
        ),
        **changes,
    )


def test_host_grant_enforced_atomically_and_owner_cannot_change_between_versions():
    registry = _registry()
    registry.register(_bundle())
    baseline = registry.bundles()
    for candidate in (
        _bundle("com.other.stolen"),
        _bundle(version="2", publication=BundlePublication("com.other.publisher")),
        _bundle(publication=None),
        _bundle("org.example2.lookalike"),
    ):
        with pytest.raises(ValueError):
            registry.register(candidate)
        assert registry.bundles() == baseline
    registry.register(_bundle(version="2"))
    assert len(registry.bundles()) == 2


def test_conflicting_namespace_grants_cannot_depend_on_registration_order():
    first = NamespaceGrant("org.example", "org.example.publisher")
    second = NamespaceGrant("org.example.control", "com.other.publisher")
    for grants in ((first, second), (second, first), (first, first)):
        with pytest.raises(ValueError, match="ownership"):
            NamespaceOwnership(grants)


def test_private_bundle_has_no_public_manifest_and_cannot_export_contracts():
    registry = DomainExtensionRegistry((DomainExtensionBundle("local", "1"),))
    with pytest.raises(ValueError, match="published"):
        publication_manifest(registry, "local", "1")
    with pytest.raises(ValueError, match="publication metadata"):
        registry.register(
            DomainExtensionBundle(
                "draft",
                "1",
                contracts=(ContractDefinition(ContractKind.UNIT, "org.example:meter", "1"),),
            )
        )


def test_schema_namespace_cannot_be_reclaimed_under_another_project_schema_id():
    registry = _registry()
    first = _bundle("org.example.first")
    first = replace(
        first,
        schemas=(
            DomainSchema(
                "opaque-schema-1",
                "org.example.schema",
                "1",
                bundle=BundleReference(first.id, first.version),
            ),
        ),
    )
    registry.register(first)
    second = _bundle(
        "org.example.second",
        schemas=(
            DomainSchema(
                "opaque-schema-2",
                "org.example.schema",
                "1",
                bundle=BundleReference("org.example.second", "1"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="already have an implementation"):
        registry.register(second)
    assert registry.bundles() == (first,)


@pytest.mark.parametrize("kind", list(ContractKind))
def test_every_public_vocabulary_kind_requires_owner_and_unique_definition(kind):
    registry = _registry()
    contract = ContractDefinition(kind, "org.example.vocabulary:entry", "1")
    registry.register(_bundle(contracts=(contract,)))
    with pytest.raises(ValueError, match="already have an implementation"):
        registry.register(_bundle("org.example.other", contracts=(contract,)))
    with pytest.raises(ValueError, match="namespace grant"):
        registry.register(
            _bundle("org.example.foreign", contracts=(replace(contract, id="com.other:entry"),))
        )


def test_production_bundles_all_have_lossless_public_manifests():
    registry = builtin_registry()
    for bundle in registry.bundles():
        manifest = publication_manifest(registry, bundle.id, bundle.version)
        wire = publication_to_proto(manifest)
        binary = wire.SerializeToString(deterministic=True)
        restored = publication_from_proto(identity_pb2.PublicationManifest.FromString(binary))
        assert restored == manifest
        assert publication_to_proto(restored).SerializeToString(deterministic=True) == binary


def test_publication_requires_available_acyclic_public_dependencies():
    registry = _registry()
    a = _bundle("org.example.a", required_bundles=(BundleReference("org.example.b", "1"),))
    registry.register(a)
    with pytest.raises(ValueError, match="unavailable"):
        publication_manifest(registry, a.id, a.version)
    registry.register(
        _bundle("org.example.b", required_bundles=(BundleReference(a.id, a.version),))
    )
    with pytest.raises(ValueError, match="cycle"):
        publication_manifest(registry, a.id, a.version)
