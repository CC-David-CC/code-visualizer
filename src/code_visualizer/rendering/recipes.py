"""Adaptive vector recipes for the complete atomic DRAKON alphabet."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from code_visualizer.rendering.geometry import Point, Rect, Segment
from code_visualizer.rendering.text import TextMeasurer, wrap_text

U = 16.0
MIN_BODY_WIDTH = 10 * U
MAX_TEXT_WIDTH = 30 * U
HORIZONTAL_AIR = U
VERTICAL_AIR = U / 2
STROKE_WIDTH = 2.0


class RecipeKind(StrEnum):
    FUNCTION_HEADER = "function_header"
    END = "end"
    ACTION = "action"
    IF = "if_question"
    SELECT = "select"
    CASE = "case"
    BRANCH_HEADER = "branch_header"
    ADDRESS = "address"
    CALL = "call"
    ASSIGNMENT = "assignment_shelf"
    SIGNATURE_PANEL = "signature_panel"
    FOR_START = "for_start"
    FOR_END = "for_end"
    OUTPUT = "output"
    INPUT = "input"
    DELAY = "delay"
    PERIOD = "period"
    START_TIMER = "start_timer"
    SYNCHRONIZER = "synchronizer"
    REALTIME_PROCESS = "realtime_process"
    NOTE_RICH = "note_rich"
    NOTE_RIGHT = "note_right"
    NOTE_LEFT = "note_left"
    LOOP_RETURN = "loop_return"
    SILHOUETTE_TRANSITION = "silhouette_transition"
    CONNECTOR_MARKER = "connector_marker"
    CONCURRENT_BOUNDARY = "concurrent_process_boundary"


@dataclass(frozen=True, slots=True)
class Port:
    name: str
    point: Point
    valence: str
    truth: bool | None = None


@dataclass(frozen=True, slots=True)
class TextBlock:
    role: str
    text: str
    lines: tuple[str, ...]
    safe_bounds: Rect


@dataclass(frozen=True, slots=True)
class SolvedShape:
    recipe_id: str
    recipe_version: int
    kind: RecipeKind
    bounds: Rect
    outline: tuple[Point, ...]
    dividers: tuple[Segment, ...]
    text_blocks: tuple[TextBlock, ...]
    ports: tuple[Port, ...]
    anchor_x: float
    hit_bounds: Rect
    accessibility_role: str
    accessibility_name: str
    corner_radius: float = 0.0

    def port(self, name: str) -> Point:
        for port in self.ports:
            if port.name == name:
                return port.point
        raise KeyError(name)


def _needed_text_width(text: str, measurer: TextMeasurer, *, role: str = "code") -> float:
    return max(
        (measurer.measure_line(line, role=role).width for line in text.splitlines()), default=0
    )


def required_body_width(
    kind: RecipeKind,
    texts: dict[str, str],
    measurer: TextMeasurer,
) -> float:
    role = "title" if kind is RecipeKind.FUNCTION_HEADER else "code"
    if kind is RecipeKind.PERIOD:
        timer_width = _needed_text_width(texts.get("timer", "timer"), measurer, role=role)
        seconds_width = _needed_text_width(texts.get("seconds", "period"), measurer, role=role)
        return max(
            MIN_BODY_WIDTH,
            min(MAX_TEXT_WIDTH, timer_width + seconds_width + HORIZONTAL_AIR * 4),
        )
    needed = max(
        (_needed_text_width(value, measurer, role=role) for value in texts.values()), default=0
    )
    return max(MIN_BODY_WIDTH, min(MAX_TEXT_WIDTH, needed) + HORIZONTAL_AIR * 2)


def _block(
    role: str,
    text: str,
    safe: Rect,
    measurer: TextMeasurer,
) -> TextBlock:
    return TextBlock(role, text, wrap_text(text, measurer, safe.width), safe)


def solve_recipe(
    kind: RecipeKind,
    texts: dict[str, str],
    measurer: TextMeasurer,
    *,
    shared_body_width: float | None = None,
) -> SolvedShape:
    body_width = max(
        required_body_width(kind, texts, measurer),
        shared_body_width or MIN_BODY_WIDTH,
    )
    primary = next(iter(texts.values()), kind.value)
    lines = wrap_text(primary, measurer, body_width - HORIZONTAL_AIR * 2)
    text_height = max(measurer.line_height, len(lines) * measurer.line_height)
    height = max(3 * U, text_height + VERTICAL_AIR * 2)
    dividers: tuple[Segment, ...] = ()
    outline: tuple[Point, ...]
    blocks: tuple[TextBlock, ...]

    if kind in {RecipeKind.ASSIGNMENT, RecipeKind.SIGNATURE_PANEL}:
        upper = texts.get("target", "result")
        lower = texts.get("value", "None")
        upper_lines = wrap_text(upper, measurer, body_width - HORIZONTAL_AIR * 2)
        lower_lines = wrap_text(lower, measurer, body_width - HORIZONTAL_AIR * 2)
        upper_height = len(upper_lines) * measurer.line_height + VERTICAL_AIR * 2
        lower_height = len(lower_lines) * measurer.line_height + VERTICAL_AIR * 2
        height = max(4 * U, upper_height + lower_height)
        divider_y = upper_height
        dividers = (Segment(Point(0, divider_y), Point(body_width, divider_y)),)
        blocks = (
            TextBlock(
                "target",
                upper,
                upper_lines,
                Rect(
                    HORIZONTAL_AIR,
                    VERTICAL_AIR,
                    body_width - 2 * HORIZONTAL_AIR,
                    upper_height - 2 * VERTICAL_AIR,
                ),
            ),
            TextBlock(
                "value",
                lower,
                lower_lines,
                Rect(
                    HORIZONTAL_AIR,
                    divider_y + VERTICAL_AIR,
                    body_width - 2 * HORIZONTAL_AIR,
                    lower_height - 2 * VERTICAL_AIR,
                ),
            ),
        )
        width = body_width
        outline = (
            Point(0, 0),
            Point(width, 0),
            Point(width, height),
            Point(0, height),
        )
    elif kind in {RecipeKind.OUTPUT, RecipeKind.SILHOUETTE_TRANSITION}:
        arrow_width = 2.5 * U
        width = body_width + arrow_width
        divider_x = body_width
        outline = (
            Point(0, 0),
            Point(divider_x, 0),
            Point(width, height / 2),
            Point(divider_x, height),
            Point(0, height),
        )
        dividers = (Segment(Point(divider_x, 0), Point(divider_x, height)),)
        safe = Rect(
            HORIZONTAL_AIR,
            VERTICAL_AIR,
            body_width - 2 * HORIZONTAL_AIR,
            height - 2 * VERTICAL_AIR,
        )
        blocks = (_block("expression", primary, safe, measurer),)
    elif kind in {RecipeKind.IF, RecipeKind.SELECT, RecipeKind.SYNCHRONIZER}:
        question_width = 2.5 * U
        width = body_width + question_width
        outline = (
            Point(0, 0),
            Point(body_width, 0),
            Point(width, height / 2),
            Point(body_width, height),
            Point(0, height),
        )
        dividers = (Segment(Point(body_width, 0), Point(body_width, height)),)
        safe = Rect(
            HORIZONTAL_AIR,
            VERTICAL_AIR,
            body_width - 2 * HORIZONTAL_AIR,
            height - 2 * VERTICAL_AIR,
        )
        blocks = (_block("condition", primary, safe, measurer),)
    elif kind is RecipeKind.INPUT:
        arrow_width = 2.5 * U
        width = body_width + arrow_width
        outline = (
            Point(arrow_width, 0),
            Point(width, 0),
            Point(width, height),
            Point(arrow_width, height),
            Point(0, height / 2),
        )
        dividers = (Segment(Point(arrow_width, 0), Point(arrow_width, height)),)
        safe = Rect(
            arrow_width + HORIZONTAL_AIR,
            VERTICAL_AIR,
            body_width - 2 * HORIZONTAL_AIR,
            height - 2 * VERTICAL_AIR,
        )
        blocks = (_block("input", primary, safe, measurer),)
    elif kind is RecipeKind.CALL:
        width = body_width
        inset = U
        outline = (Point(0, 0), Point(width, 0), Point(width, height), Point(0, height))
        dividers = (
            Segment(Point(inset, 0), Point(inset, height)),
            Segment(Point(width - inset, 0), Point(width - inset, height)),
        )
        safe = Rect(
            inset + HORIZONTAL_AIR,
            VERTICAL_AIR,
            width - 2 * (inset + HORIZONTAL_AIR),
            height - 2 * VERTICAL_AIR,
        )
        blocks = (_block("call", primary, safe, measurer),)
    elif kind is RecipeKind.PERIOD:
        width = body_width
        bevel = U
        timer = texts.get("timer", "timer")
        seconds = texts.get("seconds", "period")
        half = width / 2
        compartment_width = half - bevel - HORIZONTAL_AIR * 2
        timer_lines = wrap_text(timer, measurer, compartment_width)
        seconds_lines = wrap_text(seconds, measurer, compartment_width)
        height = max(
            3 * U,
            max(len(timer_lines), len(seconds_lines)) * measurer.line_height + VERTICAL_AIR * 2,
        )
        outline = (
            Point(bevel, 0),
            Point(width - bevel, 0),
            Point(width, height / 2),
            Point(width - bevel, height),
            Point(bevel, height),
            Point(0, height / 2),
        )
        dividers = (Segment(Point(half, 0), Point(half, height)),)
        blocks = (
            TextBlock(
                "timer",
                timer,
                timer_lines,
                Rect(
                    bevel + HORIZONTAL_AIR,
                    VERTICAL_AIR,
                    compartment_width,
                    height - 2 * VERTICAL_AIR,
                ),
            ),
            TextBlock(
                "seconds",
                seconds,
                seconds_lines,
                Rect(
                    half + HORIZONTAL_AIR,
                    VERTICAL_AIR,
                    compartment_width,
                    height - 2 * VERTICAL_AIR,
                ),
            ),
        )
    elif kind is RecipeKind.DELAY:
        width = body_width
        bevel = U
        outline = (
            Point(bevel, 0),
            Point(width - bevel, 0),
            Point(width, height / 2),
            Point(width - bevel, height),
            Point(bevel, height),
            Point(0, height / 2),
        )
        safe = Rect(
            bevel + HORIZONTAL_AIR,
            VERTICAL_AIR,
            width - 2 * (bevel + HORIZONTAL_AIR),
            height - 2 * VERTICAL_AIR,
        )
        blocks = (_block("timing", primary, safe, measurer),)
    elif kind is RecipeKind.START_TIMER:
        width = max(body_width, height)
        cut = min(U, height / 4)
        outline = (
            Point(cut, 0),
            Point(width - cut, 0),
            Point(width, cut),
            Point(width, height - cut),
            Point(width - cut, height),
            Point(cut, height),
            Point(0, height - cut),
            Point(0, cut),
        )
        safe = Rect(
            HORIZONTAL_AIR,
            VERTICAL_AIR,
            width - 2 * HORIZONTAL_AIR,
            height - 2 * VERTICAL_AIR,
        )
        blocks = (_block("timer", primary, safe, measurer),)
    elif kind in {RecipeKind.NOTE_RICH, RecipeKind.NOTE_LEFT, RecipeKind.NOTE_RIGHT}:
        width = body_width
        fold = 1.5 * U
        if kind is RecipeKind.NOTE_LEFT:
            outline = (
                Point(fold, 0),
                Point(width, 0),
                Point(width, height),
                Point(0, height),
                Point(0, fold),
            )
            dividers = (
                Segment(Point(0, fold), Point(fold, fold)),
                Segment(Point(fold, 0), Point(fold, fold)),
            )
            safe = Rect(
                fold + HORIZONTAL_AIR,
                VERTICAL_AIR,
                width - fold - 2 * HORIZONTAL_AIR,
                height - 2 * VERTICAL_AIR,
            )
        else:
            outline = (
                Point(0, 0),
                Point(width - fold, 0),
                Point(width, fold),
                Point(width, height),
                Point(0, height),
            )
            dividers = (Segment(Point(width - fold, 0), Point(width - fold, fold)),)
            if kind is RecipeKind.NOTE_RICH:
                dividers += (Segment(Point(0, height - U / 2), Point(width, height - U / 2)),)
            safe = Rect(
                HORIZONTAL_AIR,
                VERTICAL_AIR,
                width - fold - 2 * HORIZONTAL_AIR,
                height - 2 * VERTICAL_AIR,
            )
        blocks = (_block("note", primary, safe, measurer),)
    elif kind in {RecipeKind.REALTIME_PROCESS, RecipeKind.CONCURRENT_BOUNDARY}:
        width = body_width
        inset = U / 2
        if kind is RecipeKind.CONCURRENT_BOUNDARY:
            height = max(height, measurer.line_height + 2 * (inset + VERTICAL_AIR))
        outline = (Point(0, 0), Point(width, 0), Point(width, height), Point(0, height))
        if kind is RecipeKind.REALTIME_PROCESS:
            dividers = (
                Segment(Point(inset, 0), Point(inset, height)),
                Segment(Point(width - inset, 0), Point(width - inset, height)),
            )
            safe = Rect(
                inset + HORIZONTAL_AIR,
                VERTICAL_AIR,
                width - 2 * (inset + HORIZONTAL_AIR),
                height - 2 * VERTICAL_AIR,
            )
        else:
            dividers = (
                Segment(Point(0, inset), Point(width, inset)),
                Segment(Point(0, height - inset), Point(width, height - inset)),
            )
            safe = Rect(
                HORIZONTAL_AIR,
                inset + VERTICAL_AIR,
                width - 2 * HORIZONTAL_AIR,
                height - 2 * (inset + VERTICAL_AIR),
            )
        blocks = (_block("process", primary, safe, measurer),)
    elif kind is RecipeKind.CONNECTOR_MARKER:
        width = max(3 * U, min(body_width, 6 * U))
        height = max(height, 3 * U)
        outline = (
            Point(width / 2, 0),
            Point(width, height / 2),
            Point(width / 2, height),
            Point(0, height / 2),
        )
        safe = Rect(U, VERTICAL_AIR, width - 2 * U, height - 2 * VERTICAL_AIR)
        blocks = (_block("marker", primary, safe, measurer),)
    elif kind in {RecipeKind.FOR_START, RecipeKind.FOR_END, RecipeKind.LOOP_RETURN}:
        width = body_width
        notch = 1.5 * U
        if kind is RecipeKind.FOR_END:
            outline = (
                Point(0, 0),
                Point(width, 0),
                Point(width - notch, height),
                Point(notch, height),
            )
        elif kind is RecipeKind.LOOP_RETURN:
            outline = (
                Point(notch, 0),
                Point(width, 0),
                Point(width, height),
                Point(notch, height),
                Point(0, height / 2),
            )
        else:
            outline = (
                Point(notch, 0),
                Point(width - notch, 0),
                Point(width, height),
                Point(0, height),
            )
        safe = Rect(
            notch + HORIZONTAL_AIR / 2,
            VERTICAL_AIR,
            width - 2 * notch - HORIZONTAL_AIR,
            height - 2 * VERTICAL_AIR,
        )
        blocks = (_block("loop", primary, safe, measurer),)
    else:
        width = body_width
        outline = (
            Point(0, 0),
            Point(width, 0),
            Point(width, height),
            Point(0, height),
        )
        role = "title" if kind in {RecipeKind.FUNCTION_HEADER, RecipeKind.BRANCH_HEADER} else "text"
        safe = Rect(
            HORIZONTAL_AIR,
            VERTICAL_AIR,
            width - 2 * HORIZONTAL_AIR,
            height - 2 * VERTICAL_AIR,
        )
        blocks = (_block(role, primary, safe, measurer),)

    anchor_x = width / 2 if kind is RecipeKind.CONNECTOR_MARKER else body_width / 2
    ports = [
        Port("input", Point(anchor_x, 0), "sequence"),
        Port("output", Point(anchor_x, height), "sequence"),
    ]
    if kind in {RecipeKind.IF, RecipeKind.SELECT, RecipeKind.SYNCHRONIZER}:
        ports = [
            Port("input", Point(anchor_x, 0), "sequence"),
            Port("down", Point(anchor_x, height), "sequence"),
            Port("right", Point(width, height / 2), "sequence"),
        ]
    elif kind is RecipeKind.FUNCTION_HEADER:
        ports = [Port("output", Point(anchor_x, height), "sequence")]
    elif kind is RecipeKind.END:
        ports = [Port("input", Point(anchor_x, 0), "sequence")]

    bounds = Rect(0, 0, width, height)
    display_name = {
        RecipeKind.FUNCTION_HEADER: "Function Header",
        RecipeKind.END: "End",
        RecipeKind.ACTION: "Action",
        RecipeKind.IF: "If Question",
        RecipeKind.SELECT: "Select",
        RecipeKind.CASE: "Case",
        RecipeKind.BRANCH_HEADER: "Branch Header",
        RecipeKind.ADDRESS: "Address",
        RecipeKind.CALL: "Call",
        RecipeKind.ASSIGNMENT: "Assignment Shelf",
        RecipeKind.SIGNATURE_PANEL: "Signature Panel",
        RecipeKind.FOR_START: "For Start",
        RecipeKind.FOR_END: "For End",
        RecipeKind.OUTPUT: "Output",
        RecipeKind.INPUT: "Input",
        RecipeKind.DELAY: "Delay",
        RecipeKind.PERIOD: "Period",
        RecipeKind.START_TIMER: "Start Timer",
        RecipeKind.SYNCHRONIZER: "Synchronizer",
        RecipeKind.REALTIME_PROCESS: "Realtime Parallel Process",
        RecipeKind.NOTE_RICH: "Rich Note",
        RecipeKind.NOTE_RIGHT: "Right Note",
        RecipeKind.NOTE_LEFT: "Left Note",
        RecipeKind.LOOP_RETURN: "Loop Return Arrow",
        RecipeKind.SILHOUETTE_TRANSITION: "Silhouette Transition",
        RecipeKind.CONNECTOR_MARKER: "Connector Marker",
        RecipeKind.CONCURRENT_BOUNDARY: "Concurrent Process Boundary",
    }[kind]
    return SolvedShape(
        recipe_id=f"drakon.{kind.value}",
        recipe_version=1,
        kind=kind,
        bounds=bounds,
        outline=outline,
        dividers=dividers,
        text_blocks=blocks,
        ports=tuple(ports),
        anchor_x=anchor_x,
        hit_bounds=bounds.expanded(U / 2),
        accessibility_role="diagram operation",
        accessibility_name=f"{display_name}: {primary}",
        corner_radius=(
            height / 2
            if kind is RecipeKind.END
            else U
            if kind
            in {
                RecipeKind.FUNCTION_HEADER,
                RecipeKind.BRANCH_HEADER,
                RecipeKind.ADDRESS,
            }
            else 0.0
        ),
    )
