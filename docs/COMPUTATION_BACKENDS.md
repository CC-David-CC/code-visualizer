# Computation backends and evidence

**P1 status: integration verification.** The host/service and publication behavior
below is implemented in the isolated draft. P0 remains accepted; focused proofs do
not replace P1 GUI/process acceptance and the complete regression gate.

A computation targets a registered representation contract. The Python-program
backend executes ProgramModel; Python implements all current adapters. Other
domain models can target their own representations and registered computations.

```text
canonical project revision + explicit source model
    -> deterministic scoped transformation plan
    -> immutable terminal model + origin map
    -> registered backend
    -> typed observations and resource artifacts
    -> immutable evidence
    -> existing runtime timeline, semantic selection, and editable notations
```

## Ownership and admission

`ComputationRequest` selects an exact backend identity/version and an optional domain
model identity, with typed configuration, an optional reproducibility seed, and
resource references. An absent model selects the directly authored programming
domain. Selecting a domain model makes it the computation root; referenced objects
remain inputs, and transformed output remains disposable.

`generation.computation.prepare_computation` reuses the existing transformation
planner. Planning still rejects ambiguous paths, missing dependencies, cycles,
invalid intermediate models, identity collisions, and missing origins. Backend
registrations carry the required representation and optional exact schema/version.
A missing implementation produces an explicit diagnostic. Registration order never
chooses a backend or a transformation path.

Global structural integrity is checked first. Required values, schema constraints,
and extension requirements then follow the selected domain model, referenced input
closure and transformation schemas. An unrelated incomplete domain remains editable
without blocking this computation; a missing required referenced value still blocks
it. A malformed Python expression cannot prevent an independent mathematical
computation. A ProgramModel terminal continues through the existing Python admission
checks. The complete authored Python contribution is retained; dynamic Python
dependencies are not inferred from a few syntactic references.

`DomainExtensionBundle.backends` contains trusted implementation registrations.
Project data cannot import a backend, persist a callback, or execute a transform
through Python `eval`. A backend consumes `PreparedComputation` and returns a frozen
`BackendResult`. Observations use the closed canonical value algebra; bulk output
uses `ProducedResource` and the managed resource store.

## Host ownership and execution strategies

`ComputationService.submit` captures an immutable project/request snapshot and
returns a queued session. The host retains the attempt and its resource/evidence
stores independently of an editing attachment. Main-window session replacement
detaches the old kernel; it does not destroy that host's running jobs. A standalone
kernel that created its own host closes it when the kernel closes.

Production preparation and registered backend behavior execute in a supervised
worker selected by a trusted `WorkerProfile`. The profile's command is application
composition, never persisted project input. The worker verifies the exact expected
`BackendDefinition`, including capabilities. Missing or ambiguous strategies fail
explicitly; a custom registry or unavailable worker cannot trigger an implicit
local callback fallback.

The orchestration pool handles snapshot encoding/hashing and host resource/evidence
admission outside GUI handlers. Extension validators and transformations run in the
worker. Host receipt checks resolve typed public contracts, verify bytes and origins,
and enforce protocol state without executing extension validators. Python preparation
emits the existing file-tree artifact; its worker exits before the host starts the
existing managed Python execution child. There is no nested Python solver worker.

GUI controls submit and observe immutable attempt snapshots. `execute_computation`
submits the same lifecycle and waits; `advance_computation` waits for admitted data
without executing a backend on its caller's stack. Neither blocking API belongs on
the GUI event stack. Selection delivery runs on the observer's thread. Progress may
coalesce, while every admitted publication remains addressable by receipt identity.
Default host admission bounds are four orchestration workers and 256 retained
attempts; exceeding the attempt limit is explicit.

`InProcessDriver` is an explicitly selected embedding/test strategy. It preserves
local closure identity and one-update stepping but provides no process isolation or
forced-preemption guarantee. The low-level `BackendExecution` and portable
`run_computation_plan` remain callable within an already isolated worker or trusted
embedding. Their synchronous APIs do not establish a GUI-safe execution strategy.

## Python build roots

