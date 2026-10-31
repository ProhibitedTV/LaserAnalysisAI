"""JSON and HTML report generation."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .artifacts import relative_to, write_json
from .blinding import is_unblinded
from .psychophysics import build_falsification_matrix
from .theme import badge_class, evidence_tone, report_stylesheet
from .stats import current_statistics


def build_report(experiment_dir: Path, run_dir: Path, run_record: dict[str, Any], *, write_html: bool = True) -> dict[str, Any]:
    run_record = current_statistics(run_record)
    aggregate = run_record["aggregate_statistics"]
    unblinded = is_unblinded(run_record)
    primary_metric = aggregate.get("primary_metric", "structure_score")
    candidates = top_candidates(run_record["results"], score_key="primary_metric_score", unblinded=unblinded)
    annotations = run_record.get("review_annotations", {})
    for candidate in candidates:
        candidate["review_annotation"] = annotations.get(candidate["blind_id"], {})
    badges = report_badges(run_record)
    psychophysics = run_record.get("psychophysics_analysis") if unblinded else {"sealed": True}
    falsification_matrix = (
        build_falsification_matrix(
            psychophysics_analysis=psychophysics,
            detector_evidence={
                "tested": aggregate.get("inference", {}).get("status") == "tested",
                "outcome": aggregate.get("evidence_ladder", "no signal"),
            },
        )
        if unblinded
        else {"sealed": True}
    )
    symbol_transcriptions = run_record.get("symbol_transcriptions") if unblinded else None
    report = {
        "schema_version": 1,
        "statistics_migration": run_record.get("statistics_migration"),
        "experiment_id": run_record["experiment_id"],
        "run_id": run_record["run_id"],
        "created_at": run_record["created_at"],
        "profile": run_record["profile"],
        "protocol": run_record.get("protocol", "anomaly"),
        "analysis_plan": run_record.get("analysis_plan", {}),
        "blind_seed": run_record["blind_seed"],
        "review_state": run_record.get("review_state", {"unblinded": True, "unblinded_at": None}),
        "review_session": run_record.get("review_session", {"complete": False, "completed_at": None}),
        "review_annotations": annotations,
        "provenance_summary": run_record.get("provenance_summary", {}),
        "capture_protocol_summary": run_record.get("capture_protocol_summary", {}),
        "study_context": run_record.get("study_context", {"sealed": not unblinded}),
        "subjective_reports": run_record.get("subjective_reports", []) if unblinded else [],
        "psychophysics_analysis": psychophysics,
        "falsification_matrix": falsification_matrix,
        "external_dataset_references": run_record.get("external_dataset_references", []) if unblinded else [],
        "symbol_transcription_summary": _symbol_transcription_summary(symbol_transcriptions),
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
        "source_provenance": source_provenance(run_record.get("samples", [])) if unblinded else [],
        "top_candidates": candidates,
        "artifacts": {
            "results_json": relative_to(run_dir / "results.json", experiment_dir),
            "report_json": relative_to(run_dir / "report.json", experiment_dir),
            "report_html": relative_to(run_dir / "report.html", experiment_dir),
        },
    }
    if write_html:
        write_html_report(run_dir / "report.html", report)
    return report


def top_candidates(
    results: list[dict[str, Any]],
    limit: int = 20,
    score_key: str = "structure_score",
    unblinded: bool = True,
) -> list[dict[str, Any]]:
    best_by_sample: dict[str, dict[str, Any]] = {}
    for result in results:
        if result.get("unblinded_label") == "synthetic_positive":
            continue
        current = best_by_sample.get(result["sample_id"])
        if current is None or _candidate_rank(result, score_key) > _candidate_rank(current, score_key):
            best_by_sample[result["sample_id"]] = result

    candidates = sorted(best_by_sample.values(), key=lambda item: _candidate_rank(item, score_key), reverse=True)[:limit]
    records = []
    for item in candidates:
        record = {
            "blind_id": item["blind_id"],
            "sample_id": item["sample_id"],
            "blinded_label": item["blinded_label"],
            "structure_score": item["structure_score"],
            "primary_metric": item.get("primary_metric", "structure_score"),
            "primary_metric_score": item.get("primary_metric_score", item["structure_score"]),
            "persistence_score": item.get("persistence_score", 0.0),
            "preprocessing_variant": item["preprocessing_variant"],
            "ocr_text": item.get("ocr", {}).get("text", ""),
            "ocr_confidence": item.get("ocr", {}).get("confidence", 0.0),
            "ocr_attempts": item.get("ocr_attempts", []),
            "ocr_ensemble": item.get("ocr_ensemble", {}),
            "candidate_rois": item.get("candidate_rois", [])[:3],
            "processed_path": item["processed_path"],
            "review_image_path": item.get("review_image_path", ""),
            "roi_overlay_path": item.get("roi_overlay_path", ""),
            "q_value": item.get("q_value"),
            "detector_family_scores": item.get("detector_family_scores", {}),
            "cross_pattern": item.get("cross_pattern", {}),
        }
        if unblinded:
            record.update(
                {
                    "unblinded_label": item.get("unblinded_label", ""),
                    "source_path": item.get("source_path", ""),
                    "frame_index": item.get("frame_index"),
                    "timestamp_ms": item.get("timestamp_ms"),
                    "control_type": item.get("control_type", ""),
                    "capture_metadata": item.get("capture_metadata", {}),
                }
            )
        records.append(record)
    return records


def write_report_json(path: Path, report: dict[str, Any]) -> None:
    write_json(path, report)


def write_html_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(render_html_report(report), encoding="utf-8")


def render_html_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    unblinded = bool(report.get("review_state", {}).get("unblinded", True))
    candidates = report["top_candidates"]
    rows = "\n".join(_candidate_row(candidate, unblinded=unblinded) for candidate in candidates)
    provenance_rows = "\n".join(_provenance_row(record) for record in report.get("source_provenance", []))
    protocol_rows = "\n".join(_capture_protocol_row(record) for record in report.get("source_provenance", []))
    provenance_body = provenance_rows or '<tr><td colspan="7">No capture provenance was attached.</td></tr>'
    badges = " ".join(
        f'<span class="{badge_class(badge)}">{html.escape(badge)}</span>'
        for badge in report.get("badges", [])
    )
    interpretation = report.get("interpretation", {})
    inference = report.get("aggregate_statistics", {}).get("inference", {})
    inference_html = "<p>Independent-unit counts and source classes remain sealed.</p>"
    if unblinded:
        diagnostics = report.get("aggregate_statistics", {}).get("control_diagnostics", {})
        inference_html = (
            "<h2>Independent capture inference</h2><p>" + html.escape(inference.get("message", "Not tested")) + "</p>"
            + "<p>Unit: independent matched capture pair. Candidate FDR and confidence intervals are not estimated. "
              "Frame persistence does not establish replication.</p>"
            + "<p>Declared complete pairs: " + str(inference.get("pair_count", 0))
            + "; empirical capture records: " + html.escape(str(inference.get("empirical_capture_counts", {})))
            + "; generated null frames: " + str(diagnostics.get("generated_null", {}).get("frame_count", 0))
            + "; positive calibration images: " + str(report.get("aggregate_statistics", {}).get("synthetic_positive_count", 0))
            + ".</p><details><summary>Method, limitations and source classes</summary>"
              '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">'
            + html.escape(json.dumps({"inference": inference, "source_class_diagnostics": diagnostics}, indent=2, sort_keys=True))
            + "</pre></details>"
        )
    migration_html = "<p>" + html.escape(report["statistics_migration"]) + "</p>" if report.get("statistics_migration") else ""
    ladder_tone = evidence_tone(summary.get("evidence_ladder"))
    if unblinded:
        metrics_html = f"""
    <div class="metric"><strong>Laser mean</strong>{_fmt(summary['laser_mean_score'])}</div>
    <div class="metric"><strong>Control mean</strong>{_fmt(summary['control_mean_score'])}</div>
    <div class="metric"><strong>Difference</strong>{_fmt(summary['mean_difference'])}</div>
    <div class="metric"><strong>Paired Cohen dz</strong>{_fmt(summary['cohen_d'])}</div>
    <div class="metric"><strong>Permutation p</strong>{_fmt(summary['permutation_p_value'])}</div>
    <div class="metric"><strong>Minimum q</strong>{_fmt(summary.get('minimum_q_value'))}</div>"""
        provenance_html = f"""
  <h2>Capture Protocol</h2>
  <table><thead><tr><th>Capture</th><th>Footage class</th><th>Pattern</th><th>Wavelength</th><th>Surface</th><th>Geometry</th><th>Safety / quality</th></tr></thead>
    <tbody>{protocol_rows or '<tr><td colspan="7">No structured capture protocol was attached.</td></tr>'}</tbody>
  </table>
  <h2>Source Provenance</h2>
  <table><thead><tr><th>Capture</th><th>Media</th><th>Phenomena</th><th>License</th><th>Expected behavior</th><th>Limitations</th><th>Warnings</th></tr></thead>
    <tbody>{provenance_body}</tbody>
  </table>"""
        study_context = report.get("study_context", {})
        subjective_html = f"""
  <h2>Subjective Context</h2>
  <div class="summary">
    <p><strong>Evidence role:</strong> Context only; excluded from detector scores and control statistics.</p>
    <p><strong>Mode:</strong> {html.escape(str(study_context.get('mode', 'footage_only')))}</p>
    <p><strong>Session:</strong> {html.escape(str(study_context.get('pseudonymous_session_id') or 'not attached'))}</p>
    <p>{html.escape(str(study_context.get('perception_notes', '')))}</p>
  </div>"""
        psychophysics = report.get("psychophysics_analysis") or {}
        psych_metrics = psychophysics.get("metrics", {})
        if psychophysics.get("analysis_status") == "tested":
            psychophysics_html = f"""
  <h2>Signal-Detection Trial Analysis</h2>
  <div class="summary">
    <p><strong>Evidence role:</strong> Psychophysics only; kept separate from camera detector evidence.</p>
    <div class="metric"><strong>d-prime</strong>{_fmt(psych_metrics.get('d_prime'))}</div>
    <div class="metric"><strong>Criterion</strong>{_fmt(psych_metrics.get('criterion'))}</div>
    <div class="metric"><strong>Balanced accuracy</strong>{_fmt(psych_metrics.get('balanced_accuracy'))}</div>
    <p>{html.escape(str(psychophysics.get('interpretation_limit', '')))}</p>
  </div>"""
        else:
            psychophysics_html = ""
        matrix_rows = "\n".join(
            _falsification_row(row) for row in report.get("falsification_matrix", {}).get("rows", [])
        )
        falsification_html = f"""
  <h2>Falsification Matrix</h2>
  <table><thead><tr><th>Question</th><th>Evidence domain</th><th>Status</th><th>Outcome</th></tr></thead>
    <tbody>{matrix_rows or '<tr><td colspan="4">No falsification modules were declared.</td></tr>'}</tbody>
  </table>"""
        community_summary = report.get("symbol_transcription_summary", {})
        community_html = f"""
  <h2>Community Data Context</h2>
  <div class="summary">
    <p><strong>External imports:</strong> {len(report.get('external_dataset_references', []))}</p>
    <p><strong>Symbol transcriptions:</strong> {int(community_summary.get('record_count', 0))}</p>
    <p><strong>Evidence role:</strong> Context only; excluded from detector scores.</p>
  </div>"""
        candidate_headers = "<th>Blind ID</th><th>Role</th><th>Score</th><th>Persistence</th><th>q-value</th><th>Variant</th><th>Source</th><th>OCR</th><th>Review</th><th>Image</th>"
    else:
        metrics_html = '<div class="sealed">Source roles and control statistics remain sealed until explicit unblind.</div>'
        provenance_html = ""
        subjective_html = ""
        psychophysics_html = ""
        falsification_html = ""
        community_html = ""
        candidate_headers = "<th>Blind ID</th><th>Score</th><th>Persistence</th><th>Variant</th><th>OCR</th><th>Review</th><th>Image</th>"
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>LaserAnalysisAI Report {html.escape(report['run_id'])}</title>
  <style>{report_stylesheet()}</style>
</head>
<body>
  <h1>LaserAnalysisAI Blinded Signal Report</h1>
  {migration_html}
  {inference_html}
  <div class="summary">
    <p>{badges}</p>
    <div class="metric"><strong>Evidence ladder</strong><span class="evidence-value evidence-value--{ladder_tone}">{html.escape(str(summary['evidence_ladder']))}</span></div>
    <div class="metric"><strong>Primary metric</strong>{html.escape(str(summary.get('primary_metric', 'structure_score')))}</div>
    {metrics_html}
    <p>{html.escape(summary['null_result_language'])}</p>
    <p><strong>What this means:</strong> {html.escape(interpretation.get('what_this_means', ''))}</p>
    <p><strong>What this does not mean:</strong> {html.escape(interpretation.get('what_this_does_not_mean', ''))}</p>
  </div>
  {provenance_html}
  {subjective_html}
  {psychophysics_html}
  {falsification_html}
  {community_html}
  <h2>Top Candidates</h2>
  <table>
    <thead>
      <tr>{candidate_headers}</tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
"""
    return html_text


