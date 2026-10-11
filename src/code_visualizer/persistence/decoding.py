"""Strict, non-executing decoder for the current development format."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.application.drakon_program_adapter import (
    drakon_from_program,
    promote_program_from_drakon,
)
from code_visualizer.config import PRODUCT
from code_visualizer.domain.assets import ManagedAsset, ShapePackReference
from code_visualizer.domain.authoring import (
    AuthoredRelationKind,
    AuthoredSemanticRelation,
    SemanticConcept,
)
from code_visualizer.domain.common import DocumentKind, ExtensionField, JsonValue
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Case,
    ContextItem,
    Delay,
    DrakonAtom,
    DrakonDiagram,
    End,
    ExceptionHandler,
    Header,
    If,
    Input,
    Loop,
    Note,
    Output,
    Parallel,
    ParallelBranch,
    Period,
    RealtimeProcess,
    Select,
    Sequence,
    Silhouette,
    SilhouetteBranch,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    Try,
    With,
)
from code_visualizer.domain.expression import (
    ExpressionNode,
    expression_node_from_data,
    render_expression_tree,
)
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    FreeformObject,
    Guide,
    GuideOrientation,
    Layer,
    Point,
    Rect,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.domain.invocation_arguments import (
    ConfiguredArguments,
    configured_arguments_from_text,
)
from code_visualizer.domain.mindmap import CrossLink, MindMapDiagram, Topic
from code_visualizer.domain.module_paths import canonical_module_path, canonical_package_path
from code_visualizer.domain.program import (
    ExpressionRole,
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
    ProgramParameter,
    ProgramPeriod,
    ProgramRealtimeProcess,
    ProgramSelect,
    ProgramSequence,
    ProgramSilhouette,
    ProgramSilhouetteBranch,
    ProgramSimpleStatement,
    ProgramStartTimer,
    ProgramStatement,
    ProgramSymbol,
    ProgramSymbolKind,
    ProgramSynchronizer,
    ProgramTransfer,
    ProgramTry,
    ProgramTypeAlias,
    ProgramWith,
    program_statements,
)
from code_visualizer.domain.program_index import ProgramFunctionLocation, program_function_locations
from code_visualizer.domain.program_kinds import (
    CallableKind,
    LoopKind,
    MethodKind,
    NotePlacement,
    ParallelMode,
    ParameterKind,
    ProgramModuleKind,
    SelectMode,
    SimpleKind,
    TransferKind,
)
from code_visualizer.domain.program_signatures import FunctionSpec, ParameterSpec
from code_visualizer.domain.project import (
    EnvironmentVariable,
    Project,
    ProjectDocument,
    PythonRuntimeSettings,
    RunProfile,
)
from code_visualizer.domain.projection import (
    DrakonViewDefinition,
    ProjectionDecoration,
    ProjectionDefinition,
    ProjectionGrouping,
    ProjectionLabelStyle,
    ProjectionLayout,
    TraversalDirection,
)
from code_visualizer.domain.semantic import SemanticObjectKind, SemanticRelationKind
from code_visualizer.persistence.intentional import DomainDecodeError, domain_workspace_from_data
from code_visualizer.persistence.invocation import (
    invocation_arguments_from_data,
    invocation_arguments_to_data,
)
from code_visualizer.validation import Severity, validate_integrity


@dataclass(frozen=True, slots=True)
class ProjectDecodeError(ValueError):
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.message}"


def _fail(code: str, path: str, message: str) -> ProjectDecodeError:
    return ProjectDecodeError(code, path, message)


def _object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise _fail("FORMAT_EXPECTED_OBJECT", path, "expected an object")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise _fail("FORMAT_NON_STRING_KEY", path, "object keys must be strings")
        result[key] = item
    return result


def _array(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise _fail("FORMAT_EXPECTED_ARRAY", path, "expected an array")
    return list(value)


def _required(data: Mapping[str, object], key: str, path: str) -> object:
    if key not in data:
        raise _fail("FORMAT_MISSING_FIELD", f"{path}.{key}", "required field is missing")
    return data[key]


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise _fail("FORMAT_EXPECTED_STRING", path, "expected a string")
    return value


def _nonempty_string(value: object, path: str) -> str:
    result = _string(value, path)
    if not result.strip():
        raise _fail("FORMAT_EMPTY_STRING", path, "value must not be empty")
    return result


def _optional_string(value: object, path: str) -> str | None:
    if value is None:
        return None
    return _string(value, path)


def _enum[T: StrEnum](enum_type: type[T], value: object, path: str) -> T:
    try:
        return enum_type(_string(value, path))
    except ValueError as exc:
        raise _fail("FORMAT_INVALID_ENUM", path, str(exc)) from exc


def _boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise _fail("FORMAT_EXPECTED_BOOLEAN", path, "expected a Boolean")
    return value


def _integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail("FORMAT_EXPECTED_INTEGER", path, "expected an integer")
    return value


def _number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail("FORMAT_EXPECTED_NUMBER", path, "expected a number")
    result = float(value)
    if not math.isfinite(result):
        raise _fail("FORMAT_NONFINITE_NUMBER", path, "number must be finite")
    return result


def _json_value(value: object, path: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _fail("FORMAT_NONFINITE_NUMBER", path, "number must be finite")
        return value
    if isinstance(value, list):
        return [_json_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        data = _object(value, path)
        return {key: _json_value(item, f"{path}.{key}") for key, item in data.items()}
    raise _fail("FORMAT_UNSUPPORTED_VALUE", path, "value is not valid JSON")


def _extensions(value: object, path: str) -> tuple[ExtensionField, ...]:
    result: list[ExtensionField] = []
    for index, raw in enumerate(_array(value, path)):
        item_path = f"{path}[{index}]"
        data = _object(raw, item_path)
        namespace = _nonempty_string(
            _required(data, "namespace", item_path), f"{item_path}.namespace"
        )
        values = _object(_required(data, "values", item_path), f"{item_path}.values")
        result.append(
            ExtensionField(
                namespace=namespace,
                values=tuple(
                    (key, _json_value(item, f"{item_path}.values.{key}"))
                    for key, item in sorted(values.items())
                ),
            )
        )
    return tuple(result)


def _parameter(value: object, path: str) -> ParameterSpec:
    data = _object(value, path)
    try:
        kind = ParameterKind(_string(_required(data, "kind", path), f"{path}.kind"))
    except ValueError as exc:
        raise _fail("FORMAT_UNKNOWN_PARAMETER_KIND", f"{path}.kind", str(exc)) from exc
    return ParameterSpec(
        name=_nonempty_string(_required(data, "name", path), f"{path}.name"),
        kind=kind,
        annotation=_optional_string(data.get("annotation"), f"{path}.annotation"),
        default=_optional_string(data.get("default"), f"{path}.default"),
    )


def _function(data: Mapping[str, object], path: str) -> FunctionSpec:
    try:
        kind = CallableKind(_string(_required(data, "kind", path), f"{path}.kind"))
    except ValueError as exc:
        raise _fail("FORMAT_UNKNOWN_CALLABLE_KIND", f"{path}.kind", str(exc)) from exc
    parameters = tuple(
        _parameter(item, f"{path}.parameters[{index}]")
        for index, item in enumerate(
            _array(_required(data, "parameters", path), f"{path}.parameters")
        )
    )
    decorators = tuple(
        _string(item, f"{path}.decorators[{index}]")
        for index, item in enumerate(
            _array(_required(data, "decorators", path), f"{path}.decorators")
        )
    )
    raw_method_kind = data.get("method_kind")
    method_kind: MethodKind | None = None
    if raw_method_kind is not None:
        try:
            method_kind = MethodKind(_string(raw_method_kind, f"{path}.method_kind"))
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_METHOD_KIND", f"{path}.method_kind", str(exc)) from exc
    return FunctionSpec(
        identifier=_nonempty_string(_required(data, "identifier", path), f"{path}.identifier"),
        display_name=_nonempty_string(
            _required(data, "display_name", path), f"{path}.display_name"
        ),
        kind=kind,
        parameters=parameters,
        return_annotation=_optional_string(
            data.get("return_annotation"), f"{path}.return_annotation"
        ),
        decorators=decorators,
        docstring=_optional_string(data.get("docstring"), f"{path}.docstring"),
        module=canonical_module_path(_string(_required(data, "module", path), f"{path}.module")),
        owning_class=_optional_string(data.get("owning_class"), f"{path}.owning_class"),
        method_kind=method_kind,
    )


def function_spec_from_data(value: object, path: str = "$.function") -> FunctionSpec:
    return _function(_object(value, path), path)


def drakon_atom_from_data(value: object, path: str = "$.atom") -> DrakonAtom:
    data = _object(value, path)
    kind = _string(_required(data, "kind", path), f"{path}.kind")
    atom_id = _nonempty_string(_required(data, "id", path), f"{path}.id")
    if kind == "action":
        return Action(
            id=atom_id,
            source=_string(_required(data, "source", path), f"{path}.source"),
        )
    if kind == "output":
        return Output(
            id=atom_id,
            expression=_string(_required(data, "expression", path), f"{path}.expression"),
            destination=_optional_string(data.get("destination"), f"{path}.destination"),
            end=_optional_string(data.get("end"), f"{path}.end"),
        )
    if kind == "assignment":
        return Assignment(
            id=atom_id,
            target=_string(_required(data, "target", path), f"{path}.target"),
            value=_string(_required(data, "value", path), f"{path}.value"),
            annotation=_optional_string(data.get("annotation"), f"{path}.annotation"),
            operator=_string(_required(data, "operator", path), f"{path}.operator"),
        )
    if kind == "if":
        return If(
            id=atom_id,
            condition=_string(_required(data, "condition", path), f"{path}.condition"),
            true_branch=_sequence(_required(data, "true_branch", path), f"{path}.true_branch"),
            false_branch=_sequence(_required(data, "false_branch", path), f"{path}.false_branch"),
            preferred_truth=_boolean(
                _required(data, "preferred_truth", path), f"{path}.preferred_truth"
            ),
        )
    if kind == "transfer":
        try:
            transfer_kind = TransferKind(
                _string(_required(data, "transfer_kind", path), f"{path}.transfer_kind")
            )
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_TRANSFER_KIND", f"{path}.transfer_kind", str(exc)) from exc
        return Transfer(
            id=atom_id,
            transfer_kind=transfer_kind,
            expression=_string(data.get("expression", "None"), f"{path}.expression"),
            cause=_optional_string(data.get("cause"), f"{path}.cause"),
        )
    if kind == "simple_statement":
        try:
            statement_kind = SimpleKind(
                _string(_required(data, "statement_kind", path), f"{path}.statement_kind")
            )
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_SIMPLE_KIND", f"{path}.statement_kind", str(exc)) from exc
        return SimpleStatement(
            id=atom_id,
            statement_kind=statement_kind,
            source=_string(_required(data, "source", path), f"{path}.source"),
            secondary=_optional_string(data.get("secondary"), f"{path}.secondary"),
        )
    if kind == "call":
        return Call(
            id=atom_id,
            expression=_string(_required(data, "expression", path), f"{path}.expression"),
            awaited=_boolean(data.get("awaited", False), f"{path}.awaited"),
            result_target=_optional_string(data.get("result_target"), f"{path}.result_target"),
            target_diagram_id=_optional_string(
                data.get("target_diagram_id"), f"{path}.target_diagram_id"
            ),
            arguments=_string(data.get("arguments", ""), f"{path}.arguments"),
        )
    if kind == "input":
        return Input(
            id=atom_id,
            target=_string(_required(data, "target", path), f"{path}.target"),
            prompt=_string(_required(data, "prompt", path), f"{path}.prompt"),
            converter=_optional_string(data.get("converter"), f"{path}.converter"),
            annotation=_optional_string(data.get("annotation"), f"{path}.annotation"),
        )
    if kind == "delay":
        return Delay(
            id=atom_id,
            seconds=_string(_required(data, "seconds", path), f"{path}.seconds"),
            asynchronous=_boolean(data.get("asynchronous", False), f"{path}.asynchronous"),
        )
    if kind == "start_timer":
        return StartTimer(
            id=atom_id,
            timer=_nonempty_string(_required(data, "timer", path), f"{path}.timer"),
        )
    if kind == "period":
        return Period(
            id=atom_id,
            timer=_nonempty_string(_required(data, "timer", path), f"{path}.timer"),
            seconds=_string(_required(data, "seconds", path), f"{path}.seconds"),
            asynchronous=_boolean(data.get("asynchronous", False), f"{path}.asynchronous"),
        )
    if kind == "realtime_process":
        return RealtimeProcess(
            id=atom_id,
            call=_string(_required(data, "call", path), f"{path}.call"),
            awaited=_boolean(data.get("awaited", False), f"{path}.awaited"),
        )
    if kind == "note":
        try:
            placement = NotePlacement(
                _string(_required(data, "placement", path), f"{path}.placement")
            )
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_NOTE_PLACEMENT", f"{path}.placement", str(exc)) from exc
        return Note(
            id=atom_id,
            text=_string(_required(data, "text", path), f"{path}.text"),
            placement=placement,
        )
    if kind == "select":
        try:
            mode = SelectMode(_string(_required(data, "mode", path), f"{path}.mode"))
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_SELECT_MODE", f"{path}.mode", str(exc)) from exc
        cases: list[Case] = []
        for index, raw_case in enumerate(_array(_required(data, "cases", path), f"{path}.cases")):
            case_path = f"{path}.cases[{index}]"
            case = _object(raw_case, case_path)
            cases.append(
                Case(
                    id=_nonempty_string(_required(case, "id", case_path), f"{case_path}.id"),
                    label=_string(_required(case, "label", case_path), f"{case_path}.label"),
                    body=_sequence(_required(case, "body", case_path), f"{case_path}.body"),
                    condition=_string(
                        _required(case, "condition", case_path), f"{case_path}.condition"
                    ),
                    pattern=_string(_required(case, "pattern", case_path), f"{case_path}.pattern"),
                    guard=_optional_string(case.get("guard"), f"{case_path}.guard"),
                    is_default=_boolean(
                        _required(case, "is_default", case_path), f"{case_path}.is_default"
                    ),
                )
            )
        return Select(
            id=atom_id,
            expression=_string(_required(data, "expression", path), f"{path}.expression"),
            cases=tuple(cases),
            mode=mode,
            preferred_case_id=_optional_string(
                data.get("preferred_case_id"), f"{path}.preferred_case_id"
            ),
        )
    if kind == "loop":
        try:
            loop_kind = LoopKind(_string(_required(data, "loop_kind", path), f"{path}.loop_kind"))
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_LOOP_KIND", f"{path}.loop_kind", str(exc)) from exc
        return Loop(
            id=atom_id,
            loop_kind=loop_kind,
            body=_sequence(_required(data, "body", path), f"{path}.body"),
            else_body=_sequence(_required(data, "else_body", path), f"{path}.else_body"),
            condition=_string(_required(data, "condition", path), f"{path}.condition"),
            target=_string(_required(data, "target", path), f"{path}.target"),
            iterable=_string(_required(data, "iterable", path), f"{path}.iterable"),
            children=_string(_required(data, "children", path), f"{path}.children"),
            delay_seconds=_string(_required(data, "delay_seconds", path), f"{path}.delay_seconds"),
        )
    if kind == "with":
        contexts: list[ContextItem] = []
        for index, raw_context in enumerate(
            _array(_required(data, "contexts", path), f"{path}.contexts")
        ):
            context_path = f"{path}.contexts[{index}]"
            context = _object(raw_context, context_path)
            contexts.append(
                ContextItem(
                    id=_nonempty_string(
                        _required(context, "id", context_path), f"{context_path}.id"
                    ),
                    expression=_string(
                        _required(context, "expression", context_path),
                        f"{context_path}.expression",
                    ),
                    target=_optional_string(context.get("target"), f"{context_path}.target"),
                )
            )
        return With(
            id=atom_id,
            contexts=tuple(contexts),
            body=_sequence(_required(data, "body", path), f"{path}.body"),
            asynchronous=_boolean(data.get("asynchronous", False), f"{path}.asynchronous"),
        )
    if kind == "try":
        handlers: list[ExceptionHandler] = []
        for index, raw_handler in enumerate(
            _array(_required(data, "handlers", path), f"{path}.handlers")
        ):
            handler_path = f"{path}.handlers[{index}]"
            handler = _object(raw_handler, handler_path)
            handlers.append(
                ExceptionHandler(
                    id=_nonempty_string(
                        _required(handler, "id", handler_path), f"{handler_path}.id"
                    ),
                    exception=_string(
                        _required(handler, "exception", handler_path),
                        f"{handler_path}.exception",
                    ),
                    name=_optional_string(handler.get("name"), f"{handler_path}.name"),
                    body=_sequence(
                        _required(handler, "body", handler_path), f"{handler_path}.body"
                    ),
                )
            )
        return Try(
            id=atom_id,
            body=_sequence(_required(data, "body", path), f"{path}.body"),
            handlers=tuple(handlers),
            else_body=_sequence(_required(data, "else_body", path), f"{path}.else_body"),
            finally_body=_sequence(_required(data, "finally_body", path), f"{path}.finally_body"),
            except_star=_boolean(data.get("except_star", False), f"{path}.except_star"),
        )
    if kind == "synchronizer":
        return Synchronizer(
            id=atom_id,
            timer=_nonempty_string(_required(data, "timer", path), f"{path}.timer"),
            deadline=_string(_required(data, "deadline", path), f"{path}.deadline"),
            on_time=_sequence(_required(data, "on_time", path), f"{path}.on_time"),
            on_timeout=_sequence(_required(data, "on_timeout", path), f"{path}.on_timeout"),
            preferred_on_time=_boolean(
                data.get("preferred_on_time", True), f"{path}.preferred_on_time"
            ),
        )
    if kind == "parallel":
        try:
            parallel_mode = ParallelMode(_string(_required(data, "mode", path), f"{path}.mode"))
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_PARALLEL_MODE", f"{path}.mode", str(exc)) from exc
        parallel_branches: list[ParallelBranch] = []
        for index, raw_branch in enumerate(
            _array(_required(data, "branches", path), f"{path}.branches")
        ):
            branch_path = f"{path}.branches[{index}]"
            branch = _object(raw_branch, branch_path)
            parallel_branches.append(
                ParallelBranch(
                    id=_nonempty_string(_required(branch, "id", branch_path), f"{branch_path}.id"),
                    name=_string(_required(branch, "name", branch_path), f"{branch_path}.name"),
                    body=_sequence(_required(branch, "body", branch_path), f"{branch_path}.body"),
                )
            )
        return Parallel(id=atom_id, branches=tuple(parallel_branches), mode=parallel_mode)
    if kind == "silhouette":
        silhouette_branches: list[SilhouetteBranch] = []
        for index, raw_branch in enumerate(
            _array(_required(data, "branches", path), f"{path}.branches")
        ):
            branch_path = f"{path}.branches[{index}]"
            branch = _object(raw_branch, branch_path)
            silhouette_branches.append(
                SilhouetteBranch(
                    id=_nonempty_string(_required(branch, "id", branch_path), f"{branch_path}.id"),
                    name=_string(_required(branch, "name", branch_path), f"{branch_path}.name"),
                    body=_sequence(_required(branch, "body", branch_path), f"{branch_path}.body"),
                    target_branch_id=_optional_string(
                        branch.get("target_branch_id"), f"{branch_path}.target_branch_id"
                    ),
                )
            )
        return Silhouette(
            id=atom_id,
            display_name=_nonempty_string(
                _required(data, "display_name", path), f"{path}.display_name"
            ),
            identifier=_nonempty_string(_required(data, "identifier", path), f"{path}.identifier"),
            branches=tuple(silhouette_branches),
            initial_branch_id=_nonempty_string(
                _required(data, "initial_branch_id", path), f"{path}.initial_branch_id"
            ),
        )
    raise _fail("FORMAT_UNKNOWN_ATOM_KIND", f"{path}.kind", f"unknown atom kind {kind!r}")


def _sequence(value: object, path: str) -> Sequence:
    data = _object(value, path)
    return Sequence(
        id=_nonempty_string(_required(data, "id", path), f"{path}.id"),
        atoms=tuple(
            drakon_atom_from_data(item, f"{path}.atoms[{index}]")
            for index, item in enumerate(_array(_required(data, "atoms", path), f"{path}.atoms"))
        ),
    )


def _drakon(data: Mapping[str, object], path: str) -> DrakonDiagram:
    header = _object(_required(data, "header", path), f"{path}.header")
    body = _object(_required(data, "body", path), f"{path}.body")
    end = _object(_required(data, "end", path), f"{path}.end")
    return DrakonDiagram(
        id=_nonempty_string(_required(data, "id", path), f"{path}.id"),
        title=_nonempty_string(_required(data, "title", path), f"{path}.title"),
        header=Header(
            id=_nonempty_string(_required(header, "id", f"{path}.header"), f"{path}.header.id"),
            function=_function(
                _object(_required(data, "function", path), f"{path}.function"),
                f"{path}.function",
            ),
        ),
        body=_sequence(body, f"{path}.body"),
        end=End(id=_nonempty_string(_required(end, "id", f"{path}.end"), f"{path}.end.id")),
        description=_string(data.get("description", ""), f"{path}.description"),
        extensions=_extensions(data.get("extensions", []), f"{path}.extensions"),
    )


def _topic(value: object, path: str) -> Topic:
    data = _object(value, path)
    children = tuple(
        _topic(child, f"{path}.children[{index}]")
        for index, child in enumerate(_array(_required(data, "children", path), f"{path}.children"))
    )
    return Topic(
        id=_nonempty_string(_required(data, "id", path), f"{path}.id"),
        text=_string(_required(data, "text", path), f"{path}.text"),
        children=children,
        notes=_string(data.get("notes", ""), f"{path}.notes"),
        collapsed=_boolean(data.get("collapsed", False), f"{path}.collapsed"),
        links=tuple(
            _string(item, f"{path}.links[{index}]")
            for index, item in enumerate(_array(data.get("links", []), f"{path}.links"))
        ),
        attachments=tuple(
            _nonempty_string(item, f"{path}.attachments[{index}]")
            for index, item in enumerate(_array(data.get("attachments", []), f"{path}.attachments"))
        ),
        semantic_id=_optional_string(data.get("semantic_id"), f"{path}.semantic_id"),
        label_override=_optional_string(data.get("label_override"), f"{path}.label_override"),
    )


def topic_from_data(value: object, path: str = "$.topic") -> Topic:
    """Decode one bounded semantic clipboard topic subtree."""

    return _topic(value, path)


def _mind_map(data: Mapping[str, object], path: str) -> MindMapDiagram:
    links: list[CrossLink] = []
    for index, raw in enumerate(
        _array(_required(data, "cross_links", path), f"{path}.cross_links")
    ):
        item_path = f"{path}.cross_links[{index}]"
        item = _object(raw, item_path)
        links.append(
            CrossLink(
                id=_nonempty_string(_required(item, "id", item_path), f"{item_path}.id"),
                source_topic_id=_nonempty_string(
                    _required(item, "source_topic_id", item_path),
                    f"{item_path}.source_topic_id",
                ),
                target_topic_id=_nonempty_string(
                    _required(item, "target_topic_id", item_path),
                    f"{item_path}.target_topic_id",
                ),
                label=_string(item.get("label", ""), f"{item_path}.label"),
                semantic_relation_id=_optional_string(
                    item.get("semantic_relation_id"),
                    f"{item_path}.semantic_relation_id",
                ),
                label_override=_optional_string(
                    item.get("label_override"),
                    f"{item_path}.label_override",
                ),
            )
        )
    return MindMapDiagram(
        id=_nonempty_string(_required(data, "id", path), f"{path}.id"),
        title=_nonempty_string(_required(data, "title", path), f"{path}.title"),
        root=_topic(_required(data, "root", path), f"{path}.root"),
        cross_links=tuple(links),
        layout=_nonempty_string(_required(data, "layout", path), f"{path}.layout"),
        extensions=_extensions(data.get("extensions", []), f"{path}.extensions"),
        live_projection=(
            None
            if data.get("live_projection") is None
            else projection_definition_from_data(
                data.get("live_projection"), f"{path}.live_projection"
            )
        ),
    )


def _point(value: object, path: str) -> Point:
    data = _object(value, path)
    return Point(
        x=_number(_required(data, "x", path), f"{path}.x"),
        y=_number(_required(data, "y", path), f"{path}.y"),
    )


def _freeform_object(value: object, path: str) -> FreeformObject:
    data = _object(value, path)
    kind = _string(_required(data, "kind", path), f"{path}.kind")
    item_id = _nonempty_string(_required(data, "id", path), f"{path}.id")
    if kind == "shape":
        bounds = _object(_required(data, "bounds", path), f"{path}.bounds")
        try:
            shape = ShapeKind(_string(_required(data, "shape", path), f"{path}.shape"))
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_SHAPE_KIND", f"{path}.shape", str(exc)) from exc
        return ShapeObject(
            id=item_id,
            shape=shape,
            bounds=Rect(
                x=_number(_required(bounds, "x", f"{path}.bounds"), f"{path}.bounds.x"),
                y=_number(_required(bounds, "y", f"{path}.bounds"), f"{path}.bounds.y"),
                width=_number(_required(bounds, "width", f"{path}.bounds"), f"{path}.bounds.width"),
                height=_number(
                    _required(bounds, "height", f"{path}.bounds"), f"{path}.bounds.height"
                ),
            ),
            text=_string(data.get("text", ""), f"{path}.text"),
            locked=_boolean(data.get("locked", False), f"{path}.locked"),
            hidden=_boolean(data.get("hidden", False), f"{path}.hidden"),
            z_index=_integer(data.get("z_index", 0), f"{path}.z_index"),
            rotation=_number(data.get("rotation", 0.0), f"{path}.rotation"),
            layer_id=_nonempty_string(data.get("layer_id", "layer_default"), f"{path}.layer_id"),
            group_id=_optional_string(data.get("group_id"), f"{path}.group_id"),
            asset_id=_optional_string(data.get("asset_id"), f"{path}.asset_id"),
            points=tuple(
                _point(item, f"{path}.points[{index}]")
                for index, item in enumerate(_array(data.get("points", []), f"{path}.points"))
            ),
            fill=_string(data.get("fill", "#ffffff"), f"{path}.fill"),
            stroke=_string(data.get("stroke", "#1f2937"), f"{path}.stroke"),
            semantic_id=_optional_string(data.get("semantic_id"), f"{path}.semantic_id"),
            label_override=_optional_string(data.get("label_override"), f"{path}.label_override"),
        )
    if kind == "connector":
        return ConnectorObject(
            id=item_id,
            source_id=_nonempty_string(_required(data, "source_id", path), f"{path}.source_id"),
            target_id=_nonempty_string(_required(data, "target_id", path), f"{path}.target_id"),
            points=tuple(
                _point(item, f"{path}.points[{index}]")
                for index, item in enumerate(
                    _array(_required(data, "points", path), f"{path}.points")
                )
            ),
            orthogonal=_boolean(data.get("orthogonal", True), f"{path}.orthogonal"),
            label=_string(data.get("label", ""), f"{path}.label"),
            arrow_start=_boolean(data.get("arrow_start", False), f"{path}.arrow_start"),
            arrow_end=_boolean(data.get("arrow_end", True), f"{path}.arrow_end"),
            layer_id=_nonempty_string(data.get("layer_id", "layer_default"), f"{path}.layer_id"),
            locked=_boolean(data.get("locked", False), f"{path}.locked"),
            semantic_relation_id=_optional_string(
                data.get("semantic_relation_id"),
                f"{path}.semantic_relation_id",
            ),
            label_override=_optional_string(data.get("label_override"), f"{path}.label_override"),
        )
    raise _fail("FORMAT_UNKNOWN_FREEFORM_KIND", f"{path}.kind", f"unknown kind {kind!r}")


def freeform_object_from_data(value: object, path: str = "$.freeform_object") -> FreeformObject:
    """Decode one semantic clipboard free-form object."""

    return _freeform_object(value, path)


def _freeform(data: Mapping[str, object], path: str) -> FreeformDiagram:
    objects = tuple(
        _freeform_object(item, f"{path}.objects[{index}]")
        for index, item in enumerate(_array(_required(data, "objects", path), f"{path}.objects"))
    )
    layers_list: list[Layer] = []
    raw_layers = _array(
        data.get("layers", [{"id": "layer_default", "name": "Layer 1"}]),
        f"{path}.layers",
    )
    for index, raw in enumerate(raw_layers):
        item_path = f"{path}.layers[{index}]"
        item = _object(raw, item_path)
        layers_list.append(
            Layer(
                id=_nonempty_string(_required(item, "id", item_path), f"{item_path}.id"),
                name=_nonempty_string(_required(item, "name", item_path), f"{item_path}.name"),
                hidden=_boolean(item.get("hidden", False), f"{item_path}.hidden"),
                locked=_boolean(item.get("locked", False), f"{item_path}.locked"),
            )
        )
    layers = tuple(layers_list)
    guides: list[Guide] = []
    for index, raw in enumerate(_array(data.get("guides", []), f"{path}.guides")):
        item_path = f"{path}.guides[{index}]"
        item = _object(raw, item_path)
        try:
            orientation = GuideOrientation(
                _string(_required(item, "orientation", item_path), f"{item_path}.orientation")
            )
        except ValueError as exc:
            raise _fail(
                "FORMAT_UNKNOWN_GUIDE_ORIENTATION",
                f"{item_path}.orientation",
                str(exc),
            ) from exc
        guides.append(
            Guide(
                _nonempty_string(_required(item, "id", item_path), f"{item_path}.id"),
                orientation,
                _number(_required(item, "position", item_path), f"{item_path}.position"),
            )
        )
    return FreeformDiagram(
        id=_nonempty_string(_required(data, "id", path), f"{path}.id"),
        title=_nonempty_string(_required(data, "title", path), f"{path}.title"),
        objects=objects,
        layers=layers,
        guides=tuple(guides),
        grid_size=_number(data.get("grid_size", 16.0), f"{path}.grid_size"),
        snap_to_grid=_boolean(data.get("snap_to_grid", True), f"{path}.snap_to_grid"),
        extensions=_extensions(data.get("extensions", []), f"{path}.extensions"),
        live_projection=(
            None
            if data.get("live_projection") is None
            else projection_definition_from_data(
                data.get("live_projection"), f"{path}.live_projection"
            )
        ),
    )


def document_from_data(value: object, path: str = "$.document") -> ProjectDocument:
    data = _object(value, path)
    raw_kind = _string(_required(data, "kind", path), f"{path}.kind")
    try:
        kind = DocumentKind(raw_kind)
    except ValueError as exc:
        raise _fail("FORMAT_UNKNOWN_DOCUMENT_KIND", f"{path}.kind", str(exc)) from exc
    if kind is DocumentKind.DRAKON:
        return _drakon(data, path)
    if kind is DocumentKind.MIND_MAP:
        return _mind_map(data, path)
    if kind is DocumentKind.FREEFORM:
        return _freeform(data, path)
    raise _fail("FORMAT_UNKNOWN_DOCUMENT_KIND", f"{path}.kind", raw_kind)


def _run_profile(value: object, path: str) -> RunProfile:
    data = _object(value, path)
    environment: list[EnvironmentVariable] = []
    for index, raw in enumerate(_array(data.get("environment", []), f"{path}.environment")):
        item_path = f"{path}.environment[{index}]"
        item = _object(raw, item_path)
        environment.append(
            EnvironmentVariable(
                name=_nonempty_string(_required(item, "name", item_path), f"{item_path}.name"),
                value=_string(_required(item, "value", item_path), f"{item_path}.value"),
            )
        )
    return RunProfile(
        name=_nonempty_string(_required(data, "name", path), f"{path}.name"),
        interpreter=_string(data.get("interpreter", ""), f"{path}.interpreter"),
        working_directory=_string(data.get("working_directory", "."), f"{path}.working_directory"),
        arguments=_string(data.get("arguments", ""), f"{path}.arguments"),
        environment=tuple(environment),
    )


def _configured_arguments(value: object, path: str) -> ConfiguredArguments:
    try:
        return invocation_arguments_from_data(value)
    except ValueError as exc:
        raise _fail("FORMAT_INVOCATION_ARGUMENTS", path, str(exc)) from exc


def runtime_settings_from_data(
    value: object, path: str = "$.runtime_settings"
) -> PythonRuntimeSettings:
    data = _object(value, path)
    unknown = set(data) - {"run_profiles", "active_run_profile"}
    if unknown:
        raise _fail(
            "FORMAT_DUPLICATE_EXECUTABLE_STATE",
            path,
            "Runtime configuration cannot contain executable fields: " + ", ".join(sorted(unknown)),
        )

    profiles = tuple(
        _run_profile(item, f"{path}.run_profiles[{index}]")
        for index, item in enumerate(
            _array(data.get("run_profiles", [{"name": "Default"}]), f"{path}.run_profiles")
        )
    )
    return PythonRuntimeSettings(
        run_profiles=profiles,
        active_run_profile=_nonempty_string(
            data.get("active_run_profile", "Default"), f"{path}.active_run_profile"
        ),
    )


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{path}[{index}]") for index, item in enumerate(_array(value, path))
    )


def _semantic_concept(value: object, path: str) -> SemanticConcept:
    data = _object(value, path)
    return SemanticConcept(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _nonempty_string(_required(data, "title", path), f"{path}.title"),
        _string(data.get("description", ""), f"{path}.description"),
        _string_tuple(data.get("member_ids", []), f"{path}.member_ids"),
        _string_tuple(data.get("tags", []), f"{path}.tags"),
    )


def _authored_semantic_relation(value: object, path: str) -> AuthoredSemanticRelation:
    data = _object(value, path)
    try:
        kind = AuthoredRelationKind(_string(data.get("kind", "associates"), f"{path}.kind"))
    except ValueError as exc:
        raise _fail("FORMAT_UNKNOWN_AUTHORED_RELATION_KIND", f"{path}.kind", str(exc)) from exc
    return AuthoredSemanticRelation(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _nonempty_string(_required(data, "source_id", path), f"{path}.source_id"),
        _nonempty_string(_required(data, "target_id", path), f"{path}.target_id"),
        kind,
        _string(data.get("label", ""), f"{path}.label"),
        _string(data.get("description", ""), f"{path}.description"),
    )


def projection_definition_from_data(value: object, path: str) -> ProjectionDefinition:
    data = _object(value, path)
    try:
        object_kinds = tuple(
            SemanticObjectKind(item)
            for item in _string_tuple(data.get("object_kinds", []), f"{path}.object_kinds")
        )
        relation_kinds = tuple(
            SemanticRelationKind(item)
            for item in _string_tuple(data.get("relation_kinds", []), f"{path}.relation_kinds")
        )
        decorations = tuple(
            ProjectionDecoration(item)
            for item in _string_tuple(data.get("decorations", ["kind"]), f"{path}.decorations")
        )
        direction = TraversalDirection(_string(data.get("direction", "both"), f"{path}.direction"))
        grouping = ProjectionGrouping(_string(data.get("grouping", "none"), f"{path}.grouping"))
        label_style = ProjectionLabelStyle(
            _string(data.get("label_style", "short"), f"{path}.label_style")
        )
        layout = ProjectionLayout(_string(data.get("layout", "hierarchical"), f"{path}.layout"))
    except ValueError as exc:
        raise _fail("FORMAT_UNKNOWN_PROJECTION_VALUE", path, str(exc)) from exc
    return ProjectionDefinition(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _nonempty_string(_required(data, "title", path), f"{path}.title"),
        _optional_string(data.get("scope_id"), f"{path}.scope_id"),
        object_kinds,
        relation_kinds,
        direction,
        _integer(data.get("max_depth", 4), f"{path}.max_depth"),
        grouping,
        decorations,
        label_style,
        layout,
        _boolean(data.get("include_scope", True), f"{path}.include_scope"),
        _boolean(data.get("include_isolated", True), f"{path}.include_isolated"),
        _integer(data.get("node_limit", 100), f"{path}.node_limit"),
        _string_tuple(data.get("expanded_ids", []), f"{path}.expanded_ids"),
        _string_tuple(data.get("focus_ids", []), f"{path}.focus_ids"),
    )


def _program_expression(
    value: object,
    path: str,
) -> ProgramExpression:
    data = _object(value, path)
    try:
        role = ExpressionRole(_nonempty_string(_required(data, "role", path), f"{path}.role"))
    except ValueError as exc:
        raise _fail("FORMAT_UNKNOWN_EXPRESSION_ROLE", f"{path}.role", str(exc)) from exc
    expression_id = _nonempty_string(_required(data, "id", path), f"{path}.id")
    if "source" in data:
        raise _fail(
            "FORMAT_DUPLICATE_EXPRESSION_TRUTH",
            f"{path}.source",
            "canonical expressions must store only their tree",
        )
    try:
        tree = expression_node_from_data(_required(data, "tree", path))
        render_expression_tree(tree)
    except ProjectDecodeError:
        raise
    except ValueError as exc:
        raise _fail("FORMAT_INVALID_EXPRESSION_TREE", f"{path}.tree", str(exc)) from exc
    return ProgramExpression(expression_id, role, tree)


def _optional_program_expression(
    value: object,
    path: str,
) -> ProgramExpression | None:
    return None if value is None else _program_expression(value, path)


def program_expression_from_data(
    value: object,
    path: str = "$.program_expression",
) -> ProgramExpression:
    """Decode one canonical expression from a command or project payload."""

    return _program_expression(value, path)


def _program_sequence(
    value: object,
    path: str,
) -> ProgramSequence:
    data = _object(value, path)
    statements: list[ProgramStatement] = []
    for index, raw in enumerate(_array(_required(data, "statements", path), f"{path}.statements")):
        statement_path = f"{path}.statements[{index}]"
        item = _object(raw, statement_path)
        kind = _nonempty_string(_required(item, "kind", statement_path), f"{statement_path}.kind")
        statement_id = _nonempty_string(
            _required(item, "id", statement_path), f"{statement_path}.id"
        )
        written = tuple(
            _nonempty_string(raw_id, f"{statement_path}.written_symbol_ids[{symbol_index}]")
            for symbol_index, raw_id in enumerate(
                _array(item.get("written_symbol_ids", []), f"{statement_path}.written_symbol_ids")
            )
        )
        if kind == "assignment":
            statements.append(
                ProgramAssignment(
                    statement_id,
                    _program_expression(
                        _required(item, "target", statement_path),
                        f"{statement_path}.target",
                    ),
                    _program_expression(
                        _required(item, "value", statement_path),
                        f"{statement_path}.value",
                    ),
                    _optional_program_expression(
                        item.get("annotation"),
                        f"{statement_path}.annotation",
                    ),
                    _nonempty_string(
                        _required(item, "operator", statement_path),
                        f"{statement_path}.operator",
                    ),
                    written,
                )
            )
        elif kind == "output":
            statements.append(
                ProgramOutput(
                    statement_id,
                    _program_expression(
                        _required(item, "expression", statement_path),
                        f"{statement_path}.expression",
                    ),
                    _optional_program_expression(
                        item.get("destination"),
                        f"{statement_path}.destination",
                    ),
                    _optional_program_expression(
                        item.get("end"),
                        f"{statement_path}.end",
                    ),
                )
            )
        elif kind == "call":
            statements.append(
                ProgramCall(
                    statement_id,
                    _program_expression(
                        _required(item, "expression", statement_path),
                        f"{statement_path}.expression",
                    ),
                    _program_expression(
                        _required(item, "arguments", statement_path),
                        f"{statement_path}.arguments",
                    ),
                    _boolean(
                        _required(item, "awaited", statement_path),
                        f"{statement_path}.awaited",
                    ),
                    _optional_program_expression(
                        item.get("result_target"),
                        f"{statement_path}.result_target",
                    ),
                    _optional_string(
                        item.get("target_function_id"),
                        f"{statement_path}.target_function_id",
                    ),
                    written,
                )
            )
        elif kind == "if":
            statements.append(
                ProgramIf(
                    statement_id,
                    _program_expression(
                        _required(item, "condition", statement_path),
                        f"{statement_path}.condition",
                    ),
                    _program_sequence(
                        _required(item, "true_branch", statement_path),
                        f"{statement_path}.true_branch",
                    ),
                    _program_sequence(
                        _required(item, "false_branch", statement_path),
                        f"{statement_path}.false_branch",
                    ),
                    _boolean(
                        _required(item, "preferred_truth", statement_path),
                        f"{statement_path}.preferred_truth",
                    ),
                )
            )
        elif kind == "action":
            statements.append(_program_action(item, statement_path))
        elif kind == "transfer":
            statements.append(_program_transfer(item, statement_path))
        elif kind == "simple_statement":
            statements.append(_program_simple_statement(item, statement_path))
        elif kind == "input":
            statements.append(_program_input(item, statement_path))
        elif kind == "delay":
            statements.append(_program_delay(item, statement_path))
        elif kind == "start_timer":
            statements.append(_program_start_timer(item, statement_path))
        elif kind == "period":
            statements.append(_program_period(item, statement_path))
        elif kind == "realtime_process":
            statements.append(_program_realtime_process(item, statement_path))
        elif kind == "note":
            statements.append(_program_note(item, statement_path))
        elif kind == "select":
            statements.append(_program_select(item, statement_path))
        elif kind == "loop":
            statements.append(_program_loop(item, statement_path))
        elif kind == "with":
            statements.append(_program_with(item, statement_path))
        elif kind == "try":
            statements.append(_program_try(item, statement_path))
        elif kind == "synchronizer":
            statements.append(_program_synchronizer(item, statement_path))
        elif kind == "parallel":
            statements.append(_program_parallel(item, statement_path))
        elif kind == "silhouette":
            statements.append(_program_silhouette(item, statement_path))
        else:
            raise _fail(
                "FORMAT_UNKNOWN_PROGRAM_STATEMENT",
                f"{statement_path}.kind",
                f"unknown canonical statement kind {kind!r}",
            )
    return ProgramSequence(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        tuple(statements),
    )


def _program_action(value: object, path: str) -> ProgramAction:
    data = _object(value, path)
    return ProgramAction(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _program_expression(_required(data, "source", path), f"{path}.source"),
    )


def _program_transfer(value: object, path: str) -> ProgramTransfer:
    data = _object(value, path)
    return ProgramTransfer(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _enum(TransferKind, _required(data, "transfer_kind", path), f"{path}.transfer_kind"),
        _optional_program_expression(_required(data, "expression", path), f"{path}.expression"),
        _optional_program_expression(_required(data, "cause", path), f"{path}.cause"),
    )


def _program_simple_statement(value: object, path: str) -> ProgramSimpleStatement:
    data = _object(value, path)
    return ProgramSimpleStatement(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _enum(SimpleKind, _required(data, "statement_kind", path), f"{path}.statement_kind"),
        _program_expression(_required(data, "source", path), f"{path}.source"),
        _optional_program_expression(_required(data, "secondary", path), f"{path}.secondary"),
    )


def _program_input(value: object, path: str) -> ProgramInput:
    data = _object(value, path)
    return ProgramInput(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _program_expression(_required(data, "target", path), f"{path}.target"),
        _program_expression(_required(data, "prompt", path), f"{path}.prompt"),
        _optional_program_expression(_required(data, "converter", path), f"{path}.converter"),
        _optional_program_expression(_required(data, "annotation", path), f"{path}.annotation"),
    )


def _program_delay(value: object, path: str) -> ProgramDelay:
    data = _object(value, path)
    return ProgramDelay(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _program_expression(_required(data, "seconds", path), f"{path}.seconds"),
        _boolean(_required(data, "asynchronous", path), f"{path}.asynchronous"),
    )


def _program_start_timer(value: object, path: str) -> ProgramStartTimer:
    data = _object(value, path)
    return ProgramStartTimer(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _string(_required(data, "timer", path), f"{path}.timer"),
    )


def _program_period(value: object, path: str) -> ProgramPeriod:
    data = _object(value, path)
    return ProgramPeriod(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _string(_required(data, "timer", path), f"{path}.timer"),
        _program_expression(_required(data, "seconds", path), f"{path}.seconds"),
        _boolean(_required(data, "asynchronous", path), f"{path}.asynchronous"),
    )


def _program_realtime_process(value: object, path: str) -> ProgramRealtimeProcess:
    data = _object(value, path)
    return ProgramRealtimeProcess(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _program_expression(_required(data, "call", path), f"{path}.call"),
        _boolean(_required(data, "awaited", path), f"{path}.awaited"),
    )


def _program_note(value: object, path: str) -> ProgramNote:
    data = _object(value, path)
    return ProgramNote(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _string(_required(data, "text", path), f"{path}.text"),
        _enum(NotePlacement, _required(data, "placement", path), f"{path}.placement"),
    )


def _program_case(value: object, path: str) -> ProgramCase:
    data = _object(value, path)
    return ProgramCase(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _string(_required(data, "label", path), f"{path}.label"),
        _program_sequence(_required(data, "body", path), f"{path}.body"),
        _program_expression(_required(data, "condition", path), f"{path}.condition"),
        _program_expression(_required(data, "pattern", path), f"{path}.pattern"),
        _optional_program_expression(_required(data, "guard", path), f"{path}.guard"),
        _boolean(_required(data, "is_default", path), f"{path}.is_default"),
    )


def _program_select(value: object, path: str) -> ProgramSelect:
    data = _object(value, path)
    return ProgramSelect(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _program_expression(_required(data, "expression", path), f"{path}.expression"),
        tuple(
            _program_case(item, f"{path}.cases[{index}]")
            for index, item in enumerate(_array(_required(data, "cases", path), f"{path}.cases"))
        ),
        _enum(SelectMode, _required(data, "mode", path), f"{path}.mode"),
        _optional_string(_required(data, "preferred_case_id", path), f"{path}.preferred_case_id"),
    )


def _program_loop(value: object, path: str) -> ProgramLoop:
    data = _object(value, path)
    return ProgramLoop(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _enum(LoopKind, _required(data, "loop_kind", path), f"{path}.loop_kind"),
        _program_sequence(_required(data, "body", path), f"{path}.body"),
        _program_sequence(_required(data, "else_body", path), f"{path}.else_body"),
        _program_expression(_required(data, "condition", path), f"{path}.condition"),
        _program_expression(_required(data, "target", path), f"{path}.target"),
        _program_expression(_required(data, "iterable", path), f"{path}.iterable"),
        _program_expression(_required(data, "children", path), f"{path}.children"),
        _program_expression(_required(data, "delay_seconds", path), f"{path}.delay_seconds"),
    )


def _program_context_item(value: object, path: str) -> ProgramContextItem:
    data = _object(value, path)
    return ProgramContextItem(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _program_expression(_required(data, "expression", path), f"{path}.expression"),
        _optional_program_expression(_required(data, "target", path), f"{path}.target"),
    )


def _program_with(value: object, path: str) -> ProgramWith:
    data = _object(value, path)
    return ProgramWith(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        tuple(
            _program_context_item(item, f"{path}.contexts[{index}]")
            for index, item in enumerate(
                _array(_required(data, "contexts", path), f"{path}.contexts")
            )
        ),
        _program_sequence(_required(data, "body", path), f"{path}.body"),
        _boolean(_required(data, "asynchronous", path), f"{path}.asynchronous"),
    )


def _program_exception_handler(value: object, path: str) -> ProgramExceptionHandler:
    data = _object(value, path)
    return ProgramExceptionHandler(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _optional_program_expression(_required(data, "exception", path), f"{path}.exception"),
        _optional_program_expression(_required(data, "name", path), f"{path}.name"),
        _program_sequence(_required(data, "body", path), f"{path}.body"),
    )


def _program_try(value: object, path: str) -> ProgramTry:
    data = _object(value, path)
    return ProgramTry(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _program_sequence(_required(data, "body", path), f"{path}.body"),
        tuple(
            _program_exception_handler(item, f"{path}.handlers[{index}]")
            for index, item in enumerate(
                _array(_required(data, "handlers", path), f"{path}.handlers")
            )
        ),
        _program_sequence(_required(data, "else_body", path), f"{path}.else_body"),
        _program_sequence(_required(data, "finally_body", path), f"{path}.finally_body"),
        _boolean(_required(data, "except_star", path), f"{path}.except_star"),
    )


def _program_synchronizer(value: object, path: str) -> ProgramSynchronizer:
    data = _object(value, path)
    return ProgramSynchronizer(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _string(_required(data, "timer", path), f"{path}.timer"),
        _program_expression(_required(data, "deadline", path), f"{path}.deadline"),
        _program_sequence(_required(data, "on_time", path), f"{path}.on_time"),
        _program_sequence(_required(data, "on_timeout", path), f"{path}.on_timeout"),
        _boolean(_required(data, "preferred_on_time", path), f"{path}.preferred_on_time"),
    )


def _program_parallel_branch(value: object, path: str) -> ProgramParallelBranch:
    data = _object(value, path)
    return ProgramParallelBranch(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _string(_required(data, "name", path), f"{path}.name"),
        _program_sequence(_required(data, "body", path), f"{path}.body"),
    )


def _program_parallel(value: object, path: str) -> ProgramParallel:
    data = _object(value, path)
    return ProgramParallel(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        tuple(
            _program_parallel_branch(item, f"{path}.branches[{index}]")
            for index, item in enumerate(
                _array(_required(data, "branches", path), f"{path}.branches")
            )
        ),
        _enum(ParallelMode, _required(data, "mode", path), f"{path}.mode"),
    )


def _program_silhouette_branch(value: object, path: str) -> ProgramSilhouetteBranch:
    data = _object(value, path)
    return ProgramSilhouetteBranch(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _string(_required(data, "name", path), f"{path}.name"),
        _program_sequence(_required(data, "body", path), f"{path}.body"),
        _optional_string(_required(data, "target_branch_id", path), f"{path}.target_branch_id"),
    )


def _program_silhouette(value: object, path: str) -> ProgramSilhouette:
    data = _object(value, path)
    return ProgramSilhouette(
        _nonempty_string(_required(data, "id", path), f"{path}.id"),
        _string(_required(data, "display_name", path), f"{path}.display_name"),
        _string(_required(data, "identifier", path), f"{path}.identifier"),
        tuple(
            _program_silhouette_branch(item, f"{path}.branches[{index}]")
            for index, item in enumerate(
                _array(_required(data, "branches", path), f"{path}.branches")
            )
        ),
        _string(_required(data, "initial_branch_id", path), f"{path}.initial_branch_id"),
    )


def program_sequence_from_data(
    value: object,
    path: str = "$.program_sequence",
) -> ProgramSequence:
    """Decode one canonical sequence independently of a project."""

    return _program_sequence(value, path)


def program_statement_from_data(
    value: object,
    path: str = "$.program_statement",
) -> ProgramStatement:
    """Decode one statement using the canonical project grammar."""

    sequence = _program_sequence(
        {"id": "command-envelope", "statements": [value]},
        path,
    )
    return sequence.statements[0]


def _program_function(
    value: object,
    path: str,
) -> ProgramFunction:
    data = _object(value, path)
    if {"module", "owning_class"} & data.keys():
        raise _fail(
            "FORMAT_DUPLICATE_EXECUTABLE_STATE",
            path,
            "Function ownership belongs to module/class declarations",
        )
    function_id = _nonempty_string(_required(data, "id", path), f"{path}.id")
    try:
        kind = CallableKind(_nonempty_string(_required(data, "kind", path), f"{path}.kind"))
    except ValueError as exc:
        raise _fail("FORMAT_UNKNOWN_CALLABLE_KIND", f"{path}.kind", str(exc)) from exc
    raw_method_kind = data.get("method_kind")
    method_kind: MethodKind | None = None
    if raw_method_kind is not None:
        try:
            method_kind = MethodKind(_nonempty_string(raw_method_kind, f"{path}.method_kind"))
        except ValueError as exc:
            raise _fail("FORMAT_UNKNOWN_METHOD_KIND", f"{path}.method_kind", str(exc)) from exc
    parameters: list[ProgramParameter] = []
    for index, raw in enumerate(_array(_required(data, "parameters", path), f"{path}.parameters")):
        parameter_path = f"{path}.parameters[{index}]"
        item = _object(raw, parameter_path)
        try:
            parameter_kind = ParameterKind(
                _nonempty_string(_required(item, "kind", parameter_path), f"{parameter_path}.kind")
            )
        except ValueError as exc:
            raise _fail(
                "FORMAT_UNKNOWN_PARAMETER_KIND",
                f"{parameter_path}.kind",
                str(exc),
            ) from exc
        parameters.append(
            ProgramParameter(
                _nonempty_string(_required(item, "id", parameter_path), f"{parameter_path}.id"),
                _nonempty_string(
                    _required(item, "symbol_id", parameter_path),
                    f"{parameter_path}.symbol_id",
                ),
                _nonempty_string(_required(item, "name", parameter_path), f"{parameter_path}.name"),
                parameter_kind,
                _optional_program_expression(
                    item.get("annotation"),
                    f"{parameter_path}.annotation",
                ),
                _optional_program_expression(
                    item.get("default"),
                    f"{parameter_path}.default",
                ),
            )
        )
    decorators = tuple(
        _program_expression(
            item,
            f"{path}.decorators[{index}]",
        )
        for index, item in enumerate(
            _array(_required(data, "decorators", path), f"{path}.decorators")
        )
    )
    return ProgramFunction(
        function_id,
        _nonempty_string(_required(data, "symbol_id", path), f"{path}.symbol_id"),
        _nonempty_string(_required(data, "identifier", path), f"{path}.identifier"),
        _nonempty_string(_required(data, "display_name", path), f"{path}.display_name"),
        kind,
        tuple(parameters),
        _optional_program_expression(
            data.get("return_annotation"),
            f"{path}.return_annotation",
        ),
        decorators,
        _optional_string(data.get("docstring"), f"{path}.docstring"),
        method_kind,
        _program_sequence(
            _required(data, "body", path),
            f"{path}.body",
        ),
        _expression_nodes(data.get("type_parameters", []), f"{path}.type_parameters"),
    )


def program_function_from_data(
    value: object,
    path: str = "$.program_function",
) -> ProgramFunction:
    """Decode one canonical function for exact restore operations."""

    return _program_function(value, path)


def _expression_nodes(value: object, path: str) -> tuple[ExpressionNode, ...]:
    try:
        return tuple(expression_node_from_data(item) for item in _array(value, path))
    except (ValueError, TypeError) as exc:
        raise _fail("FORMAT_PROGRAM_EXPRESSION", path, str(exc)) from exc


def _declarations(value: object, path: str) -> tuple[ProgramDeclaration, ...]:
    return tuple(
        program_declaration_from_data(item, f"{path}[{index}]")
        for index, item in enumerate(_array(value, path))
    )


def _declaration_fields(data: Mapping[str, object], allowed: set[str], path: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise _fail(
            "FORMAT_UNKNOWN_PROGRAM_FIELD",
            path,
            "Unknown canonical declaration fields: " + ", ".join(sorted(extra)),
        )


def program_declaration_from_data(
    value: object,
    path: str = "$.program_declaration",
) -> ProgramDeclaration:
    data = _object(value, path)
    kind = _nonempty_string(_required(data, "kind", path), f"{path}.kind")
    if kind == "function_reference":
        if set(data) != {"kind", "function_id"}:
            raise _fail(
                "FORMAT_PROGRAM_OWNERSHIP",
                path,
                "A function reference stores only its target identity",
            )
        return ProgramFunctionReference(
            _nonempty_string(_required(data, "function_id", path), f"{path}.function_id")
        )
    if kind == "class":
        return program_class_from_data(data, path)
    if kind in {"import", "type_alias"}:
        _declaration_fields(data, {"kind", "id", "source"}, path)
        identity = _nonempty_string(_required(data, "id", path), f"{path}.id")
        source = _program_expression(_required(data, "source", path), f"{path}.source")
        return (
            ProgramImport(identity, source)
            if kind == "import"
            else ProgramTypeAlias(identity, source)
        )
    return program_statement_from_data(data, path)


def program_class_from_data(value: object, path: str = "$.program_class") -> ProgramClass:
    data = _object(value, path)
    _declaration_fields(
        data,
        {
            "kind",
            "id",
            "identifier",
            "body",
            "arguments",
            "decorators",
            "docstring",
            "type_parameters",
        },
        path,
    )
    if data.get("kind") != "class":
        raise _fail("FORMAT_PROGRAM_CLASS", path, "Expected a class declaration")
    return ProgramClass(
        id=_nonempty_string(_required(data, "id", path), f"{path}.id"),
        identifier=_nonempty_string(_required(data, "identifier", path), f"{path}.identifier"),
        body=_declarations(_required(data, "body", path), f"{path}.body"),
        arguments=_optional_program_expression(data.get("arguments"), f"{path}.arguments"),
        decorators=tuple(
            _program_expression(item, f"{path}.decorators[{index}]")
            for index, item in enumerate(_array(data.get("decorators", []), f"{path}.decorators"))
        ),
        docstring=_optional_string(data.get("docstring"), f"{path}.docstring"),
        type_parameters=_expression_nodes(
            data.get("type_parameters", []), f"{path}.type_parameters"
        ),
    )


def program_module_from_data(value: object, path: str = "$.program_module") -> ProgramModule:
    data = _object(value, path)
    legacy = {
        "imports",
        "constants",
        "type_aliases",
        "declarations",
        "before_functions",
        "after_functions",
    }
    if legacy & data.keys():
        raise _fail(
            "FORMAT_DUPLICATE_EXECUTABLE_STATE",
            path,
            "Module declarations must have one typed ordered body",
        )
    _declaration_fields(data, {"id", "kind", "path", "body", "docstring"}, path)
    try:
        kind = ProgramModuleKind(_string(_required(data, "kind", path), f"{path}.kind"))
    except ValueError as exc:
        raise _fail("FORMAT_PROGRAM_MODULE_KIND", f"{path}.kind", str(exc)) from exc
    module_path = _string(_required(data, "path", path), f"{path}.path")
    return ProgramModule(
        id=_nonempty_string(_required(data, "id", path), f"{path}.id"),
        path=""
        if kind is ProgramModuleKind.PACKAGE and module_path == ""
        else canonical_module_path(module_path),
        body=_declarations(_required(data, "body", path), f"{path}.body"),
        docstring=_string(data.get("docstring", ""), f"{path}.docstring"),
        kind=kind,
    )


def program_entrypoint_from_data(
    value: object, path: str = "$.program_entrypoint"
) -> ProgramEntryPoint:
    data = _object(value, path)
    _declaration_fields(data, {"id", "callable_id", "arguments", "startup"}, path)
    return ProgramEntryPoint(
        id=_nonempty_string(_required(data, "id", path), f"{path}.id"),
        callable_id=_optional_string(data.get("callable_id"), f"{path}.callable_id"),
        arguments=_configured_arguments(_required(data, "arguments", path), f"{path}.arguments"),
        startup=_declarations(_required(data, "startup", path), f"{path}.startup"),
    )


def program_model_from_data(value: object, path: str = "$.program_model") -> ProgramModel:
    data = _object(value, path)
    symbols: list[ProgramSymbol] = []
    for index, raw in enumerate(_array(_required(data, "symbols", path), f"{path}.symbols")):
        symbol_path = f"{path}.symbols[{index}]"
        item = _object(raw, symbol_path)
        try:
            kind = ProgramSymbolKind(
                _nonempty_string(_required(item, "kind", symbol_path), f"{symbol_path}.kind")
            )
        except ValueError as exc:
            raise _fail(
                "FORMAT_UNKNOWN_PROGRAM_SYMBOL_KIND",
                f"{symbol_path}.kind",
                str(exc),
            ) from exc
        symbols.append(
            ProgramSymbol(
                _nonempty_string(_required(item, "id", symbol_path), f"{symbol_path}.id"),
                _nonempty_string(_required(item, "name", symbol_path), f"{symbol_path}.name"),
                kind,
                _nonempty_string(
                    _required(item, "owner_id", symbol_path), f"{symbol_path}.owner_id"
                ),
                _nonempty_string(
                    _required(item, "declaration_id", symbol_path),
                    f"{symbol_path}.declaration_id",
                ),
            )
        )
    decoded_symbols = tuple(symbols)
    functions = tuple(
        _program_function(item, f"{path}.functions[{index}]")
        for index, item in enumerate(
            _array(_required(data, "functions", path), f"{path}.functions")
        )
    )
    return ProgramModel(
        functions,
        decoded_symbols,
        tuple(
            program_module_from_data(item, f"{path}.modules[{index}]")
            for index, item in enumerate(
                _array(_required(data, "modules", path), f"{path}.modules")
            )
        ),
        canonical_package_path(_string(_required(data, "package", path), f"{path}.package")),
        program_entrypoint_from_data(data["entrypoint"], f"{path}.entrypoint")
        if _required(data, "entrypoint", path) is not None
        else None,
    )


def _drakon_views_from_data(value: object, path: str) -> tuple[DrakonViewDefinition, ...]:
    views: list[DrakonViewDefinition] = []
    for index, raw in enumerate(_array(value, path)):
        view_path = f"{path}[{index}]"
        item = _object(raw, view_path)
        views.append(
            DrakonViewDefinition(
                _nonempty_string(
                    _required(item, "document_id", view_path), f"{view_path}.document_id"
                ),
                _nonempty_string(
                    _required(item, "function_id", view_path), f"{view_path}.function_id"
                ),
                _nonempty_string(_required(item, "title", view_path), f"{view_path}.title"),
                _nonempty_string(_required(item, "header_id", view_path), f"{view_path}.header_id"),
                _nonempty_string(_required(item, "end_id", view_path), f"{view_path}.end_id"),
            )
        )
    return tuple(views)


def _upgrade_v4_program(
    value: object,
    documents: tuple[ProjectDocument, ...],
    views: tuple[DrakonViewDefinition, ...],
) -> ProgramModel:
    """Consume the old placeholder format at load time, never in the live model.

    Only placeholder entries are filled from legacy diagrams. Already canonical
    statements, expressions, signatures and identities remain authoritative.
    """
    from code_visualizer.persistence.serialization import program_statement_to_data

    def without_placeholders(raw: object) -> object:
        if isinstance(raw, list):
            return [
                without_placeholders(item)
                for item in raw
                if not (
                    isinstance(item, dict) and item.get("kind") == "unmigrated_drakon_statement"
                )
            ]
        if isinstance(raw, dict):
            return {key: without_placeholders(item) for key, item in raw.items()}
        return raw

    previous = program_model_from_data(without_placeholders(value))
    diagrams = tuple(item for item in documents if isinstance(item, DrakonDiagram))
    promoted = promote_program_from_drakon(diagrams, previous, views, deterministic=True).model
    functions = {item.id: item for item in promoted.functions}

    def upgrade_sequence(raw: object, function_id: str, path: str) -> object:
        if isinstance(raw, list):
            return [
                upgrade_sequence(item, function_id, f"{path}[{index}]")
                for index, item in enumerate(raw)
            ]
        if isinstance(raw, dict):
            if raw.get("kind") == "unmigrated_drakon_statement":
                function = functions.get(function_id)
                statement = (
                    next(
                        (
                            item
                            for item in program_statements(function.body)
                            if item.id == raw.get("id")
                        ),
                        None,
                    )
                    if function
                    else None
                )
                if (
                    statement is None
                    or type(statement).__name__ != f"Program{raw.get('drakon_kind')}"
                ):
                    raise _fail(
                        "FORMAT_LEGACY_PAYLOAD_REQUIRED",
                        path,
                        "The revision-4 statement has no matching legacy DRAKON payload",
                    )
                return program_statement_to_data(statement)
            return {
                key: upgrade_sequence(item, function_id, f"{path}.{key}")
                for key, item in raw.items()
            }
        return raw

    data = _object(value, "$.program_model")
    updated = dict(data)
    updated["functions"] = [
        upgrade_sequence(
            item,
            _nonempty_string(
                _required(
                    _object(item, "$.program_model.functions"), "id", "$.program_model.functions"
                ),
                "$.program_model.functions.id",
            ),
            f"$.program_model.functions[{index}]",
        )
        for index, item in enumerate(
            _array(_required(data, "functions", "$.program_model"), "$.program_model.functions")
        )
    ]
    model = program_model_from_data(updated)
    previous_ids = {item.id for item in model.symbols}
    from dataclasses import replace

    return replace(
        model,
        symbols=(
            *model.symbols,
            *(item for item in promoted.symbols if item.id not in previous_ids),
        ),
    )


def _project_document_from_data(
    value: object,
    path: str,
    model: ProgramModel,
    views: Mapping[str, DrakonViewDefinition],
    functions: Mapping[str, ProgramFunction],
    locations: Mapping[str, ProgramFunctionLocation],
) -> ProjectDocument:
    data = _object(value, path)
    if data.get("kind") != "drakon":
        return document_from_data(value, path)
    if any(key in data for key in ("body", "header", "end")):
        raise _fail(
            "FORMAT_DUPLICATE_EXECUTABLE_STATE",
            path,
            "DRAKON presentations must not store executable fields",
        )
    document_id = _nonempty_string(_required(data, "id", path), f"{path}.id")
    view = views.get(document_id)
    function = functions.get(view.function_id) if view is not None else None
    if view is None or function is None:
        raise _fail(
            "PROGRAM_UNRESOLVED_DRAKON_VIEW",
            path,
            "DRAKON presentation must bind an existing canonical function",
        )
    from dataclasses import replace

    return replace(
        drakon_from_program(function, view, model=model, locations=locations),
        title=_nonempty_string(_required(data, "title", path), f"{path}.title"),
        description=_string(data.get("description", ""), f"{path}.description"),
        extensions=_extensions(data.get("extensions", []), f"{path}.extensions"),
    )


def project_from_data(value: object) -> Project:
    data = _object(value, "$")
    format_revision = _integer(_required(data, "format_revision", "$"), "$.format_revision")
    if format_revision not in {4, 5, 6, 7, 8, 9, 10, PRODUCT.project_format_revision}:
        raise _fail(
            "FORMAT_UNSUPPORTED_REVISION",
            "$.format_revision",
            f"expected {PRODUCT.project_format_revision}, received {format_revision}",
        )
    if "module_setup" in data and "runtime_settings" in data:
        raise _fail(
            "FORMAT_DUPLICATE_RUNTIME_SETTINGS",
            "$",
            "A project cannot contain both runtime_settings and legacy module_setup",
        )
    if format_revision >= 11 and "module_setup" in data:
        raise _fail(
            "FORMAT_LEGACY_RUNTIME_SETTINGS",
            "$.module_setup",
            "Current projects use runtime_settings; module_setup is a legacy load-boundary field",
        )
    if format_revision < 8:
        setup_data = _object(_required(data, "module_setup", "$"), "$.module_setup")
        legacy_arguments = setup_data.get("entrypoint_arguments", "")
        if isinstance(legacy_arguments, str):
            data = {
                **data,
                "module_setup": {
                    **setup_data,
                    "entrypoint_arguments": invocation_arguments_to_data(
                        configured_arguments_from_text(legacy_arguments)
                    ),
                },
            }
    raw_documents = _array(_required(data, "documents", "$"), "$.documents")
    drakon_views = _drakon_views_from_data(_required(data, "drakon_views", "$"), "$.drakon_views")
    raw_model = _required(data, "program_model", "$")
    if format_revision < 10:
        from code_visualizer.persistence.program_migration import (
            legacy_runtime_data,
            migrate_legacy_program_data,
        )

        raw_setup = _object(_required(data, "module_setup", "$"), "$.module_setup")
        raw_model = migrate_legacy_program_data(
            raw_model,
            raw_setup,
            project_id=_nonempty_string(_required(data, "project_id", "$"), "$.project_id"),
        )
        data = {**data, "module_setup": legacy_runtime_data(raw_setup)}
        workspace = _object(data.get("domain_workspace", {}), "$.domain_workspace")
        references = _array(
            workspace.get("bundle_references", []), "$.domain_workspace.bundle_references"
        )
        data = {
            **data,
            "domain_workspace": {
                **workspace,
                "bundle_references": [
                    {**item, "version": "2"}
                    if isinstance(item, dict)
                    and item.get("id") == "code_visualizer.computation"
                    and item.get("version") == "1"
                    else item
                    for item in references
                ],
            },
        }
    if format_revision < 11:
        from code_visualizer.persistence.program_migration import default_program_module_kinds

        raw_model = default_program_module_kinds(raw_model)
        runtime = _required(data, "module_setup", "$")
        data = {key: item for key, item in data.items() if key != "module_setup"}
        data["runtime_settings"] = runtime
    if format_revision == 4:
        documents = tuple(
            document_from_data(item, f"$.documents[{index}]")
            for index, item in enumerate(raw_documents)
        )
        program_model = _upgrade_v4_program(raw_model, documents, drakon_views)
        functions = {item.id: item for item in program_model.functions}
        views = {item.document_id: item for item in drakon_views}
        locations = program_function_locations(program_model)
        documents = tuple(
            drakon_from_program(
                functions[views[item.id].function_id],
                views[item.id],
                item,
                model=program_model,
                locations=locations,
            )
            if isinstance(item, DrakonDiagram)
            and item.id in views
            and views[item.id].function_id in functions
            else item
            for item in documents
        )
    else:
        program_model = program_model_from_data(raw_model)
        functions = {item.id: item for item in program_model.functions}
        views = {item.document_id: item for item in drakon_views}
        locations = program_function_locations(program_model)
        documents = tuple(
            _project_document_from_data(
                item, f"$.documents[{index}]", program_model, views, functions, locations
            )
            for index, item in enumerate(raw_documents)
        )
    concepts = tuple(
        _semantic_concept(item, f"$.concepts[{index}]")
        for index, item in enumerate(_array(data.get("concepts", []), "$.concepts"))
    )
    semantic_relations = tuple(
        _authored_semantic_relation(item, f"$.semantic_relations[{index}]")
        for index, item in enumerate(
            _array(data.get("semantic_relations", []), "$.semantic_relations")
        )
    )
    projection_definitions = tuple(
        projection_definition_from_data(item, f"$.projection_definitions[{index}]")
        for index, item in enumerate(
            _array(data.get("projection_definitions", []), "$.projection_definitions")
        )
    )
    managed_assets: list[ManagedAsset] = []
    for index, raw in enumerate(_array(data.get("managed_assets", []), "$.managed_assets")):
        item_path = f"$.managed_assets[{index}]"
        item = _object(raw, item_path)
        managed_assets.append(
            ManagedAsset(
                id=_nonempty_string(_required(item, "id", item_path), f"{item_path}.id"),
                relative_path=_nonempty_string(
                    _required(item, "relative_path", item_path), f"{item_path}.relative_path"
                ),
                sha256=_nonempty_string(
                    _required(item, "sha256", item_path), f"{item_path}.sha256"
                ),
                media_type=_nonempty_string(
                    _required(item, "media_type", item_path), f"{item_path}.media_type"
                ),
                byte_size=_integer(
                    _required(item, "byte_size", item_path), f"{item_path}.byte_size"
                ),
                original_name=_string(item.get("original_name", ""), f"{item_path}.original_name"),
                width=(
                    _integer(item["width"], f"{item_path}.width")
                    if item.get("width") is not None
                    else None
                ),
                height=(
                    _integer(item["height"], f"{item_path}.height")
                    if item.get("height") is not None
                    else None
                ),
            )
        )
    shape_packs: list[ShapePackReference] = []
    for index, raw in enumerate(_array(data.get("shape_packs", []), "$.shape_packs")):
        item_path = f"$.shape_packs[{index}]"
        item = _object(raw, item_path)
        shape_packs.append(
            ShapePackReference(
                id=_nonempty_string(_required(item, "id", item_path), f"{item_path}.id"),
                name=_nonempty_string(_required(item, "name", item_path), f"{item_path}.name"),
                version=_nonempty_string(
                    _required(item, "version", item_path), f"{item_path}.version"
                ),
                manifest_path=_nonempty_string(
                    _required(item, "manifest_path", item_path), f"{item_path}.manifest_path"
                ),
                sha256=_nonempty_string(
                    _required(item, "sha256", item_path), f"{item_path}.sha256"
                ),
            )
        )
    try:
        domain_workspace = domain_workspace_from_data(data.get("domain_workspace", {}))
    except DomainDecodeError as exc:
        raise _fail("FORMAT_DOMAIN_INVALID", "$.domain_workspace", str(exc)) from exc
    project = Project(
        id=_nonempty_string(_required(data, "project_id", "$"), "$.project_id"),
        title=_nonempty_string(_required(data, "title", "$"), "$.title"),
        description=_string(data.get("description", ""), "$.description"),
        revision=_integer(_required(data, "revision", "$"), "$.revision"),
        documents=documents,
        runtime_settings=runtime_settings_from_data(
            _required(data, "runtime_settings", "$"), "$.runtime_settings"
        ),
        managed_assets=tuple(managed_assets),
        shape_packs=tuple(shape_packs),
        concepts=concepts,
        semantic_relations=semantic_relations,
        projection_definitions=projection_definitions,
        program_model=program_model,
        drakon_views=drakon_views,
        domain_workspace=domain_workspace,
        extensions=_extensions(data.get("extensions", []), "$.extensions"),
        format_revision=PRODUCT.project_format_revision,
    )
    errors = [
        diagnostic
        for diagnostic in validate_integrity(project)
        if diagnostic.severity is Severity.ERROR
    ]
    if errors:
        first = errors[0]
        raise _fail(first.code, first.field or "$", first.message)
    return project


def project_from_json(source: str) -> Project:
    try:
        raw: object = json.loads(
            source,
            parse_constant=lambda value: (_ for _ in ()).throw(
                _fail("FORMAT_NONFINITE_NUMBER", "$", f"invalid numeric constant {value}")
            ),
        )
    except json.JSONDecodeError as exc:
        raise _fail("FORMAT_INVALID_JSON", "$", str(exc)) from exc
    return project_from_data(raw)
