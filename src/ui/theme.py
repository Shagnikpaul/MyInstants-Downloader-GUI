from PySide6.QtGui import QPalette, QColor, QIcon, QPixmap
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QStyleFactory
from ..utils import resource_path

def apply_dark_theme(app):
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(30, 30, 30))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    palette.setColor(QPalette.PlaceholderText, Qt.white)
    app.setPalette(palette)

def apply_light_theme(app):
    app.setStyle("Fusion")
    palette = QStyleFactory.create("Fusion").standardPalette()
    app.setPalette(palette)

def get_icon(name, color_invert=False):
    path = resource_path(name)
    if not path.exists():
        return QIcon()
    pixmap = QPixmap(str(path))
    if color_invert:
        image = pixmap.toImage()
        image.invertPixels()
        pixmap = QPixmap.fromImage(image)
    return QIcon(pixmap)
