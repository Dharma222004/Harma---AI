# Harma AI feature status

Last updated: 2026-10-31

## Play Protect & Release Upgrade Status

- [x] Full audit of `AndroidManifest.xml` and tool/service declarations.
- [x] Removed dangerous permissions triggering Play Protect financial fraud block (`SEND_SMS`, `CALL_PHONE`, `READ_CONTACTS`, `CAMERA`, and `BIND_NOTIFICATION_LISTENER_SERVICE`).
- [x] Replaced direct SMS sending with safe Android `ACTION_SENDTO` intent (zero SMS permissions required).
- [x] Replaced direct phone calling with safe Android `ACTION_DIAL` intent (zero phone permissions required).
- [x] Converted flashlight to native `CameraManager.setTorchMode` (zero camera permissions required).
- [x] Replaced background notification listener with transparent accessibility notification panel trigger.
- [x] Bumped targetSdk to 34, compileSdk to 34, versionCode to 3, versionName to 1.2.0.
- [x] Generated standard Android adaptive launcher icons (mdpi, hdpi, xhdpi, xxhdpi, xxxhdpi, and anydpi with Material You monochrome support).
- [x] Enabled R8 code shrinking and resource shrinking with comprehensive `proguard-rules.pro`.
- [x] Verified encrypted runtime preferences for API keys (no hardcoded secrets).
- [x] Implemented in-app explanation rationale dialogs and just-in-time permission requests.
- [x] Release APK signed with persistent RSA-3072 key (APK Signature Scheme v2 verified).
- [x] Gradle unit tests passed, Android lint passed with 0 errors.
- [x] Provided step-by-step ADB installation instructions.
