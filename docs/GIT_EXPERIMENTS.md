# P2: Git experiment inputs and editing transactions

Status: R5/R6 recovery verification passed on the recorded Windows environment.
Earlier corrective Windows verification remains historical evidence. P3 remains separate.
P0/P1 archives and receipts remain the accepted Windows baseline. This document specifies P2 only;
the separate transition plan and P2-01 through P2-11 are the acceptance contract.

## Ownership and exact input closure

The editable `Project` continues to belong to its existing `ProjectAuthority`.
Git stores historical inputs; it is not another editable model. A run consumes an
immutable snapshot through the existing host-owned `ComputationService`. Replacing
an editor detaches its runtime attachment, not the computation or its storage.

An explicit Freeze & Run declaration contains:

* The complete native serialization of the accepted project snapshot, including
  its local revision and presentation policy for later inspection.
* The normalized existing `ComputationRequest`: selected root, exact backend
  identity/version, configuration, seed, and explicit resource references.
* Resource references reachable from that snapshot and request, their exact
  descriptors, and verified content hashes. This is intentionally conservative:
  the whole authored snapshot is retained, not a claim of minimal root closure.
  Resource bytes are imported into retained content-addressed storage, never Git.
* An explicit list of additional repository-relative UTF-8 source files and their
  execution-relative destinations. Empty is a valid declaration. No directory
  scanning, index capture, implicit imports, symlinks, or path escapes. Binary or
  large data must be declared as resources. Inputs cannot replace emitted files.
* A small versioned manifest recording those files, hashes, resource descriptors,
  request, installed application/Python/platform identity and registered contract
  versions. Lock files can be selected explicitly as source inputs.

The input tree starts from an **empty private Git index**. Its only entries are
native `project.json`, the input manifest, and the selected files. Parent ancestry
does not add files to this tree. The original HEAD, raw index, worktree files and
unrelated staged/unstaged/untracked content are never changed. Selected bytes and
expected Git state are checked again before publication. External changes reject
the operation; they are not silently included or stashed.

Source ownership is relative to the approved editing worktree. A managed linked
worktree can live beneath the common Git directory; that ancestry does not turn
its ordinary files into metadata. Actual Git metadata inside the editing tree,
native recovery directories (including case variants), links and path escapes
remain excluded. The existing count, size and destination restrictions still apply.

Execution uses the captured bytes and verified retained resources. Python still
executes its single emitted package tree; declared auxiliary source files are
materialized at that same boundary. No live authoring directory is an execution
source. Ambient imports, undeclared filesystem/network access, hardware and native
libraries are not made hermetic by Git. P2 records this limitation and does not
claim cacheability or bitwise reproducibility from a commit and seed alone.

## Identity, retention and recovery

An experiment variant is a real local Git branch with an owned linked worktree.
An attempt has a separate opaque operational identity. Its retained ref is
`refs/code-visualizer/runs/<attempt-id>`; this points to its input commit and is
independent of the human branch name. Repeating identical frozen input reuses that
commit and allocates another attempt. Scientific evidence keeps its existing
content-derived identity and encoding; attempt timestamps and Git labels do not
enter historical evidence hashes.

Freeze does not move an existing editing HEAD or rewrite its index, including an
owned worktree's index. Its branch tip is the editing base; the run reference is
the authoritative input commit. The next fork starts at that retained input,
even when it is newer than the editing branch tip. Ordinary explicit Git commits
remain available for reviewing authoring changes. This avoids silently consuming
staged work in an experiment worktree as well as in the original repository.

The repository's common Git directory owns the experiment retention directory.
It contains operational manifests, attempt records, resource/evidence stores and
owned worktree registrations. It survives removal of an inactive linked worktree.
Deleting the repository or its retained storage is outside this retention promise.
Recovery and inspection do not automatically restart a possibly executed attempt.
Ordinary Git pushes do not include these local retention refs or resource bytes.
Backup must include the common Git directory and its retained resource storage.

Freeze is a recoverable sequence, not a fictional transaction spanning Git and
the filesystem:

