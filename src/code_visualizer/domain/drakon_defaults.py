"""Discoverable, context-valid defaults for every semantic DRAKON construct.

The command layer and visual library share these stable kind names.  Defaults
are deliberately executable: inserting an icon never opens a modal editor and
never introduces placeholder text that breaks Python generation.
"""

from __future__ import annotations

from dataclasses import dataclass

from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Case,
    ContextItem,
    Delay,
    DrakonAtom,
    ExceptionHandler,
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
from code_visualizer.domain.program_kinds import (
    LoopKind,
    NotePlacement,
    ParallelMode,
    SelectMode,
    SimpleKind,
    TransferKind,
)


@dataclass(frozen=True, slots=True)
class AtomKindInfo:
    kind: str
    label: str
    category: str
    description: str


@dataclass(frozen=True, slots=True)
class MacroiconInfo:
    id: str
    label: str
    description: str
    preview_atom_kind: str


MACROICON_INVENTORY: tuple[MacroiconInfo, ...] = (
    MacroiconInfo("header_parameters", "Header with Parameters", "Add a typed parameter", "action"),
    MacroiconInfo("binary_if", "Binary If", "Complete preferred/alternate decision", "if"),
    MacroiconInfo("select", "Select", "Complete ordered Select", "select"),
    MacroiconInfo("conditional_loop", "Conditional Loop", "Complete While loop", "while_loop"),
    MacroiconInfo(
        "select_loop", "Select Loop", "Select nested in a conditional loop", "while_loop"
    ),
    MacroiconInfo("for_loop", "For Loop", "Complete iterable For loop", "for_loop"),
    MacroiconInfo("wait_loop", "Wait Loop", "Complete polling loop", "wait_loop"),
    MacroiconInfo("timed_action", "Timed Action", "Timer, Action, and deadline fork", "action"),
    MacroiconInfo(
        "timed_shelf", "Timed Shelf", "Timer, Assignment, and deadline fork", "assignment"
    ),
    MacroiconInfo("timed_fork", "Timed Fork", "Timer, If, and deadline fork", "if"),
    MacroiconInfo("timed_select", "Timed Select", "Timer, Select, and deadline fork", "select"),
    MacroiconInfo(
        "timed_conditional_loop",
        "Timed Conditional Loop",
        "Timer, While loop, and deadline fork",
        "while_loop",
    ),
    MacroiconInfo(
        "timed_select_loop",
        "Timed Select Loop",
        "Timer and a Select nested in a loop",
        "while_loop",
    ),
    MacroiconInfo(
        "timed_for_loop", "Timed For Loop", "Timer, For loop, and deadline fork", "for_loop"
    ),
    MacroiconInfo(
        "timed_wait_loop", "Timed Wait Loop", "Timer, Wait loop, and deadline fork", "wait_loop"
    ),
    MacroiconInfo("timed_call", "Timed Call", "Timer, Call, and deadline fork", "call"),
    MacroiconInfo("timed_output", "Timed Output", "Timer, Output, and deadline fork", "output"),
    MacroiconInfo("timed_input", "Timed Input", "Timer, Input, and deadline fork", "input"),
    MacroiconInfo(
        "timed_start_timer",
        "Timed Start Timer",
        "Start a timer and expose its deadline routes",
        "start_timer",
    ),
    MacroiconInfo(
        "timed_parallel",
        "Timed Parallel",
        "Timer, parallel processes, and deadline fork",
        "parallel",
    ),
    MacroiconInfo("tree_loop", "TREE Loop", "Complete depth-first tree traversal", "tree_dfs_loop"),
)


