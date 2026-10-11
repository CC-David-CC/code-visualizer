"""Ordered rooted mind-map editor projected through the shared authority."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.selection import SelectionState
from code_visualizer.domain.mindmap import (
    MindMapDiagram,
    Topic,
    find_topic,
    find_topic_parent,
)
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import SemanticObjectKind
from code_visualizer.rendering import layout_mind_map
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.ui_qt.vector_canvas import VectorCanvas


class MindMapDocumentWidget(QWidget):
    projectChanged = Signal()

    def __init__(
        self,
        client: CodeVisualizerClient,
        diagram_id: str,
        parent: QWidget | None = None,
        *,
        kernel: ProjectKernel | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("mindMapDocument")
        self._client = client
        self.diagram_id = diagram_id
        self._selected_id: str | None = None
        self._kernel = kernel
        self._anchor_target: str | None = None

        self.header = QLabel()
        self.header.setObjectName("mindMapHeader")
        self.layout_choice = QComboBox()
        self.layout_choice.setObjectName("mindMapLayout")
        for label, value in (
            ("Balanced", "balanced"),
            ("Left to right", "left_to_right"),
            ("Right to left", "right_to_left"),
            ("Radial", "radial"),
        ):
            self.layout_choice.addItem(label, value)
        self.layout_choice.activated.connect(self._set_layout)
        self.add_sibling_button = QPushButton("Add Sibling (Enter)")
        self.add_child_button = QPushButton("Add Child (Tab)")
        self.promote_button = QPushButton("Promote (Shift+Tab)")
        self.demote_button = QPushButton("Demote")
        self.collapse_button = QPushButton("Collapse / Expand")
        self.delete_button = QPushButton("Delete…")
        self.fit_button = QPushButton("Fit")
        self.add_sibling_button.clicked.connect(self.add_sibling)
        self.add_child_button.clicked.connect(self.add_child)
        self.promote_button.clicked.connect(self.promote)
        self.demote_button.clicked.connect(self.demote)
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        self.delete_button.clicked.connect(self.preview_delete)
        self.fit_button.clicked.connect(self._fit)
        controls = QHBoxLayout()
        controls.addWidget(self.header, 1)
        controls.addWidget(QLabel("Layout:"))
        controls.addWidget(self.layout_choice)
        controls.addWidget(self.add_sibling_button)
        controls.addWidget(self.add_child_button)
        controls.addWidget(self.promote_button)
        controls.addWidget(self.demote_button)
        controls.addWidget(self.collapse_button)
        controls.addWidget(self.delete_button)
        controls.addWidget(self.fit_button)

        self.canvas = VectorCanvas(mode="mind_map")
        self.canvas.objectSelected.connect(self._select_topic)
        self.canvas.reparentRequested.connect(self._reparent)
        self.canvas.addSiblingRequested.connect(self.add_sibling)
        self.canvas.addChildRequested.connect(self.add_child)
        self.canvas.promoteRequested.connect(self.promote)
        self.canvas.deleteRequested.connect(self.preview_delete)

        self.topic_text = QLineEdit()
        self.topic_text.setObjectName("mindMapTopicText")
        self.topic_notes = QPlainTextEdit()
        self.topic_notes.setObjectName("mindMapTopicNotes")
        self.topic_notes.setPlaceholderText("Notes")
        self.topic_notes.setMaximumHeight(80)
        self.topic_links = QPlainTextEdit()
        self.topic_links.setObjectName("mindMapTopicLinks")
        self.topic_links.setPlaceholderText("Safe links, one per line (never opened on load)")
        self.topic_links.setMaximumHeight(70)
        self.topic_attachments = QLineEdit()
        self.topic_attachments.setObjectName("mindMapTopicAttachments")
        self.topic_attachments.setPlaceholderText("Managed asset IDs, comma separated")
        self.apply_topic_button = QPushButton("Apply Topic")
        self.apply_topic_button.clicked.connect(self.apply_topic)
        self.live_label_button = QPushButton("Use Live Label")
        self.live_label_button.setObjectName("mindMapUseLiveLabel")
        self.live_label_button.setToolTip(
            "Remove the authored label override and follow semantic renames again."
        )
        self.live_label_button.clicked.connect(self.use_live_label)
        editor = QHBoxLayout()
        editor.addWidget(QLabel("Topic:"))
        editor.addWidget(self.topic_text, 2)
        editor.addWidget(QLabel("Notes:"))
        editor.addWidget(self.topic_notes, 2)
        editor.addWidget(QLabel("Links:"))
        editor.addWidget(self.topic_links, 2)
        editor.addWidget(QLabel("Attachments:"))
        editor.addWidget(self.topic_attachments, 1)
        editor.addWidget(self.apply_topic_button)
        editor.addWidget(self.live_label_button)

        self.cross_link_target = QComboBox()
        self.cross_link_target.setObjectName("mindMapCrossLinkTarget")
        self.cross_link_label = QLineEdit()
        self.cross_link_label.setPlaceholderText("Cross-link label")
        self.add_cross_link_button = QPushButton("Add Cross-link")
        self.add_cross_link_button.clicked.connect(self.add_cross_link)
        cross_links = QHBoxLayout()
        cross_links.addWidget(QLabel("Typed cross-link to:"))
        cross_links.addWidget(self.cross_link_target)
        cross_links.addWidget(self.cross_link_label)
        cross_links.addWidget(self.add_cross_link_button)
        cross_links.addStretch(1)

        self.anchor_target = QLabel("Select code in another projection to choose a link target.")
        self.anchor_target.setObjectName("mindMapAnchorTarget")
        self.anchor_state = QLabel("Annotation only")
        self.anchor_state.setObjectName("mindMapAnchorState")
        self.link_semantic_button = QPushButton("Link Topic to Selected Code")
        self.link_semantic_button.setObjectName("linkMindMapSemantic")
        self.clear_semantic_button = QPushButton("Make Annotation Only")
        self.clear_semantic_button.setObjectName("clearMindMapSemantic")
        self.link_semantic_button.clicked.connect(self.link_to_selected_semantic)
        self.clear_semantic_button.clicked.connect(self.clear_semantic_anchor)
        anchor_row = QHBoxLayout()
        anchor_row.addWidget(QLabel("Semantic link:"))
        anchor_row.addWidget(self.anchor_state)
        anchor_row.addWidget(self.anchor_target, 1)
        anchor_row.addWidget(self.link_semantic_button)
        anchor_row.addWidget(self.clear_semantic_button)

        self.delete_preview = QFrame()
        self.delete_preview.setObjectName("mindMapDeletePreview")
        delete_layout = QHBoxLayout(self.delete_preview)
        self.delete_explanation = QLabel()
        self.delete_subtree_button = QPushButton("Delete Entire Subtree")
        self.promote_children_button = QPushButton("Delete Topic; Promote Children")
        self.cancel_delete_button = QPushButton("Cancel")
        self.delete_subtree_button.clicked.connect(lambda: self._delete(False))
        self.promote_children_button.clicked.connect(lambda: self._delete(True))
        self.cancel_delete_button.clicked.connect(self.delete_preview.hide)
        delete_layout.addWidget(self.delete_explanation, 1)
        delete_layout.addWidget(self.delete_subtree_button)
        delete_layout.addWidget(self.promote_children_button)
        delete_layout.addWidget(self.cancel_delete_button)
        self.delete_preview.hide()

        self.status = QLabel()
        self.status.setObjectName("mindMapStatus")
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.canvas, 1)
        layout.addLayout(editor)
        layout.addLayout(cross_links)
        layout.addLayout(anchor_row)
        layout.addWidget(self.delete_preview)
        layout.addWidget(self.status)
        self.refresh(client.snapshot())
        if kernel is not None:
            self.update_shared_selection(kernel.selection.state)

    def refresh(self, project: Project) -> None:
        document = self._document(project)
        if document is None:
            self.header.setText("Mind map unavailable")
            return
        self.header.setText(document.title)
        index = self.layout_choice.findData(document.layout)
        if index >= 0:
            self.layout_choice.setCurrentIndex(index)
        self.canvas.set_vector_scene(layout_mind_map(document))
        self.cross_link_target.clear()

        def add_topics(topic: Topic, depth: int = 0) -> None:
            self.cross_link_target.addItem(f"{'  ' * depth}{topic.text}", topic.id)
            for child in topic.children:
                add_topics(child, depth + 1)

        add_topics(document.root)
        selected = self._selected_id
        if selected is None or find_topic(document.root, selected) is None:
            selected = document.root.id
        self._select_topic(selected)
        self.canvas.select_objects((selected,))

    def _document(self, project: Project) -> MindMapDiagram | None:
        if self._kernel is not None and self._kernel.revision == project.revision:
            resolved = self._kernel.queries.resolved_document(self.diagram_id)
            if isinstance(resolved, MindMapDiagram):
                return resolved
        return next(
            (
                item
                for item in project.documents
                if isinstance(item, MindMapDiagram) and item.id == self.diagram_id
            ),
            None,
        )

    def _selected(self) -> tuple[MindMapDiagram, Topic] | None:
        document = self._document(self._client.snapshot())
        if document is None or self._selected_id is None:
            return None
        topic = find_topic(document.root, self._selected_id)
        return (document, topic) if topic is not None else None

    def selected_topic(self) -> tuple[MindMapDiagram, Topic] | None:
        """Return the semantic selection without exposing canvas implementation state."""

        return self._selected()

    def select_topic(self, topic_id: str) -> None:
        """Reveal a topic after navigation or semantic paste."""

        self._select_topic(topic_id)
        self.canvas.select_objects((topic_id,))

    def _select_topic(self, topic_id: str) -> None:
        document = self._document(self._client.snapshot())
        topic = find_topic(document.root, topic_id) if document is not None else None
        if topic is None:
            return
        self._selected_id = topic_id
        self.topic_text.setText(topic.text)
        self.topic_notes.setPlainText(topic.notes)
        self.topic_links.setPlainText("\n".join(topic.links))
        self.topic_attachments.setText(", ".join(topic.attachments))
        is_root = document is not None and topic_id == document.root.id
        self.promote_button.setEnabled(not is_root)
        self.demote_button.setEnabled(not is_root)
        self.delete_button.setEnabled(not is_root)
        self._update_anchor_state(topic)
        self.live_label_button.setEnabled(
            document is not None
            and document.live_projection is not None
            and topic.semantic_id is not None
            and topic.label_override is not None
        )

    def update_shared_selection(self, state: SelectionState) -> None:
        self._anchor_target = state.primary
        kernel = self._kernel
        value = (
            kernel.queries.semantic_object(state.primary)
            if (kernel is not None and state.primary is not None)
            else None
        )
        usable = value is not None and value.kind not in {
            SemanticObjectKind.VIEW,
            SemanticObjectKind.GLYPH,
            SemanticObjectKind.ANNOTATION,
        }
        self.link_semantic_button.setEnabled(usable)
        if value is None:
            self.anchor_target.setText("Select code in DRAKON or Code Visualizer first.")
        else:
            self.anchor_target.setText(
                f"Selected target: {value.label} · {value.kind.value} · {value.id}"
            )

    def _update_anchor_state(self, topic: Topic) -> None:
        kernel = self._kernel
        semantic = (
            kernel.queries.semantic_object(topic.semantic_id)
            if kernel is not None and topic.semantic_id is not None
            else None
        )
        if topic.semantic_id is None:
            self.anchor_state.setText("Annotation only")
            self.clear_semantic_button.setEnabled(False)
        else:
            label = semantic.label if semantic is not None else "Unresolved semantic object"
            self.anchor_state.setText(f"Linked: {label} · {topic.semantic_id}")
            self.clear_semantic_button.setEnabled(True)

    def link_to_selected_semantic(self) -> None:
        selected = self._selected()
        kernel = self._kernel
        if selected is None or kernel is None or self._anchor_target is None:
            self.status.setText("Select a topic and an executable semantic target first.")
            return
        semantic = kernel.queries.semantic_object(self._anchor_target)
        if semantic is None or semantic.kind in {
            SemanticObjectKind.VIEW,
            SemanticObjectKind.GLYPH,
            SemanticObjectKind.ANNOTATION,
        }:
            self.status.setText("The selected item is presentation only and cannot drive code.")
            return
        document, topic = selected
        self._after(
            self._client.set_view_anchor(
                document.id,
                topic.id,
                semantic_id=semantic.id,
            ),
            topic.id,
        )

    def clear_semantic_anchor(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        self._after(
            self._client.set_view_anchor(document.id, topic.id),
            topic.id,
        )

    def _after(self, result: object, selected_id: str | None = None) -> None:
        if not isinstance(result, CommandAccepted):
            self.status.setText("The semantic edit was rejected; the project is unchanged.")
            return
        if selected_id is not None:
            self._selected_id = selected_id
        self.refresh(self._client.snapshot())
        self.status.setText(f"Applied at revision {result.revision}")
        self.projectChanged.emit()

    def add_child(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        result = self._client.add_mindmap_topic(
            document.id,
            topic.id,
            "New child topic",
            len(topic.children),
        )
        new_id = result.affected_ids[-1] if isinstance(result, CommandAccepted) else None
        self._after(result, new_id)

    def add_sibling(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        parent = find_topic_parent(document.root, topic.id)
        if parent is None:
            self.add_child()
            return
        index = next(i for i, child in enumerate(parent.children) if child.id == topic.id) + 1
        result = self._client.add_mindmap_topic(
            document.id,
            parent.id,
            "New sibling topic",
            index,
        )
        new_id = result.affected_ids[-1] if isinstance(result, CommandAccepted) else None
        self._after(result, new_id)

    def promote(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        parent = find_topic_parent(document.root, topic.id)
        grandparent = find_topic_parent(document.root, parent.id) if parent is not None else None
        if parent is None or grandparent is None:
            self.status.setText("This topic is already at the highest movable level.")
            return
        parent_index = next(
            i for i, child in enumerate(grandparent.children) if child.id == parent.id
        )
        self._after(
            self._client.move_mindmap_topic(
                document.id,
                topic.id,
                grandparent.id,
                parent_index + 1,
            ),
            topic.id,
        )

    def demote(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        parent = find_topic_parent(document.root, topic.id)
        if parent is None:
            return
        index = next(i for i, child in enumerate(parent.children) if child.id == topic.id)
        if index == 0:
            self.status.setText("Demote needs a preceding sibling to become the new parent.")
            return
        new_parent = parent.children[index - 1]
        self._after(
            self._client.move_mindmap_topic(
                document.id,
                topic.id,
                new_parent.id,
                len(new_parent.children),
            ),
            topic.id,
        )

    def _reparent(self, topic_id: str, parent_id: str) -> None:
        document = self._document(self._client.snapshot())
        parent = find_topic(document.root, parent_id) if document is not None else None
        if document is None or parent is None:
            return
        self._after(
            self._client.move_mindmap_topic(
                document.id,
                topic_id,
                parent_id,
                len(parent.children),
            ),
            topic_id,
        )

    def toggle_collapsed(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        result = self._client.update_mindmap_topic(
            document.id,
            topic.id,
            topic.text,
            notes=topic.notes,
            collapsed=not topic.collapsed,
            links=topic.links,
            attachments=topic.attachments,
            update_label=False,
        )
        self._after(result, topic.id)

    def apply_topic(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        links = tuple(
            line.strip() for line in self.topic_links.toPlainText().splitlines() if line.strip()
        )
        attachments = tuple(
            value.strip() for value in self.topic_attachments.text().split(",") if value.strip()
        )
        result = self._client.update_mindmap_topic(
            document.id,
            topic.id,
            self.topic_text.text().strip() or "Untitled topic",
            notes=self.topic_notes.toPlainText(),
            collapsed=topic.collapsed,
            links=links,
            attachments=attachments,
        )
        self._after(result, topic.id)

    def use_live_label(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        self._after(
            self._client.update_mindmap_topic(
                document.id,
                topic.id,
                topic.text,
                notes=topic.notes,
                collapsed=topic.collapsed,
                links=topic.links,
                attachments=topic.attachments,
                derive_label=True,
            ),
            topic.id,
        )

    def add_cross_link(self) -> None:
        selected = self._selected()
        target = self.cross_link_target.currentData()
        if selected is None or not isinstance(target, str):
            return
        document, topic = selected
        if target == topic.id:
            self.status.setText("A cross-link needs a different target topic.")
            return
        self._after(
            self._client.add_mindmap_cross_link(
                document.id,
                topic.id,
                target,
                label=self.cross_link_label.text(),
            ),
            topic.id,
        )

    def preview_delete(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        if topic.id == document.root.id:
            self.status.setText("A mind map must retain exactly one root topic.")
            return
        self.delete_explanation.setText(
            f"Delete “{topic.text}”? Choose whether its {len(topic.children)} direct child"
            f"{'ren' if len(topic.children) != 1 else ''} are deleted or promoted."
        )
        self.delete_preview.show()

    def _delete(self, promote_children: bool) -> None:
        selected = self._selected()
        if selected is None:
            return
        document, topic = selected
        parent = find_topic_parent(document.root, topic.id)
        result = self._client.remove_mindmap_topic(
            document.id,
            topic.id,
            promote_children=promote_children,
        )
        self.delete_preview.hide()
        self._after(result, parent.id if parent is not None else document.root.id)

    def _set_layout(self) -> None:
        document = self._document(self._client.snapshot())
        layout = self.layout_choice.currentData()
        if document is not None and isinstance(layout, str):
            self._after(self._client.set_mindmap_layout(document.id, layout), self._selected_id)

    def _fit(self) -> None:
        self.canvas.fit_content()
