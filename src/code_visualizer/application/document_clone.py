"""Mode-aware document cloning with fresh semantic identities."""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.domain.common import JsonValue, new_id
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.project import ProjectDocument
from code_visualizer.persistence.decoding import document_from_data
from code_visualizer.persistence.serialization import document_to_data


def clone_document(
    document: ProjectDocument,
    *,
    title: str | None = None,
    document_id: str | None = None,
) -> ProjectDocument:
    """Clone a complete document while preserving only intentional external references."""

    raw = document_to_data(document)
    identifiers: list[str] = []

    def collect(value: JsonValue) -> None:
        if isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key == "id" and isinstance(item, str):
                    identifiers.append(item)
                collect(item)

    collect(raw)
    mapping: dict[str, str] = {}
    for identifier in identifiers:
        prefix = identifier.split("_", 1)[0]
        mapping[identifier] = new_id(prefix if prefix.isidentifier() else "object")
    mapping[document.id] = document_id or new_id("diagram")

    def remap(value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return mapping.get(value, value)
        if isinstance(value, list):
            return [remap(item) for item in value]
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        return value

    cloned_data = remap(raw)
    assert isinstance(cloned_data, dict)
    cloned_data["title"] = title or f"{document.title} Copy"
    cloned = document_from_data(cloned_data)
    if isinstance(cloned, DrakonDiagram):
        function = cloned.header.function
        cloned = replace(
            cloned,
            header=replace(
                cloned.header,
                function=replace(
                    function,
                    identifier=f"{function.identifier}_copy",
                    display_name=f"{function.display_name} Copy",
                ),
            ),
        )
    return cloned
