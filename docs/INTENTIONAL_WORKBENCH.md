# Intentional/domain workbench

The subsequent [Universal workbench](UNIVERSAL_WORKBENCH.md) extension preserves
this ownership design while separating canonical definition and presentation policy
from derivation, computation, evidence and resources. The Python-program backend
executes ProgramModel; Python also implements the other domain backend adapters.
Math and space are ordinary foundation bundles. Closed values and versioned Protobuf
adapters extend the public contract without replacing ProgramModel or project.json.

The implementation and orchestration remain Python-native. ProgramModel is the
canonical Python-program domain, including ordered module/class ownership and
entrypoint declarations; other terminal representations may go directly to their
own Python computation adapters. General backend boundaries do not imply a
multi-language programming model. See [Python ownership](PYTHON_PROGRAM_MODEL.md).

## Phase 00: repository findings and target design

This extends Code Visualizer in place. The repository review covered the canonical
domains and codecs, authority and automation, semantic indexing and query language,
generation and isolated execution, Qt/rendering adapters, release tooling, and their
test suites. Before this extension, D-007 described complete extension bundles as a
design intention: static contribution seams registered commands and docks, but did
not compose schemas, intentional instances, editable notations, and transformations.

The existing application already supplies immutable revisions, stable identities,
typed commands and actor-aware history, deterministic persistence, complete typed
ProgramModel ownership, semantic lenses, shared selection, Python IR/source mapping,
and a revision-pinned runtime graph. These mechanisms are retained.

Current architecture before this extension:

```text
ProjectAuthority -> ProgramModel -> PythonProjectIR -> Python -> execution
                       |                                      |
                       +-> SemanticProgram -> lenses <---------+
                       +-> DRAKON editable projection
```

Target architecture:

```text
                         ProjectAuthority
                                |
                    one canonical Project revision
                       /                    \
             ProgramModel                DomainWorkspace
       specialized programming domain    schemas + intentional nodes
                       \                    /
                        -> SemanticProgram <-
                               |
                  query lenses + editable notations
                  graph / table / hierarchy and form
                               |
                 identity-bound typed semantic commands

immutable canonical snapshot -> explicit transformation plan
                                  |
                         derived build composition
                         ProgramModel + OriginMap
                                  |
                         existing PythonProjectIR
                                  |
                         Python + source/origin maps
                                  |
                     existing run / trace / debug
                                  |
                 revision-pinned runtime semantic IDs
                                  |
                  original intentions in every notation
```

## Retained meanings and generalized contracts

`SemanticConcept` remains an authored grouping. `ProjectionDefinition` remains a
query/lens policy. Neither becomes a schema or a structured editing language.
`ProgramModel` retains its physical representation, all statement/expression types,
symbol ownership, and DRAKON commands. Uniformity means a shared workbench contract,
not flattening mature typed structures into generic nodes.

New `DomainSchema`, `ConceptDefinition`, property and role definitions describe
generic domains. `IntentionalNode` and `DomainModel` own their instances.
`NotationDefinition` describes representations with explicit editable field bindings.
Complete static `DomainExtensionBundle` registrations compose data schemas and
implementation contributions. Versioned transformations and immutable origins join
domain intentions to disposable executable output.

## Canonical ownership and explicit invalid states

`Project.program_model` is the sole owner of directly authored program semantics.
`Project.domain_workspace` is the sole owner of generic schemas and intentional nodes.
They contain distinct meaning. A transformed function is never inserted into the
authored ProgramModel; a composed build value exists only for its source revision.

Intentional nodes are a flat immutable identity table. Containment roles own child IDs;
each node has exactly one owning role or is a root. There is no second parent field
to reconcile. References can form graphs, including cycles. Identity is independent
of spelling, path, order, and notation. Property/role definitions also have stable IDs.

Malformed value types, duplicate IDs or ownership, illegal target concepts, dangling
references, containment cycles, and upper cardinality violations are integrity errors.
Missing required properties and unsatisfied minimum cardinalities are explicit,
saveable incomplete authoring states that block dependent builds. This follows the
existing incomplete-expression policy and permits incremental form construction.
Unknown implementation bundles are build findings, never grounds for discarding data.

Typed `domain.*` commands enter the existing authority, transaction, revision,
conflict, event, journal, and undo machinery. A notation gesture names an intentional
ID and a property or role ID. No edit is inferred from a rendered representation.

