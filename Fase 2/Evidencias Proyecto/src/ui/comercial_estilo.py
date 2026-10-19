"""Estilo visual de la pantalla Comercial (rediseño basado en
dashboard-v2.html). Solo apariencia: no contiene lógica de negocio."""
import html
import os
import sys

import qtawesome as qta
from PyQt6.QtCore import Qt, QSize, QRectF, QSettings, QEvent, QObject, QVariantAnimation, QEasingCurve, QTimer, pyqtSignal
from PyQt6.QtGui import (QIcon, QColor, QPainter, QPainterPath, QBrush, QFont, QFontMetrics, QFontDatabase,
                         QLinearGradient, QPen)
from PyQt6.QtWidgets import (QPushButton, QStyledItemDelegate, QStyle, QStyleOptionViewItem,
                             QApplication, QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QLabel, QButtonGroup, QWidget,
                             QGraphicsDropShadowEffect, QListWidget, QListWidgetItem, QAbstractItemView, QComboBox, QTabBar)

from src.theme import tema

FONDO = "#F3F5F9"
SUPERFICIE = "#FFFFFF"
SUPERFICIE_2 = "#F7F9FC"
TINTA = "#0F1B33"
APAGADO = "#66748D"
LINEA = "#E3E8F0"
LINEA_SUAVE = "#EDF0F6"
PRIMARIO = "#1F6FEB"
PRIMARIO_SUAVE = "#E8F0FE"
ENCABEZADO_1 = "#16315C"
ENCABEZADO_2 = "#0F2447"
ENCABEZADO_TEXTO = "#E9EFFA"
FILA_ALTERNA = "#F7FAFF"
FILA_HOVER = "#EAF2FF"
FILA_SELECCION = "#DBE9FF"
PIZARRA = "#52607A"
PIZARRA_SUAVE = "#E8ECF3"
VERDE = "#0F9D6E"
ROJO = "#E04848"
ROJO_SUAVE = "#FDE5E5"
AMBAR = "#D98404"
AZUL = "#1F6FEB"
VIOLETA = "#7C4DDE"

DURACION_HOVER_MS = 200
FAMILIA_FUENTE = "Inter"
ALFA_SOMBRA_PANEL = 45


def crear_sombra_panel(panel):
    """Sombra del panel flotante; parte invisible y aparece al deslizarlo."""
    sombra = QGraphicsDropShadowEffect(panel)
    sombra.setBlurRadius(28)
    sombra.setOffset(-4, 6)
    sombra.setColor(QColor(15, 27, 51, 0))
    panel.setGraphicsEffect(sombra)
    return sombra


def configurar_animacion_panel(animacion):
    """Misma duración y curva que el menú lateral de la ventana principal."""
    animacion.setDuration(250)
    animacion.setEasingCurve(QEasingCurve.Type.InOutQuart)


def fijar_sombra_panel(panel, visible):
    """Sombra del panel con intensidad fija: cambiarla en cada cuadro de la
    animación obliga a recalcular el desenfoque y se nota entrecortada."""
    sombra = panel.graphicsEffect()
    if not isinstance(sombra, QGraphicsDropShadowEffect):
        return
    alfa = ALFA_SOMBRA_PANEL if visible else 0
    color = sombra.color()
    if color.alpha() != alfa:
        color.setAlpha(alfa)
        sombra.setColor(color)


class _VigilaModulo(QObject):
    """Oculta el panel flotante cuando su pantalla deja de verse y lo devuelve
    al volver, ya que el panel cuelga de la ventana y no de la pantalla."""

    def __init__(self, modulo, panel, esta_abierto):
        super().__init__(modulo)
        self._panel = panel
        self._esta_abierto = esta_abierto

    def eventFilter(self, objeto, evento):
        tipo = evento.type()
        if tipo == QEvent.Type.Hide:
            self._panel.hide()
        elif tipo == QEvent.Type.Show and self._esta_abierto():
            self._panel.show()
            self._panel.raise_()
        return False


def capa_panel(modulo):
    """Contenedor de la ventana que incluye el encabezado de página; si la
    pantalla vive fuera de la ventana principal, la propia pantalla."""
    capa = getattr(modulo.window(), 'content_area', None)
    return capa if capa is not None and capa.isAncestorOf(modulo) else modulo


def montar_panel_sobre_encabezado(modulo, panel, esta_abierto):
    """Pasa el panel de la pantalla al contenedor de la ventana para que cubra
    también el título de página (la primera vez que se va a mostrar)."""
    capa = capa_panel(modulo)
    if panel.parentWidget() is not capa:
        panel.setParent(capa)
    if getattr(modulo, '_vigila_panel', None) is None:
        modulo._vigila_panel = _VigilaModulo(modulo, panel, esta_abierto)
        modulo.installEventFilter(modulo._vigila_panel)


def geometria_panel_flotante(modulo, abierto, derecha=None, abajo=None, ancho=None, margen=15):
    """Rectángulo del panel en coordenadas de su contenedor. `derecha`/`abajo`
    (en coordenadas de la pantalla) acotan el borde; por defecto, el de la pantalla."""
    from PyQt6.QtCore import QPoint, QRect
    capa = capa_panel(modulo)
    derecha = modulo.width() if derecha is None else derecha
    abajo = modulo.height() if abajo is None else abajo
    ancho = ancho if ancho is not None else max(320, min(400, int(modulo.width() * 0.3)))
    origen = modulo.mapTo(capa, QPoint(0, 0))
    encabezado = getattr(modulo.window(), 'page_head', None)
    if capa is not modulo and encabezado is not None and encabezado.isVisible():
        arriba = encabezado.mapTo(capa, QPoint(0, 0)).y() + 10
    else:
        arriba = origen.y() + 10
    x = origen.x() + derecha - margen - ancho if abierto else capa.width() + 30
    return QRect(x, arriba, ancho, max(0, origen.y() + abajo - margen - arriba))


def sombra_segun_posicion(panel, x_cerrado, x_abierto):
    """Intensidad de la sombra según cuánto del panel ya entró en pantalla."""
    sombra = panel.graphicsEffect()
    if not isinstance(sombra, QGraphicsDropShadowEffect) or x_cerrado == x_abierto:
        return
    avance = max(0.0, min(1.0, (x_cerrado - panel.x()) / (x_cerrado - x_abierto)))
    color = sombra.color()
    alfa = round(ALFA_SOMBRA_PANEL * avance)
    if color.alpha() != alfa:
        color.setAlpha(alfa)
        sombra.setColor(color)


def mezclar_con_blanco(color, proporcion):
    """Color con `proporcion` (0-1) de opacidad sobre fondo blanco, en hex."""
    c = QColor(color)
    r = round(255 + (c.red() - 255) * proporcion)
    g = round(255 + (c.green() - 255) * proporcion)
    b = round(255 + (c.blue() - 255) * proporcion)
    return QColor(r, g, b).name()


