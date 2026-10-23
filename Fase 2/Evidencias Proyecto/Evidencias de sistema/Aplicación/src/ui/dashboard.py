"""Dashboard "Gestión del negocio" de Volvo Connect: foto actual de la flota,
comparativo mes a mes, unidades vendidas contra la meta, conexión por servicio
y por ejecutivo, calculados desde el Registro Maestro."""
import logging
import math
from datetime import date

import qtawesome as qta
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QObject, QSize, QThread, QTimer, QVariantAnimation, Qt, QRectF, QPropertyAnimation, QEasingCurve, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QApplication, QListWidgetItem, QButtonGroup, QToolTip, QCheckBox, QComboBox, QFrame, QLineEdit, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel,
                             QListWidget, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from src.core.data_manager import DataManager
from src.ui.comercial_estilo import ComboTarjeta
from src.ui.esqueleto_carga import EsqueletoCarga
from src.services import dashboard_services as servicio
from src.services import metas_service
from src.theme import tema

FONDO = "#F3F5F9"
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


class _GraficoBase(QWidget):
    """Lo común de los gráficos pintados a mano: fuente y colores sobre tarjeta blanca."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._datos = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        _con_tema(self)

    def set_datos(self, datos):
        self._datos = datos
        self.update()

    def _fuente(self, px, negrita=False):
        f = QFont(self.font())
        f.setPixelSize(px)
        f.setBold(negrita)
        return f

    @staticmethod
    def _texto(painter, rect, alineacion, texto, color):
        painter.setPen(tema.texto(color))
        painter.drawText(rect, alineacion | Qt.AlignmentFlag.AlignVCenter, texto)

    @staticmethod
    def _barra(painter, rect, color, radio=6):
        ruta = QPainterPath()
        ruta.addRoundedRect(rect, radio, radio)
        painter.fillPath(ruta, _relleno(color))


class GraficoMesAMes(_GraficoBase):
    """Una fila por mes (el más nuevo arriba): al centro los que se conectaron (izquierda) y los
    que se desconectaron (derecha), con el mes escrito a ambos lados."""
    ALTO_FILA = 28
    ALTO_CABECERA = 24
    ANCHO_ETIQUETA = 126
    ANCHO_NETO = 0

    def set_datos(self, datos):
        super().set_datos(datos)
        self.setMinimumHeight(self.ALTO_CABECERA + max(1, len(datos)) * self.ALTO_FILA)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._datos:
            painter.end()
            return
        izq = Qt.AlignmentFlag.AlignLeft
        der = Qt.AlignmentFlag.AlignRight
        centro_a = Qt.AlignmentFlag.AlignHCenter
        ancho_col = self.ANCHO_ETIQUETA + self.ANCHO_NETO
        x0 = 16.0
        zona = max(200.0, self.width() - 2 * ancho_col - 48 - 2 * x0)
        x_centro = x0 + ancho_col + 24 + zona / 2
        x_der = x_centro + zona / 2 + 24
        largo_max = zona / 2 - 46
        maximo = max(1, max(max(d['vendidas'], d['bajas']) for d in self._datos))
        painter.setFont(self._fuente(10, True))
        self._texto(painter, QRectF(x0, 0, ancho_col, self.ALTO_CABECERA), izq, "MES", APAGADO)
        self._texto(painter, QRectF(x0 + ancho_col + 24, 0, zona / 2 - 10, self.ALTO_CABECERA), der, "◀ SE CONECTARON", MARINO)
        self._texto(painter, QRectF(x_centro + 10, 0, zona / 2 - 10, self.ALTO_CABECERA), izq, "SE DESCONECTARON ▶", ROJO_TEXTO)
        self._texto(painter, QRectF(x_der, 0, ancho_col, self.ALTO_CABECERA), der, "MES", APAGADO)
        painter.setPen(QPen(tema.fondo("#9AA8C0"), 1))
        painter.drawLine(int(x_centro), self.ALTO_CABECERA, int(x_centro), self.height())
        for i, d in enumerate(self._datos):
            y = self.ALTO_CABECERA + i * self.ALTO_FILA
            alto = self.ALTO_FILA
            painter.setFont(self._fuente(12, True))
            self._texto(painter, QRectF(x0, y, self.ANCHO_ETIQUETA, alto), izq, d['etiqueta'], MARINO)
            self._texto(painter, QRectF(x_der, y, self.ANCHO_ETIQUETA, alto), der, d['etiqueta'], MARINO)
            largo_izq = max(3.0 if d['vendidas'] else 0.0, d['vendidas'] / maximo * largo_max)
            largo_der = max(3.0 if d['bajas'] else 0.0, d['bajas'] / maximo * largo_max)
            barra_y = y + (alto - 14) / 2
            painter.setFont(self._fuente(11, True))
            if largo_izq:
                self._barra(painter, QRectF(x_centro - 3 - largo_izq, barra_y, largo_izq, 14), MARINO, 7)
            self._texto(painter, QRectF(x_centro - 3 - largo_izq - 44, y, 40, alto), der, _num(d['vendidas']), MARINO)
            if largo_der:
                self._barra(painter, QRectF(x_centro + 3, barra_y, largo_der, 14), ROJO, 7)
            self._texto(painter, QRectF(x_centro + 3 + largo_der + 4, y, 40, alto), izq, _num(d['bajas']), ROJO_TEXTO)
        painter.end()


class _DetalleMes(QWidget):
    """Tarjeta flotante con los clientes de una columna del gráfico de ventas: razón social
    (cortada si es larga) y, a su derecha, conectados, activando, desconectados y total.
    Aparece con un fundido y un deslizamiento, y sus filas entran una tras otra."""
    ANCHO_NOMBRE = 190
    ANCHO_COL = 54
    ALTO_FILA = 26
    MARGEN = 10
    PAD = 16
    ALTO_CABECERA = 62

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._titulo = ""
        self._detalle = {'filas': [], 'otros': 0, 'total': 0}
        self._rev = 1.0
        self._aparecer = QPropertyAnimation(self, b"windowOpacity", self)
        self._aparecer.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._aparecer.finished.connect(self._al_terminar_fundido)
        self._deslizar = QPropertyAnimation(self, b"pos", self)
        self._deslizar.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._entrada = QVariantAnimation(self)
        self._entrada.setStartValue(0.0)
        self._entrada.setEndValue(1.0)
        self._entrada.setDuration(420)
        self._entrada.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._entrada.valueChanged.connect(self._mover_entrada)

    def _mover_entrada(self, valor):
        self._rev = float(valor)
        self.update()

    def _al_terminar_fundido(self):
        if self.windowOpacity() < 0.02:
            self.hide()

    def _tamano(self):
        filas = len(self._detalle['filas'])
        alto = (2 * self.MARGEN + self.ALTO_CABECERA + 24 + filas * self.ALTO_FILA
                + (24 if self._detalle['otros'] else 0) + self.PAD)
        ancho = 2 * self.MARGEN + 2 * self.PAD + self.ANCHO_NOMBRE + 4 * self.ANCHO_COL
        return ancho, alto

    def mostrar(self, titulo, detalle, destino, desde_derecha=True):
        """Muestra la tarjeta con `destino` como esquina superior izquierda de la ventana."""
        self._titulo, self._detalle = titulo, detalle
        ancho, alto = self._tamano()
        self.resize(ancho, alto)
        visible = self.isVisible() and self.windowOpacity() > 0.05
        self._aparecer.stop()
        self._deslizar.stop()
        if not visible:
            salto = -14 if desde_derecha else 14
            self.move(destino + QPoint(salto, 0))
            self.setWindowOpacity(0.0)
            self.show()
            self._aparecer.setDuration(200)
            self._deslizar.setDuration(260)
        else:
            self._aparecer.setDuration(120)
            self._deslizar.setDuration(200)
        self._aparecer.setStartValue(self.windowOpacity())
        self._aparecer.setEndValue(1.0)
        self._deslizar.setStartValue(self.pos())
        self._deslizar.setEndValue(destino)
        self._aparecer.start()
        self._deslizar.start()
        self._entrada.stop()
        self._entrada.start()
        self.update()

    def ocultar(self):
        if not self.isVisible():
            return
        self._deslizar.stop()
        self._aparecer.stop()
        self._aparecer.setDuration(130)
        self._aparecer.setStartValue(self.windowOpacity())
        self._aparecer.setEndValue(0.0)
        self._aparecer.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.MARGEN
        caja = QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)
        for i, opacidad in enumerate((0.05, 0.07, 0.09)):
            sombra = QPainterPath()
            sombra.addRoundedRect(caja.adjusted(-(3 - i), -(3 - i) + 3, 3 - i, 3 - i + 3), 18, 18)
            painter.fillPath(sombra, QColor(15, 27, 51, int(255 * opacidad)))
        contorno = QPainterPath()
        contorno.addRoundedRect(caja, 16, 16)
        painter.fillPath(contorno, tema.fondo("#FFFFFF"))
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.drawPath(contorno)

        fuente = QFont(self.font())
        fuente.setPixelSize(12)
        x0 = caja.left() + self.PAD
        x_cols = x0 + self.ANCHO_NOMBRE
        izq = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        der = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        y = caja.top() + 14
        fuente.setBold(True)
        fuente.setPixelSize(15)
        painter.setFont(fuente)
        painter.setPen(tema.texto(TINTA))
        painter.drawText(QRectF(x0, y, caja.width() - 2 * self.PAD, 22), izq, self._titulo)
        fuente.setBold(False)
        fuente.setPixelSize(11)
        painter.setFont(fuente)
        painter.setPen(tema.texto(APAGADO))
        painter.drawText(QRectF(x0, y + 22, caja.width() - 2 * self.PAD, 18), izq,
                         f"{_num(self._detalle['total'])} unidades vendidas, por cliente")
        y = caja.top() + self.ALTO_CABECERA
        fuente.setBold(True)
        fuente.setPixelSize(10)
        painter.setFont(fuente)
        encabezados = (("Conect.", MARINO), ("Activ.", TONO_SUAVE), ("Desc.", ROJO_TEXTO), ("Total", TINTA))
        for j, (texto, color) in enumerate(encabezados):
            painter.setPen(tema.texto(color))
            painter.drawText(QRectF(x_cols + j * self.ANCHO_COL, y, self.ANCHO_COL, 20), der, texto)
        y += 22
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.drawLine(int(x0), int(y), int(caja.right() - self.PAD), int(y))
        y += 2
        for i, fila in enumerate(self._detalle['filas']):
            alfa = max(0.0, min(1.0, (self._rev - i * 0.05) / 0.55))
            painter.setOpacity(alfa)
            desplazo = (1.0 - alfa) * 8
            ry = y + i * self.ALTO_FILA + desplazo
            fuente.setBold(True)
            fuente.setPixelSize(12)
            painter.setFont(fuente)
            corto = QFontMetrics(fuente).elidedText(fila['nombre'], Qt.TextElideMode.ElideRight, self.ANCHO_NOMBRE - 10)
            painter.setPen(tema.texto(TINTA))
            painter.drawText(QRectF(x0, ry, self.ANCHO_NOMBRE - 6, self.ALTO_FILA), izq, corto)
            fuente.setBold(False)
            painter.setFont(fuente)
            valores = (('conectadas', MARINO), ('activando', TONO_SUAVE), ('desconectadas', ROJO_TEXTO))
            for j, (clave, color) in enumerate(valores):
                painter.setPen(tema.texto(color if fila[clave] else "#B5BFD0"))
                painter.drawText(QRectF(x_cols + j * self.ANCHO_COL, ry, self.ANCHO_COL, self.ALTO_FILA), der, _num(fila[clave]))
            fuente.setBold(True)
            painter.setFont(fuente)
            painter.setPen(tema.texto(TINTA))
            painter.drawText(QRectF(x_cols + 3 * self.ANCHO_COL, ry, self.ANCHO_COL, self.ALTO_FILA), der, _num(fila['total']))
        if self._detalle['otros']:
            painter.setOpacity(max(0.0, min(1.0, (self._rev - 0.4) / 0.6)))
            fuente.setBold(False)
            fuente.setPixelSize(11)
            painter.setFont(fuente)
            painter.setPen(tema.texto(APAGADO))
            ry = y + len(self._detalle['filas']) * self.ALTO_FILA + 2
            painter.drawText(QRectF(x0, ry, caja.width() - 2 * self.PAD, 20), izq,
                             f"y {_num(self._detalle['otros'])} clientes más")
        painter.end()


class GraficoMetas(_GraficoBase):
    """Columnas de unidades vendidas por mes: lo oscuro ya está conectado, lo
    claro aún no. La marca punteada es la meta de ese mes. Al pasar el mouse por una
    columna aparece la tarjeta con los clientes de ese mes."""
    ALTO_PIE = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.detalle_mes = None
        self._tarjeta = None
        self._i_hover = -1
        self._i_foco = -1
        self._foco = 0.0
        self._anim_foco = QVariantAnimation(self)
        self._anim_foco.setDuration(180)
        self._anim_foco.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_foco.valueChanged.connect(self._mover_foco)
        self._k = None
        self._anim_k = QVariantAnimation(self)
        self._anim_k.setDuration(320)
        self._anim_k.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim_k.valueChanged.connect(self._mover_k)

    def _mover_k(self, valor):
        self._k = float(valor)
        self.update()

    def set_visibles(self, cantidad, animado=False):
        """Cuántos meses se ven (los más recientes); al cambiar, las columnas se
        reacomodan y aparecen o se desvanecen las más antiguas."""
        cantidad = float(max(1, min(cantidad, len(self._datos) or cantidad)))
        self._anim_k.stop()
        if animado and self._k and self._k != cantidad:
            self._anim_k.setStartValue(self._k)
            self._anim_k.setEndValue(cantidad)
            self._anim_k.start()
        else:
            self._k = cantidad
            self.update()

    def _mover_foco(self, valor):
        self._foco = float(valor)
        self.update()

    def _geometria(self):
        n = len(self._datos)
        k = min(max(self._k if self._k else float(n), 1.0), float(n))
        cantidad = min(n, math.ceil(k))
        visibles = self._datos[n - cantidad:]
        arriba = 22
        area_h = self.height() - arriba - self.ALTO_PIE
        ancho_col = self.width() / k
        pesos = [1.0 if (cantidad - i) <= k else k - (cantidad - 1) for i in range(cantidad)]
        tope = max(1, max(max(d['vendidas'], d.get('meta') or 0) * p for d, p in zip(visibles, pesos)))
        return visibles, pesos, cantidad, arriba, area_h, ancho_col, tope

    def _columna_en(self, pos):
        """(índice entre los visibles, rectángulo de su barra) bajo `pos`, o (-1, None)."""
        if not self._datos:
            return -1, None
        visibles, pesos, cantidad, arriba, area_h, ancho_col, tope = self._geometria()
        i = int((pos.x() - (self.width() - cantidad * ancho_col)) // ancho_col)
        if not 0 <= i < cantidad or pesos[i] < 0.6 or not visibles[i]['vendidas']:
            return -1, None
        ancho_barra = ancho_col * 0.6
        x = self.width() - (cantidad - i) * ancho_col
        alto = area_h * visibles[i]['vendidas'] / tope
        base = arriba + area_h
        rect = QRectF(x + (ancho_col - ancho_barra) / 2, base - alto, ancho_barra, alto)
        return (i, rect) if rect.adjusted(-4, -4, 4, 4).contains(pos) else (-1, None)

    def _cambiar_foco(self, indice):
        self._anim_foco.stop()
        self._anim_foco.setStartValue(self._foco)
        self._anim_foco.setEndValue(1.0 if indice >= 0 else 0.0)
        self._anim_foco.start()

    def mouseMoveEvent(self, event):
        i, rect = self._columna_en(event.position())
        if i == self._i_hover:
            return
        if i < 0:
            self._soltar_columna()
            return
        entraba = self._i_hover < 0
        self._i_hover = self._i_foco = i
        if entraba:
            self._cambiar_foco(i)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mostrar_detalle(i, rect)

    def _mostrar_detalle(self, i, rect):
        if self.detalle_mes is None:
            return
        d = self._geometria()[0][i]
        detalle = self.detalle_mes(d.get('periodo'))
        if not detalle or not detalle['filas']:
            if self._tarjeta is not None:
                self._tarjeta.ocultar()
            return
        if self._tarjeta is None:
            self._tarjeta = _DetalleMes()
        periodo = d.get('periodo')
        titulo = f"{servicio.MESES[periodo.month - 1]} {periodo.year}" if periodo is not None else d['etiqueta']
        self._tarjeta._detalle = detalle
        ancho, alto = self._tarjeta._tamano()
        pantalla = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        derecha = self.mapToGlobal(QPoint(int(rect.right()) + 6, 0)).x() - _DetalleMes.MARGEN
        izquierda = self.mapToGlobal(QPoint(int(rect.left()) - 6, 0)).x() - ancho + _DetalleMes.MARGEN
        a_la_derecha = derecha + ancho <= pantalla.right()
        x = derecha if a_la_derecha else izquierda
        y = self.mapToGlobal(QPoint(0, int(rect.top() + rect.height() / 2))).y() - alto // 2
        y = max(pantalla.top() + 8, min(y, pantalla.bottom() - alto - 8))
        self._tarjeta.mostrar(titulo, detalle, QPoint(x, y), desde_derecha=a_la_derecha)

    def _soltar_columna(self):
        if self._i_hover < 0:
            return
        self._i_hover = -1
        self._cambiar_foco(-1)
        self.unsetCursor()
        if self._tarjeta is not None:
            self._tarjeta.ocultar()

    def leaveEvent(self, event):
        self._soltar_columna()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._soltar_columna()
        super().hideEvent(event)

    def wheelEvent(self, event):
        self._soltar_columna()
        event.ignore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._datos:
            painter.end()
            return
        centro = Qt.AlignmentFlag.AlignHCenter
        visibles, pesos, cantidad, arriba, area_h, ancho_col, tope = self._geometria()
        painter.setPen(QPen(tema.fondo("#D2D9E6"), 1))
        painter.drawLine(0, arriba + area_h, self.width(), arriba + area_h)
        for i, (d, peso) in enumerate(zip(visibles, pesos)):
            atenuar = 0.5 * self._foco if i != self._i_foco else 0.0
            painter.setOpacity(peso * (1.0 - atenuar))
            x = self.width() - (cantidad - i) * ancho_col
            ancho_barra = ancho_col * 0.6
            alto_total = area_h * d['vendidas'] / tope
            barra_x = x + (ancho_col - ancho_barra) / 2
            base = arriba + area_h
            if d['vendidas']:
                alto_con = alto_total * d['conectadas'] / d['vendidas']
                alto_des = alto_total * d.get('desconectadas', 0) / d['vendidas']
                ruta = QPainterPath()
                ruta.addRoundedRect(QRectF(barra_x, base - alto_total, ancho_barra, alto_total), 5, 5)
                painter.save()
                painter.setClipPath(ruta)
                painter.fillRect(QRectF(barra_x, base - alto_total, ancho_barra, alto_total), _relleno(TONO_CLARO))
                if alto_des:
                    painter.fillRect(QRectF(barra_x, base - alto_total, ancho_barra, alto_des), _relleno(ROJO))
                painter.fillRect(QRectF(barra_x, base - alto_con, ancho_barra, alto_con), _relleno(MARINO))
                painter.restore()
            painter.setFont(self._fuente(12, True))
            self._texto(painter, QRectF(x, base - alto_total - 20, ancho_col, 18), centro, _num(d['vendidas']), TINTA)
            meta = d.get('meta')
            if meta:
                y_meta = base - area_h * meta / tope
                pluma = QPen(_relleno(MARINO), 2, Qt.PenStyle.DashLine)
                painter.setPen(pluma)
                painter.drawLine(int(x + ancho_col * 0.08), int(y_meta), int(x + ancho_col * 0.92), int(y_meta))
            pie = base + 4
            painter.setFont(self._fuente(11, True))
            self._texto(painter, QRectF(x, pie, ancho_col, 16), centro, d['etiqueta'], MARINO)
            painter.setFont(self._fuente(10))
            self._texto(painter, QRectF(x, pie + 16, ancho_col, 14), centro, f"{_num(d['conectadas'])} conect.", APAGADO)
            if meta:
                cumple = d['vendidas'] / meta
                painter.setFont(self._fuente(10, True))
                self._texto(painter, QRectF(x, pie + 30, ancho_col, 14), centro, f"{round(cumple * 100)}% de meta",
                            MARINO if cumple >= 1 else ROJO_TEXTO)
        painter.setOpacity(1.0)
        painter.end()


class BarrasServicio(_GraficoBase):
    """Una barra lateral por tipo de servicio, del que mejor conecta al que
    peor; el color indica el plan."""
    ALTO_MIN = 34

    @staticmethod
    def color_plan(nombre):
        base = nombre.strip().lower()
        if base.startswith(("básico", "basico")):
            return TONO_CLARO
        if base.startswith("medio"):
            return TONO_MEDIO
        return MARINO

    def set_datos(self, datos):
        super().set_datos(datos)
        self.setMinimumHeight(max(1, len(datos)) * self.ALTO_MIN)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._datos:
            painter.end()
            return
        alto_fila = min(self.height() / len(self._datos), 48.0)
        x_barra = 134
        x_fin = self.width() - 70
        for i, d in enumerate(self._datos):
            y = i * alto_fila
            painter.setFont(self._fuente(12, True))
            nombre = QFontMetrics(painter.font()).elidedText(d['servicio'], Qt.TextElideMode.ElideRight, x_barra - 12)
            self._texto(painter, QRectF(0, y, x_barra - 8, alto_fila), Qt.AlignmentFlag.AlignLeft, nombre, TINTA)
            alto_barra = min(26.0, alto_fila - 8)
            pista = QRectF(x_barra, y + (alto_fila - alto_barra) / 2, x_fin - x_barra, alto_barra)
            self._barra(painter, pista, "#EDF0F6", 7)
            largo = max(pista.width() * 0.14, pista.width() * d['pct'])
            relleno = QRectF(pista.left(), pista.top(), largo, pista.height())
            self._barra(painter, relleno, self.color_plan(d['servicio']), 7)
            painter.setFont(self._fuente(11, True))
            self._texto(painter, relleno.adjusted(0, 0, -9, 0), Qt.AlignmentFlag.AlignRight, _pct(d['pct']), "#FFFFFF")
            painter.setFont(self._fuente(11))
            self._texto(painter, QRectF(x_fin + 6, y, 64, alto_fila), Qt.AlignmentFlag.AlignRight, f"{_num(d['n'])} un.", APAGADO)
        painter.end()


class BarrasEjecutivo(_GraficoBase):
    """Una barra por ejecutivo con sus camiones conectados, por conectar y desconectados."""
    ALTO_MIN = 24
    ALTO_CABECERA = 22

    def set_datos(self, datos):
        super().set_datos(datos)
        self.setMinimumHeight(self.ALTO_CABECERA + max(1, len(datos)) * self.ALTO_MIN)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._datos:
            painter.end()
            return
        alto_fila = min((self.height() - self.ALTO_CABECERA) / len(self._datos), 36.0)
        x_barra = 144
        ancho_texto = 140
        x_fin = self.width() - ancho_texto - 12
        maximo = max(1, max(d['n'] for d in self._datos))
        self._encabezados(painter, x_fin + 8)
        for i, d in enumerate(self._datos):
            y = self.ALTO_CABECERA + i * alto_fila
            painter.setFont(self._fuente(12, True))
            nombre = QFontMetrics(painter.font()).elidedText(d['ejecutivo'], Qt.TextElideMode.ElideRight, x_barra - 10)
            self._texto(painter, QRectF(0, y, x_barra - 6, alto_fila), Qt.AlignmentFlag.AlignLeft, nombre, TINTA)
            alto_barra = min(14.0, alto_fila - 6)
            pista = QRectF(x_barra, y + (alto_fila - alto_barra) / 2, x_fin - x_barra, alto_barra)
            self._barra(painter, pista, "#EDF0F6", alto_barra / 2)
            ruta = QPainterPath()
            ruta.addRoundedRect(pista, alto_barra / 2, alto_barra / 2)
            painter.save()
            painter.setClipPath(ruta)
            x = pista.left()
            for clave, color in (('conectadas', MARINO), ('por_conectar', TONO_CLARO), ('desconectadas', ROJO)):
                largo = pista.width() * d[clave] / maximo
                painter.fillRect(QRectF(x, pista.top(), largo, pista.height()), _relleno(color))
                x += largo
            painter.restore()
            self._pie(painter, y, alto_fila, d, x_fin + 8)
        painter.end()

    def _columnas(self, x_ini):
        """(clave, ancho, color, encabezado) de la tabla de la derecha, a partir de x_ini."""
        columnas = (('conectadas', 32, MARINO, MARINO), ('por_conectar', 28, TONO_SUAVE, TONO_CLARO),
                    ('desconectadas', 32, ROJO_TEXTO, ROJO), ('n', 40, TINTA, None))
        x = x_ini
        for clave, ancho, color, titulo in columnas:
            yield clave, x, ancho, color, titulo
            x += ancho

    def _pie(self, painter, y, alto, d, x_ini):
        painter.setFont(self._fuente(11, True))
        for clave, x, ancho, color, _ in self._columnas(x_ini):
            self._texto(painter, QRectF(x, y, ancho, alto), Qt.AlignmentFlag.AlignRight, _num(d[clave]), color)

    def _encabezados(self, painter, x_ini):
        painter.setFont(self._fuente(9, True))
        for _, x, ancho, _, punto in self._columnas(x_ini):
            if punto is None:
                self._texto(painter, QRectF(x, 0, ancho, self.ALTO_CABECERA), Qt.AlignmentFlag.AlignRight, "TOTAL", APAGADO)
                continue
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_relleno(punto))
            painter.drawEllipse(QRectF(x + ancho - 10,self.ALTO_CABECERA / 2 - 5, 10, 10))


class _LineaCarga(QWidget):
    """Línea fina que corre de lado a lado mientras se espera algo."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._fase = 0.0
        self.hide()
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(900)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._mover)

    def _mover(self, valor):
        self._fase = float(valor)
        self.update()

    def iniciar(self):
        self.show()
        self.raise_()
        if self._anim.state() != QVariantAnimation.State.Running:
            self._anim.start()

    def detener(self):
        self._anim.stop()
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        largo = self.width() * 0.3
        x = -largo + self._fase * (self.width() + largo)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_relleno(MARINO))
        painter.drawRoundedRect(QRectF(x, 0, largo, self.height()), 1.5, 1.5)
        painter.end()


