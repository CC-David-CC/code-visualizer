from dataclasses import replace

from PySide6.QtCore import Qt

from code_visualizer.domain.drakon import Assignment, Select
from code_visualizer.domain.drakon_defaults import create_default_atom
from code_visualizer.ui_qt.atom_inspector import AtomInspector


def test_shelf_inspector_uses_semantic_labels_and_applies_typed_fields(qtbot) -> None:
    atom = create_default_atom("assignment", "assignment_inspector")
    assert isinstance(atom, Assignment)
    inspector = AtomInspector()
    qtbot.addWidget(inspector)
    inspector.show()
    inspector.set_atom(atom)

    labels = [
        inspector.properties.item(row, 0).text() for row in range(inspector.properties.rowCount())
    ]
    assert labels == [
        "Assignment / iteration target",
        "Assignment kind / operator",
        "Type annotation",
        "Value expression",
    ]
    assert "upper field names state" in inspector.purpose.text()

    replacements: list[object] = []
    inspector.replacementRequested.connect(replacements.append)
    inspector.properties.item(0, 1).setText("answer")
    inspector.properties.item(2, 1).setText("int")
    inspector.properties.item(3, 1).setText("6 * 7")
    qtbot.mouseClick(inspector.apply_button, Qt.MouseButton.LeftButton)

    replacement = replacements[-1]
    assert isinstance(replacement, Assignment)
    assert (replacement.target, replacement.annotation, replacement.value) == (
        "answer",
        "int",
        "6 * 7",
    )


def test_select_inspector_edits_ordered_cases_without_a_modal(qtbot) -> None:
    atom = create_default_atom("select", "select_inspector")
    assert isinstance(atom, Select)
    inspector = AtomInspector()
    qtbot.addWidget(inspector)
    inspector.show()
    inspector.set_atom(atom)

    assert inspector.members.horizontalHeaderItem(0).text() == "Case label"
    assert inspector.members.rowCount() == 2
    inspector.members.selectRow(0)
    qtbot.mouseClick(inspector.add_member, Qt.MouseButton.LeftButton)
    assert inspector.members.rowCount() == 3
    assert inspector.members.item(2, 3).text() == "Yes"
    inspector.members.item(1, 0).setText("Explicit second case")
    inspector.members.item(1, 1).setText("value == 2")
    inspector.members.item(0, 4).setText("No")
    inspector.members.item(1, 4).setText("Yes")

    replacements: list[object] = []
    inspector.replacementRequested.connect(replacements.append)
    qtbot.mouseClick(inspector.apply_button, Qt.MouseButton.LeftButton)

    replacement = replacements[-1]
    assert isinstance(replacement, Select)
    assert [case.label for case in replacement.cases] == [
        "First",
        "Explicit second case",
        "Otherwise",
    ]
    assert replacement.cases[1].condition == "value == 2"
    assert replacement.cases[-1].is_default
    assert replacement.preferred_case_id == replacement.cases[1].id


def test_multi_selection_inspector_applies_only_edited_common_properties(qtbot) -> None:
    first = create_default_atom("assignment", "assignment_first")
    second = create_default_atom("assignment", "assignment_second")
    assert isinstance(first, Assignment)
    assert isinstance(second, Assignment)
    first = replace(first, target="left", value="1")
    second = replace(second, target="right", value="2")
    inspector = AtomInspector()
    qtbot.addWidget(inspector)
    inspector.show()
    inspector.set_atoms((first, second))

    assert "2 operations selected" in inspector.purpose.text()
    assert not inspector.members.isVisible()
    assert inspector.properties.item(0, 1).text() == "— multiple values —"
    inspector.properties.item(0, 1).setText("shared")

    replacements: list[object] = []
    inspector.replacementRequested.connect(replacements.append)
    qtbot.mouseClick(inspector.apply_button, Qt.MouseButton.LeftButton)

    replacement = replacements[-1]
    assert isinstance(replacement, tuple)
    assert [item.target for item in replacement] == ["shared", "shared"]
    assert [item.value for item in replacement] == ["1", "2"]
