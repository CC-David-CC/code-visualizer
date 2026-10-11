# Test strategy

P5 adds closed field/time/preview contracts, transitive resource closure, actual
isolated diffusion/probe execution, portable restart, real dirty-Git and killed-host
recovery, persistent publication-write failures and desktop controls. Convergence
is checked both at the numerical boundary and independently from sealed worker
arrays. The large-history test writes 128 roughly 4 MiB chunks incrementally and
measures lazy view/cache/queue behavior with a CPU worker, native CAD computation
and background preview bursts sampled by QtRuntimeObserver. Normal qualification
keeps the 250 ms heartbeat limit. On 13 September 2026 the user explicitly allowed
350 or 500 ms for the restricted laptop environment; the selected restricted
profile uses **350 ms for this P5 field-heartbeat test only**. Set
`CODE_VISUALIZER_P5_HOST_PROFILE=restricted` explicitly; unset/`normal` keeps 250 ms
and unknown profiles fail. The raw receipt records both profile and threshold.
Interaction p95/p99, memory/cache bounds, worker deadlines and every P4 baseline
expectation remain unchanged. Earlier failed runs keep their original verdicts;
a restricted-profile pass is not a normal-profile timing qualification.
Use requirements-fields.txt in addition to the
P4 dependencies. [The P5 acceptance map](P5_ACCEPTANCE_MAP.md) links raw failed and
corrected receipts; full regression and distribution results are recorded separately.

P4 adds real CAD-resource, managed-Python publication, independent-consumer,
artifact-inspection, geometric-region, promotion and dirty-Git lifecycle tests.
The [P4 acceptance map](P4_ACCEPTANCE_MAP.md) identifies each actual test cohort.
Use `requirements-cad.txt` (including the scientific pins) for this gate. The
saved-source proof `tools/prove_cad_artifacts.py` forbids example-factory imports,
closes each producer/consumer host and replays portable consumer plans. Native
CLI/GUI and extracted-archive verification run this same proof. Missing optional
CAD implementations are diagnosed; they do not substitute for executing the CAD
acceptance cohort. Existing P0-P3 assertions and deadlines remain unchanged.

P3 adds `test_rational_dimensions.py`, `test_unit_algebra.py`,
`test_equation_compiler.py`, `test_equation_computation.py`, `test_dc_equations.py`,
`test_physical_examples.py`, `test_physical_experiments.py`,
`test_physical_workbench_qt.py` and `test_physical_archive_proof.py`.
The [acceptance map](P3_ACCEPTANCE_MAP.md) connects them to the unchanged transition
requirements. Use the pinned `science` extra for the full P3 gate. NumPy solves
are checked against independent divider/bridge and F=k*x expectations, explicit
units, rank failures, physical and normalized residuals, and source origins.

The physical archive proof loads native inputs with example-factory and Qt imports
forbidden, executes through the existing host, closes it and replays a Protobuf
plan from retained resources. The real Git/Qt proof creates a load via native
dialogs and authority commands, forks once, undoes/redoes, reruns and compares
retained evidence with Git/resource verification off the GUI thread. The headless
proof also removes an inactive worktree and reopens after host restart. P2 metadata,
admission, restart, auxiliary-source and checkpoint tests remain regression gates.
No P3 test changes their assertions. Final regression and platform evidence are
reported separately from focused checkpoint results.

P2's independent review adds `test_git_experiments_review.py` (the four supplied
regression probes) and `test_git_experiments_closure.py` (source-bearing lifecycle,
exact file transfer, source races, coherent context publication and persistent
metadata/notification failure). Run these with the existing P2, Qt/automation and
architecture suites; retain prior failed logs and baseline tests unchanged.

## Transition P0 accepted; P1 accepted on the recorded Windows reference environment

