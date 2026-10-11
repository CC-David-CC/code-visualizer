# P3 correction plan: point/interval equation typing

Status: implemented and available Windows gates verified. The focused type gate
passes 161 cases, the host/notation gate 50, and the complete suite 1,980. All 16
unchanged independent affine tests pass, including extracted delivery source.
The corrected prior recovery cohort is 11 passed/2 Windows fixture failures; the
real-symlink controls and fresh Linux/macOS execution remain explicitly unverified.
See the [completion receipt](receipts/transition-p3-affine-correction.json) and
[evidence](receipts/p3-affine-correction-2026-09-11/README.md). P4-P8 are not included.

Delivery policy update: the user explicitly authorizes replacing `programmodel.zip`
and cleaning up superseded release ZIPs/sidecars. Their exact bytes are verified
in Git first and indexed in [release retention](receipts/p3-affine-correction-2026-09-11/release-retention.json).
This supersedes the original plan's separate-archive requirement below. Historical
receipts, review inputs, old tests and example source stay unchanged.

## Reviewed baseline and reproduced evidence

The controlling input is the supplied independent review, preserved with its
unchanged tests in [the planning evidence](receipts/p3-affine-planning-2026-09-11/README.md).
Its [corrective handoff](receipts/p3-affine-planning-2026-09-11/input-review/CODEX_P3_AFFINE_CORRECTIONS.md)
and [findings](receipts/p3-affine-planning-2026-09-11/input-review/REVIEW.md)
describe two defects, represented by five failing parameterized cases.

- Checkout tested: `e7752e88cc09353f3e24c63d9430749551792e63`.
- Original delivery: `programmodel-p3-review.zip`, 9,685,647 bytes,
  SHA-256 `6ded240f3ca545b3a1aba760c5ed913da5e0931df5fbc327323e8294ec0cb5d9`.
- All 67 files listed by the supplied review manifest match their hashes and sizes.
- Fresh Windows reproduction with CPython 3.13.15, Pint 0.26.1, SymPy 1.14.0 and
  NumPy 2.5.3: **11 passed, 5 failed** in the new 16-case review cohort.
- All three newly supplied admission/restart cases pass unchanged. The full
  prior cohort on this Windows run is **9 passed, 4 failed**: two 30-second
  fork-completion timeouts and two CRLF-versus-LF control assertions. These
  are retained failures, not a claim of 13 Windows passes.
- The historical 1,898-test pass belongs to the original P3 delivery. It does
  not certify the new affine regressions, and was not repeated during planning.

Preserve the original P0/P1/P2/P3 archives, sidecars, manifests, failed and passing
receipts, examples and existing test expectations. Publish a separately named
corrected delivery after implementation; do not overwrite the reviewed artifact.

## Findings and intended correction

| Finding | Current source boundary | Required behavior |
|---|---|---|
| P3-R1, high: point = interval can solve in one orientation | `equation_compiler.py` uses arithmetic `result_kind("subtract", ...)` as its equality check | Check symmetric relation compatibility first, then derive the residual type. Point = interval is invalid in both orientations. |
| P3-R2, medium: scalar scaling erases interval kind | `unit_algebra.py::result_kind` receives only kinds and returns LINEAR for all binary products/quotients | Supply actual operand dimensions as well as kinds. Preserve interval type under dimensionless scaling, while retaining the existing restrictions on points and dimensional products. |

Both changes belong in the existing foundation type algebra and equation compiler.
Keep ProgramModel, DomainWorkspace, ProjectAuthority, the host lifecycle, P2 durable
attempt bindings, resources, evidence and the numerical solver architecture intact.

## Regression preflight: investigate the additional Windows failures

The first run used a deep scratch path and all 13 prior cases failed at Git
worktree creation with `fatal: '$GIT_DIR' too big`. A shorter path allowed the
actual tests to execute. Keep both runs; do not change Git configuration or
canonical input bytes to make the fixtures pass.

Before closing the regression gate, rerun these two cases independently at the
unchanged baseline, preserving their existing 30-second deadline:

- `test_semantic_fork_must_not_silently_revert_declared_source_edits`
- `test_successful_freeze_protects_an_unrun_child_before_and_after_reopen[True]`

Both failed in `finish_edit(...).result(timeout=30)`, rather than at an assertion
that frozen meaning changed. Do not assume the cause is harmless scheduling:
measure the Git/worker handoff if they reproduce, and compare with the accepted
Windows baseline. An eventual durable edit is not a deadline pass. Resolve a
reproducible regression through the existing P2 implementation, without weakening
the assertions or changing its authoritative attempt/context design.

The two real-symlink controls fail earlier at an LF byte literal because the
Windows fixture writes CRLF. Their symlink operations were not reached. Run those
original controls on their supported reference platform, and record Windows
coverage separately. Do not normalize captured source bytes or change the test
expectation. The review's Linux 13-pass result remains supplied evidence.

