# Canonical Python program ownership

ProgramModel is the canonical **Python-program semantic model**. It is not a
language-neutral AST. Python owns this application, its orchestration, and the
supported programming runtime. General backend boundaries describe representations,
computation and evidence; they do not require every domain computation to become a
programming-domain model.

## Ownership cutover

Previously, a function carried its module/class spelling, and ModuleSetup held
imports, constants, aliases, executable source suites, package and entrypoint
settings. Those jointly described Python meaning. They also forced generation to
invent class/module identities from names and to reconstruct declaration order.

The canonical model now stores:

```text
ProgramModel
  package
  modules: ProgramModule(id, path, ordered body, docstring, MODULE/PACKAGE kind)
    ProgramImport / ProgramAssignment / ProgramTypeAlias
    ProgramAction and the existing structured statement families
    ProgramClass(id, identifier, bases/metaclass, decorators, ordered body)
    ProgramFunctionReference(function_id)
  functions: existing mature function table
  symbols: existing stable symbol table
  entrypoint: selected callable, literal arguments, typed startup declarations
```

A function's one owning declaration position references its stable table identity.
The function does not also store an owning module/class name or inverse owner ID.
Renaming or moving a scope changes its spelling or containment, preserving IDs.
Module and class IDs are project identities, never public contract identifiers.

The existing complete expression algebra and all twenty statement families remain.
Text admission parses imports, assignments, type aliases and class definitions into
typed canonical declarations. General Python suites, including imported helper
function definitions, retain complete Python AST structure in ProgramAction. There
is no persisted valid-source copy beside that tree. A helper function represented
inside such a suite is not also copied into the structured function table; the
structured editor owns functions in that table through explicit references.
Incomplete text remains an explicit, non-buildable expression as before.
Ordinary Python type comments are retained in the typed tree. Suites containing
`# type: ignore` currently retain their exact source as an explicit unsupported
expression and block generation, because their line-specific directive meaning
cannot yet survive normalized AST emission. They are never silently discarded.

## Runtime settings and derived output

Project.runtime_settings contains only interpreter/run profiles and their active
selection. It has no executable fields. The Python Project workspace submits
canonical program commands independently of runtime-profile edits.

```text
authored Python ProgramModel -----+
                                 +--> disposable composed ProgramModel
domain intentions --> transform -+            |
                                       ordered Python IR
                                              |
                               code_visualizer.python.source
                                              |
                            ordinary Python backend invocation
                                              |
                                    events and evidence
```

At the derived build boundary, contributions targeting the same module path are
composed in explicit contribution order. Origin links are retained; no transformed
module or function is saved into the authored ProgramModel. Module/class source
spans carry their actual canonical scope identities. MODULE emits a .py file;
PACKAGE emits the authored __init__.py for its folder. An empty package path denotes
the root ProgramModel.package initializer. Real package files and the launcher are
the sole execution representation for generated, live, trace, debug and backend
runs. Temporary execution preserves ordinary import machinery, file inspection,
package resources and initialization order. See [Python execution](PYTHON_EXECUTION.md).

## Migration and protocol boundaries

Native revision 10 imports legacy revision 4–9 executable setup into ProgramModel
once, including journal forward/inverse operations. Initial migration IDs are
deterministic; after loading they are stored identities. A legacy function's
unlisted module is materialized explicitly, matching the previous lowering behavior
that synthesized that module. This removes a redundant configuration dependency.
Invalid Python remains editable and diagnostic-producing; unsafe ownership fails
integrity checks.

Revision 11 renames the remaining runtime-only record to runtime_settings and stores
an explicit module kind. Legacy snapshots and journals migrate once on load. Old
terminal-v2 records without kind decode as MODULE after hash verification; new
terminal records include kind without rewriting existing immutable resources.

Portable computation terminal revision 2 carries the canonical model alone.
It does not carry executable ModuleSetup. The incompatible terminal payload has a
separate published logical-type version; old resources remain preserved and cannot
be silently interpreted as the new contract.

In-process authority, preparation and backend execution remain ordinary Python
calls. Protobuf is used only where there is a durable or process/network interchange
boundary. Future native libraries or foreign workers are implementation details
behind Python backend adapters. Circuit equations, simulation inputs and training
plans can therefore go directly to their own Python backends without becoming
ProgramModel or changing this programming domain.
