"""Focused immutable mutations and durable inverses for schema-owned intentions."""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.application.authority import CommandError, Handler, Mutation
from code_visualizer.application.commands import Operation
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    IntentionalNode,
    PropertyValue,
    RoleBinding,
)
from code_visualizer.domain.project import Project
from code_visualizer.persistence.evidence import evidence_content_hash, evidence_from_data
from code_visualizer.persistence.intentional import (
    bundle_from_data,
    bundle_to_data,
    concept_definition_from_data,
    domain_model_from_data,
    domain_model_to_data,
    domain_schema_from_data,
    domain_schema_to_data,
    domain_value_from_data,
    intentional_node_from_data,
    intentional_node_to_data,
    property_definition_from_data,
    role_definition_from_data,
)
from code_visualizer.persistence.values import canonical_value_to_data


def _text(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise CommandError("DOMAIN_COMMAND_PAYLOAD", f"{key} must be nonempty text")
    return value


def _optional_text(payload: dict[str, JsonValue], key: str) -> str | None:
    return None if payload.get(key) is None else _text(payload, key)


def _integer(value: JsonValue, default: int = 0) -> int:
    if value is None:
        return default
    if type(value) is not int:
        raise CommandError("DOMAIN_COMMAND_PAYLOAD", "Index must be an integer")
    return value


def _ids(value: JsonValue) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CommandError("DOMAIN_COMMAND_PAYLOAD", "Expected an array of identities")
    return tuple(str(item) for item in value)


def _model(project: Project, payload: dict[str, JsonValue]) -> DomainModel:
    identity = _text(payload, "model_id")
    model = project.domain_workspace.model(identity)
    if model is None:
        raise CommandError("DOMAIN_MODEL_MISSING", f"Domain model {identity!r} does not exist")
    return model


def _schema(project: Project, payload: dict[str, JsonValue]) -> DomainSchema:
    identity = _text(payload, "schema_id")
    schema = project.domain_workspace.schema(identity)
    if schema is None:
        raise CommandError("DOMAIN_SCHEMA_MISSING", f"Domain schema {identity!r} does not exist")
    return schema


def _node(model: DomainModel, node_id: str) -> IntentionalNode:
    node = model.node(node_id)
    if node is None:
        raise CommandError("DOMAIN_NODE_MISSING", f"Node {node_id!r} does not exist")
    return node


def _with_model(project: Project, model: DomainModel) -> Project:
    return replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            models=tuple(
                model if item.id == model.id else item for item in project.domain_workspace.models
            ),
        ),
    )


def _put_schema(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    schema = domain_schema_from_data(payload.get("schema"))
    before = project.domain_workspace.schema(schema.id)
    values = tuple(
        schema if item.id == schema.id else item for item in project.domain_workspace.schemas
    )
    if before is None:
        index = _integer(payload.get("index"), len(values))
        if not 0 <= index <= len(values):
            raise CommandError("DOMAIN_SCHEMA_INDEX", "Schema index is outside the workspace")
        values = (*values[:index], schema, *values[index:])
    inverse = (
        Operation("domain.schema.delete", {"schema_id": schema.id})
        if before is None
        else Operation("domain.schema.put", {"schema": domain_schema_to_data(before)})
    )
    return Mutation(
        replace(project, domain_workspace=replace(project.domain_workspace, schemas=values)),
        "domain.schema.changed",
        {"schema_id": schema.id},
        (schema.id, *(item.id for item in schema.concepts)),
        inverse,
    )


def _delete_schema(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    schema = _schema(project, payload)
    candidate = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            schemas=tuple(
                item for item in project.domain_workspace.schemas if item.id != schema.id
            ),
        ),
    )
    return Mutation(
        candidate,
        "domain.schema.deleted",
        {"schema_id": schema.id},
        (schema.id,),
        Operation(
            "domain.schema.put",
            {
                "schema": domain_schema_to_data(schema),
                "index": project.domain_workspace.schemas.index(schema),
            },
        ),
    )


