#!/usr/bin/env bash
set -e

echo "==================================================="
echo "          Harma AI - Reliable Installer"
echo "==================================================="
echo ""

ADB_BIN="adb"
if ! command -v adb &> /dev/null; then
    if [ -f "$HOME/Library/Android/sdk/platform-tools/adb" ]; then
        ADB_BIN="$HOME/Library/Android/sdk/platform-tools/adb"
    elif [ -f "$HOME/Android/Sdk/platform-tools/adb" ]; then
        ADB_BIN="$HOME/Android/Sdk/platform-tools/adb"
    else
        echo "[ERROR] adb not found. Ensure Android platform-tools is installed."
        exit 1
    fi
fi

echo "[INFO] Using ADB: $ADB_BIN"

APK_PATH="app/build/outputs/harma/Harma-AI-release.apk"
if [ ! -f "$APK_PATH" ]; then
    if [ -f "app/build/outputs/apk/release/app-release.apk" ]; then
        APK_PATH="app/build/outputs/apk/release/app-release.apk"
    else
        echo "[INFO] Building signed release APK..."
        ./gradlew assembleRelease
    fi
fi

if [ ! -f "$APK_PATH" ]; then
    echo "[ERROR] Release APK not found at $APK_PATH"
    exit 1
fi

echo "[INFO] Target APK: $APK_PATH"
echo "[INFO] Connected devices:"
"$ADB_BIN" devices

echo ""
echo "[INFO] Installing release APK..."
"$ADB_BIN" install -r -d "$APK_PATH"

echo ""
echo "==================================================="
echo "[SUCCESS] Harma AI installed successfully!"
echo "Open Harma AI and enable Accessibility service to begin."
echo "==================================================="

