<#
.SYNOPSIS
    Pack the launcher zip: RE-Amped2-v<version>-Windows-x64.zip, holding
    RE-Amped2-Setup.exe and recomplauncher.json.

.DESCRIPTION
    RecompLauncher installs a release's Windows .zip in preference to an
    installer .exe, picks it by the system and processor in its name, and
    reads recomplauncher.json beside the program. That file runs the
    installer headless (--prepare) on the launcher's setup screen, then
    starts RE-Amped2.exe.

    prepare.version in the packed file is set to the installer's version
    (Amped2Installer.csproj): when it changes, RecompLauncher runs the build
    again, which every update needs, since RE-Amped2.exe is compiled from that
    release's sources.

    build.ps1 runs this on the unsigned installer; the release workflow runs
    it again on the signed one.

.EXAMPLE
    .\installer\pack-launcher-zip.ps1 -Exe .\installer\dist\RE-Amped2-Setup.exe
#>
param(
    [Parameter(Mandatory = $true)] [string]$Exe,
    [string]$Out = ''
)
$ErrorActionPreference = 'Stop'
$Installer = $PSScriptRoot
if (-not $Out) { $Out = Split-Path -Parent (Resolve-Path $Exe) }

[xml]$proj = Get-Content (Join-Path $Installer 'Amped2Installer.csproj')
$version = ($proj.Project.PropertyGroup | Where-Object { $_.Version } | Select-Object -First 1).Version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "No version in Amped2Installer.csproj (found '$version')" }

$json = Get-Content (Join-Path $Installer 'recomplauncher.json') -Raw -Encoding UTF8
$stamped = [regex]::Replace($json, '("version"\s*:\s*")[^"]*(")', "`${1}$version`${2}", 1)
if ($stamped -notmatch [regex]::Escape("""version"": ""$version""")) { throw 'recomplauncher.json has no prepare "version" to set' }

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zipPath = Join-Path $Out "RE-Amped2-v$version-Windows-x64.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath }
$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
try {
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $zip, (Resolve-Path $Exe), 'RE-Amped2-Setup.exe', [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    $entry = $zip.CreateEntry('recomplauncher.json')
    $w = New-Object System.IO.StreamWriter($entry.Open(), (New-Object System.Text.UTF8Encoding $false))
    $w.Write($stamped)
    $w.Dispose()
} finally {
    $zip.Dispose()
}
Write-Host ("Launcher zip: {0} ({1:N1} MB, prepare version {2})" -f $zipPath, ((Get-Item $zipPath).Length / 1MB), $version)
