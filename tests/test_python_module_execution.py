"""Canonical Python ownership keeps generated, live, and portable execution equal."""

import ast
import json
from dataclasses import replace

import pytest

from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.expression import expression_tree_from_ast
from code_visualizer.domain.invocation import InvocationBindingError, bind_invocation
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAssignment,
    ProgramCall,
    ProgramClass,
    ProgramDelay,
    ProgramEntryPoint,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramModel,
    ProgramModule,
    ProgramOutput,
    ProgramParameter,
    ProgramSequence,
    ProgramSymbol,
    ProgramSymbolKind,
    ProgramTransfer,
    make_program_expression,
)
from code_visualizer.domain.program_bindings import resolve_linked_callable
from code_visualizer.domain.program_kinds import CallableKind, MethodKind, TransferKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.domain.transformation import OriginLink, OriginMap
from code_visualizer.execution import (
    DebugLaunch,
    DebugSession,
    SourceLocation,
    run_generated,
    run_project,
    trace_project,
)
from code_visualizer.execution.runtime import program_binding_specs
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.generation.computation import prepare_computation
from code_visualizer.generation.emitter import emit_project
from code_visualizer.generation.lowering import lower_project
from code_visualizer.generation.program_composition import compose_programs, composed_origins
from code_visualizer.generation.python import BuildBlockedError, generate_python
from code_visualizer.generation.transformation import value_identities
from code_visualizer.persistence.computation_terminal import load_terminal, publish_terminal
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.validation import assess_project


def _expression(owner, source, role=ExpressionRole.VALUE):
    return make_program_expression(owner, "value", source, role, identity_namespace=owner)


def _function(identity, name, statements, *, method=None, parameters=()):
    return ProgramFunction(
        identity,
        f"symbol:{identity}",
        name,
        name,
        CallableKind.SYNC,
        parameters,
        None,
        (),
        None,
        method,
        ProgramSequence(f"body:{identity}", statements),
    )


def _symbols(functions):
    result = []
    for function in functions:
        result.append(
            ProgramSymbol(
                function.symbol_id,
                function.identifier,
                ProgramSymbolKind.FUNCTION,
                function.id,
                function.id,
            )
        )
        result.extend(
            ProgramSymbol(
                parameter.symbol_id,
                parameter.name,
                ProgramSymbolKind.PARAMETER,
                function.id,
                parameter.id,
            )
            for parameter in function.parameters
        )
    return tuple(result)


def _module(identity, path, source, functions=()):
    return ProgramModule(
        identity,
        path,
        (
            *parse_python_declarations(identity, source, identity_namespace=identity),
            *(ProgramFunctionReference(item.id) for item in functions),
        ),
    )


def _project():
    reads = []
    locals_ = []
    for side in ("left", "right"):
        assignment = ProgramAssignment(
            f"{side}:local",
            _expression(f"{side}:target", "value", ExpressionRole.TARGET),
            _expression(f"{side}:global", "VALUE"),
        )
        function = _function(
            f"{side}:read",
            "read",
            (
                assignment,
                ProgramTransfer(
                    f"{side}:return",
                    TransferKind.RETURN,
                    _expression(f"{side}:result", "value"),
                    None,
                ),
            ),
        )
        reads.append(function)
        locals_.append(
            ProgramSymbol(
                f"{side}:symbol:value",
                "value",
                ProgramSymbolKind.LOCAL,
                function.id,
                assignment.id,
            )
        )
    main = _function(
        "main:run",
        "main",
        (ProgramOutput("main:output", _expression("main:pair", "(left_read(), right.read())")),),
    )
    functions = (*reads, main)
    program = ProgramModel(
        functions,
        (*_symbols(functions), *locals_),
        (
            _module("module:left", "left", "VALUE = 1", (reads[0],)),
            _module("module:right", "right", "VALUE = 2", (reads[1],)),
            _module(
                "module:main",
                "main",
                "from app.left import read as left_read\nfrom app import right",
                (main,),
            ),
        ),
        entrypoint=ProgramEntryPoint(
            "entrypoint:main",
            main.id,
            startup=parse_python_declarations(
                "entrypoint:main",
                "from app.left import read as startup_read\nprint(f'startup:{startup_read()}')",
                identity_namespace="startup",
            ),
        ),
    )
    return Project("project:module-parity", "Python modules", (), program_model=program)


