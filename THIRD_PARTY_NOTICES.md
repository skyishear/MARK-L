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
  prompt/schema example value; the v8.44 tool-session, run-recording and
  memory wiring)
- `core/problem_solver.py` — **modified** (Agent / memory integration)
- `ui.py`, `setup.py` — modified (one display string each: project name)
- `.gitignore` — modified
- `requirements.txt` — **modified** (v8.45: `anthropic`, `openai`, `ollama`
  declared)
- Retained without modification:
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

The imported file does not carry its license header or copyright notice;
the file is retained byte-for-byte and the license text is therefore
reproduced here, as published by the CryptoJS project
(<https://github.com/brix/crypto-js/blob/develop/LICENSE>):

> The MIT License (MIT)
>
> Copyright (c) 2009-2013 Jeff Mott
> Copyright (c) 2013-2016 Evan Vosberg
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
> THE SOFTWARE.

The copy in this repository does not identify its version; the copyright
holders above are those of the upstream project's published license.
