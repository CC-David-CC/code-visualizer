# Semantic projection language

## Purpose

A projection is a disposable answer to “show this program from this point of view.” It
does not own executable meaning and it does not copy Python. Architecture, Calls,
Control, Data, Concepts, and author-created lenses compile through the same Qt-free
pipeline:

```text
semantic program -> scope -> relation traversal -> object filtering
                 -> grouping -> decoration -> label style -> layout -> scene/text
```

DRAKON remains a specialized structural notation because its routes and editing rules
carry formal control semantics. Runtime data remains ephemeral, but a
`RuntimeOverlayContext` can decorate any compiled projection rather than requiring a
separate runtime-only lens.

## Definition vocabulary

`ProjectionDefinition` is persisted with the project and contains:

- `scope_id`: optional semantic root;
- `object_kinds`: selected semantic object kinds, or all when empty;
- `relation_kinds`: relationships to follow, or all when empty;
- `direction`: outgoing, incoming, or both;
- `max_depth`: bounded traversal depth from 1 through 64;
- `grouping`: none, owner, authored concept, or semantic kind;
- `decorations`: kind, detail, and anchor state badges;
- `label_style`: short, detail, or qualified ownership path;
- `layout`: hierarchical, horizontal, radial, or grid;
- `include_scope`: retain the chosen root even when its kind is filtered;
- `include_isolated`: retain matching but unconnected objects.
- `node_limit`: bounded visible-object budget from 2 through 1000;
- `focus_ids`: stable semantic objects that seed relevance ranking;
- `expanded_ids`: semantic nodes whose next expression depth is visible.

Expression roots are meaningful objects; their typed-tree descendants are hidden until
the root is expanded. When a result exceeds its object budget, compilation starts from
explicit focus, shared selection, or active runtime identity and ranks graph distance
over control, call, read/write, and branch relations. It retains useful shortest paths
and owner context where the budget allows, then reports omitted counts by semantic
kind. The Data built-in uses a budget of 50, so Dijkstra opens as an algorithm/symbol
view rather than a dump of hundreds of expression nodes.

The **New Lens** dialog exposes this vocabulary without requiring Python. Saved lenses
appear in the View selector and survive save/load/undo. The command palette can open
every built-in lens, compose a lens, create concepts, relate selected objects, and
materialize the current lens.

## Authored meaning

`SemanticConcept` groups program objects that the author considers related even when
their Python modules differ. It has a stable identity, name, explanation, members, and
tags. `AuthoredSemanticRelation` records one of these explicit meanings:

```text
associates | depends_on | explains | implements |
communicates_with | precedes_conceptually
```

Concept membership lowers to `conceptually_contains`; authored relationships lower to
`authored` in the read model. Neither changes generated Python or DRAKON control flow.
They are validated, journaled, undoable, queryable, and available to human and agent
clients through the same commands.

## Editable compositions

**Make Mind Map** and **Make Canvas** create ordinary editable live-view documents.
They persist the definition and presentation overrides, then recompile semantic content
for every revision. Real topics/shapes keep `semantic_id`; real cross-links/connectors
keep `semantic_relation_id`. Synthetic grouping glyphs remain annotations.

An anchored label follows semantic rename while `label_override` is null. Editing the
label deliberately creates an override; **Use Live Label** clears it. Mind-map notes,
collapse state, links, and attachments and freeform bounds, style, layers, and guides
remain authored presentation. Manual unanchored topics/shapes remain annotations.

## Python and automation

An embedded client can persist and preview a lens:

```python
from code_visualizer.domain.projection import (
    ProjectionDefinition,
    ProjectionLayout,
    TraversalDirection,
)
from code_visualizer.domain.semantic import SemanticRelationKind

definition = ProjectionDefinition(
    "lens_calls_from_main",
    "Calls from main",
    scope_id="diagram_main",
    relation_kinds=(SemanticRelationKind.CALLS,),
    direction=TraversalDirection.OUTGOING,
    layout=ProjectionLayout.HORIZONTAL,
    include_isolated=False,
)
client.put_projection_definition(definition)
projection = session.kernel.compose_projection(definition)
```

Remote clients use `query.projection_definitions` and
`query.compose_projection`. `view.compose` is also discoverable through
`service.operations`, and `capability.invoke` invokes it generically. Mutation command types are `semantic.concept.put/delete`,
`semantic.relation.put/delete`, `projection.put/delete`, and
`projection.materialize`.

## Truth boundary

- A definition is presentation policy, not executable semantics.
- A materialized mind map/canvas is a composition, not a second control-flow truth.
- Generated Python is an artifact.
- Runtime adapters never enter project persistence.
- All edits to canonical meaning go through typed authority commands.
