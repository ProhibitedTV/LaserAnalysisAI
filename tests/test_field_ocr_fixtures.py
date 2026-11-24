"""The public synthetic field-check images must remain valid and distinct."""
from pathlib import Path
import unittest

import cv2
import numpy as np

from laserlab.font_ocr import _source_mask


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "docs" / "field-test"


class FieldOCRFixtureTests(unittest.TestCase):
    def read_fixture(self, filename):
        image = cv2.imread(str(FIXTURE_DIR / filename), cv2.IMREAD_COLOR)
        self.assertIsNotNone(image, filename)
        self.assertEqual(image.shape, (64, 64, 3))
        self.assertEqual(image.dtype, np.uint8)
        return image

    def test_blank_control_decodes_and_abstains_at_mask_stage(self):
        image = self.read_fixture("blank.pgm")
        self.assertFalse(np.any(image))
        self.assertIsNone(_source_mask(image))

    def test_geometric_control_decodes_with_high_contrast_and_valid_mask(self):
        image = self.read_fixture("geometric.pgm")
        self.assertEqual(set(np.unique(image)), {0, 255})
        self.assertEqual(int(np.count_nonzero(image[:, :, 0])), 433)
        mask = _source_mask(image)
        self.assertIsNotNone(mask)
        self.assertEqual(mask.shape, (64, 64))
        self.assertGreater(int(np.count_nonzero(mask)), 0)


if __name__ == "__main__":
    unittest.main()
