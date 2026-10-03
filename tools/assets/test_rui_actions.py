"""rui_actions round-trips every .actions file in game/GuiPackages byte for byte.

    python tools/assets/test_rui_actions.py
"""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rui_actions  # noqa: E402

GAME = Path(__file__).resolve().parents[2] / "game"


def main():
    n = bad = 0
    for rui in sorted((GAME / "GuiPackages").glob("*.rui")):
        z = zipfile.ZipFile(rui)
        for name in z.namelist():
            if not name.lower().endswith(".actions"):
                continue
            data = z.read(name)
            n += 1
            try:
                ok = rui_actions.write(rui_actions.read(data)) == data
            except Exception as e:  # noqa: BLE001
                ok, data = False, repr(e)
            if not ok:
                bad += 1
                print("MISMATCH", rui.name, name, data if isinstance(data, str) else "")
    print(f"{n} .actions files, {bad} mismatched")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
