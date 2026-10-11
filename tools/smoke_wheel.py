"""Inspect and isolated-import the built wheel without trusting the source tree."""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dist", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    wheels = sorted(args.dist.resolve().glob("code_visualizer-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected exactly one Code Visualizer wheel, found {len(wheels)}")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        required = {
            "code_visualizer/resources/icon_manifest.json",
            "code_visualizer/resources/fonts/DejaVuSans.ttf",
            "code_visualizer/resources/fonts/DejaVuSansMono.ttf",
            "code_visualizer/resources/fonts/LICENSE-DejaVu.txt",
            "code_visualizer/resources/sparta/libsparta_p7serial.dll",
            "code_visualizer/resources/sparta/manifest.json",
            "code_visualizer/resources/sparta/LICENSE",
            "code_visualizer/resources/sparta/sparta-corresponding-source.zip",
            "code_visualizer/resources/sparta/ar.species",
            "code_visualizer/resources/sparta/ar.vss",
            "code_visualizer/resources/hybrid_gas/project.json",
        }
        for family in (
            "identity",
            "value",
            "domain",
            "resource",
            "computation",
            "evidence",
            "command",
            "worker",
        ):
            required.update(
                {
                    f"code_visualizer/protocol/v1/{family}.proto",
                    f"code_visualizer/protocol/v1/{family}_pb2.py",
                    f"code_visualizer/protocol/v1/{family}_pb2.pyi",
                }
            )
        missing = required - names
        if missing:
            raise SystemExit(f"Wheel is missing package data: {sorted(missing)}")
        if any(name.casefold().endswith(".drn") for name in names):
            raise SystemExit("Legacy .drn content must not be packaged")
        entry_points_name = next(
            (name for name in names if name.endswith(".dist-info/entry_points.txt")),
            None,
        )
        if entry_points_name is None:
            raise SystemExit("Wheel has no console entry-point metadata")
        entry_points = archive.read(entry_points_name).decode("utf-8")
        for expected in ("code-visualizer =", "code-visualizer-gui ="):
            if expected not in entry_points:
                raise SystemExit(f"Wheel entry points do not contain {expected!r}")
    source = (
        "import sys; "
        f"sys.path.insert(0, {str(wheel)!r}); "
        "import code_visualizer; "
        "from code_visualizer.protocol.v1 import value_pb2; "
        "value = value_pb2.CanonicalValue(schema_version=1, text='wheel proof'); "
        "assert value_pb2.CanonicalValue.FromString(value.SerializeToString()) == value; "
        "assert '.whl' in value_pb2.__file__; "
        "print(code_visualizer.__version__)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", source],
        check=True,
        capture_output=True,
        text=True,
    )
    print(f"wheel={wheel.name} version={result.stdout.strip()} resources=ok entrypoints=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
