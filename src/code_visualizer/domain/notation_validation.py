"""Structural checks for composed notations without executing queries or rendering."""

from __future__ import annotations

import math
from dataclasses import fields, is_dataclass

from code_visualizer.domain import notation_syntax as v
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainIssue,
    DomainSchema,
    DomainWorkspace,
    PropertyDefinition,
    ValueKind,
)

type _Candidates = tuple[tuple[DomainSchema, ConceptDefinition], ...]
type _Bindings = dict[str, _Candidates]


def validate_composed_notation(
    body: v.Visual,
    schema: DomainSchema,
    workspace: DomainWorkspace | None = None,
    *,
    schemas: tuple[DomainSchema, ...] = (),
) -> tuple[DomainIssue, ...]:
    issues: list[DomainIssue] = []
    identities: set[str] = set()
    count = 0
    # A schema-only compiler cannot claim that an instance selector is dangling.
    # Editors with a full workspace also validate the selected model's existence.
    schemas = workspace.schemas if workspace is not None else schemas or (schema,)
    all_concepts = tuple((item, concept) for item in schemas for concept in item.concepts)

    def concepts(selected: tuple[DomainSchema, ...]) -> _Candidates:
        return tuple((item, concept) for item in selected for concept in item.concepts)

    def issue(code: str, message: str, identity: str, *, incomplete: bool = False) -> None:
        issues.append(DomainIssue(code, message, identity, incomplete=incomplete))

    def related(
        candidates: _Candidates, role_id: str, identity: str, *, references: bool = False
    ) -> _Candidates:
        targets: dict[tuple[str, str], tuple[DomainSchema, ConceptDefinition]] = {}
        found = False
        for owner, concept in candidates:
            roles = (
                concept.reference_roles
                if references
                else (*concept.containment_roles, *concept.reference_roles)
            )
            for role in roles:
                if role.id != role_id:
                    continue
                found = True
                for concept_id in role.allowed_concept_ids:
                    target = owner.concept(concept_id)
                    if target is not None:
                        targets[(owner.id, target.id)] = (owner, target)
        if candidates and not found:
            issue(
                "NOTATION_ROLE",
                f"{'Reference' if references else 'Domain'} role {role_id!r} "
                "is not available on the bound objects",
                identity,
            )
        return tuple(targets.values())

    def query_candidates(query: v.NotationQuery, bindings: _Bindings) -> _Candidates:
        if isinstance(query, v.NotationObjects):
            selected = schemas if query.workspace else (schema,)
            if query.schema_id is not None:
                selected = tuple(
                    item
                    for item in selected
                    if item.id == query.schema_id and item.version == query.schema_version
                )
                if not selected:
                    issue(
                        "NOTATION_SCHEMA",
                        "Selected schema version is unavailable in this query scope",
                        query.id,
                        incomplete=True,
                    )
            if query.model_id is not None and workspace is not None:
                model = workspace.model(query.model_id)
                if model is None:
                    issue(
                        "NOTATION_MODEL",
                        "Selected domain model is unavailable",
                        query.id,
                        incomplete=True,
                    )
                    return ()
                selected = tuple(
                    item
                    for item in selected
                    if item.id == model.schema_id and item.version == model.schema_version
                )
                if not selected:
                    issue(
                        "NOTATION_MODEL",
                        "Selected model does not belong to the query's schema scope",
                        query.id,
                    )
            candidates = concepts(selected)
            if query.concept_id:
                narrowed = tuple(item for item in candidates if item[1].id == query.concept_id)
                if candidates and not narrowed:
                    issue(
                        "NOTATION_CONCEPT",
                        "Selected concept is not defined in the query's schema scope",
                        query.id,
                    )
                return narrowed
            return candidates
        if isinstance(query, v.NotationRelated):
            source = bindings.get(query.source_binding_id, ())
            if query.role_id:
                if not query.incoming:
                    return related(source, query.role_id, query.id)
                allowed = {(owner.id, concept.id) for owner, concept in source}
                result = tuple(
                    (owner, concept)
                    for owner, concept in all_concepts
                    if any(
                        role.id == query.role_id
                        and any(
                            (owner.id, target) in allowed for target in role.allowed_concept_ids
                        )
                        for role in (*concept.containment_roles, *concept.reference_roles)
                    )
                )
                if source and not result:
                    issue(
                        "NOTATION_ROLE",
                        "No declared incoming role accepts the bound objects",
                        query.id,
                    )
                return result
            # Authored semantic relations can connect any canonical workspace objects.
            # Their runtime result is a union, not a copy of the current schema.
            return all_concepts
        return ()

    def properties(
        candidates: _Candidates, property_id: str | None, identity: str
    ) -> tuple[PropertyDefinition, ...]:
        result: list[PropertyDefinition] = []
        for _owner, concept in candidates:
            selected_id = property_id or concept.display_property_id
            selected = concept.property(selected_id) if selected_id else None
            if selected:
                result.append(selected)
        if candidates and property_id and not result:
            issue(
                "NOTATION_PROPERTY",
                f"Property {property_id!r} is not available on the bound objects",
                identity,
            )
        return tuple(result)

    def visit(value: object, bindings: _Bindings, depth: int) -> None:
        nonlocal count
        if count > 20_000:
            return
        if isinstance(value, tuple):
            for item in value:
                visit(item, bindings, depth + 1)
            return
        if not is_dataclass(value) or isinstance(value, type):
            return
        count += 1
        identity = str(getattr(value, "id", ""))
        if depth > 64 or count > 20_000:
            issue("NOTATION_LIMIT", "Notation syntax exceeds its structural limits", identity)
            return
        if not identity or identity in identities:
            issue(
                "NOTATION_ID", "Notation element identities must be unique and nonempty", identity
            )
        identities.add(identity)
        if isinstance(value, (v.VisualHole, v.NotationQueryHole)):
            issue("NOTATION_HOLE", value.label, identity, incomplete=True)
        if isinstance(value, v.VisualRepeat):
            visit(value.query, bindings, depth + 1)
            if not value.binding_id or value.binding_id in bindings:
                issue(
                    "NOTATION_BINDING",
                    "Repeat binding identity is missing or shadows another binding",
                    identity,
                )
            candidates = query_candidates(value.query, bindings)
            visit(
                value.body,
                {**bindings, value.binding_id: candidates, "self": candidates},
                depth + 1,
            )
            return
        if isinstance(value, v.NotationObjects) and (
            (value.schema_id is None) != (value.schema_version is None)
        ):
            issue(
                "NOTATION_SCHEMA",
                "Workspace schema selection must pin identity and version together",
                identity,
            )
        binding_fields = (
            ("source_binding_id", "target_binding_id")
            if isinstance(value, v.VisualConnector)
            else ("source_binding_id",)
            if isinstance(value, v.NotationRelated)
            else ("binding_id",)
            if isinstance(value, (v.VisualField, v.VisualPredicate))
            or (isinstance(value, v.VisualNumber) and value.property_id is not None)
            else ()
        )
        for name in binding_fields:
            if getattr(value, name) not in bindings:
                issue("NOTATION_BINDING", "Visual element refers to an unbound object", identity)
        if isinstance(value, v.VisualField):
            candidates = bindings.get(value.binding_id, ())
            for role_id in value.reference_role_ids:
                candidates = related(candidates, role_id, identity, references=True)
            properties(candidates, value.property_id, identity)
        if isinstance(value, (v.VisualNumber, v.VisualPredicate)) and value.property_id is not None:
            definitions = properties(
                bindings.get(value.binding_id, ()), value.property_id, identity
            )
            numeric = isinstance(value, v.VisualNumber) or value.operator in {
                v.VisualComparison.LESS,
                v.VisualComparison.GREATER,
            }
            if (
                numeric
                and definitions
                and not any(
                    item.value_kind in {ValueKind.INTEGER, ValueKind.NUMBER} for item in definitions
                )
            ):
                issue(
                    "NOTATION_PROPERTY_TYPE",
                    "Numeric notation requires a numeric property",
                    identity,
                )
            if (
                isinstance(value, v.VisualPredicate)
                and numeric
                and type(value.expected) not in {int, float}
            ):
                issue(
                    "NOTATION_PROPERTY_TYPE",
                    "Ordered comparison requires a numeric comparison value",
                    identity,
                )
        if (
            isinstance(value, v.NotationRelated)
            and value.role_id
            and (value.relation_kind or value.relation_label)
        ):
            issue(
                "NOTATION_QUERY", "Choose a domain role or a semantic relation selector", identity
            )
        for field in fields(value):
            item = getattr(value, field.name)
            if type(item) in {int, float} and (not math.isfinite(item) or abs(item) > 1_000_000):
                issue("NOTATION_NUMBER", "Visual numbers must be finite and bounded", identity)
            if (
                field.name in {"gap", "padding", "font_size", "wrap_width"}
                and isinstance(item, (int, float))
                and item < 0
            ):
                issue("NOTATION_NUMBER", "Visual sizes and gaps cannot be negative", identity)
            visit(item, bindings, depth + 1)

    visit(body, {"self": concepts((schema,))}, 0)
    return tuple(issues)
