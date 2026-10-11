import ast
import json
from collections.abc import Iterator
from pathlib import Path

from code_visualizer.application.examples import EXAMPLE_CATALOG, example_session
from code_visualizer.domain.drakon import (
    DrakonAtom,
    DrakonDiagram,
    If,
    Output,
    Sequence,
    Silhouette,
    nested_sequences,
)
from code_visualizer.domain.freeform import FreeformDiagram, ShapeObject
from code_visualizer.domain.mindmap import MindMapDiagram, walk_topics
from code_visualizer.execution import run_generated, run_project
from code_visualizer.generation import (
    expected_artifact_contents,
    generate_python_project,
)
from code_visualizer.persistence import ProjectStore
from code_visualizer.rendering import document_to_svg, layout_drakon, project_document
from code_visualizer.validation import Severity, validate_project


def _walk_atoms(sequence: Sequence) -> Iterator[DrakonAtom]:
    for atom in sequence.atoms:
        yield atom
        for nested in nested_sequences(atom):
            yield from _walk_atoms(nested)


def test_learning_progression_has_simple_to_advanced_projects_that_compile() -> None:
    assert len(EXAMPLE_CATALOG) >= 13
    assert EXAMPLE_CATALOG[0].id == "hello_world"
    assert EXAMPLE_CATALOG[15].id == "computational_instrument"
    assert EXAMPLE_CATALOG[16].id == "traffic_light"

    for definition in EXAMPLE_CATALOG:
        session = example_session(definition.id)
        try:
            project = session.authority.snapshot()
            errors = [item for item in validate_project(project) if item.severity is Severity.ERROR]
            assert errors == [], definition.id
            generated = generate_python_project(project)
            assert generated.files
            for item in generated.files:
                compile(item.source, item.path, "exec")
        finally:
            session.close()


def test_pathfinding_example_runs_dijkstra_and_a_star_with_the_expected_path() -> None:
    session = example_session("dijkstra")
    try:
        project = session.authority.snapshot()
        assert {concept.id for concept in project.concepts} == {
            "concept_pathfinding_search",
            "concept_frontier_relaxation",
        }
        projection = session.kernel.queries.saved_projection("projection_pathfinding_core")
        assert projection is not None
        assert {item.semantic_id for item in projection.nodes} >= {
            "concept_pathfinding_search",
            "concept_frontier_relaxation",
            "diagram_dijkstra_algorithm",
            "diagram_a_star_algorithm",
        }
        result = run_project(generate_python_project(project))
    finally:
        session.close()

    assert result.return_code == 0
    assert result.stdout.count("['A', 'C', 'B', 'D']") == 2
    assert "Dijkstra path:" in result.stdout
    assert "A* path:" in result.stdout
    assert result.stdout.count("total cost: 4.0") == 2


def test_computational_instrument_generates_and_runs_a_nested_python_system(tmp_path) -> None:
    session = example_session("computational_instrument")
    try:
        project = session.authority.snapshot()
        assert project.program_model.package == "bci"
        assert len(project.documents) == 9
        assert {module.path for module in project.program_model.modules} == {
            "main",
            "math.numerical",
            "math.vectors",
            "model.snapshots",
            "simulation.integrators",
            "simulation.scheduler",
            "telemetry.signals",
            "testing.replay_checks",
            "ui.scope",
        }
        errors = [item for item in validate_project(project) if item.severity is Severity.ERROR]
        assert errors == []

        root = tmp_path / "computational-instrument"
        session.save_as(root)
        result = session.generate()
        relative = {path.relative_to(result.root).as_posix() for path in result.files}
        assert {
            "bci/__init__.py",
            "bci/main.py",
            "bci/math/__init__.py",
            "bci/math/numerical.py",
            "bci/math/vectors.py",
            "bci/model/snapshots.py",
            "bci/simulation/integrators.py",
            "bci/simulation/scheduler.py",
            "bci/telemetry/signals.py",
            "bci/testing/replay_checks.py",
            "bci/ui/scope.py",
            "project.graph-index.json",
            "diagrams/bci/math/vectors/add_vectors.svg",
            "diagrams/bci/simulation/scheduler/run_instrument.svg",
        } <= relative

        graph_index = json.loads(
            (result.root / "project.graph-index.json").read_text(encoding="utf-8")
        )
        assert graph_index["package"] == "bci"
        assert len(graph_index["documents"]) == 9
        for document in graph_index["documents"]:
            assert (result.root / document["code_path"]).is_file()
            assert (result.root / document["graph_path"]).is_file()

        run = run_generated(result.root / "run_project.py")
        assert run.return_code == 0
        assert run.stdout.splitlines() == [
            (
                "BCI scope | samples=(1.5, 1.5, 4.0) | mean=2.33 | state=9.50 | "
                "3 samples @ mean 2.33"
            ),
            "Replay deterministic: True",
        ]
        recovered = ProjectStore(root).recover(promote=False)
        assert recovered.runtime_settings == project.runtime_settings
        assert recovered.program_model == project.program_model
        assert recovered.documents == project.documents
    finally:
        session.close()


