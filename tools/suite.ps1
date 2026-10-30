<#
.SYNOPSIS
    The regression suite: runs named cases and says whether anything regressed.

.DESCRIPTION
    Each case in tools\suite\cases.json is one isolated tools\diag.ps1 run
    (its own saves and settings under test\, nothing of the player's
    touched). The case sets the switches, often a scripted pad, runs for a
    fixed time, and tools\suite\analyze.py checks what it left:
      - the log: markers that must appear in order, and things no run may
        show (a crash, the watchdog, a reboot into Boom.xbe, the title's
        out-of-memory handler, a bug check, the music replaying stale data);
      - [HEALTH]: idle voices linked stay 0;
      - [GPU] frames: the frame rate over a window, from a marker on;
      - [PACE] (RECOMP_PACE_TRACE, always on here): pacing resyncs;
      - diag.ps1 -Samples: private memory flat over the same window;
      - [REACHED]: no guessed or missing code beyond the coverage baseline;
      - RECOMP_GPU_SHOT_PRESENT frames: not black, and close to the golden.

    Everything a pass writes goes to diag\suite-<date-time>\: the logs,
    samples, shots, one JSON result per case and report.md.

    Goldens and the coverage baseline are local and git-ignored, because
    both come from the game (test\suite\goldens\<case>\, and
    test\suite\coverage-baseline.txt). -UpdateGoldens and -UpdateBaseline
    take them from this pass.

    Like any test run, the suite refuses to start while RE-Amped2 is
    running: the player may be playing.

.EXAMPLE
    .\tools\suite.ps1 -Quick
.EXAMPLE
    .\tools\suite.ps1 -Cases ml1 -Env @{ RECOMP_GPU_NODEPTH = '1' }
.EXAMPLE
    .\tools\suite.ps1 -Repeat 3
#>
param(
    [string[]]$Cases = @(),
    # Only the cases marked quick (boot, ml1).
    [switch]$Quick,
    # The soak runs only when named or with -Soak.
    [switch]$Soak,
    [int]$Repeat = 1,
    # Switches for every case, over the case's own: an injected regression,
    # or a diagnostic.
    [hashtable]$Env = @{},
    [string]$ExeName = 'RE-Amped2.exe',
    [switch]$UpdateGoldens,
    [switch]$UpdateBaseline
)

$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
$Suite   = Join-Path $PSScriptRoot 'suite'
$Local   = Join-Path $Project 'test\suite'
$Goldens = Join-Path $Local 'goldens'
$Baseline = Join-Path $Local 'coverage-baseline.txt'
New-Item -ItemType Directory -Force $Goldens | Out-Null

$all = (Get-Content -Raw (Join-Path $Suite 'cases.json') | ConvertFrom-Json).cases
if ($Cases.Count) {
    $chosen = foreach ($n in $Cases) {
        $c = $all | Where-Object name -eq $n
        if (-not $c) { throw "No case '$n' (cases: $(($all.name) -join ', '))" }
        $c
    }
} elseif ($Quick) {
    $chosen = $all | Where-Object { $_.quick }
} else {
    $chosen = $all | Where-Object { $_.name -ne 'soak' -or $Soak }
}

$running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like 'RE-Amped2*' })
if ($running.Count) {
    throw "RE-Amped2 is running (pid $($running.Id -join ', ')); the player may be playing."
}

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmm'
$runName = "suite-$stamp"
$Out = Join-Path $Project "diag\$runName"
New-Item -ItemType Directory -Force $Out | Out-Null
$exe = Join-Path $Project "build\Release\$ExeName"
$t0 = Get-Date
$injected = ($Env.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Name)=$($_.Value)" }) -join ' '
Write-Host "Suite ${runName}: $(@($chosen).Count) case(s) x $Repeat on $ExeName ($((Get-Item $exe).LastWriteTime))" -ForegroundColor Cyan
if ($injected) { Write-Host "  injected: $injected" -ForegroundColor Yellow }

