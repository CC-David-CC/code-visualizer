"""Build the revision-pinned semantic read model from canonical program truth.

The persisted :class:`ProgramModel` owns all executable constructs. DRAKON is
refreshed as an editor projection before indexing; mind-map and free-form documents
contribute views and annotations. Python expressions are parsed without execution.
"""

from __future__ import annotations

import ast
import builtins
import hashlib
from dataclasses import dataclass, fields, is_dataclass

from code_visualizer.application.domain_index import domain_semantic_contribution
from code_visualizer.application.live_views import (
    changed_live_document_ids,
    resolve_live_document,
    semantic_projection_source,
)
from code_visualizer.application.program_model import canonicalize_project
from code_visualizer.domain.drakon import (
    DrakonAtom,
    DrakonDiagram,
    Sequence,
    nested_sequences,
)
from code_visualizer.domain.expression import (
    AttributeExpression,
    CallExpression,
    CompositeExpression,
    ExpressionContext,
    ExpressionList,
    ExpressionNode,
    ExpressionScalar,
    LiteralExpression,
    SubscriptExpression,
    SymbolReferenceExpression,
    UnparsedPythonExpression,
    expression_children,
    expression_node_kind,
    expression_node_label,
    render_expression_tree,
)
from code_visualizer.domain.freeform import ConnectorObject, FreeformDiagram, ShapeObject
from code_visualizer.domain.mindmap import MindMapDiagram, walk_topics
from code_visualizer.domain.module_paths import PythonPathError, qualified_module_name
from code_visualizer.domain.program import (
    ProgramAssignment,
    ProgramCall,
    ProgramClass,
    ProgramDeclaration,
    ProgramExpression,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramIf,
    ProgramImport,
    ProgramLoop,
    ProgramModule,
    ProgramParallel,
    ProgramSelect,
    ProgramSequence,
    ProgramSilhouette,
    ProgramStatement,
    ProgramSymbol,
    ProgramSynchronizer,
    ProgramTransfer,
    ProgramTry,
    ProgramTypeAlias,
    ProgramWith,
    program_node_id,
)
from code_visualizer.domain.program_index import program_function_locations
from code_visualizer.domain.program_kinds import ProgramModuleKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import (
    SemanticObject,
    SemanticObjectKind,
    SemanticProgram,
    SemanticProperty,
    SemanticRelation,
    SemanticRelationKind,
    diff_semantic_program,
)
from code_visualizer.extensions.registry import DomainExtensionRegistry


@dataclass(frozen=True, slots=True)
class _CodeField:
    owner_id: str
    field: str
    source: str
    mode: str = "eval"


