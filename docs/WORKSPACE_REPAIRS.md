# Workspace repairs

September 30, 2026. The active editor working tree has a first implementation of the
layout, docking and execution-navigation repairs in the root UI_REPAIR_PLAN.md.
These changes are **not yet validated by application tests or an interactive GUI
review**. The existing selection ownership and source mapping are preserved.

## Changed behavior

- The main and detached document windows are bounded to the available monitor work
  area. The project explorer no longer demands a 350-pixel minimum width.
- Fresh/reset layouts prioritize the diagram. Automation, development output and
  secondary right-side panels start hidden; View exposes them. Inspector shares
  the Project dock tab area, leaving more height for the compact scrolling Shapes list.
- Inspector property labels wrap, rows grow to their contents and full values have
  tooltips. Signature details scroll instead of forcing the document wider.
- The diagram/code splitter starts around 60/40, has visible handles and retains
  user proportions. Wrap Code is a saved view preference.
- Empty function output is collapsed. Output can be opened or hidden explicitly;
  new output is indicated when hidden, and the output pane's chosen height is retained.
- Auto-fit is explicit. It refits after a visible viewport settles following resize,
  opening, docking or splitter movement. Manual zoom/pan turns it off; Fit restores it.
- The function toolbar travels with its document. Detached windows share its actions,
  enabled state and shortcuts rather than adding a duplicate execution toolbar.
- A logical tab order retains detached slots and respects subsequent visible tab
  reordering. Redocking uses that order instead of appending the tab.
- Run Function/Trace Function/Debug Function identify their function target through
  tooltips. Run Project describes the configured entry point. Python → Project Entry
  Point opens the existing configuration. Stop Function and Stop Project have separate
  targets; Shift+F6 stops the active docked function, Shift+F5 stops the project run.
- Closing the last tab reveals the example picker plus documents that can be reopened.
  File → Close Project / Return to Examples uses the existing save/discard/cancel
  lifecycle. Closing views does not change the independent computation-host policy.

Use **View → Reset Workspace Layout** to adopt the new default layout. Explicit saved
dock arrangements are otherwise preserved. A reset does not erase unrelated settings.

## Preserved and pending

The generalized Header/Select/Case/handler/branch resolver, whole-function selection,
leaf selection, provenance spans and structural editing guards are retained. The
additional nearest-code fallback and Start/End navigation policy in Stage 4 remains
planned; this pass does not claim those extensions are implemented.

The fixed scientific worktree, calibration, protocols, study results and dated ZIP
deliveries were not edited. The September 22 ZIP series does not contain these new
working-tree UI changes.

No tests or application launch were performed for this repair pass, following the
user's instruction. Static validation and exact file changes are recorded in
workspace-records/2026-09-30/UI_REPAIR_IMPLEMENTATION.json at the repository root.
Original edited files were retained under the neighboring ui-repair-before directory.

Before calling this a verified UI release, review the actual layout on the intended
screens and run the relevant existing regressions when testing is requested.
