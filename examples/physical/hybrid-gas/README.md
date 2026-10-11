# Particle and continuum gas shear

This is an authored argon channel with explicit walls, particle ownership,
interfaces, frame, conserved fields and numerical policy. Its calibration is a
retained resource: sixteen independent native observations and their measured
transport fit. The project does not contain a second editable fitted viscosity.

In **File → Physical examples → Particle and continuum gas shear**, choose a new
project folder. Code Visualizer copies and verifies the declared input resources
in the background before opening the native project. The packaged inputs remain
unchanged. You can also open this directory's `project.json` directly; keep its
adjacent `resources/` directory with it.

In the domain workbench, select `gas:experiment` and the **Bounded argon state/flux computation**
computation backend. Review the gas, channel, walls, slab and policy in the form.
Use the existing **Freeze & Run** path to retain the input Git commit and attempt.
The default long study has 340,000 microscopic steps. Its computation may take
tens of minutes on a restricted laptop; opening the example does not run it.

Inspect a published history or checkpoint in **Computation and evidence →
Adaptive cells and epochs**. Scrub exact retained samples, select a conserved
component, then select a cell and create a probe. The same panel supports
periodic adaptive fields and this wall-bounded gas; the resource's declared
geometry, frame, units and exact cell identities determine its interpretation.
A probe is an ordinary authored resource query and can run after the native
producer exits. Playback and provisional candidates do not edit the source.

The bundled engine is the qualified Windows x64 serial SPARTA build16 with its
matching source and GPL license under `src/code_visualizer/resources/sparta`.
Other platforms can edit the intentions and read retained data; native execution
requires a separately qualified engine. See `docs/P7_CONTRACT.md` for the physical
and statistical limits. This example is a bounded monatomic mean-flow model.
Completion of a single run does not establish statistical equivalence. P7's
ensemble, actual return, full regression and distribution acceptance are still
being qualified; this source is not a P7 acceptance claim.
