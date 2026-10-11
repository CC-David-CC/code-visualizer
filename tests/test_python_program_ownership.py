from dataclasses import replace

import pytest

from code_visualizer.application.project_factory import create_default_project
from code_visualizer.domain.program import (
    ProgramAction,
    ProgramAssignment,
    ProgramClass,
    ProgramFunctionReference,
    ProgramImport,
    ProgramModel,
    ProgramModule,
    ProgramTypeAlias,
    program_expressions,
)
from code_visualizer.domain.program_ownership import place_program_function
from code_visualizer.domain.project import Project
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.generation import generate_python_project
from code_visualizer.validation import validate_integrity, validate_project


def test_python_text_admission_retains_order_and_complete_class_structure():
    source = '''import collections as co
a = b = 7
type Pair[T] = tuple[T, T]
@decorate
class Holder[T](Base, metaclass=Meta):
    """An explicitly owned class."""
    threshold = 3
    def get(self):
        return self.threshold
after = Holder
'''
    body = parse_python_declarations("module:test", source, identity_namespace="import")
    assert [type(item) for item in body] == [
        ProgramImport,
        ProgramAssignment,
        ProgramTypeAlias,
        ProgramClass,
        ProgramAssignment,
    ]
    assert body[1].target.source == "a = b"
    cls = body[3]
    assert isinstance(cls, ProgramClass)
    assert cls.identifier == "Holder"
    assert cls.arguments.source == "Base, metaclass=Meta"
    assert cls.decorators[0].source == "decorate"
    assert cls.docstring == "An explicitly owned class."
    assert len(cls.type_parameters) == 1
    assert isinstance(cls.body[1], ProgramAction)
    assert "def get(self):" in cls.body[1].source.source
    assert parse_python_declarations("module:test", source, identity_namespace="import") == body


def test_module_and_class_rename_preserve_owned_function_identity():
    project = create_default_project()
    function = project.program_model.functions[0]
    model = place_program_function(project.program_model, function.id, "workers", "Worker")
    module = model.module_for(function.id)
    cls = model.class_for(function.id)
    assert module is not None and cls is not None
    renamed_class = replace(cls, identifier="Renamed")
    renamed_module = replace(module, path="processing", body=(renamed_class,))
    renamed = replace(
        model,
        modules=tuple(renamed_module if item.id == module.id else item for item in model.modules),
    )
    assert renamed.function(function.id) is function
    assert renamed.module_for(function.id).id == module.id
    assert renamed.class_for(function.id).id == cls.id
    assert renamed.module_path_for(function.id) == "processing"
    assert renamed.class_name_for(function.id) == "Renamed"
    assert not validate_integrity(
        replace(project, documents=(), drakon_views=(), program_model=renamed)
    )


@pytest.mark.parametrize(
    "case,code",
    [
        ("unowned", "PROGRAM_UNOWNED_FUNCTION"),
        ("duplicate", "PROGRAM_DUPLICATE_FUNCTION_OWNER"),
        ("dangling", "PROGRAM_UNRESOLVED_FUNCTION_REFERENCE"),
        ("scope_collision", "PROGRAM_DUPLICATE_OWNERSHIP"),
    ],
)
def test_invalid_declaration_ownership_is_explicit(case, code):
    project = create_default_project()
    model = project.program_model
    module = model.modules[0]
    function = model.functions[0]
    if case == "unowned":
        body = ()
    elif case == "duplicate":
        body = (ProgramFunctionReference(function.id), ProgramFunctionReference(function.id))
    elif case == "dangling":
        body = (*module.body, ProgramFunctionReference("missing"))
    else:
        body = (*module.body, ProgramClass(module.id, "Collision"))
    invalid = replace(project, program_model=replace(model, modules=(replace(module, body=body),)))
    assert code in {item.code for item in validate_integrity(invalid)}


def test_module_only_python_is_canonical_and_buildable():
    body = parse_python_declarations("module:standalone", "answer = 7\nprint(answer)")
    model = ProgramModel(modules=(ProgramModule("module:standalone", "values", body),))
    project = Project("project:standalone", "Standalone Python", (), program_model=model)
    assert not validate_project(project)
    generated = generate_python_project(project)
    assert "answer = 7" in generated.file("app/values.py").source
    assert "print(answer)" in generated.file("app/values.py").source
    assert project.program_model is model


def test_incomplete_module_source_is_preserved_but_not_buildable():
    source = "if missing:"
    body = parse_python_declarations("module:incomplete", source)
    project = Project(
        "project:incomplete",
        "Incomplete",
        (),
        program_model=ProgramModel(
            modules=(ProgramModule("module:incomplete", "main", body),),
        ),
    )
    assert next(program_expressions(body)).source == source
    assert not validate_integrity(project)
    assert "PROGRAM_INCOMPLETE_EXPRESSION" in {item.code for item in validate_project(project)}
