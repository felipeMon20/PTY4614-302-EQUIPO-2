from PyQt6.QtCore import Qt, QVariantAnimation, QEasingCurve, QPoint, QRect, QRectF, QTimer, QEvent
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPen
from PyQt6.QtWidgets import QFrame, QTableView, QWidget
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


def animar_tabla_principal(contenedor, ms=300):
    """Esqueleto corto sobre la tabla más grande a la vista de una pantalla (cambio de pestaña)."""
    tablas = [t for t in contenedor.findChildren(QTableView) if t.isVisible() and t.viewport().height() >= 80]
    if tablas:
        animar_sobre_tabla(max(tablas, key=lambda t: t.width() * t.height()), ms)


def animar_caja(caja, ms=300):
    """Esqueleto corto sobre el cuerpo de una caja de `admin_estilo.caja_con_encabezado`: su encabezado
    azul y su marco se quedan quietos."""
    if not caja.isVisible() or caja.height() < 100:
        return
    esqueleto = caja.__dict__.get('_esqueleto_caja')
    if esqueleto is None:
        esqueleto = caja._esqueleto_caja = EsqueletoCaja(caja)
    esqueleto.iniciar_ya(rapido=True)
    QTimer.singleShot(ms, lambda: esqueleto.terminar() if sip.isdeleted(esqueleto) is False else None)


