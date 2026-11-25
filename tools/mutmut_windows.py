"""Run mutmut on Windows using spawn-based process isolation.

Upstream mutmut exits early on win32 and relies on ``os.fork()``. This entry point
patches isolation helpers, then loads ``mutmut.__main__`` with those guards relaxed.
"""

from __future__ import annotations

import importlib.util
import multiprocessing as mp
import os
import pickle
import platform
import subprocess
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

_STUB_SCRIPT = (
    "import sys,types\n"
    "resource=types.ModuleType('resource')\n"
    "resource.RLIMIT_CPU=0\n"
    "resource.setrlimit=lambda *a,**k:None\n"
    "sys.modules['resource']=resource\n"
)


def _spawn_worker_with_result(
    result_path: str, pickled_callable: bytes, pickled_args: bytes
) -> None:
    """Child target: run a pickled callable and write the result to *result_path*."""
    _ensure_unix_stubs()
    fn = pickle.loads(pickled_callable)
    args = pickle.loads(pickled_args)
    try:
        value = fn(*args)
        with open(result_path, "wb") as output:
            pickle.dump({"ok": True, "value": value}, output)
        sys.exit(0)
    except Exception as error:
        with open(result_path, "wb") as output:
            pickle.dump(
                {
                    "ok": False,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                },
                output,
            )
        sys.exit(1)


def _spawn_worker_exit(pickled_callable: bytes, pickled_args: bytes) -> None:
    """Child target: run a pickled callable and exit with its return code."""
    _ensure_unix_stubs()
    fn = pickle.loads(pickled_callable)
    args = pickle.loads(pickled_args)
    try:
        code = fn(*args)
        sys.exit(code if isinstance(code, int) else 0)
    except Exception:
        sys.exit(1)


