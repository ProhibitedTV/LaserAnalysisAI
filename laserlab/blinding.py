"""Seal and restore review records around an explicit unblind action."""

from __future__ import annotations

from typing import Any


UNBLIND_FILENAME = ".laserlab_unblind.json"


def is_unblinded(run_record: dict[str, Any]) -> bool:
    state = run_record.get("review_state")
    return True if state is None else bool(state.get("unblinded"))


def build_unblind_payload(
    samples: list[dict[str, Any]],
    results: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    sample_map = {sample["blind_id"]: dict(sample) for sample in samples}
    calibration_results = [
        dict(result)
        for result in results
        if sample_map.get(result["blind_id"], {}).get("unblinded_label") == "synthetic_positive"
    ]
    return {
        "schema_version": 1,
        "samples": sample_map,
        "calibration_results": calibration_results,
        "manifest_sensitive": {
            "sources": manifest.get("sources", []),
            "captures": manifest.get("captures", []),
            "controls": manifest.get("controls", []),
            "capture_metadata": manifest.get("capture_metadata", {}),
        },
    }


def seal_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "sample_id": sample["blind_id"],
            "blind_id": sample["blind_id"],
            "blinded_label": sample["blind_id"],
        }
        for sample in samples
        if sample.get("unblinded_label") != "synthetic_positive"
    ]


def seal_results(results: list[dict[str, Any]], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sample_map = {sample["blind_id"]: sample for sample in samples}
    return [
        _seal_result(result)
        for result in results
        if sample_map.get(result["blind_id"], {}).get("unblinded_label") != "synthetic_positive"
    ]


def restore_run_record(run_record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    restored = dict(run_record)
    sample_map = payload.get("samples", {})
    restored["samples"] = [dict(sample) for sample in sample_map.values()]
    restored_results = []
    for result in run_record.get("results", []):
        sample = sample_map.get(result.get("blind_id"))
        if not sample:
            raise ValueError(f"Missing sealed sample mapping for {result.get('blind_id')}")
        restored_results.append(_restore_result(result, sample))
    restored_results.extend(dict(result) for result in payload.get("calibration_results", []))
    restored["results"] = restored_results
    return restored


def seal_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(manifest)
    sealed["sources"] = [
        {
            "source_id": source.get("source_id"),
            "kind": source.get("kind"),
            "sealed": True,
        }
        for source in manifest.get("sources", [])
    ]
    sealed["captures"] = [
        {
            "capture_id": capture.get("capture_id"),
            "source_id": capture.get("source_id"),
            "kind": capture.get("kind"),
            "frame_count": len(capture.get("frames", [])),
            "sealed": True,
        }
        for capture in manifest.get("captures", [])
    ]
    sealed["controls"] = []
    sealed["capture_metadata"] = {"sealed": True}
    return sealed


def restore_manifest(manifest: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    restored = dict(manifest)
    for key, value in payload.get("manifest_sensitive", {}).items():
        restored[key] = value
    return restored


def _seal_result(result: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "run_id",
        "blind_id",
        "blinded_label",
        "review_image_path",
        "processed_path",
        "processed_sha256",
        "preprocessing_profile",
        "preprocessing_variant",
        "preprocessing_hash",
        "protocol",
        "primary_metric",
        "ocr",
        "connected_components",
        "entropy_texture",
        "edge_line_density",
        "fft_spectrum",
        "speckle_contrast",
        "texture_features",
        "frame_registration",
        "detector_family_scores",
        "candidate_rois",
        "structure_score",
        "primary_metric_score",
        "persistence_score",
    }
    sealed = {key: value for key, value in result.items() if key in allowed}
    sealed["sample_id"] = result["blind_id"]
    sealed["q_value"] = None
    return sealed


def _restore_result(result: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    restored = dict(result)
    restored.update(
        {
            "sample_id": sample["sample_id"],
            "unblinded_label": sample["unblinded_label"],
            "capture_id": sample.get("capture_id"),
            "parent_capture_id": sample.get("parent_capture_id"),
            "frame_id": sample.get("frame_id"),
            "parent_frame_id": sample.get("parent_frame_id"),
            "control_type": sample.get("control_type"),
            "frame_index": sample.get("frame_index"),
            "timestamp_ms": sample.get("timestamp_ms"),
            "source_path": sample.get("path", ""),
            "source_sha256": sample.get("source_sha256", ""),
            "capture_metadata": sample.get("capture_metadata", {}),
        }
    )
    return restored
