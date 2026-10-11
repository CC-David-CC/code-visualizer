"""Top-level aggregate for the current native development format."""

from __future__ import annotations

from dataclasses import dataclass, field

from code_visualizer.config import PRODUCT
from code_visualizer.domain.assets import ManagedAsset, ShapePackReference
from code_visualizer.domain.authoring import AuthoredSemanticRelation, SemanticConcept
from code_visualizer.domain.common import ExtensionField
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.freeform import FreeformDiagram
from code_visualizer.domain.intentional import DomainWorkspace
from code_visualizer.domain.mindmap import MindMapDiagram
from code_visualizer.domain.program import ProgramModel
from code_visualizer.domain.projection import DrakonViewDefinition, ProjectionDefinition

type ProjectDocument = DrakonDiagram | MindMapDiagram | FreeformDiagram


@dataclass(frozen=True, slots=True)
class EnvironmentVariable:
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class RunProfile:
    name: str = "Default"
    interpreter: str = ""
    working_directory: str = "."
    arguments: str = ""
    environment: tuple[EnvironmentVariable, ...] = ()


@dataclass(frozen=True, slots=True)
class PythonRuntimeSettings:
    """Non-executable Python runtime preferences; program declarations live in ProgramModel."""

    run_profiles: tuple[RunProfile, ...] = (RunProfile(),)
    active_run_profile: str = "Default"


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    title: str
    documents: tuple[ProjectDocument, ...]
    revision: int = 0
    description: str = ""
    runtime_settings: PythonRuntimeSettings = PythonRuntimeSettings()
    managed_assets: tuple[ManagedAsset, ...] = ()
    shape_packs: tuple[ShapePackReference, ...] = ()
    concepts: tuple[SemanticConcept, ...] = ()
    semantic_relations: tuple[AuthoredSemanticRelation, ...] = ()
    projection_definitions: tuple[ProjectionDefinition, ...] = ()
    program_model: ProgramModel = field(default_factory=ProgramModel)
    drakon_views: tuple[DrakonViewDefinition, ...] = ()
    domain_workspace: DomainWorkspace = field(default_factory=DomainWorkspace)
    extensions: tuple[ExtensionField, ...] = ()
    format_revision: int = PRODUCT.project_format_revision
