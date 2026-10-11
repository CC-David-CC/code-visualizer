# Intentional workbench transition

## P6-R1: corrected and requalified; P5 remains accepted

The shared compiler preserves authored nonzero-denominator conditions separately
from simplified matrix entries, with normalized nominal/bound values and original
semantic identities. No authority, runtime, resource, checkpoint or Git boundary
changed. The unchanged review first reproduced six failures with real Pint; all
51 independent, 91 core and 100 preservation cases now pass. Cohorts overlap.

The full run at `9ec3ab40f8a3d7e135ec2bdb52522558620cb37a` passes **2,354 cases**
in 6,735.44 seconds with zero failures, errors or skips, preserving all 2,289
reviewed P6 cases and 231 test/fixture files. That includes the complete accepted
P5 baseline. The isolated wheel and both freshly built Windows executables pass
saved P4/P5/P6 proofs and direct R1 checks. Both executables also pass the unchanged
native P2 restart/fork proof. P6's actual worker/large-history UI workload passes
its unchanged limits.

The [current map](P6_ACCEPTANCE_MAP.md), [correction record](P6_R1_CORRECTION.md)
and [new receipt](receipts/transition-p6-r1.json) identify the fresh evidence.
Extracted-source verification and the delivered ZIP hash are recorded after
packaging in the matching adjacent sidecars. The old reviewed P6 archive and
all historical receipts remain unchanged. P6 acceptance is pending user review;
this task does not advance P7/P8. Earlier entries retain their historical meaning.

## P6: source, wheel and Windows executables qualified; acceptance review open

P5 was accepted by the user on 13 September 2026 within its recorded Windows
scope. That decision is additive in `receipts/p5-acceptance-2026-09-13.json`;
the historical receipts below retain their original status and measurements.
P6 implements the supplied electrothermal/axial fragment using the same authority,
Git freeze/fork, computation host and resource/evidence boundaries. Independent
transient/reference, restart/durability, structural and saved-source/Qt
cohorts pass. The complete run at `21065a5` passes 2,289 cases, including every
one of the 2,122 accepted baseline identities, in 5,581.41 seconds with no failures
or skips. P6 interaction p95/p99 are 3.26/14.56 ms; maximum heartbeat is 158.59 ms
under the predeclared 250-ms bound and 50% process-tree CPU restriction. The
first complete run's cancellation-fixture race and the stronger checkpoint-ACK
ordering correction remain documented. All original test bytes are preserved.
The isolated wheel and both Windows executables pass the saved P4/P5/P6 proofs,
including post-exit resource consumption and portable replay. Both executables
pass the unchanged P2 restart/fork proof. All 14,812 native manifest files and
746 application/resource file copies are verified. Two failed native harness
attempts remain recorded; the fresh build supplies the source-package visibility
required by the builder and verifier. Application/test source is unchanged.
The [structured receipt](receipts/transition-p6.json) and
[raw evidence manifest](receipts/p6-verification-2026-09-13/evidence-manifest.json)
identify the actual results. Extracted-source qualification and final ZIP identity
are established after packaging in the adjacent delivery sidecars.
See [the P6 map](P6_ACCEPTANCE_MAP.md), [contract](P6_CONTRACT.md) and
[workflow](COUPLED_PHYSICS_WORKFLOW.md). No P6 acceptance or P7/P8 completion is
claimed by these qualification results.

## P5: source and packaged gates verified; acceptance review open

The complete run on `6d44a6f` passes **2,122/2,122** in 5,581.52 seconds, with
zero failures, errors or skips. It includes all **2,027 unchanged P4 cases** and
95 P5/corrective cases. The P2 recovery reproductions, original Git-checkout
cleanup and both new session-publication lifetime tests pass. The source inventory
and accepted P4 archive stayed unchanged throughout the run. See the
[complete analysis](receipts/p5-verification-2026-09-12/full-regression-10-analysis.json).

The user-authorized restricted profile permits a **350 ms P5 field heartbeat**;
the measured maximum is **122.0 ms**, with interaction p95/p99 **33.4/41.2 ms** and
memory/cache within bounds. The normal profile remains 250 ms. All other test
expectations remain unchanged; earlier failed results are preserved. The entire
run used a verified job-wide limit of four of eight logical CPUs (50%). Unrelated
builds were not altered. This receipt identifies restricted-host qualification.

