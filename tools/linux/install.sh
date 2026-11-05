#!/usr/bin/env bash
# install.sh - Build RE-Amped2 on this Linux PC from the player's own Amped 2
# disc image. The Linux counterpart of RE-Amped2-Setup.exe
# (installer/README.md): the release tarball carries this project's sources,
# the xboxrecomp toolkit and xdvdfs, and no game code or data.
#
#   ./install.sh DISC.iso [INSTALL_DIR]      (default ~/Games/RE-Amped2)
#
#   --no-menu-entry   don't add RE-Amped2 to the applications menu
#   --no-look         leave out the RE-Amped2 look (logo, splash, loading
#                     screen); an update removes it
#   --no-menus        leave out the RE-Amped2 menus (the menu mod, which
#                     needs Java); an update removes them
#   --hd-movies       set up HD copies of the movies: FFmpeg (the system's
#                     package) and INSTALL_DIR/convert-hd-movies.sh, which
#                     makes them (about an hour and 6.5 GB; run it after
#                     the install). The game decodes them with FFmpeg too.
#   --keep-temp       keep INSTALL_DIR/_install_temp (sources and build)
#
# Stages as on Windows: build tools, disc, recompiler, translate, compile,
# menu mod, finish (with the look). Saves in INSTALL_DIR/game/UDATA survive a reinstall. The work
# happens in INSTALL_DIR/_install_temp; the full log is INSTALL_DIR/install.log.
#
# On an image-based system (Bazzite, Silverblue, Kinoite: /usr is read-only)
# the build tools go in a Distrobox container instead: install.sh offers to
# create one ("re-amped2", Fedora of the host's release) and runs itself
# again inside it. The container shares the home folder, display, GPU and
# sound, and the game starts through it (RE-Amped2.sh).
set -euo pipefail

TITLE_ID=4D530041
BOX=re-amped2
# Set inside a Distrobox container (its name): the game then starts through it.
IN_BOX="${CONTAINER_ID:-}"

MENU_ENTRY=1
LOOK=1
MENUS=1
HD_MOVIES=0
KEEP_TEMP=0
ARGS=()
OPTS=()
for a in "$@"; do
    case "$a" in
        --no-menu-entry) MENU_ENTRY=0; OPTS+=("$a") ;;
        --no-look) LOOK=0; OPTS+=("$a") ;;
        --no-menus) MENUS=0; OPTS+=("$a") ;;
        --hd-movies) HD_MOVIES=1; OPTS+=("$a") ;;
        --keep-temp) KEEP_TEMP=1; OPTS+=("$a") ;;
        -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
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
# HD movies: FFmpeg converts them and decodes them while the game runs.
if [ "$HD_MOVIES" = 1 ]; then
    command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || missing+=(ffmpeg)
