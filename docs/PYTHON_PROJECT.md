# Python Project

`Ctrl+Shift+M` opens a normal outer workspace tab. The Project tree and Python menu provide the same route. It replaces hidden file properties and delimiter conventions.

## Structured composition

Each configured module has a canonical dotted path. The editor also accepts filesystem
input such as `math/vectors.py`; it normalizes that to `math.vectors` and continuously
previews the exact output, for example `generated/bci/math/vectors.py`. Each module has:

- a module/package-initializer kind, dotted path and docstring;
- `import module [as alias]` and `from module import name [as alias]` rows;
- typed constants;
- Python 3.12 type aliases;
- helper functions, classes, and advanced declarations;
- source units with an explicit owner and ordered declaration position.

The project area assigns every canonical function, including functions without a
DRAKON view, to a module and selects the entrypoint callable and literal arguments.
Startup declarations remain in ProgramModel. PythonRuntimeSettings holds run
profiles: interpreter, working directory, command arguments and environment values.

The Project explorer renders these records as a filesystem-shaped tree: package
folders, module `.py` files, and the DRAKON functions owned by each file. Activating a
module opens this workspace at that module. Creating a new Algorithm while a module or
one of its functions is selected assigns the new function to that module. A module may
contain several functions. Their DRAKON diagrams are optional projections of the
canonical functions and their existing declaration positions.

**Add package initializer** creates an explicit package. A blank package path selects
the project's root `__init__.py`; a path such as `tools` selects `tools/__init__.py`.
Its imports, declarations and functions use the same controls and authority as modules.
Module paths must be safe relative Python names. Absolute paths, `..`, an `__init__`
module spelling, case-only collisions and a plain module used as a package prefix are
diagnosed before generation. Choose the package-initializer kind for a package.

Apply commits the setup and function ownership changes as one revisioned semantic transaction. Undo/redo, SDK clients, persistence, diagnostics, preview, live testing, trace, and disk generation therefore observe the same state.

## Artifact lifecycle

After first save, committed edits are coalesced by a revision-aware quiet-period scheduler. It compacts the latest revision, validates that exact snapshot, emits through typed IR, rechecks the current revision, and then atomically promotes `generated/`. Cancelled or stale jobs cannot promote.

A complete artifact set contains the package/module tree, `run_project.py`, source
maps, `project.graph-index.json`, generation report, run configuration, diagram SVGs
and `generation.json`. A blocked or interrupted generation keeps the previous
complete directory. Reveal and preview use that manifest.

Live Run, Trace and Debug execute this same generated file tree in a temporary
directory. The code pane selects a real generated file; breakpoints, events and stack
frames carry its relative path and line. Selecting a frame or semantic object opens
the corresponding file without changing program meaning. Runtime origins continue
to highlight the original program or domain identities at the executed revision.