1. Capture the immutable authority snapshot and expected repository state; record
   a planned operation with an allocated attempt/variant identity.
2. Validate the closure, verify/import resource bytes and write the exact small
   input manifest. Record retained inputs.
3. Create the input tree/commit with the private index. Record the commit before
   publishing references.
4. Compare expected state; create/update only owned refs using expected old OIDs;
   establish the owned editing worktree through ordinary Git/session loading.
5. Retain the immutable per-attempt ref and prepare the immutable editor context.
   Durably record the ready attempt's variant/input binding and install its
   admission protection before any execution submission. An uncertain attempt
   write blocks the affected editor until reopening reconciles the durable state.
6. Admit that attempt into the existing computation service. Persist lifecycle
   boundaries before backend execution and retain terminal evidence/publications.
   Subsequent editor handoff and marker/reporting writes cannot undo the freeze.

Ready attempts already freeze their owning variants; interrupted or failed
admission never resets them to unrun. On load, retained attempts and freeze
operations determine admission policy. Variant markers are ownership locators and
status caches. Stale markers cannot override durable bindings; missing or
contradictory records require recovery. See [freeze recovery](GIT_FREEZE_RECOVERY.md).

Every boundary has a durable recovery record. Failures before admission never
execute. Failures after admission never pretend the run did not start. A restart
marks nonterminal orphan attempts interrupted; it does not replay them. Recovery
reports the durable boundary and can open retained inputs for inspection;
retrying computation is an explicit new attempt. Referenced objects/resources are
retained on partial failure. Cleanup only removes registered, clean, inactive
worktrees using Git, without force; it never removes user worktrees or run refs.

## Semantic edit boundary

The boundary is the **validated candidate of the existing authority command**,
including transactions and undo/redo. Invalid text and rejected commands have no
candidate to publish. Definition comparison includes the canonical ProgramModel,
domain schemas/instances, executable language definitions and validators,
extension references, authored semantic relationships, and runtime settings.
Changes to run configuration, seed or declared input files also change input.

Document geometry, DRAKON view policy, lens definitions, notation presentation,
assets, panels/camera and project display metadata are presentation state. They
remain authored and persisted, but do not alone create an experiment branch.
This distinction compares typed canonical components, never rendered-view diffs
or a list of widget gestures. Unknown semantic extension contents are treated
conservatively as definition state.

The first accepted definition change to a frozen variant prepares one uniquely
named branch/worktree from the exact frozen input. The ordinary session loader
validates it. Current presentation and the explicitly anchored local undo history
are carried into that editing context. The same authority operation is then
durably applied. Only then is the replacement editor published. Further accepted
edits stay on that unrun variant. No branch is allocated per keystroke.

Fork preparation reads the source declarations from the retained input manifest
and captures their **current working-file bytes** from the predecessor. It copies
only those declared files into the new worktree, preserving exact line endings.
The frozen commit supplies ancestry, not a replacement for current auxiliary
source. The predecessor's index (including a staged version of a selected file)
and unrelated files are neither copied nor modified. Missing/unsafe sources fail
explicitly. Both predecessor and candidate sources are checked before native edit
acceptance and again before editor publication. A race after acceptance yields a
recoverable unpublished child, never a silently published mixed input set.

The loaded `ProjectSession` owns one immutable `ExperimentContext`: variant ID,
frozen attempt ID and expected Git state. The controller's active session pointer
selects that entire context. Git reads and admission preparation finish before the
pointer changes; there are no separately mutable manager copies to clear on error.
A gate bound to an obsolete session rejects edits. Failed candidate preparation
leaves the predecessor's frozen context intact for the next semantic edit.

Git/resource IO runs in host background work, not a GUI command handler. A pending
fork is not an accepted edit. Concurrent submissions and external changes receive
an explicit pending/conflict result. On failure the old session stays readable,
its run continues, and the command has not been falsely accepted. If the native
journal already accepted an edit but editor publication failed, the operation
reports `recovery_required` with that worktree and accepted revision. Undo/redo use
the same boundary and cannot rewrite a frozen run or replay an unrelated branch's
journal. A reopened run is historical/read-only until explicitly edited as a new
variant.

