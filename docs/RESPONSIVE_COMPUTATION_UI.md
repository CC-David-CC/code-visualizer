# Responsive computation attachments

Focused P1 integration and the Windows offscreen response-time matrix pass. The
complete repository regression and final delivery checks are still separate gates.

## Ownership

The desktop composition root owns a ComputationService. MainWindow passes that host
through ProjectSession.new/open, example factories and Git reload. A directly
constructed window or kernel can own a local host for embedding and tests. Closing
an editor attachment detaches it; closing the owning host cancels and drains its
work. Ordinary editor replacement does not shut down the host.

Each attachment retains its existing RuntimeSessionRegistry. A scientific attempt
continues to publish into its original registry after the editor is replaced. A new
kernel gets a new attachment and registry, even if its project ID and revision match
the previous editor. No runtime state is copied between registries. The host lists
retained attempts and their immutable evidence/publications for explicit inspection.
Attachment identity is operational; source and input digests identify scientific
inputs independently of a window's lifetime.

Interactive DRAKON and domain debugger sessions retain their editor lifetime. Their
existing stop/detach behavior and emitted-file execution adapters remain in place.

## Submission and observation

The domain workbench's Run computation button captures the current immutable
project/request and calls start_computation. The host returns a queued session and
performs preparation, execution and admission away from the Qt button callback.
The synchronous headless convenience waits on that same attempt.

QtRuntimeObserver samples immutable latest runtime and attempt snapshots every
40 milliseconds. Workers do not enqueue one Qt callback per progress event. The
host retains terminal outcomes and sealed publication receipts; polling may skip
superseded progress displays without discarding those records. The GUI adapter does
not accept arbitrary worker callbacks or decode resource bytes in its timer.
Terminal semantic selection is delivered by that Qt observer on the GUI thread;
the orchestration thread records the desired selection without invoking UI subscribers.

Runtime ticks update activity decorations, attempt status, observation previews and
sealed artifact metadata. They do not rebuild schema definitions, diagnostics or an
open property form. Table and hierarchy items remain in place. Composed-canvas
activity changes preserve geometry, selection and pan. Automatic computation
selection updates shared visual selection while retaining the form's editing
target and uncommitted text. Deliberate user navigation keeps its normal behavior.

Cancel acknowledges the selected host attempt immediately. Its phase/status later
reports the worker's terminal result and whether termination was forced. The UI
does not wait for cooperative shutdown in the button handler.
Once final verification has started, the Cancel control is disabled and the attempt
is labelled as verifying its result; a previously accepted cancellation cannot be
reclassified as success by a late result.

## Current and historical source

Current authoring highlights use kernel.current_runtime_ids(), which admits only
the current attachment and revision. An earlier attempt remains inspectable as
historical when the source revision changes or a new editor attaches. A matching
revision number in another attachment is insufficient to adopt its runtime state.

Observation previews display their revision, sequence and source provenance. They
distinguish provisional values, accepted observations and unaccepted observations
from failed or cancelled attempts. Sealed publications display their resource ID
and content hash while the producer can still be running. Opening that receipt
reads retained admitted metadata; it does not hash, decode or modify its resource.
Historical evidence inspection does not highlight current authoring objects.

## Verification

tests/test_computation_host_qt.py checks burst coalescing, preserved in-progress
editing, current-source gating, the actual Run/Cancel buttons, process cancellation,
editor replacement and sealed-resource survival. Its pan proof drags the graph
viewport while a real worker runs, then preserves that viewport and the open draft
form through cancellation and the terminal update. Its process tests use the shared
statically registered tests/fixtures/computation_worker_fixture.py. Configured
stress modes supply typed request parameters without replacing execution or
admission. The default progress case uses the unmodified button request.

The reference timing cases write JSON receipts beside their temporary resource
stores. Run them without competing suites before interpreting the response-time
assertions. An isolated burst test is not a substitute for the process/CPU tests.

The existing foundation editor test waits for asynchronous completion while retaining
its canonical edit, undo, notation and evidence assertions. It closes the host even
when a verification fails.

## Python editor preparation

