"""Visible Python Project workspace; no magic property delimiters."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.commands import ConfigureProgram, ConfigurePythonRuntime
from code_visualizer.application.features.program.ownership import (
    attach_function,
    remove_function_reference,
    update_owner,
)
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.program_model import effective_program_model
from code_visualizer.application.python_authoring import (
    ConstantSpec,
    ImportSpec,
    PythonModuleDraft,
    TypeAliasSpec,
    apply_module_draft,
    edit_declaration_text,
    module_draft,
)
from code_visualizer.domain.common import new_id
from code_visualizer.domain.invocation_arguments import (
    configured_arguments_from_text,
    render_invocation_arguments,
)
from code_visualizer.domain.module_paths import (
    PythonPathError,
    canonical_module_path,
    canonical_package_path,
    module_file_label,
    python_module_file_path,
)
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAction,
    ProgramClass,
    ProgramEntryPoint,
    ProgramExpression,
    ProgramModel,
    ProgramModule,
    iter_program_nodes,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import ProgramModuleKind
from code_visualizer.domain.project import (
    EnvironmentVariable,
    Project,
    PythonRuntimeSettings,
    RunProfile,
)
from code_visualizer.sdk import CodeVisualizerClient


def _table(headers: tuple[str, ...], name: str) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setObjectName(name)
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return table


def _set_rows(table: QTableWidget, rows: tuple[tuple[str, ...], ...]) -> None:
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(value))


def _rows(table: QTableWidget) -> tuple[tuple[str, ...], ...]:
    result: list[tuple[str, ...]] = []
    for row in range(table.rowCount()):
        values_list: list[str] = []
        for column in range(table.columnCount()):
            item = table.item(row, column)
            values_list.append(item.text().strip() if item is not None else "")
        values = tuple(values_list)
        if any(values):
            result.append(values)
    return tuple(result)


def _table_with_buttons(
    table: QTableWidget,
    *,
    add_label: str,
) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    buttons = QHBoxLayout()
    add = QPushButton(add_label)
    remove = QPushButton("Remove selected")
    add.clicked.connect(lambda: table.insertRow(table.rowCount()))

    def remove_selected() -> None:
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)

    remove.clicked.connect(remove_selected)
    buttons.addWidget(add)
    buttons.addWidget(remove)
    buttons.addStretch(1)
    layout.addLayout(buttons)
    layout.addWidget(table)
    return widget


class PythonProjectWidget(QWidget):
    projectChanged = Signal()

    def __init__(
        self,
        client: CodeVisualizerClient,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("pythonProjectWorkspace")
        self.setAccessibleName("Python Project workspace")
        self._client = client
        self._loading = False
        self._current_module_row = -1
        self._modules: list[PythonModuleDraft] = []
        self._source_id: str | None = None
        self._class_id: str | None = None
        self._draft_revision = client.snapshot().revision

        heading = QLabel("Python Project")
        heading.setObjectName("pythonProjectHeading")
        explanation = QLabel(
            "Compose a real Python package tree. Dotted paths such as math.vectors (or the "
            "filesystem form math/vectors.py) become nested folders shared by the project "
            "explorer, generated code, graph exports, live tests, and disk generation."
        )
        explanation.setWordWrap(True)

        self.package = QLineEdit()
        self.package.setObjectName("packagePath")
        self.package.setPlaceholderText("bci, company.product, or company/product")
        package_form = QFormLayout()
        package_form.addRow("Generated package:", self.package)

        self.module_list = QListWidget()
        self.module_list.setObjectName("configuredModules")
        self.module_list.setAccessibleName("Configured Python modules")
        self.add_module = QPushButton("Add module")
        self.remove_module = QPushButton("Remove module")
        self.add_package = QPushButton("Add package initializer")
        self.add_package.setObjectName("addPythonPackage")
        self.add_package.clicked.connect(self._add_package)
        self.add_module.clicked.connect(self._add_module)
        self.remove_module.clicked.connect(self._remove_module)
        module_sidebar = QWidget()
        module_sidebar_layout = QVBoxLayout(module_sidebar)
        module_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        module_sidebar_layout.addWidget(QLabel("Output modules"))
        module_sidebar_layout.addWidget(self.module_list, 1)
        module_sidebar_layout.addWidget(self.add_module)
        module_sidebar_layout.addWidget(self.add_package)
        module_sidebar_layout.addWidget(self.remove_module)

        self.module_path = QLineEdit()
        self.module_path.setObjectName("modulePath")
        self.module_path.setPlaceholderText("math.vectors or math/vectors.py")
        self.module_kind = QComboBox()
        self.module_kind.setObjectName("pythonModuleKind")
        self.module_kind.addItem("Module (.py)", ProgramModuleKind.MODULE.value)
        self.module_kind.addItem(
            "Package initializer (__init__.py)", ProgramModuleKind.PACKAGE.value
        )
        self.module_kind.currentIndexChanged.connect(self._update_output_preview)
        self.module_output_path = QLabel()
        self.module_output_path.setObjectName("moduleOutputPath")
        self.module_output_path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.module_docstring = QPlainTextEdit()
        self.module_docstring.setObjectName("moduleDocstring")
        self.module_docstring.setPlaceholderText("Optional module docstring")
        self.module_docstring.setMaximumHeight(90)
        basics = QWidget()
        basics_form = QFormLayout(basics)
        basics_form.addRow("Kind:", self.module_kind)
        basics_form.addRow("Module / folder path:", self.module_path)
        basics_form.addRow("Generated file:", self.module_output_path)
        basics_form.addRow("Docstring:", self.module_docstring)

        self.imports = _table(("Module", "Imported name", "Alias"), "moduleImports")
        imports = _table_with_buttons(self.imports, add_label="Add import")
        self.constants = _table(("Name", "Annotation", "Expression"), "moduleConstants")
        constants = _table_with_buttons(self.constants, add_label="Add constant")
        self.type_aliases = _table(("Name", "Type expression"), "moduleTypeAliases")
        aliases = _table_with_buttons(self.type_aliases, add_label="Add type alias")

        self.declarations = QPlainTextEdit()
        self.declarations.setObjectName("moduleDeclarations")
        self.declarations.setPlaceholderText("Helper functions, classes, and advanced declarations")
        self.source_unit = QComboBox()
        self.source_unit.setObjectName("moduleSourceUnit")
        self.source_unit.currentIndexChanged.connect(self._source_changed)
        self.source_owner = QComboBox()
        self.source_owner.setObjectName("sourceUnitOwner")
        self.source_position = QComboBox()
        self.source_position.setObjectName("sourceUnitPosition")
        self.source_position.addItem("Before existing declarations", "first")
        self.source_position.addItem("After existing declarations", "last")
        source_add = QPushButton("Add source unit")
        source_add.setObjectName("addModuleSourceUnit")
        source_add.clicked.connect(self._add_source_unit)
        source_tabs = QWidget()
        source_layout = QVBoxLayout(source_tabs)
        source_layout.addWidget(QLabel("Edit one canonical source unit by its stable identity."))
        source_layout.addWidget(self.source_unit)
        source_layout.addWidget(QLabel("Owner for a new source unit:"))
        source_layout.addWidget(self.source_owner)
        source_layout.addWidget(self.source_position)
        source_layout.addWidget(source_add)
        source_buttons = QHBoxLayout()
        for label, delta in (("Move earlier", -1), ("Move later", 1), ("Remove unit", None)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, step=delta: self._move_source_unit(step))
            source_buttons.addWidget(button)
        source_layout.addLayout(source_buttons)
        source_layout.addWidget(self.declarations)

        self.classes = QComboBox()
        self.classes.setObjectName("moduleClasses")
        self.classes.currentIndexChanged.connect(self._class_changed)
        self.class_identifier = QLineEdit()
        self.class_identifier.setObjectName("programClassIdentifier")
        self.class_arguments = QLineEdit()
        self.class_arguments.setObjectName("programClassArguments")
        self.class_docstring = QPlainTextEdit()
        self.class_docstring.setObjectName("programClassDocstring")
        class_add = QPushButton("Add class")
        class_add.setObjectName("addProgramClass")
        class_add.clicked.connect(self._add_class)
        class_panel = QWidget()
        class_form = QFormLayout(class_panel)
        class_form.addRow("Class:", self.classes)
        class_form.addRow("Name:", self.class_identifier)
        class_form.addRow("Bases / metaclass:", self.class_arguments)
        class_form.addRow("Docstring:", self.class_docstring)
        class_form.addRow(class_add)

        module_tabs = QTabWidget()
        module_tabs.setObjectName("moduleCompositionTabs")
        module_tabs.addTab(basics, "Module")
        module_tabs.addTab(imports, "Imports")
        module_tabs.addTab(constants, "Constants")
        module_tabs.addTab(aliases, "Type aliases")
        module_tabs.addTab(source_tabs, "Source units")
        module_tabs.addTab(class_panel, "Classes")

        module_splitter = QSplitter(Qt.Orientation.Horizontal)
        module_splitter.addWidget(module_sidebar)
        module_splitter.addWidget(module_tabs)
        module_splitter.setStretchFactor(0, 0)
        module_splitter.setStretchFactor(1, 1)

        self.function_modules = _table(
            ("Projection", "Python callable", "Generated module"),
            "functionModuleAssignments",
        )
        self.function_modules.setAccessibleName("Function to module assignments")
        self.entrypoint = QComboBox()
        self.entrypoint.setObjectName("entrypointDiagram")
        self.entrypoint_arguments = QLineEdit()
        self.entrypoint_arguments.setObjectName("entrypointArguments")
        self.entrypoint_arguments.setPlaceholderText(
            'Literal values only: 7, label="ready", events=["timer"]'
        )
        self.post_source = QPlainTextEdit()
        self.post_source.setObjectName("postSource")
        self.post_source.setPlaceholderText("Explicit post-source / launcher declarations")
        self.post_source.setMaximumHeight(100)

        composition = QWidget()
        composition_layout = QVBoxLayout(composition)
        entry_form = QFormLayout()
        entry_form.addRow("Entry-point callable:", self.entrypoint)
        entry_form.addRow("Entry-point arguments:", self.entrypoint_arguments)
        composition_layout.addWidget(QLabel("Function ownership"))
        composition_layout.addWidget(self.function_modules)
        composition_layout.addLayout(entry_form)
        composition_layout.addWidget(QLabel("Post-source / main block"))
        composition_layout.addWidget(self.post_source)

        self.profile_name = QLineEdit()
        self.profile_name.setObjectName("runProfileName")
        self.interpreter = QLineEdit()
        self.interpreter.setObjectName("pythonInterpreter")
        self.interpreter.setPlaceholderText("Blank uses the Code Visualizer interpreter")
        self.working_directory = QLineEdit()
        self.working_directory.setObjectName("runWorkingDirectory")
        self.run_arguments = QLineEdit()
        self.run_arguments.setObjectName("runProfileArguments")
        self.environment = _table(("Variable", "Value"), "runEnvironment")
        environment = _table_with_buttons(self.environment, add_label="Add environment variable")
        run_profile = QWidget()
        run_layout = QVBoxLayout(run_profile)
        run_form = QFormLayout()
        run_form.addRow("Profile name:", self.profile_name)
        run_form.addRow("Interpreter:", self.interpreter)
        run_form.addRow("Working directory:", self.working_directory)
        run_form.addRow("Command arguments:", self.run_arguments)
        run_layout.addLayout(run_form)
        run_layout.addWidget(QLabel("Environment variables"))
        run_layout.addWidget(environment)

        project_tabs = QTabWidget()
        self.project_tabs = project_tabs
        project_tabs.setObjectName("projectPythonSetupTabs")
        project_tabs.addTab(module_splitter, "Modules")
        project_tabs.addTab(composition, "Functions & entry point")
        project_tabs.addTab(run_profile, "Run profile")

        self.message = QLabel()
        self.message.setObjectName("pythonProjectMessage")
        self.message.setWordWrap(True)
        self.apply_button = QPushButton("Apply Python Project")
        self.apply_button.setObjectName("applyPythonProject")
        self.apply_button.clicked.connect(self.apply_changes)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(explanation)
        layout.addLayout(package_form)
        layout.addWidget(project_tabs, 1)
        layout.addWidget(self.message)
        layout.addWidget(self.apply_button)

        self.module_list.currentRowChanged.connect(self._module_row_changed)
        self.module_path.textChanged.connect(self._update_output_preview)
        self.package.textChanged.connect(self._update_output_preview)
        self.refresh(client.snapshot())

    def refresh(self, project: Project) -> None:
        current_module_id = (
            self._modules[self._current_module_row].module.id
            if 0 <= self._current_module_row < len(self._modules)
            else None
        )
        self._loading = True
        setup = project.runtime_settings
        self._draft_revision = project.revision
        self.package.setText(project.program_model.package)
        self._modules = [module_draft(item) for item in project.program_model.modules]
        self.module_list.clear()
        for module in self._modules:
            module_item = QListWidgetItem(module_file_label(module.path, kind=module.module.kind))
            module_item.setToolTip(module.path)
            self.module_list.addItem(module_item)
        self._current_module_row = -1
        if self._modules:
            selected_row = next(
                (
                    index
                    for index, draft in enumerate(self._modules)
                    if draft.module.id == current_module_id
                ),
                0,
            )
            self.module_list.setCurrentRow(selected_row)
            self._load_module(selected_row)
            self._current_module_row = selected_row

        model = effective_program_model(project)
        documents = {item.id: item for item in project.documents}
        views = {item.function_id: item for item in project.drakon_views}
        self.function_modules.setRowCount(len(model.functions))
        self.entrypoint.clear()
        self.entrypoint.addItem("No entry point", None)
        selected_entry = 0
        for row, function in enumerate(model.functions):
            view = views.get(function.id)
            document = documents.get(view.document_id) if view is not None else None
            values = (
                document.title if document is not None else "Semantic only",
                function.identifier,
                model.module_path_for(function.id),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column < 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item.setData(Qt.ItemDataRole.UserRole, function.id)
                self.function_modules.setItem(row, column, item)
            self.entrypoint.addItem(
                f"{function.identifier}() — {model.module_path_for(function.id)}",
                function.id,
            )
            if function.id == model.entrypoint_callable_id:
                selected_entry = row + 1
        self.entrypoint.setCurrentIndex(selected_entry)
        self.entrypoint_arguments.setText(render_invocation_arguments(model.entrypoint_arguments))
        entrypoint = model.entrypoint
        self._startup = entrypoint.startup if entrypoint is not None else ()
        self._startup_action = next(
            (item for item in self._startup if isinstance(item, ProgramAction)), None
        )
        self._startup_source = (
            self._startup_action.source.source if self._startup_action is not None else ""
        )
        self.post_source.setPlainText(self._startup_source)

        profile = next(
            (item for item in setup.run_profiles if item.name == setup.active_run_profile),
            setup.run_profiles[0] if setup.run_profiles else RunProfile(),
        )
        self.profile_name.setText(profile.name)
        self.interpreter.setText(profile.interpreter)
        self.working_directory.setText(profile.working_directory)
        self.run_arguments.setText(profile.arguments)
        _set_rows(
            self.environment,
            tuple((item.name, item.value) for item in profile.environment),
        )
        if not self.message.text().startswith("Applied at revision"):
            self.message.setText(f"Editing revision {project.revision}")
        self._loading = False
        self._update_output_preview()

    def apply_changes(self) -> None:
        if self._loading:
            return
        self._store_current_module()
        project = self._client.snapshot()
        profile_name = self.profile_name.text().strip() or "Default"
        profile = RunProfile(
            name=profile_name,
            interpreter=self.interpreter.text().strip(),
            working_directory=self.working_directory.text().strip() or ".",
            arguments=self.run_arguments.text(),
            environment=tuple(
                EnvironmentVariable(name, value) for name, value in _rows(self.environment)
            ),
        )
        setup = PythonRuntimeSettings(run_profiles=(profile,), active_run_profile=profile_name)
        model = replace(
            project.program_model,
            package=canonical_package_path(self.package.text()),
            modules=tuple(apply_module_draft(item) for item in self._modules),
        )
        for row in range(self.function_modules.rowCount()):
            function_item = self.function_modules.item(row, 0)
            module_item = self.function_modules.item(row, 2)
            if function_item is None or module_item is None:
                continue
            function_id = function_item.data(Qt.ItemDataRole.UserRole)
            path_text = module_item.text().strip()
            path = canonical_module_path(path_text) if path_text else ""
            if not isinstance(function_id, str) or path == project.program_model.module_path_for(
                function_id
            ):
                continue
            destination = next((item for item in model.modules if item.path == path), None)
            if destination is None:
                self.message.setText(
                    f"Module {path!r} does not exist; create it before assigning a function."
                )
                return
            model = attach_function(
                remove_function_reference(model, function_id), function_id, destination.id
            )
        startup = self._startup
        if self.post_source.toPlainText() != self._startup_source:
            identity = (
                self._startup_action.id if self._startup_action is not None else new_id("startup")
            )
            action = ProgramAction(
                identity,
                make_program_expression(
                    identity, "source", self.post_source.toPlainText(), ExpressionRole.STATEMENTS
                ),
            )
            startup = (
                tuple(action if item is self._startup_action else item for item in startup)
                if self._startup_action is not None
                else (*startup, action)
            )
        current_entrypoint = model.entrypoint
        entrypoint = ProgramEntryPoint(
            current_entrypoint.id if current_entrypoint is not None else new_id("entrypoint"),
            self.entrypoint.currentData(),
            configured_arguments_from_text(self.entrypoint_arguments.text()),
            startup,
        )
        result = self._client.transaction(
            (
                ConfigureProgram(model.package, model.modules, entrypoint),
                ConfigurePythonRuntime(setup),
            ),
            expected_revision=self._draft_revision,
            intent="Edit canonical Python modules and runtime configuration",
        )
        if isinstance(result, CommandAccepted):
            self._draft_revision = result.revision
            self.projectChanged.emit()
            self.message.setText(f"Applied at revision {result.revision}")
        else:
            self.message.setText(f"Could not apply: {result.code} — {result.message}")

    def _module_row_changed(self, row: int) -> None:
        if self._loading:
            return
        self._store_current_module()
        self._load_module(row)
        self._current_module_row = row

    @staticmethod
    def _identified_rows(table: QTableWidget) -> tuple[tuple[tuple[str, ...], str], ...]:
        result = []
        for row in range(table.rowCount()):
            values = tuple(
                cell.text().strip() if (cell := table.item(row, column)) is not None else ""
                for column in range(table.columnCount())
            )
            if any(values):
                first = table.item(row, 0)
                identity = first.data(Qt.ItemDataRole.UserRole) if first is not None else None
                result.append((values, identity if isinstance(identity, str) else ""))
        return tuple(result)

    def _store_source(self) -> None:
        row = self._current_module_row
        if self._loading or row < 0 or row >= len(self._modules) or self._source_id is None:
            return
        draft = self._modules[row]
        model = ProgramModel(modules=(draft.module,))
        updated = edit_declaration_text(
            model, self._source_id, "source", self.declarations.toPlainText()
        )
        self._modules[row] = replace(draft, module=updated.modules[0])

    def _store_class(self) -> None:
        row = self._current_module_row
        if self._loading or row < 0 or row >= len(self._modules) or self._class_id is None:
            return
        draft = self._modules[row]
        model = ProgramModel(modules=(draft.module,))
        declaration = model.class_(self._class_id)
        if declaration is None:
            return
        owner = model.owner_of(declaration.id)
        assert owner is not None
        source = self.class_arguments.text().strip()
        arguments = declaration.arguments
        if source != (arguments.source if arguments is not None else ""):
            arguments = (
                make_program_expression(
                    declaration.id, "arguments", source, ExpressionRole.ARGUMENTS
                )
                if source
                else None
            )
        declaration = replace(
            declaration,
            identifier=self.class_identifier.text().strip(),
            arguments=arguments,
            docstring=self.class_docstring.toPlainText() or None,
        )
        updated = update_owner(
            model,
            owner.id,
            lambda body: tuple(
                declaration
                if isinstance(item, ProgramClass) and item.id == declaration.id
                else item
                for item in body
            ),
        )
        self._modules[row] = replace(draft, module=updated.modules[0])

    def _store_current_module(self) -> None:
        row = self._current_module_row
        if self._loading or row < 0 or row >= len(self._modules):
            return
        self._store_source()
        self._store_class()
        old = self._modules[row]
        kind = ProgramModuleKind(self.module_kind.currentData())
        path = canonical_module_path(self.module_path.text(), kind=kind)
        self._modules[row] = PythonModuleDraft(
            replace(
                old.module, path=path, kind=kind, docstring=self.module_docstring.toPlainText()
            ),
            imports=tuple(
                ImportSpec(values[0], values[1] or None, values[2] or None, identity)
                for values, identity in self._identified_rows(self.imports)
            ),
            constants=tuple(
                ConstantSpec(values[0], values[2], values[1] or None, identity)
                for values, identity in self._identified_rows(self.constants)
            ),
            type_aliases=tuple(
                TypeAliasSpec(values[0], values[1], identity)
                for values, identity in self._identified_rows(self.type_aliases)
            ),
        )
        item = self.module_list.item(row)
        if item is not None:
            item.setText(module_file_label(path, kind=kind))
            item.setToolTip(path)

    def _load_module(self, row: int) -> None:
        if row < 0 or row >= len(self._modules):
            return
        loading = self._loading
        self._loading = True
        draft = self._modules[row]
        self._current_module_row = row
        self.module_path.setText(draft.path)
        self.module_kind.setCurrentIndex(self.module_kind.findData(draft.module.kind.value))
        self.module_docstring.setPlainText(draft.docstring)
        for table, records, values in (
            (
                self.imports,
                draft.imports,
                tuple((item.module, item.name or "", item.alias or "") for item in draft.imports),
            ),
            (
                self.constants,
                draft.constants,
                tuple(
                    (item.name, item.annotation or "", item.expression) for item in draft.constants
                ),
            ),
            (
                self.type_aliases,
                draft.type_aliases,
                tuple((item.name, item.expression) for item in draft.type_aliases),
            ),
        ):
            _set_rows(table, values)
            for index, record in enumerate(records):
                cell = table.item(index, 0)
                if cell is not None:
                    cell.setData(
                        Qt.ItemDataRole.UserRole,
                        cast(ImportSpec | ConstantSpec | TypeAliasSpec, record).id,
                    )
        self.source_unit.clear()
        previous_source_owner = self.source_owner.currentData()
        self.source_owner.clear()
        self.source_owner.addItem(f"Module {draft.path}", draft.module.id)
        for item in iter_program_nodes(draft.module):
            if isinstance(item, ProgramClass):
                self.source_owner.addItem(f"Class {item.identifier}", item.id)
            if isinstance(item, ProgramAction):
                self.source_unit.addItem(
                    item.source.source.splitlines()[0]
                    if item.source.source
                    else "Empty source unit",
                    item.source.id,
                )
        source_row = self.source_unit.findData(self._source_id)
        self.source_owner.setCurrentIndex(max(0, self.source_owner.findData(previous_source_owner)))
        self.source_unit.setCurrentIndex(max(0, source_row))
        self._source_id = self.source_unit.currentData()
        self.declarations.setEnabled(self._source_id is not None)
        selected = next(
            (
                item
                for item in iter_program_nodes(draft.module)
                if isinstance(item, ProgramExpression) and item.id == self._source_id
            ),
            None,
        )
        self.declarations.setPlainText(selected.source if selected is not None else "")
        self.classes.clear()
        for item in iter_program_nodes(draft.module):
            if isinstance(item, ProgramClass):
                self.classes.addItem(item.identifier, item.id)
        class_row = self.classes.findData(self._class_id)
        self.classes.setCurrentIndex(max(0, class_row))
        self._class_id = self.classes.currentData()
        self._load_class_fields()
        self._loading = loading
        self._update_output_preview()

    def _source_changed(self, _index: int) -> None:
        if self._loading:
            return
        self._store_source()
        self._source_id = self.source_unit.currentData()
        row = self._current_module_row
        if row < 0:
            return
        selected = next(
            (
                item
                for item in iter_program_nodes(self._modules[row].module)
                if isinstance(item, ProgramExpression) and item.id == self._source_id
            ),
            None,
        )
        self.declarations.setEnabled(selected is not None)
        self.declarations.setPlainText(selected.source if selected is not None else "")

    def _load_class_fields(self) -> None:
        row = self._current_module_row
        selected = (
            next(
                (
                    item
                    for item in iter_program_nodes(self._modules[row].module)
                    if isinstance(item, ProgramClass) and item.id == self._class_id
                ),
                None,
            )
            if row >= 0
            else None
        )
        self.class_identifier.setText(selected.identifier if selected is not None else "")
        self.class_arguments.setText(
            selected.arguments.source
            if selected is not None and selected.arguments is not None
            else ""
        )
        self.class_docstring.setPlainText(selected.docstring or "" if selected is not None else "")
        for widget in (self.class_identifier, self.class_arguments, self.class_docstring):
            widget.setEnabled(selected is not None)

    def _class_changed(self, _index: int) -> None:
        if self._loading:
            return
        self._store_class()
        self._class_id = self.classes.currentData()
        self._load_class_fields()

    def _add_class(self) -> None:
        self._store_current_module()
        row = self._current_module_row
        if row < 0:
            return
        draft = self._modules[row]
        declaration = ProgramClass(new_id("class"), f"NewClass{self.classes.count() + 1}")
        self._modules[row] = replace(
            draft, module=replace(draft.module, body=(*draft.module.body, declaration))
        )
        self._load_module(row)
        self.classes.setCurrentIndex(self.classes.findData(declaration.id))

    def _add_source_unit(self) -> None:
        self._store_current_module()
        row = self._current_module_row
        if row < 0:
            return
        draft = self._modules[row]
        identity = new_id("source")
        action = ProgramAction(
            identity, make_program_expression(identity, "source", "pass", ExpressionRole.STATEMENTS)
        )
        owner_id = self.source_owner.currentData() or draft.module.id
        updated = update_owner(
            ProgramModel(modules=(draft.module,)),
            owner_id,
            lambda body: (
                (*body, action) if self.source_position.currentData() == "last" else (action, *body)
            ),
        )
        self._modules[row] = replace(draft, module=updated.modules[0])
        self._load_module(row)
        self.source_unit.setCurrentIndex(self.source_unit.findData(action.source.id))

    def _move_source_unit(self, delta: int | None) -> None:
        self._store_current_module()
        row = self._current_module_row
        if row < 0 or self._source_id is None:
            return
        draft = self._modules[row]
        model = ProgramModel(modules=(draft.module,))
        action = next(
            (
                item
                for item in iter_program_nodes(draft.module)
                if isinstance(item, ProgramAction) and item.source.id == self._source_id
            ),
            None,
        )
        owner = model.owner_of(action.id) if action is not None else None
        if owner is None or action is None:
            return
        items = list(owner.body)
        index = items.index(action)
        if delta is None:
            items.pop(index)
        else:
            destination = index + delta
            if not 0 <= destination < len(items):
                return
            items[index], items[destination] = items[destination], items[index]
        updated = update_owner(model, owner.id, lambda _body: tuple(items))
        self._modules[row] = replace(draft, module=updated.modules[0])
        self._load_module(row)

    def _add_module(self) -> None:
        self._store_current_module()
        existing = {module.path for module in self._modules}
        index = len(self._modules) + 1
        path = f"module_{index}"
        while path in existing:
            index += 1
            path = f"module_{index}"
        self._modules.append(module_draft(ProgramModule(new_id("module"), path)))
        item = QListWidgetItem(module_file_label(path))
        item.setToolTip(path)
        self.module_list.addItem(item)
        self.module_list.setCurrentRow(len(self._modules) - 1)

    def select_module(self, module_id: str) -> None:
        """Select a module activated from the filesystem-shaped project explorer."""

        row = next(
            (index for index, module in enumerate(self._modules) if module.module.id == module_id),
            -1,
        )
        if row >= 0:
            self.module_list.setCurrentRow(row)

    def _add_package(self) -> None:
        self._store_current_module()
        existing = {draft.path for draft in self._modules}
        path = ""
        index = 1
        while path in existing:
            path = f"package_{index}"
            index += 1
        module = ProgramModule(new_id("package"), path, kind=ProgramModuleKind.PACKAGE)
        self._modules.append(module_draft(module))
        self.module_list.addItem(QListWidgetItem(module_file_label(path, kind=module.kind)))
        self.module_list.setCurrentRow(len(self._modules) - 1)

    def _update_output_preview(self, _text: str = "") -> None:
        try:
            relative = python_module_file_path(
                self.package.text(),
                self.module_path.text(),
                kind=ProgramModuleKind(self.module_kind.currentData()),
            )
        except PythonPathError as exc:
            self.module_output_path.setText(f"Path needs repair: {exc}")
        else:
            self.module_output_path.setText(f"generated/{relative}")

    def _remove_module(self) -> None:
        row = self.module_list.currentRow()
        if row < 0 or len(self._modules) <= 1:
            self.message.setText("A project must keep at least one configured module.")
            return
        self._modules.pop(row)
        self._loading = True
        self.module_list.takeItem(row)
        self._loading = False
        next_row = min(row, len(self._modules) - 1)
        self._current_module_row = -1
        self.module_list.setCurrentRow(next_row)
        self._load_module(next_row)
        self._current_module_row = next_row
