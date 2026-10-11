# Native project format

P4 keeps project format revision 11. CAD consumer schemas/models and their exact
resource references use the existing DomainWorkspace encoding. Geometry/mesh bytes
are external immutable resources, never fields in project.json. Optional named
computation inputs/outputs use request version 2 (including the portable request
message); requests without bindings retain their historical encoding exactly.
Promotion journals a typed `domain.model.promote_artifact` command and ordinary
undo inverse. It does not write generated ProgramModel or geometry into source.

P5 retains this same native authoring format. Field, grid, frame and diffusion
policy instances are ordinary schema-driven domain models. Arrays, series pages
and numerical checkpoints are independently versioned content-addressed resources;
their bytes do not enter project.json. A Probe stores an explicit root resource
reference and exact sample/node/time selection as its authored input. PreviewEvent
is an additive versioned worker message and is never persisted as canonical input
or durable evidence. Explicit Resume uses the existing request configuration and
retained parent-attempt/publication binding. See [field contracts](FIELD_RESOURCES.md).

## Development format revision

The native writer emits `format_revision: 11`. The decoder accepts revisions 4 through 11.
Public contract ownership, backend capabilities and chunk transport do not change
this authoring format. Namespace grants and implementation registrations belong
to host composition; publication manifests use the identity protocol family.
Installed reference vocabularies use the existing schemas/models/bundle-reference
fields and normal command journal. SI vocabulary contents remain ordinary domain
objects, with immutable released definitions checked by the registered bundle.
Evidence metadata now obeys the shared 2 MiB native/wire envelope; resource bytes
remain external. See [Contract identities](CONTRACT_IDENTITIES.md).

P3 keeps this container revision. New exact rational dimension powers use a nested
version-2 encoding; all integral vectors retain the existing version-1 bytes,
including historical evidence and frozen-input hashes. `foundation.math@2` is a
separate schema/backend extension, not an automatic migration of math@1 indexed
assignment evaluation. A project installs one exact version of a schema identity;
ambiguous selection requires an explicit version. Unit products, equations, solve
requests and DC topology are ordinary schema instances. Solver outputs are never
saved into `domain_workspace`. See [canonical values](CANONICAL_VALUES.md).

Revision 4 is upgraded at the load boundary: already canonical fields retain their
identities and semantics, while the old placeholders are replaced using their
matching DRAKON payload. Missing or mismatched legacy payload is rejected explicitly.
The same legacy snapshot always upgrades to the same expression identities. Saving
an upgraded project writes revision 11. Revision 5 acquires an empty domain workspace
without changing any canonical programming identity. Revisions before 4 and legacy `.drn` files are
not supported.

Revision 7 adds `domain_workspace.language_definitions`: version-pinned, typed
notation definitions, validator queries, and transformation templates. Revision 6
acquires an empty language collection. The decoder uses a closed host record list
and checks every tagged value against its declared slot type; project data cannot
select Python imports or callbacks. Structural/text budgets bound these definitions.
Unsupported grammar versions survive loading with diagnostics that block dependent
builds. Holes are explicit saveable authoring states. Compiled rules and generated
ProgramModel contributions are never persisted. See [Domain language](DOMAIN_LANGUAGE.md).

Revision 8 stores configured invocation arguments as typed literal positional and
keyword values, with tagged list/tuple/dictionary contents. Earlier raw argument text
is parsed once at load: supported literals become structured values; names, calls,
and other expressions survive as explicit unresolved configuration that blocks
execution. Existing journal command/inverse payloads migrate at the same boundary,
including transactions, preserving undo/redo. Current commands and snapshots reject
raw argument strings. No decoder evaluates argument text or resolves module names.

Revision 9 admits the closed CanonicalValue version 1 algebra and property value
constraints. Existing scalar values retain their representation; complex, quantity,
small tensor and resource references have explicit versioned tags. Dimension, dtype
and shape constraints are schema data. Resources and evidence live beside author
state, not in generated ProgramModel or projection bodies. See
[Canonical values](CANONICAL_VALUES.md), [Resources and evidence](RESOURCES_AND_EVIDENCE.md)
and [Protobuf boundaries](PROTOBUF_BOUNDARIES.md). Protobuf wire versions remain
independent of this native JSON format.

Revision 10 completes native Python ownership. `program_model.modules` contains
ordered declaration bodies, including typed imports, assignments, aliases, module
statements, classes, and function references. Classes own their ordered bodies,
typed arguments/decorators/type parameters, and docstrings. A function occurs once
in the mature function table and has exactly one owning reference; module and class
names are derived from ownership rather than copied into each function. Package
identity and the optional typed entrypoint, literal arguments and startup body
belong to `ProgramModel`. An empty model has no fabricated entrypoint identity.

Revision 11 names the remaining runtime-only value `PythonRuntimeSettings` and its
project field `runtime_settings`. The old `ModuleSetup` Python type and
`Project.module_setup` field are removed. Revisions 4-10 convert the old persisted
key once at load, after any earlier executable-ownership migration. A snapshot
containing both keys is rejected, and current snapshots reject the old key alone.
The `python.configure_runtime` command still carries the settings record directly;
its command identity and existing durable undo/redo payloads are unchanged.

