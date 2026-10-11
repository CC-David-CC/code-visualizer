# Versioned protobuf boundaries

The protobuf contracts describe exchange between tools. Canonical domain objects remain immutable
Python values, `ProgramModel` retains its native representation, and every edit still enters the
existing `ProjectAuthority`. Project files and undo journals retain the native JSON format.

The checked-in schemas are in `src/code_visualizer/protocol/v1/`:

| Contract | Contents |
| --- | --- |
| `identity.proto` | Stable semantic identities, exact version references and origin mappings |
| `value.proto` | Text, boolean, integer, real, complex, quantity, tensor and resource values |
| `domain.proto` | Schemas, concepts, property/role definitions, objects and models |
| `resource.proto` | Immutable resource metadata, tensor axes, dtype, shape and units |
| `computation.proto` | Backend descriptions, revision-pinned requests, terminal plans, sessions, progress and cancellation requests |
| `evidence.proto` | Observations, artifacts, diagnostics, configuration, composed origins and sealed publication receipts |
| `worker.proto` | Closed preparation/execution requests, resource events, publication acknowledgments and terminal verification |
| `command.proto` | Explicit intentional edits and authority receipts |

The identity family now also carries bounded publication manifests: namespace-owner
claims, typed public contracts, exact dependencies and resolved public references.
Receiving a manifest never installs code or grants namespace ownership. See
[Contract identities](CONTRACT_IDENTITIES.md). The resource family carries bounded
start/chunk/finish/abort transfer frames; each chunk carries at most 256 KiB and
uses the same 2 MiB envelope limit as other messages. The computation family carries
backend API versions and explicit batch/streaming capability declarations.
Streaming backends opt into sealed output publication with the additive
`publications` capability. Its false default is omitted, preserving existing
backend message bytes. Scientific `EvidencePublication` records reuse provenance
and artifact contracts; `PublicationEvent` carries the separate session/sequence.
Final evidence encodings and their native content hashes are unchanged.

