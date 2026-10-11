from collections.abc import Iterator
from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QTreeWidgetItem

from code_visualizer.application.queries import ProjectQueries
from code_visualizer.application.scale_fixture import build_scale_project
from code_visualizer.application.search import search_project
from code_visualizer.generation import generate_python
from code_visualizer.persistence import ProjectStore
from code_visualizer.ui_qt.main_window import CloseDecision, MainWindow
from code_visualizer.validation import validate_project


def _elapsed(operation):
    started = perf_counter()
    value = operation()
    return value, perf_counter() - started


def _walk_tree(item: QTreeWidgetItem) -> Iterator[QTreeWidgetItem]:
    yield item
    for index in range(item.childCount()):
        yield from _walk_tree(item.child(index))


def test_500_diagram_headless_workload_stays_within_release_budgets(tmp_path) -> None:
    project = build_scale_project()
    semantic_project = build_scale_project(atoms_per_diagram=20)
    store = ProjectStore(tmp_path / "scale")
    _saved, save_seconds = _elapsed(lambda: store.initialize(project))
    opened, open_seconds = _elapsed(store.recover)
    matches, search_seconds = _elapsed(lambda: search_project(opened, "Function 049"))
    diagnostics, validation_seconds = _elapsed(lambda: validate_project(opened))
    queries, semantic_index_seconds = _elapsed(
        lambda: ProjectQueries.from_project(semantic_project)
    )
    generated, generation_seconds = _elapsed(lambda: generate_python(opened))

    assert len(opened.documents) == 500
    assert matches
    assert not diagnostics
    assert generated.source
    assert len(queries.program.objects) > 70_000
    assert len(queries.program.relations) > 100_000
    assert save_seconds < 5.0
    assert open_seconds < 5.0
    assert search_seconds < 2.0
    assert validation_seconds < 5.0
    assert generation_seconds < 10.0
    assert semantic_index_seconds < 12.0


def test_500_diagram_gui_opens_lazily_and_tree_activation_materializes_one_tab(
    qtbot, tmp_path
) -> None:
    root = tmp_path / "scale-gui"
    scale_project = build_scale_project()
    ProjectStore(root).initialize(scale_project)
    window = MainWindow(
        close_decision=lambda _session: CloseDecision.DISCARD,
        settings=QSettings(str(Path(tmp_path) / "scale.ini"), QSettings.Format.IniFormat),
    )
    qtbot.addWidget(window)
    window.show()
    _opened, open_seconds = _elapsed(lambda: window.open_project(root))

    project_root = window.project_tree.topLevelItem(0)
    assert project_root.childCount() == 3  # Python Project, generated tree, and assets.
    diagram_items = tuple(
        item
        for item in _walk_tree(project_root)
        if isinstance(item.data(0, Qt.ItemDataRole.UserRole), str)
        and item.data(0, Qt.ItemDataRole.UserRole).startswith("diagram_scale_")
    )
    assert len(diagram_items) == 500
    assert window.documents.count() == 1
    assert open_seconds < 8.0

    last_id = scale_project.documents[-1].id
    last_document = next(
        item for item in diagram_items if item.data(0, Qt.ItemDataRole.UserRole) == last_id
    )
    parent = last_document.parent()
    while parent is not None:
        parent.setExpanded(True)
        parent = parent.parent()
    window.project_tree.scrollToItem(last_document)
    qtbot.wait(50)
    rect = window.project_tree.visualItemRect(last_document)
    assert not rect.isEmpty()
    qtbot.mouseClick(
        window.project_tree.viewport(),
        Qt.MouseButton.LeftButton,
        pos=rect.center(),
    )
    qtbot.keyClick(window.project_tree, Qt.Key.Key_Return)
    assert window.documents.count() == 2
    assert window.documents.tabText(window.documents.currentIndex()) == "Function 0499"
