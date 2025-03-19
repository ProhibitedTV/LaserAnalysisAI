"""
Video Loader module for handling video selection and frame extraction.
This module provides functionality to load videos and extract frames with progress updates.
"""

from PyQt5.QtWidgets import QFileDialog, QProgressDialog
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from scripts.frame_extraction import extract_frames
from utils.common import ensure_directory_exists
import os

class FrameExtractionThread(QThread):
    """
    A QThread for extracting frames from a video without blocking the GUI.

    Attributes:
        video_path (str): Path to the video file.
        output_folder (str): Directory to save the extracted frames.
        frame_interval (int): Interval between frames to save.
        progress (pyqtSignal): Signal to update progress in the GUI.
    """
    progress = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, video_path, output_folder, frame_interval=5):
        super().__init__()
        self.video_path = video_path
        self.output_folder = output_folder
        self.frame_interval = frame_interval

    def run(self):
        """Runs the frame extraction process in a separate thread."""
        extract_frames(
            self.video_path,
            self.output_folder,
            self.frame_interval,
            progress_callback=self.progress.emit
        )
        self.finished.emit()


class VideoLoader:
    """
    Handles video loading and frame extraction.

    Attributes:
        videoPath (str): Path to the loaded video file.
    """
    
    def __init__(self):
        """Initializes the VideoLoader with default values."""
        self.videoPath = None
        self.thread = None
    
    def load_video(self, parent):
        """
        Handles video selection and frame extraction.

        Args:
            parent (QWidget): The parent widget for dialogs and progress updates.

        Returns:
            str: Path to the loaded video file, or None if no video was selected.
        """
        options = QFileDialog.Options()
        filePath, _ = QFileDialog.getOpenFileName(parent, "Load Video", "", "Videos (*.mp4 *.avi *.mov *.mkv)", options=options)
        if filePath:
            self.videoPath = filePath
            print(f"Loaded Video: {self.videoPath}")
            
            # Ensure the frames directory exists
            ensure_directory_exists("data/frames")
            
            # Show progress dialog
            progress = QProgressDialog("Extracting frames...", "Cancel", 0, 100, parent)
            progress.setWindowModality(Qt.WindowModal)
            progress.setValue(0)

            # Create and start the frame extraction thread
            self.thread = FrameExtractionThread(self.videoPath, "data/frames")
            self.thread.progress.connect(progress.setValue)
            self.thread.finished.connect(progress.close)
            self.thread.start()

            return self.videoPath
        return None
