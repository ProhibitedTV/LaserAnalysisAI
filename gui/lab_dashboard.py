"""LaserLab desktop dashboard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from PyQt5.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from laserlab import app_api
from laserlab.fixtures import list_fixtures


class ApiWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task: Callable[[], Any]):
        super().__init__()
        self._task = task

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._task())
        except Exception as exc:  # pragma: no cover - exercised by manual GUI use
            self.failed.emit(str(exc))


class LabDashboardWindow(QMainWindow):
    """Main desktop dashboard for LaserLab experiments."""

    def __init__(self):
        super().__init__()
        self.experiment_dir: Path | None = None
        self.latest_report: dict[str, Any] | None = None
        self.worker: ApiWorker | None = None
        self._build_ui()
        self._apply_style()
        self._load_fixtures()

    def _build_ui(self) -> None:
        self.setWindowTitle("LaserLab")
        self.resize(1280, 820)

        file_menu = self.menuBar().addMenu("File")
        open_report = QAction("Open Latest Report", self)
        open_report.triggered.connect(self.open_report_html)
        file_menu.addAction(open_report)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._experiment_tab(), "Experiment")
        self.tabs.addTab(self._run_tab(), "Run")
        self.tabs.addTab(self._review_tab(), "Review")
        self.tabs.addTab(self._fixtures_tab(), "Fixtures")
        self.tabs.addTab(self._settings_tab(), "Settings")
        self.setCentralWidget(self.tabs)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    def _experiment_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        experiment_group = QGroupBox("Experiment")
        experiment_layout = QGridLayout(experiment_group)
        self.experiment_path = QLineEdit("experiments\\dashboard")
        browse_exp = QPushButton("Browse")
        browse_exp.clicked.connect(self.browse_experiment)
        open_exp = QPushButton("Open")
        open_exp.clicked.connect(self.open_experiment)
        experiment_layout.addWidget(QLabel("Directory"), 0, 0)
        experiment_layout.addWidget(self.experiment_path, 0, 1)
        experiment_layout.addWidget(browse_exp, 0, 2)
        experiment_layout.addWidget(open_exp, 0, 3)
        layout.addWidget(experiment_group)

        source_group = QGroupBox("Sources")
        source_layout = QGridLayout(source_group)
        self.source_path = QLineEdit()
        browse_source = QPushButton("Browse")
        browse_source.clicked.connect(self.browse_source)
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["video", "image-set"])
        self.label_combo = QComboBox()
        self.label_combo.addItems(["laser", "control"])
        self.all_frames = QCheckBox("All frames")
        self.frame_interval = QSpinBox()
        self.frame_interval.setRange(1, 10000)
        self.frame_interval.setValue(5)
        self.max_frames = QSpinBox()
        self.max_frames.setRange(0, 1000000)
        self.max_frames.setSpecialValueText("No cap")
        self.max_frames.setValue(24)
        self.add_capture_button = QPushButton("Add Capture")
        self.add_capture_button.clicked.connect(self.add_capture)

        source_layout.addWidget(QLabel("Path"), 0, 0)
        source_layout.addWidget(self.source_path, 0, 1, 1, 4)
        source_layout.addWidget(browse_source, 0, 5)
        source_layout.addWidget(QLabel("Kind"), 1, 0)
        source_layout.addWidget(self.kind_combo, 1, 1)
        source_layout.addWidget(QLabel("Label"), 1, 2)
        source_layout.addWidget(self.label_combo, 1, 3)
        source_layout.addWidget(self.all_frames, 1, 4)
        source_layout.addWidget(self.add_capture_button, 1, 5)
        source_layout.addWidget(QLabel("Frame interval"), 2, 0)
        source_layout.addWidget(self.frame_interval, 2, 1)
        source_layout.addWidget(QLabel("Max frames"), 2, 2)
        source_layout.addWidget(self.max_frames, 2, 3)
        layout.addWidget(source_group)

        self.capture_table = QTableWidget(0, 5)
        self.capture_table.setHorizontalHeaderLabels(["Capture ID", "Label", "Kind", "Frames", "Source"])
        self.capture_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.capture_table, 1)
        return page

    def _run_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        controls = QGroupBox("Run")
        form = QFormLayout(controls)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["baseline", "wide"])
        self.blind_seed = QSpinBox()
        self.blind_seed.setRange(1, 2147483647)
        self.blind_seed.setValue(20260710)
        self.run_button = QPushButton("Run Analysis")
        self.run_button.clicked.connect(self.run_analysis)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        form.addRow("Profile", self.profile_combo)
        form.addRow("Blind seed", self.blind_seed)
        form.addRow(self.run_button, self.progress)
        layout.addWidget(controls)

        actions = QHBoxLayout()
        open_report = QPushButton("Open HTML Report")
        open_report.clicked.connect(self.open_report_html)
        export_csv = QPushButton("Export Candidates CSV")
        export_csv.clicked.connect(self.export_candidates)
        refresh = QPushButton("Refresh Review")
        refresh.clicked.connect(self.refresh_review)
        actions.addWidget(open_report)
        actions.addWidget(export_csv)
        actions.addWidget(refresh)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.run_log = QTextEdit()
        self.run_log.setReadOnly(True)
        layout.addWidget(self.run_log, 1)
        return page

    def _review_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        metrics = QGroupBox("Evidence")
        grid = QGridLayout(metrics)
        self.metric_labels: dict[str, QLabel] = {}
        labels = [
            ("evidence_ladder", "Evidence"),
            ("laser_mean_score", "Laser mean"),
            ("control_mean_score", "Control mean"),
            ("mean_difference", "Difference"),
            ("permutation_p_value", "Permutation p"),
            ("sample_count", "Samples"),
        ]
        for index, (key, label) in enumerate(labels):
            name = QLabel(label)
            value = QLabel("n/a")
            value.setObjectName("metricValue")
            self.metric_labels[key] = value
            grid.addWidget(name, index // 3 * 2, index % 3)
            grid.addWidget(value, index // 3 * 2 + 1, index % 3)
        layout.addWidget(metrics)

        splitter = QSplitter(Qt.Horizontal)
        self.candidate_table = QTableWidget(0, 8)
        self.candidate_table.setHorizontalHeaderLabels(
            ["Blind ID", "Label", "Score", "Persist", "Variant", "Source", "OCR", "Processed"]
        )
        self.candidate_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.candidate_table.itemSelectionChanged.connect(self.show_selected_candidate)
        splitter.addWidget(self.candidate_table)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        self.preview_label = QLabel("No candidate selected")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(360, 280)
        self.preview_label.setObjectName("preview")
        self.ocr_text = QTextEdit()
        self.ocr_text.setReadOnly(True)
        preview_layout.addWidget(self.preview_label, 2)
        preview_layout.addWidget(self.ocr_text, 1)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        return page

    def _fixtures_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.fixture_table = QTableWidget(0, 5)
        self.fixture_table.setHorizontalHeaderLabels(["ID", "Title", "Label", "License", "Source"])
        self.fixture_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.fixture_table, 1)

        demo = QGroupBox("Demo")
        demo_layout = QGridLayout(demo)
        self.demo_experiment_path = QLineEdit("experiments\\dashboard-demo")
        self.demo_max_frames = QSpinBox()
        self.demo_max_frames.setRange(1, 1000)
        self.demo_max_frames.setValue(8)
        self.demo_profile = QComboBox()
        self.demo_profile.addItems(["baseline", "wide"])
        self.run_demo_button = QPushButton("Run Fixture Demo")
        self.run_demo_button.clicked.connect(self.run_fixture_demo)
        demo_layout.addWidget(QLabel("Experiment"), 0, 0)
        demo_layout.addWidget(self.demo_experiment_path, 0, 1, 1, 4)
        demo_layout.addWidget(QLabel("Max frames"), 1, 0)
        demo_layout.addWidget(self.demo_max_frames, 1, 1)
        demo_layout.addWidget(QLabel("Profile"), 1, 2)
        demo_layout.addWidget(self.demo_profile, 1, 3)
        demo_layout.addWidget(self.run_demo_button, 1, 4)
        layout.addWidget(demo)
        return page

    def _settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        info = QTextEdit()
        info.setReadOnly(True)
        info.setPlainText(
            "Python: " + os.sys.executable + "\n"
            "Bundled fixtures: sample_media\n"
            "Generated experiments: experiments\n"
            "Release bundle: dist\\LaserLab-windows.zip\n"
        )
        layout.addWidget(info)
        return page

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f7fafc; color: #17202a; font-size: 12px; }
            QTabWidget::pane, QGroupBox, QTableWidget, QTextEdit, QLineEdit, QComboBox, QSpinBox {
                border: 1px solid #cbd5e1;
            }
            QGroupBox { margin-top: 10px; padding: 8px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QPushButton { padding: 6px 10px; border: 1px solid #9fb3c8; background: #ffffff; }
            QPushButton:hover { background: #eef4f9; }
            QHeaderView::section { background: #d9e2ec; padding: 5px; border: 0; }
            QLabel#metricValue { font-size: 20px; font-weight: 700; color: #102a43; }
            QLabel#preview { background: #ffffff; border: 1px solid #cbd5e1; }
            """
        )

    def browse_experiment(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Experiment Directory", self.experiment_path.text())
        if path:
            self.experiment_path.setText(path)

    def browse_source(self) -> None:
        if self.kind_combo.currentText() == "image-set":
            path = QFileDialog.getExistingDirectory(self, "Image Set", "")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Video Source", "", "Videos (*.mp4 *.avi *.mov *.mkv *.webm *.ogv);;All files (*.*)"
            )
        if path:
            self.source_path.setText(path)

    def open_experiment(self) -> None:
        try:
            experiment_dir = Path(self.experiment_path.text())
            manifest = app_api.create_experiment(experiment_dir)
            self.experiment_dir = experiment_dir
            self._populate_captures(manifest)
            self.status.showMessage(f"Experiment open: {self.experiment_dir}")
            self.refresh_review(silent=True)
        except Exception as exc:
            self._error(str(exc))

    def add_capture(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        if not self.source_path.text().strip():
            self._error("Choose a source path before adding a capture.")
            return
        source = Path(self.source_path.text())
        max_frames = None if self.max_frames.value() == 0 else self.max_frames.value()

        def task() -> dict[str, Any]:
            return app_api.add_capture(
                experiment_dir=experiment,
                source=source,
                kind=self.kind_combo.currentText(),
                label=self.label_combo.currentText(),
                all_frames=self.all_frames.isChecked(),
                frame_interval=self.frame_interval.value(),
                max_frames=max_frames,
            )

        self._run_worker("Adding capture", task, self._capture_added)

    def run_analysis(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return

        def task() -> dict[str, Any]:
            return app_api.run_analysis(
                experiment_dir=experiment,
                profile=self.profile_combo.currentText(),
                blind_seed=self.blind_seed.value(),
            )

        self._run_worker("Running analysis", task, self._analysis_finished)

    def run_fixture_demo(self) -> None:
        self.experiment_path.setText(self.demo_experiment_path.text())
        self.experiment_dir = Path(self.demo_experiment_path.text())
        profile = self.demo_profile.currentText()
        max_frames = self.demo_max_frames.value()

        def task() -> dict[str, Any]:
            experiment = app_api.create_experiment(self.experiment_dir)
            if not experiment.get("captures"):
                app_api.add_capture(
                    self.experiment_dir,
                    Path("sample_media") / "commons-young-double-slit.ogv",
                    "video",
                    "laser",
                    all_frames=True,
                    max_frames=max_frames,
                )
                app_api.add_capture(
                    self.experiment_dir,
                    Path("sample_media") / "commons-double-slit-experiment.webm",
                    "video",
                    "control",
                    all_frames=True,
                    max_frames=max_frames,
                )
            run_record = app_api.run_analysis(self.experiment_dir, profile=profile, blind_seed=20260710)
            return {"manifest": experiment, "run": run_record}

        self._run_worker("Running fixture demo", task, self._demo_finished)

    def refresh_review(self, silent: bool = False) -> None:
        if not self.experiment_dir:
            if not silent:
                self._error("Open an experiment first.")
            return
        try:
            self.latest_report = app_api.load_latest_report(self.experiment_dir)
            self._populate_report(self.latest_report)
            if not silent:
                self.status.showMessage("Review refreshed")
        except Exception as exc:
            if not silent:
                self._error(str(exc))

    def open_report_html(self) -> None:
        if not self.latest_report:
            self.refresh_review(silent=True)
        if not self.latest_report:
            self._error("No report available.")
            return
        path = self.latest_report.get("local_paths", {}).get("report_html")
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))

    def export_candidates(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Candidates", "candidate_export.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            exported = app_api.export_candidates_csv(experiment, Path(path))
            self.status.showMessage(f"Exported {exported}")
        except Exception as exc:
            self._error(str(exc))

    def show_selected_candidate(self) -> None:
        if not self.latest_report:
            return
        selected = self.candidate_table.currentRow()
        candidates = self.latest_report.get("top_candidates", [])
        if selected < 0 or selected >= len(candidates):
            return
        candidate = candidates[selected]
        details = [
            f"Sample: {candidate.get('sample_id', '')}",
            f"Source: {candidate.get('source_path', '')}",
            f"Frame: {candidate.get('frame_index', 'n/a')}",
            f"Control: {candidate.get('control_type') or 'n/a'}",
            "",
            candidate.get("ocr_text", ""),
        ]
        self.ocr_text.setPlainText("\n".join(str(item) for item in details))
        self.preview_label.clear()
        processed = candidate.get("processed_path")
        if processed and self.experiment_dir:
            image_path = self.experiment_dir / processed
            if image_path.exists():
                pixmap = QPixmap(str(image_path))
                self.preview_label.setPixmap(pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio))
                return
        self.preview_label.setText("Preview unavailable")

    def _run_worker(self, label: str, task: Callable[[], Any], on_success: Callable[[Any], None]) -> None:
        if self.worker and self.worker.isRunning():
            self._error("A task is already running.")
            return
        self.progress.setRange(0, 0)
        self._set_busy(True)
        self.status.showMessage(label)
        self.run_log.append(label + "...")
        self.worker = ApiWorker(task)
        self.worker.finished_ok.connect(lambda result: self._worker_success(result, on_success))
        self.worker.failed.connect(self._worker_failed)
        self.worker.start()

    def _worker_success(self, result: Any, on_success: Callable[[Any], None]) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self._set_busy(False)
        on_success(result)

    def _worker_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self._set_busy(False)
        self.run_log.append("Error: " + message)
        self._error(message)

    def _capture_added(self, manifest: dict[str, Any]) -> None:
        self._populate_captures(manifest)
        self.run_log.append("Capture added.")
        self.status.showMessage("Capture added")

    def _analysis_finished(self, run_record: dict[str, Any]) -> None:
        stats = run_record.get("aggregate_statistics", {})
        self.run_log.append(f"Run complete: {run_record.get('run_id')}")
        self.run_log.append(f"Evidence ladder: {stats.get('evidence_ladder', 'n/a')}")
        self.refresh_review(silent=True)
        self.tabs.setCurrentIndex(2)
        self.status.showMessage("Analysis complete")

    def _demo_finished(self, payload: dict[str, Any]) -> None:
        self._analysis_finished(payload["run"])
        try:
            self._populate_captures(app_api.create_experiment(self.experiment_dir))
        except Exception:
            pass

    def _populate_captures(self, manifest: dict[str, Any]) -> None:
        captures = manifest.get("captures", [])
        self.capture_table.setRowCount(len(captures))
        for row, capture in enumerate(captures):
            source_id = capture.get("source_id", "")
            values = [
                capture.get("capture_id", ""),
                capture.get("label", ""),
                capture.get("kind", ""),
                str(len(capture.get("frames", []))),
                source_id,
            ]
            for column, value in enumerate(values):
                self.capture_table.setItem(row, column, QTableWidgetItem(value))

    def _populate_report(self, report: dict[str, Any]) -> None:
        stats = report.get("aggregate_statistics", {})
        for key, label in self.metric_labels.items():
            value = stats.get(key)
            label.setText("n/a" if value is None else str(value))

        candidates = report.get("top_candidates", [])
        self.candidate_table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            values = [
                candidate.get("blind_id", ""),
                candidate.get("unblinded_label", ""),
                str(candidate.get("structure_score", "")),
                str(candidate.get("persistence_score", "")),
                candidate.get("preprocessing_variant", ""),
                candidate.get("source_path", "")[:80],
                candidate.get("ocr_text", "")[:80],
                candidate.get("processed_path", ""),
            ]
            for column, value in enumerate(values):
                self.candidate_table.setItem(row, column, QTableWidgetItem(value))
        if candidates:
            self.candidate_table.selectRow(0)

    def _load_fixtures(self) -> None:
        fixtures = list_fixtures(include_restricted=True)
        self.fixture_table.setRowCount(len(fixtures))
        for row, item in enumerate(fixtures):
            values = [
                item.get("id", ""),
                item.get("title", ""),
                item.get("label", ""),
                item.get("license", ""),
                item.get("source_page", ""),
            ]
            for column, value in enumerate(values):
                self.fixture_table.setItem(row, column, QTableWidgetItem(value))

    def _require_experiment(self) -> Path | None:
        if not self.experiment_dir:
            self.open_experiment()
        return self.experiment_dir

    def _set_busy(self, busy: bool) -> None:
        enabled = not busy
        self.run_button.setEnabled(enabled)
        self.add_capture_button.setEnabled(enabled)
        self.run_demo_button.setEnabled(enabled)

    def _error(self, message: str) -> None:
        self.status.showMessage(message)
        QMessageBox.warning(self, "LaserLab", message)


def main() -> int:
    app = QApplication([])
    window = LabDashboardWindow()
    window.show()
    return app.exec_()
