"""Package the current source application without machine-specific runtime state."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = (".github", "assets", "docs", "examples", "packaging", "src", "tests", "tools")
FILES = (
    ".gitignore",
    "artifacts/performance/m9-scale-results.json",
    "launch.py",
    "pyproject.toml",
    "README.md",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-science.txt",
    "requirements-cad.txt",
    "requirements-fields.txt",
    "requirements-fields.lock",
    "STATUS.md",
)
EXCLUDED = {
    "__pycache__",
    ".code-visualizer",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
}
START_HERE = """# Code Visualizer — Intentional/domain workbench source delivery

For a short setup and test guide, read docs/RUN_ON_ANOTHER_COMPUTER.md.
This delivery includes function and structural ownership selection with Qt regression
tests against the saved Select/Match, handler, parallel, and silhouette examples.
When supplied as programmodel.zip, programmodel-examples.zip, and
programmodel-evidence.zip, extract all three into the same destination folder.
Each archive contributes files to the same programmodel directory.

Extract the entire archive to a writable folder. Install Python 3.12 or newer,
then run `python launch.py` inside the extracted `programmodel` folder.
The launcher creates a local runtime and installs the pinned runtime dependencies.
Internet access is needed for that first installation; this source archive does
not include an offline wheelhouse.

P3's physical examples additionally need the optional scientific dependencies.
After the first launch, install them into the same application environment:
`.runtime/Scripts/python -m pip install -r requirements-science.txt` on Windows
(or `.runtime/bin/python` on Linux/macOS). If you already use `.venv`, install there.
Choose File > Physical examples for the DC divider or F = k*x. Both use the
Unit-aware linear equations backend. See examples/physical/README.md for authoring,
Freeze & Run, adding a load and retained-run comparison. Verification needs these
scientific dependencies too.

P4 adds the Spring-driven CAD physical example. Install requirements-cad.txt into
the same environment (it includes the scientific pins). See docs/CAD_ARTIFACT_WORKFLOW.md
for selecting a solution resource, publishing BREP from ordinary Python, creating
mesh/measurement consumers and promoting an independent input. Run
`python tools/prove_cad_artifacts.py --output .test-cad-proof` to verify the saved
source, fresh-host consumers, resource origins and portable consumer replay.
Native CAD was qualified on the recorded Windows/CPython environment.

P5 adds the Diffusion: time, fields and checkpoints example. Install
requirements-fields.txt into the same environment for its SciPy backend. See
docs/DIFFUSION_FIELD_WORKFLOW.md for accepted/trial views, exact field probes,
Cancel, retained checkpoint selection and explicit Resume. Run
`python tools/prove_field_history.py --output .test-field-proof` to verify saved
source, independent post-exit consumption and portable replay. Verification scope
and platform limitations are recorded in docs/P5_ACCEPTANCE_MAP.md and STATUS.md.
P6 adds the Electrothermal resistor and heat sink and CAD-backed axial bar
physical examples. Install requirements-fields.txt and requirements-cad.txt in
the same environment. See docs/COUPLED_PHYSICS_WORKFLOW.md for coupled accepted/
trial history, exact probes, explicit restart, CAD publication and axial analysis.
Run `python tools/prove_coupled_physics.py --output .test-coupled-proof` for the
saved-source proof with example factories forbidden and portable consumers.
Qualification and limitations are in docs/P6_ACCEPTANCE_MAP.md and STATUS.md.
P7 adds Adaptive periodic diffusion pulse and Particle and continuum gas shear.
Install requirements-fields.txt. The selected native gas participant requires
the recorded Windows environment and its bundled SPARTA binary/data. See
docs/ADAPTIVE_FIELDS.md and docs/HYBRID_GAS_WORKFLOW.md for retained cell views,
exact downstream probes, cancellation and explicit checkpoint continuation.
P7 qualification status is recorded in STATUS.md; P8 is separate work.

The current application source, all 17 example projects, tests, and design docs
are included. ProgramModel remains the canonical programming domain. Generic
domain schemas and stable intentions use the same authority, with editable
composed visual/textual notations, transformations, and runtime origins.

The Language authoring tab edits custom notations, validation rules and typed
transformation templates as project data. Example 17 includes the complete FSM
language definition. No extension Python edits are needed to change those rules.
Generated and live execution share one InvocationSpec for async functions,
generators, and class/instance methods. One canonical signature binder validates
literal arguments and receiver eligibility before generation or execution.
The native writer uses format revision 11. Canonical modules and classes own ordered
Python declarations and stable function references. PythonRuntimeSettings contains
runtime profiles only; portable computation terminals carry the same canonical program.
The Python Project workspace supports authored root and nested package initializers.
Generated, live Run, Trace, Debug and programming-backend execution all use the same
emitted package tree and normal Python imports. Temporary live files preserve __file__,
inspect and package-resource behavior; source/runtime positions include file identity.
Combined source is a readable preview only.

