"""CAD interpretation at the ordinary Python computation API boundary."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import QuantityValue, ResourceReference
from code_visualizer.execution.python_api import context, input_resource, publish_bytes
from code_visualizer.extensions.cad.native import encode_solid, implementation_version
from code_visualizer.extensions.cad.resources import (
    BREP,
    MEDIA_TYPE,
    CadError,
    CadHeader,
    CadOrigins,
    FrameSnapshot,
)
from code_visualizer.extensions.cad.units import cad_catalog
from code_visualizer.extensions.foundations.equations import RESULT_TYPE
from code_visualizer.persistence.values import canonical_value_from_data

if TYPE_CHECKING:
    from build123d import Shape


def solved_length(input_name: str, symbol_id: str) -> QuantityValue:
    source = input_resource(input_name, ResourceLogicalTypeReference(RESULT_TYPE, "1"))
    data = json.loads(source.read_bytes(limit=2 * 1024 * 1024))
    if (
        not isinstance(data, dict)
        or data.get("format") != RESULT_TYPE
        or data.get("version") != "1"
    ):
        raise CadError("CAD_EQUATION_INPUT", "Expected the supported checked equation solution")
    variables = data.get("variables")
    if not isinstance(variables, list):
        raise CadError("CAD_EQUATION_INPUT", "Missing solved variables")
    selected = [v for v in variables if isinstance(v, dict) and v.get("id") == symbol_id]
    if len(selected) != 1 or selected[0].get("kind") not in ("linear", "interval"):
        raise CadError("CAD_EQUATION_INPUT", "Select exactly one linear/interval solved length")
    value = canonical_value_from_data(selected[0].get("value"))
    if not isinstance(value, QuantityValue) or type(value.magnitude) not in (int, float):
        raise CadError("CAD_EQUATION_INPUT", "The solution must be a real quantity")
    converted = cad_catalog().convert(value, cad_catalog().unit("foundation.units.si:meter"))
    from code_visualizer.extensions.cad.resources import positive

    positive(converted.magnitude)
    return converted


def native_length(value: QuantityValue) -> float:
    from code_visualizer.extensions.cad.resources import positive

    return positive(
        cad_catalog().convert(value, cad_catalog().unit("foundation.units.si:millimeter")).magnitude
    )


def publish_solid(
    name: str,
    shape: Shape[Any],
    *,
    frame: FrameSnapshot,
    parameters: tuple[tuple[str, QuantityValue], ...],
    parent: ResourceReference | None = None,
    tolerance: float = 1e-7,
) -> str:
    active = context()
    declaration = next((v for v in active.request.outputs if v.name == name), None)
    if declaration is None or declaration.logical_type != BREP:
        raise CadError("CAD_OUTPUT_DECLARATION", "A named BREP output declaration is required")
    if parent is not None and parent not in active.request.resources:
        raise CadError("CAD_PARENT", "A parent must be an explicitly bound input resource")
    header = CadHeader(
        BREP,
        frame,
        CadOrigins(
            active.request.project_id,
            active.request.revision,
            active.input_digest,
            declaration.semantic_ids,
        ),
        "org.opencascade.brep",
        implementation_version(),
        tolerance,
        parameters,
        parent,
    )
    return publish_bytes(
        name,
        encode_solid(shape, header),
        logical_type=BREP,
        media_type=MEDIA_TYPE,
        semantic_ids=declaration.semantic_ids,
    )
