# Diffusion: time, fields and checkpoints

Open project.json, select **Diffusion experiment**, then **Computation and
evidence**. The Crank-Nicolson backend solves a one-dimensional rod with zero
endpoint temperature excess and a sine initial profile. The field is a temperature
interval, measured in kelvin, in an explicit laboratory frame.

Install the `fields` extra for the pinned NumPy/SciPy/Pint dependencies. Freeze &
Run retains the authored definition through the existing Git experiment workflow.
Accepted samples and checkpoints are immutable resources. Trial previews are
provisional and never become authored values or evidence by being displayed.

The example uses length 1 m, diffusivity 0.1 m²/s, initial amplitude 10 K interval,
65 nodes, 2048 accepted steps and a final time of 1 s. Its analytic midpoint is
3.7270783885343794 K interval. Spatial discretization leaves an expected small error;
the automated proof uses an absolute tolerance of 0.0008 K for this grid.

Cancellation seals scheduled accepted samples. Numerical steps newer than the
last sampled state are disposable and are recomputed after explicit checkpoint
resume. Resume retains the original sample times, with no duplicate boundary row.

Run `python tools/prove_field_history.py --output <fresh-directory>` to execute
this saved source and consume the result in a fresh host. The proof blocks example
factories and Qt imports. Its independent probe stores a reference to the retained
history and an exact sample/node selection; it does not copy the field into a second
editable model.
