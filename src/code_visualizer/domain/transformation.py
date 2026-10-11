"""Immutable transformation descriptions and revision-pinned semantic origins."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class Representation:
    id: str
    version: str = "1"


PROGRAM_REPRESENTATION = Representation("code_visualizer.program")


@dataclass(frozen=True, slots=True)
class TransformationDefinition:
    id: str
    version: str
    source: Representation
    target: Representation
    depends_on: tuple[str, ...] = ()
    description: str = ""

    @property
    def key(self) -> str:
        return f"{self.id}@{self.version}"


@dataclass(frozen=True, slots=True)
class OriginLink:
    generated_id: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OriginMap:
    project_id: str
    revision: int
    links: tuple[OriginLink, ...] = ()

    def __post_init__(self) -> None:
        identities = [item.generated_id for item in self.links]
        if len(set(identities)) != len(identities):
            raise ValueError("An origin map cannot contain duplicate generated identities")
        if self.revision < 0:
            raise ValueError("An origin map revision must not be negative")
        if not self.project_id:
            raise ValueError("An origin map requires a project identity")
        if any(
            not item.generated_id
            or not item.source_ids
            or any(not source for source in item.source_ids)
            for item in self.links
        ):
            raise ValueError("Every origin link requires generated and source identities")
        if any(len(set(item.source_ids)) != len(item.source_ids) for item in self.links):
            raise ValueError("An origin link cannot repeat a source identity")

    def sources(self, generated_id: str) -> tuple[str, ...]:
        return next(
            (item.source_ids for item in self.links if item.generated_id == generated_id),
            (),
        )

    def composed_with(self, previous: OriginMap) -> OriginMap:
        """Resolve an output-to-input map through an earlier transformation's map."""

        if (self.project_id, self.revision) != (previous.project_id, previous.revision):
            raise ValueError("Origin composition requires the same project revision")
        earlier = {item.generated_id: item.source_ids for item in previous.links}
        return OriginMap(
            self.project_id,
            self.revision,
            tuple(
                OriginLink(
                    item.generated_id,
                    tuple(
                        sorted(
                            {
                                source
                                for intermediate in item.source_ids
                                for source in earlier.get(intermediate, (intermediate,))
                            }
                        )
                    ),
                )
                for item in sorted(self.links, key=lambda link: link.generated_id)
            ),
        )


def derived_id(transformation_key: str, source_id: str, role: str) -> str:
    """Namespaced identity independent of display name, collection order, or notation."""

    digest = hashlib.sha256(
        "\0".join((transformation_key, source_id, role)).encode("utf-8")
    ).hexdigest()[:28]
    return f"derived:{digest}"
