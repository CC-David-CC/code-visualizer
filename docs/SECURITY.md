# Security model

## Trust boundary

Native project files, visual assets, and shape packs are untrusted data. Opening,
recovering, searching, validating, rendering, generating, and exporting them must not
execute project Python. Run, Trace, Debug, and F5 are explicit user/capability actions.
Those actions run ordinary local child processes with the current OS account; Code
Visualizer does not claim an OS sandbox.

## Local authority and automation

One OS-backed lease owns each writable project. The desktop or headless authority
serializes commands, revisions, events, and durable journal records. Conflicting
writers receive owner metadata and may connect or open read-only.

WebSocket JSON-RPC binds to loopback by default and requires an ephemeral bearer token
at upgrade. Non-loopback binding needs an explicit flag and warning. Grants separate
read, edit, propose, save, generate, execute, destructive, and admin capabilities.
Proposal mode cannot mutate until a human accepts against its original revision.
Tokens are secrets: do not paste them into project source or logs.

MCP exposes semantic project tools, not shell, package installation, raw pixel drawing,
or arbitrary execution. All transports enforce bounded messages and reach the same
command validation as the GUI.

## Persistence and recovery

JSON and journal reads have byte limits; trailing interrupted journal records are
ignored; identity conflicts fail closed. Native writes use same-directory temporary
files, flush/fsync, and atomic replacement. Journal append failure truncates back to
the prior durable boundary so a rejected command cannot reappear during recovery.
Generated directories use a rollback backup; failed or stale promotion preserves the
prior complete manifest-backed set.

Read-only recovery never promotes or rewrites data. Future schema versions open
read-only only if required metadata can be decoded safely.

## Assets and exports

Imported images have size/dimension bounds, are decoded, re-encoded as inert PNG,
hashed, and copied beneath the project. Passive shape-pack SVG rejects scripts,
events, external URLs, traversal, foreign objects, and semantic command content.
Managed hashes are checked before display/export. Cross-project clipboard fragments
carry versioned safe semantic data and report external references for rebinding; they
cannot embed executable callbacks.

## Process and output controls

Runners use argument arrays rather than a shell, explicit working directories and
environment overlays, bounded stdout/stderr, timeouts, and stop/terminate handling.
Debug and trace workers use bounded protocols. A project can still read/write anything
its OS user can access once explicitly executed.

## Dependency and license review

The release environment records versions in build/test output. Runtime dependencies
reviewed for this release are PySide6 6.11.2 (LGPL-3.0-only or GPL alternatives),
Pillow 12.3.0 (MIT-CMU), and websockets 16.1.1 (BSD-3-Clause). Optional debugpy 1.8.21
is MIT. Build 1.6.0 is MIT; PyInstaller 6.22.2 is GPLv2-or-later with its distribution
exception. The bundled DejaVu font license is shipped beside the font files.

## Reporting

Security reports should include the native schema version, application version,
platform, exact operation or file, whether execution capability was granted, and the
smallest non-sensitive reproduction. Never include bearer tokens or private project
source in a public report.
