# Quickstart: Hello World

## Start from a genuinely blank project

1. Launch `code-visualizer-gui` and choose **New Project**.
2. Confirm the center shows one empty `main()` algorithm, its Header, visible insertion
   target, and End. Empty is valid and previews as `pass`; no example is hidden.
3. Click the insertion target, then click **Output** in Shapes. It inserts immediately
   without a popup. Keyboard-only: press `Ctrl+Shift+P`, type `insert output`, use
   Up/Down if needed, and press Enter while typing focus remains in search.
4. Click the Output. In the lower-left **Inspector**, set Expression to
   `"Hello, world!"` and choose **Apply**. F2 is the direct primary-field route.
5. Press **F6**. The unified document runs a disposable generated file tree in a child
   process; no save is required. Live Test should show `Hello, world!`.
6. Press **Ctrl+S** and choose an empty project folder. The untouched title adopts the
   folder name only after `project.json` is safely written.
7. Press **Ctrl+G**. Watch Pending, Validating, Generating, then Up to date.
8. In **Python Development > Artifacts**, select `app/main.py`, the launcher, source
   map, report, or SVG. Confirm the tree is non-empty, then choose **Open Generated
   Folder**. Reveal is enabled only for a complete manifest.
9. Press **F5** to run the current generated entry point. The Run Output tab should
   show `Hello, world!`.

Use **Ctrl+Shift+S** for **Save As** when you want an exact editable fork. The new
folder receives the current semantic snapshot and becomes the active writable
project; this also provides the explicit path from a read-only open to a new copy.

The Welcome page's **Start with Hello World** button scaffolds steps 3-4. It is a
deliberate starter, not a hidden example project.

## When generation is blocked

Incomplete Python remains editable and saved. Diagnostics supplies a stable code,
object/field, explanation, and repair. Generation preserves the prior complete set
until the latest revision is valid. There is no vague validity percentage: the panel
says Unsaved, Pending, Validating, Validated, Blocked, Generating, Up to date, Failed,
or Stale output.

## Add another module

Press **Ctrl+Shift+M** for **Python Project**. Add a module or package, assign functions,
and edit its ordered source units. Imports, constants, type aliases, classes, helper
declarations, startup declarations, entrypoint, environment, interpreter, and working
directory have visible controls. A package owns its `__init__.py`; an empty package
path identifies the project's root package.

Use `math.vectors` or `math/vectors.py` for nested output. With package `bci`, both
forms preview and generate `bci/math/vectors.py`. The Project explorer mirrors that
folder tree and nests every diagram under its owning module. Select a module before
choosing **Document > New Algorithm** to create the new callable in that file.

Open **Python Modules** for a small two-function package, then **Bespoke Computational
Instrument** for a runnable nine-diagram system spanning math, model, simulation,
telemetry, UI, and replay-testing packages.

Open **First Delivery**, then choose **My Lens | Learning progression** in Code
Visualizer to see an authored concept across three algorithms. Use **Make Mind Map**
or **Make Canvas** to create an editable, semantically linked composition. Open
**Dijkstra and A\* Pathfinding**, select its Pathfinding conceptual core lens, start a
debug session, and inspect `frontier` as Heap while moving through Runtime Values
history. The **Semantic Text** tab edits selected canonical fields through the same
undoable command authority.
See [Generation and artifacts](GENERATION_AND_ARTIFACTS.md) and
[Live test and debug](LIVE_TEST_AND_DEBUG.md) for the complete development loop.
