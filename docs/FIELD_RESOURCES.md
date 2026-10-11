# Field resources and exact interpretation

Implemented and verified in the P5 Windows qualification, 13 September 2026.
Acceptance review remains open. See the [acceptance map](P5_ACCEPTANCE_MAP.md)
and [structured receipt](receipts/transition-p5.json), including the explicit
restricted-host heartbeat profile and platform limits.

Authored field, grid, space/frame and problem intentions live in DomainWorkspace.
Prepared arrays, sample histories and numerical restart state are disposable or
immutable resources. They never become a second editable field model.

The foundation.fields/1 public contracts are independently versioned logical
types: float64_array, uniform_support, scalar_interpretation, series and
scalar_preview. Their IDs are qualified; versions are separate. Space@2 uses the
explicit algebra_schema identity and depends on math@2. Space@1 remains exact.

A scalar interpretation names its authored field, component, exact unit and
quantity kind, support, node association, float64 dtype and all-finite policy.
Uniform support names the authored space/frame/axis and the exact coordinate
resource, origin, positive spacing and node count. The current reader supports
one-dimensional Cartesian data; other interpretations fail explicitly.

Each numeric chunk is an immutable NumPy 1.0 file of at most 4 MiB. It has no
object dtype or pickle data. A sample row holds accepted step, physical time and
one scalar per node; its closed index supplies the interpretation and units.
Descriptor and header shape/dtype/size must agree, including exact file length.
The reader uses a read-only mapping or a read-only bounded array.

Array units must also agree with their role. A coordinate array may leave its
tensor-level unit absent because the support defines it, or declare that exact
support unit. A conflicting unit is rejected without implicit conversion. Sample
matrices mix step, time and field columns; they cannot claim one tensor-level unit
for the whole matrix. Viewer slices, probes and checkpoint prefix validation use
the same bounded `FieldHistory` chunk reader and enforce these rules alike.

A series page contains at most 256 typed chunk entries, one interpretation and
source identity, and optionally an exact prefix and its last accepted position.
Pages are at most 64 KiB. Prefixes must agree in source, interpretation and physical
coverage. There are no mutable latest files, implicit interpolation or clamping.

ResourceInterpretation is trusted static bundle implementation code. Its exact
logical type selects a bounded decoder returning ResourceDependency records.
DomainExtensionRegistry.resource_closure verifies hashes, identities, child
type/size claims, cycles, and a 1,024-resource/64-depth/2 MiB metadata boundary.
Known opaque types remain leaves; missing public contracts are diagnosed and
their stored data remains untouched. Registration rejects duplicate interpreters.

The same closure is used in preparation, portable-plan admission, freeze capture,
worker output admission and session recovery copying. Persistence accepts resolved
references or an explicitly supplied read-only resolver; the CAS store does not
import field semantics. Callers copying composite resources must supply that
resolver, as ProjectSession does.

A ProducedResource can stage a flat bounded set of children. The existing host
seals and claims the interpreted closure before acknowledging its one root
publication. Unreferenced children and incomplete/unsolicited transfers fail.
Children do not each consume an EvidencePublication receipt. Within one worker
phase already transferred children are reused; all original transfer and receipt
budgets remain. An orphan file after a failure is not an admitted publication.

Backends opt into file-backed input resolution through their static registration;
old backends retain their existing bytes/file expectations. FieldHistory decodes
metadata first, opens numeric chunks on demand, and keeps a bounded LRU (maximum
64 MiB). A displayed slice owns a small immutable vector, so old view frames do
not keep evicted chunk mappings alive. Hashing/admission and view preparation
belong off the GUI thread.

PreviewEvent is a separate versioned worker event. A registered PreviewContract
admits bounded named CanonicalValues. The scalar interpretation carries one
accepted/trial pair with shared sampled node indices, at most 256 values per
state. Accepted physical time, candidate time and shared transport sequence are
distinct. Runtime keeps only the latest preview; no preview becomes an evidence
observation, publication receipt or accepted history entry.

Focused executable coverage: test_field_contracts.py, test_field_preview.py and
test_field_resources.py, including actual worker transfer, fresh-host copied
closure consumption and portable replay. Old publication codec goldens remain
unchanged; field metadata and preview bytes have their own v1 golden fixture.

The diffusion checkpoint includes exact numerical-library/method identity and a
scientific definition compatibility digest. That digest remains stable across a
resume; the computation request's complete input digest changes when a checkpoint
is selected. Both are retained for their different purposes. The prefix contains
only scheduled accepted samples; restart verifies every retained time against the
fixed integration/sample policy and continues without a duplicate boundary sample.

The field view owns a separate exact history cursor and a coherent trial pane.
Its optional overview contains at most 64 exact sampled times and 512 spatial
columns. It is a reduced presentation, with no temporal interpolation. The full
immutable field remains available to an independently authored Probe and its
ordinary computation backend. The production proof now makes the producer's
original storage location unavailable before executing that consumer and tests a
fresh-host plus portable numerical restart. See [the workflow](DIFFUSION_FIELD_WORKFLOW.md).
