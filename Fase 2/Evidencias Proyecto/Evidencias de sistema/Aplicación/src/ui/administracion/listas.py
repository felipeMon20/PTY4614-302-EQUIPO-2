"""Listas agrupadas y desplegables de Administración (Historial, Contactos).
Cada grupo arma su contenido recién al abrirse por primera vez, para que una
lista con miles de registros se abra al instante. Solo apariencia."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QScrollArea, QSizePolicy,
                             QMenu, QApplication)

from src.ui.compartido import comercial_estilo as estilo_com
from src.theme.theme_manager import ThemeManager
from src.theme.colors import SURFACE, BORDER, TEXT_SECONDARY
from src.ui.compartido.menu_contextual import crear_menu

TONOS = {
    "azul": ("#E8F0FE", "#1F6FEB"), "verde": ("#E3F6EE", "#0F9D6E"), "rojo": ("#FDECEC", "#E04848"),
    "ambar": ("#FEF3DC", "#D98404"), "violeta": ("#EFE9FC", "#7C4DDE"), "gris": ("#EDF0F6", "#66748D"),
}
_TRANSPARENTE = "background: transparent; border: none;"


def pildora(texto, tono="gris"):
    fondo, color = TONOS.get(tono, TONOS["gris"])
    lbl = QLabel(str(texto))
    lbl.setStyleSheet(f"background: {fondo}; color: {color}; border-radius: 10px; padding: 2px 10px; "
                      "font-size: 11px; font-weight: 700; border: none;")
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lbl


def texto(contenido, color=None, tam=12, negrita=False, seleccionable=False):
    lbl = QLabel(str(contenido))
    lbl.setStyleSheet(f"color: {color or estilo_com.TINTA}; font-size: {tam}px; "
                      f"font-weight: {'700' if negrita else '500'}; {_TRANSPARENTE}")
    if seleccionable:
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lbl


def plural(n, singular, plural_=None):
    return f"{n} {singular if n == 1 else (plural_ or singular + 's')}"


def avatar(iniciales, tono="azul"):
    fondo, color = TONOS.get(tono, TONOS["azul"])
    lbl = QLabel(iniciales)
    lbl.setFixedSize(34, 34)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(f"background: {fondo}; color: {color}; border-radius: 10px; font-size: 12px; font-weight: 800; border: none;")
    return lbl


class Colapsable(QFrame):
    """Cabecera clicable y cuerpo que se arma al primer despliegue. `nivel` 1
    es un grupo grande (fondo gris claro); `nivel` 2, una fila dentro de él."""

    def __init__(self, constructor=None, abierto=False, nivel=1, parent=None):
        super().__init__(parent)
        self._constructor = constructor
        self._cuerpo = None
        self._abierto = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        fondo = estilo_com.SUPERFICIE_2 if nivel == 1 else "transparent"
        self.cabecera = QPushButton()
        self.cabecera.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cabecera.setMinimumHeight(38 if nivel == 1 else 32)
        self.cabecera.setStyleSheet(
            f"QPushButton {{ background: {fondo}; border: none; border-top: 1px solid {estilo_com.LINEA_SUAVE}; text-align: left; }}"
            f"QPushButton:hover {{ background: {estilo_com.PRIMARIO_SUAVE}; }}")
        self._fila = QHBoxLayout(self.cabecera)
        self._fila.setContentsMargins(14 if nivel == 1 else 20, 2, 14, 2)
        self._fila.setSpacing(10)
        self._chevron = QLabel()
        self._chevron.setFixedWidth(14)
        self._chevron.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._chevron.setStyleSheet(_TRANSPARENTE)
        self._fila.addWidget(self._chevron)
        lay.addWidget(self.cabecera)
        self.cabecera.clicked.connect(self.alternar)
        self._pintar_chevron()
        self._fondo = fondo
        self._copiable = None
        self._marcada = False
        if abierto:
            self.alternar()

    def hacer_copiable(self, valor):
        """Clic derecho copia `valor` (por ejemplo el VIN); Ctrl+clic marca la
        fila para copiar varios a la vez."""
        valor = str(valor or "").strip()
        if not valor or valor == "-":
            return
        self._copiable = valor
        self.cabecera.setToolTip("Ctrl+clic para marcar varias filas; clic derecho para copiar el VIN")
        self.cabecera.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cabecera.customContextMenuRequested.connect(self._menu_copiar)
        self.cabecera.clicked.disconnect(self.alternar)
        self.cabecera.clicked.connect(self._al_clic)

    def _lista(self):
        padre = self.parentWidget()
        while padre is not None and not isinstance(padre, ListaAgrupada):
            padre = padre.parentWidget()
        return padre

    def _al_clic(self):
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
            self._marcar(not self._marcada)
        else:
            self.alternar()

    def _marcar(self, marcada):
        self._marcada = marcada
        fondo = estilo_com.PRIMARIO_SUAVE if marcada else self._fondo
        self.cabecera.setStyleSheet(
            f"QPushButton {{ background: {fondo}; border: none; border-top: 1px solid {estilo_com.LINEA_SUAVE}; text-align: left; }}"
            f"QPushButton:hover {{ background: {estilo_com.PRIMARIO_SUAVE}; }}")
        lista = self._lista()
        if lista is not None:
            if marcada and self not in lista.marcadas:
                lista.marcadas.append(self)
            elif not marcada and self in lista.marcadas:
                lista.marcadas.remove(self)

    def _menu_copiar(self, pos):
        lista = self._lista()
        marcadas = [f for f in (lista.marcadas if lista is not None else []) if f._copiable]
        usar_marcadas = self._marcada and len(marcadas) > 1
        valores = list(dict.fromkeys(f._copiable for f in marcadas)) if usar_marcadas else [self._copiable]
        menu = crear_menu(self.cabecera)
        copiar = menu.accion(f"Copiar VIN ({len(valores)})" if len(valores) > 1 else "Copiar VIN", 'fa5s.barcode')
        limpiar = menu.accion("Quitar marcas", 'fa5s.times') if marcadas else None
        elegido = menu.exec(self.cabecera.mapToGlobal(pos))
        if elegido is copiar:
            QApplication.clipboard().setText("\n".join(valores))
        elif limpiar is not None and elegido is limpiar:
            for f in list(marcadas):
                f._marcar(False)

    def agregar(self, widget, stretch=0):
        if not isinstance(widget, QPushButton):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._fila.addWidget(widget, stretch)

    def alternar(self):
        self._abierto = not self._abierto
        if self._abierto and self._cuerpo is None and self._constructor is not None:
            self._cuerpo = self._constructor()
            self.layout().addWidget(self._cuerpo)
        if self._cuerpo is not None:
            self._cuerpo.setVisible(self._abierto)
        self._pintar_chevron()

    def _pintar_chevron(self):
        icono = 'fa5s.chevron-down' if self._abierto else 'fa5s.chevron-right'
        self._chevron.setPixmap(ThemeManager.icon_pixmap(icono, color=estilo_com.APAGADO, size=10))


class ListaAgrupada(QScrollArea):
    """Columna desplazable de bloques apilados (días, flotas)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.marcadas = []
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        self.viewport().setAutoFillBackground(False)
        self._contenido = QWidget()
        self._contenido.setObjectName("listaAdmin")
        self._contenido.setStyleSheet("QWidget#listaAdmin { background: transparent; }")
        self._lay = QVBoxLayout(self._contenido)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._lay.addStretch(1)
        self.setWidget(self._contenido)

    def reiniciar(self):
        self.marcadas = []
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def agregar(self, widget):
        self._lay.insertWidget(self._lay.count() - 1, widget)

    def mostrar_vacio(self, mensaje):
        lbl = QLabel(mensaje)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setMinimumHeight(140)
        lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 13px; font-weight: 600; {_TRANSPARENTE}")
        self.agregar(lbl)

    def boton_pie(self, mensaje, accion):
        """Botón centrado al final de la lista (ej. «Mostrar más días»)."""
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        fila.setContentsMargins(0, 12, 0, 14)
        boton = QPushButton(mensaje)
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.setStyleSheet(
            f"QPushButton {{ background: {estilo_com.SUPERFICIE_2}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
            "border-radius: 10px; padding: 7px 18px; font-weight: 700; }"
            f"QPushButton:hover {{ background: {estilo_com.PRIMARIO_SUAVE}; }}")
        boton.clicked.connect(accion)
        fila.addStretch()
        fila.addWidget(boton)
        fila.addStretch()
        self.agregar(contenedor)
        return contenedor
