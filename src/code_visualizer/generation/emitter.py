"""Deterministic Python emitter and bidirectional source-map projection."""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass, replace

from code_visualizer.domain.invocation import (
    InvocationSpec,
    InvocationSymbols,
    invocation_symbols,
    render_invocation,
)
from code_visualizer.domain.module_paths import (
    PythonPathError,
    python_module_file_path,
    qualified_module_name,
)
from code_visualizer.domain.program_kinds import (
    CallableKind,
    LoopKind,
    MethodKind,
    ParallelMode,
    ParameterKind,
    ProgramModuleKind,
    SelectMode,
    SimpleKind,
    TransferKind,
)
from code_visualizer.domain.program_signatures import ParameterSpec
from code_visualizer.domain.python_symbols import PythonSymbolAllocator, python_identifiers
from code_visualizer.domain.transformation import OriginMap
from code_visualizer.generation.ir import (
    AssignmentIR,
    CallIR,
    ClassIR,
    DeclarationIR,
    DelayIR,
    FunctionIR,
    IfIR,
    InputIR,
    LoopIR,
    ModuleIR,
    NoteIR,
    Origin,
    OutputIR,
    ParallelIR,
    PassIR,
    PeriodIR,
    PythonProjectIR,
    RawStatementIR,
    RealtimeProcessIR,
    SelectIR,
    SilhouetteIR,
    SimpleStatementIR,
    StartTimerIR,
    StatementIR,
    SynchronizerIR,
    TransferIR,
    TryIR,
    WithIR,
)


class GenerationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SourceSpan:
    map_id: str
    file_path: str
    project_id: str
    semantic_id: str
    presentation_id: str | None
    field: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int


@dataclass(frozen=True, slots=True)
class GeneratedFile:
    path: str
    source: str
    spans: tuple[SourceSpan, ...]


@dataclass(frozen=True, slots=True)
class GeneratedProject:
    files: tuple[GeneratedFile, ...]
    invocation: InvocationSpec | None
    entrypoint_module: str | None
    origins: OriginMap | None = None
    launcher_path: str = "run_project.py"

    @property
    def entrypoint(self) -> str | None:
        """Display metadata; execution uses the complete invocation contract."""

        return self.invocation.identifier if self.invocation is not None else None

    def file(self, path: str) -> GeneratedFile:
        for item in self.files:
            if item.path == path:
                return item
        raise KeyError(path)

    @property
    def spans(self) -> tuple[SourceSpan, ...]:
        return tuple(span for item in self.files for span in item.spans)


def _authored_identifiers(value: object) -> frozenset[str]:
    """Reserve authored bindings and loads in every descendant lexical scope.

    A file-wide closure is intentionally conservative: generated globals cannot be
    shadowed by parameters, and generated locals cannot capture nested free loads.
    This does not infer bindings from display labels, comments, or docstrings.
    """
    if isinstance(value, str):
        return python_identifiers(value)
    if isinstance(value, Origin | NoteIR):
        return frozenset()
    if isinstance(value, FunctionIR):
        return _authored_identifiers((_signature(value), value.decorators, value.body))
    if isinstance(value, ClassIR):
        return _authored_identifiers(
            (value.identifier, value.arguments, value.decorators, value.type_parameters, value.body)
        )
    if isinstance(value, ModuleIR):
        return _authored_identifiers(value.body)
    if isinstance(value, tuple):
        return frozenset(name for item in value for name in _authored_identifiers(item))
    if is_dataclass(value) and not isinstance(value, type):
        return _authored_identifiers(tuple(getattr(value, field.name) for field in fields(value)))
    return frozenset()


