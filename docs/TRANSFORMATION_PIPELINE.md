# Transformation pipeline

The scoped planner also supports registered computation terminals beyond Python.
`generation.computation.prepare_computation()` prepares an explicit backend request;
`generation.build.prepare_build()` remains the Python composition boundary. See
[Computation backends and evidence](COMPUTATION_BACKENDS.md) for portable terminal
resources, backend admission, typed observations, and runtime evidence.

`generation.build.prepare_build()` accepts one immutable project revision and an
explicit `DomainExtensionRegistry`. Omitting the registry selects the statically
composed built-ins. It returns a disposable `BuildSnapshot`: the effective project
for lowering, an immutable `OriginMap`, and the transformation identities used.
Nothing in this operation writes to the authority or project persistence.

```text
canonical Project at revision N
  ProgramModel              domain models and schemas
       |                              |
       |                   unique transformation paths
       |                              |
       +---------- derived composition boundary
                              |
                    effective ProgramModel
                              |
                    existing PythonProjectIR
                              |
                    existing Python emitter
                              |
            Python + source map + domain origin map
```

## Definitions and registered implementations

`domain.transformation` contains inert value types:

- `Representation(id, version)` names an input or output contract.
- `TransformationDefinition(id, version, source, target, depends_on, description)`
  identifies a transform and its prerequisites. A prerequisite is an exact
  `id@version` key.
- `OriginLink(generated_id, source_ids)` relates a derived object to every source
  intention that caused it.
- `OriginMap(project_id, revision, links)` pins those relationships to an immutable
  semantic revision.

`generation.transformation.RegisteredTransformation` pairs a definition with trusted
implementation code. The implementation receives a `TransformationInput` containing
the immutable project, owning domain model, current representation and value, and
input origins. It returns a `TransformationResult` containing the output
representation/value, origins, and optional entrypoint candidates.

These callables are registered by extension bundles at the composition boundary.
Project files contain schema data, bundle references, and optional inert authored
language definitions. A fixed interpreter compiles those typed definitions into
disposable registered contributions. Project data cannot name an import, load a
callback, or execute arbitrary source as a transform. See [Domain language](DOMAIN_LANGUAGE.md).

`RegisteredTransformation.schema_id/schema_version` optionally scope a registration
to one exact schema contract. Authored languages and the built-in FSM always use this
scope. The planner checks the scope at each stage and follows the registered target
schema to the next stage, even when multiple schemas share a namespace representation.
Execution checks both source and target scopes again. Unscoped host transformations remain useful
for neutral intermediate representations shared across domains.

`extensions.languages.resolve_domain_languages(project, host_registry)` is the common
composition boundary for kernel reads, notations, validation, and generation. It
combines host bundles with `SchemaLanguageContribution` values derived from canonical
language data. These contributions do not become bundles or own the user's schema.
Re-resolution starts from the original host registry, so removed definitions cannot
leave stale transformations behind. Conflicting contribution identities produce
diagnostics instead of overriding registered behavior.

## Planning and ordering

Authored syntax version 2 can target a user-defined intermediate schema. A
`DomainTemplate` selects source objects, emits typed target-concept nodes and scalar
properties, and binds containment/reference roles to nodes emitted by another named
node template. All target nodes are allocated before roles are resolved. This gives
references deterministic identities without relying on template declaration order.

```text
canonical A instances + authored schemas/languages A, B, C
    -> disposable B DomainModel -> disposable C DomainModel
    -> disposable ProgramModel -> existing Python pipeline
```

Schema B and schema C are authored canonical definitions; the B/C instances in this
pipeline are derived artifacts. The input snapshot retains the original project and
root model while each stage receives its current immutable value. Origins compose
from every emitted node to its immediate input nodes, then back to A. No stage inserts
its output into `DomainWorkspace.models`.

Planning states include the representation and exact schema identity/version, so a
later stage is checked against its intermediate input schema rather than the original
root schema. Explicit dependency keys still determine permissible ordering. The
executor validates every derived DomainModel against its target schema before any
subsequent stage can consume it, then runs registered target-domain validation.
Every intermediate identity must differ from canonical project identities.

The planner validates duplicate transformation keys, missing prerequisites,
prerequisite cycles, and representation cycles before executing anything. It finds
paths from a schema's namespace/version representation to a selected terminal,
including `code_visualizer.program@1` for Python. Every prerequisite must appear earlier in the selected
path. Zero valid paths is an explicit missing-path diagnostic; multiple valid paths
is an ambiguity diagnostic. Registration order and numeric priorities never choose
meaning.

