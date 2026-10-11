from dataclasses import replace

import pytest

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.notation_canvas import (
    NotationCompositionError,
    compile_notation_canvas,
)
from code_visualizer.application.notations import notation_edit_command
from code_visualizer.domain import notation_syntax as v
from code_visualizer.domain.authoring import AuthoredRelationKind, AuthoredSemanticRelation
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    ValueKind,
)
from code_visualizer.domain.language import AuthoredDomainLanguage
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.project import Project
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient


def composed_project():
    measurements = DomainSchema(
        "measurements",
        "example.measurements",
        "1",
        (
            ConceptDefinition(
                "sensor",
                "Sensor",
                (
                    PropertyDefinition("sensor.name", "Name"),
                    PropertyDefinition("sensor.reading", "Reading", ValueKind.NUMBER),
                ),
                display_property_id="sensor.name",
            ),
        ),
    )
    requirements = DomainSchema(
        "requirements",
        "example.requirements",
        "3",
        (
            ConceptDefinition(
                "requirement",
                "Requirement",
                (PropertyDefinition("requirement.summary", "Summary"),),
                display_property_id="requirement.summary",
            ),
        ),
    )
    sensor = IntentionalNode(
        "sensor:one",
        "sensor",
        (PropertyValue("sensor.name", "Acceleration"), PropertyValue("sensor.reading", 9.81)),
    )
    requirement = IntentionalNode(
        "requirement:one",
        "requirement",
        (PropertyValue("requirement.summary", "Keep acceleration below 12"),),
    )
    sensor_model = DomainModel(
        "observations", measurements.id, "1", (sensor.id,), (sensor,), "Measurements"
    )
    requirement_model = DomainModel(
        "safety", requirements.id, "3", (requirement.id,), (requirement,), "Safety requirements"
    )
    sensor_card = v.VisualBox(
        "sensor-card",
        v.VisualGroup(
            "sensor-info",
            v.VisualLayout.COLUMN,
            (
                v.VisualField("sensor-name", "s", "sensor.name"),
                v.VisualFraction(
                    "equation",
                    v.VisualField("reading", "s", "sensor.reading"),
                    v.VisualScript(
                        "units",
                        v.VisualText("unit", "s"),
                        v.VisualText("power", "2", font_size=10.0),
                    ),
                ),
            ),
        ),
    )
    requirement_card = v.VisualBox(
        "requirement-card",
        v.VisualField("requirement-text", "r", "requirement.summary"),
        fill="#eaf6ed",
    )
    body = v.VisualRepeat(
        "sensors",
        v.NotationObjects("sensor-query", "sensor"),
        "s",
        v.VisualGroup(
            "joined-row",
            v.VisualLayout.ROW,
            (
                sensor_card,
                v.VisualRepeat(
                    "requirement-repeat",
                    v.NotationRelated("related", "s", relation_kind="implements"),
                    "r",
                    v.VisualGroup(
                        "relationship",
                        v.VisualLayout.ROW,
                        (
                            requirement_card,
                            v.VisualConnector("traceability", "s", "r", "implements"),
                        ),
                    ),
                    binding_name="requirement",
                ),
            ),
            gap=100.0,
        ),
        binding_name="sensor",
    )
    definition = NotationDefinition(
        "instrument",
        "Instrument and requirements",
        NotationKind.COMPOSED,
        schema_id=measurements.id,
        body=body,
    )
    language = AuthoredDomainLanguage(
        "measurement-language",
        measurements.id,
        "1",
        title="Measurement notation",
        notations=(definition,),
    )
    project = Project(
        "composed-project",
        "Cross-domain instrument",
        (),
        semantic_relations=(
            AuthoredSemanticRelation(
                "link", sensor.id, requirement.id, AuthoredRelationKind.IMPLEMENTS
            ),
        ),
        domain_workspace=DomainWorkspace(
            (measurements, requirements),
            (sensor_model, requirement_model),
            language_definitions=(language,),
        ),
    )
    return project, definition


def test_cross_domain_formula_compiles_direct_edit_bindings_and_roundtrips_without_copies():
    project, definition = composed_project()
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="composed-test")
    kernel = ProjectKernel(authority)
    try:
        canvas = kernel.notation("observations", definition.id).canvas
        assert canvas is not None
        fields = {item.syntax_id: item for item in canvas.items if item.edit}
        assert fields["sensor-name"].edit.model_id == "observations"
        assert fields["requirement-text"].edit.model_id == "safety"
        assert {item.semantic_ids for item in fields.values()} == {
            ("sensor:one",),
            ("requirement:one",),
        }
        assert len(canvas.connectors) == 1
        edge = canvas.connectors[0]
        assert (edge.source_id, edge.target_id) == ("sensor:one", "requirement:one")
        source = next(item for item in canvas.items if item.syntax_id == "sensor-card")
        assert edge.start[0] == source.x + source.width
        assert edge.start != (source.x + source.width / 2, source.y + source.height / 2)
        binding = fields["requirement-text"].edit
        assert isinstance(
            client.submit(notation_edit_command(binding, "Revised limit", revision=0)),
            CommandAccepted,
        )
        with pytest.raises(ValueError, match="changed"):
            notation_edit_command(binding, "Stale edit", revision=1)
        updated = kernel.notation("observations", definition.id).canvas
        assert (
            next(item.text for item in updated.items if item.syntax_id == "requirement-text")
            == "Revised limit"
        )
        assert client.snapshot().domain_workspace.model(
            "observations"
        ) == project.domain_workspace.model("observations")
        restored = project_from_json(normalized_project_json(client.snapshot()))
        assert restored.domain_workspace == client.snapshot().domain_workspace
        assert restored.semantic_relations == project.semantic_relations
        assert isinstance(client.undo(), CommandAccepted)
        assert client.snapshot().domain_workspace == project.domain_workspace
    finally:
        kernel.close()
        client.close()


