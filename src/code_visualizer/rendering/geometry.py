"""Small immutable geometry vocabulary shared by layout and render adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

    def translated(self, dx: float, dy: float) -> Point:
        return Point(self.x + dx, self.y + dy)


@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def top(self) -> float:
        return self.y

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    def translated(self, dx: float, dy: float) -> Rect:
        return Rect(self.x + dx, self.y + dy, self.width, self.height)

    def expanded(self, amount: float) -> Rect:
        return Rect(
            self.x - amount,
            self.y - amount,
            self.width + amount * 2,
            self.height + amount * 2,
        )

    def union(self, other: Rect) -> Rect:
        left = min(self.left, other.left)
        top = min(self.top, other.top)
        right = max(self.right, other.right)
        bottom = max(self.bottom, other.bottom)
        return Rect(left, top, right - left, bottom - top)

    def intersects(self, other: Rect) -> bool:
        return not (
            self.right <= other.left
            or other.right <= self.left
            or self.bottom <= other.top
            or other.bottom <= self.top
        )

    def contains(self, point: Point) -> bool:
        return self.left <= point.x <= self.right and self.top <= point.y <= self.bottom


@dataclass(frozen=True, slots=True)
class Segment:
    start: Point
    end: Point

    def __post_init__(self) -> None:
        if self.start.x != self.end.x and self.start.y != self.end.y:
            raise ValueError("DRAKON route segments must be orthogonal")

    @property
    def is_horizontal(self) -> bool:
        return self.start.y == self.end.y

    @property
    def length(self) -> float:
        return abs(self.end.x - self.start.x) + abs(self.end.y - self.start.y)

    def bounds(self, stroke_width: float = 0.0) -> Rect:
        half = stroke_width / 2
        left = min(self.start.x, self.end.x) - half
        top = min(self.start.y, self.end.y) - half
        width = abs(self.end.x - self.start.x) + stroke_width
        height = abs(self.end.y - self.start.y) + stroke_width
        return Rect(left, top, width, height)


def union_rects(rects: tuple[Rect, ...]) -> Rect:
    if not rects:
        return Rect(0, 0, 0, 0)
    result = rects[0]
    for rect in rects[1:]:
        result = result.union(rect)
    return result
