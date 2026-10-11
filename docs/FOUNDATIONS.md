# Mathematical and spatial foundations

`foundation.math@1` and `foundation.space@1` are ordinary first-party extension
bundles. Their schemas, constraints, notations and backend registrations use the
same workbench interfaces available to every domain. Neither the intentional
kernel nor ProgramModel contains mathematical or physical special cases.

`foundation.units@1` and `foundation.units.si@1` add ordinary shared units and
conversion definitions. The SI vocabulary has seven shared dimension bases and
28 common units; alternative systems use the same schema. The **Add vocabulary**
workbench action installs these definitions through one authority transaction.
See [Foundation units](FOUNDATION_UNITS.md) for exact conversion and context rules.

## Mathematical meaning

The mathematical schema represents Symbol, TensorSymbol, Literal,
OperatorApplication, Equation, Constraint, Index, Derivative, Integral and
Function. ComplexLiteral, QuantityLiteral, TensorLiteral and ResourceLiteral
carry the corresponding canonical value variants. A mathematical operation is a
named operator with owned operand objects and explicit references to bound
symbols. It is not a string of Python or a callback.

Declarations have stable identities. A SymbolReference is an owned occurrence
that points to a declaration. This distinction permits `A[i,k] * B[k,j]` to
contain two different occurrences of the same `k` without copying its meaning or
giving an owned object two parents. Index objects refer to tensor declarations;
tensor declarations may refer to literal/resource bindings. The tensor shape
declaration is an optional integer vector, checked against a known binding.

The schema can preserve mathematics beyond the available evaluator. For example,
Derivative, Integral, Function and Constraint have structured contents, but the
first backend does not claim to differentiate, integrate, solve constraints or
prove identities. Their execution requires an implementation that understands
those meanings. Unknown operators remain editable; an unsupported operation in a
requested computation returns an explicit diagnostic.

## Spatial meaning

The spatial schema represents Space, Axis, Frame, Transform, Region and Point.
Frames reference spaces. Points reference their frames and mathematical tensor
contents. Transforms reference source and target frames and one homogeneous
matrix in the mathematical model. The same matrix is not also stored as a
second rotation/translation representation. Regions reference an ordered set of
points and a common frame.

Extension validators check dimension/axis consistency, point coordinate shape,
homogeneous transform shape and last row, common region frames and minimum
point counts. Changing mathematical coordinates to an incompatible shape keeps
the authored edit and produces a spatial diagnostic. Generic containment and
reference integrity still apply independently.

Reference role definitions can target concept identities from another installed
schema. Adding the registered spatial schema through the workbench also adds its
mathematical schema dependency in one authority transaction. Containment remains
local to its model; references cross models. A notation field that follows a
reference resolves the actual owning model before producing its typed edit
command.

## Typed editing

Property definitions offer eight value kinds: string, integer, number, Boolean,
complex, quantity, tensor and resource. Number controls preserve integer versus
real values and signed zero; enum choices preserve the complete canonical value
identity. Absence remains an explicit unset property.

Complex values use real and imaginary fields. Quantities use a typed magnitude,
unit identity/version and a dimension table of basis identities and integer
exponents. Tensors use a dtype selector, shape field and editable element table.
Higher dimensions flatten into rows while retaining the typed shape. Inline
tensors are limited to 1,024 elements and 16 dimensions; larger contents belong
in managed resources. Dtype representability is validated rather than rounded
silently. Resource controls offer existing managed resources, explicit portable
identity/hash references, and file import into the saved project's resource
store.

Schema property forms also edit dimension constraints, tensor dtype constraints
and tensor shape constraints. An empty shape constraint accepts any shape,
`scalar` specifies rank zero, and `2, ?` fixes the first dimension while leaving
the second unconstrained. Opening and accepting an existing definition preserves
its constraints and typed default.

The same value controls serve hierarchy/form editing, double-clicked table
cells and editable composed-notation fields. Each submits the binding's typed
command to the existing authority. No rendered structure is reverse engineered.

## Direct numerical interpretation

`foundation.math.indexed_equations@1` consumes the mathematical representation
directly. There is no ProgramModel lowering, PythonProjectIR or generated Python
in this route. Its trusted implementation is a bounded host interpreter of the
semantic mathematical objects.

The supported fragment is finite real/integer tensor indexing, addition,
subtraction, multiplication, division, negation and finite sums. `sum` names its
bound symbols explicitly; the evaluator infers their dimensions consistently
from indexed tensor uses. An equation's left side declares output tensor/free
indices; its right side computes each output element. This is an evaluation
contract, not a proof that arbitrary pre-existing left and right bindings agree.
An optional typed `equation_id` configuration selects one equation; otherwise all
equations execute in stable identity order.

The backend enforces 100,000 evaluation steps, depth 64 and at most 1,024 output
elements. Resource tensor inputs currently use the documented little-endian
float64 media type. Unit-bearing resources are explicitly rejected until a backend
implements their unit algebra; dimensions are never silently stripped. Unsupported
syntax, conflicting dimensions, unbound symbols,
division by zero and numeric range failures produce diagnostics. Cancellation
is not available for this synchronous bounded backend.

Results are immutable TensorValue observations and produced little-endian
float64 resource bytes. Each observation/artifact names every mathematical
object used to produce it. The generic computation facade validates origins,
publishes resources, records revision/input/implementation provenance and
publishes activity through the existing runtime and semantic selection planes.
Graph, table and hierarchy notations decorate those original identities.

The workbench's **Computation and evidence** tab lists available registered
backends, runs the selected model and inspects evidence, input identity and
origin-linked observations/resources. This UI is generic. Persisted evidence
can be loaded from the saved project's evidence store; selecting an observation
navigates to its original semantic objects. It does not modify canonical data.

## Reproducible proof

The checked-in proof is `examples/proofs/foundation-math`. Its canonical project
contains the equation:

```text
C[i,j] = sum(k, A[i,k] * B[k,j])
A = [[1, 2], [3, 4]]
B = [[5, 6], [7, 8]]
C = [[19, 22], [43, 50]]
```

Run from the source root, using an installed project environment:

```powershell
.venv/Scripts/python.exe tools/prove_foundation_math.py --output examples/proofs/foundation-math
```

Use a fresh `--output` directory to reproduce independently. The tool writes
`project.json`, `plan.json`, `plan.pb`, `evidence.pb`, `proof.json`, managed tensor/terminal resources and
durable evidence. It verifies the tensor result, origin identities, unchanged
canonical snapshot, zero ProgramModel functions, all three notation highlights,
and byte-preserving typed persistence. It then runs a portable worker using only
the decoded protobuf plan, terminal resource closure and static registry, requiring
the complete evidence to equal the editor-side result. The evidence also crosses
the binary protobuf boundary without changing any typed value or origin.

`tests/test_foundations.py` additionally proves reference ownership across math
and space, spatial diagnostics, schema installation, typed controls and
table/form/composed edits with undo over the same objects. This proof complements
the existing seventeen Python examples; it is not routed through their Python
build verification.
