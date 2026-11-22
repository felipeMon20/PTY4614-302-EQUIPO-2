"""Selector de vistas: botones de a uno con una pastilla que se desliza hasta el elegido (Dashboard y Facturación Manual)."""
from PyQt6.QtCore import QEasingCurve, QRectF, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QSizePolicy

from src.theme import tema


_MARINO = "#1B2B4E"
_BOTON_OSCURO = "#3A66D4"


def _fondo_boton():
    """Fondo de la pastilla: marino en claro, azul más vivo en oscuro."""
    return _BOTON_OSCURO if tema.es_oscuro() else _MARINO


class SelectorDeslizante(QFrame):
    DURACION_MS = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(3, 3, 3, 3)
        self._lay.setSpacing(4)
        self._grupo = QButtonGroup(self)
        self._botones = []
        self._pastilla = QRectF()
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.DURACION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._mover)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def agregar(self, boton: QPushButton):
        self._grupo.addButton(boton)
        self._lay.addWidget(boton, 1)
        self._botones.append(boton)
        boton.toggled.connect(lambda marcado, b=boton: marcado and self._ir_a(b))

    def _destino(self):
        for b in self._botones:
            if b.isChecked():
                return QRectF(b.geometry())
        return None

    def _mover(self, valor):
        self._pastilla = QRectF(valor)
        self.update()

    def _ir_a(self, boton):
        destino = QRectF(boton.geometry())
        self._anim.stop()
        if not self.isVisible() or destino.isEmpty() or self._pastilla.isEmpty():
            self._pastilla = destino
            self.update()
            return
        self._anim.setStartValue(self._pastilla)
        self._anim.setEndValue(destino)
        self._anim.start()

    def _ajustar(self):
        self._lay.activate()
        destino = self._destino()
        if destino is not None and self._anim.state() != QVariantAnimation.State.Running:
            self._pastilla = destino
            self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._ajustar()
        QTimer.singleShot(0, self._ajustar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajustar()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fondo = QPainterPath()
        fondo.addRoundedRect(QRectF(self.rect()), 10, 10)
        painter.fillPath(fondo, tema.fondo("#F3F5F9"))
        if not self._pastilla.isEmpty():
            pastilla = QPainterPath()
            pastilla.addRoundedRect(self._pastilla, 8, 8)
            painter.fillPath(pastilla, QColor(_fondo_boton()))
        painter.end()
