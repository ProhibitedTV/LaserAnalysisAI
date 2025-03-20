"""
Frame Viewer module for handling frame navigation, processing, and OCR.
This module manages the display of original and processed frames in the GUI.
"""

import os
import cv2
import cv2.cuda  # Import OpenCV's CUDA module for GPU acceleration
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt, QMetaObject, Q_ARG, QObject, pyqtSlot, QThread, pyqtSignal, QRunnable, QThreadPool
from PyQt5.QtWidgets import QProgressDialog, QApplication
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.common import list_images_in_directory, ensure_directory_exists
from scripts.image_processing import process_image
from gui.ocr_processor import OCRProcessor

class FrameProcessingThread(QThread):
    """
    A QThread for processing frames and performing OCR without blocking the GUI.

    Attributes:
        frames (list): List of frame file paths to process.
        processed_folder (str): Directory to save processed frames.
        ocrProcessor (OCRProcessor): OCRProcessor instance for performing OCR.
        progress (pyqtSignal): Signal to update progress in the GUI.
    """
    progress = pyqtSignal(int)
    finished = pyqtSignal(list, list)  # Emits processed_frames and ocr_texts

    def __init__(self, frames, processed_folder, ocrProcessor):
        super().__init__()
        self.frames = frames
        self.processed_folder = processed_folder
        self.ocrProcessor = ocrProcessor

    def run(self):
        """Processes frames and performs OCR in a separate thread."""
        processed_frames = [None] * len(self.frames)
        ocr_texts = [None] * len(self.frames)

        for index, frame in enumerate(self.frames):
            # Process the frame
            processed_frame = process_image(frame)
            if processed_frame is not None:
                processed_path = frame.replace("frames", "processed_frames")
                ensure_directory_exists(os.path.dirname(processed_path))
                cv2.imwrite(processed_path, processed_frame)
                processed_frames[index] = processed_path

            # Perform OCR
            try:
                ocr_texts[index] = self.ocrProcessor.process_ocr(processed_path, return_text=True)
            except Exception as e:
                ocr_texts[index] = f"OCR Error: {str(e)}"

            # Emit progress
            self.progress.emit(int((index + 1) / len(self.frames) * 100))

        self.finished.emit(processed_frames, ocr_texts)