def _assert_surfaces(project, tmp_path, expected):
    assessment = assess_project(project)
    assert assessment.buildable, assessment.diagnostics
    ir = lower_project(project)
    generated = emit_project(ir)
    for file in generated.files:
        path = tmp_path / file.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(file.source, encoding="utf-8")
    trace = trace_project(
        generated,
        binding_specs=program_binding_specs(project.program_model),
    )
    results = (
        run_generated(tmp_path / "run_project.py"),
        run_project(generated),
        trace.run,
    )
    for result in results:
        assert result.return_code == 0, result.stderr
        assert result.stdout == expected
        assert not result.stderr
    return generated, trace


def test_module_globals_import_aliases_and_startup_have_execution_parity(tmp_path):
    project = _project()
    before = project_to_data(project)
    source, trace = _assert_surfaces(project, tmp_path, "startup:1\n(1, 2)\n")
    assert project_to_data(project) == before
    active = {
        span.semantic_id
        for event in trace.runtime_events
        for span in source.spans
        if span.file_path == event.file_path and span.start_line <= event.line <= span.end_line
    }
    assert {"left:local", "right:local", "main:output"} <= active
    bound = {
        binding.semantic_symbol_id
        for event in trace.runtime_events
        if event.runtime_graph is not None
        for binding in event.runtime_graph.bindings
    }
    assert {"left:symbol:value", "right:symbol:value"} <= bound


def test_debugger_stops_at_original_module_lines_and_finishes(tmp_path):
    project = _project()
    ir = lower_project(project)
    source = emit_project(ir)
    assert ir.entrypoint is not None
    breakpoint = next(
        SourceLocation(span.file_path, span.start_line)
        for span in source.spans
        if span.semantic_id == "right:local"
    )
    events = []
    with DebugSession() as debugger:
        debugger.start(
            DebugLaunch(
                project=source,
                breakpoints=(breakpoint,),
                binding_specs=program_binding_specs(project.program_model),
            )
        )
        for _ in range(100):
            event = debugger.wait_event(timeout=10)
            events.append(event)
            if event.event == "paused":
                debugger.continue_execution()
            if event.event in {"finished", "failed", "stopped"}:
                break
    assert events[-1].event == "finished", events[-1]
    assert any(event.event == "paused" and event.location == breakpoint for event in events)


def test_explicit_class_metadata_and_order_use_existing_python_pipeline(tmp_path):
    parameter = ProgramParameter("parameter:cls", "symbol:cls", "cls")
    run = _function(
        "function:run",
        "run",
        (
            ProgramOutput(
                "class:output",
                _expression(
                    "class:result",
                    "(cls.value, cls.inherited, cls.meta, cls.decorated, cls.__doc__)",
                ),
            ),
        ),
        method=MethodKind.CLASS,
        parameters=(parameter,),
    )
    prelude = parse_python_declarations(
        "module:classes",
        """
class Meta(type):
    def __new__(meta, name, bases, namespace):
        cls = super().__new__(meta, name, bases, namespace)
        cls.meta = 'meta'
        return cls
class Base:
    inherited = 'base'
def decorate(cls):
    cls.decorated = 'decorated'
    return cls
""",
        identity_namespace="class-metadata",
    )
    declaration = ProgramClass(
        "class:Worker",
        "Worker",
        (
            *parse_python_declarations(
                "class:Worker", "value = 7", identity_namespace="class-body"
            ),
            ProgramFunctionReference(run.id),
        ),
        _expression("class:bases", "Base, metaclass=Meta", ExpressionRole.ARGUMENTS),
        (_expression("class:decorator", "decorate", ExpressionRole.DECORATOR),),
        "Worker documentation",
        (
            expression_tree_from_ast(
                "type:Worker:T",
                ast.parse("class Worker[T]: pass").body[0].type_params[0],
                identity_namespace="class-type-parameter",
            ),
        ),
    )
    program = ProgramModel(
        (run,),
        _symbols((run,)),
        (ProgramModule("module:classes", "classes", (*prelude, declaration)),),
        entrypoint=ProgramEntryPoint("entrypoint:classes", run.id),
    )
    project = Project("project:classes", "Class ownership", (), program_model=program)
    source, _ = _assert_surfaces(
        project,
        tmp_path,
        "(7, 'base', 'meta', 'decorated', 'Worker documentation')\n",
    )
    assert any(span.semantic_id == declaration.id for span in source.spans)
    assert "class Worker[T](Base, metaclass=Meta):" in source.file("app/classes.py").source


