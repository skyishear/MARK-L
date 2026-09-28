"""Tests for v8.28 ``core.execution_failure`` (shared failure normalization)."""

from __future__ import annotations

import ast
import dataclasses
import os
import sys

import pytest

import core.execution_failure as failure_module
from core.execution_failure import ExecutionFailure, normalize_execution_failure

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, ".."))
CORE_DIR = os.path.join(ROOT, "core")
MODULE_PATH = os.path.join(CORE_DIR, "execution_failure.py")
SECRET = "token=sk-live-123 password=hunter2 /home/alice/.ssh/id_rsa"


def _tree() -> ast.Module:
    with open(MODULE_PATH, encoding="utf-8") as f:
        return ast.parse(f.read())


def _raised(exc: BaseException) -> BaseException:
    try:
        raise exc
    except BaseException as caught:  # noqa: BLE001 - need a live traceback
        return caught


class TestValue:
    def test_fields_exact(self) -> None:
        assert [f.name for f in dataclasses.fields(ExecutionFailure)] == [
            "exception_type", "run_id", "tool_name", "project"]

    def test_frozen(self) -> None:
        f = ExecutionFailure("ToolError", "r1", "t", None)
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.run_id = "r2"  # type: ignore[misc]

    def test_slots(self) -> None:
        f = ExecutionFailure("ToolError", "r1", "t", None)
        assert not hasattr(f, "__dict__")
        assert ExecutionFailure.__slots__ == ("exception_type", "run_id", "tool_name", "project")

    def test_equality_and_hash(self) -> None:
        a = ExecutionFailure("E", "r", None, None)
        assert a == ExecutionFailure("E", "r", None, None) and hash(a) == hash(ExecutionFailure("E", "r", None, None))


class TestNormalize:
    def test_exception_type_name(self) -> None:
        class CustomBoom(RuntimeError):
            pass

        f = normalize_execution_failure(CustomBoom(SECRET), run_id="r1", tool_name="step two", project="home")
        assert f == ExecutionFailure("CustomBoom", "r1", "step two", "home")

    def test_defaults(self) -> None:
        assert normalize_execution_failure(ValueError(), run_id="r") == ExecutionFailure("ValueError", "r", None, None)

    def test_base_exceptions(self) -> None:
        assert normalize_execution_failure(KeyboardInterrupt(), run_id="r").exception_type == "KeyboardInterrupt"

    @pytest.mark.parametrize("exc", [
        RuntimeError(SECRET),
        RuntimeError({"token": "sk-live-123"}, "password=hunter2"),
        _raised(ValueError(SECRET)),
    ])
    def test_no_message_repr_args_or_traceback_stored(self, exc: BaseException) -> None:
        f = normalize_execution_failure(exc, run_id="r", tool_name="t", project="p")
        dumped = repr(f) + repr(dataclasses.astuple(f))
        for fragment in ("sk-live-123", "hunter2", "id_rsa", "Traceback", repr(exc)):
            assert fragment not in dumped, fragment
        assert not any(v is exc for v in dataclasses.astuple(f))

    def test_only_type_name_is_read(self) -> None:
        fn = next(n for n in ast.walk(_tree()) if isinstance(n, ast.FunctionDef)
                  and n.name == "normalize_execution_failure")
        body = [n for stmt in fn.body for n in ast.walk(stmt)]
        uses = [n for n in body if isinstance(n, ast.Name) and n.id == "exc"]
        type_calls = [c for c in body if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                      and c.func.id == "type" and [a.id for a in c.args if isinstance(a, ast.Name)] == ["exc"]]
        # one isinstance() guard + one type(exc)
        assert len(uses) == 2 and len(type_calls) == 1
        called = {c.func.id for c in body if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        attrs = {n.attr for n in body if isinstance(n, ast.Attribute)}
        assert not {"str", "repr", "format", "print"} & called
        assert "traceback" not in {n.id for n in body if isinstance(n, ast.Name)}
        assert not {"args", "__traceback__", "__str__", "__repr__", "with_traceback", "__cause__",
                    "__context__"} & attrs

    @pytest.mark.parametrize("run_id", ["", "   ", None, 3])
    def test_invalid_run_id(self, run_id: object) -> None:
        with pytest.raises(ValueError):
            normalize_execution_failure(RuntimeError(), run_id=run_id)  # type: ignore[arg-type]

    def test_not_an_exception(self) -> None:
        with pytest.raises(TypeError):
            normalize_execution_failure("boom", run_id="r")  # type: ignore[arg-type]


class TestArchitecture:
    def test_stdlib_only_imports(self) -> None:
        for node in ast.walk(_tree()):
            if isinstance(node, ast.ImportFrom):
                assert node.module in {"__future__", "dataclasses", "typing"}, node.module
            elif isinstance(node, ast.Import):
                raise AssertionError(node.names[0].name)
        assert failure_module.__all__ == ["ExecutionFailure", "normalize_execution_failure"]

    def test_no_io_state_or_status_vocabulary(self) -> None:
        src = open(MODULE_PATH, encoding="utf-8").read()
        tree = _tree()
        idents = ({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
                  | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)})
        for forbidden in ("PipelineRunStatus", "PlanStatus", "GoalStatus", "retry", "attempt",
                          "open", "print", "logging"):
            assert forbidden not in idents, forbidden
        assert [n.name for n in tree.body if isinstance(n, ast.ClassDef)] == ["ExecutionFailure"]
        assert "global " not in src

    def test_only_agent_imports_it(self) -> None:
        for name in os.listdir(CORE_DIR):
            if name.endswith(".py") and name != "execution_failure.py":
                with open(os.path.join(CORE_DIR, name), encoding="utf-8") as f:
                    assert "execution_failure" not in f.read(), name
        with open(os.path.join(CORE_DIR, "agent", "__init__.py"), encoding="utf-8") as f:
            assert "from core.execution_failure import normalize_execution_failure" in f.read()

    def test_fresh_interpreter_import(self) -> None:
        import subprocess

        out = subprocess.run([sys.executable, "-c", "import core.execution_failure, core.agent"],
                             cwd=ROOT, capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
