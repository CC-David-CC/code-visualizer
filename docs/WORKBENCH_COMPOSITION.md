# Composable notation, intermediate languages, and Git

This extends the existing authority, schema kernel, language interpreter, build
planner and execution adapters. ProgramModel and DomainWorkspace retain their
canonical ownership. SemanticConcept remains an authored grouping;
ProjectionDefinition remains a semantic lens.

## Gaps in the preceding delivery

1. A notation selected one of graph, table or hierarchy/form renderers. Users could
   configure those families, but could not compose their own notation grammar.
2. Authored transformations terminated at ProgramModel. Intermediate schemas could
   be defined, but the template language could not emit their instances.
3. Queries and templates were editable as typed trees, with limited concise syntax
   for human authoring.
4. Native journal history supported local undo, but there was no integrated Git
   workflow. Naively switching branches would allow a larger local journal revision
   to resurrect the prior branch's model.
5. InvocationSpec still accepted namespace-dependent argument text and assumed an
   instance receiver could always be constructed without arguments.

## Target contracts

```text
ProjectAuthority
  schemas + intentional instances + authored language definitions
        |                         |
        |                         +-- typed notation grammar
        |                                |
        |                         primitives + direct edit bindings
        |                                |
        |                         text / formula / geometry / layout
        |                                |
        +<-------- typed commands by stable intentional identity
        |
        +-- Domain A -> derived Domain B -> derived Domain C -> ProgramModel
                  immutable snapshots + composed origins             |
                                                             existing Python IR
                                                                    |
                                                        shared invocation + runtime

saved canonical project <-> Git working tree / index / commits / branches
                             explicit conflict and validated reload boundary
```

## Notation ownership

A notation body is a typed, inert tree of visual/textual primitives, explicit field
bindings, repetition, conditions and layout. Rendered positions and strings are
disposable. Graph/table/form remain useful presets. They do not limit the shape of a
user-authored body. Mathematics uses composition such as fractions and superscripts;
structured text uses tokens, editable fields and ordered groups. Geometry and paths
support other spatial notations without teaching the domain kernel their meaning.

Workspace queries may bind objects from multiple schema/model domains. Authored
semantic relationships connect cross-domain identities. Each editable field retains
its actual owning model, node, property/role and revision; a joined view never creates
a shadow domain instance or infers edits from rendered differences. Selection and
runtime decorations use the same existing stable IDs and origin plane.

The concise authoring syntax parses into this same typed notation tree. The tree and
its text rendering are not two stored truths. Project files contain no callbacks,
imports, Python execution or dynamically loaded renderers.

## Intermediate languages

A domain-targeting transformation names an exact target schema/version and a typed
node template. It allocates deterministic node identities, evaluates properties,
then resolves containment and reference roles against those identities. Each output
must satisfy its schema and registered validators. Exactly one output family is
chosen: domain output or existing program-function templates.

Planning tracks representation and schema scope at every edge. A later B-to-C stage
is checked against B, not against the original A schema. Explicit dependencies,
cycle checks and ambiguity diagnostics determine order. Intermediate instances are
derived build values; only their schemas and transformation definitions are authored.
Origins compose through every stage back to original canonical intentions.

## Git boundary

Git is the version-control implementation. The app supplies reviewable status,
diffs, staging, commits, history, branches, merges and explicit remote actions using
the Git executable without shell composition. There is no separate semantic merge
engine and no automatic commitment of the user's working tree.

Working-tree changes require a saved canonical revision and a clean switch/merge
boundary. Conflicted or invalid project JSON cannot be loaded into the authority.
An external-HEAD/conflict barrier prevents autosave from overwriting branch changes.
Validated reload reads project.json directly and retires the preceding session;
untracked local recovery history is archived rather than replayed over another
branch. This reuses the normal session lifecycle and one active authority.

## Invocation context

Configured arguments are immutable positional/keyword literal values. A compact
editor notation is parsed without evaluating Python; names, calls, arithmetic,
unpacking and other namespace-dependent expressions are rejected. Supported values
are finite scalars, lists, tuples and string-keyed dictionaries. A legacy expression
is preserved as explicit unresolved notation, with a build diagnostic.

Direct execution of an instance method requires a constructor signature that accepts
zero arguments. Required constructor parameters produce a diagnostic before generation
or execution. Programs requiring receiver setup expose a top-level entrypoint. The
focused live closure includes the receiver's canonical class methods and initializer.
This closes invocation context without creating a receiver-construction language.

`bind_invocation` also binds the configured arguments to the canonical parameter
signature. It uses Python's `inspect.Signature.bind()` with placeholder values for
arguments, implicit receivers and present defaults. Positional-only, keyword-only,
variadic and duplicate-binding rules therefore share one implementation. An invalid
call produces `INVOCATION_ARGUMENT_MISMATCH` before generation or execution. Defaults
and annotations are never evaluated by this check. Saved-project validation checks
the saved configuration; a selected diagram's arguments apply only to its temporary
execution snapshot. The persisted argument representation remains unchanged.

The [from-blank authoring proof](DOMAIN_AUTHORING_PROOF.md) creates its schema,
instances, notations, validator and transformation through ordinary authority
commands. It records a reproducible command sequence and runtime highlights over
the same original objects without importing example factories or an FSM extension.

## Persistence and invalid states

Native format 8 stores typed invocation arguments and the new notation/domain-output
syntax. Earlier supported formats migrate once at load. Language grammar 2 adds the
new authored syntax; grammar 1 remains supported for earlier definitions. Missing
implementations, explicit holes, invalid paths or incomplete definitions remain
diagnostic authoring states. Malformed slots, ownership violations, duplicate IDs,
unresolved Git conflicts and incompatible branch snapshots cannot silently enter an
accepted canonical revision.

Focused tests precede full regression. Required proofs include context-independent
invocation parity, composed cross-domain edits/runtime identity, authorable multi-stage
lowering with origins, and actual Git operations against temporary repositories.
Implementation details and final evidence are recorded in the component guides and
STATUS.md.
