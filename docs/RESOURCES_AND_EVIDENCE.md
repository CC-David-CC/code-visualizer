# Resources and evidence

Project author state stays in `project.json`. `ResourceStore(project_root)` manages
`resources/sha256/<prefix>/<content hash>` and immutable descriptor JSON under
`resources/descriptors/`. `EvidenceStore(project_root)` manages immutable records
under `evidence/`. These stores are attached to a saved project session; they are
not another authority or canonical domain model.

Resource bytes use SHA-256. Descriptor identity hashes a versioned semantic encoding
of content hash, byte size, media type, optional tensor dtype/shape/axes/unit and
logical type. Thus the same bytes may have distinct descriptors without conflicting
interpretations. Managed locations are derived from hashes; project values cannot
inject filesystem paths or cause implicit network downloads. Imports stream data;
reads verify hashes and sizes. Descriptor and evidence records are bounded.

## Versioned resource interpretations

`DataResource.logical_type` is optional. When present it is a
`ResourceLogicalTypeReference(id, version)`, with a globally qualified public name
and a separate exact version. A media type describes byte encoding; this reference
identifies the public interpretation contract. It never loads implementation code.
Storage and transfer preserve a well-formed reference even when its implementation
is unavailable. Computation admission resolves that exact registered contract and
its publication dependencies before using the resource. It never selects a latest
version or treats a similar spelling as equivalent.

The universal terminal uses `code_visualizer.computation.terminal@2`, independently
of whether Python or another backend will execute it. Its resource descriptor
records the typed reference, and a portable terminal loader also verifies that the
registry provides the exact contract. The terminal is itself a resource and cannot
bypass admission merely because it is separate from the request's other inputs.

Descriptors with no logical interpretation retain the native **version 1** encoding
(`logical_type: ""`) and Protobuf descriptor version 1 with no logical-type field.
Their bytes and content-addressed descriptor identities remain unchanged. Typed
logical references use native **descriptor version 2** and the object
`"logical_type": {"id": "org.example.field", "version": "1"}`. Protobuf descriptor
version 2 carries the corresponding typed message. The descriptor identity includes
both contract identity and version; changing either produces a different descriptor,
while unchanged bulk bytes remain deduplicated under the same content hash.

Legacy nonempty opaque strings, including `computation-terminal@1`, are rejected
explicitly on load. They do not contain an authoritative qualified contract/version
pair, so the codec never invents one. The existing files are left intact for deliberate
regeneration of derived terminals or explicit resource re-import with the correct
contract. Typed descriptors claiming version 1, version 2 descriptors missing their
typed reference, and unknown versions or fields also fail explicitly. This is a
resource-descriptor evolution; canonical project JSON and CanonicalValue are unchanged.

The storage layer verifies structure and content integrity, independently of which
extensions are installed. Operational admission additionally requires a registered
published RESOURCE_LOGICAL_TYPE provider with a valid dependency closure. Thus a
resource can be safely archived without its implementation while still being
unavailable for computation. Local execution and portable workers use the same rule
for inputs, terminal payloads, produced resources and resource-valued observations.
Host-side checks resolve inert public unit/dimension-basis references as well as
resource logical types. Registered interpretation validators run during worker or
explicit in-process admission. The callback-free checks and behavioral validation
are separate operations over shared typed reference traversal; the host never
executes extension validation merely to accept a transferred descriptor.

## Portable metadata and chunked data

`domain.boundaries.MAX_PORTABLE_ENVELOPE_BYTES` is the single **2 MiB** envelope
limit shared by evidence admission, v1 Protobuf and the authenticated WebSocket.
An admitted evidence record must fit both its canonical JSON encoding and its
actual v1 Protobuf encoding. The two encodings have different overhead, so checking
the JSON length alone is insufficient. `validate_portable_evidence` performs both
checks at the outer persistence/computation boundary; the domain has no Protobuf
dependency. Existing JSON hashes remain unchanged. Oversized legacy evidence is
rejected explicitly on read rather than silently truncated or fragmented.

Evidence holds compact observations such as peak/RMS values and resource references.
Waveforms, fields, trajectories, training histories, spectra and meshes belong in
resources even when individual samples would each satisfy CanonicalValue limits.
Evidence metadata is never split into a sequence of oversized-observation fragments.

Bulk bytes use a separate versioned `ResourceTransferFrame` in `resource.proto`:

```text
start(transfer ID, immutable descriptor)
chunk(transfer ID, offset = 0, bytes)
chunk(transfer ID, offset = previous offset + previous length, bytes)
...
finish(transfer ID)
```

