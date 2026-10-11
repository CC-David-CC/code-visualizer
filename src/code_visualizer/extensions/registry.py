"""Complete, versioned domain contributions composed explicitly by the host.

Only immutable data and BundleReference values are persisted. Callables here are
trusted implementation code supplied at the composition boundary, never by a project.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from code_visualizer.domain.identifiers import (
    BundlePublication,
    ContractDefinition,
    ContractKind,
    ContractReference,
    NamespaceOwnership,
    resolve_contract_references,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    DomainIssue,
    DomainModel,
    DomainSchema,
)
from code_visualizer.domain.notation import NotationDefinition
from code_visualizer.domain.project import Project
from code_visualizer.domain.resources import DataResource, ResourceLogicalTypeReference
from code_visualizer.domain.semantic import SemanticObject, SemanticRelation
from code_visualizer.domain.transformation import OriginMap, Representation
from code_visualizer.domain.value_contracts import value_contract_references
from code_visualizer.domain.values import CanonicalValue, ResourceReference
from code_visualizer.execution.backends import RegisteredBackend
from code_visualizer.execution.resource_interpretation import (
    ResourceInterpretation,
    ResourceReader,
    resource_closure,
)
from code_visualizer.generation.transformation import RegisteredTransformation

if TYPE_CHECKING:
    from code_visualizer.generation.emitter import GeneratedProject


@dataclass(frozen=True, slots=True)
class SemanticContribution:
    objects: tuple[SemanticObject, ...] = ()
    relations: tuple[SemanticRelation, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainParticipant:
    """Uniform read contract over specialized and schema-driven physical storage."""

    id: str
    provider_id: str
    title: str
    representation: Representation
    root_ids: tuple[str, ...]
    object_ids: tuple[str, ...]
    command_prefix: str
    schema_id: str | None = None


@dataclass(frozen=True, slots=True)
class DomainProvider:
    id: str
    title: str
    domains: Callable[[Project], tuple[DomainParticipant, ...]]


@dataclass(frozen=True, slots=True)
class GeneratorInput:
    """A disposable composed build, never a canonical project submitted for re-lowering."""

    project: Project
    origins: OriginMap


@dataclass(frozen=True, slots=True)
class GeneratorContribution:
    id: str
    title: str
    source: Representation
    target: Representation
    generate: Callable[[GeneratorInput], GeneratedProject]


@dataclass(frozen=True, slots=True)
class RuntimeDecoration:
    semantic_id: str
    label: str


@dataclass(frozen=True, slots=True)
class RuntimePresentationContribution:
    id: str
    decorate: Callable[[tuple[str, ...]], tuple[RuntimeDecoration, ...]]


@dataclass(frozen=True, slots=True)
class DomainExtensionBundle:
    id: str
    version: str
    schemas: tuple[DomainSchema, ...] = ()
    validators: tuple[Callable[[Project, DomainModel], tuple[DomainIssue, ...]], ...] = ()
    semantic_indexers: tuple[Callable[[Project, DomainModel], SemanticContribution], ...] = ()
    notations: tuple[NotationDefinition, ...] = ()
    transformations: tuple[RegisteredTransformation, ...] = ()
    generators: tuple[GeneratorContribution, ...] = ()
    runtime_presenters: tuple[RuntimePresentationContribution, ...] = ()
    providers: tuple[DomainProvider, ...] = ()
    backends: tuple[RegisteredBackend, ...] = ()
    required_bundles: tuple[BundleReference, ...] = ()
    reference_models: tuple[DomainModel, ...] = ()
    publication: BundlePublication | None = None
    contracts: tuple[ContractDefinition, ...] = ()
    workspace_validators: tuple[Callable[[Project], tuple[DomainIssue, ...]], ...] = ()
    canonical_value_validators: tuple[Callable[[CanonicalValue], None], ...] = ()
    resource_interpretations: tuple[ResourceInterpretation, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemaLanguageContribution:
    """Disposable behavior for an authored schema; this does not own that schema."""

    id: str
    schema_id: str
    schema_version: str
    validators: tuple[Callable[[Project, DomainModel], tuple[DomainIssue, ...]], ...] = ()
    notations: tuple[NotationDefinition, ...] = ()
    transformations: tuple[RegisteredTransformation, ...] = ()


class DomainExtensionRegistry:
    """Deterministic static registry; registration order has no semantic meaning."""

    def __init__(
        self,
        bundles: Iterable[DomainExtensionBundle] = (),
        *,
        languages: tuple[SchemaLanguageContribution, ...] = (),
        resolution_issues: tuple[DomainIssue, ...] = (),
        host_registry: DomainExtensionRegistry | None = None,
        namespace_ownership: NamespaceOwnership | None = None,
    ) -> None:
        from code_visualizer.extensions.publication import FIRST_PARTY_OWNERSHIP

        self._bundles: dict[tuple[str, str], DomainExtensionBundle] = {}
        self._contributions: set[tuple[str, str]] = set()
        self._languages = tuple(sorted(languages, key=lambda item: item.id))
        self.resolution_issues = resolution_issues
        self.host_registry = host_registry if host_registry is not None else self
        self.namespace_ownership: NamespaceOwnership = (
            namespace_ownership
            if namespace_ownership is not None
            else host_registry.namespace_ownership
            if host_registry is not None
            else FIRST_PARTY_OWNERSHIP
        )
        self._public_contracts: dict[ContractDefinition, tuple[str, str]] = {}
        self._publication_scopes: dict[
            BundleReference,
            tuple[tuple[DomainExtensionBundle, ...], tuple[ContractDefinition, ...]],
        ] = {}
        self._resolved_publications: dict[BundleReference, tuple[ContractDefinition, ...]] = {}
        for bundle in bundles:
            self.register(bundle)
        for language in self._languages:
            identities = (
                ("language", language.id),
                *(("notation", item.id) for item in language.notations),
                *(("transformation", item.definition.key) for item in language.transformations),
            )
            if len(set(identities)) != len(identities) or set(identities) & self._contributions:
                raise ValueError(f"Ambiguous authored contributions in language {language.id!r}")
            if any(item.schema_id != language.schema_id for item in language.notations):
                raise ValueError("Authored notations must retain their exact schema scope")
            if any(
                (item.schema_id, item.schema_version)
                != (language.schema_id, language.schema_version)
                for item in language.transformations
            ):
                raise ValueError("Authored transformations must retain their exact schema scope")
            self._contributions.update(identities)

    def register(self, bundle: DomainExtensionBundle) -> None:
        key = (bundle.id, bundle.version)
        if not all(key):
            raise ValueError("A bundle needs a nonempty identity and version")
        if key in self._bundles:
            raise ValueError(f"Bundle {bundle.id}@{bundle.version} is already registered")
        identities = (
            *(("schema", f"{item.id}@{item.version}") for item in bundle.schemas),
            *(("notation", item.id) for item in bundle.notations),
            *(("transformation", item.definition.key) for item in bundle.transformations),
            *(("generator", item.id) for item in bundle.generators),
            *(("runtime", item.id) for item in bundle.runtime_presenters),
            *(("provider", item.id) for item in bundle.providers),
            *(("backend", item.definition.key) for item in bundle.backends),
            *(
                ("resource", f"{item.logical_type.id}@{item.logical_type.version}")
                for item in bundle.resource_interpretations
            ),
        )
        if len(identities) != len(set(identities)):
            raise ValueError(f"Duplicate contribution inside bundle {bundle.id}@{bundle.version}")
        duplicates = set(identities) & self._contributions
        if duplicates:
            raise ValueError(f"Ambiguous extension contributions: {sorted(duplicates)!r}")
        for schema in bundle.schemas:
            if schema.bundle is None or (schema.bundle.id, schema.bundle.version) != key:
                raise ValueError(
                    f"Schema {schema.id!r} must explicitly name its owning bundle "
                    f"{bundle.id}@{bundle.version}"
                )
        public_contracts = self._publication_contracts(bundle)
        if len(public_contracts) != len(set(public_contracts)):
            raise ValueError("A bundle cannot declare the same public contract twice")
        conflicts = set(public_contracts) & self._public_contracts.keys()
        if conflicts:
            raise ValueError(
                f"Public contracts already have an implementation: {sorted(conflicts)!r}"
            )
        if len(set(bundle.required_bundles)) != len(bundle.required_bundles):
            raise ValueError("Duplicate bundle dependency")
        if BundleReference(bundle.id, bundle.version) in bundle.required_bundles:
            raise ValueError("A bundle cannot depend on itself")
        model_ids = [model.id for model in bundle.reference_models]
        previous_ids = {model.id for model in self.reference_models()}
        if len(set(model_ids)) != len(model_ids) or set(model_ids) & previous_ids:
            raise ValueError("Reference model identities must have exactly one bundle owner")
        self._contributions.update(identities)
        self._bundles[key] = bundle
        self._public_contracts.update((contract, key) for contract in public_contracts)
        # Only static inert definitions are cached. A new registration invalidates
        # closure proofs; resource payloads, project values and failures are not cached.
        self._publication_scopes.clear()
        self._resolved_publications.clear()

    def _publication_contracts(
        self, bundle: DomainExtensionBundle
    ) -> tuple[ContractDefinition, ...]:
        if bundle.publication is None:
            if bundle.contracts:
                raise ValueError("Public contract definitions require bundle publication metadata")
            claimed = (
                bundle.id,
                *(schema.namespace for schema in bundle.schemas),
                *(item.definition.id for item in bundle.backends),
                *(item.definition.id for item in bundle.transformations),
            )
            if any(
                grant.contains(identity)
                for identity in claimed
                for grant in self.namespace_ownership.grants
            ):
                raise ValueError("A granted namespace cannot be claimed by a private bundle")
            return ()
        contracts = (
            ContractDefinition(ContractKind.BUNDLE, bundle.id, bundle.version),
            *(
                ContractDefinition(ContractKind.SCHEMA_NAMESPACE, schema.namespace, schema.version)
                for schema in bundle.schemas
            ),
            *(
                ContractDefinition(ContractKind.REPRESENTATION, schema.namespace, schema.version)
                for schema in bundle.schemas
            ),
            *(
                ContractDefinition(
                    ContractKind.BACKEND, item.definition.id, item.definition.version
                )
                for item in bundle.backends
            ),
            *(
                ContractDefinition(
                    ContractKind.TRANSFORMATION, item.definition.id, item.definition.version
                )
                for item in bundle.transformations
            ),
            *bundle.contracts,
        )
        for contract in contracts:
            self.namespace_ownership.require_owner(contract.id, bundle.publication.owner_id)
        from code_visualizer.extensions.publication import derive_public_contract_references

        # One typed walk supplies both assembly syntax checks and publication
        # closure checks. Assembly remains independent of registration order.
        derive_public_contract_references(bundle)
        return contracts

    def publication_contracts(self, bundle_id: str, version: str) -> tuple[ContractDefinition, ...]:
        bundle = self.get(bundle_id, version)
        if bundle is None or bundle.publication is None:
            raise ValueError("Only published bundles have a public contract manifest")
        return tuple(
            sorted(
                contract
                for contract, owner in self._public_contracts.items()
                if owner == (bundle_id, version)
            )
        )

    def _publication_scope(
        self, reference: BundleReference
    ) -> tuple[tuple[DomainExtensionBundle, ...], tuple[ContractDefinition, ...]]:
        previous = self._publication_scopes.get(reference)
        if previous is not None:
            return previous
        closure = self.bundle_closure(reference)
        if any(bundle.publication is None for bundle in closure):
            raise ValueError("Published bundles cannot depend on private implementation bundles")
        contracts = tuple(
            contract
            for bundle in closure
            for contract in self.publication_contracts(bundle.id, bundle.version)
        )
        self._publication_scopes[reference] = (closure, contracts)
        return closure, contracts

    def validate_publication_closure(
        self, reference: BundleReference
    ) -> tuple[ContractDefinition, ...]:
        """Validate each supplier within its own exact dependencies, then the root.

        No recursive manifest call and no installed-but-unrelated provider can
        authorize a missing dependency. Returned references are exact evidence.
        """
        from code_visualizer.extensions.publication import derive_public_contract_references

        previous = self._resolved_publications.get(reference)
        if previous is not None:
            return previous
        closure, _ = self._publication_scope(reference)
        resolved: tuple[ContractDefinition, ...] = ()
        for bundle in closure:
            scope, definitions = self._publication_scope(BundleReference(bundle.id, bundle.version))
            uses = derive_public_contract_references(
                bundle,
                schemas=tuple(schema for candidate in scope for schema in candidate.schemas),
                require_schema_resolution=True,
            )
            resolved = resolve_contract_references(uses, definitions)
        self._resolved_publications[reference] = resolved
        return resolved

    def resolve_contract_references(
        self, reference: BundleReference, references: Iterable[ContractReference]
    ) -> tuple[ContractDefinition, ...]:
        """Resolve supplied public uses inside one fully valid dependency closure."""
        self.validate_publication_closure(reference)
        _, definitions = self._publication_scope(reference)
        return resolve_contract_references(references, definitions)

    def resolve_registered_contract_references(
        self, references: Iterable[ContractReference]
    ) -> tuple[ContractDefinition, ...]:
        """Resolve caller input contracts from published providers in this host.

        Inputs need not be owned by a backend's dependencies. Each selected
        provider must nevertheless have a complete valid publication closure.
        """
        resolved = resolve_contract_references(references, self._public_contracts)
        owners = {self._public_contracts[contract] for contract in resolved}
        for bundle_id, version in sorted(owners):
            self.validate_publication_closure(BundleReference(bundle_id, version))
        return resolved

    def reference_models(self) -> tuple[DomainModel, ...]:
        return tuple(
            sorted(
                (model for bundle in self.bundles() for model in bundle.reference_models),
                key=lambda model: model.id,
            )
        )

    def validate_value(self, value: CanonicalValue) -> None:
        for bundle in self.bundles():
            for validator in bundle.canonical_value_validators:
                validator(value)

    def resource_interpretation(
        self, logical_type: ResourceLogicalTypeReference
    ) -> ResourceInterpretation | None:
        return next(
            (
                item
                for bundle in self.bundles()
                for item in bundle.resource_interpretations
                if item.logical_type == logical_type
            ),
            None,
        )

    def resource_closure(
        self, references: tuple[ResourceReference, ...], reader: ResourceReader
    ) -> tuple[ResourceReference, ...]:
        """Read-only dependency interpretation, shared by host, freeze and portable admission."""

        def validate(descriptor: DataResource) -> None:
            self.resolve_registered_contract_references(value_contract_references(descriptor))

        return resource_closure(references, reader, self.resource_interpretation, validate=validate)

    def validate_workspace(self, project: Project) -> tuple[DomainIssue, ...]:
        return tuple(
            issue
            for bundle in self.bundles()
            for validator in bundle.workspace_validators
            for issue in validator(project)
        )

    def bundle_closure(self, reference: BundleReference) -> tuple[DomainExtensionBundle, ...]:
        """Dependency-first deterministic closure; missing code/data never disappears."""
        visited: set[BundleReference] = set()
        visiting: set[BundleReference] = set()
        result: list[DomainExtensionBundle] = []

        def visit(current: BundleReference) -> None:
            if current in visiting:
                raise ValueError("Bundle dependency cycle")
            if current in visited:
                return
            bundle = self.get(current.id, current.version)
            if bundle is None:
                raise ValueError(f"Required bundle {current.id}@{current.version} is unavailable")
            visiting.add(current)
            for child in sorted(bundle.required_bundles, key=lambda item: (item.id, item.version)):
                visit(child)
            visiting.remove(current)
            visited.add(current)
            result.append(bundle)

        visit(reference)
        return tuple(result)

    def get(self, bundle_id: str, version: str) -> DomainExtensionBundle | None:
        return self._bundles.get((bundle_id, version))

    def bundles(self) -> tuple[DomainExtensionBundle, ...]:
        return tuple(self._bundles[key] for key in sorted(self._bundles))

    def providers(self) -> tuple[DomainProvider, ...]:
        return tuple(
            sorted(
                (item for bundle in self.bundles() for item in bundle.providers),
                key=lambda item: item.id,
            )
        )

    def domains(self, project: Project) -> tuple[DomainParticipant, ...]:
        participants = tuple(
            item for provider in self.providers() for item in provider.domains(project)
        )
        ids = [item.id for item in participants]
        if len(ids) != len(set(ids)):
            raise ValueError("Domain providers returned duplicate domain identities")
        owned = [identity for item in participants for identity in item.object_ids]
        if len(owned) != len(set(owned)):
            raise ValueError("Domain providers claim the same canonical identity")
        return tuple(sorted(participants, key=lambda item: item.id))

    def transformations(self) -> tuple[RegisteredTransformation, ...]:
        return tuple(
            sorted(
                (
                    *(item for bundle in self.bundles() for item in bundle.transformations),
                    *(item for language in self._languages for item in language.transformations),
                ),
                key=lambda item: item.definition.key,
            )
        )

    def transformations_for(
        self, schema_id: str, schema_version: str
    ) -> tuple[RegisteredTransformation, ...]:
        return tuple(
            item
            for item in self.transformations()
            if item.schema_id is None
            or (item.schema_id, item.schema_version) == (schema_id, schema_version)
        )

    def authored_validators_for(
        self, schema_id: str, schema_version: str
    ) -> tuple[Callable[[Project, DomainModel], tuple[DomainIssue, ...]], ...]:
        return tuple(
            validator
            for language in self._languages
            if (language.schema_id, language.schema_version) == (schema_id, schema_version)
            for validator in language.validators
        )

    def validate_model(self, project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
        """Validate a canonical or disposable model against its registered domain behavior."""

        bundle = self.bundle_for_model(project, model)
        schema = project.domain_workspace.schema(model.schema_id)
        validators = bundle.validators if bundle is not None and schema in bundle.schemas else ()
        return tuple(
            issue
            for validator in (
                *validators,
                *self.authored_validators_for(model.schema_id, model.schema_version),
            )
            for issue in validator(project, model)
        )

    def notations_for(
        self, schema_id: str, schema_version: str | None = None
    ) -> tuple[NotationDefinition, ...]:
        return tuple(
            sorted(
                (
                    *(
                        item
                        for bundle in self.bundles()
                        for item in bundle.notations
                        if item.schema_id in {None, schema_id}
                        and (
                            schema_version is None
                            or not any(schema.id == schema_id for schema in bundle.schemas)
                            or any(
                                (schema.id, schema.version) == (schema_id, schema_version)
                                for schema in bundle.schemas
                            )
                        )
                    ),
                    *(
                        item
                        for language in self._languages
                        if (language.schema_id, language.schema_version)
                        == (schema_id, schema_version)
                        for item in language.notations
                    ),
                ),
                key=lambda item: item.id,
            )
        )

    def generators(self) -> tuple[GeneratorContribution, ...]:
        return tuple(
            sorted(
                (item for bundle in self.bundles() for item in bundle.generators),
                key=lambda item: item.id,
            )
        )

    def backends(self) -> tuple[RegisteredBackend, ...]:
        return tuple(
            sorted(
                (item for bundle in self.bundles() for item in bundle.backends),
                key=lambda item: item.definition.key,
            )
        )

    def backend(self, backend_id: str, version: str) -> RegisteredBackend | None:
        return next(
            (
                item
                for item in self.backends()
                if (item.definition.id, item.definition.version) == (backend_id, version)
            ),
            None,
        )

    def runtime_decorations(self, active_ids: tuple[str, ...]) -> tuple[RuntimeDecoration, ...]:
        decorations = {
            (item.semantic_id, item.label)
            for bundle in self.bundles()
            for presenter in bundle.runtime_presenters
            for item in presenter.decorate(active_ids)
        }
        if any(identity not in active_ids for identity, _label in decorations):
            raise ValueError("Runtime presentation must decorate an active semantic identity")
        return tuple(RuntimeDecoration(identity, label) for identity, label in sorted(decorations))

    def bundle_for_model(
        self, project: Project, model: DomainModel
    ) -> DomainExtensionBundle | None:
        schema = project.domain_workspace.schema(model.schema_id)
        if schema is None or schema.bundle is None:
            return None
        return self.get(schema.bundle.id, schema.bundle.version)


def validate_extension_requirements(
    project: Project,
    registry: DomainExtensionRegistry | None = None,
) -> tuple[DomainIssue, ...]:
    """Build diagnostics only: unavailable code never makes persisted data vanish."""

    workspace = project.domain_workspace
    if not (
        workspace.schemas
        or workspace.models
        or workspace.bundle_references
        or workspace.language_definitions
    ):
        return ()
    from code_visualizer.extensions.languages import resolve_domain_languages

    registry = resolve_domain_languages(project, registry)
    required = set(workspace.bundle_references)
    required.update(schema.bundle for schema in workspace.schemas if schema.bundle is not None)
    issues: list[DomainIssue] = list(registry.resolution_issues)
    for reference in sorted(required, key=lambda item: (item.id, item.version)):
        if registry.get(reference.id, reference.version) is None:
            issues.append(
                DomainIssue(
                    "DOMAIN_EXTENSION_MISSING",
                    f"Required extension {reference.id}@{reference.version} is unavailable; "
                    "data is preserved",
                    reference.id,
                    incomplete=True,
                )
            )
        else:
            try:
                registry.bundle_closure(reference)
            except ValueError as exc:
                issues.append(
                    DomainIssue(
                        "DOMAIN_EXTENSION_DEPENDENCY", str(exc), reference.id, incomplete=True
                    )
                )
    for schema in workspace.schemas:
        if schema.bundle is None:
            continue
        bundle = registry.get(schema.bundle.id, schema.bundle.version)
        if bundle is None:
            continue
        registered = next((item for item in bundle.schemas if item.id == schema.id), None)
        if registered != schema:
            issues.append(
                DomainIssue(
                    "DOMAIN_EXTENSION_SCHEMA_MISMATCH",
                    f"Schema {schema.id}@{schema.version} differs from its "
                    "registered implementation",
                    schema.id,
                    incomplete=True,
                )
            )
    for model in workspace.models:
        bundle = registry.bundle_for_model(project, model)
        if bundle is not None and not any(
            item.code == "DOMAIN_EXTENSION_SCHEMA_MISMATCH" and item.object_id == model.schema_id
            for item in issues
        ):
            for validator in bundle.validators:
                issues.extend(validator(project, model))
        for validator in registry.authored_validators_for(model.schema_id, model.schema_version):
            issues.extend(validator(project, model))
    registered_models = {model.id: model for model in registry.reference_models()}
    for model in workspace.models:
        registered_model = registered_models.get(model.id)
        if registered_model is not None and registered_model != model:
            issues.append(
                DomainIssue(
                    "DOMAIN_EXTENSION_REFERENCE_MISMATCH",
                    "Reference vocabulary differs from its immutable bundle definition",
                    model.id,
                    incomplete=True,
                )
            )
    issues.extend(registry.validate_workspace(project))
    return tuple(issues)