class _Writer:
    def __init__(self, file_path: str, *, authored: object = ()) -> None:
        self.file_path = file_path
        self.lines: list[str] = []
        self.spans: list[SourceSpan] = []
        self.authored_names = _authored_identifiers(authored)
        self.symbols = PythonSymbolAllocator(self.authored_names)
        self._scope: tuple[str, ...] = ()
        self._scope_is_class = False
        self._scope_parents: dict[tuple[str, ...], tuple[str, ...]] = {}
        self._role_names: dict[tuple[tuple[str, ...], str], str] = {}

    def unique_name(self, base: str) -> str:
        return self.symbols.allocate(base)

    def symbol(self, role: str, preferred: str, *, module_scope: bool = False) -> str:
        key = (() if module_scope else self._scope, role)
        if key not in self._role_names:
            self._role_names[key] = self.unique_name(preferred)
        return self._role_names[key]

    @contextmanager
    def lexical_scope(self, identity: str, *, class_scope: bool = False) -> Iterator[None]:
        previous = self._scope
        previous_is_class = self._scope_is_class
        self._scope = (*previous, identity)
        self._scope_is_class = class_scope
        # A class's namespace is not an enclosing lexical binding scope for its
        # methods/nested classes. An enclosing function still can supply closures.
        self._scope_parents[self._scope] = (
            self._scope_parents[previous] if previous_is_class else previous
        )
        try:
            yield
        finally:
            self._scope = previous
            self._scope_is_class = previous_is_class

    def reference(self, role: str, preferred: str) -> str:
        scope = self._scope
        while True:
            if (scope, role) in self._role_names:
                return self._role_names[(scope, role)]
            if not scope:
                return self.symbol(role, preferred, module_scope=True)
            scope = self._scope_parents[scope]

    def runtime_name(self, name: str) -> str:
        return self.symbol(f"runtime:{name}", name, module_scope=True)

    def line(self, text: str = "", origin: Origin | None = None) -> None:
        line_number = len(self.lines) + 1
        self.lines.append(text)
        if origin is not None:
            self._span(origin, line_number, line_number, len(text))

    def source(self, source: str, *, indent: str = "", origin: Origin) -> None:
        source_lines = source.splitlines()
        if not source_lines:
            return
        start = len(self.lines) + 1
        for line in source_lines:
            self.lines.append(f"{indent}{line}" if line.strip() else "")
        self._span(origin, start, len(self.lines), len(self.lines[-1]))

    def blank(self) -> None:
        if self.lines and self.lines[-1] != "":
            self.lines.append("")

    def _span(self, origin: Origin, start: int, end: int, end_column: int) -> None:
        ordinal = len(self.spans)
        identity = "\0".join(
            (
                self.file_path,
                origin.project_id,
                origin.semantic_id,
                origin.presentation_id or "",
                origin.field,
                str(ordinal),
            )
        )
        map_id = "map_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        self.spans.append(
            SourceSpan(
                map_id=map_id,
                file_path=self.file_path,
                project_id=origin.project_id,
                semantic_id=origin.semantic_id,
                presentation_id=origin.presentation_id,
                field=origin.field,
                start_line=start,
                start_column=0,
                end_line=end,
                end_column=end_column,
            )
        )

    def finish(self) -> GeneratedFile:
        source = "\n".join(self.lines).rstrip() + "\n"
        _verify_python(source, self.file_path)
        return GeneratedFile(self.file_path, source, tuple(self.spans))


def _verify_python(source: str, path: str) -> None:
    try:
        ast.parse(source, filename=path)
        compile(source, path, "exec")
    except SyntaxError as exc:
        raise GenerationError(f"{path}:{exc.lineno}:{exc.offset}: {exc.msg}") from exc


def _docstring_source(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return f'"""{escaped}"""'


def _parameter_source(parameter: ParameterSpec) -> str:
    prefix = ""
    if parameter.kind is ParameterKind.VAR_POSITIONAL:
        prefix = "*"
    elif parameter.kind is ParameterKind.VAR_KEYWORD:
        prefix = "**"
    result = f"{prefix}{parameter.name}"
    if parameter.annotation:
        result += f": {parameter.annotation}"
    if parameter.default is not None:
        result += f" = {parameter.default}"
    return result


def _signature(function: FunctionIR) -> str:
    parameters: list[str] = []
    items = function.parameters
    last_positional_only = max(
        (index for index, item in enumerate(items) if item.kind is ParameterKind.POSITIONAL_ONLY),
        default=-1,
    )
    has_var_positional = any(item.kind is ParameterKind.VAR_POSITIONAL for item in items)
    inserted_keyword_marker = False
    for index, parameter in enumerate(items):
        if (
            parameter.kind is ParameterKind.KEYWORD_ONLY
            and not has_var_positional
            and not inserted_keyword_marker
        ):
            parameters.append("*")
            inserted_keyword_marker = True
        parameters.append(_parameter_source(parameter))
        if index == last_positional_only:
            parameters.append("/")
    prefix = "async " if function.kind in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR} else ""
    type_parameters = f"[{', '.join(function.type_parameters)}]" if function.type_parameters else ""
    result = f"{prefix}def {function.identifier}{type_parameters}({', '.join(parameters)})"
    if function.return_annotation:
        result += f" -> {function.return_annotation}"
    return result + ":"


def _safe_identifier(value: str, *, fallback: str) -> str:
    candidate = re.sub(r"\W+", "_", value.strip().lower()).strip("_")
    if not candidate:
        candidate = fallback
    if candidate[0].isdigit():
        candidate = f"{fallback}_{candidate}"
    return candidate


def _timer_name(writer: _Writer, timer: str, *, reference: bool = False) -> str:
    resolve = writer.reference if reference else writer.symbol
    return resolve(f"timer:{timer}", f"_cv_timer_{_safe_identifier(timer, fallback='timer')}")


def _declare_timers(writer: _Writer, declarations: tuple[DeclarationIR, ...]) -> None:
    """Determine scope-local timer assignments before resolving any timer read."""
    for item in declarations:
        if isinstance(item, FunctionIR | ClassIR | ParallelIR):
            continue
        if isinstance(item, StartTimerIR | PeriodIR):
            _timer_name(writer, item.timer)
        for group in _nested_statement_groups(item):
            _declare_timers(writer, group)


