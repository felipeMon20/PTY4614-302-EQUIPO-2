"""Vista ampliada de «Entradas y salidas por mes»: la tarjeta crece hasta el centro del Resumen y muestra las
ventas frente a las tres clases de salida (dado de baja, baja solicitada y sin fecha de baja) con su tabla."""
import math

import qtawesome as qta
from PyQt6.QtCore import QEasingCurve, QPoint, QPointF, QRect, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from src.theme import tema
from src.ui.administracion import estilo as admin_estilo
from src.ui.dashboard.base import APAGADO, LINEA, MARINO, ROJO, ROJO_TEXTO, TINTA, _con_tema, _estilo_marca, _num, _relleno
from src.ui.dashboard.graficos import _GraficoBase

VERDE = "#0E8F5B"
SUAVE = "#F6F8FC"


def _con_signo(n):
    return f"+{_num(n)}" if n > 0 else (f"−{_num(abs(n))}" if n < 0 else "0")


def variacion(d, contar_sin_fecha):
    return d['altas'] - d['dadas'] - d['solicitadas'] - (d['sin_fecha'] if contar_sin_fecha else 0)


def _linea_detalle(titulo, altas, meta, altas_con_meta, dadas, solicitadas, sin_fecha, v):
    color = VERDE if v >= 0 else ROJO_TEXTO

    def cifra(n, texto):
        return f"<b>{_num(n)}</b> {texto}"
    partes = [titulo, cifra(altas, "ventas")]
    if meta:
        cumple = altas_con_meta / meta
        partes.append(f"meta <b>{_num(meta)}</b> · <b style='color:{VERDE if cumple >= 1 else ROJO_TEXTO}'>{round(cumple * 100)}%</b>")
    partes += [cifra(dadas + solicitadas, "bajas"), cifra(sin_fecha, "sin fecha de baja"), f"Variación <b style='color:{color}'>{_con_signo(v)}</b>"]
    return "&nbsp;&nbsp;&nbsp;".join(partes)


def texto_detalle(d, contar_sin_fecha):
    """Línea de detalle de un mes: ventas, meta, salidas por clase y variación (texto enriquecido)."""
    return _linea_detalle(f"<b style='font-size:13px'>{d['mes']}</b>", d['altas'], d.get('meta'), d['altas'], d['dadas'],
                          d['solicitadas'], d['sin_fecha'], variacion(d, contar_sin_fecha))


def texto_resumen_anio(datos, contar_sin_fecha):
    """Línea de detalle del año en curso: la suma de sus meses (el % de meta compara solo los meses que tienen meta)."""
    if not datos:
        return ""
    anio = datos[-1]['periodo'].year
    meses = [d for d in datos if d['periodo'].year == anio]
    con_meta = [d for d in meses if d.get('meta')]
    primero, ultimo = (m['etiqueta'].split()[0] for m in (meses[0], meses[-1]))
    rango = primero if len(meses) == 1 else f"{primero}–{ultimo}"
    titulo = f"<b style='font-size:13px'>{anio}</b> <span style='color:{APAGADO}'>{rango}</span>"
    return _linea_detalle(titulo, sum(d['altas'] for d in meses), sum(d['meta'] for d in con_meta), sum(d['altas'] for d in con_meta),
                          sum(d['dadas'] for d in meses), sum(d['solicitadas'] for d in meses), sum(d['sin_fecha'] for d in meses),
                          sum(variacion(d, contar_sin_fecha) for d in meses))


def _color_sin_fecha():
    color = QColor(_relleno(ROJO))
    color.setAlphaF(0.38)
    return color


