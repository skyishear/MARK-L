"""Tests for core.memory_adapter."""

from __future__ import annotations

from typing import Any

import pytest

from core.agent.memory_adapter import (
    MemoryAdapterError,
    persist_to_memory_engine,
    query_memory_engine,
    remove_from_memory_engine,
)

# ── Fakes standing in for MemoryEngine's real functions ──────────────────


def fake_remember(
    category: str,
    key: str,
    value: str,
    *,
    importance: int = 3,
    confidence: float = 1.0,
    source: str = "user_stated",
    project: str | None = None,
    memory_type: str = "permanent",
    sensitive: bool = False,
    ttl_days: int | None = None,
) -> str:
    return f"remembered: {category}/{key}"


def fake_recall(
    *,
    query: str | None = None,
    category: str | None = None,
    project: str | None = None,
    memory_type: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    return [{"category": category, "query": query, "limit": limit}]


def fake_forget(
    *,
    key: str | None = None,
    category: str | None = None,
    project: str | None = None,
) -> int:
    return 1


def raising_remember(*args: Any, **kwargs: Any) -> str:
    raise RuntimeError("db locked")


def raising_recall(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    raise RuntimeError("db locked")


def raising_forget(*args: Any, **kwargs: Any) -> int:
    raise RuntimeError("db locked")


# ── persist_to_memory_engine ──────────────────────────────────────────────


class TestPersistToMemoryEngine:
    def test_forwards_positional_args(self) -> None:
        captured: dict[str, Any] = {}

        def spy_remember(category: str, key: str, value: str, **kwargs: Any) -> str:
            captured["category"] = category
            captured["key"] = key
            captured["value"] = value
            captured["kwargs"] = kwargs
            return "ok"

        result = persist_to_memory_engine(spy_remember, "preferences", "k", "v")
        assert result == "ok"
        assert captured["category"] == "preferences"
        assert captured["key"] == "k"
        assert captured["value"] == "v"

    def test_forwards_all_keyword_args(self) -> None:
        captured: dict[str, Any] = {}

        def spy_remember(category: str, key: str, value: str, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "ok"

        persist_to_memory_engine(
            spy_remember,
            "technical",
            "k",
            "v",
            importance=5,
            confidence=0.9,
            source="foundation_adapter",
            project="mark_l",
            memory_type="session",
            sensitive=True,
            ttl_days=7,
        )
        assert captured == {
            "importance": 5,
            "confidence": 0.9,
            "source": "foundation_adapter",
            "project": "mark_l",
            "memory_type": "session",
            "sensitive": True,
            "ttl_days": 7,
        }

    def test_uses_default_kwargs_when_not_specified(self) -> None:
        captured: dict[str, Any] = {}

        def spy_remember(category: str, key: str, value: str, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "ok"

        persist_to_memory_engine(spy_remember, "notes", "k", "v")
        assert captured["importance"] == 3
        assert captured["confidence"] == 1.0
        assert captured["source"] == "adapter"
        assert captured["project"] is None
        assert captured["memory_type"] == "permanent"
        assert captured["sensitive"] is False
        assert captured["ttl_days"] is None

    def test_returns_remember_fn_result_verbatim(self) -> None:
        result = persist_to_memory_engine(fake_remember, "preferences", "k", "v")
        assert result == "remembered: preferences/k"

    def test_empty_category_raises(self) -> None:
        with pytest.raises(MemoryAdapterError):
            persist_to_memory_engine(fake_remember, "", "k", "v")

    def test_blank_category_raises(self) -> None:
        with pytest.raises(MemoryAdapterError):
            persist_to_memory_engine(fake_remember, "   ", "k", "v")

    def test_empty_key_raises(self) -> None:
        with pytest.raises(MemoryAdapterError):
            persist_to_memory_engine(fake_remember, "notes", "", "v")

    def test_empty_value_raises(self) -> None:
        with pytest.raises(MemoryAdapterError):
            persist_to_memory_engine(fake_remember, "notes", "k", "")

    def test_blank_value_raises(self) -> None:
        with pytest.raises(MemoryAdapterError):
            persist_to_memory_engine(fake_remember, "notes", "k", "   ")

    def test_remember_fn_exception_is_wrapped(self) -> None:
        with pytest.raises(MemoryAdapterError, match="remember_fn failed"):
            persist_to_memory_engine(raising_remember, "notes", "k", "v")

    def test_validation_runs_before_calling_remember_fn(self) -> None:
        calls: list[Any] = []

        def spy_remember(*args: Any, **kwargs: Any) -> str:
            calls.append(args)
            return "ok"

        with pytest.raises(MemoryAdapterError):
            persist_to_memory_engine(spy_remember, "", "k", "v")
        assert calls == []


# ── query_memory_engine ────────────────────────────────────────────────────


class TestQueryMemoryEngine:
    def test_forwards_all_kwargs(self) -> None:
        captured: dict[str, Any] = {}

        def spy_recall(**kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return []

        query_memory_engine(
            spy_recall,
            query="wifi",
            category="technical",
            project="mark_l",
            memory_type="permanent",
            limit=10,
        )
        assert captured == {
            "query": "wifi",
            "category": "technical",
            "project": "mark_l",
            "memory_type": "permanent",
            "limit": 10,
        }

    def test_uses_default_kwargs_when_not_specified(self) -> None:
        captured: dict[str, Any] = {}

        def spy_recall(**kwargs: Any) -> list[dict[str, Any]]:
            captured.update(kwargs)
            return []

        query_memory_engine(spy_recall)
        assert captured == {
            "query": None,
            "category": None,
            "project": None,
            "memory_type": None,
            "limit": 25,
        }

    def test_returns_recall_fn_result_verbatim(self) -> None:
        result = query_memory_engine(fake_recall, category="preferences", limit=5)
        assert result == [{"category": "preferences", "query": None, "limit": 5}]

    def test_recall_fn_exception_is_wrapped(self) -> None:
        with pytest.raises(MemoryAdapterError, match="recall_fn failed"):
            query_memory_engine(raising_recall)


# ── remove_from_memory_engine ─────────────────────────────────────────────


class TestRemoveFromMemoryEngine:
    def test_forwards_filters(self) -> None:
        captured: dict[str, Any] = {}

        def spy_forget(**kwargs: Any) -> int:
            captured.update(kwargs)
            return 2

        result = remove_from_memory_engine(spy_forget, key="k", category="notes")
        assert result == 2
        assert captured == {"key": "k", "category": "notes", "project": None}

    def test_returns_forget_fn_result_verbatim(self) -> None:
        result = remove_from_memory_engine(fake_forget, key="k")
        assert result == 1

    def test_no_filters_raises(self) -> None:
        with pytest.raises(MemoryAdapterError):
            remove_from_memory_engine(fake_forget)

    def test_forget_fn_exception_is_wrapped(self) -> None:
        with pytest.raises(MemoryAdapterError, match="forget_fn failed"):
            remove_from_memory_engine(raising_forget, key="k")

    def test_validation_runs_before_calling_forget_fn(self) -> None:
        calls: list[Any] = []

        def spy_forget(**kwargs: Any) -> int:
            calls.append(kwargs)
            return 0

        with pytest.raises(MemoryAdapterError):
            remove_from_memory_engine(spy_forget)
        assert calls == []


# ── Independence from both Foundation modules and MemoryEngine ───────────


class TestIndependence:
    def test_no_import_of_foundation_or_memory_engine_modules(self) -> None:
        import ast

        import core.agent.memory_adapter as module

        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.add(node.module)

        forbidden_prefixes = ("core.", "memory.")
        for name in imported_names:
            assert not any(name.startswith(p) for p in forbidden_prefixes)
            assert name not in ("core", "memory")

    def test_module_only_imports_stdlib_typing(self) -> None:
        import ast

        import core.agent.memory_adapter as module

        source = module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed = {"typing", "collections.abc", "__future__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module in allowed
