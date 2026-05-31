import sys
import os
from PyQt6.QtWidgets import QApplication
from src.viewer import LectorWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Lector')
    window = LectorWindow()
    window.show()
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            window._set_text(f.read())
        window.setWindowTitle(f'Lector — {os.path.basename(path)}')
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
