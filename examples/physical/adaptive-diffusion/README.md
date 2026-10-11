# Adaptive periodic diffusion pulse

Open `project.json`, select **Adaptive periodic diffusion pulse**, and choose
**Freeze & Run**. The saved domain objects define the physical interval, field,
initial pulse, units, numerical policy and output schedule. No Python source or
example factory supplies the running experiment's meaning.

The pulse diffuses around a periodic one-metre interval for twenty seconds.
The initial partition resolves the authored pulse; the controller then removes
unnecessary refinement as the pulse smooths. Each accepted sample retains its
own mesh epoch and cell identities. The calculation conserves total mass.

In **Computation and evidence → Adaptive cells and epochs**, inspect a history
or checkpoint, scrub exact retained times, and select a cell. A cell that has
been merged remains visibly absent; the view never substitutes another cell
at the same array position. **Create exact cell probe** authors a consumer of
that sample, epoch, cell and component. Its copied resources remain usable
after the original worker or inactive worktree is gone.

Provisional candidates are labelled as awaiting host publication. They do not
advance retained time. An accepted policy edit after Freeze & Run creates an
unrun Git variant; automatic refinement is evidence inside the original run.

The independent continuum criterion is a weighted cell-average error at most
0.005 at all 201 sample times. The current default uses 63.49% of the counted
work of the smallest qualifying uniform comparator. See `docs/P7_CONTRACT.md`
for the method, work accounting, failed initial calibration and limitations.
This example proves the continuum slice; it does not certify particle coupling
or complete P7 acceptance.

Requires the application's `fields` dependencies. To reproduce saved-source
execution, exact resource reuse and checkpoint continuation in a fresh process,
run `tools/prove_adaptive_physics.py --output <fresh-directory>` with the
application Python environment. Use the documented CPU budget on this laptop.