The public Python build retains authored ProgramModel functions and adds domain
models with applicable ProgramModel transformation paths. Reference-only data
models do not become implicit Python roots. Invalid or ambiguous plans still fail,
including a declared multi-stage route whose schema scope or prerequisite ordering
prevents an executable plan. Declared routes are checked by exact representation
identity/version; they never authorize borrowing another schema's implementation.
Explicit `model_ids` can exclude such a model when choosing a narrower build.
If no Python route is declared at all, the model remains a reference-only input,
and a domain-only project producing no executable functions reports a missing
Python path rather than claiming that an empty program implements its meaning.

`prepare_build(..., model_ids=(...))`, `generate_python`, and
`generate_python_project` accept explicit contribution roots. The existing
`entrypoint_model_id` selects the entrypoint while retaining other applicable
contributions unless `model_ids` narrows them. All domain data and required bundles
remain validated. No transformed program enters canonical project storage.

The Python computation adapter reuses existing lowering, emission and project trace
execution through its managed child. It retains canonical invocation binding,
coroutine/generator handling and source maps. Its observations identify traced
program objects and explicitly text-valued stdout/stderr. It does not reinterpret
printed Python representations as typed return values. Interactive Python debugging
and its runtime object graph remain available through the existing debugger.

A program without a selected callable executes its modules in canonical declaration
order and then its launcher startup declarations. The emitted launcher owns this
operation and every selected callable invocation, including result policy. Run,
Trace, Debug, and the Python backend execute those same files. Live sessions
materialize a disposable directory and use normal Python imports, so `__file__`,
`inspect.getsource`, relative imports, and package resources retain Python semantics.
The directory remains alive until the process exits, including cancellation,
failure, and restart. Runtime variable bindings include module and qualified
function names so identically named methods remain distinct. Focused diagram
execution retains complete modules, omitting only
unrelated incomplete function definitions; initialization dependencies and dynamic
reflection prevent that omission.
The generated-code pane displays the selected file's ordinary Python source.
`SourceLocation(file_path, line, column)` identifies positions relative to the
emitted root, independent of temporary-directory names. Breakpoints, events, and
stack frames use these positions directly; no embedded loader or line-offset
conversion is involved. Debug starts at configured file breakpoints, or steps at
the first emitted statement when no breakpoint was supplied. Traces include module
and package initialization. Explicit standalone source-snapshot automation remains
a separate supported input to the same worker; it is not a ProgramModel runtime.
Streams larger than the inline value limit become UTF-8 text resources. Trace
observations are bounded, with an explicit truncation diagnostic. The adapter's
`timeout_seconds` configuration defaults to 30 and accepts values up to 300.

## Resources, origins, and evidence

Input resources are resolved from the terminal model, configuration, explicitly
supplied handles, and the transitive containment/reference closure of cross-model
inputs. Unrelated model values are not read. Resource identities, descriptors, and
payload hashes are verified before execution. `ResolvedResource` carries its
descriptor and exactly one input: immutable bytes up to the 64 MiB read bound, or
an ephemeral `ResourceFile(path, byte_size, content_hash)` for larger inputs.
`resource.open()` opens a caller-closed binary stream for either variant; a file
backend may also use `resource.file.path` with its own streaming or mapped library.
The managed input is read-only to backends. Integrity is checked during resolution;
an external process changing the store requires another verification before reuse.
Their disposable project context contains only the terminal and declared input
closure, so a local backend cannot inspect unrelated editor contents that would
be absent from its portable execution package.

Every observed semantic identity must belong to the terminal or its declared input
closure. Origins then connect derived identities to their original intentions.
Unknown output identities, mismatched revisions, corrupt resources, and invalid
typed values are rejected before publishing runtime state. `ProducedResource`
accepts exactly one output: bounded immutable bytes, or the same typed `ResourceFile`
contract. File output is streamed into the managed store, and its declared size
and hash must match before publication. Files larger than memory limits therefore
remain usable in both local and portable execution.

