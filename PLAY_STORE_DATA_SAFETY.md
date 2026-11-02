# Google Play Console - Data Safety Questionnaire Answers

Use these exact answers when filling out the Google Play Console **Data Safety** section for **Harma AI** (`com.personal.harmaai`):

---

### Data Collection and Security
1. **Does your app collect or share any of the required user data types?**
   - **Answer:** Yes (Voice/Audio recordings only for speech-to-text functionality).
2. **Is all of the user data collected by your app encrypted in transit?**
   - **Answer:** Yes (all network communication uses HTTPS/TLS 1.3).
3. **Do you provide a way for users to request that their data be deleted?**
   - **Answer:** Yes (users can clear all task history and stored memories in app Settings, or by clearing app data).

---

### Data Types Breakdown

#### Audio Files (Voice or sound recordings)
- **Collected?** Yes.
- **Shared with third parties?** No.
- **Processed ephemerally?** Yes. Audio is streamed to Groq Whisper for speech recognition and discarded immediately.
- **Required or Optional?** Optional (only used when the user uses voice input).
- **Purpose:** App functionality (Voice control).

#### Personal Info
- **Collected or Shared?** No.

#### Financial Info
- **Collected or Shared?** No. (Harma AI explicitly blocks access to payment screens and never handles financial credentials).

#### Health and Fitness
- **Collected or Shared?** No.

#### Messages (SMS, emails, chat messages)
- **Collected or Shared?** No.

#### Photos and Videos
- **Collected or Shared?** No.

#### Location
- **Collected or Shared?** No.

#### App Activity / Performance / Device IDs
- **Collected or Shared?** No.

---

### Summary for Play Console
- **No data shared with third parties for marketing/advertising.**
- **No user tracking across other apps or websites.**
- **Data collected is strictly functional and encrypted in transit.**

