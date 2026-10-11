# Architecture

Static extension composition registers the complete schema, validator, backend
and resource contracts. Registering a catalog does not execute a solver or load
an unselected solver/history implementation. The axial solver and adaptive/gas
history consumers import those implementation modules inside their existing
execution operations. This retains ordinary typed Python calls and the same
worker/authority boundaries. No partial registry, new loader or project callback
is introduced. Fresh-process import tests protect this distinction, and real
backend/portable/restart tests exercise the deferred paths.

The application and programming domain are Python-native. ProgramModel owns Python
module/class declarations, imports, typed suites and entrypoint semantics; runtime
profiles remain separate configuration. General representations and computation
backends do not make ProgramModel a universal language AST. Authority commands and
pure domain operations remain Python calls. The P1 computation host supervises
preparation and execution across an actual process boundary; Protobuf carries inert
requests, events, resources and receipts at that boundary. It is not an internal
domain-object conversion mechanism. See [Canonical Python ownership](PYTHON_PROGRAM_MODEL.md)
for canonical ownership and [Python execution](PYTHON_EXECUTION.md) for the
revision-11 package/runtime-settings cutover.

P4 composes the existing equation backend, authored Python and independent CAD
consumers through explicit typed resources. Python backend version 2 publishes
BREP through its existing emitted-file child and the host's receipt/ACK boundary.
Mesh, measurement, boundary resolution and independent imported-solid translation
are normal CAD-domain computations. A new authority command promotes a selected
artifact to a fresh authored input; generated geometry remains immutable. The Qt
adapter reads bounded inert metadata/mesh data, while native topology runs in
owned backend processes. Git freeze captures named bindings and installed package
versions alongside the existing input closure. See [the workflow](CAD_ARTIFACT_WORKFLOW.md).

P5 uses those same boundaries for a bounded diffusion domain. Authored field,
grid, frame and numerical-policy intentions stay canonical. A registered Python
streaming backend derives vectors and emits immutable field-series/checkpoint
resources. Trusted registered resource interpretations expose transitive child
references for capture, transfer and retention; persistence owns bytes without
interpreting physics. Provisional preview events retain only the newest coherent
accepted/trial pair and never become evidence or authored state. The field viewer
reads chunks lazily, and explicit checkpoint Resume uses the existing Git input
and computation transaction. Receipt association precedes live publication and
the failure-evidence ledger. See [field contracts](FIELD_RESOURCES.md),
[the workflow](DIFFUSION_FIELD_WORKFLOW.md) and [P5 qualification](P5_ACCEPTANCE_MAP.md).

P3 adds two ordinary domain clients of the same computation path. The DC extension
derives math@2 equations from nets and component-owned terminals. Authored math@2
problems enter that representation directly. A checked compiler authorizes units
from the frozen vocabulary, constructs bounded linear algebra, and calls the
registered Python scientific backend. Neither client lowers through ProgramModel.
Matrices and solutions are derived resources; observations keep original domain
IDs. The host and Git freeze/recovery ordering remain the P1/P2 authority.
See [shared equations](SHARED_EQUATIONS.md) and [DC equations](DC_EQUATIONS.md).

## Purpose

Code Visualizer is built around one canonical project authority and a shared project
kernel. Program meaning remains independent of Qt, storage, transport, rendering,
generated Python, and runtime values.

## Current canonical architecture

The intentional workbench extends this architecture with schema-driven domains under
the same authority. `Project.program_model` retains specialized programming storage;
`Project.domain_workspace` owns generic schemas and intentional instances. They own
different authored meaning. Transformations compose a disposable ProgramModel only at
the build boundary. See [Intentional workbench](INTENTIONAL_WORKBENCH.md) for the gap
analysis, ownership rules, dependency graph, and phase evidence.

```text
ProjectAuthority
  +-- Definition plane: ProgramModel / schemas / domain intentions
  +-- Presentation policy: notation definitions / layout overrides
           |
           +--> SemanticProgram --> lenses / selection / editable notations
           |
           +--> transformations --> disposable terminal representation
                                            |
                                     registered backend
                                            |
                                  computation session/events
                                            |
                              immutable evidence + OriginMap
                                      |                 |
                              resource store      original semantic IDs
                                                   in every notation
```

