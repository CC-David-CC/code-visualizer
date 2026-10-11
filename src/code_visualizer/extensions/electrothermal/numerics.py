"""Partitioned implicit windows over real P3 electrical and thermal solves."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from math import isfinite

from code_visualizer.domain.intentional import DomainModel
from code_visualizer.domain.transformation import OriginMap, derived_id
from code_visualizer.domain.values import QuantityValue
from code_visualizer.execution.backends import BackendContext, PreparedComputation
from code_visualizer.extensions.dc import REPRESENTATION, TRANSFORMATION
from code_visualizer.extensions.dc import identity as dc_id
from code_visualizer.extensions.dc_equations import lower_dc
from code_visualizer.extensions.electrothermal.problem import CouplingError, ElectrothermalProblem
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.foundations.equation_backend import solve_linear
from code_visualizer.extensions.foundations.equation_compiler import (
    EquationError,
    LinearSystem,
    Residual,
    Variable,
    compile_equation_family,
    real,
)
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind, UnitAlgebra
from code_visualizer.extensions.foundations.units import UnitCatalog
from code_visualizer.generation.transformation import TransformationInput

TOLERANCE = 1e-10
ENERGY_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class WindowIdentity:
    source_digest: str
    step: int
    time: float


@dataclass(frozen=True, slots=True)
class AcceptedState:
    step: int
    resistor_rise: float
    sink_rise: float
    energy_in: float = 0.0
    energy_out: float = 0.0


@dataclass(frozen=True, slots=True)
class CircuitPoint:
    window: WindowIdentity
    temperature: float
    resistance: float
    voltage: float
    current: float
    power: float
    residual: float


@dataclass(frozen=True, slots=True)
class ThermalPoint:
    window: WindowIdentity
    resistor_rise: float
    sink_rise: float


@dataclass(frozen=True, slots=True)
class CoupledTrial:
    base: AcceptedState
    iteration: int
    thermal: ThermalPoint
    electrical: CircuitPoint
    thermal_residuals: tuple[float, float]
    interface_residual: float
    normalized_residual: float
    energy_residual: float
    converged: bool


class WindowCancelled(Exception):
    """The caller retains the immutable accepted base and its existing prefix."""


class CoupledSolver:
    def __init__(
        self, snapshot: PreparedComputation, problem: ElectrothermalProblem, source_digest: str
    ):
        import numpy
        import sympy  # type: ignore[import-untyped]

        self.problem, self.source_digest = problem, source_digest
        self.numerical_identity = (
            f"numpy={numpy.__version__};sympy={sympy.__version__};float64-le;partitioned-be-v1"
        )
        model = snapshot.project.domain_workspace.model(problem.circuit_model_id)
        if model is None:
            raise CouplingError(
                "COUPLING_CIRCUIT", "Circuit is absent from frozen input", problem.id
            )
        derived = lower_dc(
            TransformationInput(
                snapshot.project,
                model,
                REPRESENTATION,
                model,
                OriginMap(snapshot.project.id, snapshot.project.revision),
            )
        )
        assert isinstance(derived.value, DomainModel)
        self.electrical_origins = derived.origins
        self.resistance_id = derived_id(TRANSFORMATION.key, problem.resistor_id, "resistance")
        self.family = compile_equation_family(
            derived.value, snapshot.dependency_models, (self.resistance_id,)
        )
        current_id = derived_id(TRANSFORMATION.key, problem.resistor_id, "current")
        self.current_index = next(
            i for i, item in enumerate(self.family.nominal.variables) if item.id == current_id
        )
        unit = self.family.nominal.variables[self.current_index].scale.unit
        algebra = UnitAlgebra(UnitCatalog.from_models(snapshot.dependency_models))
        self.current_factor = real(
            algebra.convert(QuantityValue(1, unit), quantity(1, "ampere").unit).magnitude
        )
        resistor = model.node(problem.resistor_id)
        assert resistor is not None
        potentials = []
        for side in ("positive", "negative"):
            terminal = model.node(resistor.child_ids(dc_id("Resistor", side))[0])
            assert terminal is not None
            net_id = terminal.reference_ids(dc_id("Terminal", "net"))[0]
            potential_id = derived_id(TRANSFORMATION.key, net_id, "potential")
            index = next(
                i for i, item in enumerate(self.family.nominal.variables) if item.id == potential_id
            )
            variable_unit = self.family.nominal.variables[index].scale.unit
            factor = real(
                algebra.convert(QuantityValue(1, variable_unit), quantity(1, "volt").unit).magnitude
            )
            potentials.append((index, factor))
        self.potentials = tuple(potentials)

    def initial(self) -> AcceptedState:
        p = self.problem
        return AcceptedState(
            0,
            p.initial_resistor_temperature - p.ambient_temperature,
            p.initial_sink_temperature - p.ambient_temperature,
        )

    def electrical(self, window: WindowIdentity, temperature: float) -> CircuitPoint:
        p = self.problem
        resistance = p.resistance * (1 + p.alpha * (temperature - p.reference_temperature))
        if not 200 <= temperature <= 1000 or not isfinite(resistance) or resistance <= 0:
            raise CouplingError(
                "COUPLING_RESISTANCE", "Trial temperature/resistance outside fragment", p.law_id
            )
        try:
            system = self.family.bind({self.resistance_id: quantity(resistance, "ohm")})
            solution = solve_linear(system)
        except EquationError as exc:
            origins = self.electrical_origins.sources(exc.semantic_id)
            raise CouplingError(
                exc.code, str(exc), origins[0] if origins else p.resistor_id
            ) from exc
        current = solution.values[self.current_index] * self.current_factor
        # Independently solved terminal potentials provide the oriented voltage;
        # constitutive power is checked against it, not used to define it.
        positive, negative = self.potentials
        voltage = (
            solution.values[positive[0]] * positive[1] - solution.values[negative[0]] * negative[1]
        )
        power = voltage * current
        if abs(power - current * current * resistance) / p.power_scale > TOLERANCE:
            raise CouplingError("COUPLING_POWER_BALANCE", "VI and I²R do not agree", p.resistor_id)
        return CircuitPoint(
            window,
            temperature,
            resistance,
            voltage,
            current,
            power,
            max(abs(item) for item in solution.normalized_residuals),
        )

    def thermal(self, window: WindowIdentity, base: AcceptedState, power: float) -> ThermalPoint:
        p = self.problem
        cr, cs, g, h, dt = (
            p.resistor_capacity,
            p.sink_capacity,
            p.contact_conductance,
            p.ambient_conductance,
            p.dt,
        )
        matrix = ((cr / dt + g, -g), (-g, cs / dt + g + h))
        right = (cr * base.resistor_rise / dt + power, cs * base.sink_rise / dt)
        variables = tuple(
            Variable(node, node, quantity(p.temperature_scale, "kelvin"), QuantityKind.INTERVAL)
            for node in (p.resistor_body_id, p.sink_body_id)
        )
        residuals = tuple(
            Residual(
                node + ":balance",
                node,
                "Thermal power balance",
                quantity(p.power_scale, "watt"),
                p.power_scale,
                1.0,
                (node, p.contact_id, p.ambient_id),
            )
            for node in (p.resistor_body_id, p.sink_body_id)
        )
        try:
            values = solve_linear(
                LinearSystem(p.id, variables, residuals, matrix, right, 1e-12, TOLERANCE, 1e12)
            ).values
        except EquationError as exc:
            raise CouplingError(exc.code, str(exc), p.contact_id) from exc
        if any(not 200 <= p.ambient_temperature + v <= 1000 for v in values):
            raise CouplingError(
                "COUPLING_RANGE", "Thermal trial leaves supported temperature range", p.contact_id
            )
        return ThermalPoint(window, values[0], values[1])

    def trials(self, base: AcceptedState, context: BackendContext) -> Iterator[CoupledTrial]:
        p = self.problem
        window = WindowIdentity(self.source_digest, base.step + 1, p.time(base.step + 1))
        guess = base.resistor_rise

        def boundary() -> None:
            if context.cancellation_requested:
                raise WindowCancelled

        boundary()
        # Thermal-first begins with the previous guess's circuit. Electrical-first
        # evaluates it at the start of each trial. Both solve the same fixed point.
        previous = self.electrical(window, p.ambient_temperature + guess)
        for iteration in range(1, p.max_iterations + 1):
            boundary()
            supplied = (
                self.electrical(window, p.ambient_temperature + guess)
                if p.evaluation_order == "electrical_first"
                else previous
            )
            boundary()
            thermal = self.thermal(window, base, supplied.power)
            boundary()
            final = self.electrical(window, p.ambient_temperature + thermal.resistor_rise)
            boundary()
            if thermal.window != window or supplied.window != window or final.window != window:
                raise CouplingError(
                    "COUPLING_ENDPOINT", "Mixed source/window/time in candidate", p.exchange_ids[0]
                )
            if final.temperature != p.ambient_temperature + thermal.resistor_rise:
                raise CouplingError(
                    "COUPLING_ENDPOINT",
                    "Circuit temperature differs from endpoint",
                    p.exchange_ids[0],
                )
            x, y = thermal.resistor_rise, thermal.sink_rise
            contact = p.contact_conductance * (x - y)
            loss = p.ambient_conductance * y
            thermal_residuals = (
                p.resistor_capacity * (x - base.resistor_rise) / p.dt - final.power + contact,
                p.sink_capacity * (y - base.sink_rise) / p.dt - contact + loss,
            )
            interface = final.power - supplied.power
            energy = (
                p.resistor_capacity * (x - base.resistor_rise)
                + p.sink_capacity * (y - base.sink_rise)
                - p.dt * (final.power - loss)
            )
            normalized = max(
                abs(x - guess) / p.temperature_scale,
                abs(interface) / p.power_scale,
                *(abs(v) / p.power_scale for v in thermal_residuals),
                abs(energy) / p.energy_scale,
                final.residual,
            )
            if not all(isfinite(v) for v in (normalized, energy, final.power, final.current)):
                raise CouplingError("COUPLING_NUMERIC_RANGE", "Nonfinite candidate", p.id)
            trial = CoupledTrial(
                base,
                iteration,
                thermal,
                final,
                thermal_residuals,
                interface,
                normalized,
                energy,
                normalized <= TOLERANCE and abs(energy) <= ENERGY_TOLERANCE,
            )
            yield trial
            if trial.converged:
                return
            # Only the iteration guess changes. Every thermal solve receives the
            # identical full base; accepted energy/time/cursors have not advanced.
            guess, previous = x, final
        raise CouplingError(
            "COUPLING_NOT_CONVERGED", "The authored iteration budget was exhausted", p.policy_id
        )

    def accept(self, trial: CoupledTrial) -> AcceptedState:
        if not trial.converged:
            raise CouplingError(
                "COUPLING_REJECTED", "A rejected trial cannot advance state", self.problem.id
            )
        p = self.problem
        return AcceptedState(
            trial.thermal.window.step,
            trial.thermal.resistor_rise,
            trial.thermal.sink_rise,
            trial.base.energy_in + p.dt * trial.electrical.power,
            trial.base.energy_out + p.dt * p.ambient_conductance * trial.thermal.sink_rise,
        )
