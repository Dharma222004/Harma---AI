package com.personal.harmaai.permissions

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings

data class BrandBackgroundGuide(
    val brandName: String,
    val title: String,
    val steps: List<String>,
    val settingsButtonLabel: String,
    val intentCandidates: List<Intent>,
)

object DeviceBackgroundPolicy {
    fun getGuide(context: Context): BrandBackgroundGuide {
        val manufacturer = Build.MANUFACTURER.orEmpty().lowercase()
        val brand = Build.BRAND.orEmpty().lowercase()
        val pkgUri = Uri.parse("package:${context.packageName}")

        return when {
            // Xiaomi / Redmi / POCO (HyperOS / MIUI)
            listOf("xiaomi", "redmi", "poco").any { manufacturer.contains(it) || brand.contains(it) } -> {
                BrandBackgroundGuide(
                    brandName = "Xiaomi / HyperOS",
                    title = "Keep Harma AI running",
                    steps = listOf(
                        "Enable 'Autostart' for Harma AI.",
                        "Set Battery saver to 'No restrictions'.",
                        "Lock Harma AI in the Recents tray (long press app card in Recents).",
                    ),
                    settingsButtonLabel = "Open Autostart Settings",
                    intentCandidates = listOf(
                        Intent().setComponent(ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity")),
                        Intent().setComponent(ComponentName("com.miui.powerkeeper", "com.miui.powerkeeper.ui.HiddenAppsConfigActivity")),
                        Intent("miui.intent.action.OP_AUTO_START").addCategory(Intent.CATEGORY_DEFAULT),
                    ),
                )
            }

            // Oppo / Realme / OnePlus (ColorOS / OxygenOS / Realme UI)
            listOf("oppo", "realme", "oneplus").any { manufacturer.contains(it) || brand.contains(it) } -> {
                BrandBackgroundGuide(
                    brandName = "ColorOS / OxygenOS",
                    title = "Keep Harma AI running",
                    steps = listOf(
                        "Enable 'Auto launch' and 'Allow background activity'.",
                        "Set Battery usage to 'Don't optimize' or 'Unrestricted'.",
                        "In the Recents screen, tap the three dots or lock icon to lock Harma AI.",
                    ),
                    settingsButtonLabel = "Open Startup Settings",
                    intentCandidates = listOf(
                        Intent().setComponent(ComponentName("com.oplus.safecenter", "com.oplus.safecenter.startupapp.StartupAppListActivity")),
                        Intent().setComponent(ComponentName("com.coloros.safecenter", "com.coloros.safecenter.startupapp.StartupAppListActivity")),
                        Intent().setComponent(ComponentName("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity")),
                        Intent().setComponent(ComponentName("com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity")),
                    ),
                )
            }

            // Vivo / iQOO (Funtouch OS / OriginOS)
            listOf("vivo", "iqoo").any { manufacturer.contains(it) || brand.contains(it) } -> {
                BrandBackgroundGuide(
                    brandName = "Vivo / iQOO",
                    title = "Keep Harma AI running",
                    steps = listOf(
                        "Turn on 'Autostart' for Harma AI.",
                        "Set Background power consumption to 'High background power usage' or 'Don't restrict'.",
                        "Lock Harma AI in the Recents screen.",
                    ),
                    settingsButtonLabel = "Open Autostart Manager",
                    intentCandidates = listOf(
                        Intent().setComponent(ComponentName("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity")),
                        Intent().setComponent(ComponentName("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity")),
                        Intent().setComponent(ComponentName("com.iqoo.secure", "com.iqoo.secure.MainActivity")),
                    ),
                )
            }

            // Samsung (One UI)
            listOf("samsung").any { manufacturer.contains(it) || brand.contains(it) } -> {
                BrandBackgroundGuide(
                    brandName = "Samsung One UI",
                    title = "Keep Harma AI running",
                    steps = listOf(
                        "Go to Battery → Background usage limits and ensure Harma AI is in 'Never sleeping apps'.",
                        "In App info → Battery, choose 'Unrestricted'.",
                        "Lock Harma AI in the Recent apps view.",
                    ),
                    settingsButtonLabel = "Open Battery Settings",
                    intentCandidates = listOf(
                        Intent().setComponent(ComponentName("com.samsung.android.lool", "com.samsung.android.sm.battery.ui.BatteryActivity")),
                        Intent().setComponent(ComponentName("com.samsung.android.sm", "com.samsung.android.sm.ui.battery.BatteryActivity")),
                    ),
                )
            }

            // Huawei / Honor (EMUI / MagicOS)
            listOf("huawei", "honor").any { manufacturer.contains(it) || brand.contains(it) } -> {
                BrandBackgroundGuide(
                    brandName = "Huawei / Honor",
                    title = "Keep Harma AI running",
                    steps = listOf(
                        "Go to App Launch / Startup and set Harma AI to 'Manage manually'.",
                        "Enable Auto-launch, Secondary launch, and Run in background.",
                        "Disable battery power-saving restrictions.",
                    ),
                    settingsButtonLabel = "Open App Launch",
                    intentCandidates = listOf(
                        Intent().setComponent(ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity")),
                        Intent().setComponent(ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.optimize.bootstart.BootStartActivity")),
                    ),
                )
            }

            // Motorola / Nothing / Pixel / Stock Android
            listOf("google", "motorola", "moto", "nothing", "hmd", "nokia").any { manufacturer.contains(it) || brand.contains(it) } -> {
                BrandBackgroundGuide(
                    brandName = "Stock Android / Pixel",
                    title = "Keep Harma AI running",
                    steps = listOf(
                        "In App info → Battery, select 'Unrestricted'.",
                        "Allow background data and exempt from battery saver.",
                    ),
                    settingsButtonLabel = "Open App Info",
                    intentCandidates = listOf(
                        Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
                        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkgUri),
                    ),
                )
            }

            // Default fallback
            else -> {
                val detected = Build.MANUFACTURER.takeIf { it.isNotBlank() }?.replaceFirstChar(Char::uppercase) ?: "Android"
                BrandBackgroundGuide(
                    brandName = detected,
                    title = "Keep Harma AI running",
                    steps = listOf(
                        "Allow background activity and autostart for Harma AI.",
                        "Set battery usage to 'Unrestricted' (disable battery optimization).",
                        "Lock Harma AI in your phone's Recent apps tray.",
                    ),
                    settingsButtonLabel = "Open App Settings",
                    intentCandidates = listOf(
                        Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
                        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, pkgUri),
                    ),
                )
            }
        }
    }

    fun openBackgroundSettings(context: Context) {
        val guide = getGuide(context)
        val pm = context.packageManager
        for (intent in guide.intentCandidates) {
            try {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                if (intent.resolveActivity(pm) != null) {
                    context.startActivity(intent)
                    return
                }
            } catch (_: Exception) {}
        }
        // Fallback 1: Battery optimization settings
        try {
            val batteryIntent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (batteryIntent.resolveActivity(pm) != null) {
                context.startActivity(batteryIntent)
                return
            }
        } catch (_: Exception) {}
        // Fallback 2: App details
        try {
            val detailsIntent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            context.startActivity(detailsIntent)
        } catch (_: Exception) {}
    }
}

