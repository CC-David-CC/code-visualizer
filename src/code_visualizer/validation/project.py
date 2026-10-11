"""Pure integrity and Python generation-gate diagnostics.

Integrity diagnostics protect model construction and authority commits. Python
diagnostics intentionally remain editable: an incomplete expression is useful
project state, but it blocks generation until repaired.
"""

from __future__ import annotations

import ast
import keyword
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from code_visualizer.domain.invocation import InvocationBindingError, bind_invocation
from code_visualizer.domain.invocation_arguments import (
    InvocationArguments,
    UnresolvedInvocationArguments,
    parse_invocation_arguments,
)
from code_visualizer.domain.program_bindings import ProgramScope, resolve_linked_callable
from code_visualizer.domain.program_index import ProgramFunctionLocation, program_function_locations

if TYPE_CHECKING:
    from code_visualizer.extensions.registry import DomainExtensionRegistry

from code_visualizer.application.drakon_program_adapter import drakon_from_program
from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Delay,
    DrakonAtom,
    DrakonDiagram,
    If,
    Input,
    Loop,
    Note,
    Output,
    Parallel,
    Period,
    RealtimeProcess,
    Select,
    Sequence,
    Silhouette,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    Try,
    With,
    drakon_atom_ids,
    nested_sequences,
)
from code_visualizer.domain.expression import (
    ExpressionNode,
    SymbolReferenceExpression,
    UnparsedPythonExpression,
    expression_children,
    expression_identity_ids,
)
from code_visualizer.domain.freeform import ConnectorObject, FreeformDiagram, ShapeObject
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.mindmap import MindMapDiagram, Topic, walk_topics
from code_visualizer.domain.program import (
    ProgramAssignment,
    ProgramCall,
    ProgramClass,
    ProgramDeclaration,
    ProgramEntryPoint,
    ProgramExpression,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramIf,
    ProgramImport,
    ProgramModel,
    ProgramModule,
    ProgramOutput,
    ProgramSequence,
    ProgramStatement,
    ProgramSymbolKind,
    ProgramTypeAlias,
    expression_parse_mode,
    iter_program_nodes,
    program_expressions,
    program_node_id,
    program_statements,
)
from code_visualizer.domain.program_kinds import (
    CallableKind,
    LoopKind,
    MethodKind,
    ParallelMode,
    ParameterKind,
    ProgramModuleKind,
    SelectMode,
    SimpleKind,
    TransferKind,
)
from code_visualizer.domain.project import Project, ProjectDocument
from code_visualizer.domain.projection import DrakonViewDefinition


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DiagnosticCategory(StrEnum):
    PROJECT = "project"
    PYTHON = "python"
    TOPOLOGY = "topology"
    LAYOUT = "layout"
    GENERATION = "generation"
    RUNTIME = "runtime"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    object_id: str | None = None
    field: str | None = None
    diagram_id: str | None = None
    category: DiagnosticCategory = DiagnosticCategory.PROJECT
    suggested_repair: str = ""


class BuildabilityStatus(StrEnum):
    BUILDABLE = "buildable"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ProjectAssessment:
    """Validation findings plus the explicit build gate they imply."""

    status: BuildabilityStatus
    diagnostics: tuple[Diagnostic, ...]
    blocking_diagnostics: tuple[Diagnostic, ...]

    @property
    def buildable(self) -> bool:
        return self.status is BuildabilityStatus.BUILDABLE


def _duplicate_ids(values: list[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _topic_ids(topic: Topic) -> list[str]:
    result = [topic.id]
    for child in topic.children:
        result.extend(_topic_ids(child))
    return result


def _sequence_ids(sequence: Sequence) -> list[str]:
    result = [sequence.id]
    for atom in sequence.atoms:
        result.extend(drakon_atom_ids(atom))
    return result


def _integrity_drakon(document: DrakonDiagram) -> list[Diagnostic]:
    local_ids = [document.id, document.header.id, document.end.id]
    local_ids.extend(_sequence_ids(document.body))
    return [
        Diagnostic(
            "DOC_DUPLICATE_ID",
            Severity.ERROR,
            f"Identifier {duplicate!r} is used more than once",
            duplicate,
            diagram_id=document.id,
            category=DiagnosticCategory.TOPOLOGY,
        )
        for duplicate in sorted(_duplicate_ids(local_ids))
    ]


def _integrity_mind_map(document: MindMapDiagram) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    topic_ids = _topic_ids(document.root)
    topic_set = set(topic_ids)
    for duplicate in sorted(_duplicate_ids(topic_ids)):
        diagnostics.append(
            Diagnostic(
                "MIND_DUPLICATE_TOPIC",
                Severity.ERROR,
                f"Topic identifier {duplicate!r} is used more than once",
                duplicate,
                diagram_id=document.id,
                category=DiagnosticCategory.TOPOLOGY,
            )
        )
    for link in document.cross_links:
        if link.source_topic_id not in topic_set or link.target_topic_id not in topic_set:
            diagnostics.append(
                Diagnostic(
                    "MIND_UNRESOLVED_LINK",
                    Severity.ERROR,
                    "Cross-link endpoint does not exist in this mind map",
                    link.id,
                    diagram_id=document.id,
                    category=DiagnosticCategory.TOPOLOGY,
                )
            )
    return diagnostics


def _integrity_freeform(document: FreeformDiagram) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    object_ids = [item.id for item in document.objects]
    object_set = set(object_ids)
    layer_ids = [layer.id for layer in document.layers]
    layer_set = set(layer_ids)
    if "layer_default" not in layer_set:
        diagnostics.append(
            Diagnostic(
                "FREEFORM_DEFAULT_LAYER_REQUIRED",
                Severity.ERROR,
                "A free-form scene must retain its default layer",
                document.id,
                "layers",
                document.id,
                DiagnosticCategory.TOPOLOGY,
            )
        )
    for duplicate in sorted(_duplicate_ids(layer_ids)):
        diagnostics.append(
            Diagnostic(
                "FREEFORM_DUPLICATE_LAYER",
                Severity.ERROR,
                f"Layer identifier {duplicate!r} is used more than once",
                duplicate,
                "layers",
                document.id,
                DiagnosticCategory.TOPOLOGY,
            )
        )
    guide_ids = [guide.id for guide in document.guides]
    for duplicate in sorted(_duplicate_ids(guide_ids)):
        diagnostics.append(
            Diagnostic(
                "FREEFORM_DUPLICATE_GUIDE",
                Severity.ERROR,
                f"Guide identifier {duplicate!r} is used more than once",
                duplicate,
                "guides",
                document.id,
                DiagnosticCategory.LAYOUT,
            )
        )
    if not math.isfinite(document.grid_size) or document.grid_size < 1.0:
        diagnostics.append(
            Diagnostic(
                "FREEFORM_INVALID_GRID",
                Severity.ERROR,
                "Grid size must be finite and at least 1",
                document.id,
                "grid_size",
                document.id,
                DiagnosticCategory.LAYOUT,
            )
        )
    for guide in document.guides:
        if not math.isfinite(guide.position):
            diagnostics.append(
                Diagnostic(
                    "FREEFORM_NONFINITE_GUIDE",
                    Severity.ERROR,
                    "Guide positions must be finite",
                    guide.id,
                    "position",
                    document.id,
                    DiagnosticCategory.LAYOUT,
                )
            )
    for duplicate in sorted(_duplicate_ids(object_ids)):
        diagnostics.append(
            Diagnostic(
                "FREEFORM_DUPLICATE_OBJECT",
                Severity.ERROR,
                f"Object identifier {duplicate!r} is used more than once",
                duplicate,
                diagram_id=document.id,
                category=DiagnosticCategory.TOPOLOGY,
            )
        )
    for item in document.objects:
        if item.layer_id not in layer_set:
            diagnostics.append(
                Diagnostic(
                    "FREEFORM_LAYER_NOT_FOUND",
                    Severity.ERROR,
                    "Object layer does not exist in this scene",
                    item.id,
                    "layer_id",
                    document.id,
                    DiagnosticCategory.TOPOLOGY,
                )
            )
        if isinstance(item, ShapeObject):
            values = (
                item.bounds.x,
                item.bounds.y,
                item.bounds.width,
                item.bounds.height,
            )
            if not all(math.isfinite(value) for value in values):
                diagnostics.append(
                    Diagnostic(
                        "FREEFORM_NONFINITE_BOUNDS",
                        Severity.ERROR,
                        "Shape bounds must be finite",
                        item.id,
                        "bounds",
                        document.id,
                        DiagnosticCategory.LAYOUT,
                    )
                )
            if item.bounds.width < 0 or item.bounds.height < 0:
                diagnostics.append(
                    Diagnostic(
                        "FREEFORM_NEGATIVE_SIZE",
                        Severity.ERROR,
                        "Shape width and height must not be negative",
                        item.id,
                        "bounds",
                        document.id,
                        DiagnosticCategory.LAYOUT,
                    )
                )
        elif isinstance(item, ConnectorObject):
            if item.source_id not in object_set or item.target_id not in object_set:
                diagnostics.append(
                    Diagnostic(
                        "FREEFORM_UNRESOLVED_CONNECTOR",
                        Severity.ERROR,
                        "Connector endpoint does not exist in this scene",
                        item.id,
                        diagram_id=document.id,
                        category=DiagnosticCategory.TOPOLOGY,
                    )
                )
    return diagnostics


def _integrity_document(document: ProjectDocument) -> list[Diagnostic]:
    if isinstance(document, DrakonDiagram):
        return _integrity_drakon(document)
    if isinstance(document, MindMapDiagram):
        return _integrity_mind_map(document)
    if isinstance(document, FreeformDiagram):
        return _integrity_freeform(document)
    raise TypeError(f"Unsupported project document: {type(document).__name__}")


def _program_statement_ids(sequence: ProgramSequence) -> list[str]:
    return [
        program_node_id(node)
        for node in iter_program_nodes(sequence)
        if not isinstance(node, ProgramExpression)
    ]


def _program_statements(sequence: ProgramSequence) -> tuple[ProgramStatement, ...]:
    return tuple(program_statements(sequence))


def _program_expressions(function: ProgramFunction) -> tuple[ProgramExpression, ...]:
    return tuple(program_expressions(function))


def _program_expression_nodes(expression: ProgramExpression) -> tuple[ExpressionNode, ...]:
    result: list[ExpressionNode] = []

    def visit(node: ExpressionNode) -> None:
        result.append(node)
        for _field, child in expression_children(node):
            visit(child)

    visit(expression.tree)
    return tuple(result)


def _integrity_program_ownership(
    model: ProgramModel,
    nodes: tuple[object, ...],
    expressions: tuple[ProgramExpression, ...],
) -> list[Diagnostic]:
    """Every stored declaration has one owner; function references are ownership."""
    diagnostics: list[Diagnostic] = []
    references: dict[str, list[str]] = {}
    identities: dict[str, list[str]] = {}
    # Existing function/symbol/expression checks retain their precise diagnostics.
    # This additional check covers the new scopes and their complete subtrees.
    for node in nodes:
        identity = getattr(node, "id", None)
        if isinstance(identity, str):
            identities.setdefault(identity, []).append(type(node).__name__)
    new_ownership_ids = {
        identity
        for node in iter_program_nodes((model.modules, model.entrypoint))
        if isinstance(identity := getattr(node, "id", None), str)
    }
    for expression in expressions:
        for identity in expression_identity_ids(expression.tree):
            identities.setdefault(identity, []).append("expression-node")
            if expression.id in new_ownership_ids:
                new_ownership_ids.add(identity)
    for module in model.modules:

        def visit(owner: ProgramModule | ProgramClass) -> None:
            for declaration in owner.body:
                if isinstance(declaration, ProgramFunctionReference):
                    references.setdefault(declaration.function_id, []).append(owner.id)
                elif isinstance(declaration, ProgramClass):
                    visit(declaration)

        visit(module)
    for identity, kinds in identities.items():
        if not identity.strip():
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_EMPTY_IDENTITY",
                    Severity.ERROR,
                    "Canonical objects require a nonempty project identity",
                    identity,
                    "id",
                )
            )
        if len(kinds) > 1 and identity in new_ownership_ids:
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_DUPLICATE_OWNERSHIP",
                    Severity.ERROR,
                    "A Python declaration identity cannot denote multiple owned objects",
                    identity,
                    "program_model",
                )
            )
    for identity, owners in references.items():
        if model.function(identity) is None:
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_UNRESOLVED_FUNCTION_REFERENCE",
                    Severity.ERROR,
                    "An owning declaration references a missing function",
                    identity,
                    "body",
                )
            )
        if len(owners) != 1:
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_DUPLICATE_FUNCTION_OWNER",
                    Severity.ERROR,
                    "A function must occur in exactly one module or class body",
                    identity,
                    "body",
                )
            )
    for function in model.functions:
        if function.id not in references:
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_UNOWNED_FUNCTION",
                    Severity.ERROR,
                    "A function requires an owning module or class declaration",
                    function.id,
                    "body",
                )
            )
    if model.entrypoint is not None:
        for node in iter_program_nodes(model.entrypoint.startup):
            if isinstance(node, ProgramFunctionReference):
                diagnostics.append(
                    Diagnostic(
                        "PROGRAM_ENTRYPOINT_FUNCTION_OWNER",
                        Severity.ERROR,
                        "Entrypoint startup cannot own a programming function; "
                        "use a module or class",
                        model.entrypoint.id,
                        "startup",
                    )
                )
    for node in iter_program_nodes((model.modules, model.entrypoint)):
        if (
            isinstance(node, ProgramCall)
            and node.target_function_id is not None
            and model.function(node.target_function_id) is None
        ):
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_UNRESOLVED_CALL_TARGET",
                    Severity.ERROR,
                    "A linked canonical call must reference an existing function",
                    node.id,
                    "target_function_id",
                )
            )
    return diagnostics


