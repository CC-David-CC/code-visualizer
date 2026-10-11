"""Stable origin mappings shared by computation plans and returned evidence."""

from code_visualizer.domain.identifiers import (
    BundlePublication,
    ContractDefinition,
    ContractKind,
    PublicationManifest,
)
from code_visualizer.domain.transformation import OriginLink, OriginMap
from code_visualizer.protocol.v1 import identity_pb2 as wire
from code_visualizer.protocol.validation import check_message, require_field


def origins_to_proto(value: OriginMap) -> wire.OriginMap:
    return wire.OriginMap(
        project_id=value.project_id,
        revision=value.revision,
        links=[
            wire.OriginLink(generated_id=o.generated_id, source_ids=o.source_ids)
            for o in value.links
        ],
    )


def origins_from_proto(value: wire.OriginMap) -> OriginMap:
    check_message(value)
    return OriginMap(
        value.project_id,
        value.revision,
        tuple(OriginLink(o.generated_id, tuple(o.source_ids)) for o in value.links),
    )


def contract_to_proto(value: ContractDefinition) -> wire.ContractDefinition:
    return wire.ContractDefinition(kind=value.kind.value, id=value.id, version=value.version)


def contract_from_proto(value: wire.ContractDefinition) -> ContractDefinition:
    check_message(value)
    return ContractDefinition(ContractKind(value.kind), value.id, value.version)


def publication_to_proto(value: PublicationManifest) -> wire.PublicationManifest:
    result = wire.PublicationManifest(
        naming_version=value.publication.naming_version,
        owner_id=value.publication.owner_id,
        bundle=contract_to_proto(value.bundle),
        contracts=[contract_to_proto(item) for item in value.contracts],
        dependencies=[contract_to_proto(item) for item in value.dependencies],
        references=[contract_to_proto(item) for item in value.references],
    )
    check_message(result)
    return result


def publication_from_proto(value: wire.PublicationManifest) -> PublicationManifest:
    check_message(value)
    require_field(value, "bundle")
    return PublicationManifest(
        contract_from_proto(value.bundle),
        BundlePublication(value.owner_id, value.naming_version),
        tuple(contract_from_proto(item) for item in value.contracts),
        tuple(contract_from_proto(item) for item in value.dependencies),
        tuple(contract_from_proto(item) for item in value.references),
    )
