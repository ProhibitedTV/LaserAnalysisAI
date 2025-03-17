import cv2
import pytesseract
import numpy as np
import os
from scripts.frame_extraction import extract_frames

# Set the Tesseract OCR path for Windows users
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def preprocess_image(image_path):
    """Preprocess the image to enhance OCR accuracy."""
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"Error: Image not found! {image_path}")
        return None
    
    # Noise reduction and contrast enhancement
    img = cv2.bilateralFilter(img, 9, 75, 75)  # Preserve edges while reducing noise
    img = cv2.equalizeHist(img)  # Improve contrast
    
    # Adaptive thresholding to improve text recognition
    img = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    
    # Morphological operations to enhance text clarity
    kernel = np.ones((2,2), np.uint8)
    img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, kernel)
    img = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel)
    
    return img

def detect_characters(image_path, ocr_mode="--oem 3 --psm 6"):
    """Detects potential characters in a given image using OCR."""
    processed = preprocess_image(image_path)
    if processed is None:
        return None
    
    # Use Tesseract OCR to detect text
    detected_text = pytesseract.image_to_string(processed, config=ocr_mode)
    
    print(f"Detected Text in {image_path}:")
    print(detected_text)
    
    return detected_text

def detect_characters_in_folder(folder_path="data/frames", ocr_mode="--oem 3 --psm 6"):
    """Processes all images in the frames folder for character detection."""
    if not os.path.exists(folder_path):
        print(f"Error: Folder not found! {folder_path}")
        return
    
    image_files = [f for f in sorted(os.listdir(folder_path)) if f.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff"))]
    
    if not image_files:
        print("No images found in the folder. Extracting frames first...")
        video_path = "data/sample_video.mp4"  # Modify this to dynamically select a video
        extract_frames(video_path, folder_path)
        image_files = [f for f in sorted(os.listdir(folder_path)) if f.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff"))]
        if not image_files:
            print("Frame extraction failed or no frames extracted.")
            return
    
    results = {}
    for filename in image_files:
        image_path = os.path.join(folder_path, filename)
        text = detect_characters(image_path, ocr_mode)
        results[filename] = text
    
    return results

if __name__ == "__main__":
    detect_characters_in_folder()