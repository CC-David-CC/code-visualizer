"""Explicit codecs for inert domain schemas and canonical intentional instances."""

from __future__ import annotations

import math
from enum import StrEnum

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    ConstraintDefinition,
    ConstraintKind,
    DomainModel,
    DomainSchema,
    DomainValue,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.persistence.canonical import JsonArray, JsonObject, json_object_data
from code_visualizer.persistence.language import (
    LanguageDecodeError,
    authored_language_from_data,
    authored_language_to_data,
)
from code_visualizer.persistence.values import (
    canonical_value_from_data,
    canonical_value_to_data,
    value_constraints_from_data,
    value_constraints_to_data,
)


class DomainDecodeError(ValueError):
    pass


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DomainDecodeError("Expected an object with text keys")
    return dict(value)


def _array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise DomainDecodeError("Expected an array")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise DomainDecodeError("Expected text")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise DomainDecodeError("Expected an integer")
    return value


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise DomainDecodeError("Expected a boolean")
    return value


def domain_value_from_data(value: object) -> DomainValue:
    try:
        return canonical_value_from_data(value)
    except ValueError as exc:
        raise DomainDecodeError(str(exc)) from exc


def _number(value: object) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise DomainDecodeError("Expected a finite number")
    return float(value)


def _enum[T: StrEnum](kind: type[T], value: object) -> T:
    try:
        return kind(_text(value))
    except ValueError as exc:
        raise DomainDecodeError(f"Unknown {kind.__name__}: {value!r}") from exc


def bundle_to_data(bundle: BundleReference) -> dict[str, JsonValue]:
    return {"id": bundle.id, "version": bundle.version}


def bundle_from_data(value: object) -> BundleReference:
    data = _object(value)
    return BundleReference(_text(data.get("id")), _text(data.get("version")))


def property_definition_to_data(value: PropertyDefinition) -> dict[str, JsonValue]:
    return json_object_data(_property_definition_stream(value))


def _property_definition_stream(value: PropertyDefinition) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "name": value.name,
            "value_kind": value.value_kind.value,
            "required": value.required,
            "default": None if value.default is None else canonical_value_to_data(value.default),
            "choices": JsonArray(canonical_value_to_data(item) for item in value.choices),
            "minimum": None if value.minimum is None else float(value.minimum),
            "maximum": None if value.maximum is None else float(value.maximum),
            "value_constraints": value_constraints_to_data(value.value_constraints),
        }
    )


def property_definition_from_data(value: object) -> PropertyDefinition:
    data = _object(value)
    default = data.get("default")
    return PropertyDefinition(
        _text(data.get("id")),
        _text(data.get("name")),
        _enum(ValueKind, data.get("value_kind", "string")),
        _boolean(data.get("required", False)),
        None if default is None else domain_value_from_data(default),
        tuple(domain_value_from_data(item) for item in _array(data.get("choices", []))),
        _number(data.get("minimum")),
        _number(data.get("maximum")),
        value_constraints_from_data(data.get("value_constraints", {})),
    )


def role_definition_to_data(value: RoleDefinition) -> dict[str, JsonValue]:
    return json_object_data(_role_definition_stream(value))


def _role_definition_stream(value: RoleDefinition) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "name": value.name,
            "allowed_concept_ids": JsonArray(iter(value.allowed_concept_ids)),
            "min_count": value.min_count,
            "max_count": value.max_count,
            "ordered": value.ordered,
        }
    )


def role_definition_from_data(value: object) -> RoleDefinition:
    data = _object(value)
    maximum = data.get("max_count")
    return RoleDefinition(
        _text(data.get("id")),
        _text(data.get("name")),
        tuple(_text(item) for item in _array(data.get("allowed_concept_ids", []))),
        _integer(data.get("min_count", 0)),
        None if maximum is None else _integer(maximum),
        _boolean(data.get("ordered", True)),
    )


def _constraint_to_data(value: ConstraintDefinition) -> dict[str, JsonValue]:
    return {
        "id": value.id,
        "kind": value.kind.value,
        "property_id": value.property_id,
        "role_id": value.role_id,
    }


def _constraint_from_data(value: object) -> ConstraintDefinition:
    data = _object(value)
    return ConstraintDefinition(
        _text(data.get("id")),
        _enum(ConstraintKind, data.get("kind")),
        _text(data.get("property_id")),
        _optional_text(data.get("role_id")),
    )


def concept_definition_to_data(value: ConceptDefinition) -> dict[str, JsonValue]:
    return json_object_data(_concept_definition_stream(value))


def _concept_definition_stream(value: ConceptDefinition) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "name": value.name,
            "properties": JsonArray(_property_definition_stream(item) for item in value.properties),
            "containment_roles": JsonArray(
                _role_definition_stream(item) for item in value.containment_roles
            ),
            "reference_roles": JsonArray(
                _role_definition_stream(item) for item in value.reference_roles
            ),
            "constraints": JsonArray(_constraint_to_data(item) for item in value.constraints),
            "display_property_id": value.display_property_id,
            "description": value.description,
        }
    )


