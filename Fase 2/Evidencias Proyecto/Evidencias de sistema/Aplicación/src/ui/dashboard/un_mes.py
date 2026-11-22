"""Gráficos del Resumen cuando el filtro deja un solo mes: puente de camiones activos, avance de la meta,
planes y complementos y vendidos según su estado. Con varios meses el tablero usa los gráficos de siempre."""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy

from src.theme import tema
from src.ui.dashboard.base import APAGADO, LINEA, MARINO, ROJO, ROJO_TEXTO, TINTA, TONO_CLARO, _num, _pct, _relleno
from src.ui.dashboard.graficos import _GraficoBase

VERDE = "#0E8F5B"
PISTA = "#E6ECF5"
IZQ = Qt.AlignmentFlag.AlignLeft
DER = Qt.AlignmentFlag.AlignRight
CENTRO = Qt.AlignmentFlag.AlignHCenter


def _signo(n):
    return f"+{_num(n)}" if n > 0 else (f"−{_num(abs(n))}" if n < 0 else "0")


class _GraficoClicable(_GraficoBase):
    """Gráfico con zonas que se pueden presionar: cada una emite su clave en `zona_clicada`."""
    zona_clicada = pyqtSignal(str)
    MARGEN_SUPERIOR = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._zonas = []
        self._hover = None

    def _registrar(self, rect, clave, ayuda=""):
        self._zonas.append((rect, clave, ayuda))

    def _zona_completa(self, pos):
        pos = pos - QPointF(0, self.MARGEN_SUPERIOR)
        for rect, clave, ayuda in self._zonas:
            if rect.contains(pos):
                return clave, ayuda
        return None, ""

    def _zona_en(self, pos):
        return self._zona_completa(pos)[0]

    def mouseMoveEvent(self, event):
        clave, ayuda = self._zona_completa(event.position())
        if ayuda != self.toolTip():
            self.setToolTip(ayuda)
        if clave != self._hover:
            self._hover = clave
            self.setCursor(Qt.CursorShape.PointingHandCursor if clave else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        clave = self._zona_en(event.position())
        if event.button() == Qt.MouseButton.LeftButton and clave:
            self.zona_clicada.emit(clave)

    def _resaltar(self, painter, rect, clave, radio=6):
        if clave == self._hover:
            ruta = QPainterPath()
            ruta.addRoundedRect(rect.adjusted(-1, -1, 1, 1), radio, radio)
            painter.setPen(QPen(tema.fondo(TINTA), 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(ruta)

    def _pastilla(self, painter, x, y, texto, color_texto, color_fondo):
        painter.setFont(self._fuente(12, True))
        ancho = QFontMetrics(painter.font()).horizontalAdvance(texto) + 26
        rect = QRectF(x, y, ancho, 26)
        self._barra(painter, rect, color_fondo, 13)
        self._texto(painter, rect, CENTRO, texto, color_texto)
        return ancho

    def _cifra(self, painter, x, ancho, titulo, valor, color=TINTA, tamano=26):
        painter.setFont(self._fuente(10, True))
        self._texto(painter, QRectF(x, 2, ancho, 14), IZQ, titulo, APAGADO)
        painter.setFont(self._fuente(tamano, True))
        self._texto(painter, QRectF(x, 16, ancho, 34), IZQ, valor, color)

    def _linea_encabezado(self, painter, piezas, w, tamano=22, alto=30):
        """Línea centrada de cifras con su título: piezas = ('g', título, valor, color) o ('op', símbolo).
        Si no cabe en el ancho, baja el tamaño. Devuelve la zona de cada grupo, en el orden dado."""
        def medir(px):
            medidas = []
            for p in piezas:
                if p[0] == 'op':
                    medidas.append(QFontMetrics(self._fuente(px - 4, True)).horizontalAdvance(p[1]) + 20)
                else:
                    medidas.append(QFontMetrics(self._fuente(10, True)).horizontalAdvance(p[1]) + 8
                                   + QFontMetrics(self._fuente(px, True)).horizontalAdvance(p[2]) + 4)
            return medidas
        px = tamano
        medidas = medir(px)
        while sum(medidas) > w - 28 and px > 14:
            px -= 2
            medidas = medir(px)
        x = max(14.0, (w - sum(medidas)) / 2)
        centro_v = Qt.AlignmentFlag.AlignVCenter
        zonas = []
        for p, ancho in zip(piezas, medidas):
            if p[0] == 'op':
                painter.setFont(self._fuente(px - 4, True))
                self._texto(painter, QRectF(x, 0, ancho, alto), CENTRO | centro_v, p[1], APAGADO)
            else:
                painter.setFont(self._fuente(10, True))
                ancho_t = QFontMetrics(painter.font()).horizontalAdvance(p[1]) + 8
                self._texto(painter, QRectF(x, 0, ancho_t, alto), IZQ | centro_v, p[1], APAGADO)
                painter.setFont(self._fuente(px, True))
                self._texto(painter, QRectF(x + ancho_t, 0, ancho - ancho_t, alto), IZQ | centro_v, p[2], p[3])
                zonas.append(QRectF(x, 0, ancho, alto))
            x += ancho
        return zonas

    def paintEvent(self, event):
        self._zonas = []
        if not self._datos:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(0, self.MARGEN_SUPERIOR)
        self._pintar(painter, self._datos[0])
        painter.end()


class PuenteMes(_GraficoClicable):
    """Camiones activos de un mes: al inicio, los que entraron, los que salieron y el cierre."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    @staticmethod
    def _ayuda_inicio(d):
        mes = d.get('mes', "") or "el mes"
        return (f"Camiones conectados al comenzar {mes}: los del cierre menos los nuevos más las bajas. "
                "Sus renovaciones solo cambiaron de contrato y no se suman.")

    def _pintar_renovadas(self, painter, rc, renovadas, maximo, alto_max, mes):
        """Dentro de la barra Al inicio: franja clara (a escala) con las renovaciones del mes y su cifra debajo."""
        franja = QRectF(rc.left(), rc.top(), rc.width(), max(4.0, renovadas / maximo * alto_max))
        ruta = QPainterPath()
        ruta.addRoundedRect(rc, 5, 5)
        painter.save()
        painter.setClipPath(ruta)
        painter.fillRect(franja, _relleno(TONO_CLARO))
        painter.restore()
        painter.setFont(self._fuente(13, True))
        self._texto(painter, QRectF(rc.left(), franja.bottom() + 6, rc.width(), 18), CENTRO, _num(renovadas), "#FFFFFF")
        painter.setFont(self._fuente(10))
        self._texto(painter, QRectF(rc.left(), franja.bottom() + 22, rc.width(), 14), CENTRO, "renovadas", "#FFFFFF")
        self._registrar(franja.adjusted(0, 0, 0, 40), 'renovados',
                        f"{_num(renovadas)} camiones renovaron su contrato en {mes}. Ya estaban conectados, "
                        "por eso están dentro del inicio y no se suman otra vez.")

    def _pintar(self, painter, d):
        w, h = self.width(), self.height() - self.MARGEN_SUPERIOR
        mes = d.get('mes', "")
        # Con Año o Mes, Al inicio y Al cierre también abren sus camiones (son unidades del filtro)
        periodo = bool(d.get('periodo'))
        n_inicio, n_cierre, n_baja = "AL INICIO", "AL CIERRE", "BAJAS"
        # Una línea centrada que se lee como suma: «AL INICIO 5.071 + NUEVOS 193 − BAJAS 67 = AL CIERRE 5.197»
        zonas = self._linea_encabezado(painter, [
            ('g', n_inicio, _num(d['inicio']), TINTA), ('op', "+"),
            ('g', "NUEVOS", _num(d['nuevos']), VERDE), ('op', "−"),
            ('g', n_baja, _num(d['bajas']), ROJO_TEXTO if d['bajas'] else TINTA), ('op', "="),
            ('g', n_cierre, _num(d['cierre']), TINTA)], w)
        ayudas = (self._ayuda_inicio(d), "Camiones que entraron como nuevos en el mes.",
                  "Camiones que salieron del servicio en el mes.",
                  f"Camiones conectados al terminar {mes or 'el mes'}: al inicio + nuevos − bajas.")
        for zona, ayuda in zip(zonas, ayudas):
            self._registrar(zona, '', ayuda)

        izq, der, arriba, abajo = 14.0, w - 14.0, 42.0, h - 22.0
        ancho_col = (der - izq) / 4
        ancho_barra = min(ancho_col * 0.62, 90)
        maximo = max(1, d['inicio'], d['nuevos'], d['bajas'], d['cierre'])
        alto_max = max(20.0, abajo - arriba - 20)
        centros = [izq + ancho_col * (i + 0.5) for i in range(4)]

        def rect(i, valor):
            alto = max(4.0, valor / maximo * alto_max) if valor else 4.0
            return QRectF(centros[i] - ancho_barra / 2, abajo - alto, ancho_barra, alto)

        # Con Año o Mes, Renovados y Total también abren sus camiones (son unidades del filtro)
        barras = [(rect(0, d['inicio']), MARINO, _num(d['inicio']), "Al inicio", 'renovados' if periodo else None),
                  (rect(1, d['nuevos']), VERDE, _signo(d['nuevos']), "Nuevos", 'altas'),
                  (rect(2, d['bajas']), ROJO, _signo(-d['bajas']), "Bajas", 'bajas'),
                  (rect(3, d['cierre']), MARINO, _num(d['cierre']), "Al cierre", 'total' if periodo else None)]
        painter.setPen(QPen(tema.fondo("#C9D4E6"), 1))
        painter.drawLine(int(izq), int(abajo), int(der), int(abajo))
        for rc, color, valor, nombre, clave in barras:
            self._barra(painter, rc, color, 5)
            if nombre == "Al inicio" and d.get('renovadas'):
                self._pintar_renovadas(painter, rc, d['renovadas'], maximo, alto_max, mes)
            if clave:
                self._registrar(rc.adjusted(-6, -20, 6, 0), clave)
                self._resaltar(painter, rc, clave, 5)
            painter.setFont(self._fuente(13, True))
            self._texto(painter, QRectF(rc.left() - 10, rc.top() - 20, rc.width() + 20, 18), CENTRO, valor,
                        ROJO_TEXTO if color == ROJO else VERDE if color == VERDE else TINTA)
            painter.setFont(self._fuente(11))
            self._texto(painter, QRectF(rc.left() - 10, abajo + 3, rc.width() + 20, 16), CENTRO, nombre, APAGADO)


class MedidorMeta(_GraficoClicable):
    """Avance de la meta del mes: medidor de 0 a 150% con el porcentaje al centro y tres cifras debajo."""
    MAX_PCT = 1.5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(250)

    def _arco(self, painter, caja, f0, f1, color, grosor):
        if f1 <= f0:
            return
        ruta = QPainterPath()
        ruta.arcMoveTo(caja, 180 - 180 * f0)
        ruta.arcTo(caja, 180 - 180 * f0, -180 * (f1 - f0))
        lapiz = QPen(_relleno(color), grosor)
        lapiz.setCapStyle(Qt.PenCapStyle.FlatCap)
        painter.setPen(lapiz)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(ruta)

    def _tarjeta(self, painter, rect, etiqueta, valor, color, nota, compacta=False):
        ruta = QPainterPath()
        ruta.addRoundedRect(rect, 12, 12)
        painter.fillPath(ruta, tema.fondo("#F6F8FC"))
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(ruta)
        margen = 10 if compacta else 14
        x, ancho = rect.left() + margen, rect.width() - 2 * margen
        painter.setFont(self._fuente(9 if compacta else 10, True))
        self._texto(painter, QRectF(x, rect.top() + 8, ancho, 14), IZQ, etiqueta, APAGADO)
        painter.setFont(self._fuente(20 if compacta else 24, True))
        self._texto(painter, QRectF(x, rect.top() + 22, ancho, 32), IZQ, valor, color)
        painter.setFont(self._fuente(10 if compacta else 11))
        self._texto(painter, QRectF(x, rect.top() + 54, ancho, 14), IZQ, nota, APAGADO)

    def _pintar(self, painter, d):
        w, h = float(self.width()), float(self.height() - self.MARGEN_SUPERIOR)
        ventas, meta, mes = d['ventas'], d.get('meta'), d.get('mes', "")
        sufijo = " CIV" if d.get('civ') else ""   # con el filtro CIV la meta es la de unidades con CIV
        self._registrar(QRectF(0, 0, w, h), 'altas',
                        f"{_num(ventas)} ventas{' con CIV' if sufijo else ''} de {mes}" + (f" de una meta de {_num(meta)}" if meta else "")
                        + ". Presiona para ver sus flotas.")
        if not meta:
            y = max(10.0, (h - 102.0) / 2)
            painter.setFont(self._fuente(44, True))
            self._texto(painter, QRectF(0, y, w, 56), CENTRO, _num(ventas), TINTA)
            painter.setFont(self._fuente(13))
            self._texto(painter, QRectF(0, y + 58, w, 20), CENTRO, f"ventas{' con CIV' if sufijo else ''} de {mes}", APAGADO)
            self._texto(painter, QRectF(0, y + 82, w, 20), CENTRO, d.get('sin_meta') or "Sin meta definida para este mes", APAGADO)
            return
        pct = ventas / meta
        alto_cifras, hueco = 74.0, 14.0
        compacta = w < 400
        r_ext = max(60.0, min(w * (0.40 if compacta else 0.30), h - alto_cifras - hueco - 22.0 - 26.0))
        grosor = r_ext * 0.24
        r = r_ext - grosor / 2
        # Con la caja más alta que el dibujo, este se centra en vez de dejar el espacio vacío abajo
        desplazo = max(0.0, (h - (22.0 + r_ext + 24.0 + alto_cifras)) / 2)
        cx, cy = w / 2, desplazo + 22.0 + r_ext
        caja = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        f_meta = 1 / self.MAX_PCT
        f_valor = min(pct, self.MAX_PCT) / self.MAX_PCT
        self._arco(painter, caja, 0, 1, PISTA, grosor)
        self._arco(painter, caja, 0, min(f_valor, f_meta), MARINO, grosor)
        self._arco(painter, caja, f_meta, f_valor, VERDE, grosor)
        angulo = math.pi * (1 - f_meta)
        painter.setPen(QPen(tema.fondo(TINTA), 2.4))
        for borde in ((r - grosor / 2 - 3, r + grosor / 2 + 3),):
            painter.drawLine(QPointF(cx + borde[0] * math.cos(angulo), cy - borde[0] * math.sin(angulo)),
                             QPointF(cx + borde[1] * math.cos(angulo), cy - borde[1] * math.sin(angulo)))
        painter.setFont(self._fuente(12, True))
        self._texto(painter, QRectF(cx + (r_ext + 6) * math.cos(angulo) - 4, cy - (r_ext + 6) * math.sin(angulo) - 16, 50, 16), IZQ, "Meta", TINTA)
        painter.setFont(self._fuente(int(round(r_ext * 0.34)), True))
        self._texto(painter, QRectF(cx - r, cy - r_ext * 0.55, 2 * r, r_ext * 0.4), CENTRO, f"{round(pct * 100)}%", VERDE if pct >= 1 else ROJO_TEXTO)
        painter.setFont(self._fuente(12))
        self._texto(painter, QRectF(cx - r, cy - r_ext * 0.1, 2 * r, 18), CENTRO, f"de la meta{sufijo}" if compacta else f"de la meta{sufijo} de {mes}", APAGADO)
        painter.setFont(self._fuente(11))
        self._texto(painter, QRectF(cx - r - 25, cy + 4, 50, 14), CENTRO, "0", APAGADO)
        self._texto(painter, QRectF(cx + r - 25, cy + 4, 50, 14), CENTRO, "150%", APAGADO)
        # Tres cifras
        ancho_c = min(w - (20.0 if compacta else 28.0), 520.0)
        espacio = 6.0 if compacta else 10.0
        ancho_t = (ancho_c - 2 * espacio) / 3
        x0, y0 = (w - ancho_c) / 2, min(cy + 24.0, h - alto_cifras)
        if ventas >= meta:
            nota = (f"el día {d['dia']}" if compacta else f"cumplida el día {d['dia']}") if d.get('dia') else ("cumplida" if compacta else "meta cumplida")
            tercera = ("SOBRE META" if compacta else "SOBRE LA META", f"+{_num(ventas - meta)}", VERDE, nota)
        else:
            tercera = ("FALTAN", _num(meta - ventas), ROJO_TEXTO, "para la meta" if compacta else "para llegar a la meta")
        for i, (etq, valor, color, nota) in enumerate((("VENTAS" + sufijo, _num(ventas), TINTA, "acumuladas"),
                                                       ("META" + sufijo, _num(meta), TINTA, d.get('unidad', "del mes")), tercera)):
            self._tarjeta(painter, QRectF(x0 + i * (ancho_t + espacio), y0, ancho_t, alto_cifras), etq, valor, color, nota, compacta)


class AnilloEstado(_GraficoClicable):
    """Estado de los camiones hoy: anillo de conectadas y desconectadas con el porcentaje al centro y tres tarjetas debajo,
    con el mismo diseño del medidor de meta. Los datos traen n0 (conectadas), n1 (desconectadas), n2 (otros estados), total
    e `info`, una tupla por tarjeta (nombre, color, variación, color de la variación, ayuda)."""
    GRIS = "#A9B6CC"
    ALTO_TARJETA = 74.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self._geo_anillo = None

    def _zona_completa(self, pos):
        anillo = self._geo_anillo
        if anillo:
            cx, cy, r_in, r_out, tramos = anillo
            p = pos - QPointF(0, self.MARGEN_SUPERIOR)
            dx, dy = p.x() - cx, p.y() - cy
            if r_in <= math.hypot(dx, dy) <= r_out:
                angulo = math.degrees(math.atan2(dx, -dy)) % 360
                acumulado = 0.0
                for fraccion, clave, ayuda in tramos:
                    acumulado += fraccion * 360
                    if angulo < acumulado:
                        return clave, ayuda
        return super()._zona_completa(pos)

    def _tarjeta(self, painter, rect, clave, etiqueta, valor, nota, variacion, color_variacion, ayuda, compacta):
        ruta = QPainterPath()
        ruta.addRoundedRect(rect, 12, 12)
        painter.fillPath(ruta, tema.fondo("#F6F8FC"))
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(ruta)
        self._registrar(rect, clave, ayuda)
        self._resaltar(painter, rect, clave, 12)
        margen = 10 if compacta else 14
        x, ancho = rect.left() + margen, rect.width() - 2 * margen
        painter.setFont(self._fuente(9 if compacta else 10, True))
        self._texto(painter, QRectF(x, rect.top() + 8, ancho, 14), IZQ, etiqueta, APAGADO)
        painter.setFont(self._fuente(20 if compacta else 24, True))
        self._texto(painter, QRectF(x, rect.top() + 22, ancho, 32), IZQ, valor, TINTA)
        painter.setFont(self._fuente(10 if compacta else 11))
        y = rect.top() + 54
        if nota:
            self._texto(painter, QRectF(x, y, ancho, 14), IZQ, nota, APAGADO)
            x += QFontMetrics(painter.font()).horizontalAdvance(nota + "  ")
        if variacion:
            painter.setFont(self._fuente(10 if compacta else 11, True))
            libre = rect.right() - margen - x
            if QFontMetrics(painter.font()).horizontalAdvance(variacion + " este mes") <= libre:
                variacion += " este mes"   # solo si cabe en la tarjeta
            self._texto(painter, QRectF(x, y, max(10.0, libre), 14), IZQ, variacion, color_variacion)

    def _pintar(self, painter, d):
        w, h = float(self.width()), float(self.height() - self.MARGEN_SUPERIOR)
        compacta = w < 400
        total = d['total'] or 1
        cifras = [d['n0'], d['n1'], d['n2']]
        info = d['info']
        # Anillo
        alto_t = self.ALTO_TARJETA
        diametro = max(86.0, min(w * 0.44, h - alto_t - 14.0 - 20.0))
        grosor = diametro * 0.17
        cx, cy = w / 2, 10.0 + diametro / 2
        r = diametro / 2 - grosor / 2
        caja = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        tramos, inicio = [], 0.0
        for i, n in enumerate(cifras):
            if n <= 0:
                continue
            fraccion = n / total
            nombre, color, _v, _c, ayuda = info[i]
            tramos.append((fraccion, f"fila:{i}", f"{nombre}: {_num(n)} camiones ({_pct(fraccion)}). Presiona para ver sus flotas."))
            ruta = QPainterPath()
            ruta.arcMoveTo(caja, 90 - 360 * inicio)
            ruta.arcTo(caja, 90 - 360 * inicio, -360 * fraccion)
            lapiz = QPen(_relleno(color), grosor)
            lapiz.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(lapiz)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(ruta)
            inicio += fraccion
        self._geo_anillo = (cx, cy, r - grosor / 2, r + grosor / 2, tramos)
        painter.setFont(self._fuente(int(round(diametro * 0.155)), True))
        self._texto(painter, QRectF(cx - r, cy - diametro * 0.15, 2 * r, diametro * 0.2), CENTRO, _pct(d['n0'] / total), TINTA)
        painter.setFont(self._fuente(10))
        self._texto(painter, QRectF(cx - r, cy + diametro * 0.04, 2 * r, 14), CENTRO, "conectados", APAGADO)
        # Tarjetas
        ancho_c = min(w - (20.0 if compacta else 28.0), 520.0)
        espacio = 6.0 if compacta else 10.0
        ancho_t = (ancho_c - 2 * espacio) / 3
        x0, y0 = (w - ancho_c) / 2, min(cy + diametro / 2 + 14.0, h - alto_t)
        etiquetas = [("CONECTADAS", cifras[0]), ("DESCONECTADAS", cifras[1]),
                     (("OTROS" if cifras[2] > 0 else "TOTAL"), cifras[2] if cifras[2] > 0 else d['total'])]
        for i, (etiqueta, n) in enumerate(etiquetas):
            nombre, color, variacion, color_v, ayuda = info[i]
            nota = _pct(n / total) if (i < 2 or cifras[2] > 0) else "camiones"
            clave = f"fila:{i}" if (i < 2 or cifras[2] > 0) else "total"
            self._tarjeta(painter, QRectF(x0 + i * (ancho_t + espacio), y0, ancho_t, alto_t), clave,
                          etiqueta if not (compacta and etiqueta == "DESCONECTADAS") else "DESCONECT.", _num(n), nota,
                          variacion, color_v, ayuda or f"{nombre}: {_num(n)} camiones. Presiona para ver sus flotas.", compacta)


class PlanesMes(_GraficoClicable):
    """Planes y complementos de los camiones conectados: una tarjeta por plan y los totales de CIV y Safety Zone."""
    C_CIV, C_SZ, C_AMBOS, C_SIN = "#2F5BB0", "#14B8A6", "#0F1B33", "#C4CFE2"
    T_SZ = "#0B8F82"
    ALTO_FILA, ALTO_CAB, ALTO_TOTAL = 24.0, 38.0, 48.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(208)

    def set_datos(self, datos, animado=False):
        """La altura se ajusta a las filas que haya: con «Solo Safety Zone» las tarjetas de plan son más altas."""
        d = datos[0] if datos else None
        planes = [p for p in d['planes'] if p['n']] if d else []
        filas = 3 + (1 if any(p['sz'] - p['ambos'] > 0 for p in planes) else 0)
        self.setMinimumHeight(int(self.MARGEN_SUPERIOR + 8 + self.ALTO_CAB + self.ALTO_FILA * filas + 10 + 12 + self.ALTO_TOTAL + 10))
        super().set_datos(datos, animado)

    def _caja(self, painter, rect, fondo):
        ruta = QPainterPath()
        ruta.addRoundedRect(rect, 12, 12)
        painter.fillPath(ruta, tema.fondo(fondo))
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(ruta)

    def _punto(self, painter, x, y, color):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_relleno(color))
        painter.drawRoundedRect(QRectF(x, y, 10, 10), 3, 3)

    def _pintar(self, painter, d):
        w = float(self.width())
        orden = {'full': 0, 'medio': 1, 'basico': 2, '': 3}
        planes = sorted((p for p in d['planes'] if p['n']), key=lambda p: orden.get(p['clave'], 4))
        if not planes:
            painter.setFont(self._fuente(13))
            self._texto(painter, QRectF(0, 60, w, 24), CENTRO, "No hay camiones conectados con plan en este período", APAGADO)
            return
        con_solo_sz = any(p['sz'] - p['ambos'] > 0 for p in planes)
        grupos = [("Solo CIV", lambda p: p['civ'] - p['ambos'], self.C_CIV)]
        if con_solo_sz:
            grupos.append(("Solo Safety Zone", lambda p: p['sz'] - p['ambos'], self.C_SZ))
        grupos += [("CIV y Safety Zone", lambda p: p['ambos'], self.C_AMBOS),
                   ("Sin complemento", lambda p: p['n'] - p['civ'] - p['sz'] + p['ambos'], self.C_SIN)]
        izq, hueco = 14.0, 12.0
        n = len(planes)
        ancho_t = (w - 2 * izq - hueco * (n - 1)) / n
        alto_fila, alto_cab = self.ALTO_FILA, self.ALTO_CAB
        alto_t = alto_cab + alto_fila * len(grupos) + 10
        y0 = 8.0
        for i, p in enumerate(planes):
            x = izq + i * (ancho_t + hueco)
            rect = QRectF(x, y0, ancho_t, alto_t)
            self._caja(painter, rect, "#F6F8FC")
            self._registrar(rect, f"plan:{p['clave']}", f"{p['nombre']}: {_num(p['n'])} camiones conectados. Presiona para ver sus flotas.")
            painter.setFont(self._fuente(15, True))
            self._texto(painter, QRectF(x + 14, y0 + 6, ancho_t - 100, 28), IZQ, f"Plan {p['nombre']}" if p['clave'] else p['nombre'], TINTA)
            painter.setFont(self._fuente(24, True))
            self._texto(painter, QRectF(x + ancho_t - 100, y0 + 4, 86, 32), DER, _num(p['n']), TINTA)
            painter.setPen(QPen(tema.fondo(LINEA), 1))
            painter.drawLine(QPointF(x + 14, y0 + alto_cab), QPointF(x + ancho_t - 14, y0 + alto_cab))
            for j, (nombre, valor, color) in enumerate(grupos):
                y = y0 + alto_cab + 4 + j * alto_fila
                self._punto(painter, x + 14, y + alto_fila / 2 - 5, color)
                painter.setFont(self._fuente(13))
                self._texto(painter, QRectF(x + 32, y, ancho_t - 100, alto_fila), IZQ, nombre, TINTA)
                painter.setFont(self._fuente(15, True))
                self._texto(painter, QRectF(x + ancho_t - 100, y, 86, alto_fila), DER, _num(valor(p)), TINTA)
        # Totales de cada complemento
        y1 = y0 + alto_t + 12
        ancho_tot = (w - 2 * izq - hueco) / 2
        for i, (nombre, valor, color, texto, clave) in enumerate((("Total con CIV", d['civ'], self.C_CIV, self.C_CIV, 'civ'),
                                                                  ("Total con Safety Zone", d['sz'], self.C_SZ, self.T_SZ, 'sz'))):
            rect = QRectF(izq + i * (ancho_tot + hueco), y1, ancho_tot, self.ALTO_TOTAL)
            self._caja(painter, rect, "#FFFFFF")
            self._registrar(rect, clave, f"{nombre}: {_num(valor)} camiones. Presiona para ver sus flotas.")
            self._punto(painter, rect.left() + 14, rect.top() + self.ALTO_TOTAL / 2 - 5, color)
            painter.setFont(self._fuente(13, True))
            self._texto(painter, QRectF(rect.left() + 32, rect.top(), ancho_tot - 120, self.ALTO_TOTAL), IZQ, nombre, TINTA)
            painter.setFont(self._fuente(26, True))
            self._texto(painter, QRectF(rect.right() - 100, rect.top(), 86, self.ALTO_TOTAL), DER, _num(valor), texto)


class ApiladaMes(_GraficoClicable):
    """Unidades vendidas en el mes en una sola barra según cómo están hoy, y el avance de la meta."""
    # Conectadas ya reúne activando, sin flota y no entregadas; "Otros estados" solo se muestra si hay unidades
    ESTADOS = (('conectadas', "Conectadas", MARINO), ('por_conectar', "Otros estados", TONO_CLARO),
               ('desconectadas', "Desconectadas", ROJO))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(138)

    def _pintar(self, painter, d):
        w = self.width()
        vendidas = d['vendidas']
        # Cifras centradas con el mismo encabezado de los otros gráficos del mes
        self._linea_encabezado(painter, [
            ('g', "VENDIDOS", _num(vendidas), TINTA), ('op', "·"),
            ('g', "CONECTADOS HOY", _pct(d['conectadas'] / vendidas) if vendidas else "—", TINTA)], w)
        pista = QRectF(14, 40, w - 28, 28)
        self._barra(painter, pista, PISTA, 10)
        x = pista.left()
        estados = [e for e in self.ESTADOS if e[0] != 'por_conectar' or d['por_conectar']]
        total_hueco = 2.0 * max(0, sum(1 for c, _n, _k in estados if d[c]) - 1)
        for clave, _nombre, color in estados:
            n = d[clave]
            if not n or not vendidas:
                continue
            ancho = (pista.width() - total_hueco) * n / vendidas
            seg = QRectF(x, pista.top(), ancho, pista.height())
            self._barra(painter, seg, color, 10)
            self._registrar(seg, clave)
            self._resaltar(painter, seg, clave, 10)
            if ancho >= 26:
                painter.setFont(self._fuente(13, True))
                self._texto(painter, seg, CENTRO, _num(n), "#FFFFFF")
            x += ancho + 2
        # Leyenda centrada
        painter.setFont(self._fuente(12))
        metrica = QFontMetrics(painter.font())
        items = [(clave, f"{nombre} {_num(d[clave])}", color) for clave, nombre, color in estados]
        anchos = [metrica.horizontalAdvance(texto) + 16 for _c, texto, _k in items]
        total = sum(anchos) + 14 * (len(items) - 1)
        x = max(14.0, (w - total) / 2)
        for (clave, texto, color), ancho in zip(items, anchos):
            self._barra(painter, QRectF(x, 80, 10, 10), color, 3)
            self._texto(painter, QRectF(x + 16, 74, ancho, 22), IZQ, texto, APAGADO)
            self._registrar(QRectF(x, 74, ancho + 4, 22), clave)
            x += ancho + 14
        meta = d.get('meta')
        zona = QRectF(14, 98, w - 28, 26)
        if meta:
            # Avance de la meta en la misma paleta del tablero; lo que pasa de la meta se ve en el tono claro
            escala = max(vendidas, meta)
            ancho_total = w - 28
            painter.setFont(self._fuente(12, True))
            cumplida = vendidas >= meta
            self._texto(painter, QRectF(14, 96, w - 28, 16), CENTRO,
                        f"Meta {_num(meta)} · {_pct(vendidas / meta)}" + (" · cumplida" if cumplida else ""), TINTA)
            self._barra(painter, QRectF(14, 116, ancho_total, 8), PISTA, 4)
            hasta_meta = min(vendidas, meta)
            if hasta_meta:
                self._barra(painter, QRectF(14, 116, ancho_total * hasta_meta / escala, 8), MARINO, 4)
            if cumplida and vendidas > meta:
                x_meta = 14 + ancho_total * meta / escala
                self._barra(painter, QRectF(x_meta, 116, 14 + ancho_total - x_meta, 8), TONO_CLARO, 4)
                painter.setPen(QPen(tema.fondo(TINTA), 2))
                painter.drawLine(int(x_meta), 113, int(x_meta), 127)
        else:
            painter.setPen(QPen(tema.fondo("#C9D4E6"), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(zona, 8, 8)
            painter.setFont(self._fuente(11))
            self._texto(painter, zona.adjusted(10, 0, -10, 0), CENTRO, "La meta del mes se muestra solo sin filtros.", APAGADO)
