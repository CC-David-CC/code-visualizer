from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.session import ProjectSession
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.drakon import Assignment
from code_visualizer.domain.mindmap import MindMapDiagram
from code_visualizer.domain.semantic import (
    ProjectionKind,
    SemanticObjectKind,
    SemanticRelationKind,
)
from code_visualizer.persistence.decoding import project_from_data
from code_visualizer.persistence.serialization import project_to_data


def test_semantic_kernel_indexes_architecture_expressions_symbols_calls_and_control() -> None:
    session = ProjectSession.new()
    try:
        main = session.authority.snapshot().documents[0]
        inserted = session.client.insert_drakon_atom(
            main.id,
            "assignment",
            0,
            target="distances[node]",
            value="current_distance + weight",
        )
        assert isinstance(inserted, CommandAccepted)
        created = session.client.create_diagram(
            DocumentKind.DRAKON,
            "Relax helper",
            identifier="relax",
            module="graph.algorithms",
        )
        assert isinstance(created, CommandAccepted)
        call = session.client.insert_drakon_atom(main.id, "call", 1)
        assert isinstance(call, CommandAccepted)
        call_id = session.authority.snapshot().documents[0].body.atoms[1].id
        session.client.set_drakon_text(main.id, call_id, "expression", "relax")

        queries = session.kernel.queries
        program = queries.program
        assignment = session.authority.snapshot().documents[0].body.atoms[0]
        assert isinstance(assignment, Assignment)
        assert queries.semantic_object(assignment.id).kind is SemanticObjectKind.OPERATION
        expression = queries.semantic_object(f"expression:{assignment.id}:value")
        assert expression is not None
        assert expression.kind is SemanticObjectKind.EXPRESSION
        assert any(
            item.kind is SemanticRelationKind.WRITES
            and queries.semantic_object(item.target_id).label == "distances"
            for item in program.relations
            if item.source_id == assignment.id
        )
        reads = {
            queries.semantic_object(item.target_id).label
            for item in program.relations
            if item.source_id == assignment.id and item.kind is SemanticRelationKind.READS
        }
        assert {"node", "current_distance", "weight"} <= reads

        architecture = queries.projection(ProjectionKind.ARCHITECTURE)
        assert {item.kind for item in architecture.nodes} >= {
            SemanticObjectKind.PROJECT,
            SemanticObjectKind.NAMESPACE,
            SemanticObjectKind.MODULE,
            SemanticObjectKind.FUNCTION,
        }
        assert any(
            item.kind is SemanticRelationKind.CALLS and item.source_id == main.id
            for item in program.relations
        )
        control = queries.projection(ProjectionKind.CONTROL, main.id)
        assert assignment.id in {item.semantic_id for item in control.nodes}
        data = queries.projection(ProjectionKind.DATA, main.id)
        assert any(item.kind is SemanticObjectKind.SYMBOL for item in data.nodes)
    finally:
        session.close()


def test_view_anchors_are_commanded_undoable_serialized_and_shared_by_queries() -> None:
    session = ProjectSession.new()
    try:
        main = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(main.id, "output", 0, source='"hello"')
        operation_id = session.authority.snapshot().documents[0].body.atoms[0].id
        session.client.create_diagram(DocumentKind.MIND_MAP, "Concepts")
        mindmap = session.authority.snapshot().documents[-1]
        assert isinstance(mindmap, MindMapDiagram)

        anchored = session.client.set_view_anchor(
            mindmap.id,
            mindmap.root.id,
            semantic_id=operation_id,
        )
        assert isinstance(anchored, CommandAccepted)
        queries = session.kernel.queries
        assert queries.semantic_id_for_view_object(mindmap.id, mindmap.root.id) == operation_id
        views = queries.views_for(operation_id)
        mindmap_view = next(item for item in views if item.document_id == mindmap.id)
        assert mindmap_view.anchor_id == operation_id

        decoded = project_from_data(project_to_data(session.authority.snapshot()))
        decoded_mindmap = decoded.documents[-1]
        assert isinstance(decoded_mindmap, MindMapDiagram)
        assert decoded_mindmap.root.semantic_id == operation_id

        undone = session.client.undo()
        assert isinstance(undone, CommandAccepted)
        restored = session.authority.snapshot().documents[-1]
        assert isinstance(restored, MindMapDiagram)
        assert restored.root.semantic_id is None

        rejected = session.client.set_view_anchor(
            restored.id,
            restored.root.id,
            semantic_id="semantic_missing",
        )
        assert isinstance(rejected, CommandRejected)
        assert rejected.code == "SEMANTIC_OBJECT_NOT_FOUND"
    finally:
        session.close()


def test_selection_capabilities_and_rpc_queries_share_the_same_revision() -> None:
    session = ProjectSession.new()
    service = AutomationService(session.authority, kernel=session.kernel)
    context = AutomationContext(
        "agent",
        "connection-1",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.READ}),
    )
    observed = []
    unsubscribe = session.kernel.selection.subscribe(observed.append)
    try:
        main = session.authority.snapshot().documents[0]
        operations = service.dispatch("service.operations", {}, context)
        assert isinstance(operations, list)
        operation_ids = {item["id"] for item in operations}
        assert {
            "analysis.semantic",
            "analysis.dataflow",
            "execution.debugger",
            "execution.run",
            "export.svg",
            "layout.drakon",
            "python.generator",
            "view.runtime",
        } <= operation_ids
        scene = session.kernel.capabilities.invoke("layout.drakon", {"diagram_id": main.id})
        assert scene.nodes
        projection = service.dispatch(
            "query.projection",
            {"kind": "architecture"},
            context,
        )
        assert isinstance(projection, dict)
        assert projection["revision"] == session.authority.revision
        resolved = service.dispatch(
            "query.semantic_object",
            {"object_id": main.id},
            context,
        )
        assert isinstance(resolved, dict)
        assert resolved["kind"] == "function"

        service.dispatch(
            "service.presence",
            {"selection": [main.id]},
            context,
        )
        assert session.kernel.selection.state.primary == main.id
        assert session.kernel.selection.state.source == "automation:connection-1"
        assert observed[-1].semantic_ids == (main.id,)

        renamed = session.client.rename_project("Semantic revision")
        assert isinstance(renamed, CommandAccepted)
        assert session.kernel.queries.program.revision == renamed.revision
        assert session.kernel.selection.state.revision == renamed.revision
    finally:
        unsubscribe()
        service.close()
        session.close()
