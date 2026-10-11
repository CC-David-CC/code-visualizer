# P6 acceptance map after P6-R1

Status: all five source gates, isolated wheel and fresh Windows executables
verified after the shared compiler correction. P5 remains accepted. P6 acceptance
is pending user review. The final extracted-source verification and delivered ZIP
identity are recorded in adjacent `programmodel.verification.json` and
`programmodel.zip.sha256`. P7/P8 are outside this delivery.

## Source and preservation

The qualified application/test/tool/packaging/example/asset/config inventory is
903 Windows checkout files recorded at
`9ec3ab40f8a3d7e135ec2bdb52522558620cb37a`. The full run passes
**2,354 tests in 6,735.44 seconds**, with zero failures, errors or skips.
All 2,289 reviewed P6 identities and 231 test/fixture files are preserved, including
all 2,122 accepted P5 identities and 205 original files. The 65 additive cases
cover the independent review and further unit-aware definedness controls.

The [Git/checkout audit](receipts/p6-r1-verification-2026-09-13/qualified-source-git-bytes.json)
distinguishes 711 tracked files from 192 ignored generated example files preserved
from the reviewed archive. Of the tracked files, 175 differ only by Git's
LF/Windows CRLF conversion; the remaining 536 match Git blob bytes exactly.
The inventory hashes identify the actual tested checkout bytes. Of its 903 files,
899 belong to the portable source archive; four local authoring-proof journal and
snapshot fixtures are excluded by the existing `.code-visualizer` packaging rule.
Their hashes and Git history remain retained. The portable proof includes its
canonical project, explicit commands and proof receipt. See the
[portable-closure addendum](receipts/p6-r1-portable-closure-2026-09-14/closure.json).
No source was changed by this audit; every authored source path is tracked at the
qualified commit.

The unchanged review runs with Pint 0.26.1: **51 independent, 91 core and 100
preservation cases pass**. Cohorts overlap and must not be added to the full count.
The same independent runner reproduced six failures and 45 passes before the
correction. Review assertions, saved projects and all 51 manifested files are
retained [byte for byte](receipts/p6-r1-review-2026-09-13/review-manifest.json).

P5's [acceptance decision](receipts/p5-acceptance-2026-09-13.json), original
archives and all earlier receipts remain unchanged. The reviewed P6 ZIP
`f031656dee49961e12083c6f00a8ecd2f219658c5131529c3c49911dfa40bc17`
and accepted P5 ZIP
`260c1cd82bed4dc3bb9559f3f5c3446261856faee7e1965cbca8c119c29cc863`
remain separate retained artifacts. The earlier [P6 receipt](receipts/transition-p6.json)
describes its original source; it is not new verification of this correction.

## Five gates

| Gate | Implemented boundary and measured proof | Passing tests in the complete run |
|---|---|---|
| P6-01 — Thermal/electrical feedback | Authored, saved electrothermal intentions prepare one ordinary streaming worker. Published channels agree with independent continuous, implicit-window and steady references. Power, component balances, contact signs and cumulative energy agree; evaluation order and presentation policy do not select different physics. Authored division conditions survive nominal parameterization and every normalized binding, including canceled quotients. | `test_electrothermal_references.py`, `test_electrothermal_window.py`, `test_equation_family.py`, `test_equation_family_domains.py`, `test_equation_family_definedness.py` |
| P6-02 — Implicit rollback and coherent acceptance | Real participant calculations retry from one immutable accepted base. Rejected trials do not advance accepted temperatures, energy or cursors. The checkpoint-2 cancellation proof requires exactly that retained prefix, cooperative termination and complete resumed/uninterrupted equality. Trial and retained displays have distinct typed contracts. | `test_electrothermal_window.py`, `test_electrothermal_lifecycle.py`, `test_channel_workbench.py` |
| P6-03 — Interface units, support, mapping and time | Point/interval fidelity, dimensions, support identities, mapping versions, endpoint times and resource closure are checked at source relations. All 17 earlier-channel mutations are rejected even when restart state matches. Missing cached and uncached child transfers fail. New channel/checkpoint goldens preserve old field meanings. | `test_electrothermal_contracts.py`, `test_channel_contracts.py`, `test_electrothermal_checkpoints.py`, `test_electrothermal_history_integrity.py`, `test_p6_contract_goldens.py`, `test_axial_contracts.py` |
| P6-04 — Participant, publication and restart failures | An independent job continues during coupled failure. Eight persistent storage/descriptor/root/receipt/association/ACK/reporting cuts reopen in fresh interpreters and preserve explicit checkpoint resume and fork-before-edit. Killed-host recovery, dirty Git, undo/redo, repeated attempts, equal local revisions and retained history after inactive worktree removal pass. | `test_electrothermal_lifecycle.py`, `test_electrothermal_publication_failures.py`, `test_electrothermal_host_crash.py`, `test_electrothermal_git.py`, `test_coupled_active_git.py` |
| P6-05 — Separate structural adapter | A real emitted-Python CAD producer publishes a verified filled rectangular prism and exits. Explicit material, frame/axis, end-region support/load and idealization feed actual P3 element equilibrium. Decoded arrays match independent extension, stress, reaction and energy references at 3/9/17/65 nodes. SI/mm, signed force, altered sections and empty-store portable replay pass. Holes, taper, disconnected geometry and the original perforated P4 example are rejected. | `test_axial_computation.py`, `test_axial_contracts.py`, `test_axial_workbench.py`, `test_p6_final_admission.py`, `test_p6_saved_examples.py`, `test_p6_review_subsolvers.py` |