The P0 generated-binding and execution-lifetime checkpoint passed the complete
Windows suite: **1,522 tests in 1,890.71 seconds**, with the existing performance
limits unchanged. Its exact source and verification are recorded in
[transition-p0.json](receipts/transition-p0.json). That acceptance remains separate
from the promoted P1 implementation; passing focused P1 tests is not a
full-regression receipt. The [phase receipt](receipts/transition-p1.json) records
source `d5b0b98d2920fd23d630d4f57d26ca1485bd39ff` and each completed or unavailable gate.
Complete regression: 1,745 passed in 1,208.66 seconds on a95ca791; all 851 source snapshot files matched afterward. The packaging-only follow-up passed 11 focused tests and native smoke; application source stayed identical.
Static/protocol checks: mypy passed for 263 configured source files; Ruff checks passed; all 421 files passed formatting; Protobuf regeneration check passed.

P1 separates callback semantics from production isolation. Existing local closures
explicitly use `InProcessTestKernel`, which owns an `InProcessDriver` and its cleanup.
They retain their assertions, numerical results, ordered advancement, error handling
and resource checks. Production tests use trusted static worker compositions and
real Python/backend processes, including independent producer and consumer hosts.
No implicit in-process fallback, blanket monkeypatch, skip, or performance-threshold
increase substitutes for a failed process test.

Required focused proofs include:

- `test_computation_publications.py`, `test_worker_protocol.py` and
  `test_editor_worker_contracts.py`: native/Protobuf round trips, historical hash
  preservation, typed bindings, closed envelopes, receipt budgets and no durable
  receipt on failed admission.
- `test_computation_transfer_admission.py` and `test_resource_admission_phases.py`:
  bounded resource bytes, descriptor metadata and empty-transfer counts; exact
  transferred-reference closure; callback-free host contract checks; validator
  behavior confined to explicit worker/in-process admission.
- `test_computation_publication_process.py`: real consumption while a producer is
  active and after its process/host exit, sealed receipt survival across cancellation
  and crashes, CPU cancellation, and missing-strategy rejection.
- `test_computation_admission_races.py`: cancellation between real Python preparation
  and managed-child installation prevents entrypoint execution; finalization rejects
  cancellation and concurrent host close drains the verifier before retaining success.
- `test_computation_scope.py`: unrelated incomplete domain contents do not block a
  selected computation; referenced incompleteness and global structural corruption do.
- `test_editor_preparation_qt.py` and `test_computation_host_qt.py`: real controls,
  asynchronous preparation, revision-safe replacement, retained attempts/publications,
  unchanged editor state, GUI-thread selection, progress/resource pressure and cancel.
- `test_preparation_import_boundaries.py::test_real_editor_preparation_does_not_load_rendering_or_qt`
  uses a fresh interpreter to protect the Python preparation dependency boundary.
- `test_editor_preparation.py::test_prepared_snapshot_wakes_an_already_waiting_observer`
  proves accepted preparation updates wake existing condition waiters. Existing
  three-second agent-edit and five-second search/undo preview waits remain unchanged.
- `test_computation_resource_lifetime.py` and `test_resource_readthrough.py`
  preserve durable scientific closure while operational snapshots/artifacts stay
  in scratch storage. `test_foundation_archive_proof.py` retains exact historical
  bytes. `test_computation_store_admission.py` rejects an EvidenceStore without
  an explicit ResourceStore before allocating an attempt.
- `test_runtime_snapshot_sharing.py` checks complete immutable record fidelity,
  historical snapshots and reset boundaries; allocation reuse changes no GC policy.

The pre-P1 GUI receipt records a real CPU-bound callback inside
`DomainWorkbenchWidget.run_computation`: a **455.47 ms** handler and **466.62 ms**
heartbeat gap. [transition-p1-before.json](receipts/transition-p1-before.json) includes
the source hashes, stack, raw timings and environment. It is an observational
baseline, not a P1 pass. The [corrected quiet receipt](receipts/p1-windows-offscreen-2026-09-10/manifest.json)
records 4 passed in 81.00 seconds in the recorded Windows offscreen environment, with pre/post source and test hashes unchanged, separately from the complete legacy
suite and packaging/extraction result: wheel build and isolated import, fresh Windows CLI/GUI smoke, and extracted-source preflight passed, including all 17 examples and both independent proofs.
Timing checks run without competing profilers, process suites or source
generation; correctness tests retain their normal bounds. Earlier failed and
aborted runs remain recorded rather than being relabeled as passes. The new
large-source 120-second completion watchdog is a liveness bound, not a
throughput promise. Variable import probes are diagnostics, not evidence of
wall-time speedup. P2–P8 and authored-Python typed model/CAD publication remain
outside this gate; native Linux/macOS checks remain unverified on this host.