def _candidate_row(candidate: dict[str, Any], unblinded: bool) -> str:
    media = _candidate_media(candidate)
    ocr_text = candidate.get("ocr_text") or ""
    annotation = candidate.get("review_annotation") or {}
    review_text = ", ".join(annotation.get("flags", []))
    if annotation.get("note"):
        review_text = (review_text + " | " if review_text else "") + str(annotation["note"])
    if unblinded:
        return f"""
      <tr>
        <td><code>{html.escape(candidate['blind_id'])}</code></td>
        <td>{html.escape(candidate.get('unblinded_label', ''))}</td>
        <td>{_fmt(candidate.get('primary_metric_score', candidate['structure_score']))}</td>
        <td>{_fmt(candidate.get('persistence_score'))}</td>
        <td>{_fmt(candidate.get('q_value'))}</td>
        <td>{html.escape(candidate['preprocessing_variant'])}</td>
        <td>{html.escape(_source_label(candidate))}</td>
        <td>{html.escape(ocr_text[:120])}</td>
        <td>{html.escape(review_text[:240])}</td>
        <td>{media}</td>
      </tr>
"""
    return f"""
      <tr>
        <td><code>{html.escape(candidate['blind_id'])}</code></td>
        <td>{_fmt(candidate.get('primary_metric_score', candidate['structure_score']))}</td>
        <td>{_fmt(candidate.get('persistence_score'))}</td>
        <td>{html.escape(candidate['preprocessing_variant'])}</td>
        <td>{html.escape(ocr_text[:120])}</td>
        <td>{html.escape(review_text[:240])}</td>
        <td>{media}</td>
      </tr>
"""


