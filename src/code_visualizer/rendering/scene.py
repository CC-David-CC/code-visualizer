"""Qt-independent DRAKON scene layout with semantic route metadata."""

from __future__ import annotations

from dataclasses import dataclass, replace

from code_visualizer.domain.drakon import (
    Action,
    Assignment,
    Call,
    Delay,
    DrakonAtom,
    DrakonDiagram,
    If,
    Input,
    Loop,
    Note,
    Output,
    Parallel,
    Period,
    RealtimeProcess,
    Select,
    Sequence,
    Silhouette,
    SimpleStatement,
    StartTimer,
    Synchronizer,
    Transfer,
    Try,
    With,
    nested_sequences,
)
from code_visualizer.domain.program_kinds import NotePlacement, TransferKind
from code_visualizer.rendering.geometry import Point, Rect, Segment, union_rects
from code_visualizer.rendering.recipes import (
    STROKE_WIDTH,
    Port,
    RecipeKind,
    SolvedShape,
    U,
    required_body_width,
    solve_recipe,
)
from code_visualizer.rendering.text import DeterministicTextMeasurer, TextMeasurer


@dataclass(frozen=True, slots=True)
class LayoutMetrics:
    unit: float = U
    metre: float = 2 * U
    rhythm: float = 6 * U
    silhouette_pitch: float = 9 * U
    connector_clearance: float = U
    touch_target: float = 2.75 * U
    margin: float = 2 * U


@dataclass(frozen=True, slots=True)
class SequenceBoundary:
    sequence_id: str
    index: int


@dataclass(frozen=True, slots=True)
class SceneNode:
    object_id: str
    shape: SolvedShape
    origin: Point

    @property
    def bounds(self) -> Rect:
        return self.shape.bounds.translated(self.origin.x, self.origin.y)

    def port(self, name: str) -> Point:
        local = self.shape.port(name)
        return local.translated(self.origin.x, self.origin.y)


@dataclass(frozen=True, slots=True)
class SceneRoute:
    id: str
    segment: Segment
    boundary: SequenceBoundary | None
    legal_insertion: bool
    tooltip: str
    arrow_at_end: bool = False

    def hit_bounds(self, metrics: LayoutMetrics) -> Rect:
        return self.segment.bounds(metrics.touch_target)


@dataclass(frozen=True, slots=True)
class SceneLabel:
    text: str
    bounds: Rect
    semantic_id: str


@dataclass(frozen=True, slots=True)
class DiagramScene:
    diagram_id: str
    nodes: tuple[SceneNode, ...]
    routes: tuple[SceneRoute, ...]
    labels: tuple[SceneLabel, ...]
    bounds: Rect
    skewer_x: float
    metrics: LayoutMetrics

    def insertion_routes(self) -> tuple[SceneRoute, ...]:
        return tuple(route for route in self.routes if route.legal_insertion)


