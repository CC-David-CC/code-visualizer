from dataclasses import replace
from pathlib import Path

from code_visualizer.application.commands import ReplaceDiagramSnapshot
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.program_model import canonicalize_project, function_for_document
from code_visualizer.application.projection_language import (
    builtin_projection_definition,
    compile_projection,
)
from code_visualizer.application.runtime_overlay import (
    RuntimeOverlayContext,
    overlay_runtime_context,
)
from code_visualizer.application.runtime_projection import RuntimeAdapterKind
from code_visualizer.application.runtime_sessions import RuntimeSessionRegistry
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.drakon import Assignment, Call, If, Output, Sequence
from code_visualizer.domain.freeform import FreeformDiagram, Rect, ShapeObject
from code_visualizer.domain.invocation_arguments import parse_invocation_arguments
from code_visualizer.domain.mindmap import MindMapDiagram, find_topic, walk_topics
from code_visualizer.domain.program import (
    ProgramAssignment,
    ProgramCall,
    ProgramIf,
    ProgramSymbolKind,
)
from code_visualizer.domain.program_signatures import ParameterSpec
from code_visualizer.domain.projection import ProjectionViewTarget
from code_visualizer.domain.semantic import (
    ProjectionKind,
    SemanticObjectKind,
    SemanticRelationKind,
)
from code_visualizer.execution import (
    DebugEvent,
    DebugState,
    RuntimeBinding,
    RuntimeChild,
    RuntimeGraph,
    RuntimeValue,
    RuntimeValueKind,
)
from code_visualizer.generation import generate_python, generate_python_project
from code_visualizer.persistence import ProjectStore


def test_program_model_is_truth_for_first_typed_construct_family_and_undo() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(
            session.client.insert_drakon_atom(
                diagram.id,
                "assignment",
                0,
                target="answer",
                value="40 + 2",
            ),
            CommandAccepted,
        )
        snapshot = session.authority.snapshot()
        assignment_id = snapshot.documents[0].body.atoms[0].id
        function = function_for_document(snapshot, diagram.id)
        assert function is not None
        assignment = function.body.statements[0]
        assert isinstance(assignment, ProgramAssignment)
        assert assignment.value.source == "40 + 2"
        original_value = assignment.value

        drakon = snapshot.documents[0]
        stale_assignment = replace(drakon.body.atoms[0], value="999")
        stale_drakon = replace(drakon, body=replace(drakon.body, atoms=(stale_assignment,)))
        stale_project = replace(snapshot, documents=(stale_drakon,))
        source = generate_python(stale_project).source
        assert "answer = 40 + 2" in source
        assert "answer = 999" not in source
        repaired = canonicalize_project(stale_project).documents[0]
        assert repaired.body.atoms[0].value == "40 + 2"

        changed = session.client.set_drakon_text(
            diagram.id,
            assignment_id,
            "value",
            "6 * 7",
        )
        assert isinstance(changed, CommandAccepted)
        changed_function = function_for_document(session.authority.snapshot(), diagram.id)
        assert changed_function is not None
        changed_assignment = changed_function.body.statements[0]
        assert isinstance(changed_assignment, ProgramAssignment)
        assert changed_assignment.value.source == "6 * 7"
        assert "answer = 6 * 7" in generate_python(session.authority.snapshot()).source

        assert isinstance(session.client.undo(), CommandAccepted)
        restored_function = function_for_document(session.authority.snapshot(), diagram.id)
        assert restored_function is not None
        restored_assignment = restored_function.body.statements[0]
        assert isinstance(restored_assignment, ProgramAssignment)
        assert restored_assignment.value.source == "40 + 2"
        assert restored_assignment.value == original_value
    finally:
        session.close()


