package com.personal.harmaai.network

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Monitors validated internet connectivity (`NET_CAPABILITY_INTERNET` + `NET_CAPABILITY_VALIDATED`)
 * and notifies subscribers (such as `OfflineTaskQueueManager`) when the device transitions
 * from offline to online.
 */
object NetworkMonitor {
    private val _isOnline = MutableStateFlow(true)
    val isOnline: StateFlow<Boolean> = _isOnline.asStateFlow()

    @Volatile
    private var registered = false

    private val reconnectListeners = mutableListOf<() -> Unit>()

    fun initialize(context: Context) {
        val appContext = context.applicationContext
        val cm = appContext.getSystemService(ConnectivityManager::class.java) ?: return
        _isOnline.value = checkValidatedInternet(cm)

        if (registered) return
        synchronized(this) {
            if (registered) return
            val request = NetworkRequest.Builder()
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .build()
            runCatching {
                cm.registerNetworkCallback(
                    request,
                    object : ConnectivityManager.NetworkCallback() {
                        override fun onAvailable(network: Network) {
                            updateState(cm)
                        }

                        override fun onCapabilitiesChanged(
                            network: Network,
                            networkCapabilities: NetworkCapabilities,
                        ) {
                            updateState(cm)
                        }

                        override fun onLost(network: Network) {
                            updateState(cm)
                        }
                    },
                )
                registered = true
            }
        }
    }

    fun isCurrentlyOnline(context: Context): Boolean {
        val cm = context.applicationContext.getSystemService(ConnectivityManager::class.java)
            ?: return true
        val online = checkValidatedInternet(cm)
        _isOnline.value = online
        return online
    }

    fun addOnReconnectListener(listener: () -> Unit) {
        synchronized(reconnectListeners) {
            reconnectListeners += listener
        }
    }

    private fun updateState(cm: ConnectivityManager) {
        val wasOffline = !_isOnline.value
        val nowOnline = checkValidatedInternet(cm)
        _isOnline.value = nowOnline
        if (wasOffline && nowOnline) {
            val listeners = synchronized(reconnectListeners) { reconnectListeners.toList() }
            listeners.forEach { runCatching { it.invoke() } }
        }
    }

    private fun checkValidatedInternet(cm: ConnectivityManager): Boolean {
        val activeNetwork = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(activeNetwork) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    }
}
