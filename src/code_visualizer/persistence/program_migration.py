"""Explicit legacy Python ownership and module-kind load-boundary upgrades.

Legacy source is parsed exactly once. The result contains ordinary canonical
declarations, not a retained setup payload or a second executable model.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from code_visualizer.domain.common import JsonValue
from code_visualizer.domain.invocation_arguments import (
    InvocationArguments,
    configured_arguments_from_text,
)
from code_visualizer.domain.module_paths import (
    canonical_module_path,
    canonical_package_path,
    qualified_module_name,
)
from code_visualizer.domain.program import (
    ProgramClass,
    ProgramDeclaration,
    ProgramFunctionReference,
    ProgramModule,
)
from code_visualizer.domain.python_declarations import parse_python_declarations
from code_visualizer.persistence.invocation import invocation_arguments_to_data


def default_program_module_kinds(
    raw_program: object, path: str = "$.program_model"
) -> dict[str, JsonValue]:
    """Read old ordinary modules without discarding any unrecognized record fields.

    Used by pre-11 snapshots/history and the additive portable terminal-2 contract.
    Current author-state and command decoders require the explicit discriminator.
    """
    from code_visualizer.persistence.decoding import _array, _object, _required

    program = _object(raw_program, path)
    modules: list[JsonValue] = []
    for index, value in enumerate(_array(_required(program, "modules", path), f"{path}.modules")):
        module = _object(value, f"{path}.modules[{index}]")
        modules.append(cast(JsonValue, {"kind": "module", **module}))
    return {**cast(dict[str, JsonValue], program), "modules": modules}


def migrate_legacy_module_kind_operation(
    command_type: str, payload: dict[str, JsonValue], depth: int = 0
) -> tuple[str, dict[str, JsonValue]]:
    """Upgrade only the declared module/header slots in durable pre-11 history."""
    from code_visualizer.persistence.decoding import _array, _object, _string

    if depth > 32:
        raise ValueError("Legacy history operation exceeds nesting limits")
    if command_type == "transaction":
        operations: list[JsonValue] = []
        for raw in _array(payload.get("operations"), "operation.operations"):
            item = _object(raw, "operation")
            name, values = migrate_legacy_module_kind_operation(
                _string(item.get("command_type"), "operation.command_type"),
                cast(dict[str, JsonValue], _object(item.get("payload"), "operation.payload")),
                depth + 1,
            )
            operations.append(
                {**cast(dict[str, JsonValue], item), "command_type": name, "payload": values}
            )
        return command_type, {**payload, "operations": operations}
    if command_type == "program.configure":
        return command_type, default_program_module_kinds(payload, "operation.payload")
    if command_type == "program.module.put":
        converted = default_program_module_kinds({"modules": [payload.get("module")]})
        modules = cast(list[JsonValue], converted["modules"])
        return command_type, {**payload, "module": modules[0]}
    if command_type == "program.function.restore" and "program_header" in payload:
        return command_type, {
            **payload,
            "program_header": default_program_module_kinds(
                payload["program_header"], "operation.program_header"
            ),
        }
    return command_type, payload


def migrate_legacy_program_data(
    raw_program: object,
    raw_setup: object,
    *,
    project_id: str,
) -> dict[str, JsonValue]:
    """Allocate ownership and declaration identities without changing existing IDs."""
    # Local imports keep the current decoder independent of legacy formats.
    from code_visualizer.persistence.decoding import (
        _array,
        _nonempty_string,
        _object,
        _optional_string,
        _required,
        _string,
    )
    from code_visualizer.persistence.serialization import (
        program_declaration_to_data,
        program_module_to_data,
    )

    program = _object(raw_program, "$.program_model")
    setup = _object(raw_setup, "$.module_setup")
    package = canonical_package_path(_string(setup.get("package", "app"), "$.module_setup.package"))
    functions = tuple(
        _object(item, "$.program_model.functions")
        for item in _array(
            _required(program, "functions", "$.program_model"), "$.program_model.functions"
        )
    )
    scopes: dict[str, list[tuple[str, str | None]]] = {}
    migrated_functions: list[JsonValue] = []
    for item in functions:
        function_id = _nonempty_string(_required(item, "id", "function"), "function.id")
        path = canonical_module_path(
            _nonempty_string(_required(item, "module", "function"), "function.module")
        )
        class_name = _optional_string(item.get("owning_class"), "function.owning_class")
        scopes.setdefault(path, []).append((function_id, class_name))
        migrated_functions.append(
            cast(
                JsonValue,
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key not in {"module", "owning_class"}
                    },
                    "type_parameters": item.get("type_parameters", []),
                },
            )
        )

    modules: list[ProgramModule] = []
    legacy_modules = _array(_required(setup, "modules", "$.module_setup"), "$.module_setup.modules")
    configured = {
        canonical_module_path(_nonempty_string(_object(value, "module").get("path"), "module.path"))
        for value in legacy_modules
    }
    # Old lowering already materialized a default module for every function scope.
    # Preserve that executable behavior while removing the redundant setup list.
    legacy_modules.extend({"path": path} for path in scopes if path not in configured)
    for index, value in enumerate(legacy_modules):
        field = f"$.module_setup.modules[{index}]"
        module = _object(value, field)
        path = canonical_module_path(
            _nonempty_string(_required(module, "path", field), f"{field}.path")
        )
        # These were already public semantic identities in revisions 4-9.
        # Promote them into canonical IDs instead of invalidating saved anchors.
        module_id = f"module:{qualified_module_name(package, path)}"
        body: list[ProgramDeclaration] = []

        def append_source(
            role: str,
            source: str,
            *,
            target: list[ProgramDeclaration] = body,
            owner_id: str = module_id,
            module_path: str = path,
        ) -> None:
            target.extend(
                parse_python_declarations(
                    f"{owner_id}:{role}",
                    source,
                    identity_namespace=f"legacy:{project_id}:{module_path}:{role}",
                )
            )

        for position, raw in enumerate(_array(module.get("imports", []), f"{field}.imports")):
            item = _object(raw, f"{field}.imports[{position}]")
            imported = _nonempty_string(_required(item, "module", field), f"{field}.imports.module")
            name = _optional_string(item.get("name"), f"{field}.imports.name")
            alias = _optional_string(item.get("alias"), f"{field}.imports.alias")
            source = f"from {imported} import {name}" if name is not None else f"import {imported}"
            if alias is not None:
                source += f" as {alias}"
            append_source(f"import:{position}", source)
        for position, raw in enumerate(_array(module.get("constants", []), f"{field}.constants")):
            item = _object(raw, f"{field}.constants[{position}]")
            name = _nonempty_string(_required(item, "name", field), f"{field}.constants.name")
            expression = _string(
                _required(item, "expression", field), f"{field}.constants.expression"
            )
            annotation = _optional_string(item.get("annotation"), f"{field}.constants.annotation")
            target = f"{name}: {annotation}" if annotation else name
            append_source(f"constant:{position}", f"{target} = {expression}")
        for position, raw in enumerate(
            _array(module.get("type_aliases", []), f"{field}.type_aliases")
        ):
            item = _object(raw, f"{field}.type_aliases[{position}]")
            name = _nonempty_string(_required(item, "name", field), f"{field}.type_aliases.name")
            expression = _string(
                _required(item, "expression", field), f"{field}.type_aliases.expression"
            )
            append_source(f"alias:{position}", f"type {name} = {expression}")
        for role in ("declarations", "before_functions"):
            append_source(role, _string(module.get(role, ""), f"{field}.{role}"))

        owners: dict[str, list[ProgramFunctionReference]] = {}
        for function_id, class_name in scopes.get(path, ()):
            reference = ProgramFunctionReference(function_id)
            if class_name is None:
                body.append(reference)
            else:
                owners.setdefault(class_name, []).append(reference)
        body.extend(
            ProgramClass(f"class:{module_id}:{name}", name, tuple(references))
            for name, references in owners.items()
        )
        append_source(
            "after_functions",
            _string(module.get("after_functions", ""), f"{field}.after_functions"),
        )
        modules.append(
            ProgramModule(
                module_id,
                path,
                tuple(body),
                _string(module.get("docstring", ""), f"{field}.docstring"),
            )
        )

    arguments = setup.get(
        "entrypoint_arguments", invocation_arguments_to_data(InvocationArguments())
    )
    entrypoint_id = f"entrypoint:{project_id}"
    startup = parse_python_declarations(
        f"{entrypoint_id}:startup",
        _string(setup.get("post_source", ""), "$.module_setup.post_source"),
        identity_namespace=f"legacy:{project_id}:startup",
    )
    return {
        "functions": migrated_functions,
        "symbols": cast(JsonValue, _required(program, "symbols", "$.program_model")),
        "modules": [program_module_to_data(item) for item in modules],
        "package": package,
        "entrypoint": {
            "id": entrypoint_id,
            "callable_id": _optional_string(
                setup.get("entrypoint_callable_id"), "$.module_setup.entrypoint_callable_id"
            ),
            "arguments": cast(JsonValue, arguments),
            "startup": [program_declaration_to_data(item) for item in startup],
        },
    }


def legacy_runtime_data(raw_setup: Mapping[str, object]) -> dict[str, JsonValue]:
    return {
        "run_profiles": cast(JsonValue, raw_setup.get("run_profiles", [{"name": "Default"}])),
        "active_run_profile": cast(JsonValue, raw_setup.get("active_run_profile", "Default")),
    }


def migrate_legacy_program_operation(
    command_type: str,
    payload: dict[str, JsonValue],
    raw_project: Mapping[str, object],
    depth: int = 0,
) -> tuple[str, dict[str, JsonValue]]:
    """Translate durable history once; live command decoding has no legacy branch."""
    from code_visualizer.persistence.decoding import _array, _object, _string

    if depth > 32:
        raise ValueError("Legacy history operation exceeds nesting limits")
    project_id = _string(raw_project.get("project_id"), "project.project_id")
    program = _object(raw_project.get("program_model"), "project.program_model")
    setup = _object(raw_project.get("module_setup"), "project.module_setup")

    def header(model: Mapping[str, object], settings: Mapping[str, object]) -> dict[str, JsonValue]:
        version = raw_project.get("format_revision")
        arguments = settings.get("entrypoint_arguments", "")
        if type(version) is int and version < 8 and isinstance(arguments, str):
            settings = {
                **settings,
                "entrypoint_arguments": invocation_arguments_to_data(
                    configured_arguments_from_text(arguments)
                ),
            }
        converted = migrate_legacy_program_data(model, settings, project_id=project_id)
        return {key: converted[key] for key in ("package", "modules", "entrypoint")}

    def transaction(operations: list[JsonValue]) -> tuple[str, dict[str, JsonValue]]:
        flattened: list[JsonValue] = []
        for operation in operations:
            if isinstance(operation, dict) and operation.get("command_type") == "transaction":
                nested = _object(operation.get("payload"), "transaction.payload")
                flattened.extend(
                    cast(
                        list[JsonValue], _array(nested.get("operations"), "transaction.operations")
                    )
                )
            else:
                flattened.append(operation)
        return "transaction", {"operations": flattened}

    if command_type == "transaction":
        translated: list[JsonValue] = []
        for raw in _array(payload.get("operations"), "operation.operations"):
            item = _object(raw, "operation")
            name, values = migrate_legacy_program_operation(
                _string(item.get("command_type"), "operation.command_type"),
                cast(dict[str, JsonValue], _object(item.get("payload"), "operation.payload")),
                raw_project,
                depth + 1,
            )
            translated.append({"command_type": name, "payload": values})
        return transaction(translated)
    if command_type == "python.replace_module_setup":
        return transaction(
            [
                {"command_type": "program.configure", "payload": header(program, payload)},
                {
                    "command_type": "python.configure_runtime",
                    "payload": legacy_runtime_data(payload),
                },
            ]
        )
    if command_type == "domain.bundle.put":
        reference = payload.get("reference")
        if (
            isinstance(reference, dict)
            and reference.get("id") == "code_visualizer.computation"
            and reference.get("version") == "1"
        ):
            return command_type, {**payload, "reference": {**reference, "version": "2"}}
    if (
        command_type == "domain.bundle.delete"
        and payload.get("bundle_id") == "code_visualizer.computation"
        and payload.get("version") == "1"
    ):
        return command_type, {**payload, "version": "2"}
    if command_type == "program.function.create":
        module_path = canonical_module_path(
            _string(payload.get("module", "main"), "operation.module")
        )
        package = canonical_package_path(
            _string(setup.get("package", "app"), "module_setup.package")
        )
        return command_type, {
            **{key: value for key, value in payload.items() if key != "module"},
            "owner_id": f"module:{qualified_module_name(package, module_path)}",
        }
    if command_type == "program.function.set_module":
        module_path = canonical_module_path(_string(payload.get("module"), "operation.module"))
        function_id = _string(payload.get("function_id"), "operation.function_id")
        functions = [
            {**item, "module": module_path}
            if isinstance(item, dict) and item.get("id") == function_id
            else item
            for item in _array(program.get("functions"), "functions")
        ]
        return "program.configure", header({**program, "functions": functions}, setup)
    if command_type in {"program.function.restore", "program.function.replace_exact"}:
        function = _object(payload.get("function"), "operation.function")
        function_id = _string(function.get("id"), "operation.function.id")
        functions = _array(program.get("functions"), "program.functions")
        existing = next(
            (
                index
                for index, item in enumerate(functions)
                if isinstance(item, dict) and item.get("id") == function_id
            ),
            None,
        )
        if existing is not None:
            functions[existing] = function
        else:
            index = payload.get("function_index", len(functions))
            if type(index) is not int or not 0 <= index <= len(functions):
                raise ValueError("Legacy function restore index is invalid")
            functions.insert(index, function)
        settings = dict(setup)
        if "entrypoint_callable_id" in payload:
            settings["entrypoint_callable_id"] = payload["entrypoint_callable_id"]
        canonical_header = header({**program, "functions": functions}, settings)
        canonical_function = {
            **{
                key: value
                for key, value in function.items()
                if key not in {"module", "owning_class"}
            },
            "type_parameters": function.get("type_parameters", []),
        }
        updated = cast(
            dict[str, JsonValue],
            {
                **{key: value for key, value in payload.items() if key != "entrypoint_callable_id"},
                "function": canonical_function,
            },
        )
        if command_type == "program.function.restore":
            return command_type, {**updated, "program_header": canonical_header}
        return transaction(
            [
                {"command_type": command_type, "payload": updated},
                {"command_type": "program.configure", "payload": canonical_header},
            ]
        )
    return command_type, payload
