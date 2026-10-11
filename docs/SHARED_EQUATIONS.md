# Shared unit-aware equation boundary

`foundation.math@2` extends the existing mathematical expression schema. It keeps
stable Symbol, Equation, expression-occurrence and containment identities, and
adds Problem, SolveRequest, Binding and RelationUse. `foundation.math@1` and
`foundation.math.indexed_equations@1` retain their released assignment-evaluation
meaning. A project installs an exact schema version; installing an incompatible
version over authored contents requires an explicit migration, never registry
order. Bundle installation and notation discovery honor that version.

A Symbol declares its characteristic scale, output unit and quantity kind. Every
symbol used by a selected relation is explicitly bound or selected as unknown.
There is no default zero, inferred unit, implicit legacy binding or automatic
choice among solve requests. One request may be selected implicitly only when
exactly one exists. Otherwise computation configuration supplies `request_id`.
Changing the requested unknown changes request intentions, not the Equation.

Relations reference an explicit unit vocabulary through their Problem. Complete
vocabulary inputs retain their canonical root and node order when scoped for
execution. Catalog lookup, unit products and conversions use this frozen closure.
Matching dimensions alone never authorizes a conversion. Points and intervals
have distinct algebra; frequency and logarithmic kinds require supported explicit
operators and currently produce a diagnostic.

Equality has its own symmetric typing rule: both operands must have the same
supported quantity kind, matching dimensions and an authorized unit-factor path.
A point-to-point relation has an interval residual. Point = interval is invalid
in either orientation, even though point minus interval is a valid arithmetic
translation. Residual scales describe differences and never apply a coordinate
offset. These checks run before matrix construction; diagnostics retain the
authored Equation, OperatorApplication or RelationUse identity.

Arithmetic uses kind and dimension together. An interval multiplied by an
explicitly dimensionless linear scalar (in either order), or divided by that
scalar, remains an interval. Other products and quotients compose dimensions and
produce linear quantities. Missing dimensional context is not dimensionless;
unit conversions still require catalog authorization. Points cannot be multiplied,
divided or negated, and unsupported kinds cannot bypass checking through scaling.

The registered `foundation.math.linear_equations@1` backend accepts math@2, not
ProgramModel. A private compiler constructs SymPy expressions from an operator
allowlist over canonical nodes. Names and operator strings are never parsed as
Python or library expression text. This adapter supports finite real scalar
linear relations after known bindings. Unknown products/denominators, tensors,
derivatives, integrals, nonlinear and DAE requests are outside its contract.

For reported unknown values x, the checked relation is A*x=b. Each positive
variable scale s and equation residual scale r is retained with its unit. The
numerical system is A'[i,j]=A[i,j]*s[j]/r[i], b'[i]=b[i]/r[i], x=s*y.
NumPy checks normalized matrix/augmented rank, conditioning and residual tolerance.
Square full-rank systems use solve; rectangular full-column-rank consistent
systems use least squares. Underdetermined, singular and inconsistent systems
receive distinct diagnostics. There is no minimum-norm fallback for these cases.
All numerical inputs and outputs must be finite. The bounded v1 adapter accepts
at most 256 unknowns, 512 relations and 50,000 expression visits.

Results use the existing host-owned computation lifecycle. Small observations
carry quantities, physical residuals, normalized residuals and semantic origins.
A content-addressed `foundation.math.equation_solution@1` resource retains the
checked matrices, scales, rank, condition, policies and numerical library versions.
The existing terminal resource retains source meanings and unit definitions.
Neither symbolic expressions nor matrices become a second authored model.
Portable plan replay and retained evidence require no editor or producer process.

The optional science extra pins Pint 0.26.1, SymPy 1.14.0 and NumPy 2.5.3.
Core project loading remains independent of these packages; execution without
them reports `SCIENCE_DEPENDENCY_MISSING`. P3 does not claim nonlinear/DAE solvers,
universal symbolic mathematics or later transition phases.

The adapter's numerical policies use the documented NumPy
[SVD rank boundary](https://numpy.org/doc/stable/reference/generated/numpy.linalg.matrix_rank.html)
and [least-squares cutoff](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html).
Affine operations follow the point/interval distinction documented by
[Pint](https://pint.readthedocs.io/en/stable/user/nonmult.html), after authorization
by the project's own catalog.