def _integrity_program_model(project: Project) -> list[Diagnostic]:
    model = project.program_model
    diagnostics: list[Diagnostic] = []
    nodes = tuple(iter_program_nodes(model))
    all_expressions = tuple(node for node in nodes if isinstance(node, ProgramExpression))
    function_ids = [item.id for item in model.functions]
    symbol_ids = [item.id for item in model.symbols]
    view_document_ids = [item.document_id for item in project.drakon_views]
    for code, label, values in (
        ("PROGRAM_DUPLICATE_FUNCTION", "function", function_ids),
        ("PROGRAM_DUPLICATE_SYMBOL", "symbol", symbol_ids),
        ("PROGRAM_DUPLICATE_DRAKON_VIEW", "DRAKON view", view_document_ids),
    ):
        for duplicate in sorted(_duplicate_ids(values)):
            diagnostics.append(
                Diagnostic(
                    code,
                    Severity.ERROR,
                    f"Canonical {label} identifier {duplicate!r} is used more than once",
                    duplicate,
                    "program_model",
                )
            )
    diagnostics.extend(_integrity_program_ownership(model, nodes, all_expressions))
    function_set = set(function_ids)
    symbol_set = set(symbol_ids)
    symbols = {item.id: item for item in model.symbols}
    drakon_documents = {item.id for item in project.documents if isinstance(item, DrakonDiagram)}
    all_expression_identity_ids = tuple(
        identity
        for expression in all_expressions
        for identity in expression_identity_ids(expression.tree)
    )
    program_identity_kinds: dict[str, set[str]] = {}
    for kind, identities in (
        ("function", function_ids),
        ("symbol", symbol_ids),
        (
            "statement-or-sequence",
            [
                identity
                for function in model.functions
                for identity in _program_statement_ids(function.body)
            ],
        ),
        (
            "parameter",
            [item.id for function in model.functions for item in function.parameters],
        ),
        ("expression", [item.id for item in all_expressions]),
        ("expression-node", list(all_expression_identity_ids)),
    ):
        for identity in identities:
            program_identity_kinds.setdefault(identity, set()).add(kind)
    for identity, kinds in sorted(program_identity_kinds.items()):
        if len(kinds) < 2:
            continue
        diagnostics.append(
            Diagnostic(
                "PROGRAM_IDENTITY_COLLISION",
                Severity.ERROR,
                f"Canonical identifier {identity!r} denotes multiple semantic objects: "
                f"{', '.join(sorted(kinds))}",
                identity,
                "program_model",
            )
        )
    for code, label, values in (
        (
            "PROGRAM_DUPLICATE_EXPRESSION",
            "expression",
            [item.id for item in all_expressions],
        ),
        (
            "PROGRAM_DUPLICATE_EXPRESSION_NODE",
            "expression-node",
            list(all_expression_identity_ids),
        ),
    ):
        for duplicate in sorted(_duplicate_ids(values)):
            diagnostics.append(
                Diagnostic(
                    code,
                    Severity.ERROR,
                    f"Canonical {label} identifier {duplicate!r} is used more than once",
                    duplicate,
                    "program_model",
                )
            )
    for function in model.functions:
        local_ids = _program_statement_ids(function.body)
        for duplicate in sorted(_duplicate_ids(local_ids)):
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_DUPLICATE_STATEMENT",
                    Severity.ERROR,
                    f"Canonical statement identifier {duplicate!r} is used more than once",
                    duplicate,
                    "program_model",
                )
            )
        referenced_symbols = {
            function.symbol_id,
            *(item.symbol_id for item in function.parameters),
        }
        missing = sorted(referenced_symbols - symbol_set)
        for symbol_id in missing:
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_UNRESOLVED_SYMBOL",
                    Severity.ERROR,
                    f"Canonical symbol {symbol_id!r} does not exist",
                    symbol_id,
                    "program_model",
                )
            )
        parameter_ids = [item.id for item in function.parameters]
        for duplicate in sorted(_duplicate_ids(parameter_ids)):
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_DUPLICATE_PARAMETER",
                    Severity.ERROR,
                    f"Canonical parameter identifier {duplicate!r} is used more than once",
                    duplicate,
                    "program_model",
                )
            )
        expression_nodes = tuple(
            node
            for expression in _program_expressions(function)
            for node in _program_expression_nodes(expression)
        )
        for node in expression_nodes:
            if (
                isinstance(node, SymbolReferenceExpression)
                and node.symbol_id is not None
                and node.symbol_id not in symbol_set
            ):
                diagnostics.append(
                    Diagnostic(
                        "PROGRAM_UNRESOLVED_EXPRESSION_SYMBOL",
                        Severity.ERROR,
                        f"Expression symbol {node.symbol_id!r} does not exist",
                        node.id,
                        "program_model",
                    )
                )
        function_symbol = symbols.get(function.symbol_id)
        if function_symbol is not None and (
            function_symbol.kind is not ProgramSymbolKind.FUNCTION
            or function_symbol.owner_id != function.id
        ):
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_INVALID_FUNCTION_SYMBOL",
                    Severity.ERROR,
                    "A function symbol must be owned by its canonical function",
                    function.symbol_id,
                    "program_model",
                )
            )
        for parameter in function.parameters:
            symbol = symbols.get(parameter.symbol_id)
            if symbol is not None and (
                symbol.kind is not ProgramSymbolKind.PARAMETER
                or symbol.owner_id != function.id
                or symbol.declaration_id != parameter.id
                or symbol.name != parameter.name
            ):
                diagnostics.append(
                    Diagnostic(
                        "PROGRAM_INVALID_PARAMETER_SYMBOL",
                        Severity.ERROR,
                        "A parameter and its stable symbol identity must agree",
                        parameter.id,
                        "program_model",
                    )
                )
        for statement in _program_statements(function.body):
            written = (
                statement.written_symbol_ids
                if isinstance(statement, (ProgramAssignment, ProgramCall))
                else ()
            )
            for symbol_id in written:
                symbol = symbols.get(symbol_id)
                if symbol is None or symbol.owner_id != function.id:
                    diagnostics.append(
                        Diagnostic(
                            "PROGRAM_UNRESOLVED_WRITTEN_SYMBOL",
                            Severity.ERROR,
                            "A written symbol must exist in the statement's function",
                            statement.id,
                            "program_model",
                        )
                    )
            if (
                isinstance(statement, ProgramCall)
                and statement.target_function_id is not None
                and statement.target_function_id not in function_set
            ):
                diagnostics.append(
                    Diagnostic(
                        "PROGRAM_UNRESOLVED_CALL_TARGET",
                        Severity.ERROR,
                        "A linked canonical call must reference an existing function",
                        statement.id,
                        "program_model",
                    )
                )
    owned_structure_ids = [
        identity
        for function in model.functions
        for identity in (
            *_program_statement_ids(function.body),
            *(parameter.id for parameter in function.parameters),
        )
    ]
    for duplicate in sorted(_duplicate_ids(owned_structure_ids)):
        diagnostics.append(
            Diagnostic(
                "PROGRAM_DUPLICATE_OWNERSHIP",
                Severity.ERROR,
                "A canonical statement, sequence or parameter cannot have multiple owners",
                duplicate,
                "program_model",
            )
        )
    for symbol in model.symbols:
        if symbol.owner_id not in function_set:
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_UNRESOLVED_SYMBOL_OWNER",
                    Severity.ERROR,
                    "A canonical symbol must be owned by an existing function",
                    symbol.id,
                    "program_model",
                )
            )
    for view in project.drakon_views:
        if view.function_id not in function_set or view.document_id not in drakon_documents:
            diagnostics.append(
                Diagnostic(
                    "PROGRAM_UNRESOLVED_DRAKON_VIEW",
                    Severity.ERROR,
                    "DRAKON view must reference an existing canonical function and document",
                    view.document_id,
                    "program_model",
                )
            )
    return diagnostics


