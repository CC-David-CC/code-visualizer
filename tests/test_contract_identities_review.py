"""Publication review regressions: private-name bypass and reference version scope."""

from dataclasses import replace

import pytest

from code_visualizer.domain.computation import BackendDefinition
from code_visualizer.domain.identifiers import (
    BundlePublication,
    ContractDefinition,
    ContractKind,
    NamespaceGrant,
    NamespaceOwnership,
)
from code_visualizer.domain.intentional import BundleReference, DomainSchema
from code_visualizer.domain.transformation import Representation, TransformationDefinition
from code_visualizer.execution.backends import RegisteredBackend
from code_visualizer.extensions.publication import publication_manifest
from code_visualizer.extensions.registry import (
    DomainExtensionBundle,
    DomainExtensionRegistry,
    GeneratorContribution,
)
from code_visualizer.generation.transformation import RegisteredTransformation

OWNER = "org.example.publisher"
OWNERSHIP = NamespaceOwnership((NamespaceGrant("org.example", OWNER),))


def _never_run(*_):
    pytest.fail("Publication validation must not execute implementation code")


def _backend(identity, representation, *, schema_version=None):
    return RegisteredBackend(
        BackendDefinition(
            identity,
            "1",
            "Backend",
            representation,
            "opaque-schema" if schema_version is not None else None,
            schema_version,
        ),
        _never_run,
    )


@pytest.mark.parametrize("kind", ["backend", "schema", "transformation"])
def test_private_bundle_cannot_claim_granted_names_through_contributions(kind):
    registry = DomainExtensionRegistry(namespace_ownership=OWNERSHIP)
    baseline = DomainExtensionBundle("existing-draft", "1")
    registry.register(baseline)
    candidate = DomainExtensionBundle("private-draft", "1")
    if kind == "backend":
        candidate = replace(
            candidate, backends=(_backend("org.example.rogue", Representation("local-input")),)
        )
    elif kind == "schema":
        candidate = replace(
            candidate,
            schemas=(
                DomainSchema(
                    "opaque-schema",
                    "org.example.rogue",
                    "1",
                    bundle=BundleReference(candidate.id, candidate.version),
                ),
            ),
        )
    else:
        candidate = replace(
            candidate,
            transformations=(
                RegisteredTransformation(
                    TransformationDefinition(
                        "org.example.rogue",
                        "1",
                        Representation("local-input"),
                        Representation("local-output"),
                    ),
                    _never_run,
                ),
            ),
        )
    with pytest.raises(ValueError, match="granted namespace"):
        registry.register(candidate)
    assert registry.bundles() == (baseline,)
    assert registry.backend("org.example.rogue", "1") is None
    assert registry.transformations() == ()
    # Atomic failure must not reserve either the rejected bundle or contribution IDs.
    registry.register(DomainExtensionBundle("private-draft", "1"))


def test_local_drafts_can_consume_a_public_representation_without_claiming_ownership():
    backend = _backend("local-backend", Representation("org.example.input"))
    registry = DomainExtensionRegistry(namespace_ownership=OWNERSHIP)
    registry.register(DomainExtensionBundle("private-draft", "1", backends=(backend,)))
    assert registry.backend("local-backend", "1") is backend
    with pytest.raises(ValueError, match="published"):
        publication_manifest(registry, "private-draft", "1")


@pytest.mark.parametrize(
    "surface",
    [
        "backend-input",
        "transformation-source",
        "transformation-target",
        "generator-source",
        "generator-target",
        "backend-schema",
        "transformation-source-schema",
        "transformation-target-schema",
        "bundle-dependency",
    ],
)
def test_published_reference_versions_are_validated_before_registration(surface):
    registry = DomainExtensionRegistry(namespace_ownership=OWNERSHIP)
    valid = Representation("org.example.input", "1")
    invalid = Representation("org.example.input", "bad@version")
    candidate = DomainExtensionBundle(
        "org.example.bundle", "1", publication=BundlePublication(OWNER)
    )
    if surface == "backend-input":
        candidate = replace(candidate, backends=(_backend("org.example.backend", invalid),))
    elif surface == "backend-schema":
        candidate = replace(
            candidate,
            backends=(_backend("org.example.backend", valid, schema_version="bad@version"),),
        )
    elif surface.startswith("transformation"):
        transformation = RegisteredTransformation(
            TransformationDefinition(
                "org.example.transform",
                "1",
                invalid if surface == "transformation-source" else valid,
                invalid if surface == "transformation-target" else valid,
            ),
            _never_run,
        )
        if surface == "transformation-source-schema":
            transformation = replace(
                transformation, schema_id="opaque-schema", schema_version="bad@version"
            )
        elif surface == "transformation-target-schema":
            transformation = replace(
                transformation,
                target_schema_id="opaque-schema",
                target_schema_version="bad@version",
            )
        candidate = replace(candidate, transformations=(transformation,))
    elif surface.startswith("generator"):
        candidate = replace(
            candidate,
            generators=(
                GeneratorContribution(
                    "local-generator-key",
                    "Generator",
                    invalid if surface == "generator-source" else valid,
                    invalid if surface == "generator-target" else valid,
                    _never_run,
                ),
            ),
        )
    else:
        candidate = replace(
            candidate, required_bundles=(BundleReference("org.example.dependency", "bad@version"),)
        )
    with pytest.raises(ValueError, match="version"):
        registry.register(candidate)
    assert registry.bundles() == ()


def test_publication_resolves_exact_representation_versions_through_declared_dependencies():
    registry = DomainExtensionRegistry(namespace_ownership=OWNERSHIP)
    representation = ContractDefinition(ContractKind.REPRESENTATION, "org.example.input", "1")
    provider = DomainExtensionBundle(
        "org.example.ir", "1", publication=BundlePublication(OWNER), contracts=(representation,)
    )
    registry.register(provider)
    consumer = DomainExtensionBundle(
        "org.example.backend_bundle",
        "1",
        publication=BundlePublication(OWNER),
        backends=(_backend("org.example.backend", Representation(representation.id, "2")),),
        required_bundles=(BundleReference(provider.id, provider.version),),
    )
    registry.register(consumer)
    with pytest.raises(ValueError, match=r"representation|Representation"):
        publication_manifest(registry, consumer.id, consumer.version)
    assert registry.backend("org.example.backend", "1") is consumer.backends[0]

    matching = replace(
        consumer,
        id="org.example.matching",
        backends=(
            _backend("org.example.matching_backend", Representation(representation.id, "1")),
        ),
    )
    registry.register(matching)
    manifest = publication_manifest(registry, matching.id, matching.version)
    assert representation in manifest.references
    assert representation not in manifest.contracts

    undeclared = replace(
        matching,
        id="org.example.undeclared",
        required_bundles=(),
        backends=(
            _backend("org.example.undeclared_backend", Representation(representation.id, "1")),
        ),
    )
    registry.register(undeclared)
    with pytest.raises(ValueError, match=r"representation|Representation"):
        publication_manifest(registry, undeclared.id, undeclared.version)
