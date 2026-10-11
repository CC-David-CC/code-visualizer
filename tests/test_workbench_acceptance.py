"""The Traffic Light acceptance loop crosses real authoring and runtime boundaries."""

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.domain_execution import trace_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.notations import notation_edit_command
from code_visualizer.application.search import search_project
from code_visualizer.domain.projection import ProjectionDefinition
from code_visualizer.extensions.fsm import traffic_light_project
from code_visualizer.generation.python import generate_python
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk.client import CodeVisualizerClient


def _tree_objects(roots):
    result = {}
    pending = list(roots)
    while pending:
        node = pending.pop()
        result[node.node_id] = node
        pending.extend(node.children)
    return result


def test_table_rename_save_reload_and_real_trace_return_to_every_domain_notation(tmp_path):
    original = traffic_light_project()
    authority = ProjectAuthority(original)
    kernel = ProjectKernel(authority)
    client = CodeVisualizerClient(authority, actor_id="traffic-light-acceptance")
    try:
        table = kernel.notation("traffic:model", "fsm:table")
        row = next(item for item in table.rows if item.node_id == "traffic:green-yellow")
        target = next(cell for cell in row.cells if cell.semantic_id == "traffic:yellow")
        assert target.text == "Yellow"
        assert target.edit is not None
        command = notation_edit_command(target.edit, "Amber", revision=kernel.revision)
        assert isinstance(
            client.submit(command, expected_revision=target.edit.revision), CommandAccepted
        )
        renamed = authority.snapshot()
        assert len(renamed.domain_workspace.models[0].nodes) == len(
            original.domain_workspace.models[0].nodes
        )
        assert {node.id for node in renamed.domain_workspace.models[0].nodes} == {
            node.id for node in original.domain_workspace.models[0].nodes
        }
        assert renamed.domain_workspace.node("traffic:green-yellow").references == (
            original.domain_workspace.node("traffic:green-yellow").references
        )
        assert (
            next(
                node
                for node in kernel.notation("traffic:model", "fsm:graph").graph.nodes
                if node.id == "traffic:yellow"
            ).label
            == "Amber"
        )
        assert (
            _tree_objects(kernel.notation("traffic:model", "fsm:form").roots)[
                "traffic:yellow"
            ].label
            == "Amber"
        )
        assert kernel.queries.semantic_object("traffic:yellow").label == "Amber"
        assert {match.object_id for match in search_project(renamed, "Amber")} == {"traffic:yellow"}
        assert isinstance(client.undo(), CommandAccepted)
        assert authority.snapshot().domain_workspace == original.domain_workspace
        assert isinstance(client.redo(), CommandAccepted)
        assert authority.snapshot().domain_workspace == renamed.domain_workspace
        source = tmp_path / "project.json"
        serialized = normalized_project_json(authority.snapshot())
        source.write_text(serialized, encoding="utf-8")
        reloaded = project_from_json(source.read_text(encoding="utf-8"))
        assert normalized_project_json(reloaded) == serialized
        assert reloaded.domain_workspace == renamed.domain_workspace
        assert reloaded.program_model.functions == ()
    finally:
        client.close()
        kernel.close()

    # Observe the real registry notification. No synthetic active IDs or private
    # registry mutation stand in for the trace-to-notation integration.
    kernel = ProjectKernel(ProjectAuthority(reloaded))
    generated = generate_python(reloaded)
    assert "Amber" in generated.source
    assert "Yellow" not in generated.source
    captured = []
    intended_ids = {"traffic:green-yellow", "traffic:yellow", "traffic:signal"}

    def observe(state):
        if captured or not intended_ids <= set(state.origin_ids):
            return
        captured.append(
            (
                state,
                kernel.notation("traffic:model", "fsm:graph"),
                kernel.notation("traffic:model", "fsm:table"),
                kernel.notation("traffic:model", "fsm:form"),
                kernel.compose_projection(ProjectionDefinition("domain", "Domain intentions")),
            )
        )

    unsubscribe = kernel.runtime.subscribe(observe, replay=False)
    before_run = normalized_project_json(reloaded)
    try:
        trace = trace_project(kernel, model_id="traffic:model")
        assert trace.run.return_code == 0, trace.run.stderr
        assert "Amber" in trace.run.stdout
        assert captured
        state, graph, table, form, lens = captured[0]
        assert state.project_revision == reloaded.revision
        assert state.artifact_revision == reloaded.revision
        assert state.semantic_id in {span.semantic_id for span in generated.spans}
        assert generated.origins is not None
        assert intended_ids <= set(generated.origins.sources(state.semantic_id))
        assert any(
            event.event_sequence == state.event_sequence and event.origin_ids == state.origin_ids
            for event in kernel.runtime.history(state.execution_session_id)
        )
        assert (
            "active"
            in next(node for node in graph.graph.nodes if node.id == "traffic:yellow").badges
        )
        assert next(edge for edge in graph.graph.edges if edge.id == "traffic:green-yellow").active
        active_row = next(row for row in table.rows if row.node_id == "traffic:green-yellow")
        assert active_row.active
        assert {"traffic:yellow", "traffic:signal"} <= {
            cell.semantic_id for cell in active_row.cells
        }
        tree = _tree_objects(form.roots)
        assert all(tree[identity].active for identity in intended_ids)
        assert tree["traffic:yellow"].label == "Amber"
        assert intended_ids <= {node.semantic_id for node in lens.nodes if "active" in node.badges}
        assert kernel.selection.state.execution_session_id == state.execution_session_id
        assert normalized_project_json(kernel.authority.snapshot()) == before_run
        assert kernel.authority.snapshot().program_model.functions == ()
    finally:
        unsubscribe()
        kernel.close()
