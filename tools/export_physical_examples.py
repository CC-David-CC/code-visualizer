"""Export selected physical examples as native authored source, without computing artifacts."""

import argparse
from pathlib import Path

from code_visualizer.application.examples import PHYSICAL_EXAMPLE_CATALOG, example_session
from code_visualizer.application.resource_examples import copy_inputs, source
from code_visualizer.persistence.serialization import normalized_project_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--example",
        action="append",
        required=True,
        choices=[item.id for item in PHYSICAL_EXAMPLE_CATALOG],
    )
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).resolve().parents[1] / "examples/physical"
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    for name in args.example:
        directory = args.output / name.replace("_", "-")
        definition = next(item for item in PHYSICAL_EXAMPLE_CATALOG if item.id == name)
        resources = None
        if definition.resource_directory is not None:
            project, resources = source(definition.resource_directory)
        else:
            session = example_session(name)
            try:
                project = session.authority.snapshot()
            finally:
                session.close()
        data = normalized_project_json(project).encode("utf-8")
        path = directory / "project.json"
        if path.exists() and path.read_bytes() != data and not args.replace:
            raise ValueError("Existing source differs; select --replace explicitly: " + str(path))
        directory.mkdir(parents=True, exist_ok=True)
        if resources is not None:
            copy_inputs(project, resources, directory)
        path.write_bytes(data)
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
