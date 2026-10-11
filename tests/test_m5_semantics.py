from dataclasses import replace

import pytest

from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.project_factory import (
    create_default_project,
    initialize_project_documents,
)
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    DrakonAtom,
    ExceptionHandler,
    Loop,
    Output,
    Parallel,
    Period,
    Sequence,
    Silhouette,
    StartTimer,
    Synchronizer,
    Transfer,
    Try,
    create_empty_drakon,
    nested_sequences,
)
from code_visualizer.domain.drakon_defaults import (
    ATOM_KIND_INVENTORY,
    MACROICON_INVENTORY,
    create_default_atom,
)
from code_visualizer.domain.program import ProgramEntryPoint
from code_visualizer.domain.program_kinds import CallableKind, LoopKind, MethodKind, TransferKind
from code_visualizer.domain.program_signatures import ParameterSpec
from code_visualizer.execution import run_project
from code_visualizer.generation import generate_python, generate_python_project
from code_visualizer.persistence.decoding import drakon_atom_from_data
from code_visualizer.persistence.serialization import drakon_atom_to_data
from code_visualizer.rendering.catalog import preview_for_atom_kind
from code_visualizer.rendering.recipes import RecipeKind
from code_visualizer.rendering.scene import layout_drakon
from code_visualizer.validation import Severity, validate_project

ASYNC_KINDS = {
    "async_delay",
    "async_for_loop",
    "async_parallel",
    "async_period",
    "async_with",
    "await_call",
}
GENERATOR_KINDS = {"yield", "yield_from"}


def _contextual_diagram(atom_kind: str, index: int):
    diagram = create_empty_drakon()
    atom = create_default_atom(atom_kind, f"atom_semantic_{index}")
    callable_kind = (
        CallableKind.ASYNC
        if atom_kind in ASYNC_KINDS
        else CallableKind.GENERATOR
        if atom_kind in GENERATOR_KINDS
        else CallableKind.SYNC
    )
    atoms: tuple[DrakonAtom, ...] = (atom,)
    if isinstance(atom, (Period, Synchronizer)):
        atoms = (StartTimer(f"timer_semantic_{index}", "operation"), atom)
    if atom_kind in {"break", "continue"}:
        atoms = (
            Loop(
                f"loop_semantic_{index}",
                LoopKind.FOR,
                Sequence(f"sequence_loop_{index}", (atom,)),
                Sequence(f"sequence_loop_else_{index}"),
                target="item",
                iterable="range(1)",
            ),
        )
    if atom_kind == "nonlocal":
        parallel = create_default_atom("parallel", f"parallel_semantic_{index}")
        assert isinstance(parallel, Parallel)
        first = replace(
            parallel.branches[0],
            body=Sequence(f"sequence_nonlocal_{index}", (atom,)),
        )
        atoms = (
            Assignment(f"assignment_semantic_{index}", "captured_value", "0"),
            replace(parallel, branches=(first, parallel.branches[1])),
        )
    function = replace(diagram.header.function, kind=callable_kind)
    return replace(
        diagram,
        header=replace(diagram.header, function=function),
        body=replace(diagram.body, atoms=atoms),
    )


def _project(diagram):
    project = create_default_project()
    return initialize_project_documents(
        replace(
            project,
            program_model=replace(
                project.program_model, entrypoint=ProgramEntryPoint("entrypoint:test", diagram.id)
            ),
        ),
        (diagram,),
    )


