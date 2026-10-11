"""PyInstaller entry point for the desktop bundle."""

from code_visualizer.execution.child_process import dispatch_internal_worker


def _computation_worker() -> int:
    from code_visualizer.application.computation_worker import main

    return main()


def _main() -> int:
    worker_result = dispatch_internal_worker(computation_worker=_computation_worker)
    if worker_result is not None:
        return worker_result
    from code_visualizer.ui_qt.app import main

    return main()


raise SystemExit(_main())
