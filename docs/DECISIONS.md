# Decision log

## D-044 - Host-owned computation lifetime and sealed publication admission

**Status:** P1 accepted on the recorded Windows reference environment. P0 remains accepted;
this decision does not mark later transition phases complete.

**Decision:** One host-owned `ComputationService` accepts immutable project/request
snapshots. GUI submission and headless wait share its attempts and existing runtime
plane. Editor attachment lifetime is separate from computation lifetime. Trusted
process profiles supervise preparation and backend work; the Python strategy owns
the existing execution child after preparation, without nesting Python execution
inside another solver worker. Explicit in-process composition remains available
for embedding and callback-identity tests, never as an inferred fallback.

Workers exchange closed versioned data messages. Registered behavior executes in
the worker; host admission checks contracts, origin identities, resource hashes and
protocol state without extension callbacks. Global structural integrity remains
required, while domain completeness follows selected computation dependencies.
Whole-project source hashing remains deliberately conservative.

Streaming backends may declare `publications=True`. A publication is an immutable,
content-derived evidence receipt for one verified artifact and its provenance.
Session identity and event sequence remain outside that receipt. Resource import,
contract validation and cumulative receipt-budget reservation precede durable
publication; acknowledgment precedes producer cleanup. Consumers select exact
typed resource references, not a global latest result. Existing request, terminal
and final-evidence bytes retain their encoding; the new false capability is omitted
to preserve historical hashes.

Final evidence requires a separate resource-secured acknowledgment, verification
that the backend iterator ends, and normal worker exit. Cancellation accepted before
final admission cannot become successful evidence. Cancellation during final
verification is explicitly rejected; host shutdown drains that verification.
Host-forced termination and cooperative cancellation remain distinct operational
facts. Neither retracts earlier sealed publications or fabricates success.

Operational snapshots and emitted execution-file transports belong to an
attempt/editor scratch store, separate from durable scientific resources.
Explicit verified read-only inputs avoid eager bulk copies. Only checked
terminals and admitted scientific outputs cross into durable storage through
the existing CAS pipeline. Local corruption never triggers fallback. This
preserves exact historical archive resources and sealed receipts after cleanup.
Durable receipts require both stores at shared submission; worker launch
rejects nested input layouts rather than dropping read-through ancestors.

The GUI observes runtime snapshots on its own thread and distinguishes pending
preparation from execution. Stop can cancel preparation immediately without
starting a late artifact; an already running child uses its normal completion
protocol. Accepted preparation snapshots notify waiting observers. SVG rendering
is imported for artifact export, not as a dependency of Python preparation.
Neither presentation timing nor temporary transport files own meaning.

**Reason:** A synchronous callback on the GUI stack cannot provide responsive
editing, crash isolation or bounded forced cancellation. Durable typed outputs also
need an ownership boundary before a producer's staging files disappear. Separating
authored state, attempts, disposable representations and immutable receipts solves
both problems without another authority, command bus or canonical model. It does
not implement authored-Python/CAD publication or later experiment-language phases.
See [Computation publications](COMPUTATION_PUBLICATIONS.md).

## D-043 - Allocate generated Python bindings against authored lexical names

**Decision:** A single deterministic Python symbol allocator reserves NFKC-normalized
authored identifiers across an emitted file, including nested bindings and free
references. The emitter and invocation renderer allocate implementation imports,
helpers, temporaries and launcher bindings through that policy. Generated timer
bindings retain lexical ownership: assignments declare a local role, reads resolve
enclosing roles, and function closure lookup skips class namespaces.

Existing explicit references to feature-dependent runtime helpers retain their
initial evaluation environment and ordinary authored shadowing. Typed operations
use protected implementation bindings. Authored expressions, built-in lookup,
declaration order and canonical identities remain unchanged. The policy covers
lexical names; it does not infer names created dynamically through reflection.

**Reason:** A fixed underscore prefix cannot separate generated implementation from
valid authored Python. A shared allocator prevents capture without a blacklist,
source rewriting or separate execution paths. Persistent generated files, live
Run/Trace/Debug and the Python computation backend continue to execute the same
emitted package. See [Python execution](PYTHON_EXECUTION.md).

The regression gate also exposed a completion-delivery race in the existing live
adapter. A terminal debugger event is now delivered only after preceding output,
worker exit and temporary-tree cleanup; stopping during natural shutdown does not
race another command against the exiting process. This corrects runtime lifetime
without changing canonical semantics or the emitted representation.

## D-042 - One emitted Python package for every project execution surface

ProgramModule distinguishes ordinary modules from package initializers with an
explicit MODULE/PACKAGE kind. Both own typed declarations and opaque project IDs.
Authored initializers participate in normal Python imports; derived empty parent
initializers never overwrite them.