Every message fits the same envelope; data chunks are additionally limited to
**256 KiB**. A transfer ID is an opaque ephemeral identity, never a file path.
The descriptor identifies the expected resource, content SHA-256, total byte size,
and typed metadata. A receiver admits only the resource reference explicitly
requested by its caller, checks descriptor identity and its caller-selected storage
budget, and streams into a randomly named managed staging file. Duplicate starts,
identity changes, gaps, replayed offsets, excessive bytes, unknown fields/versions,
truncation, aborts and trailing frames fail explicitly and remove staging data.
An empty resource uses start/finish without an empty chunk.

Finish seals the stream after size/hash verification. Commit reverifies the sealed
file before publishing immutable content and descriptor; no receiver-side path is
accepted from the sender. The iterator/context-managed APIs clean staging files on
disconnects and exceptions. A process killed without unwinding can leave unpublished
staging data or an unreferenced verified content blob. Neither publishes a partial
resource descriptor or changes canonical author state.
There is no resume protocol in v1: restart a failed transfer under a fresh transfer ID.

`application.worker_transport` integrates this with the existing portable worker:

- `export_resource_stream` yields bounded binary frames directly from a verified
  resource file, without loading the whole resource.
- `import_resource_stream` consumes those frames and commits only after a valid
  complete stream. An explicit registry additionally validates semantic contracts
  at the start frame before committing data; raw archival copying preserves unknown
  typed references.
- `run_streamed_computation_plan` receives a binary plan plus its explicit input
  resource streams, invokes the existing `run_computation_plan`, and returns one
  bounded binary evidence message. Input resources already cached by verified
  identity may be omitted; unsolicited/duplicate inputs are rejected. The caller
  supplies a total incoming-byte budget. Earlier successful immutable transfers
  remain reusable if a later input fails. The worker always supplies its registry
  and checks logical-type contracts for both incoming and previously cached inputs.
- Output artifact references in the returned evidence are transferred through the
  same stream API in the reverse direction.

This is a portable worker API, not another server or authority. Its caller owns
transport authentication. The existing authenticated WebSocket command channel
retains its command protocol and the same 2 MiB limit; no project command can
provide a filesystem path or bypass resource verification.

Backend resources can exceed the 64 MiB in-memory read limit. The shared computation
resolver provides a verified ephemeral file input above that limit, with the same
descriptor used for small byte inputs. Backends can return a typed file output with
declared size/hash; admission streams and verifies it before publishing the content
reference. Backend-owned staging files remain the backend's cleanup responsibility.
No local input or output path is persisted or transported in a plan or evidence.

The existing recovery-copy action copies the canonical resource closure and this
project's durable evidence, including sealed publication-only receipts and their
input, terminal and output resources even when the producer never completed.
Each resource is streamed into independent destination storage and verified before
project metadata is published. The original data remains intact. Unrelated resource
objects and editor journals are not copied; corrupt or unavailable required content
fails explicitly. Ordinary Save As retains its existing restriction to an unsaved
project or the same project root.

An evidence record pins project revision, source model, backend identity/version,
input digest, configuration, random seed, input resources, transformation versions
and an immutable OriginMap. Durable computations also pin the terminal resource
needed by a worker to reproduce the result without the editor's project instance.
Observations hold bounded typed values; artifacts hold
resource references. Both can name originating semantic objects. Evidence is
content-addressed using the explicit versioned JSON encoding, independently of
Protobuf's wire encoding. This is an integrity contract, not a cryptographic claim
that an untrusted backend's scientific result is correct.

Ephemeral sessions decorate views through the existing runtime and selection plane.
The evidence record survives that session and does not change when an author edits
the project. Evidence from an earlier revision stays historical; it cannot masquerade
as a current runtime observation.

The P1 draft adds immutable `EvidencePublication` receipts under
`evidence/publications/`. A streaming backend can seal a typed output before its
final result. Receipt admission verifies resource bytes and contracts and reserves
the complete metadata against a cumulative 2 MiB per-attempt budget before writing
the receipt. It then acknowledges the producer, which may release its staging file.
Another computation can consume that exact resource while the producer runs or
after process exit. Cancellation and later failure cannot retract a receipt, and
a receipt never claims the overall computation succeeded. Historical final-evidence
bytes/hashes remain unchanged. See [sealed publications](COMPUTATION_PUBLICATIONS.md)
for the closed protocol and remaining draft acceptance gates.

`PromoteEvidenceObservation` is an explicit typed authority command. It carries the
selected bounded evidence record and observation identity plus a target property.
The handler verifies content identity, project, successful outcome and non-future
revision, then applies the normal property edit with its schema validation and
undo/redo behavior. Historical observations may be promoted deliberately under the
current command revision precondition. The journal preserves that action's evidence;
the project stores only the newly authored property. No automatic promotion occurs.

The current storage policy retains immutable records until an explicit maintenance
operation removes them. It performs no automatic garbage collection. Backends may
use file-oriented data formats such as NPY, HDF5 or images through media types and
registered implementations; the universal descriptor does not encode physics.
