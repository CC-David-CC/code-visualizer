"""Language authoring mutations and durable inverses on one ProjectAuthority."""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.application.authority import CommandError, Handler, Mutation
from code_visualizer.application.commands import Operation
from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.language import (
    AuthoredDomainLanguage,
    AuthoredTransformation,
    ValidatorDefinition,
)
from code_visualizer.domain.language_structure import language_owned_ids
from code_visualizer.domain.notation import NotationDefinition
from code_visualizer.domain.project import Project
from code_visualizer.persistence.language import (
    LanguageDecodeError,
    authored_language_from_data,
    authored_language_to_data,
    language_record_from_data,
    language_record_to_data,
)

type Definition = NotationDefinition | ValidatorDefinition | AuthoredTransformation


def _text(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise CommandError("DOMAIN_LANGUAGE_PAYLOAD", f"{key} must be nonempty text")
    return value


def _index(payload: dict[str, JsonValue], length: int) -> int:
    value = payload.get("index", length)
    if type(value) is not int or not 0 <= value <= length:
        raise CommandError("DOMAIN_LANGUAGE_INDEX", "Index is outside the collection")
    return value


def _lookup(project: Project, payload: dict[str, JsonValue]) -> AuthoredDomainLanguage:
    language = project.domain_workspace.language(_text(payload, "language_id"))
    if language is None:
        raise CommandError("DOMAIN_LANGUAGE_MISSING", "Authored language does not exist")
    return language


def _project_with(project: Project, language: AuthoredDomainLanguage) -> Project:
    return replace(
        project,
        domain_workspace=replace(
            project.domain_workspace,
            language_definitions=tuple(
                language if item.id == language.id else item
                for item in project.domain_workspace.language_definitions
            ),
        ),
    )


def _put(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    language = authored_language_from_data(payload.get("language"))
    previous = project.domain_workspace.language(language.id)
    values = project.domain_workspace.language_definitions
    if previous is None:
        index = _index(payload, len(values))
        values = (*values[:index], language, *values[index:])
        inverse = Operation("domain.language.delete", {"language_id": language.id})
    else:
        values = tuple(language if item.id == language.id else item for item in values)
        inverse = Operation(
            "domain.language.put", {"language": authored_language_to_data(previous)}
        )
    changed_ids = (
        *language_owned_ids(language),
        *(language_owned_ids(previous) if previous else ()),
    )
    return Mutation(
        replace(
            project, domain_workspace=replace(project.domain_workspace, language_definitions=values)
        ),
        "domain.language.changed",
        {"language_id": language.id},
        tuple(dict.fromkeys(changed_ids)),
        inverse,
    )


def _delete(project: Project, payload: dict[str, JsonValue]) -> Mutation:
    language = _lookup(project, payload)
    values = project.domain_workspace.language_definitions
    return Mutation(
        replace(
            project,
            domain_workspace=replace(
                project.domain_workspace,
                language_definitions=tuple(item for item in values if item.id != language.id),
            ),
        ),
        "domain.language.deleted",
        {"language_id": language.id},
        language_owned_ids(language),
        Operation(
            "domain.language.put",
            {
                "language": authored_language_to_data(language),
                "index": values.index(language),
            },
        ),
    )


def _identity(value: Definition) -> str:
    return value.definition.id if isinstance(value, AuthoredTransformation) else value.id


def _definitions(language: AuthoredDomainLanguage, kind: str) -> tuple[Definition, ...]:
    if kind == "notation":
        return language.notations
    if kind == "validator":
        return language.validators
    return language.transformations


def _replace_definitions(
    language: AuthoredDomainLanguage, kind: str, values: tuple[Definition, ...]
) -> AuthoredDomainLanguage:
    if kind == "notation":
        assert all(isinstance(item, NotationDefinition) for item in values)
        return replace(
            language,
            notations=tuple(item for item in values if isinstance(item, NotationDefinition)),
        )
    if kind == "validator":
        assert all(isinstance(item, ValidatorDefinition) for item in values)
        return replace(
            language,
            validators=tuple(item for item in values if isinstance(item, ValidatorDefinition)),
        )
    assert all(isinstance(item, AuthoredTransformation) for item in values)
    return replace(
        language,
        transformations=tuple(item for item in values if isinstance(item, AuthoredTransformation)),
    )


def _edit(project: Project, payload: dict[str, JsonValue], kind: str, deleting: bool) -> Mutation:
    language = _lookup(project, payload)
    values = _definitions(language, kind)
    definition: Definition | None = None
    if deleting:
        identity = _text(payload, "definition_id")
    else:
        if kind == "notation":
            definition = language_record_from_data(payload.get("definition"), NotationDefinition)
        elif kind == "validator":
            definition = language_record_from_data(payload.get("definition"), ValidatorDefinition)
        else:
            definition = language_record_from_data(
                payload.get("definition"), AuthoredTransformation
            )
        identity = _identity(definition)
    previous = next((item for item in values if _identity(item) == identity), None)
    if deleting:
        if previous is None:
            raise CommandError("DOMAIN_LANGUAGE_DEFINITION_MISSING", "Definition does not exist")
        updated = tuple(item for item in values if _identity(item) != identity)
    elif previous is None:
        assert definition is not None
        index = _index(payload, len(values))
        updated = (*values[:index], definition, *values[index:])
    else:
        assert definition is not None
        updated = tuple(definition if _identity(item) == identity else item for item in values)
    inverse = (
        Operation(
            f"domain.language.{kind}.delete",
            {"language_id": language.id, "definition_id": identity},
        )
        if previous is None
        else Operation(
            f"domain.language.{kind}.put",
            {
                "language_id": language.id,
                "definition": language_record_to_data(previous),
                "index": values.index(previous),
            },
        )
    )
    return Mutation(
        _project_with(project, _replace_definitions(language, kind, updated)),
        "domain.language.changed",
        {"language_id": language.id, "definition_id": identity},
        (language.id, identity),
        inverse,
    )


def _guard(handler: Handler) -> Handler:
    def apply(project: Project, payload: dict[str, JsonValue]) -> Mutation:
        try:
            return handler(project, payload)
        except LanguageDecodeError as exc:
            raise CommandError("DOMAIN_LANGUAGE_PAYLOAD", str(exc)) from exc

    return apply


def language_handlers() -> tuple[tuple[str, Handler], ...]:
    handlers: list[tuple[str, Handler]] = [
        ("domain.language.put", _put),
        ("domain.language.delete", _delete),
    ]
    for kind in ("notation", "validator", "transformation"):
        for deleting in (False, True):

            def edit(
                project: Project,
                payload: dict[str, JsonValue],
                kind: str = kind,
                deleting: bool = deleting,
            ) -> Mutation:
                return _edit(project, payload, kind, deleting)

            suffix = "delete" if deleting else "put"
            handlers.append((f"domain.language.{kind}.{suffix}", edit))
    return tuple((name, _guard(handler)) for name, handler in handlers)
