"""Exact lumped-channel resource contracts at the existing static boundary."""

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.execution.resource_interpretation import ResourceInterpretation
from code_visualizer.extensions.channels.codec import (
    interpretation_dependencies,
    series_dependencies,
)
from code_visualizer.extensions.channels.domain import BUNDLE, channel_schema, notations
from code_visualizer.extensions.channels.preview import PREVIEW_TYPE
from code_visualizer.extensions.channels.probe import probe_backend
from code_visualizer.extensions.channels.records import INTERPRETATION_TYPE, SERIES_TYPE
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def channels_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        "1",
        schemas=(channel_schema(),),
        notations=notations(),
        backends=(probe_backend(),),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(BundleReference("foundation.fields", "1"),),
        contracts=tuple(
            ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, item.id, item.version)
            for item in (INTERPRETATION_TYPE, SERIES_TYPE, PREVIEW_TYPE)
        ),
        resource_interpretations=(
            ResourceInterpretation(INTERPRETATION_TYPE, interpretation_dependencies),
            ResourceInterpretation(SERIES_TYPE, series_dependencies),
        ),
    )