Ruff, formatting (530 files), mypy (319 source files), generated protocols and
dependency checks pass. The isolated wheel and both native executables pass the
saved CAD/field computations and portable replay; both executables also pass the
unchanged P2 restart/fork proof. Every native manifest file and application source
file is verified. The original external review passes 16 affine and 11 recovery
cases, including all three admission/restart cases; its two unchanged Windows
LF/CRLF fixture failures remain explicit.

See the [P5 acceptance map](P5_ACCEPTANCE_MAP.md),
[structured receipt](receipts/transition-p5.json) and
[CPU/profile conditions](receipts/p5-verification-2026-09-12/CPU_BUDGET.md).
Exact extracted-source qualification and delivered archive bytes are recorded in
the adjacent `programmodel.verification.json` and `programmodel.zip.sha256`.
The source archive needs internet for first dependency installation. Qualification
is Windows x64 / CPython 3.13.15; normal-profile timing and other native platforms
are not certified. P5 acceptance remains open; P6-P8 have not started.

## P4: accepted on the recorded Windows configuration

The user accepted P4 on 12 September 2026 and requested P5 planning. The
[acceptance decision](receipts/p4-acceptance-2026-09-12.json) binds that decision
to delivery commit 60ed00b and its historical ZIP and execution receipts below.
Acceptance retains the stated platform and independent-review limitations.
It is not a new test execution or acceptance of P5.

P4 is implemented and its available Windows gates are verified: **2,027 passed,
zero failed or skipped in 3637.62 seconds**, including all 1,980 unchanged
P3 cases and 47 new P4 cases. The tested source commit is `7d77a32e56aeb3a62c628e184ee3e50510359230`.
See the [acceptance map](P4_ACCEPTANCE_MAP.md),
[structured receipt](receipts/transition-p4.json), and
[workflow](CAD_ARTIFACT_WORKFLOW.md).

The saved Spring-driven CAD recipe consumes the P3 solved length, publishes typed
BREP through ordinary managed Python, and supports independent measurement, mesh,
boundary and translation computations after producer exit. The geometry viewer,
explicit promotion, undo/redo and real dirty-Git run/edit/history proofs use the
existing authority, host, resources and retained-run boundaries.

Both packaged executables pass the five historical computation smokes, the saved
CAD composition and unchanged P2 restart/fork proof. The wheel passes isolated
imports and the real saved CAD workflow. Extracted archive verification includes
all 17 original examples, both old independent proofs, both P3 physical clients,
the CAD composition and portable consumers. The P4 archive is retained at Git
delivery commit `60ed00b`. The workspace's `programmodel.zip` and adjacent
verification/checksum files identify the current delivery.

The unchanged external affine review passes 16 cases. The original recovery
review passes 11 and retains its two Windows LF/CRLF fixture failures before
symlink creation. Both separate real-link probes lack Windows symlink privilege
(WinError 1314); this coverage is explicitly unverified. All three external
admission/restart checks pass. No assertions or deadlines were weakened.

Qualification is Windows x64 / CPython 3.13.15, build123d 0.11.1,
cadquery-ocp-novtk/proxy 7.9.3.1.1 (native OCP runtime 7.9.3.1), and the recorded
science/Qt pins. That P4 receipt certifies neither Linux/macOS/Python 3.12 native
operation nor later phases. The additional independent composition package was not
available locally. First source installation needs internet; no offline wheelhouse
is included. Earlier failed gates and exact predecessor Git blobs remain preserved.

## Previous P3 correction checkpoint — historical verification

P3-R1/P3-R2 are implemented and the fresh Windows regression passes **1,980 tests
in 2962.71s** at `6e5306d7a615fbcce81228909b6431b9a459d7f3`. This retains all 1,898 earlier cases and adds
82 focused/host cases. The unchanged 16-case affine review passes, including from
extracted source. Wheel/native CLI/GUI, five packaged computations, packaged P2
recovery, all old examples/proofs and both physical portable clients pass.

