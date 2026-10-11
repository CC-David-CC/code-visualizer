"""Deterministic semantic search and typed replacement command construction."""

from __future__ import annotations

from dataclasses import dataclass

from code_visualizer.application.commands import (
    ConfigurePythonRuntime,
    RenameDiagram,
    RenameProject,
    SetDrakonText,
    SetProgramDeclarationText,
    TransformFreeformObject,
    TypedCommand,
    UpdateMindMapTopic,
)
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Delay,
    DrakonAtom,
    DrakonDiagram,
    If,
    Input,
    Loop,
    Note,
    Output,
    Period,
    RealtimeProcess,
    Select,
    Silhouette,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    nested_sequences,
)
from code_visualizer.domain.freeform import FreeformDiagram, ShapeObject
from code_visualizer.domain.language_structure import language_records
from code_visualizer.domain.mindmap import MindMapDiagram, find_topic, walk_topics
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramExpression,
    ProgramModule,
    ProgramNote,
    iter_program_nodes,
    program_node_id,
)
from code_visualizer.domain.project import Project
from code_visualizer.persistence.decoding import runtime_settings_from_data
from code_visualizer.persistence.serialization import runtime_settings_to_data


@dataclass(frozen=True, slots=True)
class SearchMatch:
    diagram_id: str | None
    object_id: str
    field: str
    text: str
    path: str
    kind: str
    replace_supported: bool


_DRAKON_FIELDS: dict[type[object], tuple[str, ...]] = {
    Action: ("source",),
    Assignment: ("target", "value", "annotation", "operator"),
    Call: ("arguments", "expression", "result_target"),
    Delay: ("seconds",),
    If: ("condition",),
    Input: ("target", "prompt", "converter", "annotation"),
    Loop: ("condition", "target", "iterable", "children", "delay_seconds"),
    Note: ("text",),
    Output: ("expression", "destination", "end"),
    Period: ("timer", "seconds"),
    RealtimeProcess: ("call",),
    Select: ("expression",),
    Silhouette: ("display_name", "identifier"),
    SimpleStatement: ("source", "secondary"),
    StartTimer: ("timer",),
    Synchronizer: ("timer", "deadline"),
    Transfer: ("expression", "cause"),
}


