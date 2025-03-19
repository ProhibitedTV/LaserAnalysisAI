"""
OCR Processor module for handling Optical Character Recognition (OCR) tasks.
This module preprocesses images, applies OCR using Tesseract, and updates the GUI with results.
"""

from utils.common import load_grayscale_image, preprocess_for_ocr, enhance_contrast, apply_morphological_operations
from PyQt5.QtWidgets import QTextEdit
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QObject, QMetaObject, Q_ARG, Qt, pyqtSlot
from concurrent.futures import ThreadPoolExecutor
import pytesseract
import cv2

class OCRProcessor(QObject):
    """
    Handles Optical Character Recognition (OCR) on images.

    Attributes:
        text_display (QTextEdit): The GUI text box where detected text will be displayed.
        enhance_text (bool): If True, applies additional image enhancements.
    """

    def __init__(self, text_display: QTextEdit, enhance_text: bool = False):
        """
        Initializes the OCR Processor.

        Args:
            text_display (QTextEdit): The widget where detected text is displayed.
            enhance_text (bool, optional): Whether to apply extra text enhancement techniques. Defaults to False.
        """
        super().__init__()  # Initialize QObject
        self.text_display = text_display
        self.enhance_text = enhance_text  # Toggle for additional image enhancements

        # Set the Tesseract executable path
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    
    def set_tesseract_path(self, path: str):
        """
        Sets the Tesseract executable path.

        Args:
            path (str): The file path to the Tesseract executable.
        """
        pytesseract.pytesseract.tesseract_cmd = path
        print(f"Tesseract path updated to: {path}")

    def process_ocr(self, image_path: str, return_text: bool = False, display_widget=None) -> str:
        """
        Runs OCR on the provided image with preprocessing and updates the text display.

        Args:
            image_path (str): The file path of the image to analyze.
            return_text (bool, optional): Whether to return the detected text. Defaults to False.
            display_widget (QLabel, optional): The widget to display the image with bounding boxes.

        Returns:
            str: The detected text if return_text is True, otherwise None.
        """
        if not image_path:
            QMetaObject.invokeMethod(
                self, "update_text_display", Qt.QueuedConnection, Q_ARG(str, "Error: No image selected.")
            )
            return ""

        # Load the image in grayscale mode
        img = load_grayscale_image(image_path)
        if img is None:
            QMetaObject.invokeMethod(
                self, "update_text_display", Qt.QueuedConnection, Q_ARG(str, "Error: Image not found.")
            )
            return ""

        # Apply standard OCR preprocessing
        preprocessed_img = preprocess_for_ocr(img)

        # Apply additional enhancements if enabled
        if self.enhance_text:
            preprocessed_img = enhance_contrast(preprocessed_img)
            preprocessed_img = apply_morphological_operations(preprocessed_img)

        # Convert the processed image to binary format before OCR
        _, binary_img = cv2.threshold(preprocessed_img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Run OCR on the preprocessed image with all language options
        custom_config = r'--oem 3 --psm 6 -l eng+fra+spa+deu+ita+por+rus+jpn+chi_sim+chi_tra'
        try:
            ocr_data = pytesseract.image_to_data(binary_img, config=custom_config, output_type=pytesseract.Output.DICT)
            detected_text = pytesseract.image_to_string(binary_img, config=custom_config).strip()
        except pytesseract.TesseractNotFoundError:
            QMetaObject.invokeMethod(
                self, "update_text_display", Qt.QueuedConnection, Q_ARG(str, "Error: Tesseract is not installed or not in PATH.")
            )
            return ""
        except pytesseract.TesseractError as e:
            QMetaObject.invokeMethod(
                self, "update_text_display", Qt.QueuedConnection, Q_ARG(str, f"OCR Error: {str(e)}")
            )
            return ""

        # Calculate average confidence
        confidences = [int(conf) for conf in ocr_data['conf'] if conf != '-1']
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        # Extract detailed word-level information and draw bounding boxes
        word_details = []
        img_with_boxes = cv2.cvtColor(binary_img, cv2.COLOR_GRAY2BGR)
        for i in range(len(ocr_data['text'])):
            if ocr_data['text'][i].strip():
                word_details.append(
                    f"Word: '{ocr_data['text'][i]}', Confidence: {ocr_data['conf'][i]}%, "
                    f"Bounding Box: (x: {ocr_data['left'][i]}, y: {ocr_data['top'][i]}, "
                    f"w: {ocr_data['width'][i]}, h: {ocr_data['height'][i]})"
                )
                # Draw bounding box on the image
                x, y, w, h = ocr_data['left'][i], ocr_data['top'][i], ocr_data['width'][i], ocr_data['height'][i]
                cv2.rectangle(img_with_boxes, (x, y), (x + w, y + h), (0, 255, 0), 2)

        # Combine results into a detailed output
        result_text = (
            f"Detected Text:\n{detected_text}\n\n"
            f"Average Confidence: {avg_confidence:.2f}%\n\n"
            f"Word Details:\n" + "\n".join(word_details)
        )

        # Update the GUI with the detected text
        QMetaObject.invokeMethod(
            self, "update_text_display", Qt.QueuedConnection, Q_ARG(str, result_text)
        )

        # Display the image with bounding boxes in the provided widget
        if display_widget:
            height, width, channel = img_with_boxes.shape
            bytes_per_line = 3 * width
            q_img = QImage(img_with_boxes.data, width, height, bytes_per_line, QImage.Format_RGB888)
            QMetaObject.invokeMethod(
                self, "update_display_widget", Qt.QueuedConnection, Q_ARG(QPixmap, QPixmap.fromImage(q_img))
            )

        return detected_text if return_text else result_text

    @pyqtSlot(str)
    def update_text_display(self, text):
        """Updates the text display in the main thread."""
        self.text_display.setPlainText(text)  # Ensure this works with QTextEdit

    @pyqtSlot(QPixmap)
    def update_display_widget(self, pixmap):
        """Updates the display widget with a pixmap in the main thread."""
        self.text_display.setPixmap(pixmap)

    def process_ocr_batch(self, image_paths, progress_callback=None):
        """
        Processes OCR on a batch of images using multi-threading.

        Args:
            image_paths (list): List of image file paths to process.
            progress_callback (callable, optional): Function to update progress.

        Returns:
            list: List of detected texts for each image.
        """
        results = [None] * len(image_paths)

        def process_single(index, image_path):
            results[index] = self.process_ocr(image_path, return_text=True)
            if progress_callback:
                progress_callback(index + 1)

        with ThreadPoolExecutor() as executor:
            for i, image_path in enumerate(image_paths):
                executor.submit(process_single, i, image_path)

        return results
