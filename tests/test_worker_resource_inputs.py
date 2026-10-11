"""Trusted worker roots must preserve the explicit resource lookup contract."""

import os
from pathlib import Path

import pytest

from code_visualizer.application.computation_process import worker_resource_environment
from code_visualizer.application.computation_worker import (
    INPUT_RESOURCE_ROOT_ENV,
    RESOURCE_ROOT_ENV,
)
from code_visualizer.persistence.resource_store import ResourceStore


def test_worker_environment_rejects_nested_readthrough_instead_of_losing_ancestors(tmp_path):
    durable = ResourceStore(tmp_path / "durable")
    descriptor = durable.put(b"ancestor input", "text/plain")
    intermediate = ResourceStore(tmp_path / "intermediate", inputs=durable)
    scratch = ResourceStore(tmp_path / "scratch", inputs=intermediate)
    assert scratch.read(descriptor.reference) == b"ancestor input"
    with pytest.raises(ValueError, match=r"one direct durable input store.*nested"):
        worker_resource_environment(scratch)
    assert scratch.descriptors() == ()
    assert intermediate.descriptors() == ()
    assert durable.descriptors() == (descriptor,)


def test_direct_worker_input_environment_roundtrip_is_exact_and_clears_stale_roots(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(RESOURCE_ROOT_ENV, "stale-write-root")
    monkeypatch.setenv(INPUT_RESOURCE_ROOT_ENV, "stale-input-root")
    durable = ResourceStore(tmp_path / "durable")
    descriptor = durable.put(b"authored input", "text/plain")
    scratch = ResourceStore(tmp_path / "scratch", inputs=durable)
    environment = worker_resource_environment(scratch)
    assert environment[RESOURCE_ROOT_ENV] == str(scratch.root.parent)
    assert environment[INPUT_RESOURCE_ROOT_ENV] == str(durable.root.parent)

    # Reconstruct exactly the two roots admitted by the fixed worker entrypoint.
    received = ResourceStore(
        Path(environment[RESOURCE_ROOT_ENV]),
        inputs=ResourceStore(Path(environment[INPUT_RESOURCE_ROOT_ENV])),
    )
    assert received.describe(descriptor.reference) == descriptor
    assert received.verified_path(descriptor.reference) == durable.verified_path(
        descriptor.reference
    )
    assert received.read(descriptor.reference) == b"authored input"
    assert received.descriptors() == ()
    assert not scratch.root.exists()

    isolated = ResourceStore(tmp_path / "isolated")
    standalone = worker_resource_environment(isolated)
    assert standalone[RESOURCE_ROOT_ENV] == str(isolated.root.parent)
    assert INPUT_RESOURCE_ROOT_ENV not in standalone
    assert os.environ[RESOURCE_ROOT_ENV] == "stale-write-root"
    assert os.environ[INPUT_RESOURCE_ROOT_ENV] == "stale-input-root"