def _candidate_media(candidate: dict[str, Any]) -> str:
    roi = (candidate.get("candidate_rois") or [{}])[0]
    sources = [
        ("Original", candidate.get("review_image_path")),
        ("Processed", candidate.get("processed_path")),
        ("ROI overlay", candidate.get("roi_overlay_path")),
        ("Processed crop", roi.get("processed_crop_path") or roi.get("crop_path")),
    ]
    items = []
    for label, stored in sources:
        if not stored:
            continue
        source = html.escape(_relative_from_run(str(stored)))
        items.append(
            f'<a href="{source}"><span>{html.escape(label)}</span><img src="{source}" '
            f'alt="{html.escape(candidate["blind_id"])} {html.escape(label)}"></a>'
        )
    return '<div class="candidate-media">' + "".join(items) + "</div>"


def _falsification_row(row: dict[str, Any]) -> str:
    outcome = row.get("outcome")
    if isinstance(outcome, dict):
        outcome_text = ", ".join(f"{key}: {_fmt(value)}" for key, value in outcome.items())
    else:
        outcome_text = str(outcome or "")
    return (
        "<tr>"
        f"<td>{html.escape(str(row.get('question', '')))}</td>"
        f"<td>{html.escape(str(row.get('evidence_domain', '')))}</td>"
        f"<td>{html.escape(str(row.get('status', 'not_tested')).replace('_', ' '))}</td>"
        f"<td>{html.escape(outcome_text)}</td>"
        "</tr>"
    )


