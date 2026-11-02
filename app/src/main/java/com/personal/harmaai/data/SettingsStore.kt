package com.personal.harmaai.data

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.personal.harmaai.BuildConfig

/**
 * Encrypted, process-safe settings used by the UI and the foreground agent service.
 * Secrets and user preferences are explicitly excluded from Android backup in the manifest.
 */
class SettingsStore(context: Context) {
    private val appContext = context.applicationContext
    private val masterKey = MasterKey.Builder(appContext)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val preferences = EncryptedSharedPreferences.create(
        appContext,
        FILE_NAME,
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    var apiKey: String
        get() = preferences.getString(KEY_API_KEY, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_API_KEY, value.trim()).apply()

    var groqApiKey: String
        get() = preferences.getString(KEY_GROQ_API_KEY, BuildConfig.DEFAULT_GROQ_API_KEY).orEmpty()
        set(value) = preferences.edit().putString(KEY_GROQ_API_KEY, value.trim()).apply()

    var groqWhisperModel: String
        get() = preferences.getString(KEY_GROQ_WHISPER_MODEL, DEFAULT_GROQ_WHISPER_MODEL)
            .orEmpty()
            .ifBlank { DEFAULT_GROQ_WHISPER_MODEL }
        set(value) = preferences.edit()
            .putString(KEY_GROQ_WHISPER_MODEL, value.trim().ifBlank { DEFAULT_GROQ_WHISPER_MODEL })
            .apply()

    var alwaysListenEnabled: Boolean
        get() = preferences.getBoolean(KEY_ALWAYS_LISTEN, false)
        set(value) = preferences.edit().putBoolean(KEY_ALWAYS_LISTEN, value).apply()

    var wakeWordThreshold: Float
        get() = preferences.getFloat(KEY_WAKE_WORD_THRESHOLD, DEFAULT_WAKE_WORD_THRESHOLD)
            .coerceIn(0.3f, 0.9f)
        set(value) = preferences.edit()
            .putFloat(KEY_WAKE_WORD_THRESHOLD, value.coerceIn(0.3f, 0.9f))
            .apply()

    var whisperLanguage: String
        get() = preferences.getString(KEY_WHISPER_LANGUAGE, DEFAULT_WHISPER_LANGUAGE)
            .orEmpty()
            .ifBlank { DEFAULT_WHISPER_LANGUAGE }
        set(value) = preferences.edit()
            .putString(KEY_WHISPER_LANGUAGE, value.trim())
            .apply()

    var fastModel: String
        get() = preferences.getString(KEY_FAST_MODEL, DEFAULT_FAST_MODEL)
            .orEmpty()
            .ifBlank { DEFAULT_FAST_MODEL }
        set(value) = preferences.edit()
            .putString(KEY_FAST_MODEL, value.trim().ifBlank { DEFAULT_FAST_MODEL })
            .apply()

    var smartModel: String
        get() = preferences.getString(KEY_SMART_MODEL, DEFAULT_SMART_MODEL)
            .orEmpty()
            .ifBlank { DEFAULT_SMART_MODEL }
        set(value) = preferences.edit()
            .putString(KEY_SMART_MODEL, value.trim().ifBlank { DEFAULT_SMART_MODEL })
            .apply()

    var modelMode: String
        get() = preferences.getString(KEY_MODEL_MODE, "fast").orEmpty().ifBlank { "fast" }
        set(value) = preferences.edit().putString(KEY_MODEL_MODE, value.trim()).apply()

    var primaryModel: String
        get() {
            val defaultChoice = if (modelMode == "smart") smartModel else fastModel
            return preferences.getString(KEY_PRIMARY_MODEL, defaultChoice)
                .orEmpty()
                .ifBlank { defaultChoice }
        }
        set(value) = preferences.edit()
            .putString(KEY_PRIMARY_MODEL, value.trim())
            .apply()

    var fallbackModels: List<String>
        get() = decodeList(
            preferences.getString(KEY_FALLBACK_MODELS, null)
                ?: DEFAULT_FALLBACK_MODELS.joinToString(LIST_SEPARATOR),
        )
        set(value) = preferences.edit()
            .putString(KEY_FALLBACK_MODELS, encodeList(value))
            .apply()

    var maxSteps: Int
        get() = preferences.getInt(KEY_MAX_STEPS, DEFAULT_MAX_STEPS).coerceIn(1, 50)
        set(value) = preferences.edit().putInt(KEY_MAX_STEPS, value.coerceIn(1, 50)).apply()

    var stepDelayMs: Long
        get() = preferences.getLong(KEY_STEP_DELAY_MS, DEFAULT_STEP_DELAY_MS)
            .coerceIn(50L, 5_000L)
        set(value) = preferences.edit()
            .putLong(KEY_STEP_DELAY_MS, value.coerceIn(50L, 5_000L))
            .apply()

    var confirmationsEnabled: Boolean
        get() = preferences.getBoolean(KEY_CONFIRMATIONS, true)
        set(value) = preferences.edit().putBoolean(KEY_CONFIRMATIONS, value).apply()

    var visionEnabled: Boolean
        get() = preferences.getBoolean(KEY_VISION, true)
        set(value) = preferences.edit().putBoolean(KEY_VISION, value).apply()

    var ttsEnabled: Boolean
        get() = preferences.getBoolean(KEY_TTS, true)
        set(value) = preferences.edit().putBoolean(KEY_TTS, value).apply()

    var speechRate: Float
        get() = preferences.getFloat(KEY_SPEECH_RATE, 1.0f).coerceIn(0.5f, 2.0f)
        set(value) = preferences.edit().putFloat(KEY_SPEECH_RATE, value.coerceIn(0.5f, 2.0f)).apply()

    var speechPitch: Float
        get() = preferences.getFloat(KEY_SPEECH_PITCH, 1.0f).coerceIn(0.5f, 2.0f)
        set(value) = preferences.edit().putFloat(KEY_SPEECH_PITCH, value.coerceIn(0.5f, 2.0f)).apply()

    var conversationMode: Boolean
        get() = preferences.getBoolean(KEY_CONVERSATION_MODE, false)
        set(value) = preferences.edit().putBoolean(KEY_CONVERSATION_MODE, value).apply()

    var autoSendWithoutConfirmation: Boolean
        get() = preferences.getBoolean(KEY_AUTO_SEND, false)
        set(value) = preferences.edit().putBoolean(KEY_AUTO_SEND, value).apply()

    var onboardingCompleted: Boolean
        get() = preferences.getBoolean(KEY_ONBOARDING_COMPLETE, false)
        set(value) = preferences.edit().putBoolean(KEY_ONBOARDING_COMPLETE, value).apply()

    var allowedApps: Set<String>
        get() = decodeList(preferences.getString(KEY_ALLOWED_APPS, "").orEmpty()).toSet()
        set(value) = preferences.edit().putString(KEY_ALLOWED_APPS, encodeList(value)).apply()

    var deniedApps: Set<String>
        get() = decodeList(preferences.getString(KEY_DENIED_APPS, "").orEmpty()).toSet()
        set(value) = preferences.edit().putString(KEY_DENIED_APPS, encodeList(value)).apply()

    /** Ordered, unique model candidates for the active NVIDIA provider. */
    fun modelChain(): List<String> = buildList {
        add(primaryModel)
        addAll(fallbackModels)
    }.map(String::trim).filter(String::isNotBlank).distinct()

    fun resetNonSecretSettings() {
        val retainedKey = apiKey
        val retainedGroqKey = groqApiKey
        preferences.edit().clear().apply()
        apiKey = retainedKey
        groqApiKey = retainedGroqKey
        primaryModel = BuildConfig.DEFAULT_NVIDIA_MODEL
        fallbackModels = DEFAULT_FALLBACK_MODELS
    }

    init {
        migrateLegacyProviderSettings()
        if (!preferences.contains(KEY_PRIMARY_MODEL)) {
            primaryModel = BuildConfig.DEFAULT_NVIDIA_MODEL
        }
        if (!preferences.contains(KEY_FALLBACK_MODELS)) {
            fallbackModels = DEFAULT_FALLBACK_MODELS
        }
    }

    /**
     * Older builds stored active-provider values under Gemini-era names. Only values that can be
     * identified as NVIDIA settings are copied; a Gemini key must never be sent to NVIDIA.
     */
    private fun migrateLegacyProviderSettings() {
        val editor = preferences.edit()
        var changed = false

        if (!preferences.contains(KEY_API_KEY)) {
            preferences.getString(LEGACY_KEY_API_KEY, "")
                .orEmpty()
                .trim()
                .takeIf { it.startsWith("nvapi-") }
                ?.let {
                    editor.putString(KEY_API_KEY, it)
                    changed = true
                }
        }
        if (!preferences.contains(KEY_PRIMARY_MODEL)) {
            preferences.getString(LEGACY_KEY_PRIMARY_MODEL, "")
                .orEmpty()
                .trim()
                .takeIf { it.startsWith("nvidia/") }
                ?.let {
                    editor.putString(KEY_PRIMARY_MODEL, it)
                    changed = true
                }
        }
        if (!preferences.contains(KEY_FALLBACK_MODELS)) {
            val legacyModels = decodeList(
                preferences.getString(LEGACY_KEY_FALLBACK_MODELS, "").orEmpty(),
            ).filter { it.startsWith("nvidia/") }
            if (legacyModels.isNotEmpty()) {
                editor.putString(KEY_FALLBACK_MODELS, encodeList(legacyModels))
                changed = true
            }
        }
        listOf(
            LEGACY_KEY_API_KEY,
            LEGACY_KEY_PRIMARY_MODEL,
            LEGACY_KEY_FALLBACK_MODELS,
        ).forEach { legacyKey ->
            if (preferences.contains(legacyKey)) {
                editor.remove(legacyKey)
                changed = true
            }
        }
        if (changed) editor.apply()
    }

    private fun encodeList(values: Iterable<String>): String = values
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .distinct()
        .joinToString(LIST_SEPARATOR)

    private fun decodeList(value: String): List<String> = value
        .split('\n', ',', ';')
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .distinct()

    companion object {
        const val DEFAULT_MAX_STEPS = 15
        const val DEFAULT_STEP_DELAY_MS = 150L
        const val DEFAULT_GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"
        const val DEFAULT_WAKE_WORD_THRESHOLD = 0.5f
        const val DEFAULT_WHISPER_LANGUAGE = "en"
        const val DEFAULT_FAST_MODEL = "meta/llama-3.3-70b-instruct"
        const val DEFAULT_SMART_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"

        val DEFAULT_FALLBACK_MODELS = emptyList<String>()

        private const val FILE_NAME = "harma_ai_secure_settings"
        private const val LIST_SEPARATOR = "\n"
        private const val KEY_API_KEY = "nvidia_api_key"
        private const val KEY_PRIMARY_MODEL = "nvidia_primary_model"
        private const val KEY_FAST_MODEL = "nvidia_fast_model"
        private const val KEY_SMART_MODEL = "nvidia_smart_model"
        private const val KEY_MODEL_MODE = "nvidia_model_mode"
        private const val KEY_FALLBACK_MODELS = "nvidia_fallback_models"
        private const val KEY_GROQ_API_KEY = "groq_api_key"
        private const val KEY_GROQ_WHISPER_MODEL = "groq_whisper_model"
        private const val KEY_ALWAYS_LISTEN = "always_listen_enabled"
        private const val KEY_WAKE_WORD_THRESHOLD = "wake_word_threshold"
        private const val KEY_WHISPER_LANGUAGE = "whisper_language"
        private const val LEGACY_KEY_API_KEY = "gemini_api_key"
        private const val LEGACY_KEY_PRIMARY_MODEL = "primary_model"
        private const val LEGACY_KEY_FALLBACK_MODELS = "fallback_models"
        private const val KEY_MAX_STEPS = "max_steps"
        private const val KEY_STEP_DELAY_MS = "step_delay_ms"
        private const val KEY_CONFIRMATIONS = "confirmations_enabled"
        private const val KEY_VISION = "vision_enabled"
        private const val KEY_TTS = "tts_enabled"
        private const val KEY_SPEECH_RATE = "speech_rate"
        private const val KEY_SPEECH_PITCH = "speech_pitch"
        private const val KEY_CONVERSATION_MODE = "conversation_mode"
        private const val KEY_AUTO_SEND = "auto_send_without_confirmation"
        private const val KEY_ONBOARDING_COMPLETE = "onboarding_complete"
        private const val KEY_ALLOWED_APPS = "allowed_apps"
        private const val KEY_DENIED_APPS = "denied_apps"
    }
}