def interpolar(color_a, color_b, t):
    a, b = QColor(color_a), QColor(color_b)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


# ------------------------------------------------------------------ fuente

_fuente_cargada = None


QSS_FUENTE_MODULO = f"QWidget {{ font-family: '{FAMILIA_FUENTE}', 'Segoe UI', sans-serif; }}"

QSS_SCROLL_PANEL = f"""
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ border: none; background: transparent; width: 6px; margin: 4px 0px; }}
    QScrollBar::handle:vertical {{ background: #CBD5E1; min-height: 30px; border-radius: 3px; }}
    QScrollBar::handle:vertical:hover {{ background: {APAGADO}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""


def fuente_comercial(base):
    """Fuente Inter (src/assets/fonts/Inter, licencia OFL) con el tamaño de
    `base`. Si no se pudo registrar, devuelve `base` sin cambios."""
    global _fuente_cargada
    if _fuente_cargada is None:
        raiz = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        carpeta = os.path.join(raiz, 'src', 'assets', 'fonts', 'Inter')
        ok = False
        if os.path.isdir(carpeta):
            for nombre in sorted(os.listdir(carpeta)):
                if nombre.lower().endswith('.ttf'):
                    ok = QFontDatabase.addApplicationFont(os.path.join(carpeta, nombre)) >= 0 or ok
        _fuente_cargada = ok
    fuente = QFont(base)
    if _fuente_cargada:
        fuente.setFamily(FAMILIA_FUENTE)
    return fuente


# ------------------------------------------------------- animación de hover

class AnimacionHover(QObject):
    """Progreso 0→1 al entrar el mouse y 1→0 al salir, con la misma
    duración/curva que las transiciones del HTML (~200 ms). Llama a
    `on_progreso(valor)` en cada cuadro."""

    def __init__(self, widget, on_progreso):
        super().__init__(widget)
        self._widget = widget
        self._on_progreso = on_progreso
        self.progreso = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(DURACION_HOVER_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._cambio)
        widget.installEventFilter(self)

    def _cambio(self, valor):
        self.progreso = float(valor)
        self._on_progreso(self.progreso)

    def _ir_a(self, destino):
        self._anim.stop()
        self._anim.setStartValue(self.progreso)
        self._anim.setEndValue(destino)
        self._anim.setDuration(max(1, round(DURACION_HOVER_MS * abs(destino - self.progreso))))
        self._anim.start()

    def eventFilter(self, obj, event):
        if obj is self._widget:
            tipo = event.type()
            if tipo == QEvent.Type.Enter and self._widget.isEnabled():
                self._ir_a(1.0)
            elif tipo in (QEvent.Type.Leave, QEvent.Type.EnabledChange, QEvent.Type.Hide):
                if tipo != QEvent.Type.EnabledChange or not self._widget.isEnabled():
                    self._ir_a(0.0)
        return False


class _Levantamiento:
    """Desplaza el widget unos píxeles según el progreso del hover (como el
    `transform` del HTML). Si el layout lo reubica mientras está desplazado,
    toma esa posición como nueva base y vuelve a aplicar el desplazamiento."""

    def _iniciar_levantamiento(self, dx, dy):
        self._lev_dx, self._lev_dy = dx, dy
        self._lev_base = None
        self._lev_moviendo = False
        self._lev_progreso = 0.0

    def _aplicar_levantamiento(self, progreso):
        self._lev_progreso = progreso
        if self._lev_base is None:
            self._lev_base = self.pos()
        self._lev_moviendo = True
        self.move(self._lev_base.x() + round(self._lev_dx * progreso),
                  self._lev_base.y() + round(self._lev_dy * progreso))
        self._lev_moviendo = False

    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._lev_moviendo:
            self._lev_base = self.pos()
            if self._lev_progreso:
                self._aplicar_levantamiento(self._lev_progreso)


# ---------------------------------------------------------------- tarjetas

def qss_tarjeta(nombre_objeto):
    return f"QFrame#{nombre_objeto} {{ background-color: {SUPERFICIE}; border: 1px solid {LINEA}; border-radius: 14px; }}"


QSS_BARRA_BANDEJA = f"QFrame#barraBandejaComercial {{ background: transparent; border: none; border-bottom: 1px solid {LINEA}; }}"

QSS_TITULO_SECCION = (
    f"color: {APAGADO}; font-size: 11px; font-weight: bold; letter-spacing: 1px; "
    "background: transparent; border: none;"
)

QSS_BOTON_BI = (
    "QPushButton { background-color: #FBBF24; color: #3B2A00; border-radius: 17px; "
    "font-weight: 800; font-size: 11px; border: none; }"
)


# ------------------------------------------------------- botones de la barra

_BASE_BOTON_BARRA = "border-radius: 10px; padding: 0px 10px; min-height: 34px; font-weight: 600; font-size: 12px;"


def qss_boton_barra(variante='neutro'):
    if variante == 'capsula':
        return (
            f"QPushButton {{ {_BASE_BOTON_BARRA} color: white; background: transparent; border: none; }}"
            "QPushButton:hover { background: rgba(255,255,255,0.16); }"
            "QPushButton:disabled { color: rgba(255,255,255,0.4); }"
        )
    if variante == 'alerta':
        return f"QPushButton {{ {_BASE_BOTON_BARRA} color: {ROJO}; background-color: {ROJO_SUAVE}; border: 1px solid {ROJO}; font-weight: bold; }}"
    if variante == 'naranja':
        return (
            f"QPushButton {{ {_BASE_BOTON_BARRA} color: {AMBAR}; background: transparent; border: none; }}"
            "QPushButton:hover { background: rgba(255,255,255,0.16); }"
        )
    if variante == 'activo':
        return f"QPushButton {{ {_BASE_BOTON_BARRA} color: {PRIMARIO}; background-color: {PRIMARIO_SUAVE}; border: 1px solid {PRIMARIO}; font-weight: bold; }}"
    color_texto = '#1B2B4E' if variante == 'excel' else TINTA
    # Fondo y borde los pinta AnimadorBotonBarra (animados); el QSS solo deja el texto
    return (
        f"QPushButton {{ {_BASE_BOTON_BARRA} color: {color_texto}; background: transparent; border: 1px solid transparent; }}"
        f"QPushButton:disabled {{ color: {APAGADO}; }}"
    )


class AnimadorBotonBarra(AnimacionHover):
    """Fondo/borde animados para los botones de la barra de la bandeja
    (creados en la vista antigua, por eso se usa un filtro de eventos y no
    una subclase). En 'alerta'/'activo' el fondo lo pone el QSS y no se pinta."""

    def __init__(self, boton):
        super().__init__(boton, lambda _v: boton.update())
        boton._icono_original = boton.icon()

        def set_icon(icono):
            boton._icono_original = icono
            self._aplicar_icono()
        boton.setIcon = set_icon
        tema.GestorTema.instancia().tema_cambiado.connect(self._aplicar_icono)

    def _aplicar_icono(self, *_):
        """El botón 'excel' es blanco en claro y translúcido en oscuro: su icono
        azul marino pasa a blanco."""
        boton = self._widget
        original = getattr(boton, '_icono_original', None)
        variante = boton.property('variante_barra')
        if original is None or original.isNull() or variante == 'capsula':
            return
        QPushButton.setIcon(boton, _icono_blanco(original) if variante == 'excel' and tema.es_oscuro() else original)

    def eventFilter(self, obj, event):
        if obj is self._widget and event.type() == QEvent.Type.Paint:
            variante = self._widget.property('variante_barra') or 'neutro'
            if variante in ('neutro', 'excel'):
                self._pintar_fondo(variante)
        return super().eventFilter(obj, event)

    def _pintar_fondo(self, variante):
        boton = self._widget
        p = self.progreso if boton.isEnabled() else 0.0
        painter = QPainter(boton)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(boton.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if variante == 'excel':
            grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            if tema.es_oscuro():
                relleno = interpolar(QColor(255, 255, 255, 26), QColor(255, 255, 255, 56), p)
            else:
                relleno = interpolar("#FFFFFF", "#E6EBF5", p)
            grad.setColorAt(0.0, relleno)
            grad.setColorAt(1.0, relleno)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
        else:
            painter.setPen(QPen(interpolar(tema.fondo(LINEA), PRIMARIO, p), 1))
            painter.setBrush(interpolar(tema.fondo(SUPERFICIE_2), tema.fondo(PRIMARIO_SUAVE), p))
        painter.drawRoundedRect(rect, 10, 10)
        painter.end()


def aplicar_estilo_boton_barra(boton, variante='neutro'):
    # Los botones dentro de la cápsula oscura usan icono blanco en su estado normal
    if boton.property('en_capsula') and variante == 'neutro':
        variante = 'capsula'
    boton.setProperty('variante_barra', variante)
    if getattr(boton, '_animador_barra', None) is None:
        boton._animador_barra = AnimadorBotonBarra(boton)
    boton.setStyleSheet(qss_boton_barra(variante))
    boton._animador_barra._aplicar_icono()
    if boton.property('en_capsula'):
        original = getattr(boton, '_icono_original', None)
        if original is not None:
            QPushButton.setIcon(boton, _icono_blanco(original) if variante == 'capsula' else original)
    boton.update()


def _icono_blanco(icono, tam=QSize(16, 16)):
    pix = icono.pixmap(tam)
    p = QPainter(pix)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(pix.rect(), QColor('white'))
    p.end()
    return QIcon(pix)


def preparar_boton_capsula(boton):
    """Deja el botón en el estilo de la cápsula oscura de la barra. Todo
    setIcon posterior (estados de alerta, recarga, etc.) se respeta y solo
    se tiñe de blanco mientras el botón está en su variante normal."""
    boton.setProperty('en_capsula', True)
    boton._icono_original = boton.icon()

    def set_icon(icono):
        boton._icono_original = icono
        blanco = boton.property('variante_barra') == 'capsula'
        QPushButton.setIcon(boton, _icono_blanco(icono) if blanco else icono)
    boton.setIcon = set_icon
    aplicar_estilo_boton_barra(boton, 'neutro')


# ------------------------------------------------------ pestañas y tarjetas KPI

QSS_SUBPESTANAS = f"""
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
        background: transparent; color: {APAGADO}; padding: 10px 16px; margin-right: 2px;
        border: none; border-bottom: 3px solid transparent; font-weight: 600; font-size: 13px;
    }}
    QTabBar::tab:hover:!selected {{ color: {TINTA}; }}
    QTabBar::tab:selected {{ color: {PRIMARIO}; border-bottom: 3px solid {PRIMARIO}; }}