def test_unrelated_drakon_edit_preserves_unchanged_canonical_expression_trees() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        replacement = replace(
            diagram,
            body=replace(
                diagram.body,
                atoms=(
                    Assignment("assignment_stable", "result", "6 * 7"),
                    Output("output_changed", 'f"answer={result}"'),
                ),
            ),
        )
        assert isinstance(
            session.client.submit(ReplaceDiagramSnapshot(replacement)),
            CommandAccepted,
        )
        before = function_for_document(session.authority.snapshot(), diagram.id)
        assert before is not None
        assignment_before = before.body.statements[0]
        assert isinstance(assignment_before, ProgramAssignment)

        assert isinstance(
            session.client.set_drakon_text(
                diagram.id,
                "output_changed",
                "expression",
                'f"updated={result}"',
            ),
            CommandAccepted,
        )
        after = function_for_document(session.authority.snapshot(), diagram.id)
        assert after is not None
        assignment_after = after.body.statements[0]

        assert assignment_after == assignment_before
        assert assignment_after.target.tree is assignment_before.target.tree
        assert assignment_after.value.tree is assignment_before.value.tree
    finally:
        session.close()


def test_migrated_drakon_commands_bypass_wholesale_promotion(monkeypatch) -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(
            session.client.insert_drakon_atom(diagram.id, "if", 0),
            CommandAccepted,
        )
        decision = session.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(decision, If)

        def fail_bridge(*_args, **_kwargs):
            raise AssertionError("migrated command reached the promotion bridge")

        monkeypatch.setattr(
            "code_visualizer.application.drakon_program_adapter.promote_program_from_drakon",
            fail_bridge,
        )
        monkeypatch.setattr(
            "code_visualizer.application.program_model.promote_program_from_drakon",
            fail_bridge,
        )

        assert isinstance(
            session.client.insert_drakon_atom(
                diagram.id,
                "assignment",
                1,
                target="answer",
                value="40 + 2",
            ),
            CommandAccepted,
        )
        assignment = session.authority.snapshot().documents[0].body.atoms[1]
        assert isinstance(assignment, Assignment)
        assert isinstance(
            session.client.set_drakon_text(
                diagram.id,
                assignment.id,
                "value",
                "6 * 7",
            ),
            CommandAccepted,
        )
        assert isinstance(
            session.client.set_drakon_text(
                diagram.id,
                decision.id,
                "condition",
                "answer > 0",
            ),
            CommandAccepted,
        )
        assert isinstance(
            session.client.remove_drakon_block(
                diagram.id,
                session.authority.snapshot().documents[0].body.id,
                (assignment.id,),
            ),
            CommandAccepted,
        )
    finally:
        session.close()


def test_sequence_assignment_call_if_and_expressions_promote_end_to_end() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        nested = If(
            "if_positive",
            "answer > 0",
            Sequence(
                "sequence_positive",
                (Call("call_print", "print(answer)"),),
            ),
            Sequence(
                "sequence_nonpositive",
                (Assignment("assignment_fallback", "answer", "0"),),
            ),
        )
        replacement = replace(
            diagram,
            header=replace(
                diagram.header,
                function=replace(
                    diagram.header.function,
                    parameters=(ParameterSpec("answer", annotation="int"),),
                    return_annotation="None",
                ),
            ),
            body=replace(
                diagram.body,
                atoms=(Assignment("assignment_seed", "answer", "answer + 1"), nested),
            ),
        )
        result = session.client.submit(ReplaceDiagramSnapshot(replacement))
        assert isinstance(result, CommandAccepted)
        function = function_for_document(session.authority.snapshot(), diagram.id)
        assert function is not None
        assert function.parameters[0].annotation is not None
        assert function.parameters[0].annotation.source == "int"
        assert function.return_annotation is not None
        assert function.return_annotation.source == "None"
        assert isinstance(function.body.statements[0], ProgramAssignment)
        decision = function.body.statements[1]
        assert isinstance(decision, ProgramIf)
        assert decision.condition.source == "answer > 0"
        assert isinstance(decision.true_branch.statements[0], ProgramCall)
        assert isinstance(decision.false_branch.statements[0], ProgramAssignment)
        entrypoint = session.authority.snapshot().program_model.entrypoint
        configured = session.client.configure_entrypoint(
            replace(entrypoint, arguments=parse_invocation_arguments("41"))
        )
        assert isinstance(configured, CommandAccepted)
        for item in generate_python_project(session.authority.snapshot()).files:
            compile(item.source, item.path, "exec")
    finally:
        session.close()


