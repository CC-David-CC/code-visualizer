# Public contract identity and ownership, version 1

Project object identity and public vocabulary identity are separate contracts.
An equation, node, model, motor, wire, property definition or schema object keeps
its opaque project-global identity through rename, move, persistence and undo.
No name/path/notation is substituted for that identity. A schema's **namespace**
is its published representation contract; its project object ID is not a namespace.

Public bundle, schema namespace, backend, representation, transformation,
unit-definition, dimension-basis and resource logical-type names use the common
`domain.identifiers` grammar. Examples are `org.example.control.pid`,
`com.example.solver.fem`, `foundation.math`, and `foundation.units.si:meter`.
The namespace contains at least two lowercase ASCII dot-separated segments;
segments may contain digits, `_` and `-`. An optional colon introduces one
case-sensitive ASCII member name (letters/digits/underscore/dot/hyphen). Names
are at most 255 bytes. There is no trimming, case folding, Unicode normalization,
display-name alias resolution or embedded `@version`. Version is a separate
bounded, case-sensitive contract field. Dimension bases are immutable identities;
a change of basis meaning needs a new identity, not a reused spelling.

`NamespaceOwnership` contains explicit host-controlled `NamespaceGrant` records.
A publication declares its owner using `BundlePublication`; registration verifies
every exported contract against those grants. Conflicting/overlapping grants,
duplicate contracts, and attempts to claim another publisher's namespace fail
before registration mutates anything. Versions of a bundle share its namespace
owner. A registered namespace cannot be reclaimed by omitting publication metadata.

This does not verify domain-name registration or establish trust from a string.
Reverse DNS is recommended for third parties because it provides an existing
ownership convention. The application distributor must verify a publisher and
grant its prefix at the static composition boundary. Project files and portable
manifests cannot create grants or load code. First-party reserved prefixes are
`foundation`, `code_visualizer`, and `org.codevisualizer`, owned by
`org.codevisualizer`. Different publishers need disjoint explicitly granted
prefixes; namespace delegation is an explicit host configuration change.

## Drafts and publication

Private in-process registrations and project-authored languages can retain local
experimental names. They have no public publication manifest. This preserves
existing authored data and local tests without declaring strings such as `spice`,
`meter`, or `field` globally owned. `publication_manifest(registry, id, version)`
requires a published bundle, its exact dependency closure, and public dependencies.
The production first-party registry uses publication metadata and grants. A third
party shipping an extension must do the same; passing local test registration is
not publication approval.

Public contract metadata records contract **kind**, identity and version. Defining
a unit does not register a backend with the same name. Sources and targets refer
to existing representation contracts; an implementation cannot acquire ownership
merely by consuming one. The same schema namespace/version cannot be implemented
under two differently named schema objects in a public registry. Schema bodies
remain checked against their exact immutable bundle definitions on project load.

Bundles can contribute ordinary immutable `reference_models` and exact
`required_bundles`. They do not acquire a second canonical storage model. Installing
a bundle submits ordinary schema/model/bundle-reference commands in one authority
transaction. Altering installed vocabulary under its reserved model identity gives
an explicit diagnostic. Missing dependencies and dependency cycles block publication
or installation; data remains readable. Project-authored variants use new object
and public contract identities rather than impersonating a released vocabulary.

`foundation.units.si@1` uses this boundary for a single shared SI basis/unit
vocabulary. Its dimensional and conversion checks belong to the foundation
extension, not the identifier grammar or CanonicalValue.

## Reference closure is part of publication

`derive_public_contract_references(bundle)` walks inert typed definitions, including
schema defaults and choices, dimensional value constraints, reference-model values,
notations, backend definitions and transformation/generator representations. It does
not inspect callback bodies or interpret arbitrary strings as public identities.
Opaque schema object references resolve through their declared schema to its public
namespace and version. Project node and model identities remain project identities.

Every discovered reference must be supplied by the bundle itself or its **exact
declared transitive dependency closure**. Merely registering another provider in the
host is insufficient. Each dependency must satisfy its own closure, so a dependency
cannot borrow a contract from its consumer. Publication never invents a dependency
or selects a provider by import order. Missing contracts, wrong versions and ambiguous
schema/basis references are explicit failures.

`ContractReference` distinguishes use from definition. Most references require an
exact version. A dimension basis can omit its version because its identity has
immutable meaning: exactly one matching basis definition must exist in the closure.
Zero matches fail; multiple versions fail as ambiguous. A new physical meaning needs
a new basis ID. The portable publication manifest records the **resolved exact
ContractDefinition references**, retaining a reproducible proof of this resolution.

## Resource logical types

`DataResource.logical_type` is absent or a `ResourceLogicalTypeReference(id, version)`.
It cannot contain a display label, a local string, or an embedded `@version`.
`code_visualizer.computation@2` publishes the backend-independent
`code_visualizer.computation.terminal@2` logical-type contract. The math bundle
publishes `foundation.math.tensor@1`; both use separate ID/version fields.

Storage and raw archival transfer preserve unknown typed metadata. Computation
admission resolves a logical-type reference to a registered published contract and
validates its supplier's publication closure. This applies to inputs, the terminal
resource, backend outputs, artifact references and live/final observations. Worker
admission also checks cached resources. Missing implementations block interpretation
without deleting stored bytes or altering authored state.
