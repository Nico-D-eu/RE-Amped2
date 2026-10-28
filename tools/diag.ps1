<#
.SYNOPSIS
    One diagnostic run of RE-Amped2.exe with a set of runtime switches.

.DESCRIPTION
    Sets the given RECOMP_* environment variables for this run only, runs the
    exe from the project root for -Seconds, kills it if still running, and
    writes stderr to diag\<Name>.txt. Then prints a short summary so runs can
    be compared side by side.

    The watchdog (RECOMP_WATCHDOG_SECS) calls _exit(3) after its dump, so a run
    with it set ending on its own is expected.

    Every run is isolated (tools\testenv.ps1): it writes its saves to
    test\runs\<Name>\hdd, the console's storage to test\storage, and reads
    test\amped2.ini, so it never changes the player's saves, caches or
    settings. By default the hdd starts as a copy of the player's
    game\UDATA and game\TDATA, so the run has their unlocks; the player's
    folders are only read. Their profile was moved aside and back by
    -FreshSave until 2026-10-28, and on 2026-10-01 it was left aside.

    -FreshSave starts from an empty hdd: a new console, so an unattended walk
    creates a new player instead of stopping at "That player already exists.
    Overwrite?".
    -Fixture <name> starts from test\fixtures\<name> instead.
    -Shared runs on the player's own saves and settings, as runs did before
    isolation. Only for looking at their actual state, never for tests.

    The run refuses to start while another RE-Amped2 is running (the player
    may be playing), unless -AllowParallel says the player is fine with it.

.EXAMPLE
    .\tools\diag.ps1 vblank @{ RECOMP_VBLANK = '1'; RECOMP_WATCHDOG_SECS = '20' }
#>
param(
    [Parameter(Mandatory)] [string]$Name,
    [hashtable]$Env = @{},
    [int]$Seconds = 30,
    [switch]$FreshSave,
    [string]$Fixture = '',
    # The default now (a copy of the player's saves); kept so older command
    # lines still work.
    [switch]$KeepSave,
    [switch]$Shared,
    [switch]$AllowParallel,
    # Another build of the exe in build\Release, e.g. a copy taken so a rebuild
    # can relink RE-Amped2.exe while this run is going.
    [string]$ExeName = 'RE-Amped2.exe'
)

$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
$Exe     = Join-Path $Project "build\Release\$ExeName"
$OutDir  = Join-Path $Project 'diag'
$Log     = Join-Path $OutDir "$Name.txt"
$Stdout  = Join-Path $OutDir "$Name.stdout.txt"
New-Item -ItemType Directory -Force $OutDir | Out-Null

if ($Shared -and ($FreshSave -or $Fixture)) {
    throw '-Shared runs on the player''s own saves; -FreshSave and -Fixture need an isolated run.'
}

$running = @(Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -in 'RE-Amped2', 'amped2_recomp' })
if ($running.Count -and -not $AllowParallel) {
    throw ("RE-Amped2 is already running (pid $($running.Id -join ', ')); the player may be " +
           "playing. Wait, or pass -AllowParallel if they agreed.")
}
if ($running.Count -and $Shared) {
    throw '-Shared with a running game would open the same saves twice.'
}

$runEnv = @{}
if (-not $Shared) {
    $Test = & (Join-Path $PSScriptRoot 'testenv.ps1')
    $RunDir = Join-Path $Test "runs\$Name"
    $Hdd = Join-Path $RunDir 'hdd'
    # Each run starts from its own fresh copy; the last one's hdd is replaced.
    if (Test-Path $Hdd) { Remove-Item -Recurse -Force -LiteralPath $Hdd }
    New-Item -ItemType Directory -Force $Hdd | Out-Null
    if ($Fixture) {
        $from = Join-Path $Test "fixtures\$Fixture"
        if (-not (Test-Path $from)) { throw "No fixture $from" }
        Copy-Item -Recurse -Path (Join-Path $from '*') -Destination $Hdd
        $start = "fixture $Fixture"
    } elseif ($FreshSave) {
        $start = 'empty (fresh console)'
    } else {
        foreach ($d in 'UDATA', 'TDATA') {
            $src = Join-Path $Project "game\$d"
            if (Test-Path $src) { Copy-Item -Recurse -Path $src -Destination $Hdd }
        }
        $start = "a copy of the player's saves"
    }
    # The storage is shared by test runs, so caches stay warm, but the game
    # writes its cache partitions with exclusive opens: next to another
    # instance, a run gets storage of its own.
    $storage = Join-Path $Test 'storage'
    if ($running.Count) {
        $storage = Join-Path $RunDir 'storage'
        Write-Host "  another instance is running: this run uses its own storage, $storage"
    }
    $runEnv = @{
        RECOMP_HDD_DIR       = $Hdd
        RECOMP_SAVE_DIR      = $storage
        RECOMP_SHADER_CACHE  = Join-Path $Test 'shader_cache'
        AMPED2_INI           = Join-Path $Test 'amped2.ini'
        AMPED2_COVERAGE_FILE = Join-Path $Test 'amped2-coverage.txt'
        AMPED2_CRASH_DIR     = Join-Path $RunDir 'crash'
    }
    Write-Host "  isolated run in $RunDir; saves start as $start"
}

# The caller's switches win over the isolation defaults, so a run can still
# point one of them elsewhere on purpose.
foreach ($k in $Env.Keys) { $runEnv[$k] = [string]$Env[$k] }

$saved = @{}
foreach ($k in $runEnv.Keys) {
    $saved[$k] = [Environment]::GetEnvironmentVariable($k)
    [Environment]::SetEnvironmentVariable($k, [string]$runEnv[$k])
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
    if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force; $p.WaitForExit(5000) | Out-Null }
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
Write-Host ("  crash={0} icall_fail={1} unimpl={2} reached={3} display_mode={4} flips={5} dma_put_moves={6} threads={7}" -f `
    (Count '\[CRASH\]'), (Count 'Failed to resolve'), (Count '\[UNIMPL\]'), (Count '\[REACHED\]'),
    (Count '\[AV\] SetDisplayMode'), (Count '(?i)\bflip'), (Count 'DMA_PUT ='), (Count 'spawned worker'))
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