$results = @()
for ($rep = 1; $rep -le $Repeat; $rep++) {
    foreach ($c in $chosen) {
        $id = if ($Repeat -gt 1) { "$($c.name)-$rep" } else { $c.name }
        $missing = @($c.requires | Where-Object { $_ -and -not (Test-Path (Join-Path $Project $_)) })
        if ($missing.Count) {
            Write-Host ("  {0,-10} SKIP  needs {1}" -f $id, ($missing -join ', ')) -ForegroundColor DarkGray
            $results += [pscustomobject]@{ case = $id; pass = $null; skipped = "needs $($missing -join ', ')" }
            continue
        }

        $e = @{
            RECOMP_PACE_TRACE    = '1'
            # Off, so every address the run reaches is printed: a coverage
            # file already holding it would keep it quiet.
            AMPED2_COVERAGE_FILE = '0'
        }
        # "@pads\x.pad" (a pad script file) is relative to tools\suite.
        $c.env.PSObject.Properties | ForEach-Object {
            $v = [string]$_.Value
            if ($v -like '@pads*') { $v = '@' + (Join-Path $Suite $v.Substring(1)) }
            $e[$_.Name] = $v
        }
        $prefix = "${id}_"
        if ($c.shot_ms) {
            $e['RECOMP_GPU_SHOT_PRESENT'] = Join-Path $Out $prefix
            $e['RECOMP_GPU_SHOT_MS'] = [string]$c.shot_ms
        }
        foreach ($k in $Env.Keys) { $e[$k] = [string]$Env[$k] }

        $save = @{}
        if ($c.save -eq 'fresh') { $save.FreshSave = $true }
        elseif ($c.save -like 'fixture:*') { $save.Fixture = $c.save.Substring(8) }

        Write-Host ("  {0,-10} running {1} s ..." -f $id, $c.seconds) -NoNewline
        & (Join-Path $PSScriptRoot 'diag.ps1') "$runName\$id" $e $c.seconds -Samples -ExeName $ExeName @save *> (Join-Path $Out "$id.diag.txt")

        $caseFile = Join-Path $Out "$id.case.json"
        $c | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 $caseFile
        $args_ = @((Join-Path $Suite 'analyze.py'), $caseFile, (Join-Path $Out "$id.txt"),
            '--samples', (Join-Path $Out "$id.samples.csv"),
            '--shots', $Out, '--shot-prefix', $prefix,
            '--goldens', (Join-Path $Goldens $c.name),
            '--crash-dir', (Join-Path $Project "test\runs\$runName\$id\crash"))
        # An -UpdateBaseline pass takes the baseline from what it reaches.
        if (-not $UpdateBaseline) { $args_ += '--baseline', $Baseline }
        $json = & py -3 -I @args_
        if ($LASTEXITCODE) { throw "analyze.py failed on $id" }
        $json | Set-Content -Encoding utf8 (Join-Path $Out "$id.result.json")
        $r = $json | ConvertFrom-Json
        $r | Add-Member -NotePropertyName case -NotePropertyValue $id -Force
        $results += $r

        $m = $r.metrics
        $bits = @()
        if ($null -ne $m.fps) { $bits += "$($m.fps) fps (slowest 10 s $($m.fps_min_10s))" }
        if ($m.private_mb) { $bits += "mem $($m.private_mb[0])->$($m.private_mb[1]) MB" }
        $bad = @($r.checks | Where-Object { -not $_.ok })
        $word = if ($r.pass) { 'PASS' } else { 'FAIL' }
        Write-Host (" {0}  {1}" -f $word, ($bits -join ', ')) -ForegroundColor $(if ($r.pass) { 'Green' } else { 'Red' })
        foreach ($b in $bad) {
            $tag = if ($b.warn) { 'warn' } else { 'FAIL' }
            Write-Host ("               {0}: {1}  {2}" -f $tag, $b.check, $b.detail) -ForegroundColor $(if ($b.warn) { 'Yellow' } else { 'Red' })
        }

        if ($UpdateGoldens) {
            $dir = Join-Path $Goldens $c.name
            New-Item -ItemType Directory -Force $dir | Out-Null
            foreach ($s in $c.checks.shots) {
                $src = Join-Path $Out ('{0}{1:D4}.bmp' -f $prefix, $s.index)
                if (Test-Path $src) { Copy-Item $src (Join-Path $dir ('{0:D4}.bmp' -f $s.index)) -Force }
            }
            Write-Host "               goldens for $($c.name) taken from this run" -ForegroundColor DarkGray
        }
        if ($UpdateBaseline -and $r.metrics.reached) {
            $have = @(if (Test-Path $Baseline) { Get-Content $Baseline })
            $new = @($r.metrics.reached | Where-Object { $have -notcontains $_ })
            if (-not (Test-Path $Baseline)) {
                '# Coverage the suite accepts: kind and guest address, one per line (tools\suite.ps1 -UpdateBaseline).' |
                    Set-Content -Encoding ascii $Baseline
            }
            if ($new.Count) { $new | Add-Content -Encoding ascii $Baseline }
            Write-Host "               baseline: $($new.Count) address(es) added" -ForegroundColor DarkGray
        }
    }
}

# The report.
$ran = @($results | Where-Object { $null -ne $_.pass })
$failed = @($ran | Where-Object { -not $_.pass })
$minutes = ((Get-Date) - $t0).TotalMinutes
$md = @("# Suite $runName", '',
    "- exe: ``build\Release\$ExeName``, build $(($ran | Select-Object -First 1).metrics.build)",
    "- injected: $(if ($injected) { $injected } else { 'none' })",
    ("- {0} passed, {1} failed, {2} skipped, in {3:F1} min" -f ($ran.Count - $failed.Count), $failed.Count,
        ($results.Count - $ran.Count), $minutes), '',
    '| Case | Result | fps (slowest 10 s) | Private MB | Resyncs | Stalls |', '|---|---|---|---|---|---|')
foreach ($r in $results) {
    if ($null -eq $r.pass) { $md += "| $($r.case) | skipped ($($r.skipped)) | | | | |"; continue }
    $m = $r.metrics
    $md += ('| {0} | {1} | {2} | {3} | {4} | {5} |' -f $r.case, $(if ($r.pass) { 'pass' } else { '**FAIL**' }),
        $(if ($null -ne $m.fps) { "$($m.fps) ($($m.fps_min_10s))" } else { '' }),
        $(if ($m.private_mb) { "$($m.private_mb[0]) -> $($m.private_mb[1])" } else { '' }),
        $m.pace_resyncs, $m.stalls)
}
foreach ($r in $ran) {
    $md += '', "## $($r.case)", ''
    foreach ($ch in $r.checks) {
        $mark = if ($ch.ok) { 'x' } elseif ($ch.warn) { '~' } else { ' ' }
        $md += "- [$mark] $($ch.check)$(if ($ch.detail) { ": $($ch.detail)" })"
    }
}
$md | Set-Content -Encoding utf8 (Join-Path $Out 'report.md')

$colour = if ($failed.Count) { 'Red' } else { 'Green' }
Write-Host ("{0}: {1} of {2} passed in {3:F1} min -> diag\{4}\report.md" -f `
    $(if ($failed.Count) { 'FAILED' } else { 'PASSED' }), ($ran.Count - $failed.Count), $ran.Count, $minutes, $runName) -ForegroundColor $colour
exit $(if ($failed.Count) { 1 } else { 0 })
