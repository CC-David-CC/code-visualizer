"""Mathematical meaning, typed editors and neutral evidence share canonical identities."""

import struct
from dataclasses import replace

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog, QTableWidgetItem

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation import execute_computation, get_evidence
from code_visualizer.application.domain_commands import PutDomainSchema, SetDomainProperty
from code_visualizer.application.domain_installation import schema_installation
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.notation_canvas import compile_notation_canvas
from code_visualizer.application.notations import field_cell, notation_edit_command
from code_visualizer.domain import notation_syntax as visual
from code_visualizer.domain.computation import ComputationRequest
from code_visualizer.domain.evidence import ComputationOutcome
from code_visualizer.domain.intentional import (
    DomainModel,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    ValueKind,
)
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.notation import NotationDefinition, NotationField, NotationKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.resources import TensorDescriptor
from code_visualizer.domain.values import (
    ComplexValue,
    Dimension,
    DimensionPower,
    QuantityValue,
    ResourceReference,
    TensorDType,
    TensorValue,
    UnitReference,
    ValueConstraints,
    canonical_value_key,
)
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.foundations.backend import BACKEND_ID, TENSOR_MEDIA_TYPE
from code_visualizer.extensions.foundations.examples import matrix_product_project
from code_visualizer.extensions.foundations.math import SCHEMA_ID, math_schema, validate_math
from code_visualizer.extensions.foundations.math import identity as math_id
from code_visualizer.extensions.foundations.space import identity as space_id
from code_visualizer.extensions.foundations.space import space_schema, validate_space
from code_visualizer.extensions.foundations.units_si import si_catalog
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.evidence_store import EvidenceStore
from code_visualizer.persistence.resource_store import ResourceStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.editors import (
    PropertyDialog,
    ReferenceEditor,
    ScalarEditor,
    ValueDialog,
)
from code_visualizer.ui_qt.features.domain_workbench.value_editors import (
    ComplexValueEditor,
    QuantityValueEditor,
    ResourceValueEditor,
    TensorValueEditor,
)
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget


def _kernel(tmp_path, project=None):
    authority = ProjectAuthority(project or matrix_product_project())
    client = CodeVisualizerClient(authority, actor_id="foundation-proof")
    kernel = ProjectKernel(
        authority, resource_store=ResourceStore(tmp_path), evidence_store=EvidenceStore(tmp_path)
    )
    return kernel, client


def _request(kernel):
    project = kernel.authority.snapshot()
    return ComputationRequest(project.id, project.revision, BACKEND_ID, "1", "matrix:model")


def _space_project():
    project = matrix_product_project()
    math_model = project.domain_workspace.models[0]
    coordinates = IntentionalNode(
        "geometry:coordinates",
        math_id("TensorLiteral"),
        (
            PropertyValue(
                math_id("TensorLiteral", "value"),
                TensorValue(TensorDType.FLOAT64, (2,), (1.0, 2.0)),
            ),
        ),
    )
    matrix = IntentionalNode(
        "geometry:matrix",
        math_id("TensorLiteral"),
        (
            PropertyValue(
                math_id("TensorLiteral", "value"),
                TensorValue(
                    TensorDType.FLOAT64, (3, 3), (1.0, 0.0, 10.0, 0.0, 1.0, 20.0, 0.0, 0.0, 1.0)
                ),
            ),
        ),
    )
    math_model = replace(
        math_model,
        roots=(*math_model.roots, coordinates.id, matrix.id),
        nodes=(*math_model.nodes, coordinates, matrix),
    )
    space = IntentionalNode(
        "geometry:space",
        space_id("Space"),
        (
            PropertyValue(space_id("Space", "name"), "Plane"),
            PropertyValue(space_id("Space", "dimension"), 2),
        ),
    )
    frames = tuple(
        IntentionalNode(
            f"geometry:{name}",
            space_id("Frame"),
            (PropertyValue(space_id("Frame", "name"), name),),
            references=(RoleBinding(space_id("Frame", "space"), (space.id,)),),
        )
        for name in ("local", "world")
    )
    point = IntentionalNode(
        "geometry:point",
        space_id("Point"),
        (PropertyValue(space_id("Point", "name"), "P"),),
        references=(
            RoleBinding(space_id("Point", "frame"), (frames[0].id,)),
            RoleBinding(space_id("Point", "coordinates"), (coordinates.id,)),
        ),
    )
    transform = IntentionalNode(
        "geometry:transform",
        space_id("Transform"),
        (PropertyValue(space_id("Transform", "name"), "Translate"),),
        references=(
            RoleBinding(space_id("Transform", "source"), (frames[0].id,)),
            RoleBinding(space_id("Transform", "target"), (frames[1].id,)),
            RoleBinding(space_id("Transform", "matrix"), (matrix.id,)),
        ),
    )
    nodes = (space, *frames, point, transform)
    model = DomainModel(
        "geometry:model",
        space_schema().id,
        "1",
        tuple(node.id for node in nodes),
        nodes,
        "Geometry",
    )
    return replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            schemas=(*project.domain_workspace.schemas, space_schema()),
            models=(math_model, model),
        ),
    )