The Python-program backend reuses existing ProgramModel lowering, generation,
invocation and trace/debug infrastructure. Python implements the application and
all current backend adapters; other domain backends consume exact
schema-scoped terminal models. Foundation math and space are ordinary versioned
domain extensions. The kernel owns no physical or mathematical concept enumeration.
Closed bounded values, resources, computation and evidence have language-neutral
Protobuf adapters; canonical project storage remains JSON. See
[Universal workbench](UNIVERSAL_WORKBENCH.md), [Canonical values](CANONICAL_VALUES.md),
[Resources and evidence](RESOURCES_AND_EVIDENCE.md) and
[Protobuf boundaries](PROTOBUF_BOUNDARIES.md).

Published contracts have qualified names and host-granted namespace ownership,
independent of opaque project object identities. Complete bundles can install
immutable reference vocabularies through the ordinary authority transaction path.
`foundation.units@1` and `foundation.units.si@1` provide common dimension bases,
unit definitions and explicit affine conversions as ordinary domain data. See
[Contract identities](CONTRACT_IDENTITIES.md) and [Foundation units](FOUNDATION_UNITS.md).

Publication derives public references throughout inert definitions and verifies each
supplier against exact declared dependency closures. Resource logical types are typed
ID/version references, including portable terminal payloads. Storage can preserve
unknown contracts; computation admission requires their published implementations.
The backend-independent computation bundle owns the portable terminal contract.
This ecosystem boundary precedes the separate module/class ownership migration
described in [Programming domain integration](PROGRAM_DOMAIN_INTEGRATION.md).

Backend API v1 declares capabilities and supplies one lifecycle for batch execution
and cooperative streaming. Live events and final evidence have the same 2 MiB
portable envelope limit; large series remain resources. Resources travel as bounded,
ordered, hash-verified chunks to the existing portable worker. Cancellation, event
delivery, evidence and original-object overlays retain the existing runtime authority.

## P1 computation lifetime and publications — accepted on the recorded Windows reference environment

P0 generated-name hygiene is accepted; P1 is implemented in the promoted repository.
The canonical ownership above is unchanged. A `ComputationService` owned by the
application host retains immutable submitted snapshots, execution attempts and store
handles. An editor kernel attaches its existing runtime registry and selection to
that host. Replacing or closing an editing attachment does not own or destroy a
running computation. Closing the host cancels active work and drains work already
admitted for final verification.

```text
ProjectAuthority snapshot + request
  -> ComputationService.submit -> immediate session identity
  -> supervised preparation -> terminal resource + optional Python file artifact
  -> supervised backend OR existing managed Python child
  -> resource verification -> sealed publication receipt -> producer ACK
  -> terminal proposal -> resource admission -> completion verification + normal exit
  -> final immutable evidence
```

The GUI observes immutable attempt snapshots; `execute_computation` waits for the
same submitted lifecycle in headless use. Production `advance_computation` waits
for admitted updates rather than invoking a backend on the caller's stack. The
GUI does not use that blocking wait. Progress/presentation notifications may
coalesce; publication receipts remain individually addressable and bounded.
Selection is delivered on the observing GUI or headless caller's thread.
The editor's single disposable preparation cache may reuse a default preview
for an explicit Run/Trace/Debug request only when the immutable author snapshot,
target and already-bound invocation arguments match exactly. Different arguments
still go through canonical signature binding in the worker; an override never
becomes the project's configured default.

Widgets wait for their preparation/observer phase rather than expecting a
synchronous render after publication. Stop during pending preparation rejects
late artifacts and immediately reports cancellation; running-child completion
continues through the existing execution adapter. Accepted preparation snapshots
notify condition waiters; SVG rendering imports are deferred to artifact export
rather than entering Python compilation through eager package imports.

