"""Lower canonical ProgramModel semantics into the typed Python IR."""

from __future__ import annotations

import ast
from collections.abc import Iterator, Mapping
from unicodedata import normalize

from code_visualizer.domain.expression import (
    AttributeExpression,
    ExpressionNode,
    SymbolReferenceExpression,
    UnparsedPythonExpression,
    expression_children,
    render_expression_tree,
)
from code_visualizer.domain.invocation import bind_invocation
from code_visualizer.domain.invocation_arguments import InvocationArguments
from code_visualizer.domain.program import (
    ProgramAction,
    ProgramAssignment,
    ProgramCall,
    ProgramClass,
    ProgramDeclaration,
    ProgramDelay,
    ProgramEntryPoint,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramIf,
    ProgramImport,
    ProgramInput,
    ProgramLoop,
    ProgramModule,
    ProgramNote,
    ProgramOutput,
    ProgramParallel,
    ProgramParameter,
    ProgramPeriod,
    ProgramRealtimeProcess,
    ProgramSelect,
    ProgramSequence,
    ProgramSilhouette,
    ProgramSimpleStatement,
    ProgramStartTimer,
    ProgramStatement,
    ProgramSynchronizer,
    ProgramTransfer,
    ProgramTry,
    ProgramTypeAlias,
    ProgramWith,
    iter_program_nodes,
    program_expressions,
)
from code_visualizer.domain.program_bindings import resolve_linked_callable
from code_visualizer.domain.program_index import ProgramFunctionLocation, program_function_locations
from code_visualizer.domain.program_kinds import MethodKind
from code_visualizer.domain.program_signatures import ParameterSpec
from code_visualizer.domain.project import Project
from code_visualizer.generation.ir import (
    AssignmentIR,
    CallIR,
    ClassIR,
    ContextItemIR,
    DeclarationIR,
    DelayIR,
    EntryPointIR,
    ExceptionHandlerIR,
    FunctionIR,
    IfIR,
    InputIR,
    LoopIR,
    ModuleIR,
    NoteIR,
    Origin,
    OutputIR,
    ParallelBranchIR,
    ParallelIR,
    PassIR,
    PeriodIR,
    PythonProjectIR,
    RawStatementIR,
    RealtimeProcessIR,
    SelectCaseIR,
    SelectIR,
    SilhouetteBranchIR,
    SilhouetteIR,
    SimpleStatementIR,
    StartTimerIR,
    StatementIR,
    SynchronizerIR,
    TransferIR,
    TryIR,
    WithIR,
)


def _origin(
    project: Project,
    diagram: str | None,
    semantic_id: str,
    field: str,
) -> Origin:
    return Origin(project.id, semantic_id, field, diagram)


def _program_call_expression(
    project: Project,
    owner: ProgramFunction | ProgramModule | ProgramClass | ProgramEntryPoint | None,
    statement: ProgramCall,
) -> str:
    if statement.target_function_id is None:
        return statement.expression.source
    model = project.program_model
    target = model.function(statement.target_function_id)
    if target is None:
        return statement.expression.source
    callable_name = resolve_linked_callable(model, owner, target) if owner is not None else None
    if callable_name is None:
        return statement.expression.source
    return f"{callable_name}({statement.arguments.source})"