@pytest.mark.parametrize(
    ("index", "atom_kind"),
    tuple((index, item.kind) for index, item in enumerate(ATOM_KIND_INVENTORY)),
)
def test_every_semantic_atom_round_trips_renders_and_compiles(index: int, atom_kind: str) -> None:
    original = create_default_atom(atom_kind, f"atom_roundtrip_{index}")
    assert drakon_atom_from_data(drakon_atom_to_data(original)) == original
    preview_for_atom_kind(atom_kind)

    diagram = _contextual_diagram(atom_kind, index)
    project = _project(diagram)
    errors = [item for item in validate_project(project) if item.severity is Severity.ERROR]
    assert errors == []

    generated = generate_python_project(project)
    for item in generated.files:
        compile(item.source, item.path, "exec")

    scene = layout_drakon(diagram)
    assert all(
        scene.bounds.contains(route.segment.start) and scene.bounds.contains(route.segment.end)
        for route in scene.routes
    )
    for left_index, left in enumerate(scene.nodes):
        for right in scene.nodes[left_index + 1 :]:
            assert not left.bounds.intersects(right.bounds)

    def sequences(sequence: Sequence) -> tuple[Sequence, ...]:
        result = [sequence]
        for item in sequence.atoms:
            for child in nested_sequences(item):
                result.extend(sequences(child))
        return tuple(result)

    expected = {
        (sequence.id, boundary)
        for sequence in sequences(diagram.body)
        for boundary in range(len(sequence.atoms) + 1)
    }
    actual = {
        (route.boundary.sequence_id, route.boundary.index)
        for route in scene.insertion_routes()
        if route.boundary is not None
    }
    assert actual == expected


def test_atomic_and_macro_inventory_is_complete() -> None:
    assert len(RecipeKind) == 27
    assert len(ATOM_KIND_INVENTORY) >= 45
    assert len(MACROICON_INVENTORY) == 21
    assert len({item.kind for item in ATOM_KIND_INVENTORY}) == len(ATOM_KIND_INVENTORY)


def test_every_atomic_recipe_is_bound_to_a_real_semantic_scene_projection() -> None:
    diagram = create_empty_drakon()
    atoms = tuple(
        create_default_atom(item.kind, f"atom_inventory_binding_{index}")
        for index, item in enumerate(ATOM_KIND_INVENTORY)
    )
    diagram = replace(
        diagram,
        header=replace(
            diagram.header,
            function=replace(
                diagram.header.function,
                parameters=(ParameterSpec("value", annotation="object", default="None"),),
            ),
        ),
        body=replace(diagram.body, atoms=atoms),
    )

    scene = layout_drakon(diagram)

    assert {node.shape.kind for node in scene.nodes} == set(RecipeKind)


@pytest.mark.parametrize("macro_id", tuple(item.id for item in MACROICON_INVENTORY))
def test_each_macroicon_is_one_undoable_typed_transaction(macro_id: str) -> None:
    session = ProjectSession.new()
    try:
        # Compile library functions: the parameter macro introduces required inputs.
        configured = session.client.configure_entrypoint(None)
        assert isinstance(configured, CommandAccepted)
        diagram = session.authority.snapshot().documents[0]
        before = session.authority.revision
        result = session.client.insert_drakon_macro(diagram.id, macro_id, 0)
        assert isinstance(result, CommandAccepted)
        assert result.revision == before + 1
        project = session.authority.snapshot()
        assert not [item for item in validate_project(project) if item.severity is Severity.ERROR]
        for item in generate_python_project(project).files:
            compile(item.source, item.path, "exec")
        undone = session.client.undo()
        assert isinstance(undone, CommandAccepted)
        assert session.authority.snapshot().documents[0].body.atoms == ()
    finally:
        session.close()


def test_silhouette_uses_readable_state_name_and_runs_to_one_exit() -> None:
    diagram = _contextual_diagram("silhouette", 1)
    project = _project(diagram)
    source = generate_python(project, include_main=False).source

    assert "_golden_node_state" in source
    assert "atom_semantic" not in source
    result = run_project(generate_python_project(project))
    assert result.return_code == 0
    assert result.stdout.splitlines() == ["start state action", "finish state action"]