class FrameViewer(QObject):
    """
    Handles frame navigation, processing, and OCR in the GUI.

    Attributes:
        originalView (QLabel): QLabel for displaying the original frame.
        processedView (QLabel): QLabel for displaying the processed frame.
        ocrProcessor (OCRProcessor): OCRProcessor instance for handling OCR tasks.
    """
    
    def __init__(self, originalView, processedView, ocrProcessor):
        """Initializes the FrameViewer with the given QLabel for displaying frames."""
        super().__init__()  # Initialize QObject
        self.originalView = originalView
        self.processedView = processedView
        self.ocrProcessor = ocrProcessor
        self.frames = []
        self.processed_frames = []
        self.ocr_texts = []
        self.current_frame_index = 0
    
    def load_frames(self, folder_path="data/frames"):
        """
        Loads extracted frames from the specified folder.
        """
        self.frames = list_images_in_directory(folder_path)
        self.processed_frames = [None] * len(self.frames)  # Reset processed frames
        self.ocr_texts = [None] * len(self.frames)  # Reset OCR texts
        self.current_frame_index = 0

    def on_processing_finished(self, processed_frames, ocr_texts):
        """
        Callback for when frame processing and OCR are complete.

        Args:
            processed_frames (list): List of processed frame file paths.
            ocr_texts (list): List of OCR texts for each frame.
        """
        self.processed_frames = processed_frames
        self.ocr_texts = ocr_texts
        self.current_frame_index = 0
        if self.frames:
            self.display_frame()
    
    def process_frame(self, frame_path):
        """
        Processes a single frame using the image processing module.

        Args:
            frame_path (str): Path to the frame image.

        Returns:
            str: Path to the processed frame image.
        """
        processed = process_image(frame_path)
        if processed is not None:
            processed_path = frame_path.replace("frames", "processed_frames")
            ensure_directory_exists(os.path.dirname(processed_path))
            cv2.imwrite(processed_path, processed)
            return processed_path
        return None
    
    def process_ocr(self, frame_path):
        """Processes OCR on a single frame and returns the detected text."""
        try:
            return self.ocrProcessor.process_ocr(frame_path, return_text=True)
        except Exception as e:
            return f"OCR Error: {str(e)}"
    
    @pyqtSlot(int, str)
    def update_processed_frame(self, index, processed_frame):
        """Updates the processed frame in the main thread."""
        self.processed_frames[index] = processed_frame
    
    @pyqtSlot(int, str)
    def update_ocr_text(self, index, ocr_text):
        """Updates the OCR text in the main thread."""
        self.ocr_texts[index] = ocr_text
    
    @pyqtSlot()
    def display_frame(self):
        """Displays the current frame and its processed version in the GUI."""
        if self.frames:
            frame_path = self.frames[self.current_frame_index]
            processed_frame_path = self.processed_frames[self.current_frame_index]
            ocr_text = self.ocr_texts[self.current_frame_index]
            
            self._update_pixmap(self.originalView, frame_path, "Original frame not found.")
            self._update_pixmap(self.processedView, processed_frame_path, "Processed frame not found.")
            
            # Clear OCR text display if no OCR text is available
            QMetaObject.invokeMethod(
                self.ocrProcessor.text_display,
                "setPlainText",
                Qt.QueuedConnection,
                Q_ARG(str, ocr_text if ocr_text else "")
            )
    
    def _update_pixmap(self, label, image_path, error_message):
        """Updates a QLabel with a pixmap or an error message."""
        if image_path and os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            label.setPixmap(pixmap.scaled(350, 350, Qt.KeepAspectRatio))
        else:
            label.setText(error_message)
    
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
            self.display_frame()
            return self.frames[self.current_frame_index], self.processed_frames[self.current_frame_index]
        return None, None  # Always return a tuple, even if the index is invalid

    def process_all_frames(self, progress_callback, finished_callback, processing_mode="Edge Detection"):
        """
        Processes all frames using the specified processing mode and updates progress.

        Args:
            progress_callback (callable): Function to update progress.
            finished_callback (callable): Function to call when processing is complete.
            processing_mode (str): The processing mode to apply ("Edge Detection", "Thresholding", etc.).
        """
        class FrameProcessingWorker(QObject):
            """
            A QObject-based worker for processing frames with signals for progress and completion.

            Attributes:
                progress (pyqtSignal): Signal to update progress in the GUI.
                finished (pyqtSignal): Signal to notify when processing is complete.
            """
            progress = pyqtSignal(int)
            finished = pyqtSignal(list)

            def __init__(self, frames, processed_folder, processing_mode):
                super().__init__()
                self.frames = frames
                self.processed_folder = processed_folder
                self.processing_mode = processing_mode

            def process_frames(self):
                """Processes all frames using the specified processing mode."""
                processed_frames = [None] * len(self.frames)

                for index, frame_path in enumerate(self.frames):
                    try:
                        # Process the frame using the selected mode
                        processed_frame = process_image(frame_path, processing_type=self.processing_mode)
                        if processed_frame is None:
                            print(f"Error processing frame {index}: Unsupported processing mode.")
                            continue

                        # Save the processed frame
                        processed_path = frame_path.replace("frames", "processed_frames")
                        ensure_directory_exists(os.path.dirname(processed_path))
                        cv2.imwrite(processed_path, processed_frame)
                        processed_frames[index] = processed_path

                        # Emit progress
                        self.progress.emit(int((index + 1) / len(self.frames) * 100))
                    except Exception as e:
                        print(f"Error processing frame {index}: {e}")

                self.finished.emit(processed_frames)

        class FrameProcessingRunnable(QRunnable):
            """
            A QRunnable wrapper for running the FrameProcessingWorker in a separate thread.
            """
            def __init__(self, worker):
                super().__init__()
                self.worker = worker

            def run(self):
                """Executes the worker's frame processing logic."""
                self.worker.process_frames()

        # Show progress dialog
        progress = QProgressDialog("Processing frames for edge detection...", "Cancel", 0, 100)
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)

        def update_progress(value):
            progress.setValue(value)

        def on_finished(processed_frames):
            progress.close()
            finished_callback(processed_frames)

        # Create the worker and runnable
        worker = FrameProcessingWorker(self.frames, "data/processed_frames", processing_mode)
        worker.progress.connect(update_progress)
        worker.finished.connect(on_finished)

        runnable = FrameProcessingRunnable(worker)
        QThreadPool.globalInstance().start(runnable)

    def process_all_ocr(self, progress_callback, finished_callback):
        """
        Processes OCR for all processed frames and updates progress.

        Args:
            progress_callback (callable): Function to update progress.
            finished_callback (callable): Function to call when OCR is complete.
        """
        class OCRProcessingWorker(QObject):
            """
            A QObject-based worker for performing OCR with signals for progress and completion.

            Attributes:
                progress (pyqtSignal): Signal to update progress in the GUI.
                finished (pyqtSignal): Signal to notify when OCR is complete.
            """
            progress = pyqtSignal(int)
            finished = pyqtSignal(list)

            def __init__(self, processed_frames, ocr_processor):
                super().__init__()
                self.processed_frames = processed_frames
                self.ocr_processor = ocr_processor

            def process_ocr(self):
                """Processes OCR for all processed frames."""
                ocr_texts = [None] * len(self.processed_frames)

                for index, frame_path in enumerate(self.processed_frames):
                    try:
                        if frame_path:
                            ocr_texts[index] = self.ocr_processor.process_ocr(frame_path, return_text=True)
                        else:
                            ocr_texts[index] = "No processed frame available."
                        
                        # Emit progress
                        self.progress.emit(int((index + 1) / len(self.processed_frames) * 100))
                    except Exception as e:
                        print(f"Error processing OCR for frame {index}: {e}")
                        ocr_texts[index] = f"OCR Error: {str(e)}"

                self.finished.emit(ocr_texts)

        class OCRProcessingRunnable(QRunnable):
            """
            A QRunnable wrapper for running the OCRProcessingWorker in a separate thread.
            """
            def __init__(self, worker):
                super().__init__()
                self.worker = worker

            def run(self):
                """Executes the worker's OCR processing logic."""
                self.worker.process_ocr()

        # Show progress dialog
        progress = QProgressDialog("Processing OCR for frames...", "Cancel", 0, 100)
        progress.setWindowModality(Qt.WindowModal)
        progress.setValue(0)

        def update_progress(value):
            progress.setValue(value)

        def on_finished(ocr_texts):
            progress.close()
            finished_callback(ocr_texts)

        # Create the worker and runnable
        worker = OCRProcessingWorker(self.processed_frames, self.ocrProcessor)
        worker.progress.connect(update_progress)
        worker.finished.connect(on_finished)

        runnable = OCRProcessingRunnable(worker)
        QThreadPool.globalInstance().start(runnable)

    def on_processing_finished(self, processed_frames):
        """
        Callback for when frame processing is complete.

        Args:
            processed_frames (list): List of processed frame file paths.
        """
        self.processed_frames = processed_frames
        self.current_frame_index = 0
        if self.frames:
            self.display_frame()

    def on_ocr_finished(self, ocr_texts):
        """
        Callback for when OCR processing is complete.

        Args:
            ocr_texts (list): List of OCR results for each frame.
        """
        self.ocr_texts = ocr_texts
        self.current_frame_index = 0
        if self.frames:
            self.display_frame()
