"""Inert, editable language data for the existing Traffic Light teaching example."""

from dataclasses import replace
from itertools import count

from code_visualizer.domain import language as l
from code_visualizer.domain import notation_syntax as v
from code_visualizer.domain.notation import NotationDefinition, NotationKind
from code_visualizer.domain.program_kinds import TransferKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    Representation,
    TransformationDefinition,
)
from code_visualizer.extensions.fsm import traffic_light_project


def _transition_sentences(schema_id: str) -> NotationDefinition:
    """A user-editable textual notation composed from the generic visual vocabulary."""

    transitions = v.VisualRepeat(
        "authored:sentences:transitions",
        v.NotationRelated(
            "authored:sentences:query-transitions",
            "sentence:state",
            role_id="fsm:transition:source",
            incoming=True,
        ),
        "sentence:transition",
        v.VisualGroup(
            "authored:sentences:sentence",
            children=(
                v.VisualText("authored:sentences:when", "When"),
                v.VisualField(
                    "authored:sentences:event",
                    "sentence:transition",
                    "fsm:event:name",
                    ("fsm:transition:event",),
                ),
                v.VisualText("authored:sentences:becomes", "arrives, change to"),
                v.VisualField(
                    "authored:sentences:target",
                    "sentence:transition",
                    "fsm:state:name",
                    ("fsm:transition:target",),
                ),
            ),
        ),
        binding_name="transition",
    )
    states = v.VisualRepeat(
        "authored:sentences:states",
        v.NotationObjects("authored:sentences:query-states", "fsm:state"),
        "sentence:state",
        v.VisualBox(
            "authored:sentences:card",
            v.VisualGroup(
                "authored:sentences:state-body",
                v.VisualLayout.COLUMN,
                (
                    v.VisualField(
                        "authored:sentences:state-name",
                        "sentence:state",
                        "fsm:state:name",
                        font_size=20.0,
                    ),
                    transitions,
                ),
            ),
            fill="#f1f6ff",
        ),
        binding_name="state",
        gap=18.0,
    )
    return NotationDefinition(
        "authored:fsm:sentences",
        "Transition sentences",
        NotationKind.COMPOSED,
        schema_id=schema_id,
        body=v.VisualGroup(
            "authored:sentences:body",
            v.VisualLayout.COLUMN,
            (
                v.VisualText(
                    "authored:sentences:title",
                    "Read the machine in its own words",
                    font_size=22.0,
                    strong=True,
                ),
                v.VisualText(
                    "authored:sentences:hint", "Edit a state or event name in any sentence."
                ),
                states,
            ),
            gap=16.0,
        ),
    )


