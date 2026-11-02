@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo           Harma AI - Reliable Installer
echo ===================================================
echo.

set ADB_EXE=adb
where adb >nul 2>&1
if %ERRORLEVEL% neq 0 (
    if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" (
        set ADB_EXE="%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
    ) else if exist "%ANDROID_HOME%\platform-tools\adb.exe" (
        set ADB_EXE="%ANDROID_HOME%\platform-tools\adb.exe"
    ) else (
        echo [ERROR] adb was not found in PATH or Android SDK platform-tools.
        echo Please ensure Android SDK Platform-Tools is installed and USB debugging is enabled on your phone.
        exit /b 1
    )
)

echo [INFO] Using ADB: %ADB_EXE%

set APK_PATH=app\build\outputs\harma\Harma-AI-release.apk
if not exist "%APK_PATH%" (
    if exist "app\build\outputs\apk\release\app-release.apk" (
        set APK_PATH=app\build\outputs\apk\release\app-release.apk
    ) else (
        echo [INFO] Release APK not found. Building signed release APK now...
        call gradlew.bat assembleRelease
        if %ERRORLEVEL% neq 0 (
            echo [ERROR] Gradle build failed. Check the errors above.
            exit /b 1
        )
    )
)

if not exist "%APK_PATH%" (
    echo [ERROR] Release APK not found at %APK_PATH%.
    exit /b 1
)

echo [INFO] Target APK: %APK_PATH%
echo [INFO] Checking connected devices...
%ADB_EXE% devices

echo.
echo [INFO] Installing Harma AI signed release APK...
%ADB_EXE% install -r -d "%APK_PATH%"

if %ERRORLEVEL% equ 0 (
    echo.
    echo ===================================================
    echo [SUCCESS] Harma AI installed successfully!
    echo.
    echo Next steps on your phone:
    echo 1. Open Harma AI.
    echo 2. For Android 13+: In the setup screen, tap 'Open App Info',
    echo    tap the top-right three dots (⋮), select 'Allow restricted settings'.
    echo 3. Tap 'Open Accessibility Settings' and toggle Harma AI ON.
    echo ===================================================
) else (
    echo.
    echo ===================================================
    echo [NOTE] If Play Protect blocked the install:
    echo 1. Look at your phone screen.
    echo 2. Tap 'More details' or 'Details'.
    echo 3. Tap 'Install anyway'.
    echo Or run: %ADB_EXE% install -r -d -g "%APK_PATH%"
    echo ===================================================
)

exit /b %ERRORLEVEL%