def _emit_optional_else(
    writer: _Writer,
    statements: tuple[StatementIR, ...],
    *,
    depth: int,
    origin: Origin,
) -> None:
    if statements:
        writer.line(f"{'    ' * depth}else:", origin)
        _emit_statements(writer, statements, depth=depth + 1)


def _emit_statements(
    writer: _Writer,
    statements: tuple[StatementIR, ...],
    *,
    depth: int,
) -> None:
    indent = "    " * depth
    for statement in statements:
        if isinstance(statement, PassIR):
            writer.line(f"{indent}pass", statement.origin)
        elif isinstance(statement, RawStatementIR):
            writer.source(statement.source, indent=indent, origin=statement.origin)
        elif isinstance(statement, OutputIR):
            options: list[str] = []
            if statement.destination:
                options.append(f"file={statement.destination}")
            if statement.end:
                options.append(f"end={statement.end}")
            arguments = ", ".join((statement.expression, *options))
            writer.line(f"{indent}print({arguments})", statement.origin)
        elif isinstance(statement, AssignmentIR):
            target = statement.target
            if statement.annotation:
                target += f": {statement.annotation}"
            writer.line(
                f"{indent}{target} {statement.operator} {statement.value}",
                statement.origin,
            )
        elif isinstance(statement, IfIR):
            test = (
                statement.condition if statement.preferred_truth else f"not ({statement.condition})"
            )
            writer.line(f"{indent}if {test}:", statement.origin)
            preferred = (
                statement.true_branch if statement.preferred_truth else statement.false_branch
            )
            secondary = (
                statement.false_branch if statement.preferred_truth else statement.true_branch
            )
            _emit_statements(writer, preferred, depth=depth + 1)
            writer.line(f"{indent}else:", statement.origin)
            _emit_statements(writer, secondary, depth=depth + 1)
        elif isinstance(statement, TransferIR):
            expression = statement.expression.strip()
            if statement.kind is TransferKind.RETURN:
                source = "return" + (f" {expression}" if expression else "")
            elif statement.kind is TransferKind.RAISE:
                source = "raise" + (f" {expression}" if expression else "")
                if statement.cause:
                    source += f" from {statement.cause}"
            elif statement.kind is TransferKind.YIELD:
                source = "yield" + (f" {expression}" if expression else "")
            elif statement.kind is TransferKind.YIELD_FROM:
                source = f"yield from {expression}"
            elif statement.kind is TransferKind.BREAK:
                source = "break"
            else:
                source = "continue"
            writer.line(f"{indent}{source}", statement.origin)
        elif isinstance(statement, SimpleStatementIR):
            if statement.kind is SimpleKind.PASS:
                source = "pass"
            elif statement.kind is SimpleKind.DELETE:
                source = f"del {statement.source}"
            elif statement.kind is SimpleKind.GLOBAL:
                source = f"global {statement.source}"
            elif statement.kind is SimpleKind.NONLOCAL:
                source = f"nonlocal {statement.source}"
            elif statement.kind is SimpleKind.ASSERT:
                source = f"assert {statement.source}"
                if statement.secondary:
                    source += f", {statement.secondary}"
            else:
                source = statement.source
            writer.source(source, indent=indent, origin=statement.origin)
        elif isinstance(statement, CallIR):
            call = f"await {statement.expression}" if statement.awaited else statement.expression
            if statement.result_target:
                call = f"{statement.result_target} = {call}"
            writer.line(f"{indent}{call}", statement.origin)
        elif isinstance(statement, InputIR):
            expression = f"input({statement.prompt})"
            if statement.converter:
                expression = f"{statement.converter}({expression})"
            target = statement.target
            if statement.annotation:
                target += f": {statement.annotation}"
            writer.line(f"{indent}{target} = {expression}", statement.origin)
        elif isinstance(statement, DelayIR):
            duration = f"max(0.0, float({statement.seconds}))"
            if statement.asynchronous:
                writer.line(
                    f"{indent}await {writer.runtime_name('_cv_asyncio')}.sleep({duration})",
                    statement.origin,
                )
            else:
                writer.line(
                    f"{indent}{writer.runtime_name('_cv_time')}.sleep({duration})", statement.origin
                )
        elif isinstance(statement, StartTimerIR):
            writer.line(
                f"{indent}{_timer_name(writer, statement.timer)} = "
                f"{writer.runtime_name('_cv_time')}.perf_counter()",
                statement.origin,
            )
        elif isinstance(statement, PeriodIR):
            timer = _timer_name(writer, statement.timer)
            deadline = writer.unique_name(
                f"_cv_{_safe_identifier(statement.timer, fallback='timer')}_deadline"
            )
            writer.line(
                f"{indent}{deadline} = {timer} + ({statement.seconds})",
                statement.origin,
            )
            remaining = f"max(0.0, {deadline} - {writer.runtime_name('_cv_time')}.perf_counter())"
            if statement.asynchronous:
                writer.line(
                    f"{indent}await {writer.runtime_name('_cv_asyncio')}.sleep({remaining})",
                    statement.origin,
                )
            else:
                writer.line(
                    f"{indent}{writer.runtime_name('_cv_time')}.sleep({remaining})",
                    statement.origin,
                )
            writer.line(f"{indent}{timer} = {deadline}", statement.origin)
        elif isinstance(statement, RealtimeProcessIR):
            prefix = "await " if statement.awaited else ""
            writer.line(f"{indent}{prefix}{statement.call}", statement.origin)
        elif isinstance(statement, NoteIR):
            lines = statement.text.splitlines() or [""]
            writer.source(
                "\n".join(f"# {line}" if line else "#" for line in lines),
                indent=indent,
                origin=statement.origin,
            )
            writer.line(f"{indent}pass", statement.origin)
        elif isinstance(statement, SelectIR):
            if statement.mode is SelectMode.MATCH:
                writer.line(f"{indent}match {statement.expression}:", statement.origin)
                for case in statement.cases:
                    guard = f" if {case.guard}" if case.guard else ""
                    writer.line(f"{indent}    case {case.pattern}{guard}:", case.origin)
                    _emit_statements(writer, case.body, depth=depth + 2)
            elif statement.cases:
                for index, case in enumerate(statement.cases):
                    if case.is_default:
                        keyword = "if True" if index == 0 else "else"
                        suffix = ":"
                    else:
                        keyword = "if" if index == 0 else "elif"
                        suffix = f" {case.condition}:"
                    writer.line(f"{indent}{keyword}{suffix}", case.origin)
                    _emit_statements(writer, case.body, depth=depth + 1)
            else:
                writer.line(f"{indent}pass", statement.origin)
        elif isinstance(statement, LoopIR):
            if statement.kind is LoopKind.WHILE:
                writer.line(f"{indent}while {statement.condition}:", statement.origin)
                _emit_statements(writer, statement.body, depth=depth + 1)
                _emit_optional_else(
                    writer,
                    statement.else_body,
                    depth=depth,
                    origin=statement.origin,
                )
            elif statement.kind is LoopKind.DO_FIRST:
                first = writer.unique_name("_cv_first_iteration")
                writer.line(f"{indent}{first} = True", statement.origin)
                writer.line(
                    f"{indent}while {first} or ({statement.condition}):",
                    statement.origin,
                )
                writer.line(f"{indent}    {first} = False", statement.origin)
                _emit_statements(writer, statement.body, depth=depth + 1)
                _emit_optional_else(
                    writer,
                    statement.else_body,
                    depth=depth,
                    origin=statement.origin,
                )
            elif statement.kind in {LoopKind.FOR, LoopKind.ASYNC_FOR}:
                prefix = "async " if statement.kind is LoopKind.ASYNC_FOR else ""
                writer.line(
                    f"{indent}{prefix}for {statement.target} in {statement.iterable}:",
                    statement.origin,
                )
                _emit_statements(writer, statement.body, depth=depth + 1)
                _emit_optional_else(
                    writer,
                    statement.else_body,
                    depth=depth,
                    origin=statement.origin,
                )
            elif statement.kind is LoopKind.WAIT:
                writer.line(f"{indent}while not ({statement.condition}):", statement.origin)
                _emit_statements(writer, statement.body, depth=depth + 1)
                writer.line(
                    f"{indent}    {writer.runtime_name('_cv_time')}.sleep"
                    f"(max(0.0, float({statement.delay_seconds})))",
                    statement.origin,
                )
                _emit_optional_else(
                    writer,
                    statement.else_body,
                    depth=depth,
                    origin=statement.origin,
                )
            else:
                work = writer.unique_name(
                    f"_cv_{_safe_identifier(statement.target, fallback='node')}_work"
                )
                if statement.kind is LoopKind.TREE_BFS:
                    writer.line(
                        f"{indent}{work} = {writer.runtime_name('_cv_deque')}"
                        f"({statement.iterable})",
                        statement.origin,
                    )
                    pop = "popleft()"
                else:
                    writer.line(
                        f"{indent}{work} = list(reversed(list({statement.iterable})))",
                        statement.origin,
                    )
                    pop = "pop()"
                writer.line(f"{indent}while {work}:", statement.origin)
                writer.line(
                    f"{indent}    {statement.target} = {work}.{pop}",
                    statement.origin,
                )
                _emit_statements(writer, statement.body, depth=depth + 1)
                children = f"({statement.children})({statement.target})"
                if statement.kind is LoopKind.TREE_BFS:
                    writer.line(f"{indent}    {work}.extend({children})", statement.origin)
                else:
                    writer.line(
                        f"{indent}    {work}.extend(reversed(list({children})))",
                        statement.origin,
                    )
                _emit_optional_else(
                    writer,
                    statement.else_body,
                    depth=depth,
                    origin=statement.origin,
                )
        elif isinstance(statement, WithIR):
            contexts = ", ".join(
                item.expression + (f" as {item.target}" if item.target else "")
                for item in statement.contexts
            )
            prefix = "async " if statement.asynchronous else ""
            writer.line(f"{indent}{prefix}with {contexts}:", statement.origin)
            _emit_statements(writer, statement.body, depth=depth + 1)
        elif isinstance(statement, TryIR):
            writer.line(f"{indent}try:", statement.origin)
            _emit_statements(writer, statement.body, depth=depth + 1)
            keyword = "except*" if statement.except_star else "except"
            for handler in statement.handlers:
                name = f" as {handler.name}" if handler.name else ""
                writer.line(
                    f"{indent}{keyword} {handler.exception}{name}:",
                    handler.origin,
                )
                _emit_statements(writer, handler.body, depth=depth + 1)
            if statement.else_body:
                writer.line(f"{indent}else:", statement.origin)
                _emit_statements(writer, statement.else_body, depth=depth + 1)
            if statement.finally_body:
                writer.line(f"{indent}finally:", statement.origin)
                _emit_statements(writer, statement.finally_body, depth=depth + 1)
        elif isinstance(statement, SynchronizerIR):
            timer = _timer_name(writer, statement.timer, reference=True)
            condition = (
                f"{writer.runtime_name('_cv_time')}.perf_counter() - {timer} "
                f"<= ({statement.deadline})"
            )
            if not statement.preferred_on_time:
                condition = f"not ({condition})"
            writer.line(f"{indent}if {condition}:", statement.origin)
            preferred = statement.on_time if statement.preferred_on_time else statement.on_timeout
            alternate = statement.on_timeout if statement.preferred_on_time else statement.on_time
            _emit_statements(writer, preferred, depth=depth + 1)
            writer.line(f"{indent}else:", statement.origin)
            _emit_statements(writer, alternate, depth=depth + 1)
        elif isinstance(statement, ParallelIR):
            names: list[str] = []
            for parallel_branch in statement.branches:
                base = f"_cv_{_safe_identifier(parallel_branch.name, fallback='process')}"
                name = writer.unique_name(base)
                names.append(name)
                async_prefix = "async " if statement.mode is ParallelMode.ASYNC else ""
                writer.line(f"{indent}{async_prefix}def {name}():", parallel_branch.origin)
                with writer.lexical_scope(name):
                    _declare_timers(writer, parallel_branch.body)
                    _emit_statements(writer, parallel_branch.body, depth=depth + 1)
            if statement.mode is ParallelMode.ASYNC:
                group = writer.unique_name("_cv_group")
                writer.line(
                    f"{indent}async with {writer.runtime_name('_cv_asyncio')}.TaskGroup() "
                    f"as {group}:",
                    statement.origin,
                )
                for name in names:
                    writer.line(f"{indent}    {group}.create_task({name}())", statement.origin)
            else:
                pool = writer.unique_name("_cv_pool")
                pending = writer.unique_name("_cv_pending")
                future = writer.unique_name("_cv_future")
                writer.line(
                    f"{indent}with {writer.runtime_name('_cv_futures')}.ThreadPoolExecutor"
                    f"(max_workers={len(names)}) as {pool}:",
                    statement.origin,
                )
                calls = ", ".join(f"{pool}.submit({name})" for name in names)
                writer.line(f"{indent}    {pending} = [{calls}]", statement.origin)
                writer.line(f"{indent}    for {future} in {pending}:", statement.origin)
                writer.line(f"{indent}        {future}.result()", statement.origin)
        elif isinstance(statement, SilhouetteIR):
            state = writer.unique_name(
                f"_{_safe_identifier(statement.identifier, fallback='silhouette')}_state"
            )
            writer.line(f"{indent}{state} = {statement.initial_name!r}", statement.origin)
            writer.line(f"{indent}while {state} is not None:", statement.origin)
            for index, silhouette_branch in enumerate(statement.branches):
                keyword = "if" if index == 0 else "elif"
                writer.line(
                    f"{indent}    {keyword} {state} == {silhouette_branch.name!r}:",
                    silhouette_branch.origin,
                )
                _emit_statements(writer, silhouette_branch.body, depth=depth + 2)
                writer.line(
                    f"{indent}        {state} = {silhouette_branch.target_name!r}",
                    silhouette_branch.origin,
                )
            writer.line(f"{indent}    else:", statement.origin)
            writer.line(
                f"{indent}        raise RuntimeError(f'Unknown {statement.display_name} state: "
                f"{{{state}!r}}')",
                statement.origin,
            )
        else:
            raise GenerationError(f"Unsupported IR statement {type(statement).__name__}")


