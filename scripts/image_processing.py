"""
Image Processing module for preprocessing and analyzing images.
This module applies various techniques such as edge detection, thresholding, and morphological operations.
"""

import cv2
import matplotlib.pyplot as plt
import numpy as np
from utils.common import load_grayscale_image, apply_threshold, apply_morphological_operations

def process_image(image_path, show_analysis=False, processing_type="Edge Detection"):
    """
    Processes an image using the specified processing type.

    Args:
        image_path (str): Path to the image file.
        show_analysis (bool): Whether to display analysis results.
        processing_type (str): Type of processing to apply ("Edge Detection", "Thresholding", etc.).

    Returns:
        numpy.ndarray: Processed image.
    """
    img = load_grayscale_image(image_path)
    
    if img is None:
        print("Error: Image not found!")
        return None

    if processing_type == "Edge Detection":
        processed = apply_edge_detection(img)
    elif processing_type == "Thresholding":
        processed = apply_threshold(img)
    elif processing_type == "Morphological Operations":
        processed = apply_morphological_operations(img)
    elif processing_type == "Adaptive Thresholding":
        processed = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
    elif processing_type == "Gaussian Blur":
        processed = cv2.GaussianBlur(img, (5, 5), 0)
    elif processing_type == "Sharpening":
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        processed = cv2.filter2D(img, -1, kernel)
    elif processing_type == "Histogram Equalization":
        processed = cv2.equalizeHist(img)
    elif processing_type == "Median Blur":
        processed = cv2.medianBlur(img, 5)
    elif processing_type == "Bilateral Filter":
        processed = cv2.bilateralFilter(img, 9, 75, 75)
    else:
        print(f"Error: Unknown processing type '{processing_type}'")
        return None

    if show_analysis:
        display_analysis(img, processed, processing_type)

    return processed

def apply_edge_detection(image):
    """
    Applies edge detection to the image using the Canny algorithm.

    Args:
        image (numpy.ndarray): Input grayscale image.

    Returns:
        numpy.ndarray: Edge-detected image.
    """
    blurred = cv2.GaussianBlur(image, (5, 5), 0)
    return cv2.Canny(blurred, 50, 150)

def display_analysis(original, processed, processing_type):
    """
    Displays the original and processed images side by side for analysis.

    Args:
        original (numpy.ndarray): Original image.
        processed (numpy.ndarray): Processed image.
        processing_type (str): Type of processing applied.
    """
    plt.figure(figsize=(15, 5))
    plt.subplot(1, 2, 1)
    plt.imshow(original, cmap='gray')
    plt.title("Original Image")

    plt.subplot(1, 2, 2)
    plt.imshow(processed, cmap='gray')
    plt.title(processing_type)

    plt.show()

# Test the function
if __name__ == "__main__":
    image_path = "../data/sample_projection.jpg"  # Change this to an actual image path
    process_image(image_path, show_analysis=True, processing_type="Edge Detection")