def _lower_program_statement(
    project: Project,
    diagram: str | None,
    owner: ProgramFunction | ProgramModule | ProgramClass | ProgramEntryPoint | None,
    atom: ProgramStatement,
) -> StatementIR:
    if isinstance(atom, ProgramAction):
        return RawStatementIR(atom.source.source, _origin(project, diagram, atom.id, "source"))
    if isinstance(atom, ProgramOutput):
        return OutputIR(
            atom.expression.source,
            (atom.destination.source if atom.destination is not None else None),
            (atom.end.source if atom.end is not None else None),
            _origin(project, diagram, atom.id, "expression"),
        )
    if isinstance(atom, ProgramAssignment):
        return AssignmentIR(
            atom.target.source,
            atom.value.source,
            (atom.annotation.source if atom.annotation is not None else None),
            atom.operator,
            _origin(project, diagram, atom.id, "value"),
        )
    if isinstance(atom, ProgramIf):
        return IfIR(
            atom.condition.source,
            _lower_program_sequence(project, diagram, owner, atom.true_branch),
            _lower_program_sequence(project, diagram, owner, atom.false_branch),
            atom.preferred_truth,
            _origin(project, diagram, atom.id, "condition"),
        )
    if isinstance(atom, ProgramTransfer):
        return TransferIR(
            atom.transfer_kind,
            (atom.expression.source if atom.expression is not None else ""),
            (atom.cause.source if atom.cause is not None else None),
            _origin(project, diagram, atom.id, "expression"),
        )
    if isinstance(atom, ProgramSimpleStatement):
        return SimpleStatementIR(
            atom.statement_kind,
            atom.source.source,
            (atom.secondary.source if atom.secondary is not None else None),
            _origin(project, diagram, atom.id, "source"),
        )
    if isinstance(atom, ProgramCall):
        return CallIR(
            _program_call_expression(project, owner, atom),
            atom.awaited,
            (atom.result_target.source if atom.result_target is not None else None),
            _origin(
                project,
                diagram,
                atom.id,
                "target_function_id" if atom.target_function_id else "expression",
            ),
        )
    if isinstance(atom, ProgramInput):
        return InputIR(
            atom.target.source,
            atom.prompt.source,
            (atom.converter.source if atom.converter is not None else None),
            (atom.annotation.source if atom.annotation is not None else None),
            _origin(project, diagram, atom.id, "prompt"),
        )
    if isinstance(atom, ProgramDelay):
        return DelayIR(
            atom.seconds.source,
            atom.asynchronous,
            _origin(project, diagram, atom.id, "seconds"),
        )
    if isinstance(atom, ProgramStartTimer):
        return StartTimerIR(atom.timer, _origin(project, diagram, atom.id, "timer"))
    if isinstance(atom, ProgramPeriod):
        return PeriodIR(
            atom.timer,
            atom.seconds.source,
            atom.asynchronous,
            _origin(project, diagram, atom.id, "seconds"),
        )
    if isinstance(atom, ProgramRealtimeProcess):
        return RealtimeProcessIR(
            atom.call.source,
            atom.awaited,
            _origin(project, diagram, atom.id, "call"),
        )
    if isinstance(atom, ProgramNote):
        return NoteIR(
            atom.text,
            atom.placement.value,
            _origin(project, diagram, atom.id, "text"),
        )
    if isinstance(atom, ProgramSelect):
        return SelectIR(
            atom.expression.source,
            tuple(
                SelectCaseIR(
                    case.id,
                    case.label,
                    case.condition.source,
                    case.pattern.source,
                    (case.guard.source if case.guard is not None else None),
                    case.is_default,
                    _lower_program_sequence(project, diagram, owner, case.body),
                    _origin(project, diagram, case.id, "condition"),
                )
                for case in atom.cases
            ),
            atom.mode,
            atom.preferred_case_id,
            _origin(project, diagram, atom.id, "expression"),
        )
    if isinstance(atom, ProgramLoop):
        return LoopIR(
            atom.loop_kind,
            _lower_program_sequence(project, diagram, owner, atom.body),
            _lower_program_sequence(project, diagram, owner, atom.else_body, empty_pass=False),
            atom.condition.source,
            atom.target.source,
            atom.iterable.source,
            atom.children.source,
            atom.delay_seconds.source,
            _origin(project, diagram, atom.id, "loop"),
        )
    if isinstance(atom, ProgramWith):
        return WithIR(
            tuple(
                ContextItemIR(
                    item.expression.source,
                    (item.target.source if item.target is not None else None),
                    _origin(project, diagram, item.id, "expression"),
                )
                for item in atom.contexts
            ),
            _lower_program_sequence(project, diagram, owner, atom.body),
            atom.asynchronous,
            _origin(project, diagram, atom.id, "contexts"),
        )
    if isinstance(atom, ProgramTry):
        return TryIR(
            _lower_program_sequence(project, diagram, owner, atom.body),
            tuple(
                ExceptionHandlerIR(
                    (handler.exception.source if handler.exception is not None else ""),
                    (handler.name.source if handler.name is not None else None),
                    _lower_program_sequence(project, diagram, owner, handler.body),
                    _origin(project, diagram, handler.id, "exception"),
                )
                for handler in atom.handlers
            ),
            _lower_program_sequence(project, diagram, owner, atom.else_body, empty_pass=False),
            _lower_program_sequence(project, diagram, owner, atom.finally_body, empty_pass=False),
            atom.except_star,
            _origin(project, diagram, atom.id, "try"),
        )
    if isinstance(atom, ProgramSynchronizer):
        return SynchronizerIR(
            atom.timer,
            atom.deadline.source,
            _lower_program_sequence(project, diagram, owner, atom.on_time),
            _lower_program_sequence(project, diagram, owner, atom.on_timeout),
            atom.preferred_on_time,
            _origin(project, diagram, atom.id, "deadline"),
        )
    if isinstance(atom, ProgramParallel):
        return ParallelIR(
            tuple(
                ParallelBranchIR(
                    branch.name,
                    _lower_program_sequence(project, diagram, owner, branch.body),
                    _origin(project, diagram, branch.id, "name"),
                )
                for branch in atom.branches
            ),
            atom.mode,
            _origin(project, diagram, atom.id, "branches"),
        )
    if isinstance(atom, ProgramSilhouette):
        branch_names = {branch.id: branch.name for branch in atom.branches}
        return SilhouetteIR(
            atom.display_name,
            atom.identifier,
            tuple(
                SilhouetteBranchIR(
                    branch.name,
                    _lower_program_sequence(project, diagram, owner, branch.body),
                    branch_names.get(branch.target_branch_id)
                    if branch.target_branch_id is not None
                    else None,
                    _origin(project, diagram, branch.id, "name"),
                )
                for branch in atom.branches
            ),
            branch_names.get(atom.initial_branch_id, atom.initial_branch_id),
            _origin(project, diagram, atom.id, "identifier"),
        )
    raise TypeError(f"Unsupported program statement {type(atom).__name__}")


