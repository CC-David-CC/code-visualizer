import json
from dataclasses import replace

import pytest

from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.project import Project
from code_visualizer.persistence.decoding import ProjectDecodeError, project_from_json
from code_visualizer.persistence.serialization import normalized_project_json


def test_current_format_round_trip_preserves_normalized_snapshot() -> None:
    project = create_default_project(title="Round Trip")

    decoded = project_from_json(normalized_project_json(project))

    assert normalized_project_json(decoded) == normalized_project_json(project)


def test_decoder_rejects_an_obsolete_development_format() -> None:
    raw = json.loads(normalized_project_json(create_default_project()))
    raw["format_revision"] = 3

    with pytest.raises(ProjectDecodeError, match="FORMAT_UNSUPPORTED_REVISION"):
        project_from_json(json.dumps(raw))


def test_decoder_requires_the_current_format_revision_field() -> None:
    raw = json.loads(normalized_project_json(create_default_project()))
    del raw["format_revision"]

    with pytest.raises(ProjectDecodeError, match=r"FORMAT_MISSING_FIELD.*format_revision"):
        project_from_json(json.dumps(raw))


def test_decoder_rejects_unresolved_entrypoint() -> None:
    project = create_default_project()
    invalid = replace(
        project,
        program_model=replace(
            project.program_model,
            entrypoint=replace(project.program_model.entrypoint, callable_id="missing"),
        ),
    )

    with pytest.raises(ProjectDecodeError, match="PROJECT_UNRESOLVED_ENTRYPOINT"):
        project_from_json(normalized_project_json(invalid))


def test_decoder_rejects_duplicate_document_ids() -> None:
    project = create_default_project()
    invalid = Project(
        id=project.id,
        title=project.title,
        documents=(project.documents[0], project.documents[0]),
        runtime_settings=project.runtime_settings,
    )

    with pytest.raises(ProjectDecodeError, match="DOC_DUPLICATE_ID"):
        project_from_json(normalized_project_json(invalid))
