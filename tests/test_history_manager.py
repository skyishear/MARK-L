import threading

import pytest

from core.agent.history_manager import (
    HistoryManager,
    HistoryRecord,
    HistoryManagerError,
    InvalidHistoryRecordError,
)


def test_record_stores_entry():
    manager = HistoryManager()
    record = manager.record(
        "planner",
        "created execution plan",
        metadata={"mission_id": "m1"},
    )
    assert isinstance(record, HistoryRecord)
    assert record.category == "planner"
    assert record.description == "created execution plan"
    assert record.metadata == {"mission_id": "m1"}
    assert record.timestamp != ""


def test_record_empty_category_raises():
    manager = HistoryManager()
    with pytest.raises(InvalidHistoryRecordError):
        manager.record("", "description")


def test_record_whitespace_category_raises():
    manager = HistoryManager()
    with pytest.raises(InvalidHistoryRecordError):
        manager.record("   ", "description")


def test_record_empty_description_raises():
    manager = HistoryManager()
    with pytest.raises(InvalidHistoryRecordError):
        manager.record("planner", "")


def test_get_history_returns_all():
    manager = HistoryManager()
    manager.record("planner", "r1")
    manager.record("executor", "r2")
    records = manager.get_history()
    assert len(records) == 2


def test_get_history_filtered():
    manager = HistoryManager()
    manager.record("planner", "r1")
    manager.record("executor", "r2")
    records = manager.get_history(category="planner")
    assert len(records) == 1
    assert records[0].category == "planner"


def test_latest_returns_last():
    manager = HistoryManager()
    manager.record("planner", "r1")
    latest = manager.record("planner", "r2")
    assert manager.latest("planner") is latest


def test_latest_without_filter():
    manager = HistoryManager()
    manager.record("planner", "r1")
    latest = manager.record("executor", "r2")
    assert manager.latest() is latest


def test_latest_missing_category_raises():
    manager = HistoryManager()
    with pytest.raises(HistoryManagerError):
        manager.latest("ghost")


def test_clear():
    manager = HistoryManager()
    manager.record("planner", "r1")
    manager.clear()
    assert manager.get_history() == []


def test_summary():
    manager = HistoryManager()
    manager.record("planner", "r1")
    manager.record("planner", "r2")
    manager.record("executor", "r3")

    summary = manager.summary()
    assert summary["total"] == 3
    assert summary["counts"]["planner"] == 2
    assert summary["counts"]["executor"] == 1


def test_summary_empty():
    manager = HistoryManager()
    summary = manager.summary()
    assert summary["total"] == 0
    assert summary["counts"] == {}


def test_history_record_is_immutable():
    manager = HistoryManager()
    record = manager.record("planner", "r1")

    with pytest.raises(Exception):
        record.description = "mutated"


def test_manager_never_executes_metadata():
    called = []

    def callback():
        called.append(True)

    manager = HistoryManager()
    manager.record("planner", "r1", metadata={"callback": callback})

    manager.get_history()
    manager.latest()
    manager.summary()
    manager.clear()

    assert called == []


def test_thread_safety():
    manager = HistoryManager()
    errors = []

    def worker(category):
        try:
            for i in range(100):
                manager.record(category, f"record-{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(f"category{n}",)) for n in range(5)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    assert errors == []
    assert manager.summary()["total"] == 500