def test_foundations_are_complete_ordinary_schemas_and_install_dependencies_in_one_authority():
    schema = math_schema()
    assert {
        math_id(name)
        for name in (
            "Symbol",
            "Literal",
            "OperatorApplication",
            "Equation",
            "Constraint",
            "Index",
            "TensorSymbol",
            "Derivative",
            "Integral",
            "Function",
        )
    } <= {item.id for item in schema.concepts}
    registry = builtin_registry()
    assert registry.get("foundation.math", "1").schemas == (schema,)
    assert registry.get("foundation.space", "1").schemas == (space_schema(),)
    project = Project("foundation-install", "Foundations", ())
    available = tuple(schema for bundle in registry.bundles() for schema in bundle.schemas)
    schemas = schema_installation(project.domain_workspace, available, space_schema().id)
    assert {item.id for item in schemas} == {schema.id, space_schema().id}
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="installation")
    assert isinstance(
        client.transaction(tuple(PutDomainSchema(item) for item in schemas)), CommandAccepted
    )
    assert not validate_domain_workspace(authority.snapshot().domain_workspace)
    assert not authority.snapshot().program_model.functions


def test_structured_equation_roundtrips_without_executable_source_or_duplicate_symbol_meaning():
    project = matrix_product_project()
    schema, model = project.domain_workspace.schemas[0], project.domain_workspace.models[0]
    assert not validate_domain_workspace(project.domain_workspace)
    assert not validate_math(project, model)
    nodes = {node.id: node for node in model.nodes}
    equation = nodes["matrix:equation"]
    assert equation.child_ids(math_id("Equation", "right")) == ("matrix:expression:sum",)
    summation = nodes["matrix:expression:sum"]
    assert summation.reference_ids(math_id("OperatorApplication", "bound_symbols")) == ("matrix:k",)
    occurrences = [
        node
        for node in nodes.values()
        if node.concept_id == math_id("SymbolReference")
        and node.reference_ids(math_id("SymbolReference", "symbol")) == ("matrix:k",)
    ]
    assert len(occurrences) == 2 and occurrences[0].id != occurrences[1].id
    assert sum(node.id == "matrix:k" for node in model.nodes) == 1
    assert not any(
        prop.name.lower() in {"python", "source", "callback"}
        for concept in schema.concepts
        for prop in concept.properties
    )
    serialized = normalized_project_json(project)
    reloaded = project_from_json(serialized)
    assert reloaded.domain_workspace == project.domain_workspace
    assert normalized_project_json(reloaded) == serialized