def test_golden_node_output_follows_the_silhouette_instead_of_being_inside_an_if() -> None:
    session = example_session("silhouette")
    try:
        project = session.authority.snapshot()
        diagram = project.documents[0]
        assert isinstance(diagram, DrakonDiagram)
        assert len(diagram.body.atoms) == 2
        silhouette, output = diagram.body.atoms
        assert isinstance(silhouette, Silhouette)
        assert isinstance(output, Output)
        assert not any(isinstance(atom, If) for atom in _walk_atoms(diagram.body))

        branches = {branch.id: branch for branch in silhouette.branches}
        visited: list[str] = []
        current: str | None = silhouette.initial_branch_id
        while current is not None:
            assert current not in visited
            visited.append(current)
            current = branches[current].target_branch_id
        assert set(visited) == set(branches)
        assert sum(branch.target_branch_id is None for branch in silhouette.branches) == 1

        scene = layout_drakon(diagram)
        output_node = next(node for node in scene.nodes if node.object_id == output.id)
        silhouette_node_ids = {
            silhouette.id,
            *(branch.id for branch in silhouette.branches),
            *(f"{branch.id}:address" for branch in silhouette.branches),
            *(atom.id for branch in silhouette.branches for atom in _walk_atoms(branch.body)),
        }
        silhouette_bottom = max(
            node.bounds.bottom for node in scene.nodes if node.object_id in silhouette_node_ids
        )
        assert output_node.bounds.top > silhouette_bottom
        assert any(
            route.boundary is not None
            and route.boundary.sequence_id == diagram.body.id
            and route.boundary.index == 1
            and route.segment.end.y == output_node.bounds.top
            for route in scene.routes
        )

        generated = generate_python_project(project)
        module_source = generated.file("app/main.py").source
        function = next(
            item
            for item in ast.parse(module_source).body
            if isinstance(item, ast.FunctionDef) and item.name == "main"
        )
        assert isinstance(function, ast.FunctionDef)
        assert isinstance(function.body[1], ast.While)
        assert any(isinstance(statement, ast.If) for statement in function.body[1].body)
        post_silhouette = function.body[2]
        assert isinstance(post_silhouette, ast.Expr)
        assert isinstance(post_silhouette.value, ast.Call)
        assert isinstance(post_silhouette.value.func, ast.Name)
        assert post_silhouette.value.func.id == "print"
        assert isinstance(post_silhouette.value.args[0], ast.Constant)
        assert post_silhouette.value.args[0].value == "output"

        result = run_project(generated)
        assert result.return_code == 0
        assert result.stdout.splitlines() == [
            "start state action",
            "finish state action",
            "output",
        ]
    finally:
        session.close()


def test_first_delivery_is_a_small_complete_shared_semantic_project() -> None:
    session = example_session("first_delivery")
    try:
        project = session.authority.snapshot()
        assert project.title == "First Delivery — Shared Semantic Starter"
        assert sum(isinstance(item, DrakonDiagram) for item in project.documents) == 3
        assert sum(isinstance(item, MindMapDiagram) for item in project.documents) == 1
        assert sum(isinstance(item, FreeformDiagram) for item in project.documents) == 1
        mind_map = next(item for item in project.documents if isinstance(item, MindMapDiagram))
        freeform = next(item for item in project.documents if isinstance(item, FreeformDiagram))
        assert {topic.semantic_id for topic in walk_topics(mind_map.root) if topic.semantic_id} >= {
            project.id,
            "diagram_first_hello",
            "diagram_first_decision",
            "output_first_hello",
        }
        assert {
            item.semantic_id
            for item in freeform.objects
            if isinstance(item, ShapeObject) and item.semantic_id
        } == {project.id, "diagram_first_hello"}
        assert session.kernel.queries.views_for("diagram_first_hello")
        assert project.concepts[0].id == "concept_first_delivery_happy_path"
        learning = session.kernel.queries.saved_projection("projection_first_delivery_learning")
        assert learning is not None
        assert {item.semantic_id for item in learning.nodes} >= {
            "concept_first_delivery_happy_path",
            "diagram_first_hello",
            "diagram_first_decision",
            "diagram_first_loop",
        }
        for document in project.documents:
            scene = project_document(document)
            assert scene.bounds.width > 0
            assert scene.bounds.height > 0
            svg = document_to_svg(document)
            assert svg.startswith("<svg")
            assert svg.endswith("</svg>\n")
        result = run_project(generate_python_project(project))
        assert result.return_code == 0
        assert result.stdout == "Hello, world!\n"
    finally:
        session.close()


def test_example_artifact_fixtures_exactly_match_their_native_projects() -> None:
    root = Path(__file__).resolve().parents[1]
    example_root = root / "examples" / "projects"
    fixtures = json.loads(
        (root / "tests/fixtures/example-artifacts.json").read_text(encoding="utf-8")
    )
    expected_directories = tuple(
        f"{index:02d}-{definition.id.replace('_', '-')}"
        for index, definition in enumerate(EXAMPLE_CATALOG, start=1)
    )
    project_directories = tuple(
        path.name
        for path in sorted(example_root.iterdir())
        if path.is_dir() and (path / "project.json").is_file()
    )
    assert project_directories == expected_directories
    assert set(fixtures) == set(expected_directories)

    for directory in expected_directories:
        project_root = example_root / directory
        project = ProjectStore(project_root).recover(promote=False)
        expected = expected_artifact_contents(project, project_root=project_root)
        actual = fixtures[directory]
        assert set(actual) == set(expected), directory
        for relative, source in expected.items():
            assert actual[relative] == source, (
                directory,
                relative,
            )
