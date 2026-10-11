"""Inert managed-asset metadata; project loading never dereferences asset sources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ManagedAsset:
    id: str
    relative_path: str
    sha256: str
    media_type: str
    byte_size: int
    original_name: str = ""
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class ShapePackReference:
    id: str
    name: str
    version: str
    manifest_path: str
    sha256: str
