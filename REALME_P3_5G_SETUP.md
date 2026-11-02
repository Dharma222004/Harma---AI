# Harma AI setup on Realme P3 5G

Use the signed release APK at `app/build/outputs/harma/Harma-AI-release.apk`.

## Install

1. On the phone, allow installs from the file manager/browser used to open the APK, or enable USB debugging and use:

   ```powershell
   & "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe" install -r ".\app\build\outputs\harma\Harma-AI-release.apk"
   ```

2. If Android shows **Restricted settings**, open **App info → menu → Allow restricted settings**, then return to Accessibility. Realme UI wording can vary.
3. A stable release signature improves update identity but cannot guarantee that Play Protect will accept an accessibility-automation app. Only continue with the APK you built in this workspace.

To verify the local file before copying it:

```powershell
Get-FileHash -Algorithm SHA256 ".\app\build\outputs\harma\Harma-AI-release.apk"
```

## First-run configuration

1. Open **Harma AI → Settings** and enter a newly rotated NVIDIA key. Keep the model as `nvidia/nemotron-3.5-super-vl-120b-a12b`.
2. Grant microphone and camera. Grant contacts, phone, and SMS only if those tools are required.
3. Enable **Harma AI phone control** in Accessibility.
4. Allow **Display over other apps** for the emergency STOP control.
5. Optionally enable Notification access for notification-reading tasks.
6. Enable Modify system settings for brightness and Do Not Disturb access for silent-mode actions.

## Realme background settings

In Realme UI, search Settings for Harma AI and enable:

- Auto launch.
- Allow background activity/background running.
- Unrestricted or no-optimization battery use.
- Notification permission for the foreground task indicator.

Also open Recents and lock Harma AI so Realme UI is less likely to terminate a multi-app task. These controls are manual and their menu names vary by firmware.

## Safe validation order

Test flashlight, battery, volume, and opening Settings first. Then test YouTube search. Test WhatsApp messaging last and confirm that Harma AI asks before pressing the final Send action. Keep the floating STOP control visible throughout UI-automation tests.

Back up `signing/harma-ai-release.jks` together with the private `keystore.properties` file. Both are required to produce future APK updates that Android accepts over this installation.
