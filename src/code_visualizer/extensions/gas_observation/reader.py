"""Resource-qualified cell identity and exact conservative-field selection."""

from code_visualizer.domain.values import QuantityValue
from code_visualizer.extensions.hybrid_gas.history import GasHistory


def cell_ids(history: GasHistory) -> tuple[str, ...]:
    support = history.interpretation
    return tuple(
        f"{support.region_id}:gas-cell:{history.series.interpretation.content_hash}:{i}"
        for i in range(support.cells)
    )


def probe(
    history: GasHistory,
    sample: int,
    cell_id: str,
    component_id: str,
    frame_id: str,
    time: QuantityValue,
) -> QuantityValue:
    support = history.interpretation
    ids = cell_ids(history)
    if cell_id not in ids or component_id not in support.field_ids or frame_id != support.frame_id:
        raise ValueError(
            "GAS_PROBE_MEANING: select a cell, component and frame of this exact resource"
        )
    selected = history.gas_slice(sample)
    if time != selected.position.time:
        raise ValueError("GAS_PROBE_TIME: explicit sample and physical time disagree")
    component = support.field_ids.index(component_id)
    return QuantityValue(
        float(selected.conserved[ids.index(cell_id), component]), support.units[component]
    )
