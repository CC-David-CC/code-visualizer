# One Python package execution representation

ProgramModel remains the canonical Python domain. Representation, ComputationBackend,
Evidence and Resource retain their separate meanings; this change does not introduce
other programming languages or require domain computations to become Python programs.

## Execution cutover

The previous live adapter embedded emitted modules in a combined source string and
installed a custom import loader. Its namespaces approximated a package, but its
module filenames did not exist. File inspection and package resource behavior could
therefore disagree with generated execution.

The replacement is:

```text
canonical Python ProgramModel
             |
       PythonProjectIR
             |
       GeneratedProject
       (files + launcher + file-local spans + origins)
             |
       +-----+--------------------+
       |                          |
persistent generated/       temporary execution tree
       |                          |
       +----------+---------------+
                  |
       ordinary Python import machinery
       Run / Trace / Debug / computation backend
```

Generation renders the launcher invocation once using the existing signature binder.
Execution adapters materialize those exact files and execute that launcher. They do
not regenerate callable expressions, pad module source, or emulate import loaders.
Temporary files remain available for the execution session and are removed after
its child has finished. Working-directory and interpreter preferences are runtime
configuration; they do not change what was emitted.

Debugger completion is an observable delivery boundary. The controller drains the
child's output streams, waits for process exit and removes its temporary file tree
before making a terminal event available. Public terminal state changes when the
caller consumes that event, after the preceding stdout events. A stop requested
during natural shutdown waits for cleanup instead of sending another command to an
exiting worker. This preserves both final console output and Windows file lifetime.

The shared file-launch bootstrap loads its own standard-library dependencies before
exposing the emitted root. At the launcher's first call it releases cached modules
that normal Python finders resolve to authored source in that root. Built-in and
frozen-module precedence remains intact. Run removes this one-shot trace immediately;
Debug retains its tracing callback. No import hook remains installed, and private
worker arguments do not become application arguments.

Combined source is a presentation only. Raw-source automation remains an explicit
single-file capability, distinct from execution of a canonical programming project.
No ProgramModel execution path converts a project into that raw-source capability.

## Managed computations and bounded delivery

The production computation service prepares captured revisions in a fixed trusted
worker. Validation, invocation binding and lowering complete there. The worker hands
back a disposable resource containing emitted files, source maps, origins and runtime
bindings. The host admits that resource and starts the established Python trace child;
it does not lower again or nest another computation worker around that child.

Managed artifact execution is a static composition decision. Currently only the exact
built-in Python backend definition, matching request and ProgramModel terminal have a
managed strategy. A different backend or version cannot acquire Python execution by
returning a Python-shaped artifact or setting `external_worker`. The Python backend
retains its published batch result contract. Explicit `InProcessDriver` injection is
available for embeddings and identity-sensitive tests; it is never an inferred
production fallback.

The private debugger event queue defaults to 256 entries, with an explicit bounded
capacity. A queued event is admitted only within the shared 2 MiB frame envelope.
Oversized event data fails with `protocol_limit`; semantic event contents are not
silently truncated. Authored output writes are split into chunks of at most 8,192
characters while preserving their text. Backpressure never holds the debugger command
lock, so cancellation can reach a worker even when its consumer stops draining events.
Diagnostic stderr retention is bounded to 65,536 characters.

Run and Trace capture stdout and stderr incrementally, up to the configured character
limit for each channel (one million by default). They retain the prefix and report
truncation without accumulating the remainder first. Console capture is a bounded
preview; large computed values belong in explicitly published typed resources.
Runtime history remains subject to its existing event and object-preview limits.

Completed editor traces are mapped and formatted on the existing completion thread.
An index over the requested file/line locations preserves each surface's explicit
source-span policy without rescanning the full map for every event: the diagram
uses the first matching span; the domain workbench uses the narrowest span, then
the earliest start, then original map order. Terminal events use the same lookup
while remaining separate from the captured trace-event list. The console preview contains
at most 65,536 characters, including at most 16,384 per output channel and 512 of
locals per event. An explicit notice distinguishes this presentation limit from the
recording limit. The original captured trace, output and full locals remain available
for event inspection; mapping and preview generation do not mutate them.
The retained stdout and stderr also have output pages of at most 65,536 characters
and 512 display lines. Page metadata contains only channel and character offsets;
selecting pages reads bounded slices of the original capture. Consecutive pages
cover every captured character exactly once, including trailing newlines, so the
preview limit does not make captured output inaccessible.

The generic computation worker uses a separate length-framed binary control channel,
with a 2 MiB frame and default queued-byte bound and a 256-frame count bound. Python
and native writes to its ordinary stdout cannot enter that protocol. Both generic
workers and the existing managed Python child have owned process trees: Windows jobs
or POSIX process groups are established before submitted work starts. Closing an
execution releases its descendants as well as its immediate process.
Plain Run uses that same owned tree. Its Stop action sets the existing session
request flag; the orchestration thread terminates the tree, drains output and
releases temporary files before delivering completion. A normally exited parent
cannot leave descendants holding its generated directory or console pipes.

