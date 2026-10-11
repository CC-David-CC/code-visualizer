import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from code_visualizer.application.messages import CommandAccepted, CommandRejected
from code_visualizer.application.session import ProjectSession
from code_visualizer.asset_management import (
    AssetSafetyError,
    import_managed_image,
    install_shape_pack,
    sanitize_shape_svg,
    verify_managed_asset,
)
from code_visualizer.domain.assets import ManagedAsset
from code_visualizer.domain.common import DocumentKind
from code_visualizer.domain.freeform import (
    FreeformDiagram,
    GuideOrientation,
    Rect,
    ShapeKind,
    ShapeObject,
)
from code_visualizer.persistence.decoding import ProjectDecodeError, project_from_data
from code_visualizer.persistence.serialization import project_to_data
from code_visualizer.rendering import ExportOptions, export_document, layout_freeform


def _write_image(path: Path) -> None:
    image = Image.new("RGBA", (24, 18), (220, 40, 80, 180))
    image.save(path, format="PNG")
    with path.open("ab") as stream:
        stream.write(b"untrusted appended metadata")


def test_managed_image_is_sanitized_hashed_contained_and_registered(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    source = tmp_path / "avatar.png"
    _write_image(source)

    asset = import_managed_image(project_root, source)
    target = project_root / Path(asset.relative_path)
    assert target.is_file()
    assert target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert b"untrusted appended metadata" not in target.read_bytes()
    assert asset.width == 24
    assert asset.height == 18
    assert hashlib.sha256(target.read_bytes()).hexdigest() == asset.sha256
    assert verify_managed_asset(project_root, asset)

    session = ProjectSession.new()
    try:
        result = session.client.register_managed_asset(asset)
        assert isinstance(result, CommandAccepted)
        session.client.create_diagram(DocumentKind.FREEFORM, "Images")
        diagram = session.authority.snapshot().documents[-1]
        assert isinstance(diagram, FreeformDiagram)
        session.client.create_freeform_shape(
            diagram.id,
            ShapeKind.IMAGE,
            Rect(10, 20, 240, 180),
            object_id="shape_image",
        )
        linked = session.client.transform_freeform_object(
            diagram.id,
            "shape_image",
            Rect(10, 20, 240, 180),
            asset_id=asset.id,
        )
        assert isinstance(linked, CommandAccepted)
        updated = session.authority.snapshot()
        image_diagram = updated.documents[-1]
        assert isinstance(image_diagram, FreeformDiagram)
        options = ExportOptions(
            asset_root=project_root,
            managed_assets=updated.managed_assets,
            transparent=True,
        )
        svg_path = tmp_path / "image-scene.svg"
        png_path = tmp_path / "image-scene.png"
        export_document(image_diagram, svg_path, options=options)
        export_document(image_diagram, png_path, options=options)
        assert "data:image/png;base64," in svg_path.read_text(encoding="utf-8")
        with Image.open(png_path) as rendered:
            assert rendered.width > 1 and rendered.height > 1
        rejected = session.client.remove_managed_asset(asset.id)
        assert isinstance(rejected, CommandRejected)
        assert rejected.code == "ASSET_IN_USE"
    finally:
        session.close()


def test_native_decode_rejects_asset_path_traversal_without_dereferencing() -> None:
    session = ProjectSession.new()
    try:
        unsafe = replace(
            session.authority.snapshot(),
            managed_assets=(
                ManagedAsset(
                    "asset_bad",
                    "../../outside.py",
                    "0" * 64,
                    "image/png",
                    1,
                    "outside.py",
                    1,
                    1,
                ),
            ),
        )
        with pytest.raises(ProjectDecodeError, match="ASSET_UNSAFE_PATH"):
            project_from_data(project_to_data(unsafe))
    finally:
        session.close()


@pytest.mark.parametrize(
    "payload",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><script/></svg>',
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10" '
            b'onload="x"><path d="M0 0"/></svg>'
        ),
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" '
            b'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
            b'<path xlink:href="https://example.invalid/x"/></svg>'
        ),
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><foreignObject/></svg>',
        (
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            b'<path filter="url(#x)"/></svg>'
        ),
        (
            b'<!DOCTYPE svg [<!ENTITY x "boom">]>'
            b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
            b"<text>&x;</text></svg>"
        ),
    ],
)
def test_shape_svg_rejects_active_content(payload: bytes) -> None:
    with pytest.raises(AssetSafetyError) as caught:
        sanitize_shape_svg(payload)
    assert caught.value.code in {"SHAPE_SVG_ACTIVE_CONTENT", "SHAPE_SVG_INVALID"}