def test_symbol_and_parameter_identities_survive_renames() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        initial_spec = replace(
            diagram.header.function,
            identifier="greet",
            parameters=(ParameterSpec("name", annotation="str"),),
        )
        assert isinstance(
            session.client.replace_function_spec(diagram.id, initial_spec),
            CommandAccepted,
        )
        before = function_for_document(session.authority.snapshot(), diagram.id)
        assert before is not None
        function_symbol_id = before.symbol_id
        parameter_id = before.parameters[0].id
        parameter_symbol_id = before.parameters[0].symbol_id

        renamed_spec = replace(
            initial_spec,
            identifier="welcome",
            parameters=(ParameterSpec("person", annotation="str"),),
        )
        assert isinstance(
            session.client.replace_function_spec(diagram.id, renamed_spec),
            CommandAccepted,
        )
        after = function_for_document(session.authority.snapshot(), diagram.id)
        assert after is not None
        assert after.symbol_id == function_symbol_id
        assert after.parameters[0].id == parameter_id
        assert after.parameters[0].symbol_id == parameter_symbol_id
        symbol = session.authority.snapshot().program_model.symbol(parameter_symbol_id)
        assert symbol is not None
        assert symbol.kind is ProgramSymbolKind.PARAMETER
        assert symbol.name == "person"
        semantic_symbol = session.kernel.queries.semantic_object(parameter_symbol_id)
        assert semantic_symbol is not None
        assert semantic_symbol.label == "person"
        semantic_function_symbol = session.kernel.queries.semantic_object(function_symbol_id)
        assert semantic_function_symbol is not None
        assert semantic_function_symbol.label == "welcome"

        assert isinstance(
            session.client.insert_drakon_atom(
                diagram.id,
                "assignment",
                0,
                target="local_value",
                value="1",
            ),
            CommandAccepted,
        )
        snapshot = session.authority.snapshot()
        local_before = next(
            item
            for item in snapshot.program_model.symbols
            if item.kind is ProgramSymbolKind.LOCAL and item.name == "local_value"
        )
        assignment_id = snapshot.documents[0].body.atoms[0].id
        assert isinstance(
            session.client.set_drakon_text(
                diagram.id,
                assignment_id,
                "target",
                "renamed_value",
            ),
            CommandAccepted,
        )
        local_after = next(
            item
            for item in session.authority.snapshot().program_model.symbols
            if item.kind is ProgramSymbolKind.LOCAL
        )
        assert local_after.id == local_before.id
        assert local_after.name == "renamed_value"
    finally:
        session.close()


