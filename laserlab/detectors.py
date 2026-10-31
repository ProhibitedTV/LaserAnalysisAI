"""Detector implementations used by the blinded validation pipeline."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ensure_dir, relative_to
from .ocr_adapters import OCRRequest, TesseractAdapter, run_ocr_ensemble
from .roi_detection import crop_rois, detect_code_rois, draw_roi_overlay
from .scientific import cross_pattern_metrics, fft_spectrum_metrics, glcm_texture_metrics, speckle_contrast_metrics


@dataclass(frozen=True)
class DetectorContext:
    experiment_dir: Path
    run_dir: Path
    blind_id: str
    variant_name: str
    original_image: Any


_TESSERACT_ADAPTER = TesseractAdapter()


def run_detectors(processed_image: Any, context: DetectorContext) -> dict[str, Any]:
    components = connected_components(processed_image)
    texture = entropy_texture(processed_image)
    edge_lines = edge_line_density(processed_image)
    fft = fft_spectrum_metrics(processed_image)
    speckle = speckle_contrast_metrics(processed_image)
    glcm = glcm_texture_metrics(processed_image)
    cross = cross_pattern_metrics(processed_image)
    rois, overlay_path = prepare_candidate_rois(processed_image, context, cross)
    ocr, ocr_attempts, ocr_ensemble = run_roi_ocr(processed_image, rois, context)
    structure = structure_score(ocr, components, texture, edge_lines, rois)
    return {
        "ocr": ocr,
        "ocr_attempts": ocr_attempts,
        "ocr_ensemble": ocr_ensemble,
        "connected_components": components,
        "entropy_texture": texture,
        "edge_line_density": edge_lines,
        "fft_spectrum": fft,
        "speckle_contrast": speckle,
        "texture_features": glcm,
        "cross_pattern": cross,
        "candidate_rois": rois,
        "roi_overlay_path": overlay_path,
        "detector_family_scores": detector_family_scores(ocr, components, texture, edge_lines, fft, speckle, glcm, rois, cross),
        "structure_score": structure,
    }


def to_grayscale(image: Any) -> Any:
    import cv2

    if len(image.shape) == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def binary_for_structure(image: Any) -> Any:
    import cv2

    gray = to_grayscale(image)
    if gray.max() <= 1:
        gray = (gray * 255).astype("uint8")
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def run_ocr(image: Any) -> dict[str, Any]:
    ensemble = run_ocr_ensemble(
        [_TESSERACT_ADAPTER],
        OCRRequest(image=image, roi_reference={"id": "full_frame"}),
    )
    return legacy_ocr_summary(ensemble["attempts"])


def prepare_candidate_rois(
    processed_image: Any,
    context: DetectorContext,
    cross: dict[str, Any],
    limit: int = 8,
) -> tuple[list[dict[str, Any]], str]:
    """Detect, persist, and overlay auditable ROI candidates."""

    import cv2
    import numpy as np

    raw_rois = detect_code_rois(
        processed_image,
        max_rois=limit,
        parent_variant={"name": context.variant_name},
    )
    processed_crops = crop_rois(processed_image, raw_rois)
    crop_dir = ensure_dir(context.run_dir / "candidates" / context.blind_id)
    mask_dir = ensure_dir(context.run_dir / "roi_masks" / context.blind_id)
    original_height, original_width = context.original_image.shape[:2]
    processed_height, processed_width = processed_image.shape[:2]
    scale_x = original_width / max(1, processed_width)
    scale_y = original_height / max(1, processed_height)
    records: list[dict[str, Any]] = []

    for raw, processed_crop in zip(raw_rois, processed_crops):
        processed_bbox = dict(raw["bbox"])
        original_bbox = _scale_bbox(processed_bbox, scale_x, scale_y, original_width, original_height)
        x, y, width, height = _bbox_values(original_bbox)
        original_crop = context.original_image[y:y + height, x:x + width]
        safe_id = str(raw["id"]).replace("-", "_")
        stem = f"{context.variant_name}_{safe_id}"
        crop_path = crop_dir / f"{stem}_original.png"
        processed_crop_path = crop_dir / f"{stem}_processed.png"
        mask_path = mask_dir / f"{stem}_mask.png"
        mask = np.zeros((processed_height, processed_width), dtype="uint8")
        px, py, pw, ph = _bbox_values(processed_bbox)
        mask[py:py + ph, px:px + pw] = 255
        _write_image(crop_path, original_crop)
        _write_image(processed_crop_path, processed_crop)
        _write_image(mask_path, mask)
        record = dict(raw)
        record.update(
            {
                "bbox": original_bbox,
                "processed_bbox": processed_bbox,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "area": width * height,
                "crop_path": relative_to(crop_path, context.experiment_dir),
                "processed_crop_path": relative_to(processed_crop_path, context.experiment_dir),
                "mask_path": relative_to(mask_path, context.experiment_dir),
                "mask_kind": "bounding_box",
            }
        )
        records.append(record)

    cross_records = extract_cross_rois(processed_image, context, cross)
    for cross_record in cross_records:
        original_bbox = {
            "x": int(cross_record["x"]),
            "y": int(cross_record["y"]),
            "width": int(cross_record["width"]),
            "height": int(cross_record["height"]),
        }
        processed_bbox = _scale_bbox(
            original_bbox,
            1.0 / max(scale_x, 1e-9),
            1.0 / max(scale_y, 1e-9),
            processed_width,
            processed_height,
        )
        px, py, pw, ph = _bbox_values(processed_bbox)
        processed_crop = processed_image[py:py + ph, px:px + pw]
        region_type = str(cross_record.get("region_type", "cross_region"))
        safe_region = region_type.replace("-", "_")
        stem = f"{context.variant_name}_{safe_region}"
        processed_crop_path = crop_dir / f"{stem}_processed.png"
        mask_path = mask_dir / f"{stem}_mask.png"
        mask = np.zeros((processed_height, processed_width), dtype="uint8")
        mask[py:py + ph, px:px + pw] = 255
        _write_image(processed_crop_path, processed_crop)
        _write_image(mask_path, mask)
        confidence = float(cross.get("confidence", 0.0) or 0.0)
        cross_record.update(
            {
                "id": f"cross-{safe_region}",
                "bbox": original_bbox,
                "processed_bbox": processed_bbox,
                "detector_reasons": ["cross_pattern", region_type],
                "component_scores": {
                    "structure_density": round(confidence, 6),
                    "local_contrast": 0.0,
                    "persistence": 0.0,
                    "proposal_support": 1.0,
                    "edge_density": 0.0,
                },
                "score": round(confidence, 6),
                "parent_variant": {
                    "name": context.variant_name,
                    "width": processed_width,
                    "height": processed_height,
                },
                "fallback": False,
                "processed_crop_path": relative_to(processed_crop_path, context.experiment_dir),
                "mask_path": relative_to(mask_path, context.experiment_dir),
                "mask_kind": "bounding_box",
            }
        )
        records.append(cross_record)

    overlay_records = [{"bbox": item["processed_bbox"]} for item in records]
    overlay = draw_roi_overlay(processed_image, overlay_records)
    overlay_dir = ensure_dir(context.run_dir / "roi_overlays")
    overlay_path = overlay_dir / f"{context.blind_id}_{context.variant_name}.png"
    _write_image(overlay_path, overlay)
    return records, relative_to(overlay_path, context.experiment_dir)


def run_roi_ocr(
    processed_image: Any,
    rois: list[dict[str, Any]],
    context: DetectorContext,
    limit: int = 3,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    """Run OCR against explicit ROI references and preserve every attempt."""

    ordered = sorted(
        rois,
        key=lambda item: (
            bool(item.get("fallback")),
            -float(item.get("score", 0.0) or 0.0),
            str(item.get("id", "")),
        ),
    )[:limit]
    attempts: list[dict[str, Any]] = []
    roi_results: list[dict[str, Any]] = []
    for roi in ordered:
        x, y, width, height = _bbox_values(roi["processed_bbox"])
        crop = processed_image[y:y + height, x:x + width]
        reference_id = "full_frame" if roi.get("fallback") else str(roi["id"])
        reference = {
            "id": reference_id,
            "bbox": dict(roi["bbox"]),
            "processed_bbox": dict(roi["processed_bbox"]),
            "crop_path": roi.get("crop_path"),
            "processed_crop_path": roi.get("processed_crop_path"),
        }
        ensemble = run_ocr_ensemble(
            [_TESSERACT_ADAPTER],
            OCRRequest(
                image=crop,
                roi_reference=reference,
                preprocessing_metadata={"variant": context.variant_name},
                timeout_seconds=30.0,
                language="eng",
            ),
        )
        attempts.extend(ensemble["attempts"])
        roi_results.append(
            {
                "roi_reference": reference,
                "agreement": ensemble["agreement"],
            }
        )
        if ensemble["attempts"] and not any(item.get("available") for item in ensemble["attempts"]):
            break

    ensemble_summary = {
        "schema_version": "1.0",
        "agreement_scope": "per_roi",
        "engine_ids": sorted({str(item.get("engine_id", "")) for item in attempts}),
        "attempt_count": len(attempts),
        "roi_results": roi_results,
    }
    return legacy_ocr_summary(attempts), attempts, ensemble_summary


def legacy_ocr_summary(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Retain the v0.7 OCR summary while richer attempts remain available."""

    available = [item for item in attempts if item.get("available")]
    successful = [
        item
        for item in available
        if item.get("failure_reason") is None and isinstance(item.get("text"), str) and item.get("text", "").strip()
    ]
    best = max(
        successful,
        key=lambda item: (float(item.get("confidence") or 0.0), len(str(item.get("text") or ""))),
        default=None,
    )
    if best is not None:
        boxes = list(best.get("word_boxes", []))
        return {
            "available": True,
            "text": str(best.get("text") or ""),
            "confidence": round(float(best.get("confidence") or 0.0) * 100.0, 6),
            "boxes": boxes,
            "character_boxes": list(best.get("character_boxes", [])),
            "word_count": len(boxes),
            "engine": best.get("engine_id"),
            "roi_reference": best.get("roi_reference"),
        }
    reason = next((str(item.get("failure_reason")) for item in attempts if item.get("failure_reason")), None)
    return {
        "available": bool(available),
        "reason": reason or ("no OCR attempts" if not attempts else None),
        "text": "",
        "confidence": 0.0,
        "boxes": [],
        "character_boxes": [],
        "word_count": 0,
        "engine": attempts[0].get("engine_id") if attempts else None,
        "roi_reference": attempts[0].get("roi_reference") if attempts else {"id": "full_frame"},
    }