def test_visual_only_shape_pack_installs_sanitized_svg_deterministically(tmp_path: Path) -> None:
    source_root = tmp_path / "source-pack"
    source_root.mkdir()
    (source_root / "star.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
        '<polygon points="10,0 20,20 0,20" fill="#facc15"/></svg>',
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "id": "basic-shapes",
        "name": "Basic Shapes",
        "version": "1.0.0",
        "shapes": [{"id": "star", "name": "Star", "svg": "star.svg"}],
    }
    manifest_path = source_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    project_root = tmp_path / "project"

    first = install_shape_pack(project_root, manifest_path)
    second = install_shape_pack(project_root, manifest_path)
    assert first == second
    assert first.reference.manifest_path.startswith("assets/shape-packs/")
    installed_svg = project_root / Path(first.shapes[0].relative_path)
    assert installed_svg.is_file()
    assert b"script" not in installed_svg.read_bytes().lower()

    session = ProjectSession.new()
    try:
        assert isinstance(
            session.client.register_shape_pack(first.reference),
            CommandAccepted,
        )
    finally:
        session.close()


def test_shape_pack_rejects_traversal_and_semantic_extensions(tmp_path: Path) -> None:
    outside = tmp_path / "outside.svg"
    outside.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><path d="M0 0"/></svg>',
        encoding="utf-8",
    )
    pack = tmp_path / "pack"
    pack.mkdir()
    manifest = {
        "schema_version": 1,
        "id": "unsafe",
        "name": "Unsafe",
        "version": "1",
        "python": "import os",
        "shapes": [{"id": "x", "name": "X", "svg": "../outside.svg"}],
    }
    path = pack / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssetSafetyError) as semantic:
        install_shape_pack(tmp_path / "project", path)
    assert semantic.value.code == "SHAPE_PACK_SEMANTICS_FORBIDDEN"
    manifest.pop("python")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssetSafetyError) as traversal:
        install_shape_pack(tmp_path / "project", path)
    assert traversal.value.code == "SHAPE_PACK_PATH_TRAVERSAL"


def test_layers_guides_grid_visibility_locking_and_atomic_removal() -> None:
    session = ProjectSession.new()
    try:
        session.client.create_diagram(DocumentKind.FREEFORM, "Layered")
        diagram = session.authority.snapshot().documents[-1]
        assert isinstance(diagram, FreeformDiagram)
        assert isinstance(
            session.client.add_freeform_layer(diagram.id, "Annotations", layer_id="layer_notes"),
            CommandAccepted,
        )
        session.client.create_freeform_shape(
            diagram.id,
            ShapeKind.TEXT,
            Rect(40, 40, 180, 60),
            text="Layer note",
            object_id="note",
            layer_id="layer_notes",
        )
        assert isinstance(
            session.client.add_freeform_guide(
                diagram.id,
                GuideOrientation.VERTICAL,
                120.0,
                guide_id="guide_v",
            ),
            CommandAccepted,
        )
        session.client.configure_freeform_canvas(diagram.id, 20.0, True)
        session.client.update_freeform_layer(
            diagram.id,
            "layer_notes",
            "Annotations",
            hidden=True,
            locked=True,
        )
        updated = session.authority.snapshot().documents[-1]
        assert isinstance(updated, FreeformDiagram)
        assert updated.grid_size == 20.0
        assert updated.snap_to_grid
        assert not any(node.object_id == "note" for node in layout_freeform(updated).nodes)
        rejected = session.client.transform_freeform_object(
            diagram.id,
            "note",
            Rect(80, 80, 180, 60),
        )
        assert isinstance(rejected, CommandRejected)
        assert rejected.code == "FREEFORM_LAYER_LOCKED"
        session.client.update_freeform_layer(
            diagram.id,
            "layer_notes",
            "Annotations",
            hidden=False,
            locked=False,
        )
        removed = session.client.remove_freeform_layer(diagram.id, "layer_notes")
        assert isinstance(removed, CommandAccepted)
        final = session.authority.snapshot().documents[-1]
        assert isinstance(final, FreeformDiagram)
        note = next(item for item in final.objects if isinstance(item, ShapeObject))
        assert note.layer_id == "layer_default"
        assert {guide.id for guide in final.guides} == {"guide_v"}
        assert isinstance(session.client.undo(), CommandAccepted)
    finally:
        session.close()