def validate_integrity(project: Project) -> tuple[Diagnostic, ...]:
    """Return only diagnostics that make canonical model state unsafe."""

    diagnostics: list[Diagnostic] = []
    if project.revision < 0:
        diagnostics.append(
            Diagnostic(
                "PROJECT_NEGATIVE_REVISION",
                Severity.ERROR,
                "Project revision must not be negative",
                project.id,
                "revision",
            )
        )
    document_ids = [document.id for document in project.documents]
    for duplicate in sorted(_duplicate_ids(document_ids)):
        diagnostics.append(
            Diagnostic(
                "DOC_DUPLICATE_ID",
                Severity.ERROR,
                f"Document identifier {duplicate!r} is used more than once",
                duplicate,
                category=DiagnosticCategory.TOPOLOGY,
            )
        )
    callable_ids = {function.id for function in project.program_model.functions}
    configured_arguments = project.program_model.entrypoint_arguments
    if not isinstance(
        configured_arguments, (InvocationArguments, UnresolvedInvocationArguments)
    ) or (
        isinstance(configured_arguments, UnresolvedInvocationArguments)
        and (
            not isinstance(configured_arguments.text, str)
            or len(configured_arguments.text) > 100_000
        )
    ):
        diagnostics.append(
            Diagnostic(
                "INVOCATION_ARGUMENT_STRUCTURE",
                Severity.ERROR,
                "Invocation arguments must be typed literal values or explicit incomplete notation",
                project.id,
                "entrypoint_arguments",
            )
        )
    if (
        project.program_model.entrypoint_callable_id is not None
        and project.program_model.entrypoint_callable_id not in callable_ids
    ):
        diagnostics.append(
            Diagnostic(
                "PROJECT_UNRESOLVED_ENTRYPOINT",
                Severity.ERROR,
                "The configured entry-point callable does not exist",
                project.id,
                "entrypoint_callable_id",
            )
        )
    for document in project.documents:
        diagnostics.extend(_integrity_document(document))
    diagnostics.extend(_integrity_program_model(project))
    diagnostics.extend(
        Diagnostic(item.code, Severity.ERROR, item.message, item.object_id, item.field)
        for item in validate_domain_workspace(project.domain_workspace)
        if not item.incomplete
    )
    # Domain identities share the semantic selection namespace with program and
    # authored concept identities. A collision can never silently replace a node.
    if (
        project.domain_workspace.schemas
        or project.domain_workspace.models
        or project.domain_workspace.language_definitions
    ):
        from code_visualizer.domain.language_structure import language_owned_ids

        domain_ids = [
            *(schema.id for schema in project.domain_workspace.schemas),
            *(
                concept.id
                for schema in project.domain_workspace.schemas
                for concept in schema.concepts
            ),
            *(
                identity
                for schema in project.domain_workspace.schemas
                for concept in schema.concepts
                for identity in (
                    *(item.id for item in concept.properties),
                    *(item.id for item in concept.containment_roles),
                    *(item.id for item in concept.reference_roles),
                    *(item.id for item in concept.constraints),
                )
            ),
            *(model.id for model in project.domain_workspace.models),
            *(node.id for model in project.domain_workspace.models for node in model.nodes),
            *(
                identity
                for language in project.domain_workspace.language_definitions
                for identity in language_owned_ids(language)
            ),
        ]
        program_ids = {
            project.id,
            *(item.id for item in project.concepts),
            *(item.id for item in project.program_model.symbols),
        }
        program_ids.update(
            identity
            for item in iter_program_nodes(project.program_model)
            if isinstance(identity := getattr(item, "id", None), str)
        )
        for expression in program_expressions(project.program_model):
            program_ids.update(expression_identity_ids(expression.tree))
        for identity in sorted(set(domain_ids) & program_ids):
            diagnostics.append(
                Diagnostic(
                    "DOMAIN_IDENTITY_COLLISION",
                    Severity.ERROR,
                    "Domain identity collides with another canonical semantic object",
                    identity,
                )
            )

    concept_ids = [concept.id for concept in project.concepts]
    concept_id_set = set(concept_ids)
    for duplicate in sorted(_duplicate_ids(concept_ids)):
        diagnostics.append(
            Diagnostic(
                "SEMANTIC_CONCEPT_DUPLICATE_ID",
                Severity.ERROR,
                f"Semantic concept identifier {duplicate!r} is used more than once",
                duplicate,
                "concepts",
            )
        )
    concept_members = {
        concept.id: tuple(member for member in concept.member_ids if member in concept_id_set)
        for concept in project.concepts
    }
    for concept_id in sorted(concept_id_set):
        pending = list(concept_members.get(concept_id, ()))
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == concept_id:
                diagnostics.append(
                    Diagnostic(
                        "SEMANTIC_CONCEPT_CYCLE",
                        Severity.ERROR,
                        "Conceptual containment must not contain a cycle",
                        concept_id,
                        "member_ids",
                    )
                )
                break
            if current in visited:
                continue
            visited.add(current)
            pending.extend(concept_members.get(current, ()))

    relation_ids = [relation.id for relation in project.semantic_relations]
    for duplicate in sorted(_duplicate_ids(relation_ids)):
        diagnostics.append(
            Diagnostic(
                "SEMANTIC_RELATION_DUPLICATE_ID",
                Severity.ERROR,
                f"Authored relationship identifier {duplicate!r} is used more than once",
                duplicate,
                "semantic_relations",
            )
        )
    projection_ids = [definition.id for definition in project.projection_definitions]
    for duplicate in sorted(_duplicate_ids(projection_ids)):
        diagnostics.append(
            Diagnostic(
                "PROJECTION_DUPLICATE_ID",
                Severity.ERROR,
                f"Projection identifier {duplicate!r} is used more than once",
                duplicate,
                "projection_definitions",
            )
        )
    live_definitions = tuple(
        document.live_projection
        for document in project.documents
        if isinstance(document, (MindMapDiagram, FreeformDiagram))
        and document.live_projection is not None
    )
    for definition in (*project.projection_definitions, *live_definitions):
        if not 1 <= definition.max_depth <= 64:
            diagnostics.append(
                Diagnostic(
                    "PROJECTION_INVALID_DEPTH",
                    Severity.ERROR,
                    "Projection traversal depth must be between 1 and 64",
                    definition.id,
                    "max_depth",
                )
            )
        if not 2 <= definition.node_limit <= 1000:
            diagnostics.append(
                Diagnostic(
                    "PROJECTION_INVALID_LIMIT",
                    Severity.ERROR,
                    "Projection object limit must be between 2 and 1000",
                    definition.id,
                    "node_limit",
                )
            )

    asset_ids = [asset.id for asset in project.managed_assets]
    asset_set = set(asset_ids)
    for duplicate in sorted(_duplicate_ids(asset_ids)):
        diagnostics.append(
            Diagnostic(
                "ASSET_DUPLICATE_ID",
                Severity.ERROR,
                f"Managed asset identifier {duplicate!r} is used more than once",
                duplicate,
                "managed_assets",
            )
        )
    for asset in project.managed_assets:
        path = PurePosixPath(asset.relative_path)
        safe_path = (
            not path.is_absolute()
            and "\\" not in asset.relative_path
            and ".." not in path.parts
            and "." not in path.parts
            and len(path.parts) >= 2
            and path.parts[0] == "assets"
        )
        if not safe_path:
            diagnostics.append(
                Diagnostic(
                    "ASSET_UNSAFE_PATH",
                    Severity.ERROR,
                    "Managed asset paths must stay beneath the project assets directory",
                    asset.id,
                    "relative_path",
                )
            )
        if re.fullmatch(r"[0-9a-f]{64}", asset.sha256) is None:
            diagnostics.append(
                Diagnostic(
                    "ASSET_INVALID_HASH",
                    Severity.ERROR,
                    "Managed asset SHA-256 must be 64 lowercase hexadecimal characters",
                    asset.id,
                    "sha256",
                )
            )
        if asset.byte_size < 0:
            diagnostics.append(
                Diagnostic(
                    "ASSET_INVALID_SIZE",
                    Severity.ERROR,
                    "Managed asset byte size cannot be negative",
                    asset.id,
                    "byte_size",
                )
            )
        if (asset.width is None) != (asset.height is None) or (
            asset.width is not None
            and asset.height is not None
            and (asset.width <= 0 or asset.height <= 0)
        ):
            diagnostics.append(
                Diagnostic(
                    "ASSET_INVALID_DIMENSIONS",
                    Severity.ERROR,
                    "Image dimensions must be a positive width/height pair",
                    asset.id,
                    "width",
                )
            )
    pack_ids = [pack.id for pack in project.shape_packs]
    for duplicate in sorted(_duplicate_ids(pack_ids)):
        diagnostics.append(
            Diagnostic(
                "SHAPE_PACK_DUPLICATE_ID",
                Severity.ERROR,
                f"Shape pack identifier {duplicate!r} is used more than once",
                duplicate,
                "shape_packs",
            )
        )
    for pack in project.shape_packs:
        path = PurePosixPath(pack.manifest_path)
        if (
            path.is_absolute()
            or "\\" in pack.manifest_path
            or ".." in path.parts
            or len(path.parts) < 3
            or path.parts[:2] != ("assets", "shape-packs")
        ):
            diagnostics.append(
                Diagnostic(
                    "SHAPE_PACK_UNSAFE_PATH",
                    Severity.ERROR,
                    "Shape pack manifests must stay beneath assets/shape-packs",
                    pack.id,
                    "manifest_path",
                )
            )
        if re.fullmatch(r"[0-9a-f]{64}", pack.sha256) is None:
            diagnostics.append(
                Diagnostic(
                    "SHAPE_PACK_INVALID_HASH",
                    Severity.ERROR,
                    "Shape pack SHA-256 must be 64 lowercase hexadecimal characters",
                    pack.id,
                    "sha256",
                )
            )
    for document in project.documents:
        if isinstance(document, FreeformDiagram):
            for item in document.objects:
                if (
                    isinstance(item, ShapeObject)
                    and item.asset_id is not None
                    and item.asset_id not in asset_set
                ):
                    diagnostics.append(
                        Diagnostic(
                            "ASSET_REFERENCE_NOT_FOUND",
                            Severity.ERROR,
                            "Image shape refers to a missing managed asset",
                            item.id,
                            "asset_id",
                            document.id,
                        )
                    )
        elif isinstance(document, MindMapDiagram):
            for topic in walk_topics(document.root):
                for attachment in topic.attachments:
                    if attachment not in asset_set:
                        diagnostics.append(
                            Diagnostic(
                                "ASSET_REFERENCE_NOT_FOUND",
                                Severity.ERROR,
                                "Mind-map attachment refers to a missing managed asset",
                                topic.id,
                                "attachments",
                                document.id,
                            )
                        )
    return tuple(diagnostics)


def _valid_dotted_name(value: str, *, allow_empty: bool = False) -> bool:
    if not value:
        return allow_empty
    return all(part.isidentifier() and not keyword.iskeyword(part) for part in value.split("."))


def _python_error(
    code: str,
    message: str,
    *,
    object_id: str | None,
    field: str,
    diagram_id: str | None = None,
    repair: str = "Enter valid Python for this field.",
) -> Diagnostic:
    return Diagnostic(
        code,
        Severity.ERROR,
        message,
        object_id,
        field,
        diagram_id,
        DiagnosticCategory.PYTHON,
        repair,
    )


def _parse_field(
    source: str,
    *,
    mode: str,
    code: str,
    label: str,
    object_id: str | None,
    field: str,
    diagram_id: str | None = None,
    allow_empty: bool = False,
) -> Diagnostic | None:
    if not source.strip() and allow_empty:
        return None
    if not source.strip():
        return _python_error(
            code,
            f"{label} is empty",
            object_id=object_id,
            field=field,
            diagram_id=diagram_id,
        )
    try:
        ast.parse(source, mode=mode)
    except SyntaxError as exc:
        location = f"line {exc.lineno}, column {exc.offset}" if exc.lineno else "unknown location"
        return _python_error(
            code,
            f"{label} is not valid Python ({location}): {exc.msg}",
            object_id=object_id,
            field=field,
            diagram_id=diagram_id,
        )
    return None


