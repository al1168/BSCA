"""Entry point for the BSCA Setup GUI. Sibling of `gui.py` but
simpler: no settings file, no language seeding, no first-run dialog."""
import sys

from PyQt6.QtWidgets import QApplication

from setup_gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
