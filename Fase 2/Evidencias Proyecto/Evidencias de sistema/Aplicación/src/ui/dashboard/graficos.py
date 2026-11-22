"""Gráficos del Dashboard pintados a mano: mes a mes, metas, servicio, ejecutivo, fuga y clientes."""
import math
from PyQt6.QtCore import QVariantAnimation, Qt, QRectF, QPropertyAnimation, QEasingCurve, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QToolTip, QSizePolicy, QWidget
from src.services import dashboard_services as servicio
from src.theme import tema
from src.ui.dashboard.base import (
    APAGADO,
    AZUL_SUAVE,
    LINEA,
    MARINO,
    ROJO,
    ROJO_SUAVE,
    ROJO_TEXTO,
    TINTA,
    TONO_CLARO,
    TONO_MEDIO,
    TONO_SUAVE,
    _con_tema,
    _num,
    _pct,
    _relleno,
)


class _GraficoBase(QWidget):
    """Lo común de los gráficos pintados a mano: fuente y colores sobre tarjeta blanca."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._datos = []
        self._destino = []          # los datos a los que llega la animación (iguales a _datos cuando no hay una en curso)
        self._origen_datos = []
        self._anim_datos = QVariantAnimation(self)
        self._anim_datos.setDuration(380)
        self._anim_datos.setStartValue(0.0)
        self._anim_datos.setEndValue(1.0)
        self._anim_datos.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_datos.valueChanged.connect(self._paso_datos)
        self._anim_datos.finished.connect(self._fin_datos)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        _con_tema(self)

    def set_datos(self, datos, animado=False):
        """Con `animado` los valores pasan de los anteriores a los nuevos (solo si ya había datos a la vista)."""
        self._anim_datos.stop()
        self._destino = datos
        if animado and self.isVisible() and self._datos and datos:
            self._origen_datos = self._datos
            self._anim_datos.start()
            return
        self._datos = datos
        self.update()

    @staticmethod
    def _mezclar(origen, destino, t):
        """Datos intermedios entre dos listas de diccionarios, alineadas por el final: los números se mezclan."""
        n, m = len(destino), len(origen)
        resultado = []
        for i, d in enumerate(destino):
            j = i - (n - m)
            o = origen[j] if 0 <= j < m else None
            if o is None:
                resultado.append(d)
                continue
            e = dict(d)
            for clave, v in d.items():
                ov = o.get(clave)
                if isinstance(v, bool) or isinstance(ov, bool) or not isinstance(v, (int, float)) or not isinstance(ov, (int, float)):
                    continue
                mezcla = ov + (v - ov) * t
                e[clave] = int(round(mezcla)) if isinstance(v, int) and isinstance(ov, int) else mezcla
            resultado.append(e)
        return resultado

    def _paso_datos(self, t):
        self._datos = self._mezclar(self._origen_datos, self._destino, float(t))
        self.update()

    def _fin_datos(self):
        self._datos = self._destino
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
    mes_clicado = pyqtSignal(object)   # período (pd.Period) de la columna presionada

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
        self._estado = 'todos'
        self._w = [1.0, 1.0, 1.0]
        self._w0 = [1.0, 1.0, 1.0]
        self._w1 = [1.0, 1.0, 1.0]
        self._anim_w = QVariantAnimation(self)
        self._anim_w.setDuration(280)
        self._anim_w.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim_w.setStartValue(0.0)
        self._anim_w.setEndValue(1.0)
        self._anim_w.valueChanged.connect(self._mover_w)

    _PESOS_ESTADO = {'todos': (1.0, 1.0, 1.0), 'conectadas': (1.0, 0.0, 0.0), 'otros': (0.0, 1.0, 0.0),
                     'desconectadas': (0.0, 0.0, 1.0)}

    @property
    def estado(self):
        return self._estado

    def set_estado(self, clave, animado=True):
        """Qué parte de lo vendido se ve: todo, solo conectadas, solo desconectadas o solo las demás (por conectar y otros)."""
        if clave not in self._PESOS_ESTADO or clave == self._estado:
            return
        self._estado = clave
        self._anim_w.stop()
        self._w0 = list(self._w)
        self._w1 = list(self._PESOS_ESTADO[clave])
        if animado and self.isVisible():
            self._anim_w.start()
        else:
            self._w = list(self._w1)
            self.update()

    def _mover_w(self, t):
        t = float(t)
        self._w = [a + (b - a) * t for a, b in zip(self._w0, self._w1)]
        self.update()

    @staticmethod
    def _partes(d):
        con = min(d['conectadas'], d['vendidas'])
        des = min(d.get('desconectadas', 0), d['vendidas'] - con)
        return con, max(0, d['vendidas'] - con - des), des

    def _alto_valor(self, d):
        return sum(p * w for p, w in zip(self._partes(d), self._w))

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
        meta_op = min(self._w)
        tope = max(1, max(max(self._alto_valor(d), (d.get('meta') or 0) * meta_op) * p for d, p in zip(visibles, pesos)))
        return visibles, pesos, cantidad, arriba, area_h, ancho_col, tope

    def _columna_en(self, pos):
        """(índice entre los visibles, rectángulo de su barra) bajo `pos`, o (-1, None)."""
        if not self._datos:
            return -1, None
        visibles, pesos, cantidad, arriba, area_h, ancho_col, tope = self._geometria()
        i = int((pos.x() - (self.width() - cantidad * ancho_col)) // ancho_col)
        if not 0 <= i < cantidad or pesos[i] < 0.6 or self._alto_valor(visibles[i]) <= 0:
            return -1, None
        ancho_barra = ancho_col * 0.6
        x = self.width() - (cantidad - i) * ancho_col
        alto = area_h * self._alto_valor(visibles[i]) / tope
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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            i, _rect = self._columna_en(event.position())
            if i >= 0:
                periodo = self._geometria()[0][i].get('periodo')
                if periodo is not None:
                    self.mes_clicado.emit(periodo)
                    return
        super().mousePressEvent(event)

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
            con, otros, des = (p * w for p, w in zip(self._partes(d), self._w))
            valor = con + otros + des
            alto_total = area_h * valor / tope
            barra_x = x + (ancho_col - ancho_barra) / 2
            base = arriba + area_h
            if valor > 0:
                ruta = QPainterPath()
                ruta.addRoundedRect(QRectF(barra_x, base - alto_total, ancho_barra, alto_total), 5, 5)
                painter.save()
                painter.setClipPath(ruta)
                y = base
                for cantidad_seg, color in ((con, MARINO), (otros, TONO_CLARO), (des, ROJO)):
                    alto_seg = area_h * cantidad_seg / tope
                    if alto_seg > 0:
                        painter.fillRect(QRectF(barra_x, y - alto_seg, ancho_barra, alto_seg), _relleno(color))
                        y -= alto_seg
                painter.restore()
            painter.setFont(self._fuente(12, True))
            self._texto(painter, QRectF(x, base - alto_total - 20, ancho_col, 18), centro, _num(int(round(valor))), TINTA)
            meta = d.get('meta')
            meta_op = min(self._w)
            if meta and meta_op > 0.01:
                y_meta = base - area_h * meta / tope
                pluma = QPen(_relleno(MARINO), 2, Qt.PenStyle.DashLine)
                painter.setOpacity(peso * (1.0 - atenuar) * meta_op)
                painter.setPen(pluma)
                painter.drawLine(int(x + ancho_col * 0.08), int(y_meta), int(x + ancho_col * 0.92), int(y_meta))
                painter.setOpacity(peso * (1.0 - atenuar))
            pie = base + 4
            painter.setFont(self._fuente(11, True))
            self._texto(painter, QRectF(x, pie, ancho_col, 16), centro, d['etiqueta'], MARINO)
            painter.setFont(self._fuente(10))
            # Con columnas angostas (más meses a la vista) los subtítulos se acortan para no pisarse
            if self._estado == 'todos':
                texto_con = f"{_num(d['conectadas'])} conect."
            else:
                texto_con = f"de {_num(d['vendidas'])}"
            if QFontMetrics(painter.font()).horizontalAdvance(texto_con) > ancho_col - 6:
                texto_con = _num(d['conectadas'] if self._estado == 'todos' else d['vendidas'])
            self._texto(painter, QRectF(x, pie + 16, ancho_col, 14), centro, texto_con, APAGADO)
            if meta and self._estado == 'todos':
                cumple = d['vendidas'] / meta
                painter.setFont(self._fuente(10, True))
                texto_meta = f"{round(cumple * 100)}% de meta"
                if QFontMetrics(painter.font()).horizontalAdvance(texto_meta) > ancho_col - 6:
                    texto_meta = f"{round(cumple * 100)}%"
                self._texto(painter, QRectF(x, pie + 30, ancho_col, 14), centro, texto_meta,
                            MARINO if cumple >= 1 else ROJO_TEXTO)
        painter.setOpacity(1.0)
        painter.end()


class BarrasServicio(_GraficoBase):
    """Una barra lateral por tipo de servicio, del que mejor conecta al que
    peor; el color indica el plan."""
    ALTO_MIN = 34
    ALTO_CABECERA = 22

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
        self.setMinimumHeight(self.ALTO_CABECERA + max(1, len(datos)) * self.ALTO_MIN)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._datos:
            painter.end()
            return
        alto_fila = min((self.height() - self.ALTO_CABECERA) / len(self._datos), 48.0)
        x_barra = 134
        x_fin = self.width() - 70
        painter.setFont(self._fuente(10, True))
        self._texto(painter, QRectF(x_fin + 6, 0, 64, self.ALTO_CABECERA), Qt.AlignmentFlag.AlignRight, "UNIDADES", APAGADO)
        for i, d in enumerate(self._datos):
            y = self.ALTO_CABECERA + i * alto_fila
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
            painter.setFont(self._fuente(12, True))
            self._texto(painter, QRectF(x_fin + 6, y, 64, alto_fila), Qt.AlignmentFlag.AlignRight, _num(d['n']), TINTA)
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

    def _avance(self, i):
        """Avance de la entrada de la fila `i` (de 0 a 1); aquí siempre completa."""
        return 1.0

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
            avance = self._avance(i)
            painter.save()
            painter.setOpacity(avance)
            painter.translate(-(1.0 - avance) * 18, 0)
            y = self.ALTO_CABECERA + i * alto_fila
            self._nombre(painter, QRectF(0, y, ancho_nombre, alto_fila), d['nombre'])
            alto_barra = min(16.0, alto_fila - 8)
            pista = QRectF(x_barra, y + (alto_fila - alto_barra) / 2, x_fin - x_barra, alto_barra)
            self._barra(painter, pista, "#EDF0F6", alto_barra / 2)
            largo = max(4.0, pista.width() * d['tasa'] / maximo * avance)
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
            painter.restore()
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