## P2 real Git transactions and retained attempts

The [P2 acceptance map](P2_ACCEPTANCE_MAP.md) covers real dirty Git repositories,
exact capture before execution, unrelated staged/unstaged/untracked preservation,
durable refs, failure boundaries, first-edit branching, local history transfer,
same-revision isolation, retained reopening and conservative checkpoint compatibility.
Tests use the existing supervised worker and actual Git commands. The first dirty
freeze proof passed before the automatic edit gate was introduced; its receipt and
failed precursor are retained. Actual desktop widgets prove that Git operations
stay off the GUI thread and unsubmitted signature text does not fork. JSON and
Protobuf automation share deferred authority admission and the CLI reconnects to
the selected worktree without destroying its scientific host.

P0/P1 archive/receipt bytes, historical evidence and legacy tests are preserved.
P2 final regression, source identity, packaging and platform limitations are recorded
independently; focused cohorts are not substituted for the complete suite.

## One package execution representation

Package proofs compare persistent and temporary execution of the exact emitted files,
including authored root/nested initializers, relative imports, initialization order,
real __file__, inspect.getsource and importlib.resources. MODULE/PACKAGE collisions
and reserved initializer spellings are explicit diagnostics. Semantic ownership uses
the canonical package ID. Multi-file breakpoints, stack navigation and runtime origins
use artifact-relative locations, including failures during package initialization.
Invocation matrices retain all supported callable shapes and signature failures.
Temporary trees survive debugging and are cleaned up after completion/cancellation.

Native-11 migration tests cover runtime_settings and explicit module kinds through
save/reload and forward/inverse journals. Terminal-v2 compatibility verifies original
hashes before decoding a missing kind as MODULE. UI tests create/edit a root initializer
and prove authority undo/redo, persistence, real-file previews and execution.

Artifact admission tests force readers and directory promotion to overlap. They
verify complete-tree reads, a final revision check after waiting, responsive reads
during staged generation, bounded previews and explicit external file-lock failures.
Recovery tests preserve final disk rereads while reusing identical decoded input;
Git tests verify one session-owned discovery with fresh status/HEAD and replacement
session scoping. The existing editor-open performance budget remains unchanged.

## Canonical Python ownership

The module-ownership gate exercises ordered imports, assignments, aliases, class
headers and bodies, mature function references, and startup declarations. It rejects
missing/duplicate owners, dangling references and identity collisions. Module-only
programs, repeated names in distinct modules, lexical linked calls, constructors,
defaults and focused execution dependencies run through the existing Python pipeline.
Generated files, live Run, Trace, Debug and portable terminal execution share these
semantics and preserve source and origin mappings.

Migration tests cover native revision 4–9 snapshots and forward/inverse journal
operations. They preserve old module/class semantic anchors through rename and reload,
retain Python type comments, reject duplicate executable setup in native revision 10,
and preserve unsupported line-bound directives without silently losing meaning.
Qt proofs edit module/class/source ownership through the authority, undo and redo,
and correlate readable module previews with execution-harness breakpoints and domain
origins. The unchanged 500-diagram release budgets remain a regression gate.

## Published boundaries

Public-reference closure regressions exercise missing and mismatched providers in
schema defaults, choices, dimensional constraints, reference-model values and nested
inert definitions. They reject unrelated-provider shortcuts, ambiguous immutable
dimension bases and dependencies borrowing declarations from their consumers.

