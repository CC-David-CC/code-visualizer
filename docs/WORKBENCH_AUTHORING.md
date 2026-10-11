# Authoring a domain language inside a project

The Domain Workbench can own the rules that explain a domain, as well as its schema
and instances. A project-authored language contains editable notation declarations,
validation predicates, and structural transformation recipes. The application ships
one interpreter for those inert values. A project does not load Python modules,
register a callback, or evaluate Python text to obtain this behavior.

```text
ProjectAuthority
  DomainWorkspace
    schemas                 definitions of valid domain contents
    models                  one canonical set of intentional objects
    language_definitions    author-created notations, rules, and templates
              |
       revision-derived resolution
              |
    existing notation / validation / transformation contracts
              |
       derived ProgramModel + OriginMap
              |
       existing Python generation and execution
              |
       original domain identities in every notation
```

`AuthoredDomainLanguage` pins a source schema identity/version. Its `version` names
the author's language revision; `syntax_version` separately identifies the supported
interpreter grammar. The current grammar is version 1. Unsupported grammar versions
preserve authored data and produce an explicit diagnostic. Installed extensions and
project-authored languages remain distinct contribution owners. Resolution creates a
disposable catalog for one project revision and never mutates the host registry.

## Notations and direct editing

Authored notations reuse `NotationDefinition` and its graph, table, and hierarchy/form
vocabulary. Their concept selections and property/reference paths are checked against
the owning schema. A field's edit binding still names its actual intentional object,
property or role, and displayed revision. Editing a referenced state's name changes
that state through the existing authority; no rendered-view comparison is involved.

A composite label is readable. Independently editable fields retain their direct
bindings. There is no attempt to infer an inverse for arbitrary string formatting.
See [Notation language](NOTATION_LANGUAGE.md) for the common renderer/edit contract.

## Queries run while authoring or building

Query values are scalars, domain objects, or immutable ordered tuples of these values.
The syntax consists of explicit typed nodes, not an expression string:

| Query | Meaning |
| --- | --- |
| `QueryLiteral` | String, number, Boolean, or null value. |
| `QueryVariable` | A value bound by a stable lexical binding ID. |
| `QueryNodes` | Objects of one concept in the input model; optionally roots only. |
| `QueryRole` | Contained or referenced objects reached through a declared role. |
| `QueryProperty` / `QueryIdentity` | A scalar property or the object's stable ID. |
| `QueryUnary` | Boolean negation, collection count, or first element. |
| `QueryBinary` | Equality, ordered comparison, Boolean operations, membership, addition. |
| `QueryTuple` | An immutable sequence of query results. |
| `QueryMap` / `QueryFilter` | Evaluate a value or predicate for each selected item. |
| `QueryAll` / `QueryUnique` | Universal predicate or uniqueness by a selected key. |
| `QueryHole` | An explicit unfinished query. |

Bindings belong to their lexical body. A map's binding is available in its value,
but not in its input collection. Bindings cannot shadow another active binding.
Property/role paths must be valid for every possible source concept. This first
interpreter scopes reference traversal to its input model; cross-model relationships
remain available in the wider semantic index.

Boolean operations short-circuit. `First` on an empty collection reports a diagnostic
instead of guessing a target. An absent property produces null; it does not recreate
a default that the author explicitly removed. Domain objects compare by identity;
Boolean true and numeric one are distinct query values. Global object selection is
ordered by stable ID. Declared ordered roles retain their order, and unordered roles
use stable-ID order during interpretation.

`ValidatorDefinition` selects a concept and binds each matching object to a predicate.
A false result produces the author's diagnostic code/message on that original object.
Schema integrity and required-field validation remain separate existing checks.

## Templates describe the program that will run

`AuthoredTransformation` retains the existing versioned source/target/dependency
description and owns one or more `FunctionTemplate` values. Each function selects
source domain objects and declares stable parameter/local-symbol identities.
Generated function spellings include a deterministic suffix. Renaming a template
symbol preserves its identity and updates every bound runtime reference.

Build-time instructions are `TemplateExpand`, `TemplateWhen`, and `TemplateLet`.
They expand a collection of source objects, conditionally emit a body, or bind a query
value. They never become runtime loops or statements by themselves. Object-based
expansion supplies stable identity independently of collection position.

Runtime statement templates currently cover assignment, output, binary if, for loops,
and return/raise/break/continue. `TemplateFor` emits an actual runtime loop;
`TemplateExpand` emits a sequence of statements at build time. Runtime expressions
contain literal query results, bound symbols, arithmetic/comparison/Boolean operators,
or the fixed `range`, `len`, `str`, and `ValueError` built-ins. Local names cannot
shadow these operations or output's `print` function. Parameters may have defaults.

This first grammar emits ProgramModel directly. It does not yet author arbitrary
intermediate representations, every ProgramModel statement family, or user-defined
runtime calls. Those are explicit language extensions; existing programming-domain
constructs and registered transformation paths retain their full capabilities.

The interpreter constructs existing typed expression ASTs directly. A domain string
containing Python-looking text becomes a string literal. There is no text substitution,
parser-based code template, Python `eval`, or import operation in this language.

## Incomplete work, identity, and limits

Query, runtime-expression, and statement holes are saveable, explicit incomplete
states. Invalid scope, paths, symbol references, transfers, or template definitions
produce diagnostics; affected transformations cannot build. The normal authority
revision/conflict/event/history contract also governs language edits.

Every emitted function, symbol, statement, sequence, and expression-tree node has a
deterministic generated ID and an origin. Its identity incorporates transformation
identity/version, source object identities, template identity, and semantic role.
Explicit `origins` queries add source causes to a statement and its descendants.
Build-time object expansion adds the bound object's identity automatically. Existing
source maps and runtime sessions carry these origins back to the authored objects.

Interpretation has fixed operation, collection, text, nesting, and generated-node
limits. An exhausted limit is an explicit diagnostic. These limits are host behavior,
not project-controlled permissions. Queries have no filesystem, environment, clock,
network, or arbitrary callback access. Executing generated programs continues to use
the existing execution capability and isolated worker.

Native format 7 persists only definitions and their typed syntax alongside schemas and
instances. It does not persist compiled callables, derived ProgramModel output, or
runtime observations. Earlier supported formats load with no authored languages.

## Traffic Light proof

The authored proof reuses StateMachine, State, Transition, Event, and Action concepts.
Its saved validation checks unique state/event transition pairs and initial-state
ownership. Its recipe initializes a state variable, loops over the machine's event
sequence, expands transitions into guarded branches, enters the target state, emits
optional action messages, and continues to the next event. Unhandled events raise
an ordinary generated error. No interpreter operation knows about state machines.

`tests/test_authored_language.py` builds and traces this recipe using a host registry
without the handwritten FSM bundle. It proves persistence, deterministic generated
identities, origins for states/transitions/actions, schema-aware diagnostics, bounded
queries, and literal treatment of code-looking domain text. Additional UI and resolver
tests exercise the same definitions through authority commands and application forms.
