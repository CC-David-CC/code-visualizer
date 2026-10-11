"""Static composition of resource readers and typed cell-consumer authoring.

The shared UI only sees prepared cells. A registered adapter interprets its own
resource contract and prepares commands; neither the renderer nor the kernel
infers physics or edits from pixels.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache

from code_visualizer.application.cell_artifacts import PreparedCellProbe
from code_visualizer.domain.preview import PreviewEvent
from code_visualizer.domain.project import Project
from code_visualizer.domain.resources import ResourceLogicalTypeReference
from code_visualizer.domain.values import ResourceReference
from code_visualizer.extensions.foundations.cell_presentation import CellPresentation, CellReader
from code_visualizer.extensions.registry import DomainExtensionRegistry
from code_visualizer.persistence.computation_resources import resolve_computation_resource
from code_visualizer.persistence.resource_store import ResourceStore

type ProbeFactory = Callable[
    [
        Project,
        DomainExtensionRegistry,
        ResourceStore,
        ResourceStore,
        ResourceReference,
        int,
        int,
        str,
        str,
    ],
    PreparedCellProbe,
]


@dataclass(frozen=True, slots=True)
class CellPresentationAdapter:
    history_type: ResourceLogicalTypeReference
    preview_type: ResourceLogicalTypeReference
    reader: Callable[[], CellReader]
    probe: ProbeFactory


@cache
def builtin_cell_adapters() -> tuple[CellPresentationAdapter, ...]:
    from code_visualizer.application.adaptive_artifacts import prepare_probe as adaptive_probe
    from code_visualizer.application.gas_artifacts import prepare_probe as gas_probe
    from code_visualizer.extensions.adaptive_fields.presentation import CellPresentationReader
    from code_visualizer.extensions.adaptive_fields.records import HISTORY_TYPE, PREVIEW_TYPE
    from code_visualizer.extensions.gas_observation.presentation import GasPresentationReader
    from code_visualizer.extensions.hybrid_gas.preview import PREVIEW_TYPE as GAS_PREVIEW
    from code_visualizer.extensions.hybrid_gas.records import HISTORY_TYPE as GAS_HISTORY

    return (
        CellPresentationAdapter(HISTORY_TYPE, PREVIEW_TYPE, CellPresentationReader, adaptive_probe),
        CellPresentationAdapter(GAS_HISTORY, GAS_PREVIEW, GasPresentationReader, gas_probe),
    )


def supports_preview(preview: PreviewEvent) -> bool:
    return any(a.preview_type == preview.interpretation for a in builtin_cell_adapters())


def prepare_probe(
    project: Project,
    registry: DomainExtensionRegistry,
    source_store: ResourceStore,
    target_store: ResourceStore,
    history: ResourceReference,
    sample: int,
    epoch: int,
    cell_id: str,
    component_id: str,
) -> PreparedCellProbe:
    kind = source_store.describe(history).logical_type
    adapter = next((a for a in builtin_cell_adapters() if a.history_type == kind), None)
    if adapter is None:
        raise ValueError("No cell consumer is registered for this resource interpretation")
    return adapter.probe(
        project, registry, source_store, target_store, history, sample, epoch, cell_id, component_id
    )


class CellPresentationReader:
    """One bounded reader/cache, selected off-thread by the exact resource type."""

    def __init__(self, adapters: tuple[CellPresentationAdapter, ...] | None = None):
        self.adapters = builtin_cell_adapters() if adapters is None else adapters
        if len({a.history_type for a in self.adapters}) != len(self.adapters):
            raise ValueError("Ambiguous cell presentation registration")
        self._reader: CellReader | None = None
        self._adapter: CellPresentationAdapter | None = None

    @property
    def cache_bytes(self) -> int:
        return self._reader.cache_bytes if self._reader is not None else 0

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
        self._reader, self._adapter = None, None

    def _history(
        self,
        root: ResourceReference,
        store: ResourceStore,
        registry: DomainExtensionRegistry,
    ) -> ResourceReference | None:
        types = {a.history_type for a in self.adapters}
        descriptor = store.describe(root)
        if descriptor.logical_type in types:
            return root
        interpreter = (
            registry.resource_interpretation(descriptor.logical_type)
            if descriptor.logical_type
            else None
        )
        if interpreter is None or descriptor.byte_size > interpreter.metadata_limit:
            return None
        histories = tuple(
            d.reference
            for d in interpreter.dependencies(store.read(root))
            if d.logical_type in types
        )
        if len(histories) > 1:
            raise ValueError("This artifact does not contain one cell history")
        return histories[0] if histories else None

    def prepare(
        self,
        root: ResourceReference,
        store: ResourceStore,
        registry: DomainExtensionRegistry,
        context: object,
        sample: int | None = None,
        component_id: str | None = None,
        *,
        preview: PreviewEvent | None = None,
        session_id: str = "",
        input_digest: str = "",
        cancelled: Callable[[], bool] = lambda: False,
        alternatives: tuple[ResourceReference, ...] = (),
    ) -> CellPresentation:
        # A computation can publish several output kinds. Search its explicit
        # newest-first receipt snapshot off-thread; only registered dependencies
        # can identify a history. A malformed candidate is never hidden by fallback.
        for candidate in (root, *alternatives):
            if cancelled():
                raise InterruptedError("Cell presentation was superseded")
            history = self._history(candidate, store, registry)
            if history is not None:
                root = history
                break
        else:
            raise ValueError("Select a retained cell history or its checkpoint")
        descriptor = store.describe(root)
        adapter = next(a for a in self.adapters if a.history_type == descriptor.logical_type)
        if self._adapter != adapter:
            self.close()
            self._reader, self._adapter = adapter.reader(), adapter
        assert self._reader is not None
        return self._reader.prepare(
            root,
            lambda ref: resolve_computation_resource(store, ref, file_backed=True),
            context,
            sample,
            component_id,
            preview=preview,
            session_id=session_id,
            input_digest=input_digest,
            cancelled=cancelled,
        )
