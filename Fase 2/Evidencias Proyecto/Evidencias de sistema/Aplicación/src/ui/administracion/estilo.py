"""Piezas visuales compartidas por las pantallas de Administración (Historial,
Instalaciones, Contactos y Ejecutivos): las mismas de la bandeja de Comercial
-- fila de tarjetas KPI, sub-pestañas con contador, barra azul de opciones
separada de la tarjeta de la tabla y botones de cápsula. Solo apariencia; la
lógica de cada pantalla sigue en su módulo."""
import weakref
from types import SimpleNamespace

from PyQt6.QtCore import Qt, QTimer, QRectF, QThread, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QTabBar, QTabWidget,
                             QAbstractItemView, QHeaderView, QApplication, QSizePolicy)

from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.icono_tema import fijar_icono_tema
from src.ui.compartido.transiciones import TransicionFundidoSubida, capturar
from src.ui.ingresos.base import PantallaIngresosBase, aplicar_estilo_tabla_lectura, estilo_combo_barra
from src.theme.colors import FONDO_APP, BORDE_CAJA
from src.theme.theme_manager import ThemeManager

_QSS_BARRA = "QFrame#barraAdmin { background-color: #1B2B4E; border: none; border-radius: 14px; }"
_QSS_CAPSULA = "QFrame { background: rgba(255,255,255,0.08); border-radius: 14px; }"


def raiz_pantalla(widget, con_fondo=True):
    """Fuente, fondo gris de la aplicación (el mismo de Clientes y Flota) y
    márgenes de una pantalla de Administración; devuelve su layout."""
    estilo = estilo_com.QSS_FUENTE_MODULO
    if con_fondo:
        widget.setObjectName("moduloAdmin")
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        estilo += f"QWidget#moduloAdmin {{ background-color: {FONDO_APP}; }}"
    widget.setStyleSheet(estilo)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(15, 15, 15, 15)
    layout.setSpacing(0 if con_fondo else 12)
    return layout


def fila_kpis(cantidad):
    """Contenedor con `cantidad` tarjetas informativas (no filtran). Devuelve
    (contenedor, [tarjetas]); se rellenan con `tarjeta.definir(...)` y
    `tarjeta.actualizar(valor, fraccion, pie)`."""
    contenedor = QWidget()
    fila = QHBoxLayout(contenedor)
    fila.setContentsMargins(0, 4, 0, 0)
    fila.setSpacing(12)
    tarjetas = []
    for _ in range(cantidad):
        tarjeta = estilo_com.TarjetaKpiResumen()
        tarjeta.setCheckable(False)
        tarjeta.setCursor(Qt.CursorShape.ArrowCursor)
        politica = tarjeta.sizePolicy()
        politica.setRetainSizeWhenHidden(True)
        tarjeta.setSizePolicy(politica)
        tarjetas.append(tarjeta)
        fila.addWidget(tarjeta, stretch=1)
    return contenedor, tarjetas


MARGEN_BARRA_HOJA = (16, 0, 16, 0)
_QSS_BARRA_HOJA = (f"QFrame#barraAdmin {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {BORDE_CAJA}; "
                   f"border-top: none; border-radius: 0px; }}")


def _grupo_hoja():
    """Cápsula azul de botones sin encabezado, para la barra clara; queda oculta hasta tener botones."""
    capsula = QFrame()
    capsula.setStyleSheet("QFrame { background: #1B2B4E; border-radius: 14px; }")
    lay = QHBoxLayout(capsula)
    lay.setContentsMargins(4, 3, 4, 3)
    lay.setSpacing(4)
    capsula.hide()
    return capsula, lay