PythonProjectIR emits one GeneratedProject: real package files, launcher, file-local
source spans and origins. Generated execution uses a persistent tree; live Run,
Trace, Debug and the programming backend materialize the same files temporarily.
All execute the emitted launcher through Python's normal import machinery. The
combined source renderer is a readable preview only and contains no custom loader.
Runtime positions carry artifact-relative file identity, line and column, retaining
revision-pinned semantic selection and domain origins across module boundaries.

PythonRuntimeSettings and the native runtime_settings key replace the obsolete
ModuleSetup name. The workspace is Python Project. Revision 11 migrates earlier
snapshots and journals; current documents cannot carry both keys. Terminal-v2
modules lacking the additive kind field retain MODULE semantics after their original
bytes and hashes are verified.

Python remains the implementation language and supported programming runtime.
Representation, ComputationBackend, Evidence and Resource retain their independent
contracts. See [Python execution](PYTHON_EXECUTION.md).

## D-041 - Canonical Python modules and classes own executable declarations

ProgramModel is deliberately Python-specific. Ordered ProgramModule/ProgramClass
bodies own imports, assignments, aliases, typed Python suites and function-table
references. Scope IDs are stored project IDs; their spelling is not their identity.
Package, entrypoint selection, literal arguments and startup declarations are
program semantics. PythonRuntimeSettings retains only run-profile configuration.

Native revision 10 migrates legacy executable setup and journal operations. Portable
computation terminal revision 2 migrates at the same boundary and carries no second
executable setup representation. Generated Python remains the published
code_visualizer.python.source representation and never canonical author state.

General computation backends remain ordinary Python adapters. Neither non-program
domains nor future foreign implementation details require a universal programming
AST, internal protobuf roundtrips, or lowering every computation into ProgramModel.
See [PYTHON_PROGRAM_MODEL.md](PYTHON_PROGRAM_MODEL.md) for ownership, invalid states,
and migration details.

## D-039 - Bind invocations against canonical parameter signatures

**Decision:** `bind_invocation(program, function, arguments)` validates canonical
callable membership, receiver eligibility and argument binding, then returns the
existing `InvocationSpec`. It builds `inspect.Signature` from `ProgramParameter`
kinds and default presence. Placeholder values preserve Python's binding rules
without evaluating defaults, annotations or program code. Implicit receiver binding
uses the same operation, including variadic signatures.
Effective parameter names follow Python identifier normalization and class-private
mangling. Temporary signature aliases preserve name equality while accommodating
Unicode spellings that Python accepts but `inspect.Parameter` rejects after
normalization. Diagnostics return the effective names; canonical spelling is unchanged.

Validation, lowering and canonical execution adapters consume this operation.
Invalid calls remain editable but produce `INVOCATION_ARGUMENT_MISMATCH` and block
generation/execution. Selected-diagram arguments override saved invocation settings
only in the temporary build. Source-snapshot capabilities consume a supplied spec;
they cannot bind arbitrary source against an unrelated canonical program.

**Reason:** Literal arguments alone do not establish that a callable can accept them.
Python's own signature binder supplies one rule for missing, excess, duplicate,
positional-only and keyword-only arguments, defaults, `*args` and `**kwargs`. This
requires no new invocation representation, receiver language or ProgramModel change.

## D-038 - Git owns cross-revision collaboration and merges

**Decision:** Use the installed Git CLI, its index, branches, history, text merges and
configured remotes. Desktop and permission-checked automation share session-aware Git
use cases. Worktree replacement blocks the old authority; native decoding and integrity
validation precede reopening through the ordinary project session lifecycle.

**Reason:** A semantic VCS would create another history and reconciliation system.
Local undo remains revision recovery data and is archived at a Git boundary so a higher
revision from another branch cannot resurrect its contents. Git-tracked recovery state
is refused; no force, automatic stash, automatic commit or silent conflict resolution is
used. See [Git workflow](GIT_WORKFLOW.md).

## D-037 - Literal invocation context and explicit receiver eligibility

**Decision:** Configured arguments own typed literal values. Every launcher renders
the same values; argument expressions cannot depend on a module namespace. Direct
instance-method entrypoints require a constructor signature accepting zero arguments.
A top-level entrypoint owns any stateful receiver setup. Legacy expression text is
preserved as unresolved configuration and must be repaired before execution.

**Reason:** Callable targeting alone did not unify the environment in which arguments
and receivers were formed. These checks close the runtime-adapter contract without
inventing a general invocation language or changing ProgramModel ownership.

## D-036 - Schema-scoped intermediate representations are derived artifacts

