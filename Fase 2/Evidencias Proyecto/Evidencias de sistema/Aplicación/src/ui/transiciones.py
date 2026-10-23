import math

from PyQt6.QtCore import Qt, QVariantAnimation, QEasingCurve, QAbstractAnimation, QPointF, QRectF
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QBrush
from PyQt6.QtWidgets import QWidget, QStackedWidget

from src.theme import tema


def ms_restantes_animacion(anim):
    if anim is None or anim.state() != QAbstractAnimation.State.Running:
        return 0
    return max(0, anim.duration() - anim.currentTime())


class TransicionFundidoSubida(QWidget):
    """Capa sobre un contenedor (workspace, contenido de un QTabWidget o un
    QStackedWidget interno) al cambiar de pantalla: la foto de la anterior se
    desvanece y la nueva (real, no una foto) aparece subiendo unos píxeles.
    Solo se mueve el contenedor, sin relayouts."""
    DURACION_MS = 260
    DESPLAZAMIENTO_PX = 14

    def __init__(self, parent, contenedor, color_fondo=None):
        super().__init__(parent)
        self._contenedor = contenedor
        self._fondo = QColor(color_fondo) if color_fondo else None
        self._foto = None
        self._pos_final = None
        self._progreso = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(self.DURACION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_progreso)
        self._anim.finished.connect(self.terminar)

    def iniciar(self, foto_anterior):
        self.terminar()
        self._foto = foto_anterior
        self._pos_final = self._contenedor.pos()
        self.setGeometry(self._contenedor.geometry())
        self.raise_()
        self.show()
        self._on_progreso(0.0)
        self._anim.start()

    def ms_restantes(self):
        return ms_restantes_animacion(self._anim)

    def terminar(self):
        if self._anim.state() == QVariantAnimation.State.Running:
            self._anim.stop()
        if self._pos_final is not None:
            self._contenedor.move(self._pos_final)
            self._pos_final = None
        self._foto = None
        self.hide()

    def _on_progreso(self, valor):
        if self._pos_final is None:
            return
        self._progreso = float(valor)
        desplazamiento = round(self.DESPLAZAMIENTO_PX * (1.0 - self._progreso))
        self._contenedor.move(self._pos_final.x(), self._pos_final.y() + desplazamiento)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._fondo is not None:
            fondo = tema.fondo(self._fondo)
            fondo.setAlphaF(max(0.0, 1.0 - self._progreso))
            painter.fillRect(self.rect(), fondo)
        # La pantalla anterior se apaga en el primer 60 % de la animación
        opacidad_anterior = max(0.0, 1.0 - self._progreso / 0.6)
        if self._foto is not None and opacidad_anterior > 0:
            painter.setOpacity(opacidad_anterior)
            painter.drawPixmap(0, 0, self._foto)
        painter.end()


class TransicionCirculo(QWidget):
    """Cambio de tema: la foto de la ventana con el tema anterior tapa todo
    mientras se aplica el nuevo, y luego se abre un círculo desde el botón
    que deja ver la app ya cambiada."""
    DURACION_MS = 200

    def __init__(self, parent):
        super().__init__(parent)
        self._foto = None
        self._centro = QPointF()
        self._radio = 0.0
        self._radio_max = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(self.DURACION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_progreso)
        self._anim.finished.connect(self.terminar)

    def iniciar(self, contenedor, centro, aplicar_cambio):
        """`contenedor`: widget a fotografiar (mismo padre que esta capa).
        `centro`: punto de origen en coordenadas de `contenedor`.
        `aplicar_cambio`: función que cambia el tema bajo la foto."""
        self.terminar()
        self._foto = contenedor.grab()
        self.setGeometry(contenedor.geometry())
        self._centro = QPointF(centro)
        ancho, alto = self.width(), self.height()
        self._radio_max = math.hypot(max(centro.x(), ancho - centro.x()), max(centro.y(), alto - centro.y()))
        self._radio = 0.0
        self.raise_()
        self.show()
        self.repaint()
        aplicar_cambio()
        self._anim.start()

    def terminar(self):
        if self._anim.state() == QVariantAnimation.State.Running:
            self._anim.stop()
        self._foto = None
        self.hide()

    def _on_progreso(self, valor):
        self._radio = self._radio_max * float(valor)
        self.update()

    def paintEvent(self, event):
        if self._foto is None:
            return
        tapa = QPainterPath()
        tapa.addRect(QRectF(self.rect()))
        if self._radio > 0:
            hueco = QPainterPath()
            hueco.addEllipse(self._centro, self._radio, self._radio)
            tapa = tapa.subtracted(hueco)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(tapa, QBrush(self._foto))
        painter.end()


def instalar_transicion_pestanas(tabs):
    """Aplica TransicionFundidoSubida al cambiar de pestaña con el mouse."""
    if tabs.property("transicion_instalada"):
        return
    stack = tabs.findChild(QStackedWidget, options=Qt.FindChildOption.FindDirectChildrenOnly)
    if stack is None:
        return
    transicion = TransicionFundidoSubida(tabs, stack)
    pendiente = {}

    # tabBarClicked se emite antes del cambio: es el momento de tomar la foto
    def _antes(idx):
        pendiente.clear()
        if idx >= 0 and idx != tabs.currentIndex() and stack.isVisible():
            transicion.terminar()
            pendiente[idx] = stack.grab()

    def _despues(idx):
        foto = pendiente.pop(idx, None)
        pendiente.clear()
        if foto is not None:
            transicion.iniciar(foto)

    tabs.tabBar().tabBarClicked.connect(_antes)
    tabs.currentChanged.connect(_despues)
    tabs.setProperty("transicion_instalada", True)
    tabs._transicion_pestanas = transicion


def cambiar_pagina_animada(stack, pagina):
    """setCurrentWidget con transición; si la página ya está activa o el
    stack no se ve, cambia sin animar."""
    if stack.currentWidget() is pagina or not stack.isVisible() or stack.parentWidget() is None:
        stack.setCurrentWidget(pagina)
        return
    transicion = getattr(stack, "_transicion_pagina", None)
    if transicion is None:
        transicion = TransicionFundidoSubida(stack.parentWidget(), stack)
        stack._transicion_pagina = transicion
    transicion.terminar()
    foto = stack.grab()
    stack.setCurrentWidget(pagina)
    transicion.iniciar(foto)
