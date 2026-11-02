package com.personal.harmaai

import android.Manifest
import android.app.Application
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import com.personal.harmaai.agent.OfflineTaskQueueManager
import com.personal.harmaai.data.HarmaDatabase
import com.personal.harmaai.data.SettingsStore
import com.personal.harmaai.tools.AppListCache
import com.personal.harmaai.voice.HarmaVoiceService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class HarmaAiApplication : Application() {
    val settings: SettingsStore by lazy { SettingsStore(this) }
    val database: HarmaDatabase by lazy { HarmaDatabase.getInstance(this) }
    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        settings
        database
        AppListCache.initialize(this, appScope)
        OfflineTaskQueueManager.initialize(this, database)
        if (settings.alwaysListenEnabled &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        ) {
            HarmaVoiceService.start(this)
        }
    }
}
