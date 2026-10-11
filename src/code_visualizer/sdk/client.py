"""Typed in-process client over the same authority port used by future transports."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Protocol

from code_visualizer.application.commands import (
    AddFreeformGuide,
    AddFreeformLayer,
    AddMindMapCrossLink,
    AddMindMapTopic,
    ArrangeFreeformObjects,
    ConfigureProgram,
    ConfigureProgramEntryPoint,
    ConfigurePythonRuntime,
    CreateDiagram,
    CreateFreeformConnector,
    CreateFreeformShape,
    CreateProgramFunction,
    DeleteAuthoredSemanticRelation,
    DeleteProgramClass,
    DeleteProgramFunction,
    DeleteProgramModule,
    DeleteProgramStatements,
    DeleteProjectionDefinition,
    DeleteSemanticConcept,
    DuplicateDiagram,
    InsertDrakonAtom,
    InsertDrakonBlock,
    InsertProgramStatement,
    MaterializeProjectionView,
    MoveDiagram,
    MoveDrakonBlock,
    MoveMindMapTopic,
    MoveProgramStatements,
    PutAuthoredSemanticRelation,
    PutProgramClass,
    PutProgramModule,
    PutProjectionDefinition,
    PutSemanticConcept,
    RegisterManagedAsset,
    RegisterShapePack,
    RemoveDrakonBlock,
    RemoveFreeformGuide,
    RemoveFreeformLayer,
    RemoveFreeformObjects,
    RemoveManagedAsset,
    RemoveMindMapTopic,
    RenameDiagram,
    RenameProgramSymbol,
    RenameProject,
    ReplaceDrakonAtom,
    ReplaceFunctionSpec,
    ReplaceProgramExpression,
    ReplaceProgramFunctionSignature,
    ReplaceProgramOutput,
    SetDrakonText,
    SetFreeformCanvasOptions,
    SetFreeformObjectProperties,
    SetFunctionOwner,
    SetMindMapLayout,
    SetViewAnchor,
    TransformFreeformObject,
    TypedCommand,
    UnwrapDrakonAtom,
    UpdateFreeformLayer,
    UpdateMindMapTopic,
    WrapDrakonBlock,
    new_operation_id,
)
from code_visualizer.application.domain_commands import (
    CreateDomainNode,
    DeleteDomainNode,
    MoveDomainChild,
    PutDomainModel,
    PutDomainSchema,
    SetDomainProperty,
    SetDomainReference,
)
from code_visualizer.application.drakon_structure import (
    clone_atoms_with_fresh_ids,
    with_empty_primary,
)
from code_visualizer.application.messages import (
    CommandAccepted,
    CommandEnvelope,
    CommandResult,
    EventEnvelope,
)
from code_visualizer.application.statement_conversion import convert_simple_statement
from code_visualizer.domain.assets import ManagedAsset, ShapePackReference
from code_visualizer.domain.authoring import (
    AuthoredRelationKind,
    AuthoredSemanticRelation,
    SemanticConcept,
)
from code_visualizer.domain.common import DocumentKind, new_id
from code_visualizer.domain.drakon import (
    Action,
    Call,
    Case,
    DrakonAtom,
    DrakonDiagram,
    If,
    Parallel,
    ParallelBranch,
    Select,
    Silhouette,
    SilhouetteBranch,
    find_atom_location,
    find_sequence,
)
from code_visualizer.domain.drakon import Sequence as DrakonSequence
from code_visualizer.domain.drakon_defaults import MACROICON_INVENTORY, create_default_atom
from code_visualizer.domain.freeform import GuideOrientation, Rect, ShapeKind
from code_visualizer.domain.intentional import (
    DomainModel,
    DomainSchema,
    DomainValue,
    IntentionalNode,
)
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramEntryPoint,
    ProgramModule,
    ProgramStatement,
)
from code_visualizer.domain.program_signatures import FunctionSpec, ParameterSpec
from code_visualizer.domain.project import Project, PythonRuntimeSettings
from code_visualizer.domain.projection import ProjectionDefinition, ProjectionViewTarget


class AuthorityPort(Protocol):
    @property
    def revision(self) -> int: ...

    def snapshot(self) -> Project: ...

    def subscribe(self, subscriber: Callable[[EventEnvelope], None]) -> Callable[[], None]: ...

    def execute(self, command: CommandEnvelope) -> CommandResult: ...

    def execute_transaction(
        self,
        commands: Sequence[CommandEnvelope],
        *,
        actor_id: str,
        operation_id: str,
        expected_revision: int,
        intent: str = "",
    ) -> CommandResult: ...

    def undo(
        self,
        *,
        actor_id: str,
        operation_id: str,
        expected_revision: int,
    ) -> CommandResult: ...

    def redo(
        self,
        *,
        actor_id: str,
        operation_id: str,
        expected_revision: int,
    ) -> CommandResult: ...


class CodeVisualizerClient:
    def __init__(self, authority: AuthorityPort, *, actor_id: str) -> None:
        if not actor_id.strip():
            raise ValueError("actor_id must not be empty")
        self._authority = authority
        self.actor_id = actor_id
        self._events: list[EventEnvelope] = []
        self._observed_revision = authority.revision
        self._unsubscribe = authority.subscribe(self._receive)

    @property
    def observed_revision(self) -> int:
        return self._observed_revision

    @property
    def events(self) -> tuple[EventEnvelope, ...]:
        return tuple(self._events)

    def snapshot(self) -> Project:
        project = self._authority.snapshot()
        self._observed_revision = project.revision
        return project

    def submit(
        self,
        command: TypedCommand,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
        intent: str = "",
    ) -> CommandResult:
        operation = command.to_operation()
        result = self._authority.execute(
            CommandEnvelope(
                command_type=operation.command_type,
                actor_id=self.actor_id,
                operation_id=operation_id or new_operation_id(),
                project_id=self._authority.snapshot().id,
                expected_revision=(
                    self._observed_revision if expected_revision is None else expected_revision
                ),
                payload=operation.payload,
                intent=intent,
            )
        )
        self._observe_result(result)
        return result

    def transaction(
        self,
        commands: Sequence[TypedCommand],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
        intent: str = "",
    ) -> CommandResult:
        revision = self._observed_revision if expected_revision is None else expected_revision
        project_id = self._authority.snapshot().id
        envelopes = tuple(
            CommandEnvelope(
                command_type=operation.command_type,
                actor_id=self.actor_id,
                operation_id=new_operation_id(),
                project_id=project_id,
                expected_revision=revision,
                payload=operation.payload,
            )
            for operation in (command.to_operation() for command in commands)
        )
        result = self._authority.execute_transaction(
            envelopes,
            actor_id=self.actor_id,
            operation_id=operation_id or new_operation_id(),
            expected_revision=revision,
            intent=intent,
        )
        self._observe_result(result)
        return result

    def rename_project(
        self,
        title: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RenameProject(title),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def put_domain_schema(self, schema: DomainSchema) -> CommandResult:
        return self.submit(PutDomainSchema(schema))

    def put_domain_model(self, model: DomainModel) -> CommandResult:
        return self.submit(PutDomainModel(model))

    def create_domain_node(
        self,
        model_id: str,
        node: IntentionalNode,
        *,
        parent_id: str | None = None,
        role_id: str | None = None,
        index: int | None = None,
    ) -> CommandResult:
        return self.submit(CreateDomainNode(model_id, node, parent_id, role_id, index))

    def delete_domain_node(self, model_id: str, node_id: str) -> CommandResult:
        return self.submit(DeleteDomainNode(model_id, node_id))

    def set_domain_property(
        self, model_id: str, node_id: str, property_id: str, value: DomainValue | None
    ) -> CommandResult:
        return self.submit(SetDomainProperty(model_id, node_id, property_id, value))

    def move_domain_child(
        self,
        model_id: str,
        node_id: str,
        parent_id: str | None,
        role_id: str | None,
        index: int = 0,
    ) -> CommandResult:
        return self.submit(MoveDomainChild(model_id, node_id, parent_id, role_id, index))

    def set_domain_reference(
        self, model_id: str, node_id: str, role_id: str, target_ids: tuple[str, ...]
    ) -> CommandResult:
        return self.submit(SetDomainReference(model_id, node_id, role_id, target_ids))

    def create_diagram(
        self,
        kind: DocumentKind,
        title: str,
        *,
        identifier: str | None = None,
        module: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            CreateDiagram(kind, title, identifier, module=module),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def set_function_owner(
        self,
        function_id: str,
        owner_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            SetFunctionOwner(function_id, owner_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def configure_python_runtime(
        self,
        settings: PythonRuntimeSettings,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            ConfigurePythonRuntime(settings),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def configure_program(
        self,
        package: str,
        modules: tuple[ProgramModule, ...],
        entrypoint: ProgramEntryPoint | None,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            ConfigureProgram(package, modules, entrypoint),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def put_program_module(
        self, module: ProgramModule, *, expected_revision: int | None = None
    ) -> CommandResult:
        return self.submit(PutProgramModule(module), expected_revision=expected_revision)

    def delete_program_module(
        self, module_id: str, *, expected_revision: int | None = None
    ) -> CommandResult:
        return self.submit(DeleteProgramModule(module_id), expected_revision=expected_revision)

    def put_program_class(
        self, owner_id: str, declaration: ProgramClass, *, expected_revision: int | None = None
    ) -> CommandResult:
        return self.submit(
            PutProgramClass(owner_id, declaration), expected_revision=expected_revision
        )

    def delete_program_class(
        self, class_id: str, *, expected_revision: int | None = None
    ) -> CommandResult:
        return self.submit(DeleteProgramClass(class_id), expected_revision=expected_revision)

    def configure_entrypoint(
        self, entrypoint: ProgramEntryPoint | None, *, expected_revision: int | None = None
    ) -> CommandResult:
        return self.submit(
            ConfigureProgramEntryPoint(entrypoint), expected_revision=expected_revision
        )

    def replace_program_function_signature(
        self, function_id: str, signature: FunctionSpec, *, expected_revision: int | None = None
    ) -> CommandResult:
        return self.submit(
            ReplaceProgramFunctionSignature(function_id, signature),
            expected_revision=expected_revision,
        )

    def replace_function_spec(
        self,
        diagram_id: str,
        function: FunctionSpec,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            ReplaceFunctionSpec(diagram_id, function),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def create_program_function(
        self,
        identifier: str,
        *,
        owner_id: str | None = None,
        display_name: str | None = None,
        function_id: str | None = None,
        symbol_id: str | None = None,
        body_sequence_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            CreateProgramFunction(
                identifier,
                owner_id or self.snapshot().program_model.modules[0].id,
                display_name,
                function_id,
                symbol_id,
                body_sequence_id,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Create canonical Python function",
        )

    def delete_program_function(
        self,
        function_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            DeleteProgramFunction(function_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Delete canonical Python function",
        )

    def insert_program_statement(
        self,
        function_id: str,
        sequence_id: str,
        index: int,
        statement_kind: str = "structured",
        *,
        statement_id: str | None = None,
        statement: ProgramStatement | None = None,
        target: str | None = None,
        value: str | None = None,
        annotation: str | None = None,
        operator: str = "=",
        expression: str | None = None,
        destination: str | None = None,
        end: str | None = None,
        arguments: str = "",
        awaited: bool = False,
        result_target: str | None = None,
        target_function_id: str | None = None,
        condition: str | None = None,
        preferred_truth: bool = True,
        true_sequence_id: str | None = None,
        false_sequence_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            InsertProgramStatement(
                function_id=function_id,
                sequence_id=sequence_id,
                index=index,
                statement_kind=statement_kind,
                statement_id=statement_id,
                statement=statement,
                target=target,
                value=value,
                annotation=annotation,
                operator=operator,
                expression=expression,
                destination=destination,
                end=end,
                arguments=arguments,
                awaited=awaited,
                result_target=result_target,
                target_function_id=target_function_id,
                condition=condition,
                preferred_truth=preferred_truth,
                true_sequence_id=true_sequence_id,
                false_sequence_id=false_sequence_id,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent=f"Insert canonical {statement_kind}",
        )

    def delete_program_statements(
        self,
        function_id: str,
        sequence_id: str,
        statement_ids: tuple[str, ...],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            DeleteProgramStatements(function_id, sequence_id, statement_ids),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Delete canonical statements",
        )

    def move_program_statements(
        self,
        function_id: str,
        source_sequence_id: str,
        statement_ids: tuple[str, ...],
        destination_sequence_id: str,
        destination_index: int,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            MoveProgramStatements(
                function_id,
                source_sequence_id,
                statement_ids,
                destination_sequence_id,
                destination_index,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Move canonical statements",
        )

    def replace_program_expression(
        self,
        function_id: str,
        expression_id: str,
        source: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            ReplaceProgramExpression(function_id, expression_id, source),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Replace canonical Python expression",
        )

    def replace_program_output(
        self,
        function_id: str,
        statement_id: str,
        expression: str,
        *,
        destination: str | None = None,
        end: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            ReplaceProgramOutput(
                function_id,
                statement_id,
                expression,
                destination,
                end,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Replace canonical Python output",
        )

    def rename_program_symbol(
        self,
        symbol_id: str,
        name: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RenameProgramSymbol(symbol_id, name),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Rename canonical Python symbol",
        )

    def rename_diagram(
        self,
        diagram_id: str,
        title: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RenameDiagram(diagram_id, title),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def move_diagram(
        self,
        diagram_id: str,
        index: int,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            MoveDiagram(diagram_id, index),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def duplicate_diagram(
        self,
        diagram_id: str,
        *,
        title: str | None = None,
        document_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            DuplicateDiagram(diagram_id, title, document_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def insert_drakon_atom(
        self,
        diagram_id: str,
        atom_kind: str,
        index: int,
        *,
        source: str | None = None,
        target: str | None = None,
        value: str | None = None,
        sequence_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            InsertDrakonAtom(
                diagram_id=diagram_id,
                atom_kind=atom_kind,
                index=index,
                source=source,
                target=target,
                value=value,
                sequence_id=sequence_id,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def insert_drakon_macro(
        self,
        diagram_id: str,
        macro_id: str,
        index: int,
        *,
        sequence_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        known = {item.id for item in MACROICON_INVENTORY}
        if macro_id not in known:
            raise ValueError(f"Unknown DRAKON macroicon {macro_id!r}")
        project = self.snapshot()
        diagram = next(
            (
                item
                for item in project.documents
                if isinstance(item, DrakonDiagram) and item.id == diagram_id
            ),
            None,
        )
        if diagram is None:
            raise ValueError(f"DRAKON diagram {diagram_id!r} does not exist")
        if macro_id == "header_parameters":
            existing = {item.name for item in diagram.header.function.parameters}
            ordinal = 1
            parameter_name = "value"
            while parameter_name in existing:
                ordinal += 1
                parameter_name = f"value_{ordinal}"
            function = replace(
                diagram.header.function,
                parameters=(
                    *diagram.header.function.parameters,
                    ParameterSpec(parameter_name),
                ),
            )
            return self.submit(
                ReplaceFunctionSpec(diagram_id, function),
                expected_revision=expected_revision,
                operation_id=operation_id,
                intent="Insert Header with Parameters macroicon",
            )

        target_sequence = sequence_id or diagram.body.id
        simple = {
            "binary_if": "if",
            "select": "select",
            "conditional_loop": "while_loop",
            "for_loop": "for_loop",
            "wait_loop": "wait_loop",
            "tree_loop": "tree_dfs_loop",
        }
        if macro_id in simple:
            return self.submit(
                InsertDrakonAtom(
                    diagram_id,
                    simple[macro_id],
                    index,
                    sequence_id=target_sequence,
                ),
                expected_revision=expected_revision,
                operation_id=operation_id,
                intent=f"Insert {macro_id} macroicon",
            )

        commands: list[TypedCommand] = []
        if macro_id in {"select_loop", "timed_select_loop"}:
            root_index = index
            if macro_id == "timed_select_loop":
                commands.append(
                    InsertDrakonAtom(
                        diagram_id,
                        "start_timer",
                        root_index,
                        sequence_id=target_sequence,
                    )
                )
                root_index += 1
            loop_id = new_id("atom")
            commands.append(
                InsertDrakonAtom(
                    diagram_id,
                    "while_loop",
                    root_index,
                    atom_id=loop_id,
                    sequence_id=target_sequence,
                )
            )
            commands.append(
                InsertDrakonAtom(
                    diagram_id,
                    "select",
                    0,
                    sequence_id=f"sequence_{loop_id}_body",
                )
            )
            if macro_id == "timed_select_loop":
                commands.append(
                    InsertDrakonAtom(
                        diagram_id,
                        "synchronizer",
                        root_index + 1,
                        sequence_id=target_sequence,
                    )
                )
        else:
            timed_middle = {
                "timed_action": "action",
                "timed_shelf": "assignment",
                "timed_fork": "if",
                "timed_select": "select",
                "timed_conditional_loop": "while_loop",
                "timed_for_loop": "for_loop",
                "timed_wait_loop": "wait_loop",
                "timed_call": "call",
                "timed_output": "output",
                "timed_input": "input",
                "timed_parallel": "parallel",
            }
            commands.append(
                InsertDrakonAtom(
                    diagram_id,
                    "start_timer",
                    index,
                    sequence_id=target_sequence,
                )
            )
            if macro_id != "timed_start_timer":
                commands.append(
                    InsertDrakonAtom(
                        diagram_id,
                        timed_middle[macro_id],
                        index + 1,
                        sequence_id=target_sequence,
                    )
                )
            commands.append(
                InsertDrakonAtom(
                    diagram_id,
                    "synchronizer",
                    index + (1 if macro_id == "timed_start_timer" else 2),
                    sequence_id=target_sequence,
                )
            )
        return self.transaction(
            commands,
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent=f"Insert {macro_id} macroicon",
        )

    def move_drakon_block(
        self,
        diagram_id: str,
        source_sequence_id: str,
        atom_ids: tuple[str, ...],
        destination_sequence_id: str,
        destination_index: int,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            MoveDrakonBlock(
                diagram_id,
                source_sequence_id,
                atom_ids,
                destination_sequence_id,
                destination_index,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def insert_drakon_block(
        self,
        diagram_id: str,
        sequence_id: str,
        index: int,
        atoms: tuple[DrakonAtom, ...],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            InsertDrakonBlock(diagram_id, sequence_id, index, atoms),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Insert a complete DRAKON block",
        )

    def remove_drakon_block(
        self,
        diagram_id: str,
        sequence_id: str,
        atom_ids: tuple[str, ...],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RemoveDrakonBlock(diagram_id, sequence_id, atom_ids),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Remove a complete DRAKON block",
        )

    def duplicate_drakon_block(
        self,
        diagram_id: str,
        sequence_id: str,
        atom_ids: tuple[str, ...],
        destination_index: int,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        diagram = self._drakon_diagram(diagram_id)
        sequence = find_sequence(diagram.body, sequence_id)
        if sequence is None:
            raise ValueError(f"DRAKON Sequence {sequence_id!r} does not exist")
        first_index = next(
            (index for index, atom in enumerate(sequence.atoms) if atom.id == atom_ids[0]),
            -1,
        )
        originals = sequence.atoms[first_index : first_index + len(atom_ids)]
        if first_index < 0 or tuple(atom.id for atom in originals) != atom_ids:
            raise ValueError("A duplicated block must be contiguous and in Sequence order")
        clones = clone_atoms_with_fresh_ids(originals)
        return self.insert_drakon_block(
            diagram_id,
            sequence_id,
            destination_index,
            clones,
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def replace_drakon_atom(
        self,
        diagram_id: str,
        atom: DrakonAtom,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
        intent: str = "Replace a typed DRAKON construct",
    ) -> CommandResult:
        return self.submit(
            ReplaceDrakonAtom(diagram_id, atom.id, atom),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent=intent,
        )

    def convert_drakon_statement(
        self,
        diagram_id: str,
        atom_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        replacement = convert_simple_statement(self._drakon_atom(diagram_id, atom_id))
        return self.replace_drakon_atom(
            diagram_id,
            replacement,
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Convert one Python statement into a typed DRAKON icon",
        )

    def wrap_drakon_block(
        self,
        diagram_id: str,
        sequence_id: str,
        atom_ids: tuple[str, ...],
        wrapper_kind: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        wrapper, _primary = with_empty_primary(create_default_atom(wrapper_kind, new_id("atom")))
        return self.submit(
            WrapDrakonBlock(diagram_id, sequence_id, atom_ids, wrapper),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent=f"Wrap block in {wrapper_kind}",
        )

    def unwrap_drakon_atom(
        self,
        diagram_id: str,
        atom_id: str,
        *,
        body_sequence_id: str | None = None,
        discard_other_bodies: bool = False,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            UnwrapDrakonAtom(
                diagram_id,
                atom_id,
                body_sequence_id,
                discard_other_bodies,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Unwrap a DRAKON construct",
        )

    def set_if_preferred_truth(
        self,
        diagram_id: str,
        atom_id: str,
        preferred_truth: bool,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, If):
            raise ValueError("Preferred truth applies only to an If construct")
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, preferred_truth=preferred_truth),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Set the If preferred route independently from truth",
        )

    def link_call(
        self,
        diagram_id: str,
        atom_id: str,
        target_diagram_id: str | None,
        *,
        arguments: str = "",
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Call):
            raise ValueError("Only a Call construct can link to a callable diagram")
        expression = atom.expression
        if target_diagram_id is not None:
            target = self._drakon_diagram(target_diagram_id)
            owner = (
                f"{target.header.function.owning_class}."
                if target.header.function.owning_class
                else ""
            )
            expression = f"{owner}{target.header.function.identifier}({arguments})"
        return self.replace_drakon_atom(
            diagram_id,
            replace(
                atom,
                expression=expression,
                target_diagram_id=target_diagram_id,
                arguments=arguments,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Link a Call to a stable callable diagram",
        )

    def swap_if_outcomes(
        self,
        diagram_id: str,
        atom_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, If):
            raise ValueError("Outcome swapping applies only to an If construct")
        swapped = replace(
            atom,
            true_branch=atom.false_branch,
            false_branch=atom.true_branch,
            preferred_truth=not atom.preferred_truth,
        )
        return self.replace_drakon_atom(
            diagram_id,
            swapped,
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Swap If truth bindings while preserving the visual preferred route",
        )

    def add_select_case(
        self,
        diagram_id: str,
        atom_id: str,
        *,
        label: str = "Case",
        condition: str = "False",
        pattern: str = "_",
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Select):
            raise ValueError("Cases can be added only to a Select construct")
        case_id = new_id("case")
        new_case = Case(
            case_id,
            label,
            DrakonSequence(
                new_id("sequence"),
                (Action(new_id("atom"), 'print("case action")'),),
            ),
            condition=condition,
            pattern=pattern,
        )
        default_index = next(
            (index for index, case in enumerate(atom.cases) if case.is_default),
            len(atom.cases),
        )
        cases = list(atom.cases)
        cases.insert(default_index, new_case)
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, cases=tuple(cases)),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Add an ordered Select Case",
        )

    def remove_select_case(
        self,
        diagram_id: str,
        atom_id: str,
        case_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Select):
            raise ValueError("Cases can be removed only from a Select construct")
        if len(atom.cases) <= 2:
            raise ValueError("Select must retain at least two Cases")
        removed = next((case for case in atom.cases if case.id == case_id), None)
        if removed is None:
            raise ValueError(f"Case {case_id!r} does not exist")
        cases = tuple(case for case in atom.cases if case.id != case_id)
        if removed.is_default:
            cases = (*cases[:-1], replace(cases[-1], is_default=True))
        preferred = atom.preferred_case_id
        if preferred == case_id:
            preferred = cases[0].id
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, cases=cases, preferred_case_id=preferred),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Remove an ordered Select Case",
        )

    def reorder_select_cases(
        self,
        diagram_id: str,
        atom_id: str,
        ordered_case_ids: tuple[str, ...],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Select):
            raise ValueError("Cases can be reordered only on a Select construct")
        by_id = {case.id: case for case in atom.cases}
        if set(ordered_case_ids) != set(by_id) or len(ordered_case_ids) != len(by_id):
            raise ValueError("Case order must contain every existing Case exactly once")
        cases = tuple(by_id[case_id] for case_id in ordered_case_ids)
        if not cases[-1].is_default:
            raise ValueError("The default Case must remain rightmost/final")
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, cases=cases),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Reorder Select Cases",
        )

    def add_silhouette_branch(
        self,
        diagram_id: str,
        atom_id: str,
        *,
        name: str = "Next State",
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Silhouette):
            raise ValueError("States can be added only to a Silhouette")
        exits = [branch for branch in atom.branches if branch.target_branch_id is None]
        if len(exits) != 1:
            raise ValueError("Repair the silhouette finite exit before adding a state")
        branch_id = new_id("branch")
        branch = SilhouetteBranch(
            branch_id,
            name,
            DrakonSequence(
                new_id("sequence"),
                (Action(new_id("atom"), 'print("state action")'),),
            ),
            None,
        )
        branches = tuple(
            replace(existing, target_branch_id=branch_id)
            if existing.id == exits[0].id
            else existing
            for existing in atom.branches
        )
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, branches=(*branches, branch)),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Add a named Silhouette state",
        )

    def retarget_silhouette_branch(
        self,
        diagram_id: str,
        atom_id: str,
        branch_id: str,
        target_branch_id: str | None,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Silhouette):
            raise ValueError("Address targets belong only to a Silhouette")
        branch_ids = {branch.id for branch in atom.branches}
        if branch_id not in branch_ids:
            raise ValueError(f"State {branch_id!r} does not exist")
        if target_branch_id is not None and target_branch_id not in branch_ids:
            raise ValueError(f"Address target {target_branch_id!r} does not exist")
        branches = tuple(
            replace(branch, target_branch_id=target_branch_id) if branch.id == branch_id else branch
            for branch in atom.branches
        )
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, branches=branches),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Retarget a Silhouette Address",
        )

    def remove_silhouette_branch(
        self,
        diagram_id: str,
        atom_id: str,
        branch_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Silhouette):
            raise ValueError("States can be removed only from a Silhouette")
        if len(atom.branches) <= 1:
            raise ValueError("A Silhouette must retain at least one state")
        removed = next((branch for branch in atom.branches if branch.id == branch_id), None)
        if removed is None:
            raise ValueError(f"State {branch_id!r} does not exist")
        branches = tuple(
            replace(branch, target_branch_id=removed.target_branch_id)
            if branch.target_branch_id == branch_id
            else branch
            for branch in atom.branches
            if branch.id != branch_id
        )
        initial = atom.initial_branch_id
        if initial == branch_id:
            initial = removed.target_branch_id or branches[0].id
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, branches=branches, initial_branch_id=initial),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Remove a Silhouette state and splice its Address route",
        )

    def set_silhouette_initial_branch(
        self,
        diagram_id: str,
        atom_id: str,
        branch_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Silhouette):
            raise ValueError("Initial states belong only to a Silhouette")
        if branch_id not in {branch.id for branch in atom.branches}:
            raise ValueError(f"State {branch_id!r} does not exist")
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, initial_branch_id=branch_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Choose the Silhouette initial state",
        )

    def reorder_silhouette_branches(
        self,
        diagram_id: str,
        atom_id: str,
        ordered_branch_ids: tuple[str, ...],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Silhouette):
            raise ValueError("States can be reordered only on a Silhouette")
        by_id = {branch.id: branch for branch in atom.branches}
        if set(ordered_branch_ids) != set(by_id) or len(ordered_branch_ids) != len(by_id):
            raise ValueError("State order must contain every branch exactly once")
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, branches=tuple(by_id[item] for item in ordered_branch_ids)),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Reorder Silhouette states",
        )

    def add_parallel_branch(
        self,
        diagram_id: str,
        atom_id: str,
        *,
        name: str = "Process",
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Parallel):
            raise ValueError("Processes can be added only to a Parallel construct")
        branch = ParallelBranch(
            new_id("branch"),
            name,
            DrakonSequence(
                new_id("sequence"),
                (Action(new_id("atom"), 'print("parallel process action")'),),
            ),
        )
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, branches=(*atom.branches, branch)),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Add a Parallel process",
        )

    def remove_parallel_branch(
        self,
        diagram_id: str,
        atom_id: str,
        branch_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Parallel):
            raise ValueError("Processes can be removed only from a Parallel construct")
        if len(atom.branches) <= 2:
            raise ValueError("Parallel must retain at least two processes")
        if branch_id not in {branch.id for branch in atom.branches}:
            raise ValueError(f"Process {branch_id!r} does not exist")
        return self.replace_drakon_atom(
            diagram_id,
            replace(
                atom,
                branches=tuple(branch for branch in atom.branches if branch.id != branch_id),
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Remove a Parallel process",
        )

    def reorder_parallel_branches(
        self,
        diagram_id: str,
        atom_id: str,
        ordered_branch_ids: tuple[str, ...],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        atom = self._drakon_atom(diagram_id, atom_id)
        if not isinstance(atom, Parallel):
            raise ValueError("Processes can be reordered only on a Parallel construct")
        by_id = {branch.id: branch for branch in atom.branches}
        if set(ordered_branch_ids) != set(by_id) or len(ordered_branch_ids) != len(by_id):
            raise ValueError("Process order must contain every branch exactly once")
        return self.replace_drakon_atom(
            diagram_id,
            replace(atom, branches=tuple(by_id[item] for item in ordered_branch_ids)),
            expected_revision=expected_revision,
            operation_id=operation_id,
            intent="Reorder Parallel processes",
        )

    def _drakon_diagram(self, diagram_id: str) -> DrakonDiagram:
        project = self.snapshot()
        diagram = next(
            (
                item
                for item in project.documents
                if isinstance(item, DrakonDiagram) and item.id == diagram_id
            ),
            None,
        )
        if diagram is None:
            raise ValueError(f"DRAKON diagram {diagram_id!r} does not exist")
        return diagram

    def _drakon_atom(self, diagram_id: str, atom_id: str) -> DrakonAtom:
        diagram = self._drakon_diagram(diagram_id)
        location = find_atom_location(diagram.body, atom_id)
        if location is None:
            raise ValueError(f"DRAKON atom {atom_id!r} does not exist")
        return location[0].atoms[location[1]]

    def set_drakon_text(
        self,
        diagram_id: str,
        atom_id: str,
        field: str,
        value: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            SetDrakonText(diagram_id, atom_id, field, value),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def add_mindmap_topic(
        self,
        diagram_id: str,
        parent_id: str,
        text: str,
        index: int,
        *,
        topic_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            AddMindMapTopic(diagram_id, parent_id, text, index, topic_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def update_mindmap_topic(
        self,
        diagram_id: str,
        topic_id: str,
        text: str,
        *,
        notes: str = "",
        collapsed: bool = False,
        links: tuple[str, ...] = (),
        attachments: tuple[str, ...] = (),
        derive_label: bool = False,
        update_label: bool = True,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            UpdateMindMapTopic(
                diagram_id,
                topic_id,
                text,
                notes,
                collapsed,
                links,
                attachments,
                derive_label,
                update_label,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def move_mindmap_topic(
        self,
        diagram_id: str,
        topic_id: str,
        parent_id: str,
        index: int,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            MoveMindMapTopic(diagram_id, topic_id, parent_id, index),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def remove_mindmap_topic(
        self,
        diagram_id: str,
        topic_id: str,
        *,
        promote_children: bool = False,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RemoveMindMapTopic(diagram_id, topic_id, promote_children),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def add_mindmap_cross_link(
        self,
        diagram_id: str,
        source_topic_id: str,
        target_topic_id: str,
        *,
        label: str = "",
        link_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            AddMindMapCrossLink(
                diagram_id,
                source_topic_id,
                target_topic_id,
                label,
                link_id,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def set_mindmap_layout(
        self,
        diagram_id: str,
        layout: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            SetMindMapLayout(diagram_id, layout),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def set_view_anchor(
        self,
        diagram_id: str,
        object_id: str,
        *,
        semantic_id: str | None = None,
        semantic_relation_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            SetViewAnchor(diagram_id, object_id, semantic_id, semantic_relation_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def put_semantic_concept(
        self,
        concept: SemanticConcept,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            PutSemanticConcept(concept),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def create_semantic_concept(
        self,
        title: str,
        member_ids: tuple[str, ...] = (),
        *,
        description: str = "",
        tags: tuple[str, ...] = (),
        concept_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.put_semantic_concept(
            SemanticConcept(
                concept_id or new_id("concept"),
                title,
                description,
                member_ids,
                tags,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def delete_semantic_concept(
        self,
        concept_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            DeleteSemanticConcept(concept_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def put_authored_semantic_relation(
        self,
        relation: AuthoredSemanticRelation,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            PutAuthoredSemanticRelation(relation),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def create_authored_semantic_relation(
        self,
        source_id: str,
        target_id: str,
        *,
        kind: AuthoredRelationKind = AuthoredRelationKind.ASSOCIATES,
        label: str = "",
        description: str = "",
        relation_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.put_authored_semantic_relation(
            AuthoredSemanticRelation(
                relation_id or new_id("semantic-relation"),
                source_id,
                target_id,
                kind,
                label,
                description,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def delete_authored_semantic_relation(
        self,
        relation_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            DeleteAuthoredSemanticRelation(relation_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def put_projection_definition(
        self,
        definition: ProjectionDefinition,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            PutProjectionDefinition(definition),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def delete_projection_definition(
        self,
        definition_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            DeleteProjectionDefinition(definition_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def materialize_projection(
        self,
        definition: ProjectionDefinition,
        target: ProjectionViewTarget,
        title: str,
        *,
        document_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            MaterializeProjectionView(definition, target, title, document_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def create_freeform_shape(
        self,
        diagram_id: str,
        shape: ShapeKind,
        bounds: Rect,
        *,
        text: str = "",
        object_id: str | None = None,
        layer_id: str = "layer_default",
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            CreateFreeformShape(
                diagram_id,
                shape,
                bounds,
                text,
                object_id,
                layer_id,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def transform_freeform_object(
        self,
        diagram_id: str,
        object_id: str,
        bounds: Rect,
        *,
        rotation: float = 0.0,
        text: str | None = None,
        fill: str | None = None,
        stroke: str | None = None,
        asset_id: str | None = None,
        derive_label: bool = False,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            TransformFreeformObject(
                diagram_id,
                object_id,
                bounds,
                rotation,
                text,
                fill,
                stroke,
                asset_id,
                derive_label,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def remove_freeform_objects(
        self,
        diagram_id: str,
        object_ids: tuple[str, ...],
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RemoveFreeformObjects(diagram_id, object_ids),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def connect_freeform_objects(
        self,
        diagram_id: str,
        source_id: str,
        target_id: str,
        *,
        label: str = "",
        orthogonal: bool = True,
        connector_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            CreateFreeformConnector(
                diagram_id,
                source_id,
                target_id,
                label,
                orthogonal,
                connector_id,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def set_freeform_properties(
        self,
        diagram_id: str,
        object_ids: tuple[str, ...],
        *,
        locked: bool | None = None,
        hidden: bool | None = None,
        layer_id: str | None = None,
        group_id: str | None = None,
        z_index: int | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            SetFreeformObjectProperties(
                diagram_id,
                object_ids,
                locked,
                hidden,
                layer_id,
                group_id,
                z_index,
            ),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def arrange_freeform_objects(
        self,
        diagram_id: str,
        object_ids: tuple[str, ...],
        arrangement: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            ArrangeFreeformObjects(diagram_id, object_ids, arrangement),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def add_freeform_layer(
        self,
        diagram_id: str,
        name: str,
        *,
        layer_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            AddFreeformLayer(diagram_id, name, layer_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def update_freeform_layer(
        self,
        diagram_id: str,
        layer_id: str,
        name: str,
        *,
        hidden: bool = False,
        locked: bool = False,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            UpdateFreeformLayer(diagram_id, layer_id, name, hidden, locked),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def remove_freeform_layer(
        self,
        diagram_id: str,
        layer_id: str,
        *,
        fallback_layer_id: str = "layer_default",
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RemoveFreeformLayer(diagram_id, layer_id, fallback_layer_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def add_freeform_guide(
        self,
        diagram_id: str,
        orientation: GuideOrientation,
        position: float,
        *,
        guide_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            AddFreeformGuide(diagram_id, orientation, position, guide_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def remove_freeform_guide(
        self,
        diagram_id: str,
        guide_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RemoveFreeformGuide(diagram_id, guide_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def configure_freeform_canvas(
        self,
        diagram_id: str,
        grid_size: float,
        snap_to_grid: bool,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            SetFreeformCanvasOptions(diagram_id, grid_size, snap_to_grid),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def register_managed_asset(
        self,
        asset: ManagedAsset,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RegisterManagedAsset(asset),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def remove_managed_asset(
        self,
        asset_id: str,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RemoveManagedAsset(asset_id),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def register_shape_pack(
        self,
        shape_pack: ShapePackReference,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        return self.submit(
            RegisterShapePack(shape_pack),
            expected_revision=expected_revision,
            operation_id=operation_id,
        )

    def undo(
        self,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        result = self._authority.undo(
            actor_id=self.actor_id,
            operation_id=operation_id or new_operation_id(),
            expected_revision=(
                self._observed_revision if expected_revision is None else expected_revision
            ),
        )
        self._observe_result(result)
        return result

    def redo(
        self,
        *,
        expected_revision: int | None = None,
        operation_id: str | None = None,
    ) -> CommandResult:
        result = self._authority.redo(
            actor_id=self.actor_id,
            operation_id=operation_id or new_operation_id(),
            expected_revision=(
                self._observed_revision if expected_revision is None else expected_revision
            ),
        )
        self._observe_result(result)
        return result

    def close(self) -> None:
        self._unsubscribe()

    def _receive(self, event: EventEnvelope) -> None:
        self._events.append(event)
        self._observed_revision = max(self._observed_revision, event.revision)

    def _observe_result(self, result: CommandResult) -> None:
        if isinstance(result, CommandAccepted):
            self._observed_revision = max(self._observed_revision, result.revision)
        else:
            self._observed_revision = max(self._observed_revision, result.current_revision)
