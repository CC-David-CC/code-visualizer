"""Export the in-app learning progression as native projects plus artifacts."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from code_visualizer.application.examples import EXAMPLE_CATALOG, example_session
from code_visualizer.generation import atomic_promote_directory, generate_to_disk
from code_visualizer.persistence import ProjectStore

_EXAMPLE_WORKFLOWS = {
    "traffic_light": (
        "\n\n## One state machine, three editable notations\n\n"
        "Open **Domain Workbench** and select **Traffic Light**. The graph, transition "
        "table, and hierarchy share the same state, transition, event, and action IDs. "
        "In the table, rename Yellow to Amber through the Target cell of the "
        "Green transition. The graph, form, semantic search, and generated Python "
        "immediately read the same renamed object. Undo and redo preserve its identity.\n\n"
        "Use **Trace** to execute the default three timer events, or **Debug** and "
        "step through transitions. Runtime highlights refer back to the original "
        "states, transitions, and message actions in every notation. The generated "
        "program and origin map are disposable build artifacts; `project.json` "
        "contains the domain schema, canonical intentions, and typed language definitions.\n\n"
        "## Edit the language itself\n\n"
        "Select **Language authoring > Edit definition** to inspect and change the "
        "notations, validation rules, and transformation templates. The finite-state-machine "
        "behavior in this example is interpreted from these saved definitions; it does not "
        "use the handwritten FSM extension. The structured editor offers typed node choices, "
        "property/role selectors, bindings, symbols, and ordered template bodies. Save, "
        "build, and trace after a change; undo restores the prior language definition. "
        "The **Transition sentences** notation shows editable state names and transition "
        "sentences using the general composition language. Select that notation in the "
        "definition editor and choose **Edit notation expression and preview** to invent "
        "a different layout. Query slots also offer **Edit query expression** for readable "
        "validator and transformation expressions over the same typed definitions. "
        "See `docs/DOMAIN_LANGUAGE.md` and `docs/WORKBENCH_AUTHORING.md` in the source folder.\n"
    ),
    "first_delivery": (
        "\n\n## Semantic authoring walkthrough\n\n"
        "Open **Code Visualizer**, choose **My Lens | Learning progression**, and switch "
        "between Graph and Semantic Text. The saved `First delivery happy path` concept "
        "groups three executable diagrams without moving their Python ownership. Select nodes "
        "and try **Make Mind Map** or **Make Canvas**; the new editable glyphs retain semantic "
        "anchors and remain non-executable compositions.\n"
    ),
    "dijkstra": (
        "\n\n## Runtime visualization walkthrough\n\n"
        "Choose **My Lens | Pathfinding conceptual core** to compare Dijkstra and A*. "
        "Start Debug on the runnable main diagram, then leave the visualizer on "
        "**Control flow** or **Data flow**: runtime is an overlay on every lens. Focus "
        "`frontier`, inspect it as **Heap**, and step to see the active DRAKON node, "
        "incoming route, changed symbol, and heap mutation. Previous/Next/Live recompute "
        "the same overlays for bounded history without rewinding or mutating the program.\n"
    ),
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    target_root = root / "examples" / "projects"
    target_root.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".projects-export-", dir=target_root.parent) as raw:
        staged_root = Path(raw)
        for index, definition in enumerate(EXAMPLE_CATALOG, start=1):
            project_root = staged_root / f"{index:02d}-{definition.id.replace('_', '-')}"
            session = example_session(definition.id)
            try:
                project = session.authority.snapshot()
                store = ProjectStore(project_root)
                store.initialize(project)
                generate_to_disk(project, project_root)
                (project_root / "README.md").write_text(
                    f"# {definition.label}\n\n"
                    f"{definition.description}.\n\n"
                    "Open this directory from Code Visualizer. The canonical editable model is "
                    "`project.json`; `generated/` is a complete manifest-backed artifact set. "
                    "Use document editors for programming examples, or the Domain Workbench "
                    "for domain examples. Save and generate the project, or use the live "
                    "Run/Trace/Debug controls in the relevant editor.\n"
                    f"{_EXAMPLE_WORKFLOWS.get(definition.id, '')}",
                    encoding="utf-8",
                )
            finally:
                session.close()
        atomic_promote_directory(staged_root, target_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
