"""Install a complete declared example input closure before publishing its project.

This is source materialization, not computation. Callers perform it off the GUI
thread and use ordinary ProjectSession loading once the source is durable.
"""

from importlib.resources import files
from pathlib import Path

from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.project import Project
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.lease import ProjectLease
from code_visualizer.persistence.project_resources import copy_project_resources
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.store import ProjectStore


def source(directory: str) -> tuple[Project, ResourceStore]:
    from code_visualizer.application.examples import PHYSICAL_EXAMPLE_CATALOG

    if directory not in {d.resource_directory for d in PHYSICAL_EXAMPLE_CATALOG}:
        raise ValueError("Unknown registered example resource directory")
    root = Path(str(files("code_visualizer"))) / "resources" / directory
    project = project_from_json((root / "project.json").read_text(encoding="utf-8"))
    return project, ResourceStore(root)


def copy_inputs(project: Project, resources: ResourceStore, destination: Path) -> None:
    registry = builtin_registry()
    copy_project_resources(
        project,
        resources,
        None,
        destination,
        resolve_closure=lambda refs: registry.resource_closure(refs, resources),
    )


def materialize_example(
    directory: str,
    destination: Path,
    *,
    computations: ComputationService | None = None,
) -> ProjectSession:
    project, resources = source(directory)
    store = ProjectStore(destination.resolve())
    lease = ProjectLease.acquire(store.root, owner_id="example-materialization")
    try:
        if store.project_file.exists():
            raise FileExistsError(f"A project already exists at {store.project_file}")
        copy_inputs(project, resources, store.root)
        store.initialize(project)
    finally:
        lease.release()
    return ProjectSession.open(store.root, computations=computations)
