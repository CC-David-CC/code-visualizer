from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    Rect,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.domain.mindmap import MindMapDiagram, find_topic


def test_ordered_mindmap_commands_prevent_cycles_promote_and_undo() -> None:
    session = ProjectSession.new()
    try:
        created = session.client.create_diagram(DocumentKind.MIND_MAP, "Release map")
        assert isinstance(created, CommandAccepted)
        diagram = session.authority.snapshot().documents[-1]
        assert isinstance(diagram, MindMapDiagram)
        root_id = diagram.root.id

        first = session.client.add_mindmap_topic(
            diagram.id,
            root_id,
            "Plan",
            0,
            topic_id="topic_plan",
        )
        assert isinstance(first, CommandAccepted)
        session.client.add_mindmap_topic(
            diagram.id,
            root_id,
            "Ship",
            1,
            topic_id="topic_ship",
        )
        session.client.add_mindmap_topic(
            diagram.id,
            "topic_plan",
            "Tests",
            0,
            topic_id="topic_tests",
        )
        rejected = session.client.move_mindmap_topic(
            diagram.id,
            "topic_plan",
            "topic_tests",
            0,
        )
        assert isinstance(rejected, CommandRejected)
        assert rejected.code == "MIND_INVALID_MOVE"

        session.client.update_mindmap_topic(
            diagram.id,
            "topic_tests",
            "Automated tests",
            notes="Run before release",
            collapsed=True,
            links=("https://example.invalid/checklist",),
        )
        session.client.add_mindmap_cross_link(
            diagram.id,
            "topic_tests",
            "topic_ship",
            label="unblocks",
            link_id="cross_release",
        )
        session.client.set_mindmap_layout(diagram.id, "left_to_right")
        session.client.remove_mindmap_topic(
            diagram.id,
            "topic_plan",
            promote_children=True,
        )
        updated = session.authority.snapshot().documents[-1]
        assert isinstance(updated, MindMapDiagram)
        assert tuple(child.id for child in updated.root.children) == (
            "topic_tests",
            "topic_ship",
        )
        promoted = find_topic(updated.root, "topic_tests")
        assert promoted is not None
        assert promoted.notes == "Run before release"
        assert updated.layout == "left_to_right"
        assert updated.cross_links[0].id == "cross_release"

        undone = session.client.undo()
        assert isinstance(undone, CommandAccepted)
        restored = session.authority.snapshot().documents[-1]
        assert isinstance(restored, MindMapDiagram)
        assert find_topic(restored.root, "topic_plan") is not None
    finally:
        session.close()


def test_freeform_shapes_connect_transform_group_arrange_lock_remove_and_undo() -> None:
    session = ProjectSession.new()
    try:
        session.client.create_diagram(DocumentKind.FREEFORM, "Architecture sketch")
        diagram = session.authority.snapshot().documents[-1]
        assert isinstance(diagram, FreeformDiagram)
        for object_id, x, text in (
            ("shape_input", 10.0, "Input"),
            ("shape_process", 180.0, "Process"),
            ("shape_output", 410.0, "Output"),
        ):
            result = session.client.create_freeform_shape(
                diagram.id,
                ShapeKind.ROUNDED_RECTANGLE,
                Rect(x, 40.0 + x / 10, 120.0, 64.0),
                text=text,
                object_id=object_id,
            )
            assert isinstance(result, CommandAccepted)
        session.client.connect_freeform_objects(
            diagram.id,
            "shape_input",
            "shape_process",
            connector_id="connector_one",
        )
        session.client.set_freeform_properties(
            diagram.id,
            ("shape_input", "shape_process"),
            group_id="group_pipeline",
        )
        session.client.arrange_freeform_objects(
            diagram.id,
            ("shape_input", "shape_process", "shape_output"),
            "align_top",
        )
        session.client.transform_freeform_object(
            diagram.id,
            "shape_output",
            Rect(410.0, 41.0, 150.0, 72.0),
            rotation=15.0,
        )
        session.client.set_freeform_properties(
            diagram.id,
            ("shape_output",),
            locked=True,
        )
        rejected = session.client.transform_freeform_object(
            diagram.id,
            "shape_output",
            Rect(0.0, 0.0, 1.0, 1.0),
        )
        assert isinstance(rejected, CommandRejected)
        assert rejected.code == "FREEFORM_OBJECT_LOCKED"

        updated = session.authority.snapshot().documents[-1]
        assert isinstance(updated, FreeformDiagram)
        shapes = {item.id: item for item in updated.objects if isinstance(item, ShapeObject)}
        assert {item.bounds.y for item in shapes.values()} == {41.0}
        assert shapes["shape_input"].group_id == "group_pipeline"
        assert shapes["shape_output"].rotation == 15.0
        assert any(isinstance(item, ConnectorObject) for item in updated.objects)

        session.client.remove_freeform_objects(diagram.id, ("shape_process",))
        removed = session.authority.snapshot().documents[-1]
        assert isinstance(removed, FreeformDiagram)
        assert "connector_one" not in {item.id for item in removed.objects}
        session.client.undo()
        restored = session.authority.snapshot().documents[-1]
        assert isinstance(restored, FreeformDiagram)
        assert "connector_one" in {item.id for item in restored.objects}
    finally:
        session.close()
