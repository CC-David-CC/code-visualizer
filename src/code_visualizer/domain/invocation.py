"""One callable-invocation contract shared by artifacts, live execution, and debugging."""

from __future__ import annotations

import ast
import keyword
import re
from dataclasses import dataclass
from enum import StrEnum
from inspect import Parameter, Signature
from typing import TYPE_CHECKING
from unicodedata import normalize

from code_visualizer.domain.invocation_arguments import (
    EMPTY_INVOCATION_ARGUMENTS,
    InvocationArguments,
    render_invocation_arguments,
)
from code_visualizer.domain.program_bindings import mangle_python_identifier, python_member_path
from code_visualizer.domain.program_kinds import CallableKind, MethodKind, ParameterKind
from code_visualizer.domain.python_symbols import PythonSymbolAllocator

if TYPE_CHECKING:
    from code_visualizer.domain.program import ProgramFunction, ProgramModel


INVOCATION_RESULT_NAME = "_cv_invocation_result"


class InvocationResultPolicy(StrEnum):
    DISCARD = "discard"
    CAPTURE = "capture"
    PRINT = "print"


@dataclass(frozen=True, slots=True)
class InvocationSpec:
    identifier: str
    kind: CallableKind = CallableKind.SYNC
    owning_class: str | None = None
    method_kind: MethodKind | None = None
    arguments: InvocationArguments = EMPTY_INVOCATION_ARGUMENTS
    callable_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, CallableKind):
            raise ValueError("Invocation kind must be a CallableKind")
        if self.method_kind is not None and not isinstance(self.method_kind, MethodKind):
            raise ValueError("Invocation method kind must be a MethodKind")
        if not isinstance(self.arguments, InvocationArguments):
            raise ValueError("Invocation arguments must be structured literal values")
        if not isinstance(self.identifier, str):
            raise ValueError("Invocation identifier must be text")
        for name, qualified in ((self.identifier, False), (self.owning_class, True)):
            if name is not None and (
                not isinstance(name, str)
                or any(
                    not part.isidentifier() or keyword.iskeyword(part)
                    for part in (name.split(".") if qualified else (name,))
                )
            ):
                raise ValueError(f"Invalid invocation identifier {name!r}")
        if (self.owning_class is None) != (self.method_kind is None):
            raise ValueError("A method invocation requires both owning class and method kind")
        if self.callable_id is not None and (
            not isinstance(self.callable_id, str) or not self.callable_id
        ):
            raise ValueError("A canonical callable identity must be nonempty text")

    def callable_source(self, *, imported_alias: str | None = None) -> str:
        if imported_alias is not None and (
            not isinstance(imported_alias, str)
            or not imported_alias.isidentifier()
            or keyword.iskeyword(imported_alias)
        ):
            raise ValueError("An imported callable alias must be a Python identifier")
        if self.owning_class is None:
            return imported_alias or self.identifier
        owner = (
            ".".join((imported_alias, *self.owning_class.split(".")[1:]))
            if imported_alias
            else self.owning_class
        )
        if self.method_kind is MethodKind.INSTANCE:
            owner += "()"
        return f"{owner}.{self.identifier}"


