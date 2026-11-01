"""Offline tests for explicit consent, bounded cache age and safe provenance."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from laserlab.artifacts import sha256_json
from laserlab.catalog_cache import CatalogCache, CatalogCacheError, refresh_catalog, open_saved_catalog
from laserlab.veilbreak_bridge import (
    CATALOG_TTL, LICENSE_POLICY_URL, MCP_ENDPOINT, VeilbreakError,
    linked_record, safe_public_record,
)


class CacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = CatalogCache(self.root / "cache")
        self.now = datetime.now(timezone.utc)
        self.provenance = {"origin": "live", "source_endpoint": MCP_ENDPOINT,
                           "retrieved_at": self.now.isoformat(), "expires_at": (self.now + CATALOG_TTL).isoformat()}
        self.raw = {"id": 7, "title": "Public diffraction reference", "meta": {
            "laser_wavelength": 650, "laser_power": 1, "projection_distance": 5,
            "substance_dose": "PRIVATE dose"}, "equipment": ["camera", "grating"],
            "tags": ["optics"], "author": "PRIVATE author", "content": "PRIVATE body"}
        self.record = safe_public_record(self.raw, "protocols")

    def save(self):
        self.cache.save("protocols", [self.record], self.provenance)
        return self.cache._path("protocols")

    def test_disabled_refresh_never_opens_or_creates_cache(self):
        client = Mock()
        client.call.return_value = [self.raw]
        with patch("laserlab.catalog_cache.CatalogCache", side_effect=AssertionError("no cache access")):
            view = refresh_catalog("protocols", client=client)
        self.assertEqual(view["cache_status"], "disabled")
        self.assertEqual(len(view["records"]), 1)
        self.assertFalse(self.cache.directory.exists())
        with self.assertRaises(ValueError):
            refresh_catalog("protocols", cache_enabled="true", client=client)
        self.assertEqual(client.call.call_count, 1)

    def test_disabled_saved_access_is_rejected_before_disk_access(self):
        cache = Mock()
        with self.assertRaisesRegex(CatalogCacheError, "Enable"):
            open_saved_catalog("protocols", cache=cache)
        cache.load.assert_not_called()

    def test_opted_in_refresh_persists_only_public_allow_list_and_source_policy(self):
        client = Mock()
        client.call.return_value = [self.raw]
        view = refresh_catalog("protocols", cache_enabled=True, cache=self.cache, client=client)
        self.assertEqual(view["cache_status"], "saved")
        path = self.cache._path("protocols")
        encoded = path.read_text()
        self.assertNotIn("PRIVATE", encoded)
        data = json.loads(encoded)
        self.assertEqual(data["provenance"]["source_endpoint"], MCP_ENDPOINT)
        self.assertEqual(data["provenance"]["license_policy_url"], LICENSE_POLICY_URL)
        self.assertEqual(data["provenance"]["license_status"], "per_record_unverified")
        self.assertEqual(data["records"][0]["record_id"], 7)
        self.assertAlmostEqual(data["records"][0]["optical_metadata"]["projection_distance_meters"], 1.524)

    def test_saved_catalog_is_network_free_and_keeps_original_retrieval_time(self):
        self.provenance["retrieved_at"] = (self.now - timedelta(hours=1)).isoformat()
        self.provenance["expires_at"] = (self.now - timedelta(hours=1) + CATALOG_TTL).isoformat()
        self.save()
        with patch("laserlab.catalog_cache.browse_public", side_effect=AssertionError("no network")):
            view = open_saved_catalog("protocols", cache_enabled=True, cache=self.cache)
            reference = linked_record(view["records"][0])
        self.assertEqual(view["provenance"]["origin"], "saved")
        self.assertEqual(reference["retrieved_at"], self.provenance["retrieved_at"])
        self.assertEqual(reference["catalog_provenance"]["origin"], "saved")
        self.assertEqual(reference["field_confidence"]["projection_distance_meters"]["source_field"], "meta.projection_distance")
        self.assertGreater(datetime.fromisoformat(reference["linked_at"]), datetime.fromisoformat(reference["retrieved_at"]))
        self.assertTrue(reference["excluded_from_detector_scoring"])

    def test_expiry_boundary_future_time_and_excessive_lifetime_are_rejected(self):
        path = self.save()
        with self.assertRaisesRegex(VeilbreakError, "expired or invalid"):
            self.cache.load("protocols", now=self.now + CATALOG_TTL)
        with self.assertRaisesRegex(VeilbreakError, "expired or invalid"):
            self.cache.load("protocols", now=self.now - timedelta(seconds=1))
        data = json.loads(path.read_text())
        data["provenance"]["expires_at"] = (self.now + timedelta(days=365)).isoformat()
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(VeilbreakError, "expired or invalid"):
            self.cache.load("protocols")

    def test_expiry_is_rechecked_when_linking_and_bad_provenance_cannot_be_ignored(self):
        self.save()
        record = self.cache.load("protocols")["records"][0]
        old = self.now - timedelta(days=2)
        record["catalog_provenance"].update(retrieved_at=old.isoformat(), expires_at=(old + CATALOG_TTL).isoformat())
        with self.assertRaisesRegex(VeilbreakError, "expired"):
            linked_record(record)
        record["catalog_provenance"] = "bad provenance"
        with self.assertRaisesRegex(ValueError, "Invalid public catalog"):
            linked_record(record)

    def test_failed_network_refresh_preserves_previous_snapshot_without_fallback(self):
        path = self.save()
        before = path.read_bytes()
        client = Mock()
        client.call.side_effect = VeilbreakError("service unavailable")
        with self.assertRaisesRegex(VeilbreakError, "unavailable"):
            refresh_catalog("protocols", cache_enabled=True, cache=self.cache, client=client)
        self.assertEqual(path.read_bytes(), before)

    def test_failed_atomic_write_keeps_old_file_and_removes_only_its_temporary_file(self):
        path = self.save()
        before = path.read_bytes()
        other = self.cache.directory / "unrelated.txt"
        other.write_text("preserve me")
        with patch("laserlab.catalog_cache.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.cache.save("protocols", [{**self.record, "title": "new title"}], self.provenance)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(other.read_text(), "preserve me")
        self.assertEqual(list(self.cache.directory.glob("*.tmp")), [])

    def test_cache_write_failure_is_visible_while_live_records_remain_available(self):
        client = Mock()
        client.call.return_value = [self.raw]
        with patch.object(self.cache, "save", side_effect=OSError("PRIVATE path")):
            view = refresh_catalog("protocols", cache_enabled=True, cache=self.cache, client=client)
        self.assertEqual(view["cache_status"], "save_failed")
        self.assertEqual(view["records"][0]["record_id"], 7)
        self.assertNotIn("PRIVATE", json.dumps(view))

    def test_missing_corrupt_and_checksum_mismatched_snapshots_never_fetch_network(self):
        with patch("laserlab.catalog_cache.browse_public", side_effect=AssertionError("no network")):
            with self.assertRaisesRegex(CatalogCacheError, "No saved catalog"):
                self.cache.load("protocols")
            path = self.save()
            data = json.loads(path.read_text())
            data["records"][0]["title"] = "changed"
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(CatalogCacheError, "invalid or damaged"):
                self.cache.load("protocols")
            path.write_text("{bad json")
            with self.assertRaisesRegex(CatalogCacheError, "invalid or damaged"):
                self.cache.load("protocols")

    def test_edited_snapshot_cannot_reintroduce_omitted_fields_or_scoring(self):
        path = self.save()
        data = json.loads(path.read_text())
        row = data["records"][0]
        row.update(author="PRIVATE author", questionnaire={"person": "PRIVATE person"}, excluded_from_detector_scoring=False)
        row["optical_metadata"]["participant"] = "PRIVATE participant"
        row["field_confidence"] = {"wavelength_nm": {"status": "exact", "note": "PRIVATE note"}}
        data["records_sha256"] = sha256_json(data["records"])
        path.write_text(json.dumps(data))
        view = self.cache.load("protocols")
        self.assertNotIn("PRIVATE", json.dumps(view))
        self.assertTrue(view["records"][0]["excluded_from_detector_scoring"])

    def test_clear_only_removes_fixed_managed_files_and_rejects_path_traversal(self):
        self.save()
        experiment_row = {**self.record, "record_type": "experiment"}
        self.cache.save("experiments", [experiment_row], self.provenance)
        other = self.cache.directory / "personal-notes.json"
        other.write_text("unrelated work")
        self.assertEqual(self.cache.clear(), 2)
        self.assertEqual(other.read_text(), "unrelated work")
        with self.assertRaises(ValueError):
            self.cache.load("../personal-notes")
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(CatalogCacheError, "managed local file"):
                self.cache.clear()
        self.assertEqual(other.read_text(), "unrelated work")

    def test_large_record_sets_are_kept_and_oversized_or_invalid_snapshots_are_refused(self):
        rows = [{**self.record, "record_id": number} for number in range(1, 254)]
        self.cache.save("protocols", rows, self.provenance)
        self.assertEqual(self.cache.load("protocols")["records"][-1]["record_id"], 253)
        with patch("laserlab.catalog_cache.MAX_RESPONSE_BYTES", 20):
            with self.assertRaisesRegex(CatalogCacheError, "size limit"):
                self.cache.save("protocols", rows, self.provenance)
            with self.assertRaisesRegex(CatalogCacheError, "invalid or damaged"):
                self.cache.load("protocols")
        with self.assertRaisesRegex(CatalogCacheError, "unsupported record"):
            self.cache.save("protocols", [{**self.record, "record_id": False}], self.provenance)


if __name__ == "__main__":
    unittest.main()
