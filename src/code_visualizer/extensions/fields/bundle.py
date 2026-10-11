"""Complete, statically registered field interpretation contribution."""

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.execution.resource_interpretation import ResourceInterpretation
from code_visualizer.extensions.fields.codec import (
    interpretation_dependencies,
    series_dependencies,
    support_dependencies,
)
from code_visualizer.extensions.fields.domain import BUNDLE, field_schema, notations
from code_visualizer.extensions.fields.probe import probe_backend
from code_visualizer.extensions.fields.records import (
    ARRAY_TYPE,
    INTERPRETATION_TYPE,
    PREVIEW_TYPE,
    SERIES_TYPE,
    SUPPORT_TYPE,
)
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def fields_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        "1",
        schemas=(field_schema(),),
        publication=FIRST_PARTY_PUBLICATION,
        notations=notations(),
        backends=(probe_backend(),),
        required_bundles=(
            BundleReference("foundation.space", "2"),
            BundleReference("foundation.fields.units", "1"),
        ),
        contracts=tuple(
            ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, item.id, item.version)
            for item in (ARRAY_TYPE, SUPPORT_TYPE, INTERPRETATION_TYPE, SERIES_TYPE, PREVIEW_TYPE)
        ),
        resource_interpretations=(
            ResourceInterpretation(SUPPORT_TYPE, support_dependencies),
            ResourceInterpretation(INTERPRETATION_TYPE, interpretation_dependencies),
            ResourceInterpretation(SERIES_TYPE, series_dependencies),
        ),
    )
