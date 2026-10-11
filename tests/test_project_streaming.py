"""Streaming snapshots retain the exact native byte contract and record lifetimes."""

import hashlib
import json
from pathlib import Path

import pytest

from code_visualizer.application.scale_fixture import build_scale_project
from code_visualizer.persistence import serialization
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.decoding import project_from_data

EXAMPLES = tuple(sorted((Path(__file__).parents[1] / "examples/projects").glob("*/project.json")))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.parent.name)
def test_every_saved_example_keeps_its_existing_canonical_bytes(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    project = project_from_data(raw)
    expected = canonical_data_bytes(raw)
    assert canonical_data_bytes(serialization.project_to_data(project)) == expected
    chunks = tuple(serialization.project_data_chunks(project))
    assert chunks and all(0 < len(chunk) <= 64 * 1024 for chunk in chunks)
    assert b"".join(chunks) == expected
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    assert digest.digest() == hashlib.sha256(expected).digest()


def test_one_large_function_streams_nested_statements_without_a_whole_function_tree(monkeypatch):
    project = build_scale_project(1, atoms_per_diagram=10000)
    expected = canonical_data_bytes(serialization.project_to_data(project))
    original = serialization._program_action_stream
    visited = []

    def action(value):
        visited.append(value.id)
        return original(value)

    monkeypatch.setattr(serialization, "_program_action_stream", action)
    stream = serialization.project_data_chunks(project)
    first = next(stream)
    assert 0 < len(visited) < 10000
    assert len(first) == 64 * 1024
    assert first + b"".join(stream) == expected
    assert len(visited) == 10000
