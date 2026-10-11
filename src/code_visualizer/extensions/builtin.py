"""Built-in domains composed explicitly, without project-controlled code loading."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from code_visualizer.domain.expression import expression_identity_ids
from code_visualizer.domain.identifiers import ContractDefinition, ContractKind
from code_visualizer.domain.intentional import BundleReference
from code_visualizer.domain.program import iter_program_nodes, program_expressions
from code_visualizer.domain.project import Project
from code_visualizer.domain.resources import TERMINAL_LOGICAL_TYPE
from code_visualizer.domain.transformation import PROGRAM_REPRESENTATION, Representation
from code_visualizer.extensions.publication import FIRST_PARTY_PUBLICATION
from code_visualizer.extensions.registry import (
    DomainExtensionBundle,
    DomainExtensionRegistry,
    DomainParticipant,
    DomainProvider,
    GeneratorContribution,
    GeneratorInput,
)

if TYPE_CHECKING:
    from code_visualizer.generation.emitter import GeneratedProject


def _program_domains(project: Project) -> tuple[DomainParticipant, ...]:
    model = project.program_model
    object_ids = {
        identity
        for node in iter_program_nodes(model)
        if isinstance(identity := getattr(node, "id", None), str)
    }
    for expression in program_expressions(model):
        object_ids.update(expression_identity_ids(expression.tree))
    return (
        DomainParticipant(
            f"program-domain:{project.id}",
            "code_visualizer.program",
            "Programming",
            PROGRAM_REPRESENTATION,
            (
                *(item.id for item in model.modules),
                *((model.entrypoint.id,) if model.entrypoint is not None else ()),
            ),
            tuple(sorted(object_ids)),
            "program.",
        ),
    )


def _intentional_domains(project: Project) -> tuple[DomainParticipant, ...]:
    workspace = project.domain_workspace
    return tuple(
        DomainParticipant(
            model.id,
            "code_visualizer.intentional",
            model.title or model.id,
            Representation(schema.namespace, schema.version),
            model.roots,
            tuple(sorted(item.id for item in model.nodes)),
            "domain.",
            schema.id,
        )
        for model in workspace.models
        if (schema := workspace.schema(model.schema_id)) is not None
    )


def _python_generator(value: GeneratorInput) -> GeneratedProject:
    from code_visualizer.generation.emitter import emit_project
    from code_visualizer.generation.lowering import lower_project

    generated = emit_project(lower_project(value.project))
    return replace(generated, origins=value.origins if value.origins.links else None)


def program_bundle() -> DomainExtensionBundle:
    """Adapt mature typed storage; do not manufacture generic program node copies."""

    from code_visualizer.execution.python_backend import python_backend

    return DomainExtensionBundle(
        "code_visualizer.program",
        "1",
        providers=(DomainProvider("code_visualizer.program", "Programming", _program_domains),),
        generators=(
            GeneratorContribution(
                "python",
                "Python",
                PROGRAM_REPRESENTATION,
                Representation("code_visualizer.python.source", "3.12"),
                _python_generator,
            ),
        ),
        backends=(python_backend(),),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(BundleReference("code_visualizer.computation", "2"),),
        contracts=(
            ContractDefinition(ContractKind.REPRESENTATION, PROGRAM_REPRESENTATION.id, "1"),
            ContractDefinition(
                ContractKind.REPRESENTATION, "code_visualizer.python.source", "3.12"
            ),
        ),
    )


def computation_bundle() -> DomainExtensionBundle:
    """Publish portable computation contracts independently of any backend domain."""
    return DomainExtensionBundle(
        "code_visualizer.computation",
        "2",
        publication=FIRST_PARTY_PUBLICATION,
        contracts=(
            ContractDefinition(
                ContractKind.RESOURCE_LOGICAL_TYPE,
                TERMINAL_LOGICAL_TYPE.id,
                TERMINAL_LOGICAL_TYPE.version,
            ),
        ),
    )


def intentional_bundle() -> DomainExtensionBundle:
    return DomainExtensionBundle(
        "code_visualizer.intentional",
        "1",
        providers=(
            DomainProvider(
                "code_visualizer.intentional",
                "Schema-driven domains",
                _intentional_domains,
            ),
        ),
        publication=FIRST_PARTY_PUBLICATION,
    )


def python_artifacts_bundle() -> DomainExtensionBundle:
    from code_visualizer.execution.python_backend import publishing_python_backend

    return DomainExtensionBundle(
        "code_visualizer.python.artifacts",
        "1",
        backends=(publishing_python_backend(),),
        publication=FIRST_PARTY_PUBLICATION,
        required_bundles=(BundleReference("code_visualizer.program", "1"),),
        contracts=(
            ContractDefinition(
                ContractKind.RESOURCE_LOGICAL_TYPE, "code_visualizer.python.byte_stream", "1"
            ),
        ),
    )


def builtin_registry() -> DomainExtensionRegistry:
    from code_visualizer.extensions.adaptive_diffusion.bundle import adaptive_diffusion_bundle
    from code_visualizer.extensions.adaptive_fields.bundle import adaptive_fields_bundle
    from code_visualizer.extensions.adaptive_fields.units import (
        units_bundle as adaptive_units_bundle,
    )
    from code_visualizer.extensions.axial.bundle import axial_bundle
    from code_visualizer.extensions.cad import cad_bundle
    from code_visualizer.extensions.cad.units import units_bundle as cad_units_bundle
    from code_visualizer.extensions.channels.bundle import channels_bundle
    from code_visualizer.extensions.dc import dc_bundle
    from code_visualizer.extensions.diffusion.bundle import diffusion_bundle
    from code_visualizer.extensions.electrothermal.bundle import electrothermal_bundle
    from code_visualizer.extensions.electrothermal.units import units_bundle as thermal_units_bundle
    from code_visualizer.extensions.fields.bundle import fields_bundle
    from code_visualizer.extensions.fields.units import units_bundle as field_units_bundle
    from code_visualizer.extensions.foundations import math_bundle, space_bundle
    from code_visualizer.extensions.foundations.equations import equation_bundle
    from code_visualizer.extensions.foundations.space import space_v2_bundle
    from code_visualizer.extensions.foundations.unit_algebra_si import (
        algebra_bundle,
        algebra_si_bundle,
    )
    from code_visualizer.extensions.foundations.units import units_bundle
    from code_visualizer.extensions.foundations.units_si import si_bundle
    from code_visualizer.extensions.fsm import fsm_bundle
    from code_visualizer.extensions.gas_observation.bundle import (
        observation_bundle as gas_observation_bundle,
    )
    from code_visualizer.extensions.hybrid_gas.bundle import hybrid_gas_bundle
    from code_visualizer.extensions.hybrid_gas.units import units_bundle as gas_units_bundle
    from code_visualizer.extensions.publication import FIRST_PARTY_OWNERSHIP

    return DomainExtensionRegistry(
        (
            computation_bundle(),
            program_bundle(),
            python_artifacts_bundle(),
            intentional_bundle(),
            fsm_bundle(),
            math_bundle(),
            space_bundle(),
            units_bundle(),
            si_bundle(),
            algebra_bundle(),
            algebra_si_bundle(),
            equation_bundle(),
            dc_bundle(),
            cad_units_bundle(),
            cad_bundle(),
            space_v2_bundle(),
            field_units_bundle(),
            fields_bundle(),
            diffusion_bundle(),
            channels_bundle(),
            thermal_units_bundle(),
            electrothermal_bundle(),
            axial_bundle(),
            adaptive_units_bundle(),
            adaptive_fields_bundle(),
            adaptive_diffusion_bundle(),
            gas_units_bundle(),
            hybrid_gas_bundle(),
            gas_observation_bundle(),
        ),
        namespace_ownership=FIRST_PARTY_OWNERSHIP,
    )
