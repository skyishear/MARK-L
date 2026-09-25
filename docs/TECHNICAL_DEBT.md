# MARK L — Technical Debt & Future Improvements

> **FUTURE IDEAS ONLY. PLANNING ONLY. NO IMPLEMENTATION IN THE CURRENT VERSION.**
>
> This document enumerates improvements that **may** be implemented in later versions
> of MARK L without changing the current architecture. **Nothing in this document is to
> be implemented in the present version.** It contains no code, defines no API, and
> introduces no architectural change. Items listed here are explicitly **deferred** work.
>
> Any reference to a "future version" is informational. No code, no TODO markers, no
> placeholders, and no architectural changes are introduced by this document. The
> production codebase remains untouched.

---

## How to read this document

Each section is structured around the same set of fields:

- **Purpose** — the high-level idea.
- **Why it is useful** — the concrete benefit.
- **Which module should own it** — the current architectural slot where the
  responsibility would land (informational; no module is created by this document).
- **Why it is NOT implemented now** — explicit reason for deferral.
- **Expected future version** — a soft target (no commitment).
- **Estimated implementation complexity** — low / medium / high.
- **Possible risks** — non-exhaustive, informational only.

Every section **must** be read as a deferred idea, not a current task. This document
is a forward-looking journal, not a TODO list.

---

## 1. AIService future improvements

- **Purpose.** Gradually harden `AIService` so it can serve as the single
  long-term entry point for any model interaction in MARK L.
- **Why it is useful.** Concentrates every AI call behind one stable façade,
  making future cross-cutting concerns (audit, throttling, telemetry) easy to add
  in exactly one place.
- **Which module should own it.** `core.ai_service.AIService` remains the
  only module exposed to callers.
- **Why it is NOT implemented now.** v7.x milestones are deliberately minimal;
  each hardening step must be earned by an explicit later milestone.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Low to medium.
- **Possible risks.** Feature creep, accidental coupling to providers, and
  silently becoming a god-object. Mitigated by keeping the public surface small
  and routing all new behaviour through already-frozen layers.

**Reminder:** these are FUTURE IDEAS ONLY. They are NOT to be implemented in the
current version.

---

## 2. ContextManager future responsibilities

- **Purpose.** Make `ContextManager` the single place where the ordered
  transcript is *shaped* before being sent to a provider.
- **Why it is useful.** A single shaping layer makes it easy to add
  filtering, redaction, summarization, and token budgeting without touching
  providers or routing.
- **Which module should own it.** `core.context_manager.ContextManager`.
- **Why it is NOT implemented now.** The current `ContextManager` is a
  documented identity pass-through, by design.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Medium.
- **Possible risks.** Behaviour drift between providers, hidden context loss,
  and silent message redaction. Mitigated by explicit opt-in and audit logs.

**Reminder:** this section is a FUTURE IDEA ONLY. It is NOT to be implemented
in the current version.

---

## 3. PromptBuilder (future layer only)

- **Purpose.** A small layer that turns a `Message` stream + metadata into the
  exact payload a provider expects (system prompts, structured headers, etc.).
- **Why it is useful.** Centralizes prompt construction so providers stop
  hard-coding message shapes and so future features (system messages, tool
  prompts) can be added without touching routing.
- **Which module should own it.** A new `core.prompt_builder` module,
  introduced **only when needed**, in a future version.
- **Why it is NOT implemented now.** v7.x provides ordered `Message`
  payloads directly; the extra layer would add complexity for no immediate
  gain.
- **Expected future version.** v8.x or v9.x.
- **Estimated implementation complexity.** Medium.
- **Possible risks.** Provider-specific divergence, accidental lock-in to one
  vendor's prompt format, and silent message rewriting. Mitigated by keeping
  the prompt format pure and side-effect free.

**Reminder:** PromptBuilder is a FUTURE LAYER ONLY and is NOT to be created or
implemented in the current version.

---

## 4. Memory Engine integration

- **Purpose.** Allow long-lived memories (facts, preferences, prior outcomes)
  to be considered when preparing provider context.