@dataclass(frozen=True, slots=True)
class _FlowContext:
    callable_kind: CallableKind
    loop_depth: int = 0
    nested_function_depth: int = 0
    in_exception_handler: bool = False
    in_except_star: bool = False


_COMPOUND_OR_TRANSFER_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Match,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Return,
    ast.Raise,
    ast.Yield,
    ast.YieldFrom,
    ast.Break,
    ast.Continue,
)


def _flow_error(
    code: str,
    message: str,
    document: DrakonDiagram,
    object_id: str,
    field: str,
    repair: str,
) -> Diagnostic:
    return _python_error(
        code,
        message,
        object_id=object_id,
        field=field,
        diagram_id=document.id,
        repair=repair,
    )


def _append_parse(
    diagnostics: list[Diagnostic],
    document: DrakonDiagram,
    source: str,
    *,
    mode: str,
    code: str,
    label: str,
    object_id: str,
    field: str,
    allow_empty: bool = False,
) -> None:
    diagnostic = _parse_field(
        source,
        mode=mode,
        code=code,
        label=label,
        object_id=object_id,
        field=field,
        diagram_id=document.id,
        allow_empty=allow_empty,
    )
    if diagnostic is not None:
        diagnostics.append(diagnostic)


def _requires_async(
    diagnostics: list[Diagnostic],
    document: DrakonDiagram,
    context: _FlowContext,
    object_id: str,
    field: str,
    label: str,
) -> None:
    if context.callable_kind not in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR}:
        diagnostics.append(
            _flow_error(
                "PY_AWAIT_OUTSIDE_ASYNC",
                f"{label} requires an async function",
                document,
                object_id,
                field,
                "Change the function kind to async or use the synchronous construct.",
            )
        )


def _intersect_timers(outputs: list[frozenset[str]], fallback: frozenset[str]) -> frozenset[str]:
    if not outputs:
        return fallback
    result = set(outputs[0])
    for output in outputs[1:]:
        result.intersection_update(output)
    return frozenset(result)


def _async_syntax_fields(atom: DrakonAtom) -> tuple[tuple[str, str, str], ...]:
    if isinstance(atom, Action):
        return ((atom.source, "exec", "source"),)
    if isinstance(atom, Output):
        return tuple(
            (source, "eval", field)
            for source, field in (
                (atom.expression, "expression"),
                (atom.destination or "", "destination"),
                (atom.end or "", "end"),
            )
            if source
        )
    if isinstance(atom, Assignment):
        target = atom.target + (f": {atom.annotation}" if atom.annotation else "")
        return ((f"{target} {atom.operator} {atom.value}", "exec", "value"),)
    if isinstance(atom, If):
        return ((atom.condition, "eval", "condition"),)
    if isinstance(atom, Transfer):
        return tuple(
            (source, "eval", field)
            for source, field in ((atom.expression, "expression"), (atom.cause or "", "cause"))
            if source
        )
    if isinstance(atom, SimpleStatement):
        return ((atom.source, "exec", "source"),)
    if isinstance(atom, Call):
        if atom.target_diagram_id is not None:
            return ((f"_linked_call({atom.arguments})", "eval", "arguments"),)
        return ((atom.expression, "eval", "expression"),)
    if isinstance(atom, Input):
        return tuple(
            (source, "eval", field)
            for source, field in ((atom.prompt, "prompt"), (atom.converter or "", "converter"))
            if source
        )
    if isinstance(atom, (Delay, Period)):
        return ((atom.seconds, "eval", "seconds"),)
    if isinstance(atom, RealtimeProcess):
        return ((atom.call, "eval", "call"),)
    if isinstance(atom, Select):
        result = [(atom.expression, "eval", "expression")]
        for case in atom.cases:
            result.append((case.condition, "eval", "condition"))
            if case.guard:
                result.append((case.guard, "eval", "guard"))
        return tuple(result)
    if isinstance(atom, Loop):
        return (
            (atom.condition, "eval", "condition"),
            (atom.iterable, "eval", "iterable"),
            (atom.children, "eval", "children"),
            (atom.delay_seconds, "eval", "delay_seconds"),
        )
    if isinstance(atom, With):
        return tuple((item.expression, "eval", "expression") for item in atom.contexts)
    if isinstance(atom, Try):
        return tuple((item.exception, "eval", "exception") for item in atom.handlers)
    if isinstance(atom, Synchronizer):
        return ((atom.deadline, "eval", "deadline"),)
    return ()


def _contains_async_syntax(source: str, mode: str) -> bool:
    try:
        tree = ast.parse(source, mode=mode)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.Await) or (isinstance(node, ast.comprehension) and bool(node.is_async))
        for node in ast.walk(tree)
    )


