"""
Main entry point for the Laser Projection Analysis application.
This script initializes the PyQt5 application and launches the main window.
"""

import sys
from PyQt5.QtWidgets import QApplication
from gui.main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