- **Why it is useful.** Lets the system reason with knowledge accumulated
  across sessions, not only the current transcript.
- **Which module should own it.** A new `core.memory_engine` module, in a
  future version, distinct from any existing `MemoryIndexManager`.
- **Why it is NOT implemented now.** v7.x uses only the in-memory
  `ConversationHistory`; persistent memory is intentionally out of scope.
- **Expected future version.** v9.x.
- **Estimated implementation complexity.** High.
- **Possible risks.** Stale memories, privacy concerns, and accidental coupling
  between memory and provider selection. Mitigated by strict write-time
  validation and a clear ownership boundary.

**Reminder:** Memory Engine integration is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 5. Token budgeting

- **Purpose.** Cap the number of tokens sent to a provider per call, using
  model-specific tokenizer counts.
- **Why it is useful.** Prevents context overflow, stabilizes cost, and
  enables fair sharing of long histories across turns.
- **Which module should own it.** A token-budget strategy attached to
  `ContextManager`; token counting utilities live in a small, separate
  helper module introduced later.
- **Why it is NOT implemented now.** No tokenization layer exists yet; v7.x
  forwards the full ordered transcript.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Medium.
- **Possible risks.** Provider-specific tokenizer differences, off-by-one
  budget errors, and silent truncation of important messages. Mitigated by
  per-provider tokenizer selection and explicit truncation reporting.

**Reminder:** token budgeting is a FUTURE IDEA ONLY and is NOT to be
implemented in the current version.

---

## 6. History trimming

- **Purpose.** Drop or fold older turns when the transcript exceeds a
  configured size or age.
- **Why it is useful.** Keeps very long conversations affordable and
  predictable.
- **Which module should own it.** `ContextManager`, with a pluggable trim
  strategy.
- **Why it is NOT implemented now.** The current `ConversationHistory` is
  the source of truth; trimming must be a derived view.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Low to medium.
- **Possible risks.** Losing important context, surprising users, and
  drift between trimmed and untrimmed transcripts. Mitigated by explicit
  policies and audit-friendly ordering.

**Reminder:** history trimming is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 7. Context filtering

- **Purpose.** Allow `ContextManager` to remove specific message classes
  (e.g. PII, debug noise, internal-only turns) before provider dispatch.
- **Why it is useful.** Privacy, safety, and cost control.
- **Which module should own it.** `ContextManager`, with rule-based
  filters supplied at construction time.
- **Why it is NOT implemented now.** No filtering policies are part of the
  current contract; adding them would change observable behaviour.
- **Expected future version.** v8.x or v9.x.
- **Estimated implementation complexity.** Medium.
- **Possible risks.** Over-aggressive filtering, false sense of privacy, and
  inconsistent filtering across providers. Mitigated by strict policy files
  and per-provider overrides.

**Reminder:** context filtering is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 8. Vector memory / embeddings

- **Purpose.** Enable similarity-based retrieval over long-term memory
  using embeddings and a vector index.
- **Why it is useful.** Surfaces relevant past context that simple
  recency-based history cannot.
- **Which module should own it.** A new `core.vector_memory` module, in a
  future version, isolated from `AIConversationEngine` and providers.
- **Why it is NOT implemented now.** v7.x has no embeddings, no vector
  index, and no async I/O. Adding any of these would be a separate
  architectural decision.
- **Expected future version.** v9.x or later.
- **Estimated implementation complexity.** High.
- **Possible risks.** Embedding drift, vector index staleness, vendor lock-in,
  and new I/O surfaces in a previously network-free architecture. Mitigated
  by an isolated module and a clear migration story.

**Reminder:** vector memory and embeddings are FUTURE IDEAS ONLY. They are
NOT to be implemented in the current version.

---

## 9. Tool calling

- **Purpose.** Allow providers to call structured tools (functions,
  search, file access) and have the result fed back into the conversation.
- **Why it is useful.** Turns MARK L into a true agent harness.
- **Which module should own it.** A future `core.tool_runtime` module,
  gated by the existing `AIService`. Provider-specific tool plumbing
  stays inside provider modules.
