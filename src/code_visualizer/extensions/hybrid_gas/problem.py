"""Unit-normalized frozen definitions. Native allocation follows complete admission."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import isclose, isfinite
from typing import TYPE_CHECKING

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.intentional import DomainIssue, DomainModel, IntentionalNode
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, QuantityValue, ResourceReference
from code_visualizer.execution.backends import PreparedComputation, terminal_schemas
from code_visualizer.extensions.fields.records import scalar
from code_visualizer.extensions.foundations.space import identity as space_id
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind, UnitAlgebra
from code_visualizer.extensions.foundations.units import UnitError
from code_visualizer.extensions.hybrid_gas.continuum import GasGrid, Wall
from code_visualizer.extensions.hybrid_gas.coupling import Slab
from code_visualizer.extensions.hybrid_gas.domain import COMPONENTS, identity
from code_visualizer.extensions.hybrid_gas.interface import FluxUnits, Interface
from code_visualizer.extensions.hybrid_gas.policy import ModelPolicy
from code_visualizer.extensions.hybrid_gas.thermodynamics import GasLaw
from code_visualizer.extensions.hybrid_gas.units import catalog, quantity
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.intentional import domain_model_to_data, domain_schema_to_data

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


class GasError(ValueError):
    def __init__(self, code: str, message: str, object_id: str):
        super().__init__(message)
        self.code, self.object_id = code, object_id


def definition_digest(snapshot: PreparedComputation) -> str:
    if not isinstance(snapshot.value, DomainModel):
        raise ValueError("Gas computation requires intentional input")
    data: dict[str, JsonValue] = {
        "version": 1,
        "backend": [snapshot.request.backend_id, snapshot.request.backend_version],
        "seed": snapshot.request.seed,
        "models": [
            domain_model_to_data(m)
            for m in sorted((snapshot.value, *snapshot.dependency_models), key=lambda m: m.id)
        ],
        "schemas": [domain_schema_to_data(s) for s in terminal_schemas(snapshot)],
    }
    return sha256(canonical_data_bytes(data)).hexdigest()


@dataclass(frozen=True, slots=True)
class GasPolicy:
    mode: str
    seed: int
    quantum: float
    window_ticks: int
    final_tick: int
    sample_ticks: int
    checkpoint_ticks: int
    statistics_ticks: int
    warmup_ticks: int
    block_ticks: int
    chunk_rows: int
    preview_windows: int
    collision_cells: int
    particles_full_channel: int
    maximum_particles: int
    model: ModelPolicy


@dataclass(frozen=True, slots=True)
class GasProblem:
    problem_id: str
    gas_id: str
    region_id: str
    slab_id: str
    initial_id: str
    policy_id: str
    space_id: str
    frame_id: str
    axis_id: str
    field_ids: tuple[str, ...]
    face_ids: tuple[str, str]
    wall_ids: tuple[str, str]
    calibration: ResourceReference
    grid: GasGrid
    slab: Slab
    walls: tuple[Wall, Wall]
    number_density: float
    temperature: float
    velocity: tuple[float, float, float]
    sine_amplitude: float
    policy: GasPolicy

    @property
    def origins(self) -> tuple[str, ...]:
        return (
            self.problem_id,
            self.gas_id,
            self.region_id,
            self.slab_id,
            self.initial_id,
            self.policy_id,
            *self.field_ids,
            *self.face_ids,
            *self.wall_ids,
        )

    @property
    def fnum(self) -> float:
        return (
            self.number_density
            * self.grid.area
            * self.grid.length
            / self.policy.particles_full_channel
        )

    def faces(self, source: str, law_digest: str, law: GasLaw) -> tuple[Interface, Interface]:
        def face(i: int, normal: int) -> Interface:
            return Interface(
                source,
                law_digest,
                self.policy_id,
                self.slab_id,
                self.face_ids[i],
                self.frame_id,
                self.axis_id,
                normal,
                quantity(self.grid.area, "square_meter"),
                quantity(self.fnum * law.species_mass, "kilogram"),
                FluxUnits.si(),
            )

        return face(0, -1), face(1, 1)

    def initial_values(self, law: GasLaw) -> NDArray[np.float64]:
        import numpy as np

        edges = np.arange(self.grid.cells + 1) * self.grid.spacing
        wave = 2 * np.pi / self.grid.length
        mean_sin = -np.diff(np.cos(wave * edges)) / (wave * self.grid.spacing)
        mean_sin2 = 0.5 - np.diff(np.sin(2 * wave * edges)) / (4 * wave * self.grid.spacing)
        w = np.empty((self.grid.cells, 5))
        w[:, 0] = self.number_density * law.species_mass
        w[:, 1:4] = self.velocity
        w[:, 1] += self.sine_amplitude * mean_sin
        w[:, 4] = self.number_density * law.boltzmann * self.temperature
        q = law.conserved(w)
        # Integrate initial kinetic energy on the actual support, rather than
        # treating a cell-average velocity as its pointwise square.
        q[:, 4] += 0.5 * w[:, 0] * self.sine_amplitude**2 * (mean_sin2 - mean_sin**2)
        law.primitive(q)
        q.setflags(write=False)
        return q


def derive_problem(project: Project, model: DomainModel) -> GasProblem:
    nodes = {n.id: n for m in project.domain_workspace.models for n in m.nodes}
    concepts = {c.id: c for s in project.domain_workspace.schemas for c in s.concepts}
    root = model.node(model.roots[0]) if len(model.roots) == 1 else None
    if root is None or root.concept_id != identity("Problem"):
        raise GasError("GAS_ROOT", "Select one gas experiment", model.id)

    def value(n: IntentionalNode, name: str) -> CanonicalValue:
        key = n.concept_id + ":" + name
        result = n.property(key)
        if result is None and n.concept_id in concepts:
            prop = concepts[n.concept_id].property(key)
            result = prop.default if prop else None
        if result is None:
            raise GasError("GAS_PARAMETER", f"Missing {name}", n.id)
        return result

    def targets(
        n: IntentionalNode, name: str, kind: str, size: int, *, reference: bool = False
    ) -> tuple[IntentionalNode, ...]:
        key = n.concept_id + ":" + name
        ids = n.reference_ids(key) if reference else n.child_ids(key)
        result = tuple(nodes.get(i) for i in ids)
        if len(result) != size or any(x is None or x.concept_id != kind for x in result):
            raise GasError("GAS_REFERENCE", f"{name} requires {size} typed targets", n.id)
        return tuple(x for x in result if x is not None)

    algebra = UnitAlgebra(catalog())

    def amount(n: IntentionalNode, name: str, unit: str) -> float:
        actual = value(n, name)
        if not isinstance(actual, QuantityValue):
            raise GasError("GAS_QUANTITY", f"{name} requires a typed quantity", n.id)
        try:
            kind = QuantityKind.POINT if unit == "kelvin" else QuantityKind.LINEAR
            return scalar(algebra.convert(actual, quantity(1, unit).unit, kind=kind), name)
        except UnitError as exc:
            raise GasError(exc.issue.code, exc.issue.message, n.id) from exc
        except ValueError as exc:
            raise GasError("GAS_QUANTITY", str(exc), n.id) from exc

    def count(n: IntentionalNode, name: str, low: int, high: int) -> int:
        actual = value(n, name)
        if type(actual) is not int or not low <= actual <= high:
            raise GasError("GAS_POLICY", f"{name} requires an integer in {low}..{high}", n.id)
        return actual

    def ratio(n: IntentionalNode, name: str) -> float:
        actual = value(n, name)
        if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not isfinite(actual):
            raise GasError("GAS_POLICY", f"{name} requires a finite ratio", n.id)
        return float(actual)

    (gas,) = targets(root, "gas", identity("Gas"), 1)
    (channel,) = targets(root, "channel", identity("Channel"), 1)
    (region,) = targets(root, "slab", identity("Slab"), 1)
    (initial,) = targets(root, "initial", identity("Initial"), 1)
    (policy,) = targets(root, "policy", identity("Policy"), 1)
    (frame,) = targets(channel, "frame", space_id("Frame"), 1, reference=True)
    (axis,) = targets(channel, "axis", space_id("Axis"), 1, reference=True)
    (space,) = targets(frame, "space", space_id("Space"), 1, reference=True)
    axes = targets(space, "axes", space_id("Axis"), 3)
    if (
        value(space, "dimension") != 3
        or tuple(value(a, "ordinal") for a in axes) != (0, 1, 2)
        or axis.id != axes[1].id
    ):
        raise GasError(
            "GAS_FRAME", "Requires the second axis of one Cartesian 3D frame", channel.id
        )
    if value(gas, "species") != "argon_vss_0.81_1.4" or value(gas, "interpretation") != "mean_flow":
        raise GasError(
            "GAS_MODEL_UNSUPPORTED",
            "Only the declared monatomic mean-flow model is supported",
            gas.id,
        )
    calibration = value(gas, "calibration")
    if not isinstance(calibration, ResourceReference):
        raise GasError(
            "GAS_CALIBRATION_RESOURCE",
            "Select retained independent calibration observations",
            gas.id,
        )
    height, area = amount(channel, "height", "meter"), amount(channel, "area", "square_meter")
    lower, upper = amount(region, "lower", "meter"), amount(region, "upper", "meter")
    cells = count(policy, "cells", 16, 128)
    if cells % 8:
        raise GasError(
            "GAS_PROFILE_SUPPORT", "The bounded profile requires eight equal bins", policy.id
        )
    collision_cells = count(policy, "collision_cells", 16, 512)
    if not 0 < lower < upper < height or area <= 0:
        raise GasError(
            "GAS_GEOMETRY", "An interior slab requires positive channel geometry", region.id
        )
    grid = GasGrid(height, area, cells)
    first, stop = round(lower / grid.spacing), round(upper / grid.spacing)
    fine_first, fine_stop = (
        round(lower / height * collision_cells),
        round(upper / height * collision_cells),
    )
    if (
        any(
            not isclose(actual, expected, abs_tol=height * 1e-13, rel_tol=0)
            for actual, expected in (
                (lower, first * grid.spacing),
                (upper, stop * grid.spacing),
                (lower, fine_first * height / collision_cells),
                (upper, fine_stop * height / collision_cells),
            )
        )
        or not 1 <= stop - first <= 128
        or fine_stop <= fine_first
    ):
        raise GasError(
            "GAS_COVERAGE",
            "Slab endpoints must coincide with both declared cell partitions",
            region.id,
        )
    slab = Slab(first, stop, grid)
    mode = value(policy, "mode")
    if mode not in ("fixed", "adaptive", "continuum", "particle"):
        raise GasError("GAS_POLICY", "Unsupported computation mode", policy.id)
    assert isinstance(mode, str)
    final, sample, checkpoint, statistics, warmup, block = (
        count(policy, name, low, 400000)
        for name, low in (
            ("final_tick", 1),
            ("sample_ticks", 1),
            ("checkpoint_ticks", 1),
            ("statistics_ticks", 1),
            ("warmup_ticks", 0),
            ("block_ticks", 1),
        )
    )
    window = count(policy, "window_ticks", 1, 64)
    if (
        any(t % window for t in (final, sample, checkpoint, statistics, warmup, block))
        or final % sample
        or checkpoint % sample
        or final // sample + 1 > 256
        or final // checkpoint + 2 > 16
        or final // statistics > 512
        or block % statistics
        or warmup % statistics
        or warmup >= final
        or (final - warmup) // statistics > 256
        or (final - warmup) % block
    ):
        raise GasError(
            "GAS_OUTPUT_POLICY",
            "Time, statistics and checkpoint schedules exceed aligned bounds",
            policy.id,
        )
    quantum = amount(policy, "quantum", "second")
    if quantum <= 0:
        raise GasError("GAS_TIME", "Microscopic quantum must be positive", policy.id)
    try:
        model_policy = ModelPolicy(
            ratio(policy, "activation_threshold"),
            ratio(policy, "return_threshold"),
            count(policy, "low_opportunities", 1, 64),
            count(policy, "minimum_dwell_ticks", 0, 400000),
            count(policy, "maximum_switches", 1, 8),
        )
    except ValueError as exc:
        raise GasError("GAS_MODEL_POLICY", str(exc), policy.id) from exc
    numerical = GasPolicy(
        mode,
        count(policy, "seed", 1, (1 << 31) - 1),
        quantum,
        window,
        final,
        sample,
        checkpoint,
        statistics,
        warmup,
        block,
        count(policy, "chunk_rows", 1, 256),
        count(policy, "preview_windows", 1, 200000),
        collision_cells,
        count(policy, "particles_full_channel", 400, 20000),
        count(policy, "maximum_particles", 400, 20000),
        model_policy,
    )
    if numerical.particles_full_channel > numerical.maximum_particles:
        raise GasError("GAS_PARTICLE_BUDGET", "Expected population exceeds the bound", policy.id)
    walls = targets(root, "walls", identity("Wall"), 2)
    faces = targets(root, "interfaces", identity("Interface"), 2)
    fields = targets(root, "fields", identity("Field"), 5)

    def by_property(
        items: tuple[IntentionalNode, ...], prop: str, required: tuple[str, ...]
    ) -> tuple[IntentionalNode, ...]:
        table = {str(value(n, prop)): n for n in items}
        if set(table) != set(required):
            raise GasError("GAS_ROLE_MEANING", f"{prop} must cover {required} exactly", root.id)
        return tuple(table[key] for key in required)

    walls = by_property(walls, "side", ("lower", "upper"))
    faces = by_property(faces, "side", ("lower", "upper"))
    fields = by_property(fields, "component", COMPONENTS)
    wall_values = tuple(
        Wall(
            amount(n, "temperature", "kelvin"),
            amount(n, "velocity_x", "meter_per_second"),
            amount(n, "velocity_z", "meter_per_second"),
        )
        for n in walls
    )
    density, temperature = (
        amount(initial, "number_density", "per_cubic_meter"),
        amount(initial, "temperature", "kelvin"),
    )
    if density <= 0 or temperature <= 0:
        raise GasError(
            "GAS_INITIAL",
            "Initial number density and absolute temperature must be positive",
            initial.id,
        )
    velocity = tuple(amount(initial, "velocity_" + a, "meter_per_second") for a in "xyz")
    return GasProblem(
        root.id,
        gas.id,
        channel.id,
        region.id,
        initial.id,
        policy.id,
        space.id,
        frame.id,
        axis.id,
        tuple(n.id for n in fields),
        (faces[0].id, faces[1].id),
        (walls[0].id, walls[1].id),
        calibration,
        grid,
        slab,
        (wall_values[0], wall_values[1]),
        density,
        temperature,
        (velocity[0], velocity[1], velocity[2]),
        amount(initial, "sine_amplitude", "meter_per_second"),
        numerical,
    )


def validate_problem(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    try:
        derive_problem(project, model)
    except GasError as exc:
        return (DomainIssue(exc.code, str(exc), exc.object_id, incomplete=True),)
    except (ValueError, OverflowError) as exc:
        return (DomainIssue("GAS_DEFINITION", str(exc), model.id, incomplete=True),)
    return ()
