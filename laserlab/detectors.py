"""Detector implementations used by the blinded validation pipeline."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifacts import ensure_dir, relative_to
from .scientific import fft_spectrum_metrics, glcm_texture_metrics, speckle_contrast_metrics


@dataclass(frozen=True)
class DetectorContext:
    experiment_dir: Path
    run_dir: Path
    blind_id: str
    variant_name: str
    original_image: Any


def run_detectors(processed_image: Any, context: DetectorContext) -> dict[str, Any]:
    ocr = run_ocr(processed_image)
    components = connected_components(processed_image)
    texture = entropy_texture(processed_image)
    edge_lines = edge_line_density(processed_image)
    fft = fft_spectrum_metrics(processed_image)
    speckle = speckle_contrast_metrics(processed_image)
    glcm = glcm_texture_metrics(processed_image)
    rois = extract_candidate_rois(processed_image, context)
    structure = structure_score(ocr, components, texture, edge_lines, rois)
    return {
        "ocr": ocr,
        "connected_components": components,
        "entropy_texture": texture,
        "edge_line_density": edge_lines,
        "fft_spectrum": fft,
        "speckle_contrast": speckle,
        "texture_features": glcm,
        "candidate_rois": rois,
        "detector_family_scores": detector_family_scores(ocr, components, texture, edge_lines, fft, speckle, glcm, rois),
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
    try:
        import pytesseract
    except ImportError:
        return {"available": False, "reason": "pytesseract is not installed", "text": "", "confidence": 0.0, "boxes": []}

    config = "--oem 3 --psm 6 -l eng"
    try:
        data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)
        text = pytesseract.image_to_string(image, config=config).strip()
    except pytesseract.TesseractNotFoundError:
        return {"available": False, "reason": "tesseract executable not found", "text": "", "confidence": 0.0, "boxes": []}
    except pytesseract.TesseractError as exc:
        return {"available": False, "reason": f"tesseract error: {exc}", "text": "", "confidence": 0.0, "boxes": []}

    boxes = []
    confidences = []
    for index, raw_text in enumerate(data.get("text", [])):
        value = raw_text.strip()
        if not value:
            continue
        raw_conf = data["conf"][index]
        try:
            confidence = float(raw_conf)
        except (TypeError, ValueError):
            confidence = -1.0
        if confidence >= 0:
            confidences.append(confidence)
        boxes.append(
            {
                "text": value,
                "confidence": confidence,
                "x": int(data["left"][index]),
                "y": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
            }
        )

    return {
        "available": True,
        "text": text,
        "confidence": float(sum(confidences) / len(confidences)) if confidences else 0.0,
        "boxes": boxes,
        "word_count": len(boxes),
    }


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
        + float(fft.get("ring_energy_ratio", 0.0)) * 0.25,
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