"""

QSS_CONTENEDOR_SUBPESTANAS = f"QFrame#contenedorSubpestanasComercial {{ background: transparent; border: none; border-bottom: 1px solid {LINEA}; }}"


class SelectorSegmentado(QFrame):
    """Control segmentado (fondo gris con la opción activa en blanco) que
    maneja un QTabWidget cuya barra propia queda oculta."""

    def __init__(self, tabs, parent=None):
        super().__init__(parent)
        self._tabs = tabs
        self.setObjectName("selectorSegmentadoComercial")
        self.setStyleSheet(f"""
            QFrame#selectorSegmentadoComercial {{ background-color: {PIZARRA_SUAVE}; border-radius: 12px; border: none; }}
            QPushButton {{ background: transparent; color: {APAGADO}; border: none; border-radius: 9px;
                           padding: 7px 18px; font-weight: 600; font-size: 13px; }}
            QPushButton:hover:!checked {{ color: {TINTA}; }}
            QPushButton:checked {{ background-color: {SUPERFICIE}; color: {PRIMARIO}; }}
            QPushButton:disabled {{ color: #A9B4C6; }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        for i in range(tabs.count()):
            btn = QPushButton(tabs.tabText(i))
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._grupo.addButton(btn, i)
            layout.addWidget(btn)
        self._grupo.idClicked.connect(tabs.setCurrentIndex)
        tabs.currentChanged.connect(self._sincronizar)
        self._sincronizar(tabs.currentIndex())

    def _sincronizar(self, indice):
        btn = self._grupo.button(indice)
        if btn is not None:
            btn.setChecked(True)

    def sincronizar_estado(self):
        """Copia habilitado/tooltip de cada pestaña a su botón (la barra
        propia del QTabWidget está oculta)."""
        for i in range(self._tabs.count()):
            btn = self._grupo.button(i)
            if btn is not None:
                btn.setEnabled(self._tabs.isTabEnabled(i))
                btn.setToolTip(self._tabs.tabToolTip(i))


class SelectorSubpestanas(QFrame):
    """Pestañas con línea inferior (las sub-pestañas de Comercial) que
    manejan un QTabWidget cuya barra propia queda oculta. Misma interfaz que
    SelectorSegmentado, más `tabBarClicked` para las transiciones."""

    def __init__(self, tabs, parent=None):
        super().__init__(parent)
        self._tabs = tabs
        self.setObjectName("contenedorSubpestanasComercial")
        self.setStyleSheet(QSS_CONTENEDOR_SUBPESTANAS)
        self._barra = QTabBar()
        for i in range(tabs.count()):
            self._barra.addTab(tabs.tabText(i))
        self._barra.setExpanding(False)
        self._barra.setDrawBase(False)
        self._barra.setCursor(Qt.CursorShape.PointingHandCursor)
        self._barra.setStyleSheet(QSS_SUBPESTANAS + "QTabBar::tab:selected { color: #1B2B4E; border-bottom: 3px solid #1B2B4E; }")
        fila = QHBoxLayout(self)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.addWidget(self._barra)
        fila.addStretch()
        self.tabBarClicked = self._barra.tabBarClicked
        self._barra.currentChanged.connect(tabs.setCurrentIndex)
        tabs.currentChanged.connect(self._sincronizar)
        self._sincronizar(tabs.currentIndex())

    def _sincronizar(self, indice):
        if indice != self._barra.currentIndex():
            self._barra.blockSignals(True)
            self._barra.setCurrentIndex(indice)
            self._barra.blockSignals(False)

    def sincronizar_estado(self):
        for i in range(self._tabs.count()):
            self._barra.setTabEnabled(i, self._tabs.isTabEnabled(i))
            self._barra.setTabToolTip(i, self._tabs.tabToolTip(i))


class TarjetaKpiComercial(_Levantamiento, QPushButton):
    """Tarjeta KPI: fondo, borde y círculo decorativo pintados a mano para
    animar el hover (borde que se oscurece y la tarjeta sube 3 px, solo si
    es clicable). La marcada lleva borde de 2 px con su color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._acento = QColor(PRIMARIO)
        self._seleccionable = False
        self.setStyleSheet("QPushButton { background: transparent; border: none; text-align: left; }")
        self._iniciar_levantamiento(0, -3)
        self._hover = AnimacionHover(self, self._on_hover)
        self._plano = False

    def set_estilo_plano(self, plano=True):
        """Sin círculo decorativo; la tarjeta marcada lleva borde azul marino."""
        self._plano = plano
        self.update()

    def configurar(self, seleccionable, color):
        self._seleccionable = seleccionable
        self._acento = QColor(color)
        if not seleccionable and self._hover.progreso:
            self._on_hover(0.0)
        self.update()

    def set_color_acento(self, color):
        self._acento = QColor(color)
        self.update()

    def _on_hover(self, progreso):
        self._aplicar_levantamiento(progreso if self._seleccionable else 0.0)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        marcada = self._seleccionable and self.isChecked()
        grosor = (1.5 if self._plano else 2) if marcada else 1
        rect = QRectF(self.rect()).adjusted(grosor / 2, grosor / 2, -grosor / 2, -grosor / 2)
        contorno = QPainterPath()
        contorno.addRoundedRect(rect, 14, 14)
        painter.fillPath(contorno, tema.fondo(SUPERFICIE))

        if not self._plano:
            painter.save()
            painter.setClipPath(contorno)
            circulo = QColor(self._acento)
            circulo.setAlphaF(0.10)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(circulo)
            painter.drawEllipse(QRectF(self.width() - 82, -28, 110, 110))
            painter.restore()

        if marcada:
            borde = QColor("#1B2B4E") if self._plano else QColor(self._acento)
        else:
            p = self._hover.progreso if self._seleccionable else 0.0
            borde = interpolar(tema.fondo(LINEA), tema.fondo("#B9C6DA"), p)
        painter.setPen(QPen(borde, grosor))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(contorno)
        painter.end()


class BarraKpi(QWidget):
    """Barra de proporción de una tarjeta KPI; el ancho se anima al cambiar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._fraccion = 0.0
        self._color = QColor(PRIMARIO)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(700)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._cambio)

    def _cambio(self, valor):
        self._fraccion = float(valor)
        self.update()

    def set_valor(self, fraccion, color):
        self._color = QColor(color)
        fraccion = max(0.0, min(1.0, float(fraccion)))
        self._anim.stop()
        self._anim.setStartValue(self._fraccion)
        self._anim.setEndValue(fraccion)
        self._anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(tema.fondo(LINEA_SUAVE))
        painter.drawRoundedRect(QRectF(self.rect()), 3, 3)
        if self._fraccion > 0:
            painter.setBrush(self._color)
            painter.drawRoundedRect(QRectF(0, 0, max(6.0, self.width() * self._fraccion), self.height()), 3, 3)
        painter.end()


QSS_KPI_TITULO = f"color: {APAGADO}; font-size: 10px; font-weight: bold; letter-spacing: 0.8px; background: transparent; border: none;"
QSS_KPI_VALOR = f"color: {TINTA}; font-size: 24px; font-weight: 800; background: transparent; border: none;"
QSS_KPI_SUBTITULO = f"color: {APAGADO}; font-size: 10px; background: transparent; border: none;"


def qss_icono_kpi(fondo):
    return f"background-color: {fondo}; border-radius: 11px; border: none;"


def formatear_porcentaje(fraccion):
    return f"{fraccion * 100:.1f}".replace('.', ',') + " % del total"


# ---------------------------------------------------------- acciones rápidas

QSS_ACCION_RAPIDA_TRANSPARENTE = """
    QPushButton { background: transparent; border: 1px solid transparent; border-radius: 12px; text-align: left; padding: 8px; }
"""


class GrillaAcciones(QGridLayout):
    """Acciones de a dos por fila. Se reacomoda sola cuando un botón se
    muestra u oculta; un botón solo en la última fila ocupa todo el ancho."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)
        self._botones = []
        self._pendiente = False

    def agregar(self, boton):
        self._botones.append(boton)
        boton.installEventFilter(self)
        self._reacomodar()

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide) and not self._pendiente:
            self._pendiente = True
            QTimer.singleShot(0, self._reacomodar)
        return False

    @staticmethod
    def _oculto_a_proposito(boton):
        # isHidden() también es True en un botón recién creado que aún no se mostró
        return (boton.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide)
                and boton.testAttribute(Qt.WidgetAttribute.WA_WState_Hidden))

    def _reacomodar(self):
        self._pendiente = False
        for b in self._botones:
            self.removeWidget(b)
        visibles = [b for b in self._botones if not self._oculto_a_proposito(b)]
        for i, b in enumerate(visibles):
            solo = i == len(visibles) - 1 and len(visibles) % 2 == 1
            self.addWidget(b, i // 2, i % 2, 1, 2 if solo else 1)


class BotonAccionRapida(_Levantamiento, QPushButton):
    """Acción rápida con fondo/borde animados al pasar el mouse y un
    desplazamiento de 3 px a la derecha (como el HTML). Si se le asigna un
    QSS con fondo propio (ej. estado de "Agregar contacto"), ese QSS se
    pinta encima y manda."""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self.setStyleSheet(QSS_ACCION_RAPIDA_TRANSPARENTE)
        self._iniciar_levantamiento(3, 0)
        self._hover = AnimacionHover(self, self._on_hover)

    def _on_hover(self, progreso):
        self._aplicar_levantamiento(progreso if self.isEnabled() else 0.0)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.isEnabled():
            p = self._hover.progreso
            fondo = interpolar(tema.fondo(SUPERFICIE_2), tema.fondo(mezclar_con_blanco(self._color.name(), 0.08)), p)
            borde = interpolar(tema.fondo(LINEA), self._color, p)
        else:
            fondo, borde = tema.fondo(FONDO), tema.fondo(LINEA_SUAVE)
        painter.setPen(QPen(borde, 1))
        painter.setBrush(fondo)
        painter.drawRoundedRect(rect, 12, 12)
        painter.end()
        super().paintEvent(event)


def qss_icono_accion(color):
    return f"background-color: {mezclar_con_blanco(color, 0.14)}; border-radius: 10px; border: none;"


# ----------------------------------------------------------- ficha de unidad

QSS_FICHA_HERO = f"""
    QFrame#fichaHeroComercial {{
        border: 1px solid {LINEA}; border-radius: 14px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {PRIMARIO_SUAVE}, stop:1 {SUPERFICIE_2});
    }}
