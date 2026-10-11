"""Optional CAD interpretation of resources; no native imports during authoring."""

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.extensions.cad.domain import BUNDLE, cad_schema, notations
from code_visualizer.extensions.cad.resources import BREP, MEASUREMENT, MESH, REGION
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def cad_bundle() -> DomainExtensionBundle:
    from code_visualizer.extensions.cad.backend import backends

    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(cad_schema(),),
        notations=notations(),
        backends=backends(),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(
            BundleReference("code_visualizer.cad.units", "1"),
            BundleReference("foundation.math", "2"),
            BundleReference("code_visualizer.computation", "2"),
        ),
        contracts=(
            *(
                ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, t.id, t.version)
                for t in (BREP, MESH, MEASUREMENT, REGION)
            ),
        ),
    )