Native-journal acceptance determines the edit outcome. Secondary operation/error
metadata writes, cleanup and notifications cannot convert an accepted edit into a
plain failure. Polling includes the host operation ID, command operation ID,
variant, recovery root and accepted revision, even if error logging also fails.
The previous durable operation phase and native journal support inspection after
restart; they do not authorize replay. Recovery messages report secondary failures
explicitly. This is recoverable multi-file publication, not universal power-loss
atomicity.

## Runtime and checkpoint context

Project ID plus local revision is insufficient across branches. Runtime activity
is scoped by the existing host attachment and attempt, with immutable source
digest and retained input commit alongside it. Replacing the editor creates a new
attachment; late events remain with their original attempt. Historical evidence
can be inspected explicitly without making it current editor runtime state.

Checkpoint reuse must be explicitly supported by the registered backend contract.
A resource is not a checkpoint merely because it is retained. Conservative P2
compatibility requires the same definition, backend/version, environment,
configuration, seed and original input closure. Compatible resume records its
parent attempt and exact sealed resource; parameter changes require a declared
state-transfer operation and are rejected here. P2 adds no solver, numerical
restart algorithm, or P3-P8 scientific capability.

## Verification order

First prove dirty-repository Freeze & Run and failure recovery with a real Git
repository and the existing computation lifecycle. Only after that passes add
automatic fork-before-edit. The P2 acceptance map will link each requirement to
automated evidence, then report complete regression, packaging, exact source and
platform limits. The accepted P1 archive and receipts are not replaced.

## Implementation evidence so far

The first real dirty-repository gate passed before the automatic edit gate was
implemented: 11 freeze tests and 27 architecture/dependency checks. Its preserved
[receipt](receipts/p2-first-freeze-2026-09-10.json) records the exact source manifest
and the earlier Windows `git show` failure. Input reads now use `git cat-file`.
Subsequent focused gates proved the first fork/history transfer, retained resources,
real worker checkpoint consumption, source-file execution, and desktop Git thread
placement. These focused checks are not a complete regression claim.

Windows worktrees use an operation-scoped `core.longpaths=true` setting and retain
captured source line endings during initial checkout. The loader does not rewrite
an already equivalent native project merely to seed local history. No repository
or global Git configuration is changed. Shared Git object/ref operations run
against the common Git directory, so removing the worktree that discovered the
repository does not strand its retained runs.

The native command result has an explicit deferred state. It carries a host
operation ID, not a pretend accepted revision. JSON automation can poll that
operation; Protobuf CommandResponse adds the compatible `deferred` field at tag 6.
Previously defined fields and historical command/evidence encodings are unchanged.
The registered checkpoint adapter is optional trusted Python implementation data;
existing backend definitions and their portable encodings are unchanged. The
ordinary worker still receives its existing resource-valued configuration.

The input environment includes installed application code and registered backend
source fingerprints when available, alongside Python/platform/bundle versions.
No ambient environment variables or credentials are copied. This identifies the
declared implementation; it is not a dependency installer or a hermetic sandbox.

The current desktop's Freeze & Run button uses the selected computation backend
and domain/root. Additional UTF-8 source paths are declared in the Git panel as
`repository/path.py => runtime/path.py`. Those files join the existing emitted
Python package tree. Other backends consume typed resources and explicitly reject
file-tree attachments they cannot interpret. Unsubmitted text in a signature
editor does not reach the authority gate.

Each captured Python source file is an ordinary content-addressed resource bound
to the existing request as `source_file:<relative destination>`. Preparation and
portable plan replay use that same binding; changing the original file after
capture cannot change either execution. The trusted backend registration declares
whether it supports source-file bindings. Files are at most 8 MiB each and 64 MiB
in aggregate; the existing 128-parameter envelope includes these bindings. The
input manifest is at most 2 MiB and reachable resource references at most 1,024.
No new terminal format or second Python execution path is introduced.