Planning accepts at most 512 registered transformations and spends at most 100,000
graph/search work units. Registration streams are bounded while they are consumed.
Excessive plans fail with `TRANSFORM_LIMIT`; sorted graph traversal also makes cycle
diagnostics independent of hash iteration order.

This first contract deliberately has one input and one output per transform.
Successive rewrites of the same physical model use distinct representation versions
or named intermediate representations. Independent domain models are lowered on
their own paths and combined at the build boundary. A future multi-input transform
would need an explicit port and dependency contract rather than shared mutable state.

The executor checks each result's declared representation and revision. It composes
output-to-input origins through the preceding map, so a chain of transforms still
returns to original canonical intentions. The host validates final typed program
integrity and Python buildability before emitting artifacts.

## Ownership and composition

The authored `ProgramModel` remains canonical. Domain transformations contribute
additional functions and symbols only to the effective build model. The build checks
generated identities against all existing canonical/project/presentation identities
and against earlier contributions. Every generated identity, including expression
tree identities, must have an origin; stale origin entries and unknown source IDs
are rejected.

`derived_id(transform_key, source_id, semantic_role)` uses a deterministic namespaced
digest. Changing a state label changes generated text without changing its state ID
or the derived operation IDs. Derived IDs differ from canonical domain IDs because
they denote different objects with different ownership.

An explicitly authored programming entrypoint retains its meaning in mixed projects.
Otherwise, one derived entrypoint is selected. Multiple candidates produce an
ambiguity diagnostic and require an explicit `entrypoint_model_id` build selection
or an authored orchestration entrypoint. The
build never persists a generated callable ID as authored module setup.

## Python and runtime return path

Public `generate_python()` and `generate_python_project()` prepare domain contributions
and then call the existing lowering and emitter. They accept an optional explicit
extension registry for embedded hosts. Registered generators receive a
`GeneratorInput` containing an already prepared project and its origins, so they cannot
accidentally transform a domain twice.

The existing source map continues to identify the generated ProgramModel object.
Generated results additionally carry their `OriginMap`; disk builds containing domain
outputs write `project.origin-map.json` in the manifest-owned artifact directory.
Directly authored programming projects retain their existing artifact set.

`application.domain_execution` generates a revision snapshot and uses the existing
`trace_source` or `DebugSession` worker. A runtime event's line resolves through the
source map to a generated object; the runtime registry then resolves its original
domain IDs through the session's pinned origin map. `RuntimeSessionState.semantic_id`
retains the generated location, `origin_ids` retains its high-level causes, and
`active_ids` exposes their union. Graph, table, form, semantic lenses, and generated
code can therefore decorate their own representations of the same activity.

Origin maps cannot be replaced during a session or mixed across projects or artifact
revisions. Editing while a worker runs leaves its execution pinned to its original
snapshot. Runtime state and origins remain ephemeral and are never serialized into
the authored project.

## Finite state machine proof

`extensions.fsm` owns the StateMachine, State, Transition, Event, and Action schema,
validators, graph/table/form notations, and its transformation. Core build and runtime
code contain no FSM-specific branches.

A machine owns its states, transitions, events, and optional message actions. Its
initial-state reference selects the starting state. The default execution repeats
the ordered event list for the configured number of event cycles; the generated
callable also accepts an explicit event sequence. A transition's state/event pair is
unique within its machine. Unhandled runtime events raise an ordinary mapped Python
error. Message actions become typed output statements; there is no persisted Python
callback or arbitrary action-source evaluator.

The Traffic Light example lowers to typed assignment, loop, select, output, and
transfer nodes. Tracing Green → Yellow identifies the Transition, target State, Event,
and applicable Action. Renaming Yellow to Amber changes every projected label and the
generated messages while preserving those identities.

`tests/test_transformation_pipeline.py` exercises planning, deterministic output,
origin composition, collision and ambiguity rejection, disposable builds, mixed
program/domain ownership, native persistence, registered generation, actual Python
execution, interactive debugger stepping, and runtime revision guards.

`tests/test_language_composition.py` exercises the same path using a project-authored
announcement language: typed validation, all three editable notations, exact schema
scope, deterministic generation, real Run/Trace/Debug, source origins, missing grammar
support, and host contribution conflicts. Its source schema has no owning bundle.

`tests/test_intermediate_languages.py` authors three FSM representation languages,
lowers A through disposable B and C models, executes the existing Python pipeline,
and traces activity back to A. It covers exact schema scope, ambiguity and cycles,
invalid intermediate values, per-stage validation, canonical identity collisions,
save/load, rename stability, and template edits with undo/redo.
