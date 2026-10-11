# Domain schemas and canonical intentions

`domain.intentional` supplies immutable typed values for domains that use generic
storage. `Project.domain_workspace` owns these schemas and instances. The existing
`Project.program_model` owns directly authored programming semantics through its
specialized representation. A transformed program is a disposable build result and
is never written into either canonical owner.

## Identity and schema vocabulary

Every schema, concept definition, property definition, role definition, constraint,
model, and intentional node has an opaque stable identity. Names, positions and
notation do not determine identity. Definition IDs are used as keys in instance
values, so renaming a property or role does not reinterpret its existing contents.
Domain IDs must not collide with other canonical semantic identities.

`DomainSchema(id, namespace, version, concepts, bundle, description)` contains one
active version of a schema in a project. Each `DomainModel` pins that schema ID and
version. `bundle` is an optional `BundleReference(id, version)` to registered
implementation behavior; the full inert schema remains in the project so its
contents remain inspectable when the implementation is unavailable.

A bundle that claims a schema in its `schemas` contribution must have that schema
explicitly name the same owning bundle ID and version. Registration rejects a missing
or mismatched owner, so registered validators and semantic indexing cannot silently
become unreachable. A notation-only extension can target an independent user schema
without claiming ownership of that schema. Unbundled user schemas remain legal.

`ConceptDefinition` owns:

- `properties`: named `PropertyDefinition` values;
- `containment_roles`: roles that exclusively own children;
- `reference_roles`: roles that point to other nodes;
- `constraints`: closed declarative validation rules;
- `display_property_id`: the property used for a human label;
- descriptive text.

`PropertyDefinition` declares one of `string`, `integer`, `number`, `boolean`,
`complex`, `quantity`, `tensor` or `resource`, whether a value is required, an
optional default, allowed typed choices, optional dimension/dtype/shape constraints and
numeric bounds. Booleans are not accepted as integers or numbers. Numbers must be
finite. Property absence represents an unset optional value; null is not an additional
untyped value category. Creation inserts declared defaults once into the canonical
node. Later schema changes do not silently rewrite existing instance values.

`RoleDefinition` declares permitted concept IDs, minimum and maximum cardinality,
and whether ordering matters. Containment target concepts belong to the same schema
and their nodes belong to the same model. Reference targets may belong to another
model/schema in the same workspace when the role explicitly permits their concept.
References can form cycles. An unordered role has no positional domain meaning;
its explicit ID sequence is still preserved by persistence.

The initial declarative `ConstraintDefinition` kinds are:

- `NONEMPTY`: a local text property must contain non-whitespace text;
- `UNIQUE_PROPERTY`: a property must be unique among a containment role's children.

More involved domain validation belongs to registered extension implementation
code. Persisted schema values contain no callbacks, module names to import, Python
expressions to evaluate, or executable code.

## One containment owner

```text
DomainModel
  roots: stable IDs
  nodes: one flat tuple of IntentionalNode values
    node.id / concept_id
    properties: PropertyValue(property_id, CanonicalValue)
    children: RoleBinding(role_id, child IDs)
    references: RoleBinding(role_id, target IDs)
```

A node occurs exactly once in the node table and has exactly one incoming
containment ownership edge or one root entry. Children are IDs, never copies of
nodes. There is no competing stored parent pointer. Every containment component
must be rooted and acyclic. The validator uses bounded iterative traversal of the
flat graph and reports malformed ownership rather than recursing through it.

## Editing and incomplete state

`application.domain_commands` contains typed commands consumed by the existing
`ProjectAuthority`. `application.features.domains` owns their handlers, and the
normal static authority registry composes them with `program.*` commands.

| Operation | Meaning |
| --- | --- |
| `domain.schema.put/delete` | Create, replace or remove a schema definition |
| `domain.schema.concept.put/delete` | Edit one schema concept |
| `domain.schema.property.put` | Add or change a property definition |
| `domain.schema.role.put` | Add or change a containment/reference definition |
| `domain.model.put/delete` | Create, replace or remove a model |
| `domain.node.create/delete` | Create an identity or delete its owned subtree |
| `domain.node.set_property` | Change one typed property; null unsets it |
| `domain.node.insert_child` | Attach an existing root to a containment role |
| `domain.node.move_child` | Move an existing node, retaining identity |
| `domain.node.remove_child` | Detach a child into the same model's roots |
| `domain.node.set_reference/remove_reference` | Edit explicitly named reference roles |
| `domain.bundle.put/delete` | Change required implementation references |

Incoming references must be removed explicitly before deleting their target.
Transactions can remove references and delete a subtree in one revision. A schema
change that affects existing instance types or pins must likewise provide a valid
final transaction result.

The authority validates structural safety at commit. Duplicate IDs, wrong value
types, undefined properties/roles, missing schemas/concepts, dangling edges, illegal
target concepts, maximum cardinality violations, multiple containment owners and
cycles reject the transaction. The decoder enforces the same boundary.

Missing required properties, minimum cardinality, text completeness, uniqueness,
range and choice constraints are explicit incomplete states. They can be saved and
edited but block generation until repaired. This lets a form create a machine before
all of its states and mandatory references exist. Missing extension implementations
are also build diagnostics; they never make the decoder discard project data.

All edits use the existing actor/revision/operation-ID conflict model, event stream,
journal, undo and redo. Node inverses carry only affected canonical nodes and changed
root ownership, preserving edits by another actor to disjoint nodes. Schema/model
replacement has an appropriately broader conflict scope. Multi-step redo replays
undone operations in original dependency order. The native journal restores the
same command history after a restart.

The Python SDK can use `client.submit(SetDomainProperty(...))` and the convenience
`put_domain_schema`, `put_domain_model`, `create_domain_node`, `delete_domain_node`,
`set_domain_property`, `move_domain_child`, and `set_domain_reference` methods.
Remote SDK, JSON-RPC and MCP route typed payloads through that same authority.

## Persistence and validation boundaries

Format revision 6 adds `domain_workspace` to the native snapshot. Explicit codecs in
`persistence.intentional` validate canonical value types without loading implementation code.

CanonicalValue version 1 is closed and bounded. Complex, quantity and small tensor
values have immutable typed representations; large arrays cross the resource boundary.
Unit and resource references are values rather than contained objects. See
[Canonical values](CANONICAL_VALUES.md) and [Resources and evidence](RESOURCES_AND_EVIDENCE.md).
Schemas, model pins, node IDs, property values, role bindings and bundle references
round-trip; tuple order is retained and JSON object keys are sorted. Numeric schema
bounds normalize to JSON numbers consistently. Revision 4/5 projects acquire an
empty domain workspace at the load boundary. The current writer uses revision 8,
which additionally persists typed `language_definitions` for schema-pinned notations,
validation queries and program templates. Revision 6 acquires an empty language
collection. See [Domain language](DOMAIN_LANGUAGE.md) for authoring and commands.

`validate_domain_workspace()` is pure and returns `DomainIssue` values.
`incomplete=False` protects integrity; `incomplete=True` reports build completeness.
`validate_project(..., extensions=registry)` combines these findings with explicit
registered extension requirements and domain validators. Supplying a registry is an
application composition decision, never a persisted request to load code.
