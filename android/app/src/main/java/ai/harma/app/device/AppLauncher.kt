package ai.harma.app.device

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager

/**
 * Native App discovery and launcher with verified package resolution
 */
class AppLauncher(private val context: Context) {

    fun launchPackage(packageName: String): Boolean {
        val launchIntent = context.packageManager.getLaunchIntentForPackage(packageName) ?: return false
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        context.startActivity(launchIntent)
        return true
    }

    fun findPackageByName(appName: String): String? {
        val pm = context.packageManager
        val packages = pm.getInstalledApplications(PackageManager.GET_META_DATA)

        // Exact or case-insensitive match on label
        for (app in packages) {
            val label = pm.getApplicationLabel(app).toString()
            if (label.equals(appName, ignoreCase = true)) {
                return app.packageName
            }
        }

        // Substring match
        for (app in packages) {
            val label = pm.getApplicationLabel(app).toString()
            if (label.contains(appName, ignoreCase = true)) {
                return app.packageName
            }
        }

        // Known standard mappings
        return when (appName.lowercase()) {
            "whatsapp" -> "com.whatsapp"
            "chrome" -> "com.android.chrome"
            "youtube" -> "com.google.android.youtube"
            "maps" -> "com.google.android.apps.maps"
            "settings" -> "com.android.settings"
            "camera" -> "com.google.android.GoogleCamera"
            else -> null
        }
    }

    fun launchAppByName(appName: String): Boolean {
        val pkg = findPackageByName(appName) ?: return false
        return launchPackage(pkg)
    }
}
