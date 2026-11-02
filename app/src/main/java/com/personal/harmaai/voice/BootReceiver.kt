package com.personal.harmaai.voice

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.personal.harmaai.data.SettingsStore

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            val settings = SettingsStore(context)
            if (settings.alwaysListenEnabled) {
                Log.i("HarmaWake", "Boot completed. Starting HarmaVoiceService because Always Listen is enabled.")
                HarmaVoiceService.start(context)
            } else {
                Log.i("HarmaWake", "Boot completed. Always Listen is disabled, not starting service.")
            }
        }
    }
}

