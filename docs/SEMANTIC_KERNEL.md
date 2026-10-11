# Semantic kernel and visual projections

P5 adds no physical object kinds to this kernel. Fields, grids, diffusion problems,
initial/boundary conditions and time policies are ordinary domain intentions with
stable IDs. Their numerical vectors and histories are immutable resources, not
semantic nodes per sample. A publication's original IDs use the existing runtime
overlay; provisional previews do not change accepted selection. Historical views
are pinned to their resource, input and editor attachment, so equal local revision
numbers on different branches cannot alias. An independent probe owns its own
intention and names the original field through retained resource provenance.

Public contract references and project semantic identities have different scopes.
Schema defaults, choices, dimensional constraints and reference vocabulary data
participate in publication dependency closure through their typed public references.
The resulting manifest records exact resolved contracts; it does not rename nodes,
models, semantic selections or authored concept groupings. Immutable dimension-basis
IDs resolve uniquely within the declared closure.

Resource interpretation is likewise explicit: a stored descriptor may preserve an
unknown logical-type ID/version, while computation admission requires its published
provider. This validation adds no canonical store or authority and leaves runtime
origin mapping attached to the same project semantic IDs.

P3 does not add electrical or solver object kinds to this index. Nets, terminals,
components, mathematical symbols, relations and requests are domain objects.
The DC transformation maps every generated equation occurrence and variable to
its authored origins. Real computation observations follow that map into the
existing revision-pinned runtime history and applicable graph/table/form views.
A filtered notation need not contain the last observed object; earlier observations
remain inspectable in the same history. Retained comparison performs explicit
navigation by origin ID, not attachment of historical runtime to another branch.

The universal boundary adds typed bounded values, resources and immutable evidence,
not physics or mathematics object kinds. Foundation schema definitions and instances
use the existing DOMAIN/CONCEPT_DEFINITION/DOMAIN_OBJECT index kinds. Reference values
do not create containment-owned semantic objects. Evidence and ephemeral sessions
retain original semantic IDs through OriginMap; the existing selection and notation
overlay plane decorates them at their pinned revision. Canonical presentation policy
remains distinct from definition even though both use one authority. See
[Universal workbench](UNIVERSAL_WORKBENCH.md).

Publication ownership does not alter indexed project object IDs. Unit systems,
unit definitions and dimension factors use ordinary foundation domain concepts.
Live backend progress and observations use the existing runtime session and
sequence plane; observed objects retain their generated and original identities.
Streams have explicit capability declarations and bounded event envelopes before
publication. Installing reference vocabulary is one normal undoable authority
transaction, discoverable through the workbench's **Add vocabulary** action.

Project-authored languages contribute distinct language, notation, validation-rule,
transformation and template identities to the derived index. Their expression and
symbol identities remain addressable without conflating them with authored
`SemanticConcept` groupings. Search and shared selection navigate these objects into
the structured language editor. Notation/query/template data remains canonical in
`DomainWorkspace.language_definitions`; compiled behavior is revision-derived.
See [Domain language](DOMAIN_LANGUAGE.md).

Composed notation queries can join intentional nodes from multiple workspace schemas
using authored or derived semantic relationships. `ProjectKernel.notation` supplies
the same indexed relations used by other lenses. Every field keeps its actual model,
node, property and revision; repeated glyph occurrences have distinct presentation
IDs while retaining shared canonical semantic IDs. Mathematical and spatial layouts
therefore reuse selection, direct edits and revision-pinned runtime decoration.

Readable notation/query editors parse directly into owned typed definitions. Their
text and previews do not create another semantic representation. Intermediate-domain
transformation results are build values: their composed origins lead back to indexed
authored intentions, rather than installing another canonical domain model.

## What is canonical

One `ProjectAuthority` owns one immutable project revision. `Project.program_model` is
the executable write truth for Python modules, classes, declarations, entrypoint setup,
functions, parameters, stable symbols, every supported statement and nested structure,
and their expressions. Modules and classes own ordered declaration bodies; a
`ProgramFunctionReference` gives each function one declaration position while its
mature structured body remains in the function table. DRAKON is an editor projection
over that complete model. Removing its view leaves validation, indexing, generation,
dependency analysis, and canonical commands available.