def test_live_view_labels_follow_rename_until_deliberately_overridden() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        definition = builtin_projection_definition(
            ProjectionKind.ARCHITECTURE,
            session.kernel.queries.program,
        )
        result = session.client.materialize_projection(
            definition,
            ProjectionViewTarget.MIND_MAP,
            "Live architecture",
            document_id="diagram_live_architecture",
        )
        assert isinstance(result, CommandAccepted)
        persisted = session.authority.snapshot().documents[-1]
        assert isinstance(persisted, MindMapDiagram)
        assert persisted.live_projection == definition

        renamed = replace(diagram.header.function, identifier="greet")
        assert isinstance(
            session.client.replace_function_spec(diagram.id, renamed),
            CommandAccepted,
        )
        resolved = session.kernel.queries.resolved_document(persisted.id)
        assert isinstance(resolved, MindMapDiagram)
        topic = next(item for item in walk_topics(resolved.root) if item.semantic_id == diagram.id)
        assert topic.text == "greet"
        glyph = session.kernel.queries.semantic_object(f"glyph:mindmap:{persisted.id}:{topic.id}")
        assert glyph is not None
        assert glyph.label == "greet"

        # Presentation-only edits must not accidentally freeze a derived label.
        assert isinstance(
            session.client.update_mindmap_topic(
                resolved.id,
                topic.id,
                topic.text,
                notes=topic.notes,
                collapsed=not topic.collapsed,
                links=topic.links,
                attachments=topic.attachments,
                update_label=False,
            ),
            CommandAccepted,
        )
        renamed = replace(renamed, identifier="salute")
        assert isinstance(
            session.client.replace_function_spec(diagram.id, renamed),
            CommandAccepted,
        )
        resolved = session.kernel.queries.resolved_document(persisted.id)
        assert isinstance(resolved, MindMapDiagram)
        topic = find_topic(resolved.root, topic.id)
        assert topic is not None
        assert topic.text == "salute"
        assert topic.label_override is None

        assert isinstance(
            session.client.update_mindmap_topic(
                resolved.id,
                topic.id,
                "Public entry point",
                notes=topic.notes,
                collapsed=topic.collapsed,
                links=topic.links,
                attachments=topic.attachments,
            ),
            CommandAccepted,
        )
        assert isinstance(
            session.client.replace_function_spec(
                diagram.id,
                replace(renamed, identifier="welcome"),
            ),
            CommandAccepted,
        )
        overridden = session.kernel.queries.resolved_document(persisted.id)
        assert isinstance(overridden, MindMapDiagram)
        topic = find_topic(overridden.root, topic.id)
        assert topic is not None
        assert topic.text == "Public entry point"
        assert topic.label_override == "Public entry point"
        glyph = session.kernel.queries.semantic_object(f"glyph:mindmap:{persisted.id}:{topic.id}")
        assert glyph is not None
        assert glyph.label == "Public entry point"

        assert isinstance(
            session.client.update_mindmap_topic(
                overridden.id,
                topic.id,
                topic.text,
                notes=topic.notes,
                collapsed=topic.collapsed,
                links=topic.links,
                attachments=topic.attachments,
                derive_label=True,
            ),
            CommandAccepted,
        )
        following = session.kernel.queries.resolved_document(persisted.id)
        assert isinstance(following, MindMapDiagram)
        topic = find_topic(following.root, topic.id)
        assert topic is not None
        assert topic.text == "welcome"
        assert topic.label_override is None
    finally:
        session.close()


def test_live_freeform_keeps_layout_but_not_copied_semantic_text() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        definition = builtin_projection_definition(
            ProjectionKind.ARCHITECTURE,
            session.kernel.queries.program,
        )
        assert isinstance(
            session.client.materialize_projection(
                definition,
                ProjectionViewTarget.FREEFORM,
                "Live architecture canvas",
                document_id="diagram_live_canvas",
            ),
            CommandAccepted,
        )
        canvas = session.kernel.queries.resolved_document("diagram_live_canvas")
        assert isinstance(canvas, FreeformDiagram)
        shape = next(
            item
            for item in canvas.objects
            if isinstance(item, ShapeObject) and item.semantic_id == diagram.id
        )
        authored_bounds = Rect(777.0, 333.0, 260.0, 88.0)
        assert isinstance(
            session.client.transform_freeform_object(
                canvas.id,
                shape.id,
                authored_bounds,
                rotation=4.0,
            ),
            CommandAccepted,
        )
        renamed = replace(diagram.header.function, identifier="calculate")
        assert isinstance(
            session.client.replace_function_spec(diagram.id, renamed),
            CommandAccepted,
        )
        canvas = session.kernel.queries.resolved_document(canvas.id)
        assert isinstance(canvas, FreeformDiagram)
        shape = next(item for item in canvas.objects if item.id == shape.id)
        assert isinstance(shape, ShapeObject)
        assert shape.text == "calculate"
        assert shape.bounds == authored_bounds
        assert shape.rotation == 4.0

        assert isinstance(
            session.client.transform_freeform_object(
                canvas.id,
                shape.id,
                shape.bounds,
                rotation=shape.rotation,
                text="Stable public API",
            ),
            CommandAccepted,
        )
        assert isinstance(
            session.client.replace_function_spec(
                diagram.id,
                replace(renamed, identifier="compute"),
            ),
            CommandAccepted,
        )
        canvas = session.kernel.queries.resolved_document(canvas.id)
        assert isinstance(canvas, FreeformDiagram)
        shape = next(item for item in canvas.objects if item.id == shape.id)
        assert isinstance(shape, ShapeObject)
        assert shape.text == "Stable public API"
        assert shape.label_override == "Stable public API"

        assert isinstance(
            session.client.transform_freeform_object(
                canvas.id,
                shape.id,
                shape.bounds,
                rotation=shape.rotation,
                derive_label=True,
            ),
            CommandAccepted,
        )
        canvas = session.kernel.queries.resolved_document(canvas.id)
        assert isinstance(canvas, FreeformDiagram)
        shape = next(item for item in canvas.objects if item.id == shape.id)
        assert isinstance(shape, ShapeObject)
        assert shape.text == "compute"
        assert shape.label_override is None
    finally:
        session.close()


