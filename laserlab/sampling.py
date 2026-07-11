"""Deterministic frame sampling and near-duplicate detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SAMPLING_PROFILES: dict[str, dict[str, Any]] = {
    "quick": {
        "mode": "interval",
        "frame_interval": 15,
        "max_frames": 25,
        "deduplicate": True,
        "scene_change_threshold": 0.12,
    },
    "baseline": {
        "mode": "interval",
        "frame_interval": 5,
        "max_frames": 250,
        "deduplicate": True,
        "scene_change_threshold": 0.10,
    },
    "wide": {
        "mode": "interval",
        "frame_interval": 2,
        "max_frames": 1000,
        "deduplicate": True,
        "scene_change_threshold": 0.08,
    },
    "exhaustive": {
        "mode": "all_frames",
        "frame_interval": 1,
        "max_frames": None,
        "deduplicate": True,
        "scene_change_threshold": 0.05,
    },
}

SAMPLING_MODES = {"interval", "all_frames", "capped_all_frames", "scene_change"}


def resolve_sampling_plan(
    profile: str = "baseline",
    mode: str | None = None,
    frame_interval: int | None = None,
    max_frames: int | None = None,
    deduplicate: bool | None = None,
    scene_change_threshold: float | None = None,
) -> dict[str, Any]:
    if profile not in SAMPLING_PROFILES:
        raise ValueError(f"Unknown sampling profile: {profile}")
    plan = dict(SAMPLING_PROFILES[profile])
    plan["profile"] = profile
    if mode is not None:
        plan["mode"] = mode
    if frame_interval is not None:
        plan["frame_interval"] = frame_interval
    if max_frames is not None:
        plan["max_frames"] = max_frames
    if deduplicate is not None:
        plan["deduplicate"] = deduplicate
    if scene_change_threshold is not None:
        plan["scene_change_threshold"] = scene_change_threshold
    if plan["mode"] not in SAMPLING_MODES:
        raise ValueError(f"Unknown frame sampling mode: {plan['mode']}")
    if int(plan["frame_interval"]) < 1:
        raise ValueError("frame_interval must be >= 1")
    if plan["max_frames"] is not None and int(plan["max_frames"]) < 1:
        raise ValueError("max_frames must be >= 1 when provided")
    threshold = float(plan["scene_change_threshold"])
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("scene_change_threshold must be between 0 and 1")
    plan["frame_interval"] = 1 if plan["mode"] in {"all_frames", "capped_all_frames"} else int(plan["frame_interval"])
    plan["max_frames"] = None if plan["mode"] == "all_frames" else plan["max_frames"]
    plan["deduplicate"] = bool(plan["deduplicate"])
    plan["scene_change_threshold"] = threshold
    return plan


def frame_signature(image: Any) -> str:
    """Return a stable 64-bit average hash for an image array."""
    import cv2
    import numpy as np

    gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    bits = resized >= float(np.mean(resized))
    value = 0
    for bit in bits.flatten():
        value = (value << 1) | int(bool(bit))
    return f"{value:016x}"


def signature_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def scene_change_score(previous: Any | None, current: Any) -> float:
    import cv2
    import numpy as np

    if previous is None:
        return 1.0
    left = previous if len(previous.shape) == 2 else cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY)
    right = current if len(current.shape) == 2 else cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    left = cv2.resize(left, (64, 64), interpolation=cv2.INTER_AREA)
    right = cv2.resize(right, (64, 64), interpolation=cv2.INTER_AREA)
    return float(np.mean(cv2.absdiff(left, right)) / 255.0)


@dataclass
class DuplicateMatch:
    frame_id: str
    distance: int
    mean_difference: float


class DuplicateTracker:
    """Track accepted frame signatures and find deterministic near duplicates."""

    def __init__(self, max_distance: int = 3, max_mean_difference: float = 4.0):
        self.max_distance = max_distance
        self.max_mean_difference = max_mean_difference
        self._accepted: list[tuple[str, str, float]] = []

    def match(self, signature: str, mean_intensity: float) -> DuplicateMatch | None:
        best: DuplicateMatch | None = None
        for frame_id, accepted_signature, accepted_mean in self._accepted:
            distance = signature_distance(signature, accepted_signature)
            mean_difference = abs(mean_intensity - accepted_mean)
            if (
                distance <= self.max_distance
                and mean_difference <= self.max_mean_difference
                and (best is None or (distance, mean_difference) < (best.distance, best.mean_difference))
            ):
                best = DuplicateMatch(frame_id=frame_id, distance=distance, mean_difference=mean_difference)
        return best

    def add(self, frame_id: str, signature: str, mean_intensity: float) -> None:
        self._accepted.append((frame_id, signature, mean_intensity))
