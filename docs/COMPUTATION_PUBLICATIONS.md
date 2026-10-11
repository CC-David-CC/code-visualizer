# Sealed computation publications

**Status: P1 accepted on the recorded Windows reference environment.** Receipts, native/Protobuf adapters, resource
admission and supervised workers are implemented in the promoted repository.
The [acceptance map](P1_ACCEPTANCE_MAP.md) and [final receipt](receipts/transition-p1.json)
separate focused proofs, corrected reference timing and complete release gates.
P0 remains independently accepted; later transition phases remain pending.
This note extends the existing [computation lifecycle](COMPUTATION_BACKENDS.md) and
[resource/evidence boundary](RESOURCES_AND_EVIDENCE.md).

The P0 application returns `ProducedResource` objects at completion. P1 adds a
bounded publication capability so another computation can consume sealed bytes
while the producer runs or after its process exits. Receipt-layer tests exercise
the shared lifecycle driver; they do not substitute for process and GUI proofs.

## Contracts and ownership

P4 adds publication-capable **`code_visualizer.python@2`**, registered by
`code_visualizer.python.artifacts@1`. Version 1 and its historical request bytes
remain unchanged. Named `ResourceInput`/`ResourceOutput` declarations extend the
existing request; nonempty bindings use native/Protobuf request version 2. The
ordinary emitted-file Python child receives verified staged input handles and a
typed publication capability. `publish_file`/`publish_bytes` return only after
host resource admission, receipt commit and ACK. Native stdout uses a separate
bounded output pipe, never the publication protocol.

