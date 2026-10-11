# Automation API

Code Visualizer exposes the same typed semantic authority to the desktop, Python,
CLI, JSON-RPC, and MCP. Automation inserts and edits model objects; it never draws
pixel coordinates or fabricates DRAKON connector lines.

## Find the desktop endpoint

Open **View > Automation Access** or run **Show Automation Access** from the command
palette. The dock shows the loopback WebSocket endpoint, a hidden bearer token,
connected actors, their last revision/event, and agent proposals. The token is
created for the current project session and is cleared when that session closes.

The desktop keeps the endpoint on `127.0.0.1`. Treat the token as a password. Merely
having LLM edit access does not grant execution, generation, saving, or destructive
capabilities.

For a long-running headless authority, start a saved native project directly:

```powershell
code-visualizer serve .\my-project
```

The first JSON line contains `endpoint`, `token`, project/revision identity, and the
security posture. A non-loopback `--host` is rejected unless `--allow-remote` is
explicitly supplied; the server then prints a remote-binding warning.

## Typed Python client

```python
import asyncio

from code_visualizer.application.commands import (
    CreateDiagram,
    InsertDrakonAtom,
    RenameProject,
)
from code_visualizer.domain.common import DocumentKind
from code_visualizer.sdk import AsyncRemoteClient


async def edit(endpoint: str, token: str, diagram_id: str) -> None:
    async with AsyncRemoteClient(
        endpoint,
        token,
        actor_id="planning-agent",
    ) as client:
        await client.subscribe()
        result = await client.submit(
            InsertDrakonAtom(
                diagram_id,
                "action",
                0,
                source='print("Hello from the agent")',
            ),
            intent="Add the first executable step",
        )
        print(result)


asyncio.run(edit("ws://127.0.0.1:PORT", "TOKEN", "diagram_id"))
```

`submit()` supplies a unique operation ID and the most recently observed revision.
Repeating an operation ID is idempotent. A stale revision returns
`REVISION_CONFLICT`; it never relocates an edit to a different insertion target.
Use `snapshot()` or `subscribe(since_revision=...)` to rebase. If the bounded event
history no longer covers the requested revision, `subscribe` returns a canonical
snapshot and reports that resynchronization was required.

Typed transactions validate against a temporary snapshot and commit as one revision:

```python
result = await client.transaction(
    (RenameProject("Algorithms"), CreateDiagram(DocumentKind.MIND_MAP, "Plan")),
    intent="Name the project and add its design map",
)
```

Actor-scoped `preview_undo()` reports the target operation/revision, affected IDs,
and conflicts. `undo()` and `redo()` add compensating journaled revisions; they do
not rewrite history.

## JSON-RPC 2.0 over WebSocket

Send `Authorization: Bearer TOKEN` in the WebSocket upgrade, then initialize the
connection before any other method:

```json
{"jsonrpc":"2.0","id":1,"method":"service.initialize","params":{"actor_id":"agent","mode":"commit"}}
```

Subscribe to canonical and collaboration events:

```json
{"jsonrpc":"2.0","id":2,"method":"service.subscribe","params":{"since_revision":0}}
```

The server publishes `service.event` notifications. Every event includes schema and
project revision, actor, operation ID, affected IDs, timestamp, event type, and a
bounded payload. Event families include semantic commits, presence, proposals,
validation, generation, execution/output, conflicts, permission rejection, and
snapshot resynchronization.

