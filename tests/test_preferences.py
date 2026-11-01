from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from laserlab.preferences import (
    MAX_RECENT_EXPERIMENTS,
    SCHEMA_VERSION,
    load_preferences,
    remember_experiment,
    save_preferences,
    set_last_source_directory,
    set_veilbreak_cache_enabled,
)


class PreferencesTests(unittest.TestCase):
    def test_cache_is_off_unless_explicitly_enabled_and_navigation_preserves_choice(self):
        self.assertFalse(load_preferences(self.preferences_file)["veilbreak_cache_enabled"])
        for value in ("true", 1, {}, []):
            with self.assertRaises(ValueError):
                set_veilbreak_cache_enabled(value, self.preferences_file)
            saved = save_preferences({"veilbreak_cache_enabled": value}, self.preferences_file)
            self.assertFalse(saved["veilbreak_cache_enabled"])
        set_veilbreak_cache_enabled(True, self.preferences_file)
        experiment = self._directory("with-cache")
        remember_experiment(experiment, self.preferences_file)
        self.assertTrue(load_preferences(self.preferences_file)["veilbreak_cache_enabled"])
        set_veilbreak_cache_enabled(False, self.preferences_file)
        saved = load_preferences(self.preferences_file)
        self.assertFalse(saved["veilbreak_cache_enabled"])
        self.assertEqual(saved["recent_experiments"], [str(experiment.resolve())])

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.preferences_file = self.root / "state" / "preferences.json"

    def _directory(self, name: str) -> Path:
        directory = self.root / name
        directory.mkdir()
        return directory

    def test_round_trip_writes_only_the_allow_listed_schema(self) -> None:
        experiment = self._directory("experiment")
        source = self._directory("source")

        saved = save_preferences(
            {
                "schema_version": 999,
                "recent_experiments": [str(experiment)],
                "last_source_directory": str(source),
                "labels": ["laser", "control"],
                "media_metadata": {"camera": "private"},
            },
            self.preferences_file,
        )

        self.assertEqual(load_preferences(self.preferences_file), saved)
        on_disk = json.loads(self.preferences_file.read_text(encoding="utf-8"))
        self.assertEqual(
            set(on_disk),
            {"schema_version", "recent_experiments", "last_source_directory", "veilbreak_cache_enabled"},
        )
        self.assertEqual(on_disk["schema_version"], SCHEMA_VERSION)
        self.assertEqual(on_disk["recent_experiments"], [str(experiment.resolve())])
        self.assertEqual(on_disk["last_source_directory"], str(source.resolve()))

    def test_remember_deduplicates_moves_to_front_and_keeps_five(self) -> None:
        experiments = [self._directory(f"experiment-{index}") for index in range(6)]
        for experiment in experiments:
            remember_experiment(experiment, self.preferences_file)

        remember_experiment(experiments[2], self.preferences_file)
        recent = load_preferences(self.preferences_file)["recent_experiments"]

        self.assertEqual(len(recent), MAX_RECENT_EXPERIMENTS)
        self.assertEqual(
            recent,
            [
                str(experiments[2].resolve()),
                str(experiments[5].resolve()),
                str(experiments[4].resolve()),
                str(experiments[3].resolve()),
                str(experiments[1].resolve()),
            ],
        )

    def test_corrupt_and_wrong_shape_files_recover_to_defaults(self) -> None:
        self.preferences_file.parent.mkdir(parents=True)
        default = {
            "schema_version": SCHEMA_VERSION,
            "recent_experiments": [],
            "last_source_directory": None,
            "veilbreak_cache_enabled": False,
        }


        self.preferences_file.write_text("{not-json", encoding="utf-8")
        self.assertEqual(load_preferences(self.preferences_file), default)

        self.preferences_file.write_text(json.dumps(["wrong", "shape"]), encoding="utf-8")
        self.assertEqual(load_preferences(self.preferences_file), default)

        experiment = self._directory("recovered-experiment")
        recovered = remember_experiment(experiment, self.preferences_file)
        self.assertEqual(recovered["recent_experiments"], [str(experiment.resolve())])
        self.assertEqual(load_preferences(self.preferences_file), recovered)

    def test_load_prunes_missing_experiment_directories(self) -> None:
        present = self._directory("present")
        removed = self._directory("removed")
        save_preferences(
            {"recent_experiments": [str(removed), str(present)]},
            self.preferences_file,
        )
        removed.rmdir()

        loaded = load_preferences(self.preferences_file)

        self.assertEqual(loaded["recent_experiments"], [str(present.resolve())])

    def test_last_source_directory_is_stored_without_changing_recents(self) -> None:
        experiment = self._directory("experiment-with-source")
        source = self._directory("last-source")
        remember_experiment(experiment, self.preferences_file)

        saved = set_last_source_directory(source, self.preferences_file)

        self.assertEqual(saved["last_source_directory"], str(source.resolve()))
        self.assertEqual(saved["recent_experiments"], [str(experiment.resolve())])
        self.assertEqual(load_preferences(self.preferences_file), saved)


if __name__ == "__main__":
    unittest.main()
