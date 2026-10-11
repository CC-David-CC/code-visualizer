"""Explicit deterministic projection of the current development format."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from typing import cast

from code_visualizer.application.drakon_program_adapter import promote_program_from_drakon
from code_visualizer.config import PRODUCT
from code_visualizer.domain.common import ExtensionField, JsonValue
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
    Parallel,
    Period,
    RealtimeProcess,
    Select,
    Sequence,
    Silhouette,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    Try,
    With,
)
from code_visualizer.domain.expression import expression_node_to_data
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    FreeformObject,
    ShapeObject,
)
from code_visualizer.domain.mindmap import MindMapDiagram, Topic
from code_visualizer.domain.program import (
    ProgramAction,
    ProgramAssignment,
    ProgramCall,
    ProgramCase,
    ProgramClass,
    ProgramContextItem,
    ProgramDeclaration,
    ProgramDelay,
    ProgramEntryPoint,
    ProgramExceptionHandler,
    ProgramExpression,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramIf,
    ProgramImport,
    ProgramInput,
    ProgramLoop,
    ProgramModel,
    ProgramModule,
    ProgramNote,
    ProgramOutput,
    ProgramParallel,
    ProgramParallelBranch,
    ProgramPeriod,
    ProgramRealtimeProcess,
    ProgramSelect,
    ProgramSequence,
    ProgramSilhouette,
    ProgramSilhouetteBranch,
    ProgramSimpleStatement,
    ProgramStartTimer,
    ProgramStatement,
    ProgramSynchronizer,
    ProgramTransfer,
    ProgramTry,
    ProgramTypeAlias,
    ProgramWith,
)
from code_visualizer.domain.program_signatures import FunctionSpec
from code_visualizer.domain.project import Project, ProjectDocument, PythonRuntimeSettings
from code_visualizer.domain.projection import ProjectionDefinition
from code_visualizer.persistence.canonical import (
    JsonArray,
    JsonObject,
    json_object_data,
    json_stream_chunks,
)
from code_visualizer.persistence.intentional import domain_workspace_stream
from code_visualizer.persistence.invocation import invocation_arguments_to_data


def _extensions_to_data(fields: tuple[ExtensionField, ...]) -> list[JsonValue]:
    return [
        {
            "namespace": field.namespace,
            "values": dict(field.values),
        }
        for field in fields
    ]


def drakon_atom_to_data(atom: DrakonAtom) -> dict[str, JsonValue]:
    if isinstance(atom, Action):
        return {"id": atom.id, "kind": "action", "source": atom.source}
    if isinstance(atom, Output):
        return {
            "destination": atom.destination,
            "end": atom.end,
            "expression": atom.expression,
            "id": atom.id,
            "kind": "output",
        }
    if isinstance(atom, Assignment):
        return {
            "annotation": atom.annotation,
            "id": atom.id,
            "kind": "assignment",
            "operator": atom.operator,
            "target": atom.target,
            "value": atom.value,
        }
    if isinstance(atom, If):
        return {
            "condition": atom.condition,
            "false_branch": _sequence_to_data(atom.false_branch),
            "id": atom.id,
            "kind": "if",
            "preferred_truth": atom.preferred_truth,
            "true_branch": _sequence_to_data(atom.true_branch),
        }
    if isinstance(atom, Transfer):
        return {
            "cause": atom.cause,
            "expression": atom.expression,
            "id": atom.id,
            "kind": "transfer",
            "transfer_kind": atom.transfer_kind.value,
        }
    if isinstance(atom, SimpleStatement):
        return {
            "id": atom.id,
            "kind": "simple_statement",
            "secondary": atom.secondary,
            "source": atom.source,
            "statement_kind": atom.statement_kind.value,
        }
    if isinstance(atom, Call):
        return {
            "arguments": atom.arguments,
            "awaited": atom.awaited,
            "expression": atom.expression,
            "id": atom.id,
            "kind": "call",
            "result_target": atom.result_target,
            "target_diagram_id": atom.target_diagram_id,
        }
    if isinstance(atom, Input):
        return {
            "annotation": atom.annotation,
            "converter": atom.converter,
            "id": atom.id,
            "kind": "input",
            "prompt": atom.prompt,
            "target": atom.target,
        }
    if isinstance(atom, Delay):
        return {
            "asynchronous": atom.asynchronous,
            "id": atom.id,
            "kind": "delay",
            "seconds": atom.seconds,
        }
    if isinstance(atom, StartTimer):
        return {"id": atom.id, "kind": "start_timer", "timer": atom.timer}
    if isinstance(atom, Period):
        return {
            "asynchronous": atom.asynchronous,
            "id": atom.id,
            "kind": "period",
            "seconds": atom.seconds,
            "timer": atom.timer,
        }
    if isinstance(atom, RealtimeProcess):
        return {
            "awaited": atom.awaited,
            "call": atom.call,
            "id": atom.id,
            "kind": "realtime_process",
        }
    if isinstance(atom, Note):
        return {
            "id": atom.id,
            "kind": "note",
            "placement": atom.placement.value,
            "text": atom.text,
        }
    if isinstance(atom, Select):
        return {
            "cases": [
                {
                    "body": _sequence_to_data(case.body),
                    "condition": case.condition,
                    "guard": case.guard,
                    "id": case.id,
                    "is_default": case.is_default,
                    "label": case.label,
                    "pattern": case.pattern,
                }
                for case in atom.cases
            ],
            "expression": atom.expression,
            "id": atom.id,
            "kind": "select",
            "mode": atom.mode.value,
            "preferred_case_id": atom.preferred_case_id,
        }
    if isinstance(atom, Loop):
        return {
            "body": _sequence_to_data(atom.body),
            "children": atom.children,
            "condition": atom.condition,
            "delay_seconds": atom.delay_seconds,
            "else_body": _sequence_to_data(atom.else_body),
            "id": atom.id,
            "iterable": atom.iterable,
            "kind": "loop",
            "loop_kind": atom.loop_kind.value,
            "target": atom.target,
        }
    if isinstance(atom, With):
        return {
            "asynchronous": atom.asynchronous,
            "body": _sequence_to_data(atom.body),
            "contexts": [
                {"expression": item.expression, "id": item.id, "target": item.target}
                for item in atom.contexts
            ],
            "id": atom.id,
            "kind": "with",
        }
    if isinstance(atom, Try):
        return {
            "body": _sequence_to_data(atom.body),
            "else_body": _sequence_to_data(atom.else_body),
            "except_star": atom.except_star,
            "finally_body": _sequence_to_data(atom.finally_body),
            "handlers": [
                {
                    "body": _sequence_to_data(handler.body),
                    "exception": handler.exception,
                    "id": handler.id,
                    "name": handler.name,
                }
                for handler in atom.handlers
            ],
            "id": atom.id,
            "kind": "try",
        }
    if isinstance(atom, Synchronizer):
        return {
            "deadline": atom.deadline,
            "id": atom.id,
            "kind": "synchronizer",
            "on_time": _sequence_to_data(atom.on_time),
            "on_timeout": _sequence_to_data(atom.on_timeout),
            "preferred_on_time": atom.preferred_on_time,
            "timer": atom.timer,
        }
    if isinstance(atom, Parallel):
        return {
            "branches": [
                {"body": _sequence_to_data(branch.body), "id": branch.id, "name": branch.name}
                for branch in atom.branches
            ],
            "id": atom.id,
            "kind": "parallel",
            "mode": atom.mode.value,
        }
    if isinstance(atom, Silhouette):
        return {
            "branches": [
                {
                    "body": _sequence_to_data(branch.body),
                    "id": branch.id,
                    "name": branch.name,
                    "target_branch_id": branch.target_branch_id,
                }
                for branch in atom.branches
            ],
            "display_name": atom.display_name,
            "id": atom.id,
            "identifier": atom.identifier,
            "initial_branch_id": atom.initial_branch_id,
            "kind": "silhouette",
        }
    raise TypeError(f"Unsupported DRAKON atom: {type(atom).__name__}")


def _sequence_to_data(sequence: Sequence) -> dict[str, JsonValue]:
    return {
        "atoms": [drakon_atom_to_data(atom) for atom in sequence.atoms],
        "id": sequence.id,
    }


def function_spec_to_data(function: FunctionSpec) -> dict[str, JsonValue]:
    return {
        "decorators": list(function.decorators),
        "display_name": function.display_name,
        "docstring": function.docstring,
        "identifier": function.identifier,
        "kind": function.kind.value,
        "method_kind": function.method_kind.value if function.method_kind else None,
        "module": function.module,
        "owning_class": function.owning_class,
        "parameters": [
            {
                "annotation": parameter.annotation,
                "default": parameter.default,
                "kind": parameter.kind.value,
                "name": parameter.name,
            }
            for parameter in function.parameters
        ],
        "return_annotation": function.return_annotation,
    }


def _drakon_to_data(diagram: DrakonDiagram) -> dict[str, JsonValue]:
    return {
        "body": _sequence_to_data(diagram.body),
        "description": diagram.description,
        "end": {"id": diagram.end.id},
        "extensions": _extensions_to_data(diagram.extensions),
        "function": function_spec_to_data(diagram.header.function),
        "header": {"id": diagram.header.id},
        "id": diagram.id,
        "kind": diagram.kind.value,
        "title": diagram.title,
    }


def _topic_to_data(topic: Topic) -> dict[str, JsonValue]:
    return {
        "children": [_topic_to_data(child) for child in topic.children],
        "collapsed": topic.collapsed,
        "id": topic.id,
        "notes": topic.notes,
        "text": topic.text,
        "links": list(topic.links),
        "attachments": list(topic.attachments),
        "semantic_id": topic.semantic_id,
        "label_override": topic.label_override,
    }


def topic_to_data(topic: Topic) -> dict[str, JsonValue]:
    """Return the stable representation of one complete topic subtree."""

    return _topic_to_data(topic)


def _mind_map_to_data(diagram: MindMapDiagram) -> dict[str, JsonValue]:
    return {
        "cross_links": [
            {
                "id": link.id,
                "label": link.label,
                "source_topic_id": link.source_topic_id,
                "target_topic_id": link.target_topic_id,
                "semantic_relation_id": link.semantic_relation_id,
                "label_override": link.label_override,
            }
            for link in diagram.cross_links
        ],
        "extensions": _extensions_to_data(diagram.extensions),
        "id": diagram.id,
        "kind": diagram.kind.value,
        "layout": diagram.layout,
        "root": _topic_to_data(diagram.root),
        "title": diagram.title,
        "live_projection": (
            projection_definition_to_data(diagram.live_projection)
            if diagram.live_projection is not None
            else None
        ),
    }


def _freeform_object_to_data(item: FreeformObject) -> dict[str, JsonValue]:
    if isinstance(item, ShapeObject):
        return {
            "bounds": {
                "height": item.bounds.height,
                "width": item.bounds.width,
                "x": item.bounds.x,
                "y": item.bounds.y,
            },
            "hidden": item.hidden,
            "id": item.id,
            "kind": "shape",
            "locked": item.locked,
            "shape": item.shape.value,
            "text": item.text,
            "z_index": item.z_index,
            "rotation": item.rotation,
            "layer_id": item.layer_id,
            "group_id": item.group_id,
            "asset_id": item.asset_id,
            "points": [{"x": point.x, "y": point.y} for point in item.points],
            "fill": item.fill,
            "stroke": item.stroke,
            "semantic_id": item.semantic_id,
            "label_override": item.label_override,
        }
    if isinstance(item, ConnectorObject):
        return {
            "id": item.id,
            "kind": "connector",
            "label": item.label,
            "orthogonal": item.orthogonal,
            "points": [{"x": point.x, "y": point.y} for point in item.points],
            "source_id": item.source_id,
            "target_id": item.target_id,
            "arrow_start": item.arrow_start,
            "arrow_end": item.arrow_end,
            "layer_id": item.layer_id,
            "locked": item.locked,
            "semantic_relation_id": item.semantic_relation_id,
            "label_override": item.label_override,
        }
    raise TypeError(f"Unsupported free-form object: {type(item).__name__}")


def freeform_object_to_data(item: FreeformObject) -> dict[str, JsonValue]:
    """Return the stable representation of one free-form object."""

    return _freeform_object_to_data(item)


def _freeform_to_data(diagram: FreeformDiagram) -> dict[str, JsonValue]:
    return {
        "extensions": _extensions_to_data(diagram.extensions),
        "id": diagram.id,
        "kind": diagram.kind.value,
        "objects": [_freeform_object_to_data(item) for item in diagram.objects],
        "layers": [
            {
                "hidden": layer.hidden,
                "id": layer.id,
                "locked": layer.locked,
                "name": layer.name,
            }
            for layer in diagram.layers
        ],
        "guides": [
            {
                "id": guide.id,
                "orientation": guide.orientation.value,
                "position": guide.position,
            }
            for guide in diagram.guides
        ],
        "grid_size": diagram.grid_size,
        "snap_to_grid": diagram.snap_to_grid,
        "title": diagram.title,
        "live_projection": (
            projection_definition_to_data(diagram.live_projection)
            if diagram.live_projection is not None
            else None
        ),
    }


def document_to_data(document: ProjectDocument) -> dict[str, JsonValue]:
    if isinstance(document, DrakonDiagram):
        return _drakon_to_data(document)
    if isinstance(document, MindMapDiagram):
        return _mind_map_to_data(document)
    if isinstance(document, FreeformDiagram):
        return _freeform_to_data(document)
    raise TypeError(f"Unsupported project document: {type(document).__name__}")


def runtime_settings_to_data(settings: PythonRuntimeSettings) -> dict[str, JsonValue]:
    return {
        "active_run_profile": settings.active_run_profile,
        "run_profiles": [
            {
                "arguments": profile.arguments,
                "environment": [
                    {"name": variable.name, "value": variable.value}
                    for variable in profile.environment
                ],
                "interpreter": profile.interpreter,
                "name": profile.name,
                "working_directory": profile.working_directory,
            }
            for profile in settings.run_profiles
        ],
    }


def projection_definition_to_data(
    definition: ProjectionDefinition,
) -> dict[str, JsonValue]:
    return {
        "decorations": [item.value for item in definition.decorations],
        "direction": definition.direction.value,
        "grouping": definition.grouping.value,
        "id": definition.id,
        "include_scope": definition.include_scope,
        "include_isolated": definition.include_isolated,
        "label_style": definition.label_style.value,
        "layout": definition.layout.value,
        "max_depth": definition.max_depth,
        "object_kinds": [item.value for item in definition.object_kinds],
        "relation_kinds": [item.value for item in definition.relation_kinds],
        "scope_id": definition.scope_id,
        "title": definition.title,
        "node_limit": definition.node_limit,
        "expanded_ids": list(definition.expanded_ids),
        "focus_ids": list(definition.focus_ids),
    }


def _program_expression_to_data(value: ProgramExpression | None) -> JsonValue:
    if value is None:
        return None
    return {
        "id": value.id,
        "role": value.role.value,
        "tree": cast(JsonValue, expression_node_to_data(value.tree)),
    }


def program_expression_to_data(value: ProgramExpression) -> dict[str, JsonValue]:
    """Serialize one canonical expression for command/event payloads."""

    result = _program_expression_to_data(value)
    assert isinstance(result, dict)
    return result


def _program_sequence_stream(value: ProgramSequence) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "statements": JsonArray(_program_statement_stream(item) for item in value.statements),
        }
    )


def _program_statement_stream(statement: ProgramStatement) -> JsonObject:
    if isinstance(statement, ProgramAssignment):
        return JsonObject(
            {
                "annotation": _program_expression_to_data(statement.annotation),
                "id": statement.id,
                "kind": "assignment",
                "operator": statement.operator,
                "target": _program_expression_to_data(statement.target),
                "value": _program_expression_to_data(statement.value),
                "written_symbol_ids": JsonArray(statement.written_symbol_ids),
            }
        )
    elif isinstance(statement, ProgramOutput):
        return JsonObject(
            {
                "destination": _program_expression_to_data(statement.destination),
                "end": _program_expression_to_data(statement.end),
                "expression": _program_expression_to_data(statement.expression),
                "id": statement.id,
                "kind": "output",
            }
        )
    elif isinstance(statement, ProgramCall):
        return JsonObject(
            {
                "arguments": _program_expression_to_data(statement.arguments),
                "awaited": statement.awaited,
                "expression": _program_expression_to_data(statement.expression),
                "id": statement.id,
                "kind": "call",
                "result_target": _program_expression_to_data(statement.result_target),
                "target_function_id": statement.target_function_id,
                "written_symbol_ids": JsonArray(statement.written_symbol_ids),
            }
        )
    elif isinstance(statement, ProgramIf):
        return JsonObject(
            {
                "condition": _program_expression_to_data(statement.condition),
                "false_branch": _program_sequence_stream(statement.false_branch),
                "id": statement.id,
                "kind": "if",
                "preferred_truth": statement.preferred_truth,
                "true_branch": _program_sequence_stream(statement.true_branch),
            }
        )
    elif isinstance(statement, ProgramAction):
        return _program_action_stream(statement)
    elif isinstance(statement, ProgramTransfer):
        return _program_transfer_stream(statement)
    elif isinstance(statement, ProgramSimpleStatement):
        return _program_simple_statement_stream(statement)
    elif isinstance(statement, ProgramInput):
        return _program_input_stream(statement)
    elif isinstance(statement, ProgramDelay):
        return _program_delay_stream(statement)
    elif isinstance(statement, ProgramStartTimer):
        return _program_start_timer_stream(statement)
    elif isinstance(statement, ProgramPeriod):
        return _program_period_stream(statement)
    elif isinstance(statement, ProgramRealtimeProcess):
        return _program_realtime_process_stream(statement)
    elif isinstance(statement, ProgramNote):
        return _program_note_stream(statement)
    elif isinstance(statement, ProgramSelect):
        return _program_select_stream(statement)
    elif isinstance(statement, ProgramLoop):
        return _program_loop_stream(statement)
    elif isinstance(statement, ProgramWith):
        return _program_with_stream(statement)
    elif isinstance(statement, ProgramTry):
        return _program_try_stream(statement)
    elif isinstance(statement, ProgramSynchronizer):
        return _program_synchronizer_stream(statement)
    elif isinstance(statement, ProgramParallel):
        return _program_parallel_stream(statement)
    elif isinstance(statement, ProgramSilhouette):
        return _program_silhouette_stream(statement)
    else:
        raise TypeError(f"Unsupported program statement: {type(statement).__name__}")


def _program_action_stream(value: ProgramAction) -> JsonObject:
    return JsonObject(
        {"id": value.id, "kind": "action", "source": _program_expression_to_data(value.source)}
    )


def _program_transfer_stream(value: ProgramTransfer) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "transfer",
            "transfer_kind": value.transfer_kind.value,
            "expression": _program_expression_to_data(value.expression),
            "cause": _program_expression_to_data(value.cause),
        }
    )


def _program_simple_statement_stream(value: ProgramSimpleStatement) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "simple_statement",
            "statement_kind": value.statement_kind.value,
            "source": _program_expression_to_data(value.source),
            "secondary": _program_expression_to_data(value.secondary),
        }
    )


def _program_input_stream(value: ProgramInput) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "input",
            "target": _program_expression_to_data(value.target),
            "prompt": _program_expression_to_data(value.prompt),
            "converter": _program_expression_to_data(value.converter),
            "annotation": _program_expression_to_data(value.annotation),
        }
    )


def _program_delay_stream(value: ProgramDelay) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "delay",
            "seconds": _program_expression_to_data(value.seconds),
            "asynchronous": value.asynchronous,
        }
    )


def _program_start_timer_stream(value: ProgramStartTimer) -> JsonObject:
    return JsonObject({"id": value.id, "kind": "start_timer", "timer": value.timer})


def _program_period_stream(value: ProgramPeriod) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "period",
            "timer": value.timer,
            "seconds": _program_expression_to_data(value.seconds),
            "asynchronous": value.asynchronous,
        }
    )


def _program_realtime_process_stream(value: ProgramRealtimeProcess) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "realtime_process",
            "call": _program_expression_to_data(value.call),
            "awaited": value.awaited,
        }
    )


def _program_note_stream(value: ProgramNote) -> JsonObject:
    return JsonObject(
        {"id": value.id, "kind": "note", "text": value.text, "placement": value.placement.value}
    )


def _program_case_stream(value: ProgramCase) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "label": value.label,
            "body": _program_sequence_stream(value.body),
            "condition": _program_expression_to_data(value.condition),
            "pattern": _program_expression_to_data(value.pattern),
            "guard": _program_expression_to_data(value.guard),
            "is_default": value.is_default,
        }
    )


def _program_select_stream(value: ProgramSelect) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "select",
            "expression": _program_expression_to_data(value.expression),
            "cases": JsonArray(_program_case_stream(item) for item in value.cases),
            "mode": value.mode.value,
            "preferred_case_id": value.preferred_case_id,
        }
    )


def _program_loop_stream(value: ProgramLoop) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "loop",
            "loop_kind": value.loop_kind.value,
            "body": _program_sequence_stream(value.body),
            "else_body": _program_sequence_stream(value.else_body),
            "condition": _program_expression_to_data(value.condition),
            "target": _program_expression_to_data(value.target),
            "iterable": _program_expression_to_data(value.iterable),
            "children": _program_expression_to_data(value.children),
            "delay_seconds": _program_expression_to_data(value.delay_seconds),
        }
    )


def _program_context_item_stream(value: ProgramContextItem) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "expression": _program_expression_to_data(value.expression),
            "target": _program_expression_to_data(value.target),
        }
    )


def _program_with_stream(value: ProgramWith) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "with",
            "contexts": JsonArray(_program_context_item_stream(item) for item in value.contexts),
            "body": _program_sequence_stream(value.body),
            "asynchronous": value.asynchronous,
        }
    )


def _program_exception_handler_stream(value: ProgramExceptionHandler) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "exception": _program_expression_to_data(value.exception),
            "name": _program_expression_to_data(value.name),
            "body": _program_sequence_stream(value.body),
        }
    )


def _program_try_stream(value: ProgramTry) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "try",
            "body": _program_sequence_stream(value.body),
            "handlers": JsonArray(
                _program_exception_handler_stream(item) for item in value.handlers
            ),
            "else_body": _program_sequence_stream(value.else_body),
            "finally_body": _program_sequence_stream(value.finally_body),
            "except_star": value.except_star,
        }
    )


def _program_synchronizer_stream(value: ProgramSynchronizer) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "synchronizer",
            "timer": value.timer,
            "deadline": _program_expression_to_data(value.deadline),
            "on_time": _program_sequence_stream(value.on_time),
            "on_timeout": _program_sequence_stream(value.on_timeout),
            "preferred_on_time": value.preferred_on_time,
        }
    )


def _program_parallel_branch_stream(value: ProgramParallelBranch) -> JsonObject:
    return JsonObject(
        {"id": value.id, "name": value.name, "body": _program_sequence_stream(value.body)}
    )


def _program_parallel_stream(value: ProgramParallel) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "parallel",
            "branches": JsonArray(_program_parallel_branch_stream(item) for item in value.branches),
            "mode": value.mode.value,
        }
    )


def _program_silhouette_branch_stream(value: ProgramSilhouetteBranch) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "name": value.name,
            "body": _program_sequence_stream(value.body),
            "target_branch_id": value.target_branch_id,
        }
    )


def _program_silhouette_stream(value: ProgramSilhouette) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": "silhouette",
            "display_name": value.display_name,
            "identifier": value.identifier,
            "branches": JsonArray(
                _program_silhouette_branch_stream(item) for item in value.branches
            ),
            "initial_branch_id": value.initial_branch_id,
        }
    )


def program_sequence_to_data(value: ProgramSequence) -> dict[str, JsonValue]:
    return json_object_data(_program_sequence_stream(value))


def program_statement_to_data(value: ProgramStatement) -> dict[str, JsonValue]:
    return json_object_data(_program_statement_stream(value))


def _program_function_stream(value: ProgramFunction) -> JsonObject:
    return JsonObject(
        {
            "body": _program_sequence_stream(value.body),
            "decorators": JsonArray(_program_expression_to_data(item) for item in value.decorators),
            "display_name": value.display_name,
            "docstring": value.docstring,
            "id": value.id,
            "identifier": value.identifier,
            "kind": value.kind.value,
            "method_kind": value.method_kind.value if value.method_kind is not None else None,
            "type_parameters": JsonArray(
                cast(JsonValue, expression_node_to_data(item)) for item in value.type_parameters
            ),
            "parameters": JsonArray(
                JsonObject(
                    {
                        "annotation": _program_expression_to_data(item.annotation),
                        "default": _program_expression_to_data(item.default),
                        "id": item.id,
                        "kind": item.kind.value,
                        "name": item.name,
                        "symbol_id": item.symbol_id,
                    }
                )
                for item in value.parameters
            ),
            "return_annotation": _program_expression_to_data(value.return_annotation),
            "symbol_id": value.symbol_id,
        }
    )


def program_function_to_data(value: ProgramFunction) -> dict[str, JsonValue]:
    return json_object_data(_program_function_stream(value))


def program_declaration_stream(value: ProgramDeclaration) -> JsonObject:
    if isinstance(value, ProgramFunctionReference):
        return JsonObject({"kind": "function_reference", "function_id": value.function_id})
    if isinstance(value, ProgramClass):
        return program_class_stream(value)
    if isinstance(value, (ProgramImport, ProgramTypeAlias)):
        return JsonObject(
            {
                "kind": "import" if isinstance(value, ProgramImport) else "type_alias",
                "id": value.id,
                "source": _program_expression_to_data(value.source),
            }
        )
    return _program_statement_stream(value)


def program_declaration_to_data(value: ProgramDeclaration) -> dict[str, JsonValue]:
    return json_object_data(program_declaration_stream(value))


def program_class_stream(value: ProgramClass) -> JsonObject:
    return JsonObject(
        {
            "kind": "class",
            "id": value.id,
            "identifier": value.identifier,
            "body": JsonArray(program_declaration_stream(item) for item in value.body),
            "arguments": _program_expression_to_data(value.arguments),
            "decorators": JsonArray(_program_expression_to_data(item) for item in value.decorators),
            "docstring": value.docstring,
            "type_parameters": JsonArray(
                cast(JsonValue, expression_node_to_data(item)) for item in value.type_parameters
            ),
        }
    )


def program_class_to_data(value: ProgramClass) -> dict[str, JsonValue]:
    return json_object_data(program_class_stream(value))


def program_module_stream(value: ProgramModule) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "kind": value.kind.value,
            "path": value.path,
            "docstring": value.docstring,
            "body": JsonArray(program_declaration_stream(item) for item in value.body),
        }
    )


def program_module_to_data(value: ProgramModule) -> dict[str, JsonValue]:
    return json_object_data(program_module_stream(value))


def program_entrypoint_stream(value: ProgramEntryPoint) -> JsonObject:
    return JsonObject(
        {
            "id": value.id,
            "callable_id": value.callable_id,
            "arguments": invocation_arguments_to_data(value.arguments),
            "startup": JsonArray(program_declaration_stream(item) for item in value.startup),
        }
    )


def program_entrypoint_to_data(value: ProgramEntryPoint) -> dict[str, JsonValue]:
    return json_object_data(program_entrypoint_stream(value))


def program_model_stream(value: ProgramModel) -> JsonObject:
    return JsonObject(
        {
            "functions": JsonArray(_program_function_stream(item) for item in value.functions),
            "modules": JsonArray(program_module_stream(item) for item in value.modules),
            "package": value.package,
            "entrypoint": program_entrypoint_stream(value.entrypoint)
            if value.entrypoint is not None
            else None,
            "symbols": JsonArray(
                JsonObject(
                    {
                        "declaration_id": item.declaration_id,
                        "id": item.id,
                        "kind": item.kind.value,
                        "name": item.name,
                        "owner_id": item.owner_id,
                    }
                )
                for item in value.symbols
            ),
        }
    )


def program_model_to_data(value: ProgramModel) -> dict[str, JsonValue]:
    return json_object_data(program_model_stream(value))


def _project_document_to_data(document: ProjectDocument) -> dict[str, JsonValue]:
    if isinstance(document, DrakonDiagram):
        return {
            "id": document.id,
            "kind": document.kind.value,
            "title": document.title,
            "description": document.description,
            "extensions": _extensions_to_data(document.extensions),
        }
    return document_to_data(document)


def project_stream(project: Project) -> JsonObject:
    if not project.program_model.functions and (not project.program_model.modules):
        diagrams = tuple(item for item in project.documents if isinstance(item, DrakonDiagram))
        if diagrams:
            promoted = promote_program_from_drakon(
                diagrams, project.program_model, project.drakon_views, deterministic=True
            )
            project = replace(
                project, program_model=promoted.model, drakon_views=promoted.drakon_views
            )
    return JsonObject(
        {
            "concepts": JsonArray(
                JsonObject(
                    {
                        "description": concept.description,
                        "id": concept.id,
                        "member_ids": JsonArray(concept.member_ids),
                        "tags": JsonArray(concept.tags),
                        "title": concept.title,
                    }
                )
                for concept in project.concepts
            ),
            "description": project.description,
            "domain_workspace": domain_workspace_stream(project.domain_workspace),
            "documents": JsonArray(
                _project_document_to_data(document) for document in project.documents
            ),
            "drakon_views": JsonArray(
                JsonObject(
                    {
                        "document_id": item.document_id,
                        "end_id": item.end_id,
                        "function_id": item.function_id,
                        "header_id": item.header_id,
                        "title": item.title,
                    }
                )
                for item in project.drakon_views
            ),
            "extensions": _extensions_to_data(project.extensions),
            "runtime_settings": runtime_settings_to_data(project.runtime_settings),
            "managed_assets": JsonArray(
                JsonObject(
                    {
                        "byte_size": asset.byte_size,
                        "id": asset.id,
                        "height": asset.height,
                        "media_type": asset.media_type,
                        "original_name": asset.original_name,
                        "relative_path": asset.relative_path,
                        "sha256": asset.sha256,
                        "width": asset.width,
                    }
                )
                for asset in project.managed_assets
            ),
            "shape_packs": JsonArray(
                JsonObject(
                    {
                        "id": pack.id,
                        "manifest_path": pack.manifest_path,
                        "name": pack.name,
                        "sha256": pack.sha256,
                        "version": pack.version,
                    }
                )
                for pack in project.shape_packs
            ),
            "project_id": project.id,
            "program_model": program_model_stream(project.program_model),
            "projection_definitions": JsonArray(
                projection_definition_to_data(definition)
                for definition in project.projection_definitions
            ),
            "revision": project.revision,
            "format_revision": PRODUCT.project_format_revision,
            "semantic_relations": JsonArray(
                JsonObject(
                    {
                        "description": relation.description,
                        "id": relation.id,
                        "kind": relation.kind.value,
                        "label": relation.label,
                        "source_id": relation.source_id,
                        "target_id": relation.target_id,
                    }
                )
                for relation in project.semantic_relations
            ),
            "title": project.title,
        }
    )


def project_to_data(project: Project) -> dict[str, JsonValue]:
    return json_object_data(project_stream(project))


def project_data_chunks(project: Project) -> Iterator[bytes]:
    return json_stream_chunks(project_stream(project))


def normalized_project_json(project: Project) -> str:
    data = cast(JsonValue, project_to_data(project))
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