Resource contract tests prove JSON/Protobuf round trips, reserved legacy field tags,
untyped descriptor identity preservation, explicit legacy-string rejection and typed
chunk transfer. The admission matrix covers local/exported/portable/streamed/cached
inputs, the terminal, bytes/file outputs, artifacts and live/final observations.
Unknown typed metadata survives archival transfer; computation rejects it before
backend execution or output/evidence admission, as applicable. The foundation proof
reproduces its native project, disposable descriptors, resources and evidence exactly.

## Universal boundary proofs

`test_canonical_values_resources.py` checks every CanonicalValue variant, inline
bounds, dtype/shape/dimension contracts, cross-model reference traversal, compound
intermediate transformations, authority edits/history, deterministic persistence,
resource identity/hash verification and explicit evidence promotion.
`test_value_boundary_rejection.py` rejects deeply nested invalid numeric slots
without recursion and oversized immutable-record replacements without unbounded reads.

Protobuf golden and contract tests cover scalar presence, all value variants,
schemas/objects, resources, requests/plans/sessions/events, evidence and typed commands.
Real authenticated WebSocket tests retain capability grants, conflicts, idempotency,
undo and native events. `python tools/generate_protocol.py --check` verifies the
checked-in bindings using the pinned compiler. Generated files are excluded from
handwritten lint/type diagnostics; their exported stubs type-check the adapters.

Computation tests exercise Python terminal adapters outside the programming pipeline, deterministic origins,
portable worker execution, evidence resources, missing/ambiguous paths, immutable
inputs, revision-pinned overlays and the existing Python backend. Foundation tests
keep mathematical and coordinate invariants in extensions and exercise structured
tensor equations, generic value editors and same-object notation highlights.
The complete legacy suite and all 17 generated Python examples remain required.

`test_foundation_archive_proof.py` recreates the mathematical proof using isolated
extracted source, compares binary plans, resources and evidence, and rejects a
tampered binary plan. The source archive verifier requires this proof alongside
the independent from-blank authoring proof and every catalog example. Wheel smoke
verification checks all seven contracts, generated modules and typing stubs and
round-trips a value using the wheel's generated code.

## Test pyramid

1. Pure domain tests prove constructors and invariants.
2. Property tests explore commands, persistence round trips, and layout metrics.
3. Application tests exercise revisions, transactions, events, undo, permissions, and conflicts.
4. Adapter contract tests run scenarios through embedded, CLI, Python, JSON-RPC, and MCP paths.
5. Qt tests send real key, pointer, wheel, drag, close, and detach events.
6. Artifact tests parse, compile, run, hash, and inspect generated outputs.
7. End-to-end gates reproduce acceptance scenarios A through L.

The intentional-workbench gate additionally exercises schema validation, containment
ownership/cardinality/cycles, references, typed domain commands, actor-aware undo/redo,
legacy migration and current-format round trips, missing implementations, bundle registration, and stable
semantic indexing. Graph/table/form tests edit the same canonical identities and
require other notations and semantic selection to observe each accepted revision.

Transformation tests reject dependency cycles, missing prerequisites, ambiguous paths,
and collisions, then prove deterministic ProgramModel output and complete origins.
Traffic Light generates through the existing Python emitter, executes as a normal
generated project, and uses the existing trace/debug worker. Runtime tests resolve
State, Transition, and Action identities back into all applicable notations. Qt tests
exercise schema creation and actual structured edits instead of only constructing DTOs.
The complete pre-existing suite remains a final regression gate.

`test_workbench_acceptance.py` runs the complete Amber scenario through a real table
edit binding, native persistence, undo/redo and the trace worker. A runtime subscriber
captures the kernel's graph, table, hierarchy and semantic lens on the same event,
then correlates that event to the generated source span and immutable origins. It
requires active State, Transition and Action identities while the canonical program
remains empty.

## Determinism

The invocation gate covers all sixteen callable-kind/method-kind combinations
through generated projects, live Run, Trace and Debug. Adapter tests additionally
exercise the real desktop buttons, CLI, automation and structured capability input
for the async, generator and class examples. Assertions cover body effects, arguments,
useful trace events and correct exception propagation; ordinary return display is
tested as an explicit policy.

