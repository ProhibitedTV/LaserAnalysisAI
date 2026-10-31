"""Deterministic, explainable region proposals for code-like image structure.

The detector deliberately does not attempt to recognize symbols.  It proposes
regions worth sending to downstream detectors while preserving the reasons and
component scores that caused each proposal to survive.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import cv2
import numpy as np


DEFAULT_SCORE_THRESHOLD = 0.52


def detect_code_rois(
    image: Any,
    max_rois: int = 8,
    *,
    persistence: Any | None = None,
    parent_variant: Mapping[str, Any] | str | None = None,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Return JSON-safe, ranked regions containing code-like structure.

    ``persistence`` may be a scalar confidence or a heat map aligned with the
    image.  It is optional: when omitted, its component is reported as ``0``
    and the other score weights are rebalanced.  ``parent_variant`` is copied
    into every result so callers can trace a crop back to a preprocessing
    variant without exposing source labels.
    """

    if max_rois < 1:
        raise ValueError("max_rois must be at least 1")
    gray = _as_gray_uint8(image)
    height, width = gray.shape
    if height == 0 or width == 0:
        raise ValueError("image must not be empty")

    parent = _parent_metadata(parent_variant, width, height)
    persistence_map, has_persistence = _normalize_persistence(persistence, gray.shape)
    proposals: list[dict[str, Any]] = []
    proposals.extend(_component_proposals(gray))
    proposals.extend(_edge_density_proposals(gray))
    proposals.extend(_texture_band_proposals(gray))
    proposals.extend(_grid_proposals(gray))
    proposals = _merge_near_identical_proposals(proposals)

    scored = [
        _score_proposal(gray, proposal, persistence_map, has_persistence, parent)
        for proposal in proposals
    ]
    surviving = [item for item in scored if item["score"] >= float(score_threshold)]
    selected = non_max_suppression(surviving, max_rois=max_rois)
    if not selected:
        return [_fallback_record(gray, persistence_map, has_persistence, parent)]

    records: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        record = dict(item)
        record["id"] = f"roi-{index:03d}"
        records.append(record)
    return records


def non_max_suppression(
    candidates: list[dict[str, Any]],
    *,
    iou_threshold: float = 0.35,
    max_rois: int = 8,
) -> list[dict[str, Any]]:
    """Suppress overlapping candidates using a stable, deterministic order."""

    if not 0.0 <= iou_threshold <= 1.0:
        raise ValueError("iou_threshold must be between 0 and 1")
    if max_rois < 1:
        return []
    ordered = sorted(candidates, key=_candidate_sort_key)
    kept: list[dict[str, Any]] = []
    for candidate in ordered:
        bbox = _bbox_tuple(candidate["bbox"])
        if any(_intersection_over_union(bbox, _bbox_tuple(item["bbox"])) > iou_threshold for item in kept):
            continue
        kept.append(candidate)
        if len(kept) >= max_rois:
            break
    return kept


