from dataclasses import replace

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QLineEdit, QPushButton
from pytestqt.exceptions import TimeoutError as QtTimeoutError

from code_visualizer.application.authored_examples import authored_traffic_light_project
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain import language as lang
from code_visualizer.domain.intentional import (
    DomainModel,
    DomainWorkspace,
    IntentionalNode,
    PropertyValue,
)
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationKind,
    NotationNodeRule,
)
from code_visualizer.domain.project import Project
from code_visualizer.extensions.fsm import fsm_schema
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.language_editors import LanguageEditorDialog
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow


def _schema():
    return replace(
        fsm_schema(), id="authored:schema", namespace="example.authored_fsm", bundle=None
    )


def _window(qtbot, tmp_path):
    schema = _schema()
    node = IntentionalNode("state:first", "fsm:state", (PropertyValue("fsm:state:name", "Red"),))
    model = DomainModel(
        "authored:model", schema.id, schema.version, (node.id,), (node,), "State machine"
    )
    project = Project(
        "authored:project",
        "Authored state machine",
        (),
        domain_workspace=DomainWorkspace((schema,), (model,)),
    )
    authority = ProjectAuthority(project)
    session = ProjectSession(
        authority, CodeVisualizerClient(authority, actor_id="language-ui-test"), None, 0
    )
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    qtbot.addWidget(window)
    window.show()
    window._install_session(session)
    window._show_domain_workbench()
    window.domain_workbench.tabs.setCurrentWidget(window.domain_workbench.language_panel)
    return window, session


def _select(qtbot, dialog, path):
    dialog.select_path(path)
    item = dialog.tree.currentItem()
    qtbot.mouseClick(
        dialog.tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=dialog.tree.visualItemRect(item).center(),
    )


def _kind(qtbot, dialog, path, variant, *, add=False):
    _select(qtbot, dialog, path)
    index = dialog.variant.findData(variant)
    assert index >= 0
    dialog.variant.setCurrentIndex(index)
    qtbot.mouseClick(dialog.add_button if add else dialog.replace_button, Qt.MouseButton.LeftButton)


def _field(qtbot, dialog, name, value):
    control = dialog.findChild(
        (QLineEdit if isinstance(value, str) else QComboBox), f"languageField:{name}"
    )
    if control is None:
        control = dialog.findChild(QComboBox, f"languageField:{name}")
    assert control is not None
    if isinstance(control, QLineEdit):
        control.selectAll()
        qtbot.keyClicks(control, value)
    else:
        index = control.findData(value)
        assert index >= 0, (name, value)
        control.setCurrentIndex(index)
    qtbot.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)


def _property_query(qtbot, dialog, path):
    _kind(qtbot, dialog, path, lang.QueryProperty)
    _field(qtbot, dialog, "property_id", "fsm:state:name")
    _kind(qtbot, dialog, (*path, "source"), lang.QueryVariable)
    assert dialog.findChild(QComboBox, "languageField:binding_id").count() == 1


def _author_language(qtbot, dialog):
    # Three custom notations, including an explicit table property binding.
    for index, kind in enumerate((NotationKind.GRAPH, NotationKind.TABLE, NotationKind.TREE_FORM)):
        _kind(qtbot, dialog, ("notations",), NotationDefinition, add=True)
        _field(qtbot, dialog, "title", f"State machine {kind.value}")
        _field(qtbot, dialog, "kind", kind)
        _kind(qtbot, dialog, ("notations", index, "concept_ids"), str, add=True)
        _field(qtbot, dialog, "value", "fsm:state")
        if kind is NotationKind.TABLE:
            _kind(qtbot, dialog, ("notations", index, "columns"), NotationColumn, add=True)
            _field(qtbot, dialog, "title", "State name")
            _select(qtbot, dialog, ("notations", index, "columns", 0, "field"))
            _field(qtbot, dialog, "property_id", "fsm:state:name")
        else:
            _kind(qtbot, dialog, ("notations", index, "node_rules"), NotationNodeRule, add=True)
            _field(qtbot, dialog, "concept_id", "fsm:state")
            _field(qtbot, dialog, "label_property_id", "fsm:state:name")
    # Validator: each State name differs from the empty string.
    _kind(qtbot, dialog, ("validators",), lang.ValidatorDefinition, add=True)
    _field(qtbot, dialog, "concept_id", "fsm:state")
    _field(qtbot, dialog, "message", "A state needs a name")
    _kind(qtbot, dialog, ("validators", 0, "predicate"), lang.QueryBinary)
    _field(qtbot, dialog, "operator", lang.QueryBinaryOperator.NOT_EQUAL)
    _property_query(qtbot, dialog, ("validators", 0, "predicate", "left"))
    _kind(qtbot, dialog, ("validators", 0, "predicate", "right"), lang.QueryLiteral)
    # One generated function for each root Book; output is a query over that object.
    _kind(qtbot, dialog, ("transformations",), lang.AuthoredTransformation, add=True)
    _kind(qtbot, dialog, ("transformations", 0, "functions"), lang.FunctionTemplate, add=True)
    _select(qtbot, dialog, ("transformations", 0, "functions", 0, "source"))
    _field(qtbot, dialog, "concept_id", "fsm:state")
    _kind(
        qtbot, dialog, ("transformations", 0, "functions", 0, "body"), lang.TemplateOutput, add=True
    )
    expression = ("transformations", 0, "functions", 0, "body", 0, "value")
    _kind(qtbot, dialog, expression, lang.RuntimeLiteral)
    _property_query(qtbot, dialog, (*expression, "query"))


