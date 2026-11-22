"""Tablero Resumen del Dashboard de Volvo Connect: cómo está el negocio de un vistazo.
Un estado del mes, cuatro KPI con su evolución, la base mes a mes, la composición de la
base, altas contra bajas y ventas contra la meta. Reutiliza los filtros, el cálculo y las
metas de `DashboardModule`; solo cambia lo que se dibuja."""
from datetime import date

import html
import math
import re
import time

import qtawesome as qta
from PyQt6.QtCore import QEvent, QObject, Qt, QPoint, QPointF, QRect, QRectF, QSize, QTimer, QPropertyAnimation, QEasingCurve, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QTextDocument
from PyQt6.QtWidgets import QBoxLayout, QButtonGroup, QCheckBox, QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from src.services import dashboard_services as servicio
from src.services import operaciones_services
from src.theme import tema
from src.ui.administracion import estilo as admin_estilo
from src.ui.compartido.comercial_estilo import ComboTarjeta, crear_sombra_panel
from src.ui.marco.sidebar_estilo import BotonMenuSidebar, qss_boton_menu
from src.ui.dashboard import (APAGADO, FONDO, LINEA, MARINO, ROJO, TINTA, TONO_CLARO, TONO_MEDIO, BarraProporcion, DashboardModule,
                              GraficoMetas, PanelMetas, SelectorMultiple, SelectorPeriodo, _GraficoBase, _Punto, _con_tema, _estilo_marca,
                              _estilo_principal, _etiqueta, _leyenda, _num, _pct, _relleno)
from src.ui.compartido.esqueleto_carga import EsqueletoCarga
from src.ui.dashboard.ab_ampliado import GraficoSalidas, VistaAmpliadaSalidas, leyenda_salidas, texto_detalle, texto_resumen_anio
from src.ui.dashboard.un_mes import AnilloEstado, ApiladaMes, MedidorMeta, PlanesMes, PuenteMes

VERDE = "#0E8F5B"
AMBAR = "#C77700"
GRIS_BASE = "#A9B6CC"
_AZUL_ENCABEZADO = "#1B2B4E"
_SUAVE_FILTRO = "#F6F8FC"
_ALTO_FRANJA_KPI = 24
_TAM_VALOR_KPI = 32     # el número es lo que más se ve de cada KPI, más que su franja   # todas las franjas azules de los KPI miden lo mismo


def _con_signo(n):
    return f"+{_num(n)}" if n > 0 else (f"−{_num(abs(n))}" if n < 0 else "0")


def _caja_flotante(painter, fuente, lineas, ancla, limites):
    """Tarjeta oscura con el detalle de lo que está bajo el mouse; la primera línea va en negrita."""
    painter.setFont(fuente)
    fm = QFontMetrics(fuente)
    ancho = max(fm.horizontalAdvance(linea) for linea in lineas) + 22
    alto = len(lineas) * (fm.height() + 2) + 14
    x = ancla.x() + 14
    if x + ancho > limites.right():
        x = ancla.x() - 14 - ancho
    y = max(limites.top(), min(ancla.y() - alto / 2, limites.bottom() - alto))
    ruta = QPainterPath()
    ruta.addRoundedRect(QRectF(x, y, ancho, alto), 9, 9)
    painter.fillPath(ruta, QColor(_AZUL_ENCABEZADO))
    painter.setPen(QColor("white"))
    for i, linea in enumerate(lineas):
        f = painter.font()
        f.setBold(i == 0)
        painter.setFont(f)
        painter.drawText(QRectF(x + 11, y + 7 + i * (fm.height() + 2), ancho - 16, fm.height() + 2),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, linea)


