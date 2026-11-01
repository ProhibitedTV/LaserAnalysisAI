"""Offline packaged-demo qualification using only bundled public fixtures."""
from __future__ import annotations

import tempfile
from pathlib import Path


def smoke_bundled_demo() -> None:
    from . import app_api
    from .fixtures import fixture_metadata
    from .runtime import resource_path

    with tempfile.TemporaryDirectory(prefix="laserlab-offline-demo-") as temporary:
        experiment = Path(temporary) / "practice"
        for filename, fixture, role in (
            ("commons-young-double-slit.ogv", "commons-young-double-slit", "laser"),
            ("commons-double-slit-experiment.webm", "commons-double-slit-experiment", "control"),
        ):
            app_api.add_capture(experiment, resource_path("sample_media", filename), "video", role,
                                all_frames=True, max_frames=1, capture_metadata=fixture_metadata(fixture))
        record = app_api.run_analysis(experiment, profile="baseline", blind_seed=5301, control_generation="none")
        if record["review_state"]["unblinded"]:
            raise RuntimeError("Packaged demo did not preserve blinded review")
        app_api.complete_review(experiment)
        report = app_api.unblind_latest_run(experiment)
        if report["aggregate_statistics"]["evidence_ladder"] != "not tested":
            raise RuntimeError("Bundled demonstration was incorrectly treated as experimental evidence")
        app_api.export_review_bundle(experiment, Path(temporary) / "practice.zip")
