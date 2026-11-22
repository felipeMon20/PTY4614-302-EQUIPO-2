"""Cambio de pestaña del Dashboard con deslizamiento vertical y con la rueda del mouse.
Al cambiar, la zona de contenido de la pestaña que sale y la de la que entra se dibujan como dos fotos que suben o bajan
juntas: no se reacomoda nada por cuadro. Con la rueda, un giro cambia de pestaña y no queda a medias."""
import time
from math import pi, sin

from PyQt6.QtCore import QEasingCurve, QRect, QRectF, Qt, QTimer, QVariantAnimation
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QTabWidget, QWidget

from src.ui.dashboard.base import FONDO


class _CapaDeslizante(QWidget):
    """Capa opaca sobre el contenido que dibuja las dos fotos desplazadas (o una sola que rebota)."""
    DURACION = 380
    DURACION_REBOTE = 220

    def __init__(self, parent):
        super().__init__(parent)
        self.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._vieja = self._nueva = None
        self._signo = 1
        self._t = 0.0
        self._rebote = False
        self._al_terminar = None
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._mover)
        self._anim.finished.connect(self._fin)

    def congelar(self, region, foto):
        """Muestra la foto quieta (mientras la pestaña nueva se pinta por primera vez)."""
        self._anim.stop()
        self._preparar(region, foto, None, 1, None, False)

    def deslizar(self, region, vieja, nueva, signo, al_terminar):
        self._preparar(region, vieja, nueva, signo, al_terminar, False)
        self._anim.setDuration(self.DURACION)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def rebotar(self, region, foto, signo, al_terminar):
        self._preparar(region, foto, None, signo, al_terminar, True)
        self._anim.setDuration(self.DURACION_REBOTE)
        self._anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._anim.start()

    def _preparar(self, region, vieja, nueva, signo, al_terminar, rebote):
        self._vieja, self._nueva, self._signo, self._rebote, self._al_terminar = vieja, nueva, signo, rebote, al_terminar
        self._t = 0.0
        self.setGeometry(region)
        self.show()
        self.raise_()

    def _mover(self, valor):
        self._t = float(valor)
        self.update()

    def _fin(self):
        self.hide()
        self._vieja = self._nueva = None
        alerta, self._al_terminar = self._al_terminar, None
        if alerta is not None:
            alerta()

    def wheelEvent(self, evento):
        # Los giros durante la animación cuentan como inercia: así el siguiente cambio espera una pausa
        self.parentWidget().pasar_por_rueda(evento)
        evento.accept()

    def paintEvent(self, evento):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(FONDO))
        if self._vieja is None:
            painter.end()
            return
        w, h = float(self.width()), float(self.height())

        def foto(pixmap, y):
            painter.drawPixmap(QRectF(0, y, w, h), pixmap, QRectF(0, 0, pixmap.width(), pixmap.height()))
        if self._rebote:
            foto(self._vieja, self._signo * 12 * sin(pi * self._t))
        elif self._nueva is None:
            foto(self._vieja, 0)
        else:
            foto(self._vieja, -self._signo * self._t * h)
            foto(self._nueva, self._signo * (1 - self._t) * h)
        painter.end()


class TabsVerticales(QTabWidget):
    """QTabWidget del Dashboard: cambia de pestaña deslizando el contenido hacia arriba o hacia abajo y acepta la rueda."""
    UMBRAL_RUEDA = 50
    PAUSA_INERCIA_MS = 120

    def __init__(self, parent=None):
        super().__init__(parent)
        self._capa = _CapaDeslizante(self)
        self._ocupado = False
        self._acum = 0.0
        self._ultimo_evento = 0.0
        self._espera_pausa = False
        self._fin_animacion = 0.0

    # ------------------------------------------------------------------ cambio con deslizamiento
    @staticmethod
    def _foto(modulo, region):
        return modulo.grab(region)

    def _region(self, modulo):
        calcular = getattr(modulo, 'region_deslizante', None)
        if calcular is None:
            return None
        region = calcular()
        return region if region.width() > 40 and region.height() > 40 else None

    def setCurrentIndex(self, indice):
        actual = self.currentIndex()
        modulo = self.currentWidget()
        if self._ocupado or indice == actual or indice < 0 or not self.isVisible() or modulo is None or self._region(modulo) is None:
            super().setCurrentIndex(indice)
            return
        region = self._region(modulo)
        vieja = self._foto(modulo, region)
        zona = QRect(modulo.mapTo(self, region.topLeft()), region.size())
        self._ocupado = True
        # La foto vieja queda quieta mientras la pestaña nueva se pinta con sus datos; la animación arranca
        # en el siguiente ciclo, cuando ya está armada
        self._capa.congelar(zona, vieja)
        self._fin_animacion = time.monotonic() * 1000 + _CapaDeslizante.DURACION + 100
        try:
            super().setCurrentIndex(indice)
            nuevo = self.currentWidget()
            copiar = getattr(nuevo, 'copiar_filtros_de', None)
            if copiar is not None:
                copiar(modulo)
            preparar = getattr(nuevo, 'preparar_deslizamiento', None)
            if preparar is not None:
                preparar()
        except Exception:
            self._capa.hide()
            self._ocupado = False
            raise
        QTimer.singleShot(0, lambda: self._arrancar(nuevo, region, zona, 1 if indice > actual else -1))

    def _arrancar(self, nuevo, region, zona, signo):
        if self.currentWidget() is not nuevo:
            self._capa.hide()
            self._ocupado = False
            return
        if nuevo.layout() is not None:
            nuevo.layout().activate()
        self._capa.deslizar(zona, self._capa._vieja, self._foto(nuevo, region), signo, self._liberar)
        self._fin_animacion = time.monotonic() * 1000 + _CapaDeslizante.DURACION

    def _liberar(self):
        self._ocupado = False

    # ------------------------------------------------------------------ rueda
    def pasar_por_rueda(self, evento):
        """Un giro = un cambio de pestaña. Se ignora lo que llega mientras dura la animación y la inercia del
        trackpad (hasta que haya una pausa). Devuelve True si el evento se atendió."""
        giro = evento.angleDelta().y()
        if giro == 0 or evento.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        ahora = time.monotonic() * 1000
        pausa = ahora - self._ultimo_evento
        self._ultimo_evento = ahora
        evento.accept()
        if self._ocupado:
            self._espera_pausa = True
            return True
        if self._espera_pausa:
            if ahora < self._fin_animacion or pausa < self.PAUSA_INERCIA_MS:
                return True
            self._espera_pausa = False
            self._acum = 0.0
        if pausa > 220:
            self._acum = 0.0
        self._acum -= giro
        if abs(self._acum) < self.UMBRAL_RUEDA:
            return True
        signo = 1 if self._acum > 0 else -1
        self._acum = 0.0
        self._espera_pausa = True
        destino = self.currentIndex() + signo
        if 0 <= destino < self.count():
            self.setCurrentIndex(destino)
        else:
            self._rebotar(signo)
        return True

    def _rebotar(self, signo):
        modulo = self.currentWidget()
        region = self._region(modulo) if modulo is not None else None
        if region is None or self._ocupado:
            return
        self._ocupado = True
        zona = QRect(modulo.mapTo(self, region.topLeft()), region.size())
        self._capa.rebotar(zona, self._foto(modulo, region), -signo, self._liberar)
        self._fin_animacion = time.monotonic() * 1000 + _CapaDeslizante.DURACION_REBOTE
