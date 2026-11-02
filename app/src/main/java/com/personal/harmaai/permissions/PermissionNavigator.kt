package com.personal.harmaai.permissions

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.content.ContextCompat
import com.personal.harmaai.accessibility.AgentAccessibilityService

data class PermissionSnapshot(
    val microphone: Boolean,
    val notifications: Boolean,
    val accessibility: Boolean,
    val accessibilitySetting: Boolean,
    val accessibilityLive: Boolean,
    val batteryExempt: Boolean,
    val dndAccess: Boolean,
    val phoneCall: Boolean = false,
)

object PermissionNavigator {
    fun snapshot(context: Context): PermissionSnapshot {
        val settingEnabled = isAccessibilitySettingEnabled(context)
        val serviceLive = AgentAccessibilityService.isConnected()
        return PermissionSnapshot(
            microphone = granted(context, Manifest.permission.RECORD_AUDIO),
            notifications = Build.VERSION.SDK_INT < 33 || granted(context, Manifest.permission.POST_NOTIFICATIONS),
            accessibility = settingEnabled && serviceLive,
            accessibilitySetting = settingEnabled,
            accessibilityLive = serviceLive,
            batteryExempt = (context.getSystemService(Context.POWER_SERVICE) as PowerManager)
                .isIgnoringBatteryOptimizations(context.packageName),
            dndAccess = (context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
                .isNotificationPolicyAccessGranted,
            phoneCall = granted(context, Manifest.permission.CALL_PHONE),
        )
    }

    fun openAccessibility(context: Context) = launch(context, Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))

    @SuppressLint("BatteryLife")
    fun requestBatteryExemption(context: Context) = launch(
        context,
        Intent(
            Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
            Uri.parse("package:${context.packageName}"),
        ),
    )

    fun openDndAccess(context: Context) = launch(
        context,
        Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS),
    )

    fun openAppDetails(context: Context) = launch(
        context,
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")),
    )

    fun openBackgroundSettings(context: Context) = DeviceBackgroundPolicy.openBackgroundSettings(context)

    private fun granted(context: Context, permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    fun isAccessibilitySettingEnabled(context: Context): Boolean {
        val cn = ComponentName(context, AgentAccessibilityService::class.java)
        val full = cn.flattenToString()
        val short = cn.flattenToShortString()
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
        ).orEmpty()
        return enabled.split(":").any {
            it.equals(full, ignoreCase = true) || it.equals(short, ignoreCase = true)
        }
    }

    fun isAccessibilityTrulyConnected(context: Context): Boolean =
        isAccessibilitySettingEnabled(context) && AgentAccessibilityService.isConnected()

    private fun launch(context: Context, intent: Intent) {
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (intent.resolveActivity(context.packageManager) != null) {
            context.startActivity(intent)
        } else {
            openAppDetails(context)
        }
    }
}