def _validate_sequence(
    document: DrakonDiagram,
    sequence: Sequence,
    context: _FlowContext,
    timers_in: frozenset[str] = frozenset(),
) -> tuple[list[Diagnostic], frozenset[str]]:
    diagnostics: list[Diagnostic] = []
    timers = timers_in
    for atom in sequence.atoms:
        # These expression fields are checked by _validate_program_sequence.
        expressions_checked = isinstance(atom, (Assignment, Output, Call, If))
        for source, mode, field in () if expressions_checked else _async_syntax_fields(atom):
            if _contains_async_syntax(source, mode):
                _requires_async(
                    diagnostics,
                    document,
                    context,
                    atom.id,
                    field,
                    "Async expression",
                )
        if isinstance(atom, Action):
            _append_parse(
                diagnostics,
                document,
                atom.source,
                mode="exec",
                code="PY_INVALID_ACTION",
                label="Action source",
                object_id=atom.id,
                field="source",
            )
            try:
                tree = ast.parse(atom.source, mode="exec")
            except SyntaxError:
                tree = None
            if tree is not None and any(
                isinstance(node, _COMPOUND_OR_TRANSFER_NODES) for node in ast.walk(tree)
            ):
                diagnostics.append(
                    _flow_error(
                        "PY_ACTION_OWNS_TOPOLOGY",
                        "Raw Action source cannot hide a compound or flow-transfer statement",
                        document,
                        atom.id,
                        "source",
                        "Use the corresponding visual If, loop, Try, With, or transfer icon.",
                    )
                )
        elif isinstance(atom, (Output, Assignment)):
            pass
        elif isinstance(atom, If):
            true_diagnostics, true_timers = _validate_sequence(
                document, atom.true_branch, context, timers
            )
            false_diagnostics, false_timers = _validate_sequence(
                document, atom.false_branch, context, timers
            )
            diagnostics.extend(true_diagnostics)
            diagnostics.extend(false_diagnostics)
            timers = true_timers & false_timers
        elif isinstance(atom, Transfer):
            expression_optional = atom.transfer_kind in {
                TransferKind.RETURN,
                TransferKind.RAISE,
                TransferKind.YIELD,
                TransferKind.BREAK,
                TransferKind.CONTINUE,
            }
            if atom.transfer_kind not in {TransferKind.BREAK, TransferKind.CONTINUE}:
                _append_parse(
                    diagnostics,
                    document,
                    atom.expression,
                    mode="eval",
                    code="PY_INVALID_TRANSFER",
                    label=atom.transfer_kind.value.replace("_", " ").title(),
                    object_id=atom.id,
                    field="expression",
                    allow_empty=expression_optional,
                )
            if atom.cause:
                _append_parse(
                    diagnostics,
                    document,
                    atom.cause,
                    mode="eval",
                    code="PY_INVALID_TRANSFER",
                    label="Raise cause",
                    object_id=atom.id,
                    field="cause",
                )
            if (
                atom.transfer_kind in {TransferKind.BREAK, TransferKind.CONTINUE}
                and not context.loop_depth
            ):
                diagnostics.append(
                    _flow_error(
                        "PY_LOOP_TRANSFER_OUTSIDE_LOOP",
                        f"{atom.transfer_kind.value.title()} is not inside a loop",
                        document,
                        atom.id,
                        "transfer_kind",
                        "Move this icon into a visual loop body.",
                    )
                )
            if context.in_except_star and atom.transfer_kind in {
                TransferKind.RETURN,
                TransferKind.BREAK,
                TransferKind.CONTINUE,
            }:
                diagnostics.append(
                    _flow_error(
                        "PY_TRANSFER_INSIDE_EXCEPT_STAR",
                        f"{atom.transfer_kind.value.title()} is illegal inside except*",
                        document,
                        atom.id,
                        "transfer_kind",
                        "Move the transfer after the exception-group handler.",
                    )
                )
            if atom.transfer_kind in {TransferKind.YIELD, TransferKind.YIELD_FROM}:
                if context.callable_kind not in {
                    CallableKind.GENERATOR,
                    CallableKind.ASYNC_GENERATOR,
                }:
                    diagnostics.append(
                        _flow_error(
                            "PY_YIELD_OUTSIDE_GENERATOR",
                            "Yield requires a generator function",
                            document,
                            atom.id,
                            "transfer_kind",
                            "Change the function kind to generator or async generator.",
                        )
                    )
                if (
                    atom.transfer_kind is TransferKind.YIELD_FROM
                    and context.callable_kind is CallableKind.ASYNC_GENERATOR
                ):
                    diagnostics.append(
                        _flow_error(
                            "PY_YIELD_FROM_ASYNC_GENERATOR",
                            "Async generators cannot use yield from",
                            document,
                            atom.id,
                            "transfer_kind",
                            "Use Yield in a loop or change to a synchronous generator.",
                        )
                    )
            if (
                atom.transfer_kind is TransferKind.RETURN
                and atom.expression.strip()
                and atom.expression.strip() != "None"
                and context.callable_kind is CallableKind.ASYNC_GENERATOR
            ):
                diagnostics.append(
                    _flow_error(
                        "PY_RETURN_VALUE_ASYNC_GENERATOR",
                        "Async generators cannot return a value",
                        document,
                        atom.id,
                        "expression",
                        "Leave the Return expression empty.",
                    )
                )
            if (
                atom.transfer_kind is TransferKind.RAISE
                and not atom.expression.strip()
                and not context.in_exception_handler
            ):
                diagnostics.append(
                    _flow_error(
                        "PY_BARE_RAISE_OUTSIDE_HANDLER",
                        "Bare raise is only legal in an exception handler",
                        document,
                        atom.id,
                        "expression",
                        "Provide an exception expression or move it into an except branch.",
                    )
                )
        elif isinstance(atom, SimpleStatement):
            prefixes = {
                SimpleKind.PASS: "pass",
                SimpleKind.DELETE: f"del {atom.source}",
                SimpleKind.GLOBAL: f"global {atom.source}",
                SimpleKind.NONLOCAL: f"nonlocal {atom.source}",
                SimpleKind.ASSERT: f"assert {atom.source}"
                + (f", {atom.secondary}" if atom.secondary else ""),
                SimpleKind.EXPRESSION: atom.source,
            }
            _append_parse(
                diagnostics,
                document,
                prefixes[atom.statement_kind],
                mode="exec",
                code="PY_INVALID_SIMPLE_STATEMENT",
                label=atom.statement_kind.value.title(),
                object_id=atom.id,
                field="source",
            )
            if atom.statement_kind is SimpleKind.NONLOCAL and not context.nested_function_depth:
                diagnostics.append(
                    _flow_error(
                        "PY_NONLOCAL_WITHOUT_ENCLOSING_FUNCTION",
                        "Nonlocal requires an enclosing generated function scope",
                        document,
                        atom.id,
                        "source",
                        "Use this inside a process branch or remove the Nonlocal icon.",
                    )
                )
        elif isinstance(atom, Call):
            pass
        elif isinstance(atom, Input):
            expression = f"input({atom.prompt})"
            if atom.converter:
                expression = f"{atom.converter}({expression})"
            target = atom.target + (f": {atom.annotation}" if atom.annotation else "")
            _append_parse(
                diagnostics,
                document,
                f"{target} = {expression}",
                mode="exec",
                code="PY_INVALID_INPUT",
                label="Input",
                object_id=atom.id,
                field="prompt",
            )
        elif isinstance(atom, Delay):
            _append_parse(
                diagnostics,
                document,
                atom.seconds,
                mode="eval",
                code="PY_INVALID_DURATION",
                label="Delay duration",
                object_id=atom.id,
                field="seconds",
            )
            if atom.asynchronous:
                _requires_async(
                    diagnostics, document, context, atom.id, "asynchronous", "Async Delay"
                )
        elif isinstance(atom, StartTimer):
            if not atom.timer.isidentifier() or keyword.iskeyword(atom.timer):
                diagnostics.append(
                    _flow_error(
                        "PY_INVALID_TIMER_NAME",
                        f"{atom.timer!r} is not a legal timer name",
                        document,
                        atom.id,
                        "timer",
                        "Use a readable Python identifier such as request_cycle.",
                    )
                )
            else:
                timers = timers | {atom.timer}
        elif isinstance(atom, Period):
            _append_parse(
                diagnostics,
                document,
                atom.seconds,
                mode="eval",
                code="PY_INVALID_DURATION",
                label="Period duration",
                object_id=atom.id,
                field="seconds",
            )
            if atom.timer not in timers:
                diagnostics.append(
                    _flow_error(
                        "PY_TIMER_BEFORE_START",
                        f"Timer {atom.timer!r} may be used before Start Timer",
                        document,
                        atom.id,
                        "timer",
                        "Place a matching Start Timer on every route before this Period.",
                    )
                )
            if atom.asynchronous:
                _requires_async(
                    diagnostics, document, context, atom.id, "asynchronous", "Async Period"
                )
        elif isinstance(atom, RealtimeProcess):
            _append_parse(
                diagnostics,
                document,
                atom.call,
                mode="eval",
                code="PY_INVALID_CALL",
                label="Realtime process call",
                object_id=atom.id,
                field="call",
            )
            if atom.awaited:
                _requires_async(
                    diagnostics, document, context, atom.id, "awaited", "Awaited process"
                )
        elif isinstance(atom, Note):
            pass
        elif isinstance(atom, Select):
            if len(atom.cases) < 2:
                diagnostics.append(
                    _flow_error(
                        "DRAKON_SELECT_NEEDS_CASES",
                        "Select requires at least two ordered cases",
                        document,
                        atom.id,
                        "cases",
                        "Add a case and an explicit default route.",
                    )
                )
            defaults = [index for index, case in enumerate(atom.cases) if case.is_default]
            if len(defaults) != 1 or (defaults and defaults[0] != len(atom.cases) - 1):
                diagnostics.append(
                    _flow_error(
                        "DRAKON_SELECT_DEFAULT_ORDER",
                        "Select needs exactly one final default case",
                        document,
                        atom.id,
                        "cases",
                        "Mark only the final case as the default route.",
                    )
                )
            if atom.mode is SelectMode.MATCH:
                _append_parse(
                    diagnostics,
                    document,
                    atom.expression,
                    mode="eval",
                    code="PY_INVALID_EXPRESSION",
                    label="Match subject",
                    object_id=atom.id,
                    field="expression",
                )
            case_outputs: list[frozenset[str]] = []
            for case in atom.cases:
                if atom.mode is SelectMode.CONDITIONS and not case.is_default:
                    _append_parse(
                        diagnostics,
                        document,
                        case.condition,
                        mode="eval",
                        code="PY_INVALID_CONDITION",
                        label=f"Case {case.label} condition",
                        object_id=case.id,
                        field="condition",
                    )
                elif atom.mode is SelectMode.MATCH:
                    guard = f" if {case.guard}" if case.guard else ""
                    _append_parse(
                        diagnostics,
                        document,
                        f"match _value:\n    case {case.pattern}{guard}:\n        pass",
                        mode="exec",
                        code="PY_INVALID_MATCH_CASE",
                        label=f"Case {case.label} pattern",
                        object_id=case.id,
                        field="pattern",
                    )
                case_diagnostics, case_timers = _validate_sequence(
                    document, case.body, context, timers
                )
                diagnostics.extend(case_diagnostics)
                case_outputs.append(case_timers)
            timers = _intersect_timers(case_outputs, timers)
        elif isinstance(atom, Loop):
            for source, field, label in (
                (atom.condition, "condition", "Loop condition"),
                (atom.iterable, "iterable", "Loop iterable"),
                (atom.children, "children", "TREE children expression"),
                (atom.delay_seconds, "delay_seconds", "Wait delay"),
            ):
                _append_parse(
                    diagnostics,
                    document,
                    source,
                    mode="eval",
                    code="PY_INVALID_LOOP_FIELD",
                    label=label,
                    object_id=atom.id,
                    field=field,
                )
            _append_parse(
                diagnostics,
                document,
                f"for {atom.target} in ():\n    pass",
                mode="exec",
                code="PY_INVALID_LOOP_TARGET",
                label="Loop target",
                object_id=atom.id,
                field="target",
            )
            if atom.loop_kind is LoopKind.ASYNC_FOR:
                _requires_async(diagnostics, document, context, atom.id, "loop_kind", "Async For")
            loop_context = _FlowContext(
                context.callable_kind,
                context.loop_depth + 1,
                context.nested_function_depth,
                context.in_exception_handler,
                context.in_except_star,
            )
            body_diagnostics, _ = _validate_sequence(document, atom.body, loop_context, timers)
            else_diagnostics, _ = _validate_sequence(document, atom.else_body, context, timers)
            diagnostics.extend(body_diagnostics)
            diagnostics.extend(else_diagnostics)
        elif isinstance(atom, With):
            if not atom.contexts:
                diagnostics.append(
                    _flow_error(
                        "DRAKON_WITH_NEEDS_CONTEXT",
                        "With requires at least one context manager",
                        document,
                        atom.id,
                        "contexts",
                        "Add a context manager expression.",
                    )
                )
            for item in atom.contexts:
                target = f" as {item.target}" if item.target else ""
                prefix = "async " if atom.asynchronous else ""
                _append_parse(
                    diagnostics,
                    document,
                    f"{prefix}with {item.expression}{target}:\n    pass",
                    mode="exec",
                    code="PY_INVALID_CONTEXT_MANAGER",
                    label="Context manager",
                    object_id=item.id,
                    field="expression",
                )
            if atom.asynchronous:
                _requires_async(
                    diagnostics, document, context, atom.id, "asynchronous", "Async With"
                )
            body_diagnostics, _ = _validate_sequence(document, atom.body, context, timers)
            diagnostics.extend(body_diagnostics)
        elif isinstance(atom, Try):
            if not atom.handlers and not atom.finally_body.atoms:
                diagnostics.append(
                    _flow_error(
                        "DRAKON_TRY_NEEDS_HANDLER",
                        "Try requires an exception handler or finally branch",
                        document,
                        atom.id,
                        "handlers",
                        "Add an except or finally branch.",
                    )
                )
            body_diagnostics, _ = _validate_sequence(document, atom.body, context, timers)
            diagnostics.extend(body_diagnostics)
            for handler in atom.handlers:
                _append_parse(
                    diagnostics,
                    document,
                    handler.exception,
                    mode="eval",
                    code="PY_INVALID_EXCEPTION_TYPE",
                    label="Exception type",
                    object_id=handler.id,
                    field="exception",
                )
                handler_context = _FlowContext(
                    context.callable_kind,
                    context.loop_depth,
                    context.nested_function_depth,
                    True,
                    atom.except_star,
                )
                handler_diagnostics, _ = _validate_sequence(
                    document, handler.body, handler_context, timers
                )
                diagnostics.extend(handler_diagnostics)
            for branch in (atom.else_body, atom.finally_body):
                branch_diagnostics, _ = _validate_sequence(document, branch, context, timers)
                diagnostics.extend(branch_diagnostics)
        elif isinstance(atom, Synchronizer):
            _append_parse(
                diagnostics,
                document,
                atom.deadline,
                mode="eval",
                code="PY_INVALID_DURATION",
                label="Synchronizer deadline",
                object_id=atom.id,
                field="deadline",
            )
            if atom.timer not in timers:
                diagnostics.append(
                    _flow_error(
                        "PY_TIMER_BEFORE_START",
                        f"Timer {atom.timer!r} may be used before Start Timer",
                        document,
                        atom.id,
                        "timer",
                        "Place a matching Start Timer on every route before this Synchronizer.",
                    )
                )
            on_time_diagnostics, on_time_timers = _validate_sequence(
                document, atom.on_time, context, timers
            )
            timeout_diagnostics, timeout_timers = _validate_sequence(
                document, atom.on_timeout, context, timers
            )
            diagnostics.extend(on_time_diagnostics)
            diagnostics.extend(timeout_diagnostics)
            timers = on_time_timers & timeout_timers
        elif isinstance(atom, Parallel):
            if len(atom.branches) < 2:
                diagnostics.append(
                    _flow_error(
                        "DRAKON_PARALLEL_NEEDS_BRANCHES",
                        "Parallel requires at least two processes",
                        document,
                        atom.id,
                        "branches",
                        "Add another process branch.",
                    )
                )
            if atom.mode is ParallelMode.ASYNC:
                _requires_async(diagnostics, document, context, atom.id, "mode", "Async Parallel")
            branch_names = [branch.name.casefold() for branch in atom.branches]
            if _duplicate_ids(branch_names):
                diagnostics.append(
                    _flow_error(
                        "DRAKON_DUPLICATE_PROCESS_NAME",
                        "Parallel process names must be unique",
                        document,
                        atom.id,
                        "branches",
                        "Give each process a distinct readable name.",
                    )
                )
            branch_kind = (
                CallableKind.ASYNC if atom.mode is ParallelMode.ASYNC else CallableKind.SYNC
            )
            branch_context = _FlowContext(
                branch_kind,
                0,
                context.nested_function_depth + 1,
            )
            for parallel_branch in atom.branches:
                branch_diagnostics, _ = _validate_sequence(
                    document, parallel_branch.body, branch_context, timers
                )
                diagnostics.extend(branch_diagnostics)
        elif isinstance(atom, Silhouette):
            if not atom.identifier.isidentifier() or keyword.iskeyword(atom.identifier):
                diagnostics.append(
                    _flow_error(
                        "PY_INVALID_SILHOUETTE_IDENTIFIER",
                        f"{atom.identifier!r} is not a legal silhouette identifier",
                        document,
                        atom.id,
                        "identifier",
                        "Use a readable identifier such as golden_node.",
                    )
                )
            branch_ids = {branch.id for branch in atom.branches}
            if atom.initial_branch_id not in branch_ids:
                diagnostics.append(
                    _flow_error(
                        "DRAKON_SILHOUETTE_INITIAL_MISSING",
                        "Silhouette initial address does not exist",
                        document,
                        atom.id,
                        "initial_branch_id",
                        "Choose an existing named state as the initial address.",
                    )
                )
            exits = [branch for branch in atom.branches if branch.target_branch_id is None]
            if len(exits) != 1:
                diagnostics.append(
                    _flow_error(
                        "DRAKON_SILHOUETTE_EXIT_COUNT",
                        "Silhouette requires exactly one finite exit state",
                        document,
                        atom.id,
                        "branches",
                        "Leave exactly one state without a transition target.",
                    )
                )
            names = [branch.name.casefold() for branch in atom.branches]
            if _duplicate_ids(names):
                diagnostics.append(
                    _flow_error(
                        "DRAKON_SILHOUETTE_DUPLICATE_STATE",
                        "Silhouette state names must be unique",
                        document,
                        atom.id,
                        "branches",
                        "Give each state a distinct human-readable name.",
                    )
                )
            for silhouette_branch in atom.branches:
                if (
                    silhouette_branch.target_branch_id is not None
                    and silhouette_branch.target_branch_id not in branch_ids
                ):
                    diagnostics.append(
                        _flow_error(
                            "DRAKON_SILHOUETTE_TARGET_MISSING",
                            f"State {silhouette_branch.name!r} points to a missing address",
                            document,
                            silhouette_branch.id,
                            "target_branch_id",
                            "Choose an existing state or the finite exit.",
                        )
                    )
                branch_context = _FlowContext(
                    context.callable_kind,
                    0,
                    context.nested_function_depth,
                    context.in_exception_handler,
                    context.in_except_star,
                )
                branch_diagnostics, _ = _validate_sequence(
                    document, silhouette_branch.body, branch_context, timers
                )
                diagnostics.extend(branch_diagnostics)
            branches_by_id = {branch.id: branch for branch in atom.branches}
            if atom.initial_branch_id in branches_by_id and all(
                branch.target_branch_id is None or branch.target_branch_id in branches_by_id
                for branch in atom.branches
            ):
                visited: set[str] = set()
                current: str | None = atom.initial_branch_id
                while current is not None and current not in visited:
                    visited.add(current)
                    current = branches_by_id[current].target_branch_id
                if current is not None:
                    diagnostics.append(
                        _flow_error(
                            "DRAKON_SILHOUETTE_NONTERMINATING",
                            "The initial silhouette route repeats without reaching its finite exit",
                            document,
                            atom.id,
                            "initial_branch_id",
                            "Retarget one Address on the repeated route to the finite exit.",
                        )
                    )
                for unreachable_id in sorted(branch_ids - visited):
                    unreachable = branches_by_id[unreachable_id]
                    diagnostics.append(
                        _flow_error(
                            "DRAKON_SILHOUETTE_UNREACHABLE_STATE",
                            f"State {unreachable.name!r} cannot be reached from the initial state",
                            document,
                            unreachable.id,
                            "name",
                            "Retarget an Address to this state or remove the unreachable branch.",
                        )
                    )
    return diagnostics, timers


