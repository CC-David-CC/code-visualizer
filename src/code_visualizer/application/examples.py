"""Editable example-session factories shared by welcome and future automation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

from code_visualizer.application.authored_examples import authored_traffic_light_project
from code_visualizer.application.authority import ProjectAuthority
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.physical_examples import (
    dc_divider_project,
    spring_equation_project,
)
from code_visualizer.application.project_factory import initialize_project_documents
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.authoring import (
    AuthoredRelationKind,
    AuthoredSemanticRelation,
    SemanticConcept,
)
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.drakon import (
    Assignment,
    Call,
    DrakonAtom,
    DrakonDiagram,
    End,
    Header,
    If,
    Loop,
    Output,
    Sequence,
    SimpleStatement,
    Transfer,
)
from code_visualizer.domain.freeform import (
    ConnectorObject,
    FreeformDiagram,
    Rect,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.domain.mindmap import CrossLink, MindMapDiagram, Topic
from code_visualizer.domain.program import ProgramEntryPoint, ProgramModel, ProgramModule
from code_visualizer.domain.program_kinds import (
    CallableKind,
    LoopKind,
    MethodKind,
    SimpleKind,
    TransferKind,
)
from code_visualizer.domain.program_signatures import FunctionSpec, ParameterSpec
from code_visualizer.domain.project import (
    EnvironmentVariable,
    Project,
    PythonRuntimeSettings,
    RunProfile,
)
from code_visualizer.domain.projection import (
    ProjectionDecoration,
    ProjectionDefinition,
    ProjectionGrouping,
    ProjectionLayout,
    TraversalDirection,
)
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.domain.semantic import SemanticObjectKind, SemanticRelationKind
from code_visualizer.sdk import CodeVisualizerClient


class ExampleBuildError(RuntimeError):
    pass


def _example_module(
    path: str, source: str = "", *, docstring: str = "", after: str = ""
) -> ProgramModule:
    identity = f"example:module:{path}"
    return ProgramModule(
        identity,
        path,
        (
            *parse_python_declarations(identity, source, identity_namespace="example"),
            *parse_python_declarations(identity, after, identity_namespace="after"),
        ),
        docstring,
    )


def _example_program(
    *,
    package: str,
    modules: tuple[ProgramModule, ...],
    entrypoint_callable_id: str,
    startup: str = "",
) -> ProgramModel:
    identity = f"example:entrypoint:{entrypoint_callable_id}"
    return ProgramModel(
        modules=modules,
        package=package,
        entrypoint=ProgramEntryPoint(
            identity,
            entrypoint_callable_id,
            startup=parse_python_declarations(identity, startup, identity_namespace="example"),
        ),
    )


@dataclass(frozen=True, slots=True)
class ExampleDefinition:
    id: str
    label: str
    description: str
    resource_directory: str | None = None


EXAMPLE_CATALOG: tuple[ExampleDefinition, ...] = (
    ExampleDefinition(
        "hello_world", "01 · Hello World", "One Output icon; smallest runnable project"
    ),
    ExampleDefinition(
        "python_modules",
        "02 · Python Modules",
        "Two functions, imports, constants, artifacts, run, and trace",
    ),
    ExampleDefinition("values", "03 · Values and Assignment", "Typed Shelf plus Output"),
    ExampleDefinition("decisions", "04 · Binary Decision", "If, preferred route, and join"),
    ExampleDefinition("select_match", "05 · Select and Match", "Ordered conditions and match/case"),
    ExampleDefinition("loops", "06 · Loop Progression", "While, do-first, iterable For, and TREE"),
    ExampleDefinition("contexts", "07 · Contexts and Exceptions", "With and Try/except/finally"),
    ExampleDefinition(
        "timing", "08 · Timing and Synchronization", "Timer, delay, period, deadline"
    ),
    ExampleDefinition("parallel", "09 · Parallel Processes", "Threaded structured concurrency"),
    ExampleDefinition("async", "10 · Async Python", "Await, async For, and TaskGroup"),
    ExampleDefinition("generators", "11 · Generators", "Yield and Yield From"),
    ExampleDefinition("classes", "12 · Classes and Methods", "Static method entry point"),
    ExampleDefinition(
        "silhouette", "13 · Golden Node Silhouette", "Named finite state progression"
    ),
    ExampleDefinition(
        "first_delivery",
        "14 · First Delivery",
        "One semantic program shown through DRAKON, mind-map, and free-form views",
    ),
    ExampleDefinition(
        "dijkstra",
        "15 · Dijkstra and A* Pathfinding",
        "Two source-mapped heap-frontier algorithms with deterministic graph tests",
    ),
    ExampleDefinition(
        "computational_instrument",
        "16 · Bespoke Computational Instrument",
        "Nine cooperating diagrams across math, model, simulation, telemetry, UI, and testing",
    ),
    ExampleDefinition(
        "traffic_light",
        "17 · Traffic Light Domain Workbench",
        "One state machine edited through graph, table, and form with runtime origins",
    ),
)


PHYSICAL_EXAMPLE_CATALOG: tuple[ExampleDefinition, ...] = (
    ExampleDefinition("dc_divider", "DC resistor network", "Unit-aware circuit equations"),
    ExampleDefinition(
        "spring_equation", "Unit-aware equation: F = k*x", "Authored physical equation"
    ),
    ExampleDefinition(
        "spring_cad", "Spring-driven CAD and reusable geometry", "Published geometric resources"
    ),
    ExampleDefinition(
        "diffusion_field", "Diffusion: time, fields and checkpoints", "Retained spatial history"
    ),
    ExampleDefinition(
        "electrothermal",
        "Resistor and heat sink: coupled windows",
        "Implicit electrothermal feedback, trials and retained history",
    ),
    ExampleDefinition(
        "axial_bar",
        "Solid CAD bar and axial equilibrium",
        "Explicit geometry, material, end regions and P3 equilibrium",
    ),
    ExampleDefinition(
        "adaptive_diffusion",
        "Adaptive periodic diffusion pulse",
        "Conservative cell refinement, exact epochs and retained probes",
    ),
    ExampleDefinition(
        "hybrid_gas",
        "Particle and continuum gas shear",
        "Calibrated native participant, conservative interfaces and retained cell queries",
        resource_directory="hybrid_gas",
    ),
)


def _first_delivery_project() -> Project:
    hello = DrakonDiagram(
        id="diagram_first_hello",
        title="Hello World",
        header=Header("header_first_hello", FunctionSpec("main", "Hello World")),
        body=Sequence(
            "sequence_first_hello",
            (Output("output_first_hello", '"Hello, world!"'),),
        ),
        end=End("end_first_hello"),
        description="The smallest complete generated Python application: one Output operation.",
    )
    decision = DrakonDiagram(
        id="diagram_first_decision",
        title="Preferred route decision",
        header=Header(
            "header_first_decision",
            FunctionSpec(
                "describe_sign",
                "Describe a number",
                parameters=(ParameterSpec("value", annotation="int", default="1"),),
            ),
        ),
        body=Sequence(
            "sequence_first_decision",
            (
                If(
                    "if_first_positive",
                    "value >= 0",
                    Sequence(
                        "sequence_first_positive",
                        (Output("output_first_positive", '"preferred / True: non-negative"'),),
                    ),
                    Sequence(
                        "sequence_first_negative",
                        (Output("output_first_negative", '"right branch / False: negative"'),),
                    ),
                    preferred_truth=True,
                ),
            ),
        ),
        end=End("end_first_decision"),
        description=(
            "Truth and preference are distinct: True is explicitly bound to the vertical "
            "preferred route in this example."
        ),
    )
    loop = DrakonDiagram(
        id="diagram_first_loop",
        title="Small iterable loop",
        header=Header("header_first_loop", FunctionSpec("count_three", "Count three values")),
        body=Sequence(
            "sequence_first_loop",
            (
                Loop(
                    "loop_first_three",
                    LoopKind.FOR,
                    Sequence(
                        "sequence_first_loop_body",
                        (Output("output_first_loop_value", 'f"loop value: {number}"'),),
                    ),
                    Sequence("sequence_first_loop_else"),
                    target="number",
                    iterable="range(1, 4)",
                ),
            ),
        ),
        end=End("end_first_loop"),
        description="A compact Python iterable For whose body remains inside the loop graphic.",
    )
    mind_map = MindMapDiagram(
        id="diagram_first_mind_map",
        title="First delivery plan",
        root=Topic(
            "topic_first_root",
            "Deliver a useful visual Python project",
            (
                Topic(
                    "topic_first_design",
                    "Design",
                    (
                        Topic("topic_first_happy", "Teach the happy path"),
                        Topic(
                            "topic_first_readable",
                            "Keep every icon readable",
                            semantic_id="loop_first_three",
                        ),
                    ),
                    notes="Prefer direct, visible controls over hidden properties.",
                    semantic_id="diagram_first_hello",
                ),
                Topic(
                    "topic_first_verify",
                    "Verify",
                    (
                        Topic(
                            "topic_first_run",
                            "Run generated Python",
                            semantic_id="output_first_hello",
                        ),
                        Topic("topic_first_export", "Inspect all three export modes"),
                    ),
                    semantic_id="diagram_first_decision",
                ),
                Topic("topic_first_share", "Share and extend"),
            ),
            semantic_id="project_first_delivery",
        ),
        cross_links=(
            CrossLink(
                "cross_first_feedback",
                "topic_first_verify",
                "topic_first_design",
                "feedback",
            ),
        ),
        layout="balanced",
    )
    freeform = FreeformDiagram(
        id="diagram_first_freeform",
        title="First delivery architecture",
        objects=(
            ShapeObject(
                "shape_first_input",
                ShapeKind.ROUNDED_RECTANGLE,
                Rect(20, 40, 180, 82),
                "Human or agent edit",
                fill="#dbeafe",
                stroke="#1d4ed8",
            ),
            ShapeObject(
                "shape_first_authority",
                ShapeKind.ROUNDED_RECTANGLE,
                Rect(280, 40, 190, 82),
                "Single project authority",
                z_index=1,
                fill="#dcfce7",
                stroke="#15803d",
                semantic_id="project_first_delivery",
            ),
            ShapeObject(
                "shape_first_output",
                ShapeKind.ROUNDED_RECTANGLE,
                Rect(550, 40, 190, 82),
                "Diagram + Python artifacts",
                z_index=2,
                fill="#fef3c7",
                stroke="#b45309",
                semantic_id="diagram_first_hello",
            ),
            ConnectorObject(
                "connector_first_input",
                "shape_first_input",
                "shape_first_authority",
                label="semantic command",
            ),
            ConnectorObject(
                "connector_first_output",
                "shape_first_authority",
                "shape_first_output",
                label="one revision",
            ),
        ),
        grid_size=20.0,
        snap_to_grid=True,
    )
    return Project(
        id="project_first_delivery",
        title="First Delivery — Shared Semantic Starter",
        description=(
            "A deliberately small executable program with DRAKON, mind-map, and free-form "
            "views anchored to shared semantic identities; unanchored objects remain annotations."
        ),
        documents=(hello, decision, loop, mind_map, freeform),
        program_model=_example_program(
            package="first_delivery",
            modules=(
                _example_module(
                    "main",
                    "",
                    docstring="Small executable algorithms from the First Delivery collection.",
                    after="",
                ),
            ),
            entrypoint_callable_id=hello.id,
            startup="",
        ),
        concepts=(
            SemanticConcept(
                "concept_first_delivery_happy_path",
                "First delivery happy path",
                "Start with output, add a visible choice, then introduce iteration.",
                (
                    hello.id,
                    "output_first_hello",
                    decision.id,
                    "if_first_positive",
                    loop.id,
                    "loop_first_three",
                ),
                ("learning", "happy-path"),
            ),
        ),
        semantic_relations=(
            AuthoredSemanticRelation(
                "semantic_relation_first_output_to_choice",
                hello.id,
                decision.id,
                AuthoredRelationKind.PRECEDES_CONCEPTUALLY,
                "then add a choice",
                "The learning sequence grows one control idea at a time.",
            ),
            AuthoredSemanticRelation(
                "semantic_relation_first_choice_to_loop",
                decision.id,
                loop.id,
                AuthoredRelationKind.PRECEDES_CONCEPTUALLY,
                "then add repetition",
                "Iteration follows once the preferred route is readable.",
            ),
        ),
        projection_definitions=(
            ProjectionDefinition(
                "projection_first_delivery_learning",
                "Learning progression",
                scope_id="concept_first_delivery_happy_path",
                object_kinds=(
                    SemanticObjectKind.CONCEPT,
                    SemanticObjectKind.FUNCTION,
                    SemanticObjectKind.OPERATION,
                ),
                relation_kinds=(
                    SemanticRelationKind.CONCEPTUALLY_CONTAINS,
                    SemanticRelationKind.AUTHORED,
                ),
                direction=TraversalDirection.OUTGOING,
                max_depth=4,
                grouping=ProjectionGrouping.CONCEPT,
                decorations=(ProjectionDecoration.KIND, ProjectionDecoration.DETAIL),
                layout=ProjectionLayout.RADIAL,
                include_isolated=False,
            ),
        ),
    )


def _accepted(result: object, step: str) -> None:
    if not isinstance(result, CommandAccepted):
        raise ExampleBuildError(f"Example step failed: {step}")


def hello_world_session(*, computations: ComputationService | None = None) -> ProjectSession:
    session = ProjectSession.new(computations=computations)
    try:
        _accepted(session.client.rename_project("Hello World Example"), "rename")
        main = session.authority.snapshot().documents[0]
        _accepted(
            session.client.insert_drakon_atom(
                main.id,
                "output",
                0,
                source='"Hello, world!"',
            ),
            "insert output",
        )
    except Exception:
        session.close()
        raise
    return session


def python_modules_session(*, computations: ComputationService | None = None) -> ProjectSession:
    session = ProjectSession.new(computations=computations)
    try:
        _accepted(session.client.rename_project("Python Modules Example"), "rename")
        main = session.authority.snapshot().documents[0]
        _accepted(
            session.client.insert_drakon_atom(
                main.id,
                "action",
                0,
                source="print(make_greeting())",
            ),
            "insert main action",
        )
        _accepted(
            session.client.create_diagram(
                DocumentKind.DRAKON,
                "Build greeting",
                identifier="build_greeting",
                module="helpers",
            ),
            "create helper function",
        )
        helper = session.authority.snapshot().documents[1]
        _accepted(
            session.client.insert_drakon_atom(
                helper.id,
                "return",
                0,
                source="Greeter(MESSAGE).render()",
            ),
            "insert helper return",
        )
        setup = _example_program(
            package="studio_demo",
            modules=(
                _example_module(
                    "main",
                    "from studio_demo.helpers import build_greeting as make_greeting",
                    docstring="Runnable package entry point generated from a DRAKON diagram.",
                    after="MODULE_READY: bool = True",
                ),
                _example_module(
                    "helpers",
                    (
                        'MESSAGE: str = "Hello from two modules!"\n'
                        "type MessageText = str\n"
                        "class Greeter:\n"
                        "    def __init__(self, message: MessageText) -> None:\n"
                        "        self.message = message\n"
                        "\n"
                        "    def render(self) -> str:\n"
                        "        return self.message"
                    ),
                    docstring="Reusable values, declarations, and a generated helper function.",
                    after="",
                ),
            ),
            entrypoint_callable_id=main.id,
            startup='PROJECT_LABEL = "Module Setup demonstration"',
        )
        current = session.authority.snapshot().program_model
        modules = tuple(
            replace(
                module, id=existing.id, body=(*module.body[:-1], *existing.body, *module.body[-1:])
            )
            if module.path == "main"
            else replace(module, id=existing.id, body=(*module.body, *existing.body))
            for module in setup.modules
            for existing in current.modules
            if existing.path == module.path
        )
        _accepted(
            session.client.configure_program(
                package=setup.package, modules=modules, entrypoint=setup.entrypoint
            ),
            "configure modules",
        )
        _accepted(
            session.client.configure_python_runtime(
                PythonRuntimeSettings(
                    run_profiles=(
                        RunProfile(
                            name="Default",
                            working_directory=".",
                            environment=(EnvironmentVariable("CV_EXAMPLE", "modules"),),
                        ),
                    )
                )
            ),
            "configure runtime",
        )
    except Exception:
        session.close()
        raise
    return session


def _progression_session(
    title: str,
    atom_kinds: tuple[str, ...],
    *,
    callable_kind: CallableKind = CallableKind.SYNC,
    method_kind: MethodKind | None = None,
    owning_class: str | None = None,
    computations: ComputationService | None = None,
) -> ProjectSession:
    session = ProjectSession.new(computations=computations)
    try:
        _accepted(session.client.rename_project(title), "rename progression")
        diagram = session.authority.snapshot().documents[0]
        if not isinstance(diagram, DrakonDiagram):
            raise ExampleBuildError("Default example document is not DRAKON")
        function = replace(
            diagram.header.function,
            kind=callable_kind,
            owning_class=owning_class,
            method_kind=method_kind,
        )
        _accepted(
            session.client.replace_function_spec(diagram.id, function),
            "configure function semantics",
        )
        for index, atom_kind in enumerate(atom_kinds):
            _accepted(
                session.client.insert_drakon_atom(diagram.id, atom_kind, index),
                f"insert {atom_kind}",
            )
    except Exception:
        session.close()
        raise
    return session


def _class_example_session(*, computations: ComputationService | None = None) -> ProjectSession:
    session = _progression_session(
        "Classes and Methods Example",
        ("output",),
        method_kind=MethodKind.STATIC,
        owning_class="ExampleApplication",
        computations=computations,
    )
    diagram = session.authority.snapshot().documents[0]
    assert isinstance(diagram, DrakonDiagram)
    function = replace(
        diagram.header.function,
        identifier="run",
        display_name="Run application",
    )
    _accepted(session.client.replace_function_spec(diagram.id, function), "name method")
    atom = diagram.body.atoms[0]
    _accepted(
        session.client.set_drakon_text(
            diagram.id,
            atom.id,
            "expression",
            '"Hello from a generated static method"',
        ),
        "edit method output",
    )
    return session


def _dijkstra_project() -> Project:
    pass_node = SimpleStatement("dijkstra_skip", SimpleKind.PASS, "pass")
    goal_check = If(
        "dijkstra_goal_check",
        "current == goal",
        Sequence(
            "dijkstra_goal_true",
            (Transfer("dijkstra_break", TransferKind.BREAK, ""),),
        ),
        Sequence("dijkstra_goal_false", (pass_node,)),
    )
    relax_check = If(
        "dijkstra_relax_check",
        "candidate < distances.get(neighbor, float('inf'))",
        Sequence(
            "dijkstra_relax_true",
            (
                Assignment("dijkstra_store_distance", "distances[neighbor]", "candidate"),
                Assignment("dijkstra_store_previous", "previous[neighbor]", "current"),
                Call(
                    "dijkstra_push_frontier",
                    "heapq.heappush(frontier, (candidate, neighbor))",
                ),
            ),
        ),
        Sequence(
            "dijkstra_relax_false",
            (SimpleStatement("dijkstra_keep_best", SimpleKind.PASS, "pass"),),
        ),
    )
    neighbors = Loop(
        "dijkstra_neighbors",
        LoopKind.FOR,
        Sequence(
            "dijkstra_neighbor_body",
            (
                Assignment(
                    "dijkstra_candidate",
                    "candidate",
                    "current_distance + weight",
                ),
                relax_check,
            ),
        ),
        Sequence("dijkstra_neighbor_else"),
        target="neighbor, weight",
        iterable="graph.get(current, ())",
    )
    frontier_loop = Loop(
        "dijkstra_frontier_loop",
        LoopKind.WHILE,
        Sequence(
            "dijkstra_frontier_body",
            (
                Assignment(
                    "dijkstra_pop",
                    "current_distance, current",
                    "heapq.heappop(frontier)",
                ),
                goal_check,
                neighbors,
            ),
        ),
        Sequence("dijkstra_frontier_else"),
        condition="frontier",
    )
    path_loop = Loop(
        "dijkstra_path_loop",
        LoopKind.WHILE,
        Sequence(
            "dijkstra_path_body",
            (
                Call("dijkstra_append_path", "path.append(node)"),
                Assignment("dijkstra_previous_node", "node", "previous.get(node)"),
            ),
        ),
        Sequence("dijkstra_path_else"),
        condition="node is not None",
    )
    algorithm = DrakonDiagram(
        id="diagram_dijkstra_algorithm",
        title="Dijkstra shortest path",
        header=Header(
            "header_dijkstra_algorithm",
            FunctionSpec(
                "dijkstra",
                "Dijkstra shortest path",
                parameters=(
                    ParameterSpec("graph", annotation="dict[str, list[tuple[str, float]]]"),
                    ParameterSpec("start", annotation="str"),
                    ParameterSpec("goal", annotation="str"),
                ),
                return_annotation="tuple[float, list[str]]",
                docstring="Return the shortest cost and path using a heap frontier.",
            ),
        ),
        body=Sequence(
            "sequence_dijkstra_algorithm",
            (
                Assignment("dijkstra_distances", "distances", "{start: 0.0}", "dict[str, float]"),
                Assignment("dijkstra_previous", "previous", "{}", "dict[str, str]"),
                Assignment("dijkstra_frontier", "frontier", "[(0.0, start)]"),
                frontier_loop,
                Assignment("dijkstra_path", "path", "[]", "list[str]"),
                Assignment("dijkstra_path_node", "node", "goal"),
                path_loop,
                Call("dijkstra_reverse_path", "path.reverse()"),
                Transfer(
                    "dijkstra_result",
                    TransferKind.RETURN,
                    "(distances.get(goal, float('inf')), path)",
                ),
            ),
        ),
        end=End("end_dijkstra_algorithm"),
        description=(
            "Advanced visual algorithm: heap frontier, nested loops, decisions, and path recovery."
        ),
    )
    a_star_relax = If(
        "a_star_relax_check",
        "candidate < distances.get(neighbor, float('inf'))",
        Sequence(
            "a_star_relax_true",
            (
                Assignment("a_star_store_distance", "distances[neighbor]", "candidate"),
                Assignment("a_star_store_previous", "previous[neighbor]", "current"),
                Call(
                    "a_star_push_frontier",
                    "heapq.heappush(frontier, "
                    "(candidate + heuristic.get(neighbor, 0.0), candidate, neighbor))",
                ),
            ),
        ),
        Sequence(
            "a_star_relax_false",
            (SimpleStatement("a_star_keep_best", SimpleKind.PASS, "pass"),),
        ),
    )
    a_star_neighbors = Loop(
        "a_star_neighbors",
        LoopKind.FOR,
        Sequence(
            "a_star_neighbor_body",
            (
                Assignment("a_star_candidate", "candidate", "current_distance + weight"),
                a_star_relax,
            ),
        ),
        Sequence("a_star_neighbor_else"),
        target="neighbor, weight",
        iterable="graph.get(current, ())",
    )
    a_star_goal = If(
        "a_star_goal_check",
        "current == goal",
        Sequence(
            "a_star_goal_true",
            (Transfer("a_star_break", TransferKind.BREAK, ""),),
        ),
        Sequence(
            "a_star_goal_false",
            (SimpleStatement("a_star_search_on", SimpleKind.PASS, "pass"),),
        ),
    )
    a_star_frontier = Loop(
        "a_star_frontier_loop",
        LoopKind.WHILE,
        Sequence(
            "a_star_frontier_body",
            (
                Assignment(
                    "a_star_pop",
                    "estimated, current_distance, current",
                    "heapq.heappop(frontier)",
                ),
                a_star_goal,
                a_star_neighbors,
            ),
        ),
        Sequence("a_star_frontier_else"),
        condition="frontier",
    )
    a_star_path = Loop(
        "a_star_path_loop",
        LoopKind.WHILE,
        Sequence(
            "a_star_path_body",
            (
                Call("a_star_append_path", "path.append(node)"),
                Assignment("a_star_previous_node", "node", "previous.get(node)"),
            ),
        ),
        Sequence("a_star_path_else"),
        condition="node is not None",
    )
    a_star = DrakonDiagram(
        id="diagram_a_star_algorithm",
        title="A* shortest path",
        header=Header(
            "header_a_star_algorithm",
            FunctionSpec(
                "a_star",
                "A* shortest path",
                parameters=(
                    ParameterSpec("graph", annotation="dict[str, list[tuple[str, float]]]"),
                    ParameterSpec("heuristic", annotation="dict[str, float]"),
                    ParameterSpec("start", annotation="str"),
                    ParameterSpec("goal", annotation="str"),
                ),
                return_annotation="tuple[float, list[str]]",
                docstring=(
                    "Return the shortest cost and path using an admissible heuristic and heap."
                ),
            ),
        ),
        body=Sequence(
            "sequence_a_star_algorithm",
            (
                Assignment("a_star_distances", "distances", "{start: 0.0}", "dict[str, float]"),
                Assignment("a_star_previous", "previous", "{}", "dict[str, str]"),
                Assignment(
                    "a_star_initial_frontier",
                    "frontier",
                    "[(heuristic.get(start, 0.0), 0.0, start)]",
                ),
                a_star_frontier,
                Assignment("a_star_path", "path", "[]", "list[str]"),
                Assignment("a_star_path_node", "node", "goal"),
                a_star_path,
                Call("a_star_reverse_path", "path.reverse()"),
                Transfer(
                    "a_star_result",
                    TransferKind.RETURN,
                    "(distances.get(goal, float('inf')), path)",
                ),
            ),
        ),
        end=End("end_a_star_algorithm"),
        description=(
            "Advanced visual algorithm: heuristic frontier, nested loop, relaxation, and recovery."
        ),
    )
    main = DrakonDiagram(
        id="diagram_dijkstra_main",
        title="Run Dijkstra example",
        header=Header(
            "header_dijkstra_main",
            FunctionSpec("main", "Run Dijkstra example"),
        ),
        body=Sequence(
            "sequence_dijkstra_main",
            (
                Assignment(
                    "dijkstra_example_graph",
                    "graph",
                    "{'A': [('B', 4.0), ('C', 1.0)], "
                    "'B': [('D', 1.0)], 'C': [('B', 2.0), ('D', 5.0)], 'D': []}",
                ),
                Assignment(
                    "pathfinding_example_heuristic",
                    "heuristic",
                    "{'A': 4.0, 'B': 1.0, 'C': 3.0, 'D': 0.0}",
                ),
                Call(
                    "dijkstra_example_call",
                    "dijkstra(graph, 'A', 'D')",
                    result_target="cost, path",
                    target_diagram_id=algorithm.id,
                    arguments="graph, 'A', 'D'",
                ),
                Output(
                    "dijkstra_example_output",
                    'f"Dijkstra path: {path}; total cost: {cost}"',
                ),
                Call(
                    "a_star_example_call",
                    "a_star(graph, heuristic, 'A', 'D')",
                    result_target="a_cost, a_path",
                    target_diagram_id=a_star.id,
                    arguments="graph, heuristic, 'A', 'D'",
                ),
                Output(
                    "a_star_example_output",
                    'f"A* path: {a_path}; total cost: {a_cost}"',
                ),
            ),
        ),
        end=End("end_dijkstra_main"),
    )
    return Project(
        id="project_dijkstra_progression",
        title="Dijkstra and A* Pathfinding Example",
        description=(
            "Advanced end-to-end Python diagram studio example with deterministic graph data."
        ),
        documents=(main, algorithm, a_star),
        program_model=_example_program(
            package="dijkstra_demo",
            modules=(
                _example_module(
                    "main",
                    "import heapq",
                    docstring="Generated visual implementations of Dijkstra and A* pathfinding.",
                    after="",
                ),
            ),
            entrypoint_callable_id=main.id,
            startup="",
        ),
        concepts=(
            SemanticConcept(
                "concept_pathfinding_search",
                "Shortest-path search",
                "The two executable strategies and their shared runnable demonstration.",
                (main.id, algorithm.id, a_star.id),
                ("algorithm", "pathfinding"),
            ),
            SemanticConcept(
                "concept_frontier_relaxation",
                "Frontier and relaxation",
                "Heap ordering, neighbor traversal, and improved-distance updates.",
                (
                    "dijkstra_frontier",
                    "dijkstra_frontier_loop",
                    "dijkstra_neighbors",
                    "dijkstra_relax_check",
                    "a_star_initial_frontier",
                    "a_star_frontier_loop",
                    "a_star_neighbors",
                    "a_star_relax_check",
                ),
                ("heap", "runtime", "invariant"),
            ),
        ),
        semantic_relations=(
            AuthoredSemanticRelation(
                "semantic_relation_a_star_refines_dijkstra",
                a_star.id,
                algorithm.id,
                AuthoredRelationKind.DEPENDS_ON,
                "heuristic refinement of",
                "A* retains relaxation while prioritizing the frontier by estimated cost.",
            ),
            AuthoredSemanticRelation(
                "semantic_relation_search_uses_frontier",
                "concept_pathfinding_search",
                "concept_frontier_relaxation",
                AuthoredRelationKind.IMPLEMENTS,
                "implemented through",
                "Both strategies share the frontier-and-relaxation conceptual core.",
            ),
        ),
        projection_definitions=(
            ProjectionDefinition(
                "projection_pathfinding_core",
                "Pathfinding conceptual core",
                scope_id="concept_pathfinding_search",
                object_kinds=(
                    SemanticObjectKind.CONCEPT,
                    SemanticObjectKind.FUNCTION,
                    SemanticObjectKind.STRUCTURE,
                    SemanticObjectKind.OPERATION,
                ),
                relation_kinds=(
                    SemanticRelationKind.CONCEPTUALLY_CONTAINS,
                    SemanticRelationKind.AUTHORED,
                    SemanticRelationKind.CALLS,
                ),
                direction=TraversalDirection.OUTGOING,
                max_depth=8,
                grouping=ProjectionGrouping.CONCEPT,
                decorations=(ProjectionDecoration.KIND, ProjectionDecoration.DETAIL),
                layout=ProjectionLayout.RADIAL,
                include_isolated=False,
            ),
        ),
    )


def _instrument_diagram(
    identifier: str,
    title: str,
    module: str,
    atoms: tuple[DrakonAtom, ...],
    *,
    parameters: tuple[ParameterSpec, ...] = (),
    return_annotation: str | None = None,
    description: str,
) -> DrakonDiagram:
    stable = identifier.replace("_", "-")
    return DrakonDiagram(
        id=f"diagram_bci_{stable}",
        title=title,
        header=Header(
            f"header_bci_{stable}",
            FunctionSpec(
                identifier,
                title,
                parameters=parameters,
                return_annotation=return_annotation,
                docstring=description,
                module=module,
            ),
        ),
        body=Sequence(f"sequence_bci_{stable}", atoms),
        end=End(f"end_bci_{stable}"),
        description=description,
    )


def _computational_instrument_project() -> Project:
    add_vectors = _instrument_diagram(
        "add_vectors",
        "Add instrument vectors",
        "math.vectors",
        (
            Transfer(
                "return_bci_add_vectors",
                TransferKind.RETURN,
                "tuple(a + b for a, b in zip(left, right, strict=True))",
            ),
        ),
        parameters=(
            ParameterSpec("left", annotation="tuple[float, ...]"),
            ParameterSpec("right", annotation="tuple[float, ...]"),
        ),
        return_annotation="tuple[float, ...]",
        description="Combine two equal-length instrument vectors element by element.",
    )
    arithmetic_mean = _instrument_diagram(
        "arithmetic_mean",
        "Compute arithmetic mean",
        "math.numerical",
        (
            If(
                "if_bci_values_empty",
                "values",
                Sequence("sequence_bci_values_present"),
                Sequence(
                    "sequence_bci_values_empty",
                    (
                        Transfer(
                            "raise_bci_values_empty",
                            TransferKind.RAISE,
                            'ValueError("values must not be empty")',
                        ),
                    ),
                ),
                preferred_truth=True,
            ),
            Transfer(
                "return_bci_arithmetic_mean",
                TransferKind.RETURN,
                "sum(values) / len(values)",
            ),
        ),
        parameters=(ParameterSpec("values", annotation="tuple[float, ...]"),),
        return_annotation="float",
        description="Reject an empty sample and compute its deterministic arithmetic mean.",
    )
    make_snapshot = _instrument_diagram(
        "make_snapshot",
        "Build model snapshot",
        "model.snapshots",
        (
            Call(
                "call_bci_snapshot_mean",
                "arithmetic_mean(samples)",
                result_target="average",
                target_diagram_id=arithmetic_mean.id,
                arguments="samples",
            ),
            Transfer(
                "return_bci_snapshot",
                TransferKind.RETURN,
                '{"samples": samples, "mean": average}',
            ),
        ),
        parameters=(ParameterSpec("samples", annotation="tuple[float, ...]"),),
        return_annotation="dict[str, object]",
        description="Create an immutable-style model snapshot from instrument samples.",
    )
    euler_step = _instrument_diagram(
        "euler_step",
        "Advance simulation state",
        "simulation.integrators",
        (
            Transfer(
                "return_bci_euler_step",
                TransferKind.RETURN,
                "state + derivative * dt",
            ),
        ),
        parameters=(
            ParameterSpec("state", annotation="float"),
            ParameterSpec("derivative", annotation="float"),
            ParameterSpec("dt", annotation="float"),
        ),
        return_annotation="float",
        description="Advance one scalar state with an explicit Euler integration step.",
    )
    signal_summary = _instrument_diagram(
        "signal_summary",
        "Summarize telemetry signal",
        "telemetry.signals",
        (
            Transfer(
                "return_bci_signal_summary",
                TransferKind.RETURN,
                "f\"{len(snapshot['samples'])} samples @ mean {snapshot['mean']:.2f}\"",
            ),
        ),
        parameters=(ParameterSpec("snapshot", annotation="dict[str, object]"),),
        return_annotation="str",
        description="Turn a model snapshot into a compact operator-facing signal.",
    )
    run_instrument = _instrument_diagram(
        "run_instrument",
        "Run instrument pipeline",
        "simulation.scheduler",
        (
            Assignment(
                "assignment_bci_left_samples",
                "left_samples",
                "(1.0, 2.0, 3.0)",
                "tuple[float, ...]",
            ),
            Assignment(
                "assignment_bci_right_samples",
                "right_samples",
                "(0.5, -0.5, 1.0)",
                "tuple[float, ...]",
            ),
            Call(
                "call_bci_add_vectors",
                "add_vectors(left_samples, right_samples)",
                result_target="samples",
                target_diagram_id=add_vectors.id,
                arguments="left_samples, right_samples",
            ),
            Call(
                "call_bci_euler_step",
                "euler_step(10.0, -0.25, 2.0)",
                result_target="state",
                target_diagram_id=euler_step.id,
                arguments="10.0, -0.25, 2.0",
            ),
            Call(
                "call_bci_make_snapshot",
                "make_snapshot(samples)",
                result_target="snapshot",
                target_diagram_id=make_snapshot.id,
                arguments="samples",
            ),
            Call(
                "call_bci_signal_summary",
                "signal_summary(snapshot)",
                result_target="signal",
                target_diagram_id=signal_summary.id,
                arguments="snapshot",
            ),
            Transfer(
                "return_bci_run_instrument",
                TransferKind.RETURN,
                (
                    '{"samples": samples, "mean": snapshot["mean"], '
                    '"state": state, "signal": signal}'
                ),
            ),
        ),
        return_annotation="dict[str, object]",
        description="Coordinate math, integration, model, and telemetry subsystems.",
    )
    format_scope = _instrument_diagram(
        "format_scope",
        "Format supervisory scope",
        "ui.scope",
        (
            Transfer(
                "return_bci_format_scope",
                TransferKind.RETURN,
                (
                    "f\"BCI scope | samples={result['samples']} | "
                    "mean={result['mean']:.2f} | state={result['state']:.2f} | "
                    "{result['signal']}\""
                ),
            ),
        ),
        parameters=(ParameterSpec("result", annotation="dict[str, object]"),),
        return_annotation="str",
        description="Present a compact human-supervisory view of an instrument result.",
    )
    replay_check = _instrument_diagram(
        "replay_is_deterministic",
        "Check deterministic replay",
        "testing.replay_checks",
        (
            Call(
                "call_bci_replay_first",
                "run_instrument()",
                result_target="first",
                target_diagram_id=run_instrument.id,
            ),
            Call(
                "call_bci_replay_second",
                "run_instrument()",
                result_target="second",
                target_diagram_id=run_instrument.id,
            ),
            Transfer(
                "return_bci_replay_check",
                TransferKind.RETURN,
                "first == second",
            ),
        ),
        return_annotation="bool",
        description="Run the complete instrument twice and compare the resulting snapshots.",
    )
    main = _instrument_diagram(
        "main",
        "Instrument application",
        "main",
        (
            Call(
                "call_bci_main_run",
                "run_instrument()",
                result_target="result",
                target_diagram_id=run_instrument.id,
            ),
            Call(
                "call_bci_main_scope",
                "format_scope(result)",
                result_target="scope_text",
                target_diagram_id=format_scope.id,
                arguments="result",
            ),
            Output("output_bci_scope", "scope_text"),
            Call(
                "call_bci_main_replay",
                "replay_is_deterministic()",
                result_target="replay_ok",
                target_diagram_id=replay_check.id,
            ),
            Output("output_bci_replay", 'f"Replay deterministic: {replay_ok}"'),
        ),
        description="Runnable entry point for the multi-package computational instrument.",
    )

    return Project(
        id="project_bespoke_computational_instrument",
        title="Bespoke Computational Instrument",
        description=(
            "A working multi-directory visual Python system. Nine DRAKON callables cooperate "
            "across math, model, simulation, telemetry, UI, and replay-testing packages."
        ),
        documents=(
            main,
            add_vectors,
            arithmetic_mean,
            make_snapshot,
            euler_step,
            run_instrument,
            signal_summary,
            format_scope,
            replay_check,
        ),
        program_model=_example_program(
            package="bci",
            modules=(
                _example_module(
                    "math.vectors",
                    "",
                    docstring="Vector operations for instrument sample channels.",
                    after="",
                ),
                _example_module(
                    "math.numerical",
                    "",
                    docstring="Small numerical foundations for instrument models.",
                    after="",
                ),
                _example_module(
                    "model.snapshots",
                    "from bci.math.numerical import arithmetic_mean",
                    docstring="Stable model snapshots shared across subsystem boundaries.",
                    after="",
                ),
                _example_module(
                    "simulation.integrators",
                    "",
                    docstring="Deterministic numerical integration primitives.",
                    after="",
                ),
                _example_module(
                    "telemetry.signals",
                    "",
                    docstring="Operator-facing telemetry summaries.",
                    after="",
                ),
                _example_module(
                    "simulation.scheduler",
                    (
                        "from bci.math.vectors import add_vectors\n"
                        "from bci.model.snapshots import make_snapshot\n"
                        "from bci.simulation.integrators import euler_step\n"
                        "from bci.telemetry.signals import signal_summary"
                    ),
                    docstring="Cross-subsystem instrument orchestration.",
                    after="",
                ),
                _example_module(
                    "ui.scope", "", docstring="Human-supervisory presentation helpers.", after=""
                ),
                _example_module(
                    "testing.replay_checks",
                    "from bci.simulation.scheduler import run_instrument",
                    docstring="Executable deterministic replay checks.",
                    after="",
                ),
                _example_module(
                    "main",
                    (
                        "from bci.simulation.scheduler import run_instrument\n"
                        "from bci.testing.replay_checks import replay_is_deterministic\n"
                        "from bci.ui.scope import format_scope"
                    ),
                    docstring="Bespoke computational instrument entry point.",
                    after="",
                ),
            ),
            entrypoint_callable_id=main.id,
            startup="",
        ),
    )


def _session_from_project(
    project: Project, *, computations: ComputationService | None = None
) -> ProjectSession:
    if project.documents:
        project = initialize_project_documents(project, project.documents)
    authority = ProjectAuthority(project)
    client = CodeVisualizerClient(authority, actor_id="desktop-example")
    return ProjectSession(authority, client, None, -1, computations=computations)


def _edit_example_atom(
    session: ProjectSession,
    index: int,
    field: str,
    value: str,
) -> None:
    diagram = session.authority.snapshot().documents[0]
    if not isinstance(diagram, DrakonDiagram):
        raise ExampleBuildError("Example document is not DRAKON")
    atom = diagram.body.atoms[index]
    _accepted(
        session.client.set_drakon_text(diagram.id, atom.id, field, value),
        f"edit {field}",
    )


def example_session(
    example_id: str,
    *,
    computations: ComputationService | None = None,
    destination: Path | None = None,
) -> ProjectSession:
    definition = next((d for d in PHYSICAL_EXAMPLE_CATALOG if d.id == example_id), None)
    if definition is not None and definition.resource_directory is not None:
        from code_visualizer.application.resource_examples import materialize_example

        if destination is None:
            raise ExampleBuildError(
                "Choose a new project folder for the example and its retained inputs"
            )
        return materialize_example(
            definition.resource_directory, destination, computations=computations
        )
    progression = partial(_progression_session, computations=computations)
    from_project = partial(_session_from_project, computations=computations)
    if example_id == "dc_divider":
        return from_project(dc_divider_project())
    if example_id == "spring_equation":
        return from_project(spring_equation_project())
    if example_id == "spring_cad":
        from code_visualizer.application.cad_examples import spring_cad_project

        return from_project(spring_cad_project())
    if example_id == "diffusion_field":
        from code_visualizer.application.field_examples import diffusion_project

        return from_project(diffusion_project())
    if example_id == "electrothermal":
        from code_visualizer.application.coupled_examples import electrothermal_project

        return from_project(electrothermal_project())
    if example_id == "axial_bar":
        from code_visualizer.application.axial_examples import axial_cad_project

        return from_project(axial_cad_project())
    if example_id == "adaptive_diffusion":
        from code_visualizer.application.adaptive_examples import adaptive_diffusion_project

        return from_project(adaptive_diffusion_project())
    if example_id == "hello_world":
        return hello_world_session(computations=computations)
    if example_id == "python_modules":
        return python_modules_session(computations=computations)
    if example_id == "values":
        session = progression("Values and Assignment Example", ("assignment", "output"))
        _edit_example_atom(session, 0, "value", "6 * 7")
        _edit_example_atom(session, 1, "expression", 'f"The answer is {result}"')
        return session
    if example_id == "decisions":
        return progression("Binary Decision Example", ("assignment", "if", "output"))
    if example_id == "select_match":
        session = progression(
            "Select and Match Example",
            ("assignment", "select", "match_select", "output"),
        )
        _edit_example_atom(session, 0, "target", "value")
        _edit_example_atom(session, 0, "value", "1")
        _edit_example_atom(session, 3, "expression", 'f"selected value: {value}"')
        return session
    if example_id == "loops":
        return progression(
            "Loop Progression Example",
            ("while_loop", "do_first_loop", "for_loop", "tree_bfs_loop", "output"),
        )
    if example_id == "contexts":
        return progression("Contexts and Exceptions Example", ("with", "try", "output"))
    if example_id == "timing":
        return progression(
            "Timing and Synchronization Example",
            ("start_timer", "delay", "period", "synchronizer", "output"),
        )
    if example_id == "parallel":
        return progression("Parallel Processes Example", ("parallel", "output"))
    if example_id == "async":
        return progression(
            "Async Python Example",
            ("await_call", "async_for_loop", "async_parallel", "output"),
            callable_kind=CallableKind.ASYNC,
        )
    if example_id == "generators":
        session = progression(
            "Generator Example",
            ("output", "yield", "yield_from"),
            callable_kind=CallableKind.GENERATOR,
        )
        _edit_example_atom(session, 0, "expression", '"generator started"')
        _edit_example_atom(session, 1, "expression", "1")
        _edit_example_atom(session, 2, "expression", "(2, 3)")
        return session
    if example_id == "classes":
        return _class_example_session(computations=computations)
    if example_id == "silhouette":
        return progression("Golden Node Silhouette Example", ("silhouette", "output"))
    if example_id == "first_delivery":
        return from_project(_first_delivery_project())
    if example_id == "dijkstra":
        return from_project(_dijkstra_project())
    if example_id == "computational_instrument":
        return from_project(_computational_instrument_project())
    if example_id == "traffic_light":
        return from_project(authored_traffic_light_project())
    raise ExampleBuildError(f"Unknown example {example_id!r}")