class _Builder:
    def __init__(
        self,
        project: Project,
        *,
        function_ids: frozenset[str] | None = None,
        document_ids: frozenset[str] | None = None,
        include_authoring: bool = True,
        extensions: DomainExtensionRegistry | None = None,
    ) -> None:
        self.project = project
        self.function_ids = function_ids
        self.document_ids = document_ids
        self.include_authoring = include_authoring
        self.extensions = extensions
        self.objects: dict[str, SemanticObject] = {}
        self.relations: dict[str, SemanticRelation] = {}
        self.function_by_identifier: dict[str, list[str]] = {}
        for function in project.program_model.functions:
            self.function_by_identifier.setdefault(function.identifier, []).append(function.id)
        self.document_by_object: dict[str, str] = {}
        self.parent_by_object: dict[str, str] = {}
        self._builtin_names = frozenset(dir(builtins))
        self._canonical_symbols = {
            (item.owner_id, item.name): item.id for item in project.program_model.symbols
        }
        self._symbols_by_owner: dict[str, list[ProgramSymbol]] = {}
        for symbol in project.program_model.symbols:
            self._symbols_by_owner.setdefault(symbol.owner_id, []).append(symbol)
        self._expression_sources: dict[int, str] = {}
        self._literal_sources: dict[tuple[ExpressionScalar, str | None], str] = {}

    def _render_expression(self, tree: ExpressionNode) -> str:
        """Render once for this immutable build's labels, details, and source fields."""

        key = id(tree)
        if key not in self._expression_sources:
            if isinstance(tree, LiteralExpression):
                literal_key = (tree.value, tree.literal_kind)
                if literal_key not in self._literal_sources:
                    self._literal_sources[literal_key] = render_expression_tree(tree)
                source = self._literal_sources[literal_key]
            else:
                source = render_expression_tree(tree)
            self._expression_sources[key] = source
            if isinstance(tree, CompositeExpression) and tree.python_kind == "Module":
                body = next((item.value for item in tree.fields if item.name == "body"), None)
                type_ignores = next(
                    (item.value for item in tree.fields if item.name == "type_ignores"), None
                )
                if (
                    isinstance(body, ExpressionList)
                    and len(body.items) == 1
                    and isinstance(body.items[0], CompositeExpression)
                    and body.items[0].python_kind != "Expr"
                    and (
                        type_ignores is None
                        or (isinstance(type_ignores, ExpressionList) and not type_ignores.items)
                    )
                ):
                    # With no docstring or type-ignore context, a single statement
                    # renders identically inside and outside its Module wrapper.
                    self._expression_sources.setdefault(id(body.items[0]), source)
        return self._expression_sources[key]

    def _expression_label(self, tree: ExpressionNode) -> str:
        if not isinstance(tree, (CompositeExpression, LiteralExpression)):
            return expression_node_label(tree)
        try:
            rendered = self._render_expression(tree)
        except ValueError:
            rendered = expression_node_kind(tree)
        return " ".join(rendered.split())[:240] or expression_node_kind(tree)

    def add_object(self, value: SemanticObject) -> None:
        existing = self.objects.get(value.id)
        if existing is None:
            self.objects[value.id] = value
            if value.document_id is not None:
                self.document_by_object[value.id] = value.document_id
            if value.parent_id is not None:
                self.parent_by_object[value.id] = value.parent_id
            return
        if existing.kind is not value.kind or existing.label != value.label:
            raise ValueError(f"Semantic identity collision for {value.id!r}")

    def add_relation(
        self,
        kind: SemanticRelationKind,
        source_id: str,
        target_id: str,
        *,
        label: str = "",
        owner_id: str | None = None,
        discriminator: str = "",
    ) -> None:
        raw = "\0".join((kind.value, source_id, target_id, label, owner_id or "", discriminator))
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        relation_id = f"relation:{kind.value}:{digest}"
        self.relations.setdefault(
            relation_id,
            SemanticRelation(
                relation_id,
                kind,
                source_id,
                target_id,
                label,
                owner_id,
            ),
        )

    def contains(self, parent_id: str, child_id: str, *, label: str = "") -> None:
        self.add_relation(
            SemanticRelationKind.CONTAINS,
            parent_id,
            child_id,
            label=label,
        )

    def build(self) -> SemanticProgram:
        self._index_architecture()
        self._index_program()
        if self.include_authoring:
            contribution = domain_semantic_contribution(self.project, self.extensions)
            for item in contribution.objects:
                if item.id in self.objects:
                    raise ValueError(f"Domain identity collides with program identity {item.id!r}")
                self.add_object(item)
            for relation in contribution.relations:
                if relation.id in self.relations:
                    raise ValueError(f"Domain relationship collision {relation.id!r}")
                self.relations[relation.id] = relation
        for document in self.project.documents:
            if isinstance(document, DrakonDiagram) and (
                self.document_ids is None or document.id in self.document_ids
            ):
                self._index_drakon_view(document)
        if self.include_authoring:
            self._index_authoring()
        core = SemanticProgram(
            self.project.id,
            self.project.revision,
            tuple(self.objects.values()),
            tuple(self.relations.values()),
        )
        for document in self.project.documents:
            if self.document_ids is not None and document.id not in self.document_ids:
                continue
            resolved = resolve_live_document(document, core)
            if isinstance(resolved, MindMapDiagram):
                self._index_mind_map(resolved)
            elif isinstance(resolved, FreeformDiagram):
                self._index_freeform(resolved)
        # A concept or authored relation may intentionally refer to a presentation
        # glyph. Re-run the idempotent overlay after those glyphs exist.
        if self.include_authoring:
            self._index_authoring()
        return SemanticProgram(
            self.project.id,
            self.project.revision,
            tuple(sorted(self.objects.values(), key=lambda item: (item.kind.value, item.id))),
            tuple(sorted(self.relations.values(), key=lambda item: item.id)),
        )

    def _index_authoring(self) -> None:
        """Overlay author intent without changing executable control semantics."""

        for concept in self.project.concepts:
            self.add_object(
                SemanticObject(
                    concept.id,
                    SemanticObjectKind.CONCEPT,
                    concept.title,
                    parent_id=self.project.id,
                    detail=concept.description,
                    properties=tuple(SemanticProperty("tag", tag) for tag in concept.tags),
                )
            )
            self.contains(self.project.id, concept.id, label="authored concept")
        available = set(self.objects)
        for concept in self.project.concepts:
            for index, member_id in enumerate(concept.member_ids):
                if member_id not in available:
                    continue
                self.add_relation(
                    SemanticRelationKind.CONCEPTUALLY_CONTAINS,
                    concept.id,
                    member_id,
                    label="conceptual member",
                    owner_id=concept.id,
                    discriminator=str(index),
                )
        for relation in self.project.semantic_relations:
            if relation.source_id not in available or relation.target_id not in available:
                continue
            if relation.id in self.relations:
                existing = self.relations[relation.id]
                if (
                    existing.kind is SemanticRelationKind.AUTHORED
                    and existing.source_id == relation.source_id
                    and existing.target_id == relation.target_id
                ):
                    continue
                raise ValueError(f"Semantic relationship identity collision for {relation.id!r}")
            self.relations[relation.id] = SemanticRelation(
                relation.id,
                SemanticRelationKind.AUTHORED,
                relation.source_id,
                relation.target_id,
                relation.label or relation.kind.value.replace("_", " "),
                relation.id,
            )

    def _index_architecture(self) -> None:
        project = self.project
        self._package_owners: dict[str, str] = {}
        for module in project.program_model.modules:
            if module.kind is ProgramModuleKind.PACKAGE:
                try:
                    name = qualified_module_name(
                        project.program_model.package, module.path, kind=module.kind
                    )
                except PythonPathError:
                    continue
                self._package_owners.setdefault(name, module.id)
        self.add_object(
            SemanticObject(
                project.id,
                SemanticObjectKind.PROJECT,
                project.title,
                detail=project.description,
            )
        )
        package = project.program_model.package
        root_namespace = self._ensure_namespace(package)
        self.contains(project.id, root_namespace)
        for module in project.program_model.modules:
            self._index_module(module)
        entrypoint = project.program_model.entrypoint
        if entrypoint is not None:
            self._add_operation(entrypoint.id, "Program entrypoint", project.id, None)
            self._index_declarations(entrypoint.startup, entrypoint.id)

    def _ensure_namespace(self, qualified: str) -> str:
        if qualified in self._package_owners:
            return self._package_owners[qualified]
        namespace_id = f"namespace:{qualified}"
        if namespace_id in self.objects:
            return namespace_id
        parent_id: str | None = None
        if "." in qualified:
            parent_id = self._ensure_namespace(qualified.rpartition(".")[0])
        self.add_object(
            SemanticObject(
                namespace_id,
                SemanticObjectKind.NAMESPACE,
                qualified.rsplit(".", maxsplit=1)[-1],
                parent_id=parent_id,
                detail=qualified,
            )
        )
        if parent_id is not None:
            self.contains(parent_id, namespace_id)
        return namespace_id

    def _index_module(self, module: ProgramModule) -> None:
        try:
            qualified = qualified_module_name(
                self.project.program_model.package, module.path, kind=module.kind
            )
        except PythonPathError:
            qualified = module.path or self.project.program_model.package or "(unnamed package)"
        namespace_name = qualified.rpartition(".")[0]
        namespace_id = (
            self.project.id
            if module.kind is ProgramModuleKind.PACKAGE and not module.path
            else self._ensure_namespace(namespace_name)
        )
        self.add_object(
            SemanticObject(
                module.id,
                SemanticObjectKind.MODULE,
                qualified.rsplit(".", maxsplit=1)[-1],
                parent_id=namespace_id,
                detail=qualified,
                properties=(
                    SemanticProperty("module", module.path),
                    SemanticProperty("module_kind", module.kind.value),
                ),
            )
        )
        self.contains(namespace_id, module.id)
        self._index_declarations(module.body, module.id)

    def _index_declarations(
        self, declarations: tuple[ProgramDeclaration, ...], owner_id: str
    ) -> None:
        for declaration in declarations:
            if isinstance(declaration, ProgramFunctionReference):
                continue
            if isinstance(declaration, ProgramClass):
                self.add_object(
                    SemanticObject(
                        declaration.id,
                        SemanticObjectKind.CLASS,
                        declaration.identifier,
                        parent_id=owner_id,
                        detail=declaration.docstring or "",
                    )
                )
                self.contains(owner_id, declaration.id)
                if declaration.arguments is not None:
                    self._index_program_expression(
                        declaration.arguments, declaration.id, owner_id, None
                    )
                for expression in declaration.decorators:
                    self._index_program_expression(expression, declaration.id, owner_id, None)
                self._index_type_parameters(declaration.type_parameters, declaration.id, None)
                self._index_declarations(declaration.body, declaration.id)
                continue
            if isinstance(declaration, (ProgramImport, ProgramTypeAlias)):
                label = "Import" if isinstance(declaration, ProgramImport) else "Type alias"
                self._add_operation(declaration.id, label, owner_id, None)
                self._index_program_expression(declaration.source, declaration.id, owner_id, None)
            else:
                self._index_program_statement(declaration, owner_id, owner_id, None)

    def _index_program(self) -> None:
        """Index executable truth without reading its DRAKON projection."""

        views = {item.function_id: item for item in self.project.drakon_views}
        locations = program_function_locations(self.project.program_model)
        # Register every callable before bodies so name-based calls resolve regardless
        # of declaration order or whether a function has a DRAKON view.
        for function in self.project.program_model.functions:
            location = locations.get(function.id)
            parent_id = location.owner.id if location is not None else self.project.id
            view = views.get(function.id)
            document_id = view.document_id if view is not None else None
            self.add_object(
                SemanticObject(
                    function.id,
                    SemanticObjectKind.FUNCTION,
                    function.identifier,
                    parent_id=parent_id,
                    document_id=document_id,
                    detail=function.display_name,
                    properties=(
                        SemanticProperty("callable_kind", function.kind.value),
                        SemanticProperty(
                            "module", location.module.path if location is not None else ""
                        ),
                    ),
                )
            )
            self.contains(parent_id, function.id)

        for function in self.project.program_model.functions:
            if self.function_ids is not None and function.id not in self.function_ids:
                continue
            view = views.get(function.id)
            document_id = view.document_id if view is not None else None
            self._index_function_symbols(function, document_id)
            for parameter in function.parameters:
                if parameter.annotation is not None:
                    self._index_program_expression(
                        parameter.annotation,
                        parameter.symbol_id,
                        function.id,
                        document_id,
                    )
                if parameter.default is not None:
                    self._index_program_expression(
                        parameter.default,
                        parameter.symbol_id,
                        function.id,
                        document_id,
                    )
            if function.return_annotation is not None:
                self._index_program_expression(
                    function.return_annotation,
                    function.id,
                    function.id,
                    document_id,
                )
            for decorator in function.decorators:
                self._index_program_expression(
                    decorator,
                    function.id,
                    function.id,
                    document_id,
                )
            self._index_type_parameters(function.type_parameters, function.id, document_id)
            entry_id = f"control-entry:{function.id}"
            exit_id = f"control-exit:{function.id}"
            self._add_operation(entry_id, "Entry", function.id, document_id)
            self._add_operation(exit_id, "Exit", function.id, document_id)
            self._index_program_sequence(
                function.body,
                function.id,
                function.id,
                document_id,
            )
            self._wire_sequence(
                function.body,
                entry_id,
                exit_id,
                function.id,
                entry_label="entry",
            )

    def _index_type_parameters(
        self, parameters: tuple[ExpressionNode, ...], owner_id: str, document_id: str | None
    ) -> None:
        for parameter in parameters:
            self.add_object(
                SemanticObject(
                    parameter.id,
                    SemanticObjectKind.EXPRESSION,
                    expression_node_kind(parameter),
                    parent_id=owner_id,
                    document_id=document_id,
                    field="type_parameter",
                    detail=self._expression_label(parameter),
                )
            )
            self.contains(owner_id, parameter.id)
            self._index_expression_node(
                parameter,
                parameter.id,
                parameter.id,
                owner_id,
                owner_id,
                document_id,
                "type_parameter",
                force_write=False,
            )

    def _index_function_symbols(
        self,
        function: ProgramFunction,
        document_id: str | None,
    ) -> None:
        del document_id
        for symbol in self._symbols_by_owner.get(function.id, ()):
            self._ensure_symbol(symbol.id, symbol.name, function.id, external=False)
            self.add_relation(
                SemanticRelationKind.DEFINES,
                function.id,
                symbol.id,
                label=symbol.kind.value,
            )

    def _index_program_sequence(
        self,
        sequence: ProgramSequence,
        scope_id: str,
        parent_id: str,
        document_id: str | None,
    ) -> None:
        self._add_structure_child(sequence.id, "Sequence", parent_id, document_id, "")
        for statement in sequence.statements:
            self._index_program_statement(statement, sequence.id, scope_id, document_id)

    def _index_program_statement(
        self,
        statement: ProgramStatement,
        parent_id: str,
        scope_id: str,
        document_id: str | None,
    ) -> None:
        label = type(statement).__name__.removeprefix("Program")
        label = label.replace("RealtimeProcess", "Realtime Process")
        detail = ""
        if isinstance(statement, ProgramAssignment):
            detail = (
                f"{self._render_expression(statement.target.tree)} {statement.operator} "
                f"{self._render_expression(statement.value.tree)}"
            )
        else:
            for name in (
                "source",
                "expression",
                "condition",
                "target",
                "call",
                "timer",
                "display_name",
                "text",
            ):
                value = getattr(statement, name, None)
                if isinstance(value, ProgramExpression):
                    detail = self._render_expression(value.tree)
                    break
                if isinstance(value, str) and value:
                    detail = value
                    break
        self._add_operation(statement.id, label, parent_id, document_id, detail=detail[:240])
        for field in fields(statement):
            self._index_program_child(
                getattr(statement, field.name),
                statement.id,
                scope_id,
                document_id,
            )
        if isinstance(statement, ProgramCall):
            self._index_program_call(scope_id, statement)
        if isinstance(statement, ProgramIf):
            for branch, name in (
                (statement.true_branch, "true"),
                (statement.false_branch, "false"),
            ):
                self.add_relation(
                    SemanticRelationKind.BRANCH,
                    statement.id,
                    branch.id,
                    label=name,
                    owner_id=scope_id,
                )
        if isinstance(statement, ProgramSilhouette):
            for state in statement.branches:
                if state.target_branch_id is not None:
                    self.add_relation(
                        SemanticRelationKind.TRANSITION,
                        state.id,
                        state.target_branch_id,
                        label="address",
                        owner_id=statement.id,
                    )

    def _index_program_child(
        self,
        value: object,
        parent_id: str,
        scope_id: str,
        document_id: str | None,
    ) -> None:
        if isinstance(value, ProgramExpression):
            self._index_program_expression(value, parent_id, scope_id, document_id)
        elif isinstance(value, ProgramSequence):
            self._index_program_sequence(value, scope_id, parent_id, document_id)
        elif isinstance(value, tuple):
            for item in value:
                self._index_program_child(item, parent_id, scope_id, document_id)
        elif is_dataclass(value) and not isinstance(value, type):
            object_id = program_node_id(value)
            kind = type(value).__name__.removeprefix("Program")
            label = getattr(value, "label", getattr(value, "name", kind))
            self._add_structure_child(
                object_id, label if isinstance(label, str) else kind, parent_id, document_id, kind
            )
            for field in fields(value):
                self._index_program_child(
                    getattr(value, field.name),
                    object_id,
                    scope_id,
                    document_id,
                )

    def _index_program_call(self, owner_id: str, statement: ProgramCall) -> None:
        target_id = statement.target_function_id
        if target_id is None:
            matches = self.function_by_identifier.get(
                self._render_expression(statement.expression.tree).strip(), []
            )
            target_id = matches[0] if len(matches) == 1 else None
        if target_id is None or self.project.program_model.function(target_id) is None:
            return
        self.add_relation(
            SemanticRelationKind.CALLS,
            owner_id,
            target_id,
            label=self._render_expression(statement.expression.tree),
            owner_id=statement.id,
        )

    def _index_program_expression(
        self,
        expression: ProgramExpression,
        owner_id: str,
        scope_id: str,
        document_id: str | None,
    ) -> None:
        source = self._render_expression(expression.tree).strip()
        incomplete = isinstance(expression.tree, UnparsedPythonExpression)
        self.add_object(
            SemanticObject(
                expression.id,
                SemanticObjectKind.EXPRESSION,
                expression.role.value,
                parent_id=owner_id,
                document_id=document_id,
                field=expression.role.value,
                detail=self._expression_label(expression.tree),
                properties=(
                    SemanticProperty("ast_kind", expression_node_kind(expression.tree)),
                    SemanticProperty("incomplete", str(incomplete).lower()),
                    SemanticProperty("source", source[:500]),
                ),
            )
        )
        self.add_relation(
            SemanticRelationKind.EVALUATES,
            owner_id,
            expression.id,
            label=expression.role.value,
        )
        self._index_expression_node(
            expression.tree,
            expression.id,
            expression.id,
            owner_id,
            scope_id,
            document_id,
            expression.role.value,
            force_write=False,
        )

    def _index_expression_node(
        self,
        node: ExpressionNode,
        semantic_node_id: str,
        expression_root_id: str,
        owner_id: str,
        scope_id: str,
        document_id: str | None,
        field: str,
        *,
        force_write: bool,
    ) -> None:
        if isinstance(node, CallExpression) and isinstance(node.callee, SymbolReferenceExpression):
            matches = self.function_by_identifier.get(node.callee.name, [])
            if len(matches) == 1:
                self.add_relation(
                    SemanticRelationKind.CALLS,
                    scope_id,
                    matches[0],
                    label=node.callee.name,
                    owner_id=owner_id,
                )
        if isinstance(node, SymbolReferenceExpression):
            external = node.symbol_id is None and node.name in self._builtin_names
            symbol_scope = "python" if external else scope_id
            symbol_id = node.symbol_id or self._symbol_id(symbol_scope, node.name)
            self._ensure_symbol(symbol_id, node.name, symbol_scope, external=external)
            writing = force_write or node.context in {
                ExpressionContext.STORE,
                ExpressionContext.DELETE,
            }
            access = SemanticRelationKind.WRITES if writing else SemanticRelationKind.READS
            self.add_relation(access, owner_id, symbol_id, label=field)
            self.add_relation(
                SemanticRelationKind.REFERENCES,
                semantic_node_id,
                symbol_id,
                label="write" if writing else "read",
                owner_id=expression_root_id,
            )
        write_value = force_write or (
            isinstance(node, (AttributeExpression, SubscriptExpression))
            and node.context in {ExpressionContext.STORE, ExpressionContext.DELETE}
        )
        for index, (child_field, child) in enumerate(expression_children(node)):
            child_id = child.id
            self.add_object(
                SemanticObject(
                    child_id,
                    SemanticObjectKind.EXPRESSION,
                    expression_node_kind(child),
                    parent_id=semantic_node_id,
                    document_id=document_id,
                    field=field,
                    detail=self._expression_label(child),
                    properties=(SemanticProperty("path", child_field),),
                )
            )
            self.add_relation(
                SemanticRelationKind.CONTAINS,
                semantic_node_id,
                child_id,
                label=child_field,
                discriminator=str(index),
            )
            self._index_expression_node(
                child,
                child_id,
                expression_root_id,
                owner_id,
                scope_id,
                document_id,
                field,
                force_write=write_value and child_field == "value",
            )

    def _index_drakon_view(self, diagram: DrakonDiagram) -> None:
        binding = next(
            (item for item in self.project.drakon_views if item.document_id == diagram.id),
            None,
        )
        if binding is None or self.project.program_model.function(binding.function_id) is None:
            return
        view_id = f"view:drakon:{diagram.id}"
        self.add_object(
            SemanticObject(
                view_id,
                SemanticObjectKind.VIEW,
                f"{diagram.title} · DRAKON",
                parent_id=self.project.id,
                document_id=diagram.id,
                detail="drakon",
                anchor_id=binding.function_id,
            )
        )
        self.add_relation(SemanticRelationKind.ANCHORS, view_id, binding.function_id)
        glyphs: list[tuple[str, str, str]] = [
            (diagram.header.id, "Function Header", f"control-entry:{binding.function_id}"),
            (diagram.end.id, "End", f"control-exit:{binding.function_id}"),
        ]
        glyphs.extend(
            (atom.id, type(atom).__name__.replace("RealtimeProcess", "Realtime Process"), atom.id)
            for atom in self._walk_atoms(diagram.body)
        )
        for object_id, label, anchor in glyphs:
            glyph_id = f"glyph:drakon:{object_id}"
            self.add_object(
                SemanticObject(
                    glyph_id,
                    SemanticObjectKind.GLYPH,
                    label,
                    parent_id=view_id,
                    document_id=diagram.id,
                    detail="drakon icon",
                    properties=(SemanticProperty("view_object_id", object_id),),
                    anchor_id=anchor,
                )
            )
            self.contains(view_id, glyph_id)
            self.add_relation(SemanticRelationKind.ANCHORS, glyph_id, anchor)

    def _add_operation(
        self,
        object_id: str,
        label: str,
        parent_id: str,
        document_id: str | None,
        *,
        detail: str = "",
    ) -> None:
        self.add_object(
            SemanticObject(
                object_id,
                SemanticObjectKind.OPERATION,
                label,
                parent_id=parent_id,
                document_id=document_id,
                detail=detail,
            )
        )
        self.contains(parent_id, object_id)

    def _add_structure_child(
        self,
        object_id: str,
        label: str,
        parent_id: str,
        document_id: str | None,
        detail: str,
    ) -> None:
        self.add_object(
            SemanticObject(
                object_id,
                SemanticObjectKind.STRUCTURE,
                label,
                parent_id=parent_id,
                document_id=document_id,
                detail=detail,
            )
        )
        self.contains(parent_id, object_id)

    def _wire_sequence(
        self,
        sequence: ProgramSequence,
        predecessor_id: str,
        successor_id: str,
        function_id: str,
        *,
        entry_label: str = "next",
    ) -> None:
        atoms = sequence.statements
        if not atoms:
            self.add_relation(
                SemanticRelationKind.CONTROL_FLOW,
                predecessor_id,
                successor_id,
                label=entry_label,
                owner_id=function_id,
                discriminator=sequence.id,
            )
            return
        self.add_relation(
            SemanticRelationKind.CONTROL_FLOW,
            predecessor_id,
            atoms[0].id,
            label=entry_label,
            owner_id=function_id,
            discriminator=sequence.id,
        )
        for index, atom in enumerate(atoms):
            successor = atoms[index + 1].id if index + 1 < len(atoms) else successor_id
            self._wire_atom(atom, successor, function_id)

    def _wire_atom(self, atom: ProgramStatement, successor_id: str, function_id: str) -> None:
        if isinstance(atom, ProgramIf):
            self._wire_sequence(
                atom.true_branch,
                atom.id,
                successor_id,
                function_id,
                entry_label="true",
            )
            self._wire_sequence(
                atom.false_branch,
                atom.id,
                successor_id,
                function_id,
                entry_label="false",
            )
            return
        if isinstance(atom, ProgramSelect):
            for case in atom.cases:
                self.add_relation(
                    SemanticRelationKind.BRANCH,
                    atom.id,
                    case.id,
                    label=case.label,
                    owner_id=function_id,
                )
                self._wire_sequence(
                    case.body,
                    case.id,
                    successor_id,
                    function_id,
                    entry_label="body",
                )
            return
        if isinstance(atom, ProgramLoop):
            self._wire_sequence(
                atom.body,
                atom.id,
                atom.id,
                function_id,
                entry_label="body",
            )
            self._wire_sequence(
                atom.else_body,
                atom.id,
                successor_id,
                function_id,
                entry_label="else/exit",
            )
            return
        if isinstance(atom, ProgramWith):
            self._wire_sequence(atom.body, atom.id, successor_id, function_id, entry_label="body")
            return
        if isinstance(atom, ProgramTry):
            self._wire_sequence(atom.body, atom.id, successor_id, function_id, entry_label="try")
            for handler in atom.handlers:
                self.add_relation(
                    SemanticRelationKind.BRANCH,
                    atom.id,
                    handler.id,
                    label="except",
                    owner_id=function_id,
                )
                self._wire_sequence(
                    handler.body,
                    handler.id,
                    successor_id,
                    function_id,
                    entry_label="handler",
                )
            self._wire_sequence(
                atom.else_body,
                atom.id,
                successor_id,
                function_id,
                entry_label="else",
            )
            self._wire_sequence(
                atom.finally_body,
                atom.id,
                successor_id,
                function_id,
                entry_label="finally",
            )
            return
        if isinstance(atom, ProgramSynchronizer):
            self._wire_sequence(
                atom.on_time,
                atom.id,
                successor_id,
                function_id,
                entry_label="on time",
            )
            self._wire_sequence(
                atom.on_timeout,
                atom.id,
                successor_id,
                function_id,
                entry_label="timeout",
            )
            return
        if isinstance(atom, ProgramParallel):
            for parallel_branch in atom.branches:
                self.add_relation(
                    SemanticRelationKind.BRANCH,
                    atom.id,
                    parallel_branch.id,
                    label=parallel_branch.name,
                    owner_id=function_id,
                )
                self._wire_sequence(
                    parallel_branch.body,
                    parallel_branch.id,
                    successor_id,
                    function_id,
                    entry_label="parallel",
                )
            return
        if isinstance(atom, ProgramSilhouette):
            for silhouette_branch in atom.branches:
                self.add_relation(
                    SemanticRelationKind.BRANCH,
                    atom.id,
                    silhouette_branch.id,
                    label=silhouette_branch.name,
                    owner_id=function_id,
                )
                self._wire_sequence(
                    silhouette_branch.body,
                    silhouette_branch.id,
                    successor_id,
                    function_id,
                    entry_label="state",
                )
            return
        if isinstance(atom, ProgramTransfer) and atom.transfer_kind.value in {"return", "raise"}:
            return
        self.add_relation(
            SemanticRelationKind.CONTROL_FLOW,
            atom.id,
            successor_id,
            label="next",
            owner_id=function_id,
        )

    def _index_mind_map(self, diagram: MindMapDiagram) -> None:
        view_id = f"view:mindmap:{diagram.id}"
        self.add_object(
            SemanticObject(
                view_id,
                SemanticObjectKind.VIEW,
                f"{diagram.title} · Mind map",
                parent_id=self.project.id,
                document_id=diagram.id,
                detail="mindmap",
            )
        )
        topics = {topic.id: topic for topic in walk_topics(diagram.root)}
        for topic in topics.values():
            object_id = f"glyph:mindmap:{diagram.id}:{topic.id}"
            anchor = topic.semantic_id
            kind = SemanticObjectKind.GLYPH if anchor is not None else SemanticObjectKind.ANNOTATION
            self.add_object(
                SemanticObject(
                    object_id,
                    kind,
                    topic.text,
                    parent_id=view_id,
                    document_id=diagram.id,
                    detail="mind-map topic",
                    properties=(SemanticProperty("view_object_id", topic.id),),
                    anchor_id=anchor,
                )
            )
            self.contains(view_id, object_id)
            if anchor is not None:
                self.add_relation(
                    SemanticRelationKind.ANCHORS,
                    object_id,
                    anchor,
                    label="semantic topic",
                )
        for topic in topics.values():
            source = f"glyph:mindmap:{diagram.id}:{topic.id}"
            for child in topic.children:
                target = f"glyph:mindmap:{diagram.id}:{child.id}"
                self.add_relation(SemanticRelationKind.CONTAINS, source, target, label="child")
        for link in diagram.cross_links:
            object_id = f"glyph:mindmap:{diagram.id}:{link.id}"
            anchor = link.semantic_relation_id
            self.add_object(
                SemanticObject(
                    object_id,
                    SemanticObjectKind.GLYPH
                    if anchor is not None
                    else SemanticObjectKind.ANNOTATION,
                    link.label or "Cross-link",
                    parent_id=view_id,
                    document_id=diagram.id,
                    detail="mind-map cross-link",
                    properties=(SemanticProperty("view_object_id", link.id),),
                    anchor_id=anchor,
                )
            )
            self.contains(view_id, object_id)
            if anchor is not None:
                self.add_relation(SemanticRelationKind.ANCHORS, object_id, anchor)
            self.add_relation(
                SemanticRelationKind.REFERENCES,
                f"glyph:mindmap:{diagram.id}:{link.source_topic_id}",
                f"glyph:mindmap:{diagram.id}:{link.target_topic_id}",
                label=link.label,
                owner_id=object_id,
            )

    def _index_freeform(self, diagram: FreeformDiagram) -> None:
        view_id = f"view:freeform:{diagram.id}"
        self.add_object(
            SemanticObject(
                view_id,
                SemanticObjectKind.VIEW,
                f"{diagram.title} · Freeform",
                parent_id=self.project.id,
                document_id=diagram.id,
                detail="freeform",
            )
        )
        for item in diagram.objects:
            object_id = f"glyph:freeform:{diagram.id}:{item.id}"
            if isinstance(item, ShapeObject):
                anchor = item.semantic_id
                kind = (
                    SemanticObjectKind.GLYPH
                    if anchor is not None
                    else SemanticObjectKind.ANNOTATION
                )
                label = item.text or item.shape.value.replace("_", " ").title()
                properties = (SemanticProperty("view_object_id", item.id),)
            else:
                anchor = item.semantic_relation_id
                kind = (
                    SemanticObjectKind.GLYPH
                    if anchor is not None
                    else SemanticObjectKind.ANNOTATION
                )
                label = item.label or "Connector"
                properties = (SemanticProperty("view_object_id", item.id),)
            self.add_object(
                SemanticObject(
                    object_id,
                    kind,
                    label,
                    parent_id=view_id,
                    document_id=diagram.id,
                    detail="freeform object",
                    properties=properties,
                    anchor_id=anchor,
                )
            )
            self.contains(view_id, object_id)
            if anchor is not None:
                self.add_relation(SemanticRelationKind.ANCHORS, object_id, anchor)
        for item in diagram.objects:
            if not isinstance(item, ConnectorObject):
                continue
            source = f"glyph:freeform:{diagram.id}:{item.source_id}"
            target = f"glyph:freeform:{diagram.id}:{item.target_id}"
            self.add_relation(
                SemanticRelationKind.REFERENCES,
                source,
                target,
                label=item.label,
                owner_id=f"glyph:freeform:{diagram.id}:{item.id}",
            )

    def _index_code(
        self,
        code: _CodeField,
        scope_id: str,
        document_id: str | None,
    ) -> None:
        source = code.source.strip()
        if not source:
            return
        root_id = f"expression:{code.owner_id}:{code.field}"
        try:
            if code.mode == "exec":
                root: ast.AST = ast.parse(source, mode="exec")
            elif code.mode == "target":
                statement = ast.parse(f"{source} = None", mode="exec").body[0]
                root = statement.targets[0] if isinstance(statement, ast.Assign) else statement
            else:
                root = ast.parse(source, mode="eval").body
            invalid = "false"
            detail = self._node_label(root)
        except (SyntaxError, ValueError) as exc:
            root = ast.Constant(value=source)
            invalid = "true"
            detail = f"Invalid Python: {exc.msg if isinstance(exc, SyntaxError) else exc}"
        self.add_object(
            SemanticObject(
                root_id,
                SemanticObjectKind.EXPRESSION,
                code.field,
                parent_id=code.owner_id,
                document_id=document_id,
                field=code.field,
                detail=detail,
                properties=(
                    SemanticProperty("ast_kind", type(root).__name__),
                    SemanticProperty("invalid", invalid),
                    SemanticProperty("source", source[:500]),
                ),
            )
        )
        self.add_relation(
            SemanticRelationKind.EVALUATES,
            code.owner_id,
            root_id,
            label=code.field,
        )
        written_names = self._written_names(root) if code.mode == "target" else set()
        self._index_ast_node(
            root,
            root_id,
            root_id,
            code,
            scope_id,
            document_id,
            written_names,
            "root",
        )

    def _index_ast_node(
        self,
        node: ast.AST,
        node_id: str,
        expression_root_id: str,
        code: _CodeField,
        scope_id: str,
        document_id: str | None,
        written_names: set[str],
        path: str,
    ) -> None:
        if isinstance(node, ast.Name):
            external = node.id in self._builtin_names
            symbol_scope = "python" if external else scope_id
            symbol_id = self._symbol_id(symbol_scope, node.id)
            self._ensure_symbol(symbol_id, node.id, symbol_scope, external=external)
            writing = isinstance(node.ctx, (ast.Store, ast.Del)) or node.id in written_names
            access = SemanticRelationKind.WRITES if writing else SemanticRelationKind.READS
            self.add_relation(access, code.owner_id, symbol_id, label=code.field)
            self.add_relation(
                SemanticRelationKind.REFERENCES,
                node_id,
                symbol_id,
                label="write" if writing else "read",
                owner_id=expression_root_id,
            )
        child_index = 0
        for field_name, value in ast.iter_fields(node):
            values = value if isinstance(value, list) else [value]
            for list_index, child in enumerate(values):
                if not isinstance(child, ast.AST) or isinstance(
                    child,
                    (ast.Load, ast.Store, ast.Del),
                ):
                    continue
                child_path = f"{path}.{field_name}"
                if isinstance(value, list):
                    child_path += f"[{list_index}]"
                digest = hashlib.sha256(child_path.encode("utf-8")).hexdigest()[:12]
                child_id = f"{expression_root_id}:node:{digest}"
                self.add_object(
                    SemanticObject(
                        child_id,
                        SemanticObjectKind.EXPRESSION,
                        type(child).__name__,
                        parent_id=node_id,
                        document_id=document_id,
                        field=code.field,
                        detail=self._node_label(child),
                        properties=(SemanticProperty("path", child_path),),
                    )
                )
                self.add_relation(
                    SemanticRelationKind.CONTAINS,
                    node_id,
                    child_id,
                    label=field_name,
                    discriminator=str(child_index),
                )
                self._index_ast_node(
                    child,
                    child_id,
                    expression_root_id,
                    code,
                    scope_id,
                    document_id,
                    written_names,
                    child_path,
                )
                child_index += 1

    def _ensure_symbol(
        self,
        symbol_id: str,
        name: str,
        scope_id: str,
        *,
        external: bool,
    ) -> None:
        self.add_object(
            SemanticObject(
                symbol_id,
                SemanticObjectKind.SYMBOL,
                name,
                parent_id=scope_id if scope_id in self.objects else None,
                detail="Python built-in" if external else "project symbol",
                properties=(SemanticProperty("external", str(external).lower()),),
            )
        )

    def _symbol_id(self, scope_id: str, name: str) -> str:
        return self._canonical_symbols.get((scope_id, name), f"symbol:{scope_id}:{name}")

    @staticmethod
    def _written_names(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, (ast.Tuple, ast.List)):
            result: set[str] = set()
            for item in node.elts:
                result.update(_Builder._written_names(item))
            return result
        if isinstance(node, ast.Starred):
            return _Builder._written_names(node.value)
        if isinstance(node, (ast.Attribute, ast.Subscript)):
            current: ast.AST = node.value
            while isinstance(current, (ast.Attribute, ast.Subscript)):
                current = current.value
            return {current.id} if isinstance(current, ast.Name) else set()
        return set()

    @staticmethod
    def _node_label(node: ast.AST) -> str:
        try:
            label = ast.unparse(node)
        except (AttributeError, ValueError):
            label = type(node).__name__
        label = " ".join(label.split())
        return label[:160] or type(node).__name__

    @staticmethod
    def _called_identifier(source: str) -> str | None:
        try:
            value = ast.parse(source, mode="eval").body
        except SyntaxError:
            return None
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            return value.func.id
        return None

    @staticmethod
    def _walk_atoms(sequence: Sequence) -> tuple[DrakonAtom, ...]:
        result: list[DrakonAtom] = []
        for atom in sequence.atoms:
            result.append(atom)
            for child in nested_sequences(atom):
                result.extend(_Builder._walk_atoms(child))
        return tuple(result)