def _program_requires_async(
    diagnostics: list[Diagnostic],
    function: ProgramFunction,
    object_id: str,
    field: str,
    label: str,
    diagram_id: str | None,
) -> None:
    if function.kind not in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR}:
        diagnostics.append(
            _python_error(
                "PY_AWAIT_OUTSIDE_ASYNC",
                f"{label} requires an async function",
                object_id=object_id,
                field=field,
                diagram_id=diagram_id,
                repair="Change the function kind to async or use synchronous Python.",
            )
        )


def _append_program_parse(
    diagnostics: list[Diagnostic],
    source: str,
    *,
    mode: str,
    code: str,
    label: str,
    object_id: str,
    field: str,
    diagram_id: str | None,
    allow_empty: bool = False,
) -> None:
    diagnostic = _parse_field(
        source,
        mode=mode,
        code=code,
        label=label,
        object_id=object_id,
        field=field,
        diagram_id=diagram_id,
        allow_empty=allow_empty,
    )
    if diagnostic is not None:
        diagnostics.append(diagnostic)


def _validate_program_sequence(
    function: ProgramFunction,
    sequence: ProgramSequence,
    diagram_id: str | None,
) -> list[Diagnostic]:
    """Validate executable semantics owned by one canonical statement tree."""

    diagnostics: list[Diagnostic] = []
    for statement in program_statements(sequence):
        if isinstance(statement, ProgramAssignment):
            target = statement.target.source
            if statement.annotation is not None:
                target += f": {statement.annotation.source}"
            source = f"{target} {statement.operator} {statement.value.source}"
            _append_program_parse(
                diagnostics,
                source,
                mode="exec",
                code="PY_INVALID_ASSIGNMENT",
                label="Assignment",
                object_id=statement.id,
                field="value",
                diagram_id=diagram_id,
            )
            if _contains_async_syntax(source, "exec"):
                _program_requires_async(
                    diagnostics,
                    function,
                    statement.id,
                    "value",
                    "Async assignment expression",
                    diagram_id,
                )
        elif isinstance(statement, ProgramOutput):
            fields = (
                (statement.expression, "expression", "Output expression"),
                (statement.destination, "destination", "Output destination"),
                (statement.end, "end", "Output end value"),
            )
            for expression, field, label in fields:
                if expression is None:
                    continue
                source = expression.source
                _append_program_parse(
                    diagnostics,
                    source,
                    mode="eval",
                    code="PY_INVALID_EXPRESSION",
                    label=label,
                    object_id=statement.id,
                    field=field,
                    diagram_id=diagram_id,
                )
                if _contains_async_syntax(source, "eval"):
                    _program_requires_async(
                        diagnostics,
                        function,
                        statement.id,
                        field,
                        f"Async {label.lower()}",
                        diagram_id,
                    )
        elif isinstance(statement, ProgramCall):
            linked = statement.target_function_id is not None
            source = (
                f"_linked_call({statement.arguments.source})"
                if linked
                else statement.expression.source
            )
            _append_program_parse(
                diagnostics,
                source,
                mode="eval",
                code="PY_INVALID_CALL",
                label="Linked call arguments" if linked else "Call expression",
                object_id=statement.id,
                field="arguments" if linked else "expression",
                diagram_id=diagram_id,
            )
            if statement.result_target is not None:
                _append_program_parse(
                    diagnostics,
                    f"{statement.result_target.source} = None",
                    mode="exec",
                    code="PY_INVALID_ASSIGNMENT_TARGET",
                    label="Call result target",
                    object_id=statement.id,
                    field="result_target",
                    diagram_id=diagram_id,
                )
            async_source = statement.expression.source if not linked else statement.arguments.source
            if statement.awaited or _contains_async_syntax(async_source, "eval"):
                _program_requires_async(
                    diagnostics,
                    function,
                    statement.id,
                    "awaited" if statement.awaited else "expression",
                    "Await Call" if statement.awaited else "Async call expression",
                    diagram_id,
                )
        elif isinstance(statement, ProgramIf):
            source = statement.condition.source
            _append_program_parse(
                diagnostics,
                source,
                mode="eval",
                code="PY_INVALID_CONDITION",
                label="If condition",
                object_id=statement.id,
                field="condition",
                diagram_id=diagram_id,
            )
            if _contains_async_syntax(source, "eval"):
                _program_requires_async(
                    diagnostics,
                    function,
                    statement.id,
                    "condition",
                    "Async condition",
                    diagram_id,
                )
    return diagnostics


