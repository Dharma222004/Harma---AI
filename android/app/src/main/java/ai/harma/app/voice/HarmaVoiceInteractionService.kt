package ai.harma.app.voice

import android.service.voice.VoiceInteractionService

/**
 * Android System VoiceInteractionService entry point
 * Keeps the always-running service lightweight and delegates heavy interaction
 * to the HarmaVoiceSessionService / HarmaRuntime.
 */
class HarmaVoiceInteractionService : VoiceInteractionService() {

    override fun onReady() {
        super.onReady()
    }

    override fun onShutdown() {
        super.onShutdown()
    }
}