Trusted host composition selects a registered process profile. Workers reconstruct
their registry from installed application code and verify the expected backend
contract. Requests contain no callbacks, imports or executable paths. Missing
strategies fail explicitly. Python preparation finishes before the existing Python
execution child starts; a generic solver worker does not launch a nested Python
executor. Explicit in-process embedding remains available for local callback tests,
with no implied crash isolation or forced-cancellation guarantee.

Serialization, hashing and host admission run outside GUI handlers. Registered
validators, transformations and backend implementations run in the supervised worker.
The receiving host checks typed contracts, hashes, origins and protocol state without
calling extension validators. Global ownership/integrity checks remain mandatory;
domain executable completeness follows the selected model and declared dependency
closure. The source digest still covers the complete project snapshot, and the
computation digest covers that snapshot plus the normalized request. This is
conservative invalidation, not a claim of minimal dependency hashing.

Operational source snapshots and Python execution-file artifacts remain in
attempt/editor scratch resource stores. Declared durable inputs are read through
the same verified resource APIs without bulk copying; local corruption cannot
fall through to another owner. Only checked scientific terminals and admitted
output resources join the durable closure. Scratch cleanup therefore preserves
sealed evidence while keeping transport artifacts out of exact archive proofs.
The worker launch accepts one direct input store and rejects nested input
chains. Shared submission rejects an EvidenceStore without an explicitly
supplied ResourceStore before allocating work; no-store execution is ephemeral.

An `EvidencePublication` owns one verified resource artifact and immutable provenance;
session/sequence fields belong to its `PublicationEvent` envelope. Publication is
durable before its acknowledgment permits producer cleanup. A consumer explicitly
selects the exact typed `ResourceReference`, including after the producer exits.
Cancellation or failure cannot retract a previously sealed receipt or imply that
the producer succeeded. Final evidence separately requires terminal verification.
No publication becomes authored model state without an ordinary promotion command.

See [Computation backends](COMPUTATION_BACKENDS.md) and
[Sealed publications](COMPUTATION_PUBLICATIONS.md) for limits and protocol details.
This work does not implement P2–P8, authored-Python model publication, a CAD backend,
or a new canonical grouping/experiment model.

## P2 Git experiment inputs and edit admission

P2 extends the existing Git/session boundary with [retained experiment inputs](GIT_EXPERIMENTS.md).
An empty private Git index captures only declared source files, native author state
and a bounded manifest. Verified resources and operational attempts live beneath
the repository's common Git directory. A retained run ref and durable ready attempt
exist before the existing computation service starts execution.

Accepted semantic candidates, including undo/redo, pass the authority's host
admission gate. The first edit to a frozen definition is deferred while a background
worker opens a real branch/worktree, seeds the explicitly anchored native journal
and applies the same authority command. No second canonical model or command bus
is involved. Presentation-only commands continue on the current variant. Editor
replacement detaches overlays while host computations continue against their pinned
inputs. Source-file bindings use ordinary resources and the existing Python file
tree, including portable-plan replay. No evidence encoding or project format changes.

P2 verification is tracked separately in [its acceptance map](P2_ACCEPTANCE_MAP.md).
P3–P8 solvers, scientific domains, CAD publication and experiment composition are
outside this change.

## Domain extension and notation contracts

Domain definitions and instances use frozen typed values. Complete static bundles in
`extensions` contribute schemas, validators, notations, indexing, transformations,
generators, and optional runtime presentation. They do not install another authority,
load code from a project, or persist executable callbacks. Existing `SemanticConcept`
and `ProjectionDefinition` meanings are unchanged.

The workspace also owns typed `AuthoredDomainLanguage` definitions: declarative
notations, validator queries, and structural program templates. A revision-derived
resolver compiles them into exact schema/version contributions using one registered
interpreter. The structured desktop editor and automation submit `domain.language.*`
commands to the same authority. No project-selected imports or executable callbacks
are loaded. See [Domain language](DOMAIN_LANGUAGE.md) for composition and editor use.

