"""Review the exact media-free exchange before selecting a local output file."""
from __future__ import annotations

import json

from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel,
    QPlainTextEdit, QVBoxLayout,
)


class ResearchExchangeDialog(QDialog):
    def __init__(self, preview: dict, preview_builder, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Review local results exchange")
        self.resize(850, 650)
        self.preview_builder = preview_builder
        self.preview = preview
        layout = QVBoxLayout(self)
        note = QLabel("Review the exact JSON below, including consent and sharing rights. Saving creates a local file; it does not submit results to Veilbreak. Settings and outcomes may still disclose context.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.hashes = QCheckBox("Include recorded source hashes (can link recordings across exports)")
        layout.addWidget(self.hashes)
        self.reference = QComboBox()
        self.reference.setAccessibleName("Optional linked community reference")
        self.reference.addItem("No community reference ID", None)
        for choice in preview["_reference_choices"]:
            self.reference.addItem(f"Veilbreak {choice['record_type']} #{choice['record_id']}", choice)
        layout.addWidget(self.reference)
        self.document = QPlainTextEdit()
        self.document.setReadOnly(True)
        layout.addWidget(self.document, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.privacy = QCheckBox("I reviewed this exact preview and the consent, privacy and attribution requirements.")
        layout.addWidget(self.privacy)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.Save)
        self.save_button.setEnabled(False)
        buttons.accepted.connect(self._accept_review)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.hashes.toggled.connect(self._refresh)
        self.reference.currentIndexChanged.connect(self._refresh)
        self.privacy.toggled.connect(lambda checked: self.save_button.setEnabled(checked and self.preview is not None))
        self._show_document()

    def options(self) -> dict:
        return {"include_source_hashes": self.hashes.isChecked(), "reference": self.reference.currentData()}

    def _accept_review(self) -> None:
        if self.preview is not None and self.privacy.isChecked():
            self.accept()

    def _show_document(self) -> None:
        document = self.preview["document"]
        findings = document.get("findings") or {}
        privacy = document.get("privacy") or {}
        purpose = "Practice demo" if document.get("experiment_purpose") == "practice_demo" else "Saved analysis"
        self.summary.setText(f"{purpose}: {findings.get('evidence_level', 'not tested')}. "
                             f"Declared independent pairs: {findings.get('declared_independent_pair_count', 'unknown')}. "
                             f"Source hashes: {'included' if privacy.get('source_hashes_included') else 'excluded'}. "
                             f"Community reference ID: {'included' if document.get('community_references') else 'excluded'}.")
        self.document.setPlainText(json.dumps(document, indent=2, sort_keys=True, allow_nan=False))
        self.message.setText("Changing options requires a fresh review. Source files and saved results are preserved.")

    def _refresh(self, *_args) -> None:
        self.privacy.setChecked(False)
        self.save_button.setEnabled(False)
        try:
            self.preview = self.preview_builder(**self.options())
            self._show_document()
        except Exception:
            self.preview = None
            self.document.clear()
            self.summary.clear()
            self.message.setText("The saved experiment could not be refreshed. Close this preview and check the current review state before trying again.")
