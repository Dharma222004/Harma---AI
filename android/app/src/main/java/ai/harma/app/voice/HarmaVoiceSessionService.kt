package ai.harma.app.voice

import android.content.Context
import android.os.Bundle
import android.service.voice.VoiceInteractionSession
import android.service.voice.VoiceInteractionSessionService

/**
 * Handles active system assistant interaction sessions
 */
class HarmaVoiceSessionService : VoiceInteractionSessionService() {

    override fun onNewSession(args: Bundle?): VoiceInteractionSession {
        return HarmaAssistantSession(this)
    }

    private class HarmaAssistantSession(context: Context) : VoiceInteractionSession(context) {
        override fun onHandleAssist(data: Bundle?, structure: android.app.assist.AssistStructure?, content: android.app.assist.AssistContent?) {
            super.onHandleAssist(data, structure, content)
            // Session invocation received
        }
    }
}