def search_project(project: Project, query: str, *, limit: int = 500) -> tuple[SearchMatch, ...]:
    needle = query.casefold().strip()
    if not needle:
        return ()
    matches: list[SearchMatch] = []

    def add(
        *,
        diagram_id: str | None,
        object_id: str,
        field: str,
        value: object,
        path: str,
        kind: str,
        replace_supported: bool,
    ) -> None:
        if len(matches) >= limit or value is None:
            return
        text = str(value)
        if needle in text.casefold():
            matches.append(
                SearchMatch(
                    diagram_id,
                    object_id,
                    field,
                    text,
                    path,
                    kind,
                    replace_supported,
                )
            )

    add(
        diagram_id=None,
        object_id=project.id,
        field="title",
        value=project.title,
        path="project.title",
        kind="project",
        replace_supported=True,
    )
    for language in project.domain_workspace.language_definitions:
        for identity, record, _parent in language_records(language):
            for field in (
                "title",
                "name",
                "message",
                "label",
                "value",
                "identifier_prefix",
                "description",
            ):
                value = getattr(record, field, None)
                if isinstance(value, str):
                    add(
                        diagram_id=None,
                        object_id=identity,
                        field=field,
                        value=value,
                        path=f"languages.{language.id}.{identity}.{field}",
                        kind="domain_language",
                        replace_supported=False,
                    )
    for model in project.domain_workspace.models:
        schema = project.domain_workspace.schema(model.schema_id)
        if schema is None:
            continue
        for node in model.nodes:
            concept = schema.concept(node.concept_id)
            for prop in node.properties:
                definition = concept.property(prop.property_id) if concept is not None else None
                add(
                    diagram_id=None,
                    object_id=node.id,
                    field=prop.property_id,
                    value=prop.value,
                    path=f"{model.title or model.id} / "
                    f"{concept.name if concept else node.concept_id} / "
                    f"{definition.name if definition else prop.property_id}",
                    kind="domain_property",
                    replace_supported=isinstance(prop.value, str),
                )
    for document in project.documents:
        add(
            diagram_id=document.id,
            object_id=document.id,
            field="title",
            value=document.title,
            path=f"documents.{document.id}.title",
            kind=document.kind.value,
            replace_supported=True,
        )
        if isinstance(document, DrakonDiagram):
            drakon_id = document.id
            function = document.header.function
            for field in ("identifier", "display_name"):
                add(
                    diagram_id=document.id,
                    object_id=document.header.id,
                    field=field,
                    value=getattr(function, field),
                    path=f"documents.{document.id}.header.{field}",
                    kind="function_header",
                    replace_supported=True,
                )

            def visit(atom: DrakonAtom, diagram_id: str = drakon_id) -> None:
                for field in _DRAKON_FIELDS.get(type(atom), ()):
                    add(
                        diagram_id=diagram_id,
                        object_id=atom.id,
                        field=field,
                        value=getattr(atom, field),
                        path=f"documents.{diagram_id}.atoms.{atom.id}.{field}",
                        kind=type(atom).__name__,
                        replace_supported=True,
                    )
                for sequence in nested_sequences(atom):
                    for child in sequence.atoms:
                        visit(child)

            for atom in document.body.atoms:
                visit(atom)
        elif isinstance(document, MindMapDiagram):
            for topic in walk_topics(document.root):
                for field in ("text", "notes"):
                    add(
                        diagram_id=document.id,
                        object_id=topic.id,
                        field=field,
                        value=getattr(topic, field),
                        path=f"documents.{document.id}.topics.{topic.id}.{field}",
                        kind="mind_topic",
                        replace_supported=True,
                    )
        elif isinstance(document, FreeformDiagram):
            for item in document.objects:
                if isinstance(item, ShapeObject):
                    add(
                        diagram_id=document.id,
                        object_id=item.id,
                        field="text",
                        value=item.text,
                        path=f"documents.{document.id}.objects.{item.id}.text",
                        kind=f"freeform_{item.shape.value}",
                        replace_supported=True,
                    )

    for program_node in iter_program_nodes(
        (project.program_model.modules, project.program_model.entrypoint)
    ):
        editable_fields = (
            ("path", "docstring")
            if isinstance(program_node, ProgramModule)
            else ("identifier", "docstring")
            if isinstance(program_node, ProgramClass)
            else ("source",)
            if isinstance(program_node, ProgramExpression)
            else ("text",)
            if isinstance(program_node, ProgramNote)
            else ()
        )
        for field in editable_fields:
            add(
                diagram_id=None,
                object_id=program_node_id(program_node),
                field=field,
                value=getattr(program_node, field),
                path=f"program.{program_node_id(program_node)}.{field}",
                kind="program_declaration",
                replace_supported=True,
            )

    def visit_setup(value: JsonValue, path: str) -> None:
        if len(matches) >= limit:
            return
        if isinstance(value, dict):
            for key in sorted(value):
                visit_setup(value[key], f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit_setup(item, f"{path}[{index}]")
        elif isinstance(value, str):
            add(
                diagram_id=None,
                object_id=project.id,
                field=path.rsplit(".", 1)[-1],
                value=value,
                path=path,
                kind="runtime_settings",
                replace_supported=True,
            )

    visit_setup(runtime_settings_to_data(project.runtime_settings), "runtime_settings")
    return tuple(matches)


def replacement_command(
    project: Project,
    match: SearchMatch,
    value: str,
) -> TypedCommand | None:
    if not match.replace_supported:
        return None
    if match.kind == "project":
        return RenameProject(value)
    if match.kind == "domain_property":
        model = next(
            (
                item
                for item in project.domain_workspace.models
                if item.node(match.object_id) is not None
            ),
            None,
        )
        return (
            SetDomainProperty(model.id, match.object_id, match.field, value)
            if model is not None
            else None
        )
    if match.kind == "program_declaration":
        return SetProgramDeclarationText(match.object_id, match.field, value)
    if match.kind == "runtime_settings":
        setup_data = runtime_settings_to_data(project.runtime_settings)
        replaced = _replace_json_path(setup_data, match.path, value)
        return ConfigurePythonRuntime(runtime_settings_from_data(replaced))
    document = next(
        (item for item in project.documents if item.id == match.diagram_id),
        None,
    )
    if document is None:
        return None
    if match.object_id == document.id and match.field == "title":
        return RenameDiagram(document.id, value)
    if isinstance(document, DrakonDiagram):
        return SetDrakonText(document.id, match.object_id, match.field, value)
    if isinstance(document, MindMapDiagram):
        topic = find_topic(document.root, match.object_id)
        if topic is None:
            return None
        return UpdateMindMapTopic(
            document.id,
            topic.id,
            value if match.field == "text" else topic.text,
            value if match.field == "notes" else topic.notes,
            topic.collapsed,
            topic.links,
            topic.attachments,
        )
    if isinstance(document, FreeformDiagram):
        shape = next(
            (
                item
                for item in document.objects
                if isinstance(item, ShapeObject) and item.id == match.object_id
            ),
            None,
        )
        if shape is not None:
            return TransformFreeformObject(
                document.id,
                shape.id,
                shape.bounds,
                shape.rotation,
                text=value,
                fill=shape.fill,
                stroke=shape.stroke,
                asset_id=shape.asset_id,
            )
    return None


def replacement_commands(
    project: Project,
    replacements: tuple[tuple[SearchMatch, str], ...],
) -> tuple[TypedCommand, ...]:
    """Build one non-clobbering command set for a Replace All transaction."""

    commands: list[TypedCommand] = []
    setup_data = runtime_settings_to_data(project.runtime_settings)
    setup_changed = False
    topic_values: dict[tuple[str, str], dict[str, str]] = {}
    topic_matches: dict[tuple[str, str], SearchMatch] = {}

    for match, value in replacements:
        if not match.replace_supported:
            continue
        if match.kind == "runtime_settings":
            setup_data = _replace_json_path(setup_data, match.path, value)
            setup_changed = True
            continue
        if match.kind == "mind_topic" and match.diagram_id is not None:
            key = (match.diagram_id, match.object_id)
            topic_values.setdefault(key, {})[match.field] = value
            topic_matches[key] = match
            continue
        command = replacement_command(project, match, value)
        if command is not None:
            commands.append(command)

    for key in sorted(topic_values):
        diagram_id, topic_id = key
        document = next(
            (
                item
                for item in project.documents
                if isinstance(item, MindMapDiagram) and item.id == diagram_id
            ),
            None,
        )
        topic = find_topic(document.root, topic_id) if document is not None else None
        if topic is None:
            continue
        values = topic_values[key]
        commands.append(
            UpdateMindMapTopic(
                diagram_id,
                topic.id,
                values.get("text", topic.text),
                values.get("notes", topic.notes),
                topic.collapsed,
                topic.links,
                topic.attachments,
            )
        )

    if setup_changed:
        commands.append(ConfigurePythonRuntime(runtime_settings_from_data(setup_data)))
    return tuple(commands)


def _replace_json_path(
    setup_data: dict[str, JsonValue],
    path: str,
    replacement: str,
) -> dict[str, JsonValue]:
    prefix = "runtime_settings"
    if path != prefix and not path.startswith(f"{prefix}."):
        raise ValueError(f"Not a Python Project path: {path}")
    suffix = path[len(prefix) :]
    tokens: list[str | int] = []
    cursor = 0
    while cursor < len(suffix):
        marker = suffix[cursor]
        if marker == ".":
            cursor += 1
            end = cursor
            while end < len(suffix) and suffix[end] not in ".[":
                end += 1
            if end == cursor:
                raise ValueError(f"Invalid Python Project path: {path}")
            tokens.append(suffix[cursor:end])
            cursor = end
        elif marker == "[":
            end = suffix.find("]", cursor)
            if end < 0 or not suffix[cursor + 1 : end].isdigit():
                raise ValueError(f"Invalid Python Project path: {path}")
            tokens.append(int(suffix[cursor + 1 : end]))
            cursor = end + 1
        else:
            raise ValueError(f"Invalid Python Project path: {path}")
    if not tokens:
        raise ValueError("A Python Project scalar path is required")

    def replace_at(value: JsonValue, remaining: list[str | int]) -> JsonValue:
        token = remaining[0]
        tail = remaining[1:]
        if isinstance(token, str) and isinstance(value, dict) and token in value:
            return {
                key: (
                    replace_at(item, tail)
                    if key == token and tail
                    else replacement
                    if key == token
                    else item
                )
                for key, item in value.items()
            }
        if isinstance(token, int) and isinstance(value, list) and 0 <= token < len(value):
            return [
                replace_at(item, tail)
                if index == token and tail
                else replacement
                if index == token
                else item
                for index, item in enumerate(value)
            ]
        raise ValueError(f"Python Project path does not exist: {path}")

    result = replace_at(setup_data, tokens)
    if not isinstance(result, dict):
        raise ValueError(f"Python Project path did not preserve an object: {path}")
    return result