def _dijkstra_runtime_graph(revision: int, sequence: int) -> RuntimeGraph:
    return RuntimeGraph(
        "execution_dijkstra",
        revision,
        revision,
        sequence,
        "frame_dijkstra",
        (RuntimeBinding("frontier", "frontier_heap", True),),
        (
            RuntimeValue(
                "frontier_heap",
                "builtins.list",
                RuntimeValueKind.SEQUENCE,
                "[(2, 'B'), (5, 'C'), (3, 'D')]",
                children=(
                    RuntimeChild("0", "frontier_0"),
                    RuntimeChild("1", "frontier_1"),
                    RuntimeChild("2", "frontier_2"),
                ),
            ),
            RuntimeValue(
                "frontier_0",
                "builtins.tuple",
                RuntimeValueKind.SCALAR,
                "(2, 'B')",
            ),
            RuntimeValue(
                "frontier_1",
                "builtins.tuple",
                RuntimeValueKind.SCALAR,
                "(5, 'C')",
            ),
            RuntimeValue(
                "frontier_2",
                "builtins.tuple",
                RuntimeValueKind.SCALAR,
                "(3, 'D')",
            ),
        ),
        history_index=sequence,
        checkpoint=True,
    )


def test_dijkstra_runtime_overlay_compression_and_rewind_reference_path() -> None:
    root = Path(__file__).resolve().parents[1] / "examples" / "projects" / "15-dijkstra"
    project = ProjectStore(root).recover(promote=False)
    session = ProjectSession.open(root, read_only=True)
    try:
        queries = session.kernel.queries
        dijkstra = next(
            item
            for item in queries.program.objects
            if item.kind is SemanticObjectKind.FUNCTION and item.label == "dijkstra"
        )
        control = queries.projection(ProjectionKind.CONTROL, dijkstra.id)
        control_nodes = {item.id: item for item in control.nodes}
        drakon = queries.projection(ProjectionKind.DRAKON, dijkstra.document_id)
        drakon_semantic_ids = {item.semantic_id for item in drakon.nodes}
        active_edge = next(
            edge
            for edge in control.edges
            if edge.kind is SemanticRelationKind.CONTROL_FLOW
            and edge.source_id in control_nodes
            and edge.target_id in control_nodes
            and control_nodes[edge.source_id].semantic_id in drakon_semantic_ids
            and control_nodes[edge.target_id].semantic_id in drakon_semantic_ids
        )
        previous_semantic = control_nodes[active_edge.source_id].semantic_id
        active_semantic = control_nodes[active_edge.target_id].semantic_id

        registry = RuntimeSessionRegistry()
        previous = registry.record(
            DebugEvent(
                1,
                "paused",
                DebugState.PAUSED,
                execution_session_id="execution_dijkstra",
                project_revision=project.revision,
                artifact_revision=project.revision,
                runtime_graph=_dijkstra_runtime_graph(project.revision, 1),
            ),
            semantic_id=previous_semantic,
        )
        current = registry.record(
            DebugEvent(
                2,
                "paused",
                DebugState.PAUSED,
                execution_session_id="execution_dijkstra",
                project_revision=project.revision,
                artifact_revision=project.revision,
                runtime_graph=_dijkstra_runtime_graph(project.revision, 2),
            ),
            semantic_id=active_semantic,
        )
        context = RuntimeOverlayContext(
            current,
            previous,
            RuntimeAdapterKind.HEAP,
            "frontier",
        )
        overlaid_control = overlay_runtime_context(control, context)
        assert any(
            node.semantic_id == active_semantic and "active" in node.badges
            for node in overlaid_control.nodes
        )
        assert any(edge.active for edge in overlaid_control.edges)
        overlaid_drakon = overlay_runtime_context(drakon, context)
        assert any(
            node.semantic_id == active_semantic and "active" in node.badges
            for node in overlaid_drakon.nodes
        )
        assert any(edge.active for edge in overlaid_drakon.edges)

        data_definition = builtin_projection_definition(
            ProjectionKind.DATA,
            queries.program,
            dijkstra.id,
        )
        data = compile_projection(
            queries.program,
            data_definition,
            kind=ProjectionKind.DATA,
        )
        assert len(data.nodes) <= 50
        assert any(node.id.startswith("projection-summary:") for node in data.nodes)
        assert any(node.expandable for node in data.nodes)
        assert len(queries.program.objects) > 198
        overlaid_data = overlay_runtime_context(data, context)
        assert any(
            node.kind is SemanticObjectKind.SYMBOL
            and node.label == "frontier"
            and "changed" in node.badges
            for node in overlaid_data.nodes
        )
        assert any(edge.id.startswith("runtime-edge:heap:") for edge in overlaid_data.edges)

        rewound = overlay_runtime_context(
            control,
            RuntimeOverlayContext(previous, adapter=RuntimeAdapterKind.HEAP),
        )
        assert any(
            node.semantic_id == previous_semantic and "active" in node.badges
            for node in rewound.nodes
        )
    finally:
        session.close()