The backend owns output staging files. A batch backend keeps them available until
the enclosing computation call returns. A streaming backend keeps them available
until the host resumes its iterator after the terminal result. The host imports
and verifies those outputs first, then checks that the iterator ends without another
update, and only then commits and publishes evidence. This permits ordinary
`TemporaryDirectory` and `finally` cleanup around a terminal yield. Invalid trailing
updates publish no evidence; already verified resource bytes are disposable cache
contents. Cleanup remains backend-owned on success, cancellation, or failure. The
host never deletes an arbitrary backend-provided path. Input/output paths are ephemeral process details;
they do not enter canonical values, portable plans, Protobuf messages, input digests
or evidence. Only verified content references cross those persistent boundaries.
The foundation mathematical evaluator retains its smaller bounded tensor contract
and explicitly rejects file-backed inputs it cannot evaluate.

`ComputationEvidence` records the backend identity/version, pinned project revision,
input digest, ordered transformations, typed configuration, seed, input resources,
terminal resource, observations, output artifacts, diagnostics, and immutable origins.
Its identity is the hash of its encoded content. There are no wall-clock timestamps
or random execution-session IDs in deterministic evidence content.

Resource references in observation values obey the same integrity and descriptor
validation as artifact references. Terminal observations may reference freshly
produced resources in the same result, because imports precede evidence admission.
Live observations may reference only resources that are already published and
verified; missing, corrupt, or dimensionally invalid resource descriptions cannot
enter the shared runtime timeline.

The current input digest covers canonical project JSON plus the normalized request.
This conservatively invalidates evidence when any project content changes; it does
not pretend that untracked external state is a reproducible input. A backend must
express relevant inputs through its request and resource contract.

`ResourceStore` and `EvidenceStore` live beside project JSON. Durable computation
publishes its terminal resource before execution, so the evidence alone identifies
the reproducible input artifact. Production attempts without a supplied resource
store use a temporary host-owned store retained until host close. That availability
does not promise durable replay; sealed publications require explicit durable stores.
Low-level in-memory embedding may also produce ephemeral evidence without a terminal
resource. An explicit recovery copy preserves the snapshot's resource references,
durable evidence and publication receipts, including all input, terminal and output
resources, through verified immutable imports. Publication-only recovery works even
when no final evidence was written. It leaves the original stores intact and does
not copy unrelated cached resources or the old journal. Ordinary Save As does not
relocate a saved project to another root.

Evidence records decorate the existing `RuntimeSessionRegistry`. Each observed
identity and its original causes enter the same selection and notation overlays as
Python events. Editing afterward leaves evidence pinned to its original revision;
views mark the observation stale while rendering current canonical values. Observed
values become authored properties only through an explicit
`domain.node.promote_evidence` command, with ordinary validation and undo/redo.

## Sealed publications and downstream consumption

A streaming backend declaring `publications=True` may yield a
`ProducedResourceEvent`. Shared admission verifies the exact logical type/version,
resource descriptor and bytes, checks origins and reserves the full metadata budget
before committing an immutable `EvidencePublication`. Its content-derived identity
covers provenance and one `EvidenceArtifact`. Session identity and sequence belong
to the `PublicationEvent` envelope, not the scientific receipt.

The worker retains staging output while awaiting the admitted receipt acknowledgment.
Only that acknowledgment permits iterator advancement and temporary-file cleanup.
The host's native/Protobuf envelope and cumulative receipt limits are 2 MiB; repeated
provenance counts toward the budget. Resource transfer separately bounds bytes,
descriptor metadata and transfer count, including empty transfers. The host rejects
unclaimed, omitted, incomplete or unrelated resource transfers before accepting the
associated output. See [Sealed publications](COMPUTATION_PUBLICATIONS.md) for limits.

A consumer names the exact `ResourceReference` in request resources or a resource-valued
configuration parameter. Its backend checks the expected logical type/version. The
same bytes can be consumed while the producer continues or after producer process and
host exit. This explicit selection is not an automatic experiment dependency graph
or a claim that a partially completed producer succeeded.

Final evidence is admitted separately: the worker transfers output bytes and proposes
evidence, the host secures its complete resource closure and acknowledges it, and the
worker verifies that its iterator has no trailing update. Only completion verification
and normal process exit allow final evidence commit. Already sealed receipts survive
a later cancellation, crash or invalid terminal stream; unfinished staging is never
promoted to a receipt merely because bytes exist.

