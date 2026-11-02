# Harma AI ProGuard / R8 Rules

# Keep Android components declared in manifest
-keep public class com.personal.harmaai.HarmaAiApplication { *; }
-keep public class com.personal.harmaai.MainActivity { *; }
-keep public class com.personal.harmaai.service.HarmaAgentService { *; }
-keep public class com.personal.harmaai.accessibility.AgentAccessibilityService { *; }
-keep public class com.personal.harmaai.voice.HarmaVoiceService { *; }
-keep class com.personal.harmaai.voice.** { *; }

# Keep Room database and DAO classes
-keep class androidx.room.** { *; }
-dontwarn androidx.room.**
-keep class * extends androidx.room.RoomDatabase
-keep @androidx.room.Dao interface * { *; }
-keep @androidx.room.Entity class * { *; }
-keep class com.personal.harmaai.data.** { *; }

# Keep data models used in JSON serialization / reflection
-keepclassmembers class com.personal.harmaai.tools.** {
    <fields>;
    <init>(...);
}
-keepclassmembers class com.personal.harmaai.agent.** {
    <fields>;
    <init>(...);
}
-keepclassmembers class com.personal.harmaai.accessibility.** {
    <fields>;
    <init>(...);
}
-keepclassmembers class com.personal.harmaai.network.** {
    <fields>;
    <init>(...);
}

# AndroidX Security Crypto (EncryptedSharedPreferences & MasterKey)
-keep class androidx.security.crypto.** { *; }
-dontwarn androidx.security.crypto.**
-keep class com.google.crypto.tink.** { *; }
-dontwarn com.google.crypto.tink.**

# OkHttp & Okio
-keepattributes Signature
-keepattributes *Annotation*
-keep class okhttp3.** { *; }
-keep interface okhttp3.** { *; }
-dontwarn okhttp3.**
-dontwarn okio.**

# Kotlin Coroutines
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}
-keepclassmembernames class kotlinx.** {
    volatile <fields>;
}

# Keep Compose rules
-keep class androidx.compose.** { *; }
-dontwarn androidx.compose.**

