#!/usr/bin/env bash
# regen.sh - Regenerate Amped 2's recompiled C from game/default.xbe on
# Linux. The same pipeline as tools/regen.ps1 (steps 2-5), without the
# Ghidra names, which the build does not need.
#
#   tools/linux/regen.sh [--python PATH] [--skip-analysis] [-- RECOMP_ARGS...]
#
#   --python PATH     the interpreter to run the toolkit with (default
#                     python3; the installer passes its virtual environment's)
#   --skip-analysis   only re-run the recompiler (step 5)
#
# Runs from inside ../xboxrecomp, where the tools live, and writes
# src/recomp/gen. config/no_optimize.txt is not applied: it holds MSVC
# pragmas for one slow function, and GCC and Clang compile it quickly.
set -euo pipefail

PYTHON=python3
SKIP_ANALYSIS=0
RECOMP_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --python) PYTHON="$2"; shift 2 ;;
        --skip-analysis) SKIP_ANALYSIS=1; shift ;;
        --) shift; RECOMP_ARGS=("$@"); break ;;
        *) echo "regen.sh: unknown argument $1" >&2; exit 2 ;;
    esac
done

PROJECT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TOOLKIT=$(cd "$PROJECT/../xboxrecomp" && pwd)
XBE="$PROJECT/game/default.xbe"
GEN_DIR="$PROJECT/src/recomp/gen"
SEEDS="$PROJECT/config/seed_functions.json"

[ -f "$XBE" ] || { echo "No XBE at $XBE -- extract the disc first." >&2; exit 1; }

step() {
    echo
    local name="$1" rc=0
    echo "=== $name ==="
    shift
    "$@" || rc=$?
    [ "$rc" = 0 ] || { echo "$name failed (exit $rc)" >&2; exit 1; }
}

cd "$TOOLKIT"
if [ "$SKIP_ANALYSIS" = 0 ]; then
    step 'Step 2: parse XBE' \
        "$PYTHON" -m tools.xbe_parser "$XBE" --json "$PROJECT/game/default_analysis.json"
    seed_args=()
    [ -f "$SEEDS" ] && seed_args=(--seed-functions "$SEEDS")
    step 'Step 3: disassemble' "$PYTHON" -m tools.disasm "$XBE" -v "${seed_args[@]}"
    step 'Step 4: identify functions' "$PYTHON" -m tools.func_id "$XBE" -v
    step 'Step 4.5: recover calling conventions' "$PYTHON" -m tools.abi_analysis "$XBE" -v
    if [ -f tools/ghidra_naming/export/functions.json ]; then
        step 'Step 4.6: apply Ghidra names' "$PYTHON" tools/ghidra_naming/merge_names.py --apply
    fi
fi

# --exclude-manual / --manual-functions / --force-return: see tools/regen.ps1.
manual_args=()
[ -f "$PROJECT/config/manual_functions.json" ] &&
    manual_args+=(--manual-functions "$PROJECT/config/manual_functions.json")
if [ -f "$PROJECT/config/force_return.txt" ]; then
    while IFS= read -r line; do
        line=${line%%#*}
        line=$(echo "$line" | tr -d '[:space:]')
        [ -n "$line" ] && manual_args+=(--force-return "$line")
    done < "$PROJECT/config/force_return.txt"
fi
step 'Step 5: recompile' \
    "$PYTHON" -m tools.recomp "$XBE" --all --split 250 --game-name 'Amped 2' \
        --gen-dir "$GEN_DIR" \
        --exclude-manual "$PROJECT/src/recomp_manual.c" \
        "${manual_args[@]}" "${RECOMP_ARGS[@]}"

echo
echo "Generated code is in $GEN_DIR"
