# Project-authored domain languages

`DomainWorkspace.language_definitions` owns inert `AuthoredDomainLanguage` values.
Each language pins one schema ID and version and contains editable notation
definitions, validation rules, and domain or program transformation templates. The schema,
language definitions, and intentional instances are canonical project data. Their
compiled behavior and generated programs are disposable derived values.

An authored language has a stable ID, its own version, and a separate `syntax_version`
that identifies the supported grammar. Versioning a language does not select Python
code. Unsupported syntax versions remain loadable and saveable, with an explicit
diagnostic that prevents dependent builds.

## Authoring in the desktop

Open **Domain Workbench > Language authoring**. Choose **New language**, or select an
existing language and **Edit definition**. The structured tree exposes notations,
rules, and transformation templates as typed slots and collections. Select a slot,
choose its node kind, and use **Set kind** or **Add item**. The adjacent form edits
scalar values, operators, schema properties and roles, domain query bindings, and
runtime symbols. **Apply fields** changes the draft; **Save** submits one
version-checked `PutDomainLanguage` command to the authority. **Up**, **Down**, and
**Remove** manage structured ordering. Holes can be saved while a definition is
incomplete.

Use **Preview notation** to display the selected domain model with an authored graph,
table, hierarchy/form, or composed notation. **Build model** and **Trace** use the shared transformation,
Python, and runtime pipelines. Reopening a definition edits its existing identities.
No persistence JSON or imported Python is required to define this behavior.

## Composition and ownership

```text
canonical project revision
  domain schema + instances + authored language definitions
                              |
            resolve_domain_languages(project, host registry)
                              |
                disposable schema-scoped contributions
                 /                |                \
            notations         validators       transformations
                 |                                 |
           typed edits                         ProgramModel
                 |                                 |
          same authority                    Python / runtime origins
```

The resolver uses the statically registered language interpreter. It does not load
plugins, import project-selected modules, evaluate Python strings, or attach callbacks
to persisted objects. Host implementations remain registered extension code.

`SchemaLanguageContribution` binds compiled behavior to an exact schema ID and
version. It does not claim ownership of that schema or manufacture a synthetic
bundle. A user-authored schema keeps `bundle=None`. Existing bundled schemas retain
their existing ownership checks.

The kernel, notation service, validation, and Python build use the same resolver.
Resolving an already composed registry rebuilds from its host registry and the current
canonical definitions. Deleted or edited rules cannot survive as stale registrations.
Duplicate contribution identities are diagnostics; competing valid transformation
paths are explicit ambiguities. Registry ordering never chooses between meanings.
An incomplete transformation keeps valid independent notations and validators
available, so authoring can continue. Its diagnostic still blocks generation.

## Typed query vocabulary

Queries inspect the immutable domain snapshot while validating or generating:

- literals, variables, concept instances, owned/reference roles, properties, and IDs;
- tuples and collection mapping, filtering, universal predicates, and uniqueness;
- Boolean and comparison operators, containment, addition, count, and first element.

Every query node has a stable owned identity. Bindings refer to explicit binding IDs;
property and role access uses schema IDs. The checker follows possible concept types
through role paths and rejects missing members and incompatible operators. Queries
cannot access the filesystem, import packages, or invoke arbitrary Python functions.
Traversal and interpretation have explicit depth, operation, collection, and output
limits.

## Validation rules

A `ValidatorDefinition` selects one concept, binds each instance, and evaluates a
Boolean predicate. A false predicate emits its configured diagnostic against the
intentional object. Validation runs through the existing project assessment and
workbench diagnostic surfaces. Invalid instances remain canonical authoring data;
generation requires the project to satisfy its rules.

Query slots also have a readable expression editor. Contextual bindings name the
objects already in scope, so a rule can be written as:

```text
count(machine.States) >= 3
every(machine.Transitions, 'transition',
  first(transition.Source) in machine.States)
```

Property and role access resolves human names against the source schema. Names with
spaces use `prop(machine, 'Event cycles')`; explicit `prop` and `role` calls can also
select a stable identity when names are ambiguous. `first`, `count`, `identity`,
`nodes`, `map`, `where`, `every`, and `unique` operate on immutable domain values.
Ordinary comparisons, `and`, `or`, `not`, `in`, and addition compile to the existing
query types. `hole('Finish later')` preserves an incomplete editable slot.

The same checker validates structured and textual edits. Text edits update only the
typed query draft, retain matching syntax identities, and use the existing language
command on Save. No separate expression source is persisted. Changing a validator
expression changes diagnostics; changing a transformation's scalar query changes
the generated implementation through the existing pipeline.

## Program templates

