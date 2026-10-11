"""Shared palette-to-recipe projection for drag previews and library icons."""

from __future__ import annotations

from code_visualizer.domain.drakon_defaults import MACROICON_INVENTORY
from code_visualizer.rendering.recipes import RecipeKind


def preview_for_atom_kind(kind: str) -> tuple[RecipeKind, dict[str, str]]:
    if kind.startswith("macro:"):
        macro_id = kind.removeprefix("macro:")
        macro = next((item for item in MACROICON_INVENTORY if item.id == macro_id), None)
        if macro is None:
            raise KeyError(f"No visual preview for macroicon {macro_id!r}")
        return preview_for_atom_kind(macro.preview_atom_kind)
    if kind == "assignment":
        return RecipeKind.ASSIGNMENT, {"target": "result", "value": "None"}
    direct: dict[str, tuple[RecipeKind, str, str]] = {
        "action": (RecipeKind.ACTION, "source", 'print("action")'),
        "output": (RecipeKind.OUTPUT, "expression", '"output"'),
        "input": (RecipeKind.INPUT, "input", 'value ← input("Input: ")'),
        "call": (RecipeKind.CALL, "call", "print('called')"),
        "await_call": (RecipeKind.CALL, "call", "await operation()"),
        "if": (RecipeKind.IF, "condition", "condition"),
        "select": (RecipeKind.SELECT, "select", "ordered select"),
        "match_select": (RecipeKind.SELECT, "select", "match value"),
        "with": (RecipeKind.CALL, "with", "with context"),
        "async_with": (RecipeKind.CALL, "with", "async with context"),
        "try": (RecipeKind.SELECT, "try", "try · except"),
        "try_star": (RecipeKind.SELECT, "try", "try · except*"),
        "return": (RecipeKind.SILHOUETTE_TRANSITION, "transfer", "return None"),
        "raise": (RecipeKind.SILHOUETTE_TRANSITION, "transfer", "raise error"),
        "yield": (RecipeKind.SILHOUETTE_TRANSITION, "transfer", "yield value"),
        "yield_from": (RecipeKind.SILHOUETTE_TRANSITION, "transfer", "yield from values"),
        "break": (RecipeKind.LOOP_RETURN, "transfer", "break"),
        "continue": (RecipeKind.LOOP_RETURN, "transfer", "continue"),
        "pass": (RecipeKind.ACTION, "source", "pass"),
        "delete": (RecipeKind.ACTION, "source", "del temporary"),
        "global": (RecipeKind.ACTION, "source", "global shared_value"),
        "nonlocal": (RecipeKind.ACTION, "source", "nonlocal captured_value"),
        "assert": (RecipeKind.ACTION, "source", "assert condition"),
        "expression": (RecipeKind.ACTION, "source", "operation()"),
        "delay": (RecipeKind.DELAY, "delay", "delay 0.1 s"),
        "async_delay": (RecipeKind.DELAY, "delay", "async delay 0.1 s"),
        "start_timer": (RecipeKind.START_TIMER, "timer", "start timer · operation"),
        "synchronizer": (RecipeKind.SYNCHRONIZER, "sync", "operation ≤ 1.0 s"),
        "parallel": (RecipeKind.CONCURRENT_BOUNDARY, "parallel", "2 parallel processes"),
        "async_parallel": (
            RecipeKind.CONCURRENT_BOUNDARY,
            "parallel",
            "2 async processes",
        ),
        "realtime_process": (
            RecipeKind.REALTIME_PROCESS,
            "process",
            "realtime process",
        ),
        "silhouette": (RecipeKind.BRANCH_HEADER, "silhouette", "Golden Node · 2 states"),
        "note": (RecipeKind.NOTE_RICH, "note", "Explain the intent here"),
        "note_left": (RecipeKind.NOTE_LEFT, "note", "Left note"),
        "note_right": (RecipeKind.NOTE_RIGHT, "note", "Right note"),
    }
    loop_labels = {
        "while_loop": "while condition",
        "do_first_loop": "do first · while condition",
        "for_loop": "for item in iterable",
        "async_for_loop": "async for item in iterable",
        "wait_loop": "wait until ready",
        "tree_dfs_loop": "TREE DFS",
        "tree_bfs_loop": "TREE BFS",
    }
    if kind in loop_labels:
        return RecipeKind.FOR_START, {"loop": loop_labels[kind]}
    if kind in {"period", "async_period"}:
        return RecipeKind.PERIOD, {
            "timer": "async operation" if kind == "async_period" else "operation",
            "seconds": "1.0 s",
        }
    try:
        recipe, role, text = direct[kind]
    except KeyError as exc:
        raise KeyError(f"No visual preview for atom kind {kind!r}") from exc
    return recipe, {role: text}
