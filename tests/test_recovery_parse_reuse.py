"""Recovery reuses decoding while continuing to observe the bounded disk inputs."""

from dataclasses import replace

import pytest

import code_visualizer.persistence.store as persistence
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.persistence.store import ProjectStore, ProjectStoreError


def test_identical_project_and_snapshot_parse_once_per_recovery(monkeypatch, tmp_path):
    project = create_default_project()
    store = ProjectStore(tmp_path)
    store.initialize(project)
    parsed = []
    reads = []
    decode = persistence.project_from_json
    read = store._bounded_read

    def record_decode(source):
        parsed.append(source)
        return decode(source)

    def record_read(path, limit):
        reads.append(path)
        return read(path, limit)

    monkeypatch.setattr(persistence, "project_from_json", record_decode)
    monkeypatch.setattr(store, "_bounded_read", record_read)
    for recovery_count in (1, 2):
        assert store.recover(promote=False) == project
        assert len(parsed) == recovery_count
        assert reads.count(store.project_file) == 2 * recovery_count
        assert reads.count(store.snapshots_root / "00000000000000000000.json") == recovery_count


def test_final_disk_reread_decodes_changed_bytes_and_does_not_overwrite_newer_file(
    monkeypatch, tmp_path
):
    project = create_default_project()
    store = ProjectStore(tmp_path)
    store.initialize(project)
    snapshot = replace(project, revision=2, title="Recoverable snapshot")
    external = replace(project, revision=3, title="External writer")
    store.write_snapshot(snapshot)
    parsed = []
    decode = persistence.project_from_json

    def record_decode(source):
        parsed.append(source)
        return decode(source)

    def replace_durable_file_before_final_read():
        store.save(external)
        return ()

    monkeypatch.setattr(persistence, "project_from_json", record_decode)
    monkeypatch.setattr(store, "read_journal", replace_durable_file_before_final_read)
    assert store.recover() == snapshot
    assert parsed == [
        normalized_project_json(project),
        normalized_project_json(snapshot),
        normalized_project_json(external),
    ]
    assert store.project_file.read_text(encoding="utf-8") == normalized_project_json(external)


def test_changed_recovery_sources_still_validate_each_project_identity(monkeypatch, tmp_path):
    project = create_default_project()
    store = ProjectStore(tmp_path)
    store.initialize(project)
    store.write_snapshot(replace(project, id="foreign-project", revision=1))
    with pytest.raises(ProjectStoreError, match="more than one project identity"):
        store.recover()
    assert store.load() == project


def test_recovery_source_memo_remains_bounded_and_revalidates_evicted_text(monkeypatch, tmp_path):
    project = create_default_project()
    later = replace(project, revision=1, title="Later snapshot")
    store = ProjectStore(tmp_path)
    store.initialize(project)
    store.write_snapshot(later)
    limit = max(len(normalized_project_json(value).encode("utf-8")) for value in (project, later))
    monkeypatch.setattr(persistence, "MAX_PROJECT_JSON_BYTES", limit)
    parsed = []
    decode = persistence.project_from_json

    def record_decode(source):
        parsed.append(source)
        return decode(source)

    monkeypatch.setattr(persistence, "project_from_json", record_decode)
    assert store.recover(promote=False) == later
    assert parsed == [
        normalized_project_json(project),
        normalized_project_json(later),
        normalized_project_json(project),
    ]
