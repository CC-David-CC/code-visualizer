"""First physical field experiment, composed at the ordinary static boundary."""

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.execution.resource_interpretation import ResourceInterpretation
from code_visualizer.extensions.diffusion.backend import diffusion_backend
from code_visualizer.extensions.diffusion.domain import BUNDLE, diffusion_schema, notations
from code_visualizer.extensions.diffusion.problem import validate_problem
from code_visualizer.extensions.fields.codec import checkpoint_dependencies
from code_visualizer.extensions.fields.domain import BUNDLE as FIELDS
from code_visualizer.extensions.fields.records import CHECKPOINT_TYPE
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def diffusion_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(diffusion_schema(),),
        validators=(validate_problem,),
        notations=notations(),
        backends=(diffusion_backend(),),
        required_bundles=(FIELDS,),
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