On Windows the launcher is created suspended, assigned to its Job and then resumed.
This contains the venv redirector's real interpreter child before either can execute
submitted work, following the documented
[suspended-thread startup boundary](https://learn.microsoft.com/en-us/windows/win32/procthread/suspending-thread-execution).
Shutdown waits for the associated process handles to signal exit before releasing
temporary files. It does not wait for accounting counters to reach zero: those
counters may retain exited processes while another component still owns a handle,
as described by [Job accounting](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information).

Cancellation acknowledgement disarms the cooperative cancellation grace only after a
valid cancelled result proposal. It does not charge host resource verification and
admission against a backend shutdown timer. Once the host sends `WorkerTerminalSecured`,
`expect_exit` imposes a bounded completion-verification deadline; repeated calls cannot
extend it. A normal prepared-artifact response can start that deadline immediately.
The attempt records forced termination only when the supervisor actually forces the
process tree to stop. A cancellation request alone is not evidence of forced termination.
The runner's Stop request remains nonblocking; managed-driver close waits for bounded
shutdown completion before releasing its caller.

Source installations launch the fixed computation worker script. Frozen installations
use `--code-visualizer-internal-python --computation-worker`; trusted CLI and desktop
entrypoints supply the fixed callback before normal application/UI startup. No worker
module path or callback is supplied by project data. The execution adapter does not
import application composition code.

## Generated Python names

One deterministic allocator selects implementation-only imports, helper functions,
temporary variables and invocation bindings. Before emission it reserves authored
Python identifiers throughout the emitted file, including parameters, local bindings
and loads in nested scopes. Identifier comparison uses Python's NFKC normalization.
This conservative reservation prevents a generated local from capturing an authored
free reference and an authored local from shadowing a generated module dependency.
It does not prohibit user names or rewrite authored expressions.

Generated semantic bindings also track lexical ownership. StartTimer and Period
declare their timer in the current scope before emission; Synchronizer resolves that
binding through enclosing lexical scopes. A parallel branch can therefore read an
outer timer, while a timer assigned in the branch remains local. Method closure
lookup skips the class namespace, following Python's scope rules.

Existing feature-dependent helper bindings remain available to explicitly authored
Python: _cv_asyncio, _cv_futures, _cv_time, _cv_deque, _cv_async_iter and nullcontext.
They describe the initial evaluation environment, including defaults and class
bodies. Later authored assignments can shadow those names normally. Generated
operations use separately allocated implementation bindings, so shadowing an explicit
helper reference does not replace a typed operation's dependency. Authored built-in
references retain their ordinary Python lookup behavior.

The launcher and explicit raw-source invocation adapters use the same allocator and
invocation renderer, including async consumers and captured results. The guarantee
covers lexically present bindings and references; dynamically constructed names in
globals(), exec or equivalent reflection are not inferred. Generated names are
disposable output and do not change canonical identities or project persistence.

## Python package modules

ProgramModule has a Python-specific MODULE/PACKAGE kind. Both kinds own the same
ordered typed declarations and stable function references. Paths are relative to
ProgramModel.package:

| Kind | Path | Package prefix | Emitted file | Import name |
| --- | --- | --- | --- | --- |
| MODULE | main | app | app/main.py | app.main |
| PACKAGE | empty | app | app/__init__.py | app |
| PACKAGE | tools | app | app/tools/__init__.py | app.tools |
| MODULE | tools.vector | app | app/tools/vector.py | app.tools.vector |

An authored initializer is never replaced by generated boilerplate. Missing parent
initializers with no authored declarations remain empty derived files. A module
cannot simultaneously be a package prefix, and a MODULE named __init__ cannot
masquerade as a PACKAGE. An empty root package needs a nonempty package prefix.
Colliding import names or output paths are explicit diagnostics.

Relative imports use the actual package context: a PACKAGE's own import name, or
the parent name of a MODULE. Package initialization, __file__, __spec__, loaders,
inspect and importlib.resources consequently use ordinary Python behavior.

## File-qualified runtime locations

SourceLocation carries an artifact-relative file path, line and column. Its enclosing
execution session pins project/artifact revisions. SourceSpan retains the semantic
identity and presentation identity at that location. Temporary absolute filenames
are process details and are translated back to the artifact-relative path.

Breakpoints, frames, trace events, runtime binding resolution and editor navigation
use file-qualified positions. Equal line numbers or function names in different files
cannot alias. Runtime origins continue through the same revision-pinned semantic
overlay plane to the original authored program and domain objects.

## Runtime naming and compatibility

PythonRuntimeSettings and Project.runtime_settings describe interpreter/run profiles.
The Python Project workspace edits canonical declarations and those separate settings
through existing authority commands. Native revision 11 uses runtime_settings and
an explicit module kind. Earlier native snapshots and journals migrate on load;
current data cannot contain both runtime_settings and the legacy module_setup key.
Historical terminal revision 2 modules without a kind mean MODULE. Their immutable
bytes and hashes are verified before decoding defaults; durable resources are not
rewritten. New terminal data carries the explicit kind.

## Artifact publication and editor recovery

Generated-file inspection, manifest reads and bounded previews share a short
filesystem admission boundary with directory promotion. Readers close their handles
before promotion begins and see a complete published tree. Lowering and staged writes
remain outside that boundary; the final revision check occurs inside it. An external
program holding an incompatible file handle still produces an explicit failure.

Project recovery may reuse an immutable decoded snapshot when a later read within
that recovery returns identical source text. Retention is bounded by the project
source envelope. Every disk read, including the final external-change check, remains.
The session also owns the discovered Git adapter shared by its UI; status and HEAD
are read afresh when needed. These are operation/session reuse boundaries, not new
canonical state or durable caches.

## Verification

The gate compares persistent and temporary execution of the same emitted files,
including authored root/nested initializers, relative imports, real __file__, inspect,
package resources and initialization order. Multi-file trace/debug tests resolve
identical line numbers to distinct semantic IDs. Existing callable-shape, source-map,
domain-origin, history, automation and complete regression tests remain required.
