"""Listas del tablero Qué mejorar para contactar clientes: los clientes con camiones desconectados o sin
servicio y la cartera de cada ejecutivo. Cada fila se puede presionar."""
from PyQt6.QtCore import QEasingCurve, QPoint, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QApplication, QSizePolicy

from src.theme import tema
from src.ui.dashboard.base import (APAGADO, AZUL_SUAVE, LINEA, MARINO, ROJO, ROJO_SUAVE, ROJO_TEXTO, TINTA, TONO_CLARO, TONO_MEDIO,
                                   _num, _pct)
from src.ui.dashboard.graficos import BarrasFuga, _DetalleMes
from src.ui.dashboard.un_mes import _GraficoClicable

AMBAR = "#C77700"
AMBAR_SUAVE = "#FFF1D9"
PISTA = "#E6ECF5"
IZQ = Qt.AlignmentFlag.AlignLeft
DER = Qt.AlignmentFlag.AlignRight
CENTRO = Qt.AlignmentFlag.AlignHCenter
MARGEN = 14.0


class _TarjetaDetalle(_DetalleMes):
    """Tarjeta flotante con el detalle de una fila de un gráfico del tablero. Usa el fundido y el deslizamiento de la
    tarjeta de ventas por mes. `_detalle` trae: `subtitulo`, `filas` [(texto, valor, color)], `bloque` (título de la
    lista), `lineas` [(texto, texto a la derecha)] y `pie`."""
    ANCHO = 300
    MAX_LINEAS = 4

    def _tamano(self):
        d = self._detalle
        alto = 2 * self.MARGEN + 62 + 4 + 26 * len(d['filas']) + 10 + 18 + 12
        if d.get('bloque'):
            alto += 8 + 18 + max(1, len(d['lineas'])) * 20
        return self.ANCHO + 2 * self.MARGEN, alto

    def paintEvent(self, event):
        d = self._detalle
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
        x0 = caja.left() + self.PAD
        ancho = caja.width() - 2 * self.PAD
        izq = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        der = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        y = caja.top() + 14
        fuente.setBold(True)
        fuente.setPixelSize(15)
        painter.setFont(fuente)
        painter.setPen(tema.texto(TINTA))
        painter.drawText(QRectF(x0, y, ancho, 22), izq,
                         QFontMetrics(fuente).elidedText(self._titulo, Qt.TextElideMode.ElideRight, int(ancho)))
        fuente.setBold(False)
        fuente.setPixelSize(11)
        painter.setFont(fuente)
        painter.setPen(tema.texto(APAGADO))
        painter.drawText(QRectF(x0, y + 22, ancho, 18), izq,
                         QFontMetrics(fuente).elidedText(d['subtitulo'], Qt.TextElideMode.ElideRight, int(ancho)))
        y = caja.top() + 62
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.drawLine(int(x0), int(y), int(caja.right() - self.PAD), int(y))
        y += 4
        total = d.get('total') or sum(v for _t, v, _c in d['filas'])
        for i, (texto, valor, color) in enumerate(d['filas']):
            alfa = max(0.0, min(1.0, (self._rev - i * 0.08) / 0.55))
            painter.setOpacity(alfa)
            ry = y + i * 26 + (1.0 - alfa) * 8
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tema.fondo(color))
            painter.drawEllipse(QRectF(x0, ry + 9, 8, 8))
            fuente.setBold(False)
            fuente.setPixelSize(12)
            painter.setFont(fuente)
            painter.setPen(tema.texto(TINTA))
            painter.drawText(QRectF(x0 + 16, ry, 130, 26), izq, texto)
            fuente.setBold(True)
            painter.setFont(fuente)
            painter.setPen(tema.texto(color if valor else "#B5BFD0"))
            painter.drawText(QRectF(x0 + ancho - 120, ry, 60, 26), der, _num(valor))
            fuente.setBold(False)
            painter.setFont(fuente)
            painter.setPen(tema.texto(APAGADO))
            painter.drawText(QRectF(x0 + ancho - 56, ry, 56, 26), der, _pct(valor / total) if total else "")
        painter.setOpacity(max(0.0, min(1.0, (self._rev - 0.25) / 0.6)))
        y += 26 * len(d['filas']) + 8
        if d.get('bloque'):
            fuente.setBold(True)
            fuente.setPixelSize(10)
            painter.setFont(fuente)
            painter.setPen(tema.texto(APAGADO))
            painter.drawText(QRectF(x0, y, ancho, 18), izq, d['bloque'].upper())
            y += 18
            fuente.setBold(False)
            fuente.setPixelSize(12)
            painter.setFont(fuente)
            lineas = d['lineas'] or [("Ninguno", "")]
            for texto, derecha in lineas:
                painter.setPen(tema.texto(TINTA if d['lineas'] else APAGADO))
                ancho_der = QFontMetrics(fuente).horizontalAdvance(derecha) + 8 if derecha else 0
                painter.drawText(QRectF(x0, y, ancho - ancho_der, 20), izq,
                                 QFontMetrics(fuente).elidedText(texto, Qt.TextElideMode.ElideRight, int(ancho - ancho_der)))
                if derecha:
                    painter.setPen(tema.texto(APAGADO))
                    painter.drawText(QRectF(x0, y, ancho, 20), der, derecha)
                y += 20
        y += 10
        fuente.setPixelSize(11)
        painter.setFont(fuente)
        painter.setPen(tema.texto(APAGADO))
        painter.drawText(QRectF(x0, y, ancho, 18), izq, d['pie'])
        painter.end()