A generic semantic command has this shape:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "command.execute",
  "params": {
    "command_type": "drakon.insert",
    "expected_revision": 7,
    "intent": "Add success output",
    "operation_id": "agent-op-104",
    "payload": {
      "atom_id": "action_success",
      "atom_kind": "output",
      "diagram_id": "diagram_main",
      "index": 2,
      "sequence_id": "sequence_true",
      "source": "result"
    }
  }
}
```

External mutations require an integer `expected_revision`. Prefer
`drakon.list_insertions` to obtain stable semantic `sequence_id` and index pairs for
all eligible horizontal and vertical route segments. Do not infer flow from canvas
coordinates.

Python modules and classes are canonical objects with stable project IDs. Create a
module or class with its typed declaration payload, then create or move a function
using `owner_id`; paths and names are editable properties, not ownership references.
An omitted insertion index preserves position when the function already has that
owner; an explicit index requests a declaration-order change.
`program.configure` atomically replaces the typed package/module/entrypoint header
without replacing the function/symbol tables. This supports coordinated ownership
moves and uses the ordinary transaction/history contract. `python.configure_runtime`
accepts only run profiles and the active profile; the old executable
`python.replace_module_setup` command is not accepted by the live authority.

For executable behavior that does not need a presentation document, use the canonical
program methods directly:

```text
program.configure
program.module.put
program.module.delete
program.class.put
program.class.delete
program.declaration.set_text
program.entrypoint.configure
program.function.create
program.function.delete
program.function.set_owner
program.function.replace_signature
python.configure_runtime
program.statement.insert
program.statement.move
program.statement.delete
program.expression.replace
program.symbol.rename
```

For example, these two calls create a callable in an existing module with ID
`module_greeter` and add a call to `print` without first creating or drawing a DRAKON document:

```json
{"jsonrpc":"2.0","id":10,"method":"program.function.create","params":{"expected_revision":7,"operation_id":"create-greet","function_id":"function_greet","body_sequence_id":"sequence_greet","symbol_id":"symbol_greet","identifier":"greet","display_name":"Greet","owner_id":"module_greeter"}}
```

```json
{"jsonrpc":"2.0","id":11,"method":"program.statement.insert","params":{"expected_revision":8,"operation_id":"add-greeting","function_id":"function_greet","sequence_id":"sequence_greet","index":0,"statement_id":"statement_print","statement_kind":"call","expression":"print","arguments":"\"Hello\""}}
```

Direct creation/insertion supplies safe defaults for omitted opaque IDs, assignment
operator, argument text, branch sequence IDs, await state, and branch preference.
Supplying IDs explicitly is useful when another client needs to reference them in the
same planned transaction. Canonical functions generate through their owning module even
when no DRAKON view exists. Deletion requires the `destructive` capability; every
operation remains revisioned, journaled, observable, and undoable.

`service.capabilities` returns the exact protocol version, actor mode, grants, and
available methods. `service.operations` separately returns discoverable substantial
operation descriptors from the project-kernel capability registry. Invoke any one of
those statically registered operations without adding another dispatcher branch:

```json
{"jsonrpc":"2.0","id":9,"method":"capability.invoke","params":{"capability_id":"view.data","inputs":{"root_id":"diagram_dijkstra_algorithm"}}}
```

`capability.invoke` requires read permission and validates the capability ID and input
object. Capability-specific permissions still apply to the RPC methods that expose
generation, execution, saving, or destructive work; generic discovery is not a grant.
The version-1 semantic surface includes project snapshots and
diagram listing; canonical program/function/statement/expression/symbol authoring;
diagram lifecycle; DRAKON insertion/replacement/removal/move/wrap;
text/property/layout intent; mind-map editing; free-form editing; validation;
generation; test/trace/run; actor-aware history; search; and navigation.

Read-only semantic queries avoid internal document dataclasses:

```text
query.semantic_object       {"object_id": "..."}
query.children              {"namespace_id": "..."}
query.callers               {"function_id": "..."}
query.references            {"symbol_id": "..."}
query.control_flow          {"function_id": "..."}
query.data_dependencies     {"operation_id": "..."}
query.views_for             {"semantic_id": "..."}
query.projection            {"kind": "architecture|calls|control|data|concepts|drakon|mindmap|freeform|runtime", "root_id": null}
query.projection_definitions {}
query.compose_projection    {"definition": {...}}
runtime.active              {}
runtime.sessions            {}
runtime.history             {"execution_session_id": null}
capability.invoke           {"capability_id": "view.architecture", "inputs": {}}
```

Projection queries and view capabilities apply the active runtime overlay by default.
That means an external program or LLM sees the same active node, route, changed symbol,
and bounded runtime structure as the GUI while sharing the authority revision.

`view.set_anchor` is a revisioned mutation for linking mind-map/freeform presentation
objects to semantic object or relation IDs. Presence selection now enters the same
shared selection service used by the GUI, so agent focus is reflected without pointer
automation.

## Proposal mode and capabilities

Initialize an untrusted planning client with `"mode":"proposal"`. A direct mutation
is rejected. Submit the same command envelope with `proposal.create`; the response
contains its base revision, affected IDs, summary, and bounded deterministic diff.
The human sees it in **Automation & Collaboration** and explicitly accepts or rejects
it. Acceptance uses the proposal's original revision, so an intervening conflict is
visible rather than silently rebased.

Bearer grants are capability sets: `read`, `edit`, `propose`, `save`, `generate`,
`execute`, `destructive`, and `admin`. Execution is intentionally separate from
editing. A read-only token can subscribe and inspect but cannot mutate.

Presence is non-canonical and does not create a revision:

```python
await client.update_presence(
    selection=("diagram_main", "condition_ready"),
    preview="Changing the ready branch after human review",
)
await client.reveal("diagram_main", "condition_ready")
```

The desktop displays the actor and selection/navigation request on Qt's main thread.

## CLI against a live authority

Use `rpc` for scripts that must join an existing authority instead of opening a
second file-backed session:

```powershell
code-visualizer rpc ws://127.0.0.1:PORT project.list_diagrams --token TOKEN
code-visualizer rpc ws://127.0.0.1:PORT validate.project --token TOKEN
code-visualizer rpc ws://127.0.0.1:PORT command.execute --token TOKEN `
  --actor build-agent --params '{"command_type":"project.rename","expected_revision":0,"operation_id":"rename-1","intent":"Name project","payload":{"title":"Algorithms"}}'
