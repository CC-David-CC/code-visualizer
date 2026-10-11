from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.session import ProjectSession
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.domain.authoring import AuthoredRelationKind
from code_visualizer.domain.freeform import ConnectorObject, FreeformDiagram, ShapeObject
from code_visualizer.domain.mindmap import MindMapDiagram, walk_topics
from code_visualizer.domain.projection import (
    ProjectionDecoration,
    ProjectionDefinition,
    ProjectionGrouping,
    ProjectionLabelStyle,
    ProjectionLayout,
    ProjectionViewTarget,
    TraversalDirection,
)
from code_visualizer.domain.semantic import (
    ProjectionKind,
    SemanticObjectKind,
    SemanticRelationKind,
)
from code_visualizer.persistence.decoding import project_from_data
from code_visualizer.persistence.serialization import project_to_data, projection_definition_to_data


def test_authored_concepts_relationships_and_lenses_share_one_revisioned_model() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        inserted = session.client.insert_drakon_atom(
            diagram.id,
            "assignment",
            0,
            target="answer",
            value="40 + 2",
        )
        assert isinstance(inserted, CommandAccepted)
        atom = session.authority.snapshot().documents[0].body.atoms[0]

        concept_result = session.client.create_semantic_concept(
            "Answer pipeline",
            (diagram.id, atom.id),
            description="The calculation and its entry point.",
            tags=("example", "intent"),
            concept_id="concept_answer_pipeline",
        )
        assert isinstance(concept_result, CommandAccepted)
        relation_result = session.client.create_authored_semantic_relation(
            diagram.id,
            atom.id,
            kind=AuthoredRelationKind.IMPLEMENTS,
            label="implements answer",
            description="An author-owned explanatory relationship.",
            relation_id="semantic_relation_answer",
        )
        assert isinstance(relation_result, CommandAccepted)

        definition = ProjectionDefinition(
            "projection_answer_pipeline",
            "Answer pipeline lens",
            scope_id="concept_answer_pipeline",
            object_kinds=(
                SemanticObjectKind.CONCEPT,
                SemanticObjectKind.FUNCTION,
                SemanticObjectKind.OPERATION,
            ),
            relation_kinds=(SemanticRelationKind.CONCEPTUALLY_CONTAINS,),
            direction=TraversalDirection.OUTGOING,
            max_depth=3,
            grouping=ProjectionGrouping.CONCEPT,
            decorations=(ProjectionDecoration.KIND, ProjectionDecoration.DETAIL),
            label_style=ProjectionLabelStyle.QUALIFIED,
            layout=ProjectionLayout.RADIAL,
        )
        put_lens = session.client.put_projection_definition(definition)
        assert isinstance(put_lens, CommandAccepted)

        projection = session.kernel.queries.saved_projection(definition.id)
        assert projection is not None
        assert projection.kind is ProjectionKind.COMPOSED
        assert projection.definition_id == definition.id
        assert projection.title == definition.title
        assert projection.layout == ProjectionLayout.RADIAL.value
        assert {item.semantic_id for item in projection.nodes} >= {
            "concept_answer_pipeline",
            diagram.id,
            atom.id,
        }
        assert any(
            edge.kind is SemanticRelationKind.CONCEPTUALLY_CONTAINS for edge in projection.edges
        )

        decoded = project_from_data(project_to_data(session.authority.snapshot()))
        assert decoded.concepts == session.authority.snapshot().concepts
        assert decoded.semantic_relations == session.authority.snapshot().semantic_relations
        assert decoded.projection_definitions == (definition,)

        in_use = session.client.delete_semantic_concept("concept_answer_pipeline")
        assert isinstance(in_use, CommandRejected)
        assert in_use.code == "SEMANTIC_CONCEPT_IN_USE"

        undone = session.client.undo()
        assert isinstance(undone, CommandAccepted)
        assert session.authority.snapshot().projection_definitions == ()
        redone = session.client.redo()
        assert isinstance(redone, CommandAccepted)
        assert session.authority.snapshot().projection_definitions == (definition,)
    finally:
        session.close()


