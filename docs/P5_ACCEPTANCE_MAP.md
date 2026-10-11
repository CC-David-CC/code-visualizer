# P5 acceptance map

Status: **source and packaged gates verified under the restricted-host profile; acceptance open**.
The [P5 contract](receipts/p3-verification-2026-09-11/contract-ACCEPTANCE_TESTS.md)
and [implementation plan](P5_IMPLEMENTATION_PLAN.md) retain all 2,027 P4 baseline
identities and expectations.

The complete run on `6d44a6f` passes **2,122/2,122** in 5,581.52 seconds, with zero
failures, errors or skips: all 2,027 baseline cases plus 95 additions. The original
Git-checkout cleanup case, both new publication-lifetime cases and every P2 recovery
reproduction pass. Source and predecessor archive bytes remain unchanged. The
[analysis](receipts/p5-verification-2026-09-12/full-regression-10-analysis.json) links
raw GUI measurements and the complete case inventory.

The explicit user-authorized restricted profile permits a **350 ms P5 field
heartbeat**; the measured maximum is **122.0 ms**. Interaction p95/p99 are
**33.4/41.2 ms** and memory/cache remain bounded. The normal profile stays at 250 ms;
all other assertions are unchanged. The run uses four of eight logical CPUs
through verified job-wide affinity (50%), with unrelated builds untouched.
This is a restricted-profile qualification; prior failed runs retain their original
verdicts. See [CPU_BUDGET.md](receipts/p5-verification-2026-09-12/CPU_BUDGET.md) and
the [receipt history](receipts/p5-verification-2026-09-12/README.md).

Quality, isolated wheel and native CLI/GUI checks pass. Both native frontends
pass the saved CAD/field proofs, portable replay/restart and unchanged P2 retained
history. Every manifest file is verified, with 317 Python source files and 12
application data files matching each frontend. See the
[structured receipt](receipts/transition-p5.json),
[native result](receipts/p5-verification-2026-09-12/publication-distribution/native-final.json)
and [wheel result](receipts/p5-verification-2026-09-12/publication-distribution/wheel-final.json).

The original external review passes 16 affine and 11 recovery cases, including
all three admission/restart reproductions. Two unchanged LF/CRLF fixture failures
remain; actual symlink privilege, other native platforms and normal-profile timing
are not certified. The adjacent `programmodel.verification.json` binds the exact
delivered ZIP to its extracted-source qualification. P6-P8 are not claimed.

| ID | Required observation | Executable proof | Status |
|---|---|---|---|
| P5-01 | Correct bounded ODE/diffusion computation, independent reference, convergence and dimensions | Saved diffusion intentions through the real host, analytic spatial/temporal study, equivalent-unit and invalid-kind cases, independent field probe and portable replay | Pass: complete source regression, convergence/probe studies and wheel/native execution |
| P5-02 | Field support, units, frames, components/association and physical time are interpreted explicitly | Closed field/index/chunk codecs; normal authoring and source origins; malformed/incompatible interpretation rejected by consumer and viewer | Pass: complete source regression and packaged independent consumers |
| P5-03 | Long histories remain chunked, lazy and responsive; accepted published data stays immutable | Nested closure transfer to a fresh store, bounded slice reads/cache/queues, 16/128 chunk stress with CPU and CAD work, historical hash checks | Pass: bounded memory/cache, independent closure replay and restricted-profile heartbeat 122.0 ms |
| P5-04 | Cancel/resume and host restart validate numerical compatibility and retain honest outcomes | Actual streaming checkpoint, new attempt, fresh-process host recovery and resumed/reference comparison; dirty Git, crash and persistent metadata failures | Pass: dirty Git, killed-host recovery, publication failures, native history and portable numerical restart |
| P5-05 | Accepted and provisional state coexist without mixing; renderer does not control numerical time | Real trial/corrected numerical states, typed preview coalescing, coherent frame admission, late/same-revision branch rejection, display-rate invariance | Pass: complete coherence/clock and desktop stress cases, plus packaged execution |

## Intermediate evidence and corrections

The 50-case numerical/checkpoint/saved-source cohort is in
`receipts/p5-numerical-checkpoint.xml`. The killed-host/reopened numerical restart
passes in `receipts/p5-diffusion-host-crash.xml` (1 case, 191.77 seconds). The dirty
Git field test passes in `receipts/p5-diffusion-git-crash-first.xml`; that cohort's
other case exposed the Windows venv launcher/interpreter PID distinction, corrected
by terminating the verified interpreter while retaining the ordinary process-tree owner.