def barra_opciones(icono, titulo, subtitulo="", mostrar_titulo=True, con_grupos=True, hoja=False, subpestanas=None):
    """Barra azul con ícono, título y subtítulo a la izquierda, una zona para
    filtros y la cápsula de botones a la derecha. Con `mostrar_titulo=False`
    la zona de filtros ocupa el lugar del ícono y el título. Con `hoja=True` es
    la fila clara de la hoja blanca de Administración: `subpestanas` (si hay)
    a la izquierda, el resumen, los filtros y las cápsulas a la derecha."""
    marco = QFrame()
    marco.setObjectName("barraAdmin")
    marco.setStyleSheet(_QSS_BARRA_HOJA if hoja else _QSS_BARRA)
    if hoja:
        marco.setMinimumHeight(56)
    fila = QHBoxLayout(marco)
    fila.setContentsMargins(*(MARGEN_BARRA_HOJA if hoja else (15, 7, 15, 7)))
    fila.setSpacing(12 if hoja else 8)

    lbl_titulo = QLabel(titulo)
    lbl_titulo.setStyleSheet(
        f"color: {estilo_com.TINTA if hoja else 'white'}; font-size: 15px; font-weight: 800; background: transparent;")
    lbl_subtitulo = QLabel(subtitulo)
    lbl_subtitulo.setStyleSheet(
        f"color: {estilo_com.APAGADO if hoja else '#B8C2D6'}; font-size: 11px; font-weight: 600; background: transparent;")
    bloque = QWidget()
    lay_bloque = QVBoxLayout(bloque)
    lay_bloque.setContentsMargins(0, 0, 0, 0)
    lay_bloque.setSpacing(0)
    lay_bloque.addWidget(lbl_titulo)
    lay_bloque.addWidget(lbl_subtitulo)
    if hoja and subpestanas is not None:
        lbl_titulo.hide()
        subpestanas.setStyleSheet("QFrame#contenedorSubpestanasComercial { background: transparent; border: none; }")

    zona_filtros = QHBoxLayout()
    zona_filtros.setSpacing(8)
    if hoja:
        grupo_filtros, lay_filtros = _grupo_hoja()
        grupo_acciones, lay_capsula = _grupo_hoja()
        grupo_generales, lay_generales = _grupo_hoja()
        grupos = {'filtros': (grupo_filtros, lay_filtros), 'acciones': (grupo_acciones, lay_capsula),
                  'generales': (grupo_generales, lay_generales)}
        widgets_derecha = (grupo_filtros, grupo_acciones, grupo_generales)
    elif con_grupos:
        # Tres grupos con encabezado; cada uno aparece al recibir su primer botón
        grupo_filtros, lay_filtros = PantallaIngresosBase._crear_grupo_barra("Filtros")
        grupo_acciones, lay_capsula = PantallaIngresosBase._crear_grupo_barra("Acciones")
        grupo_generales, lay_generales = PantallaIngresosBase._crear_grupo_barra("Generales")
        grupos = {'filtros': (grupo_filtros, lay_filtros), 'acciones': (grupo_acciones, lay_capsula),
                  'generales': (grupo_generales, lay_generales)}
        widgets_derecha = (grupo_filtros, grupo_acciones, grupo_generales)
    else:
        capsula = QFrame()
        capsula.setStyleSheet(_QSS_CAPSULA)
        lay_capsula = QHBoxLayout(capsula)
        lay_capsula.setContentsMargins(5, 5, 5, 5)
        lay_capsula.setSpacing(4)
        grupos = {}
        widgets_derecha = (capsula,)

    if mostrar_titulo:
        if hoja and subpestanas is not None:
            fila.addWidget(subpestanas)
        fila.addWidget(bloque)
        fila.addStretch()
        fila.addLayout(zona_filtros)
    else:
        bloque.setParent(marco)
        bloque.hide()
        fila.addLayout(zona_filtros, 1)
    for widget in widgets_derecha:
        fila.addWidget(widget)
    return SimpleNamespace(marco=marco, lbl_titulo=lbl_titulo, lbl_subtitulo=lbl_subtitulo,
                           zona_filtros=zona_filtros, lay_capsula=lay_capsula, grupos=grupos)


def boton_capsula(barra, icono, tooltip, boton=None, grupo='acciones'):
    """Convierte `boton` (o crea uno) en un botón de solo ícono dentro de la cápsula
    del grupo `grupo` ('filtros', 'acciones' o 'generales')."""
    boton = boton or QPushButton()
    boton.setText("")
    boton.setIcon(ThemeManager.icon(icono, color='white'))
    boton.setToolTip(tooltip)
    boton.setCursor(Qt.CursorShape.PointingHandCursor)
    boton.setFixedWidth(44)
    if barra.grupos:
        contenedor, lay = barra.grupos[grupo]
        lay.addWidget(boton)
        contenedor.show()
    else:
        barra.lay_capsula.addWidget(boton)
    estilo_com.preparar_boton_capsula(boton)
    return boton


_ESTILO_COMBO_CLARO = (
    f"QComboBox {{ background-color: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid #DCE3EC; "
    "border-radius: 10px; padding: 0 12px; min-height: 32px; font-weight: 600; font-size: 12px; }"
    "QComboBox:hover { border: 1px solid #B9C6DA; }"
    "QComboBox::drop-down { border: none; width: 22px; }"
    "QComboBox QAbstractItemView { background: white; color: #0F1B33; selection-background-color: #E8F0FE;"
    " selection-color: #0F1B33; outline: none; }")


def combo_barra(combo, ancho=190, claro=False):
    """Combo de la barra azul (o de la barra clara con `claro=True`) con la lista en tarjeta flotante."""
    combo.setStyleSheet(_ESTILO_COMBO_CLARO if claro else estilo_combo_barra())
    combo.setMinimumWidth(ancho)
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    return combo


def etiqueta_barra(texto, claro=False):
    lbl = QLabel(texto)
    color = estilo_com.APAGADO if claro else "#B8C2D6"
    lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; background: transparent;")
    return lbl


def tarjeta_contenido(nombre="tarjetaAdmin", hoja=False):
    """Tarjeta blanca de bordes redondeados que aloja la tabla. Devuelve (marco, layout).
    Con `hoja=True` queda pegada a la fila clara de arriba, con el borde de las cajas de Clientes y Flota."""
    marco = QFrame()
    marco.setObjectName(nombre)
    if hoja:
        marco.setStyleSheet(
            f"QFrame#{nombre} {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {BORDE_CAJA}; "
            "border-top: none; border-top-left-radius: 0px; border-top-right-radius: 0px; "
            "border-bottom-left-radius: 14px; border-bottom-right-radius: 14px; }")
    else:
        marco.setStyleSheet(estilo_com.qss_tarjeta(nombre))
    capas = QVBoxLayout(marco)
    capas.setContentsMargins(1, 0 if hoja else 1, 1, 1)
    capas.setSpacing(0)
    return marco, capas