def test_structured_language_editor_builds_notations_query_rules_and_function_template(qtbot):
    dialog = LanguageEditorDialog(_schema())
    qtbot.addWidget(dialog)
    dialog.show()
    _author_language(qtbot, dialog)
    language = dialog.language()
    assert tuple(item.kind for item in language.notations) == (
        NotationKind.GRAPH,
        NotationKind.TABLE,
        NotationKind.TREE_FORM,
    )
    assert language.notations[1].columns[0].field.property_id == "fsm:state:name"
    rule = language.validators[0]
    assert isinstance(rule.predicate, lang.QueryBinary)
    assert rule.predicate.left.source.binding_id == rule.binding_id
    function = language.transformations[0].functions[0]
    assert function.body[0].value.query.source.binding_id == function.binding_id
    from code_visualizer.domain.language_validation import validate_authored_language

    assert validate_authored_language(language, _schema()) == ()
    dialog.close()


def test_workbench_language_edit_persists_previews_builds_and_undoes(qtbot, tmp_path):
    window, session = _window(qtbot, tmp_path)
    workbench = window.domain_workbench

    def author():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, LanguageEditorDialog)
        _author_language(qtbot, dialog)
        buttons = dialog.findChild(QDialogButtonBox)
        qtbot.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton
        )

    QTimer.singleShot(0, author)
    qtbot.mouseClick(
        workbench.findChild(QPushButton, "newDomainLanguage"), Qt.MouseButton.LeftButton
    )
    languages = session.authority.snapshot().domain_workspace.language_definitions
    assert len(languages) == 1, workbench.status.text()
    language = languages[0]
    for identifier in (
        language.id,
        language.notations[0].id,
        language.validators[0].id,
        language.transformations[0].definition.id,
        language.transformations[0].functions[0].body[0].value.query.id,
    ):
        window._reveal_semantic_id(identifier)
        assert workbench.tabs.currentWidget() is workbench.language_panel
        assert workbench.languages.currentItem().data(0, Qt.ItemDataRole.UserRole)[2] == identifier
        assert session.kernel.selection.state.primary == identifier
    table_notation = language.notations[1]
    workbench.notation_choice.setCurrentIndex(workbench.notation_choice.findData(table_notation.id))
    assert workbench.table.item(0, 1).text() == "Red"
    binding = workbench.table.item(0, 1).data(Qt.ItemDataRole.UserRole)
    assert binding.edit.node_id == "state:first"
    workbench.build_model()
    qtbot.waitUntil(lambda: workbench._generated is not None, timeout=10000)
    assert "Red" in workbench.code.toPlainText(), workbench.status.text()
    workbench.trace_model()
    qtbot.waitUntil(lambda: workbench.status.text() == "Red\n", timeout=15000)
    assert "Red" in workbench.status.text()
    original_output = language.transformations[0].functions[0].body[0]

    def change_transformation():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, LanguageEditorDialog)
        query_path = ("transformations", 0, "functions", 0, "body", 0, "value", "query")
        _kind(qtbot, dialog, query_path, lang.QueryLiteral)
        literal = dialog.findChild(QLineEdit, "languageLiteralValue")
        literal.selectAll()
        qtbot.keyClicks(literal, "Changed by the language editor")
        buttons = dialog.findChild(QDialogButtonBox)
        qtbot.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton
        )

    QTimer.singleShot(0, change_transformation)
    workbench.edit_language()
    edited_language = session.authority.snapshot().domain_workspace.language_definitions[0]
    assert edited_language.transformations[0].functions[0].body[0].id == original_output.id
    workbench.trace_model()
    try:
        qtbot.waitUntil(
            lambda: workbench.status.text() == "Changed by the language editor\n", timeout=15000
        )
    except QtTimeoutError as exc:
        raise AssertionError(workbench.status.text()) from exc
    assert workbench.status.text() == "Changed by the language editor\n"
    assert (
        session.authority.snapshot().domain_workspace.node("state:first").property("fsm:state:name")
        == "Red"
    )
    workbench.undo()
    assert session.authority.snapshot().domain_workspace.language_definitions == languages
    workbench.redo()
    languages = session.authority.snapshot().domain_workspace.language_definitions
    stored = tmp_path / "saved"
    session.save_as(stored)
    reopened = ProjectSession.open(stored, read_only=True)
    try:
        assert reopened.authority.snapshot().domain_workspace.language_definitions == languages
    finally:
        reopened.close()
    before = session.authority.snapshot().domain_workspace
    workbench.tabs.setCurrentWidget(workbench.language_panel)
    workbench.delete_language()
    assert session.authority.snapshot().domain_workspace.language_definitions == ()
    workbench.undo()
    assert session.authority.snapshot().domain_workspace == before
    window.close()