def test_matrix_equation_runs_directly_returns_resources_and_highlights_origins(
    tmp_path, monkeypatch
):
    import code_visualizer.generation.python as python_generation

    def forbidden(*_args, **_kwargs):
        pytest.fail("A mathematical backend called the Python generator")

    monkeypatch.setattr(python_generation, "generate_python", forbidden)
    monkeypatch.setattr(python_generation, "generate_python_project", forbidden)
    kernel, client = _kernel(tmp_path)
    try:
        before = normalized_project_json(kernel.authority.snapshot())
        first = execute_computation(kernel, _request(kernel))
        assert first.outcome is ComputationOutcome.SUCCEEDED
        assert first.provenance.transformations == ()
        value = first.observations[0].value
        assert value == TensorValue(TensorDType.FLOAT64, (2, 2), (19.0, 22.0, 43.0, 50.0))
        assert {
            "matrix:equation",
            "matrix:expression:sum",
            "matrix:A",
            "matrix:B",
            "matrix:C",
            "matrix:k",
        } <= set(first.observations[0].semantic_ids)
        descriptor = kernel.resource_store.describe(first.artifacts[0].resource)
        assert descriptor.media_type == TENSOR_MEDIA_TYPE
        assert descriptor.tensor.shape == (2, 2)
        assert (
            struct.unpack("<4d", kernel.resource_store.read(first.artifacts[0].resource))
            == value.elements
        )
        assert get_evidence(kernel, first.id) == first
        assert execute_computation(kernel, _request(kernel)) == first
        assert normalized_project_json(kernel.authority.snapshot()) == before
        assert kernel.runtime.active.observation.value == value
        assert "matrix:expression:sum" in kernel.runtime.active.active_ids
        for kind in (NotationKind.GRAPH, NotationKind.TABLE, NotationKind.TREE_FORM):
            definition = next(
                item for item in kernel.notations("matrix:model") if item.kind is kind
            )
            projection = kernel.notation("matrix:model", definition.id)
            assert projection.runtime_revision == 0
            if kind is NotationKind.TABLE:
                assert any(row.active for row in projection.rows)
            else:
                assert any(node.badges for node in projection.graph.nodes)
        assert isinstance(
            client.submit(
                SetDomainProperty("matrix:model", "matrix:k", math_id("Symbol", "name"), "r")
            ),
            CommandAccepted,
        )
        newer = execute_computation(kernel, _request(kernel))
        assert newer.observations[0].value == value
        assert newer.provenance.revision == 1 and first.provenance.revision == 0
        assert newer.provenance.input_digest != first.provenance.input_digest
        assert kernel.evidence_store.get(first.id) == first
    finally:
        kernel.close()


def test_dimension_mismatch_is_owned_by_math_and_space_not_structural_kernel(tmp_path):
    project = _space_project()
    model = project.domain_workspace.model("geometry:model")
    assert not validate_domain_workspace(project.domain_workspace)
    assert not validate_space(project, model)
    kernel, client = _kernel(tmp_path, project)
    try:
        value = TensorValue(TensorDType.FLOAT64, (3,), (1.0, 2.0, 3.0))
        assert isinstance(
            client.submit(
                SetDomainProperty(
                    "matrix:model", "geometry:coordinates", math_id("TensorLiteral", "value"), value
                )
            ),
            CommandAccepted,
        )
        changed = kernel.authority.snapshot()
        assert not validate_domain_workspace(changed.domain_workspace)
        assert any(item.code == "SPACE_POINT_DIMENSION" for item in validate_space(changed, model))
        assert isinstance(client.undo(), CommandAccepted)
        assert kernel.authority.snapshot().domain_workspace == project.domain_workspace
    finally:
        kernel.close()


def test_cross_model_field_binding_and_reference_editor_keep_true_owner(qtbot, tmp_path):
    project = _space_project()
    workspace = project.domain_workspace
    model = workspace.model("geometry:model")
    schema = workspace.schema(model.schema_id)
    node = model.node("geometry:point")
    field = NotationField(math_id("TensorLiteral", "value"), (space_id("Point", "coordinates"),))
    cell = field_cell(
        schema, model, node, field, cell_id="coordinates", revision=0, workspace=workspace
    )
    assert cell.semantic_id == "geometry:coordinates" and cell.edit.model_id == "matrix:model"
    role = schema.concept(space_id("Point")).role(space_id("Point", "coordinates"))
    editor = ReferenceEditor(role, schema, model, ("geometry:coordinates",), workspace=workspace)
    qtbot.addWidget(editor)
    assert any(
        editor.item(index).data(Qt.ItemDataRole.UserRole) == "geometry:coordinates"
        for index in range(editor.count())
    )
    assert not any(
        editor.item(index).text().startswith("Missing") for index in range(editor.count())
    )
    kernel, client = _kernel(tmp_path, project)
    try:
        value = TensorValue(TensorDType.FLOAT64, (2,), (9.0, 2.0))
        assert isinstance(
            client.submit(notation_edit_command(cell.edit, value, revision=0)), CommandAccepted
        )
        assert (
            kernel.authority.snapshot()
            .domain_workspace.node("geometry:coordinates")
            .property(math_id("TensorLiteral", "value"))
            == value
        )
        assert kernel.authority.snapshot().domain_workspace.node("geometry:point") == node
    finally:
        kernel.close()


