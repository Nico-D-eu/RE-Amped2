<#
.SYNOPSIS
    Build RE-Amped2 for Android (an APK) on Windows, from code already
    generated from the player's own disc, and optionally install it on a
    phone connected over USB.

.DESCRIPTION
    The Windows installer runs this when the player ticks "Also build for
    Android"; it works on its own too, after a normal install or a
    developer build (src\recomp\gen in place). It downloads, pinned and
    hash-checked, into -Work:
      - Microsoft's build of OpenJDK 17 (javac, keytool; the SDK tools need
        Java);
      - Google's Android command-line tools, whose sdkmanager installs the
        exact SDK packages below and checks them (this accepts Google's
        Android SDK licence, so only with -AcceptAndroidLicenses: the
        installer asks the player first);
      - the SDL2 2.30.10 source release (its Java activity and the library).
    Then it builds SDL2 and the game with the NDK (arm64-v8a, Android 10 and
    later), packs and signs the APK with a key made on this PC, and with
    -InstallOnPhone installs it through adb and copies the game data into
    the app's folder (Android/data/org.reamped2.app/files).

    No game data or generated code goes anywhere but this PC and the
    player's own phone.

.EXAMPLE
    .\tools\android\build_android.ps1 -Work C:\Temp\a2android -AcceptAndroidLicenses -InstallOnPhone -Game .\game
