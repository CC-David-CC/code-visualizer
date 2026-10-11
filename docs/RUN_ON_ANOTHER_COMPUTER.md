# Run this source package on another computer

This delivery consists of three ordinary zip archives, each below 50,000,000 bytes:

- `programmodel.zip`: the complete application, all tests, bundled resources,
  core examples, build tools, dependency lists, and documentation.
- `programmodel-examples.zip`: the saved physical example projects and their resources.
- `programmodel-evidence.zip`: historical verification receipts and supporting evidence.

Extract **all three archives into the same writable destination folder**. They each
contain paths starting with `programmodel/`; the extracted files merge into that one
folder. There is no special split-archive utility or concatenation step. Keep the
folder's contents together. The main zip can launch independently; extract the full
set before running all included tests or opening the supplemental examples.

## Start the application

Install 64-bit Python 3.12 or newer. This delivery was checked on Windows with
CPython 3.13.15. Internet access is required for the first dependency installation;
this archive does not contain an offline wheelhouse or a bundled Python interpreter.
Install Git and make `git` available on PATH for project Git features and Git tests.

In PowerShell, change into the extracted `programmodel` folder and run:

```powershell
py -3.13 launch.py
```

If your Python is available as `python`, use `python launch.py` instead. The launcher
creates `.runtime`, installs the pinned core dependencies from `requirements.txt`,
and opens the application. Use the same command for subsequent launches. There is
no need to activate the environment or change PowerShell's execution policy.

On Linux/macOS, from the extracted folder run `python3 launch.py` with Python 3.12+
and virtual-environment support installed. A graphical desktop and the platform's
Qt runtime libraries are required. The bundled native gas participant is Windows
specific; see [Hybrid gas](HYBRID_GAS_WORKFLOW.md) for its platform requirements.

Use **Open Project** to select the extracted `examples/projects/03-values` folder,
which contains `project.json`. In this Values and Assignment example, the function header
selects the complete generated function; selecting its `def main():` line selects
the visual header. Clicking the assignment selects only its corresponding code.
Selecting a match, case, handler, or branch highlights its complete owned source;
selecting a child statement narrows the highlight to that statement. See
[Selection ownership](SELECTION_OWNERSHIP.md) for the behavior and regression tests.
See [Quickstart](QUICKSTART.md) for creating a project from scratch.

## Optional physical examples and debugging

Install optional dependencies into the same environment used by the launcher.
For example, on Windows:

```powershell
.\.runtime\Scripts\python.exe -m pip install -r requirements-science.txt
.\.runtime\Scripts\python.exe -m pip install -r requirements-cad.txt
.\.runtime\Scripts\python.exe -m pip install -r requirements-fields.txt
```

The CAD list includes the scientific dependencies. The full development list below
includes these optional packages and the debugger. On Linux/macOS, substitute
`.runtime/bin/python` for `.runtime\Scripts\python.exe`.

## Run the included tests

From the extracted `programmodel` folder, after the first launch:

```powershell
.\.runtime\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.runtime\Scripts\python.exe -m pip install --no-deps -e .
$env:QT_QPA_PLATFORM = 'offscreen'
.\.runtime\Scripts\python.exe -m pytest
```

The full suite includes scientific, CAD, native-platform, execution, and Git tests.
Platform-specific checks need the corresponding dependencies and supported host.
For the focused function-header regression tests:

```powershell
.\.runtime\Scripts\python.exe -m pytest tests/test_function_header_selection_qt.py -q
```

On Linux/macOS, install the same requirements with `.runtime/bin/python`, then run
`QT_QPA_PLATFORM=offscreen .runtime/bin/python -m pytest`.

For a checkout inside another large Git repository, put pytest's temporary projects
outside that repository using `--basetemp PATH_TO_A_NEW_TEMP_DIRECTORY`. Pytest clears
the supplied directory, so choose a dedicated test directory with no personal files.

## Contents and verification

`source-manifest.json` in the main zip records every delivered file's size and SHA-256
across all three archives. Each companion `.zip.sha256` checks its respective zip.
`programmodel.verification.json`
records this package's extraction, launch, and focused test checks. Historical
qualification receipts inside `docs/receipts/` describe their recorded revisions.

The dedicated selection suite has 30 passing cases covering functions, nested
structural owners, intrinsic headers, leaf statements, and safe editing. The nine
original function-header tests are unchanged. The delivery report records the
broader regression and extracted-package checks; it does not claim a new full-suite
or full physical-simulation qualification.

For installation and architecture details, read [README](../README.md) and
[START_HERE](../START_HERE.md). Build the source archive again with
`python tools/build_programmodel_archive.py --split --output programmodel.zip`.
The archive verifier accepts the complete set with `--archive programmodel.zip
--supplement programmodel-examples.zip --supplement programmodel-evidence.zip`.
Its full qualification also runs the longer physical and gas proofs.
