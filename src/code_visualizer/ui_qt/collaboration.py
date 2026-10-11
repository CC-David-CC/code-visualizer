"""Human-visible controls for the authenticated semantic automation authority."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.messages import EventEnvelope
from code_visualizer.domain.common import JsonValue


class CollaborationWidget(QWidget):
    """Endpoint discovery, actor presence, and explicit proposal review."""

    acceptProposalRequested = Signal(str)
    rejectProposalRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("collaborationWidget")
        self.setAccessibleName("Automation and collaboration")
        self._token = ""
        self._actors: dict[str, QTreeWidgetItem] = {}

        explanation = QLabel(
            "External tools edit semantic objects through this project's authenticated "
            "authority. Code execution is a separate permission."
        )
        explanation.setWordWrap(True)

        self.endpoint = QLineEdit()
        self.endpoint.setObjectName("automationEndpoint")
        self.endpoint.setReadOnly(True)
        self.endpoint.setAccessibleName("Local automation endpoint")
        self.endpoint.setPlaceholderText("Open a project to start its local endpoint")
        self.copy_endpoint = QPushButton("Copy endpoint")
        self.copy_endpoint.clicked.connect(lambda: self._copy(self.endpoint.text()))
        endpoint_row = QHBoxLayout()
        endpoint_row.addWidget(QLabel("Endpoint:"))
        endpoint_row.addWidget(self.endpoint, 1)
        endpoint_row.addWidget(self.copy_endpoint)

        self.token = QLineEdit()
        self.token.setObjectName("automationToken")
        self.token.setReadOnly(True)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.token.setAccessibleName("Bearer access token")
        self.reveal_token = QPushButton("Show token")
        self.reveal_token.setCheckable(True)
        self.reveal_token.toggled.connect(self._set_token_visible)
        self.copy_token = QPushButton("Copy token")
        self.copy_token.clicked.connect(lambda: self._copy(self._token))
        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("Token:"))
        token_row.addWidget(self.token, 1)
        token_row.addWidget(self.reveal_token)
        token_row.addWidget(self.copy_token)

        self.status = QLabel("No project authority is active.")
        self.status.setObjectName("automationStatus")
        self.status.setWordWrap(True)

        self.actors = QTreeWidget()
        self.actors.setObjectName("automationActors")
        self.actors.setAccessibleName("Connected actors and recent authority activity")
        self.actors.setHeaderLabels(["Actor", "Mode / state", "Last event", "Revision"])
        self.actors.setRootIsDecorated(False)

        self.proposals = QTreeWidget()
        self.proposals.setObjectName("automationProposals")
        self.proposals.setAccessibleName("Agent proposals awaiting human review")
        self.proposals.setHeaderLabels(["Proposed by", "Summary", "Base", "Proposal ID"])
        self.proposals.setRootIsDecorated(False)
        self.proposals.itemSelectionChanged.connect(self._proposal_selection_changed)
        self.accept_proposal = QPushButton("Accept selected proposal")
        self.reject_proposal = QPushButton("Reject selected proposal")
        self.accept_proposal.setEnabled(False)
        self.reject_proposal.setEnabled(False)
        self.accept_proposal.clicked.connect(self._accept_selected)
        self.reject_proposal.clicked.connect(self._reject_selected)
        proposal_buttons = QHBoxLayout()
        proposal_buttons.addWidget(self.accept_proposal)
        proposal_buttons.addWidget(self.reject_proposal)

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addLayout(endpoint_row)
        layout.addLayout(token_row)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("Live actors"))
        layout.addWidget(self.actors, 1)
        layout.addWidget(QLabel("Proposals"))
        layout.addWidget(self.proposals, 1)
        layout.addLayout(proposal_buttons)

    def set_access(self, endpoint: str, token: str) -> None:
        self.endpoint.setText(endpoint)
        self._token = token
        self.token.setText(token)
        self.status.setText("Loopback-only endpoint active; bearer authentication required.")
        self.copy_endpoint.setEnabled(True)
        self.copy_token.setEnabled(True)

    def clear_access(self) -> None:
        self.endpoint.clear()
        self._token = ""
        self.token.clear()
        self.reveal_token.setChecked(False)
        self.actors.clear()
        self._actors.clear()
        self.proposals.clear()
        self.status.setText("No project authority is active.")

    def observe_event(self, event: EventEnvelope) -> None:
        actor = event.actor_id or "unknown"
        item = self._actors.get(actor)
        if item is None:
            item = QTreeWidgetItem([actor, "active", "", str(event.revision)])
            item.setData(0, Qt.ItemDataRole.UserRole, actor)
            self.actors.addTopLevelItem(item)
            self._actors[actor] = item
        raw_mode = event.payload.get("mode")
        state = str(raw_mode) if isinstance(raw_mode, str) else item.text(1) or "active"
        if event.event_type == "presence.disconnected":
            state = "disconnected"
        elif event.event_type == "presence.connected":
            state = f"{state} · connected"
        item.setText(1, state)
        item.setText(2, event.event_type)
        item.setText(3, str(event.revision))
        item.setToolTip(2, f"Operation {event.operation_id}")
        self.status.setText(f"Revision {event.revision}: {event.actor_id} · {event.event_type}")

    def set_proposals(self, raw_proposals: list[JsonValue]) -> None:
        selected_id = self.selected_proposal_id()
        self.proposals.clear()
        for raw in raw_proposals:
            if not isinstance(raw, dict):
                continue
            proposal_id = raw.get("proposal_id")
            actor = raw.get("actor_id")
            summary = raw.get("summary")
            base = raw.get("base_revision")
            if (
                not isinstance(proposal_id, str)
                or not isinstance(actor, str)
                or not isinstance(summary, str)
            ):
                continue
            item = QTreeWidgetItem([actor, summary, str(base), proposal_id])
            item.setData(0, Qt.ItemDataRole.UserRole, proposal_id)
            diff = raw.get("diff")
            if isinstance(diff, str):
                item.setToolTip(1, diff)
            self.proposals.addTopLevelItem(item)
            if proposal_id == selected_id:
                item.setSelected(True)
        self._proposal_selection_changed()

    def selected_proposal_id(self) -> str | None:
        selected = self.proposals.selectedItems()
        if not selected:
            return None
        value = selected[0].data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    @staticmethod
    def _copy(value: str) -> None:
        if value:
            QApplication.clipboard().setText(value)

    def _set_token_visible(self, visible: bool) -> None:
        self.token.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self.reveal_token.setText("Hide token" if visible else "Show token")

    def _proposal_selection_changed(self) -> None:
        enabled = self.selected_proposal_id() is not None
        self.accept_proposal.setEnabled(enabled)
        self.reject_proposal.setEnabled(enabled)

    def _accept_selected(self) -> None:
        proposal_id = self.selected_proposal_id()
        if proposal_id is not None:
            self.acceptProposalRequested.emit(proposal_id)

    def _reject_selected(self) -> None:
        proposal_id = self.selected_proposal_id()
        if proposal_id is not None:
            self.rejectProposalRequested.emit(proposal_id)