**Decision:** An authored transformation outputs either program templates or typed
instances of a pinned target schema. Planning follows explicit dependencies and
representation/schema/version edges. Intermediate nodes are deterministic build
objects with origins, validated after each stage and never persisted as authored data.

**Reason:** Users can construct intermediate languages without registering extension
Python. Schema scope must follow every stage, and multiple viable routes require an
ambiguity diagnostic rather than selection by registration order.

## D-035 - Editable notation is a composable typed language

**Decision:** A composed notation defines text, fields, equations, groups, shapes,
paths, positions, queries, and connectors over stable canonical bindings. Cross-domain
queries use the workspace and semantic relations. A readable expression editor and
structured controls edit the same typed syntax. Graph/table/form remain presets.

**Reason:** A fixed renderer menu cannot express domain-specific human notation.
Composition generalizes representation while direct field commands preserve one
owner for meaning. Rendered geometry and expression text remain derived.

## D-034 - Project-authored language definitions are typed inert data

**Decision:** DomainWorkspace owns schema-pinned notation definitions, validator
queries, and structural program templates. One statically registered interpreter
resolves these into ordinary scoped workbench contributions for a project revision.
Typed language commands and the structured UI use the existing authority and history.
ProgramModel retains its specialized representation; transformed output is derived.

**Reason:** Users can change their language inside the workbench without executable
project callbacks, renderer diffing, or another canonical instance model. A bounded
initial grammar with explicit holes and diagnostics is preferable to unvalidated
Python strings or a claim of universal language construction.

## D-033 - One callable invocation contract across execution adapters

**Decision:** InvocationSpec describes callable identity, name, owner, method kind,
callable kind and arguments. Generated launchers, Run, Trace, Debug, CLI and automation
use one implementation of targeting, awaiting and generator consumption. Ordinary
return display is an explicit presentation policy; generator yields are drained.

**Reason:** Bare names discarded the metadata needed to execute async functions,
generators and methods. This is a runtime-adapter correction, not a canonical model
or domain-architecture change.

## D-001 — Independent project root

**Decision:** Build inside `code visualizer/` with its own package, dependency metadata, tests, examples, docs, and virtual environment.

**Reason:** The controlling specification requires a verifiable from-scratch boundary while preserving the prototype until explicit cutover.

## D-002 — Product identity is centralized

**Decision:** “Code Visualizer” and its application ID live in one immutable configuration value.

**Reason:** Branding must not leak into schema tags, protocol method names, or generated identifiers.

## D-003 — Distinct persisted views, one semantic-program boundary

**Decision:** The current native format retains distinct DRAKON, mind-map, and free-form payloads joined
by an explicit union. The application does not expose that union as the mature program
API: a revision-derived `SemanticProgram` supplies functions, structures, operations,
expressions, symbols, relations, and presentation anchors through `ProjectQueries`.

**Reason:** Their persistence and editing invariants differ, so a generic node/edge
document would make invalid states easy. At the same time, treating them as unrelated
programs prevents synchronized navigation and visualization. These payloads are
projections over canonical semantic truth, not three independent program models.

## D-004 — Immutable semantic snapshots

**Decision:** Canonical values are frozen, slotted dataclasses with tuple-owned collections.

**Reason:** Revisions, undo, deterministic serialization, concurrent readers, and events become easier to reason about.

## D-005 — Explicit serialization

**Decision:** Every schema field is projected deliberately; `dataclasses.asdict` is not the persistence contract.

**Reason:** Explicit codecs prevent refactors from silently changing project files and make development-format cutovers deliberate.

## D-006 — Live service, not file inbox

**Decision:** Collaboration uses a single semantic command/event authority. Files provide durability and recovery, not live command delivery.

**Reason:** Human and automated clients need revisions, conflicts, subscriptions, capabilities, and immediate GUI projection.

## D-007 — Complete extension bundles

**Decision:** A semantic extension provides model, validation, persistence, rendering metadata, and optional Python lowering as one capability.

**Reason:** Registering only a picture or generator would create unexplained palette items and semantic gaps.

**Implementation:** The intentional-workbench extension implements this contract in
`extensions.registry.DomainExtensionBundle`. The explicit built-in composition includes
the programming provider, generic intentional provider, and independent FSM domain.
Schemas, validators, semantic contributions, editable notation definitions,
transformations, generators, and optional runtime presenters belong to one versioned
registration. Projects persist data and bundle references; no dynamic loader or
project-authored callbacks are introduced. Missing implementations preserve data and
produce build diagnostics. See D-029 through D-032.

## D-008 — One solved vector scene

**Decision:** Text measurement, recipe dimensions, outlines, dividers, ports, routes, labels, hit corridors, and fit bounds are solved in a Qt-free scene before projection.

