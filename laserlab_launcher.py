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
    if "--smoke-demo" in sys.argv:
        from laserlab.demo_smoke import smoke_bundled_demo
        smoke_bundled_demo()
        print("LaserLab offline bundled demo smoke OK")
        raise SystemExit(0)
    if "--smoke" in sys.argv:
        raise SystemExit(main(smoke=True))
    if "--smoke-fonts" in sys.argv:
        from PyQt5.QtWidgets import QApplication
        from laserlab.branding import BRAND_FONT_VARIANTS, load_brand_font
        from laserlab.font_qualification import inspect_font_resources

        app = QApplication.instance() or QApplication([])
        result = inspect_font_resources()
        if not result["all_verified"] or result["verified_variants"] != len(BRAND_FONT_VARIANTS):
            raise SystemExit("Packaged CodeOfReality fonts are absent or fail verification")
        for variant, (_, _filename, expected_family) in BRAND_FONT_VARIANTS.items():
            actual_family = load_brand_font(variant)
            if actual_family != expected_family:
                raise SystemExit(f"CodeOfReality Qt family mismatch: {variant}")
        print(f"LaserLab GUI font smoke OK / variants={len(BRAND_FONT_VARIANTS)}")
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