def animar_cajas(contenedor, ms=300):
    """`animar_caja` en todas las cajas visibles de una pantalla."""
    for caja in contenedor.findChildren(QFrame):
        if caja.property("cajaAdmin"):
            animar_caja(caja, ms)


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
    ALTO_TARJETA_GRILLA = 68
    ALTO_TARJETA_CONTRATO = 66

    def __init__(self, caja, forma='tarjetas', fondo=None):
        super().__init__(caja)
        self._caja = caja
        self._forma = forma
        self._fondo = fondo
        self._mostrando = False
        self.debajo_de = None   # función que devuelve un widget de la caja: el esqueleto cubre solo lo que queda bajo él
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

    def fijar_forma(self, forma):
        self._forma = forma
        self.update()

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
        referencia = self.debajo_de() if self.debajo_de is not None else None
        if referencia is not None and referencia.isVisible():
            fondo = referencia.mapTo(self._caja, QPoint(0, referencia.height())).y() + 10
            if rect.top() < fondo < rect.bottom() - 40:
                rect.setTop(fondo)
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
            if self._forma in ('dashboard', 'tablero'):
                self._pintar_dashboard(painter, self._forma == 'dashboard')
            elif self._forma in ('ficha', 'hoja'):
                self._pintar_ficha(painter, self._forma == 'ficha')
            elif self._forma in ('grilla', 'grilla_contratos'):
                self._pintar_tarjetas_grilla(painter, contratos=self._forma == 'grilla_contratos')
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

    def _pintar_tarjetas_grilla(self, painter, contratos=False):
        """Tarjetas compactas en una columna: las de Cliente (nombre y contadores)
        o las de Contratos (cuatro filas de chips)."""
        columnas, hueco = 1, 6 if contratos else 8
        ancho_col = (self.width() - hueco * (columnas - 1)) / columnas
        alto = self.ALTO_TARJETA_CONTRATO if contratos else self.ALTO_TARJETA_GRILLA
        pincel = self._pincel_brillo()
        y = 0
        while y < self.height():
            for c in range(columnas):
                x = c * (ancho_col + hueco)
                painter.setPen(QPen(tema.fondo(BORDER), 1))
                painter.setBrush(tema.fondo(SURFACE))
                painter.drawRoundedRect(QRectF(x + 0.5, y + 0.5, ancho_col - 1, alto - 1), 10, 10)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(pincel)
                if contratos:
                    der = (ancho_col - 20) * 0.42
                    izq = (ancho_col - 20) * 0.40
                    self._barra(painter, x + 10, y + 8, izq, 24)
                    self._barra(painter, x + 10, y + 38, izq, 18)
                    self._barra(painter, x + ancho_col - 10 - der, y + 11, der, 18)
                    self._barra(painter, x + ancho_col - 10 - der, y + 38, der, 18)
                else:
                    self._barra(painter, x + 10, y + 10, 14, 14)
                    self._barra(painter, x + 32, y + 10, ancho_col * 0.62, 10)
                    self._barra(painter, x + 32, y + 26, ancho_col * 0.38, 10)
                    self._barra(painter, x + 10, y + 46, ancho_col * 0.36, 9)
                    self._barra(painter, x + ancho_col - 10 - 112, y + 43, 54, 15)
                    self._barra(painter, x + ancho_col - 10 - 52, y + 43, 52, 15)
            y += alto + hueco

    def _pintar_ficha(self, painter, con_portada=True):
        ancho = self.width()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._pincel_brillo())
        # Portada compacta (título, VIN y chips) y ficha en dos columnas
        if con_portada:
            painter.drawRoundedRect(QRectF(0, 0, ancho, 78), 14, 14)
            painter.setBrush(tema.fondo(SURFACE))
            self._barra(painter, 16, 16, ancho * 0.34, 14)
            self._barra(painter, 16, 40, ancho * 0.22, 10)
            for i in range(4):
                self._barra(painter, 16 + i * (ancho * 0.16 + 8), 58, ancho * 0.16, 12)
            painter.setBrush(self._pincel_brillo())
        y = 98 if con_portada else 4
        hueco = 16
        ancho_col = (ancho - hueco) / 2
        while y < self.height():
            for c in range(2):
                x = c * (ancho_col + hueco)
                self._barra(painter, x, y, ancho_col * 0.45, 11)
                for f in range(4):
                    yf = y + 24 + f * 22
                    self._barra(painter, x + 8, yf, ancho_col * 0.30, 9)
                    self._barra(painter, x + ancho_col - 8 - ancho_col * 0.34, yf, ancho_col * 0.34, 9)
            y += 24 + 4 * 22 + 12

    def _tarjeta_dashboard(self, painter, pincel, x, y, ancho, alto):
        painter.setPen(QPen(tema.fondo("#E3E8F0"), 1))
        painter.setBrush(tema.fondo("#FFFFFF"))
        painter.drawRoundedRect(QRectF(x + 0.5, y + 0.5, ancho - 1, alto - 1), 16, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pincel)
        self._barra(painter, x + 18, y + 20, ancho * 0.4, 12)
        self._barra(painter, x + 18, y + 42, ancho * 0.6, 9)

    def _pintar_dashboard(self, painter, con_cifras=True):
        """Silueta de los tableros del Dashboard: franja de estado con sus chips, la fila de cifras
        (solo el Resumen) y las cajas de gráficos en dos filas."""
        ancho, hueco = self.width(), 10
        pincel = self._pincel_brillo()
        ancho_col = (ancho - 4 * hueco) / 5
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pincel)
        for i in range(5):
            painter.drawRoundedRect(QRectF(i * (ancho_col + hueco), 0, ancho_col, 46), 14, 14)
        y = 46 + hueco
        if con_cifras:
            for i in range(5):
                self._tarjeta_dashboard(painter, pincel, i * (ancho_col + hueco), y, ancho_col, 96)
            y += 96 + hueco
        alto_fila = (self.height() - y - hueco) / 2
        if alto_fila < 60:
            return
        ancho_caja = (ancho - hueco) / 2
        for _ in range(2):
            for c in range(2):
                x = c * (ancho_caja + hueco)
                self._tarjeta_dashboard(painter, pincel, x, y, ancho_caja, alto_fila)
                for k in range(min(6, int((alto_fila - 80) // 26))):
                    self._barra(painter, x + 18, y + 66 + k * 26, ancho_caja * (0.25 + 0.12 * ((k * 3 + c) % 4)), 12)
            y += alto_fila + hueco


class EsqueletoCaja(EsqueletoCarga):
    """Cubre el cuerpo de una caja con encabezado, sin tocar el encabezado ni las esquinas."""
    MARGEN = 6

    def __init__(self, caja):
        super().__init__(caja, 'tarjetas')

    def _rect_cubierto(self):
        caja, m = self._caja, self.MARGEN
        tope = caja._encabezado.geometry().bottom() + m
        return QRect(m, tope, max(0, caja.width() - 2 * m), max(0, caja.height() - tope - m))