class _FilasConTooltip(_GraficoBase):
    """Gráfico de filas con ayuda emergente: los nombres largos se cortan con '…' y la
    ayuda muestra el nombre completo al pasar el mouse por la fila."""
    ALTO_FILA = 30
    ALTO_TOPE = 30.0
    ALTO_CABECERA = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._fila_ayuda = -1

    def set_datos(self, datos, *args):
        super().set_datos(datos)
        self.setMinimumHeight(self.ALTO_CABECERA + max(1, len(datos)) * self.ALTO_FILA)

    def _alto_fila(self):
        return min((self.height() - self.ALTO_CABECERA) / max(1, len(self._datos)), self.ALTO_TOPE)

    def _texto_ayuda(self, dato):
        return dato['nombre']

    def mouseMoveEvent(self, event):
        fila = int((event.position().y() - self.ALTO_CABECERA) // self._alto_fila()) if self._datos else -1
        if fila == self._fila_ayuda:
            return
        self._fila_ayuda = fila
        if 0 <= fila < len(self._datos):
            QToolTip.showText(event.globalPosition().toPoint(), self._texto_ayuda(self._datos[fila]), None)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event):
        self._fila_ayuda = -1
        QToolTip.hideText()
        super().leaveEvent(event)

    def _nombre(self, painter, rect, texto):
        painter.setFont(self._fuente(12, True))
        corto = QFontMetrics(painter.font()).elidedText(texto, Qt.TextElideMode.ElideRight, int(rect.width()) - 4)
        self._texto(painter, rect, Qt.AlignmentFlag.AlignLeft, corto, TINTA)


