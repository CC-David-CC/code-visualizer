"""Operational command-line adapter over the headless project service."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from code_visualizer import __version__
from code_visualizer.application.computation_service import ComputationService
from code_visualizer.application.git import (
    GitError,
    GitRepository,
    first_untracked_adoption,
    has_git_ancestor,
)
from code_visualizer.application.git_service import GitProjectController
from code_visualizer.application.headless import HeadlessService
from code_visualizer.application.invocations import invocation_for_document
from code_visualizer.application.messages import CommandAccepted, CommandResult
from code_visualizer.application.project_factory import create_default_project
from code_visualizer.application.session import ProjectSession
from code_visualizer.automation.mcp import McpServerAdapter, run_mcp_stdio
from code_visualizer.automation.service import AccessMode, AutomationCapability, AutomationService
from code_visualizer.automation.websocket import (
    AccessGrant,
    AutomationWebSocketServer,
    new_bearer_token,
)
from code_visualizer.config import PRODUCT
from code_visualizer.domain.common import DocumentKind, JsonValue
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.project import Project
from code_visualizer.execution import run_generated, trace_project
from code_visualizer.generation import (
    GenerationError,
    generate_python_project,
    load_generation_manifest,
)
from code_visualizer.generation.artifacts import ArtifactGenerationError
from code_visualizer.persistence import ProjectStore
from code_visualizer.persistence.serialization import normalized_project_json
from code_visualizer.sdk import AsyncRemoteClient, RemoteRpcError
from code_visualizer.validation import Severity, assess_project


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="code-visualizer", description=PRODUCT.name)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--new-project-json",
        action="store_true",
        help="print a deterministic in-memory starter project snapshot",
    )
    subparsers = parser.add_subparsers(dest="command")

    create = subparsers.add_parser("new", help="create a native project directory")
    create.add_argument("path")
    create.add_argument("--title", default="Untitled Project")

    show = subparsers.add_parser("show", help="print the recovered canonical snapshot")
    show.add_argument("path")

    rename = subparsers.add_parser("rename", help="rename a project")
    rename.add_argument("path")
    rename.add_argument("title")
    rename.add_argument("--actor", default="cli")

    add_diagram = subparsers.add_parser("add-diagram", help="create a diagram")
    add_diagram.add_argument("path")
    add_diagram.add_argument("kind", choices=[kind.value for kind in DocumentKind])
    add_diagram.add_argument("title")
    add_diagram.add_argument("--identifier")
    add_diagram.add_argument("--actor", default="cli")

    insert = subparsers.add_parser("insert", help="insert a core DRAKON atom")
    insert.add_argument("path")
    insert.add_argument("diagram_id")
    insert.add_argument("atom_kind", choices=["action", "output", "assignment"])
    insert.add_argument("--index", type=int, default=0)
    insert.add_argument("--source")
    insert.add_argument("--target")
    insert.add_argument("--value")
    insert.add_argument("--actor", default="cli")

    undo = subparsers.add_parser("undo", help="undo the actor's latest compatible command")
    undo.add_argument("path")
    undo.add_argument("--actor", default="cli")

    redo = subparsers.add_parser("redo", help="redo the actor's latest undone command")
    redo.add_argument("path")
    redo.add_argument("--actor", default="cli")

    recover = subparsers.add_parser("recover", help="promote the newest durable revision")
    recover.add_argument("path")

    validate = subparsers.add_parser("validate", help="print actionable project diagnostics")
    validate.add_argument("path")

    generate = subparsers.add_parser("generate", help="atomically generate the saved project")
    generate.add_argument("path")

    run = subparsers.add_parser("run", help="run the current complete generated manifest")
    run.add_argument("path")

    trace = subparsers.add_parser("trace", help="trace one diagram from an isolated snapshot")
    trace.add_argument("path")
    trace.add_argument("diagram_id")
    trace.add_argument("--arguments", default="")

    for command, description in (
        ("compute", "execute a registered semantic computation backend"),
        ("export-plan", "publish a portable computation terminal and plan"),
    ):
        computation = subparsers.add_parser(command, help=description)
        computation.add_argument("path")
        computation.add_argument("--backend", required=True)
        computation.add_argument("--backend-version", default="1")
        computation.add_argument(
            "--model", help="canonical domain model identity; omit for authored Python"
        )
        computation.add_argument("--seed", type=int)
        computation.add_argument(
            "--configuration",
            default="{}",
            help="object of parameter names to typed canonical JSON values",
        )
        if command == "export-plan":
            computation.add_argument("--output", required=True, help="new plan receipt file")
            computation.add_argument(
                "--protobuf",
                action="store_true",
                help="write the typed protobuf plan (also selected by .pb suffix)",
            )
    worker = subparsers.add_parser(
        "run-plan", help="run a portable terminal without loading an editor project"
    )
    worker.add_argument("plan")
    worker.add_argument(
        "--protobuf",
        action="store_true",
        help="read a typed protobuf plan (also selected by .pb suffix)",
    )
    worker.add_argument(
        "--resources", required=True, help="directory containing the resources/evidence stores"
    )

    serve = subparsers.add_parser(
        "serve",
        help="host one project authority for simultaneous GUI, Python, CLI, and MCP clients",
    )
    serve.add_argument("path")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--token")
    serve.add_argument("--allow-remote", action="store_true")

    rpc = subparsers.add_parser("rpc", help="call a semantic method on a live authority")
    rpc.add_argument("endpoint")
    rpc.add_argument("method")
    rpc.add_argument("--token", required=True)
    rpc.add_argument("--actor", default="cli")
    rpc.add_argument("--mode", choices=[mode.value for mode in AccessMode], default="commit")
    rpc.add_argument("--params", default="{}")

    mcp = subparsers.add_parser(
        "mcp",
        help="bridge an MCP stdio host to the semantic project authority",
    )
    mcp.add_argument("endpoint")
    mcp.add_argument("--token", required=True)
    mcp.add_argument("--actor", default="mcp-agent")
    mcp.add_argument("--mode", choices=[mode.value for mode in AccessMode], default="proposal")
    return parser


def _result_data(result: CommandResult) -> dict[str, JsonValue]:
    if isinstance(result, CommandAccepted):
        return {
            "affected_ids": list(result.affected_ids),
            "revision": result.revision,
            "status": "accepted",
        }
    return {
        "code": result.code,
        "current_revision": result.current_revision,
        "details": result.details,
        "message": result.message,
        "status": "rejected",
    }


def _emit_result(result: CommandResult) -> int:
    print(json.dumps(_result_data(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if isinstance(result, CommandAccepted) else 2


def _path(args: argparse.Namespace) -> Path:
    return Path(str(args.path))


def _actor(args: argparse.Namespace) -> str:
    return str(args.actor)


def _load_project(root: Path) -> Project:
    """A Git checkout is an explicit snapshot, never a lower-revision recovery candidate."""
    if has_git_ancestor(root.resolve()):
        repository = GitRepository(root)
        if not first_untracked_adoption(repository):
            return repository.load_project()
    return ProjectStore(root).recover()


async def _serve_project(args: argparse.Namespace) -> int:
    token = str(args.token) if args.token else new_bearer_token()
    port = int(args.port)
    reload_requested = asyncio.Event()
    loop = asyncio.get_running_loop()

    def git_changed(result: object) -> None:
        if getattr(result, "reload_required", False):
            loop.call_soon_threadsafe(reload_requested.set)

    # One scientific host outlives editor/endpoint replacement. Interactive
    # debugging still retires with its ordinary AutomationService.
    computations = ComputationService()
    controller: GitProjectController | None = None
    try:
        session = ProjectSession.open(_path(args), actor_id="headless", computations=computations)
        controller = GitProjectController(session, changed=git_changed)
        while True:
            active = controller.session

            def active_root(selected: ProjectSession = active) -> Path | None:
                return selected.root

            service = AutomationService(
                active.authority,
                project_root=active_root,
                kernel=active.kernel,
                git=controller,
            )
            server = AutomationWebSocketServer(
                service,
                host=str(args.host),
                port=port,
                grants=(AccessGrant(token, frozenset(AutomationCapability)),),
                allow_remote=bool(args.allow_remote),
            )
            started = False
            try:
                await server.start()
                started = True
                port = server.port
                active.update_authority_endpoint(server.endpoint)
                print(
                    json.dumps(
                        {
                            "endpoint": server.endpoint,
                            "project_id": active.authority.snapshot().id,
                            "revision": active.authority.revision,
                            "security": server.security_warning,
                            "token": token,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    flush=True,
                )
                while True:
                    await reload_requested.wait()
                    reload_requested.clear()
                    await asyncio.sleep(0.15)
                    try:
                        if controller.session is active:
                            # Ordinary Git checkout: use the existing loader.
                            await asyncio.to_thread(controller.reload_session)
                        # Freeze/fork already loaded its new worktree and journal.
                    except (GitError, OSError) as exc:
                        print(
                            json.dumps({"status": "git_reload_blocked", "message": str(exc)}),
                            file=sys.stderr,
                            flush=True,
                        )
                        continue
                    break
            finally:
                if started:
                    await server.stop()
                service.close()
                active.update_authority_endpoint(None)
                active.close()
    finally:
        if controller is not None:
            await asyncio.to_thread(controller.close_background, wait=True)
            controller.session.close()
        await asyncio.to_thread(computations.close)


def _rpc_params(raw: str) -> dict[str, JsonValue]:
    try:
        decoded: object = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--params is not valid JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
        raise ValueError("--params must be a JSON object")
    return {str(key): value for key, value in decoded.items()}


async def _rpc_call(args: argparse.Namespace) -> int:
    params = _rpc_params(str(args.params))
    async with AsyncRemoteClient(
        str(args.endpoint),
        str(args.token),
        actor_id=_actor(args),
        mode=AccessMode(str(args.mode)),
    ) as client:
        result = await client.call(str(args.method), params)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


async def _run_mcp(args: argparse.Namespace) -> int:
    async with AsyncRemoteClient(
        str(args.endpoint),
        str(args.token),
        actor_id=_actor(args),
        mode=AccessMode(str(args.mode)),
    ) as client:
        await client.subscribe()
        await run_mcp_stdio(McpServerAdapter(client))
    return 0


def _run_async(operation: object) -> int:
    try:
        return asyncio.run(operation)  # type: ignore[arg-type]
    except KeyboardInterrupt:
        return 130
    except (RemoteRpcError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 2


def _computation_command(args: argparse.Namespace) -> int:
    from code_visualizer.application.computation import (
        execute_computation,
        export_computation_plan,
        run_computation_plan,
    )
    from code_visualizer.domain.computation import ComputationParameter, ComputationRequest
    from code_visualizer.domain.evidence import ComputationOutcome
    from code_visualizer.extensions.builtin import builtin_registry
    from code_visualizer.persistence.computation import (
        computation_plan_from_data,
        computation_plan_to_data,
    )
    from code_visualizer.persistence.evidence import evidence_to_data
    from code_visualizer.persistence.evidence_store import EvidenceStore
    from code_visualizer.persistence.resource_store import ResourceStore, read_bounded
    from code_visualizer.persistence.values import canonical_value_from_data

    try:
        if args.command == "run-plan":
            plan_path = Path(str(args.plan))
            payload = read_bounded(plan_path, 16 * 1024 * 1024)
            if args.protobuf or plan_path.suffix.lower() == ".pb":
                from google.protobuf.message import DecodeError

                from code_visualizer.protocol.computation import computation_plan_from_proto
                from code_visualizer.protocol.v1.computation_pb2 import ComputationPlan as WirePlan

                wire_plan = WirePlan()
                try:
                    wire_plan.ParseFromString(payload)
                except DecodeError as exc:
                    raise ValueError("Malformed protobuf computation plan") from exc
                plan = computation_plan_from_proto(wire_plan)
            else:
                plan = computation_plan_from_data(json.loads(payload))
            resource_root = Path(str(args.resources))
            evidence = run_computation_plan(
                plan, builtin_registry(), ResourceStore(resource_root), EvidenceStore(resource_root)
            )
        else:
            configuration = json.loads(str(args.configuration))
            if not isinstance(configuration, dict) or any(
                not isinstance(name, str) for name in configuration
            ):
                raise ValueError("Configuration must be an object of named typed values")
            headless = HeadlessService.open(_path(args))
            try:
                assert headless.session is not None
                project = headless.authority.snapshot()
                request = ComputationRequest(
                    project.id,
                    project.revision,
                    str(args.backend),
                    str(args.backend_version),
                    None if args.model is None else str(args.model),
                    tuple(
                        ComputationParameter(name, canonical_value_from_data(value))
                        for name, value in sorted(configuration.items())
                    ),
                    args.seed,
                )
                if args.command == "export-plan":
                    plan = export_computation_plan(headless.session.kernel, request)
                    output = Path(str(args.output))
                    if args.protobuf or output.suffix.lower() == ".pb":
                        from code_visualizer.protocol.computation import computation_plan_to_proto

                        with output.open("xb") as binary_stream:
                            binary_stream.write(
                                computation_plan_to_proto(plan).SerializeToString(
                                    deterministic=True
                                )
                            )
                    else:
                        with output.open("x", encoding="utf-8", newline="\n") as stream:
                            json.dump(
                                computation_plan_to_data(plan),
                                stream,
                                ensure_ascii=True,
                                sort_keys=True,
                                indent=2,
                            )
                            stream.write("\n")
                    print(
                        json.dumps(
                            {
                                "status": "complete",
                                "plan": str(output.resolve()),
                                "revision": request.revision,
                            },
                            sort_keys=True,
                        )
                    )
                    return 0
                evidence = execute_computation(headless.session.kernel, request)
            finally:
                headless.close()
        print(json.dumps(evidence_to_data(evidence), ensure_ascii=True, sort_keys=True, indent=2))
        return 0 if evidence.outcome is ComputationOutcome.SUCCEEDED else 2
    except (ValueError, OSError) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "code": getattr(exc, "code", "COMPUTATION_INPUT"),
                    "message": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.new_project_json:
        print(normalized_project_json(create_default_project()), end="")
        return 0
    if args.command == "serve":
        return _run_async(_serve_project(args))
    if args.command == "rpc":
        return _run_async(_rpc_call(args))
    if args.command == "mcp":
        return _run_async(_run_mcp(args))
    if args.command in {"compute", "export-plan", "run-plan"}:
        return _computation_command(args)
    if args.command == "new":
        service = HeadlessService.create(_path(args), title=str(args.title))
        try:
            print(normalized_project_json(service.authority.snapshot()), end="")
        finally:
            service.close()
        return 0
    if args.command == "show":
        print(normalized_project_json(_load_project(_path(args))), end="")
        return 0
    if args.command == "recover":
        project = _load_project(_path(args))
        print(normalized_project_json(project), end="")
        return 0
    if args.command == "validate":
        project = _load_project(_path(args))
        assessment = assess_project(project)
        diagnostics = assessment.diagnostics
        print(
            json.dumps(
                {
                    "buildability": assessment.status.value,
                    "diagnostics": [
                        {
                            "category": item.category.value,
                            "code": item.code,
                            "diagram_id": item.diagram_id,
                            "field": item.field,
                            "message": item.message,
                            "object_id": item.object_id,
                            "severity": item.severity.value,
                            "suggested_repair": item.suggested_repair,
                        }
                        for item in diagnostics
                    ],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 2 if any(item.severity is Severity.ERROR for item in diagnostics) else 0
    if args.command == "generate":
        headless = HeadlessService.open(_path(args))
        try:
            assert headless.session is not None
            generation_result = headless.session.generate()
        except ArtifactGenerationError as exc:
            print(
                json.dumps({"message": str(exc), "status": "blocked"}, sort_keys=True),
                file=sys.stderr,
            )
            return 2
        finally:
            headless.close()
        print(
            json.dumps(
                {
                    "files": [
                        path.relative_to(generation_result.root).as_posix()
                        for path in generation_result.files
                    ],
                    "revision": generation_result.revision,
                    "root": str(generation_result.root),
                    "status": "complete",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "run":
        project = _load_project(_path(args))
        assessment = assess_project(project)
        if not assessment.buildable:
            first = assessment.blocking_diagnostics[0]
            print(
                json.dumps(
                    {
                        "code": first.code,
                        "message": first.message,
                        "status": "blocked",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        manifest = load_generation_manifest(_path(args))
        if manifest is None or manifest.get("revision") != project.revision:
            print(
                json.dumps(
                    {
                        "code": "ARTIFACTS_NOT_CURRENT",
                        "message": "Generate the current valid revision before running it.",
                        "status": "blocked",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
        artifact_root = _path(args).resolve() / "generated"
        launcher = artifact_root / "run_project.py"
        if not launcher.is_file():
            print(
                json.dumps(
                    {
                        "code": "ARTIFACTS_NOT_CURRENT",
                        "message": "Generate the current Python project launcher first.",
                        "status": "blocked",
                    },
                    sort_keys=True,
                )
            )
            return 2
        run_result = run_generated(launcher, working_directory=_path(args).resolve())
        print(run_result.stdout, end="")
        if run_result.stderr:
            print(run_result.stderr, end="", file=sys.stderr)
        return run_result.return_code
    if args.command == "trace":
        project = _load_project(_path(args))
        diagram_id = str(args.diagram_id)
        document = next(
            (
                item
                for item in project.documents
                if isinstance(item, DrakonDiagram) and item.id == diagram_id
            ),
            None,
        )
        if document is None:
            parser.error(f"DRAKON diagram {diagram_id!r} does not exist")
        try:
            invocation = invocation_for_document(project, diagram_id, str(args.arguments))
            live_project = generate_python_project(
                project,
                focus_diagram_id=diagram_id,
                invocation=invocation,
            )
        except GenerationError as exc:
            print(
                json.dumps({"message": str(exc), "status": "blocked"}, sort_keys=True),
                file=sys.stderr,
            )
            return 2
        trace_result = trace_project(
            live_project,
            project_revision=project.revision,
            artifact_revision=project.revision,
        )
        print(
            json.dumps(
                {
                    "events": [
                        {
                            "detail": event.detail,
                            "event": event.event,
                            "function": event.function,
                            "index": event.index,
                            "file_path": event.file_path,
                            "line": event.line,
                            "locals": dict(event.locals),
                        }
                        for event in trace_result.events
                    ],
                    "return_code": trace_result.run.return_code,
                    "stderr": trace_result.run.stderr,
                    "stdout": trace_result.run.stdout,
                    "truncated": trace_result.events_truncated,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return trace_result.run.return_code
    if args.command is None:
        parser.print_help()
        return 0

    service = HeadlessService.open(_path(args))
    client = service.client(_actor(args))
    try:
        if args.command == "rename":
            return _emit_result(client.rename_project(str(args.title)))
        if args.command == "add-diagram":
            return _emit_result(
                client.create_diagram(
                    DocumentKind(str(args.kind)),
                    str(args.title),
                    identifier=(None if args.identifier is None else str(args.identifier)),
                )
            )
        if args.command == "insert":
            return _emit_result(
                client.insert_drakon_atom(
                    str(args.diagram_id),
                    str(args.atom_kind),
                    int(args.index),
                    source=None if args.source is None else str(args.source),
                    target=None if args.target is None else str(args.target),
                    value=None if args.value is None else str(args.value),
                )
            )
        if args.command == "undo":
            return _emit_result(client.undo())
        if args.command == "redo":
            return _emit_result(client.redo())
    finally:
        client.close()
        service.close()
    parser.error(f"Unsupported command {args.command!r}")