def build_semantic_program(
    project: Project,
    extensions: DomainExtensionRegistry | None = None,
) -> SemanticProgram:
    """Return one deterministic semantic read model pinned to ``project.revision``."""

    diagram_ids = {item.id for item in project.documents if isinstance(item, DrakonDiagram)}
    mapped_ids = {item.document_id for item in project.drakon_views}
    function_ids = {item.id for item in project.program_model.functions}
    bindings_are_current = all(item.function_id in function_ids for item in project.drakon_views)
    canonical = (
        project
        if function_ids and diagram_ids <= mapped_ids and bindings_are_current
        else canonicalize_project(project)
    )
    return _Builder(canonical, extensions=extensions).build()


@dataclass(frozen=True, slots=True)
class SemanticIndexUpdate:
    """One incremental read-model result and its invalidation scope."""

    program: SemanticProgram
    reindexed_function_ids: frozenset[str]
    reindexed_document_ids: frozenset[str]
    used_full_rebuild: bool = False


def _semantic_descendants(
    program: SemanticProgram,
    roots: frozenset[str],
    document_ids: frozenset[str],
) -> set[str]:
    selected = {
        item.id for item in program.objects if item.id in roots or item.document_id in document_ids
    }
    changed = True
    while changed:
        changed = False
        for item in program.objects:
            if item.id in selected or item.parent_id not in selected:
                continue
            selected.add(item.id)
            changed = True
    return selected