The external recovery result is 11 passed/2 fixture failures before real symlink
creation; all three original admission/restart cases pass. The original Windows
deadlines and byte assertions remain unchanged. Fresh Linux/macOS and those two
symlink controls are not certified. See the
[corrective receipt](receipts/transition-p3-affine-correction.json) and
[acceptance map](P3_ACCEPTANCE_MAP.md).

The user authorizes `programmodel.zip` as the single current delivery. Superseded
ZIPs and sidecars are removed only after exact Git blob recovery is proved in the
[retention record](receipts/p3-affine-correction-2026-09-11/release-retention.json).
That P3 receipt preserves its historical inputs and makes no P4-P8 claim.

## Scope and baseline

The separate `intentional_workbench_transition_20260910` planning pack proposes
P0 through P8. This implementation pass follows its P0/P1 handoff: correct generated
Python names, then establish responsive computation lifetime and sealed intermediate
publications. Typed model composition is the intended use of that boundary. The
later CAD, equation-solving, Git experiment, field and coupling gates are separate
capabilities and are not implied by an infrastructure proof.

On 10 September 2026 the supplied baseline verifier accepted the local
`programmodel.zip` with SHA-256
`e4235d60209d11797a8b3753d1773ebcbcd4e86fa9372fd14862760b604c8576`:
695 archive entries, including all 694 manifest-listed payloads. The source repository
HEAD at the start of this pass was `e5df0c4f6e4498a0a25b3445fb76a05adc842a3a`.
At the start, the working source included accumulated uncommitted changes; that
HEAD alone did not identify the delivered application. The verified archive is
the exact transition input.

The previous delivery's 1,495-test pass is recorded in STATUS.md. It is prior
verification, not a fresh full-suite result for this transition. The six supplied
generated-name tests were rerun unchanged and all six failed on the baseline.
Their SHA-256 is
`d3c3546200badd83a186dbced0ab8d322bce1e703732fa038d4e6c1f4e870563`.

## P0: generated-name hygiene — accepted

The baseline allowed an authored binding to replace the launcher's `_entrypoint`
or a generated operation's `_cv_time` dependency. The correction uses generated-symbol
allocation while retaining valid author identifiers and accepted program semantics.

Use one neutral allocator for implementation-owned dependencies, helpers and
temporaries. Reserve normalized authored identifiers, including binding and load
sites in the relevant lexical closure. Allocate names consistently across emitted
modules, launcher invocation and explicit raw-source invocation adapters. Preserve
the canonical model and the real emitted package execution path.

Existing canonical expressions can explicitly refer to runtime-provided helpers.
Their ordinary evaluation and authored shadowing remain meaningful. Protect the
implementation's own references separately; do not rewrite arbitrary canonical
loads or invent a reserved-user-name blacklist.

The supplied six tests remain byte-for-byte evidence. Additional parity tests cover
local, nested and free references through persistent launch, live Run, Trace, Debug
and the registered Python backend. The phase gate also requires existing regression
tests, both independent authoring proofs, source origins and historical persistence.

The accepted source commit is `e0c60577c1013988632f7718c947b30ebd6e9944` on
`workbench-transition-p0-20260910`. A private index imported the verified source
baseline and recorded the correction; the user's original HEAD and index stayed
unchanged. [The phase receipt](receipts/transition-p0.json) records exact commands,
hashes, environment, earlier failures and the accepted 1,522-test result. Both
scale-performance limits passed unchanged. The existing independent authoring and
direct-math proofs passed, and canonical example input bytes were retained.

The full gate also exposed a debugger completion race. Terminal delivery now follows
stdout delivery, child exit and temporary-tree cleanup. Three deterministic lifecycle
tests cover that correction; no ProgramModel semantics changed.

## P1: lifetime, isolation and publication — accepted on the recorded Windows reference environment

Before P1, the domain-workbench button prepared and advanced backend work on the
GUI thread, and the kernel cleared scientific runtime state on editor replacement.
The [baseline measurement](receipts/transition-p1-before.json) records that blocking
behavior. The promoted implementation moves computation ownership to the host;
editors attach or detach without destroying an independent running attempt.
Interactive debugging retains its explicit editor-session lifetime.

