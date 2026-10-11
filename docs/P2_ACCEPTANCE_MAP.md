# P2 acceptance map

Status: R5/R6 recovery verification passed on the recorded Windows environment.
Previous Windows verification below remains historical evidence. P3 remains separate.
P0/P1 archives, verification receipts, historical evidence and test expectations
are preserved. Corrective regression, packaging and source identity are recorded in
[the corrective receipt](receipts/transition-p2-corrections.json). The original
[P2 receipt](receipts/transition-p2.json) remains historical evidence.

| Case | Automated proof / boundary |
| --- | --- |
| P2-01 | `test_p2_first_freeze_run_in_dirty_real_git`: exact Git tree, retained ref and durable ready attempt checked before the existing host's submit boundary |
| P2-02 | `test_p2_canonical_parameter_edit_forks_once` and `test_p2_first_semantic_edit_forks_once_and_preserves_presentation`: native command applies on a branch from the retained input, previous parameter/input/evidence unchanged |
| P2-03 | First-edit test plus `test_p2_desktop_freeze_and_fork_keep_git_off_gui_and_unaccepted_text_unforked`: many accepted edits, rejected commands, presentation changes and actual unsubmitted signature text |
| P2-04 | `test_p2_old_worker_and_resources_survive_editor_replacement`: supervised worker continues after fork/detach; sealed resource and terminal evidence survive |
| P2-05 | `test_p2_identical_run_has_another_attempt_on_same_commit`: distinct operational IDs, same input commit and content-derived scientific evidence |
| P2-06 | Dirty-repository proof checks original HEAD, physical index and staged/unstaged/untracked bytes; `test_p2_declared_source_executes_captured_bytes_in_normal_python_tree` checks captured auxiliary Python source |
| P2-07 | Parameterized freeze/fork and real write failure tests, missing resources, external ref/index/source changes, `test_p2_failure_after_submission_keeps_real_run_and_recovery_record`, and `test_p2_recovery_never_replays_unfinished_attempts`; native accepted edits remain recoverable if host publication fails |
| P2-08 | `test_p2_same_revision_branches_do_not_share_late_runtime`: same project ID/revision with different definitions and attachments; old terminal activity cannot enter the new runtime |
| P2-09 | Retained-run branch rename/deletion/removal tests; dirty inactive worktree rejection; removal of the worktree that originally discovered the retained repository |
| P2-10 | `test_p2_checkpoint_resume_consumes_sealed_state_and_rejects_parameter_change` and `test_p2_checkpoint_chain_uses_same_binding_through_git_automation`: a real registered portable worker consumes sealed state; changed parameters never reach execution; compatible chains retain their immediate parent |
| P2-11 | `test_p2_undo_redo_preserves_explicit_predecessor_history` and reopened-variant test: anchored native history, ordinary authority operations and preserved frozen inputs |

All core proofs live in `tests/test_git_experiments.py`; the desktop proof lives in
`tests/test_git_experiments_qt.py`. `tests/test_git_experiments_automation.py` proves
existing grants, deferred Protobuf responses, authority/event handoff and real CLI
endpoint reconnection to the experiment worktree. Its worker fixture is registered test composition,
not a new runtime or a persisted extension callback. The existing architecture,
dependency, Git, authority, Protobuf, computation and GUI suites remain in force.

The [transaction contract](GIT_EXPERIMENTS.md) defines closure, semantic ownership,
retained input references, recovery and checkpoint limitations. The
[first-freeze receipt](receipts/p2-first-freeze-2026-09-10.json) preserves the required
ordering: real Freeze & Run passed before automatic fork-before-edit was added.

Platform scope: current measurements are Windows with real local Git and Qt
offscreen. Linux/macOS native behavior has not been verified by these runs.
Filesystem atomic replacement and flushes are not a claim of protection against
every storage-device/power-loss failure. Deleting the repository's common Git
directory or retained resource storage is outside the retention guarantee.

## Historical Windows verification

Complete regression: 1,786 passed in 1300.75s. P2 plus architecture/dependency gate: 65 passed in 438.87s. Ruff, format, mypy and generated Protobuf checks passed. Wheel, native Windows CLI/GUI (including real P2 freeze/fork/reopen), all 17 extracted examples and both independent proofs passed.

Verified source: `dcc83a5a26c9b2a9501fb7c87b3780432f0c1575`. See [the phase receipt](receipts/transition-p2.json) for exact commands, hashes, earlier failed attempts and platform limitations. Final delivery metadata is adjacent to `programmodel-p2.zip`; P0/P1 files remain unchanged.

## Independent review corrections

The four supplied review probes first failed unchanged on Windows. Their original
review pack and prior receipts remain historical evidence. The suite now includes
those probes in `tests/test_git_experiments_review.py`, retaining every assertion.
`tests/test_git_experiments_closure.py` adds the complete lifecycle and persistent
failure cases below. No existing test file or canonical-domain type was changed.