def _full_index_update(
    project: Project,
    extensions: DomainExtensionRegistry | None = None,
) -> SemanticIndexUpdate:
    return SemanticIndexUpdate(
        build_semantic_program(project, extensions),
        frozenset(item.id for item in project.program_model.functions),
        frozenset(item.id for item in project.documents),
        True,
    )


def _replace_live_document_segments(
    project: Project,
    program: SemanticProgram,
    document_ids: frozenset[str],
) -> SemanticProgram:
    """Reconcile changed live presentation segments over an updated semantic core."""

    if not document_ids:
        return program
    old_dirty = _semantic_descendants(program, frozenset(), document_ids)
    objects = {item.id: item for item in program.objects if item.id not in old_dirty}
    relations = {
        item.id: item
        for item in program.relations
        if item.source_id not in old_dirty
        and item.target_id not in old_dirty
        and item.owner_id not in old_dirty
    }
    source = SemanticProgram(
        project.id,
        project.revision,
        tuple(objects.values()),
        tuple(relations.values()),
    )
    builder = _Builder(
        project,
        function_ids=frozenset(),
        document_ids=frozenset(),
        include_authoring=False,
    )
    builder.objects.update(objects)
    builder.relations.update(relations)
    builder.document_by_object.update(
        (item.id, item.document_id) for item in objects.values() if item.document_id is not None
    )
    builder.parent_by_object.update(
        (item.id, item.parent_id) for item in objects.values() if item.parent_id is not None
    )
    for document in project.documents:
        if document.id not in document_ids:
            continue
        resolved = resolve_live_document(document, source)
        if isinstance(resolved, MindMapDiagram):
            builder._index_mind_map(resolved)
        elif isinstance(resolved, FreeformDiagram):
            builder._index_freeform(resolved)
    # Authored concept membership may deliberately target a generated glyph.
    # Reapply that overlay after the new glyph identities are known.
    builder._index_authoring()
    return SemanticProgram(
        project.id,
        project.revision,
        tuple(sorted(builder.objects.values(), key=lambda item: (item.kind.value, item.id))),
        tuple(sorted(builder.relations.values(), key=lambda item: item.id)),
    )


