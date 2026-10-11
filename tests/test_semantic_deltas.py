from __future__ import annotations

from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.project_factory import (
    create_default_project,
    initialize_project_documents,
)
from code_visualizer.application.projection_language import builtin_projection_definition
from code_visualizer.application.semantic_index import (
    build_semantic_program,
    update_semantic_program,
)
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    DrakonDiagram,
    If,
    Sequence,
    create_empty_drakon,
)
from code_visualizer.domain.mindmap import MindMapDiagram, walk_topics
from code_visualizer.domain.program import ProgramAssignment, ProgramSymbolKind
from code_visualizer.domain.projection import ProjectionViewTarget
from code_visualizer.domain.semantic import ProjectionKind, SemanticObjectKind
from code_visualizer.generation import generate_python_project
from code_visualizer.sdk import CodeVisualizerClient


def test_kernel_publishes_identity_keyed_semantic_delta_and_reuses_new_read_model() -> None:
    session = ProjectSession.new()
    events = []
    unsubscribe = session.kernel.subscribe(events.append)
    try:
        initial_queries = session.kernel.queries
        project = session.authority.snapshot()
        function = project.program_model.functions[0]
        result = session.client.insert_program_statement(
            function.id,
            function.body.id,
            0,
            "assignment",
            statement_id="delta_assignment",
            target="answer",
            value="40 + 2",
            true_sequence_id="unused_true",
            false_sequence_id="unused_false",
        )
        assert isinstance(result, CommandAccepted)
        assert events
        delta = events[0].semantic_delta
        assert delta is not None
        assert delta.from_revision == 0
        assert delta.to_revision == 1
        assert "delta_assignment" in {item.id for item in delta.added_objects}
        assert "expression:delta_assignment:value" in {item.id for item in delta.added_objects}
        assert session.kernel.queries is not initial_queries
        assert all(item.semantic_delta == delta for item in events)
    finally:
        unsubscribe()
        session.close()


def test_migrated_expression_indexing_does_not_reparse_drakon_text(monkeypatch) -> None:
    session = ProjectSession.new()
    try:
        project = session.authority.snapshot()
        function = project.program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="typed_expression_assignment",
                target="result",
                value="left + right",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        canonical = session.authority.snapshot()

        def fail_parse(*_args, **_kwargs):
            raise AssertionError("migrated ProgramExpression was reparsed")

        monkeypatch.setattr("code_visualizer.application.semantic_index.ast.parse", fail_parse)
        semantic = build_semantic_program(canonical)
        assignment = next(
            item for item in semantic.objects if item.id == "typed_expression_assignment"
        )
        assert assignment.kind is SemanticObjectKind.OPERATION
        assert {
            item.label for item in semantic.objects if item.kind is SemanticObjectKind.SYMBOL
        } >= {
            "result",
            "left",
            "right",
        }
    finally:
        session.close()


def test_incremental_function_segment_matches_full_rebuild_oracle() -> None:
    session = ProjectSession.new()
    try:
        before = session.authority.snapshot()
        before_program = build_semantic_program(before)
        function = before.program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="incremental_assignment",
                target="distance",
                value="current + weight",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        after = session.authority.snapshot()

        update = update_semantic_program(
            before,
            before_program,
            after,
            verify_with_full_rebuild=True,
        )

        assert not update.used_full_rebuild
        assert update.reindexed_function_ids == frozenset({function.id})
        assert update.program == session.kernel.queries.program
    finally:
        session.close()


