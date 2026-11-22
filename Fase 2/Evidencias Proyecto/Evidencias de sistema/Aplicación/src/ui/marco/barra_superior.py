"""Barra superior de la ventana principal (rediseño 04-11-2026).

Piezas, todas dibujadas a mano con los colores del tema (se repintan con `tema_cambiado`, sin hojas de estilo):
- EstadoSincronizacion: pastilla de estado de los archivos vigilados, con transiciones entre estados.
- BotonIcono: botón de la cápsula (campana, correos, ajustes) con animaciones al pasar el mouse.
- CapsulaAcciones: contenedor que junta estado, campana, correos, tema y ajustes.
- BuscadorPildora: caja de búsqueda en forma de píldora con una guía que se despliega al enfocar.
- PildoraSeleccion: «filas seleccionadas» comprimido a un ícono con el número.
"""
import math
from datetime import datetime

import qtawesome as qta
from PyQt6.QtCore import Qt, QRectF, QPointF, QPoint, QSize, QTimer, QObject, QVariantAnimation, QEasingCurve, QEvent, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetricsF, QPainterPath, QLinearGradient
from PyQt6.QtWidgets import (QAbstractButton, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QWidget, QGraphicsOpacityEffect, QApplication)

from src.theme import tema

# ---------------------------------------------------------------- utilidades


def _mezcla(a, b, t):
    t = max(0.0, min(1.0, t))
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t), round(a.alpha() + (b.alpha() - a.alpha()) * t))


def _acotar(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _fondo(hexa):
    return tema.fondo(hexa)


def _texto(hexa):
    return tema.texto(hexa)


_PIXMAPS = {}


def _pixmap(nombre, color, tam):
    clave = (nombre, color.name(), tam)
    pm = _PIXMAPS.get(clave)
    if pm is None:
        pm = _PIXMAPS[clave] = qta.icon(nombre, color=color.name()).pixmap(QSize(tam, tam))
    return pm


class Progreso(QObject):
    """Valor entre 0 y 1 que se anima hacia un destino y avisa en cada cuadro."""

    def __init__(self, padre, duracion=200, curva=QEasingCurve.Type.OutCubic, inicial=0.0, al_cambiar=None):
        super().__init__(padre)
        self.valor = float(inicial)
        self._duracion = duracion
        self._al_cambiar = al_cambiar
        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(curva)
        self._anim.valueChanged.connect(self._cambio)

    def _cambio(self, v):
        self.valor = float(v)
        if self._al_cambiar:
            self._al_cambiar()

    def fijar(self, v):
        self._anim.stop()
        self.valor = float(v)
        if self._al_cambiar:
            self._al_cambiar()

    def ir_a(self, destino, duracion=None):
        self._anim.stop()
        ms = round(self._duracion * abs(destino - self.valor)) if duracion is None else duracion
        if ms <= 0:
            self.fijar(destino)
            return
        self._anim.setStartValue(self.valor)
        self._anim.setEndValue(float(destino))
        self._anim.setDuration(ms)
        self._anim.start()

    def reiniciar(self, duracion=None):
        self.fijar(0.0)
        self.ir_a(1.0, duracion or self._duracion)


def _fuente(base, px, negrita=False):
    f = QFont(base)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight.ExtraBold if negrita else QFont.Weight.Normal)
    return f


# ---------------------------------------------------------------- tarjeta flotante (guía y lista de archivos)


class TarjetaFlotante(QFrame):
    """Panel con sombra suave que aparece bajo un widget. Es hijo de la ventana (no una ventana aparte), así
    no le quita el foco al campo de búsqueda; no recibe el mouse."""

    MARGEN = 12

    def __init__(self, ventana):
        super().__init__(ventana)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._lay = QVBoxLayout(self)
        m = self.MARGEN
        self._lay.setContentsMargins(m + 14, m + 12, m + 14, m + 12)
        self._lay.setSpacing(7)
        self._fade = Progreso(self, 170)
        self._y = 0
        self.hide()

    def vaciar(self):
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def agregar(self, widget):
        self._lay.addWidget(widget)
        # En un panel ya visible los widgets nuevos nacen ocultos y el layout no los cuenta al medir
        widget.show()

    def mostrar_bajo(self, ancla, ancho, dx=0):
        """Coloca la tarjeta justo bajo `ancla`, alineada a su borde izquierdo."""
        ventana = self.parentWidget()
        self.setFixedWidth(ancho + 2 * self.MARGEN)
        self._lay.activate()
        self.resize(self.width(), self.sizeHint().height())
        p = ancla.mapTo(ventana, QPoint(0, ancla.height()))
        self.move(p.x() + dx - self.MARGEN, p.y() - self.MARGEN + 4)
        self.raise_()
        if not self.isVisible():
            self.show()
        self.update()

    def ocultar(self):
        if self.isVisible():
            self.hide()
            padre = self.parentWidget()
            if padre is not None:
                padre.update(self.geometry())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.MARGEN
        caja = QRectF(self.rect()).adjusted(m, m, -m, -m)
        for i in range(m, 0, -2):
            alfa = int(5 * (1 - i / m) + 1)
            sombra = QColor(0, 0, 0, alfa * (3 if tema.es_oscuro() else 1))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sombra)
            p.drawRoundedRect(caja.adjusted(-i, -i + 4, i, i + 4), 16 + i, 16 + i)
        p.setBrush(_fondo('#FFFFFF'))
        p.setPen(QPen(_fondo('#E5E7EB'), 1))
        p.drawRoundedRect(caja, 16, 16)
        p.end()


