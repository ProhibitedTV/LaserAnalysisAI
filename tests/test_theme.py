from __future__ import annotations

import unittest

from laserlab.theme import (
    COLORS,
    TONE_COLORS,
    badge_class,
    badge_strip_html,
    dashboard_stylesheet,
    evidence_tone,
    quality_checklist_html,
    report_stylesheet,
)


def _relative_luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255.0 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


class ThemeTests(unittest.TestCase):
    def test_core_text_and_status_colors_remain_readable_on_dark_surfaces(self) -> None:
        for color in (COLORS["text"], COLORS["text_soft"], *TONE_COLORS.values()):
            with self.subTest(color=color):
                self.assertGreaterEqual(_contrast_ratio(color, COLORS["canvas"]), 4.5)

    def test_evidence_and_badge_tones_are_stable(self) -> None:
        self.assertEqual(evidence_tone("blinded review"), "sealed")
        self.assertEqual(evidence_tone("no signal"), "neutral")
        self.assertEqual(evidence_tone("artifact"), "warning")
        self.assertEqual(evidence_tone("repeatable candidate"), "positive")
        self.assertEqual(badge_class("OCR unavailable"), "badge badge--warning")
        self.assertEqual(badge_class("review blinded"), "badge badge--sealed")
        self.assertEqual(badge_class("review unblinded"), "badge badge--positive")
        self.assertEqual(badge_class("calibration passed"), "badge badge--positive")

    def test_dashboard_and_report_share_tokens(self) -> None:
        dashboard = dashboard_stylesheet()
        report = report_stylesheet()
        for token in (COLORS["canvas"], COLORS["text"], COLORS["cyan"], COLORS["mint"]):
            self.assertIn(token, dashboard)
            self.assertIn(token, report)
        self.assertIn("badge--warning", report)
        self.assertIn('QLabel#metricValue[tone="warning"]', dashboard)

    def test_rich_status_helpers_escape_user_visible_text(self) -> None:
        badges = badge_strip_html(["warning <source>"])
        checklist = quality_checklist_html([("matched <control>", False)])
        self.assertIn("&lt;source&gt;", badges)
        self.assertIn("&lt;control&gt;", checklist)
        self.assertNotIn("<source>", badges)


if __name__ == "__main__":
    unittest.main()
