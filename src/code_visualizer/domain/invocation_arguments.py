"""Immutable literal values for namespace-independent invocation configuration."""

from __future__ import annotations

import ast
import keyword
import math
from dataclasses import dataclass
from typing import cast


@dataclass(frozen=True, slots=True)
class ArgumentList:
    items: tuple[ArgumentValue, ...] = ()


@dataclass(frozen=True, slots=True)
class ArgumentTuple:
    items: tuple[ArgumentValue, ...] = ()


@dataclass(frozen=True, slots=True)
class ArgumentEntry:
    key: str
    value: ArgumentValue


@dataclass(frozen=True, slots=True)
class ArgumentDictionary:
    entries: tuple[ArgumentEntry, ...] = ()


type ArgumentValue = (
    str | int | float | bool | ArgumentList | ArgumentTuple | ArgumentDictionary | None
)


@dataclass(frozen=True, slots=True)
class InvocationKeyword:
    name: str
    value: ArgumentValue


@dataclass(frozen=True, slots=True)
class InvocationArguments:
    positional: tuple[ArgumentValue, ...] = ()
    keywords: tuple[InvocationKeyword, ...] = ()

    def __post_init__(self) -> None:
        if type(self.positional) is not tuple or type(self.keywords) is not tuple:
            raise ValueError("Invocation arguments require immutable positional and keyword tuples")
        if len(self.positional) + len(self.keywords) > 10_000:
            raise ValueError("Invocation literals exceed structural limits")
        names: set[str] = set()
        values = list(self.positional)
        for item in self.keywords:
            if (
                type(item) is not InvocationKeyword
                or not isinstance(item.name, str)
                or not item.name.isidentifier()
                or keyword.iskeyword(item.name)
                or item.name in names
            ):
                raise ValueError("Invocation keyword names must be distinct Python identifiers")
            names.add(item.name)
            values.append(item.value)
        pending = [(item, 0) for item in values]
        count, text = 0, sum(len(item.name) for item in self.keywords)
        if text > 100_000:
            raise ValueError("Invocation literals exceed the text limit")
        while pending:
            value, depth = pending.pop()
            count += 1
            if count > 10_000 or depth > 32:
                raise ValueError("Invocation literals exceed structural limits")
            if type(value) is str:
                text += len(value)
                if text > 100_000:
                    raise ValueError("Invocation literals exceed the text limit")
            elif (
                value is None
                or type(value) in (bool, int)
                or (type(value) is float and math.isfinite(value))
            ):
                continue
            elif type(value) in (ArgumentList, ArgumentTuple):
                assert isinstance(value, (ArgumentList, ArgumentTuple))
                if type(value.items) is not tuple or len(value.items) + count > 10_000:
                    raise ValueError("Invocation sequence is invalid or too large")
                pending.extend((item, depth + 1) for item in value.items)
            elif type(value) is ArgumentDictionary:
                if type(value.entries) is not tuple or len(value.entries) + count > 10_000:
                    raise ValueError("Invocation dictionary is invalid or too large")
                keys: set[str] = set()
                for entry in value.entries:
                    if (
                        type(entry) is not ArgumentEntry
                        or type(entry.key) is not str
                        or entry.key in keys
                    ):
                        raise ValueError("Invocation dictionary keys must be distinct strings")
                    keys.add(entry.key)
                    pending.extend(((entry.key, depth + 1), (entry.value, depth + 1)))
            else:
                raise ValueError("Invocation arguments support finite literal values only")


EMPTY_INVOCATION_ARGUMENTS = InvocationArguments()


@dataclass(frozen=True, slots=True)
class UnresolvedInvocationArguments:
    text: str


type ConfiguredArguments = InvocationArguments | UnresolvedInvocationArguments


def _literal(node: ast.AST, depth: int = 0) -> ArgumentValue:
    if depth > 32:
        raise ValueError("Invocation literals exceed the nesting limit")
    if isinstance(node, ast.Constant) and (
        node.value is None or type(node.value) in (str, int, float, bool)
    ):
        return cast(ArgumentValue, node.value)
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, (ast.USub, ast.UAdd))
        and isinstance(node.operand, ast.Constant)
        and type(node.operand.value) in (int, float)
    ):
        number = cast(int | float, node.operand.value)
        return -number if isinstance(node.op, ast.USub) else number
    if isinstance(node, (ast.List, ast.Tuple)):
        items = tuple(_literal(item, depth + 1) for item in node.elts)
        return ArgumentList(items) if isinstance(node, ast.List) else ArgumentTuple(items)
    if isinstance(node, ast.Dict):
        entries: list[ArgumentEntry] = []
        for key_node, value_node in zip(node.keys, node.values, strict=True):
            if not isinstance(key_node, ast.Constant) or type(key_node.value) is not str:
                raise ValueError("Invocation dictionary keys must be string literals")
            entries.append(ArgumentEntry(key_node.value, _literal(value_node, depth + 1)))
        return ArgumentDictionary(tuple(entries))
    raise ValueError("Use literal values, not names, calls, expressions, or argument unpacking")


def parse_invocation_arguments(text: str) -> InvocationArguments:
    """Read the compact editor notation; no Python expression is evaluated."""
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError("Invocation argument notation must be bounded text")
    try:
        expression = ast.parse(f"_arguments({text})", mode="eval").body
    except (SyntaxError, RecursionError) as exc:
        raise ValueError("Enter literal positional values and name=value keyword values") from exc
    if (
        not isinstance(expression, ast.Call)
        or not isinstance(expression.func, ast.Name)
        or expression.func.id != "_arguments"
    ):
        raise ValueError("Invalid invocation argument notation")
    if sum(1 for _ in ast.walk(expression)) > 20_000:
        raise ValueError("Invocation argument notation exceeds structural limits")
    if any(item.arg is None for item in expression.keywords):
        raise ValueError("Invocation argument unpacking is not supported")
    return InvocationArguments(
        tuple(_literal(item) for item in expression.args),
        tuple(
            InvocationKeyword(item.arg, _literal(item.value))
            for item in expression.keywords
            if item.arg is not None
        ),
    )


def configured_arguments_from_text(text: str) -> ConfiguredArguments:
    try:
        return parse_invocation_arguments(text)
    except ValueError:
        return UnresolvedInvocationArguments(text)


def render_argument_value(value: ArgumentValue) -> str:
    if isinstance(value, ArgumentList):
        return "[" + ", ".join(render_argument_value(item) for item in value.items) + "]"
    if isinstance(value, ArgumentTuple):
        return (
            "("
            + ", ".join(render_argument_value(item) for item in value.items)
            + ("," if len(value.items) == 1 else "")
            + ")"
        )
    if isinstance(value, ArgumentDictionary):
        return (
            "{"
            + ", ".join(
                f"{item.key!r}: {render_argument_value(item.value)}" for item in value.entries
            )
            + "}"
        )
    return repr(value)


def render_invocation_arguments(arguments: ConfiguredArguments) -> str:
    if isinstance(arguments, UnresolvedInvocationArguments):
        return arguments.text
    return ", ".join(
        (
            *(render_argument_value(item) for item in arguments.positional),
            *(f"{item.name}={render_argument_value(item.value)}" for item in arguments.keywords),
        )
    )
