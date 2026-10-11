# Time, accepted state and numerical checkpoints

P5 uses the existing host-owned computation lifecycle, Git freeze transaction and
immutable publication receipts. Physical time belongs to the field interpretation;
it is independent of worker transport sequence, elapsed wall time and playback.
The diffusion backend is a bounded first-party domain adapter. Neither the generic
kernel nor ProgramModel implements its numerical method.

## Three state boundaries

| State | Owner and lifetime | What it establishes |
|---|---|---|
| Numerically accepted state | Mutable worker vector until publication | A step passed the backend's residual, endpoint, finiteness and decay checks |
| Published accepted state | Immutable resource closure and acknowledged receipt | Exact sampled values and their interpretation are durably associated with this attempt |
| Trial preview | Latest replaceable runtime event | A reduced provisional candidate and its accepted base; no durable result or restart promise |

`TemporalPosition` contains a physical-time quantity, accepted step and sample
index. A series records exact sample positions and ordered chunk coverage. The
reader rejects gaps, overlaps, incompatible interpretations and invalid coordinates.
It never interpolates or clamps a requested sample. A cancelled or interrupted
attempt can have a useful published prefix; that does not make the attempt successful.

The numerical example uses fixed-step Crank–Nicolson integration with a real
predictor and correction. The correction is checked before the candidate becomes
the next accepted vector. A scalar preview carries the accepted/trial pair, common
sampled node indices, interpretation, source/input identity and distinct accepted
and candidate times. It has at most 256 values per state. The existing runtime
plane keeps one latest preview per attempt; the Qt observer samples it independently.
Changing preview frequency or the playback clock cannot change integration steps
or scheduled published samples.

## Publication and recovery order

The worker transfers the declared child resources and root through the existing
bounded transport. The host verifies the complete interpreted closure, seals the
publication receipt and associates it with the retained attempt. Only then does
it expose the publication to the live ledger and acknowledge it to the worker.
Every claimed resource must have completed a transfer in that worker phase,
including children already present in the local content-addressed store.

An I/O failure can leave orphan bytes or a receipt that was not acknowledged. These
are preserved as inert recovery material. They do not appear as a usable retained
checkpoint, live publication or successful failure-evidence artifact. Earlier
acknowledged publications remain valid. A terminal-report failure cannot retract
the durable freeze association or silently permit edits to the frozen variant.

Git establishes the input commit, retained reference, attempt and recoverable
authoring protection before computation admission. Startup reconciles these
durable facts; a stale unrun marker cannot override them. An orphan host attempt
is reported as interrupted, not inferred successful from output file presence.
P5 preserves the P2 recovery rules and unchanged regression tests.

## Restart contract

`code_visualizer.diffusion.checkpoint` version 1 is a closed, bounded resource
record. It references the full accepted numerical vector and an acknowledged
field-series prefix, and records:

- The scientific definition compatibility digest and exact interpretation.
- Accepted physical time, step and sample position.
- Fixed integration, sampling and checkpoint policy digest and next cursors.
- Numerical method/state-format identity, float64 and NumPy/SciPy versions.
- Immutable vector and prefix references, with their complete resource closure.

The scientific compatibility digest excludes the act of choosing a checkpoint.
The complete computation input digest includes that choice. They serve different
purposes and both remain in provenance. Selecting a checkpoint never edits the
original physical definition or writes a transformed model back into the project.

Resume is explicit. The retained-run controls select an acknowledged publication
owned by the chosen attempt. The application recovers the original unresumed
request through explicit parent links, then uses the ordinary freeze/bind path.
The backend independently validates the actual resource state for both prepared
and portable requests: source and policy, numerical identity, field/grid/frame,
unit and quantity kind, array shape/finiteness, endpoints, exact accepted vector,
prefix coverage and every retained physical time. Coverage must equal the union
of the authored sampling and checkpoint schedules, including initial and final
states. Ordered rows with a missing or unscheduled sample are rejected, even when
their times and final vector agree. An incompatible input is rejected;
there is no automatic state transfer between changed models or grids.

Cancellation checkpoints the last **scheduled sampled accepted state**. Any
newer numerical tail is recomputed on resume. Thus progress may show a later step
than the retained checkpoint, and cancellation cannot add an unscheduled sample.
The resumed output retains the old prefix and starts after its boundary without
duplicating a sample. Identical requests make distinct attempts; the same source
commit can serve those attempts. A changed resume input can require a new frozen
variant through the existing Git transaction.

## Presentation and retained use

The history cursor selects an exact retained sample. Accepted history, provisional
trial and attempt outcome are labeled separately. The optional time overview is
a reduced image of at most 64 exact sample times and 512 spatial columns. It is
presentation, not another field. The viewer holds at most one active and one
replaceable pending preparation, with a 64 MiB chunk cache. Attachment, generation
and revision guards reject late results from replaced editors and equal-revision
branches. Resource and Git operations run outside GUI handlers.

An independent Probe intention can consume a selected field resource after the
producer and its host have exited. It requires the declared closure and exact
sample, node, time, unit and interpretation. No producer filesystem path or
editable copy of the result is needed. Published bytes survive editor replacement,
branch changes and removal of a clean inactive managed worktree.

Executable proofs and measured limits are listed in
[P5_ACCEPTANCE_MAP.md](P5_ACCEPTANCE_MAP.md). The user-facing sequence is in
[DIFFUSION_FIELD_WORKFLOW.md](DIFFUSION_FIELD_WORKFLOW.md); field encodings and
resource bounds are in [FIELD_RESOURCES.md](FIELD_RESOURCES.md).

## Adaptive continuum continuation

The new `code_visualizer.adaptive_diffusion.checkpoint` version 1 preserves an
adaptive cell partition, accepted sampled vector, complete history/decision
prefix, temporal proposal, rejection/work totals, dwell/coarsening counters
and future schedule cursors. It requires the exact authored dependency and
numerical implementation identities. It uses the same host acknowledgment,
retained attempt association and explicit resume controls described above.

Physical time is an integer tick of the authored quantum. Each sample names
its exact mesh epoch. Cancellation restores the last sampled accepted boundary
before sealing its checkpoint; an unsampled private numerical tail is not
retained evidence. Resumption preserves all sample values, supports and decisions.
If cancellation closes a partial chunk, chunk packaging can differ from an
uninterrupted run. Regular checkpoint continuation also reproduces the final
resource root when those boundaries coincide.

The support-aware consumer selects a sample, epoch, cell lineage and component,
not a reused array index. Its immutable closure survives worker exit, editor
replacement and clean inactive worktree removal. See [ADAPTIVE_FIELDS.md](ADAPTIVE_FIELDS.md)
for the closed encoding and [P7_CONTRACT.md](P7_CONTRACT.md) for its numerical proof.
This is the continuum continuation contract; native particle recovery is a
separate P7 feasibility/qualification effort.