def _bbox_values(bbox: dict[str, Any]) -> tuple[int, int, int, int]:
    return int(bbox["x"]), int(bbox["y"]), int(bbox["width"]), int(bbox["height"])


def _scale_bbox(
    bbox: dict[str, Any],
    scale_x: float,
    scale_y: float,
    limit_width: int,
    limit_height: int,
) -> dict[str, int]:
    x, y, width, height = _bbox_values(bbox)
    x0 = max(0, min(limit_width - 1, int(round(x * scale_x))))
    y0 = max(0, min(limit_height - 1, int(round(y * scale_y))))
    x1 = max(x0 + 1, min(limit_width, int(round((x + width) * scale_x))))
    y1 = max(y0 + 1, min(limit_height, int(round((y + height) * scale_y))))
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def _write_image(path: Path, image: Any) -> None:
    import cv2

    if image is None or getattr(image, "size", 0) == 0 or not cv2.imwrite(str(path), image):
        raise RuntimeError(f"Failed to write detector artifact: {path}")


def connected_components(image: Any) -> dict[str, Any]:
    import cv2
    import numpy as np

    binary = binary_for_structure(image)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(255 - binary, connectivity=8)
    components = []
    height, width = binary.shape[:2]
    image_area = max(1, height * width)
    for label in range(1, num_labels):
        x, y, w, h, area = [int(value) for value in stats[label]]
        if area < 4:
            continue
        aspect = w / max(1, h)
        fill_ratio = area / max(1, w * h)
        text_like = 0.15 <= fill_ratio <= 0.85 and 0.1 <= aspect <= 10.0 and area / image_area < 0.2
        components.append(
            {
                "x": x,
                "y": y,
                "width": w,
                "height": h,
                "area": area,
                "aspect_ratio": aspect,
                "fill_ratio": fill_ratio,
                "text_like": text_like,
            }
        )

    areas = [item["area"] for item in components]
    text_like_count = sum(1 for item in components if item["text_like"])
    return {
        "component_count": len(components),
        "text_like_count": text_like_count,
        "median_area": float(np.median(areas)) if areas else 0.0,
        "components": sorted(components, key=lambda item: item["area"], reverse=True)[:50],
    }