#>
param(
    [string]$Amped2 = '',               # project folder (default: two levels above this script)
    [string]$Toolkit = '',
    [Parameter(Mandatory = $true)] [string]$Work,
    [string]$Out = '',
    [string]$Game = '',                 # extracted game folder, copied to the phone
    [string]$Mods = '',                 # optional mods folder (menus, packs), copied too
    [switch]$HdMovies,                  # with -Mods: copy mods\movie_pack (the HD movies, about 4 GB) too
    [switch]$AcceptAndroidLicenses,
    [switch]$InstallOnPhone,
    [switch]$PackOnly                   # reuse an existing libmain.so in -Work (testing)
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
# Windows PowerShell 5.1 leaves $PSScriptRoot empty in parameter defaults
# under -File, so the default is worked out here.
if (-not $Amped2) { $Amped2 = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
if (-not $Toolkit) { $Toolkit = Join-Path (Split-Path -Parent $Amped2) 'xboxrecomp' }
if (-not $Out) { $Out = $Work }
New-Item -ItemType Directory -Force $Work, $Out | Out-Null
$Work = (Resolve-Path $Work).Path
$Dl = Join-Path $Work 'downloads'
New-Item -ItemType Directory -Force $Dl | Out-Null

# Pinned downloads: name, URL, SHA-256.
$Pins = @(
    @{ Name = 'microsoft-jdk-17.0.13-windows-x64.zip'
       Url  = 'https://aka.ms/download-jdk/microsoft-jdk-17.0.13-windows-x64.zip'
       Sha  = 'A18DEBCF24C66BFB370467AA853696BBA45BE09F2B808E46931E91B2B5B072F0' },
    @{ Name = 'commandlinetools-win-11076708_latest.zip'
       Url  = 'https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip'
       Sha  = '4D6931209EEBB1BFB7C7E8B240A6A3CB3AB24479EA294F3539429574B1EEC862' },
    @{ Name = 'SDL2-2.30.10.tar.gz'
       Url  = 'https://github.com/libsdl-org/SDL/releases/download/release-2.30.10/SDL2-2.30.10.tar.gz'
       Sha  = 'F59ADF36A0FCF4C94198E7D3D776C1B3824211AB7AEEBEB31FE19836661196AA' }
)
$SdkPackages = @('platform-tools', 'platforms;android-34', 'build-tools;34.0.0',
                 'ndk;27.2.12479018', 'cmake;3.22.1')
$Package = 'org.reamped2.app'

function Step($t) { Write-Host "== $t ==" }
function Run($exe, [string[]]$a, [string]$what) {
    & $exe @a
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

Step 'Downloads'
foreach ($p in $Pins) {
    $f = Join-Path $Dl $p.Name
    if (-not (Test-Path $f) -or (Get-FileHash $f -Algorithm SHA256).Hash -ne $p.Sha) {
        Write-Host "  fetching $($p.Name)"
        # curl.exe (Windows 10 and later) is many times faster than
        # Invoke-WebRequest in Windows PowerShell 5.1.
        if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
            & curl.exe -sSL --fail -o $f $p.Url
            if ($LASTEXITCODE -ne 0) { throw "download of $($p.Name) failed (curl exit $LASTEXITCODE)" }
        } else {
            Invoke-WebRequest -Uri $p.Url -OutFile $f -UseBasicParsing
        }
    }
    $h = (Get-FileHash $f -Algorithm SHA256).Hash
    if ($h -ne $p.Sha) { Remove-Item $f; throw "$($p.Name): SHA-256 $h is not the pinned $($p.Sha)" }
}

$Jdk = Join-Path $Work 'jdk'
if (-not (Test-Path (Join-Path $Jdk 'bin\javac.exe'))) {
    Step 'JDK'
    $t = Join-Path $Work 'jdk-unpack'
    Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
    Expand-Archive (Join-Path $Dl $Pins[0].Name) $t
    Move-Item (Get-ChildItem $t -Directory | Select-Object -First 1).FullName $Jdk
    Remove-Item -Recurse -Force $t
}
$env:JAVA_HOME = $Jdk
$env:Path = (Join-Path $Jdk 'bin') + ';' + $env:Path

$Sdk = Join-Path $Work 'sdk'
$SdkMgr = Join-Path $Sdk 'cmdline-tools\latest\bin\sdkmanager.bat'
if (-not (Test-Path $SdkMgr)) {
    Step 'Android command-line tools'
    $t = Join-Path $Work 'clt-unpack'
    Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
    Expand-Archive (Join-Path $Dl $Pins[1].Name) $t
    New-Item -ItemType Directory -Force (Join-Path $Sdk 'cmdline-tools') | Out-Null
    Move-Item (Join-Path $t 'cmdline-tools') (Join-Path $Sdk 'cmdline-tools\latest')
    Remove-Item -Recurse -Force $t
}
$Ndk = Join-Path $Sdk 'ndk\27.2.12479018'
$Bt = Join-Path $Sdk 'build-tools\34.0.0'
$CmakeDir = Join-Path $Sdk 'cmake\3.22.1\bin'
if (-not (Test-Path (Join-Path $Ndk 'build\cmake\android.toolchain.cmake')) -or
        -not (Test-Path (Join-Path $Bt 'aapt2.exe')) -or -not (Test-Path (Join-Path $CmakeDir 'ninja.exe'))) {
    if (-not $AcceptAndroidLicenses) {
        throw 'Installing the Android SDK packages accepts Google''s Android SDK licence; run with -AcceptAndroidLicenses once the player has agreed.'
    }
    Step 'Android SDK packages (accepting the SDK licences)'
    # What `sdkmanager --licenses` writes when one answers "y": the accepted
    # Android SDK licence's hash in licenses\android-sdk-license (the
    # packages here are all under that licence). Its prompts cannot be
    # answered through a pipe from Windows PowerShell, and the installer has
    # already asked the player.
    $lic = Join-Path $Sdk 'licenses'
    New-Item -ItemType Directory -Force $lic | Out-Null
    [IO.File]::WriteAllText((Join-Path $lic 'android-sdk-license'), "`n24333f8a63b6825ea9c5514f83c2829b004d1fee")
    Run $SdkMgr (@("--sdk_root=$Sdk") + $SdkPackages) 'sdkmanager'
    if (-not (Test-Path (Join-Path $Ndk 'build\cmake\android.toolchain.cmake'))) {
        throw 'sdkmanager did not install the Android SDK packages (were the licences accepted?).'
    }
}
$Cmake = Join-Path $CmakeDir 'cmake.exe'
$Ninja = Join-Path $CmakeDir 'ninja.exe'
$Toolchain = Join-Path $Ndk 'build\cmake\android.toolchain.cmake'
$AbiArgs = @('-G', 'Ninja', "-DCMAKE_MAKE_PROGRAM=$Ninja", "-DCMAKE_TOOLCHAIN_FILE=$Toolchain",
             '-DANDROID_ABI=arm64-v8a', '-DANDROID_PLATFORM=android-29', '-DCMAKE_BUILD_TYPE=Release')

$SdlSrc = Join-Path $Work 'SDL2-2.30.10'
$SdlPre = Join-Path $Work 'sdl-prefix'
if (-not (Test-Path (Join-Path $SdlPre 'lib\libSDL2.so'))) {
    Step 'SDL2 for Android'
    # android-project-ant holds symlinks Windows' tar cannot make; unused.
    if (-not (Test-Path (Join-Path $SdlSrc 'CMakeLists.txt'))) {
        Run 'tar.exe' @('-xzf', (Join-Path $Dl $Pins[2].Name), '-C', $Work,
                        '--exclude', 'SDL2-2.30.10/android-project-ant') 'tar'
    }
    $b = Join-Path $Work 'build-sdl'
    Run $Cmake (@('-S', $SdlSrc, '-B', $b) + $AbiArgs + @("-DCMAKE_INSTALL_PREFIX=$SdlPre",
                 '-DSDL_STATIC=OFF', '-DSDL_SHARED=ON', '-DSDL_TEST=OFF')) 'SDL2 configure'
    Run $Cmake @('--build', $b, '--parallel') 'SDL2 build'
    Run $Cmake @('--install', $b) 'SDL2 install'
}

$Build = Join-Path $Work 'build-android'
if (-not $PackOnly) {
    Step 'RE-Amped2 for Android (the long step)'
    if (-not (Test-Path (Join-Path $Amped2 'src\recomp\gen\recomp_funcs.h'))) {
        throw "No generated code in $Amped2\src\recomp\gen: install or regenerate from the disc first."
    }
    Run $Cmake (@('-S', $Amped2, '-B', $Build) + $AbiArgs + @("-DCMAKE_FIND_ROOT_PATH=$SdlPre",
                 "-DSDL2_DIR=$SdlPre\lib\cmake\SDL2", "-DXBOXRECOMP_DIR=$Toolkit")) 'configure'
    Run $Cmake @('--build', $Build, '--parallel') 'build'
}
$Lib = Join-Path $Build 'libmain.so'
if (-not (Test-Path $Lib)) { throw "no $Lib" }

Step 'APK'
$Jar = Join-Path $Sdk 'platforms\android-34\android.jar'
$Here = Join-Path $Amped2 'android'
$W = Join-Path $Work 'apk-staging'
Remove-Item -Recurse -Force $W -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force (Join-Path $W 'classes'), (Join-Path $W 'lib\arm64-v8a') | Out-Null
$java = Get-ChildItem -Recurse (Join-Path $SdlSrc 'android-project\app\src\main\java') -Filter *.java | ForEach-Object FullName
Run (Join-Path $Jdk 'bin\javac.exe') (@('-nowarn', '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-cp', $Jar,
     '-d', (Join-Path $W 'classes')) + $java) 'javac'
$classes = Get-ChildItem -Recurse (Join-Path $W 'classes') -Filter *.class | ForEach-Object FullName
Run (Join-Path $Bt 'd8.bat') (@('--release', '--min-api', '29', '--lib', $Jar, '--output', $W) + $classes) 'd8'
Run (Join-Path $Bt 'aapt2.exe') @('compile', '--dir', (Join-Path $Here 'res'), '-o', (Join-Path $W 'res.zip')) 'aapt2 compile'
$base = Join-Path $W 'base.apk'
Run (Join-Path $Bt 'aapt2.exe') @('link', '-o', $base, '--manifest', (Join-Path $Here 'AndroidManifest.xml'),
     '-I', $Jar, '--min-sdk-version', '29', '--target-sdk-version', '34', (Join-Path $W 'res.zip')) 'aapt2 link'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::Open($base, 'Update')
try {
    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, (Join-Path $W 'classes.dex'), 'classes.dex')
    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, $Lib, 'lib/arm64-v8a/libmain.so')
    [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($z, (Join-Path $SdlPre 'lib\libSDL2.so'), 'lib/arm64-v8a/libSDL2.so')
} finally { $z.Dispose() }
$aligned = Join-Path $W 'aligned.apk'
Run (Join-Path $Bt 'zipalign.exe') @('-f', '-p', '4', $base, $aligned) 'zipalign'
# The player's own signing key, made once on this PC and kept in -Work.
$Ks = Join-Path $Work 're-amped2.keystore'
if (-not (Test-Path $Ks)) {
    Run (Join-Path $Jdk 'bin\keytool.exe') @('-genkeypair', '-keystore', $Ks, '-storepass', 'reamped2',
         '-keypass', 'reamped2', '-alias', 're-amped2', '-keyalg', 'RSA', '-keysize', '2048',
         '-validity', '10000', '-dname', 'CN=RE-Amped2 (built on this PC)') 'keytool'
}
$Apk = Join-Path $Out 'RE-Amped2.apk'
Run (Join-Path $Bt 'apksigner.bat') @('sign', '--ks', $Ks, '--ks-pass', 'pass:reamped2', '--key-pass', 'pass:reamped2',
     '--out', $Apk, $aligned) 'apksigner'
Run (Join-Path $Bt 'apksigner.bat') @('verify', $Apk) 'apksigner verify'
Write-Host "APK: $Apk ($([math]::Round((Get-Item $Apk).Length / 1MB)) MB)"

if ($InstallOnPhone) {
    Step 'Phone'
    $Adb = Join-Path $Sdk 'platform-tools\adb.exe'
    $dev = (& $Adb devices | Select-String "`tdevice$")
    if (-not $dev) { throw 'No phone over USB: switch on USB debugging, connect it, allow this PC, and run again.' }
    $res = & $Adb install -r $Apk 2>&1 | Out-String
    if ($res -match 'INSTALL_FAILED_UPDATE_INCOMPATIBLE|signatures do not match') {
        throw ('The phone already has a RE-Amped2 signed with another key (an older build). Android only installs over ' +
               'an app with the same key: uninstall RE-Amped2 on the phone first (that also deletes its game folder and ' +
               'saves on the phone; copy Android/data/org.reamped2.app/files/game/UDATA off first to keep them), then run again.')
    }
    if ($res -notmatch 'Success') { throw "adb install failed: $res" }
    # The app makes its own folder on first start; Android lets adb write
    # there only once it exists.
    & $Adb shell am start -n "$Package/org.libsdl.app.SDLActivity" | Out-Null
    Start-Sleep -Seconds 4
    & $Adb shell am force-stop $Package | Out-Null
    $F = "/sdcard/Android/data/$Package/files"
    if ($Game) {
        Write-Host '  copying the game (a few minutes)'
        # The game folder must exist first: "adb push Dir parent/" into a
        # parent that is not there yet makes parent a copy of Dir, so the
        # first folder (Animations) lost its own level and the game crashed
        # loading a level without its animations (2026-11-19).
        Run $Adb @('shell', 'mkdir', '-p', "$F/game") 'make the game folder'
        Get-ChildItem $Game | Where-Object { @('UDATA', 'TDATA', 'CACHE') -notcontains $_.Name } | ForEach-Object {
            Run $Adb @('push', $_.FullName, "$F/game/") "copy $($_.Name)"
        }
    }
    if ($Mods -and (Test-Path $Mods)) {
        # The menus (build), the packs and mods.json. Not cache (the game
        # rebuilds it), and the HD movies only with -HdMovies: about 4 GB
        # on the phone. mods/ is made first, for the reason above.
        Write-Host '  copying the mods'
        Run $Adb @('shell', 'mkdir', '-p', "$F/mods") 'make the mods folder'
        $skip = @('cache')
        if (-not $HdMovies) { $skip += 'movie_pack' }
        Get-ChildItem $Mods | Where-Object { $skip -notcontains $_.Name } | ForEach-Object {
            Run $Adb @('push', $_.FullName, "$F/mods/") "copy mods\$($_.Name)"
        }
    }
    Write-Host 'Installed. Start RE-Amped2 from the phone''s app list; a Bluetooth or USB gamepad plays it.'
}