class _ConTarjeta:
    """Mezcla para los gráficos que muestran una `_TarjetaDetalle` al pasar el mouse por una fila."""

    def _iniciar_tarjeta(self):
        self._tarjeta = None
        self._clave_tarjeta = None

    def _mostrar_tarjeta(self, clave, titulo, detalle, centro_local):
        """`centro_local`: punto del gráfico (x del mouse, y del centro de la fila) junto al que sale la tarjeta."""
        if clave == self._clave_tarjeta:
            return
        self._clave_tarjeta = clave
        if self._tarjeta is None:
            self._tarjeta = _TarjetaDetalle()
        self._tarjeta._detalle = detalle
        ancho, alto = self._tarjeta._tamano()
        pantalla = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        centro = self.mapToGlobal(centro_local)
        a_la_derecha = centro.x() + 18 + ancho - _DetalleMes.MARGEN <= pantalla.right()
        x = centro.x() + 18 - _DetalleMes.MARGEN if a_la_derecha else centro.x() - 18 - ancho + _DetalleMes.MARGEN
        y = max(pantalla.top() + 8, min(centro.y() - alto // 2, pantalla.bottom() - alto - 8))
        self._tarjeta.mostrar(titulo, detalle, QPoint(x, y), desde_derecha=a_la_derecha)

    def _ocultar_tarjeta(self):
        self._clave_tarjeta = None
        if self._tarjeta is not None:
            self._tarjeta.ocultar()


class _Entrada:
    """Mezcla para los gráficos que, al cambiar sus datos, hacen entrar las filas una tras otra (con sus barras
    creciendo) para que se note el cambio."""

    def _iniciar_entrada(self):
        self._progreso = 1.0
        self._k_fila = 1.0
        self._anim_entrada = QVariantAnimation(self)
        self._anim_entrada.setStartValue(0.0)
        self._anim_entrada.setEndValue(1.0)
        self._anim_entrada.setDuration(420)
        self._anim_entrada.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_entrada.valueChanged.connect(self._mover_entrada)

    def _mover_entrada(self, valor):
        self._progreso = float(valor)
        self.update()

    def set_datos(self, datos, *args):
        cambio = bool(datos) and datos != self._datos
        super().set_datos(datos, *args)
        if cambio and self.isVisible():
            self._anim_entrada.stop()
            self._progreso = 0.0
            self._anim_entrada.start()

    def _avance(self, i):
        return max(0.0, min(1.0, (self._progreso - i * 0.09) / 0.55))

    def _abrir_fila(self, painter, i):
        self._k_fila = self._avance(i)
        painter.save()
        painter.setOpacity(self._k_fila)
        painter.translate(-(1.0 - self._k_fila) * 18, 0)

    def _cerrar_fila(self, painter):
        painter.restore()
        self._k_fila = 1.0


class _ListaContacto(_Entrada, _GraficoClicable):
    """Base de las dos listas: encabezado fijo y filas de alto fijo con su línea separadora."""
    ALTO_CABECERA = 22
    ALTO_FILA = 34
    MARGEN_SUPERIOR = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._iniciar_entrada()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_datos(self, datos):
        super().set_datos(datos)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _elidir(self, painter, texto, ancho):
        return QFontMetrics(painter.font()).elidedText(texto, Qt.TextElideMode.ElideRight, int(max(0, ancho)))

    def _encabezado(self, painter, columnas):
        painter.setFont(self._fuente(10, True))
        for x, ancho, texto, alineacion in columnas:
            self._texto(painter, QRectF(x, 0, ancho, self.ALTO_CABECERA), alineacion, texto.upper(), APAGADO)

    def _fila(self, painter, i, clave):
        """Rectángulo de la fila `i` con su línea superior y el resaltado al pasar el mouse."""
        y = self.ALTO_CABECERA + i * self.ALTO_FILA
        rect = QRectF(0, y, self.width(), self.ALTO_FILA)
        if clave == self._hover:
            fondo = QColor(tema.fondo(AZUL_SUAVE))
            fondo.setAlphaF(0.7)
            painter.fillRect(rect, fondo)
        painter.setPen(QPen(tema.fondo(LINEA), 1))
        painter.drawLine(int(MARGEN - 4), int(y), int(self.width() - MARGEN + 4), int(y))
        return rect

    def _segmentos(self, painter, rect, partes, alto=14.0):
        """Barra apilada de `partes` [(valor, color)] dentro de `rect`, con 2 px entre tramos."""
        pista = QRectF(rect.left(), rect.center().y() - alto / 2, rect.width(), alto)
        self._barra(painter, pista, PISTA, 5)
        con_valor = [(v, c) for v, c in partes if v > 0]
        total = sum(v for v, _c in con_valor)
        if not total:
            return
        libre = pista.width() - 2.0 * (len(con_valor) - 1)
        x = pista.left()
        for valor, color in con_valor:
            ancho = max(3.0, libre * valor / total * self._k_fila)
            self._barra(painter, QRectF(x, pista.top(), ancho, alto), color, 5)
            x += ancho + 2


class TablaClientes(_ConTarjeta, _ListaContacto):
    """Cliente, ejecutivos, sus camiones (conectados, desconectados y sin servicio) y qué hacer con él."""
    fila_clicada = pyqtSignal(int)
    ANCHO_ACCION = 74.0
    ANCHO_TOTAL = 84.0
    TEXTO_ACCION = {'rec': "Recuperar", 'ofr': "Ofrecer", 'amb': "Ambas"}

    TEXTO_DETALLE = {'rec': "Recuperar camiones desconectados", 'ofr': "Ofrecer el servicio",
                     'amb': "Recuperar y ofrecer el servicio"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._iniciar_tarjeta()

    def set_datos(self, datos):
        super().set_datos(datos)
        self._ocultar_tarjeta()

    def mousePressEvent(self, event):
        clave = self._zona_en(event.position())
        if event.button() == Qt.MouseButton.LeftButton and clave and clave.startswith("fila:"):
            self.fila_clicada.emit(int(clave[5:]))

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        clave = self._hover
        if not (clave and clave.startswith("fila:")) or int(clave[5:]) >= len(self._datos):
            self._ocultar_tarjeta()
            return
        indice = int(clave[5:])
        f = self._datos[indice]
        detalle = {'subtitulo': f"{_num(f['con'] + f['des'] + f['sin'])} camiones · {self.TEXTO_DETALLE[f['accion']]}",
                   'filas': (("Conectados", f['con'], MARINO), ("Desconectados", f['des'], ROJO), ("Sin servicio", f['sin'], AMBAR)),
                   'bloque': "Ejecutivos", 'lineas': [(n, "") for n in f['ejecutivos'][:_TarjetaDetalle.MAX_LINEAS]],
                   'pie': "Clic para ver sus camiones en General"}
        if len(f['ejecutivos']) > _TarjetaDetalle.MAX_LINEAS:
            detalle['lineas'].append((f"y {len(f['ejecutivos']) - _TarjetaDetalle.MAX_LINEAS} más", ""))
        self._mostrar_tarjeta(clave, f['nombre'], detalle,
                              QPoint(int(event.position().x()), int(self.ALTO_CABECERA + (indice + 0.5) * self.ALTO_FILA)))

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._ocultar_tarjeta()

    def hideEvent(self, event):
        self._ocultar_tarjeta()
        super().hideEvent(event)

    def wheelEvent(self, event):
        self._ocultar_tarjeta()
        event.ignore()

    def _columnas(self):
        ancho = self.width() - 2 * MARGEN - self.ANCHO_ACCION - self.ANCHO_TOTAL - 3 * 12
        x_nombre = MARGEN
        w_nombre, w_barra = ancho * 0.5, ancho * 0.5
        x_barra = x_nombre + w_nombre + 12
        x_total = x_barra + w_barra + 12
        x_accion = x_total + self.ANCHO_TOTAL + 12
        return (x_nombre, w_nombre), (x_barra, w_barra), (x_accion, self.ANCHO_ACCION), (x_total, self.ANCHO_TOTAL)

    def paintEvent(self, event):
        self._zonas = []
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        (xn, wn), (xb, wb), (xa, wa), (xt, wt) = self._columnas()
        self._encabezado(painter, ((xn, wn, "Cliente", IZQ), (xb, wb, "Sus camiones", IZQ),
                                   (xt, wt, "A contactar", DER), (xa, wa, "Acción", DER)))
        for i, f in enumerate(self._datos):
            clave = f"fila:{i}"
            self._abrir_fila(painter, i)
            rect = self._fila(painter, i, clave)
            alto = self.ALTO_FILA
            y = rect.top()
            painter.setFont(self._fuente(12, True))
            self._texto(painter, QRectF(xn, y, wn, alto), IZQ, self._elidir(painter, f['nombre'], wn), TINTA)
            self._segmentos(painter, QRectF(xb, y, wb, alto), ((f['con'], MARINO), (f['des'], ROJO), (f['sin'], AMBAR)))
            painter.setFont(self._fuente(13, True))
            self._texto(painter, QRectF(xt, y, wt, alto), DER, _num(f['des'] + f['sin']), TINTA)
            fondo, color = {'rec':(ROJO_SUAVE, ROJO_TEXTO), 'ofr': (AMBAR_SUAVE, AMBAR), 'amb': (AZUL_SUAVE, TINTA)}[f['accion']]
            painter.setFont(self._fuente(11, True))
            texto = self.TEXTO_ACCION[f['accion']]
            ancho_a = QFontMetrics(painter.font()).horizontalAdvance(texto) + 18
            chip = QRectF(xa + wa - ancho_a, y + (alto - 20) / 2, ancho_a, 20)
            self._barra(painter, chip, fondo, 10)
            self._texto(painter, chip, CENTRO, texto, color)
            self._cerrar_fila(painter)
            self._registrar(rect, clave)
        painter.end()


class BarrasEjecutivoContacto(_ConTarjeta, _ListaContacto):
    """Cartera de cada ejecutivo en una barra (conectados, por conectar, desconectados y sin servicio) y cuántos
    clientes tiene por contactar. Presionar uno filtra la lista de clientes."""
    ejecutivo_clicado = pyqtSignal(str)
    ANCHO_NUMERO = 86.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.seleccion = None
        self._iniciar_tarjeta()

    def set_datos(self, datos):
        super().set_datos(datos)
        self._ocultar_tarjeta()

    def mousePressEvent(self, event):
        clave = self._zona_en(event.position())
        if event.button() == Qt.MouseButton.LeftButton and clave and clave.startswith("ej:"):
            self.ejecutivo_clicado.emit(clave[3:])

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        clave = self._hover
        indice = next((i for i, f in enumerate(self._datos) if clave == f"ej:{f['ejecutivo']}"), -1)
        if indice < 0:
            self._ocultar_tarjeta()
            return
        f = self._datos[indice]
        clientes = f.get('clientes', [])
        lineas = [(nombre, TablaClientes.TEXTO_ACCION[accion]) for nombre, accion in clientes[:_TarjetaDetalle.MAX_LINEAS]]
        if f['k'] > len(lineas):
            lineas.append((f"y {f['k'] - len(lineas)} más", ""))
        total = f['conectadas'] + f['por_conectar'] + f['desconectadas'] + f['sin']
        detalle = {'subtitulo': f"{_num(total)} camiones · {_num(f['k'])} clientes por contactar",
                   'filas': (("Conectados", f['conectadas'], MARINO), ("Por conectar", f['por_conectar'], TONO_MEDIO),
                             ("Desconectados", f['desconectadas'], ROJO), ("Sin servicio", f['sin'], AMBAR)),
                   'bloque': "Clientes a contactar", 'lineas': lineas, 'pie': "Clic para ver solo sus clientes"}
        self._mostrar_tarjeta(clave, f['ejecutivo'], detalle,
                              QPoint(int(event.position().x()), int(self.ALTO_CABECERA + (indice + 0.5) * self.ALTO_FILA)))

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._ocultar_tarjeta()

    def hideEvent(self, event):
        self._ocultar_tarjeta()
        super().hideEvent(event)

    def wheelEvent(self, event):
        self._ocultar_tarjeta()
        event.ignore()

    def paintEvent(self, event):
        self._zonas = []
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        ancho = self.width() - 2 * MARGEN - self.ANCHO_NUMERO - 2 * 12
        w_nombre, w_barra = ancho / 3, ancho * 2 / 3
        x_barra = MARGEN + w_nombre + 12
        x_num = x_barra + w_barra + 12
        self._encabezado(painter, ((MARGEN, w_nombre, "Ejecutivo", IZQ), (x_barra, w_barra, "Unidades", IZQ),
                                   (x_num, self.ANCHO_NUMERO, "A contactar", DER)))
        for i, f in enumerate(self._datos):
            clave = f"ej:{f['ejecutivo']}"
            self._abrir_fila(painter, i)
            rect = self._fila(painter, i, clave)
            if self.seleccion == f['ejecutivo']:
                fondo = QColor(tema.fondo(AZUL_SUAVE))
                painter.fillRect(rect, fondo)
            y, alto = rect.top(), self.ALTO_FILA
            painter.setFont(self._fuente(12, True))
            self._texto(painter, QRectF(MARGEN, y, w_nombre, alto), IZQ, self._elidir(painter, f['ejecutivo'], w_nombre), TINTA)
            self._segmentos(painter, QRectF(x_barra, y, w_barra, alto),
                            ((f['conectadas'], MARINO), (f['por_conectar'], TONO_CLARO), (f['desconectadas'], ROJO), (f['sin'], AMBAR)))
            painter.setFont(self._fuente(13, True))
            self._texto(painter, QRectF(x_num, y, self.ANCHO_NUMERO, alto), DER, _num(f['k']), TINTA)
            self._cerrar_fila(painter)
            self._registrar(rect, clave)
        painter.end()


class FugaConDetalle(_ConTarjeta, _Entrada, BarrasFuga):
    """Dónde se pierden clientes, con una tarjeta por grupo: sus camiones por estado, los clientes que más pierden
    y cuánto se aleja del promedio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._iniciar_tarjeta()
        self._iniciar_entrada()

    def set_datos(self, datos, promedio=0.0):
        super().set_datos(datos, promedio)
        self._ocultar_tarjeta()

    def mouseMoveEvent(self, event):
        alto_fila = self._alto_fila()
        fila = int((event.position().y() - self.ALTO_CABECERA) // alto_fila) if self._datos else -1
        if not 0 <= fila < len(self._datos):
            self._ocultar_tarjeta()
            return
        d = self._datos[fila]
        otros = max(0, d['n'] - d['con'] - d['des'])
        dif = (d['tasa'] - self._promedio) * 100
        comparacion = (f"{abs(dif):.1f}".replace(".", ",") + (" pts sobre el promedio" if dif > 0 else " pts bajo el promedio"))
        detalle = {'subtitulo': f"{_num(d['des'])} de {_num(d['n'])} camiones desconectados ({_pct(d['tasa'])})",
                   'filas': (("Desconectados", d['des'], ROJO), ("Conectados", d['con'], MARINO), ("Otros estados", otros, TONO_CLARO)),
                   'total': d['n'], 'bloque': "Clientes que más pierden",
                   'lineas': [(nombre, f"{_num(n)} desc.") for nombre, n in d.get('clientes', [])],
                   'pie': f"{comparacion} ({_pct(self._promedio)})"}
        self._mostrar_tarjeta(fila, d['nombre'], detalle,
                              QPoint(int(event.position().x()), int(self.ALTO_CABECERA + (fila + 0.5) * alto_fila)))

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._ocultar_tarjeta()

    def hideEvent(self, event):
        self._ocultar_tarjeta()
        super().hideEvent(event)

    def wheelEvent(self, event):
        self._ocultar_tarjeta()
        event.ignore()
