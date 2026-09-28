<#
.SYNOPSIS
    Regenerate Amped 2's recompiled C from game\default.xbe.

.DESCRIPTION
    Runs the xboxrecomp pipeline (GETTING_STARTED.md steps 2-5) from inside the
    toolkit clone, since that is where tools\ lives, and writes the generated
    code into this project's src\recomp\gen.

      2    xbe_parser    -> game\default_analysis.json
      3    disasm        -> xboxrecomp\tools\disasm\output\functions.json
                            (all code sections, not --text-only: .text calls
                            straight into D3D, DSOUND, XPP, XMV ...)
      4    func_id       -> xboxrecomp\tools\func_id\output\
      4.5  abi_analysis  -> xboxrecomp\tools\abi_analysis\output\abi_functions.json
      4.6  merge_names   -> Ghidra FidDb names written into functions.json
                            (uses the cached export; -Ghidra re-runs Ghidra)
      5    recomp        -> src\recomp\gen\

    Step 3 rewrites functions.json from scratch, so step 4.6 has to run after
    it every time -- which is why it is part of this script and not a one-off.

.PARAMETER Ghidra
    Re-run the headless Ghidra analysis (slow) before merging names.

.PARAMETER SkipAnalysis
    Skip steps 2-4.6 and only re-run the recompiler (e.g. after editing
    recomp_manual.c overrides or passing new --force-return probes).

.PARAMETER RecompArgs
    Extra arguments passed straight to tools.recomp, e.g.
    -RecompArgs '--force-return','0x0015D780=0'
#>
param(
    [switch]$Ghidra,
    [switch]$SkipAnalysis,
    [string[]]$RecompArgs = @()
)

$ErrorActionPreference = 'Stop'

$Project = Split-Path -Parent $PSScriptRoot
$Toolkit = Join-Path (Split-Path -Parent $Project) 'xboxrecomp'
$Ghidra_Home = Join-Path (Split-Path -Parent $Project) 'Ghidra'
$Xbe     = Join-Path $Project 'game\default.xbe'
$GenDir  = Join-Path $Project 'src\recomp\gen'
$Seeds   = Join-Path $Project 'config\seed_functions.json'

if (-not (Test-Path $Xbe)) {
    throw "No XBE at $Xbe -- extract the disc first (see README.md)."
}

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    & $Body
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit $LASTEXITCODE)" }
}

Push-Location $Toolkit
try {
    if (-not $SkipAnalysis) {
        Invoke-Step 'Step 2: parse XBE' {
            py -3 -m tools.xbe_parser $Xbe --json (Join-Path $Project 'game\default_analysis.json')
        }
        Invoke-Step 'Step 3: disassemble' {
            # Function starts only a run can see (thread routines, indirect-call
            # targets). Grow it with:
            #   py -3 -m tools.seed_from_log <run log> <xbe> --functions
            #       tools\disasm\output\functions.json --seeds <this file>
            $seedArgs = @()
            if (Test-Path $Seeds) { $seedArgs = @('--seed-functions', $Seeds) }
            py -3 -m tools.disasm $Xbe -v @seedArgs
        }
        Invoke-Step 'Step 4: identify functions' {
            py -3 -m tools.func_id $Xbe -v
        }
        Invoke-Step 'Step 4.5: recover calling conventions' {
            py -3 -m tools.abi_analysis $Xbe -v
        }

        if ($Ghidra) {
            Invoke-Step 'Step 4.6a: headless Ghidra analysis' {
                $bashXbe  = ($Xbe -replace '\\', '/') -replace '^([A-Za-z]):', '/$1'
                $bashHome = ($Ghidra_Home -replace '\\', '/') -replace '^([A-Za-z]):', '/$1'
                # Git Bash, which is not normally on PowerShell's PATH.
                $gitBash = Join-Path (Split-Path (Split-Path (Get-Command git).Source)) 'bin\bash.exe'
                & $gitBash -c "GHIDRA_HOME='$bashHome' XBE='$bashXbe' tools/ghidra_naming/run_ghidra.sh"
            }
        }
        if (Test-Path 'tools\ghidra_naming\export\functions.json') {
            Invoke-Step 'Step 4.6: apply Ghidra names' {
                py -3 tools/ghidra_naming/merge_names.py --apply
            }
        } else {
            Write-Host "`n(no Ghidra export cached -- skipping names; run with -Ghidra)" -ForegroundColor Yellow
        }
    }

    Invoke-Step 'Step 5: recompile' {
        # --exclude-manual: every sub_XXXXXXXX defined in recomp_manual.c is
        # declared but not generated, so the hand-written version links.
        # --manual-functions: the same for hand copies kept in other files
        # (src\lua_probe.c), which the scan of recomp_manual.c cannot see.
        $manualArgs = @()
        $manualJson = Join-Path $Project 'config\manual_functions.json'
        if (Test-Path $manualJson) { $manualArgs = @('--manual-functions', $manualJson) }
        py -3 -m tools.recomp $Xbe --all --split 250 --game-name 'Amped 2' `
            --gen-dir $GenDir `
            --exclude-manual (Join-Path $Project 'src\recomp_manual.c') `
            @manualArgs @RecompArgs
    }

    # Functions whose optimised compile time is pathological (config\no_optimize.txt):
    # wrap each in #pragma optimize("", off/on) in whichever chunk holds it. The
    # recompiler rewrites a chunk only when its output changes, and that output
    # never has the pragmas, so a chunk holding one of these is rewritten and
    # re-patched on every run -- one quick recompile, not a 30-minute one.
    $noOpt = Join-Path $Project 'config\no_optimize.txt'
    if (Test-Path $noOpt) {
        $names = Get-Content $noOpt | ForEach-Object { $_.Trim() } |
            Where-Object { $_ -and -not $_.StartsWith('#') }
        foreach ($name in $names) {
            $hit = Select-String -Path (Join-Path $GenDir 'recomp_*.c') `
                -Pattern "^void $name\(void\)$" | Select-Object -First 1
            if (-not $hit) { Write-Host "  no_optimize: $name not found" -ForegroundColor Yellow; continue }
            $lines = [System.Collections.Generic.List[string]](Get-Content -Encoding UTF8 $hit.Path)
            $start = $hit.LineNumber - 1
            if ($start -gt 0 -and $lines[$start - 1] -like '#pragma optimize*') { continue }
            $end = $start
            while ($end -lt $lines.Count -and $lines[$end] -ne '}') { $end++ }
            $lines.Insert($end + 1, '#pragma optimize("", on)')
            $lines.Insert($start, '#pragma optimize("", off)  /* config\no_optimize.txt */')
            Set-Content -Path $hit.Path -Value $lines -Encoding utf8
            Write-Host "  no_optimize: $name in $(Split-Path -Leaf $hit.Path)"
        }
    }
} finally {
    Pop-Location
}

Write-Host "`nGenerated code is in $GenDir" -ForegroundColor Green
Write-Host 'Build: cmake -S . -B build ; cmake --build build --config Release'
