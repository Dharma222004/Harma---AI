# Privacy Policy for Harma AI

**Effective Date:** October 31, 2026  
**Application:** Harma AI (`com.personal.harmaai`)

Harma AI is an autonomous, on-device AI assistant designed to help users control their Android phone via voice and natural language commands. We are committed to maintaining the highest standards of user privacy, security, and data transparency.

---

### 1. Data We Do NOT Collect
- **Passwords, PINs, and Financial Data:** Harma AI strictly ignores and refuses to interact with password fields, PIN entry screens, OTPs, CVVs, UPI screens, and payment authentication interfaces.
- **Personal Identifiers:** We do not collect names, phone numbers, email addresses, or contacts without explicit user interaction.
- **Advertising or Tracking IDs:** Harma AI contains no advertisements, analytics trackers, or third-party tracking SDKs.

---

### 2. How the AccessibilityService API is Used
Harma AI uses Android's `AccessibilityService` API strictly to execute actions requested directly by you (such as opening apps, tapping buttons, and entering text):
- **On-Screen Content:** Harma AI reads the active window UI tree only during an active user command to identify buttons and text relevant to your instruction. This data is processed ephemerally and is never sold, shared, or stored for telemetry.
- **Security Screens (`FLAG_SECURE`):** Harma AI automatically detects protected screens and halts execution so you can enter sensitive credentials manually.
- **User Control:** You retain full control at all times. Any running task can be immediately terminated using the persistent "STOP" button in the notification shade or by pressing the physical Volume Down key twice.

---

### 3. Audio & Voice Input
- When you use voice commands ("Hey Harma" or tapping the microphone button), audio is captured locally and converted to text using the Groq Whisper speech-to-text API over secure HTTPS/TLS.
- Audio is never recorded in the background while Harma AI is idle, and raw audio files are discarded immediately after transcription.

---

### 4. AI Processing
- Text commands and screen context are sent to the user-configured LLM provider (e.g. NVIDIA NIM API) over an encrypted HTTPS connection solely to generate the tool actions required to fulfill your command.
- API keys entered by the user are stored locally on the device using Android Jetpack EncryptedSharedPreferences (AES-256 GCM).

---

### 5. Local Storage & Deletion
- All task history, step logs, and user memories are stored strictly locally in an on-device SQLite database (`harma_ai.db`).
- You can clear all history and memory at any time within Harma AI Settings, or by clearing app storage in Android Settings.

---

### 6. Contact & Inquiries
For questions or support regarding this privacy policy:  
**Email:** support@harma.ai  
**Repository:** https://github.com/personal/harma-ai

