# Harma AI manual test checklist

## Installation and setup

- [ ] `assembleDebug` succeeds.
- [ ] `assembleRelease` produces a signed, non-debuggable APK with the persistent Harma AI certificate.
- [ ] APK installs as `com.personal.harmaai`.
- [ ] Launcher name and all screens say **Harma AI**.
- [ ] NVIDIA API key is masked in Settings and survives restart.
- [ ] The APK does not contain a bootstrap API key or read one from `local.properties`.
- [ ] Primary model is `nvidia/nemotron-3.5-super-vl-120b-a12b`.
- [ ] Accessibility service is enabled.
- [ ] Overlay and notification permissions are enabled.
- [ ] Camera and microphone permissions are granted.
- [ ] On the Realme P3 5G, Auto launch and Allow background activity are enabled, battery use is unrestricted, and Harma AI is locked in Recents.

## Direct tools

- [ ] “Turn on the flashlight” switches the torch on.
- [ ] “Turn off the flashlight” switches it off.
- [ ] “Set media volume to 40 percent” changes and reports actual volume.
- [ ] “Open Settings” launches Android Settings.
- [ ] “Set an alarm for 6 AM” creates the alarm.
- [ ] “Start a five-minute timer” starts the timer.
- [ ] “Open example.com” launches the browser.
- [ ] “What is my battery percentage?” reports battery state.

## Sensitive actions

- [ ] Calls show a Harma AI confirmation before `ACTION_CALL`.
- [ ] SMS shows a confirmation with the recipient/message details redacted appropriately.
- [ ] Denying confirmation prevents the action.
- [ ] A repeated successful call/SMS is not executed twice.

## Accessibility agent

- [ ] “Open YouTube and search for lo-fi music” opens YouTube, finds the search field, types, and submits.
- [ ] Indexed taps are shown in the live action log.
- [ ] Scrolling updates the screen observation.
- [ ] Canvas/WebView-like screens trigger screenshot vision when enabled.
- [ ] Password fields stop the agent without reading or typing.
- [ ] Locking the phone stops with the unlock instruction.

## Voice and cancellation

- [ ] Mic button transcribes a command and starts a task.
- [ ] Completed response is spoken when TTS is enabled.
- [ ] In-app STOP cancels immediately.
- [ ] Notification STOP cancels immediately.
- [ ] Floating overlay STOP cancels while another app is open.
- [ ] Double-press Volume Down cancels while Accessibility is enabled.

## Reliability

- [ ] A missing app produces a clear failure instead of looping.
- [ ] Denied permission produces a setup instruction.
- [ ] Three identical failed actions stop the loop.
- [ ] The 25-step limit stops an unfinished task.
- [ ] NVIDIA authentication/rate-limit/server errors are reported without exposing the API key.
- [ ] A tool-call response preserves the matching NVIDIA `tool_call_id` before the next model request.
- [ ] Task status and summary appear in History.
