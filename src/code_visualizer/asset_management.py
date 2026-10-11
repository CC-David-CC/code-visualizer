"""Bounded, inert project asset ingestion and shape-pack sanitization."""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from code_visualizer.domain.assets import ManagedAsset, ShapePackReference

MAX_IMAGE_SOURCE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
MAX_MANIFEST_BYTES = 1 * 1024 * 1024
MAX_SVG_BYTES = 512 * 1024
MAX_SHAPES_PER_PACK = 128
MAX_SVG_ELEMENTS = 2_000
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,31}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_TRANSFORM = re.compile(r"[A-Za-z0-9.,() +\-]*\Z")


class AssetSafetyError(ValueError):
    """A stable rejection for unbounded, active, or escaping asset content."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class InstalledShape:
    id: str
    name: str
    relative_path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class InstalledShapePack:
    reference: ShapePackReference
    shapes: tuple[InstalledShape, ...]


def _read_bounded(path: Path, limit: int, *, code: str) -> bytes:
    try:
        size = path.stat().st_size
        if size > limit:
            raise AssetSafetyError(code, f"{path.name} exceeds the {limit}-byte safety limit")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except AssetSafetyError:
        raise
    except OSError as exc:
        raise AssetSafetyError("ASSET_READ_FAILED", f"Cannot read {path.name}: {exc}") from exc
    if len(data) > limit:
        raise AssetSafetyError(code, f"{path.name} exceeds the {limit}-byte safety limit")
    return data


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        raise AssetSafetyError(
            "ASSET_WRITE_FAILED", f"Cannot install {target.name}: {exc}"
        ) from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_project_asset(project_root: Path, relative_path: str) -> Path:
    """Resolve already-trusted metadata while still enforcing project containment."""

    pure = PurePosixPath(relative_path)
    if (
        pure.is_absolute()
        or "\\" in relative_path
        or ".." in pure.parts
        or "." in pure.parts
        or not pure.parts
        or pure.parts[0] != "assets"
    ):
        raise AssetSafetyError("ASSET_UNSAFE_PATH", "Asset path escapes the project assets folder")
    root = project_root.resolve()
    target = root.joinpath(*pure.parts).resolve()
    assets_root = (root / "assets").resolve()
    if not _within(assets_root, target):
        raise AssetSafetyError("ASSET_UNSAFE_PATH", "Asset path escapes the project assets folder")
    return target


def import_managed_image(project_root: Path, source: Path) -> ManagedAsset:
    """Decode and re-encode one still image so metadata and appended payloads are removed."""

    data = _read_bounded(source.resolve(), MAX_IMAGE_SOURCE_BYTES, code="IMAGE_TOO_LARGE")
    try:
        with Image.open(BytesIO(data)) as opened:
            width, height = opened.size
            frames = int(getattr(opened, "n_frames", 1))
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise AssetSafetyError(
                    "IMAGE_PIXEL_LIMIT",
                    f"Image dimensions {width}x{height} exceed the safe pixel budget",
                )
            if frames != 1:
                raise AssetSafetyError(
                    "IMAGE_ANIMATION_UNSUPPORTED", "Managed images must be still"
                )
            opened.load()
            converted = opened.convert("RGBA" if "A" in opened.getbands() else "RGB")
            output = BytesIO()
            converted.save(output, format="PNG", optimize=True, compress_level=9)
            sanitized = output.getvalue()
    except AssetSafetyError:
        raise
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise AssetSafetyError(
            "IMAGE_INVALID", "The selected file is not a safe decodable image"
        ) from exc
    if len(sanitized) > MAX_IMAGE_OUTPUT_BYTES:
        raise AssetSafetyError("IMAGE_TOO_LARGE", "Sanitized image exceeds the output safety limit")
    digest = hashlib.sha256(sanitized).hexdigest()
    relative = f"assets/images/{digest}.png"
    target = resolve_project_asset(project_root, relative)
    if target.exists():
        existing = _read_bounded(target, MAX_IMAGE_OUTPUT_BYTES, code="IMAGE_TOO_LARGE")
        if hashlib.sha256(existing).hexdigest() != digest:
            raise AssetSafetyError(
                "ASSET_HASH_COLLISION", "Existing managed image has wrong content"
            )
    else:
        _atomic_write(target, sanitized)
    return ManagedAsset(
        id=f"asset_{digest[:24]}",
        relative_path=relative,
        sha256=digest,
        media_type="image/png",
        byte_size=len(sanitized),
        original_name=source.name,
        width=width,
        height=height,
    )


def verify_managed_asset(project_root: Path, asset: ManagedAsset) -> bool:
    if _HASH.fullmatch(asset.sha256) is None or asset.byte_size < 0:
        return False
    try:
        target = resolve_project_asset(project_root, asset.relative_path)
        data = _read_bounded(
            target, max(MAX_IMAGE_OUTPUT_BYTES, asset.byte_size), code="ASSET_TOO_LARGE"
        )
    except AssetSafetyError:
        return False
    return len(data) == asset.byte_size and hashlib.sha256(data).hexdigest() == asset.sha256


_ALLOWED_ELEMENTS = {
    "svg",
    "g",
    "path",
    "rect",
    "circle",
    "ellipse",
    "line",
    "polyline",
    "polygon",
    "text",
}
_ALLOWED_ATTRIBUTES = {
    "id",
    "viewBox",
    "width",
    "height",
    "preserveAspectRatio",
    "transform",
    "d",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "points",
    "fill",
    "fill-opacity",
    "stroke",
    "stroke-width",
    "stroke-linecap",
    "stroke-linejoin",
    "stroke-opacity",
    "opacity",
    "font-size",
    "font-family",
    "font-weight",
    "text-anchor",
}


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def sanitize_shape_svg(source: bytes) -> bytes:
    """Return deterministic, passive SVG or reject the complete shape."""

    if len(source) > MAX_SVG_BYTES:
        raise AssetSafetyError("SHAPE_SVG_TOO_LARGE", "Shape SVG exceeds the safety limit")
    folded = source.lower()
    if b"<!doctype" in folded or b"<!entity" in folded:
        raise AssetSafetyError(
            "SHAPE_SVG_ACTIVE_CONTENT", "DTD and entity declarations are forbidden"
        )
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise AssetSafetyError("SHAPE_SVG_INVALID", f"Invalid SVG: {exc}") from exc
    elements = tuple(root.iter())
    if len(elements) > MAX_SVG_ELEMENTS:
        raise AssetSafetyError("SHAPE_SVG_TOO_COMPLEX", "Shape SVG has too many elements")
    for element in elements:
        namespace = element.tag[1:].split("}", 1)[0] if element.tag.startswith("{") else ""
        tag = _local_name(element.tag)
        if namespace not in {"", SVG_NAMESPACE} or tag not in _ALLOWED_ELEMENTS:
            raise AssetSafetyError(
                "SHAPE_SVG_ACTIVE_CONTENT",
                f"SVG element {tag!r} is not permitted in a visual shape pack",
            )
        if element.tail and element.tail.strip():
            raise AssetSafetyError("SHAPE_SVG_INVALID", "Mixed SVG tail text is not supported")
        if tag != "text" and element.text and element.text.strip():
            raise AssetSafetyError("SHAPE_SVG_INVALID", "Text is permitted only in text elements")
        if element.text is not None and len(element.text) > 2_000:
            raise AssetSafetyError("SHAPE_SVG_TOO_COMPLEX", "SVG text exceeds the safety limit")
        normalized: dict[str, str] = {}
        for raw_name, raw_value in element.attrib.items():
            name = _local_name(raw_name)
            value = raw_value.strip()
            lowered = value.casefold()
            if (
                raw_name.startswith("{")
                or name.casefold().startswith("on")
                or name not in _ALLOWED_ATTRIBUTES
                or "url(" in lowered
                or "javascript:" in lowered
                or "data:" in lowered
                or "@import" in lowered
                or "expression(" in lowered
            ):
                raise AssetSafetyError(
                    "SHAPE_SVG_ACTIVE_CONTENT",
                    f"SVG attribute {name!r} is not permitted",
                )
            if name == "transform" and _SAFE_TRANSFORM.fullmatch(value) is None:
                raise AssetSafetyError("SHAPE_SVG_ACTIVE_CONTENT", "Unsafe transform syntax")
            if len(value) > 32_000:
                raise AssetSafetyError("SHAPE_SVG_TOO_COMPLEX", "SVG attribute is too long")
            normalized[name] = value
        element.attrib.clear()
        element.attrib.update(sorted(normalized.items()))
        element.tag = f"{{{SVG_NAMESPACE}}}{tag}"
    if _local_name(root.tag) != "svg":
        raise AssetSafetyError("SHAPE_SVG_INVALID", "Shape root must be an SVG element")
    if "viewBox" not in root.attrib:
        raise AssetSafetyError("SHAPE_SVG_INVALID", "Shape SVG requires a viewBox")
    ET.register_namespace("", SVG_NAMESPACE)
    result = ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
    return bytes(result) + b"\n"


def _manifest_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AssetSafetyError("SHAPE_PACK_INVALID", f"{label} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _required_manifest_text(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AssetSafetyError("SHAPE_PACK_INVALID", f"Manifest {key!r} must be non-empty text")
    return value.strip()


def _safe_shape_source(base: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or "\\" in relative or ".." in pure.parts or "." in pure.parts:
        raise AssetSafetyError("SHAPE_PACK_PATH_TRAVERSAL", "Shape paths cannot escape the pack")
    resolved_base = base.resolve()
    candidate = resolved_base.joinpath(*pure.parts).resolve()
    if not _within(resolved_base, candidate):
        raise AssetSafetyError("SHAPE_PACK_PATH_TRAVERSAL", "Shape paths cannot escape the pack")
    return candidate


def install_shape_pack(project_root: Path, manifest_path: Path) -> InstalledShapePack:
    """Install a strict versioned visual-only manifest and sanitized local SVG shapes."""

    source = _read_bounded(manifest_path.resolve(), MAX_MANIFEST_BYTES, code="SHAPE_PACK_TOO_LARGE")
    try:
        raw: object = json.loads(source)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetSafetyError("SHAPE_PACK_INVALID", f"Invalid shape-pack JSON: {exc}") from exc
    manifest = _manifest_object(raw, "Manifest")
    allowed_keys = {"schema_version", "id", "name", "version", "shapes"}
    unknown = set(manifest) - allowed_keys
    if unknown:
        raise AssetSafetyError(
            "SHAPE_PACK_SEMANTICS_FORBIDDEN",
            f"Unknown manifest fields are forbidden: {', '.join(sorted(unknown))}",
        )
    if manifest.get("schema_version") != 1:
        raise AssetSafetyError("SHAPE_PACK_INVALID", "Shape-pack schema_version must be 1")
    pack_id = _required_manifest_text(manifest, "id")
    name = _required_manifest_text(manifest, "name")
    version = _required_manifest_text(manifest, "version")
    if _IDENTIFIER.fullmatch(pack_id) is None or _VERSION.fullmatch(version) is None:
        raise AssetSafetyError(
            "SHAPE_PACK_INVALID", "Pack ID or version contains unsafe characters"
        )
    raw_shapes = manifest.get("shapes")
    if not isinstance(raw_shapes, list) or not 1 <= len(raw_shapes) <= MAX_SHAPES_PER_PACK:
        raise AssetSafetyError("SHAPE_PACK_INVALID", "Shape packs require 1 to 128 shapes")
    source_root = manifest_path.resolve().parent
    installed: list[InstalledShape] = []
    normalized_shapes: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw_shape in enumerate(raw_shapes):
        shape = _manifest_object(raw_shape, f"shapes[{index}]")
        if set(shape) != {"id", "name", "svg"}:
            raise AssetSafetyError(
                "SHAPE_PACK_SEMANTICS_FORBIDDEN",
                "Each shape may contain only id, name, and svg fields",
            )
        shape_id = _required_manifest_text(shape, "id")
        shape_name = _required_manifest_text(shape, "name")
        shape_source = _required_manifest_text(shape, "svg")
        if _IDENTIFIER.fullmatch(shape_id) is None or shape_id in seen:
            raise AssetSafetyError(
                "SHAPE_PACK_INVALID", "Shape IDs must be unique safe identifiers"
            )
        seen.add(shape_id)
        source_path = _safe_shape_source(source_root, shape_source)
        sanitized = sanitize_shape_svg(
            _read_bounded(source_path, MAX_SVG_BYTES, code="SHAPE_SVG_TOO_LARGE")
        )
        digest = hashlib.sha256(sanitized).hexdigest()
        relative = f"assets/shape-packs/{pack_id}/{version}/shapes/{shape_id}.svg"
        _atomic_write(resolve_project_asset(project_root, relative), sanitized)
        installed.append(InstalledShape(shape_id, shape_name, relative, digest))
        normalized_shapes.append(
            {"id": shape_id, "name": shape_name, "sha256": digest, "svg": relative}
        )
    normalized_manifest = {
        "id": pack_id,
        "name": name,
        "schema_version": 1,
        "shapes": normalized_shapes,
        "version": version,
        "visual_only": True,
    }
    normalized = (
        json.dumps(normalized_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_digest = hashlib.sha256(normalized).hexdigest()
    relative_manifest = f"assets/shape-packs/{pack_id}/{version}/manifest.json"
    _atomic_write(resolve_project_asset(project_root, relative_manifest), normalized)
    reference = ShapePackReference(
        id=f"{pack_id}@{version}",
        name=name,
        version=version,
        manifest_path=relative_manifest,
        sha256=manifest_digest,
    )
    return InstalledShapePack(reference, tuple(installed))
