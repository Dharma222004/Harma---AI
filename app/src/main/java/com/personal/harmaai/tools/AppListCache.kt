package com.personal.harmaai.tools

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.concurrent.ConcurrentHashMap

/**
 * Thread-safe cache of installed launcher applications with fast fuzzy matching.
 * Refreshes automatically on package install/uninstall broadcasts.
 */
object AppListCache {
    private const val TAG = "AppListCache"

    // Normalized label -> package name
    private val labelToPackage = ConcurrentHashMap<String, String>()
    // Package name -> display label
    private val packageToLabel = ConcurrentHashMap<String, String>()

    @Volatile
    private var isInitialized = false

    private val commonAliases = mapOf(
        "youtube" to listOf("yt", "you tube"),
        "whatsapp" to listOf("wa", "whats app"),
        "chrome" to listOf("google chrome", "browser", "internet"),
        "settings" to listOf("phone settings", "system settings"),
        "paytm" to listOf("pay tm"),
        "gpay" to listOf("google pay", "tez"),
        "phonepe" to listOf("phone pe"),
        "maps" to listOf("google maps"),
        "gmail" to listOf("email", "mail", "google mail"),
        "spotify" to listOf("music"),
        "camera" to listOf("cam"),
        "gallery" to listOf("photos", "google photos"),
        "clock" to listOf("alarm", "timer"),
        "calculator" to listOf("calc"),
        "contacts" to listOf("phonebook", "people"),
        "messages" to listOf("sms", "text messages", "messaging"),
    )

    fun initialize(context: Context, scope: CoroutineScope) {
        if (isInitialized) return
        scope.launch(Dispatchers.IO) {
            refresh(context)
            registerPackageReceiver(context.applicationContext)
            isInitialized = true
        }
    }

    fun refresh(context: Context) {
        try {
            val pm = context.packageManager
            val launcherIntent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                PackageManager.ResolveInfoFlags.of(0)
            } else {
                @Suppress("DEPRECATION")
                0
            }

            val activities = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                pm.queryIntentActivities(launcherIntent, flags as PackageManager.ResolveInfoFlags)
            } else {
                @Suppress("DEPRECATION")
                pm.queryIntentActivities(launcherIntent, 0)
            }

            val newLabelToPkg = mutableMapOf<String, String>()
            val newPkgToLabel = mutableMapOf<String, String>()

            for (info in activities) {
                val pkg = info.activityInfo.packageName ?: continue
                val label = runCatching { info.loadLabel(pm).toString().trim() }.getOrNull().orEmpty()
                if (label.isNotBlank()) {
                    val normLabel = normalize(label)
                    newLabelToPkg[normLabel] = pkg
                    newPkgToLabel[pkg] = label
                }
            }

            labelToPackage.clear()
            labelToPackage.putAll(newLabelToPkg)
            packageToLabel.clear()
            packageToLabel.putAll(newPkgToLabel)

            Log.i(TAG, "Cached ${labelToPackage.size} installed launcher applications.")
        } catch (e: Exception) {
            Log.e(TAG, "Failed to refresh installed apps cache: ${e.message}")
        }
    }

    /**
     * Resolves an app query string to an installed package name.
     * Uses exact match, alias match, prefix/contains match, and token matching.
     */
    fun resolvePackage(query: String, context: Context? = null): String? {
        val q = normalize(query)
        if (q.isBlank()) return null

        // 1. Direct package match
        if (packageToLabel.containsKey(q)) return q

        // 2. Exact label match
        labelToPackage[q]?.let { return it }

        // 3. Known alias match
        for ((targetName, aliases) in commonAliases) {
            if (q == targetName || aliases.contains(q)) {
                // Find package matching targetName
                labelToPackage[targetName]?.let { return it }
                labelToPackage.entries.firstOrNull { it.key.contains(targetName) }?.value?.let { return it }
            }
        }

        // 4. Starts with / Contains match in cached labels
        labelToPackage.entries.firstOrNull { it.key.startsWith(q) }?.value?.let { return it }
        labelToPackage.entries.firstOrNull { it.key.contains(q) }?.value?.let { return it }

        // 5. Query word in label
        val words = q.split(" ").filter { it.length > 2 }
        if (words.isNotEmpty()) {
            for (word in words) {
                labelToPackage.entries.firstOrNull { it.key.contains(word) }?.value?.let { return it }
            }
        }

        // 6. Fallback if cache was empty or app just installed
        if (context != null && labelToPackage.isEmpty()) {
            refresh(context)
            return labelToPackage[q]
                ?: labelToPackage.entries.firstOrNull { it.key.contains(q) }?.value
        }

        return null
    }

    fun getAppLabel(packageName: String): String =
        packageToLabel[packageName] ?: packageName

    private fun normalize(text: String): String =
        text.lowercase().trim().replace(Regex("[^a-z0-9 ]"), "")

    private fun registerPackageReceiver(context: Context) {
        val filter = IntentFilter().apply {
            addAction(Intent.ACTION_PACKAGE_ADDED)
            addAction(Intent.ACTION_PACKAGE_REMOVED)
            addAction(Intent.ACTION_PACKAGE_REPLACED)
            addDataScheme("package")
        }
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context?, intent: Intent?) {
                if (c != null) {
                    refresh(c)
                }
            }
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            context.registerReceiver(receiver, filter)
        }
    }
}
