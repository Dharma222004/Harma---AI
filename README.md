# Harma AI — Autonomous Android Agent

Harma AI is a personal-use, sideloaded Android agent that can interpret a typed or spoken command, use NVIDIA Nemotron tool calling, execute a native Android or accessibility tool, observe the result, and continue until the task is complete.

- Package: `com.personal.harmaai`
- Minimum Android: 11 / API 30
- Target Android: 14 / API 34
- Version: 1.2.0 (code 3)

## Implemented capabilities

- NVIDIA OpenAI-compatible tool calling with configurable primary/fallback models
- Direct flashlight control via native CameraManager torch (zero camera permission required)
- App launch, volume/ringer, global brightness, alarms, timers, URLs, web searches, settings panels, battery, and clipboard
- Safe phone dialing (`Intent.ACTION_DIAL`) and safe SMS drafting (`Intent.ACTION_SENDTO`) without dangerous telephony/SMS permissions
- Accessibility UI tree observation with stable element indexes
- Indexed taps, coordinate taps, long press, text entry, scrolling, swipes, Back/Home/Recents/notifications/quick settings
- Screenshot fallback for NVIDIA vision-language reasoning
- Foreground observe → think → act → verify loop with a 25-step default limit
- Three-repeat stuck detection and duplicate consequential-action protection
- Sensitive-action confirmation for calls, SMS, payment/send/delete-style taps, and other risky tools
- Password, PIN, OTP, card, login, protected-screen, and lock-screen safeguards
- Always-visible STOP overlay and double-press Volume Down emergency stop
- Push-to-talk Android speech recognition with clear in-app rationale dialog and optional text-to-speech results
- Permission onboarding with individual, clearly explained cards requested just in time
- Room task/step history and filtered local memory
- Allow/deny app lists
- ProGuard / R8 code and resource shrinking enabled for minimal release footprint
- Adaptive launcher icons across all screen densities with Material You monochrome support

## Keystore generation and release build

### 1. Keystore generation command
The persistent release keystore was created using Java's `keytool`:

```powershell
& "$env:JAVA_HOME\bin\keytool.exe" -genkeypair -v -keystore "signing\harma-ai-release.jks" -alias "harma-ai" -keyalg RSA -keysize 3072 -validity 10000 -storetype PKCS12 -dname "CN=Harma AI Personal, OU=Personal Android, O=Harma AI, L=Local, ST=Local, C=IN"
```

The keystore credentials are configured in `keystore.properties`:
```properties
storeFile=signing/harma-ai-release.jks
storePassword=<password>
keyAlias=harma-ai
keyPassword=<password>
```

### 2. Build release APK
Run from PowerShell in this repository:

```powershell
.\gradlew.bat clean testDebugUnitTest lintDebug assembleRelease
```

Generated signed release APK:
```text
app\build\outputs\harma\Harma-AI-release.apk
```

## Install over USB debugging (ADB)

1. **Enable Developer Options on phone**:
   - Go to **Settings → About device → Version**.
   - Tap **Build number** 7 times until you see "You are now in Developer mode!".
2. **Enable USB Debugging**:
   - Go to **Settings → Additional settings / System → Developer options**.
   - Turn ON **USB debugging** (and **Install via USB** if present on Realme/ColorOS).
3. **Connect phone to PC**:
   - Connect via USB cable.
   - On the phone, accept the prompt: "Allow USB debugging from this computer? Check 'Always allow' and tap 'Allow'".
4. **Verify ADB connection**:
   ```powershell
   & "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" devices
   ```
5. **Install APK**:
   ```powershell
   & "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r ".\app\build\outputs\harma\Harma-AI-release.apk"
   ```

## Required first-run setup

Open Harma AI and complete the setup cards:

1. **Microphone**: Tap the microphone icon or the card; approve the clear explanation to speak voice commands.
2. **Accessibility**: Select **Harma AI phone control** and enable it. (On Android 13+, if greyed out: open **Settings → Apps → Harma AI → ⋮ (top right) → Allow restricted settings** first).
3. **Display over other apps**: Allow Harma AI's emergency floating STOP overlay.
4. **Battery optimization exemption**: Recommended for multi-app agent tasks.
5. **Modify system settings**: Needed for global brightness changes.
6. **Do Not Disturb access**: Needed for silent/ringer mode changes.
7. **Realme UI / ColorOS background**: Enable **Auto launch**, **Allow background activity**, and lock Harma AI in Recents.

## First tests

1. `Turn on the flashlight.`
2. `Set media volume to 40 percent.`
3. `Open Settings.`
4. `Set an alarm for 6:00 AM called Wake up.`
5. `Open YouTube and search for lo-fi music.`
6. `Send an SMS saying hello to 9876543210.` — confirm the safety dialog.
