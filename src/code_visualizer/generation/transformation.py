"""Pure, explicitly registered transformation planning and execution contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, fields, is_dataclass, replace

from code_visualizer.domain.intentional import DomainIssue, DomainModel, DomainWorkspace
from code_visualizer.domain.intentional_validation import validate_domain_workspace
from code_visualizer.domain.language_structure import language_owned_ids
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.project import Project
from code_visualizer.domain.transformation import (
    OriginMap,
    Representation,
    TransformationDefinition,
)
from code_visualizer.domain.values import (
    ComplexValue,
    QuantityValue,
    ResourceReference,
    TensorValue,
    UnitReference,
)


class TransformationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


MAX_PLAN_TRANSFORMATIONS = 512
MAX_PLAN_STEPS = 100_000


@dataclass(frozen=True, slots=True)
class TransformationInput:
    project: Project
    model: DomainModel
    representation: Representation
    value: DomainModel | ProgramModel
    origins: OriginMap


@dataclass(frozen=True, slots=True)
class TransformationResult:
    representation: Representation
    value: DomainModel | ProgramModel
    origins: OriginMap
    entrypoint_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RegisteredTransformation:
    definition: TransformationDefinition
    transform: Callable[[TransformationInput], TransformationResult]
    schema_id: str | None = None
    schema_version: str | None = None
    target_schema_id: str | None = None
    target_schema_version: str | None = None

    def __post_init__(self) -> None:
        if (self.schema_id is None) != (self.schema_version is None):
            raise ValueError("Transformation schema identity and version must be paired")
        if self.schema_id == "" or self.schema_version == "":
            raise ValueError("Transformation schema scope must be nonempty")
        if (self.target_schema_id is None) != (self.target_schema_version is None):
            raise ValueError("Target schema identity and version must be paired")
        if self.target_schema_id == "" or self.target_schema_version == "":
            raise ValueError("Target schema scope must be nonempty")

    @property
    def source_schema(self) -> tuple[str, str] | None:
        return (
            (self.schema_id, self.schema_version)
            if self.schema_id is not None and self.schema_version is not None
            else None
        )

    @property
    def target_schema(self) -> tuple[str, str] | None:
        return (
            (self.target_schema_id, self.target_schema_version)
            if self.target_schema_id is not None and self.target_schema_version is not None
            else None
        )


def _value_identity_list(root: object) -> list[str]:
    result: list[str] = []

    def collect(value: object) -> None:
        if isinstance(
            value, (ComplexValue, QuantityValue, TensorValue, ResourceReference, UnitReference)
        ):
            return
        if isinstance(value, tuple):
            for item in value:
                collect(item)
        elif is_dataclass(value) and not isinstance(value, type):
            identity = getattr(value, "id", None)
            if isinstance(identity, str):
                result.append(identity)
            for item in fields(value):
                collect(getattr(value, item.name))

    collect(root)
    return result


def value_identities(root: object) -> frozenset[str]:
    """Walk immutable owned values, including otherwise hidden expression AST identities."""

    return frozenset(_value_identity_list(root))


def canonical_project_identities(project: Project) -> frozenset[str]:
    """Reserve owned project IDs without treating local notation keys as objects."""

    workspace = project.domain_workspace
    without_languages = replace(
        project, domain_workspace=replace(workspace, language_definitions=())
    )
    return value_identities(without_languages) | frozenset(
        identity
        for language in workspace.language_definitions
        for identity in language_owned_ids(language)
    )


def _reject_cycles[T](edges: dict[T, set[T]], code: str) -> None:
    visiting: set[T] = set()
    visited: set[T] = set()

    def visit(node: T) -> None:
        if node in visiting:
            raise TransformationError(code, f"Transformation cycle contains {node!r}")
        if node in visited:
            return
        visiting.add(node)
        for child in sorted(edges.get(node, ()), key=repr):
            visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in sorted(edges, key=repr):
        visit(node)


def _ordered_registrations(
    registrations: Iterable[RegisteredTransformation],
) -> tuple[RegisteredTransformation, ...]:
    bounded: list[RegisteredTransformation] = []
    for registration in registrations:
        if len(bounded) == MAX_PLAN_TRANSFORMATIONS:
            raise TransformationError(
                "TRANSFORM_LIMIT", "Transformation planning exceeds 512 registrations"
            )
        bounded.append(registration)
    return tuple(sorted(bounded, key=lambda item: item.definition.key))


def declared_transformation_sources(
    registrations: Iterable[RegisteredTransformation], target: Representation
) -> frozenset[Representation]:
    """Find representations declaring a route, without claiming an executable plan.

    Schema scopes and prerequisites govern executable eligibility, not whether a
    representation declares this destination. This bounded descriptor-only query
    distinguishes reference-only data from an unsupported implementation scope.
    """
    incoming: dict[Representation, set[Representation]] = {}
    for item in _ordered_registrations(registrations):
        incoming.setdefault(item.definition.target, set()).add(item.definition.source)
    reached: set[Representation] = set()
    pending = [target]
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        reached.add(current)
        pending.extend(sorted(incoming.get(current, ()), reverse=True))
    return frozenset(reached)


def plan_transformations(
    registrations: Iterable[RegisteredTransformation],
    source: Representation,
    target: Representation,
    *,
    source_schema: tuple[str, str] | None = None,
    target_schema: tuple[str, str] | None = None,
) -> tuple[RegisteredTransformation, ...]:
    """Find the unique representation path satisfying explicit prerequisite ordering.

    A transformation has one immutable input and one output. Intermediate versions
    distinguish successive rewrites of the same physical model. Independent domain
    contributions are composed at the build boundary, outside this linear path.
    """

    entries = _ordered_registrations(registrations)
    by_key: dict[str, RegisteredTransformation] = {}
    dependencies: dict[str, set[str]] = {}
    type State = tuple[Representation, tuple[str, str] | None]
    representations: dict[State, set[State]] = {}
    outgoing: dict[Representation, list[RegisteredTransformation]] = {}
    graph_steps = 0
    scopes = {
        source_schema,
        *(item.source_schema for item in entries),
        *(item.target_schema for item in entries),
    }
    for item in entries:
        definition = item.definition
        if definition.key in by_key:
            raise TransformationError(
                "TRANSFORM_DUPLICATE", f"Duplicate transformation {definition.key!r}"
            )
        by_key[definition.key] = item
        dependencies[definition.key] = set(definition.depends_on)
        outgoing.setdefault(definition.source, []).append(item)
        for scope in scopes if item.source_schema is None else (item.source_schema,):
            graph_steps += 1
            if graph_steps > MAX_PLAN_STEPS:
                raise TransformationError(
                    "TRANSFORM_LIMIT", "Transformation scope graph exceeds its budget"
                )
            representations.setdefault((definition.source, scope), set()).add(
                (definition.target, item.target_schema)
            )
    for key, required in dependencies.items():
        missing = required - by_key.keys()
        if missing:
            raise TransformationError(
                "TRANSFORM_MISSING_DEPENDENCY", f"{key!r} requires {sorted(missing)!r}"
            )
    _reject_cycles(dependencies, "TRANSFORM_DEPENDENCY_CYCLE")
    _reject_cycles(representations, "TRANSFORM_REPRESENTATION_CYCLE")
    if source_schema is None:
        possible = {item.source_schema for item in entries if item.definition.source == source}
        if len(possible) == 1:
            source_schema = next(iter(possible))
        elif len(possible) > 1 and any(scope is not None for scope in possible):
            raise TransformationError(
                "TRANSFORM_SCHEMA_AMBIGUOUS",
                "Choose the exact source schema for this representation",
            )
    if source == target and (target_schema is None or target_schema == source_schema):
        return ()

    paths: list[tuple[RegisteredTransformation, ...]] = []
    remaining = MAX_PLAN_STEPS

    def follow(current: State, path: tuple[RegisteredTransformation, ...]) -> None:
        nonlocal remaining
        if len(paths) > 1:
            return
        if current[0] == target and (target_schema is None or current[1] == target_schema):
            paths.append(path)
            return
        previous = {item.definition.key for item in path}
        for item in outgoing.get(current[0], ()):
            remaining -= 1
            if remaining < 0:
                raise TransformationError(
                    "TRANSFORM_LIMIT", "Transformation planning exceeds its search budget"
                )
            definition = item.definition
            if (
                definition.source == current[0]
                and (item.source_schema is None or item.source_schema == current[1])
                and set(definition.depends_on) <= previous
            ):
                follow((definition.target, item.target_schema), (*path, item))

    follow((source, source_schema), ())
    if not paths:
        raise TransformationError(
            "TRANSFORM_NO_PATH",
            f"No dependency-valid transformation path from {source!r} to {target!r}",
        )
    if len(paths) != 1:
        raise TransformationError(
            "TRANSFORM_AMBIGUOUS_PATH",
            f"More than one transformation path connects {source!r} to {target!r}",
        )
    return paths[0]


def execute_transformations(
    snapshot: TransformationInput,
    plan: tuple[RegisteredTransformation, ...],
    *,
    validate_domain: Callable[[DomainModel], tuple[DomainIssue, ...]] | None = None,
) -> TransformationResult:
    if plan:
        if snapshot.representation != plan[0].definition.source:
            raise TransformationError("TRANSFORM_INPUT", "Transformation input does not match plan")
        initial_scope = (
            (snapshot.value.schema_id, snapshot.value.schema_version)
            if isinstance(snapshot.value, DomainModel)
            else None
        )
        if plan[0].source_schema is not None and plan[0].source_schema != initial_scope:
            raise TransformationError(
                "TRANSFORM_SCHEMA_SCOPE", "Transformation is registered for a different schema"
            )
        expected = plan_transformations(
            plan,
            snapshot.representation,
            plan[-1].definition.target,
            source_schema=initial_scope,
            target_schema=plan[-1].target_schema,
        )
        if expected != plan:
            raise TransformationError(
                "TRANSFORM_ORDER", "Execution order differs from the valid plan"
            )
    current = TransformationResult(snapshot.representation, snapshot.value, snapshot.origins)
    canonical_ids = canonical_project_identities(snapshot.project)
    for registered in plan:
        definition = registered.definition
        current_scope = (
            (current.value.schema_id, current.value.schema_version)
            if isinstance(current.value, DomainModel)
            else None
        )
        if registered.source_schema is not None and registered.source_schema != current_scope:
            raise TransformationError(
                "TRANSFORM_SCHEMA_SCOPE", "Transformation is registered for a different schema"
            )
        if current.representation != definition.source:
            raise TransformationError("TRANSFORM_INPUT", "Transformation input does not match plan")
        output = registered.transform(
            TransformationInput(
                snapshot.project,
                snapshot.model,
                current.representation,
                current.value,
                current.origins,
            )
        )
        if output.representation != definition.target:
            raise TransformationError(
                "TRANSFORM_OUTPUT", f"{definition.key!r} returned the wrong representation"
            )
        if registered.target_schema is not None and (
            not isinstance(output.value, DomainModel)
            or registered.target_schema != (output.value.schema_id, output.value.schema_version)
        ):
            raise TransformationError(
                "TRANSFORM_TARGET_SCHEMA", "Transformation returned another target schema"
            )
        if (output.origins.project_id, output.origins.revision) != (
            snapshot.project.id,
            snapshot.project.revision,
        ):
            raise TransformationError(
                "TRANSFORM_ORIGIN_REVISION", "A transformation changed its pinned origin revision"
            )
        identity_list = _value_identity_list(output.value)
        identities = frozenset(identity_list)
        if len(identities) != len(identity_list):
            raise TransformationError(
                "TRANSFORM_DUPLICATE_ID", "Generated objects cannot share an owned identity"
            )
        if identities & canonical_ids:
            raise TransformationError(
                "TRANSFORM_ID_COLLISION",
                "Derived transformation objects cannot reuse canonical project identities",
            )
        if isinstance(output.value, DomainModel):
            # A derived representation may reference its frozen canonical inputs
            # (for example reference vocabularies). Ownership remains disjoint,
            # proved above; this validation context is never persisted.
            findings = validate_domain_workspace(
                DomainWorkspace(
                    snapshot.project.domain_workspace.schemas,
                    (*snapshot.project.domain_workspace.models, output.value),
                )
            )
            if not findings and validate_domain is not None:
                findings = validate_domain(output.value)
            if findings:
                first = findings[0]
                raise TransformationError(
                    first.code, f"Invalid intermediate domain: {first.message}"
                )
        mapped = {link.generated_id for link in output.origins.links}
        if mapped - identities:
            raise TransformationError(
                "TRANSFORM_ORIGIN_STALE", "Origins name objects absent from transformation output"
            )
        if identities - mapped:
            raise TransformationError(
                "TRANSFORM_ORIGIN_MISSING", "Every transformed object requires an origin"
            )
        available = value_identities(current.value)
        if any(set(link.source_ids) - available for link in output.origins.links):
            raise TransformationError(
                "TRANSFORM_ORIGIN_UNKNOWN",
                "Transformation origins must reference its input objects",
            )
        current = TransformationResult(
            output.representation,
            output.value,
            output.origins.composed_with(current.origins),
            output.entrypoint_ids,
        )
    return current
