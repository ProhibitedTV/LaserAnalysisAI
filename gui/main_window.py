import sys
from PyQt5.QtWidgets import (
    QApplication, QLabel, QPushButton, QFileDialog, QVBoxLayout, QWidget,
    QHBoxLayout, QMenuBar, QMainWindow, QAction, QProgressDialog, QStatusBar, QTextEdit, QSlider, QComboBox
)
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
from gui.frame_viewer import FrameViewer
from gui.ocr_processor import OCRProcessor
from gui.video_loader import VideoLoader
from utils.common import ensure_directory_exists
import os

"""
Main Window module for the Laser Projection Analysis application.
This module defines the main GUI layout and handles user interactions.
"""

class MainWindow(QMainWindow):
    """
    Main application window for Laser Projection Analysis.

    Attributes:
        videoLoader (VideoLoader): VideoLoader instance for handling video loading.
        ocrProcessor (OCRProcessor): OCRProcessor instance for handling OCR tasks.
        frameViewer (FrameViewer): FrameViewer instance for managing frames.
    """
    
    def __init__(self):
        """Initializes the main window and its components."""
        super().__init__()
        self.initUI()
    
    def initUI(self):
        """Sets up the user interface components."""
        self.setWindowTitle("Laser Projection Analysis")
        self.setGeometry(100, 100, 800, 600)
        
        # Menu Bar
        menubar = self.menuBar()
        fileMenu = menubar.addMenu("File")
        
        setTesseractPathAction = QAction("Set Tesseract Path", self)
        setTesseractPathAction.triggered.connect(self.setTesseractPath)
        fileMenu.addAction(setTesseractPathAction)
        
        exitAction = QAction("Exit", self)
        exitAction.triggered.connect(self.close)
        fileMenu.addAction(exitAction)
        
        # Buttons for each stage
        self.loadVideoButton = QPushButton("Load Video and Extract Frames")
        self.loadVideoButton.clicked.connect(self.loadVideo)
        
        self.processFramesButton = QPushButton("Process Frames (Edge Detection)")
        self.processFramesButton.clicked.connect(self.processFrames)
        self.processFramesButton.setEnabled(False)  # Disabled until frames are extracted
        
        self.processOCRButton = QPushButton("Process OCR")
        self.processOCRButton.clicked.connect(self.processOCR)
        self.processOCRButton.setEnabled(False)  # Disabled until frames are processed
        
        # Dropdown for selecting processing mode
        self.processingModeDropdown = QComboBox(self)
        self.processingModeDropdown.addItems([
            "Edge Detection",
            "Thresholding",
            "Morphological Operations",
            "Adaptive Thresholding",
            "Gaussian Blur",
            "Sharpening",
            "Histogram Equalization",
            "Median Blur",
            "Bilateral Filter"
        ])
        self.processingModeDropdown.currentIndexChanged.connect(self.update_help_text)

        # Help text box for explaining processing modes
        self.processingHelpText = QLabel(self)
        self.processingHelpText.setWordWrap(True)
        self.processingHelpText.setStyleSheet("font-size: 12px; color: gray;")
        self.processingHelpText.setText("Select a processing mode to see its description.")

        # Views for displaying frames
        self.originalView = QLabel(self)
        self.originalView.setAlignment(Qt.AlignCenter)
        self.originalView.setText("Original Frame")
        
        self.processedView = QLabel(self)
        self.processedView.setAlignment(Qt.AlignCenter)
        self.processedView.setText("Processed Frame")
        
        # Text box for OCR results
        self.ocrTextBox = QTextEdit(self)
        self.ocrTextBox.setReadOnly(True)
        self.ocrTextBox.setPlaceholderText("OCR results will appear here...")

        # Frame navigation controls
        self.prevFrameButton = QPushButton("Previous Frame")
        self.prevFrameButton.clicked.connect(self.prevFrame)
        self.prevFrameButton.setEnabled(False)

        self.nextFrameButton = QPushButton("Next Frame")
        self.nextFrameButton.clicked.connect(self.nextFrame)
        self.nextFrameButton.setEnabled(False)

        self.frameSlider = QSlider(Qt.Horizontal)
        self.frameSlider.setMinimum(0)
        self.frameSlider.setEnabled(False)
        self.frameSlider.valueChanged.connect(self.setFrame)

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.loadVideoButton)
        layout.addWidget(self.processingModeDropdown)  # Add dropdown below the first button
        layout.addWidget(self.processingHelpText)  # Add help text below the dropdown
        layout.addWidget(self.processFramesButton)
        layout.addWidget(self.processOCRButton)
        
        frameLayout = QHBoxLayout()
        frameLayout.addWidget(self.originalView)
        frameLayout.addWidget(self.processedView)
        layout.addLayout(frameLayout)

        navigationLayout = QHBoxLayout()
        navigationLayout.addWidget(self.prevFrameButton)
        navigationLayout.addWidget(self.frameSlider)
        navigationLayout.addWidget(self.nextFrameButton)
        layout.addLayout(navigationLayout)
        
        layout.addWidget(self.ocrTextBox)  # Add OCR text box to the layout
        
        centralWidget = QWidget()
        centralWidget.setLayout(layout)
        self.setCentralWidget(centralWidget)
        
        # Status Bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        
        # Initialize components
        self.videoLoader = VideoLoader()
        self.ocrProcessor = OCRProcessor(self.ocrTextBox)  # Pass QTextEdit to OCRProcessor
        self.frameViewer = FrameViewer(self.originalView, self.processedView, self.ocrProcessor)
    
    def loadVideo(self):
        """Handles video loading and frame extraction."""
        filePath = self.videoLoader.load_video(self)
        if filePath:
            self.videoLoader.thread.finished.connect(self.onFramesExtracted)
            self.statusBar.showMessage(f"Loaded Video: {filePath}")

    def onFramesExtracted(self):
        """Callback for when frame extraction is complete."""
        self.frameViewer.load_frames("data/frames")
        self.statusBar.showMessage("Frame extraction completed.")
        self.processFramesButton.setEnabled(True)

        # Enable frame navigation controls
        self.frameSlider.setMaximum(len(self.frameViewer.frames) - 1)
        self.frameSlider.setEnabled(True)
        self.prevFrameButton.setEnabled(True)
        self.nextFrameButton.setEnabled(True)

        # Display the first frame
        if self.frameViewer.frames:
            self.frameViewer.set_frame(0)

    def setFrame(self, value):
        """Sets the current frame to be displayed."""
        self.frameViewer.set_frame(value)

    def prevFrame(self):
        """Moves to the previous frame."""
        if self.frameSlider.value() > 0:
            self.frameSlider.setValue(self.frameSlider.value() - 1)

    def nextFrame(self):
        """Moves to the next frame."""
        if self.frameSlider.value() < self.frameSlider.maximum():
            self.frameSlider.setValue(self.frameSlider.value() + 1)

    def processFrames(self):
        """Processes all extracted frames based on the selected processing mode."""
        selected_mode = self.processingModeDropdown.currentText()  # Get the selected processing mode

        def update_progress(value):
            self.statusBar.showMessage(f"Processing frames ({selected_mode})... {value}%")

        def on_finished(processed_frames):
            self.frameViewer.processed_frames = processed_frames
            self.statusBar.showMessage(f"Frame processing ({selected_mode}) completed.")
            self.processOCRButton.setEnabled(True)

            # Display the first processed frame alongside the original
            if self.frameViewer.frames:
                self.frameViewer.set_frame(0)

        self.frameViewer.process_all_frames(update_progress, on_finished, processing_mode=selected_mode)

    def processOCR(self):
        """Processes OCR for all processed frames and shows a progress dialog."""
        def update_progress(value):
            self.statusBar.showMessage(f"Processing OCR... {value}%")

        def on_finished(ocr_texts):
            self.frameViewer.ocr_texts = ocr_texts
            self.statusBar.showMessage("OCR processing completed.")

            # Display the first processed frame with OCR results
            if self.frameViewer.frames:
                self.frameViewer.set_frame(0)

        # Ensure we are targeting the processed frames
        self.frameViewer.process_all_ocr(update_progress, on_finished)

    def setTesseractPath(self):
        """Allows the user to set the Tesseract executable path."""
        options = QFileDialog.Options()
        filePath, _ = QFileDialog.getOpenFileName(self, "Set Tesseract Path", "", "Executables (*.exe)", options=options)
        if filePath:
            self.ocrProcessor.set_tesseract_path(filePath)
            self.statusBar.showMessage(f"Tesseract path set to: {filePath}")

    def update_help_text(self):
        """Updates the help text based on the selected processing mode."""
        selected_mode = self.processingModeDropdown.currentText()
        help_texts = {
            "Edge Detection": "Highlights the edges in the image by detecting areas with rapid intensity changes.",
            "Thresholding": "Converts the image to black and white based on a pixel intensity threshold.",
            "Morphological Operations": "Applies transformations like dilation and erosion to refine shapes in the image.",
            "Adaptive Thresholding": "Applies a threshold dynamically based on the local pixel neighborhood.",
            "Gaussian Blur": "Smoothens the image by reducing noise and detail using a Gaussian filter.",
            "Sharpening": "Enhances the edges and fine details in the image.",
            "Histogram Equalization": "Improves contrast by redistributing pixel intensity values.",
            "Median Blur": "Reduces noise while preserving edges by replacing each pixel with the median of its neighbors.",
            "Bilateral Filter": "Smoothens the image while preserving edges by considering both spatial and intensity differences."
        }
        self.processingHelpText.setText(help_texts.get(selected_mode, "Select a processing mode to see its description."))
