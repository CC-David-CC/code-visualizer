"""Static contract reuse must not cache mutable registries or worker launch paths."""

from code_visualizer.application.computation_process import default_profiles
from code_visualizer.execution import child_process
from code_visualizer.extensions import builtin


def test_profiles_share_only_inert_contract_keys_per_static_composition(monkeypatch):
    original = builtin.builtin_registry
    calls = []

    def composition():
        calls.append("first")
        return original()

    monkeypatch.setattr(builtin, "builtin_registry", composition)
    monkeypatch.setattr(child_process, "computation_worker_command", lambda _: ["source-worker"])
    first = default_profiles()[0]
    monkeypatch.setattr(child_process, "computation_worker_command", lambda _: ["frozen-worker"])
    second = default_profiles()[0]
    assert calls == ["first"]
    assert first.command == ("source-worker",)
    assert second.command == ("frozen-worker",)
    assert second.backend_keys is first.backend_keys
    assert ("code_visualizer.python", "1") in second.backend_keys

    def different_composition():
        calls.append("second")
        return original()

    monkeypatch.setattr(builtin, "builtin_registry", different_composition)
    assert default_profiles()[0].backend_keys == first.backend_keys
    assert calls == ["first", "second"]
