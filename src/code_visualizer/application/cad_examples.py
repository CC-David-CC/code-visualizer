"""Native source for the spring-driven CAD example, using the ordinary Python domain."""

from dataclasses import replace

from code_visualizer.application.physical_examples import spring_equation_project
from code_visualizer.domain.computation import (
    ComputationParameter,
    ComputationRequest,
    ResourceInput,
    ResourceOutput,
)
from code_visualizer.domain.intentional import BundleReference
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
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.builtin import builtin_registry
from code_visualizer.extensions.cad.domain import BUNDLE
from code_visualizer.extensions.cad.resources import BREP
from code_visualizer.extensions.foundations.equations import RESULT_TYPE

RECIPE_ID = "cad:recipe"
SOLUTION_TYPE = ResourceLogicalTypeReference(RESULT_TYPE, "1")
RECIPE = (
    (
        "imports",
        """from pathlib import Path
from build123d import Align, Box, Cylinder, Pos
from code_visualizer.execution.python_api import input_resource
from code_visualizer.extensions.cad.python_api import solved_length, native_length, publish_solid
from code_visualizer.extensions.cad.domain import quantity
from code_visualizer.extensions.cad.resources import FrameSnapshot
from code_visualizer.extensions.cad.units import cad_catalog
from code_visualizer.domain.resources import ResourceLogicalTypeReference""",
    ),
    (
        "parameters",
        """length = solved_length('solution', 'spring:x')
width, height, radius = quantity(0.02), quantity(0.01), quantity(0.002)
L, W = native_length(length), native_length(width)
H, R = native_length(height), native_length(radius)""",
    ),
    (
        "frame",
        """frame = FrameSnapshot('cad:recipe-space', 'cad:recipe-frame',
    cad_catalog().unit('foundation.units.si:millimeter'))""",
    ),
    ("box", "solid = Box(L, W, H, align=(Align.MIN, Align.MIN, Align.MIN))"),
    (
        "cut",
        """solid = solid - Pos(L / 2, W / 2, 0) * Cylinder(R, H,
    align=(Align.CENTER, Align.CENTER, Align.MIN))""",
    ),
    (
        "publish",
        """source = input_resource('solution',
    ResourceLogicalTypeReference('foundation.math.equation_solution', '1'))
receipt = publish_solid('solid', solid, frame=frame,
    parameters=(('length', length), ('width', width), ('height', height), ('hole_radius', radius)),
    parent=source.descriptor.reference)
print('Solid publication acknowledged:', receipt)
print('Real emitted module:', Path(__file__).is_file())""",
    ),
)


def spring_cad_project() -> Project:
    project = spring_equation_project()
    registry = builtin_registry()
    workspace = project.domain_workspace
    schemas = {s.id: s for s in workspace.schemas}
    models = {m.id: m for m in workspace.models}
    references = set(workspace.bundle_references)
    for reference in (BUNDLE, BundleReference("code_visualizer.python.artifacts", "1")):
        for bundle in registry.bundle_closure(reference):
            references.add(BundleReference(bundle.id, bundle.version))
            for schema in bundle.schemas:
                if schema.id in schemas and schemas[schema.id] != schema:
                    raise ValueError("Example requires conflicting schema versions")
                schemas[schema.id] = schema
            models.update((m.id, m) for m in bundle.reference_models)
    statements = tuple(
        ProgramAction(
            "cad:" + role,
            make_program_expression(
                "cad:" + role,
                "code",
                source,
                ExpressionRole.STATEMENTS,
                identity_namespace="cad-example-v1",
            ),
        )
        for role, source in RECIPE
    )
    function = ProgramFunction(
        RECIPE_ID,
        "cad:recipe-symbol",
        "main",
        "Spring-driven perforated beam",
        CallableKind.SYNC,
        (),
        None,
        (),
        None,
        None,
        ProgramSequence("cad:recipe-body", statements),
    )
    program = ProgramModel(
        (function,),
        (
            ProgramSymbol(
                function.symbol_id, "main", ProgramSymbolKind.FUNCTION, function.id, function.id
            ),
        ),
        (ProgramModule("cad:module", "main", (ProgramFunctionReference(function.id),)),),
        entrypoint=ProgramEntryPoint("cad:entrypoint", function.id),
    )
    return replace(
        project,
        id="physical:spring-cad",
        title="Spring-driven perforated beam",
        description=(
            "Solve F=k*x, select the retained solution, and run the Python recipe. "
            "Measure or tessellate the sealed BREP independently. The recipe owns "
            "the millimeter Cartesian frame. Geometry and display mesh are separate resources."
        ),
        program_model=program,
        domain_workspace=replace(
            workspace,
            schemas=tuple(schemas.values()),
            models=tuple(models.values()),
            bundle_references=tuple(sorted(references, key=lambda r: (r.id, r.version))),
        ),
    )


def recipe_request(project: Project, solution: ResourceReference) -> ComputationRequest:
    """Bind a chosen immutable solution, never a mutable 'latest result'."""
    return ComputationRequest(
        project.id,
        project.revision,
        "code_visualizer.python",
        "2",
        configuration=(ComputationParameter("timeout_seconds", 120),),
        inputs=(ResourceInput("solution", solution, SOLUTION_TYPE),),
        outputs=(
            ResourceOutput(
                "solid",
                BREP,
                tuple("cad:" + role for role in ("parameters", "frame", "box", "cut", "publish")),
            ),
        ),
    )
