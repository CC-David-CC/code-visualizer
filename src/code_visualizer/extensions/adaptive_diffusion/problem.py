"""Unit-normalized disposable input for the explicitly bounded diffusion fragment."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import fsum, isclose, isfinite
from typing import TYPE_CHECKING

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.intentional import DomainIssue, DomainModel, IntentionalNode
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import CanonicalValue, QuantityValue, UnitReference
from code_visualizer.execution.backends import PreparedComputation
from code_visualizer.extensions.adaptive_diffusion.domain import identity
from code_visualizer.extensions.adaptive_fields.domain import identity as field_id
from code_visualizer.extensions.adaptive_fields.units import catalog, quantity
from code_visualizer.extensions.fields.records import scalar
from code_visualizer.extensions.foundations.space import identity as space_id
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind, UnitAlgebra
from code_visualizer.extensions.foundations.units import UnitError
from code_visualizer.persistence.canonical import canonical_data_bytes
from code_visualizer.persistence.intentional import domain_model_to_data

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from code_visualizer.extensions.adaptive_fields.mesh import Mesh


class AdaptiveError(ValueError):
    def __init__(self, code: str, message: str, object_id: str):
        super().__init__(message)
        self.code, self.object_id = code, object_id


def definition_digest(snapshot: PreparedComputation) -> str:
    """Exact authored dependency closure; resume selection is not scientific input."""
    if not isinstance(snapshot.value, DomainModel):
        raise ValueError("Adaptive diffusion requires an intentional model")
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


@dataclass(frozen=True, slots=True)
class AdaptivePolicy:
    mesh_mode: str
    base_cells: int
    maximum_cells: int
    maximum_level: int
    quantum: float
    maximum_dt_ticks: int
    final_tick: int
    sample_ticks: int
    checkpoint_ticks: int
    spatial_atol: float
    spatial_rtol: float
    temporal_atol: float
    temporal_rtol: float
    coarsen_threshold: float
    parent_threshold: float
    coarsen_after: int
    dwell: int
    decision_every: int
    maximum_steps: int
    maximum_rejections: int
    maximum_epochs: int
    chunk_rows: int
    preview_every: int

    def time(self, tick: int) -> float:
        return tick * self.quantum


@dataclass(frozen=True, slots=True)
class FourierMode:
    id: str
    harmonic: int
    amplitude: float


@dataclass(frozen=True, slots=True)
class AdaptiveProblem:
    problem_id: str
    field_id: str
    region_id: str
    initial_id: str
    policy_id: str
    space_id: str
    frame_id: str
    axis_id: str
    axis_name: str
    length: float
    area: float
    diffusivity: float
    scale: float
    unit: UnitReference
    mean: float
    center: float
    modes: tuple[FourierMode, ...]
    policy: AdaptivePolicy

    @property
    def origins(self) -> tuple[str, ...]:
        return (
            self.problem_id,
            self.field_id,
            self.region_id,
            self.initial_id,
            self.policy_id,
            *(mode.id for mode in self.modes),
        )

    def initial_values(self, mesh: Mesh) -> NDArray[np.float64]:
        """Integrate the authored initial meaning on a derived initial partition."""
        import numpy as np

        if (mesh.region_id, mesh.length) != (self.region_id, self.length):
            raise AdaptiveError(
                "ADAPTIVE_MAPPING", "Initial partition belongs to another region", self.region_id
            )
        faces, widths = mesh.faces, mesh.widths
        values = np.full(len(mesh.cells), self.mean, dtype=np.float64)
        for mode in self.modes:
            wave = 2 * np.pi * mode.harmonic / self.length
            values += (
                mode.amplitude * np.diff(np.sin(wave * (faces - self.center))) / (wave * widths)
            )
        if not np.isfinite(values).all() or np.any(values < 0):
            raise AdaptiveError(
                "ADAPTIVE_INITIAL",
                "Initial cell averages exceed the finite positive fragment",
                self.initial_id,
            )
        values.setflags(write=False)
        return values


def derive_problem(project: Project, model: DomainModel) -> AdaptiveProblem:
    nodes = {node.id: node for item in project.domain_workspace.models for node in item.nodes}
    root = model.node(model.roots[0]) if len(model.roots) == 1 else None
    if root is None or root.concept_id != identity("Problem"):
        raise AdaptiveError(
            "ADAPTIVE_ROOT", "Select exactly one adaptive diffusion problem", model.id
        )

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
            raise AdaptiveError("ADAPTIVE_PARAMETER", f"Missing {name}", node.id)
        return actual

    def target(
        node: IntentionalNode, role: str, concept: str, *, child: bool = False
    ) -> IntentionalNode:
        key = node.concept_id + ":" + role
        ids = node.child_ids(key) if child else node.reference_ids(key)
        result = nodes.get(ids[0]) if len(ids) == 1 else None
        if result is None or result.concept_id != concept:
            raise AdaptiveError("ADAPTIVE_REFERENCE", f"Missing typed {role} reference", node.id)
        return result

    algebra = UnitAlgebra(catalog())

    def amount(node: IntentionalNode, name: str, unit: str) -> float:
        actual = value(node, name)
        if not isinstance(actual, QuantityValue):
            raise AdaptiveError("ADAPTIVE_UNIT", f"{name} requires an explicit quantity", node.id)
        try:
            return scalar(
                algebra.convert(actual, quantity(1, unit).unit, kind=QuantityKind.LINEAR), name
            )
        except UnitError as exc:
            raise AdaptiveError(exc.issue.code, exc.issue.message, node.id) from exc
        except ValueError as exc:
            raise AdaptiveError("ADAPTIVE_UNIT", str(exc), node.id) from exc

    def count(node: IntentionalNode, name: str, low: int, high: int) -> int:
        actual = value(node, name)
        if type(actual) is not int or not low <= actual <= high:
            raise AdaptiveError(
                "ADAPTIVE_POLICY", f"{name} requires an integer in {low}..{high}", node.id
            )
        return actual

    def ratio(node: IntentionalNode, name: str) -> float:
        actual = value(node, name)
        if (
            not isinstance(actual, (float, int))
            or isinstance(actual, bool)
            or not isfinite(actual)
            or not 0 <= actual <= 1
        ):
            raise AdaptiveError(
                "ADAPTIVE_POLICY", f"{name} requires a finite ratio in [0, 1]", node.id
            )
        return float(actual)

    field = target(root, "field", field_id("Field"))
    region = target(field, "region", field_id("Interval"))
    frame = target(region, "frame", space_id("Frame"))
    axis = target(region, "axis", space_id("Axis"))
    space = target(frame, "space", space_id("Space"))
    if (
        value(space, "dimension") != 1
        or value(axis, "ordinal") != 0
        or space.child_ids(space_id("Space", "axes")) != (axis.id,)
    ):
        raise AdaptiveError(
            "ADAPTIVE_FRAME", "Requires the sole axis of a Cartesian 1D frame", region.id
        )
    if value(field, "quantity_kind") != "linear" or value(root, "boundary") != "periodic":
        raise AdaptiveError(
            "ADAPTIVE_VALIDITY",
            "Only linear concentration and periodic diffusion are supported",
            root.id,
        )
    initial = target(root, "initial", identity("FourierInitial"), child=True)
    policy = target(root, "policy", identity("Policy"), child=True)
    length = amount(region, "length", "meter")
    area = amount(region, "area", "square_meter")
    diffusivity = amount(root, "diffusivity", "square_meter_per_second")
    scale = amount(field, "scale", "kilogram_per_cubic_meter")
    for actual, source, name in (
        (length, region, "length"),
        (area, region, "area"),
        (diffusivity, root, "diffusivity"),
        (scale, field, "scale"),
    ):
        if actual <= 0:
            raise AdaptiveError("ADAPTIVE_RANGE", f"{name} must be positive", source.id)
    mean = amount(initial, "mean", "kilogram_per_cubic_meter")
    center = amount(initial, "center", "meter")
    mode_ids = initial.child_ids(identity("FourierInitial", "modes"))
    modes = []
    if len(mode_ids) > 8:
        raise AdaptiveError(
            "ADAPTIVE_INITIAL", "At most eight Fourier modes are supported", initial.id
        )
    for node_id in mode_ids:
        node = nodes.get(node_id)
        if node is None or node.concept_id != identity("Mode"):
            raise AdaptiveError(
                "ADAPTIVE_REFERENCE", "Initial profile has a missing typed mode", initial.id
            )
        modes.append(
            FourierMode(
                node.id,
                count(node, "mode", 1, 8),
                amount(node, "amplitude", "kilogram_per_cubic_meter"),
            )
        )
    if (
        len({mode.harmonic for mode in modes}) != len(modes)
        or not 0 <= center <= length
        or mean < fsum(abs(mode.amplitude) for mode in modes)
    ):
        raise AdaptiveError(
            "ADAPTIVE_INITIAL",
            "Requires distinct modes, center in the region and mean >= sum(abs(amplitudes))",
            initial.id,
        )
    maximum_dt = amount(policy, "maximum_dt", "second")
    subdivisions = count(policy, "subdivisions", 0, 20)
    quantum = maximum_dt / (1 << subdivisions)
    if not isfinite(quantum) or quantum <= 0:
        raise AdaptiveError(
            "ADAPTIVE_SCHEDULE", "Maximum step must define a finite positive tick", policy.id
        )

    def ticks(name: str) -> int:
        actual = amount(policy, name, "second") / quantum
        if not isfinite(actual) or not 1 <= actual <= 1 << 40:
            raise AdaptiveError(
                "ADAPTIVE_SCHEDULE", f"{name} exceeds the exact tick boundary", policy.id
            )
        rounded = round(actual)
        if not isclose(actual, rounded, rel_tol=0, abs_tol=1e-6):
            raise AdaptiveError(
                "ADAPTIVE_SCHEDULE", f"{name} must align with the declared tick", policy.id
            )
        return rounded

    final_tick, sample_ticks, checkpoint_ticks = (
        ticks(name) for name in ("final_time", "sample_interval", "checkpoint_interval")
    )
    if final_tick % sample_ticks or checkpoint_ticks % sample_ticks:
        raise AdaptiveError(
            "ADAPTIVE_SCHEDULE", "Final time and checkpoints must coincide with samples", policy.id
        )
    base_cells = count(policy, "base_cells", 16, 512)
    maximum_cells = count(policy, "maximum_cells", 16, 512)
    spatial_atol = amount(policy, "spatial_atol", "kilogram_per_cubic_meter")
    temporal_atol = amount(policy, "temporal_atol", "kilogram_per_cubic_meter")
    coarsen_threshold, parent_threshold = (
        ratio(policy, "coarsen_threshold"),
        ratio(policy, "parent_threshold"),
    )
    if (
        base_cells > maximum_cells
        or min(spatial_atol, temporal_atol) <= 0
        or not 0 < coarsen_threshold < parent_threshold < 1
    ):
        raise AdaptiveError(
            "ADAPTIVE_POLICY",
            "Requires positive scales, base <= maximum cells and 0 < coarsen < parent < 1",
            policy.id,
        )
    samples, checkpoints = (
        final_tick // sample_ticks + 1,
        (final_tick + checkpoint_ticks - 1) // checkpoint_ticks + 1,
    )
    if samples > 256 or checkpoints > 16:
        raise AdaptiveError(
            "ADAPTIVE_OUTPUT_LIMIT",
            "Finite history is bounded to 256 samples and 16 checkpoints",
            policy.id,
        )
    maximum_level = count(policy, "maximum_level", 0, 5)
    maximum_epochs = count(policy, "maximum_epochs", 1, 32)
    chunk_rows = count(policy, "chunk_rows", 1, 256)
    # Sample blocks close at support changes and checkpoints. Their complete index
    # remains bounded without depending on a linear chain of earlier manifests.
    maximum_chunks = (samples + chunk_rows - 1) // chunk_rows + maximum_epochs + checkpoints - 1
    if maximum_chunks > 64:
        raise AdaptiveError(
            "ADAPTIVE_OUTPUT_LIMIT",
            "Declared output policy can exceed 64 cell-history blocks",
            policy.id,
        )
    try:
        smallest_width = length / (base_cells * (1 << maximum_level))
        numeric_range = diffusivity * maximum_dt / smallest_width**2
        total_mass = area * length * mean
    except (OverflowError, ZeroDivisionError) as exc:
        raise AdaptiveError(
            "ADAPTIVE_RANGE", "Physical scales exceed the finite float64 fragment", root.id
        ) from exc
    if not isfinite(numeric_range) or numeric_range <= 0 or not isfinite(total_mass):
        raise AdaptiveError(
            "ADAPTIVE_RANGE", "Physical scales exceed the finite float64 fragment", root.id
        )
    mesh_mode = value(policy, "mesh_mode")
    if mesh_mode not in ("adaptive", "uniform"):
        raise AdaptiveError("ADAPTIVE_POLICY", "Select adaptive or uniform mesh policy", policy.id)
    assert isinstance(mesh_mode, str)
    numerical_policy = AdaptivePolicy(
        mesh_mode,
        base_cells,
        maximum_cells,
        maximum_level,
        quantum,
        1 << subdivisions,
        final_tick,
        sample_ticks,
        checkpoint_ticks,
        spatial_atol,
        ratio(policy, "spatial_rtol"),
        temporal_atol,
        ratio(policy, "temporal_rtol"),
        coarsen_threshold,
        parent_threshold,
        count(policy, "coarsen_after", 1, 1000),
        count(policy, "dwell", 1, 1000),
        count(policy, "decision_every", 1, 64),
        count(policy, "maximum_steps", 1, 8192),
        count(policy, "maximum_rejections", 1, 1024),
        maximum_epochs,
        chunk_rows,
        count(policy, "preview_every", 1, 8192),
    )
    return AdaptiveProblem(
        root.id,
        field.id,
        region.id,
        initial.id,
        policy.id,
        space.id,
        frame.id,
        axis.id,
        str(value(axis, "name")),
        length,
        area,
        diffusivity,
        scale,
        quantity(1, "kilogram_per_cubic_meter").unit,
        mean,
        center,
        tuple(sorted(modes, key=lambda mode: mode.harmonic)),
        numerical_policy,
    )


def validate_problem(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    try:
        derive_problem(project, model)
    except AdaptiveError as exc:
        return (DomainIssue(exc.code, str(exc), exc.object_id, incomplete=True),)
    return ()
