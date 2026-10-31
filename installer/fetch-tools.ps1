<#
.SYNOPSIS
    Downloads the two third-party tools the installer ships, xdvdfs.exe and
    unluac.jar, and checks them against fixed SHA-256 hashes.

.DESCRIPTION
    Used by the release workflow (.github/workflows/installer.yml), so a
    build from the public repositories ships exactly these files. Pass the
    results to build.ps1 with -Xdvdfs and -Unluac. To move to a newer
    version, change the URL and both hashes together, and the licence texts
    in licenses\ if they changed.

.PARAMETER OutDir
    Where to put the tools (created if missing).
#>
param(
    [Parameter(Mandatory)] [string]$OutDir
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Windows PowerShell 5.1's progress bar makes downloads crawl
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

New-Item -ItemType Directory -Force $OutDir | Out-Null
$OutDir = (Resolve-Path $OutDir).Path

function Get-Checked([string]$url, [string]$file, [string]$sha256) {
    # SourceForge answers browser-like agents, PowerShell's included, with
    # its download page instead of the file.
    Invoke-WebRequest $url -OutFile $file -UseBasicParsing -UserAgent 'Wget'
    $got = (Get-FileHash $file -Algorithm SHA256).Hash
    if ($got -ne $sha256) { throw "$file has SHA-256 $got, expected $sha256" }
}

# xdvdfs 0.8.3 (MIT), the Windows build from its GitHub release.
$zip = Join-Path $OutDir 'xdvdfs-windows.zip'
Get-Checked 'https://github.com/antangelo/xdvdfs/releases/download/v0.8.3/xdvdfs-windows-1cc850bf1b3487fad7ec7c9eed01d83e8fc75ba4.zip' `
    $zip '008b1b3a63f1ecb00d1ed51ab154053fd0f7c41c68e973455bbe77ab989a7cc5'
$unz = Join-Path $OutDir 'xdvdfs'
Expand-Archive $zip $unz -Force
$xdvdfs = Join-Path $OutDir 'xdvdfs.exe'
Move-Item (Join-Path $unz 'xdvdfs.exe') $xdvdfs -Force
Remove-Item $zip, $unz -Recurse -Force
if ((Get-FileHash $xdvdfs -Algorithm SHA256).Hash -ne 'df5f19954ef706c130c256546bf67cf7725611bdb30d1815577187007a6f907a') {
    throw 'xdvdfs.exe in the zip is not the expected build'
}

# unluac 2025-12-23 (MIT), from SourceForge.
Get-Checked 'https://downloads.sourceforge.net/project/unluac/Unstable/unluac_2025_12_23.jar' `
    (Join-Path $OutDir 'unluac.jar') '98be0fa84ac73ca66dce2842a2e4512226f4c611b6500dc96415571fc5538fcc'

Write-Host "xdvdfs.exe and unluac.jar in $OutDir, hashes checked"