ATOM_KIND_INVENTORY: tuple[AtomKindInfo, ...] = (
    AtomKindInfo("action", "Action", "Core", "One simple Python statement"),
    AtomKindInfo("assignment", "Assignment / Shelf", "Core", "Typed Python assignment"),
    AtomKindInfo("output", "Output", "I/O", "Print or write a Python expression"),
    AtomKindInfo("input", "Input", "I/O", "Read and optionally convert input"),
    AtomKindInfo("call", "Call", "Core", "Call a function and optionally keep its result"),
    AtomKindInfo("await_call", "Await Call", "Async", "Await a function call"),
    AtomKindInfo("if", "If", "Decisions", "Binary decision with explicit routes"),
    AtomKindInfo("select", "Select Conditions", "Decisions", "Ordered condition branches"),
    AtomKindInfo("match_select", "Match / Case", "Decisions", "Python match with guards"),
    AtomKindInfo("while_loop", "While Loop", "Loops", "Pre-tested conditional loop"),
    AtomKindInfo("do_first_loop", "Do-first Loop", "Loops", "Run once before testing"),
    AtomKindInfo("for_loop", "For Loop", "Loops", "Iterate over any Python iterable"),
    AtomKindInfo("async_for_loop", "Async For Loop", "Async", "Iterate asynchronously"),
    AtomKindInfo("wait_loop", "Wait Loop", "Timing", "Poll until a condition becomes true"),
    AtomKindInfo("tree_dfs_loop", "TREE Loop · DFS", "Loops", "Depth-first tree traversal"),
    AtomKindInfo("tree_bfs_loop", "TREE Loop · BFS", "Loops", "Breadth-first tree traversal"),
    AtomKindInfo("with", "With", "Python", "One or more context managers"),
    AtomKindInfo("async_with", "Async With", "Async", "Asynchronous context managers"),
    AtomKindInfo("try", "Try", "Python", "Try / except / else / finally"),
    AtomKindInfo("try_star", "Try · except*", "Python", "Handle exception groups"),
    AtomKindInfo("return", "Return", "Transfers", "Return from the current function"),
    AtomKindInfo("raise", "Raise", "Transfers", "Raise an exception"),
    AtomKindInfo("yield", "Yield", "Transfers", "Yield one value"),
    AtomKindInfo("yield_from", "Yield From", "Transfers", "Delegate to an iterable"),
    AtomKindInfo("break", "Break", "Transfers", "Exit the containing loop"),
    AtomKindInfo("continue", "Continue", "Transfers", "Continue the containing loop"),
    AtomKindInfo("pass", "Pass", "Simple", "Explicit no-op"),
    AtomKindInfo("delete", "Delete", "Simple", "Delete a target"),
    AtomKindInfo("global", "Global", "Simple", "Declare global names"),
    AtomKindInfo("nonlocal", "Nonlocal", "Simple", "Declare nonlocal names"),
    AtomKindInfo("assert", "Assert", "Simple", "Assert a condition with an optional message"),
    AtomKindInfo("expression", "Expression", "Simple", "Evaluate an expression for effects"),
    AtomKindInfo("delay", "Delay", "Timing", "Blocking delay"),
    AtomKindInfo("async_delay", "Async Delay", "Async", "Cooperative asynchronous delay"),
    AtomKindInfo("start_timer", "Start Timer", "Timing", "Capture a monotonic timer"),
    AtomKindInfo("period", "Period", "Timing", "Maintain a fixed blocking cadence"),
    AtomKindInfo("async_period", "Async Period", "Async", "Maintain an async cadence"),
    AtomKindInfo("synchronizer", "Synchronizer", "Timing", "Branch on a timer deadline"),
    AtomKindInfo("parallel", "Parallel Processes", "Concurrency", "Run branches in threads"),
    AtomKindInfo("async_parallel", "Async Parallel", "Concurrency", "Run branches in a TaskGroup"),
    AtomKindInfo("realtime_process", "Realtime Process", "Concurrency", "Invoke one process step"),
    AtomKindInfo("silhouette", "Silhouette", "DRAKON", "Named finite state silhouette"),
    AtomKindInfo("note", "Rich Note", "Notes", "Explanatory note"),
    AtomKindInfo("note_left", "Left Note", "Notes", "Left-side explanatory note"),
    AtomKindInfo("note_right", "Right Note", "Notes", "Right-side explanatory note"),
)


def supported_atom_kinds() -> frozenset[str]:
    return frozenset(item.kind for item in ATOM_KIND_INVENTORY)


def _sequence(owner: str, role: str, *atoms: DrakonAtom) -> Sequence:
    return Sequence(f"sequence_{owner}_{role}", tuple(atoms))


