"""LaserLab community science dashboard."""

from __future__ import annotations

import logging
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
    QInputDialog,
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

from laserlab import __version__, app_api
from laserlab.capture_inference import sample_class, source_class_label
from laserlab.report import pair_quality_html
from laserlab.replication import comparison_html
from laserlab.catalog_cache import CatalogCache, refresh_catalog, open_saved_catalog
from laserlab.diagnostics import (
    collect_diagnostics,
    configure_logging,
    export_support_bundle as write_support_bundle,
    get_state_dir,
)
from laserlab.fixtures import list_fixtures
from laserlab.manifest import load_manifest
from laserlab.preferences import load_preferences, remember_experiment, set_last_source_directory, set_veilbreak_cache_enabled
from laserlab.runtime import default_experiments_dir
from laserlab.theme import badge_strip_html, dashboard_stylesheet, evidence_tone, quality_checklist_html
from .veilbreak_catalog import VeilbreakCatalogDialog
from .research_exchange import ResearchExchangeDialog


VEILBREAK_API_KEY_PAGE = "https://veilbreak.ai/api-access"
SUPPORT_PAGE = "https://github.com/ProhibitedTV/LaserAnalysisAI/wiki/Troubleshooting"
ISSUE_FORMS_PAGE = "https://github.com/ProhibitedTV/LaserAnalysisAI/issues/new/choose"


LOGGER = logging.getLogger("laserlab.gui")


class ApiWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, task: Callable[[], Any]):
        super().__init__()
        self._task = task
        self.result: Any = None
        self.error: str | None = None

    def run(self) -> None:
        try:
            self.result = self._task()
            self.finished_ok.emit(self.result)
        except Exception as exc:  # pragma: no cover - exercised by manual GUI use
            LOGGER.exception("Background task failed")
            self.error = str(exc)
            self.failed.emit(self.error)


