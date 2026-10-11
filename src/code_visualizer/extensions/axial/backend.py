"""One normal computation consumes a completed CAD resource and publishes equilibrium."""

from code_visualizer.domain.computation import BackendDefinition
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
)
from code_visualizer.domain.intentional import DomainModel
from code_visualizer.execution.backends import (
    BackendResult,
    PreparedComputation,
    ProducedResource,
    RegisteredBackend,
)
from code_visualizer.extensions.axial.domain import BACKEND_ID, REPRESENTATION, SCHEMA_ID, quantity
from code_visualizer.extensions.axial.problem import AxialError, derive_problem
from code_visualizer.extensions.axial.records import (
    CODEC,
    MAPPING_TYPE,
    RESULT_TYPE,
    AxialResult,
    amount,
)
from code_visualizer.extensions.fields.arrays import array_resource
from code_visualizer.extensions.foundations.equation_compiler import EquationError
from code_visualizer.persistence.computation_resources import produced_descriptor


def axial_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Verified CAD prism: axial equilibrium",
            REPRESENTATION,
            SCHEMA_ID,
            "1",
            "Real linear element assembly with fixed support and signed axial load.",
        ),
        execute=execute,
        file_backed_inputs=True,
    )


def execute(snapshot: PreparedComputation) -> BackendResult:
    try:
        return solve(snapshot)
    except AxialError as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic(exc.code, str(exc), (exc.object_id,)),),
        )
    except EquationError as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic(exc.code, str(exc), (exc.semantic_id,)),),
        )
    except ImportError as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic("SCIENCE_DEPENDENCY_MISSING", str(exc)),),
        )
    except (ValueError, KeyError, FloatingPointError, OverflowError) as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(EvidenceDiagnostic("AXIAL_INPUT_OR_NUMERIC", str(exc)),),
        )


def solve(snapshot: PreparedComputation) -> BackendResult:
    import numpy as np

    from code_visualizer.extensions.axial.assembly import BarElement, solve_bar
    from code_visualizer.extensions.axial.geometry import derive_mapping

    if not isinstance(snapshot.value, DomainModel) or snapshot.request.configuration:
        raise ValueError("Axial computation requires authored domain parameters")
    problem = derive_problem(snapshot.project, snapshot.value)
    inputs = {resource.descriptor.reference: resource for resource in snapshot.resources}
    if problem.geometry not in inputs:
        raise AxialError(
            "AXIAL_GEOMETRY_RESOURCE", "The declared BREP input is unavailable", problem.geometry_id
        )
    mapping = derive_mapping(inputs[problem.geometry], problem, snapshot.input_digest)
    length, area, origin = (
        amount(mapping.length, "meter"),
        amount(mapping.area, "square_meter"),
        amount(mapping.origin, "meter"),
    )
    elements = tuple(
        BarElement(length / (problem.nodes - 1), area, problem.young_modulus)
        for _ in range(problem.nodes - 1)
    )
    result = solve_bar(elements, problem.force, problem.id, problem.origins)
    mapping_resource = ProducedResource(
        "axial:mapping",
        CODEC.encode(mapping),
        "application/json",
        problem.origins,
        "Verified material geometry → axial support",
        logical_type=MAPPING_TYPE,
    )
    arrays = tuple(
        array_resource(
            "axial:" + name, np.asarray(data, dtype=np.float64), unit=quantity(1, unit).unit
        )
        for name, data, unit in (
            ("coordinates", np.linspace(origin, origin + length, problem.nodes), "meter"),
            ("displacement", result.displacement, "meter"),
            ("stress", result.stress, "pascal"),
            ("element_force", result.element_force, "newton"),
            ("stiffness", result.stiffness, "newton_per_meter"),
            ("right", result.right, "newton"),
        )
    )
    references = tuple(produced_descriptor(resource).reference for resource in arrays)
    record = AxialResult(
        source_digest=snapshot.input_digest,
        mapping=produced_descriptor(mapping_resource).reference,
        nodes=problem.nodes,
        coordinates=references[0],
        displacement=references[1],
        stress=references[2],
        element_force=references[3],
        stiffness=references[4],
        right=references[5],
        young_modulus=quantity(problem.young_modulus, "pascal"),
        applied_force=quantity(problem.force, "newton"),
        reaction=quantity(result.reaction, "newton"),
        strain_energy=quantity(result.energy, "joule"),
        normalized_residual=max(abs(v) for v in result.solution.normalized_residuals),
        condition=result.solution.condition,
        numerical_identity="numpy=" + np.__version__ + ";float64-le;linear-axial-v1",
        semantic_ids=problem.origins,
    )
    observations = tuple(
        EvidenceObservation(name, origins, quantity(value, unit), label, index)
        for index, (name, label, value, unit, origins) in enumerate(
            (
                (
                    "axial:extension",
                    "Axial end displacement",
                    result.displacement[-1],
                    "meter",
                    (problem.geometry_id, problem.load_id),
                ),
                (
                    "axial:stress",
                    "Signed axial stress",
                    result.stress[-1],
                    "pascal",
                    (problem.material_id, problem.load_id),
                ),
                (
                    "axial:reaction",
                    "Fixed-end axial reaction",
                    result.reaction,
                    "newton",
                    (problem.support_id,),
                ),
                ("axial:energy", "Elastic strain energy", result.energy, "joule", problem.origins),
            )
        )
    )
    return BackendResult(
        observations=observations,
        produced_resources=(
            ProducedResource(
                "axial:result",
                CODEC.encode(record),
                "application/json",
                problem.origins,
                "Small-strain axial equilibrium of the verified solid prism",
                logical_type=RESULT_TYPE,
                dependencies=(mapping_resource, *arrays),
            ),
        ),
    )
