#!/usr/bin/env bash
# package.sh - Pack the Linux release: RE-Amped2-<version>-linux.tar.gz in
# installer/dist, the counterpart of installer/build.ps1's payload.
#
#   tools/linux/package.sh [--xdvdfs PATH] [--unluac PATH]
#
# The tarball holds the working trees of amped2 (minus installer/, .claude/,
# screenshots/) and ../xboxrecomp (git-tracked plus untracked, not ignored,
# so never game/, mods/, generated code or build output), xdvdfs for Linux
# and unluac (downloaded and checked against their SHA-256 unless given), the
# icon as a PNG, manifest.txt with both repos' commits, and install.sh at the
# top. Uncommitted changes are included and marked +modified in the
# manifest; commit both repos first for a release. The version is the
# installer's (installer/Amped2Installer.csproj).
set -euo pipefail

XDVDFS=''
UNLUAC=''
while [ $# -gt 0 ]; do
    case "$1" in
        --xdvdfs) XDVDFS="$2"; shift 2 ;;
        --unluac) UNLUAC="$2"; shift 2 ;;
        *) echo "package.sh: unknown argument $1" >&2; exit 2 ;;
    esac
done

PROJECT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TOOLKIT=$(cd "$PROJECT/../xboxrecomp" && pwd)
VERSION=$(sed -n 's:.*<Version>\(.*\)</Version>.*:\1:p' "$PROJECT/installer/Amped2Installer.csproj" | head -1)
[ -n "$VERSION" ] || { echo "No <Version> in Amped2Installer.csproj" >&2; exit 1; }
NAME="RE-Amped2-$VERSION-linux"
OUT="$PROJECT/installer/dist"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/$NAME"
mkdir -p "$ROOT/tools" "$OUT"

# xdvdfs 0.8.3 (MIT), the Linux build from its GitHub release; the same
# version installer/fetch-tools.ps1 takes for Windows.
XDVDFS_URL=https://github.com/antangelo/xdvdfs/releases/download/v0.8.3/xdvdfs-linux-1cc850bf1b3487fad7ec7c9eed01d83e8fc75ba4.zip
XDVDFS_ZIP_SHA=f96a07359b56ceb580632437b8334633b7a8f1a931bc81b18c33cd745df2c708
XDVDFS_SHA=ba860c079d756451e6396824e9866724d9765d4cabd1ecee148e53d18350a2e8
if [ -z "$XDVDFS" ]; then
    curl -fsSL -o "$STAGE/xdvdfs.zip" "$XDVDFS_URL"
    echo "$XDVDFS_ZIP_SHA  $STAGE/xdvdfs.zip" | sha256sum -c --quiet
    python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extract("xdvdfs", sys.argv[2])' \
        "$STAGE/xdvdfs.zip" "$STAGE"
    XDVDFS="$STAGE/xdvdfs"
fi
echo "$XDVDFS_SHA  $XDVDFS" | sha256sum -c --quiet ||
    { echo "$XDVDFS is not the expected xdvdfs 0.8.3 build" >&2; exit 1; }
install -m 755 "$XDVDFS" "$ROOT/tools/xdvdfs"

# Tracked plus untracked-but-not-ignored files of a repo, minus some folders.
copy_tree() {
    local src="$1" dst="$2" s; shift 2
    mkdir -p "$dst"
    # --ignore-failed-read: files deleted but not committed yet.
    git -C "$src" ls-files -z --cached --others --exclude-standard |
        (cd "$src" && tar --null --ignore-failed-read -T - -cf - 2>/dev/null) |
        tar -C "$dst" -xf -
    for s in "$@"; do rm -rf "${dst:?}/$s"; done
    # A Windows checkout has CRLF; shell scripts must be LF.
    find "$dst" -name '*.sh' -exec sed -i 's/\r$//' {} + -exec chmod 755 {} +
}
copy_tree "$PROJECT" "$ROOT/amped2" installer .claude screenshots
copy_tree "$TOOLKIT" "$ROOT/xboxrecomp"

