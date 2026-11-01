"""Offline Qt tests for complete, searchable public reference selection."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt5.QtWidgets import QApplication, QMessageBox

from gui.veilbreak_catalog import VeilbreakCatalogDialog
from gui.lab_dashboard import LabDashboardWindow


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def records(self):
        return [{"source": "veilbreak", "record_type": "protocol", "record_id": n,
                 "title": "Repeated public title", "optical_metadata": {
                     "wavelength_nm": 650 if n % 2 else 532,
                     "equipment": {"notes": "grating" if n == 253 else "camera"},
                     "tags": ["optics"]}} for n in range(1, 254)]

    def test_paging_reaches_every_record_and_selects_duplicate_titles_by_row(self):
        dialog = VeilbreakCatalogDialog("protocols", self.records())
        self.addCleanup(dialog.close)
        self.assertEqual(dialog.table.rowCount(), 50)
        self.assertFalse(dialog.previous.isEnabled())
        for _ in range(5):
            dialog.next.click()
        self.assertEqual(dialog.table.rowCount(), 3)
        self.assertFalse(dialog.next.isEnabled())
        dialog.table.selectRow(2)
        self.assertEqual(dialog.selected_record()["record_id"], 253)
        self.assertIn("251–253 of 253", dialog.count.text())
        dialog.previous.click()
        self.assertEqual(dialog.selected_record()["record_id"], 201)

    def test_search_and_wavelength_filter_all_loaded_pages_without_network(self):
        with patch("laserlab.veilbreak_bridge.build_opener", side_effect=AssertionError("no network")):
            dialog = VeilbreakCatalogDialog("protocols", self.records())
            self.addCleanup(dialog.close)
            dialog.next.click()
            dialog.search.setText("grating optics")
            self.assertEqual(dialog.page, 0)
            self.assertEqual(dialog.selected_record()["record_id"], 253)
            dialog.wavelength.setValue(532)
            self.assertEqual(dialog.table.rowCount(), 0)
            self.assertIsNone(dialog.selected_record())
            self.assertFalse(dialog.use_button.isEnabled())
            dialog.wavelength.setValue(650)
            self.assertEqual(dialog.selected_record()["record_id"], 253)
            dialog.search.clear()
            self.assertIn("127 matches", dialog.count.text())

    def test_catalog_selection_still_requires_local_reference_confirmation(self):
        dummy = SimpleNamespace(experiment_dir=Path("local-experiment"),
                                community_data_status=Mock(), status=Mock(), _error=Mock())
        record = self.records()[0]
        with patch("gui.lab_dashboard.VeilbreakCatalogDialog") as factory, \
             patch("gui.lab_dashboard.QMessageBox.question", return_value=QMessageBox.No) as question, \
             patch("gui.lab_dashboard.app_api.link_veilbreak_reference", return_value=record) as link:
            factory.return_value.exec_.return_value = 0
            LabDashboardWindow._choose_veilbreak_record(dummy, "protocols", [record])
            question.assert_not_called()
            factory.return_value.exec_.return_value = 1
            factory.return_value.selected_record.return_value = record
            LabDashboardWindow._choose_veilbreak_record(dummy, "protocols", [record])
            link.assert_not_called()
            question.return_value = QMessageBox.Yes
            LabDashboardWindow._choose_veilbreak_record(dummy, "protocols", [record])
            link.assert_called_once_with(dummy.experiment_dir, record)
            self.assertIn("not measurements", question.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
