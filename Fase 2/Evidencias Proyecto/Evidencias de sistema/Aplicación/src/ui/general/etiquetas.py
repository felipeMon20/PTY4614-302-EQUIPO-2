"""Etiquetas, chips copiables y controles pequeños de General."""
from src.theme.colors import BORDER, PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY
import html
from PyQt6.QtWidgets import (QLabel, QPushButton, QStackedWidget, QStackedLayout, QListWidgetItem, QGridLayout, QSizePolicy, QFrame, QVBoxLayout,
                             QHBoxLayout)
from PyQt6.QtCore import Qt, QSize, QRectF, QTimer, QDate, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from src.ui.compartido.comercial_estilo import PopupFiltroValores
from src.ui.compartido.copiar import copiar_texto, escribir_portapapeles
from src.ui.compartido.selector_fecha import SelectorFecha
from src.ui.general.constantes import (
    AZUL,
    LINEA_AZUL,
    TEXTO_SOBRE_AZUL,
    TINTE_CLARO,
    _clave_flota_texto,
)


class _PilaAltoDePaginaActual(QStackedLayout):
    """Pila cuyo «alto según el ancho» es el de la página visible: la de Qt toma el mayor de todas las páginas
    y el scroll que la envuelve dejaba a Contratos anteriores con el alto de Historial."""

    def hasHeightForWidth(self):
        pagina = self.currentWidget()
        return bool(pagina is not None and pagina.hasHeightForWidth())

    def heightForWidth(self, ancho):
        pagina = self.currentWidget()
        return pagina.heightForWidth(ancho) if pagina is not None else -1


