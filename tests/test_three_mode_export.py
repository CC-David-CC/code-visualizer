from io import BytesIO

from PIL import Image

from code_visualizer.domain.drakon import Action, Sequence, create_empty_drakon
from code_visualizer.domain.freeform import FreeformDiagram, Rect, ShapeKind, ShapeObject
from code_visualizer.domain.mindmap import MindMapDiagram, Topic
from code_visualizer.rendering import (
    ExportFormat,
    ExportOptions,
    document_to_pdf,
    document_to_png,
    document_to_svg,
    export_document,
)


def _documents():
    drakon = create_empty_drakon(title="Incomplete algorithm")
    drakon = type(drakon)(
        drakon.id,
        drakon.title,
        drakon.header,
        Sequence(drakon.body.id, (Action("broken_action", "broken("),)),
        drakon.end,
    )
    mindmap = MindMapDiagram(
        "mind_export",
        "Export map",
        Topic("root_export", "Root", (Topic("child_export", "Child"),)),
    )
    freeform = FreeformDiagram(
        "free_export",
        "Export canvas",
        (
            ShapeObject(
                "export_shape",
                ShapeKind.ROUNDED_RECTANGLE,
                Rect(20.0, 30.0, 240.0, 90.0),
                "Safe vector export",
            ),
        ),
    )
    return drakon, mindmap, freeform


def test_all_modes_export_deterministic_svg_png_and_pdf_without_a_viewport() -> None:
    for document in _documents():
        svg = document_to_svg(document)
        assert svg == document_to_svg(document)
        assert svg.startswith("<svg")
        assert document.title in svg

        options = ExportOptions(scale=1.25, dpi=144, transparent=True)
        png = document_to_png(document, options=options)
        assert png == document_to_png(document, options=options)
        image = Image.open(BytesIO(png))
        assert image.width > 10
        assert image.height > 10
        assert image.mode == "RGBA"

        pdf = document_to_pdf(document)
        assert pdf == document_to_pdf(document)
        assert pdf.startswith(b"%PDF-1.4")
        assert pdf.endswith(b"%%EOF\n")


def test_export_document_atomically_writes_each_supported_format(tmp_path) -> None:
    document = _documents()[1]
    for format in ExportFormat:
        path = tmp_path / f"mind-map.{format.value}"
        result = export_document(document, path, format=format)
        assert result.path == path.resolve()
        assert result.width > 0 and result.height > 0
        assert len(result.sha256) == 64
        assert path.stat().st_size > 100
        assert not tuple(tmp_path.glob("*.tmp"))