def caja_con_encabezado(nombre, titulo, subtitulo=""):
    """Caja blanca con su propio encabezado azul (título y resumen). Devuelve un
    objeto con `marco`, `cuerpo` (layout para el contenido), `lbl_titulo`,
    `lbl_subtitulo` y `fila_cab` (layout del encabezado, para botones a la derecha)."""
    marco = QFrame()
    marco.setObjectName(nombre)
    marco.setStyleSheet(
        f"QFrame#{nombre} {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {BORDE_CAJA}; border-radius: 14px; }}")
    raiz = QVBoxLayout(marco)
    raiz.setContentsMargins(1, 1, 1, 1)
    raiz.setSpacing(0)
    cab = QFrame()
    cab.setObjectName(nombre + "Cab")
    cab.setStyleSheet(
        f"QFrame#{nombre}Cab {{ background-color: #1B2B4E; border: none; "
        "border-top-left-radius: 13px; border-top-right-radius: 13px; }")
    fila = QHBoxLayout(cab)
    fila.setContentsMargins(16, 10, 16, 10)
    texto = QVBoxLayout()
    texto.setSpacing(0)
    lbl_titulo = QLabel(titulo)
    lbl_titulo.setStyleSheet("color: white; font-size: 14px; font-weight: 800; background: transparent;")
    lbl_subtitulo = QLabel(subtitulo)
    lbl_subtitulo.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
    texto.addWidget(lbl_titulo)
    texto.addWidget(lbl_subtitulo)
    fila.addLayout(texto)
    fila.addStretch()
    raiz.addWidget(cab)
    cuerpo = QVBoxLayout()
    cuerpo.setContentsMargins(0, 0, 0, 0)
    cuerpo.setSpacing(0)
    raiz.addLayout(cuerpo, 1)
    marco._encabezado = cab
    marco.setProperty("cajaAdmin", True)
    return SimpleNamespace(marco=marco, cuerpo=cuerpo, lbl_titulo=lbl_titulo, lbl_subtitulo=lbl_subtitulo, fila_cab=fila)


def fijar_badge(badge, n):
    """Contador en píldora de las listas de secciones."""
    badge.setText(str(n))
    badge.setFixedSize(max(30, badge.fontMetrics().horizontalAdvance(str(n)) + 18), 20)


def boton_seccion(nombre, icono=None):
    """Botón de una lista de secciones (ícono, nombre y contador a la derecha). Devuelve (botón, contador)."""
    boton = QPushButton()
    boton.setCheckable(True)
    boton.setCursor(Qt.CursorShape.PointingHandCursor)
    boton.setMinimumHeight(40)
    boton.setStyleSheet(
        "QPushButton { background: #1B2B4E; border: 1px solid #1B2B4E; border-radius: 10px; text-align: left; }"
        "QPushButton:hover { background: #2C4A80; border: 1px solid #2C4A80; }"
        "QPushButton:checked { background: #2C4A80; border: 1px solid #6F93D6; }")
    fila = QHBoxLayout(boton)
    fila.setContentsMargins(10, 0, 10, 0)
    fila.setSpacing(8)
    lbl = QLabel(nombre)
    lbl.setWordWrap(True)
    lbl.setStyleSheet("color: white; font-size: 12px; font-weight: 700; background: transparent; border: none;")
    badge = QLabel("0")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setStyleSheet("background-color: rgba(255,255,255,0.18); color: white; "
                        "border-radius: 10px; font-size: 11px; font-weight: bold;")
    for w in (lbl, badge):
        w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    if icono:
        lbl_icono = QLabel()
        lbl_icono.setPixmap(ThemeManager.icon(icono, color="white").pixmap(16, 16))
        lbl_icono.setStyleSheet("background: transparent; border: none;")
        lbl_icono.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        fila.addWidget(lbl_icono)
    fila.addWidget(lbl, 1)
    fila.addWidget(badge)
    return boton, badge


def bloque_caja(titulo):
    """Bloque con título en mayúsculas, separado por una línea del anterior."""
    bloque = QWidget()
    bloque.setObjectName("bloqueCaja")
    bloque.setStyleSheet(f"QWidget#bloqueCaja {{ background: transparent; border-top: 1px solid {estilo_com.LINEA}; }}")
    lay = QVBoxLayout(bloque)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(6)
    lbl = QLabel(titulo.upper())
    lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 10px; font-weight: 800; letter-spacing: 1px; "
                      "background: transparent; border: none;")
    lay.addWidget(lbl)
    return bloque


def etiqueta_caja(texto):
    lbl = QLabel(texto)
    lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; font-weight: 700; background: transparent; border: none;")
    return lbl


