"""Reference vocabularies are discoverable, ordinary authority transactions."""

from PySide6.QtWidgets import QInputDialog, QPushButton

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.domain.project import Project
from code_visualizer.extensions.foundations.units import units_schema
from code_visualizer.extensions.foundations.units_si import si_model
from code_visualizer.sdk.client import CodeVisualizerClient
from code_visualizer.ui_qt.features.domain_workbench.widget import DomainWorkbenchWidget


def test_si_vocabulary_install_from_ui_uses_one_undoable_authority_transaction(qtbot, monkeypatch):
    authority = ProjectAuthority(Project("vocabulary-ui", "Vocabulary workbench", ()))
    kernel = ProjectKernel(authority)
    client = CodeVisualizerClient(authority, actor_id="vocabulary-author")
    widget = DomainWorkbenchWidget()
    qtbot.addWidget(widget)
    widget.attach(kernel, client)
    monkeypatch.setattr(
        QInputDialog, "getItem", lambda *_a, **_k: ("foundation.units.si (1)", True)
    )
    button = widget.findChild(QPushButton, "addReferenceVocabulary")
    assert button is not None
    button.click()
    snapshot = authority.snapshot()
    assert snapshot.domain_workspace.schema(units_schema().id) == units_schema()
    assert snapshot.domain_workspace.model(si_model().id) == si_model()
    assert (
        BundleReference("foundation.units.si", "1") in snapshot.domain_workspace.bundle_references
    )
    assert kernel.revision == 1
    assert widget.current_model() == si_model()
    client.undo()
    assert authority.snapshot().domain_workspace.models == ()
    client.redo()
    assert authority.snapshot().domain_workspace.model(si_model().id) == si_model()
    widget.resize(1300, 900)
    widget.show()
    qtbot.waitExposed(widget)
    assert widget.grab().save(".test-reference-vocabulary.png")
    widget.attach(None)
    kernel.close()
