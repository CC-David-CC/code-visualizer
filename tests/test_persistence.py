from dataclasses import replace

import pytest

from code_visualizer.application.messages import CommandRejected
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.application.session import ProjectSession
from code_visualizer.persistence import (
    JournalRecord,
    ProjectLeaseConflict,
    ProjectStore,
)
from code_visualizer.persistence.store import ProjectStoreError


def test_store_initializes_saves_and_loads_project(tmp_path) -> None:
    store = ProjectStore(tmp_path / "demo", snapshot_interval=2)
    project = create_default_project(title="Saved Project")

    store.initialize(project)
    loaded = store.load()

    assert loaded == project
    assert store.project_file.is_file()
    assert (store.snapshots_root / "00000000000000000000.json").is_file()


def test_recovery_promotes_newest_durable_journal_revision(tmp_path) -> None:
    store = ProjectStore(tmp_path / "demo")
    original = create_default_project(title="Before")
    store.initialize(original)
    updated = replace(original, title="After", revision=1)
    store.append(
        JournalRecord(
            revision=1,
            actor_id="human",
            operation_id="op-1",
            command_type="project.rename",
            project=updated,
            occurred_at="2026-08-29T00:00:00+00:00",
        )
    )

    recovered = store.recover()

    assert recovered == updated
    assert store.load() == updated


def test_truncated_final_journal_record_does_not_destroy_recovery(tmp_path) -> None:
    store = ProjectStore(tmp_path / "demo")
    project = create_default_project()
    store.initialize(project)
    store.append(
        JournalRecord(
            revision=0,
            actor_id="system",
            operation_id="initial",
            command_type="project.snapshot",
            project=project,
            occurred_at="2026-08-29T00:00:00+00:00",
        )
    )
    with store.journal_file.open("a", encoding="utf-8") as stream:
        stream.write('{"revision":')

    assert store.recover() == project


def test_interrupted_atomic_replace_keeps_previous_snapshot(monkeypatch, tmp_path) -> None:
    store = ProjectStore(tmp_path / "demo")
    original = create_default_project(title="Durable")
    store.initialize(original)
    before = store.project_file.read_bytes()

    def fail_replace(_source, _target) -> None:
        raise OSError("injected replace interruption")

    monkeypatch.setattr("code_visualizer.persistence.store.os.replace", fail_replace)
    with pytest.raises(ProjectStoreError, match="injected replace interruption"):
        store.save(replace(original, title="Must not appear"))

    assert store.project_file.read_bytes() == before
    assert not tuple(store.root.glob(".project.json.*.tmp"))


def test_failed_journal_fsync_rejects_command_without_recoverable_ghost_revision(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "journal-fsync"
    session = ProjectSession.new()
    session.save_as(root)
    original = session.authority.snapshot()
    prior_journal = ProjectStore(root).read_journal()

    with monkeypatch.context() as patcher:
        patcher.setattr(
            "code_visualizer.persistence.store.os.fsync",
            lambda _descriptor: (_ for _ in ()).throw(OSError("injected journal fsync")),
        )
        result = session.client.rename_project("Rejected title")

    assert isinstance(result, CommandRejected)
    assert result.code == "PERSISTENCE_FAILED"
    assert session.authority.snapshot() == original
    assert ProjectStore(root).read_journal() == prior_journal
    session.close()

    reopened = ProjectSession.open(root)
    try:
        assert reopened.authority.snapshot() == original
    finally:
        reopened.close()


def test_project_lease_prevents_two_writers_and_allows_explicit_read_only(tmp_path) -> None:
    root = tmp_path / "leased"
    owner = ProjectSession.new(actor_id="owner")
    owner.save_as(root)
    try:
        with pytest.raises(ProjectLeaseConflict) as conflict:
            ProjectSession.open(root, actor_id="second-writer")
        assert conflict.value.owner["owner_id"] == "owner"

        before = (root / "project.json").read_bytes()
        viewer = ProjectSession.open(root, actor_id="viewer", read_only=True)
        try:
            assert viewer.authority.is_read_only
            result = viewer.client.rename_project("Forbidden")
            assert isinstance(result, CommandRejected)
            assert result.code == "PROJECT_READ_ONLY"
            assert (root / "project.json").read_bytes() == before
        finally:
            viewer.close()
    finally:
        owner.close()

    successor = ProjectSession.open(root, actor_id="successor")
    successor.close()


def test_bounded_project_load_rejects_oversized_native_file(monkeypatch, tmp_path) -> None:
    store = ProjectStore(tmp_path / "bounded")
    store.initialize(create_default_project())
    monkeypatch.setattr("code_visualizer.persistence.store.MAX_PROJECT_JSON_BYTES", 32)

    with pytest.raises(ProjectStoreError, match="safety limit"):
        store.load()


def test_read_only_recovery_never_promotes_or_rewrites_files(tmp_path) -> None:
    store = ProjectStore(tmp_path / "recovery")
    original = create_default_project(title="Snapshot")
    store.initialize(original)
    recovered = replace(original, title="Journal", revision=1)
    store.append(
        JournalRecord(
            revision=1,
            actor_id="human",
            operation_id="rename",
            command_type="project.rename",
            project=recovered,
            occurred_at="2026-08-29T00:00:00+00:00",
        )
    )
    store.project_file.write_text("{interrupted", encoding="utf-8")
    before = store.project_file.read_bytes()

    assert store.recover(promote=False) == recovered
    assert store.project_file.read_bytes() == before
