# Laser Projection Analysis Application

The **Laser Projection Analysis Application** is a PyQt5-based GUI tool designed for analyzing laser projection videos. It provides a streamlined workflow for extracting frames from videos, applying various image processing techniques, and performing Optical Character Recognition (OCR) on the processed frames.

## Features

### 1. **Video Loading and Frame Extraction**
- Load video files in common formats such as `.mp4`, `.avi`, `.mov`, and `.mkv`.
- Extract frames at regular intervals and save them to the `data/frames` directory.
- Progress updates during frame extraction to keep the user informed.

### 2. **Image Processing**
- Apply a variety of image processing techniques to the extracted frames:
  - **Edge Detection**: Highlights edges by detecting areas with rapid intensity changes.
  - **Thresholding**: Converts images to black and white based on pixel intensity thresholds.
  - **Morphological Operations**: Refines shapes in the image using dilation and erosion.
  - **Adaptive Thresholding**: Dynamically applies thresholds based on local pixel neighborhoods.
  - **Gaussian Blur**: Smoothens the image by reducing noise and detail.
  - **Sharpening**: Enhances edges and fine details in the image.
  - **Histogram Equalization**: Improves contrast by redistributing pixel intensity values.
  - **Median Blur**: Reduces noise while preserving edges using a median filter.
  - **Bilateral Filter**: Smoothens the image while preserving edges by considering spatial and intensity differences.
- Select the desired processing mode from a dropdown menu.
- View a brief explanation of each processing mode in a dynamic help text box.

### 3. **Optical Character Recognition (OCR)**
- Perform OCR on the processed frames using Tesseract.
- Supports multiple languages, including English, French, Spanish, German, Italian, Portuguese, Russian, Japanese, and Chinese (Simplified and Traditional).
- Displays detected text, average confidence, and word-level details with bounding boxes.
- Batch OCR processing for all frames with progress updates.

### 4. **Frame Navigation**
- Navigate through the extracted and processed frames using:
  - A **slider** for quick navigation.
  - **Previous** and **Next** buttons for frame-by-frame navigation.
- View the original and processed frames side by side.

### 5. **Customizable Tesseract Path**
- Set the path to the Tesseract executable directly from the GUI.

---

## Installation

### Prerequisites
- Python 3.7 or higher
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed on your system

### Steps
1. Clone the repository:
   ```bash
   git clone https://github.com/your-repo/LaserProjectionAnalysis.git
   cd LaserProjectionAnalysis
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the application:
   ```bash
   python main.py
   ```

---

## Usage

1. **Load a Video**:
   - Click the **"Load Video and Extract Frames"** button.
   - Select a video file from your system.
   - Frames will be extracted and saved to the `data/frames` directory.

2. **Select a Processing Mode**:
   - Choose a processing mode from the dropdown menu.
   - A brief explanation of the selected mode will appear below the dropdown.

3. **Process Frames**:
   - Click the **"Process Frames"** button to apply the selected processing mode to the extracted frames.
   - Processed frames will be saved to the `data/processed_frames` directory.

4. **Perform OCR**:
   - Click the **"Process OCR"** button to extract text from the processed frames.
   - Detected text, confidence levels, and word details will be displayed in the text box.

5. **Navigate Frames**:
   - Use the slider or the **Previous** and **Next** buttons to navigate through the frames.
   - View the original and processed frames side by side.

6. **Set Tesseract Path**:
   - Use the **"Set Tesseract Path"** option in the File menu to specify the path to the Tesseract executable.

---

## Directory Structure

```
LaserProjectionAnalysis/
├── data/
│   ├── frames/               # Extracted frames
│   ├── processed_frames/     # Processed frames
├── gui/
│   ├── main_window.py        # Main GUI window
│   ├── frame_viewer.py       # Frame navigation and processing
│   ├── ocr_processor.py      # OCR processing
│   ├── video_loader.py       # Video loading and frame extraction
├── scripts/
│   ├── image_processing.py   # Image processing techniques
│   ├── frame_extraction.py   # Frame extraction logic
├── utils/
│   ├── common.py             # Utility functions
├── main.py                   # Entry point for the application
├── requirements.txt          # Python dependencies
└── README.md                 # Project documentation
```

---

## Dependencies

- PyQt5
- OpenCV
- Tesseract OCR
- NumPy
- Matplotlib

Install all dependencies using:
```bash
pip install -r requirements.txt
```

---

## Contributing

Contributions are welcome! Please fork the repository and submit a pull request with your changes.

---

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.