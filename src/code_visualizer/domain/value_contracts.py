"""Public references carried by inert values, independently of interpretation code."""

from dataclasses import fields, is_dataclass

from code_visualizer.domain.identifiers import ContractKind, ContractReference
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import DimensionPower, UnitReference


def value_contract_reference(value: object) -> ContractReference | None:
    """Classify one typed reference; object names and arbitrary strings remain opaque."""
    if isinstance(value, UnitReference):
        return ContractReference(ContractKind.UNIT, value.id, value.version)
    if isinstance(value, DimensionPower):
        return ContractReference(ContractKind.DIMENSION_BASIS, value.basis_id, None)
    if isinstance(value, ResourceLogicalTypeReference):
        return ContractReference(ContractKind.RESOURCE_LOGICAL_TYPE, value.id, value.version)
    return None


def value_contract_references(value: object) -> tuple[ContractReference, ...]:
    """Visit immutable typed records without calling registered implementation code."""
    references: set[ContractReference] = set()
    active: set[int] = set()

    def visit(item: object) -> None:
        if callable(item):
            return
        reference = value_contract_reference(item)
        if reference is not None:
            references.add(reference)
        if isinstance(item, tuple):
            for child in item:
                visit(child)
        elif is_dataclass(item) and not isinstance(item, type):
            if id(item) in active:
                raise ValueError("Contract reference data must be acyclic")
            active.add(id(item))
            for member in fields(item):
                visit(getattr(item, member.name))
            active.remove(id(item))

    visit(value)
    return tuple(sorted(references, key=lambda item: item.sort_key))
