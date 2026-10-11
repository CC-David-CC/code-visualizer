# Python mapping

## One projection pipeline

Canonical project semantics lower to `PythonProjectIR`, which emits one
`GeneratedProject` containing real package files, launcher and source maps. Persistent
generated execution and temporary live Run/Trace/Debug execute those same files.
Combined source is a read-only preview, never an execution representation. Widgets
display emitted files and use file-qualified locations. Every emitted span records
its primary canonical `semantic_id`, field,
and an optional DRAKON `presentation_id`; canonical-only callables therefore map to
source without inventing a diagram identity.

Lowering starts exclusively at `ProgramModel` for every construct:

```text
ProgramFunction -> ProgramSequence -> ProgramAssignment / ProgramOutput
                                    / ProgramCall / ProgramIf / ProgramSelect
                                    / ProgramLoop / ProgramTry / ProgramWith
                                    / ProgramTransfer / ProgramParallel / timing / state
                -> role-tagged ProgramExpression.tree
                -> derived Python expression -> PythonProjectIR -> emitter
```

All DRAKON function and atom values are editor projections. Stale projected values
cannot change generated Python while the canonical model is unchanged. Lowering and
dependency closure never recover statements from a DRAKON document. Structural flow
validation reuses the existing context rules on values rendered from the canonical
function, including functions with no view.

The generation modules for Python entrypoints, lowering, IR, and emission do not
import DRAKON or application editors. They read `Project.program_model` directly.
Callable, parameter, method, control-flow, and parallel kind values originate
in neutral `domain.program_kinds`. Textual parameter/signature DTOs originate in
`domain.program_signatures`; lowering derives them from canonical typed expressions.
SVG artifact generation can still inspect DRAKON presentations to draw them, while
executable module ownership comes from the bound canonical function.

`FunctionIR.callable_id` is always the canonical callable identity.
`FunctionIR.presentation_id` is either the bound DRAKON document or `None`, and its
`signature_origin.semantic_id` remains the callable ID in both cases. Source-map v3
uses the same invariant for every span; it does not overload a diagram field with a
callable ID or a generic object field with a presentation header ID.

`ProgramExpression` has no stored source field. Text-entry commands parse once into a
complete tree; linked-symbol rename and rebinding transform that tree by stable identity.
The lowering boundary renders normalized Python from the tree. Argument lists and
chained assignment targets are structural role nodes, so forms such as `f(*xs, **kw)`
and `left = alias = value` do not rely on synthetic text or lossy splitting.

## Callable and project model

`ProgramFunction` represents sync, async, generator, and async-generator callables;
every Python parameter kind; defaults and annotations; decorators;
docstring; return annotation; and instance, class, or static method kind.
Function, parameter, and local `ProgramSymbol` IDs remain stable through rename.
`ProgramModule` and `ProgramClass` own ordered declarations and function references;
ownership is not duplicated on the function. A module's kind distinguishes ordinary
modules from authored package initializers. ProgramModel also owns imports, constants,
aliases, startup declarations and entrypoint semantics. `PythonRuntimeSettings` owns
interpreter, environment and run profiles. The Python Project workspace edits these
separate canonical records through the authority.

## Statement and expression mapping

| Semantic construct | Deterministic Python form |
|---|---|
| Empty Sequence | `pass` |
| Action | Parsed non-compound statements; hidden `if`/loop/Try/With/match/function/class topology is rejected. |
| Shelf | Plain/chained/unpacking `=`, annotated assignment, or augmented operator. |
| Output / Input | `print(...)`; typed target from optional converter around `input(...)`. |
| Call | Free expression or stable linked callable ID plus arguments; optional `await` and result target. |
| If | Preferred body emitted first; condition is inverted only when False is preferred. |
| Select | Ordered `if`/`elif`/`else` or `match`/`case` with guards. |
| Transfer | Return, Raise/from, Yield, Yield From, Break, or Continue. |
| Simple statement | Pass, del, global, nonlocal, assert, or expression statement. |
| Loop | While, do-first lowering, For, async For, WAIT, DFS, or BFS; Python loop `else` is preserved. |
| With / Try | Multiple sync/async contexts; except or except*, else, and finally. |
| Parallel | Joined `ThreadPoolExecutor` futures or `asyncio.TaskGroup`. |
| Silhouette | Readable named-state dispatcher such as `_golden_node_state`; no stable ID leaks into source. |

All Python expressions are accepted in expression roles when AST-valid,
including comprehensions, lambdas, f-strings, named expressions, slicing, and
await/async comprehensions in legal callable contexts. Python is parsed and
compiled without execution during validation or generation.

## Runtime profile

- Delay uses `max(0.0, float(seconds))` with `time.sleep` or
  `await asyncio.sleep`.
- Start Timer records `time.perf_counter()` under a readable generated name.
- Period sleeps only the remaining cadence and advances its deadline.
- Synchronizer compares monotonic elapsed time and chooses explicit bodies.
- Sync Parallel submits in declared order, joins futures in declared order,
  and re-raises a branch failure; executor shutdown joins remaining work.
- Async Parallel uses `TaskGroup`, whose failure policy cancels siblings and
  raises an exception group.
- DFS uses a reversed explicit stack so children are visited in source order;
  BFS uses `deque.popleft()`.
- WAIT retries while its condition is false and places a clamped Delay on the
  return path.
- Connector, Case, For End, Address, bus, and marker glyphs shape visible
  structure but never emit invented runtime calls.

Flow-sensitive diagnostics cover timer start-before-use, loop transfers,
await/yield legality, bare raise, except* transfers, linked Calls, and
silhouette termination/reachability.

## Generation boundary

Generation parses and compiles every output file before atomic promotion. Disk
generation is gated by project diagnostics; invalid edits remain saveable and
repairable while the preceding complete artifact set stays intact. F5/F6/F7
are explicit child-process actions and project code never executes on open,
preview, validation, autosave, or generation.
