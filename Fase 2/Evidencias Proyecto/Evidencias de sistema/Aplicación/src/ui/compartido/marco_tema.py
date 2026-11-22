"""Marco pintado a mano (fondo, borde y esquinas redondeadas) que sigue el tema sin hoja de estilo.

Un QFrame con setStyleSheet obliga a Qt a repolarizar todo su subárbol cada vez que cambia
el tema; este marco solo se repinta, y el gestor de temas puede saltárselo (ver
GestorTema._es_transparente).
"""
from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame

from src.theme import tema

PROP_TRANSPARENTE_FORZADO = tema.PROP_TRANSPARENTE_FORZADO


def trayecto_redondeado(rect, radios):
    """Rectángulo con radio propio por esquina: (arriba-izq, arriba-der, abajo-der, abajo-izq)."""
    tl, tr, br, bl = radios
    p = QPainterPath()
    p.moveTo(rect.left() + tl, rect.top())
    p.lineTo(rect.right() - tr, rect.top())
    if tr:
        p.arcTo(rect.right() - 2 * tr, rect.top(), 2 * tr, 2 * tr, 90, -90)
    p.lineTo(rect.right(), rect.bottom() - br)
    if br:
        p.arcTo(rect.right() - 2 * br, rect.bottom() - 2 * br, 2 * br, 2 * br, 0, -90)
    p.lineTo(rect.left() + bl, rect.bottom())
    if bl:
        p.arcTo(rect.left(), rect.bottom() - 2 * bl, 2 * bl, 2 * bl, -90, -90)
    p.lineTo(rect.left(), rect.top() + tl)
    if tl:
        p.arcTo(rect.left(), rect.top(), 2 * tl, 2 * tl, 180, -90)
    p.closeSubpath()
    return p


class MarcoTema(QFrame):
    def __init__(self, fondo, borde=None, grosor=0, radio=0, radios=None, parent=None):
        super().__init__(parent)
        self._fondo = fondo
        self._borde = borde
        self._grosor = grosor if borde else 0
        self._radios = tuple(radios) if radios else (radio,) * 4
        self.setProperty(PROP_TRANSPARENTE_FORZADO, True)
        if self._grosor:
            # Reserva el ancho del borde para el contenido, como hace la hoja de estilo
            self.setFrameShape(QFrame.Shape.Box)
            self.setLineWidth(self._grosor)
            self.setMidLineWidth(0)
        tema.GestorTema.instancia().tema_cambiado.connect(self._al_cambiar_tema)

    def _al_cambiar_tema(self, *_):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        exterior = trayecto_redondeado(rect, self._radios)
        p.fillPath(exterior, QBrush(tema.fondo(self._fondo)))
        if self._grosor:
            g = self._grosor
            # Trazo centrado en el medio del borde, igual que dibuja Qt los bordes de las hojas de estilo
            medio = rect.adjusted(g / 2, g / 2, -g / 2, -g / 2)
            trazo = trayecto_redondeado(medio, tuple(max(0.0, r - g / 2) for r in self._radios))
            p.setPen(QPen(tema.fondo(self._borde), g))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(trazo)
        p.end()
