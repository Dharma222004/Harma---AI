@echo off
title Install Harma AI to Phone
echo ===================================================
echo   Installing Harma AI directly to your Android device
echo ===================================================
echo.
echo Checking connected devices...
"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" devices
echo.
echo Pushing and installing Harma-AI-release.apk...
"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" install -r "%~dp0app\build\outputs\harma\Harma-AI-release.apk"
echo.
if %ERRORLEVEL% EQU 0 (
    echo ===================================================
    echo   SUCCESS: Harma AI is now installed on your phone!
    echo ===================================================
) else (
    echo ===================================================
    echo   Installation via USB encountered an error.
    echo   Make sure:
    echo   1. Phone is connected via USB cable.
    echo   2. "USB Debugging" is enabled in Developer Options.
    echo   3. Tap "Allow" on the USB prompt on your phone screen.
    echo ===================================================
)
echo.
pause

