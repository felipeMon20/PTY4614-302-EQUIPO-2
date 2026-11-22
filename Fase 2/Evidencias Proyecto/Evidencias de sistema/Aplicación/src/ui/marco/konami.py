"""Código Konami del modo programador: escrito en cualquier pantalla de la app (con la ventana activa), abre el juego.

Mientras se escribe aparecen, abajo a la derecha, diez puntitos tenues que se encienden con cada tecla correcta y se
apagan solos. Solo se instala con MODO_PROGRAMADOR."""
from PyQt6.QtCore import QEasingCurve, QEvent, QObject, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QApplication, QWidget

KONAMI = (Qt.Key.Key_Up, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
          Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_B, Qt.Key.Key_A)


class PistaKonami(QWidget):
    """Puntitos tenues que muestran cuántas teclas correctas van; no reciben el mouse."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(len(KONAMI) * 7, 8)
        self._avance = 0
        self._alfa = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(350)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._cambiar_alfa)
        self._olvido = QTimer(self)
        self._olvido.setSingleShot(True)
        self._olvido.setInterval(2200)
        self._olvido.timeout.connect(lambda: self._mover_alfa(0.0))
        self.hide()

    def _cambiar_alfa(self, valor):
        self._alfa = float(valor)
        self.setVisible(self._alfa > 0.01)
        self.update()

    def _mover_alfa(self, destino):
        self._anim.stop()
        self._anim.setStartValue(self._alfa)
        self._anim.setEndValue(destino)
        self._anim.start()

    def avanzar(self, n):
        """n teclas correctas seguidas; 0 apaga los puntos."""
        self._avance = n
        if n <= 0:
            self._olvido.stop()
            self._mover_alfa(0.0)
            return
        self._mover_alfa(1.0)
        self._olvido.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(len(KONAMI)):
            encendido = i < self._avance
            p.setBrush(QColor(107, 122, 144, int(255 * self._alfa * (0.8 if encendido else 0.22))))
            p.drawEllipse(i * 7 + 1, 2, 4, 4)
        p.end()


class DetectorKonami(QObject):
    """Observa el teclado de la ventana principal; al completar el código abre el juego."""

    def __init__(self, ventana):
        super().__init__(ventana)
        self._ventana = ventana
        self._avance = 0
        self._pista = PistaKonami(ventana)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        # Una tecla sin atender sube por los widgets padre y el filtro la vería varias veces: solo cuenta la del primero
        if (event.type() == QEvent.Type.KeyPress and not event.isAutoRepeat() and isinstance(obj, QWidget)
                and obj.window() is self._ventana and obj is (QApplication.focusWidget() or QApplication.activeWindow())):
            tecla = event.key()
            if tecla == KONAMI[self._avance]:
                self._avance += 1
            else:
                self._avance = 1 if tecla == KONAMI[0] else 0
            self._mostrar_pista()
            if self._avance == len(KONAMI):
                self._avance = 0
                QTimer.singleShot(250, self._abrir_juego)
        return False

    def _mostrar_pista(self):
        v = self._ventana
        self._pista.move(v.width() - self._pista.width() - 20, v.height() - self._pista.height() - 12)
        self._pista.raise_()
        self._pista.avanzar(self._avance)

    def _abrir_juego(self):
        from src.ui.marco.juego_volvo_scania import JuegoDialogo
        self._pista.avanzar(0)
        JuegoDialogo(self._ventana).exec()
