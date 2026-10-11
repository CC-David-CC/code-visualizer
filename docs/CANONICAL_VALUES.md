# CanonicalValue version 1

`domain.values` defines a closed immutable contract. Text, boolean, integer and real
retain their existing Python scalar representation. Complex, quantity, inline tensor
and resource reference use frozen dataclasses. None means absence, never an extra
value variant. Native persistence and Protobuf adapters validate the same constructors.

| Variant | Contract |
| --- | --- |
| Text | UTF-8, at most 65,536 bytes |
| Boolean | True or false, distinct from integer |
| Integer | Signed magnitude at most 4,096 bits |
| Real | Finite IEEE binary64, preserving negative zero |
| Complex | Two finite real components |
| Quantity | Integer/real/complex magnitude and versioned unit reference |
| Tensor | Explicit dtype, shape and immutable numeric/boolean elements |
| ResourceReference | Descriptor identity and lowercase SHA-256 content hash |

Inline tensors contain at most 1,024 elements and 16 axes. Shape product must equal
element count. Empty axes and rank-zero scalars are explicit. Dtypes distinguish
boolean, signed/unsigned 8/16/32/64-bit integers, float32/64 and complex64/128.
Elements must fit their declared dtype exactly. Float32 values must be rounded
explicitly before admission; the canonical boundary never silently loses precision.
Resource tensors can be larger. In-memory resource reads have a separate 64 MiB
limit; file-oriented backends use verified resource paths and streaming libraries.

A `Dimension` is a sorted tuple of unique basis identities and nonzero integral
exponents. It contains no physical quantity enumeration. A unit reference pins its
identity, version and declared dimension. Schemas can require a dimension, tensor
dtype or partially constrained shape. The domain defines units, conversions,
coordinate interpretation and equation semantics; the kernel checks structure.

Native scalar JSON remains readable. Compound values use a closed tagged object:

```json
{"$value":"tensor","version":1,"dtype":"float64","shape":[2,2],"elements":[1.0,2.0,3.0,4.0]}
```

Unknown tags, versions and compound fields fail explicitly. A property cannot
contain arbitrary dictionaries, callbacks, Python complex objects, NumPy arrays
or millions of samples. Large data becomes a resource. Schema defaults and choices,
authority commands, undo patches and project persistence use the same codec.

Canonical storage equality preserves the value variant and floating-point bits,
including signed zero. Setting an integer property value from `1` to `1.0`, or a
real from `0.0` to `-0.0`, is an observable authoring edit with an exact inverse.
This also applies inside quantities and tensors, schema defaults and choices,
computation configuration and evidence. Mathematical query equality is a separate
operation and does not decide whether persisted authoring state changed.

Domain-to-domain templates may copy compound values without changing their meaning.
Generic query equality handles them as typed values; arithmetic and ordered
comparisons remain defined only for their declared operand types. Python runtime
literals require supported scalar values: a domain must explicitly lower its
compound values into executable semantics rather than relying on repr or coercion.

Cross-model references are explicit immutable input dependencies. Queries enumerate
their selected source model; role traversal can reach referenced objects when the
caller supplies the input workspace. This does not copy those objects or change
their containment owner. Unit/resource references are values, not newly owned
semantic objects discovered by a dataclass walk.

## Rational dimension extension (P3)

Dimension powers now admit bounded exact rational exponents, reduced to a positive
denominator. Integral results use the original integer representation. Native
dimensions with fractional powers explicitly carry version 2 and numerator/
denominator fields; integer dimensions retain their original bytes. Quantity
version 2 is admitted only with a fractional dimension. Other value variants
retain version 1; relabeled tensors and mixed/unnormalized encodings reject.

Protobuf adds a versioned rational-dimension field without reusing any released
field number. Old integer messages remain byte-identical. Resources, evidence,
commands and schema constraints use these same nested adapters. Native project
revision 11 remains the unchanged container: only the already versioned value
contract is extended. No authored input or journal requires an automatic rewrite;
legacy n decodes as the integral member of the same exact algebra. This preserves
P2 frozen-definition hashes rather than migrating every old project gratuitously.

The dimension editor accepts an integer or exact ratio, such as -5/2. Values remain
small; this does not add a Rational/Decimal variant to CanonicalValue. Mathematical
and physical operator meaning still belongs to foundation domains.