Persistent bytes, descriptor, receipt and final-report failures passed immediately.
The retained-association case exposed a real ordering defect: an unacknowledged
receipt entered the live ledger and failure evidence. Retained association now
precedes both. `receipts/p5-publication-ordering-corrected.xml` records **67 passes**,
including all five new failure/reopen/resume cases and existing publication and
architecture tests. The initial failed receipt is retained separately.

The first large-history harness retained 128 real 4,190,288-byte chunks; its view
cache stayed below 64 MiB and measured incremental RSS was 3,915,776 bytes. It is
not a passing responsiveness result: the harness built preview bursts in a GUI
callback, bypassing the coalesced observer, and incorrectly treated a valid CAD
runtime selection as a view mutation. Raw failed samples remain in
`receipts/p5-field-stress-first.json`; the corrected harness uses background
admitted-event bursts through the existing `QtRuntimeObserver` and separate
ordinary editor attachments. Thresholds remain unchanged.

The desktop test exposed missing selection of a just-submitted frozen attempt
after editor handoff. The shell now reveals that exact attempt, enabling its
Cancel control and field outputs. Explicit Resume may create a new frozen input
variant because the checkpoint is part of its source closure; the test checks
that draft text and playback create no variant before that explicit operation.
These intermediate runs are not summed into a unique regression total.

The corrected observer-path stress passes in `receipts/p5-field-stress-observer.json`:
12,288 background previews, p95/p99 acknowledgment 27.8/30.3 ms, maximum heartbeat
gap 82.9 ms, incremental RSS 4,734,976 bytes and a cache below 64 MiB. Real CPU
and native CAD work ran concurrently. The uncooperative CPU fixture required the
existing forced-termination path; cancellation acknowledged in 1.12 ms and finished
in 0.552 seconds. `receipts/p5-desktop-controls-final.xml` records 29 passes for
the complete field desktop workflow, the old P2 desktop gate and architecture.
`receipts/p5-retained-convergence.json` records independent spatial/temporal error
and source/resource/evidence identities from sealed worker output. Full regression
and distribution qualification were still outstanding at that checkpoint; the
final results are linked above.

Final-source review reproduced two further admission defects. A missing worker
transfer reached resource lookup before semantic admission, changing the old
ValueError contract into FileNotFoundError. Transfer claims now check every root
and child before lookup, including locally cached children (24 focused passes plus
25 dependency checks). Resume also accepted a prefix with an omitted or unscheduled
sample when its rows remained ordered. It now requires the complete authored
sampling/checkpoint schedule. The corrected 40-case cohort and a distinct-interval,
nonaligned-final-step restart case pass. Original reproductions and corrected
receipts are under `receipts/p5-verification-2026-09-12/`.

The unchanged external review passes 16 affine and 11 recovery cases in the short
review directory, with the two existing LF/CRLF controls still failing. A first run
from a deeply nested output hit Git for Windows' internal GIT_DIR path bound before
the recovery assertions; those logs are preserved. Both actual symlink privilege
probes still report WinError 1314. No test expectation or timeout was changed.

## Numerical and authoring proof

The first complete run on `d19b2d7` recorded 2,097 passes and three failures;
its source inventory and raw samples are retained under
`receipts/p5-verification-2026-09-12/`. One old admission test exposed an omitted
worker transfer being resolved from storage before checking the transfer claim.
Admission now checks that every closure member completed this worker's transfer,
even if its bytes were cached. The unchanged old test and new cached/uncached
cases pass.

Further real-resource checks rejected two previously accepted malformed restart
prefixes: a missing scheduled sample and a substituted unscheduled sample. Restart
now verifies exact union coverage of the sampling and checkpoint schedules. A
distinct-period positive case verifies that the two schedules need not coincide.
Coordinate array units must match the support if explicitly supplied; heterogeneous
sample matrices cannot claim one unit for every column. The shared chunk reader
applies the same rules to slices and restart. The final focused field/restart/
admission/architecture cohort records 58 passes.

The full run also exposed an editor Trace heartbeat pause during generation-2
garbage collection, and one undo-preview timeout. Undo passes unchanged in the
focused rerun. Sparse source-map lookup previously allocated sorting records for
every span in a visited module. It now retains only intervals containing requested
locations, preserving both mapping policies and all events. A 50,000-span allocation
proof reproduces the old >12 MB transient allocation and passes the new 2 MiB bound.
The unchanged editor responsiveness/undo gates and mapping/architecture cohort pass
51 cases; Trace's maximum heartbeat gap was 78.6 ms. No GC setting, timing threshold
or old test expectation was changed for that correction. The final complete
regression above includes these cases.

