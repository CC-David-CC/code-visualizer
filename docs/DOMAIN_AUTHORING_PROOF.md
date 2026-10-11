# From a blank project to runtime domain highlights

`tools/prove_domain_authoring.py` constructs a complete proof through the same typed
authority commands used by the workbench. It starts with `Project(..., documents=())`:
no schema, instances, authored language, or program functions exist.

The script supplies only the generic intentional-domain and programming providers.
They contribute no domain schema or transformation. It does not call a state-machine
factory, an example-project factory, or a handwritten domain extension. The focused
test runs it in a separate interpreter that rejects imports of those modules and Qt.

Run from the source folder with the installed development environment:

```powershell
$env:PYTHONPATH = 'src'
.venv\Scripts\python.exe tools/prove_domain_authoring.py --output artifacts/proofs/my-toggle
```

Choose a new or empty output folder. The script refuses to replace an existing proof.
On other systems use the environment's Python executable with `PYTHONPATH=src`.

The command sequence creates three concepts—Machine, State, Transition—and defines
their properties, containment roles, and references individually. It then creates an
empty model and adds five canonical objects: one machine, two states, two transitions.
Both transitions respond to a toggle; the machine starts at Idle and takes three steps.

Authored graph, transition-table, and hierarchy/form definitions present these same
objects. Editing the table renames Active to Engaged through a reference to its stable
State ID; graph property editing renames Idle to Rest. A form edit changes the step
count, and undo/redo restores the intended three-step run. Every edit is a typed
authority command, recorded in `commands.json` with its expected revision.

The script adds an authored validator and an inert typed transformation. The generic
interpreter lowers the machine to a disposable ProgramModel using assignments,
conditionals, and a loop. The existing Python generator emits and executes:

```text
Engaged
Rest
Engaged
```

The trace uses the ordinary workbench runtime service. A runtime listener observes
the generated operation's origin map and checks that the same original State and
Transition are active in the graph, transition table, and hierarchy/form. The record
includes the generated semantic ID, original IDs, event sequence, and pinned revision.
No view contents are copied back into the model.

The shipped format 9 proof has canonical project SHA-256
`04826eb06b0ea544c22108bbac3bc550560c1934ceaeb59da60a3c0148e4ddc4`.
It retains 41 authority commands, five canonical objects, and the same runtime highlights.

The output contains:

- `project.json`: the canonical schema, five objects, and authored definitions;
- `commands.json`: the reproducible authority command sequence, including undo/redo;
- `generated/`: the existing Python build, source maps, and origin map;
- `proof.json`: the assertions' results, output, canonical hash, and runtime highlights.

`project.json` contains zero authored program functions. Generated functions belong
only to the build. Repeated lowering and generation are equal, native save/load retains
the canonical identities, and running/tracing leaves the canonical JSON unchanged.

Open the output folder in Code Visualizer, select **Domain Workbench → Two-state
toggle**, and inspect **Toggle graph**, **Transition table**, or **Hierarchy and form**.
Its authored language is editable through **Language authoring**. No JSON editing is
needed to continue from the saved proof.

The dedicated automated proof is:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_domain_authoring_proof.py -q
```

Besides executing the isolated proof, the test replays the recorded commands against
another blank authority and compares the resulting native project byte for byte.
The source-archive verifier also re-creates the shipped proof from extracted source
in a separate interpreter with example imports forbidden. It compares the project,
command sequence, runtime receipt, and every generated artifact against the shipped
files while retaining the normal 17-example checks.
This is an API-level authoring proof; it does not claim to automate every mouse gesture
or replace the separate desktop interaction tests.
