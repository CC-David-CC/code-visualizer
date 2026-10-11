# P2 authoritative freeze recovery

The R5/R6 follow-up passes the recorded Windows verification. Previous archives
and source-bound receipts remain historical evidence. P3-P8 are outside this
correction. See [the recovery receipt](receipts/transition-p2-freeze-recovery.json).

The declared source/input closure and semantic edit boundary remain those in
[GIT_EXPERIMENTS.md](GIT_EXPERIMENTS.md): the native accepted Project, explicit
auxiliary sources, request, reachable resources and implementation/environment
identity are captured. Presentation changes and unaccepted text do not fork.
The original editing HEAD/index and unrelated files remain untouched.

## Durable authority and transaction

The existing immutable input fields of `RetainedAttempt` establish the association
between an editing variant, an exact Git input commit and its retained run ref.
Creating that durable record freezes the variant, even if host admission later
fails. Its lifecycle phase records execution progress; it never grants permission
to edit the variant again. No extra `was_run` flag or canonical model is needed.

1. Capture and recheck the declared closure; create the real input commit and any
   replacement worktree. Preserve the existing native journal transfer.
2. Retain the per-attempt Git reference. Prepare the editor's immutable context
   and admission gate, including fallible Git reads, before host submission.
3. Durably create the attempt binding, then install its prepared context before
   advancing the operational phase or submitting computation. If the write has
   an uncertain outcome, block the affected editor until reopening reconciles it.
4. Recheck inputs and submit through the existing host-owned computation service.
   Submission failure leaves a frozen or recovery-blocked variant; recovery never
   automatically executes it. An explicit rerun allocates a new attempt.
5. Recheck an unpublished replacement before handing it to the editor. A failed
   handoff preserves the predecessor and the retained run. Variant-marker and
   operation updates report/cache the binding; their failure cannot undo it.

## Reopening

The ordinary ProjectSession loader verifies managed-worktree ownership and
reconciles retained attempts and freeze operations before allowing semantic edits.
A stale empty/older marker cannot override an existing attempt. Identical reruns
may have several attempts for the same input; the most recently created attempt
supplies the context. The attempt ID breaks timestamp ties without changing input
meaning. Lifecycle status, branch labels and local revision alone are insufficient.

Missing/unreadable ownership metadata, missing attempts referenced by a completed
freeze phase, broken retained refs, contradictory input bindings, or a canonical
definition that differs from its frozen binding require explicit recovery. The
loader refuses writable open with a diagnostic naming the conflicting record;
restore that metadata/ref from retained history and reopen. It never invents an
unrun context to make an uncertain state editable. Read-only retained-run
inspection stays separate from editing-variant ownership.

A loaded frozen session also rejects semantic edits before a Git controller is
attached. The controller installs the existing fork admission handler; there is
still one authority and one command/undo pipeline. Reconciliation and Git/resource
work stay in the existing session/host worker paths, outside gesture handlers.

## Proofs required

Keep the four original review probes and all 1,800 existing test assertions.
Add same-editor and replacement freezes, uncertain durable writes, persistent
cache/reporting failures, reopen with stale/missing/conflicting records, direct
session admission, ready/nonterminal recovery without replay, and subsequent
fork/undo/redo. Rerun P2-01 through P2-11, architecture/automation/Qt, complete
regression and packaging. Report platform-specific unavailable controls separately.
