import hashlib
import json
from pathlib import Path

from PIL import Image
from PySide6.QtSvg import QSvgRenderer

from code_visualizer.domain.drakon_defaults import MACROICON_INVENTORY
from code_visualizer.rendering.contact_sheet import (
    CONTACT_SHEET_HEIGHT,
    CONTACT_SHEET_WIDTH,
    initial_contact_sheet_svg,
    initial_if_layout_svg,
)
from code_visualizer.rendering.recipes import RecipeKind
from code_visualizer.ui_qt.font_support import register_application_fonts

ROOT = Path(__file__).resolve().parents[1]


def test_initial_contact_sheet_is_current_valid_and_multi_dpi(qapp) -> None:
    del qapp
    golden_root = ROOT / "assets" / "goldens"
    svg_path = golden_root / "initial-icon-contact-sheet.svg"

    assert svg_path.read_text(encoding="utf-8") == initial_contact_sheet_svg()
    assert QSvgRenderer(str(svg_path)).isValid()
    if_svg = golden_root / "initial-if-layout.svg"
    assert if_svg.read_text(encoding="utf-8") == initial_if_layout_svg()
    assert QSvgRenderer(str(if_svg)).isValid()
    with Image.open(golden_root / "initial-icon-contact-sheet.png") as image:
        assert image.size == (round(CONTACT_SHEET_WIDTH), round(CONTACT_SHEET_HEIGHT))
    with Image.open(golden_root / "initial-icon-contact-sheet@2x.png") as image:
        assert image.size == (
            round(CONTACT_SHEET_WIDTH * 2),
            round(CONTACT_SHEET_HEIGHT * 2),
        )


def test_bundled_fonts_register_and_match_audited_hashes(qapp) -> None:
    del qapp
    fonts = register_application_fonts()
    assert fonts.interface == "DejaVu Sans"
    assert fonts.code == "DejaVu Sans Mono"
    expected = {
        "DejaVuSans.ttf": "7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954",
        "DejaVuSansMono.ttf": "b4a6c3e4faab8773f4ff761d56451646409f29abedd68f05d38c2df667d3c582",
    }
    for filename, digest in expected.items():
        payload = (ROOT / "src" / "code_visualizer" / "resources" / "fonts" / filename).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == digest


def test_icon_manifest_matches_the_complete_m5_inventory() -> None:
    manifest_path = ROOT / "src" / "code_visualizer" / "resources" / "icon_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert {item["id"] for item in manifest["recipes"]} == {
        f"drakon.{kind.value}" for kind in RecipeKind
    }
    assert len(manifest["recipes"]) == 27
    assert len(manifest["macroicons"]) == 21
    assert {item["id"] for item in manifest["macroicons"]} == {
        item.id for item in MACROICON_INVENTORY
    }
    assert {item["id"] for item in manifest["macroicons"]} >= {
        "binary_if",
        "tree_loop",
        "timed_parallel",
    }
    assert all(item["status"] == "implemented_m5" for item in manifest["recipes"])