An `AuthoredTransformation` contains an ordinary versioned `TransformationDefinition`
and typed function templates. Each function template selects source domain objects;
its generated function and descendants receive deterministic identities and origins.
Template symbols and parameters have stable identities distinct from runtime names.

Build-time expansion, conditional expansion, and local bindings select what program
structure exists. Runtime expression nodes describe literals derived from queries,
symbol references, operators, and a bounded set of explicit built-in functions.
Statement templates describe assignment, output, conditionals, loops, and transfers.
These values construct the existing strongly typed `ProgramModel`; they never become
a competing executable representation.

Program templates generate synchronous functions. Programming remains the mature
specialized domain; its complete physical model is retained.

## Intermediate domain templates

Syntax version 2 adds `DomainTemplate` as an alternative output of an
`AuthoredTransformation`. Select an exact target schema and version, then add node
templates selecting source objects and declaring their target concepts. Property
templates evaluate scalar queries. Containment and reference templates identify a
target node template and query the source objects whose generated nodes they need.
All nodes receive deterministic identities before roles are bound, so forward and
cyclic references do not depend on template ordering. Containment remains acyclic
and has exactly one owner under the ordinary domain validator.

This permits authored A → B → C → ProgramModel pipelines. B and C schemas and language
definitions are canonical authoring data; their generated instances are disposable.
Each stage consumes the preceding immutable result, validates its target schema and
registered rules, and composes origins back to A. The planner uses exact schema IDs
and versions alongside representation names, retaining explicit dependencies,
cycle rejection, and ambiguity diagnostics. No intermediate instance is saved in
`DomainWorkspace.models` or submitted to the authority.

Syntax 1 remains readable for existing direct program templates. Intermediate outputs
and composed notations require syntax 2; unsupported grammar versions remain preserved
with explicit diagnostics.

Origin clauses name source domain objects responsible for an emitted statement.
Without an explicit clause, enclosing source origins apply. The common executor
checks complete origin coverage and composes maps across subsequent transformations.
Generated Python uses the existing emitter and invocation contract, and existing
Run/Trace/Debug return runtime activity to the original domain objects.

## Notations, selection, and persistence

Authored notations use the existing independent `NotationDefinition` contract:
graph node/edge rules, table columns, and hierarchy/form presentation. Property and
reference paths resolve to intentional IDs plus typed edit affordances. Editing a
cell submits a semantic command to the same authority; rendered values are never
diffed or imported to reconstruct meaning.

Select a notation in the language editor and choose **Edit notation expression and
preview…** to compose a readable notation with a live, disposable preview. For example:

```text
each('State', 'state', box(
  column(text('Current state'), field('state', 'Name'))
))
```

`row`, `column`, `wrap`, `box`, and `text` compose layout; `fraction`, `superscript`,
and `subscript` compose formal notation. `at` and numeric property coordinates support
positioned diagrams; `path` and `connect` add geometry and semantic links. `when`
selects conditional notation. `related` traverses a declared role or an authored
semantic relationship, and `each(..., scope='workspace', schema='namespace',
version='1')` selects another exact schema across domain models.

The expression parser resolves human concept, property, and role names to stable
schema IDs. Ambiguous names require an explicit identity. Only the closed notation
grammar is accepted: there is no evaluation of Python, arbitrary calls, or imported
behavior. The text is an editor buffer over the typed AST, never a second persisted
representation. Reapplying edits preserves identities in matching structural slots
and keeps lexical binding identities when their display names change. Save uses the
same language-authority command as the structured editor.

The normal authored Traffic Light example includes **Transition sentences** alongside
its graph, table, and hierarchy. Its editable state/event names and transition
sentences are compiled from this generic vocabulary, with no FSM-specific renderer.

Language, notation, validator, transformation, and template identities appear in
the derived semantic index. Their containment and schema references support shared
selection, navigation, semantic lenses, and text search. Notation column keys remain
local presentation identifiers rather than global semantic objects.

Native persistence stores only the closed typed grammar and canonical values.
Language edits use the existing authority revision, conflict, event, and undo/redo
contracts. Holes and incomplete typed expressions are diagnosed explicitly; generated
artifacts and resolved callback closures are never saved as canonical data.

The typed SDK commands are `PutDomainLanguage`, `DeleteDomainLanguage`,
`PutDomainNotation`, `DeleteDomainNotation`, `PutDomainValidator`,
`DeleteDomainValidator`, `PutDomainTransformation`, and `DeleteDomainTransformation`
in `application.language_commands`. Remote operations use `domain.language.put/delete`
and `domain.language.notation/validator/transformation.put/delete` through the same
authority. Mutation requests carry the expected project revision. Fine-grained puts
replace one stable definition identity; undo restores exact definition order.
