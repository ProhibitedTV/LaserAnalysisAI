"""Run the bundled fixture demo through the GUI-safe app API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from laserlab import app_api


LASER_FIXTURE = ROOT / "sample_media" / "commons-young-double-slit.ogv"
CONTROL_FIXTURE = ROOT / "sample_media" / "commons-double-slit-experiment.webm"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LaserLab fixture demo.")
    parser.add_argument("--experiment", default="experiments/release-demo")
    parser.add_argument("--max-frames", type=int, default=12)
    parser.add_argument("--profile", default="wide", choices=["baseline", "wide"])
    parser.add_argument("--blind-seed", type=int, default=20260710)
    parser.add_argument("--dump-dir", default="release_dumps")
    args = parser.parse_args()

    experiment_dir = Path(args.experiment)
    manifest = app_api.create_experiment(experiment_dir)
    labels = {capture.get("label") for capture in manifest.get("captures", [])}
    if "laser" not in labels:
        app_api.add_capture(
            experiment_dir,
            LASER_FIXTURE,
            "video",
            "laser",
            all_frames=True,
            max_frames=args.max_frames,
        )
    if "control" not in labels:
        app_api.add_capture(
            experiment_dir,
            CONTROL_FIXTURE,
            "video",
            "control",
            all_frames=True,
            max_frames=args.max_frames,
        )

    run_record = app_api.run_analysis(experiment_dir, profile=args.profile, blind_seed=args.blind_seed)
    report = app_api.load_latest_report(experiment_dir)

    dump_dir = Path(args.dump_dir)
    dump_dir.mkdir(parents=True, exist_ok=True)
    summary_path = dump_dir / "release-demo-summary.json"
    candidates_path = dump_dir / "release-demo-top-candidates.csv"
    summary = {
        "experiment": str(experiment_dir),
        "run_id": run_record["run_id"],
        "profile": run_record["profile"],
        "blind_seed": run_record["blind_seed"],
        "sample_count": len(run_record.get("samples", [])),
        "result_count": len(run_record.get("results", [])),
        "aggregate_statistics": run_record["aggregate_statistics"],
        "local_paths": report.get("local_paths", {}),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    app_api.export_candidates_csv(experiment_dir, candidates_path)

    print(f"Run complete: {report['local_paths']['run_dir']}")
    print(f"Summary: {summary_path}")
    print(f"Candidates: {candidates_path}")
    print(f"Report: {report['local_paths']['report_html']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
