"""Typed ephemeral resource transfer frames; these are not canonical project state."""

from dataclasses import dataclass

from code_visualizer.domain.boundaries import MAX_RESOURCE_CHUNK_BYTES
from code_visualizer.domain.resources import DataResource


def _transfer_identity(identity: str) -> None:
    if not isinstance(identity, str) or not identity or len(identity.encode("utf-8")) > 256:
        raise ValueError("A resource transfer requires an opaque identity of at most 256 bytes")


@dataclass(frozen=True, slots=True)
class ResourceTransferStart:
    transfer_id: str
    resource: DataResource

    def __post_init__(self) -> None:
        _transfer_identity(self.transfer_id)
        if not isinstance(self.resource, DataResource):
            raise ValueError("A resource transfer requires a typed descriptor")


@dataclass(frozen=True, slots=True)
class ResourceTransferChunk:
    transfer_id: str
    offset: int
    data: bytes

    def __post_init__(self) -> None:
        _transfer_identity(self.transfer_id)
        if type(self.offset) is not int or not 0 <= self.offset < 1 << 63:
            raise ValueError("A resource chunk requires a nonnegative signed 64-bit offset")
        if type(self.data) is not bytes or not 0 < len(self.data) <= MAX_RESOURCE_CHUNK_BYTES:
            raise ValueError("A resource chunk must contain between 1 byte and 256 KiB")


@dataclass(frozen=True, slots=True)
class ResourceTransferFinish:
    transfer_id: str

    def __post_init__(self) -> None:
        _transfer_identity(self.transfer_id)


@dataclass(frozen=True, slots=True)
class ResourceTransferAbort:
    transfer_id: str
    reason: str = ""

    def __post_init__(self) -> None:
        _transfer_identity(self.transfer_id)
        if not isinstance(self.reason, str) or len(self.reason.encode("utf-8")) > 4096:
            raise ValueError("A transfer abort reason must be bounded text")


type ResourceTransferFrame = (
    ResourceTransferStart | ResourceTransferChunk | ResourceTransferFinish | ResourceTransferAbort
)
