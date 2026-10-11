"""Injected text measurement with a deterministic headless implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TextSize:
    width: float
    height: float


class TextMeasurer(Protocol):
    @property
    def line_height(self) -> float: ...

    def measure_line(self, text: str, *, role: str = "code") -> TextSize: ...


@dataclass(frozen=True, slots=True)
class DeterministicTextMeasurer:
    character_width: float = 8.0
    line_height: float = 20.0

    def measure_line(self, text: str, *, role: str = "code") -> TextSize:
        factor = 1.08 if role in {"title", "branch"} else 1.0
        return TextSize(len(text.expandtabs(4)) * self.character_width * factor, self.line_height)


def wrap_text(text: str, measurer: TextMeasurer, max_width: float) -> tuple[str, ...]:
    """Wrap predictably, including long code tokens that contain no spaces."""

    if max_width <= 0:
        raise ValueError("max_width must be positive")
    result: list[str] = []
    source_lines = text.splitlines() or [""]
    for source in source_lines:
        if not source:
            result.append("")
            continue
        current = ""
        for word in source.split(" "):
            candidate = word if not current else f"{current} {word}"
            if measurer.measure_line(candidate).width <= max_width:
                current = candidate
                continue
            if current:
                result.append(current)
                current = ""
            chunk = ""
            for character in word:
                proposed = chunk + character
                if chunk and measurer.measure_line(proposed).width > max_width:
                    result.append(chunk)
                    chunk = character
                else:
                    chunk = proposed
            current = chunk
        result.append(current)
    return tuple(result)
