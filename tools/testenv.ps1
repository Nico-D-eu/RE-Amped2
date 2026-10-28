<#
.SYNOPSIS
    Sets up test\, the place test runs keep everything they write.

.DESCRIPTION
    A test run must never change the player's saves or settings, and must be
    able to run while the player's own game is open. The game reads its disc
    files from game\ like any run (read-only opens share, toolkit
    kernel_file.c), but everything it writes goes under test\:

      test\storage\          the console's storage (RECOMP_SAVE_DIR): partition
                             images and the cache partitions, shared by test
                             runs so their caches stay warm (a run started
                             next to another instance uses
                             test\runs\<name>\storage instead: the game
                             writes its caches with exclusive opens)
      test\runs\<name>\hdd\  E: for one run (RECOMP_HDD_DIR): UDATA and TDATA,
                             a copy of the player's, a fixture's, or empty
      test\runs\<name>\crash crash reports from that run (AMPED2_CRASH_DIR)
      test\amped2.ini        test settings (AMPED2_INI), the game's defaults
                             unless edited
      test\shader_cache\     compiled shaders (RECOMP_SHADER_CACHE), seeded
                             from the project's, so a run doesn't start cold
      test\amped2-coverage.txt  what test runs reached (AMPED2_COVERAGE_FILE),
                             kept apart from the player's list
      test\fixtures\<name>\  saved profiles for tests that need progress
                             (UDATA\ and TDATA\ as in game\), copied in only
                             with the player's OK

    tools\diag.ps1 calls this before every run; it only creates what is
    missing and copies shaders newer than the test copy. test\ is git-ignored.
#>
param()

$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
$Test    = Join-Path $Project 'test'

foreach ($d in 'storage', 'runs', 'fixtures', 'shader_cache') {
    New-Item -ItemType Directory -Force (Join-Path $Test $d) | Out-Null
}

$cache = Join-Path $Project 'shader_cache'
if (Test-Path $cache) {
    # /XO: only shaders the test copy lacks or has older. Exit codes below 8
    # are success for robocopy.
    robocopy $cache (Join-Path $Test 'shader_cache') /E /XO /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy of the shader cache failed ($LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
}

$Test
