"""Colores, formatos y piezas pequeñas compartidas por los gráficos del Dashboard."""
import qtawesome as qta
from PyQt6 import sip
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget
from src.theme import tema
from src.theme.colors import FONDO_APP


FONDO = FONDO_APP


TINTA = "#0F1B33"


APAGADO = "#5B6980"


LINEA = "#E3E8F0"


MARINO = "#1B2B4E"


AZUL = MARINO


AZUL_SUAVE = "#E3E8F1"


TONO_MEDIO = "#2F4A7A"


TONO_SUAVE = "#4A6491"


TONO_CLARO = "#7088AE"


ROJO = "#D1453B"


ROJO_TEXTO = "#C2362D"


ROJO_SUAVE = "#FDE5E5"


COLORES_ESTADO = {"DESCONECTADO": ROJO, "ACTIVANDO": TONO_SUAVE, "NO ENTREGADO": TONO_MEDIO, "SIN FLOTA": TONO_CLARO,
                  "OTROS": "#A9B6CC"}


# Rellenos de gráficos en modo oscuro: los azules marino se vuelven visibles sobre el fondo oscuro
_RELLENO_OSCURO = {MARINO: "#5B8CF0", TONO_MEDIO: "#4672C9", TONO_SUAVE: "#3F5F9E", TONO_CLARO: "#3A4C74", ROJO: "#E2574C"}


_BOTON_OSCURO = "#3A66D4"


def _relleno(color):
    """Color de una barra o figura: el mismo en claro, más visible en oscuro."""
    if tema.es_oscuro():
        return QColor(_RELLENO_OSCURO.get(str(QColor(color).name()).upper()) or tema.fondo(color))
    return QColor(color)


def _con_tema(widget):
    """Repinta el widget al cambiar el tema."""
    def _repintar_widget(*_):
        if not sip.isdeleted(widget):
            widget.refrescar_tema() if hasattr(widget, 'refrescar_tema') else widget.update()
    tema.GestorTema.instancia().tema_cambiado.connect(_repintar_widget)


def _fondo_boton(hover=False):
    """Fondo de los botones principales: marino en claro, azul más vivo en oscuro."""
    if tema.es_oscuro():
        return "#4F7BE5" if hover else _BOTON_OSCURO
    return TONO_MEDIO if hover else MARINO


def _estilo_principal(radio, padding, fuente):
    return (f"QPushButton {{ background: {_fondo_boton()}; color: white; border: none; border-radius: {radio}px; "
            f"padding: {padding}; font-size: {fuente}px; font-weight: 700; }} "
            f"QPushButton:hover {{ background: {_fondo_boton(True)}; }}")


def _estilo_marca():
    return ("QCheckBox { color: #0F1B33; font-size: 12px; font-weight: 700; spacing: 6px; "
            "background: white; border: 1px solid #D9DEE8; border-radius: 9px; padding: 7px 10px; } "
            "QCheckBox:hover { border-color: #B9C6DA; } "
            "QCheckBox::indicator { width: 15px; height: 15px; border: 1.5px solid #9AA8C0; border-radius: 4px; background: white; } "
            f"QCheckBox::indicator:checked {{ background: {_fondo_boton()}; border-color: {_fondo_boton()}; }}")


class _Punto(QWidget):
    """Cuadrito de color de las leyendas."""
    def __init__(self, color, lado=9):
        super().__init__()
        self._color = color
        self.setFixedSize(lado, lado)
        _con_tema(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_relleno(self._color))
        painter.drawRoundedRect(QRectF(self.rect()), 2, 2)
        painter.end()


def _num(n):
    return f"{int(n):,}".replace(",", ".")


def _pct(fraccion):
    return f"{fraccion * 100:.1f}".replace(".", ",") + "%"


def _etiqueta(texto, estilo):
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"{estilo} background: transparent; border: none;")
    return lbl


def _icono_en_circulo(nombre, color, fondo, tam=38, lado_icono=15, redondo=False):
    lbl = QLabel()
    lbl.setFixedSize(tam, tam)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    radio = tam // 2 if redondo else 12
    lbl.setStyleSheet(f"background: {fondo}; border-radius: {radio}px; border: none;")

    def pintar_icono(*_):
        if not sip.isdeleted(lbl):
            lbl.setPixmap(qta.icon(nombre, color=_relleno(color).name()).pixmap(lado_icono, lado_icono))
    pintar_icono()
    tema.GestorTema.instancia().tema_cambiado.connect(pintar_icono)
    return lbl


def _leyenda(items):
    """Fila de cuadritos de color con su nombre."""
    caja = QWidget()
    caja.setStyleSheet("background: transparent;")
    fila = QHBoxLayout(caja)
    fila.setContentsMargins(0, 0, 0, 0)
    fila.setSpacing(12)
    for texto, color in items:
        fila.addWidget(_Punto(color))
        fila.addWidget(_etiqueta(texto, f"color: {APAGADO}; font-size: 11px;"))
    fila.addStretch()
    return caja


class _TarjetaAcento(QFrame):
    """Tarjeta blanca con una franja de color en el borde izquierdo."""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = color
        _con_tema(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        contorno = QPainterPath()
        contorno.addRoundedRect(rect, 14, 14)
        painter.fillPath(contorno, tema.fondo("#FFFFFF"))
        painter.save()
        painter.setClipPath(contorno)
        painter.fillRect(QRectF(0, 0, 3.5, self.height()), _relleno(self._color))
        painter.restore()
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(contorno)
        painter.end()


class BarraProporcion(QWidget):
    """Barra fina de proporción: uno o varios tramos de color sobre un fondo suave."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._tramos = []
        _con_tema(self)

    def set_tramos(self, tramos):
        self._tramos = [(max(0.0, min(1.0, f)), c) for f, c in tramos]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tema.fondo("#EDF0F6"))
        painter.drawRoundedRect(QRectF(self.rect()), 3, 3)
        ancho = self.width()
        x = 0.0
        for fraccion, color in self._tramos:
            if fraccion <= 0:
                continue
            w = max(3.0, ancho * fraccion)
            painter.setBrush(_relleno(color))
            painter.drawRoundedRect(QRectF(x, 0, min(w, ancho - x), self.height()), 3, 3)
            x += w + 1.5
        painter.end()