**Reason:** Canvas, thumbnails, ghosts, SVG, and goldens must not drift into separate shape fractions or clip connector geometry.

## D-009 — Routes project semantic boundaries

**Decision:** Every eligible horizontal or vertical route segment carries a typed Sequence ID and insertion index. Structural drag submits a block-transplant command; pixel contact never changes flow.

**Reason:** This makes insertion predictable, automatable, undoable, and independent of viewport scale.

## D-010 — Reproducible bundled fonts

**Decision:** Unmodified licensed DejaVu interface and monospace fonts are registered as application resources and audited by hash.

**Reason:** Qt off-screen and packaged systems cannot be assumed to expose the same system fonts; missing glyphs invalidate text-collision goldens.

## D-011 — One typed Python IR

**Decision:** Module files, standalone preview, live execution, trace, and source maps are all emitted from one typed Python IR carrying semantic origins.

**Reason:** Independent widget and disk generators inevitably disagree about imports, branches, line numbers, and validity.

Source origins name canonical semantic objects first. A presentation document is
nullable navigation context, never a fallback identity for a canonical callable.

## D-012 — Editable Python errors are not integrity failures

**Decision:** Referential/identity failures reject unsafe model construction, while invalid Python text commits as an actionable diagnostic and blocks dependent generation.

**Reason:** An IDE must preserve incomplete work without publishing broken or partial artifacts.

## D-013 — The manifest gates artifact UX

**Decision:** Artifact preview and folder reveal read a complete, non-empty generation manifest; directory existence alone is never success.

**Reason:** Opening an empty or stale folder gives a false signal and hides the actual blocking diagnostic.

## D-014 - OS lease plus explicit read-only open

**Decision:** A byte-range lock, bounded owner metadata, and optional live endpoint
make one authority the only writer. Conflicts offer connection or read-only navigation.

**Reason:** Advisory marker files alone cannot prevent simultaneous writers or survive
crashes reliably.

## D-015 - Semantic clipboard and navigation

**Decision:** Clipboard data and caller/address navigation use versioned semantic IDs,
never canvas pixels or generated-text guesses.

**Reason:** Cross-document edits and refactors must remain deterministic after layout,
rename, and source regeneration.

## D-016 - Background revision-safe pipeline

**Decision:** Validation/generation execute in a bounded worker pool and may publish or
promote only while session identity and project revision still match.

**Reason:** Large projects must not freeze Qt, and an old job must never win a race with
newer human or agent work.

## D-017 - Optional native bundles remain reproducible commands

**Decision:** Wheels/sdists use PEP 517. Optional Windows/Linux onedir bundles use one
checked-in PyInstaller driver, resource collection, packaged smoke tests, and a
SHA-256 manifest. On Windows the GUI uses the console bootloader with `hide-early` for
enterprise WDAC compatibility. D-021 makes these bundles optional rather than the
supported release.

**Reason:** A release claim needs executable evidence and an auditable build path, not
an undocumented workstation artifact.

## D-018 - Example catalogs promote as one artifact

**Decision:** Regeneration builds the entire bundled-project catalog in a sibling
staging directory, verifies each native project and generated manifest, then atomically
swaps the catalog with rollback on promotion failure.

**Reason:** Replacing projects one at a time can retain stale recovery snapshots or
removed directories whose project identity no longer matches regenerated native data.

## D-019 - Context controls construction affordances

**Decision:** Shapes and palette commands remain discoverable but explain and reject
constructs that are illegal at the active insertion boundary. Loop transfers,
async-only atoms, generator returns, and unsupported nested-scope operations are
derived from typed ownership context.

**Reason:** A Python IDE should prevent structurally impossible edits before mutation
while still teaching why an operation is unavailable.

## D-020 - Frozen execution has a private worker boundary

**Decision:** Source and wheel installs launch their current interpreter. Frozen
desktop/CLI bundles re-enter their own embedded runtime only through a private child
mode for source, trace, generated-project, and debugger workers; a run-profile
interpreter always overrides the default.

**Reason:** In a frozen application `sys.executable` is the product executable, not a
general Python command. Passing `-c` to it would re-enter the public argument parser,
while the private worker retains process isolation and a self-contained basic runtime.

## D-021 - The supported release is a source folder

**Decision:** The primary distribution is a manifest-backed folder containing the
complete source, examples, docs, tests, pinned requirements, and an offline Windows
3.12/3.13 wheelhouse. `python launch.py` creates a private in-folder environment and
starts GUI or CLI. Custom native executables are optional signing-team artifacts.

