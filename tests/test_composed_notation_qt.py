from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialogButtonBox,
    QGraphicsTextItem,
    QInputDialog,
    QPushButton,
)
from test_composed_notations import composed_project

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.language_commands import PutDomainLanguage
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.domain import language as lang
from code_visualizer.domain.notation import NotationKind
from code_visualizer.domain.notation_syntax import VisualRepeat
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    Representation,
    TransformationDefinition,
)
from code_visualizer.execution import DebugEvent, DebugState
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.language_editors import LanguageEditorDialog
from code_visualizer.ui_qt.features.domain_workbench.notation_expression_editor import (
    NotationExpressionDialog,
)
from code_visualizer.ui_qt.features.domain_workbench.query_expression_editor import (
    QueryExpressionDialog,
)
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget


def _workbench(qtbot):
    project, definition = composed_project()
    authority = ProjectAuthority(project)
    kernel = ProjectKernel(authority)
    client = CodeVisualizerClient(authority, actor_id="composed-qt")
    widget = DomainWorkbenchWidget()
    qtbot.addWidget(widget)
    widget.resize(1200, 840)
    widget.attach(kernel, client)
    widget.tabs.setCurrentWidget(widget.composed)
    widget.show()
    return widget, kernel, client, project, definition


def test_pointer_edits_cross_domain_fields_and_shared_selection_and_undo(qtbot):
    widget, kernel, client, project, definition = _workbench(qtbot)
    try:
        assert widget.notation_choice.currentData() == definition.id
        assert any(
            isinstance(item, QGraphicsTextItem) and item.toPlainText() == "implements"
            for item in widget.composed.scene.items()
        )
        for syntax, updated, model_id, node_id, property_id in (
            ("sensor-name", "Velocity", "observations", "sensor:one", "sensor.name"),
            (
                "requirement-text",
                "Reviewed safety limit",
                "safety",
                "requirement:one",
                "requirement.summary",
            ),
        ):
            canvas = widget.composed.canvas
            field = next(item for item in canvas.items if item.syntax_id == syntax)
            item = widget.composed.items_by_id[field.id]
            widget.composed.view.ensureVisible(item)
            position = widget.composed.view.mapFromScene(item.sceneBoundingRect().center())
            qtbot.mouseClick(
                widget.composed.view.viewport(), Qt.MouseButton.LeftButton, pos=position
            )
            assert node_id in kernel.selection.state.semantic_ids

            def answer(value=updated):
                dialog = QApplication.activeModalWidget()
                assert isinstance(dialog, QInputDialog)
                dialog.setTextValue(value)
                dialog.accept()

            QTimer.singleShot(0, answer)
            qtbot.mouseDClick(
                widget.composed.view.viewport(), Qt.MouseButton.LeftButton, pos=position
            )
            assert (
                client.snapshot()
                .domain_workspace.model(model_id)
                .node(node_id)
                .property(property_id)
                == updated
            )
            assert (
                next(item.text for item in widget.composed.canvas.items if item.syntax_id == syntax)
                == updated
            )
        assert isinstance(client.undo(), CommandAccepted)
        assert isinstance(client.undo(), CommandAccepted)
        assert client.snapshot().domain_workspace == project.domain_workspace
        kernel.runtime.record(
            DebugEvent(
                1,
                "paused",
                DebugState.PAUSED,
                execution_session_id="composed-runtime",
                project_revision=kernel.revision,
                artifact_revision=kernel.revision,
            ),
            semantic_id="requirement:one",
        )
        # Runtime publication is sampled by the Qt observer, not rendered on
        # the publisher's thread.
        qtbot.waitUntil(
            lambda: next(
                item.active
                for item in widget.composed.canvas.items
                if item.syntax_id == "requirement-text"
            )
        )
        assert next(
            item.active
            for item in widget.composed.canvas.items
            if item.syntax_id == "requirement-text"
        )
        assert not next(
            item.active for item in widget.composed.canvas.items if item.syntax_id == "sensor-name"
        )
        assert widget.composed.canvas.connectors[0].active
        kernel.selection.select(("requirement:one",), source="test.runtime_selection")
        selected = widget.composed.scene.selectedItems()
        assert selected
        restored = project_from_json(normalized_project_json(client.snapshot()))
        assert restored.domain_workspace == project.domain_workspace
    finally:
        widget.attach(None)
        kernel.close()
        client.close()


def test_human_expression_ui_previews_and_saves_typed_math_and_cross_domain_join(qtbot):
    widget, kernel, client, project, definition = _workbench(qtbot)
    try:
        schema = project.domain_workspace.schemas[0]
        language = project.domain_workspace.language_definitions[0]
        editor = LanguageEditorDialog(
            schema, language, workspace=project.domain_workspace, project=project
        )
        qtbot.addWidget(editor)
        editor.show()
        editor.select_identity(definition.id)
        expression = """each('Sensor', 'sensor',
  row(box(column(text('Measured quantity'), field('sensor', 'Name'),
        fraction(field('sensor', 'Reading'), superscript(text('s'), text('2'))))),
      related('sensor', 'implements', 'requirement',
        row(box(field('requirement', 'Summary')), connect('sensor', 'requirement'))),
      gap=50))"""

        def author():
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, NotationExpressionDialog)
            dialog.editor.setPlainText(expression)
            qtbot.mouseClick(
                dialog.findChild(QPushButton, "notationPreviewButton"), Qt.MouseButton.LeftButton
            )
            assert dialog._valid, dialog.status.text()
            assert {item.edit.model_id for item in dialog.preview.canvas.items if item.edit} == {
                "observations",
                "safety",
            }
            buttons = dialog.findChild(QDialogButtonBox)
            qtbot.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton
            )

        QTimer.singleShot(0, author)
        qtbot.mouseClick(editor.expression_button, Qt.MouseButton.LeftButton)
        changed = editor.language()
        assert changed.syntax_version == 2
        assert changed.notations[0].kind is NotationKind.COMPOSED
        assert isinstance(changed.notations[0].body, VisualRepeat)
        assert changed.notations[0].body.id == definition.body.id
        assert isinstance(client.submit(PutDomainLanguage(changed)), CommandAccepted)
        assert any(item.text == "Measured quantity" for item in widget.composed.canvas.items)
        assert client.snapshot().domain_workspace.models == project.domain_workspace.models
        assert project_from_json(
            normalized_project_json(client.snapshot())
        ).domain_workspace.language_definitions == (changed,)
        assert isinstance(client.undo(), CommandAccepted)
        assert client.snapshot().domain_workspace.language_definitions == (language,)
    finally:
        widget.attach(None)
        kernel.close()
        client.close()


