# P3 acceptance map

Status: **P3-R1/P3-R2 corrected; available Windows implementation gates verified**.
The complete suite passes **1,980 cases in 2962.71s** at `6e5306d7a615fbcce81228909b6431b9a459d7f3`,
including all 1,898 unchanged previous cases and 82 added affine tests. The supplied
16-case affine cohort passes unchanged in the focused and extracted-source runs.
The original external recovery cohort is 11 passed/2 failed on Windows: two fixture
line-ending controls cannot reach their real-symlink assertions. All three supplied
admission/restart cases pass unchanged. This explicit platform limit remains open;
it does not justify weakening the tests or claiming a fresh Linux pass.

The correction reuses the existing host, resources, evidence, Git and runtime
projection paths. Four valid affine computations publish/replay typed resources;
two invalid equalities publish durable failed evidence before numerical solving.
Fresh wheel/native CLI/GUI, all five packaged computations, both packaged recovery
proofs, quality gates and extracted example/portable proofs pass. Exact commands,
inventories, limits and failed attempts are in the
[correction receipt](receipts/transition-p3-affine-correction.json) and
[evidence directory](receipts/p3-affine-correction-2026-09-11/README.md).

The original [acceptance specification](receipts/p3-verification-2026-09-11/contract-ACCEPTANCE_TESTS.md)
defines these IDs. Historical results below remain identified as earlier evidence.
`programmodel.zip` is the user-authorized current delivery; superseded artifacts
remain recoverable at the commit recorded in the
[retention inventory](receipts/p3-affine-correction-2026-09-11/release-retention.json).
P4-P8 are not claimed.

| ID | Implemented proof | Executed coverage |
|---|---|---|
| P3-01 | Topology-derived divider 2.5 V; loaded 5/3 V; currents, KCL and origins; independent bridge | `test_dc_equations.py`, `test_physical_experiments.py`, `test_physical_workbench_qt.py` |
| P3-02 | F=k*x gives x=0.05 m; another solve request finds F without changing the relation | `test_equation_compiler.py::test_two_requested_unknowns_share_one_unchanged_relation`, `test_equation_computation.py`, physical portable proof |
| P3-03 | kOhm/mA/mm conversion; voltage on resistance fails during preparation | `test_unit_algebra.py`, `test_dc_equations.py`, `test_equation_compiler.py`, invalid-unit solver-entry guard |
| P3-04 | Corrected symmetric equality, interval residuals and dimension-aware interval scaling | `test_affine_unit_types.py`, `test_affine_equations.py`, `test_affine_computation.py`; all 16 unchanged independent affine cases pass, including extracted source. |
| P3-05 | Mixed V/A variables, column/row scales, rank and condition policy, physical/normalized residuals | `test_equation_compiler.py` scaled/overdetermined/condition cases; DC resource reports |
| P3-06 | Bounded exact rational dimensions including V/sqrt(Hz); integral native/wire bytes unchanged | `test_rational_dimensions.py`, `test_unit_algebra.py`; unchanged foundation archive and R5/R6 recovery tests |
| P3-07 | Only declared catalog conversions authorize Pint; exact public closure, released units immutable | `test_unit_algebra.py`; unchanged unit/publication tests; exact schema-version installation regression |
| P3-08 | Inconsistent/singular/underdetermined distinguished; nonlinear/DAE/ill-conditioned diagnosed | `test_equation_compiler.py`; finite/residual checks in the shared numerical operation |
| P3-09 | math@1 indexed evaluation unchanged; math@2 solve request has its own backend contract | unchanged `test_foundation_archive_proof.py`; version/unknown-change tests; native and Protobuf plan replay |
| P3-10 | No implicit cyclic/angular/logarithmic arithmetic, no executable author text | `test_equation_compiler.py` kind and malicious-operator cases; `test_unit_algebra.py` |

Historical original-P3 checkpoint receipts: [dimensions](receipts/p3-dimensions-2026-09-11/),
[units](receipts/p3-units-2026-09-11/), [equations](receipts/p3-equations-2026-09-11/),
[DC](receipts/p3-dc-2026-09-11/), [workbench](receipts/p3-workbench-2026-09-11/).
The workbench cohort passed 60 tests in 142.51 seconds, including real dirty Git,
Qt dialogs, retained comparison, restart/worktree removal and architecture checks.
A separate 32-case gate includes missing Pint/SymPy/NumPy diagnostics plus unchanged
architecture checks. The configured typing gate covers 278 files; lint, formatting
and generated protocol checks pass. These overlapping cohorts are not an additive
full-suite count. Windows CPython 3.13.15 is the measured platform.

The first complete run passed 1,897 tests and failed one legacy release-helper
fixture (2,798.55 seconds). The helper now receives new physical smoke cases
explicitly from the production release operation; the original eight helper
assertions remain unchanged. That corrected gate plus architecture passes all
35 cases. The same production operation ran all five computations successfully
in the built executables. Wheel build/isolated import, native CLI/GUI, both
packaged stale-marker restart/fork proofs, lint/format/types/wire checks pass.
The failed run, its JUnit and source inventory remain in
[verification receipts](receipts/p3-verification-2026-09-11/). The final full rerun
passes 1,898 cases in 2400.96 seconds at commit
`0a8dd459c44d37e912d717159341f71639ba7e18`, with no source changes during execution.
Its [structured receipt](receipts/transition-p3.json) identifies the source, raw log,
JUnit, cohort counts, numerical tolerances and platform. No failed receipt is
replaced by a later pass. The source archive preflight also passes: 1,203 entries,
all 17 original projects, both historical independent proofs, both physical clients,
typed resource checks and identical portable evidence after producer exit.