The resource family explicitly supports two descriptor revisions. `DataResource`
version 1 is retained only without a logical interpretation contract. Version 2
requires `ResourceLogicalTypeReference(id, version)` in new field 8,
`logical_type_reference`. The former opaque string field 7 and its name
`logical_type` are reserved, never recycled. Legacy messages containing field 7
are rejected as unknown rather than silently assigned a contract version. A typed
reference with descriptor version 1, or a version 2 descriptor without one, is
invalid. Other message families keep their existing schema versions. See
[resource descriptor evolution](RESOURCES_AND_EVIDENCE.md#versioned-resource-interpretations)
for native persistence and identity preservation. Protocol decoding proves structure,
while computation admission additionally proves a registered provider.

Durable evidence must fit both the native metadata encoding and the actual v1
Protobuf encoding within 2 MiB. Resource bytes use streamed transfer; evidence
metadata is never made unbounded by fragmenting it. See
[Resources and evidence](RESOURCES_AND_EVIDENCE.md) for the portable worker API.

These contracts contain no `Any`, `Struct`, JSON payload, executable callback, project-supplied
Protobuf type descriptor, Python source, or duplicate encoding of the programming AST. Domain schemas determine
what quantities, fields and other values mean. The common value contract carries their structure.

`CanonicalValue` uses a closed `oneof` with `schema_version = 1`. False, zero and empty text are
present values. Absence is represented by field presence; there is no null value. Property removal
has its own command variant. Signed 64-bit integers use `sint64`; larger integers use bounded
canonical decimal text, preserving the canonical 4096-bit integer range. Reals preserve IEEE 754
binary64 values, including negative zero; non-finite values are rejected. Tensor dtype, shape and
elements are checked by the same canonical constructors used by native commands. Resource messages
carry content identities and metadata; they do not grant access to arbitrary filesystem paths.

Every public decoder rejects unsupported schema versions, unknown fields (including nested fields),
missing required messages, unknown value variants and messages over 2 MiB. A newer sender must use a
contract the receiver supports; the adapter never drops a field and then claims a lossless round trip.
Optional fields and oneofs retain explicit presence, following the
[protobuf field-presence contract](https://protobuf.dev/programming-guides/field_presence/).

## Use the existing automation connection

Open the normal bearer-authenticated WebSocket endpoint and initialize in JSON:

```json
{"jsonrpc":"2.0","id":1,"method":"service.initialize","params":{"actor_id":"engineer","binary_protocol":"protobuf.v1"}}
```

After initialization, binary frames contain a generated `command_pb2.CommandEnvelope`; the binary
reply is `command_pb2.CommandResponse`. JSON requests remain available on the same connection.
Unnegotiated binary frames are rejected. Claimed actor and project identities must match the
authenticated session and its project. The adapter calls the existing service dispatch, which checks
capabilities, proposal/commit mode, revision, idempotency and canonical validity before journaling.

For an in-process client constructing a wire command:

```python
from code_visualizer.application.domain_commands import SetDomainProperty
from code_visualizer.protocol.commands import command_to_proto

command = command_to_proto(
    SetDomainProperty("model-id", "node-id", "property-id", 42),
    actor_id="engineer",
    operation_id="operation-id",
    project_id="project-id",
    expected_revision=7,
)
payload = command.SerializeToString()
```

Version 1 supports domain schema/model installation and deletion, concept/property/role definition
edits, node creation/deletion, set/unset property, child movement, reference edits, bundle references,
explicit evidence promotion, and undo/redo. Unsupported command families fail explicitly. Programming
commands, transactions and the complete existing event payloads remain available through JSON
automation. Binary command receipts carry the accepted revision, affected IDs, undo group and event
metadata, or a rejection code and message. They intentionally do not replace the full event/history API.

Resource, computation and evidence adapters are public typed exchange helpers in `protocol.resources`,
`protocol.computation` and `protocol.evidence`. These DTO codecs do not themselves execute a backend
or import a resource; the existing capability service remains responsible for those actions.
`ComputationPlan` references an immutable terminal model resource and carries its representation,
transformation sequence, origin map and input digest. No programming AST is copied into the wire
schema. Sessions explicitly advertise whether cancellation is supported; the existence of a portable
cancel-request message does not imply that a backend can interrupt an active computation.

The draft host/worker process path uses `protocol.worker` byte adapters. Worker
requests compare an inert expected backend definition against trusted installed
composition. Resource transfers and proposed final evidence use a receipt/verification
handshake before terminal admission. No request chooses an import or executable.
Editor preparation variants additionally carry one canonical target and optional
typed Python invocation literals. Their closed list/tuple/dictionary/null vocabulary
preserves the existing invocation contract; it does not extend `CanonicalValue`.
The worker performs signature binding and returns a content-addressed emitted-file
artifact with checked runtime binding metadata. See
[sealed publications](COMPUTATION_PUBLICATIONS.md) for draft status and admission order.

P5 adds the explicitly versioned `PreviewEvent` at worker-event field 19. It names
the attempt/input identity, exact registered preview interpretation and bounded
typed values. It is coalescible runtime presentation, not an observation or evidence
record. Old request/evidence fields and envelope limits are unchanged. Composite
resources use the same child transfer frames and root publication handshake; no
array history is embedded in a protobuf event. See
[TIME_AND_CHECKPOINTS.md](TIME_AND_CHECKPOINTS.md) for temporal and restart ownership.

## Reproducible generation and evolution

Install the development dependencies and run:

```text
python tools/generate_protocol.py
python tools/generate_protocol.py --check
```

The compiler is pinned to `grpcio-tools==1.78.0`, which emits Python protobuf 6.31.1 code; runtime
`protobuf==6.33.5` is pinned within its supported compatibility range. The repository includes the
generated Python and typing stubs, so opening a project requires no compiler. See the
[protobuf runtime compatibility guarantee](https://protobuf.dev/support/cross-version-runtime-guarantee/).

Field numbers are permanent. Reserve removed field numbers and names; never recycle them. Changes
that a version 1 receiver cannot preserve require an explicitly supported contract revision. Native
project format revisions, command envelope versions and protobuf schema versions are independent.
Legacy native scalar values and the default command envelope version remain compatible.

Golden wire fixtures test stable field tags and scalar presence; DTO tests exercise schema/object,
resource, computation, evidence and command round trips. Authentication tests send real binary
commands through the existing WebSocket authority and verify grants, conflicts, idempotency and undo.

Protobuf deterministic serialization is useful for repeatable fixtures within the pinned toolchain.
It is **not** a canonical content hash across implementations or compiler releases; resource/evidence
identity uses the application's own content contracts. See
[protobuf serialization is not canonical](https://protobuf.dev/programming-guides/serialization-not-canonical/).
