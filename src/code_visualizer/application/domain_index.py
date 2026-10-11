"""Schema and intentional-instance contributions to the shared semantic index."""

from __future__ import annotations

import hashlib
from dataclasses import fields, is_dataclass

from code_visualizer.domain.intentional import node_label
from code_visualizer.domain.language import AuthoredDomainLanguage, ValidatorDefinition
from code_visualizer.domain.language_structure import language_records
from code_visualizer.domain.notation import NotationDefinition
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import (
    SemanticObject,
    SemanticObjectKind,
    SemanticProperty,
    SemanticRelation,
    SemanticRelationKind,
)
from code_visualizer.domain.transformation import TransformationDefinition
from code_visualizer.extensions.languages import resolve_domain_languages
from code_visualizer.extensions.registry import DomainExtensionRegistry, SemanticContribution


def domain_relation_id(
    kind: SemanticRelationKind,
    source_id: str,
    target_id: str,
    role_id: str = "",
) -> str:
    payload = "\0".join((kind, source_id, target_id, role_id))
    digest = hashlib.sha256(payload.encode()).hexdigest()[:24]
    return f"relation:domain:{digest}"


def domain_semantic_contribution(
    project: Project,
    registry: DomainExtensionRegistry | None = None,
) -> SemanticContribution:
    workspace = project.domain_workspace
    if not workspace.schemas and not workspace.models and not workspace.language_definitions:
        return SemanticContribution()
    objects: list[SemanticObject] = []
    relations: list[SemanticRelation] = []

    def relate(
        kind: SemanticRelationKind,
        source: str,
        target: str,
        *,
        role_id: str = "",
        label: str = "",
    ) -> None:
        relations.append(
            SemanticRelation(
                domain_relation_id(kind, source, target, role_id),
                kind,
                source,
                target,
                label,
                source,
            )
        )

    for schema in workspace.schemas:
        objects.append(
            SemanticObject(
                schema.id,
                SemanticObjectKind.DOMAIN_SCHEMA,
                schema.namespace,
                parent_id=project.id,
                detail=schema.description,
                properties=(SemanticProperty("version", schema.version),),
            )
        )
        relate(SemanticRelationKind.CONTAINS, project.id, schema.id)
        for concept in schema.concepts:
            objects.append(
                SemanticObject(
                    concept.id,
                    SemanticObjectKind.CONCEPT_DEFINITION,
                    concept.name,
                    parent_id=schema.id,
                    detail=concept.description,
                )
            )
            relate(SemanticRelationKind.CONTAINS, schema.id, concept.id)
            for prop in concept.properties:
                objects.append(
                    SemanticObject(
                        prop.id,
                        SemanticObjectKind.PROPERTY_DEFINITION,
                        prop.name,
                        parent_id=concept.id,
                        detail=prop.value_kind.value,
                        properties=(SemanticProperty("required", str(prop.required).lower()),),
                    )
                )
                relate(SemanticRelationKind.CONTAINS, concept.id, prop.id)
            for containment, roles in (
                (True, concept.containment_roles),
                (False, concept.reference_roles),
            ):
                for role in roles:
                    objects.append(
                        SemanticObject(
                            role.id,
                            SemanticObjectKind.ROLE_DEFINITION,
                            role.name,
                            parent_id=concept.id,
                            detail="containment" if containment else "reference",
                            properties=(
                                SemanticProperty("minimum", str(role.min_count)),
                                SemanticProperty("maximum", str(role.max_count)),
                                SemanticProperty("ordered", str(role.ordered).lower()),
                            ),
                        )
                    )
                    relate(SemanticRelationKind.CONTAINS, concept.id, role.id)
                    for allowed_id in role.allowed_concept_ids:
                        relate(SemanticRelationKind.REFERENCES, role.id, allowed_id, label="allows")

    for model in workspace.models:
        model_schema = workspace.schema(model.schema_id)
        if model_schema is None:
            continue  # Integrity validation diagnoses incomplete externally supplied snapshots.
        objects.append(
            SemanticObject(
                model.id,
                SemanticObjectKind.DOMAIN,
                model.title or model_schema.namespace,
                parent_id=project.id,
                properties=(
                    SemanticProperty("schema_id", model_schema.id),
                    SemanticProperty("schema_version", model.schema_version),
                ),
            )
        )
        relate(SemanticRelationKind.CONTAINS, project.id, model.id)
        relate(SemanticRelationKind.REFERENCES, model.id, model_schema.id, label="schema")
        owners = {
            child: node.id
            for node in model.nodes
            for role in node.children
            for child in role.node_ids
        }
        for root_id in model.roots:
            relate(SemanticRelationKind.CONTAINS, model.id, root_id)
        for node in model.nodes:
            node_concept = model_schema.concept(node.concept_id)
            properties = (
                SemanticProperty("model_id", model.id),
                SemanticProperty("schema_id", model_schema.id),
                SemanticProperty("concept_id", node.concept_id),
                *(SemanticProperty(item.property_id, str(item.value)) for item in node.properties),
            )
            objects.append(
                SemanticObject(
                    node.id,
                    SemanticObjectKind.INTENTION,
                    node_label(model_schema, node),
                    parent_id=owners.get(node.id, model.id),
                    detail=node_concept.name if node_concept is not None else node.concept_id,
                    properties=properties,
                )
            )
            relate(SemanticRelationKind.REFERENCES, node.id, node.concept_id, label="instance of")
            for containment, bindings in ((True, node.children), (False, node.references)):
                for binding in bindings:
                    bound_role = (
                        node_concept.role(binding.role_id) if node_concept is not None else None
                    )
                    for target_id in binding.node_ids:
                        relate(
                            SemanticRelationKind.CONTAINS
                            if containment
                            else SemanticRelationKind.REFERENCES,
                            node.id,
                            target_id,
                            role_id=binding.role_id,
                            label=bound_role.name if bound_role is not None else binding.role_id,
                        )
    authored_references: list[tuple[str, str, str]] = []
    for language in workspace.language_definitions:
        for identity, record, parent_id in language_records(language):
            label = str(getattr(record, "title", "") or getattr(record, "name", "") or identity)
            kind = SemanticObjectKind.TEMPLATE
            if isinstance(record, AuthoredDomainLanguage):
                kind = SemanticObjectKind.LANGUAGE_DEFINITION
            elif isinstance(record, ValidatorDefinition):
                kind = SemanticObjectKind.VALIDATION_RULE
                label = record.message
            elif isinstance(record, NotationDefinition):
                kind = SemanticObjectKind.NOTATION_DEFINITION
            elif isinstance(record, TransformationDefinition):
                kind = SemanticObjectKind.TRANSFORMATION
            owner = parent_id or language.schema_id
            objects.append(
                SemanticObject(
                    identity,
                    kind,
                    label,
                    parent_id=owner,
                    detail=type(record).__name__,
                    properties=(SemanticProperty("language_id", language.id),),
                )
            )
            relate(SemanticRelationKind.CONTAINS, owner, identity)
            if is_dataclass(record) and not isinstance(record, type):
                for field in fields(record):
                    target = getattr(record, field.name)
                    if field.name.endswith("_id") and isinstance(target, str):
                        authored_references.append((identity, target, field.name))
    known_ids = {item.id for item in objects}
    for source, target, label in authored_references:
        if target in known_ids:
            relate(SemanticRelationKind.REFERENCES, source, target, role_id=label, label=label)

    registry = resolve_domain_languages(project, registry)
    for model in workspace.models:
        bundle = registry.bundle_for_model(project, model)
        model_schema = workspace.schema(model.schema_id)
        if bundle is None or model_schema not in bundle.schemas:
            continue
        for contributor in bundle.semantic_indexers:
            contribution = contributor(project, model)
            objects.extend(contribution.objects)
            relations.extend(contribution.relations)
    ids = [item.id for item in objects]
    relation_ids = [item.id for item in relations]
    if len(ids) != len(set(ids)) or len(relation_ids) != len(set(relation_ids)):
        raise ValueError("Domain index contribution has duplicate semantic identities")
    return SemanticContribution(tuple(objects), tuple(relations))