def test_ordered_default_and_decorator_evaluation_and_future_imports_match(tmp_path):
    parameter = ProgramParameter(
        "parameter:n",
        "symbol:n",
        "n",
        default=_expression("default:n", "VALUE", ExpressionRole.DEFAULT),
    )
    function = _function(
        "function:ordered",
        "main",
        (
            ProgramDelay("ordered:delay", _expression("ordered:seconds", "0"), False),
            ProgramOutput(
                "ordered:output", _expression("ordered:result", "(n, VALUE, events, __doc__)")
            ),
        ),
        parameters=(parameter,),
    )
    function = replace(
        function, decorators=(_expression("decorator:main", "decorate", ExpressionRole.DECORATOR),)
    )
    prelude = parse_python_declarations(
        "module:ordered",
        '''"""Ordered module"""
# Future imports must remain ahead of injected runtime support.
from __future__ import annotations
VALUE = 11
events = []
def decorate(function):
    events.append('decorated')
    return function
''',
        identity_namespace="ordered",
    )
    suffix = parse_python_declarations(
        "module:ordered:tail", "VALUE = 99", identity_namespace="tail"
    )
    program = ProgramModel(
        (function,),
        _symbols((function,)),
        (
            ProgramModule(
                "module:ordered", "main", (*prelude, ProgramFunctionReference(function.id), *suffix)
            ),
        ),
        entrypoint=ProgramEntryPoint("entrypoint:ordered", function.id),
    )
    project = Project("project:ordered", "Declaration order", (), program_model=program)
    _assert_surfaces(project, tmp_path, "(11, 99, ['decorated'], 'Ordered module')\n")


def test_imported_constructor_signature_cannot_be_ignored_by_instance_admission():
    run = _function(
        "function:run",
        "run",
        (),
        method=MethodKind.INSTANCE,
        parameters=(ProgramParameter("p:self", "s:self", "self"),),
    )
    declaration = ProgramClass(
        "class:Worker",
        "Worker",
        (
            *parse_python_declarations(
                "class:Worker", "def __init__(self, required):\n    self.required = required"
            ),
            ProgramFunctionReference(run.id),
        ),
    )
    program = ProgramModel(
        (run,), _symbols((run,)), (ProgramModule("module:worker", "main", (declaration,)),)
    )
    with pytest.raises(InvocationBindingError, match="constructor") as error:
        bind_invocation(program, run)
    assert error.value.code == "INVOCATION_RECEIVER_REQUIRES_SETUP"


def test_portable_terminal_carries_all_python_meaning_in_program_model(tmp_path):
    project = _project()
    registry = builtin_registry()
    request = ComputationRequest(project.id, project.revision, "code_visualizer.python", "1")
    snapshot = prepare_computation(project, request, registry)
    store = ResourceStore(tmp_path)
    plan = publish_terminal(snapshot, store)
    payload = json.loads(store.read(plan.model))
    assert payload["version"] == 2
    assert "module_setup" not in payload
    loaded = load_terminal(plan, store, registry)
    assert loaded.value == project.program_model
    backend = registry.backend("code_visualizer.python", "1")
    assert backend is not None and backend.execute is not None
    result = backend.execute(loaded)
    stdout = next(item.value for item in result.observations if item.label == "stdout")
    assert stdout == "startup:1\n(1, 2)\n"