Grammar version 2 generalizes notation through a typed composition algebra rather
than additional domain-specific renderers. Queries bind canonical objects; editable
fields carry their owning model, node, property and revision. Geometry is derived.
Cross-domain semantic queries can combine these bindings in one canvas. Graph,
table and hierarchy remain convenient presets. The expression editor parses into
the same typed definition and never infers edits from a rendered view.

Domain templates can emit another exact schema/version as an intermediate build
representation. Planning tracks schema scope on each edge and rejects cycles or
ambiguous paths. Each stage validates its immutable output and composes origins
back to authored nodes; only the final derived ProgramModel reaches existing Python
lowering. Intermediate instances never enter the canonical workspace.
See [Workbench composition](WORKBENCH_COMPOSITION.md) for the cutover and boundaries.

Invocation is a separate runtime-adapter contract. `InvocationSpec` carries the
canonical callable identity, identifier, owner/method kind, callable kind and arguments.
The emitter uses its shared invocation renderer to create one package launcher.
Generated execution, live execution and the programming backend execute that same
launcher, so awaiting, generator consumption and class/instance targeting have one
implementation. Combined source is a preview, never a project execution format.
Configured arguments are structured literal values, never namespace-dependent
Python expressions. `bind_invocation` builds an `inspect.Signature` directly from
canonical parameter kinds and default presence, then validates both the receiver's
zero-argument construction and the configured call. Implicit receiver values and
literal arguments are represented by placeholders; no authored expression executes
during binding. Validation, lowering and canonical execution adapters use this one
operation and report `INVOCATION_ARGUMENT_MISMATCH` before launching an invalid call.
Stateful setup belongs in a normal top-level entrypoint. Per-diagram arguments select
temporary build settings without modifying the saved project configuration.
This correction changes neither canonical ProgramModel nor domain ownership.

The write-model inversion covers every supported statement family:

```text
ProgramModel (canonical executable truth)
  |
  +-- Python lowering --> PythonProjectIR --> Python artifacts
  |
  +-- DRAKON adapter --> structural editor projection
  |
  +-- semantic index --> SemanticProgram (derived read model)
                          |
                          +-- queries / visual lenses / runtime overlays
```

`ProgramModel` owns function identity and signature, rename-stable function,
parameter, and local symbols, ordered sequences, all 20 statement types, their owned
branches/contexts/handlers, and every expression role inside those constructs. Python lowering consumes this model.
A DRAKON edit is translated into canonical state inside the authority transaction and
the accepted DRAKON document is immediately re-projected before commit.

Every structured statement is self-contained in `ProgramModel`. DRAKON contributes
presentation bindings, never executable fallback data. `SemanticProgram` remains a
deterministic revision-pinned index for querying and visualization.

The mature model has four planes:

```text
Semantic Program
  functions · structures · operations · expressions · symbols · relations
          |
          +---- presentation projections ---- DRAKON / mind map / freeform
          |
          +---- artifact lowering ----------- Python / SVG / maps / manifests
          |
          +---- revision-pinned execution --- frames / bindings / object graph
```

Presentation state is not executable truth, generated files are disposable, and
runtime sessions are ephemeral. Stable semantic identities connect all four.

## Dependency direction

```text
Qt GUI -----------------+
CLI / Python SDK -------|
JSON-RPC / MCP ---------|
                        v
                  Project Kernel
      commands / queries / events / capabilities
                 shared selection
                        |
            +-----------+-----------+
            v           v           v
      semantic index / view definitions / build config
            |           |           |
            +-----------+-----------+
                        |
       validation / projection / layout / Python IR
                        |
       persistence / rendering / execution adapters
```

Domain modules contain value types and pure operations. They do not import application,
generation, persistence, validation, or Qt modules. The application layer composes
those types into commands and projections; persistence owns format decoding and
migration. No core module imports PySide6.

The executable dependency boundary is explicit:

