# P4 implementation plan: generated CAD and reusable artifacts

Status: **implemented and available Windows gates verified**.
The phase remains P4 only. The final complete suite passes 2,027 tests at
`7d77a32e56aeb3a62c628e184ee3e50510359230`. Native CLI/GUI, wheel, saved CAD and independent-consumer proofs,
P2 recovery, static checks and extracted-source preflight pass. The
[acceptance receipt](receipts/transition-p4.json) records exact results and
limitations; [the acceptance map](P4_ACCEPTANCE_MAP.md) connects P4-01 through
P4-06 to executable proofs. The earlier full-run packaging failure and its
correction remain recorded, and all previous assertions remain unchanged.

Original P3 ZIP/sidecar bytes are recoverable from the recorded Git blobs before
the authorized P4 replacement. Old tests, examples, receipts and review inputs
are retained. Real Windows symlink creation and fresh Linux/macOS/Python 3.12
native qualification are not certified; P5-P8 remain separate work.

The controlling inputs are the exact [P4 handoff](receipts/p4-planning-2026-09-11/contract-CODEX_P4_HANDOFF.md),
the [transition plan](receipts/p3-verification-2026-09-11/contract-TRANSITION_PLAN.md)
sections 3–6, 8.1 and P4, and the original
[P4-01 through P4-06 requirements](receipts/p3-verification-2026-09-11/contract-ACCEPTANCE_TESTS.md).
The [acceptance map](P4_ACCEPTANCE_MAP.md) records executed proofs and the remaining platform limitations.

## 1. Accepted source and preservation boundary

Planning starts at Git commit `9f217e36ffb9442f3e4b46b8d556974b7197c735` on `master`.
The actual application is `code visualizer/`, inside the existing root repository.
The handoff's received filename `programmodel(20260911-215254).zip` identifies the
same bytes as the producer's current `programmodel.zip`:

| Identity | Accepted value |
|---|---|
| Archive SHA-256 | `e85ed66f48af1c5f474d5749429be3bf9ae0c32a971a66e16499a2d2aa4c08d6` |
| Size / entries / manifest payloads | 11,254,905 bytes / 1,326 / 1,325 |
| Source-manifest SHA-256 | `83a69d2447d03ff7fb6c810df1722eee73a7715d37847ce1f1efa1892c45a38f` |
| Delivery source | `880b94fb83aba7f3a9dc86ba3c8c2887c48eb8a3` |
| Implementation and regression source | `6e5306d7a615fbcce81228909b6431b9a459d7f3` |
| Embedded P3 correction receipt SHA-256 | `c22792848b4e2cee4e5df342989190f41a671914c6910f9ee89f35ed3a387f1d` |

The [P3 acceptance map](P3_ACCEPTANCE_MAP.md),
[correction receipt](receipts/transition-p3-affine-correction.json) and
[verification notes](receipts/p3-affine-correction-2026-09-11/README.md) remain the
baseline. Their 1,980 Windows passes and packaging results are historical evidence,
not tests executed by writing this plan. The [planning receipt](receipts/p4-planning-2026-09-11/receipt.json)
records the fresh read-only checks separately.

Preserve P0 name/invocation/package behavior; P1 host lifetime, process isolation,
publication budgets and admission; P2 authoritative freeze binding before admission
and restart reconciliation; and both P3 affine corrections. Preserve all old test
assertions, examples, review inputs, resource bytes and failed/passing receipts.
No automatic checkout, reset, stash, remote operation or user-work cleanup belongs
to P4. The user-authorized current release filename remains `programmodel.zip`;
replace it only at final delivery after exact Git recovery of its predecessor.

## 2. What the implementation supplied at P4 planning entry

Paths in this table are relative to `src/code_visualizer/`.