def authored_traffic_light_project() -> Project:
    """Reuse the existing FSM schema/instances only; all executable behavior is data."""
    project = traffic_light_project()
    schema = replace(
        project.domain_workspace.schemas[0], namespace="example.authored.fsm", bundle=None
    )
    serial = count()

    def identity() -> str:
        return f"recipe:syntax:{next(serial)}"

    def variable(binding: str) -> l.QueryVariable:
        return l.QueryVariable(identity(), binding)

    def role(binding: str, field: str) -> l.QueryRole:
        return l.QueryRole(identity(), variable(binding), field)

    def first(binding: str, field: str) -> l.QueryUnary:
        return l.QueryUnary(identity(), l.QueryUnaryOperator.FIRST, role(binding, field))

    def prop(binding: str, field: str) -> l.QueryProperty:
        return l.QueryProperty(identity(), variable(binding), field)

    def reference_id(binding: str, field: str) -> l.QueryIdentity:
        return l.QueryIdentity(identity(), first(binding, field))

    def reference_property(binding: str, role_id: str, property_id: str) -> l.QueryProperty:
        return l.QueryProperty(identity(), first(binding, role_id), property_id)

    def literal(query: l.Query) -> l.RuntimeLiteral:
        return l.RuntimeLiteral(identity(), query)

    def runtime_variable(symbol_id: str) -> l.RuntimeVariable:
        return l.RuntimeVariable(identity(), symbol_id)

    def runtime_binary(
        operator: l.RuntimeBinaryOperator, left: l.RuntimeExpression, right: l.RuntimeExpression
    ) -> l.RuntimeBinary:
        return l.RuntimeBinary(identity(), operator, left, right)

    unique = l.ValidatorDefinition(
        "recipe:unique-transitions",
        "fsm:machine",
        "rule:machine",
        l.QueryUnique(
            identity(),
            role("rule:machine", "fsm:machine:transitions"),
            "rule:transition",
            l.QueryTuple(
                identity(),
                (
                    reference_id("rule:transition", "fsm:transition:source"),
                    reference_id("rule:transition", "fsm:transition:event"),
                ),
            ),
        ),
        "Each state and event pair must select only one transition",
        "AUTHORED_UNIQUE_TRANSITION",
    )
    initial = l.ValidatorDefinition(
        "recipe:initial-owned",
        "fsm:machine",
        "rule:initial-machine",
        l.QueryBinary(
            identity(),
            l.QueryBinaryOperator.IN,
            first("rule:initial-machine", "fsm:machine:initial"),
            role("rule:initial-machine", "fsm:machine:states"),
        ),
        "The initial state must belong to this machine",
        "AUTHORED_INITIAL_STATE",
    )
    state, event = "recipe:symbol:state", "recipe:symbol:event"
    transition_body = (
        l.TemplateIf(
            "recipe:transition-if",
            runtime_binary(
                l.RuntimeBinaryOperator.AND,
                runtime_binary(
                    l.RuntimeBinaryOperator.EQUAL,
                    runtime_variable(state),
                    literal(reference_id("build:transition", "fsm:transition:source")),
                ),
                runtime_binary(
                    l.RuntimeBinaryOperator.EQUAL,
                    runtime_variable(event),
                    literal(
                        reference_property(
                            "build:transition", "fsm:transition:event", "fsm:event:name"
                        )
                    ),
                ),
            ),
            true_body=(
                l.TemplateAssignment(
                    "recipe:enter-target",
                    state,
                    literal(reference_id("build:transition", "fsm:transition:target")),
                ),
                l.TemplateOutput(
                    "recipe:show-target",
                    literal(
                        reference_property(
                            "build:transition", "fsm:transition:target", "fsm:state:name"
                        )
                    ),
                ),
                l.TemplateExpand(
                    "recipe:actions",
                    role("build:transition", "fsm:transition:action"),
                    "build:action",
                    (
                        l.TemplateOutput(
                            "recipe:action-output",
                            literal(prop("build:action", "fsm:action:message")),
                        ),
                    ),
                ),
                l.TemplateTransfer("recipe:next-event", TransferKind.CONTINUE),
            ),
            origins=(
                role("build:transition", "fsm:transition:target"),
                role("build:transition", "fsm:transition:event"),
            ),
        ),
    )
    recipe = l.AuthoredTransformation(
        TransformationDefinition(
            "recipe:lower",
            "1",
            Representation(schema.namespace, schema.version),
            PROGRAM_REPRESENTATION,
        ),
        (
            l.FunctionTemplate(
                "recipe:function",
                l.QueryNodes(identity(), "fsm:machine", roots_only=True),
                "build:machine",
                display_name=prop("build:machine", "fsm:machine:name"),
                symbols=(l.TemplateSymbol(state, "state"), l.TemplateSymbol(event, "event")),
                body=(
                    l.TemplateAssignment(
                        "recipe:initialize",
                        state,
                        literal(reference_id("build:machine", "fsm:machine:initial")),
                        origins=(role("build:machine", "fsm:machine:initial"),),
                    ),
                    l.TemplateFor(
                        "recipe:event-loop",
                        event,
                        runtime_binary(
                            l.RuntimeBinaryOperator.MULTIPLY,
                            literal(
                                l.QueryMap(
                                    identity(),
                                    role("build:machine", "fsm:machine:events"),
                                    "build:event",
                                    prop("build:event", "fsm:event:name"),
                                )
                            ),
                            literal(prop("build:machine", "fsm:machine:steps")),
                        ),
                        body=(
                            l.TemplateExpand(
                                "recipe:transitions",
                                role("build:machine", "fsm:machine:transitions"),
                                "build:transition",
                                transition_body,
                            ),
                            l.TemplateTransfer(
                                "recipe:unhandled",
                                TransferKind.RAISE,
                                l.RuntimeCall(
                                    identity(),
                                    l.RuntimeBuiltin.VALUE_ERROR,
                                    (
                                        literal(
                                            l.QueryLiteral(
                                                identity(), "No transition accepts this event"
                                            )
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    l.TemplateTransfer(
                        "recipe:return-state", TransferKind.RETURN, runtime_variable(state)
                    ),
                ),
            ),
        ),
    )
    # These notation declarations are inert schema paths, copied from the existing
    # example as editable project-owned definitions, not an installed contribution.
    from code_visualizer.extensions.fsm import fsm_notations

    language = l.AuthoredDomainLanguage(
        "recipe:language",
        schema.id,
        schema.version,
        title="Editable Traffic Light language",
        notations=(
            *(replace(notation, id="authored:" + notation.id) for notation in fsm_notations()),
            _transition_sentences(schema.id),
        ),
        validators=(unique, initial),
        transformations=(recipe,),
    )
    return replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            schemas=(schema,),
            bundle_references=(),
            language_definitions=(language,),
        ),
    )
