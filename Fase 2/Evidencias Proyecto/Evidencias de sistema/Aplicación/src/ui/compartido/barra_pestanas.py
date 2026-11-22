"""Barra de pestañas con teclado: Tab entra a la barra, las flechas mueven un recuadro de foco sin cambiar de pestaña y
Espacio o Enter abren la pestaña marcada."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QTabBar


class BarraPestanas(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Solo con Tab: un clic con el mouse no deja el recuadro puesto
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self._foco = -1

    def _visibles(self):
        return [i for i in range(self.count()) if self.isTabVisible(i) and self.isTabEnabled(i)]

    def focusInEvent(self, evento):
        self._foco = self.currentIndex()
        super().focusInEvent(evento)
        self.update()

    def focusOutEvent(self, evento):
        super().focusOutEvent(evento)
        self.update()

    def keyPressEvent(self, evento):
        tecla = evento.key()
        visibles = self._visibles()
        if tecla in (Qt.Key.Key_Right, Qt.Key.Key_Left) and visibles:
            if self._foco not in visibles:
                self._foco = visibles[0]
            else:
                paso = 1 if tecla == Qt.Key.Key_Right else -1
                self._foco = visibles[(visibles.index(self._foco) + paso) % len(visibles)]
            self.update()
            evento.accept()
            return
        if tecla in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._foco in visibles:
            self.tabBarClicked.emit(self._foco)
            self.setCurrentIndex(self._foco)
            evento.accept()
            return
        super().keyPressEvent(evento)

    def paintEvent(self, evento):
        super().paintEvent(evento)
        if self.hasFocus() and 0 <= self._foco < self.count() and self.isTabVisible(self._foco):
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor("#1F6FEB"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.tabRect(self._foco)).adjusted(2, 2, -2, -2), 8, 8)
            p.end()