```text
generation.lowering --------------------> domain.program
domain.program -------------------------> domain.expression
domain.program -------------------------> domain.program_kinds

application.drakon_program_adapter ------> domain.program
application.drakon_program_adapter ------> domain.drakon

domain.drakon / Python IR ---------------> domain.program_kinds
domain.drakon / Python IR ---------------> domain.program_signatures
```

`domain.program` does not import DRAKON or its adapter. Shared enums have one identity
in `domain.program_kinds`: callable, parameter, method, transfer, loop, select,
parallel, simple-statement, and note-placement kinds. `domain.program_signatures`
owns textual `FunctionSpec` and `ParameterSpec` values used at editor and emission
boundaries. The canonical callable and its typed expression trees remain in
`ProgramFunction`; textual signatures are derived values.

| Responsibility | Module |
| --- | --- |
| Executable values and generic program traversal | `domain.program` |
| DRAKON presentation binding, `DrakonViewDefinition` | `domain.projection` |
| Explicit DRAKON import, promotion, and projection | `application.drakon_program_adapter` |
| Initial project/document construction | `application.project_factory` |
| Typed canonical command handlers | `application.features.program` |
| Native format decoding, revision-4 migration, and serialization | `persistence.decoding`, `persistence.serialization` |
| Canonical Python lowering and emission | `generation.lowering`, `generation.ir`, `generation.emitter` |

Factory and codec APIs are imported from these modules directly. Domain package
initialization does not eagerly load concrete editors, factories, or storage.

## Semantic edit boundary

The required editor path is:

```text
DRAKON gesture
  -> resolve semantic identity and edit intent
  -> program.* command
  -> ProgramModel mutation in the authority transaction
  -> refresh the bound DRAKON projection
```

Commands operate on the affected expression, statement, sequence, or function.
Insertion and explicit clipboard/import input may need DRAKON-to-program conversion
for the incoming subtree. That conversion belongs at the adapter boundary; it does
not make the resulting DRAKON document the source of a canonical update. Undo restores
the exact canonical values, including symbol and expression identities. Presentation
metadata updates do not reconstruct executable semantics.

Whole-project promotion belongs to initial construction and legacy import. A normal
editor transaction must not modify a complete projected document and re-promote that
document to discover the user's intended semantic change.

## Canonical structure and editor projections

DRAKON stores the specialized structural editor projection: a header, one intrinsic
End, ordered Sequences, typed atoms, branches, and stable insertion boundaries.
Executable fields are refreshed from `ProgramModel`; geometry is derived from semantics
plus limited layout intent.

Mind maps store a recursively owned ordered hierarchy. Tree ownership makes containment cycles unrepresentable in the normal model.

Free-form diagrams store visual objects and connectors. A shape may be a semantic glyph
or an annotation; a connector may represent a semantic relation or remain an annotation.
Its geometry never acquires DRAKON execution meaning.

The project aggregate persists these documents as an explicit tagged union for their
specialized editors. Revision 5 persists only metadata for DRAKON documents and
reconstructs their structural editor values from the bound function.
`build_semantic_program()` indexes functions, statements, expressions, and symbols
directly from `ProgramModel`. DRAKON contributes only presentation glyphs. Stable `ProgramSymbol.id` values flow
into semantic symbol identities, so rename changes spelling rather than identity.
Features consume `ProjectQueries`, not the document union.

Python expressions have one canonical representation. A valid expression is a
persisted, identity-bearing tree that losslessly carries every Python AST node, field,
list, scalar, context, and operator. Specialized nodes expose symbols, literals,
attributes, subscripts, binary operations, calls, argument lists, and chained assignment
targets; complete composite nodes cover the remaining grammar. Normalized Python text
is a derived rendering, not a stored peer. Invalid or incomplete authored text is an
explicit `UnparsedPythonExpression`, where that single leaf owns the text and has no
second semantic form. Each parse allocates fresh provisional node IDs, so tree position
can never falsely assert identity; identity-preserving rename/rebinding is guarded by
semantic discriminators. Parsing occurs only when text enters through a command or
text-entry replacement; current-format decoding, indexing, symbol rebinding, and rename operate
directly on the tree.

