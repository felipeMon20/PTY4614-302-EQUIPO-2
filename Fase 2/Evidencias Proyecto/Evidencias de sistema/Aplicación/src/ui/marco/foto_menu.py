"""Foto del pie del menú lateral: llena el alto libre (con tope) y se recorta por los lados, anclada abajo."""
import math

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QRectF, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import QWidget

from src.theme.menu_fotos import ruta_foto

ALTO_INICIAL = 352
ALTO_MIN = 0
ALTO_MAX = 520
FUNDIDO_ARRIBA = 0.24


class FotoMenu(QWidget):
    def __init__(self, carpeta_assets, ancho, parent=None):
        super().__init__(parent)
        self._carpeta = carpeta_assets
        self._origen = QPixmap()
        self._cache = None
        self._anterior = None
        self._avance = 1.0
        self._animacion = QVariantAnimation(self)
        self._animacion.setDuration(380)
        self._animacion.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animacion.valueChanged.connect(self._on_avance)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(ancho)
        self.setFixedHeight(ALTO_INICIAL)

    def set_foto(self, foto_id, animado=False):
        """Con `animado` la foto nueva se abre desde el centro hacia afuera sobre la anterior."""
        anterior = self._cache[1] if (animado and self._cache is not None and self.isVisible()) else None
        self._origen = QPixmap(ruta_foto(self._carpeta, foto_id))
        self._cache = None
        if anterior is not None:
            self._anterior = anterior
            self._animacion.stop()
            self._animacion.setStartValue(0.0)
            self._animacion.setEndValue(1.0)
            self._animacion.start()
        self.update()

    def _on_avance(self, valor):
        self._avance = valor
        if valor >= 1.0:
            self._anterior = None
        self.update()

    def fijar_alto(self, libre):
        alto = max(ALTO_MIN, min(ALTO_MAX, libre))
        if alto != self.height():
            self.setFixedHeight(alto)

    def _armar(self):
        dpr = self.devicePixelRatioF()
        ancho, alto = round(self.width() * dpr), round(self.height() * dpr)
        imagen = QImage(ancho, alto, QImage.Format.Format_ARGB32_Premultiplied)
        imagen.fill(Qt.GlobalColor.transparent)
        if not self._origen.isNull():
            ajustada = self._origen.scaled(ancho, alto, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                           Qt.TransformationMode.SmoothTransformation)
            p = QPainter(imagen)
            p.drawPixmap(0, 0, ajustada, (ajustada.width() - ancho) // 2, ajustada.height() - alto, ancho, alto)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            fundido = QLinearGradient(0, 0, 0, alto)
            fundido.setColorAt(0.0, QColor(0, 0, 0, 0))
            fundido.setColorAt(FUNDIDO_ARRIBA, QColor(0, 0, 0, 255))
            fundido.setColorAt(1.0, QColor(0, 0, 0, 255))
            p.fillRect(imagen.rect(), fundido)
            p.end()
        pm = QPixmap.fromImage(imagen)
        pm.setDevicePixelRatio(dpr)
        return pm

    def paintEvent(self, _evento):
        clave = (self.width(), self.height(), self.devicePixelRatioF())
        if self._cache is None or self._cache[0] != clave:
            self._cache = (clave, self._armar())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._anterior is not None and self._avance < 1.0:
            centro = QPointF(self.width() / 2, self.height() / 2)
            radio = math.hypot(centro.x(), centro.y()) * self._avance
            recorte = QPainterPath()
            recorte.addEllipse(centro, radio, radio)
            # La anterior solo se ve fuera del círculo: dentro, el fondo del menú aparece junto con la foto nueva
            fuera = QPainterPath()
            fuera.addRect(QRectF(self.rect()))
            p.setClipPath(fuera.subtracted(recorte))
            p.drawPixmap(0, 0, self._anterior)
            p.setClipPath(recorte)
        p.drawPixmap(0, 0, self._cache[1])
        p.end()


class AjusteAltoFoto(QObject):
    """Con la ventana alta la foto crece hasta su tope; con la ventana baja se achica y los botones del menú
    conservan siempre su alto (antes se aplastaban y saltaban al plegar el menú)."""

    def __init__(self, sidebar, cabecera, contenido, foto):
        super().__init__(sidebar)
        self._cabecera, self._contenido, self._foto = cabecera, contenido, foto
        sidebar.installEventFilter(self)

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Type.Resize:
            libre = objeto.height() - self._cabecera.height() - self._contenido.sizeHint().height()
            self._foto.fijar_alto(libre)
        return False
