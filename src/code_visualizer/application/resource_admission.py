"""Resolve resource meaning before computation; storage alone grants no interpretation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_visualizer.domain.identifiers import ContractKind, ContractReference
from code_visualizer.domain.resources import (
    DataResource,
    ResourceLogicalTypeReference,
    TensorDescriptor,
)
from code_visualizer.domain.value_contracts import value_contract_references
from code_visualizer.domain.values import CanonicalValue, QuantityValue, validate_canonical_value
from code_visualizer.generation.transformation import TransformationError

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionRegistry


def check_resource_contracts(
    logical_type: ResourceLogicalTypeReference | None,
    tensor: TensorDescriptor | None,
    registry: DomainExtensionRegistry,
) -> None:
    """Resolve inert public identities; never invoke registered validators on the host."""
    if logical_type is not None:
        try:
            registry.resolve_registered_contract_references(
                (
                    ContractReference(
                        ContractKind.RESOURCE_LOGICAL_TYPE, logical_type.id, logical_type.version
                    ),
                )
            )
        except ValueError as exc:
            raise TransformationError("RESOURCE_LOGICAL_TYPE_UNAVAILABLE", str(exc)) from exc
    _check_references(tensor, registry)


def _check_references(value: object, registry: DomainExtensionRegistry) -> None:
    try:
        registry.resolve_registered_contract_references(value_contract_references(value))
    except ValueError as exc:
        raise TransformationError("RESOURCE_VALUE_CONTRACT_UNAVAILABLE", str(exc)) from exc


def check_value_contracts(value: CanonicalValue, registry: DomainExtensionRegistry) -> None:
    validate_canonical_value(value)
    _check_references(value, registry)


def validate_value_contracts(value: CanonicalValue, registry: DomainExtensionRegistry) -> None:
    check_value_contracts(value, registry)
    registry.validate_value(value)


def validate_resource_contracts(
    logical_type: ResourceLogicalTypeReference | None,
    tensor: TensorDescriptor | None,
    registry: DomainExtensionRegistry,
) -> None:
    """Worker admission additionally executes registered interpretation validation."""
    check_resource_contracts(logical_type, tensor, registry)
    if tensor is not None and tensor.unit is not None:
        registry.validate_value(QuantityValue(0, tensor.unit))


def check_resource_descriptor(descriptor: DataResource, registry: DomainExtensionRegistry) -> None:
    check_resource_contracts(descriptor.logical_type, descriptor.tensor, registry)


def validate_resource_descriptor(
    descriptor: DataResource, registry: DomainExtensionRegistry
) -> None:
    validate_resource_contracts(descriptor.logical_type, descriptor.tensor, registry)