## Dependency direction and composition

Domain modules contain frozen values and pure operations, with no Qt, application,
generation, validation, or persistence imports. Explicit codecs remain in persistence.
The application composes commands, indexing, notation editing, and execution services.

Extension implementation contracts and built-in composition live in a Qt-free
`extensions` package. Both generation and application can consume the same explicit
registry without reversing the existing generation-to-domain dependency. Registries
are constructed deterministically; no project-specified imports, eval, persisted
callbacks, filesystem plugin discovery, or import-order registration is introduced.
Duplicate and ambiguous registrations fail explicitly.

## Persistence and cutover

Format revision 6 adds the domain workspace. Revision-4 and revision-5 projects are
upgraded at the existing load boundary with an empty workspace, preserving all
existing program identities and v5 metadata-only DRAKON ownership. Schemas, instance
values, and bundle identity/version references are persisted data. Notation definitions
are registered declarative contributions; generic fallback notations derive from the
schema. Transform results, compiled notations, executable callbacks, and runtime
states are absent from native snapshots. Existing supported migrations remain
load-boundary operations rather than live compatibility models.

## Transformation ownership and origins

Each implementation declares a stable identity/version, source and target
representation, and explicit dependencies. Planning validates dependency cycles and
source/target compatibility and rejects ambiguous paths; arbitrary numeric priorities
and incidental registration order cannot select semantics. Inputs are immutable.
Generated IDs derive deterministically from source identity and semantic role.
Composition rejects collisions between contributions and directly authored programs.

An immutable `OriginMap` associates generated semantic IDs with the high-level IDs
that caused them to exist and is pinned to project identity/revision. Composition
preserves transitive origins. The existing Python lowering and source maps retain
generated IDs, while runtime sessions add origin IDs alongside the generated location.
Generated-source highlights and graph/table/form highlights therefore refer to the
same execution event. Directly authored programs retain their existing DRAKON mapping;
this first domain workbench displays derived Python without creating a derived DRAKON
editor. Older executions remain pinned to their older revision.

## Implementation phases and evidence

1. Schema/instance kernel, authority commands, validation, and v6 persistence.
2. Complete static bundles and built-in programming-domain participation.
3. Domain/schema/instance semantic indexing, queries, selection, and automation.
4. Generic graph, table, and hierarchy/form notations with direct edit bindings.
5. Deterministic transformation planning, derived composition, and origins.
6. Existing Python pipeline integration without another generator.
7. Independent finite-state-machine extension and Traffic Light example.
8. Execute its derived program using existing isolated execution.
9. Runtime backprojection through the shared runtime plane and notations.
10. Discoverable schema/instance/notation/transformation workbench UI.

Each phase runs focused tests plus dependency/architecture checks. The final gate
adds actual Qt editing, persistence/undo, deterministic generation, real trace/debug,
origin highlighting, all examples, and the complete legacy suite. Types or a roadmap
alone do not satisfy the workbench acceptance scenario. Implementation evidence and
any design changes are recorded here and in STATUS.md as the phases complete.

## Implemented vertical slice

The implementation now supplies each boundary in the target diagram. The main
automated proofs are:

| Boundary | Evidence |
| --- | --- |
| Schema and canonical instance kernel | `test_intentional_kernel.py`: scalar/schema validation, ownership, cycles, references, stable rename/move identities, exact history, native round trips and missing implementations |
| Complete bundles and semantic participation | `test_domain_extensions_and_index.py`, `test_extension_schema_ownership.py`: deterministic registration, exact schema ownership, validators/index contributions, provider ownership, search, lenses, selection and runtime presentation |
| Editable notations | `test_domain_notations.py`, `test_domain_workbench_qt.py`: reference-path table edits, graph connection gestures, schema-derived forms, shared selection, undo, stale edit rejection and an independent library domain |
| Transformation planning and builds | `test_transformation_pipeline.py`, `test_workbench_build_boundaries.py`: dependency ordering, ambiguous/cyclic paths, complete transitive origins, collision rejection, disposable output and mixed authored/derived programs |
| Python and runtime return path | Existing emitter, trace worker and debugger exercised by domain pipeline tests; original state, transition and action IDs accompany generated locations |
| Workbench and automation | `test_domain_text_and_runtime_automation.py`, `test_workbench_service_boundaries.py`: identity-bound semantic text, registered execution capability, revisions and existing access controls |
| Complete Amber scenario | `test_workbench_acceptance.py`: table rename, search, graph/hierarchy, undo/redo, native save/reload, real trace, source/origin correlation and State/Transition/Action highlighting through the live kernel |
| Legacy preservation | Complete existing suite, dependency tests, all twenty statement families, and every catalog example regenerated and executed with its views removed |

