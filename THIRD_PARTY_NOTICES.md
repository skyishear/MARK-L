# Third-Party Notices

MARK-L (project identity: EDITH) contains components that were not
authored as part of this project. This file records their origin and
license terms. It is separate from the project's own identity and
documentation (`readme.md`).

---

## 1. Imported Mark-L base snapshot

**Origin.** The repository was started from an imported snapshot of the
"Mark-L" personal assistant project (Mark L), created by **FatihMakes**
(source repository as identified in the imported documentation:
`https://github.com/FatihMakes/Mark-L`). The snapshot was imported in
commit `b1b1709` ("Initial commit: MARK L base project").

**License.** The imported snapshot declared:

> Personal and non-commercial use only.
> Licensed under Creative Commons BY-NC 4.0.

License: Creative Commons Attribution-NonCommercial 4.0 International
(CC BY-NC 4.0) — <https://creativecommons.org/licenses/by-nc/4.0/>

That license continues to apply to the derived material listed below,
including its non-commercial restriction. No copyright notice was
included with the imported snapshot.

**Derived material retained in this repository:**

- `main.py` — **modified** (Agent composition-root integration; one
  prompt/schema example value)
- `core/problem_solver.py` — **modified** (Agent / memory integration)
- `ui.py`, `setup.py` — modified (one display string each: project name)
- `.gitignore` — modified
- Retained without modification:
  - `requirements.txt`
  - `actions/` (all modules)
  - `dashboard/` (except the CryptoJS file noted in section 2)
  - `memory/` (`__init__.py`, `config_manager.py`, `core_memory.py`,
    `memory_manager.py`)
  - `skills/` (`__init__.py`, `spotify.py`, `weather.py`)
  - `config/__init__.py`, `config/jarvis.ico`
  - `core/__init__.py`, `core/identity_engine.py`, `core/installer.py`,
    `core/llm_client.py`, `core/prompt.txt`, `core/skill_registry.py`,
    `core/stt.py`, `core/tts.py`

Everything else in the repository — including the v8.x architecture,
`core/agent/`, the provider, context, memory, reflection, planning,
execution and tool modules added after the import, `tests/`, and the
governance documents — was developed as part of MARK-L.

---

## 2. CryptoJS

`dashboard/static/crypto-js.min.js` is a minified copy of the third-party
**CryptoJS** library, included as part of the imported snapshot. It is
not covered by section 1. CryptoJS is distributed by its authors under
the **MIT License**.

The imported file does not carry its license header or copyright notice.
Restoring the CryptoJS MIT license text alongside this file is an open
item.