def test_derived_module_composition_preserves_member_and_origin_identities():
    project = _project()
    authored = project.program_model
    additional = _module("derived:module", "main", "DERIVED = 3")
    contribution = ProgramModel(modules=(additional,))
    composed = compose_programs(authored, contribution)
    module = next(item for item in composed.program.modules if item.path == "main")
    assert module.id == "module:main"
    assert module.body[-1] == additional.body[-1]
    origins = OriginMap(
        project.id,
        project.revision,
        (
            OriginLink("module:main", ("authored:meaning",)),
            *(
                OriginLink(identity, ("domain:meaning",))
                for identity in sorted(value_identities(contribution))
            ),
        ),
    )
    mapped = composed_origins(origins, composed.program, composed.replacements)
    module_link = next(item for item in mapped.links if item.generated_id == module.id)
    assert set(module_link.source_ids) == {"authored:meaning", "domain:meaning"}
    assert "derived:module" not in value_identities(composed.program)
    assert project.program_model == authored


@pytest.mark.parametrize("empty", (False, True))
def test_module_only_program_runs_once_through_live_trace_and_backend(tmp_path, empty):
    program = (
        ProgramModel()
        if empty
        else ProgramModel(
            modules=(
                _module("module:first", "first", "print('one')"),
                _module("module:second", "second", "from app import first\nprint('two')"),
            ),
            entrypoint=ProgramEntryPoint(
                "entrypoint:modules",
                startup=parse_python_declarations(
                    "entrypoint:modules",
                    "print('startup')",
                    identity_namespace="module-startup",
                ),
            ),
        )
    )
    project = Project("project:module-only", "Module initialization", (), program_model=program)
    expected = "" if empty else "one\ntwo\nstartup\n"
    source, trace = _assert_surfaces(project, tmp_path / "generated", expected)
    if not empty:
        assert any(
            span.semantic_id == program.modules[0].body[0].id
            for event in trace.runtime_events
            for span in source.spans
            if span.file_path == event.file_path and span.start_line <= event.line <= span.end_line
        )
    registry = builtin_registry()
    request = ComputationRequest(project.id, 0, "code_visualizer.python", "1")
    snapshot = prepare_computation(project, request, registry)
    store = ResourceStore(tmp_path / "resources")
    loaded = load_terminal(publish_terminal(snapshot, store), store, registry)
    backend = registry.backend("code_visualizer.python", "1")
    assert backend is not None and backend.execute is not None
    result = backend.execute(loaded)
    assert next(item.value for item in result.observations if item.label == "stdout") == expected


@pytest.mark.parametrize(
    "dependency", ("body", "default", "module", "class", "import", "reflection")
)
def test_focused_projection_retains_incomplete_dependencies_of_python_initialization(dependency):
    broken = _function(
        "function:broken",
        "broken",
        (
            ProgramAssignment(
                "broken:assignment",
                _expression("broken:target", "value", ExpressionRole.TARGET),
                _expression("broken:value", "missing +"),
            ),
        ),
    )
    body = (
        (ProgramOutput("selected:output", _expression("selected:expression", "broken()")),)
        if dependency == "body"
        else ()
    )
    parameters = (
        (
            ProgramParameter(
                "selected:p",
                "selected:s",
                "value",
                default=_expression("selected:default", "broken()", ExpressionRole.DEFAULT),
            ),
        )
        if dependency == "default"
        else ()
    )
    if dependency == "reflection":
        body = (ProgramOutput("selected:output", _expression("selected:reflection", "globals()")),)
    selected = _function("function:selected", "selected", body, parameters=parameters)
    declarations = ()
    if dependency in {"module", "import"}:
        declarations = parse_python_declarations(
            "scope", "broken()" if dependency == "module" else "from app.main import broken"
        )
    elif dependency == "class":
        declarations = (
            ProgramClass(
                "class:initialize",
                "Initialize",
                parse_python_declarations("class:initialize", "broken()"),
            ),
        )
    program = ProgramModel(
        (broken, selected),
        _symbols((broken, selected)),
        (
            ProgramModule(
                "module:focused",
                "main",
                (
                    ProgramFunctionReference(broken.id),
                    ProgramFunctionReference(selected.id),
                    *declarations,
                ),
            ),
        ),
        entrypoint=ProgramEntryPoint("entrypoint:focused", selected.id),
    )
    project = Project("project:focused", "Focused dependencies", (), program_model=program)
    with pytest.raises(BuildBlockedError, match="PROGRAM_INCOMPLETE_EXPRESSION"):
        generate_python(project, focus_diagram_id=selected.id, include_main=False)


