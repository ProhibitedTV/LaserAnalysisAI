"""Local search and paging of already allow-listed public catalog records."""
from __future__ import annotations

import json
from typing import Any

from PyQt5.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class VeilbreakCatalogDialog(QDialog):
    PAGE_SIZE = 50

    def __init__(self, kind: str, records: list[dict[str, Any]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Veilbreak public references")
        self.resize(800, 520)
        self.records = records
        self.page = 0
        self._page_records: list[dict[str, Any]] = []
        layout = QVBoxLayout(self)
        note = QLabel("Search the downloaded public catalog locally. Published metadata is context, not a measurement of your setup.")
        note.setWordWrap(True)
        layout.addWidget(note)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title, equipment or tags")
        self.search.setAccessibleName("Search public references")
        self.wavelength = QDoubleSpinBox()
        self.wavelength.setRange(0, 100000)
        self.wavelength.setDecimals(1)
        self.wavelength.setSpecialValueText("Any wavelength")
        self.wavelength.setSuffix(" nm")
        self.wavelength.setAccessibleName("Reported wavelength in nanometers; zero means any")
        filters.addWidget(self.search, 1)
        filters.addWidget(self.wavelength)
        layout.addLayout(filters)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Published reference", "Reported wavelength"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table, 1)
        paging = QHBoxLayout()
        self.previous = QPushButton("Previous")
        self.next = QPushButton("Next")
        self.count = QLabel()
        paging.addWidget(self.previous)
        paging.addWidget(self.count, 1)
        paging.addWidget(self.next)
        layout.addLayout(paging)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.use_button = buttons.addButton(f"Use selected {kind[:-1]} as reference", QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search.textChanged.connect(self._reset_filter)
        self.wavelength.valueChanged.connect(self._reset_filter)
        self.previous.clicked.connect(lambda: self._change_page(-1))
        self.next.clicked.connect(lambda: self._change_page(1))
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(self._accept_selection)
        self._render()

    def selected_record(self) -> dict[str, Any] | None:
        row = self.table.currentRow()
        return self._page_records[row] if 0 <= row < len(self._page_records) else None

    def _accept_selection(self, *_args) -> None:
        if self.selected_record() is not None:
            self.accept()

    def _selection_changed(self) -> None:
        self.use_button.setEnabled(self.selected_record() is not None)

    def _reset_filter(self, *_args) -> None:
        self.page = 0
        self._render()

    def _change_page(self, delta: int) -> None:
        self.page += delta
        self._render()

    def _render(self) -> None:
        terms = self.search.text().casefold().split()
        wavelength = self.wavelength.value()
        filtered = []
        for record in self.records:
            optical = record.get("optical_metadata") or {}
            text = json.dumps([record.get("record_id"), record.get("title"), optical.get("equipment"), optical.get("tags")], ensure_ascii=False).casefold()
            if all(term in text for term in terms) and (
                wavelength == 0 or optical.get("wavelength_nm") == wavelength
            ):
                filtered.append(record)
        self.page = max(0, min(self.page, (len(filtered) - 1) // self.PAGE_SIZE))
        start = self.page * self.PAGE_SIZE
        self._page_records = filtered[start:start + self.PAGE_SIZE]
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._page_records))
        for row, record in enumerate(self._page_records):
            value = (record.get("optical_metadata") or {}).get("wavelength_nm")
            values = (str(record["record_id"]), record["title"], f"{value:g} nm" if isinstance(value, (int, float)) else "Unknown")
            for column, text in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.count.setText(f"{start + 1 if filtered else 0}–{start + len(self._page_records)} of {len(filtered)} matches ({len(self.records)} loaded)")
        self.previous.setEnabled(self.page > 0)
        self.next.setEnabled(start + self.PAGE_SIZE < len(filtered))
        if self._page_records:
            self.table.selectRow(0)
        self._selection_changed()
