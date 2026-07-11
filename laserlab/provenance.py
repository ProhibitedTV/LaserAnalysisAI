"""Media metadata inspection and capture-quality warnings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .artifacts import list_images


RECOMMENDED_CAPTURE_FIELDS = {
    "camera": "Camera/device was not recorded.",
    "exposure": "Exposure settings were not recorded.",
    "focus_mode": "Focus mode was not recorded.",
    "compression_history": "Compression history was not recorded.",
}


def inspect_source(source: Path, kind: str) -> dict[str, Any]:
    source = Path(source)
    base = {
        "file_size_bytes": source.stat().st_size if source.is_file() else None,
        "source_kind": kind,
    }
    if kind == "video":
        return {**base, **_inspect_video(source)}
    return {**base, **_inspect_image_set(source)}


def provenance_warnings(capture_metadata: dict[str, Any], media: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for field, message in RECOMMENDED_CAPTURE_FIELDS.items():
        if not capture_metadata.get(field):
            warnings.append({"code": f"missing_{field}", "severity": "warning", "message": message})
    if not media.get("width") or not media.get("height"):
        warnings.append({"code": "unknown_resolution", "severity": "warning", "message": "Media resolution could not be determined."})
    if media.get("source_kind") == "video" and not media.get("fps"):
        warnings.append({"code": "unknown_fps", "severity": "warning", "message": "Video frame rate could not be determined."})
    if capture_metadata.get("camera_fixed") is False:
        warnings.append({"code": "camera_not_fixed", "severity": "warning", "message": "Camera was marked as not fixed; persistence scores may reflect motion."})
    if capture_metadata.get("saturated") is True:
        warnings.append({"code": "capture_saturated", "severity": "warning", "message": "Capture was marked saturated; clipped regions can create detector artifacts."})
    return warnings


def _inspect_video(source: Path) -> dict[str, Any]:
    try:
        import cv2
    except ImportError:
        return {"width": None, "height": None, "fps": None, "frame_count": None, "codec": None}
    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        return {"width": None, "height": None, "fps": None, "frame_count": None, "codec": None}
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
        codec = "".join(chr((fourcc >> (8 * index)) & 0xFF) for index in range(4)).strip("\x00")
        return {
            "width": width or None,
            "height": height or None,
            "fps": fps or None,
            "frame_count": frame_count or None,
            "duration_ms": int(frame_count / fps * 1000) if frame_count and fps else None,
            "codec": codec or None,
            "container": source.suffix.lower().lstrip(".") or None,
        }
    finally:
        cap.release()


def _inspect_image_set(source: Path) -> dict[str, Any]:
    images = list_images(source)
    width = height = None
    formats = sorted({path.suffix.lower().lstrip(".") for path in images})
    if images:
        try:
            import cv2

            image = cv2.imread(str(images[0]), cv2.IMREAD_UNCHANGED)
            if image is not None:
                height, width = image.shape[:2]
        except ImportError:
            pass
    return {
        "width": width,
        "height": height,
        "image_count": len(images),
        "formats": formats,
    }
