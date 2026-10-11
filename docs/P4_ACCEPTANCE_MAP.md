# P4 acceptance map

Status: **P4-01 through P4-06 accepted by the user on 12 September 2026 within
the recorded Windows scope**. The [acceptance decision](receipts/p4-acceptance-2026-09-12.json)
identifies the unchanged delivered artifact; it does not relabel unverified cases
or constitute a new test run.
Follow [the implementation plan](P4_IMPLEMENTATION_PLAN.md) and the unchanged
[phase contract](receipts/p3-verification-2026-09-11/contract-ACCEPTANCE_TESTS.md).
The following files contain the implemented proofs. The source-bound logs in
`receipts/p4-implementation-2026-09-11/` record actual results, including failed
intermediate gates. The structured P4 receipt records the completed release gates and explicit platform limitations.

| ID | Required executable proof | Implemented coverage / checkpoint |
|---|---|---|
| P4-01 | Authored ProgramModel Python runs its real emitted package; declares a typed output; host seals serialized BREP through structured publication; a fresh consumer works after producer and producer-host exit, with stdout parsing and producer replay forbidden | **Passed.** `test_python_artifact_bindings.py`, `test_python_publication_failures.py`, `test_cad_composition.py`; B/C |
| P4-02 | P3 solved length feeds a box and perforated beam with explicit conversion/frame; distinct mesh resource; independent BREP measurement checks bounds/analytic volume; origins resolve parameters, P3 symbol and authored operations | **Passed.** `test_cad_resources.py`, `test_cad_composition.py`, `test_cad_artifact_ui.py`; A/C/D |
| P4-03 | Real active CAD job survives first accepted edit/fork; predecessor and child inputs/results stay distinct; old geometry survives replacement/restart/worktree removal; same-revision and late-event isolation hold | **Passed.** `test_cad_experiments.py`, `test_cad_artifact_ui.py`; E |
| P4-04 | Authored support/load-region rule remaps against new geometry or reports unresolved/ambiguous boundary; stale direct picks fail; face/triangle IDs always include resource revision/hash | **Passed.** `test_cad_regions.py`, `test_cad_artifact_ui.py`; F |
| P4-05 | Missing/corrupt bytes, wrong logical type/version, unsupported frame, unavailable decoder/backend, failed/cancelled generation and partial publication have explicit outcomes; no implicit producer rerun or decoder fallback | **Passed.** `test_cad_resources.py`, `test_python_publication_failures.py`, `test_cad_composition.py`, `test_cad_artifact_ui.py`; A/B/C/F |
| P4-06 | Explicit promotion creates independent editable geometry input and one accepted owner; real translation edit derives a new output without the producer; recipe edit remains separate; undo/redo and retention/admission failures preserve ownership/history | **Passed.** `test_cad_admission.py`, `test_cad_composition.py`, `test_cad_experiments.py`, `test_cad_artifact_ui.py`; F |

## Final regression and distribution evidence

The final complete suite passes **2,027 tests, zero failures/errors/skips**, in
3637.62 seconds at `7d77a32e56aeb3a62c628e184ee3e50510359230`. All 1,980 old cases remain unchanged; 47
new cases cover CAD resources, consumers, views, promotion, Git history and Python
publication. The 98-case P2 headless/architecture cohort and its Qt case pass.

| Gate | Actual result |
|---|---|
| Configured strict mypy, Ruff check/format, generated protocol, pip check | Passed; 292 typed and 477 formatted files |
| Native Windows CLI/GUI | All five old computation smokes, both CAD compositions and startup passed; full manifest verified |
| Packaged P2 restart/fork | Passed for both executables with original proof assertions |
| Wheel | Build/import and actual saved CAD/fresh-consumer/portable proof passed; all application imports confined to wheel |
| Source archive preflight | 17 old examples, two old proofs, two P3 physical clients, saved CAD proof and portable replays passed |
| Unchanged affine review | 16 passed, including extracted source |
| Original external recovery | 11 passed, 2 unchanged Windows fixture failures before link creation |
| Separate real Windows link probes | File and directory creation unavailable: WinError 1314; ordinary managed-source control passed |

The initial complete run recorded 2,026 passes and one packaging failure. Native
library collection was moved from command construction into explicit release
assembly; the original packaging test then passed unchanged. The complete suite
was repeated on that correction. The native executables and their 290 matching
application source files did not change during this tooling correction.

The independent mesh error proof sampled 756 cylindrical wall-edge points and
measured a maximum chord error of 0.0006216359983703956 mm, below 0.05 mm.
Real preview interaction during a native consumer run recorded 14.35 ms submit
acknowledgment, at most 1.67 ms view acknowledgment, and a 140.15 ms maximum
heartbeat gap under the existing 250 ms bound.

## Executed focused evidence

| Receipt label | Actual result | Scope |
|---|---|---|
| `cad-composition-promotion-regions-fixed` | 35 passed | Actual BREP composition, independent consumers, translation/promotion, region remapping and 27 architecture cases |
| `cad-ui-and-dirty-git` | 32 passed | Four Qt/example cases, real dirty-Git CAD run/edit/rerun/retention, 27 architecture cases |
| `python-publication-failures` | 50 passed | Acknowledged publication retention, failed second admission, cancellation during receipt I/O, typed bindings, UI/resource/architecture regressions |
| `cad-admission-history-fixed` | 34 passed | Promotion rejection and native journal recovery, actor-scoped undo/redo, architecture |
| `cad-consumer-failures` | 38 passed | Missing/corrupt/wrong-type/native-decoder input failures plus architecture |
| `cad-saved-source-proof` | Passed | Saved native source with factory imports forbidden; six independent host steps and four portable consumer replays |
| `cad-depth-ui` | 34 passed | Per-pixel occlusion/picking, cancellation and raster work bounds; Qt artifact inspection and architecture |

