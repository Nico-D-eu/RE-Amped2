#!/usr/bin/env bash
# install.sh - Build RE-Amped2 on this Linux PC from the player's own Amped 2
# disc image. The Linux counterpart of RE-Amped2-Setup.exe
# (installer/README.md): the release tarball carries this project's sources,
# the xboxrecomp toolkit and xdvdfs, and no game code or data.
#
#   ./install.sh DISC.iso [INSTALL_DIR]      (default ~/Games/RE-Amped2)
#
#   --no-menu-entry   don't add RE-Amped2 to the applications menu
#   --keep-temp       keep INSTALL_DIR/_install_temp (sources and build)
#
# Stages as on Windows: build tools, disc, recompiler, translate, compile,
# finish. Saves in INSTALL_DIR/game/UDATA survive a reinstall. The work
# happens in INSTALL_DIR/_install_temp; the full log is INSTALL_DIR/install.log.
set -euo pipefail

TITLE_ID=4D530041

MENU_ENTRY=1
KEEP_TEMP=0
ARGS=()
for a in "$@"; do
    case "$a" in
        --no-menu-entry) MENU_ENTRY=0 ;;
        --keep-temp) KEEP_TEMP=1 ;;
        -h|--help) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "install.sh: unknown option $a" >&2; exit 2 ;;
        *) ARGS+=("$a") ;;
    esac
done
[ ${#ARGS[@]} -ge 1 ] && [ ${#ARGS[@]} -le 2 ] || {
    echo "usage: ./install.sh DISC.iso [INSTALL_DIR]" >&2; exit 2; }

DISC=$(realpath -e "${ARGS[0]}") || { echo "No disc image at ${ARGS[0]}" >&2; exit 1; }
DEST=$(realpath -m "${ARGS[1]:-$HOME/Games/RE-Amped2}")
# The payload: amped2/ and xboxrecomp/ side by side, xdvdfs in tools/.
PAYLOAD=$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)
XDVDFS="$PAYLOAD/tools/xdvdfs"
if [ ! -x "$XDVDFS" ] && command -v xdvdfs >/dev/null; then
    XDVDFS=$(command -v xdvdfs)
fi

