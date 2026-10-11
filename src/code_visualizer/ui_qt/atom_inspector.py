"""Purpose-built, non-modal editor for typed DRAKON atom properties."""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import Any, cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.domain.common import new_id
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Case,
    ContextItem,
    Delay,
    DrakonAtom,
    ExceptionHandler,
    If,
    Input,
    Loop,
    Note,
    Output,
    Parallel,
    ParallelBranch,
    Period,
    RealtimeProcess,
    Select,
    Sequence,
    Silhouette,
    SilhouetteBranch,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    Try,
    With,
)

ATOM_ROLE = Qt.ItemDataRole.UserRole
MIXED_ROLE = Qt.ItemDataRole.UserRole + 1
MIXED_VALUE = "— multiple values —"


_FIELD_LABELS = {
    "annotation": "Type annotation",
    "arguments": "Linked call arguments",
    "asynchronous": "Async operation",
    "awaited": "Await result",
    "call": "Callable expression",
    "cause": "Raise from cause",
    "children": "TREE children function",
    "condition": "Condition / continuation test",
    "converter": "Input converter",
    "deadline": "Deadline seconds",
    "delay_seconds": "Retry delay seconds",
    "destination": "Output destination (file=)",
    "display_name": "Silhouette display name",
    "end": "Output terminator (end=)",
    "except_star": "Exception-group handlers (except*)",
    "expression": "Python expression",
    "identifier": "Silhouette Python identifier",
    "iterable": "Iterable / roots expression",
    "loop_kind": "Loop form",
    "mode": "Structured mode",
    "operator": "Assignment kind / operator",
    "placement": "Note placement",
    "preferred_on_time": "Preferred route is on-time",
    "preferred_truth": "Preferred downward route is True",
    "prompt": "Input prompt expression",
    "result_target": "Optional result target",
    "secondary": "Secondary expression / message",
    "seconds": "Duration / cadence seconds",
    "source": "Python statement / note text",
    "statement_kind": "Simple statement kind",
    "target": "Assignment / iteration target",
    "text": "Note text",
    "timer": "Timer identity",
    "transfer_kind": "Transfer kind",
    "value": "Value expression",
}


def _fields(atom: DrakonAtom) -> tuple[str, ...]:
    if isinstance(atom, Action):
        return ("source",)
    if isinstance(atom, Output):
        return ("expression", "destination", "end")
    if isinstance(atom, Assignment):
        return ("target", "operator", "annotation", "value")
    if isinstance(atom, Transfer):
        return ("transfer_kind", "expression", "cause")
    if isinstance(atom, SimpleStatement):
        return ("statement_kind", "source", "secondary")
    if isinstance(atom, Call):
        return ("expression", "arguments", "awaited", "result_target")
    if isinstance(atom, Input):
        return ("target", "annotation", "prompt", "converter")
    if isinstance(atom, Delay):
        return ("seconds", "asynchronous")
    if isinstance(atom, StartTimer):
        return ("timer",)
    if isinstance(atom, Period):
        return ("timer", "seconds", "asynchronous")
    if isinstance(atom, RealtimeProcess):
        return ("call", "awaited")
    if isinstance(atom, Note):
        return ("text", "placement")
    if isinstance(atom, If):
        return ("condition", "preferred_truth")
    if isinstance(atom, Select):
        return ("expression", "mode")
    if isinstance(atom, Loop):
        return ("loop_kind", "target", "iterable", "condition", "children", "delay_seconds")
    if isinstance(atom, With):
        return ("asynchronous",)
    if isinstance(atom, Try):
        return ("except_star",)
    if isinstance(atom, Synchronizer):
        return ("timer", "deadline", "preferred_on_time")
    if isinstance(atom, Parallel):
        return ("mode",)
    if isinstance(atom, Silhouette):
        return ("display_name", "identifier")