## Project kernel and application service

`ProjectAuthority` is the only writer. All clients submit typed command envelopes
containing actor, operation ID, expected revision, and typed payload. Successful
commands publish typed events and journal entries.

`ProjectKernel` composes the authority with:

- a revision-cached `SemanticProgram` and stable `ProjectQueries`;
- identity-keyed `SemanticDelta` values on every project-revision event;
- a discoverable `CapabilityRegistry` for substantial operations;
- one application-wide semantic `SelectionService`;
- a runtime-session registry whose state never enters project persistence.

Composition roots are statically registered. The first physically owned vertical slice
is `application/features/program`: it owns canonical program mutation policy and
handlers while `authority_contributions.py` only registers them. `ui_qt/workbench.py`
supplies dock placement and discovery, and the kernel capability registry supplies
invocable operations. Duplicate contribution IDs are rejected and discovery order is
deterministic. These are internal seams, not a third-party plugin loader.

Features have four communication highways: commands change the program, queries
inspect it, events report change, and capabilities perform substantial work. Selection
is a fifth deliberately shared UI/session service. Widgets do not call other feature
widgets.

The same service port backs embedded desktop use, a headless local service, CLI, typed
Python SDK, JSON-RPC, and MCP. RPC clients can query semantic objects, children,
callers, references, control/data dependencies, projections, view anchors, capability
descriptors, and revision-pinned runtime sessions.

## Presentation projections and Code Visualizer

`SemanticProjection` is a disposable graph DTO. Architecture, call, control-flow,
data-flow, and authored-concept views compile from persisted `ProjectionDefinition`
vocabulary: scope, traversal, filtering, grouping, decoration, labels, and layout.
DRAKON remains specialized. Runtime Values is built from the execution registry
instead. `projection_positions()` is shared by the Qt graph and projection-to-canvas
materializer, so general lenses do not grow independent layout stacks.

The first vertical Qt feature lives under
`ui_qt/features/semantic_visualizer/`. It contributes a dock rather than adding graph
logic to editor widgets. Wheel/trackpad motion pans; Ctrl-wheel zooms. Its nodes and
relationship paths and its semantic-text lines publish stable IDs to the shared
selection service. Supported text edits submit the same typed commands as graphical
editors. DRAKON,
generated source, anchored design glyphs, automation presence, and runtime pauses react
to that same selection without direct cross-widget calls.

Author-created concepts and explanatory relationships are canonical intent but not
executable control semantics. Saved lens definitions are canonical presentation
policy. Materialized mind maps and freeform canvases are now live view definitions plus
presentation overrides. Anchored labels derive from current semantics; an intentional
edit records `label_override`, and **Use Live Label** removes it. Bounds, style, notes,
collapse state, and manual annotations remain authored presentation.

Projection definitions have an object budget, focus IDs, and expandable IDs. Expression
detail is hidden beneath expression roots until requested. When a lens exceeds its
budget, graph distance from shared selection/runtime focus, meaningful control/data/call
relations, shortest paths, and owner context determine what remains visible. Omitted
objects are summarized by semantic kind. The built-in Data lens defaults to 50 useful
objects rather than exposing every expression node at once.

The Qt graph uses a keyed `SceneReconciler`. Semantic node and edge IDs retain their
`QGraphicsItem` identity across revisions; content, badges, and active state update in
place, while layout runs only for definition, layout, or topology changes. Selection
and positions therefore survive runtime stepping instead of being destroyed by a full
`scene.clear()` refresh.

## Runtime plane

An interactive debugger launch is immutable execution identity:

```text
execution session S
  project revision N
  artifact revision N
  frame -> bindings -> runtime objects/values
```

