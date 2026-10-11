"""Static, complete gas domain registration; the kernel has no gas semantics."""

from functools import partial

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.execution.resource_interpretation import (
    ResourceDependency,
    ResourceInterpretation,
)
from code_visualizer.extensions.hybrid_gas.backend import gas_backend
from code_visualizer.extensions.hybrid_gas.calibration import (
    CALIBRATION_TYPE,
    calibration_dependencies,
)
from code_visualizer.extensions.hybrid_gas.domain import BUNDLE, gas_schema, notations
from code_visualizer.extensions.hybrid_gas.preview import PREVIEW_TYPE
from code_visualizer.extensions.hybrid_gas.problem import validate_problem
from code_visualizer.extensions.hybrid_gas.records import (
    CHECKPOINT_TYPE,
    CODEC,
    HISTORY_TYPE,
    INTERPRETATION_TYPE,
    STATISTICS_TYPE,
    TAPE_TYPE,
    TRANSFER_TYPE,
    GasCheckpoint,
    GasInterpretation,
    GasSeries,
    GasStatistics,
    GasTape,
    GasTransfer,
)
from code_visualizer.extensions.hybrid_gas.units import BUNDLE as UNITS
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle

type GasRecord = (
    GasCheckpoint | GasInterpretation | GasSeries | GasStatistics | GasTape | GasTransfer
)


def dependencies(record_type: type[GasRecord], payload: bytes) -> tuple[ResourceDependency, ...]:
    return CODEC.decode(payload, record_type).dependencies()


def hybrid_gas_bundle() -> DomainExtensionBundle:
    interpretations = (
        ResourceInterpretation(INTERPRETATION_TYPE, partial(dependencies, GasInterpretation)),
        ResourceInterpretation(HISTORY_TYPE, partial(dependencies, GasSeries)),
        ResourceInterpretation(TAPE_TYPE, partial(dependencies, GasTape)),
        ResourceInterpretation(CHECKPOINT_TYPE, partial(dependencies, GasCheckpoint)),
        ResourceInterpretation(TRANSFER_TYPE, partial(dependencies, GasTransfer)),
        ResourceInterpretation(STATISTICS_TYPE, partial(dependencies, GasStatistics)),
        ResourceInterpretation(CALIBRATION_TYPE, calibration_dependencies),
    )
    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(gas_schema(),),
        validators=(validate_problem,),
        notations=notations(),
        backends=(gas_backend(),),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(
            UNITS,
            BundleReference("foundation.fields", "1"),
            BundleReference("foundation.space", "2"),
        ),
        contracts=tuple(
            ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, kind.id, kind.version)
            for kind in (
                INTERPRETATION_TYPE,
                HISTORY_TYPE,
                TAPE_TYPE,
                CHECKPOINT_TYPE,
                TRANSFER_TYPE,
                STATISTICS_TYPE,
                CALIBRATION_TYPE,
                PREVIEW_TYPE,
            )
        ),
        resource_interpretations=interpretations,
    )