def _action(owner: str, role: str, message: str) -> Action:
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    return Action(f"atom_{owner}_{role}", f'print("{escaped}")')


def _loop(atom_id: str, kind: LoopKind) -> Loop:
    labels = {
        LoopKind.WHILE: "while loop action",
        LoopKind.DO_FIRST: "do-first loop action",
        LoopKind.FOR: "for loop action",
        LoopKind.ASYNC_FOR: "async for loop action",
        LoopKind.WAIT: "wait loop action",
        LoopKind.TREE_DFS: "tree DFS action",
        LoopKind.TREE_BFS: "tree BFS action",
    }
    condition = "True" if kind is LoopKind.WAIT else "False"
    return Loop(
        id=atom_id,
        loop_kind=kind,
        body=_sequence(atom_id, "body", _action(atom_id, "body_action", labels[kind])),
        else_body=_sequence(atom_id, "else"),
        condition=condition,
        target="item",
        iterable=(
            "_cv_async_iter(range(3))"
            if kind is LoopKind.ASYNC_FOR
            else "[{'children': []}]"
            if kind in {LoopKind.TREE_DFS, LoopKind.TREE_BFS}
            else "range(3)"
        ),
        children="lambda node: node.get('children', [])",
        delay_seconds="0.1",
    )


def create_default_atom(atom_kind: str, atom_id: str) -> DrakonAtom:
    """Create a complete, executable semantic construct without prompting."""

    if atom_kind == "action":
        return Action(atom_id, 'print("action")')
    if atom_kind == "assignment":
        return Assignment(atom_id, "result", "None")
    if atom_kind == "output":
        return Output(atom_id, '"output"')
    if atom_kind == "input":
        return Input(atom_id, "value", '"Input: "')
    if atom_kind in {"call", "await_call"}:
        expression = "_cv_asyncio.sleep(0)" if atom_kind == "await_call" else "print('called')"
        return Call(atom_id, expression, atom_kind == "await_call")
    if atom_kind == "if":
        return If(
            atom_id,
            "True",
            _sequence(
                atom_id,
                "true",
                _action(atom_id, "true_action", "true branch action"),
            ),
            _sequence(
                atom_id,
                "false",
                _action(atom_id, "false_action", "false branch action"),
            ),
        )
    if atom_kind in {"select", "match_select"}:
        first = Case(
            f"case_{atom_id}_first",
            "First",
            _sequence(
                atom_id,
                "case_first",
                _action(atom_id, "case_first_action", "first case action"),
            ),
            condition="value == 1",
            pattern="1",
        )
        fallback = Case(
            f"case_{atom_id}_default",
            "Otherwise",
            _sequence(
                atom_id,
                "case_default",
                _action(atom_id, "case_default_action", "default case action"),
            ),
            condition="True",
            pattern="_",
            is_default=True,
        )
        return Select(
            atom_id,
            expression="value",
            cases=(first, fallback),
            mode=SelectMode.MATCH if atom_kind == "match_select" else SelectMode.CONDITIONS,
            preferred_case_id=first.id,
        )
    loop_kinds = {
        "while_loop": LoopKind.WHILE,
        "do_first_loop": LoopKind.DO_FIRST,
        "for_loop": LoopKind.FOR,
        "async_for_loop": LoopKind.ASYNC_FOR,
        "wait_loop": LoopKind.WAIT,
        "tree_dfs_loop": LoopKind.TREE_DFS,
        "tree_bfs_loop": LoopKind.TREE_BFS,
    }
    if atom_kind in loop_kinds:
        return _loop(atom_id, loop_kinds[atom_kind])
    if atom_kind in {"with", "async_with"}:
        return With(
            atom_id,
            (
                ContextItem(
                    f"context_{atom_id}_1",
                    "_cv_asyncio.timeout(None)" if atom_kind == "async_with" else "nullcontext()",
                    "resource" if atom_kind == "with" else None,
                ),
            ),
            _sequence(atom_id, "with", _action(atom_id, "with_action", "with action")),
            atom_kind == "async_with",
        )
    if atom_kind in {"try", "try_star"}:
        return Try(
            atom_id,
            _sequence(atom_id, "try", _action(atom_id, "try_action", "try action")),
            (
                ExceptionHandler(
                    f"handler_{atom_id}_exception",
                    "Exception",
                    "error",
                    _sequence(
                        atom_id,
                        "except",
                        _action(atom_id, "except_action", "exception action"),
                    ),
                ),
            ),
            _sequence(atom_id, "try_else"),
            _sequence(atom_id, "finally"),
            atom_kind == "try_star",
        )
    transfers = {
        "return": TransferKind.RETURN,
        "raise": TransferKind.RAISE,
        "yield": TransferKind.YIELD,
        "yield_from": TransferKind.YIELD_FROM,
        "break": TransferKind.BREAK,
        "continue": TransferKind.CONTINUE,
    }
    if atom_kind in transfers:
        expression = "RuntimeError('error')" if atom_kind == "raise" else "None"
        if atom_kind in {"break", "continue"}:
            expression = ""
        return Transfer(atom_id, transfers[atom_kind], expression)
    simple = {
        "pass": (SimpleKind.PASS, "pass", None),
        "delete": (SimpleKind.DELETE, "temporary", None),
        "global": (SimpleKind.GLOBAL, "shared_value", None),
        "nonlocal": (SimpleKind.NONLOCAL, "captured_value", None),
        "assert": (SimpleKind.ASSERT, "True", '"assertion failed"'),
        "expression": (SimpleKind.EXPRESSION, "print('expression action')", None),
    }
    if atom_kind in simple:
        statement_kind, source, secondary = simple[atom_kind]
        return SimpleStatement(atom_id, statement_kind, source, secondary)
    if atom_kind in {"delay", "async_delay"}:
        return Delay(atom_id, "0.1", atom_kind == "async_delay")
    if atom_kind == "start_timer":
        return StartTimer(atom_id, "operation")
    if atom_kind in {"period", "async_period"}:
        return Period(atom_id, "operation", "1.0", atom_kind == "async_period")
    if atom_kind == "synchronizer":
        return Synchronizer(
            atom_id,
            "operation",
            "1.0",
            _sequence(atom_id, "on_time", _action(atom_id, "on_time_action", "on time")),
            _sequence(
                atom_id,
                "on_timeout",
                _action(atom_id, "on_timeout_action", "timed out"),
            ),
        )
    if atom_kind in {"parallel", "async_parallel"}:
        return Parallel(
            atom_id,
            (
                ParallelBranch(
                    f"branch_{atom_id}_one",
                    "First process",
                    _sequence(
                        atom_id,
                        "parallel_one",
                        _action(atom_id, "parallel_one_action", "first process"),
                    ),
                ),
                ParallelBranch(
                    f"branch_{atom_id}_two",
                    "Second process",
                    _sequence(
                        atom_id,
                        "parallel_two",
                        _action(atom_id, "parallel_two_action", "second process"),
                    ),
                ),
            ),
            ParallelMode.ASYNC if atom_kind == "async_parallel" else ParallelMode.SYNC,
        )
    if atom_kind == "realtime_process":
        return RealtimeProcess(atom_id, "print('realtime process')")
    if atom_kind == "silhouette":
        start_id = f"branch_{atom_id}_start"
        finish_id = f"branch_{atom_id}_finish"
        return Silhouette(
            atom_id,
            "Golden Node",
            "golden_node",
            (
                SilhouetteBranch(
                    start_id,
                    "Start",
                    _sequence(
                        atom_id,
                        "state_start",
                        _action(atom_id, "state_start_action", "start state action"),
                    ),
                    finish_id,
                ),
                SilhouetteBranch(
                    finish_id,
                    "Finish",
                    _sequence(
                        atom_id,
                        "state_finish",
                        _action(atom_id, "state_finish_action", "finish state action"),
                    ),
                    None,
                ),
            ),
            start_id,
        )
    note_placements = {
        "note": NotePlacement.RICH,
        "note_left": NotePlacement.LEFT,
        "note_right": NotePlacement.RIGHT,
    }
    if atom_kind in note_placements:
        return Note(atom_id, "Explain the intent here.", note_placements[atom_kind])
    raise KeyError(atom_kind)