The isolated worker safely adapts exact built-in containers and raw instance
`__dict__` data without invoking user properties. Captures have depth, child, node, and
preview limits; aliases and cycles use shared value IDs. The worker sends a full
checkpoint periodically and deltas between checkpoints. `RuntimeTraceStore` retains
that compact bounded stream and reconstructs `graph_at(step)` from the nearest
checkpoint with a small LRU cache; only the active graph is retained in full. Trace is
the same worker/protocol in non-pausing record mode, not a second textual tracing
architecture. The document shows an expandable tree and the Code Visualizer can
project the same graph spatially. List/queue/heap/graph/matrix/tree/mapping adapters
change only its presentation.
`RuntimeBinding` carries its canonical `semantic_symbol_id` and `frame_id`, so overlays
do not guess identity from a repeated local name. `RuntimeOverlayContext` applies the
same state to every lens: active semantic/DRAKON node, active incoming route, changed
symbol previews, and a bounded value-graph adapter. Timeline selection recomputes this
overlay for an older state without rewinding the child process. If the project advances,
the UI explicitly says that the running session remains pinned to the older revision.
Runtime graph/event identity mismatches are rejected.

## Extension boundaries

Extension is deliberate and versioned:

1. **Semantic extensions** register new typed constructs, validators, IR lowering, and persistence codecs as one capability bundle.
2. **Shape recipes** register appearance and hit geometry only. They cannot add executable semantics.
3. **Document-mode adapters** project one canonical model into commands, render scenes, search, and accessibility.
4. **Transport adapters** translate external protocols into the same command/query ports.
5. **Runtime adapters** implement explicitly named I/O, timing, concurrency, and debugging profiles.

Registries are composed at the application boundary. Domain objects never contain
arbitrary executable callbacks or Qt objects. “Feature slice” does not mean that the
canonical model is fragmented into unrelated plugins; every slice runs over the same
kernel contracts.

## Determinism

Stable IDs are opaque strings. Ordered semantic collections use tuples. Serialization is explicit, uses sorted JSON keys and stable list order, and ends with one newline. Rendering, generation, and source mapping accept a project revision and reject stale promotion.

## Rendering and structural interaction

The Qt-free rendering package measures text through an injected port, solves one versioned vector recipe per semantic icon, then derives a `DiagramScene` containing final nodes, orthogonal routes, truth/preference labels, fit bounds, and `SequenceBoundary` metadata. The same solved shapes feed Qt paths, palette thumbnails, drag ghosts, generated SVG, contact sheets, and hit corridors.

The canvas never infers control flow from contact. Palette drops and existing-block drags select a boundary carried by a rendered route segment, then submit typed insert or block-transplant commands. A transplant owns its recursive construct bodies, commits as one revision, and rejects self-containment or non-contiguous source selections.

Structural insert/remove/duplicate/move/wrap/unwrap and whole-construct replacement share this command path. Composite replacement preserves the outer stable ID, rejects collisions in owned IDs, and makes Case, context, handler, process, and state metadata editable without exposing storage JSON. Canonical linked Calls refer to a function ID; lowering resolves the callable's current identifier and a configured cross-module import.

Unmodified wheel and two-axis trackpad deltas pan. Ctrl-scroll and native pinch zoom. Connector corridors are pointer affordances but do not enlarge persisted/export fit bounds; visible stroked routes and labels do.

## Python development pipeline

Canonical `ProgramFunction` values and visible module composition lower into a Qt-free
`PythonProjectIR`. Textual signature DTOs come from `domain.program_signatures`;
lowering derives them directly from canonical parameters and annotations. Neither the
typed IR nor the emitter imports the DRAKON domain or application edit adapters.
Canonical dotted module paths are also a virtual graph filesystem: the Project explorer,
Python package files, graph-index records, source maps, and SVG exports derive from the
same ownership. Typed statement nodes retain semantic origins. One deterministic emitter
produces module files, package initializers, the package launcher, standalone preview,
and source-map v3. Source spans name canonical semantic identity first and carry a
nullable presentation document second; preview widgets and runners do not own alternate
string generators.

Python syntax diagnostics are editable generation-gate findings, while referential/identity diagnostics protect canonical model construction. This separation lets an incomplete expression survive save/undo without permitting an unsafe graph or a partial artifact promotion.

