# Reversible cutover plan

The redesign remains an independent sibling directory. The parent prototype and the
historical Tcl reference stay untouched throughout cutover.

## Preconditions

1. Every M0-M9 gate and acceptance A-L has exact evidence in `STATUS.md`.
2. Ruff, mypy, all pytest tests, wheel inspection, and the source-folder offline
   bootstrap/GUI/CLI smokes pass.
3. Ubuntu CI builds/tests the same commit and smokes its source folder.
4. Example projects regenerate byte-for-byte, compile, and run as documented.
5. Icon/contact-sheet and First Delivery artifacts receive manual visual review.
6. Accessibility, security, provenance, and screen-reader results are recorded.

## Promotion

1. Tag the prototype's current revision; do not alter its native files.
2. Archive the release wheel, source distribution, source folder, manifests, and
   quality logs by version.
3. Make `code visualizer/` the documented launch root and point new shortcuts at
   `python launch.py`.
4. Keep prototype launch instructions under an explicitly named "Previous prototype"
   section for one release cycle.
5. New projects use only the current native development-format revision. There is no
   `.drn` import, export, inspection, or compatibility transform.

## Rollback

Rollback changes only launch/documentation pointers to the tagged prototype. It does
not transform projects or overwrite either implementation. Native redesign projects
remain readable by the archived redesign release; prototype projects remain where
they were. Copy the affected project directory before investigating a persistence
failure, and preserve `.code-visualizer/` recovery data.

## Removal decision

Remove the prototype from the default distribution only after the observation window
has no release-gate regression and archived binaries/source remain available. Never
replace the historical read-only reference or claim native-format compatibility that
does not exist.