def _run_in_spawn_with_result(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run *fn* in a spawned child and return its pickled result."""
    if kwargs:
        raise TypeError("spawn isolation does not support keyword arguments")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as handle:
        path = handle.name
    process = mp.get_context("spawn").Process(
        target=_spawn_worker_with_result,
        args=(path, pickle.dumps(fn), pickle.dumps(args)),
        daemon=True,
    )
    process.start()
    process.join()
    try:
        with open(path, "rb") as source:
            data = pickle.load(source)
    finally:
        os.unlink(path)
    if process.exitcode != 0 or not data.get("ok"):
        message = f"Child exited with code {process.exitcode}"
        if data and not data.get("ok") and "error" in data:
            message += f": {data['error']}"
        raise ChildProcessError(message)
    return data["value"]


def _run_in_spawn(fn: Callable[..., int], *args: Any, **kwargs: Any) -> int:
    """Run *fn* in a spawned child and return its exit code."""
    if kwargs:
        raise TypeError("spawn isolation does not support keyword arguments")
    process = mp.get_context("spawn").Process(
        target=_spawn_worker_exit,
        args=(pickle.dumps(fn), pickle.dumps(args)),
        daemon=True,
    )
    process.start()
    process.join()
    return process.exitcode if process.exitcode is not None else 1


def _ensure_unix_stubs() -> None:
    """Stub POSIX-only modules so mutmut can import on Windows."""
    import types

    if "resource" not in sys.modules:
        stub = types.ModuleType("resource")
        stub.RLIMIT_CPU = 0
        stub.setrlimit = lambda *args, **kwargs: None
        sys.modules["resource"] = stub


def _patch_isolation() -> None:
    """Replace fork-based runners with spawn-based workers on Windows."""
    _ensure_unix_stubs()
    import mutmut.code_coverage as code_coverage
    from collections.abc import Iterable

    from mutmut.configuration import config
    from mutmut.mutation.trampoline import set_mutant_under_test
    from mutmut.runners.harness import PytestRunner
    from mutmut.state import state
    from mutmut.workers import isolation
    from mutmut.workers.isolation import MutantResult, MutantRunner, RunningWorker

    def gather_coverage_inline(
        runner: PytestRunner, source_files: Iterable[Path]
    ) -> code_coverage.CoverageInfo:
        """Measure coverage in-process; Windows has no fork-safe alternative."""
        return code_coverage._gather_coverage_in_this_process(runner, source_files)

    code_coverage.gather_coverage = gather_coverage_inline
    isolation.run_in_fork_with_result = _run_in_spawn_with_result
    isolation.run_in_fork = _run_in_spawn

    class WindowsProcessRunner(MutantRunner):
        """Isolation runner that tests each mutant in a spawned subprocess."""

        def __init__(self, max_workers: int, test_runner: PytestRunner) -> None:
            self.max_workers = max_workers
            self.test_runner = test_runner
            self._running: dict[mp.Process, RunningWorker] = {}
            self._no_tests_results: list[MutantResult] = []

        def startup(self) -> None:
            return

        def submit(
            self,
            mutant_name: str,
            tests: list[str],
            cpu_time_limit: int,
            estimated_time: float,
        ) -> None:
            if not tests:
                self._no_tests_results.append(
                    MutantResult(mutant_name=mutant_name, exit_code=33, duration=0.0)
                )
                return

            tests_sorted = sorted(
                tests, key=lambda test_name: state().duration_by_test[test_name]
            )
            payload = pickle.dumps(
                (mutant_name, tests_sorted, config().debug),
                protocol=pickle.HIGHEST_PROTOCOL,
            )
            script = (
                _STUB_SCRIPT + "import os,pickle,sys\n"
                "from mutmut.mutation.trampoline import set_mutant_under_test\n"
                "from mutmut.runners.harness import PytestRunner\n"
                "mutant_name, tests, debug = pickle.loads(sys.stdin.buffer.read())\n"
                "set_mutant_under_test(mutant_name)\n"
                "if not debug:\n"
                "    sys.stdout = sys.stderr = open(os.devnull, 'w')\n"
                "runner = PytestRunner()\n"
                "sys.exit(runner.run_tests(mutant_name=mutant_name, tests=tests))\n"
            )
            process = subprocess.Popen(
                [sys.executable, "-c", script],
                stdin=subprocess.PIPE,
                cwd=os.getcwd(),
            )
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.close()
            self._running[process] = RunningWorker(
                mutant_name, datetime.now(), estimated_time
            )

        def has_capacity(self) -> bool:
            return len(self._running) < self.max_workers

        def wait_for_result(self, timeout: float | None = None) -> MutantResult:
            if self._no_tests_results:
                return self._no_tests_results.pop(0)
            if not self._running:
                raise ChildProcessError("No mutant workers are running")
            while True:
                for process, worker in list(self._running.items()):
                    exit_code = process.poll()
                    if exit_code is None:
                        continue
                    self._running.pop(process)
                    duration = (datetime.now() - worker.start_time).total_seconds()
                    return MutantResult(
                        mutant_name=worker.mutant_name,
                        exit_code=exit_code,
                        duration=duration,
                    )
                if timeout == 0:
                    raise ChildProcessError("Timed out waiting for a mutant worker")
                time.sleep(0.05)

        def pending_count(self) -> int:
            return len(self._running) + len(self._no_tests_results)

        def signal_work_complete(self) -> None:
            return

        def stop_all_workers(self) -> None:
            for process in list(self._running):
                process.terminate()

        def shutdown(self) -> None:
            for process in list(self._running):
                process.wait(timeout=1)

        def collect_stats(self, tests: list[str] | None) -> int:
            return self.test_runner.run_stats(tests=tests or [])

        def run_clean_tests(self, tests: list[str]) -> int:
            return self.test_runner.run_tests(mutant_name=None, tests=tests)

        def run_forced_fail(self) -> int:
            return self.test_runner.run_forced_fail()

        def list_all_tests(self) -> Any:
            return self.test_runner.list_all_tests()

    def get_mutant_runner(max_workers: int = 1) -> MutantRunner:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        pytest_runner = PytestRunner()
        pytest_runner.prepare_main_test_run()
        return WindowsProcessRunner(max_workers=max_workers, test_runner=pytest_runner)

    isolation.get_mutant_runner = get_mutant_runner


def _load_mutmut_cli() -> Any:
    """Import the mutmut CLI without the upstream Windows exit guard."""
    _ensure_unix_stubs()
    import mutmut

    main_path = Path(mutmut.__file__).with_name("__main__.py")
    source = main_path.read_text(encoding="utf-8")
    source = source.replace(
        'if platform.system() == "Windows":\n'
        "    print(\n"
        '        "To run mutmut on Windows, please use the WSL. Native windows support is tracked in issue https://github.com/boxed/mutmut/issues/397"\n'
        "    )\n"
        "    sys.exit(1)\n",
        "",
    )
    source = source.replace('set_start_method("fork")', 'set_start_method("spawn")')
    module = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("mutmut.__main__", loader=None)
    )
    module.__file__ = str(main_path)
    sys.modules["mutmut.__main__"] = module
    exec(compile(source, str(main_path), "exec"), module.__dict__)
    return module.cli


def main() -> None:
    """Patch isolation and forward to the mutmut command-line interface."""
    if platform.system() == "Windows":
        os.environ["MUTMUT_WINDOWS_SHIM"] = "1"
        mp.freeze_support()
        _patch_isolation()
    cli = _load_mutmut_cli()
    cli(prog_name="mutmut")


if __name__ == "__main__":
    main()