class BarrasFuga(_FilasConTooltip):
    """Porcentaje de unidades desconectadas por grupo (industria, modelo o facturación),
    con una marca vertical en el promedio de todo el universo."""
    NEUTRO = "#A9B6CC"
    ALTO_CABECERA = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self._promedio = 0.0

    def set_datos(self, datos, promedio=0.0):
        self._promedio = promedio
        super().set_datos(datos)

    def _texto_ayuda(self, d):
        return f"{d['nombre']}\n{_num(d['des'])} de {_num(d['n'])} unidades desconectadas ({_pct(d['tasa'])})"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._datos:
            painter.end()
            return
        alto_fila = self._alto_fila()
        ancho_nombre = min(210, max(130, int(self.width() * 0.30)))
        x_barra = ancho_nombre + 8
        x_fin = self.width() - 150
        maximo = max(0.01, self._promedio, max(d['tasa'] for d in self._datos))
        x = 0.0
        painter.setFont(self._fuente(10))
        for color, texto in ((ROJO, "Pierde más que el promedio"), (self.NEUTRO, "Pierde igual o menos")):
            self._barra(painter, QRectF(x, (self.ALTO_CABECERA - 9) / 2, 9, 9), color, 2)
            ancho_texto = QFontMetrics(painter.font()).horizontalAdvance(texto) + 6
            self._texto(painter, QRectF(x + 14, 0, ancho_texto, self.ALTO_CABECERA), Qt.AlignmentFlag.AlignLeft, texto, APAGADO)
            x += 14 + ancho_texto + 10
        for i, d in enumerate(self._datos):
            y = self.ALTO_CABECERA + i * alto_fila
            self._nombre(painter, QRectF(0, y, ancho_nombre, alto_fila), d['nombre'])
            alto_barra = min(16.0, alto_fila - 8)
            pista = QRectF(x_barra, y + (alto_fila - alto_barra) / 2, x_fin - x_barra, alto_barra)
            self._barra(painter, pista, "#EDF0F6", alto_barra / 2)
            largo = max(4.0, pista.width() * d['tasa'] / maximo)
            sobre = d['tasa'] > self._promedio
            self._barra(painter, QRectF(pista.left(), pista.top(), largo, pista.height()), ROJO if sobre else self.NEUTRO, alto_barra / 2)
            x_prom = pista.left() + pista.width() * self._promedio / maximo
            painter.setPen(QPen(_relleno(MARINO), 2))
            painter.drawLine(int(x_prom), int(pista.top() - 3), int(x_prom), int(pista.bottom() + 3))
            painter.setFont(self._fuente(12, True))
            self._texto(painter, QRectF(x_fin + 6, y, 50, alto_fila), Qt.AlignmentFlag.AlignRight, _pct(d['tasa']),
                        ROJO_TEXTO if sobre else APAGADO)
            painter.setFont(self._fuente(11))
            self._texto(painter, QRectF(x_fin + 58, y, self.width() - x_fin - 58, alto_fila), Qt.AlignmentFlag.AlignRight,
                        f"{_num(d['des'])} de {_num(d['n'])}", APAGADO)
        painter.end()


class BarrasClientes(_FilasConTooltip):
    """Clientes con más unidades desconectadas. La barra roja son sus unidades desconectadas
    (todas parten del mismo borde y bajan de mayor a menor); a la derecha, cuántas siguen
    conectadas y si el cliente es parcial (aún conecta) o ya no."""
    ALTO_CABECERA = 22
    ANCHO_DES = 46
    ANCHO_CON = 70
    ANCHO_CHIP = 74

    def _texto_ayuda(self, d):
        estado = "Parcial: aún tiene unidades conectadas" if d['con'] else "Todas sus unidades están desconectadas"
        return f"{d['nombre']}\n{_num(d['con'])} conectadas · {_num(d['des'])} desconectadas\n{estado}"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._datos:
            painter.end()
            return
        alto_fila = self._alto_fila()
        ancho_nombre = min(260, max(150, int(self.width() * 0.36)))
        x_barra = ancho_nombre + 8
        x_des = self.width() - self.ANCHO_CHIP - self.ANCHO_CON - self.ANCHO_DES - 16
        x_con = self.width() - self.ANCHO_CHIP - self.ANCHO_CON - 8
        maximo = max(1, max(d['des'] for d in self._datos))
        painter.setFont(self._fuente(10, True))
        self._texto(painter, QRectF(x_barra, 0, x_con - x_barra - 40, self.ALTO_CABECERA), Qt.AlignmentFlag.AlignLeft, "DESCONECTADAS", ROJO_TEXTO)
        self._texto(painter, QRectF(x_con - 30, 0, self.ANCHO_CON + 30, self.ALTO_CABECERA), Qt.AlignmentFlag.AlignRight, "CONECTADAS", MARINO)
        for i, d in enumerate(self._datos):
            y = self.ALTO_CABECERA + i * alto_fila
            self._nombre(painter, QRectF(0, y, ancho_nombre, alto_fila), d['nombre'])
            alto_barra = min(14.0, alto_fila - 8)
            pista = QRectF(x_barra, y + (alto_fila - alto_barra) / 2, x_des - x_barra - 6, alto_barra)
            self._barra(painter, pista, "#EDF0F6", alto_barra / 2)
            largo = max(alto_barra, pista.width() * d['des'] / maximo)
            self._barra(painter, QRectF(pista.left(), pista.top(), largo, pista.height()), ROJO, alto_barra / 2)
            painter.setFont(self._fuente(12, True))
            self._texto(painter, QRectF(x_des, y, self.ANCHO_DES, alto_fila), Qt.AlignmentFlag.AlignRight, _num(d['des']), ROJO_TEXTO)
            self._texto(painter, QRectF(x_con, y, self.ANCHO_CON, alto_fila), Qt.AlignmentFlag.AlignRight, _num(d['con']), MARINO if d['con'] else APAGADO)
            parcial = d['con'] > 0
            chip = QRectF(self.width() - self.ANCHO_CHIP, y + (alto_fila - 18) / 2, self.ANCHO_CHIP, 18)
            self._barra(painter, chip, AZUL_SUAVE if parcial else ROJO_SUAVE, 9)
            painter.setFont(self._fuente(10, True))
            self._texto(painter, chip, Qt.AlignmentFlag.AlignHCenter, "Parcial" if parcial else "Todas", MARINO if parcial else ROJO_TEXTO)
        painter.end()