def boton_chip(texto):
    """Botón de opción corta (el elegido queda azul oscuro); varios forman una fila de rangos."""
    boton = QPushButton(texto)
    boton.setCheckable(True)
    boton.setCursor(Qt.CursorShape.PointingHandCursor)
    boton.setStyleSheet(
        f"QPushButton {{ background: #EEF2F6; color: {estilo_com.APAGADO}; border: none; border-radius: 9px; "
        "padding: 6px 4px; font-size: 12px; font-weight: 600; }"
        "QPushButton:hover { background: #E1E7F0; }"
        "QPushButton:checked { background: #1B2B4E; color: white; }")
    return boton


def boton_accion(texto, icono, peligro=False):
    """Botón ancho con ícono y nombre; `peligro` lo deja con borde y texto rojos."""
    fondo, hover = ("#B3261E", "#961F18") if peligro else ("#1B2B4E", "#2C4A80")
    boton = QPushButton("  " + texto)
    boton.setIcon(ThemeManager.icon(icono, color="white"))
    boton.setCursor(Qt.CursorShape.PointingHandCursor)
    boton.setStyleSheet(
        f"QPushButton {{ background: {fondo}; color: white; border: none; "
        "border-radius: 10px; padding: 0 12px; min-height: 34px; font-weight: 700; font-size: 12px; text-align: left; }"
        f"QPushButton:hover {{ background: {hover}; }}"
        "QPushButton:disabled { background: #A9B3C4; color: white; }")
    return boton


# ---------------------------------------------------- caja de detalle (derecha)
QSS_CAMPOS_DETALLE = (
    f"QLineEdit {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid #DCE3EC; "
    "border-radius: 10px; padding: 0 12px; min-height: 34px; font-size: 12px; font-weight: 600; }"
    "QLineEdit:focus { border: 1px solid #1B2B4E; }"
    "QLineEdit:read-only { background: #F1F5F9; color: #64748B; }"
    "QLineEdit[error=\"true\"] { border: 1px solid #E04848; background: #FEF2F2; }")


def rotulo_campo(texto):
    """Rótulo de un campo de la caja de detalle: mayúsculas pequeñas."""
    lbl = QLabel(str(texto).upper())
    lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 10px; font-weight: 800; letter-spacing: 1px; "
                      "background: transparent; border: none;")
    return lbl


def nombre_detalle(texto=""):
    """Nombre grande de lo seleccionado, arriba del contenido de la caja de detalle."""
    lbl = QLabel(texto)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 15px; font-weight: 800; background: transparent; border: none;")
    return lbl


