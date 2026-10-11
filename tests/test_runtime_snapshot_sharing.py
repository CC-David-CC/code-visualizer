"""Full trace snapshots share only exactly equal immutable records, with bounded cache ownership."""

from copy import deepcopy

import pytest

from code_visualizer.execution.debugger import DebugSession, DebugState, _decode_event
from code_visualizer.execution.runtime import (
    RuntimeBinding,
    RuntimeGraphAccumulator,
    decode_runtime_delta,
)


def _binding(**changes):
    return {
        "name": "value",
        "value_id": "value:1",
        "changed": False,
        "semantic_symbol_id": "symbol:1",
        "frame_id": "frame:1",
        **changes,
    }


def _event(sequence, bindings, locals=None):
    return {
        "sequence": sequence,
        "event": "trace",
        "trace_event": "line",
        "execution_session_id": "execution:test",
        "project_revision": 7,
        "artifact_revision": 7,
        "file_path": "app/main.py",
        "line": sequence + 1,
        "locals": {"value": "1"} if locals is None else locals,
        "runtime_snapshot": {
            "kind": "checkpoint",
            "frame_id": "frame:1",
            "history_index": sequence,
            "bindings": bindings,
            "values": [],
        },
    }


@pytest.mark.parametrize(
    "change",
    (
        {"name": "renamed"},
        {"value_id": "value:2"},
        {"changed": True},
        {"semantic_symbol_id": "symbol:2"},
        {"semantic_symbol_id": None},
        {"frame_id": "frame:2"},
    ),
    ids=("name", "value", "changed-flag", "symbol", "absent-symbol", "frame"),
)
def test_binding_reuse_compares_every_field_and_preserves_prior_snapshots(change):
    accumulator = RuntimeGraphAccumulator()
    local_pairs = {}
    first = _decode_event(_event(0, [_binding()]), DebugState.RUNNING, accumulator, local_pairs)
    unchanged = _decode_event(_event(1, [_binding()]), DebugState.RUNNING, accumulator, local_pairs)
    assert first is not None and unchanged is not None
    assert first.runtime_delta is not None and unchanged.runtime_delta is not None
    original = first.runtime_delta.bindings[0]
    assert unchanged.runtime_delta.bindings[0] is original
    raw = _event(2, [_binding(**change)])
    changed = _decode_event(raw, DebugState.RUNNING, accumulator, local_pairs)
    assert changed is not None and changed.runtime_delta is not None
    expected = decode_runtime_delta(
        raw["runtime_snapshot"],
        execution_session_id="execution:test",
        project_revision=7,
        artifact_revision=7,
        sequence=2,
    )
    assert changed.runtime_delta == expected
    assert changed.runtime_delta.bindings[0] is not original
    assert original == RuntimeBinding("value", "value:1", False, "symbol:1", "frame:1")
    assert first.runtime_graph is not None and unchanged.runtime_graph is not None
    assert first.runtime_graph.bindings == unchanged.runtime_graph.bindings == (original,)


def test_locals_share_equal_pairs_without_losing_changes_removals_or_historical_values():
    accumulator = RuntimeGraphAccumulator()
    local_pairs = {}
    first = _decode_event(
        _event(0, [], {"kept": "same", "changed": "before", "removed": "present"}),
        DebugState.RUNNING,
        accumulator,
        local_pairs,
    )
    second = _decode_event(
        _event(1, [], {"kept": "same", "changed": "after", "added": "new"}),
        DebugState.RUNNING,
        accumulator,
        local_pairs,
    )
    assert first is not None and second is not None
    assert first.locals == (("changed", "before"), ("kept", "same"), ("removed", "present"))
    assert second.locals == (("added", "new"), ("changed", "after"), ("kept", "same"))
    assert first.locals[1] is second.locals[2]
    assert first.locals[0] is not second.locals[1]
    assert set(local_pairs) == {"added", "changed", "kept"}
    _decode_event(_event(2, [], {}), DebugState.RUNNING, accumulator, local_pairs)
    assert local_pairs == {}
    assert first.locals[2] == ("removed", "present")


def test_record_allocation_scales_with_changed_records_not_full_retained_event_size(monkeypatch):
    original_init = RuntimeBinding.__init__
    created = 0

    def count_binding(self, *args, **kwargs):
        nonlocal created
        created += 1
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(RuntimeBinding, "__init__", count_binding)
    accumulator = RuntimeGraphAccumulator()
    local_pairs = {}
    events = []
    for index in range(500):
        raw = _event(
            index,
            [_binding(name=f"binding:{item}") for item in range(40)],
            {f"function_{item:04d}": f"<function {item}>" for item in range(index + 1)},
        )
        event = _decode_event(raw, DebugState.RUNNING, accumulator, local_pairs)
        assert event is not None
        events.append(event)
    assert created == 40, "Unchanged bindings must not allocate a new record per event"
    assert len(events) == 500
    assert sum(len(event.locals) for event in events) == 125_250
    assert len({id(pair) for event in events for pair in event.locals}) == 500
    assert len(local_pairs) == 500
    assert len(accumulator._bindings) == 40
    for index, event in enumerate(events):
        assert len(event.locals) == index + 1
        assert event.locals[-1] == (f"function_{index:04d}", f"<function {index}>")
        assert event.runtime_delta is not None and len(event.runtime_delta.bindings) == 40
        assert event.runtime_graph is not None
        assert event.runtime_graph.bindings is event.runtime_delta.bindings


def test_binding_cache_drops_removed_records_and_reset_or_other_session_never_reuses_them():
    first_session, second_session = DebugSession(), DebugSession()
    raw = _event(0, [_binding()])
    original_raw = deepcopy(raw)
    first = _decode_event(
        raw, DebugState.RUNNING, first_session._runtime, first_session._local_pairs
    )
    second = _decode_event(
        raw, DebugState.RUNNING, second_session._runtime, second_session._local_pairs
    )
    assert first is not None and second is not None and first == second
    assert first.runtime_delta is not None and second.runtime_delta is not None
    binding = first.runtime_delta.bindings[0]
    assert binding is not second.runtime_delta.bindings[0]
    assert first.locals[0] is not second.locals[0]
    assert raw == original_raw

    _decode_event(
        _event(1, [], {}), DebugState.RUNNING, first_session._runtime, first_session._local_pairs
    )
    assert first_session._runtime._bindings == {}
    reintroduced = _decode_event(
        _event(2, [_binding()]),
        DebugState.RUNNING,
        first_session._runtime,
        first_session._local_pairs,
    )
    assert reintroduced is not None and reintroduced.runtime_delta is not None
    assert reintroduced.runtime_delta.bindings[0] == binding
    assert reintroduced.runtime_delta.bindings[0] is not binding
    first_session._runtime.reset()
    assert first_session._runtime._bindings == {}
    assert first.runtime_delta.bindings[0] is binding