Executable proofs: `test_diffusion_computation.py`, `test_diffusion_numerics.py`,
`test_diffusion_retained_convergence.py`, `test_field_archive_proof.py` and the
normal `tools/prove_field_history.py` saved-source proof.

1. Create/load ordinary schema-driven field/grid/problem/policy intentions; edit
   through the existing form/authority/SDK. Save/reload and undo/redo preserve IDs.
   The number of authored nodes is independent of stored sample count.
2. Run zero-boundary, sine-initial-data diffusion with L=1 m, D=0.1 m²/s,
   amplitude=10 K interval and final time=1 s. Read published samples, not private
   backend arrays, for the independent comparison. Exact midpoint:
   3.7270783885343794 K interval.
3. Use (nodes,steps)=(33,512),(65,2048),(129,8192). Finest-grid max error <=2e-4 K;
   spatial order [1.9,2.1]. Separately fix 33 nodes and use 512/1024/2048 steps
   against the exact semidiscrete sine solution: temporal order [1.8,2.2].
   Record vector error, endpoint error, residual, norms and actual units.
4. Equivalent mm/ms and interval-unit representations preserve SI results. Wrong
   diffusivity dimension, affine-point amplitude, missing units/frame, invalid
   grid, nonfinite state, unsupported boundary or D*dt/dx²>0.5 fail explicitly.
   An unrelated incomplete model or missing unrelated optional backend stays local.
5. After the producer and host exit, copy only the selected declared resource
   closure to an empty store. Remove access to the producer's files/store. A fresh
   probe returns the selected quantity and source origins without producer replay.
   Repeat through the existing portable plan protocol and from extracted source
   with example-factory imports forbidden.

## Interpretation and resource proof

Executable proofs: `test_field_contracts.py`, `test_field_resources.py`,
`test_field_preview.py` and the unchanged transfer/publication admission tests.

| Boundary | Required cases |
|---|---|
| Versioned interpretation | Exact public type/version and unit closure; unknown/missing interpreter; duplicate registration; space@1/math@1 old goldens and space@2/math@2 new composition |
| Array contract | Shape/dtype/byte-length mismatch, object/pickle arrays, excessive headers, nonfinite data, missing or inconsistent masks, unsupported association/components |
| Spatial contract | Missing support/frame/axis, wrong coordinate unit, changed support hash, wrong frame identity; no automatic placement in the CAD frame |
| Temporal contract | Wrong time dimension, unordered/duplicate samples, gaps/overlap, wrong step/time mapping, mismatched channel times; no silent interpolation or clamping |
| Resource graph | Missing/corrupt/wrong-type child, child rebound under an identity, duplicate children, cycles, excessive depth/count, omitted portable child, unrelated transferred bytes |
| Admission | Failure before/after child transfer, parent seal, receipt write and retained-attempt association; no acknowledgment of an incomplete closure; earlier sealed prefixes survive |
| Receipt granularity | Many transferred child chunks are claimed by a bounded index/root publication; no full-provenance receipt per sample or requirement for one per chunk |
| Laziness | Instrument reads/maps/allocations; selected slices touch only required chunks after admission; no eager materialization of the full collection |
| Bounds | Existing envelope/receipt/request/transfer limits unchanged; over-budget output policy rejected; one observation per field sample prohibited |

Check SHA-256 of every already published chunk/index before and after later
publications, cancellation, resume, editor replacement, copying and inactive
worktree removal. New suffix/index resources can reference old data; old bytes
must not be rewritten.

## Checkpoint, attempt and recovery proof

Executable proofs: `test_diffusion_checkpoints.py`, `test_diffusion_git.py`,
`test_diffusion_host_crash.py` and `test_diffusion_publication_failures.py`, alongside
the unchanged P2 checkpoint and freeze-recovery tests.

1. Request cancellation after a real acknowledged checkpoint; verify cancelled
   outcome and the exact retained accepted prefix. Resume explicitly in a new
   attempt. Compare final values with an uninterrupted run (<=1e-9 K interval),
   identical time/sample coordinates and no duplicated join sample.
2. Terminate the owning host process, not merely an editor widget. Reopen through
   the ordinary session/controller loader. The old attempt is interrupted and
   frozen authoring remains protected. Resume only a fully acknowledged compatible
   checkpoint; never infer success or restartability from a state file alone.