| Existing seam | Reuse and actual gap |
|---|---|
| `execution/python_backend.py`, `execution/computation_driver.py` | Python prepares `GeneratedProject`, then manages its existing trace child. `code_visualizer.python@1` is explicitly batch-only. Final output is trace/stdout/stderr evidence; authored code has no typed publication capability. |
| `execution/project_files.py`, `execution/debugger.py`, `execution/debug_worker.py` | Real emitted files, normal imports, file-qualified maps and owned child lifetime already exist. Add a publication/input adapter to this child; do not add another Python interpreter around it. |
| `application/computation_process.py`, `computation_jobs.py`, `computation_publications.py` | Other registered backends already transfer resources and acknowledge sealed publications. Reuse their admission, ordering, budget and durable-receipt rules in managed Python. |
| `execution/worker_process.py`, `persistence/resource_transfer.py`, `protocol/resource_transfer.py` | Bounded transport, process-tree ownership and chunked transfers exist. The debug worker currently uses JSON lines on original stdio; native output must not be able to corrupt new publication frames. |
| `domain/resources.py`, `application/resource_admission.py`, `persistence/resource_store.py` | Exact logical-type references, published contract resolution, hashes and immutable bytes exist. There is no BREP/mesh interpretation, geometry decoder or CAD-specific validation. |
| `domain/computation.py`, `generation/computation.py`, `persistence/computation_terminal.py` | Frozen typed requests, declared resource closure, terminal snapshots and origins exist. Named typed Python input/output declarations and their child-facing API are missing. |
| `extensions/foundations/equation_backend.py`, `unit_algebra.py`, `units.py`, `space.py` | The spring solution, quantities, explicit catalog conversions, spaces/axes/frames exist. CAD must consume the solved resource and check its meaning; it must not add an equation solver or reinterpret old unit contracts. |
| `application/git_experiments.py`, `experiment_inputs.py`, `experiment_recovery.py`, `session.py` | Real Git capture/fork, retained attempts and recovery admission exist. New bindings and optional implementation identities must join that closure without changing its ordering. |
| `application/features/domains/handlers.py` | Observation-to-property promotion exists. It does not implement generated-geometry ownership or editing imported geometry. |
| `ui_qt/features/domain_workbench/widget.py`, `ui_qt/git_workbench.py` | Computation/publication lists, semantic selection, deferred edits and retained comparison exist. Add a bounded geometry viewer and explicit artifact-consuming actions here. |

No new project, command bus, scheduler, byte store or universal geometry node
model is required. ProgramModel continues to own authored Python. CAD interpretation
belongs in a first-party extension; presentation remains an adapter.

## 3. Concrete resource and execution decisions

### 3.1 Geometric meaning and its approximation

Use an Open Cascade BREP representation for the first geometric resource. “Exact”
means retained analytic/BREP geometry rather than a display approximation; it does
not mean exact arithmetic or universally deterministic native serialization.

Publish first-party ID/version contracts, provisionally:

| Contract | Purpose |
|---|---|
| `code_visualizer.cad.brep` / `1` | One self-contained geometric resource with BREP bytes and checked interpretation metadata |
| `code_visualizer.cad.triangle_mesh` / `1` | Distinct display geometry derived from a specific geometric resource |
| `code_visualizer.cad.measurement` / `1` | Unit-bearing measurements, method, tolerances and source-resource identity |
| `code_visualizer.cad.region_resolution` / `1` | Resolution of an authored boundary rule against one exact geometry revision |

Register them in `code_visualizer.cad@1` with the exact required foundation bundle
closure. Names are proposed contracts, not an assertion that they are registered
today. No local `brep@1` string, media-type guessing, pickle or arbitrary decoder
import is a portable interpretation contract.

Keep the geometric resource self-contained: a small, closed, versioned header plus
the BREP payload in one sealed file. Define a bounded length-prefixed envelope and
strict member/size validation before committing the codec. This avoids hiding a
mandatory second resource inside opaque bytes that current closure traversal
cannot discover. Mesh arrays similarly live in their own sealed binary resource;
they are not editor nodes or giant event payloads. Register typed parsers at the
extension boundary; do not add CAD fields to generic `DataResource`.

The checked metadata must include representation/serializer/decoder versions,
native library versions, coordinate length unit, frame/space identity and frozen
interpretation, axes/handedness, geometric tolerances, producing parameter and
operation origins, and payload bounds. Mesh metadata adds the exact BREP hash,
tessellator/version, chordal and angular tolerances, indexed-triangle layout and
revision-scoped face groups. Referenced provenance is distinct from data required
to decode a self-contained resource. Any genuinely required external resource
must also be an explicit request input, never an undiscovered header dependency.