@pytest.mark.parametrize(
    ("atom_kind", "expected_code"),
    (
        ("break", "PY_LOOP_TRANSFER_OUTSIDE_LOOP"),
        ("continue", "PY_LOOP_TRANSFER_OUTSIDE_LOOP"),
        ("await_call", "PY_AWAIT_OUTSIDE_ASYNC"),
        ("yield", "PY_YIELD_OUTSIDE_GENERATOR"),
        ("period", "PY_TIMER_BEFORE_START"),
    ),
)
def test_flow_diagnostics_name_the_illegal_context(atom_kind: str, expected_code: str) -> None:
    diagram = create_empty_drakon()
    diagram = replace(
        diagram,
        body=replace(diagram.body, atoms=(create_default_atom(atom_kind, "atom_bad_flow"),)),
    )
    codes = {item.code for item in validate_project(_project(diagram))}
    assert expected_code in codes


@pytest.mark.parametrize(
    ("method_kind", "parameters", "invocation"),
    (
        (MethodKind.INSTANCE, (ParameterSpec("self"),), "_entrypoint().run()"),
        (MethodKind.CLASS, (ParameterSpec("cls"),), "_entrypoint.run()"),
        (MethodKind.STATIC, (), "_entrypoint.run()"),
    ),
)
def test_class_method_semantics_and_entrypoint_invocation(
    method_kind: MethodKind,
    parameters: tuple[ParameterSpec, ...],
    invocation: str,
) -> None:
    diagram = create_empty_drakon(identifier="run", title="Run")
    function = replace(
        diagram.header.function,
        owning_class="Worker",
        method_kind=method_kind,
        parameters=parameters,
    )
    diagram = replace(
        diagram,
        header=replace(diagram.header, function=function),
        body=replace(diagram.body, atoms=(Output("output_method", '"ok"'),)),
    )
    project = _project(diagram)
    generated = generate_python_project(project)

    assert invocation in generated.file("run_project.py").source
    for item in generated.files:
        compile(item.source, item.path, "exec")


@pytest.mark.parametrize(
    "expression",
    (
        "[item * 2 for item in range(3)]",
        "(lambda value: value + 1)(1)",
        'f"answer={1 + 1}"',
        "(_named_value := 4)",
        "[1, 2, 3][1:]",
        "dict(answer=42)",
    ),
)
def test_full_expression_roles_validate_and_compile(expression: str) -> None:
    diagram = create_empty_drakon()
    diagram = replace(
        diagram,
        body=replace(
            diagram.body,
            atoms=(Assignment("assignment_expression", "result", expression),),
        ),
    )
    project = _project(diagram)

    assert not [item for item in validate_project(project) if item.severity is Severity.ERROR]
    for item in generate_python_project(project).files:
        compile(item.source, item.path, "exec")


def test_async_syntax_is_accepted_only_in_async_expression_roles() -> None:
    diagram = create_empty_drakon()
    diagram = replace(
        diagram,
        body=replace(
            diagram.body,
            atoms=(Assignment("assignment_await", "result", "await operation()"),),
        ),
    )
    sync_codes = {item.code for item in validate_project(_project(diagram))}
    assert "PY_AWAIT_OUTSIDE_ASYNC" in sync_codes

    async_diagram = replace(
        diagram,
        header=replace(
            diagram.header,
            function=replace(diagram.header.function, kind=CallableKind.ASYNC),
        ),
    )
    async_project = _project(async_diagram)
    assert "PY_AWAIT_OUTSIDE_ASYNC" not in {item.code for item in validate_project(async_project)}
    for item in generate_python_project(async_project).files:
        compile(item.source, item.path, "exec")


def test_except_star_rejects_control_transfer_from_handler() -> None:
    diagram = create_empty_drakon()
    handler = ExceptionHandler(
        "handler_group",
        "Exception",
        "errors",
        Sequence(
            "sequence_handler_group",
            (Transfer("transfer_return", TransferKind.RETURN, "None"),),
        ),
    )
    construct = Try(
        "try_group",
        Sequence("sequence_try_group", (Action("action_raise", "raise Exception('boom')"),)),
        (handler,),
        Sequence("sequence_try_group_else"),
        Sequence("sequence_try_group_finally"),
        True,
    )
    diagram = replace(diagram, body=replace(diagram.body, atoms=(construct,)))

    codes = {item.code for item in validate_project(_project(diagram))}
    assert "PY_TRANSFER_INSIDE_EXCEPT_STAR" in codes


