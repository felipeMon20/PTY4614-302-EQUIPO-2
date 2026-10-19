import os
import sys

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

from src.theme.colors import *


def _ruta_recurso(*partes):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *partes)


class DashboardModule(QWidget):
    """Pantalla de espera: el dashboard todavía no se ha entregado."""

    _TAMANO_GIF = QSize(360, 324)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(14)
        layout.addStretch()

        self.lbl_gif = QLabel()
        self.lbl_gif.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_gif.setStyleSheet("background: transparent; border: none;")
        self._movie = QMovie(_ruta_recurso('src', 'assets', 'elmo_fuego.gif'))
        self._movie.setScaledSize(self._TAMANO_GIF)
        self.lbl_gif.setMovie(self._movie)
        layout.addWidget(self.lbl_gif)

        titulo = QLabel("Esperando que envíen el dashboard")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 20px; font-weight: bold; background: transparent;")
        layout.addWidget(titulo)

        detalle = QLabel("Cuando llegue, aparecerá aquí.")
        detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        detalle.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 13px; background: transparent;")
        layout.addWidget(detalle)
        layout.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        self._movie.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._movie.stop()