P4 supports finite valid solids in a declared right-handed Cartesian 3D frame,
with an explicit length scale. Initially use millimeters at the build123d boundary
and SI quantities in the proof's inputs/results. Resolve meter-to-millimeter through
the existing unit catalog. Reject wrong dimensions, unsupported quantity kinds,
missing conversion paths, nonfinite/nonpositive dimensions and unsupported frames.
Do not infer scale from a filename or a viewer default. An interpretation snapshot
is derived data, not a second editable frame definition.

### 3.2 Named bindings and publication from ordinary Python

Extend the **existing request** with closed typed input/output declarations:
named resource inputs bind an exact `ResourceReference` and expected logical type;
output declarations name the required logical type, required/optional completion
policy, and allowed source origins. Scalar configuration remains in its current
typed value tuple. The existing `resources` tuple remains the derived complete
resource closure, not another editable set of bindings.

Use explicit versioned native/Protobuf adapters for any new request fields. Empty
declarations must preserve historical encodings, digests and replay exactly.
Freeze run configuration through the existing P2 request transaction. A changed
binding on an already-frozen variant changes its closure and therefore requires a
new variant; it cannot be smuggled into the old attempt through an environment
variable or mutable filename. Do not add a parallel experiment document.

An installed Python runtime API exposes named verified inputs and explicit file
publication. Domain adapters convert a build123d object to the checked geometric
file **inside the ordinary authored child**. The host receives typed declarations,
descriptors and chunked bytes, never that Python object's identity. Resolve the
publication call's file/line through existing source spans and validate any
additional parameter/operation IDs against the frozen origin closure. Do not
pretend to infer the lineage of every CAD face from arbitrary Python code.

The generated package and invocation stay the existing emitted representation.
Supply attempt-local input handles/staging and the publication capability as
execution context. Do not expose writable durable-store paths, inject generated
identifiers that shadow author names, or put host-specific paths into saved files.
Persistent and ephemeral package launches use the same adapter. A bare launch
without a required publication context diagnoses that absence; it cannot silently
pretend that publication succeeded. Source-only Run/Trace/Debug keep their existing
behavior, with explicit context needed for artifact-producing execution.

Keep `code_visualizer.python@1` unchanged. Introduce a publication-capable version
of that same Python backend, with explicit streaming/publication capabilities,
selected for new artifact requests. Register it through a separate new contract
contribution depending on the existing programming/computation bundles, so the
old published bundle/definition is not silently redefined. Both versions share
lowering, emitted files, managed child, invocation and result interpretation.
Update exact worker/preparation/managed-strategy registrations together.

Use the existing chunk/admission vocabulary and receipt constructor. Publication
returns only after descriptor/hash/type/origin checks, cumulative 2 MiB metadata
reservation, durable receipt commit and ACK. Missing required outputs prevent a
successful terminal result. Previously sealed publications survive later failure
or cancellation, but are not advertised as a successful producer invocation.
No new protocol is decoded from application `print()` output. Reuse the worker
channel's descriptor isolation for native stdout too; multiplex control and
publication without making cancellation wait behind a blocked ACK or debug pause.

### 3.3 Computation composition and provenance

The first composition is an explicit sequence of ordinary host submissions:

```text
P3 spring definition -> existing equation backend -> sealed solution resource
                                                    |
                           named exact input + selected symbol + unit contract
                                                    v
authored ProgramModel -> existing emitted files -> managed Python/build123d
                                                    |
                                           sealed BREP geometry
                                             /             \
                                  tessellation job       measurement job
                                         |                    |
                                  mesh resource        quantities/evidence
                                         \                    /
                                      retained artifact views
```

A downstream action binds the successful output of a specific attempt/publication,
or an explicitly chosen historical sealed publication. It never reads global
`latest`, a producer's working directory, or a mutable output filename. Dispatch
through `ComputationService`; no task-graph product or second scheduler is needed.
Failure blocks only dependents. Do not rerun a producer to satisfy a missing input.

Mesh/measurement/region requests are small schema-driven CAD domain requests
consuming resources through existing registered backends. They need no ProgramModel
lowering. Register their terminal representations and exact transformation paths
normally. Closed typed payloads, schemas and references replace ad hoc callback
configuration; algorithms live in trusted extension code.