These cohorts overlap and must not be added to claim a unique suite count. The
initial fixture/import failures are retained beside the corrected runs. The real
Git proof preserves unrelated staged, unstaged and untracked bytes; forks once
while CAD is active; keeps 50 mm and 60 mm results distinct; removes a clean
inactive worktree; and reopens retained evidence after restart. It also verifies
that the captured implementation identity includes installed CAD versions.

## Proof details that cannot be replaced by a screenshot

- Producer, tessellator and measurement are separate ordinary host attempts. The
  consumer opens the exact saved resource; no producer object or factory survives
  in its process. Reopen and portable replay work without regenerating geometry.
- Spring `10 N / (200 N/m) = 0.05 m` becomes 50 mm by declared unit conversion.
  Box bounds are 50/20/10 mm. The perforated solid's volume is
  `0.05*0.02*0.01 - pi*0.002**2*0.01 m^3`. A changed solved length changes output
  and retains the previous source/resource hashes.
- Predeclared small-fixture tolerances: length <= `1e-8 m` absolute; volume <=
  `max(1e-12 m^3, 1e-7*expected)`; mesh chordal deflection `0.05 mm`, angular
  deflection `0.1 rad`. Measure mesh error separately from BREP measurements.
- Assert exact logical type/version, bytes/hash, frame/unit interpretation,
  producer and consumer provenance, origin resolution and retained resource
  closure. Repeat a frozen input with a distinct attempt; do not require universal
  byte-for-byte native BREP determinism across environments.
- Sealed output survives subsequent producer failure/cancellation. Required
  success-output bindings cannot treat that producer as successful; explicit
  historical sealed-publication consumption remains a separate choice.

## Continuing regression gates

| Boundary | Existing tests/evidence to preserve and rerun |
|---|---|
| Dependency architecture | `test_architecture_boundaries.py`, `test_dependency_layering.py` after every checkpoint |
| Python execution | `test_managed_python_computation.py`, `test_generated_symbol_execution_parity.py`, `test_review_generated_name_hygiene.py`, all invocation, module/package, source-map, debugger and execution tests in the complete suite |
| Host, transfer, admission | `test_computation_publication_process.py`, `test_computation_publications.py`, `test_computation_resource_lifetime.py`, `test_computation_admission_races.py`, `test_resource_admission_phases.py`, `test_resource_contract_admission.py`, `test_worker_resource_inputs.py`, `test_resource_readthrough.py`, resource/chunked-transport and process tests |
| Responsiveness | `test_computation_host_qt.py`, `test_computation_phase_parity_qt.py`, P1 reference measurements plus new real CAD decode/tessellation/render preparation measurements |
| P2 | All `test_git_experiments*.py`, including closure, review, freeze review/recovery, automation and Qt; retain the 98-case headless/architecture baseline and additional Qt case |
| P3 | All physical/equation/unit/rational tests, especially `test_affine_unit_types.py`, `test_affine_equations.py`, `test_affine_computation.py`, real Pint-backed host publication and both physical portable clients |
| Independent inputs | Exact affine file plus four prior recovery files and unchanged runner in `receipts/p3-affine-planning-2026-09-11/input-review/`; additional handoff-mentioned composition files pending supply |
| Historical compatibility | Foundation/domain archive proofs, old native/wire request/backend/terminal bytes, publication/resource contract fixtures, unchanged canonical examples, old retained freeze bindings and checkpoints |
| Distribution | Full suite, ruff, mypy, generated protocol, wheel, native CLI/GUI, native P2 recovery, original 17 examples, old independent proofs, both P3 clients and new CAD example/portable proof from exact extracted archive |

The Windows baseline is 1,980 repository passes, 16 unchanged external affine
passes, and 11 passes/2 fixture failures in the separate 13-case external recovery
cohort. The latter includes all three passing admission/restart tests. Do not
convert those two failures into passes or skips. Add separate real Windows
symlink coverage with explicit bytes and privilege evidence; preserve the originals.
The handoff reports scoped Linux review, not a fresh cross-platform full suite.

## Execution and receipt discipline

Run from `code visualizer/` using the tested interpreter. Set `PYTHONPATH=src`
and `QT_QPA_PLATFORM=offscreen` for the ordinary cohort. External review subprocesses
need both `src` and `tests`, supplied by the unchanged review runner. Use fresh
short scratch paths; do not extend previous deadlines to obtain a pass.

```powershell
python -m pytest tests/test_architecture_boundaries.py tests/test_dependency_layering.py
python -m pytest
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m mypy
python tools/generate_protocol.py --check
```

Add each checkpoint's new focused tests before its architecture gate. Use the
existing `tools/build_release.py`, `tools/build_programmodel_archive.py` and
`tools/verify_programmodel_archive.py` for distribution, extending their real
production proof lists rather than weakening legacy helper assertions. The wheel
baseline uses `pip wheel --no-deps --no-build-isolation --no-index`; dependency
resolution/installation for the optional CAD lock is a separate recorded step.

For every row record source commit/inventory, actual commands, dependency lock,
raw log/JUnit hashes, numerical expectations/results, origin assertions, retained
resource hashes, process lifecycle and failure cases. Separate unique full-suite
counts from overlapping cohorts. Preserve failed runs alongside later passes.
No-CAD controls do not replace actual-CAD acceptance. Platform limitations and
the availability of the additional independent package remain explicit.

Final evidence belongs in `docs/receipts/transition-p4.json` with adjacent detailed
receipts. This map only changes a row to passed after its complete proof executes.
No P5–P8 completion is implied.