def test_every_palette_construct_edits_and_replays_without_document_promotion(monkeypatch) -> None:
    from code_visualizer.domain.drakon_defaults import supported_atom_kinds

    session = ProjectSession.new()
    try:

        def fail_import(*_args, **_kwargs):
            raise AssertionError("A live DRAKON gesture attempted document import")

        monkeypatch.setattr(
            "code_visualizer.application.drakon_program_adapter.promote_program_from_drakon",
            fail_import,
        )
        monkeypatch.setattr(
            "code_visualizer.application.program_model.promote_program_from_drakon",
            fail_import,
        )
        diagram_id = session.authority.snapshot().documents[0].id
        for kind in sorted(supported_atom_kinds()):
            before = session.authority.snapshot().program_model
            result = session.client.insert_drakon_atom(diagram_id, kind, 0)
            assert isinstance(result, CommandAccepted), (kind, result)
            inserted = session.authority.snapshot().program_model
            assert len(inserted.functions[0].body.statements) == 1
            assert result.affected_ids[0] == inserted.functions[0].body.statements[0].id, kind
            assert isinstance(session.client.undo(), CommandAccepted), kind
            assert session.authority.snapshot().program_model == before, kind
            assert isinstance(session.client.redo(), CommandAccepted), kind
            assert session.authority.snapshot().program_model == inserted, kind
            atom = session.authority.snapshot().documents[0].body.atoms[0]
            if kind != "output":
                assert isinstance(
                    session.client.replace_drakon_atom(diagram_id, atom), CommandAccepted
                ), kind
                assert session.authority.snapshot().program_model == inserted, kind
                assert isinstance(session.client.undo(), CommandAccepted), kind
            assert isinstance(session.client.undo(), CommandAccepted), kind
    finally:
        session.close()


