"""Command line interface for LaserAnalysisAI v2."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .bundle import export_review_bundle
from .diagnostics import collect_diagnostics, configure_logging, export_support_bundle
from .ingest import init_experiment
from .manifest import latest_run_dir, load_manifest
from .pipeline import run_experiment, unblind_latest_run
from .protocols import describe_protocol, list_protocol_presets
from .report import build_report, write_report_json
from .artifacts import load_json
from .fixtures import fetch_fixtures, list_fixtures
from .ingest import CAPTURE_ROLES


LOGGER = logging.getLogger("laserlab.cli")


def main(argv: list[str] | None = None) -> int:
    try:
        configure_logging()
    except OSError:
        pass
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
                capture_metadata={"independent_pair_id": args.independent_pair_id,
                                  "pair_exchangeability_acknowledged": args.acknowledge_pair_exchangeability},
                sampling_profile=args.sampling_profile,
                sampling_mode="all_frames" if args.all_frames and args.max_frames is None else "capped_all_frames" if args.all_frames else args.sampling_mode,
                deduplicate=not args.keep_duplicates,
                scene_change_threshold=args.scene_change_threshold,
            )
            print(f"Experiment ready: {Path(args.experiment) / 'manifest.json'}")
            print(f"Captures: {len(manifest['captures'])}")
            warnings = manifest["captures"][-1].get("provenance_warnings", [])
            print(f"Provenance warnings: {len(warnings)}")
            for warning in warnings:
                print(f"  {warning.get('code')}: {warning.get('message')}")
            return 0
        if args.command == "run":
            run_record = run_experiment(
                experiment_dir=Path(args.experiment),
                profile_name=args.profile,
                blind_seed=args.blind_seed,
                protocol=args.protocol,
                roi=_parse_roi(args.roi),
                primary_metric=args.primary_metric,
                preprocessing_intensity=args.preprocessing_intensity,
                control_generation=args.control_generation,
            )
            latest = Path(args.experiment) / "runs" / run_record["run_id"]
            print(f"Run complete: {latest}")
            print("Review state: blinded; labels and control statistics are sealed")
            print(f"Report: {latest / 'report.html'}")
            return 0
        if args.command == "unblind":
            run_record = unblind_latest_run(Path(args.experiment))
            unblinded_at = run_record.get("review_state", {}).get("unblinded_at") or "legacy run"
            print(f"Review state: unblinded at {unblinded_at}")
            print(f"Evidence ladder: {run_record['aggregate_statistics']['evidence_ladder']}")
            print(run_record["aggregate_statistics"].get("null_result_language", ""))
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
        if args.command == "protocols":
            if args.protocol_action == "list":
                for item in list_protocol_presets():
                    print(f"{item['id']}: {item['name']} [{item['primary_metric']}]")
                    print(f"  {item['description']}")
                return 0
            if args.protocol_action == "describe":
                print(describe_protocol(args.preset))
                return 0
        if args.command == "bundle":
            path = export_review_bundle(
                Path(args.experiment),
                Path(args.output),
                include_media=args.include_media,
                privacy_acknowledged=args.acknowledge_privacy,
            )
            print(path)
            return 0
        if args.command == "diagnostics":
            experiment = Path(args.experiment) if args.experiment else None
            record = collect_diagnostics(experiment)
            serialized = json.dumps(record, indent=2, sort_keys=True) + "\n"
            if args.output:
                destination = Path(args.output)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(serialized, encoding="utf-8")
                print(destination)
            elif args.format == "json":
                print(serialized, end="")
            else:
                _print_diagnostics(record)
            return 0
        if args.command == "support-bundle":
            experiment = Path(args.experiment) if args.experiment else None
            print(export_support_bundle(Path(args.output), experiment))
            return 0
    except Exception as exc:
        LOGGER.exception("CLI command failed")
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
    init_parser.add_argument("--independent-pair-id", help="Non-identifying predeclared ID shared by one independently acquired laser/control pair.")
    init_parser.add_argument("--acknowledge-pair-exchangeability", action="store_true", help="Declare a justified design in which conditions are exchangeable within each independent pair under the null.")
    init_parser.add_argument("--source", required=True, help="Video file or directory/file of images.")
    init_parser.add_argument("--kind", required=True, choices=["video", "image-set"])
    init_parser.add_argument("--label", required=True, choices=sorted(CAPTURE_ROLES))
    init_parser.add_argument("--experiment", required=True, help="Experiment output directory.")
    init_parser.add_argument("--sampling-profile", choices=["quick", "baseline", "wide", "exhaustive"], default="baseline")
    init_parser.add_argument("--sampling-mode", choices=["interval", "scene_change"], default=None)
    init_parser.add_argument("--frame-interval", type=int, default=None, help="Override the sampling profile frame interval.")
    init_parser.add_argument("--all-frames", action="store_true", help="Extract every frame from video sources.")
    init_parser.add_argument("--max-frames", type=int, default=None, help="Optional maximum frames to ingest.")
    init_parser.add_argument("--scene-change-threshold", type=float, default=None, help="Normalized scene-change threshold from 0 to 1.")
    init_parser.add_argument("--keep-duplicates", action="store_true", help="Keep near-duplicate frames instead of suppressing them.")

    run_parser = subparsers.add_parser("run", help="Score a sealed blinded review without source attribution.")
    run_parser.add_argument("--experiment", required=True, help="Experiment directory containing manifest.json.")
    run_parser.add_argument("--profile", default="baseline", help="Preprocessing profile name. Default: baseline.")
    run_parser.add_argument("--blind-seed", type=int, default=1, help="Seed for deterministic blinding.")
    run_parser.add_argument("--protocol", choices=["diffraction", "speckle", "ocr", "anomaly"], default=None)
    run_parser.add_argument("--primary-metric", default=None, help="Override protocol primary metric.")
    run_parser.add_argument("--preprocessing-intensity", choices=["standard", "wide"], default=None)
    run_parser.add_argument("--control-generation", choices=["none", "standard", "strict"], default=None)
    run_parser.add_argument("--roi", default=None, help="Optional ROI as x,y,width,height.")

    unblind_parser = subparsers.add_parser("unblind", help="Explicitly reveal the latest run and compute control statistics.")
    unblind_parser.add_argument("--experiment", required=True, help="Experiment directory containing a sealed run.")

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

    protocols_parser = subparsers.add_parser("protocols", help="List or describe scientific protocol presets.")
    protocols_subparsers = protocols_parser.add_subparsers(dest="protocol_action", required=True)
    protocols_subparsers.add_parser("list", help="List protocol presets.")
    protocol_describe = protocols_subparsers.add_parser("describe", help="Describe a protocol preset.")
    protocol_describe.add_argument("preset", choices=["diffraction", "speckle", "ocr", "anomaly"])

    bundle_parser = subparsers.add_parser("bundle", help="Export a local-first community review bundle.")
    bundle_parser.add_argument("--experiment", required=True, help="Experiment directory containing a completed run.")
    bundle_parser.add_argument("--output", required=True, help="Output zip path.")
    bundle_parser.add_argument("--include-media", action="store_true", help="Include original source media where available.")
    bundle_parser.add_argument(
        "--acknowledge-privacy",
        action="store_true",
        help="Confirm that participant, subjective, and community context was reviewed before unblinded export.",
    )

    diagnostics_parser = subparsers.add_parser(
        "diagnostics",
        help="Inspect local runtime, dependency, fixture, and optional OCR readiness.",
    )
    diagnostics_parser.add_argument("--experiment", help="Optional experiment directory to probe without reading its manifest.")
    diagnostics_parser.add_argument("--format", choices=["text", "json"], default="text")
    diagnostics_parser.add_argument("--output", help="Optional JSON output file. No media or manifest content is included.")

    support_parser = subparsers.add_parser(
        "support-bundle",
        help="Export redacted diagnostics and a sanitized recent log without media.",
    )
    support_parser.add_argument("--output", required=True, help="Support ZIP output path.")
    support_parser.add_argument("--experiment", help="Optional experiment directory existence probe.")

    return parser


def _parse_roi(raw: str | None) -> dict[str, int] | None:
    if not raw:
        return None
    parts = [int(part.strip()) for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("--roi must be x,y,width,height")
    return {"x": parts[0], "y": parts[1], "width": parts[2], "height": parts[3]}


def _print_diagnostics(record: dict[str, object]) -> None:
    runtime = record.get("runtime", {}) if isinstance(record.get("runtime"), dict) else {}
    dependencies = record.get("dependencies", {}) if isinstance(record.get("dependencies"), dict) else {}
    ocr = record.get("ocr", {}) if isinstance(record.get("ocr"), dict) else {}
    tesseract = ocr.get("tesseract", {}) if isinstance(ocr.get("tesseract"), dict) else {}
    fixtures = record.get("fixtures", {}) if isinstance(record.get("fixtures"), dict) else {}
    print(f"LaserLab {record.get('laserlab_version', 'unknown')}")
    print(f"Python {runtime.get('python_version', 'unknown')} / packaged={bool(runtime.get('frozen'))}")
    for name in ("numpy", "opencv", "PyQt5", "pytesseract"):
        item = dependencies.get(name, {}) if isinstance(dependencies.get(name), dict) else {}
        version = f" {item.get('version')}" if item.get("version") else ""
        if name == "PyQt5" and runtime.get("entrypoint") == "cli" and item.get("status") == "unavailable":
            version = " (carried by the separate GUI executable)"
        print(f"{name}: {item.get('status', 'unknown')}{version}")
    print(
        "fixtures: "
        + ("ready" if fixtures.get("catalog_valid") else "check failed")
        + f" ({fixtures.get('bundled_file_count', 0)}/{fixtures.get('redistributable_count', 0)})"
    )
    print(f"tesseract: {tesseract.get('status', 'unknown')} (optional)")
    print("privacy: no telemetry, uploads, source media, or manifest content")


if __name__ == "__main__":
    raise SystemExit(main())
