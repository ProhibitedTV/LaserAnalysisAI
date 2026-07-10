"""Command line interface for LaserAnalysisAI v2."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ingest import init_experiment
from .manifest import latest_run_dir, load_manifest
from .pipeline import run_experiment
from .report import build_report, write_report_json
from .artifacts import load_json
from .fixtures import fetch_fixtures, list_fixtures


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            manifest = init_experiment(
                source=Path(args.source),
                kind=args.kind,
                label=args.label,
                experiment_dir=Path(args.experiment),
                frame_interval=1 if args.all_frames else args.frame_interval,
                max_frames=args.max_frames,
            )
            print(f"Experiment ready: {Path(args.experiment) / 'manifest.json'}")
            print(f"Captures: {len(manifest['captures'])}")
            return 0
        if args.command == "run":
            run_record = run_experiment(
                experiment_dir=Path(args.experiment),
                profile_name=args.profile,
                blind_seed=args.blind_seed,
            )
            latest = Path(args.experiment) / "runs" / run_record["run_id"]
            print(f"Run complete: {latest}")
            print(f"Evidence ladder: {run_record['aggregate_statistics']['evidence_ladder']}")
            print(f"Report: {latest / 'report.html'}")
            return 0
        if args.command == "report":
            manifest = load_manifest(Path(args.experiment))
            run_dir = latest_run_dir(Path(args.experiment), manifest)
            run_record = load_json(run_dir / "results.json")
            report = build_report(Path(args.experiment), run_dir, run_record)
            if args.format in {"json", "both"}:
                write_report_json(run_dir / "report.json", report)
                print(run_dir / "report.json")
            if args.format in {"html", "both"}:
                print(run_dir / "report.html")
            return 0
        if args.command == "fixtures":
            if args.fixture_action == "list":
                for item in list_fixtures(include_restricted=args.include_restricted):
                    marker = "redistributable" if item["redistributable"] else "external/manual"
                    print(f"{item['id']}: {item['title']} [{marker}]")
                    print(f"  source: {item['source_page']}")
                    print(f"  license: {item['license']}")
                return 0
            if args.fixture_action == "fetch":
                fetched = fetch_fixtures(
                    output_dir=Path(args.output),
                    fixture_ids=args.id,
                    include_restricted=args.include_restricted,
                )
                for item in fetched:
                    print(f"{item['status']}: {item['id']} -> {item.get('path', item.get('reason', ''))}")
                return 0
    except Exception as exc:
        print(f"laserlab error: {exc}", file=sys.stderr)
        return 2
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m laserlab.cli",
        description="Blinded signal validation pipeline for laser captures.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create or append to an experiment manifest.")
    init_parser.add_argument("--source", required=True, help="Video file or directory/file of images.")
    init_parser.add_argument("--kind", required=True, choices=["video", "image-set"])
    init_parser.add_argument("--label", required=True, choices=["laser", "control"])
    init_parser.add_argument("--experiment", required=True, help="Experiment output directory.")
    init_parser.add_argument("--frame-interval", type=int, default=5, help="Video frame interval. Default: 5.")
    init_parser.add_argument("--all-frames", action="store_true", help="Extract every frame from video sources.")
    init_parser.add_argument("--max-frames", type=int, default=None, help="Optional maximum frames to ingest.")

    run_parser = subparsers.add_parser("run", help="Run blinded detectors and statistical comparison.")
    run_parser.add_argument("--experiment", required=True, help="Experiment directory containing manifest.json.")
    run_parser.add_argument("--profile", default="baseline", help="Preprocessing profile name. Default: baseline.")
    run_parser.add_argument("--blind-seed", type=int, default=1, help="Seed for deterministic blinding.")

    report_parser = subparsers.add_parser("report", help="Regenerate report artifacts for the latest run.")
    report_parser.add_argument("--experiment", required=True, help="Experiment directory containing manifest.json.")
    report_parser.add_argument("--format", choices=["html", "json", "both"], default="html")

    fixtures_parser = subparsers.add_parser("fixtures", help="List or download public fixture footage.")
    fixtures_subparsers = fixtures_parser.add_subparsers(dest="fixture_action", required=True)

    fixtures_list = fixtures_subparsers.add_parser("list", help="List fixture footage candidates.")
    fixtures_list.add_argument("--include-restricted", action="store_true", help="Include manual/external sources.")

    fixtures_fetch = fixtures_subparsers.add_parser("fetch", help="Download redistributable fixture footage.")
    fixtures_fetch.add_argument("--output", default="sample_media", help="Output directory. Default: sample_media.")
    fixtures_fetch.add_argument("--id", action="append", help="Fixture ID to fetch. Repeat for multiple IDs.")
    fixtures_fetch.add_argument("--include-restricted", action="store_true", help="Include entries without direct downloads as skipped records.")

    return parser


if __name__ == "__main__":
    raise SystemExit(main())