3. Repeat the same selected resume input and a chain of resumes. Assert distinct
   attempts, correct parent publication/attempt IDs, same applicable input commit
   for identical requests, original compatibility basis, and unmodified prefixes.
4. Reject changed parameter, boundary, grid, horizon, numerical method, units/frame,
   library/state-format version, wrong vector length/dtype, nonfinite values,
   inconsistent accepted step/time or publication cursor, provisional state and
   forged/missing/corrupt parent resources. Exercise direct prepared and portable
   requests as well as the Git button; neither bypasses backend state validation.
5. Inject persistent failures at resource bytes/descriptor, prefix/checkpoint
   receipt, attempt-publication association, ready/admission and terminal reporting.
   Also inject host crashes between these boundaries. Earlier acknowledged state
   remains usable; uncertain new state requires recovery and cannot unfreeze edits.
6. With a real dirty Git repository, edit during solve, fork once, continue editing
   the unrun variant, undo/redo, rerun, switch between equal local revisions, reopen
   a retained run and remove only a clean inactive owned worktree. Verify original
   HEAD/index and unrelated staged/unstaged/untracked bytes. Late results do not
   decorate a replacement editor. Retain the original P2 stale-marker and
   post-submission-failure assertions.

## UI, temporal coherence and stress proof

Executable proofs: `test_field_history_qt.py`, `test_field_history_stress.py`,
`test_diffusion_controls_qt.py`, `test_diffusion_display_clock.py` and
`test_field_preview.py`.

- Exercise real Freeze & Run, Cancel, checkpoint selection, Resume and retained
  history controls. Keep an unaccepted form edit and graph navigation usable.
- Display accepted state n alongside the actual predictor for candidate n+1.
  Reject stale/wrong-base/wrong-source trials; a failed trial leaves accepted n
  intact. A frame with channels from different steps/interpretations cannot be
  admitted. Never label a provisional preview as accepted because it was rendered.
- Flood preview updates faster than painting; keep one latest value and bounded
  pending work. Preserve durable publication acknowledgments and terminal events.
  Compare numerical samples with the view closed and at different refresh rates.
- Inspect current and historical sources, including same project/revision numbers
  on different branches. Replace the editor while a slice is decoding and while
  the solver runs; obsolete completions cannot update selection or pixels.
- Stress 16 then 128 roughly 4 MiB chunks, repeated random slices, a real CPU job
  and the P4 CAD view/consumer. Record cache/queue/task sizes, decoded chunk count,
  host/view/worker RSS and raw interaction times. Field cache <=64 MiB; incremental
  field-view working-set growth <=64 MiB after warm-up. One active and one
  replaceable pending slice request; no per-sample evidence or Qt object buildup.
- Preserve reference-machine limits: acknowledgment p95 <=100 ms and p99 <=200 ms,
  attributable heartbeat gap <=250 ms. The explicitly selected, user-authorized
  restricted-host profile permits <=350 ms for this field-heartbeat measurement;
  record the profile and threshold, and do not claim a normal-profile timing pass.
  Cancellation acknowledges promptly and uses
  the existing grace/escalation. Separate numerical, storage, rendering and GUI
  measurements. Preserve failed samples and all other deadlines.

## Regression and release receipt

After each implementation checkpoint run focused cases plus the two architecture
test modules. Final qualification requires the complete existing suite, strict
configured mypy, Ruff check/format, generated protocol and dependency checks.
Keep all 2,027 baseline test identities/expectations and old source examples; do
not sum overlapping focused cohorts into the unique full-suite total.

Run the original external affine and recovery inputs/runner unchanged. The two
Windows LF/CRLF fixture failures and unavailable real-symlink privileges remain
explicit until separately verified. Include P4 CAD/native publication, promotion,
viewer and retained-run proofs, and all P2 recovery regressions.

Use the normal example catalog, wheel, native CLI/GUI and archive verification
paths. Prove real numerical execution, retained restart and the independent field
consumer in each supported distribution; include all old 17 examples and old
foundation/P3/P4 proofs. Missing native/science packages must not break ordinary
authoring or masquerade as a scientific pass.

The P5 receipt contains source/contract hashes, environment lock, real
commands and logs/JUnit, numerical expectations/results, retained resource hashes,
origin assertions, process/recovery evidence, memory/timing samples, packaging
results and limitations. A successful P4 run or planning reference calculation
does not close a P5 row. Submit the exact P5 artifact for acceptance review before
starting P6 or claiming any later phase.
