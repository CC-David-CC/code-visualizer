# P7: adaptive computation contract

Implementation started 14 September 2026. P0-P6 are accepted; P7 is not qualified.
The source-bound baseline is phase-records/p7-20260914/baseline.json in the Git
repository. The approved P6 archive is preserved unchanged, SHA-256
bb1c9833ae0674f46eafa6c165d41e402e9e7344e2d26264db73b634a9771b4d.

The original P7-01..05 gates and the committed p7-planning-20260914 package govern
this work. No P8 or universal multiphysics claim. P6-R1 denominator validity at
nominal compilation and every real unit-normalized binding is a regression gate.

The author's 15 September performance clarification distinguishes workload memory
from editor overhead and permits a cold start under 10 seconds while requiring
responsive subsequent actions. A measured need may justify a 128 MiB internal
cache; 64 MiB remains the default, not a whole-application RAM ceiling. See the
source-bound `phase-records/p7-20260914/PERFORMANCE_POLICY_ADDENDUM.md` for exact
scope and attribution rules. Prior receipts and action/heartbeat gates are retained.

## First scientific fragment, pinned before results

Conservative finite-volume concentration diffusion on a fixed periodic Cartesian
1D interval. C in kg/m³, D in m²/s, area in m². Cell averages, never node values.
Default L=1 m, area=1 m², D=0.001 m²/s, center L/2, initial concentration
1 + ((1+cos(2*pi*(x-L/2)/L))/2)^8 kg/m³, encoded as eight authored Fourier modes.
Default 32 base cells, final time 20 s; samples each 0.1 s (201 including zero),
checkpoints each 2 s (11 including zero).

Backward Euler, SciPy sparse direct solves; full/two-half temporal estimate and
accepted two-half state. Maximum dt=0.05 s with ten binary subdivisions; integer
ticks align all outputs. Constant finite positive D, length, area and scales.
No arbitrary PDE snippets, sources, moving geometry or implicit model fallback.

Spatial indicator: width*abs(right_slope-left_slope)/8, divided by
atol + rtol*max(abs(C),scale). Default atol=0.001 kg/m³, rtol=0.002,
scale=1 kg/m³; temporal scales one tenth of these. Refine above 1; sibling
coarsening below 0.25 for three opportunities, dwell at least two, parent
indicator at most 0.5. Neighbor levels differ by at most one. Linear limited
prolongation and volume-weighted restriction preserve mass. No clipping.

Initial bounds: 16..512 cells, at most five levels above the base, 8192 accepted
steps, 32 support epochs, 256 samples, 16 checkpoints, bounded rejected work.
Actual encoded resource/publication budgets may impose a smaller limit.
Mass residual: 1e-12 normalized per transfer and 1e-9 per run.
Numerical/mathematical/model/budget failures remain distinct diagnostics.

The independent reference is the analytic Fourier decay integrated over every
actual cell. Uniform space convergence order 1.7..2.3 and time order 0.8..1.2
are measured separately. Adaptive normalized L2 error target <=0.005 at every
declared time; tighter spatial tolerance must lower maximum error; actual
coarsening required. Work target <75% of the smallest qualifying uniform grid's
declared work score (solved unknowns + indicator cell visits + transferred cells),
with matched temporal policy, counting rejected work. Wall time reported separately.
These are acceptance targets, not passing results. Any evidence-driven method
change gets an explicit addendum retaining the original failed attempt.

The first authoring fragment uses ordinary published unit definitions for area
and concentration. Its finite Fourier profile requires distinct harmonics 1..8,
a center within the interval, and mean >= sum(abs(amplitudes)), a sufficient
nonnegative initial-state contract. Output times must align with the declared
binary tick; checkpoints and the horizon coincide with scheduled samples. These
supported-domain checks precede computation; no silent time rounding or clipping.

## Ownership, history and recovery

Only authored field/region/profile/policy objects belong to DomainWorkspace.
Adaptive supports, state arrays, transfers, controllers and decisions are derived
or runtime/evidence resources. Automatic decisions do not create Git branches.
First accepted policy edit follows the existing frozen-variant fork/undo boundary.

