from PyQt6.QtCore import Qt, QVariantAnimation, QEasingCurve, QRectF, QTimer, QEvent
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPen
from PyQt6.QtWidgets import QWidget

from src.theme.colors import SURFACE, BORDER
from src.theme import tema

COLOR_BLOQUE = QColor("#E8ECF1")
COLOR_BRILLO = QColor("#F7F9FB")
# En oscuro el brillo debe ser más claro que el bloque (la conversión
# automática los invertiría)
COLOR_BLOQUE_OSCURO = QColor("#1C2740")
COLOR_BRILLO_OSCURO = QColor("#2A3756")


class EsqueletoCarga(QWidget):
    """Capa sobre el contenido de una caja mientras corre una carga en
    segundo plano: tarjetas o filas grises con un brillo que las recorre.
    Es opaca (WA_OpaquePaintEvent), así que el brillo no repinta los widgets
    de abajo; al terminar, la foto del contenido nuevo aparece encima con un
    fundido. Uso: iniciar() al lanzar la carga, terminar() después de pintar
    los datos."""
    RETRASO_MS = 150        # cargas más rápidas no muestran el esqueleto
    FUNDIDO_MS = 220
    CICLO_BRILLO_MS = 1100
    MAXIMO_MS = 15000       # por si la carga nunca avisa que terminó

    ALTO_TARJETA = 78
    SEPARACION = 10

    def __init__(self, caja, forma='tarjetas'):
        super().__init__(caja)
        self._caja = caja
        self._forma = forma
        self._mostrando = False
        self._fase = 0.0
        self._foto = None
        self._opacidad_foto = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.hide()
        caja.installEventFilter(self)

        self._retraso = QTimer(self)
        self._retraso.setSingleShot(True)
        self._retraso.timeout.connect(self._mostrar)

        self._tope = QTimer(self)
        self._tope.setSingleShot(True)
        self._tope.timeout.connect(self._ocultar)

        self._brillo = QVariantAnimation(self)
        self._brillo.setStartValue(0.0)
        self._brillo.setEndValue(1.0)
        self._brillo.setDuration(self.CICLO_BRILLO_MS)
        self._brillo.setLoopCount(-1)
        self._brillo.valueChanged.connect(self._on_brillo)

        self._fundido = QVariantAnimation(self)
        self._fundido.setStartValue(0.0)
        self._fundido.setEndValue(1.0)
        self._fundido.setDuration(self.FUNDIDO_MS)
        self._fundido.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fundido.valueChanged.connect(self._on_fundido)
        self._fundido.finished.connect(self._ocultar)

    def iniciar(self):
        if self._mostrando:
            # Otra carga llegó durante el fundido: vuelve al esqueleto
            self._fundido.stop()
            self._foto = None
            self._brillo.start()
            self._tope.start(self.MAXIMO_MS)
            self.update()
            return
        self._retraso.start(self.RETRASO_MS)

    def terminar(self):
        self._retraso.stop()
        if not self._mostrando:
            return
        if not self._caja.isVisible():
            self._ocultar()
            return
        # Sin la capa encima, para que la foto sea solo del contenido nuevo
        self.hide()
        self._foto = self._caja.grab(self._rect_cubierto())
        self.show()
        self._brillo.stop()
        self._opacidad_foto = 0.0
        self._fundido.start()

    def _mostrar(self):
        if not self._caja.isVisible():
            return
        self._mostrando = True
        self._foto = None
        self.setGeometry(self._rect_cubierto())
        self.raise_()
        self.show()
        self._brillo.start()
        self._tope.start(self.MAXIMO_MS)

    def _ocultar(self):
        self._retraso.stop()
        self._tope.stop()
        self._brillo.stop()
        self._fundido.stop()
        self._mostrando = False
        self._foto = None
        self.hide()

    def _rect_cubierto(self):
        rect = self._caja.contentsRect()
        layout = self._caja.layout()
        if layout is not None:
            m = layout.contentsMargins()
            rect = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        return rect

    def eventFilter(self, obj, event):
        if obj is self._caja and event.type() == QEvent.Type.Resize and self._mostrando:
            self.setGeometry(self._rect_cubierto())
        return False

    def _on_brillo(self, valor):
        self._fase = float(valor)
        self.update()

    def _on_fundido(self, valor):
        self._opacidad_foto = float(valor)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), tema.fondo(SURFACE))
        if self._opacidad_foto < 1.0 or self._foto is None:
            if self._forma == 'ficha':
                self._pintar_ficha(painter)
            else:
                self._pintar_tarjetas(painter)
        if self._foto is not None:
            painter.setOpacity(self._opacidad_foto)
            painter.drawPixmap(0, 0, self._foto)
        painter.end()

    def _pincel_brillo(self):
        # Banda clara que cruza toda la capa de izquierda a derecha
        ancho = max(1, self.width())
        banda = max(120.0, ancho * 0.35)
        x0 = -banda + self._fase * (ancho + banda)
        gradiente = QLinearGradient(x0, 0, x0 + banda, 0)
        bloque, brillo = (COLOR_BLOQUE_OSCURO, COLOR_BRILLO_OSCURO) if tema.es_oscuro() else (COLOR_BLOQUE, COLOR_BRILLO)
        gradiente.setColorAt(0.0, bloque)
        gradiente.setColorAt(0.5, brillo)
        gradiente.setColorAt(1.0, bloque)
        return gradiente

    def _barra(self, painter, x, y, ancho, alto):
        painter.drawRoundedRect(QRectF(x, y, max(0.0, ancho), alto), alto / 2, alto / 2)

    def _pintar_tarjetas(self, painter):
        ancho = self.width()
        pincel = self._pincel_brillo()
        y = 0
        while y < self.height():
            tarjeta = QRectF(0.5, y + 0.5, ancho - 1, self.ALTO_TARJETA)
            painter.setPen(QPen(tema.fondo(BORDER), 1))
            painter.setBrush(tema.fondo(SURFACE))
            painter.drawRoundedRect(tarjeta, 8, 8)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pincel)
            self._barra(painter, 16, y + 16, ancho * 0.45, 12)
            self._barra(painter, ancho - 16 - 72, y + 14, 72, 16)
            self._barra(painter, 16, y + 38, ancho * 0.55, 9)
            self._barra(painter, 16, y + 56, ancho * 0.25, 9)
            y += self.ALTO_TARJETA + self.SEPARACION

    def _pintar_ficha(self, painter):
        ancho = self.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._pincel_brillo())
        self._barra(painter, 4, 6, ancho * 0.6, 16)
        self._barra(painter, 4, 32, ancho * 0.8, 10)
        y = 64
        fila = 0
        while y < self.height():
            if fila % 5 == 0:
                self._barra(painter, 4, y, ancho * 0.4, 12)
                y += 26
            self._barra(painter, 20, y, ancho * 0.32, 9)
            self._barra(painter, ancho - 4 - ancho * 0.22, y, ancho * 0.22, 9)
            y += 24
            fila += 1