def estado_vacio():
    """Cartel de una caja de detalle sin selección: círculo con ícono, título y una línea. Devuelve
    (página, mostrar), con mostrar(icono, titulo, detalle); el ícono sigue el tema."""
    pagina = QWidget()
    lay_pagina = QVBoxLayout(pagina)
    lay_pagina.setContentsMargins(12, 12, 12, 12)
    marco = QFrame()
    marco.setObjectName("estadoVacioDetalle")
    marco.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    marco.setStyleSheet("QFrame#estadoVacioDetalle { background-color: #F3F5F9; border: 1px dashed #B5C2DB; border-radius: 16px; }"
                        "QFrame#estadoVacioDetalle QLabel { background: transparent; border: none; }")
    lay = QVBoxLayout(marco)
    lay.setContentsMargins(20, 24, 20, 24)
    lay.setSpacing(10)
    icono = QLabel()
    icono.setFixedSize(76, 76)
    icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icono.setStyleSheet("background: #E3E9F4; border: 2px dashed #B5C2DB; border-radius: 38px;")
    titulo = QLabel()
    titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    titulo.setWordWrap(True)
    titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 15px; font-weight: 800;")
    detalle = QLabel()
    detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
    detalle.setWordWrap(True)
    detalle.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px;")
    lay.addStretch(1)
    lay.addWidget(icono, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addSpacing(4)
    lay.addWidget(titulo)
    lay.addWidget(detalle)
    lay.addStretch(2)
    lay_pagina.addWidget(marco)

    def mostrar(nombre_icono, texto_titulo, texto_detalle):
        fijar_icono_tema(icono, nombre_icono, "#1B2B4E", 30)
        titulo.setText(texto_titulo)
        detalle.setText(texto_detalle)
    return pagina, mostrar


def crear_pie():
    """Franja de botones al pie de la caja de detalle. Devuelve (marco, layout)."""
    pie = QFrame()
    pie.setStyleSheet(f"QFrame {{ background: {estilo_com.SUPERFICIE_2}; border: none; border-top: 1px solid {estilo_com.LINEA}; }}")
    lay = QVBoxLayout(pie)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(6)
    return pie, lay


def boton_pie(texto, variante="primario", icono=None):
    """Botón ancho del pie de la caja de detalle: `primario` (azul oscuro), `peligro` (rojo) o `secundario` (contorno)."""
    if variante == "secundario":
        estilo = (f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
                  "border-radius: 10px; padding: 0 12px; min-height: 34px; font-weight: 700; font-size: 12px; }"
                  "QPushButton:hover { background: #F1F4F9; }")
        color_icono = estilo_com.TINTA
    else:
        fondo, hover = ("#B3261E", "#961F18") if variante == "peligro" else ("#1B2B4E", "#2C4A80")
        estilo = (f"QPushButton {{ background: {fondo}; color: white; border: none; border-radius: 10px; "
                  "padding: 0 12px; min-height: 34px; font-weight: 700; font-size: 12px; }"
                  f"QPushButton:hover {{ background: {hover}; }}"
                  "QPushButton:disabled { background: #A9B3C4; color: white; }")
        color_icono = "white"
    boton = QPushButton(("  " + texto) if icono else texto)
    if icono:
        boton.setIcon(ThemeManager.icon(icono, color=color_icono))
    boton.setCursor(Qt.CursorShape.PointingHandCursor)
    boton.setStyleSheet(estilo)
    return boton


class PastillaAviso(QWidget):
    """Pastilla redondeada ámbar con un ícono de alerta y una cantidad, para el borde de una pestaña."""
    ALTO = 20
    MARGEN = 8

    def __init__(self, cantidad, parent=None):
        super().__init__(parent)
        self._texto = str(cantidad)
        self._icono = ThemeManager.icon('fa5s.exclamation-circle', color='#1B2B4E').pixmap(13, 13)
        fuente = QFont(self.font())
        fuente.setPixelSize(11)
        fuente.setWeight(QFont.Weight.ExtraBold)
        self.setFont(fuente)
        ancho_texto = self.fontMetrics().horizontalAdvance(self._texto)
        self._ancho_pastilla = 10 + 13 + 4 + ancho_texto + 10
        self.setFixedSize(self._ancho_pastilla + self.MARGEN, self.ALTO)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        zona = QRectF(0, 0, self._ancho_pastilla, self.ALTO)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FBBF24"))
        p.drawRoundedRect(zona, self.ALTO / 2, self.ALTO / 2)
        p.drawPixmap(10, (self.ALTO - 13) // 2, self._icono)
        p.setPen(QColor("#1B2B4E"))
        p.setFont(self.font())
        p.drawText(QRectF(10 + 13 + 4, 0, self._ancho_pastilla - 27 - 10, self.ALTO), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self._texto)


class _CalculoAvisosClientes(QThread):
    """Calcula en segundo plano cuántos clientes hay por revisar (ver EncabezadoAdministracion)."""
    listo = pyqtSignal(int, str)

    def __init__(self, comercial):
        super().__init__()
        self._comercial = comercial

    def run(self):
        try:
            from src.services.comercial_services import contratos_actuales
            from src.ui.administracion.clientes import armar_resumen_de, mascaras_casos
            df, _cdbs, _flota = armar_resumen_de(self._comercial, contratos_actuales(self._comercial).copy())
            razones, cdbs, sin_rut, varios_rut = mascaras_casos(df)
            n = int((razones | cdbs | sin_rut | varios_rut).sum())
            detalle = (f"{n} clientes por revisar: {int(razones.sum())} con varias razones, {int(cdbs.sum())} con varios CDB, "
                       f"{int(sin_rut.sum())} sin RUT, {int(varios_rut.sum())} con varios RUT")
        except Exception:
            return
        self.listo.emit(n, detalle)


class EncabezadoAdministracion(QFrame):
    """Panel azul con el título de Administración y las pestañas de sus pantallas,
    pegado a la hoja blanca. Maneja un QTabWidget cuya barra propia queda oculta
    (misma interfaz que SelectorSubpestanas)."""

    # Cada pantalla de Administración arma su propio encabezado: el aviso de Clientes se calcula una sola vez
    # y se comparte, así una pestaña recién armada ya lo muestra al nacer
    _aviso_clientes = (0, "")
    _vivos = weakref.WeakSet()
    _conectado = False
    _temporizador_avisos = None

    def __init__(self, tabs, titulo, subtitulo, parent=None, separado=False, subtitulos=None, titulo_grande=False, compacto=False):
        super().__init__(parent)
        self._tabs = tabs
        self._compacto = compacto
        self._subtitulos = subtitulos or {}
        self._subtitulo_base = subtitulo
        self.setObjectName("encabezadoAdmin")
        radio_inferior = 14 if separado else 0
        self.setStyleSheet(
            "QFrame#encabezadoAdmin { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1B2B4E, stop:1 #2C4A80); "
            f"border: none; border-top-left-radius: 14px; border-top-right-radius: 14px; "
            f"border-bottom-left-radius: {radio_inferior}px; border-bottom-right-radius: {radio_inferior}px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 8 if compacto else 14, 20, 0)
        lay.setSpacing(0)
        lbl_titulo = QLabel(titulo)
        tam_titulo = 24 if titulo_grande else 20
        lbl_titulo.setStyleSheet(f"color: white; font-size: {tam_titulo}px; font-weight: 800; background: transparent;")
        self._lbl_sub = QLabel(subtitulo)
        self._lbl_sub.setStyleSheet("color: #C9D3E6; font-size: 12px; background: transparent;")
        self._lbl_titulo = lbl_titulo
        if not compacto:
            lay.addWidget(lbl_titulo)
            lay.addWidget(self._lbl_sub)
            lay.addSpacing(10)
        from src.ui.compartido.barra_pestanas import BarraPestanas
        self._barra = BarraPestanas()
        for i in range(tabs.count()):
            self._barra.addTab(tabs.tabText(i))
        self._barra.setExpanding(False)
        self._barra.setDrawBase(False)
        self._barra.setCursor(Qt.CursorShape.PointingHandCursor)
        # Sin flechas de desplazamiento: si las pestañas no caben, se compactan (ver resizeEvent)
        self._barra.setUsesScrollButtons(False)
        self._barra.setMinimumWidth(0)
        self._compacta = None
        self._ancho_normal = None
        self._estilo_barra(False)
        fila = QHBoxLayout()
        fila.setContentsMargins(0, 0, 0, 0)
        if compacto:
            # Título y pestañas en una sola fila; el subtítulo queda como globo del título
            self._lbl_sub.hide()
            self._fila = fila
            fila.setSpacing(26)
            fila.addWidget(lbl_titulo, 0, Qt.AlignmentFlag.AlignVCenter)
        fila.addWidget(self._barra, 0, Qt.AlignmentFlag.AlignBottom)
        fila.addStretch()
        lay.addLayout(fila)
        self.tabBarClicked = self._barra.tabBarClicked
        self._barra.currentChanged.connect(tabs.setCurrentIndex)
        tabs.currentChanged.connect(self._sincronizar)
        self._sincronizar(tabs.currentIndex())
        if any(self._barra.tabText(i) == "Clientes" for i in range(self._barra.count())):
            EncabezadoAdministracion._vivos.add(self)
            self.poner_aviso_pestana("Clientes", *EncabezadoAdministracion._aviso_clientes)
            EncabezadoAdministracion._preparar_avisos()

    def _estilo_barra(self, compacta):
        if compacta == self._compacta:
            return
        self._compacta = compacta
        relleno, margen, letra = ("9px 10px", 2, 12) if compacta else ("9px 18px", 4, 13)
        self._barra.setStyleSheet(
            "QTabBar { background: transparent; }"
            f"QTabBar::tab {{ background: transparent; color: #C9D3E6; padding: {relleno}; margin-right: {margen}px; border: none; "
            f"border-top-left-radius: 10px; border-top-right-radius: 10px; font-weight: 600; font-size: {letra}px; }}"
            "QTabBar::tab:hover:!selected { color: white; background: rgba(255,255,255,0.08); }"
            f"QTabBar::tab:selected {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; }}")

    _ESTILO_BARRA_CAJA = (
        "QTabBar { background: transparent; }"
        "QTabBar::tab { background: transparent; color: #C9D3E6; padding: 7px 12px; margin-right: 4px; border: none; "
        "border-radius: 9px; font-weight: 600; font-size: 12px; }"
        "QTabBar::tab:hover:!selected { color: white; background: rgba(255,255,255,0.10); }"
        f"QTabBar::tab:selected {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; }}")

    def mover_a(self, layout):
        """Lleva el título y las pestañas a otro layout (la caja de filtros del Dashboard); el encabezado queda vacío."""
        layout.addWidget(self._lbl_titulo)
        layout.addWidget(self._barra)
        self._compacta = "caja"
        self._barra.setStyleSheet(self._ESTILO_BARRA_CAJA)

    def devolver(self):
        """Vuelve el título y las pestañas a la fila del encabezado."""
        self._fila.insertWidget(0, self._lbl_titulo, 0, Qt.AlignmentFlag.AlignVCenter)
        self._fila.insertWidget(1, self._barra, 0, Qt.AlignmentFlag.AlignBottom)
        self._compacta = None
        self._ancho_normal = None
        self._ajustar_barra()

    def _ajustar_barra(self):
        """Con poco ancho usa pestañas más angostas en vez de las flechas de desplazamiento."""
        if self._compacta == "caja":
            return
        if self._ancho_normal is None:
            self._estilo_barra(False)
            self._ancho_normal = self._barra.sizeHint().width()
        self._estilo_barra(self._ancho_normal > self.width() - 40)

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self._ajustar_barra()

    @staticmethod
    def _preparar_avisos():
        """Conecta una sola vez el recálculo del aviso a los cambios de datos y lo pide la primera vez."""
        if EncabezadoAdministracion._conectado:
            return
        EncabezadoAdministracion._conectado = True
        from src.core.data_manager import DataManager
        temporizador = QTimer(QApplication.instance())
        temporizador.setSingleShot(True)
        temporizador.setInterval(800)
        temporizador.timeout.connect(EncabezadoAdministracion._recalcular_avisos)
        EncabezadoAdministracion._temporizador_avisos = temporizador
        DataManager().data_ready.connect(temporizador.start)
        QTimer.singleShot(1500, EncabezadoAdministracion._recalcular_avisos)

    _hilo_avisos = None
    _avisos_pendientes = False

    @staticmethod
    def _recalcular_avisos():
        """Cantidad de clientes por revisar (varias razones, varios CDB, sin RUT o varios RUT) en todos los encabezados
        abiertos. El cálculo corre en un hilo; si llega otra carga mientras tanto, se repite al terminar."""
        previo = EncabezadoAdministracion._hilo_avisos
        if previo is not None and previo.isRunning():
            EncabezadoAdministracion._avisos_pendientes = True
            return
        try:
            from src.core.data_manager import DataManager
            from src.core.hilos import iniciar_hilo_retenido
            hilo = _CalculoAvisosClientes(DataManager().get_comercial_df())
        except Exception:
            return
        hilo.listo.connect(EncabezadoAdministracion._aplicar_avisos)
        EncabezadoAdministracion._hilo_avisos = hilo
        iniciar_hilo_retenido(hilo)

    @staticmethod
    def _aplicar_avisos(n, detalle):
        if EncabezadoAdministracion._avisos_pendientes:
            EncabezadoAdministracion._avisos_pendientes = False
            QTimer.singleShot(150, EncabezadoAdministracion._recalcular_avisos)
        EncabezadoAdministracion._aviso_clientes = (n, detalle)
        for encabezado in list(EncabezadoAdministracion._vivos):
            try:
                encabezado.poner_aviso_pestana("Clientes", n, detalle)
            except RuntimeError:
                EncabezadoAdministracion._vivos.discard(encabezado)

    def poner_aviso_pestana(self, nombre, cantidad, detalle=""):
        """Pastilla ámbar con un ícono y la cantidad a la derecha del nombre de la pestaña; sin casos, se quita."""
        for i in range(self._barra.count()):
            if self._barra.tabText(i) != nombre:
                continue
            previo = self._barra.tabButton(i, QTabBar.ButtonPosition.RightSide)
            if previo is not None:
                self._barra.setTabButton(i, QTabBar.ButtonPosition.RightSide, None)
                previo.deleteLater()
            if cantidad <= 0:
                self._barra.setTabToolTip(i, "")
                return
            pastilla = PastillaAviso(cantidad)
            pastilla.setToolTip(detalle)
            self._barra.setTabButton(i, QTabBar.ButtonPosition.RightSide, pastilla)
            self._barra.setTabToolTip(i, detalle)
            self._barra.updateGeometry()
            self._ancho_normal = None
            self._ajustar_barra()
            return

    def _sincronizar(self, indice):
        if self._subtitulos:
            self._lbl_sub.setText(self._subtitulos.get(self._tabs.tabText(indice), self._subtitulo_base))
            if self._compacto:
                self._lbl_titulo.setToolTip(self._lbl_sub.text())
        if indice != self._barra.currentIndex():
            self._barra.blockSignals(True)
            self._barra.setCurrentIndex(indice)
            self._barra.blockSignals(False)

    def sincronizar_estado(self):
        for i in range(self._tabs.count()):
            self._barra.setTabEnabled(i, self._tabs.isTabEnabled(i))
            self._barra.setTabToolTip(i, self._tabs.tabToolTip(i))


def subpestanas(nombres):
    """Barra de sub-pestañas con contador, como la de Comercial. Devuelve
    (contenedor, tabbar, badges); `actualizar_contador(tabbar, badges, i, n)`
    cambia el número."""
    tabbar = QTabBar()
    badges = []
    for i, nombre in enumerate(nombres):
        tabbar.addTab(nombre)
        badge = QLabel("0")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(34, 20)
        tabbar.setTabButton(i, QTabBar.ButtonPosition.RightSide, badge)
        badges.append(badge)

    def estilizar(*_):
        actual = tabbar.currentIndex()
        for i, badge in enumerate(badges):
            fondo, texto = ("#E3E8F0", "#1B2B4E") if i == actual else ("#EEF2F6", estilo_com.APAGADO)
            badge.setStyleSheet(
                f"background-color: {fondo}; color: {texto}; border-radius: 10px; "
                "padding: 0px 8px; font-size: 11px; font-weight: bold; min-width: 10px;")

    tabbar.currentChanged.connect(estilizar)
    estilizar()
    tabbar.setExpanding(False)
    tabbar.setDrawBase(False)
    tabbar.setStyleSheet(estilo_com.QSS_SUBPESTANAS + "QTabBar::tab { padding-right: 6px; } "
                         "QTabBar::tab:selected { color: #1B2B4E; border-bottom: 3px solid #1B2B4E; }")
    contenedor = QFrame()
    contenedor.setObjectName("contenedorSubpestanasComercial")
    contenedor.setStyleSheet(estilo_com.QSS_CONTENEDOR_SUBPESTANAS)
    fila = QHBoxLayout(contenedor)
    fila.setContentsMargins(0, 0, 0, 0)
    fila.addWidget(tabbar)
    fila.addStretch()
    return contenedor, tabbar, badges


def animar_subpestanas(modulo, tabbar):
    """Transición de fundido al cambiar de sub-pestaña: se anima el último
    bloque del layout del módulo (la tarjeta de la tabla), que es lo que se
    repinta con los datos de la sub-pestaña."""
    transicion = {}
    pendiente = {}

    def _contenedor():
        lay = modulo.layout()
        return lay.itemAt(lay.count() - 1).widget() if lay is not None and lay.count() else None

    def _antes(indice):
        pendiente.clear()
        contenedor = _contenedor()
        if contenedor is None or indice == tabbar.currentIndex() or not contenedor.isVisible():
            return
        if 't' not in transicion:
            transicion['t'] = TransicionFundidoSubida(modulo, contenedor)
            transicion['t'].DESPLAZAMIENTO_PX = 8
            transicion['t']._anim.setDuration(170)
        transicion['t'].terminar()
        pendiente[indice] = capturar(contenedor)

    def _despues(indice):
        foto = pendiente.pop(indice, None)
        pendiente.clear()
        if foto is not None:
            transicion['t'].iniciar(foto)

    tabbar.tabBarClicked.connect(_antes)
    tabbar.currentChanged.connect(_despues)


def actualizar_contador(tabbar, badges, indice, n):
    badge = badges[indice]
    if badge.text() == str(n):
        return
    badge.setText(str(n))
    badge.setFixedWidth(max(34, badge.fontMetrics().horizontalAdvance(str(n)) + 24))
    tabbar.setTabText(indice, tabbar.tabText(indice))


def enlazar_tabs(tabbar, tabs):
    """Usa `tabbar` como selector visible de un QTabWidget y oculta el nativo,
    manteniendo los dos sincronizados (el código existente sigue llamando a
    `tabs.setCurrentIndex`)."""
    tabs.tabBar().hide()
    tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
    tabbar.currentChanged.connect(tabs.setCurrentIndex)
    tabs.currentChanged.connect(tabbar.setCurrentIndex)
    tabbar.setCurrentIndex(tabs.currentIndex())


def fijar_columnas(tabla, anchos, estirada):
    """Anchos fijos que el usuario no puede cambiar; `estirada` toma el espacio sobrante,
    así la tabla nunca necesita scroll lateral. `anchos` es {nombre de columna: píxeles}."""
    tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    cab = tabla.horizontalHeader()
    cab.setStretchLastSection(False)
    modelo = tabla.model()
    for i in range(modelo.columnCount()):
        nombre = modelo.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        if nombre == estirada or nombre not in anchos:
            cab.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        else:
            cab.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            tabla.setColumnWidth(i, anchos[nombre])


def estilar_tabla(tabla, editable=False):
    """Tabla con el aspecto de la de Comercial. Conserva el `menu_type` que
    tuviera y, si `editable`, deja activa la edición de celdas."""
    menu = tabla.menu_type
    aplicar_estilo_tabla_lectura(tabla, 44)
    tabla.menu_type = menu
    if editable:
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
    delegado = estilo_com.DelegadoCeldasComercial([tabla, tabla.frozen_view])
    tabla.setItemDelegate(delegado)
    tabla.frozen_view.setItemDelegate(delegado)
    tabla._delegado_admin = delegado
    return tabla


def exportar_excel(widget, df, prefijo, depurar=False, resaltado=None, titulo=None):
    """Exporta `df` a Excel con el mismo diálogo y avance que las tablas, para
    las pantallas que muestran listas en vez de una tabla. Con `depurar` omite las
    columnas sin datos (ver ExportExcelThread)."""
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    en_curso = getattr(widget, '_export_excel_thread', None)
    if en_curso is not None and en_curso.isRunning():
        QMessageBox.information(widget, "Exportar", "Ya hay una exportación en curso. Espera a que termine.")
        return
    if df is None or df.empty:
        QMessageBox.warning(widget, "Exportar", "No hay datos visibles.")
        return
    ruta, _ = QFileDialog.getSaveFileName(widget, "Guardar Excel", f"{prefijo}.xlsx", "Archivos Excel (*.xlsx)")
    if not ruta:
        return
    from src.ui.compartido.exportacion import iniciar_exportacion
    iniciar_exportacion(widget, df, ruta, titulo=titulo or prefijo.replace("_", " "), depurar=depurar, resaltado=resaltado)


def pie_paginacion(btn_prev, lbl_page, btn_next):
    """Pie delgado con la paginación, dentro de la tarjeta de la tabla."""
    marco = QFrame()
    marco.setStyleSheet(f"QFrame {{ background: transparent; border-top: 1px solid {estilo_com.LINEA}; }}")
    fila = QHBoxLayout(marco)
    fila.setContentsMargins(12, 8, 12, 8)
    fila.setSpacing(12)
    for btn, icono in ((btn_prev, 'fa5s.chevron-left'), (btn_next, 'fa5s.chevron-right')):
        btn.setIcon(ThemeManager.icon(icono, color=estilo_com.APAGADO))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: {estilo_com.SUPERFICIE_2}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
            "border-radius: 10px; padding: 6px 14px; font-weight: 700; }"
            f"QPushButton:hover {{ background: {estilo_com.PRIMARIO_SUAVE}; }}"
            "QPushButton:disabled { color: #A9B3C4; }")
    lbl_page.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px; font-weight: 700; border: none;")
    fila.addStretch()
    fila.addWidget(btn_prev)
    fila.addWidget(lbl_page)
    fila.addWidget(btn_next)
    fila.addStretch()
    return marco
