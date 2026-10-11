"""Static workbench contribution metadata for the Qt shell.

The registry is an internal composition seam, not a dynamic or third-party plugin
system. MainWindow owns lifecycle while placement and discovery live here.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow

from code_visualizer.application.static_registry import StaticContributionRegistry


@dataclass(frozen=True, slots=True)
class WorkbenchContribution:
    id: str
    attribute: str
    area: Qt.DockWidgetArea
    view_menu_order: int | None = None


def build_workbench_registry() -> StaticContributionRegistry[WorkbenchContribution]:
    registry: StaticContributionRegistry[WorkbenchContribution] = StaticContributionRegistry()
    values = (
        WorkbenchContribution("project", "project_dock", Qt.DockWidgetArea.LeftDockWidgetArea, 20),
        WorkbenchContribution("shapes", "shapes_dock", Qt.DockWidgetArea.LeftDockWidgetArea, 30),
        WorkbenchContribution(
            "inspector", "inspector_dock", Qt.DockWidgetArea.LeftDockWidgetArea, 40
        ),
        WorkbenchContribution(
            "development", "development_dock", Qt.DockWidgetArea.BottomDockWidgetArea, 50
        ),
        WorkbenchContribution(
            "collaboration", "collaboration_dock", Qt.DockWidgetArea.RightDockWidgetArea
        ),
        WorkbenchContribution("search", "search_dock", Qt.DockWidgetArea.RightDockWidgetArea),
        WorkbenchContribution(
            "navigation", "navigation_dock", Qt.DockWidgetArea.RightDockWidgetArea
        ),
        WorkbenchContribution(
            "visualizer", "visualizer_dock", Qt.DockWidgetArea.RightDockWidgetArea, 10
        ),
        WorkbenchContribution("domains", "domain_dock", Qt.DockWidgetArea.RightDockWidgetArea, 15),
        WorkbenchContribution("git", "git_dock", Qt.DockWidgetArea.RightDockWidgetArea, 17),
    )
    for order, value in enumerate(values):
        registry.register(value.id, value, order=order)
    return registry


WORKBENCH_CONTRIBUTIONS = build_workbench_registry()


def place_workbench_dock(
    window: QMainWindow,
    contribution_id: str,
    dock: QDockWidget,
) -> None:
    contribution = WORKBENCH_CONTRIBUTIONS.get(contribution_id)
    if dock.objectName() == "":
        dock.setObjectName(contribution.attribute)
    window.addDockWidget(contribution.area, dock)


def view_menu_docks(window: QMainWindow) -> tuple[QDockWidget, ...]:
    contributions = sorted(
        (
            item.value
            for item in WORKBENCH_CONTRIBUTIONS.contributions()
            if item.value.view_menu_order is not None
        ),
        key=lambda item: (item.view_menu_order or 0, item.id),
    )
    return tuple(
        dock
        for item in contributions
        if isinstance((dock := getattr(window, item.attribute, None)), QDockWidget)
    )
