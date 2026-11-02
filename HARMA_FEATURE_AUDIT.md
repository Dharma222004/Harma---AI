# Harma AI feature audit

Statuses are based on source-path inspection plus a successful local build/lint run. Features requiring a physical phone are not marked fully implemented until device verification.

| Capability | Status | Evidence / limitation |
|---|---|---|
| Typed chat UI and action log | IMPLEMENTED | Compose chat, live steps, confirmation dialog, screenshots, history, and STOP control compile successfully. |
| Push-to-talk speech recognition | PARTIALLY IMPLEMENTED | Android `SpeechRecognizer` is wired to task submission; not tested on the Realme P3 5G and has no multi-turn continuation. |
| Text-to-speech | PARTIALLY IMPLEMENTED | Speaks completed summaries; no barge-in/interruption handling or device verification. |
| Continuous listening / “Hey Harma” | MISSING | No wake-word engine or microphone foreground service. |
| Provider-independent LLM layer | MISSING | The active client and history are Gemini-specific. |
| Requested NVIDIA model | MISSING | No NVIDIA endpoint, bearer authentication, OpenAI tool calls, or `image_url` messages exist. |
| Function/tool calling | PARTIALLY IMPLEMENTED | Gemini tool declarations and one-tool execution exist; no live API validation and no provider-neutral schema. |
| Streaming response | MISSING | Current network call waits for one complete JSON response. |
| Cancellation | IMPLEMENTED | Coroutine cancellation cancels the OkHttp call; in-app, overlay, notification, and accessibility volume-key stops exist. |
| Task planning / dynamic selection | PARTIALLY IMPLEMENTED | The model dynamically selects tools in a bounded loop; there is no explicit durable plan graph or conditional task state. |
| Retry and model fallback | PARTIALLY IMPLEMENTED | Basic HTTP/model fallback exists for Gemini; no `Retry-After`, jitter, structured provider errors, or fallback provider. |
| Replanning and stuck detection | PARTIALLY IMPLEMENTED | Three identical failed calls stop the run, but no explicit recovery policy or stale-node re-resolution exists. |
| Long-running task management | PARTIALLY IMPLEMENTED | Foreground service and wake lock exist; runs are not resumable after process death/reboot. |
| Flashlight | PARTIALLY IMPLEMENTED | Uses `CameraManager`, registers torch callback, and checks state; physical torch not verified. |
| Volume / ringer | PARTIALLY IMPLEMENTED | Native APIs and read-back exist; DND/OEM behavior not device-tested. |
| App launch | PARTIALLY IMPLEMENTED | Package resolution and launch intent exist; final foreground package is not verified. |
| Brightness | PARTIALLY IMPLEMENTED | Native setting write with special-access check; Realme behavior not tested. |
| Wi-Fi / Bluetooth | NEEDS IMPROVEMENT | Correctly opens restricted Android settings; it cannot silently toggle on modern Android. |
| Alarm / timer | PARTIALLY IMPLEMENTED | Uses AlarmClock intents; creation is not read back or device-tested. |
| Calls / SMS | PARTIALLY IMPLEMENTED | Permissions, contact lookup, confirmation, and execution exist; no physical verification. |
| Battery / clipboard | PARTIALLY IMPLEMENTED | Native reads/writes exist; clipboard access remains subject to Android foreground restrictions. |
| Location, device information, camera capture, file operations | MISSING | No registered tools or implementations. |
| Accessibility tree observation | PARTIALLY IMPLEMENTED | Compact indexed nodes and secure-field detection exist; stale nodes and OEM/app-specific trees need device tests. |
| Tap/type/scroll/swipe/global actions | PARTIALLY IMPLEMENTED | Implemented in the accessibility service; no instrumentation or Realme verification. |
| Screenshot vision | PARTIALLY IMPLEMENTED | API 30 screenshot capture and Gemini inline data exist; no NVIDIA image schema yet, OCR, resize budget, or visual grounding. |
| Verification engine | NEEDS IMPROVEMENT | Observation is fed back to the model, but most tools do not assert expected versus actual state. |
| Short-term context | PARTIALLY IMPLEMENTED | Recent messages are bounded; older turns are dropped rather than summarized. |
| Persistent task history | IMPLEMENTED | Room task/step persistence compiles; no physical persistence test was possible. |
| Long-term user memory | PARTIALLY IMPLEMENTED | A small importance-ordered Room table is injected; no extraction UI, semantic retrieval, or user correction flow. |
| Permission onboarding | PARTIALLY IMPLEMENTED | Runtime and special-access pages are present; permissions are requested as a broad bundle rather than just in time. |
| App allow/deny policy | PARTIALLY IMPLEMENTED | Settings and checks exist but match user strings/package fragments and need stronger package normalization. |
| Secret and sensitive-action safety | PARTIALLY IMPLEMENTED | Password/OTP/payment detection and confirmations exist; broad text regexes can false-positive and commands may still be persisted. |
| Realme/ColorOS background setup | PARTIALLY IMPLEMENTED | OPlus/ColorOS autostart intents exist; exact P3 firmware path and successful grant cannot be detected reliably. |
| Release signing / distributable APK | MISSING | Current output is debug-signed only. |
| Automated tests | MISSING | Gradle unit test task reports `NO-SOURCE`; no instrumentation tests exist. |

## Upgrade delta

After this baseline audit, the active provider-neutral NVIDIA layer, matching tool-result IDs, VL data URLs, lowercase schemas, bounded retries, screenshot resizing/history control, secure runtime key configuration, Realme P3 guidance, release signing, and JVM protocol/safety tests were implemented. Streaming, wake word, OCR, semantic memory, process-death resume, and physical Realme verification remain open and are tracked in `FEATURE_STATUS.md`.