def update_semantic_program(
    previous_project: Project,
    previous_program: SemanticProgram,
    project: Project,
    *,
    verify_with_full_rebuild: bool = False,
    extensions: DomainExtensionRegistry | None = None,
) -> SemanticIndexUpdate:
    """Incrementally replace changed function segments of a semantic read model.

    The deliberately narrow fast path covers stable project/module structure and
    edits inside existing canonical functions and their DRAKON views. Structural
    project changes fall back to the retained full builder. Tests may enable the
    oracle check to compare the incremental result byte-for-byte with a full build.
    """

    previous = canonicalize_project(previous_project)
    current = canonicalize_project(project)
    if current.domain_workspace.models:
        if extensions is None:
            from code_visualizer.extensions.builtin import builtin_registry

            extensions = builtin_registry()
        if any(bundle.semantic_indexers for bundle in extensions.bundles()):
            # Contributors can inspect the whole immutable snapshot. Until one
            # declares a narrower dependency contract, retain a full-build oracle.
            return _full_index_update(current, extensions)
    previous_functions = {item.id: item for item in previous.program_model.functions}
    current_functions = {item.id: item for item in current.program_model.functions}
    previous_documents = {item.id: item for item in previous.documents}
    current_documents = {item.id: item for item in current.documents}
    stable_global_state = (
        previous.id == current.id
        and previous.title == current.title
        and previous.description == current.description
        and previous.runtime_settings == current.runtime_settings
        and previous.program_model.modules == current.program_model.modules
        and previous.program_model.package == current.program_model.package
        and previous.program_model.entrypoint == current.program_model.entrypoint
        and previous.concepts == current.concepts
        and previous.semantic_relations == current.semantic_relations
        and previous.domain_workspace == current.domain_workspace
        and previous.drakon_views == current.drakon_views
        and previous_functions.keys() == current_functions.keys()
        and previous_documents.keys() == current_documents.keys()
    )
    if not stable_global_state:
        return _full_index_update(current, extensions)

    changed_function_ids = {
        function_id
        for function_id, function in current_functions.items()
        if previous_functions[function_id] != function
    }
    previous_symbols = {item.id: item for item in previous.program_model.symbols}
    current_symbols = {item.id: item for item in current.program_model.symbols}
    for symbol_id in previous_symbols.keys() | current_symbols.keys():
        before = previous_symbols.get(symbol_id)
        after = current_symbols.get(symbol_id)
        if before == after:
            continue
        owner_id = after.owner_id if after is not None else before.owner_id if before else None
        if owner_id is not None:
            if owner_id not in current_functions or owner_id not in previous_functions:
                return _full_index_update(current, extensions)
            changed_function_ids.add(owner_id)

    if any(
        previous_functions[item].identifier != current_functions[item].identifier
        for item in changed_function_ids
    ):
        # Name-based calls can resolve from any function, so callable rename is a
        # project-wide function-body invalidation even though architecture is stable.
        changed_function_ids = set(current_functions)

    changed_document_ids = {
        document_id
        for document_id, document in current_documents.items()
        if previous_documents[document_id] != document
    }
    if any(not isinstance(current_documents[item], DrakonDiagram) for item in changed_document_ids):
        return _full_index_update(current, extensions)
    views_by_function = {item.function_id: item.document_id for item in current.drakon_views}
    for function_id in changed_function_ids:
        document_id = views_by_function.get(function_id)
        if document_id is not None:
            changed_document_ids.add(document_id)
    functions_by_document = {item.document_id: item.function_id for item in current.drakon_views}
    for document_id in changed_document_ids:
        bound_function_id = functions_by_document.get(document_id)
        if bound_function_id is not None:
            changed_function_ids.add(bound_function_id)

    function_scope = frozenset(changed_function_ids)
    document_scope = frozenset(changed_document_ids)
    if not function_scope and not document_scope:
        result = SemanticIndexUpdate(
            SemanticProgram(
                current.id,
                current.revision,
                previous_program.objects,
                previous_program.relations,
            ),
            function_scope,
            document_scope,
        )
    else:
        fragment = _Builder(
            current,
            function_ids=function_scope,
            document_ids=document_scope,
            include_authoring=False,
        ).build()
        old_dirty = _semantic_descendants(previous_program, function_scope, document_scope)
        new_dirty = _semantic_descendants(fragment, function_scope, document_scope)
        objects = {item.id: item for item in previous_program.objects if item.id not in old_dirty}
        objects.update((item.id, item) for item in fragment.objects if item.id in new_dirty)
        removed_ids = old_dirty - new_dirty

        def old_relation_is_dirty(item: SemanticRelation) -> bool:
            return (
                item.source_id in old_dirty
                or item.owner_id in function_scope
                or (item.kind is SemanticRelationKind.CONTAINS and item.target_id in old_dirty)
                or item.source_id in removed_ids
                or item.target_id in removed_ids
            )

        relations = {
            item.id: item for item in previous_program.relations if not old_relation_is_dirty(item)
        }
        relations.update(
            (
                item.id,
                item,
            )
            for item in fragment.relations
            if item.source_id in new_dirty
            or item.owner_id in function_scope
            or (item.kind is SemanticRelationKind.CONTAINS and item.target_id in new_dirty)
        )
        result = SemanticIndexUpdate(
            SemanticProgram(
                current.id,
                current.revision,
                tuple(sorted(objects.values(), key=lambda item: (item.kind.value, item.id))),
                tuple(sorted(relations.values(), key=lambda item: item.id)),
            ),
            function_scope,
            document_scope,
        )

    core_before = semantic_projection_source(previous_program)
    core_after = semantic_projection_source(result.program)
    core_delta = diff_semantic_program(core_before, core_after)
    live_document_scope = changed_live_document_ids(
        current.documents,
        core_before,
        core_after,
        core_delta,
    )
    if live_document_scope:
        result = SemanticIndexUpdate(
            _replace_live_document_segments(current, result.program, live_document_scope),
            result.reindexed_function_ids,
            result.reindexed_document_ids | live_document_scope,
        )

    if verify_with_full_rebuild:
        oracle = build_semantic_program(current, extensions)
        if result.program != oracle:
            raise AssertionError("Incremental semantic index diverged from full rebuild oracle")
    return result
