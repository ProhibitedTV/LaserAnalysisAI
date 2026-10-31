"""Shared LaserLab presentation tokens for the dashboard and HTML reports."""

from __future__ import annotations

import html
import re
from typing import Iterable


COLORS = {
    "canvas": "#070b12",
    "surface": "#0a111b",
    "panel": "#0d1520",
    "panel_raised": "#111d29",
    "field": "#091019",
    "preview": "#05080d",
    "border": "#1f3344",
    "border_active": "#1f5260",
    "text": "#d7e3ed",
    "text_soft": "#a9bac8",
    "muted": "#7f9aaa",
    "disabled": "#526674",
    "cyan": "#35d4d4",
    "mint": "#72f1b8",
    "magenta": "#f5a6cf",
    "pink": "#ef4da8",
    "violet": "#b7a1ff",
    "amber": "#f6c56d",
    "danger": "#ff7da8",
}


EVIDENCE_TONES = {
    "blinded review": "sealed",
    "no signal": "neutral",
    "artifact": "warning",
    "anomaly": "context",
    "above-control candidate": "candidate",
    "repeatable candidate": "positive",
}


TONE_COLORS = {
    "neutral": COLORS["cyan"],
    "positive": COLORS["mint"],
    "warning": COLORS["amber"],
    "sealed": COLORS["magenta"],
    "candidate": COLORS["pink"],
    "context": COLORS["violet"],
}


def evidence_tone(value: object) -> str:
    return EVIDENCE_TONES.get(str(value or "").strip().lower(), "neutral")


def badge_tone(label: object) -> str:
    value = str(label or "").strip().lower()
    if "unblinded" in value:
        return "positive"
    if any(token in value for token in ("blinded", "sealed")):
        return "sealed"
    if any(token in value for token in ("failed", "unavailable", "warning", "not included", "not tested")):
        return "warning"
    if "context only" in value:
        return "context"
    if any(token in value for token in ("passed", "matched", "corrected")):
        return "positive"
    return "neutral"


def badge_class(label: object) -> str:
    return f"badge badge--{badge_tone(label)}"


def badge_strip_html(labels: Iterable[object]) -> str:
    badges = []
    for label in labels:
        text = html.escape(str(label))
        tone = badge_tone(label)
        color = TONE_COLORS[tone]
        badges.append(
            f'<span style="color:{color}; border:1px solid {color}; border-radius:3px; '
            f'padding:3px 7px; margin-right:5px; font-weight:600;">&#91;{text}&#93;</span>'
        )
    return "&nbsp;&nbsp;".join(badges) or f'<span style="color:{COLORS["muted"]};">No status badges</span>'


def quality_checklist_html(items: Iterable[tuple[str, bool]]) -> str:
    rows = []
    for label, passed in items:
        tone = "positive" if passed else "warning"
        color = TONE_COLORS[tone]
        status = "OK" if passed else "TODO"
        rows.append(
            f'<div style="margin:3px 0;"><span style="color:{color}; font-weight:700;">'
            f'{status}</span>&nbsp;&nbsp;{html.escape(str(label))}</div>'
        )
    return "".join(rows)


