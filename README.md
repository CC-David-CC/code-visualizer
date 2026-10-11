# Code Visualizer

A Python desktop programming workbench with structural DRAKON editing, mind maps,
free-form diagrams, generated Python, and execution visualization. ProgramModel
is the canonical model; diagrams and code are views of that model.

The editor includes schema-driven domain notation, language authoring, source maps,
linked execution and debugging, project persistence, and 17 educational examples.
Optional math, field and CAD backends support the physical examples.

## Run

Install Python 3.12 or newer, then from this folder run:

```powershell
python launch.py
```

The launcher creates an ignored `.runtime/` environment and installs the runtime
dependencies. The first setup needs internet access. For launcher options:

```powershell
python launch.py --launcher-help
```

See [Quickstart](docs/QUICKSTART.md), [Running on another computer](docs/RUN_ON_ANOTHER_COMPUTER.md)
and [current status](STATUS.md). Scientific and CAD examples need their optional
dependencies; see the corresponding `requirements-*.txt` files and workflow docs.
The bundled SPARTA native participant is specific to its recorded Windows environment.

## Develop

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,debug]"
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python -m pytest
```

Use `.[dev,debug,science,cad,fields]` for the optional scientific/CAD test dependencies.

## Directory map

| Folder | Contents |
|---|---|
| src/code_visualizer/ | Application source and required runtime resources |
| tests/ | Automated tests and fixtures |
| examples/ | Saved educational and physical projects, including required resources |
| assets/ | Visual regression fixtures |
| docs/ | Architecture, APIs, workflows and implementation decisions |
| tools/, packaging/ | Development and packaging tools |
| inspiration/ | Supplied language PDFs and appearance references |
| artifacts/performance/ | One retained benchmark fixture used by the packaging tools |

This standalone baseline comes from the active educational Code Visualizer tree,
not the divergent archived P7 research copy. Environments, caches, builds, old
delivery receipts and the original Tcl DRAKON editor are outside this repository.
See [provenance](docs/PROVENANCE.md) and [third-party resources](THIRD_PARTY.md).
