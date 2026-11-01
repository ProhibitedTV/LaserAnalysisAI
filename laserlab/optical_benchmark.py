"""Small deterministic optical probes, never empirical matched-control evidence."""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from statistics import mean
from typing import Any

from .artifacts import load_json, sha256_file, sha256_json, write_json

BENCHMARK_VERSION = "optical-probes-v1"
WIDTH, HEIGHT, FRAME_COUNT = 256, 160, 3
TASK_RULES = {
    "text_like_components": {"metric": "connected_components.text_like_count", "threshold": 5},
    "periodic_pattern": {"metric": "fft_spectrum.peak_prominence", "threshold": 8.0},
    "pixel_clipping": {"metric": "any_channel_ge_250_fraction", "threshold": .02},
    "frame_persistence": {"metric": "mean_pipeline_mask_persistence", "threshold": .8},
    "ocr_text_presence": {"metric": "full_frame_nonempty_alphanumeric_ocr", "threshold": None},
}
VARIANTS = {
    "original": {"blur_kernel": None, "sigma": None, "jpeg_quality": None},
    "blur": {"blur_kernel": 5, "sigma": 1.2, "jpeg_quality": None},
    "jpeg35": {"blur_kernel": None, "sigma": None, "jpeg_quality": 35},
    "blur_jpeg35": {"blur_kernel": 5, "sigma": 1.2, "jpeg_quality": 35},
}
# Original geometric 5x7 calibration glyphs; no external font or text asset.
GLYPHS = {
    "L": (16, 16, 16, 16, 16, 16, 31), "A": (14, 17, 17, 31, 17, 17, 17),
    "S": (15, 16, 16, 14, 1, 1, 30), "E": (31, 16, 16, 30, 16, 16, 31),
    "R": (30, 17, 17, 30, 20, 18, 17), "3": (30, 1, 1, 14, 1, 1, 30),
    "1": (4, 12, 4, 4, 4, 4, 14), "4": (2, 6, 10, 18, 31, 2, 2),
}


def benchmark_catalog() -> list[dict[str, Any]]:
    definitions = [
        ("fringes", "Periodic fringe approximation", True, True, "16-pixel integer cosine-like lookup; stationary vertical fringes", None),
        ("speckle", "Dynamic speckle-like intensity", False, False, "SHAKE-256 intensity lookup approximating an exponential distribution; independent frames", None),
        ("compression_blocks", "Repeated block artifact", None, True, "8x8 constant blocks from a fixed pseudorandom field; stationary, no inserted text", None),
        ("saturated_patch", "Single-channel clipped region", None, True, "64x64 rectangle with red channel 255 on a dark field; stationary", None),
        ("sensor_noise", "Independent sensor-noise approximation", False, False, "SHAKE-256 uniform grayscale bytes mapped to 30..219; independent frames", None),
        ("static_texture", "Repeated glyph-like geometric texture", True, True, "16x16 repeating corner/checker texture; stationary, no encoded letters", None),
        ("known_text", "Light-on-dark text calibration", None, True, "Original 5x7 glyphs at scale 4; light text on dark background", "LASER 314"),
        ("small_text", "Small light-on-dark calibration", None, True, "Original 5x7 glyphs at scale 2; light text on dark background", "LASER 314"),
        ("dark_text", "Dark-on-light text calibration", None, True, "Original 5x7 glyphs at scale 4; dark text on light background", "LASER 314"),
        ("blank", "Uniform blank", False, True, "Uniform grayscale value 70; stationary", None),
    ]
    result = []
    for case_id, title, periodic, persistent, design, text in definitions:
        record = {
            "id": case_id, "title": title, "fixture_type": "synthetic", "footage_class": "regression_fixture",
            "evidence_role": "software_calibration_only", "license": "MIT", "source": "laserlab.optical_benchmark",
            "attribution": "LaserAnalysisAI contributors; original software-generated arrays and geometric glyphs",
            "seed": 314159, "frame_count": FRAME_COUNT, "width": WIDTH, "height": HEIGHT,
            "design": design, "known_text": text,
            "ground_truth": {"text_like_components": bool(text), "ocr_text_presence": bool(text),
                             "periodic_pattern": periodic, "pixel_clipping": case_id == "saturated_patch",
                             "frame_persistence": persistent},
            "expected_behavior": "Known inserted text" if text else "No intentionally inserted text; structure and OCR can still respond to artifacts",
            "limitations": "Synthetic approximation, not a physical optics model, recorded control, independent acquisition or validated language.",
        }
        # Encoding/blur can remove clipping; do not assign an invented pixel truth to derivatives.
        record["variant_ground_truth"] = {variant: {**record["ground_truth"],
            "pixel_clipping": record["ground_truth"]["pixel_clipping"] if variant == "original" else None} for variant in VARIANTS}
        result.append(record)
    return result