**Reason:** The product is Python-first and does not benefit from making an unsigned
bootloader a release requirement. A source folder is inspectable, editable, resistant
to enterprise executable reputation policy, and still gives a one-command launch with
reproducible dependencies.

## D-022 - Four planes, joined by stable identities

**Decision:** The system distinguishes a semantic program, presentation views,
disposable artifacts, and revision-pinned runtime sessions. DRAKON glyphs intrinsically
anchor to operations; mind-map topics and freeform shapes may anchor to semantic
objects; cross-links and connectors may anchor to semantic relationships. Unanchored
items are annotations and never become executable merely because they were drawn.

**Reason:** Program meaning, layout, generated files, and runtime state have different
lifetimes and invariants. Stable identities let every lens select and reveal the same
thing without copying assignments into multiple documents or making widgets depend on
one another.

## D-023 - Project kernel communication highways

**Decision:** Vertical features communicate through commands, queries, semantic
events, capability services, and one shared selection service. `ProjectKernel` owns
revision-cached read models and these services. Substantial operations are registered
under discoverable IDs such as `python.generator`, `analysis.dataflow`,
`execution.debugger`, and `view.runtime` rather than hard-coded widget calls.

**Reason:** Direct DRAKON-to-mind-map-to-debugger widget calls cannot scale. A small
neutral vocabulary of semantic IDs and immutable DTOs lets Qt, CLI, SDK, WebSocket,
and future feature slices evolve independently over the same authority.

## D-024 - Runtime values are bounded graphs, not repr strings

**Decision:** Each debugger launch records an execution-session ID, project revision,
and artifact revision. Pauses emit bounded identity-preserving value graphs with
bindings, types, previews, child edges, alias/cycle references, periodic checkpoints,
and deltas. Stringified locals remain only as a flat display summary.

**Reason:** `repr()` loses aliasing, container structure, and object identity, and an
execution of revision N must never be silently reinterpreted against revision N+1.
Bounded graphs make data visualization possible without unbounded heap copying or
unsafe property evaluation.

## D-025 - A canonical expression has one representation

**Decision:** ProgramModel stores a complete, identity-bearing Python syntax tree
for every valid expression and derives normalized source from it. Incomplete text uses
an explicit `UnparsedPythonExpression` leaf and has no competing parsed form. Text entry
is a parse boundary; decode, query, refactor, and lowering
are tree-driven.

**Reason:** Persisting both authored source and a semantic tree creates two values that
can disagree inside the purported canonical model. A single renderable tree makes
stable-symbol refactoring deterministic, keeps persistence honest, and confines the
necessary text escape hatch to visibly incomplete work.

## D-026 - Expression identity must be truthful before it is stable

**Decision:** Parsing creates fresh provisional IDs for every expression node. Tree
position never determines identity. A structural transformation may retain an ID only
when node kind and semantic discriminator establish that it is the same object; an
uncertain match receives a fresh ID. A later tree reconciler may preserve more IDs only
with equivalent evidence.

Incomplete expression text is a valid authoring state but an explicitly non-buildable
state. `assess_project()` reports buildability, and generation, run, trace, and debug
must pass that gate. D-027 completes the subsequent statement-family inversion.

**Reason:** False identity corrupts selection, semantic deltas, runtime overlays, and
automation references more severely than allocating a new identity. Separating model
integrity from buildability preserves comfortable editing without allowing invalid
Python artifacts or executions.


## D-027 - Complete canonical statement ownership

**Decision:** Every supported statement owns its typed expressions, nested sequences,
branches, contexts, and handlers in ProgramModel. DRAKON edits translate at the command
boundary. Canonical statement insertion accepts a complete typed subtree; expression,
move, delete, rename, and history operations traverse every owned structure.
Python lowering and semantic indexing consume canonical values directly.

Revision 5 persists DRAKON presentation metadata without executable bodies. The
revision-4 importer consumes old placeholder records once, preserves canonical fields,
and assigns deterministic identities to imported expression trees. There is no live
placeholder class or payload fallback.

**Reason:** Functions must remain editable, validatable, executable, and traceable
after their views are removed. Keeping a second executable body in a view prevents
that guarantee and makes persistence, refactoring, and recovery ambiguous.

## D-028 - Dependencies follow canonical ownership

**Decision:** `domain.program` owns executable value types and pure traversal only.
DRAKON import/promotion and projection are application adapter operations. Shared
semantic enums originate in `domain.program_kinds`, and textual signature DTOs
originate in `domain.program_signatures`. DRAKON and Python generation import those
neutral types. Presentation bindings belong to `domain.projection`; project factories
belong to `application.project_factory`; native codecs and legacy migration belong
to `persistence`.

