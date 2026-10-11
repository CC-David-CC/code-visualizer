from dataclasses import replace

from code_visualizer.application.navigation import (
    NavigationHistory,
    NavigationLocation,
    build_call_hierarchy,
    find_address_transitions,
    find_callers,
)
from code_visualizer.application.project_factory import (
    create_default_project,
    initialize_project_documents,
)
from code_visualizer.domain.drakon import (
    Call,
    DrakonDiagram,
    Sequence,
    Silhouette,
    SilhouetteBranch,
    create_empty_drakon,
)


def test_stable_call_and_address_queries_mark_recursive_cycles() -> None:
    project = create_default_project(title="Navigation")
    main = project.documents[0]
    assert isinstance(main, DrakonDiagram)
    helper = create_empty_drakon(identifier="helper", title="Helper", diagram_id="helper")
    main = replace(
        main,
        body=Sequence(main.body.id, (Call("call_helper", target_diagram_id=helper.id),)),
    )
    helper = replace(
        helper,
        body=Sequence(helper.body.id, (Call("call_main", target_diagram_id=main.id),)),
    )
    silhouette = Silhouette(
        "workflow",
        "Workflow",
        "workflow",
        (
            SilhouetteBranch("state_ready", "Ready", Sequence("ready_body"), "state_done"),
            SilhouetteBranch("state_done", "Done", Sequence("done_body"), None),
        ),
        "state_ready",
    )
    helper = replace(helper, body=Sequence(helper.body.id, (*helper.body.atoms, silhouette)))
    project = initialize_project_documents(project, (main, helper))

    callers = find_callers(project, helper.id)
    assert len(callers) == 1
    assert callers[0].source == NavigationLocation(main.id, "call_helper", "target_diagram_id")
    assert callers[0].target_diagram_id == helper.id

    addresses = find_address_transitions(project, diagram_id=helper.id)
    assert len(addresses) == 1
    assert addresses[0].target_object_id == "state_done"
    assert addresses[0].source.object_id == silhouette.id
    assert "state_ready" in addresses[0].stable_path

    hierarchy = build_call_hierarchy(project, main.id)
    assert hierarchy.children[0].diagram_id == helper.id
    recursive = hierarchy.children[0].children[0]
    assert recursive.diagram_id == main.id
    assert recursive.cycle
    assert not recursive.children


def test_navigation_history_clamps_and_drops_abandoned_forward_path() -> None:
    history = NavigationHistory(limit=3)
    first = NavigationLocation("first")
    second = NavigationLocation("second", "atom")
    third = NavigationLocation("third")
    replacement = NavigationLocation("replacement")

    history.visit(first)
    history.visit(second)
    history.visit(third)
    assert history.back() == second
    history.visit(replacement)
    assert not history.can_go_forward
    assert history.back() == second
    assert history.back() == first
    assert history.back() is None