P5 uniform/node fields and P6 lumped channels retain exact v1 contracts. New cell
supports and histories use distinct globally registered logical types. A complete
bounded history index records each sample's support/epoch and exact coverage.
No implicit interpolation or index-based identity across a support change.

Use the existing host-owned worker and resource closure/publication/ACK. A
checkpoint includes one coherent accepted solution/support/controller/output
prefix. Receipt and durable attempt association precede acknowledgement.
No stale marker, interrupted publication or reload may restore unrun edit
permission. Retained resources survive editor replacement/worktree removal.

## Particle proof and qualification

P7-02 requires a real bounded state/flux hybrid and independent conservation/
statistical comparison after the planned B0 backend feasibility decision.
The pinned serial SPARTA implementation is selected after the recorded B0
native state/flux, reconstruction, host and frozen-worker proofs. Independent
viscosity calibration and reservoir expectation controls pass; coupled
qualification remains open. See the phase B0 scientific supplement.
P5/P6 checkpoint guarantees cannot be weakened to
accommodate missing native state. A fake worker or a field plot cannot pass P7.

Use 50% job-wide CPU control for all tests/builds, serial qualification, existing
P5 restricted 350 ms profile and P6/new P7 250 ms heartbeat, 100/200 ms interaction
p95/p99 and 64 MiB presentation/cache limits. The large-parent-Git startup
limitation stays explicit. Preserve old tests, examples, receipts and archives.

Scheduling clarification,15September: independent qualification jobs have run
concurrently within the same four-logical-CPU ceiling, superseding the original
serial scheduling assumption. The main gas cohort was further narrowed to
CPUs0..1 (25%) while editor checks used the existing CPUs0..3 budget. The original
and additive Windows job receipts identify the exact processes and limits.
Sources, seeds, time horizons, worker counts, test deadlines and scientific
acceptance criteria did not change. Loaded timing failures remain in the record;
neither those failures nor concurrent scheduling are hidden by a passing rerun.

## Preserved first numerical result and method investigation

The first controller (controller-first-02, 14 September) passed accuracy,
coarsening, conservation and tolerance improvement, but failed the planned work
comparison: adaptive work 71528 versus uniform-32 work 38400. Uniform-32 already
meets the 0.005 error target (maximum error 0.0015345602206488374). The adaptive
maximum error was 0.0008210641778734066. The raw 14-case error/work curves are
retained in the phase records. No P7 cost pass is claimed.

Investigation retains the 0.005 error and 75% work targets. It tests an initial
base of 16 cells and an authored decision_every count, independently of display
and output cadence. Hysteresis/dwell count these scientific decision opportunities.
The existing every-step behavior remains decision_every=1. Skipped spatial checks
are explicit in decision resources, never fabricated zero-error observations.
Uniform comparison now includes 16 cells so no newly qualifying coarse control
is omitted. Default-policy changes require the resulting numerical evidence.

