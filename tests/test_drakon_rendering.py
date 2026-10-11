from dataclasses import replace

from hypothesis import given
from hypothesis import strategies as st

from code_visualizer.application.project_factory import (
    create_default_project,
    initialize_project_documents,
)
from code_visualizer.domain.common import new_id
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    If,
    Output,
    Sequence,
    create_empty_drakon,
)
from code_visualizer.generation import generate_python
from code_visualizer.rendering import layout_drakon, scene_to_svg
from code_visualizer.rendering.recipes import RecipeKind, U, solve_recipe
from code_visualizer.rendering.text import DeterministicTextMeasurer


def _decision(*, preferred_truth: bool = True) -> If:
    return If(
        id=new_id("if"),
        condition="value > 0",
        true_branch=Sequence(
            new_id("sequence"),
            (Action(new_id("action"), 'print("positive")'),),
        ),
        false_branch=Sequence(
            new_id("sequence"),
            (Action(new_id("action"), 'print("not positive")'),),
        ),
        preferred_truth=preferred_truth,
    )


def _diagram_with(*atoms):
    diagram = create_empty_drakon()
    return replace(diagram, body=replace(diagram.body, atoms=tuple(atoms)))


def test_routes_are_orthogonal_metadata_covers_horizontal_and_vertical_boundaries() -> None:
    decision = _decision()
    diagram = _diagram_with(
        Action(new_id("action"), "value = 1"),
        decision,
        Output(new_id("output"), '"done"'),
    )

    scene = layout_drakon(diagram)

    assert all(
        route.segment.start.x == route.segment.end.x or route.segment.start.y == route.segment.end.y
        for route in scene.routes
    )
    secondary = [
        route
        for route in scene.insertion_routes()
        if route.boundary
        and route.boundary.sequence_id == decision.false_branch.id
        and route.boundary.index == 0
    ]
    assert any(route.segment.is_horizontal for route in secondary)
    assert any(not route.segment.is_horizontal for route in secondary)
    root_boundaries = {
        route.boundary.index
        for route in scene.insertion_routes()
        if route.boundary and route.boundary.sequence_id == diagram.body.id
    }
    assert root_boundaries == {0, 1, 2, 3}


def test_fit_bounds_include_every_connector_and_label() -> None:
    scene = layout_drakon(_diagram_with(_decision()))

    for route in scene.routes:
        assert scene.bounds.contains(route.segment.start)
        assert scene.bounds.contains(route.segment.end)
    for label in scene.labels:
        assert scene.bounds.contains(label.bounds.center)


def test_output_and_shelf_reserve_air_around_internal_strokes() -> None:
    measurer = DeterministicTextMeasurer()
    output = solve_recipe(
        RecipeKind.OUTPUT,
        {"expression": '"a moderately long output value"'},
        measurer,
    )
    divider_x = output.dividers[0].start.x
    output_text = output.text_blocks[0].safe_bounds
    assert output_text.right <= divider_x - U

    shelf = solve_recipe(
        RecipeKind.ASSIGNMENT,
        {
            "target": "four_assignments_need_independent_targets: list[int]",
            "value": "build_a_long_value_without_touching_the_divider()",
        },
        measurer,
    )
    divider_y = shelf.dividers[0].start.y
    upper, lower = shelf.text_blocks
    assert upper.safe_bounds.bottom < divider_y
    assert lower.safe_bounds.top > divider_y


@given(
    st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=1, max_size=300)
)
def test_action_recipe_wraps_arbitrary_printable_text_inside_safe_region(text: str) -> None:
    measurer = DeterministicTextMeasurer()
    shape = solve_recipe(RecipeKind.ACTION, {"source": text}, measurer)
    block = shape.text_blocks[0]

    assert block.safe_bounds.left > shape.bounds.left
    assert block.safe_bounds.right < shape.bounds.right
    assert all(measurer.measure_line(line).width <= block.safe_bounds.width for line in block.lines)
    assert len(block.lines) * measurer.line_height <= block.safe_bounds.height


