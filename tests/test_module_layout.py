from dataclasses import replace

import pytest

from code_visualizer.application.messages import CommandAccepted
from code_visualizer.application.session import ProjectSession
from code_visualizer.domain.drakon import DrakonDiagram
from code_visualizer.domain.module_paths import (
    PythonPathError,
    module_file_label,
    normalize_module_path,
    normalize_package_path,
    python_module_file_path,
)
from code_visualizer.domain.program import ProgramFunctionReference, ProgramModule
from code_visualizer.domain.project import Project
from code_visualizer.generation import GenerationError, generate_python_project
from code_visualizer.generation.emitter import emit_project
from code_visualizer.generation.lowering import lower_project
from code_visualizer.persistence import ProjectStore
from code_visualizer.validation import validate_project


def test_module_paths_accept_dotted_and_filesystem_forms_but_reject_escape_paths() -> None:
    assert normalize_package_path("company/product") == "company.product"
    assert normalize_module_path("math.vectors") == "math.vectors"
    assert normalize_module_path("math/vectors.py") == "math.vectors"
    assert normalize_module_path(r"math\vectors.py") == "math.vectors"
    assert module_file_label("math.vectors") == "math/vectors.py"
    assert python_module_file_path("bci", "math/vectors.py") == "bci/math/vectors.py"

    for unsafe in ("../escape.py", "/absolute.py", r"C:\absolute.py", "math//vectors.py"):
        with pytest.raises(PythonPathError):
            normalize_module_path(unsafe)
    with pytest.raises(PythonPathError):
        normalize_module_path("math/class.py")


def test_commands_canonicalize_filesystem_paths_and_persist_the_nested_layout(tmp_path) -> None:
    session = ProjectSession.new()
    try:
        initial = session.authority.snapshot()
        main = initial.documents[0]
        original_module = initial.program_model.modules[0]
        target = ProgramModule("module:vectors", "math/vectors.py")
        assert isinstance(
            session.client.configure_program(
                "company/product",
                (original_module, target),
                initial.program_model.entrypoint,
            ),
            CommandAccepted,
        )
        assert isinstance(
            session.client.set_function_owner(main.id, target.id),
            CommandAccepted,
        )
        assert isinstance(session.client.delete_program_module(original_module.id), CommandAccepted)
        project = session.authority.snapshot()
        assert project.program_model.package == "company.product"
        assert project.program_model.modules[0].path == "math.vectors"
        document = project.documents[0]
        assert isinstance(document, DrakonDiagram)
        assert document.header.function.module == "math.vectors"
        assert not validate_project(project)

        generated = generate_python_project(project)
        assert generated.file("company/product/math/vectors.py").path.endswith("vectors.py")
        assert generated.file("company/product/math/__init__.py").source

        root = tmp_path / "nested-native-project"
        session.save_as(root)
        recovered = ProjectStore(root).recover(promote=False)
        assert recovered.program_model.package == "company.product"
        assert recovered.program_model.modules[0].path == "math.vectors"
        recovered_main = recovered.documents[0]
        assert isinstance(recovered_main, DrakonDiagram)
        assert recovered_main.header.function.module == "math.vectors"
    finally:
        session.close()


def _project_with_modules(package: str, paths: tuple[str, ...]) -> Project:
    session = ProjectSession.new()
    try:
        project = session.authority.snapshot()
    finally:
        session.close()
    function = project.program_model.functions[0]
    return replace(
        project,
        program_model=replace(
            project.program_model,
            package=package,
            modules=tuple(
                ProgramModule(
                    f"module:{index}",
                    path,
                    (ProgramFunctionReference(function.id),) if index == 0 else (),
                )
                for index, path in enumerate(paths)
            ),
        ),
    )


@pytest.mark.parametrize(
    ("package", "paths", "expected_code"),
    (
        ("bci", ("math", "math.vectors"), "PY_MODULE_PACKAGE_COLLISION"),
        ("bci", ("Math.vectors", "math.vectors"), "PY_MODULE_PATH_CASE_COLLISION"),
        ("bci", ("math.__init__",), "PY_RESERVED_MODULE_PATH"),
        ("", ("run_project",), "PY_RESERVED_MODULE_PATH"),
        ("bci", ("../escape",), "PY_INVALID_MODULE_PATH"),
    ),
)
def test_validation_rejects_ambiguous_or_reserved_output_layouts(
    package: str,
    paths: tuple[str, ...],
    expected_code: str,
) -> None:
    project = _project_with_modules(package, paths)
    codes = {diagnostic.code for diagnostic in validate_project(project)}
    assert expected_code in codes


def test_emitter_refuses_a_module_that_is_also_a_package_prefix() -> None:
    project = _project_with_modules("bci", ("math", "math.vectors"))
    with pytest.raises(GenerationError, match="also a package prefix"):
        emit_project(lower_project(project))


def test_emitter_refuses_parent_directory_output_even_without_prevalidation() -> None:
    project = _project_with_modules("bci", ("../escape",))
    with pytest.raises(GenerationError, match="Unsafe Python module path"):
        emit_project(lower_project(project))