The false publication capability is omitted from existing serialized definitions.
New publication/worker messages are additive contracts; historical request, terminal,
resource and final-evidence encodings retain their hashes. Native project revision 11
does not change for P1. This is not the later authored-Python model-publication API,
and it introduces no handwritten CAD or other scientific-domain implementation.

## Portable terminal contract

`export_computation_plan(kernel, request)` publishes a `ComputationPlan`: the request,
terminal representation, content-addressed model resource, transformation identities,
origin map, and input digest. The terminal uses the explicit media type
`application/vnd.code-visualizer.computation-terminal+json;version=2`, with logical
type `code_visualizer.computation.terminal@2` supplied by `code_visualizer.computation@2`.

The resource includes the typed terminal, relevant schemas, and explicit referenced-input
slices. Python modules, classes, package, entrypoint arguments, and launcher startup
are carried exclusively inside ProgramModel; executable ModuleSetup is absent.
Old immutable terminal resources remain readable as resources but cannot execute as
the new terminal contract. Project format migration reconstructs authored Python
ownership before a new terminal is built. The terminal contains no editor
views or authority state. The loader verifies canonical JSON encoding, full field
round trips, resource hashes, representation/schema scopes, all dependency-domain
validators, and exact origin coverage. Unknown or omitted fields cannot silently
change meaning through legacy persistence defaults.

`run_computation_plan(plan, registry, resource_store, evidence_store=None)` executes
this package without an editor project or ProjectAuthority. This is the worker
boundary. Protobuf adapters encode the same typed request, plan, session, progress,
observation, cancellation, and evidence contracts. Protobuf is transport; canonical
project JSON remains the source format.

## Backend implementation API v1

`BackendDefinition.api_version` is the implementation API version, separate from
the backend's own semantic implementation version and the Protobuf schema version.
Inert definitions for future APIs can be inspected and transported, but
`RegisteredBackend` rejects every unsupported API before publication. API v1 admits
exactly one implementation corresponding to its declared execution mode:

```python
# Batch: existing backends use this unchanged callback shape.
RegisteredBackend(definition, execute=run_batch)
# run_batch(PreparedComputation) -> BackendResult

# Streaming: the execution driver advances the iterator one update at a time.
RegisteredBackend(definition, stream=run_stream)
# run_stream(PreparedComputation, BackendContext)
#   -> Iterator[ProgressEvent | ObservationEvent | ProducedResourceEvent | BackendResult]
```

`BackendCapabilities` explicitly describes `batch` or `streaming` execution,
live progress, live observations, sealed publications, cooperative cancellation,
deterministic behavior, seed-controlled behavior, and use of an external worker.
These are implementation
guarantees, not requests to the host to invent those features. Batch backends cannot
advertise live progress, live observations, publications, or cooperative cancellation.
They may return typed
observations in their terminal result. `seeded=False` means no seed-controlled
behavior is promised; an optional request seed remains provenance metadata and
does not silently become a reproducibility guarantee. `deterministic=True` promises
the same result for identical admitted inputs; `seeded=True` promises repeatability
when the relevant inputs include the same seed. The indexed math backend declares
determinism. Python declares an external worker and no determinism guarantee.

The backend lifecycle is `queued -> running -> succeeded | failed | cancelled`.
Within an explicitly selected driver, advancing performs one batch execution or
requests one streaming update. The production host separately records preparation,
running, cancellation and final-verification phases; its public advance operation
only waits for admitted data. A streaming backend emits exactly one terminal result
and then ends. Live observations, progress and publications share one strictly
increasing sequence; wrong sessions, repeated
sequences or observation IDs, undeclared events, unknown semantic origins, missing
terminal results, and updates following termination are explicit failures.
Every live progress or observation update must fit the exact 2 MiB Protobuf envelope
before it is accumulated or published, including labels and progress messages.
Inbound and outbound event adapters enforce the same limit. No metadata is silently
truncated. Completion separately enforces the total evidence envelope.
Accumulated live observations also share the 2 MiB bound, measured incrementally
using their exact repeated-field encoding in portable evidence. Crossing it rejects
the next observation before accumulation or publication and directs the backend to
use resources for series. Final admission additionally counts provenance, resources,
diagnostics, and the canonical JSON encoding; it can never persist an oversized record.
Streamed observations are accumulated once in final evidence; a streaming terminal
must not repeat them. Final evidence is subject to the same portable metadata
envelope as every other backend; waveforms and large series belong in resources.

