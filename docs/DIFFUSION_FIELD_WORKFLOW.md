# Diffusion, retained field history and numerical restart

P5 adds one deliberately bounded physical experiment: constant-coefficient scalar
diffusion on a fixed one-dimensional Cartesian grid, with zero endpoint values
and an initial sine profile. It uses the ordinary domain workbench and isolated
computation service. It does not introduce a general PDE solver or CAD meshing.

Install the `fields` optional dependencies, or the qualified fields lock when
using a verified release. Open **Diffusion: time, fields and checkpoints** from
the examples menu. Its saved source is `examples/physical/diffusion-field/project.json`.
The domain form exposes diffusivity, initial amplitude, grid/frame references,
final time, integration steps, sample interval, checkpoint interval and preview
interval. Accepted edits use the existing authority, undo and Git fork boundary.

For retained experiments, first use **File → Save As…** to save this example in
your own project folder. Open **View → Git** and use **Initialize Git** if that
folder is not already in a repository. Git must be installed. The
[Git workflow](GIT_WORKFLOW.md) describes reviewing
and committing files; Freeze & Run captures its own declared input without
committing unrelated staged work. Keep the project path reasonably short on Windows.

Select the diffusion experiment and its Crank–Nicolson backend in **Computation
and evidence**. **Freeze & Run** captures the declared source/resource closure
and protects the editing variant before admitting computation. **Cancel
computation** requests cooperative cancellation of the selected attempt. The
retained attempt remains cancelled even when it has a useful field prefix.

The **Field history and trials** tab shows the selected retained accepted sample,
its physical time and step, field unit and quantity kind, support/frame/axis,
coverage and input identity. Scrub the slider to select an exact sample, or play
retained samples at the independent display clock. **Follow published history**
selects the newest durable sample. **Load time overview** explicitly reads a
bounded set of exact samples for a small image; it does not interpolate time.
The provisional pane separately shows a trial and its accepted base. Receiving
a trial never advances the retained cursor or changes an authored parameter.

**Create exact probe** authors a normal independent consumer of the selected
immutable history, sample, node, physical time and interpretation. It retains the
declared resource closure before submitting a revision-checked authority command.
Run that probe through the same backend controls. No producer process or editable
copy of the field is needed. Historical source selection cannot highlight a
different editing branch merely because its local revision number matches.

Open **Git → Retained runs**, select an attempt, and choose **List checkpoints**.
Select a retained checkpoint and press **Resume selected checkpoint**. Resume is
explicit and creates a new attempt with the parent attempt and publication IDs.
The existing freeze transaction checks the original source/input compatibility;
the backend also checks method/library identity, numerical state, grid, units,
frame, sampling/checkpoint cursors and the complete acknowledged prefix. A changed
physical definition requires a new run. P5 does not transfer state between changed
models or discretizations. **Open retained run** reopens its historical definition
for inspection after the producing editor or an inactive worktree has gone away.

Cancellation checkpoints use the last scheduled sampled accepted state. Newer
unpublished numerical work is recomputed on resume. Progress can therefore show
a later step than the retained checkpoint. This preserves the exact authored
sample grid: cancellation does not insert an extra sample or duplicate the
checkpoint boundary. Restarting a host labels orphan attempts interrupted; file
presence cannot imply successful completion or permission to edit frozen input.

Arrays live in immutable, individually bounded resources. A field-series root
names its interpretation, support, chunk pages and any prior prefix. The viewer
opens chunks lazily with a 64 MiB cache and at most one active and one replaceable
pending preparation. A publication enters the live plane and failure-evidence
ledger only after its receipt is durably associated with its retained attempt.
Failures can leave inert unacknowledged bytes, but those bytes do not enable Resume.

The default example uses L=1 m, D=0.1 m²/s and amplitude=10 K **interval**, ending
at 1 s. Its independent analytic midpoint is 3.7270783885343794 K interval. The
finite-grid result has discretization error; convergence tests quantify that
error rather than treating printed precision as physical accuracy. Details and
limits are in [the implementation plan](P5_IMPLEMENTATION_PLAN.md),
[field contracts](FIELD_RESOURCES.md) and [the acceptance map](P5_ACCEPTANCE_MAP.md).

[Time and checkpoints](TIME_AND_CHECKPOINTS.md) specifies the distinction between
solver-accepted, durably published and provisional state and the exact restart boundary.
