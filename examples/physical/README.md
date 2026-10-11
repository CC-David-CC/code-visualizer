# Physical equation examples (P3)

These two native projects use the same **Unit-aware linear equations** backend.
They contain authored definitions and unit vocabularies, with no generated program,
solver results or cached evidence stored as authoring state.

Install `requirements-science.txt` into the application interpreter, or install
`.[science]`. Choose **File → Physical examples** for a new editable copy, or open
one of these project folders. Use **Domain Workbench** to inspect graph, table and
hierarchy/form views. Select **Unit-aware linear equations**, then **Run computation**.
For retained experiments, save in a Git repository and use **Freeze & Run**.

* `dc-divider`: a 5 V source and two 1,000 ohm resistors. The midpoint is 2.5 V;
  branch currents are 2.5 mA. The source's reported current is -2.5 mA because
  every component's positive-to-negative orientation is explicit.
* `spring-equation`: the authored relation `F = k*x`, bindings 10 N and 200 N/m,
  and unknown `x`. The result is 0.05 m. The equation remains the same when a
  different symbol is selected as unknown and the complementary binding is supplied.

To load the divider, select the Circuit in the hierarchy and **Add child**, choose
**Components**, then **Resistor**. Name it Load and retain 1,000 ohms. Select the
new resistor and add a Terminal to its **+** role, with Net set to Midpoint; add
another Terminal to **-**, with Net set to Reference. Incomplete authoring remains
editable and diagnosed until the endpoints are complete. Adding the first accepted
child to a frozen definition forks once. Further edits and undo/redo stay on that
unrun variant. The three resistor currents now follow from topology, and the
midpoint is 5/3 V.

After the second Freeze & Run, open **Git → Retained runs**, select both attempts
and **Compare selected runs**. The comparison reads each retained input and evidence,
shows units and differences, and lets you navigate back to their semantic origins.
It does not copy results into parameters. Old results remain inspectable after
closing the editor and removing a clean inactive experiment worktree.

The JSON solution resource records the compiled equations' coefficient matrix,
physical scales, normalized matrix, rank, condition, values and residuals. P3 solves
bounded scalar steady linear problems. Nonlinear, transient/DAE, frequency-specific
and logarithmic operators require an explicit later contract and are diagnosed.

From the source folder, reproduce both worker/portable/resource/origin proofs:

```powershell
python tools/prove_physical_equations.py --output NEW_OUTPUT_FOLDER
```

This command loads the saved project files with example factory and Qt imports
forbidden. The normal source-archive verifier also runs it. The existing 17 Python
examples and earlier independent proofs retain their separate unchanged checks.
# Time-dependent field example

`diffusion-field/` contains one ordinary canonical diffusion experiment, its
field/grid and explicit foundation.space@2 frame. Install requirements-fields.txt.
Open **Diffusion: time, fields and checkpoints**, then use **Freeze & Run**,
**Field history and trials**, and **Git → Retained runs → List checkpoints →
Resume selected checkpoint**. An exact probe consumes retained samples after the
producer exits. See [the workflow](../../docs/DIFFUSION_FIELD_WORKFLOW.md).

## Adaptive cells and particle/continuum shear

`adaptive-diffusion/` contains the periodic diffusion pulse and its authored
refinement policy. `hybrid-gas/` contains the bounded argon shear definition and
its complete seventeen-resource calibration input. Opening the gas example from
the physical catalog copies this declared closure to a chosen project directory
before publishing the editor. It does not start a computation.

Both use the existing **Freeze & Run**, retained checkpoint and exact cell-probe
routes, with **Cells and support history** for accepted samples and distinct
provisional previews. Install `requirements-fields.txt`; the selected native gas
engine currently requires the recorded Windows environment. See
[adaptive cell histories](../../docs/ADAPTIVE_FIELDS.md) and
[the gas workflow](../../docs/HYBRID_GAS_WORKFLOW.md). P7 qualification remains
open; neither a short example run nor an installation smoke proves its statistical
physical acceptance gates.