These extra local failures do not explain the affine defects, which reproduce
under both path configurations with the pinned science packages. They remain
explicit acceptance checks while the bounded P3 type correction proceeds.

## Checkpoint 1: define and implement the complete typing decision

Expected production scope:
[unit_algebra.py](../src/code_visualizer/extensions/foundations/unit_algebra.py)
and [equation_compiler.py](../src/code_visualizer/extensions/foundations/equation_compiler.py).
Add focused regression files rather than weakening or rewriting existing assertions.

Use the information already held by the compiler's derived `_Expression`:
quantity kind, normalized dimension, and declared unit-factor evidence. These
are immutable computation data, not additional canonical state.

Keep one arithmetic kind-inference operation. Extend `result_kind` with explicit
operand dimensional context for decisions that need it; existing unambiguous
kind-only calls remain valid. An omitted dimension is unknown, not dimensionless.
An interval product/quotient whose kind cannot be determined without that context
must request it or diagnose its absence, never silently fall back to LINEAR.
All production compiler calls supply their actual operand dimensions.

Add a separate relation-typing operation that checks both operand kinds and the
existing dimension/conversion compatibility, then returns the residual type.
Do not route equality through the subtraction translation rule. Share existing
unit-compatibility logic; do not create separate GUI, preparation and backend rule
tables.

The supported equality matrix is:

| Left/right operand kinds | Additional requirement | Residual kind |
|---|---|---|
| LINEAR / LINEAR | Matching dimensions and authorized unit factors | LINEAR |
| INTERVAL / INTERVAL | Matching dimensions and authorized unit factors | INTERVAL |
| POINT / POINT | Matching dimensions and authorized unit factors | INTERVAL |
| Mixed supported kinds, either orientation | Always invalid | `UNIT_KIND_MISMATCH` |
| Unsupported frequency/angular/logarithmic kinds | Existing diagnostic remains | No numerical system |

The scaling rules are:

| Operation | Result |
|---|---|
| INTERVAL * dimensionless LINEAR | INTERVAL |
| dimensionless LINEAR * INTERVAL | INTERVAL |
| INTERVAL / dimensionless LINEAR | INTERVAL |
| INTERVAL * dimensional LINEAR, either order | LINEAR with the composed dimension |
| INTERVAL / dimensional LINEAR | LINEAR with the quotient dimension |
| LINEAR / INTERVAL | LINEAR with the quotient dimension |
| INTERVAL * INTERVAL or INTERVAL / INTERVAL | LINEAR with the composed dimension |
| Any multiplication/division involving POINT; negating POINT | Existing point-operation diagnostic |

LINEAR alone does not mean dimensionless. The scalar dimension must be explicitly
empty after normal dimensional reduction. Unit factors still compose and must
resolve through the declared catalog. Equal dimensions, including dimensionless
dimensions, never grant an undeclared unit conversion.

Retain the existing valid addition/subtraction rules: point minus point gives an
interval; point plus/minus interval gives a point; interval plus point gives a
point; interval plus/minus interval gives an interval. Retain rejection of
point+point, interval-point and point+LINEAR.

Validate every selected relation before `linear_eq_to_matrix` or `solve_linear`.
Interpret a point-to-point residual's scale using interval semantics: scaling a
difference never applies an affine coordinate offset. Keep positive finite scale,
dimension, declared conversion, nonlinear and division-by-zero guards.

Attribute a failed relation to its Equation ID, a failed arithmetic operation to
its OperatorApplication ID, and an invalid residual scale to its RelationUse ID.
Preserve existing diagnostic codes and composed origins through the host.

Required focused proofs:

- The supplied 16 affine cases pass unchanged, including both equality orientations,
  Celsius and kelvin outputs, and the expected 40, 40 and 25 degrees Celsius.
- Test all supported equality kind pairs in both orientations, dimension mismatch,
  and missing conversion paths. Point-to-point residuals use interval scale.
- Test dimensionless scaling with literal and explicitly bound scalar operands,
  both multiplication orders, zero and negative multipliers, and a nonzero divisor.
- Test dimensional products, inverse dimensions and interval products so a blanket
  "preserve interval" rule cannot pass. Missing dimensional context is explicit.
- Test existing forbidden point operations, unsupported frequency/logarithmic
  kinds, zero division and nonlinear unknown products/denominators.
- Keep direct DC, F=k*x, unscaled translation, rank/conditioning and rational
  dimension controls. No tolerance or expected-answer changes.

Gate: focused type/compiler tests, unchanged external affine tests, architecture
and dependency tests, lint, format and configured typing. Commit the coherent
arithmetic/relation correction with its regression coverage.

## Checkpoint 2: prove normal computation and durable publication