class InvocationBindingError(ValueError):
    """A canonical callable cannot accept the configured invocation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


_PARAMETER_KINDS = {
    ParameterKind.POSITIONAL_ONLY: Parameter.POSITIONAL_ONLY,
    ParameterKind.POSITIONAL_OR_KEYWORD: Parameter.POSITIONAL_OR_KEYWORD,
    ParameterKind.VAR_POSITIONAL: Parameter.VAR_POSITIONAL,
    ParameterKind.KEYWORD_ONLY: Parameter.KEYWORD_ONLY,
    ParameterKind.VAR_KEYWORD: Parameter.VAR_KEYWORD,
}
_BINDING_VALUE = object()


def _parameter_name(owning_class: str | None, name: str) -> str:
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"Invalid parameter identifier {name!r}")
    return mangle_python_identifier(
        normalize("NFKC", name),
        owning_class.rsplit(".", 1)[-1] if owning_class is not None else None,
    )


def _bind_parameters(
    function: ProgramFunction,
    arguments: InvocationArguments,
    implicit_count: int,
    owning_class: str | None,
) -> None:
    names: dict[str, str] = {}

    def signature_name(name: str) -> str:
        if name not in names:
            names[name] = f"_cv_bind_{len(names)}"
        return names[name]

    # Python accepts some Unicode identifiers that normalize to keywords, whereas
    # inspect.Parameter rejects keyword names. A one-to-one alias map preserves
    # name equality and collisions without imposing a different identifier grammar.
    parameters = tuple(
        Parameter(
            signature_name(_parameter_name(owning_class, item.name)),
            _PARAMETER_KINDS[item.kind],
            default=_BINDING_VALUE if item.default is not None else Parameter.empty,
        )
        for item in function.parameters
    )
    keywords = {
        signature_name(normalize("NFKC", item.name)): _BINDING_VALUE for item in arguments.keywords
    }
    if len(keywords) != len(arguments.keywords):
        raise TypeError("keyword arguments collide after Python identifier normalization")
    try:
        # Binding an implicit receiver removes its positional slot while retaining
        # Python's rules for *args and duplicate receiver-name keywords. No defaults,
        # annotations or argument contents are evaluated to validate a call's shape.
        Signature(parameters).bind(
            *((_BINDING_VALUE,) * (implicit_count + len(arguments.positional))),
            **keywords,
        )
    except (TypeError, ValueError) as exc:
        original_names = {alias: name for name, alias in names.items()}
        message = re.sub(
            r"'(_cv_bind_\d+)'",
            lambda match: repr(original_names[match.group(1)]),
            str(exc),
        )
        raise type(exc)(message) from exc


def _implicit_receiver_count(function: ProgramFunction) -> int:
    if function.method_kind is MethodKind.CLASS:
        return 1
    # Python installs an undecorated __new__ as a static method automatically.
    return int(
        function.method_kind is MethodKind.INSTANCE
        and normalize("NFKC", function.identifier) != "__new__"
    )


def bind_invocation(
    program: ProgramModel,
    function: ProgramFunction,
    arguments: InvocationArguments = EMPTY_INVOCATION_ARGUMENTS,
) -> InvocationSpec:
    """Validate receiver and Python parameter binding, then describe that invocation."""
    if program.function(function.id) != function:
        raise InvocationBindingError(
            "INVOCATION_CALLABLE_MISMATCH", "The selected callable is not in this canonical program"
        )
    if not isinstance(arguments, InvocationArguments):
        raise InvocationBindingError(
            "INVOCATION_LITERAL_ARGUMENTS", "Invocation arguments must be structured literal values"
        )
    owning_class = program.class_name_for(function.id)
    owner = program.class_for(function.id)
    if program.module_for(function.id) is None:
        raise InvocationBindingError("INVOCATION_CALLABLE_INVALID", "Callable has no owning module")
    if function.method_kind is MethodKind.INSTANCE:
        from code_visualizer.domain.program import ProgramAction

        imported_constructor = False
        if owner is not None:
            for declaration in owner.body:
                if not isinstance(declaration, ProgramAction):
                    continue
                try:
                    parsed = ast.parse(declaration.source.source)
                except SyntaxError as exc:
                    raise InvocationBindingError(
                        "INVOCATION_CALLABLE_INVALID", "Class declaration is incomplete"
                    ) from exc
                if isinstance(parsed, ast.Module) and any(
                    isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                    and normalize("NFKC", node.name) in {"__new__", "__init__"}
                    for node in parsed.body
                ):
                    imported_constructor = True
        if imported_constructor:
            raise InvocationBindingError(
                "INVOCATION_RECEIVER_REQUIRES_SETUP",
                "Direct instance execution requires a structured constructor signature; "
                "expose a top-level entrypoint that constructs the receiver defined "
                "by Python declarations.",
            )
        if owner is not None and (owner.arguments is not None or owner.decorators):
            raise InvocationBindingError(
                "INVOCATION_RECEIVER_REQUIRES_SETUP",
                "Direct instance execution cannot establish constructor requirements for "
                "a class with bases, metaclass arguments, or decorators; expose a top-level "
                "entrypoint that constructs and initializes the receiver.",
            )
        for constructor in program.functions:
            constructor_name = normalize("NFKC", constructor.identifier)
            if program.class_for(constructor.id) != owner or constructor_name not in {
                "__init__",
                "__new__",
            }:
                continue
            implicit_count = _implicit_receiver_count(constructor)
            if constructor_name == "__new__":
                # Construction explicitly passes cls to __new__, in addition to
                # any descriptor binding declared by a classmethod decorator.
                implicit_count += 1
            try:
                _bind_parameters(
                    constructor, EMPTY_INVOCATION_ARGUMENTS, implicit_count, owning_class
                )
            except (TypeError, ValueError) as exc:
                raise InvocationBindingError(
                    "INVOCATION_RECEIVER_REQUIRES_SETUP",
                    f"{owning_class}.{constructor.identifier}(): {exc}. "
                    "Direct instance-method execution requires a zero-argument constructor; "
                    "expose a top-level entrypoint that constructs and initializes the receiver.",
                ) from exc
    name = f"{owning_class}.{function.identifier}" if owning_class else function.identifier
    try:
        _bind_parameters(function, arguments, _implicit_receiver_count(function), owning_class)
    except (TypeError, ValueError) as exc:
        raise InvocationBindingError("INVOCATION_ARGUMENT_MISMATCH", f"{name}(): {exc}") from exc
    try:
        path = python_member_path(
            function.identifier, tuple(owning_class.split(".")) if owning_class else ()
        )
        return InvocationSpec(
            path[-1],
            function.kind,
            ".".join(path[:-1]) if owning_class else None,
            function.method_kind,
            arguments,
            function.id,
        )
    except ValueError as exc:
        raise InvocationBindingError("INVOCATION_CALLABLE_INVALID", str(exc)) from exc


@dataclass(frozen=True, slots=True)
class InvocationSymbols:
    asyncio_alias: str
    consumer: str
    item: str
    result: str


def invocation_symbols(
    invocation: InvocationSpec,
    *,
    imported_alias: str | None = None,
    allocator: PythonSymbolAllocator | None = None,
) -> InvocationSymbols:
    """Use the caller's lexical allocation context for every wrapper binding."""
    allocator = allocator or PythonSymbolAllocator()
    allocator.reserve(
        (invocation.identifier, *(invocation.owning_class or "").split("."), imported_alias or "")
    )
    return InvocationSymbols(
        allocator.allocate("_cv_asyncio"),
        allocator.allocate("_cv_consume_entrypoint"),
        allocator.allocate("_cv_item"),
        allocator.allocate(INVOCATION_RESULT_NAME),
    )


