"""Readers and whole-directory promotion share one brief filesystem boundary."""

import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from pathlib import Path
from threading import Event, current_thread

import pytest

from code_visualizer.application.project_factory import create_default_project
from code_visualizer.generation import artifacts


def _saved_artifacts(tmp_path, monkeypatch):
    project = create_default_project()
    root = tmp_path / "generated"
    root.mkdir()
    (root / "module.py").write_bytes(b"old\n")
    (root / "generation.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "revision": project.revision,
                "files": {"module.py": hashlib.sha256(b"old\n").hexdigest()},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        artifacts, "expected_artifact_contents", lambda *_args, **_kwargs: {"module.py": "new\n"}
    )
    return project, root


@pytest.mark.parametrize("reader_kind", ("preview", "inspection", "manifest"))
@pytest.mark.parametrize("superseded", (False, True))
def test_open_readers_finish_before_promotion_and_revision_is_rechecked(
    tmp_path, monkeypatch, reader_kind, superseded
):
    project, root = _saved_artifacts(tmp_path, monkeypatch)
    opened, release, staged = Event(), Event(), Event()
    original_open, original_write = Path.open, artifacts._write_text
    held_path = root / ("module.py" if reader_kind == "preview" else "generation.json")

    @contextmanager
    def held_open(path, *args, **kwargs):
        with original_open(path, *args, **kwargs) as stream:
            if current_thread().name.startswith("artifact-reader") and path == held_path:
                opened.set()
                assert release.wait(5)
            yield stream

    def write(path, contents):
        original_write(path, contents)
        staged.set()

    monkeypatch.setattr(Path, "open", held_open)
    monkeypatch.setattr(artifacts, "_write_text", write)
    readers = {
        "preview": lambda: artifacts.read_artifact_text(tmp_path, "module.py"),
        "inspection": lambda: artifacts.inspect_generation(tmp_path),
        "manifest": lambda: artifacts.load_generation_manifest(tmp_path),
    }
    revision = [project.revision]
    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="artifact-reader") as reader_pool,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix="artifact-writer") as writer_pool,
    ):
        read = reader_pool.submit(readers[reader_kind])
        try:
            assert opened.wait(5)
            generated = writer_pool.submit(
                artifacts.generate_to_disk,
                project,
                tmp_path,
                current_revision=lambda: revision[0],
            )
            assert staged.wait(5)
            with pytest.raises(TimeoutError):
                generated.result(timeout=0.1)
            if superseded:
                revision[0] += 1
        finally:
            release.set()
        value = read.result(timeout=5)
        if reader_kind == "preview":
            assert value == "old\n"
        elif reader_kind == "inspection":
            assert value.clean
        else:
            assert value["revision"] == project.revision
        if superseded:
            with pytest.raises(artifacts.StaleGenerationError):
                generated.result(timeout=5)
        else:
            assert generated.result(timeout=5).revision == project.revision
    assert (root / "module.py").read_text(encoding="utf-8") == ("old\n" if superseded else "new\n")


def test_preview_never_observes_the_gap_between_directory_renames(tmp_path, monkeypatch):
    project, root = _saved_artifacts(tmp_path, monkeypatch)
    moved, release = Event(), Event()
    original_replace = artifacts.os.replace

    def replace(source, target):
        original_replace(source, target)
        if source == root:
            moved.set()
            assert release.wait(5)

    monkeypatch.setattr(artifacts.os, "replace", replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        generated = pool.submit(artifacts.generate_to_disk, project, tmp_path)
        try:
            assert moved.wait(5)
            read = pool.submit(artifacts.read_artifact_text, tmp_path, "module.py")
            with pytest.raises(TimeoutError):
                read.result(timeout=0.1)
        finally:
            release.set()
        assert generated.result(timeout=5).revision == project.revision
        assert read.result(timeout=5) == "new\n"


def test_expensive_build_work_does_not_block_artifact_readers(tmp_path, monkeypatch):
    project, _root = _saved_artifacts(tmp_path, monkeypatch)
    building, release = Event(), Event()

    def build(*_args, **_kwargs):
        building.set()
        assert release.wait(5)
        return {"module.py": "new\n"}

    monkeypatch.setattr(artifacts, "expected_artifact_contents", build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        generated = pool.submit(artifacts.generate_to_disk, project, tmp_path)
        try:
            assert building.wait(5)
            read = pool.submit(artifacts.read_artifact_text, tmp_path, "module.py")
            assert read.result(timeout=1) == "old\n"
        finally:
            release.set()
        assert generated.result(timeout=5).revision == project.revision


def test_preview_size_and_path_boundaries_remain_explicit(tmp_path, monkeypatch):
    _project, _root = _saved_artifacts(tmp_path, monkeypatch)
    assert artifacts.read_artifact_text(tmp_path, "module.py", maximum_bytes=4) == "old\n"
    assert artifacts.read_artifact_text(tmp_path, "module.py", maximum_bytes=3) is None
    for relative in ("../module.py", "/module.py", "x/../module.py", "x\\module.py"):
        with pytest.raises(ValueError, match="relative file path"):
            artifacts.read_artifact_text(tmp_path, relative)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file sharing contract")
def test_uncoordinated_external_reader_remains_an_explicit_failure(tmp_path, monkeypatch):
    project, root = _saved_artifacts(tmp_path, monkeypatch)
    with (
        (root / "module.py").open("rb"),
        pytest.raises(artifacts.ArtifactGenerationError, match="WinError 5"),
    ):
        artifacts.generate_to_disk(project, tmp_path)
    assert (root / "module.py").read_text(encoding="utf-8") == "old\n"
    assert not tuple(tmp_path.glob(".generated-*.tmp"))
