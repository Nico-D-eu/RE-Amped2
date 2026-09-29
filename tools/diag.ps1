<#
.SYNOPSIS
    One diagnostic run of amped2_recomp.exe with a set of runtime switches.

.DESCRIPTION
    Sets the given RECOMP_* environment variables for this run only, runs the
    exe from the project root for -Seconds, kills it if still running, and
    writes stderr to diag\<Name>.txt. Then prints a short summary so runs can
    be compared side by side.

    The watchdog (RECOMP_WATCHDOG_SECS) calls _exit(3) after its dump, so a run
    with it set ending on its own is expected.

    -FreshSave moves the title's saved profiles (game\UDATA\4d530041\<id>
    directories) into diag\saves_moved\<timestamp>\ before the run, so an
    unattended walk creates a new player instead of stopping at "That player
    already exists. Overwrite?" (default No, which loops back to name
    entry). Moved, never deleted: copy a directory back to restore it.

.EXAMPLE
    .\tools\diag.ps1 vblank @{ RECOMP_VBLANK = '1'; RECOMP_WATCHDOG_SECS = '20' }
#>
param(
    [Parameter(Mandatory)] [string]$Name,
    [hashtable]$Env = @{},
    [int]$Seconds = 30,
    [switch]$FreshSave
)

$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
$Exe     = Join-Path $Project 'build\Release\amped2_recomp.exe'
$OutDir  = Join-Path $Project 'diag'
$Log     = Join-Path $OutDir "$Name.txt"
$Stdout  = Join-Path $OutDir "$Name.stdout.txt"
New-Item -ItemType Directory -Force $OutDir | Out-Null

if ($FreshSave) {
    $udata = Join-Path $Project 'game\UDATA\4d530041'
    $profiles = @(Get-ChildItem -Path $udata -Directory -ErrorAction SilentlyContinue)
    if ($profiles.Count) {
        $dest = Join-Path $OutDir ("saves_moved\" + (Get-Date -Format 'yyyyMMdd_HHmmss'))
        New-Item -ItemType Directory -Force $dest | Out-Null
        foreach ($d in $profiles) { Move-Item -LiteralPath $d.FullName -Destination $dest }
        Write-Host "  moved $($profiles.Count) saved profile(s) to $dest"
    }
}

$saved = @{}
foreach ($k in $Env.Keys) {
    $saved[$k] = [Environment]::GetEnvironmentVariable($k)
    [Environment]::SetEnvironmentVariable($k, [string]$Env[$k])
}
try {
    $p = Start-Process -FilePath $Exe -WorkingDirectory $Project -PassThru `
        -RedirectStandardError $Log -RedirectStandardOutput $Stdout
    if ($p.WaitForExit($Seconds * 1000)) {
        $ending = "exited by itself (code $($p.ExitCode))"
    } else {
        Stop-Process -Id $p.Id -Force
        $ending = "still running after ${Seconds}s, killed"
    }
} finally {
    foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k]) }
}

$s = Get-Content $Log
# Case-sensitive: the runtime's markers are upper-case, and a case-insensitive
# 'CRASH' also matches the title's own audio banks (Crashes.xsb).
function Count($pat) { ($s | Select-String -CaseSensitive -Pattern $pat).Count }
$switches = ($Env.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ' '
$files = $s | Select-String '\[PATH\] \\Device\\CdRom0\\(.+)$' |
    ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -Unique

Write-Host "=== $Name  [$switches]" -ForegroundColor Cyan
Write-Host "  $ending; $($s.Count) log lines -> diag\$Name.txt"
Write-Host ("  crash={0} icall_fail={1} unimpl={2} display_mode={3} flips={4} dma_put_moves={5} threads={6}" -f `
    (Count '\[CRASH\]'), (Count 'Failed to resolve'), (Count '\[UNIMPL\]'), (Count '\[AV\] SetDisplayMode'),
    (Count '(?i)\bflip'), (Count 'DMA_PUT ='), (Count 'spawned worker'))
Write-Host "  contiguous-arena failures: $(Count '\[CONTIG\] arena exhausted')"
Write-Host "  disc files: $($files.Count) distinct, last: $(($files | Select-Object -Last 3) -join ', ')"
$wd = ($s | Select-String '\[WATCHDOG\]' | Select-Object -First 1)
if ($wd) {
    Write-Host "  $($wd.Line.Trim())"
    $s[$wd.LineNumber..($wd.LineNumber + 4)] | ForEach-Object { Write-Host "  $_" }
}
Write-Host '  last non-trace lines:'
$s | Where-Object { $_ -notmatch '^\s+(GS |\[PATH\]|\[READ\]|\[HEAP\])' } | Select-Object -Last 6 |
    ForEach-Object { Write-Host "    $_" }