`test_invocation_binding.py` checks the canonical signature binder for missing
arguments, excess positional arguments, unknown keywords, positional-only and
keyword-only restrictions, duplicate binding, defaults, `*args` and `**kwargs`.
Receiver and constructor signatures use the same binding rules. Tests prove default
and annotation expressions are not evaluated, cover Python identifier normalization,
and reject stale invocation metadata. Actual GUI, CLI and automation calls verify
rejection before worker admission and successful selected arguments even when the
saved project invocation is invalid.
Class-private parameter tests cover Python name mangling for all method kinds,
ordinary positional binding, `**kwargs`, dunder exemptions and class-name
normalization. Incomplete callable identifiers remain diagnostic authoring states
rather than making project assessment raise an exception.
The legacy macro compilation fixture now declares a library project because its
parameter macro introduces required inputs. The inversion fixture supplies its
required `answer` argument before generation. Their existing structural, compilation
and undo assertions are retained; invalid configured calls have their own explicit
admission tests.

`test_domain_authoring_proof.py` runs the from-blank proof in an isolated interpreter
that blocks example factories, FSM implementations and Qt. It records every authority
command, replays them to identical native JSON, executes through the existing Python
pipeline and checks one runtime event's original State/Transition highlights across
graph, table and form. The shipped artifact lives in
`examples/proofs/authority-authored-toggle/`; its reproducible script is
`tools/prove_domain_authoring.py`.

The context extension checks literal arguments across persistent and temporary package
namespaces; required receiver setup, defaults and top-level construction; explicit
unresolved legacy expressions; and migrated journal undo/redo including transactions.
Composed-notation tests exercise cross-domain direct edits, mathematical layout,
runtime decoration, occurrence identity, connector anchoring, query budgets and
schema-aware field/role/coordinate diagnostics. Actual Qt gestures and expression
preview/edit controls complement the immutable compiler tests.

Intermediate-language tests lower through multiple authored schemas and validate
each stage, deterministic node IDs, dependency ordering, origins, ambiguity/cycles,
and disposal. Git proofs use isolated temporary repositories and real Git commands;
branch changes must not resurrect an earlier journal or allow a stale authority to
write over the checked-out project.

The language-authoring gate checks closed typed decoding, structural/text bounds,
durable fine-grained and whole-definition history, conflict handling, incomplete
holes, missing/unsupported implementations, schema scope, stable template identities,
deterministic lowering, and shared runtime origins. Actual Qt controls construct
notation/rule/template definitions and edit the full authored FSM loop. The normal
Traffic Light example now stores its behavior as inert authored definitions rather
than depending on the handwritten FSM transformation.

Tests inject ID factories, clocks, filesystem ports, text metrics, and process runners. Tests do not sleep to prove debounce behavior. Golden geometry compares semantic coordinates before raster comparison.

## Independence

The public ecosystem boundary is covered by `test_contract_identities.py` and
`test_contract_identities_review.py`: qualified names, owner grants, atomic collision
rejection, private-contribution impersonation, exact representation dependencies,
version validation, and binary publication manifests. `test_foundation_units.py`
checks shared SI definitions, dimensional identity, explicit conversion paths and
contexts, immutable public meanings, persistence, and authority recovery/undo.
`test_vocabulary_installation_ui.py` installs that vocabulary through the real UI.

`test_resource_transport.py` proves multi-message transfer into a separate portable
worker with whole-payload reads forbidden, resource-return parity, exact evidence
envelope limits, budget enforcement, corruption/order/replay rejection and cleanup.
`test_backend_lifecycle.py` covers batch/stream parity, capabilities/API versions,
progress/observation sequencing, cancellation, shared original-object highlighting
and portable evidence. These run alongside all existing architecture, ProgramModel,
generation, runtime, native persistence and performance tests.

An AST-based test scans every new source file. Imports from the parent prototype and PySide6 imports outside the Qt adapter fail the build.