Both domains still use the existing authority, shared unit/equation compiler,
computation host, resources and retained Git attempts. Only the shared compiler
has a production-code change. No physical-domain, backend or canonical-state
replacement is involved. [The correction record](P6_R1_CORRECTION.md) explains
the invariant and failure diagnostics.

## Numerical evidence

The fresh full run records independent DOP853/Radau comparisons at rtol `1e-12`
and atol `1e-13`, sharing no production assembly/RHS helper. At window lengths
1, 0.5 and 0.25 seconds over 0-100 seconds, maximum published temperature errors
are **0.03257887, 0.01637607 and 0.00820992 K**. Observed orders
**0.99235 and 0.99615** meet the predeclared [0.9, 1.1] band;
the finest error is below 0.02 K. The separate constant-resistance matrix
exponential check records 0.00795615 K error at 0.25 seconds. These are
time-discretization errors; the normalized coupling residual limit remains
`1e-10` and window energy residual `1e-9 J`.

The independent 100 mm / 100 mm² / 200 GPa / 1000 N axial targets are extension
`5e-6 m`, stress `1e7 Pa`, reaction `-1000 N` and energy `0.0025 J`. Geometry
tolerance remains `1e-7` relative and `1e-9 m` absolute. The 42 adopted independent
review controls cover 18 thermal and 24 axial parameter combinations. See
[the contract](P6_CONTRACT.md) for supported ranges and numerical identities.

## Workbench and distribution

The isolated wheel passes the unchanged P4/P5/P6 saved-source proofs, portable
consumer replay and direct R1 saved-project compiler checks. Application imports
are verified inside the wheel. Both freshly rebuilt Windows executables pass
the existing P4/P5/P6 resource proofs, GUI startup, unchanged P2 recovery proof
and direct R1 checks under frozen imports. All 14,812
native manifest files and 746 application/resource copies verify.
Native manifest SHA-256: `d2c330f5adc7b5d9a617b1a2fe3e5293088aca82308d19637872f6f1c79f7317`.

Native attempt 01's build and existing proofs passed, but the new R1 harness used
an unsupported script-with-arguments invocation. Attempt 02 completes R1 via the
existing `-c` interface against those same manifest-verified executables, linking
the successful earlier proofs. Both attempts and the original harness are retained;
no application change or assertion relaxation was needed.

The [new structured receipt](receipts/transition-p6-r1.json) links the five gates
to actual passing case identities. The
[raw manifest](receipts/p6-r1-verification-2026-09-13/evidence-manifest.json)
preserves 173 fresh evidence files, including source inventories,
raw logs/JUnit, numerical and UI measurements, dependency locks, earlier failures
and wheel/native results. Raw bytes are protected from Git line-ending conversion.
Fresh extracted-source verification uses the existing archive verifier and all
17 program examples, then repeats R1 against the extracted compiler and saved
projects. Its completed results and ZIP hash belong in the adjacent sidecar.

## Responsiveness and limits

The complete run's actual unpaused worker/large-history Qt workload measures:

| Measurement | Fresh result | Unchanged P6 limit |
|---|---:|---:|
| Interaction p95 | 4.95 ms | 100 ms |
| Interaction p99 | 18.95 ms | 200 ms |
| Maximum heartbeat gap | 213.54 ms | 250 ms |
| Reader cache / incremental working set | Both within bound | 64 MiB each |

P5's separate restricted workload also passes: interaction p95/p99
33.66/39.47 ms and maximum heartbeat
112.26 ms. Its authorized 350 ms allowance remains
P5-only. All test/build process trees use four of eight logical CPUs (50%);
unrelated jobs are untouched.

The complete run retains one 180-second faulthandler diagnostic dump in a passing
test, plus the existing JUnit property-format warnings. No tests were skipped.
Pre-correction failures, initial
lint/typing failures and all older qualification failures keep their original
outcomes. Earlier Windows LF/CRLF fixture, symlink-privilege and deep-Git-path
limits remain explicit in their historical receipts.

The first complete run at `274f853` records 2,352 passes and two GUI timing
failures: a 3-second live-agent display timeout and a 29.70-second 500-diagram
open against an 8-second bound. The slow open reproduced under the large
development Git checkout. Both unchanged tests passed outside Git ancestry,
followed by all 26 surrounding GUI tests. The live-agent timeout did not reproduce
in those fresh comparisons. The final complete run uses a fresh OS temporary
root with no parent Git repository; real Git tests still initialize their own
repositories. Every assertion, order, deadline and CPU limit remains unchanged.
The [diagnosis](receipts/p6-r1-verification-2026-09-13/gui-environment-diagnosis.json)
preserves the comparisons. Initial GUI attachment under a very large parent Git
repository still has that separate cost; P6-R1 does not claim to fix it.

Qualification is **Windows x64 / CPython 3.13.15 / exact recorded dependencies /
offscreen Qt**. It does not certify other platforms, Python 3.12 or subjective
interactive usability. First source installation needs internet; this ZIP has no
offline wheelhouse. The supported fragment remains fixed-window two-body
electrothermal coupling and small-strain axial equilibrium of a verified solid
rectangular prism. General multiphysics/FEM, RF and P7/P8 are not claimed.