def _nested_statement_groups(statement: StatementIR) -> tuple[tuple[StatementIR, ...], ...]:
    if isinstance(statement, IfIR):
        return (statement.true_branch, statement.false_branch)
    if isinstance(statement, SelectIR):
        return tuple(case.body for case in statement.cases)
    if isinstance(statement, LoopIR):
        return (statement.body, statement.else_body)
    if isinstance(statement, WithIR):
        return (statement.body,)
    if isinstance(statement, TryIR):
        return (
            statement.body,
            *(handler.body for handler in statement.handlers),
            statement.else_body,
            statement.finally_body,
        )
    if isinstance(statement, SynchronizerIR):
        return (statement.on_time, statement.on_timeout)
    if isinstance(statement, ParallelIR):
        return tuple(branch.body for branch in statement.branches)
    if isinstance(statement, SilhouetteIR):
        return tuple(branch.body for branch in statement.branches)
    return ()


def _runtime_features(declarations: tuple[DeclarationIR, ...]) -> frozenset[str]:
    features: set[str] = set()

    def walk(statements: tuple[StatementIR, ...]) -> None:
        for statement in statements:
            if isinstance(statement, (StartTimerIR, PeriodIR, SynchronizerIR)):
                features.add("time")
            elif isinstance(statement, DelayIR):
                features.add("asyncio" if statement.asynchronous else "time")
            elif isinstance(statement, (CallIR, RealtimeProcessIR)) and statement.awaited:
                features.add("asyncio")
            elif isinstance(statement, LoopIR):
                if statement.kind is LoopKind.ASYNC_FOR:
                    features.add("asyncio")
                    features.add("async_iter")
                elif statement.kind is LoopKind.WAIT:
                    features.add("time")
                elif statement.kind is LoopKind.TREE_BFS:
                    features.add("deque")
            elif isinstance(statement, WithIR):
                if statement.asynchronous:
                    features.add("asyncio")
                if any("nullcontext" in item.expression for item in statement.contexts):
                    features.add("nullcontext")
            elif isinstance(statement, ParallelIR):
                features.add("asyncio" if statement.mode is ParallelMode.ASYNC else "futures")
            for group in _nested_statement_groups(statement):
                walk(group)

    def declarations_walk(items: tuple[DeclarationIR, ...]) -> None:
        for item in items:
            if isinstance(item, ClassIR):
                declarations_walk(item.body)
            elif isinstance(item, FunctionIR):
                walk(item.body)
            else:
                walk((item,))

    declarations_walk(declarations)
    return frozenset(features)