class _Linea(QWidget):
    """Fila de texto de las tarjetas flotantes: etiqueta, texto y detalle a la derecha, con colores del tema."""

    def __init__(self, etiqueta, texto, detalle="", marca=None, mono=False, parent=None):
        super().__init__(parent)
        self._e, self._t, self._d, self._marca, self._mono = etiqueta, texto, detalle, marca, mono
        self.setFixedHeight(22)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, x = self.height(), 0.0
        if self._marca is not None:
            ok = self._marca
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_fondo('#E7F6EF' if ok else '#FDECEC'))
            p.drawEllipse(QRectF(0, (h - 18) / 2, 18, 18))
            p.setPen(QPen(_texto('#0B7A55' if ok else '#B91C1C'), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            c = QPointF(9, h / 2)
            if ok:
                p.drawPolyline([c + QPointF(-3.2, 0.2), c + QPointF(-0.9, 2.6), c + QPointF(3.4, -2.4)])
            else:
                p.drawLine(c + QPointF(-2.8, -2.8), c + QPointF(2.8, 2.8))
                p.drawLine(c + QPointF(2.8, -2.8), c + QPointF(-2.8, 2.8))
            x = 28.0
        if self._e:
            fe = _fuente(self.font(), 10, True)
            p.setFont(fe)
            ancho_e = max(60.0, QFontMetricsF(fe).horizontalAdvance(self._e) + 14)
            caja = QRectF(0, (h - 18) / 2, ancho_e, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_fondo('#E6EFFD'))
            p.drawRoundedRect(caja, 6, 6)
            p.setPen(_texto('#1F6FEB'))
            p.drawText(caja, Qt.AlignmentFlag.AlignCenter, self._e)
            x = ancho_e + 10
        ft = QFont("Consolas") if self._mono else self.font()
        ft.setPixelSize(12)
        p.setFont(ft)
        p.setPen(_texto('#0F1B33'))
        p.drawText(QRectF(x, 0, self.width() - x, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._t)
        if self._d:
            p.setFont(_fuente(self.font(), 11))
            p.setPen(_texto('#66748D'))
            p.drawText(QRectF(0, 0, self.width(), h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._d)
        p.end()


class _Titulo(QLabel):
    def __init__(self, texto, parent=None):
        super().__init__(texto.upper(), parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("color: #66748D; font-size: 10px; font-weight: 800; letter-spacing: 1px; background: transparent;")


class _Pie(QLabel):
    def __init__(self, texto, parent=None):
        super().__init__(texto, parent)
        self.setWordWrap(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("color: #66748D; font-size: 11px; background: transparent; padding-top: 4px;")


# ---------------------------------------------------------------- botones de la cápsula


class BotonIcono(QAbstractButton):
    """Ícono que sube y se tiñe de azul al pasar el mouse. `giro`: grados que gira el ícono con el hover
    (engranaje); `rebote`: salta una vez (correos); `sonar()` hace sonar la campana; `fijar_contador(n)`
    muestra un número con rebote."""

    TAM = 36

    def __init__(self, icono, ayuda, giro=0.0, rebote=False, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.TAM, self.TAM)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(ayuda)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._icono, self._giro, self._rebote, self._n = icono, giro, rebote, 0
        self._hover = Progreso(self, 180, al_cambiar=self.update)
        self._sonar = Progreso(self, 850, QEasingCurve.Type.Linear, inicial=1.0, al_cambiar=self.update)
        self._pop = Progreso(self, 420, QEasingCurve.Type.OutBack, inicial=1.0, al_cambiar=self.update)
        tema.GestorTema.instancia().tema_cambiado.connect(self._tema_cambio)

    def _tema_cambio(self, *_):
        self.update()

    def sizeHint(self):
        return QSize(self.TAM, self.TAM)

    def enterEvent(self, event):
        self._hover.ir_a(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.ir_a(0.0)
        super().leaveEvent(event)

    def sonar(self):
        self._sonar.reiniciar()

    def fijar_icono(self, nombre):
        self._icono = nombre
        self.update()

    def fijar_contador(self, n, animar=True):
        if n > self._n and animar:
            self._pop.reiniciar()
        self._n = n
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        h = self._hover.valor
        p.translate(0, -2 * h)
        if h > 0.01:
            bg = QColor(_fondo('#E6EFFD'))
            bg.setAlphaF(h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(0.5, 0.5, self.TAM - 1, self.TAM - 1), 11, 11)
        color = _mezcla(_texto('#0F1B33'), _texto('#1F6FEB'), h)
        pm = _pixmap(self._icono, color, 16)
        angulo = self._giro * h
        escala = 1.0 + (0.12 * math.sin(h * math.pi) if self._rebote else 0.0)
        if self.isDown():
            escala *= 0.94
        s = self._sonar.valor
        pivote = QPointF(self.TAM / 2, self.TAM / 2 - (5 if s < 1 else 0))
        if s < 1:
            angulo += 16 * math.sin(s * math.pi * 5) * (1 - s)
        p.save()
        p.translate(pivote)
        p.rotate(angulo)
        p.scale(escala, escala)
        p.drawPixmap(QPointF(-8, -8 + (5 if s < 1 else 0)), pm)
        p.restore()
        if self._n > 0:
            self._badge(p)
        p.end()

    def _badge(self, p):
        texto = str(self._n) if self._n < 100 else "99+"
        f = _fuente(self.font(), 10, True)
        ancho = max(16.0, QFontMetricsF(f).horizontalAdvance(texto) + 10)
        escala = max(0.0, self._pop.valor)
        centro = QPointF(self.TAM - 2 - ancho / 2, 8.5)
        p.save()
        p.translate(centro)
        p.scale(escala, escala)
        caja = QRectF(-ancho / 2, -8, ancho, 16)
        p.setPen(QPen(_fondo('#F7F9FC'), 2))
        p.setBrush(QColor('#EF4444'))
        p.drawRoundedRect(caja, 8, 8)
        p.setPen(QColor('#FFFFFF'))
        p.setFont(f)
        p.drawText(caja, Qt.AlignmentFlag.AlignCenter, texto)
        p.restore()


class _Separador(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(7, 22)
        tema.GestorTema.instancia().tema_cambiado.connect(self._tema_cambio)

    def _tema_cambio(self, *_):
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(QRectF(3, 0, 1, 22), _fondo('#E3E8F0'))
        p.end()


# ---------------------------------------------------------------- estado de sincronización

_ESTADOS = {
    'al_dia': dict(bg='#F7F9FC', borde='#E3E8F0', color='#0F9D6E', suave='#66748D', icono='punto'),
    'detectando': dict(bg='#FFF6E5', borde='#F6DFAE', color='#B45309', suave='#B45309', icono='sync'),
    'actualizado': dict(bg='#E7F6EF', borde='#BFE6D4', color='#0B7A55', suave='#0B7A55', icono='check'),
}


class EstadoSincronizacion(QWidget):
    """Pastilla de estado. Al cambiar de estado se mezclan los colores, el ícono anterior sale y el nuevo entra
    (la paloma se dibuja trazo a trazo), el texto sube y el nuevo entra desde abajo, y la pastilla se ensancha
    o encoge sin saltos. Mientras detecta, gira el ícono y un brillo recorre la pastilla. Vuelve sola a «al día»
    a los SEGUNDOS_ACTUALIZADO segundos de actualizarse."""

    ALTO = 36
    SEGUNDOS_ACTUALIZADO = 12

    def __init__(self, archivos=(), parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.ALTO)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._archivos = tuple(archivos)
        self._revisiones = {}
        self._ultima = None
        self._de = None
        self._a = {'clave': 'al_dia', 'texto': 'Datos al día', 'hora': ''}
        self._ancho_de = self._ancho_a = 0.0
        self._t = Progreso(self, 520, QEasingCurve.Type.InOutCubic, inicial=1.0, al_cambiar=self._cuadro)
        self._fase = QVariantAnimation(self)
        self._fase.setStartValue(0.0)
        self._fase.setEndValue(1.0)
        self._fase.setDuration(1100)
        self._fase.setLoopCount(-1)
        self._fase.setEasingCurve(QEasingCurve.Type.Linear)
        self._fase.valueChanged.connect(lambda _v: self.update())
        self._pulso = QVariantAnimation(self)
        self._pulso.setStartValue(0.0)
        self._pulso.setEndValue(1.0)
        self._pulso.setDuration(2400)
        self._pulso.setLoopCount(3)
        self._pulso.valueChanged.connect(lambda _v: self.update())
        self._revertir = QTimer(self)
        self._revertir.setSingleShot(True)
        self._revertir.timeout.connect(self.al_dia)
        self._espera_popup = QTimer(self)
        self._espera_popup.setSingleShot(True)
        self._espera_popup.setInterval(260)
        self._espera_popup.timeout.connect(self._mostrar_popup)
        self._popup = None
        self._ancho_a = self._medir(self._a)
        self.setFixedWidth(round(self._ancho_a))
        self._ayuda = ""   # sin globo propio: lo que explicaría se muestra al pie de la lista de archivos
        tema.GestorTema.instancia().tema_cambiado.connect(self._tema_cambio)

    # ----- estado público
    def _vigilados(self):
        return "Se vigilan: " + (" · ".join(self._archivos) if self._archivos else "los archivos de datos")

    def _ir(self, clave, texto, hora, ayuda, duracion=520):
        self._de = dict(self._a)
        self._ancho_de = float(self.width())
        self._a = {'clave': clave, 'texto': texto, 'hora': hora}
        self._ancho_a = self._medir(self._a)
        self._ayuda = ayuda
        if clave == 'detectando':
            self._fase.start()
        self._t.fijar(0.0)
        self._t.ir_a(1.0, duracion)
        if clave == 'al_dia':
            QTimer.singleShot(duracion + 50, self._arrancar_pulso)
        else:
            self._pulso.stop()
        if clave != 'detectando':
            QTimer.singleShot(duracion + 50, lambda: self._fase.stop() if self._a['clave'] != 'detectando' else None)

    def _arrancar_pulso(self):
        if self._a['clave'] == 'al_dia' and self.isVisible():
            self._pulso.start()

    def al_dia(self):
        self._revertir.stop()
        hora = f"· {self._ultima.strftime('%H:%M')}" if self._ultima else ""
        self._ir('al_dia', 'Datos al día', hora, "Los datos están sincronizados.\n" + self._vigilados(), duracion=1100)

    def detectando(self, archivo):
        self._revertir.stop()
        self._ir('detectando', 'Detectando cambios…', '', f"Se detectó un cambio en {archivo}; comparando con lo que había.", duracion=420)

    def actualizado(self, archivo, resumen="", fecha=None):
        """En la pastilla solo «Actualizado» y la hora; el archivo y `resumen` («6 unidades», «sin diferencias»)
        quedan en el globo de ayuda."""
        self._ultima = fecha or datetime.now()
        self.revisado(archivo, self._ultima)
        tip = f"{archivo} se actualizó a las {self._ultima.strftime('%H:%M:%S')}." + (f"\nCambios: {resumen}." if resumen else "")
        self._ir('actualizado', 'Actualizado', self._ultima.strftime('%H:%M'), tip, duracion=560)
        self._revertir.start(self.SEGUNDOS_ACTUALIZADO * 1000)

    def revisado(self, archivo, fecha=None):
        """Anota cuándo se revisó un archivo (se ve al pasar el mouse sobre la pastilla)."""
        self._revisiones[archivo] = fecha or datetime.now()

    # ----- medidas y animación
    def _medir(self, estado):
        fb = _fuente(self.font(), 13, True)
        fr = _fuente(self.font(), 13)
        ancho = 10 + 18 + 8 + QFontMetricsF(fb).horizontalAdvance(estado['texto']) + 14
        if estado['hora']:
            ancho += 7 + QFontMetricsF(fr).horizontalAdvance(estado['hora'])
        return float(ancho)

    def sizeHint(self):
        return QSize(round(self._ancho_a), self.ALTO)

    def _cuadro(self):
        e = self._t.valor
        self.setFixedWidth(round(self._ancho_de + (self._ancho_a - self._ancho_de) * e) if self._ancho_de else round(self._ancho_a))
        self.update()

    def _tema_cambio(self, *_):
        self.update()

    # ----- ratón: lista de archivos vigilados
    def enterEvent(self, event):
        self._espera_popup.start()
        if self._a['clave'] == 'al_dia' and self._pulso.state() != QVariantAnimation.State.Running:
            self._pulso.setLoopCount(1)
            self._pulso.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._espera_popup.stop()
        if self._popup is not None:
            self._popup.ocultar()
        super().leaveEvent(event)

    def _mostrar_popup(self):
        ventana = self.window()
        if ventana is None or ventana is self:
            return
        if self._popup is None:
            self._popup = TarjetaFlotante(ventana)
        self._poblar_popup()
        self._popup.mostrar_bajo(self, 260)

    def _poblar_popup(self):
        self._popup.vaciar()
        self._popup.agregar(_Titulo("Archivos vigilados"))
        for archivo in self._archivos:
            r = self._revisiones.get(archivo)
            self._popup.agregar(_Linea("", archivo, f"revisado {r.strftime('%H:%M')}" if r else "sin revisar", marca=True))
        if self._a['clave'] != 'al_dia' and self._ayuda:
            self._popup.agregar(_Pie(self._ayuda))

    # ----- dibujo
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        e = self._t.valor
        a = self._a
        de = self._de or a
        cd, ca = _ESTADOS[de['clave']], _ESTADOS[a['clave']]
        mz = lambda k: _mezcla(_fondo(cd[k]) if k in ('bg', 'borde') else _texto(cd[k]),
                               _fondo(ca[k]) if k in ('bg', 'borde') else _texto(ca[k]), e)
        w, h = self.width(), self.height()
        caja = QRectF(0.5, 0.5, w - 1, h - 1)
        forma = QPainterPath()
        forma.addRoundedRect(caja, 12, 12)
        p.fillPath(forma, mz('bg'))
        # brillo que recorre la pastilla mientras detecta
        brillo = e if a['clave'] == 'detectando' else ((1 - e) if de['clave'] == 'detectando' else 0.0)
        if brillo > 0.01:
            p.save()
            p.setClipPath(forma)
            ancho_b = w * 0.6
            x = -ancho_b + (w + ancho_b * 2) * self._fase.currentValue() if self._fase.state() == QVariantAnimation.State.Running else -ancho_b
            g = QLinearGradient(x, 0, x + ancho_b, 0)
            c = QColor(_texto(ca['color']) if a['clave'] == 'detectando' else _texto(cd['color']))
            c0, c1 = QColor(c), QColor(c)
            c0.setAlpha(0)
            c1.setAlpha(int(60 * brillo))
            g.setColorAt(0, c0)
            g.setColorAt(0.5, c1)
            g.setColorAt(1, c0)
            p.fillRect(self.rect(), g)
            p.restore()
        p.setPen(QPen(mz('borde'), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(caja, 12, 12)

        color = mz('color')
        suave = mz('suave')
        # ícono: el anterior sale y el nuevo entra con rebote
        centro = QPointF(19, h / 2)
        if self._de is not None and e < 1.0:
            u = _acotar(e / 0.45)
            self._icono(p, cd['icono'], centro, color, 1.0 - 0.6 * u, 1.0 - u, 1.0)
        v = _acotar((e - 0.2) / 0.8) if self._de is not None else 1.0
        curva = QEasingCurve(QEasingCurve.Type.OutBack)
        self._icono(p, ca['icono'], centro, color, 0.35 + 0.65 * curva.valueForProgress(v), v, v)

        # texto: el anterior sube y se desvanece, el nuevo entra desde abajo
        fb, fr = _fuente(self.font(), 13, True), _fuente(self.font(), 13)
        x0 = 10 + 18 + 8
        if self._de is not None and e < 0.45:
            self._texto_estado(p, de, x0, -7 * _acotar(e / 0.4), 1.0 - _acotar(e / 0.4), fb, fr, color, suave)
        n = _acotar((e - 0.3) / 0.7) if self._de is not None else 1.0
        self._texto_estado(p, a, x0, 7 * (1 - n), n, fb, fr, color, suave)
        p.end()

    def _texto_estado(self, p, estado, x, dy, alfa, fb, fr, color, suave):
        if alfa <= 0.01:
            return
        h = self.height()
        p.save()
        p.setOpacity(alfa)
        p.setFont(fb)
        p.setPen(color)
        ancho_t = QFontMetricsF(fb).horizontalAdvance(estado['texto'])
        p.drawText(QRectF(x, dy, ancho_t + 4, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, estado['texto'])
        if estado['hora']:
            p.setFont(fr)
            p.setPen(suave)
            p.drawText(QRectF(x + ancho_t + 7, dy, 200, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, estado['hora'])
        p.restore()

    def _icono(self, p, tipo, centro, color, escala, alfa, dibujo):
        if alfa <= 0.01:
            return
        p.save()
        p.setOpacity(_acotar(alfa))
        p.translate(centro)
        p.scale(escala, escala)
        if tipo == 'punto':
            if self._pulso.state() == QVariantAnimation.State.Running:
                f = self._pulso.currentValue()
                halo = QColor(color)
                halo.setAlphaF(0.55 * (1 - f))
                p.setPen(QPen(halo, 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = 3 + 6 * f
                p.drawEllipse(QPointF(0, 0), r, r)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(0, 0), 4, 4)
        elif tipo == 'sync':
            giro = (self._fase.currentValue() if self._fase.state() == QVariantAnimation.State.Running else 0.0) * 360
            p.rotate(giro)
            p.setPen(QPen(color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            caja = QRectF(-6.5, -6.5, 13, 13)
            p.drawArc(caja, 30 * 16, 130 * 16)
            p.drawArc(caja, 210 * 16, 130 * 16)
            for ang in (160, 340):
                r = math.radians(ang)
                punta = QPointF(6.5 * math.cos(r), -6.5 * math.sin(r))
                tang = QPointF(math.sin(r), math.cos(r))
                n = QPointF(math.cos(r), -math.sin(r))
                p.drawLine(punta, punta + tang * 3.4 * -1 + n * 2.2)
                p.drawLine(punta, punta + tang * 3.4 * -1 - n * 2.2)
        elif tipo == 'check':
            p.setPen(QPen(color, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            barrido = _acotar(dibujo / 0.7)
            p.drawArc(QRectF(-7.5, -7.5, 15, 15), 90 * 16, -int(360 * barrido * 16))
            trazo = _acotar((dibujo - 0.55) / 0.45)
            if trazo > 0:
                a1, a2, a3 = QPointF(-3.2, 0.2), QPointF(-0.9, 2.7), QPointF(3.5, -2.4)
                if trazo < 0.4:
                    p.drawLine(a1, a1 + (a2 - a1) * (trazo / 0.4))
                else:
                    p.drawPolyline([a1, a2, a2 + (a3 - a2) * ((trazo - 0.4) / 0.6)])
        p.restore()


# ---------------------------------------------------------------- cápsula


class CapsulaAcciones(QFrame):
    """Contenedor redondeado que junta estado, campana, correos, tema y ajustes."""

    def __init__(self, widgets, parent=None):
        super().__init__(parent)
        self._hover = Progreso(self, 220, al_cambiar=self.update)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(4)
        for w in widgets:
            lay.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        tema.GestorTema.instancia().tema_cambiado.connect(self._tema_cambio)

    def _tema_cambio(self, *_):
        self.update()

    def enterEvent(self, event):
        self._hover.ir_a(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.ir_a(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._hover.valor
        caja = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_fondo('#F7F9FC'))
        p.drawRoundedRect(caja, 16, 16)
        borde = _mezcla(_fondo('#E3E8F0'), _mezcla(_fondo('#E3E8F0'), _texto('#1F6FEB'), 0.45), h)
        p.setPen(QPen(borde, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(caja, 16, 16)
        p.end()


# ---------------------------------------------------------------- filas seleccionadas


class PildoraSeleccion(QLabel):
    """«N seleccionados» comprimido a un ícono con el número; al pasar el mouse se despliega. Mantiene la
    interfaz de un QLabel (setText, show, hide) para que la ventana siga actualizándola igual."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._n = 0
        self._hover = Progreso(self, 220, al_cambiar=self._cuadro)
        tema.GestorTema.instancia().tema_cambiado.connect(self._tema_cambio)

    def setStyleSheet(self, hoja):
        pass  # se dibuja a mano con los colores del tema

    def setText(self, texto):
        digitos = "".join(c for c in str(texto) if c.isdigit())
        self._n = int(digitos) if digitos else 0
        self.setToolTip(f"{self._n} fila{'' if self._n == 1 else 's'} seleccionada{'' if self._n == 1 else 's'}")
        self._cuadro()

    def _tema_cambio(self, *_):
        self.update()

    def _anchos(self):
        f = _fuente(self.font(), 11, True)
        fm = QFontMetricsF(f)
        compacto = 8 + 13 + 5 + fm.horizontalAdvance(str(self._n)) + 9
        return compacto, compacto + 5 + fm.horizontalAdvance("seleccionados") + 2

    def _cuadro(self):
        c, t = self._anchos()
        self.setFixedWidth(round(c + (t - c) * self._hover.valor))
        self.update()

    def enterEvent(self, event):
        self._hover.ir_a(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.ir_a(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._hover.valor
        caja = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(_fondo('#003057'), 1))
        p.setBrush(_fondo('#003057'))
        p.drawRoundedRect(caja, 12, 12)
        blanco = QColor('#FFFFFF')
        p.setPen(QPen(blanco, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cy = self.height() / 2
        p.drawRoundedRect(QRectF(8, cy - 6, 12, 12), 3, 3)
        p.drawPolyline([QPointF(10.8, cy), QPointF(13.2, cy + 2.4), QPointF(17.2, cy - 2.6)])
        f = _fuente(self.font(), 11, True)
        p.setFont(f)
        p.setPen(blanco)
        fm = QFontMetricsF(f)
        x = 8 + 13 + 5
        p.drawText(QRectF(x, 0, fm.horizontalAdvance(str(self._n)) + 2, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, str(self._n))
        if h > 0.02:
            p.setOpacity(_acotar(h * 1.4 - 0.3))
            p.drawText(QRectF(x + fm.horizontalAdvance(str(self._n)) + 5, 0, 120, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "seleccionados")
        p.end()


class ChipFaltantes(QLabel):
    """«N sin resultado»: los VIN buscados que no están en el Registro Maestro. Un clic los copia (uno por línea)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._faltantes = []
        self._texto = ""
        self._reloj = QTimer(self)
        self._reloj.setSingleShot(True)
        self._reloj.setInterval(1600)
        self._reloj.timeout.connect(self._mostrar_cuenta)

    def poner(self, faltantes):
        self._faltantes = list(faltantes)
        self._reloj.stop()
        if not self._faltantes:
            self.hide()
            return
        self._mostrar_cuenta()
        self.show()

    def _mostrar_cuenta(self):
        n = len(self._faltantes)
        self.setText(f"{n} sin resultado")
        muestra = "\n".join(self._faltantes[:12]) + (f"\n… y {n - 12} más" if n > 12 else "")
        self.setToolTip(f"No están en el Registro Maestro. Clic para copiarlos:\n{muestra}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._faltantes:
            QApplication.clipboard().setText("\n".join(self._faltantes))
            self.setText("Copiados")
            self._reloj.start()
        super().mousePressEvent(event)


# ---------------------------------------------------------------- búsqueda en píldora


class _Burbuja(QWidget):
    """Lupa dentro de un círculo: se vuelve azul, se inclina y crece al enfocar la búsqueda."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.foco = 0.0

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        f = self.foco
        centro = QPointF(17, 17)
        p.translate(centro)
        p.rotate(-12 * f)
        esc = 1 + 0.08 * f
        p.scale(esc, esc)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_mezcla(_fondo('#E6EFFD'), _fondo('#1F6FEB'), f))
        p.drawEllipse(QPointF(0, 0), 16, 16)
        color = _mezcla(_texto('#1F6FEB'), QColor('#FFFFFF'), f)
        p.drawPixmap(QPointF(-8, -8), _pixmap('fa5s.search', color, 16))
        p.end()


class _BotonBorrar(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Borrar la búsqueda")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._hover = Progreso(self, 160, al_cambiar=self.update)

    def enterEvent(self, event):
        self._hover.ir_a(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.ir_a(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self._hover.valor
        if h > 0.01:
            bg = QColor(_fondo('#E6EFFD'))
            bg.setAlphaF(h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()), 8, 8)
        p.translate(13, 13)
        p.rotate(90 * h)
        p.setPen(QPen(_mezcla(_texto('#66748D'), _texto('#1F6FEB'), h), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(-4, -4), QPointF(4, 4))
        p.drawLine(QPointF(4, -4), QPointF(-4, 4))
        p.end()


class _Atajo(QWidget):
    """Etiqueta «Ctrl F» que se desvanece al enfocar o escribir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 22)
        self.opacidad = 1.0

    def paintEvent(self, event):
        if self.opacidad <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.opacidad)
        caja = QRectF(0.5, 0.5, self.width() - 1, self.height() - 2)
        p.setPen(QPen(_fondo('#E5E7EB'), 1))
        p.setBrush(_fondo('#FFFFFF'))
        p.drawRoundedRect(caja, 7, 7)
        p.setPen(QPen(_fondo('#E5E7EB'), 2))
        p.drawLine(QPointF(5, self.height() - 1), QPointF(self.width() - 5, self.height() - 1))
        p.setFont(_fuente(self.font(), 11, True))
        p.setPen(_texto('#66748D'))
        p.drawText(caja, Qt.AlignmentFlag.AlignCenter, "Ctrl F")
        p.end()


class BuscadorPildora(QFrame):
    """Búsqueda en forma de píldora. Envuelve el campo de texto y el contador de la ventana (`linea` y
    `cuenta`, que siguen siendo suyos) y agrega la burbuja de la lupa, el botón de borrar, el atajo y una
    guía que se despliega al enfocar: cómo buscar si está vacía, o cada término con una marca verde si se
    encontró y roja si no (`estados(lista)` devuelve la lista de bool; sin él, solo se listan)."""

    ALTO = 46
    MARGEN = 5            # espacio para el halo del foco
    MAX_TERMINOS_GUIA = 8

    def __init__(self, linea, cuenta, estados=None, parent=None):
        super().__init__(parent)
        self._linea, self._cuenta, self._estados = linea, cuenta, estados
        self._guia = None
        self._modo_flota = False
        self._placeholder_normal = linea.placeholderText()
        self.setFixedHeight(self.ALTO + 2 * self.MARGEN)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self._hover = Progreso(self, 200, al_cambiar=self.update)
        self._foco = Progreso(self, 260, al_cambiar=self._cuadro_foco)
        self._burbuja = _Burbuja()
        self._borrar = _BotonBorrar()
        self._atajo = _Atajo()
        linea.setFrame(False)
        linea.setStyleSheet("QLineEdit { background: transparent; border: none; color: #0F1B33; font-size: 14px; padding: 0; }")
        linea.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(self.MARGEN + 6, self.MARGEN, self.MARGEN + 10, self.MARGEN)
        lay.setSpacing(10)
        lay.addWidget(self._burbuja, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(linea, 1)
        lay.addWidget(cuenta, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._borrar, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._atajo, 0, Qt.AlignmentFlag.AlignVCenter)
        self._borrar.hide()
        self._borrar.clicked.connect(linea.clear)
        linea.installEventFilter(self)
        linea.textChanged.connect(self._texto_cambio)
        self._relojes = QTimer(self)
        self._relojes.setSingleShot(True)
        self._relojes.setInterval(90)
        self._relojes.timeout.connect(self._actualizar_guia)
        tema.GestorTema.instancia().tema_cambiado.connect(self._tema_cambio)

    # ----- eventos
    def eventFilter(self, obj, event):
        if obj is self._linea:
            tipo = event.type()
            if tipo == QEvent.Type.FocusIn:
                self._foco.ir_a(1.0)
                self._mostrar_guia()
                QApplication.instance().installEventFilter(self)
            elif tipo == QEvent.Type.FocusOut:
                self._foco.ir_a(0.0)
                QApplication.instance().removeEventFilter(self)
                if self._guia is not None:
                    self._guia.ocultar()
        elif event.type() == QEvent.Type.MouseButtonPress and self._linea.hasFocus():
            try:
                pos = self.mapFromGlobal(event.globalPosition().toPoint())
                if not self.rect().contains(pos):
                    self._linea.clearFocus()
            except AttributeError:
                pass
        return False

    def mousePressEvent(self, event):
        self._linea.setFocus()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self._hover.ir_a(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover.ir_a(0.0)
        super().leaveEvent(event)

    def _tema_cambio(self, *_):
        self._linea.setStyleSheet("QLineEdit { background: transparent; border: none; color: #0F1B33; font-size: 14px; padding: 0; }")
        self.update()

    def _cuadro_foco(self):
        f = self._foco.valor
        self._burbuja.foco = f
        self._burbuja.update()
        self._actualizar_atajo()
        self.update()

    def _actualizar_atajo(self):
        tiene = bool(self._linea.text())
        self._atajo.opacidad = 0.0 if (tiene or self._foco.valor > 0.05) else 1.0 - self._foco.valor * 4
        self._atajo.setVisible(self._atajo.opacidad > 0.01)
        self._atajo.update()

    def _texto_cambio(self, texto):
        self._borrar.setVisible(bool(texto))
        self._actualizar_atajo()
        if self._guia is not None and (self._guia.isVisible() or not texto.strip()):
            self._relojes.start()

    def fijar_modo_flota(self, activo):
        """En el Dashboard la barra busca flotas (no VIN, chasis ni RUT): cambia el texto de ayuda y la guía."""
        activo = bool(activo)
        if activo == self._modo_flota:
            return
        self._modo_flota = activo
        self._linea.setPlaceholderText(" Buscar flota VC..." if activo else self._placeholder_normal)
        if self._guia is not None and self._guia.isVisible():
            self._actualizar_guia()

    # ----- guía
    def _mostrar_guia(self):
        ventana = self.window()
        if ventana is None or ventana is self:
            return
        if self._guia is None:
            self._guia = TarjetaFlotante(ventana)
        self._actualizar_guia()

    def _actualizar_guia(self):
        if self._guia is None or not self._linea.hasFocus():
            return
        g = self._guia
        if self._linea.text().strip():
            g.ocultar()
            return
        g.vaciar()
        if self._modo_flota:
            g.agregar(_Titulo("Buscar flota"))
            g.agregar(_Linea("FLOTA", "Escribe parte del nombre y elige una de la lista"))
        else:
            g.agregar(_Titulo("Cómo buscar"))
            g.agregar(_Linea("VIN", "93KAB10X5TE000123, 93KAB20X1TE000124, 93KAB10X8SE000125, 93KAB20X4SE000126", mono=True))
            g.agregar(_Linea("CHASIS", "E000123, E000124, E000125, E000126", mono=True))
            g.agregar(_Linea("RUT", "Cliente, con o sin puntos ni guion"))
            g.agregar(_Pie("Pega una lista (una por línea o separada por comas) y se buscan todos a la vez."))
        g.mostrar_bajo(self, self.width() - 2 * self.MARGEN, dx=self.MARGEN)

    # ----- dibujo
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.MARGEN
        caja = QRectF(m, m, self.width() - 2 * m, self.ALTO)
        radio = self.ALTO / 2
        hv, fc = self._hover.valor, self._foco.valor
        azul = _fondo('#1F6FEB')
        # halo del foco
        if fc > 0.01:
            for i in range(m, 0, -1):
                c = QColor(azul)
                c.setAlphaF(0.075 * fc * (1 - (i - 1) / m))
                p.setPen(QPen(c, 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(caja.adjusted(-i + 0.5, -i + 0.5, i - 0.5, i - 0.5), radio + i, radio + i)
        relleno = _mezcla(_fondo('#F4F6FA'), _fondo('#FFFFFF'), fc)
        borde = _mezcla(_fondo('#E5E7EB'), _mezcla(_fondo('#E5E7EB'), azul, 0.4), hv)
        borde = _mezcla(borde, azul, fc)
        p.setPen(QPen(borde, 1))
        p.setBrush(relleno)
        p.drawRoundedRect(caja.adjusted(0.5, 0.5, -0.5, -0.5), radio, radio)
        p.end()
