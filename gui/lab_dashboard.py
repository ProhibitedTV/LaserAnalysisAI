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
from laserlab.fixtures import fixture_metadata, list_fixtures


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
        self.tabs.addTab(self._setup_tab(), "Setup")
        self.tabs.addTab(self._run_tab(), "Run")
        self.tabs.addTab(self._review_tab(), "Review")
        self.tabs.addTab(self._compare_tab(), "Compare")
        self.tabs.addTab(self._export_tab(), "Export")
        self.setCentralWidget(self.tabs)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    def _setup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("LaserLab / blinded signal review")
        title.setObjectName("title")
        subtitle = QLabel("Observed patterns deserve careful testing. Source roles stay sealed until you explicitly unblind.")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        actions = QGroupBox("Start")
        action_layout = QHBoxLayout(actions)
        self.home_demo_button = QPushButton("Run bundled demo")
        self.home_demo_button.clicked.connect(self.run_fixture_demo)
        self.home_analyze_button = QPushButton("Analyze footage")
        self.home_analyze_button.clicked.connect(self.analyze_my_footage)
        self.home_open_button = QPushButton("Open experiment")
        self.home_open_button.clicked.connect(self.open_existing_experiment)
        action_layout.addWidget(self.home_demo_button)
        action_layout.addWidget(self.home_analyze_button)
        action_layout.addWidget(self.home_open_button)
        action_layout.addStretch(1)
        layout.addWidget(actions)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._experiment_tab())
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._protocol_tab(), 2)
        right_layout.addWidget(self._fixtures_tab(), 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)
        return page

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
        self.capture_table.verticalHeader().setVisible(False)
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
        self.protocol_description.setMaximumHeight(86)
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
        state_row = QHBoxLayout()
        self.review_state_label = QLabel("BLINDED / source roles sealed")
        self.review_state_label.setObjectName("reviewState")
        self.unblind_button = QPushButton("Unblind and compare")
        self.unblind_button.setObjectName("dangerButton")
        self.unblind_button.clicked.connect(self.unblind_review)
        state_row.addWidget(self.review_state_label)
        state_row.addStretch(1)
        state_row.addWidget(self.unblind_button)
        layout.addLayout(state_row)
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
        self.candidate_table = QTableWidget(0, 6)
        self.candidate_table.setHorizontalHeaderLabels(["Blind ID", "Score", "Persist", "Variant", "OCR", "Processed"])
        self.candidate_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.candidate_table.verticalHeader().setVisible(False)
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

        self.filmstrip_table = QTableWidget(0, 2)
        self.filmstrip_table.setHorizontalHeaderLabels(["Blind ID", "Score"])
        self.filmstrip_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.filmstrip_table.verticalHeader().setVisible(False)
        self.filmstrip_table.setMaximumHeight(130)
        layout.addWidget(self.filmstrip_table)
        return page

    def _compare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.family_table = QTableWidget(0, 4)
        self.family_table.setHorizontalHeaderLabels(["Detector family", "Mean", "Low", "High"])
        self.family_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.family_table.verticalHeader().setVisible(False)
        layout.addWidget(QLabel("Detector-family comparison across laser samples"))
        layout.addWidget(self.family_table, 1)
        self.compare_notes = QTextEdit()
        self.compare_notes.setReadOnly(True)
        layout.addWidget(self.compare_notes)
        return page

    def _fixtures_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.fixture_table = QTableWidget(0, 7)
        self.fixture_table.setHorizontalHeaderLabels(
            ["ID", "Title", "Label", "Phenomena", "License", "Expected behavior", "Source"]
        )
        self.fixture_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.fixture_table.verticalHeader().setVisible(False)
        self.fixture_table.setMaximumHeight(145)
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
            QMainWindow, QWidget { background: #070b12; color: #d7e3ed; font-family: "Segoe UI"; font-size: 12px; }
            QMenuBar, QMenu, QStatusBar { background: #090f18; color: #a9bac8; }
            QTabWidget::pane { border: 1px solid #1f3344; top: -1px; }
            QTabBar::tab { background: #0a111b; color: #7f9aaa; border: 1px solid #1f3344; padding: 9px 18px; }
            QTabBar::tab:selected { color: #72f1b8; border-bottom: 2px solid #35d4d4; background: #0d1520; }
            QTabBar::tab:disabled { color: #405462; background: #080d14; border-color: #172733; }
            QGroupBox { border: 1px solid #1f3344; margin-top: 10px; padding: 9px; font-weight: 600; color: #9fb2c0; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #35d4d4; }
            QTableWidget, QTextEdit, QLineEdit, QComboBox, QSpinBox {
                background: #0b121c; color: #d7e3ed; border: 1px solid #1f3344; selection-background-color: #173747;
            }
            QLineEdit, QComboBox, QSpinBox { min-height: 26px; padding: 2px 6px; }
            QPushButton { padding: 7px 12px; border: 1px solid #2c5965; border-radius: 3px; background: #101c27; color: #d7e3ed; }
            QPushButton:hover { border-color: #35d4d4; color: #72f1b8; background: #122631; }
            QPushButton:disabled { color: #4b5f6d; border-color: #1a2934; background: #0a1118; }
            QPushButton#dangerButton { border-color: #9f396f; color: #f5a6cf; }
            QPushButton#dangerButton:hover { border-color: #ef4da8; background: #291324; }
            QHeaderView::section { background: #111d29; color: #7f9aaa; padding: 6px; border: 0; border-right: 1px solid #1f3344; }
            QProgressBar { border: 1px solid #1f3344; background: #0b121c; text-align: center; color: #d7e3ed; }
            QProgressBar::chunk { background: #35d4d4; }
            QLabel#title { font-size: 24px; font-weight: 700; color: #72f1b8; }
            QLabel#subtitle { font-size: 14px; color: #7f9aaa; }
            QLabel#metricValue { font-size: 18px; font-weight: 700; color: #35d4d4; }
            QLabel#reviewState { color: #f5a6cf; font-weight: 700; padding: 6px 0; }
            QLabel#preview { background: #05080d; border: 1px solid #1f5260; min-height: 220px; color: #607786; }
            QTextEdit#checklist { background: #091019; color: #9fb2c0; }
            """
        )

    def _preview_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumSize(250, 220)
        label.setObjectName("preview")
        return label

    def analyze_my_footage(self) -> None:
        self.tabs.setCurrentIndex(0)
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
                    capture_metadata=fixture_metadata("commons-young-double-slit"),
                )
                app_api.add_capture(
                    self.experiment_dir,
                    Path("sample_media") / "commons-double-slit-experiment.webm",
                    "video",
                    "control",
                    all_frames=True,
                    max_frames=max_frames,
                    capture_metadata=fixture_metadata("commons-double-slit-experiment"),
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

    def unblind_review(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        answer = QMessageBox.question(
            self,
            "Unblind review",
            "Reveal source roles and provenance, then compute matched-control statistics? This cannot be reversed for this run.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        self._run_worker("Unblinding review", lambda: app_api.unblind_latest_run(experiment), self._unblind_finished)

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
        if selected < 0:
            return
        blind_item = self.candidate_table.item(selected, 0)
        if blind_item is None:
            return
        candidate = next(
            (item for item in candidates if item.get("blind_id") == blind_item.text()),
            None,
        )
        if candidate is None:
            return
        details = [
            f"Blind ID: {candidate.get('blind_id', '')}",
            f"Primary metric: {candidate.get('primary_metric', 'structure_score')}",
            f"Primary score: {candidate.get('primary_metric_score', candidate.get('structure_score'))}",
            f"Families: {candidate.get('detector_family_scores', {})}",
        ]
        if self._review_is_unblinded():
            details.extend(
                [
                    f"Role: {candidate.get('unblinded_label', '')}",
                    f"Source: {candidate.get('source_path', '')}",
                    f"Frame: {candidate.get('frame_index', 'n/a')}",
                    f"Control: {candidate.get('control_type') or 'n/a'}",
                    f"q-value: {candidate.get('q_value')}",
                ]
            )
        else:
            details.append("Source role, path, frame attribution, and q-value are sealed.")
        details.extend(["", candidate.get("ocr_text", "")])
        self.candidate_details.setPlainText("\n".join(str(item) for item in details))
        self._load_candidate_images(candidate)

    def _load_candidate_images(self, candidate: dict[str, Any]) -> None:
        for label, text in ((self.original_preview, "Original"), (self.processed_preview, "Processed"), (self.crop_preview, "Candidate crop")):
            label.clear()
            label.setText(text)
        if not self.experiment_dir:
            return
        source = candidate.get("review_image_path") or candidate.get("source_path")
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
        self.run_log.append("Review sealed. Inspect candidates before unblinding.")
        self.refresh_review(silent=True)
        self.tabs.setCurrentIndex(2)
        self.status.showMessage("Analysis complete / blinded review locked")

    def _unblind_finished(self, report: dict[str, Any]) -> None:
        self.latest_report = report
        self._populate_report(report)
        if self.experiment_dir:
            self._populate_captures(app_api.create_experiment(self.experiment_dir))
        self.tabs.setCurrentIndex(2)
        self.run_log.append("Review unblinded. Matched-control statistics computed.")
        self.status.showMessage("Review unblinded")

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
                str(len(capture.get("frames", [])) or capture.get("frame_count", 0)),
                capture.get("source_id", ""),
            ]
            for column, value in enumerate(values):
                self.capture_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _populate_report(self, report: dict[str, Any]) -> None:
        stats = report.get("aggregate_statistics", {})
        summary = report.get("summary", {})
        unblinded = bool(report.get("review_state", {}).get("unblinded", True))
        self.review_state_label.setText(
            "UNBLINDED / source roles visible" if unblinded else "BLINDED / source roles sealed"
        )
        self.unblind_button.setEnabled(not unblinded)
        self.unblind_button.setText("Review unblinded" if unblinded else "Unblind and compare")
        self.tabs.setTabVisible(0, unblinded)
        self.tabs.setTabVisible(1, unblinded)
        self.include_media.setEnabled(unblinded)
        if not unblinded:
            self.include_media.setChecked(False)
            self.tabs.setCurrentIndex(2)
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
        if unblinded:
            headers = ["Blind ID", "Role", "Score", "Persist", "q", "Variant", "Source", "OCR", "Processed"]
        else:
            headers = ["Blind ID", "Score", "Persist", "Variant", "OCR", "Processed"]
        self.candidate_table.setColumnCount(len(headers))
        self.candidate_table.setHorizontalHeaderLabels(headers)
        self.candidate_table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            common = [
                candidate.get("blind_id", ""),
                str(candidate.get("primary_metric_score", candidate.get("structure_score", ""))),
                str(candidate.get("persistence_score", "")),
                candidate.get("preprocessing_variant", ""),
                candidate.get("ocr_text", "")[:80],
                candidate.get("processed_path", ""),
            ]
            values = (
                [common[0], candidate.get("unblinded_label", ""), common[1], common[2], str(candidate.get("q_value", "")), common[3], candidate.get("source_path", "")[:80], common[4], common[5]]
                if unblinded
                else common
            )
            for column, value in enumerate(values):
                self.candidate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.candidate_table.setSortingEnabled(True)
        if candidates:
            self.candidate_table.sortItems(2 if unblinded else 1, Qt.DescendingOrder)
            self.candidate_table.selectRow(0)
        self._populate_filmstrip(report, unblinded=unblinded)
        self._populate_family_table(stats, unblinded=unblinded)

    def _populate_filmstrip(self, report: dict[str, Any], unblinded: bool) -> None:
        candidates = report.get("top_candidates", [])[:8]
        headers = ["Blind ID", "Score", "Role", "Source"] if unblinded else ["Blind ID", "Score"]
        self.filmstrip_table.setColumnCount(len(headers))
        self.filmstrip_table.setHorizontalHeaderLabels(headers)
        self.filmstrip_table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            values = [candidate.get("blind_id", ""), str(candidate.get("primary_metric_score", ""))]
            if unblinded:
                values.extend([candidate.get("unblinded_label", ""), candidate.get("source_path", "")])
            for column, value in enumerate(values):
                self.filmstrip_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _populate_family_table(self, stats: dict[str, Any], unblinded: bool) -> None:
        if not unblinded:
            self.family_table.setRowCount(0)
            self.compare_notes.setPlainText(
                "Comparisons are sealed during review. Unblind only after candidate inspection is complete."
            )
            return
        families = stats.get("detector_family_statistics", {})
        self.family_table.setRowCount(len(families))
        for row, (family, record) in enumerate(families.items()):
            values = [family, record.get("mean"), record.get("low"), record.get("high")]
            for column, value in enumerate(values):
                self.family_table.setItem(row, column, QTableWidgetItem("n/a" if value is None else str(value)))
        self.compare_notes.setPlainText(
            "Detector families summarize measured image structure. They do not establish language, origin, or intent."
        )

    def _review_is_unblinded(self) -> bool:
        if not self.latest_report:
            return False
        return bool(self.latest_report.get("review_state", {}).get("unblinded", True))

    def _load_fixtures(self) -> None:
        fixtures = list_fixtures(include_restricted=True)
        self.fixture_table.setRowCount(len(fixtures))
        for row, item in enumerate(fixtures):
            values = [
                item.get("id", ""),
                item.get("title", ""),
                item.get("label", ""),
                ", ".join(item.get("phenomena", [])),
                item.get("license", ""),
                item.get("expected_behavior", ""),
                item.get("source_page", ""),
            ]
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
            self.unblind_button,
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
