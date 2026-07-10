"""JSON and HTML report generation."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .artifacts import relative_to, write_json


def build_report(experiment_dir: Path, run_dir: Path, run_record: dict[str, Any]) -> dict[str, Any]:
    aggregate = run_record["aggregate_statistics"]
    candidates = top_candidates(run_record["results"])
    report = {
        "schema_version": 1,
        "experiment_id": run_record["experiment_id"],
        "run_id": run_record["run_id"],
        "created_at": run_record["created_at"],
        "profile": run_record["profile"],
        "blind_seed": run_record["blind_seed"],
        "summary": {
            "evidence_ladder": aggregate["evidence_ladder"],
            "null_result_language": aggregate["null_result_language"],
            "laser_mean_score": aggregate["laser_mean_score"],
            "control_mean_score": aggregate["control_mean_score"],
            "mean_difference": aggregate["mean_difference"],
            "cohen_d": aggregate["cohen_d"],
            "permutation_p_value": aggregate["permutation_p_value"],
        },
        "aggregate_statistics": aggregate,
        "top_candidates": candidates,
        "artifacts": {
            "results_json": relative_to(run_dir / "results.json", experiment_dir),
            "report_json": relative_to(run_dir / "report.json", experiment_dir),
            "report_html": relative_to(run_dir / "report.html", experiment_dir),
        },
    }
    write_html_report(run_dir / "report.html", report)
    return report


def top_candidates(results: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    best_by_sample: dict[str, dict[str, Any]] = {}
    for result in results:
        current = best_by_sample.get(result["sample_id"])
        if current is None or result["structure_score"] > current["structure_score"]:
            best_by_sample[result["sample_id"]] = result

    candidates = sorted(best_by_sample.values(), key=lambda item: item["structure_score"], reverse=True)[:limit]
    return [
        {
            "blind_id": item["blind_id"],
            "sample_id": item["sample_id"],
            "blinded_label": item["blinded_label"],
            "unblinded_label": item["unblinded_label"],
            "structure_score": item["structure_score"],
            "persistence_score": item.get("persistence_score", 0.0),
            "preprocessing_variant": item["preprocessing_variant"],
            "ocr_text": item.get("ocr", {}).get("text", ""),
            "ocr_confidence": item.get("ocr", {}).get("confidence", 0.0),
            "candidate_rois": item.get("candidate_rois", [])[:3],
            "processed_path": item["processed_path"],
        }
        for item in candidates
    ]


def write_report_json(path: Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_html_report(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    candidates = report["top_candidates"]
    rows = "\n".join(_candidate_row(candidate) for candidate in candidates)
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>LaserAnalysisAI Report {html.escape(report['run_id'])}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2933; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .summary {{ border: 1px solid #cbd5e1; border-radius: 6px; padding: 16px; max-width: 960px; }}
    .metric {{ display: inline-block; margin: 8px 18px 8px 0; }}
    .metric strong {{ display: block; font-size: 12px; color: #52616b; text-transform: uppercase; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; font-size: 12px; text-transform: uppercase; color: #52616b; }}
    code {{ background: #f0f4f8; padding: 2px 4px; border-radius: 4px; }}
    img {{ max-width: 180px; max-height: 120px; border: 1px solid #d9e2ec; }}
  </style>
</head>
<body>
  <h1>LaserAnalysisAI Blinded Signal Report</h1>
  <div class="summary">
    <div class="metric"><strong>Evidence ladder</strong>{html.escape(str(summary['evidence_ladder']))}</div>
    <div class="metric"><strong>Laser mean</strong>{_fmt(summary['laser_mean_score'])}</div>
    <div class="metric"><strong>Control mean</strong>{_fmt(summary['control_mean_score'])}</div>
    <div class="metric"><strong>Difference</strong>{_fmt(summary['mean_difference'])}</div>
    <div class="metric"><strong>Cohen d</strong>{_fmt(summary['cohen_d'])}</div>
    <div class="metric"><strong>Permutation p</strong>{_fmt(summary['permutation_p_value'])}</div>
    <p>{html.escape(summary['null_result_language'])}</p>
  </div>
  <h2>Top Candidates</h2>
  <table>
    <thead>
      <tr>
        <th>Blind ID</th>
        <th>Unblinded Label</th>
        <th>Score</th>
        <th>Persistence</th>
        <th>Variant</th>
        <th>OCR</th>
        <th>Image</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(html_text, encoding="utf-8")


def _candidate_row(candidate: dict[str, Any]) -> str:
    image_src = html.escape(_relative_from_run(candidate["processed_path"]))
    ocr_text = candidate.get("ocr_text") or ""
    return f"""
      <tr>
        <td><code>{html.escape(candidate['blind_id'])}</code></td>
        <td>{html.escape(candidate['unblinded_label'])}</td>
        <td>{_fmt(candidate['structure_score'])}</td>
        <td>{_fmt(candidate.get('persistence_score'))}</td>
        <td>{html.escape(candidate['preprocessing_variant'])}</td>
        <td>{html.escape(ocr_text[:120])}</td>
        <td><a href="{image_src}"><img src="{image_src}" alt="{html.escape(candidate['blind_id'])}"></a></td>
      </tr>
"""


def _relative_from_run(path: str) -> str:
    parts = path.split("/")
    if "runs" in parts:
        index = parts.index("runs")
        if len(parts) > index + 2:
            return "/".join(parts[index + 2 :])
    return path


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return html.escape(str(value))
