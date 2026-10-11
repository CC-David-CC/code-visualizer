# Live test, trace, and debug

The diagram, generated/source-mapped code, and console are one indivisible document.
Choose diagram-only, code-only, side-by-side, stacked, or tabbed layout. Detaching an
outer document moves this entire trio and its live process state.

## F6: run the current diagram

F6 lowers the active callable in its owning Python project, materializes the emitted
files in a disposable directory, and starts an ordinary local Python child process.
Saving the project first is not required. Output and errors appear in the document
console, which retains a bounded number of lines. Use this after editing one operation
or branch.

The generated placeholder fields are valid Python, so a newly inserted construct can
run before customization. An empty ordinary callable runs as `pass`.

Run, trace, debug, and generated launchers use the same immutable `InvocationSpec`.
It carries the canonical callable identity, callable kind, method owner and kind,
and structured literal arguments. A shared renderer handles ordinary and asynchronous
functions, generators, asynchronous generators, and instance/class/static methods.
Generators are consumed to completion; yielded values are not printed automatically.
Every project execution surface uses the generated launcher's discard-return policy.
Trace records callable returns as events; use an Output operation to print a returned
value. No execution surface evaluates the combined code preview as a Python module.

Canonical execution binds arguments against the selected `ProgramParameter` signature
before starting a process. Required values, positional-only and keyword-only parameters,
variadic parameters, and implicit method receivers use the same binding check. Binding
does not evaluate defaults, annotations, or argument expressions.

Per-diagram Run, Trace, and Debug use the document's argument field. The selected
invocation replaces the saved entrypoint and its arguments only in the disposable
build snapshot. A valid selected invocation can therefore run while the saved project
entrypoint needs different arguments; the canonical project settings stay unchanged.
Whole-project generation and execution continue to validate the saved entrypoint.

## F7: trace the current diagram

F7 runs the same isolated execution worker as Debug in non-pausing record mode. Its
bounded `DebugEvent` stream uses the same checkpoints, runtime deltas, semantic symbol
bindings, and source-map identities as an interactive session. Line events map to
stable semantic/field IDs plus an optional presentation document and highlight both
the icon and code; the recorded
timeline can be replayed through every runtime-aware projection. Trace does not infer
identity from generated names and is not a separate textual tracing architecture.

## Interactive debug

Debug Current launches an isolated debugger worker. Breakpoints may be placed from
diagram objects or source lines. Continue, step, stop, restart, stdin, call stack,
changed locals, exceptions, and bounded history remain in the unified document.
When execution pauses, both the semantic object and exact source span are revealed.

The worker executes the same emitted launcher and package files. Launcher, module
initializer, and callable events retain their actual file paths. A breakpoint is a
file-qualified source location; equal line numbers in other files do not collide.
Without a breakpoint, stepping begins in the launcher or module initialization.
Use Step Into to enter its callable, then Step Over to advance within that function.

Each launch is pinned to an execution-session ID, project revision, and artifact
revision. Editing while paused does not reinterpret the old process: the UI reports
“running revision N; project is now N+1” until restart.

Locals are expandable runtime graphs, not only `repr()` strings. Bindings point to
typed values/objects and carry canonical symbol and frame IDs; lists, tuples, mappings,
sets, aliases, cycles, and safe instance fields retain identity. Capture depth,
children, node count, and previews are bounded. The worker emits periodic checkpoints
and intermediate deltas. A bounded `RuntimeTraceStore` retains those compact records,
reconstructs requested history from the nearest checkpoint, and caches only a few
recent graphs. Open **Code Visualizer > Runtime Values** to inspect the same session
spatially, or use `runtime.active` from the automation API.

## F5: run the complete generated project

F5 checks the artifact manifest, revision, and hashes. A missing/stale set is generated
in the background first; a modified external set is not overwritten silently. The
configured runtime profile supplies interpreter, working directory, and environment.
Callable arguments belong to the canonical entrypoint. Output appears in Python
Development > Run Output.

Wheel/source installations use their active Python interpreter. Native frozen bundles
use a private child-Python entry in the packaged runtime for built-in and bundled
modules, so Run/Trace/Debug never re-enter the public CLI parser. Set **Interpreter**
in the visible run profile when the project needs a particular virtual environment or
third-party packages; that configured interpreter takes precedence.

## Python module ownership and remaining limits

Run, Trace, Debug, and saved launchers preserve separate Python module namespaces.
Canonical package modules own their `__init__.py` bodies, including relative imports
and initialization order. Real files also support `__file__`, source inspection and
package resources. Private nested-class members and private parameters use shared
Python name resolution.

A callable marked as a generator without any `yield` still emits a body that Python
treats as an ordinary function. Its declared callable kind does not insert a hidden
yield; include the appropriate generator operation before executing it.

## Stopping and limits

Shift+F6 stops the active per-document or project process. Nonterminating runs are
terminated and reported as stopped. stdout/stderr, trace history, console text, and
protocol messages are bounded to protect the studio from accidental output floods.

These processes use the current OS user's permissions. They provide process isolation
and termination, not a security sandbox. Opening, previewing, validating, saving,
generating, and exporting never execute project Python; Run/Trace/Debug are explicit
execution boundaries.