def test_silhouette_diagnoses_initial_cycle_and_unreachable_exit() -> None:
    diagram = _contextual_diagram("silhouette", 44)
    silhouette = diagram.body.atoms[0]
    assert isinstance(silhouette, Silhouette)
    first, second = silhouette.branches
    broken = replace(
        silhouette,
        branches=(replace(first, target_branch_id=first.id), second),
    )
    diagram = replace(diagram, body=replace(diagram.body, atoms=(broken,)))

    codes = {item.code for item in validate_project(_project(diagram))}
    assert "DRAKON_SILHOUETTE_NONTERMINATING" in codes
    assert "DRAKON_SILHOUETTE_UNREACHABLE_STATE" in codes


def test_silhouette_rejects_every_invalid_address_topology_edge() -> None:
    diagram = _contextual_diagram("silhouette", 45)
    silhouette = diagram.body.atoms[0]
    assert isinstance(silhouette, Silhouette)
    first, second = silhouette.branches
    broken = replace(
        silhouette,
        identifier="class",
        initial_branch_id="missing_initial_address",
        branches=(
            replace(first, name="Duplicate", target_branch_id="missing_target_address"),
            replace(second, name="duplicate", target_branch_id=first.id),
        ),
    )
    diagram = replace(diagram, body=replace(diagram.body, atoms=(broken,)))

    codes = {item.code for item in validate_project(_project(diagram))}
    assert {
        "PY_INVALID_SILHOUETTE_IDENTIFIER",
        "DRAKON_SILHOUETTE_INITIAL_MISSING",
        "DRAKON_SILHOUETTE_EXIT_COUNT",
        "DRAKON_SILHOUETTE_DUPLICATE_STATE",
        "DRAKON_SILHOUETTE_TARGET_MISSING",
    } <= codes


def test_do_first_wait_and_loop_else_follow_python_transfer_semantics() -> None:
    diagram = create_empty_drakon()
    do_first = Loop(
        "loop_do_first_else",
        LoopKind.DO_FIRST,
        Sequence("sequence_do_first_body", (Output("output_first_body", '"first body"'),)),
        Sequence("sequence_do_first_else", (Output("output_first_else", '"first else"'),)),
        condition="False",
    )
    interrupted = Loop(
        "loop_do_first_break",
        LoopKind.DO_FIRST,
        Sequence(
            "sequence_do_first_break_body",
            (
                Output("output_break_body", '"break body"'),
                Transfer("transfer_break", TransferKind.BREAK, ""),
            ),
        ),
        Sequence("sequence_do_first_break_else", (Output("output_break_else", '"wrong"'),)),
        condition="True",
    )
    wait = Loop(
        "loop_wait_else",
        LoopKind.WAIT,
        Sequence("sequence_wait_body", (Output("output_wait_body", '"wrong"'),)),
        Sequence("sequence_wait_else", (Output("output_wait_else", '"wait else"'),)),
        condition="True",
        delay_seconds="-1",
    )
    diagram = replace(
        diagram,
        body=replace(diagram.body, atoms=(do_first, interrupted, wait)),
    )
    project = _project(diagram)

    assert not [item for item in validate_project(project) if item.severity is Severity.ERROR]
    result = run_project(generate_python_project(project))
    assert result.return_code == 0
    assert result.stdout.splitlines() == ["first body", "first else", "break body", "wait else"]


