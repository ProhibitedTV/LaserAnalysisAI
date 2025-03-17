import os
import cv2
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QProgressDialog
from utils.common import list_images_in_directory, ensure_directory_exists
from scripts.image_processing import process_image
from gui.ocr_processor import OCRProcessor

class FrameViewer:
    """Handles frame navigation and display in the GUI."""
    
    def __init__(self, originalView, processedView, ocrProcessor):
        """Initializes the FrameViewer with the given QLabel for displaying frames."""
        self.originalView = originalView
        self.processedView = processedView
        self.ocrProcessor = ocrProcessor
        self.frames = []
        self.processed_frames = []
        self.ocr_texts = []
        self.current_frame_index = 0
    
    def load_frames(self, folder_path="data/frames"):
        """Loads extracted frames from the specified folder and processes them."""
        self.frames = list_images_in_directory(folder_path)
        
        # Show progress dialog
        progress = QProgressDialog("Processing frames...", "Cancel", 0, len(self.frames))
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)
        
        self.processed_frames = []
        self.ocr_texts = []
        
        for i, frame in enumerate(self.frames):
            self.processed_frames.append(self.process_frame(frame))
            self.ocr_texts.append(self.process_ocr(self.processed_frames[-1]))
            progress.setValue(i + 1)
        
        self.current_frame_index = 0
        if self.frames:
            self.display_frame()
    
    def process_frame(self, frame_path):
        """Processes a single frame and returns the path to the processed frame."""
        processed = process_image(frame_path)
        if processed is not None:
            processed_path = frame_path.replace("frames", "processed_frames")
            ensure_directory_exists(os.path.dirname(processed_path))
            cv2.imwrite(processed_path, processed)
            return processed_path
        return None
    
    def process_ocr(self, frame_path):
        """Processes OCR on a single frame and returns the detected text."""
        return self.ocrProcessor.process_ocr(frame_path, return_text=True)
    
    def display_frame(self):
        """Displays the current frame and its processed version in the GUI."""
        if self.frames:
            frame_path = self.frames[self.current_frame_index]
            processed_frame_path = self.processed_frames[self.current_frame_index]
            ocr_text = self.ocr_texts[self.current_frame_index]
            
            original_pixmap = QPixmap(frame_path)
            processed_pixmap = QPixmap(processed_frame_path)
            
            self.originalView.setPixmap(original_pixmap.scaled(350, 350, Qt.KeepAspectRatio))
            self.processedView.setPixmap(processed_pixmap.scaled(350, 350, Qt.KeepAspectRatio))
            self.ocrProcessor.text_display.setPlainText(ocr_text)
            
            return frame_path, processed_frame_path
        return None, None
    
    def next_frame(self):
        """Moves to the next frame if available."""
        if self.frames and self.current_frame_index < len(self.frames) - 1:
            self.current_frame_index += 1
            return self.display_frame()
        return None, None
    
    def prev_frame(self):
        """Moves to the previous frame if available."""
        if self.frames and self.current_frame_index > 0:
            self.current_frame_index -= 1
            return self.display_frame()
        return None, None
    
    def set_frame(self, index):
        """Sets the frame index and displays the corresponding frame."""
        if 0 <= index < len(self.frames):
            self.current_frame_index = index
            return self.display_frame()
        return None, None
