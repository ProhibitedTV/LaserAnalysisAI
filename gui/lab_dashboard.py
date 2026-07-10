"""LaserLab community science dashboard."""

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
    """Guided desktop dashboard for community LaserLab experiments."""

    def __init__(self):
        super().__init__()
        self.experiment_dir: Path | None = None
        self.latest_report: dict[str, Any] | None = None
        self.worker: ApiWorker | None = None
        self.protocol_presets = app_api.list_protocol_presets()
        self._build_ui()
        self._apply_style()
        self._load_fixtures()
        self._protocol_changed()

    def _build_ui(self) -> None:
        self.setWindowTitle("LaserLab Community Science")
        self.resize(1420, 900)

        file_menu = self.menuBar().addMenu("File")
        open_report = QAction("Open Latest Report", self)
        open_report.triggered.connect(self.open_report_html)
        file_menu.addAction(open_report)
        export_bundle = QAction("Export Review Bundle", self)
        export_bundle.triggered.connect(self.export_bundle)
        file_menu.addAction(export_bundle)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._home_tab(), "Home")
        self.tabs.addTab(self._experiment_tab(), "Experiment Setup")
        self.tabs.addTab(self._protocol_tab(), "Protocol")
        self.tabs.addTab(self._run_tab(), "Run")
        self.tabs.addTab(self._review_tab(), "Review")
        self.tabs.addTab(self._compare_tab(), "Compare")
        self.tabs.addTab(self._fixtures_tab(), "Fixtures")
        self.tabs.addTab(self._export_tab(), "Export")
        self.tabs.addTab(self._settings_tab(), "Settings")
        self.setCentralWidget(self.tabs)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    def _home_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("LaserLab")
        title.setObjectName("title")
        subtitle = QLabel("A local-first blinded validation lab for laser, diffraction, speckle, and symbol-recovery experiments.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        actions = QGroupBox("Start")
        grid = QGridLayout(actions)
        self.home_demo_button = QPushButton("Run bundled demo")
        self.home_demo_button.clicked.connect(self.run_fixture_demo)
        self.home_analyze_button = QPushButton("Analyze my footage")
        self.home_analyze_button.clicked.connect(self.analyze_my_footage)
        self.home_open_button = QPushButton("Open existing experiment")
        self.home_open_button.clicked.connect(self.open_existing_experiment)
        grid.addWidget(self.home_demo_button, 0, 0)
        grid.addWidget(self.home_analyze_button, 0, 1)
        grid.addWidget(self.home_open_button, 0, 2)
        layout.addWidget(actions)

        principles = QTextEdit()
        principles.setReadOnly(True)
        principles.setPlainText(
            "LaserLab reports whether selected detections exceed matched controls under a reproducible protocol.\n\n"
            "It does not claim origin, intent, or metaphysical proof. Use controls, synthetic positives, and repeated captures."
        )
        layout.addWidget(principles, 1)
        return page

    def _experiment_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        experiment_group = QGroupBox("Experiment")
        experiment_layout = QGridLayout(experiment_group)
        self.experiment_path = QLineEdit(str(Path("experiments") / "community-demo"))
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

    def _protocol_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        protocol_group = QGroupBox("Protocol Preset")
        form = QFormLayout(protocol_group)
        self.protocol_combo = QComboBox()
        for preset in self.protocol_presets:
            self.protocol_combo.addItem(preset["name"], preset["id"])
        self.protocol_combo.setCurrentIndex(3)
        self.protocol_combo.currentIndexChanged.connect(self._protocol_changed)
        self.protocol_description = QTextEdit()
        self.protocol_description.setReadOnly(True)
        self.primary_metric_combo = QComboBox()
        self.primary_metric_combo.addItems(["structure_score", "fft_peak_prominence", "speckle_contrast", "ocr_symbol_score"])
        self.preprocessing_intensity = QComboBox()
        self.preprocessing_intensity.addItems(["standard", "wide"])
        self.control_generation = QComboBox()
        self.control_generation.addItems(["standard", "strict", "none"])
        self.frame_sampling_mode = QComboBox()
        self.frame_sampling_mode.addItems(["interval", "all_frames", "capped_all_frames"])
        form.addRow("Preset", self.protocol_combo)
        form.addRow("Primary metric", self.primary_metric_combo)
        form.addRow("Preprocessing intensity", self.preprocessing_intensity)
        form.addRow("Control generation", self.control_generation)
        form.addRow("Frame sampling mode", self.frame_sampling_mode)
        form.addRow("Description", self.protocol_description)
        layout.addWidget(protocol_group)

        advanced = QGroupBox("Advanced ROI")
        grid = QGridLayout(advanced)
        self.roi_enabled = QCheckBox("Crop analysis to ROI")
        self.roi_x = QSpinBox()
        self.roi_y = QSpinBox()
        self.roi_w = QSpinBox()
        self.roi_h = QSpinBox()
        for spin in (self.roi_x, self.roi_y, self.roi_w, self.roi_h):
            spin.setRange(0, 100000)
        self.roi_w.setValue(0)
        self.roi_h.setValue(0)
        self.apply_protocol_button = QPushButton("Save Protocol Plan")
        self.apply_protocol_button.clicked.connect(self.apply_protocol_plan)
        grid.addWidget(self.roi_enabled, 0, 0, 1, 2)
        grid.addWidget(QLabel("x"), 1, 0)
        grid.addWidget(self.roi_x, 1, 1)
        grid.addWidget(QLabel("y"), 1, 2)
        grid.addWidget(self.roi_y, 1, 3)
        grid.addWidget(QLabel("width"), 2, 0)
        grid.addWidget(self.roi_w, 2, 1)
        grid.addWidget(QLabel("height"), 2, 2)
        grid.addWidget(self.roi_h, 2, 3)
        grid.addWidget(self.apply_protocol_button, 3, 0, 1, 4)
        layout.addWidget(advanced)
        layout.addStretch(1)
        return page

    def _run_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        controls = QGroupBox("Run")
        form = QFormLayout(controls)
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["baseline", "wide", "auto"])
        self.profile_combo.setCurrentText("wide")
        self.blind_seed = QSpinBox()
        self.blind_seed.setRange(1, 2147483647)
        self.blind_seed.setValue(20260710)
        self.estimate_label = QLabel("Estimate: n/a")
        estimate = QPushButton("Estimate Run")
        estimate.clicked.connect(self.update_estimate)
        self.run_button = QPushButton("Run Analysis")
        self.run_button.clicked.connect(self.run_analysis)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        form.addRow("Profile", self.profile_combo)
        form.addRow("Blind seed", self.blind_seed)
        form.addRow(estimate, self.estimate_label)
        form.addRow(self.run_button, self.progress)
        layout.addWidget(controls)

        self.quality_checklist = QTextEdit()
        self.quality_checklist.setReadOnly(True)
        self.quality_checklist.setObjectName("checklist")
        layout.addWidget(self.quality_checklist)

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
            ("primary_metric", "Primary"),
            ("laser_mean_score", "Laser mean"),
            ("control_mean_score", "Control mean"),
            ("mean_difference", "Difference"),
            ("permutation_p_value", "Permutation p"),
            ("minimum_q_value", "Min q"),
            ("sample_count", "Samples"),
        ]
        for index, (key, label) in enumerate(labels):
            name = QLabel(label)
            value = QLabel("n/a")
            value.setObjectName("metricValue")
            self.metric_labels[key] = value
            grid.addWidget(name, index // 4 * 2, index % 4)
            grid.addWidget(value, index // 4 * 2 + 1, index % 4)
        layout.addWidget(metrics)
        self.badges_label = QLabel("Badges: n/a")
        layout.addWidget(self.badges_label)
        self.interpretation_text = QTextEdit()
        self.interpretation_text.setReadOnly(True)
        self.interpretation_text.setMaximumHeight(90)
        layout.addWidget(self.interpretation_text)

        splitter = QSplitter(Qt.Horizontal)
        self.candidate_table = QTableWidget(0, 9)
        self.candidate_table.setHorizontalHeaderLabels(
            ["Blind ID", "Label", "Score", "Persist", "q", "Variant", "Source", "OCR", "Processed"]
        )
        self.candidate_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.candidate_table.setSortingEnabled(True)
        self.candidate_table.itemSelectionChanged.connect(self.show_selected_candidate)
        splitter.addWidget(self.candidate_table)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_row = QHBoxLayout()
        self.original_preview = self._preview_label("Original")
        self.processed_preview = self._preview_label("Processed")
        self.crop_preview = self._preview_label("Candidate crop")
        preview_row.addWidget(self.original_preview)
        preview_row.addWidget(self.processed_preview)
        preview_row.addWidget(self.crop_preview)
        preview_layout.addLayout(preview_row, 2)
        overlay_row = QHBoxLayout()
        self.show_processed_overlay = QCheckBox("Processed")
        self.show_processed_overlay.setChecked(True)
        self.show_crop_overlay = QCheckBox("Crop")
        self.show_crop_overlay.setChecked(True)
        overlay_row.addWidget(QLabel("Overlays"))
        overlay_row.addWidget(self.show_processed_overlay)
        overlay_row.addWidget(self.show_crop_overlay)
        overlay_row.addStretch(1)
        preview_layout.addLayout(overlay_row)
        self.candidate_details = QTextEdit()
        self.candidate_details.setReadOnly(True)
        preview_layout.addWidget(self.candidate_details, 1)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.filmstrip_table = QTableWidget(0, 4)
        self.filmstrip_table.setHorizontalHeaderLabels(["Sample", "Frame", "Label", "Source"])
        self.filmstrip_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.filmstrip_table.setMaximumHeight(130)
        layout.addWidget(self.filmstrip_table)
        return page

    def _compare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.family_table = QTableWidget(0, 4)
        self.family_table.setHorizontalHeaderLabels(["Detector family", "Mean", "Low", "High"])
        self.family_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(QLabel("Detector-family comparison across laser samples"))
        layout.addWidget(self.family_table, 1)
        self.compare_notes = QTextEdit()
        self.compare_notes.setReadOnly(True)
        layout.addWidget(self.compare_notes)
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
        self.demo_experiment_path = QLineEdit(str(Path("experiments") / "community-demo"))
        self.demo_max_frames = QSpinBox()
        self.demo_max_frames.setRange(1, 1000)
        self.demo_max_frames.setValue(8)
        self.demo_protocol = QComboBox()
        for preset in self.protocol_presets:
            self.demo_protocol.addItem(preset["name"], preset["id"])
        self.demo_protocol.setCurrentIndex(3)
        self.run_demo_button = QPushButton("Run Fixture Demo")
        self.run_demo_button.clicked.connect(self.run_fixture_demo)
        demo_layout.addWidget(QLabel("Experiment"), 0, 0)
        demo_layout.addWidget(self.demo_experiment_path, 0, 1, 1, 4)
        demo_layout.addWidget(QLabel("Max frames"), 1, 0)
        demo_layout.addWidget(self.demo_max_frames, 1, 1)
        demo_layout.addWidget(QLabel("Protocol"), 1, 2)
        demo_layout.addWidget(self.demo_protocol, 1, 3)
        demo_layout.addWidget(self.run_demo_button, 1, 4)
        layout.addWidget(demo)
        return page

    def _export_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        actions = QGroupBox("Local-first Sharing")
        grid = QGridLayout(actions)
        open_report = QPushButton("Open HTML Report")
        open_report.clicked.connect(self.open_report_html)
        self.export_csv_button = QPushButton("Export Candidates CSV")
        self.export_csv_button.clicked.connect(self.export_candidates)
        self.export_bundle_button = QPushButton("Export Review Bundle")
        self.export_bundle_button.clicked.connect(self.export_bundle)
        self.include_media = QCheckBox("Include source media")
        grid.addWidget(open_report, 0, 0)
        grid.addWidget(self.export_csv_button, 0, 1)
        grid.addWidget(self.export_bundle_button, 0, 2)
        grid.addWidget(self.include_media, 1, 0, 1, 3)
        layout.addWidget(actions)
        self.export_log = QTextEdit()
        self.export_log.setReadOnly(True)
        self.export_log.setPlainText("Bundles include manifest, reports, top crops, hashes, environment info, and optional source media.")
        layout.addWidget(self.export_log, 1)
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
            "Release bundles: dist/LaserLab-v<version>-<platform>.zip\n"
            "Sharing: local-first review bundles; no telemetry or uploads\n"
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
            QPushButton { padding: 7px 12px; border: 1px solid #9fb3c8; background: #ffffff; }
            QPushButton:hover { background: #eef4f9; }
            QHeaderView::section { background: #d9e2ec; padding: 5px; border: 0; }
            QLabel#title { font-size: 32px; font-weight: 800; color: #102a43; }
            QLabel#subtitle { font-size: 15px; color: #52616b; }
            QLabel#metricValue { font-size: 19px; font-weight: 700; color: #102a43; }
            QLabel#preview { background: #ffffff; border: 1px solid #cbd5e1; min-height: 220px; }
            QTextEdit#checklist { background: #ffffff; }
            """
        )

    def _preview_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumSize(250, 220)
        label.setObjectName("preview")
        return label

    def analyze_my_footage(self) -> None:
        self.tabs.setCurrentIndex(1)
        self.browse_source()

    def open_existing_experiment(self) -> None:
        self.browse_experiment()
        self.open_experiment()

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
            plan = manifest.get("analysis_plan", {})
            self._set_combo_data(self.protocol_combo, plan.get("protocol", manifest.get("protocol", "anomaly")))
            self._set_combo_text(self.primary_metric_combo, plan.get("primary_metric", "structure_score"))
            self._set_combo_text(self.control_generation, plan.get("control_generation", "standard"))
            self._set_combo_text(self.preprocessing_intensity, plan.get("preprocessing_intensity", "standard"))
            self._set_combo_text(self.frame_sampling_mode, plan.get("frame_sampling_mode", "interval"))
            self.status.showMessage(f"Experiment open: {self.experiment_dir}")
            self.refresh_review(silent=True)
            self.update_estimate()
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

    def apply_protocol_plan(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        try:
            manifest = app_api.update_analysis_plan(
                experiment,
                protocol=self._current_protocol(),
                primary_metric=self.primary_metric_combo.currentText(),
                preprocessing_intensity=self.preprocessing_intensity.currentText(),
                control_generation=self.control_generation.currentText(),
                frame_sampling_mode=self.frame_sampling_mode.currentText(),
                roi=self._roi(),
            )
            self._populate_captures(manifest)
            self.update_estimate()
            self.status.showMessage("Protocol plan saved")
        except Exception as exc:
            self._error(str(exc))

    def update_estimate(self) -> None:
        if not self.experiment_dir:
            self.estimate_label.setText("Estimate: open an experiment first")
            self._update_quality_checklist({})
            return
        profile = self.profile_combo.currentText()
        if profile == "auto":
            profile = self._preset()["profile"]
        estimate = app_api.estimate_run(
            self.experiment_dir,
            profile=profile,
            protocol=self._current_protocol(),
            control_generation=self.control_generation.currentText(),
        )
        self.estimate_label.setText(
            f"{estimate['detector_records']} detector records, {estimate['runtime_label']} run"
        )
        self._update_quality_checklist(estimate)

    def run_analysis(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        profile = self.profile_combo.currentText()

        def task() -> dict[str, Any]:
            return app_api.run_analysis(
                experiment_dir=experiment,
                profile=profile,
                blind_seed=self.blind_seed.value(),
                protocol=self._current_protocol(),
                roi=self._roi(),
                primary_metric=self.primary_metric_combo.currentText(),
                preprocessing_intensity=self.preprocessing_intensity.currentText(),
                control_generation=self.control_generation.currentText(),
            )

        self._run_worker("Running analysis", task, self._analysis_finished)

    def run_fixture_demo(self) -> None:
        self.experiment_path.setText(self.demo_experiment_path.text())
        self.experiment_dir = Path(self.demo_experiment_path.text())
        protocol = self.demo_protocol.currentData() or "anomaly"
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
            preset = next((item for item in self.protocol_presets if item["id"] == protocol), self.protocol_presets[-1])
            run_record = app_api.run_analysis(
                self.experiment_dir,
                profile=preset["profile"],
                protocol=protocol,
                primary_metric=preset["primary_metric"],
                control_generation="standard",
                blind_seed=20260710,
            )
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
            self.export_log.append(f"Exported CSV: {exported}")
            self.status.showMessage(f"Exported {exported}")
        except Exception as exc:
            self._error(str(exc))

    def export_bundle(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export Review Bundle", "laserlab-review-bundle.zip", "ZIP (*.zip)")
        if not path:
            return
        try:
            exported = app_api.export_review_bundle(experiment, Path(path), include_media=self.include_media.isChecked())
            self.export_log.append(f"Exported bundle: {exported}")
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
            f"Primary metric: {candidate.get('primary_metric', 'structure_score')}",
            f"Primary score: {candidate.get('primary_metric_score', candidate.get('structure_score'))}",
            f"Control: {candidate.get('control_type') or 'n/a'}",
            f"q-value: {candidate.get('q_value')}",
            f"Families: {candidate.get('detector_family_scores', {})}",
            "",
            candidate.get("ocr_text", ""),
        ]
        self.candidate_details.setPlainText("\n".join(str(item) for item in details))
        self._load_candidate_images(candidate)

    def _load_candidate_images(self, candidate: dict[str, Any]) -> None:
        for label, text in ((self.original_preview, "Original"), (self.processed_preview, "Processed"), (self.crop_preview, "Candidate crop")):
            label.clear()
            label.setText(text)
        if not self.experiment_dir:
            return
        source = candidate.get("source_path")
        if source:
            self._set_pixmap(self.original_preview, self.experiment_dir / source)
        processed = candidate.get("processed_path")
        if processed:
            self._set_pixmap(self.processed_preview, self.experiment_dir / processed)
        rois = candidate.get("candidate_rois", [])
        if rois and rois[0].get("crop_path"):
            self._set_pixmap(self.crop_preview, self.experiment_dir / rois[0]["crop_path"])

    def _set_pixmap(self, label: QLabel, path: Path) -> None:
        if path.exists():
            pixmap = QPixmap(str(path))
            label.setPixmap(pixmap.scaled(label.size(), Qt.KeepAspectRatio))

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
        self.update_estimate()
        self.status.showMessage("Capture added")

    def _analysis_finished(self, run_record: dict[str, Any]) -> None:
        stats = run_record.get("aggregate_statistics", {})
        self.run_log.append(f"Run complete: {run_record.get('run_id')}")
        self.run_log.append(f"Evidence ladder: {stats.get('evidence_ladder', 'n/a')}")
        self.refresh_review(silent=True)
        self.tabs.setCurrentIndex(4)
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
            values = [
                capture.get("capture_id", ""),
                capture.get("label", ""),
                capture.get("kind", ""),
                str(len(capture.get("frames", []))),
                capture.get("source_id", ""),
            ]
            for column, value in enumerate(values):
                self.capture_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _populate_report(self, report: dict[str, Any]) -> None:
        stats = report.get("aggregate_statistics", {})
        summary = report.get("summary", {})
        for key, label in self.metric_labels.items():
            value = summary.get(key, stats.get(key))
            label.setText("n/a" if value is None else str(value))
        self.badges_label.setText("Badges: " + ", ".join(report.get("badges", [])))
        interpretation = report.get("interpretation", {})
        self.interpretation_text.setPlainText(
            "What this means: " + interpretation.get("what_this_means", "") + "\n"
            "What this does not mean: " + interpretation.get("what_this_does_not_mean", "")
        )

        self.candidate_table.setSortingEnabled(False)
        candidates = report.get("top_candidates", [])
        self.candidate_table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            values = [
                candidate.get("blind_id", ""),
                candidate.get("unblinded_label", ""),
                str(candidate.get("primary_metric_score", candidate.get("structure_score", ""))),
                str(candidate.get("persistence_score", "")),
                str(candidate.get("q_value", "")),
                candidate.get("preprocessing_variant", ""),
                candidate.get("source_path", "")[:80],
                candidate.get("ocr_text", "")[:80],
                candidate.get("processed_path", ""),
            ]
            for column, value in enumerate(values):
                self.candidate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.candidate_table.setSortingEnabled(True)
        if candidates:
            self.candidate_table.selectRow(0)
        self._populate_filmstrip(report)
        self._populate_family_table(stats)

    def _populate_filmstrip(self, report: dict[str, Any]) -> None:
        candidates = report.get("top_candidates", [])[:8]
        self.filmstrip_table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            values = [
                candidate.get("sample_id", ""),
                str(candidate.get("frame_index", "")),
                candidate.get("unblinded_label", ""),
                candidate.get("source_path", ""),
            ]
            for column, value in enumerate(values):
                self.filmstrip_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _populate_family_table(self, stats: dict[str, Any]) -> None:
        families = stats.get("detector_family_statistics", {})
        self.family_table.setRowCount(len(families))
        for row, (family, record) in enumerate(families.items()):
            values = [family, record.get("mean"), record.get("low"), record.get("high")]
            for column, value in enumerate(values):
                self.family_table.setItem(row, column, QTableWidgetItem("n/a" if value is None else str(value)))
        self.compare_notes.setPlainText(
            "Detector families are summaries, not separate proof claims. Use them to see which scientific lens drove the run."
        )

    def _load_fixtures(self) -> None:
        fixtures = list_fixtures(include_restricted=True)
        self.fixture_table.setRowCount(len(fixtures))
        for row, item in enumerate(fixtures):
            values = [item.get("id", ""), item.get("title", ""), item.get("label", ""), item.get("license", ""), item.get("source_page", "")]
            for column, value in enumerate(values):
                self.fixture_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _update_quality_checklist(self, estimate: dict[str, Any]) -> None:
        captures = []
        if self.experiment_dir:
            try:
                captures = app_api.create_experiment(self.experiment_dir).get("captures", [])
            except Exception:
                captures = []
        labels = {capture.get("label") for capture in captures}
        lines = [
            ("laser capture", "laser" in labels),
            ("control capture", "control" in labels),
            ("frame count >= 2", estimate.get("sample_count", 0) >= 2),
            ("matched controls enabled", self.control_generation.currentText() != "none"),
            ("multiple comparisons corrected", True),
        ]
        self.quality_checklist.setPlainText("\n".join(("OK  " if ok else "TODO ") + label for label, ok in lines))

    def _protocol_changed(self) -> None:
        preset = self._preset()
        self.protocol_description.setPlainText(
            preset["description"] + "\n\nScience options: " + ", ".join(preset.get("science", []))
        )
        self._set_combo_text(self.primary_metric_combo, preset["primary_metric"])
        self._set_combo_text(self.preprocessing_intensity, "wide" if preset["profile"] == "wide" else "standard")

    def _preset(self) -> dict[str, Any]:
        protocol = self._current_protocol()
        return next((item for item in self.protocol_presets if item["id"] == protocol), self.protocol_presets[-1])

    def _current_protocol(self) -> str:
        return self.protocol_combo.currentData() or "anomaly"

    def _roi(self) -> dict[str, int] | None:
        if not self.roi_enabled.isChecked():
            return None
        width = self.roi_w.value()
        height = self.roi_h.value()
        if width <= 0 or height <= 0:
            return None
        return {"x": self.roi_x.value(), "y": self.roi_y.value(), "width": width, "height": height}

    def _set_combo_text(self, combo: QComboBox, text: str) -> None:
        index = combo.findText(text)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_combo_data(self, combo: QComboBox, value: str) -> None:
        for index in range(combo.count()):
            if combo.itemData(index) == value:
                combo.setCurrentIndex(index)
                return

    def _require_experiment(self) -> Path | None:
        if not self.experiment_dir:
            self.open_experiment()
        return self.experiment_dir

    def _set_busy(self, busy: bool) -> None:
        enabled = not busy
        for button in (
            self.run_button,
            self.add_capture_button,
            self.run_demo_button,
            self.home_demo_button,
            self.export_csv_button,
            self.export_bundle_button,
        ):
            button.setEnabled(enabled)

    def _error(self, message: str) -> None:
        self.status.showMessage(message)
        QMessageBox.warning(self, "LaserLab", message)


def main() -> int:
    app = QApplication([])
    window = LabDashboardWindow()
    window.show()
    return app.exec_()
