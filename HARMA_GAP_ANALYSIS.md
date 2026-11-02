# Harma AI gap analysis

| Feature | Existing status | Problem | Required changes | Priority |
|---|---|---|---|---|
| NVIDIA Nemotron 3.5 Super VL | MISSING | Active Gemini REST format is incompatible. | Add OpenAI-compatible `/v1/chat/completions` client for `nvidia/nemotron-3.5-super-vl-120b-a12b`, bearer auth, tool calls, image data URLs, reasoning fields, retries, cancellation, and streaming parsing. | P0 |
| Provider-neutral agent contract | MISSING | Orchestrator stores Gemini response JSON. | Introduce neutral conversation messages and decision models; depend on an interface rather than a concrete provider. | P0 |
| Secure provider configuration | NEEDS IMPROVEMENT | Gemini build constants and preference names remain; any client-side key is extractable. | Rename/migrate settings, never commit the posted key, document rotation and backend proxy option. | P0 |
| JSON tool schema | NEEDS IMPROVEMENT | Schema types are uppercase and Gemini-oriented. | Emit standard lowercase JSON Schema and OpenAI `tools` declarations. | P0 |
| Visual input | PARTIALLY IMPLEMENTED | JPEG capture exists but uses Gemini inline-data format and has no size policy. | Encode an OpenAI `image_url` data URL, constrain dimensions/quality, and omit stale screenshots from history. | P0 |
| Reliable action completion | NEEDS IMPROVEMENT | Many results mean “intent dispatched” rather than “goal achieved.” | Add expected-state checks, package/window verification, failure codes, and explicit finish rules. | P1 |
| Paused user interaction | BROKEN | `ask_user` stops; the user's response starts an unrelated new task. | Persist pending session state and resume it with the reply, or clearly scope `ask_user` as task termination until implemented. | P1 |
| Realme P3 5G resilience | PARTIALLY IMPLEMENTED | OEM autostart/background controls vary and are not observable. | Add Realme-specific onboarding copy, app-details fallback, battery/background checklist, and physical validation. | P1 |
| Release provenance | MISSING | Debug certificate changes provenance expectations and is unsuitable for stable updates. | Add configurable persistent release signing and verify the release certificate. Do not promise removal of Play Protect warnings. | P1 |
| Sensitive-data retention | NEEDS IMPROVEMENT | User commands and screenshot files can contain private data; screenshot files are not pruned. | Redact/avoid secret-bearing tasks, add retention controls, delete orphan screenshots, and keep provider logs free of keys. | P1 |
| Automated verification | MISSING | No tests exist. | Add JVM tests for provider serialization/parsing, schema conversion, retry classification, and safety behavior; add device test checklist. | P1 |
| Wake word | MISSING | Voice is push-to-talk only. | Add a replaceable wake-word interface and foreground microphone service only after privacy/battery design and key choice. | P2 |
| OCR / visual grounding | MISSING | Sparse-tree screens depend entirely on the remote VLM guessing from a screenshot. | Add OCR/grounding and coordinate normalization with confidence thresholds. | P2 |
| Durable tasks and memory | PARTIALLY IMPLEMENTED | No process-death resume or relevant retrieval. | Persist task state transitions, summarize history, and add user-controlled memory management. | P2 |
| Additional device tools | MISSING | Location, device info, camera capture, and file operations are absent. | Add narrowly scoped native controllers and just-in-time permission policies as actual use cases require. | P3 |

## Existing bugs and weaknesses

- The UI and documentation contain stale Gemini naming and some mojibake punctuation.
- A plain model text reply without a `finish` tool is currently treated as successful completion even without device evidence.
- Model fallback messaging assumes that a different model is always a valid substitute.
- Consequential duplicate protection covers calls, SMS, alarms, and timers, but not equivalent sensitive UI taps.
- `fallbackToDestructiveMigration()` can erase history on a future schema change.
- Screenshot files are not deleted when old Room rows are removed.
- Autostart intent launch is treated as success even if the selected OEM activity immediately rejects or redirects.

## Reuse / refactor / create

- Reuse: accessibility service, native tools, safety gate, foreground service, overlay, Compose screens, Room, voice wrappers.
- Refactor: orchestrator conversation model, tool schema generation, settings names/defaults, verification results, retention behavior.
- Create: provider-neutral LLM models/interface, NVIDIA client and SSE parser, NVIDIA serialization/parser tests, release-signing configuration, Realme P3 setup guide.

## Resolution update

- Resolved in 1.1.0: active NVIDIA client, provider-neutral messages, matching tool-call IDs, lowercase schemas, VL image transport and resizing, secure runtime configuration, verified/dispatched evidence, app foreground verification, completion-tool enforcement, screenshot retention cap, Realme setup guidance, persistent release signing, and initial JVM tests.
- Partially resolved: `ask_user` can continue in memory, but not after process death; verification is stronger, but arbitrary third-party UI workflows still rely on model interpretation of the observed tree/screenshot.
- Still open: streaming, wake word, OCR/local grounding, durable plans, semantic memory, additional location/file tools, instrumentation tests, and physical Realme P3 validation.