Retain `(source commit, source/input digest, attempt, publication, resource hash)`
through every step. Resource-local face/triangle indices are qualified by the
geometry/mesh hash. Link parameter, Python operation, unit/frame and selected P3
symbol origins through original evidence and the existing origin map. Cross-run
references retain their original source context; they must never become current
activity merely because a semantic ID or local revision matches. Large topology
maps are resource data, not extra evidence observations per triangle.

### 3.4 Boundary selections and explicit ownership

Provide two distinct selections: a transient picked face scoped to one geometry
hash, and an authored CAD `RegionSelection` rule stored in DomainWorkspace through
ordinary commands. Initially support bounded geometric rules such as a planar
end face at the minimum/maximum coordinate along a declared frame axis, with a
normal constraint, tolerance and expected cardinality. Loads/supports in P4 are
authored region assignments; no structural solve is implied.

On regeneration, run the rule against the new exact BREP. Publish its resolution
and qualified face groups. Zero or ambiguous matches, unsupported geometry/frame,
or stale direct picks produce an unresolved-boundary diagnostic and prevent a
dependent boundary assignment from appearing resolved. Do not select the nearest
face opportunistically or reuse face numbering across revisions.

“Edit recipe” changes the original ProgramModel/domain parameter through authority
and P2. “Promote to editable input” instead explicitly creates a new authored
geometry-input identity referencing the exact retained output plus provenance and
an initially empty edit definition. It does not make the CAS bytes writable.
Prove one real independent edit, such as a unit-checked translation of the imported
solid, and a new derived output that does not rerun its old producer. The selected
input binding has exactly one owner: generated-recipe output **or** independent
import/edit definition. It cannot remain automatically driven by both. The old
recipe, run and resource remain historical and inspectable.

Use a typed command on the existing authority for the atomic ownership change,
with revision/source checks. Stage and verify resource retention outside the
handler before accepting the command. Undo/redo restores authored bindings, not
historical bytes or a previous run's journal. Merely copying a ResourceReference
or renaming an artifact is insufficient proof of P4-06.

## 4. Commit-sized implementation sequence

Each checkpoint ends with its focused tests, architecture/dependency tests, updated
design/acceptance evidence and a Git commit. Commit source before expensive final
verification and record any subsequent changes separately.

### A. Lock dependencies and the resource contract

The accepted Windows CPython 3.13.15 environment has Pint 0.26.1, SymPy 1.14.0,
NumPy 2.5.3 and PySide6 6.11.2. It initially had no build123d/OCP. With the user's
explicit installation authorization, a separate `code visualizer/.venv-p4-cad/`
now contains the unchanged development/science pins plus build123d **0.11.1**,
`cadquery-ocp-novtk`/`cadquery-ocp-proxy` **7.9.3.1.1** and SciPy **1.18.1**.
The [full resolved environment lock](receipts/p4-planning-2026-09-11/cad-environment.lock.txt)
and wheel hashes in the adjacent pip report identify that installation. `pip check`
passes; the original `.venv/` was not modified.

In that environment, 123 unchanged focused architecture, affine/scientific-host,
managed-Python and publication cases pass, as do all 16 original affine review
cases. These overlap existing regression cohorts; the full suite and packaging
are still implementation/release gates, not fresh planning claims.