def test_projection_language_is_available_over_the_automation_read_surface() -> None:
    session = ProjectSession.new()
    service = AutomationService(session.authority, kernel=session.kernel)
    context = AutomationContext(
        "projection-reader",
        "projection-connection",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.READ}),
    )
    try:
        definition = ProjectionDefinition(
            "preview_architecture",
            "Preview architecture",
            object_kinds=(
                SemanticObjectKind.PROJECT,
                SemanticObjectKind.MODULE,
                SemanticObjectKind.FUNCTION,
            ),
            relation_kinds=(SemanticRelationKind.CONTAINS,),
            grouping=ProjectionGrouping.OWNER,
            layout=ProjectionLayout.HORIZONTAL,
        )
        composed = service.dispatch(
            "query.compose_projection",
            {"definition": projection_definition_to_data(definition)},
            context,
        )
        assert isinstance(composed, dict)
        assert composed["definition_id"] == definition.id
        assert composed["layout"] == ProjectionLayout.HORIZONTAL.value
        assert composed["revision"] == session.authority.revision
        assert service.dispatch("query.projection_definitions", {}, context) == []
    finally:
        service.close()
        session.close()


def test_projection_materialization_creates_editable_semantically_anchored_views() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(diagram.id, "output", 0, source='"hello"')
        atom = session.authority.snapshot().documents[0].body.atoms[0]
        session.client.create_authored_semantic_relation(
            diagram.id,
            atom.id,
            kind=AuthoredRelationKind.EXPLAINS,
            label="introduces output",
            relation_id="semantic_relation_explanation",
        )
        definition = ProjectionDefinition(
            "projection_explanation",
            "Explanation",
            object_kinds=(SemanticObjectKind.FUNCTION, SemanticObjectKind.OPERATION),
            relation_kinds=(SemanticRelationKind.AUTHORED,),
            layout=ProjectionLayout.HORIZONTAL,
        )

        mind_result = session.client.materialize_projection(
            definition,
            ProjectionViewTarget.MIND_MAP,
            "Explanation - Mind Map",
            document_id="diagram_explanation_mindmap",
        )
        assert isinstance(mind_result, CommandAccepted)
        mindmap = session.authority.snapshot().documents[-1]
        assert isinstance(mindmap, MindMapDiagram)
        assert {topic.semantic_id for topic in walk_topics(mindmap.root)} >= {
            diagram.id,
            atom.id,
        }
        assert any(
            link.semantic_relation_id == "semantic_relation_explanation"
            for link in mindmap.cross_links
        )

        canvas_result = session.client.materialize_projection(
            definition,
            ProjectionViewTarget.FREEFORM,
            "Explanation - Canvas",
            document_id="diagram_explanation_canvas",
        )
        assert isinstance(canvas_result, CommandAccepted)
        canvas = session.authority.snapshot().documents[-1]
        assert isinstance(canvas, FreeformDiagram)
        assert {item.semantic_id for item in canvas.objects if isinstance(item, ShapeObject)} >= {
            diagram.id,
            atom.id,
        }
        assert any(
            isinstance(item, ConnectorObject)
            and item.semantic_relation_id == "semantic_relation_explanation"
            for item in canvas.objects
        )

        undone = session.client.undo()
        assert isinstance(undone, CommandAccepted)
        assert all(
            document.id != "diagram_explanation_canvas"
            for document in session.authority.snapshot().documents
        )
    finally:
        session.close()


def test_concept_lens_hides_unrelated_program_objects_by_default() -> None:
    session = ProjectSession.new()
    try:
        diagram = session.authority.snapshot().documents[0]
        session.client.insert_drakon_atom(diagram.id, "output", 0, source='"member"')
        session.client.insert_drakon_atom(diagram.id, "output", 1, source='"unrelated"')
        member, unrelated = session.authority.snapshot().documents[0].body.atoms
        session.client.create_semantic_concept(
            "Visible idea",
            (member.id,),
            concept_id="concept_visible_idea",
        )
        projection = session.kernel.queries.projection(ProjectionKind.CONCEPTS)
        semantic_ids = {item.semantic_id for item in projection.nodes}
        assert {"concept_visible_idea", member.id} <= semantic_ids
        assert unrelated.id not in semantic_ids
    finally:
        session.close()
