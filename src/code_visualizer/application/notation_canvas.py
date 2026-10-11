"""Compile a composed notation into disposable primitives and explicit edit bindings."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

from code_visualizer.application.notations import NotationEditBinding, field_cell
from code_visualizer.domain import notation_syntax as v
from code_visualizer.domain.intentional import DomainModel, DomainSchema, IntentionalNode
from code_visualizer.domain.notation import NotationDefinition, NotationField
from code_visualizer.domain.project import Project
from code_visualizer.domain.semantic import SemanticRelation


class CanvasKind(StrEnum):
    TEXT = "text"
    FIELD = "field"
    BOX = "box"
    PATH = "path"


@dataclass(frozen=True, slots=True)
class CanvasItem:
    id: str
    syntax_id: str
    kind: CanvasKind
    x: float
    y: float
    width: float
    height: float
    semantic_ids: tuple[str, ...] = ()
    text: str = ""
    font_size: float = 14.0
    strong: bool = False
    fill: str = "transparent"
    stroke: str = "#172033"
    shape: v.VisualShape = v.VisualShape.RECTANGLE
    points: tuple[tuple[float, float], ...] = ()
    closed: bool = False
    edit: NotationEditBinding | None = None
    active: bool = False
    occurrence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CanvasConnector:
    id: str
    source_id: str
    target_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    label: str = ""
    arrow: bool = True
    stroke: str = "#536b91"
    active: bool = False


@dataclass(frozen=True, slots=True)
class NotationCanvas:
    definition_id: str
    revision: int
    items: tuple[CanvasItem, ...]
    connectors: tuple[CanvasConnector, ...]
    width: float
    height: float
    runtime_revision: int | None = None


@dataclass(frozen=True, slots=True)
class _Bound:
    model: DomainModel
    schema: DomainSchema
    node: IntentionalNode


@dataclass(frozen=True, slots=True)
class _Connection:
    id: str
    source_id: str
    target_id: str
    definition: v.VisualConnector
    occurrence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Fragment:
    items: tuple[CanvasItem, ...] = ()
    connections: tuple[_Connection, ...] = ()
    width: float = 0.0
    height: float = 0.0


class NotationCompositionError(ValueError):
    pass


def _shift(fragment: _Fragment, x: float, y: float) -> _Fragment:
    return replace(
        fragment, items=tuple(replace(item, x=item.x + x, y=item.y + y) for item in fragment.items)
    )


def _pack(
    parts: tuple[_Fragment, ...],
    layout: v.VisualLayout,
    gap: float,
    padding: float = 0.0,
    wrap_width: float = 600.0,
) -> _Fragment:
    items: list[CanvasItem] = []
    connections: list[_Connection] = []
    x = y = padding
    width = height = 0.0
    line_height = 0.0
    for part in parts:
        if layout is v.VisualLayout.WRAP and x > padding and x + part.width > wrap_width:
            x, y = padding, y + line_height + gap
            line_height = 0.0
        shifted = part if layout is v.VisualLayout.POSITIONED else _shift(part, x, y)
        items.extend(shifted.items)
        connections.extend(shifted.connections)
        width = max(width, (0.0 if layout is v.VisualLayout.POSITIONED else x) + part.width)
        height = max(height, (0.0 if layout is v.VisualLayout.POSITIONED else y) + part.height)
        if layout in {v.VisualLayout.ROW, v.VisualLayout.WRAP}:
            x += part.width + gap
            line_height = max(line_height, part.height)
        elif layout is v.VisualLayout.COLUMN:
            y += part.height + gap
    return _Fragment(tuple(items), tuple(connections), width + padding, height + padding)


class _Compiler:
    def __init__(
        self,
        project: Project,
        model: DomainModel,
        relations: tuple[SemanticRelation, ...],
        active_ids: tuple[str, ...],
    ) -> None:
        self.project = project
        self.model = model
        self.active_ids = frozenset(active_ids)
        self.remaining = 20_000
        self.objects: dict[str, _Bound] = {}
        for candidate in project.domain_workspace.models:
            schema = project.domain_workspace.schema(candidate.schema_id)
            if schema is not None:
                self.objects.update(
                    (node.id, _Bound(candidate, schema, node)) for node in candidate.nodes
                )
        self.relations = tuple(
            (item.source_id, item.target_id, item.kind.value, item.label) for item in relations
        )
        self.relations += tuple(
            (item.source_id, item.target_id, item.kind.value, item.label)
            for item in project.semantic_relations
        )

    def charge(self, depth: int, count: int = 1) -> None:
        self.remaining -= count
        if self.remaining < 0 or depth > 64:
            raise NotationCompositionError("Notation expansion exceeds 20000 elements or 64 levels")

    def query(self, query: v.NotationQuery, environment: dict[str, _Bound]) -> tuple[_Bound, ...]:
        if isinstance(query, v.NotationQueryHole):
            return ()
        if isinstance(query, v.NotationObjects):
            self.charge(0, len(self.objects))
            if (
                query.model_id is not None
                and self.project.domain_workspace.model(query.model_id) is None
            ):
                raise NotationCompositionError(
                    "The notation's selected domain model is unavailable"
                )
            if query.schema_id is not None:
                schema = self.project.domain_workspace.schema(query.schema_id)
                if schema is None or schema.version != query.schema_version:
                    raise NotationCompositionError(
                        "The notation's selected schema/version is unavailable"
                    )
            return tuple(
                bound
                for bound in self.objects.values()
                if (query.workspace or bound.model.id == self.model.id)
                and (not query.model_id or bound.model.id == query.model_id)
                and (not query.schema_id or bound.schema.id == query.schema_id)
                and (not query.concept_id or bound.node.concept_id == query.concept_id)
                and (not query.roots_only or bound.node.id in bound.model.roots)
            )
        source = environment.get(query.source_binding_id)
        if source is None:
            raise NotationCompositionError("Related-object query has no bound source object")
        identities: list[str] = []
        if query.role_id:
            if query.incoming:
                self.charge(0, len(self.objects))
                identities.extend(
                    bound.node.id
                    for bound in self.objects.values()
                    if source.node.id
                    in (
                        *bound.node.child_ids(query.role_id),
                        *bound.node.reference_ids(query.role_id),
                    )
                )
            else:
                identities.extend(
                    (
                        *source.node.child_ids(query.role_id),
                        *source.node.reference_ids(query.role_id),
                    )
                )
                self.charge(0, len(identities))
        else:
            self.charge(0, len(self.relations))
            for left, right, kind, label in self.relations:
                if query.relation_kind and query.relation_kind != kind:
                    continue
                if query.relation_label and query.relation_label != label:
                    continue
                if (right if query.incoming else left) == source.node.id:
                    identities.append(left if query.incoming else right)
        return tuple(
            self.objects[identity]
            for identity in dict.fromkeys(identities)
            if identity in self.objects
        )

    def number(self, number: v.VisualNumber, environment: dict[str, _Bound]) -> float:
        value: object = number.value
        if number.property_id:
            bound = environment.get(number.binding_id)
            if bound is None:
                raise NotationCompositionError("A coordinate refers to an unbound object")
            value = bound.node.property(number.property_id)
        if type(value) not in {int, float}:
            raise NotationCompositionError("A visual coordinate or size needs a numeric property")
        result = float(cast(int | float, value)) * number.scale + number.offset
        if not math.isfinite(result) or abs(result) > 1_000_000:
            raise NotationCompositionError("A visual coordinate exceeds the finite canvas range")
        return result

    def predicate(self, condition: v.VisualPredicate, environment: dict[str, _Bound]) -> bool:
        bound = environment.get(condition.binding_id)
        value = (
            bound.node.property(condition.property_id)
            if bound and condition.property_id
            else (bound.node.id if bound else None)
        )
        if condition.operator is v.VisualComparison.PRESENT:
            return value is not None
        if condition.operator is v.VisualComparison.EQUAL:
            return value == condition.expected
        if condition.operator is v.VisualComparison.NOT_EQUAL:
            return value != condition.expected
        if type(value) not in {int, float} or type(condition.expected) not in {int, float}:
            raise NotationCompositionError("Ordered visual conditions need numeric values")
        left, right = cast(int | float, value), cast(int | float, condition.expected)
        return left < right if condition.operator is v.VisualComparison.LESS else left > right

    def compile(
        self,
        visual: v.Visual,
        environment: dict[str, _Bound],
        chain: tuple[str, ...] = (),
        depth: int = 0,
    ) -> _Fragment:
        self.charge(depth)
        identity = f"visual:{visual.id}:" + "/".join(chain)
        bound = environment.get("self")
        semantic_ids = (bound.node.id,) if bound else ()

        def child(value: v.Visual) -> _Fragment:
            return self.compile(value, environment, chain, depth + 1)

        if isinstance(visual, (v.VisualText, v.VisualField, v.VisualHole)):
            text = (
                visual.text
                if isinstance(visual, v.VisualText)
                else visual.label
                if isinstance(visual, v.VisualHole)
                else ""
            )
            size = visual.font_size if not isinstance(visual, v.VisualHole) else 14.0
            edit = None
            if isinstance(visual, v.VisualField):
                selected = environment.get(visual.binding_id)
                if selected is None:
                    raise NotationCompositionError(
                        "Editable field has no bound object; place it inside a repeat"
                    )
                cell = field_cell(
                    selected.schema,
                    selected.model,
                    selected.node,
                    NotationField(visual.property_id, visual.reference_role_ids),
                    cell_id=identity,
                    revision=self.project.revision,
                    editable=visual.editable,
                    workspace=self.project.domain_workspace,
                )
                text, edit, semantic_ids = cell.text, cell.edit, (cell.semantic_id,)
            width = max(
                12.0, max((len(line) for line in text.splitlines()), default=0) * size * 0.64 + 8
            )
            height = max(1, len(text.splitlines())) * size * 1.45 + 4
            item = CanvasItem(
                identity,
                visual.id,
                CanvasKind.FIELD if edit else CanvasKind.TEXT,
                0,
                0,
                width,
                height,
                semantic_ids,
                text,
                size,
                visual.strong if isinstance(visual, v.VisualText) else False,
                stroke=visual.color if isinstance(visual, v.VisualText) else "#172033",
                edit=edit,
                active=bool(self.active_ids.intersection(semantic_ids)),
                occurrence=chain,
            )
            return _Fragment((item,), width=width, height=height)
        if isinstance(visual, v.VisualGroup):
            return _pack(
                tuple(child(item) for item in visual.children),
                visual.layout,
                visual.gap,
                visual.padding,
                visual.wrap_width,
            )
        if isinstance(visual, v.VisualRepeat):
            parts = tuple(
                self.compile(
                    visual.body,
                    {**environment, visual.binding_id: item, "self": item},
                    (*chain, item.node.id),
                    depth + 1,
                )
                for item in self.query(visual.query, environment)
            )
            return _pack(parts, visual.layout, visual.gap)
        if isinstance(visual, v.VisualConditional):
            selected_visual = (
                visual.body if self.predicate(visual.predicate, environment) else visual.otherwise
            )
            return child(selected_visual) if selected_visual else _Fragment()
        if isinstance(visual, v.VisualPosition):
            part = child(visual.body)
            x, y = self.number(visual.x, environment), self.number(visual.y, environment)
            return replace(
                _shift(part, x, y), width=max(0, x) + part.width, height=max(0, y) + part.height
            )
        if isinstance(visual, v.VisualBox):
            part = child(visual.body)
            width = max(
                part.width + 2 * visual.padding,
                self.number(visual.width, environment) if visual.width else 0,
            )
            height = max(
                part.height + 2 * visual.padding,
                self.number(visual.height, environment) if visual.height else 0,
            )
            box = CanvasItem(
                identity,
                visual.id,
                CanvasKind.BOX,
                0,
                0,
                width,
                height,
                semantic_ids,
                fill=visual.fill,
                stroke=visual.stroke,
                shape=visual.shape,
                active=bool(self.active_ids.intersection(semantic_ids)),
                occurrence=chain,
            )
            return _Fragment(
                (box, *_shift(part, visual.padding, visual.padding).items),
                part.connections,
                width,
                height,
            )
        if isinstance(visual, v.VisualFraction):
            top, bottom = child(visual.numerator), child(visual.denominator)
            width = max(top.width, bottom.width) + 10
            line = CanvasItem(
                identity,
                visual.id,
                CanvasKind.PATH,
                0,
                top.height + 3,
                width,
                1,
                semantic_ids,
                points=((0, 0), (width, 0)),
                occurrence=chain,
            )
            return _Fragment(
                (
                    *_shift(top, (width - top.width) / 2, 0).items,
                    line,
                    *_shift(bottom, (width - bottom.width) / 2, top.height + 8).items,
                ),
                (*top.connections, *bottom.connections),
                width,
                top.height + bottom.height + 8,
            )
        if isinstance(visual, v.VisualScript):
            base, script = child(visual.base), child(visual.script)
            offset = script.height * 0.55
            base_y = offset if visual.position is v.ScriptPosition.SUPER else 0.0
            script_y = 0.0 if visual.position is v.ScriptPosition.SUPER else base.height * 0.65
            return _Fragment(
                (*_shift(base, 0, base_y).items, *_shift(script, base.width, script_y).items),
                (*base.connections, *script.connections),
                base.width + script.width,
                max(base_y + base.height, script_y + script.height),
            )
        if isinstance(visual, v.VisualPath):
            points = tuple(
                (self.number(point.x, environment), self.number(point.y, environment))
                for point in visual.points
            )
            width = max((point[0] for point in points), default=0.0)
            height = max((point[1] for point in points), default=0.0)
            item = CanvasItem(
                identity,
                visual.id,
                CanvasKind.PATH,
                0,
                0,
                width,
                height,
                semantic_ids,
                fill=visual.fill,
                stroke=visual.stroke,
                points=points,
                closed=visual.closed,
                occurrence=chain,
            )
            return _Fragment((item,), width=width, height=height)
        if isinstance(visual, v.VisualConnector):
            source, target = (
                environment.get(visual.source_binding_id),
                environment.get(visual.target_binding_id),
            )
            if source is None or target is None:
                raise NotationCompositionError("A connector needs two bound domain objects")
            return _Fragment(
                connections=(_Connection(identity, source.node.id, target.node.id, visual, chain),)
            )
        raise NotationCompositionError("Unknown visual notation element")


def compile_notation_canvas(
    project: Project,
    model_id: str,
    definition: NotationDefinition,
    *,
    relations: tuple[SemanticRelation, ...] = (),
    active_ids: tuple[str, ...] = (),
    runtime_revision: int | None = None,
) -> NotationCanvas:
    model = project.domain_workspace.model(model_id)
    if model is None or definition.body is None:
        raise NotationCompositionError("A composed notation needs a model and a visual body")
    compiler = _Compiler(
        project,
        model,
        relations,
        active_ids if runtime_revision in {None, project.revision} else (),
    )
    root = compiler.objects.get(model.roots[0]) if len(model.roots) == 1 else None
    fragment = compiler.compile(definition.body, {"self": root} if root else {})
    anchors: dict[str, list[CanvasItem]] = {}
    for item in fragment.items:
        for semantic_id in item.semantic_ids:
            if item.kind is not CanvasKind.PATH:
                anchors.setdefault(semantic_id, []).append(item)

    def anchor(semantic_id: str, occurrence: tuple[str, ...]) -> CanvasItem | None:
        candidates = anchors.get(semantic_id, [])
        if not candidates:
            return None

        def score(item: CanvasItem) -> tuple[int, int, int]:
            common = 0
            for left, right in zip(item.occurrence, occurrence, strict=False):
                if left != right:
                    break
                common += 1
            priority = (
                2 if item.kind is CanvasKind.BOX else 1 if item.kind is CanvasKind.FIELD else 0
            )
            return common, -abs(len(item.occurrence) - len(occurrence)), priority

        best = max(score(item) for item in candidates)
        chosen = [item for item in candidates if score(item) == best]
        if len(chosen) != 1:
            raise NotationCompositionError(
                "A connector has multiple displayed anchors in this object context; "
                "wrap its intended occurrence in one box"
            )
        return chosen[0]

    connectors = []
    for connection in fragment.connections:
        source, target = (
            anchor(connection.source_id, connection.occurrence),
            anchor(connection.target_id, connection.occurrence),
        )
        if source is None or target is None:
            continue

        def boundary(item: CanvasItem, other: CanvasItem) -> tuple[float, float]:
            x, y = item.x + item.width / 2, item.y + item.height / 2
            dx = other.x + other.width / 2 - x
            dy = other.y + other.height / 2 - y
            if dx == dy == 0:
                return x, y
            factors = []
            if dx:
                factors.append(item.width / (2 * abs(dx)))
            if dy:
                factors.append(item.height / (2 * abs(dy)))
            factor = min(factors)
            return x + dx * factor, y + dy * factor

        connectors.append(
            CanvasConnector(
                connection.id,
                connection.source_id,
                connection.target_id,
                boundary(source, target),
                boundary(target, source),
                connection.definition.label,
                connection.definition.arrow,
                connection.definition.stroke,
                bool(
                    compiler.active_ids.intersection((connection.source_id, connection.target_id))
                ),
            )
        )
    return NotationCanvas(
        definition.id,
        project.revision,
        fragment.items,
        tuple(connectors),
        fragment.width,
        fragment.height,
        runtime_revision,
    )