def entropy_texture(image: Any) -> dict[str, Any]:
    import cv2
    import numpy as np

    gray = to_grayscale(image)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    total = float(hist.sum())
    probabilities = hist / total if total else hist
    entropy = -float(sum(p * math.log2(p) for p in probabilities if p > 0))
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {
        "entropy": entropy,
        "contrast_std": float(np.std(gray)),
        "laplacian_variance": laplacian_variance,
    }


def edge_line_density(image: Any) -> dict[str, Any]:
    import cv2
    import numpy as np

    gray = to_grayscale(image)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges) / max(1, edges.size))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=50,
        minLineLength=max(10, min(gray.shape[:2]) // 20),
        maxLineGap=8,
    )
    lengths = []
    if lines is not None:
        for line in lines[:100]:
            x1, y1, x2, y2 = [int(value) for value in line[0]]
            lengths.append(math.hypot(x2 - x1, y2 - y1))
    return {
        "edge_density": edge_density,
        "line_count": len(lengths),
        "mean_line_length": float(sum(lengths) / len(lengths)) if lengths else 0.0,
    }


def extract_candidate_rois(image: Any, context: DetectorContext, limit: int = 5) -> list[dict[str, Any]]:
    import cv2

    binary = binary_for_structure(image)
    contours, _ = cv2.findContours(255 - binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    height, width = binary.shape[:2]
    image_area = max(1, height * width)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < 25 or area > image_area * 0.5:
            continue
        aspect = w / max(1, h)
        if 0.05 <= aspect <= 20.0:
            boxes.append((x, y, w, h, area))

    boxes = sorted(boxes, key=lambda item: item[4], reverse=True)[:limit]
    crop_dir = ensure_dir(context.run_dir / "candidates" / context.blind_id)
    records = []
    original_height, original_width = context.original_image.shape[:2]
    scale_x = original_width / max(1, width)
    scale_y = original_height / max(1, height)
    for index, (x, y, w, h, area) in enumerate(boxes):
        pad = 4
        x0 = max(0, int((x - pad) * scale_x))
        y0 = max(0, int((y - pad) * scale_y))
        x1 = min(original_width, int((x + w + pad) * scale_x))
        y1 = min(original_height, int((y + h + pad) * scale_y))
        if x1 <= x0 or y1 <= y0:
            continue
        crop = context.original_image[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        crop_path = crop_dir / f"{context.variant_name}_{index:02d}.png"
        cv2.imwrite(str(crop_path), crop)
        records.append(
            {
                "x": int(x0),
                "y": int(y0),
                "width": int(x1 - x0),
                "height": int(y1 - y0),
                "area": int(area),
                "crop_path": relative_to(crop_path, context.experiment_dir),
            }
        )
    return records


def extract_cross_rois(image: Any, context: DetectorContext, cross: dict[str, Any]) -> list[dict[str, Any]]:
    import cv2

    if not cross.get("detected") or cross.get("center_x") is None or cross.get("center_y") is None:
        return []
    processed_height, processed_width = image.shape[:2]
    original_height, original_width = context.original_image.shape[:2]
    scale_x = original_width / max(1, processed_width)
    scale_y = original_height / max(1, processed_height)
    cx = int(float(cross["center_x"]) * scale_x)
    cy = int(float(cross["center_y"]) * scale_y)
    half_band = max(5, int(min(original_width, original_height) * 0.04))
    half_center = max(10, int(min(original_width, original_height) * 0.10))
    regions = [
        ("cross_center", cx - half_center, cy - half_center, cx + half_center, cy + half_center),
        ("horizontal_arm", 0, cy - half_band, original_width, cy + half_band),
        ("vertical_arm", cx - half_band, 0, cx + half_band, original_height),
    ]
    crop_dir = ensure_dir(context.run_dir / "candidates" / context.blind_id)
    records = []
    for index, (region_type, x0, y0, x1, y1) in enumerate(regions):
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(original_width, x1), min(original_height, y1)
        crop = context.original_image[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        crop_path = crop_dir / f"{context.variant_name}_cross_{index:02d}.png"
        cv2.imwrite(str(crop_path), crop)
        records.append(
            {
                "x": x0,
                "y": y0,
                "width": x1 - x0,
                "height": y1 - y0,
                "area": (x1 - x0) * (y1 - y0),
                "region_type": region_type,
                "crop_path": relative_to(crop_path, context.experiment_dir),
            }
        )
    return records


def structure_score(
    ocr: dict[str, Any],
    components: dict[str, Any],
    texture: dict[str, Any],
    edge_lines: dict[str, Any],
    rois: list[dict[str, Any]],
) -> float:
    ocr_words = float(ocr.get("word_count", len(ocr.get("boxes", []))) or 0)
    ocr_conf = max(0.0, float(ocr.get("confidence", 0.0) or 0.0)) / 100.0
    ocr_score = min(1.0, (ocr_words / 8.0) * 0.6 + ocr_conf * 0.4) if ocr.get("available") else 0.0

    component_score = min(1.0, float(components.get("text_like_count", 0)) / 30.0)
    entropy_score = min(1.0, max(0.0, float(texture.get("entropy", 0.0)) / 8.0))
    edge_score = min(1.0, float(edge_lines.get("edge_density", 0.0)) * 8.0)
    line_score = min(1.0, float(edge_lines.get("line_count", 0)) / 30.0)
    roi_score = min(1.0, len(rois) / 5.0)

    score = (
        ocr_score * 0.25
        + component_score * 0.20
        + entropy_score * 0.15
        + edge_score * 0.20
        + line_score * 0.10
        + roi_score * 0.10
    )
    return round(float(score), 6)


def detector_family_scores(
    ocr: dict[str, Any],
    components: dict[str, Any],
    texture: dict[str, Any],
    edge_lines: dict[str, Any],
    fft: dict[str, Any],
    speckle: dict[str, Any],
    glcm: dict[str, Any],
    rois: list[dict[str, Any]],
    cross: dict[str, Any] | None = None,
) -> dict[str, float]:
    symbol = 0.0
    if ocr.get("available"):
        words = float(ocr.get("word_count", len(ocr.get("boxes", []))) or 0)
        conf = max(0.0, float(ocr.get("confidence", 0.0) or 0.0)) / 100.0
        symbol = min(1.0, (words / 8.0) * 0.6 + conf * 0.4)
    symbol = max(symbol, min(1.0, float(components.get("text_like_count", 0)) / 40.0))

    diffraction = min(
        1.0,
        float(fft.get("peak_prominence", 0.0)) / 8.0 * 0.75
        + float(fft.get("ring_energy_ratio", 0.0)) * 0.15
        + float((cross or {}).get("confidence", 0.0)) * 0.10,
    )
    speckle_score = min(1.0, float(speckle.get("spatial_contrast_mean", 0.0)) * 2.0)
    texture_score = min(
        1.0,
        float(texture.get("entropy", 0.0)) / 8.0 * 0.35
        + float(edge_lines.get("edge_density", 0.0)) * 4.0 * 0.25
        + min(1.0, float(glcm.get("contrast", 0.0)) / 24.0) * 0.25
        + min(1.0, len(rois) / 5.0) * 0.15,
    )
    return {
        "symbol": round(float(symbol), 6),
        "diffraction": round(float(diffraction), 6),
        "speckle": round(float(speckle_score), 6),
        "texture": round(float(texture_score), 6),
    }
