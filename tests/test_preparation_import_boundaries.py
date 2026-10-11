"""Fresh-process preparation imports only its required execution/generation layers."""

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"


def _fresh_python(tmp_path, script):
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys\nsys.path.insert(0, {str(SOURCE_ROOT)!r})\n" + dedent(script),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout


def test_real_editor_preparation_does_not_load_rendering_or_qt(tmp_path):
    output = _fresh_python(
        tmp_path,
        """
        from code_visualizer.application.editor_preparation import prepare_editor

        def assert_preparation_imports():
            forbidden = (
                'code_visualizer.rendering', 'code_visualizer.ui_qt',
                'PySide6', 'shiboken6',
            )
            loaded = sorted(
                name for name in sys.modules
                if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden)
            )
            assert not loaded, loaded

        assert_preparation_imports()
        from io import BytesIO
        from pathlib import Path
        from code_visualizer.application.project_factory import create_default_project
        from code_visualizer.domain.worker import (
            WorkerEditorPreparationRequest, WorkerEditorPrepared,
        )
        from code_visualizer.execution.worker_process import WorkerChannel, read_worker_frame
        from code_visualizer.extensions.builtin import builtin_registry
        from code_visualizer.persistence.canonical import canonical_data_bytes
        from code_visualizer.persistence.python_execution import load_python_execution_artifact
        from code_visualizer.persistence.resource_store import ResourceStore
        from code_visualizer.persistence.serialization import project_to_data
        from code_visualizer.protocol.worker import worker_event_from_bytes

        project = create_default_project()
        original = project_to_data(project)
        store = ResourceStore(Path.cwd())
        source = store.put(canonical_data_bytes(original), 'application/json')
        request = WorkerEditorPreparationRequest(
            'import-boundary', source.reference, project.id, project.revision,
            focus_diagram_id=project.documents[0].id,
        )
        channel = WorkerChannel(BytesIO(), BytesIO())
        prepare_editor(request, builtin_registry(), store, channel)
        channel.outgoing.seek(0)
        events = []
        while True:
            try:
                events.append(worker_event_from_bytes(read_worker_frame(channel.outgoing)))
            except EOFError:
                break
        result = events[-1]
        assert isinstance(result, WorkerEditorPrepared)
        assert result.source_digest == source.content_hash
        artifact = load_python_execution_artifact(result.execution_artifact, store)
        assert artifact.generated.invocation is not None
        assert (
            artifact.generated.invocation.callable_id
            == project.program_model.entrypoint_callable_id
        )
        assert any('def main(' in file.source for file in artifact.generated.files)
        assert project_to_data(project) == original
        assert_preparation_imports()
        print('prepared without rendering or Qt')
        """,
    )
    assert output.strip() == "prepared without rendering or Qt"


def test_generation_and_execution_public_exports_are_exact_defining_objects(tmp_path):
    output = _fresh_python(
        tmp_path,
        """
        from importlib import import_module

        contracts = {
            'code_visualizer.generation': {
                'code_visualizer.generation.artifacts': (
                    'ArtifactInspection', 'GenerationResult', 'atomic_promote_directory',
                    'expected_artifact_contents', 'generate_to_disk', 'inspect_generation',
                    'load_generation_manifest',
                ),
                'code_visualizer.generation.emitter': (
                    'GeneratedProject', 'GenerationError', 'SourceSpan',
                ),
                'code_visualizer.generation.python': (
                    'BuildBlockedError', 'GeneratedPython', 'generate_python',
                    'generate_python_project', 'generated_module_for_diagram',
                ),
            },
            'code_visualizer.execution': {
                'code_visualizer.execution.debugger': (
                    'DebugEvent', 'DebugFrame', 'DebugLaunch', 'DebugSession', 'DebugState',
                ),
                'code_visualizer.execution.runner': (
                    'RunResult', 'RunSession', 'TraceEvent', 'TraceResult', 'run_generated',
                    'run_project', 'run_source', 'trace_project', 'trace_source',
                ),
                'code_visualizer.execution.runtime': (
                    'RuntimeBinding', 'RuntimeBindingSpec', 'RuntimeChild', 'RuntimeGraph',
                    'RuntimeGraphDelta', 'RuntimeTraceStore', 'RuntimeValue', 'RuntimeValueKind',
                    'SourceLocation',
                ),
            },
        }
        for facade_name, modules in contracts.items():
            facade = import_module(facade_name)
            expected = {name for names in modules.values() for name in names}
            assert set(facade.__all__) == expected
            assert len(facade.__all__) == len(expected)
            star_exports = {}
            exec('from ' + facade_name + ' import *', star_exports)
            for defining_module, names in modules.items():
                owner = import_module(defining_module)
                for name in names:
                    actual = getattr(facade, name)
                    assert actual is getattr(owner, name), (facade_name, defining_module, name)
                    assert star_exports[name] is actual
            try:
                getattr(facade, 'no_such_public_export')
            except AttributeError:
                pass
            else:
                raise AssertionError('Unknown facade export did not raise AttributeError')
        print('public exports preserve exact identity')
        """,
    )
    assert output.strip() == "public exports preserve exact identity"


def test_complete_static_catalog_does_not_load_unselected_solver_or_history_implementations(
    tmp_path,
):
    output = _fresh_python(
        tmp_path,
        """
        forbidden = (
            'code_visualizer.extensions.axial.assembly',
            'code_visualizer.extensions.axial.geometry',
            'code_visualizer.extensions.adaptive_diffusion.history',
            'code_visualizer.extensions.gas_observation.reader',
            'code_visualizer.extensions.hybrid_gas.history',
        )
        class RejectUnselectedImplementation:
            def find_spec(self, fullname, path=None, target=None):
                if fullname in forbidden:
                    raise ImportError('Unexpected catalog execution dependency: ' + fullname)
        sys.meta_path.insert(0, RejectUnselectedImplementation())

        from code_visualizer.extensions.builtin import builtin_registry
        registry = builtin_registry()
        actual = {backend.definition.id for backend in registry.backends()}
        assert 'code_visualizer.python' in actual
        assert 'org.codevisualizer.axial.linear_bar' in actual
        assert 'code_visualizer.adaptive_diffusion.finite_volume' in actual
        assert 'code_visualizer.hybrid_gas.state_flux' in actual
        assert not any(name in sys.modules for name in forbidden)
        print('complete contracts without unselected execution modules')
        """,
    )
    assert output.strip() == "complete contracts without unselected execution modules"
