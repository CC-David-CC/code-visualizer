"""Immutable bounded model-selection decisions, never authored edits."""

from dataclasses import dataclass, replace
from math import isfinite


@dataclass(frozen=True, slots=True)
class ModelPolicy:
    activation_threshold: float
    return_threshold: float
    low_opportunities: int
    minimum_dwell_ticks: int
    maximum_switches: int = 2

    def __post_init__(self) -> None:
        if (
            not isfinite(self.activation_threshold)
            or not isfinite(self.return_threshold)
            or not 0 <= self.return_threshold < self.activation_threshold <= 0.05
            or type(self.low_opportunities) is not int
            or not 1 <= self.low_opportunities <= 64
            or type(self.minimum_dwell_ticks) is not int
            or not 0 <= self.minimum_dwell_ticks <= 400000
            or type(self.maximum_switches) is not int
            or not 1 <= self.maximum_switches <= 8
        ):
            raise ValueError("GAS_MODEL_POLICY: invalid hysteresis/dwell/switch budget")


@dataclass(frozen=True, slots=True)
class ModelState:
    particle: bool = False
    low_count: int = 0
    changed_tick: int = 0
    switches: int = 0
    last_decision_tick: int = -1

    def __post_init__(self) -> None:
        if type(self.particle) is not bool or any(
            type(v) is not int
            for v in (self.low_count, self.changed_tick, self.switches, self.last_decision_tick)
        ):
            raise ValueError("GAS_CONTROLLER: invalid typed model state")
        if (
            not 0 <= self.low_count <= 512
            or not 0 <= self.changed_tick <= 400000
            or not 0 <= self.switches <= 8
            or not -1 <= self.last_decision_tick <= 400000
        ):
            raise ValueError("GAS_CONTROLLER: model state exceeds its bounded counters")


@dataclass(frozen=True, slots=True)
class ModelDecision:
    before: ModelState
    after: ModelState
    tick: int
    indicator: float
    action: str
    reason: str


def decide(
    policy: ModelPolicy,
    state: ModelState,
    tick: int,
    indicator: float,
    *,
    return_ready: bool,
) -> ModelDecision:
    if type(tick) is not int or tick <= state.last_decision_tick or tick < state.changed_tick:
        raise ValueError("GAS_DECISION_TIME: model decisions require advancing accepted ticks")
    if not isfinite(indicator) or indicator < 0:
        raise ValueError("GAS_INDICATOR: invalid gradient Knudsen estimate")
    low = state.low_count + 1 if indicator < policy.return_threshold else 0
    after = replace(state, low_count=low, last_decision_tick=tick)
    action, reason = "retain", "hysteresis"
    if not state.particle and indicator > policy.activation_threshold:
        action, reason = "activate", "gradient_threshold"
    elif state.particle and low >= policy.low_opportunities:
        if tick - state.changed_tick < policy.minimum_dwell_ticks:
            reason = "minimum_dwell"
        elif not return_ready:
            reason = "insufficient_return_statistics"
        else:
            action, reason = "return", "coarse_compatible"
    if action != "retain":
        if state.switches >= policy.maximum_switches:
            action, reason = "reject", "switch_budget"
        else:
            after = replace(
                after,
                particle=action == "activate",
                low_count=0,
                switches=state.switches + 1,
                changed_tick=tick,
            )
    return ModelDecision(state, after, tick, indicator, action, reason)
