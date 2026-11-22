"""Cabecera del menú lateral: marca VOLVO y un camión cuya cabina acompaña el borde del menú.

Todo se pinta según el ancho actual del menú, así que el camión avanza y retrocede junto con la animación
del ancho (sin un reloj propio) y sus ruedas giran según lo que recorre. Plegado queda solo la cabina."""
import os

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget

ANCHO_MIN = 72
ANCHO_MAX = 264
ANCHO_CAMION = 104
MARGEN_DER_MAX = 10
MARGEN_DER_MIN = 6
TOP_CAMION = 6
ANCHO_MARCA = 112
GIRO_RUEDAS_GRADOS = 540
# Ruedas sobre la imagen sin espejar: (izquierda, arriba, ancho) como fracción del ancho de la imagen
_RUEDAS = {"del": (0.1512, 0.7436, 0.1698), "tras": (0.7931, 0.7339, 0.1724)}


class CabeceraCamion(QWidget):
    def __init__(self, carpeta_assets, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._camion = QPixmap(os.path.join(carpeta_assets, 'camion_menu.png'))
        self._ruedas = {nombre: QPixmap(os.path.join(carpeta_assets, f'camion_rueda_{nombre}.png')) for nombre in _RUEDAS}
        self._marca = QPixmap(os.path.join(carpeta_assets, 'volvo_letras_blanco.png'))

    def _avance(self):
        """0 con el menú plegado, 1 desplegado."""
        return max(0.0, min(1.0, (self.width() - ANCHO_MIN) / (ANCHO_MAX - ANCHO_MIN)))

    def paintEvent(self, _evento):
        if self._camion.isNull():
            return
        avance = self._avance()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        # Con el menú abierto la marca aparece cuando el camión ya pasó
        opacidad = max(0.0, min(1.0, (avance - 0.55) / 0.4))
        if opacidad > 0:
            p.setOpacity(opacidad)
            self._pintar_marca(p)
            p.setOpacity(1.0)
        self._pintar_camion(p, avance)
        p.end()

    def _pintar_marca(self, p):
        if not self._marca.isNull():
            alto = ANCHO_MARCA * self._marca.height() / self._marca.width()
            p.drawPixmap(QRectF(22, 31, ANCHO_MARCA, alto), self._marca, QRectF(self._marca.rect()))
        fuente = QFont()
        fuente.setFamilies(['Inter', 'Segoe UI', 'Arial'])
        fuente.setPixelSize(8)
        fuente.setWeight(QFont.Weight.DemiBold)
        fuente.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.9)
        p.setFont(fuente)
        p.setPen(QColor('#8EA3C6'))
        p.drawText(QPointF(22, 56), "SISTEMA DE GESTIÓN")

    def _pintar_camion(self, p, avance):
        ancho = ANCHO_CAMION
        alto = ancho * self._camion.height() / self._camion.width()
        margen = MARGEN_DER_MIN + (MARGEN_DER_MAX - MARGEN_DER_MIN) * avance
        izquierda = self.width() - margen - ancho
        # La foto mira hacia la izquierda: se espeja para que avance hacia el borde del menú
        p.save()
        p.translate(izquierda + ancho, TOP_CAMION)
        p.scale(-1, 1)
        p.drawPixmap(QRectF(0, 0, ancho, alto), self._camion, QRectF(self._camion.rect()))
        p.restore()
        # Las ruedas giran lo que avanza el menú; una vuelta menos lenta que la real evita el efecto de rueda parada
        grados = (avance - 1) * GIRO_RUEDAS_GRADOS
        for nombre, (izq, arriba, fraccion) in _RUEDAS.items():
            sprite = self._ruedas[nombre]
            if sprite.isNull():
                continue
            lado = fraccion * ancho
            cx = izquierda + ancho - (izq + fraccion / 2) * ancho
            cy = TOP_CAMION + arriba * alto + lado / 2
            p.save()
            p.translate(cx, cy)
            p.rotate(grados)
            p.scale(-1, 1)
            p.drawPixmap(QRectF(-lado / 2, -lado / 2, lado, lado), sprite, QRectF(sprite.rect()))
            p.restore()
