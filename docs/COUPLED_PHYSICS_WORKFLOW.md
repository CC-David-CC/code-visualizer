# Coupled physics and the axial structural client (P6)

Install `requirements-fields.txt` and `requirements-cad.txt` into the same
environment used by `launch.py`. The coupled example uses the scientific pins;
the axial client additionally uses the pinned build123d/OpenCascade implementation.
The source archive needs internet for first installation. These examples are
synthetic verification models, with the supported fragment in
[P6_CONTRACT.md](P6_CONTRACT.md) and [P6_AXIAL_FRAGMENT.md](P6_AXIAL_FRAGMENT.md).

## Electrothermal feedback

Open **File → Physical examples → Resistor and heat sink: coupled windows**, or
open `examples/physical/electrothermal`. Its canonical domain objects describe
the circuit, two thermal bodies, resistance law, transfers and window policy.
The **Domain workbench** edits those same objects through typed authority commands.
The default is a 5 V source, 10 ohm reference resistor and 100-second run.

Select the electrothermal model and its registered backend, then **Freeze & Run**.
The existing Git transaction captures the declared source and input resources,
retains an input commit and protects the editing variant before admission. The
worker iterates the electrical/thermal equations inside one computation attempt.
One converged window owns both temperatures, coherent circuit values and the
accepted energy ledger. The numerical method is fixed-step backward Euler;
coupling convergence does not make its time-discretization error vanish.

The workbench **Channels** tab shows retained accepted values and a separate
provisional-iteration table. A trial names its numerical base and candidate
window. That base can be absent from the retained sampling schedule; the UI says
so explicitly. It never creates an invented retained sample. Temperature points,
intervals, current, power and energy retain their individual units and supports.

Turn off **Follow published samples** to scrub or play exact retained samples.
Select a channel for its bounded min/max curve and use **Select channel source**
to navigate to its authored object. Panning, channel selection and playback are
presentation changes. **Create exact probe** authors a separate consumer of the
selected immutable history, channel and sample. It uses the same computation
host; it does not restart the producer or scrape printed output.

An accepted semantic edit after a freeze creates one unrun child variant.
The old attempt keeps its input and retained resources. Later edits stay on that
child until it is frozen. A view of an earlier attempt identifies historical
source, including when two branches have equal local revision numbers.

**Cancel** retains the last scheduled coherent prefix and reports cancellation.
Use the existing retained-run checkpoint controls to select a checkpoint and
explicitly **Resume** into a new attempt. Compatibility includes scientific
inputs, mapping, numerical method and sampling policy. Parameter changes require
a new run. A retained checkpoint never silently transfers old state to changed
physics; interruption never implies automatic replay.

## CAD-backed axial bar

Open **Solid CAD bar and axial equilibrium**, or `examples/physical/axial-bar`. The
saved source is an ordinary canonical Python recipe. In the CAD artifact panel,
choose **Freeze Python CAD producer…** and declare its required BREP output
`bar`. The existing Python backend emits and runs the real package, publishes
the typed solid, and exits. The example is a solid 100 × 10 × 10 mm prism.

Select the successful `bar` artifact and choose **Create axial analysis…**.
Specify Young modulus, signed axial force, 3–65 nodes and the Cartesian axis.
Defaults are 200 GPa, 1000 N, 17 nodes and x. Resource inspection and closure
copy happen on the background worker. One authority transaction creates the
authored material, geometry idealization, support, load and resource-scoped
end-region predicates. The same action can create a consumer in another project.

Freeze and run the new axial model with its registered backend. It checks the
actual solid and end faces, derives a typed geometry-to-axis mapping, assembles
element stiffness and solves equilibrium using the existing P3 linear boundary.
For the default bar, the independent targets are 5 µm extension, 10 MPa stress,
−1000 N reaction and 0.0025 J strain energy. Inspect its result to see displacement
versus position, source frame and metrics. Display axes have independent scales.
This display is derived evidence; the reference BREP remains immutable.

The supported geometry is one aligned solid rectangular prism. Holes, taper,
disconnected bodies, transverse loads, wrong frames and stale region bindings
are explicit diagnostics. This is a bounded axial solver, not a general FEM
package. Missing native CAD capability remains a local capability diagnostic.

## Reproducible saved-source proof

Run `python tools/prove_coupled_physics.py --output NEW_DIRECTORY`. It loads
both saved sources while forbidding example-factory imports, runs the actual
host, decodes resources, compares independent numerical targets, ends producers,
and replays consumers from copied closures in empty stores. It also resumes an
explicit retained coupled checkpoint. `proof.json` records this tool's result;
the full gate, performance and release evidence is separate in
[P6_ACCEPTANCE_MAP.md](P6_ACCEPTANCE_MAP.md).

P7 adaptivity and P8 are outside P6. General multiphysics meshes, multirate
coupling, RF and real-device certification are not implied by these examples.
