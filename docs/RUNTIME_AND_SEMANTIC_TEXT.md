# Runtime time and semantic text

## Program by time

The runtime registry keeps a bounded immutable timeline per execution session. Every
state carries execution identity, project revision, artifact revision, event sequence,
semantic location, and an identity-preserving runtime object graph. Storage remains a
compact checkpoint/delta stream; `graph_at(step)` reconstructs from the nearest
checkpoint and a small LRU holds only recently viewed graphs. The default bound is 500
states. Starting a named session resets that session's prior timeline; closing the
project clears all runtime state. Interactive Debug and recorded Trace produce this
same event format.

The Code Visualizer provides **Previous**, **Next**, a timeline slider, and **Live** for
every lens. `RuntimeOverlayContext` supplies the selected state, its previous state,
adapter, and focused binding. Architecture, Calls, Control, Data, DRAKON, and saved
lenses can therefore show active semantics and values without changing their base
projection. Selecting history changes only presentation state. It never rewinds the
child process and never writes observed values into `project.json`. If code advances
beyond the execution revision, the visualizer reports the pinned revision explicitly.

The overlay marks:

- every node whose semantic anchor matches the paused operation;
- the visible route from the previous semantic location to the current one;
- matching symbol nodes by canonical symbol ID and frame ID, including changed state
  and a bounded value preview;
- a bounded runtime value subgraph using the selected adapter.

The Dijkstra example is the reference path: step the algorithm, observe the active
DRAKON glyph and incoming edge, see `frontier` marked changed, inspect the heap topology,
then move the timeline backward and see the same projections resolve the earlier state.

Use `runtime.active`, `runtime.sessions`, or `runtime.history` from automation.
`analysis.runtime_history` is discoverable through the capability registry, and MCP
offers `active_runtime` and `runtime_history`.

## Data-structure adapters

The same runtime identities can be inspected as:

```text
Auto | Generic | List | Queue | Heap | Graph | Matrix | Tree | Mapping |
Tensor | DataFrame
```

Auto uses the focused binding name and safe observed container shape. A queue becomes
a front-to-back chain, a heap uses parent/child index topology, graph data uses radial
layout, matrix data uses a grid, and trees retain hierarchy. Choosing an adapter never
calls user properties or mutates the object. Per-binding Focus bounds large frames and
makes the selected structure's role explicit through badges.

Debugger graph identity and revisions must match the containing debug event. The
registry rejects mismatched observations instead of silently combining states.

## Semantic Text tab

The Code Visualizer's **Semantic Text** tab renders the current lens as deterministic,
identity-mapped text. Clicking an object or relationship line publishes the same
selection used by DRAKON, graph views, generated source, design glyphs, automation, and
runtime focus.

The lower editor exposes supported canonical fields for the selected item. Applying a
change issues an ordinary typed command, so validation, events, persistence, undo, and
agent observation behave exactly as they do for graphical edits. The initial surface
supports:

- project title;
- function identifier, human name, and documentation;
- DRAKON Python expression fields exposed by the semantic index;
- concept name, explanation, and tags;
- authored relationship label and explanation.

Structural changes still use their specialized editors and commands. The text outline
is not editable generated Python, and unsupported semantic items clearly remain
read-only. This is an incremental textual interface into one program, not source-code
round-tripping or a second parser-owned program.