"""
QSS_FICHA_AVATAR = (
    "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3B82F6, stop:1 #14B8A6);"
    "color: white; border-radius: 14px; font-weight: 800; font-size: 14px; border: none;"
)
QSS_FICHA_NOMBRE = f"color: {TINTA}; font-weight: bold; font-size: 13px; background: transparent; border: none;"
QSS_FICHA_CHASIS = f"color: {APAGADO}; font-size: 11px; background: transparent; border: none;"
QSS_FICHA_META = f"QFrame#fichaMetaComercial {{ background-color: {SUPERFICIE_2}; border: 1px solid {LINEA}; border-radius: 12px; }}"
QSS_FICHA_META_TITULO = f"color: {APAGADO}; font-size: 9px; font-weight: 500; letter-spacing: 0.8px; background: transparent; border: none;"
QSS_FICHA_META_VALOR = f"color: {TINTA}; font-size: 12px; font-weight: 600; background: transparent; border: none;"
QSS_BOTON_CERRAR_PANEL = f"""
    QPushButton {{ background: transparent; border: none; border-radius: 13px; }}
    QPushButton:hover {{ background-color: {LINEA}; }}
"""
QSS_PANEL_FLOTANTE = f"QFrame#accionesRapidasComercial {{ background-color: {SUPERFICIE}; border: 1px solid #D5DDEA; border-radius: 14px; }}"
QSS_FICHA_VACIA =f"color: {APAGADO}; font-size: 12px; background: transparent; border: none; padding: 6px 2px;"
QSS_OBSERVACIONES = f"""
    QTextEdit {{ background-color: {SUPERFICIE_2}; border: 1px solid {LINEA}; border-radius: 12px; padding: 6px 8px; color: {TINTA}; font-size: 12px; }}
    QTextEdit:focus {{ border: 1px solid {PRIMARIO}; }}
    QTextEdit:disabled {{ background-color: {FONDO}; color: {APAGADO}; }}