The editor command contract is gesture, semantic intent, `program.*` command,
canonical mutation, then projection refresh. Initial construction and explicit legacy
import may promote a whole DRAKON document. Routine editing must express the affected
canonical operation rather than infer it by re-promoting a completed projection.

**Reason:** Correct data flow alone does not prevent the canonical model from becoming
dependent on one editor. Neutral definitions and outward adapters make that direction
enforceable. Commands scoped to semantic intent preserve the same model and history
behavior across structural, textual, graphical, and automated clients.

## D-029 - Uniform workbench contract, specialized canonical storage

**Decision:** A single ProjectAuthority owns the typed ProgramModel and schema-driven
DomainWorkspace as different authored domains. Providers expose one discovery and
identity protocol. ProgramModel is not recoded as generic intentional nodes.

**Reason:** A shared workbench needs uniform access and ownership, not weaker physical
storage. Existing expression, symbol, containment, and DRAKON invariants remain useful.
Transformed ProgramModel contributions are build artifacts, never persisted authored
programs beside their source intentions.

## D-030 - Notations bind edits directly to intentional identities

**Decision:** NotationDefinition is distinct from ProjectionDefinition. Declarative
property/reference paths compile to graph/table/tree-form items carrying explicit
node, property/role, and revision bindings. Edits submit existing-authority domain.*
commands. Generic fallback notations work for any schema.

**Reason:** A cell can show and edit a referenced object's name without creating a copy
or discovering changes by comparing rendered views. Shared identity also supports
selection, undo, search, and runtime highlights.

## D-031 - Explicit transformation dependencies and derived composition

**Decision:** Versioned transformations declare source/target representations and
dependency keys. Planning rejects missing dependencies, cycles, and ambiguous paths.
Inputs and origins are immutable; composition rejects generated identity collisions.
The existing Python lowering/emitter remains the programming-domain generator.

**Reason:** Numeric priorities and import order cannot express semantic prerequisites.
Explicit intermediate representations make independently developed transforms
composable without hidden global mutation or another canonical model.

## D-032 - Origins extend the existing revision-pinned runtime plane

**Decision:** OriginMap links every generated semantic identity to its source
intentions. RuntimeSessionState retains generated semantic_id and original origin_ids
under one execution/project/artifact revision. Code and domain views consume their
union for applicable highlights. Trace and debug use the existing isolated worker.

**Reason:** A separate domain debugger would split the execution truth. Stable origins
recover domain meaning from existing source maps while retaining ordinary program
debugging and honest behavior when the authored revision advances.

## D-033 - Definition, presentation, derivation, computation, evidence and resources

**Decision:** Authored definition and presentation policy remain under one authority.
Transformations produce disposable terminal representations. Registered backends
consume those representations; ProgramModel is required only for Python computation.
Immutable evidence retains revision, inputs, transformations, backend version,
origins and resource hashes. Explicit promotion is an ordinary authority command.

**Reason:** A simulation result has a durable provenance lifetime without becoming
authored input. A mathematical equation or physical relationship belongs to a domain,
while the workbench provides identities, references and computation boundaries.
First-party math and space foundations use the same extension contracts as other
domains. The kernel has no universal Connection or physical-object enum.

## D-034 - Closed bounded values and external content-addressed data

**Decision:** CanonicalValue v1 has eight variants: text, boolean, integer, real,
complex, quantity, small tensor and resource reference. Legacy Python scalars retain
their representation. Compound values are immutable, finite and bounded; tensor
shape/dtype and quantity dimensions are schema contracts. Large bytes remain in the
resource plane, with descriptor identity distinct from byte-content identity.

**Reason:** A uniform boundary does not require replacing ProgramModel with generic
trees or wrapping every scalar. Limits prevent canonical state and command journals
from becoming bulk-array stores. Domains interpret dimensions, frames and quantities.

## D-035 - Protobuf is an interchange contract, independent of native persistence

**Decision:** Checked-in versioned .proto families and generated bindings describe
the universal boundaries and typed commands. Adapters validate before authority or
backend admission. There is no Any/Struct/opaque JSON escape hatch. Unknown fields,
variants and unsupported versions are explicit failures; field numbers are never
reused. The authenticated automation session can negotiate binary commands while
retaining its existing capability/revision/event system. project.json remains
canonical author storage. Resource and evidence identities never hash Protobuf bytes.

**Reason:** Solver and frontend implementations can target a language-neutral
contract without adopting Python classes or Qt. A wire protocol does not determine
the ontology, backend implementation, project format or canonical hash algorithm.

## D-036 - Public contracts have host-granted namespace owners

