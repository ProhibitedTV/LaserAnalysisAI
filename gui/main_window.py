import sys
import cv2
import numpy as np
import pytesseract
from PyQt5.QtWidgets import (
    QApplication, QLabel, QPushButton, QFileDialog, QVBoxLayout, QWidget,
    QHBoxLayout, QSlider, QMenuBar, QMainWindow, QAction, QTextEdit, QCheckBox,
    QSpacerItem, QSizePolicy, QStatusBar, QComboBox
)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt
from gui.frame_viewer import FrameViewer
from gui.ocr_processor import OCRProcessor
from gui.video_loader import VideoLoader
from scripts.image_processing import process_image
from utils.common import ensure_directory_exists
import os

class MainWindow(QMainWindow):
    """Main application window for Laser Projection Analysis."""
    
    def __init__(self):
        """Initializes the main window and its components."""
        super().__init__()
        self.initUI()
    
    def initUI(self):
        """Sets up the user interface components."""
        self.setWindowTitle("Laser Projection Analysis")
        self.setGeometry(100, 100, 1000, 600)
        
        # Apply custom stylesheet for modern look
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2e2e2e;
                color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QPushButton {
                background-color: #4a4a4a;
                color: #ffffff;
                border: 1px solid #5a5a5a;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QSlider::groove:horizontal {
                border: 1px solid #5a5a5a;
                height: 8px;
                background: #4a4a4a;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                border: 1px solid #5a5a5a;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
            QTextEdit {
                background-color: #4a4a4a;
                color: #ffffff;
                border: 1px solid #5a5a5a;
            }
            QCheckBox {
                color: #ffffff;
            }
            QComboBox {
                background-color: #4a4a4a;
                color: #ffffff;
                border: 1px solid #5a5a5a;
            }
            QMenuBar {
                background-color: #4a4a4a;
                color: #ffffff;
            }
            QMenuBar::item {
                background: #4a4a4a;
                color: #ffffff;
            }
            QMenuBar::item:selected {
                background: #5a5a5a;
            }
            QStatusBar {
                background-color: #4a4a4a;
                color: #ffffff;
            }
        """)
        
        # Menu Bar
        menubar = self.menuBar()
        fileMenu = menubar.addMenu("File")
        
        loadImageAction = QAction("Load Image", self)
        loadImageAction.triggered.connect(self.loadImage)
        fileMenu.addAction(loadImageAction)
        
        loadVideoAction = QAction("Load Video", self)
        loadVideoAction.triggered.connect(self.loadVideo)
        fileMenu.addAction(loadVideoAction)
        
        exitAction = QAction("Exit", self)
        exitAction.triggered.connect(self.close)
        fileMenu.addAction(exitAction)
        
        # Left Side - Video & Frame Navigation
        self.loadVideoButton = QPushButton("Load Video")
        self.loadVideoButton.clicked.connect(self.loadVideo)
        
        self.prevFrameButton = QPushButton("Previous Frame")
        self.prevFrameButton.clicked.connect(self.prevFrame)
        
        self.nextFrameButton = QPushButton("Next Frame")
        self.nextFrameButton.clicked.connect(self.nextFrame)
        
        self.frameSlider = QSlider(Qt.Horizontal)
        self.frameSlider.setMinimum(0)
        self.frameSlider.valueChanged.connect(self.setFrame)
        
        # Center - Image Processing & Display
        self.processButton = QPushButton("Process Image")
        self.processButton.clicked.connect(self.processImage)
        
        self.showAnalysisCheckbox = QCheckBox("Show Image Analysis")
        
        self.reprocessButton = QPushButton("Reprocess Image")
        self.reprocessButton.clicked.connect(self.processImage)
        
        self.processingTypeComboBox = QComboBox()
        self.processingTypeComboBox.addItems(["Edge Detection", "Thresholding", "Morphological Operations"])
        
        self.originalView = QLabel(self)
        self.originalView.setAlignment(Qt.AlignCenter)
        self.processedView = QLabel(self)
        self.processedView.setAlignment(Qt.AlignCenter)
        
        # Right Side - OCR Tools
        self.detectTextButton = QPushButton("Detect Characters")
        self.detectTextButton.clicked.connect(self.detectCharacters)
        
        self.ocrTextBox = QTextEdit(self)
        self.ocrTextBox.setReadOnly(True)
        self.ocrTextBox.setPlaceholderText("Detected text will appear here...")
        
        self.saveTextButton = QPushButton("Save OCR Text")
        self.saveTextButton.clicked.connect(self.saveOCRText)
        
        # Layout
        leftLayout = QVBoxLayout()
        leftLayout.addWidget(self.loadVideoButton)
        leftLayout.addWidget(self.originalView)
        
        sliderLayout = QHBoxLayout()
        sliderLayout.addWidget(self.prevFrameButton)
        sliderLayout.addWidget(self.frameSlider)
        sliderLayout.addWidget(self.nextFrameButton)
        
        leftLayout.addLayout(sliderLayout)
        leftLayout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        
        centerLayout = QVBoxLayout()
        centerLayout.addWidget(self.processButton)
        centerLayout.addWidget(self.showAnalysisCheckbox)
        centerLayout.addWidget(self.reprocessButton)
        centerLayout.addWidget(self.processingTypeComboBox)
        centerLayout.addWidget(self.processedView)
        centerLayout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        
        rightLayout = QVBoxLayout()
        rightLayout.addWidget(self.detectTextButton)
        rightLayout.addWidget(self.ocrTextBox)
        rightLayout.addWidget(self.saveTextButton)
        rightLayout.addSpacerItem(QSpacerItem(20, 40, QSizePolicy.Minimum, QSizePolicy.Expanding))
        
        mainLayout = QHBoxLayout()
        mainLayout.addLayout(leftLayout)
        mainLayout.addLayout(centerLayout)
        mainLayout.addLayout(rightLayout)
        
        centralWidget = QWidget()
        centralWidget.setLayout(mainLayout)
        self.setCentralWidget(centralWidget)
        
        # Status Bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        
        self.imagePath = None
        self.videoLoader = VideoLoader()
        self.ocrProcessor = OCRProcessor(self.ocrTextBox)
        self.frameViewer = FrameViewer(self.originalView, self.processedView, self.ocrProcessor)
    
    def loadImage(self):
        """Handles image selection and display."""
        options = QFileDialog.Options()
        filePath, _ = QFileDialog.getOpenFileName(self, "Load Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.tiff)", options=options)
        if filePath:
            self.imagePath = filePath
            pixmap = QPixmap(filePath)
            self.originalView.setPixmap(pixmap.scaled(350, 350, Qt.KeepAspectRatio))
            self.statusBar.showMessage(f"Loaded Image: {filePath}")
    
    def loadVideo(self):
        """Handles video loading and frame extraction."""
        filePath = self.videoLoader.load_video()
        if filePath:
            self.frameViewer.load_frames("data/frames")
            self.frameSlider.setMaximum(len(self.frameViewer.frames) - 1)
            self.statusBar.showMessage(f"Loaded Video: {filePath}")
    
    def setFrame(self, value):
        """Sets the current frame to be displayed."""
        self.imagePath, _ = self.frameViewer.set_frame(value)
        self.statusBar.showMessage(f"Displaying Frame: {self.imagePath}")
    
    def prevFrame(self):
        """Moves to the previous frame."""
        if self.frameSlider.value() > 0:
            self.frameSlider.setValue(self.frameSlider.value() - 1)
    
    def nextFrame(self):
        """Moves to the next frame."""
        if self.frameSlider.value() < self.frameSlider.maximum():
            self.frameSlider.setValue(self.frameSlider.value() + 1)
    
    def processImage(self):
        """Processes the current image for analysis."""
        if not self.imagePath:
            self.statusBar.showMessage("No image loaded to process.")
            return
        
        processing_type = self.processingTypeComboBox.currentText()
        show_analysis = self.showAnalysisCheckbox.isChecked()
        processed = process_image(self.imagePath, show_analysis, processing_type)
        
        if processed is not None:
            height, width = processed.shape
            bytesPerLine = width
            qImg = QImage(processed.data, width, height, bytesPerLine, QImage.Format_Grayscale8)
            self.processedView.setPixmap(QPixmap.fromImage(qImg).scaled(350, 350, Qt.KeepAspectRatio))
            self.statusBar.showMessage("Image processing completed.")
    
    def detectCharacters(self):
        """Detects characters in the current image using OCR."""
        self.ocrProcessor.process_ocr(self.imagePath)
        self.statusBar.showMessage("OCR processing completed.")
    
    def saveOCRText(self):
        """Saves the detected OCR text to a file."""
        text = self.ocrTextBox.toPlainText()
        if text:
            filePath, _ = QFileDialog.getSaveFileName(self, "Save OCR Text", "ocr_output.txt", "Text Files (*.txt)")
            if filePath:
                with open(filePath, 'w', encoding='utf-8') as file:
                    file.write(text)
                self.statusBar.showMessage(f"OCR text saved to: {filePath}")