def _atom_kind_text(atom: DrakonAtom) -> tuple[RecipeKind, dict[str, str]]:
    if isinstance(atom, Action):
        return RecipeKind.ACTION, {"source": atom.source}
    if isinstance(atom, Output):
        return RecipeKind.OUTPUT, {"expression": atom.expression}
    if isinstance(atom, Assignment):
        target = atom.target
        if atom.annotation:
            target += f": {atom.annotation}"
        if atom.operator != "=":
            target += f" {atom.operator}"
        return RecipeKind.ASSIGNMENT, {"target": target, "value": atom.value}
    if isinstance(atom, If):
        return RecipeKind.IF, {"condition": atom.condition}
    if isinstance(atom, Transfer):
        keyword = atom.transfer_kind.value.replace("_", " ")
        text = keyword if not atom.expression else f"{keyword} {atom.expression}"
        kind = (
            RecipeKind.LOOP_RETURN
            if atom.transfer_kind in {TransferKind.BREAK, TransferKind.CONTINUE}
            else RecipeKind.SILHOUETTE_TRANSITION
        )
        return kind, {"transfer": text}
    if isinstance(atom, SimpleStatement):
        return RecipeKind.ACTION, {"source": f"{atom.statement_kind.value} {atom.source}".strip()}
    if isinstance(atom, Call):
        prefix = "await " if atom.awaited else ""
        result = f"{atom.result_target} = " if atom.result_target else ""
        return RecipeKind.CALL, {"call": f"{result}{prefix}{atom.expression}"}
    if isinstance(atom, Input):
        return RecipeKind.INPUT, {"input": f"{atom.target} ← input({atom.prompt})"}
    if isinstance(atom, Delay):
        prefix = "async " if atom.asynchronous else ""
        return RecipeKind.DELAY, {"delay": f"{prefix}delay {atom.seconds} s"}
    if isinstance(atom, StartTimer):
        return RecipeKind.START_TIMER, {"timer": f"start timer · {atom.timer}"}
    if isinstance(atom, Period):
        return RecipeKind.PERIOD, {
            "timer": f"{'async ' if atom.asynchronous else ''}{atom.timer}",
            "seconds": f"{atom.seconds} s",
        }
    if isinstance(atom, RealtimeProcess):
        prefix = "await " if atom.awaited else ""
        return RecipeKind.REALTIME_PROCESS, {"process": f"{prefix}{atom.call}"}
    if isinstance(atom, Note):
        kinds = {
            NotePlacement.RICH: RecipeKind.NOTE_RICH,
            NotePlacement.LEFT: RecipeKind.NOTE_LEFT,
            NotePlacement.RIGHT: RecipeKind.NOTE_RIGHT,
        }
        return kinds[atom.placement], {"note": atom.text}
    if isinstance(atom, Select):
        subject = f"match {atom.expression}" if atom.mode.value == "match" else "ordered select"
        return RecipeKind.SELECT, {"select": subject}
    if isinstance(atom, Loop):
        detail = {
            "for": f"for {atom.target} in {atom.iterable}",
            "async_for": f"async for {atom.target} in {atom.iterable}",
            "while": f"while {atom.condition}",
            "do_first": f"do first · while {atom.condition}",
            "wait": f"wait until {atom.condition}",
            "tree_dfs": f"TREE DFS · {atom.target} in {atom.iterable}",
            "tree_bfs": f"TREE BFS · {atom.target} in {atom.iterable}",
        }[atom.loop_kind.value]
        return RecipeKind.FOR_START, {"loop": detail}
    if isinstance(atom, With):
        contexts = ", ".join(item.expression for item in atom.contexts)
        prefix = "async " if atom.asynchronous else ""
        return RecipeKind.CALL, {"with": f"{prefix}with {contexts}"}
    if isinstance(atom, Try):
        marker = "try · except*" if atom.except_star else "try · except"
        return RecipeKind.SELECT, {"try": marker}
    if isinstance(atom, Synchronizer):
        return RecipeKind.SYNCHRONIZER, {"sync": f"{atom.timer} ≤ {atom.deadline} s"}
    if isinstance(atom, Parallel):
        return RecipeKind.CONCURRENT_BOUNDARY, {
            "parallel": f"{atom.mode.value} parallel · {len(atom.branches)} processes"
        }
    if isinstance(atom, Silhouette):
        return RecipeKind.BRANCH_HEADER, {
            "silhouette": f"{atom.display_name} · {len(atom.branches)} states"
        }
    raise TypeError(type(atom).__name__)


def _walk_atoms(sequence: Sequence) -> tuple[DrakonAtom, ...]:
    result: list[DrakonAtom] = []
    for atom in sequence.atoms:
        result.append(atom)
        for nested in nested_sequences(atom):
            result.extend(_walk_atoms(nested))
    return tuple(result)


def _function_label(diagram: DrakonDiagram) -> str:
    function = diagram.header.function
    parameters = ", ".join(parameter.name for parameter in function.parameters)
    async_prefix = "async " if function.kind.value.startswith("async") else ""
    owner = f"{function.owning_class}." if function.owning_class else ""
    returns = f" → {function.return_annotation}" if function.return_annotation else ""
    return (
        f"{function.display_name} · {async_prefix}{owner}{function.identifier}"
        f"({parameters}){returns}"
    )


