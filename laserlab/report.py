"""JSON and HTML report generation."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .artifacts import relative_to, write_json


def build_report(experiment_dir: Path, run_dir: Path, run_record: dict[str, Any]) -> dict[str, Any]:
    aggregate = run_record["aggregate_statistics"]
    primary_metric = aggregate.get("primary_metric", "structure_score")
    candidates = top_candidates(run_record["results"], score_key="primary_metric_score")
    badges = report_badges(run_record)
    report = {
        "schema_version": 1,
        "experiment_id": run_record["experiment_id"],
        "run_id": run_record["run_id"],
        "created_at": run_record["created_at"],
        "profile": run_record["profile"],
        "protocol": run_record.get("protocol", "anomaly"),
        "analysis_plan": run_record.get("analysis_plan", {}),
        "blind_seed": run_record["blind_seed"],
        "badges": badges,
        "summary": {
            "evidence_ladder": aggregate["evidence_ladder"],
            "null_result_language": aggregate["null_result_language"],
            "laser_mean_score": aggregate["laser_mean_score"],
            "control_mean_score": aggregate["control_mean_score"],
            "mean_difference": aggregate["mean_difference"],
            "cohen_d": aggregate["cohen_d"],
            "permutation_p_value": aggregate["permutation_p_value"],
            "minimum_q_value": aggregate.get("minimum_q_value"),
            "primary_metric": primary_metric,
        },
        "interpretation": interpretation_text(aggregate),
        "detector_family_explanations": detector_family_explanations(),
        "aggregate_statistics": aggregate,
        "source_provenance": source_provenance(run_record.get("samples", [])),
        "top_candidates": candidates,
        "artifacts": {
            "results_json": relative_to(run_dir / "results.json", experiment_dir),
            "report_json": relative_to(run_dir / "report.json", experiment_dir),
            "report_html": relative_to(run_dir / "report.html", experiment_dir),
        },
    }
    write_html_report(run_dir / "report.html", report)
    return report


def top_candidates(
    results: list[dict[str, Any]],
    limit: int = 20,
    score_key: str = "structure_score",
) -> list[dict[str, Any]]:
    best_by_sample: dict[str, dict[str, Any]] = {}
    for result in results:
        current = best_by_sample.get(result["sample_id"])
        if current is None or _candidate_score(result, score_key) > _candidate_score(current, score_key):
            best_by_sample[result["sample_id"]] = result

    candidates = sorted(best_by_sample.values(), key=lambda item: _candidate_score(item, score_key), reverse=True)[:limit]
    return [
        {
            "blind_id": item["blind_id"],
            "sample_id": item["sample_id"],
            "blinded_label": item["blinded_label"],
            "unblinded_label": item["unblinded_label"],
            "structure_score": item["structure_score"],
            "primary_metric": item.get("primary_metric", "structure_score"),
            "primary_metric_score": item.get("primary_metric_score", item["structure_score"]),
            "persistence_score": item.get("persistence_score", 0.0),
            "preprocessing_variant": item["preprocessing_variant"],
            "ocr_text": item.get("ocr", {}).get("text", ""),
            "ocr_confidence": item.get("ocr", {}).get("confidence", 0.0),
            "candidate_rois": item.get("candidate_rois", [])[:3],
            "processed_path": item["processed_path"],
            "source_path": item.get("source_path", ""),
            "frame_index": item.get("frame_index"),
            "timestamp_ms": item.get("timestamp_ms"),
            "control_type": item.get("control_type", ""),
            "q_value": item.get("q_value"),
            "detector_family_scores": item.get("detector_family_scores", {}),
            "capture_metadata": item.get("capture_metadata", {}),
        }
        for item in candidates
    ]


def write_report_json(path: Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_html_report(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    candidates = report["top_candidates"]
    rows = "\n".join(_candidate_row(candidate) for candidate in candidates)
    provenance_rows = "\n".join(_provenance_row(record) for record in report.get("source_provenance", []))
    provenance_body = provenance_rows or '<tr><td colspan="5">No catalog fixture metadata was attached.</td></tr>'
    badges = " ".join(f"<span class=\"badge\">{html.escape(badge)}</span>" for badge in report.get("badges", []))
    interpretation = report.get("interpretation", {})
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>LaserAnalysisAI Report {html.escape(report['run_id'])}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; color: #1f2933; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .summary {{ border: 1px solid #cbd5e1; border-radius: 6px; padding: 16px; max-width: 960px; }}
    .badge {{ display: inline-block; background: #e6f4f1; border: 1px solid #9fc9bf; border-radius: 999px; padding: 4px 10px; margin: 4px 6px 4px 0; font-size: 12px; }}
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
    <p>{badges}</p>
    <div class="metric"><strong>Evidence ladder</strong>{html.escape(str(summary['evidence_ladder']))}</div>
    <div class="metric"><strong>Primary metric</strong>{html.escape(str(summary.get('primary_metric', 'structure_score')))}</div>
    <div class="metric"><strong>Laser mean</strong>{_fmt(summary['laser_mean_score'])}</div>
    <div class="metric"><strong>Control mean</strong>{_fmt(summary['control_mean_score'])}</div>
    <div class="metric"><strong>Difference</strong>{_fmt(summary['mean_difference'])}</div>
    <div class="metric"><strong>Cohen d</strong>{_fmt(summary['cohen_d'])}</div>
    <div class="metric"><strong>Permutation p</strong>{_fmt(summary['permutation_p_value'])}</div>
    <div class="metric"><strong>Minimum q</strong>{_fmt(summary.get('minimum_q_value'))}</div>
    <p>{html.escape(summary['null_result_language'])}</p>
    <p><strong>What this means:</strong> {html.escape(interpretation.get('what_this_means', ''))}</p>
    <p><strong>What this does not mean:</strong> {html.escape(interpretation.get('what_this_does_not_mean', ''))}</p>
  </div>
  <h2>Source Provenance</h2>
  <table>
    <thead>
      <tr>
        <th>Fixture</th>
        <th>Phenomena</th>
        <th>License</th>
        <th>Expected behavior</th>
        <th>Limitations</th>
      </tr>
    </thead>
    <tbody>
      {provenance_body}
    </tbody>
  </table>
  <h2>Top Candidates</h2>
  <table>
    <thead>
      <tr>
        <th>Blind ID</th>
        <th>Unblinded Label</th>
        <th>Score</th>
        <th>Persistence</th>
        <th>q-value</th>
        <th>Variant</th>
        <th>Source</th>
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
        <td>{_fmt(candidate.get('primary_metric_score', candidate['structure_score']))}</td>
        <td>{_fmt(candidate.get('persistence_score'))}</td>
        <td>{_fmt(candidate.get('q_value'))}</td>
        <td>{html.escape(candidate['preprocessing_variant'])}</td>
        <td>{html.escape(_source_label(candidate))}</td>
        <td>{html.escape(ocr_text[:120])}</td>
        <td><a href="{image_src}"><img src="{image_src}" alt="{html.escape(candidate['blind_id'])}"></a></td>
      </tr>
"""


