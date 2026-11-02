package com.personal.harmaai.voice

import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService
import androidx.annotation.RequiresApi

@RequiresApi(Build.VERSION_CODES.N)
class HarmaVoiceTileService : TileService() {

    override fun onStartListening() {
        super.onStartListening()
        qsTile?.apply {
            state = Tile.STATE_INACTIVE
            label = "Harma Voice"
            updateTile()
        }
    }

    override fun onClick() {
        super.onClick()
        qsTile?.apply {
            state = Tile.STATE_ACTIVE
            updateTile()
        }

        // Trigger immediate speech capture flow without wake word
        HarmaVoiceService.triggerTalkNow(this)

        qsTile?.apply {
            state = Tile.STATE_INACTIVE
            updateTile()
        }
    }
}

