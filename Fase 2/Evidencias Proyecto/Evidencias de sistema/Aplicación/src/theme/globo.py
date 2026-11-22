"""Globo de ayuda de toda la app: borde redondeado, colores según el modo claro u oscuro y letra de la app.

Qt dibuja los QToolTip con esquinas cuadradas, así que se reemplaza `QToolTip.showText` por un globo propio
(ventana sin marco y translúcida). Los globos que ya pasaban por `showText` (el filtro de tema, los gráficos, las
notificaciones) lo usan sin cambiar nada."""
import math

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import (QAbstractTextDocumentLayout, QColor, QCursor, QFont, QGuiApplication, QPainter, QPen,
                         QTextBlockFormat, QTextCursor, QTextDocument)
from PyQt6.QtWidgets import QApplication, QToolTip, QWidget

_ANCHO_MAX = 340
_RELLENO_X, _RELLENO_Y = 14, 10
_SOMBRA = 8
_RADIO = 11
_COLORES = {
    False: {"fondo": "#FFFFFF", "borde": "#D5DDEB", "texto": "#1B2B4E", "sombra": (15, 27, 51)},
    True: {"fondo": "#1A2540", "borde": "#33415E", "texto": "#E5ECF6", "sombra": (0, 0, 0)},
}
_globo = {}


class _Globo(QWidget):
    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._doc = QTextDocument(self)
        self._origen = QPoint()
        self._por_distancia = False
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._vigia = QTimer(self)
        self._vigia.setInterval(120)
        self._vigia.timeout.connect(self._vigilar)
        self._limite = QTimer(self)
        self._limite.setSingleShot(True)
        self._limite.timeout.connect(self.ocultar)

    def _fuente(self):
        fuente = QFont(QApplication.font())
        fuente.setPixelSize(12)
        fuente.setWeight(QFont.Weight.Medium)
        return fuente

    def mostrar(self, pos, texto, ms=-1, por_distancia=False):
        self._por_distancia = por_distancia
        doc = self._doc
        doc.setDefaultFont(self._fuente())
        if Qt.mightBeRichText(texto):
            doc.setHtml(texto)
        else:
            doc.setPlainText(texto)
        formato = QTextBlockFormat()
        formato.setLineHeight(140, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.mergeBlockFormat(formato)
        doc.setTextWidth(-1)
        doc.setTextWidth(min(_ANCHO_MAX, math.ceil(doc.idealWidth()) + 2))
        tam = doc.size()
        ancho = math.ceil(tam.width()) + 2 * _RELLENO_X + 2 * _SOMBRA
        alto = math.ceil(tam.height()) + 2 * _RELLENO_Y + 2 * _SOMBRA
        self.resize(ancho, alto)

        pantalla = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        zona = pantalla.availableGeometry()
        x, y = pos.x() + 10 - _SOMBRA, pos.y() + 18 - _SOMBRA
        if x + ancho > zona.right():
            x = zona.right() - ancho
        if y + alto > zona.bottom():
            y = pos.y() - alto - 4 + _SOMBRA
        self.move(max(zona.left(), x), max(zona.top(), y))
        self._origen = QCursor.pos()
        self.update()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._anim.stop()
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        self._vigia.start()
        self._limite.start(ms if ms and ms > 0 else 14000)

    def ocultar(self):
        self._vigia.stop()
        self._limite.stop()
        self._anim.stop()
        self.hide()

    def _vigilar(self):
        if not self._por_distancia:
            return
        d = QCursor.pos() - self._origen
        if abs(d.x()) + abs(d.y()) > 40:
            self.ocultar()

    def paintEvent(self, event):
        from src.theme import tema
        c = _COLORES[tema.es_oscuro()]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        caja = QRectF(self.rect()).adjusted(_SOMBRA, _SOMBRA, -_SOMBRA, -_SOMBRA)
        r, g, b = c["sombra"]
        p.setPen(Qt.PenStyle.NoPen)
        for i, alfa in enumerate((10, 14, 18, 22)):
            extra = 4 - i
            p.setBrush(QColor(r, g, b, alfa))
            p.drawRoundedRect(caja.adjusted(-extra, -extra + 2, extra, extra + 2), _RADIO + extra, _RADIO + extra)
        p.setPen(QPen(QColor(c["borde"]), 1))
        p.setBrush(QColor(c["fondo"]))
        p.drawRoundedRect(caja.adjusted(0.5, 0.5, -0.5, -0.5), _RADIO, _RADIO)
        p.save()
        p.translate(QPointF(caja.left() + _RELLENO_X, caja.top() + _RELLENO_Y))
        contexto = QAbstractTextDocumentLayout.PaintContext()
        contexto.palette.setColor(contexto.palette.ColorRole.Text, QColor(c["texto"]))
        self._doc.documentLayout().draw(p, contexto)
        p.restore()
        p.end()


def _obtener():
    if "g" not in _globo:
        _globo["g"] = _Globo()
    return _globo["g"]


def mostrar_texto(pos, texto, widget=None, rect=None, msecs=-1, por_distancia=False):
    """Sustituye a QToolTip.showText. Con `por_distancia` (globos de widgets) se oculta al alejar el mouse; los que
    muestran los gráficos por su cuenta se ocultan solo cuando ellos lo piden o al salir del widget."""
    if not texto:
        ocultar_texto()
        return
    _obtener().mostrar(pos, texto, msecs, por_distancia)


def ocultar_texto():
    if "g" in _globo:
        _globo["g"].ocultar()


def visible():
    return "g" in _globo and _globo["g"].isVisible()


def instalar():
    if QToolTip.showText is not mostrar_texto:
        QToolTip.showText = staticmethod(mostrar_texto)
        QToolTip.hideText = staticmethod(ocultar_texto)
