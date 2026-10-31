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
    QDoubleSpinBox,
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
    QScrollArea,
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
from laserlab.theme import badge_strip_html, dashboard_stylesheet, evidence_tone, quality_checklist_html


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

        help_menu = self.menuBar().addMenu("Help")
        quick_start = QAction("First-time walkthrough", self)
        quick_start.triggered.connect(self.show_quick_start)
        help_menu.addAction(quick_start)
        feedback = QAction("Report a problem or suggest an improvement", self)
        feedback.triggered.connect(self.open_feedback)
        help_menu.addAction(feedback)

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
        subtitle = QLabel(
            "Explore patterns in recorded laser footage using blinded comparisons. "
            "The app checks detections against controls; it cannot determine their origin or meaning."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        first_steps = QLabel(
            "New here? Try the sample demo first (no recordings needed). "
            "For your own footage: create an experiment, add a laser recording and a "
            "matched control, then run and review before unblinding."
        )
        first_steps.setObjectName("subtitle")
        first_steps.setWordWrap(True)
        layout.addWidget(first_steps)

        actions = QGroupBox("Start")
        action_layout = QHBoxLayout(actions)
        self.home_demo_button = QPushButton("Try sample demo")
        self.home_demo_button.setToolTip(
            "Practice with public optical clips; these are not a matched experimental pair."
        )
        self.home_demo_button.clicked.connect(self.run_fixture_demo)
        self.home_analyze_button = QPushButton("Analyze my footage")
        self.home_analyze_button.setObjectName("primaryButton")
        self.home_analyze_button.clicked.connect(self.analyze_my_footage)
        self.home_open_button = QPushButton("Open existing experiment")
        self.home_open_button.clicked.connect(self.open_existing_experiment)
        action_layout.addWidget(self.home_demo_button)
        action_layout.addWidget(self.home_analyze_button)
        action_layout.addWidget(self.home_open_button)
        self.home_help_button = QPushButton("How it works")
        self.home_help_button.clicked.connect(self.show_quick_start)
        action_layout.addWidget(self.home_help_button)
        action_layout.addStretch(1)
        layout.addWidget(actions)

        self.setup_steps = QTabWidget()
        self.setup_steps.addTab(self._experiment_tab(), "1  Experiment")
        self.setup_steps.addTab(self._capture_tab(), "2  Add Capture")
        self.setup_steps.addTab(self._protocol_tab(), "3  Analysis Plan")
        self.setup_steps.addTab(self._fixtures_tab(), "Demo")
        layout.addWidget(self.setup_steps, 1)
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
        self.experiment_path = QLineEdit(str(Path("experiments") / "my-first-experiment"))
        browse_exp = QPushButton("Browse")
        browse_exp.clicked.connect(self.browse_experiment)
        open_exp = QPushButton("Create / Open")
        open_exp.clicked.connect(self.open_experiment)
        experiment_layout.addWidget(QLabel("Directory"), 0, 0)
        experiment_layout.addWidget(self.experiment_path, 0, 1)
        experiment_layout.addWidget(browse_exp, 0, 2)
        experiment_layout.addWidget(open_exp, 0, 3)
        layout.addWidget(experiment_group)

        guidance = QLabel(
            "Choose a folder and click Create / Open. Next, add laser footage and a "
            "control recording made with the same camera settings and geometry."
        )
        guidance.setObjectName("subtitle")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)

        self.capture_table = QTableWidget(0, 6)
        self.capture_table.setHorizontalHeaderLabels(["Capture", "Role", "Footage class", "Pattern", "Frames", "Warnings"])
        self.capture_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.capture_table.verticalHeader().setVisible(False)
        layout.addWidget(self.capture_table, 1)

        continue_button = QPushButton("Continue to Add Capture")
        continue_button.clicked.connect(lambda: self.setup_steps.setCurrentIndex(1))
        layout.addWidget(continue_button)
        return page

    def _capture_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)

        capture_intro = QLabel(
            "Start with your laser video or image folder. Then add a matched control: "
            "keep the camera, focus, exposure, distance, and surface as similar as possible."
        )
        capture_intro.setObjectName("subtitle")
        capture_intro.setWordWrap(True)
        layout.addWidget(capture_intro)

        source_group = QGroupBox("Source")
        source_layout = QGridLayout(source_group)
        self.source_path = QLineEdit()
        browse_source = QPushButton("Browse")
        browse_source.clicked.connect(self.browse_source)
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["video", "image-set"])
        self.label_combo = QComboBox()
        for display, value in (
            ("Laser recording", "laser"),
            ("Matched control (same setup)", "matched_control"),
            ("Other control", "control"),
            ("Camera / sensor noise", "sensor_noise"),
            ("Synthetic positive test", "synthetic_positive"),
            ("Synthetic negative test", "synthetic_negative"),
        ):
            self.label_combo.addItem(display, value)
        self.label_combo.setToolTip(
            "Choose the recording's real role. Source roles are sealed during blinded review."
        )
        self.footage_class_combo = QComboBox()
        for label, value in (
            ("Wall-projection experiment", "primary_wall_projection"),
            ("Calibration fixture", "calibration_fixture"),
            ("Regression fixture", "regression_fixture"),
            ("Demo fixture", "demo_fixture"),
            ("Other footage", "other"),
        ):
            self.footage_class_combo.addItem(label, value)
        self.laser_pattern_combo = QComboBox()
        self.laser_pattern_combo.addItems(["cross", "dot", "line", "grid", "fan", "unknown"])
        self.wavelength_nm = QDoubleSpinBox()
        self.wavelength_nm.setRange(0.0, 2000.0)
        self.wavelength_nm.setDecimals(1)
        self.wavelength_nm.setValue(650.0)
        self.wavelength_nm.setSuffix(" nm")
        self.surface_combo = QComboBox()
        self.surface_combo.addItems(["matte_wall", "painted_drywall", "textured_paper", "fabric", "other", "unknown"])
        self.camera_fixed_check = QCheckBox("Camera fixed")
        self.beam_fixed_check = QCheckBox("Beam path fixed")
        self.non_reflective_check = QCheckBox("Non-reflective target")
        self.not_saturated_check = QCheckBox("Projected region not saturated")
        self.safety_ack_check = QCheckBox("Laser safety reviewed")
        self.sampling_profile = QComboBox()
        self.sampling_profile.addItems(["quick", "baseline", "wide", "exhaustive"])
        self.sampling_profile.setCurrentText("baseline")
        self.all_frames = QCheckBox("All frames")
        self.deduplicate_frames = QCheckBox("Suppress duplicates")
        self.deduplicate_frames.setChecked(True)
        self.frame_interval = QSpinBox()
        self.frame_interval.setRange(1, 10000)
        self.frame_interval.setValue(5)
        self.max_frames = QSpinBox()
        self.max_frames.setRange(0, 1000000)
        self.max_frames.setSpecialValueText("No cap")
        self.max_frames.setValue(250)
        self.sampling_profile.currentTextChanged.connect(self._sampling_profile_changed)
        self.add_capture_button = QPushButton("Add Capture")
        self.add_capture_button.clicked.connect(self.add_capture)

        source_layout.addWidget(QLabel("Path"), 0, 0)
        source_layout.addWidget(self.source_path, 0, 1, 1, 4)
        source_layout.addWidget(browse_source, 0, 5)
        source_layout.addWidget(QLabel("Recording type"), 1, 0)
        source_layout.addWidget(self.kind_combo, 1, 1)
        source_layout.addWidget(QLabel("What is this recording?"), 1, 2)
        source_layout.addWidget(self.label_combo, 1, 3)
        source_layout.addWidget(QLabel("Footage type"), 2, 0)
        source_layout.addWidget(self.footage_class_combo, 2, 1, 1, 3)
        layout.addWidget(source_group)

        essentials = QGroupBox("Capture essentials")
        essential_layout = QGridLayout(essentials)
        essential_layout.addWidget(QLabel("Laser pattern"), 0, 0)
        essential_layout.addWidget(self.laser_pattern_combo, 0, 1)
        essential_layout.addWidget(QLabel("Wavelength"), 0, 2)
        essential_layout.addWidget(self.wavelength_nm, 0, 3)
        essential_layout.addWidget(QLabel("Projection surface"), 1, 0)
        essential_layout.addWidget(self.surface_combo, 1, 1)
        essential_layout.addWidget(self.camera_fixed_check, 2, 0)
        essential_layout.addWidget(self.beam_fixed_check, 2, 1)
        essential_layout.addWidget(self.non_reflective_check, 2, 2)
        essential_layout.addWidget(self.not_saturated_check, 2, 3)
        essential_layout.addWidget(self.safety_ack_check, 3, 0, 1, 2)
        layout.addWidget(essentials)
        safety_notice = QLabel(
            "Use a fixed mount, beam stop, non-reflective target, and trained handling. Never view or align a beam at eye level."
        )
        safety_notice.setWordWrap(True)
        safety_notice.setObjectName("warning")
        layout.addWidget(safety_notice)

        self.capture_advanced_button = QPushButton("Show advanced capture details")
        self.capture_advanced_button.setCheckable(True)
        layout.addWidget(self.capture_advanced_button)
        self.capture_advanced = QWidget()
        advanced_layout = QGridLayout(self.capture_advanced)
        self.projection_distance = QDoubleSpinBox()
        self.projection_distance.setRange(0.0, 10000.0)
        self.projection_distance.setDecimals(2)
        self.projection_distance.setSuffix(" m")
        self.rated_power = QDoubleSpinBox()
        self.rated_power.setRange(0.0, 100000.0)
        self.rated_power.setDecimals(2)
        self.rated_power.setSuffix(" mW")
        self.laser_class = QLineEdit()
        self.manufacturer_model = QLineEdit()
        self.diffraction_optic = QLineEdit()
        self.mount_type = QComboBox()
        self.mount_type.addItems(["tripod", "clamp", "lab_stand", "handheld", "unknown"])
        self.cross_center_visible = QCheckBox("Cross center visible")
        self.entire_cross_visible = QCheckBox("Entire cross visible")
        self.surface_texture_visible = QCheckBox("Surface texture visible")
        self.geometry_notes = QLineEdit()
        self.intermediate_notes = QLineEdit()
        self.room_lighting_notes = QLineEdit()
        self.external_dataset_reference = QLineEdit()
        self.external_dataset_reference.setPlaceholderText("Optional corpus/archive reference")
        self.symbol_corpus_compared = QCheckBox("Compared with a symbol corpus")
        advanced_layout.addWidget(QLabel("Projection distance"), 0, 0)
        advanced_layout.addWidget(self.projection_distance, 0, 1)
        advanced_layout.addWidget(QLabel("Rated power"), 0, 2)
        advanced_layout.addWidget(self.rated_power, 0, 3)
        advanced_layout.addWidget(QLabel("Laser class"), 1, 0)
        advanced_layout.addWidget(self.laser_class, 1, 1)
        advanced_layout.addWidget(QLabel("Diffraction optic"), 1, 2)
        advanced_layout.addWidget(self.diffraction_optic, 1, 3)
        advanced_layout.addWidget(QLabel("Manufacturer / model"), 2, 0)
        advanced_layout.addWidget(self.manufacturer_model, 2, 1)
        advanced_layout.addWidget(QLabel("Mount"), 2, 2)
        advanced_layout.addWidget(self.mount_type, 2, 3)
        advanced_layout.addWidget(self.cross_center_visible, 3, 0)
        advanced_layout.addWidget(self.entire_cross_visible, 3, 1)
        advanced_layout.addWidget(self.surface_texture_visible, 3, 2)
        advanced_layout.addWidget(QLabel("Geometry notes"), 4, 0)
        advanced_layout.addWidget(self.geometry_notes, 4, 1, 1, 3)
        advanced_layout.addWidget(QLabel("Intermediate layer"), 5, 0)
        advanced_layout.addWidget(self.intermediate_notes, 5, 1, 1, 3)
        advanced_layout.addWidget(QLabel("Room lighting"), 6, 0)
        advanced_layout.addWidget(self.room_lighting_notes, 6, 1, 1, 3)
        advanced_layout.addWidget(QLabel("External corpus/reference"), 7, 0)
        advanced_layout.addWidget(self.external_dataset_reference, 7, 1, 1, 2)
        advanced_layout.addWidget(self.symbol_corpus_compared, 7, 3)
        advanced_layout.addWidget(QLabel("Sampling profile"), 8, 0)
        advanced_layout.addWidget(self.sampling_profile, 8, 1)
        advanced_layout.addWidget(QLabel("Frame interval"), 8, 2)
        advanced_layout.addWidget(self.frame_interval, 8, 3)
        advanced_layout.addWidget(QLabel("Max frames"), 9, 0)
        advanced_layout.addWidget(self.max_frames, 9, 1)
        advanced_layout.addWidget(self.all_frames, 9, 2)
        advanced_layout.addWidget(self.deduplicate_frames, 9, 3)
        self.capture_advanced.setVisible(False)
        self.capture_advanced_button.toggled.connect(self.capture_advanced.setVisible)
        self.capture_advanced_button.toggled.connect(
            lambda checked: self.capture_advanced_button.setText(
                "Hide advanced capture details" if checked else "Show advanced capture details"
            )
        )
        layout.addWidget(self.capture_advanced)
        layout.addWidget(self.add_capture_button)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        return page

    def _protocol_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        protocol_group = QGroupBox("Analysis preset")
        form = QFormLayout(protocol_group)
        self.protocol_combo = QComboBox()
        for preset in self.protocol_presets:
            self.protocol_combo.addItem(preset["name"], preset["id"])
        self.protocol_combo.setCurrentIndex(3)
        self.protocol_combo.currentIndexChanged.connect(self._protocol_changed)
        self.protocol_description = QTextEdit()
        self.protocol_description.setReadOnly(True)
        self.protocol_description.setMaximumHeight(120)
        form.addRow("Preset", self.protocol_combo)
        form.addRow("Purpose", self.protocol_description)
        layout.addWidget(protocol_group)

        self.protocol_advanced_button = QPushButton("Show advanced analysis controls")
        self.protocol_advanced_button.setCheckable(True)
        layout.addWidget(self.protocol_advanced_button)
        self.protocol_advanced = QWidget()
        advanced_layout = QVBoxLayout(self.protocol_advanced)
        detector_group = QGroupBox("Detector and sampling controls")
        detector_form = QFormLayout(detector_group)
        self.primary_metric_combo = QComboBox()
        self.primary_metric_combo.addItems(["structure_score", "fft_peak_prominence", "speckle_contrast", "ocr_symbol_score"])
        self.preprocessing_intensity = QComboBox()
        self.preprocessing_intensity.addItems(["standard", "wide"])
        self.control_generation = QComboBox()
        self.control_generation.addItems(["standard", "strict", "none"])
        self.frame_sampling_mode = QComboBox()
        self.frame_sampling_mode.addItems(["interval", "scene_change", "all_frames", "capped_all_frames"])
        detector_form.addRow("Primary metric", self.primary_metric_combo)
        detector_form.addRow("Preprocessing intensity", self.preprocessing_intensity)
        detector_form.addRow("Control generation", self.control_generation)
        detector_form.addRow("Frame sampling mode", self.frame_sampling_mode)
        advanced_layout.addWidget(detector_group)

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
        grid.addWidget(self.roi_enabled, 0, 0, 1, 2)
        grid.addWidget(QLabel("x"), 1, 0)
        grid.addWidget(self.roi_x, 1, 1)
        grid.addWidget(QLabel("y"), 1, 2)
        grid.addWidget(self.roi_y, 1, 3)
        grid.addWidget(QLabel("width"), 2, 0)
        grid.addWidget(self.roi_w, 2, 1)
        grid.addWidget(QLabel("height"), 2, 2)
        grid.addWidget(self.roi_h, 2, 3)
        advanced_layout.addWidget(advanced)

        experimental = QGroupBox("Experimental psychophysics modules")
        experimental_layout = QHBoxLayout(experimental)
        self.import_trials_button = QPushButton("Import yes/no trials")
        self.import_trials_button.clicked.connect(self.import_trial_file)
        self.psychophysics_status = QLabel("Not attached")
        experimental_layout.addWidget(self.import_trials_button)
        experimental_layout.addWidget(self.psychophysics_status, 1)
        advanced_layout.addWidget(experimental)
        self.protocol_advanced.setVisible(False)
        self.protocol_advanced_button.toggled.connect(self.protocol_advanced.setVisible)
        self.protocol_advanced_button.toggled.connect(
            lambda checked: self.protocol_advanced_button.setText(
                "Hide advanced analysis controls" if checked else "Show advanced analysis controls"
            )
        )
        layout.addWidget(self.protocol_advanced)

        study = QGroupBox("Study context")
        study_form = QFormLayout(study)
        self.study_mode = QComboBox()
        self.study_mode.addItem("Footage only", "footage_only")
        self.study_mode.addItem("Retrospective report attached", "retrospective_report")
        self.study_mode.addItem("Externally approved study metadata", "externally_approved_study")
        study_form.addRow("Context", self.study_mode)
        self.subjective_fields = QWidget()
        subjective_form = QFormLayout(self.subjective_fields)
        self.session_id = QLineEdit()
        self.session_id.setPlaceholderText("Pseudonymous ID only")
        self.perception_notes = QTextEdit()
        self.perception_notes.setMaximumHeight(80)
        self.subjective_confidence = QDoubleSpinBox()
        self.subjective_confidence.setRange(0.0, 1.0)
        self.subjective_confidence.setSingleStep(0.05)
        self.ethics_reference = QLineEdit()
        self.privacy_ack = QCheckBox("No direct identifiers; sharing risk reviewed")
        subjective_form.addRow("Session ID", self.session_id)
        subjective_form.addRow("Context notes", self.perception_notes)
        subjective_form.addRow("Self-rating", self.subjective_confidence)
        subjective_form.addRow("Ethics reference", self.ethics_reference)
        subjective_form.addRow(self.privacy_ack)
        privacy_notice = QLabel("Subjective context is stored separately and never contributes to detector scores.")
        privacy_notice.setWordWrap(True)
        privacy_notice.setObjectName("warning")
        subjective_form.addRow(privacy_notice)
        self.subjective_fields.setVisible(False)
        self.study_mode.currentIndexChanged.connect(self._study_mode_changed)
        study_form.addRow(self.subjective_fields)
        layout.addWidget(study)

        self.apply_protocol_button = QPushButton("Save Analysis Plan")
        self.apply_protocol_button.clicked.connect(self.apply_protocol_plan)
        layout.addWidget(self.apply_protocol_button)
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
        self.run_button.setObjectName("primaryButton")
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
        self.complete_review_button = QPushButton("Mark review complete")
        self.complete_review_button.clicked.connect(self.mark_review_complete)
        state_row.addWidget(self.review_state_label)
        state_row.addStretch(1)
        state_row.addWidget(self.complete_review_button)
        state_row.addWidget(self.unblind_button)
        layout.addLayout(state_row)
        metrics = QGroupBox("Evidence")
        metrics.setObjectName("evidencePanel")
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
        self.badges_label.setObjectName("badgeStrip")
        self.badges_label.setTextFormat(Qt.RichText)
        self.badges_label.setWordWrap(True)
        layout.addWidget(self.badges_label)
        self.interpretation_text = QTextEdit()
        self.interpretation_text.setReadOnly(True)
        self.interpretation_text.setMaximumHeight(90)
        layout.addWidget(self.interpretation_text)

        filters = QGroupBox("Candidate filters")
        filter_layout = QHBoxLayout(filters)
        self.review_family_filter = QComboBox()
        self.review_family_filter.addItems(["all", "symbol", "diffraction", "speckle", "texture"])
        self.review_variant_filter = QComboBox()
        self.review_variant_filter.addItem("all")
        self.review_ocr_filter = QComboBox()
        self.review_ocr_filter.addItems(["all", "has OCR output", "no OCR output"])
        self.review_min_score = QDoubleSpinBox()
        self.review_min_score.setRange(0.0, 1.0)
        self.review_min_score.setSingleStep(0.05)
        self.review_min_persistence = QDoubleSpinBox()
        self.review_min_persistence.setRange(0.0, 1.0)
        self.review_min_persistence.setSingleStep(0.05)
        for label, widget in (
            ("Family", self.review_family_filter),
            ("Variant", self.review_variant_filter),
            ("OCR", self.review_ocr_filter),
            ("Min score", self.review_min_score),
            ("Min persistence", self.review_min_persistence),
        ):
            filter_layout.addWidget(QLabel(label))
            filter_layout.addWidget(widget)
        filter_layout.addStretch(1)
        self.review_family_filter.currentIndexChanged.connect(self._apply_review_filters)
        self.review_variant_filter.currentIndexChanged.connect(self._apply_review_filters)
        self.review_ocr_filter.currentIndexChanged.connect(self._apply_review_filters)
        self.review_min_score.valueChanged.connect(self._apply_review_filters)
        self.review_min_persistence.valueChanged.connect(self._apply_review_filters)
        layout.addWidget(filters)

        splitter = QSplitter(Qt.Horizontal)
        self.candidate_table = QTableWidget(0, 7)
        self.candidate_table.setHorizontalHeaderLabels(["Blind ID", "Score", "Persist", "Variant", "OCR", "Review", "Processed"])
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
        self.show_processed_overlay = QCheckBox("ROI boxes")
        self.show_processed_overlay.setChecked(True)
        self.show_crop_overlay = QCheckBox("Candidate crop")
        self.show_crop_overlay.setChecked(True)
        self.show_processed_overlay.toggled.connect(self.show_selected_candidate)
        self.show_crop_overlay.toggled.connect(self.show_selected_candidate)
        overlay_row.addWidget(QLabel("Overlays"))
        overlay_row.addWidget(self.show_processed_overlay)
        overlay_row.addWidget(self.show_crop_overlay)
        overlay_row.addStretch(1)
        preview_layout.addLayout(overlay_row)
        self.candidate_details = QTextEdit()
        self.candidate_details.setReadOnly(True)
        preview_layout.addWidget(self.candidate_details, 1)
        annotation_group = QGroupBox("Blinded reviewer annotation")
        annotation_layout = QVBoxLayout(annotation_group)
        flag_row = QHBoxLayout()
        self.review_flag_checks: dict[str, QCheckBox] = {}
        for flag in ("interesting", "artifact", "ocr_hit", "persistent", "exclude"):
            checkbox = QCheckBox(flag.replace("_", " "))
            self.review_flag_checks[flag] = checkbox
            flag_row.addWidget(checkbox)
        self.review_note = QTextEdit()
        self.review_note.setMaximumHeight(70)
        self.save_review_button = QPushButton("Save annotation")
        self.save_review_button.clicked.connect(self.save_selected_annotation)
        annotation_layout.addLayout(flag_row)
        annotation_layout.addWidget(self.review_note)
        annotation_layout.addWidget(self.save_review_button)
        preview_layout.addWidget(annotation_group)
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

        demo_note = QLabel(
            "A practice run with public optical clips, not a matched scientific experiment. "
            "Use your own controlled recordings to test a hypothesis."
        )
        demo_note.setObjectName("subtitle")
        demo_note.setWordWrap(True)
        layout.addWidget(demo_note)

        demo = QGroupBox("Demo")
        demo_layout = QGridLayout(demo)
        self.demo_experiment_path = QLineEdit(str(Path("experiments") / "bundled-demo"))
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
        sharing_tip = QLabel(
            "Sharing is optional. Blinded bundles protect source roles; unblinded exports "
            "can reveal identifying metadata. Check privacy and media rights first."
        )
        sharing_tip.setObjectName("subtitle")
        sharing_tip.setWordWrap(True)
        layout.addWidget(sharing_tip)

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

        self.community_tools_button = QPushButton("Show community data tools")
        self.community_tools_button.setCheckable(True)
        layout.addWidget(self.community_tools_button)
        self.community_tools = QGroupBox("Community data / local files")
        community_grid = QGridLayout(self.community_tools)
        self.import_reference_button = QPushButton("Import reference metadata")
        self.import_reference_button.clicked.connect(self.import_reference_file)
        self.import_symbols_button = QPushButton("Import symbol transcriptions")
        self.import_symbols_button.clicked.connect(self.import_symbol_file)
        self.export_symbols_button = QPushButton("Export symbol transcriptions")
        self.export_symbols_button.clicked.connect(self.export_symbol_file)
        self.community_data_status = QLabel("No local community data attached")
        community_grid.addWidget(self.import_reference_button, 0, 0)
        community_grid.addWidget(self.import_symbols_button, 0, 1)
        community_grid.addWidget(self.export_symbols_button, 0, 2)
        community_grid.addWidget(self.community_data_status, 1, 0, 1, 3)
        self.community_tools.setVisible(False)
        self.community_tools_button.toggled.connect(self.community_tools.setVisible)
        self.community_tools_button.toggled.connect(
            lambda checked: self.community_tools_button.setText(
                "Hide community data tools" if checked else "Show community data tools"
            )
        )
        layout.addWidget(self.community_tools)
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
        self.setStyleSheet(dashboard_stylesheet())

    def show_quick_start(self) -> None:
        """Explain the workflow without needing a browser or scientific jargon."""
        QMessageBox.information(
            self,
            "LaserLab / First-time walkthrough",
            "Welcome to LaserLab!\n\n"
            "1. Try sample demo to learn the workflow. Public example clips are not matched controls.\n\n"
            "2. Create / Open an experiment folder; add your laser recording AND a matched control. "
            "Keep camera, surface, focus, and exposure as similar as possible.\n\n"
            "3. Choose an Analysis Plan, run, and inspect results in Review while sources are hidden.\n\n"
            "4. Mark review complete before explicitly unblinding. You may export a blinded bundle.\n\n"
            "Detected shapes are not proof of language or unusual origin. Null results matter, too. "
            "Never aim lasers at eyes or reflective surfaces.",
        )

    def open_feedback(self) -> None:
        """Open optional GitHub feedback without uploading local experiment data."""
        QDesktopServices.openUrl(QUrl("https://github.com/ProhibitedTV/LaserAnalysisAI/issues/new"))

    def _preview_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumSize(250, 220)
        label.setObjectName("preview")
        return label

    def analyze_my_footage(self) -> None:
        self.tabs.setCurrentIndex(0)
        if self.experiment_dir is None:
            self.setup_steps.setCurrentIndex(0)
            self.status.showMessage("First create or open an experiment folder, then add footage.")
            return
        self.setup_steps.setCurrentIndex(1)
        self.browse_source()

    def open_existing_experiment(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.setup_steps.setCurrentIndex(0)
        path = QFileDialog.getExistingDirectory(
            self, "Open Existing Experiment", self.experiment_path.text()
        )
        if not path:
            return
        self.experiment_path.setText(path)
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
            context = manifest.get("study_context", {})
            self._set_combo_data(self.study_mode, context.get("mode", "footage_only"))
            self.session_id.setText(str(context.get("pseudonymous_session_id") or ""))
            self.perception_notes.setPlainText(str(context.get("perception_notes") or ""))
            self.subjective_confidence.setValue(float(context.get("confidence") or 0.0))
            self.ethics_reference.setText(str(context.get("ethics_review_reference") or ""))
            self.privacy_ack.setChecked(bool(context.get("privacy_acknowledged")))
            psychophysics = manifest.get("psychophysics_analysis") or {}
            trial_count = (manifest.get("psychophysics_trials") or {}).get("source", {}).get("record_count", 0)
            self.psychophysics_status.setText(
                f"{trial_count} trials attached / d-prime {psychophysics.get('metrics', {}).get('d_prime', 'n/a')}"
                if trial_count
                else "Not attached"
            )
            reference_count = len(manifest.get("external_dataset_references", []))
            symbol_count = len((manifest.get("symbol_transcriptions") or {}).get("records", []))
            self.community_data_status.setText(
                f"References: {reference_count} / symbol transcriptions: {symbol_count}"
                if reference_count or symbol_count
                else "No local community data attached"
            )
            self._study_mode_changed()
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
                label=self.label_combo.currentData(),
                all_frames=self.all_frames.isChecked(),
                frame_interval=self.frame_interval.value(),
                max_frames=max_frames,
                sampling_profile=self.sampling_profile.currentText(),
                sampling_mode=self.frame_sampling_mode.currentText(),
                deduplicate=self.deduplicate_frames.isChecked(),
                capture_metadata=self._capture_metadata(),
            )

        self._run_worker("Adding capture", task, self._capture_added)

    def apply_protocol_plan(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        try:
            app_api.update_study_context(experiment, self._study_context())
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

    def import_trial_file(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Pre-declared Yes/No Trials",
            "",
            "Trial data (*.json *.csv)",
        )
        if not path:
            return
        try:
            payload = app_api.import_psychophysics_trials(experiment, Path(path))
            analysis = payload["analysis"]
            d_prime = analysis["metrics"].get("d_prime")
            d_prime_text = "n/a" if d_prime is None else f"{d_prime:.3f}"
            self.psychophysics_status.setText(
                f"{payload['source']['record_count']} trials / d-prime {d_prime_text}"
            )
            self.status.showMessage("Psychophysics trials attached; detector scoring remains separate")
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

    def mark_review_complete(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        try:
            app_api.complete_review(experiment)
            self.refresh_review(silent=True)
            self.status.showMessage("Blind review marked complete")
        except Exception as exc:
            self._error(str(exc))

    def save_selected_annotation(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        row = self.candidate_table.currentRow()
        blind_item = self.candidate_table.item(row, 0) if row >= 0 else None
        if blind_item is None:
            self._error("Select a candidate before saving an annotation.")
            return
        flags = [flag for flag, checkbox in self.review_flag_checks.items() if checkbox.isChecked()]
        try:
            app_api.save_review_annotation(
                experiment,
                blind_id=blind_item.text(),
                note=self.review_note.toPlainText(),
                flags=flags,
            )
            selected_blind_id = blind_item.text()
            self.refresh_review(silent=True)
            self._select_candidate(selected_blind_id)
            self.status.showMessage(f"Annotation saved for {selected_blind_id}")
        except Exception as exc:
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
        privacy_acknowledged = False
        try:
            report = self.latest_report or app_api.load_latest_report(experiment)
        except Exception:
            report = {}
        if report.get("review_state", {}).get("unblinded") and (
            report.get("subjective_reports")
            or (report.get("psychophysics_analysis") or {}).get("analysis_status") == "tested"
            or report.get("external_dataset_references")
            or report.get("symbol_transcription_summary", {}).get("record_count", 0)
        ):
            answer = QMessageBox.question(
                self,
                "Privacy review",
                "Confirm that participant IDs, subjective context, community metadata, and sharing risk were reviewed.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            privacy_acknowledged = True
        path, _ = QFileDialog.getSaveFileName(self, "Export Review Bundle", "laserlab-review-bundle.zip", "ZIP (*.zip)")
        if not path:
            return
        try:
            exported = app_api.export_review_bundle(
                experiment,
                Path(path),
                include_media=self.include_media.isChecked(),
                privacy_acknowledged=privacy_acknowledged,
            )
            self.export_log.append(f"Exported bundle: {exported}")
            self.status.showMessage(f"Exported {exported}")
        except Exception as exc:
            self._error(str(exc))

    def import_reference_file(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Local Community Reference",
            "",
            "Community data (*.json *.csv)",
        )
        if not path:
            return
        try:
            payload = app_api.import_external_dataset_reference(experiment, Path(path))
            self.community_data_status.setText(
                f"Imported {len(payload['records'])} context-only reference record(s); privacy not reviewed"
            )
            self.export_log.append(f"Imported local reference hash: {payload['source_sha256']}")
        except Exception as exc:
            self._error(str(exc))

    def import_symbol_file(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Symbol Transcriptions",
            "",
            "Symbol data (*.json *.csv)",
        )
        if not path:
            return
        try:
            payload = app_api.import_symbol_transcriptions(experiment, Path(path))
            self.community_data_status.setText(
                f"Imported {len(payload['records'])} context-only symbol transcription(s); privacy not reviewed"
            )
        except Exception as exc:
            self._error(str(exc))

    def export_symbol_file(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        answer = QMessageBox.question(
            self,
            "Privacy review",
            "Confirm that pseudonymous IDs, transcriptions, and sharing risk were reviewed.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Symbol Transcriptions",
            "symbol-transcriptions.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        try:
            exported = app_api.export_symbol_transcriptions_csv(
                experiment,
                Path(path),
                privacy_acknowledged=True,
            )
            self.export_log.append(f"Exported symbol transcriptions: {exported}")
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
            f"Cross registration: {candidate.get('cross_pattern', {})}",
            f"ROI candidates: {len(candidate.get('candidate_rois', []))}",
            f"OCR attempts: {len(candidate.get('ocr_attempts', []))}",
            f"OCR engines: {candidate.get('ocr_ensemble', {}).get('engine_ids', [])}",
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
        annotation = candidate.get("review_annotation") or {}
        if annotation:
            details.extend(["", f"Review flags: {', '.join(annotation.get('flags', []))}", annotation.get("note", "")])
        self.candidate_details.setPlainText("\n".join(str(item) for item in details))
        self.review_note.setPlainText(annotation.get("note", ""))
        selected_flags = set(annotation.get("flags", []))
        for flag, checkbox in self.review_flag_checks.items():
            checkbox.setChecked(flag in selected_flags)
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
        processed = (
            candidate.get("roi_overlay_path")
            if self.show_processed_overlay.isChecked()
            else candidate.get("processed_path")
        )
        if processed:
            self._set_pixmap(self.processed_preview, self.experiment_dir / processed)
        rois = candidate.get("candidate_rois", [])
        if self.show_crop_overlay.isChecked() and rois:
            crop = rois[0].get("processed_crop_path") or rois[0].get("crop_path")
            if crop:
                self._set_pixmap(self.crop_preview, self.experiment_dir / crop)

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
        self.source_path.clear()
        if self.label_combo.currentData() == "laser":
            control_index = self.label_combo.findData("matched_control")
            if control_index >= 0:
                self.label_combo.setCurrentIndex(control_index)

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
                capture.get("metadata", {}).get("footage_class", ""),
                capture.get("metadata", {}).get("laser_pattern_type", ""),
                str(len(capture.get("frames", [])) or capture.get("frame_count", 0)),
                str(len(capture.get("provenance_warnings", []))),
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
        self._set_dynamic_property(self.review_state_label, "unblinded", "true" if unblinded else "false")
        review_complete = bool(report.get("review_session", {}).get("complete"))
        self.unblind_button.setEnabled(not unblinded and review_complete)
        self.unblind_button.setText("Review unblinded" if unblinded else "Unblind and compare")
        self.complete_review_button.setEnabled(not unblinded and not review_complete)
        self.complete_review_button.setText("Review complete" if review_complete else "Mark review complete")
        self.tabs.setTabVisible(0, unblinded)
        self.tabs.setTabVisible(1, unblinded)
        self.include_media.setEnabled(unblinded)
        if not unblinded:
            self.include_media.setChecked(False)
            self.tabs.setCurrentIndex(2)
        for key, label in self.metric_labels.items():
            value = summary.get(key, stats.get(key))
            label.setText("n/a" if value is None else str(value))
            if key == "evidence_ladder":
                self._set_dynamic_property(label, "tone", evidence_tone(value))
        self.badges_label.setText(badge_strip_html(report.get("badges", [])))
        interpretation = report.get("interpretation", {})
        self.interpretation_text.setPlainText(
            "What this means: " + interpretation.get("what_this_means", "") + "\n"
            "What this does not mean: " + interpretation.get("what_this_does_not_mean", "")
        )

        all_candidates = report.get("top_candidates", [])
        current_variant = self.review_variant_filter.currentText()
        variants = sorted({str(item.get("preprocessing_variant", "")) for item in all_candidates if item.get("preprocessing_variant")})
        self.review_variant_filter.blockSignals(True)
        self.review_variant_filter.clear()
        self.review_variant_filter.addItems(["all", *variants])
        self._set_combo_text(self.review_variant_filter, current_variant)
        self.review_variant_filter.blockSignals(False)
        self._populate_candidate_table(report, unblinded=unblinded)
        self._populate_filmstrip(report, unblinded=unblinded)
        self._populate_family_table(stats, unblinded=unblinded)

    def _populate_candidate_table(self, report: dict[str, Any], unblinded: bool) -> None:
        self.candidate_table.setSortingEnabled(False)
        candidates = self._filtered_candidates(report.get("top_candidates", []))
        if unblinded:
            headers = ["Blind ID", "Role", "Score", "Persist", "q", "Variant", "Source", "OCR", "Review", "Processed"]
        else:
            headers = ["Blind ID", "Score", "Persist", "Variant", "OCR", "Review", "Processed"]
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
                self._annotation_summary(candidate),
                candidate.get("processed_path", ""),
            ]
            values = (
                [common[0], candidate.get("unblinded_label", ""), common[1], common[2], str(candidate.get("q_value", "")), common[3], candidate.get("source_path", "")[:80], common[4], common[5], common[6]]
                if unblinded
                else common
            )
            for column, value in enumerate(values):
                self.candidate_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.candidate_table.setSortingEnabled(True)
        if candidates:
            self.candidate_table.sortItems(2 if unblinded else 1, Qt.DescendingOrder)
            self.candidate_table.selectRow(0)

    def _filtered_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        family = self.review_family_filter.currentText()
        variant = self.review_variant_filter.currentText()
        ocr_filter = self.review_ocr_filter.currentText()
        filtered = []
        for candidate in candidates:
            score = float(candidate.get("primary_metric_score", candidate.get("structure_score", 0.0)) or 0.0)
            persistence = float(candidate.get("persistence_score", 0.0) or 0.0)
            if score < self.review_min_score.value() or persistence < self.review_min_persistence.value():
                continue
            if variant != "all" and candidate.get("preprocessing_variant") != variant:
                continue
            has_ocr = bool(str(candidate.get("ocr_text", "")).strip())
            if ocr_filter == "has OCR output" and not has_ocr:
                continue
            if ocr_filter == "no OCR output" and has_ocr:
                continue
            families = candidate.get("detector_family_scores", {})
            if family != "all" and families:
                strongest = max(families, key=lambda key: float(families.get(key, 0.0) or 0.0))
                if strongest != family:
                    continue
            filtered.append(candidate)
        return filtered

    def _apply_review_filters(self, *_args: Any) -> None:
        if not self.latest_report:
            return
        self._populate_candidate_table(self.latest_report, unblinded=self._review_is_unblinded())

    @staticmethod
    def _annotation_summary(candidate: dict[str, Any]) -> str:
        annotation = candidate.get("review_annotation") or {}
        flags = ", ".join(annotation.get("flags", []))
        note = str(annotation.get("note", "")).strip()
        return (flags + (" | " if flags and note else "") + note)[:120]

    def _select_candidate(self, blind_id: str) -> None:
        for row in range(self.candidate_table.rowCount()):
            item = self.candidate_table.item(row, 0)
            if item and item.text() == blind_id:
                self.candidate_table.selectRow(row)
                return

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
        warning_count = sum(len(capture.get("provenance_warnings", [])) for capture in captures)
        laser_captures = [capture for capture in captures if capture.get("label") == "laser"]
        wall_projection = any(
            capture.get("metadata", {}).get("footage_class") == "primary_wall_projection"
            for capture in laser_captures
        )
        camera_fixed = bool(laser_captures) and all(
            capture.get("metadata", {}).get("camera_fixed") is True for capture in laser_captures
        )
        safe_target = bool(laser_captures) and all(
            capture.get("metadata", {}).get("non_reflective_surface") is True
            and capture.get("metadata", {}).get("projected_region_not_saturated") is True
            for capture in laser_captures
        )
        lines = [
            ("laser capture", "laser" in labels),
            ("control capture", bool(labels & {"control", "matched_control", "sensor_noise", "synthetic_negative"})),
            ("wall or flat projection target", wall_projection),
            ("fixed camera and geometry", camera_fixed),
            ("non-reflective, non-saturated target", safe_target),
            ("frame count >= 2", estimate.get("sample_count", 0) >= 2),
            ("matched controls enabled", self.control_generation.currentText() != "none"),
            ("capture provenance complete", warning_count == 0),
            ("multiple comparisons corrected", True),
        ]
        self.quality_checklist.setHtml(quality_checklist_html(lines))

    def _protocol_changed(self) -> None:
        preset = self._preset()
        self.protocol_description.setPlainText(
            preset["description"] + "\n\nScience options: " + ", ".join(preset.get("science", []))
        )
        self._set_combo_text(self.primary_metric_combo, preset["primary_metric"])
        self._set_combo_text(self.preprocessing_intensity, "wide" if preset["profile"] == "wide" else "standard")

    def _study_mode_changed(self, *_args: Any) -> None:
        self.subjective_fields.setVisible((self.study_mode.currentData() or "footage_only") != "footage_only")

    def _study_context(self) -> dict[str, Any]:
        return {
            "mode": self.study_mode.currentData() or "footage_only",
            "pseudonymous_session_id": self.session_id.text().strip() or None,
            "perception_notes": self.perception_notes.toPlainText().strip(),
            "confidence": self.subjective_confidence.value(),
            "privacy_acknowledged": self.privacy_ack.isChecked(),
            "ethics_review_reference": self.ethics_reference.text().strip() or None,
        }

    def _capture_metadata(self) -> dict[str, Any]:
        return {
            "footage_class": self.footage_class_combo.currentData() or "other",
            "laser_pattern_type": self.laser_pattern_combo.currentText(),
            "wavelength_nm": self.wavelength_nm.value() or None,
            "projection_surface_type": self.surface_combo.currentText(),
            "camera_fixed": self.camera_fixed_check.isChecked(),
            "beam_path_fixed": self.beam_fixed_check.isChecked(),
            "non_reflective_surface": self.non_reflective_check.isChecked(),
            "projected_region_not_saturated": self.not_saturated_check.isChecked(),
            "safety_acknowledged": self.safety_ack_check.isChecked(),
            "projection_distance_meters": self.projection_distance.value() or None,
            "rated_power_mw": self.rated_power.value() or None,
            "laser_class_label": self.laser_class.text().strip() or None,
            "manufacturer_model": self.manufacturer_model.text().strip() or None,
            "diffraction_optic_type": self.diffraction_optic.text().strip() or None,
            "mount_type": self.mount_type.currentText(),
            "cross_center_visible": self.cross_center_visible.isChecked(),
            "entire_cross_visible": self.entire_cross_visible.isChecked(),
            "surface_texture_visible": self.surface_texture_visible.isChecked(),
            "laser_to_target_geometry_notes": self.geometry_notes.text().strip(),
            "intermediate_material_notes": self.intermediate_notes.text().strip(),
            "room_lighting_notes": self.room_lighting_notes.text().strip(),
            "external_dataset_reference": self.external_dataset_reference.text().strip() or None,
            "symbol_corpus_compared": self.symbol_corpus_compared.isChecked(),
        }

    def _sampling_profile_changed(self, profile: str) -> None:
        defaults = {
            "quick": (15, 25, False),
            "baseline": (5, 250, False),
            "wide": (2, 1000, False),
            "exhaustive": (1, 0, True),
        }
        interval, maximum, all_frames = defaults.get(profile, defaults["baseline"])
        self.frame_interval.setValue(interval)
        self.max_frames.setValue(maximum)
        self.all_frames.setChecked(all_frames)

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

    @staticmethod
    def _set_dynamic_property(widget: QWidget, name: str, value: str) -> None:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

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