**Decision:** Qualified public names and exact versions are distinct from opaque
project object identities. A published bundle declares an owner; the composition
root grants that owner a namespace. Registration atomically rejects conflicts and
private contributions claiming reserved namespaces. Publication manifests verify
all typed public references against exact declared bundle dependencies. Local drafts
remain editable but cannot produce public manifests.

**Reason:** A stable string alone cannot prevent independently developed extensions
from redefining the same backend, unit, schema namespace or representation. A host
grant expresses trust; spelling a reverse-DNS name is not authentication.

## D-037 - Shared units are ordinary immutable foundation data

**Decision:** foundation.units defines schemas and validated conversion behavior;
foundation.units.si supplies ordinary DomainModels for shared SI units and bases.
Unit catalogs are derived indexes. Referenced SI identity/version/dimension must
match the released definition. Alternative systems and conversion contexts use
the same schema. Reference vocabulary installation uses ordinary authority commands.

**Reason:** Dimensional structure belongs in the general value contract, while SI
and conversion meaning belong to an independently versioned foundation. No new
CanonicalValue variants or kernel physical taxonomy are needed.

## D-038 - Portable metadata is small; resource transport is streamed

**Decision:** Evidence admission enforces both exact native JSON and exact v1
Protobuf encoding within 2 MiB. Resource transfer uses bounded typed chunks,
contiguous offsets, explicit transfer budgets, hash/size verification and staging.
Incomplete or malformed streams cannot publish a descriptor. Bulk observations
remain resources rather than being split into oversized evidence records.

**Reason:** Durable evidence that cannot cross its own wire boundary violates
portability. Chunking transports data without weakening the metadata invariant.

## D-039 - Backend API v1 declares capabilities and owns a bounded lifecycle

**Decision:** Batch and cooperative streaming implementations share start, advance,
cancel and terminal-result admission. Capability declarations distinguish live
events, cancellation, deterministic/seeded behavior and external workers. Versions
and capability/implementation inconsistencies fail at registration. Existing
execute APIs drain the same lifecycle; the current Python and math adapters remain
batch implementations. Runtime state remains ephemeral under the existing registry.

**Reason:** Third parties need an implementation contract as well as message types.
The presence of a cancellation message does not imply forced preemption, scheduling
or checkpoint support. No second command bus or computation authority is introduced.

## D-040 - Public references resolve through declared contracts

**Decision:** Derive public references from all inert published definitions through
one typed traversal. Resolve each bundle against its exact dependency closure;
dependencies cannot borrow declarations from their consumers. Versionless immutable
dimension bases must resolve uniquely. Manifests record exact resolved references.
Resource logical types use qualified IDs plus separate versions and require published
providers at computation admission. The universal terminal format has its own
computation contract bundle, independent of Python or mathematical domains.

**Reason:** Naming rules are ineffective if a portable descriptor cannot express
them or a schema can use an undeclared unit through its default value. Preserving
unknown metadata in storage is distinct from admitting its interpretation. Typed
resource descriptors evolve explicitly without recycling Protobuf field tags or
changing the hashes of resources that have no logical type.

## D-041 - Git retains experiment inputs; the existing authority owns edits

**Decision:** Freeze an explicitly declared source/resource closure through an
empty private Git index, leaving the original HEAD/index and unrelated files alone.
Retain each attempt's input commit under its own Git ref and durable operational
envelope before submitting the existing host computation lifecycle. Resources and
evidence live under repository-common retention, independently of editor worktrees.

The authority's validated candidate determines whether an edit changes definition
state. Its first semantic edit after a freeze is deferred while a background host
worker creates one real branch/worktree, loads it normally, transfers explicitly
anchored native history and commits that same authority operation. Further edits
stay there until another freeze. Views, unaccepted text, derived products and old
runtime state cannot become a second editable definition. Partial transactions
report their durable boundary; recovery never guesses whether to replay a run.

