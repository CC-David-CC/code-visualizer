"""Finite state machines: one schema, three notations, one ProgramModel lowering."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import TYPE_CHECKING

from code_visualizer.domain.intentional import (
    BundleReference,
    ConceptDefinition,
    DomainIssue,
    DomainModel,
    DomainSchema,
    DomainWorkspace,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
    RoleBinding,
    RoleDefinition,
    ValueKind,
)
from code_visualizer.domain.notation import (
    NotationColumn,
    NotationDefinition,
    NotationEdgeRule,
    NotationField,
    NotationKind,
    NotationNodeRule,
)
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAssignment,
    ProgramCase,
    ProgramExpression,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramLoop,
    ProgramModel,
    ProgramModule,
    ProgramOutput,
    ProgramParameter,
    ProgramSelect,
    ProgramSequence,
    ProgramStatement,
    ProgramSymbol,
    ProgramSymbolKind,
    ProgramTransfer,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import CallableKind, LoopKind, SelectMode, TransferKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    OriginLink,
    OriginMap,
    Representation,
    TransformationDefinition,
    derived_id,
)
from code_visualizer.generation.transformation import (
    RegisteredTransformation,
    TransformationError,
    TransformationInput,
    TransformationResult,
)

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionBundle

SCHEMA_ID = "fsm:schema"
BUNDLE_REFERENCE = BundleReference("org.codevisualizer.fsm", "1")
FSM_REPRESENTATION = Representation("org.codevisualizer.fsm", "1")
FSM_TRANSFORMATION = TransformationDefinition(
    "org.codevisualizer.fsm.to_program",
    "1",
    FSM_REPRESENTATION,
    PROGRAM_REPRESENTATION,
    description="Lower state/event transitions and message actions into typed ProgramModel.",
)


def fsm_schema() -> DomainSchema:
    def name(concept: str) -> PropertyDefinition:
        return PropertyDefinition(f"fsm:{concept}:name", "Name", required=True)

    def reference(role: str, target: str, *, required: bool = True) -> RoleDefinition:
        return RoleDefinition(role, role.rsplit(":", 1)[-1].title(), (target,), int(required), 1)

    return DomainSchema(
        SCHEMA_ID,
        FSM_REPRESENTATION.id,
        FSM_REPRESENTATION.version,
        (
            ConceptDefinition(
                "fsm:machine",
                "State machine",
                (
                    name("machine"),
                    PropertyDefinition(
                        "fsm:machine:steps",
                        "Event cycles",
                        ValueKind.INTEGER,
                        default=3,
                        minimum=1,
                        maximum=10000,
                    ),
                ),
                (
                    RoleDefinition("fsm:machine:states", "States", ("fsm:state",), 1),
                    RoleDefinition("fsm:machine:transitions", "Transitions", ("fsm:transition",)),
                    RoleDefinition("fsm:machine:events", "Events", ("fsm:event",), 1),
                    RoleDefinition("fsm:machine:actions", "Actions", ("fsm:action",)),
                ),
                (reference("fsm:machine:initial", "fsm:state"),),
                display_property_id="fsm:machine:name",
                description="An ordered event sequence drives transitions from the initial state.",
            ),
            ConceptDefinition(
                "fsm:state", "State", (name("state"),), display_property_id="fsm:state:name"
            ),
            ConceptDefinition(
                "fsm:event", "Event", (name("event"),), display_property_id="fsm:event:name"
            ),
            ConceptDefinition(
                "fsm:action",
                "Action",
                (
                    name("action"),
                    PropertyDefinition("fsm:action:message", "Message", required=True),
                ),
                display_property_id="fsm:action:name",
            ),
            ConceptDefinition(
                "fsm:transition",
                "Transition",
                reference_roles=(
                    reference("fsm:transition:source", "fsm:state"),
                    reference("fsm:transition:event", "fsm:event"),
                    reference("fsm:transition:target", "fsm:state"),
                    reference("fsm:transition:action", "fsm:action", required=False),
                ),
            ),
        ),
        BUNDLE_REFERENCE,
        "Finite state machines with stable state, transition, event, and action identities.",
    )


def fsm_notations() -> tuple[NotationDefinition, ...]:
    return (
        NotationDefinition(
            "fsm:graph",
            "State graph",
            NotationKind.GRAPH,
            node_rules=(NotationNodeRule("fsm:state", "fsm:state:name"),),
            edge_rules=(
                NotationEdgeRule(
                    "fsm:transition",
                    "fsm:transition:source",
                    "fsm:transition:target",
                    label_fields=(NotationField("fsm:event:name", ("fsm:transition:event",)),),
                ),
            ),
            layout="radial",
            schema_id=SCHEMA_ID,
        ),
        NotationDefinition(
            "fsm:table",
            "Transition table",
            NotationKind.TABLE,
            concept_ids=("fsm:transition",),
            columns=(
                NotationColumn(
                    "source", "Source", NotationField("fsm:state:name", ("fsm:transition:source",))
                ),
                NotationColumn(
                    "event", "Event", NotationField("fsm:event:name", ("fsm:transition:event",))
                ),
                NotationColumn(
                    "action",
                    "Action",
                    NotationField("fsm:action:message", ("fsm:transition:action",)),
                ),
                NotationColumn(
                    "target", "Target", NotationField("fsm:state:name", ("fsm:transition:target",))
                ),
            ),
            schema_id=SCHEMA_ID,
        ),
        NotationDefinition(
            "fsm:form",
            "Hierarchy and properties",
            NotationKind.TREE_FORM,
            node_rules=(
                NotationNodeRule(
                    "fsm:transition",
                    label_fields=(
                        NotationField("fsm:state:name", ("fsm:transition:source",)),
                        NotationField("fsm:event:name", ("fsm:transition:event",)),
                        NotationField("fsm:state:name", ("fsm:transition:target",)),
                    ),
                ),
            ),
            schema_id=SCHEMA_ID,
        ),
    )


def validate_fsm(_project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    issues: list[DomainIssue] = []
    for node in model.nodes:
        if node.concept_id != "fsm:transition":
            name = node.property(f"{node.concept_id}:name")
            if isinstance(name, str) and not name.strip():
                issues.append(
                    DomainIssue(
                        "FSM_EMPTY_NAME",
                        "A named FSM object needs a nonempty name",
                        node.id,
                        incomplete=True,
                    )
                )
    for root_id in model.roots:
        machine = model.node(root_id)
        if machine is None or machine.concept_id != "fsm:machine":
            issues.append(DomainIssue("FSM_ROOT", "FSM roots must be state machines", root_id))
            continue
        owned = {
            concept: set(machine.child_ids(f"fsm:machine:{role}"))
            for concept, role in (("state", "states"), ("event", "events"), ("action", "actions"))
        }
        initial = machine.reference_ids("fsm:machine:initial")
        if initial and initial[0] not in owned["state"]:
            issues.append(
                DomainIssue(
                    "FSM_INITIAL_OWNER", "Initial state belongs to another machine", machine.id
                )
            )
        for concept in ("state", "event"):
            names: set[str] = set()
            for identity in sorted(owned[concept]):
                named_node = model.node(identity)
                label = str(named_node.property(f"fsm:{concept}:name")) if named_node else ""
                if label in names:
                    issues.append(
                        DomainIssue(
                            "FSM_DUPLICATE_NAME",
                            f"Duplicate {concept} name {label!r}",
                            identity,
                            incomplete=True,
                        )
                    )
                names.add(label)
        pairs: set[tuple[str, str]] = set()
        for transition_id in machine.child_ids("fsm:machine:transitions"):
            transition = model.node(transition_id)
            if transition is None:
                continue
            for role, concept in (
                ("source", "state"),
                ("target", "state"),
                ("event", "event"),
                ("action", "action"),
            ):
                if set(transition.reference_ids(f"fsm:transition:{role}")) - owned[concept]:
                    issues.append(
                        DomainIssue(
                            "FSM_REFERENCE_OWNER",
                            f"Transition {role} must belong to its machine",
                            transition.id,
                        )
                    )
            source = transition.reference_ids("fsm:transition:source")
            event = transition.reference_ids("fsm:transition:event")
            if source and event:
                pair = source[0], event[0]
                if pair in pairs:
                    issues.append(
                        DomainIssue(
                            "FSM_AMBIGUOUS_TRANSITION",
                            "A state/event pair has multiple transitions",
                            transition.id,
                            incomplete=True,
                        )
                    )
                pairs.add(pair)
    return tuple(issues)


def lower_fsm(snapshot: TransformationInput) -> TransformationResult:
    if not isinstance(snapshot.value, DomainModel):
        raise TransformationError("FSM_INPUT", "FSM lowering requires domain instances")
    model = snapshot.value
    functions: list[ProgramFunction] = []
    symbols: list[ProgramSymbol] = []
    explicit_origins: dict[str, tuple[str, ...]] = {}

    def identity(source_id: str, role: str, origins: tuple[str, ...] = ()) -> str:
        result = derived_id(FSM_TRANSFORMATION.key, source_id, role)
        explicit_origins[result] = origins or (source_id,)
        return result

    def require_node(node_id: str) -> IntentionalNode:
        value = model.node(node_id)
        if value is None:
            raise TransformationError("FSM_REFERENCE", f"Missing FSM object {node_id!r}")
        return value

    for machine_id in model.roots:
        machine = require_node(machine_id)
        function_id = identity(machine.id, "function")
        symbol_ids = {
            name: identity(machine.id, f"symbol:{name}") for name in ("events", "event", "state")
        }

        def expression(
            owner: str,
            field: str,
            source: str,
            role: ExpressionRole = ExpressionRole.VALUE,
            bound_symbols: dict[str, str] = symbol_ids,
        ) -> ProgramExpression:
            return make_program_expression(
                owner,
                field,
                source,
                role,
                resolve_symbol=lambda referenced_name, _context: bound_symbols.get(referenced_name),
                identity_namespace=FSM_TRANSFORMATION.key,
            )

        def assign(
            source: str,
            role: str,
            target: str,
            value: str,
            origins: tuple[str, ...] = (),
            bound_symbols: dict[str, str] = symbol_ids,
        ) -> ProgramAssignment:
            owner = identity(source, role, origins)
            return ProgramAssignment(
                owner,
                expression(owner, "target", target, ExpressionRole.TARGET),
                expression(owner, "value", value),
                written_symbol_ids=(bound_symbols[target],),
            )

        def output(
            source: str, role: str, message: str, origins: tuple[str, ...] = ()
        ) -> ProgramOutput:
            owner = identity(source, role, origins)
            return ProgramOutput(owner, expression(owner, "expression", repr(message)))

        initial = require_node(machine.reference_ids("fsm:machine:initial")[0])
        state_names = {
            node.id: str(node.property("fsm:state:name"))
            for node in (require_node(item) for item in machine.child_ids("fsm:machine:states"))
        }
        cases: list[ProgramCase] = []
        for transition_id in machine.child_ids("fsm:machine:transitions"):
            transition = require_node(transition_id)
            source = require_node(transition.reference_ids("fsm:transition:source")[0])
            target = require_node(transition.reference_ids("fsm:transition:target")[0])
            event = require_node(transition.reference_ids("fsm:transition:event")[0])
            event_name = str(event.property("fsm:event:name"))
            origins = (transition.id, target.id, event.id)
            statements: list[ProgramStatement] = [
                assign(transition.id, "enter-state", "state", repr(target.id), origins)
            ]
            for action_id in transition.reference_ids("fsm:transition:action"):
                action = require_node(action_id)
                statements.append(
                    output(
                        transition.id,
                        f"action:{action.id}",
                        str(action.property("fsm:action:message")),
                        (*origins, action.id),
                    )
                )
            label = f"{state_names[source.id]} --{event_name}--> {state_names[target.id]}"
            statements.append(output(transition.id, "transition-output", label, origins))
            case_id = identity(transition.id, "case")
            cases.append(
                ProgramCase(
                    case_id,
                    label,
                    ProgramSequence(identity(transition.id, "body", origins), tuple(statements)),
                    expression(
                        case_id,
                        "condition",
                        f"state == {source.id!r} and event == {event_name!r}",
                        ExpressionRole.CONDITION,
                    ),
                    expression(case_id, "pattern", "_", ExpressionRole.PATTERN),
                    None,
                    False,
                )
            )
        fallback_id = identity(machine.id, "unknown-event")
        failure_id = identity(machine.id, "unknown-event-raise")
        cases.append(
            ProgramCase(
                fallback_id,
                "No matching transition",
                ProgramSequence(
                    identity(machine.id, "unknown-event-body"),
                    (
                        ProgramTransfer(
                            failure_id,
                            TransferKind.RAISE,
                            expression(
                                failure_id,
                                "expression",
                                "ValueError(f'No transition for {state!r} and {event!r}')",
                            ),
                            None,
                        ),
                    ),
                ),
                expression(fallback_id, "condition", "True", ExpressionRole.CONDITION),
                expression(fallback_id, "pattern", "_", ExpressionRole.PATTERN),
                None,
                True,
            )
        )
        select_id = identity(machine.id, "dispatch")
        select = ProgramSelect(
            select_id,
            expression(select_id, "expression", "state"),
            tuple(cases),
            SelectMode.CONDITIONS,
            None,
        )
        loop_id = identity(machine.id, "events-loop")
        event_names = tuple(
            str(require_node(item).property("fsm:event:name"))
            for item in machine.child_ids("fsm:machine:events")
        )
        cycles = machine.property("fsm:machine:steps")
        cycles = cycles if isinstance(cycles, int) else 3
        loop = ProgramLoop(
            loop_id,
            LoopKind.FOR,
            ProgramSequence(identity(machine.id, "events-body"), (select,)),
            ProgramSequence(identity(machine.id, "events-else")),
            expression(loop_id, "condition", "True", ExpressionRole.CONDITION),
            expression(loop_id, "target", "event", ExpressionRole.TARGET),
            expression(
                loop_id, "iterable", f"events if events is not None else {event_names!r} * {cycles}"
            ),
            expression(loop_id, "children", "lambda node: ()"),
            expression(loop_id, "delay_seconds", "0"),
        )
        initial_assignment = assign(
            machine.id, "initial-state", "state", repr(initial.id), (machine.id, initial.id)
        )
        return_id = identity(machine.id, "return-state")
        parameter_id = identity(machine.id, "events-parameter")
        function_symbol = identity(machine.id, "function-symbol")
        function_name = "run_machine_" + function_id.rsplit(":", 1)[-1][:12]
        functions.append(
            ProgramFunction(
                function_id,
                function_symbol,
                function_name,
                str(machine.property("fsm:machine:name")),
                CallableKind.SYNC,
                (
                    ProgramParameter(
                        parameter_id,
                        symbol_ids["events"],
                        "events",
                        default=expression(parameter_id, "default", "None", ExpressionRole.DEFAULT),
                    ),
                ),
                None,
                (),
                "Generated from canonical state-machine intentions.",
                None,
                ProgramSequence(
                    identity(machine.id, "body"),
                    (
                        initial_assignment,
                        output(initial.id, "initial-output", state_names[initial.id]),
                        loop,
                        ProgramTransfer(
                            return_id,
                            TransferKind.RETURN,
                            expression(return_id, "expression", f"{state_names!r}[state]"),
                            None,
                        ),
                    ),
                ),
            )
        )
        symbols.extend(
            (
                ProgramSymbol(
                    function_symbol,
                    function_name,
                    ProgramSymbolKind.FUNCTION,
                    function_id,
                    function_id,
                ),
                ProgramSymbol(
                    symbol_ids["events"],
                    "events",
                    ProgramSymbolKind.PARAMETER,
                    function_id,
                    parameter_id,
                ),
                ProgramSymbol(
                    symbol_ids["state"],
                    "state",
                    ProgramSymbolKind.LOCAL,
                    function_id,
                    initial_assignment.id,
                ),
                ProgramSymbol(
                    symbol_ids["event"], "event", ProgramSymbolKind.LOCAL, function_id, loop_id
                ),
            )
        )
    program = ProgramModel(
        tuple(functions),
        tuple(symbols),
        modules=(
            ProgramModule(
                identity(model.id, "module"),
                "main",
                tuple(ProgramFunctionReference(function.id) for function in functions),
            ),
        ),
    )
    links: dict[str, tuple[str, ...]] = {}

    def collect(value: object, inherited: tuple[str, ...]) -> None:
        if isinstance(value, tuple):
            for item in value:
                collect(item, inherited)
        elif is_dataclass(value) and not isinstance(value, type):
            raw_id = getattr(value, "id", None)
            origins = (
                explicit_origins.get(raw_id, inherited) if isinstance(raw_id, str) else inherited
            )
            if isinstance(raw_id, str):
                links[raw_id] = tuple(sorted(set(origins)))
            for item in fields(value):
                collect(getattr(value, item.name), origins)

    collect(program, model.roots)
    return TransformationResult(
        PROGRAM_REPRESENTATION,
        program,
        OriginMap(
            snapshot.project.id,
            snapshot.project.revision,
            tuple(OriginLink(key, value) for key, value in sorted(links.items())),
        ),
        tuple(function.id for function in functions),
    )


def traffic_light_project() -> Project:
    def named(identity: str, concept: str, name: str, **properties: str | int) -> IntentionalNode:
        return IntentionalNode(
            identity,
            f"fsm:{concept}",
            (
                PropertyValue(f"fsm:{concept}:name", name),
                *(
                    PropertyValue(f"fsm:{concept}:{key}", value)
                    for key, value in properties.items()
                ),
            ),
        )

    states = tuple(
        named(f"traffic:{name.lower()}", "state", name) for name in ("Red", "Green", "Yellow")
    )
    event = named("traffic:timer", "event", "timer")
    action = named("traffic:signal", "action", "Signal change", message="The signal changes.")
    transitions = tuple(
        IntentionalNode(
            f"traffic:{source}-{target}",
            "fsm:transition",
            references=(
                RoleBinding("fsm:transition:source", (f"traffic:{source}",)),
                RoleBinding("fsm:transition:event", (event.id,)),
                RoleBinding("fsm:transition:target", (f"traffic:{target}",)),
                RoleBinding("fsm:transition:action", (action.id,)),
            ),
        )
        for source, target in (("red", "green"), ("green", "yellow"), ("yellow", "red"))
    )
    machine = IntentionalNode(
        "traffic:machine",
        "fsm:machine",
        (PropertyValue("fsm:machine:name", "Traffic Light"), PropertyValue("fsm:machine:steps", 3)),
        (
            RoleBinding("fsm:machine:states", tuple(node.id for node in states)),
            RoleBinding("fsm:machine:transitions", tuple(node.id for node in transitions)),
            RoleBinding("fsm:machine:events", (event.id,)),
            RoleBinding("fsm:machine:actions", (action.id,)),
        ),
        (RoleBinding("fsm:machine:initial", (states[0].id,)),),
    )
    model = DomainModel(
        "traffic:model",
        SCHEMA_ID,
        "1",
        (machine.id,),
        (machine, *states, event, action, *transitions),
        "Traffic Light",
    )
    return Project(
        "project_traffic_light",
        "Traffic Light — Intentional Domain Workbench",
        (),
        description=(
            "One state machine edited through graph, transition table, and hierarchy; "
            "traced activity returns to its original intentions."
        ),
        domain_workspace=DomainWorkspace((fsm_schema(),), (model,), (BUNDLE_REFERENCE,)),
    )


def fsm_bundle() -> DomainExtensionBundle:
    # Bundle composition is an explicit boundary, never an import from project data.
    from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
    from code_visualizer.extensions.registry import DomainExtensionBundle

    schema = fsm_schema()
    return DomainExtensionBundle(
        BUNDLE_REFERENCE.id,
        BUNDLE_REFERENCE.version,
        schemas=(schema,),
        validators=(validate_fsm,),
        notations=fsm_notations(),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(BundleReference("code_visualizer.program", "1"),),
        transformations=(
            RegisteredTransformation(
                FSM_TRANSFORMATION, lower_fsm, schema_id=schema.id, schema_version=schema.version
            ),
        ),
    )