def _validate_program_function(
    function: ProgramFunction,
    diagram_id: str | None,
    location: ProgramFunctionLocation | None,
) -> list[Diagnostic]:
    """Validate a callable without consulting any visual projection."""

    diagnostics: list[Diagnostic] = []
    if not function.identifier.isidentifier() or keyword.iskeyword(function.identifier):
        diagnostics.append(
            _python_error(
                "PY_INVALID_IDENTIFIER",
                f"{function.identifier!r} is not a legal Python identifier",
                object_id=function.id,
                field="identifier",
                diagram_id=diagram_id,
                repair="Choose a unique identifier using letters, digits, and underscores.",
            )
        )
    parameter_names: list[str] = []
    for parameter in function.parameters:
        parameter_names.append(parameter.name)
        if not parameter.name.isidentifier() or keyword.iskeyword(parameter.name):
            diagnostics.append(
                _python_error(
                    "PY_INVALID_PARAMETER",
                    f"{parameter.name!r} is not a legal parameter name",
                    object_id=parameter.id,
                    field="name",
                    diagram_id=diagram_id,
                )
            )
        for expression, code, label, field in (
            (
                parameter.default,
                "PY_INVALID_DEFAULT",
                f"Default for {parameter.name}",
                "default",
            ),
            (
                parameter.annotation,
                "PY_INVALID_ANNOTATION",
                f"Annotation for {parameter.name}",
                "annotation",
            ),
        ):
            if expression is not None:
                _append_program_parse(
                    diagnostics,
                    expression.source,
                    mode="eval",
                    code=code,
                    label=label,
                    object_id=expression.id,
                    field=field,
                    diagram_id=diagram_id,
                )
    for duplicate in sorted(_duplicate_ids(parameter_names)):
        diagnostics.append(
            _python_error(
                "PY_DUPLICATE_PARAMETER",
                f"Parameter {duplicate!r} is defined more than once",
                object_id=function.id,
                field="parameters",
                diagram_id=diagram_id,
                repair="Give each parameter a unique name.",
            )
        )
    if function.return_annotation is not None:
        _append_program_parse(
            diagnostics,
            function.return_annotation.source,
            mode="eval",
            code="PY_INVALID_ANNOTATION",
            label="Return annotation",
            object_id=function.return_annotation.id,
            field="return_annotation",
            diagram_id=diagram_id,
        )
    for decorator in function.decorators:
        _append_program_parse(
            diagnostics,
            decorator.source,
            mode="eval",
            code="PY_INVALID_DECORATOR",
            label="Decorator",
            object_id=decorator.id,
            field="decorators",
            diagram_id=diagram_id,
        )
    module_path = location.module.path if location is not None else ""
    class_name = location.class_name if location is not None else None
    if not _valid_dotted_name(
        module_path,
        allow_empty=location is not None and location.module.kind is ProgramModuleKind.PACKAGE,
    ):
        diagnostics.append(
            _python_error(
                "PY_INVALID_MODULE_PATH",
                f"{module_path!r} is not a legal dotted module path",
                object_id=function.id,
                field="module",
                diagram_id=diagram_id,
                repair="Assign the function to a configured dotted module path.",
            )
        )
    if class_name is not None and not _valid_dotted_name(class_name):
        diagnostics.append(
            _python_error(
                "PY_INVALID_CLASS_NAME",
                f"{class_name!r} is not a legal class name",
                object_id=function.id,
                field="owning_class",
                diagram_id=diagram_id,
                repair="Use a Python identifier such as SearchEngine.",
            )
        )
    if class_name is None and function.method_kind is not None:
        diagnostics.append(
            _python_error(
                "PY_METHOD_WITHOUT_CLASS",
                "A method kind requires an owning class",
                object_id=function.id,
                field="method_kind",
                diagram_id=diagram_id,
                repair="Choose an owning class or make this a module-level function.",
            )
        )
    if class_name is not None and function.method_kind is None:
        diagnostics.append(
            _python_error(
                "PY_CLASS_FUNCTION_NEEDS_METHOD_KIND",
                "A class-owned function requires instance, class, or static method semantics",
                object_id=function.id,
                field="method_kind",
                diagram_id=diagram_id,
                repair="Select a method kind in the function signature panel.",
            )
        )
    expected_first = (
        "self"
        if function.method_kind is MethodKind.INSTANCE
        else "cls"
        if function.method_kind is MethodKind.CLASS
        else None
    )
    if expected_first is not None and (
        not function.parameters or function.parameters[0].name != expected_first
    ):
        assert function.method_kind is not None
        diagnostics.append(
            _python_error(
                "PY_METHOD_RECEIVER_MISSING",
                f"{function.method_kind.value.title()} method must start with {expected_first!r}",
                object_id=function.id,
                field="parameters",
                diagram_id=diagram_id,
                repair=f"Add {expected_first!r} as the first parameter.",
            )
        )

    signature_parts: list[str] = []
    last_positional_only = max(
        (
            index
            for index, item in enumerate(function.parameters)
            if item.kind is ParameterKind.POSITIONAL_ONLY
        ),
        default=-1,
    )
    has_var_positional = any(
        item.kind is ParameterKind.VAR_POSITIONAL for item in function.parameters
    )
    keyword_marker = False
    for index, parameter in enumerate(function.parameters):
        if (
            parameter.kind is ParameterKind.KEYWORD_ONLY
            and not has_var_positional
            and not keyword_marker
        ):
            signature_parts.append("*")
            keyword_marker = True
        prefix = (
            "*"
            if parameter.kind is ParameterKind.VAR_POSITIONAL
            else "**"
            if parameter.kind is ParameterKind.VAR_KEYWORD
            else ""
        )
        item_source = f"{prefix}{parameter.name}"
        if parameter.annotation is not None:
            item_source += f": {parameter.annotation.source}"
        if parameter.default is not None:
            item_source += f" = {parameter.default.source}"
        signature_parts.append(item_source)
        if index == last_positional_only:
            signature_parts.append("/")
    async_prefix = (
        "async " if function.kind in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR} else ""
    )
    _append_program_parse(
        diagnostics,
        f"{async_prefix}def {function.identifier}({', '.join(signature_parts)}):\n    pass",
        mode="exec",
        code="PY_INVALID_FUNCTION_SIGNATURE",
        label="Function signature",
        object_id=function.id,
        field="parameters",
        diagram_id=diagram_id,
    )
    diagnostics.extend(_validate_program_sequence(function, function.body, diagram_id))
    return diagnostics


def _validate_program_linked_calls(project: Project) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    model = project.program_model
    functions = {item.id: item for item in model.functions}
    views = {item.function_id: item.document_id for item in project.drakon_views}
    contexts: list[tuple[object, str | None, ProgramScope]] = [
        (function.body, views.get(function.id), function) for function in functions.values()
    ]

    def add_declaration_scope(owner: ProgramModule | ProgramClass | ProgramEntryPoint) -> None:
        body = owner.startup if isinstance(owner, ProgramEntryPoint) else owner.body
        contexts.append(
            (tuple(item for item in body if not isinstance(item, ProgramClass)), None, owner)
        )
        for item in body:
            if isinstance(item, ProgramClass):
                add_declaration_scope(item)

    for module in model.modules:
        add_declaration_scope(module)
    if model.entrypoint is not None:
        add_declaration_scope(model.entrypoint)
    for contents, diagram_id, scope in contexts:
        for statement in iter_program_nodes(contents):
            if not isinstance(statement, ProgramCall) or statement.target_function_id is None:
                continue
            target = functions.get(statement.target_function_id)
            if target is None:
                diagnostics.append(
                    _python_error(
                        "PY_UNRESOLVED_CALL",
                        "Linked Call target does not exist",
                        object_id=statement.id,
                        field="target_function_id",
                        diagram_id=diagram_id,
                        repair="Choose an existing canonical callable or unlink the Call.",
                    )
                )
                continue
            if target.method_kind is MethodKind.INSTANCE:
                diagnostics.append(
                    _python_error(
                        "PY_LINKED_INSTANCE_CALL_NEEDS_RECEIVER",
                        "A linked instance-method Call needs an explicit receiver expression",
                        object_id=statement.id,
                        field="target_function_id",
                        diagram_id=diagram_id,
                        repair=(
                            "Use an expression Call such as worker.run(...) "
                            "or link a static method."
                        ),
                    )
                )
            if statement.awaited and target.kind not in {
                CallableKind.ASYNC,
                CallableKind.ASYNC_GENERATOR,
            }:
                diagnostics.append(
                    _python_error(
                        "PY_AWAIT_NON_ASYNC_CALL",
                        f"Linked target {target.identifier!r} is not async",
                        object_id=statement.id,
                        field="awaited",
                        diagram_id=diagram_id,
                        repair="Turn off Await or change the target callable kind.",
                    )
                )
            if statement.awaited and target.kind is CallableKind.ASYNC_GENERATOR:
                diagnostics.append(
                    _python_error(
                        "PY_AWAIT_ASYNC_GENERATOR_CALL",
                        "An async-generator call must be iterated, not awaited",
                        object_id=statement.id,
                        field="awaited",
                        diagram_id=diagram_id,
                        repair="Use an async For loop over this callable.",
                    )
                )
            symbol = (model.class_name_for(target.id) or target.identifier).split(".")[0]
            package_module = ".".join(
                part for part in (model.package, model.module_path_for(target.id)) if part
            )
            imported = resolve_linked_callable(model, scope, target) is not None
            if not imported:
                diagnostics.append(
                    _python_error(
                        "PY_LINKED_CALL_IMPORT_MISSING",
                        f"Linked target {symbol!r} is in module "
                        f"{model.module_path_for(target.id)!r} "
                        "but is not imported",
                        object_id=statement.id,
                        field="target_function_id",
                        diagram_id=diagram_id,
                        repair=(f"Add 'from {package_module} import {symbol}' in Python Project."),
                    )
                )
    return diagnostics


def _validate_program_flow(
    function: ProgramFunction,
    diagram_id: str | None,
    model: ProgramModel,
    locations: Mapping[str, ProgramFunctionLocation],
    structure: DrakonDiagram | None = None,
) -> list[Diagnostic]:
    """Reuse structural flow rules on a value derived solely from the function.

    The checker needs textual Python and structural routes, never a saved view.
    Every diagnostic keeps the canonical statement identity even without a view.
    """
    if structure is None:
        view = DrakonViewDefinition(
            diagram_id or function.id,
            function.id,
            function.display_name,
            f"control-entry:{function.id}",
            f"control-exit:{function.id}",
        )
        structure = drakon_from_program(function, view, model=model, locations=locations)
    diagnostics, _timers = _validate_sequence(
        structure,
        structure.body,
        _FlowContext(function.kind),
    )
    return [replace(item, diagram_id=diagram_id) for item in diagnostics]


def _validate_declarations(body: tuple[ProgramDeclaration, ...]) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for declaration in body:
        if isinstance(declaration, ProgramFunctionReference):
            continue
        if isinstance(declaration, ProgramClass):
            if not declaration.identifier.isidentifier() or keyword.iskeyword(
                declaration.identifier
            ):
                diagnostics.append(
                    _python_error(
                        "PY_INVALID_CLASS_NAME",
                        "Class name must be a Python identifier",
                        object_id=declaration.id,
                        field="identifier",
                    )
                )
            diagnostics.extend(_validate_declarations(declaration.body))
            expressions = (
                *declaration.decorators,
                *((declaration.arguments,) if declaration.arguments else ()),
            )
        else:
            expressions = tuple(program_expressions(declaration))
        for expression in expressions:
            mode = expression_parse_mode(expression.role)
            # The canonical parser handles Python's specialized target, argument,
            # pattern, and name contexts. Complete module compilation is also a
            # generation gate, where lexical scope is available.
            if mode not in {"eval", "exec"}:
                continue
            diagnostic = _parse_field(
                expression.source,
                mode=mode,
                code="PY_INVALID_MODULE_SOURCE",
                label="Python declaration",
                object_id=declaration.id,
                field=expression.role.value,
                allow_empty=False,
            )
            if diagnostic:
                diagnostics.append(diagnostic)
        if isinstance(declaration, (ProgramImport, ProgramTypeAlias)):
            expected = (
                (ast.Import, ast.ImportFrom)
                if isinstance(declaration, ProgramImport)
                else (ast.TypeAlias,)
            )
            try:
                parsed = ast.parse(declaration.source.source)
            except (SyntaxError, ValueError):
                continue
            if len(parsed.body) != 1 or not isinstance(parsed.body[0], expected):
                diagnostics.append(
                    _python_error(
                        "PROGRAM_DECLARATION_KIND",
                        "A typed declaration must contain its declared Python construct",
                        object_id=declaration.id,
                        field="source",
                    )
                )
    return diagnostics


def _validate_module(module: ProgramModule) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if not _valid_dotted_name(module.path, allow_empty=module.kind is ProgramModuleKind.PACKAGE):
        diagnostics.append(
            _python_error(
                "PY_INVALID_MODULE_PATH",
                f"{module.path!r} is not a legal dotted module path",
                object_id=module.id,
                field="path",
                repair="Use dotted Python identifiers, for example algorithms.search.",
            )
        )
    diagnostics.extend(_validate_declarations(module.body))
    return diagnostics


def _atoms_in(sequence: Sequence) -> tuple[DrakonAtom, ...]:
    result: list[DrakonAtom] = []
    for atom in sequence.atoms:
        result.append(atom)
        for nested in nested_sequences(atom):
            result.extend(_atoms_in(nested))
    return tuple(result)


def _validate_program_completeness(project: Project) -> tuple[Diagnostic, ...]:
    views_by_function = {item.function_id: item for item in project.drakon_views}
    view_by_expression = {
        expression.id: views_by_function.get(function.id)
        for function in project.program_model.functions
        for expression in program_expressions(function)
    }
    diagnostics: list[Diagnostic] = []
    for expression in program_expressions(project.program_model):
        view = view_by_expression.get(expression.id)
        for node in _program_expression_nodes(expression):
            if isinstance(node, UnparsedPythonExpression):
                diagnostics.append(
                    Diagnostic(
                        "PROGRAM_INCOMPLETE_EXPRESSION",
                        Severity.ERROR,
                        f"Expression is incomplete: {node.reason}",
                        expression.id,
                        expression.role.value,
                        view.document_id if view is not None else None,
                        DiagnosticCategory.PYTHON,
                        "Complete or replace the expression before generating or executing.",
                    )
                )
    return tuple(diagnostics)


