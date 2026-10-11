"""Authentic pre-cutover payloads for tests of historical persistence only."""

from code_visualizer.domain.invocation_arguments import (
    UnresolvedInvocationArguments,
    render_invocation_arguments,
)
from code_visualizer.domain.program import ProgramAssignment, ProgramClass, ProgramFunctionReference
from code_visualizer.persistence.invocation import invocation_arguments_to_data
from code_visualizer.persistence.serialization import project_to_data


def legacy_project_data(project, revision=9):
    """Encode old ownership slots for fixtures whose module bodies contain callables.

    Tests with legacy module source populate its original setup fields explicitly;
    this helper does not pretend a current-format envelope is an old-format file.
    """
    raw = project_to_data(project)
    raw["module_setup"] = raw.pop("runtime_settings")
    model = project.program_model
    raw["format_revision"] = revision
    for function in raw["program_model"]["functions"]:
        function["module"] = model.module_path_for(function["id"])
        function["owning_class"] = model.class_name_for(function["id"])
        function.pop("type_parameters")
    for key in ("modules", "package", "entrypoint"):
        raw["program_model"].pop(key)

    def assert_callable_owners(body):
        for item in body:
            assert isinstance(item, (ProgramFunctionReference, ProgramClass))
            if isinstance(item, ProgramClass):
                assert not item.arguments and not item.decorators and not item.type_parameters
                assert_callable_owners(item.body)

    modules = []
    for module in model.modules:
        constants = [item for item in module.body if isinstance(item, ProgramAssignment)]
        assert_callable_owners(tuple(item for item in module.body if item not in constants))
        assert all(item.operator == "=" for item in constants)
        modules.append(
            {
                "path": module.path,
                "docstring": module.docstring,
                "imports": [],
                "constants": [
                    {
                        "name": item.target.source,
                        "expression": item.value.source,
                        "annotation": item.annotation.source
                        if item.annotation is not None
                        else None,
                    }
                    for item in constants
                ],
                "type_aliases": [],
                "declarations": "",
                "before_functions": "",
                "after_functions": "",
            }
        )
    arguments = model.entrypoint_arguments
    old_arguments = (
        arguments.text
        if isinstance(arguments, UnresolvedInvocationArguments)
        else render_invocation_arguments(arguments)
    )
    assert model.entrypoint is None or not model.entrypoint.startup
    raw["module_setup"].update(
        {
            "package": model.package,
            "modules": modules,
            "post_source": "",
            "entrypoint_callable_id": model.entrypoint_callable_id,
            "entrypoint_arguments": old_arguments
            if revision < 8
            else invocation_arguments_to_data(arguments),
        }
    )
    return raw
