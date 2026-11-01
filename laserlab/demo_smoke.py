"""Offline packaged-demo qualification using only bundled public fixtures."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path


def smoke_bundled_demo() -> None:
    from . import app_api

    with tempfile.TemporaryDirectory(prefix="laserlab-offline-demo-") as temporary:
        payload = app_api.run_bundled_demo(Path(temporary) / "practice", max_frames=1)
        experiment = Path(payload["experiment_dir"])
        record = payload["run"]
        if record["review_state"]["unblinded"] or record.get("experiment_purpose") != "demo":
            raise RuntimeError("Packaged demo did not preserve blinded review")
        try:
            app_api.prepare_research_exchange(experiment)
        except ValueError:
            pass
        else:
            raise RuntimeError("Packaged exchange exposed a sealed review")
        app_api.complete_review(experiment)
        report = app_api.unblind_latest_run(experiment)
        if report["aggregate_statistics"]["evidence_ladder"] != "not tested" or report.get("experiment_purpose") != "demo":
            raise RuntimeError("Bundled demonstration was incorrectly treated as experimental evidence")
        app_api.export_review_bundle(experiment, Path(temporary) / "practice.zip")
        preview = app_api.prepare_research_exchange(experiment)
        output = Path(temporary) / "practice-exchange.json"
        app_api.export_research_exchange(experiment, output, expected_snapshot=preview["_snapshot_sha256"], privacy_acknowledged=True)
        exchange = json.loads(output.read_text(encoding="utf-8"))
        if (exchange["experiment_purpose"] != "practice_demo" or exchange["findings"]["evidence_level"] != "not tested"
                or exchange["findings"]["candidate_fdr"] is not None or exchange["privacy"]["source_hashes_included"]):
            raise RuntimeError("Packaged local exchange lost its practice or privacy boundary")