def dashboard_stylesheet() -> str:
    c = COLORS
    tones = TONE_COLORS
    return f"""
        QMainWindow, QWidget {{ background: {c['canvas']}; color: {c['text']}; font-family: "Segoe UI"; font-size: 12px; }}
        QMenuBar, QMenu, QStatusBar {{ background: {c['field']}; color: {c['text_soft']}; }}
        QTabWidget::pane {{ border: 1px solid {c['border']}; top: -1px; }}
        QTabBar::tab {{ background: {c['surface']}; color: {c['muted']}; border: 1px solid {c['border']}; padding: 9px 18px; }}
        QTabBar::tab:selected {{ color: {c['mint']}; border-bottom: 2px solid {c['cyan']}; background: {c['panel']}; }}
        QTabBar::tab:disabled {{ color: {c['disabled']}; background: {c['canvas']}; border-color: {c['border']}; }}
        QGroupBox {{ border: 1px solid {c['border']}; margin-top: 10px; padding: 9px; font-weight: 600; color: {c['text_soft']}; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['cyan']}; }}
        QGroupBox#evidencePanel {{ border-color: {c['border_active']}; background: {c['surface']}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QTableWidget {{ background: {c['field']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['border_active']}; selection-color: {c['text']}; }}
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus, QTableWidget:focus {{ border-color: {c['cyan']}; }}
        QComboBox QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['border_active']}; }}
        QCheckBox {{ color: {c['text_soft']}; spacing: 7px; }}
        QPushButton {{ background: {c['panel_raised']}; color: {c['text']}; border: 1px solid {c['border_active']}; padding: 8px 13px; min-height: 16px; }}
        QPushButton:hover {{ border-color: {c['cyan']}; color: {c['mint']}; background: {c['panel']}; }}
        QPushButton:pressed {{ background: {c['border_active']}; }}
        QPushButton:disabled {{ color: {c['disabled']}; border-color: {c['border']}; background: {c['surface']}; }}
        QPushButton#primaryButton {{ color: {c['canvas']}; background: {c['cyan']}; border-color: {c['cyan']}; font-weight: 700; }}
        QPushButton#primaryButton:hover {{ background: {c['mint']}; border-color: {c['mint']}; }}
        QPushButton#dangerButton {{ border-color: #9f396f; color: {c['magenta']}; }}
        QPushButton#dangerButton:hover {{ border-color: {c['pink']}; background: #291324; }}
        QPushButton#dangerButton:disabled {{ color: #5b4050; border-color: #382333; background: {c['surface']}; }}
        QHeaderView::section {{ background: {c['panel_raised']}; color: {c['muted']}; padding: 6px; border: 0; border-right: 1px solid {c['border']}; }}
        QTableWidget::item:selected {{ background: {c['border_active']}; color: {c['text']}; }}
        QProgressBar {{ border: 1px solid {c['border']}; background: {c['surface']}; text-align: center; color: {c['text']}; }}
        QProgressBar::chunk {{ background: {c['cyan']}; }}
        QLabel#title {{ font-size: 24px; font-weight: 700; color: {c['mint']}; }}
        QLabel#subtitle {{ font-size: 14px; color: {c['muted']}; }}
        QLabel#metricValue {{ font-size: 18px; font-weight: 700; color: {c['cyan']}; }}
        QLabel#metricValue[tone="positive"] {{ color: {tones['positive']}; }}
        QLabel#metricValue[tone="warning"] {{ color: {tones['warning']}; }}
        QLabel#metricValue[tone="sealed"] {{ color: {tones['sealed']}; }}
        QLabel#metricValue[tone="candidate"] {{ color: {tones['candidate']}; }}
        QLabel#metricValue[tone="context"] {{ color: {tones['context']}; }}
        QLabel#reviewState {{ color: {c['magenta']}; font-weight: 700; padding: 6px 0; }}
        QLabel#reviewState[unblinded="true"] {{ color: {c['mint']}; }}
        QLabel#warning {{ color: {c['amber']}; padding: 6px 2px; }}
        QLabel#badgeStrip {{ padding: 5px 0; }}
        QLabel#preview {{ background: {c['preview']}; border: 1px solid {c['border_active']}; min-height: 220px; color: {c['muted']}; }}
        QTextEdit#checklist {{ background: {c['field']}; color: {c['text_soft']}; }}
    """


def report_stylesheet() -> str:
    c = COLORS
    tones = TONE_COLORS
    return re.sub(
        r"\n[ ]{4}",
        "\n",
        f"""
    body {{ font-family: Inter, Segoe UI, sans-serif; margin: 28px; background: {c['canvas']}; color: {c['text']}; }}
    h1, h2 {{ color: {c['mint']}; }}
    .summary {{ background: {c['panel']}; border: 1px solid {c['border']}; padding: 16px; border-radius: 5px; }}
    .badge {{ display: inline-block; border: 1px solid {c['border_active']}; border-radius: 3px; padding: 4px 8px; margin: 3px 4px 3px 0; font-size: 12px; font-weight: 600; color: {c['cyan']}; }}
    .badge--positive {{ color: {tones['positive']}; border-color: {tones['positive']}; }}
    .badge--warning {{ color: {tones['warning']}; border-color: {tones['warning']}; }}
    .badge--sealed {{ color: {tones['sealed']}; border-color: {tones['sealed']}; }}
    .badge--candidate {{ color: {tones['candidate']}; border-color: {tones['candidate']}; }}
    .badge--context {{ color: {tones['context']}; border-color: {tones['context']}; }}
    .sealed {{ border-left: 3px solid {c['pink']}; padding: 10px; margin: 12px 0; color: {c['magenta']}; }}
    .metric {{ display: inline-block; margin: 8px 18px 8px 0; }}
    .metric strong {{ display: block; font-size: 12px; color: {c['muted']}; text-transform: uppercase; }}
    .evidence-value {{ font-weight: 700; color: {c['cyan']}; }}
    .evidence-value--positive {{ color: {tones['positive']}; }}
    .evidence-value--warning {{ color: {tones['warning']}; }}
    .evidence-value--sealed {{ color: {tones['sealed']}; }}
    .evidence-value--candidate {{ color: {tones['candidate']}; }}
    .evidence-value--context {{ color: {tones['context']}; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid {c['border']}; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: {c['panel_raised']}; font-size: 12px; text-transform: uppercase; color: {c['muted']}; }}
    code {{ background: {c['panel_raised']}; color: {c['mint']}; padding: 2px 4px; border-radius: 3px; }}
    img {{ max-width: 150px; max-height: 105px; border: 1px solid {c['border_active']}; }}
    .candidate-media {{ display: grid; grid-template-columns: repeat(2, minmax(90px, 1fr)); gap: 6px; min-width: 210px; }}
    .candidate-media span {{ display: block; color: {c['muted']}; font-size: 10px; text-transform: uppercase; }}
    a {{ color: {c['cyan']}; }}
        """.strip(),
    )

