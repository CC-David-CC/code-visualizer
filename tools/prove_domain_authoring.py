"""Reproduce a complete domain workbench loop from a blank authority.

Run with the repository environment and PYTHONPATH=src. This script deliberately
imports no example factory or handwritten domain extension.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from itertools import count
from pathlib import Path

from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.commands import TypedCommand
from code_visualizer.application.domain_commands import (
    CreateDomainNode,
    PutDomainConcept,
    PutDomainModel,
    PutDomainPropertyDefinition,
    PutDomainRoleDefinition,
    PutDomainSchema,
    SetDomainReference,
)
from code_visualizer.application.domain_execution import trace_project
from code_visualizer.application.kernel import ProjectKernel
from code_visualizer.application.language_commands import (
    PutDomainLanguage,
    PutDomainNotation,
    PutDomainTransformation,
    PutDomainValidator,
)
from code_visualizer.application.messages import CommandAccepted, CommandResult
from code_visualizer.application.notations import (
    NotationTreeNode,
    field_cell,
    notation_edit_command,
)
from code_visualizer.application.runtime_sessions import RuntimeSessionState
from code_visualizer.domain import language as l
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.intentional import (
    ConceptDefinition,
    DomainModel,
    DomainSchema,
    IntentionalNode,
    PropertyDefinition,
    PropertyValue,
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
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import (
    PROGRAM_REPRESENTATION,
    Representation,
    TransformationDefinition,
)
from code_visualizer.execution import run_generated
from code_visualizer.extensions.builtin import intentional_bundle, program_bundle
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.generation import generate_python_project, generate_to_disk
from code_visualizer.generation.build import prepare_build
from code_visualizer.persistence import ProjectStore
from code_visualizer.persistence.decoding import project_from_json
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import CodeVisualizerClient
from code_visualizer.validation import assess_project

SCHEMA = "proof:schema"
MODEL = "proof:model"
LANGUAGE = "proof:language"
MACHINE = "proof:Machine"
STATE = "proof:State"
TRANSITION = "proof:Transition"
ROOT = "proof:toggle"
IDLE = "proof:idle"
ACTIVE = "proof:active"
ACTIVATE = "proof:activate"
DEACTIVATE = "proof:deactivate"
NOTATIONS = ("proof:graph", "proof:table", "proof:form")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _accepted(result: CommandResult) -> None:
    _require(isinstance(result, CommandAccepted), f"Authority rejected an edit: {result}")


def _language_behavior() -> tuple[l.ValidatorDefinition, l.AuthoredTransformation]:
    """Construct inert user-authored syntax; none of these values is executable code."""

    serial = count()

    def identity() -> str:
        return f"proof:syntax:{next(serial)}"

    def variable(binding: str) -> l.QueryVariable:
        return l.QueryVariable(identity(), binding)

    def role(binding: str, role_id: str) -> l.QueryRole:
        return l.QueryRole(identity(), variable(binding), role_id)

    def first(binding: str, role_id: str) -> l.QueryUnary:
        return l.QueryUnary(identity(), l.QueryUnaryOperator.FIRST, role(binding, role_id))

    def prop(binding: str, property_id: str) -> l.QueryProperty:
        return l.QueryProperty(identity(), variable(binding), property_id)

    def target_id() -> l.RuntimeLiteral:
        return l.RuntimeLiteral(
            identity(), l.QueryIdentity(identity(), first("transition", "proof:target"))
        )

    def origins() -> tuple[l.Query, ...]:
        return (variable("transition"), first("transition", "proof:target"))

    validator = l.ValidatorDefinition(
        "proof:deterministic",
        MACHINE,
        "machine",
        l.QueryUnique(
            identity(),
            role("machine", "proof:transitions"),
            "transition",
            l.QueryIdentity(identity(), first("transition", "proof:source")),
        ),
        "Each state has one outgoing transition",
        "PROOF_AMBIGUOUS_STATE",
    )
    current, previous, tick = "proof:current", "proof:previous", "proof:tick"
    update = l.TemplateIf(
        "proof:take-transition",
        l.RuntimeBinary(
            identity(),
            l.RuntimeBinaryOperator.EQUAL,
            l.RuntimeVariable(identity(), previous),
            l.RuntimeLiteral(
                identity(), l.QueryIdentity(identity(), first("transition", "proof:source"))
            ),
        ),
        (
            l.TemplateAssignment("proof:change-state", current, target_id(), origins()),
            l.TemplateOutput(
                "proof:show-state",
                l.RuntimeLiteral(
                    identity(),
                    l.QueryProperty(
                        identity(), first("transition", "proof:target"), "proof:state-name"
                    ),
                ),
                origins(),
            ),
        ),
        origins=origins(),
    )
    function = l.FunctionTemplate(
        "proof:function",
        l.QueryNodes(identity(), MACHINE, roots_only=True),
        "machine",
        identifier_prefix="run_toggle",
        display_name=prop("machine", "proof:machine-name"),
        symbols=(
            l.TemplateSymbol(current, "state"),
            l.TemplateSymbol(previous, "previous"),
            l.TemplateSymbol(tick, "tick"),
        ),
        body=(
            l.TemplateAssignment(
                "proof:initial-state",
                current,
                l.RuntimeLiteral(
                    identity(), l.QueryIdentity(identity(), first("machine", "proof:initial"))
                ),
            ),
            l.TemplateFor(
                "proof:steps",
                tick,
                l.RuntimeCall(
                    identity(),
                    l.RuntimeBuiltin.RANGE,
                    (l.RuntimeLiteral(identity(), prop("machine", "proof:step-count")),),
                ),
                (
                    l.TemplateAssignment(
                        "proof:remember-state", previous, l.RuntimeVariable(identity(), current)
                    ),
                    l.TemplateExpand(
                        "proof:expand-transitions",
                        role("machine", "proof:transitions"),
                        "transition",
                        (update,),
                    ),
                ),
            ),
        ),
    )
    return validator, l.AuthoredTransformation(
        TransformationDefinition(
            "proof:lower", "1", Representation("proof.authored.toggle", "1"), PROGRAM_REPRESENTATION
        ),
        (function,),
    )


def _notations() -> tuple[NotationDefinition, ...]:
    source = NotationField("proof:state-name", ("proof:source",))
    target = NotationField("proof:state-name", ("proof:target",))
    event = NotationField("proof:event-name")
    return (
        NotationDefinition(
            NOTATIONS[0],
            "Toggle graph",
            NotationKind.GRAPH,
            concept_ids=(STATE,),
            node_rules=(NotationNodeRule(STATE, "proof:state-name"),),
            edge_rules=(NotationEdgeRule(TRANSITION, "proof:source", "proof:target", (event,)),),
            schema_id=SCHEMA,
        ),
        NotationDefinition(
            NOTATIONS[1],
            "Transition table",
            NotationKind.TABLE,
            concept_ids=(TRANSITION,),
            columns=(
                NotationColumn("source", "Source", source),
                NotationColumn("event", "Event", event),
                NotationColumn("target", "Target", target),
            ),
            schema_id=SCHEMA,
        ),
        NotationDefinition(
            NOTATIONS[2],
            "Hierarchy and form",
            NotationKind.TREE_FORM,
            node_rules=(NotationNodeRule(TRANSITION, label_fields=(source, event, target)),),
            schema_id=SCHEMA,
        ),
    )


def _tree_nodes(roots: tuple[NotationTreeNode, ...]) -> tuple[NotationTreeNode, ...]:
    return tuple(item for root in roots for item in (root, *_tree_nodes(root.children)))


def run_proof(output: Path) -> dict[str, JsonValue]:
    """Create and verify a new proof folder. Never replace an existing artifact."""

    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Choose a new or empty proof output directory")
    output.mkdir(parents=True, exist_ok=True)
    blank = Project("proof:project", "Authority-authored toggle", ())
    _require(
        not blank.domain_workspace.schemas and not blank.program_model.functions,
        "The proof must start without a domain or executable program",
    )
    store = ProjectStore(output)
    store.initialize(blank)
    authority = ProjectAuthority(blank, store=store)
    client = CodeVisualizerClient(authority, actor_id="from-blank-proof")
    host = DomainExtensionRegistry((program_bundle(), intentional_bundle()))
    _require(
        all(not bundle.schemas and not bundle.transformations for bundle in host.bundles()),
        "The host must not supply a domain schema or lowering implementation",
    )
    kernel = ProjectKernel(authority, extensions=host)
    commands: list[JsonValue] = []

    def submit(command: TypedCommand) -> None:
        operation = command.to_operation()
        revision = authority.revision
        _accepted(
            client.submit(
                command, expected_revision=revision, operation_id=f"proof:command:{len(commands)}"
            )
        )
        commands.append({**operation.to_data(), "expected_revision": revision})

    def history(action: str) -> None:
        revision = authority.revision
        _accepted(client.undo() if action == "undo" else client.redo())
        commands.append({"command_type": action, "expected_revision": revision})

    try:
        submit(PutDomainSchema(DomainSchema(SCHEMA, "proof.authored.toggle", "1")))
        for identity, name in ((MACHINE, "Machine"), (STATE, "State"), (TRANSITION, "Transition")):
            submit(PutDomainConcept(SCHEMA, ConceptDefinition(identity, name)))
        for concept, definition in (
            (MACHINE, PropertyDefinition("proof:machine-name", "Name", required=True)),
            (
                MACHINE,
                PropertyDefinition(
                    "proof:step-count",
                    "Steps",
                    ValueKind.INTEGER,
                    required=True,
                    minimum=1,
                    maximum=20,
                ),
            ),
            (STATE, PropertyDefinition("proof:state-name", "Name", required=True)),
            (TRANSITION, PropertyDefinition("proof:event-name", "Event", required=True)),
        ):
            submit(PutDomainPropertyDefinition(SCHEMA, concept, definition))
        for concept_id, property_id in (
            (MACHINE, "proof:machine-name"),
            (STATE, "proof:state-name"),
            (TRANSITION, "proof:event-name"),
        ):
            schema = authority.snapshot().domain_workspace.schema(SCHEMA)
            assert schema is not None
            definition_concept = schema.concept(concept_id)
            assert definition_concept is not None
            submit(
                PutDomainConcept(
                    SCHEMA, replace(definition_concept, display_property_id=property_id)
                )
            )
        for owner, role, containment in (
            (MACHINE, RoleDefinition("proof:states", "States", (STATE,), min_count=2), True),
            (
                MACHINE,
                RoleDefinition("proof:transitions", "Transitions", (TRANSITION,), min_count=2),
                True,
            ),
            (
                MACHINE,
                RoleDefinition("proof:initial", "Initial", (STATE,), min_count=1, max_count=1),
                False,
            ),
            (
                TRANSITION,
                RoleDefinition("proof:source", "Source", (STATE,), min_count=1, max_count=1),
                False,
            ),
            (
                TRANSITION,
                RoleDefinition("proof:target", "Target", (STATE,), min_count=1, max_count=1),
                False,
            ),
        ):
            submit(PutDomainRoleDefinition(SCHEMA, owner, role, containment))
        submit(PutDomainModel(DomainModel(MODEL, SCHEMA, "1", title="Two-state toggle")))
        submit(
            CreateDomainNode(
                MODEL,
                IntentionalNode(
                    ROOT,
                    MACHINE,
                    (
                        PropertyValue("proof:machine-name", "Toggle"),
                        PropertyValue("proof:step-count", 3),
                    ),
                ),
            )
        )
        for identity, name in ((IDLE, "Idle"), (ACTIVE, "Active")):
            submit(
                CreateDomainNode(
                    MODEL,
                    IntentionalNode(identity, STATE, (PropertyValue("proof:state-name", name),)),
                    ROOT,
                    "proof:states",
                )
            )
        for identity, source_id, target_id in (
            (ACTIVATE, IDLE, ACTIVE),
            (DEACTIVATE, ACTIVE, IDLE),
        ):
            submit(
                CreateDomainNode(
                    MODEL,
                    IntentionalNode(
                        identity, TRANSITION, (PropertyValue("proof:event-name", "toggle"),)
                    ),
                    ROOT,
                    "proof:transitions",
                )
            )
            submit(SetDomainReference(MODEL, identity, "proof:source", (source_id,)))
            submit(SetDomainReference(MODEL, identity, "proof:target", (target_id,)))
        submit(SetDomainReference(MODEL, ROOT, "proof:initial", (IDLE,)))
        submit(
            PutDomainLanguage(
                l.AuthoredDomainLanguage(LANGUAGE, SCHEMA, "1", title="Authored toggle behavior")
            )
        )
        for notation in _notations():
            submit(PutDomainNotation(LANGUAGE, notation))
        validator, transformation = _language_behavior()
        submit(PutDomainValidator(LANGUAGE, validator))
        submit(PutDomainTransformation(LANGUAGE, transformation))

        # A table's target-name cell owns an explicit edit binding to the same State.
        table = kernel.notation(MODEL, NOTATIONS[1])
        cell = next(row.cells[2] for row in table.rows if row.node_id == ACTIVATE)
        assert cell.edit is not None
        _require(cell.edit.node_id == ACTIVE, "A reference path must edit its canonical target")
        submit(notation_edit_command(cell.edit, "Engaged", revision=authority.revision))
        history("undo")
        history("redo")

        # Graph selection and form property controls use these same semantic bindings.
        def edit_property(node_id: str, property_id: str, value: str | int) -> None:
            project = authority.snapshot()
            schema = project.domain_workspace.schema(SCHEMA)
            model = project.domain_workspace.model(MODEL)
            assert schema is not None and model is not None
            node = model.node(node_id)
            assert node is not None
            field = field_cell(
                schema,
                model,
                node,
                NotationField(property_id),
                cell_id="proof:property-control",
                revision=project.revision,
            )
            assert field.edit is not None
            submit(notation_edit_command(field.edit, value, revision=project.revision))

        kernel.selection.select((IDLE,), revision=authority.revision, source="proof.graph")
        edit_property(IDLE, "proof:state-name", "Rest")
        edit_property(ROOT, "proof:step-count", 4)
        history("undo")
        history("redo")
        history("undo")
        project = authority.snapshot()
        graph = kernel.notation(MODEL, NOTATIONS[0]).graph
        _require(
            {node.label for node in graph.nodes} == {"Rest", "Engaged"},
            "Graph did not see shared edits",
        )
        tree = _tree_nodes(kernel.notation(MODEL, NOTATIONS[2]).roots)
        _require(
            next(node.label for node in tree if node.node_id == ACTIVE) == "Engaged",
            "Form did not see the table edit",
        )
        _require(
            kernel.queries.semantic_object(ACTIVE) is not None,
            "Domain object is missing from semantic navigation",
        )
        model = project.domain_workspace.model(MODEL)
        assert model is not None
        _require(
            len(model.nodes) == 5 and len({node.id for node in model.nodes}) == 5,
            "An edit copied a canonical object",
        )
        assessment = assess_project(project, extensions=host)
        _require(assessment.buildable, str(assessment.blocking_diagnostics))
        serialized = normalized_project_json(project)
        _require(
            project_from_json(serialized) == project == store.recover(), "Native round trip failed"
        )
        build = prepare_build(project, host)
        _require(build == prepare_build(project, host), "Lowering is not deterministic")
        _require(
            not project.program_model.functions and bool(build.project.program_model.functions),
            "Executable output must exist only in the derived build",
        )
        generated = generate_python_project(project, extensions=host)
        _require(
            generated == generate_python_project(project, extensions=host),
            "Generation is not deterministic",
        )
        files = generate_to_disk(
            project, output, current_revision=lambda: authority.revision, extensions=host
        )
        run = run_generated(files.root / "run_project.py")
        _require(run.return_code == 0, run.stderr)
        _require(
            run.stdout == "Engaged\nRest\nEngaged\n",
            f"Unexpected state progression: {run.stdout!r}",
        )

        highlights: list[JsonValue] = []

        def observe_runtime(state: RuntimeSessionState) -> None:
            if highlights or not {ACTIVE, ACTIVATE} <= set(state.origin_ids):
                return
            graph_view = kernel.notation(MODEL, NOTATIONS[0])
            table_view = kernel.notation(MODEL, NOTATIONS[1])
            form_view = kernel.notation(MODEL, NOTATIONS[2])
            graph_node = next(node for node in graph_view.graph.nodes if node.semantic_id == ACTIVE)
            graph_edge = next(edge for edge in graph_view.graph.edges if edge.id == ACTIVATE)
            row = next(row for row in table_view.rows if row.node_id == ACTIVATE)
            form_node = next(
                node for node in _tree_nodes(form_view.roots) if node.node_id == ACTIVE
            )
            _require(
                "active" in graph_node.badges
                and graph_edge.active
                and row.active
                and form_node.active,
                "One runtime event must highlight the same source objects in every notation",
            )
            highlights.append(
                {
                    "event_sequence": state.event_sequence,
                    "project_revision": state.project_revision,
                    "generated_semantic_id": state.semantic_id,
                    "origin_ids": list(state.origin_ids),
                    "graph_state": graph_node.semantic_id,
                    "graph_transition": graph_edge.id,
                    "table_transition": row.node_id,
                    "form_state": form_node.node_id,
                }
            )

        unsubscribe = kernel.runtime.subscribe(observe_runtime)
        try:
            trace = trace_project(kernel, model_id=MODEL)
        finally:
            unsubscribe()
        _require(
            trace.run.return_code == 0 and trace.run.stdout == run.stdout,
            "Trace execution diverged",
        )
        _require(bool(highlights), "No runtime event returned to the authored State and Transition")
        _require(
            normalized_project_json(authority.snapshot()) == serialized,
            "Generation or runtime modified canonical source",
        )
        report: dict[str, JsonValue] = {
            "passed": True,
            "project_id": project.id,
            "revision": project.revision,
            "canonical_project_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            "host_bundles": [bundle.id for bundle in host.bundles()],
            "starts_blank": True,
            "canonical_nodes": [node.id for node in model.nodes],
            "command_count": len(commands),
            "transformations": list(build.transformations),
            "authored_program_functions": len(project.program_model.functions),
            "derived_program_functions": len(build.project.program_model.functions),
            "native_roundtrip": True,
            "undo_redo": True,
            "deterministic_build": True,
            "stdout": run.stdout,
            "runtime_highlights": highlights,
        }
        (output / "commands.json").write_text(
            json.dumps(commands, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (output / "proof.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return report
    finally:
        kernel.close()
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="A new or empty proof directory")
    args = parser.parse_args()
    report = run_proof(args.output)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
