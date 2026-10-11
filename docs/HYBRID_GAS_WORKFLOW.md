# Particle and continuum gas shear

P7 is under qualification. P0-P6 remain accepted; the development source does
not by itself establish P7 acceptance. Numerical limits and measured evidence
are in [P7_CONTRACT.md](P7_CONTRACT.md) and [STATUS.md](../STATUS.md).

Install `requirements-fields.txt` in the application's Python environment.
The selected gas participant uses the bundled Windows serial SPARTA library,
species data and VSS interaction data. The corresponding source and license
are shipped beside the library. Other native platforms have not been qualified.
Opening and editing a definition is separate from having its computation
dependencies available.

Choose **File > Physical examples > Particle and continuum gas shear**, then
choose a writable project directory. Opening copies the saved definition and
its complete seventeen-resource calibration input. It does not run a solver.
The calibration is an immutable input with provenance; it is not a second
editable viscosity parameter. Alternatively, open the complete
`examples/physical/hybrid-gas` folder from an extracted source distribution.

The hierarchy and property editor expose the region, space/frame/axis, fields,
walls, particle slab and policy. Properties carry ordinary unit and reference
contracts. Invalid density, energy, frame, species, interface or execution
policy yields a diagnostic. Switching representation does not repair an invalid
physical definition.

## Run, inspect and reuse a retained result

Use the existing Git dock to initialize Git if needed. Select the experiment
and its **Bounded argon state/flux computation** backend, then **Freeze & Run**.
The existing transaction captures the declared source/input closure and retained
run reference before admitting execution. It preserves unrelated Git work.
The backend runs through the ordinary host-owned process lifecycle.

Open **Computation and evidence**, then **Cells and support history** in the
field outputs. The same panel reads the adaptive continuum and gas resource
contracts. Choose a component, inspect a cell, scrub the sample cursor, or use
**Play retained samples**. Playback and component selection are presentation
operations. They do not mutate the definition or launch another computation.
Accepted samples retain exact physical time, units, support and source identity.
Provisional previews are separately identified; they do not advance the retained
sample cursor. A final statistics publication does not hide the same attempt's
latest cell history.

**Select field source** navigates to originating semantic objects when the
displayed attempt belongs to the active definition. A historical attempt stays
historical after a branch or editor change. It cannot silently select a different
same-numbered revision's objects.

Choose a retained cell and **Create exact cell probe**. The application prepares
and copies its complete resource closure in the background, then submits an
ordinary authority edit. The resulting query records exact history, sample,
cell, component, frame and time. Select that model and **Freeze & Run** it to
obtain the same unit-bearing value in a new attempt. It works after the original
producer exits or its clean inactive worktree is removed. It does not copy the
field into another editable model. The probe supports normal save/load and
undo/redo.

## Editing and continuing

The first accepted semantic change to a frozen definition creates one unrun Git
variant. Further changes and undo/redo remain on that variant. Solver decisions,
unaccepted text, playback and presentation changes do not create branches. An
already running attempt keeps its original frozen policy and resources.

**Cancel** requests cooperative completion at the next scheduled sample. The
host retains a finite escalation deadline; a forced stop is reported separately
and keeps the previous acknowledged checkpoint. Slow or failed publication
must never turn an unacknowledged candidate into a resumable checkpoint.

To continue, open **Git > Retained runs > List checkpoints > Resume selected
checkpoint**. Resume is explicit and checks exact source, inputs, physical law,
implementation and native state. A changed seed or policy cannot consume the
old checkpoint as though it belonged to the new variant. The selected engine
reconstructs the complete accepted prefix and validates active native/RNG/
collision/reservoir state before continuing. Regular compatible restart preserves
every sample and the retained history root. This exact claim is tied to the
recorded implementation, runtime, platform and binary; it is not cross-platform
floating-point equivalence.

## Reproduce the saved-source proof

From the application source folder:

```powershell
python tools/prove_hybrid_gas.py --output NEW_OUTPUT_DIRECTORY
```

This runs the saved full horizon with example factories and Qt imports forbidden,
checks interpreted output and origins, reuses an exact cell after the producer
location becomes unavailable, and resumes a checkpoint in a fresh host. It can
take substantially longer than a normal installation check.

For installation qualification, add `--smoke`. That submits one recorded
authority transaction changing only the output/time schedule to a short run.
The report and saved journal distinguish the received source from the authored
short variant. Physical inputs, calibration, seed, particle model and interface
remain unchanged. A short installation proof is not statistical qualification.

The supported scientific slice is one-species dilute argon shear with declared
planar ownership, VSS collisions and bounded fixed-wall/state/flux coupling.
Independent calibration, full-particle comparisons, uncertainty and conservation
have separate evidence. This is not a general fluid, molecular, chemistry or
multiphysics solver, and no P8 work is implied.
