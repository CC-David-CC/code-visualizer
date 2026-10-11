# P1 acceptance map

**Status: P1 accepted on the recorded Windows reference environment.** Final source: `d5b0b98d2920fd23d630d4f57d26ca1485bd39ff`.
See [phase receipt](receipts/transition-p1.json) and
[corrected reference timing](receipts/p1-windows-offscreen-2026-09-10/manifest.json) for gate results.
This maps `intentional_workbench_transition_20260910/ACCEPTANCE_TESTS.md`, P1-01
through P1-09, to the repository tests. A test reference identifies its proof
scope, not a recorded pass. The final receipt must identify the tested source,
environment, commands, raw measurements, failures and platform limitations.
Accepted P0 remains recorded separately in
[transition-p0.json](receipts/transition-p0.json).

## P1-01 — Responsive CPU work and large-input preparation

- [test_editor_preparation_qt.py](../tests/test_editor_preparation_qt.py)::
  `test_real_run_and_trace_buttons_prepare_without_blocking_gui` exercises actual
  Run/Trace controls with a large canonical Python project and fixed preparation
  worker, retaining source identity and emitted artifacts.
- [test_computation_host_qt.py](../tests/test_computation_host_qt.py)::
  `test_real_run_button_keeps_large_resource_admission_off_gui` checks actual
  input-byte/hash results while recording GUI heartbeat and acknowledgment.
- The same file's
  `test_cancel_button_acknowledges_uncooperative_cpu_worker_without_freezing`
  records repeated edit-gesture latency while a real CPU worker runs.

The final preparation boundary is also covered by
[test_preparation_import_boundaries.py](../tests/test_preparation_import_boundaries.py)::
`test_real_editor_preparation_does_not_load_rendering_or_qt` and
[test_editor_preparation.py](../tests/test_editor_preparation.py)::
`test_prepared_snapshot_wakes_an_already_waiting_observer`. Existing agent-edit
and search/undo preview deadlines remain unchanged. Dependency/import probes
are diagnostics, not a timing or whole-suite acceptance receipt.

These are complementary scenarios; they are not one simultaneous large-input,
CPU-worker and every-navigation-gesture stress test. The measured UI gates are
acknowledgment at most 200 ms and heartbeat gaps at most 250 ms. The CPU interaction
scenario additionally checks nearest-rank p95/p99 limits of 100/200 ms.

## P1-02 — Keep the running model's authoring surfaces usable

- [test_computation_host_qt.py](../tests/test_computation_host_qt.py)::
  `test_runtime_bursts_preserve_open_form_table_tree_and_authoring_selection`
  retains widget identities, uncommitted text, canonical state and authoring
  selection while runtime graph decoration changes.
- `test_real_run_button_keeps_progress_bounded_and_preserves_open_editor` retains
  the actual open property editor during a real worker's progress stream.
- `test_editor_replacement_retains_running_attempt_and_sealed_publication` replaces
  the editing attachment, navigates historical attempt/publication rows and preserves
  the running attempt independently of its former kernel.
- `test_graph_pan_and_uncommitted_form_survive_running_worker_and_terminal_update`
  pans the graph during an active CPU worker, then checks retained viewport position,
  scene item identity and uncommitted form text after cancellation and terminal delivery.

The present proof uses existing model/notation surfaces, not a new canonical group
type.

## P1-03 — Bound bursts without losing sealed results

- [test_worker_process.py](../tests/test_worker_process.py)::
  `test_slow_consumer_has_bounded_queue_and_cancellation_still_completes` saturates
  the byte queue while preserving cancellation delivery.
- [test_computation_host_qt.py](../tests/test_computation_host_qt.py)::
  `test_real_run_button_keeps_progress_bounded_and_preserves_open_editor` checks
  notification coalescing, bounded runtime history and terminal evidence.
- [test_editor_preparation.py](../tests/test_editor_preparation.py)::
  `test_preview_mailbox_coalesces_pending_requests_and_rejects_obsolete_completion`
  proves latest-request preview delivery.
- [test_editor_preparation_qt.py](../tests/test_editor_preparation_qt.py)::
  `test_trace_preview_is_bounded_but_every_event_and_full_selected_details_remain`
  distinguishes a bounded console preview from retained trace detail and
  reconstructs complete stdout/stderr through bounded selectable pages.
- [test_workbench_trace_delivery_qt.py](../tests/test_workbench_trace_delivery_qt.py)::
  `test_domain_trace_batches_retain_origins_and_detach_discards_pending_delivery`
  applies the same full-output access and origin/detach proofs to the generic
  workbench. Output pages abbreviate presentation size, not the captured data.
