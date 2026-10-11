# DRAKON icon and macroicon inventory

This is an executable inventory, not a gallery. `icon_manifest.json` is the
machine-readable counterpart. The canvas, Shapes tiles, drag ghosts, SVG
export, and contact sheet all consume the same versioned vector recipes.

## Atomic forms

| # | Recipe | Semantic contribution and creation route |
|---:|---|---|
| 1 | Function Header | Intrinsic callable entry; edited in Function Signature. |
| 2 | End | Intrinsic single finite terminal; never inserted as a second End. |
| 3 | Action | Non-topology-owning Python statements; Shapes/palette `Insert Action`. |
| 4 | If / Question | Typed condition with explicit truth and independent preferred route. |
| 5 | Select / Choice | Owns ordered condition or `match` Cases and one final default. |
| 6 | Case | Derived from each stable `Case`; its body remains an editable Sequence. |
| 7 | Branch Header | Derived from named Parallel processes and silhouette states. |
| 8 | Address | Derived from each silhouette state's stable target or finite exit. |
| 9 | Call / Insertion | Expression call or stable diagram-linked call with arguments/result. |
| 10 | Assignment Shelf | One plain, chained, unpacking, annotated, or augmented assignment. |
| 11 | Signature panel | Derived when typed parameters/callable metadata are present. |
| 12 | For Start | Typed While, do-first, For, async For, WAIT, DFS, or BFS boundary. |
| 13 | For End | Derived at the end of a loop-owned body. |
| 14 | Output | Typed `print`, including `file=` and `end=` expression fields. |
| 15 | Input | Typed target assigned from `input` and an optional converter. |
| 16 | Delay / Pause | Clamped sync or async sleep. |
| 17 | Scheduling Period | Remaining-cadence sleep for a named monotonic timer. |
| 18 | Start Clock / Timer | Records `time.perf_counter()` under a typed timer identity. |
| 19 | Synchronizer | Chooses explicit on-time/timeout bodies from elapsed time. |
| 20 | Realtime Process | Ordinary or awaited process-call operation. |
| 21 | Rich Note | Non-executable explanatory annotation with its own safe region. |
| 22 | Right Note | Right-fold annotation; does not alter control flow. |
| 23 | Left Note | Left-fold annotation; does not alter control flow. |
| 24 | Loop Return | Visual transfer used by Break/Continue and loop-return semantics. |
| 25 | Silhouette Transition | Explicit Return/Raise/Yield family and transition projection. |
| 26 | Connector marker | Visible empty-Sequence insertion affordance; emits no fake call. |
| 27 | Concurrent boundary | Owns named sync/async Parallel processes and their join policy. |

Every form above is asserted to occur in a real semantic `DiagramScene` by
`test_every_atomic_recipe_is_bound_to_a_real_semantic_scene_projection`.
Header, End, Case, Address, signature, For End, and connector markers are
derived projections because duplicating them as loose atoms would make the
program model invalid.

## Macroicons

Each macroicon is one command or transaction, one revision, and one undo step.
Defaults parse, validate, and generate before the user edits them.

| # | Macroicon | Typed structure created |
|---:|---|---|
| 1 | Header with Parameters | Adds a typed `ParameterSpec`. |
| 2 | Binary If | Complete If with both owned bodies. |
| 3 | Select / Switch | Ordered Cases plus final default. |
| 4 | Conditional Loop | While boundary, body, else, and continuation. |
| 5 | Select Loop | Select nested in a loop body. |
| 6 | For Loop | Iterable For with body and loop else. |
| 7 | Wait Loop | Retry body plus mandatory delay return. |
| 8 | Action by Timer | Start Timer, Action, Synchronizer. |
| 9 | Shelf by Timer | Start Timer, Shelf, Synchronizer. |
| 10 | Fork by Timer | Start Timer, If, Synchronizer. |
| 11 | Select by Timer | Start Timer, Select, Synchronizer. |
| 12 | Conditional Loop by Timer | Start Timer, While, Synchronizer. |
| 13 | Select Loop by Timer | Start Timer, loop containing Select, Synchronizer. |
| 14 | For Loop by Timer | Start Timer, For, Synchronizer. |
| 15 | Wait Loop by Timer | Start Timer, WAIT, Synchronizer. |
| 16 | Call by Timer | Start Timer, Call, Synchronizer. |
| 17 | Output by Timer | Start Timer, Output, Synchronizer. |
| 18 | Input by Timer | Start Timer, Input, Synchronizer. |
| 19 | Start Timer by Timer | Start Timer and explicit deadline fork. |
| 20 | Parallel Process by Timer | Start Timer, Parallel, Synchronizer. |
| 21 | TREE Loop | Depth-first TREE loop; Inspector can select BFS. |

## Text and geometry contract

Each recipe owns its outline, dividers, ports, hit bounds, and named text-safe
regions. Shelf compartments size independently. Output/Input arrow
compartments, Period halves, note folds, loop notches, and parallel bars are
excluded from text regions. Shared body width and one solved skewer anchor
prevent one-pixel connector doglegs. Fit and export include final strokes,
routes, labels, and arrow compartments.

Generated fixtures:

- `assets/goldens/initial-icon-contact-sheet.svg`
- `assets/goldens/initial-icon-contact-sheet.png`
- `assets/goldens/initial-icon-contact-sheet@2x.png`
- `assets/goldens/initial-if-layout.svg`

The artwork is newly authored geometry and contains no raster element or
historical DRAKON asset.
