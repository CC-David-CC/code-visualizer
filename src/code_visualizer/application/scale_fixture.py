"""Deterministic large-project fixtures used by performance and recovery gates."""

from __future__ import annotations

from dataclasses import replace

from code_visualizer.application.project_factory import (
    create_default_project,
    initialize_project_documents,
)
from code_visualizer.domain.drakon import Action, DrakonDiagram, End, Header, Sequence
from code_visualizer.domain.program import ProgramEntryPoint
from code_visualizer.domain.program_signatures import FunctionSpec
from code_visualizer.domain.project import Project


def build_scale_project(
    diagram_count: int = 500,
    *,
    atoms_per_diagram: int = 0,
) -> Project:
    if diagram_count < 1:
        raise ValueError("A scale fixture needs at least one diagram")
    if atoms_per_diagram < 0:
        raise ValueError("atoms_per_diagram must not be negative")
    documents = tuple(
        DrakonDiagram(
            f"diagram_scale_{index:04d}",
            f"Function {index:04d}",
            Header(
                f"header_scale_{index:04d}",
                FunctionSpec(
                    f"function_{index:04d}",
                    f"Function {index:04d}",
                ),
            ),
            Sequence(
                f"sequence_scale_{index:04d}",
                tuple(
                    Action(
                        f"atom_scale_{index:04d}_{atom_index:04d}",
                        f"value_{atom_index} = {atom_index}",
                    )
                    for atom_index in range(atoms_per_diagram)
                ),
            ),
            End(f"end_scale_{index:04d}"),
        )
        for index in range(diagram_count)
    )
    base = create_default_project(title=f"Scale Fixture ({diagram_count} diagrams)")
    return initialize_project_documents(
        replace(
            base,
            id=f"project_scale_{diagram_count}",
            program_model=replace(
                base.program_model,
                entrypoint=ProgramEntryPoint(f"entrypoint:scale:{diagram_count}", documents[0].id),
            ),
        ),
        documents,
    )
