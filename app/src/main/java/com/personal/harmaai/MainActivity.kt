package com.personal.harmaai

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.content.ContextCompat
import com.personal.harmaai.ui.HarmaAiApp
import com.personal.harmaai.ui.theme.HarmaTheme
import com.personal.harmaai.voice.HarmaVoiceService

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            HarmaTheme {
                HarmaAiApp()
            }
        }
    }

    override fun onResume() {
        super.onResume()
        val app = application as HarmaAiApplication
        if (app.settings.alwaysListenEnabled &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        ) {
            HarmaVoiceService.start(this)
        }
    }
}