The calibration (continuum-calibration-01) selects base_cells=16,
spatial_atol=0.004 kg/m³, spatial_rtol=0.008, decision_every=4. Other physical,
temporal, hysteresis, dwell and acceptance bounds remain as pinned above. With
the same pulse and 201 reference times, this policy gave maximum L2 error
0.0027255068063450644, 22 initial/16 final cells and three coarsening events.
Work was 24380 (63.49% of uniform-32's 38400). Uniform-16 fails the unchanged
0.005 bound with error 0.005368481489402804; it is now explicitly included in the
comparator sequence. Twice tightening tolerance improves error to 0.00251347
then 0.00124777. This supersedes the original default-policy numbers, not the
scientific acceptance targets. Fresh qualification follows this calibration.

## Real worker cancellation and checkpoint admission

The first real cancellation proof (adaptive-recovery-02) exposed a lifecycle
budget mismatch. The worker stopped computing and the host admitted history
through 0.2 s, but the existing fixed 0.5 s grace expired before the matching
checkpoint/terminal proposal. The result explicitly reported forced termination
and retained checkpoint zero. No unacknowledged checkpoint became available.

Trusted `RegisteredBackend` composition now declares a finite cancellation grace
(0..60 s). Existing registrations retain 0.5 s. The adaptive worker requests 5 s
to seal its bounded sample/controller closure; author data cannot extend it.
The existing host still enforces the deadline and owns forced termination.
This does not change numerical time, the GUI heartbeat budget, checkpoint
compatibility, wire contracts, or P2 admission. Host shutdown retains its existing
short termination behavior. If cleanup fails, earlier acknowledged publications
remain authoritative.

A cancelled run closes its partial numeric chunk. Resume must reproduce all
sample values, positions, support epochs and decision resources exactly; it need
not reproduce the uninterrupted run's physical chunk boundaries or history-root
hash. Resume from a regular checkpoint also reproduces the root hash when its
chunk boundaries match. Neither comparison permits missing or duplicated samples.

## Continuum presentation measurement

The active workload uses the actual adaptive worker at dt_max=0.0025 s with a
preview every step, an ordinary dirty-repository freeze, one policy edit/fork,
and exact retained history scrubbing. Synthetic reader stimuli have 16/17 then
511/512 cells over six samples each; they are explicitly not physics evidence.
Eighty scrubs exercise both, with source replacement and cancellation afterward.

Heartbeat and interaction limits remain 250/100/200 ms (maximum/p95/p99).
The 64 MiB presentation growth measurement follows P6: maximum RSS while viewing
the large history minus maximum RSS while viewing the small history. Total host
growth from initial warmup is also recorded, including new Git authoring contexts.
The first P7 stress draft incorrectly applied the presentation bound to that
whole-host growth; those failed receipts remain. It is not a 64 MiB total-editor
budget. Cache, pending-task and active source identity checks remain independent.

Initial painting incurred hundreds of separate graphics items and, in an
intermediate table model, Python callbacks for individual paint roles. The panel
now batches partition lines and uses native Qt model storage. No numerical,
garbage-collection, process-priority or acceptance threshold was changed.

## Registered gas input, computation and restart boundaries

The first gas slice is a bounded monatomic mean-flow extension. The generic
kernel does not acquire gas, wall or particle concepts. The authored model owns
physical gas/geometry/frame/initial/wall/interface/field/policy identities. Its
calibration property references seventeen immutable resources: the independently
qualified study and sixteen actual observation arrays. The pinned fit derives
transport for computation; no editable viscosity copy is persisted.

The native engine is serial SPARTA build16, source revision
e071055fca6ccd250d4b894dadb7ff64d6e6fcac plus the recorded adapter/build changes.
Its Windows x64 DLL, species/collision inputs, GPL license and complete matching
source/build archive are sealed package data. Other platforms can read retained
data; native execution requires a separately qualified implementation. The
normal ComputationService owns preparation, subprocess lifetime, cancellation,
resource transfer and publication. No gas-specific process manager is introduced.

Conserved nonperiodic samples have their own gas interpretation and reuse the
bounded NumericHistory/array I/O. They do not reinterpret periodic dyadic cell
support. Actual signed particle transfers replace provisional continuum face
integrals; whole-run mass, all momenta and energy close independently of sampling
uncertainty. The continuum can take up to sixteen bounded power-of-two SSPRK
substeps within one communication window, without changing the native quantum.
Actual substep work is counted. A failed advanced native candidate is destroyed.

Checkpoints bind source and installed implementation identities, all five state
fields, actual native input tape, complete active native observation, controller,
statistics/flux accumulators, transfers and acknowledged sample cursor. The tape
uses at most128 chunks of4096 rows, covering the full400,000-tick one-step budget
with each numeric chunk below4MiB. A fresh worker reconstructs the entire prefix
and verifies exact native state, every input row and all accumulated meaning
before continuing. Replayed work is reported. A regular checkpoint preserves
the retained sample/chunk partition and root; no duplicate boundary sample is
inserted. Publication of a checkpoint occurs only after its exact sampled state
and complete resource closure have been acknowledged by the existing host.

Model activation and return are explicit conservative transfers. Their records
contain the state immediately before the model change, actual retained particle
moments, accounting and (for return) raw statistical blocks and uncertainty.
No synthetic mean state stands in for an actual successful particle return.
Hysteresis, dwell, support/law/units/frame checks, precision and finite budgets
remain separate gates. Insufficient return fidelity is an explicit failed
computation with its previously acknowledged prefix retained.

The detailed predeclared gas protocol is in the phase record's
GAS_QUALIFICATION_PROTOCOL.md. It distinguishes primary bulk/profile means from
supplementary wall impulses, uses multiplicity-adjusted practical-equivalence
intervals and limits any sampling extension to a precision-based rule. These
scientific comparisons, complete gas UI/Git qualification, full regression and
distribution are still pending. B0 engineering and short worker proofs do not
constitute P7-02 acceptance.

## Shared retained-cell presentation and downstream gas queries

The common cell presentation is an immutable display DTO, with resource-specific
readers responsible for physical interpretation and stable cell identities. It
is never persisted as another support model. Periodic adaptive support and
wall-bounded gas support retain their distinct resource contracts. One Qt panel
uses the same bounded queue, cache, sample cursor, native table and batched paths
for both. Provisional base/candidate frames retain independently resolved cell
identities and cannot advance the accepted cursor. Another attempt, definition,
frame, support or conflicting retained base is rejected.

The gas observation bundle authors an exact retained history/sample/cell/field/
frame/time query through ordinary domain commands. The application prepares and
copies the declared resource closure off-thread, then submits the prepared
commands to the existing authority. A fresh ordinary worker consumes those
resources without an active native producer or an authored copy of its field.
The selected value keeps its exact unit. Undo/redo and persistence apply to the
query intention; playback does not edit that intention or its producer.

Focused gas-presentation-02 passes49 actual native, portable/restart, consumer,
shared-view, preview/source, undo/reload and architecture cases. An existing
host throttle defect is also corrected: only progress updates advance the
progress-throttle clock, so preceding preview events cannot starve progress.
These proofs establish the retained cell path, not ensemble physics or the
remaining gas Git, whole-product performance and distribution gates.

## Resource-bearing saved example

The physical catalog includes the saved gas source and its seventeen-resource
calibration closure. Opening it asks for a project directory, verifies/copies
the declared inputs in the background, then opens the ordinary native session.
No computation is started by opening the example. Packaged resources are read
only; a changed editor context prevents a late prepared session from replacing
the active editor. A failed input copy does not publish an incomplete project.
The normal physical-example exporter includes the same complete source closure.

The declaration/preview path does not need to import numerical execution
controllers. Those implementation-only imports are deferred until computation.
Preview dispatch coalesces the current authority snapshot before starting a
worker; explicit execution remains pinned to its requested immutable snapshot.

## Actual bounded return evidence

The original 64-cell decaying-shear case ended with insufficient return fidelity:
its post-warmup gradient sensor never crossed the unchanged .001 return threshold.
That failed case and all its raw data remain retained. A separately predeclared
16-cell target, with all other physical inputs, seed, budgets and thresholds
unchanged, activated at 0 and returned at 176000 after 76 statistical blocks. It
completed 340000 ticks and 171 retained samples, with both particle and continuum
states. The return used actual native moments and had zero normalized transfer
residual; activation residual was 3.23e-16. This result applies to that target.

The successful case is tied to `07bb1e16f3f755ad1421f76416ca83c21b678e2a` and source
hash `5586a00f32af88892522a9406ce7bcf15aeccafe3e8b08a8888be337d99382bf`.
It does not upgrade the original 64-cell case or complete the independent
hybrid/full-particle ensemble. Fresh reconstruction after the actual return,
gas Git/performance, complete regression and distribution remain pending.

## Integrated lifecycle qualification

The application now disposes all retired document widgets when replacing a
session, including hidden and detached views. It closes their preparation owners
without changing the lifetime of host-owned computations or retained resources.

A cell view searches the selected attempt's explicit newest-first publication
snapshot on its existing background reader. It selects the latest resource with
one registered cell-history dependency, so a later statistics output cannot hide
the final history. Direct artifact inspection remains strict. Corrupt or ambiguous
metadata is rejected rather than concealed by choosing an older publication.
The renderer performs no resource reads to select this history.

New qualification cases exercise actual gas publication failures, cancellation,
killed-host reopening, final-output selection and unpaused native/Git/UI load.
Their focused results are pending; static checks alone do not establish P7.
