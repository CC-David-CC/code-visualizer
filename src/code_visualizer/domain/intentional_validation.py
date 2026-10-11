"""Pure schema and containment validation; no extension implementations are loaded."""

from __future__ import annotations

import math

from code_visualizer.domain.intentional import (
    ConceptDefinition,
    ConstraintKind,
    DomainIssue,
    DomainSchema,
    DomainValue,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.language_structure import language_owned_ids, validate_language_slots
from code_visualizer.domain.values import (
    ComplexValue,
    QuantityValue,
    ResourceReference,
    TensorValue,
    validate_canonical_value,
    value_satisfies,
)


def value_matches(definition: PropertyDefinition, value: DomainValue) -> bool:
    try:
        validate_canonical_value(value)
    except ValueError:
        return False
    if not value_satisfies(value, definition.value_constraints):
        return False
    match definition.value_kind:
        case ValueKind.STRING:
            return isinstance(value, str)
        case ValueKind.INTEGER:
            return type(value) is int
        case ValueKind.NUMBER:
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and (type(value) is int or math.isfinite(value))
            )
        case ValueKind.BOOLEAN:
            return type(value) is bool
        case ValueKind.COMPLEX:
            return isinstance(value, ComplexValue)
        case ValueKind.QUANTITY:
            return isinstance(value, QuantityValue)
        case ValueKind.TENSOR:
            return isinstance(value, TensorValue)
        case ValueKind.RESOURCE:
            return isinstance(value, ResourceReference)


