# V6 — Owner attestation checklist (Windows desktop)

Contract V6 (`docs/EDITH_COMPLETION_CONTRACT.md` §6, §15) is the owner's manual
check that the v8.x production wiring works on a real Windows desktop. It
covers what an agent cannot verify: the GUI, audio, Windows-only packages, live
provider calls and Gemini Live. **Only the owner fills in §15; an agent never
marks V6 passed (OD-10).**

Commit to test: the head of branch `claude/sharp-gauss-vuud98` (record its
`git rev-parse --short HEAD` below). Estimated time: 20–30 minutes.

## 0. Prepare

- [ ] `git fetch && git checkout claude/sharp-gauss-vuud98 && git pull`
- [ ] Note the commit hash: `__________`
- [ ] Fresh virtual environment: `python -m venv .venv`, activate it, then
      `pip install -r requirements-dev.txt`
- [ ] Gemini API key is in the config (`config/api_keys.json` as the app expects).
- [ ] Automated suite on Windows: `python -m pytest -q` → all pass
      (expected at this commit: **2798 passed**). Count: `______`
      *(Windows-only packages that a Linux run skips are exercised here.)*

## 1. Launch

- [ ] `python main.py` starts; the UI window opens; no traceback in the console.
- [ ] Console shows no `[Memory] ⚠️ v8 memory import skipped` line
      (if it appears, note the reason: `__________`).
- [ ] The assistant connects to Gemini Live (state leaves "connecting").

## 2. One live provider call

- [ ] Say or type a plain question (e.g. "what is two plus two"). The reply is
      spoken/shown. (Plain Live conversation works.)

## 3. One voice turn that makes a tool call (the main V6 check)

Use a read-only tool first.

- [ ] Say: "What is my system status?" (`system_status`).
      Console shows `[JARVIS] 📞 system_status` and `🔧 system_status`, and the
      assistant answers with real values. **No error text** such as
      `error: refused (...)` or `error: failed (...)` is spoken.
- [ ] Say: "Search the web for today's weather news" (`web_search`). It answers
      from results.

## 4. Behaviour that must still hold (legacy gates kept)

- [ ] **Side-effecting tool:** ask it to open an app (e.g. "open Notepad").
      It opens (the production confirmation hook approves; the spoken request is
      the confirmation).
- [ ] **PIN gate:** with a PIN set and not unlocked, ask for a high-risk action
      (e.g. delete a file). The assistant refuses and asks for the PIN; after
      "unlock with PIN …" the action works. (Same behaviour as before v8.44.)
- [ ] **Memory:** say "remember that my favourite colour is green", then in a new
      turn "what is my favourite colour?" → answers green.
- [ ] **Skills:** ask for the weather (skill tool). It answers.

## 5. Evidence the v8.x path is used (OD-C limit)

The per-run limits are observable: at most **5 model rounds / 10 tool
executions per turn**.

- [ ] Ask for a task that needs many tool steps in one request (e.g. "open
      Notepad, then Calculator, then Paint, then Chrome, then File Explorer, one
      after another"). After the limit the assistant reports that it could not
      continue, and the console/answer carries `error: failed
      (ToolLoopExhaustedError)` for the extra calls. The **next** spoken turn
      works normally again (the run resets at turn end).
- [ ] If tool replies never arrive or the session hangs after a tool call, note
      it exactly: `__________` — this would falsify the assumption that
      `turn_complete` is not sent between a tool call and its response.

## 6. Record the result

Fill the table in `docs/EDITH_COMPLETION_CONTRACT.md` §15 yourself:

| Date | Commit | Checks run | Result | By |
|---|---|---|---|---|
| `<date>` | `<hash>` | launch · live provider call · voice tool-call turn (§1–§3), plus §4–§5 | PASSED / FAILED (+ notes) | `<you>` |

Any failure: copy the console output and the step number, and give it to the
agent as a bug report — the next milestone is derived from it.