Revision 11 also requires `kind: "module" | "package"` on each canonical
`ProgramModule`. A package owns its initializer body. A package path of `""`
identifies the project's configured root package; `"tools"` identifies its nested
package. Ordinary modules retain nonempty leaf paths. Native revisions through 10
acquire `kind: "module"` without changing stored IDs or declaration order. Their
durable `program.configure`, `program.module.put`, and function-restoration headers
acquire the same default, including operations inside transactions. A missing kind
is rejected by current native and command codecs.

Computation terminal format 2 keeps its existing public identity. Its additive
module discriminator defaults to ordinary-module semantics when absent in an older
terminal. The loader verifies the original resource bytes and content hash first;
defaulting for typed decoding never rewrites immutable artifacts or provenance.
The strict typed round-trip check still rejects unrecognized module fields.

The revision 4–9 importer preserves all previously canonical function, symbol and
expression identities. Formerly anonymous modules/classes/declarations acquire
deterministic identities once, then retain them across renames. Legacy source is
parsed into the existing typed Python AST, with incomplete source represented
explicitly. Ordered imports, constants, aliases, helper/before suites, top-level
functions, grouped method classes and after suites retain their previous execution
order. Unconfigured function module paths acquire the same empty module that old
Python lowering already supplied. There is no retained source mirror or legacy
executable setup in a current snapshot.

Module/class promotion retains the old semantic index identities exactly:
`module:app.main` and `class:module:app.main:Worker`, for example. Existing concept
members, lens scopes, mind-map topics and freeform anchors therefore still resolve.
These IDs become stored identities; later module/class renames do not regenerate
them. A collision with existing canonical meaning is an explicit decoding error.

Ordinary Python type comments remain in their typed AST fields and are not also
stored as standalone notes. Line-bound `# type: ignore` directives currently remain
explicit unsupported source values: the entire submitted suite is preserved in one
`UnparsedPythonExpression`, with a diagnostic blocking generation. The editor does
not silently move suppression directives to another statement or discard them.
Supporting these directives requires canonical directive anchors and a renderer
that preserves their scope across layout changes; source line numbers alone do not
provide that contract.

Legacy journal forward/inverse operations migrate with their snapshots, including
nested transactions. Old setup replacement becomes the current typed program
configuration and runtime configuration commands. Live command decoding does not
accept the legacy setup operation. Expanded transaction contents are flattened into
one atomic current transaction. Historical module moves reconstruct only the typed
program ownership header, including formerly implicit classes; they preserve
function/domain tables and acquire conservative project-level history conflict
scope. An explicit first-party `code_visualizer.computation@1` reference upgrades
to version 2 with its journal put/delete operations; unrelated extension references
remain unchanged. Released immutable computation terminal resources
use their own format version; migrating author state never rewrites such resources.

Authored language grammar version 2 adds composed visual/textual notation trees and
schema-targeted domain templates. Grammar version 1 remains readable with its
original capabilities; a missing legacy grammar tag means version 1. Intermediate
model results, notation canvas items and expression-editor source are not persisted
beside their canonical typed definitions.

The native codecs are `persistence.decoding` and `persistence.serialization`.
`project_from_data`, `project_from_json`, `project_to_data`, and
`normalized_project_json` are imported from those modules. Decoding invokes
`application.drakon_program_adapter` for legacy conversion and for reconstruction of
current DRAKON projections. These persistence operations are outside the canonical
domain; `domain.program` has no storage or editor dependency.

## Snapshot envelope

A normalized project snapshot contains `format_revision`, stable `project_id`, title,
description, monotonic `revision`, `runtime_settings`, `program_model`, `domain_workspace`, ordered `documents`, authored
`concepts`, `semantic_relations`, saved `projection_definitions`, managed assets, shape
packs, and optional namespaced extension data.

`domain_workspace` contains explicit domain schemas, version-pinned models, canonical
intentional nodes and inert bundle references. Every node occurs once in a flat node
table; roots and child/reference roles contain stable IDs. There is no stored parent
mirror and no stored transformed `ProgramModel`. Missing extension implementations
produce build diagnostics while the schema and all instance data remain loadable.
See [Domain schema](DOMAIN_SCHEMA.md) for the strict structural versus incomplete
editing-state boundary. Revision 6 prevents earlier readers from silently dropping
these new canonical meanings.

`program_model` is required and owns directly authored programming meaning. Domain
intentions own their higher-level meaning separately; their transformed program output
is derived and is not written into this field. Top-level
`drakon_views` is also required and contains presentation bindings from DRAKON
documents to canonical functions. Revision-5 through revision-8 decoding derives DRAKON editor values from
the canonical model; legacy upgrades remain at the decoder boundary. A function may exist without any visual projection, and deleting a
view does not delete its canonical behavior. `program.function.delete` is the explicit
executable-lifetime operation.

