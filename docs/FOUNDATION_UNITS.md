# Units as ordinary domain meaning

`foundation.units@1` defines the language of unit systems. The intentional kernel
still knows only identity, typed values, containment, references and dimensional
contracts. `foundation.units.si@1` supplies immutable reference data using that
language; neither SI names nor conversion rules are kernel primitives.

## Canonical ownership

The schema contains these ordinary concepts:

| Concept | Canonical contents |
| --- | --- |
| DimensionBasis | Name, globally owned contract ID and version |
| DimensionFactor | Nonzero integer exponent and reference to a basis |
| UnitDefinition | Name, symbol, contract ID/version and owned dimension factors |
| Conversion | Source/target unit references, scale, offset and optional context |
| UnitSystem | Name, contract ID/version and owned bases, units and conversions |

The SI vocabulary is one immutable `DomainModel` contributed as bundle reference
data. Installing it uses the existing authority and ordinary schema/model
commands. The contribution has a declared dependency on `foundation.units@1`;
it does not claim ownership of that bundle's schema. Modified installed reference
data receives an explicit validation diagnostic and cannot be used as the
published vocabulary. A different system is authored as another ordinary
model using the same schema.

Node IDs such as `si-v1:unit:meter` identify intentional objects. Their
`contract_id` properties such as `foundation.units.si:meter` identify public
contracts. Renaming or relocating an author's object never renames its public
contract implicitly. Public contract names use the global naming convention;
versions occupy separate fields. A dimension basis ID is immutable across
versions because the existing `DimensionPower` contract refers to the basis
identity without a version field. A changed basis requires a new identity.

`UnitCatalog` is a disposable typed index derived solely from model contents.
It is not another canonical table of unit meanings, and it is never persisted.
The SI reference model and its derived catalog can be cached because their
contents are immutable. Published contract lists are also derived from that
same reference model.

## Shared SI vocabulary

The seven base dimension identities are:

```text
foundation.units.si:basis.length
foundation.units.si:basis.mass
foundation.units.si:basis.time
foundation.units.si:basis.electric_current
foundation.units.si:basis.temperature
foundation.units.si:basis.amount
foundation.units.si:basis.luminous_intensity
```

Version 1 contains meter, kilogram, second, ampere, kelvin, mole and candela;
dimensionless one; hertz, newton, pascal, joule, watt, coulomb, volt, ohm, farad,
weber, tesla and henry; degree Celsius; and seven explicit prefixed examples.
The base vocabulary follows the [BIPM SI base units](https://www.bipm.org/en/measurement-units/si-base-units)
and dimensional combinations follow the [BIPM SI Brochure](https://www.bipm.org/en/publications/si-brochure).
The public spelling `meter` is fixed for this API; human notations may show
“metre” without changing the identity.

A volt and a millivolt share the declared powers `mass¹ length² time⁻³
electric_current⁻¹`. A newton uses `mass¹ length¹ time⁻²`. An electrical extension
and a mechanical extension therefore refer to the same time and length bases.
No extension may reinterpret `foundation.units.si:meter@1` as a time unit.
SI validation checks references in authored quantity values, schema defaults
and choices, and the generic value-validation seam checks external quantities
and resource unit descriptors at admission.

## Conversion boundary

```python
catalog = si_catalog()  # derived from the registered SI intentions
source = catalog.unit("foundation.units.si:millivolt", "1")
target = catalog.unit("foundation.units.si:volt", "1")
result = catalog.convert(QuantityValue(1200, source), target)
# QuantityValue(1.2, target)
```

The operation validates both identity/version/dimension contracts, requires
identical declared dimensions, then resolves an explicitly declared conversion
path. Each edge means `target = source * scale + offset`; its inverse follows
from the same edge. Scale must be finite and nonzero. Integer powers, reference
integrity and duplicate contract identities are validated before conversion.

Applicable conversion graphs must be forests. Duplicate, redundant and cyclic
paths produce `UNIT_CONVERSION_AMBIGUOUS`, even when somebody considers their
numerical results equivalent. This prevents registry order or a floating-point
tolerance from choosing a physical meaning. A named conversion context is
explicitly selected; unconditional edges remain applicable within that context.
Independent context-specific conversions are not silently combined.

Equal dimensions alone never manufacture a conversion. A third-party inch
definition can reference the existing SI length basis and declare an inch to
meter edge. The existing meter-to-centimeter edge then composes automatically.
Different dimensional conventions, natural units and nonlinear calibrations
need an explicit interpretation that owns those meanings; the v1 affine
converter diagnoses their absence instead of assuming equivalence.

The interpreter composes finite coefficients with internal rational arithmetic
to avoid intermediate binary rounding, then returns the existing integer, real
or complex magnitude variants. This does not add an exact-number variant to
`CanonicalValue` or claim arbitrary-precision real output. Complex scaling is
supported; complex values with an offset and numeric overflow produce explicit
diagnostics. Temperature intervals and unit algebra remain domain-level
semantics; an absolute Celsius-to-kelvin conversion does not imply that adding
two absolute temperatures is valid.

## Persistence and proofs

The schema, reference intentions and quantity values round-trip through the
existing deterministic project JSON and typed Protobuf adapters. No unit-specific
wire payload, callback, expression parser or `eval` is introduced. A unit
conversion returns a value; it does not mutate an authored parameter. Promotion
uses the same existing explicit authority edit as every other computed value.

`tests/test_foundation_units.py` covers ordinary schema validation, common base
and derived dimensions, third-party units using shared bases, scale/offset and
inverse composition, named contexts, dimensional mismatch, duplicate/cyclic
paths, invalid public IDs, immutable SI contracts, complex/range failures and
JSON/Protobuf round trips. Existing architecture and dependency tests ensure
the kernel remains independent of the foundation implementations.
# P3 unit products and numerical adapter

`foundation.units.algebra@1` adds ordinary `ProductUnit`, `UnitEquation`, and
`Factor` intentions. Factors carry a positive real quantity measure and a bounded,
reduced rational power. These are foundation data, not new canonical value kinds.
The derived `UnitCatalog` resolves them together with the existing explicit
conversion graph. Cycles, conflicting product anchors, incompatible dimensions,
unknown versions and undeclared conversion paths are diagnostics.

`foundation.units.algebra.si@1` declares SI products and four additional units:
kiloohm, newton per meter, newton per millimeter, and volt per root hertz. It does
not alter the released SI catalog. Product factors retain typed unit references,
so publication proves their exact bundle dependency closure. Released SI product
meanings cannot be shadowed by a project.

The optional `science` extra pins Pint, SymPy and NumPy. The Pint adapter constructs
an empty registry only after the catalog authorizes an operation. It supplies
private generated identifiers and numerical definitions; neither Pint's default
vocabulary nor author-entered parser text determines domain permissions. Affine
points and intervals have distinct operations. Frequency and logarithmic kinds
require an explicit supported operator and currently diagnose unsupported use.

The arithmetic kind operation receives operand dimensions when interpreting
interval scaling. LINEAR alone does not imply a scalar: only an explicitly empty
dimension preserves INTERVAL under multiplication (either order) or division of
the interval. Dimensional products and inverse intervals have ordinary linear
kind and composed dimensions. An ambiguous call without dimensional context
reports `UNIT_DIMENSION_REQUIRED`; all equation compiler calls supply that context.

Equality is distinct from arithmetic subtraction. It compares like supported
kinds and returns an interval residual for two points. The compiler additionally
checks dimensions and declared unit factors. A legal point-minus-interval
translation does not authorize equating a point to an interval. This correction
does not change the unit catalogs, canonical values or portable result formats.