## Host and automation operations

`git.freeze_run` accepts the existing serialized computation `request`, optional
`sources: [{path, destination}]`, and optional
`resume: {attempt_id, publication_id}`. It returns a pending host operation ID.
`git.experiment_operation` polls that ID (or the ID on a deferred command result).
`git.experiment_runs` lists durable attempts; `git.reopen_run` opens a retained
attempt read-only; `git.remove_experiment_worktree` removes a clean inactive owned
variant; `git.recover_experiments` reports incomplete transactions and marks orphan
attempts interrupted without replay. These use the existing READ/EDIT/SAVE/ADMIN
grants; freeze additionally requires EXECUTE. As before, ADMIN includes all grants.
Proposal mode cannot change Git state or execute a freeze.

The desktop and CLI `serve` host reconnect their existing endpoint after a session
handoff. The headless computation service survives that replacement. Automation
follows the already published controller session, reattaches its authority event
subscription, discards proposals from the predecessor branch, and requests a
snapshot resynchronization. A query never loads or reconstructs another project.
Embedding hosts remain responsible for closing retired editor sessions.

Checkpoint bindings preserve the base input closure independently of earlier
checkpoint parameters, allowing a chain of compatible resumes. Each child records
its immediate parent attempt and sealed publication. A changed definition,
configuration, input resource, implementation or environment requires explicit
state transfer and is rejected by this conservative P2 policy.

## Historical Windows verification

Keep Windows repository and worktree roots reasonably short. P5 requalification
of the unchanged independent review hit Git's `fatal: '$GIT_DIR' too big` limit
when fixtures were nested under a long receipts path, despite `core.longpaths`.
The same behavioral tests ran from a short workspace path. Git's internal path
limit is separate from ordinary filesystem long-path support; the workbench does
not replace Git to bypass it. The original LF/CRLF fixture and missing real-symlink
privilege limitations remain recorded in the P5 acceptance receipt.

Complete regression: 1,786 passed in 1300.75s. P2 plus architecture/dependency gate: 65 passed in 438.87s. Ruff, format, mypy and generated Protobuf checks passed. Wheel, native Windows CLI/GUI (including real P2 freeze/fork/reopen), all 17 extracted examples and both independent proofs passed.

Verified source: `dcc83a5a26c9b2a9501fb7c87b3780432f0c1575`. See [the phase receipt](receipts/transition-p2.json) for exact commands, hashes, earlier failed attempts and platform limitations. Final delivery metadata is adjacent to `programmodel-p2.zip`; P0/P1 files remain unchanged.

## Corrective verification

Corrective full regression: 1,800 passed in 1512.20s. P2/Qt/automation/architecture gate: 79 passed in 769.87s. All four original review probes pass unchanged. Ruff, formatting, configured mypy, protocol generation, wheel/native Windows builds, packaged source-bearing rerun/fork, all 17 extracted examples and both independent proofs passed.

Verified implementation: `1c86f680fe05dc6edc36f6b1f203fdaed7a5d113`. The [corrective receipt](receipts/transition-p2-corrections.json) preserves earlier failed attempts, exact commands and platform limits. Final archive verification is in the adjacent `programmodel-p2-corrected.verification.json`. Original P2 and P0/P1 artifacts remain unchanged.

## Freeze-recovery verification

P2 freeze-recovery verification: 1,820 tests passed in 2126.73s. The new recovery/architecture gate passed 47 cases; the legacy P2/Qt/automation/architecture gate passed 79. The original four review probes and four Windows-portable follow-up cases pass unchanged. Quality checks, fresh wheel/native CLI/GUI builds, packaged stale-marker restart/fork, all 17 extracted examples and both independent proofs passed.

See [the source-bound recovery receipt](receipts/transition-p2-freeze-recovery.json). Native Linux/macOS and Windows real-symlink controls were unavailable. P3-P8 remain unstarted.
