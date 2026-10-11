# Accessibility

Code Visualizer targets WCAG 2.2 AA concepts applicable to a Qt desktop IDE.

## Keyboard routes

The command palette (`Ctrl+Shift+P`) retains typing focus while Up/Down select enabled
results and Enter executes exactly once. Search includes names, aliases, categories,
shortcuts, and descriptions. Disabled rows expose a reason. Escape cancels.

Core shortcuts include Ctrl+N/O/S, Ctrl+Shift+S Save As, Ctrl+Z/Ctrl+Shift+Z,
Ctrl+F/H, F2/F3 field editing, Ctrl+Shift+V validation, Ctrl+G generation,
F5/F6/F7 execution, Shift+F6 stop, Ctrl+Shift+M Python Project, Ctrl+Shift+D
detach/dock, Alt+Left/Right navigation, Alt+Up/Down structural reorder, and +/-/0
zoom/fit. Ctrl+Alt+Left/Right cycles semantic insertion targets and Escape clears the
target. Ctrl+Shift+L tidies/refits. Shapes search and insertion, diagnostics, layouts,
artifact reveal, and docking also have keyboard routes. Text controls retain
conventional editing shortcuts.

Semantic Tab traversal follows preferred executable flow before secondary branches
and Cases. Focus is distinct from semantic selection. Shift-click toggles a semantic
selection; a left-to-right marquee contains objects while right-to-left intersects
them, matching conventional vector-editor expectations without relying on color.

## Accessible information

Icons expose kind, displayed text, validity, ports, truth/preference, and traversal
position through Qt accessibility properties. Palette active-row changes send focus
events. Diagnostics use severity text, stable code, explanation, location, and repair;
color is supplemental. Drag targets combine highlight, cursor/ghost, and explanatory
text. Generated code, Python Project, consoles, and artifact previews are standard
accessible text/table controls.

## Appearance

Classic, Light, Dark, and High Contrast themes use measured AA contrast pairs.
Reduced Motion suppresses nonessential animation. Vector geometry scales with Qt DPI;
hit targets and icon internal clearances remain independent of raster resolution.
Bundled licensed DejaVu fonts make fallback and off-screen rendering predictable.

## Verification workflow

Automated tests inspect accessible names/descriptions, palette active-item events,
focus order, theme contrast, reduced-motion state, semantic Tab order, and real
keyboard interaction. The Windows release smoke uses the packaged executable.

Real Windows screen-reader checklist:

1. Start Narrator, then start Code Visualizer.
2. Create a project and traverse Project, Shapes, Inspector, document, and Python
   Development controls with Tab/Shift+Tab.
3. Open the command palette, type `insert if`, move with arrows, and confirm the
   active command, category, shortcut, and disabled reason are announced.
4. Traverse a decision canvas and confirm semantic order, truth/preference, ports,
   and position are announced.
5. Introduce invalid Python and confirm the diagnostic can be located and activated
   without color.
6. Read generated source and run output, detach/dock the document, then stop Narrator.

`STATUS.md` records the dated result and any platform constraint for the executed
screen-reader smoke; this checklist is also the repeatable pre-release procedure.