def draw_roi_overlay(
    image: Any,
    rois: list[Mapping[str, Any]],
    *,
    color: tuple[int, int, int] = (0, 255, 255),
    thickness: int = 2,
) -> np.ndarray:
    """Return a BGR copy with ROI rectangles and ranks drawn in memory."""

    source = np.asarray(image)
    if source.ndim == 2:
        overlay = cv2.cvtColor(_as_gray_uint8(source), cv2.COLOR_GRAY2BGR)
    elif source.ndim == 3 and source.shape[2] == 4:
        overlay = cv2.cvtColor(source.astype(np.uint8), cv2.COLOR_BGRA2BGR)
    elif source.ndim == 3 and source.shape[2] == 3:
        overlay = source.astype(np.uint8, copy=True)
    else:
        raise ValueError("image must be grayscale, BGR, or BGRA")

    for index, roi in enumerate(rois, start=1):
        x, y, width, height = _bbox_tuple(roi["bbox"])
        cv2.rectangle(overlay, (x, y), (x + width - 1, y + height - 1), color, thickness)
        cv2.putText(
            overlay,
            str(index),
            (x + 3, min(overlay.shape[0] - 3, y + 14)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            max(1, thickness),
            cv2.LINE_AA,
        )
    return overlay


def crop_rois(image: Any, rois: list[Mapping[str, Any]]) -> list[np.ndarray]:
    """Return in-memory copies of the requested crops in ROI order."""

    source = np.asarray(image)
    if source.ndim not in (2, 3) or source.size == 0:
        raise ValueError("image must be a non-empty image array")
    image_height, image_width = source.shape[:2]
    crops: list[np.ndarray] = []
    for roi in rois:
        x, y, width, height = _bbox_tuple(roi["bbox"])
        x2 = min(image_width, x + width)
        y2 = min(image_height, y + height)
        crops.append(source[max(0, y):y2, max(0, x):x2].copy())
    return crops


def _as_gray_uint8(image: Any) -> np.ndarray:
    array = np.asarray(image)
    if array.size == 0:
        raise ValueError("image must not be empty")
    if array.ndim == 2:
        gray = array
    elif array.ndim == 3 and array.shape[2] == 3:
        gray = cv2.cvtColor(array.astype(np.uint8), cv2.COLOR_BGR2GRAY)
    elif array.ndim == 3 and array.shape[2] == 4:
        gray = cv2.cvtColor(array.astype(np.uint8), cv2.COLOR_BGRA2GRAY)
    else:
        raise ValueError("image must be grayscale, BGR, or BGRA")
    if gray.dtype == np.uint8:
        return gray.copy()
    finite = np.nan_to_num(gray.astype(np.float32), nan=0.0, posinf=255.0, neginf=0.0)
    if finite.size and float(finite.max()) <= 1.0 and float(finite.min()) >= 0.0:
        finite *= 255.0
    return np.clip(finite, 0.0, 255.0).astype(np.uint8)


def _parent_metadata(parent_variant: Mapping[str, Any] | str | None, width: int, height: int) -> dict[str, Any]:
    if parent_variant is None:
        metadata: dict[str, Any] = {"name": "original"}
    elif isinstance(parent_variant, str):
        metadata = {"name": parent_variant}
    elif isinstance(parent_variant, Mapping):
        metadata = {str(key): _json_scalar(value) for key, value in parent_variant.items()}
    else:
        raise TypeError("parent_variant must be a mapping, string, or None")
    metadata["width"] = int(width)
    metadata["height"] = int(height)
    return metadata


def _normalize_persistence(persistence: Any | None, shape: tuple[int, int]) -> tuple[np.ndarray, bool]:
    if persistence is None:
        return np.zeros(shape, dtype=np.float32), False
    if np.isscalar(persistence):
        value = float(np.clip(float(persistence), 0.0, 1.0))
        return np.full(shape, value, dtype=np.float32), True
    values = np.asarray(persistence, dtype=np.float32)
    if values.ndim == 3:
        values = values.mean(axis=2)
    if values.ndim != 2 or values.size == 0:
        raise ValueError("persistence must be a scalar or non-empty 2D heat map")
    if values.shape != shape:
        values = cv2.resize(values, (shape[1], shape[0]), interpolation=cv2.INTER_AREA)
    values = np.nan_to_num(values, nan=0.0, posinf=1.0, neginf=0.0)
    maximum = float(values.max())
    minimum = float(values.min())
    if minimum < 0.0 or maximum > 1.0:
        values = (values - minimum) / max(1e-6, maximum - minimum)
    return np.clip(values, 0.0, 1.0).astype(np.float32), True


def _component_proposals(gray: np.ndarray) -> list[dict[str, Any]]:
    height, width = gray.shape
    image_area = height * width
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, bright = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    masks = [bright, cv2.bitwise_not(bright)]
    proposals: list[dict[str, Any]] = []
    for mask in masks:
        foreground = float(np.count_nonzero(mask) / max(1, mask.size))
        if not 0.005 <= foreground <= 0.65:
            continue
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        glyphs: list[tuple[int, int, int, int]] = []
        for contour in contours:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            area = float(cv2.contourArea(contour))
            box_area = box_width * box_height
            aspect = box_width / max(1.0, box_height)
            fill = area / max(1.0, box_area)
            if (
                8 <= box_area <= image_area * 0.04
                and 3 <= box_width <= width * 0.28
                and 4 <= box_height <= height * 0.28
                and 0.12 <= aspect <= 4.5
                and 0.06 <= fill <= 0.95
            ):
                glyphs.append((x, y, box_width, box_height))
        proposals.extend(_group_glyph_rows(glyphs, width, height))
    return proposals


def _group_glyph_rows(
    glyphs: list[tuple[int, int, int, int]], image_width: int, image_height: int
) -> list[dict[str, Any]]:
    if len(glyphs) < 3:
        return []
    glyphs = sorted(glyphs, key=lambda box: (box[1] + box[3] / 2.0, box[0], box[2], box[3]))
    median_height = float(np.median([box[3] for box in glyphs]))
    rows: list[list[tuple[int, int, int, int]]] = []
    for box in glyphs:
        center_y = box[1] + box[3] / 2.0
        matching = None
        for row in rows:
            row_center = float(np.median([item[1] + item[3] / 2.0 for item in row]))
            row_height = float(np.median([item[3] for item in row]))
            if abs(center_y - row_center) <= max(4.0, 0.7 * max(median_height, row_height)):
                matching = row
                break
        if matching is None:
            rows.append([box])
        else:
            matching.append(box)

    proposals: list[dict[str, Any]] = []
    for row in rows:
        ordered = sorted(row, key=lambda box: box[0])
        clusters: list[list[tuple[int, int, int, int]]] = []
        for box in ordered:
            if not clusters:
                clusters.append([box])
                continue
            previous = clusters[-1][-1]
            gap = box[0] - (previous[0] + previous[2])
            typical_height = float(np.median([item[3] for item in clusters[-1]] + [box[3]]))
            if gap <= max(8.0, typical_height * 2.5):
                clusters[-1].append(box)
            else:
                clusters.append([box])
        for cluster in clusters:
            if len(cluster) < 3:
                continue
            heights = np.asarray([item[3] for item in cluster], dtype=np.float32)
            centers = np.asarray([item[1] + item[3] / 2.0 for item in cluster], dtype=np.float32)
            size_consistency = 1.0 - min(1.0, float(heights.std()) / max(1.0, float(heights.mean())))
            alignment = 1.0 - min(1.0, float(centers.std()) / max(1.0, float(heights.mean())))
            if size_consistency < 0.35 or alignment < 0.30:
                continue
            bbox = _union_boxes(cluster, image_width, image_height, padding=max(3, int(np.median(heights) * 0.35)))
            proposals.append(
                {
                    "bbox": bbox,
                    "reasons": {"connected_components", "repeated_glyph_contours"},
                    "proposal_metrics": {
                        "glyph_count": len(cluster),
                        "glyph_size_consistency": size_consistency,
                        "glyph_alignment": alignment,
                    },
                }
            )
    return proposals


def _edge_density_proposals(gray: np.ndarray) -> list[dict[str, Any]]:
    height, width = gray.shape
    image_area = height * width
    median = float(np.median(gray))
    lower = int(max(20, 0.66 * median))
    upper = int(min(240, max(lower + 30, 1.33 * median)))
    edges = cv2.Canny(gray, lower, upper)
    kernel_width = max(3, min(11, width // 40))
    kernel_height = max(3, min(7, height // 60))
    joined = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((kernel_height, kernel_width), np.uint8), iterations=2)
    joined = cv2.dilate(joined, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    proposals: list[dict[str, Any]] = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area = box_width * box_height
        if not image_area * 0.004 <= area <= image_area * 0.65:
            continue
        region_edges = edges[y:y + box_height, x:x + box_width]
        density = float(np.count_nonzero(region_edges) / max(1, region_edges.size))
        if 0.018 <= density <= 0.34:
            proposals.append(
                {
                    "bbox": _padded_box((x, y, box_width, box_height), width, height, 4),
                    "reasons": {"line_edge_density"},
                    "proposal_metrics": {"edge_density": density},
                }
            )
    return proposals


def _texture_band_proposals(gray: np.ndarray) -> list[dict[str, Any]]:
    height, width = gray.shape
    image_area = height * width
    laplacian = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    local_energy = cv2.blur(laplacian, (max(5, width // 32) | 1, max(5, height // 32) | 1))
    global_mean = float(local_energy.mean())
    global_std = float(local_energy.std())
    if global_mean < 0.75 or global_std < 0.25:
        return []
    threshold = max(float(np.percentile(local_energy, 82.0)), global_mean + 0.65 * global_std)
    mask = np.where(local_energy >= threshold, 255, 0).astype(np.uint8)
    horizontal = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, max(5, width // 24)), np.uint8), iterations=1)
    vertical = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((max(5, height // 24), 3), np.uint8), iterations=1)
    combined = cv2.bitwise_or(horizontal, vertical)
    contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    proposals: list[dict[str, Any]] = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area = box_width * box_height
        if not image_area * 0.006 <= area <= image_area * 0.55:
            continue
        region_energy = float(local_energy[y:y + box_height, x:x + box_width].mean())
        concentration = region_energy / max(1e-6, global_mean)
        if concentration >= 1.18:
            proposals.append(
                {
                    "bbox": _padded_box((x, y, box_width, box_height), width, height, 5),
                    "reasons": {"high_frequency_texture_band"},
                    "proposal_metrics": {"frequency_concentration": min(3.0, concentration) / 3.0},
                }
            )
    return proposals


def _grid_proposals(gray: np.ndarray) -> list[dict[str, Any]]:
    height, width = gray.shape
    edges = cv2.Canny(gray, 40, 140)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180.0,
        threshold=max(18, min(height, width) // 10),
        minLineLength=max(12, min(height, width) // 5),
        maxLineGap=max(4, min(height, width) // 30),
    )
    if lines is None:
        return []
    horizontal: list[tuple[int, int, int, int]] = []
    vertical: list[tuple[int, int, int, int]] = []
    for raw in lines[:400]:
        x1, y1, x2, y2 = (int(value) for value in raw[0])
        angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180.0
        length = math.hypot(x2 - x1, y2 - y1)
        if (angle <= 10.0 or angle >= 170.0) and length >= width * 0.18:
            horizontal.append((x1, y1, x2, y2))
        elif 80.0 <= angle <= 100.0 and length >= height * 0.18:
            vertical.append((x1, y1, x2, y2))
    horizontal = _unique_axis_lines(horizontal, horizontal_axis=True)
    vertical = _unique_axis_lines(vertical, horizontal_axis=False)
    if len(horizontal) < 3 or len(vertical) < 3:
        return []

    points = [(x, y) for line in horizontal + vertical for x, y in ((line[0], line[1]), (line[2], line[3]))]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x1, x2 = max(0, min(xs)), min(width, max(xs) + 1)
    y1, y2 = max(0, min(ys)), min(height, max(ys) + 1)
    if (x2 - x1) * (y2 - y1) > width * height * 0.80:
        inset_x = int(width * 0.02)
        inset_y = int(height * 0.02)
        x1, y1, x2, y2 = inset_x, inset_y, width - inset_x, height - inset_y
    regularity = 0.5 * (
        _spacing_regularity([int((line[1] + line[3]) / 2) for line in horizontal])
        + _spacing_regularity([int((line[0] + line[2]) / 2) for line in vertical])
    )
    if regularity < 0.25:
        return []
    return [
        {
            "bbox": _padded_box((x1, y1, x2 - x1, y2 - y1), width, height, 4),
            "reasons": {"grid_like_arrangement", "line_edge_density"},
            "proposal_metrics": {
                "horizontal_line_count": len(horizontal),
                "vertical_line_count": len(vertical),
                "grid_regularity": regularity,
            },
        }
    ]


def _score_proposal(
    gray: np.ndarray,
    proposal: dict[str, Any],
    persistence_map: np.ndarray,
    has_persistence: bool,
    parent: dict[str, Any],
) -> dict[str, Any]:
    x, y, width, height = proposal["bbox"]
    region = gray[y:y + height, x:x + width]
    edges = cv2.Canny(region, 40, 140)
    edge_density = float(np.count_nonzero(edges) / max(1, edges.size))
    edge_quality = _band_score(edge_density, 0.018, 0.08, 0.30)

    p05, p95 = np.percentile(region, [5, 95]) if region.size else (0.0, 0.0)
    robust_range = float((p95 - p05) / 255.0)
    contrast_std = float(np.std(region) / 80.0)
    local_contrast = min(1.0, 0.65 * robust_range + 0.35 * min(1.0, contrast_std))

    metrics = proposal.get("proposal_metrics", {})
    glyph_quality = min(
        1.0,
        min(1.0, float(metrics.get("glyph_count", 0)) / 7.0)
        * float(metrics.get("glyph_size_consistency", 0.0))
        * float(metrics.get("glyph_alignment", 0.0)),
    )
    grid_quality = float(metrics.get("grid_regularity", 0.0))
    texture_quality = float(metrics.get("frequency_concentration", 0.0))
    reasons = sorted(str(reason) for reason in proposal.get("reasons", set()))
    reason_support = min(1.0, len(reasons) / 3.0)
    # Dense white noise can accidentally form short, similarly sized contour
    # runs.  Require those semantic cues to live in a plausible edge-density
    # band instead of treating contour alignment as sufficient on its own.
    semantic_structure = max(glyph_quality, grid_quality) * edge_quality
    structure_density = min(
        1.0,
        0.25 * edge_quality
        + 0.42 * semantic_structure
        + 0.18 * texture_quality
        + 0.15 * reason_support,
    )
    persistence_score = float(
        persistence_map[y:y + height, x:x + width].mean()
    ) if has_persistence else 0.0
    if has_persistence:
        total = 0.48 * structure_density + 0.24 * local_contrast + 0.14 * reason_support + 0.14 * persistence_score
    else:
        total = 0.55 * structure_density + 0.30 * local_contrast + 0.15 * reason_support

    return {
        "bbox": {"x": int(x), "y": int(y), "width": int(width), "height": int(height)},
        "detector_reasons": reasons,
        "component_scores": {
            "structure_density": round(float(structure_density), 6),
            "local_contrast": round(float(local_contrast), 6),
            "persistence": round(float(persistence_score), 6),
            "proposal_support": round(float(reason_support), 6),
            "edge_density": round(float(edge_density), 6),
        },
        "score": round(float(np.clip(total, 0.0, 1.0)), 6),
        "parent_variant": dict(parent),
        "fallback": False,
    }


def _fallback_record(
    gray: np.ndarray,
    persistence_map: np.ndarray,
    has_persistence: bool,
    parent: dict[str, Any],
) -> dict[str, Any]:
    height, width = gray.shape
    robust_range = float((np.percentile(gray, 95) - np.percentile(gray, 5)) / 255.0)
    persistence_score = float(persistence_map.mean()) if has_persistence else 0.0
    return {
        "id": "roi-000-full-frame",
        "bbox": {"x": 0, "y": 0, "width": int(width), "height": int(height)},
        "detector_reasons": ["full_frame_fallback"],
        "component_scores": {
            "structure_density": 0.0,
            "local_contrast": round(robust_range, 6),
            "persistence": round(persistence_score, 6),
            "proposal_support": 0.0,
            "edge_density": 0.0,
        },
        "score": 0.0,
        "parent_variant": dict(parent),
        "fallback": True,
    }


def _merge_near_identical_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for proposal in sorted(proposals, key=lambda item: (*item["bbox"], sorted(item["reasons"]))):
        match = next(
            (
                item
                for item in merged
                if _intersection_over_union(tuple(proposal["bbox"]), tuple(item["bbox"])) >= 0.78
            ),
            None,
        )
        if match is None:
            merged.append(
                {
                    "bbox": tuple(int(value) for value in proposal["bbox"]),
                    "reasons": set(proposal["reasons"]),
                    "proposal_metrics": dict(proposal.get("proposal_metrics", {})),
                }
            )
            continue
        match["reasons"].update(proposal["reasons"])
        for key, value in proposal.get("proposal_metrics", {}).items():
            if isinstance(value, (int, float)):
                match["proposal_metrics"][key] = max(float(value), float(match["proposal_metrics"].get(key, 0.0)))
    return merged


def _unique_axis_lines(
    lines: list[tuple[int, int, int, int]], *, horizontal_axis: bool
) -> list[tuple[int, int, int, int]]:
    ordered = sorted(
        lines,
        key=lambda line: (
            int((line[1] + line[3]) / 2) if horizontal_axis else int((line[0] + line[2]) / 2),
            -int(math.hypot(line[2] - line[0], line[3] - line[1])),
        ),
    )
    unique: list[tuple[int, int, int, int]] = []
    for line in ordered:
        position = (line[1] + line[3]) / 2.0 if horizontal_axis else (line[0] + line[2]) / 2.0
        if all(
            abs(position - ((item[1] + item[3]) / 2.0 if horizontal_axis else (item[0] + item[2]) / 2.0)) >= 4.0
            for item in unique
        ):
            unique.append(line)
    return unique


def _spacing_regularity(positions: list[int]) -> float:
    values = sorted(set(positions))
    if len(values) < 3:
        return 0.0
    gaps = np.diff(np.asarray(values, dtype=np.float32))
    if float(gaps.mean()) <= 0.0:
        return 0.0
    return float(1.0 - min(1.0, float(gaps.std() / gaps.mean())))


def _union_boxes(
    boxes: list[tuple[int, int, int, int]], width: int, height: int, *, padding: int
) -> tuple[int, int, int, int]:
    x1 = min(box[0] for box in boxes)
    y1 = min(box[1] for box in boxes)
    x2 = max(box[0] + box[2] for box in boxes)
    y2 = max(box[1] + box[3] for box in boxes)
    return _padded_box((x1, y1, x2 - x1, y2 - y1), width, height, padding)


def _padded_box(
    bbox: tuple[int, int, int, int], image_width: int, image_height: int, padding: int
) -> tuple[int, int, int, int]:
    x, y, width, height = bbox
    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(image_width, x + width + padding)
    y2 = min(image_height, y + height + padding)
    return int(x1), int(y1), int(max(1, x2 - x1)), int(max(1, y2 - y1))


def _band_score(value: float, minimum: float, ideal: float, maximum: float) -> float:
    if value <= minimum or value >= maximum:
        return 0.0
    if value <= ideal:
        return (value - minimum) / max(1e-9, ideal - minimum)
    return (maximum - value) / max(1e-9, maximum - ideal)


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    x, y, width, height = _bbox_tuple(candidate["bbox"])
    return (-float(candidate.get("score", 0.0)), y, x, -(width * height), width, height)


def _bbox_tuple(bbox: Any) -> tuple[int, int, int, int]:
    if isinstance(bbox, Mapping):
        return int(bbox["x"]), int(bbox["y"]), int(bbox["width"]), int(bbox["height"])
    if len(bbox) != 4:
        raise ValueError("bbox must contain x, y, width, and height")
    return tuple(int(value) for value in bbox)  # type: ignore[return-value]


def _intersection_over_union(
    first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = aw * ah + bw * bh - intersection
    return float(intersection / union) if union > 0 else 0.0


def _json_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    return str(value)
