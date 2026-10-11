# Editable domain notations

The Domain Workbench edits intentional objects through composed visual/textual
notations, alongside graph, table, and hierarchy/form presets. All resolve the same `IntentionalNode.id` values in the
authority's `DomainWorkspace`. Their rendered content is disposable; neither a cell
nor a graph shape stores another copy of a property or reference.

Open **Domain Workbench** from the View menu or command palette. **New domain** opens
the schema editor; **Add registered domain** installs a schema supplied by a registered
bundle. A schema contains concepts, typed value properties, containment roles, and
reference roles. Property controls expose types, defaults, required values, choices,
and numeric bounds. Role controls expose allowed concepts, cardinality, and ordering.
Definition identities remain stable when their names change.

Choose **New model**, then **New object** or **Add child**. The form derives its fields
and target choices from the selected concept. **Apply fields** submits one transaction;
Move, Up, Down, Delete, Undo, and Redo use the same authority commands. Invalid changes
are reported without replacing the accepted model. The Diagnostics tab shows
incomplete fields, structural issues, missing extensions, registered validation
findings and transformation-plan errors with semantic selection targets. Revealing
an indexed schema, concept, property or role opens its exact definition in the
Schema and extensions tab, preserving shared selection by stable identity.

## Definition vocabulary

`domain.notation.NotationDefinition` is separate from the existing
`ProjectionDefinition`. Projection definitions select and arrange read-model objects;
notation definitions additionally bind visible values to explicit edit targets.
Bundles register declarative notation definitions, and every user schema receives
generic graph, concept-table, and hierarchy/form definitions automatically.

The **Language authoring** tab also stores project-owned notation definitions.
Choose **New language**, select **Notations** in the structured tree, and use
**Add item**. Set the notation kind, included concepts, graph node/relationship
rules, or table columns through typed fields. A column's binding can select a
property directly or follow an ordered sequence of reference roles first.
**Apply fields** updates the draft; **Save** submits the language definition to
the authority. **Preview notation** opens the selected definition against the
current model. These definitions persist across save/reload and support undo.

The same editor exposes typed validation queries and program templates, including
the distinction between expansion over domain objects while building and loops
in the generated program. See [Domain language authoring](DOMAIN_LANGUAGE.md).

| Definition | Meaning |
| --- | --- |
| `NotationKind` | Graph, table, hierarchy/form presets, or composed notation. |
| `concept_ids` | Optional concept filter for graph nodes or table rows. |
| `NotationNodeRule` | Concept, optional label property, or an ordered set of label fields. |
| `NotationEdgeRule` | Relationship concept, source/target reference roles, and label fields. |
| `NotationColumn` | Stable column ID, visible title, field path, and editability. |
| `NotationField` | Explicit reference-role traversal followed by a property or reference target. |
| `layout` | Hierarchical, horizontal, radial, or grid graph layout. |
| `body` | Optional typed composition of text, editable fields, geometry, and object queries. |

## Composed visual and textual notation

The three presets are convenient starting points. A `COMPOSED` definition instead
uses `domain.notation_syntax` primitives, which can be nested without a new renderer
or domain-specific flag:

| Primitives | Use |
| --- | --- |
| Text, editable field | Tokens, prose, property values, explicit reference selectors. |
| Row, column, wrap, positioned group | Inline notation, documents, cards, free placement. |
| Box, rectangle, rounded shape, ellipse | Bound object shapes containing other notation. |
| Repeat, conditional | Render queried objects or select a presentation branch. |
| Fraction, superscript, subscript | Mathematical notation with editable semantic values. |
| Numeric coordinate, positioned element, path | Property-driven positions, timelines, diagrams. |
| Connector | Join two bound semantic objects, preserving their identities. |

In **Language authoring**, select a notation and choose **Edit notation expression
and preview**. The concise expression surface and the structured body tree edit the
same typed AST. The live preview uses the current model and semantic index; saving
the dialog updates the language draft. Saving the language submits one authority
command. The **Composed** tab renders the saved definition; double-click a bound
field or press F2 to edit its canonical property or reference.

For example, a notation can combine measurements and their linked requirements:

```text
each('Sensor', 'sensor',
  row(
    box(column(field('sensor', 'Name'),
      fraction(field('sensor', 'Reading'),
        superscript(text('s'), text('2'))))),
    related('sensor', 'implements', 'requirement',
      row(box(field('requirement', 'Summary')),
        connect('sensor', 'requirement'))),
    gap=50))
```

Concept, property, and role names resolve to stable schema IDs; ambiguous names
need a qualified or explicit identity. The closed expression grammar accepts only
declared constructors and literal options. It never evaluates Python or arbitrary
calls. Expression text is an editor buffer; persistence saves only the typed AST.
Matching structural slots retain their syntax IDs, and changing a repeat's displayed
alias preserves its lexical binding ID.

