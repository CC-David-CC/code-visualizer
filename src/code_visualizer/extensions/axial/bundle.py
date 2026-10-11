"""Complete optional axial capability; static registration does not import OCP."""

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.execution.resource_interpretation import ResourceInterpretation
from code_visualizer.extensions.axial.backend import axial_backend
from code_visualizer.extensions.axial.domain import BUNDLE, axial_schema, notations
from code_visualizer.extensions.axial.problem import validate_problem
from code_visualizer.extensions.axial.records import (
    MAPPING_TYPE,
    RESULT_TYPE,
    mapping_dependencies,
    result_dependencies,
)
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def axial_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        "1",
        schemas=(axial_schema(),),
        validators=(validate_problem,),
        notations=notations(),
        backends=(axial_backend(),),
        required_bundles=(
            BundleReference("code_visualizer.cad", "1"),
            BundleReference("foundation.fields", "1"),
        ),
        publication=FIRST_PARTY_PUBLICATION,
        contracts=tuple(
            ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, kind.id, kind.version)
            for kind in (MAPPING_TYPE, RESULT_TYPE)
        ),
        resource_interpretations=(
            ResourceInterpretation(MAPPING_TYPE, mapping_dependencies),
            ResourceInterpretation(RESULT_TYPE, result_dependencies),
        ),
    )
