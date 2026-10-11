"""Discoverable substantial-operation registry for vertical feature slices."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from code_visualizer.domain.common import JsonValue


class CapabilityKind(StrEnum):
    ANALYSIS = "analysis"
    GENERATOR = "generator"
    EXECUTION = "execution"
    EXPORT = "export"
    LAYOUT = "layout"
    VIEW = "view"


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    id: str
    label: str
    kind: CapabilityKind
    description: str
    input_contract: dict[str, JsonValue]
    output_contract: dict[str, JsonValue]


CapabilityHandler = Callable[[Mapping[str, object]], object]


@dataclass(frozen=True, slots=True)
class RegisteredCapability:
    descriptor: CapabilityDescriptor
    handler: CapabilityHandler

    def invoke(self, inputs: Mapping[str, object] | None = None) -> object:
        return self.handler({} if inputs is None else inputs)


class CapabilityRegistry:
    """Small stable service boundary; registration order never affects discovery."""

    def __init__(self) -> None:
        self._entries: dict[str, RegisteredCapability] = {}
        self._lock = RLock()

    def register(
        self,
        descriptor: CapabilityDescriptor,
        handler: CapabilityHandler,
        *,
        replace: bool = False,
    ) -> Callable[[], None]:
        with self._lock:
            if descriptor.id in self._entries and not replace:
                raise ValueError(f"Capability {descriptor.id!r} is already registered")
            entry = RegisteredCapability(descriptor, handler)
            self._entries[descriptor.id] = entry

        def unregister() -> None:
            with self._lock:
                if self._entries.get(descriptor.id) is entry:
                    self._entries.pop(descriptor.id, None)

        return unregister

    def get(self, capability_id: str) -> RegisteredCapability:
        with self._lock:
            try:
                return self._entries[capability_id]
            except KeyError as exc:
                raise KeyError(f"Unknown capability {capability_id!r}") from exc

    def descriptors(
        self,
        *,
        kind: CapabilityKind | None = None,
    ) -> tuple[CapabilityDescriptor, ...]:
        with self._lock:
            descriptors = tuple(entry.descriptor for entry in self._entries.values())
        return tuple(
            sorted(
                (item for item in descriptors if kind is None or item.kind is kind),
                key=lambda item: item.id,
            )
        )

    def invoke(
        self,
        capability_id: str,
        inputs: Mapping[str, object] | None = None,
    ) -> object:
        return self.get(capability_id).invoke(inputs)