def _provenance_row(record: dict[str, Any]) -> str:
    title = record.get("fixture_title") or record.get("fixture_id") or "Unknown fixture"
    source_page = record.get("source_page")
    if source_page:
        title_html = f'<a href="{html.escape(str(source_page))}">{html.escape(str(title))}</a>'
    else:
        title_html = html.escape(str(title))
    phenomena = ", ".join(str(item) for item in record.get("phenomena", []))
    return f"""
      <tr>
        <td>{title_html}</td>
        <td>{html.escape(phenomena)}</td>
        <td>{html.escape(str(record.get('license', '')))}</td>
        <td>{html.escape(str(record.get('expected_behavior', '')))}</td>
        <td>{html.escape(str(record.get('limitations', '')))}</td>
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


def _source_label(candidate: dict[str, Any]) -> str:
    parts = [candidate.get("source_path", "")]
    frame_index = candidate.get("frame_index")
    if frame_index is not None:
        parts.append(f"frame {frame_index}")
    control_type = candidate.get("control_type")
    if control_type:
        parts.append(str(control_type))
    fixture_title = candidate.get("capture_metadata", {}).get("fixture_title")
    if fixture_title:
        parts.append(str(fixture_title))
    return " | ".join(str(part) for part in parts if part)


def source_provenance(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for sample in samples:
        metadata = sample.get("capture_metadata") or {}
        fixture_id = metadata.get("fixture_id")
        if fixture_id:
            records[str(fixture_id)] = dict(metadata)
    return [records[key] for key in sorted(records)]


def _candidate_score(result: dict[str, Any], score_key: str) -> float:
    value = result.get(score_key)
    if value is None:
        value = result.get("structure_score", 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def report_badges(run_record: dict[str, Any]) -> list[str]:
    aggregate = run_record.get("aggregate_statistics", {})
    results = run_record.get("results", [])
    badges = ["multiple comparisons corrected"]
    if aggregate.get("calibration_passed"):
        badges.append("calibration passed")
    elif aggregate.get("synthetic_positive_count", 0) > 0:
        badges.append("calibration failed")
    if aggregate.get("control_count", 0) > 0:
        badges.append("controls matched")
    if results and not any(item.get("ocr", {}).get("available") for item in results):
        badges.append("OCR unavailable")
    badges.append("media not included")
    return badges


def interpretation_text(aggregate: dict[str, Any]) -> dict[str, str]:
    ladder = aggregate.get("evidence_ladder")
    if ladder in {"above-control candidate", "repeatable candidate"}:
        means = "The selected protocol found laser-frame scores above matched controls under this run's thresholds."
    elif ladder == "anomaly":
        means = "The run found elevated structure, but not enough to clear the controlled evidence threshold."
    else:
        means = "The selected capture and detector set did not beat matched controls."
    return {
        "what_this_means": means,
        "what_this_does_not_mean": "This report does not establish origin, intent, or metaphysical proof; it only summarizes controlled image detections.",
    }


def detector_family_explanations() -> dict[str, str]:
    return {
        "symbol": "OCR and connected-component evidence for text-like or symbol-like regions.",
        "diffraction": "FFT peak/ring evidence for repeatable spatial-frequency structure.",
        "speckle": "Local contrast evidence using K = standard deviation divided by mean intensity.",
        "texture": "Haralick-style texture, entropy, edge, line, and ROI structure evidence.",
    }