def test_live_view_consumes_semantic_delta_without_widening_local_invalidation() -> None:
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
                ProjectionViewTarget.MIND_MAP,
                "Live architecture",
                document_id="live_architecture_delta",
            ),
            CommandAccepted,
        )
        before = session.authority.snapshot()
        before_program = build_semantic_program(before)

        function = before.program_model.functions[0]
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="local_live_delta_assignment",
                target="answer",
                value="42",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        local_after = session.authority.snapshot()
        local_update = update_semantic_program(
            before,
            before_program,
            local_after,
            verify_with_full_rebuild=True,
        )
        assert not local_update.used_full_rebuild
        assert local_update.reindexed_function_ids == frozenset({function.id})
        assert local_update.reindexed_document_ids == frozenset({diagram.id})

        current_diagram = next(item for item in local_after.documents if item.id == diagram.id)
        assert isinstance(current_diagram, DrakonDiagram)
        renamed_spec = replace(current_diagram.header.function, identifier="renamed_live_delta")
        assert isinstance(
            session.client.replace_function_spec(diagram.id, renamed_spec),
            CommandAccepted,
        )
        renamed_after = session.authority.snapshot()
        rename_update = update_semantic_program(
            local_after,
            local_update.program,
            renamed_after,
            verify_with_full_rebuild=True,
        )
        assert not rename_update.used_full_rebuild
        assert rename_update.reindexed_function_ids == frozenset({function.id})
        assert rename_update.reindexed_document_ids == frozenset(
            {diagram.id, "live_architecture_delta"}
        )
        live_document = next(
            item for item in renamed_after.documents if item.id == "live_architecture_delta"
        )
        assert isinstance(live_document, MindMapDiagram)
        live_topic = next(
            item for item in walk_topics(live_document.root) if item.semantic_id == function.id
        )
        live_glyph = next(
            item
            for item in rename_update.program.objects
            if item.id == f"glyph:mindmap:{live_document.id}:{live_topic.id}"
        )
        assert live_glyph.label == "renamed_live_delta"
    finally:
        session.close()


def test_transitional_drakon_edit_preserves_order_and_stays_incremental() -> None:
    diagrams = tuple(
        replace(
            create_empty_drakon(
                identifier=f"function_{index}",
                title=f"Function {index}",
                diagram_id=f"diagram_{index}",
            ),
            body=Sequence(
                f"sequence_{index}",
                (Action(f"action_{index}", f"value_{index} = 1"),),
            ),
        )
        for index in range(3)
    )
    base = create_default_project(title="Stable ordering")
    project = initialize_project_documents(
        replace(
            base,
            program_model=replace(
                base.program_model,
                entrypoint=replace(base.program_model.entrypoint, callable_id=diagrams[0].id),
            ),
        ),
        diagrams,
    )
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="ordering-test")
    try:
        before = authority.snapshot()
        before_program = build_semantic_program(before)
        before_source = generate_python_project(before).file("app/main.py").source
        function_order = tuple(item.id for item in before.program_model.functions)
        symbol_order = tuple(item.id for item in before.program_model.symbols)
        view_order = tuple(item.document_id for item in before.drakon_views)
        document_order = tuple(item.id for item in before.documents)

        result = client.set_drakon_text(
            diagrams[0].id,
            "action_0",
            "source",
            "value_0 = 2",
        )
        assert isinstance(result, CommandAccepted)
        after = authority.snapshot()
        after_source = generate_python_project(after).file("app/main.py").source
        update = update_semantic_program(
            before,
            before_program,
            after,
            verify_with_full_rebuild=True,
        )

        assert tuple(item.id for item in after.program_model.functions) == function_order
        assert tuple(item.id for item in after.program_model.symbols) == symbol_order
        assert tuple(item.document_id for item in after.drakon_views) == view_order
        assert tuple(item.id for item in after.documents) == document_order
        assert after_source == before_source.replace("value_0 = 1", "value_0 = 2")
        assert not update.used_full_rebuild
        assert update.reindexed_function_ids == frozenset({diagrams[0].id})
        assert update.reindexed_document_ids == frozenset({diagrams[0].id})
    finally:
        client.close()