class _Muestra(QWidget):
    """Cuadrito de la leyenda: liso, con rayas o punto."""

    def __init__(self, forma):
        super().__init__()
        self._forma = forma
        self.setFixedSize(12, 12)
        _con_tema(self)

    def paintEvent(self, evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        caja = QRectF(0.5, 0.5, 11, 11)
        if self._forma == 'punto':
            p.setPen(QPen(tema.fondo("#FFFFFF"), 1.5))
            p.setBrush(tema.fondo(TINTA))
            p.drawEllipse(QPointF(6, 6), 4.5, 4.5)
        elif self._forma == 'meta':
            p.setPen(QPen(tema.texto(TINTA), 2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(0, 6), QPointF(12, 6))
        elif self._forma == 'rayas':
            p.setPen(QPen(_relleno(ROJO), 1))
            p.setBrush(QBrush(_relleno(ROJO), Qt.BrushStyle.BDiagPattern))
            p.drawRoundedRect(caja, 2.5, 2.5)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush({'nuevo': _relleno(MARINO), 'baja': _relleno(ROJO), 'sin_fecha': _color_sin_fecha()}[self._forma])
            p.drawRoundedRect(caja, 2.5, 2.5)
        p.end()


def leyenda_salidas():
    caja = QWidget()
    caja.setStyleSheet("background: transparent;")
    fila = QHBoxLayout(caja)
    fila.setContentsMargins(0, 0, 0, 0)
    fila.setSpacing(7)
    for i, (forma, texto) in enumerate((('nuevo', "Ventas del mes"), ('meta', "Meta"), ('baja', "Bajas"),
                                        ('sin_fecha', "Sin fecha de baja"), ('punto', "Variación del mes"))):
        if i:
            fila.addSpacing(11)
        fila.addWidget(_Muestra(forma))
        etiqueta = QLabel(texto)
        etiqueta.setStyleSheet(f"color: {APAGADO}; font-size: 11px; background: transparent; border: none;")
        fila.addWidget(etiqueta)
    fila.addStretch(1)
    return caja


class GraficoSalidas(_GraficoBase):
    """Ventas hacia arriba y, hacia abajo, las salidas apiladas por clase; el punto es la variación del mes.
    Muestra los últimos `k` meses (decimal mientras se anima): al sumar meses las columnas se reacomodan y los
    más antiguos aparecen con un fundido."""
    IZQ, DER, ARRIBA = 42, 10, 20
    mes_foco = pyqtSignal(int)
    mes_salio = pyqtSignal()
    mes_clicado = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(130)
        self._hover = None
        self._foco = None
        # Sombreado del mes bajo el mouse: se desliza de una columna a otra y se funde al entrar y salir
        self._banda = 0.0
        self._banda_op = 0.0
        self._anim_banda = QVariantAnimation(self)
        self._anim_banda.setDuration(200)
        self._anim_banda.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_banda.valueChanged.connect(self._mover_banda)
        self._anim_banda_op = QVariantAnimation(self)
        self._anim_banda_op.setDuration(180)
        self._anim_banda_op.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim_banda_op.valueChanged.connect(self._mover_banda_op)
        self._contar = True
        self._progreso = 1.0
        self._k = None
        self._anim_k = QVariantAnimation(self)
        self._anim_k.setDuration(420)
        self._anim_k.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim_k.valueChanged.connect(self._mover_k)
        self._anim_crece = QVariantAnimation(self)
        self._anim_crece.setStartValue(0.0)
        self._anim_crece.setEndValue(1.0)
        self._anim_crece.setDuration(520)
        self._anim_crece.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_crece.valueChanged.connect(lambda v: self.set_progreso(float(v)))

    def sizeHint(self):
        return QSize(900, 300)

    def set_datos(self, datos, animado=False):
        """Con `animado`, los meses que ya estaban pasan de sus valores anteriores a los nuevos; si cambia la cantidad
        de meses las barras vuelven a crecer desde cero."""
        mismos = len(datos) == len(self._destino)
        self._anim_crece.stop()
        super().set_datos(datos, animado and mismos)
        if animado and not mismos and self.isVisible() and datos:
            self._progreso = 0.0
            self._anim_crece.start()

    def set_contar(self, contar):
        self._contar = contar
        self.update()

    def set_progreso(self, valor):
        self._progreso = valor
        self.update()

    def set_foco(self, indice):
        self._foco = indice
        self.update()

    def _mover_k(self, valor):
        self._k = float(valor)
        self.update()

    def set_visibles(self, cantidad, animado=False):
        """Cuántos meses se ven (los más recientes)."""
        cantidad = float(max(1, min(cantidad, len(self._datos) or cantidad)))
        self._anim_k.stop()
        if animado and self._k and self._k != cantidad and self.isVisible():
            self._anim_k.setStartValue(self._k)
            self._anim_k.setEndValue(cantidad)
            self._anim_k.start()
        else:
            self._k = cantidad
            self.update()

    def _visibles(self):
        """(índice del primer mes dibujado, meses dibujados, k, peso de cada uno): el más antiguo puede estar a medio aparecer."""
        n = len(self._datos)
        k = min(max(self._k if self._k else float(n), 1.0), float(n))
        cantidad = min(n, math.ceil(k))
        pesos = [1.0 if (cantidad - i) <= k else k - (cantidad - 1) for i in range(cantidad)]
        return n - cantidad, self._datos[n - cantidad:], k, pesos

    @property
    def ABAJO(self):
        # Con metas, bajo cada mes va una segunda línea con su porcentaje de meta
        return 44 if any(d.get('meta') for d in self._datos) else 26

    def _area(self):
        return QRectF(self.IZQ, self.ARRIBA, self.width() - self.IZQ - self.DER, self.height() - self.ARRIBA - self.ABAJO)

    def _rango(self):
        _inicio, vistos, _k, pesos = self._visibles()
        arriba = max(100.0, max(max(d['altas'], d.get('meta') or 0) * w for d, w in zip(vistos, pesos)))
        abajo = max(100.0, max((d['dadas'] + d['solicitadas'] + d['sin_fecha']) * w for d, w in zip(vistos, pesos)))
        # Un poco más de espacio abajo para la cifra de bajas bajo cada barra
        return -abajo * 1.18, arriba

    def _indice(self, x):
        """Posición (en la lista completa) del mes bajo la coordenada x, o None."""
        inicio, vistos, k, _pesos = self._visibles()
        area = self._area()
        paso = area.width() / k
        i = int((x - (area.right() - len(vistos) * paso)) // paso)
        return inicio + i if 0 <= i < len(vistos) else None

    def mouseMoveEvent(self, event):
        if not self._datos:
            return
        nuevo = self._indice(event.position().x())
        if nuevo != self._hover:
            anterior = self._hover
            self._hover = nuevo
            self.setCursor(Qt.CursorShape.PointingHandCursor if nuevo is not None else Qt.CursorShape.ArrowCursor)
            self._llevar_banda(nuevo, anterior)
            if nuevo is not None:
                self.mes_foco.emit(nuevo)
            else:
                self.mes_salio.emit()
            self.update()

    def leaveEvent(self, event):
        salia = self._hover is not None
        self._hover = None
        self._llevar_banda(None, 0)
        if salia:
            self.mes_salio.emit()
        self.update()

    def _mover_banda(self, valor):
        self._banda = float(valor)
        self.update()

    def _mover_banda_op(self, valor):
        self._banda_op = float(valor)
        self.update()

    def _llevar_banda(self, nuevo, anterior):
        """Desliza el sombreado hasta la columna `nuevo` (o lo funde si el mouse salió)."""
        visible = self.isVisible()
        if nuevo is not None:
            self._anim_banda.stop()
            if anterior is None or self._banda_op < 0.05 or not visible:
                self._banda = float(nuevo)
            else:
                self._anim_banda.setStartValue(self._banda)
                self._anim_banda.setEndValue(float(nuevo))
                self._anim_banda.start()
        destino = 0.0 if nuevo is None else 1.0
        self._anim_banda_op.stop()
        if visible and self._banda_op != destino:
            self._anim_banda_op.setStartValue(self._banda_op)
            self._anim_banda_op.setEndValue(destino)
            self._anim_banda_op.start()
        else:
            self._banda_op = destino

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._datos or self._hover is None:
            return
        area = self._area()
        lo, hi = self._rango()
        cero = area.bottom() - (0 - lo) / (hi - lo) * area.height()
        self.mes_clicado.emit(self._hover, 'altas' if event.position().y() < cero else 'bajas')

    def paintEvent(self, event):
        if not self._datos:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self._area()
        lo, hi = self._rango()
        escala = area.height() / (hi - lo)
        y = lambda v: area.bottom() - (v - lo) * escala
        inicio, vistos, k, pesos = self._visibles()
        paso = area.width() / k
        ancho = paso * 0.56
        p = self._progreso
        if self._banda_op > 0.01:
            cx_banda = area.right() - (len(vistos) - (self._banda - inicio)) * paso + paso / 2
            if area.left() - paso / 2 <= cx_banda <= area.right() + paso / 2:
                fondo = QColor(120, 140, 175, round(40 * self._banda_op))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(fondo)
                painter.drawRoundedRect(QRectF(cx_banda - paso / 2 + 2, 2, paso - 4, self.height() - 4), 9, 9)
        painter.setFont(self._fuente(10))
        salto = 100 if hi - lo <= 800 else 200
        for valor in range(int(math.ceil(lo / salto)) * salto, int(hi) + 1, salto):
            painter.setPen(QPen(tema.fondo("#9AA8C0" if valor == 0 else LINEA), 1.4 if valor == 0 else 1,
                                Qt.PenStyle.SolidLine if valor == 0 else Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(area.left(), y(valor)), QPointF(area.right(), y(valor)))
            self._texto(painter, QRectF(0, y(valor) - 8, self.IZQ - 6, 16), Qt.AlignmentFlag.AlignRight,
                        f"+{valor}" if valor > 0 else str(valor), APAGADO)
        colores = {'dadas': _relleno(ROJO), 'sin_fecha': _color_sin_fecha()}
        for pos, (d, peso) in enumerate(zip(vistos, pesos)):
            i = inicio + pos
            cx = area.right() - (len(vistos) - pos) * paso + paso / 2
            painter.setOpacity(peso)
            alto = d['altas'] * escala * p
            if alto > 0:
                self._barra(painter, QRectF(cx - ancho / 2, y(0) - alto, ancho, alto), MARINO, 3)
            corte = y(0)
            for clave in ('dadas', 'solicitadas', 'sin_fecha'):
                h = d[clave] * escala * p
                if h <= 0:
                    continue
                ruta = QPainterPath()
                ruta.addRoundedRect(QRectF(cx - ancho / 2, corte, ancho, max(h, 1.5)), 2, 2)
                if clave == 'solicitadas':
                    painter.fillPath(ruta, tema.fondo("#FFFFFF"))
                    painter.fillPath(ruta, QBrush(_relleno(ROJO), Qt.BrushStyle.BDiagPattern))
                    painter.setPen(QPen(_relleno(ROJO), 1.2))
                    painter.drawPath(ruta)
                else:
                    painter.fillPath(ruta, colores[clave])
                corte += h
            meta = d.get('meta')
            if meta:
                painter.setPen(QPen(tema.texto(TINTA), 2, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(cx - ancho / 2 - 10, y(meta)), QPointF(cx + ancho / 2 + 10, y(meta)))
            painter.setOpacity(peso * max(0.0, (p - 0.6) / 0.4))
            painter.setFont(self._fuente(11, True))
            self._texto(painter, QRectF(cx - paso / 2, y(0) - alto - 18, paso, 16), Qt.AlignmentFlag.AlignHCenter, _num(d['altas']), TINTA)
            bajas = d['dadas'] + d['solicitadas'] + d['sin_fecha']
            if bajas:
                self._texto(painter, QRectF(cx - paso / 2, corte + 3, paso, 16), Qt.AlignmentFlag.AlignHCenter, _num(bajas), ROJO_TEXTO)
            painter.setPen(QPen(tema.fondo("#FFFFFF"), 2))
            painter.setBrush(tema.fondo(TINTA))
            painter.drawEllipse(QPointF(cx, y(variacion(d, self._contar))), 4.6, 4.6)
            painter.setOpacity(peso)
            painter.setFont(self._fuente(10, i == self._foco))
            self._texto(painter, QRectF(cx - paso / 2, self.height() - self.ABAJO + 4, paso, 16),
                        Qt.AlignmentFlag.AlignHCenter, d['etiqueta'], TINTA if i == self._foco else APAGADO)
            if meta:
                cumple = d['altas'] / meta
                painter.setFont(self._fuente(10, True))
                texto = f"{round(cumple * 100)}%"
                self._texto(painter, QRectF(cx - paso / 2, self.height() - self.ABAJO + 20, paso, 16),
                            Qt.AlignmentFlag.AlignHCenter, texto, VERDE if cumple >= 1 else ROJO_TEXTO)
        painter.setOpacity(1.0)
        painter.end()

class TablaSalidas(QWidget):
    """Resumen en tabla de los meses del gráfico: ventas, cada clase de salida, variación y total."""
    ALTO_FILA = 26
    ANCHO_ROTULO = 128
    ANCHO_TOTAL = 66
    FILAS = (("Ventas del mes", 'altas'), ("Bajas", 'dadas'),("Sin fecha de baja", 'sin_fecha'))

    def __init__(self, parent=None):
        super().__init__(parent)
        self._datos = []
        self._contar = True
        self.setFixedHeight(self.ALTO_FILA * (len(self.FILAS) + 2))
        _con_tema(self)

    def set_datos(self, datos, contar):
        self._datos, self._contar = datos, contar
        self.update()

    def paintEvent(self, event):
        if not self._datos:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self._datos)
        h = self.ALTO_FILA
        caja = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        ruta = QPainterPath()
        ruta.addRoundedRect(caja, 10, 10)
        painter.setClipPath(ruta)
        painter.fillRect(QRectF(0, 0, self.width(), h), tema.fondo(SUAVE))
        ancho_col = (self.width() - self.ANCHO_ROTULO - self.ANCHO_TOTAL) / n
        x_total = self.width() - self.ANCHO_TOTAL
        izq = Qt.AlignmentFlag.AlignLeft
        der = Qt.AlignmentFlag.AlignRight
        painter.setFont(self._fuente(10, True))
        for j, d in enumerate(self._datos):
            self._texto(painter, QRectF(self.ANCHO_ROTULO + j * ancho_col, 0, ancho_col - 8, h), der, d['etiqueta'], APAGADO)
        self._texto(painter, QRectF(x_total, 0, self.ANCHO_TOTAL - 8, h), der, "Total", APAGADO)
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        for r in range(1, len(self.FILAS) + 2):
            painter.drawLine(QPointF(0, r * h), QPointF(self.width(), r * h))
        for r, (rotulo, clave) in enumerate(self.FILAS, start=1):
            painter.setFont(self._fuente(11, True))
            self._texto(painter, QRectF(10, r * h, self.ANCHO_ROTULO - 10, h), izq, rotulo, TINTA)
            painter.setFont(self._fuente(11))
            for j, d in enumerate(self._datos):
                self._texto(painter, QRectF(self.ANCHO_ROTULO + j * ancho_col, r * h, ancho_col - 8, h), der,
                            _num(d[clave]) if d[clave] else "–", TINTA if d[clave] else APAGADO)
            painter.setFont(self._fuente(11, True))
            total = sum(d[clave] for d in self._datos)
            self._texto(painter, QRectF(x_total, r * h, self.ANCHO_TOTAL - 8, h), der, _num(total), TINTA)
        r = len(self.FILAS) + 1
        painter.setFont(self._fuente(11, True))
        self._texto(painter, QRectF(10, r * h, self.ANCHO_ROTULO - 10, h), izq, "Variación", TINTA)
        for j, d in enumerate(self._datos):
            v = variacion(d, self._contar)
            self._texto(painter, QRectF(self.ANCHO_ROTULO + j * ancho_col, r * h, ancho_col - 8, h), der, _con_signo(v),
                        VERDE if v >= 0 else ROJO_TEXTO)
        self._texto(painter, QRectF(x_total, r * h, self.ANCHO_TOTAL - 8, h), der,
                    _con_signo(sum(variacion(d, self._contar) for d in self._datos)), TINTA)
        painter.setClipping(False)
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(ruta)
        painter.end()

    def _fuente(self, px, negrita=False):
        f = QFont(self.font())
        f.setPixelSize(px)
        f.setBold(negrita)
        return f

    @staticmethod
    def _texto(painter, rect, alineacion, texto, color):
        painter.setPen(tema.texto(color))
        painter.drawText(rect, alineacion | Qt.AlignmentFlag.AlignVCenter, texto)


class VistaAmpliadaSalidas(QWidget):
    """Capa sobre el Resumen: oscurece el tablero y hace crecer la tarjeta desde su lugar hasta el centro."""
    pedir_flotas = pyqtSignal(int, str)   # posición del mes y 'altas' o 'bajas'

    DURACION = 520
    MARGEN = 16

    def __init__(self, parent):
        super().__init__(parent)
        self.hide()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._datos = []
        self._abierta = False
        self._animando = False
        self._t = 0.0
        self._origen = QRect()
        self._foto_tarjeta = self._foto_panel = self._fondo = None
        # La capa pinta ella sola el fondo (una foto del tablero): así Qt no repinta los gráficos de abajo en cada cuadro
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        caja = admin_estilo.caja_con_encabezado("ampliadoAltasBajas", "Ventas, Bajas y Metas",
                                                "Lo que se vendió cada mes frente a las bajas del mismo mes y a la meta del equipo.")
        self._panel = caja.marco
        self._panel.setParent(self)
        btn = QPushButton(" Cerrar")
        btn.setIcon(qta.icon('fa5s.times', color='#1B2B4E'))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("QPushButton { background: #F4F6FB; color: #1B2B4E; border: none; border-radius: 10px; padding: 7px 12px; "
                          "font-size: 12px; font-weight: 700; } QPushButton:hover { background: #FFFFFF; }")
        btn.clicked.connect(lambda: self.cerrar())
        caja.fila_cab.addWidget(btn)
        self._cuerpo = QWidget()
        self._cuerpo.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self._cuerpo)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(8)
        fila = QHBoxLayout()
        fila.setSpacing(14)
        fila.addWidget(leyenda_salidas(), 1)
        self.chk_sin_fecha = QCheckBox("Contar en la variación las bajas sin fecha")
        self.chk_sin_fecha.setChecked(True)
        self.chk_sin_fecha.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_sin_fecha.setStyleSheet(_estilo_marca().replace("padding: 7px 10px", "padding: 4px 9px"))
        self.chk_sin_fecha.setToolTip("Las bajas sin fecha de baja son contratos con el término vencido y la unidad desconectada. "
                                      "Hoy cuentan en el mes del término; desmarcada, no se descuentan de la variación.")
        self.chk_sin_fecha.toggled.connect(self._cambio_conteo)
        fila.addWidget(self.chk_sin_fecha)
        lay.addLayout(fila)
        self.grafico = GraficoSalidas()
        self.grafico.mes_foco.connect(self._foco)
        self.grafico.mes_clicado.connect(self._clic)
        lay.addWidget(self.grafico, 1)
        self.detalle = QLabel()
        self.detalle.setMinimumHeight(38)
        self.detalle.setStyleSheet(f"background: {SUAVE}; border: 1px solid {LINEA}; border-radius: 12px; padding: 4px 14px; "
                                   f"color: {TINTA}; font-size: 12px;")
        lay.addWidget(self.detalle)
        self.tabla = TablaSalidas()
        lay.addWidget(self.tabla)
        caja.cuerpo.addWidget(self._cuerpo, 1)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.DURACION)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._aplicar)
        self._anim.finished.connect(self._al_terminar)
        self._crecer = QVariantAnimation(self)
        self._crecer.setStartValue(0.0)
        self._crecer.setEndValue(1.0)
        self._crecer.setDuration(650)
        self._crecer.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._crecer.valueChanged.connect(lambda v: self.grafico.set_progreso(float(v)))
        _con_tema(self)

    # ------------------------------------------------------------------ datos
    def set_datos(self, datos):
        self._datos = datos
        self.grafico.set_datos(datos)
        self._foco(min(self.grafico._foco if self.grafico._foco is not None else len(datos) - 1, len(datos) - 1) if datos else 0)
        self.tabla.set_datos(datos, self.chk_sin_fecha.isChecked())

    def _cambio_conteo(self, contar):
        self.grafico.set_contar(contar)
        self.tabla.set_datos(self._datos, contar)
        if self._datos:
            self._foco(self.grafico._foco or 0)

    def _foco(self, i):
        if not self._datos:
            self.detalle.setText("")
            return
        self.detalle.setText(texto_detalle(self._datos[i], self.chk_sin_fecha.isChecked()))
        self.grafico.set_foco(i)

    def _clic(self, indice, tipo):
        self.cerrar(rapido=True)
        self.pedir_flotas.emit(indice, tipo)

    # ------------------------------------------------------------------ apertura y cierre
    # Mientras la tarjeta crece se dibujan dos fotos (la tarjeta y la vista ampliada) escaladas: los widgets reales
    # solo se muestran al terminar, así no se reacomoda todo el contenido en cada cuadro.
    def _objetivo(self):
        ancho = min(980, self.width() - 2 * self.MARGEN)
        alto = min(max(self._panel.sizeHint().height(), 420), self.height() - 2 * self.MARGEN)
        return QRect((self.width() - ancho) // 2, (self.height() - alto) // 2, ancho, alto)

    def _fotografiar_panel(self):
        self._panel.setGeometry(self._objetivo())
        self._panel.show()
        self._panel.layout().activate()
        self._foto_panel = self._redondear(self._panel.grab())
        self._panel.hide()

    @staticmethod
    def _redondear(foto, radio=14):
        """Foto con las esquinas redondeadas ya recortadas, para no recortar en cada cuadro de la animación."""
        resultado = QPixmap(foto.size())
        resultado.setDevicePixelRatio(foto.devicePixelRatio())
        resultado.fill(Qt.GlobalColor.transparent)
        p = QPainter(resultado)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ruta = QPainterPath()
        ruta.addRoundedRect(QRectF(0, 0, foto.width() / foto.devicePixelRatio(), foto.height() / foto.devicePixelRatio()), radio, radio)
        p.setClipPath(ruta)
        p.drawPixmap(0, 0, foto)
        p.end()
        return resultado

    def _tomar_fondo(self):
        """Foto del tablero tal como está, sin esta capa."""
        visible = self.isVisible()
        if visible:
            self.hide()
        self._fondo = self.parentWidget().grab()
        if visible:
            self.show()

    def _aplicar(self, t):
        self._t = float(t)
        self.update()

    def abrir(self, origen, datos, foto_tarjeta=None):
        """`origen` es el rectángulo de la tarjeta, en coordenadas de la pantalla que contiene esta capa."""
        if self._abierta:
            return
        self._abierta = True
        self._origen = origen
        self.setGeometry(self.parentWidget().rect())
        self._tomar_fondo()
        dpr = self._fondo.devicePixelRatio()
        self._foto_tarjeta = self._redondear(self._fondo.copy(QRect(int(origen.x() * dpr), int(origen.y() * dpr),
                                                                  int(origen.width() * dpr), int(origen.height() * dpr))))
        self.set_datos(datos)
        self.grafico.set_progreso(0.0)
        self._t = 0.0
        self.show()
        self.raise_()
        self.setFocus()
        self._fotografiar_panel()
        self._animando = True
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def cerrar(self, rapido=False):
        if not self._abierta:
            return
        self._abierta = False
        self._crecer.stop()
        self._anim.stop()
        if rapido:
            self._animando = False
            self._panel.hide()
            self.hide()
            return
        if not self._animando:
            self.grafico.set_progreso(1.0)
            self._fotografiar_panel()
            self._animando = True
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _al_terminar(self):
        self._animando = False
        if self._abierta:
            self._panel.setGeometry(self._objetivo())
            self._panel.show()
            self._crecer.start()
        else:
            self.hide()

    def reubicar(self):
        if not self.parentWidget():
            return
        self.setGeometry(self.parentWidget().rect())
        if self._abierta and not self._animando:
            self._tomar_fondo()
            self._panel.setGeometry(self._objetivo())

    @property
    def abierta(self):
        return self._abierta

    # ------------------------------------------------------------------ eventos
    def paintEvent(self, event):
        painter = QPainter(self)
        if self._fondo is not None:
            painter.drawPixmap(QRectF(self.rect()), self._fondo, QRectF(self._fondo.rect()))
        painter.fillRect(self.rect(), QColor(10, 18, 36, int(120 * self._t)))
        if self._animando and self._foto_panel is not None:
            o, d, t = self._origen, self._objetivo(), self._t
            rect = QRectF(o.x() + (d.x() - o.x()) * t, o.y() + (d.y() - o.y()) * t,
                          o.width() + (d.width() - o.width()) * t, o.height() + (d.height() - o.height()) * t)
            if self._foto_tarjeta is not None:
                painter.drawPixmap(rect, self._foto_tarjeta, QRectF(self._foto_tarjeta.rect()))
            painter.setOpacity(max(0.0, min(1.0, (t - 0.15) / 0.55)) if self._foto_tarjeta is not None else 1.0)
            painter.drawPixmap(rect, self._foto_panel, QRectF(self._foto_panel.rect()))
        painter.end()

    def mousePressEvent(self, event):
        if self._animando:
            return
        if not self._panel.geometry().contains(event.position().toPoint()):
            self.cerrar()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and not self._animando:
            self.cerrar()
        else:
            super().keyPressEvent(event)