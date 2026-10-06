"""Dependency declarations (completion contract V7).

Every third-party package imported at module level by the production code must be
declared in ``requirements.txt``; the provider SDKs the v8.x providers use must be
declared; the test runner lives in ``requirements-dev.txt``. Imports nested in
functions or ``try`` blocks are optional features and are not required to be
declared. ``core/stt.py`` and ``core/tts.py`` (inherited speech modules, imported
by nothing in the production entry point) are the one recorded exclusion.
"""

from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STD = set(sys.stdlib_module_names)
LOCAL = {"core", "actions", "memory", "skills", "config", "dashboard", "tests", "ui", "main", "setup"}
EXCLUDED_FILES = {os.path.join("core", "stt.py"), os.path.join("core", "tts.py")}
# import name -> requirements.txt package name
PACKAGE = {"PIL": "pillow", "PyQt6": "PyQt6", "cv2": "opencv-python", "google": "google-genai",
           "qrcode": "qrcode", "pptx": "python-pptx", "bs4": "beautifulsoup4", "multipart": "python-multipart",
           "win32com": "pywin32", "win32gui": "pywin32", "win32api": "pywin32", "win32con": "pywin32",
           "pythoncom": "pywin32"}


def declared(path: str) -> set[str]:
    names: set[str] = set()
    for line in open(os.path.join(ROOT, path), encoding="utf-8"):
        line = line.split("#")[0].strip()
        if line and not line.startswith("-"):
            names.add(re.split(r"[\[;<>=! ]", line)[0].lower())
    return names


def module_level_third_party() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    files = [f for f in os.listdir(ROOT) if f.endswith(".py")]
    for folder in ("core", "actions", "memory", "skills", "config", "dashboard"):
        for dirpath, _, names in os.walk(os.path.join(ROOT, folder)):
            files += [os.path.relpath(os.path.join(dirpath, n), ROOT) for n in names if n.endswith(".py")]
    for rel in files:
        if rel in EXCLUDED_FILES or rel == "setup.py":
            continue
        tree = ast.parse(open(os.path.join(ROOT, rel), encoding="utf-8").read())
        for node in tree.body:  # module level only (not nested in a function or try block)
            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
            for mod in mods:
                top = mod.split(".")[0]
                if top not in STD and top not in LOCAL:
                    found.setdefault(top, set()).add(rel)
    return found


def test_module_level_third_party_imports_are_declared() -> None:
    have = declared("requirements.txt")
    missing = {top: sorted(files) for top, files in module_level_third_party().items()
               if PACKAGE.get(top, top).lower() not in have}
    assert missing == {}, missing


def test_the_v8_provider_sdks_are_declared() -> None:
    assert {"anthropic", "openai", "ollama", "google-genai"} <= declared("requirements.txt")


def test_the_dev_requirements_add_the_test_runner_on_top_of_the_runtime_set() -> None:
    text = open(os.path.join(ROOT, "requirements-dev.txt"), encoding="utf-8").read()
    assert "-r requirements.txt" in text and "pytest" in declared("requirements-dev.txt")
    assert "pytest" not in declared("requirements.txt")


def test_the_suite_needs_only_declared_packages() -> None:
    have = declared("requirements-dev.txt") | declared("requirements.txt")
    needed: set[str] = set()
    tests_dir = os.path.join(ROOT, "tests")
    for name in os.listdir(tests_dir):
        if name.endswith(".py"):
            for node in ast.walk(ast.parse(open(os.path.join(tests_dir, name), encoding="utf-8").read())):
                mods = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                    [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
                needed |= {m.split(".")[0] for m in mods if m.split(".")[0] not in STD | LOCAL}
    assert {PACKAGE.get(n, n).lower() for n in needed} <= have | {"pytest"}, needed


def test_the_speech_modules_are_not_reachable_from_the_production_entry_point() -> None:
    for rel in ("main.py",):
        source = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "core.stt" not in source and "core.tts" not in source