# unluac 2025-12-23 (MIT), for the menu mod; the build installer/fetch-tools
# .ps1 takes, where build.ps1's payload puts it.
UNLUAC_URL=https://downloads.sourceforge.net/project/unluac/Unstable/unluac_2025_12_23.jar
UNLUAC_SHA=98be0fa84ac73ca66dce2842a2e4512226f4c611b6500dc96415571fc5538fcc
if [ -z "$UNLUAC" ]; then
    curl -fsSL -o "$STAGE/unluac.jar" "$UNLUAC_URL"
    UNLUAC="$STAGE/unluac.jar"
fi
echo "$UNLUAC_SHA  $UNLUAC" | sha256sum -c --quiet ||
    { echo "$UNLUAC is not the expected unluac build" >&2; exit 1; }
mkdir -p "$ROOT/amped2/tools/bin"
install -m 644 "$UNLUAC" "$ROOT/amped2/tools/bin/unluac.jar"

describe() {
    local c; c=$(git -C "$1" rev-parse HEAD)
    # autocrlf as the Windows checkout has it, or every file reads as changed.
    [ -n "$(git -C "$1" -c core.autocrlf=true status --porcelain --untracked-files=no)" ] &&
        c="$c+modified"
    echo "$c"
}
{
    echo "RE-Amped2 $VERSION for Linux"
    echo "amped2     $(describe "$PROJECT")"
    echo "xboxrecomp $(describe "$TOOLKIT")"
    echo "xdvdfs     0.8.3"
    echo "unluac     2025-12-23"
} > "$ROOT/manifest.txt"

# The icon's largest image, for the applications menu (Vista-style ICOs keep
# it as a PNG).
python3 - "$PROJECT/branding/RE-Amped2.ico" "$ROOT/RE-Amped2.png" <<'EOF'
import struct, sys
data = open(sys.argv[1], 'rb').read()
best = None
for i in range(struct.unpack_from('<H', data, 4)[0]):
    w, h, _, _, _, _, size, off = struct.unpack_from('<BBBBHHII', data, 6 + 16 * i)
    w = w or 256
    if data[off:off + 8] == b'\x89PNG\r\n\x1a\n' and (best is None or w > best[0]):
        best = (w, data[off:off + size])
if best:
    open(sys.argv[2], 'wb').write(best[1])
else:
    print('no PNG image in the icon; the menu entry will have none')
EOF

cat > "$ROOT/install.sh" <<'EOF'
#!/usr/bin/env bash
# Builds RE-Amped2 from your own Amped 2 disc image:
#   ./install.sh DISC.iso [INSTALL_DIR]      (default ~/Games/RE-Amped2)
exec bash "$(dirname "$(readlink -f "$0")")/amped2/tools/linux/install.sh" "$@"
EOF
chmod 755 "$ROOT/install.sh"
cat > "$ROOT/INSTALL.txt" <<EOF
RE-Amped2 $VERSION for Linux (early access)

This download holds no game code or data. install.sh builds the game on
this PC from your own Amped 2 disc image (USA or Europe/Australia):

  ./install.sh "Amped 2.iso"                  (installs to ~/Games/RE-Amped2)
  ./install.sh "Amped 2.iso" ~/somewhere/else

It needs a C compiler, CMake, Ninja, pkg-config, Python 3 with venv and the
SDL2, libepoxy and OpenSSL headers, plus Java for the RE-Amped2 menus, and
offers to install what is missing (apt, pacman or dnf). It downloads three
Python packages (capstone; numpy and pillow for the menus). The build
takes 10-30 minutes and about 4 GB of disk while it runs.

Saves in INSTALL_DIR/game/UDATA are kept when you install again.
EOF

tar -C "$STAGE" -czf "$OUT/$NAME.tar.gz" "$NAME"
(cd "$OUT" && sha256sum "$NAME.tar.gz" | tee "$NAME.tar.gz.sha256")
echo "$OUT/$NAME.tar.gz: $(du -h "$OUT/$NAME.tar.gz" | cut -f1)"