def test_typed_tensor_table_form_composed_edits_and_computation_ui(qtbot, tmp_path, request):
    from threading import get_ident

    kernel, client = _kernel(tmp_path)
    request.addfinalizer(kernel.close)
    request.addfinalizer(client.close)
    widget = DomainWorkbenchWidget()
    qtbot.addWidget(widget)
    request.addfinalizer(lambda: widget.attach(None))
    widget.attach(kernel, client)
    widget.show()
    before = kernel.authority.snapshot().domain_workspace
    notation_id = f"notation:{SCHEMA_ID}:table:{math_id('TensorLiteral')}"
    widget.notation_choice.setCurrentIndex(widget.notation_choice.findData(notation_id))

    def edit_modal():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, ValueDialog)
        control = dialog.editor.control
        assert isinstance(control, TensorValueEditor)
        control.table.setItem(0, 0, QTableWidgetItem("10.0"))
        dialog._accept()

    QTimer.singleShot(0, edit_modal)
    widget._table_open(0, 1)
    prop = math_id("TensorLiteral", "value")
    assert (
        kernel.authority.snapshot()
        .domain_workspace.node("matrix:A:value")
        .property(prop)
        .elements[0]
        == 10.0
    )
    widget.reveal("matrix:A:value")
    control = widget._properties[prop].control
    assert isinstance(control, TensorValueEditor)
    control.table.setItem(0, 1, QTableWidgetItem("12.0"))
    widget.apply_fields()
    assert (
        kernel.authority.snapshot()
        .domain_workspace.node("matrix:A:value")
        .property(prop)
        .elements[1]
        == 12.0
    )
    assert len(kernel.authority.snapshot().domain_workspace.models[0].nodes) == len(
        before.models[0].nodes
    )
    widget.undo()
    widget.undo()
    assert kernel.authority.snapshot().domain_workspace == before
    project = kernel.authority.snapshot()
    definition = NotationDefinition(
        "math:editable-values",
        "Tensor contents",
        NotationKind.COMPOSED,
        schema_id=SCHEMA_ID,
        body=visual.VisualRepeat(
            "repeat",
            visual.NotationObjects("objects", math_id("TensorLiteral")),
            "tensor",
            visual.VisualField("contents", "tensor", prop),
        ),
    )
    canvas = compile_notation_canvas(project, "matrix:model", definition)
    widget.composed.set_canvas(canvas)
    item = next(
        item for item in canvas.items if item.edit and item.edit.node_id == "matrix:A:value"
    )
    QTimer.singleShot(0, edit_modal)
    widget.composed.edit_item(item.id)
    assert (
        kernel.authority.snapshot()
        .domain_workspace.node("matrix:A:value")
        .property(prop)
        .elements[0]
        == 10.0
    )
    widget.undo()
    gui_thread = get_ident()
    selection_threads = []
    request.addfinalizer(
        kernel.selection.subscribe(
            lambda _state: selection_threads.append(get_ident()), replay=False
        )
    )
    widget.run_computation()
    qtbot.waitUntil(lambda: widget.evidence_view.topLevelItemCount() == 1, timeout=15000)
    assert widget.evidence_view.topLevelItemCount() == 1
    assert widget.tabs.currentWidget() is widget.evidence_panel
    assert "succeeded" in widget.status.text()
    assert selection_threads and set(selection_threads) == {gui_thread}
    widget.attach(None)
    kernel.close()