def _lower_program_sequence(
    project: Project,
    diagram: str | None,
    owner: ProgramFunction | ProgramModule | ProgramClass | ProgramEntryPoint | None,
    sequence: ProgramSequence,
    *,
    empty_pass: bool = True,
) -> tuple[StatementIR, ...]:
    if not sequence.statements:
        return (PassIR(_origin(project, diagram, sequence.id, "body")),) if empty_pass else ()
    return tuple(
        _lower_program_statement(project, diagram, owner, statement)
        for statement in sequence.statements
    )


def _lower_parameter(parameter: ProgramParameter) -> ParameterSpec:
    return ParameterSpec(
        parameter.name,
        parameter.kind,
        parameter.annotation.source if parameter.annotation is not None else None,
        parameter.default.source if parameter.default is not None else None,
    )


def _lower_program_function(
    project: Project,
    function: ProgramFunction,
    diagram: str | None,
    location: ProgramFunctionLocation | None,
) -> FunctionIR:
    view = next(
        (
            item
            for item in project.drakon_views
            if item.function_id == function.id and (diagram is None or item.document_id == diagram)
        ),
        None,
    )
    presentation_id = view.document_id if view is not None else None
    return FunctionIR(
        callable_id=function.id,
        presentation_id=presentation_id,
        identifier=function.identifier,
        display_name=function.display_name,
        kind=function.kind,
        parameters=tuple(_lower_parameter(item) for item in function.parameters),
        return_annotation=(
            function.return_annotation.source if function.return_annotation is not None else None
        ),
        decorators=tuple(item.source for item in function.decorators),
        docstring=function.docstring,
        module=location.module.path if location is not None else "",
        owning_class=location.class_name if location is not None else None,
        method_kind=function.method_kind,
        body=_lower_program_sequence(project, presentation_id, function, function.body),
        signature_origin=Origin(
            project.id,
            function.id,
            "signature",
            presentation_id,
        ),
        type_parameters=tuple(render_expression_tree(item) for item in function.type_parameters),
    )