def concept_definition_from_data(value: object) -> ConceptDefinition:
    data = _object(value)
    return ConceptDefinition(
        _text(data.get("id")),
        _text(data.get("name")),
        tuple(property_definition_from_data(item) for item in _array(data.get("properties", []))),
        tuple(
            role_definition_from_data(item) for item in _array(data.get("containment_roles", []))
        ),
        tuple(role_definition_from_data(item) for item in _array(data.get("reference_roles", []))),
        tuple(_constraint_from_data(item) for item in _array(data.get("constraints", []))),
        _optional_text(data.get("display_property_id")),
        _text(data.get("description", "")),
    )


def domain_schema_to_data(value: DomainSchema) -> dict[str, JsonValue]:
    return json_object_data(domain_schema_stream(value))


def domain_schema_stream(value: DomainSchema) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "namespace": value.namespace,
            "version": value.version,
            "concepts": JsonArray(_concept_definition_stream(item) for item in value.concepts),
            "bundle": None if value.bundle is None else bundle_to_data(value.bundle),
            "description": value.description,
        }
    )


def domain_schema_from_data(value: object) -> DomainSchema:
    data = _object(value)
    bundle = data.get("bundle")
    return DomainSchema(
        _text(data.get("id")),
        _text(data.get("namespace")),
        _text(data.get("version")),
        tuple(concept_definition_from_data(item) for item in _array(data.get("concepts", []))),
        None if bundle is None else bundle_from_data(bundle),
        _text(data.get("description", "")),
    )


def _binding_stream(value: RoleBinding) -> JsonObject:
    return JsonObject({"role_id": value.role_id, "node_ids": JsonArray(iter(value.node_ids))})


def _binding_from_data(value: object) -> RoleBinding:
    data = _object(value)
    return RoleBinding(
        _text(data.get("role_id")), tuple(_text(item) for item in _array(data.get("node_ids", [])))
    )


def intentional_node_to_data(value: IntentionalNode) -> dict[str, JsonValue]:
    return json_object_data(intentional_node_stream(value))


def intentional_node_stream(value: IntentionalNode) -> JsonObject:
    """One explicit inventory, including lazily visited large property/role arrays."""
    return JsonObject(
        {
            "id": value.id,
            "concept_id": value.concept_id,
            "properties": JsonArray(
                JsonObject(
                    {"property_id": item.property_id, "value": canonical_value_to_data(item.value)}
                )
                for item in value.properties
            ),
            "children": JsonArray(_binding_stream(item) for item in value.children),
            "references": JsonArray(_binding_stream(item) for item in value.references),
        }
    )


def intentional_node_from_data(value: object) -> IntentionalNode:
    data = _object(value)
    properties = []
    for value in _array(data.get("properties", [])):
        prop = _object(value)
        properties.append(
            PropertyValue(_text(prop.get("property_id")), domain_value_from_data(prop.get("value")))
        )
    return IntentionalNode(
        _text(data.get("id")),
        _text(data.get("concept_id")),
        tuple(properties),
        tuple(_binding_from_data(item) for item in _array(data.get("children", []))),
        tuple(_binding_from_data(item) for item in _array(data.get("references", []))),
    )


def domain_model_to_data(value: DomainModel) -> dict[str, JsonValue]:
    return json_object_data(domain_model_stream(value))


def domain_model_stream(value: DomainModel) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "schema_id": value.schema_id,
            "schema_version": value.schema_version,
            "roots": JsonArray(iter(value.roots)),
            "nodes": JsonArray(intentional_node_stream(item) for item in value.nodes),
            "title": value.title,
        }
    )


def domain_model_from_data(value: object) -> DomainModel:
    data = _object(value)
    return DomainModel(
        _text(data.get("id")),
        _text(data.get("schema_id")),
        _text(data.get("schema_version")),
        tuple(_text(item) for item in _array(data.get("roots", []))),
        tuple(intentional_node_from_data(item) for item in _array(data.get("nodes", []))),
        _text(data.get("title", "")),
    )


def domain_workspace_to_data(value: DomainWorkspace) -> dict[str, JsonValue]:
    return json_object_data(domain_workspace_stream(value))


def domain_workspace_stream(value: DomainWorkspace) -> JsonObject:
    return JsonObject(
        {
            "schemas": JsonArray(domain_schema_stream(item) for item in value.schemas),
            "models": JsonArray(domain_model_stream(item) for item in value.models),
            "bundle_references": JsonArray(
                bundle_to_data(item) for item in value.bundle_references
            ),
            "language_definitions": JsonArray(
                authored_language_to_data(item) for item in value.language_definitions
            ),
        }
    )


def domain_workspace_from_data(value: object) -> DomainWorkspace:
    data = _object(value)
    try:
        languages = tuple(
            authored_language_from_data(item)
            for item in _array(data.get("language_definitions", []))
        )
    except LanguageDecodeError as exc:
        raise DomainDecodeError(str(exc)) from exc
    return DomainWorkspace(
        tuple(domain_schema_from_data(item) for item in _array(data.get("schemas", []))),
        tuple(domain_model_from_data(item) for item in _array(data.get("models", []))),
        tuple(bundle_from_data(item) for item in _array(data.get("bundle_references", []))),
        languages,
    )