@given(
    mutations=st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=5),
            st.integers(min_value=0, max_value=3),
            st.integers(min_value=-20, max_value=100),
        ),
        min_size=1,
        max_size=12,
    )
)
@settings(max_examples=30, deadline=None)
def test_randomized_local_mutations_match_full_semantic_oracle(
    mutations: list[tuple[int, int, int]],
) -> None:
    diagrams = tuple(
        replace(
            create_empty_drakon(
                identifier=f"oracle_{index}",
                title=f"Oracle {index}",
                diagram_id=f"oracle_diagram_{index}",
            ),
            body=Sequence(
                f"oracle_sequence_{index}",
                (
                    Action(f"oracle_action_{index}", f"scratch_{index} = 0"),
                    Assignment(
                        f"oracle_assignment_{index}",
                        f"value_{index}",
                        str(index),
                    ),
                    Call(
                        f"oracle_call_{index}",
                        "print",
                        arguments=f"value_{index}",
                    ),
                    If(
                        f"oracle_if_{index}",
                        f"value_{index} >= 0",
                        Sequence(f"oracle_true_{index}"),
                        Sequence(f"oracle_false_{index}"),
                    ),
                ),
            ),
        )
        for index in range(4)
    )
    base = create_default_project(title="Randomized semantic oracle")
    project = initialize_project_documents(
        replace(
            base,
            program_model=replace(
                base.program_model,
                entrypoint=replace(base.program_model.entrypoint, callable_id=diagrams[0].id),
            ),
        ),
        diagrams,
    )
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="randomized-oracle")
    try:
        previous = authority.snapshot()
        previous_program = build_semantic_program(previous)
        for step, (mutation_kind, function_index, value) in enumerate(mutations):
            diagram_id = diagrams[function_index].id
            function = previous.program_model.function(diagram_id)
            assert function is not None
            if mutation_kind == 0:
                result = client.set_drakon_text(
                    diagram_id,
                    f"oracle_action_{function_index}",
                    "source",
                    f"scratch_{function_index} = ({value}, {step})",
                )
            elif mutation_kind == 1:
                result = client.set_drakon_text(
                    diagram_id,
                    f"oracle_assignment_{function_index}",
                    "value",
                    f"({value}) + {step + 1000}",
                )
            elif mutation_kind == 2:
                result = client.set_drakon_text(
                    diagram_id,
                    f"oracle_if_{function_index}",
                    "condition",
                    f"value_{function_index} >= ({value} + {step})",
                )
            elif mutation_kind == 3:
                result = client.set_drakon_text(
                    diagram_id,
                    f"oracle_call_{function_index}",
                    "arguments",
                    f"{value}, {step}",
                )
            elif mutation_kind == 4:
                result = client.insert_program_statement(
                    function.id,
                    function.body.id,
                    len(function.body.statements),
                    "assignment",
                    statement_id=f"oracle_insert_{step}",
                    target=f"inserted_{function_index}_{step}",
                    value=str(value),
                    true_sequence_id=f"oracle_unused_true_{step}",
                    false_sequence_id=f"oracle_unused_false_{step}",
                )
            else:
                assignment = next(
                    item
                    for item in function.body.statements
                    if item.id == f"oracle_assignment_{function_index}"
                )
                assert isinstance(assignment, ProgramAssignment)
                symbol = previous.program_model.symbol(assignment.written_symbol_ids[0])
                assert symbol is not None and symbol.kind is ProgramSymbolKind.LOCAL
                result = client.rename_program_symbol(
                    symbol.id,
                    f"value_{function_index}_at_{step}",
                )
            assert isinstance(result, CommandAccepted)

            current = authority.snapshot()
            update = update_semantic_program(
                previous,
                previous_program,
                current,
                verify_with_full_rebuild=True,
            )
            assert not update.used_full_rebuild
            assert update.reindexed_function_ids == frozenset({diagram_id})
            assert update.reindexed_document_ids == frozenset({diagram_id})
            previous = current
            previous_program = update.program
    finally:
        client.close()


def test_incremental_kernel_does_not_call_project_wide_query_builder(monkeypatch) -> None:
    session = ProjectSession.new()
    try:
        function = session.authority.snapshot().program_model.functions[0]

        def fail_full_build(*_args, **_kwargs):
            raise AssertionError("ordinary function edit used full query rebuild")

        monkeypatch.setattr(
            "code_visualizer.application.kernel.ProjectQueries.from_project",
            fail_full_build,
        )
        assert isinstance(
            session.client.insert_program_statement(
                function.id,
                function.body.id,
                0,
                "assignment",
                statement_id="incremental_kernel_assignment",
                target="answer",
                value="42",
                true_sequence_id="unused_true",
                false_sequence_id="unused_false",
            ),
            CommandAccepted,
        )
        assert session.kernel.queries.semantic_object("incremental_kernel_assignment") is not None
    finally:
        session.close()