The programming-domain provider advertises modules and the optional entrypoint as
its roots, including module-only libraries. Its object index includes classes,
ordered declarations, function contents, and complete expression/type-parameter
syntax identities. Module and class renames do not change any of these identities.

`domain.program` is independent of DRAKON and application modules. Shared semantic
enums live in `domain.program_kinds`; textual signature DTOs live in
`domain.program_signatures`. `application.drakon_program_adapter` owns explicit
import/promotion and DRAKON projection. Presentation bindings belong to
`domain.projection`, and initial project construction belongs to
`application.project_factory`. Editor gestures resolve semantic IDs and submit
canonical edit intents through the program command feature; projections refresh
from accepted canonical state.

`ProjectKernel.queries` builds a deterministic `SemanticProgram` read model from the
canonical revision and caches it until the next authority event. Feature code should
not inspect the tagged document union. Executable objects are indexed directly
from `ProgramModel`; the read model adds ownership, typed expression depth,
relationships, and presentation glyphs without becoming another writer. DRAKON is
consulted only for presentation glyphs.

Module and class semantic IDs come directly from canonical declarations, not from
module paths or class names. Rename changes the indexed label and generated spelling;
shared selection and authored relationships retain their targets. Imports, assignments,
type aliases, source units, class bases/decorators and callable/class type-parameter
syntax are indexed from their canonical trees. Structural module/class changes use a
full read-model rebuild; function-local edits retain the incremental path and its
full-build oracle. Runtime preferences in `PythonRuntimeSettings` contain no executable source.

The Python Project workspace edits declaration identities through the same authority as
the signature inspector, semantic text, search replacement, SDK and automation. Its
transient import/constant/alias form rows are not persisted. Source-unit editing targets
one canonical expression identity. The explorer enumerates canonical functions and
classes, including functions without DRAKON documents.

Authored package initializers are canonical module objects, distinguished by
MODULE/PACKAGE kind. Their project IDs also own nested modules in the semantic index;
the index does not invent a second package object for the same initializer. Runtime
locations include emitted file identity as well as line/column, so equal line numbers
in different modules resolve to their own semantic spans and original domain IDs.

The semantic program includes package/module/class/function ownership, executable
operations and structures, parsed expression nodes, scoped symbols, calls,
control-flow branches, reads, writes, definitions, references, transitions, views,
glyphs, annotations, anchors, author-named concepts, and author-owned explanatory
relationships.

`ProgramExpression.tree` is the only persisted canonical expression value. It is a
complete, renderable Python syntax tree; `ProgramExpression.source` is a computed read
view kept for consumers that need normalized text. Invalid or incomplete Python becomes
`UnparsedPythonExpression`, whose leaf text is the sole truth. It is saveable and
editable, but produces `PROGRAM_INCOMPLETE_EXPRESSION` and makes the affected build
scope non-buildable. Indexing, stable-symbol rename, rebinding, and current-format decoding
walk complete trees and never reparse derived source text.

Every accepted revision also carries an identity-keyed `SemanticDelta`: added, removed,
and changed objects and relations. The kernel constructs the new read model once,
reuses it for all events in the transaction, rebases shared selection, and publishes
the same delta to every feature listener.

## Stable query surface

The read model also indexes `DOMAIN_SCHEMA`, `CONCEPT_DEFINITION`,
`PROPERTY_DEFINITION`, `ROLE_DEFINITION`, `DOMAIN`, and `INTENTION`. Schema members and
intentional instances keep their canonical IDs. Containment and reference relations
retain identity through display-name edits; cross-domain authored relationships use
the existing relationship mechanism. Domain edits invalidate the revision-derived
index, not any canonical program copy.

`ProjectKernel.workbench()` discovers domain providers, schemas, versioned bundles,
transformations, generators, and diagnostics. `notations(model_id)` lists registered
and schema-derived notations; `notation(model_id, notation_id)` compiles current objects
with explicit command bindings and the shared runtime overlay. RPC exposes these as
`query.workbench`, `query.notations`, and `query.notation`; capabilities include
`analysis.workbench`, `view.notation`, and `execution.workbench.trace`.

Domain commands use the same command envelope and `command.execute`/transaction,
history, and event APIs. A returned notation edit binding includes its source revision,
node ID, property/role ID, and edit kind. Clients submit its semantic command with that
expected revision; they do not send a modified rendered document.

