# Harma AI Android architecture

## Execution flow

```text
Typed/voice command
        ↓
HarmaAgentService (foreground + STOP notification/overlay)
        ↓
AgentOrchestrator
        ↓
Observe accessibility tree / optional screenshot
        ↓
AgentLlmClient → NvidiaAgentClient with OpenAI-compatible tools
        ↓
SafetyGate → confirmation when required
        ↓
AgentToolExecutor
   ├─ Direct native Android tools
   └─ Accessibility screen tools
        ↓
Re-observe, verify, persist trace, repeat or finish
```

## Main modules

- `agent/`: state, system prompt, safety policy, tool boundary, loop, stuck detection, and duplicate-side-effect protection.
- `network/`: provider-neutral messages plus NVIDIA chat-completions, VL `image_url` input, matching `tool_call_id` results, transient reasoning preservation, model fallback, cancellation, and bounded retry/`Retry-After` handling.
- `tools/`: direct native Android capability catalog and executors.
- `accessibility/`: compact indexed UI tree, gestures, global navigation, secure-field detection, screenshots, and window settling.
- `service/`: foreground runtime and floating STOP overlay.
- `voice/`: Android SpeechRecognizer and TextToSpeech wrappers.
- `data/`: encrypted settings and Room task/step/memory storage.
- `notifications/`: notification listener with OTP-like value masking.
- `permissions/`: permission-state inspection and system-settings navigation.
- `ui/`: Compose chat, live trace, screenshots, confirmation dialog, settings, onboarding, and history.

## Harma reference concepts reused

The provided desktop/web Harma project informed these Android-native patterns:

- Central tool registry with name, description, JSON schema, permission risk, and normalized result.
- A single execution boundary: resolve → safety → confirmation → execute → observe → verify.
- SAFE, SENSITIVE, and HIGH_RISK action tiers.
- Tool-and-arguments fingerprints for stuck and duplicate-action detection.
- Distinguishing “tool executed” from “task verified complete.”
- Bounded history/memory and secret filtering.

The reference ADB/web implementations were not copied as the Android runtime. Harma AI uses native Android APIs and an on-device AccessibilityService.

## Safety invariants

- No secret entry or extraction.
- No lock-screen bypass.
- No automatic permission-dialog approval.
- Explicit confirmation for consequential actions.
- A successful call/SMS/alarm fingerprint is never executed twice in one task.
- Maximum step budget and repeated-failure stop.
- Emergency cancellation through chat, notification, overlay, or double Volume Down.

## NVIDIA provider protocol

- Default model: `nvidia/nemotron-3.5-super-vl-120b-a12b`.
- Endpoint: `https://integrate.api.nvidia.com/v1/chat/completions` with bearer authentication.
- Tool schemas use lowercase standard JSON Schema and parallel tool calls are disabled so the safety boundary processes one action at a time.
- Assistant tool-call messages are retained in memory and every tool response uses the exact matching `tool_call_id`.
- Screenshots are resized to a 1280-pixel longest edge and sent as JPEG data URLs. Only the newest screenshot remains in the bounded model history.
- Hidden reasoning is never shown in the UI, written to Room, or logged. It is held only in the in-memory provider conversation when required for continuity.
- The API key is entered at runtime and stored in Android encrypted preferences; it is not compiled into `BuildConfig` or read from `local.properties`.

## Verification states

Native tool results distinguish `verified` from `dispatched`. Torch, volume, ringer, brightness, clipboard, and battery operations include direct state evidence. Intent-based actions remain `dispatched` until a later device observation; app launches are promoted to `verified` only when the accessibility foreground package matches the requested package. A plain model reply cannot finish a task—the model must call the `finish` tool after reviewing evidence.
