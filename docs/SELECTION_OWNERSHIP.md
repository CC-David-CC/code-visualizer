# DRAKON selection and source extents

Selection follows semantic ownership. A function selects its complete generated
function, a structural atom selects its descendants, and an intrinsic case, handler,
or branch header selects only that owned branch. A leaf selects its own statement.

`domain.drakon_selection.selection_objects` walks the real selectable objects in the
existing typed diagram. `selection_ownership` resolves their owned identities using
`drakon_atom_ids`, including sequence identities for generated empty-body `pass`
statements. Sequence insertion markers, loop-end glyphs, branch-address glyphs,
End, and routing geometry are not independent semantic selections.

The canvas keeps `selected_object_ids` separate from `selected_atom_ids`. Generic
atom delete, move, duplicate, and field-edit actions consume only the latter.
Case, handler, branch, and function-header selections never become editable atoms.

The document resolves the intrinsic function header through `DrakonViewDefinition`
to the canonical callable ID. `ui_qt.source_selection.source_selection_range` then
uses existing source spans belonging to the selected object's ownership closure,
restricted to the bound presentation and one generated file. It computes the
earliest start and latest end; it does not rewrite any provenance span. For a
single span, the original span already gives the exact selection extent.

Source cursor navigation uses the direct provenance owner to select a visual node,
then applies the same ownership rule to its highlight. Thus `match value:` selects
the complete match, `case 1:` selects that case and its body, and an inner `print`
selects only that statement. The cursor stays at the line chosen by the user.

## Regression coverage

Run these tests from the source folder in an environment with the development
dependencies installed and `QT_QPA_PLATFORM=offscreen`:

```text
python -m pytest tests/test_structural_selection_qt.py tests/test_drakon_selection_ownership.py tests/test_function_header_selection_qt.py -q
```

The 30 dedicated tests include the unchanged nine function-header cases. The new
tests load the saved `05-select-match` project for actual mouse clicks and source
cursor navigation. They distinguish the duplicate print statements in its separate
condition and match blocks by their exact line positions. They cover match-to-leaf
contraction, empty cases, safe structural actions, handler/parallel/silhouette
headers, and exclusion of synthetic layout objects. A domain test checks recursive
ownership through a case containing another decision.

The new case-click, match-click, and case-source tests were also run against the
previously delivered UI modules: all three failed with the reported missing
selection or single-line match highlight. They pass with the generalized resolver.

`programmodel.verification.json`, delivered beside the archives, records the current
broader regression and extracted-package checks. These focused checks do not
constitute a rerun of the entire application test suite or long physical proofs.