@given(preferred_truth=st.booleans())
def test_preference_and_truth_are_independent_in_layout_and_python(
    preferred_truth: bool,
) -> None:
    decision = _decision(preferred_truth=preferred_truth)
    diagram = _diagram_with(decision)
    scene = layout_drakon(diagram)
    project = create_default_project()
    project = initialize_project_documents(
        replace(
            project,
            program_model=replace(
                project.program_model,
                entrypoint=replace(project.program_model.entrypoint, callable_id=diagram.id),
            ),
        ),
        (diagram,),
    )

    assert any(label.text == f"{preferred_truth} · preferred" for label in scene.labels)
    assert any(label.text == f"{not preferred_truth} · alternate" for label in scene.labels)
    decision_node = next(node for node in scene.nodes if node.object_id == decision.id)
    assert (
        next(port for port in decision_node.shape.ports if port.name == "down").truth
        is preferred_truth
    )
    assert (
        next(port for port in decision_node.shape.ports if port.name == "right").truth
        is not preferred_truth
    )
    source = generate_python(project).source
    if preferred_truth:
        assert "if value > 0:" in source
        assert source.index("print('positive')") < source.index("print('not positive')")
    else:
        assert "if not (value > 0):" in source
        assert source.index("print('not positive')") < source.index("print('positive')")


def test_svg_is_vector_only_and_exposes_insertion_metadata() -> None:
    diagram = _diagram_with(_decision())
    svg = scene_to_svg(layout_drakon(diagram))

    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "data-insertion-boundary" in svg
    assert "<image" not in svg
    assert "<script" not in svg
    assert svg == scene_to_svg(layout_drakon(diagram))


def test_final_nodes_do_not_overlap_and_share_exact_skewer_coordinate() -> None:
    diagram = _diagram_with(
        Action(new_id("action"), "value = 1"),
        Output(new_id("output"), '"value"'),
        Assignment(new_id("assignment"), "answer", "value + 41"),
    )
    scene = layout_drakon(diagram)

    for index, left in enumerate(scene.nodes):
        for right in scene.nodes[index + 1 :]:
            assert not left.bounds.intersects(right.bounds)
    for node in scene.nodes:
        port_name = "output" if node.object_id == diagram.header.id else "input"
        assert node.port(port_name).x == scene.skewer_x


@given(
    preferred_truth=st.booleans(),
    true_count=st.integers(min_value=0, max_value=4),
    false_count=st.integers(min_value=0, max_value=4),
    prefix_count=st.integers(min_value=0, max_value=3),
)
def test_layout_projects_every_recursive_boundary_without_node_overlap(
    preferred_truth: bool,
    true_count: int,
    false_count: int,
    prefix_count: int,
) -> None:
    true_branch = Sequence(
        new_id("sequence"),
        tuple(
            Action(new_id("action"), f"true_value_{index} = {index}") for index in range(true_count)
        ),
    )
    false_branch = Sequence(
        new_id("sequence"),
        tuple(
            Action(new_id("action"), f"false_value_{index} = {index}")
            for index in range(false_count)
        ),
    )
    decision = If(
        new_id("if"),
        "flag",
        true_branch,
        false_branch,
        preferred_truth,
    )
    prefix = tuple(
        Action(new_id("action"), f"prefix_{index} = {index}") for index in range(prefix_count)
    )
    diagram = _diagram_with(*prefix, decision)
    scene = layout_drakon(diagram)

    expected_boundaries = {
        *((diagram.body.id, index) for index in range(len(diagram.body.atoms) + 1)),
        *((true_branch.id, index) for index in range(len(true_branch.atoms) + 1)),
        *((false_branch.id, index) for index in range(len(false_branch.atoms) + 1)),
    }
    actual_boundaries = {
        (route.boundary.sequence_id, route.boundary.index)
        for route in scene.insertion_routes()
        if route.boundary is not None
    }
    assert actual_boundaries == expected_boundaries
    for index, left in enumerate(scene.nodes):
        for right in scene.nodes[index + 1 :]:
            assert not left.bounds.intersects(right.bounds)
