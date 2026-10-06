"""Frozen-module content pins (completion contract V4).

``tests/test_architecture_freeze.py`` pins the *import edges* of the legacy
modules; this file pins their *content*. Each frozen module below has exactly
one commit in git (its introduction is its freeze point), so its SHA-256 at
that commit is pinned here. Line endings are normalized before hashing, so a
Windows checkout (CRLF) hashes the same as a Linux one.

``main.py`` is pinned separately (``AUTHORIZED_SHA256``): it carries the
exceptions recorded in ``docs/EDITH_COMPLETION_CONTRACT.md`` §13 (commit
``aa95b63``, confirmed by the owner, and the owner-authorized v8.44 wiring), so
its pin is the authorized content, not a freeze-point commit.

A change to a pinned file must be an explicit, owner-authorized milestone that
updates its pin in the same change (``ROADMAP.md`` Frozen Modules).
"""

from __future__ import annotations

import hashlib
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# path -> (SHA-256 of the content with LF line endings, freeze-point commit)
FROZEN_SHA256: dict[str, tuple[str, str]] = {
    "core/planner.py": ("d8b5e362081e40451f9415b75c0d1098a047e5093f166b8d3a187f26cbe5c1a0", "ba12007"),
    "core/planner_problem_solver_adapter.py": ("7bd2da389c3fc63422aa7c5a04ab002f5bca98fc95ff04a1cad8a192de0ae437", "8551d59"),
    "core/planner_execution_orchestrator_adapter.py": ("bbf3a8f7cbeb429fba4119545309426e3c5d55d943d90538efedee8cac4e5ae1", "a4249bd"),
    "core/execution_orchestrator.py": ("0972e1c3de368c9116c01e3ba03337df8873f6a22fb9f18867d93fad9a34c9a6", "a4249bd"),
    "core/execution_pipeline.py": ("62b6e019e5bb27f55c0024df6a39f4a4c70f7a038d6b9ed29e0212b61456d96c", "d5dccbc"),
    "core/execution_session.py": ("140a9569c3c8bde88683455ca20b522dcdee01b137de08301eb70037e4ecae82", "90c87c0"),
    "core/execution_coordinator.py": ("017407a0777621fc201fd45f432bb11a782aefe43b10c0eeafc9d2f69c0ea90b", "6e6bac1"),
    "core/execution_result.py": ("c696adc4a59ac4806d5ddc5d34fe6a1998fa3484951e66adde065e4685a21d64", "90c87c0"),
    "core/execution_progress.py": ("1428c48e16e0d52c14ef57dd4186e09b7cc15a45d77ea99ae20a6a5d8fb2cecb", "90c87c0"),
    "core/execution_event.py": ("75f4eb251d6126a31caf5ac1dbcf9dedb7e7c87bcdc9e5011beb7c50259b0148", "90c87c0"),
    "core/skill_registry.py": ("1e881e63e02d28c6d6c107e958f0e34adacfa730dacef9368a2161b9758543c3", "b1b1709"),
    "core/skill_dispatch.py": ("3dd272b1d005ed08385d3add1da9e54600ff0030ab6dc3d282602b08f52672cd", "88fb5e5"),
    "skills/__init__.py": ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", "b1b1709"),
    "skills/spotify.py": ("154d7743d2dcf68c1b3268a12276b47aa35a0ed19caa73480fa55e845989ee2a", "b1b1709"),
    "skills/weather.py": ("576b36b359bc3ec0f49f6ad69720f0fc4e410b6a43b50fcdf9ed7201775991f8", "b1b1709"),
}
# Owner-authorized content (contract §13): main.py after the v8.44 scoped unfreeze (OD-2).
AUTHORIZED_SHA256: dict[str, tuple[str, str]] = {
    "main.py": ("b4193c049141c94adb5c883f2bb8946ddf83c3a7b68d0fd978dc90792b8db821", "v8.44"),
}


def _digest(relative: str) -> str:
    with open(os.path.join(ROOT, relative), "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


@pytest.mark.parametrize("relative", sorted({**FROZEN_SHA256, **AUTHORIZED_SHA256}))
def test_frozen_module_content_is_unchanged(relative: str) -> None:
    expected, freeze_commit = {**FROZEN_SHA256, **AUTHORIZED_SHA256}[relative]
    assert _digest(relative) == expected, (
        f"{relative} differs from its freeze point ({freeze_commit}); frozen modules change only "
        "through an explicit, owner-authorized milestone that also updates this pin"
    )


def test_line_ending_normalization_is_applied() -> None:
    assert hashlib.sha256(b"a\nb\n").hexdigest() == hashlib.sha256(b"a\r\nb\r\n".replace(b"\r\n", b"\n")).hexdigest()


def test_the_skills_package_has_no_unpinned_files() -> None:
    present = {f"skills/{n}" for n in os.listdir(os.path.join(ROOT, "skills")) if n.endswith(".py")}
    assert present == {p for p in FROZEN_SHA256 if p.startswith("skills/")}


def _roadmap_frozen_paths() -> set[str]:
    with open(os.path.join(ROOT, "ROADMAP.md"), encoding="utf-8") as f:
        text = f.read()
    block = text[text.index("## Frozen Modules"):text.index("## Architecture Policy")]
    return set(re.findall(r"`((?:core|skills)/[A-Za-z0-9_./*]+|main\.py)`", block))


def test_every_roadmap_frozen_module_is_pinned_or_documented_pending() -> None:
    listed = _roadmap_frozen_paths()
    assert listed, "ROADMAP.md Frozen Modules section could not be parsed"
    for path in listed:
        if path == "skills/*":
            continue
        assert path in FROZEN_SHA256 or path in AUTHORIZED_SHA256, path


def test_every_pin_is_a_roadmap_frozen_module() -> None:
    listed = _roadmap_frozen_paths()
    for path in FROZEN_SHA256:
        assert path in listed or (path.startswith("skills/") and "skills/*" in listed), path


def test_main_py_is_the_single_authorized_exception_and_is_recorded() -> None:
    assert set(AUTHORIZED_SHA256) == {"main.py"} and "main.py" not in FROZEN_SHA256
    with open(os.path.join(ROOT, "docs", "EDITH_COMPLETION_CONTRACT.md"), encoding="utf-8") as f:
        contract = f.read()
    section = contract[contract.index("## 13. Recorded exceptions"):contract.index("## 14. Amendment log")]
    assert "main.py" in section and "aa95b63" in section and "v8.44" in section
