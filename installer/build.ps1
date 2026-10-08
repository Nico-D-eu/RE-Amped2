<#
.SYNOPSIS
    Builds installer\dist\Amped2-Setup.exe, the player-facing installer.

.DESCRIPTION
    1. Packs obj\payload.zip:
         amped2\       this project's files (git-tracked and untracked but
                       not ignored, i.e. no game data, generated code or
                       build output), plus tools\bin\unluac.jar for the menu mod
         xboxrecomp\   the toolkit, the same way
         tools\        xdvdfs.exe, the disc extractor
         manifest.txt  the commits the sources come from
    2. Builds Amped2Installer.csproj (.NET Framework 4.8, WinForms) with the
       zip embedded, so the result is one self-contained .exe.

    The sources are taken from the working trees as they are, uncommitted
    changes included; manifest.txt notes when a tree was modified.

.PARAMETER Xdvdfs
    Path to xdvdfs.exe (default: next to the project folders).

.PARAMETER Unluac
    Path to unluac.jar (default: tools\bin\unluac.jar).
#>
param(
    [string]$Xdvdfs = '',
    [string]$Unluac = ''
)

$ErrorActionPreference = 'Stop'

$Installer = $PSScriptRoot
$Project   = Split-Path -Parent $Installer
$Root      = Split-Path -Parent $Project
$Toolkit   = Join-Path $Root 'xboxrecomp'
if (-not $Xdvdfs) { $Xdvdfs = Join-Path $Root 'xdvdfs.exe' }
if (-not $Unluac) { $Unluac = Join-Path $Project 'tools\bin\unluac.jar' }

foreach ($need in $Toolkit, $Xdvdfs, $Unluac) {
    if (-not (Test-Path $need)) { throw "Missing $need" }
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$obj = Join-Path $Installer 'obj'
New-Item -ItemType Directory -Force $obj | Out-Null
$zipPath = Join-Path $obj 'payload.zip'
if (Test-Path $zipPath) { Remove-Item $zipPath }

function Get-TreeFiles([string]$repo) {
    # Tracked plus untracked-but-not-ignored, relative, forward slashes.
    $files = git -C $repo ls-files --cached --others --exclude-standard
    if ($LASTEXITCODE -ne 0) { throw "git ls-files failed in $repo" }
    $files | Where-Object { Test-Path -LiteralPath (Join-Path $repo $_) -PathType Leaf }
}

function Get-Version([string]$repo) {
    $hash = git -C $repo rev-parse --short HEAD
    $dirty = git -C $repo status --porcelain --untracked-files=no
    if ($dirty) { "$hash+modified" } else { $hash }
}

$zip = [System.IO.Compression.ZipFile]::Open($zipPath, 'Create')
$count = 0
try {
    function Add-Entry([string]$file, [string]$entry) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $file, $entry, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
        $script:count++
    }

    foreach ($rel in Get-TreeFiles $Project) {
        if ($rel -like 'installer/*' -or $rel -like '.claude/*') { continue }   # not needed to build the game
        Add-Entry (Join-Path $Project $rel) "amped2/$rel"
    }
    Add-Entry $Unluac 'amped2/tools/bin/unluac.jar'

    foreach ($rel in Get-TreeFiles $Toolkit) {
        if ($rel -like '.claude/*') { continue }
        Add-Entry (Join-Path $Toolkit $rel) "xboxrecomp/$rel"
    }
    Add-Entry $Xdvdfs 'tools/xdvdfs.exe'

    $manifest = @(
        "amped2=$(Get-Version $Project)",
        "xboxrecomp=$(Get-Version $Toolkit)",
        "packed=$(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    ) -join "`r`n"
    $entry = $zip.CreateEntry('manifest.txt')
    $w = New-Object System.IO.StreamWriter $entry.Open()
    $w.Write($manifest)
    $w.Dispose()
} finally {
    $zip.Dispose()
}
$size = (Get-Item $zipPath).Length / 1MB
Write-Host ("Payload: {0} files, {1:N1} MB" -f $count, $size)
Write-Host $manifest

dotnet build (Join-Path $Installer 'Amped2Installer.csproj') -c Release --nologo -v minimal
if ($LASTEXITCODE -ne 0) { throw 'dotnet build failed' }

$dist = Join-Path $Installer 'dist'
New-Item -ItemType Directory -Force $dist | Out-Null
Copy-Item (Join-Path $Installer 'bin\Release\Amped2-Setup.exe') $dist -Force
$exe = Join-Path $dist 'Amped2-Setup.exe'
Write-Host ("`nBuilt {0} ({1:N1} MB)" -f $exe, ((Get-Item $exe).Length / 1MB)) -ForegroundColor Green
