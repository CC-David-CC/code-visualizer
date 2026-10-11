"""Source extents for UI selection, separate from generated provenance."""

from dataclasses import dataclass

from code_visualizer.domain.projection import DrakonViewDefinition
from code_visualizer.generation.emitter import GeneratedProject, SourceSpan


@dataclass(frozen=True, slots=True)
class SourceSelectionRange:
    file_path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int


def source_selection_range(
    generated: GeneratedProject, view: DrakonViewDefinition, owned_ids: tuple[str, ...]
) -> SourceSpan | SourceSelectionRange | None:
    """Enclose owned provenance within one bound presentation and generated file."""
    semantic_ids = {
        view.function_id if identity == view.header_id else identity for identity in owned_ids
    }
    for module in generated.files:
        spans = tuple(
            span
            for span in module.spans
            if span.presentation_id == view.document_id and span.semantic_id in semantic_ids
        )
        if not spans:
            continue
        if len(spans) == 1:
            return spans[0]
        start = min((span.start_line, span.start_column) for span in spans)
        end = max((span.end_line, span.end_column) for span in spans)
        return SourceSelectionRange(module.path, *start, *end)
    return None