- **Why it is NOT implemented now.** Tool calling requires new request /
  response shapes, retries, security boundaries, and async I/O — each of
  which is currently forbidden.
- **Expected future version.** v9.x.
- **Estimated implementation complexity.** High.
- **Possible risks.** Infinite tool loops, unsafe tool execution, and
  inconsistent tool semantics across providers. Mitigated by a centralized
  tool registry and a strict allow-list policy.

**Reminder:** tool calling is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 10. Structured outputs

- **Purpose.** Allow callers to request a typed / schema-validated
  response from any provider.
- **Why it is useful.** Enables deterministic downstream consumption of
  model output.
- **Which module should own it.** A thin `core.structured_output` layer
  that wraps the existing `AIRequest` / `AIResponse` pair.
- **Why it is NOT implemented now.** v7.x providers return plain text;
  schema validation would silently change observable behaviour.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Medium.
- **Possible risks.** Schema drift between providers, silent coercion, and
  validation errors becoming indistinguishable from model errors. Mitigated
  by per-provider schema profiles.

**Reminder:** structured outputs are a FUTURE IDEA ONLY. They are NOT to be
implemented in the current version.

---

## 11. Vision support

- **Purpose.** Allow providers that support vision to receive image
  inputs alongside text.
- **Why it is useful.** Unlocks image-grounded reasoning.
- **Which module should own it.** Provider-specific payload extensions in
  each v7.x provider module; an `Attachment` concept on the request side.
- **Why it is NOT implemented now.** v7.x `AIRequest` carries only
  `prompt` and `history`; no image / attachment concept exists.
- **Expected future version.** v8.x or v9.x.
- **Estimated implementation complexity.** Medium to high.
- **Possible risks.** Provider capability drift, bandwidth / cost spikes,
  and PII leakage via images. Mitigated by capability flags and explicit
  attachment auditing.

**Reminder:** vision support is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 12. Audio support

- **Purpose.** Allow speech-in / speech-out through providers that support
  audio.
- **Why it is useful.** Enables voice-driven flows.
- **Which module should own it.** Provider-specific payload extensions in
  each v7.x provider module, plus an audio transport layer that lives
  **outside** the core AI stack.
- **Why it is NOT implemented now.** v7.x has no audio transport and no
  async I/O.
- **Expected future version.** v9.x or later.
- **Estimated implementation complexity.** High.
- **Possible risks.** Latency, codec support fragmentation, and privacy
  concerns. Mitigated by isolating audio I/O behind a transport interface.

**Reminder:** audio support is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 13. Streaming

- **Purpose.** Allow partial model output to be consumed as it is
  produced.
- **Why it is useful.** Better UX for long generations.
- **Which module should own it.** Provider-specific streaming adapters;
  `AIService` may grow a streaming entry point in a future version.
- **Why it is NOT implemented now.** v7.x is fully synchronous; adding
  streaming would change the call model.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Medium to high.
- **Possible risks.** Buffer management, partial output handling, and
  inconsistent back-pressure semantics across providers. Mitigated by a
  shared streaming interface.

**Reminder:** streaming is a FUTURE IDEA ONLY. It is NOT to be implemented
in the current version.

---

## 14. Retry policy

- **Purpose.** Allow transient failures (timeouts, rate limits) to be
  retried a bounded number of times.
- **Why it is useful.** Improves robustness without changing the public
  call model.
- **Which module should own it.** A future `core.retry_policy` module,
  wired into `AIService`.
- **Why it is NOT implemented now.** Retries are explicitly forbidden in
  v7.x.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Low to medium.
- **Possible risks.** Hiding persistent provider outages, double-billing
  on partial success, and amplifying rate-limit problems. Mitigated by
  bounded, jittered retries and explicit error reporting.

**Reminder:** retry policy is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 15. Fallback policy

- **Purpose.** Allow `AIService` to transparently retry on a different
  provider when the primary one is unavailable.
- **Why it is useful.** Improves availability and vendor diversification.
- **Which module should own it.** A future `core.fallback_policy` module,
  wired into `AIService` (above `AIConversationEngine`).
