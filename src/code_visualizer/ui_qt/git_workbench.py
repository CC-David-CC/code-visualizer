"""Explicit Git review and collaboration controls for the existing project shell."""

from __future__ import annotations

from collections.abc import Callable
from threading import Thread
from typing import cast

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.checkpoint_selection import CheckpointChoice
from code_visualizer.application.experiment_inputs import SourceInput
from code_visualizer.application.git import (
    GitBranch,
    GitCommit,
    GitConflict,
    GitDiff,
    GitError,
    GitRemote,
    GitStatus,
)
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.persistence.experiment_store import RetainedAttempt


class GitWorkbenchWidget(QWidget):
    """Every write originates in an explicit button or permission-checked RPC."""

    completed = Signal(object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller: GitProjectController | None = None
        self.snapshot: GitStatus | None = None
        self._busy = False
        layout = QVBoxLayout(self)
        self.status_label = QLabel("Save or open a project to use Git")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        toolbar = QHBoxLayout()
        self._button(toolbar, "Refresh", self.refresh)
        self._button(toolbar, "Initialize Git", lambda: self.perform("initialize"))
        self._button(toolbar, "Reload validated project", lambda: self.perform("reload"))
        layout.addLayout(toolbar)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        changes = QWidget()
        change_layout = QVBoxLayout(changes)
        self.files = QTreeWidget()
        self.files.setHeaderLabels(["Index", "Worktree", "Path"])
        self.files.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.files.itemSelectionChanged.connect(self._show_diff)
        change_layout.addWidget(self.files)
        review = QHBoxLayout()
        self.staged = QCheckBox("Show staged diff")
        self.staged.toggled.connect(self._show_diff)
        review.addWidget(self.staged)
        self._button(review, "Stage selected", lambda: self._paths("stage"))
        self._button(review, "Unstage selected", lambda: self._paths("unstage"))
        self._button(review, "Resolve conflict…", self._resolve)
        change_layout.addLayout(review)
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        self.diff.setPlaceholderText("Select a file to review its exact Git diff")
        change_layout.addWidget(self.diff)
        self.message = QPlainTextEdit()
        self.message.setPlaceholderText("Commit message — commits the reviewed staged index")
        self.message.setMaximumHeight(85)
        change_layout.addWidget(self.message)
        commit = QHBoxLayout()
        self._button(commit, "Commit staged files", self._commit)
        self._button(commit, "Abort current merge", lambda: self.perform("abort_merge"))
        change_layout.addLayout(commit)
        self.tabs.addTab(changes, "Changes")
        history = QWidget()
        history_layout = QVBoxLayout(history)
        self.history = QTreeWidget()
        self.history.setHeaderLabels(["Commit", "Author", "Date", "Subject"])
        self.history.itemSelectionChanged.connect(self._show_commit)
        history_layout.addWidget(self.history)
        self.history_diff = QPlainTextEdit()
        self.history_diff.setReadOnly(True)
        history_layout.addWidget(self.history_diff)
        self.tabs.addTab(history, "History")
        branches = QWidget()
        branch_layout = QVBoxLayout(branches)
        self.branch = QComboBox()
        branch_layout.addWidget(QLabel("Local branch"))
        branch_layout.addWidget(self.branch)
        local = QHBoxLayout()
        self._button(local, "New branch…", self._new_branch)
        self._button(
            local, "Switch", lambda: self.perform("switch", branch=self.branch.currentText())
        )
        self._button(
            local,
            "Merge for review",
            lambda: self.perform("merge", branch=self.branch.currentText()),
        )
        branch_layout.addLayout(local)
        branch_layout.addWidget(
            QLabel(
                "Switch and merge require a saved project and clean Git working tree. "
                "Merge results remain staged for explicit review and commit."
            )
        )
        self.remote = QComboBox()
        branch_layout.addWidget(QLabel("Configured remote"))
        branch_layout.addWidget(self.remote)
        self.remote_branch = QLineEdit()
        self.remote_branch.setPlaceholderText("Remote branch (for pull); local branch (for push)")
        branch_layout.addWidget(self.remote_branch)
        remote_buttons = QHBoxLayout()
        self._button(remote_buttons, "Add remote…", self._add_remote)
        self._button(
            remote_buttons, "Fetch", lambda: self.perform("fetch", remote=self.remote.currentText())
        )
        self._button(
            remote_buttons,
            "Pull fast-forward",
            lambda: self.perform(
                "pull", remote=self.remote.currentText(), branch=self.remote_branch.text()
            ),
        )
        self._button(
            remote_buttons,
            "Push",
            lambda: self.perform(
                "push", remote=self.remote.currentText(), branch=self.remote_branch.text()
            ),
        )
        branch_layout.addLayout(remote_buttons)
        branch_layout.addStretch()
        self.tabs.addTab(branches, "Branches / remotes")
        retained = QWidget()
        retained_layout = QVBoxLayout(retained)
        self.retained_runs = QTreeWidget()
        self.retained_runs.setHeaderLabels(["Attempt", "Input commit", "State"])
        self.retained_runs.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        retained_layout.addWidget(self.retained_runs)
        run_buttons = QHBoxLayout()
        self._button(run_buttons, "Open retained run", self._open_retained_run)
        self._button(run_buttons, "List checkpoints", self._list_checkpoints)
        self._button(run_buttons, "Compare selected runs", self._compare_runs)
        self._button(run_buttons, "Remove inactive worktree", self._remove_retained_worktree)
        self._button(
            run_buttons,
            "Inspect interrupted operations",
            lambda: self.perform("recover_experiments"),
        )
        retained_layout.addLayout(run_buttons)
        checkpoint_bar = QHBoxLayout()
        self.checkpoints = QComboBox()
        self.checkpoints.setObjectName("retainedCheckpointChoice")
        checkpoint_bar.addWidget(self.checkpoints, 1)
        self._button(checkpoint_bar, "Resume selected checkpoint", self._resume_checkpoint)
        retained_layout.addLayout(checkpoint_bar)
        self.comparison_label = QLabel("Select two retained attempts to compare their evidence.")
        self.comparison_label.setWordWrap(True)
        retained_layout.addWidget(self.comparison_label)
        self.comparison = QTreeWidget()
        self.comparison.setObjectName("retainedRunComparison")
        self.comparison.setHeaderLabels(
            ["Observation", "Earlier", "Later", "Later - earlier", "Status"]
        )
        self.comparison.itemSelectionChanged.connect(self._comparison_selected)
        retained_layout.addWidget(self.comparison)
        self.tabs.addTab(retained, "Retained runs")
        self.source_inputs = QPlainTextEdit()
        self.source_inputs.setPlaceholderText(
            "Optional declared source inputs, one per line:\n"
            "repository/path.py => runtime/path.py\n"
            "Freeze & Run always includes project.json and input/resource manifests."
        )
        self.source_inputs.setMaximumHeight(100)
        layout.addWidget(QLabel("Freeze & Run: additional source closure"))
        layout.addWidget(self.source_inputs)
        self.completed.connect(self._finished)

    @staticmethod
    def _button(layout: QHBoxLayout, text: str, callback: Callable[[], object]) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def attach(
        self, controller: GitProjectController | None, *, review: dict[str, object] | None = None
    ) -> None:
        old_project = self.controller.session.authority.snapshot().id if self.controller else None
        new_project = controller.session.authority.snapshot().id if controller else None
        if old_project != new_project:
            self.comparison.clear()
            self.checkpoints.clear()
            self.comparison_label.setText("Select two retained attempts to compare their evidence.")
        self.controller = controller
        self.refresh(review)

    def declared_sources(self) -> tuple[SourceInput, ...]:
        lines = [
            line.strip() for line in self.source_inputs.toPlainText().splitlines() if line.strip()
        ]
        if len(lines) > 1000 or any("=>" not in line for line in lines):
            raise ValueError("Declare at most 1000 source paths as path => runtime/path")
        return tuple(SourceInput(*[part.strip() for part in line.split("=>", 1)]) for line in lines)

    def refresh(self, review: dict[str, object] | None = None) -> None:
        if not isinstance(review, dict):  # QPushButton.clicked may supply its checked boolean.
            review = None
        if (
            review is None
            and self.controller is not None
            and self.controller.prepared_review is not None
        ):
            controller = self.controller

            def prepare() -> None:
                try:
                    value: object = controller.prepare_review()
                except (GitError, OSError, RuntimeError) as exc:
                    value = exc
                self.completed.emit(controller, value)

            Thread(target=prepare, name="git-review", daemon=True).start()
            return
        self.files.clear()
        self.history.clear()
        self.branch.clear()
        self.remote.clear()
        self.retained_runs.clear()
        self.snapshot = None
        if self.controller is None:
            self.status_label.setText("Save or open a project to use Git")
            return
        controller = self.controller

        def read(method: str) -> object:
            return review[method] if review is not None else controller.execute(method, {})

        try:
            status = read("status")
            if not isinstance(status, GitStatus):
                return
            self.snapshot = status
            problem = (
                str(review["problem"])
                if review is not None
                else controller.session.storage_problem()
            )
            self.status_label.setText(
                f"{status.branch} · {status.head[:12] or 'no commits'} · {status.root}"
                + (f"\n{problem}" if problem else "")
            )
            for item in status.files:
                row = QTreeWidgetItem([item.index, item.worktree, item.path])
                row.setData(0, Qt.ItemDataRole.UserRole, item.path)
                if not item.in_project:
                    row.setToolTip(
                        2,
                        "Outside this project: visible for repository review; "
                        "cannot be staged here",
                    )
                self.files.addTopLevelItem(row)
            for commit in cast(tuple[GitCommit, ...], read("history")):
                row = QTreeWidgetItem(
                    [commit.oid[:12], commit.author, commit.timestamp, commit.subject]
                )
                row.setData(0, Qt.ItemDataRole.UserRole, commit.oid)
                self.history.addTopLevelItem(row)
            for branch in cast(tuple[GitBranch, ...], read("branches")):
                self.branch.addItem(branch.name)
                if branch.current:
                    self.branch.setCurrentText(branch.name)
            for remote in cast(tuple[GitRemote, ...], read("remotes")):
                self.remote.addItem(remote.name)
                self.remote.setItemData(
                    self.remote.count() - 1, remote.fetch_url, Qt.ItemDataRole.ToolTipRole
                )
            if review is not None:
                for attempt in cast(tuple[RetainedAttempt, ...], review.get("runs", ())):
                    row = QTreeWidgetItem([attempt.id, attempt.commit[:12], attempt.phase])
                    row.setData(0, Qt.ItemDataRole.UserRole, attempt)
                    self.retained_runs.addTopLevelItem(row)
        except (GitError, OSError, RuntimeError) as exc:
            self.status_label.setText(str(exc))

    def perform(self, method: str, **params: object) -> None:
        if self.controller is None or self._busy:
            return
        if self.snapshot is not None:
            params.setdefault("expected_head", self.snapshot.head)
        controller = self.controller
        self._busy = True
        self.setEnabled(False)
        self.status_label.setText(f"Git {method}…")

        def run() -> None:
            try:
                result: object = controller.execute(method, params)
            except (GitError, OSError, RuntimeError) as exc:
                result = exc
            self.completed.emit(controller, result)

        Thread(target=run, name="git-workbench", daemon=True).start()

    def _finished(self, controller: object, result: object) -> None:
        self._busy = False
        self.setEnabled(True)
        if controller is not self.controller:
            return
        if isinstance(result, dict) and "checkpoints" in result:
            self.checkpoints.clear()
            for choice in result["checkpoints"]:
                if isinstance(choice, CheckpointChoice):
                    self.checkpoints.addItem(choice.label, choice)
            self.status_label.setText(
                "Select a retained checkpoint and resume explicitly. "
                "The current definition must remain compatible."
            )
            return
        if isinstance(result, dict) and result.get("comparison") is True:
            self.comparison.clear()
            self.comparison_label.setText(
                f"{result['left_attempt']} ({str(result['left_commit'])[:12]}, "
                f"{result['left_outcome']})\n"
                f"to {result['right_attempt']} ({str(result['right_commit'])[:12]}, "
                f"{result['right_outcome']})"
            )
            for value in result["rows"]:
                row = QTreeWidgetItem(
                    [
                        str(value[key])
                        for key in ("label", "left_text", "right_text", "difference_text", "status")
                    ]
                )
                row.setData(0, Qt.ItemDataRole.UserRole, tuple(value["semantic_ids"]))
                row.setToolTip(0, "\n".join(value["semantic_ids"]))
                row.setToolTip(3, str(value["note"]))
                self.comparison.addTopLevelItem(row)
            for column in range(5):
                self.comparison.resizeColumnToContents(column)
            self.status_label.setText("Retained evidence compared; authoring state is unchanged.")
            return
        if isinstance(result, dict) and isinstance(result.get("status"), GitStatus):
            self.refresh(result)
            return
        if not isinstance(result, Exception):
            self.refresh()
        if isinstance(result, Exception) or (isinstance(result, dict) and "operations" in result):
            self.status_label.setText(str(result))

    def _open_retained_run(self) -> None:
        selected = self.retained_runs.currentItem()
        if selected is not None:
            attempt = selected.data(0, Qt.ItemDataRole.UserRole)
            self.perform("reopen_run", attempt_id=attempt.id)

    def _list_checkpoints(self) -> None:
        selected = self.retained_runs.currentItem()
        if selected is not None:
            attempt = selected.data(0, Qt.ItemDataRole.UserRole)
            self.perform("experiment_checkpoints", attempt_id=attempt.id)

    def _resume_checkpoint(self) -> None:
        choice = self.checkpoints.currentData()
        if isinstance(choice, CheckpointChoice):
            self.perform(
                "resume_checkpoint",
                attempt_id=choice.attempt_id,
                publication_id=choice.publication_id,
            )

    def _compare_runs(self) -> None:
        selected = self.retained_runs.selectedItems()
        if len(selected) != 2:
            self.status_label.setText("Select exactly two retained attempts.")
            return
        attempts = sorted(
            (item.data(0, Qt.ItemDataRole.UserRole) for item in selected),
            key=lambda item: (item.created_at, item.id),
        )
        self.perform("compare_runs", left_id=attempts[0].id, right_id=attempts[1].id)

    def _comparison_selected(self) -> None:
        selected = self.comparison.currentItem()
        if selected is None or self.controller is None:
            return
        identities = selected.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(identities, tuple) and identities:
            kernel = self.controller.session.kernel
            kernel.selection.select(
                identities, source="ui.retained_comparison", revision=kernel.revision
            )

    def _remove_retained_worktree(self) -> None:
        selected = self.retained_runs.currentItem()
        if selected is not None:
            attempt = selected.data(0, Qt.ItemDataRole.UserRole)
            self.perform("remove_experiment_worktree", variant_id=attempt.variant_id)

    def _paths(self, method: str) -> None:
        self.perform(
            method,
            paths=[row.data(0, Qt.ItemDataRole.UserRole) for row in self.files.selectedItems()],
        )

    def _commit(self) -> None:
        if self.snapshot is not None:
            self.perform(
                "commit",
                message=self.message.toPlainText(),
                expected_index=self.snapshot.index_fingerprint,
            )

    def _show_diff(self) -> None:
        selected = self.files.selectedItems()
        if self.controller is None or not selected:
            self.diff.clear()
            return
        try:
            result = self.controller.execute(
                "diff",
                {
                    "path": selected[0].data(0, Qt.ItemDataRole.UserRole),
                    "staged": self.staged.isChecked(),
                },
            )
            if isinstance(result, GitDiff):
                self.diff.setPlainText(result.patch)
        except (GitError, OSError) as exc:
            self.diff.setPlainText(str(exc))

    def _show_commit(self) -> None:
        selected = self.history.selectedItems()
        if self.controller is not None and selected:
            try:
                self.history_diff.setPlainText(
                    str(
                        self.controller.execute(
                            "commit_diff", {"oid": selected[0].data(0, Qt.ItemDataRole.UserRole)}
                        )
                    )
                )
            except GitError as exc:
                self.history_diff.setPlainText(str(exc))

    def _new_branch(self) -> None:
        value, accepted = QInputDialog.getText(self, "Create Git branch", "Branch name")
        if accepted and value:
            self.perform("create_branch", branch=value)

    def _add_remote(self) -> None:
        name, accepted = QInputDialog.getText(self, "Add Git remote", "Remote name")
        if not accepted or not name:
            return
        url, accepted = QInputDialog.getText(self, "Add Git remote", "Repository URL or path")
        if accepted and url:
            self.perform("add_remote", name=name, url=url)

    def _resolve(self) -> None:
        rows = self.files.selectedItems()
        if self.controller is None or len(rows) != 1:
            return
        path = rows[0].data(0, Qt.ItemDataRole.UserRole)
        try:
            conflict = self.controller.execute("conflict", {"path": path})
            if not isinstance(conflict, GitConflict):
                return
        except GitError as exc:
            self.status_label.setText(str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Resolve Git conflict: {path}")
        dialog.resize(1000, 700)
        layout = QVBoxLayout(dialog)
        versions = QTabWidget()
        for label, content in (
            ("Base", conflict.base),
            ("Ours", conflict.ours),
            ("Theirs", conflict.theirs),
        ):
            view = QPlainTextEdit(content)
            view.setReadOnly(True)
            versions.addTab(view, label)
        layout.addWidget(versions)
        layout.addWidget(QLabel("Resolved result (project.json is validated before staging)"))
        edited = QPlainTextEdit(conflict.working)
        layout.addWidget(edited)
        choices = QHBoxLayout()
        self._button(choices, "Use ours", lambda: edited.setPlainText(conflict.ours))
        self._button(choices, "Use theirs", lambda: edited.setPlainText(conflict.theirs))
        layout.addLayout(choices)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.perform("resolve_conflict", path=path, choice="edited", text=edited.toPlainText())
