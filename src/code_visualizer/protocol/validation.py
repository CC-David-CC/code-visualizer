"""Bounded decoding with explicit version and unknown-field policy."""

from __future__ import annotations

from typing import Protocol, cast

from google.protobuf.message import DecodeError, Message

from code_visualizer.domain.boundaries import MAX_PORTABLE_ENVELOPE_BYTES

MAX_MESSAGE_BYTES = MAX_PORTABLE_ENVELOPE_BYTES
SCHEMA_VERSION = 1


class _UnknownFieldCleaner(Protocol):
    # The protobuf runtime supplies this API; types-protobuf omits it on Message.
    def DiscardUnknownFields(self) -> None: ...


class ProtocolBoundaryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def check_message(value: Message, *, version: int | None = None) -> None:
    if value.ByteSize() > MAX_MESSAGE_BYTES:
        raise ProtocolBoundaryError("PROTOCOL_SIZE_LIMIT", "Protobuf message exceeds 2 MiB")
    if version is not None and version != SCHEMA_VERSION:
        raise ProtocolBoundaryError("PROTOCOL_VERSION_UNSUPPORTED", "Supported schema version is 1")
    clean = type(value)()
    clean.CopyFrom(value)
    cast(_UnknownFieldCleaner, clean).DiscardUnknownFields()
    if clean.SerializeToString(deterministic=True) != value.SerializeToString(deterministic=True):
        raise ProtocolBoundaryError(
            "PROTOCOL_UNKNOWN_FIELD",
            "Message contains fields this contract version cannot preserve",
        )


def parse_message[T: Message](payload: bytes, message_type: type[T]) -> T:
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolBoundaryError("PROTOCOL_SIZE_LIMIT", "Protobuf message exceeds 2 MiB")
    result = message_type()
    try:
        result.ParseFromString(payload)
    except DecodeError as exc:
        raise ProtocolBoundaryError("PROTOCOL_MALFORMED", "Malformed protobuf message") from exc
    check_message(result)
    return result


def require_field(value: Message, name: str) -> None:
    if not value.HasField(name):
        raise ProtocolBoundaryError("PROTOCOL_FIELD_REQUIRED", f"{name} must be present")


def invalid(message: str) -> ProtocolBoundaryError:
    return ProtocolBoundaryError("PROTOCOL_VALUE_INVALID", message)