The universal contracts separate authored definitions and presentation policy from
derived representations, computation sessions, immutable evidence and external
content-addressed resources. Python implements the application and backend adapters;
the Python-program backend executes ProgramModel while other domain backends consume
their own representations. Math and space schemas are ordinary domain extensions.
Bounded typed canonical values
support complex numbers, quantities, small tensors and resource references.
Version 1 Protobuf contracts provide typed interchange and portable commands;
project.json remains the human-readable authoring format.

Public contracts use qualified identifiers with host-granted namespace ownership.
Publication validates typed references throughout definitions against exact bundle
dependencies. Resource logical types carry a qualified ID and separate version;
computation admits them only through registered published providers.
The Add vocabulary action installs foundation.units.si and its ordinary units schema.
Backend API v1 supports declared batch/cooperative-streaming capabilities. Evidence
metadata stays within 2 MiB; large resources use verified bounded chunk transport.
Built-in Python/math backends retain their batch contracts. Submitted computations
run under a host-owned supervisor that can terminate its worker process tree.
Cooperative backend cancellation and host-forced termination are reported separately.
The host preserves revision-pinned attempts across editor replacement. Streaming
backends can publish verified typed resources with immutable provenance receipts;
another computation can consume those exact resources after the producer exits.
See docs/COMPUTATION_PUBLICATIONS.md and docs/TRANSITION_PROGRESS.md for the boundary
and the measured verification scope. Python backend version 2 adds declared named
resource inputs and required outputs through the same emitted-file worker and host
admission path. Version 1 retains its historical batch contract. Later experiment
language phases remain separate work.

Composed notations support editable text, mathematics, geometry and cross-domain
relationships. Readable expression editors preview the canonical typed definition.
Transformation templates can lower through user-defined intermediate schemas.
The Git dock integrates real staging, diffs, commits, branches and explicit remote
actions with a validated project reload boundary.

Freeze & Run captures a declared input closure into a retained Git commit before
execution, preserving the original HEAD/index and unrelated work. The first
accepted semantic edit opens one real experiment branch/worktree; presentation
and unsubmitted text do not fork. Retained runs/resources survive editor and
inactive-worktree removal. See docs/GIT_EXPERIMENTS.md and docs/P2_ACCEPTANCE_MAP.md
for recovery, verification and platform limits. P3 adds shared unit-aware equations
and the two physical examples described above. P8 remains separate work.

Use Open Project to select an example's folder containing `project.json`. Start with
`examples/projects/17-traffic-light` for the complete domain-workbench loop:
rename a state through the transition table, inspect the same objects in the
graph and form, generate Python, then trace/debug back to the original states,
transitions, and actions.

For a proof authored from blank without example factories or a handwritten domain
extension, open `examples/proofs/authority-authored-toggle`. It includes canonical
data, all 41 authority commands, generated Python and a runtime highlight receipt.
`tools/prove_domain_authoring.py` reproduces it in a new output folder; see
`docs/DOMAIN_AUTHORING_PROOF.md` for the exact boundary and verification.

`examples/proofs/foundation-math` contains a structured indexed matrix equation,
its binary computation plan, immutable result resources and evidence. The math
backend evaluates it without generating Python, and a worker consuming plan.pb
reproduces the same evidence and original-object highlights. Run
`python tools/prove_foundation_math.py --output NEW_FOLDER` to reproduce the proof.

Read README.md and these design documents:

