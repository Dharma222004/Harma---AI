package ai.harma.app.device

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.view.accessibility.AccessibilityManager

/**
 * Manages checking and requesting Harma's Accessibility Service state.
 */
object AccessibilityHelper {

    fun isAccessibilityEnabled(context: Context): Boolean {
        val am = context.getSystemService(Context.ACCESSIBILITY_SERVICE) as? AccessibilityManager ?: return false
        val enabledServices = am.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK)
        val expectedServiceName = "${context.packageName}/${HarmaAccessibilityService::class.java.canonicalName}"
        val simpleName = "${context.packageName}/.device.HarmaAccessibilityService"

        return enabledServices.any {
            it.id.equals(expectedServiceName, ignoreCase = true) ||
            it.id.equals(simpleName, ignoreCase = true) ||
            it.id.contains("HarmaAccessibilityService")
        }
    }

    fun openAccessibilitySettings(context: Context) {
        val intent = Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK
        }
        context.startActivity(intent)
    }
}
