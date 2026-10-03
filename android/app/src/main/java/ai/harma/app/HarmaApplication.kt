package ai.harma.app

import android.app.Application
import ai.harma.app.data.local.SecurePreferences
import ai.harma.app.data.repository.HarmaRepository
import ai.harma.app.device.AppLauncher
import ai.harma.app.device.CapabilityDispatcher
import ai.harma.app.device.FlashlightController
import ai.harma.app.device.WhatsAppAutomation

class HarmaApplication : Application() {

    lateinit var securePreferences: SecurePreferences
        private set

    lateinit var repository: HarmaRepository
        private set

    lateinit var appLauncher: AppLauncher
        private set

    lateinit var flashlightController: FlashlightController
        private set

    lateinit var whatsAppAutomation: WhatsAppAutomation
        private set

    lateinit var capabilityDispatcher: CapabilityDispatcher
        private set

    companion object {
        lateinit var instance: HarmaApplication
            private set
    }

    override fun onCreate() {
        super.onCreate()
        instance = this

        securePreferences = SecurePreferences(this)
        repository = HarmaRepository(this, securePreferences)
        appLauncher = AppLauncher(this)
        flashlightController = FlashlightController(this)
        whatsAppAutomation = WhatsAppAutomation(this, appLauncher)
        capabilityDispatcher = CapabilityDispatcher(
            context = this,
            securePrefs = securePreferences,
            appLauncher = appLauncher,
            flashlightController = flashlightController,
            whatsAppAutomation = whatsAppAutomation
        )
    }
}
