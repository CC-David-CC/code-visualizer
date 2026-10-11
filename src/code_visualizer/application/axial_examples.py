"""Authored Python CAD source and an explicit artifact-consuming axial definition."""

from code_visualizer.domain.computation import (
    ComputationParameter,
    ComputationRequest,
    ResourceOutput,
)
from code_visualizer.domain.intentional import (
    BundleReference,
    DomainModel,
    DomainWorkspace,
)
from code_visualizer.domain.program import (
    ExpressionRole,
    ProgramAction,
    ProgramEntryPoint,
    ProgramFunction,
    ProgramFunctionReference,
    ProgramModel,
    ProgramModule,
    ProgramSequence,
    ProgramSymbol,
    ProgramSymbolKind,
    make_program_expression,
)
from code_visualizer.domain.program_kinds import CallableKind
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.axial.domain import BUNDLE
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.cad.resources import BREP

MODEL_ID = "axial:experiment"
FRAME_ID = "bar:frame"
RECIPE_ID = "bar:recipe"
RECIPE_ROLES = ("imports", "parameters", "frame", "box", "publish")


def axial_cad_project(
    *,
    length: float = 0.1,
    width: float = 0.01,
    height: float = 0.01,
    native_unit: str = "millimeter",
) -> Project:
    if native_unit not in ("millimeter", "meter"):
        raise ValueError("The example uses declared SI meter or millimeter coordinates")
    recipe = (
        "from build123d import Align, Box\n"
        "from code_visualizer.extensions.cad.python_api import publish_solid\n"
        "from code_visualizer.extensions.cad.resources import FrameSnapshot\n"
        "from code_visualizer.extensions.cad.domain import quantity\n"
        "from code_visualizer.extensions.cad.units import cad_catalog",
        f"length, width, height = quantity({length!r}), quantity({width!r}), quantity({height!r})",
        f"frame = FrameSnapshot('bar:space', {FRAME_ID!r}, "
        f"cad_catalog().unit('foundation.units.si:{native_unit}'))\n"
        "L, W, H = (float(cad_catalog().convert(q, frame.unit).magnitude) "
        "for q in (length, width, height))",
        "solid = Box(L, W, H, align=(Align.MIN, Align.MIN, Align.MIN))",
        "receipt = publish_solid('bar', solid, frame=frame, "
        "parameters=(('length', length), ('width', width), ('height', height)))\n"
        "print('Solid bar publication acknowledged:', receipt)",
    )
    statements = tuple(
        ProgramAction(
            "bar:" + role,
            make_program_expression(
                "bar:" + role,
                "code",
                source,
                ExpressionRole.STATEMENTS,
                identity_namespace="axial-example-v1",
            ),
        )
        for role, source in zip(RECIPE_ROLES, recipe, strict=True)
    )
    function = ProgramFunction(
        RECIPE_ID,
        "bar:recipe-symbol",
        "main",
        "Publish a solid rectangular bar",
        CallableKind.SYNC,
        (),
        None,
        (),
        None,
        None,
        ProgramSequence("bar:body", statements),
    )
    program = ProgramModel(
        (function,),
        (
            ProgramSymbol(
                function.symbol_id, "main", ProgramSymbolKind.FUNCTION, function.id, function.id
            ),
        ),
        (ProgramModule("bar:module", "main", (ProgramFunctionReference(function.id),)),),
        entrypoint=ProgramEntryPoint("bar:entrypoint", function.id),
    )
    registry = builtin_registry()
    bundles = {
        item.id: item
        for reference in (BUNDLE, BundleReference("code_visualizer.python.artifacts", "1"))
        for item in registry.bundle_closure(reference)
    }
    return Project(
        "physical:axial-bar",
        "Solid bar → axial equilibrium",
        (),
        description="Run the real Python CAD recipe, then use its sealed solid for axial analysis. "
        "Material, support, load and the one-dimensional idealization remain authored intentions.",
        program_model=program,
        domain_workspace=DomainWorkspace(
            tuple(schema for bundle in bundles.values() for schema in bundle.schemas),
            tuple(model for bundle in bundles.values() for model in bundle.reference_models),
            tuple(BundleReference(bundle.id, bundle.version) for bundle in bundles.values()),
        ),
    )


def recipe_request(project: Project) -> ComputationRequest:
    return ComputationRequest(
        project.id,
        project.revision,
        "code_visualizer.python",
        "2",
        configuration=(ComputationParameter("timeout_seconds", 120),),
        outputs=(ResourceOutput("bar", BREP, tuple("bar:" + role for role in RECIPE_ROLES)),),
    )


def axial_models(
    project: Project,
    resource: ResourceReference,
    *,
    nodes: int = 9,
    young_modulus: float = 2e11,
    force: float = 1000,
    frame_id: str = FRAME_ID,
    axis: str = "x",
) -> tuple[DomainModel, DomainModel]:
    from code_visualizer.extensions.axial.authoring import create_models

    return create_models(
        project,
        resource,
        nodes=nodes,
        young_modulus=young_modulus,
        force=force,
        frame_id=frame_id,
        axis=axis,
        namespace="axial",
    )