| Review / P2 cases | Additional proof |
| --- | --- |
| R1; P2-05, P2-06 | `test_declared_sources_can_be_refrozen_in_the_managed_worktree`: ordinary owned source, repeated attempt, same commit |
| R2; P2-02, P2-06 | `test_semantic_fork_must_not_silently_revert_declared_source_edits`: child preserves current `VALUE = 88` |
| R3; P2-02, P2-07 | `test_failed_fork_arm_must_not_unfreeze_the_old_editor`: Git-state-read failure after journal acceptance; the next edit remains deferred |
| R4; P2-07 | `test_durable_edit_with_persistent_metadata_failure_must_report_recovery`: accepted journal plus repeatedly unwritable operation metadata |
| P2-02, P2-05, P2-06, P2-09, P2-11 | `test_p2_source_lifecycle_survives_rerun_fork_history_reopen_and_producer_exit`: source-bearing freeze/rerun, staged-versus-working source, native parameter edit, fork, exact CRLF transfer, undo/redo, execution, reload/rerun and retained consumption after host exit |
| P2-07 | `test_p2_source_change_during_fork_is_conflict_or_accepted_recovery`: predecessor/candidate changes before and after journal acceptance |
| P2-07 | `test_p2_persistent_recovery_write_and_notification_failure_preserve_accepted_outcome`: failures before/after publication; polling identities, native recovery, subsequent edit policy |
| P2-07 | `test_p2_failed_freeze_handoff_preserves_the_predecessor_context`: submitted computation survives candidate arming failure while the active frozen context stays intact |
| P2-06 | Source admission tests preserve metadata, path, case and link exclusions in an owned worktree |

The source-bound corrective verification below covers these cases. P3-P8 remain separate.

## Corrective verification

The following section records the previous correction, before the R5/R6 follow-up.

Corrective full regression: 1,800 passed in 1512.20s. P2/Qt/automation/architecture gate: 79 passed in 769.87s. All four original review probes pass unchanged. Ruff, formatting, configured mypy, protocol generation, wheel/native Windows builds, packaged source-bearing rerun/fork, all 17 extracted examples and both independent proofs passed.

Verified implementation: `1c86f680fe05dc6edc36f6b1f203fdaed7a5d113`. The [corrective receipt](receipts/transition-p2-corrections.json) preserves earlier failed attempts, exact commands and platform limits. Final archive verification is in the adjacent `programmodel-p2-corrected.verification.json`. Original P2 and P0/P1 artifacts remain unchanged.

## R5/R6 freeze-recovery coverage

| Gate | Proof |
|---|---|
| P2-01, P2-02, P2-07 / R5 | `test_git_experiments_freeze_review.py`: same-editor post-submit Git-read failure cannot admit the next semantic edit in place |
| P2-02, P2-07, P2-09 / R6 | Same file: persistent marker failure followed by ordinary reopen restores frozen protection |
| P2-07 | `test_failed_same_editor_freeze_cannot_lose_durable_protection`: writes fail before/after durability, ready-phase reporting fails, and host admission fails before/after its durable boundary |
| P2-02, P2-09, P2-11 | `test_persistent_reporting_failure_keeps_same_editor_and_reopened_editor_frozen`: marker/operation/both failures, subsequent fork, undo/redo, retained inspection |
| P2-03, P2-05 | `test_reopen_derives_latest_identical_attempt_and_protects_without_controller`: stale empty/older caches, absent operation report, distinct attempts on identical input, presentation allowed and semantic edits blocked before controller attachment |
| P2-07, P2-09 | `test_uncertain_reopen_refuses_writable_authority_and_releases_lease`: missing ownership/attempt/ref, foreign variant binding, contradictory inputs, unreadable attempt/operation history |

These are 20 new cases, including the two integrated review probes; running the
original probes separately does not create additional independent cases. All
47 focused cases (20 new plus 27 architecture/dependency checks) pass. The 79
legacy P2/Qt/automation/architecture cases, full suite and packaging now pass as recorded below.

## Freeze-recovery verification

P2 freeze-recovery verification: 1,820 tests passed in 2126.73s. The new recovery/architecture gate passed 47 cases; the legacy P2/Qt/automation/architecture gate passed 79. The original four review probes and four Windows-portable follow-up cases pass unchanged. Quality checks, fresh wheel/native CLI/GUI builds, packaged stale-marker restart/fork, all 17 extracted examples and both independent proofs passed.

See [the source-bound recovery receipt](receipts/transition-p2-freeze-recovery.json). Native Linux/macOS and Windows real-symlink controls were unavailable. P3-P8 remain unstarted.
