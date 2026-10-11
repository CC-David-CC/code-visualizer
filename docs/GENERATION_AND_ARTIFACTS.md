# Generation and artifacts

## Save establishes project ownership

A new project is in memory until the first Save. Choose an empty project directory;
`project.json` becomes the canonical current-format snapshot and `.code-visualizer/`
contains the lease, journal, and recovery snapshots. An untouched "Untitled Project"
adopts the directory name only after that write succeeds.

Only one writable authority may own a directory. A second desktop/service can connect
to the endpoint recorded by the owner or open explicitly read-only. It never becomes
a second independent writer.

## Revision-aware background pipeline

Saved edits move through these visible states:

`Pending -> Validating -> Generating -> Up to date`

`Blocked`, `Failed`, `Stale output`, `Validated`, and `Unsaved` explain the other
outcomes. Rapid edits are coalesced. Validation and generation run outside the Qt UI
thread. Every job retains its starting revision; a newer edit or replacement session
makes the old job ineligible for promotion.

Autosave first compacts the exact durable revision. Validation never executes project
code. If errors exist, generation is Blocked and the prior complete output remains.

## Atomic artifact contract

Generation writes and fsyncs a private sibling directory, verifies the revision is
still current, then swaps the whole directory into `generated/`. A complete set has:

- package directories and authored or generated `__init__.py` files;
- configured module files;
- `run_project.py`, the configured package entry launcher;
- `project.source-map.json`, v3 bidirectional spans with primary `semantic_id` and
  optional `presentation_id`;
- `project.graph-index.json`, diagram IDs/titles/functions mapped to code and SVG paths;
- `generation-report.json`, diagnostics and entry-point metadata;
- `run-config.json`, the selected interpreter/profile projection;
- one SVG per DRAKON, mind-map, and free-form document; DRAKON SVGs mirror the Python
  package/module hierarchy;
- `generation.json`, a complete manifest with revision and SHA-256 hashes.

The combined code preview is read-only presentation text, not a standalone Python
file or an execution artifact. Each emitted module compiles in its own namespace.
An authored PACKAGE module contributes its initializer exactly once; missing parent
initializers are disposable generated boilerplate.

"Open Generated Folder" is enabled by a non-empty complete manifest, not by directory
existence. A blocked first generation therefore leads to Diagnostics instead of an
empty folder.

For a package `bci` and module `simulation.scheduler`, generation creates
`bci/simulation/scheduler.py`, the required `bci/` and `bci/simulation/`
`__init__.py` files, and graph exports beneath
`diagrams/bci/simulation/scheduler/`. The in-application Artifact tree presents the
same nested layout instead of flattening paths into one list.

## External edits

Generated Python is inspectable but not canonical. Before F5 and automatic promotion,
Code Visualizer compares every manifest hash and reports missing, modified, or
unexpected files. External changes pause automatic generation and appear in Artifact
Diff. Explicit Generate Project is the deliberate overwrite boundary.

## Commands

Desktop:

- `Ctrl+Shift+V`: validate in the background.
- `Ctrl+G`: explicitly generate the latest saved valid revision.
- Python Development > Artifacts: inspect files and hashes.
- Open Generated Folder: reveal only a complete set.
- `F5`: verify and run the generated entry point.

CLI:

```powershell
code-visualizer validate .\my-project
code-visualizer generate .\my-project
code-visualizer run .\my-project
```

The CLI acquires the same project lease and uses the same validator, IR, emitter,
manifest, source map, and child-process runner as the desktop.
`validate` prints `{ "buildability": ..., "diagnostics": [...] }`. Incomplete
expression text remains saveable, but all generation, run, trace, and debug entry
points stop at the buildability gate and preserve the last complete artifact set.

## One invocation contract

Lowering creates a neutral `InvocationSpec` from the selected canonical function,
including its stable identity, callable kind, owning class/method kind, and configured
arguments. `EntryPointIR`, generated results, and live execution carry this value.
Imported module aliases are rendering bindings rather than a second callable model.
The standalone launcher, in-memory Run, Trace, and debugger all use the same renderer
to call, await, or consume the selected function. Normal return values may be displayed
by live tools; generated launchers discard them. Generator values are drained in all
paths, preserving execution and exceptions without inventing an output convention.
Invocation helper bindings avoid callable, owning-class, and argument identifiers;
capturing a generator's terminal result happens only after its body has completed.

The structured invocation transport is ephemeral execution configuration. It is not
another persisted owner of program meaning; project configuration and `ProgramModel`
remain the source from which an invocation is derived.