EditorPreparation owns one active supervised preparation and one replaceable pending
request for an editor. Qt debounces source previews, captures immutable project
state and structured literal arguments, then samples the latest preparation receipt.
The fixed worker derives the existing InvocationSpec and calls the existing Python
preparation/lowering once. Its disposable artifact carries emitted files, source and
origin maps, and canonical runtime bindings. It contains no second authored program.
Host snapshot encoding uses the same canonical JSON byte contract incrementally.
Persistence-only field inventories feed both ordinary JSON dictionaries and streamed
bytes; programming sequences and generic-domain arrays release each temporary record
after encoding it. This avoids both a monolithic native encoder and constructing a
second full JSON tree beside the immutable source. No garbage-collector policy is
changed. Assessment derives DRAKON once and reuses unambiguously bound structures for
flow checks; global integrity checks are retained. Artifact admission counts lines
once per file while retaining each source-map bounds check.

The host verifies the captured source hash, request identity and completed bounded
resource transfer before decoding the artifact. Qt admits a result only for its
current editor, request and revision. Changing source or replacing an editor cancels
pending work; an obsolete request cannot start execution or overwrite its replacement.
Existing running/debugging source files remain pinned while author state changes.
Stop is available during preparation as well as execution. Cancelling preparation
reports which pending Run, Trace or Debug request was stopped, restores the controls,
and cannot launch a late prepared artifact. Runtime-overlay and trace tests wait
for their existing asynchronous delivery boundaries; live-stop tests explicitly
enter the runner before stopping it.

Each editor retains at most one successfully admitted preparation for reuse. Its
key is the exact immutable Project object, selected diagram/domain target and
structured arguments within that adapter's fixed worker-profile context. Run and
Trace can share the emitted files and bindings while receiving fresh request IDs.
A different source object, target or arguments replaces the entry; closing the
editor releases it. No transformed program or cache enters canonical persistence.

Run uses RunSession.start_project, Trace uses RunSession.start_project_trace, and
Debug uses the existing DebugSession. Their real files and source mappings come from
the admitted preparation. Domain Workbench Build/Trace/Debug use that same adapter.
Interactive execution retains its editor lifetime; scientific host attempts remain
independent of editor replacement. Custom static implementations require an explicit
compatible worker profile; persisted data cannot select imports or callbacks.

tests/test_editor_preparation.py proves focused invocation admission, canonical
binding/origin preservation, and obsolete-request rejection. The authored-language
Qt proof supplies tests/fixtures/editor_worker_fixture.py, whose registry contains
only programming, intentional, and neutral computation contracts; it registers no
handwritten FSM extension.

Trace completion prepares source locations and a bounded console preview away
from Qt. The document preserves its original first-match mapping policy; domain
traces preserve their narrowest-span policy. Runtime events enter the existing
registry/selection path in Qt batches of at most 32 events or eight milliseconds
per turn. Domain origins are registered once before delivery. Detaching an editor
discards its pending presentation, and current-source gates still control overlays.

The complete captured TraceResult remains available. The preview is limited to
64 Ki characters with an explicit notice; captured-event selectors reveal each
event's full captured locals. The same selectors expose all retained stdout/stderr
through pages of at most 64 Ki characters and 512 display lines. Page descriptors
contain offsets into the original output, rather than another copy of its data.
Only a selected page is rendered. Tests cover exact concatenation of the displayed
pages, all-event delivery, source navigation, origins and detach behavior.

tests/test_project_streaming.py compares exact bytes and hashes with all 17 saved
projects and proves a single large function streams its nested statements. Domain
streaming tests cover rich schema/value inventories and large node, role and schema
arrays. These descriptors describe codec work only; they are never domain values or
persisted project objects.

The process timing matrix includes actual editor Run/Trace over the normal
500-diagram/20-statement source fixture and an actual generic Run that admits and
streams a 128 MiB input resource. Run/Cancel acknowledgement fields describe their
individual button samples. The active CPU-worker case separately records at least
100 real text-edit gestures and reports nearest-rank p95/p99, with 100/200 ms limits;
heartbeat gaps retain the independent 250 ms bound. Raw passing and earlier failed
measurements, environment details, source manifests and fixture digests are retained
under [the Windows offscreen receipt directory](receipts/p1-windows-offscreen-2026-09-10/manifest.json).
These measurements describe that reference environment, not all supported systems.

The new large-source fixture uses a 120-second completion watchdog, matching the
existing editor preparation lifecycle. That watchdog detects a stuck test; it is
not a P1 throughput promise. Receipts record actual Run/Trace elapsed times. The
30-second exploratory receipts are retained with the phase evidence; no existing
test deadline or acknowledgement/heartbeat/percentile gate was relaxed.