def test_structured_domain_output_uses_target_schema_choices_and_source_query_bindings(qtbot):
    project, _ = composed_project()
    source, target = project.domain_workspace.schemas
    language = lang.AuthoredDomainLanguage(
        "new-language",
        source.id,
        source.version,
        title="Domain pipeline",
        transformations=(
            lang.AuthoredTransformation(
                TransformationDefinition(
                    "transform",
                    "1",
                    Representation(source.namespace, source.version),
                    PROGRAM_REPRESENTATION,
                )
            ),
        ),
        syntax_version=1,
    )
    editor = LanguageEditorDialog(source, language, workspace=project.domain_workspace)
    qtbot.addWidget(editor)
    editor.show()
    editor.select_path(("transformations", 0, "domain"))
    editor.variant.setCurrentIndex(editor.variant.findData(lang.DomainTemplate))
    qtbot.mouseClick(editor.replace_button, Qt.MouseButton.LeftButton)
    field = editor.findChild(QComboBox, "languageField:target_schema_id")
    field.setCurrentIndex(field.findData(target.id))
    qtbot.mouseClick(editor.apply_button, Qt.MouseButton.LeftButton)
    output = editor.language().transformations[0]
    assert editor.language().syntax_version == 2
    assert output.domain.target_schema_version == target.version
    assert output.definition.target == Representation(target.namespace, target.version)
    editor.select_path(("transformations", 0, "domain", "nodes"))
    qtbot.mouseClick(editor.add_button, Qt.MouseButton.LeftButton)
    concept = editor.findChild(QComboBox, "languageField:concept_id")
    assert concept.findData("requirement") >= 0
    assert concept.findData("sensor") < 0
    editor.select_path(("transformations", 0, "domain", "nodes", 0, "source"))
    editor.variant.setCurrentIndex(editor.variant.findData(lang.QueryNodes))
    qtbot.mouseClick(editor.replace_button, Qt.MouseButton.LeftButton)
    concept = editor.findChild(QComboBox, "languageField:concept_id")
    assert concept.findData("sensor") >= 0
    assert concept.findData("requirement") < 0


def test_query_expression_ui_changes_validator_meaning_and_keeps_binding_and_undo(qtbot):
    widget, kernel, client, project, _ = _workbench(qtbot)
    try:
        language = project.domain_workspace.language_definitions[0]
        predicate = lang.QueryBinary(
            "limit-test",
            lang.QueryBinaryOperator.LESS,
            lang.QueryProperty(
                "read-limit", lang.QueryVariable("read-sensor", "sensor-binding"), "sensor.reading"
            ),
            lang.QueryLiteral("maximum", 12),
        )
        validator = lang.ValidatorDefinition(
            "limit-validator",
            "sensor",
            "sensor-binding",
            predicate,
            "Reading must satisfy the limit",
            code="MEASUREMENT_LIMIT",
        )
        original = replace(language, validators=(validator,))
        assert isinstance(client.submit(PutDomainLanguage(original)), CommandAccepted)
        assert not any(item.code == "MEASUREMENT_LIMIT" for item in kernel.workbench().diagnostics)
        editor = LanguageEditorDialog(
            project.domain_workspace.schemas[0], original, workspace=project.domain_workspace
        )
        qtbot.addWidget(editor)
        editor.show()
        editor.select_identity(predicate.id)

        def edit_query():
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, QueryExpressionDialog)
            assert dialog.bindings[0].id == "sensor-binding"
            assert "item.Reading" in dialog.editor.toPlainText()
            dialog.editor.setPlainText("item.Reading > 12")
            qtbot.mouseClick(
                dialog.findChild(QPushButton, "queryExpressionCheck"), Qt.MouseButton.LeftButton
            )
            assert dialog._valid, dialog.status.text()
            buttons = dialog.findChild(QDialogButtonBox)
            qtbot.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton
            )

        QTimer.singleShot(0, edit_query)
        qtbot.mouseClick(editor.query_expression_button, Qt.MouseButton.LeftButton)
        changed = editor.language()
        assert changed.validators[0].predicate.id == predicate.id
        assert changed.validators[0].binding_id == "sensor-binding"
        assert changed.validators[0].predicate.operator is lang.QueryBinaryOperator.GREATER
        assert isinstance(client.submit(PutDomainLanguage(changed)), CommandAccepted)
        assert any(item.code == "MEASUREMENT_LIMIT" for item in kernel.workbench().diagnostics)
        assert client.snapshot().domain_workspace.models == project.domain_workspace.models
        assert isinstance(client.undo(), CommandAccepted)
        assert not any(item.code == "MEASUREMENT_LIMIT" for item in kernel.workbench().diagnostics)
    finally:
        widget.attach(None)
        kernel.close()
        client.close()