```

`validate.project` and `validate.diagram` return an object with explicit
`buildability` (`buildable` or `blocked`) and a `diagnostics` array. An incomplete
canonical expression is reported as `PROGRAM_INCOMPLETE_EXPRESSION`; clients may keep
editing and saving it but must not request generation or execution until repaired.

Offline CLI commands (`new`, `show`, `rename`, `add-diagram`, `insert`, `validate`,
`generate`, `run`, and `trace`) use the same application service and native format,
but are intended for exclusive, non-live workflows.

## MCP adapter

Bridge an MCP host's stdio transport to the live authority:

```powershell
code-visualizer mcp ws://127.0.0.1:PORT --token TOKEN --actor coding-agent
```

The safe default is proposal mode. Add `--mode commit` only for a grant intended to
commit. MCP tools are deliberately semantic:

- `project_snapshot`, `list_diagrams`, and `list_drakon_insertions`;
- `semantic_object`, `semantic_projection`, `list_projection_definitions`,
  `compose_semantic_projection`, and `discover_operations`;
- `active_runtime` and `runtime_history`;
- `semantic_command` and `propose_semantic_command`;
- `validate_project` and `generate_preview`;
- `search_project`, `update_presence`, and `undo_my_last_command`.

There is no pixel draw, raw connector, shell, package-install, or arbitrary Python
execution tool. MCP errors are returned as structured tool errors. The stdio adapter
and WebSocket transport both enforce bounded message sizes.

## Embedded in-process client

Tests and single-process integrations may use `HeadlessService` and
`CodeVisualizerClient` directly. Multiple embedded clients still share one authority,
event stream, revisions, idempotency table, operation journal, and actor-aware history.
Use the WebSocket service when independently running programs need to collaborate.