Submission pins canonical source and request. Serialization, hashing, supervised
preparation and backend execution, and resource admission stay outside GUI handlers.
Headless execution waits for the same submitted lifecycle. Python preparation
finishes before the existing managed Python child starts; there is no nested solver
worker running another Python executor. Installed trusted composition selects
workers, never project-supplied imports or pickled callbacks. Tests requiring local
callback identity explicitly select in-process composition.

Global structural integrity remains mandatory. Executable completeness and backend
availability follow the selected root's dependencies. Source hashing deliberately
covers the whole immutable project, and input hashing includes the normalized
request; this does not claim minimal dependency hashing or later Git experiments.

[Computation publications](COMPUTATION_PUBLICATIONS.md) defines the implemented
typed admission boundary. A sealed resource remains an exact consumable reference
while its producer runs and after its exit, cancellation or crash. A receipt is not
a claim that the entire producer succeeded. Progress can coalesce, but sealed
publications and terminal outcomes use bounded lossless delivery.

The first promoted full suite exposed an operational resource leak: preparation
snapshots were entering the scientific resource store. Attempt-local scratch now
holds source snapshots and emitted execution artifacts. Explicit verified reads
reuse durable inputs without bulk copies; only checked terminals and admitted
scientific outputs enter durable storage. The unchanged historical foundation
archive proof passes exactly and still rejects altered binary plans. New real
success/cancellation/crash and editor-preview proofs retain durable closure while
cleaning scratch state. No project format or historical encoding changed.
Shared submission also rejects durable evidence without an explicitly supplied
resource store before attempt allocation, for production and local embedding.

The same regression exposed UI expectations that assumed synchronous runtime and
Trace delivery. Those tests now wait for their actual observer/completion phase
while preserving their assertions and deadlines. Stop during pending Run/Trace/
Debug preparation immediately reports cancellation and prevents even a late typed
artifact from starting execution; running-child cancellation remains unchanged.
Trace admission reuses exact immutable binding records within its accumulator;
all fields, history and events remain unchanged, with no GC-policy changes.

A later intermediate full run recorded 1,740 passing tests and two failures in
1,912.11 seconds. Its failures were the existing three-second main-window agent-edit
preview and five-second search/undo preview deadlines. Python preparation now
defers the SVG rendering import to artifact export, and accepted EditorPreparation
snapshots wake condition waiters. Both original checks passed unchanged in the
corrected 69-test cohort; no deadline or assertion was loosened. Variable import
probes informed this dependency correction but do not establish a wall-time speedup.
Failed and interrupted full attempts remain recorded with their source identities;
partial attempts and focused cohorts are not relabeled as complete regression passes.

The [acceptance map](P1_ACCEPTANCE_MAP.md) links P1-01 through P1-09 to actual proofs.
Final source: `d5b0b98d2920fd23d630d4f57d26ca1485bd39ff`; complete suite: 1,745 passed in 1,208.66 seconds on a95ca791; all 851 source snapshot files matched afterward. The packaging-only follow-up passed 11 focused tests and native smoke; application source stayed identical.
Corrected quiet matrix: 4 passed in 81.00 seconds in the recorded Windows offscreen environment, with pre/post source and test hashes unchanged.
Release checks: wheel build and isolated import, fresh Windows CLI/GUI smoke, and extracted-source preflight passed, including all 17 examples and both independent proofs.
See [final receipt](receipts/transition-p1.json) and
[corrected timing receipt](receipts/p1-windows-offscreen-2026-09-10/manifest.json) for exact source hashes,
commands, retained earlier failures and raw measurements. The receipt distinguishes
completed gate results from unverified platform checks.

This is P0/P1 infrastructure only. P2–P8, authored-Python model/CAD publication,
new scientific solvers and experiment composition remain pending. Measurements are
Windows/Qt offscreen observations; Linux/macOS native execution is unverified.
The 120-second large-source watchdog is a liveness bound, not a throughput promise.

## P2: original Git freeze/run delivery — historical Windows verification

The [transaction contract](GIT_EXPERIMENTS.md) first fixed the declared input closure,
definition/presentation boundary, retained run ref and recovery ordering. The real
dirty-Git proof passed before automatic branching was introduced: 11 focused tests
plus 27 architecture/dependency checks, recorded in the immutable
[first-freeze receipt](receipts/p2-first-freeze-2026-09-10.json).

