from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.freeform import create_empty_freeform
from code_visualizer.domain.mindmap import create_empty_mind_map
from code_visualizer.domain.project import Project
from code_visualizer.persistence.serialization import normalized_project_json


def test_all_three_empty_models_serialize_deterministically() -> None:
    base = create_default_project(title="All Modes")
    project = Project(
        id=base.id,
        title=base.title,
        documents=(
            base.documents[0],
            create_empty_mind_map(title="Knowledge"),
            create_empty_freeform(title="Sketch"),
        ),
        runtime_settings=base.runtime_settings,
    )

    first = normalized_project_json(project)
    second = normalized_project_json(project)

    assert first == second
    assert first.endswith("\n")
    assert '"format_revision": 11' in first
    assert '"kind": "drakon"' in first
    assert '"kind": "mind_map"' in first
    assert '"kind": "freeform"' in first