The M5 IR covers every typed atom family: assignments and transfers, ordered Select/match, every loop form and loop else, context/exception regions, sync/async concurrency, timers, WAIT/TREE, and silhouette state dispatch. Runtime helper imports are inferred by walking the IR rather than by widgets or generated-text inspection.

After first save, a revision-aware coordinator coalesces edits through an injectable scheduler. It compacts the durable revision, validates, generates into a private temporary directory, checks that the revision is still current, and atomically promotes. The manifest is the only authority for artifact reveal and preview.

Qt supplies a scheduler adapter backed by a bounded worker pool. Worker callbacks
publish immutable status objects through a queued Qt signal; widgets are touched only
on the GUI thread. Session identity and revision providers prevent a replaced project
or superseded edit from promoting stale output.

## Search, clipboard, and navigation

Project search walks the three typed models and visible Python Project data. Replace All
constructs non-clobbering typed replacements and commits one transaction. Semantic
clipboard fragments are versioned and bounded, allocate fresh IDs, preserve internal
references, carry plain text, and expose unresolved external references.

Back/Forward history is presentation state and never changes semantic revision. Find
Callers and Call Hierarchy follow linked diagram IDs; recursive graphs end in a cycle
marker. Find Address Transitions follows silhouette branch IDs rather than text.

## Durability and scale

An OS-backed byte-range lease establishes a single writer and advertises its endpoint.
Bounded reads, periodic snapshots, journal compaction, rollback-safe fsync, and
non-mutating read-only recovery make failure behavior explicit.

The shell builds the complete nested project tree but lazily materializes editor widgets
for projects over five documents. Small learning projects still open their complete set;
larger systems start with one document and use the module tree as navigation. Validation,
generation, and project execution stay off the UI thread.

## Safety boundary

Git is an application lifecycle adapter around the saved project, not a semantic merge
engine or second command bus. Its typed status/diff/history/branch/remote use cases use
the installed CLI and are shared by the Git dock and permission-checked automation.
A saved revision is the commit boundary. After a Git worktree change, the host blocks
stale commands and autosave, validates the native file, archives only untracked local
recovery history, and installs a fresh ordinary session. Conflicted/invalid files never
enter an authority. See [Git workflow](GIT_WORKFLOW.md).

For P2 experiment handoff, a loaded session owns an immutable experiment context
(variant, retained attempt, expected Git state). The controller publishes that
session only after candidate preparation succeeds. A semantic fork transfers the
current declared auxiliary source bytes alongside native history; Git ancestry
does not replace working inputs with their older frozen versions. Native-journal
acceptance remains the operation's outcome authority when secondary recovery
metadata or notifications fail. See [the transaction contract](GIT_EXPERIMENTS.md).

An attempt's immutable variant/input binding also owns durable freeze protection.
The context is installed before host submission, and ordinary session loading
reconciles attempts and freeze operations before enabling semantic writes. Marker
status is a cache; uncertainty requires recovery rather than an unrun editor.
This extends the same transaction, authority and computation lifecycle; see
[freeze recovery](GIT_FREEZE_RECOVERY.md).

Opening, validating, laying out, rendering, and generating never execute project Python. Execution is an explicit child-process capability. Asset and shape-pack loading is bounded and sanitized.

## Adaptive continuum

The adaptive continuum slice follows these same boundaries. Its authored
problem and policy are ordinary domain objects. Cell partitions, transfer
records, decisions and solver checkpoints are derived resources, published
through the existing computation host. A mesh change does not submit an
authoring command or create a Git branch. The adaptive history panel and exact
cell Probe use stable region/lineage/component identities and the existing
selection, authority and retained-run services. See [adaptive cell histories](ADAPTIVE_FIELDS.md).
The particle-continuum slice remains under qualification; this continuum
integration alone does not complete P7.

## Prohibited dependencies

- No import from the parent prototype package.
- No import from `drakon_editor1.31`.
- No PySide6 import in core policy modules.
- No persistence or widget DTOs inside the domain model.
- No geometry-inferred DRAKON connectivity.