def _edit_schema(project: Project, payload: dict[str, JsonValue], kind: str) -> Mutation:
    schema = _schema(project, payload)
    concept: ConceptDefinition | None
    if kind == "concept.put":
        concept = concept_definition_from_data(payload.get("concept"))
        concepts = tuple(concept if item.id == concept.id else item for item in schema.concepts)
        if schema.concept(concept.id) is None:
            concepts += (concept,)
    elif kind == "concept.delete":
        identity = _text(payload, "concept_id")
        if schema.concept(identity) is None:
            raise CommandError("DOMAIN_CONCEPT_MISSING", "Concept definition does not exist")
        concepts = tuple(item for item in schema.concepts if item.id != identity)
    else:
        concept = schema.concept(_text(payload, "concept_id"))
        if concept is None:
            raise CommandError("DOMAIN_CONCEPT_MISSING", "Concept definition does not exist")
        if kind == "property.put":
            definition = property_definition_from_data(payload.get("definition"))
            properties = tuple(
                definition if item.id == definition.id else item for item in concept.properties
            )
            if concept.property(definition.id) is None:
                properties += (definition,)
            concept = replace(concept, properties=properties)
        else:
            role = role_definition_from_data(payload.get("definition"))
            containment = payload.get("containment", True)
            if not isinstance(containment, bool):
                raise CommandError("DOMAIN_COMMAND_PAYLOAD", "containment must be a boolean")
            previous = concept.containment_roles if containment else concept.reference_roles
            roles = tuple(role if item.id == role.id else item for item in previous)
            if not any(item.id == role.id for item in previous):
                roles += (role,)
            concept = (
                replace(concept, containment_roles=roles)
                if containment
                else replace(concept, reference_roles=roles)
            )
        concepts = tuple(concept if item.id == concept.id else item for item in schema.concepts)
    return _put_schema(
        project, {"schema": domain_schema_to_data(replace(schema, concepts=concepts))}
    )


def _put_model(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    model = domain_model_from_data(payload.get("model"))
    before = project.domain_workspace.model(model.id)
    models = tuple(
        model if item.id == model.id else item for item in project.domain_workspace.models
    )
    if before is None:
        index = _integer(payload.get("index"), len(models))
        if not 0 <= index <= len(models):
            raise CommandError("DOMAIN_MODEL_INDEX", "Model index is outside the workspace")
        models = (*models[:index], model, *models[index:])
    inverse = (
        Operation("domain.model.delete", {"model_id": model.id})
        if before is None
        else Operation("domain.model.put", {"model": domain_model_to_data(before)})
    )
    affected = (
        tuple(
            dict.fromkeys(
                (
                    model.id,
                    *(node.id for node in model.nodes),
                    *(node.id for node in before.nodes if before is not None),
                )
            )
        )
        if before is not None
        else (model.id, *(node.id for node in model.nodes))
    )
    return Mutation(
        replace(project, domain_workspace=replace(project.domain_workspace, models=models)),
        "domain.model.changed",
        {"model_id": model.id},
        affected,
        inverse,
    )


def _delete_model(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    model = _model(project, payload)
    candidate = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            models=tuple(item for item in project.domain_workspace.models if item.id != model.id),
        ),
    )
    return Mutation(
        candidate,
        "domain.model.deleted",
        {"model_id": model.id},
        (model.id, *(item.id for item in model.nodes)),
        Operation(
            "domain.model.put",
            {
                "model": domain_model_to_data(model),
                "index": project.domain_workspace.models.index(model),
            },
        ),
    )


def _patch_operation(before: DomainModel, after: DomainModel) -> Operation:
    previous = {node.id: node for node in before.nodes}
    current = {node.id: node for node in after.nodes}
    return Operation(
        "domain.node.restore_patch",
        {
            "model_id": before.id,
            "nodes": [
                {"index": index, "node": intentional_node_to_data(node)}
                for index, node in enumerate(before.nodes)
                if current.get(node.id) != node
            ],
            "remove_ids": [identity for identity in current if identity not in previous],
            "roots": list(before.roots) if before.roots != after.roots else None,
        },
    )


