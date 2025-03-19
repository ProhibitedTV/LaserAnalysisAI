# LaserAnalysisAI

LaserAnalysisAI is a Python-based application that processes laser diffraction images, detects patterns, and extracts potential symbolic characters using OCR (Optical Character Recognition). The application leverages OpenCV, PyQt5 for the GUI, and Tesseract OCR for text extraction.

## 📂 Directory Structure
```
LaserAnalysisAI/
│── main.py                  # Entry point for the application
│── README.md                # Project documentation
│
├── gui/                     # GUI components
│   ├── main_window.py       # Main GUI logic
│   ├── frame_viewer.py      # Handles frame navigation
│   ├── ocr_processor.py     # Handles OCR processing
│   ├── video_loader.py      # Handles video loading and frame extraction
│
├── scripts/                 # Image processing & OCR utilities
│   ├── image_processing.py  # Image preprocessing logic
│   ├── frame_extraction.py  # Extracts frames from video files
│
├── data/                    # Directory for processed frames
│   ├── frames/              # Extracted frames from videos
│
└── venv/                    # Virtual environment (if using one)
```

## 🚀 Features
✅ **Load & Extract Frames from Videos** – Supports `.mp4`, `.avi`, `.mov`, and `.mkv` formats.  
✅ **Frame Navigation** – Use the **frame slider** to jump between frames.  
✅ **Image Processing & Analysis** – Apply various preprocessing techniques to detect laser diffraction patterns.  
✅ **Matplotlib Visualization Toggle** – Enable or disable the analysis window.  
✅ **OCR Detection** – Extracts potential characters using Tesseract OCR.  
✅ **Save OCR Results** – Option to save detected text as a `.txt` file.  

## 🔧 Installation
### **1️⃣ Clone the Repository**
```sh
git clone https://github.com/ProhibitedTV/LaserAnalysisAI.git
cd LaserAnalysisAI
```

### **2️⃣ Set Up a Virtual Environment (Recommended)**
```sh
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows
```

### **3️⃣ Install Dependencies**
```sh
pip install -r requirements.txt
```

### **4️⃣ Install Tesseract OCR**
- **Windows**: [Download & Install](https://github.com/UB-Mannheim/tesseract/wiki) and ensure it's added to PATH.
- **Linux (Ubuntu/Debian)**:
  ```sh
  sudo apt install tesseract-ocr
  ```
- **Mac (Homebrew)**:
  ```sh
  brew install tesseract
  ```

### **5️⃣ Run the Application**
```sh
python main.py
```

## 🎮 Usage Guide
1️⃣ **Load a Video** → Use the "Load Video" button to extract frames.  
2️⃣ **Navigate Frames** → Adjust the **frame slider** to select different frames.  
3️⃣ **Process Image** → Click "Process Image" to analyze diffraction patterns.  
4️⃣ **Enable Analysis** → Toggle the "Show Image Analysis" checkbox to visualize processing results.  
5️⃣ **Run OCR** → Click "Detect Characters" to extract potential symbols from the processed image.  
6️⃣ **Save OCR Results** → Click "Save OCR Text" to export detected text to a file.  

## 🛠️ Troubleshooting
**Q: Tesseract OCR not found?**  
A: Ensure Tesseract is installed and in your system's PATH. Test by running:
```sh
tesseract -v
```
If not detected, manually set the path in `ocr_processor.py`:
```python
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

**Q: No frames appear after loading a video?**  
A: Check that the video format is supported (`.mp4`, `.avi`, `.mov`, `.mkv`). If frames aren’t extracted, ensure `data/frames/` exists.

**Q: OCR output is inaccurate?**  
A: Try adjusting image processing settings in `image_processing.py`, such as contrast enhancement or noise reduction.

## 📜 License
This project is licensed under the MIT License. Feel free to modify and improve!

## 📞 Contact
For support or feature requests, open an issue on the GitHub repository or contact the maintainer.

Happy analyzing! 🎉