def dependency_closure(project: Project, diagram_id: str) -> frozenset[str]:
    """Omit only unrelated incomplete definitions from an explicit focused build.

    Complete declarations keep their Python import environment. Initializers,
    signature evaluation, imports, and reflection also require their dependencies.
    """
    model = project.program_model
    start_id = next(
        (view.function_id for view in project.drakon_views if view.document_id == diagram_id),
        diagram_id,
    )
    if model.function(start_id) is None:
        raise ValueError(f"Program function or DRAKON view {diagram_id!r} does not exist")
    all_ids = frozenset(function.id for function in model.functions)

    def walk(node: ExpressionNode) -> Iterator[ExpressionNode]:
        yield node
        for _, child in expression_children(node):
            yield from walk(child)

    incomplete = {
        function.id
        for function in model.functions
        if any(
            isinstance(node, UnparsedPythonExpression)
            for expression in program_expressions(function)
            for node in walk(expression.tree)
        )
    }
    if not incomplete:
        return all_ids
    by_name: dict[str, set[str]] = {}
    for function in model.functions:
        by_name.setdefault(function.identifier, set()).add(function.id)
        owner = model.class_name_for(function.id)
        for part in owner.split(".") if owner is not None else ():
            by_name.setdefault(part, set()).add(function.id)
    required = {start_id}
    names: set[str] = set()

    def collect(value: object) -> None:
        for expression in program_expressions(value):
            for node in walk(expression.tree):
                if isinstance(node, SymbolReferenceExpression):
                    names.add(node.name)
                elif isinstance(node, AttributeExpression):
                    names.add(node.attribute)
        for item in iter_program_nodes(value):
            if isinstance(item, ProgramCall) and item.target_function_id is not None:
                required.add(item.target_function_id)
            elif isinstance(item, ProgramImport):
                try:
                    imports = ast.parse(item.source.source).body
                except SyntaxError:
                    names.add("__import__")
                    continue
                for statement in imports:
                    if isinstance(statement, ast.ImportFrom):
                        names.update(alias.name for alias in statement.names)

    collect(model.modules)
    if model.entrypoint is not None:
        collect(model.entrypoint.startup)
    for function in model.functions:
        if function.id not in incomplete:
            collect((function.parameters, function.decorators, function.return_annotation))
    visited: set[str] = set()
    while True:
        if names & {"globals", "locals", "vars", "getattr", "eval", "exec", "__import__", "*"}:
            return all_ids
        for name in names:
            required.update(by_name.get(name, ()))
        pending = required - visited
        if not pending:
            break
        for identity in pending:
            visited.add(identity)
            dependency = model.function(identity)
            if dependency is not None:
                if dependency.method_kind is MethodKind.INSTANCE:
                    receiver_class = model.class_for(dependency.id)
                    required.update(
                        constructor.id
                        for constructor in model.functions
                        if model.class_for(constructor.id) == receiver_class
                        and normalize("NFKC", constructor.identifier) in {"__init__", "__new__"}
                    )
                collect(dependency)
    return frozenset((all_ids - incomplete) | required)


def _lower_declarations(
    project: Project,
    declarations: tuple[ProgramDeclaration, ...],
    locations: Mapping[str, ProgramFunctionLocation],
    selected: frozenset[str] | None = None,
    owner: ProgramModule | ProgramClass | ProgramEntryPoint | None = None,
) -> tuple[DeclarationIR, ...]:
    result: list[DeclarationIR] = []
    for item in declarations:
        if isinstance(item, ProgramFunctionReference):
            if selected is not None and item.function_id not in selected:
                continue
            function = project.program_model.function(item.function_id)
            if function is None:
                raise ValueError(f"Unknown declared function {item.function_id!r}")
            result.append(
                _lower_program_function(project, function, None, locations.get(function.id))
            )
        elif isinstance(item, ProgramClass):
            result.append(
                ClassIR(
                    item.identifier,
                    item.arguments.source if item.arguments is not None else None,
                    tuple(expression.source for expression in item.decorators),
                    item.docstring,
                    tuple(render_expression_tree(node) for node in item.type_parameters),
                    _lower_declarations(project, item.body, locations, selected, item),
                    Origin(project.id, item.id, "declaration"),
                )
            )
        elif isinstance(item, ProgramImport | ProgramTypeAlias):
            result.append(RawStatementIR(item.source.source, Origin(project.id, item.id, "source")))
        else:
            result.append(_lower_program_statement(project, None, owner, item))
    return tuple(result)


def lower_project(
    project: Project, *, diagram_ids: frozenset[str] | None = None
) -> PythonProjectIR:
    """Lower ordered canonical declarations; selection only changes invocation."""
    model = project.program_model
    locations = program_function_locations(model)
    selected_ids = (
        None
        if diagram_ids is None
        else frozenset(
            next(
                (view.function_id for view in project.drakon_views if view.document_id == identity),
                identity,
            )
            for identity in diagram_ids
        )
    )
    modules = tuple(
        ModuleIR(
            module.path,
            module.docstring,
            _lower_declarations(project, module.body, locations, selected_ids, module),
            Origin(project.id, module.id, "body"),
            module.kind,
        )
        for module in model.modules
    )
    selected = model.entrypoint
    entrypoint: EntryPointIR | None = None
    if selected is not None and selected.callable_id is not None:
        function = model.function(selected.callable_id)
        if function is None:
            raise ValueError(f"Unknown entrypoint {selected.callable_id!r}")
        if not isinstance(selected.arguments, InvocationArguments):
            raise ValueError("Unresolved entrypoint arguments cannot be lowered")
        entrypoint = EntryPointIR(
            model.module_path_for(function.id),
            bind_invocation(model, function, selected.arguments),
            Origin(project.id, selected.id, "invocation"),
        )
    return PythonProjectIR(
        project.id,
        project.revision,
        model.package,
        modules,
        _lower_declarations(project, selected.startup, locations, selected_ids, selected)
        if selected is not None
        else (),
        entrypoint,
    )
