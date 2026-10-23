"""Piezas visuales compartidas por las pantallas de Administración (Historial,
Instalaciones, Contactos y Ejecutivos): las mismas de la bandeja de Comercial
-- fila de tarjetas KPI, sub-pestañas con contador, barra azul de opciones
separada de la tarjeta de la tabla y botones de cápsula. Solo apariencia; la
lógica de cada pantalla sigue en su módulo."""
from types import SimpleNamespace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QTabBar, QTabWidget,
                             QAbstractItemView)

from src.ui import comercial_estilo as estilo_com
from src.ui.transiciones import TransicionFundidoSubida
from src.ui.ingresos_base import PantallaIngresosBase, aplicar_estilo_tabla_lectura, estilo_combo_barra
from src.theme.theme_manager import ThemeManager

_QSS_BARRA = "QFrame#barraAdmin { background-color: #1B2B4E; border: none; border-radius: 14px; }"
_QSS_CAPSULA = "QFrame { background: rgba(255,255,255,0.08); border-radius: 14px; }"


def raiz_pantalla(widget):
    """Fuente y márgenes de una pantalla de Administración; devuelve su layout."""
    widget.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(15, 15, 15, 15)
    layout.setSpacing(12)
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


def barra_opciones(icono, titulo, subtitulo="", mostrar_titulo=True, con_grupos=True):
    """Barra azul con ícono, título y subtítulo a la izquierda, una zona para
    filtros y la cápsula de botones a la derecha. Con `mostrar_titulo=False`
    la zona de filtros ocupa el lugar del ícono y el título."""
    marco = QFrame()
    marco.setObjectName("barraAdmin")
    marco.setStyleSheet(_QSS_BARRA)
    fila = QHBoxLayout(marco)
    fila.setContentsMargins(15, 7, 15, 7)
    fila.setSpacing(8)

    lbl_titulo = QLabel(titulo)
    lbl_titulo.setStyleSheet("color: white; font-size: 15px; font-weight: 800; background: transparent;")
    lbl_subtitulo = QLabel(subtitulo)
    lbl_subtitulo.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
    bloque = QWidget()
    lay_bloque = QVBoxLayout(bloque)
    lay_bloque.setContentsMargins(0, 0, 0, 0)
    lay_bloque.setSpacing(0)
    lay_bloque.addWidget(lbl_titulo)
    lay_bloque.addWidget(lbl_subtitulo)

    zona_filtros = QHBoxLayout()
    zona_filtros.setSpacing(8)
    if con_grupos:
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


def combo_barra(combo, ancho=190):
    """Combo de la barra azul con la lista en tarjeta flotante."""
    combo.setStyleSheet(estilo_combo_barra())
    combo.setMinimumWidth(ancho)
    combo.setCursor(Qt.CursorShape.PointingHandCursor)
    return combo


def etiqueta_barra(texto):
    lbl = QLabel(texto)
    lbl.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 700; background: transparent;")
    return lbl


def tarjeta_contenido(nombre="tarjetaAdmin"):
    """Tarjeta blanca de bordes redondeados que aloja la tabla. Devuelve (marco, layout)."""
    marco = QFrame()
    marco.setObjectName(nombre)
    marco.setStyleSheet(estilo_com.qss_tarjeta(nombre))
    capas = QVBoxLayout(marco)
    capas.setContentsMargins(1, 1, 1, 1)
    capas.setSpacing(0)
    return marco, capas


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
        pendiente[indice] = contenedor.grab()

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


def exportar_excel(widget, df, prefijo):
    """Exporta `df` a Excel con el mismo diálogo y avance que las tablas, para
    las pantallas que muestran listas en vez de una tabla."""
    from PyQt6.QtWidgets import QFileDialog, QMessageBox, QProgressDialog
    from src.ui.custom_table import ExportExcelThread

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
    progreso = QProgressDialog("Generando Excel...", "", 0, 100, widget)
    progreso.setWindowTitle("Exportando")
    progreso.setWindowModality(Qt.WindowModality.NonModal)
    progreso.setCancelButton(None)
    progreso.setMinimumDuration(0)
    progreso.setAutoClose(False)
    progreso.setValue(0)
    progreso.show()
    widget._export_excel_thread = ExportExcelThread(df, ruta, parent=widget)
    widget._export_excel_thread.progress_signal.connect(progreso.setValue)

    def _terminado(ok, ruta_final, error):
        progreso.close()
        if not ok:
            QMessageBox.critical(widget, "Error", error)

    widget._export_excel_thread.finished_signal.connect(_terminado)
    widget._export_excel_thread.start()


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
