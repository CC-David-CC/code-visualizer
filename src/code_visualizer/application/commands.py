"""Typed semantic commands used by SDK, CLI, GUI, and protocol adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from code_visualizer.domain.assets import ManagedAsset, ShapePackReference
from code_visualizer.domain.authoring import AuthoredSemanticRelation, SemanticConcept
from code_visualizer.domain.common import DocumentKind, JsonValue, new_id
from code_visualizer.domain.drakon import DrakonAtom
from code_visualizer.domain.freeform import GuideOrientation, Rect, ShapeKind
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramEntryPoint,
    ProgramModule,
    ProgramStatement,
)
from code_visualizer.domain.program_signatures import FunctionSpec
from code_visualizer.domain.project import ProjectDocument, PythonRuntimeSettings
from code_visualizer.domain.projection import ProjectionDefinition, ProjectionViewTarget
from code_visualizer.persistence.serialization import (
    document_to_data,
    drakon_atom_to_data,
    function_spec_to_data,
    program_class_to_data,
    program_entrypoint_to_data,
    program_module_to_data,
    program_statement_to_data,
    projection_definition_to_data,
    runtime_settings_to_data,
)


@dataclass(frozen=True, slots=True)
class Operation:
    command_type: str
    payload: dict[str, JsonValue]

    def to_data(self) -> dict[str, JsonValue]:
        return {"command_type": self.command_type, "payload": self.payload}

    @classmethod
    def from_data(cls, value: object) -> Operation:
        if not isinstance(value, dict):
            raise ValueError("Operation must be an object")
        command_type = value.get("command_type")
        payload = value.get("payload")
        if not isinstance(command_type, str) or not isinstance(payload, dict):
            raise ValueError("Operation requires command_type and payload")
        return cls(
            command_type=command_type,
            payload={str(key): item for key, item in payload.items()},
        )


class TypedCommand(Protocol):
    def to_operation(self) -> Operation: ...


@dataclass(frozen=True, slots=True)
class RenameProject:
    title: str

    def to_operation(self) -> Operation:
        return Operation("project.rename", {"title": self.title})


@dataclass(frozen=True, slots=True)
class CreateDiagram:
    kind: DocumentKind
    title: str
    identifier: str | None = None
    document_id: str | None = None
    module: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "diagram.create",
            {
                "document_id": self.document_id or new_id("diagram"),
                "identifier": self.identifier,
                "kind": self.kind.value,
                "module": self.module,
                "title": self.title,
            },
        )


@dataclass(frozen=True, slots=True)
class RenameDiagram:
    diagram_id: str
    title: str

    def to_operation(self) -> Operation:
        return Operation(
            "diagram.rename",
            {"diagram_id": self.diagram_id, "title": self.title},
        )


@dataclass(frozen=True, slots=True)
class MoveDiagram:
    diagram_id: str
    index: int

    def to_operation(self) -> Operation:
        return Operation("diagram.move", {"diagram_id": self.diagram_id, "index": self.index})


@dataclass(frozen=True, slots=True)
class DuplicateDiagram:
    diagram_id: str
    title: str | None = None
    document_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "diagram.duplicate",
            {
                "diagram_id": self.diagram_id,
                "document_id": self.document_id or new_id("diagram"),
                "title": self.title,
            },
        )


@dataclass(frozen=True, slots=True)
class ReplaceDiagramSnapshot:
    """Atomically replace one document with a fully validated semantic snapshot."""

    document: ProjectDocument

    def to_operation(self) -> Operation:
        return Operation(
            "diagram.replace_snapshot",
            {
                "diagram_id": self.document.id,
                "document": document_to_data(self.document),
            },
        )


@dataclass(frozen=True, slots=True)
class SetFunctionOwner:
    function_id: str
    owner_id: str
    index: int | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "program.function.set_owner",
            {"function_id": self.function_id, "owner_id": self.owner_id, "index": self.index},
        )


@dataclass(frozen=True, slots=True)
class ReplaceFunctionSpec:
    diagram_id: str
    function: FunctionSpec

    def to_operation(self) -> Operation:
        return Operation(
            "function.replace_spec",
            {
                "diagram_id": self.diagram_id,
                "function": function_spec_to_data(self.function),
            },
        )


@dataclass(frozen=True, slots=True)
class ReplaceProgramFunctionSignature:
    function_id: str
    signature: FunctionSpec

    def to_operation(self) -> Operation:
        return Operation(
            "program.function.replace_signature",
            {
                "function_id": self.function_id,
                "signature": function_spec_to_data(self.signature),
            },
        )


@dataclass(frozen=True, slots=True)
class CreateProgramFunction:
    """Create executable behavior without first creating a presentation view."""

    identifier: str
    owner_id: str
    display_name: str | None = None
    function_id: str | None = None
    symbol_id: str | None = None
    body_sequence_id: str | None = None

    def to_operation(self) -> Operation:
        function_id = self.function_id or new_id("function")
        return Operation(
            "program.function.create",
            {
                "body_sequence_id": self.body_sequence_id or new_id("sequence"),
                "display_name": self.display_name,
                "function_id": function_id,
                "identifier": self.identifier,
                "owner_id": self.owner_id,
                "symbol_id": self.symbol_id or new_id("symbol"),
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteProgramFunction:
    function_id: str

    def to_operation(self) -> Operation:
        return Operation("program.function.delete", {"function_id": self.function_id})


@dataclass(frozen=True, slots=True)
class InsertProgramStatement:
    """Insert a canonical subtree, or construct one of the common leaf operations."""

    function_id: str
    sequence_id: str
    index: int
    statement_kind: str = "structured"
    statement_id: str | None = None
    target: str | None = None
    value: str | None = None
    annotation: str | None = None
    operator: str = "="
    expression: str | None = None
    destination: str | None = None
    end: str | None = None
    arguments: str = ""
    awaited: bool = False
    result_target: str | None = None
    target_function_id: str | None = None
    condition: str | None = None
    preferred_truth: bool = True
    true_sequence_id: str | None = None
    false_sequence_id: str | None = None

    statement: ProgramStatement | None = None

    def to_operation(self) -> Operation:
        if self.statement is not None:
            return Operation(
                "program.statement.insert",
                {
                    "function_id": self.function_id,
                    "sequence_id": self.sequence_id,
                    "index": self.index,
                    "statement_id": self.statement_id or self.statement.id,
                    "statement": program_statement_to_data(self.statement),
                },
            )
        return Operation(
            "program.statement.insert",
            {
                "annotation": self.annotation,
                "arguments": self.arguments,
                "awaited": self.awaited,
                "condition": self.condition,
                "destination": self.destination,
                "end": self.end,
                "expression": self.expression,
                "false_sequence_id": self.false_sequence_id or new_id("sequence"),
                "function_id": self.function_id,
                "index": self.index,
                "operator": self.operator,
                "preferred_truth": self.preferred_truth,
                "result_target": self.result_target,
                "sequence_id": self.sequence_id,
                "statement_id": self.statement_id or new_id("statement"),
                "statement_kind": self.statement_kind,
                "target": self.target,
                "target_function_id": self.target_function_id,
                "true_sequence_id": self.true_sequence_id or new_id("sequence"),
                "value": self.value,
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteProgramStatements:
    function_id: str
    sequence_id: str
    statement_ids: tuple[str, ...]

    def to_operation(self) -> Operation:
        return Operation(
            "program.statement.delete",
            {
                "function_id": self.function_id,
                "sequence_id": self.sequence_id,
                "statement_ids": list(self.statement_ids),
            },
        )


@dataclass(frozen=True, slots=True)
class MoveProgramStatements:
    function_id: str
    source_sequence_id: str
    statement_ids: tuple[str, ...]
    destination_sequence_id: str
    destination_index: int

    def to_operation(self) -> Operation:
        return Operation(
            "program.statement.move",
            {
                "destination_index": self.destination_index,
                "destination_sequence_id": self.destination_sequence_id,
                "function_id": self.function_id,
                "source_sequence_id": self.source_sequence_id,
                "statement_ids": list(self.statement_ids),
            },
        )


@dataclass(frozen=True, slots=True)
class ReplaceProgramExpression:
    function_id: str
    expression_id: str
    source: str

    def to_operation(self) -> Operation:
        return Operation(
            "program.expression.replace",
            {
                "expression_id": self.expression_id,
                "function_id": self.function_id,
                "source": self.source,
            },
        )


@dataclass(frozen=True, slots=True)
class ReplaceProgramOutput:
    function_id: str
    statement_id: str
    expression: str
    destination: str | None = None
    end: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "program.output.replace",
            {
                "destination": self.destination,
                "end": self.end,
                "expression": self.expression,
                "function_id": self.function_id,
                "statement_id": self.statement_id,
            },
        )


@dataclass(frozen=True, slots=True)
class RenameProgramSymbol:
    symbol_id: str
    name: str

    def to_operation(self) -> Operation:
        return Operation(
            "program.symbol.rename",
            {"name": self.name, "symbol_id": self.symbol_id},
        )


@dataclass(frozen=True, slots=True)
class ConfigurePythonRuntime:
    settings: PythonRuntimeSettings

    def to_operation(self) -> Operation:
        return Operation("python.configure_runtime", runtime_settings_to_data(self.settings))


@dataclass(frozen=True, slots=True)
class ConfigureProgram:
    package: str
    modules: tuple[ProgramModule, ...]
    entrypoint: ProgramEntryPoint | None

    def to_operation(self) -> Operation:
        return Operation(
            "program.configure",
            {
                "package": self.package,
                "modules": [program_module_to_data(item) for item in self.modules],
                "entrypoint": program_entrypoint_to_data(self.entrypoint)
                if self.entrypoint is not None
                else None,
            },
        )


@dataclass(frozen=True, slots=True)
class PutProgramModule:
    module: ProgramModule

    def to_operation(self) -> Operation:
        return Operation("program.module.put", {"module": program_module_to_data(self.module)})


@dataclass(frozen=True, slots=True)
class DeleteProgramModule:
    module_id: str

    def to_operation(self) -> Operation:
        return Operation("program.module.delete", {"module_id": self.module_id})


@dataclass(frozen=True, slots=True)
class PutProgramClass:
    owner_id: str
    declaration: ProgramClass

    def to_operation(self) -> Operation:
        return Operation(
            "program.class.put",
            {
                "owner_id": self.owner_id,
                "class": program_class_to_data(self.declaration),
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteProgramClass:
    class_id: str

    def to_operation(self) -> Operation:
        return Operation("program.class.delete", {"class_id": self.class_id})


@dataclass(frozen=True, slots=True)
class ConfigureProgramEntryPoint:
    entrypoint: ProgramEntryPoint | None

    def to_operation(self) -> Operation:
        return Operation(
            "program.entrypoint.configure",
            {
                "entrypoint": program_entrypoint_to_data(self.entrypoint)
                if self.entrypoint is not None
                else None,
            },
        )


@dataclass(frozen=True, slots=True)
class SetProgramDeclarationText:
    declaration_id: str
    field: str
    value: str

    def to_operation(self) -> Operation:
        return Operation(
            "program.declaration.set_text",
            {
                "declaration_id": self.declaration_id,
                "field": self.field,
                "value": self.value,
            },
        )


@dataclass(frozen=True, slots=True)
class InsertDrakonAtom:
    diagram_id: str
    atom_kind: str
    index: int
    source: str | None = None
    target: str | None = None
    value: str | None = None
    annotation: str | None = None
    operator: str | None = None
    atom_id: str | None = None
    sequence_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "drakon.insert",
            {
                "annotation": self.annotation,
                "atom_id": self.atom_id or new_id("atom"),
                "atom_kind": self.atom_kind,
                "diagram_id": self.diagram_id,
                "index": self.index,
                "operator": self.operator,
                "source": self.source,
                "sequence_id": self.sequence_id,
                "target": self.target,
                "value": self.value,
            },
        )


@dataclass(frozen=True, slots=True)
class MoveDrakonBlock:
    diagram_id: str
    source_sequence_id: str
    atom_ids: tuple[str, ...]
    destination_sequence_id: str
    destination_index: int

    def to_operation(self) -> Operation:
        return Operation(
            "drakon.move_block",
            {
                "atom_ids": list(self.atom_ids),
                "destination_index": self.destination_index,
                "destination_sequence_id": self.destination_sequence_id,
                "diagram_id": self.diagram_id,
                "source_sequence_id": self.source_sequence_id,
            },
        )


@dataclass(frozen=True, slots=True)
class InsertDrakonBlock:
    diagram_id: str
    sequence_id: str
    index: int
    atoms: tuple[DrakonAtom, ...]

    def to_operation(self) -> Operation:
        return Operation(
            "drakon.insert_block",
            {
                "atoms": [drakon_atom_to_data(atom) for atom in self.atoms],
                "diagram_id": self.diagram_id,
                "index": self.index,
                "sequence_id": self.sequence_id,
            },
        )


@dataclass(frozen=True, slots=True)
class RemoveDrakonBlock:
    diagram_id: str
    sequence_id: str
    atom_ids: tuple[str, ...]

    def to_operation(self) -> Operation:
        return Operation(
            "drakon.remove_block",
            {
                "atom_ids": list(self.atom_ids),
                "diagram_id": self.diagram_id,
                "sequence_id": self.sequence_id,
            },
        )


@dataclass(frozen=True, slots=True)
class ReplaceDrakonAtom:
    diagram_id: str
    atom_id: str
    atom: DrakonAtom

    def to_operation(self) -> Operation:
        return Operation(
            "drakon.replace",
            {
                "atom": drakon_atom_to_data(self.atom),
                "atom_id": self.atom_id,
                "diagram_id": self.diagram_id,
            },
        )


@dataclass(frozen=True, slots=True)
class WrapDrakonBlock:
    diagram_id: str
    sequence_id: str
    atom_ids: tuple[str, ...]
    wrapper: DrakonAtom

    def to_operation(self) -> Operation:
        return Operation(
            "drakon.wrap",
            {
                "atom_ids": list(self.atom_ids),
                "diagram_id": self.diagram_id,
                "sequence_id": self.sequence_id,
                "wrapper": drakon_atom_to_data(self.wrapper),
            },
        )


@dataclass(frozen=True, slots=True)
class UnwrapDrakonAtom:
    diagram_id: str
    atom_id: str
    body_sequence_id: str | None = None
    discard_other_bodies: bool = False

    def to_operation(self) -> Operation:
        return Operation(
            "drakon.unwrap",
            {
                "atom_id": self.atom_id,
                "body_sequence_id": self.body_sequence_id,
                "diagram_id": self.diagram_id,
                "discard_other_bodies": self.discard_other_bodies,
            },
        )


@dataclass(frozen=True, slots=True)
class SetDrakonText:
    diagram_id: str
    atom_id: str
    field: str
    value: str

    def to_operation(self) -> Operation:
        return Operation(
            "drakon.set_text",
            {
                "atom_id": self.atom_id,
                "diagram_id": self.diagram_id,
                "field": self.field,
                "value": self.value,
            },
        )


@dataclass(frozen=True, slots=True)
class AddMindMapTopic:
    diagram_id: str
    parent_id: str
    text: str
    index: int
    topic_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "mindmap.add_topic",
            {
                "diagram_id": self.diagram_id,
                "index": self.index,
                "parent_id": self.parent_id,
                "text": self.text,
                "topic_id": self.topic_id or new_id("topic"),
            },
        )


@dataclass(frozen=True, slots=True)
class UpdateMindMapTopic:
    diagram_id: str
    topic_id: str
    text: str
    notes: str = ""
    collapsed: bool = False
    links: tuple[str, ...] = ()
    attachments: tuple[str, ...] = ()
    derive_label: bool = False
    update_label: bool = True

    def to_operation(self) -> Operation:
        return Operation(
            "mindmap.update_topic",
            {
                "attachments": list(self.attachments),
                "collapsed": self.collapsed,
                "diagram_id": self.diagram_id,
                "links": list(self.links),
                "notes": self.notes,
                "text": self.text,
                "topic_id": self.topic_id,
                "derive_label": self.derive_label,
                "update_label": self.update_label,
            },
        )


@dataclass(frozen=True, slots=True)
class MoveMindMapTopic:
    diagram_id: str
    topic_id: str
    parent_id: str
    index: int

    def to_operation(self) -> Operation:
        return Operation(
            "mindmap.move_topic",
            {
                "diagram_id": self.diagram_id,
                "index": self.index,
                "parent_id": self.parent_id,
                "topic_id": self.topic_id,
            },
        )


@dataclass(frozen=True, slots=True)
class RemoveMindMapTopic:
    diagram_id: str
    topic_id: str
    promote_children: bool = False

    def to_operation(self) -> Operation:
        return Operation(
            "mindmap.remove_topic",
            {
                "diagram_id": self.diagram_id,
                "promote_children": self.promote_children,
                "topic_id": self.topic_id,
            },
        )


@dataclass(frozen=True, slots=True)
class AddMindMapCrossLink:
    diagram_id: str
    source_topic_id: str
    target_topic_id: str
    label: str = ""
    link_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "mindmap.add_cross_link",
            {
                "diagram_id": self.diagram_id,
                "label": self.label,
                "link_id": self.link_id or new_id("cross-link"),
                "source_topic_id": self.source_topic_id,
                "target_topic_id": self.target_topic_id,
            },
        )


@dataclass(frozen=True, slots=True)
class SetMindMapLayout:
    diagram_id: str
    layout: str

    def to_operation(self) -> Operation:
        return Operation(
            "mindmap.set_layout",
            {"diagram_id": self.diagram_id, "layout": self.layout},
        )


@dataclass(frozen=True, slots=True)
class SetViewAnchor:
    """Anchor a presentation glyph to a semantic object or relationship."""

    diagram_id: str
    object_id: str
    semantic_id: str | None = None
    semantic_relation_id: str | None = None

    def __post_init__(self) -> None:
        if self.semantic_id is not None and self.semantic_relation_id is not None:
            raise ValueError("A view object cannot anchor to an object and relation together")

    def to_operation(self) -> Operation:
        return Operation(
            "view.set_anchor",
            {
                "diagram_id": self.diagram_id,
                "object_id": self.object_id,
                "semantic_id": self.semantic_id,
                "semantic_relation_id": self.semantic_relation_id,
            },
        )


@dataclass(frozen=True, slots=True)
class PutSemanticConcept:
    concept: SemanticConcept

    def to_operation(self) -> Operation:
        return Operation(
            "semantic.concept.put",
            {
                "description": self.concept.description,
                "id": self.concept.id,
                "member_ids": list(self.concept.member_ids),
                "tags": list(self.concept.tags),
                "title": self.concept.title,
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteSemanticConcept:
    concept_id: str

    def to_operation(self) -> Operation:
        return Operation("semantic.concept.delete", {"concept_id": self.concept_id})


@dataclass(frozen=True, slots=True)
class PutAuthoredSemanticRelation:
    relation: AuthoredSemanticRelation

    def to_operation(self) -> Operation:
        return Operation(
            "semantic.relation.put",
            {
                "description": self.relation.description,
                "id": self.relation.id,
                "kind": self.relation.kind.value,
                "label": self.relation.label,
                "source_id": self.relation.source_id,
                "target_id": self.relation.target_id,
            },
        )


@dataclass(frozen=True, slots=True)
class DeleteAuthoredSemanticRelation:
    relation_id: str

    def to_operation(self) -> Operation:
        return Operation("semantic.relation.delete", {"relation_id": self.relation_id})


@dataclass(frozen=True, slots=True)
class PutProjectionDefinition:
    definition: ProjectionDefinition

    def to_operation(self) -> Operation:
        return Operation("projection.put", projection_definition_to_data(self.definition))


@dataclass(frozen=True, slots=True)
class DeleteProjectionDefinition:
    definition_id: str

    def to_operation(self) -> Operation:
        return Operation("projection.delete", {"definition_id": self.definition_id})


@dataclass(frozen=True, slots=True)
class MaterializeProjectionView:
    definition: ProjectionDefinition
    target: ProjectionViewTarget
    title: str
    document_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "projection.materialize",
            {
                "definition": projection_definition_to_data(self.definition),
                "document_id": self.document_id or new_id("diagram"),
                "target": self.target.value,
                "title": self.title,
            },
        )


@dataclass(frozen=True, slots=True)
class CreateFreeformShape:
    diagram_id: str
    shape: ShapeKind
    bounds: Rect
    text: str = ""
    object_id: str | None = None
    layer_id: str = "layer_default"

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.create",
            {
                "bounds": {
                    "height": self.bounds.height,
                    "width": self.bounds.width,
                    "x": self.bounds.x,
                    "y": self.bounds.y,
                },
                "diagram_id": self.diagram_id,
                "layer_id": self.layer_id,
                "object_id": self.object_id or new_id("shape"),
                "shape": self.shape.value,
                "text": self.text,
            },
        )


@dataclass(frozen=True, slots=True)
class TransformFreeformObject:
    diagram_id: str
    object_id: str
    bounds: Rect
    rotation: float = 0.0
    text: str | None = None
    fill: str | None = None
    stroke: str | None = None
    asset_id: str | None = None
    derive_label: bool = False

    def to_operation(self) -> Operation:
        payload: dict[str, JsonValue] = {
            "bounds": {
                "height": self.bounds.height,
                "width": self.bounds.width,
                "x": self.bounds.x,
                "y": self.bounds.y,
            },
            "diagram_id": self.diagram_id,
            "object_id": self.object_id,
            "rotation": self.rotation,
        }
        if self.text is not None:
            payload["text"] = self.text
        if self.fill is not None:
            payload["fill"] = self.fill
        if self.stroke is not None:
            payload["stroke"] = self.stroke
        if self.asset_id is not None:
            payload["asset_id"] = self.asset_id
        payload["derive_label"] = self.derive_label
        return Operation("freeform.transform", payload)


@dataclass(frozen=True, slots=True)
class RemoveFreeformObjects:
    diagram_id: str
    object_ids: tuple[str, ...]

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.remove",
            {"diagram_id": self.diagram_id, "object_ids": list(self.object_ids)},
        )


@dataclass(frozen=True, slots=True)
class CreateFreeformConnector:
    diagram_id: str
    source_id: str
    target_id: str
    label: str = ""
    orthogonal: bool = True
    connector_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.connect",
            {
                "connector_id": self.connector_id or new_id("connector"),
                "diagram_id": self.diagram_id,
                "label": self.label,
                "orthogonal": self.orthogonal,
                "source_id": self.source_id,
                "target_id": self.target_id,
            },
        )


@dataclass(frozen=True, slots=True)
class SetFreeformObjectProperties:
    diagram_id: str
    object_ids: tuple[str, ...]
    locked: bool | None = None
    hidden: bool | None = None
    layer_id: str | None = None
    group_id: str | None = None
    z_index: int | None = None

    def to_operation(self) -> Operation:
        payload: dict[str, JsonValue] = {
            "diagram_id": self.diagram_id,
            "object_ids": list(self.object_ids),
        }
        if self.locked is not None:
            payload["locked"] = self.locked
        if self.hidden is not None:
            payload["hidden"] = self.hidden
        if self.layer_id is not None:
            payload["layer_id"] = self.layer_id
        if self.group_id is not None:
            payload["group_id"] = self.group_id
        if self.z_index is not None:
            payload["z_index"] = self.z_index
        return Operation("freeform.set_properties", payload)


@dataclass(frozen=True, slots=True)
class ArrangeFreeformObjects:
    diagram_id: str
    object_ids: tuple[str, ...]
    arrangement: str

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.arrange",
            {
                "arrangement": self.arrangement,
                "diagram_id": self.diagram_id,
                "object_ids": list(self.object_ids),
            },
        )


@dataclass(frozen=True, slots=True)
class AddFreeformLayer:
    diagram_id: str
    name: str
    layer_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.layer.add",
            {
                "diagram_id": self.diagram_id,
                "layer_id": self.layer_id or new_id("layer"),
                "name": self.name,
            },
        )


@dataclass(frozen=True, slots=True)
class UpdateFreeformLayer:
    diagram_id: str
    layer_id: str
    name: str
    hidden: bool = False
    locked: bool = False

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.layer.update",
            {
                "diagram_id": self.diagram_id,
                "hidden": self.hidden,
                "layer_id": self.layer_id,
                "locked": self.locked,
                "name": self.name,
            },
        )


@dataclass(frozen=True, slots=True)
class RemoveFreeformLayer:
    diagram_id: str
    layer_id: str
    fallback_layer_id: str = "layer_default"

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.layer.remove",
            {
                "diagram_id": self.diagram_id,
                "fallback_layer_id": self.fallback_layer_id,
                "layer_id": self.layer_id,
            },
        )


@dataclass(frozen=True, slots=True)
class AddFreeformGuide:
    diagram_id: str
    orientation: GuideOrientation
    position: float
    guide_id: str | None = None

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.guide.add",
            {
                "diagram_id": self.diagram_id,
                "guide_id": self.guide_id or new_id("guide"),
                "orientation": self.orientation.value,
                "position": self.position,
            },
        )


@dataclass(frozen=True, slots=True)
class RemoveFreeformGuide:
    diagram_id: str
    guide_id: str

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.guide.remove",
            {"diagram_id": self.diagram_id, "guide_id": self.guide_id},
        )


@dataclass(frozen=True, slots=True)
class SetFreeformCanvasOptions:
    diagram_id: str
    grid_size: float
    snap_to_grid: bool

    def to_operation(self) -> Operation:
        return Operation(
            "freeform.canvas.configure",
            {
                "diagram_id": self.diagram_id,
                "grid_size": self.grid_size,
                "snap_to_grid": self.snap_to_grid,
            },
        )


@dataclass(frozen=True, slots=True)
class RegisterManagedAsset:
    asset: ManagedAsset

    def to_operation(self) -> Operation:
        return Operation(
            "asset.register",
            {
                "byte_size": self.asset.byte_size,
                "height": self.asset.height,
                "id": self.asset.id,
                "media_type": self.asset.media_type,
                "original_name": self.asset.original_name,
                "relative_path": self.asset.relative_path,
                "sha256": self.asset.sha256,
                "width": self.asset.width,
            },
        )


@dataclass(frozen=True, slots=True)
class RemoveManagedAsset:
    asset_id: str

    def to_operation(self) -> Operation:
        return Operation("asset.remove", {"asset_id": self.asset_id})


@dataclass(frozen=True, slots=True)
class RegisterShapePack:
    shape_pack: ShapePackReference

    def to_operation(self) -> Operation:
        return Operation(
            "shape_pack.register",
            {
                "id": self.shape_pack.id,
                "manifest_path": self.shape_pack.manifest_path,
                "name": self.shape_pack.name,
                "sha256": self.shape_pack.sha256,
                "version": self.shape_pack.version,
            },
        )


@dataclass(frozen=True, slots=True)
class RemoveShapePack:
    shape_pack_id: str

    def to_operation(self) -> Operation:
        return Operation("shape_pack.remove", {"shape_pack_id": self.shape_pack_id})


def new_operation_id() -> str:
    return f"op_{uuid4().hex}"
