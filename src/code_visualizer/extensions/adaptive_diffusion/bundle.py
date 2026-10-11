"""Canonical adaptive diffusion definitions and their bounded validity contract."""

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.execution.resource_interpretation import ResourceInterpretation
from code_visualizer.extensions.adaptive_diffusion.backend import adaptive_backend
from code_visualizer.extensions.adaptive_diffusion.checkpoint import (
    CHECKPOINT_TYPE,
    checkpoint_dependencies,
)
from code_visualizer.extensions.adaptive_diffusion.domain import BUNDLE, adaptive_schema, notations
from code_visualizer.extensions.adaptive_diffusion.initialization import (
    INITIALIZATION_TYPE,
    initialization_dependencies,
)
from code_visualizer.extensions.adaptive_diffusion.problem import validate_problem
from code_visualizer.extensions.adaptive_fields.domain import BUNDLE as FIELDS
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def adaptive_diffusion_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(adaptive_schema(),),
        validators=(validate_problem,),
        notations=notations(),
        backends=(adaptive_backend(),),
        required_bundles=(FIELDS,),
        publication=FIRST_PARTY_PUBLICATION,
        contracts=(
            ContractDefinition(
                ContractKind.RESOURCE_LOGICAL_TYPE, CHECKPOINT_TYPE.id, CHECKPOINT_TYPE.version
            ),
            ContractDefinition(
                ContractKind.RESOURCE_LOGICAL_TYPE,
                INITIALIZATION_TYPE.id,
                INITIALIZATION_TYPE.version,
            ),
        ),
        resource_interpretations=(
            ResourceInterpretation(CHECKPOINT_TYPE, checkpoint_dependencies),
            ResourceInterpretation(INITIALIZATION_TYPE, initialization_dependencies),
        ),
    )