Feature slices and integrations use:

```python
queries.semantic_object(object_id)
queries.semantic_relation(relation_id)
queries.children(namespace_id)
queries.callers(function_id)
queries.references(symbol_id)
queries.control_flow(function_id)
queries.data_dependencies(operation_id)
queries.views_for(semantic_id)
queries.projection("architecture", root=None)
queries.projection_definitions()
queries.compose_projection(definition)
queries.resolved_document(document_id)
```

The matching JSON-RPC methods are prefixed with `query.`. These DTOs are disposable;
they carry the project revision that produced them.

## Semantic glyph versus annotation

- Every DRAKON icon intrinsically represents its typed operation.
- A mind-map topic or freeform shape with no anchor is an annotation.
- A topic or shape with `semantic_id` is a glyph for that semantic object.
- A mind-map cross-link or freeform connector with `semantic_relation_id` is a glyph
  for that relationship.

`view.set_anchor` is an ordinary typed command. It validates target kind, journals,
emits `view.anchor_changed`, participates in transactions, and is undoable. In the GUI,
select code in DRAKON or Code Visualizer, return to the topic/shape, and choose
**Link … to Selected Code**. Choose **Make Annotation Only** to remove the link.

## Shared selection

Selection contains only project identity, revision, semantic IDs, a primary ID, source,
and optional execution-session ID. Selecting an operation can simultaneously highlight
its DRAKON icon, generated source, data-flow dependencies, anchored topic/shape, and
runtime focus. The publishing feature does not know who is listening.

Automation `service.presence` publishes through this same service, so a human and an
LLM can point at the same semantic object while both continue to use their native
interfaces.

## Capabilities

`service.operations` discovers registered substantial operations. Built-ins include
semantic/data analysis, all visual projections, runtime inspection, and Python
generation. Permission grants such as `read`, `edit`, and `execute` remain separate
from operation descriptors. `capability.invoke` executes a descriptor by ID with a
JSON input object, removing per-capability branches from the automation dispatcher.

## Runtime identity

Debug and recorded-trace events carry `execution_session_id`, `project_revision`, and
`artifact_revision`. State includes a reconstructed `RuntimeGraph` with frame bindings
and identity-preserving values. Each binding includes a stable semantic symbol ID and
frame ID. Exact dict/list/tuple/set/frozenset containers and safe instance fields are
expanded within fixed limits. Shared references and cycles point to one value ID.
Compatibility `locals` strings are not the data model.

Use `runtime.active`, `runtime.sessions`, or `runtime.history` over JSON-RPC to inspect
the same bounded state visible in the Runtime Values timeline. List, queue, heap,
graph, matrix, tree, mapping, tensor, DataFrame, and generic adapters are
presentation-only views over
the same value identities. History is retained as bounded checkpoint/delta records and
reconstructed lazily, rather than storing hundreds of complete graphs. Runtime state is
ephemeral and is never
written to `project.json` or generated artifacts. A `RuntimeOverlayContext` can be
applied to architecture, calls, control, data, DRAKON, saved, mind-map, or freeform
projections. It decorates the active node and route, changed symbols, and bounded
runtime structures while keeping the underlying projection reusable.

P4's managed Python publisher attaches generated-file call sites and authored
operation IDs to sealed typed resources. Independent CAD consumers retain their
exact input references and producing origins alongside their own authored intent
IDs. A display mesh's face groups are local to one exact BREP reference; they are
not new global semantic identities. Picking resolves the available authored IDs
through the existing selection service. Historical results remain inspectable,
but are not highlighted as current authoring merely because revision numbers match.

Artifact inspection and rendering do not submit semantic commands. Creating a
consumer or explicitly promoting a retained artifact does: those operations pass
through the same authority and frozen-definition admission boundary as other edits.
See [the CAD artifact workflow](CAD_ARTIFACT_WORKFLOW.md).

See [Semantic projection language](PROJECTION_LANGUAGE.md) for authored concepts,
relationships, lens composition, and editable mind-map/canvas materialization. See
[Runtime time and semantic text](RUNTIME_AND_SEMANTIC_TEXT.md) for execution history
and the command-backed text surface.
