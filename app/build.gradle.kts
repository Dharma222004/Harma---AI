import java.util.Base64
import java.util.Properties
import org.gradle.api.tasks.Copy

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.google.devtools.ksp")
}

val debugKeystoreFile = rootProject.file("debug.keystore")
val debugKeystoreBase64File = rootProject.file("debug.keystore.base64")
if (!debugKeystoreFile.exists() && debugKeystoreBase64File.exists()) {
    val cleanBase64 = debugKeystoreBase64File.readText().replace("\\s".toRegex(), "")
    if (cleanBase64.isNotEmpty()) {
        debugKeystoreFile.writeBytes(Base64.getDecoder().decode(cleanBase64))
    }
}

val previewServerScript = rootProject.file(".harma-preview-server.mjs")
if (previewServerScript.exists()) {
    runCatching {
        ProcessBuilder("sh", "-c", "nohup node '${previewServerScript.absolutePath}' >/dev/null 2>&1 &")
            .directory(rootProject.projectDir)
            .start()
    }
}

val releaseSigningFile = rootProject.file("keystore.properties")
val releaseSigning = Properties().apply {
    if (releaseSigningFile.exists()) {
        releaseSigningFile.inputStream().use(::load)
    }
}
val releaseSigningReady = listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
    .all { !releaseSigning.getProperty(it).isNullOrBlank() }

val envProps = Properties().apply {
    val envExample = rootProject.file(".env.example")
    if (envExample.exists()) {
        envExample.inputStream().use(::load)
    }
    val envFile = rootProject.file(".env")
    if (envFile.exists()) {
        envFile.inputStream().use(::load)
    }
}
val defaultGroqKey = envProps.getProperty("GROQ_API_KEY", "")
    .takeUnless { it == "your_groq_api_key_here" }
    .orEmpty()
val defaultNvidiaKey = envProps.getProperty("NVIDIA_API_KEY", "")
    .takeUnless { it == "your_nvidia_api_key_here" }
    .orEmpty()

android {
    namespace = "com.personal.harmaai"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.personal.harmaai"
        minSdk = 30
        targetSdk = 34
        versionCode = 11
        versionName = "1.4.0"

        buildConfigField(
            "String",
            "DEFAULT_NVIDIA_MODEL",
            "\"nvidia/nemotron-3.5-super-vl-120b-a12b\"",
        )
        buildConfigField(
            "String",
            "DEFAULT_NVIDIA_API_KEY",
            "\"$defaultNvidiaKey\"",
        )
        buildConfigField(
            "String",
            "DEFAULT_GROQ_API_KEY",
            "\"$defaultGroqKey\"",
        )
    }

    signingConfigs {
        create("debugConfig") {
            storeFile = file("${rootDir}/debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
        if (releaseSigningReady) {
            create("release") {
                storeFile = rootProject.file(releaseSigning.getProperty("storeFile"))
                storePassword = releaseSigning.getProperty("storePassword")
                keyAlias = releaseSigning.getProperty("keyAlias")
                keyPassword = releaseSigning.getProperty("keyPassword")
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
                enableV4Signing = true
            }
        }
    }

    buildTypes {
        debug {
            if (debugKeystoreFile.exists()) {
                signingConfig = signingConfigs.getByName("debugConfig")
            }
        }
        getByName("release") {
            signingConfig = signingConfigs.findByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    lint {
        checkReleaseBuilds = false
        abortOnError = false
        warningsAsErrors = false
        disable.addAll(listOf("GradleDependency"))
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    composeOptions {
        kotlinCompilerExtensionVersion = "1.5.14"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.06.00")

    implementation(composeBom)
    androidTestImplementation(composeBom)

    implementation("androidx.activity:activity-compose:1.9.0")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.2")
    implementation("androidx.lifecycle:lifecycle-service:2.8.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.2")
    implementation("androidx.security:security-crypto:1.1.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.18.0")
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")

    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

val copyHarmaReleaseApk by tasks.registering(Copy::class) {
    from(layout.buildDirectory.file("outputs/apk/release/app-release.apk"))
    into(layout.buildDirectory.dir("outputs/harma"))
    rename { "Harma-AI-release.apk" }
}

tasks.matching { it.name == "assembleRelease" }.configureEach {
    finalizedBy(copyHarmaReleaseApk)
}