def test_complex_quantity_tensor_and_resource_controls_keep_typed_values(
    qtbot, tmp_path, monkeypatch
):
    complex_editor = ComplexValueEditor(ComplexValue(1.0, 2.0))
    qtbot.addWidget(complex_editor)
    complex_editor.imaginary.setText("3.5")
    assert complex_editor.value() == ComplexValue(1.0, 3.5)
    quantity = QuantityValue(
        3.0, UnitReference("length:metre", "1", Dimension((DimensionPower("length", 1),)))
    )
    quantity_editor = QuantityValueEditor(quantity)
    qtbot.addWidget(quantity_editor)
    assert quantity_editor.value() == quantity
    tensor = TensorValue(TensorDType.INT64, (2,), (4, 5))
    definition = PropertyDefinition(
        "shape",
        "Shape",
        ValueKind.TENSOR,
        default=tensor,
        value_constraints=ValueConstraints(tensor_dtype=TensorDType.INT64, tensor_shape=(2,)),
    )
    property_dialog = PropertyDialog(definition)
    qtbot.addWidget(property_dialog)
    property_dialog._accept()
    assert property_dialog.result_property == definition
    property_dialog.tensor_shape.setText("?, 2")
    property_dialog.tensor_dtype.setCurrentIndex(property_dialog.tensor_dtype.findData("float64"))
    property_dialog.default_enabled.setChecked(False)
    property_dialog._accept()
    assert property_dialog.result_property.value_constraints == ValueConstraints(
        tensor_dtype=TensorDType.FLOAT64, tensor_shape=(None, 2)
    )
    quantity_definition = PropertyDefinition(
        "length",
        "Length",
        ValueKind.QUANTITY,
        value_constraints=ValueConstraints(dimension=quantity.unit.dimension),
    )
    quantity_dialog = PropertyDialog(quantity_definition)
    qtbot.addWidget(quantity_dialog)
    quantity_dialog._accept()
    assert quantity_dialog.result_property == quantity_definition
    quantity_dialog.dimension.table.setItem(0, 1, QTableWidgetItem("2"))
    quantity_dialog._accept()
    assert quantity_dialog.result_property.value_constraints.dimension == Dimension(
        (DimensionPower("length", 2),)
    )
    scalar = ScalarEditor(definition, tensor)
    qtbot.addWidget(scalar)
    assert scalar.value() == tensor
    scalar.enabled_value.setChecked(False)
    assert scalar.value() is None
    store = ResourceStore(tmp_path)
    source = tmp_path / "data.txt"
    source.write_text("immutable imported contents", encoding="utf-8")
    reference_editor = ResourceValueEditor(resource_store=store)
    qtbot.addWidget(reference_editor)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(source), ""))
    reference_editor.import_file()
    reference = reference_editor.value()
    assert isinstance(reference, ResourceReference)
    assert store.read(reference) == source.read_bytes()
    assert len(store.descriptors()) == 1


@pytest.mark.parametrize("value", [1, 1.0, 2**53 + 1, 2**100, -0.0, 0.0])
def test_number_controls_preserve_numeric_variant_and_precision(qtbot, value):
    definition = PropertyDefinition("number", "Number", ValueKind.NUMBER)
    editor = ScalarEditor(definition, value)
    qtbot.addWidget(editor)
    assert canonical_value_key(editor.value()) == canonical_value_key(value)
    definition = replace(definition, choices=(0.0, -0.0, 1, 1.0, 2**53 + 1, 2**100))
    editor = ScalarEditor(definition, value)
    qtbot.addWidget(editor)
    assert canonical_value_key(editor.value()) == canonical_value_key(value)
    dialog = PropertyDialog(replace(definition, default=value))
    qtbot.addWidget(dialog)
    dialog._accept()
    assert canonical_value_key(dialog.result_property.default) == canonical_value_key(value)
    assert tuple(map(canonical_value_key, dialog.result_property.choices)) == tuple(
        map(canonical_value_key, definition.choices)
    )