class _StackedWidgetTamañoActual(QFrame):
    """Pila de páginas cuyo sizeHint/minimumSizeHint (y alto según el ancho) solo considera la página
    actualmente visible, no el máximo entre todas sus páginas (comportamiento
    por defecto de QStackedWidget/QStackedLayout). Usado únicamente por
    vin_detalle_stack (Ficha/Historial/Contratos anteriores de la caja derecha -> Unidades): sin
    esto, la caja derecha crecía siempre según la pestaña con más contenido
    (Historial, con muchos eventos) aunque estuviera mostrando la otra
    (Ficha), a pedido explícito (15-09-2026). Ofrece lo mismo que QStackedWidget que se usa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pila = _PilaAltoDePaginaActual(self)

    def addWidget(self, widget):
        return self._pila.addWidget(widget)

    def currentWidget(self):
        return self._pila.currentWidget()

    def currentIndex(self):
        return self._pila.currentIndex()

    def setCurrentIndex(self, indice):
        self._pila.setCurrentIndex(indice)

    def count(self):
        return self._pila.count()

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()


class _EtiquetaElidida(QLabel):
    """Etiqueta de una línea que pide su ancho natural (así el badge queda
    pegado al texto) y, si no cabe, corta con "…". text() devuelve el texto
    completo."""

    def __init__(self, texto="", parent=None):
        super().__init__(parent)
        self._completo = str(texto)
        super().setText(self._completo)
        self.setMinimumWidth(40)
        self.margen_extra = 0
        self.setToolTip(self._completo)

    def text(self):
        return self._completo

    def setText(self, texto):
        self._completo = str(texto)
        self.setToolTip(self._completo)
        self._elidir()

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self._completo) + 4 + self.margen_extra, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(40, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elidir()

    def _elidir(self):
        super().setText(self.fontMetrics().elidedText(
            self._completo, Qt.TextElideMode.ElideRight, max(self.width() - self.margen_extra, 1)))


class CopyableLabel(QLabel):
    """Etiqueta que se resalta al pasar el mouse y copia su texto al
    portapapeles con un clic (usada en el subtítulo del detalle de cliente:
    Industria | RUT | CDB)."""

    _BASE_STYLE = f"color: {TEXT_SECONDARY}; font-size: 10px; padding: 1px 7px; border-radius: 9px; border: 1px solid transparent;"
    _HOVER_STYLE = _BASE_STYLE + f"background-color: {TINTE_CLARO}; color: {AZUL}; border: 1px solid {LINEA_AZUL};"
    _COPIADO_STYLE = _BASE_STYLE + "background-color: #D1FAE5; color: #065F46; border: 1px solid #6EE7B7; font-weight: bold;"
    _DURACION_COPIADO_MS = 1200

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._BASE_STYLE)
        self.setToolTip("Clic para copiar")
        self._copiado = False
        self._texto_original = None

    def set_value(self, label, value):
        """El chip dice "Copiar <label>" y copia el valor (que se ve en el tooltip); sin valor muestra "<label>: -"."""
        self._restaurar_texto()
        if value in (None, "", "-", "N/A"):
            self._copy_value = None
            self.setText(f"{label}: -")
            self.setToolTip("")
            return
        self._copy_value = str(value)
        self.setText(f"Copiar {label}")
        self.setToolTip(f"Clic para copiar: {self._copy_value}")

    def set_texto_copiable(self, texto, valor):
        """Muestra `texto` (p. ej. "Copiar Flota") y copia `valor` al hacer clic."""
        self._restaurar_texto()
        self._copy_value = str(valor) if valor not in (None, "") else "N/A"
        self.setText(texto)

    def _restaurar_texto(self):
        if self._copiado:
            self._copiado = False
            if self._texto_original is not None:
                self.setText(self._texto_original)
            self._texto_original = None

    def _fin_copiado(self):
        # El widget pudo reconstruirse mientras corría el temporizador
        try:
            self._restaurar_texto()
            self.setStyleSheet(self._HOVER_STYLE if self.underMouse() else self._BASE_STYLE)
        except RuntimeError:
            pass

    def enterEvent(self, event):
        if not self._copiado:
            self.setStyleSheet(self._HOVER_STYLE)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._copiado:
            self.setStyleSheet(self._BASE_STYLE)
        super().leaveEvent(event)

    def _copiar_valor(self):
        # Se verifica lo copiado y se reintenta si otro programa tenía el portapapeles (ver copiar.py)
        ok = escribir_portapapeles(self._copy_value)
        if not self._copiado:
            self._texto_original = self.text()
            self._copiado = True
        self.setText("✓ Copiado" if ok else "No se pudo copiar")
        self.setStyleSheet(self._COPIADO_STYLE if ok else self._BASE_STYLE + "; color: #C0392B; font-weight: bold;")
        QTimer.singleShot(self._DURACION_COPIADO_MS, self._fin_copiado)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, '_copy_value', None):
            self._copiar_valor()
        super().mousePressEvent(event)


class CopyableChip(CopyableLabel):
    """CopyableLabel con aspecto de chip (borde y fondo visibles en reposo)."""

    _BASE_STYLE = f"color: {TEXT_SECONDARY}; font-size: 10px; padding: 1px 7px; border-radius: 9px; background-color: #F7F9FC; border: 1px solid {BORDER};"
    _HOVER_STYLE = _BASE_STYLE + f"background-color: {TINTE_CLARO}; color: {AZUL}; border: 1px solid {LINEA_AZUL};"
    _COPIADO_STYLE = _BASE_STYLE + "background-color: #D1FAE5; color: #065F46; border: 1px solid #6EE7B7; font-weight: bold;"


class CopyableTitulo(CopyableLabel):
    """VIN grande del detalle: se resalta y se copia con un clic."""

    # El fondo redondeado lo dibuja paintEvent (con el estilo del label el hover salía con esquinas rectas)
    _BASE_STYLE = "color: white; font-size: 18px; font-weight: bold; padding: 1px 8px; border: none; background: transparent;"
    _HOVER_STYLE = f"color: {AZUL}; font-size: 18px; font-weight: bold; padding: 1px 8px; border: none; background: transparent;"
    _COPIADO_STYLE = "color: #065F46; font-size: 18px; font-weight: bold; padding: 1px 8px; border: none; background: transparent;"
    _RADIO_FONDO = 11

    def paintEvent(self, event):
        relleno = None
        if self._copiado:
            relleno, borde = QColor("#D1FAE5"), QColor("#6EE7B7")
        elif self.underMouse():
            relleno, borde = QColor("white"), QColor("white")
        if relleno is not None:
            pintor = QPainter(self)
            pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
            pintor.setPen(borde)
            pintor.setBrush(relleno)
            pintor.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._RADIO_FONDO, self._RADIO_FONDO)
            pintor.end()
        super().paintEvent(event)

    def set_value(self, label, value):
        self._restaurar_texto()
        self._copy_value = str(value) if value not in (None, "") else "N/A"
        self.setText(f"{label} {self._copy_value}")

    def set_texto(self, valor):
        self._restaurar_texto()
        self._copy_value = str(valor) if valor not in (None, "") else "N/A"
        self.setText(self._copy_value)


class CopyableValueLabel(QLabel):
    """Valor de una fila de "Información del cliente" con clic-para-copiar (Dirección/Comuna,
    ver _render_info_cliente): mismo gesto que CopyableLabel, pero
    conservando el estilo bold/alineado a la derecha propio de las filas
    de la caja "Información del cliente" en vez del estilo fijo de
    CopyableLabel (pensado para el subtítulo Industria | RUT | CDB)."""

    def __init__(self, text, copy_value, base_style, parent=None):
        super().__init__(text, parent)
        self._copy_value = copy_value
        self._base_style = base_style
        self._hover_style = base_style + f" background-color: {TINTE_CLARO}; color: {AZUL};"
        self.setStyleSheet(self._base_style)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clic para copiar")

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._base_style)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._copy_value:
            copiar_texto(self._copy_value, self)
        super().mousePressEvent(event)


class _EtiquetaElididaCopiable(_EtiquetaElidida):
    """Valor de una sola línea (cortado con "…") que al hacer clic copia
    `copy_value`, que puede ser más que lo que se ve."""

    def __init__(self, text, copy_value, base_style, parent=None):
        super().__init__(text, parent)
        self._copy_value = copy_value
        self._base_style = base_style
        self._hover_style = base_style + f" background-color: {TINTE_CLARO}; color: {AZUL};"
        self.setStyleSheet(self._base_style)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._base_style)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._copy_value:
            copiar_texto(self._copy_value, self)
        super().mousePressEvent(event)


class _EtiquetaDosLineas(QLabel):
    """Nombre que se parte en hasta 2 líneas y, si aún no cabe, corta con "…".
    Pide solo el alto de las líneas que usa; text() devuelve el texto completo."""

    def __init__(self, texto="", parent=None):
        super().__init__(parent)
        self._completo = str(texto)
        self._ultimo_ancho = -1
        self.setWordWrap(True)
        self.setToolTip(self._completo)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        super().setText(self._completo)

    def text(self):
        return self._completo

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._ajustar()

    def _ajustar(self):
        metrica = self.fontMetrics()
        ancho = max(self.width(), 40)
        if ancho == self._ultimo_ancho:
            return
        self._ultimo_ancho = ancho
        alto_linea = metrica.lineSpacing()
        flags = int(Qt.TextFlag.TextWordWrap)

        def lineas(texto):
            return max(1, round(metrica.boundingRect(0, 0, ancho, 10000, flags, texto).height() / alto_linea))

        texto = self._completo
        if lineas(texto) > 2:
            bajo, alto = 0, len(texto)
            while bajo < alto:
                medio = (bajo + alto + 1) // 2
                if lineas(texto[:medio].rstrip() + "…") <= 2:
                    bajo = medio
                else:
                    alto = medio - 1
            texto = texto[:bajo].rstrip() + "…"
        if super().text() != texto:
            super().setText(texto)
        alto_fijo = min(lineas(texto), 2) * alto_linea + 2
        if self.height() != alto_fijo or self.minimumHeight() != alto_fijo:
            self.setFixedHeight(alto_fijo)


class _GrillaTarjetas(QGridLayout):
    """Reparte las tarjetas en columnas iguales, de izquierda a derecha y luego
    hacia abajo. Mantiene la interfaz de lista (addWidget sin posición,
    addStretch) que usan _construir_tarjetas_por_tandas y el repintado."""

    def __init__(self, columnas, parent=None):
        super().__init__(parent)
        self._columnas = columnas
        self._n = 0
        for c in range(columnas):
            self.setColumnStretch(c, 1)

    @property
    def columnas(self):
        return self._columnas

    def addWidget(self, widget, *args):
        if args:
            super().addWidget(widget, *args)
            return
        super().addWidget(widget, self._n // self._columnas, self._n % self._columnas)
        self._n += 1

    def addStretch(self, *_):
        self.setRowStretch(self.rowCount(), 1)

    def vaciar(self):
        while self.count():
            item = self.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for fila in range(self.rowCount()):
            self.setRowStretch(fila, 0)
        self._n = 0


class _EnlaceLabel(QLabel):
    """Texto en azul que al pasar el mouse se subraya y emite clicked."""
    clicked = pyqtSignal()

    def __init__(self, texto="", parent=None):
        super().__init__(texto, parent)
        self._base = f"color: {PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;"
        self.setStyleSheet(self._base)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clic para abrir")

    def enterEvent(self, event):
        self.setStyleSheet(self._base + " text-decoration: underline;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._base)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class FiltroValoresBoton(QPushButton):
    """Botón de filtro por columna: muestra "Título: Todos / valor / n de N" y
    abre una tarjeta con los valores distintos de la columna (sin vacíos ni
    '-', sin repetir aunque difieran en mayúsculas). `seleccion()` es None
    cuando no filtra."""
    cambiado = pyqtSignal()

    _ESTILO = ("QPushButton {{ background-color: {bg}; color: {fg}; border: 1px solid {borde}; border-radius: 12px; "
               "padding: 4px 8px; font-size: 11px; font-weight: 600; text-align: left; }}"
               "QPushButton:hover {{ border-color: #1F6FEB; }}")

    def __init__(self, titulo, parent=None):
        super().__init__(parent)
        self._titulo = titulo
        self._valores = []
        self._marcados = set()
        self._popup = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._actualizar()

    @staticmethod
    def valores_distintos(serie):
        """[(clave, etiqueta, cantidad)] ordenado, sin vacíos ni '-'."""
        cuenta, etiquetas = {}, {}
        texto = serie.astype(str).str.strip()
        repeticiones = texto.value_counts()
        for v in texto.drop_duplicates():
            if v == '' or v == '-' or v.lower() in ('nan', 'none', '<na>'):
                continue
            k = _clave_flota_texto(v)
            cuenta[k] = cuenta.get(k, 0) + int(repeticiones[v])
            etiquetas.setdefault(k, v)
        return [(k, etiquetas[k], cuenta[k]) for k in sorted(cuenta, key=lambda x: x.lower())]

    def set_valores(self, valores):
        claves = {k for k, _, _ in valores}
        todos_antes = not self._valores or self._marcados >= {k for k, _, _ in self._valores}
        self._valores = valores
        if todos_antes:
            self._marcados = set(claves)
        else:
            previos = self._marcados
            self._marcados = previos & claves
            if previos and not self._marcados and claves:
                self._marcados = set(claves)
        self._actualizar()

    def seleccion(self):
        """None si están todos marcados; si no, el conjunto de claves."""
        if not self._valores or len(self._marcados) == len(self._valores):
            return None
        return set(self._marcados)

    def limpiar(self):
        self._marcados = {k for k, _, _ in self._valores}
        self._actualizar()

    def _resumen(self):
        sel = self.seleccion()
        if sel is None:
            return "Todos"
        if len(sel) == 1:
            k = next(iter(sel))
            return next((e for c, e, _ in self._valores if c == k), k)
        return f"{len(sel)} de {len(self._valores)}"

    def _actualizar(self):
        activo = self.seleccion() is not None
        self.setText(f"{self._titulo}: {self._resumen()}  ▾" if activo else f"{self._titulo}  ▾")
        self.setStyleSheet(self._ESTILO.format(
            bg="#E8F0FE" if activo else "#F7F9FC", fg="#1F6FEB" if activo else "#0F1B33",
            borde="#1F6FEB" if activo else "#E3E8F0"))

    def _al_cambiar(self, marcados):
        self._marcados = set(marcados)
        self._actualizar()
        self.cambiado.emit()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self.rect().contains(e.position().toPoint()) and self._valores:
            self._abrir()

    def _abrir(self):
        popup = PopupFiltroValores(self._titulo, self._valores, self._marcados, self._al_cambiar)
        popup.setFixedWidth(max(self.width(), 260) + 28)
        popup.adjustSize()
        origen = self.mapToGlobal(self.rect().bottomLeft())
        popup.move(origen.x() - 14, origen.y() - 6)
        self._popup = popup
        popup.show()
        popup.buscador.setFocus()


class FiltroRangoFechaBoton(QFrame):
    """Filtro por rango de fechas en una fila: la píldora con el título, el
    selector Desde, el selector Hasta y una X para quitar el filtro. Cada fecha es
    opcional. `rango()` es None cuando no filtra; si no, (desde, hasta) como date
    o None en el lado abierto. Los selectores van en línea (no dentro de una
    tarjeta flotante) porque un calendario no se puede abrir desde otro popup."""
    cambiado = pyqtSignal()

    def __init__(self, titulo, parent=None):
        super().__init__(parent)
        self._desde = None
        self._hasta = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._titulo = QLabel(titulo)
        lay.addWidget(self._titulo)
        self._selectores = {}
        for clave, texto in (('desde', "Desde"), ('hasta', "Hasta")):
            selector = SelectorFecha(QDate.currentDate())
            selector.setVacio(True, texto)
            selector.fechaElegida.connect(lambda f, c=clave: self._elegir(c, f))
            lay.addWidget(selector)
            self._selectores[clave] = selector
        self._quitar = QPushButton("\u2715")
        self._quitar.setFixedSize(26, 26)
        self._quitar.setToolTip("Quitar fechas")
        self._quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._quitar.setStyleSheet("QPushButton { border: none; border-radius: 13px; background: transparent; color: #66748D; "
                                   "font-size: 12px; font-weight: bold; } QPushButton:hover { background: #E3E8F0; }")
        self._quitar.clicked.connect(self.limpiar)
        lay.addWidget(self._quitar)
        lay.addStretch()
        self._actualizar()

    def rango(self):
        if self._desde is None and self._hasta is None:
            return None
        return (self._desde.toPyDate() if self._desde else None, self._hasta.toPyDate() if self._hasta else None)

    def limpiar(self):
        habia = self.rango() is not None
        self._desde = self._hasta = None
        for clave, texto in (('desde', "Desde"), ('hasta', "Hasta")):
            self._selectores[clave].setVacio(True, texto)
        self._actualizar()
        if habia:
            self.cambiado.emit()

    def _elegir(self, clave, fecha):
        if clave == 'desde':
            self._desde = fecha
        else:
            self._hasta = fecha
        self._actualizar()
        self.cambiado.emit()

    def _actualizar(self):
        activo = self.rango() is not None
        self._quitar.setVisible(activo)
        self._titulo.setStyleSheet(FiltroValoresBoton._ESTILO.format(
            bg="#E8F0FE" if activo else "#F7F9FC", fg="#1F6FEB" if activo else "#0F1B33",
            borde="#1F6FEB" if activo else "#E3E8F0").replace("QPushButton", "QLabel").replace("text-align: left; ", "")
            .replace("padding: 4px 8px", "padding: 5px 12px"))


class _ChipCopiaLista(CopyableLabel):
    """Chip del encabezado de la ficha de flota. Con un solo valor lo copia al hacer clic; con varios
    (flota de varios clientes) abre una lista, copia el elegido y vuelve a su estado normal."""

    _QSS_MENU = (f"QMenu {{ background-color: white; border: 1px solid {LINEA_AZUL}; border-radius: 10px; padding: 4px; }} "
                 f"QMenu::item {{ color: {TEXT_PRIMARY}; font-size: 12px; padding: 7px 16px; border-radius: 7px; }} "
                 f"QMenu::item:selected {{ background-color: {TINTE_CLARO}; color: {AZUL}; }}")

    def __init__(self, parent=None):
        super().__init__("", parent)
        self._opciones = []
        self._copy_value = None
        self._base = f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; padding: 3px 10px; " \
                     "border: 1px solid rgba(255,255,255,0.28); border-radius: 9px; background-color: rgba(255,255,255,0.08);"
        self._BASE_STYLE = self._base
        self._HOVER_STYLE = (f"color: {AZUL}; font-size: 11px; padding: 3px 10px; "
                             "border: 1px solid white; border-radius: 9px; background-color: white;")
        self._COPIADO_STYLE = ("color: #065F46; font-size: 11px; padding: 3px 10px; font-weight: bold; "
                               "border: 1px solid #6EE7B7; border-radius: 9px; background-color: #D1FAE5;")
        self.setStyleSheet(self._base)

    def set_opciones(self, texto, opciones, texto_vacio):
        """`opciones`: [(texto del menú, valor a copiar, detalle)]; sin opciones el chip no copia nada."""
        self._restaurar_texto()
        self._opciones = list(opciones)
        self._titulo_lista = texto.replace("Copiar ", "Copiar: ", 1) if texto.startswith("Copiar ") else texto
        if not self._opciones:
            self._copy_value = None
            self.setText(texto_vacio)
            self.setToolTip("Sin dato")
        elif len(self._opciones) == 1:
            self._copy_value = str(self._opciones[0][1])
            self.setText(texto)
            self.setToolTip(f"Clic para copiar: {self._copy_value}")
        else:
            self._copy_value = None
            self.setText(f"{texto}  ▾")
            self.setToolTip("Elige cuál copiar")

    def _abrir_lista(self):
        """Tarjeta flotante igual a la de los selectores de la app: cada opción con su nombre y, debajo, el detalle."""
        from src.ui.compartido.comercial_estilo import _PopupSelector, ubicar_popup_selector
        popup = _PopupSelector(self._titulo_lista, self._copiar_elegido)
        lista = popup.lista
        for titulo, valor, detalle in self._opciones:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(valor))
            item.setData(Qt.ItemDataRole.AccessibleTextRole, f"{titulo} {detalle}")
            item.setSizeHint(QSize(0, 50 if detalle else 38))
            lista.addItem(item)
            contenido = QLabel(f"<b>{html.escape(str(titulo))}</b>" + (
                f"<br><span style='color:#66748D; font-size:11px; font-weight:400;'>{html.escape(str(detalle))}</span>"
                if detalle else ""))
            contenido.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            contenido.setStyleSheet("background: transparent; border: none; color: #1B2B4E; font-size: 13px; padding-left: 12px;")
            lista.setItemWidget(item, contenido)
        lista.setFixedHeight(min(sum(lista.item(i).sizeHint().height() + 2 for i in range(lista.count())), 340) + 4)
        fuente = QFont(self.font())
        fuente.setPixelSize(13)
        fuente.setBold(True)
        mas_largo = max((QFontMetrics(fuente).horizontalAdvance(str(t)) for t, _v, _d in self._opciones), default=0)
        popup.setFixedWidth(min(max(self.width() + 60, 360, mas_largo + 80), 700))
        ubicar_popup_selector(popup, self)
        self._popup = popup
        popup.show()

    def _copiar_elegido(self, valor):
        self._copy_value = valor
        self._copiar_valor()
        self._copy_value = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and len(self._opciones) > 1:
            self._abrir_lista()
            return
        super().mousePressEvent(event)
