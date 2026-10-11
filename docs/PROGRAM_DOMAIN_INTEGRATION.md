# Programming as a workbench domain

ProgramModel is specifically the canonical **Python-program semantic model**.
Python remains the implementation language, orchestrator, and supported programming
runtime. The backend protocol generalizes computation boundaries, not Python syntax
into a hypothetical universal language. See [Canonical Python program ownership](PYTHON_PROGRAM_MODEL.md)
for module/class ownership and the revision-10 cutover.

The programming domain participates through the same `DomainProvider` contract as
schema-driven domains. `extensions.builtin.program_bundle()` provides a participant
with stable root/object IDs, the `code_visualizer.program@1` representation, and its
`program.*` command namespace. The generic provider exposes each `DomainModel` through
that same read contract with its schema identity and `domain.*` command namespace.

This protocol is uniform; canonical storage remains specialized where that preserves
stronger invariants. There is exactly one authored `ProgramModel`, and no generic
`IntentionalNode` copies of its functions, expressions, symbols, or statements.

## Retained invariants

- All twenty statement families retain their typed canonical representations.
- Expression trees retain complete Python fidelity and stable expression/symbol IDs.
- The existing containment and typed command rules remain authoritative.
- DRAKON edits continue to translate directly into `program.*` commands.
- DRAKON persistence remains presentation metadata reconstructed from ProgramModel.
- Typed Python lowering, source maps, execution, tracing, and debugging are reused.
- The semantic read model and presentation notations remain derived.

The extension does not make Python text, DRAKON, generated artifacts, or a generic tree
into another owner of programming meaning. `SemanticConcept` still groups semantic
objects; it is not a schema definition. `ProjectionDefinition` still describes a lens;
editable notation policy has a separate `NotationDefinition`.

## Build participation

A project may author programming constructs directly, domain intentions, or both.
The programming contribution is already in the target representation and needs no
translation. Other domains contribute derived ProgramModel values through their
registered transformations. `prepare_build()` composes them into a temporary project
snapshot and validates identity separation before existing Python lowering runs.

Functions and symbols authored by the user retain their exact canonical values in
that snapshot. Transformed objects belong to a derived build, carry domain origins,
and disappear when the build is discarded. Saving the original project never writes
those objects into its ProgramModel.

The effective project is an input to lowering or a registered generator. It must not
be submitted as an authority snapshot or passed back through the canonical generation
entrypoint, because that would attempt to derive the same contribution twice; the
identity collision check rejects that misuse.

The registered Python generator receives `GeneratorInput(prepared_project, origins)`
and calls existing lowering and emission directly. Public canonical generation APIs
and the workbench accept an explicit `DomainExtensionRegistry`; embedded hosts use
the same registry for indexing, validation, notation, transformations, and generation.
The default composition contains computation contracts, program, generic domain,
FSM, math, space, units and SI vocabulary bundles.

## Decision against a physical generic migration

Project-authored transformation templates also construct this same typed ProgramModel
at the derived build boundary. The generic interpreter owns no second programming
store and does not weaken expression/symbol/containment types to accommodate its
initial grammar. Saved Traffic Light behavior is now authored template data, while
the installed FSM extension remains available as an implementation comparison.

Templates may first emit another schema-defined domain representation and chain it
through further stages. These intermediate models participate in the same deterministic
planner, validation and origin composition. They remain build values; the final stage
constructs the existing typed ProgramModel when Python is the selected backend.
Other registered computation backends consume their exact terminal representations
without passing through programming semantics. ProgramModel does not acquire intermediate
domain knowledge or a generic-instance mirror.

Invocation parity is independent of that decision. A shared InvocationSpec and
renderer retain callable kind and method ownership across generated and live
execution. ProgramModel and DomainWorkspace gained no invocation-specific flags.
Configured arguments are literal values shared across invocation namespaces, and
direct instance entrypoints require receiver construction that accepts zero arguments.
Programs needing setup expose a top-level entrypoint; constructor eligibility is
checked from canonical signatures without changing their representation.

The finite-state-machine slice proves that new domain storage, editable notations,
transforms, generation, and runtime origins can coexist with specialized programming
storage under one authority. A wholesale ProgramModel-to-generic-tree migration would
add a second migration boundary and weaken typed access without reducing ownership
or pipeline complexity. No such migration is needed for this workbench capability.

Future programming domains or languages may use either generic schema-driven storage
or a specialized representation, provided their provider, commands, validators,
generators, and origins obey the same workbench contracts. Any later physical migration
must independently prove complete fidelity and simplify the implementation while
preserving all current structural, execution, mapping, and performance tests.

## Canonical ownership and the terminal cutover

`ProgramModule` and `ProgramClass` now own ordered Python declarations under stable
project identities. Functions retain their mature typed table representation and
have exactly one owning declaration reference. Package, entrypoint arguments and
startup declarations are canonical ProgramModel contents. PythonRuntimeSettings contains
only run profiles and the active profile.

The cutover preserves these boundaries:

- Module and class object IDs are opaque project IDs, never global contract names.
- Generated Python is the published `code_visualizer.python.source` representation,
  a disposable build result with source/origin maps.
- Native format 10 migrates legacy executable setup into canonical declarations.
  Portable terminal format 2 carries that complete ProgramModel and excludes
  executable ModuleSetup. Its versioned logical-type contract changes with the
  terminal payload; the former terminal interpretation is not silently reused.
- Native format 11 distinguishes ordinary modules from authored package initializers
  and names the separate runtime-settings record accurately.
- Generated execution, live Run/Trace/Debug and portable workers execute the same
  emitted package tree. Code previews display real generated modules; combined
  source is presentation only. File-qualified source/runtime origins retain semantic IDs.

See [Python ProgramModel](PYTHON_PROGRAM_MODEL.md) for the implemented ownership,
migration and validation rules.
