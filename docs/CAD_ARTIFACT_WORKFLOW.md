# Spring-driven CAD and reusable artifacts

P4 uses the existing Python package runner, computation host, resource store and
Git experiment history. It does not introduce a separate CAD executor. Install
`requirements-cad.txt` in the same environment as the application; it includes
the scientific dependencies and pins build123d and Open Cascade. The original
source-only installation still works without CAD and reports missing native
dependencies when a CAD computation needs them.

## Use the example

1. Open **File > Physical examples > Spring-driven CAD and reusable geometry**.
   Save the project into a writable Git repository (or initialize Git in its Git
   workspace). Select the shared equation model and the unit-aware linear
   equation backend, then **Freeze & Run**.
2. Open the resulting solution artifact in **Computation and evidence**. The
   **Artifact inputs and geometry** tab verifies the selected resource. Choose
   **Freeze Python with this input**, keeping `solution` as the input name and
   `solid` as the required BREP output name. This binds the exact selected result;
   there is no implicit “latest result”.
3. Select the resulting solid artifact. **Measure** or **Create display mesh**
   creates an authored consumer through the existing authority. If the definition
   is frozen, normal fork-before-edit runs first. Select the new consumer model
   and its corresponding backend, then **Freeze & Run**.
4. Open the mesh artifact to inspect its isometric/front/top presentation and
   resource-scoped face picks. The panel shows resource hash, input digest, source
   revision, frame, coordinate unit and tessellation tolerances. Current evidence
   shares semantic selection; historical evidence does not decorate another
   editor or branch just because its local revision number matches.
5. **Assign boundary** creates a planar end-face rule, initially a support at
   minimum x or load at maximum x. Edit its frame, axis, side, tolerance and
   cardinality in the ordinary domain form. Resolving it produces a typed resource;
   no structural mechanics solve is implied. A rule with zero or an unexpected
   number of matching faces fails explicitly. Direct face indices never transfer
   to another geometry hash.
6. **Promote to editable input** creates an independent geometry-input identity
   with the exact original resource and evidence/artifact provenance. Edit its
   unit-bearing translation properties and run the GeometryInput backend. This
   produces a new solid without running the original Python recipe. Undo/redo
   changes the authored binding, while old runs and resource bytes remain intact.

The example's force is 10 N and stiffness 200 N/m, so the selected solution is
0.05 m. The Python recipe explicitly converts that to 50 mm at the CAD boundary,
creates a 50 × 20 × 10 mm beam and cuts a radius-2-mm through-hole. Independent
measurement must produce volume `9.874336293856409e-6 m³`. Changing force to 12 N
gives a 60 mm beam; it does not mutate the earlier solid.

## Ownership and interpretation

The recipe owns its dimensions, operations and Cartesian frame policy as Python
meaning. BREP resources retain a frozen frame/space interpretation, parameters,
serializer versions and producing semantic IDs. A mesh is a separate derived
resource with an exact parent BREP reference, chordal/angular tolerances and
revision-local face groups. Neither representation becomes editable author state.

Resource verification and preparation run outside GUI handlers. Native topology
interpretation runs in the computation backend's owned child process. The editor
reads bounded inert metadata and mesh arrays; it does not load native topology
to accept a resource binding. A declared file that a native consumer cannot
interpret produces a diagnostic rather than triggering a fallback or rerun.

The initial viewer supports at most 10,000 triangles and 64 MiB of mesh data.
Its depth-tested image and picking buffer are at most 768 pixels per side, with
16 million candidate fragments per preparation; superseded work is cancelled.
Choose coarser tessellation for larger displays. Resource envelopes have separate
64 KiB metadata and 512 MiB payload limits. These are explicit implementation
bounds, not a claim of an unrestricted CAD workbench or P5–P8 completion.