def render_invocation(
    invocation: InvocationSpec,
    *,
    imported_alias: str | None = None,
    result_policy: InvocationResultPolicy = InvocationResultPolicy.DISCARD,
    indent: str = "",
    include_import: bool = True,
    symbols: InvocationSymbols | None = None,
) -> str:
    """Render the same invocation semantics with an explicit result presentation policy.

    Generators are drained for their body effects; yielded values and their final
    return value are discarded. Sync and async functions retain ordinary returns
    only when the caller asks to capture or display them.
    """

    if not isinstance(result_policy, InvocationResultPolicy):
        raise ValueError("Invocation result policy must be an InvocationResultPolicy")
    symbols = symbols or invocation_symbols(invocation, imported_alias=imported_alias)
    capture = result_policy is not InvocationResultPolicy.DISCARD
    result = f"{symbols.result} = " if capture else ""
    target = invocation.callable_source(imported_alias=imported_alias)
    call = f"{target}({render_invocation_arguments(invocation.arguments)})"
    lines: list[str] = []
    if include_import and invocation.kind in {CallableKind.ASYNC, CallableKind.ASYNC_GENERATOR}:
        lines.append(f"import asyncio as {symbols.asyncio_alias}")
    if invocation.kind is CallableKind.ASYNC:
        lines.append(f"{result}{symbols.asyncio_alias}.run({call})")
    elif invocation.kind is CallableKind.GENERATOR:
        lines.extend((f"for {symbols.item} in {call}:", "    pass"))
        if capture:
            lines.append(f"{symbols.result} = None")
    elif invocation.kind is CallableKind.ASYNC_GENERATOR:
        lines.extend(
            (
                f"async def {symbols.consumer}():",
                f"    async for {symbols.item} in {call}:",
                "        pass",
                f"{result}{symbols.asyncio_alias}.run({symbols.consumer}())",
            )
        )
    else:
        lines.append(f"{result}{call}")
    if result_policy is InvocationResultPolicy.PRINT:
        lines.extend(
            (
                f"if {symbols.result} is not None:",
                f"    print(repr({symbols.result}))",
            )
        )
    return "\n".join(f"{indent}{line}" for line in lines) + "\n"
