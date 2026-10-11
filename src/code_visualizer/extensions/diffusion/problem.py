"""Validate the declared physical fragment and derive one disposable numerical input."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import ceil, isfinite
from typing import NoReturn

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.intentional import DomainIssue, DomainModel, IntentionalNode
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, QuantityValue, UnitReference
from code_visualizer.execution.backends import PreparedComputation
from code_visualizer.extensions.diffusion.domain import identity
from code_visualizer.extensions.fields.domain import identity as field_id
from code_visualizer.extensions.fields.records import CHUNK_BYTES, scalar
from code_visualizer.extensions.fields.units import field_catalog
from code_visualizer.extensions.foundations.space import identity as space_id
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind, UnitAlgebra
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.intentional import domain_model_to_data


class DiffusionError(ValueError):
    def __init__(self, code: str, message: str, object_id: str):
        super().__init__(message)
        self.code, self.object_id = code, object_id


@dataclass(frozen=True, slots=True)
class DiffusionProblem:
    problem_id: str
    field_id: str
    grid_id: str
    frame_id: str
    space_id: str
    axis_id: str
    axis_name: str
    length: float
    diffusivity: float
    amplitude: float
    scale: float
    unit: UnitReference
    quantity_kind: QuantityKind
    nodes: int
    final_time: float
    steps: int
    sample_every: int
    checkpoint_every: int
    preview_every: int
    chunk_rows: int

    @property
    def dx(self) -> float:
        return self.length / (self.nodes - 1)

    @property
    def dt(self) -> float:
        return self.final_time / self.steps

    @property
    def ratio(self) -> float:
        return self.diffusivity * self.dt / self.dx**2

    def time(self, step: int) -> float:
        return step * self.dt


def definition_digest(snapshot: PreparedComputation) -> str:
    if not isinstance(snapshot.value, DomainModel):
        raise ValueError("Diffusion requires intentional domain input")
    # The scientific source is this exact definition/dependency closure, independent
    # of local editor revision and resume input. Git retains its broader source and
    # implementation/environment closure separately.
    data: dict[str, JsonValue] = {
        "version": 1,
        "backend": [snapshot.request.backend_id, snapshot.request.backend_version],
        "models": [
            domain_model_to_data(model)
            for model in sorted(
                (snapshot.value, *snapshot.dependency_models), key=lambda item: item.id
            )
        ],
    }
    return sha256(canonical_data_bytes(data)).hexdigest()


def derive_problem(project: Project, model: DomainModel) -> DiffusionProblem:
    nodes = {
        node.id: node for candidate in project.domain_workspace.models for node in candidate.nodes
    }
    root = model.node(model.roots[0]) if len(model.roots) == 1 else None
    if root is None or root.concept_id != identity("Problem"):
        raise DiffusionError("DIFFUSION_ROOT", "Select exactly one diffusion problem", model.id)

    root_id = root.id

    def fail(code: str, message: str, node: IntentionalNode | None = None) -> NoReturn:
        raise DiffusionError(code, message, node.id if node is not None else root_id)

    def target(
        node: IntentionalNode, role: str, concept: str, *, child: bool = False
    ) -> IntentionalNode:
        ids = node.child_ids(role) if child else node.reference_ids(role)
        value = nodes.get(ids[0]) if len(ids) == 1 else None
        if value is None or value.concept_id != concept:
            raise DiffusionError(
                "DIFFUSION_REFERENCE", "A required typed physical reference is absent", node.id
            )
        return value

    def value(node: IntentionalNode, name: str) -> CanonicalValue:
        prop_id = node.concept_id + ":" + name
        actual = node.property(prop_id)
        if actual is None:
            prop = next(
                (
                    concept.property(prop_id)
                    for schema in project.domain_workspace.schemas
                    for concept in schema.concepts
                    if concept.id == node.concept_id
                ),
                None,
            )
            actual = prop.default if prop is not None else None
        if actual is None:
            raise DiffusionError("DIFFUSION_PARAMETER", f"Missing {name}", node.id)
        return actual

    algebra = UnitAlgebra(field_catalog())

    def quantity(
        node: IntentionalNode,
        name: str,
        unit: UnitReference,
        kind: QuantityKind = QuantityKind.LINEAR,
    ) -> float:
        actual = value(node, name)
        if not isinstance(actual, QuantityValue):
            raise DiffusionError("DIFFUSION_UNIT", f"{name} requires an explicit quantity", node.id)
        try:
            return scalar(algebra.convert(actual, unit, kind=kind), name)
        except ValueError as exc:
            raise DiffusionError(getattr(exc, "code", "DIFFUSION_UNIT"), str(exc), node.id) from exc

    field = target(root, identity("Problem", "field"), field_id("Field"))
    grid = target(field, field_id("Field", "grid"), field_id("UniformGrid"))
    frame = target(grid, field_id("UniformGrid", "frame"), space_id("Frame"))
    axis = target(grid, field_id("UniformGrid", "axis"), space_id("Axis"))
    space = target(frame, space_id("Frame", "space"), space_id("Space"))
    if (
        value(space, "dimension") != 1
        or value(axis, "ordinal") != 0
        or space.child_ids(space_id("Space", "axes")) != (axis.id,)
    ):
        fail("DIFFUSION_FRAME", "Diffusion requires the declared axis of one Cartesian space", grid)
    initial = target(root, identity("Problem", "initial"), identity("SineInitial"), child=True)
    target(root, identity("Problem", "boundary"), identity("ZeroBoundary"), child=True)
    policy = target(root, identity("Problem", "policy"), identity("TimePolicy"), child=True)
    kind_value = value(field, "quantity_kind")
    if kind_value not in ("linear", "interval"):
        fail(
            "DIFFUSION_QUANTITY_KIND",
            "This diffusion fragment supports linear or interval scalars, not affine points",
            field,
        )
    assert isinstance(kind_value, str)
    kind = QuantityKind(kind_value)
    scale_quantity = value(field, "scale")
    if not isinstance(scale_quantity, QuantityValue):
        fail("DIFFUSION_UNIT", "A scalar field requires its explicit unit/scale", field)
    assert isinstance(scale_quantity, QuantityValue)
    scale = quantity(field, "scale", scale_quantity.unit, kind)
    amplitude = quantity(initial, "amplitude", scale_quantity.unit, kind)

    def count(node: IntentionalNode, name: str, maximum: int = 1000000) -> int:
        actual = value(node, name)
        if type(actual) is not int or not 1 <= actual <= maximum:
            raise DiffusionError(
                "DIFFUSION_POLICY",
                f"{name} is outside its supported positive integer bound",
                node.id,
            )
        return actual

    catalog = field_catalog()
    length = quantity(grid, "length", catalog.unit("foundation.units.si:meter"))
    diffusivity = quantity(
        root, "diffusivity", catalog.unit("foundation.fields.units:square_meter_per_second")
    )
    final_time = quantity(policy, "final_time", catalog.unit("foundation.units.si:second"))
    count_nodes = count(grid, "nodes", 262144)
    if min(length, diffusivity, final_time, scale) <= 0 or amplitude < 0 or count_nodes < 3:
        fail(
            "DIFFUSION_RANGE",
            "Length, diffusivity, horizon and scale must be positive; amplitude nonnegative; "
            "at least three nodes are required",
        )
    max_rows = (CHUNK_BYTES - 128) // ((count_nodes + 2) * 8)
    result = DiffusionProblem(
        root.id,
        field.id,
        grid.id,
        frame.id,
        space.id,
        axis.id,
        str(value(axis, "name")),
        length,
        diffusivity,
        amplitude,
        scale,
        scale_quantity.unit,
        kind,
        count_nodes,
        final_time,
        count(policy, "steps"),
        count(policy, "sample_every"),
        count(policy, "checkpoint_every"),
        count(policy, "preview_every"),
        min(count(policy, "chunk_rows", 262144), max_rows),
    )
    try:
        ratio = result.ratio
    except (OverflowError, ZeroDivisionError) as exc:
        raise DiffusionError(
            "DIFFUSION_STEP", "Grid/timestep exceeds float64 numerical range", policy.id
        ) from exc
    if not isfinite(ratio) or ratio > 0.5 or ratio <= 0 or result.chunk_rows < 1:
        fail("DIFFUSION_STEP", "Supported positivity fragment requires 0 < D*dt/dx² <= 0.5", policy)
    samples = (
        ceil(result.steps / result.sample_every) + ceil(result.steps / result.checkpoint_every) + 2
    )
    chunks = ceil(samples / result.chunk_rows) + ceil(result.steps / result.checkpoint_every) + 2
    checkpoints = ceil(result.steps / result.checkpoint_every) + 1
    if chunks > 256 or 2 * chunks + 3 * checkpoints + 8 > 1024:
        fail(
            "DIFFUSION_OUTPUT_LIMIT",
            "This finite history exceeds its closure/index/publication count boundary",
            policy,
        )
    if samples * (result.nodes + 2) * 8 + checkpoints * result.nodes * 8 > 2 * 1024**3:
        fail(
            "DIFFUSION_OUTPUT_LIMIT", "This finite history exceeds the 2 GiB transfer phase", policy
        )
    return result


def validate_problem(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    try:
        derive_problem(project, model)
    except DiffusionError as exc:
        return (DomainIssue(exc.code, str(exc), exc.object_id, incomplete=True),)
    return ()