def test_structured_gestures_and_signatures_use_canonical_commands(monkeypatch) -> None:
    from code_visualizer.domain.drakon import Loop

    session = ProjectSession.new()
    try:

        def fail_import(*_args, **_kwargs):
            raise AssertionError("A live DRAKON gesture attempted document import")

        monkeypatch.setattr(
            "code_visualizer.application.drakon_program_adapter.promote_program_from_drakon",
            fail_import,
        )
        diagram = session.authority.snapshot().documents[0]
        assert isinstance(
            session.client.insert_drakon_atom(diagram.id, "for_loop", 0), CommandAccepted
        )
        loop = session.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(loop, Loop)
        assert isinstance(
            session.client.set_drakon_text(diagram.id, loop.id, "iterable", "range(7)"),
            CommandAccepted,
        )
        assert isinstance(
            session.client.replace_drakon_atom(diagram.id, replace(loop, iterable="range(8)")),
            CommandAccepted,
        )
        assert isinstance(
            session.client.insert_drakon_atom(diagram.id, "output", 1), CommandAccepted
        )
        before_move = session.authority.snapshot().program_model
        assert isinstance(
            session.client.move_drakon_block(
                diagram.id, diagram.body.id, (loop.id,), diagram.body.id, 2
            ),
            CommandAccepted,
        )
        assert (
            session.authority.snapshot().program_model.functions[0].body.statements[-1].id
            == loop.id
        )
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == before_move
        assert isinstance(session.client.undo(), CommandAccepted)
        before_wrap = session.authority.snapshot().program_model
        assert isinstance(
            session.client.wrap_drakon_block(diagram.id, diagram.body.id, (loop.id,), "try"),
            CommandAccepted,
        )
        wrapper = session.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model == before_wrap
        assert isinstance(session.client.redo(), CommandAccepted)
        assert isinstance(
            session.client.unwrap_drakon_atom(diagram.id, wrapper.id, discard_other_bodies=True),
            CommandAccepted,
        )
        assert session.authority.snapshot().program_model == before_wrap
        assert isinstance(
            session.client.replace_function_spec(
                diagram.id,
                replace(
                    diagram.header.function,
                    parameters=(ParameterSpec("count", annotation="int", default="7"),),
                ),
            ),
            CommandAccepted,
        )
        function = session.authority.snapshot().program_model.functions[0]
        assert function.parameters[0].name == "count"
        assert isinstance(
            session.client.set_drakon_text(
                diagram.id, diagram.header.id, "identifier", "run_count"
            ),
            CommandAccepted,
        )
        assert session.authority.snapshot().program_model.functions[0].identifier == "run_count"
        assert isinstance(
            session.client.remove_drakon_block(diagram.id, diagram.body.id, (loop.id,)),
            CommandAccepted,
        )
        assert not session.authority.snapshot().program_model.functions[0].body.statements
        assert isinstance(session.client.undo(), CommandAccepted)
        assert session.authority.snapshot().program_model.functions[0].body.statements
    finally:
        session.close()


def test_structured_expression_gestures_never_reconvert_statement_subtrees(monkeypatch) -> None:
    from code_visualizer.domain.drakon import Loop, Transfer, Try, With

    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        for index, kind in enumerate(("for_loop", "try", "with", "return")):
            assert isinstance(
                session.client.insert_drakon_atom(diagram.id, kind, index), CommandAccepted
            )
        loop, exception_block, context_block, transfer = (
            session.authority.snapshot().documents[0].body.atoms
        )
        assert isinstance(loop, Loop)
        assert isinstance(exception_block, Try)
        assert isinstance(context_block, With)
        assert isinstance(transfer, Transfer)

        def fail_conversion(*_args, **_kwargs):
            raise AssertionError("An expression gesture reconverted a statement subtree")

        monkeypatch.setattr(
            "code_visualizer.application.drakon_program_adapter.program_statement_from_drakon",
            fail_conversion,
        )
        for atom_id, field, value in (
            (loop.id, "iterable", "range(7)"),
            (loop.id, "condition", "True"),
            (transfer.id, "expression", "42"),
            (exception_block.body.atoms[0].id, "source", "try_result = 5"),
            (context_block.body.atoms[0].id, "source", "with_result = 42"),
        ):
            before = session.authority.snapshot().program_model
            assert isinstance(
                session.client.set_drakon_text(diagram.id, atom_id, field, value), CommandAccepted
            )
            assert isinstance(session.client.undo(), CommandAccepted)
            assert session.authority.snapshot().program_model == before
            assert isinstance(session.client.redo(), CommandAccepted)
        symbols = {item.name for item in session.authority.snapshot().program_model.symbols}
        assert {"try_result", "with_result"} <= symbols
    finally:
        session.close()