Completion quiesces host publication I/O before closing staging or admitting final
evidence. Cancellation reaches the child without waiting for that I/O lock; a
receipt write already underway remains host-owned until resolved. Failed later
publications cannot remove previously acknowledged artifacts. Missing required
outputs prevent success. See [the CAD workflow](CAD_ARTIFACT_WORKFLOW.md) and
[P4's acceptance map](P4_ACCEPTANCE_MAP.md) for the concrete proof and limits.

```text
ProducedResourceEvent(session_id, sequence, resource: ProducedResource)
    -> existing resource and contract admission
    -> EvidencePublication(id, provenance: EvidenceProvenance,
                           artifact: EvidenceArtifact)
    -> PublicationEvent(session_id, sequence, publication)
```

The first event carries worker-owned staging output. The admitted publication is
immutable evidence, with a content-derived ID covering its provenance and artifact.
Execution sequence and session identity belong only to the event envelope; neither
changes the scientific receipt's identity. The provenance pins the input digest,
terminal resource, backend/version, configuration, input resources, and origins.
A publication does not have a computation-success outcome.

`EvidenceStore.put_publication` stores typed receipts under
`evidence/publications/<content hash>.json`; `get_publication` verifies them, and
`publication_identities` enumerates them independently of final evidence records.
`ResourceStore` continues to own bytes and immutable descriptors. Neither
publication nor its generated contents becomes authored project state. No new
authority, command bus, canonical model, or callable grouping concept is required.

## Operational scratch and durable resources

Source snapshots and Python execution-file artifacts are transport objects. A
computation attempt or editor preparation owns their scratch resource store. The
host explicitly supplies its durable input store for verified reads; worker paths
remain trusted launch context and never enter a project, receipt or wire message.
The same ResourceStore codec and hash/size checks serve both stores. Writes and
enumeration belong to the local store. Missing local descriptors may resolve a
declared input; malformed local metadata or missing/corrupt local bytes fail rather
than choosing another owner. Bulk inputs are not eagerly copied into scratch.
Within one process ResourceStore can compose read-through inputs. Worker launch
permits one direct input store and rejects deeper chains before launch, so ancestor
resources are never silently lost.

Preparation admits its checked scientific terminal by verified import. Execution
resources pass through the existing bounded transfer/admission path into durable
storage before a publication receipt and its ACK. Scratch cleanup cannot remove a
durable terminal, input or sealed output. No-store attempts retain their temporary
resource lifetime in the host until host close; they do not claim durable output.
Editor preparation discards scratch after decoding its admitted in-memory preview.
Durable receipts require both explicitly supplied stores. Shared submission rejects
an EvidenceStore with no ResourceStore before any attempt, callback or worker starts.
Resource-only execution remains valid without claiming durable evidence.

The unchanged foundation archive proof checks the complete resource set and bytes.
It reproduces exactly after this separation, without regeneration of historical
proof data or relaxed comparisons. Real success, cancellation and crash tests cover
the durable closure after scratch cleanup.

## Admission and bounded delivery

The existing lifecycle must perform these steps before acknowledging a publication:

1. Check the declared capability, session, monotonically increasing shared event
   sequence, unique artifact identity, and origins against the frozen input closure.
2. Validate the exact registered logical type and its dependencies, then import and
   verify the staged bytes, size, hash, and descriptor through `ResourceStore`.
3. Reserve the complete receipt against the attempt's metadata budget, then durably
   write it. A failed reservation writes no receipt.
4. Publish the admitted event to the runtime plane and acknowledge the producer.

The producer retains its staging files until acknowledgment. For an in-process
iterator, admission completes before requesting the next update, which may delete
temporary files. External transfers use the existing chunked resource protocol;
worker paths never become persistent resource references.

`application.computation_publications.seal_resource` is the common resource
admission helper. `seal_publication` accepts a staged `ProducedResourceEvent`;
`seal_admitted_publication` accepts a transferred `EvidenceArtifact` already in CAS.
Both paths use one provenance/receipt constructor, verify the actual portable event
envelope, and commit the receipt before returning the acknowledgment event.
They require an attempt-owned `PublicationBudget`. The ledger counts the larger
of each native receipt and portable event encoding, including repeated provenance,
against one cumulative 2 MiB limit. Each host job and each portable run owns its
ledger; it is ephemeral admission state, not scientific evidence.

Registered value validators run in worker/in-process admission. The receiving host
uses callback-free `check_value_contracts` and `check_resource_descriptor` to verify
typed values and exact published unit, dimension-basis, and resource contracts.
These phases share the same typed reference traversal. No foundation-specific
unit knowledge or validation-disable switch is introduced.

Progress and superseded presentation updates may coalesce. Sealed publications,
cancellation acknowledgments, and terminal events must not be dropped. Bounded
queues apply backpressure to production without blocking the GUI event loop; the
control path must remain able to receive cancellation. UI notification coalescing
must preserve access to every committed publication receipt.

Each receipt must fit both the existing 2 MiB JSON and Protobuf envelopes. Pending
delivery and cumulative per-attempt publication metadata are bounded. Reaching a
bound produces a diagnostic, never silent truncation. Bulk series belong in
resources; this phase does not promise an unbounded terminal artifact list.

## Cancellation, recovery, and downstream use

P5 exercises publication with composite field-series and checkpoint resources.
The registered interpretation exposes exact child references; the host verifies
and retains their complete closure before sealing a root receipt. The retained
attempt must durably associate that receipt before it enters the live publication
ledger or runtime presentation. Failure evidence is built from that acknowledged
ledger. A receipt or state file left by a failed association remains inert and
does not enable checkpoint Resume. Previously acknowledged prefixes survive later
bytes, descriptor, receipt, association and final-report failures. See
`test_diffusion_publication_failures.py` and [field contracts](FIELD_RESOURCES.md).

Cancellation or a later backend crash cannot mutate or retract previously sealed
bytes. Already admitted receipts remain inspectable, while the terminal attempt is
cancelled or failed. Staged or partially transferred bytes are not publications;
file existence alone never implies success. A failure between CAS import and receipt
commit leaves no accepted publication event.

Recovery must retain publication-only closure even when no terminal evidence was
written: receipt, terminal resource, input resources, and artifact descriptor/bytes.
Missing or corrupt retained data remains an explicit availability failure. Recovery
does not rerun a producer or manufacture successful evidence.

A consumer binds an exact `ResourceReference` through existing request resources or
a named resource-valued configuration parameter. Its backend validates the expected
logical type/version. This is sufficient to prove independent consumption after the
producer process exits. An explicitly selected sealed chunk does not claim the whole
producer succeeded. Future default final-output bindings must select the successful
output of a specific producer invocation, never an unqualified global `latest`.

## Compatibility and acceptance

The backend capability is `publications=False` by default. Its serializer
omits the false default so existing serialized definitions retain their bytes. A
backend must declare the capability before emitting the new event. New standalone
publication messages have their own versioned adapters; existing request, terminal,
and final-evidence encodings and hashes remain unchanged. Older peers that cannot
handle publication messages must reject that capability explicitly. Native project
format migration is not required by this addition.

Focused proofs must cover temporary-file cleanup after admission, consumption during
execution and after process exit, cancellation/crash survival, malformed publication
rejection, pinned provenance after edits, publication-only recovery, bounded event
flooding, and native/Protobuf round trips with historical hash preservation.
The [acceptance map](P1_ACCEPTANCE_MAP.md) identifies those repository tests;
the [phase receipt](receipts/transition-p1.json) records completed checks and limits.

This P1 boundary does **not** implement or claim P4's authored-Python typed model
publication interface, CAD serialization, reusable callable groups, or experiment
port graphs. Those later features must reuse this admission path.

## Closed worker messages

`domain.worker` defines inert preparation/execution requests, prepared plans,
resource frames, publication offers, proposed evidence, completion verification,
failures, and acknowledgments. `protocol.worker` provides strict byte adapters over
the `worker.proto` request/event/control unions. Every envelope has a version and
the shared 2 MiB bound. The protocol contains no `Any`, callback, import name, or
worker filesystem path. Initial requests include the complete expected
`BackendDefinition`; the installed worker must supply that exact contract.

Resource frames precede their publication offer. The host verifies the transferred
artifact and replies with the admitted `PublicationEvent` before the worker resumes
its producer. Terminal evidence has a separate handshake: the worker proposes
`ComputationEvidence`, the host secures all referenced bytes without committing
terminal evidence, then sends `WorkerTerminalSecured`. Only after the worker verifies
that its iterator has no trailing update does it send `WorkerCompletionVerified`
and exit. Host admission requires that verification and normal process exit.
Scientific receipts remain independent of session/sequence fields throughout.

Each preparation/execution phase limits resource transfers to 4096 starts, 2 MiB
of cumulative start-envelope metadata, and 2 GiB of bulk bytes. Repeated or empty
transfers consume the metadata/count budgets. A prepared response must claim
exactly its terminal and optional execution artifact. Execution claims are the
union of resource-valued observations, sealed publications, and final evidence
references. Unclaimed or omitted transfers and aborts fail before final acknowledgment;
a publication requires a finished transfer before its receipt can be written.

Editor preparation uses additional closed request/response variants. The request
pins a project resource, project identity/revision, and one selected diagram or
domain model. Optional invocation overrides contain bounded literals; the worker
binds them against the canonical function. Its response names the exact input
resource digest and a disposable emitted-file artifact containing checked runtime
symbol bindings. The host does not infer bindings from emitted source. Empty binding
collections remain omitted, preserving existing execution-artifact bytes.

Snapshot serialization uses shared persistence field inventories. The ordinary
`project_to_data` API materializes those fields; `project_data_chunks` encodes the
same fields a record at a time. Program sequences and declarations, domain nodes,
schemas, properties and role arrays use that stream. The transient `JsonObject`
and `JsonArray` descriptors describe codec work only; they are never domain values
or persisted objects. Source and computation-input hashes retain their exact bytes.
This bounds temporary collection lifetimes on the host without disabling garbage
collection or constructing a second editable model. Portable terminal round-trip
verification uses the same inventories and keeps every typed integrity check.

## Execution composition and lifetime decision

The promoted implementation supplies this lifetime model. Production GUI
submission and headless execution use one
workspace-owned computation service and the same
submitted lifecycle. `execute_computation` waits for that lifecycle; it is not an
alternative numerical implementation. An advance/poll operation delivers admitted
updates rather than invoking arbitrary backend code in its caller. Preparation,
resource hashing, backend work, and durable admission stay outside the GUI event
stack. The service retains the frozen input and stores independently of a viewed
group or editor widget; closing a view does not destroy its computation.

Python preparation imports no SVG rendering solely to compile executable
artifacts; rendering is loaded at its artifact-export use site. An accepted
EditorPreparation snapshot notifies condition waiters. These preserve the
typed preparation/observer contract without lengthening preview deadlines
or changing execution and presentation ownership.

The trusted application composition supplies an execution strategy for each exact
backend contract. A process strategy starts an approved worker executable or fixed
bootstrap whose registry is composed by installed application code. Requests carry
backend identities and immutable data, not executable names, import paths, callbacks,
or serialized Python closures. The worker verifies its available contract against
the submitted plan. A missing compatible strategy is an explicit
`COMPUTATION_WORKER_UNAVAILABLE` diagnostic, never an implicit local fallback.

The Python strategy manages the existing Python execution child directly and adapts
its events to this lifecycle. It must not run the current Python backend inside an
additional generic worker that then launches another Python child. The
`external_worker` capability describes behavior; by itself it neither authorizes a
launch nor selects a strategy. CPU execution, crash containment, cancellation grace,
and forced termination must be proven against the owned process and its descendants.
Cooperative backend cancellation and host termination are distinct operational facts;
forced termination cannot fabricate a successful result or an acknowledgment from
the backend. Already sealed publications remain valid under either outcome.

The raw `BackendExecution` driver remains usable within an already isolated worker.
An explicit in-process strategy also remains useful for trusted embedding and unit
tests. It offers no process-crash containment or forced cancellation and is never
selected because a registry is custom, a callback is a closure, or a worker is
unavailable. Production GUI/headless composition must supply a process or managed
existing-child strategy. Selecting in-process execution is an explicit host decision,
not authored project configuration.

Existing lifecycle tests register closures over temporary paths, monkeypatched
operations, and mutable cleanup probes. Windows process startup cannot preserve
that in-memory identity without serializing executable callbacks. Those fixtures
explicitly inject the in-process strategy while retaining their behavior and
assertions, including controlled one-update advancement and cancellation boundaries.
Separate process integration proofs must cover real CPU work, crashes, forced
cancellation, and GUI responsiveness. Passing the closure-based unit tests alone
cannot establish those guarantees.

Validation keeps structural integrity separate from executable completeness. Reject
corrupt ownership anywhere in the snapshot, but assess required properties,
transformations, resources, and backend availability for the requested root and its
declared dependency closure. An incomplete unrelated model must remain editable and
must not block an independent computation. The execution strategy must account for
trusted preparation implementations as well as the terminal backend; moving only
the final callback leaves expensive transformations on the GUI path.
