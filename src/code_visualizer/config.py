"""Central product identity and native development-format configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProductIdentity:
    name: str
    application_id: str
    project_format_revision: int
    state_directory: str


PRODUCT = ProductIdentity(
    name="Code Visualizer",
    application_id="org.codevisualizer.studio",
    project_format_revision=11,
    state_directory=".code-visualizer",
)