def _emit_runtime_imports(writer: _Writer, body: tuple[DeclarationIR, ...]) -> bool:
    features = _runtime_features(body)

    def preserve_authored_reference(provided_name: str, implementation_name: str) -> None:
        # These names already form the initial Python environment of existing
        # authored expressions/default recipes. Preserve ordinary authored lookup
        # and subsequent shadowing, while generated operations use their own alias.
        if provided_name in writer.authored_names and provided_name != implementation_name:
            writer.line(f"{provided_name} = {implementation_name}")

    def dependency(provided_name: str, source: str) -> None:
        alias = writer.runtime_name(provided_name)
        writer.line(f"{source} as {alias}")
        preserve_authored_reference(provided_name, alias)

    if "asyncio" in features:
        dependency("_cv_asyncio", "import asyncio")
    if "futures" in features:
        dependency("_cv_futures", "import concurrent.futures")
    if "time" in features:
        dependency("_cv_time", "import time")
    if "deque" in features:
        dependency("_cv_deque", "from collections import deque")
    if "nullcontext" in features:
        dependency("nullcontext", "from contextlib import nullcontext")
    if "async_iter" in features:
        helper = writer.runtime_name("_cv_async_iter")
        values = writer.unique_name("_cv_values")
        value = writer.unique_name("_cv_value")
        writer.line(f"async def {helper}({values}):")
        writer.line(f"    for {value} in {values}:")
        writer.line(f"        yield {value}")
        preserve_authored_reference("_cv_async_iter", helper)
    return bool(features)


