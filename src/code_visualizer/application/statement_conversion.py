"""Conservative conversion of one raw Python statement into a typed DRAKON atom."""

from __future__ import annotations

import ast

from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    DrakonAtom,
    Input,
    Output,
    SimpleStatement,
    Transfer,
)
from code_visualizer.domain.program_kinds import SimpleKind, TransferKind


class StatementConversionError(ValueError):
    pass


_AUGMENTED_OPERATORS: dict[type[ast.operator], str] = {
    ast.Add: "+=",
    ast.Sub: "-=",
    ast.Mult: "*=",
    ast.MatMult: "@=",
    ast.Div: "/=",
    ast.FloorDiv: "//=",
    ast.Mod: "%=",
    ast.Pow: "**=",
    ast.LShift: "<<=",
    ast.RShift: ">>=",
    ast.BitOr: "|=",
    ast.BitXor: "^=",
    ast.BitAnd: "&=",
}


def _source(atom: DrakonAtom) -> str:
    if isinstance(atom, Action):
        return atom.source
    if isinstance(atom, SimpleStatement) and atom.statement_kind is SimpleKind.EXPRESSION:
        return atom.source
    raise StatementConversionError(
        "Select an Action or Expression icon containing exactly one Python statement"
    )


def _unparse(value: ast.AST | None) -> str:
    return "" if value is None else ast.unparse(value)


def _input_call(value: ast.expr) -> tuple[str, str] | None:
    converter = ""
    call = value
    if (
        isinstance(call, ast.Call)
        and len(call.args) == 1
        and not call.keywords
        and isinstance(call.args[0], ast.Call)
    ):
        converter = _unparse(call.func)
        call = call.args[0]
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "input"
        and len(call.args) <= 1
        and not call.keywords
    ):
        return None
    prompt = _unparse(call.args[0]) if call.args else '""'
    return prompt, converter


def _assignment(atom_id: str, node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> DrakonAtom:
    if isinstance(node, ast.AugAssign):
        operator = _AUGMENTED_OPERATORS.get(type(node.op))
        if operator is None:
            raise StatementConversionError("This augmented-assignment operator is unsupported")
        return Assignment(atom_id, _unparse(node.target), _unparse(node.value), operator=operator)
    if isinstance(node, ast.AnnAssign):
        target = _unparse(node.target)
        annotation = _unparse(node.annotation)
        value = node.value
    else:
        target = " = ".join(_unparse(item) for item in node.targets)
        annotation = None
        value = node.value
    if value is None:
        return Assignment(atom_id, target, "None", annotation=annotation)
    input_parts = _input_call(value)
    if input_parts is not None:
        prompt, converter = input_parts
        return Input(atom_id, target, prompt, converter or None, annotation)
    if isinstance(value, ast.Call):
        return Call(atom_id, _unparse(value), result_target=target)
    return Assignment(atom_id, target, _unparse(value), annotation=annotation)


def _expression(atom_id: str, node: ast.Expr) -> DrakonAtom:
    value = node.value
    if isinstance(value, ast.Yield):
        return Transfer(atom_id, TransferKind.YIELD, _unparse(value.value))
    if isinstance(value, ast.YieldFrom):
        return Transfer(atom_id, TransferKind.YIELD_FROM, _unparse(value.value))
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name) and value.func.id == "print":
            supported = all(keyword.arg in {"file", "end"} for keyword in value.keywords)
            if len(value.args) == 1 and supported:
                options = {keyword.arg: _unparse(keyword.value) for keyword in value.keywords}
                return Output(
                    atom_id,
                    _unparse(value.args[0]),
                    options.get("file"),
                    options.get("end"),
                )
        return Call(atom_id, _unparse(value))
    return SimpleStatement(atom_id, SimpleKind.EXPRESSION, _unparse(value))


def convert_simple_statement(atom: DrakonAtom) -> DrakonAtom:
    """Convert exactly one non-compound statement while preserving the stable atom ID."""

    source = _source(atom)
    try:
        module = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        raise StatementConversionError(f"Python cannot parse this statement: {exc.msg}") from exc
    if len(module.body) != 1:
        raise StatementConversionError("Conversion requires exactly one Python statement")
    node = module.body[0]
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        return _assignment(atom.id, node)
    if isinstance(node, ast.Expr):
        return _expression(atom.id, node)
    if isinstance(node, ast.Return):
        return Transfer(atom.id, TransferKind.RETURN, _unparse(node.value))
    if isinstance(node, ast.Raise):
        return Transfer(
            atom.id,
            TransferKind.RAISE,
            _unparse(node.exc),
            _unparse(node.cause) or None,
        )
    if isinstance(node, ast.Break):
        return Transfer(atom.id, TransferKind.BREAK, "")
    if isinstance(node, ast.Continue):
        return Transfer(atom.id, TransferKind.CONTINUE, "")
    if isinstance(node, ast.Pass):
        return SimpleStatement(atom.id, SimpleKind.PASS, "pass")
    if isinstance(node, ast.Delete):
        return SimpleStatement(
            atom.id,
            SimpleKind.DELETE,
            ", ".join(_unparse(target) for target in node.targets),
        )
    if isinstance(node, ast.Global):
        return SimpleStatement(atom.id, SimpleKind.GLOBAL, ", ".join(node.names))
    if isinstance(node, ast.Nonlocal):
        return SimpleStatement(atom.id, SimpleKind.NONLOCAL, ", ".join(node.names))
    if isinstance(node, ast.Assert):
        return SimpleStatement(
            atom.id,
            SimpleKind.ASSERT,
            _unparse(node.test),
            _unparse(node.msg) or None,
        )
    raise StatementConversionError(
        f"{type(node).__name__} is compound or has a dedicated structural insertion command"
    )