class SelectorMeses(QPushButton):
    """Botón para elegir varios meses a la vez: abre una lista con casillas. Imita lo justo
    de un combo (currentData, setCurrentIndex, currentIndexChanged) para usarlo como los demás filtros."""
    currentIndexChanged = pyqtSignal(int)
    _ESTILO = ("QPushButton { background: white; color: #0F1B33; border: 1px solid #D9DEE8; border-radius: 9px; "
               "padding: 7px 12px; font-size: 12px; font-weight: 700; min-width: 100px; text-align: left; } "
               "QPushButton:hover { border-color: #B9C6DA; }")

    def __init__(self, titulo):
        super().__init__()
        self._titulo = titulo
        self._opciones = []
        self._elegidos = []
        self._lista = None
        self.setStyleSheet(self._ESTILO)
        self._texto()

    def currentData(self):
        return list(self._elegidos)

    def setCurrentIndex(self, _indice=0):
        if self._elegidos:
            self._elegidos = []
            self._texto()
            self.currentIndexChanged.emit(0)

    def set_opciones(self, pares):
        """pares: [(nombre, número de mes)]; los meses elegidos que ya no existen se descartan."""
        self._opciones = list(pares)
        validos = {m for _, m in self._opciones}
        self._elegidos = [m for m in self._elegidos if m in validos]
        self._texto()

    def _texto(self):
        nombres = {m: n for n, m in self._opciones}
        if not self._elegidos:
            texto = self._titulo
        elif len(self._elegidos) == 1:
            texto = nombres.get(self._elegidos[0], self._titulo)
        elif len(self._elegidos) <= 3:
            texto = ", ".join(nombres.get(m, "")[:3] for m in self._elegidos)
        else:
            texto = f"{len(self._elegidos)} meses"
        self.setText(texto)

    def mouseReleaseEvent(self, evento):
        super().mouseReleaseEvent(evento)
        if not self.rect().contains(evento.position().toPoint()):
            return
        if self._lista is not None:
            self._cerrar()
        elif self._opciones:
            self._abrir()

    def _cerrar(self):
        QApplication.instance().removeEventFilter(self)
        if self._lista is not None:
            self._lista.hide()
            self._lista.deleteLater()
            self._lista = None

    def eventFilter(self, objeto, evento):
        """Mientras la lista está abierta, cualquier clic fuera de ella (o Escape) la cierra."""
        if self._lista is not None:
            if evento.type() == QEvent.Type.MouseButtonPress:
                if not isinstance(objeto, QWidget):
                    return False
                if not (objeto is self or objeto is self._lista or self._lista.isAncestorOf(objeto)):
                    self._cerrar()
            elif evento.type() == QEvent.Type.KeyPress and evento.key() == Qt.Key.Key_Escape:
                self._cerrar()
        return False

    def hideEvent(self, evento):
        self._cerrar()
        super().hideEvent(evento)

    def _abrir(self):
        ventana = self.window()
        caja = QFrame(ventana)
        caja.setStyleSheet("QFrame#listaMeses { background: white; border: 1px solid #D9DEE8; border-radius: 10px; }")
        caja.setObjectName("listaMeses")
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        botones = QHBoxLayout()
        botones.setSpacing(6)
        restablecer = QPushButton("Restablecer")
        ninguno = QPushButton("Ninguno")
        ninguno.setToolTip("Desmarca todos para elegir solo los meses que quieras")
        for boton, color, color_hover in ((restablecer, _fondo_boton(), _fondo_boton(True)), (ninguno, "#D1453B", "#E2574C")):
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(f"QPushButton {{ background: {color}; color: white; border: none; border-radius: 8px; "
                                f"padding: 6px 8px; font-size: 12px; font-weight: 700; }} "
                                f"QPushButton:hover {{ background: {color_hover}; }}")
            botones.addWidget(boton, 1)
        lay.addLayout(botones)
        lista = QListWidget()
        lista.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lista.setFrameShape(QFrame.Shape.NoFrame)
        lista.setStyleSheet(
            "QListWidget { background: transparent; color: #0F1B33; border: none; font-size: 12px; font-weight: 600; outline: none; } "
            "QListWidget::item { padding: 7px 10px; border-radius: 7px; } "
            "QListWidget::item:hover { background: #E3E8F1; color: #0F1B33; }")
        for nombre, mes in self._opciones:
            item = QListWidgetItem(nombre)
            item.setData(Qt.ItemDataRole.UserRole, mes)
            self._poner(item, not self._elegidos or mes in self._elegidos)
            lista.addItem(item)
        lista.setIconSize(QSize(16, 16))
        lista.setFixedHeight(min(len(self._opciones), 12) * 34 + 4)
        lista.itemClicked.connect(self._alternar)
        lay.addWidget(lista)
        restablecer.clicked.connect(lambda: self._restablecer(lista))
        ninguno.clicked.connect(lambda: self._desmarcar_todos(lista))
        caja.setFixedWidth(max(self.width(), 200))
        caja.adjustSize()
        caja.move(self.mapTo(ventana, self.rect().bottomLeft()) + QPoint(0, 4))
        self._lista = caja
        caja.show()
        caja.raise_()
        QApplication.instance().installEventFilter(self)

    @staticmethod
    def _poner(item, marcado):
        """Casilla dibujada con un icono (la nativa se veía como un cuadro negro en el modo oscuro)."""
        item.setData(Qt.ItemDataRole.UserRole + 1, marcado)
        item.setIcon(qta.icon('fa5s.check-square', color=_relleno(MARINO).name()) if marcado
                     else qta.icon('fa5.square', color='#9AA8C0'))

    def _aplicar(self, lista):
        """Los meses marcados son los que se muestran; con todos marcados no hay filtro de mes."""
        marcados = {lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(lista.count())
                    if lista.item(i).data(Qt.ItemDataRole.UserRole + 1)}
        todos = {m for _, m in self._opciones}
        self._elegidos = [] if not marcados or marcados == todos else [m for _, m in self._opciones if m in marcados]
        if not marcados:
            for i in range(lista.count()):
                self._poner(lista.item(i), True)
        self._texto()
        self.currentIndexChanged.emit(0)

    def _alternar(self, item):
        self._poner(item, not item.data(Qt.ItemDataRole.UserRole + 1))
        self._aplicar(item.listWidget())

    def _desmarcar_todos(self, lista):
        """Deja la lista vacía para ir marcando solo los meses que se quieren ver; el filtro
        cambia en cuanto se marca el primero."""
        for i in range(lista.count()):
            self._poner(lista.item(i), False)

    def _restablecer(self, lista):
        for i in range(lista.count()):
            self._poner(lista.item(i), True)
        self._aplicar(lista)


class _CalculoPanorama(QThread):
    """Calcula el panorama sin bloquear la ventana; si falla, entrega None."""
    terminado = pyqtSignal(object)

    def __init__(self, df, parent=None):
        super().__init__(parent)
        self._df = df

    def run(self):
        try:
            resultado = servicio.calcular_panorama(self._df)
        except Exception:
            logging.getLogger(__name__).exception("No se pudo calcular el panorama del Dashboard")
            resultado = None
        self.terminado.emit(resultado)


class _IgnorarRueda(QObject):
    """Evita que la rueda del mouse cambie sin querer un combo o un número."""
    def eventFilter(self, objeto, evento):
        return evento.type() == QEvent.Type.Wheel


class PanelMetas(QFrame):
    """Tarjeta flotante para fijar la meta mensual de unidades vendidas. Guarda en
    MetasVC.csv (carpeta de datos compartida)."""
    cambio = pyqtSignal()
    cerrar = pyqtSignal()
    ANCHO = 300

    _ESTILO_SPIN = ("QSpinBox { background: white; color: #0F1B33; border: 1px solid #D9DEE8; border-radius: 9px; "
                    "padding: 6px 8px; font-size: 13px; font-weight: 600; } QSpinBox:focus { border-color: #1B2B4E; }")
    _ESTILO_BOTON = ("QPushButton { background: #F7F9FC; color: #1B2B4E; border: 1px solid #D9DEE8; border-radius: 10px; "
                     "padding: 9px 12px; font-size: 12px; font-weight: 700; } QPushButton:hover { background: #EEF2F8; }")
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("panelMetas")
        self.setStyleSheet("QFrame#panelMetas { background: white; border: 1px solid #E3E8F0; border-radius: 16px; }")
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(30)
        sombra.setOffset(0, 8)
        sombra.setColor(QColor(27, 43, 78, 60))
        self.setGraphicsEffect(sombra)
        self._metas = {}
        self._sin_rueda = _IgnorarRueda(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)

        fila_titulo = QHBoxLayout()
        fila_titulo.addWidget(_etiqueta("Meta del mes", f"color: {TINTA}; font-size: 15px; font-weight: 800;"), 1)
        boton_cerrar = QPushButton()
        boton_cerrar.setIcon(qta.icon('fa5s.times', color=_relleno(MARINO).name()))
        boton_cerrar.setFixedSize(30, 30)
        boton_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        boton_cerrar.setToolTip("Cerrar")
        boton_cerrar.setStyleSheet(self._ESTILO_BOTON.replace("padding: 9px 12px;", "padding: 0;"))
        boton_cerrar.clicked.connect(self.cerrar.emit)
        fila_titulo.addWidget(boton_cerrar)
        lay.addLayout(fila_titulo)
        subtitulo = _etiqueta("Unidades vendidas que se propone el equipo. Los meses pasados no se pueden cambiar.",
                              f"color: {APAGADO}; font-size: 11px;")
        subtitulo.setWordWrap(True)
        lay.addWidget(subtitulo)

        hoy = date.today()
        estilo_campo = f"color: {APAGADO}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        fila_periodo = QHBoxLayout()
        fila_periodo.setSpacing(8)
        caja_anio = QVBoxLayout()
        caja_anio.setSpacing(3)
        caja_anio.addWidget(_etiqueta("AÑO", estilo_campo))
        self.cmb_anio = ComboTarjeta("Año")
        self.cmb_anio.setStyleSheet(DashboardModule._ESTILO_COMBO.replace("min-width: 150px;", "min-width: 60px;"))
        for anio in (hoy.year, hoy.year + 1):
            self.cmb_anio.addItem(str(anio), anio)
        caja_anio.addWidget(self.cmb_anio)
        caja_mes = QVBoxLayout()
        caja_mes.setSpacing(3)
        caja_mes.addWidget(_etiqueta("MES", estilo_campo))
        self.cmb_mes = ComboTarjeta("Mes")
        self.cmb_mes.setStyleSheet(DashboardModule._ESTILO_COMBO.replace("min-width: 150px;", "min-width: 90px;"))
        for i, nombre in enumerate(servicio.MESES, start=1):
            self.cmb_mes.addItem(nombre, i)
        self.cmb_mes.setCurrentIndex(hoy.month - 1)
        caja_mes.addWidget(self.cmb_mes)
        fila_periodo.addLayout(caja_anio)
        fila_periodo.addLayout(caja_mes, 1)
        lay.addLayout(fila_periodo)

        lay.addWidget(_etiqueta("META DE UNIDADES VENDIDAS", estilo_campo))
        self.spin_meta = self._spin()
        lay.addWidget(self.spin_meta)
        for campo in (self.cmb_anio, self.cmb_mes, self.spin_meta):
            campo.installEventFilter(self._sin_rueda)
        self.cmb_anio.currentIndexChanged.connect(self._refrescar)
        self.cmb_mes.currentIndexChanged.connect(self._refrescar)

        self.lbl_estado = _etiqueta("", f"color: {ROJO_TEXTO}; font-size: 11px;")
        self.lbl_estado.setWordWrap(True)
        lay.addWidget(self.lbl_estado)
        guardar = QPushButton("Guardar meta")
        guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        guardar.setStyleSheet(_estilo_principal(10, '10px 12px', 13))
        guardar.clicked.connect(self._guardar)
        self.btn_guardar = guardar
        _con_tema(self)
        lay.addWidget(guardar)

    def refrescar_tema(self):
        self.btn_guardar.setStyleSheet(_estilo_principal(10, '10px 12px', 13))

    def alto_para(self, ancho):
        return self.layout().totalHeightForWidth(ancho)

    def _spin(self):
        spin = QSpinBox()
        spin.setRange(0, 100000)
        spin.setMinimumHeight(38)
        spin.setStyleSheet(self._ESTILO_SPIN)
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        return spin

    def abrir(self, metas):
        self._metas = metas
        self._refrescar()

    def _periodo(self):
        return self.cmb_anio.currentData(), self.cmb_mes.currentData()

    def _es_pasado(self):
        anio, mes = self._periodo()
        hoy = date.today()
        return (anio, mes) < (hoy.year, hoy.month)

    def _refrescar(self, *_):
        pasado = self._es_pasado()
        self.spin_meta.setValue(self._metas.get(self._periodo(), 0))
        self.spin_meta.setEnabled(not pasado)
        self.btn_guardar.setEnabled(not pasado)
        self._mostrar_estado("Los meses pasados no se pueden modificar: este archivo es nuevo y no tuvieron meta." if pasado else "", False)

    def _mostrar_estado(self, texto, ok):
        self.lbl_estado.setStyleSheet(f"color: {MARINO if ok else ROJO_TEXTO}; font-size: 11px; background: transparent; border: none;")
        self.lbl_estado.setText(texto)

    def _guardar(self):
        anio, mes = self._periodo()
        ok, mensaje = metas_service.guardar_metas(anio, {mes: self.spin_meta.value()})
        self._mostrar_estado("Meta guardada." if ok else mensaje, ok)
        if ok:
            self.cambio.emit()