Freeze uses a real empty private Git index and creates the input commit, per-attempt
retained ref and durable ready record before the existing host starts computation.
Original HEAD/index and unrelated staged/unstaged/untracked content remain intact.
The first accepted semantic candidate forks once through ordinary session loading
and native history. Later edits stay on the unrun variant. Presentation and
unaccepted text do not fork; identical reruns allocate distinct attempts on the
same input commit. Common-Git retention survives branch labels and clean inactive
worktree removal. No new authority, execution engine or canonical project exists.

Focused proofs cover dirty repository capture, portable source replay, worker and
resource survival, same-revision isolation, checkpoint compatibility, transaction
failures, undo/redo and actual Qt/automation handoff. The automation/Git/GUI cohort
passed 24 tests with its source unchanged. These are preliminary gates, not the
final full-regression result. [P2's acceptance map](P2_ACCEPTANCE_MAP.md) links all
P2-01 through P2-11 requirements. The [final receipt](receipts/transition-p2.json)
records exact source, complete regression, packaging and platform limitations.

The accepted P0/P1 archives, adjacent verification files, historical evidence and
legacy tests remain unchanged. P2 will have a separate archive. P3–P8 remain pending.

P2 final verification: Complete regression: 1,786 passed in 1300.75s. P2 plus architecture/dependency gate: 65 passed in 438.87s. Ruff, format, mypy and generated Protobuf checks passed. Wheel, native Windows CLI/GUI (including real P2 freeze/fork/reopen), all 17 extracted examples and both independent proofs passed.
Verified application source: `dcc83a5a26c9b2a9501fb7c87b3780432f0c1575`. The P2 phase receipt and acceptance map distinguish this delivery from the preserved P0/P1 results. P3–P8 remain pending.

## P2 independent review correction — verified on Windows

The review pack reproduced four additional gaps; its probes also failed unchanged
on this Windows machine. They concern repeat capture inside managed worktrees,
current auxiliary source transfer, failed editor-context preparation and persistent
metadata failure after native-journal acceptance. Their correction stays within
the existing Git/session/authority/host lifecycle. No canonical model or computation
engine was replaced. The original P2 archive and receipts remain preserved.

All four unchanged independent probes now pass. Additional tests cover a complete
source-bearing lifecycle, source races on both sides of fork acceptance, persistent
error and notification failure, subsequent edit policy and path ownership. New
fixture mistakes (duplicate domain IDs and an LF assumption on Windows) were fixed
without changing legacy expectations. Complete regression and packaging now pass;
the [acceptance map](P2_ACCEPTANCE_MAP.md) distinguishes these corrections from the
historical P2 verification. P3-P8 are not claimed.

Corrective full regression: 1,800 passed in 1512.20s. P2/Qt/automation/architecture gate: 79 passed in 769.87s. All four original review probes pass unchanged. Ruff, formatting, configured mypy, protocol generation, wheel/native Windows builds, packaged source-bearing rerun/fork, all 17 extracted examples and both independent proofs passed.

Verified implementation: `1c86f680fe05dc6edc36f6b1f203fdaed7a5d113`. See the [corrective receipt](receipts/transition-p2-corrections.json). P3-P8 remain unstarted.

## P2 freeze-recovery follow-up — verified on Windows

The corrected-archive review reproduced R5/R6 on this Windows machine. A ready
attempt now establishes durable authoring protection before execution admission;
ordinary reopen reconciles retained bindings and refuses uncertain state. The
variant marker is a cache, while the immutable session context stays intact.
The [recovery contract](GIT_FREEZE_RECOVERY.md) records the ordering and recovery
policy. Twenty new cases plus 27 architecture/dependency checks pass; lint, format,
types and protocol checks pass. Legacy regression and packaging now pass as recorded below.

The untouched review runner additionally exposes an LF-only assumption in two
controls on Windows; actual symbolic-link creation lacks privilege here. Those
controls are recorded separately from the two reproduced recovery defects. The
original archives, 159 legacy test files, 239 example files, 248 historical receipts
and 41 canonical-domain files remain byte-identical. P3-P8 remain unstarted.

## Freeze-recovery verification

P2 freeze-recovery verification: 1,820 tests passed in 2126.73s. The new recovery/architecture gate passed 47 cases; the legacy P2/Qt/automation/architecture gate passed 79. The original four review probes and four Windows-portable follow-up cases pass unchanged. Quality checks, fresh wheel/native CLI/GUI builds, packaged stale-marker restart/fork, all 17 extracted examples and both independent proofs passed.

See [the source-bound recovery receipt](receipts/transition-p2-freeze-recovery.json). Native Linux/macOS and Windows real-symlink controls were unavailable. P3-P8 remain unstarted.

## P3: shared unit-aware equations — planning started

The new [handoff](../../CODEX_P3_HANDOFF.md) accepts the scoped P2 review and starts
the existing P3 phase. The [implementation plan](P3_IMPLEMENTATION_PLAN.md) fixes
the sequence: historical compatibility, rational dimensions/unit algebra, checked
equation compilation, registered linear solving, DC and non-electrical clients,
then real authoring/Git comparison and release proofs. The
[acceptance map](P3_ACCEPTANCE_MAP.md) preserves all ten original P3 requirements
and makes the P0/P1/P2 recovery tests continuing gates.

No application code, canonical model, contract, old test or historical receipt
changes in this planning step. The accepted archive and final delivery sidecar
agree; all 1,107 physical manifest files matched the checkout before documentation
edits. Ninety-eight headless P2/architecture cases collect successfully, without a
new execution claim. Exact files for the three additional independent tests in
the handoff remain pending; they cannot be relabeled as locally rerun review.

The first implementation gate must prove old retained-run identity and edit
protection across versioned dimension changes. Current frozen-definition validation
depends on serialized definition bytes, so format migration must not invalidate
historical bindings or silently restore in-place editing. New numerical work uses
the existing host lifecycle, resource admission and Git transactions. P3 acceptance
and P4-P8 completion are not claimed.

## P3 implementation: rational value boundary

The first code checkpoint extends dimension powers through explicit native and
Protobuf versions while preserving integer encodings and the existing native
project container. The dimension form accepts exact ratios. Sixteen new cases
cover normalization, bounds, ambiguous encodings, property identity, persistence
and journal undo/redo. The 196-case value/unit/protocol/archive/architecture cohort
passes, as do both unchanged R5/R6 recovery probes. Configured mypy (269 files),
lint and regenerated-protocol checks pass. Source-bound logs are retained in
`docs/receipts/p3-dimensions-2026-09-11/`. An initial new test used the authority
constructor incorrectly; its fixture was corrected without changing legacy tests.

Unit algebra, equation solving, DC authoring and final P3 gates remain in progress.
The old assignment backend and historical evidence keep their meanings and bytes.
# P3 implementation checkpoint: declared unit algebra

The unit-product foundation and isolated Pint adapter are implemented. The focused
cohort passed 88 tests in 54.32 seconds, including the unchanged foundation archive
proof and architecture/dependency gates. Targeted typing and lint pass after an
explicit numeric type narrowing. This is a P3 implementation checkpoint, not P3
acceptance: equation solving, physical-domain integration and final regression
and packaging remain in progress.
# P3 implementation checkpoint: shared equations

The versioned math@2 request schema, checked scalar compiler and registered
NumPy backend are implemented. The initial shared-boundary cohort passed 112
tests, including the old computation, foundation archive and vocabulary UI
checks. Two subsequent host tests exercise a real worker, durable result resource
and portable replay; they exposed and then verified a fix preserving complete
reference-model input order. The configured typing pass checks 274 source files.
Circuit transformation, Git/GUI physical acceptance and final delivery gates
remain in progress. See SHARED_EQUATIONS.md for the bounded numerical contract.

Checkpoint closure: the updated equation/host/legacy foundation/architecture
cohort passed 115 tests in 144.83 seconds. The unchanged computation-scope cohort
passed all 3 tests, and configured typing passed all 274 source files. Source-bound
receipts and compressed raw logs are in `receipts/p3-equations-2026-09-11/`.
# P3 implementation checkpoint: topology-derived DC equations

The first physical domain and deterministic math@2 transformation are implemented.
The divider, loaded divider, equivalent kOhm/mA inputs and a distinct bridge network
pass their numerical/origin checks. Generated ownership stays disjoint from the
canonical project while derived references can resolve the frozen input context.
The focused circuit/transformation/input-scope/architecture cohort passed 58 tests
in 9.86 seconds; configured typing passed 276 source files. UI/Git acceptance,
distributable examples and final regression/packaging are still in progress.

## P3 implementation checkpoint: native authoring and retained comparison

Two native physical examples now execute through the same backend without a
ProgramModel contribution. The desktop offers them under File / Physical examples,
selects domain notations before generic fallbacks, and offers the declared unit
catalog in form/table/object dialogs. Exact schema version selection fixes an
existing foundation installation regression without changing its test.

The real dirty Git proof freezes the divider, adds a load through accepted native
commands, undoes/redoes, reruns and compares verified retained evidence. Original
HEAD/index/unrelated work stay unchanged. The old worktree can be removed and both
results reopened after host exit. The Qt proof uses real object dialog fields and
reference controls, the existing deferred fork, and the existing Git worker for
comparison/resource reads. Its 60-test cohort passed in 142.51 seconds; the separate
32-test dependency-failure/architecture cohort passed in 11.09 seconds. Quality,
278-file typing and regenerated-protocol checks pass. Source inventories and logs
are retained under receipts/p3-workbench-2026-09-11.

The new standalone physical proof loads saved inputs with factories and Qt imports
forbidden, checks applicable runtime notations across actual observation history,
then replays sealed Protobuf plans after host closure. The archive verifier and
native build smoke now include both physical clients. Full regression and packaging
remain the next gate; missing external review files remain explicitly unavailable.

## P3 release checkpoint: native recovery and release-helper correction

The Windows wheel and native CLI/GUI builds pass. All five packaged computation
smokes validate sealed evidence and resources: Python, old indexed math in both
frontends, DC and the spring relation. Both native frontends also pass the original
P2 stale-marker restart/fork proof with only fresh output paths substituted.

The first full P3 run recorded 1,897 passing tests and one release-helper fixture
failure in 2,798.55 seconds. The correction gives the production release operation
explicit additional computation cases while preserving the old helper contract
and every existing assertion. The unchanged helper tests plus architecture pass
35 cases; the corrected production operation still executes all five real native
computations. Lint/format, 278-file typing and wire generation pass. Full regression
is being rerun at the corrected source. The earlier failure and all exact source
inventories/logs remain in receipts/p3-verification-2026-09-11. P4-P8 remain outside
this work; the three additional external handoff tests still need their source files.

## P3 final available-gate verification

Commit `0a8dd459c44d37e912d717159341f71639ba7e18` passes the complete 1,898-case suite
in 2400.96 seconds (40 minutes), with no source changes during the run. The result
includes all 1,820 original tests, all 78 new P3 tests, the unchanged 98-case
P2/architecture cohort and the existing Qt/recovery/automation cases. All 161 old
test files, 239 old example files, 331 historical receipt files and 12 protected
delivery files remain byte-identical to the accepted baseline inventories.

Wheel and native CLI/GUI checks, five native computations, both packaged recovery
proofs and all quality checks pass. A fresh source extraction verifies all manifest
bytes, both launch entries, all 17 original regenerated projects, the two historical
independent proofs and both physical clients. Physical portable replay reproduces
the same typed resources, evidence and original-object origins after producer exit.

See receipts/transition-p3.json and P3_ACCEPTANCE_MAP.md. A separately named
programmodel-p3-review.zip and external verification sidecar identify the final
delivery without replacing any historical archive. Its final packaging can add
documentation/receipts only after the tested implementation checkpoint.

The three additional independent admission/restart/interpreter tests described in
CODEX_P3_HANDOFF.md remain unavailable locally. They are not replaced by claims
about similar local tests; formal handoff acceptance awaits that gate. Fresh P3
execution was Windows x64 / CPython 3.13.15 / Qt offscreen, not a new Linux/macOS or
Windows symlink-privilege certification. P4-P8 remain outside this implementation.

## P3 independent review: correction planned, acceptance on hold

The supplied `programmodel-p3-independent-review` verifies the original delivery
identity and reports two defects within P3-04: relation typing incorrectly reuses
arithmetic subtraction, and scalar scaling erases interval kind. All 67 supplied
manifest files match their hashes. At `e7752e88cc09353f3e24c63d9430749551792e63`,
the new affine cohort reproduces 11 passes and five failures using pinned Windows
science packages. No application or existing test was changed for reproduction.

The three previously unavailable admission/restart tests are now supplied and
pass unchanged, including the separate-interpreter recovery case. The complete
prior external Windows cohort reports 9 passes and four failures: two original
30-second fork deadlines and two LF assertions encountering Windows CRLF before
symlink creation. The first run's 13 Git path-length failures and the short-path
rerun are both retained. Neither failure class is relabeled as a passing gate.

See [P3_AFFINE_CORRECTION_PLAN.md](P3_AFFINE_CORRECTION_PLAN.md) and
[the planning evidence](receipts/p3-affine-planning-2026-09-11/README.md). The plan
repairs the shared type algebra, requires real host/resource/origin proofs, and
keeps P0/P1/P2 regression and packaging gates. Current status/acceptance documents
now reflect the review; earlier archives and receipts remain immutable. This is
planning only: no corrective implementation or P4-P8 completion is claimed.

## P3 affine correction: type-algebra checkpoint

The shared arithmetic operation now uses explicit dimensional context for interval
scaling, and a separate symmetric relation rule determines residual kind. The
compiler validates this before constructing a matrix and retains equation/operator
origins for diagnostics. Canonical models and portable contracts are unchanged.
The two baseline Windows timeout probes pass unchanged in 41.98 seconds with
their original deadlines. The corrected type/compiler/independent/architecture
cohort passes 161 cases; configured mypy passes for 278 files.

An initial new product test compared a private catalog-anchor coefficient as
though its length anchor were a meter. Its assertion now converts that coefficient
back to the stated physical units before checking 20 or 5. The first run (159
passes, two new-test failures) and corrected run are both retained. The original
independent 16 cases pass unchanged. Host/resource proofs and final regression,
packaging and receipt gates are still pending; P3 acceptance is not yet claimed.

## P3 affine correction: real host and retained results

The eight new computation cases cover real worker execution of the three scaled
translations and point equality, unit-bearing sealed resources, native evidence
reopening, Protobuf plan/evidence round trips, replay after producer closure, and
the original symbol highlighted in graph/table/hierarchy. Invalid equalities in
both orientations publish only failed evidence; an additional in-process guard
proves they cannot reach the numerical solver. All 50 host/notation/DC/architecture
cases pass. No host, authority, resource or runtime implementation changed.

The first new view test incorrectly required historical activity to be deleted
when its revision differs. Existing notations retain that history with a stale
badge and explicit revision. The new assertion now checks that established
contract, including absence of a current-active graph badge; the initial four
new-test failures and corrected run are preserved. Final full regression and
fresh packaging remain in progress. No P4 work is included.

## P5 accepted; P6 entered on 13 September 2026

The user's acceptance is recorded in receipts/p5-acceptance-2026-09-13.json.
The matching ZIP, historical receipt and all original case expectations are
preserved. The new workbench-p6-implementation-20260913 branch implements the
supplied six-stage P6 handoff. P6_CONTRACT.md declares ownership, numerical,
resource, recovery and performance boundaries before implementation. The first
proof is an actual rejected/retried electrothermal window through the existing
host, followed by bounded history and the separate axial structural proof.
No P6 gate is accepted yet; P7/P8 remain outside scope.

## P7 implementation in progress (14 September 2026)

P0-P6 are accepted within the scope recorded in the current status and preserved
receipts; the earlier entries above are historical. The P7 continuum slice has
focused reference, convergence, cost, real host/resource, retained Git/recovery
and responsive UI proofs. The accepted archive has not been replaced.

The pinned native SPARTA participant now has actual flux, complete-input replay,
independent transport and reservoir controls. Its ordinary registered gas domain
and backend retain calibrated inputs, nonperiodic histories, native input tapes,
complete checkpoints and typed previews through existing boundaries. The new
real worker/portable/fresh-resume proof passes28 cases; a separate57-case run
rejects altered native state, input tape, controller and incompatible checkpoints.
The complete gas cohort is being rerun before the integration commit.

P7 remains open: long coupled statistical qualification, an actual qualified
activation/return, gas UI/Git/lifecycle coverage, complete regression and final
packaging are not yet passed. No P8 implementation is claimed.