Traffic Light is example 17 in the normal catalog and saved-project export. Its
canonical ProgramModel is empty; its domain model contains the machine, three states,
three transitions, one event and one action. The build produces a derived callable
with an origin for each generated semantic identity. Table renaming retains the
state identity and its incoming references; graph and form projections simply read
the accepted revision. No synchronization or reconciliation step exists.

Implementation evidence led to these bounded choices:

- Generic storage uses a flat immutable identity table with explicit owning roles.
  ProgramModel keeps its stronger specialized representation under a shared provider
  protocol. See [Program domain integration](PROGRAM_DOMAIN_INTEGRATION.md).
- Incomplete authoring states remain saveable, while structural corruption rejects
  commands and decoding. Required fields and minimum cardinalities therefore support
  incremental schema/form editing without inventing placeholder truth.
- Notations are declarative host or project-authored contributions, or schema-derived fallbacks. The
  first vocabulary covers graph, table and hierarchy/form; persisted projects do not
  load renderer or transformation code.
- Transformations have explicit single-input representation paths. Independent model
  contributions compose only at the build boundary. Multiple runnable candidates
  require an explicit entrypoint selection instead of registry-order guessing.
- Generic runtime decorations add original intention IDs to the existing pinned
  runtime plane. Builds, origins and generated source stay outside authored snapshots.

## Project-authored language milestone

The next extension makes notation, validation and transformation behavior editable
inside the same workbench. `AuthoredDomainLanguage` is typed canonical definition
data pinned to a schema/version. Its queries and templates construct the existing
ProgramModel directly; they are neither generated Python text nor a second instance
store. Static host bundles remain available. The same revision-derived resolver
serves validation, notations, indexing, planning and execution.

The Language authoring tab edits typed slots, schema paths, bindings, symbols and
ordered bodies. Explicit holes support incremental authoring. Valid notation/rule
siblings remain available while an unfinished template blocks a build. Revision 7
preserves these definitions; `domain.language.*` uses the existing durable history.

Example 17 now proves the FSM loop with saved authored language data, without its
handwritten extension implementation. Tests also edit a runtime-loop template in
the actual structured UI and observe changed execution with unchanged intentions.
The initial grammar deliberately covers synchronous function templates, structured
control, queries and explicit built-ins; it does not expose every ProgramModel
feature or arbitrary runtime code. Host transforms retain intermediate-representation
composition. See [Workbench authoring](WORKBENCH_AUTHORING.md) and
[Domain language](DOMAIN_LANGUAGE.md) for exact scope.

Separately, one `InvocationSpec` now unifies generated and live callable execution.
Async and generator handling and class ownership are runtime-adapter responsibilities,
with no change to ProgramModel or DomainWorkspace ownership.

The final suite and extracted-archive results are recorded in [STATUS](../STATUS.md).

## Composable workbench extension

The subsequent extension generalizes the authored language in place. Typed notation
bodies compose text, editable fields, mathematics, spatial geometry and connectors;
workspace queries combine different domains through existing semantic identities.
Readable notation and query editors parse into the same owned syntax as the structured
controls. They retain direct semantic edit bindings and share runtime decorations.

Authored templates can now output another pinned schema, enabling domain A to lower
through authored intermediate languages B and C before constructing ProgramModel.
The planner tracks representation and schema scope together, validates every stage,
and composes origins back to A. Intermediate instances remain derived build values.

Real Git supplies commits, branches, diffs, staging, merges and remote collaboration.
The session boundary validates checked-out snapshots and isolates local recovery
history. Native format 8 also closes invocation context: literal argument values have
the same meaning in all launchers, and instance entrypoints needing constructor setup
receive an explicit diagnostic. No ProgramModel storage rewrite is involved.

See [Workbench composition](WORKBENCH_COMPOSITION.md),
[Notation language](NOTATION_LANGUAGE.md), [Transformation pipeline](TRANSFORMATION_PIPELINE.md),
and [Git workflow](GIT_WORKFLOW.md) for the current design and its limits.
