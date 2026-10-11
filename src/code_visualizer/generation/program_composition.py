"""Disposable composition of Python contributions, preserving declaration ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace

from code_visualizer.domain.invocation_arguments import ConfiguredArguments
from code_visualizer.domain.program import ProgramEntryPoint, ProgramModel, ProgramModule
from code_visualizer.domain.transformation import OriginLink, OriginMap
from code_visualizer.generation.transformation import TransformationError, value_identities


def select_entrypoint(
    program: ProgramModel,
    callable_id: str | None,
    arguments: ConfiguredArguments | None = None,
) -> ProgramModel:
    """Select a call on a temporary model without mutating its authored source."""
    entrypoint = program.entrypoint
    if entrypoint is None:
        if callable_id is None:
            return program
        entrypoint = ProgramEntryPoint(f"entrypoint:{callable_id}")
    return replace(
        program,
        entrypoint=replace(
            entrypoint,
            callable_id=callable_id,
            arguments=entrypoint.arguments if arguments is None else arguments,
        ),
    )


@dataclass(frozen=True, slots=True)
class ProgramComposition:
    program: ProgramModel
    replacements: tuple[tuple[str, str], ...] = ()


def compose_programs(authored: ProgramModel, contribution: ProgramModel) -> ProgramComposition:
    """Append one explicitly ordered contribution to matching Python module paths.

    Module paths identify the derived Python namespace. Canonical module identities
    remain distinct in their sources; the build retains the first identity and
    returns origin rewrites for subsequent contributions to that namespace.
    """
    collisions = value_identities(authored) & value_identities(contribution)
    if collisions:
        raise TransformationError(
            "TRANSFORM_ID_COLLISION", f"Python contributions share IDs: {sorted(collisions)!r}"
        )
    modules: list[ProgramModule] = list(authored.modules)
    replacements: list[tuple[str, str]] = []
    for incoming in contribution.modules:
        index = next((i for i, item in enumerate(modules) if item.path == incoming.path), None)
        if index is None:
            modules.append(incoming)
            continue
        existing = modules[index]
        if existing.kind is not incoming.kind:
            raise TransformationError(
                "TRANSFORM_MODULE_CONFLICT",
                f"Import name {existing.path!r} cannot be both a module and a package",
            )
        if existing.docstring and incoming.docstring and existing.docstring != incoming.docstring:
            raise TransformationError(
                "TRANSFORM_MODULE_CONFLICT", f"Module {existing.path!r} has conflicting docstrings"
            )
        modules[index] = replace(
            existing,
            body=(*existing.body, *incoming.body),
            docstring=existing.docstring or incoming.docstring,
        )
        replacements.append((incoming.id, existing.id))
    selected = authored.entrypoint or contribution.entrypoint
    if authored.entrypoint is not None and contribution.entrypoint is not None:
        replacements.append((contribution.entrypoint.id, authored.entrypoint.id))
        if contribution.entrypoint.startup:
            selected = replace(
                authored.entrypoint,
                startup=(*authored.entrypoint.startup, *contribution.entrypoint.startup),
            )
    return ProgramComposition(
        ProgramModel(
            (*authored.functions, *contribution.functions),
            (*authored.symbols, *contribution.symbols),
            tuple(modules),
            authored.package,
            selected,
        ),
        tuple(replacements),
    )


def composed_origins(
    origins: OriginMap, program: ProgramModel, replacements: tuple[tuple[str, str], ...] = ()
) -> OriginMap:
    """Coalesce module origins and cover a newly selected derived invocation."""
    renames = dict(replacements)
    links: dict[str, set[str]] = {}
    available = value_identities(program)
    for link in origins.links:
        identity = renames.get(link.generated_id, link.generated_id)
        if identity in available:
            links.setdefault(identity, set()).update(link.source_ids)
    if program.entrypoint is not None and program.entrypoint.id not in links:
        target = program.entrypoint.callable_id
        source_ids = links.get(target or "", {target} if target is not None else set())
        if source_ids:
            links[program.entrypoint.id] = set(source_ids)
    return replace(
        origins,
        links=tuple(
            OriginLink(identity, tuple(sorted(sources)))
            for identity, sources in sorted(links.items())
        ),
    )