`test_dependency_layering.py` also rejects outward application, persistence,
generation, validation, and UI imports anywhere in the domain package. It checks that
canonical program modules have no DRAKON dependency and imports them in a fresh
interpreter with editor/application imports actively blocked, catching package
initialization leaks. Shared semantic enums retain identical neutral class objects
in canonical and DRAKON code. Python entrypoints, lowering, IR, and emission are
checked for DRAKON and application imports; conversion APIs must belong to the
application adapter.

`test_complete_program_model.py` removes all views from every catalog example,
round-trips the canonical project, compares newly generated files with the original
project's output, and executes the generated entrypoint. It also covers all statement
families, deterministic legacy migration, duplicate executable-state rejection,
typed subtree editing, identity-preserving undo, and canonical-only dependency
analysis. These are executable ownership checks, not assertions against checked-in
generated artifacts alone.

## M0 gate

The M0 gate constructs an empty DRAKON callable with one Header and End, an empty rooted mind map, an empty free-form scene, and one project containing all three. It serializes the project twice and requires byte-identical current-format JSON.

## Completed vertical gates

- M1 uses two live SDK clients to prove revisions, event observation, conflicts, transactions, persistence, restart idempotency, actor-aware undo, and journal recovery.
- M2 drives real Qt widgets through New/Example/Open, Hello World, F6, save/generate/F5, command-palette keys, and every close/recovery-copy decision.
- M3 uses property tests for adaptive text and recursive boundary coverage, deterministic SVG/PNG fixtures at 1x/2x, visual inspection, real two-axis wheel/pan/zoom events, palette drag/drop, and multi-node transplantation onto both horizontal and vertical routes with undo.
- M4 lowers a two-function package through typed IR twice and requires byte-identical output; parses/compiles every file; verifies manifest hashes and bidirectional spans; runs the package launcher; maps bounded F7 trace events; proves invalid Python stays editable while blocking generation; uses a fake scheduler to prove debounce cancellation; rejects stale promotion; and drives Python Project, reveal, trace, run, and blocked diagnostics through real Qt controls.
- M5 round-trips, renders, and compiles every semantic atom; binds all 27 recipes to real scene semantics; inserts all 21 macroicons as one undoable revision; executes expression, assignment, loop-else, TREE, timer, class/method, linked-Call, and silhouette cases; diagnoses illegal flow contexts; and drives the typed Inspector plus keyboard structural wrap through Qt events.
- M6 drives interactive breakpoints, stepping, exception pauses, source/diagram mapping,
  whole-document detach/dock, comparison layouts, artifact tamper/diff behavior,
  package composition, and the Dijkstra/A* project.
- M7 edits ordered mind maps and layered free-form scenes through real widgets,
  sanitizes assets/shape packs, verifies connector bridges, and exports deterministic
  SVG/PNG/PDF.
- M8 connects real authenticated WebSocket clients, SDK, CLI, and MCP to one authority;
  it proves conflict/resync/capabilities/proposals/presence and GUI reflection.
- M9 covers themes/accessibility, semantic clipboard/search/navigation, OS project
  leases, bounded/cancellable execution, failure injection, 500-diagram scale,
  wheel and self-contained source-folder packaging, and regeneration/manual visual
  evidence. The folder gate creates a fresh environment from its bundled wheelhouse,
  then starts both the CLI and off-screen GUI before atomic promotion.

## P2 freeze-recovery verification

P2 freeze-recovery verification: 1,820 tests passed in 2126.73s. The new recovery/architecture gate passed 47 cases; the legacy P2/Qt/automation/architecture gate passed 79. The original four review probes and four Windows-portable follow-up cases pass unchanged. Quality checks, fresh wheel/native CLI/GUI builds, packaged stale-marker restart/fork, all 17 extracted examples and both independent proofs passed.

See [the source-bound recovery receipt](receipts/transition-p2-freeze-recovery.json).
Native Linux/macOS and Windows real-symlink controls were unavailable. This is
the historical P2 checkpoint; subsequent phase status is recorded in STATUS.md.

