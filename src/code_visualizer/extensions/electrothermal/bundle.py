"""Complete electrothermal contribution at the existing composition boundary."""

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.execution.resource_interpretation import ResourceInterpretation
from code_visualizer.extensions.channels.domain import BUNDLE as CHANNELS
from code_visualizer.extensions.dc import BUNDLE as DC
from code_visualizer.extensions.electrothermal.backend import electrothermal_backend
from code_visualizer.extensions.electrothermal.checkpoint import (
    CHECKPOINT_TYPE,
    checkpoint_dependencies,
)
from code_visualizer.extensions.electrothermal.domain import (
    BUNDLE,
    electrothermal_schema,
    notations,
)
from code_visualizer.extensions.electrothermal.problem import validate_problem
from code_visualizer.extensions.electrothermal.units import BUNDLE as UNITS
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def electrothermal_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        "1",
        schemas=(electrothermal_schema(),),
        validators=(validate_problem,),
        notations=notations(),
        backends=(electrothermal_backend(),),
        required_bundles=(DC, UNITS, CHANNELS),
        publication=FIRST_PARTY_PUBLICATION,
        contracts=(
            ContractDefinition(
                ContractKind.RESOURCE_LOGICAL_TYPE, CHECKPOINT_TYPE.id, CHECKPOINT_TYPE.version
            ),
        ),
        resource_interpretations=(
            ResourceInterpretation(CHECKPOINT_TYPE, checkpoint_dependencies),
        ),
    )