- **Why it is NOT implemented now.** v7.x has no fallback, by design.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Medium.
- **Possible risks.** Semantic divergence between providers, unexpected
  cost shifts, and silent provider substitution. Mitigated by explicit
  fallback chains and observable substitution logs.

**Reminder:** fallback policy is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 16. Provider capability matrix

- **Purpose.** A small, declarative table describing what each provider
  supports (vision, tools, structured output, languages, rate limits).
- **Why it is useful.** Lets higher layers make informed decisions without
  hard-coding provider names.
- **Which module should own it.** A future `core.provider_capabilities`
  module, registered alongside providers.
- **Why it is NOT implemented now.** v7.x treats providers as black boxes
  with a single synchronous `complete` operation.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Low to medium.
- **Possible risks.** Capability drift as providers evolve, and accidental
  coupling between the matrix and provider selection. Mitigated by versioned
  capability manifests.

**Reminder:** the provider capability matrix is a FUTURE IDEA ONLY. It is
NOT to be implemented in the current version.

---

## 17. Message metadata

- **Purpose.** Allow each `Message` to carry optional metadata (timestamps,
  source, confidence) without changing the textual content.
- **Why it is useful.** Enables richer context shaping, auditing, and
  debugging.
- **Which module should own it.** `core.conversation_history.Message` in a
  future version (additive change, no breaking modification).
- **Why it is NOT implemented now.** v7.x `Message` is a pure data
  record; adding fields would expand its public surface.
- **Expected future version.** v8.x.
- **Estimated implementation complexity.** Low.
- **Possible risks.** Metadata leaking into provider prompts by accident,
  and inconsistent metadata across clients. Mitigated by strict
  metadata-only channels and provider-agnostic metadata schemas.

**Reminder:** message metadata is a FUTURE IDEA ONLY. It is NOT to be
implemented in the current version.

---

## 18. Attachments

- **Purpose.** Allow requests to carry non-textual payloads (images,
  audio, files) via a provider-agnostic attachment concept.
- **Why it is useful.** Foundation for vision, audio, and document
  understanding.
- **Which module should own it.** A future `core.attachments` module,
  introduced alongside vision / audio work.
- **Why it is NOT implemented now.** v7.x has no attachment concept.
- **Expected future version.** v8.x or v9.x.
- **Estimated implementation complexity.** Medium to high.
- **Possible risks.** Provider attachment capability drift, storage /
  bandwidth cost, and privacy / PII concerns. Mitigated by capability
  flags and explicit attachment auditing.

**Reminder:** attachments are a FUTURE IDEA ONLY. They are NOT to be
implemented in the current version.

---

## 19. Performance optimization ideas

- **Purpose.** Capture known optimization opportunities without changing
  the architecture.
- **Why it is useful.** Prevents premature optimization now while
  ensuring future work has a backlog.
- **Which module should own it.** N/A — these are cross-cutting
  observations.
- **Ideas (informational, FUTURE only):**
  - Caching of identical prompts (kept disabled by default).
  - Connection pooling for SDK clients (kept disabled in v7.x to
    preserve lazy-init semantics).
  - Parallel fan-out across providers for non-deterministic ranking
    (kept disabled to preserve single-request determinism).
- **Why it is NOT implemented now.** v7.x forbids caching, async, and
  parallel I/O; optimization in those dimensions is incompatible with the
  current contract.
- **Expected future version.** v8.x or later, on a case-by-case basis.
- **Estimated implementation complexity.** Varies.
- **Possible risks.** Hidden caching leading to stale responses, leaked
  credentials via connection pools, and non-determinism regressions.

**Reminder:** these performance optimization ideas are FUTURE IDEAS ONLY.
They are NOT to be implemented in the current version.

---

## 20. Future architecture diagram (informational, NO implementation)

The following is a high-level, **informational** picture of how a future
version of MARK L might organize responsibilities. **It is not a design
proposal, not an implementation plan, and not a commitment.** It is included
only to anchor the rest of this document.

