#!/bin/bash
# Pack RE-Amped2 for Android into an APK, without Gradle: javac, d8, aapt2,
# zipalign and apksigner from the Android SDK.
#
#   android/build_apk.sh BUILD_DIR SDL2_SOURCE SDL2_PREFIX [OUT.apk]
#
# BUILD_DIR    the NDK build of this project (holds libmain.so), e.g.
#                cmake -S . -B build-android -G Ninja -DCMAKE_BUILD_TYPE=Release \
#                  -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
#                  -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-29 \
#                  -DCMAKE_FIND_ROOT_PATH=$SDL2_PREFIX -DSDL2_DIR=$SDL2_PREFIX/lib/cmake/SDL2
# SDL2_SOURCE  the SDL2 source release (its android-project holds the Java)
# SDL2_PREFIX  SDL2 built for arm64-v8a with the same NDK and installed
#
# Needs ANDROID_HOME (or ~/android-sdk) with build-tools;34.0.0 and
# platforms;android-34, and a JDK. Signs with a debug key made on first use
# (~/.android/debug.keystore), which is fine for sideloading.
#
# The APK holds no game data and no generated code from anyone else's disc:
# libmain.so is built here from the player's own. After installing, copy the
# extracted game/ folder to Android/data/org.reamped2.app/files/game (e.g.
# `adb push game /sdcard/Android/data/org.reamped2.app/files/`).
set -euo pipefail
BUILD=$(realpath "$1"); SDLSRC=$(realpath "$2"); SDLPRE=$(realpath "$3")
OUT=$(realpath -m "${4:-$BUILD/RE-Amped2.apk}")
SDK=${ANDROID_HOME:-$HOME/android-sdk}
BT=$SDK/build-tools/34.0.0
JAR=$SDK/platforms/android-34/android.jar
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W=$BUILD/apk-staging
rm -rf "$W"; mkdir -p "$W/classes" "$W/lib/arm64-v8a"

[ -f "$BUILD/libmain.so" ] || { echo "no $BUILD/libmain.so: build the project with the NDK first" >&2; exit 1; }

echo "Java: SDL's activity"
javac -nowarn -source 8 -target 8 -cp "$JAR" -d "$W/classes" \
    $(find "$SDLSRC/android-project/app/src/main/java" -name '*.java') 2>&1 | grep -v "^warning\|^Note:" || true
"$BT/d8" --release --min-api 29 --lib "$JAR" --output "$W" $(find "$W/classes" -name '*.class')

echo "Manifest, icon and native libraries"
# The launcher icon (android/res, made from branding/RE-Amped2.ico).
"$BT/aapt2" compile --dir "$HERE/res" -o "$W/res.zip"
"$BT/aapt2" link -o "$W/base.apk" --manifest "$HERE/AndroidManifest.xml" -I "$JAR" \
    --min-sdk-version 29 --target-sdk-version 34 "$W/res.zip"
cp "$BUILD/libmain.so" "$W/lib/arm64-v8a/"
cp "$SDLPRE/lib/libSDL2.so" "$W/lib/arm64-v8a/"
# Python's zipfile rather than zip(1), which many systems lack.
python3 - "$W" <<'PY'
import os, sys, zipfile
w = sys.argv[1]
with zipfile.ZipFile(os.path.join(w, "base.apk"), "a", zipfile.ZIP_DEFLATED) as z:
    z.write(os.path.join(w, "classes.dex"), "classes.dex")
    for name in sorted(os.listdir(os.path.join(w, "lib", "arm64-v8a"))):
        z.write(os.path.join(w, "lib", "arm64-v8a", name), "lib/arm64-v8a/" + name)
PY

echo "Align and sign"
"$BT/zipalign" -f -p 4 "$W/base.apk" "$W/aligned.apk"
KS=$HOME/.android/debug.keystore
if [ ! -f "$KS" ]; then
    mkdir -p "$(dirname "$KS")"
    keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
        -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
        -dname "CN=Android Debug,O=Android,C=US" >/dev/null
fi
"$BT/apksigner" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
    --out "$OUT" "$W/aligned.apk"
"$BT/apksigner" verify "$OUT" && ls -la "$OUT"
