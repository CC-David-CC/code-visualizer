"""Closed, bounded invocation literals for editor preparation worker requests."""

from re import fullmatch

from code_visualizer.domain.invocation_arguments import (
    ArgumentDictionary,
    ArgumentEntry,
    ArgumentList,
    ArgumentTuple,
    ArgumentValue,
    InvocationArguments,
    InvocationKeyword,
)
from code_visualizer.protocol.v1 import worker_pb2 as wire
from code_visualizer.protocol.validation import check_message, invalid, require_field


def _literal_to_proto(value: ArgumentValue) -> wire.InvocationLiteral:
    result = wire.InvocationLiteral()
    if value is None:
        result.null = True
    elif type(value) is bool:
        result.boolean = value
    elif type(value) is int:
        result.integer_decimal = str(value)
    elif type(value) is float:
        result.real = value
    elif type(value) is str:
        result.text = value
    elif isinstance(value, ArgumentList | ArgumentTuple):
        target = result.list if isinstance(value, ArgumentList) else result.tuple
        target.CopyFrom(wire.InvocationSequence(items=map(_literal_to_proto, value.items)))
    elif isinstance(value, ArgumentDictionary):
        result.dictionary.CopyFrom(
            wire.InvocationDictionary(
                entries=(
                    wire.InvocationEntry(key=item.key, value=_literal_to_proto(item.value))
                    for item in value.entries
                )
            )
        )
    else:
        raise invalid("An invocation argument must be a supported literal")
    return result


def invocation_arguments_to_proto(value: InvocationArguments) -> wire.InvocationArguments:
    if not isinstance(value, InvocationArguments):
        raise invalid("Editor preparation accepts resolved literal arguments only")
    result = wire.InvocationArguments(
        positional=map(_literal_to_proto, value.positional),
        keywords=(
            wire.InvocationEntry(key=item.name, value=_literal_to_proto(item.value))
            for item in value.keywords
        ),
    )
    check_message(result, version=1)
    return result


def invocation_arguments_from_proto(value: wire.InvocationArguments) -> InvocationArguments:
    check_message(value, version=1)
    budget = [10_000]

    def literal(item: wire.InvocationLiteral, depth: int = 0) -> ArgumentValue:
        budget[0] -= 1
        if depth > 32 or budget[0] < 0:
            raise invalid("Invocation literal exceeds structural limits")
        match item.WhichOneof("value"):
            case "null":
                if not item.null:
                    raise invalid("An invocation null marker must be true")
                return None
            case "text":
                return item.text
            case "boolean":
                return item.boolean
            case "integer_decimal":
                if not fullmatch(r"0|-?[1-9][0-9]*", item.integer_decimal):
                    raise invalid("An invocation integer requires canonical decimal notation")
                return int(item.integer_decimal)
            case "real":
                return item.real
            case "list" | "tuple":
                is_list = item.WhichOneof("value") == "list"
                sequence = item.list if is_list else item.tuple
                children = tuple(literal(child, depth + 1) for child in sequence.items)
                return ArgumentList(children) if is_list else ArgumentTuple(children)
            case "dictionary":
                entries = []
                for entry in item.dictionary.entries:
                    require_field(entry, "value")
                    entries.append(ArgumentEntry(entry.key, literal(entry.value, depth + 1)))
                return ArgumentDictionary(tuple(entries))
            case _:
                raise invalid("An invocation literal variant must be present")

    keywords = []
    for keyword in value.keywords:
        require_field(keyword, "value")
        keywords.append(InvocationKeyword(keyword.key, literal(keyword.value)))
    return InvocationArguments(tuple(literal(item) for item in value.positional), tuple(keywords))