```
                +---------------------+
                |        Agent        |
                +----------+----------+
                           |
                           v
                +----------+----------+
                |     AIService       |  (single entry point)
                +----+----------+-----+
                     |          |
                     |          +--> ContextManager (shape / filter)
                     |          |       |
                     v          v       v
                +----+----------+-------+-----+
                |   AIConversationEngine     |
                +-------------+--------------+
                              |
                              v
                +-------------+--------------+
                |      AIProviderRouter      |
                +-------------+--------------+
                              |
                              v
                +-------------+--------------+
                |     ProviderRegistry       |
                +-------------+--------------+
                              |
                              v
       +-----------+----------+--------------+----------+
       |           |          |              |          |
       v           v          v              v          v
   OpenAIProvider ClaudeProvider GeminiProvider OllamaProvider ...
```

This diagram is **informational only**. The current architecture already
contains the layers marked `AIService`, `ContextManager`,
`AIConversationEngine`, `AIProviderRouter`, `AIProviderRegistry`, and the
provider modules. Any **new** layers shown implicitly above (e.g. memory
engine, vector memory, tool runtime, retry / fallback policies) are
**FUTURE** and are **NOT** to be introduced in the current version.

---

## Cross-cutting reminder

> **Every item in this document is a FUTURE IDEA ONLY.**
> **No code is to be added, no architecture is to be changed, no public
> API is to be modified, no tests are to be updated, and no placeholders
> are to be inserted in the current version, on the basis of this
> document.**
>
> The current architecture is stable, frozen, and 100% green.
> This document does not change that.

---

## Project assessment

### Estimated project maturity

- **Foundation:** Mature and frozen.
- **v3.x Agent composition:** Mature.
- **v4.x lifecycle:** Mature.
- **v5.x skill dispatch / execution / memory / reflection / learning:**
  Mature.
- **v6.x AI provider abstraction layer:** Mature.
- **v7.0–v7.3 real transports (OpenAI / Claude / Gemini / Ollama):**
  Mature.
- **v7.4 Agent → AIService integration:** Mature.
- **v7.5 Conversation History:** Mature.
- **v7.6 Context Manager layer:** Mature.
- **Overall:** The current version is a stable, well-tested AI-augmented
  foundation. Higher-level features (memory, tools, vision, audio,
  streaming) are intentionally deferred.

### Current architectural health

- **Architecture:** Frozen. No new managers, coordinators, dispatchers,
  executors, services, pipelines, runtime layers, or adapters introduced
  in v7.x.
- **Tests:** 652/652 passing, with architecture-freeze tests, isolation
  tests, and per-module unit tests in place.
- **Provider pluggability:** Confirmed — providers are real, lazy,
  injectable, and unaware of the new context layer.
- **Public APIs:** Stable and backward-compatible across v7.0 → v7.6.
- **Token efficiency:** High — diffs remain minimal and module surfaces
  remain small.
- **Risks:** None at the architectural level. Future risks (listed above)
  are scoped to deferred work.

### Recommended next roadmap milestone

The single recommended next milestone is **v8.0 — ContextManager
hardening**, which would turn `ContextManager.prepare(...)` from an
identity pass-through into a real shaping layer (history trimming, basic
context filtering, and a minimal token-budget strategy) — **all inside
`ContextManager`**, with no changes to providers, routing, the engine, or
the public APIs. This is the natural follow-up to v7.6 and unlocks every
later item in this document.

### Is the current foundation ready for long-term expansion?

**Yes.** The current foundation is ready for long-term expansion:

- The AI stack is pluggable at every layer (`AIService`,
  `ContextManager`, `AIConversationEngine`, `AIProviderRouter`,
  `AIProviderRegistry`, providers).
- New responsibilities can be added to `ContextManager` without
  disturbing providers or routing.
- New providers can be added without changing existing modules.
- New conversation-history semantics can be added additively.
- The architecture-freeze audit will surface any unauthorized change.
- The test suite (652/652) provides strong regression coverage for the
  current contract.

The project is therefore in a strong position to grow incrementally while
preserving its existing guarantees.
