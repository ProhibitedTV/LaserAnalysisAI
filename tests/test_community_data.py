from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from laserlab.community_data import (
    export_symbol_transcriptions_csv,
    import_symbol_transcriptions_csv,
    load_external_references,
    load_local_data,
    normalize_external_reference,
    normalize_symbol_transcription,
    sha256_file,
)


class ExternalReferenceInteropTests(unittest.TestCase):
    def test_json_normalizes_provenance_confidence_and_safe_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "community.json"
            payload = {
                "privacy_status": "pseudonymized",
                "redaction_status": "redacted",
                "attribution": {"title": "Community export", "creator": "Example group"},
                "license": {"name": "CC BY 4.0", "verified": True},
                "records": [
                    {
                        "id": "reference-1",
                        "color": "green",
                        "power_mw": "5 mW",
                        "laser_class": "3R",
                        "projection_distance_cm": "250",
                        "pattern": "cross",
                        "equipment": {"laser": "Example 532 nm module", "camera": "Camera A"},
                        "tags": "wall, diffraction, dose 20 mg",
                        "observed_code": "AB-12",
                        "substance": "value that must not survive",
                        "dose_mg": "20",
                    }
                ],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")

            loaded = load_external_references(
                path,
                user_overrides={"wavelength_nm": 532, "laser_pattern_type": "grid"},
            )
            record = loaded["records"][0]

            self.assertEqual(loaded["source_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(sha256_file(path), loaded["source"]["sha256"])
            self.assertFalse(loaded["source"]["local_path_included"])
            self.assertEqual(loaded["privacy"]["status"], "pseudonymized")
            self.assertEqual(loaded["privacy"]["redaction_status"], "redacted")
            self.assertEqual(loaded["attribution"]["creator"], "Example group")
            self.assertEqual(loaded["license"]["name"], "CC BY 4.0")
            self.assertEqual(record["wavelength_nm"], 532.0)
            self.assertEqual(record["field_confidence"]["wavelength_nm"]["status"], "user_entered")
            self.assertEqual(record["rated_power_mw"], 5.0)
            self.assertEqual(record["field_confidence"]["rated_power_mw"]["status"], "exact")
            self.assertEqual(record["projection_distance_meters"], 2.5)
            self.assertEqual(record["laser_pattern_type"], "grid")
            self.assertEqual(record["tags"], ["wall", "diffraction"])
            self.assertEqual(record["context"]["observed_code"], "AB-12")
            self.assertEqual(record["context"]["evidence_role"], "context_only")
            self.assertTrue(record["context"]["excluded_from_detector_scoring"])
            self.assertEqual(
                record["safety_filter"]["substance_or_dose_fields_removed"],
                ["dose_mg", "substance"],
            )
            serialized = json.dumps(loaded)
            self.assertNotIn("value that must not survive", serialized)
            self.assertNotIn('"20"', serialized)
            self.assertFalse(record["safety_filter"]["operational_guidance_created"])

    def test_csv_supports_exact_inferred_and_missing_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "references.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["hardware", "projection_distance", "tags"])
                writer.writeheader()
                writer.writerow(
                    {
                        "hardware": "Blue cross laser, 450 nm, 0.01 W, Class 3R",
                        "projection_distance": "6 ft",
                        "tags": "cross;wall",
                    }
                )

            loaded = load_local_data(
                path,
                privacy_status="reviewed",
                redaction_status="not_required",
                attribution="Local test export",
                license_info="CC0-1.0",
            )
            record = loaded["records"][0]

            self.assertEqual(record["wavelength_nm"], 450.0)
            self.assertEqual(record["field_confidence"]["wavelength_nm"]["status"], "inferred")
            self.assertEqual(record["rated_power_mw"], 10.0)
            self.assertEqual(record["laser_class_label"], "Class 3R")
            self.assertAlmostEqual(record["projection_distance_meters"], 1.8288)
            self.assertEqual(record["field_confidence"]["equipment"]["status"], "exact")
            self.assertIn("450 nm", record["equipment"]["notes"])
            self.assertEqual(record["tags"], ["cross", "wall"])
            self.assertEqual(record["context"]["evidence_role"], "context_only")
            missing = normalize_external_reference({})
            self.assertTrue(
                all(item["status"] == "missing" for item in missing["field_confidence"].values())
            )

    def test_network_urls_and_unknown_privacy_claims_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_external_references("https://example.invalid/data.json")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "data.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_external_references(path, privacy_status="probably_public")


class SymbolTranscriptionInteropTests(unittest.TestCase):
    def test_csv_round_trip_preserves_context_records_and_metadata(self) -> None:
        crop_hash = hashlib.sha256(b"crop-bytes").hexdigest()
        payload = {
            "privacy": {"status": "pseudonymized", "redaction_status": "redacted"},
            "attribution": {"title": "Blind transcription pass", "creator": "Team 7"},
            "license": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
            "records": [
                {
                    "record_id": "symbol-001",
                    "pseudonymous_id": "observer-7",
                    "coordinate": {"x": 121.5, "y": 88.0, "space": "pixels"},
                    "timestamp_seconds": 12.25,
                    "wavelength_nm": 650.0,
                    "laser_pattern_type": "cross",
                    "transcription": "R7-K",
                    "crop_sha256": crop_hash,
                    "evidence_role": "context_only",
                    "excluded_from_detector_scoring": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as temp:
            path = export_symbol_transcriptions_csv(payload, Path(temp) / "symbols.csv")
            imported = import_symbol_transcriptions_csv(path)
            record = imported["records"][0]

            self.assertEqual(record["record_id"], "symbol-001")
            self.assertEqual(record["pseudonymous_id"], "observer-7")
            self.assertEqual(record["coordinate"], {"x": 121.5, "y": 88.0, "space": "pixels"})
            self.assertEqual(record["timestamp_seconds"], 12.25)
            self.assertEqual(record["wavelength_nm"], 650.0)
            self.assertEqual(record["laser_pattern_type"], "cross")
            self.assertEqual(record["transcription"], "R7-K")
            self.assertEqual(record["crop_sha256"], crop_hash)
            self.assertEqual(record["evidence_role"], "context_only")
            self.assertTrue(record["excluded_from_detector_scoring"])
            self.assertFalse(record["operational_guidance"])
            self.assertEqual(imported["privacy"], payload["privacy"])
            self.assertEqual(imported["attribution"]["title"], "Blind transcription pass")
            self.assertEqual(imported["license"]["name"], "CC BY 4.0")
            self.assertEqual(imported["source_sha256"], sha256_file(path))

    def test_normalizes_timestamp_and_normalized_coordinates(self) -> None:
        record = normalize_symbol_transcription(
            {
                "session_id": "anon_002",
                "coordinate": "0.25,0.75",
                "coordinate_space": "normalized",
                "timestamp": "01:02.5",
                "wavelength": "532",
                "pattern_type": "grid",
                "observed_symbols": "A-4",
            }
        )
        self.assertEqual(record["coordinate"], {"x": 0.25, "y": 0.75, "space": "normalized"})
        self.assertEqual(record["timestamp_seconds"], 62.5)
        self.assertEqual(record["wavelength_nm"], 532.0)
        self.assertEqual(record["transcription"], "A-4")
        self.assertIsNone(record["crop_sha256"])

    def test_rejects_direct_identifiers_and_invalid_crop_hashes(self) -> None:
        base = {
            "coordinate_x": 1,
            "coordinate_y": 2,
            "timestamp_seconds": 0,
            "wavelength_nm": 532,
            "laser_pattern_type": "dot",
            "transcription": "X",
        }
        with self.assertRaises(ValueError):
            normalize_symbol_transcription({**base, "pseudonymous_id": "person@example.com"})
        with self.assertRaises(ValueError):
            normalize_symbol_transcription(
                {**base, "pseudonymous_id": "anon-3", "crop_sha256": "not-a-sha256"}
            )


if __name__ == "__main__":
    unittest.main()