def test_linked_call_tracks_callable_identity_across_rename_and_dependency_closure() -> None:
    caller = create_empty_drakon(identifier="main", title="Main")
    helper = create_empty_drakon(identifier="old_helper", title="Helper")
    helper = replace(
        helper,
        header=replace(
            helper.header,
            function=replace(
                helper.header.function,
                identifier="renamed_helper",
                parameters=(ParameterSpec("value", annotation="int"),),
                return_annotation="int",
            ),
        ),
        body=replace(
            helper.body,
            atoms=(Transfer("return_helper", TransferKind.RETURN, "value * 2"),),
        ),
    )
    caller = replace(
        caller,
        body=replace(
            caller.body,
            atoms=(
                Call(
                    "call_helper",
                    "old_helper(21)",
                    result_target="answer",
                    target_diagram_id=helper.id,
                    arguments="21",
                ),
                Output("output_answer", "answer"),
            ),
        ),
    )
    base = create_default_project()
    project = initialize_project_documents(
        replace(
            base,
            program_model=replace(
                base.program_model, entrypoint=ProgramEntryPoint("entrypoint:test", caller.id)
            ),
        ),
        (caller, helper),
    )

    assert not [item for item in validate_project(project) if item.severity is Severity.ERROR]
    generated = generate_python(project, include_main=False, focus_diagram_id=caller.id)
    assert "renamed_helper(21)" in generated.source
    assert "old_helper(21)" not in generated.source
    result = run_project(generate_python_project(project, focus_diagram_id=caller.id))
    assert result.stdout == "42\n"


def test_missing_linked_call_target_is_an_actionable_generation_error() -> None:
    diagram = create_empty_drakon()
    diagram = replace(
        diagram,
        body=replace(
            diagram.body,
            atoms=(
                Call(
                    "call_missing",
                    "missing()",
                    target_diagram_id="diagram_missing",
                ),
            ),
        ),
    )

    diagnostics = validate_project(_project(diagram))
    unresolved = next(item for item in diagnostics if item.code == "PY_UNRESOLVED_CALL")
    assert unresolved.object_id == "call_missing"
    assert unresolved.suggested_repair


def test_four_sequential_shelves_cover_typed_unpacking_chained_and_augmented_assignment() -> None:
    diagram = create_empty_drakon()
    diagram = replace(
        diagram,
        body=replace(
            diagram.body,
            atoms=(
                Assignment("shelf_typed", "first", "1", annotation="int"),
                Assignment("shelf_chained", "second = alias", "first + 1"),
                Assignment("shelf_unpacking", "left, right", "(3, 4)"),
                Assignment("shelf_augmented", "first", "5", operator="+="),
                Output("output_shelves", "(first, second, alias, left, right)"),
            ),
        ),
    )
    project = _project(diagram)

    assert not [item for item in validate_project(project) if item.severity is Severity.ERROR]
    result = run_project(generate_python_project(project))
    assert result.return_code == 0
    assert result.stdout == "(6, 2, 2, 3, 4)\n"


def test_tree_depth_first_and_breadth_first_have_documented_order() -> None:
    tree = "{1: [2, 3], 2: [4], 3: [], 4: []}"
    depth_first = Loop(
        "tree_depth_first",
        LoopKind.TREE_DFS,
        Sequence(
            "sequence_tree_depth_body",
            (Call("call_depth_append", "depth_order.append(node)"),),
        ),
        Sequence("sequence_tree_depth_else"),
        target="node",
        iterable="[1]",
        children="lambda node: tree[node]",
    )
    breadth_first = Loop(
        "tree_breadth_first",
        LoopKind.TREE_BFS,
        Sequence(
            "sequence_tree_breadth_body",
            (Call("call_breadth_append", "breadth_order.append(node)"),),
        ),
        Sequence("sequence_tree_breadth_else"),
        target="node",
        iterable="[1]",
        children="lambda node: tree[node]",
    )
    diagram = create_empty_drakon()
    diagram = replace(
        diagram,
        body=replace(
            diagram.body,
            atoms=(
                Assignment("tree_data", "tree", tree),
                Assignment("tree_depth_result", "depth_order", "[]"),
                depth_first,
                Assignment("tree_breadth_result", "breadth_order", "[]"),
                breadth_first,
                Output("tree_output", "(depth_order, breadth_order)"),
            ),
        ),
    )
    project = _project(diagram)

    assert not [item for item in validate_project(project) if item.severity is Severity.ERROR]
    result = run_project(generate_python_project(project))
    assert result.return_code == 0
    assert result.stdout == "([1, 2, 4, 3], [1, 2, 3, 4])\n"
