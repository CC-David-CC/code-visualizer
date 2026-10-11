"""NumPy linear solving over the shared checked mathematical boundary."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from code_visualizer.domain.computation import BackendCapabilities, BackendDefinition
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
)
from code_visualizer.domain.intentional import DomainModel
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue
from code_visualizer.execution.backends import (
    BackendResult,
    PreparedComputation,
    ProducedResource,
    RegisteredBackend,
)
from code_visualizer.extensions.foundations.equation_compiler import (
    EquationError,
    LinearSystem,
    compile_equations,
    real,
)
from code_visualizer.extensions.foundations.equations import BACKEND_ID, REPRESENTATION, RESULT_TYPE
from code_visualizer.extensions.foundations.math import SCHEMA_ID
from code_visualizer.persistence.values import canonical_value_to_data


@dataclass(frozen=True, slots=True)
class LinearSolution:
    values: tuple[float, ...]
    residuals: tuple[float, ...]
    normalized_residuals: tuple[float, ...]
    condition: float
    rank: int
    scaled_matrix: tuple[tuple[float, ...], ...]
    scaled_right: tuple[float, ...]


def solve_linear(system: LinearSystem) -> LinearSolution:
    try:
        import numpy as np
    except ImportError as exc:
        raise EquationError(
            "SCIENCE_DEPENDENCY_MISSING",
            "Install the science extra to solve equations",
            system.request_id,
        ) from exc
    matrix, rhs = np.asarray(system.matrix, dtype=float), np.asarray(system.right, dtype=float)
    columns = np.asarray([real(item.scale.magnitude) for item in system.variables])
    rows = np.asarray([item.base_scale for item in system.residuals])
    with np.errstate(over="raise", divide="raise", invalid="raise"):
        try:
            scaled, right = matrix * columns[None, :] / rows[:, None], rhs / rows
            if not np.isfinite(scaled).all() or not np.isfinite(right).all():
                raise FloatingPointError("The normalized system is not finite")
            singular = np.linalg.svd(scaled, compute_uv=False)
            threshold = system.rank_tolerance * (float(singular[0]) if len(singular) else 0)
            rank = int(np.count_nonzero(singular > threshold))
            # The augmented column is normalized too. The same absolute threshold
            # compares the two ranks; a relative threshold on each matrix separately
            # would allow a large RHS to hide an inconsistent relation.
            augmented = np.linalg.svd(np.column_stack((scaled, right)), compute_uv=False)
            augmented_rank = int(
                np.count_nonzero(augmented > max(threshold, system.rank_tolerance))
            )
            if augmented_rank > rank:
                raise EquationError(
                    "EQUATION_INCONSISTENT",
                    f"Inconsistent relations: matrix rank {rank}, augmented rank {augmented_rank}",
                    system.request_id,
                )
            count = len(system.variables)
            if rank < count:
                code = (
                    "EQUATION_UNDERDETERMINED"
                    if len(system.residuals) < count
                    else "EQUATION_SINGULAR"
                )
                raise EquationError(
                    code,
                    f"No unique solution: rank {rank} for {count} unknowns "
                    f"and {len(system.residuals)} relations",
                    system.request_id,
                )
            condition = float(singular[0] / singular[-1])
            if not math.isfinite(condition) or condition > system.condition_limit:
                raise EquationError(
                    "EQUATION_ILL_CONDITIONED",
                    f"Scaled condition {condition:.6g} exceeds {system.condition_limit:.6g}",
                    system.request_id,
                )
            if scaled.shape[0] == scaled.shape[1]:
                result = np.linalg.solve(scaled, right)
            else:
                # Full column rank and consistent relations have already been proved.
                # This is not a minimum-norm answer to an underdetermined problem.
                result = np.linalg.lstsq(scaled, right, rcond=system.rank_tolerance)[0]
            values = result * columns
            physical = matrix @ values - rhs
            normalized = physical / rows
            if not np.isfinite(values).all() or not np.isfinite(normalized).all():
                raise FloatingPointError("The solve produced nonfinite numbers")
            if float(np.max(np.abs(normalized))) > system.residual_tolerance:
                raise EquationError(
                    "EQUATION_RESIDUAL",
                    "The solution violates the declared normalized residual tolerance",
                    system.request_id,
                )
            return LinearSolution(
                tuple(float(item) for item in values),
                tuple(
                    float(value / row.unit_scale)
                    for value, row in zip(physical, system.residuals, strict=True)
                ),
                tuple(float(item) for item in normalized),
                condition,
                rank,
                tuple(tuple(float(value) for value in row) for row in scaled),
                tuple(float(value) for value in right),
            )
        except (FloatingPointError, np.linalg.LinAlgError, OverflowError) as exc:
            raise EquationError("EQUATION_NUMERIC_RANGE", str(exc), system.request_id) from exc


def solution_result(system: LinearSystem, solution: LinearSolution) -> BackendResult:
    import numpy
    import pint
    import sympy  # type: ignore[import-untyped]

    observations: list[EvidenceObservation] = []
    variables: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    for variable, value in zip(system.variables, solution.values, strict=True):
        quantity = QuantityValue(value, variable.scale.unit)
        observations.append(
            EvidenceObservation(
                variable.id + ":solution",
                (variable.id,),
                quantity,
                variable.name,
                len(observations),
            )
        )
        variables.append(
            {
                "id": variable.id,
                "name": variable.name,
                "kind": variable.kind.value,
                "scale": canonical_value_to_data(variable.scale),
                "value": canonical_value_to_data(quantity),
            }
        )
    for row, physical, normalized in zip(
        system.residuals, solution.residuals, solution.normalized_residuals, strict=True
    ):
        quantity = QuantityValue(physical, row.scale.unit)
        observations.append(
            EvidenceObservation(
                row.id + ":residual",
                row.origins,
                quantity,
                row.name + " residual",
                len(observations),
            )
        )
        observations.append(
            EvidenceObservation(
                row.id + ":normalized",
                row.origins,
                normalized,
                row.name + " normalized residual",
                len(observations),
            )
        )
        residuals.append(
            {
                "id": row.id,
                "equation_id": row.equation_id,
                "name": row.name,
                "scale": canonical_value_to_data(row.scale),
                "base_scale": row.base_scale,
                "value": canonical_value_to_data(quantity),
                "normalized": normalized,
                "origins": list(row.origins),
            }
        )
    report = {
        "format": RESULT_TYPE,
        "version": "1",
        "request_id": system.request_id,
        "backend": {"id": BACKEND_ID, "version": "1"},
        "libraries": {
            "numpy": numpy.__version__,
            "sympy": sympy.__version__,
            "pint": pint.__version__,
        },
        "variables": variables,
        "residuals": residuals,
        "coefficient_matrix": system.matrix,
        "right_hand_side": system.right,
        "normalized_matrix": solution.scaled_matrix,
        "normalized_right": solution.scaled_right,
        "rank": solution.rank,
        "condition": solution.condition,
        "policy": {
            "rank_tolerance": system.rank_tolerance,
            "residual_tolerance": system.residual_tolerance,
            "condition_limit": system.condition_limit,
        },
    }
    resource = ProducedResource(
        system.request_id + ":solution-report",
        json.dumps(
            report, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8"),
        "application/json",
        (system.request_id,),
        "Checked equation solution and residuals",
        logical_type=ResourceLogicalTypeReference(RESULT_TYPE, "1"),
    )
    return BackendResult(observations=tuple(observations), produced_resources=(resource,))


def evaluate_equations(prepared: PreparedComputation) -> BackendResult:
    try:
        if not isinstance(prepared.value, DomainModel):
            raise EquationError(
                "EQUATION_INPUT", "The equation backend requires a mathematical domain model"
            )
        configuration = {item.name: item.value for item in prepared.request.configuration}
        if set(configuration) - {"request_id"} or (
            "request_id" in configuration
            and (
                not isinstance(configuration["request_id"], str) or not configuration["request_id"]
            )
        ):
            raise EquationError(
                "EQUATION_CONFIGURATION",
                "Optional request_id must identify one canonical solve request",
                prepared.value.id,
            )
        request_id = configuration.get("request_id")
        assert request_id is None or isinstance(request_id, str)
        system = compile_equations(prepared.value, prepared.dependency_models, request_id)
        return solution_result(system, solve_linear(system))
    except EquationError as exc:
        available = {node.id for model in prepared.dependency_models for node in model.nodes}
        if isinstance(prepared.value, DomainModel):
            available.update(node.id for node in prepared.value.nodes)
            available.add(prepared.value.id)
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    exc.code, str(exc), (exc.semantic_id,) if exc.semantic_id in available else ()
                ),
            ),
        )


def equation_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Unit-aware linear equations",
            REPRESENTATION,
            SCHEMA_ID,
            "2",
            "Checked scalar relations, explicit scales and numerical diagnostics.",
            capabilities=BackendCapabilities(deterministic=True),
        ),
        evaluate_equations,
    )