**Reason:** Git refs, canonical identity, operational attempt identity and immutable
scientific evidence serve different lifetimes. Collapsing them would either consume
unrelated user work, lose old results on checkout, or misapply same-revision runtime
events. [P2's contract](GIT_EXPERIMENTS.md) defines the exact closure and limitations.

**P2 review correction:** The approved worktree owns ordinary source files even
when its directory is nested beneath Git retention. A semantic fork carries the
current declared auxiliary source bytes alongside native history, with explicit
race checks. Each loaded session owns one immutable experiment admission context;
publishing the controller's session selects variant, attempt and expected Git
state together. Durable native acceptance remains authoritative when secondary
metadata/error writes or editor notifications fail. The review regressions extend
P2's acceptance contract without changing canonical models or computation engines.

**P2 freeze-recovery follow-up:** The durable ready attempt binds its editing
variant to the retained input before host admission. That association stays frozen
across failed admission, reporting errors and restart. The loader derives policy
from retained attempts/operations and refuses uncertain bindings; a marker cannot
grant in-place editing over durable freeze evidence. Session context remains
immutable, and recovery never automatically replays execution.

## D-045 - Shared equations extend mathematical meaning with an explicit version

**Decision:** Keep math@1 indexed assignment evaluation and all old integral
dimension encodings. Introduce math@2 relations, explicit solve requests, bindings,
unknowns, quantity kinds and physical normalization scales. Reduced rational
dimension powers have a nested versioned value/wire encoding. Unit products and
named compound-unit equations are foundation intentions. Only a declared catalog
conversion authorizes Pint; its built-in vocabulary is not a semantic authority.

**Reason:** The same authored relation can answer different solve requests. Solving
it must not silently reinterpret old assignment evidence, guess missing bindings,
strip units or alter retained input identity. The first backend accepts bounded
steady scalar linear systems, distinguishes rank failures, and records physical
and normalized residuals. SymPy sees constructed validated scalar nodes, never
author source text. NumPy and Pint are replaceable Python implementation details.

## D-046 - Physical topology and retained comparison use existing ownership

**Decision:** A DC extension owns circuit/net/component/terminal semantics and
derives the generic mathematical problem plus complete OriginMap. A direct F=k*x
client uses the same backend with no circuit dispatch. Output matrices and solution
reports are disposable typed resources; no generated model becomes authored state.
Retained comparison verifies both Git inputs, evidence identities and resource
hashes, joins observation IDs and original semantic IDs, and converts quantities
only when both frozen catalogs authorize the same conversion. It is a read operation
on the existing Git service, performed off the GUI thread.

**Reason:** Comparing experiments must remain meaningful after editor replacement,
renaming and worktree removal. Labels and local revision numbers cannot substitute
for retained input identity. P2 durable freeze admission and recovery remain
unchanged; neither a solver nor comparison introduces another execution authority.

## D-047 - Python publications extend the managed file execution boundary

**Decision:** Publish through Python backend version 2 using named typed request
bindings and the existing debugger child, bounded resource transfer, admission,
durable receipt and acknowledgement. Preserve version 1 bytes and behavior.
Quiesce in-flight host writes before terminal completion; cancellation does not
hold the admission lock. Include previously sealed artifacts in failure evidence.

**Reason:** Ordinary authored Python must produce reusable typed outputs without
stdout scraping, a second interpreter path, or process-lifetime object references.

## D-048 - Geometry, display mesh and independently authored inputs have separate owners

**Decision:** The CAD extension interprets versioned self-contained BREP and
indexed mesh resources with explicit length unit, Cartesian frame, tolerances,
native implementation versions, parents and semantic origins. Native topology is
decoded in consumer processes. The editor reads inert bounded metadata/meshes.
CAD consumers are ordinary intentions; promotion uses one generic authority
command to create a fresh model bound to the selected evidence artifact.

**Reason:** A mesh is an approximation, and a revision-local face index is not a
stable semantic identity. Authored region predicates are re-evaluated or reported
unresolved. Independent translation of a promoted input must not run its original
recipe or mutate retained bytes. The recipe's first frame remains authored Python
meaning; no incompatible foundation schema is silently upgraded.

## D-049 - Fields are authored intentions; sampled histories are immutable resources

**Decision:** foundation.fields@1 and code_visualizer.diffusion@1 use ordinary
domain schemas and the existing Python backend/lifecycle contract. A distinct
foundation.space@2 schema composes with math@2 without changing space@1. Closed
versioned resources describe support, interpretation, chunks, series prefixes and
portable numerical state. Registered trusted resource interpreters expose child
references; one bounded closure operation serves capture, preparation, transfer
and retention. The resource store itself does not interpret physics.

**Reason:** A larger history must increase retained bytes rather than canonical
node count or GUI memory. Shared typed interpretation keeps units, frames,
association and physical time explicit while leaving the generic kernel unchanged.

## D-050 - Retention precedes publication; trials and display clocks remain separate

**Decision:** A sealed root receipt must be durably associated with its retained
attempt before it enters the live ledger, runtime presentation or failure evidence.
Checkpoint Resume uses that association and the existing frozen-input transaction,
then validates exact numerical compatibility in the backend. Cancellation seals
the last scheduled sampled accepted state; newer unpublished work is recomputed.
The runtime keeps one latest bounded trial frame, and the viewer independently
selects exact retained samples using one active and one replaceable pending task.

**Reason:** A state file is not proof of acknowledgment or successful execution.
Publication failure must preserve earlier restart points without advertising a
new one. Renderer speed and cancellation timing must not alter the authored
sampling grid or copy numerical results into canonical parameters.
