import cv2
import numpy as np
import matplotlib.pyplot as plt

def process_image(image_path, show_analysis=False, processing_type="Edge Detection"):
    """Load an image, apply preprocessing, and extract potential symbols."""
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    
    if img is None:
        print("Error: Image not found!")
        return None

    if processing_type == "Edge Detection":
        # Apply Gaussian Blur to reduce noise
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        # Edge Detection (Canny)
        processed = cv2.Canny(blurred, 50, 150)
    elif processing_type == "Thresholding":
        # Apply Gaussian Blur to reduce noise
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        # Thresholding
        _, processed = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif processing_type == "Morphological Operations":
        # Apply Gaussian Blur to reduce noise
        blurred = cv2.GaussianBlur(img, (5, 5), 0)
        # Morphological operations to enhance character-like features
        kernel = np.ones((3, 3), np.uint8)
        processed = cv2.morphologyEx(blurred, cv2.MORPH_CLOSE, kernel)

    if show_analysis:
        # Display the results if the checkbox is enabled
        plt.figure(figsize=(15, 5))
        plt.subplot(1,3,1)
        plt.imshow(img, cmap='gray')
        plt.title("Original Image")

        plt.subplot(1,3,2)
        plt.imshow(processed, cmap='gray')
        plt.title(processing_type)

        plt.subplot(1,3,3)
        plt.imshow(processed, cmap='gray')
        plt.title("Processed Image")

        plt.show()

    return processed

# Test the function
if __name__ == "__main__":
    image_path = "../data/sample_projection.jpg"  # Change this to an actual image path
    process_image(image_path, show_analysis=True, processing_type="Edge Detection")
