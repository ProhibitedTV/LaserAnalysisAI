from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from laserlab import app_api
from laserlab.blinding import build_unblind_payload, restore_manifest, seal_manifest
from laserlab.manifest import load_manifest


class ResearchModuleIntegrationTests(unittest.TestCase):
    def test_local_imports_are_persisted_and_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            experiment = root / "experiment"
            app_api.create_experiment(experiment)

            trials = root / "trials.json"
            trials.write_text(
                json.dumps(
                    {
                        "trials": [
                            {"trial_id": "s1", "stimulus_truth": True, "response": "yes", "confidence": 0.8},
                            {"trial_id": "s2", "stimulus_truth": True, "response": "no", "confidence": 0.6},
                            {"trial_id": "n1", "stimulus_truth": False, "response": "yes", "confidence": 0.5},
                            {"trial_id": "n2", "stimulus_truth": False, "response": "no", "confidence": 0.9},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            trial_payload = app_api.import_psychophysics_trials(experiment, trials)
            self.assertEqual(trial_payload["analysis"]["analysis_status"], "tested")

            reference = root / "reference.json"
            reference.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "id": "community-1",
                                "laser_wavelength": 532,
                                "pattern": "cross",
                                "observed_code": "context-only",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            reference_payload = app_api.import_external_dataset_reference(experiment, reference)
            self.assertEqual(reference_payload["records"][0]["context"]["evidence_role"], "context_only")

            symbols = root / "symbols.json"
            symbols.write_text(
                json.dumps(
                    [
                        {
                            "pseudonymous_id": "observer-1",
                            "coordinate_x": 12,
                            "coordinate_y": 8,
                            "coordinate_space": "pixels",
                            "timestamp_seconds": 2.5,
                            "wavelength_nm": 532,
                            "laser_pattern_type": "cross",
                            "transcription": "K-7",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            symbol_payload = app_api.import_symbol_transcriptions(experiment, symbols)
            self.assertEqual(symbol_payload["records"][0]["evidence_role"], "context_only")

            with self.assertRaises(ValueError):
                app_api.export_symbol_transcriptions_csv(experiment, root / "blocked.csv")
            exported = app_api.export_symbol_transcriptions_csv(
                experiment,
                root / "symbols.csv",
                privacy_acknowledged=True,
            )
            self.assertTrue(exported.exists())

            manifest = load_manifest(experiment)
            payload = build_unblind_payload([], [], manifest)
            sealed = seal_manifest(manifest)
            self.assertIsNone(sealed["psychophysics_trials"])
            self.assertEqual(sealed["psychophysics_analysis"], {"sealed": True})
            self.assertEqual(sealed["external_dataset_references"], [])
            self.assertIsNone(sealed["symbol_transcriptions"])
            restored = restore_manifest(sealed, payload)
            self.assertEqual(restored["psychophysics_analysis"]["analysis_status"], "tested")
            self.assertEqual(len(restored["external_dataset_references"]), 1)
            self.assertEqual(len(restored["symbol_transcriptions"]["records"]), 1)


if __name__ == "__main__":
    unittest.main()