def validate_domain_workspace(workspace: DomainWorkspace) -> tuple[DomainIssue, ...]:
    """Unsafe structures are errors; unfinished required values remain editable.

    All role ownership lives in one flat node table. No recursive Python object graph
    is trusted, and traversal terminates even for malicious persisted containment.
    """

    issues: list[DomainIssue] = []
    schema: DomainSchema | None
    concept: ConceptDefinition | None
    definition: PropertyDefinition | None
    role: RoleDefinition | None

    def issue(
        code: str, message: str, identity: str, field: str = "", *, incomplete: bool = False
    ) -> None:
        issues.append(DomainIssue(code, message, identity, field, incomplete))

    identities: set[str] = set()

    def identity(value: str, label: str) -> None:
        if not value.strip():
            issue("DOMAIN_EMPTY_ID", f"A {label} requires a stable identity", value)
        if value in identities:
            issue("DOMAIN_DUPLICATE_ID", f"Domain identity {value!r} is used more than once", value)
        identities.add(value)

    concepts = {concept.id: concept for schema in workspace.schemas for concept in schema.concepts}
    nodes = {node.id: node for model in workspace.models for node in model.nodes}
    bundles: set[tuple[str, str]] = set()
    for bundle in workspace.bundle_references:
        if not bundle.id.strip() or not bundle.version.strip():
            issue(
                "DOMAIN_BUNDLE_REFERENCE", "Bundle identity and version must be nonempty", bundle.id
            )
        key = (bundle.id, bundle.version)
        if key in bundles:
            issue(
                "DOMAIN_BUNDLE_DUPLICATE",
                "A bundle reference is declared more than once",
                bundle.id,
            )
        bundles.add(key)
    for schema in workspace.schemas:
        identity(schema.id, "schema")
        if not schema.namespace.strip() or not schema.version.strip():
            issue(
                "DOMAIN_SCHEMA_IDENTITY", "Schema namespace and version must be nonempty", schema.id
            )
        if schema.bundle is not None and (
            not schema.bundle.id.strip() or not schema.bundle.version.strip()
        ):
            issue(
                "DOMAIN_BUNDLE_REFERENCE", "Bundle identity and version must be nonempty", schema.id
            )
        local_concepts = {item.id for item in schema.concepts}
        for concept in schema.concepts:
            identity(concept.id, "concept definition")
            if not concept.name.strip():
                issue("DOMAIN_CONCEPT_NAME", "A concept definition requires a name", concept.id)
            property_ids = {item.id for item in concept.properties}
            role_ids = {item.id for item in concept.containment_roles}
            if (
                concept.display_property_id is not None
                and concept.display_property_id not in property_ids
            ):
                issue(
                    "DOMAIN_DISPLAY_PROPERTY",
                    "Display property does not belong to this concept",
                    concept.id,
                )
            for definition in concept.properties:
                identity(definition.id, "property definition")
                contract = definition.value_constraints
                if (
                    contract.dimension is not None
                    and definition.value_kind is not ValueKind.QUANTITY
                ) or (
                    (contract.tensor_dtype is not None or contract.tensor_shape is not None)
                    and definition.value_kind is not ValueKind.TENSOR
                ):
                    issue(
                        "DOMAIN_PROPERTY_CONTRACT",
                        "Value constraints require the corresponding quantity or tensor kind",
                        definition.id,
                    )
                if not definition.name.strip():
                    issue(
                        "DOMAIN_PROPERTY_NAME",
                        "A property definition requires a name",
                        definition.id,
                    )
                values = (
                    *definition.choices,
                    *((definition.default,) if definition.default is not None else ()),
                )
                if any(not value_matches(definition, value) for value in values):
                    issue(
                        "DOMAIN_PROPERTY_RULE_TYPE",
                        "Default and choices must match the declared value type",
                        definition.id,
                    )
                if definition.minimum is not None or definition.maximum is not None:
                    if definition.value_kind not in (ValueKind.INTEGER, ValueKind.NUMBER):
                        issue(
                            "DOMAIN_PROPERTY_RANGE_TYPE",
                            "Numeric bounds require a numeric property",
                            definition.id,
                        )
                    if any(
                        value is not None and not math.isfinite(value)
                        for value in (definition.minimum, definition.maximum)
                    ):
                        issue(
                            "DOMAIN_PROPERTY_RANGE", "Numeric bounds must be finite", definition.id
                        )
                    if (
                        definition.minimum is not None
                        and definition.maximum is not None
                        and definition.minimum > definition.maximum
                    ):
                        issue(
                            "DOMAIN_PROPERTY_RANGE",
                            "Property minimum must not exceed maximum",
                            definition.id,
                        )
            for containment, definitions in (
                (True, concept.containment_roles),
                (False, concept.reference_roles),
            ):
                for role in definitions:
                    identity(role.id, "role definition")
                    if not role.name.strip():
                        issue("DOMAIN_ROLE_NAME", "A role definition requires a name", role.id)
                    if role.min_count < 0 or (
                        role.max_count is not None and role.max_count < role.min_count
                    ):
                        issue(
                            "DOMAIN_ROLE_CARDINALITY",
                            "Role cardinality bounds are invalid",
                            role.id,
                        )
                    allowed = local_concepts if containment else concepts.keys()
                    if not role.allowed_concept_ids or any(
                        item not in allowed for item in role.allowed_concept_ids
                    ):
                        issue(
                            "DOMAIN_ROLE_CONCEPT",
                            "Role allows a missing or foreign contained concept",
                            role.id,
                        )
                    if len(role.allowed_concept_ids) != len(set(role.allowed_concept_ids)):
                        issue(
                            "DOMAIN_ROLE_CONCEPT_DUPLICATE",
                            "Allowed concepts must be unique",
                            role.id,
                        )
            for constraint in concept.constraints:
                identity(constraint.id, "constraint")
                if constraint.kind is ConstraintKind.NONEMPTY:
                    definition = concept.property(constraint.property_id)
                    if (
                        definition is None
                        or definition.value_kind is not ValueKind.STRING
                        or constraint.role_id is not None
                    ):
                        issue(
                            "DOMAIN_CONSTRAINT_PROPERTY",
                            "Nonempty requires a local text property",
                            constraint.id,
                        )
                elif constraint.kind is ConstraintKind.UNIQUE_PROPERTY:
                    if constraint.role_id not in role_ids:
                        issue(
                            "DOMAIN_CONSTRAINT_ROLE",
                            "Uniqueness requires a containment role",
                            constraint.id,
                        )
                    else:
                        role = concept.role(constraint.role_id)
                        assert role is not None
                        if not any(
                            concepts[item].property(constraint.property_id) is not None
                            for item in role.allowed_concept_ids
                            if item in concepts
                        ):
                            issue(
                                "DOMAIN_CONSTRAINT_PROPERTY",
                                "Unique property must belong to a permitted child concept",
                                constraint.id,
                            )
    for model in workspace.models:
        identity(model.id, "model")
        schema = workspace.schema(model.schema_id)
        if schema is None or schema.version != model.schema_version:
            issue(
                "DOMAIN_SCHEMA_UNRESOLVED", "Model schema identity/version is unavailable", model.id
            )
        local_nodes = {node.id: node for node in model.nodes}
        owners: dict[str, list[str]] = {node.id: [] for node in model.nodes}
        for root in model.roots:
            if root not in local_nodes:
                issue("DOMAIN_ROOT_UNRESOLVED", "Root refers to a missing node", model.id, root)
            else:
                owners[root].append(model.id)
        for node in model.nodes:
            identity(node.id, "node")
            concept = schema.concept(node.concept_id) if schema is not None else None
            if concept is None:
                issue(
                    "DOMAIN_CONCEPT_UNRESOLVED",
                    "Node concept is absent from the model schema",
                    node.id,
                )
            property_ids = set()
            for prop in node.properties:
                if prop.property_id in property_ids:
                    issue(
                        "DOMAIN_PROPERTY_DUPLICATE",
                        "Property is assigned more than once",
                        node.id,
                        prop.property_id,
                    )
                property_ids.add(prop.property_id)
                definition = concept.property(prop.property_id) if concept is not None else None
                if definition is None:
                    issue(
                        "DOMAIN_PROPERTY_UNRESOLVED",
                        "Property is absent from the node concept",
                        node.id,
                        prop.property_id,
                    )
                elif not value_matches(definition, prop.value):
                    issue(
                        "DOMAIN_PROPERTY_TYPE",
                        "Value does not match the declared property type",
                        node.id,
                        prop.property_id,
                    )
                else:
                    if definition.choices and prop.value not in definition.choices:
                        issue(
                            "DOMAIN_PROPERTY_CHOICE",
                            "Value is outside the allowed choices",
                            node.id,
                            prop.property_id,
                            incomplete=True,
                        )
                    if isinstance(prop.value, (int, float)) and not isinstance(prop.value, bool):
                        numeric = prop.value
                        if (definition.minimum is not None and numeric < definition.minimum) or (
                            definition.maximum is not None and numeric > definition.maximum
                        ):
                            issue(
                                "DOMAIN_PROPERTY_RANGE",
                                "Value is outside the declared range",
                                node.id,
                                prop.property_id,
                                incomplete=True,
                            )
            if concept is not None:
                for required_property in concept.properties:
                    if required_property.required and required_property.id not in property_ids:
                        issue(
                            "DOMAIN_PROPERTY_REQUIRED",
                            "Required property has not been supplied",
                            node.id,
                            required_property.id,
                            incomplete=True,
                        )
            for containment, bindings in ((True, node.children), (False, node.references)):
                definitions = (
                    ()
                    if concept is None
                    else concept.containment_roles
                    if containment
                    else concept.reference_roles
                )
                roles = {role.id: role for role in definitions}
                seen_roles: set[str] = set()
                for binding in bindings:
                    if binding.role_id in seen_roles:
                        issue(
                            "DOMAIN_ROLE_DUPLICATE",
                            "Role is bound more than once",
                            node.id,
                            binding.role_id,
                        )
                    seen_roles.add(binding.role_id)
                    role = roles.get(binding.role_id)
                    if role is None:
                        issue(
                            "DOMAIN_ROLE_UNRESOLVED",
                            "Role is absent from this concept or has the wrong ownership kind",
                            node.id,
                            binding.role_id,
                        )
                    if len(binding.node_ids) != len(set(binding.node_ids)):
                        issue(
                            "DOMAIN_ROLE_TARGET_DUPLICATE",
                            "A role may not contain the same target twice",
                            node.id,
                            binding.role_id,
                        )
                    if (
                        role is not None
                        and role.max_count is not None
                        and len(binding.node_ids) > role.max_count
                    ):
                        issue(
                            "DOMAIN_ROLE_MAXIMUM",
                            "Role exceeds its maximum cardinality",
                            node.id,
                            binding.role_id,
                        )
                    for target_id in binding.node_ids:
                        target = (local_nodes if containment else nodes).get(target_id)
                        if target is None:
                            issue(
                                "DOMAIN_CHILD_UNRESOLVED"
                                if containment
                                else "DOMAIN_REFERENCE_UNRESOLVED",
                                "Role target does not exist",
                                node.id,
                                binding.role_id,
                            )
                        else:
                            if (
                                role is not None
                                and target.concept_id not in role.allowed_concept_ids
                            ):
                                issue(
                                    "DOMAIN_ROLE_TARGET_TYPE",
                                    "Target concept is not allowed by this role",
                                    node.id,
                                    binding.role_id,
                                )
                            if containment:
                                owners[target_id].append(node.id)
                for role in definitions:
                    targets = (
                        node.child_ids(role.id) if containment else node.reference_ids(role.id)
                    )
                    if len(targets) < role.min_count:
                        issue(
                            "DOMAIN_ROLE_REQUIRED",
                            "Role has fewer targets than required",
                            node.id,
                            role.id,
                            incomplete=True,
                        )
            if concept is not None:
                _constraints(issues, concept, node, nodes)
        for node_id, owner_ids in owners.items():
            if len(owner_ids) != 1:
                issue(
                    "DOMAIN_CONTAINMENT_OWNER",
                    "Every node must have exactly one containment owner or be one root",
                    node_id,
                )
        # Iterative three-colour DFS finds cycles without recursion or duplicate walks.
        colors: dict[str, int] = {}
        for start in local_nodes:
            if colors.get(start, 0):
                continue
            pending = [(start, False)]
            while pending:
                current, leaving = pending.pop()
                if leaving:
                    colors[current] = 2
                    continue
                if colors.get(current) == 1:
                    issue("DOMAIN_CONTAINMENT_CYCLE", "Containment must be acyclic", current)
                    continue
                if colors.get(current) == 2:
                    continue
                colors[current] = 1
                pending.append((current, True))
                pending.extend(
                    (target, False)
                    for binding in local_nodes[current].children
                    for target in reversed(binding.node_ids)
                    if target in local_nodes
                )
    for language in workspace.language_definitions:
        try:
            validate_language_slots(language)
            for owned_id in language_owned_ids(language):
                identity(owned_id, "authored language object")
        except ValueError as exc:
            issue("DOMAIN_LANGUAGE_STRUCTURE", str(exc), language.id)
            continue
        source_schema = workspace.schema(language.schema_id)
        if source_schema is None or source_schema.version != language.schema_version:
            issue(
                "DOMAIN_LANGUAGE_SCHEMA",
                "Authored language schema identity/version is unavailable",
                language.id,
            )
        if not language.version.strip():
            issue(
                "DOMAIN_LANGUAGE_VERSION", "Authored language version must be nonempty", language.id
            )
    return tuple(issues)


def _constraints(
    issues: list[DomainIssue],
    concept: ConceptDefinition,
    node: IntentionalNode,
    nodes: dict[str, IntentionalNode],
) -> None:
    for constraint in concept.constraints:
        if constraint.kind is ConstraintKind.NONEMPTY:
            value = node.property(constraint.property_id)
            if not isinstance(value, str) or not value.strip():
                issues.append(
                    DomainIssue(
                        "DOMAIN_CONSTRAINT_NONEMPTY",
                        "Text must not be empty",
                        node.id,
                        constraint.property_id,
                        True,
                    )
                )
        elif constraint.kind is ConstraintKind.UNIQUE_PROPERTY and constraint.role_id is not None:
            values: set[DomainValue] = set()
            for child_id in node.child_ids(constraint.role_id):
                child = nodes.get(child_id)
                value = child.property(constraint.property_id) if child is not None else None
                if value is not None:
                    if value in values:
                        issues.append(
                            DomainIssue(
                                "DOMAIN_CONSTRAINT_UNIQUE",
                                "Child property values must be unique within the role",
                                child_id,
                                constraint.property_id,
                                True,
                            )
                        )
                    values.add(value)