- docs/INTENTIONAL_WORKBENCH.md — architecture, ownership, and implementation scope;
- docs/DOMAIN_SCHEMA.md — schemas, canonical instances, commands, and validation;
- docs/NOTATION_LANGUAGE.md — editable notations over shared identities;
- docs/TRANSFORMATION_PIPELINE.md — derived builds and runtime origins;
- docs/PROGRAM_DOMAIN_INTEGRATION.md — retained ProgramModel invariants.
- docs/DOMAIN_LANGUAGE.md — structured language editor and composition;
- docs/WORKBENCH_AUTHORING.md — supported query and program-template grammar.
- docs/WORKBENCH_COMPOSITION.md — notation, intermediate languages and ownership;
- docs/GIT_WORKFLOW.md — real Git operations and project reload boundaries.
- docs/DOMAIN_AUTHORING_PROOF.md — independent authoring and runtime proof.
- docs/UNIVERSAL_WORKBENCH.md — canonical, derived, computation and evidence planes;
- docs/CANONICAL_VALUES.md — closed value algebra and inline limits;
- docs/RESOURCES_AND_EVIDENCE.md — immutable resources, provenance and promotion;
- docs/COMPUTATION_BACKENDS.md — registered backends and portable worker plans;
- docs/FOUNDATIONS.md — ordinary math/space domains and the direct Python-backend proof;
- docs/FOUNDATION_UNITS.md — shared unit definitions and explicit conversion contexts;
- docs/CONTRACT_IDENTITIES.md — public naming, namespace ownership and publication;
- docs/PROTOBUF_BOUNDARIES.md — versioned language-neutral interchange contracts.

STATUS.md records the verification for this delivery. This source archive is
distinct from the historical `artifacts/release/source-folder` distribution;
its offline Windows wheelhouse is not included here.

To run development checks in PowerShell after installing requirements-dev.txt
in a virtual environment:

```powershell
$env:PYTHONPATH = 'src'
$env:MYPYPATH = 'src'
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pytest
python -m mypy src
python tools/generate_protocol.py --check
ruff check src tests tools packaging
ruff format --check src tests tools packaging
```

`source-manifest.json` records the SHA-256 and size of every delivered file.
Rebuild this source archive with `python tools/build_programmodel_archive.py`.
Verify it using an interpreter with the runtime requirements already installed:
`python tools/verify_programmodel_archive.py --archive PATH_TO_PROGRAMMODEL_ZIP`.
Verification extracts a new local folder and checks manifest hashes, launch,
regeneration, and execution of all examples without installing dependencies.
It also reproduces the two historical independent proofs, the P3 physical proof
and the saved P4 CAD proof from extracted source, checking canonical data, binary
plans, resources, evidence and runtime origins, followed by the P5 retained field
and independent probe proof, then the P6 coupled/axial saved-source proof.
Install the optional CAD, scientific and fields
dependencies in the verification interpreter for these physical proofs.
"""


def source_files() -> list[Path]:
    candidates = [ROOT / name for name in FILES]
    candidates.extend(
        path for name in DIRECTORIES for path in (ROOT / name).rglob("*") if path.is_file()
    )
    return sorted(
        path
        for path in candidates
        if not EXCLUDED.intersection(path.relative_to(ROOT).parts)
        and not any(part.startswith(".test-") for part in path.relative_to(ROOT).parts)
        and not any(part.endswith(".egg-info") for part in path.relative_to(ROOT).parts)
        and path.suffix not in {".pyc", ".pyo"}
        and (path.suffix != ".lock" or path.name == "requirements-fields.lock")
    )


def _payload() -> dict[str, bytes]:
    payload = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in source_files()}
    payload["START_HERE.md"] = START_HERE.encode("utf-8")
    manifest = {
        "schema_version": 1,
        "files": [
            {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
            for name, data in sorted(payload.items())
        ],
    }
    payload["source-manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return payload


def _write_archive(output: Path, payload: dict[str, bytes]) -> tuple[int, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = ZipInfo(f"programmodel/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    temporary.replace(output)
    return len(payload), output.stat().st_size


def build_archive(output: Path) -> tuple[int, int]:
    return _write_archive(output, _payload())


def build_delivery(output: Path) -> tuple[tuple[Path, int, int], ...]:
    """Deliver ordinary overlay zips, each strictly below 50 decimal MB."""
    groups: dict[str, dict[str, bytes]] = {"": {}, "-examples": {}, "-evidence": {}}
    for name, data in _payload().items():
        group = (
            "-examples"
            if name.startswith("examples/physical/")
            else "-evidence"
            if name.startswith("docs/receipts/")
            else ""
        )
        groups[group][name] = data
    results = []
    for suffix, payload in groups.items():
        path = output.with_name(f"{output.stem}{suffix}{output.suffix}")
        count, size = _write_archive(path, payload)
        if size >= 50_000_000:
            raise ValueError(f"{path.name} exceeds the delivery limit: {size} bytes")
        results.append((path, count, size))
    return tuple(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT.parent / "programmodel.zip")
    parser.add_argument("--split", action="store_true", help="Write three zips below 50 MB each")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.split:
        for path, count, size in build_delivery(output):
            print(f"archive={path}\nfiles={count}\nbytes={size}")
    else:
        count, size = build_archive(output)
        print(f"archive={output}\nfiles={count}\nbytes={size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