def _mutation(
    project: Project, before: DomainModel, after: DomainModel, kind: str, affected: tuple[str, ...]
) -> Mutation:
    return Mutation(
        _with_model(project, after),
        kind,
        {"model_id": after.id, "node_ids": list(affected)},
        tuple(dict.fromkeys(affected)),
        _patch_operation(before, after),
    )


def _restore_patch(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    before = _model(project, payload)
    remove_ids = _ids(payload.get("remove_ids", []))
    entries = payload.get("nodes", [])
    if not isinstance(entries, list):
        raise CommandError("DOMAIN_COMMAND_PAYLOAD", "nodes must be an array")
    nodes = [item for item in before.nodes if item.id not in remove_ids]
    affected = list(remove_ids)
    for entry in entries:
        if not isinstance(entry, dict):
            raise CommandError("DOMAIN_COMMAND_PAYLOAD", "Restored node must be an object")
        node = intentional_node_from_data(entry.get("node"))
        index = _integer(entry.get("index"))
        old_index = next((i for i, item in enumerate(nodes) if item.id == node.id), None)
        if old_index is None:
            nodes.insert(min(max(index, 0), len(nodes)), node)
        else:
            nodes[old_index] = node
        affected.append(node.id)
    raw_roots = payload.get("roots")
    roots = before.roots if raw_roots is None else _ids(raw_roots)
    if roots != before.roots:
        affected.append(f"domain.roots:{before.id}")
    return _mutation(
        project,
        before,
        replace(before, nodes=tuple(nodes), roots=roots),
        "domain.nodes.restored",
        tuple(affected),
    )


def _binding(
    bindings: tuple[RoleBinding, ...], role_id: str, ids: tuple[str, ...]
) -> tuple[RoleBinding, ...]:
    values = tuple(
        RoleBinding(role_id, ids) if item.role_id == role_id else item for item in bindings
    )
    if not any(item.role_id == role_id for item in bindings):
        values += (RoleBinding(role_id, ids),)
    return tuple(item for item in values if item.node_ids)


def _detach(model: DomainModel, node_id: str) -> DomainModel:
    return replace(
        model,
        roots=tuple(item for item in model.roots if item != node_id),
        nodes=tuple(
            replace(
                node,
                children=tuple(
                    RoleBinding(
                        binding.role_id, tuple(item for item in binding.node_ids if item != node_id)
                    )
                    for binding in node.children
                    if any(item != node_id for item in binding.node_ids)
                ),
            )
            for node in model.nodes
        ),
    )


def _attach(
    project: Project,
    model: DomainModel,
    node_id: str,
    parent_id: str | None,
    role_id: str | None,
    index: int | None,
) -> DomainModel:
    if (parent_id is None) != (role_id is None):
        raise CommandError(
            "DOMAIN_CHILD_LOCATION", "Parent and role must both be supplied or both absent"
        )
    if parent_id is None:
        target = list(model.roots)
    else:
        parent = _node(model, parent_id)
        assert role_id is not None
        schema = project.domain_workspace.schema(model.schema_id)
        concept = schema.concept(parent.concept_id) if schema is not None else None
        if concept is None or not any(item.id == role_id for item in concept.containment_roles):
            raise CommandError("DOMAIN_ROLE_UNRESOLVED", "Target is not a containment role")
        target = list(parent.child_ids(role_id))
    position = len(target) if index is None else index
    if not 0 <= position <= len(target):
        raise CommandError("DOMAIN_CHILD_INDEX", "Insertion index is outside the target role")
    target.insert(position, node_id)
    if parent_id is None:
        return replace(model, roots=tuple(target))
    assert role_id is not None
    parent = _node(model, parent_id)
    updated = replace(parent, children=_binding(parent.children, role_id, tuple(target)))
    return replace(
        model, nodes=tuple(updated if node.id == parent_id else node for node in model.nodes)
    )


def _changed_ids(
    before: DomainModel, after: DomainModel, *, topology: bool = False
) -> tuple[str, ...]:
    previous = {node.id: node for node in before.nodes}
    current = {node.id: node for node in after.nodes}
    ids = tuple(
        identity
        for identity in dict.fromkeys((*previous, *current))
        if previous.get(identity) != current.get(identity)
    )
    return (
        *ids,
        *((before.id,) if topology else ()),
        *((f"domain.roots:{before.id}",) if before.roots != after.roots else ()),
    )


def _create_node(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    before = _model(project, payload)
    node = intentional_node_from_data(payload.get("node"))
    if project.domain_workspace.node(node.id) is not None:
        raise CommandError("DOMAIN_NODE_EXISTS", "A node with this identity already exists")
    schema = project.domain_workspace.schema(before.schema_id)
    concept = schema.concept(node.concept_id) if schema is not None else None
    if concept is None:
        raise CommandError("DOMAIN_CONCEPT_UNRESOLVED", "Node concept is absent from its schema")
    supplied = {item.property_id for item in node.properties}
    defaults = tuple(
        PropertyValue(item.id, item.default)
        for item in concept.properties
        if item.id not in supplied and item.default is not None
    )
    node = replace(node, properties=(*node.properties, *defaults))
    after = replace(before, nodes=(*before.nodes, node))
    raw_index = payload.get("index")
    after = _attach(
        project,
        after,
        node.id,
        _optional_text(payload, "parent_id"),
        _optional_text(payload, "role_id"),
        None if raw_index is None else _integer(raw_index),
    )
    return _mutation(
        project, before, after, "domain.node.created", _changed_ids(before, after, topology=True)
    )


def _delete_node(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    before = _model(project, payload)
    node_id = _text(payload, "node_id")
    _node(before, node_id)
    deleted: set[str] = set()
    pending = [node_id]
    while pending:
        current = pending.pop()
        if current in deleted:
            continue
        deleted.add(current)
        pending.extend(
            child for binding in _node(before, current).children for child in binding.node_ids
        )
    for model in project.domain_workspace.models:
        for node in model.nodes:
            if node.id not in deleted and any(
                target in deleted for binding in node.references for target in binding.node_ids
            ):
                raise CommandError(
                    "DOMAIN_NODE_REFERENCED", "Remove incoming references before deleting this node"
                )
    after = _detach(before, node_id)
    after = replace(after, nodes=tuple(node for node in after.nodes if node.id not in deleted))
    return _mutation(
        project, before, after, "domain.node.deleted", _changed_ids(before, after, topology=True)
    )


def _set_property(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    if "value" not in payload:
        raise CommandError("DOMAIN_COMMAND_PAYLOAD", "Property edit requires an explicit value")
    before = _model(project, payload)
    node = _node(before, _text(payload, "node_id"))
    property_id = _text(payload, "property_id")
    schema = project.domain_workspace.schema(before.schema_id)
    concept = schema.concept(node.concept_id) if schema is not None else None
    if concept is None or concept.property(property_id) is None:
        raise CommandError("DOMAIN_PROPERTY_UNRESOLVED", "Property is absent from this concept")
    raw_value = payload.get("value")
    properties = tuple(item for item in node.properties if item.property_id != property_id)
    if raw_value is not None:
        value = PropertyValue(property_id, domain_value_from_data(raw_value))
        properties = tuple(
            value if item.property_id == property_id else item for item in node.properties
        )
        if node.property(property_id) is None:
            properties += (value,)
    updated = replace(node, properties=properties)
    after = replace(
        before, nodes=tuple(updated if item.id == node.id else item for item in before.nodes)
    )
    return _mutation(project, before, after, "domain.node.property_changed", (node.id,))


def _promote_evidence(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    evidence = evidence_from_data(payload.get("evidence"))
    if evidence.id != "evidence:" + evidence_content_hash(evidence):
        raise CommandError("EVIDENCE_CONTENT_HASH", "Evidence content does not match its identity")
    if (
        evidence.provenance.project_id != project.id
        or evidence.provenance.revision > project.revision
    ):
        raise CommandError(
            "EVIDENCE_REVISION",
            "Promotion requires evidence from this project at an existing revision",
        )
    if evidence.outcome is not ComputationOutcome.SUCCEEDED:
        raise CommandError("EVIDENCE_OUTCOME", "Only successful observations can be promoted")
    observation_id = _text(payload, "observation_id")
    observation = next((item for item in evidence.observations if item.id == observation_id), None)
    if observation is None:
        raise CommandError("EVIDENCE_OBSERVATION", "The selected observation does not exist")
    mutation = _set_property(
        project, {**payload, "value": canonical_value_to_data(observation.value)}
    )
    return replace(
        mutation,
        event_type="domain.node.evidence_promoted",
        event_payload={
            **mutation.event_payload,
            "evidence_id": evidence.id,
            "observation_id": observation_id,
        },
    )


def _promote_artifact(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    evidence = evidence_from_data(payload.get("evidence"))
    if evidence.id != "evidence:" + evidence_content_hash(evidence):
        raise CommandError("EVIDENCE_CONTENT_HASH", "Evidence content does not match its identity")
    if (
        evidence.provenance.project_id != project.id
        or evidence.provenance.revision > project.revision
    ):
        raise CommandError("EVIDENCE_REVISION", "Promotion requires an existing project revision")
    if evidence.outcome is not ComputationOutcome.SUCCEEDED:
        raise CommandError("EVIDENCE_OUTCOME", "Select an artifact of a successful computation")
    artifact_id = _text(payload, "artifact_id")
    artifact = next((a for a in evidence.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise CommandError("EVIDENCE_ARTIFACT", "Selected artifact does not exist")
    model = domain_model_from_data(payload.get("model"))
    if project.domain_workspace.model(model.id) is not None:
        raise CommandError("EVIDENCE_OWNERSHIP", "Promotion must create a new authored identity")
    node = model.node(_text(payload, "node_id"))
    if node is None or node.property(_text(payload, "property_id")) != artifact.resource:
        raise CommandError("EVIDENCE_BINDING", "Authored input must bind the selected resource")
    mutation = _put_model(project, payload)
    return replace(
        mutation,
        event_type="domain.model.artifact_promoted",
        event_payload={
            "model_id": model.id,
            "evidence_id": evidence.id,
            "artifact_id": artifact.id,
            "resource_id": artifact.resource.id,
        },
    )


def _move_child(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    before = _model(project, payload)
    node_id = _text(payload, "node_id")
    _node(before, node_id)
    after = _attach(
        project,
        _detach(before, node_id),
        node_id,
        _optional_text(payload, "parent_id"),
        _optional_text(payload, "role_id"),
        _integer(payload.get("index")),
    )
    return _mutation(
        project,
        before,
        after,
        "domain.node.moved",
        (*_changed_ids(before, after, topology=True), node_id),
    )


def _insert_child(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    before = _model(project, payload)
    if _text(payload, "node_id") not in before.roots:
        raise CommandError(
            "DOMAIN_CHILD_ALREADY_OWNED", "Insert requires a root node; use move for an owned child"
        )
    return _move_child(project, payload)


def _remove_child(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    model = _model(project, payload)
    node_id = _text(payload, "node_id")
    if node_id in model.roots:
        raise CommandError("DOMAIN_CHILD_NOT_OWNED", "Node is already a root")
    return _move_child(
        project,
        {
            "model_id": model.id,
            "node_id": node_id,
            "parent_id": None,
            "role_id": None,
            "index": len(model.roots),
        },
    )


def _set_reference(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    before = _model(project, payload)
    node = _node(before, _text(payload, "node_id"))
    role_id = _text(payload, "role_id")
    schema = project.domain_workspace.schema(before.schema_id)
    concept = schema.concept(node.concept_id) if schema is not None else None
    if concept is None or not any(role.id == role_id for role in concept.reference_roles):
        raise CommandError("DOMAIN_ROLE_UNRESOLVED", "Reference role is absent from this concept")
    targets = _ids(payload.get("target_ids", []))
    updated = replace(node, references=_binding(node.references, role_id, targets))
    after = replace(
        before, nodes=tuple(updated if item.id == node.id else item for item in before.nodes)
    )
    return _mutation(project, before, after, "domain.node.reference_changed", (node.id,))


def _remove_reference(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    model = _model(project, payload)
    node = _node(model, _text(payload, "node_id"))
    role_id = _text(payload, "role_id")
    target = _optional_text(payload, "target_id")
    ids = (
        tuple(item for item in node.reference_ids(role_id) if item != target)
        if target is not None
        else ()
    )
    return _set_reference(
        project,
        {"model_id": model.id, "node_id": node.id, "role_id": role_id, "target_ids": list(ids)},
    )


def _put_bundle(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    reference = bundle_from_data(payload.get("reference"))
    if reference in project.domain_workspace.bundle_references:
        raise CommandError("DOMAIN_BUNDLE_EXISTS", "Bundle requirement already exists")
    references = project.domain_workspace.bundle_references
    index = _integer(payload.get("index"), len(references))
    if not 0 <= index <= len(references):
        raise CommandError("DOMAIN_BUNDLE_INDEX", "Bundle index is outside the workspace")
    candidate = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            bundle_references=(*references[:index], reference, *references[index:]),
        ),
    )
    return Mutation(
        candidate,
        "domain.bundle.added",
        {"bundle_id": reference.id},
        (f"domain.bundle:{reference.id}:{reference.version}",),
        Operation(
            "domain.bundle.delete", {"bundle_id": reference.id, "version": reference.version}
        ),
    )


def _delete_bundle(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    identity, version = _text(payload, "bundle_id"), _text(payload, "version")
    reference = next(
        (
            item
            for item in project.domain_workspace.bundle_references
            if item.id == identity and item.version == version
        ),
        None,
    )
    if reference is None:
        raise CommandError("DOMAIN_BUNDLE_MISSING", "Bundle requirement does not exist")
    candidate = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            bundle_references=tuple(
                item for item in project.domain_workspace.bundle_references if item != reference
            ),
        ),
    )
    return Mutation(
        candidate,
        "domain.bundle.deleted",
        {"bundle_id": identity},
        (f"domain.bundle:{identity}:{version}",),
        Operation(
            "domain.bundle.put",
            {
                "reference": bundle_to_data(reference),
                "index": project.domain_workspace.bundle_references.index(reference),
            },
        ),
    )


def _guard(handler: Handler) -> Handler:
    def apply(project: Project, payload: dict[str, JsonValue]) -> Mutation:
        try:
            return handler(project, payload)
        except ValueError as exc:
            if isinstance(exc, CommandError):
                raise
            raise CommandError("DOMAIN_COMMAND_PAYLOAD", str(exc)) from exc

    return apply


def domain_handlers() -> tuple[tuple[str, Handler], ...]:
    handlers: list[tuple[str, Handler]] = [
        ("domain.schema.put", _put_schema),
        ("domain.schema.delete", _delete_schema),
        ("domain.model.put", _put_model),
        ("domain.model.promote_artifact", _promote_artifact),
        ("domain.model.delete", _delete_model),
        ("domain.node.create", _create_node),
        ("domain.node.delete", _delete_node),
        ("domain.node.set_property", _set_property),
        ("domain.node.promote_evidence", _promote_evidence),
        ("domain.node.restore_patch", _restore_patch),
        ("domain.node.move_child", _move_child),
        ("domain.node.insert_child", _insert_child),
        ("domain.node.remove_child", _remove_child),
        ("domain.node.set_reference", _set_reference),
        ("domain.node.remove_reference", _remove_reference),
        ("domain.bundle.put", _put_bundle),
        ("domain.bundle.delete", _delete_bundle),
    ]
    for kind in ("concept.put", "concept.delete", "property.put", "role.put"):

        def handler(project: Project, payload: dict[str, JsonValue], edit: str = kind) -> Mutation:
            return _edit_schema(project, payload, edit)

        handlers.append((f"domain.schema.{kind}", handler))
    return tuple((name, _guard(handler)) for name, handler in handlers)