The backend API's cancellation capability means cooperative cancellation.
`BackendContext.cancellation_requested` becomes true; the implementation releases
its own computation resources and returns `BackendResult(CANCELLED)`. A queued
cancellation completes without calling the implementation. Reporting cancellation
without a supported, accepted request is invalid, as is reporting success after
accepting cancellation. Backends may report failure while cleaning up. Repeated
cancel requests before termination are harmless. A blocked in-process iterator
cannot be preempted by this API. Checkpointing is not a v1 capability.

Production host cancellation also supervises the owned process tree. It sends the
typed request where supported and applies bounded grace before forced termination
if the worker cannot cooperate. Managed Python cancellation uses the existing child
adapter. Host-forced termination is recorded separately from backend capability or
acknowledgment; an ordinary crash or normal exit is not called forced termination.
Thus a batch backend's `cancellation_supported=False` does not prevent the host
from stopping its isolated process. Explicit in-process batch composition still
reports `COMPUTATION_CANCEL_UNSUPPORTED`.

Terminal admission is a cancellation boundary: an earlier accepted cancellation
cannot yield successful evidence, and `cancel` after final verification begins
returns `COMPUTATION_FINALIZING`. Host shutdown drains finalizing work rather than
changing its outcome or killing the verifier. Closing an editing attachment is
different from closing this host. Failed/cancelled attempts retain earlier sealed
publications and diagnostic state through the same existing runtime plane.

No new project authority or command bus exists. The supplied math and Python backend
definitions remain batch implementations; the host supplies their process lifetime.
Streaming semantics are proved by an ordinary registered test backend, without
putting its domain-specific behavior into the lifecycle.

## APIs and CLI

The kernel exposes these existing-registry capabilities:

- `analysis.computation_backends`: backend contracts;
- `generation.computation_plan`: publish a portable plan;
- `execution.computation`: execute a typed request;
- `execution.computation_start`: submit a pinned request and return a queued session;
- `execution.computation_advance`: wait for an admitted update using `session_id`;
- `execution.computation_cancel`: request cancellation using `session_id`;
- `analysis.computation_sessions`: pinned computation sessions;
- `analysis.evidence`: read current or durable evidence.

Execution uses the existing automation EXECUTE permission; plan publication uses
GENERATE. No second authority, command bus, or unauthenticated server is introduced.

```powershell
python -m code_visualizer compute PROJECT --backend foundation.math.indexed_equations --model MODEL_ID
python -m code_visualizer export-plan PROJECT --backend foundation.math.indexed_equations --model MODEL_ID --output run.plan.json
python -m code_visualizer run-plan run.plan.json --resources PROJECT
python -m code_visualizer export-plan PROJECT --backend foundation.math.indexed_equations --model MODEL_ID --output run.plan.pb
python -m code_visualizer run-plan run.plan.pb --resources PROJECT
```

`--backend-version` defaults to `1`. `--seed` and `--configuration` populate the typed
request. The latter accepts an object of named canonical JSON values. `run-plan`
needs the resource store and registered backend, and can run while project.json is
absent. It writes derived evidence rather than opening an editor authority.
The `.pb` suffix selects the versioned Protobuf plan contract. `--protobuf` selects
the same wire format explicitly for either plan command.

`tests/test_computation_backends.py` covers direct domain-backend transformation execution,
Python regression, explicit roots, closed values, resource closure and corruption,
portable replay, shared notation highlighting, stale evidence, undo/redo, native
persistence, and CLI execution with project.json removed from the worker inputs.
`tests/test_backend_lifecycle.py` covers lifecycle transitions, live shared origins,
batch parity, cooperative cancellation, capability/API admission, deterministic
evidence, and rejection of malformed streaming protocols.
