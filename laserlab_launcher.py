"""PyInstaller-friendly GUI entrypoint for LaserLab."""

from __future__ import annotations

import sys
from pathlib import Path

from laserlab.diagnostics import configure_logging

try:
    configure_logging()
except OSError:
    pass

from gui.lab_dashboard import main
from laserlab.runtime import default_experiments_dir, resource_path


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        print("LaserLab GUI smoke OK")
        raise SystemExit(0)
    if "--smoke-resources" in sys.argv:
        fixture_names = (
            "commons-double-slit-experiment.webm",
            "commons-focused-laguerre-gaussian.webm",
            "commons-two-pinhole-laser-interference.webm",
            "commons-young-double-slit.ogv",
        )
        missing = [name for name in fixture_names if not resource_path("sample_media", name).is_file()]
        if missing:
            raise SystemExit("Missing bundled fixtures: " + ", ".join(missing))
        workspace = default_experiments_dir().resolve()
        install_dir = Path(sys.executable).resolve().parent
        if bool(getattr(sys, "frozen", False)) and (workspace == install_dir or install_dir in workspace.parents):
            raise SystemExit("Frozen experiment workspace resolves inside the install directory")
        print(f"LaserLab resource smoke OK / fixtures={len(fixture_names)} / workspace={workspace}")
        raise SystemExit(0)
    raise SystemExit(main())