def test_linked_calls_resolve_module_class_and_launcher_lexical_scopes(tmp_path):
    helper = _function(
        "function:helper",
        "helper",
        (ProgramOutput("helper:output", _expression("helper:text", "'helper'")),),
    )
    earlier = _function(
        "function:earlier",
        "earlier",
        (ProgramOutput("earlier:output", _expression("earlier:text", "'class'")),),
        method=MethodKind.STATIC,
    )
    run = _function(
        "function:run",
        "run",
        (ProgramOutput("run:output", _expression("run:text", "'run'")),),
        method=MethodKind.STATIC,
    )

    def call(identity, text, target):
        return ProgramCall(
            identity,
            _expression(f"{identity}:callee", text, ExpressionRole.CALL),
            _expression(f"{identity}:arguments", "", ExpressionRole.ARGUMENTS),
            target_function_id=target,
        )

    declaration = ProgramClass(
        "class:Worker",
        "Worker",
        (
            ProgramFunctionReference(earlier.id),
            call("call:class", "earlier()", earlier.id),
            ProgramFunctionReference(run.id),
        ),
    )
    functions = (helper, earlier, run)
    program = ProgramModel(
        functions,
        _symbols(functions),
        (
            _module("module:helper", "pkg.helper", "", (helper,)),
            ProgramModule(
                "module:main",
                "pkg.main",
                (
                    *parse_python_declarations(
                        "module:main", "from .helper import helper as chosen"
                    ),
                    declaration,
                    call("call:module", "chosen()", helper.id),
                ),
            ),
        ),
        entrypoint=ProgramEntryPoint(
            "entrypoint:scoped",
            run.id,
            startup=(
                *parse_python_declarations("entrypoint:scoped", "import app.pkg.helper as helpers"),
                call("call:startup", "helpers.helper()", helper.id),
            ),
        ),
    )
    project = Project("project:scoped", "Python lexical calls", (), program_model=program)
    _assert_surfaces(project, tmp_path, "class\nhelper\nhelper\nrun\n")


def test_classmethod_is_not_a_callable_while_its_class_body_is_executing():
    method = _function(
        "method:build",
        "build",
        (),
        method=MethodKind.CLASS,
        parameters=(ProgramParameter("method:cls", "symbol:cls", "cls"),),
    )
    owner = ProgramClass("class:Building", "Building", (ProgramFunctionReference(method.id),))
    program = ProgramModel(
        (method,), _symbols((method,)), (ProgramModule("module:main", "main", (owner,)),)
    )
    assert resolve_linked_callable(program, owner, method) is None
    with pytest.raises(TypeError, match="classmethod"):
        exec("class Building:\n    @classmethod\n    def build(cls): pass\n    build()")


def test_focused_instance_execution_keeps_its_incomplete_constructor():
    parameter = ProgramParameter("constructor:self", "constructor:self:symbol", "self")
    constructor = _function(
        "constructor",
        "__init__",
        (
            ProgramAssignment(
                "constructor:assignment",
                _expression("constructor:target", "self.value", ExpressionRole.TARGET),
                _expression("constructor:value", "missing +"),
            ),
        ),
        method=MethodKind.INSTANCE,
        parameters=(parameter,),
    )
    selected = _function(
        "selected",
        "run",
        (),
        method=MethodKind.INSTANCE,
        parameters=(ProgramParameter("selected:self", "selected:self:symbol", "self"),),
    )
    functions = (constructor, selected)
    owner = ProgramClass(
        "class:Worker", "Worker", tuple(ProgramFunctionReference(item.id) for item in functions)
    )
    model = ProgramModel(
        functions,
        _symbols(functions),
        (ProgramModule("module:main", "main", (owner,)),),
        entrypoint=ProgramEntryPoint("entrypoint:main", selected.id),
    )
    project = Project("project:constructor", "Incomplete receiver", (), program_model=model)
    with pytest.raises(BuildBlockedError, match="PROGRAM_INCOMPLETE_EXPRESSION"):
        generate_python(project, focus_diagram_id=selected.id, include_main=False)
