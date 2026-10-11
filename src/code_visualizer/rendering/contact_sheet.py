"""Generated contact sheets and representative layout goldens."""

from __future__ import annotations

from code_visualizer.domain.drakon import Action, DrakonDiagram, End, Header, If, Output, Sequence
from code_visualizer.domain.program_signatures import FunctionSpec
from code_visualizer.rendering.geometry import Point, Rect
from code_visualizer.rendering.recipes import RecipeKind, required_body_width, solve_recipe
from code_visualizer.rendering.scene import (
    DiagramScene,
    LayoutMetrics,
    SceneLabel,
    SceneNode,
    layout_drakon,
)
from code_visualizer.rendering.svg import scene_to_svg
from code_visualizer.rendering.text import DeterministicTextMeasurer

CONTACT_SHEET_WIDTH = 1800.0
CONTACT_SHEET_HEIGHT = 2520.0


def _atomic_specifications() -> tuple[tuple[RecipeKind, dict[str, str], str], ...]:
    """Return all 27 published atomic forms in stable release order."""

    return (
        (RecipeKind.FUNCTION_HEADER, {"title": "shortest_path(graph, start, goal)"}, "01 · Header"),
        (RecipeKind.END, {"text": "End"}, "02 · End"),
        (RecipeKind.ACTION, {"source": "distance = current_cost + weight"}, "03 · Action"),
        (RecipeKind.IF, {"condition": "distance < best[neighbor]"}, "04 · If"),
        (RecipeKind.SELECT, {"select": "match command"}, "05 · Select"),
        (RecipeKind.CASE, {"case": "case 'open' if permitted"}, "06 · Case"),
        (RecipeKind.BRANCH_HEADER, {"branch": "Explore frontier"}, "07 · Branch Header"),
        (RecipeKind.ADDRESS, {"address": "relax neighbors"}, "08 · Address"),
        (RecipeKind.CALL, {"call": "result = solve(graph)"}, "09 · Call"),
        (
            RecipeKind.ASSIGNMENT,
            {"target": "best: dict[str, float]", "value": "initialize_distances(vertices)"},
            "10 · Shelf / Assignment",
        ),
        (
            RecipeKind.SIGNATURE_PANEL,
            {"target": "parameters", "value": "graph, start, goal"},
            "11 · Signature Panel",
        ),
        (RecipeKind.FOR_START, {"loop": "for neighbor, weight in graph[node]"}, "12 · For Start"),
        (RecipeKind.FOR_END, {"loop": "next neighbor"}, "13 · For End"),
        (RecipeKind.OUTPUT, {"expression": 'f"path={path}, cost={cost}"'}, "14 · Output"),
        (RecipeKind.INPUT, {"input": "start = input('Start: ')"}, "15 · Input"),
        (RecipeKind.DELAY, {"delay": "delay 0.25 s"}, "16 · Delay"),
        (
            RecipeKind.PERIOD,
            {"timer": "render_cycle", "seconds": "1/60 s"},
            "17 · Period",
        ),
        (RecipeKind.START_TIMER, {"timer": "start timer · render_cycle"}, "18 · Start Timer"),
        (RecipeKind.SYNCHRONIZER, {"sync": "render_cycle ≤ 1/60 s"}, "19 · Synchronizer"),
        (RecipeKind.REALTIME_PROCESS, {"process": "await refresh_view()"}, "20 · Realtime Process"),
        (RecipeKind.NOTE_RICH, {"note": "Why this route is preferred"}, "21 · Rich Note"),
        (RecipeKind.NOTE_RIGHT, {"note": "Alternate route detail"}, "22 · Right Note"),
        (RecipeKind.NOTE_LEFT, {"note": "Precondition and invariant"}, "23 · Left Note"),
        (RecipeKind.LOOP_RETURN, {"loop": "continue iteration"}, "24 · Loop Return"),
        (
            RecipeKind.SILHOUETTE_TRANSITION,
            {"transition": "transition to Finish"},
            "25 · Silhouette Transition",
        ),
        (RecipeKind.CONNECTOR_MARKER, {"marker": "A"}, "26 · Connector Marker"),
        (
            RecipeKind.CONCURRENT_BOUNDARY,
            {"parallel": "parallel process boundary"},
            "27 · Concurrent Process Boundary",
        ),
    )


def initial_contact_sheet_scene() -> DiagramScene:
    measurer = DeterministicTextMeasurer()
    specifications = _atomic_specifications()
    shared_width = max(
        required_body_width(kind, texts, measurer) for kind, texts, _ in specifications
    )
    nodes: list[SceneNode] = []
    labels: list[SceneLabel] = []
    column_count = 3
    column_width = CONTACT_SHEET_WIDTH / column_count
    row_height = 280.0
    for index, (kind, texts, label) in enumerate(specifications):
        row, column = divmod(index, column_count)
        shape = solve_recipe(kind, texts, measurer, shared_body_width=shared_width)
        center_x = column_width * column + column_width / 2
        top = row * row_height + 92
        origin = Point(center_x - shape.anchor_x, top)
        nodes.append(SceneNode(f"contact_{kind.value}", shape, origin))
        labels.append(
            SceneLabel(
                label,
                Rect(
                    column * column_width + 48,
                    row * row_height + 38,
                    column_width - 96,
                    measurer.line_height,
                ),
                kind.value,
            )
        )
    return DiagramScene(
        diagram_id="complete-atomic-icon-contact-sheet",
        nodes=tuple(nodes),
        routes=(),
        labels=tuple(labels),
        bounds=Rect(0, 0, CONTACT_SHEET_WIDTH, CONTACT_SHEET_HEIGHT),
        skewer_x=0,
        metrics=LayoutMetrics(),
    )


def initial_contact_sheet_svg() -> str:
    return scene_to_svg(initial_contact_sheet_scene())


def initial_if_layout_scene() -> DiagramScene:
    decision = If(
        id="if_request_validity",
        condition="request_is_invalid",
        true_branch=Sequence(
            "sequence_reject",
            (Output("output_rejection", '"request rejected"'),),
        ),
        false_branch=Sequence(
            "sequence_process",
            (
                Action("action_process", 'print("process request")'),
                Action("action_record", 'print("record success")'),
            ),
        ),
        preferred_truth=False,
    )
    diagram = DrakonDiagram(
        id="diagram_if_layout_golden",
        title="Preferred route example",
        header=Header("header_route_demo", FunctionSpec("route_demo", "route demo")),
        body=Sequence(
            "sequence_root",
            (
                Action("action_receive", 'print("receive request")'),
                decision,
                Output("output_complete", '"complete"'),
            ),
        ),
        end=End("end_route_demo"),
    )
    return layout_drakon(diagram)


def initial_if_layout_svg() -> str:
    return scene_to_svg(initial_if_layout_scene())