def test_editor_keeps_ids_when_renaming_symbols_and_scopes_query_bindings(qtbot):
    dialog = LanguageEditorDialog(_schema())
    qtbot.addWidget(dialog)
    dialog.show()
    _kind(qtbot, dialog, ("transformations",), lang.AuthoredTransformation, add=True)
    prefix = ("transformations", 0, "functions")
    _kind(qtbot, dialog, prefix, lang.FunctionTemplate, add=True)
    _kind(qtbot, dialog, (*prefix, 0, "symbols"), lang.TemplateSymbol, add=True)
    _field(qtbot, dialog, "name", "counter")
    identity = dialog.language().transformations[0].functions[0].symbols[0].id
    _kind(qtbot, dialog, (*prefix, 0, "body"), lang.TemplateAssignment, add=True)
    _kind(qtbot, dialog, (*prefix, 0, "body", 0, "value"), lang.RuntimeVariable)
    assert dialog.language().transformations[0].functions[0].body[0].value.symbol_id == identity
    _select(qtbot, dialog, (*prefix, 0, "symbols", 0))
    _field(qtbot, dialog, "name", "renamed_counter")
    function = dialog.language().transformations[0].functions[0]
    assert function.symbols[0].id == identity
    assert function.body[0].symbol_id == identity
    _kind(qtbot, dialog, (*prefix, 0, "source"), lang.QueryVariable)
    assert dialog.findChild(QComboBox, "languageField:binding_id").count() == 1
    assert dialog.findChild(QComboBox, "languageField:binding_id").currentData() == ""
    dialog.close()


def test_full_traffic_light_loop_can_be_reauthored_in_ui_without_fsm_implementation(qtbot):
    from fixtures.editor_worker_fixture import fixture_registry, worker_profile

    from code_visualizer.application.computation_service import ComputationService

    project = authored_traffic_light_project()
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="authored-fsm-ui")
    host = ComputationService(profiles=(worker_profile(),))
    kernel = ProjectKernel(authority, extensions=fixture_registry(), computations=host)
    workbench = DomainWorkbenchWidget()
    qtbot.addWidget(workbench)
    workbench.resize(1100, 760)
    workbench.show()
    workbench.attach(kernel, client)
    try:
        workbench.trace_model()
        qtbot.waitUntil(lambda: workbench.status.text().startswith("Green\n"), timeout=15000)
        assert workbench.status.text().splitlines() == [
            "Green",
            "The signal changes.",
            "Yellow",
            "The signal changes.",
            "Red",
            "The signal changes.",
        ]
        assert any(state.detail == "'traffic:red'" for state in kernel.runtime.history())

        def change_loop():
            dialog = QApplication.activeModalWidget()
            assert isinstance(dialog, LanguageEditorDialog)
            pending = [dialog.tree.topLevelItem(0)]
            while pending:
                item = pending.pop()
                if item.toolTip(0) == "recipe:event-loop":
                    path = item.data(0, Qt.ItemDataRole.UserRole)
                    break
                pending.extend(item.child(index) for index in range(item.childCount()))
            else:
                raise AssertionError("Event loop recipe is not discoverable in the editor")
            _kind(qtbot, dialog, (*path, "iterable", "right", "query"), lang.QueryLiteral)
            kind = dialog.findChild(QComboBox, "languageLiteralType")
            kind.setCurrentIndex(kind.findData("int"))
            literal = dialog.findChild(QLineEdit, "languageLiteralValue")
            qtbot.keyClicks(literal, "1")
            buttons = dialog.findChild(QDialogButtonBox)
            qtbot.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save), Qt.MouseButton.LeftButton
            )

        QTimer.singleShot(0, change_loop)
        workbench.edit_language()
        edited = authority.snapshot()
        assert edited.domain_workspace.models == project.domain_workspace.models
        assert (
            edited.domain_workspace.language_definitions
            != project.domain_workspace.language_definitions
        )
        workbench.trace_model()
        qtbot.waitUntil(
            lambda: workbench.status.text() == "Green\nThe signal changes.\n", timeout=15000
        )
        assert workbench.status.text().splitlines() == [
            "Green",
            "The signal changes.",
        ]
        assert any(state.detail == "'traffic:green'" for state in kernel.runtime.history())
        assert authority.snapshot().program_model.functions == ()
        assert any("traffic:green" in state.origin_ids for state in kernel.runtime.history())
        workbench.undo()
        assert authority.snapshot().domain_workspace == project.domain_workspace
    finally:
        workbench.attach(None, None)
        workbench.close()
        kernel.close()
        host.close()
        client.close()