## Cross-cutting P0/P1/P2 gates

| Boundary | Required regression/proof |
|---|---|
| One authority | Graph/table/form edit stable canonical IDs; same undo/redo; solver output never modifies definitions. |
| P0 programming | Existing generated-name, invocation, package execution, Trace/Debug, example and independent authoring tests stay unchanged. |
| P1 host lifecycle | Existing computation, process/publication/resource and Qt responsiveness tests; equation preparation/execution use the same host-owned service. Jobs and sealed outputs survive editor replacement. |
| P2 input closure | Real dirty Git HEAD/index/unrelated-work preservation; auxiliary-source rerun/fork regressions unchanged; new request and relevant unit/environment contracts included explicitly. |
| P2 admission/restart | Existing 98-case headless cohort, the Qt case, original R1-R6 probes and three new independent review tests described below. Durable ready/admitted attempt binding never grants in-place semantic editing after failure or reload. |
| Historical migration | Old frozen inputs, old indexed-evaluation resources and their hashes stay valid. Migration never silently clears frozen context, replaces an attempt digest or replays a computation. |
| Run identity and comparison | Real UI compares two retained attempts by commit and semantic origins; same-revision branches remain isolated; unchanged rerun gets a new attempt on the same eligible input. |
| Retention and checkpoints | Old runs/resources reopen after host exit, branch switching and clean inactive worktree removal. Existing checkpoint compatibility checks retain their assertions. |
| Portable contracts | Exact bundle closure, separate global ID/version, rational dimension codecs, bounded metadata, typed resource descriptors, existing chunked transport, missing optional implementation diagnostics. |
| Packaging | Full existing suite plus P3; formatting/lint/types/generated wire code; wheel and isolated import; native CLI/GUI; extracted 17 old examples plus two new clients and old/new independent proofs. |

The three additional tests required by the handoff are now available in the
unchanged [review file](receipts/p3-affine-planning-2026-09-11/input-review/prior-tests/test_review_recovery_admission.py):

1. Verify freeze protection at the actual host-admission boundary.
2. Persist a ready/unadmitted binding across host restart, then explicitly retry.
3. Recover stale reporting in an entirely separate interpreter.

All three pass unchanged in both the planning and corrected Windows runs. Their
source SHA-256 is `14804924ab1fab60d48243cb2bc50b2673f2f755755c0345166399c19272eafb`.
The corrected 13-case prior cohort is **11 passed, 2 failed**, with no skips or
modified assertions. Both failures are literal LF byte assertions in Windows
fixtures that write CRLF, before the real-symlink operations. Those operations and
fresh Linux/macOS execution remain unverified here. The earlier two 30-second
deadline cases pass unchanged at baseline and corrected source using short Git
scratch paths; the original limits remain. Historical failures are retained.

See the [corrective receipt](receipts/transition-p3-affine-correction.json) and
[evidence](receipts/p3-affine-correction-2026-09-11/README.md). The review's 13-pass
Linux result remains supplied historical evidence, not a new local execution claim.

## Repeatable gate commands

Run from `code visualizer/`, with the intended environment activated and
`PYTHONPATH=src`, `QT_QPA_PLATFORM=offscreen`. Scientific package pins are in `requirements-science.txt`: Pint 0.26.1,
SymPy 1.14.0 and NumPy 2.5.3, with pinned transitive requirements. Use a fresh, workspace-local pytest temporary root
and log directory for each recorded execution.

The existing headless P2/architecture cohort is:

```powershell
python -m pytest `
  tests/test_git_experiments.py `
  tests/test_git_experiments_closure.py `
  tests/test_git_experiments_review.py `
  tests/test_git_experiments_freeze_review.py `
  tests/test_git_experiments_freeze_recovery.py `
  tests/test_git_experiments_automation.py `
  tests/test_architecture_boundaries.py `
  tests/test_dependency_layering.py
```

These 98 cases passed unchanged inside the 1,980-case corrective regression. Run the existing
`tests/test_git_experiments_qt.py` as well. Its case and architecture cases overlap
other recorded cohorts; report unique counts and cohort purposes separately.

For every implementation checkpoint, run its focused tests and:

```powershell
python -m pytest tests/test_architecture_boundaries.py tests/test_dependency_layering.py
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m mypy
python tools/generate_protocol.py --check
```

Before release, run `python -m pytest` and the repository's wheel, native and archive
verification tools. The user now authorizes `programmodel.zip` as the current
delivery and cleanup of older release copies after exact Git recovery is verified.
The executed results are recorded above and in the linked receipts; this command
list alone is not evidence of a pass on another machine.

## Evidence required to mark any row passed

Record exact source commit and file inventory, command/environment lock, exit code,
raw log hash, numerical expectations/tolerances, source-origin assertions and
failure cases. Preserve earlier failed receipts. Attach process/Qt measurements
only for tests actually run; record platform and symlink limitations explicitly.
The final P3 archive and sidecar must identify the verified source and include this
map with executed proof names/results. P4-P8 are not part of P3 acceptance.
