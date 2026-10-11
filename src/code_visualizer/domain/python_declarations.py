"""Python text admission into ordered canonical module/class declaration bodies.

This parser is an authoring/import boundary. Valid source is replaced by typed
trees. Incomplete source remains an explicit UnparsedPythonExpression, never a
second source field alongside a parsed tree. The runtime does not call this parser.
"""

from __future__ import annotations

import ast
import hashlib
import io
import tokenize
from uuid import uuid4

from code_visualizer.domain.expression import UnparsedPythonExpression, expression_tree_from_ast
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAction,
    ProgramAssignment,
    ProgramClass,
    ProgramDeclaration,
    ProgramExpression,
    ProgramImport,
    ProgramNote,
    ProgramTypeAlias,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import NotePlacement


def parse_python_declarations(
    owner_id: str,
    source: str,
    *,
    identity_namespace: str | None = None,
) -> tuple[ProgramDeclaration, ...]:
    """Parse one intentionally submitted body; preserve execution order and comments.

    Imported helper functions retain complete typed Python ASTs inside actions.
    Functions authored through the structured programming editor use the mature
    function table and owning ProgramFunctionReference declarations instead.
    Neither representation refers back to a source snippet for executable meaning.
    """
    seed = identity_namespace or uuid4().hex
    fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()

    def identity(role: str) -> str:
        digest = hashlib.sha256(f"{owner_id}\0{seed}\0{role}".encode()).hexdigest()[:24]
        return f"python_{digest}"

    def expression(identity_: str, role: ExpressionRole, value: ast.AST) -> ProgramExpression:
        expression_id = f"expression:{identity_}:{role.value}"
        return ProgramExpression(
            expression_id,
            role,
            expression_tree_from_ast(
                expression_id, value, identity_namespace=f"{seed}:{fingerprint}"
            ),
        )

    def incomplete(reason: str) -> tuple[ProgramDeclaration, ...]:
        if not source.strip():
            return ()
        node_id = identity("incomplete")
        return (
            ProgramAction(
                node_id,
                ProgramExpression(
                    f"expression:{node_id}:source",
                    ExpressionRole.STATEMENTS,
                    UnparsedPythonExpression(identity("incomplete:tree"), source, reason),
                ),
            ),
        )

    try:
        parsed = ast.parse(source, mode="exec", type_comments=True)
    except (SyntaxError, ValueError) as exc:
        # Keep the rejection from this type-comment-aware parser. Reparsing with
        # a more permissive parser would silently discard invalid typing syntax.
        return incomplete(str(exc))

    if parsed.type_ignores:
        # TypeIgnore targets source lines, including import/class headers and
        # multiline expressions. AST unparse cannot preserve those bindings.
        # Retain one explicit unsupported value until typed directive anchors
        # exist; moving a directive into a standalone note changes its meaning.
        return incomplete(
            "Python type: ignore directive anchors are not yet supported; original source retained"
        )

    comments = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            text = token.string.removeprefix("#").lstrip()
            if text.startswith("type:") and not text.removeprefix("type:").lstrip().startswith(
                "ignore"
            ):
                # The Python AST owns assignment/argument/function type comments.
                # A second standalone note changes their interpretation.
                continue
            comments.append((token.start[0], text))
    used_comments: set[int] = set()

    def body(
        statements: list[ast.stmt], path: str, first_line: int, last_line: int
    ) -> tuple[ProgramDeclaration, ...]:
        result: list[ProgramDeclaration] = []

        def notes_before(line: int) -> None:
            for index, (comment_line, text) in enumerate(comments):
                if (
                    first_line <= comment_line <= min(line, last_line)
                    and index not in used_comments
                ):
                    result.append(
                        ProgramNote(identity(f"comment:{index}"), text, NotePlacement.RICH)
                    )
                    used_comments.add(index)

        for index, statement in enumerate(statements):
            statement_path = f"{path}:{index}"
            node_id = identity(statement_path)
            notes_before(statement.lineno)
            suite = ast.Module(body=[statement], type_ignores=[])
            if isinstance(statement, ast.ClassDef):
                class_statements = statement.body
                docstring = ast.get_docstring(statement, clean=False)
                if docstring is not None:
                    class_statements = class_statements[1:]
                arguments = ", ".join(
                    [ast.unparse(item) for item in statement.bases]
                    + [
                        (f"{item.arg}=" if item.arg is not None else "**") + ast.unparse(item.value)
                        for item in statement.keywords
                    ]
                )
                result.append(
                    ProgramClass(
                        node_id,
                        statement.name,
                        body(
                            class_statements,
                            statement_path,
                            statement.lineno + 1,
                            statement.end_lineno or statement.lineno,
                        ),
                        make_program_expression(
                            node_id,
                            "arguments",
                            arguments,
                            ExpressionRole.ARGUMENTS,
                            identity_namespace=f"{seed}:{fingerprint}",
                        )
                        if arguments
                        else None,
                        tuple(
                            expression(f"{node_id}:decorator:{i}", ExpressionRole.DECORATOR, item)
                            for i, item in enumerate(statement.decorator_list)
                        ),
                        docstring,
                        tuple(
                            expression_tree_from_ast(
                                f"{node_id}:type_parameter:{i}",
                                item,
                                identity_namespace=f"{seed}:{fingerprint}",
                            )
                            for i, item in enumerate(statement.type_params)
                        ),
                    )
                )
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                result.append(
                    ProgramImport(node_id, expression(node_id, ExpressionRole.STATEMENTS, suite))
                )
            elif isinstance(statement, ast.TypeAlias):
                result.append(
                    ProgramTypeAlias(node_id, expression(node_id, ExpressionRole.STATEMENTS, suite))
                )
            elif isinstance(statement, ast.Assign) and statement.type_comment is None:
                target = " = ".join(ast.unparse(item) for item in statement.targets)
                result.append(
                    ProgramAssignment(
                        node_id,
                        make_program_expression(
                            node_id,
                            "target",
                            target,
                            ExpressionRole.TARGET,
                            identity_namespace=f"{seed}:{fingerprint}",
                        ),
                        expression(node_id, ExpressionRole.VALUE, statement.value),
                    )
                )
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                result.append(
                    ProgramAssignment(
                        node_id,
                        expression(node_id, ExpressionRole.TARGET, statement.target),
                        expression(node_id, ExpressionRole.VALUE, statement.value),
                        expression(node_id, ExpressionRole.ANNOTATION, statement.annotation),
                    )
                )
            else:
                result.append(
                    ProgramAction(node_id, expression(node_id, ExpressionRole.STATEMENTS, suite))
                )
        notes_before(last_line)
        return tuple(result)

    return body(parsed.body, "body", 1, len(source.splitlines()) + 1)
