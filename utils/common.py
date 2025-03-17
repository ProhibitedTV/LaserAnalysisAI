import os
import cv2
import numpy as np

# ===========================
# File & Directory Handling
# ===========================

def ensure_directory_exists(directory):
    """Ensures that the specified directory exists, creating it if necessary."""
    if not os.path.exists(directory):
        os.makedirs(directory)

def list_images_in_directory(directory):
    """Returns a sorted list of image file paths in a given directory."""
    return sorted([os.path.join(directory, f) for f in os.listdir(directory) if f.endswith((".png", ".jpg", ".jpeg", ".bmp", ".tiff"))])

# ===========================
# Image Preprocessing (For OCR & Analysis)
# ===========================

def load_grayscale_image(image_path):
    """Loads an image in grayscale mode."""
    return cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)

def preprocess_for_ocr(image):
    """Applies preprocessing steps to prepare an image for OCR."""
    blurred = cv2.GaussianBlur(image, (5, 5), 0)
    _, binary_img = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary_img

# ===========================
# Frame Processing Helpers
# ===========================

def get_batch_frames(frames, current_index, num_frames=10):
    """Returns a batch of frames (±num_frames) around the current frame index."""
    start = max(0, current_index - num_frames)
    end = min(len(frames), current_index + num_frames + 1)
    return frames[start:end]

def load_frame_from_index(frames, index):
    """Safely loads a frame from the list, ensuring the index is valid."""
    if 0 <= index < len(frames):
        return frames[index]
    return None

# ===========================
# Image Enhancement (Optional)
# ===========================

def enhance_contrast(image):
    """Enhances contrast using histogram equalization."""
    return cv2.equalizeHist(image)

def apply_morphological_operations(image):
    """Applies morphological transformations to refine text detection."""
    kernel = np.ones((3, 3), np.uint8)
    return cv2.morphologyEx(image, cv2.MORPH_CLOSE, kernel)