def _purpose(atom: DrakonAtom) -> str:
    descriptions: tuple[tuple[type[object], str], ...] = (
        (
            Assignment,
            "Shelf: the upper field names state being written; the lower field computes it.",
        ),
        (
            If,
            "If: truth labels and preferred route are independent; the preferred route stays down.",
        ),
        (Select, "Select: ordered adjacent Cases; exactly one final default route."),
        (
            Loop,
            "Loop: a typed boundary owns its body, optional else, and non-editable return route.",
        ),
        (With, "With: one or more context managers own a structured body."),
        (
            Try,
            "Try: structured handlers, optional else, and finally remain visible in the diagram.",
        ),
        (Synchronizer, "Synchronizer: compare one started monotonic timer with a deadline."),
        (Parallel, "Parallel: named process bodies join under a stated sync or async policy."),
        (
            Silhouette,
            "Silhouette: ordered named states end in explicit Address targets and one exit.",
        ),
    )
    return next(
        (description for atom_type, description in descriptions if isinstance(atom, atom_type)),
        f"{type(atom).__name__}: edit semantic Python fields; geometry remains derived.",
    )


class AtomInspector(QWidget):
    replacementRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("typedAtomInspector")
        self._atom: DrakonAtom | None = None
        self._atoms: tuple[DrakonAtom, ...] = ()
        self.purpose = QLabel("Select an operation to inspect its semantic fields.")
        self.purpose.setWordWrap(True)
        self.properties = QTableWidget(0, 2)
        self.properties.setObjectName("semanticPropertyTable")
        self.properties.setHorizontalHeaderLabels(("Semantic property", "Value"))
        self.properties.setWordWrap(True)
        self.properties.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.properties.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.properties.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.properties.verticalHeader().hide()
        self.properties.setMinimumSize(0, 0)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.members = QTableWidget()
        self.members.setObjectName("ownedMemberTable")
        self.members.horizontalHeader().setStretchLastSection(True)
        self.members.hide()

        self.add_member = QPushButton("Add")
        self.remove_member = QPushButton("Remove")
        self.move_up = QPushButton("Up")
        self.move_down = QPushButton("Down")
        self.add_member.clicked.connect(self._add_member)
        self.remove_member.clicked.connect(self._remove_member)
        self.move_up.clicked.connect(lambda: self._move_member(-1))
        self.move_down.clicked.connect(lambda: self._move_member(1))
        member_buttons = QHBoxLayout()
        for button in (self.add_member, self.remove_member, self.move_up, self.move_down):
            member_buttons.addWidget(button)

        self.apply_button = QPushButton("Apply semantic changes")
        self.apply_button.setObjectName("applySemanticProperties")
        self.apply_button.clicked.connect(self._apply)

        layout = QVBoxLayout(self)
        layout.addWidget(self.purpose)
        layout.addWidget(self.properties)
        layout.addWidget(self.members, 1)
        layout.addLayout(member_buttons)
        layout.addWidget(self.apply_button)
        self._set_member_controls(False)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.properties.resizeRowsToContents()

    def set_atom(self, atom: DrakonAtom) -> None:
        self.set_atoms((atom,))

    def set_atoms(self, atoms: tuple[DrakonAtom, ...]) -> None:
        """Inspect one atom or edit type-compatible fields shared by a selection."""

        if not atoms:
            self._atoms = ()
            self._atom = None
            self.purpose.setText("Select an operation to inspect its semantic fields.")
            self.properties.setRowCount(0)
            self.members.clear()
            self._set_member_controls(False)
            self.apply_button.setEnabled(False)
            return
        self._atoms = atoms
        self._atom = atoms[0]
        if len(atoms) == 1:
            self.purpose.setText(_purpose(atoms[0]))
        else:
            kinds = ", ".join(dict.fromkeys(type(atom).__name__ for atom in atoms))
            self.purpose.setText(
                f"{len(atoms)} operations selected ({kinds}). Change a common semantic "
                "property once to apply it to the complete selection; mixed values remain "
                "unchanged until edited."
            )
        candidate_fields = _fields(atoms[0])
        fields = tuple(
            field
            for field in candidate_fields
            if all(
                field in _fields(atom)
                and type(getattr(atom, field)) is type(getattr(atoms[0], field))
                for atom in atoms[1:]
            )
        )
        self.properties.setRowCount(len(fields))
        for row, field in enumerate(fields):
            label = QTableWidgetItem(_FIELD_LABELS.get(field, field.replace("_", " ").title()))
            label.setToolTip(label.text())
            label.setData(ATOM_ROLE, field)
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.properties.setItem(row, 0, label)
            values = tuple(getattr(atom, field) for atom in atoms)
            value = values[0]
            mixed = any(item != value for item in values[1:])
            label.setData(MIXED_ROLE, mixed)
            if isinstance(value, bool):
                combo = QComboBox()
                if mixed:
                    combo.addItem(MIXED_VALUE)
                combo.addItems(("Yes", "No"))
                combo.setCurrentText(MIXED_VALUE if mixed else "Yes" if value else "No")
                self.properties.setCellWidget(row, 1, combo)
            elif isinstance(value, StrEnum):
                combo = QComboBox()
                if mixed:
                    combo.addItem(MIXED_VALUE)
                combo.addItems(tuple(type(value)))
                combo.setCurrentText(MIXED_VALUE if mixed else value.value)
                self.properties.setCellWidget(row, 1, combo)
            else:
                self.properties.removeCellWidget(row, 1)
                item = QTableWidgetItem(
                    MIXED_VALUE if mixed else "" if value is None else str(value)
                )
                item.setToolTip(item.text())
                if mixed:
                    item.setToolTip("Mixed values. Leave unchanged to preserve each value.")
                self.properties.setItem(row, 1, item)
        if len(atoms) == 1:
            self._load_members(atoms[0])
        else:
            self.members.clear()
            self.members.setRowCount(0)
            self.members.setColumnCount(0)
            self._set_member_controls(False)
        self.apply_button.setEnabled(bool(fields))
        self.purpose.setToolTip(self.purpose.text())
        self.properties.resizeRowsToContents()

    def focus_field(self, field: str) -> None:
        for row in range(self.properties.rowCount()):
            item = self.properties.item(row, 0)
            if item is not None and item.data(ATOM_ROLE) == field:
                self.properties.selectRow(row)
                self.properties.scrollToItem(item)
                editor = self.properties.cellWidget(row, 1)
                if isinstance(editor, QComboBox):
                    editor.setFocus(Qt.FocusReason.OtherFocusReason)
                else:
                    value = self.properties.item(row, 1)
                    if value is not None:
                        self.properties.editItem(value)
                return

    def _set_member_controls(self, visible: bool) -> None:
        self.members.setVisible(visible)
        for button in (self.add_member, self.remove_member, self.move_up, self.move_down):
            button.setVisible(visible)

    def _load_members(self, atom: DrakonAtom) -> None:
        rows: list[tuple[object, tuple[str, ...]]] = []
        headers: tuple[str, ...] = ()
        if isinstance(atom, Select):
            headers = (
                "Case label",
                "Condition / pattern",
                "Guard",
                "Default",
                "Preferred",
            )
            rows = [
                (
                    case,
                    (
                        case.label,
                        case.pattern if atom.mode.value == "match" else case.condition,
                        case.guard or "",
                        "Yes" if case.is_default else "No",
                        "Yes" if case.id == atom.preferred_case_id else "No",
                    ),
                )
                for case in atom.cases
            ]
        elif isinstance(atom, With):
            headers = ("Context expression", "Optional as target")
            rows = [(item, (item.expression, item.target or "")) for item in atom.contexts]
        elif isinstance(atom, Try):
            headers = ("Exception type", "Optional name")
            rows = [(item, (item.exception, item.name or "")) for item in atom.handlers]
        elif isinstance(atom, Parallel):
            headers = ("Process name",)
            rows = [(item, (item.name,)) for item in atom.branches]
        elif isinstance(atom, Silhouette):
            headers = ("State name", "Address target", "Initial")
            names = {item.id: item.name for item in atom.branches}
            rows = [
                (
                    item,
                    (
                        item.name,
                        (
                            names.get(item.target_branch_id, "Finite exit")
                            if item.target_branch_id is not None
                            else "Finite exit"
                        ),
                        "Yes" if item.id == atom.initial_branch_id else "No",
                    ),
                )
                for item in atom.branches
            ]
        self._set_member_controls(bool(headers))
        self.members.clear()
        if not headers:
            self.members.setRowCount(0)
            self.members.setColumnCount(0)
            return
        self.members.setColumnCount(len(headers))
        self.members.setHorizontalHeaderLabels(headers)
        self.members.setRowCount(len(rows))
        for row, (semantic, values) in enumerate(rows):
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(ATOM_ROLE, semantic)
                self.members.setItem(row, column, item)

    def _property_values(self, atom: DrakonAtom) -> dict[str, object]:
        values: dict[str, object] = {}
        for row in range(self.properties.rowCount()):
            key_item = self.properties.item(row, 0)
            if key_item is None:
                continue
            field = key_item.data(ATOM_ROLE)
            if not isinstance(field, str):
                continue
            current = getattr(atom, field)
            mixed = bool(key_item.data(MIXED_ROLE))
            combo = self.properties.cellWidget(row, 1)
            if isinstance(combo, QComboBox):
                text = combo.currentText()
                if mixed and text == MIXED_VALUE:
                    continue
                if isinstance(current, bool):
                    values[field] = text == "Yes"
                else:
                    values[field] = type(current)(text)
            else:
                value_item = self.properties.item(row, 1)
                text = value_item.text() if value_item is not None else ""
                if mixed and text == MIXED_VALUE:
                    continue
                values[field] = None if current is None and not text else text
        return values

    def _member_text(self, row: int, column: int) -> str:
        item = self.members.item(row, column)
        return item.text().strip() if item is not None else ""

    def _member_semantic(self, row: int) -> object | None:
        item = self.members.item(row, 0)
        return item.data(ATOM_ROLE) if item is not None else None

    def _replacement_members(self, atom: DrakonAtom) -> DrakonAtom:
        if isinstance(atom, Select):
            cases: list[Case] = []
            preferred_case_id: str | None = None
            for row in range(self.members.rowCount()):
                original = self._member_semantic(row)
                if not isinstance(original, Case):
                    continue
                cases.append(
                    replace(
                        original,
                        label=self._member_text(row, 0),
                        condition=self._member_text(row, 1),
                        pattern=self._member_text(row, 1),
                        guard=self._member_text(row, 2) or None,
                        is_default=self._member_text(row, 3).casefold() in {"yes", "true", "1"},
                    )
                )
                if preferred_case_id is None and self._member_text(row, 4).casefold() in {
                    "yes",
                    "true",
                    "1",
                }:
                    preferred_case_id = original.id
            if preferred_case_id is None and any(
                case.id == atom.preferred_case_id for case in cases
            ):
                preferred_case_id = atom.preferred_case_id
            return replace(
                atom,
                cases=tuple(cases),
                preferred_case_id=preferred_case_id or (cases[0].id if cases else None),
            )
        if isinstance(atom, With):
            contexts: list[ContextItem] = []
            for row in range(self.members.rowCount()):
                original = self._member_semantic(row)
                if isinstance(original, ContextItem):
                    contexts.append(
                        replace(
                            original,
                            expression=self._member_text(row, 0),
                            target=self._member_text(row, 1) or None,
                        )
                    )
            return replace(atom, contexts=tuple(contexts))
        if isinstance(atom, Try):
            handlers: list[ExceptionHandler] = []
            for row in range(self.members.rowCount()):
                original = self._member_semantic(row)
                if isinstance(original, ExceptionHandler):
                    handlers.append(
                        replace(
                            original,
                            exception=self._member_text(row, 0),
                            name=self._member_text(row, 1) or None,
                        )
                    )
            return replace(atom, handlers=tuple(handlers))
        if isinstance(atom, Parallel):
            branches: list[ParallelBranch] = []
            for row in range(self.members.rowCount()):
                original = self._member_semantic(row)
                if isinstance(original, ParallelBranch):
                    branches.append(replace(original, name=self._member_text(row, 0)))
            return replace(atom, branches=tuple(branches))
        if isinstance(atom, Silhouette):
            originals: list[SilhouetteBranch] = []
            names: list[str] = []
            for row in range(self.members.rowCount()):
                original = self._member_semantic(row)
                if isinstance(original, SilhouetteBranch):
                    originals.append(original)
                    names.append(self._member_text(row, 0))
            ids_by_name = {
                name: original.id for name, original in zip(names, originals, strict=True)
            }
            silhouette_branches = tuple(
                replace(
                    original,
                    name=name,
                    target_branch_id=ids_by_name.get(self._member_text(row, 1)),
                )
                for row, (name, original) in enumerate(zip(names, originals, strict=True))
            )
            initial = next(
                (
                    original.id
                    for row, original in enumerate(originals)
                    if self._member_text(row, 2).casefold() in {"yes", "true", "1"}
                ),
                atom.initial_branch_id,
            )
            return replace(atom, branches=silhouette_branches, initial_branch_id=initial)
        return atom

    def _apply(self) -> None:
        if not self._atoms:
            return
        replacements: list[DrakonAtom] = []
        for atom in self._atoms:
            values = self._property_values(atom)
            replacement = cast(
                DrakonAtom,
                replace(cast(Any, atom), **values),
            )
            if len(self._atoms) == 1:
                replacement = self._replacement_members(replacement)
            if replacement != atom:
                replacements.append(replacement)
        if not replacements:
            self.purpose.setText(
                "No semantic properties changed; the selected operations were left intact."
            )
            return
        self.replacementRequested.emit(
            replacements[0] if len(self._atoms) == 1 else tuple(replacements)
        )

    def _add_member(self) -> None:
        atom = self._atom
        if atom is None:
            return
        values: tuple[str, ...]
        if isinstance(atom, Select):
            original: object = Case(
                new_id("case"),
                "Case",
                Sequence(new_id("sequence"), (Action(new_id("atom"), 'print("case action")'),)),
                condition="False",
            )
            values = ("Case", "False", "", "No", "No")
            row = max(0, self.members.rowCount() - 1)
        elif isinstance(atom, With):
            original = ContextItem(new_id("context"), "nullcontext()")
            values = ("nullcontext()", "")
            row = self.members.rowCount()
        elif isinstance(atom, Try):
            original = ExceptionHandler(
                new_id("handler"),
                "Exception",
                "error",
                Sequence(new_id("sequence"), (Action(new_id("atom"), 'print("handler action")'),)),
            )
            values = ("Exception", "error")
            row = self.members.rowCount()
        elif isinstance(atom, Parallel):
            original = ParallelBranch(
                new_id("branch"),
                "Process",
                Sequence(new_id("sequence"), (Action(new_id("atom"), 'print("process action")'),)),
            )
            values = ("Process",)
            row = self.members.rowCount()
        elif isinstance(atom, Silhouette):
            name = f"State {self.members.rowCount() + 1}"
            original = SilhouetteBranch(
                new_id("branch"),
                name,
                Sequence(new_id("sequence"), (Action(new_id("atom"), 'print("state action")'),)),
            )
            exit_row = next(
                (
                    index
                    for index in range(self.members.rowCount())
                    if self._member_text(index, 1).casefold() == "finite exit"
                ),
                None,
            )
            if exit_row is not None:
                exit_item = self.members.item(exit_row, 1)
                if exit_item is not None:
                    exit_item.setText(name)
            values = (name, "Finite exit", "No")
            row = self.members.rowCount()
        else:
            return
        self.members.insertRow(row)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setData(ATOM_ROLE, original)
            self.members.setItem(row, column, item)
        self.members.selectRow(row)

    def _remove_member(self) -> None:
        row = self.members.currentRow()
        if row < 0 or self._atom is None:
            return
        minimum = 2 if isinstance(self._atom, (Select, Parallel)) else 1
        if self.members.rowCount() <= minimum:
            self.purpose.setText(
                f"{_purpose(self._atom)}\nThis construct must retain {minimum} row(s)."
            )
            return
        self.members.removeRow(row)

    def _move_member(self, delta: int) -> None:
        row = self.members.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.members.rowCount():
            return
        if isinstance(self._atom, Select) and (
            self._member_text(row, 3).casefold() == "yes"
            or self._member_text(target, 3).casefold() == "yes"
        ):
            self.purpose.setText(f"{_purpose(self._atom)}\nThe default Case remains final.")
            return
        values = [
            self.members.takeItem(row, column) for column in range(self.members.columnCount())
        ]
        self.members.removeRow(row)
        self.members.insertRow(target)
        for column, item in enumerate(values):
            self.members.setItem(target, column, item)
        self.members.selectRow(target)
