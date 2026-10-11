# Provenance

## Consulted material

The redesign requirements were derived from:

- the controlling `CODEX_TASK_DRAKON_STUDIO_SOURCE_INFORMED_REDESIGN.md`;
- `CODEX_STAGE_A_REFERENCE_ANALYST.md`;
- `CODEX_TASK_SOURCE_INFORMED_DRAKON_PYTHON_EDITOR.md`;
- `DRAKON.pdf` and the three supplied English DRAKON parts;
- the independently written `cleanroom_spec/` package;
- the parent repository's README, documentation, examples, and user-supplied screenshot;
- observable product lessons recorded in the controlling specification.

The historical `drakon_editor1.31/` directory is read-only reference material. No source from it is imported, copied, translated, or modified.

## Independently authored material

All code, tests, architecture, schema, command contracts, IDs, package layout,
documentation, and built-in vector recipes under `code visualizer/` are newly authored.
The recipe engine constructs all 27 icons and 21 macroicons from geometric primitives;
no supplied raster/vector icon is packaged as product artwork.

The bundled `DejaVuSansMono.ttf` and `DejaVuSans.ttf` are unmodified DejaVu Fonts 2.37 release assets used for reproducible Qt/off-screen text. Their SHA-256 values are `b4a6c3e4faab8773f4ff761d56451646409f29abedd68f05d38c2df667d3c582` and `7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954`. The upstream license is retained beside them. They are not DRAKON artwork and do not influence icon geometry.

## Visual-language facts retained

The redesign retains public notation intent such as downward normal flow, explicit preferred routes, orthogonal connectors, structured loops, the visual alphabet, macroicons, silhouettes, and measurable metre/rhythm/air/common-fate relationships. It does not retain historical storage, widget, SQL, or generator implementation.

## Independent review result

The production package imports only modules beneath `code_visualizer`, declared
dependencies, and the standard library. Architecture tests reject parent-prototype
imports and Qt in core packages. The native schema contains no historical SQL, Tcl
procedure, or `.drn` token. Supplied screenshots and `crossroad.png` were used only as
behavioral evidence and are not bundled artwork.