def _spec() -> dict[str, Any]:
    return {"version": BENCHMARK_VERSION, "cases": benchmark_catalog(), "variants": VARIANTS,
            "tasks": TASK_RULES, "glyphs": GLYPHS, "frame_sampling": "all three synthetic frames; not independent n"}


def _noise(case_id: str, frame: int, shape: tuple[int, int]) -> Any:
    import numpy as np
    payload = f"{BENCHMARK_VERSION}:314159:{case_id}:{frame}".encode("ascii")
    return np.frombuffer(hashlib.shake_256(payload).digest(shape[0] * shape[1]), dtype=np.uint8).reshape(shape)


def _raw_frame(case: dict[str, Any], frame: int) -> Any:
    import numpy as np
    case_id = case["id"]
    yy, xx = np.indices((HEIGHT, WIDTH))
    if case_id == "fringes":
        levels = np.array((220, 212, 190, 158, 120, 82, 50, 28, 20, 28, 50, 82, 120, 158, 190, 212), dtype=np.uint8)
        gray = levels[xx % 16]
    elif case_id == "speckle":
        values = _noise(case_id, frame, (HEIGHT, WIDTH))
        lookup = np.minimum(239, np.floor(-np.log((np.arange(256) + .5) / 256) * 55)).astype(np.uint8)
        gray = lookup[values]
    elif case_id == "sensor_noise":
        gray = (_noise(case_id, frame, (HEIGHT, WIDTH)).astype(np.uint16) * 190 // 256 + 30).astype(np.uint8)
    elif case_id == "compression_blocks":
        gray = (_noise(case_id, 0, (HEIGHT // 8, WIDTH // 8)).astype(np.uint16) * 180 // 256 + 35).astype(np.uint8)
        gray = np.repeat(np.repeat(gray, 8, axis=0), 8, axis=1)
    elif case_id == "static_texture":
        pattern = ((xx % 16 < 3) & (yy % 16 < 12)) | ((yy % 16 < 3) & (xx % 16 < 12))
        gray = np.where(pattern, 210, 35).astype(np.uint8)
    elif case.get("known_text"):
        gray = np.full((HEIGHT, WIDTH), 220 if case_id == "dark_text" else 30, dtype=np.uint8)
        scale = 2 if case_id == "small_text" else 4
        text = case["known_text"]
        start_x = (WIDTH - (len(text) * 6 - 1) * scale) // 2
        start_y = (HEIGHT - 7 * scale) // 2
        for index, letter in enumerate(text):
            for row, bits in enumerate(GLYPHS.get(letter, ())):
                for col in range(5):
                    if bits & (1 << (4 - col)):
                        x, y = start_x + (index * 6 + col) * scale, start_y + row * scale
                        gray[y:y + scale, x:x + scale] = 30 if case_id == "dark_text" else 220
    else:
        gray = np.full((HEIGHT, WIDTH), 70, dtype=np.uint8)
    image = np.repeat(gray[:, :, None], 3, axis=2)
    if case_id == "saturated_patch":
        image[48:112, 96:160] = (10, 25, 255)
    return image


def _transform(image: Any, settings: dict[str, Any]) -> Any:
    import cv2
    result = image.copy()
    if settings["blur_kernel"]:
        kernel = settings["blur_kernel"]
        result = cv2.GaussianBlur(result, (kernel, kernel), settings["sigma"], borderType=cv2.BORDER_REFLECT_101)
    if settings["jpeg_quality"] is not None:
        ok, encoded = cv2.imencode(".jpg", result, [cv2.IMWRITE_JPEG_QUALITY, settings["jpeg_quality"]])
        if not ok:
            raise RuntimeError("Could not encode benchmark JPEG probe")
        result = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if result is None:
            raise RuntimeError("Could not decode benchmark JPEG probe")
    return result


def pixel_sha256(image: Any) -> str:
    header = f"uint8:{','.join(map(str, image.shape))}:BGR\0".encode("ascii")
    return hashlib.sha256(header + image.tobytes(order="C")).hexdigest()


def generate_benchmark_pack(output_dir: Path) -> dict[str, Any]:
    """Generate exclusively into a new directory; never replace an existing pack."""
    import cv2
    import numpy as np
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 1, "benchmark_version": BENCHMARK_VERSION, "spec_sha256": sha256_json(_spec()),
                "generator": {"module": "laserlab.optical_benchmark", "version": BENCHMARK_VERSION,
                              "opencv": cv2.__version__, "numpy": np.__version__, "python": platform.python_version()},
                "license": "MIT", "fixture_type": "synthetic", "variants": VARIANTS, "tasks": TASK_RULES, "cases": [],
                "limitations": "Finite software probes, not estimates of real-world optical accuracy, statistical significance or independent replication."}
    for case in benchmark_catalog():
        record = {**case, "raw_frames": [], "processed_frames": {key: [] for key in VARIANTS}}
        for index in range(FRAME_COUNT):
            raw = _raw_frame(case, index)
            for variant in ("raw", *VARIANTS):
                image = raw if variant == "raw" else _transform(raw, VARIANTS[variant])
                stored = f"{case['id']}/{variant}/frame_{index:03d}.png"
                path = output_dir / stored
                path.parent.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(path), image, [cv2.IMWRITE_PNG_COMPRESSION, 6]):
                    raise RuntimeError("Could not write benchmark frame")
                frame_record = {"index": index, "path": stored, "sha256": sha256_file(path), "pixel_sha256": pixel_sha256(image)}
                (record["raw_frames"] if variant == "raw" else record["processed_frames"][variant]).append(frame_record)
        manifest["cases"].append(record)
    write_json(output_dir / "benchmark_manifest.json", manifest)
    return manifest


def _read_frame(root: Path, record: dict[str, Any], expected_path: str) -> Any:
    import cv2
    if record.get("path") != expected_path:
        raise ValueError("Benchmark paths do not match the declared recipe")
    path = (root / expected_path).resolve()
    if not path.is_relative_to(root) or not path.is_file() or sha256_file(path) != record.get("sha256"):
        raise ValueError("Benchmark file is missing, outside the pack, or fails its SHA-256 check")
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or image.shape != (HEIGHT, WIDTH, 3) or pixel_sha256(image) != record.get("pixel_sha256"):
        raise ValueError("Benchmark decoded pixels fail their shape or SHA-256 check")
    return image


def _load_pack(pack_dir: Path) -> tuple[dict[str, Any], dict[tuple[str, str], list[Any]]]:
    root = Path(pack_dir).resolve()
    manifest = load_json(root / "benchmark_manifest.json")
    if (manifest.get("schema_version") != 1 or manifest.get("benchmark_version") != BENCHMARK_VERSION
            or manifest.get("spec_sha256") != sha256_json(_spec()) or manifest.get("fixture_type") != "synthetic"
            or manifest.get("variants") != VARIANTS or manifest.get("tasks") != TASK_RULES):
        raise ValueError("Unsupported or modified benchmark specification")
    catalog = benchmark_catalog()
    cases = manifest.get("cases", [])
    if len(cases) != len(catalog):
        raise ValueError("Benchmark cases are missing or duplicated")
    images = {}
    for case, expected in zip(cases, catalog):
        if any(case.get(key) != value for key, value in expected.items()):
            raise ValueError("Benchmark provenance, design or ground truth differs from the public recipe")
        for variant in ("raw", *VARIANTS):
            records = case.get("raw_frames", []) if variant == "raw" else case.get("processed_frames", {}).get(variant, [])
            if len(records) != FRAME_COUNT:
                raise ValueError("Benchmark frame count differs from the recipe")
            if any(record.get("index") != index for index, record in enumerate(records)):
                raise ValueError("Benchmark frame order differs from the recipe")
            frames = [_read_frame(root, record, f"{case['id']}/{variant}/frame_{index:03d}.png") for index, record in enumerate(records)]
            images[case["id"], variant] = frames
        # Check actual content against the recipe, not merely self-asserted file hashes.
        for index, raw in enumerate(images[case["id"], "raw"]):
            if pixel_sha256(raw) != pixel_sha256(_raw_frame(expected, index)):
                raise ValueError("Benchmark raw content differs from the deterministic recipe")
            for variant, settings in VARIANTS.items():
                if pixel_sha256(images[case["id"], variant][index]) != pixel_sha256(_transform(raw, settings)):
                    raise ValueError("Benchmark processed content differs from its recorded transformation")
    return manifest, images


def confusion_counts(observations: list[dict[str, Any]], task: str) -> dict[str, Any]:
    """Count only binary known truths with available predictions; never score unknowns."""
    counts = {"true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0,
              "unknown_ground_truth": 0, "not_evaluated": 0}
    for record in observations:
        truth, predicted = record.get("ground_truth", {}).get(task), record.get("predictions", {}).get(task)
        if type(truth) is not bool:
            counts["unknown_ground_truth"] += 1
        elif type(predicted) is not bool:
            counts["not_evaluated"] += 1
        else:
            key = ("true_positive" if predicted else "false_negative") if truth else ("false_positive" if predicted else "true_negative")
            counts[key] += 1
    negatives = counts["false_positive"] + counts["true_negative"]
    positives = counts["true_positive"] + counts["false_negative"]
    counts.update(evaluated=negatives + positives, negative_count=negatives, positive_count=positives,
                  false_positive_rate=counts["false_positive"] / negatives if negatives else None,
                  false_negative_rate=counts["false_negative"] / positives if positives else None,
                  unit="case-variant probes; correlated derivatives, not independent experiments")
    return counts


def evaluate_benchmark_pack(pack_dir: Path, *, ocr_adapter: Any = None) -> dict[str, Any]:
    """Evaluate shared feature functions; optional OCR is one full-frame attempt per probe."""
    import cv2
    import numpy as np
    from .detectors import connected_components, edge_line_density, entropy_texture
    from .pipeline import _apply_persistence_scores
    from .scientific import fft_spectrum_metrics, speckle_contrast_metrics
    from .ocr_adapters import OCRRequest

    manifest, images = _load_pack(Path(pack_dir))
    records = []
    for case in manifest["cases"]:
        for variant in VARIANTS:
            frames = images[case["id"], variant]
            first = frames[0]
            components = connected_components(first)
            fft = fft_spectrum_metrics(first)
            persistence_records = [{"sample_id": str(index), "preprocessing_variant": variant} for index in range(FRAME_COUNT)]
            _apply_persistence_scores(persistence_records, {(case["id"], variant): [(index, str(index), image) for index, image in enumerate(frames)]})
            persistence = mean(record["persistence_score"] for record in persistence_records)
            clipping = mean(float(np.mean(np.any(image >= 250, axis=2))) for image in frames)
            attempt = None if ocr_adapter is None else ocr_adapter.run(OCRRequest(
                image=first, roi_reference={"id": "benchmark_full_frame"},
                preprocessing_metadata={"variant": variant, "case_id": case["id"]}, timeout_seconds=10))
            ocr_text = (attempt or {}).get("text")
            scorable = bool(attempt and attempt.get("available") and not attempt.get("failure_reason") and isinstance(ocr_text, str))
            normalized = "".join(char for char in str(ocr_text or "").upper() if char.isalnum())
            predictions = {"text_like_components": components["text_like_count"] >= TASK_RULES["text_like_components"]["threshold"],
                           "periodic_pattern": fft["peak_prominence"] >= TASK_RULES["periodic_pattern"]["threshold"],
                           "pixel_clipping": clipping >= TASK_RULES["pixel_clipping"]["threshold"],
                           "frame_persistence": persistence >= TASK_RULES["frame_persistence"]["threshold"],
                           "ocr_text_presence": bool(normalized) if scorable else None}
            records.append({"case_id": case["id"], "variant": variant, "fixture_type": "synthetic",
                            "ground_truth": case["variant_ground_truth"][variant], "predictions": predictions,
                            "metrics": {"connected_components": components, "fft_spectrum": fft,
                                        "entropy_texture": entropy_texture(first), "edge_line_density": edge_line_density(first),
                                        "speckle_contrast": speckle_contrast_metrics(first), "pixel_clipping": clipping,
                                        "frame_persistence": persistence},
                            "persistence_sensitivity": {str(threshold): persistence >= threshold for threshold in (.5, .8, .95)},
                            "ocr_attempt": attempt,
                            "known_text_exact_match": (normalized == "".join(case["known_text"].split())) if scorable and case["known_text"] else None,
                            "interpretation": "Feature responses and OCR are calibration observations, not validated language or empirical evidence."})
    return {"schema_version": 1, "benchmark_version": BENCHMARK_VERSION,
            "manifest_sha256": sha256_file(Path(pack_dir) / "benchmark_manifest.json"), "spec_sha256": manifest["spec_sha256"],
            "environment": {"python": platform.python_version(), "opencv": cv2.__version__, "numpy": np.__version__},
            "case_count": len(manifest["cases"]), "probe_count": len(records), "frame_count": len(manifest["cases"]) * FRAME_COUNT,
            "fixture_type": "synthetic", "empirical_capture_count": 0, "independent_experiment_count": 0,
            "tasks": TASK_RULES, "variants": VARIANTS,
            "summary": {task: confusion_counts(records, task) for task in TASK_RULES},
            "by_variant": {variant: {task: confusion_counts([r for r in records if r["variant"] == variant], task) for task in TASK_RULES} for variant in VARIANTS},
            "records": records, "ocr_mode": "disabled" if ocr_adapter is None else str(ocr_adapter.engine_id),
            "limitations": ["Finite deterministic software probes, not a population estimate or physical optics validation.",
                            "No significance, confidence intervals, matched-control evidence or validated-language classification is produced.",
                            "Case variants and repeated frames are correlated; counts are descriptive probe counts, not independent n.",
                            "Missing, failed, unavailable and null-text OCR are unscored, not true negatives or false negatives.",
                            "OCR uses one full-frame request per case/variant; it does not benchmark the full ROI search pipeline.",
                            "Features are measured on the first frame except clipping and the actual pipeline persistence over three frames.",
                            "Image encoding and blur can vary with library versions; replay requires the recorded stack and matching hashes."]}