def _symbol_transcription_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"record_count": 0, "evidence_role": "context_only"}
    return {
        "record_count": len(payload.get("records", [])),
        "evidence_role": "context_only",
        "privacy": payload.get("privacy", {}),
        "source_sha256": payload.get("source_sha256"),
    }


def _provenance_row(record: dict[str, Any]) -> str:
    title = record.get("fixture_title") or record.get("fixture_id") or record.get("capture_id") or "Unknown capture"
    source_page = record.get("source_page")
    if source_page:
        title_html = f'<a href="{html.escape(str(source_page))}">{html.escape(str(title))}</a>'
    else:
        title_html = html.escape(str(title))
    phenomena = ", ".join(str(item) for item in record.get("phenomena", []))
    media = record.get("media_metadata", {})
    dimensions = "x".join(str(value) for value in (media.get("width"), media.get("height")) if value)
    media_parts = [dimensions]
    if media.get("fps"):
        media_parts.append(f"{media['fps']:.3g} fps")
    if media.get("codec"):
        media_parts.append(str(media["codec"]))
    warnings = "; ".join(str(item.get("message", item)) for item in record.get("provenance_warnings", []))
    return f"""
      <tr>
        <td>{title_html}</td>
        <td>{html.escape(' | '.join(part for part in media_parts if part))}</td>
        <td>{html.escape(phenomena)}</td>
        <td>{html.escape(str(record.get('license', '')))}</td>
        <td>{html.escape(str(record.get('expected_behavior', '')))}</td>
        <td>{html.escape(str(record.get('limitations', '')))}</td>
        <td>{html.escape(warnings)}</td>
      </tr>
"""