def _emit_function(writer: _Writer, function: FunctionIR, *, depth: int = 0) -> None:
    indent = "    " * depth
    if function.method_kind is MethodKind.CLASS:
        writer.line(f"{indent}@classmethod", function.signature_origin)
    elif function.method_kind is MethodKind.STATIC:
        writer.line(f"{indent}@staticmethod", function.signature_origin)
    for decorator in function.decorators:
        writer.line(f"{indent}@{decorator}", function.signature_origin)
    writer.line(f"{indent}{_signature(function)}", function.signature_origin)
    if function.docstring:
        writer.source(
            _docstring_source(function.docstring),
            indent=f"{indent}    ",
            origin=Origin(
                function.signature_origin.project_id,
                function.callable_id,
                "docstring",
                function.presentation_id,
            ),
        )
    with writer.lexical_scope(function.callable_id):
        _declare_timers(writer, function.body)
        _emit_statements(writer, function.body, depth=depth + 1)
    writer.blank()


def _emit_declarations(
    writer: _Writer, declarations: tuple[DeclarationIR, ...], *, depth: int = 0
) -> None:
    indent = "    " * depth
    for item in declarations:
        if isinstance(item, FunctionIR):
            _emit_function(writer, item, depth=depth)
        elif isinstance(item, ClassIR):
            for decorator in item.decorators:
                writer.line(f"{indent}@{decorator}", item.origin)
            parameters = f"[{', '.join(item.type_parameters)}]" if item.type_parameters else ""
            arguments = f"({item.arguments})" if item.arguments is not None else ""
            writer.line(f"{indent}class {item.identifier}{parameters}{arguments}:", item.origin)
            if item.docstring:
                writer.source(
                    _docstring_source(item.docstring), indent=indent + "    ", origin=item.origin
                )
            if item.body:
                with writer.lexical_scope(item.origin.semantic_id, class_scope=True):
                    _declare_timers(writer, item.body)
                    _emit_declarations(writer, item.body, depth=depth + 1)
            if not item.docstring and all(isinstance(child, NoteIR) for child in item.body):
                writer.line(indent + "    pass", item.origin)
            writer.blank()
        elif isinstance(item, NoteIR):
            writer.source(
                "\n".join(f"# {line}" if line else "#" for line in item.text.splitlines() or [""]),
                indent=indent,
                origin=item.origin,
            )
        else:
            _emit_statements(writer, (item,), depth=depth)