`program_model` stores functions, parameters, sequences, all supported statement
types and owned structures, role-tagged expressions, and rename-stable symbols. Every valid expression
stores one complete identity-bearing `tree`; rendered Python source is derived and is
never persisted beside that tree. `UnparsedPythonExpression` is the explicit
incomplete editing state and owns its text as one value. It may be saved, but blocks
generation, run, trace, and debug until repaired.

A canonical statement never refers to an editor payload for its meaning. Action
blocks, match patterns, argument/name lists, and deletion targets also use typed
trees. The current decoder rejects legacy placeholder tags and executable fields
(`body`, `header`, `end`) inside persisted DRAKON presentations.

Each document has a `kind` tag and kind-specific payload. DRAKON, mind-map, and
free-form payloads do not share a generic node/edge structure. Mind-map topics and
freeform shapes may have a `semantic_id`; cross-links and connectors may have a
`semantic_relation_id`. Missing anchors mean annotation only. An anchored glyph may
set `label_override`; null means derive its current semantic label.

A materialized mind map or freeform document may contain `live_projection`, a complete
persisted `ProjectionDefinition` including semantic compression controls such as
`node_limit`, `expanded_ids`, and `focus_ids`. Geometry, style, notes, collapse state,
and manual annotations remain presentation state and merge with freshly derived
semantic labels at read time.

A persisted DRAKON document contains `id`, `kind`, `title`, `description`, and
`extensions`. Its `drakon_views` binding supplies the function, header, and end IDs.
The binding value type, `DrakonViewDefinition`, lives in `domain.projection`.
At runtime its Header, root Sequence, End, and atoms are derived from the canonical
function. Standalone DRAKON command/clipboard payloads still carry editor values;
the authority translates accepted edits into canonical changes before commit.

`runtime_settings` contains only named run profiles and the active profile. Profiles
hold interpreter, working directory, process arguments and environment settings.
Current decoding rejects executable fields there. Executable package/module contents and entrypoint settings
occur only under `program_model`, independently of any DRAKON view.

Package initializer contents are authored `ProgramModule` bodies with package kind.
Generated empty parent initializers remain disposable scaffolding where no package
body was authored; they do not create a second canonical owner.

## Normalization

- UTF-8 JSON;
- lexicographically sorted keys;
- two-space indentation;
- one trailing newline;
- ordered semantic collections retained as arrays;
- opaque IDs retained across rename/save;
- no absolute implementation paths;
- no executable payload invoked during parsing.

## Directory layout

```text
<project>/
  project.json
  .code-visualizer/
    journal.jsonl
    snapshots/
      <zero-padded-revision>.json
  generated/
    generation.json
    generation-report.json
    project.source-map.json
    project.graph-index.json
    run_project.py
    run-config.json
    <package>/
      __init__.py
      <module>.py
      <sub-package>/
        __init__.py
        <nested-module>.py
    diagrams/
      <package>/
        <module>/
          <function>.svg
      design/
        <document-kind>/
          <diagram-id>.svg
```

`project.json` is atomically replaced. Every committed command first appends and
fsyncs a journal record containing the resulting exact semantic snapshot,
command/inverse metadata, actor, operation ID, affected IDs, and revision. Periodic
snapshots bound recovery work. A truncated final journal record is ignored; an invalid
interior record fails closed.

The strict decoder validates types, the exact development-format revision,
expression-node identity, stable symbol references, document/view bindings, the
canonical entrypoint, mind-map links, free-form connector references, finite geometry,
and DRAKON projection integrity without executing content. It reconstructs and
validates current expression trees without reparsing derived source.

Failed first-save attempts do not mutate the authority. A recovery copy is an
independent exact native snapshot and does not silently retarget the live session.

`generated/` is derived, never canonical. Generation builds and verifies a private
sibling directory, checks the source revision again, and atomically promotes it.
`generation.json` records the complete revision and SHA-256 for every non-manifest
artifact. Reveal and preview require a non-empty complete manifest; failed generation
leaves the preceding public directory untouched.

Runtime sessions are intentionally absent from this format. Their session ID,
project/artifact revisions, frames, bindings, and object graphs exist only in memory
and over bounded automation responses.

Resource descriptor revisions are independent of the native project revision.
Descriptors without a logical type preserve revision-1 encoding and identities;
revision 2 carries an optional-domain interpretation as a typed public ID/version
reference. Legacy nonempty string logical types fail explicitly, without rewriting
their stored files. Derived terminal/evidence fixtures are regenerated. Project
author state, stable object IDs and undo/history require no migration for this change.

Git stores the native project as ordinary versioned files; it adds no canonical model
or native format field. `<local-state>/git-checkpoint.json` records local Git HEAD and
the last successfully saved native file digest. Branch replacement or an external
same-HEAD file restore retains untracked journals and snapshots under
`<local-state>/git-history/<identity>/` and excluded from current recovery. Git-tracked
state is never moved. Decode/integrity validation must accept the selected working-tree
file before it replaces a live session; unresolved Git conflicts block admission.
See [Git workflow](GIT_WORKFLOW.md) for editor, headless and automation behavior.
