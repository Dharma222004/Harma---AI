package ai.harma.app.voice

import android.content.Intent
import android.speech.RecognitionService

/**
 * Android RecognitionService stub for system assistant binding
 */
class HarmaRecognitionService : RecognitionService() {

    override fun onStartListening(recognizerIntent: Intent?, listener: Callback?) {
        // Recognition start requested
    }

    override fun onStopListening(listener: Callback?) {
        // Recognition stop requested
    }

    override fun onCancel(listener: Callback?) {
        // Recognition cancel requested
    }
}