"""
QSS_BOTON_GUARDAR = f"""
    QPushButton {{ background-color: {PRIMARIO}; color: white; border: none; border-radius: 10px; padding: 0px 14px; min-height: 32px; font-weight: 600; font-size: 12px; }}
    QPushButton:disabled {{ background-color: {PIZARRA_SUAVE}; color: {APAGADO}; }}
"""


def qss_chip(fondo, texto):
    return (f"background-color: {fondo}; color: {texto}; border-radius: 10px; padding: 2px 10px; "
            "font-size: 11px; font-weight: bold; border: none;")


def qss_chip_ficha(fondo, texto):
    return (f"background-color: {fondo}; color: {texto}; border-radius: 9px; padding: 2px 9px; "
            "font-size: 11px; font-weight: bold; border: none;")


def texto_chip_con_punto(valor):
    """Chip de la ficha: punto del color del texto + valor (texto enriquecido)."""
    return f"<span style='font-size:9px'>&#9679;</span>&nbsp;&nbsp;{html.escape(valor)}"


def crear_celda_ficha(titulo):
    """Celda de la ficha de la unidad: etiqueta en mayúsculas + chip."""
    celda = QFrame()
    celda.setObjectName("fichaMetaComercial")
    celda.setStyleSheet(QSS_FICHA_META)
    layout = QVBoxLayout(celda)
    layout.setContentsMargins(10, 7, 10, 8)
    layout.setSpacing(5)
    lbl_titulo = QLabel(titulo)
    lbl_titulo.setObjectName("fichaMetaTitulo")
    fuente = lbl_titulo.font()
    fuente.setCapitalization(QFont.Capitalization.AllUppercase)
    lbl_titulo.setFont(fuente)
    lbl_titulo.setWordWrap(True)
    lbl_titulo.setStyleSheet(QSS_FICHA_META_TITULO)
    lbl_valor = QLabel("-")
    lbl_valor.setWordWrap(True)
    lbl_valor.setTextFormat(Qt.TextFormat.RichText)
    layout.addWidget(lbl_titulo)
    layout.addWidget(lbl_valor, alignment=Qt.AlignmentFlag.AlignLeft)
    return celda, lbl_valor


def colores_chip(valor):
    """(fondo, texto) QColor del chip de `valor`, con los colores del
    catálogo de la tabla; gris neutro si el valor no tiene color asignado."""
    from src.ui.custom_table import _FONDO_CATALOGO, _TEXTO_CATALOGO
    clave = str(valor).strip().upper()
    fondo = _FONDO_CATALOGO.get(clave)
    color = _TEXTO_CATALOGO.get(clave)
    return (fondo if fondo is not None else QColor(PIZARRA_SUAVE),
            color if color is not None else QColor(PIZARRA))


def pintar_chip_ficha(lbl, valor):
    """Chip con punto y los colores del catálogo; texto simple si está vacío."""
    texto = "" if valor is None else str(valor).strip()
    if texto.upper() in ('', '-', 'NAN', 'NONE'):
        lbl.setText('-')
        lbl.setStyleSheet(QSS_FICHA_META_VALOR)
        return
    fondo, color = colores_chip(texto)
    lbl.setText(texto_chip_con_punto(texto))
    lbl.setStyleSheet(qss_chip_ficha(fondo.name(), color.name()))


def kpi_ocultos_guardado():
    """Preferencia global (misma para todas las pantallas) de ocultar las
    tarjetas KPI; vive en el mismo QSettings que el sidebar."""
    try:
        return QSettings("GestorApp", "Dashboard").value("kpi_ocultos", False, type=bool)
    except Exception:
        return False


def guardar_kpi_ocultos(ocultos):
    try:
        QSettings("GestorApp", "Dashboard").setValue("kpi_ocultos", bool(ocultos))
    except Exception:
        pass


def sincronizar_boton_kpi(boton):
    """Deja el botón "Ampliar" igual a la preferencia guardada (si otra
    pantalla la cambió mientras esta estaba oculta)."""
    if boton is not None and boton.isChecked() != kpi_ocultos_guardado():
        boton.setChecked(kpi_ocultos_guardado())


def iniciales(texto):
    palabras = [p for p in str(texto).split() if len(p) > 2]
    return "".join(p[0] for p in palabras[:2]).upper() or "--"


# ------------------------------------------------------------------- tabla

QSS_TABLA = f"""
    QTableView {{
        background-color: {SUPERFICIE}; border: none;
        border-bottom-left-radius: 13px; border-bottom-right-radius: 13px;
        font-family: '{FAMILIA_FUENTE}', 'Segoe UI', sans-serif; font-size: 9pt;
        alternate-background-color: {FILA_ALTERNA}; color: {TINTA}; outline: 0;
    }}
    QTableView::item {{ padding: 3px 8px; border: none; border-bottom: 1px solid {LINEA_SUAVE}; border-left: 1px solid {LINEA_SUAVE}; }}
    QTableView::item:selected {{ background-color: {FILA_SELECCION}; color: {TINTA}; }}
    QHeaderView::section {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {ENCABEZADO_1}, stop:1 {ENCABEZADO_2});
        color: {ENCABEZADO_TEXTO}; padding: 6px 8px; border: none; border-bottom: 3px solid {PRIMARIO};
        font-weight: bold; font-size: 8pt;
    }}
    QScrollBar:vertical {{ border: none; background: transparent; width: 8px; margin: 0px; }}
    QScrollBar::handle:vertical {{ background: #CBD5E1; min-height: 30px; border-radius: 4px; }}
    QScrollBar::handle:vertical:hover {{ background: {APAGADO}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar:horizontal {{ border: none; background: transparent; height: 8px; margin: 0px; }}
    QScrollBar::handle:horizontal {{ background: #CBD5E1; min-width: 30px; border-radius: 4px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
"""


def aplicar_estilo_encabezado(header):
    header.set_estilo_encabezado(
        ENCABEZADO_1, ENCABEZADO_2, ENCABEZADO_TEXTO, PRIMARIO,
        separador=QColor(255, 255, 255, 26), grosor_linea=3, alto_minimo=44, espaciado_letras=0.8,
        iconos_orden=True, radio_superior=13,
    )


class DelegadoCeldasComercial(QStyledItemDelegate):
    """Filas completas resaltadas al pasar el mouse, barra de acento en la
    fila seleccionada y columnas de catálogo (las que el modelo colorea con
    BackgroundRole) como píldoras en vez de la celda entera pintada."""

    ALTO_CHIP = 22

    def __init__(self, vistas):
        super().__init__(vistas[0])
        self._vistas = list(vistas)
        self._fila_hover = -1
        for vista in self._vistas:
            vista.viewport().setMouseTracking(True)
            vista.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        tipo = event.type()
        if tipo in (QEvent.Type.MouseMove, QEvent.Type.Leave):
            fila = -1
            if tipo == QEvent.Type.MouseMove:
                for vista in self._vistas:
                    if vista.viewport() is obj:
                        fila = vista.rowAt(int(event.position().y()))
                        break
            if fila != self._fila_hover:
                self._fila_hover = fila
                for vista in self._vistas:
                    vista.viewport().update()
        return False

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        seleccionada = bool(opt.state & QStyle.StateFlag.State_Selected)

        fondo_chip = index.data(Qt.ItemDataRole.BackgroundRole)
        texto_chip = None
        if fondo_chip is not None and opt.text:
            texto_chip = opt.text
            opt.text = ""
            opt.backgroundBrush = QBrush()

        if not seleccionada and index.row() == self._fila_hover:
            # El estilo con QSS ignora backgroundBrush: se pinta el fondo antes
            painter.fillRect(opt.rect, tema.fondo(FILA_HOVER))
            opt.backgroundBrush = QBrush()
            opt.features &= ~QStyleOptionViewItem.ViewItemFeature.Alternate

        widget = opt.widget
        estilo = widget.style() if widget is not None else QApplication.style()
        estilo.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)

        if texto_chip is not None:
            color_texto = index.data(Qt.ItemDataRole.ForegroundRole)
            self._pintar_chip(painter, opt, texto_chip, tema.fondo(QColor(fondo_chip)),
                              tema.texto(QColor(color_texto) if color_texto is not None else QColor(PIZARRA)))

        if seleccionada and widget is not None and widget.horizontalHeader().visualIndex(index.column()) == 0:
            painter.fillRect(opt.rect.x(), opt.rect.y(), 3, opt.rect.height(), QColor(PRIMARIO))

    def _pintar_chip(self, painter, opt, texto, fondo, color_texto):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fuente = QFont(opt.font)
        fuente.setBold(True)
        fuente.setPointSizeF(max(7.0, fuente.pointSizeF() - 0.5))
        fm = QFontMetrics(fuente)
        punto, separacion, relleno = 6, 6, 10
        ancho_max = max(30, opt.rect.width() - 12)
        texto_visible = fm.elidedText(texto, Qt.TextElideMode.ElideRight, ancho_max - (2 * relleno + punto + separacion))
        ancho = min(ancho_max, 2 * relleno + punto + separacion + fm.horizontalAdvance(texto_visible))
        alto = self.ALTO_CHIP
        x = opt.rect.x() + (opt.rect.width() - ancho) / 2
        y = opt.rect.y() + (opt.rect.height() - alto) / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fondo)
        painter.drawRoundedRect(QRectF(x, y, ancho, alto), alto / 2, alto / 2)
        painter.setBrush(color_texto)
        painter.drawEllipse(QRectF(x + relleno, y + (alto - punto) / 2, punto, punto))
        painter.setPen(color_texto)
        painter.setFont(fuente)
        painter.drawText(QRectF(x + relleno + punto + separacion, y, ancho - relleno * 2 - punto - separacion, alto),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, texto_visible)
        painter.restore()


# ------------------------------------------- Ingresos y Conciliación (HTML v2)

class TarjetaKpiResumen(TarjetaKpiComercial):
    """Tarjeta KPI con el diseño de las de Comercial (estilo plano): título,
    valor y, abajo, la píldora con el porcentaje más una línea de apoyo. Filtra
    al hacer clic; la marcada lleva borde azul marino."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QSizePolicy
        self.set_estilo_plano(True)
        self.setFixedHeight(92)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(0)
        self._lbl_titulo = QLabel("")
        self._lbl_titulo.setWordWrap(True)
        self._lbl_titulo.setStyleSheet(
            f"color: {APAGADO}; font-size: 12px; font-weight: 500; background: transparent; border: none;")
        self._lbl_valor = QLabel("0")
        self._lbl_valor.setStyleSheet(
            f"color: {TINTA}; font-size: 24px; font-weight: 800; background: transparent; border: none;")
        self._pildora = QLabel("")
        self._pildora.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pildora.setFixedHeight(20)
        self._lbl_pie = QLabel("")
        self._lbl_pie.setStyleSheet(
            f"color: {APAGADO}; font-size: 11px; background: transparent; border: none;")
        pie = QHBoxLayout()
        pie.setSpacing(10)
        pie.addWidget(self._pildora)
        pie.addWidget(self._lbl_pie, stretch=1)
        layout.addWidget(self._lbl_titulo)
        layout.addWidget(self._lbl_valor)
        layout.addStretch()
        layout.addLayout(pie)

    def definir(self, titulo, color, tooltip=""):
        color_q = QColor(color)
        self.configurar(True, color)
        self.setToolTip(tooltip)
        self._lbl_titulo.setText(titulo)
        self._pildora.setStyleSheet(
            f"color: {color}; background-color: rgba({color_q.red()},{color_q.green()},{color_q.blue()},0.14); "
            "border-radius: 10px; padding: 0px 8px; font-size: 11px; font-weight: 800; border: none;")

    def actualizar(self, valor, porcentaje, pie):
        """`porcentaje` entre 0 y 1; con None se oculta la píldora (montos)."""
        self._lbl_valor.setText(str(valor))
        self._pildora.setVisible(porcentaje is not None)
        if porcentaje is not None:
            self._pildora.setText(f"{round(porcentaje * 100)} %")
        self._lbl_pie.setText(pie)


class BotonAccionPanel(BotonAccionRapida):
    """Acción del panel flotante (mismo look que las de Comercial y
    Operaciones): ícono, título y una línea de ayuda."""

    def __init__(self, icono, titulo, subtitulo, color, parent=None):
        super().__init__(color, parent)
        from src.theme.theme_manager import ThemeManager
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(58)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 12, 6)
        layout.setSpacing(12)
        marco = QFrame()
        marco.setFixedSize(36, 36)
        marco.setStyleSheet(qss_icono_accion(color))
        marco_layout = QVBoxLayout(marco)
        marco_layout.setContentsMargins(0, 0, 0, 0)
        lbl_icono = QLabel()
        lbl_icono.setPixmap(ThemeManager.icon_pixmap(icono, color=color, size=15))
        lbl_icono.setStyleSheet("background: transparent; border: none;")
        marco_layout.addWidget(lbl_icono, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(marco)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        self._lbl_titulo = QLabel(titulo.strip())
        self._lbl_subtitulo = QLabel(subtitulo)
        self._lbl_subtitulo.setWordWrap(True)
        textos.addWidget(self._lbl_titulo)
        textos.addWidget(self._lbl_subtitulo)
        layout.addLayout(textos, stretch=1)
        self._pintar_textos()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._pintar_textos()

    def _pintar_textos(self):
        color = TINTA if self.isEnabled() else APAGADO
        self._lbl_titulo.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px; background: transparent; border: none;")
        self._lbl_subtitulo.setStyleSheet(f"color: {APAGADO}; font-size: 10px; background: transparent; border: none;")


class _PopupSelector(QFrame):
    """Tarjeta flotante con sombra y esquinas redondeadas con la lista de opciones."""

    def __init__(self, titulo, al_elegir):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._al_elegir = al_elegir
        externo = QVBoxLayout(self)
        externo.setContentsMargins(14, 8, 14, 20)
        tarjeta = QFrame()
        tarjeta.setObjectName("popupSelector")
        tarjeta.setStyleSheet(
            "QFrame#popupSelector { background: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 14px; }")
        sombra = QGraphicsDropShadowEffect(tarjeta)
        sombra.setBlurRadius(28)
        sombra.setOffset(0, 8)
        sombra.setColor(QColor(27, 43, 78, 70))
        tarjeta.setGraphicsEffect(sombra)
        externo.addWidget(tarjeta)
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(6)
        encabezado = QLabel(titulo.upper())
        encabezado.setStyleSheet(
            "color: #66748D; font-size: 10px; font-weight: 800; letter-spacing: 1px; "
            "background: transparent; border: none; padding-left: 8px;")
        lay.addWidget(encabezado)
        self.lista = QListWidget()
        self.lista.setFrameShape(QFrame.Shape.NoFrame)
        self.lista.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.setMouseTracking(True)
        self.lista.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { color: #1B2B4E; padding: 0 12px; margin: 1px 0; border-radius: 9px; "
            "font-size: 13px; font-weight: 600; }"
            "QListWidget::item:hover { background: #F1F4F9; }"
            "QListWidget::item:selected { background: #E3E8F0; color: #1B2B4E; font-weight: 800; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }"
            "QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 3px; min-height: 28px; }"
            "QScrollBar::handle:vertical:hover { background: #A9B6C9; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }")
        self.lista.itemClicked.connect(self._clic)
        lay.addWidget(self.lista)

    def _clic(self, item):
        if item.flags() & Qt.ItemFlag.ItemIsSelectable:
            self._al_elegir(item.data(Qt.ItemDataRole.UserRole))
            self.close()


def ubicar_popup_selector(popup, ancla):
    """Coloca la tarjeta bajo `ancla` (o encima si abajo no cabe) sin salirse
    de la ventana de la app ni de la pantalla; si la lista es más alta que el
    espacio disponible, se acorta y se recorre con scroll."""
    from PyQt6.QtCore import QPoint
    popup.layout().activate()
    lista = popup.lista
    alto_lista = lista.height()
    extra = popup.sizeHint().height() - alto_lista
    popup.setFixedHeight(alto_lista + extra)
    ventana = ancla.window().frameGeometry()
    pantalla = ancla.screen().availableGeometry() if ancla.screen() is not None else ventana
    limite = ventana.intersected(pantalla)
    bajo = ancla.mapToGlobal(QPoint(0, ancla.height())).y() - 6
    alto_ancla_arriba = ancla.mapToGlobal(QPoint(0, 0)).y() + 6
    espacio_abajo = limite.bottom() - bajo - 6
    espacio_arriba = alto_ancla_arriba - limite.top() - 6
    total = alto_lista + extra
    if total <= espacio_abajo:
        y = bajo
    elif total <= espacio_arriba:
        y = alto_ancla_arriba - total
    else:
        abajo = espacio_abajo >= espacio_arriba
        disponible = max(espacio_abajo if abajo else espacio_arriba, extra + 80)
        lista.setFixedHeight(max(80, disponible - extra))
        popup.setFixedHeight(lista.height() + extra)
        y = bajo if abajo else alto_ancla_arriba - popup.height()
    x = ancla.mapToGlobal(QPoint(0, 0)).x() - 14
    x = max(limite.left(), min(x, limite.right() - popup.width()))
    popup.move(x, max(limite.top(), y))


class SelectorFiltroPopup(QPushButton):
    """Botón de filtro para la barra oscura: muestra la opción elegida y abre
    una tarjeta con las opciones agrupadas. `valor()` es None cuando está en
    "todos"."""
    cambiado = pyqtSignal(object)

    def __init__(self, titulo, texto_todos, icono='fa5s.calendar-alt', parent=None):
        super().__init__(parent)
        self._titulo = titulo
        self._texto_todos = texto_todos
        self._grupos = []
        self._valor = None
        self._popup = None
        self._compacto = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Filtrar por {titulo.lower()}")
        self.setMinimumWidth(190)
        self.setIcon(qta.icon(icono, color='white'))
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,0.10); color: white; "
            "border: 1px solid rgba(255,255,255,0.18); border-radius: 10px; min-height: 34px; "
            "padding: 0 14px; font-weight: 700; text-align: left; }"
            "QPushButton:hover { background-color: rgba(255,255,255,0.20); }")
        self._actualizar_texto()

    def valor(self):
        return self._valor

    def set_opciones(self, grupos):
        """`grupos`: lista de (titulo_grupo | None, [(valor, etiqueta), ...])."""
        self._grupos = grupos
        existentes = {v for _, items in grupos for v, _ in items}
        if self._valor not in existentes:
            self._valor = None
        self._actualizar_texto()

    def _etiqueta_actual(self):
        for _, items in self._grupos:
            for valor, etiqueta in items:
                if valor == self._valor:
                    return etiqueta
        return self._texto_todos

    def set_compacto(self, compacto):
        """Con un panel lateral abierto queda solo el icono; el valor elegido
        pasa a la ayuda emergente y un punto ámbar avisa que hay un filtro."""
        if compacto == self._compacto:
            return
        self._compacto = compacto
        if compacto:
            self.setFixedWidth(44)
        else:
            self.setMinimumWidth(190)
            self.setMaximumWidth(16777215)
        self._actualizar_texto()
        self.update()

    def _actualizar_texto(self):
        if self._compacto:
            self.setText("")
            self.setToolTip(f"{self._titulo}: {self._etiqueta_actual()}")
            return
        self.setToolTip(f"Filtrar por {self._titulo.lower()}")
        self.setText("  " + self._etiqueta_actual() + "   ▾")

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._compacto and self._valor is not None:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FBBF24"))
            p.drawEllipse(QRectF(self.width() - 13, 5, 8, 8))
            p.end()

    def _elegir(self, valor):
        if valor == self._valor:
            return
        self._valor = valor
        self._actualizar_texto()
        self.cambiado.emit(valor)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self.rect().contains(e.position().toPoint()):
            self._abrir()

    def _abrir(self):
        popup = _PopupSelector(self._titulo, self._elegir)
        lista = popup.lista

        def agregar(texto, valor=None, seleccionable=True):
            item = QListWidgetItem(texto)
            item.setData(Qt.ItemDataRole.UserRole, valor)
            if seleccionable:
                item.setSizeHint(QSize(0, 38))
            else:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setSizeHint(QSize(0, 26))
                fuente = item.font()
                fuente.setPointSizeF(max(7.5, fuente.pointSizeF() - 1.5))
                fuente.setBold(True)
                item.setFont(fuente)
                item.setForeground(QColor("#8A97AB"))
            lista.addItem(item)
            return item

        elegido = agregar(self._texto_todos, None)
        filas = 1
        for titulo, items in self._grupos:
            if titulo:
                agregar(titulo, seleccionable=False)
                filas += 0.7
            for valor, etiqueta in items:
                item = agregar(etiqueta, valor)
                filas += 1
                if valor == self._valor:
                    elegido = item
        if self._valor is None:
            elegido = lista.item(0)
        lista.setCurrentItem(elegido)
        lista.scrollToItem(elegido)

        ancho = max(self.width(), 250)
        alto_lista = int(min(filas * 40, 360))
        lista.setFixedHeight(alto_lista + 4)
        popup.setFixedWidth(ancho + 28)
        ubicar_popup_selector(popup, self)
        self._popup = popup
        popup.show()

class BotonOpcionesTarjeta(QPushButton):
    """Botón que abre la tarjeta flotante con una lista de opciones (mismo
    popup que ComboTarjeta/SelectorFiltroPopup). Con `mostrar_valor` el texto
    del botón es la opción elegida; si no, queda fijo (ej. "Ordenar")."""

    def __init__(self, titulo, texto="", opciones=(), valor=None, mostrar_valor=False,
                 al_elegir=None, parent=None):
        super().__init__(parent)
        self._titulo = titulo
        self._texto = texto
        self._opciones = list(opciones)
        self._valor = valor
        self._mostrar_valor = mostrar_valor
        self._al_elegir = al_elegir
        self._popup = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._actualizar_texto()

    def valor(self):
        return self._valor

    def _actualizar_texto(self):
        texto = self._texto
        if self._mostrar_valor:
            texto = next((e for v, e in self._opciones if v == self._valor), self._texto)
        self.setText(f" {texto}   ▾")

    def _elegir(self, valor):
        if valor != self._valor:
            self._valor = valor
            self._actualizar_texto()
        if self._al_elegir is not None:
            self._al_elegir(valor)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self.rect().contains(e.position().toPoint()):
            self._abrir()

    def _abrir(self):
        popup = _PopupSelector(self._titulo, self._elegir)
        lista = popup.lista
        for valor, etiqueta in self._opciones:
            item = QListWidgetItem(etiqueta)
            item.setData(Qt.ItemDataRole.UserRole, valor)
            item.setSizeHint(QSize(0, 38))
            lista.addItem(item)
            if valor == self._valor:
                lista.setCurrentItem(item)
        lista.setFixedHeight(int(min(len(self._opciones) * 40, 360)) + 4)
        popup.setFixedWidth(max(self.width(), 200) + 28)
        ubicar_popup_selector(popup, self)
        self._popup = popup
        popup.show()


class ComboTarjeta(QComboBox):
    """QComboBox que abre su lista en la misma tarjeta flotante del selector de
    periodo (esquinas redondeadas, sombra y selección resaltada). Conserva toda
    la API de QComboBox, así que sirve de reemplazo directo."""

    def __init__(self, titulo="", parent=None):
        super().__init__(parent)
        self._titulo_popup = titulo
        self._popup = None

    def showPopup(self):
        if self.count() == 0:
            return
        popup = _PopupSelector(self._titulo_popup, self._elegir)
        lista = popup.lista
        for i in range(self.count()):
            item = QListWidgetItem(self.itemText(i))
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setSizeHint(QSize(0, 38))
            lista.addItem(item)
        lista.setCurrentRow(max(0, self.currentIndex()))
        lista.scrollToItem(lista.currentItem())
        lista.setFixedHeight(int(min(self.count() * 40, 360)) + 4)
        popup.setFixedWidth(max(self.width(), 230) + 28)
        ubicar_popup_selector(popup, self)
        self._popup = popup
        popup.show()

    def hidePopup(self):
        if self._popup is not None:
            self._popup.close()

    def _elegir(self, indice):
        if indice is not None and indice != self.currentIndex():
            self.setCurrentIndex(indice)
            self.activated.emit(indice)
