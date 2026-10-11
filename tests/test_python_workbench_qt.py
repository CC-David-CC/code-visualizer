from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QTableWidgetItem, QTreeWidget, QTreeWidgetItem

from code_visualizer.application.messages import CommandAccepted, CommandEnvelope
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.program import ProgramAction, ProgramFunctionReference
from code_visualizer.domain.program_kinds import ProgramModuleKind
from code_visualizer.generation import inspect_generation
from code_visualizer.ui_qt.function_signature import FunctionSignatureEditor
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow
from code_visualizer.ui_qt.python_project import PythonProjectWidget


def _settings(path: Path) -> QSettings:
    return QSettings(str(path / "settings.ini"), QSettings.Format.IniFormat)


def _walk_tree(item: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
    yield item
    for index in range(item.childCount()):
        yield from _walk_tree(item.child(index))


def _item_with_data(tree: QTreeWidget, value: str) -> QTreeWidgetItem | None:
    for row in range(tree.topLevelItemCount()):
        match = next(
            (
                item
                for item in _walk_tree(tree.topLevelItem(row))
                if item.data(0, Qt.ItemDataRole.UserRole) == value
            ),
            None,
        )
        if match is not None:
            return match
    return None


def test_visible_module_setup_generates_reveals_traces_runs_and_blocks_bad_edit(
    qtbot, tmp_path
) -> None:
    root = tmp_path / "module-example"
    revealed: list[Path] = []
    window = MainWindow(
        path_chooser=lambda: root,
        folder_revealer=lambda path: not revealed.append(path),
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()

    window.welcome.examples.setCurrentRow(1)
    qtbot.keyClick(window.welcome.examples, Qt.Key.Key_Return)
    assert window.session is not None
    assert len(window.session.authority.snapshot().documents) == 2

    window.action_python_project.trigger()
    setup = window.documents.currentWidget()
    assert isinstance(setup, PythonProjectWidget)
    assert setup.package.text() == "studio_demo"
    setup.module_list.setCurrentRow(1)
    qtbot.wait(1)
    assert setup.module_path.text() == "helpers"
    setup.constants.setItem(0, 2, QTableWidgetItem('"Hello from visible setup!"'))
    qtbot.mouseClick(setup.apply_button, Qt.MouseButton.LeftButton)
    assert "Applied at revision" in setup.message.text()

    window.action_save.trigger()
    window.action_generate.trigger()
    qtbot.waitUntil(lambda: window.development.reveal_button.isEnabled())
    assert (root / "generated" / "studio_demo" / "main.py").is_file()
    assert (root / "generated" / "studio_demo" / "helpers.py").is_file()
    assert window.development.reveal_button.isEnabled()
    qtbot.mouseClick(window.development.reveal_button, Qt.MouseButton.LeftButton)
    assert revealed == [root / "generated"]

    window.documents.setCurrentIndex(0)
    window.action_trace_current.trigger()
    document = window.documents.currentWidget()
    qtbot.waitUntil(lambda: "--- mapped trace ---" in document.console.toPlainText(), timeout=15000)
    assert "--- mapped trace ---" in document.console.toPlainText()
    assert "Hello from visible setup!" in document.console.toPlainText()

    window.action_run.trigger()
    qtbot.waitUntil(lambda: window.run_output.toPlainText() == "Hello from visible setup!\n")

    project = window.session.authority.snapshot()
    main = project.documents[0]
    atom = main.body.atoms[0]
    window.session.client.set_drakon_text(main.id, atom.id, "source", "broken(")
    window.action_generate.trigger()
    qtbot.waitUntil(lambda: window.development.state_label.text() == "Blocked")
    assert window.development.state_label.text() == "Blocked"
    qtbot.mouseClick(window.development.reveal_button, Qt.MouseButton.LeftButton)
    assert revealed == [root / "generated"]
    assert window.development_tabs.currentWidget() is window.diagnostics
    diagnostic_code = window.diagnostics.topLevelItem(0).text(1)
    window.development.diagnostic_filter.setText(diagnostic_code)
    assert not window.diagnostics.topLevelItem(0).isHidden()
    window.development.diagnostic_filter.setText("no-such-diagnostic-token")
    assert all(
        window.diagnostics.topLevelItem(row).isHidden()
        for row in range(window.diagnostics.topLevelItemCount())
    )


def test_artifact_reveal_does_not_open_an_empty_or_unmanifested_folder(qtbot, tmp_path) -> None:
    root = tmp_path / "new-project"
    revealed: list[Path] = []
    window = MainWindow(
        path_chooser=lambda: root,
        folder_revealer=lambda path: not revealed.append(path),
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    window.reveal_generated_folder()

    assert revealed == []
    assert not (root / "generated").exists()
    assert window.development_tabs.currentWidget() is window.diagnostics


def test_nested_module_tree_links_graphs_setup_and_generated_artifacts(qtbot, tmp_path) -> None:
    root = tmp_path / "nested-instrument"
    window = MainWindow(
        path_chooser=lambda: root,
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window._open_example("computational_instrument")
    assert window.session is not None

    module_id = next(
        module.id
        for module in window.session.authority.snapshot().program_model.modules
        if module.path == "math.vectors"
    )
    module_item = _item_with_data(window.project_tree, f"__python_module__:{module_id}")
    assert module_item is not None
    labels: list[str] = []
    cursor: QTreeWidgetItem | None = module_item
    while cursor is not None:
        labels.append(cursor.text(0))
        cursor = cursor.parent()
    assert labels[:4] == ["vectors.py", "math/", "bci/", "generated/"]

    window.project_tree.setCurrentItem(module_item)
    qtbot.keyClick(window.project_tree, Qt.Key.Key_Return)
    setup = window.documents.currentWidget()
    assert isinstance(setup, PythonProjectWidget)
    assert setup.module_path.text() == "math.vectors"
    assert setup.module_output_path.text() == "generated/bci/math/vectors.py"

    window.project_tree.setCurrentItem(module_item)
    window.create_document(DocumentKind.DRAKON)
    project = window.session.authority.snapshot()
    created = project.documents[-1]
    assert created.header.function.module == "math.vectors"
    refreshed_module = _item_with_data(
        window.project_tree,
        f"__python_module__:{module_id}",
    )
    assert refreshed_module is not None
    created_item = _item_with_data(window.project_tree, created.id)
    assert created_item is not None and created_item.parent() is refreshed_module

    vector_diagram = next(
        document
        for document in project.documents
        if getattr(getattr(document, "header", None), "function", None) is not None
        and document.header.function.identifier == "add_vectors"
    )
    diagram_item = _item_with_data(window.project_tree, vector_diagram.id)
    assert diagram_item is not None
    assert diagram_item.parent() is refreshed_module
    window.project_tree.setCurrentItem(diagram_item)
    qtbot.keyClick(window.project_tree, Qt.Key.Key_Return)
    assert window.documents.currentWidget().diagram_id == vector_diagram.id

    window.action_save.trigger()
    window.action_generate.trigger()
    qtbot.waitUntil(
        lambda: _item_with_data(window.artifacts, "bci/math/vectors.py") is not None,
        timeout=15_000,
    )
    artifact = _item_with_data(window.artifacts, "bci/math/vectors.py")
    assert artifact is not None
    assert artifact.text(0) == "vectors.py"
    assert artifact.parent() is not None and artifact.parent().text(0) == "math/"
    graph = _item_with_data(
        window.artifacts,
        "diagrams/bci/math/vectors/add_vectors.svg",
    )
    assert graph is not None
    assert (root / "generated" / "project.graph-index.json").is_file()


def test_external_generated_edit_has_visible_diff_and_blocks_run_until_regeneration(
    qtbot, tmp_path
) -> None:
    root = tmp_path / "tamper-aware"
    window = MainWindow(
        path_chooser=lambda: root,
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    document = window.documents.currentWidget()
    document.insert_hello_world()
    window.action_save.trigger()
    window.action_generate.trigger()
    generated = root / "generated" / "app" / "main.py"
    qtbot.waitUntil(lambda: window.development.reveal_button.isEnabled())
    generated.write_text("print('external replacement')\n", encoding="utf-8")

    window.action_run.trigger()
    assert "changed externally" in window.statusBar().currentMessage()
    assert window.run_output.toPlainText() == ""
    assert window.development.artifact_inspection.modified == ("app/main.py",)
    item = _item_with_data(window.artifacts, "app/main.py")
    assert item is not None
    assert item.text(1) == "Modified"
    window.development._preview_item(item, 0)
    difference = window.development.artifact_diff.toPlainText()
    assert "external replacement" in difference
    assert "Hello, world!" in difference
    assert window.development_tabs.currentWidget() is window.development.artifact_diff

    window.action_generate.trigger()

    def regenerated() -> bool:
        assert window._pipeline.status.state.value not in {"failed", "blocked"}, (
            window._pipeline.status
        )
        if window._pipeline.status.state.value != "up_to_date":
            return False
        return generated.is_file() and "external replacement" not in generated.read_text(
            encoding="utf-8"
        )

    qtbot.waitUntil(
        regenerated,
        timeout=15_000,
    )
    assert "external replacement" not in generated.read_text(encoding="utf-8")
    assert inspect_generation(root, current_revision=window.session.authority.revision).clean


def test_class_form_and_canonical_only_function_remain_editable_without_a_diagram(qtbot, tmp_path):
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    project = window.session.authority.snapshot()
    function = project.program_model.functions[0]
    assert isinstance(
        window.session.authority.execute(
            CommandEnvelope(
                "diagram.delete",
                "test",
                "remove-projection",
                project.id,
                project.revision,
                {"diagram_id": project.documents[0].id},
            )
        ),
        CommandAccepted,
    )
    window._refresh_project()
    function_item = _item_with_data(window.project_tree, f"__program_function__:{function.id}")
    assert function_item is not None
    window._activate_project_item(function_item, 0)
    signature = window.documents.currentWidget()
    assert isinstance(signature, FunctionSignatureEditor)
    signature.display_name.setText("Canonical main")
    signature.apply()
    assert (
        window.session.authority.snapshot().program_model.function(function.id).display_name
        == "Canonical main"
    )
    assert not window.session.authority.snapshot().documents

    window.open_python_project()
    setup = window.documents.currentWidget()
    assert isinstance(setup, PythonProjectWidget)
    setup._add_class()
    class_id = setup.classes.currentData()
    setup.class_identifier.setText("Worker")
    setup.apply_changes()
    assert window.session.authority.snapshot().program_model.class_(class_id).identifier == "Worker"
    setup.class_identifier.setText("Runner")
    setup.apply_changes()
    assert window.session.authority.snapshot().program_model.class_(class_id).identifier == "Runner"
    assert _item_with_data(window.project_tree, f"__program_class__:{class_id}") is not None
    assert isinstance(window.session.client.undo(), CommandAccepted)
    assert window.session.authority.snapshot().program_model.class_(class_id).identifier == "Worker"


def test_source_units_edit_one_owner_and_keep_order_and_identity_through_history(qtbot, tmp_path):
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    window.open_python_project()
    setup = window.documents.currentWidget()
    assert isinstance(setup, PythonProjectWidget)
    setup._add_class()
    class_id = setup.classes.currentData()
    setup.class_identifier.setText("Worker")
    setup.apply_changes()
    module_id = window.session.authority.snapshot().program_model.modules[0].id

    assert setup.source_owner.currentData() == module_id
    setup._add_source_unit()
    module_source_id = setup.source_unit.currentData()
    setup.declarations.setPlainText("module_flag = 1")
    setup.apply_changes()
    first = window.session.authority.snapshot().program_model.module(module_id).body[0]
    assert isinstance(first, ProgramAction) and first.source.id == module_source_id
    setup._move_source_unit(1)
    setup.apply_changes()
    module = window.session.authority.snapshot().program_model.module(module_id)
    assert isinstance(module.body[0], ProgramFunctionReference)
    assert isinstance(module.body[1], ProgramAction)
    assert module.body[1].source.id == module_source_id

    setup.source_owner.setCurrentIndex(setup.source_owner.findData(class_id))
    setup._add_source_unit()
    class_source_id = setup.source_unit.currentData()
    setup.declarations.setPlainText("class_flag = 2")
    setup.apply_changes()
    authored = window.session.authority.snapshot().program_model
    class_action = authored.class_(class_id).body[0]
    assert isinstance(class_action, ProgramAction)
    assert class_action.source.id == class_source_id
    assert class_action.source.source == "class_flag = 2"
    assert authored.owner_of(class_action.id).id == class_id
    assert isinstance(window.session.client.undo(), CommandAccepted)
    assert not window.session.authority.snapshot().program_model.class_(class_id).body
    assert isinstance(window.session.client.redo(), CommandAccepted)
    assert window.session.authority.snapshot().program_model == authored


def test_python_project_authors_and_runs_root_package_initializer(qtbot, tmp_path):
    window = MainWindow(
        path_chooser=lambda: tmp_path / "package-project",
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=_settings(tmp_path),
    )
    qtbot.addWidget(window)
    window.show()
    window.action_new.trigger()
    assert window.session is not None
    window.action_python_project.trigger()
    editor = window.documents.currentWidget()
    assert isinstance(editor, PythonProjectWidget)
    assert editor.accessibleName() == "Python Project workspace"
    qtbot.mouseClick(editor.add_package, Qt.MouseButton.LeftButton)
    assert editor.module_kind.currentData() == ProgramModuleKind.PACKAGE.value
    assert editor.module_path.text() == ""
    assert editor.module_output_path.text() == "generated/app/__init__.py"
    editor._add_source_unit()
    editor.declarations.setPlainText("print('package initialized')")
    qtbot.mouseClick(editor.apply_button, Qt.MouseButton.LeftButton)
    assert "Applied at revision" in editor.message.text()
    model = window.session.authority.snapshot().program_model
    package = next(module for module in model.modules if module.kind is ProgramModuleKind.PACKAGE)
    assert package.path == ""
    assert _item_with_data(window.project_tree, f"__python_module__:{package.id}") is not None
    assert isinstance(window.session.client.undo(), CommandAccepted)
    assert all(
        module.id != package.id
        for module in window.session.authority.snapshot().program_model.modules
    )
    assert isinstance(window.session.client.redo(), CommandAccepted)
    assert window.session.authority.snapshot().program_model == model
    window.action_save.trigger()
    window.documents.setCurrentIndex(0)
    document = window.documents.currentWidget()
    qtbot.mouseClick(document.run_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: document.run_button.isEnabled(), timeout=10000)
    assert document.console.toPlainText() == "package initialized\n"