class DashboardModule(QWidget):
    ANCHO_MAXIMO = 1260
    _ESTILO_COMBO = (
        "QComboBox { background: white; color: #0F1B33; border: 1px solid #D9DEE8; border-radius: 9px; "
        "padding: 7px 12px; font-size: 12px; font-weight: 700; min-width: 150px; }"
        "QComboBox:hover { border-color: #B9C6DA; }"
        "QComboBox::drop-down { border: none; width: 22px; }"
        "QComboBox QAbstractItemView { background: white; color: #0F1B33; selection-background-color: #E3E8F1; "
        "selection-color: #0F1B33; border: 1px solid #D9DEE8; }")

    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.data_manager.data_ready.connect(self._on_data_ready)
        self._data_dirty = True
        self._panorama = None
        self._panorama_vista = None
        self._metas = {}
        self._registro = {}
        self._panel_abierto = False
        self.search_input = QLineEdit(self)
        self.search_input.hide()
        self._ultimo_texto = ""
        self._unidades_actuales = None
        self._segmento_fuga = "INDUSTRIA"
        self._solo_parciales = False
        self._botones_segmento = []
        self._flota = ""
        self._flotas = []
        self._orden_filtros = []
        _con_tema(self)
        self._calculo = None
        self._recarga_pendiente = False
        self._fin_carga = QTimer(self)
        self._fin_carga.setSingleShot(True)
        self._fin_carga.timeout.connect(lambda: self._esqueleto.terminar())
        self._sugerencias = QListWidget(self)
        self._sugerencias.hide()
        self._sugerencias.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sugerencias.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._sugerencias.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._anim_lista = QVariantAnimation(self)
        self._anim_lista.setDuration(180)
        self._anim_lista.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_lista.valueChanged.connect(self._alto_lista)
        self._carga_barra = _LineaCarga(self)
        self._barra_conectada = False
        self._sugerencias.setStyleSheet(
            "QListWidget { background: white; color: #0F1B33; border: 1px solid #D9DEE8; border-radius: 10px; "
            "padding: 3px; font-size: 12px; font-weight: 600; outline: none; } "
            "QListWidget::item { padding: 7px 10px; border-radius: 7px; } "
            "QListWidget::item:hover { background: #E3E8F1; color: #0F1B33; }")
        self._sugerencias.itemClicked.connect(self._elegir_sugerencia)
        self._setup_ui()

    # ------------------------------------------------------------------ interfaz
    def refrescar_tema(self):
        self.btn_quitar.setIcon(qta.icon('fa5s.times', color=_relleno(MARINO).name()))
        self.chk_pruebas.setStyleSheet(_estilo_marca())
        for boton in self._botones_segmento:
            boton.setStyleSheet(self._estilo_segmento())
        self.btn_metas.setStyleSheet(_estilo_principal(9, '9px 16px', 12))
        for marca in self.chk_servicio.values():
            marca.setStyleSheet(_estilo_marca())

    def _setup_ui(self):
        self.setStyleSheet(f"DashboardModule {{ background: {FONDO}; }}")
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.setSpacing(0)
        cabecera = QWidget()
        self._cabecera = cabecera
        cabecera.setObjectName("cabeceraDash")
        cabecera.setStyleSheet(f"QWidget#cabeceraDash {{ background: {FONDO}; }}")
        fija = QHBoxLayout(cabecera)
        fija.setContentsMargins(24, 14, 24, 10)
        columna_fija = QWidget()
        columna_fija.setStyleSheet("background: transparent;")
        columna_fija.setMaximumWidth(self.ANCHO_MAXIMO)
        fija.addStretch(1)
        fija.addWidget(columna_fija, 100)
        fija.addStretch(1)
        lay_fija = QVBoxLayout(columna_fija)
        lay_fija.setContentsMargins(0, 0, 0, 0)
        lay_fija.setSpacing(10)
        lay_fija.addLayout(self._crear_titulo())
        lay_fija.addWidget(self._crear_filtros())
        externo.addWidget(cabecera)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        externo.addWidget(scroll, 1)
        contenido = QWidget()
        contenido.setStyleSheet("background: transparent;")
        scroll.setWidget(contenido)
        scroll.verticalScrollBar().valueChanged.connect(lambda _: self._sugerencias.hide())
        centrado = QHBoxLayout(contenido)
        centrado.setContentsMargins(24, 4, 24, 14)
        columna = QWidget()
        columna.setMaximumWidth(self.ANCHO_MAXIMO)
        centrado.addStretch(1)
        centrado.addWidget(columna, 100)
        centrado.addStretch(1)
        lay = QVBoxLayout(columna)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        lay.addLayout(self._crear_kpis())
        lay.addWidget(self._crear_seccion_mes_a_mes())
        lay.addWidget(self._crear_seccion_metas())
        lay.addLayout(self._crear_fila_servicio_ejecutivo(), 1)
        lay.addLayout(self._crear_fila_fuga_clientes())
        self._esqueleto = EsqueletoCarga(columna, 'dashboard', QColor(FONDO))

        self.panel_metas = PanelMetas(self)
        self.panel_metas.cambio.connect(self._on_metas_cambiaron)
        self.panel_metas.cerrar.connect(lambda: self._mostrar_panel(False))
        self.panel_metas.hide()
        self._anim_panel = QPropertyAnimation(self.panel_metas, b"geometry", self)
        self._anim_panel.setDuration(220)
        self._anim_panel.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_panel.finished.connect(self._al_terminar_animacion)

    @staticmethod
    def _tarjeta(titulo, subtitulo):
        """Tarjeta blanca con título y subtítulo; devuelve (tarjeta, layout)."""
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaDash")
        tarjeta.setStyleSheet(f"QFrame#tarjetaDash {{ background: white; border: 1px solid {LINEA}; border-radius: 16px; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        cabecera = QVBoxLayout()
        cabecera.setSpacing(2)
        cabecera.addWidget(_etiqueta(titulo, f"color: {TINTA}; font-size: 13px; font-weight: 700;"))
        sub = _etiqueta(subtitulo, f"color: {APAGADO}; font-size: 11px;")
        sub.setWordWrap(True)
        cabecera.addWidget(sub)
        lay.addLayout(cabecera)
        return tarjeta, lay

    def _crear_titulo(self):
        caja = QVBoxLayout()
        caja.setSpacing(3)
        fila = QHBoxLayout()
        fila.setSpacing(10)
        fila.addWidget(_etiqueta("VOLVO CONNECT", f"color: {MARINO}; font-size: 18px; font-weight: 800; letter-spacing: 1px;"))
        separador = QFrame()
        separador.setFixedSize(1, 22)
        separador.setStyleSheet("background: #C5CEDD; border: none;")
        fila.addWidget(separador)
        fila.addWidget(_etiqueta("Gestión del Negocio", f"color: {TINTA}; font-size: 18px; font-weight: 700;"))
        fila.addStretch()
        caja.addLayout(fila)
        caja.addWidget(_etiqueta(
            "Un vistazo a la flota con servicio Volvo Connect, desde el Registro Maestro. "
            "Los filtros afectan todas las tarjetas y gráficos.", f"color: {APAGADO}; font-size: 11px;"))
        return caja

    def _crear_filtros(self):
        marco = QFrame()
        marco.setObjectName("filtrosDash")
        marco.setStyleSheet(f"QFrame#filtrosDash {{ background: white; border: 1px solid {LINEA}; border-radius: 14px; }}")
        fila = QHBoxLayout(marco)
        fila.setContentsMargins(12, 8, 12, 8)
        fila.setSpacing(8)
        self.filtros = {}
        nombres = {"EJECUTIVO": "Ejecutivo", "FORMA": "Contrato", "SERVICIO": "Plan", "ANIO": "Año", "MES": "Mes"}
        for columna, nombre in nombres.items():
            if columna == "ANIO":
                separador = QFrame()
                separador.setFixedSize(1, 22)
                separador.setStyleSheet(f"background: {LINEA}; border: none;")
                fila.addSpacing(4)
                fila.addWidget(separador)
                fila.addSpacing(4)
            combo = SelectorMeses(nombre) if columna == "MES" else ComboTarjeta(nombre)
            ancho = {"EJECUTIVO": 160, "FORMA": 110, "SERVICIO": 100, "ANIO": 84, "MES": 96}[columna]
            if columna != "MES":
                combo.setStyleSheet(self._ESTILO_COMBO.replace("min-width: 150px;", "min-width: 40px;"))
            combo.setFixedWidth(ancho)
            combo.setToolTip(f"Filtrar por {nombre.lower()}" + (" de inicio de contrato" if columna in ("ANIO", "MES") else "")
                             + (". Puedes elegir varios meses." if columna == "MES" else ""))
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
            combo.currentIndexChanged.connect(lambda _i, k=columna: self._cambio_filtro(k))
            fila.addWidget(combo)
            self.filtros[columna] = combo
            if columna == "SERVICIO":
                self.chk_servicio = {}
                for clave in ("CIV", "SZ"):
                    marca = QCheckBox(clave)
                    marca.setCursor(Qt.CursorShape.PointingHandCursor)
                    marca.setStyleSheet(_estilo_marca())
                    marca.setToolTip(f"Solo unidades con {clave}")
                    marca.stateChanged.connect(lambda _e, k=clave: self._cambio_filtro(k))
                    fila.addWidget(marca)
                    self.chk_servicio[clave.lower()] = marca
        fila.addSpacing(4)
        self.chk_pruebas = QCheckBox("Pruebas")
        self.chk_pruebas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_pruebas.setStyleSheet(_estilo_marca())
        self.chk_pruebas.setToolTip("Incluir los contratos de prueba (Test y Demo). Por defecto quedan fuera de las cifras.")
        self.chk_pruebas.stateChanged.connect(self._cambio_pruebas)
        fila.addWidget(self.chk_pruebas)
        fila.addStretch(1)
        self.btn_quitar = QPushButton()
        self.btn_quitar.setFixedSize(36, 36)
        self.btn_quitar.setIcon(qta.icon('fa5s.times', color=_relleno(MARINO).name()))
        self.btn_quitar.setToolTip("Quitar filtros")
        self.btn_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quitar.setStyleSheet(
            "QPushButton { background: #F7F9FC; border: 1px solid #D9DEE8; border-radius: 9px; } "
            "QPushButton:hover { background: #EEF2F8; } QPushButton:disabled { background: transparent; border-color: #E3E8F0; }")
        self.btn_quitar.clicked.connect(self._quitar_filtros)
        fila.addWidget(self.btn_quitar)
        self.btn_metas = QPushButton(" Metas")
        self.btn_metas.setIcon(qta.icon('fa5s.bullseye', color='white'))
        self.btn_metas.setToolTip("Configurar las metas de unidades vendidas")
        self.btn_metas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_metas.setStyleSheet(_estilo_principal(9, '9px 16px', 12))
        self.btn_metas.clicked.connect(lambda: self._mostrar_panel(True))
        fila.addWidget(self.btn_metas)
        return marco

    def _crear_kpis(self):
        fila = QHBoxLayout()
        fila.setSpacing(14)
        self._kpi = {}
        for clave, color in (("universo", MARINO), ("conectadas", MARINO), ("complementarios", MARINO), ("no_conectada", ROJO)):
            tarjeta = _TarjetaAcento(color)
            tarjeta.setFixedHeight(172)
            tarjeta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            lay = QVBoxLayout(tarjeta)
            lay.setContentsMargins(18, 12, 14, 12)
            lay.setSpacing(5)
            self._kpi[clave] = lay
            fila.addWidget(tarjeta, 1)
        self._armar_kpi_universo()
        self._armar_kpi_conectadas()
        self._armar_kpi_complementarios()
        self._armar_kpi_no_conectada()
        return fila

    @staticmethod
    def _cabecera_kpi(lay, titulo, icono, color, fondo):
        fila = QHBoxLayout()
        fila.addWidget(_etiqueta(titulo.upper(), f"color: {APAGADO}; font-size: 11px; font-weight: 700; letter-spacing: 1px;"))
        fila.addStretch()
        fila.addWidget(_icono_en_circulo(icono, color, fondo, tam=28, lado_icono=12, redondo=True))
        lay.addLayout(fila)

    @staticmethod
    def _pie_kpi(lay, izquierda, color):
        fila = QHBoxLayout()
        fila.addWidget(_etiqueta(izquierda, f"color: {APAGADO}; font-size: 11px; font-weight: 600;"))
        fila.addStretch()
        derecha = _etiqueta("—", f"color: {color}; font-size: 11px; font-weight: 700;")
        fila.addWidget(derecha)
        lay.addLayout(fila)
        return derecha

    def _armar_kpi_universo(self):
        lay = self._kpi["universo"]
        self._cabecera_kpi(lay, "Universo comercial", 'fa5s.truck', MARINO, AZUL_SUAVE)
        self.lbl_universo = _etiqueta("—", f"color: {TINTA}; font-size: 28px; font-weight: 800;")
        lay.addWidget(self.lbl_universo)
        self.barra_universo = BarraProporcion()
        lay.addWidget(self.barra_universo)
        lay.addStretch(1)
        self.lbl_universo_pct = self._pie_kpi(lay, "Unidades distintas (VIN)", MARINO)

    def _armar_kpi_conectadas(self):
        lay = self._kpi["conectadas"]
        self._cabecera_kpi(lay, "Con Volvo Connect", 'fa5s.wifi', MARINO, AZUL_SUAVE)
        self.lbl_conectadas = _etiqueta("—", f"color: {TINTA}; font-size: 28px; font-weight: 800;")
        lay.addWidget(self.lbl_conectadas)
        self.barra_conectadas = BarraProporcion()
        lay.addWidget(self.barra_conectadas)
        lay.addStretch(1)
        self.lbl_take_rate = self._pie_kpi(lay, "Take rate", MARINO)

    def _armar_kpi_complementarios(self):
        lay = self._kpi["complementarios"]
        self._cabecera_kpi(lay, "Productos complementarios", 'fa5s.th-large', MARINO, AZUL_SUAVE)
        fila = QHBoxLayout()
        fila.setSpacing(12)
        self.lbl_civ, self.barra_civ, self.lbl_civ_pct = self._columna_producto(fila, "CIV")
        separador = QFrame()
        separador.setFixedWidth(1)
        separador.setStyleSheet(f"background: {LINEA}; border: none;")
        fila.insertWidget(1, separador)
        self.lbl_sz, self.barra_sz, self.lbl_sz_pct = self._columna_producto(fila, "Safety Zone")
        lay.addLayout(fila)
        lay.addStretch(1)

    @staticmethod
    def _columna_producto(fila, nombre):
        col = QVBoxLayout()
        col.setSpacing(5)
        linea = QHBoxLayout()
        linea.setSpacing(6)
        valor = _etiqueta("—", f"color: {TINTA}; font-size: 28px; font-weight: 800;")
        linea.addWidget(valor)
        linea.addStretch()
        col.addLayout(linea)
        barra = BarraProporcion()
        col.addWidget(barra)
        pct = _etiqueta("—", f"color: {APAGADO}; font-size: 11px; font-weight: 600;")
        col.addWidget(pct)
        col.addStretch(1)
        fila.addLayout(col, 1)
        return valor, barra, pct

    def _armar_kpi_no_conectada(self):
        lay = self._kpi["no_conectada"]
        self._cabecera_kpi(lay, "Base no conectada", 'fa5s.ban', ROJO, ROJO_SUAVE)
        self.lbl_no_conectada = _etiqueta("—", f"color: {TINTA}; font-size: 28px; font-weight: 800;")
        lay.addWidget(self.lbl_no_conectada)
        self.barra_no_conectada = BarraProporcion()
        lay.addWidget(self.barra_no_conectada)
        self.caja_desglose = QVBoxLayout()
        self.caja_desglose.setSpacing(1)
        lay.addLayout(self.caja_desglose)
        lay.addStretch(1)

    def _crear_seccion_mes_a_mes(self):
        tarjeta, lay = self._tarjeta(
            "Conectados y desconectados, mes a mes",
            "Arriba el mes más nuevo, abajo el más antiguo. Un mes sale bien si se conectaron más unidades de las que se desconectaron.")
        lay.setContentsMargins(0, 16, 0, 16)
        lay.itemAt(0).layout().setContentsMargins(18, 0, 18, 0)
        self.grafico_mes = GraficoMesAMes()
        lay.addWidget(self.grafico_mes)
        self.lbl_sin_fecha = _etiqueta("", f"color: {APAGADO}; font-size: 11px; margin: 0 18px;")
        self.lbl_sin_fecha.setWordWrap(True)
        lay.addWidget(self.lbl_sin_fecha)
        return tarjeta

    def _crear_seccion_metas(self):
        tarjeta, lay = self._tarjeta(
            "Unidades vendidas por mes y meta",
            "Cada columna son las unidades vendidas en el mes, según su estado hoy: conectadas (abajo), por conectar "
            "y desconectadas o de baja (arriba, en rojo). La marca punteada es la meta de ese mes.")
        barra = QHBoxLayout()
        barra.setSpacing(12)
        barra.addWidget(_leyenda((("Conectadas", MARINO), ("Por conectar", TONO_CLARO), ("Desconectadas o de baja", ROJO))))
        self.lbl_meta_nota = _etiqueta("", f"color: {APAGADO}; font-size: 11px;")
        barra.addWidget(self.lbl_meta_nota)
        barra.addStretch(1)
        self._meses_metas = 6
        self.btn_meses_metas = QPushButton()
        self.btn_meses_metas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_meses_metas.setStyleSheet(PanelMetas._ESTILO_BOTON)
        self.btn_meses_metas.clicked.connect(self._alternar_meses_metas)
        barra.addWidget(self.btn_meses_metas)
        lay.addLayout(barra)
        self.grafico_metas = GraficoMetas()
        self.grafico_metas.setMinimumHeight(250)
        self.grafico_metas.detalle_mes = self._detalle_mes
        lay.addWidget(self.grafico_metas)
        return tarjeta

    def _crear_fila_servicio_ejecutivo(self):
        fila = QHBoxLayout()
        fila.setSpacing(14)
        tarjeta_s, lay_s = self._tarjeta("Conexión por tipo de servicio",
                                         "Porcentaje conectado de cada servicio, del que mejor conecta al que peor")
        lay_s.addWidget(_leyenda((("Plan Básico", TONO_CLARO), ("Plan Medio", TONO_MEDIO), ("Plan Full", MARINO))))
        self.grafico_servicio = BarrasServicio()
        lay_s.addWidget(self.grafico_servicio, 1)
        lay_s.addWidget(_etiqueta("CIV y SZ se suman al plan.", f"color: {APAGADO}; font-size: 11px;"))
        tarjeta_e, lay_e = self._tarjeta(
            "Camiones con Volvo Connect por ejecutivo",
            "Camiones que pasaron por Volvo Connect, según el ejecutivo que vendió el camión. Solo ejecutivos activos. "
            "Se muestran hasta 15, de más a menos. Cada fila: conectados / por conectar / desconectados = total.")
        lay_e.addWidget(_leyenda((("Conectados", MARINO), ("Por conectar", TONO_CLARO), ("Desconectados", ROJO))))
        self.grafico_ejecutivo = BarrasEjecutivo()
        lay_e.addWidget(self.grafico_ejecutivo, 1)
        self.lbl_ej_nota = _etiqueta("", f"color: {APAGADO}; font-size: 11px;")
        self.lbl_ej_nota.setWordWrap(True)
        lay_e.addWidget(self.lbl_ej_nota)
        for tarjeta in (tarjeta_s, tarjeta_e):
            tarjeta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        fila.addWidget(tarjeta_s, 1)
        fila.addWidget(tarjeta_e, 1)
        return fila

    @staticmethod
    def _estilo_segmento():
        return ("QPushButton { background: transparent; color: #1B2B4E; border: none; border-radius: 8px; "
                "padding: 6px 12px; font-size: 12px; font-weight: 700; } "
                f"QPushButton:checked {{ background: {_fondo_boton()}; color: white; }}")

    def _segmentos(self, opciones, al_elegir):
        """Botones de a uno para cambiar de vista; devuelve el widget que los contiene."""
        caja = QFrame()
        caja.setStyleSheet("QFrame { background: #F3F5F9; border: none; border-radius: 10px; }")
        lay = QHBoxLayout(caja)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(4)
        grupo = QButtonGroup(caja)
        for i, (clave, texto) in enumerate(opciones):
            boton = QPushButton(texto)
            boton.setCheckable(True)
            boton.setChecked(i == 0)
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(self._estilo_segmento())
            boton.clicked.connect(lambda _c, k=clave: al_elegir(k))
            grupo.addButton(boton)
            lay.addWidget(boton)
            self._botones_segmento.append(boton)
        caja.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        return caja

    def _mini_cifra(self):
        caja = QFrame()
        caja.setStyleSheet("QFrame { background: #F7F9FC; border: 1px solid #E3E8F0; border-radius: 12px; }")
        caja.setFixedHeight(80)
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        valor = _etiqueta("—", f"color: {TINTA}; font-size: 18px; font-weight: 800;")
        texto = _etiqueta("", f"color: {APAGADO}; font-size: 10px;")
        texto.setWordWrap(True)
        lay.addWidget(valor)
        lay.addWidget(texto)
        return caja, valor, texto

    def _crear_fila_fuga_clientes(self):
        fila = QHBoxLayout()
        fila.setSpacing(14)
        tarjeta_f, lay_f = self._tarjeta(
            "Dónde se pierden clientes",
            "Porcentaje de unidades desconectadas en cada grupo, del que más pierde al que menos. "
            "La marca vertical es el promedio de todo el universo.")
        lay_f.addWidget(self._segmentos((("INDUSTRIA", "Industria"), ("MODELO", "Modelo"), ("FACTURACION", "Facturación")),
                                        self._elegir_segmento_fuga), 0, Qt.AlignmentFlag.AlignLeft)
        cifras_f = QHBoxLayout()
        cifras_f.setSpacing(8)
        self._cifras_fuga = []
        for _ in range(3):
            caja, valor, texto = self._mini_cifra()
            cifras_f.addWidget(caja, 1)
            self._cifras_fuga.append((valor, texto))
        lay_f.addLayout(cifras_f)
        self.grafico_fuga = BarrasFuga()
        lay_f.addWidget(self.grafico_fuga, 1)
        self.lbl_fuga_nota = _etiqueta("", f"color: {APAGADO}; font-size: 11px;")
        self.lbl_fuga_nota.setWordWrap(True)
        lay_f.addWidget(self.lbl_fuga_nota)
        tarjeta_c, lay_c = self._tarjeta(
            "Clientes a recuperar",
            "Clientes con más unidades desconectadas. Los parciales todavía tienen unidades conectadas: "
            "son los más fáciles de recuperar con una llamada.")
        lay_c.addWidget(self._segmentos((("TODOS", "Más desconectadas"), ("PARCIALES", "Solo parciales")),
                                        self._elegir_vista_clientes), 0, Qt.AlignmentFlag.AlignLeft)
        cifras = QHBoxLayout()
        cifras.setSpacing(8)
        self._cifras_clientes = []
        for _ in range(3):
            caja, valor, texto = self._mini_cifra()
            cifras.addWidget(caja, 1)
            self._cifras_clientes.append((valor, texto))
        lay_c.addLayout(cifras)
        self.grafico_clientes = BarrasClientes()
        lay_c.addWidget(self.grafico_clientes, 1)
        nota_c = _etiqueta("Parcial: el cliente aún tiene unidades conectadas. Todas: ya no le queda ninguna. "
                           "Pasa el mouse por un nombre para verlo completo.", f"color: {APAGADO}; font-size: 11px;")
        nota_c.setWordWrap(True)
        lay_c.addWidget(nota_c)
        for tarjeta in (tarjeta_f, tarjeta_c):
            tarjeta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            tarjeta.layout().itemAt(0).layout().itemAt(1).widget().setMinimumHeight(34)
        fila.addWidget(tarjeta_f, 1)
        fila.addWidget(tarjeta_c, 1)
        return fila

    def _elegir_segmento_fuga(self, clave):
        self._segmento_fuga = clave
        self._pintar_fuga_clientes()

    def _elegir_vista_clientes(self, clave):
        self._solo_parciales = clave == "PARCIALES"
        self._pintar_fuga_clientes()

    def _pintar_fuga_clientes(self):
        unidades = self._unidades_actuales
        if unidades is None:
            self.grafico_fuga.set_datos([])
            self.grafico_clientes.set_datos([])
            self.lbl_fuga_nota.setText("")
            for valor, texto in self._cifras_clientes + self._cifras_fuga:
                valor.setText("—")
                texto.setText("")
            return
        fuga = servicio.fuga_por_segmento(unidades, self._segmento_fuga)
        self.grafico_fuga.set_datos(fuga['filas'], fuga['promedio'])
        self.lbl_fuga_nota.setText("Solo se muestran los grupos con unidades suficientes.")
        peor = fuga['filas'][0] if fuga['filas'] else None
        for (valor, texto), (cifra, descripcion) in zip(self._cifras_fuga, (
                (_pct(fuga['promedio']), "del universo está desconectado"),
                (_pct(peor['tasa']) if peor else "—", f"{peor['nombre']}, el que más pierde" if peor else ""),
                (_num(int((unidades['ACTIVACION'] == 'DESCONECTADO').sum())), "unidades desconectadas"))):
            valor.setText(cifra)
            texto.setText(descripcion)
        rec = servicio.clientes_a_recuperar(unidades, self._solo_parciales)
        self.grafico_clientes.set_datos(rec['filas'])
        for (valor, texto), (cifra, descripcion) in zip(self._cifras_clientes, (
                (_num(rec['con_desconexiones']), "clientes con unidades desconectadas"),
                (_pct(rec['pct_top10']), "de las desconexiones están en 10 clientes"),
                (_num(rec['parciales']), "clientes que aún tienen unidades conectadas"))):
            valor.setText(cifra)
            texto.setText(descripcion)

    # ------------------------------------------------------------------ panel de metas
    def _geometria_panel(self, abierto):
        ancho = min(PanelMetas.ANCHO, self.width() - 24)
        x = self.width() - ancho - 16 if abierto else self.width()
        return QRect(x, self._cabecera.height() + 4, ancho, self.panel_metas.alto_para(ancho))

    def _mostrar_panel(self, mostrar):
        if mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        self._anim_panel.stop()
        if mostrar:
            self.panel_metas.abrir(self._metas)
            self.panel_metas.setGeometry(self._geometria_panel(False))
            self.panel_metas.show()
            self.panel_metas.raise_()
        self._anim_panel.setStartValue(self.panel_metas.geometry())
        self._anim_panel.setEndValue(self._geometria_panel(mostrar))
        self._anim_panel.start()

    def _al_terminar_animacion(self):
        if not self._panel_abierto:
            self.panel_metas.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._panel_abierto:
            self.panel_metas.setGeometry(self._geometria_panel(True))

    def _on_metas_cambiaron(self):
        self._cargar_metas()
        self._registrar_cierres()
        self.panel_metas._metas = self._metas
        self._repintar()

    # ------------------------------------------------------------------ datos
    def refresh_if_dirty(self):
        if self._data_dirty:
            self.load_data()

    def _on_data_ready(self):
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def load_data(self):
        """Calcula el panorama en segundo plano mientras corre la animación de carga."""
        self._data_dirty = False
        if self._calculo is not None and self._calculo.isRunning():
            self._recarga_pendiente = True
            return
        if self._panorama is None:
            self._esqueleto.iniciar_ya()
        else:
            self._esqueleto.iniciar()
        self._calculo =_CalculoPanorama(self.data_manager.get_comercial_df(), self)
        self._calculo.terminado.connect(self._al_calcular)
        self._calculo.start()

    def _al_calcular(self, panorama):
        self._panorama = panorama
        self._llenar_filtros()
        self._registrar_cierres()
        self._cargar_metas()
        self._repintar()
        self._esqueleto.terminar()
        if self._recarga_pendiente:
            self._recarga_pendiente = False
            QTimer.singleShot(0, self.load_data)

    def _cargar_metas(self):
        self._metas = metas_service.leer_metas()
        self._registro = metas_service.leer_registro()

    def _registrar_cierres(self):
        """Guarda una sola vez cuánto se vendió y cuánto estaba conectado de cada
        mes ya cerrado, para no recalcularlo a cada rato."""
        if self._panorama is None:
            return
        actual = date.today()
        cierres = [(m['periodo'].year, m['periodo'].month, m['vendidas'], m['conectadas'])
                   for m in servicio.calcular_mensual(servicio.filtrar_panorama(self._panorama, SIN_PRUEBAS=True))
                   if (m['periodo'].year, m['periodo'].month) < (actual.year, actual.month)]
        if metas_service.registrar_cierres(cierres):
            self._registro = metas_service.leer_registro()

    # ------------------------------------------------------------------ filtros jerárquicos
    _CLAVES_FILTRO = ("EJECUTIVO", "FORMA", "SERVICIO", "CIV", "SZ", "ANIO", "MES", "FLOTA")
    _TITULOS_FILTRO = {"EJECUTIVO": "Ejecutivo", "FORMA": "Contrato", "SERVICIO": "Plan", "ANIO": "Año", "MES": "Mes"}

    def _valor_filtro(self, clave):
        if clave == "FLOTA":
            return self._flota
        if clave in ("CIV", "SZ"):
            return self.chk_servicio[clave.lower()].isChecked()
        return self.filtros[clave].currentData() or ""

    def _limpiar_filtro(self, clave):
        if clave == "FLOTA":
            self._flota = ""
            self.search_input.setText("")
            barra = getattr(self.window(), 'search_bar', None)
            if barra is not None and barra.text():
                barra.blockSignals(True)
                barra.setText("")
                barra.blockSignals(False)
            return
        control = self.chk_servicio[clave.lower()] if clave in ("CIV", "SZ") else self.filtros[clave]
        control.blockSignals(True)
        control.setChecked(False) if clave in ("CIV", "SZ") else control.setCurrentIndex(0)
        control.blockSignals(False)

    @staticmethod
    def _filtros_de(valores):
        """Argumentos de `filtrar_panorama` a partir de los valores de cada filtro."""
        servicio_f = {"plan": valores.get("SERVICIO", ""), "civ": bool(valores.get("CIV")), "sz": bool(valores.get("SZ"))}
        periodo = {"anio": valores.get("ANIO", ""), "meses": valores.get("MES") or []}
        return {"SIN_PRUEBAS": not valores.get("PRUEBAS"),
                "EJECUTIVO": valores.get("EJECUTIVO", ""), "FORMA": valores.get("FORMA", ""), "FLOTA": valores.get("FLOTA", ""),
                "SERVICIO": servicio_f if any(servicio_f.values()) else "",
                "PERIODO": periodo if any(periodo.values()) else ""}

    def _valores_actuales(self, excluir=()):
        valores = {c: self._valor_filtro(c) for c in self._CLAVES_FILTRO if c not in excluir}
        valores["PRUEBAS"] = self.chk_pruebas.isChecked()
        return valores

    def _cambio_pruebas(self, _estado=None):
        """Incluir o no los contratos de prueba no es un filtro del orden: reajusta las listas y repinta."""
        self._llenar_filtros()
        self._filtrar_animado()

    def _cambio_filtro(self, clave):
        """Cada filtro depende del orden en que se eligieron: al cambiar o quitar uno,
        se limpian los que se eligieron después, y cada lista muestra solo lo compatible."""
        orden = self._orden_filtros
        if clave in orden:
            posicion = orden.index(clave)
            posteriores = orden[posicion + 1:]
            del orden[posicion + 1:]
            for otra in posteriores:
                self._limpiar_filtro(otra)
            if not self._valor_filtro(clave):
                orden.remove(clave)
        elif self._valor_filtro(clave):
            orden.append(clave)
        self._llenar_filtros()
        self._filtrar_animado()

    def _llenar_filtros(self):
        """Rellena cada filtro con lo que queda disponible según los demás elegidos."""
        if self._panorama is None:
            return
        self._orden_filtros[:] = [c for c in self._orden_filtros if self._valor_filtro(c)]
        for clave in ("EJECUTIVO", "FORMA", "SERVICIO", "ANIO", "MES", "FLOTA", "CIV", "SZ"):
            sub = {"unidades": servicio.unidades_filtradas(
                self._panorama, **self._filtros_de(self._valores_actuales(excluir=(clave,))))}
            if clave in ("CIV", "SZ"):
                marca = self.chk_servicio[clave.lower()]
                marca.setEnabled(marca.isChecked() or servicio.tiene_complemento(sub['unidades'], clave.lower()))
                continue
            if clave == "FLOTA":
                self._flotas = servicio.opciones_filtro(sub)["FLOTA"]
                if self._flota and self._flota not in self._flotas:
                    self._limpiar_filtro("FLOTA")
                continue
            if clave == "SERVICIO":
                pares = [(etiqueta, valor) for valor, etiqueta in servicio.planes_servicio(sub)]
            elif clave == "ANIO":
                pares = [(str(anio), anio) for anio in servicio.anios_inicio(sub)]
            elif clave == "MES":
                self.filtros["MES"].set_opciones([(servicio.MESES[m - 1], m) for m in servicio.meses_inicio(sub)])
                continue
            else:
                pares = [(v, v) for v in servicio.opciones_filtro(sub)[clave]]
            combo = self.filtros[clave]
            actual = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(self._TITULOS_FILTRO[clave], "")
            for etiqueta, valor in pares:
                combo.addItem(etiqueta, valor)
            indice = combo.findData(actual) if actual else 0
            combo.setCurrentIndex(max(0, indice))
            combo.blockSignals(False)
        self._orden_filtros[:] = [c for c in self._orden_filtros if self._valor_filtro(c)]

    def _quitar_filtros(self):
        for clave in self._CLAVES_FILTRO:
            self._limpiar_filtro(clave)
        self._orden_filtros.clear()
        self._llenar_filtros()
        self._filtrar_animado()

    def filter_table(self):
        """Lo llama la ventana al escribir en su barra de búsqueda: aquí sugiere
        flotas bajo la barra y filtra solo al elegir una. Vacía, limpia el filtro."""
        texto = self.search_input.text().strip()
        barra = getattr(self.window(), 'search_bar', None)
        if not texto:
            self._carga_barra.detener()
            self._ocultar_lista()
            if self._ultimo_texto:
                self._ultimo_texto = ""
                if self._flota:
                    self._flota = ""
                    self._cambio_filtro("FLOTA")
            return
        self._ultimo_texto = texto
        self._carga_barra.detener()
        if barra is None or not barra.hasFocus() or texto == self._flota:
            self._ocultar_lista()
            return
        coinciden = [f for f in self._flotas if texto.casefold() in f.casefold()]
        self._sugerencias.clear()
        self._sugerencias.addItems(coinciden[:10])
        if not coinciden:
            self._ocultar_lista()
            return
        ventana = self.window()
        if self._sugerencias.parent() is not ventana:
            self._sugerencias.setParent(ventana)
            barra.installEventFilter(self)
        self._sugerencias.setFixedWidth(max(barra.width(), 260))
        self._sugerencias.move(barra.mapTo(ventana, barra.rect().bottomLeft()) + QPoint(0, 4))
        self._animar_lista(min(len(coinciden), 10) * 34 + 6)

    def _animar_lista(self, alto):
        """La lista baja desde la barra hasta su alto; al cerrar sube y desaparece."""
        self._anim_lista.stop()
        if not self._sugerencias.isVisible():
            self._sugerencias.setFixedHeight(1)
            self._sugerencias.show()
        self._sugerencias.raise_()
        self._anim_lista.setStartValue(float(self._sugerencias.height()))
        self._anim_lista.setEndValue(float(alto))
        self._anim_lista.start()

    def _ocultar_lista(self):
        if self._sugerencias.isVisible():
            self._animar_lista(0)

    def _alto_lista(self, valor):
        alto = int(valor)
        if alto <= 0:
            self._sugerencias.hide()
        else:
            self._sugerencias.setFixedHeight(alto)

    def _al_escribir_barra(self, texto):
        """Línea de carga bajo la barra mientras se esperan las sugerencias."""
        if not self.isVisible() or not texto.strip():
            self._carga_barra.detener()
            return
        barra = self.window().search_bar
        ventana = self.window()
        if self._carga_barra.parent() is not ventana:
            self._carga_barra.setParent(ventana)
        self._carga_barra.setGeometry(QRect(barra.mapTo(ventana, QPoint(8, barra.height() - 3)), QSize(barra.width() - 16, 3)))
        self._carga_barra.iniciar()

    def showEvent(self, event):
        super().showEvent(event)
        if self._panorama is None:
            QTimer.singleShot(0, self._esqueleto.iniciar_ya)
        barra = getattr(self.window(), 'search_bar', None)
        if barra is not None and not self._barra_conectada:
            self._barra_conectada = True
            barra.textChanged.connect(self._al_escribir_barra)

    def _elegir_sugerencia(self, item):
        valor = item.text()
        self._sugerencias.hide()
        self._ultimo_texto = valor
        barra = getattr(self.window(), 'search_bar', None)
        if barra is not None:
            barra.setText(valor)
        self._flota = valor
        self._cambio_filtro("FLOTA")

    def _filtrar_animado(self, *_):
        """Al aplicar o sacar un filtro, muestra la animación de carga y luego repinta."""
        self._esqueleto.iniciar_ya()
        QTimer.singleShot(40, self._repintar)
        self._fin_carga.start(550)

    def hideEvent(self, event):
        self._sugerencias.hide()
        super().hideEvent(event)

    def _filtros_activos(self):
        return self._filtros_de(self._valores_actuales())

    # ------------------------------------------------------------------ pintado
    def _repintar(self, *_):
        activos = self._filtros_activos()
        filtrando = any(v for k, v in activos.items() if k != "SIN_PRUEBAS")
        self.btn_quitar.setEnabled(filtrando)
        if self._panorama is None:
            self._pintar_kpis(None)
            for grafico in (self.grafico_mes, self.grafico_metas, self.grafico_servicio, self.grafico_ejecutivo):
                grafico.set_datos([])
            self.lbl_ej_nota.setText("")
            self.lbl_sin_fecha.hide()
            self._unidades_actuales = None
            self._pintar_fuga_clientes()
            return
        sub = servicio.filtrar_panorama(self._panorama, **activos)
        self._panorama_vista = sub
        unidades = sub['unidades']
        self._pintar_kpis(servicio.calcular_kpis(unidades))
        anios = servicio.anios_inicio(self._panorama)
        periodos = servicio.periodos_del_filtro(activos.get("PERIODO"), anio_min=anios[-1] if anios else None)
        mensual = servicio.calcular_mensual(sub, periodos=periodos)
        self._pintar_mes_a_mes(mensual)
        sin_fecha = servicio.desconectadas_sin_fecha(sub)
        self.lbl_sin_fecha.setText(
            f"{_num(sin_fecha)} unidades con estado Desconectado no tienen fecha de baja ni de término, "
            "así que no aparecen en ningún mes de este gráfico." if sin_fecha else "")
        self.lbl_sin_fecha.setVisible(bool(sin_fecha))
        self._pintar_metas(mensual, filtrando, periodos is not None)
        self.grafico_servicio.set_datos(servicio.conexion_por_servicio(unidades))
        ejecutivos = servicio.camiones_por_ejecutivo(unidades)
        self.grafico_ejecutivo.set_datos(ejecutivos['filas'])
        self._unidades_actuales = unidades
        self._pintar_fuga_clientes()
        self.lbl_ej_nota.setText(
            f"{_num(ejecutivos['de_inactivos'])} unidades de ejecutivos que ya no están no aparecen en la lista. "
            "Cuentan los estados Activación pendiente, Vigente, Vencido, Baja, Baja solicitada y Revisar "
            "(este último solo con activación activando, conectado o desconectado).")

    def _detalle_mes(self, periodo):
        if periodo is None or self._panorama_vista is None:
            return None
        return servicio.detalle_clientes_mes(self._panorama_vista, periodo)

    @staticmethod
    def _etiqueta_mes(periodo, corta=False):
        nombre = servicio.MESES_CORTOS[periodo.month - 1] if corta else servicio.MESES[periodo.month - 1]
        return nombre if corta else f"{nombre} {periodo.year}"

    def _pintar_mes_a_mes(self, mensual):
        self.grafico_mes.set_datos([dict(m, etiqueta=self._etiqueta_mes(m['periodo'])) for m in reversed(mensual)])

    def _alternar_meses_metas(self):
        self._meses_metas = 12 if self._meses_metas == 6 else 6
        self.btn_meses_metas.setText("Ver menos" if self._meses_metas > 6 else "Ver 6 meses más")
        self.grafico_metas.set_visibles(self._meses_metas, animado=True)

    def _pintar_metas(self, mensual, filtrando, por_periodo=False):
        actual = date.today()
        datos = []
        varios_anios = len({m['periodo'].year for m in mensual}) > 1
        self.btn_meses_metas.setVisible(len(mensual) > 6 and not por_periodo)
        self.btn_meses_metas.setText("Ver menos" if self._meses_metas > 6 else "Ver 6 meses más")
        for m in mensual:
            clave = (m['periodo'].year, m['periodo'].month)
            vendidas, conectadas = m['vendidas'], m['conectadas']
            if not filtrando and not self.chk_pruebas.isChecked() and clave < (actual.year, actual.month) and clave in self._registro:
                vendidas, conectadas = self._registro[clave]
            etiqueta = self._etiqueta_mes(m['periodo'], corta=True) + (f" {str(m['periodo'].year)[2:]}" if varios_anios else "")
            conectadas = min(conectadas, vendidas)
            datos.append({'etiqueta': etiqueta, 'periodo': m['periodo'], 'vendidas': vendidas, 'conectadas': conectadas,
                          'desconectadas': min(m.get('desconectadas', 0), vendidas - conectadas),
                          'meta': None if filtrando else self._metas.get(clave)})
        self.grafico_metas.set_datos(datos)
        self.grafico_metas.set_visibles(len(datos) if por_periodo else self._meses_metas)
        if filtrando:
            self.lbl_meta_nota.setText("Meta: solo sin filtros")
        elif not any(d['meta'] for d in datos):
            self.lbl_meta_nota.setText("Aún no hay metas definidas")
        else:
            self.lbl_meta_nota.setText("Metas del equipo de Volvo Connect")

    def _pintar_kpis(self, k):
        etiquetas = (self.lbl_universo, self.lbl_conectadas, self.lbl_no_conectada, self.lbl_civ, self.lbl_sz,
                     self.lbl_universo_pct, self.lbl_take_rate, self.lbl_civ_pct, self.lbl_sz_pct)
        barras = (self.barra_universo, self.barra_conectadas, self.barra_civ, self.barra_sz, self.barra_no_conectada)
        self._vaciar_desglose()
        if k is None:
            for lbl in etiquetas:
                lbl.setText("—")
            for barra in barras:
                barra.set_tramos([])
            return
        self.lbl_universo.setText(_num(k['universo']))
        self.lbl_universo_pct.setText("100%")
        self.barra_universo.set_tramos([(1.0, MARINO)])
        self.lbl_conectadas.setText(_num(k['conectadas']))
        self.lbl_take_rate.setText(_pct(k['take_rate']))
        self.barra_conectadas.set_tramos([(k['take_rate'], MARINO)])
        self.lbl_civ.setText(_num(k['civ']))
        self.lbl_civ_pct.setText(f"CIV · {_pct(k['civ_pct'])} de VC")
        self.barra_civ.set_tramos([(k['civ_pct'], MARINO)])
        self.lbl_sz.setText(_num(k['sz']))
        self.lbl_sz_pct.setText(f"SZ · {_pct(k['sz_pct'])} de VC")
        self.barra_sz.set_tramos([(k['sz_pct'], TONO_MEDIO)])
        self.lbl_no_conectada.setText(_num(k['no_conectada']))
        total = k['no_conectada'] or 1
        estados = sorted((d for d in k['desglose_no_conectada'] if d[1] > 0), key=lambda d: -d[1])
        self.barra_no_conectada.set_tramos([(n / total, COLORES_ESTADO.get(e, TONO_CLARO)) for e, n in estados])
        visibles = estados[:4]
        if len(estados) > 4:
            visibles.append(("OTROS", sum(n for _, n in estados[4:])))
        for estado, n in visibles:
            self.caja_desglose.addWidget(self._fila_desglose(estado, n, n / total))

    def _vaciar_desglose(self):
        while self.caja_desglose.count():
            item = self.caja_desglose.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _fila_desglose(estado, n, fraccion):
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(6)
        fila.addWidget(_Punto(COLORES_ESTADO.get(estado, TONO_CLARO), 8))
        fila.addWidget(_etiqueta(estado.capitalize(), f"color: {APAGADO}; font-size: 11px; font-weight: 600;"))
        fila.addStretch()
        fila.addWidget(_etiqueta(f"{_num(n)} · {_pct(fraccion)}", f"color: {TINTA}; font-size: 11px; font-weight: 700;"))
        return contenedor