def test_math_layout_runtime_and_positioned_numeric_property_are_disposable():
    project, definition = composed_project()
    canvas = compile_notation_canvas(
        project, "observations", definition, active_ids=("requirement:one",), runtime_revision=0
    )
    by_syntax = {item.syntax_id: item for item in canvas.items}
    assert by_syntax["reading"].y < by_syntax["equation"].y < by_syntax["unit"].y
    assert by_syntax["power"].y < by_syntax["unit"].y
    assert by_syntax["requirement-text"].active and canvas.connectors[0].active
    assert not by_syntax["sensor-name"].active
    stale = compile_notation_canvas(
        replace(project, revision=1),
        "observations",
        definition,
        active_ids=("requirement:one",),
        runtime_revision=0,
    )
    assert not any(item.active for item in stale.items)
    position = v.VisualPosition(
        "position",
        v.VisualBox("timed-box", v.VisualText("timed-text", "sample")),
        v.VisualNumber("x", property_id="sensor.reading", scale=10),
        v.VisualNumber("y", -20),
    )
    placed = compile_notation_canvas(project, "observations", replace(definition, body=position))
    assert placed.items[0].x == pytest.approx(98.1)
    assert placed.items[0].y == -20
    assert project == composed_project()[0]


def test_workspace_query_pins_schema_version_and_keeps_model_owner():
    project, definition = composed_project()
    query = v.NotationObjects("workspace-query", "requirement", "requirements", "3", workspace=True)
    repeated = v.VisualRepeat(
        "workspace-repeat",
        query,
        "requirement",
        v.VisualField("foreign-field", "requirement", "requirement.summary"),
    )
    canvas = compile_notation_canvas(project, "observations", replace(definition, body=repeated))
    assert canvas.items[0].edit.model_id == "safety"
    with pytest.raises(NotationCompositionError, match="schema/version"):
        compile_notation_canvas(
            project,
            "observations",
            replace(definition, body=replace(repeated, query=replace(query, schema_version="4"))),
        )


def test_repeated_joined_object_instances_have_unique_ids_and_local_connector_anchors():
    project, definition = composed_project()
    model = project.domain_workspace.model("observations")
    second = replace(model.nodes[0], id="sensor:two")
    model = replace(model, roots=(*model.roots, second.id), nodes=(*model.nodes, second))
    project = replace(
        project,
        domain_workspace=replace(
            project.domain_workspace, models=(model, project.domain_workspace.models[1])
        ),
        semantic_relations=(
            *project.semantic_relations,
            AuthoredSemanticRelation(
                "link2", second.id, "requirement:one", AuthoredRelationKind.IMPLEMENTS
            ),
        ),
    )
    canvas = compile_notation_canvas(project, model.id, definition)
    assert len({item.id for item in canvas.items}) == len(canvas.items)
    requirement_cards = [item for item in canvas.items if item.syntax_id == "requirement-card"]
    assert len(requirement_cards) == 2
    assert len(canvas.connectors) == 2
    assert canvas.connectors[0].end[1] < canvas.connectors[1].end[1]
    assert {
        item.edit.node_id for item in canvas.items if item.edit and item.edit.model_id == "safety"
    } == {"requirement:one"}


def test_nested_queries_are_charged_before_large_scan_and_ambiguous_connectors_fail():
    project, definition = composed_project()
    many = tuple(IntentionalNode(f"sensor:{index}", "sensor") for index in range(160))
    model = replace(
        project.domain_workspace.models[0], roots=tuple(item.id for item in many), nodes=many
    )
    project = replace(project, domain_workspace=replace(project.domain_workspace, models=(model,)))
    nested = v.VisualRepeat(
        "outer",
        v.NotationObjects("outer-query", "sensor"),
        "outer-binding",
        v.VisualRepeat(
            "inner",
            v.NotationObjects("inner-query", "sensor"),
            "inner-binding",
            v.VisualText("item", "x"),
        ),
    )
    with pytest.raises(NotationCompositionError, match="20000"):
        compile_notation_canvas(project, model.id, replace(definition, body=nested))
    project, definition = composed_project()
    original = definition.body
    cards = original.body.children
    duplicate = replace(
        cards[0], id="duplicate-card", body=v.VisualText("duplicate-text", "duplicate")
    )
    ambiguous = replace(
        original, body=replace(original.body, children=(cards[0], duplicate, cards[1]))
    )
    with pytest.raises(NotationCompositionError, match="multiple displayed anchors"):
        compile_notation_canvas(project, "observations", replace(definition, body=ambiguous))