def test_empty_tensor_with_enormous_axis_does_not_allocate_axis_pool(tmp_path):
    project = matrix_product_project()
    model = project.domain_workspace.models[0]
    output = model.node("matrix:C")
    output = replace(
        output,
        properties=(
            output.properties[0],
            PropertyValue(
                math_id("TensorSymbol", "shape"), TensorValue(TensorDType.INT64, (2,), (0, 2**60))
            ),
        ),
    )
    right = IntentionalNode(
        "matrix:expression:sum",
        math_id("Literal"),
        (PropertyValue(math_id("Literal", "value"), 1),),
    )
    replacements = {output.id: output, right.id: right}
    model = replace(
        model,
        roots=(*model.roots, "matrix:expression:multiply"),
        nodes=tuple(replacements.get(node.id, node) for node in model.nodes),
    )
    project = replace(project, domain_workspace=replace(project.domain_workspace, models=(model,)))
    kernel, _client = _kernel(tmp_path, project)
    try:
        evidence = execute_computation(kernel, _request(kernel))
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        assert evidence.observations[0].value == TensorValue(TensorDType.FLOAT64, (0, 2**60), ())
    finally:
        kernel.close()


def test_numeric_backend_reports_unsupported_resource_units_without_dropping_them(tmp_path):
    kernel, _client = _kernel(tmp_path)
    try:
        unit = si_catalog().unit("foundation.units.si:meter")
        resource = kernel.resource_store.put(
            struct.pack("<4d", 1.0, 2.0, 3.0, 4.0),
            TENSOR_MEDIA_TYPE,
            tensor=TensorDescriptor(TensorDType.FLOAT64, (2, 2), unit=unit),
        )
        project = kernel.authority.snapshot()
        model = project.domain_workspace.models[0]
        node = IntentionalNode(
            "matrix:A:value",
            math_id("ResourceLiteral"),
            (PropertyValue(math_id("ResourceLiteral", "value"), resource.reference),),
        )
        model = replace(
            model, nodes=tuple(node if item.id == node.id else item for item in model.nodes)
        )
        project = replace(
            project, domain_workspace=replace(project.domain_workspace, models=(model,))
        )
    finally:
        kernel.close()

    kernel, _client = _kernel(tmp_path, project)
    try:
        evidence = execute_computation(kernel, _request(kernel))
        assert evidence.outcome is ComputationOutcome.FAILED
        assert any(issue.code == "MATH_UNIT_UNSUPPORTED" for issue in evidence.diagnostics)
        assert evidence.artifacts == ()
    finally:
        kernel.close()


def test_rich_editors_preserve_exact_opaque_identity_on_unchanged_apply(qtbot):
    quantity = QuantityValue(
        3.0,
        UnitReference(
            " unit:length ", " 1 ", Dimension((DimensionPower(" dimension:length ", 1),))
        ),
    )
    editor = QuantityValueEditor(quantity)
    qtbot.addWidget(editor)
    assert editor.value() == quantity
    resource = ResourceReference(" resource:measured-data ", "a" * 64)
    resource_editor = ResourceValueEditor(resource)
    qtbot.addWidget(resource_editor)
    assert resource_editor.value() == resource


def test_each_equation_keeps_origins_of_shared_tensor_bindings(tmp_path):
    project = matrix_product_project()
    model = project.domain_workspace.models[0]
    expressions = tuple(
        node
        for node in model.nodes
        if node.id.startswith("matrix:expression:") or node.id == "matrix:equation"
    )
    renamed = {node.id: f"{node.id}:second" for node in expressions}
    copies = tuple(
        replace(
            node,
            id=renamed[node.id],
            children=tuple(
                replace(role, node_ids=tuple(renamed[identity] for identity in role.node_ids))
                for role in node.children
            ),
        )
        for node in expressions
    )
    model = replace(
        model, roots=(*model.roots, renamed["matrix:equation"]), nodes=(*model.nodes, *copies)
    )
    project = replace(project, domain_workspace=replace(project.domain_workspace, models=(model,)))
    kernel, _client = _kernel(tmp_path, project)
    try:
        evidence = execute_computation(kernel, _request(kernel))
        assert evidence.outcome is ComputationOutcome.SUCCEEDED, evidence.diagnostics
        assert len(evidence.observations) == 2
        for observation in evidence.observations:
            assert {"matrix:A:value", "matrix:B:value"} <= set(observation.semantic_ids)
    finally:
        kernel.close()