fi
if [ ${#missing[@]} -gt 0 ] && [ -e /run/ostree-booted ] && [ -z "$IN_BOX" ]; then
    # Image-based host: build in a Distrobox container of the same Fedora
    # release, which sees the host's / at /run/host.
    . /etc/os-release 2>/dev/null || true
    say "Missing: ${missing[*]}"
    say "${NAME:-This system} is image-based: build tools are not installed on the system itself,"
    say "but in a container. The installer can create a Distrobox container \"$BOX\" and build there;"
    say "the game then starts through it."
    command -v distrobox >/dev/null ||
        fail "Distrobox is not installed. Install it (or create a Fedora toolbox), enter it and run this again inside it."
    case "$DEST" in
        "$HOME"/*) ;;
        *) fail "with a container, install into a folder in your home directory (it is shared with the container)." ;;
    esac
    tag=latest
    [[ "${VERSION_ID:-}" =~ ^[0-9]+$ ]] && tag="$VERSION_ID"
    image="registry.fedoraproject.org/fedora-toolbox:$tag"
    [ -t 0 ] || fail "run this in a terminal to set up the container."
    read -r -p "Create the container ($image, about 1 GB download) and continue there? [y/N] " yn
    [[ "$yn" =~ ^[Yy] ]] || fail "the build tools are missing; set up a container with them and run this again inside it."
    if ! distrobox list 2>/dev/null | awk -F'|' -v n="$BOX" 'NR > 1 { gsub(/ /, "", $2); if ($2 == n) f = 1 } END { exit !f }'; then
        nvidia=(); command -v nvidia-smi >/dev/null && nvidia=(--nvidia)
        distrobox create --yes --name "$BOX" --image "$image" "${nvidia[@]}" 2>&1 | tee -a "$LOG" ||
            fail "Distrobox could not create the container."
    fi
    host() { case "$1" in "$HOME"/*) printf '%s' "$1" ;; *) printf '/run/host%s' "$1" ;; esac; }
    say "Continuing inside the container (its first start sets it up, which takes a few minutes)."
    exec distrobox enter "$BOX" -- bash "$(host "$(readlink -f "${BASH_SOURCE[0]}")")" \
        "${OPTS[@]}" "$(host "$DISC")" "$DEST"
fi
if [ ${#missing[@]} -gt 0 ]; then
    . /etc/os-release 2>/dev/null || true
    case " ${ID:-} ${ID_LIKE:-} " in
        *" debian "*|*" ubuntu "*) cmd="sudo apt-get install -y build-essential cmake ninja-build pkg-config python3-venv libsdl2-dev libepoxy-dev libgl1-mesa-dev libssl-dev" ;;
        *" arch "*) cmd="sudo pacman -S --needed base-devel cmake ninja python sdl2 libepoxy openssl" ;;
        *" fedora "*|*" rhel "*) cmd="sudo dnf install -y gcc make cmake ninja-build pkgconf python3 SDL2-devel libepoxy-devel mesa-libGL-devel openssl-devel" ;;
        *) cmd="" ;;
    esac
    # Fedora's FFmpeg is ffmpeg-free; its H.264 comes from Cisco's openh264.
    if [ -n "$cmd" ] && [ "$HD_MOVIES" = 1 ]; then
        case "$cmd" in
            *dnf*) cmd="$cmd ffmpeg-free openh264" ;;
            *) cmd="$cmd ffmpeg" ;;
        esac
    fi
    # A bare container image lacks what SDL loads at run time on a desktop
    # host: the sound server's and the window system's client libraries.
    if [ -n "$IN_BOX" ] && [[ "$cmd" == *dnf* ]]; then
        cmd="$cmd mesa-dri-drivers pipewire-libs pulseaudio-libs alsa-lib libdecor libxkbcommon libXcursor libXi libXrandr libXScrnSaver libwayland-client libwayland-egl libwayland-cursor"
    fi
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
# Java only for the RE-Amped2 menus (unluac decompiles the game's Lua), so
# without it the game is built and the menus are left out.
if [ "$MENUS" = 1 ] && ! command -v java >/dev/null; then
    . /etc/os-release 2>/dev/null || true
    case " ${ID:-} ${ID_LIKE:-} " in
        *" debian "*|*" ubuntu "*) jcmd="sudo apt-get install -y default-jre-headless" ;;
        *" arch "*) jcmd="sudo pacman -S --needed jre-openjdk-headless" ;;
        # java-21 is gone from Fedora 44; any Java runs unluac.
        *" fedora "*|*" rhel "*) jcmd="sudo dnf install -y java-latest-openjdk-headless" ;;
        *) jcmd="" ;;
    esac
    say "The RE-Amped2 menus need Java, which is not installed."
    if [ -n "$jcmd" ] && [ -t 0 ]; then
        say "  $jcmd"
        read -r -p "Install it now (asks for your password)? [y/N] " yn
        if [[ "$yn" =~ ^[Yy] ]]; then $jcmd 2>&1 | tee -a "$LOG" || true; fi
    fi
    if ! command -v java >/dev/null; then
        MENUS=0
        say "Leaving the RE-Amped2 menus out; install Java and run this again to add them."
    fi
fi

# ── Disc ──────────────────────────────────────────────────────────────
stage "Disc"
[ -x "$XDVDFS" ] || fail "xdvdfs is missing from the download ($PAYLOAD/tools/xdvdfs)."
logged "$XDVDFS" ls "$DISC" || fail "$DISC is not an Xbox disc image xdvdfs can read."
# xdvdfs will not unpack over existing files (EEXIST on Linux), so a
# reinstall unpacks beside game/ and moves each file over its old copy.
# game/UDATA (saves) and whatever else the game wrote are not on the disc
# and stay.
DISC_TMP="$DEST/_install_disc"
rm -rf "$DISC_TMP"
logged "$XDVDFS" unpack "$DISC" "$DISC_TMP" || fail "the disc could not be extracted."
mkdir -p "$DEST/game"
(cd "$DISC_TMP" && find . -type f -print0) | while IFS= read -r -d '' f; do
    mkdir -p "$DEST/game/$(dirname "$f")"
    mv -f "$DISC_TMP/$f" "$DEST/game/$f"
done
rm -rf "$DISC_TMP"
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

# ── Menu mod ──────────────────────────────────────────────────────────
# tools/mods/menus.py edits the player's own GUI archives into
# mods/build/game, which the game reads over game/. A failure here only
# leaves the menus out, as on Windows.
MENUS_OK=0
rm -rf "$DEST/mods/build/game"
if [ "$MENUS" = 1 ]; then
    stage "RE-Amped2 menus"
    if logged "$WORK/venv/bin/pip" install --disable-pip-version-check numpy pillow &&
            (cd "$WORK/src/amped2" && logged "$WORK/venv/bin/python" tools/mods/menus.py) &&
            [ -d "$WORK/src/amped2/mods/build/game" ]; then
        mkdir -p "$DEST/mods/build"
        cp -r "$WORK/src/amped2/mods/build/game" "$DEST/mods/build/"
        MENUS_OK=1
        say "Added the RE-Amped2 menus (mods/build/game)."
    else
        say "The RE-Amped2 menus could not be built and are left out (details in $LOG)."
    fi
fi

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
lic amped2/licenses/unluac-LICENSE.txt unluac-LICENSE.txt
# The RE-Amped2 look, as the Windows installer adds it: branding/pack's
# textures (RE-Amped2 art only, keyed by the originals' hashes) as the mod
# pack mods/packs/re-amped2, first in mods/mods.json; other packs are kept.
# The loading screen's controller pictures go only with their labels, which
# the menu mod blanks (menu-mod-only.txt).
rm -rf "$DEST/mods/packs/re-amped2"
if [ "$LOOK" = 1 ]; then
    mkdir -p "$DEST/mods/packs/re-amped2"
    cp -r "$PAYLOAD/amped2/branding/pack/textures" "$DEST/mods/packs/re-amped2/"
    only="$PAYLOAD/amped2/branding/pack/menu-mod-only.txt"
    if [ "$MENUS_OK" = 0 ] && [ -f "$only" ]; then
        while IFS= read -r key; do
            key=$(echo "$key" | tr -d '[:space:]')
            if [ -n "$key" ]; then rm -f "$DEST/mods/packs/re-amped2/textures/$key.dds"; fi
        done < "$only"
    fi
fi
mkdir -p "$DEST/mods"
python3 - "$DEST/mods/mods.json" "$LOOK" <<'EOF' || say "Could not update mods/mods.json; the look may not show."
import os, re, sys
path, look = sys.argv[1], sys.argv[2] == '1'
old = open(path).read() if os.path.exists(path) else ''
packs = [p for p in re.findall(r'"([^"]+)"', old) if p not in ('packs', 're-amped2')]
if look:
    packs.insert(0, 're-amped2')
open(path, 'w').write('{ "packs": [' + ', '.join('"%s"' % p for p in packs) + '] }\n')
EOF
if [ "$LOOK" = 1 ]; then say "Added the RE-Amped2 look (mods/packs/re-amped2)."; fi
{
    echo "Installed $(date -u '+%Y-%m-%d %H:%M UTC') from $DISC"
    [ -f "$PAYLOAD/manifest.txt" ] && cat "$PAYLOAD/manifest.txt"
} > "$DEST/install-info.txt"
# Built in a container: the game needs its libraries, so it starts through it.
RUN="$DEST/RE-Amped2"
rm -f "$DEST/RE-Amped2.sh"
if [ -n "$IN_BOX" ]; then
    RUN="$DEST/RE-Amped2.sh"
    cat > "$RUN" <<EOF
#!/bin/sh
# Starts RE-Amped2 in the Distrobox container "$IN_BOX" it was built in, which
# has the libraries it needs.
cd "\$(dirname "\$(readlink -f "\$0")")" || exit 1
[ -n "\${CONTAINER_ID:-}" ] && exec ./RE-Amped2 "\$@"
exec distrobox-enter -n "$IN_BOX" -- "\$PWD/RE-Amped2" "\$@"
EOF
    chmod 755 "$RUN"
fi
if [ "$MENU_ENTRY" = 1 ]; then
    apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$apps"
    cat > "$apps/re-amped2.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=RE-Amped2
Comment=Amped 2, recompiled for PC
Exec="$RUN"
Path=$DEST
Icon=$DEST/RE-Amped2.png
Terminal=false
Categories=Game;
EOF
    say "Added RE-Amped2 to the applications menu."
fi

# HD movies: the recipe (tools/mods/movie_pack.py, standard library only)
# and a script that runs it, through the container if the game runs in one.
rm -f "$DEST/convert-hd-movies.sh"
if [ "$HD_MOVIES" = 1 ]; then
    mkdir -p "$DEST/tools/mods"
    install -m 644 "$WORK/src/amped2/tools/mods/movie_pack.py" "$DEST/tools/mods/movie_pack.py"
    cat > "$DEST/convert-hd-movies.sh" <<EOF
#!/bin/sh
# RE-Amped2: converts the game's movies to HD copies in mods/movie_pack.
# Finished movies are skipped, so running this again carries on where it
# stopped. Each movie is used in the game as soon as it is done.
cd "\$(dirname "\$(readlink -f "\$0")")" || exit 1
EOF
    if [ -n "$IN_BOX" ]; then
        cat >> "$DEST/convert-hd-movies.sh" <<EOF
[ -n "\${CONTAINER_ID:-}" ] || exec distrobox-enter -n "$IN_BOX" -- "\$PWD/convert-hd-movies.sh" "\$@"
EOF
    fi
    cat >> "$DEST/convert-hd-movies.sh" <<'EOF'
exec nice python3 -I tools/mods/movie_pack.py "$@"
EOF
    chmod 755 "$DEST/convert-hd-movies.sh"
fi

say
say "Done. Start the game with $RUN"
if [ "$HD_MOVIES" = 1 ]; then
    say "For the HD movies, run $DEST/convert-hd-movies.sh (about an hour; the game can run meanwhile)."
fi
say "Your saves are in $DEST/game/UDATA; README.txt there has the controls."