class LabDashboardWindow(QMainWindow):
    """Guided desktop dashboard for community LaserLab experiments."""

    def __init__(self, preferences: dict[str, Any] | None = None):
        super().__init__()
        self.experiment_dir: Path | None = None
        self.is_demo_experiment = False
        self.latest_report: dict[str, Any] | None = None
        self.worker: ApiWorker | None = None
        self._busy = False
        self.session_comparison: dict[str, Any] | None = None
        self.comparison_directories: list[Path] = []
        self.preferences = preferences if preferences is not None else load_preferences()
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
        self.recent_menu = file_menu.addMenu("Open Recent")
        self._refresh_recent_menu()
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = self.menuBar().addMenu("Help")
        walkthrough = QAction("First-time walkthrough", self)
        walkthrough.triggered.connect(self.show_quick_start)
        help_menu.addAction(walkthrough)
        for title, url in (("Troubleshooting guide", SUPPORT_PAGE), ("Report a problem...", ISSUE_FORMS_PAGE)):
            action = QAction(title, self)
            action.triggered.connect(lambda _checked=False, page=url: self.open_support_page(page))
            help_menu.addAction(action)
        help_menu.addSeparator()
        api_key_action = QAction("Get optional Veilbreak API key...", self)
        api_key_action.triggered.connect(self.open_veilbreak_api_key_page)
        help_menu.addAction(api_key_action)
        help_menu.addSeparator()
        self.system_check_action = QAction("System Check", self)
        self.system_check_action.triggered.connect(self.show_system_check)
        help_menu.addAction(self.system_check_action)
        self.support_bundle_action = QAction("Export Support Bundle", self)
        self.support_bundle_action.triggered.connect(self.export_support_bundle)
        help_menu.addAction(self.support_bundle_action)
        open_logs = QAction("Open Log Folder", self)
        open_logs.triggered.connect(self.open_log_folder)
        help_menu.addAction(open_logs)
        help_menu.addSeparator()
        about = QAction("About LaserLab", self)
        about.triggered.connect(self.show_about)
        help_menu.addAction(about)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._setup_tab(), "Setup")
        self.tabs.addTab(self._run_tab(), "Run")
        self.tabs.addTab(self._review_tab(), "Review")
        self.tabs.addTab(self._compare_tab(), "Compare")
        self.tabs.addTab(self._export_tab(), "Export")
        central = QWidget()
        central_layout = QVBoxLayout(central)
        self.demo_banner = QWidget()
        banner_layout = QHBoxLayout(self.demo_banner)
        self.demo_notice = QLabel(
            "Practice demo: public sample clips are not a matched scientific experiment."
        )
        self.demo_notice.setWordWrap(True)
        banner_layout.addWidget(self.demo_notice, 1)
        self.try_own_button = QPushButton("Try your own footage")
        self.try_own_button.clicked.connect(self.analyze_my_footage)
        banner_layout.addWidget(self.try_own_button)
        self.demo_banner.setVisible(False)
        central_layout.addWidget(self.demo_banner)
        central_layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(f"Ready / LaserLab v{__version__}")

    def _setup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("LaserLab / explore recorded laser patterns")
        title.setObjectName("title")
        subtitle = QLabel(
            "See what image-analysis tools find in laser recordings, then compare "
            "those findings against a similar control recording. No coding or login required."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        beginner_tip = QLabel(
            "First time? Start with the bundled demo; it needs no recordings. "
            "For your own test, add a laser video and a comparison video recorded "
            "with the same camera and scene settings."
        )
        beginner_tip.setObjectName("subtitle")
        beginner_tip.setWordWrap(True)
        layout.addWidget(beginner_tip)

        actions = QGroupBox("Start")
        action_layout = QHBoxLayout(actions)
        self.home_demo_button = QPushButton("Run bundled demo")
        self.home_demo_button.setToolTip(
            "Try the buttons using public practice clips. The demo is not a matched scientific test."
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
        self.home_veilbreak_button = QPushButton("Explore Veilbreak protocols")
        self.home_veilbreak_button.setToolTip(
            "Browse published community protocols read-only; no login or upload required."
        )
        self.home_veilbreak_button.clicked.connect(
            lambda: self.browse_veilbreak("protocols")
        )
        action_layout.addWidget(self.home_veilbreak_button)
        self.home_walkthrough_button = QPushButton("How it works")
        self.home_walkthrough_button.clicked.connect(self.show_quick_start)
        action_layout.addWidget(self.home_walkthrough_button)
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
        recent = self.preferences.get("recent_experiments", [])
        default_experiment = Path(recent[0]) if recent else default_experiments_dir() / "my-first-experiment"
        self.experiment_path = QLineEdit(str(default_experiment))
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
            "Your experiment is saved locally in this folder. Choose Create / Open, "
            "then add a laser recording and a matched comparison recording. "
            "You can use the demo without making your own experiment."
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

        how_to_record = QLabel(
            "First add the laser video (or images). Next add a matched comparison "
            "recording, with camera, focus, exposure, target and geometry kept as "
            "similar as possible. A control helps rule out ordinary visual artifacts."
        )
        how_to_record.setObjectName("subtitle")
        how_to_record.setWordWrap(True)
        layout.addWidget(how_to_record)

        source_group = QGroupBox("Choose your recording")
        source_layout = QGridLayout(source_group)
        self.source_path = QLineEdit()
        browse_source = QPushButton("Browse")
        browse_source.clicked.connect(self.browse_source)
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(["video", "image-set"])
        self.label_combo = QComboBox()
        for display, code in (
            ("Laser recording", "laser"),
            ("Matched comparison (same setup)", "matched_control"),
            ("Other comparison", "control"),
            ("Camera / sensor noise", "sensor_noise"),
            ("Synthetic positive test", "synthetic_positive"),
            ("Synthetic negative test", "synthetic_negative"),
        ):
            self.label_combo.addItem(display, code)
        self.label_combo.setToolTip(
            "Choose what the file actually contains. LaserLab hides these roles during blind review."
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
        self.laser_pattern_combo.setCurrentText("unknown")
        self.wavelength_nm = QDoubleSpinBox()
        self.wavelength_nm.setRange(0.0, 2000.0)
        self.wavelength_nm.setDecimals(1)
        self.wavelength_nm.setSpecialValueText("Unknown")
        self.wavelength_nm.setValue(0.0)
        self.wavelength_nm.setSuffix(" nm")
        self.surface_combo = QComboBox()
        self.surface_combo.addItems(["matte_wall", "painted_drywall", "textured_paper", "fabric", "other", "unknown"])
        self.surface_combo.setCurrentText("unknown")
        self.camera_fixed_check = QCheckBox("Camera fixed")
        self.beam_fixed_check = QCheckBox("Beam path fixed")
        self.non_reflective_check = QCheckBox("Non-reflective target")
        self.not_saturated_check = QCheckBox("Projected region not saturated")
        for check in (self.camera_fixed_check, self.beam_fixed_check, self.non_reflective_check, self.not_saturated_check):
            check.setTristate(True)
            check.setCheckState(Qt.PartiallyChecked)
            check.setToolTip("Partially checked: unknown. Checked: yes. Empty: no. Leave unknown facts unset.")
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

        source_layout.addWidget(QLabel("Video or image folder"), 0, 0)
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
        unknown_help = QLabel("For capture facts: partly checked = unknown, checked = yes, empty = no. Leave unknown settings unset.")
        unknown_help.setWordWrap(True)
        essential_layout.addWidget(unknown_help, 4, 0, 1, 4)
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
        self.mount_type.setCurrentText("unknown")
        self.cross_center_visible = QCheckBox("Cross center visible")
        self.entire_cross_visible = QCheckBox("Entire cross visible")
        self.surface_texture_visible = QCheckBox("Surface texture visible")
        self.geometry_notes = QLineEdit()
        self.intermediate_notes = QLineEdit()
        self.room_lighting_notes = QLineEdit()
        self.camera_description = QLineEdit()
        self.exposure_description = QLineEdit()
        self.focus_description = QLineEdit()
        self.compression_description = QLineEdit()
        for field in (self.camera_description, self.exposure_description, self.focus_description, self.compression_description):
            field.setPlaceholderText("Optional; leave blank when unknown")
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
        self.independent_pair_id = QLineEdit()
        self.independent_pair_id.setPlaceholderText("Optional non-identifying ID shared by one independent laser/control pair")
        self.pair_exchangeability = QCheckBox("Independent pair; within-pair exchangeability justified")
        self.pair_exchangeability.setToolTip(
            "Only declare this for independently acquired pairs with a justified exchangeable design under the null. "
            "Copies, extra frames, and different filenames are not independent repeats. Leave unset if unknown."
        )
        advanced_layout.addWidget(QLabel("Independent matched pair ID"), 12, 0)
        advanced_layout.addWidget(self.independent_pair_id, 12, 1, 1, 3)
        advanced_layout.addWidget(self.pair_exchangeability, 13, 0, 1, 4)
        for row, label, field in (
            (14, "Camera / device", self.camera_description),
            (15, "Exposure settings", self.exposure_description),
            (16, "Focus settings", self.focus_description),
            (17, "Compression history", self.compression_description),
        ):
            advanced_layout.addWidget(QLabel(label), row, 0)
            advanced_layout.addWidget(field, row, 1, 1, 3)
        self.acquisition_source_hash = QLineEdit()
        self.acquisition_source_hash.setPlaceholderText("Optional known original acquisition SHA-256; leave unknown lineage unset")
        self.acquisition_source_hash.setToolTip("For session replication: record the original acquisition hash, including when importing a derived clip. Shared originals are not independent sessions.")
        advanced_layout.addWidget(QLabel("Original acquisition SHA-256"), 18, 0)
        advanced_layout.addWidget(self.acquisition_source_hash, 18, 1, 1, 3)
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
        replication = QGroupBox("Optional independent-session plan — record before the first run")
        replication_form = QFormLayout(replication)
        self.replication_hypothesis = QLineEdit()
        self.replication_hypothesis.setPlaceholderText("Shared non-identifying hypothesis token; no personal details")
        self.replication_independent = QCheckBox("These sessions use independently acquired original recordings, not copied or derived repeats")
        self.record_replication_button = QPushButton("Record pre-run replication plan")
        self.record_replication_button.clicked.connect(self.record_session_plan)
        replication_form.addRow("Hypothesis token", self.replication_hypothesis)
        replication_form.addRow(self.replication_independent)
        replication_form.addRow(self.record_replication_button)
        replication_note = QLabel("Fixes the current protocol/primary metric and criterion: each session must exceed its own matched controls. Local declarations cannot prove independence or external preregistration.")
        replication_note.setWordWrap(True)
        replication_form.addRow(replication_note)
        advanced_layout.addWidget(replication)
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

        pair_group = QGroupBox("Pair Quality — is this comparison fair?")
        pair_layout = QVBoxLayout(pair_group)
        self.pair_quality_button = QPushButton("Check pair quality")
        self.pair_quality_button.clicked.connect(self.inspect_pair_quality)
        pair_layout.addWidget(self.pair_quality_button)
        self.pair_quality_details = QTextEdit()
        self.pair_quality_details.setReadOnly(True)
        self.pair_quality_details.setMinimumHeight(170)
        self.pair_quality_details.setPlainText("Before Run, check the recorded laser/control pairs for mismatches and missing details. No original video is decoded again.")
        pair_layout.addWidget(self.pair_quality_details)
        layout.addWidget(pair_group, 2)

        self.quality_checklist = QTextEdit()
        self.quality_checklist.setReadOnly(True)
        self.quality_checklist.setObjectName("checklist")
        self.quality_checklist.setMaximumHeight(120)
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
            ("sample_count", "Frames / probes"),
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
        glossary = QLabel(
            "Candidate region: an area selected for inspection. Blinded: source roles are hidden. "
            "Matched control: a comparison from the same recording setup. "
            "OCR attempt: software's guess at text, not validated language. "
            "Null result: these measurements did not exceed controls; it does not settle the broader claim."
        )
        glossary.setWordWrap(True)
        glossary.setObjectName("subtitle")
        layout.addWidget(glossary)

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
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _compare_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.family_table = QTableWidget(0, 4)
        self.family_table.setHorizontalHeaderLabels(["Detector family", "Mean", "Low", "High"])
        self.family_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.family_table.verticalHeader().setVisible(False)
        self.family_table.setMaximumHeight(180)
        layout.addWidget(QLabel("Detector-family comparison across laser samples"))
        layout.addWidget(self.family_table, 1)
        self.compare_notes = QTextEdit()
        self.compare_notes.setReadOnly(True)
        self.compare_notes.setMaximumHeight(120)
        layout.addWidget(self.compare_notes)
        sessions = QGroupBox("Optional comparison across local sessions")
        session_layout = QVBoxLayout(sessions)
        self.session_compare_button = QPushButton("Compare unblinded sessions")
        self.session_compare_button.clicked.connect(self.compare_local_sessions)
        session_layout.addWidget(self.session_compare_button)
        self.session_comparison_details = QTextEdit()
        self.session_comparison_details.setReadOnly(True)
        self.session_comparison_details.setMinimumHeight(170)
        self.session_comparison_details.setPlainText("Choose two to eight explicitly unblinded experiments. Outcomes remain separate; no pooled significance or upload.")
        session_layout.addWidget(self.session_comparison_details)
        self.session_privacy = QCheckBox("I reviewed this pseudonymized summary and its privacy implications before local export")
        self.session_privacy.toggled.connect(lambda: self.session_export_button.setEnabled(bool(self.session_comparison) and self.session_privacy.isChecked() and not self._busy))
        session_layout.addWidget(self.session_privacy)
        self.session_export_button = QPushButton("Export local session summary")
        self.session_export_button.setEnabled(False)
        self.session_export_button.clicked.connect(self.export_session_summary)
        session_layout.addWidget(self.session_export_button)
        layout.addWidget(sessions, 2)
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

        demo_tip = QLabel(
            "Practice with bundled public optical videos. These are not a matched "
            "experimental pair, so demo findings are not scientific evidence about your setup."
        )
        demo_tip.setObjectName("subtitle")
        demo_tip.setWordWrap(True)
        layout.addWidget(demo_tip)

        demo = QGroupBox("Demo")
        demo_layout = QGridLayout(demo)
        self.demo_experiment_path = QLineEdit(str(default_experiments_dir() / "bundled-demo"))
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
        self.include_media.setToolTip(
            "Adds original recordings to the local ZIP after unblinding. "
            "Check consent, personal details and source licenses before sharing. No automatic upload."
        )
        grid.addWidget(open_report, 0, 0)
        grid.addWidget(self.export_csv_button, 0, 1)
        grid.addWidget(self.export_bundle_button, 0, 2)
        grid.addWidget(self.include_media, 1, 0, 1, 3)
        layout.addWidget(actions)

        sharing = QLabel(
            "Before sharing: review the ZIP, remove private details, check consent and source licenses. "
            "Include source media adds your original recordings. Export saves locally; it never uploads."
        )
        sharing.setWordWrap(True)
        layout.addWidget(sharing)

        support = QGroupBox("Installation Support")
        support_grid = QGridLayout(support)
        self.system_check_button = QPushButton("System Check")
        self.system_check_button.clicked.connect(self.show_system_check)
        self.support_bundle_button = QPushButton("Export Support Bundle")
        self.support_bundle_button.clicked.connect(self.export_support_bundle)
        support_note = QLabel("Redacted local diagnostics and logs only. No media, experiment labels, or uploads.")
        support_note.setObjectName("subtitle")
        support_note.setWordWrap(True)
        support_grid.addWidget(self.system_check_button, 0, 0)
        support_grid.addWidget(self.support_bundle_button, 0, 1)
        support_grid.addWidget(support_note, 1, 0, 1, 2)
        layout.addWidget(support)

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
        self.exchange_button = QPushButton("Review local results exchange")
        self.exchange_button.setToolTip("After explicit unblinding, preview a media-free summary before saving. Nothing is submitted to a provider.")
        self.exchange_button.clicked.connect(self.prepare_research_exchange)
        self.community_data_status = QLabel("No local community data attached")
        self.community_data_status.setWordWrap(True)
        self.veilbreak_protocols_button = QPushButton("Browse / refresh public protocols")
        self.veilbreak_protocols_button.clicked.connect(
            lambda: self.browse_veilbreak("protocols")
        )
        self.veilbreak_experiments_button = QPushButton("Browse / refresh public experiments")
        self.veilbreak_experiments_button.clicked.connect(
            lambda: self.browse_veilbreak("experiments")
        )
        self.veilbreak_note = QLabel(
            "The public Veilbreak catalog is free and needs no API key. "
            "You can optionally obtain a separate, read-only REST API key. "
            "Selected records are context only; no private footage is uploaded."
        )
        self.veilbreak_key_button = QPushButton("Get optional Veilbreak API key")
        self.veilbreak_key_button.setToolTip(
            "Opens Veilbreak's official website to generate a key with your email. "
            "LaserLab does not request, receive, or store your key."
        )
        self.veilbreak_key_button.clicked.connect(self.open_veilbreak_api_key_page)
        self.veilbreak_note.setObjectName("subtitle")
        self.veilbreak_note.setWordWrap(True)
        community_grid.addWidget(self.import_reference_button, 0, 0)
        community_grid.addWidget(self.import_symbols_button, 0, 1)
        community_grid.addWidget(self.export_symbols_button, 0, 2)
        community_grid.addWidget(self.community_data_status, 1, 0, 1, 3)
        community_grid.addWidget(self.veilbreak_protocols_button, 2, 0)
        community_grid.addWidget(self.veilbreak_experiments_button, 2, 1)
        community_grid.addWidget(self.veilbreak_key_button, 3, 0, 1, 2)
        community_grid.addWidget(self.veilbreak_note, 4, 0, 1, 3)
        community_grid.addWidget(self.exchange_button, 5, 0, 1, 3)
        self.veilbreak_cache_optin = QCheckBox("Save public catalogs on this device for offline use (24 hours)")
        self.veilbreak_cache_optin.setChecked(self.preferences.get("veilbreak_cache_enabled") is True)
        self.veilbreak_cache_optin.toggled.connect(self._cache_choice_changed)
        self.saved_protocols_button = QPushButton("Open saved protocols")
        self.saved_protocols_button.clicked.connect(lambda: self.browse_saved_veilbreak("protocols"))
        self.saved_experiments_button = QPushButton("Open saved experiments")
        self.saved_experiments_button.clicked.connect(lambda: self.browse_saved_veilbreak("experiments"))
        self.clear_catalog_cache_button = QPushButton("Clear saved catalogs")
        self.clear_catalog_cache_button.clicked.connect(self.clear_public_catalog_cache)
        cache_note = QLabel("Saved copies contain public titles and limited optical metadata with retrieval/expiry times and a license-policy reference. Copies remain on disk until cleared; they become unavailable after 24 hours. Refresh explicitly reads the public service.")
        cache_note.setWordWrap(True)
        community_grid.addWidget(self.veilbreak_cache_optin, 6, 0, 1, 3)
        community_grid.addWidget(self.saved_protocols_button, 7, 0)
        community_grid.addWidget(self.saved_experiments_button, 7, 1)
        community_grid.addWidget(self.clear_catalog_cache_button, 7, 2)
        community_grid.addWidget(cache_note, 8, 0, 1, 3)
        self._update_cache_controls()
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
        """Short, supportive guide for users without a technical background."""
        QMessageBox.information(
            self,
            "LaserLab / First-time walkthrough",
            "Welcome to LaserLab!\n\n"
            "1. Click Run bundled demo to practice with included public videos. "
            "The demo clips are NOT matched scientific controls.\n\n"
            "2. For your own footage, click Analyze my footage. "
            "LaserLab opens a local experiment folder and lets you choose a video.\n\n"
            "3. Add a second, matched comparison recording from a similar camera setup. "
            "Without a suitable control, a striking pattern can be an ordinary artifact. "
            "One pair remains descriptive: extra frames are not new experiments. Statistical comparisons "
            "need at least five independently acquired, predeclared matched pairs and suitable conditions.\n\n"
            "4. Choose an Analysis Plan and Run. Inspect proposed shapes in Review "
            "before you explicitly reveal which recording they came from.\n\n"
            "5. A score or OCR fragment is not proof of a message or its origin. "
            "Null findings are useful too. Exporting or sharing is always optional.\n\n"
            "Keep lasers away from eyes and reflective surfaces. "
            "No Veilbreak account, API key, or programming experience is needed to start.",
        )

    def _preview_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setMinimumSize(250, 220)
        label.setObjectName("preview")
        return label

    def analyze_my_footage(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        if not self.experiment_dir or self.is_demo_experiment:
            previous_path = self.experiment_path.text()
            if self.is_demo_experiment or Path(previous_path).exists():
                path = QFileDialog.getExistingDirectory(
                    self, "Choose a folder for your personal experiment", str(default_experiments_dir())
                )
                if not path:
                    return
                self.experiment_path.setText(path)
            if not self.open_experiment(allow_demo=False):
                self.experiment_path.setText(previous_path)
                return
        self.tabs.setCurrentIndex(0)
        self.setup_steps.setCurrentIndex(1)
        self.status.showMessage(
            "Select your laser recording. Next, add a matched comparison recording."
        )
        self.browse_source()

    def open_existing_experiment(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Open existing experiment", self.experiment_path.text()
        )
        if not path:
            return
        previous_path = self.experiment_path.text()
        self.experiment_path.setText(path)
        if not self.open_experiment():
            self.experiment_path.setText(previous_path)
            return
        self.setup_steps.setCurrentIndex(0)
        if self.tabs.isTabVisible(0):
            self.tabs.setCurrentIndex(0)

    def browse_experiment(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Experiment Directory", self.experiment_path.text())
        if path:
            self.experiment_path.setText(path)

    def browse_source(self) -> None:
        start_dir = str(self.preferences.get("last_source_directory") or "")
        if self.kind_combo.currentText() == "image-set":
            path = QFileDialog.getExistingDirectory(self, "Image Set", start_dir)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Video Source", start_dir, "Videos (*.mp4 *.avi *.mov *.mkv *.webm *.ogv);;All files (*.*)"
            )
        if path:
            self.source_path.setText(path)
            source_dir = Path(path) if Path(path).is_dir() else Path(path).parent
            try:
                self.preferences = set_last_source_directory(source_dir)
            except OSError:
                LOGGER.warning("Could not persist the last source directory", exc_info=True)

    def open_experiment(
        self,
        _checked: bool = False,
        *,
        allow_demo: bool = True,
        preserve_pending_capture: bool = False,
    ) -> bool:
        if self._busy or (self.worker and self.worker.isRunning()):
            self._error("Wait for the current task before switching experiments.")
            return False
        try:
            if not self.experiment_path.text().strip():
                raise ValueError("Choose a local folder for this experiment first.")
            experiment_dir = Path(self.experiment_path.text()).expanduser().resolve()
            if not allow_demo and (experiment_dir / "manifest.json").exists():
                existing = load_manifest(experiment_dir)
                if existing.get("experiment_purpose") == "demo":
                    raise ValueError("This folder contains a practice demo. Choose a different folder for your footage.")
            manifest = app_api.create_experiment(experiment_dir)
            self.experiment_dir = experiment_dir
            self.is_demo_experiment = manifest.get("experiment_purpose") == "demo"
            self.demo_banner.setVisible(self.is_demo_experiment)
            self.latest_report = None
            for preview in (self.original_preview, self.processed_preview, self.crop_preview):
                preview.clear()
            self.candidate_details.clear()
            self.review_note.clear()
            for flag in self.review_flag_checks.values():
                flag.setChecked(False)
            if not preserve_pending_capture:
                # Explicit experiment switches discard stale capture selections. When
                # Add Capture creates the first experiment, keep the file and role
                # the user already chose on the capture form.
                self.source_path.clear()
                self.label_combo.setCurrentIndex(self.label_combo.findData("laser"))
            self.include_media.setChecked(False)
            self._populate_report({"review_state": {"unblinded": True}})
            self.complete_review_button.setEnabled(False)
            self.unblind_button.setEnabled(False)
            self.pair_quality_details.setPlainText("Check Pair Quality for this experiment before Run.")
            self._clear_session_comparison("Choose unblinded experiments to compare their separate session outcomes.")
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
            self._remember_experiment(experiment_dir)
            self.status.showMessage(f"Experiment open: {self.experiment_dir}")
            self.refresh_review(silent=True)
            self.update_estimate()
            return True
        except Exception as exc:
            LOGGER.exception("Could not open experiment")
            self._error(str(exc))
            return False

    def open_support_page(self, url: str) -> None:
        if url not in {SUPPORT_PAGE, ISSUE_FORMS_PAGE}:
            return
        if not QDesktopServices.openUrl(QUrl(url)):
            self._error("Could not open the browser. Use Help > System Check and Export Support Bundle for local help.")

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.clear()
        recent = self.preferences.get("recent_experiments", [])
        if not recent:
            empty = QAction("No recent experiments", self)
            empty.setEnabled(False)
            self.recent_menu.addAction(empty)
            return
        for raw_path in recent:
            path = Path(raw_path)
            action = QAction(path.name or str(path), self)
            action.setStatusTip(str(path))
            action.triggered.connect(lambda _checked=False, selected=path: self._open_recent_experiment(selected))
            self.recent_menu.addAction(action)

    def _remember_experiment(self, experiment_dir: Path) -> None:
        try:
            self.preferences = remember_experiment(experiment_dir)
            self._refresh_recent_menu()
        except OSError:
            LOGGER.warning("Could not persist recent experiment", exc_info=True)

    def _open_recent_experiment(self, experiment_dir: Path) -> None:
        self.tabs.setCurrentIndex(0)
        self.setup_steps.setCurrentIndex(0)
        self.experiment_path.setText(str(experiment_dir))
        self.open_experiment()

    def show_system_check(self) -> None:
        try:
            record = collect_diagnostics(self.experiment_dir)
            dependencies = record.get("dependencies", {})
            tesseract = record.get("ocr", {}).get("tesseract", {})
            fixtures = record.get("fixtures", {})
            lines = [
                f"LaserLab {record.get('laserlab_version', 'unknown')}",
                f"Python {record.get('runtime', {}).get('python_version', 'unknown')}",
                f"Packaged app: {'yes' if record.get('runtime', {}).get('frozen') else 'no'}",
                "",
                "Core dependencies:",
            ]
            for name in ("numpy", "opencv", "PyQt5", "pytesseract"):
                item = dependencies.get(name, {})
                version = f" {item.get('version')}" if item.get("version") else ""
                lines.append(f"  {name}: {item.get('status', 'unknown')}{version}")
            lines.extend(
                [
                    "",
                    f"Bundled fixtures: {'ready' if fixtures.get('catalog_valid') else 'check failed'} "
                    f"({fixtures.get('bundled_file_count', 0)}/{fixtures.get('redistributable_count', 0)})",
                    f"Tesseract OCR: {tesseract.get('status', 'unknown')} (optional)",
                    "",
                    "No telemetry or uploads were performed.",
                ]
            )
            QMessageBox.information(self, "LaserLab System Check", "\n".join(lines))
        except Exception as exc:
            LOGGER.exception("System check failed")
            self._error(f"System check failed: {exc}")

    def export_support_bundle(self) -> None:
        default_name = f"LaserLab-support-v{__version__}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "Export Support Bundle", default_name, "ZIP (*.zip)")
        if not path:
            return
        try:
            exported = write_support_bundle(Path(path), self.experiment_dir)
            self.export_log.append(f"Support bundle exported: {exported}\nReview diagnostics and the log before sharing.")
            self.status.showMessage(f"Support bundle exported: {exported}. Review its contents before sharing.")
        except Exception as exc:
            LOGGER.exception("Support bundle export failed")
            self._error(f"Support bundle export failed: {exc}")

    def open_log_folder(self) -> None:
        path = get_state_dir() / "logs"
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def show_about(self) -> None:
        QMessageBox.information(
            self,
            "About LaserLab",
            f"LaserLab v{__version__}\n\n"
            "Local-first blinded analysis of laser footage and matched controls.\n"
            "LaserLab reports bounded detector evidence; it does not establish origin, intent, or metaphysical meaning.",
        )

    def add_capture(self) -> None:
        if not self.source_path.text().strip():
            self._error("Choose a source path before adding a capture.")
            return
        experiment = self._require_experiment(preserve_pending_capture=True)
        if not experiment:
            return
        if self.is_demo_experiment:
            self._error("This is a practice demo. Choose Try your own footage before adding recordings.")
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
        if self._busy:
            self._error("A task is already running.")
            return
        experiment = self._require_experiment()
        if not experiment:
            return
        # Read widgets on the GUI thread and keep the same context through preflight.
        options = {
            "profile": self.profile_combo.currentText(),
            "blind_seed": self.blind_seed.value(),
            "protocol": self._current_protocol(),
            "roi": self._roi(),
            "primary_metric": self.primary_metric_combo.currentText(),
            "preprocessing_intensity": self.preprocessing_intensity.currentText(),
            "control_generation": self.control_generation.currentText(),
        }
        self._run_worker("Checking comparison quality", lambda: app_api.assess_pair_quality(experiment),
                         lambda result: self._pair_quality_ready(result, experiment, options))

    def inspect_pair_quality(self) -> None:
        experiment = self._require_experiment()
        if not experiment:
            return
        self._run_worker("Checking comparison quality", lambda: app_api.assess_pair_quality(experiment),
                         lambda result: self._show_pair_quality(result, experiment))

    def record_session_plan(self) -> None:
        if self._busy:
            return
        experiment = self._require_experiment()
        if not experiment:
            return
        try:
            app_api.record_replication_plan(experiment, self.replication_hypothesis.text().strip(),
                                            self.replication_independent.isChecked(), self._current_protocol(),
                                            self.primary_metric_combo.currentText())
            self.replication_hypothesis.clear()
            self.status.showMessage("Local pre-run plan recorded; acquisition and preregistration remain unverified declarations")
        except Exception as exc:
            self._error(str(exc))

    def compare_local_sessions(self) -> None:
        if self._busy:
            return
        if self.latest_report and not self._review_is_unblinded():
            self._error("Finish and explicitly unblind the active review before comparing sessions.")
            return
        count, accepted = QInputDialog.getInt(self, "Compare local sessions", "Number of unblinded experiments", 2, 2, 8)
        if not accepted:
            return
        directories = []
        for number in range(count):
            selected = QFileDialog.getExistingDirectory(self, f"Choose unblinded experiment {number + 1} of {count}",
                                                        str(self.experiment_dir or default_experiments_dir()))
            if not selected:
                return
            directories.append(Path(selected))
        self._run_worker("Comparing local sessions", lambda: app_api.compare_sessions(directories),
                         lambda result: self._session_comparison_ready(result, directories))

    def _session_comparison_ready(self, summary: dict[str, Any], directories: list[Path]) -> None:
        if self.latest_report and not self._review_is_unblinded():
            self._error("The active review is blinded; compare sessions after explicit unblinding.")
            return
        self.session_comparison = summary
        self.comparison_directories = list(directories)
        self.session_comparison_details.setHtml(comparison_html(summary))
        self.session_privacy.setChecked(False)
        self.session_export_button.setEnabled(False)

    def _clear_session_comparison(self, message: str) -> None:
        self.session_comparison = None
        self.comparison_directories = []
        self.session_comparison_details.setPlainText(message)
        self.session_privacy.setChecked(False)
        self.session_export_button.setEnabled(False)

    def export_session_summary(self) -> None:
        if not self.session_comparison or not self.session_privacy.isChecked():
            self._error("Review the session summary and acknowledge privacy before export.")
            return
        output, _ = QFileDialog.getSaveFileName(self, "Export local session summary", "session-comparison.json", "JSON (*.json)")
        if not output:
            return
        directories = list(self.comparison_directories)
        snapshot = self.session_comparison["_snapshot_sha256"]
        self._run_worker("Exporting local session summary", lambda: app_api.export_session_comparison(
            directories, Path(output), privacy_acknowledged=True, expected_snapshot=snapshot),
            lambda result: self.status.showMessage("Local session summary exported; no upload"))

    def _show_pair_quality(self, assessment: dict[str, Any], experiment: Path) -> bool:
        if self.experiment_dir != experiment:
            self._error("The experiment changed. Check Pair Quality again before Run.")
            return False
        self.pair_quality_details.setHtml(pair_quality_html(assessment))
        return True

    def _pair_quality_ready(self, assessment: dict[str, Any], experiment: Path, run_options: dict[str, Any]) -> None:
        if not self._show_pair_quality(assessment, experiment):
            return
        if assessment.get("requires_exploratory"):
            choice = QMessageBox(self)
            choice.setWindowTitle("Review comparison quality")
            choice.setIcon(QMessageBox.Warning)
            choice.setText(assessment.get("summary", "Comparison details are incomplete."))
            choice.setInformativeText(
                "Read the Pair Quality checks on Run. You can inspect patterns as an exploratory run; "
                "significance and effect-size claims will be withheld. Cancel to review the recordings or missing details."
            )
            proceed = choice.addButton("Proceed as exploratory", QMessageBox.AcceptRole)
            cancel = choice.addButton(QMessageBox.Cancel)
            choice.setDefaultButton(cancel)
            choice.exec_()
            if choice.clickedButton() is not proceed:
                return
        self._launch_analysis(experiment, run_options)

    def _launch_analysis(self, experiment: Path, run_options: dict[str, Any]) -> None:
        if self.experiment_dir != experiment:
            self._error("The experiment changed. Check Pair Quality again before Run.")
            return
        # Role-specific setup details must not survive into sealed review widgets.
        self.pair_quality_details.setPlainText("Pair Quality source details are sealed during review.")
        self.quality_checklist.setPlainText("Source details remain sealed until explicit unblinding.")
        self._clear_session_comparison("Session comparison is unavailable during the active sealed review.")
        self._run_worker("Running analysis", lambda: app_api.run_analysis(experiment_dir=experiment, **run_options),
                         self._analysis_finished)

    def run_fixture_demo(self) -> None:
        if self._busy or (self.worker and self.worker.isRunning()):
            self._error("Wait for the current task before switching experiments.")
            return
        if not self.demo_experiment_path.text().strip():
            self._error("Choose a base folder for the practice demo first.")
            return
        experiment_base = Path(self.demo_experiment_path.text())
        self._clear_session_comparison("Session comparison is unavailable during the active sealed review.")
        protocol = self.demo_protocol.currentData() or "anomaly"
        max_frames = self.demo_max_frames.value()

        def task() -> dict[str, Any]:
            return app_api.run_bundled_demo(experiment_base, max_frames=max_frames, protocol=protocol)

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
            manifest = load_manifest(experiment)
        except Exception as exc:
            self._error(str(exc))
            return
        if report.get("review_state", {}).get("unblinded") and (
            report.get("subjective_reports")
            or (report.get("psychophysics_analysis") or {}).get("analysis_status") == "tested"
            or report.get("external_dataset_references")
            or report.get("symbol_transcription_summary", {}).get("record_count", 0)
            or manifest.get("replication_plan")
        ):
            answer = QMessageBox.question(
                self,
                "Privacy review",
                "Confirm that research plans, participant IDs, subjective context, community metadata, and sharing risk were reviewed.",
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

    def open_veilbreak_api_key_page(self) -> None:
        """Open the official external signup page; never handle API secrets.

        Veilbreak's public MCP catalog is keyless. Its separate read-only REST
        API key is optional and generated by Veilbreak, not LaserLab.
        """
        if not QDesktopServices.openUrl(QUrl(VEILBREAK_API_KEY_PAGE)):
            QMessageBox.information(
                self,
                "Veilbreak API key",
                "Could not open your browser. Visit Veilbreak's official API access "
                "page:\n" + VEILBREAK_API_KEY_PAGE,
            )
        else:
            self.status.showMessage(
                "Opened Veilbreak's API key page. No key is required for public catalog browsing."
            )

    def prepare_research_exchange(self) -> None:
        if not self.experiment_dir:
            self._error("Open an analyzed experiment and explicitly unblind its review first.")
            return
        experiment = self.experiment_dir
        self._run_worker("Preparing local results exchange", lambda: app_api.prepare_research_exchange(experiment),
                         lambda preview: self._review_research_exchange(experiment, preview))

    def _review_research_exchange(self, experiment: Path, preview: dict[str, Any]) -> None:
        if self.experiment_dir != experiment:
            self._error("The experiment changed. Prepare a new exchange preview.")
            return
        dialog = ResearchExchangeDialog(preview, lambda **options: app_api.prepare_research_exchange(experiment, **options), self)
        if not dialog.exec_() or dialog.preview is None or not dialog.privacy.isChecked():
            return
        output, _ = QFileDialog.getSaveFileName(self, "Save reviewed local results exchange", "research-exchange.json", "JSON (*.json)")
        if not output:
            return
        snapshot = dialog.preview["_snapshot_sha256"]
        options = dialog.options()
        self._run_worker("Saving reviewed local results exchange", lambda: app_api.export_research_exchange(
            experiment, Path(output), expected_snapshot=snapshot, privacy_acknowledged=True, **options),
            lambda result: self.status.showMessage("Reviewed results exchange saved locally; no upload."))

    def _update_cache_controls(self) -> None:
        available = self.veilbreak_cache_optin.isChecked() and not self._busy
        self.saved_protocols_button.setEnabled(available)
        self.saved_experiments_button.setEnabled(available)
        self.veilbreak_cache_optin.setEnabled(not self._busy)
        self.clear_catalog_cache_button.setEnabled(not self._busy)

    def _cache_choice_changed(self, enabled: bool) -> None:
        previous = self.preferences.get("veilbreak_cache_enabled") is True
        try:
            self.preferences = set_veilbreak_cache_enabled(enabled)
        except (OSError, ValueError):
            self.veilbreak_cache_optin.blockSignals(True)
            self.veilbreak_cache_optin.setChecked(previous)
            self.veilbreak_cache_optin.blockSignals(False)
            self._error("The public cache choice could not be saved. No new choice was applied.")
        self._update_cache_controls()

    def clear_public_catalog_cache(self) -> None:
        self._run_worker("Clearing saved public catalogs", lambda: CatalogCache().clear(),
                         lambda count: self.community_data_status.setText(f"Cleared {count} saved public catalog(s)."))

    def browse_saved_veilbreak(self, kind: str) -> None:
        enabled = self.veilbreak_cache_optin.isChecked()
        self._run_worker("Opening saved public catalog", lambda: open_saved_catalog(kind, cache_enabled=enabled),
                         lambda view: self._catalog_ready(kind, view))

    def _catalog_ready(self, kind: str, view: dict[str, Any]) -> None:
        source = view["provenance"]
        origin = "Saved copy" if source["origin"] == "saved" else "Public service"
        note = f"{origin}. Retrieved {source['retrieved_at']}; expires {source['expires_at']}. Per-record license/attribution remains unverified."
        if view["cache_status"] == "save_failed":
            note += " Saving the offline copy failed; these records are available in this live view only."
        self.community_data_status.setText(note)
        self._choose_veilbreak_record(kind, view["records"], source_note=note)

    def browse_veilbreak(self, kind: str) -> None:
        """Fetch published community metadata on demand, never in the background."""
        if kind not in ("protocols", "experiments"):
            self._error("Unknown Veilbreak catalog.")
            return
        enabled = self.veilbreak_cache_optin.isChecked()
        self._run_worker(
            f"Reading Veilbreak public {kind}",
            lambda: refresh_catalog(kind, cache_enabled=enabled),
            lambda view: self._catalog_ready(kind, view),
        )

    def _choose_veilbreak_record(
        self, kind: str, records: list[dict[str, Any]], *, source_note: str = ""
    ) -> None:
        if not records:
            QMessageBox.information(
                self, "Veilbreak catalog", "No published records were returned."
            )
            return
        dialog = VeilbreakCatalogDialog(kind, records, self, source_note=source_note)
        if not dialog.exec_():
            return
        record = dialog.selected_record()
        if record is None:
            return
        if self.experiment_dir is None:
            self.tabs.setCurrentIndex(0)
            self.setup_steps.setCurrentIndex(0)
            QMessageBox.information(
                self,
                "Create or open an experiment",
                "Catalog browsing worked. Create or open a LaserLab experiment "
                "before linking a Veilbreak reference; no data was saved.",
            )
            return
        answer = QMessageBox.question(
            self, "Link public research metadata",
            f"Link Veilbreak {record['record_type']} #{record['record_id']} "
            f"to this local experiment as context-only metadata?\n\n"
            "This does not change detector scores, import participant reports, "
            "upload footage, or publish results. Reported equipment values are "
            "not measurements of your own setup.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            linked = app_api.link_veilbreak_reference(self.experiment_dir, record)
            self.community_data_status.setText(
                f"Linked Veilbreak {linked['record_type']} #{linked['record_id']} "
                "(context only; source license not verified)"
            )
            self.status.showMessage("Veilbreak reference linked locally; nothing uploaded.")
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
                    f"Source class: {source_class_label(candidate)}",
                    f"Source: {candidate.get('source_path', '')}",
                    f"Frame: {candidate.get('frame_index', 'n/a')}",
                    f"Control: {candidate.get('control_type') or 'n/a'}",
                    "Candidate q-value: not estimated for related frames/variants",
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
        worker = self.worker
        # Complete only after QThread has stopped, so preflight can safely start a run.
        worker.finished.connect(lambda: self._worker_completed(worker, on_success))
        self.worker.start()

    def _worker_completed(self, worker: ApiWorker, on_success: Callable[[Any], None]) -> None:
        if self.worker is not worker:
            return
        self.worker = None
        if worker.error is not None:
            self._worker_failed(worker.error)
        else:
            self._worker_success(worker.result, on_success)
        worker.deleteLater()

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
        self.source_path.clear()
        roles = {capture.get("label") for capture in manifest.get("captures", [])}
        if "laser" in roles and "matched_control" not in roles:
            self.status.showMessage(
                "Laser recording added. Now choose a matched comparison recording."
            )
            comparison = self.label_combo.findData("matched_control")
            if comparison >= 0:
                self.label_combo.setCurrentIndex(comparison)
        elif "laser" in roles and "matched_control" in roles:
            self.status.showMessage(
                "Laser and matched comparison recordings added. Next: check Pair Quality and choose an Analysis Plan. One pair remains descriptive."
            )
        else:
            self.status.showMessage("Recording added. Add the other recording to compare.")

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
        self.experiment_dir = Path(payload["experiment_dir"])
        self.experiment_path.setText(str(self.experiment_dir))
        self.is_demo_experiment = True
        self.demo_banner.setVisible(True)
        self._analysis_finished(payload["run"])
        if self.experiment_dir:
            self._remember_experiment(self.experiment_dir)
        try:
            self._populate_captures(app_api.create_experiment(self.experiment_dir))
        except Exception:
            LOGGER.warning("Could not refresh demo captures", exc_info=True)
        self.status.showMessage("Practice demo complete. Inspect the sample, or choose Try your own footage.")

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
        if "experiment_purpose" in report:
            self.is_demo_experiment = report["experiment_purpose"] == "demo"
            self.demo_banner.setVisible(self.is_demo_experiment)
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
            self._clear_session_comparison("Session comparison is unavailable during the active sealed review.")
            self.pair_quality_details.setPlainText("Pair Quality source details are sealed during review.")
            self.quality_checklist.setPlainText("Source details remain sealed until explicit unblinding.")
            self.include_media.setChecked(False)
            self.tabs.setCurrentIndex(2)
        else:
            self.pair_quality_details.setHtml(pair_quality_html(report.get("pre_run_quality")))
        self.session_compare_button.setEnabled(unblinded and not self._busy)
        for key, label in self.metric_labels.items():
            value = summary.get(key, stats.get(key))
            label.setText("n/a" if value is None else str(value))
            if key == "evidence_ladder":
                self._set_dynamic_property(label, "tone", evidence_tone(value))
        self.badges_label.setText(badge_strip_html(report.get("badges", [])))
        interpretation = report.get("interpretation", {})
        self.interpretation_text.setPlainText(
            ("Practice demo only: these public clips are not matched controls.\n" if self.is_demo_experiment else "")
            + "What this means: " + interpretation.get("what_this_means", "") + "\n"
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
                ("Unscored OCR" if candidate.get("primary_metric_measurement", {}).get("status") == "unscored"
                 else str(candidate.get("primary_metric_score", candidate.get("structure_score", "")))),
                str(candidate.get("persistence_score", "")),
                candidate.get("preprocessing_variant", ""),
                candidate.get("ocr_text", "")[:80],
                self._annotation_summary(candidate),
                candidate.get("processed_path", ""),
            ]
            values = (
                [common[0], source_class_label(candidate), common[1], common[2], "n/a", common[3], candidate.get("source_path", "")[:80], common[4], common[5], common[6]]
                if unblinded
                else common
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(str(value))
                self.candidate_table.setItem(row, column, cell)
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
            score = ("Unscored OCR" if candidate.get("primary_metric_measurement", {}).get("status") == "unscored"
                     else str(candidate.get("primary_metric_score", "")))
            values = [candidate.get("blind_id", ""), score]
            if unblinded:
                values.extend([source_class_label(candidate), candidate.get("source_path", "")])
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
            "Detector families are descriptive; confidence intervals and candidate FDR are not estimated.\n"
            + stats.get("inference", {}).get("message", "") + "\n"
            + "Independent matched pairs: " + str(stats.get("inference", {}).get("pair_count", 0))
            + "; empirical capture records: " + str(stats.get("inference", {}).get("empirical_capture_counts", {}))
            + "; generated null frames: " + str(stats.get("control_diagnostics", {}).get("generated_null", {}).get("frame_count", 0))
            + "; calibration images: " + str(stats.get("synthetic_positive_count", 0))
            + ". Frame persistence is not independent replication or evidence of language, origin, or intent."
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
                manifest = app_api.create_experiment(self.experiment_dir)
                if manifest.get("outputs", {}).get("review_state") == "blinded":
                    self.quality_checklist.setPlainText("Source details remain sealed until explicit unblinding.")
                    return
                captures = manifest.get("captures", [])
            except Exception:
                captures = []
        def capture_class(capture: dict[str, Any]) -> str:
            return sample_class({"capture_id": capture.get("capture_id"), "unblinded_label": capture.get("label"),
                                 "capture_metadata": capture.get("metadata", {}), "synthetic": capture.get("synthetic"),
                                 "control_type": capture.get("control_type"), "parent_capture_id": capture.get("parent_capture_id")})

        classes = {capture_class(capture) for capture in captures}
        warning_count = sum(len(capture.get("provenance_warnings", [])) for capture in captures)
        laser_captures = [capture for capture in captures if capture_class(capture) == "empirical_laser"]
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
            ("empirical laser capture (declared)", "empirical_laser" in classes),
            ("empirical matched control (declared)", "declared_matched_control" in classes),
            ("wall or flat projection target", wall_projection),
            ("fixed camera and geometry", camera_fixed),
            ("non-reflective, non-saturated target", safe_target),
            ("frame count >= 2", estimate.get("sample_count", 0) >= 2),
            ("synthetic null probes enabled (not recorded controls)", self.control_generation.currentText() != "none"),
            ("capture provenance complete", warning_count == 0),
            ("candidate FDR withheld for related frames/variants", True),
        ]
        self.quality_checklist.setHtml(quality_checklist_html(lines) +
            "<p>Analysis may proceed as exploratory. Inferential comparisons require declared empirical matched captures "
            "and at least five independent exchangeable pairs. Repeated frames are not independent experiments.</p>")

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
            "independent_pair_id": self.independent_pair_id.text().strip() or None,
            "acquisition_source_sha256": self.acquisition_source_hash.text().strip() or None,
            "pair_exchangeability_acknowledged": self.pair_exchangeability.isChecked(),
            "footage_class": self.footage_class_combo.currentData() or "other",
            "laser_pattern_type": self.laser_pattern_combo.currentText(),
            "wavelength_nm": self.wavelength_nm.value() or None,
            "projection_surface_type": self.surface_combo.currentText(),
            "camera_fixed": self._optional_check(self.camera_fixed_check),
            "beam_path_fixed": self._optional_check(self.beam_fixed_check),
            "non_reflective_surface": self._optional_check(self.non_reflective_check),
            "projected_region_not_saturated": self._optional_check(self.not_saturated_check),
            "camera": self.camera_description.text().strip() or None,
            "exposure": self.exposure_description.text().strip() or None,
            "focus_mode": self.focus_description.text().strip() or None,
            "compression_history": self.compression_description.text().strip() or None,
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

    @staticmethod
    def _optional_check(check: QCheckBox) -> bool | None:
        state = check.checkState()
        return None if state == Qt.PartiallyChecked else state == Qt.Checked

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

    def _require_experiment(self, *, preserve_pending_capture: bool = False) -> Path | None:
        if not self.experiment_dir:
            if not self.open_experiment(
                allow_demo=not preserve_pending_capture,
                preserve_pending_capture=preserve_pending_capture,
            ):
                return None
        return self.experiment_dir

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        enabled = not busy
        self.setup_steps.setEnabled(enabled)
        self.recent_menu.setEnabled(enabled)
        self.profile_combo.setEnabled(enabled)
        self.blind_seed.setEnabled(enabled)
        for button in (
            self.exchange_button,
            self.try_own_button,
            self.run_button,
            self.pair_quality_button,
            self.session_compare_button,
            self.session_export_button,
            self.record_replication_button,
            self.home_analyze_button,
            self.home_open_button,
            self.add_capture_button,
            self.run_demo_button,
            self.home_demo_button,
            self.home_veilbreak_button,
            self.veilbreak_protocols_button,
            self.veilbreak_experiments_button,
            self.veilbreak_key_button,
            self.export_csv_button,
            self.export_bundle_button,
            self.unblind_button,
            self.complete_review_button,
        ):
            button.setEnabled(enabled)
        self._update_cache_controls()
        if enabled:
            report = self.latest_report or {}
            unblinded = bool(report.get("review_state", {}).get("unblinded", True))
            complete = bool(report.get("review_session", {}).get("complete"))
            self.unblind_button.setEnabled(not unblinded and complete)
            self.complete_review_button.setEnabled(not unblinded and not complete)
            self.session_compare_button.setEnabled(not report or unblinded)
            self.session_export_button.setEnabled(bool(self.session_comparison) and self.session_privacy.isChecked() and (not report or unblinded))

    def _error(self, message: str) -> None:
        LOGGER.warning("User-visible error: %s", message)
        self.status.showMessage(message)
        QMessageBox.warning(
            self, "LaserLab", message + "\n\nTry Help > System Check or Export Support Bundle. "
            "Review diagnostics before sharing; Help > Troubleshooting guide has recovery steps."
        )


def main() -> int:
    configure_logging()
    app = QApplication([])
    window = LabDashboardWindow()
    window.show()
    return app.exec_()
