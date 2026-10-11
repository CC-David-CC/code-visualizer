import xml.etree.ElementTree as ET

import pytest

from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    Point,
    Rect,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.domain.mindmap import CrossLink, MindMapDiagram, Topic
from code_visualizer.rendering import (
    layout_freeform,
    layout_mind_map,
    projected_edge_points,
    vector_scene_to_svg,
)


def _mind_map(layout: str) -> MindMapDiagram:
    return MindMapDiagram(
        "mind_release",
        "First delivery knowledge map",
        Topic(
            "topic_root",
            "First delivery",
            (
                Topic(
                    "topic_build",
                    "Build",
                    (
                        Topic("topic_code", "Visual Python"),
                        Topic("topic_tests", "Deterministic tests"),
                    ),
                    notes="Implementation branch",
                ),
                Topic("topic_ship", "Ship", (Topic("topic_docs", "Documentation"),)),
                Topic("topic_learn", "Learn", collapsed=True),
            ),
        ),
        (CrossLink("cross_test_ship", "topic_tests", "topic_ship", "unblocks"),),
        layout,
    )


@pytest.mark.parametrize(
    "layout",
    ("balanced", "left_to_right", "right_to_left", "radial"),
)
def test_mindmap_layouts_are_deterministic_complete_and_self_contained(layout: str) -> None:
    first = layout_mind_map(_mind_map(layout))
    second = layout_mind_map(_mind_map(layout))
    assert first == second
    assert {node.object_id for node in first.nodes} == {
        "topic_root",
        "topic_build",
        "topic_code",
        "topic_tests",
        "topic_ship",
        "topic_docs",
        "topic_learn",
    }
    assert all(first.bounds.intersects(node.bounds) for node in first.nodes)
    svg = vector_scene_to_svg(first)
    assert svg == vector_scene_to_svg(second)
    ET.fromstring(svg)
    assert "<script" not in svg.casefold()
    assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "")


def test_freeform_scene_includes_shapes_connectors_arrows_and_real_bounds() -> None:
    diagram = FreeformDiagram(
        "free_scene",
        "System sketch",
        (
            ShapeObject(
                "shape_a",
                ShapeKind.ROUNDED_RECTANGLE,
                Rect(-120.0, 20.0, 150.0, 70.0),
                "Input",
            ),
            ShapeObject(
                "shape_b",
                ShapeKind.ELLIPSE,
                Rect(260.0, 170.0, 180.0, 90.0),
                "Output",
            ),
            ShapeObject(
                "shape_arrow",
                ShapeKind.ARROW,
                Rect(20.0, 300.0, 250.0, 20.0),
                "",
            ),
            ConnectorObject("connector_ab", "shape_a", "shape_b", label="data"),
        ),
    )
    scene = layout_freeform(diagram)
    assert scene.bounds.left < -120.0
    assert scene.bounds.right > 440.0
    assert len(scene.edges[0].points) == 4
    svg = vector_scene_to_svg(scene)
    ET.fromstring(svg)
    assert "marker-end" in svg
    assert "connector_ab" in svg
    assert svg == vector_scene_to_svg(layout_freeform(diagram))


def test_later_freeform_connector_gets_deterministic_bridge_at_proper_crossing() -> None:
    diagram = FreeformDiagram(
        "free_crossing",
        "Connector bridge",
        (
            ShapeObject("left", ShapeKind.RECTANGLE, Rect(-30, 35, 20, 30)),
            ShapeObject("right", ShapeKind.RECTANGLE, Rect(210, 35, 20, 30)),
            ShapeObject("top", ShapeKind.RECTANGLE, Rect(85, -30, 30, 20)),
            ShapeObject("bottom", ShapeKind.RECTANGLE, Rect(85, 110, 30, 20)),
            ConnectorObject(
                "horizontal",
                "left",
                "right",
                points=(Point(0, 50), Point(200, 50)),
            ),
            ConnectorObject(
                "vertical",
                "top",
                "bottom",
                points=(Point(100, 0), Point(100, 100)),
            ),
        ),
    )

    scene = layout_freeform(diagram)
    horizontal, vertical = scene.edges
    assert horizontal.bridges == ()
    assert len(vertical.bridges) == 1
    assert vertical.bridges[0].point.x == 100
    assert vertical.bridges[0].point.y == 50
    projected = projected_edge_points(vertical)
    assert len(projected) > len(vertical.points)
    assert min(point.x for point in projected) < 100
    svg = vector_scene_to_svg(scene)
    assert 'id="vertical"' in svg
    assert 'data-bridges="1"' in svg
    assert svg == vector_scene_to_svg(layout_freeform(diagram))
