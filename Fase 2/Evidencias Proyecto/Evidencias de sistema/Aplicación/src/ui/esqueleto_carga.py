from PyQt6.QtCore import Qt, QVariantAnimation, QEasingCurve, QRectF, QTimer, QEvent
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPen
from PyQt6.QtWidgets import QWidget
from PyQt6 import sip

from src.theme.colors import SURFACE, BORDER
from src.theme import tema

COLOR_BLOQUE = QColor("#E8ECF1")
COLOR_BRILLO = QColor("#F7F9FB")
# En oscuro el brillo debe ser más claro que el bloque (la conversión
# automática los invertiría)
COLOR_BLOQUE_OSCURO = QColor("#1C2740")
COLOR_BRILLO_OSCURO = QColor("#2A3756")


def animar_sobre_tabla(tabla, ms=650):
    """Esqueleto corto sobre el viewport de una tabla (búsquedas y filtros)."""
    viewport = tabla.viewport()
    if viewport.height() < 80 or not tabla.isVisible():
        return
    esqueleto = tabla.__dict__.get('_esqueleto_busqueda')
    if esqueleto is None:
        esqueleto = tabla._esqueleto_busqueda = EsqueletoCarga(viewport, 'tarjetas')
    esqueleto.iniciar_ya()
    QTimer.singleShot(ms, lambda: esqueleto.terminar() if sip.isdeleted(esqueleto) is False else None)


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
    CICLO_BRILLO_RAPIDO_MS = 500
    FUNDIDO_RAPIDO_MS = 120
    MAXIMO_MS = 15000       # por si la carga nunca avisa que terminó

    ALTO_TARJETA = 78
    SEPARACION = 10

    def __init__(self, caja, forma='tarjetas', fondo=None):
        super().__init__(caja)
        self._caja = caja
        self._forma = forma
        self._fondo = fondo
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

    def _fijar_velocidad(self, rapido):
        self._brillo.setDuration(self.CICLO_BRILLO_RAPIDO_MS if rapido else self.CICLO_BRILLO_MS)
        self._fundido.setDuration(self.FUNDIDO_RAPIDO_MS if rapido else self.FUNDIDO_MS)

    def iniciar(self, rapido=False):
        self._fijar_velocidad(rapido)
        if self._mostrando:
            # Otra carga llegó durante el fundido: vuelve al esqueleto
            self._fundido.stop()
            self._foto = None
            self._brillo.start()
            self._tope.start(self.MAXIMO_MS)
            self.update()
            return
        self._retraso.start(self.RETRASO_MS)

    def iniciar_ya(self, rapido=False):
        """Muestra el esqueleto sin el retraso inicial (cambios de tema al
        desplazarse). Con `rapido` el brillo y el fundido corren más deprisa."""
        if self._mostrando:
            self.iniciar(rapido)
            return
        self._fijar_velocidad(rapido)
        self._mostrar()

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
        painter.fillRect(self.rect(), tema.fondo(self._fondo) if self._fondo else tema.fondo(SURFACE))
        if self._opacidad_foto < 1.0 or self._foto is None:
            if self._forma == 'dashboard':
                self._pintar_dashboard(painter)
            elif self._forma == 'ficha':
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
        oscuro = tema.es_oscuro()
        bloque, brillo = (COLOR_BLOQUE_OSCURO, COLOR_BRILLO_OSCURO) if oscuro else (COLOR_BLOQUE, COLOR_BRILLO)
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

    def _tarjeta_dashboard(self, painter, pincel, x, y, ancho, alto):
        painter.setPen(QPen(tema.fondo("#E3E8F0"), 1))
        painter.setBrush(tema.fondo("#FFFFFF"))
        painter.drawRoundedRect(QRectF(x + 0.5, y + 0.5, ancho - 1, alto - 1), 16, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pincel)
        self._barra(painter, x + 18, y + 20, ancho * 0.4, 12)
        self._barra(painter, x + 18, y + 42, ancho * 0.6, 9)

    def _pintar_dashboard(self, painter):
        """Silueta del Dashboard: tarjetas de cifras, dos gráficos anchos y la fila final."""
        ancho, hueco = self.width(), 14
        pincel = self._pincel_brillo()
        ancho_kpi = (ancho - 3 * hueco) / 4
        for i in range(4):
            x = i * (ancho_kpi + hueco)
            self._tarjeta_dashboard(painter, pincel, x, 0, ancho_kpi, 172)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pincel)
            self._barra(painter, x + 18, 80, ancho_kpi * 0.35, 26)
            self._barra(painter, x + 18, 128, ancho_kpi - 36, 8)
        y = 172 + hueco
        alto_mes = min(330, max(120, self.height() - y))
        self._tarjeta_dashboard(painter, pincel, 0, y, ancho, alto_mes)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pincel)
        for fila in range(min(10, int((alto_mes - 90) // 28))):
            yf = y + 74 + fila * 28
            largo = ancho * (0.14 + 0.11 * ((fila * 5) % 4))
            self._barra(painter, ancho / 2 - largo, yf, largo, 14)
            self._barra(painter, ancho / 2 + 4, yf, ancho * (0.06 + 0.07 * ((fila * 3) % 4)), 14)
        y += alto_mes + hueco
        alto_metas = min(260, max(0, self.height() - y))
        if alto_metas < 100:
            return
        self._tarjeta_dashboard(painter, pincel, 0, y, ancho, alto_metas)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pincel)
        columnas = 6
        paso = (ancho - 80) / columnas
        for c in range(columnas):
            alto_col = (alto_metas - 120) * (0.35 + 0.13 * ((c * 3) % 5))
            self._barra(painter, 40 + c * paso + paso * 0.2, y + alto_metas - 36 - alto_col, paso * 0.6, alto_col)