def _signature_text(diagram: DrakonDiagram) -> tuple[str, str] | None:
    function = diagram.header.function
    details: list[str] = []
    if function.owning_class:
        method = function.method_kind.value if function.method_kind else "method"
        details.append(f"{function.owning_class} · {method}")
    if function.decorators:
        details.append(" ".join(f"@{item}" for item in function.decorators))
    if function.return_annotation:
        details.append(f"returns {function.return_annotation}")
    if function.kind.value != "sync":
        details.append(function.kind.value.replace("_", " "))
    if not function.parameters and not details:
        return None
    parameters = ", ".join(
        parameter.name
        + (f": {parameter.annotation}" if parameter.annotation else "")
        + (f" = {parameter.default}" if parameter.default is not None else "")
        for parameter in function.parameters
    )
    return (parameters or "no parameters", " · ".join(details) or "callable signature")


class _SceneBuilder:
    def __init__(
        self,
        diagram: DrakonDiagram,
        measurer: TextMeasurer,
        metrics: LayoutMetrics,
    ) -> None:
        self.diagram = diagram
        self.measurer = measurer
        self.metrics = metrics
        atom_specs = [_atom_kind_text(atom) for atom in _walk_atoms(diagram.body)]
        widths = [required_body_width(kind, texts, measurer) for kind, texts in atom_specs]
        widths.extend(
            (
                required_body_width(
                    RecipeKind.FUNCTION_HEADER,
                    {"title": _function_label(diagram)},
                    measurer,
                ),
                required_body_width(RecipeKind.END, {"text": "End"}, measurer),
            )
        )
        self.shared_width = max(widths)
        self.shapes: dict[str, SolvedShape] = {}
        for atom in _walk_atoms(diagram.body):
            kind, texts = _atom_kind_text(atom)
            shape = solve_recipe(
                kind,
                texts,
                measurer,
                shared_body_width=self.shared_width,
            )
            if isinstance(atom, If):
                shape = replace(
                    shape,
                    ports=tuple(
                        Port(
                            port.name,
                            port.point,
                            port.valence,
                            (
                                atom.preferred_truth
                                if port.name == "down"
                                else not atom.preferred_truth
                                if port.name == "right"
                                else None
                            ),
                        )
                        for port in shape.ports
                    ),
                )
            self.shapes[atom.id] = shape
        self.header_shape = solve_recipe(
            RecipeKind.FUNCTION_HEADER,
            {"title": _function_label(diagram)},
            measurer,
            shared_body_width=self.shared_width,
        )
        self.end_shape = solve_recipe(
            RecipeKind.END,
            {"text": "End"},
            measurer,
            shared_body_width=self.shared_width,
        )
        signature = _signature_text(diagram)
        self.signature_shape = (
            solve_recipe(
                RecipeKind.SIGNATURE_PANEL,
                {"target": signature[0], "value": signature[1]},
                measurer,
                shared_body_width=self.shared_width,
            )
            if signature is not None
            else None
        )
        self.nodes: list[SceneNode] = []
        self.routes: list[SceneRoute] = []
        self.labels: list[SceneLabel] = []
        self._route_count = 0

    def _extent(self, sequence: Sequence) -> tuple[float, float]:
        left = self.shared_width / 2
        right = self.shared_width / 2
        for atom in sequence.atoms:
            shape = self.shapes[atom.id]
            atom_left = shape.anchor_x
            atom_right = shape.bounds.width - shape.anchor_x
            if isinstance(atom, If):
                preferred = atom.true_branch if atom.preferred_truth else atom.false_branch
                secondary = atom.false_branch if atom.preferred_truth else atom.true_branch
                pref_left, pref_right = self._extent(preferred)
                sec_left, sec_right = self._extent(secondary)
                occupied_right = max(atom_right, pref_right)
                offset = occupied_right + self.metrics.rhythm + sec_left
                atom_left = max(atom_left, pref_left)
                atom_right = max(occupied_right, offset + sec_right)
            elif nested_sequences(atom):
                offsets = self._composite_offsets(atom)
                for nested, offset in zip(nested_sequences(atom), offsets, strict=True):
                    nested_left, nested_right = self._extent(nested)
                    atom_left = max(atom_left, nested_left - offset)
                    atom_right = max(atom_right, offset + nested_right)
            left = max(left, atom_left)
            right = max(right, atom_right)
        return left, right

    def _secondary_offset(self, atom: If) -> float:
        preferred = atom.true_branch if atom.preferred_truth else atom.false_branch
        secondary = atom.false_branch if atom.preferred_truth else atom.true_branch
        _, preferred_right = self._extent(preferred)
        secondary_left, _ = self._extent(secondary)
        shape = self.shapes[atom.id]
        decision_right = shape.bounds.width - shape.anchor_x
        return max(decision_right, preferred_right) + self.metrics.rhythm + secondary_left

    def _composite_offsets(self, atom: DrakonAtom) -> tuple[float, ...]:
        sequences = nested_sequences(atom)
        if not sequences:
            return ()
        offsets = [0.0]
        occupied_right = max(
            self.shapes[atom.id].bounds.width - self.shapes[atom.id].anchor_x,
            self._extent(sequences[0])[1],
        )
        for sequence in sequences[1:]:
            sequence_left, sequence_right = self._extent(sequence)
            offset = occupied_right + self.metrics.rhythm + sequence_left
            offsets.append(offset)
            occupied_right = max(occupied_right, offset + sequence_right)
        return tuple(offsets)

    @staticmethod
    def _composite_labels(atom: DrakonAtom) -> tuple[str, ...]:
        if isinstance(atom, Select):
            return tuple(case.label for case in atom.cases)
        if isinstance(atom, Loop):
            return ("loop body", "loop else")
        if isinstance(atom, With):
            return ("context body",)
        if isinstance(atom, Try):
            return (
                "try",
                *(
                    f"except{'*' if atom.except_star else ''} {item.exception}"
                    for item in atom.handlers
                ),
                "else",
                "finally",
            )
        if isinstance(atom, Synchronizer):
            return ("on time", "timeout")
        if isinstance(atom, Parallel):
            return tuple(branch.name for branch in atom.branches)
        if isinstance(atom, Silhouette):
            return tuple(branch.name for branch in atom.branches)
        return tuple(f"route {index + 1}" for index, _ in enumerate(nested_sequences(atom)))

    def _node(self, object_id: str, shape: SolvedShape, x: float, top: float) -> SceneNode:
        node = SceneNode(object_id, shape, Point(x - shape.anchor_x, top))
        self.nodes.append(node)
        return node

    def _derived_shape(self, kind: RecipeKind, texts: dict[str, str]) -> SolvedShape:
        return solve_recipe(
            kind,
            texts,
            self.measurer,
            shared_body_width=self.shared_width,
        )

    def _branch_lead(
        self,
        atom: DrakonAtom,
        branch_index: int,
    ) -> tuple[str, SolvedShape] | None:
        if isinstance(atom, Select):
            case = atom.cases[branch_index]
            detail = case.pattern if atom.mode.value == "match" else case.condition
            if case.is_default:
                detail = "default"
            if case.guard:
                detail += f" if {case.guard}"
            return case.id, self._derived_shape(
                RecipeKind.CASE,
                {"case": f"{case.label} · {detail}"},
            )
        if isinstance(atom, Parallel):
            parallel_branch = atom.branches[branch_index]
            return parallel_branch.id, self._derived_shape(
                RecipeKind.BRANCH_HEADER,
                {"branch": parallel_branch.name},
            )
        if isinstance(atom, Silhouette):
            silhouette_branch = atom.branches[branch_index]
            initial = " · initial" if silhouette_branch.id == atom.initial_branch_id else ""
            return silhouette_branch.id, self._derived_shape(
                RecipeKind.BRANCH_HEADER,
                {"branch": f"{silhouette_branch.name}{initial}"},
            )
        if isinstance(atom, Try) and branch_index > 0 and branch_index <= len(atom.handlers):
            handler = atom.handlers[branch_index - 1]
            star = "*" if atom.except_star else ""
            name = f" as {handler.name}" if handler.name else ""
            return handler.id, self._derived_shape(
                RecipeKind.CASE,
                {"case": f"except{star} {handler.exception}{name}"},
            )
        return None

    def _branch_tail(
        self,
        atom: DrakonAtom,
        branch_index: int,
    ) -> tuple[str, SolvedShape] | None:
        if isinstance(atom, Loop) and branch_index == 0:
            return f"{atom.id}:end", self._derived_shape(
                RecipeKind.FOR_END,
                {"loop": "repeat / continue"},
            )
        if isinstance(atom, Silhouette):
            branch = atom.branches[branch_index]
            target = next(
                (
                    candidate.name
                    for candidate in atom.branches
                    if candidate.id == branch.target_branch_id
                ),
                "finite exit",
            )
            return f"{branch.id}:address", self._derived_shape(
                RecipeKind.ADDRESS,
                {"address": f"Address → {target}"},
            )
        return None

    def _route(
        self,
        start: Point,
        end: Point,
        boundary: SequenceBoundary | None,
        *,
        tooltip: str = "Insert at this Sequence boundary",
        arrow_at_end: bool = False,
    ) -> None:
        if start == end:
            return
        if start.x != end.x and start.y != end.y:
            raise ValueError("Route builder requires one orthogonal segment at a time")
        self._route_count += 1
        self.routes.append(
            SceneRoute(
                id=f"route_{self._route_count:04d}",
                segment=Segment(start, end),
                boundary=boundary,
                legal_insertion=boundary is not None,
                tooltip=tooltip,
                arrow_at_end=arrow_at_end,
            )
        )

    def _layout_sequence(self, sequence: Sequence, x: float, start: Point) -> Point:
        if not sequence.atoms:
            marker = self._derived_shape(
                RecipeKind.CONNECTOR_MARKER,
                {"marker": "Insert"},
            )
            top = start.y + self.metrics.metre
            node = self._node(f"{sequence.id}:insertion", marker, x, top)
            boundary = SequenceBoundary(sequence.id, 0)
            self._route(start, node.port("input"), boundary)
            return node.port("output")
        current = start
        for index, atom in enumerate(sequence.atoms):
            shape = self.shapes[atom.id]
            top = current.y + self.metrics.metre
            node = self._node(atom.id, shape, x, top)
            self._route(current, node.port("input"), SequenceBoundary(sequence.id, index))
            if not isinstance(atom, If) and not nested_sequences(atom):
                current = node.port("output")
                continue

            if not isinstance(atom, If):
                branches = nested_sequences(atom)
                offsets = self._composite_offsets(atom)
                labels = self._composite_labels(atom)
                down_port = (
                    node.port("down")
                    if any(port.name == "down" for port in node.shape.ports)
                    else node.port("output")
                )
                right_port = (
                    node.port("right")
                    if any(port.name == "right" for port in node.shape.ports)
                    else down_port
                )
                exits: list[tuple[Point, Sequence, float]] = []
                for branch_index, (branch, offset) in enumerate(
                    zip(branches, offsets, strict=True)
                ):
                    branch_x = x + offset
                    branch_start = Point(branch_x, down_port.y)
                    if branch_index > 0:
                        boundary = SequenceBoundary(branch.id, 0)
                        elbow = Point(branch_x, right_port.y)
                        self._route(right_port, elbow, boundary)
                        self._route(elbow, branch_start, boundary)
                    label = labels[branch_index] if branch_index < len(labels) else "route"
                    self.labels.append(
                        SceneLabel(
                            label,
                            Rect(
                                branch_start.x + self.metrics.unit / 2,
                                branch_start.y + 2,
                                self.measurer.measure_line(label).width,
                                self.measurer.line_height,
                            ),
                            atom.id,
                        )
                    )
                    branch_current = branch_start
                    lead = self._branch_lead(atom, branch_index)
                    if lead is not None:
                        lead_id, lead_shape = lead
                        lead_node = self._node(
                            lead_id,
                            lead_shape,
                            branch_x,
                            branch_current.y + self.metrics.metre,
                        )
                        self._route(
                            branch_current,
                            lead_node.port("input"),
                            SequenceBoundary(branch.id, 0),
                        )
                        branch_current = lead_node.port("output")
                    branch_exit = self._layout_sequence(branch, branch_x, branch_current)
                    tail = self._branch_tail(atom, branch_index)
                    if tail is not None:
                        tail_id, tail_shape = tail
                        tail_node = self._node(
                            tail_id,
                            tail_shape,
                            branch_x,
                            branch_exit.y + self.metrics.metre,
                        )
                        self._route(
                            branch_exit,
                            tail_node.port("input"),
                            SequenceBoundary(branch.id, len(branch.atoms)),
                        )
                        branch_exit = tail_node.port("output")
                    exits.append((branch_exit, branch, branch_x))
                if not exits:
                    current = down_port
                    continue
                join_y = max(exit_point.y for exit_point, _, _ in exits) + self.metrics.metre
                join = Point(x, join_y)
                for exit_point, branch, branch_x in exits:
                    boundary = SequenceBoundary(branch.id, len(branch.atoms))
                    vertical_end = Point(branch_x, join_y)
                    self._route(exit_point, vertical_end, boundary)
                    if vertical_end != join:
                        self._route(vertical_end, join, boundary)
                current = join
                continue

            preferred = atom.true_branch if atom.preferred_truth else atom.false_branch
            secondary = atom.false_branch if atom.preferred_truth else atom.true_branch
            preferred_truth = atom.preferred_truth
            down_start = node.port("down")
            secondary_x = x + self._secondary_offset(atom)
            right_port = node.port("right")
            secondary_start = Point(secondary_x, down_start.y)
            secondary_boundary = SequenceBoundary(secondary.id, 0)
            elbow = Point(secondary_x, right_port.y)
            self._route(right_port, elbow, secondary_boundary)
            self._route(elbow, secondary_start, secondary_boundary)

            label_height = self.measurer.line_height
            down_text = f"{preferred_truth} · preferred"
            right_text = f"{not preferred_truth} · alternate"
            self.labels.append(
                SceneLabel(
                    down_text,
                    Rect(
                        down_start.x + self.metrics.unit / 2,
                        down_start.y + 2,
                        self.measurer.measure_line(down_text).width,
                        label_height,
                    ),
                    atom.id,
                )
            )
            self.labels.append(
                SceneLabel(
                    right_text,
                    Rect(
                        right_port.x + self.metrics.unit / 2,
                        right_port.y - label_height - 2,
                        self.measurer.measure_line(right_text).width,
                        label_height,
                    ),
                    atom.id,
                )
            )

            down_exit = self._layout_sequence(preferred, x, down_start)
            right_exit = self._layout_sequence(secondary, secondary_x, secondary_start)
            join_y = max(down_exit.y, right_exit.y) + self.metrics.metre
            preferred_boundary = SequenceBoundary(preferred.id, len(preferred.atoms))
            trailing_secondary = SequenceBoundary(secondary.id, len(secondary.atoms))
            join = Point(x, join_y)
            self._route(down_exit, join, preferred_boundary)
            right_join = Point(secondary_x, join_y)
            self._route(right_exit, right_join, trailing_secondary)
            self._route(right_join, join, trailing_secondary)
            current = join
        return current

    def build(self) -> DiagramScene:
        left_extent, _ = self._extent(self.diagram.body)
        skewer_x = self.metrics.margin + max(left_extent, self.shared_width / 2)
        header = self._node(
            self.diagram.header.id, self.header_shape, skewer_x, self.metrics.margin
        )
        start = header.port("output")
        if self.signature_shape is not None:
            signature = self._node(
                f"{self.diagram.header.id}:signature",
                self.signature_shape,
                skewer_x,
                start.y + self.metrics.metre,
            )
            self._route(
                start,
                signature.port("input"),
                None,
                tooltip="Formal parameters and callable metadata",
            )
            start = signature.port("output")
        current = self._layout_sequence(
            self.diagram.body,
            skewer_x,
            start,
        )
        end_top = current.y + self.metrics.metre
        end = self._node(self.diagram.end.id, self.end_shape, skewer_x, end_top)
        self._route(
            current,
            end.port("input"),
            SequenceBoundary(self.diagram.body.id, len(self.diagram.body.atoms)),
        )
        fit_parts = [node.bounds.expanded(STROKE_WIDTH / 2) for node in self.nodes]
        fit_parts.extend(route.segment.bounds(STROKE_WIDTH) for route in self.routes)
        fit_parts.extend(label.bounds for label in self.labels)
        raw_bounds = union_rects(tuple(fit_parts))
        bounds = raw_bounds.expanded(self.metrics.margin)
        return DiagramScene(
            diagram_id=self.diagram.id,
            nodes=tuple(self.nodes),
            routes=tuple(self.routes),
            labels=tuple(self.labels),
            bounds=bounds,
            skewer_x=skewer_x,
            metrics=self.metrics,
        )


def layout_drakon(
    diagram: DrakonDiagram,
    *,
    measurer: TextMeasurer | None = None,
    metrics: LayoutMetrics | None = None,
) -> DiagramScene:
    resolved_measurer: TextMeasurer = measurer or DeterministicTextMeasurer()
    return _SceneBuilder(
        diagram,
        resolved_measurer,
        metrics or LayoutMetrics(),
    ).build()