The [release metadata](https://pypi.org/project/build123d/0.11.1/) and
[tagged dependency declarations](https://github.com/gumyr/build123d/blob/v0.11.1/pyproject.toml)
identify `cadquery-ocp-novtk`, NumPy, SciPy and other transitive dependencies.
Do not substitute the wrong OCP package or silently downgrade the accepted
scientific stack. The real three-process [feasibility probe](receipts/p4-planning-2026-09-11/cad-probe/commands.json)
passes: box and perforated-beam export, fresh-process BREP measurement, then
fresh-process tessellation. The measured beam volume is
`9.874336293856409e-6 m^3`; its mesh has 530 vertices and 520 triangles. This proves
local dependency feasibility, not typed publication, Git composition or P4 acceptance.

Carry this environment into implementation. Record OCCT/serializer versions and
licenses and qualify wheel/native packaging; do not assume an imported DLL can
already be redistributed correctly. The dependency probe currently checks bounds,
volume, valid indices and finite vertices, not the complete mesh-error/viewer gate.
The [official I/O API](https://build123d.readthedocs.io/en/stable/import_export.html)
documents BREP round trips and tessellation tolerances; documentation is not a
local capability test. Add the production CAD optional extra and
`requirements-cad.txt` from the verified dependency set, then check the normal
installer and distribution paths. Preserve failed probes. If unavailable, diagnose the
capability and keep ordinary authoring/old computations usable; a fake CAD object
cannot satisfy this gate.

Implement the extension-local typed envelopes, validators, registration and unit/
frame contract. Start with one self-contained solid; assemblies, unrestricted
imports and arbitrary meshing formats remain unsupported. Fix concrete payload,
topology and viewer limits before accepting input; keep metadata within the shared
2 MiB boundary and transfer bulk bytes in bounded chunks.

### B. Add and prove ordinary Python publication before CAD integration

Implement the typed request bindings, SDK adapter, optional backend version and
managed-child event/ACK path described above. Initial tests publish arbitrary
typed binary data without importing CAD. Cover declared inputs, undeclared output,
wrong type, forged origin, duplicate artifact, missing required output, oversize
metadata, partial transfer, receipt failure, cancellation/crash before and after
ACK, native `os.write` output, and producer descendants.

Prove persistent and ephemeral emitted-package parity, module resources, `__file__`,
normal imports and generated-name hygiene. Preserve the v1 Python/backend and old
terminal/resource byte fixtures. A fresh host consumes sealed output after child
and producer-host exit. This checkpoint is required before geometry or viewer work.

### C. Complete the independent CAD consumer slice

Author a native example containing the existing spring relation and real Python
CAD code. Solve `F=10 N`, `k=200 N/m` to `x=0.05 m`. Bind the exact solution
resource and symbol into Python; do not copy its displayed text into a constant.
Explicitly convert to 50 mm and generate a beam with width 20 mm and height 10 mm.
Add a through-hole of radius 2 mm to exercise a curved surface and separate source
operations. Preserve declared quantities and origins in input/evidence.

Publish BREP, let the producer exit, then run two independent consumers: one
tessellates the exact resource, the other imports it and measures bounds/volume
without the producer recipe or cached Python shape. Test both the plain box and
the cut solid. Analytic expectations are 50/20/10 mm bounds and
`0.05*0.02*0.01 - pi*0.002**2*0.01` cubic meters for the perforated beam.

For this small analytic fixture, predeclare measurement acceptance as length
absolute error <= `1e-8 m` and volume error <= `max(1e-12 m^3, 1e-7*expected)`.
These are application test limits, not universal CAD accuracy guarantees. Start
tessellation at chordal deflection `0.05 mm` and angular deflection `0.1 rad`;
record both explicitly. Verify finite vertices, valid indices, orientation and
curved-surface approximation against the exact solid and these settings. Measure
mesh error separately; never certify exact volume from the picture. If the probe
invalidates a limit, explain the numerical evidence before revising the contract.

Reopen after producer/host closure using retained bytes. Replay a portable consumer
plan with producer launch forbidden. Save a distributable native example plus
retained-resource proof, not only an example factory or screenshot.

### D. Add responsive resource views and original-source selection

Add an artifact viewer adapter at the existing workbench composition boundary.
Display the mesh with camera/picking, scale/frame, exact-resource identity,
tessellation settings and historic/current status; keep the BREP independently
inspectable and downloadable. A modest bounded Qt triangle view is sufficient;
PyVista/VTK is not a mandatory dependency for this first proof.

Decode, verify, tessellate and prepare picking/render buffers outside GUI handlers,
using existing host jobs. Pass compact immutable results back to the GUI; release
superseded render preparation and retain the last coherent frame. Picking a
qualified face/triangle resolves available source origins through shared semantic
selection. Graph/table/form and generated code must identify the same source;
unsupported fine-grained lineage is explicit.

Add Qt tests for opening historical results, navigation, panning/selection,
concurrent CPU generation and cancellation. Apply the accepted P1 measured
responsiveness gates; collect timings and bounds instead of relying on sleeps.

### E. Exercise P2 while real CAD runs

Use a real dirty temporary Git repository and the normal controller/session paths.
Wait on an explicit worker-start/checkpoint signal, then accept a source parameter
edit while the old CAD computation is active. Verify exactly one fork; further
accepted edits remain on the child. Solve the child's changed dimension and bind
its exact new result before generating its geometry. The predecessor completes
using its frozen equation result, source files, libraries and request.

Preserve original HEAD/index and unrelated staged/unstaged/untracked work. Cover a
second source-bearing freeze from a managed worktree, changed auxiliary source
carried into the child, equal local revisions on branches, late old events,
identical reruns with new attempts, external edits and failure/restart at admission.
The P2 ready binding remains authoritative even if later status writes fail.

Record exact CAD/SDK/decoder/lock identity in the declared environment/input closure;
do not put package installations or incidental caches into Git inputs. Ambient
Python dependencies remain explicitly non-hermetic. Keep both outputs accessible
after branch switching, host restart and clean inactive worktree removal. New CAD
backends must reject unsupported checkpoint resume without changing existing P2
checkpoint compatibility behavior.

### F. Complete topology, promotion and failure semantics

Implement the bounded authored boundary rules and geometry-input promotion from
section 3.4 through native commands/automation/UI. Prove a rule remaps after a
length edit, a topology edit makes it ambiguous or unresolved, and a direct old
face pick is not silently accepted against the new resource. Resolve rule IDs back
to source and show the diagnostic at the boundary assignment.

Prove independent editing after promotion, source closure retention, producer
non-execution, and undo/redo across the frozen/unrun boundary. Inject retention and
command-admission failures: there is no half-promoted owner or accepted-but-lost
edit. Repeat missing/corrupt/wrong-type/version tests for each consumer and viewer;
the type chooses one registered decoder and never a fallback selected by bytes.

### G. Regression, independent proof and distribution

Run all old and new tests with actual CAD/science dependencies. Preserve and run
the 16-case affine review and all four old external recovery files unchanged.
The handoff mentions additional independent composition checks; that separate
acceptance package was not found with the supplied handoff. Treat their exact
availability and execution as a pending gate, not as replaced by new local tests.

Update wheel/native/archive tooling to include the CAD optional runtime, new
example, portable consumer proof and responsive viewer checks explicitly. Recheck
old examples/proofs and native CLI/GUI recovery. Inspect bundled native dependency
licenses, modules/DLLs and import resources. Build from pinned source; execute the
extracted deliverable, not just the checkout. Run a no-CAD installation control.

Deliver `docs/CAD_RESOURCES.md`, `docs/PYTHON_PUBLICATION.md`, the executed P4
acceptance map, supported/unsupported inputs, dependency lock, origin/tolerance
and retention evidence, `docs/receipts/transition-p4.json`, raw commands/logs and
exact source inventory. Update architecture, decisions, computation/publication,
resource, Git, test-strategy and status docs where behavior actually changed.
Finally publish `programmodel.zip` and matching manifest/verification/checksum
sidecars. P3 evidence remains recoverable at its original commits and hashes.

## 5. Verification policy and platform limits

For each checkpoint run its new focused files plus
`tests/test_architecture_boundaries.py` and `tests/test_dependency_layering.py`.
Use the existing source-bound receipt discipline, fresh short Windows temporary
Git paths, unchanged deadlines and source-before/source-after inventories. Suggested
new proof files and mandatory legacy cohorts are in [P4_ACCEPTANCE_MAP.md](P4_ACCEPTANCE_MAP.md).

At release run `python -m pytest`, lint/format/mypy, generated-protocol checks,
wheel/isolated import, fresh native CLI/GUI, packaged computation/recovery and
extracted-archive verification. Scientific/CAD core acceptance requires real
dependencies; missing-dependency diagnostics form a separate negative cohort.
Report cohort overlap instead of adding repeated cases to the unique suite total.

The unchanged external Windows symlink controls previously stopped at LF/CRLF
fixture assertions. Preserve that failure. Add a separate real Windows link proof
using explicitly written bytes, verify link creation and record Developer Mode/
privilege requirements. A denied link operation is an unverified platform gate,
not a symlink pass. The handoff's successful Linux review is supplied evidence;
fresh Linux/macOS, alternate Python versions, GPU/render drivers and native CAD
byte determinism require their own recorded execution before making claims.

No P5–P8 work is included: no dynamics, FEM, stress certification, coupled solver,
automatic topology identity, general CAD authoring kernel, remote deployment or
security sandbox. Source installation still needs internet; there is no offline
wheelhouse. P4 is complete only when all six original gates and the carried
regression/delivery requirements have executed evidence.