Object queries normally read the selected model. An explicit
`each(..., scope='workspace', schema='example.other', version='3')` can select
objects in another domain using an exact schema/version pin. `related` follows
declared domain roles or indexed semantic relationships, including authored links
between models. A joined field's edit binding retains its actual owning model and
node; it never writes a copied value into the displayed model. Ordinary domain
reference roles retain their schema/model integrity rules; cross-domain semantic
links are separate canonical relationships.

The compiler charges both expansion and query scans against a bounded budget.
Unresolved bindings, invalid paths, unavailable schema versions, and invalid numeric
geometry produce diagnostics. Repeated objects have distinct display occurrence
IDs while sharing one canonical node ID. Connectors choose the nearest lexical
occurrence and prefer its enclosing box; ambiguous anchors are diagnosed rather
than selected by rendering order. Negative positions remain visible in the canvas
bounds. Runtime highlighting is disposable and revision-pinned.

The authored Traffic Light example includes **Transition sentences**, built from
these same primitives, alongside its graph, transition table, and hierarchy.

## Readable validation and transformation queries

Select a query in the language editor and choose **Edit query expression**. Property
access and comparisons such as `item.Reading > 12` resolve into the existing typed
query AST. The dialog shows the available lexical objects, checks the expression's
type, and preserves binding identities. Collection operations such as
`where(nodes('State'), 'state', state.Name != '')` use declared aliases and schema
members. These expressions can author validators and transformation queries without
building each comparison through the tree. The surrounding statement/template tree
still makes build-time expansion and generated runtime control flow explicit.

Domain-output templates also expose a target schema selector. Target concepts,
properties, and roles come from that schema; source queries remain scoped to the
input schema. Changing the target updates its pinned version and the transformation
contract. Generated intermediate domain models remain disposable pipeline values.

Fields are typed paths, not executable expressions or Python attribute lookups. A
path follows named reference-role IDs; traversal is bounded to 64 roles. A property
terminal requires exactly one resolved owner to be editable. Ambiguous or unresolved
paths stay readable without guessing an edit target.

For example, a citation table can edit the title of the book it references:

```python
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationField,
    NotationKind,
)

citations = NotationDefinition(
    "library.citations",
    "Citations",
    NotationKind.TABLE,
    concept_ids=("library:citation",),
    columns=(
        NotationColumn(
            "source_title",
            "Source book",
            NotationField("library:book:title", ("library:citation:source",)),
        ),
    ),
    schema_id="library:schema",
)
```

The cell displays the referenced book's title. Its edit binding contains the book's
node ID and title property's ID. Renaming that cell issues `SetDomainProperty` for
the book, so every other citation and notation immediately uses the new title.
The citation's reference keeps the same target identity. A field with reference-role
IDs and no property terminal instead exposes an explicit target-selection editor;
it issues `SetDomainReference` for the final role's owner.

## Graph editing

A graph rule can render intentional relationship objects as edges between the objects
named by their source and target reference roles. The edge retains the relationship
object's semantic ID. Multiple connections and self-loops receive distinct routes.
Fallback graphs show ordinary containment and references using indexed relationship
identities.

Select a node or edge to edit its schema-derived form. Shift-drag between two nodes
to connect them. A relationship rule opens a creation form with the source and target
already selected; remaining fields and references use normal schema controls. The
new relationship becomes a child of the unambiguous common owner's permitted role.
An ordinary reference connection offers the allowed source reference roles instead.
The gesture never infers control semantics from where an object was drawn.

## Compilation and edit boundary

`application.notations.compile_notation` returns immutable graph, row, cell, and tree
DTOs. A `NotationEditBinding` carries the owning model, node, field, displayed revision,
scalar/role definition, and allowed reference targets. `notation_edit_command`
translates that binding into a typed command and rejects stale displayed revisions.
The SDK submission also supplies that revision, so a concurrent change cannot
silently redirect a previously displayed reference path.

The Qt workbench uses `ProjectKernel.notation`, which composes registered runtime
decorations with the definition. Widgets submit commands through the existing
`CodeVisualizerClient`; they do not mutate node properties or reconstruct models
from graph shapes, table text, or tree positions. Read-only cells never acquire an
implicit write operation.

## Selection, transformations, and execution

Graph nodes, relationship edges, table cells, hierarchy items, diagnostics, and forms
publish stable semantic identities through the shared selection service. A referenced
property cell selects the referenced object it edits. A runtime observation carries
generated and original intent identities, allowing the same pause to highlight a
domain object, a table cell, and its generated Python span.

Build, Trace, and Debug use the selected model's registered transformation pipeline.
The Generated Python tab is read-only and maps selection through the build's origin
map. Debug uses the existing debugger and runtime registry; Step, Continue, and Stop
control that session. Generated functions and observed values are never installed as
editable canonical objects. Runtime state remains pinned to its project revision;
an older runtime observation is identified as stale after an authored edit.

The Traffic Light bundle demonstrates this contract with state nodes, transition
edges, a Source/Event/Action/Target table, and hierarchy/form. Those concept and role
names occur only in its schema and declarations. A separate library/citation test
uses the same renderer and cell-edit service without state-machine behavior.
