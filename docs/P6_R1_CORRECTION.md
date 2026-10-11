# P6-R1: preserve authored equation domains

Status: shared compiler correction, full source regression, isolated wheel
and fresh Windows executables verified. P5 remains accepted within its existing
Windows scope. P6 awaits acceptance review; P7/P8 are outside this task.

## Reviewed source and reproduction

The reviewed P6 archive has SHA-256
`f031656dee49961e12083c6f00a8ecd2f219658c5131529c3c49911dfa40bc17`.
It and its exact delivery sidecars are retained in Git as
`programmodel-p6-reviewed-20260913.*`. The accepted P5 archive remains
`programmodel-p5-accepted-20260913.zip`, SHA-256
`260c1cd82bed4dc3bb9559f3f5c3446261856faee7e1965cbca8c119c29cc863`.
The reviewed 2,289-pass qualification is historical evidence for that source.

The [independent review](receipts/p6-r1-review-2026-09-13/REVIEW.md), its original
assertions, representative saved projects, source excerpts and all 51 manifested
files are retained unchanged. Before modifying application code, its unchanged
portable runner reproduced **six failures and 45 passes, with no skips**, on the
dependency-complete Windows interpreter. This includes the three real-Pint
rebinding cases skipped in the review's Linux environment. The failure is at
the shared compiler; it does not establish a wrong default electrothermal run.

## Invariant and implementation boundary

Reusing an equation through a parameterized representation must not change when
that equation is defined. For the current scalar linear fragment, every authored
division requires a nonzero known denominator in normalized units, even when
symbolic simplification erases the quotient or a surrounding zero product.

The existing typed expression traversal retains an immutable nonzero-denominator
condition with the original division's semantic identity. Conditions are separate
from the simplified numerical matrix and RHS, in traversal order: inner divisions
are checked before their containing operations. This is disposable compiler state,
not another canonical expression language or persisted resource contract.

Ordinary and family compilation use the same condition check while traversing
the source, with exact nominal quantities. A family keeps these conditions and
checks each complete binding before exposing a `LinearSystem`. Binding continues
to use `UnitAlgebra` and real Pint for the existing quantity kind and declared
conversion policy. The converted magnitude then enters the same exact decimal
rational boundary used by nominal compilation, for both conditions and matrix.
Zero is exact here, not a numerical rank or residual tolerance.

Coefficient usage follows authored traversal. A coefficient used only in a
condition remains required even when the matrix is constant. Binding or a failed
condition does not modify the family, canonical model, source identities or
retained evidence. Diagnostics preserve `EQUATION_DIVISION_BY_ZERO` and the
innermost offending authored division identity.

No coupling, CAD, resource, checkpoint, Git, authority, backend or unit-policy
replacement is required. Existing linearity, ownership, affine, dimension, finite
scalar, rank, condition and residual checks remain in force. In particular,
`R*I=V` at zero resistance still reaches the existing solver's inconsistency
diagnostic; it is distinct from an undefined division.

## Fresh qualification

The unchanged external review now passes **51 independent, 91 core and 100
preservation cases**, with no failures, errors or skips and real Pint 0.26.1.
The original pre-correction result remains six failed and 45 passed. Adopted
assertions are verified equivalent after import/format/local-name cleanup.

The compiler-focused cohort passes 220 cases, including architecture/dependency
checks. Ruff, formatting and mypy (353 source files) pass. The full suite at
`9ec3ab40f8a3d7e135ec2bdb52522558620cb37a` passes **2,354 cases in 6,735.44 seconds**
with no failures, errors or skips. All 231 reviewed P6 test/fixture files and
2,289 case identities remain unchanged; all 205 accepted P5 files and 2,122
identities remain present. The 65 additive cases include the review's nine family
checks, 42 independent thermal/axial controls and 14 further definedness controls.

The isolated wheel and both fresh native executables pass the unchanged saved
P4/P5/P6 computations and a direct R1 proof loading the three reviewed project
JSON files. Imports are checked inside the delivered package, not the checkout.
Both executables pass the unchanged P2 restart/fork proof. Every native manifest
file and all 746 application/resource copies match the qualified
source. Final extracted-source verification, all 17 earlier generated examples
and the delivered ZIP hash are recorded in matching adjacent delivery sidecars.

Native attempt 01 built both executables and passed the existing release and
P2 recovery proofs, then the new R1 harness was rejected before executing its
checks: the private worker supports `-c` with arguments, not a script path plus
arguments. Attempt 02 passes the unchanged proof source through that supported
interface and verifies the same newly built files before and after. It retains
and links the completed proofs from attempt 01; no application or proof assertions
changed, and the failed aggregate attempt remains recorded as failed.

The first archive passed its existing verifier and direct R1 checks. Promotion
then stopped before replacing any delivery file: its audit incorrectly expected
four local authoring-proof journal/snapshot files in the ZIP. The established
archive policy excludes `.code-visualizer` state. The corrected audit distinguishes
the 903-file tested checkout from its 899 portable files, preserving the excluded
fixtures in Git and keeping the canonical project, commands and proof receipt in
the archive. The [closure addendum](receipts/p6-r1-portable-closure-2026-09-14/closure.json)
records this boundary and failed attempt. No packaging policy, application code,
test assertion or canonical example changed.

The [five-gate map](P6_ACCEPTANCE_MAP.md) and
[additive structured receipt](receipts/transition-p6-r1.json) reference the actual
case identities, source inventory and immutable raw evidence. Original P5 and
P6 receipts are not rewritten. Earlier failed lint/typing attempts and all
pre-correction test failures retain their actual outcomes. The full run contains
one 180-second diagnostic stack dump in a passing test. This is a diagnostic
timer, not a test timeout or an omitted test.

The first complete run remains **2,352 passed, two GUI timing failures, no skips**.
The live-agent display exceeded its original 3-second wait; opening the 500-diagram
project took 29.70 seconds against its 8-second limit. A fresh-process comparison
reproduced the slow open below the development Git checkout. Both unchanged tests
then passed in 7.64 seconds total outside Git ancestry; all 26 surrounding GUI
tests also passed. The live-agent failure did not reproduce in either fresh
comparison. See the [controlled diagnosis](receipts/p6-r1-verification-2026-09-13/gui-environment-diagnosis.json).

The fresh complete run uses one ordinary pytest process with an OS temporary
root outside any parent Git repository. Explicit Git tests still create real
repositories. No assertions, test order, deadlines or CPU limits changed. The
compiler correction does not fix the separate initial Git-panel cost for an
ordinary project inside a very large parent repository; that observed limitation
remains explicit. The failed full run is never relabeled as passing.

All builds/tests run serially under the user's 50% process-tree CPU cap. P5's
restricted 350 ms heartbeat allowance remains P5-only. The P6 workload measures
4.95/18.95 ms interaction p95/p99 and 213.54 ms maximum heartbeat,
within the unchanged 100/200/250 ms limits; cache/incremental-memory bounds pass.
Windows x64, CPython 3.13.15, exact recorded dependencies and offscreen Qt define
the qualification scope. No fresh Linux/macOS/native, Python 3.12 or subjective
interactive usability certification is implied. First source installation needs
internet; this archive has no offline wheelhouse. No P7/P8 completion is claimed.
