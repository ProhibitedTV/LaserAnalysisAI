"""Normalized OCR adapter contracts and optional engine implementations.

This module is intentionally independent from the analysis pipeline.  It gives
OCR engines one auditable result shape while preserving empty text, null text,
unavailable engines, and failed attempts as different outcomes.
"""

from __future__ import annotations

import importlib
import json
import math
import time
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable


ATTEMPT_SCHEMA_VERSION = "1.0"


class OCRAdapterTimeout(TimeoutError):
    """Raised when an OCR adapter exhausts the request timeout."""


@dataclass(frozen=True)
class OCRRequest:
    """Input image or cropped ROI plus the settings needed to reproduce OCR."""

    image: Any
    roi_reference: Any = None
    preprocessing_metadata: Mapping[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = 30.0
    language: str | None = "eng"
    script: str | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive or None")
        if not isinstance(self.preprocessing_metadata, Mapping):
            raise TypeError("preprocessing_metadata must be a mapping")

    def settings(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "language": self.language,
            "script": self.script,
        }


@dataclass(frozen=True)
class OCRPayload:
    """Engine output before adapter identity and runtime are attached."""

    text: str | None = None
    confidence: float | None = None
    word_boxes: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    character_boxes: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    failure_reason: str | None = None


@runtime_checkable
class OCRAdapterProtocol(Protocol):
    """Structural interface accepted by :func:`run_ocr_ensemble`."""

    engine_id: str

    def run(self, request: OCRRequest) -> dict[str, Any]:
        """Return one normalized, JSON-safe OCR attempt."""


class BaseOCRAdapter(ABC):
    """Base class that normalizes availability, failures, and runtime."""

    engine_id = "base"

    def availability(self) -> tuple[bool, str | None]:
        return True, None

    def engine_version(self) -> str | None:
        return None

    @abstractmethod
    def recognize(self, request: OCRRequest) -> OCRPayload | Mapping[str, Any]:
        """Run the engine and return raw normalized fields."""

    def run(self, request: OCRRequest) -> dict[str, Any]:
        if not isinstance(request, OCRRequest):
            raise TypeError("request must be an OCRRequest")
        started = time.perf_counter()
        version: str | None = None
        try:
            available, unavailable_reason = self.availability()
            if available:
                version = self.engine_version()
            if not available:
                return normalize_attempt(
                    engine_id=self.engine_id,
                    engine_version=version,
                    payload=OCRPayload(failure_reason=unavailable_reason or "engine unavailable"),
                    runtime_ms=_elapsed_ms(started),
                    available=False,
                    request=request,
                )
            payload = self.recognize(request)
            return normalize_attempt(
                engine_id=self.engine_id,
                engine_version=version,
                payload=payload,
                runtime_ms=_elapsed_ms(started),
                available=True,
                request=request,
            )
        except OCRAdapterTimeout as exc:
            return normalize_attempt(
                engine_id=self.engine_id,
                engine_version=version,
                payload=OCRPayload(failure_reason=f"timeout: {exc}"),
                runtime_ms=_elapsed_ms(started),
                available=True,
                request=request,
            )
        except Exception as exc:  # Engines are optional and may fail independently.
            return normalize_attempt(
                engine_id=self.engine_id,
                engine_version=version,
                payload=OCRPayload(failure_reason=f"{type(exc).__name__}: {exc}"),
                runtime_ms=_elapsed_ms(started),
                available=True,
                request=request,
            )


class TesseractAdapter(BaseOCRAdapter):
    """Optional pytesseract adapter; importing this module does not require it."""

    engine_id = "tesseract"

    def __init__(
        self,
        *,
        executable_path: str | Path | None = None,
        oem: int = 3,
        psm: int = 6,
        extra_config: str = "",
    ) -> None:
        self.executable_path = str(executable_path) if executable_path is not None else None
        self.oem = int(oem)
        self.psm = int(psm)
        self.extra_config = str(extra_config).strip()
        self._version: str | None = None
        self._availability: tuple[bool, str | None] | None = None

    def _module(self) -> Any:
        try:
            module = importlib.import_module("pytesseract")
        except ImportError as exc:
            raise RuntimeError("pytesseract is not installed") from exc
        if self.executable_path:
            module.pytesseract.tesseract_cmd = self.executable_path
        return module

    def availability(self) -> tuple[bool, str | None]:
        if self._availability is not None:
            return self._availability
        try:
            module = self._module()
            self._version = str(module.get_tesseract_version())
        except Exception as exc:
            self._availability = (False, f"Tesseract unavailable: {exc}")
            return self._availability
        self._availability = (True, None)
        return self._availability

    def engine_version(self) -> str | None:
        return self._version

    def recognize(self, request: OCRRequest) -> OCRPayload:
        module = self._module()
        started = time.perf_counter()
        config = f"--oem {self.oem} --psm {self.psm}"
        if self.extra_config:
            config = f"{config} {self.extra_config}"
        lang = _tesseract_language(request.language, request.script)

        text = module.image_to_string(
            request.image,
            **_tesseract_kwargs(config, lang, _remaining_timeout(request.timeout_seconds, started)),
        ).strip()
        data = module.image_to_data(
            request.image,
            output_type=module.Output.DICT,
            **_tesseract_kwargs(config, lang, _remaining_timeout(request.timeout_seconds, started)),
        )
        raw_character_boxes = module.image_to_boxes(
            request.image,
            **_tesseract_kwargs(config, lang, _remaining_timeout(request.timeout_seconds, started)),
        )

        word_boxes: list[dict[str, Any]] = []
        confidences: list[float] = []
        words = list(data.get("text", []))
        for index, raw_word in enumerate(words):
            word = "" if raw_word is None else str(raw_word).strip()
            if not word:
                continue
            confidence = _normalize_confidence(_sequence_value(data.get("conf", []), index))
            if confidence is not None:
                confidences.append(confidence)
            word_boxes.append(
                {
                    "text": word,
                    "confidence": confidence,
                    "x": _integer_or_none(_sequence_value(data.get("left", []), index)),
                    "y": _integer_or_none(_sequence_value(data.get("top", []), index)),
                    "width": _integer_or_none(_sequence_value(data.get("width", []), index)),
                    "height": _integer_or_none(_sequence_value(data.get("height", []), index)),
                }
            )

        character_boxes = _parse_tesseract_character_boxes(raw_character_boxes, request.image)
        confidence = sum(confidences) / len(confidences) if confidences else None
        return OCRPayload(
            text=text,
            confidence=confidence,
            word_boxes=word_boxes,
            character_boxes=character_boxes,
        )


class DeterministicStubAdapter(BaseOCRAdapter):
    """Configurable deterministic adapter for tests and local calibration."""

    def __init__(
        self,
        engine_id: str,
        payload: OCRPayload | Mapping[str, Any] | Callable[[OCRRequest], OCRPayload | Mapping[str, Any]],
        *,
        version: str | None = "stub-1",
    ) -> None:
        if not str(engine_id).strip():
            raise ValueError("engine_id must not be empty")
        self.engine_id = str(engine_id)
        self._payload = payload
        self._engine_version = version

    def engine_version(self) -> str | None:
        return self._engine_version

    def recognize(self, request: OCRRequest) -> OCRPayload | Mapping[str, Any]:
        if callable(self._payload):
            return self._payload(request)
        return self._payload


class UnavailableStubAdapter(DeterministicStubAdapter):
    """Deterministic unavailable engine used to verify null-attempt handling."""

    def __init__(self, engine_id: str = "unavailable-stub", reason: str = "stub engine unavailable") -> None:
        super().__init__(engine_id, OCRPayload(), version=None)
        self._reason = reason

    def availability(self) -> tuple[bool, str | None]:
        return False, self._reason


class FailingStubAdapter(DeterministicStubAdapter):
    """Deterministic adapter that raises during recognition."""

    def __init__(self, engine_id: str = "failing-stub", message: str = "stub failure") -> None:
        super().__init__(engine_id, OCRPayload())
        self._message = message

    def recognize(self, request: OCRRequest) -> OCRPayload:
        raise RuntimeError(self._message)


def normalize_attempt(
    *,
    engine_id: str,
    engine_version: str | None,
    payload: OCRPayload | Mapping[str, Any],
    runtime_ms: float,
    available: bool,
    request: OCRRequest,
) -> dict[str, Any]:
    """Build the stable JSON-safe attempt schema without dropping nulls."""

    if isinstance(payload, OCRPayload):
        values = {
            "text": payload.text,
            "confidence": payload.confidence,
            "word_boxes": payload.word_boxes,
            "character_boxes": payload.character_boxes,
            "failure_reason": payload.failure_reason,
        }
    elif isinstance(payload, Mapping):
        values = dict(payload)
    else:
        raise TypeError("OCR payload must be OCRPayload or a mapping")

    text = values.get("text")
    if text is not None and not isinstance(text, str):
        text = str(text)
    failure_reason = values.get("failure_reason")
    if failure_reason is not None and not isinstance(failure_reason, str):
        failure_reason = str(failure_reason)

    attempt = {
        "schema_version": ATTEMPT_SCHEMA_VERSION,
        "engine_id": str(engine_id),
        "engine_version": None if engine_version is None else str(engine_version),
        "text": text,
        "confidence": _normalize_confidence(values.get("confidence")),
        "word_boxes": [_normalize_box(box, character=False) for box in values.get("word_boxes", []) or []],
        "character_boxes": [
            _normalize_box(box, character=True) for box in values.get("character_boxes", []) or []
        ],
        "runtime_ms": max(0.0, round(float(runtime_ms), 3)),
        "available": bool(available),
        "failure_reason": failure_reason,
        "roi_reference": _json_safe(request.roi_reference),
        "preprocessing_metadata": _json_safe(dict(request.preprocessing_metadata)),
        "settings": _json_safe(request.settings()),
    }
    json.dumps(attempt, allow_nan=False)
    return attempt


def run_ocr_ensemble(
    adapters: Sequence[OCRAdapterProtocol],
    request: OCRRequest,
) -> dict[str, Any]:
    """Run every adapter and report exact text agreement without exclusions."""

    attempts: list[dict[str, Any]] = []
    for adapter in adapters:
        if not isinstance(adapter, OCRAdapterProtocol):
            raise TypeError("all adapters must implement OCRAdapterProtocol")
        attempt = adapter.run(request)
        attempts.append(_validate_attempt(attempt))
    result = {
        "schema_version": ATTEMPT_SCHEMA_VERSION,
        "attempts": attempts,
        "agreement": summarize_ocr_attempts(attempts),
    }
    json.dumps(result, allow_nan=False)
    return result


def summarize_ocr_attempts(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize agreement while retaining empty and null engine attempts."""

    records = [_validate_attempt(dict(attempt)) for attempt in attempts]
    annotated: list[dict[str, Any]] = []
    groups: dict[tuple[str, str | None], dict[str, Any]] = {}
    for index, attempt in enumerate(records):
        state, normalized_text = _text_signature(attempt.get("text"))
        status = _attempt_status(attempt, state)
        signature = (state, normalized_text)
        group = groups.setdefault(
            signature,
            {
                "state": state,
                "text": attempt.get("text") if state != "text" else normalized_text,
                "normalized_text": normalized_text,
                "count": 0,
                "engine_ids": [],
                "first_index": index,
            },
        )
        group["count"] += 1
        group["engine_ids"].append(attempt["engine_id"])
        annotated.append(
            {
                "index": index,
                "engine_id": attempt["engine_id"],
                "status": status,
                "text_state": state,
                "normalized_text": normalized_text,
            }
        )

    pairwise: list[dict[str, Any]] = []
    matching_pairs = 0
    for left_index in range(len(records)):
        for right_index in range(left_index + 1, len(records)):
            left_signature = _text_signature(records[left_index].get("text"))
            right_signature = _text_signature(records[right_index].get("text"))
            same_output = left_signature == right_signature
            if same_output:
                matching_pairs += 1
            pairwise.append(
                {
                    "left_index": left_index,
                    "right_index": right_index,
                    "left_engine_id": records[left_index]["engine_id"],
                    "right_engine_id": records[right_index]["engine_id"],
                    "same_output": same_output,
                    "same_status": annotated[left_index]["status"] == annotated[right_index]["status"],
                }
            )

    ordered_groups = sorted(groups.values(), key=lambda item: (-item["count"], item["first_index"]))
    for group in ordered_groups:
        group.pop("first_index", None)
    consensus: dict[str, Any]
    if not ordered_groups:
        consensus = {"state": "none", "text": None, "count": 0, "fraction": 0.0, "unique": False}
    else:
        leader = ordered_groups[0]
        unique = len(ordered_groups) == 1 or leader["count"] > ordered_groups[1]["count"]
        consensus = {
            "state": leader["state"] if unique else "tie",
            "text": leader["text"] if unique else None,
            "count": leader["count"],
            "fraction": leader["count"] / len(records),
            "unique": unique,
        }

    total_pairs = len(pairwise)
    summary = {
        "total_attempts": len(records),
        "available_attempts": sum(bool(item["available"]) for item in records),
        "unavailable_attempts": sum(not bool(item["available"]) for item in records),
        "failed_attempts": sum(item.get("failure_reason") is not None for item in records),
        "nonempty_text_attempts": sum(item["text_state"] == "text" for item in annotated),
        "empty_text_attempts": sum(item["text_state"] == "empty" for item in annotated),
        "null_text_attempts": sum(item["text_state"] == "null" for item in annotated),
        "distinct_output_count": len(ordered_groups),
        "all_attempts_agree": bool(records) and len(ordered_groups) == 1,
        "pairwise_agreement_rate": matching_pairs / total_pairs if total_pairs else (1.0 if records else 0.0),
        "consensus": consensus,
        "outputs": ordered_groups,
        "per_engine": annotated,
        "pairwise": pairwise,
    }
    return _json_safe(summary)


def _validate_attempt(attempt: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "engine_id",
        "engine_version",
        "text",
        "confidence",
        "word_boxes",
        "character_boxes",
        "runtime_ms",
        "available",
        "failure_reason",
        "roi_reference",
        "preprocessing_metadata",
    }
    missing = sorted(required.difference(attempt))
    if missing:
        raise ValueError(f"OCR attempt is missing required fields: {', '.join(missing)}")
    normalized = _json_safe(dict(attempt))
    json.dumps(normalized, allow_nan=False)
    return normalized


def _attempt_status(attempt: Mapping[str, Any], text_state: str) -> str:
    if not attempt.get("available"):
        return "unavailable"
    if attempt.get("failure_reason") is not None:
        return "failed"
    return text_state


def _text_signature(text: Any) -> tuple[str, str | None]:
    if text is None:
        return "null", None
    value = str(text)
    if value == "":
        return "empty", ""
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if normalized == "":
        return "empty", ""
    return "text", normalized


def _normalize_box(box: Mapping[str, Any], *, character: bool) -> dict[str, Any]:
    if not isinstance(box, Mapping):
        raise TypeError("OCR boxes must be mappings")
    result = {
        "character" if character else "text": _json_safe(
            box.get("character" if character else "text")
        ),
        "confidence": _normalize_confidence(box.get("confidence")),
        "x": _number_or_none(box.get("x")),
        "y": _number_or_none(box.get("y")),
        "width": _number_or_none(box.get("width")),
        "height": _number_or_none(box.get("height")),
    }
    extras = {
        str(key): _json_safe(value)
        for key, value in box.items()
        if key not in result and key not in {"text", "character"}
    }
    if extras:
        result["metadata"] = extras
    return result


def _normalize_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(confidence) or confidence < 0:
        return None
    if confidence > 1.0:
        confidence /= 100.0
    return max(0.0, min(1.0, confidence))


def _number_or_none(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _integer_or_none(value: Any) -> int | None:
    number = _number_or_none(value)
    return None if number is None else int(number)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _remaining_timeout(timeout_seconds: float | None, started: float) -> float | None:
    if timeout_seconds is None:
        return None
    remaining = timeout_seconds - (time.perf_counter() - started)
    if remaining <= 0:
        raise OCRAdapterTimeout("request deadline exceeded")
    return remaining


def _tesseract_language(language: str | None, script: str | None) -> str | None:
    values: list[str] = []
    if language is not None and language != "":
        values.append(str(language))
    if script is not None and script != "":
        script_value = str(script)
        values.append(script_value if script_value.startswith("script/") else f"script/{script_value}")
    return "+".join(values) if values else None


def _tesseract_kwargs(config: str, lang: str | None, timeout: float | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"config": config}
    if lang is not None:
        kwargs["lang"] = lang
    if timeout is not None:
        kwargs["timeout"] = timeout
    return kwargs


def _sequence_value(values: Any, index: int) -> Any:
    try:
        return values[index]
    except (IndexError, KeyError, TypeError):
        return None


def _image_height(image: Any) -> int | None:
    shape = getattr(image, "shape", None)
    if shape is not None and len(shape) >= 2:
        return int(shape[0])
    height = getattr(image, "height", None)
    if height is not None:
        return int(height)
    size = getattr(image, "size", None)
    if isinstance(size, tuple) and len(size) >= 2:
        return int(size[1])
    return None


def _parse_tesseract_character_boxes(raw_boxes: Any, image: Any) -> list[dict[str, Any]]:
    height = _image_height(image)
    records: list[dict[str, Any]] = []
    for raw_line in str(raw_boxes or "").splitlines():
        parts = raw_line.split()
        if len(parts) < 6:
            continue
        character = " ".join(parts[:-5])
        try:
            left, bottom, right, top = (int(value) for value in parts[-5:-1])
        except ValueError:
            continue
        y = height - top if height is not None else bottom
        records.append(
            {
                "character": character,
                "confidence": None,
                "x": left,
                "y": y,
                "width": max(0, right - left),
                "height": max(0, top - bottom),
                "page": _integer_or_none(parts[-1]),
                "coordinate_origin": "top_left" if height is not None else "bottom_left",
            }
        )
    return records
