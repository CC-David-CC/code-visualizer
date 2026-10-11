"""Regenerate checked-in Python contracts with the pinned development compiler.

Run ``python tools/generate_protocol.py --check`` to verify generated files without edits.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import subprocess
import sys
import tempfile
from pathlib import Path

GRPC_TOOLS_VERSION = "1.78.0"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    if importlib.metadata.version("grpcio-tools") != GRPC_TOOLS_VERSION:
        parser.error(f"Install grpcio-tools=={GRPC_TOOLS_VERSION} to regenerate contracts")
    source = Path(__file__).resolve().parents[1] / "src"
    schemas = sorted((source / "code_visualizer" / "protocol" / "v1").glob("*.proto"))
    with tempfile.TemporaryDirectory(prefix="code-visualizer-protobuf-") as temporary:
        target = Path(temporary) if options.check else source
        subprocess.run(
            [
                sys.executable,
                "-m",
                "grpc_tools.protoc",
                f"-I{source}",
                f"--python_out={target}",
                f"--pyi_out={target}",
                *map(str, schemas),
            ],
            check=True,
        )
        if options.check:
            for schema in schemas:
                for extension in (".py", ".pyi"):
                    relative = schema.relative_to(source).with_name(
                        schema.stem + "_pb2" + extension
                    )
                    expected = source / relative
                    if not expected.exists() or expected.read_text(encoding="utf-8") != (
                        target / relative
                    ).read_text(encoding="utf-8"):
                        print(f"Generated contract is stale: {relative}", file=sys.stderr)
                        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