def _emit_declaration_preamble(
    writer: _Writer, body: tuple[DeclarationIR, ...], *, docstring_present: bool = False
) -> int:
    """Keep authored docstrings/comments/future imports ahead of generated helpers."""
    head = 0
    for item in body:
        if isinstance(item, NoteIR):
            _emit_declarations(writer, (item,))
            head += 1
            continue
        if not isinstance(item, RawStatementIR):
            break
        parsed = ast.parse(item.source).body
        if (
            not docstring_present
            and len(parsed) == 1
            and isinstance(parsed[0], ast.Expr)
            and isinstance(parsed[0].value, ast.Constant)
            and isinstance(parsed[0].value.value, str)
        ):
            _emit_declarations(writer, (item,))
            docstring_present = True
            head += 1
            continue
        if not parsed or not all(
            isinstance(node, ast.ImportFrom) and node.module == "__future__" for node in parsed
        ):
            break
        _emit_declarations(writer, (item,))
        head += 1
    return head


def _emit_module_content(writer: _Writer, module: ModuleIR) -> None:
    _declare_timers(writer, module.body)
    if module.docstring:
        writer.source(
            _docstring_source(module.docstring), origin=replace(module.origin, field="docstring")
        )
        writer.blank()
    head = _emit_declaration_preamble(writer, module.body, docstring_present=bool(module.docstring))
    if _emit_runtime_imports(writer, module.body):
        writer.blank()
    _emit_declarations(writer, module.body[head:])


def module_file_path(project: PythonProjectIR, module_path: str) -> str:
    try:
        kind = next(
            (item.kind for item in project.modules if item.path == module_path),
            ProgramModuleKind.MODULE,
        )
        return python_module_file_path(project.package, module_path, kind=kind)
    except PythonPathError as exc:
        raise GenerationError(f"Unsafe Python module path {module_path!r}: {exc}") from exc


def module_qualified_name(project: PythonProjectIR, module_path: str) -> str:
    try:
        kind = next(
            (item.kind for item in project.modules if item.path == module_path),
            ProgramModuleKind.MODULE,
        )
        return qualified_module_name(project.package, module_path, kind=kind)
    except PythonPathError as exc:
        raise GenerationError(f"Invalid Python module path {module_path!r}: {exc}") from exc


def _emit_entrypoint_call(
    writer: _Writer,
    *,
    invocation: InvocationSpec,
    origin: Origin,
    imported_alias: str | None = None,
    symbols: InvocationSymbols | None = None,
) -> None:
    for line in render_invocation(
        invocation,
        imported_alias=imported_alias,
        indent="    ",
        include_import=False,
        symbols=symbols,
    ).splitlines():
        writer.line(line, origin)


def emit_modules(project: PythonProjectIR) -> tuple[GeneratedFile, ...]:
    """Render each canonical Python module once for files, previews, and execution."""
    result = []
    for module in project.modules:
        writer = _Writer(module_file_path(project, module.path), authored=module)
        _emit_module_content(writer, module)
        result.append(writer.finish())
    return tuple(result)


