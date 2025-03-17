from PyQt5.QtWidgets import QFileDialog, QProgressDialog
from PyQt5.QtCore import Qt
from scripts.frame_extraction import extract_frames
from utils.common import ensure_directory_exists
import os

class VideoLoader:
    """Handles video loading and frame extraction."""
    
    def __init__(self):
        """Initializes the VideoLoader with default values."""
        self.videoPath = None
    
    def load_video(self):
        """Handles video selection and frame extraction."""
        options = QFileDialog.Options()
        filePath, _ = QFileDialog.getOpenFileName(None, "Load Video", "", "Videos (*.mp4 *.avi *.mov *.mkv)", options=options)
        if filePath:
            self.videoPath = filePath
            print(f"Loaded Video: {self.videoPath}")
            
            # Ensure the frames directory exists
            ensure_directory_exists("data/frames")
            
            # Show progress dialog
            progress = QProgressDialog("Extracting frames...", "Cancel", 0, 100)
            progress.setWindowModality(Qt.WindowModal)
            progress.setValue(0)
            
            # Extract frames immediately after selecting a video
            extract_frames(self.videoPath, "data/frames", progress_callback=progress.setValue)
            print("Frame extraction completed.")
        return self.videoPath
