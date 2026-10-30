"""Structured wall-projection and laser-hardware capture metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


FOOTAGE_CLASSES = {
    "primary_wall_projection",
    "calibration_fixture",
    "regression_fixture",
    "demo_fixture",
    "other",
}
LASER_PATTERN_TYPES = {"cross", "dot", "line", "grid", "fan", "unknown"}
SURFACE_TYPES = {"matte_wall", "painted_drywall", "textured_paper", "fabric", "other", "unknown"}
STUDY_CONTEXT_MODES = {"footage_only", "retrospective_report", "externally_approved_study"}
WAVELENGTH_PRESETS = {
    650: "red",
    532: "green",
    488: "cyan",
    450: "blue",
    405: "violet_near_uv",
}


CAPTURE_PROTOCOL_DEFAULTS: dict[str, Any] = {
    "footage_class": "primary_wall_projection",
    "projection_surface_type": "unknown",
    "projection_distance_meters": None,
    "laser_to_target_geometry_notes": "",
    "intermediate_material_notes": "",
    "room_lighting_notes": "",
    "camera_fixed": None,
    "beam_path_fixed": None,
    "non_reflective_surface": None,
    "projected_region_not_saturated": None,
    "laser_pattern_type": "unknown",
    "wavelength_nm": None,
    "color_label": None,
    "rated_power_mw": None,
    "measured_power_mw": None,
    "laser_class_label": None,
    "manufacturer_model": None,
    "diffraction_optic_type": None,
    "mount_type": None,
    "cross_center_visible": None,
    "entire_cross_visible": None,
    "surface_texture_visible": None,
    "cross_rotation_degrees": None,
    "angle_of_incidence_degrees": None,
    "safety_acknowledged": False,
    "external_dataset_reference": None,
    "symbol_corpus_compared": False,
}


def default_capture_metadata() -> dict[str, Any]:
    return deepcopy(CAPTURE_PROTOCOL_DEFAULTS)


def normalize_capture_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    normalized = default_capture_metadata()
    normalized.update(dict(metadata or {}))
    footage_class = str(normalized.get("footage_class") or "other")
    normalized["footage_class"] = footage_class if footage_class in FOOTAGE_CLASSES else "other"
    pattern = str(normalized.get("laser_pattern_type") or "unknown")
    normalized["laser_pattern_type"] = pattern if pattern in LASER_PATTERN_TYPES else "unknown"
    surface = str(normalized.get("projection_surface_type") or "unknown")
    normalized["projection_surface_type"] = surface if surface in SURFACE_TYPES else "other"
    wavelength = _optional_float(normalized.get("wavelength_nm"))
    normalized["wavelength_nm"] = wavelength
    if wavelength is not None and not normalized.get("color_label"):
        normalized["color_label"] = color_for_wavelength(wavelength)
    for key in (
        "projection_distance_meters",
        "rated_power_mw",
        "measured_power_mw",
        "cross_rotation_degrees",
        "angle_of_incidence_degrees",
    ):
        normalized[key] = _optional_float(normalized.get(key))
    return normalized


def capture_protocol_warnings(metadata: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if metadata.get("footage_class") == "primary_wall_projection":
        _require_true(warnings, metadata, "camera_fixed", "camera_not_confirmed_fixed", "Confirm that the camera remained fixed during capture.")
        _require_true(warnings, metadata, "beam_path_fixed", "beam_path_not_confirmed_fixed", "Confirm that laser geometry remained fixed during capture.")
        _require_true(warnings, metadata, "non_reflective_surface", "surface_reflectivity_unknown", "Use and document a non-reflective projection target.")
        _require_true(warnings, metadata, "projected_region_not_saturated", "saturation_status_unknown", "Confirm that the projected region is not clipped or saturated.")
        if metadata.get("projection_surface_type") == "unknown":
            warnings.append(_warning("unknown_projection_surface", "Projection surface type was not recorded."))
    if metadata.get("laser_pattern_type") == "cross":
        _require_true(warnings, metadata, "cross_center_visible", "cross_center_not_confirmed", "Cross center visibility was not confirmed.")
        _require_true(warnings, metadata, "entire_cross_visible", "cross_extent_not_confirmed", "The full cross pattern was not confirmed visible.")
    if metadata.get("footage_class") == "primary_wall_projection":
        wavelength = metadata.get("wavelength_nm")
        if wavelength is None:
            warnings.append(_warning("unknown_wavelength", "Laser wavelength was not recorded."))
        elif wavelength <= 405:
            warnings.append(_warning("short_wavelength_safety", "Short-wavelength laser metadata requires extra safety review; never view the beam directly.", severity="safety"))
        if not metadata.get("laser_class_label"):
            warnings.append(_warning("unknown_laser_class", "Laser class was not recorded or independently verified."))
        if not metadata.get("safety_acknowledged"):
            warnings.append(_warning("laser_safety_not_acknowledged", "Laser safety acknowledgement is required for primary wall-projection metadata.", severity="safety"))
    return warnings


def capture_protocol_summary(captures: list[dict[str, Any]]) -> dict[str, Any]:
    footage_counts = {key: 0 for key in sorted(FOOTAGE_CLASSES)}
    pattern_counts = {key: 0 for key in sorted(LASER_PATTERN_TYPES)}
    wavelengths: list[float] = []
    warning_count = 0
    for capture in captures:
        metadata = normalize_capture_metadata(capture.get("metadata", {}))
        footage_counts[metadata["footage_class"]] = footage_counts.get(metadata["footage_class"], 0) + 1
        pattern_counts[metadata["laser_pattern_type"]] = pattern_counts.get(metadata["laser_pattern_type"], 0) + 1
        if metadata.get("wavelength_nm") is not None:
            wavelengths.append(float(metadata["wavelength_nm"]))
        warning_count += len(capture.get("provenance_warnings", []))
    return {
        "capture_count": len(captures),
        "footage_class_counts": footage_counts,
        "laser_pattern_counts": pattern_counts,
        "wavelengths_nm": sorted(set(wavelengths)),
        "warning_count": warning_count,
        "primary_wall_projection": footage_counts.get("primary_wall_projection", 0) > 0,
        "fixture_only": bool(captures) and footage_counts.get("primary_wall_projection", 0) == 0,
    }


def default_study_context() -> dict[str, Any]:
    return {
        "mode": "footage_only",
        "subjective_report_attached": False,
        "pseudonymous_session_id": None,
        "perception_notes": "",
        "confidence": None,
        "privacy_acknowledged": False,
        "ethics_review_reference": None,
    }


def normalize_study_context(context: dict[str, Any] | None) -> dict[str, Any]:
    normalized = default_study_context()
    normalized.update(dict(context or {}))
    mode = str(normalized.get("mode") or "footage_only")
    if mode not in STUDY_CONTEXT_MODES:
        raise ValueError(f"Unknown study context mode: {mode}")
    normalized["mode"] = mode
    normalized["subjective_report_attached"] = mode != "footage_only"
    if mode != "footage_only" and not normalized.get("privacy_acknowledged"):
        raise ValueError("Privacy acknowledgement is required before attaching subjective context.")
    if mode == "externally_approved_study" and not normalized.get("ethics_review_reference"):
        raise ValueError("Externally approved study context requires an ethics review reference.")
    return normalized


def color_for_wavelength(wavelength_nm: float) -> str:
    nearest = min(WAVELENGTH_PRESETS, key=lambda value: abs(float(value) - wavelength_nm))
    return WAVELENGTH_PRESETS[nearest] if abs(nearest - wavelength_nm) <= 20 else "custom"


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _require_true(
    warnings: list[dict[str, str]],
    metadata: dict[str, Any],
    field: str,
    code: str,
    message: str,
) -> None:
    if metadata.get(field) is not True:
        warnings.append(_warning(code, message))


def _warning(code: str, message: str, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}