- [test_computation_publications.py](../tests/test_computation_publications.py)::
  `test_cumulative_receipt_budget_rejects_before_commit` checks that receipt limits
  fail before durable publication. P1-08 covers receipt retention and consumption.

[test_runtime_snapshot_sharing.py](../tests/test_runtime_snapshot_sharing.py)
checks exact immutable binding reuse, every field change, prior snapshots and
reset/session separation. Reuse changes allocations, not recorded history.

Progress/preview notifications may coalesce. Sealed receipts remain individually
addressable; notification frequency is not the count of scientific publications.

## P1-04 — Cooperative and forced cancellation

- [test_computation_publication_process.py](../tests/test_computation_publication_process.py)::
  `test_consumer_uses_sealed_output_while_producer_is_active_and_after_cancel`
  checks cooperative cancellation without a false forced-termination flag.
- `test_uncooperative_cpu_worker_is_force_terminated_without_successful_evidence`
  checks the uncooperative outcome and explicit force diagnostic.
- [test_worker_process.py](../tests/test_worker_process.py)::
  `test_uncooperative_worker_and_its_descendant_are_cancelled`,
  `test_acknowledged_cancel_finishes_without_false_forced_termination` and
  `test_terminal_verification_has_a_deadline_without_a_cancel_request` cover process
  ownership, grace acknowledgment and bounded terminal verification.
- [test_computation_admission_races.py](../tests/test_computation_admission_races.py)::
  `test_cancel_after_real_python_preparation_before_managed_installation_skips_entrypoint`
  and
  `test_cancel_rejects_finalization_and_close_drains_real_worker_before_success_commit`
  cover the preparation/installation and final-admission boundaries.
- [test_editor_preparation_qt.py](../tests/test_editor_preparation_qt.py)::
  `test_stop_during_preparation_reports_cancellation_and_cannot_start_execution`
  covers immediate Stop feedback during Run/Trace/Debug preparation and proves
  that a late prepared artifact starts no child. Running-child Stop retains
  its separate execution proof in `test_main_window_qt.py`.
- The actual cancel-button latency proof is listed under P1-01.

## P1-05 — Crash isolation and prior publication retention

[test_computation_publication_process.py](../tests/test_computation_publication_process.py)::
`test_native_crash_does_not_terminate_other_producer_or_retract_its_publication`
runs an unrelated producer during a real process crash.
`test_producer_crash_after_publication_ack_preserves_consumable_receipt` crashes the
producer itself after sealing and then consumes the retained resource. These check
failure classification and durability independently of GUI rendering. The editor
attachment/retention proof is listed under P1-02.

## P1-06 — Pin work across author edits

- [test_editor_preparation_qt.py](../tests/test_editor_preparation_qt.py)::
  `test_author_edit_cancels_pending_run_and_only_current_preview_can_arrive` edits
  during actual preparation and rejects the obsolete execution request.
- [test_computation_host_qt.py](../tests/test_computation_host_qt.py)::
  `test_runtime_bursts_preserve_open_form_table_tree_and_authoring_selection` removes
  active decoration after an accepted revision change while retaining old runtime
  revision; `test_editor_replacement_retains_running_attempt_and_sealed_publication`
  labels a former attachment's retained output historical, even at the same revision.
- [test_computation_backends.py](../tests/test_computation_backends.py)::
  `test_evidence_retains_old_revision_through_edit_undo_redo` preserves ordinary
  authority/history behavior under explicit local test composition.
- [test_computation_admission_races.py](../tests/test_computation_admission_races.py)::
  `test_authority_edit_during_real_final_admission_retains_historical_source_and_evidence`
  gates real worker evidence admission, commits a canonical edit, and verifies that
  the successful result retains its original source/input digests and revision.
  Historical output remains inspectable without highlighting the edited source or
  changing its current selection.

These cover preparation, final admission, retained results and attachment replacement.
Cancellation during final admission is covered separately by P1-04.
Source hashing remains conservatively whole-project; it is not minimal dependency
hashing or the later Git experiment identity model.

## P1-07 — Scoped executable completeness

[test_computation_scope.py](../tests/test_computation_scope.py)::
`test_unrelated_incomplete_model_and_missing_bundle_do_not_block_requested_root`,
`test_incomplete_referenced_model_is_an_actual_dependency` and
`test_unrelated_structural_corruption_still_blocks` distinguish irrelevant
incompleteness, an actual required dependency and global integrity failures.
[test_computation_backends.py](../tests/test_computation_backends.py)::
`test_non_python_admission_does_not_require_valid_python` retains domain independence.
These scoped-planning tests use explicit local definitions; they do not claim an
arbitrary unavailable third-party solver was executed.

## P1-08 — Consume a publication before and after producer exit

