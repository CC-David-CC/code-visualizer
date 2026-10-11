"""Public contract names and host-granted ownership, independent of object IDs.

A namespace grant is a host trust decision, not a claim verified by parsing DNS.
Project object identities deliberately do not implement this naming grammar.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

CONTRACT_NAMING_VERSION = 1
MAX_CONTRACT_ID_BYTES = 255
_SEGMENT = r"[a-z][a-z0-9_-]*"
_NAMESPACE = rf"{_SEGMENT}(?:\.{_SEGMENT})+"
_MEMBER = r"[A-Za-z_][A-Za-z0-9_.-]*"


def validate_global_contract_id(value: str) -> None:
    """Require a qualified, case-stable name; versions are separate fields."""
    if (
        not isinstance(value, str)
        or len(value.encode("utf-8")) > MAX_CONTRACT_ID_BYTES
        or re.fullmatch(rf"{_NAMESPACE}(?::{_MEMBER})?", value, re.ASCII) is None
    ):
        raise ValueError(
            "Global contract IDs require a lowercase qualified namespace, optionally "
            "followed by :member, within 255 ASCII bytes; versions are separate"
        )


def validate_contract_version(value: str) -> None:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) is None
    ):
        raise ValueError("Contract versions require 1-64 ASCII letters, digits, dots, '_' or '-'")


class ContractKind(StrEnum):
    BUNDLE = "bundle"
    SCHEMA_NAMESPACE = "schema_namespace"
    BACKEND = "backend"
    REPRESENTATION = "representation"
    TRANSFORMATION = "transformation"
    UNIT = "unit"
    DIMENSION_BASIS = "dimension_basis"
    RESOURCE_LOGICAL_TYPE = "resource_logical_type"


@dataclass(frozen=True, slots=True, order=True)
class ContractDefinition:
    kind: ContractKind
    id: str
    version: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ContractKind):
            raise ValueError("A published contract requires an explicit kind")
        validate_global_contract_id(self.id)
        validate_contract_version(self.version)


@dataclass(frozen=True, slots=True)
class ContractReference:
    """A public use, distinct from a definition and from an opaque object ID.

    Dimension powers refer to immutable basis identities without a version.
    Publication resolves that use to exactly one versioned basis definition.
    Every other public use must already name an exact version.
    """

    kind: ContractKind
    id: str
    version: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ContractKind):
            raise ValueError("A public reference requires an explicit contract kind")
        validate_global_contract_id(self.id)
        if self.version is None:
            if self.kind is not ContractKind.DIMENSION_BASIS:
                raise ValueError("Only immutable dimension basis references may omit version")
        else:
            validate_contract_version(self.version)

    @property
    def sort_key(self) -> tuple[str, str, str]:
        return self.kind.value, self.id, self.version or ""


def resolve_contract_references(
    references: Iterable[ContractReference], definitions: Iterable[ContractDefinition]
) -> tuple[ContractDefinition, ...]:
    """Resolve only the supplied ownership scope; never choose a latest version."""
    available: dict[tuple[ContractKind, str], list[ContractDefinition]] = {}
    for definition in definitions:
        if not isinstance(definition, ContractDefinition):
            raise ValueError("Public resolution requires typed contract definitions")
        available.setdefault((definition.kind, definition.id), []).append(definition)
    requested = tuple(references)
    if any(not isinstance(reference, ContractReference) for reference in requested):
        raise ValueError("Public resolution requires typed contract references")
    result: set[ContractDefinition] = set()
    for reference in sorted(set(requested), key=lambda item: item.sort_key):
        matches = [
            definition
            for definition in available.get((reference.kind, reference.id), ())
            if reference.version is None or definition.version == reference.version
        ]
        label = f"{reference.kind.value} {reference.id}@{reference.version or '<immutable>'}"
        if not matches:
            raise ValueError(f"Missing public contract reference {label} in the declared scope")
        if len(matches) != 1:
            raise ValueError(f"Ambiguous public contract reference {label} in the declared scope")
        result.add(matches[0])
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class NamespaceGrant:
    namespace: str
    owner_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.namespace, str)
            or re.fullmatch(rf"{_SEGMENT}(?:\.{_SEGMENT})*", self.namespace, re.ASCII) is None
        ):
            raise ValueError("Namespace grants require a lowercase dotted namespace")
        validate_global_contract_id(self.owner_id)

    def contains(self, identity: str) -> bool:
        namespace = identity.split(":", 1)[0]
        return namespace == self.namespace or namespace.startswith(self.namespace + ".")


@dataclass(frozen=True, slots=True)
class BundlePublication:
    owner_id: str
    naming_version: int = CONTRACT_NAMING_VERSION

    def __post_init__(self) -> None:
        validate_global_contract_id(self.owner_id)
        if type(self.naming_version) is not int or self.naming_version != CONTRACT_NAMING_VERSION:
            raise ValueError("Unsupported public contract naming version")


@dataclass(frozen=True, slots=True)
class NamespaceOwnership:
    grants: tuple[NamespaceGrant, ...] = ()

    def __post_init__(self) -> None:
        if type(self.grants) is not tuple or any(
            not isinstance(grant, NamespaceGrant) for grant in self.grants
        ):
            raise ValueError("Namespace ownership requires immutable typed host grants")
        for index, left in enumerate(self.grants):
            for right in self.grants[index + 1 :]:
                if left.namespace == right.namespace or (
                    left.owner_id != right.owner_id
                    and (left.contains(right.namespace) or right.contains(left.namespace))
                ):
                    raise ValueError("Duplicate or overlapping namespace ownership grants")

    def require_owner(self, identity: str, owner_id: str) -> None:
        validate_global_contract_id(identity)
        owners = {grant.owner_id for grant in self.grants if grant.contains(identity)}
        if owners != {owner_id}:
            raise ValueError(f"No host namespace grant allows {owner_id!r} to publish {identity!r}")

    def owner(self, identity: str) -> str | None:
        validate_global_contract_id(identity)
        return next((grant.owner_id for grant in self.grants if grant.contains(identity)), None)


@dataclass(frozen=True, slots=True)
class PublicationManifest:
    bundle: ContractDefinition
    publication: BundlePublication
    contracts: tuple[ContractDefinition, ...]
    dependencies: tuple[ContractDefinition, ...] = ()
    references: tuple[ContractDefinition, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.bundle, ContractDefinition)
            or self.bundle.kind is not ContractKind.BUNDLE
        ):
            raise ValueError("A publication manifest requires a bundle contract")
        if not isinstance(self.publication, BundlePublication):
            raise ValueError("A publication manifest requires its claimed namespace owner")
        for values in (self.contracts, self.dependencies, self.references):
            if (
                type(values) is not tuple
                or len(values) > 10000
                or any(not isinstance(item, ContractDefinition) for item in values)
            ):
                raise ValueError("Manifest contracts require bounded immutable typed tuples")
            if tuple(sorted(set(values))) != values:
                raise ValueError("Manifest contracts must be unique and sorted")
        if self.bundle not in self.contracts:
            raise ValueError("A manifest must include its bundle contract")
        if any(item.kind is not ContractKind.BUNDLE for item in self.dependencies):
            raise ValueError("Manifest dependencies must be exact bundle contracts")
