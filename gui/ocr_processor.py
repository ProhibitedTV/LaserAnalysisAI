from utils.common import load_grayscale_image, preprocess_for_ocr, enhance_contrast, apply_morphological_operations
from PyQt5.QtWidgets import QTextEdit
import pytesseract
import cv2

class OCRProcessor:
    """
    Handles Optical Character Recognition (OCR) on images.

    This class loads an image, preprocesses it, applies optional enhancements, 
    and extracts text using Tesseract OCR.

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
        self.text_display = text_display
        self.enhance_text = enhance_text  # Toggle for additional image enhancements
    
    def process_ocr(self, image_path: str, return_text: bool = False) -> str:
        """
        Runs OCR on the provided image with preprocessing and updates the text display.

        Args:
            image_path (str): The file path of the image to analyze.
            return_text (bool, optional): Whether to return the detected text. Defaults to False.

        Returns:
            str: The detected text if return_text is True, otherwise None.
        """
        if not image_path:
            self.text_display.setPlainText("Error: No image selected.")
            return ""

        # Load the image in grayscale mode
        img = load_grayscale_image(image_path)
        if img is None:
            self.text_display.setPlainText("Error: Image not found.")
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
        except pytesseract.TesseractError as e:
            self.text_display.setPlainText(f"OCR Error: {str(e)}")
            return ""

        # Calculate average confidence
        confidences = [int(conf) for conf in ocr_data['conf'] if conf != '-1']
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        # Display detected text and confidence in the GUI
        if not return_text:
            result_text = f"Detected Text:\n{detected_text}\n\nAverage Confidence: {avg_confidence:.2f}%"
            self.text_display.setPlainText(result_text)
        
        return detected_text if return_text else result_text
