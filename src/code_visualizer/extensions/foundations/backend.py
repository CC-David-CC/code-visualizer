"""Bounded numerical interpretation of indexed equations, without program lowering."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterator, Mapping

from code_visualizer.domain.computation import BackendCapabilities, BackendDefinition
from code_visualizer.domain.evidence import (
    ComputationOutcome,
    EvidenceDiagnostic,
    EvidenceObservation,
)
from code_visualizer.domain.intentional import DomainModel, IntentionalNode
from code_visualizer.domain.resources import (
    ResourceAxis,
    ResourceLogicalTypeReference,
    TensorDescriptor,
)
from code_visualizer.domain.values import ResourceReference, TensorDType, TensorValue
from code_visualizer.execution.backends import (
    BackendResult,
    PreparedComputation,
    ProducedResource,
    RegisteredBackend,
)
from code_visualizer.extensions.foundations.math import (
    REPRESENTATION,
    SCHEMA_ID,
    identity,
    tensor_shape,
)

BACKEND_ID = "foundation.math.indexed_equations"
TENSOR_MEDIA_TYPE = "application/vnd.codevisualizer.tensor-float64-le"


def _coordinates(shape: tuple[int, ...]) -> Iterator[tuple[int, ...]]:
    """Iterate without pooling axes, including enormous empty tensor dimensions."""
    if any(size == 0 for size in shape):
        return
    indices = [0] * len(shape)
    while True:
        yield tuple(indices)
        for axis in range(len(shape) - 1, -1, -1):
            indices[axis] += 1
            if indices[axis] < shape[axis]:
                break
            indices[axis] = 0
        else:
            return


class MathematicalEvaluationError(ValueError):
    def __init__(self, code: str, message: str, semantic_id: str) -> None:
        self.code, self.semantic_id = code, semantic_id
        super().__init__(message)


class _Evaluator:
    def __init__(self, prepared: PreparedComputation, model: DomainModel) -> None:
        self.prepared = prepared
        self.model = model
        self.nodes = {
            node.id: node
            for candidate in prepared.project.domain_workspace.models
            for node in candidate.nodes
        }
        self.nodes.update((node.id, node) for node in model.nodes)
        self.remaining = 100_000
        self.used: set[str] = set()
        self.extents: dict[str, int] = {}
        self.tensors: dict[str, TensorValue] = {}

    def fail(self, code: str, message: str, node: IntentionalNode) -> None:
        raise MathematicalEvaluationError(code, message, node.id)

    def node(self, node_id: str) -> IntentionalNode:
        if node_id not in self.nodes:
            raise MathematicalEvaluationError(
                "MATH_REFERENCE", "Mathematical identity is unavailable", node_id
            )
        self.used.add(node_id)
        return self.nodes[node_id]

    def one(self, node: IntentionalNode, role: str, *, child: bool = False) -> IntentionalNode:
        ids = node.child_ids(role) if child else node.reference_ids(role)
        if len(ids) != 1:
            self.fail("MATH_INCOMPLETE", "This mathematical role requires exactly one object", node)
        return self.node(ids[0])

    def tensor(self, symbol: IntentionalNode, *, required: bool = True) -> TensorValue | None:
        if symbol.id in self.tensors:
            return self.tensors[symbol.id]
        ids = symbol.reference_ids(identity("TensorSymbol", "binding"))
        if not ids:
            if required:
                self.fail(
                    "MATH_UNBOUND_TENSOR",
                    "A numerical input tensor requires an explicit binding",
                    symbol,
                )
            return None
        bound = self.node(ids[0])
        value = bound.property(identity("TensorLiteral", "value"))
        if bound.concept_id == identity("ResourceLiteral"):
            reference = bound.property(identity("ResourceLiteral", "value"))
            if not isinstance(reference, ResourceReference):
                self.fail(
                    "MATH_RESOURCE", "A tensor resource needs a canonical resource reference", bound
                )
            resources = [
                resource
                for resource in self.prepared.resources
                if resource.descriptor.reference == reference
            ]
            if len(resources) != 1:
                self.fail(
                    "MATH_RESOURCE",
                    "The tensor resource was not explicitly resolved for this computation",
                    bound,
                )
            resource = resources[0]
            descriptor = resource.descriptor.tensor
            if (
                descriptor is None
                or descriptor.dtype is not TensorDType.FLOAT64
                or resource.descriptor.media_type != TENSOR_MEDIA_TYPE
            ):
                self.fail(
                    "MATH_RESOURCE_FORMAT",
                    "This backend consumes declared little-endian float64 tensor resources",
                    bound,
                )
            assert descriptor is not None
            if descriptor.unit is not None:
                self.fail(
                    "MATH_UNIT_UNSUPPORTED",
                    "This backend requires dimensionless tensors; unit algebra is not implemented",
                    bound,
                )
            if resource.data is None:
                self.fail(
                    "MATH_RESOURCE_SIZE",
                    "This bounded evaluator requires an in-memory tensor input",
                    bound,
                )
            assert resource.data is not None
            if len(resource.data) != math.prod(descriptor.shape) * 8:
                self.fail(
                    "MATH_RESOURCE_SIZE",
                    "Resource bytes do not match the declared tensor shape",
                    bound,
                )
            value = TensorValue(
                TensorDType.FLOAT64,
                descriptor.shape,
                tuple(item[0] for item in struct.iter_unpack("<d", resource.data)),
            )
        if not isinstance(value, TensorValue):
            self.fail("MATH_TENSOR_VALUE", "Tensor bindings must resolve to a tensor value", bound)
        assert isinstance(value, TensorValue)
        if value.dtype in {TensorDType.BOOL, TensorDType.COMPLEX64, TensorDType.COMPLEX128}:
            self.fail(
                "MATH_DTYPE", "This numerical backend supports real and integer tensors", bound
            )
        declared = tensor_shape(symbol)
        if declared is not None and declared != value.shape:
            self.fail(
                "MATH_TENSOR_BINDING_SHAPE",
                "Tensor binding and declaration have different shapes",
                symbol,
            )
        self.tensors[symbol.id] = value
        return value

    def shape(self, symbol: IntentionalNode) -> tuple[int, ...]:
        declared = tensor_shape(symbol)
        value = self.tensor(symbol, required=False)
        shape = declared if declared is not None else value.shape if value else None
        if shape is None:
            self.fail("MATH_TENSOR_SHAPE", "Numerical tensors require a known shape", symbol)
        assert shape is not None
        return shape

    def collect(self, node: IntentionalNode, depth: int = 0) -> None:
        self.charge(node, depth)
        if node.concept_id == identity("Index"):
            symbol = self.one(node, identity("Index", "tensor"))
            shape = self.shape(symbol)
            indices = node.child_ids(identity("Index", "indices"))
            if len(indices) != len(shape):
                self.fail("MATH_INDEX_RANK", "Tensor rank and index count differ", node)
            for index_id, size in zip(indices, shape, strict=True):
                index = self.node(index_id)
                if index.concept_id == identity("SymbolReference"):
                    variable = self.one(index, identity("SymbolReference", "symbol"))
                    previous = self.extents.setdefault(variable.id, size)
                    if previous != size:
                        self.fail(
                            "MATH_INDEX_DIMENSION",
                            "An index has incompatible extents in the equation",
                            index,
                        )
        for role in node.children:
            for child in role.node_ids:
                self.collect(self.node(child), depth + 1)

    def charge(self, node: IntentionalNode, depth: int) -> None:
        self.remaining -= 1
        if self.remaining < 0 or depth > 64:
            self.fail(
                "MATH_BUDGET",
                "Numerical evaluation exceeded 100000 steps or 64 expression levels",
                node,
            )

    def number(
        self, node: IntentionalNode, environment: Mapping[str, int], depth: int = 0
    ) -> float:
        self.charge(node, depth)
        concept = node.concept_id
        if concept == identity("Literal"):
            value = node.property(identity("Literal", "value"))
            if type(value) not in {int, float}:
                self.fail("MATH_LITERAL", "This backend requires a real scalar literal", node)
            assert isinstance(value, (int, float))
            result = float(value)
        elif concept == identity("SymbolReference"):
            symbol = self.one(node, identity("SymbolReference", "symbol"))
            if symbol.id in environment:
                return float(environment[symbol.id])
            result = self.number(
                self.one(symbol, identity("Symbol", "binding")), environment, depth + 1
            )
        elif concept == identity("Index"):
            symbol = self.one(node, identity("Index", "tensor"))
            tensor = self.tensor(symbol)
            assert tensor is not None
            indices = [
                self.number(self.node(item), environment, depth + 1)
                for item in node.child_ids(identity("Index", "indices"))
            ]
            if len(indices) != len(tensor.shape):
                self.fail("MATH_INDEX_RANK", "Tensor rank and index count differ", node)
            offset = 0
            for index, size in zip(indices, tensor.shape, strict=True):
                if not index.is_integer() or not 0 <= index < size:
                    self.fail(
                        "MATH_INDEX_BOUNDS", "A tensor index is outside its declared extent", node
                    )
                offset = offset * size + int(index)
            element = tensor.elements[offset]
            assert isinstance(element, (int, float))
            result = float(element)
        elif concept == identity("OperatorApplication"):
            operator = node.property(identity("OperatorApplication", "operator"))
            operands = tuple(
                self.node(item)
                for item in node.child_ids(identity("OperatorApplication", "operands"))
            )
            if operator == "sum":
                binders = node.reference_ids(identity("OperatorApplication", "bound_symbols"))
                if (
                    len(operands) != 1
                    or not binders
                    or any(item not in self.extents for item in binders)
                ):
                    self.fail(
                        "MATH_SUM_BINDER",
                        "A sum needs a body and bound symbols with known finite extents",
                        node,
                    )
                if any(item in environment for item in binders):
                    self.fail(
                        "MATH_BINDER_SCOPE", "A sum cannot rebind an active index declaration", node
                    )
                result = 0.0
                for coordinate in _coordinates(tuple(self.extents[item] for item in binders)):
                    scope = {**environment, **dict(zip(binders, coordinate, strict=True))}
                    result += self.number(operands[0], scope, depth + 1)
            else:
                values = tuple(self.number(item, environment, depth + 1) for item in operands)
                if operator == "negate" and len(values) == 1:
                    result = -values[0]
                elif len(values) == 2 and operator in {"add", "subtract", "multiply", "divide"}:
                    left, right = values
                    if operator == "add":
                        result = left + right
                    elif operator == "subtract":
                        result = left - right
                    elif operator == "multiply":
                        result = left * right
                    elif right != 0.0:
                        result = left / right
                    else:
                        self.fail("MATH_DIVISION_ZERO", "Division by zero", node)
                        raise AssertionError
                else:
                    self.fail(
                        "MATH_OPERATOR_UNSUPPORTED",
                        "This backend does not interpret that operator or arity",
                        node,
                    )
                    raise AssertionError
        else:
            self.fail(
                "MATH_EXPRESSION_UNSUPPORTED",
                "This backend does not interpret this mathematical concept",
                node,
            )
            raise AssertionError
        if not math.isfinite(result):
            self.fail("MATH_NONFINITE", "Numerical evaluation produced a nonfinite value", node)
        return result

    def equation(
        self, equation: IntentionalNode, sequence: int
    ) -> tuple[EvidenceObservation, ProducedResource]:
        self.used = {equation.id}
        self.extents = {}
        self.tensors = {}
        left = self.one(equation, identity("Equation", "left"), child=True)
        right = self.one(equation, identity("Equation", "right"), child=True)
        if left.concept_id != identity("Index"):
            self.fail(
                "MATH_OUTPUT",
                "This backend evaluates an equation with an indexed tensor on its left",
                equation,
            )
        output = self.one(left, identity("Index", "tensor"))
        shape = self.shape(output)
        self.collect(equation)
        free: list[str] = []
        for item in left.child_ids(identity("Index", "indices")):
            index = self.node(item)
            if index.concept_id != identity("SymbolReference"):
                self.fail(
                    "MATH_OUTPUT_INDEX",
                    "Output axes require explicit index symbol occurrences",
                    index,
                )
            free.append(self.one(index, identity("SymbolReference", "symbol")).id)
        if len(set(free)) != len(free):
            self.fail("MATH_OUTPUT_INDEX", "Output axes must use distinct free index symbols", left)
        if math.prod(shape) > 1024:
            self.fail(
                "MATH_OUTPUT_SIZE",
                "This bounded numerical backend produces at most 1024 elements",
                output,
            )
        values = tuple(
            self.number(right, dict(zip(free, coordinate, strict=True)))
            for coordinate in _coordinates(shape)
        )
        value = TensorValue(TensorDType.FLOAT64, shape, values)
        semantic_ids = tuple(sorted(self.used))
        label = str(equation.property(identity("Equation", "name")) or equation.id)
        observation = EvidenceObservation(
            f"{equation.id}:result", semantic_ids, value, label, sequence
        )
        axes = tuple(
            ResourceAxis(str(self.node(item).property(identity("Symbol", "name")) or item), item)
            for item in free
        )
        artifact = ProducedResource(
            f"{equation.id}:tensor",
            struct.pack(f"<{len(values)}d", *values),
            TENSOR_MEDIA_TYPE,
            semantic_ids,
            label,
            TensorDescriptor(value.dtype, shape, axes),
            ResourceLogicalTypeReference("foundation.math.tensor", "1"),
        )
        return observation, artifact


def evaluate_indexed_equations(prepared: PreparedComputation) -> BackendResult:
    if not isinstance(prepared.value, DomainModel) or prepared.value.schema_id != SCHEMA_ID:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    "MATH_SCHEMA", "The mathematical backend requires its exact schema"
                ),
            ),
        )
    evaluator = _Evaluator(prepared, prepared.value)
    configuration = {item.name: item.value for item in prepared.request.configuration}
    if set(configuration) - {"equation_id"} or (
        "equation_id" in configuration and not isinstance(configuration["equation_id"], str)
    ):
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic(
                    "MATH_CONFIGURATION", "Optional equation_id must identify one equation"
                ),
            ),
        )
    equations = tuple(
        sorted(
            (
                node
                for node in prepared.value.nodes
                if node.concept_id == identity("Equation")
                and ("equation_id" not in configuration or node.id == configuration["equation_id"])
            ),
            key=lambda node: node.id,
        )
    )
    if not equations:
        return BackendResult(
            ComputationOutcome.FAILED,
            diagnostics=(
                EvidenceDiagnostic("MATH_EQUATION", "No requested mathematical equation exists"),
            ),
        )
    observations = []
    resources = []
    try:
        for sequence, equation in enumerate(equations):
            observation, resource = evaluator.equation(equation, sequence)
            observations.append(observation)
            resources.append(resource)
    except MathematicalEvaluationError as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            tuple(observations),
            diagnostics=(EvidenceDiagnostic(exc.code, str(exc), (exc.semantic_id,)),),
        )
    except (OverflowError, ValueError, struct.error) as exc:
        return BackendResult(
            ComputationOutcome.FAILED,
            tuple(observations),
            diagnostics=(
                EvidenceDiagnostic("MATH_NUMERIC", str(exc), tuple(sorted(evaluator.used))),
            ),
        )
    return BackendResult(observations=tuple(observations), produced_resources=tuple(resources))


def math_backend() -> RegisteredBackend:
    return RegisteredBackend(
        BackendDefinition(
            BACKEND_ID,
            "1",
            "Indexed tensor equations",
            REPRESENTATION,
            SCHEMA_ID,
            "1",
            "Evaluate finite indexed sums directly; no program lowering or generated code.",
            capabilities=BackendCapabilities(deterministic=True),
        ),
        evaluate_indexed_equations,
    )
