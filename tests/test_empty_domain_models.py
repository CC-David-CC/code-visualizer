from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.drakon import DrakonDiagram, create_empty_drakon
from code_visualizer.domain.freeform import create_empty_freeform
from code_visualizer.domain.mindmap import create_empty_mind_map


def test_empty_drakon_has_intrinsic_header_sequence_and_single_end() -> None:
    diagram = create_empty_drakon(identifier="main", title="main")

    assert diagram.header.function.identifier == "main"
    assert diagram.body.atoms == ()
    assert diagram.end.id.startswith("end_")


def test_empty_mind_map_has_exactly_one_root() -> None:
    diagram = create_empty_mind_map()

    assert diagram.root.text == "Central topic"
    assert diagram.root.children == ()
    assert diagram.cross_links == ()


def test_empty_freeform_scene_has_no_objects() -> None:
    diagram = create_empty_freeform()

    assert diagram.objects == ()


def test_default_project_exposes_runnable_main_skeleton() -> None:
    project = create_default_project()
    main = project.documents[0]

    assert isinstance(main, DrakonDiagram)
    assert project.title == "Untitled Project"
    assert project.program_model.entrypoint_callable_id == main.id
    assert main.body.atoms == ()
    assert main.end.id.startswith("end_")
