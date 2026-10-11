import pytest

from code_visualizer.application.authority_contributions import (
    build_authority_handler_registry,
)
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.application.static_registry import StaticContributionRegistry
from code_visualizer.automation.protocol import RpcError
from code_visualizer.automation.service import (
    AccessMode,
    AutomationCapability,
    AutomationContext,
    AutomationService,
)
from code_visualizer.ui_qt.workbench import WORKBENCH_CONTRIBUTIONS


def test_static_registries_reject_duplicates_and_have_deterministic_order() -> None:
    registry: StaticContributionRegistry[str] = StaticContributionRegistry()
    registry.register("later", "L", order=20)
    registry.register("earlier-b", "B", order=10)
    registry.register("earlier-a", "A", order=10)
    assert tuple(item.id for item in registry.contributions()) == (
        "earlier-a",
        "earlier-b",
        "later",
    )
    with pytest.raises(ValueError, match="already registered"):
        registry.register("later", "duplicate")

    handlers = build_authority_handler_registry()
    assert handlers.get("drakon.replace") is not None
    assert handlers.get("program.statement.insert") is not None
    assert handlers.get("projection.materialize") is not None
    assert WORKBENCH_CONTRIBUTIONS.get("visualizer").attribute == "visualizer_dock"


def test_automation_invokes_statically_registered_kernel_capability() -> None:
    session = ProjectSession.new()
    service = AutomationService(session.authority, kernel=session.kernel)
    context = AutomationContext(
        "capability-reader",
        "capability-connection",
        AccessMode.COMMIT,
        frozenset({AutomationCapability.READ}),
    )
    try:
        result = service.dispatch(
            "capability.invoke",
            {
                "capability_id": "view.architecture",
                "inputs": {},
            },
            context,
        )
        assert isinstance(result, dict)
        assert result["kind"] == "architecture"
        advertised = service.dispatch("service.capabilities", {}, context)
        assert isinstance(advertised, dict)
        assert "capability.invoke" in advertised["methods"]
        with pytest.raises(RpcError, match="generate"):
            service.dispatch(
                "capability.invoke",
                {"capability_id": "python.generator", "inputs": {}},
                context,
            )
    finally:
        service.close()
        session.close()


def test_automation_reports_buildability_and_structured_incomplete_errors() -> None:
    session = ProjectSession.new()
    function = session.authority.snapshot().program_model.functions[0]
    inserted = session.client.insert_program_statement(
        function.id,
        function.body.id,
        0,
        "assignment",
        statement_id="automation_incomplete",
        target="answer",
        value="1",
        true_sequence_id="unused_true",
        false_sequence_id="unused_false",
    )
    assert isinstance(inserted, CommandAccepted)
    statement = session.authority.snapshot().program_model.functions[0].body.statements[0]
    replaced = session.client.replace_program_expression(
        function.id,
        statement.value.id,
        "answer +",
    )
    assert isinstance(replaced, CommandAccepted)

    service = AutomationService(session.authority, kernel=session.kernel)
    context = AutomationContext(
        "buildability-reader",
        "buildability-connection",
        AccessMode.COMMIT,
        frozenset(
            {
                AutomationCapability.READ,
                AutomationCapability.EXECUTE,
            }
        ),
    )
    try:
        validation = service.dispatch("validate.project", {}, context)
        assert isinstance(validation, dict)
        assert validation["buildability"] == "blocked"
        diagnostics = validation["diagnostics"]
        assert isinstance(diagnostics, list)
        assert "PROGRAM_INCOMPLETE_EXPRESSION" in {
            item["code"] for item in diagnostics if isinstance(item, dict)
        }

        with pytest.raises(RpcError) as preview_error:
            service.dispatch("generate.preview", {}, context)
        assert preview_error.value.data is not None
        assert preview_error.value.data["buildability"] == "blocked"

        diagram_id = session.authority.snapshot().documents[0].id
        with pytest.raises(RpcError) as run_error:
            service.dispatch(
                "test.run_diagram",
                {"arguments": "", "diagram_id": diagram_id},
                context,
            )
        assert run_error.value.data is not None
        assert run_error.value.data["buildability"] == "blocked"
    finally:
        service.close()
        session.close()
