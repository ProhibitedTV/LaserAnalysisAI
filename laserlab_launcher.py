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
        # A Windows PyInstaller --windowed executable has no console stderr or
        # stdout. Write a small deterministic diagnostic to the *test cwd* so
        # native release qualification can report actual Qt failure causes.
        import json
        report = {"schema_version": "1.0", "status": "failed", "variants": []}
        try:
            from PyQt5.QtWidgets import QApplication
            from laserlab.branding import BRAND_FONT_VARIANTS, load_brand_font
            from laserlab.font_qualification import inspect_font_resources
            app = QApplication.instance() or QApplication([])
            resources = inspect_font_resources()
            report["verified_variants"] = resources["verified_variants"]
            report["all_verified"] = resources["all_verified"]
            if not resources["all_verified"]:
                report["error"] = "At least one bundled font could not be verified"
            else:
                for variant, (_, _filename, expected_family) in BRAND_FONT_VARIANTS.items():
                    actual_family = load_brand_font(variant)
                    report["variants"].append({
                        "variant": variant, "expected_family": expected_family,
                        "registered_family": actual_family,
                    })
                report["status"] = (
                    "passed" if all(
                        item["expected_family"] == item["registered_family"]
                        for item in report["variants"]
                    ) else "failed"
                )
                if report["status"] != "passed":
                    report["error"] = "One or more Qt font-family registrations did not match"
        except Exception as exc:
            report["error"] = type(exc).__name__
            report["status"] = "failed"
        try:
            Path("laserlab-font-smoke.json").write_text(
                json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
            )
        except OSError:
            raise SystemExit(3)
        raise SystemExit(0 if report["status"] == "passed" else 2)
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