def validate_project(
    project: Project, *, extensions: DomainExtensionRegistry | None = None
) -> tuple[Diagnostic, ...]:
    # Bootstrap genuinely uninitialized in-memory projects once.  Existing
    # ProgramModel state is never overwritten from a projection.
    from code_visualizer.application.program_model import canonicalize_project

    return _validate_canonical_project(canonicalize_project(project), extensions=extensions)


def _validate_canonical_project(
    project: Project, *, extensions: DomainExtensionRegistry | None = None
) -> tuple[Diagnostic, ...]:
    """Validate one freshly derived snapshot without rebuilding its projections."""
    diagnostics = list(validate_integrity(project))
    diagnostics.extend(
        Diagnostic(item.code, Severity.ERROR, item.message, item.object_id, item.field)
        for item in validate_domain_workspace(project.domain_workspace)
        if item.incomplete
    )
    if (
        project.domain_workspace.schemas
        or project.domain_workspace.models
        or project.domain_workspace.bundle_references
        or project.domain_workspace.language_definitions
    ):
        from code_visualizer.extensions.registry import validate_extension_requirements

        diagnostics.extend(
            Diagnostic(item.code, Severity.ERROR, item.message, item.object_id, item.field)
            for item in validate_extension_requirements(project, extensions)
        )
    diagnostics.extend(_validate_program_completeness(project))
    setup = project.program_model
    if isinstance(setup.entrypoint_arguments, UnresolvedInvocationArguments):
        try:
            parse_invocation_arguments(setup.entrypoint_arguments.text)
            message = "Resolve the incomplete invocation argument setting"
        except ValueError as exc:
            message = str(exc)
        diagnostics.append(
            _python_error(
                "INVOCATION_LITERAL_ARGUMENTS",
                message,
                object_id=project.id,
                field="entrypoint_arguments",
                repair=(
                    "Enter literal values, or move namespace-dependent setup "
                    "into a top-level entrypoint."
                ),
            )
        )
    entrypoint = project.program_model.function(setup.entrypoint_callable_id or "")
    if entrypoint is not None and isinstance(setup.entrypoint_arguments, InvocationArguments):
        try:
            bind_invocation(project.program_model, entrypoint, setup.entrypoint_arguments)
        except InvocationBindingError as exc:
            diagnostics.append(
                _python_error(
                    exc.code,
                    str(exc),
                    object_id=entrypoint.id,
                    field=(
                        "entrypoint_arguments"
                        if exc.code == "INVOCATION_ARGUMENT_MISMATCH"
                        else "entrypoint_callable_id"
                    ),
                )
            )
    if not _valid_dotted_name(setup.package, allow_empty=True):
        diagnostics.append(
            _python_error(
                "PY_INVALID_PACKAGE_PATH",
                f"{setup.package!r} is not a legal dotted package path",
                object_id=project.id,
                field="package",
                repair="Use dotted Python identifiers or leave the package empty.",
            )
        )
    module_paths = [module.path for module in setup.modules]
    if not module_paths and setup.functions:
        diagnostics.append(
            _python_error(
                "PY_NO_MODULES",
                "The project has no configured Python modules",
                object_id=project.id,
                field="modules",
                repair="Add at least one module in Python Project.",
            )
        )
    for duplicate in sorted(_duplicate_ids(module_paths)):
        diagnostics.append(
            _python_error(
                "PY_DUPLICATE_MODULE",
                f"Module path {duplicate!r} is configured more than once",
                object_id=duplicate,
                field="path",
                repair="Give every configured module a unique dotted path.",
            )
        )
    valid_module_paths = tuple(
        module.path
        for module in setup.modules
        if _valid_dotted_name(module.path, allow_empty=module.kind is ProgramModuleKind.PACKAGE)
    )
    paths_by_case: dict[str, set[str]] = {}
    for module_path in valid_module_paths:
        paths_by_case.setdefault(module_path.casefold(), set()).add(module_path)
    for colliding in sorted(
        (paths for paths in paths_by_case.values() if len(paths) > 1),
        key=lambda paths: sorted(paths)[0],
    ):
        readable = ", ".join(repr(path) for path in sorted(colliding))
        diagnostics.append(
            _python_error(
                "PY_MODULE_PATH_CASE_COLLISION",
                f"Module paths {readable} collide on case-insensitive filesystems",
                object_id=sorted(colliding)[0],
                field="path",
                repair="Use module paths that differ by more than letter case.",
            )
        )
    for module_path in valid_module_paths:
        if "__init__" in module_path.split("."):
            diagnostics.append(
                _python_error(
                    "PY_RESERVED_MODULE_PATH",
                    f"Module path {module_path!r} names an initializer file rather than a module",
                    object_id=module_path,
                    field="path",
                    repair="Choose PACKAGE kind and its containing path for an initializer.",
                )
            )
        if not setup.package and module_path == "run_project":
            diagnostics.append(
                _python_error(
                    "PY_RESERVED_MODULE_PATH",
                    f"Root module {module_path!r} conflicts with a generated launcher",
                    object_id=module_path,
                    field="path",
                    repair="Use a package or rename the module.",
                )
            )
    normalized_paths = tuple((path, path.casefold()) for path in valid_module_paths)
    reported_prefixes: set[tuple[str, str]] = set()
    for module_path, folded in normalized_paths:
        module = next(item for item in setup.modules if item.path == module_path)
        if module.kind is ProgramModuleKind.PACKAGE:
            if not setup.package and not module_path:
                diagnostics.append(
                    _python_error(
                        "PY_INVALID_PACKAGE_PATH",
                        "A root initializer needs a nonempty package name",
                        object_id=module.id,
                        field="path",
                        repair="Set the project package or a nonempty package-module path.",
                    )
                )
            continue
        for other_path, other_folded in normalized_paths:
            if folded == other_folded or not other_folded.startswith(f"{folded}."):
                continue
            collision = (module_path, other_path)
            if collision in reported_prefixes:
                continue
            reported_prefixes.add(collision)
            diagnostics.append(
                _python_error(
                    "PY_MODULE_PACKAGE_COLLISION",
                    f"Module {module_path!r} is also the package prefix of {other_path!r}",
                    object_id=module_path,
                    field="path",
                    repair=(
                        f"Move {module_path!r} to a leaf such as {module_path}.core, or rename "
                        "the nested module."
                    ),
                )
            )
    model = project.program_model
    functions_by_scope: dict[tuple[str, str | None], list[str]] = {}
    locations = program_function_locations(model)
    for module in setup.modules:
        diagnostics.extend(_validate_module(module))
    views_by_function = {item.function_id: item for item in project.drakon_views}
    structures = {item.id: item for item in project.documents if isinstance(item, DrakonDiagram)}
    functions_by_document: dict[str, list[str]] = {}
    for view_binding in project.drakon_views:
        functions_by_document.setdefault(view_binding.document_id, []).append(
            view_binding.function_id
        )
    for function in project.program_model.functions:
        view = views_by_function.get(function.id)
        diagram_id = view.document_id if view is not None else None
        location = locations.get(function.id)
        diagnostics.extend(_validate_program_function(function, diagram_id, location))
        functions_by_scope.setdefault(
            (
                location.module.path if location is not None else "",
                location.class_name if location is not None else None,
            ),
            [],
        ).append(function.identifier)
        diagnostics.extend(
            _validate_program_flow(
                function,
                diagram_id,
                model,
                locations,
                structures.get(diagram_id or "")
                if functions_by_document.get(diagram_id or "") == [function.id]
                else None,
            )
        )
    for (module_path, owning_class), identifiers in functions_by_scope.items():
        for duplicate in sorted(_duplicate_ids(identifiers)):
            scope = (
                f"class {owning_class!r} in module {module_path!r}"
                if owning_class is not None
                else f"module {module_path!r}"
            )
            diagnostics.append(
                _python_error(
                    "PY_DUPLICATE_FUNCTION",
                    f"Function {duplicate!r} is duplicated in {scope}",
                    object_id=module_path,
                    field="functions",
                    repair="Rename one function; display names may still match.",
                )
            )
    diagnostics.extend(_validate_program_linked_calls(project))
    if model.entrypoint is not None:
        diagnostics.extend(_validate_declarations(model.entrypoint.startup))
    profile_names = [profile.name for profile in project.runtime_settings.run_profiles]
    for duplicate in sorted(_duplicate_ids(profile_names)):
        diagnostics.append(
            _python_error(
                "PY_DUPLICATE_RUN_PROFILE",
                f"Run profile {duplicate!r} is duplicated",
                object_id=project.id,
                field="run_profiles",
            )
        )
    if project.runtime_settings.active_run_profile not in set(profile_names):
        diagnostics.append(
            _python_error(
                "PY_UNRESOLVED_RUN_PROFILE",
                "Active run profile "
                f"{project.runtime_settings.active_run_profile!r} does not exist",
                object_id=project.id,
                field="active_run_profile",
                repair="Select an existing run profile.",
            )
        )
    return tuple(diagnostics)


def assess_project(
    project: Project,
    *,
    function_ids: frozenset[str] | None = None,
    extensions: DomainExtensionRegistry | None = None,
) -> ProjectAssessment:
    """Validate a project and state whether a requested build scope is executable.

    A focused live test/debug scope ignores findings attached to unrelated DRAKON
    documents. Project-wide and canonical-integrity findings remain blocking.
    """

    from code_visualizer.application.program_model import canonicalize_project

    project = canonicalize_project(project)
    diagnostics = _validate_canonical_project(project, extensions=extensions)
    if function_ids is not None:
        selected_diagram_ids = {
            item.document_id for item in project.drakon_views if item.function_id in function_ids
        }
        owned_ids_by_function: dict[str, set[str]] = {}
        for function in project.program_model.functions:
            expressions = _program_expressions(function)
            owned_ids_by_function[function.id] = {
                function.id,
                function.symbol_id,
                *_program_statement_ids(function.body),
                *(item.id for item in function.parameters),
                *(item.symbol_id for item in function.parameters),
                *(item.id for item in expressions),
                *(
                    node.id
                    for expression in expressions
                    for node in _program_expression_nodes(expression)
                ),
                *(
                    item.id
                    for item in project.program_model.symbols
                    if item.owner_id == function.id
                ),
            }
        all_function_owned_ids = {
            object_id for owned_ids in owned_ids_by_function.values() for object_id in owned_ids
        }
        selected_function_owned_ids = {
            object_id
            for function in project.program_model.functions
            if function.id in function_ids
            for object_id in owned_ids_by_function[function.id]
        }
        diagnostics = tuple(
            item
            for item in diagnostics
            if item.object_id in selected_function_owned_ids
            or (
                item.object_id not in all_function_owned_ids
                and (item.diagram_id is None or item.diagram_id in selected_diagram_ids)
            )
        )
    blocking = tuple(item for item in diagnostics if item.severity is Severity.ERROR)
    return ProjectAssessment(
        (BuildabilityStatus.BUILDABLE if not blocking else BuildabilityStatus.BLOCKED),
        diagnostics,
        blocking,
    )
