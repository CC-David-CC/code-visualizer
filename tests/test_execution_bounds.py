import threading

from code_visualizer.domain.invocation import InvocationSpec
from code_visualizer.execution import RunResult, RunSession, run_source


def test_large_child_output_is_drained_but_strictly_bounded() -> None:
    result = run_source(
        'def main():\n    print("x" * 100_000)\n',
        invocation=InvocationSpec("main"),
        output_limit=1_024,
    )

    assert result.return_code == 0
    assert result.output_truncated
    assert len(result.stdout) < 1_100
    assert "output truncated" in result.stdout


def test_run_session_stops_a_nonterminating_child() -> None:
    session = RunSession()
    completed = threading.Event()
    results: list[RunResult] = []

    def receive(result: RunResult) -> None:
        results.append(result)
        completed.set()

    session.start_source(
        "def main():\n    while True:\n        pass\n",
        invocation=InvocationSpec("main"),
        completed=receive,
    )
    assert session.stop()
    assert completed.wait(3.0)
    assert results[0].termination_reason == "stopped"
    assert not results[0].timed_out
