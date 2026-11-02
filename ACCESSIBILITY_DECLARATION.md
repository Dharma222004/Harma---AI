# Google Play Accessibility API Declaration

Copy and paste this disclosure into the **Accessibility API Policy** section in Google Play Console:

---

### Question 1: Is your app an Accessibility Tool?
- **Answer:** **No** (Harma AI is an autonomous device assistant that uses the Accessibility API to automate user-requested tasks on their behalf, rather than being an assistive service specifically designed for users with disabilities).

---

### Question 2: Prominent Disclosure & Purpose
Provide the following description in the Play Console declaration form and in the app's in-app onboarding:

> **Why Harma AI needs the AccessibilityService API:**
> 
> Harma AI uses the Android AccessibilityService API exclusively to perform user-requested device automation tasks via natural language or voice commands. Specifically, the service allows Harma AI to:
> 1. Observe active on-screen interactive elements (buttons, text fields, lists) solely to identify what to tap, scroll, or type to fulfill your explicit instruction.
> 2. Perform navigation actions (tap, scroll, go back, return to home) on your behalf.
> 
> **Important Safety & Privacy Protections:**
> - **Zero Sensitive Data Access:** Harma AI strictly ignores and refuses to interact with password fields, PIN entry screens, OTPs, CVVs, UPI screens, or banking/payment authentication screens (`FLAG_SECURE`).
> - **No Background Snooping:** The screen is only observed during active, user-initiated commands.
> - **Always in Your Control:** Every action is visible in real-time, and you can stop execution instantly via the persistent notification "STOP" button or by double-pressing the Volume Down key.
> - **No Unauthorized Changes:** Harma AI never modifies system security settings or prevents users from uninstalling or disabling apps.

---

### Question 3: Link to Video Demonstration
Upload a video showing the in-app disclosure screen, enabling the accessibility service in system settings, and executing an autonomous command (e.g. "open paytm"):
- **YouTube Link:** `[Add your unlisted YouTube demo video link here]`

