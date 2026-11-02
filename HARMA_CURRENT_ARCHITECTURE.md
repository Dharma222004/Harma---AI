# Harma AI current architecture audit

Audit date: 2026-10-30  
Target device: Realme P3 5G  
Package: `com.personal.harmaai`  
Minimum/target SDK: 30/34

## Verified baseline

- `clean assembleDebug`: passed.
- `testDebugUnitTest`: passed with `NO-SOURCE` (there were no unit tests).
- `lintDebug`: passed with eight dependency-update warnings and no correctness errors.
- APK signature: Android debug certificate, APK Signature Scheme v2.
- Connected Android devices: none. Hardware, OEM background behavior, and third-party app flows are not device-verified.

## Runtime flow

```text
Compose chat / Android SpeechRecognizer
                 |
                 v
HarmaAgentService (foreground notification, wake lock, STOP overlay)
                 |
                 v
AgentOrchestrator
  |-- capture accessibility tree / optional JPEG screenshot
  |-- add bounded Room memory
  |-- call the configured LLM with tool declarations
  |-- pass the selected tool through SafetyGate
  |-- execute one native or accessibility tool
  |-- wait for UI settlement and observe again
  |-- persist the step and repeat, finish, or stop
                 |
                 v
AgentRuntime StateFlow -> chat, confirmation dialog, action log, TTS
```

## Existing components to retain

- `AgentOrchestrator`: bounded observe/decide/act loop, cancellation, repeat-failure detection, step persistence.
- `AgentToolExecutor` and `ToolRegistry`: one controlled execution boundary for native and accessibility tools.
- `SafetyGate`: lock/protected-screen checks and user confirmation for consequential actions.
- `AgentAccessibilityService`: compact indexed UI tree, gestures, text entry, global navigation, screenshots, UI-settle events, emergency volume-key stop.
- `DirectToolExecutor`: torch, volume, app launch, brightness, alarms/timers, calls/SMS, URLs/search, settings panels, battery, and clipboard.
- `HarmaAgentService` and `FloatingStopOverlay`: foreground execution and visible cancellation.
- `SettingsStore`, Room entities/DAOs, Compose UI, speech recognition, TTS, and permission onboarding.

## Components that require refactoring

- `GeminiAgentClient` and provider-shaped conversation JSON are coupled to Gemini. The orchestrator needs a provider-neutral message/tool contract and a new NVIDIA OpenAI-compatible implementation.
- Tool schemas use Gemini-style uppercase JSON Schema types. They need standards-compliant lowercase types for OpenAI-compatible endpoints.
- Settings and UI name Gemini-specific keys/models. They need NVIDIA naming, safe migration, and the requested default model.
- Execution verification is uneven: torch and volume read back state, while intent launches and most UI actions only prove dispatch, not end-to-end completion.
- Conversation continuation is incomplete: `ask_user` ends the service run and a reply starts a new task instead of resuming the paused plan.
- Memory is a small ordered Room list rather than task-aware retrieval. Commands and screenshots also need stronger sensitive-data retention controls.

## Architectural bottlenecks and risks

- Every step is serialized through a remote model; latency and rate limiting directly affect UI automation.
- Screenshots are base64 encoded, sent whole, and retained as ordinary app-private JPEG files without pruning.
- The foreground run is not persisted/resumable after process death and uses a 15-minute wake-lock cap.
- Accessibility nodes can become stale between observation and action; there is no automatic element re-resolution.
- No OCR or local visual grounding exists when accessibility metadata is sparse.
- The APK is debug-signed. A stable release key improves update identity but cannot guarantee that Play Protect will accept an app using accessibility, overlays, notification access, calls, and SMS.
- A provider API key stored in any client APK can be extracted at runtime. Encrypted preferences protect at rest, not against a determined device owner or repackager; a small authenticated backend proxy is the production-safe design.

## Post-audit implementation update

The 1.1.0 upgrade kept the audited Android architecture and replaced the active Gemini-coupled path with `AgentLlmClient` plus `NvidiaAgentClient`. The active model is now `nvidia/nemotron-3.5-super-vl-120b-a12b`; tool calls, tool-call IDs, VL screenshots, retries, and model history use the NVIDIA/OpenAI-compatible protocol. Gemini code remains only as inactive legacy provider code.

Tool schemas are now standard lowercase JSON Schema. Results distinguish verified state from dispatched intent, app launches compare the requested package to the observed foreground package, plain text cannot silently complete a task, screenshots are resized and pruned, sensitive commands are redacted from Room history, and an in-memory answer can continue an `ask_user` pause. Runtime API-key entry no longer enters BuildConfig or Compose saved-instance state.