case "$DEST" in
    /|/usr|/usr/*|/opt|/etc|/etc/*|/bin|/bin/*|/sbin|/sbin/*|/lib*)
        echo "Pick a folder in your home directory: the game writes its saves and" >&2
        echo "amped2.ini beside itself." >&2
        exit 1 ;;
esac
mkdir -p "$DEST"
LOG="$DEST/install.log"
: > "$LOG"
WORK="$DEST/_install_temp"

say()  { echo "$*" | tee -a "$LOG"; }
stage() { say; say "== $* =="; }
fail() { say; say "FAILED: $*"; say "The full log is $LOG"; exit 1; }
# Runs a command with its output in the log and a dot per 50 lines on screen.
logged() {
    echo "\$ $*" >> "$LOG"
    local rc=0
    # pipefail makes the pipeline fail when the command does.
    "$@" 2>&1 | tee -a "$LOG" | awk 'NR % 50 == 0 { printf "."; fflush() } END { if (NR >= 50) print "" }' ||
        rc=$?
    [ "$rc" = 0 ]
}

cleanup() {
    [ "$KEEP_TEMP" = 1 ] && return
    # The junction first, so the delete can never reach game/.
    [ -L "$WORK/src/amped2/game" ] && rm -f "$WORK/src/amped2/game"
    [ -e "$WORK/src/amped2/game" ] && { say "Left $WORK in place: its game link is not a link."; return; }
    rm -rf "$WORK"
}
trap cleanup EXIT

say "RE-Amped2 for Linux: building from $DISC into $DEST"

# ── Build tools ───────────────────────────────────────────────────────
stage "Build tools"
missing=()
for c in cc cmake pkg-config python3; do
    command -v "$c" >/dev/null || missing+=("$c")
done
command -v ninja >/dev/null || command -v make >/dev/null || missing+=(ninja)
python3 -c 'import venv, ensurepip' 2>/dev/null || missing+=(python3-venv)
for m in sdl2 epoxy openssl; do
    pkg-config --exists "$m" 2>/dev/null || missing+=("$m")
done
if [ ${#missing[@]} -gt 0 ]; then
    . /etc/os-release 2>/dev/null || true
    case " ${ID:-} ${ID_LIKE:-} " in
        *" debian "*|*" ubuntu "*) cmd="sudo apt-get install -y build-essential cmake ninja-build pkg-config python3-venv libsdl2-dev libepoxy-dev libgl1-mesa-dev libssl-dev" ;;
        *" arch "*) cmd="sudo pacman -S --needed base-devel cmake ninja python sdl2 libepoxy openssl" ;;
        *" fedora "*|*" rhel "*) cmd="sudo dnf install -y gcc make cmake ninja-build pkgconf python3 SDL2-devel libepoxy-devel mesa-libGL-devel openssl-devel" ;;
        *) cmd="" ;;
    esac
    say "Missing: ${missing[*]}"
    if [ -z "$cmd" ]; then
        fail "install a C compiler, CMake, Ninja, pkg-config, Python 3 with venv, and the SDL2, libepoxy and OpenSSL headers, then run this again."
    fi
    say "These packages provide them:"
    say "  $cmd"
    if [ -t 0 ]; then
        read -r -p "Install them now (asks for your password)? [y/N] " yn
        [[ "$yn" =~ ^[Yy] ]] || fail "the build tools are missing; install them and run this again."
        $cmd 2>&1 | tee -a "$LOG" || fail "the package install did not finish."
    else
        fail "the build tools are missing; install them and run this again."
    fi
fi
say "Compiler: $(cc --version | head -1)"
say "CMake:    $(cmake --version | head -1)"

# ── Disc ──────────────────────────────────────────────────────────────
stage "Disc"
[ -x "$XDVDFS" ] || fail "xdvdfs is missing from the download ($PAYLOAD/tools/xdvdfs)."
logged "$XDVDFS" ls "$DISC" || fail "$DISC is not an Xbox disc image xdvdfs can read."
# Existing files are overwritten; game/UDATA (saves) is not on the disc.
logged "$XDVDFS" unpack "$DISC" "$DEST/game" || fail "the disc could not be extracted."
python3 - "$DEST/game/default.xbe" "$TITLE_ID" <<'EOF' || fail "this is not an Amped 2 disc (USA or Europe/Australia)."
import struct, sys
data = open(sys.argv[1], 'rb').read()
base, cert = struct.unpack_from('<I', data, 0x104)[0], struct.unpack_from('<I', data, 0x118)[0]
tid = struct.unpack_from('<I', data, cert - base + 8)[0]
print('Title ID %08X' % tid)
sys.exit(0 if tid == int(sys.argv[2], 16) else 1)
EOF

# ── Recompiler ────────────────────────────────────────────────────────
stage "Recompiler"
rm -rf "$WORK"
mkdir -p "$WORK/src"
cp -a "$PAYLOAD/amped2" "$PAYLOAD/xboxrecomp" "$WORK/src/"
ln -s "$DEST/game" "$WORK/src/amped2/game"
logged python3 -m venv "$WORK/venv" || fail "Python could not create a virtual environment."
logged "$WORK/venv/bin/pip" install --disable-pip-version-check 'capstone>=5,<6' ||
    fail "pip could not install capstone (needs the internet)."

# ── Translate ─────────────────────────────────────────────────────────
stage "Translate (a few minutes)"
logged bash "$WORK/src/amped2/tools/linux/regen.sh" --python "$WORK/venv/bin/python" ||
    fail "the recompiler stopped."

# ── Compile ───────────────────────────────────────────────────────────
stage "Compile (10-30 minutes)"
cores=$(nproc 2>/dev/null || echo 2)
mem_gb=$(awk '/MemTotal/ { print int($2 / 1048576) }' /proc/meminfo 2>/dev/null || echo 6)
jobs=$(( cores < mem_gb / 3 ? cores : mem_gb / 3 ))
[ "$jobs" -lt 2 ] && jobs=2
[ "$jobs" -gt 8 ] && jobs=8
gen=(); command -v ninja >/dev/null && gen=(-G Ninja)
say "$cores cores, $mem_gb GB: $jobs jobs"
logged cmake -S "$WORK/src/amped2" -B "$WORK/build" "${gen[@]}" -DCMAKE_BUILD_TYPE=Release ||
    fail "CMake could not configure the build."
logged cmake --build "$WORK/build" --parallel "$jobs" || fail "the compile stopped."

# ── Finish ────────────────────────────────────────────────────────────
stage "Finish"
install -m 755 "$WORK/build/RE-Amped2" "$DEST/RE-Amped2"
install -m 644 "$PAYLOAD/amped2/tools/linux/README.txt" "$DEST/README.txt"
[ -f "$PAYLOAD/RE-Amped2.png" ] && install -m 644 "$PAYLOAD/RE-Amped2.png" "$DEST/RE-Amped2.png"
mkdir -p "$DEST/licenses"
lic() { [ -f "$PAYLOAD/$1" ] && install -m 644 "$PAYLOAD/$1" "$DEST/licenses/$2"; true; }
lic amped2/LICENSE RE-Amped2-LICENSE.txt
lic amped2/NOTICE.md RE-Amped2-NOTICE.txt
lic xboxrecomp/LICENSE xboxrecomp-LICENSE.txt
lic xboxrecomp/NOTICE xboxrecomp-NOTICE.txt
lic xboxrecomp/LICENSES/LGPL-2.1.txt LGPL-2.1.txt
lic amped2/licenses/xdvdfs-LICENSE.txt xdvdfs-LICENSE.txt
{
    echo "Installed $(date -u '+%Y-%m-%d %H:%M UTC') from $DISC"
    [ -f "$PAYLOAD/manifest.txt" ] && cat "$PAYLOAD/manifest.txt"
} > "$DEST/install-info.txt"
if [ "$MENU_ENTRY" = 1 ]; then
    apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$apps"
    cat > "$apps/re-amped2.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=RE-Amped2
Comment=Amped 2, recompiled for PC
Exec="$DEST/RE-Amped2"
Path=$DEST
Icon=$DEST/RE-Amped2.png
Terminal=false
Categories=Game;
EOF
    say "Added RE-Amped2 to the applications menu."
fi

say
say "Done. Start the game with $DEST/RE-Amped2"
say "Your saves are in $DEST/game/UDATA; README.txt there has the controls."
