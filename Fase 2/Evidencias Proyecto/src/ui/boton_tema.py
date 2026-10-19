"""Interruptor sol/luna de la barra superior (modo claro/oscuro, 30-09-2026).
Se dibuja entero en paintEvent: cielo de día con nubes que pasa a noche con
estrellas, y el sol rueda hasta volverse luna."""
import math

from PyQt6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve, QSize, QElapsedTimer
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QRadialGradient, QPainterPath, QPen
from PyQt6.QtWidgets import QAbstractButton

ANCHO = 62
ALTO = 32
DURACION_MS = 340
# Tiempo mínimo entre cambios de tema para evitar spam de clics
ESPERA_MS = 400

_CIELO_DIA = (QColor('#9BD3FF'), QColor('#3B82F6'))
_CIELO_NOCHE = (QColor('#1E1B4B'), QColor('#0B1226'))
_SOL = (QColor('#FFE89A'), QColor('#FBBF24'))
_LUNA = (QColor('#F8FAFC'), QColor('#D9E1EE'))
_CRATERES = ((-4.5, -3.0, 3.0), (2.0, 3.5, 2.0), (2.5, -5.0, 1.5))
_ESTRELLAS = ((13, 9, 1.1), (21, 20, 1.5), (31, 11, 1.0), (40, 22, 0.9))


def _mezcla(a, b, t):
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class BotonTema(QAbstractButton):
    """checked = modo oscuro. toggled(bool) avisa el cambio; la animación del
    propio botón la maneja esta clase."""

    def __init__(self, oscuro=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(oscuro)
        self.setFixedSize(ANCHO, ALTO)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._progreso = 1.0 if oscuro else 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DURACION_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.valueChanged.connect(self._on_progreso)
        self.toggled.connect(self._animar)
        self._ultimo_cambio = QElapsedTimer()
        self._actualizar_tooltip()

    def sizeHint(self):
        return QSize(ANCHO, ALTO)

    def nextCheckState(self):
        if self._ultimo_cambio.isValid() and self._ultimo_cambio.elapsed() < ESPERA_MS:
            return
        self._ultimo_cambio.start()
        super().nextCheckState()

    def fijar_sin_animar(self, oscuro):
        self.blockSignals(True)
        self.setChecked(oscuro)
        self.blockSignals(False)
        self._anim.stop()
        self._progreso = 1.0 if oscuro else 0.0
        self._actualizar_tooltip()
        self.update()

    def reiniciar_animacion(self):
        """Vuelve a animar desde el estado anterior: el cambio de tema
        congela la UI un momento y la animación quedaría a medias."""
        self._progreso = 0.0 if self.isChecked() else 1.0
        # La espera cuenta desde que terminó de aplicarse el tema, no desde el clic
        self._ultimo_cambio.start()
        self._animar(self.isChecked())

    def _actualizar_tooltip(self):
        self.setToolTip("Cambiar a modo claro" if self.isChecked() else "Cambiar a modo oscuro")

    def _animar(self, oscuro):
        self._anim.stop()
        self._anim.setStartValue(self._progreso)
        self._anim.setEndValue(1.0 if oscuro else 0.0)
        self._anim.start()
        self._actualizar_tooltip()

    def _on_progreso(self, valor):
        self._progreso = float(valor)
        self.update()

    def paintEvent(self, event):
        t = self._progreso
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pista = QRectF(0.5, 0.5, ANCHO - 1, ALTO - 1)
        radio = pista.height() / 2

        forma = QPainterPath()
        forma.addRoundedRect(pista, radio, radio)
        degradado = QLinearGradient(pista.topLeft(), pista.bottomRight())
        degradado.setColorAt(0, _mezcla(_CIELO_DIA[0], _CIELO_NOCHE[0], t))
        degradado.setColorAt(1, _mezcla(_CIELO_DIA[1], _CIELO_NOCHE[1], t))
        p.fillPath(forma, degradado)
        p.save()
        p.setClipPath(forma)

        # Nubes que bajan y se desvanecen
        if t < 1:
            p.setPen(Qt.PenStyle.NoPen)
            for x, y, w, h, alfa in ((38, 9, 16, 6, 0.9), (31, 18, 12, 5, 0.75)):
                c = QColor(255, 255, 255)
                c.setAlphaF(alfa * (1 - t))
                p.setBrush(c)
                p.drawRoundedRect(QRectF(x, y + 22 * t, w, h), h / 2, h / 2)

        # Estrellas que aparecen en la segunda mitad
        brillo = max(0.0, min(1.0, (t - 0.25) / 0.75))
        if brillo > 0:
            p.setPen(Qt.PenStyle.NoPen)
            for x, y, r in _ESTRELLAS:
                c = QColor(255, 255, 255)
                c.setAlphaF(brillo)
                p.setBrush(c)
                p.drawEllipse(QPointF(x, y), r * brillo, r * brillo)
        p.restore()

        # Borde interior suave
        p.setPen(QPen(QColor(0, 0, 0, 40), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(pista, radio, radio)

        # Perilla: sol -> luna, rodando hacia la derecha
        r_perilla = 12.0
        centro = QPointF(4 + r_perilla + 30 * t, ALTO / 2)
        halo = _mezcla(QColor(255, 236, 150, 90), QColor(226, 232, 240, 30), t)
        if self.underMouse():
            halo.setAlpha(min(255, halo.alpha() + 50))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(centro, r_perilla + 3.5, r_perilla + 3.5)

        relleno = QRadialGradient(centro + QPointF(-3.5, -3.5), r_perilla * 1.4)
        relleno.setColorAt(0, _mezcla(_SOL[0], _LUNA[0], t))
        relleno.setColorAt(0.7, _mezcla(_SOL[1], _LUNA[1], t))
        p.setBrush(relleno)
        p.drawEllipse(centro, r_perilla, r_perilla)

        aparicion = max(0.0, min(1.0, (t - 0.35) / 0.65))
        if aparicion > 0:
            giro = math.radians(-200 * t)
            crater = QColor('#B8C2D6')
            crater.setAlphaF(aparicion)
            p.setBrush(crater)
            for dx, dy, r in _CRATERES:
                x = dx * math.cos(giro) - dy * math.sin(giro)
                y = dx * math.sin(giro) + dy * math.cos(giro)
                p.drawEllipse(centro + QPointF(x, y), r, r)

        if self.hasFocus():
            p.setPen(QPen(QColor('#6EA0FF'), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(pista.adjusted(-0.5, -0.5, 0.5, 0.5), radio, radio)
        p.end()