def emit_project(
    project: PythonProjectIR, *, _rendered_modules: tuple[GeneratedFile, ...] | None = None
) -> GeneratedProject:
    files: list[GeneratedFile] = []
    init_paths: set[str] = set()
    module_files: dict[str, str] = {}
    module_names = tuple(module.path for module in project.modules)
    if len({name.casefold() for name in module_names}) != len(module_names):
        raise GenerationError("Python modules and packages must have distinct import names")
    for module in project.modules:
        module_name = module.path
        if module_name.split(".")[-1] == "__init__":
            raise GenerationError("Use an explicit PACKAGE module for an authored initializer")
        if module.kind is ProgramModuleKind.PACKAGE:
            continue
        if any(
            other.casefold() != module_name.casefold()
            and other.casefold().startswith(f"{module_name.casefold()}.")
            for other in module_names
        ):
            raise GenerationError(
                f"Module {module_name!r} is also a package prefix; use a leaf module path"
            )
    rendered_modules = emit_modules(project) if _rendered_modules is None else _rendered_modules
    for module, rendered in zip(project.modules, rendered_modules, strict=True):
        file_path = module_file_path(project, module.path)
        file_key = file_path.casefold()
        previous = module_files.get(file_key)
        if previous is not None:
            raise GenerationError(
                f"Module paths {previous!r} and {module.path!r} map to the same output file"
            )
        module_files[file_key] = module.path
        parts = file_path.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            init_paths.add("/".join((*parts[:index], "__init__.py")))
        files.append(rendered)
    for path in sorted(init_paths):
        if path.casefold() in module_files:
            continue
        writer = _Writer(path)
        writer.line('"""Generated package; regenerate from Code Visualizer."""')
        files.append(writer.finish())

    launcher = _Writer("run_project.py", authored=project.startup)
    _declare_timers(launcher, project.startup)
    startup_head = _emit_declaration_preamble(launcher, project.startup)
    _emit_runtime_imports(launcher, project.startup)
    imported_alias: str | None = None
    symbols: InvocationSymbols | None = None
    if project.entrypoint is not None:
        entrypoint = project.entrypoint
        imported_alias = launcher.unique_name("_entrypoint")
        symbols = invocation_symbols(
            entrypoint.invocation, imported_alias=imported_alias, allocator=launcher.symbols
        )
        if entrypoint.invocation.kind in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR}:
            launcher.line(f"import asyncio as {symbols.asyncio_alias}")
        qualified = module_qualified_name(project, entrypoint.module)
        imported_name = (
            entrypoint.invocation.owning_class or entrypoint.invocation.identifier
        ).split(".")[0]
        launcher.line(
            f"from {qualified} import {imported_name} as {imported_alias}", entrypoint.origin
        )
        launcher.blank()
    elif project.modules:
        importlib_alias = launcher.unique_name("_cv_importlib")
        launcher.line(f"import importlib as {importlib_alias}")
        for module in project.modules:
            name = module_qualified_name(project, module.path)
            launcher.line(f"{importlib_alias}.import_module({name!r})", module.origin)
    _emit_declarations(launcher, project.startup[startup_head:])
    launcher.line('if __name__ == "__main__":')
    if project.entrypoint is None:
        launcher.line("    pass")
    else:
        _emit_entrypoint_call(
            launcher,
            invocation=project.entrypoint.invocation,
            origin=project.entrypoint.origin,
            imported_alias=imported_alias,
            symbols=symbols,
        )
    files.append(launcher.finish())
    return GeneratedProject(
        tuple(sorted(files, key=lambda item: item.path)),
        project.entrypoint.invocation if project.entrypoint else None,
        project.entrypoint.module if project.entrypoint else None,
    )


def emit_combined(
    project: PythonProjectIR,
    *,
    include_main: bool,
    file_path: str = "project.preview.txt",
    _rendered_modules: tuple[GeneratedFile, ...] | None = None,
) -> GeneratedFile:
    """Present emitted files as readable text; this is never an execution artifact."""
    emitted = emit_project(project, _rendered_modules=_rendered_modules)
    writer = _Writer(file_path)
    writer.line("# Read-only Python project preview. Execute run_project.py from the emitted tree.")
    for rendered in emitted.files:
        if not include_main and rendered.path == emitted.launcher_path:
            continue
        writer.blank()
        writer.line(f"# File: {rendered.path}")
        offset = len(writer.lines)
        for line in rendered.source.splitlines():
            writer.line(line)
        for span in rendered.spans:
            writer._span(
                Origin(span.project_id, span.semantic_id, span.field, span.presentation_id),
                span.start_line + offset,
                span.end_line + offset,
                span.end_column,
            )
    # A preview can contain multiple future-import sections and is intentionally
    # not compiled. Its individual files were already compiled by emit_project.
    return GeneratedFile(file_path, "\n".join(writer.lines).rstrip() + "\n", tuple(writer.spans))