class MiniBarras(QWidget):
    """Barras pequeñas de los últimos meses; el mes actual se ve más fuerte."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._valores = []
        self._color = MARINO
        self.setFixedSize(72, 34)
        _con_tema(self)

    def set_valores(self, valores, color=MARINO):
        self._valores = list(valores)
        self._color = color
        self.update()

    def paintEvent(self, event):
        if not self._valores:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        n = len(self._valores)
        ancho = 3.6
        hueco = (self.width() - n * ancho) / max(1, n - 1) if n > 1 else 0
        menor, mayor = min(self._valores), max(self._valores)
        rango = (mayor - menor) or 1
        for i, v in enumerate(self._valores):
            alto = 3 + (v - menor) / rango * (self.height() - 5)
            color = QColor(_relleno(self._color))
            color.setAlphaF(1.0 if i == n - 1 else 0.3)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(i * (ancho + hueco), self.height() - alto, ancho, alto), 1.2, 1.2)
        painter.end()


class GraficoBase(_GraficoBase):
    """Unidades con servicio al cierre de cada mes: área y línea con el mes bajo el mouse destacado."""
    IZQ, DER, ARRIBA, ABAJO = 46, 16, 12, 26

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(96)
        self._hover = None        # mes bajo el mouse (da el texto del globo)
        self._hpos = 0.0          # posición (en meses) del marcador: se desliza hacia el mes bajo el mouse
        self._halfa = 0.0         # opacidad del marcador y del globo
        self._k = 0.0             # meses a la vista (0: todos); cambia con animación
        self._anim_hpos = QVariantAnimation(self)
        self._anim_hpos.setDuration(170)
        self._anim_hpos.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_hpos.valueChanged.connect(self._mover_hpos)
        self._anim_halfa = QVariantAnimation(self)
        self._anim_halfa.setDuration(150)
        self._anim_halfa.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_halfa.valueChanged.connect(self._mover_halfa)
        self._anim_halfa.finished.connect(self._fin_halfa)
        self._anim_k = QVariantAnimation(self)
        self._anim_k.setDuration(420)
        self._anim_k.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim_k.valueChanged.connect(self._mover_k)

    def set_datos(self, datos, animado=False):
        self._hover = None
        self._halfa = 0.0
        super().set_datos(datos, animado)

    def _mover_hpos(self, v):
        self._hpos = float(v)
        self.update()

    def _mover_halfa(self, v):
        self._halfa = float(v)
        self.update()

    def _fin_halfa(self):
        if self._halfa <= 0.01:
            self._hover = None

    def _mover_k(self, v):
        self._k = float(v)
        self.update()

    def set_visibles(self, cantidad, animado=False):
        """Cuántos meses se ven (los más recientes); al cambiar, la línea se desliza y aparecen los más antiguos."""
        n = len(self._datos)
        cantidad = float(max(2, min(cantidad, n))) if n > 1 else float(cantidad)
        self._anim_k.stop()
        if animado and self._k and self._k != cantidad and self.isVisible():
            self._anim_k.setStartValue(self._k)
            self._anim_k.setEndValue(cantidad)
            self._anim_k.start()
        else:
            self._k = cantidad
            self.update()

    def _vista(self):
        """(meses a la vista, ancho de un mes, índice del primer mes que asoma)."""
        n = len(self._datos)
        k = min(max(self._k if self._k else float(n), 2.0), float(n))
        area = QRectF(self.IZQ, self.ARRIBA, self.width() - self.IZQ - self.DER, self.height() - self.ARRIBA - self.ABAJO)
        return area, k, area.width() / (k - 1), max(0, n - math.ceil(k))

    def _valor_en(self, pos):
        """Valor interpolado en la posición (fraccionaria) `pos` de la serie."""
        i = max(0.0, min(len(self._datos) - 1.0, pos))
        a = int(math.floor(i))
        b = min(a + 1, len(self._datos) - 1)
        return self._datos[a]['valor'] + (self._datos[b]['valor'] - self._datos[a]['valor']) * (i - a)

    def _geometria(self):
        area, k, paso, primero = self._vista()
        n = len(self._datos)
        valores = [self._datos[i]['valor'] for i in range(primero, n)]
        valores.append(self._valor_en(n - k))   # el valor justo en el borde izquierdo
        menor, mayor = min(valores), max(valores)
        margen = (mayor - menor) * 0.18 or max(1, mayor * 0.05)
        return area, menor - margen, mayor + margen, paso, primero

    def _x(self, area, paso, i):
        return area.right() - (len(self._datos) - 1 - i) * paso

    def mouseMoveEvent(self, event):
        if len(self._datos) > 1:
            area, _lo, _hi, paso, primero = self._geometria()
            i = round(len(self._datos) - 1 + (event.position().x() - area.right()) / paso)
            nuevo = max(primero, min(len(self._datos) - 1, i))
            if nuevo != self._hover:
                aparece = self._hover is None or self._halfa < 0.05
                self._hover = nuevo
                self._anim_hpos.stop()
                if aparece:
                    self._hpos = float(nuevo)
                else:
                    self._anim_hpos.setStartValue(self._hpos)
                    self._anim_hpos.setEndValue(float(nuevo))
                    self._anim_hpos.start()
                self._animar_halfa(1.0)

    def _animar_halfa(self, destino):
        self._anim_halfa.stop()
        self._anim_halfa.setStartValue(self._halfa)
        self._anim_halfa.setEndValue(destino)
        self._anim_halfa.start()

    def leaveEvent(self, event):
        if self._hover is not None:
            self._animar_halfa(0.0)

    def paintEvent(self, event):
        if len(self._datos) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area, lo, hi, paso, primero = self._geometria()
        n = len(self._datos)
        y = lambda v: area.bottom() - (v - lo) / (hi - lo) * area.height()
        painter.setFont(self._fuente(10))
        for k in range(4):
            valor = lo + (hi - lo) * k / 3
            painter.setPen(QPen(tema.fondo(LINEA), 1))
            painter.drawLine(QPointF(area.left(), y(valor)), QPointF(area.right(), y(valor)))
            self._texto(painter, QRectF(0, y(valor) - 8, self.IZQ - 8, 16), Qt.AlignmentFlag.AlignRight, _num(round(valor)), APAGADO)
        puntos = [QPointF(self._x(area, paso, i), y(d['valor'])) for i, d in enumerate(self._datos)]
        # La línea y el área se recortan en el borde izquierdo: al ampliar, los meses antiguos entran desde ahí
        painter.save()
        painter.setClipRect(QRectF(area.left(), 0, self.width() - area.left(), self.height()))
        desde = max(0, primero - 1)
        relleno = QPainterPath(QPointF(puntos[desde].x(), area.bottom()))
        for p in puntos[desde:]:
            relleno.lineTo(p)
        relleno.lineTo(QPointF(puntos[-1].x(), area.bottom()))
        relleno.closeSubpath()
        suave = QColor(_relleno(MARINO))
        suave.setAlphaF(0.12)
        painter.fillPath(relleno, suave)
        linea = QPainterPath(puntos[desde])
        for p in puntos[desde + 1:]:
            linea.lineTo(p)
        pen = QPen(_relleno(MARINO), 2.4)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(linea)
        painter.restore()
        # Con muchos meses se rotula uno de cada dos (o tres) para que no se amontonen
        salto = 1 if paso >= 34 else 2 if paso >= 17 else 3
        painter.setFont(self._fuente(10))
        for i in range(primero, n):
            x = puntos[i].x()
            if x < area.left() - 2 or (n - 1 - i) % salto:
                continue
            self._texto(painter, QRectF(x - 24, self.height() - self.ABAJO + 4, 48, 16),
                        Qt.AlignmentFlag.AlignHCenter, self._datos[i]['etiqueta'], APAGADO)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_relleno(MARINO))
        painter.drawEllipse(puntos[-1], 4.5, 4.5)
        painter.setFont(self._fuente(11, True))
        self._texto(painter, QRectF(puntos[-1].x() - 90, puntos[-1].y() - 24, 84, 16), Qt.AlignmentFlag.AlignRight,
                    _num(self._datos[-1]['valor']), TINTA)
        if self._hover is not None and self._halfa > 0.01:
            d = self._datos[self._hover]
            pos = max(float(primero), self._hpos)
            p = QPointF(area.right() - (n - 1 - pos) * paso, y(self._valor_en(pos)))
            a = self._halfa
            painter.setOpacity(a)
            painter.setPen(QPen(tema.fondo("#9AA8C0"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(p.x(), area.top()), QPointF(p.x(), area.bottom()))
            painter.setPen(QPen(_relleno(MARINO), 2.4))
            painter.setBrush(tema.fondo("#FFFFFF"))
            painter.drawEllipse(p, 3 + 2 * a, 3 + 2 * a)
            _caja_flotante(painter, self._fuente(11), [d['mes'], f"Base: {_num(d['valor'])}", f"Variación del mes: {_con_signo(d['neto'])}"],
                           p, QRectF(self.rect()))
            painter.setOpacity(1.0)
        painter.end()


class GraficoAltasBajas(_GraficoBase):
    """Altas hacia arriba y bajas hacia abajo por mes, con el saldo del mes como punto."""
    IZQ, DER, ARRIBA, ABAJO = 38, 10, 12, 26
    mes_clicado = pyqtSignal(int, str)   # posición del mes y 'altas' (mitad de arriba) o 'bajas' (mitad de abajo)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(96)
        self._hover = None

    def _area(self):
        return QRectF(self.IZQ, self.ARRIBA, self.width() - self.IZQ - self.DER, self.height() - self.ARRIBA - self.ABAJO)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._datos and self._hover is not None:
            area = self._area()
            lo, hi = self._rango()
            cero = area.bottom() - (0 - lo) / (hi - lo) * area.height()
            self.mes_clicado.emit(self._hover, 'altas' if event.position().y() < cero else 'bajas')

    def _rango(self):
        mayor = max(1, max(d['altas'] for d in self._datos)) * 1.15
        menor = max(1, max(d['bajas'] for d in self._datos)) * 1.15
        return -menor, mayor

    def mouseMoveEvent(self, event):
        if self._datos:
            area = self._area()
            paso = area.width() / len(self._datos)
            i = int((event.position().x() - area.left()) // paso)
            nuevo = i if 0 <= i < len(self._datos) else None
            if nuevo != self._hover:
                self._hover = nuevo
                self.setCursor(Qt.CursorShape.PointingHandCursor if nuevo is not None else Qt.CursorShape.ArrowCursor)
                self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def paintEvent(self, event):
        if not self._datos:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._area()
        lo, hi = self._rango()
        y = lambda v: area.bottom() - (v - lo) / (hi - lo) * area.height()
        paso = area.width() / len(self._datos)
        ancho = paso * 0.56
        painter.setFont(self._fuente(10))
        for valor in sorted({round(lo * 0.75 / 10) * 10, 0, round(hi * 0.5 / 10) * 10, round(hi * 0.9 / 10) * 10}):
            painter.setPen(QPen(tema.fondo("#9AA8C0" if valor == 0 else LINEA), 1))
            painter.drawLine(QPointF(area.left(), y(valor)), QPointF(area.right(), y(valor)))
            self._texto(painter, QRectF(0, y(valor) - 8, self.IZQ - 6, 16), Qt.AlignmentFlag.AlignRight,
                        (f"+{valor}" if valor > 0 else str(valor)), APAGADO)
        for i, d in enumerate(self._datos):
            cx = area.left() + paso * i + paso / 2
            if i == self._hover:
                painter.fillRect(QRectF(cx - paso / 2, area.top(), paso, area.height()), QColor(120, 140, 175, 28))
            self._barra(painter, QRectF(cx - ancho / 2, y(d['altas']), ancho, y(0) - y(d['altas'])), MARINO, 3)
            self._barra(painter, QRectF(cx - ancho / 2, y(0), ancho, y(-d['bajas']) - y(0)), ROJO, 3)
            painter.setPen(QPen(tema.fondo("#FFFFFF"), 1.5))
            painter.setBrush(tema.fondo(TINTA))
            painter.drawEllipse(QPointF(cx, y(d['neto'])), 3.6, 3.6)
            self._texto(painter, QRectF(cx - paso / 2, self.height() - self.ABAJO + 4, paso, 16),
                        Qt.AlignmentFlag.AlignHCenter, d['etiqueta'], APAGADO)
        if self._hover is not None:
            d = self._datos[self._hover]
            cx = area.left() + paso * self._hover + paso / 2
            _caja_flotante(painter, self._fuente(11), [d['mes'], f"Altas: {_num(d['altas'])}", f"Bajas: {_num(d['bajas'])}",
                                                       f"Variación: {_con_signo(d['neto'])} ({'salió bien' if d['neto'] > 0 else 'salió mal' if d['neto'] < 0 else 'sin cambio'})",
                                                       "Presiona para ver las flotas", "arriba: nuevos · abajo: bajas"],
                           QPointF(cx, area.center().y()), QRectF(self.rect()))
        painter.end()


class _Marca(QWidget):
    """Marca de leyenda para lo que no es una barra: punto de saldo o línea de meta."""

    def __init__(self, forma):
        super().__init__()
        self._forma = forma
        self.setFixedSize(18 if forma == 'linea' else 11, 11)
        _con_tema(self)

    def paintEvent(self, evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._forma == 'linea':
            p.setPen(QPen(_relleno(MARINO), 2, Qt.PenStyle.DashLine))
            p.drawLine(0, 5, self.width(), 5)
        else:
            p.setPen(QPen(tema.fondo("#FFFFFF"), 1.5))
            p.setBrush(tema.fondo(TINTA))
            p.drawEllipse(QPointF(5.5, 5.5), 4, 4)
        p.end()


def _agregar_marca(leyenda, forma, texto):
    fila = leyenda.layout()
    pos = fila.count() - 1
    fila.insertWidget(pos, _Marca(forma))
    fila.insertWidget(pos + 1, _etiqueta(texto, f"color: {APAGADO}; font-size: 11px;"))


class _RielNavegacion(QFrame):
    """Barra lateral angosta, como el menú de la ventana: un botón con icono por cada pestaña del Dashboard y otro para
    volver a abrir los filtros. Aparece cuando la caja de filtros está oculta."""
    ANCHO = 56
    pestana = pyqtSignal(int)
    filtros = pyqtSignal()
    ICONOS = {"Resumen": "fa5s.chart-line", "Qué mejorar": "fa5s.crosshairs"}
    _ESTILO_BOTON = ("QPushButton { background: transparent; border: none; border-radius: 12px; } "
                     "QPushButton:hover { background: rgba(255,255,255,0.12); } "
                     "QPushButton:checked { background: rgba(255,255,255,0.20); }")

    def __init__(self):
        super().__init__()
        self.setObjectName("rielDashboard")
        self.setFixedWidth(self.ANCHO)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QFrame#rielDashboard { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1B2B4E, stop:1 #2C4A80); "
                           "border: none; border-radius: 14px; }")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(8, 12, 8, 12)
        self._lay.setSpacing(8)
        self._botones = []
        self._sitio_pestanas = 0
        self._btn_expandir = self._crear_boton('fa5s.angle-double-right', "Expandir el menú y los filtros")
        self._btn_expandir.clicked.connect(self.filtros.emit)
        self._lay.addWidget(self._btn_expandir)
        self._lay.addWidget(self._division())
        self._lay.addWidget(self._division())
        self._btn_filtros = self._crear_boton('fa5s.sliders-h', "Mostrar los filtros")
        self._btn_filtros.setCheckable(False)
        self._btn_filtros.clicked.connect(self.filtros.emit)
        self._lay.addWidget(self._btn_filtros)
        self._lay.addStretch(1)

    @staticmethod
    def _division():
        division = QFrame()
        division.setFixedHeight(1)
        division.setStyleSheet("background: rgba(255,255,255,0.22); border: none;")
        return division

    def _crear_boton(self, icono, ayuda):
        boton = QPushButton()
        boton.setFixedSize(40, 40)
        boton.setIcon(qta.icon(icono, color="white"))
        boton.setIconSize(QSize(18, 18))
        boton.setToolTip(ayuda)
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.setStyleSheet(self._ESTILO_BOTON)
        return boton

    def poner_pestanas(self, nombres):
        """Un botón por pestaña, sobre la línea que separa a los filtros."""
        for boton in self._botones:
            boton.deleteLater()
        self._botones = []
        for i, nombre in enumerate(nombres):
            boton = self._crear_boton(self.ICONOS.get(nombre, 'fa5s.th-large'), nombre)
            boton.setCheckable(True)
            boton.clicked.connect(lambda _c, k=i: self.pestana.emit(k))
            self._lay.insertWidget(2 + i, boton)
            self._botones.append(boton)

    def marcar(self, indice):
        for i, boton in enumerate(self._botones):
            boton.setChecked(i == indice)

class _AreaConFiltros(QWidget):
    """Zona de contenido sobre la que flota la caja de filtros: avisa cuando cambia de tamaño."""
    reubicar = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.reubicar is not None:
            self.reubicar()


class _FiltroRueda(QObject):
    """Filtro de eventos de la rueda del tablero: `atender(evento)` devuelve True si ya lo resolvió."""

    def __init__(self, atender, padre):
        super().__init__(padre)
        self._atender = atender

    def eventFilter(self, objeto, evento):
        return evento.type() == QEvent.Type.Wheel and bool(self._atender(evento))


class _PilaActual(QStackedWidget):
    """Pila que pide solo el alto de la página visible: las páginas ocultas no agrandan la caja."""

    def minimumSizeHint(self):
        actual = self.currentWidget()
        if actual is None:
            return super().minimumSizeHint()
        # Cuenta también el alto mínimo que fijó cada gráfico: sin él la caja se encogía y cortaba el dibujo
        sugerido = actual.minimumSizeHint()
        return QSize(max(0, sugerido.width()), max(0, sugerido.height(), actual.minimumHeight()))


class _KpiCaja(QFrame):
    """KPI compacto: franja azul con el nombre, el valor, su variación y barras de los últimos meses."""
    clicked = pyqtSignal()

    def __init__(self, titulo, parent=None):
        super().__init__(parent)
        self._clicable = False
        self.setObjectName("kpiResumen")
        self.setStyleSheet("QFrame#kpiResumen { background: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 14px; }")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(1, 1, 1, 1)
        raiz.setSpacing(0)
        cab = QLabel(titulo.upper())
        cab.setStyleSheet(f"background: transparent; color: {APAGADO}; font-size: 9px; font-weight: 800; letter-spacing: 0.2px; "
                          "padding: 0 0 0 14px; border: none;")
        cab.setFixedHeight(_ALTO_FRANJA_KPI + 6)
        self._cab, self._titulo_base = cab, titulo
        lay_cab = QHBoxLayout(cab)
        lay_cab.setContentsMargins(0, 0, 0, 0)
        lay_cab.addStretch(1)
        self.pastilla = _nueva_pastilla_universo(15, 9)
        lay_cab.addWidget(self.pastilla)
        self.chip_tendencia = QLabel()
        self.chip_tendencia.setFixedHeight(20)
        self.chip_tendencia.hide()
        lay_cab.addWidget(self.chip_tendencia)
        lay_cab.setContentsMargins(0, 6, 10, 0)
        raiz.addWidget(cab)
        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent;")
        fila = QHBoxLayout(cuerpo)
        fila.setContentsMargins(14, 0, 14, 12)
        fila.setSpacing(8)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.valor = _etiqueta("—", f"color: {TINTA}; font-size: {_TAM_VALOR_KPI}px; font-weight: 800;")
        self.delta = _etiqueta("", f"color: {APAGADO}; font-size: 12px;")
        self.delta.setTextFormat(Qt.TextFormat.RichText)
        self._fila_chips = QHBoxLayout()
        self._fila_chips.setSpacing(6)
        self._fila_chips.setContentsMargins(0, 0, 0, 0)
        self.progreso = BarraProporcion()
        self.progreso.hide()
        self.extra = _etiqueta("", f"color: {APAGADO}; font-size: 10.5px;")
        self.extra.setTextFormat(Qt.TextFormat.RichText)
        self.extra.setWordWrap(True)
        fila_valor = QHBoxLayout()
        fila_valor.setContentsMargins(0, 0, 0, 0)
        fila_valor.addWidget(self.valor)
        fila_valor.addStretch(1)
        self.barras = MiniBarras()
        fila_valor.addWidget(self.barras, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(fila_valor)
        self._fila_chips.addWidget(self.delta)
        self._fila_chips.addStretch(1)
        col.addLayout(self._fila_chips)
        col.addWidget(self.progreso)
        col.addWidget(self.extra)
        fila.addLayout(col, 1)
        raiz.addWidget(cuerpo, 1)

    def set_clicable(self, ayuda):
        """La tarjeta entera abre algo al presionarla (emite `clicked`)."""
        self._clicable = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(ayuda)

    def mousePressEvent(self, event):
        if self._clicable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def poner_universo(self, texto, titulo=None):
        """Etiqueta de universo en el encabezado y, si se da, un título distinto al de siempre. Con un título
        propio la etiqueta sobra: el título ya dice de qué camiones habla. Las tarjetas son angostas: «Flota»."""
        self._cab.setText((titulo or self._titulo_base).upper())
        _poner_universo(self.pastilla, None)   # el aviso de los filtros ya explica qué camiones cuenta cada tarjeta

    _TONOS_CHIP = {'verde': ("#E3F4EC", "#0E8F5B"), 'rojo': ("#FBE9E7", "#C2362D"), 'neutro': ("#E3EAF7", "#2F5BB0")}

    def poner_tendencia(self, cambio, texto="", ayuda=""):
        """Chip junto al título: sube (verde) o baja (rojo) frente al mes pasado; `cambio` None lo oculta."""
        if cambio is None:
            self.chip_tendencia.hide()
            return
        tono = 'verde' if cambio > 0 else 'rojo' if cambio < 0 else 'neutro'
        fondo, color = self._TONOS_CHIP[tono]
        flecha = "↑" if cambio > 0 else "↓" if cambio < 0 else "→"
        self.chip_tendencia.setText(f"{flecha} {texto}")
        self.chip_tendencia.setStyleSheet(f"background: {fondo}; color: {color}; border: none; border-radius: 10px; padding: 0 6px; "
                                          "font-size: 10.5px; font-weight: 800;")
        self.chip_tendencia.setToolTip(ayuda)
        self.chip_tendencia.show()

    def poner(self, valor, delta="", extra="", barras=(), color_barras=MARINO, progreso=None, chips=()):
        self.valor.setText(valor)
        self.delta.setText(delta)
        self.delta.setVisible(bool(delta))
        while self._fila_chips.count() > 2:
            item = self._fila_chips.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        for i, (texto, tono) in enumerate(chips):
            fondo, color = self._TONOS_CHIP[tono]
            chip = QLabel(texto)
            chip.setStyleSheet(f"background: {fondo}; color: {color}; border: none; border-radius: 10px; padding: 0 8px; "
                               "font-size: 11.5px; font-weight: 800;")
            chip.setFixedHeight(20)
            self._fila_chips.insertWidget(i, chip)
        self.extra.setText(extra)
        self.extra.setVisible(bool(extra))
        self.barras.set_valores(barras, color_barras)
        self.barras.setVisible(len(barras) > 1)   # con un solo mes serían un punto suelto que además le quita ancho al texto
        if progreso is None:
            self.progreso.hide()
        else:
            self.progreso.set_tramos([(progreso, MARINO)])
            self.progreso.show()


class BarraComposicion(QWidget):
    """Barra horizontal que reparte los camiones por estado (la versión ancha del anillo)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._partes, self._texto = [], ""
        self.setFixedHeight(34)
        _con_tema(self)

    def set_datos(self, partes, texto):
        self._partes, self._texto = partes, texto
        self.update()

    def paintEvent(self, evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        caja = QRectF(6, 4, self.width() - 12, 26)
        ruta = QPainterPath()
        ruta.addRoundedRect(caja, 13, 13)
        p.setClipPath(ruta)
        x = caja.left()
        for fraccion, color in self._partes:
            ancho = caja.width() * fraccion
            if ancho > 0:
                p.fillRect(QRectF(x, caja.top(), ancho, caja.height()), _relleno(color))
            x += ancho
        p.setClipping(False)
        if self._partes and self._partes[0][0] > 0.08:
            f = QFont(self.font())
            f.setPixelSize(13)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("white"))
            p.drawText(QRectF(caja.left() + 14, caja.top(), caja.width() * self._partes[0][0] - 20, caja.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{self._texto} conectados")
        p.end()


class _KpiAlertas(QFrame):
    """Tarjeta angosta del final de los KPI: un triángulo de alerta con la cantidad de avisos; al presionarla se
    despliega (o se oculta) la tira «Por atender»."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiResumen")
        self._abierta = False
        self._cantidad = 0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(86)
        self.setStyleSheet("QFrame#kpiResumen { background: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 14px; } "
                           "QFrame#kpiResumen:hover { background: #FFFBF2; border: 1px solid #E9B35B; }")
        self._hover = QVariantAnimation(self)
        self._hover.setDuration(180)
        self._hover.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover.valueChanged.connect(lambda v: self._icono.set_hover(float(v)))
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(1, 1, 1, 1)
        raiz.setSpacing(0)
        cab = QLabel("ALERTAS")
        cab.setFixedHeight(_ALTO_FRANJA_KPI + 6)
        cab.setStyleSheet(f"background: transparent; color: {APAGADO}; font-size: 10px; font-weight: 800; letter-spacing: 1px; "
                          "padding: 0 12px; border: none;")
        raiz.addWidget(cab)
        self._icono = _IconoAlerta()
        raiz.addWidget(self._icono, 1)
        _con_tema(self)

    def poner(self, cantidad):
        self._cantidad = cantidad
        self._icono.set_cantidad(cantidad)
        self.setToolTip(f"{cantidad} cosas por atender. Presiona para verlas." if cantidad else "Nada por atender.")

    def set_abierta(self, abierta):
        self._abierta = abierta
        self._icono.set_abierta(abierta)

    def _animar_hover(self, destino):
        self._hover.stop()
        self._hover.setStartValue(self._icono._hover)
        self._hover.setEndValue(destino)
        self._hover.start()

    def enterEvent(self, event):
        self._animar_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animar_hover(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _IconoAlerta(QWidget):
    """Círculo ámbar con el triángulo de alerta y, en su esquina, una insignia roja con la cantidad."""

    def __init__(self):
        super().__init__()
        self._cantidad = 0
        self._abierta = False
        self._hover = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        _con_tema(self)

    def set_hover(self, valor):
        self._hover = valor
        self.update()

    def set_cantidad(self, cantidad):
        self._cantidad = cantidad
        self.update()

    def set_abierta(self, abierta):
        self._abierta = abierta
        self.update()

    def paintEvent(self, evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        centro = QPointF(self.width() / 2, self.height() / 2)
        h = self._hover
        radio = 20.0 + 2.0 * h
        ambar = QColor("#E08A00")
        p.setPen(Qt.PenStyle.NoPen)
        if self._abierta:
            relleno = ambar
        else:
            claro, medio = QColor("#FDF0D5"), QColor("#F8D48A")
            relleno = QColor(round(claro.red() + (medio.red() - claro.red()) * h), round(claro.green() + (medio.green() - claro.green()) * h),
                             round(claro.blue() + (medio.blue() - claro.blue()) * h))
        if h > 0:
            halo = QColor(224, 138, 0, round(46 * h))
            p.setBrush(halo)
            p.drawEllipse(centro, radio + 5 * h, radio + 5 * h)
        p.setBrush(relleno)
        p.drawEllipse(centro, radio, radio)
        lado = round(20 + 3 * h)
        icono = qta.icon('fa5s.exclamation-triangle', color="white" if self._abierta else "#C77700")
        p.drawPixmap(int(centro.x() - lado / 2), int(centro.y() - lado / 2), icono.pixmap(lado, lado))
        if self._cantidad:
            texto = str(self._cantidad)
            fuente = p.font()
            fuente.setPixelSize(11)
            fuente.setBold(True)
            p.setFont(fuente)
            ancho = max(19.0, QFontMetrics(fuente).horizontalAdvance(texto) + 10)
            rect = QRectF(centro.x() + radio - ancho / 2 - 2, centro.y() - radio - 4, ancho, 19)
            p.setBrush(tema.fondo("#FFFFFF"))
            p.drawRoundedRect(rect.adjusted(-2, -2, 2, 2), 11.5, 11.5)
            p.setBrush(QColor("#D64541"))
            p.drawRoundedRect(rect, 9.5, 9.5)
            p.setPen(QColor("white"))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, texto)
        p.end()

class _ColumnaSinAltoPorAncho(QVBoxLayout):
    """Columna del tablero sin «alto según ancho»: con textos que se parten en líneas, el área con scroll pedía
    siempre la altura cómoda y mostraba scroll aunque las cajas pudieran encogerse; así solo aparece si ya no caben."""

    def hasHeightForWidth(self):
        return False


_UNIVERSO_FILTRADOS, _UNIVERSO_FLOTA, _UNIVERSO_META = "Filtrados", "Toda la flota", "Meta del equipo"


def _nueva_pastilla_universo(alto=17, tamano=10):
    """Etiqueta pequeña que dice de qué camiones habla una caja cuando Año o Mes acotan las unidades."""
    pastilla = QLabel()
    pastilla.setFixedHeight(alto)
    pastilla.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    pastilla.hide()
    pastilla._tamano = tamano
    return pastilla


def _texto_pct_chip(c):
    """Texto del chip de variación: un decimal, o ninguno desde 100% para que quepa junto al título."""
    if c is None:
        return ""
    return (f"{abs(c):.0f}%" if abs(c) >= 100 else f"{abs(c):.1f}%").replace('.', ',')


def _poner_universo(pastilla, texto):
    """Muestra la etiqueta con ese texto (azul para Filtrados, ámbar para Toda la flota) o la oculta si es None."""
    if not texto:
        pastilla.hide()
        return
    filtrados = texto in (_UNIVERSO_FILTRADOS, _UNIVERSO_META)
    fondo, tinta = ("#DCE6F7", "#1B2B4E") if filtrados else ("#FBE9B7", "#7A5200")
    pastilla.setText(texto)
    pastilla.setStyleSheet(f"background: {fondo}; color: {tinta}; border: none; border-radius: {pastilla.height() // 2}px; "
                           f"padding: 0 9px; font-size: {pastilla._tamano}px; font-weight: 800; letter-spacing: 0;")
    ayudas = {_UNIVERSO_FILTRADOS: "Camiones que dejan los filtros de Año y Mes (contrato actual iniciado en el período).",
              _UNIVERSO_META: "Meta de ventas del equipo: no cambia con los filtros de Año y Mes.",
              _UNIVERSO_FLOTA: "Todo el movimiento del período en la flota, sin importar cuándo empezó el contrato actual de cada camión."}
    pastilla.setToolTip(ayudas[texto])
    pastilla.show()


def _agregar_pastilla_caja(caja):
    pastilla = _nueva_pastilla_universo()
    caja.fila_cab.insertWidget(1, pastilla, 0, Qt.AlignmentFlag.AlignTop)
    caja.fila_cab.insertSpacing(1, 10)
    return pastilla


def _ayuda_encabezado(caja, texto):
    """Texto de ayuda al pasar el mouse por el título y el subtítulo de una caja."""
    caja.lbl_titulo.setToolTip(texto)
    caja.lbl_subtitulo.setToolTip(texto)


class _ChipClicable(QFrame):
    """Chip del estado del mes: con `clicked` emite al hacer clic con el botón izquierdo."""
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.cursor().shape() == Qt.CursorShape.PointingHandCursor:
            self.clicked.emit()
        super().mousePressEvent(event)


class AnilloComposicion(QWidget):
    """Anillo de proporciones con el porcentaje principal al centro; cada tramo se puede presionar."""
    zona_clicada = pyqtSignal(int)
    GROSOR = 17

    def __init__(self, parent=None):
        super().__init__(parent)
        # Se achica si el tablero no alcanza (interfaz pequeña) y el centro escala con él
        self.setMinimumSize(112, 112)
        self.setMaximumSize(150, 150)
        self.setMouseTracking(True)
        self._tramos = []
        self._centro = ("", "")
        self._hover = -1
        self._origen_tramos = []
        self._destino_tramos = []
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(380)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._paso)
        self._anim.finished.connect(self._fin)
        _con_tema(self)

    def sizeHint(self):
        return QSize(150, 150)

    def _paso(self, t):
        t = float(t)
        self._tramos = [(o[0] + (n[0] - o[0]) * t, n[1]) for o, n in zip(self._origen_tramos, self._destino_tramos)]
        self.update()

    def _fin(self):
        self._tramos = self._destino_tramos
        self.update()

    def set_datos(self, tramos, texto, subtexto, animado=False):
        nuevos = [(max(0.0, min(1.0, f)), c) for f, c in tramos]
        self._anim.stop()
        self._centro = (texto, subtexto)
        self._hover = -1
        self._destino_tramos = nuevos
        if animado and self.isVisible() and nuevos and len(nuevos) == len(self._tramos):
            self._origen_tramos = list(self._tramos)
            self._anim.start()
            return
        self._tramos = nuevos
        self.update()

    def _arcos(self):
        """(índice, ángulo inicial, extensión) en grados, desde arriba y en sentido horario; los tramos chicos se ven."""
        arcos, inicio = [], 0.0
        for i, (fraccion, _c) in enumerate(self._tramos):
            if fraccion <= 0:
                continue
            extension = max(4.0, fraccion * 360.0)
            arcos.append((i, inicio, extension))
            inicio += extension
        escala = 360.0 / inicio if inicio > 360.0 else 1.0
        return [(i, a * escala, e * escala) for i, a, e in arcos]

    def _tramo_en(self, pos):
        c = QPointF(self.width() / 2, self.height() / 2)
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        radio = (min(self.width(), self.height()) - 16) / 2
        if not radio - self.GROSOR - 3 <= math.hypot(dx, dy) <= radio + self.GROSOR / 2 + 3:
            return -1
        angulo = math.degrees(math.atan2(dx, -dy)) % 360.0   # 0° arriba, horario
        for i, a, e in self._arcos():
            if a <= angulo < a + e:
                return i
        return -1

    def mouseMoveEvent(self, event):
        i = self._tramo_en(event.position())
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            i = self._tramo_en(event.position())
            if i >= 0:
                self.zona_clicada.emit(i)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        lado = min(self.width(), self.height()) - 16
        marco = QRectF((self.width() - lado) / 2, (self.height() - lado) / 2, lado, lado)
        pista = QPen(tema.fondo("#EDF0F6"), self.GROSOR)
        painter.setPen(pista)
        painter.drawEllipse(marco)
        for i, inicio, extension in self._arcos():
            pen = QPen(_relleno(self._tramos[i][1]), self.GROSOR + (3 if i == self._hover else 0))
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            hueco = 1.6 if len(self._arcos()) > 1 else 0.0
            painter.drawArc(marco, int((90.0 - inicio - hueco / 2) * 16), int(-max(0.5, extension - hueco) * 16))
        texto, subtexto = self._centro
        esc = min(1.0, min(self.width(), self.height()) / 150.0)
        painter.setFont(self._fuente(max(16, int(25 * esc)), True))
        painter.setPen(tema.texto(TINTA))
        painter.drawText(QRectF(0, self.height() / 2 - 26, self.width(), 30), Qt.AlignmentFlag.AlignCenter, texto)
        painter.setFont(self._fuente(max(10, int(12 * esc))))
        painter.setPen(tema.texto(APAGADO))
        painter.drawText(QRectF(0, self.height() / 2 + 5, self.width(), 18), Qt.AlignmentFlag.AlignCenter, subtexto)
        painter.end()

    def _fuente(self, px, negrita=False):
        f = QFont(self.font())
        f.setPixelSize(px)
        f.setBold(negrita)
        return f


class _FilaClicable(QFrame):
    """Fila de una lista del tablero: se resalta al pasar el mouse y emite `clicked` con el botón izquierdo."""
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("filaClicable")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QFrame#filaClicable { background: transparent; border: none; border-radius: 8px; } "
                           "QFrame#filaClicable:hover { background: #EEF2F8; }")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _signo_html(n, texto=""):
    color = VERDE if n > 0 else ("#C2362D" if n < 0 else APAGADO)
    return f'<span style="color:{color}; font-weight:700;">{_con_signo(n)}</span>' + (f" {texto}" if texto else "")


class DashboardResumenModule(DashboardModule):
    """Primer tablero del Dashboard: el estado del negocio de Volvo Connect."""
    CON_TITULO = False
    FORMA_ESQUELETO = 'dashboard'

    # Mostrar u ocultar la caja de filtros vale para todas las pestañas del Dashboard
    _filtros_visibles_compartido = True

    @property
    def _filtros_visibles(self):
        return DashboardResumenModule._filtros_visibles_compartido

    @_filtros_visibles.setter
    def _filtros_visibles(self, valor):
        DashboardResumenModule._filtros_visibles_compartido = valor

    def mostrar_cambio_pestana(self):
        self._reubicar_filtros()
        super().mostrar_cambio_pestana()

    def copiar_filtros_de(self, otro):
        """Los filtros valen para las tres pestañas: al llegar, esta toma los que dejó puestos la anterior."""
        if otro is self or not hasattr(otro, 'filtros'):
            return
        for clave in ("EJECUTIVO", "FORMA", "SERVICIO"):
            destino, origen = self.filtros[clave], otro.filtros[clave]
            destino._opciones, destino._elegidos = list(origen._opciones), list(origen._elegidos)
            destino._texto()
        destino, origen = self.filtros["PERIODO"], otro.filtros["PERIODO"]
        destino._anios, destino._meses = list(origen._anios), list(origen._meses)
        destino._anio, destino._elegidos = origen._anio, list(origen._elegidos)
        destino._texto()
        for clave, marca in self.chk_servicio.items():
            marca.blockSignals(True)
            marca.setChecked(otro.chk_servicio[clave].isChecked())
            marca.blockSignals(False)
        for nombre in ("chk_pruebas", "chk_no_aplica"):
            marca = getattr(self, nombre)
            marca.blockSignals(True)
            marca.setChecked(getattr(otro, nombre).isChecked())
            marca.blockSignals(False)
        self._flota = otro._flota
        self._orden_filtros[:] = list(otro._orden_filtros)
        self._fichas_puestas = None   # el repintado lo hace la carga de la pestaña, una sola vez

    def region_deslizante(self):
        """Zona del módulo que se desliza al cambiar de pestaña: el contenido, sin la caja de filtros."""
        x0, _y0, _alto, _fusionado = self._origen_filtros()
        izquierda = x0 + (self.ANCHO_FILTROS if self._filtros_visibles else _RielNavegacion.ANCHO) + 4
        return QRect(izquierda, 0, max(0, self.width() - izquierda), self.height())

    def _rueda_tablero(self, evento):
        """Rueda sobre el tablero: se mueve el scroll y, estando ya en el borde (o sin scroll), pasa a la pestaña
        siguiente o anterior. Devuelve True si el evento se atendió aquí."""
        tabs = getattr(getattr(self, '_selector_grupo', None), '_tabs', None)
        giro = evento.angleDelta().y()
        if tabs is None or not hasattr(tabs, 'pasar_por_rueda') or self._ampliado.abierta or giro == 0:
            return False
        barra = self._scroll_tablero.verticalScrollBar()
        if barra.maximum() > 0 and not ((giro < 0 and barra.value() >= barra.maximum()) or (giro > 0 and barra.value() <= barra.minimum())):
            return False
        if time.monotonic() - getattr(self, '_ultimo_scroll', 0.0) < 0.35:   # inercia del scroll recién terminado
            evento.accept()
            return True
        return tabs.pasar_por_rueda(evento)

    def wheelEvent(self, evento):
        """La rueda sobre un fondo sin scroll propio pasa a la pestaña siguiente o anterior del Dashboard."""
        tabs = getattr(getattr(self, '_selector_grupo', None), '_tabs', None)
        # Si el tablero tiene scroll, la rueda solo llega aquí cuando ya está en el borde; justo después de
        # moverse se ignora para que la inercia no cambie de pestaña sin querer
        if time.monotonic() - getattr(self, '_ultimo_scroll', 0.0) < 0.35:
            evento.accept()
            return
        if (tabs is None or not hasattr(tabs, 'pasar_por_rueda') or self._ampliado.abierta
                or evento.position().toPoint().x() < self.region_deslizante().left()
                or not tabs.pasar_por_rueda(evento)):
            super().wheelEvent(evento)

    # ------------------------------------------------------------------ interfaz
    def _setup_ui(self):
        self.setStyleSheet(f"DashboardResumenModule {{ background: {FONDO}; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        externo = QVBoxLayout(self)
        externo.setContentsMargins(15, 15, 15, 15)
        externo.setSpacing(0)
        cuerpo_fila = _AreaConFiltros()
        cuerpo_fila.setStyleSheet("background: transparent;")
        fila_ext = QHBoxLayout(cuerpo_fila)
        fila_ext.setContentsMargins(0, 10, 0, 0)
        self._fila_ext = fila_ext
        fila_ext.setSpacing(0)
        self._cabecera = QWidget(self)
        self._cabecera.hide()
        self._area_filtros = cuerpo_fila
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll_tablero = scroll
        fila_ext.addWidget(scroll, 1)
        externo.addWidget(cuerpo_fila, 1)
        # La caja de filtros y su riel flotan sobre el espacio libre de la izquierda: el tablero no se mueve
        # La caja y su riel cuelgan del módulo (no de la zona de abajo) para poder subir hasta el borde de arriba, junto al encabezado
        self._crear_caja_filtros().setParent(self)
        self._crear_riel_filtros().setParent(self)
        cuerpo_fila.reubicar = self._reubicar_filtros
        self._reubicar_filtros()
        contenido = QWidget()
        contenido.setStyleSheet("background: transparent;")
        scroll.setWidget(contenido)
        scroll.verticalScrollBar().valueChanged.connect(lambda _: self._sugerencias.hide())
        scroll.verticalScrollBar().valueChanged.connect(lambda _: setattr(self, '_ultimo_scroll', time.monotonic()))
        self._filtro_rueda = _FiltroRueda(self._rueda_tablero, scroll)
        scroll.viewport().installEventFilter(self._filtro_rueda)
        centrado = QHBoxLayout(contenido)
        centrado.setContentsMargins(9, 4, 9, 4)
        self._centrado = centrado
        columna = QWidget()
        columna.setMaximumWidth(self.ANCHO_MAXIMO)
        centrado.addStretch(1)
        centrado.addWidget(columna, 100)
        centrado.addStretch(1)
        lay = _ColumnaSinAltoPorAncho(columna)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self._armar_tablero(lay)
        self._reubicar_filtros()
        self._esqueleto = EsqueletoCarga(columna, self.FORMA_ESQUELETO, QColor(FONDO))
        self._datos_ab_ampliado = []
        self._ampliado = VistaAmpliadaSalidas(self)
        self._ampliado.pedir_flotas.connect(self._ver_contratos_del_mes)

    def _ampliar_altas_bajas(self):
        if not self._datos_ab_ampliado:
            return
        caja = self._cajas['ab']
        self._ampliado.abrir(QRect(caja.mapTo(self, QPoint(0, 0)), caja.size()), self._datos_ab_vistos())

    def _armar_tablero(self, lay):
        lay.addLayout(self._crear_kpis_resumen())
        lay.addWidget(self._crear_franja())
        self._cajas = {'base': self._flexible(self._crear_caja_base()),
                       'compos': self._flexible(self._crear_caja_composicion()),
                       'meta': self._flexible(self._crear_caja_meta_hoy()),
                       'civ': self._flexible(self._crear_caja_meta_civ()),
                       'ab': self._flexible(self._crear_caja_ventas_salidas())}
        self._rejilla = QGridLayout()
        self._rejilla.setContentsMargins(0, 0, 0, 0)
        self._rejilla.setSpacing(10)
        for c in range(12):
            self._rejilla.setColumnStretch(c, 1)
        self._modo_un_mes = None
        self._civ_aparte = None
        self._acomodar_tablero(False)
        lay.addLayout(self._rejilla, 5)

    def _acomodar_tablero(self, un_mes):
        """Con varios meses: base, composición y meta arriba, en tres partes iguales, y el
        gráfico de ventas, salidas y meta abajo, a todo el ancho.
        Con un solo mes: base y gráfico del mes arriba, del mismo ancho, y la composición abajo; el gráfico del mes se
        parte en dos (meta de ventas y meta CIV) salvo que el filtro CIV ya deje la meta de CIV en el primero."""
        civ_aparte = bool(un_mes and not self._meta_es_civ)
        if (un_mes, civ_aparte) == (self._modo_un_mes, self._civ_aparte):
            return
        self._modo_un_mes, self._civ_aparte = un_mes, civ_aparte
        for caja in self._cajas.values():
            self._rejilla.removeWidget(caja)
        if un_mes and civ_aparte:
            posiciones = {'base': (0, 0, 1, 6), 'ab': (0, 6, 1, 3), 'civ': (0, 9, 1, 3), 'compos': (1, 0, 1, 12)}
            filas = (3, 2)
        elif un_mes:
            posiciones = {'base': (0, 0, 1, 6), 'ab': (0, 6, 1, 6), 'compos': (1, 0, 1, 12)}
            filas = (3, 2)
        else:
            posiciones = {'base': (0, 0, 1, 4), 'compos': (0, 4, 1, 4), 'meta': (0, 8, 1, 4), 'ab': (1, 0, 1, 12)}
            filas = (4, 5)
        for clave, visible in (('meta', not un_mes), ('civ', civ_aparte)):
            caja = self._cajas[clave]
            if caja.parentWidget() is not None:   # sin padre (al armar el tablero) mostrarla abriría una ventana suelta
                caja.setVisible(visible)
        for clave, posicion in posiciones.items():
            self._rejilla.addWidget(self._cajas[clave], *posicion)
        self._rejilla.setRowStretch(0, filas[0])
        self._rejilla.setRowStretch(1, filas[1])
        # Una caja que entra al tablero por primera vez queda sobre el esqueleto de carga: se vuelve a subir el esqueleto
        esqueleto = getattr(self, '_esqueleto', None)
        if esqueleto is not None and esqueleto.isVisible():
            esqueleto.raise_()

    # ------------------------------------------------------------------ filtros en caja lateral
    ANCHO_FILTROS = 236
    ANCHO_MINIMO_RESERVA = 1250
    _ALTO_BTN_METAS = 38
    _MARGEN_METAS = 12

    def _crear_metas_en_caja(self, marco):
        """Metas vive al pie de la caja de filtros: el botón es el encabezado y el panel crece hacia arriba."""
        self._seccion_metas = QFrame(marco)
        self._seccion_metas.setObjectName("seccionMetas")
        self.btn_metas = QPushButton(" Metas", self._seccion_metas)
        self.btn_metas.setIcon(qta.icon('fa5s.bullseye', color='white'))
        self.btn_metas.setToolTip("Configurar las metas de unidades vendidas")
        self.btn_metas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_metas.setStyleSheet(_estilo_principal(10, '9px 16px', 12))
        self.btn_metas.clicked.connect(lambda: self._mostrar_panel(not self._panel_abierto))
        self.panel_metas = PanelMetas(self._seccion_metas, incrustado=True)
        self.panel_metas.cambio.connect(self._on_metas_cambiaron)
        self.panel_metas.hide()
        self._anim_panel = QPropertyAnimation(self._seccion_metas, b"geometry", self)
        self._anim_panel.setDuration(220)
        self._anim_panel.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_panel.finished.connect(self._al_terminar_animacion)
        self._seccion_metas.setGeometry(self._geometria_metas(False))

    def _crear_caja_filtros(self):
        caja = admin_estilo.caja_con_encabezado("cajaFiltrosResumen", "Filtros", "Afectan el tablero")
        self._caja_filtros = caja.marco
        caja.marco.setFixedWidth(self.ANCHO_FILTROS)
        crear_sombra_panel(caja.marco)
        # Cabecera blanca de la caja: el título (Dashboard con las pestañas subrayadas, o «Filtros» si el encabezado va aparte)
        caja.marco._encabezado.hide()
        self._banda_dash = QWidget()
        self._banda_dash.setStyleSheet("background: transparent;")
        lay_banda = QVBoxLayout(self._banda_dash)
        lay_banda.setContentsMargins(14, 16, 10, 0)
        lay_banda.setSpacing(8)
        fila_titulo = QHBoxLayout()
        fila_titulo.setSpacing(6)
        self._lbl_titulo_caja = QLabel("Filtros")
        self._lbl_titulo_caja.setStyleSheet(f"color: {MARINO}; font-size: 20px; font-weight: 800; background: transparent; border: none;")
        fila_titulo.addWidget(self._lbl_titulo_caja)
        fila_titulo.addStretch(1)
        self.btn_ocultar_filtros = QPushButton()
        self.btn_ocultar_filtros.setIcon(qta.icon('fa5s.chevron-left', color=MARINO))
        self.btn_ocultar_filtros.setFixedSize(28, 28)
        self.btn_ocultar_filtros.setToolTip("Ocultar los filtros")
        self.btn_ocultar_filtros.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ocultar_filtros.setStyleSheet("QPushButton { background: #F6F8FC; border: 1px solid #E3E8F0; border-radius: 8px; } "
                                               "QPushButton:hover { background: #E8EEF8; border-color: #C9D5EC; }")
        self.btn_ocultar_filtros.clicked.connect(lambda: self._mostrar_filtros(False))
        fila_titulo.addWidget(self.btn_ocultar_filtros)
        lay_banda.addLayout(fila_titulo)
        self._tabs_caja = QFrame()
        self._tabs_caja.setObjectName("tabsCaja")
        self._tabs_caja.setStyleSheet("QFrame#tabsCaja { background: transparent; border: none; border-bottom: 1px solid #E3E8F0; }")
        self._tabs_lay = QHBoxLayout(self._tabs_caja)
        self._tabs_lay.setContentsMargins(0, 0, 0, 0)
        self._tabs_lay.setSpacing(12)
        self._tabs_caja.hide()
        lay_banda.addWidget(self._tabs_caja)
        caja.marco.layout().insertWidget(0, self._banda_dash)
        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(14)
        self.filtros = {}
        nombres = {"EJECUTIVO": "Ejecutivo", "FORMA": "Contrato", "SERVICIO": "Plan", "PERIODO": "Período"}
        for columna, nombre in nombres.items():
            plural = {"EJECUTIVO": "ejecutivos", "FORMA": "contratos", "SERVICIO": "planes"}.get(columna)
            combo = (SelectorPeriodo(nombre) if columna == "PERIODO"
                     else SelectorMultiple(nombre, plural) if plural else ComboTarjeta(nombre))
            if not plural and columna != "PERIODO":
                combo.setStyleSheet(self._ESTILO_COMBO.replace("min-width: 150px;", "min-width: 40px;"))
            combo.setToolTip(f"Filtrar por {nombre.lower()}" + (" de inicio de contrato: año y mes" if columna == "PERIODO" else "")
                             + (". Puedes elegir varios." if plural else ""))
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
            combo.currentIndexChanged.connect(lambda _i, k=columna: self._cambio_filtro(k))
            combo.setStyleSheet(combo.styleSheet().replace("background: white", f"background: {_SUAVE_FILTRO}")
                                .replace("border: 1px solid #D9DEE8", f"border: 1px solid {_SUAVE_FILTRO}"))
            self.filtros[columna] = combo
        self.chk_servicio = {}
        fila_servicio = QHBoxLayout()
        fila_servicio.setSpacing(8)
        for clave in ("CIV", "SZ"):
            marca = QCheckBox(clave)
            marca.setCursor(Qt.CursorShape.PointingHandCursor)
            marca.setStyleSheet(self._estilo_marca_suave())
            marca.setToolTip(f"Solo unidades con {clave}")
            marca.stateChanged.connect(lambda _e, k=clave: self._cambio_filtro(k))
            fila_servicio.addWidget(marca, 1)
            self.chk_servicio[clave.lower()] = marca
        self.chk_pruebas = QCheckBox("Pruebas")
        self.chk_pruebas.setToolTip("Incluir los contratos de prueba (Test y Demo). Por defecto quedan fuera de las cifras.")
        self.chk_pruebas.stateChanged.connect(self._cambio_pruebas)
        self.chk_no_aplica = QCheckBox("No aplica")
        self.chk_no_aplica.setToolTip("Incluir los contratos con activación No aplica, que nunca pasaron por Volvo Connect. "
                                      "Por defecto quedan fuera de las cifras.")
        self.chk_no_aplica.stateChanged.connect(self._cambio_pruebas)
        fila_incluir = QHBoxLayout()
        fila_incluir.setSpacing(8)
        for marca in (self.chk_pruebas, self.chk_no_aplica):
            marca.setCursor(Qt.CursorShape.PointingHandCursor)
            marca.setStyleSheet(self._estilo_marca_suave())
            fila_incluir.addWidget(marca, 1)
        lay.addLayout(self._grupo_filtros("Equipo", self.filtros["EJECUTIVO"], self.filtros["FORMA"]))
        lay.addLayout(self._grupo_filtros("Producto", self.filtros["SERVICIO"], fila_servicio))
        lay.addLayout(self._grupo_filtros("Período", self.filtros["PERIODO"]))
        lay.addLayout(self._grupo_filtros("Incluir", fila_incluir))
        self._aplicados = QWidget()
        self._aplicados.setStyleSheet("background: transparent;")
        self._lay_aplicados = QVBoxLayout(self._aplicados)
        self._lay_aplicados.setContentsMargins(0, 0, 0, 0)
        self._lay_aplicados.setSpacing(5)
        self._aplicados.hide()
        lay.addWidget(self._aplicados)
        lay.addWidget(self._crear_aviso_universo())
        lay.addStretch(1)
        self.btn_quitar = QPushButton("  Quitar filtros")
        self.btn_quitar.setIcon(qta.icon('fa5s.times', color=APAGADO, color_disabled='#B5BFCF'))
        self.btn_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quitar.setToolTip("Quitar todos los filtros")
        self.btn_quitar.setStyleSheet("QPushButton { background: transparent; border: none; color: #5B6980; font-size: 12px; font-weight: 700; "
                                      "padding: 6px; } QPushButton:hover { color: #C2362D; } QPushButton:disabled { color: #B5BFCF; }")
        self.btn_quitar.clicked.connect(self._quitar_filtros)
        lay.addWidget(self.btn_quitar)
        lay.addSpacing(self._ALTO_BTN_METAS)
        caja.cuerpo.addWidget(cuerpo, 1)
        self._crear_metas_en_caja(caja.marco)
        self._anim_filtros = QPropertyAnimation(caja.marco, b"pos", self)
        self._anim_filtros.setDuration(180)
        self._anim_filtros.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_filtros.finished.connect(self._al_terminar_filtros)
        return caja.marco

    @staticmethod
    def _estilo_marca_suave():
        return _estilo_marca().replace("background: white; border: 1px solid #D9DEE8", f"background: {_SUAVE_FILTRO}; border: 1px solid {_SUAVE_FILTRO}").replace("padding: 7px 10px", "padding: 7px 7px")

    @staticmethod
    def _rotulo_grupo(texto):
        etiqueta = QLabel(texto.upper())
        etiqueta.setStyleSheet(f"color: {APAGADO}; font-size: 10.5px; font-weight: 800; letter-spacing: 1px; background: transparent; border: none;")
        return etiqueta

    def _grupo_filtros(self, titulo, *contenido):
        """Un grupo de la caja de filtros: su rótulo en mayúsculas pequeñas y los controles debajo."""
        grupo = QVBoxLayout()
        grupo.setSpacing(7)
        grupo.addWidget(self._rotulo_grupo(titulo))
        for item in contenido:
            grupo.addLayout(item) if isinstance(item, QHBoxLayout) else grupo.addWidget(item)
        return grupo

    def _pintar_aplicados(self):
        """Fichas con los filtros puestos; cada una quita el suyo. Sin filtros el grupo se oculta."""
        if not hasattr(self, '_lay_aplicados'):
            return
        fichas = [(c, self.filtros[c].text()) for c in ("EJECUTIVO", "FORMA", "SERVICIO", "PERIODO") if self._valor_filtro(c)]
        fichas += [(c, c) for c in ("CIV", "SZ") if self._valor_filtro(c)]
        if self._flota:
            fichas.append(("FLOTA", f"Flota {self._flota}"))
        if self.chk_pruebas.isChecked():
            fichas.append(("PRUEBAS", "Pruebas"))
        if self.chk_no_aplica.isChecked():
            fichas.append(("NO_APLICA", "No aplica"))
        if fichas == getattr(self, '_fichas_puestas', None):
            return
        self._fichas_puestas = fichas
        while self._lay_aplicados.count():
            item = self._lay_aplicados.takeAt(0)
            for w in ([item.widget()] if item.widget() else [item.layout().itemAt(i).widget() for i in range(item.layout().count())]):
                if w is not None:
                    w.hide()
                    w.deleteLater()
        self._aplicados.setVisible(bool(fichas))
        if not fichas:
            return
        self._lay_aplicados.addWidget(self._rotulo_grupo("Aplicados"))
        disponible = self.ANCHO_FILTROS - 34
        fila, usado = None, 0
        for clave, texto in fichas:
            ficha = QPushButton(texto)
            ficha.setIcon(qta.icon('fa5s.times', color='#2F5BB0'))
            ficha.setIconSize(QSize(8, 8))
            ficha.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
            ficha.setCursor(Qt.CursorShape.PointingHandCursor)
            ficha.setToolTip("Quitar este filtro")
            ficha.setStyleSheet("QPushButton { background: #E3EAF7; color: #2F5BB0; border: none; border-radius: 12px; padding: 5px 11px; "
                                "font-size: 11.5px; font-weight: 700; } QPushButton:hover { background: #D3DEF2; }")
            ficha.clicked.connect(lambda _c=False, k=clave: self._quitar_ficha(k))
            ancho = ficha.fontMetrics().horizontalAdvance(texto) + 46
            if fila is None or usado + ancho > disponible:
                fila = QHBoxLayout()
                fila.setSpacing(6)
                fila.addStretch(1)
                self._lay_aplicados.addLayout(fila)
                usado = 0
            fila.insertWidget(fila.count() - 1, ficha)
            usado += ancho + 6

    def _quitar_ficha(self, clave):
        if clave == "PRUEBAS":
            self.chk_pruebas.setChecked(False)
        elif clave == "NO_APLICA":
            self.chk_no_aplica.setChecked(False)
        else:
            self._limpiar_filtro(clave)
            self._cambio_filtro(clave)

    def _crear_riel_filtros(self):
        """Barra lateral que reemplaza a la caja de filtros cuando se oculta."""
        self._riel_filtros = _RielNavegacion()
        self._riel_filtros.filtros.connect(lambda: self._mostrar_filtros(True))
        self._riel_filtros.pestana.connect(self._ir_a_pestana)
        self._riel_enlazado = False
        self._riel_filtros.hide()
        return self._riel_filtros

    def _ir_a_pestana(self, indice):
        cab = getattr(self, '_selector_grupo', None)
        if cab is not None:
            cab._barra.setCurrentIndex(indice)
        # Esta pantalla sigue siendo la de su propia pestaña: los botones no se quedan marcados al volver
        propia = getattr(self, '_pestana_propia', None)
        if propia is not None:
            for i, boton in enumerate(getattr(self, '_botones_menu', [])):
                boton.setChecked(i == propia)
            self._riel_filtros.marcar(propia)

    def _enlazar_riel(self, cab):
        """Una vez que existe el encabezado con las pestañas, el riel las copia (nombres y cuál es la de esta pantalla)."""
        if self._riel_enlazado:
            return
        self._riel_enlazado = True
        nombres = [cab._barra.tabText(i) for i in range(cab._barra.count())]
        self._riel_filtros.poner_pestanas(nombres)
        propia = cab._tabs.indexOf(self)
        propia = propia if propia >= 0 else cab._tabs.currentIndex()
        self._riel_filtros.marcar(propia)
        # En la caja de filtros las pestañas van con subrayado bajo el título
        botones = []
        for i, nombre in enumerate(nombres):
            boton = QPushButton(nombre)
            boton.setStyleSheet("QPushButton { background: transparent; border: none; border-bottom: 3px solid transparent; color: #5B6980; "
                                "font-size: 12.5px; font-weight: 600; padding: 8px 0 7px; } QPushButton:hover { color: #1B2B4E; } "
                                "QPushButton:checked { color: #1B2B4E; font-weight: 700; border-bottom: 3px solid #2F5BB0; }")
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setCheckable(True)
            boton.setChecked(i == propia)
            boton.setToolTip(f"Ir a {nombre}")
            boton.clicked.connect(lambda _c, k=i: self._ir_a_pestana(k))
            self._tabs_lay.addWidget(boton)
            botones.append(boton)
        self._tabs_lay.addStretch(1)
        self._botones_menu = botones
        self._pestana_propia = propia
    _MARGEN_FILTROS = 12

    def _origen_filtros(self):
        """(x, y, alto, fusionado) de la caja de filtros. En ventanas anchas sube hasta el borde de arriba y el encabezado
        del Dashboard queda a su derecha, como una sola pieza; en angostas se superpone al contenido, bajo el encabezado."""
        margen = self.layout().contentsMargins()
        fusionado = self._area_filtros.width() >= self.ANCHO_MINIMO_RESERVA and getattr(self, '_hueco_cabecera', None) is not None
        if fusionado:
            return margen.left(), margen.top(), max(120, self.height() - margen.top() - margen.bottom()), True
        y = self._area_filtros.mapTo(self, QPoint(0, 0)).y() + 10
        return margen.left() + self._MARGEN_FILTROS, y, max(120, self._area_filtros.height() - 20), False

    def _actualizar_cabecera(self, fusionado):
        """Con la caja de filtros a la vista el título y las pestañas del Dashboard viven en su parte de arriba y el
        encabezado desaparece (el contenido sube); con la caja oculta vuelven al encabezado, junto al riel."""
        cab = getattr(self, '_selector_grupo', None)
        if cab is None or getattr(cab, '_envoltura', None) is None:
            return
        self._enlazar_riel(cab)
        en_caja = bool(fusionado and self._filtros_visibles)
        if en_caja != getattr(self, '_cab_en_caja', False):
            self._cab_en_caja = en_caja
            self._lbl_titulo_caja.setText("Dashboard" if en_caja else "Filtros")
            self._tabs_caja.setVisible(en_caja)
        # Con el tablero junto al borde de arriba no hay encabezado: ni con la caja a la vista ni con la barra lateral
        cab._envoltura.setVisible(not fusionado)
        self._fila_ext.setContentsMargins(0, 0 if fusionado else 10, 0, 0)

    def _ajustar_hueco_cabecera(self, fusionado):
        """Espacio que deja el encabezado a la izquierda para la caja de filtros (o su riel) cuando van juntos."""
        hueco = getattr(self, '_hueco_cabecera', None)
        if hueco is None:
            return
        ancho = 0
        if hueco.width() != ancho or hueco.minimumWidth() != ancho:
            hueco.setFixedWidth(ancho)

    def _reubicar_filtros(self):
        """Coloca la caja (o el riel) sobre el borde izquierdo, a todo el alto de la zona."""
        if not hasattr(self, '_riel_filtros'):
            return
        # En ventanas anchas el tablero deja libre a la izquierda el espacio de la caja; en angostas, la caja se superpone
        x0, y0, alto, fusionado = self._origen_filtros()
        self._actualizar_cabecera(fusionado)
        # Con la caja junto al encabezado, el contenido empieza justo donde empieza el encabezado (a su derecha)
        if fusionado:
            # El contenido empieza a la derecha de la caja de filtros, esté a la vista o plegada en la barra lateral:
            # así no se corre de lado al mostrar u ocultar los filtros
            reserva = self.ANCHO_FILTROS - 1
        elif self._area_filtros.width() >= self.ANCHO_MINIMO_RESERVA:
            reserva = self._MARGEN_FILTROS + self.ANCHO_FILTROS + 16
        else:
            reserva = 9
        centrado = getattr(self, '_centrado', None)
        if centrado is not None and centrado.contentsMargins().left() != reserva:
            centrado.setContentsMargins(reserva, 4, 9, 4)
        self._ajustar_hueco_cabecera(fusionado)
        self._anim_filtros.stop()
        x = x0 if self._filtros_visibles else -self.ANCHO_FILTROS - 24
        self._caja_filtros.setGeometry(x, y0, self.ANCHO_FILTROS, alto)
        self._acomodar_metas()
        self._riel_filtros.setGeometry(x0, y0, _RielNavegacion.ANCHO, alto)
        self._riel_filtros.setVisible(not self._filtros_visibles)
        self._caja_filtros.setVisible(self._filtros_visibles)
        self._caja_filtros.raise_()
        self._riel_filtros.raise_()

    def _mostrar_filtros(self, mostrar):
        if mostrar == self._filtros_visibles:
            return
        self._filtros_visibles = mostrar
        self._anim_filtros.stop()
        self._sugerencias.hide()
        x0, y0, _alto, fusionado = self._origen_filtros()
        self._ajustar_hueco_cabecera(fusionado)
        self._actualizar_cabecera(fusionado)
        fuera = QPoint(-self.ANCHO_FILTROS - 24, y0)
        dentro = QPoint(x0, y0)
        if mostrar:
            self._riel_filtros.hide()
            self._caja_filtros.move(fuera)
            self._caja_filtros.show()
            self._caja_filtros.raise_()
        self._anim_filtros.setStartValue(self._caja_filtros.pos())
        self._anim_filtros.setEndValue(dentro if mostrar else fuera)
        self._anim_filtros.start()
    def _al_terminar_filtros(self):
        if not self._filtros_visibles:
            self._caja_filtros.hide()
            self._riel_filtros.show()
            self._riel_filtros.raise_()

    def _geometria_metas(self, abierto):
        marco = self._caja_filtros
        ancho = self.ANCHO_FILTROS - 2 * self._MARGEN_METAS
        alto = self._ALTO_BTN_METAS
        if abierto:
            # Solo ocupa el espacio vacío: llega hasta justo debajo de "No aplica"
            tope = self.chk_no_aplica.mapTo(marco, QPoint(0, self.chk_no_aplica.height())).y() + 10
            libre = marco.height() - self._MARGEN_METAS - tope
            alto = min(alto + self.panel_metas.alto_para(ancho), max(alto, libre))
        return QRect(self._MARGEN_METAS, marco.height() - self._MARGEN_METAS - alto, ancho, alto)

    def _acomodar_metas(self):
        self._seccion_metas.setGeometry(self._geometria_metas(self._panel_abierto))
        self._acomodar_metas_hijos()
        self._seccion_metas.raise_()

    def _mostrar_panel(self, mostrar):
        if mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        self._anim_panel.stop()
        self._acomodar_metas_hijos()
        if mostrar:
            self.panel_metas.abrir(self._metas, self._metas_civ)
            self._seccion_metas.setStyleSheet("QFrame#seccionMetas { background: white; border: 1px solid #E3E8F0; border-radius: 12px; }")
            self.panel_metas.show()
            self.btn_metas.setText(" Meta del mes")
            self.btn_metas.setToolTip("Cerrar las metas")
        self._seccion_metas.raise_()
        self._anim_panel.setStartValue(self._seccion_metas.geometry())
        self._anim_panel.setEndValue(self._geometria_metas(mostrar))
        self._anim_panel.start()

    def _acomodar_metas_hijos(self):
        ancho = self.ANCHO_FILTROS - 2 * self._MARGEN_METAS
        self.btn_metas.setGeometry(0, 0, ancho, self._ALTO_BTN_METAS)
        self.panel_metas.setGeometry(0, self._ALTO_BTN_METAS, ancho, self.panel_metas.alto_para(ancho))

    def _al_terminar_animacion(self):
        if not self._panel_abierto:
            self.panel_metas.hide()
            self._seccion_metas.setStyleSheet("")
            self.btn_metas.setText(" Metas")
            self.btn_metas.setToolTip("Configurar las metas de unidades vendidas")

    def resizeEvent(self, event):
        QWidget.resizeEvent(self, event)
        if getattr(self, '_ampliado', None) is not None:
            self._ampliado.reubicar()

    @staticmethod
    def _flexible(caja):
        """Las cajas del tablero se encogen con la ventana en vez de forzar un ancho mínimo."""
        caja.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return caja

    def _crear_franja(self):
        """Tira «Por atender»: los chips de alerta en una fila. Está oculta hasta que se presiona la tarjeta Alertas."""
        marco = QWidget()
        marco.setStyleSheet("background: transparent;")
        grilla = QGridLayout(marco)
        grilla.setContentsMargins(0, 0, 0, 0)
        grilla.setHorizontalSpacing(10)
        grilla.setVerticalSpacing(0)
        for c in range(4):
            grilla.setColumnStretch(c, 1)
            grilla.setColumnMinimumWidth(c, 0)
        self._caja_alertas = grilla
        self._franja_alertas = marco
        marco.hide()
        return marco

    def _crear_franja_estado(self):
        """Estado y cuatro chips, en las mismas cinco columnas de los KPI (la usa Qué mejorar)."""
        marco = QWidget()
        marco.setStyleSheet("background: transparent;")
        grilla = QGridLayout(marco)
        grilla.setContentsMargins(0, 0, 0, 0)
        grilla.setHorizontalSpacing(10)
        grilla.setVerticalSpacing(0)
        for c in range(5):
            grilla.setColumnStretch(c, 1)
            grilla.setColumnMinimumWidth(c, 0)
        bloque = QFrame()
        bloque.setObjectName("estadoResumen")
        bloque.setMinimumHeight(46)
        bloque.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bloque.setStyleSheet("QFrame#estadoResumen { background: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 14px; }")
        lay = QHBoxLayout(bloque)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(10)
        lay.addStretch(1)
        self._icono_estado = QLabel()
        self._icono_estado.setFixedSize(30, 30)
        self._icono_estado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._icono_estado)
        texto = QVBoxLayout()
        texto.setSpacing(0)
        self.lbl_estado = _etiqueta("", f"color: {TINTA}; font-size: 14px; font-weight: 800;")
        self.lbl_estado_detalle = _etiqueta("", f"color: {APAGADO}; font-size: 11px; font-weight: 600;")
        texto.addWidget(self.lbl_estado)
        texto.addWidget(self.lbl_estado_detalle)
        lay.addLayout(texto)
        lay.addStretch(1)
        grilla.addWidget(bloque, 0, 0)
        self._caja_alertas = grilla
        return marco

    def _poner_icono_estado(self, icono, color):
        """Círculo de color con el ícono en blanco, igual que el de los demás chips."""
        self._icono_estado.setStyleSheet(f"background: {color}; border-radius: 15px; border: none;")
        self._icono_estado.setPixmap(qta.icon(icono, color="white").pixmap(14, 14))

    def _alternar_alertas(self):
        """Despliega u oculta la tira «Por atender»: crece o se recoge con un fundido."""
        self._alertas_abiertas = not getattr(self, '_alertas_abiertas', False)
        abrir = self._alertas_abiertas
        self._k_alertas.set_abierta(abrir)
        franja = self._franja_alertas
        if getattr(self, '_anim_alertas', None) is None:
            self._anim_alertas = QPropertyAnimation(franja, b"maximumHeight", self)
            self._anim_alertas.setDuration(260)
            self._anim_alertas.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim_alertas.valueChanged.connect(self._paso_alertas)
            self._anim_alertas.finished.connect(self._fin_alertas)
        anim = self._anim_alertas
        anim.stop()
        franja.layout().activate()
        self._alto_alertas = max(1, franja.layout().sizeHint().height())
        actual = franja.height() if franja.isVisible() else 0
        franja.setGraphicsEffect(QGraphicsOpacityEffect(franja))
        if abrir:
            franja.setMaximumHeight(actual)
            franja.show()
        anim.setStartValue(actual)
        anim.setEndValue(self._alto_alertas if abrir else 0)
        anim.start()

    def _paso_alertas(self, alto):
        efecto = self._franja_alertas.graphicsEffect()
        if efecto is not None:
            efecto.setOpacity(max(0.0, min(1.0, float(alto) / self._alto_alertas)))

    def _fin_alertas(self):
        franja = self._franja_alertas
        franja.setGraphicsEffect(None)
        franja.setMaximumHeight(16777215)
        if not self._alertas_abiertas:
            franja.hide()
    def _crear_aviso_universo(self):
        """Línea que explica de qué camiones hablan las cajas cuando Año o Mes acotan las unidades."""
        self._aviso_universo = QFrame()
        self._aviso_universo.setObjectName("avisoUniverso")
        self._aviso_universo.setStyleSheet("QFrame#avisoUniverso { background: #EEF3FB; border: 1px solid #C5D3EA; border-radius: 10px; }")
        lay = QVBoxLayout(self._aviso_universo)
        lay.setContentsMargins(10, 8, 10, 8)
        self._lbl_aviso_universo = _etiqueta("", f"color: {TINTA}; font-size: 11px; background: transparent; border: none;")
        self._lbl_aviso_universo.setTextFormat(Qt.TextFormat.RichText)
        self._lbl_aviso_universo.setWordWrap(True)
        lay.addWidget(self._lbl_aviso_universo)
        self._aviso_universo.hide()
        return self._aviso_universo

    def _texto_periodo(self, periodos, filtro=None):
        if len(periodos) == 1:
            return self._etiqueta_mes(periodos[0])
        if filtro and filtro.get('anio') and not filtro.get('meses'):
            return str(filtro['anio'])
        if filtro and filtro.get('meses') and not filtro.get('anio'):
            nombres = ", ".join(servicio.MESES[m - 1] for m in sorted(filtro['meses']))
            return f"{nombres} (todos los años)"
        return f"{self._etiqueta_mes(periodos[0])} a {self._etiqueta_mes(periodos[-1])}"

    def _pintar_universo(self, periodos):
        """Con Año o Mes puestos: aviso con el desglose de los camiones filtrados y etiquetas en cada caja que
        dicen si cuentan los camiones filtrados o toda la flota. Sin esos filtros todo se oculta."""
        info = getattr(self, '_info_periodo', None) if periodos else None
        filtrados, flota = (_UNIVERSO_FILTRADOS, _UNIVERSO_FLOTA) if info else (None, None)
        titulo = None
        if info:
            mes_titulo = self._etiqueta_mes(periodos[0]).split()[0].lower()
            # Con el chip de variación al lado, el nombre largo de un mes no cabe en la tarjeta
            titulo = (f"Contratos de {mes_titulo if len(mes_titulo) <= 5 else mes_titulo[:3] + '.'}" if len(periodos) == 1
                      else f"Contratos de {info['texto']}" if len(info['texto']) == 4 else "Contratos del período")
        self._k["universo"].poner_universo(filtrados, titulo)
        self._k["conectadas"].poner_universo(filtrados)
        self._k["penetracion"].poner_universo(filtrados)
        self._k["cobertura"].poner_universo(None)   # el título ya ocupa toda la franja
        self._k["neto"].poner_universo(filtrados)
        _poner_universo(self._cab_base.pastilla, flota)
        _poner_universo(self._cab_composicion.pastilla, filtrados if self._modo_un_mes else None)   # en media caja no cabe junto al título
        # En media caja (meta de ventas y meta CIV lado a lado) la etiqueta no cabe junto al título
        pastilla_ab = None if self._modo_un_mes and self._civ_aparte else (_UNIVERSO_META if self._modo_un_mes else filtrados)
        _poner_universo(self._cab_ab.pastilla, pastilla_ab if info else None)
        if not info:
            self._aviso_universo.hide()
            return
        self._lbl_aviso_universo.setText(
            f"<b>{_num(info['total'])} camiones con contrato de {info['texto'].lower()}</b><br>"
            f"{_num(info['nuevos'])} nuevos + {_num(info['renovados'])} renovados.<br>"
            "<b>Filtrados</b>: estos camiones.<br><b>Toda la flota</b>: los camiones conectados de la flota completa.")
        self._aviso_universo.show()

    def _crear_kpis_resumen(self):
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self._k = {}
        for clave, titulo in (("universo", "Total camiones"), ("conectadas", "VC Conectado"),
                              ("penetracion", "Penetración VC"), ("cobertura", "Cobertura comercial"), ("neto", "Variación del mes")):
            caja = _KpiCaja(titulo)
            caja.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            fila.addWidget(caja, 1)
            self._k[clave] = caja
        self._k["cobertura"].set_clicable("Camiones conectados que ya tienen su facturación registrada. Haz clic para ver en Flotas los que faltan.")
        self._k["cobertura"].clicked.connect(self._abrir_sin_cobertura)
        self._k_alertas = _KpiAlertas()
        self._k_alertas.clicked.connect(self._alternar_alertas)
        fila.addWidget(self._k_alertas)
        return fila

    def _abrir_sin_cobertura(self):
        unidades = self._unidades_actuales
        if unidades is not None:
            self._abrir_en_flotas(servicio.vins_sin_cobertura(unidades), "Conectados sin facturación registrada")

    def _crear_caja_base(self):
        caja = admin_estilo.caja_con_encabezado("cajaBaseResumen", "Camiones activos mes a mes",
                                                "Nuevos menos bajas, acumulado al cierre de cada mes.")
        self._cab_base = caja
        caja.pastilla = _agregar_pastilla_caja(caja)
        self._meses_base = 12
        self.btn_meses_base = QPushButton()
        self.btn_meses_base.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_meses_base.setStyleSheet(PanelMetas._ESTILO_BOTON)
        self.btn_meses_base.clicked.connect(self._alternar_meses_base)
        self.btn_meses_base.hide()
        caja.fila_cab.addWidget(self.btn_meses_base)
        self.grafico_base = GraficoBase()
        self.puente_mes = PuenteMes()
        self.puente_mes.zona_clicada.connect(self._clic_puente_mes)
        self._pila_base = _PilaActual()
        self._pila_base.addWidget(self.grafico_base)
        self._pila_base.addWidget(self.puente_mes)
        caja.cuerpo.addWidget(self._pila_base, 1)
        caja.cuerpo.setContentsMargins(14, 8, 14, 10)
        return caja.marco

    def _crear_caja_composicion(self):
        caja = admin_estilo.caja_con_encabezado("cajaComposicionResumen", "Estado de los camiones hoy", "Todos los camiones de los filtros, hoy.")
        _ayuda_encabezado(caja, "Todos los camiones que muestran los filtros, clasificados por su estado de hoy. "
                                "No depende del mes en que se vendieron.")
        caja.pastilla = _agregar_pastilla_caja(caja)
        self._cab_composicion = caja
        self._wid_composicion = QWidget()
        cuerpo = QBoxLayout(QBoxLayout.Direction.LeftToRight, self._wid_composicion)
        self._cuerpo_composicion = cuerpo
        cuerpo.setContentsMargins(18, 10, 18, 10)
        cuerpo.setSpacing(22)
        self.anillo_composicion = AnilloComposicion()
        self.anillo_composicion.zona_clicada.connect(self._clic_anillo)
        cuerpo.addWidget(self.anillo_composicion, 0, Qt.AlignmentFlag.AlignCenter)
        columna = QVBoxLayout()
        columna.addStretch(1)
        self.barra_composicion = BarraComposicion()
        self.barra_composicion.hide()
        columna.addWidget(self.barra_composicion)
        columna.addSpacing(8)
        self._filas_composicion = QVBoxLayout()
        self._filas_composicion.setSpacing(10)
        columna.addLayout(self._filas_composicion)
        columna.addStretch(1)
        cuerpo.addLayout(columna, 1)
        self._wid_composicion.hide()   # lo reemplaza el anillo con tarjetas (se conserva el armado de sus filas)
        self.estado_camiones = AnilloEstado()
        self.estado_camiones.zona_clicada.connect(self._clic_estado)
        caja.cuerpo.addWidget(self.estado_camiones, 1)
        caja.cuerpo.addWidget(self._wid_composicion)
        self.planes_mes = PlanesMes()
        self.planes_mes.zona_clicada.connect(self._clic_planes_mes)
        self.planes_mes.hide()
        caja.cuerpo.addWidget(self.planes_mes)
        self._mix_planes_mes = None
        return caja.marco

    _ESTILO_SELECTOR = ("QPushButton { background: transparent; color: #C9D3E8; border: 1px solid rgba(255,255,255,0.35); "
                        "border-radius: 11px; padding: 2px 11px; font-size: 11.5px; font-weight: 700; } "
                        "QPushButton:hover { background: rgba(255,255,255,0.12); } "
                        "QPushButton:checked { background: white; color: #1B2B4E; border-color: white; }")

    def _crear_caja_meta_hoy(self):
        """Avance de la meta del equipo en el mes en curso o en el año, a elección."""
        caja = admin_estilo.caja_con_encabezado("cajaMetaResumen", "Meta del mes", "")
        _ayuda_encabezado(caja, "Ventas frente a la meta del equipo, en el mes en curso o en el año. "
                                "Las metas solo valen sin filtros (Año y Mes no las cambian).")
        self._cab_meta = caja
        self._meta_vista = 'mes'
        grupo = QButtonGroup(caja.marco)
        self._btns_meta = {}
        for clave, texto in (('mes', "Mes"), ('anio', "Año")):
            boton = QPushButton(texto)
            boton.setCheckable(True)
            boton.setChecked(clave == self._meta_vista)
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(self._ESTILO_SELECTOR)
            boton.setFixedHeight(24)
            boton.clicked.connect(lambda _=False, c=clave: self._elegir_vista_meta(c))
            grupo.addButton(boton)
            caja.fila_cab.addWidget(boton, 0, Qt.AlignmentFlag.AlignTop)
            self._btns_meta[clave] = boton
        self.medidor_meta_hoy = MedidorMeta()
        self.medidor_meta_hoy.setMinimumHeight(200)
        self.medidor_meta_hoy._anim_datos.setDuration(700)
        self.medidor_meta_hoy.zona_clicada.connect(self._clic_meta_hoy)
        caja.cuerpo.addWidget(self.medidor_meta_hoy, 1)
        caja.cuerpo.setContentsMargins(10, 6, 10, 8)
        self._datos_meta_hoy = None
        return caja.marco

    def _crear_caja_meta_civ(self):
        """Avance de la meta de unidades con CIV del mes, junto al de la meta de ventas (tablero de un solo mes)."""
        caja = admin_estilo.caja_con_encabezado("cajaMetaCivResumen", "Meta CIV", "")
        _ayuda_encabezado(caja, "Unidades con CIV vendidas en el mes frente a la meta de CIV del equipo. "
                                "La meta no cambia con los filtros de Año y Mes.")
        self._cab_civ = caja
        self.medidor_meta_civ = MedidorMeta()
        self.medidor_meta_civ.setMinimumHeight(200)
        self.medidor_meta_civ.zona_clicada.connect(self._clic_meta_civ)
        caja.cuerpo.addWidget(self.medidor_meta_civ, 1)
        caja.cuerpo.setContentsMargins(10, 6, 10, 8)
        self._sub_meta_civ = None
        self._mes_meta_civ = None
        return caja.marco

    def _pintar_meta_civ(self, mensual, filtrando, mes, unidad="del mes"):
        """Ventas con CIV del período y su meta, con los mismos filtros del tablero (la meta solo vale sin otros filtros)."""
        activos = getattr(self, '_activos_vista', None)
        if self._meta_es_civ or activos is None or self._panorama is None:
            return
        periodos = [x['periodo'] for x in mensual]
        filtro_civ = {"plan": "", "sz": False, **(activos.get("SERVICIO") or {}), "civ": True}
        sub = servicio.filtrar_panorama(self._panorama, **{**activos, "SERVICIO": filtro_civ})
        ventas = sum(x['vendidas'] for x in servicio.calcular_mensual(sub, periodos=periodos))
        meta = self._meta_de_vista(mensual, filtrando, self._metas_civ)
        self._sub_meta_civ, self._mes_meta_civ = sub, (periodos, mes)
        self._cab_civ.lbl_titulo.setText(f"Meta CIV de {mes}")
        if meta:
            texto = f"{_num(ventas)} ventas con CIV de {_num(meta)}"
        else:
            texto = f"{_num(ventas)} con CIV · " + ("meta solo sin otros filtros" if filtrando else "sin meta definida")
        self._cab_civ.lbl_subtitulo.setText(texto)
        dia = self._dia_meta_cumplida(periodos[0], meta, sub) if len(periodos) == 1 else None
        self.medidor_meta_civ.set_datos([{'ventas': ventas, 'meta': meta, 'mes': mes, 'civ': True, 'unidad': unidad,
                                          'sin_meta': "Sin meta CIV para este período", 'dia': dia}])

    def _clic_meta_civ(self, _clave):
        if self._sub_meta_civ is None:
            return
        periodos, mes = self._mes_meta_civ
        altas = self._sub_meta_civ['altas']
        vins = sorted(set(altas.loc[altas['FECHA'].dt.to_period('M').isin(periodos), 'VIN']))
        self._abrir_en_flotas(vins, f"Vendidos con CIV en {mes}")

    def _elegir_vista_meta(self, clave):
        if clave == self._meta_vista:
            return
        datos = getattr(self, '_datos_meta_hoy', None)
        previa = datos[self._meta_vista]['meta'] if datos else None
        self._meta_vista = clave
        self._pintar_meta_hoy(animado=True, meta_previa=previa)

    def _calcular_meta_hoy(self, datos, sin_meta):
        """Ventas y meta del último mes a la vista y de su año, con los datos del gráfico de ventas."""
        if not datos:
            self._datos_meta_hoy = None
            return
        ref = datos[-1]['periodo']
        hoy = date.today()
        mes = self._etiqueta_mes(ref).split()[0].lower() + ("" if ref.year == hoy.year else f" {ref.year}")
        meta_mes = None if sin_meta else self._metas_vigentes().get((ref.year, ref.month))
        ventas_anio = sum(d['altas'] for d in datos if d['periodo'].year == ref.year)
        meta_anio = None if sin_meta else (sum(self._metas_vigentes().get((ref.year, n), 0) for n in range(1, 13)) or None)
        civ = self._meta_es_civ
        sufijo = " CIV" if civ else ""
        self._datos_meta_hoy = {
            'mes': {'ventas': datos[-1]['altas'], 'meta': meta_mes, 'mes': mes, 'unidad': "del mes", 'periodo': ref, 'civ': civ,
                    'dia': self._dia_meta_cumplida(ref, meta_mes), 'sin_meta': "Sin meta para este mes",
                    'titulo': f"Meta{sufijo} de {mes}"},
            'anio': {'ventas': ventas_anio, 'meta': meta_anio, 'mes': str(ref.year), 'unidad': "del año", 'periodo': ref, 'civ': civ,
                     'dia': None, 'sin_meta': "Sin meta para este año", 'titulo': f"Meta{sufijo} {ref.year}"}}
        self._sin_meta_hoy = bool(sin_meta)

    def _pintar_meta_hoy(self, animado=False, meta_previa=None):
        """Con `animado` (al cambiar entre Mes y Año) el medidor se llena desde cero hasta el avance nuevo y las
        cifras cuentan desde las anteriores."""
        datos = getattr(self, '_datos_meta_hoy', None)
        if not datos:
            self.medidor_meta_hoy.set_datos([])
            self._cab_meta.lbl_subtitulo.setText("")
            return
        d = datos[self._meta_vista]
        self._cab_meta.lbl_titulo.setText(d['titulo'])
        if d['meta']:
            sub = f"{_num(d['ventas'])} ventas{' con CIV' if d.get('civ') else ''} de {_num(d['meta'])}"
        else:
            sub = "Meta: solo sin filtros" if getattr(self, '_sin_meta_hoy', False) else f"{_num(d['ventas'])} ventas · sin meta definida"
        self._cab_meta.lbl_subtitulo.setText(sub)
        if animado and d['meta']:
            self.medidor_meta_hoy.set_datos([{**d, 'ventas': 0, 'meta': meta_previa or d['meta']}])
        self.medidor_meta_hoy.set_datos([d], animado)

    def _clic_meta_hoy(self, _clave):
        """Clic en el medidor: abre en General las flotas vendidas en el mes (o en el año) a la vista."""
        datos = getattr(self, '_datos_meta_hoy', None)
        sub = getattr(self, '_panorama_movimiento', None)
        if not datos or sub is None:
            return
        d = datos[self._meta_vista]
        altas = sub['altas']
        periodo = d['periodo']
        if self._meta_vista == 'mes':
            vins = servicio.vins_vendidos_mes(sub, periodo)
        else:
            vins = sorted(set(altas.loc[altas['FECHA'].dt.year == periodo.year, 'VIN']))
        self._abrir_en_flotas(vins, f"Vendidos en {d['mes']}")

    def _clic_estado(self, clave):
        """Clic en el anillo o en una tarjeta del estado de los camiones: abre en General sus flotas."""
        if clave == "total":
            unidades = self._unidades_actuales
            if unidades is not None:
                self._abrir_en_flotas(sorted(set(unidades['VIN'])), "Todos los camiones de los filtros")
            return
        filas = getattr(self, '_filas_composicion_datos', [])
        indice = int(clave.split(":")[1]) if clave.startswith("fila:") else -1
        if indice == 2:
            self._abrir_composicion(None, "Otros estados")
        elif 0 <= indice < len(filas):
            nombre, _n, _color, _detalle, estados = filas[indice]
            self._abrir_composicion(estados, nombre)

    def _clic_anillo(self, indice):
        filas = getattr(self, '_filas_composicion_datos', [])
        if 0 <= indice < len(filas):
            nombre, _n, _color, _detalle, estados = filas[indice]
            self._abrir_composicion(estados, nombre)

    def _crear_caja_ventas_salidas(self):
        caja = admin_estilo.caja_con_encabezado("cajaVentasSalidasResumen", "Ventas, Bajas y Metas",
                                                "Lo vendido cada mes frente a las bajas del mismo mes y a la meta del equipo.")
        self._cab_ab = caja
        caja.pastilla = _agregar_pastilla_caja(caja)
        _ayuda_encabezado(caja, "Arriba, las unidades vendidas de cada mes y su meta (línea punteada). Abajo, las bajas del mismo mes: "
                                "las bajas (dadas y solicitadas cuentan por igual) y las que no tienen fecha de baja. El punto es la variación del mes.")
        self.lbl_meta_nota = _etiqueta("", "color: #B8C2D6; font-size: 11px; font-weight: 600;")
        caja.fila_cab.addWidget(self.lbl_meta_nota)
        self._ver_mas = False
        self.btn_meses_metas = QPushButton()
        self.btn_meses_metas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_meses_metas.setStyleSheet(PanelMetas._ESTILO_BOTON)
        self.btn_meses_metas.clicked.connect(self._alternar_meses_metas)
        caja.fila_cab.addWidget(self.btn_meses_metas)
        self.btn_ampliar_ab = QPushButton(" Expandir")
        self.btn_ampliar_ab.setIcon(qta.icon('fa5s.expand-alt', color='#1B2B4E'))
        self.btn_ampliar_ab.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ampliar_ab.setStyleSheet(PanelMetas._ESTILO_BOTON)
        self.btn_ampliar_ab.setToolTip("Ver el gráfico grande, con la tabla de los meses")
        self.btn_ampliar_ab.clicked.connect(self._ampliar_altas_bajas)
        caja.fila_cab.addWidget(self.btn_ampliar_ab)
        normal = QWidget()
        cuerpo = QVBoxLayout(normal)
        cuerpo.setContentsMargins(14, 8, 14, 10)
        cuerpo.setSpacing(6)
        cuerpo.addWidget(leyenda_salidas())
        self.grafico_ventas_salidas = GraficoSalidas()
        self.grafico_ventas_salidas.setMinimumHeight(210)
        self.grafico_ventas_salidas.mes_foco.connect(self._foco_ventas_salidas)
        self.grafico_ventas_salidas.mes_salio.connect(self._resumen_ventas_salidas)
        self.grafico_ventas_salidas.mes_clicado.connect(self._clic_ventas_salidas)
        cuerpo.addWidget(self.grafico_ventas_salidas, 1)
        self.detalle_ventas_salidas = QLabel()
        self.detalle_ventas_salidas.setTextFormat(Qt.TextFormat.RichText)
        self.detalle_ventas_salidas.setFixedHeight(36)
        self.detalle_ventas_salidas.setStyleSheet(f"background: #F6F8FC; border: 1px solid {LINEA}; border-radius: 12px; "
                                                  f"padding: 2px 14px; color: {TINTA}; font-size: 12px;")
        cuerpo.addWidget(self.detalle_ventas_salidas)
        self.medidor_meta = MedidorMeta()
        self.medidor_meta.zona_clicada.connect(self._clic_un_mes)
        self._pila_ab = _PilaActual()
        self._pila_ab.addWidget(normal)
        self._pila_ab.addWidget(self.medidor_meta)
        caja.cuerpo.addWidget(self._pila_ab, 1)
        return caja.marco

    # ------------------------------------------------------------------ gráfico de ventas, salidas y meta
    def _foco_ventas_salidas(self, indice):
        datos = self._datos_ab_ampliado
        if 0 <= indice < len(datos):
            self.detalle_ventas_salidas.setText(texto_detalle(datos[indice], True))

    def _resumen_ventas_salidas(self):
        """Sin mes bajo el mouse, la línea de detalle muestra cómo va el año en curso."""
        self.grafico_ventas_salidas.set_foco(None)
        self.detalle_ventas_salidas.setText(texto_resumen_anio(self._datos_ab_ampliado, True))

    def _clic_ventas_salidas(self, indice, tipo):
        """Clic en la mitad de arriba (ventas) o de abajo (bajas) de un mes: abre en General las flotas de esas unidades."""
        datos = self._datos_ab_ampliado
        periodos = getattr(self, '_periodos_grafico', [])
        sub = getattr(self, '_panorama_movimiento', None)
        if not 0 <= indice < len(datos) or sub is None or datos[indice]['periodo'] not in periodos:
            return
        periodo = datos[indice]['periodo']
        if tipo == 'bajas':
            self._ver_contratos_del_mes(periodos.index(periodo), 'bajas')
        else:
            mes = self._etiqueta_mes(periodo).lower()
            self._abrir_en_flotas(servicio.vins_vendidos_mes(sub, periodo), f"Vendidos en {mes}")

    def _meses_base_ab(self):
        """Meses que se ven de entrada: el año en curso completo (de enero hasta hoy)."""
        return min(date.today().month, len(self._datos_ab_ampliado))

    def _cantidad_ab(self):
        datos = self._datos_ab_ampliado
        if getattr(self, '_ab_por_periodo', False):
            return len(datos)
        return min(self._meses_base_ab() + (6 if self._ver_mas else 0), len(datos))

    def _datos_ab_vistos(self):
        return self._datos_ab_ampliado[len(self._datos_ab_ampliado) - self._cantidad_ab():]

    def _alternar_meses_metas(self):
        self._ver_mas = not self._ver_mas
        self._mostrar_ventas_salidas(animado=True)

    def _pintar_metas(self, mensual, filtrando, por_periodo=False, filtrando_meta=None):
        """Mete las metas de cada mes en los datos del gráfico (con un filtro que recorta las ventas del equipo no hay meta;
        Año y Mes no lo hacen) y lo dibuja con los meses a la vista."""
        sin_meta = filtrando if filtrando_meta is None else filtrando_meta
        for d in self._datos_ab_ampliado:
            d['meta'] = None if sin_meta else self._metas_vigentes().get((d['periodo'].year, d['periodo'].month))
        self._ab_por_periodo = por_periodo
        self._calcular_meta_hoy(self._datos_ab_ampliado, sin_meta)
        self._pintar_meta_hoy()
        self._mostrar_ventas_salidas()
        if sin_meta:
            self.lbl_meta_nota.setText("Meta: solo sin filtros")
        elif not any(d['meta'] for d in self._datos_ab_ampliado):
            self.lbl_meta_nota.setText("Aún no hay metas definidas")
        else:
            self.lbl_meta_nota.setText("Metas CIV del equipo" if self._meta_es_civ else "Metas del equipo")

    def _mostrar_ventas_salidas(self, animado=False):
        datos = self._datos_ab_ampliado
        if self.grafico_ventas_salidas._destino is not datos:
            self.grafico_ventas_salidas.set_datos(datos, self._animar_graficos)
        self.grafico_ventas_salidas.set_visibles(self._cantidad_ab(), animado)
        if datos:
            if self.grafico_ventas_salidas._hover is not None and self.grafico_ventas_salidas._hover < len(datos):
                self._foco_ventas_salidas(self.grafico_ventas_salidas._hover)
            else:
                self._resumen_ventas_salidas()
        else:
            self.detalle_ventas_salidas.setText("")
        por_periodo = getattr(self, '_ab_por_periodo', False)
        self.btn_meses_metas.setVisible(not por_periodo and len(datos) > self._meses_base_ab())
        self.btn_meses_metas.setText("Ver menos" if self._ver_mas else "Ver 6 meses más")
        if self._ampliado.abierta:
            self._ampliado.set_datos(self._datos_ab_vistos())
    # ------------------------------------------------------------------ pintado
    def _repintar(self, *_):
        activos = self._filtros_activos()
        filtrando = any(v for k, v in activos.items() if k not in ("SIN_PRUEBAS", "SIN_NO_APLICA"))
        self.btn_quitar.setEnabled(filtrando)
        self._pintar_aplicados()
        if self._panorama is None:
            for caja in self._k.values():
                caja.poner("—")
            self._vaciar_chips()
            self._k_alertas.poner(0)
            self._vaciar(self._filas_composicion)
            for g in (self.grafico_base, self.grafico_ventas_salidas):
                g.set_datos([])
            self._datos_ab_ampliado = []
            self.anillo_composicion.set_datos([], "", "")
            self.estado_camiones.set_datos([])
            self._filas_composicion_datos = []
            self._unidades_actuales = None
            return
        self._activos_vista = activos
        sub = servicio.filtrar_panorama(self._panorama, **activos)
        self._panorama_vista = sub
        unidades = sub['unidades']
        self._unidades_actuales = unidades
        k = servicio.calcular_kpis(unidades)
        anios = servicio.anios_inicio(self._panorama)
        periodos = servicio.periodos_del_filtro(activos.get("PERIODO"), anio_min=anios[-1] if anios else None)
        self._info_periodo = None
        self._vins_nuevos_periodo = None
        if periodos is not None and len(periodos):
            altas = sub['altas']
            vins_nuevos = set(altas.loc[altas['FECHA'].dt.to_period('M').isin(list(periodos)), 'VIN'])
            self._vins_nuevos_periodo = vins_nuevos
            nuevos = int(unidades['VIN'].isin(vins_nuevos).sum())
            self._info_periodo = {'total': len(unidades), 'nuevos': nuevos, 'renovados': len(unidades) - nuevos,
                                  'texto': self._texto_periodo(list(periodos), activos.get("PERIODO"))}
        # Con Año o Mes todo el tablero cuenta los mismos camiones, los filtrados: no se mezclan universos
        sub_mov = sub
        self._panorama_movimiento = sub_mov
        mensual = servicio.calcular_mensual(sub_mov, periodos=periodos)
        # El puente de camiones activos cuenta toda la flota conectada: Año y Mes no recortan su inicio, sus nuevos ni sus bajas
        if periodos is None:
            sub_flota, mensual_flota, conectadas_flota = sub, mensual, k['con_producto']
        else:
            sub_flota = servicio.filtrar_panorama(self._panorama, **{c: v for c, v in activos.items() if c != "PERIODO"})
            mensual_flota = servicio.calcular_mensual(sub_flota, periodos=periodos)
            conectadas_flota = servicio.calcular_kpis(sub_flota['unidades'])['con_producto']
        self._panorama_flota = sub_flota
        self._periodos_grafico = [m['periodo'] for m in mensual]        # Año y Mes no recortan las ventas del equipo: con ellos la meta sigue valiendo
        filtrando_meta, self._meta_es_civ = self._modo_meta(activos)
        # La base y el KPI Conectados cuentan las unidades que muestran los filtros, igual que Total camiones
        mensual_base = self._anclar_base(mensual if sub is sub_mov else servicio.calcular_mensual(sub, periodos=periodos), k['con_producto'])
        self._meta_periodo = self._meta_del_periodo(activos.get("PERIODO"), mensual, filtrando_meta)
        self._previo_periodo = self._kpis_periodo_anterior(activos, periodos) if self._info_periodo else None
        self._cobertura_previa = self._cobertura_sin_nuevos(sub, mensual[-1]['periodo']) if periodos is None and mensual else None
        self._pintar_kpis_resumen(k, mensual, filtrando_meta, mensual_base)
        self._pintar_estado(k, mensual, sub, filtrando_meta)
        # Con Año o Mes las unidades ya están acotadas por inicio de contrato: no se compara con «este mes»
        self._composicion_mes = mensual[-1] if periodos is None and mensual else None
        self._filtro_periodo = activos.get("PERIODO") or {}
        # Un solo mes, o el Año elegido (con o sin meses): el tablero cuenta el período completo
        self._vista_periodo = bool(mensual) and periodos is not None and (len(periodos) == 1 or bool(self._filtro_periodo.get("anio")))
        self._acomodar_tablero(self._vista_periodo)
        self._pintar_composicion(k)
        # Sin Año ni Mes, la base se calcula para 24 meses y «Ver 12 meses más» deja ver el año anterior
        base_grafico = mensual_base if periodos is not None else self._anclar_base(
            servicio.calcular_mensual(sub, n_meses=self.MESES_BASE_MAX), k['con_producto'])
        largo = len(base_grafico) > 12
        self.grafico_base.set_datos([
            {'etiqueta': self._etiqueta_mes(m['periodo'], corta=True).lower() + (f" {str(m['periodo'].year)[2:]}" if largo and m['periodo'].month == 1 else ""),
             'mes': self._etiqueta_mes(m['periodo']), 'valor': m['base'], 'neto': m['neto']} for m in base_grafico], self._animar_graficos)
        self.grafico_base.set_visibles(self._meses_base if largo else len(base_grafico))
        self.btn_meses_base.setVisible(largo)
        self.btn_meses_base.setText("Ver menos" if self._meses_base > 12 else "Ver 12 meses más")
        # Sin Año ni Mes el gráfico trae 24 meses: se ve el año en curso y «Ver 6 meses más» suma meses del anterior
        mensual_grafico = mensual if periodos is not None else servicio.calcular_mensual(sub_mov, n_meses=self.MESES_BASE_MAX)
        self._periodos_grafico = [m['periodo'] for m in mensual_grafico]
        self._datos_ab_ampliado = [
            {'etiqueta': self._etiqueta_mes(m['periodo'], corta=True).lower() + (f" {str(m['periodo'].year)[2:]}" if m['periodo'].month in (1, 12) else ""),
             'mes': self._etiqueta_mes(m['periodo']), 'periodo': m['periodo'], 'altas': m['vendidas'], 'dadas': m['bajas_dadas'] + m['bajas_solicitadas'],
             'solicitadas': 0, 'sin_fecha': m['bajas_sin_fecha'], 'meta': None} for m in mensual_grafico]
        self._pintar_un_mes(mensual, filtrando_meta, mensual_base, (mensual_flota, conectadas_flota))
        self._pintar_universo(periodos)
        self._pintar_metas(mensual, filtrando, periodos is not None, filtrando_meta)

    @staticmethod
    def _modo_meta(activos):
        """(sin meta, con metas CIV): las metas del equipo valen sin más filtros que Año, Mes, Pruebas y No aplica; con el
        filtro CIV solo (sin plan ni Safety Zone) se usan las metas de CIV."""
        servicio_f = activos.get("SERVICIO")
        solo_civ = bool(isinstance(servicio_f, dict) and servicio_f.get("civ") and not servicio_f.get("sz") and not servicio_f.get("plan"))
        otros = any(v for c, v in activos.items() if c not in ("SIN_PRUEBAS", "SIN_NO_APLICA", "PERIODO", "SERVICIO"))
        if otros or (activos.get("SERVICIO") and not solo_civ):
            return True, False
        return False, solo_civ

    _meta_es_civ = False
    _vista_periodo = False
    _filtro_periodo = {}
    _etq_periodo = ""

    def _metas_vigentes(self):
        return self._metas_civ if self._meta_es_civ else self._metas

    def _kpis_periodo_anterior(self, activos, periodos):
        """KPI del período anterior para los chips de variación con Año o Mes: el mes anterior si hay un solo mes, o
        los mismos meses del año pasado si el filtro es un año. None si no hay con qué comparar."""
        filtro = activos.get("PERIODO") or {}
        if len(periodos) == 1:
            anterior = periodos[0] - 1
            previo, meses = {'anio': anterior.year, 'meses': [anterior.month]}, [anterior]
            nombre = self._etiqueta_mes(anterior).split()[0].lower()
        elif filtro.get('anio') and not filtro.get('meses'):
            nombre = str(filtro['anio'] - 1)
            previo = {'anio': filtro['anio'] - 1, 'meses': sorted({p.month for p in periodos})}
            meses = [p - 12 for p in periodos]
        else:
            return None
        sub = servicio.filtrar_panorama(self._panorama, **{**activos, "PERIODO": previo})
        if sub is None or sub['unidades'].empty:
            return None
        mensual = servicio.calcular_mensual(sub, periodos=meses)
        return {'k': servicio.calcular_kpis(sub['unidades']), 'nombre': nombre,
                'neto': mensual[-1]['neto'] if len(mensual) == 1 else None}

    @staticmethod
    def _cobertura_sin_nuevos(sub, mes):
        """Cobertura comercial de los camiones que ya estaban antes de las ventas de `mes`: sirve de comparación."""
        altas = sub['altas']
        nuevos = set(altas.loc[altas['FECHA'].dt.to_period('M') == mes, 'VIN'])
        resto = sub['unidades'][~sub['unidades']['VIN'].isin(nuevos)]
        return servicio.calcular_kpis(resto)['cobertura_pct'] if len(resto) and resto['ACTIVACION'].isin(servicio.ESTADOS_TARJETA_CONECTADOS).any() else None

    @staticmethod
    def _anclar_base(serie, conectadas):
        """La base del mes en curso es la flota conectada de hoy (la del KPI VC Conectado) y los meses anteriores se
        corren lo mismo, así cada variación mensual se mantiene."""
        hoy = date.today()
        if not serie or (serie[-1]['periodo'].year, serie[-1]['periodo'].month) != (hoy.year, hoy.month):
            return serie
        desfase = conectadas - serie[-1]['base']
        return [{**m, 'base': m['base'] + desfase} for m in serie]

    MESES_BASE_MAX = 24
    _animar_graficos = False   # solo mientras se repinta por un cambio de filtros: los gráficos pasan de los datos anteriores a los nuevos

    def _filtrar_animado(self, *_):
        """Al aplicar o sacar un filtro los gráficos se ajustan con una animación. Si cambia el Año o el Mes (el tablero
        puede pasar de varios meses a uno solo y viceversa) se muestra el esqueleto de carga mientras se rearma."""
        self._pintar_aplicados()
        activos = self._filtros_activos()
        periodo = activos.get("PERIODO")
        cambia_periodo = self._panorama is not None and periodo != getattr(self, "_periodo_visto", None)
        self._periodo_visto = periodo
        if cambia_periodo:
            self._esqueleto.iniciar_ya(rapido=True)
            QTimer.singleShot(40, self._repintar_con_esqueleto)
            return
        self._esqueleto.iniciar(rapido=True)
        QTimer.singleShot(0, self._repintar_y_terminar)

    def _repintar_con_esqueleto(self):
        self._repintar()
        self._fin_carga.start(380)

    def _repintar_y_terminar(self):
        self._animar_graficos = True
        try:
            self._repintar()
        finally:
            self._animar_graficos = False
        self._esqueleto.terminar()

    def _alternar_meses_base(self):
        self._meses_base = self.MESES_BASE_MAX if self._meses_base == 12 else 12
        self.btn_meses_base.setText("Ver menos" if self._meses_base > 12 else "Ver 12 meses más")
        self.grafico_base.set_visibles(self._meses_base, animado=True)

    _TITULOS_VARIOS = {'base': ("Camiones activos mes a mes", "Nuevos menos bajas, acumulado al cierre de cada mes."),
                       'ab': ("Ventas, Bajas y Metas", "Lo vendido cada mes frente a las bajas del mismo mes y a la meta del equipo.")}

    @staticmethod
    def _agregar_mensual(mensual):
        """Cifras del período completo: las del mes si es uno solo, o la suma de todos los meses a la vista."""
        if len(mensual) == 1:
            return mensual[0]
        suma = lambda c: sum(m.get(c, 0) for m in mensual)
        return {**mensual[-1], **{c: suma(c) for c in ('vendidas', 'bajas', 'neto', 'bajas_dadas', 'bajas_solicitadas', 'bajas_sin_fecha')}}

    def _etiqueta_vista(self, mensual):
        """Cómo se nombra el período a la vista: «noviembre», «2026» (año completo) o «oct–nov 2026»; y su unidad de meta."""
        filtro = self._filtro_periodo
        if len(mensual) == 1:
            return self._etiqueta_mes(mensual[0]['periodo']).split()[0].lower(), "del mes"
        if filtro.get('anio') and not filtro.get('meses'):
            return str(filtro['anio']), "del año"
        primero, ultimo = mensual[0]['periodo'], mensual[-1]['periodo']
        nombre = lambda p: servicio.MESES[p.month - 1][:3].lower()
        return f"{nombre(primero)}–{nombre(ultimo)} {ultimo.year}", "del período"

    def _meta_de_vista(self, mensual, filtrando, metas):
        """Meta de los meses a la vista: la del mes, o la suma (un año entero cuenta la de sus 12 meses)."""
        if filtrando:
            return None
        if len(mensual) == 1:
            p = mensual[0]['periodo']
            return metas.get((p.year, p.month))
        filtro = self._filtro_periodo
        if filtro.get('anio') and not filtro.get('meses'):
            total = sum(metas.get((filtro['anio'], n), 0) for n in range(1, 13))
        else:
            total = sum(metas.get((m['periodo'].year, m['periodo'].month), 0) for m in mensual)
        return total or None

    def _pintar_un_mes(self, mensual, filtrando, mensual_base=None, flota=None):
        """Con un solo mes o con el Año elegido a la vista, los gráficos de meses se cambian por sus versiones del período."""
        un_mes = bool(mensual) and self._vista_periodo
        self.btn_ampliar_ab.setVisible(not un_mes)
        self.lbl_meta_nota.setVisible(not un_mes)
        self.btn_meses_metas.setVisible(not un_mes and self.btn_meses_metas.isVisibleTo(self))
        if un_mes:
            self._ampliado.cerrar(rapido=True)
        self._acomodar_tablero(un_mes)
        self.estado_camiones.setVisible(not un_mes)
        self.planes_mes.setVisible(un_mes)
        cajas = {'base': (self._cab_base, self._pila_base), 'ab': (self._cab_ab, self._pila_ab)}
        mes, unidad = self._etiqueta_vista(mensual) if un_mes else ("", "del mes")
        self._etq_periodo = mes
        titulos = {'base': (f"Camiones activos en {mes}", "Al inicio + nuevos − bajas = al cierre, con los camiones conectados. Presiona una barra."),
                   'ab': (f"Meta{' CIV' if self._meta_es_civ else ''} de {mes}", "")} if un_mes else self._TITULOS_VARIOS
        for clave, (cab, pila) in cajas.items():
            pila.setCurrentIndex(1 if un_mes else 0)
            cab.lbl_titulo.setText(titulos[clave][0])
            cab.lbl_subtitulo.setText(titulos[clave][1])
        self._cab_composicion.lbl_titulo.setText("Planes y complementos" if un_mes else "Estado de los camiones hoy")
        _ayuda_encabezado(self._cab_composicion, (
            "Plan y complementos de los camiones conectados (conectado, activando, sin flota y no entregado) de los filtros. "
            "Cada camión cuenta en un solo grupo." if un_mes else
            "Todos los camiones que muestran los filtros, clasificados por su estado de hoy. No depende del mes en que se vendieron."))
        _ayuda_encabezado(self._cab_ab, (
            "Ventas frente a la meta del equipo. La meta no cambia con los filtros de Año y Mes; con un año completo suma la de sus 12 meses." if un_mes else
            "Arriba, las unidades vendidas de cada mes y su meta (línea punteada). Abajo, las bajas del mismo mes: "
            "las bajas (dadas y solicitadas cuentan por igual) y las que no tienen fecha de baja. El punto es la variación del mes."))
        if not un_mes:
            self._cab_composicion.lbl_subtitulo.setText("Todos los camiones de los filtros, hoy.")
            return
        m = self._agregar_mensual(mensual)
        # Con Año o Mes el punto de partida son los camiones que ya existían y se renovaron o cambiaron
        # Si el período llega al mes en curso, el cierre son los camiones conectados hoy de toda la flota (los 5.197 de
        # VC Conectado sin Año ni Mes) y el inicio sale de restarles los nuevos y sumarles las bajas; en períodos
        # pasados se usa la base calculada por fechas
        mf, conectadas = (self._agregar_mensual(flota[0]), flota[1]) if flota else (m, None)
        hoy = date.today()
        cierre = conectadas if conectadas is not None and (mf['periodo'].year, mf['periodo'].month) == (hoy.year, hoy.month) else mf['base']
        self.puente_mes.set_datos([{'inicio': cierre - mf['vendidas'] + mf['bajas'], 'nuevos': mf['vendidas'], 'bajas': mf['bajas'],
                                    'cierre': cierre, 'neto': mf['neto'], 'mes': mes, 'filtrado': bool(filtrando), 'periodo': False,
                                    'renovadas': (getattr(self, '_info_periodo', None) or {}).get('renovados', 0)}])
        meta = self._meta_de_vista(mensual, filtrando, self._metas_vigentes())
        con_civ = " con CIV" if self._meta_es_civ else ""
        self._cab_ab.lbl_subtitulo.setText(f"{_num(m['vendidas'])} ventas{con_civ} de {_num(meta)}" if meta else f"{_num(m['vendidas'])} ventas{con_civ} · sin meta definida")
        self.medidor_meta.set_datos([{'ventas': m['vendidas'], 'meta': meta, 'mes': mes, 'civ': self._meta_es_civ, 'unidad': unidad,
                                      'dia': self._dia_meta_cumplida(m['periodo'], meta) if len(mensual) == 1 else None}])
        unidades = getattr(self, '_unidades_actuales', None)
        mix = servicio.mix_planes(unidades) if unidades is not None else None
        self._mix_planes_mes = mix
        self._cab_composicion.lbl_subtitulo.setText(f"{_num(mix['base'])} camiones conectados de {mes}" if mix else "")
        self.planes_mes.set_datos([mix] if mix else [])
        self._pintar_meta_civ(mensual, filtrando, mes, unidad)

    def _dia_meta_cumplida(self, periodo, meta, sub=None):
        """Día del mes en que las ventas acumuladas llegaron a la meta, o None si aún no se alcanza."""
        sub = sub if sub is not None else getattr(self, '_panorama_movimiento', None)
        if sub is None or not meta:
            return None
        altas = sub['altas']
        dias = altas.loc[altas['FECHA'].dt.to_period('M') == periodo, 'FECHA'].dt.day.value_counts().sort_index().cumsum()
        llegaron = dias[dias >= meta]
        return int(llegaron.index[0]) if len(llegaron) else None

    def _clic_planes_mes(self, clave):
        mix = getattr(self, '_mix_planes_mes', None)
        if not mix:
            return
        if clave.startswith("plan:"):
            plan = next((p for p in mix['planes'] if p['clave'] == clave[5:]), None)
            if plan and plan['vins']:
                self._abrir_en_flotas(plan['vins'], f"Plan {plan['nombre']} con Volvo Connect")
        elif clave in ("civ", "sz") and mix[f"vins_{clave}"]:
            self._abrir_en_flotas(mix[f"vins_{clave}"], "Con CIV" if clave == "civ" else "Con Safety Zone")


    def _clic_un_mes(self, clave):
        """Clic en una barra de los gráficos de un solo mes: abre en General las flotas de esas unidades."""
        periodos = getattr(self, '_periodos_grafico', [])
        sub = getattr(self, '_panorama_movimiento', None)
        if not self._vista_periodo or sub is None:
            return
        if clave in ('altas', 'bajas', 'bajas_dadas', 'bajas_sin_fecha'):
            self._ver_contratos_del_periodo(clave)
            return
        if len(periodos) != 1:
            return
        nombres = {'conectadas': "Conectados", 'por_conectar': "Otros estados", 'desconectadas': "Desconectados"}
        vins = servicio.vins_vendidos_mes_estado(sub, periodos[0], clave)
        self._abrir_en_flotas(vins, f"{nombres[clave]} de {self._etiqueta_mes(periodos[0]).lower()}")

    def _clic_puente_mes(self, clave):
        """Clic en una barra del puente de camiones activos: ese gráfico cuenta toda la flota (Año y Mes no lo
        recortan), así que se abren las unidades de ese movimiento."""
        sub = getattr(self, '_panorama_flota', None)
        if not self._vista_periodo or sub is None:
            return
        if clave in ('altas', 'bajas'):
            self._ver_contratos_del_periodo(clave, sub)
            return
        nuevos = getattr(self, '_vins_nuevos_periodo', None)
        if nuevos is None:
            return
        mes = self._etq_periodo
        if clave == 'renovados':
            vista = getattr(self, '_panorama_vista', None)
            if vista is not None:
                self._abrir_en_flotas(sorted(set(vista['unidades']['VIN']) - nuevos), f"Renovados de {mes}")

    def _ver_contratos_del_periodo(self, tipo, sub=None):
        """Como _ver_contratos_del_mes, pero con todos los meses a la vista (el Año elegido o los meses sueltos)."""
        sub = sub if sub is not None else getattr(self, '_panorama_movimiento', None)
        periodos = getattr(self, '_periodos_grafico', [])
        if sub is None or not periodos:
            return
        eventos = sub['altas' if tipo == 'altas' else 'bajas']
        if tipo in ('bajas_dadas', 'bajas_sin_fecha') and 'TIPO' in eventos.columns:
            sin_fecha = eventos['TIPO'] == servicio.TIPO_BAJA_SIN_FECHA
            eventos = eventos[sin_fecha if tipo == 'bajas_sin_fecha' else ~sin_fecha]
        vins = sorted(set(eventos.loc[eventos['FECHA'].dt.to_period('M').isin(periodos), 'VIN']))
        nombre = {'altas': "Nuevos", 'bajas_dadas': "Bajas dadas", 'bajas_sin_fecha': "Bajas sin fecha"}.get(tipo, "Bajas")
        mes = self._etq_periodo
        if not vins:
            QMessageBox.information(self, "Sin contratos", f"No hay {nombre.lower()} en {mes}.")
            return
        self._abrir_en_flotas(vins, f"{nombre} de {mes}")

    def _ver_contratos_del_mes(self, indice, tipo, sub=None):
        """Clic en un mes del gráfico de entradas y salidas: abre en General (Flotas) las flotas de
        las unidades que entraron o salieron ese mes, con los filtros del tablero aplicados."""
        sub = sub if sub is not None else getattr(self, '_panorama_movimiento', None)
        periodos = getattr(self, '_periodos_grafico', [])
        if sub is None or not 0 <= indice < len(periodos):
            return
        periodo = periodos[indice]
        eventos = sub['altas' if tipo == 'altas' else 'bajas']
        if tipo in ('bajas_dadas', 'bajas_sin_fecha') and 'TIPO' in eventos.columns:
            # Las solicitadas cuentan como dadas; las sin fecha de baja van aparte
            sin_fecha = eventos['TIPO'] == servicio.TIPO_BAJA_SIN_FECHA
            eventos = eventos[sin_fecha if tipo == 'bajas_sin_fecha' else ~sin_fecha]
        vins = sorted(set(eventos.loc[eventos['FECHA'].dt.to_period('M') == periodo, 'VIN']))
        nombre = {'altas': "Nuevos", 'bajas_dadas': "Bajas dadas", 'bajas_sin_fecha': "Bajas sin fecha"}.get(tipo, "Bajas")
        mes = self._etiqueta_mes(periodo).lower()
        if not vins:
            QMessageBox.information(self, "Sin contratos", f"No hay {nombre.lower()} en {mes}.")
            return
        self._abrir_en_flotas(vins, f"{nombre} de {mes}")

    def _abrir_en_flotas(self, vins, titulo):
        """Lleva a General -> Flotas con las flotas de estos VIN y sus unidades a la vista."""
        if not vins:
            QMessageBox.information(self, "Sin camiones", f"No hay camiones en «{titulo}».")
            return
        abrir = getattr(self.window(), 'abrir_flotas_en_general', None)
        if abrir is not None:
            abrir(list(vins), titulo)

    def _meta_del_mes(self, periodo, filtrando):
        return None if filtrando else self._metas_vigentes().get((periodo.year, periodo.month))

    def _meta_del_periodo(self, periodo, mensual, filtrando_meta):
        """(título, meta, vendidas) de los meses a la vista cuando son varios: un año entero suma la meta de sus 12 meses."""
        if filtrando_meta or not periodo or len(mensual) < 2:
            return None
        anio, meses = periodo.get('anio'), periodo.get('meses')
        if anio and not meses:
            meta, titulo = sum(self._metas_vigentes().get((anio, n), 0) for n in range(1, 13)), f"Meta {anio}"
        else:
            meta, titulo = sum(self._metas_vigentes().get((m['periodo'].year, m['periodo'].month), 0) for m in mensual), "Meta del período"
        return (titulo, meta, sum(m['vendidas'] for m in mensual)) if meta else None

    def _pintar_kpis_resumen(self, k, mensual, filtrando, mensual_base=None):
        m = mensual[-1] if mensual else None
        mes = self._etiqueta_mes(m['periodo']).split()[0].lower() if m else ""
        info = getattr(self, '_info_periodo', None)
        if info:
            self._k["universo"].poner(_num(k['universo']), f"{_num(info['nuevos'])} nuevos y {_num(info['renovados'])} renovados")
        elif m:
            self._k["universo"].poner(_num(k['universo']), f"{_num(m['vendidas'])} nuevos en {mes}")
        else:
            self._k["universo"].poner(_num(k['universo']))
        previo_p = getattr(self, '_previo_periodo', None) if info else None
        ayuda_mes = f"frente a {previo_p['nombre']}" if previo_p else "frente al cierre del mes pasado"

        def _pct_cambio(actual, previo):
            return (actual - previo) / previo * 100 if previo else None
        previo_univ = previo_p['k']['universo'] if previo_p else (k['universo'] - m['vendidas'] if m and not info else 0)
        c = _pct_cambio(k['universo'], previo_univ) if previo_univ else None
        self._k["universo"].poner_tendencia(c, _texto_pct_chip(c), f"Contratos {ayuda_mes}." if previo_p else f"Camiones totales {ayuda_mes} (sin contar los nuevos del mes).")
        self._k["universo"].setToolTip("Unidades distintas (VIN) según los filtros. Incluye las No aplica solo si marcas esa casilla.")
        serie_base = mensual_base or mensual
        activos = k['con_producto']
        tasa = activos / k['universo'] if k['universo'] else 0.0
        self._k["conectadas"].poner(_num(activos))
        self._k["conectadas"].delta.setText(f"CIV {_num(k['civ'])} · SZ {_num(k['sz'])}")
        self._k["conectadas"].delta.show()
        base_prev = previo_p['k']['con_producto'] if previo_p else (serie_base[-2]['base'] if len(serie_base) > 1 else 0)
        c = _pct_cambio(activos, base_prev)
        self._k["conectadas"].poner_tendencia(c, _texto_pct_chip(c), f"Camiones conectados {ayuda_mes}.")
        desglose = " · ".join(f"{e.capitalize()} {_num(n)}" for e, n in k['desglose_conectados'] if n)
        self._k["conectadas"].setToolTip(f"Camiones hoy en estos estados: {desglose}. CIV: {_num(k['civ'])} ({_pct(k['civ_pct'])}) · "
                                         f"Safety Zone (SZ): {_num(k['sz'])} ({_pct(k['sz_pct'])}) de estas unidades.")
        self._k["penetracion"].poner(_pct(tasa), f"{_num(activos)} de {_num(k['universo'])} camiones")
        prev_tasa = (base_prev / previo_univ) if previo_univ and base_prev else None
        d_pp = (tasa - prev_tasa) * 100 if prev_tasa is not None else None
        self._k["penetracion"].poner_tendencia(d_pp, f"{abs(d_pp):.1f} pp".replace('.', ',') if d_pp is not None else "", f"Puntos porcentuales {ayuda_mes}.")
        self._k["penetracion"].setToolTip("Porcentaje de camiones con Volvo Connect: conectados, en activación, sin flota y no entregados, "
                                          f"sobre el total de camiones. Hoy: {desglose}.")
        self._k["cobertura"].poner(_pct(k['cobertura_pct']), f"{_num(k['cobertura'])} de {_num(k['con_producto'])} conectados")
        prev_cob = previo_p['k']['cobertura_pct'] if previo_p else getattr(self, '_cobertura_previa', None)
        d_cob = (k['cobertura_pct'] - prev_cob) * 100 if prev_cob is not None else None
        self._k["cobertura"].poner_tendencia(
            d_cob, f"{abs(d_cob):.1f} pp".replace('.', ',') if d_cob is not None else "",
            f"Puntos porcentuales {ayuda_mes}." if previo_p else "Puntos porcentuales frente a la cobertura sin contar los camiones nuevos del mes.")
        sin_cobertura = k['con_producto'] - k['cobertura']
        self._k["cobertura"].setToolTip(f"{_num(sin_cobertura)} camiones conectados aún no tienen su facturación registrada. "
                                        "Haz clic para ver sus flotas.")
        if m:
            meta = self._meta_del_mes(m['periodo'], filtrando)
            per = getattr(self, '_meta_periodo', None)
            cumplido = None
            if per:
                titulo_p, meta_p, vendidas_p = per
                cumplido = vendidas_p / meta_p
            elif meta:
                cumplido = m['vendidas'] / meta
            if cumplido is None:
                estado = "<span>Sin meta definida</span>"
            elif cumplido >= 1:
                estado = f"<span style='color:#0E8F5B'><b>✓ Meta superada</b></span> · {_pct(cumplido)}"
            else:
                estado = f"<span style='color:#C2362D'><b>Bajo la meta</b></span> · {_pct(cumplido)}"
            self._k["neto"].poner(_con_signo(m['neto']), f"{_num(m['vendidas'])} altas y {_num(m['bajas'])} bajas", "", (), VERDE if m['neto'] >= 0 else ROJO)
            previo = mensual[-2]['neto'] if len(mensual) > 1 else (previo_p['neto'] if previo_p else None)
            dif = m['neto'] - previo if previo is not None else None
            self._k["neto"].poner_tendencia(dif, _con_signo(dif) if dif is not None else "", f"Diferencia de la variación {ayuda_mes}.")
            self._k["neto"].valor.setStyleSheet(f"color: {VERDE if m['neto'] >= 0 else '#C2362D'}; font-size: {_TAM_VALOR_KPI}px; font-weight: 800; "
                                                "background: transparent; border: none;")
            positivos = sum(1 for x in mensual if x['neto'] > 0)
            texto = f"{_num(m['vendidas'])} entraron · {_num(m['bajas'])} salieron. {positivos} de {len(mensual)} meses con variación positiva."
            if per:
                texto += f" {per[0]}: {_num(per[2])} de {_num(per[1])}."
            elif meta:
                texto += f" Meta del mes: {_num(meta)}."
            self._k["neto"].setToolTip(texto)
        else:
            self._k["neto"].poner("—")

    def _cola_operaciones(self):
        """(activaciones, sin flota, no entregados) con las mismas reglas y datos que las colas de Operaciones;
        se recalcula solo cuando llega un panorama nuevo."""
        if getattr(self, '_cola_ops', (None,))[0] is not self._panorama:
            df = self.data_manager.get_contratos_actuales_df()
            act, sin_flota = operaciones_services.filtrar_activaciones(df), operaciones_services.filtrar_sin_flota(df)
            no_entregados = operaciones_services.filtrar_no_entregados(df)
            vins = sorted({str(v).strip().upper() for v in list(act['VIN']) + list(sin_flota['VIN']) + list(no_entregados['VIN'])}
                          ) if 'VIN' in df.columns else []
            self._cola_ops = (self._panorama, len(act), len(sin_flota), vins, len(no_entregados))
        return self._cola_ops[1], self._cola_ops[2], self._cola_ops[4]

    def _pintar_estado(self, k, mensual, sub, filtrando):
        """Los chips de «Por atender» (alertas) y el número de la tarjeta Alertas."""
        self._vaciar_chips()
        if not mensual:
            self._k_alertas.poner(0)
            return
        sin_vc = servicio.potenciales_sin_vc(self._panorama)
        if sin_vc['nuevos_mes']:
            self._agregar_alerta(
                0, f"{_num(sin_vc['nuevos_mes'])} nuevos sin servicio", "", 'azul', 'fa5s.user-plus',
                "Camiones nuevos de este mes sin Volvo Connect: son potenciales, no cuentan como ventas. "
                f"{_num(sin_vc['nuevos_con_cliente_vc'])} son de clientes que ya tienen unidades conectadas, los más fáciles de convertir.",
                vins=lambda: servicio.vins_nuevos_sin_vc(self._panorama), titulo="Nuevos sin servicio")
        else:
            self._agregar_alerta(0, "0 nuevos sin servicio", "", 'azul', 'fa5s.user-plus',
                                 f"Este mes no entraron camiones nuevos sin Volvo Connect. En total hay {_num(sin_vc['total'])} potenciales Sin VC.")
        activaciones, sin_flota, no_entregados = self._cola_operaciones()
        pendientes = activaciones + sin_flota + no_entregados
        if pendientes:
            self._agregar_alerta(1, f"{_num(pendientes)} por conectar", "", 'ambar', 'fa5s.plug',
                                 f"Cola de Operaciones: {_num(activaciones)} en activación, {_num(sin_flota)} sin flota en Volvo Connect "
                                 f"y {_num(no_entregados)} no entregados. No cambia con los filtros.",
                                 vins=lambda: self._cola_ops[3], titulo="Por conectar")
        else:
            self._agregar_alerta(1, "Sin pendientes", "", 'verde', 'fa5s.plug',
                                 "Operaciones no tiene unidades en activación, sin flota ni no entregadas.")
        vencidas = servicio.vencidas_sin_desconectar(sub)
        if vencidas:
            self._agregar_alerta(
                2, f"{_num(vencidas)} vencidas y aún conectadas", "", 'ambar', 'fa5s.hourglass-end',
                "Unidades Conectadas o Activando cuyo término de contrato ya pasó y no tienen fecha de baja. Siguen activas, así que "
                "no cuentan como baja hasta que se desconecten: es trabajo de Comercial (renovar o dar de baja).",
                vins=lambda: servicio.vins_vencidas_sin_desconectar(sub), titulo="Contrato vencido, aún conectadas")
        else:
            self._agregar_alerta(2, "Sin vencidas conectadas", "", 'verde', 'fa5s.check-circle',
                                 "Ninguna unidad Conectada o Activando tiene el término de contrato vencido.")
        sin_fecha = servicio.desconectadas_sin_fecha(sub)
        if sin_fecha:
            self._agregar_alerta(3, f"{_num(sin_fecha)} sin fecha", "", 'rojo', 'fa5s.calendar-times',
                                 "Unidades Desconectadas sin fecha de baja ni de término: no aparecen en ningún mes de los gráficos. "
                                 "Asígnales la fecha desde Comercial (Recuperar clientes > Asignar fecha de baja).",
                                 vins=lambda: servicio.vins_desconectadas_sin_fecha(sub), titulo="Desconectadas sin fecha")
        else:
            self._agregar_alerta(3, "Fechas completas", "", 'verde', 'fa5s.calendar-check', "Todas las unidades desconectadas tienen fecha de baja o de término.")
        activas = sum(1 for i in range(self._caja_alertas.count())
                      if self._caja_alertas.itemAt(i).widget() is not None
                      and self._caja_alertas.itemAt(i).widget().property("alertaActiva"))
        self._k_alertas.poner(activas)

    # (fondo, borde, color del ícono, color de las cifras): chips blancos como las tarjetas; el color va en el ícono y las cifras
    _TONOS_ALERTA = {
        'azul': ("#FFFFFF", "#E3E8F0", "#1B2B4E", None),
        'ambar': ("#FFFFFF", "#E3E8F0", "#E08A00", "#B86E00"),
        'rojo': ("#FFFFFF", "#E3E8F0", "#D64541", "#C23A33"),
        'verde': ("#FFFFFF", "#E3E8F0", "#14A06B", "#0E8F5B"),
    }

    @staticmethod
    def _texto_chip(texto, cifra):
        """Texto del chip con las cifras (palabras con números) en el color del tono."""
        seguro = html.escape(texto)
        if cifra is None:
            return seguro
        color = tema.texto(cifra).name()
        return re.sub(r'(\S*\d\S*)', rf'<span style="color:{color}">\1</span>', seguro)

    def _agregar_alerta(self, columna, texto, extra, tono, icono, ayuda, vins=None, titulo="", tam=12):
        """`vins` (función que devuelve los VIN) vuelve clicable el chip: abre sus flotas en General."""
        self._caja_alertas.addWidget(self._crear_chip(texto, extra, tono, icono, ayuda, vins, titulo, tam), 0, columna)

    def _crear_chip(self, texto, extra, tono, icono, ayuda, vins=None, titulo="", tam=12):
        fondo, borde, color, cifra = self._TONOS_ALERTA[tono]
        chip = _ChipClicable()
        chip.setObjectName("chipResumen")
        chip.setProperty("alertaActiva", tono != "verde")
        chip.setToolTip(ayuda + (" Haz clic para ver sus flotas." if vins is not None else ""))
        estilo = f"QFrame#chipResumen {{ background: {fondo}; border: 1px solid {borde}; border-radius: 14px; }}"
        if vins is not None:
            estilo += f"QFrame#chipResumen:hover {{ border: 1px solid {color}; }}"
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda: self._abrir_en_flotas(vins(), titulo))
        chip.setStyleSheet(estilo)
        chip.setMinimumHeight(40)
        chip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay = QHBoxLayout(chip)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(7)
        lay.addStretch(1)
        ico = QLabel()
        ico.setFixedSize(22, 22)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setStyleSheet(f"background: {color}; border-radius: 11px; border: none;")
        ico.setPixmap(qta.icon(icono, color="white").pixmap(11, 11))
        lay.addWidget(ico)
        lbl = _etiqueta(self._texto_chip(texto, cifra), f"color: {TINTA}; font-size: {tam}px; font-weight: 800;")
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lbl)
        if extra:
            lay.addWidget(_etiqueta(extra, f"color: {APAGADO}; font-size: 11.5px; font-weight: 600;"))
        lay.addStretch(1)
        return chip

    def _pintar_composicion(self, k):
        self._vaciar(self._filas_composicion)
        universo = k['universo'] or 1
        desglose = dict(k['desglose_no_conectada'])
        desconectadas = desglose.get('DESCONECTADO', 0)
        # Conectadas reúne los mismos estados que la tarjeta Conectados: Conectado, Activando, Sin flota y No entregado
        conectadas = k['con_producto']
        nombres = {'CONECTADO': "conectadas", 'ACTIVANDO': "en activación", 'SIN FLOTA': "sin flota", 'NO ENTREGADO': "no entregados"}
        partes = [f"{_num(n)} {nombres[e]}" for e, n in k['desglose_conectados'] if n]
        mes = getattr(self, '_composicion_mes', None)   # None si Año o Mes acotan las unidades
        nuevas = {}
        if mes:
            nombre_mes = self._etiqueta_mes(mes['periodo']).split()[0].lower()
            nuevas = {
                'Conectadas': (mes['conectadas_total'], "▲", VERDE,
                               f"Camiones vendidos en {nombre_mes} que hoy están conectados, en activación, sin flota o no entregados."),
                'Desconectadas': (mes['bajas'], "▼", "#C2362D", f"Camiones que se dieron de baja en {nombre_mes}."),
            }
        filas = [("Conectadas", conectadas, MARINO, " · ".join(partes), tuple(servicio.ESTADOS_TARJETA_CONECTADOS)),
                 ("Desconectadas", desconectadas, ROJO, "", ('DESCONECTADO',))]
        filas += [(nombre, n, GRIS_BASE, "", None) for nombre, n in self._otros_estados(k['universo'] - conectadas - desconectadas)]
        self._filas_composicion_datos = filas
        otros = sum(n for nombre, n, *_ in filas[2:])
        info = []
        for nombre, color in (("Conectadas", MARINO), ("Desconectadas", ROJO)):
            if nombre in nuevas and nuevas[nombre][0]:
                cantidad, flecha, tono, ayuda = nuevas[nombre]
                info.append((nombre, color, f"{flecha} {_num(cantidad)}", tono, ayuda))
            else:
                info.append((nombre, color, "", TINTA, ""))
        info.append(("Otros estados", GRIS_BASE, "", TINTA, ""))
        self.estado_camiones.set_datos([{'n0': conectadas, 'n1': desconectadas, 'n2': otros, 'total': k['universo'], 'info': tuple(info)}],
                                       self._animar_graficos)
        self.anillo_composicion.set_datos([(n / universo, c) for _, n, c, _d, _e in filas],
                                          _pct(conectadas / universo), "conectados", self._animar_graficos)
        # En el tablero de un solo mes la caja es muy ancha: en vez del anillo, una barra horizontal
        self.anillo_composicion.setVisible(not self._modo_un_mes)
        self._cuerpo_composicion.setDirection(QBoxLayout.Direction.LeftToRight if self._modo_un_mes else QBoxLayout.Direction.TopToBottom)
        self.barra_composicion.setVisible(bool(self._modo_un_mes))
        self.barra_composicion.set_datos([(n / universo, c) for _, n, c, _d, _e in filas], _pct(conectadas / universo))
        for nombre, n, color, detalle, estados in filas:
            fila = _FilaClicable()
            lay = QHBoxLayout(fila)
            lay.setContentsMargins(6, 3, 6, 3)
            lay.setSpacing(10)
            lay.addWidget(_Punto(color, 12))
            # En media caja el aviso del mes va bajo el nombre; en la caja ancha, a su lado
            aviso = None
            if nombre in nuevas and nuevas[nombre][0]:
                cantidad, flecha, tono, ayuda = nuevas[nombre]
                aviso = _etiqueta(f"{flecha} {_num(cantidad)} este mes", f"color: {tono}; font-size: 12.5px; font-weight: 700;")
                aviso.setToolTip(ayuda)
            if aviso is not None and not self._modo_un_mes:
                aviso.setStyleSheet(aviso.styleSheet().replace("12.5px", "11px"))
                texto = QVBoxLayout()
                texto.setSpacing(0)
                texto.addWidget(_etiqueta(nombre, f"color: {TINTA}; font-size: 14px;"))
                texto.addWidget(aviso)
                lay.addLayout(texto)
                aviso = None
            else:
                lay.addWidget(_etiqueta(nombre, f"color: {TINTA}; font-size: 14px;"))
            lay.addStretch(1)
            if aviso is not None:
                lay.addWidget(aviso)
                lay.addSpacing(8)
            cifra = _etiqueta(_num(n), f"color: {TINTA}; font-size: 15px; font-weight: 800;")
            cifra.setMinimumWidth(56)
            cifra.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(cifra)
            pct = _etiqueta(_pct(n / universo), f"color: {APAGADO}; font-size: 12.5px;")
            pct.setMinimumWidth(40)
            lay.addWidget(pct)
            # El desglose de Por conectar (activación, sin flota, no entregados) queda en el globo de la fila
            fila.setToolTip(f"{nombre}: {_num(n)} camiones" + (f" ({detalle})" if detalle else "") + ". Haz clic para ver sus flotas.")
            fila.clicked.connect(lambda e=estados, nom=nombre: self._abrir_composicion(e, nom))
            self._filas_composicion.addWidget(fila)

    def _abrir_composicion(self, estados, nombre):
        """Clic en una fila de la composición: abre en General las flotas de esos camiones."""
        unidades = self._unidades_actuales
        if unidades is None:
            return
        activacion = unidades['ACTIVACION']
        mascara = activacion.isin(estados) if estados else ~activacion.isin(self._ESTADOS_CONOCIDOS)
        self._abrir_en_flotas(sorted(set(unidades.loc[mascara, 'VIN'])), nombre)

    _ESTADOS_CONOCIDOS = ('CONECTADO', 'ACTIVANDO', 'DESCONECTADO', 'NO ENTREGADO', 'SIN FLOTA')

    def _otros_estados(self, total):
        """Los demás estados de activación con su nombre (hasta tres; el resto se junta en «Otros»)."""
        if total <= 0:
            return []
        unidades = self._unidades_actuales
        cuenta = unidades.loc[~unidades['ACTIVACION'].isin(self._ESTADOS_CONOCIDOS), 'ACTIVACION'].value_counts() \
            if unidades is not None else None
        if cuenta is None or cuenta.empty:
            return [("Otros", total)]
        filas = [(str(e).strip().capitalize() or "Sin estado", int(n)) for e, n in cuenta.items()]
        if len(filas) > 3:
            filas = filas[:2] + [("Otros", sum(n for _, n in filas[2:]))]
        return filas

    def _vaciar_chips(self):
        for i in range(self._caja_alertas.count() - 1, -1, -1):
            widget = self._caja_alertas.itemAt(i).widget()
            if widget is not None and widget.objectName() == "chipResumen":
                self._caja_alertas.removeWidget(widget)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _vaciar(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
