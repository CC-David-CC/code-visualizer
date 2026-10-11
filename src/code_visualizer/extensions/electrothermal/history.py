"""One common endpoint interprets temperature, circuit and energy channels."""

from __future__ import annotations

from typing import TYPE_CHECKING

from code_visualizer.execution.backends import ProducedResource
from code_visualizer.extensions.channels.codec import CODEC
from code_visualizer.extensions.channels.records import (
    INTERPRETATION_TYPE,
    SERIES_TYPE,
    Channel,
    ChannelChunk,
    ChannelInterpretation,
    ChannelSeries,
)
from code_visualizer.extensions.electrothermal.numerics import (
    AcceptedState,
    CircuitPoint,
    CoupledTrial,
)
from code_visualizer.extensions.electrothermal.problem import ElectrothermalProblem
from code_visualizer.extensions.electrothermal.units import quantity
from code_visualizer.extensions.foundations.series_writer import NumericSeriesWriter
from code_visualizer.extensions.foundations.unit_algebra import QuantityKind
from code_visualizer.persistence.computation_resources import produced_descriptor

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

    from code_visualizer.extensions.channels.history import ChannelHistory


def interpretation(problem: ElectrothermalProblem) -> ChannelInterpretation:
    p = problem
    definitions = (
        ("resistor_temperature", "Resistor temperature", p.resistor_body_id, "kelvin", "point"),
        ("sink_temperature", "Sink temperature", p.sink_body_id, "kelvin", "point"),
        ("resistance", "Resistance", p.resistor_id, "ohm", "linear"),
        ("voltage", "Resistor voltage", p.resistor_id, "volt", "linear"),
        ("current", "Resistor current", p.resistor_id, "ampere", "linear"),
        ("power", "Joule power", p.resistor_id, "watt", "linear"),
        ("resistor_contact_out", "Heat leaving resistor", p.resistor_body_id, "watt", "linear"),
        ("sink_contact_out", "Heat leaving sink toward resistor", p.sink_body_id, "watt", "linear"),
        ("ambient_loss", "Heat to ambient", p.ambient_id, "watt", "linear"),
        ("energy_in", "Input energy", p.source_id, "joule", "linear"),
        ("energy_out", "Ambient energy", p.ambient_id, "joule", "linear"),
        ("stored_energy", "Thermal energy change", p.id, "joule", "linear"),
        ("energy_imbalance", "Input minus loss minus stored", p.id, "joule", "linear"),
        ("resistor_residual", "Resistor power residual", p.resistor_body_id, "watt", "linear"),
        ("sink_residual", "Sink power residual", p.sink_body_id, "watt", "linear"),
        ("interface_residual", "Coupling power residual", p.exchange_ids[0], "watt", "linear"),
        ("normalized_residual", "Normalized convergence residual", p.id, "one", "linear"),
    )
    return ChannelInterpretation(
        p.id,
        tuple(
            Channel(
                p.id + ":" + key, label, (node,), node, quantity(1, unit).unit, QuantityKind(kind)
            )
            for key, label, node, unit, kind in definitions
        ),
        quantity(1).unit,
    )


def values(
    problem: ElectrothermalProblem,
    state: AcceptedState,
    circuit: CircuitPoint,
    trial: CoupledTrial | None = None,
) -> NDArray[np.float64]:
    import numpy as np

    p = problem
    contact = p.contact_conductance * (state.resistor_rise - state.sink_rise)
    energy = p.resistor_capacity * (
        state.resistor_rise - p.initial_resistor_temperature + p.ambient_temperature
    ) + p.sink_capacity * (state.sink_rise - p.initial_sink_temperature + p.ambient_temperature)
    if circuit.window.step != state.step or circuit.window.time != p.time(state.step):
        raise ValueError("A published circuit and thermal state must share one accepted window")
    return np.asarray(
        (
            state.resistor_rise + p.ambient_temperature,
            state.sink_rise + p.ambient_temperature,
            circuit.resistance,
            circuit.voltage,
            circuit.current,
            circuit.power,
            contact,
            -contact,
            p.ambient_conductance * state.sink_rise,
            state.energy_in,
            state.energy_out,
            energy,
            state.energy_in - state.energy_out - energy,
            *(trial.thermal_residuals if trial else (0.0, 0.0)),
            trial.interface_residual if trial else 0.0,
            trial.normalized_residual if trial else 0.0,
        ),
        dtype=np.float64,
    )


class HistoryWriter(NumericSeriesWriter[ChannelChunk, ChannelSeries]):
    def __init__(
        self,
        problem: ElectrothermalProblem,
        source_digest: str,
        previous: ChannelHistory | None = None,
    ):
        self.meaning = interpretation(problem)
        record = ProducedResource(
            "interpretation",
            CODEC.encode(self.meaning),
            "application/json",
            logical_type=INTERPRETATION_TYPE,
        )
        super().__init__(
            previous.series.interpretation if previous else produced_descriptor(record).reference,
            source_digest,
            len(self.meaning.channels),
            problem.chunk_rows,
            lambda step: quantity(problem.time(step)),
            ChannelChunk,
            ChannelSeries,
            CODEC.encode,
            SERIES_TYPE,
            problem.origins,
            "Accepted coupled window",
            staged=() if previous else (record,),
            prefix=previous.root if previous else None,
            prefix_last=previous.series.last if previous else None,
        )