## P6 coupled and structural qualification

P6 preserves all 2,122 accepted P5 case identities and the original test bytes.
The five gates in `P6_ACCEPTANCE_MAP.md` map to focused cohorts plus one complete
regression run. Overlapping cohorts are never added as distinct tests. Source
commits, hashes, CPU job records, raw JUnit/logs and earlier failures are retained.

Independent reference code computes continuous and eliminated discrete thermal
solutions without importing production participants or residual assembly.
Actual saved-source worker outputs are decoded before comparison. Native axial
tests assemble through P3, consume BREP after its Python producer exits and
compare arrays, forces, stress and energy to independent oracles. Golden channel
and checkpoint bytes are separate from unchanged P5 spatial contracts.

Persistent failure tests cross child storage, parent sealing, receipt, retained
association, acknowledgement and unavailable error reporting; fresh-interpreter
recovery and explicit checkpoint resume prove P2 editing protection. Active-run
tests use real dirty Git and distinct branches at equal local revisions. UI
workload tests use actual coupled computation, source-pinned previews, retained
history, edit/fork and cancellation. Synthetic large resources are explicitly a
reader stimulus, not a substitute for scientific results. Performance limits
are declared before measurements in `P6_CONTRACT.md`; P5's restricted allowance
does not change P6's 250-ms heartbeat gate.

Release qualification executes both saved P6 examples with example factories
forbidden, including ordinary exact probes, explicit restart and empty-store
portable replay. Wheel, native CLI/GUI and extracted-source checks use the same
proof tool. These are required release results, not inferred from unit tests.

## P7 qualification in progress

The adaptive continuum tests use an independent cell-integral Fourier reference
at every scheduled sample. They compare uniform convergence, tolerance
tightening, conservation and total numerical work, including rejected candidates,
indicators and transfers. Real worker, saved-source, portable, host-kill,
publication-failure, dirty-Git, same-revision branch and exact retained-consumer
proofs exercise the existing services. Old P2 recovery cases remain gates.

The cell panel's live stress test runs the real adaptive backend. Synthetic
small/large resource histories are explicitly presentation stimuli. P7 retains
the 250 ms heartbeat and 100/200 ms interaction p95/p99 limits; P5's restricted
allowance is not applied to P7. The 64 MiB incremental presentation measurement
and separate total-host growth are defined in P7_CONTRACT.md.

The ordinary domain/physical workbench and adaptive process/publication cohort
passes 48 cases in `adaptive-normal-route-01`. This is a focused result, not a
new complete-regression count. The source-bound progress map and all failed
native/scientific investigations are retained in `phase-records/p7-20260914`.
Real native state/flux, reconstruction, frozen worker and lifecycle probes belong
to B0 feasibility. They cannot substitute for the independent hybrid statistics
required by P7-02. The full regression and final delivery remain open.

Failed offscreen GUI calls keep their original failed outcome. After that call
report is fixed, `tests/conftest.py` supplies a discard decision only for the
failed test's remaining main windows, so pytest-qt teardown can finish without
an unanswerable unsaved-change dialog. Passing close/save policies are untouched.
A real child-pytest regression requires one intentional failure, one passing
policy test, no teardown errors and a complete JUnit report. This changes failure
reporting, not assertions, deadlines, garbage collection or application behavior.

The native gas UI/retained-history workload now passes28 focused cases in
`gas-ui-stress-02`: heartbeat108.10ms, interaction p95/p99 39.31/56.52ms,
incremental presentation20,008,960bytes, and cooperative cancellation9.143s.
Its previous forced-cancel failure remains available. The host avoids a second
walk of an already fully verified publication closure; each later admission
still checks integrity afresh, including changed/corrupt children.

Exact constant gas observations are recognized from their original values,
without an epsilon that could suppress real fluctuations. The independent
postprocessor, original producer identity and correction S1 are recorded
separately. Earlier producer checkpoints retain their original conservative
method digest; they are not rewritten to impersonate final-source execution.
