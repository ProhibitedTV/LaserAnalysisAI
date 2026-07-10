"""PyInstaller-friendly GUI entrypoint for LaserLab."""

from __future__ import annotations

import sys

from gui.lab_dashboard import main


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        print("LaserLab GUI smoke OK")
        raise SystemExit(0)
    raise SystemExit(main())
