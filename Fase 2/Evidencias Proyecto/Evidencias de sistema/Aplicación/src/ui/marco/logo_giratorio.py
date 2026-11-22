"""Logo de Volvo del menú lateral: gira como en la pantalla de arranque cada vez que el menú se vuelve a mostrar."""
import math
import os

from PyQt6.QtCore import Qt, QElapsedTimer, QPointF, QSize, QTimer
from PyQt6.QtGui import QPainter, QPixmap, QTransform
from PyQt6.QtWidgets import QWidget

LADO = 54
DURACION_GIRO_MS = 1100


def _ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


class LogoGiratorio(QWidget):
    def __init__(self, carpeta_assets, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(LADO, LADO))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        carpeta = carpeta_assets
        self._frente = QPixmap(os.path.join(carpeta, 'splash_logo_frente.png'))
        self._reverso = QPixmap(os.path.join(carpeta, 'splash_logo_reverso.png'))
        self._reloj = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def girar(self):
        self._reloj.start()
        self._timer.start()

    def _tick(self):
        if self._reloj.elapsed() >= DURACION_GIRO_MS:
            self._timer.stop()
        self.update()

    def paintEvent(self, _evento):
        t = self._reloj.elapsed() / DURACION_GIRO_MS if self._timer.isActive() else 1.0
        giro = _ease_out(t) * 2 * math.pi
        sx = math.cos(giro)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.translate(QPointF(self.width() / 2, self.height() / 2))
        ancho = max(abs(sx), 0.02) * (1 if sx >= 0 else -1)
        p.setTransform(QTransform().scale(ancho, 1), True)
        pm = self._frente if sx >= 0 else self._reverso
        p.drawPixmap(-self.width() // 2, -self.height() // 2, self.width(), self.height(), pm)
        p.end()
