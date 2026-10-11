"""Validate the authored axial fragment without importing native CAD or solving."""

from dataclasses import dataclass
from math import isfinite

from code_visualizer.domain.intentional import DomainIssue, DomainModel, IntentionalNode
from code_visualizer.domain.project import Project
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.extensions.axial.domain import IDEALIZATION_ID, identity, quantity
from code_visualizer.extensions.cad.domain import identity as cad_id
from code_visualizer.extensions.foundations.unit_algebra import UnitAlgebra
from code_visualizer.extensions.foundations.units import UnitCatalog, UnitError


class AxialError(ValueError):
    def __init__(self, code: str, message: str, object_id: str):
        self.code, self.object_id = code, object_id
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class AxialProblem:
    id: str
    geometry_id: str
    material_id: str
    support_id: str
    load_id: str
    geometry: ResourceReference
    frame_id: str
    axis: str
    nodes: int
    young_modulus: float
    force: float
    support_region: IntentionalNode
    load_region: IntentionalNode

    @property
    def origins(self) -> tuple[str, ...]:
        return (
            self.id,
            self.geometry_id,
            self.material_id,
            self.support_id,
            self.load_id,
            self.support_region.id,
            self.load_region.id,
        )


def derive_problem(project: Project, model: DomainModel) -> AxialProblem:
    roots = [node for node in model.nodes if node.concept_id == identity("AxialProblem")]
    if len(roots) != 1 or model.roots != (roots[0].id,):
        raise AxialError("AXIAL_ROOT", "Select one authored axial problem", model.id)
    root = roots[0]
    all_nodes = {node.id: node for item in project.domain_workspace.models for node in item.nodes}
    algebra = UnitAlgebra(UnitCatalog.from_models(project.domain_workspace.models))

    def prop(node: IntentionalNode, key: str) -> object:
        return node.property(node.concept_id + ":" + key)

    def child(key: str, kind: str) -> IntentionalNode:
        ids = root.child_ids(identity("AxialProblem", key))
        node = model.node(ids[0]) if len(ids) == 1 else None
        if node is None or node.concept_id != identity(kind):
            raise AxialError("AXIAL_OWNERSHIP", "One explicit " + key + " is required", root.id)
        return node

    def amount(node: IntentionalNode, key: str, unit: str) -> float:
        value = prop(node, key)
        if not isinstance(value, QuantityValue) or type(value.magnitude) not in (int, float):
            raise AxialError("AXIAL_QUANTITY", key + " requires a real quantity", node.id)
        try:
            result = algebra.convert(value, quantity(1, unit).unit).magnitude
        except UnitError as exc:
            raise AxialError("AXIAL_UNIT", str(exc), node.id) from exc
        assert isinstance(result, int | float)
        if not isfinite(result):
            raise AxialError("AXIAL_RANGE", "Nonfinite " + key, node.id)
        return float(result)

    geometry, material, support, load = (
        child(key, kind)
        for key, kind in (
            ("geometry", "GeometryIdealization"),
            ("material", "Material"),
            ("support", "AxialSupport"),
            ("load", "AxialLoad"),
        )
    )
    resource = prop(geometry, "geometry")
    frame, axis = prop(geometry, "frame_id"), prop(geometry, "axis")
    if not isinstance(resource, ResourceReference):
        raise AxialError("AXIAL_GEOMETRY", "Bind an exact immutable BREP", geometry.id)
    if not isinstance(frame, str) or not frame or axis not in ("x", "y", "z"):
        raise AxialError(
            "AXIAL_FRAME", "Declare a Cartesian frame and axial direction", geometry.id
        )
    assert isinstance(axis, str)
    if (prop(geometry, "method_id"), prop(geometry, "method_version")) != (IDEALIZATION_ID, "1"):
        raise AxialError("AXIAL_IDEALIZATION", "Unsupported geometry-to-axis mapping", geometry.id)
    if prop(load, "frame_id") != frame or prop(load, "axis") != axis:
        raise AxialError(
            "AXIAL_LOAD_DIRECTION",
            "Transverse or differently framed loads are unsupported",
            load.id,
        )
    modulus, force = amount(material, "young_modulus", "pascal"), amount(load, "force", "newton")
    if not 1 <= modulus <= 1e15:
        raise AxialError(
            "AXIAL_MATERIAL", "Young modulus must be positive and at most 1e15 Pa", material.id
        )
    if abs(force) > 1e9:
        raise AxialError("AXIAL_LOAD", "Resultant exceeds the declared 1e9 N bound", load.id)
    if amount(support, "displacement", "meter") != 0:
        raise AxialError(
            "AXIAL_SUPPORT", "The supported fragment has one fixed axial end", support.id
        )
    count = prop(root, "nodes")
    if type(count) is not int or not 3 <= count <= 65:
        raise AxialError("AXIAL_DISCRETIZATION", "Use 3..65 axial nodes", root.id)

    def region(owner: IntentionalNode, assignment: str, side: str) -> IntentionalNode:
        refs = owner.reference_ids(owner.concept_id + ":region")
        node = all_nodes.get(refs[0]) if len(refs) == 1 else None
        if node is None or node.concept_id != cad_id("RegionSelection"):
            raise AxialError("AXIAL_REGION", "Select one authored CAD region predicate", owner.id)
        if prop(node, "geometry") != resource:
            raise AxialError(
                "AXIAL_STALE_REGION", "Region belongs to another geometry resource", node.id
            )
        if (
            prop(node, "frame_id"),
            prop(node, "axis"),
            prop(node, "side"),
            prop(node, "assignment"),
            prop(node, "expected_count"),
        ) != (frame, axis, side, assignment, 1):
            raise AxialError(
                "AXIAL_REGION", "Require opposite end predicates in the declared frame", node.id
            )
        return node

    return AxialProblem(
        root.id,
        geometry.id,
        material.id,
        support.id,
        load.id,
        resource,
        frame,
        axis,
        count,
        modulus,
        force,
        region(support, "support", "min"),
        region(load, "load", "max"),
    )


def validate_problem(project: Project, model: DomainModel) -> tuple[DomainIssue, ...]:
    try:
        derive_problem(project, model)
    except AxialError as exc:
        return (DomainIssue(exc.code, str(exc), exc.object_id, incomplete=True),)
    return ()
