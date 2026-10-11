"""Cell-average physical authoring at the deterministic extension boundary."""

from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.execution.resource_interpretation import ResourceInterpretation
from code_visualizer.extensions.adaptive_fields.codec import (
    decisions_dependencies,
    history_dependencies,
    interpretation_dependencies,
    support_dependencies,
    transfer_dependencies,
)
from code_visualizer.extensions.adaptive_fields.domain import BUNDLE, field_schema, notations
from code_visualizer.extensions.adaptive_fields.probe import probe_backend
from code_visualizer.extensions.adaptive_fields.records import (
    DECISIONS_TYPE,
    HISTORY_TYPE,
    INTERPRETATION_TYPE,
    PREVIEW_TYPE,
    SUPPORT_TYPE,
    TRANSFER_TYPE,
)
from code_visualizer.extensions.adaptive_fields.units import BUNDLE as UNITS
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import DomainExtensionBundle


def adaptive_fields_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        BUNDLE.id,
        BUNDLE.version,
        schemas=(field_schema(),),
        notations=notations(),
        backends=(probe_backend(),),
        required_bundles=(UNITS, BundleReference("foundation.fields", "1")),
        publication=FIRST_PARTY_PUBLICATION,
        contracts=tuple(
            ContractDefinition(ContractKind.RESOURCE_LOGICAL_TYPE, item.id, item.version)
            for item in (
                SUPPORT_TYPE,
                INTERPRETATION_TYPE,
                HISTORY_TYPE,
                TRANSFER_TYPE,
                DECISIONS_TYPE,
                PREVIEW_TYPE,
            )
        ),
        resource_interpretations=(
            ResourceInterpretation(SUPPORT_TYPE, support_dependencies),
            ResourceInterpretation(INTERPRETATION_TYPE, interpretation_dependencies),
            ResourceInterpretation(HISTORY_TYPE, history_dependencies),
            ResourceInterpretation(TRANSFER_TYPE, transfer_dependencies),
            ResourceInterpretation(DECISIONS_TYPE, decisions_dependencies),
        ),
    )
