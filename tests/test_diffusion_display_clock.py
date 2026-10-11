"""Preview policy changes presentation traffic, never numerical time or accepted states."""

import numpy as np
from test_diffusion_checkpoints import history, host, latest, request

from code_visualizer.application.computation import execute_computation
from code_visualizer.application.field_examples import diffusion_project
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.extensions.fields.records import SERIES_TYPE


def test_independent_preview_frequencies_preserve_all_accepted_samples(tmp_path):
    observations = []
    for preview_every in (1, 137):
        project = diffusion_project(
            nodes=33, steps=512, sample_every=16, checkpoint_every=256, preview_every=preview_every
        )
        with host(project, tmp_path / str(preview_every)) as kernel:
            evidence = execute_computation(kernel, request(project))
            assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
            retained = history(
                latest(evidence, kernel.resource_store, SERIES_TYPE), kernel.resource_store
            )
            observations.append(tuple(retained.slice(i) for i in range(retained.sample_count)))
            retained.close()
    assert len(observations[0]) == len(observations[1]) == 33
    for first, second in zip(*observations, strict=True):
        assert first.position == second.position
        np.testing.assert_array_equal(first.values, second.values)
