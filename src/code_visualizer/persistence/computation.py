"""Strict JSON boundary for ephemeral computation requests."""

from __future__ import annotations

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.computation import (
    ComputationParameter,
    ComputationPlan,
    ComputationRequest,
    ResourceInput,
    ResourceOutput,
)
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.transformation import OriginLink, OriginMap, Representation
from code_visualizer.domain.values import ResourceReference
from code_visualizer.persistence.values import canonical_value_from_data, canonical_value_to_data


def computation_plan_to_data(value: ComputationPlan) -> dict[str, JsonValue]:
    return {
        "version": 1,
        "request": computation_request_to_data(value.request),
        "representation": {"id": value.representation.id, "version": value.representation.version},
        "model": canonical_value_to_data(value.model),
        "transformations": list(value.transformations),
        "origins": [
            {"generated_id": item.generated_id, "source_ids": list(item.source_ids)}
            for item in value.origins.links
        ],
        "input_digest": value.input_digest,
    }


def computation_plan_from_data(raw: object) -> ComputationPlan:
    from code_visualizer.persistence.values import array_data, integer_data, object_data, text_data

    data = object_data(
        raw,
        {
            "version",
            "request",
            "representation",
            "model",
            "transformations",
            "origins",
            "input_digest",
        },
    )
    if integer_data(data.get("version")) != 1:
        raise ValueError("Unsupported computation plan version")
    request = computation_request_from_data(data.get("request"))
    representation = object_data(data.get("representation"), {"id", "version"})
    model = canonical_value_from_data(data.get("model"))
    if not isinstance(model, ResourceReference):
        raise ValueError("A computation terminal must be a resource reference")
    links = [
        object_data(item, {"generated_id", "source_ids"})
        for item in array_data(data.get("origins"))
    ]
    return ComputationPlan(
        request,
        Representation(
            text_data(representation.get("id")), text_data(representation.get("version"))
        ),
        model,
        tuple(text_data(item) for item in array_data(data.get("transformations"))),
        OriginMap(
            request.project_id,
            request.revision,
            tuple(
                OriginLink(
                    text_data(item.get("generated_id")),
                    tuple(text_data(identity) for identity in array_data(item.get("source_ids"))),
                )
                for item in links
            ),
        ),
        text_data(data.get("input_digest")),
    )


def computation_request_to_data(value: ComputationRequest) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {
        "project_id": value.project_id,
        "revision": value.revision,
        "backend_id": value.backend_id,
        "backend_version": value.backend_version,
        "model_id": value.model_id,
        "configuration": [
            {"name": item.name, "value": canonical_value_to_data(item.value)}
            for item in sorted(value.configuration, key=lambda item: item.name)
        ],
        "seed": value.seed,
        "resources": [
            canonical_value_to_data(item)
            for item in sorted(value.resources, key=lambda item: item.id)
        ],
    }
    if value.inputs or value.outputs:
        result.update(
            {
                "version": 2,
                "inputs": [
                    {
                        "name": item.name,
                        "resource": canonical_value_to_data(item.resource),
                        "logical_type": {
                            "id": item.logical_type.id,
                            "version": item.logical_type.version,
                        },
                    }
                    for item in sorted(value.inputs, key=lambda item: item.name)
                ],
                "outputs": [
                    {
                        "name": item.name,
                        "logical_type": {
                            "id": item.logical_type.id,
                            "version": item.logical_type.version,
                        },
                        "semantic_ids": list(item.semantic_ids),
                        "required": item.required,
                    }
                    for item in sorted(value.outputs, key=lambda item: item.name)
                ],
            }
        )
    return result


def computation_request_from_data(raw: object) -> ComputationRequest:
    from code_visualizer.persistence.values import array_data, object_data, text_data

    if not isinstance(raw, dict):
        raise ValueError("A computation request requires its complete typed fields")
    extended = "version" in raw
    if extended and (type(raw["version"]) is not int or raw["version"] != 2):
        raise ValueError("Unsupported computation request version")
    if set(raw) != {
        "project_id",
        "revision",
        "backend_id",
        "backend_version",
        "model_id",
        "configuration",
        "seed",
        "resources",
    } | ({"version", "inputs", "outputs"} if extended else set()):
        raise ValueError("A computation request requires its complete typed fields")
    if any(
        not isinstance(raw[name], str) for name in ("project_id", "backend_id", "backend_version")
    ):
        raise ValueError("Computation identities must be text")
    if type(raw["revision"]) is not int:
        raise ValueError("Computation revision must be an integer")
    if raw["model_id"] is not None and not isinstance(raw["model_id"], str):
        raise ValueError("Computation model_id must be text or absent")
    if raw["seed"] is not None and type(raw["seed"]) is not int:
        raise ValueError("Computation seed must be an integer or absent")
    if not isinstance(raw["configuration"], list) or not isinstance(raw["resources"], list):
        raise ValueError("Computation configuration and resources must be arrays")
    parameters = []
    for item in raw["configuration"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "value"}
            or not isinstance(item["name"], str)
        ):
            raise ValueError("A computation parameter requires a name and typed value")
        parameters.append(
            ComputationParameter(item["name"], canonical_value_from_data(item["value"]))
        )
    resources = []
    for item in raw["resources"]:
        reference = canonical_value_from_data(item)
        if not isinstance(reference, ResourceReference):
            raise ValueError("Computation resources must be typed resource references")
        resources.append(reference)
    inputs, outputs = [], []

    def logical_type(value: object) -> ResourceLogicalTypeReference:
        fields = object_data(value, {"id", "version"})
        return ResourceLogicalTypeReference(
            text_data(fields.get("id")), text_data(fields.get("version"))
        )

    for value in array_data(raw.get("inputs", [])):
        item = object_data(value, {"name", "resource", "logical_type"})
        resource = canonical_value_from_data(item.get("resource"))
        if not isinstance(resource, ResourceReference):
            raise ValueError("A named input requires an exact resource reference")
        inputs.append(
            ResourceInput(
                text_data(item.get("name")), resource, logical_type(item.get("logical_type"))
            )
        )
    for value in array_data(raw.get("outputs", [])):
        item = object_data(value, {"name", "logical_type", "semantic_ids", "required"})
        if type(item.get("required")) is not bool:
            raise ValueError("An output requires its completion policy")
        required = item["required"]
        assert isinstance(required, bool)
        outputs.append(
            ResourceOutput(
                text_data(item.get("name")),
                logical_type(item.get("logical_type")),
                tuple(text_data(v) for v in array_data(item.get("semantic_ids"))),
                required,
            )
        )
    if extended and not (inputs or outputs):
        raise ValueError("Empty resource declarations use the historical request encoding")
    return ComputationRequest(
        raw["project_id"],
        raw["revision"],
        raw["backend_id"],
        raw["backend_version"],
        raw["model_id"],
        tuple(parameters),
        raw["seed"],
        tuple(resources),
        tuple(inputs),
        tuple(outputs),
    )