Extend the existing patterns in
[test_equation_computation.py](../tests/test_equation_computation.py) through a
new affine computation test module. Use the registered backend and real
ProjectKernel/host worker, ResourceStore and EvidenceStore. Do not add a
temperature-specific backend or an alternate execution path.

For the three legal scaled translations and a valid point-to-point relation:

1. Prepare and execute ordinary canonical math@2 inputs with pinned science
   dependencies. Include at least one known-binding case exercising real Pint.
2. Check the numerical values and output unit references, published variable
   `kind`, physical/normalized residuals, source IDs and provenance. Check interval
   residual scaling explicitly, including Celsius/kelvin choices.
3. Verify the normal typed `foundation.math.equation_solution@1` resource and its
   content hash. Assert the authored project and revision did not change.
4. Close the producing host/editor, reopen the evidence/resources and replay the
   exported Protobuf plan through the existing API. Equivalent inputs must reproduce
   equivalent typed results, origin maps and the established evidence identity
   contract.
5. Resolve the originating equation/symbol through the existing graph, table and
   hierarchy runtime projections. Reuse the current observation path.

For incompatible point/interval equalities in both orientations, exercise the
real host path and require FAILED evidence with `UNIT_KIND_MISMATCH`, the original
semantic ID, and no solution resource. Add a narrow in-process guard test proving
invalid typing never reaches matrix construction or the numerical solver; that
guard complements the real-worker proof rather than replacing it.

Structural preparation may accept a well-formed model. Mathematical rejection
belongs to the shared compiler before numerical admission; do not duplicate the
type checker in ProjectAuthority or the generic preparation layer.

No project-format, CanonicalValue, Protobuf or public result-contract change is
needed for these fixes. Variable kind already travels in the result report;
residuals are differences linked to their typed source relation. Preserve those
contracts and verify them. If implementation exposes a missing required field,
document the evidence and compatibility decision before altering a wire contract.

Gate: new host/publication tests, existing equation/DC/physical tests, portable
physical proof, old indexed-math proof and architecture checks. Commit the
end-to-end proofs and any necessary origin-reporting correction.

## Checkpoint 3: preserve P0/P1/P2 and close the acceptance gate

| Gate | Required evidence |
|---|---|
| Independent affine review | All 16 cases unchanged, with no missing-science skips. |
| Independent P2 recovery | The exact three admission/restart cases plus original R1-R6 and controls. Preserve platform-specific failures as such; do not edit assertions to manufacture 13 Windows passes. |
| Supplied P2 regressions | The existing 98-case headless/architecture cohort and Qt recovery case, including stale markers, failures after admission, retained reopening and fork-before-edit. |
| P3/foundations | All equation, unit, rational-dimension, publication, DC, physical workbench and retained-comparison tests with installed dependencies. |
| Complete regression | All existing 1,898 cases plus new repository tests. Record collected unique counts; overlapping cohorts are not additive. |
| Quality | Ruff check/format, configured mypy, regenerated protocol check and architecture/dependency tests. |
| Distribution | Fresh wheel/import and Windows native CLI/GUI builds; unchanged packaged stale-marker proofs; all five packaged computation smokes. |
| Extracted archive | Manifest/CRC/source identity; all 17 old examples; both historical independent proofs; both physical clients and portable replay. Run the independent affine cohort against the extracted corrected source too. |

Use short, fresh Windows test roots for managed Git worktrees. Keep the original
supplied runner and tests byte-identical. Where Linux-specific controls cannot
pass unchanged on Windows, run that original cohort on its supported reference
environment or record the gate as unverified; a prior Linux pass is historical
evidence, not a new execution claim.

After each implementation checkpoint run its focused tests and
`test_architecture_boundaries.py` / `test_dependency_layering.py`. Repeat broader
checks after a code change or failure, not merely to increase test counts.

Update [SHARED_EQUATIONS.md](SHARED_EQUATIONS.md) and
[FOUNDATION_UNITS.md](FOUNDATION_UNITS.md) with the actual arithmetic/relation
contract. Update the current [acceptance map](P3_ACCEPTANCE_MAP.md),
[STATUS.md](../STATUS.md) and [transition progress](TRANSITION_PROGRESS.md).
Keep the original P3 receipt and archived documents unchanged.

Produce a fresh correction receipt containing the exact tested commit, source
inventory, review-input hashes, commands, dependency pins, exit codes, raw log and
JUnit hashes, numerical tolerances, origin/resource assertions and platform limits.
Keep the initial failing reproductions. Build to an explicit new archive path,
for example `programmodel-p3-affine-corrected-review.zip`; never use the builder's
protected historical default path. Record any docs-only changes after testing
separately from the tested implementation.

P3 acceptance requires both corrected type semantics and the successful
end-to-end/regression gates above. Types existing, direct solver examples passing,
or the historical 1,898-test pass alone do not close this correction. No P4 work is
included.
