# Harma AI implementation roadmap

## Phase 0 — audit and reproducible baseline

- Preserve the existing project and record architecture, feature status, gaps, signing state, lint, tests, and device availability.
- Complete when all five audit/status documents exist and the untouched source builds.

## Phase 1 — NVIDIA model migration (current upgrade)

- Add provider-neutral message/decision/client contracts.
- Implement NVIDIA's OpenAI-compatible chat-completions client.
- Support the requested model, standard tool calls, screenshot `image_url` data URLs, reasoning content, streaming, cancellation, structured errors, `Retry-After`, and bounded retry/fallback.
- Convert tool schemas to standard JSON Schema.
- Rename Gemini settings/UI/documentation to NVIDIA and avoid embedding an API key.
- Add deterministic JVM tests and rebuild/lint.

Status: completed for the non-streaming protocol. Streaming remains deferred until incremental tool-call assembly can be validated without weakening correctness.

## Phase 2 — reliability and verification

- Introduce explicit expected/actual verification for app launch, alarms, intents, and UI transitions.
- Add stale-node recovery, structured failure categories, retry budgets, and better no-network guidance.
- Implement safe continuation for `ask_user` and resumable task state.
- Add screenshot resize/token/retention controls and history summarization.

## Phase 3 — Realme deployment and release identity

- Add Realme P3 5G / Realme UI setup guidance and robust settings fallbacks.
- Add a persistent, locally protected release-signing configuration.
- Build and verify the release APK/certificate. Document that Play Protect decisions cannot be guaranteed.

Status: source guidance, persistent release signing, and signed-APK certificate verification are implemented; device-side settings and installation still require the Realme P3 5G.

## Phase 4 — physical-device validation

- Connect the Realme P3 5G and validate permissions, background survival, STOP controls, torch, volume, app launch, YouTube, WhatsApp confirmation/send flow, screenshots, and cancellation.
- Capture failures by package/firmware and adjust selectors/delays without hardcoding a single app workflow.

## Phase 5 — optional autonomy expansion

- Add wake word behind a replaceable interface, OCR/visual grounding, durable multi-turn tasks, and narrowly scoped additional native tools.
- Treat payments, authentication, permanent deletion, installation, and security settings as user-controlled handoff flows, not unattended automation.

