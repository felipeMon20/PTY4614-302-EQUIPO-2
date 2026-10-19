"""Estilo del menú lateral (basado en dashboard-v2.html). Solo
apariencia: la navegación sigue en main_window.py."""
from PyQt6.QtCore import Qt, QRectF, QPoint
from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QRadialGradient, QPen
from PyQt6.QtWidgets import QFrame, QPushButton

from src.ui.comercial_estilo import AnimacionHover
from src.theme import tema

ANCHO_EXPANDIDO = 264
ANCHO_COLAPSADO = 72
MARGEN_NAV = 14
INDICADOR_ACTIVO = QColor("#6AA6FF")
DEGRADADO_CLARO = ("#14305A", "#0C2244", "#081833")
DEGRADADO_OSCURO = ("#0E2142", "#091830", "#050F20")

QSS_MARCA = ("color: white; font-family: Georgia, 'Times New Roman', serif; font-size: 21px; "
             "font-weight: bold; letter-spacing: 9px; background: transparent;")
QSS_MARCA_MINI = "color: white; font-family: Georgia, serif; font-size: 24px; font-weight: bold; background: transparent;"
QSS_SUBTITULO = "color: #B8C6DE; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 12px; background: transparent;"
QSS_ETIQUETA = ("color: #8EA3C6; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 11px; font-weight: 600; "
                "letter-spacing: 1.5px; background: transparent;")
QSS_CABECERA = "QFrame#cabeceraSidebar { background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,20); }"
QSS_BOTON_PLEGAR = """
    QPushButton { background-color: rgba(255,255,255,20); border: 1px solid rgba(255,255,255,36); border-radius: 10px; }
    QPushButton:hover { background-color: rgba(255,255,255,46); }
"""


def qss_boton_menu(colapsado):
    # El fondo lo pinta BotonMenuSidebar; el QSS solo pone texto y relleno
    alineacion = "text-align: center; padding: 0px;" if colapsado else "text-align: left; padding: 0px 16px;"
    return f"""
        QPushButton {{
            background: transparent; border: none; color: #D5DFF0;
            font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 14px; font-weight: 500;
            min-height: 46px; max-height: 46px; {alineacion}
        }}
        QPushButton:hover {{ color: #FFFFFF; background: transparent; }}
        QPushButton:checked {{ color: #FFFFFF; font-weight: 700; background: transparent; }}
        QPushButton:disabled {{ color: rgba(213,223,240,110); }}
    """


class FondoSidebar(QFrame):
    """Degradado azul marino con dos brillos (azul arriba a la izquierda,
    turquesa abajo a la derecha) y la barra del ítem activo en el borde."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._botones = []

    def registrar_botones(self, botones):
        self._botones = list(botones)
        for btn in self._botones:
            btn.toggled.connect(lambda _c: self.update())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        base = QLinearGradient(r.topLeft(), r.bottomLeft())
        for posicion, color in zip((0.0, 0.55, 1.0), DEGRADADO_OSCURO if tema.es_oscuro() else DEGRADADO_CLARO):
            base.setColorAt(posicion, QColor(color))
        p.fillRect(r, base)
        for centro, radio, color in ((r.topLeft(), 360.0, QColor(59, 130, 246, 77)),
                                     (r.bottomRight(), 320.0, QColor(20, 184, 166, 41))):
            brillo = QRadialGradient(centro, radio)
            brillo.setColorAt(0.0, color)
            brillo.setColorAt(0.7, QColor(color.red(), color.green(), color.blue(), 0))
            p.fillRect(r, brillo)

        activo = next((b for b in self._botones if b.isChecked() and b.isVisible()), None)
        if activo is not None:
            arriba = activo.mapTo(self, QPoint(0, 0)).y()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(INDICADOR_ACTIVO)
            p.drawRoundedRect(QRectF(-4, arriba + 10, 8, activo.height() - 20), 4, 4)
        p.end()


class BotonMenuSidebar(QPushButton):
    """Ítem del menú: hover animado (fondo blanco translúcido) y, si está
    marcado, degradado azul con borde claro como `nav a.active` del HTML."""

    def __init__(self, texto=""):
        super().__init__(texto)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = AnimacionHover(self, lambda _v: self.update())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isChecked():
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            grad.setColorAt(0.0, QColor(59, 130, 246, 140))
            grad.setColorAt(1.0, QColor(59, 130, 246, 46))
            p.setBrush(grad)
            p.setPen(QPen(QColor(147, 197, 253, 72), 1))
            p.drawRoundedRect(rect, 12, 12)
        elif self.isEnabled() and self._hover.progreso > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, round(20 * self._hover.progreso)))
            p.drawRoundedRect(rect, 12, 12)
        p.end()
        super().paintEvent(event)
