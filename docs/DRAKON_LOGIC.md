# DRAKON logic and visual reading

DRAKON is the executable structure in Code Visualizer, not decoration around a
separate program. The editor owns a typed tree of sequences and constructs. It
derives connectors and Python from that tree, so moving a line until it touches an
icon never changes control flow.

These diagrams were authored by this implementation from the native First Delivery
project:

- [minimal algorithm](../examples/projects/14-first-delivery/generated/diagrams/first_delivery/main/main.svg)
- [decision with explicit preferred route](../examples/projects/14-first-delivery/generated/diagrams/first_delivery/main/describe_sign.svg)
- [structured loop](../examples/projects/14-first-delivery/generated/diagrams/first_delivery/main/count_three.svg)

## The vocabulary

- A **skewer** is the main vertical route. It gives the eye a stable reading axis.
- A **block** is a contiguous semantic sequence that can move as one unit.
- A **liana** is a complete route through connected icons. It must have a finite,
  unambiguous continuation.
- A **valence** is a legal structural opening: an insertion boundary, owned body, or
  typed exit. Valence is why the editor can explain whether a drop is legal.
- A **route segment** is the rendered horizontal or vertical projection of a stable
  insertion boundary. The segment is not itself canonical program state.

The Header states the callable contract. There is exactly one intrinsic End. Normal
flow proceeds downward; early Return, Raise, Break, and Continue are typed transfers
with explicit legality rules.

## Happy path is not truth

The preferred, or happy, path is the route the reader should scan first. It remains
vertical whenever the construct permits. Truth is a separate property. An If can
therefore place either `True` or `False` downward while still generating the exact
condition semantics.

Why: a stable downward reading rhythm reduces visual search. Conflating downward
with True would change program meaning merely to improve layout. Code Visualizer
labels both the branch truth and which route is preferred.

## Visual AND, OR, Select, and decisions

Several sequential checks on one liana read as visual AND: all must continue along
their chosen route. Alternatives that rejoin represent visual OR: one branch reaches
the common continuation. These are reading laws, not permission to infer a Boolean
expression from arbitrary geometry.

Select owns an ordered tuple of Cases and at most one default. Case adjacency and
order matter because Python `if`/`elif` and `match` choose the first applicable Case.
Reordering a Case is therefore a semantic command and one undoable revision.

## Loops

Every loop has one entry, an owned body, an optional else body, and a finite return
route with no icons placed on it. The loop label has reserved space outside the body;
code text cannot overlap its boundary. Supported forms include range/iterable and
async For, pre-test While, do-first While, WAIT, and TREE depth/breadth traversal.

Why: one visible ownership boundary makes it clear what repeats. A connector drawn
backward through arbitrary icons would hide that ownership and make Break/Continue
targets ambiguous.

## Silhouettes and Addresses

A silhouette is a finite named state workflow. It owns ordered branches, one initial
state, and stable Address transitions between branch IDs. Human-facing state names
produce readable generated identifiers; opaque project IDs stay in source maps.
Find Address Transitions follows those IDs rather than guessing from labels.

Why: long workflows read as a set of named situations instead of a single sprawling
maze. The silhouette bus shows common fate, while each Address makes the next state
explicit and testable.

## Assignment Shelf

Shelf is the assignment icon. Its upper compartment is the Target plus assignment
kind/operator; its lower compartment is the Value; Annotation has its own semantic
field. `=`, annotated assignment, augmented assignment, and unpacking are distinct
typed forms. The divider is protected geometry, so neither field may cross it.

Why: assignment has two roles that should be compared at a glance. A generic Action
would make target/value intent harder to inspect and would weaken validation.

## Metre, rhythm, air, and common fate

- **Metre** is the repeated vertical spacing between operations. It makes sequence
  length and nesting visually predictable.
- **Rhythm** is consistent repetition of equivalent offsets, branch widths, and
  join positions. It lets the eye detect an exception quickly.
- **Air** is minimum clearance around text, icons, routes, arrowheads, labels, and
  buses. It prevents accidental grouping and clipping.
- **Common fate** aligns items that share a continuation or owner. Equivalent branch
  bodies receive equal-width treatment where practical.

These are measured layout invariants. They are not manual nudging advice. Tidy and
fit recompute the same deterministic scene used by the canvas, drag ghost, exported
SVG, contact sheet, and hit testing.

## Constructing safely

Select an insertion target, then click or keyboard-select a Shapes tile. The complete
construct appears immediately with valid contextual placeholder Python. Edit it with
F2/F3 or the semantic Inspector. Existing contiguous blocks can be dragged with a
ghost to highlighted compatible route segments; undo restores the entire transplant
as one revision.

Clicking an eligible vertical or horizontal connector chooses its semantic insertion
boundary; `Ctrl+Alt+Left` and `Ctrl+Alt+Right` cycle the same boundaries without a
mouse, and Escape clears the target. A tile or palette command inserts at that stable
Sequence/index reference, never at a guessed pixel location. `Alt+Up`/`Alt+Down`
reorders the selected block and `Ctrl+Shift+L` recomputes tidy geometry.

An Action or Expression containing one conservative Python statement can be upgraded
with **Convert statement to typed icon**. Assignments, input/output calls, calls, and
flow transfers become their typed semantic atom in one undoable revision; ambiguous
or multi-statement text remains unchanged with an explanatory diagnostic.