def _capture_protocol_row(record: dict[str, Any]) -> str:
    wavelength = record.get("wavelength_nm")
    wavelength_text = "n/a" if wavelength is None else f"{wavelength:g} nm {record.get('color_label') or ''}".strip()
    geometry = " | ".join(
        str(value)
        for value in (
            record.get("projection_distance_meters") and f"{record['projection_distance_meters']} m",
            record.get("laser_to_target_geometry_notes"),
            record.get("intermediate_material_notes"),
        )
        if value
    )
    safety = []
    if record.get("camera_fixed") is True:
        safety.append("camera fixed")
    if record.get("beam_path_fixed") is True:
        safety.append("beam fixed")
    if record.get("projected_region_not_saturated") is True:
        safety.append("not saturated")
    safety.extend(str(item.get("message", item)) for item in record.get("provenance_warnings", []))
    return f"""
      <tr>
        <td>{html.escape(str(record.get('capture_id') or record.get('fixture_id') or 'unknown'))}</td>
        <td>{html.escape(str(record.get('footage_class', 'other')))}</td>
        <td>{html.escape(str(record.get('laser_pattern_type', 'unknown')))}</td>
        <td>{html.escape(wavelength_text)}</td>
        <td>{html.escape(str(record.get('projection_surface_type', 'unknown')))}</td>
        <td>{html.escape(geometry)}</td>
        <td>{html.escape('; '.join(safety))}</td>
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
        capture_id = sample.get("capture_id") or sample.get("parent_capture_id")
        fixture_id = metadata.get("fixture_id")
        if not capture_id and not fixture_id:
            continue
        key = str(capture_id or fixture_id or sample.get("sample_id"))
        record = records.setdefault(key, {"capture_id": capture_id})
        if metadata:
            record.update(dict(metadata))
        if sample.get("media_metadata"):
            record["media_metadata"] = sample["media_metadata"]
        if sample.get("provenance_warnings"):
            record["provenance_warnings"] = sample["provenance_warnings"]
    return sorted(
        records.values(),
        key=lambda record: (
            0 if record.get("fixture_id") else 1,
            str(record.get("fixture_id") or record.get("capture_id") or ""),
        ),
    )


def _candidate_score(result: dict[str, Any], score_key: str) -> float:
    value = result.get(score_key)
    if value is None:
        value = result.get("structure_score", 0.0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _candidate_rank(result: dict[str, Any], score_key: str) -> tuple[float, float, float]:
    """Break primary-metric ties with visible structure without changing the metric."""

    roi_score = max(
        (float(roi.get("score", 0.0) or 0.0) for roi in result.get("candidate_rois", [])),
        default=0.0,
    )
    return (
        _candidate_score(result, score_key),
        float(result.get("structure_score", 0.0) or 0.0),
        roi_score,
    )


def report_badges(run_record: dict[str, Any]) -> list[str]:
    aggregate = run_record.get("aggregate_statistics", {})
    results = run_record.get("results", [])
    if not is_unblinded(run_record):
        badges = ["review blinded", "source roles sealed"]
    else:
        badges = ["review unblinded"]
    badges.append("candidate FDR not estimated")
    if aggregate.get("calibration_passed"):
        badges.append("calibration passed")
    elif aggregate.get("synthetic_positive_count", 0) > 0:
        badges.append("calibration failed")
    if is_unblinded(run_record) and aggregate.get("control_count", 0) > 0:
        badges.append("empirical matched controls declared")
    if is_unblinded(run_record) and aggregate.get("inference", {}).get("status") != "tested":
        badges.append("capture inference withheld")
    if results and not any(item.get("ocr", {}).get("available") for item in results):
        badges.append("OCR unavailable")
    warning_count = int(run_record.get("provenance_summary", {}).get("warning_count", 0) or 0)
    badges.append("provenance complete" if warning_count == 0 else f"provenance warnings: {warning_count}")
    if run_record.get("review_session", {}).get("complete"):
        badges.append("blind review complete")
    protocol_summary = run_record.get("capture_protocol_summary", {})
    if protocol_summary.get("primary_wall_projection"):
        badges.append("wall-projection footage")
    elif protocol_summary.get("fixture_only"):
        badges.append("fixture/demo footage only")
    if is_unblinded(run_record) and (run_record.get("psychophysics_analysis") or {}).get("analysis_status") == "tested":
        badges.append("psychophysics analyzed separately")
    if is_unblinded(run_record) and run_record.get("external_dataset_references"):
        badges.append("external metadata context only")
    if is_unblinded(run_record) and (run_record.get("symbol_transcriptions") or {}).get("records"):
        badges.append("symbol transcriptions context only")
    badges.append("media not included")
    return badges


def interpretation_text(aggregate: dict[str, Any]) -> dict[str, str]:
    ladder = aggregate.get("evidence_ladder")
    if ladder == "blinded review":
        means = "Candidates are ranked without source roles or control comparisons visible."
    elif ladder in {"not tested", "insufficient independent samples"}:
        means = aggregate.get("null_result_language", "No suitable independent empirical comparison was tested.")
    elif ladder in {"above-control candidate", "repeatable candidate"}:
        means = "The selected protocol found capture-pair scores above declared empirical matched controls under the stated exchangeability assumptions."
    elif ladder == "anomaly":
        means = "The run found elevated structure, but not enough to clear the controlled evidence threshold."
    else:
        means = "The selected capture and detector set did not beat matched controls."
    return {
        "what_this_means": means,
        "what_this_does_not_mean": "A pattern is not proof of language, origin, intent, or metaphysical meaning. Unblinding alone does not establish a suitable control or independent replication.",
    }


def detector_family_explanations() -> dict[str, str]:
    return {
        "symbol": "OCR and connected-component evidence for text-like or symbol-like regions.",
        "diffraction": "FFT peak/ring evidence for repeatable spatial-frequency structure.",
        "speckle": "Local contrast evidence using K = standard deviation divided by mean intensity.",
        "texture": "Haralick-style texture, entropy, edge, line, and ROI structure evidence.",
    }