- [test_computation_publication_process.py](../tests/test_computation_publication_process.py)::
  `test_consumer_uses_sealed_output_while_producer_is_active_and_after_cancel` consumes
  exact typed bytes while their producer is active, then checks cancellation retention.
- `test_new_host_consumes_typed_publication_after_producer_process_and_host_exit`
  reopens the receipt through a new host and consumes its exact resource reference.
- [test_computation_publications.py](../tests/test_computation_publications.py)::
  `test_publication_is_durable_before_return_and_scientific_identity_ignores_clock`,
  `test_invalid_publication_never_gets_a_durable_receipt` and
  `test_publication_only_recovery_copies_complete_resource_closure` cover admission
  order, rejection and recovery without final evidence.
- [test_computation_resource_lifetime.py](../tests/test_computation_resource_lifetime.py)
  covers success/cancel/crash scientific closure after scratch cleanup, managed
  Python transport exclusion and editor-preview lifetime.
- [test_foundation_archive_proof.py](../tests/test_foundation_archive_proof.py)::
  `test_extracted_foundation_proof_matches_and_rejects_changed_binary_plan`
  preserves the exact historical resources/evidence and rejects modified plans.

[test_computation_store_admission.py](../tests/test_computation_store_admission.py)
rejects durable evidence without a ResourceStore before attempt creation,
for production and explicit in-process submit/wait paths. Ephemeral execution
remains supported; existing resource-only/full-store proofs retain their scope.

## P1-09 — Shared GUI submit and headless wait semantics

[test_computation_phase_parity_qt.py](../tests/test_computation_phase_parity_qt.py)::
`test_gui_run_and_headless_wait_produce_identical_evidence_for_exact_resource_input`
uses the actual workbench Run button and then a fresh headless host/store for the
same canonical matrix domain and typed input resource. It compares submitted
requests, prepared plans, source/input digests, exact numerical values, origins,
output bytes and immutable evidence identities. The backend is the registered
first-party math implementation; no numerical executor is mocked. This new proof
has passed its focused check; the [final receipt](receipts/transition-p1.json) records
the source-pinned integration gate separately from the GUI timing samples.

[test_process_computation_service.py](../tests/test_process_computation_service.py)::
`test_static_backend_runs_after_supervised_preparation` exercises headless execution;
the real GUI worker paths are listed under P1-01/P1-03. In
`application.computation`, `execute_computation` calls `start_computation` and waits
on that same host; the GUI calls `start_computation` and observes the attempt.
[test_backend_lifecycle.py](../tests/test_backend_lifecycle.py)::
`test_synchronous_wrapper_consumes_stream_and_preserves_deterministic_evidence`
provides direct same-input parity under explicit local callback composition.

The lower-level callback-composition test is supplementary; it does not replace
the real GUI/headless paired proof above.

## Reproduce the mapped checks

Run from the promoted repository root after its documented dependency install:

```powershell
$env:PYTHONPATH = 'src'
$env:MYPYPATH = 'src'
$env:QT_QPA_PLATFORM = 'offscreen'
$p1Python = '.venv/Scripts/python.exe'
& $p1Python -m pytest -q tests/test_computation_scope.py tests/test_worker_process.py tests/test_computation_publications.py tests/test_computation_publication_process.py tests/test_computation_admission_races.py tests/test_process_computation_service.py tests/test_editor_preparation.py tests/test_backend_lifecycle.py --basetemp=.test-p1-map-correctness -p no:cacheprovider
```

After that process exits and all children are reaped, run the UI group alone:

```powershell
& $p1Python -m pytest -q tests/test_editor_preparation_qt.py tests/test_computation_host_qt.py tests/test_computation_phase_parity_qt.py --basetemp=.test-p1-map-ui -p no:cacheprovider
```

For an extracted source folder, first create its local environment using the
documented installation steps. Preserve the
per-test JSON receipts and sample files under the chosen `--basetemp`, along with
the source commit/diff, exact command and Python/Qt/platform versions. Do not run
parallel pytest workers, other process suites, builds, type checkers, profilers or
benchmarks during timing capture. The complete legacy suite remains a separate
required gate; these commands are focused reproductions, not a replacement.

Latency and throughput are distinct. The large source Run/Trace proof records total
completion time and uses a 120-second liveness watchdog; it does not assert a
30-second end-to-end throughput target. Its 200 ms acknowledgment and 250 ms
heartbeat limits remain explicit. A fast acknowledgment alone cannot prove completion,
and eventual completion alone cannot prove responsive editing.

Linux/macOS native execution is unverified on this Windows host. Platform-specific
skips must be reported explicitly, not counted as cross-platform proof. This map
claims no P2–P8 completion, P4 authored-Python typed model/CAD publication interface,
handwritten CAD backend or new numerical domain. The generic resource fixture proves
the lifecycle boundary; it is not scientific solver validation.
