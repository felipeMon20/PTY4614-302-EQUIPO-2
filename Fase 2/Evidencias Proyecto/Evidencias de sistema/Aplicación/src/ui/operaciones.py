import os
from html import escape as html_escape
from datetime import datetime
import openpyxl
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QPushButton, QLineEdit, QHeaderView,
                             QAbstractItemView, QTabBar, QMessageBox, QDialog,
                             QListWidget, QListWidgetItem, QDialogButtonBox, QApplication,
                             QMenu, QWidgetAction, QFileDialog, QComboBox, QCompleter,
                             QGraphicsDropShadowEffect, QGridLayout, QScrollArea, QTableWidget, QTableWidgetItem)
from PyQt6.QtCore import (Qt, QSize, QThread, pyqtSignal, QStandardPaths, QEvent, QPoint, QRect,
                          QTimer, QPropertyAnimation, QEasingCurve, QUrl, QDate)
from PyQt6.QtGui import QKeySequence, QFontMetrics, QColor, QFont, QDesktopServices
from config.settings import REPORTE_NOTAS_VENTAS_URL
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.constants import (COL_VIN, COL_ESTADO_COMERCIAL, VALOR_ESTADO_COMERCIAL_BAJA,
                                VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA,
                                COL_RAZON_SOCIAL, COL_CDB_FLOTA, COL_RUT, COL_FLOTA_VC, COL_ID, COL_ESTADO_ACTIVACION,
                                COL_CDB)
from src.services import comercial_services, operaciones_services, contactos_service, ejecutivos_service
from src.ui.custom_table import VolvoTableWidget, PandasTableModel
from src.ui.contactos import AddContactoThread
from src.ui.contactos_agregar import ContactosAddDialog
from src.ui.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.dialogo_accion import DialogoAccion
from src.ui.selector_fecha import SelectorFecha
from src.ui.ingresos_base import PantallaIngresosBase
from src.ui import comercial_estilo as estilo_com
from src.ui.transiciones import TransicionFundidoSubida
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *

MENSAJE_ERROR_GUARDADO = "No se pudo actualizar el estado. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."


def _texto_cantidad(cantidad, participio):
    plural = "vehículo" if cantidad == 1 else "vehículos"
    return f"{cantidad} {plural} {participio}{'s' if cantidad != 1 else ''}"


# =========================================================
# INTERFAZ DE OPERACIONES -- ver conversación con el usuario 14-21/09-2026;
# rediseño de Activaciones/Conectividad/Sin Flota, 24-09-2026.
#
# Las tres sub-pestañas leen PruebasFM.xlsx vía DataManager y filtran con
# operaciones_services (reglas confirmadas con el usuario, ver docstring de
# ese módulo). La pestaña "Conectividad" se eliminó (24-09-2026): su caso
# (Vigente + Activando) ya vivía dentro de Activaciones (el filtro de esa
# pestaña nunca tuvo condición de ESTADO COMERCIAL) y sigue viviendo ahí sin
# cambios. "Sin Flota" es una pestaña nueva, ocupa el índice que dejó libre
# Conectividad (idx 1) -- "Bajas" se deja intencionalmente en idx 2, sin
# tocar ninguna de sus referencias a ese índice.
#
# "Activaciones" y "Sin Flota" comparten la misma acción de escritura real
# "Marcar como CONECTADO" (ExcelWriter + SaveExcelThread, igual que
# comercial.py) -- ambas fuerzan ESTADO COMERCIAL = Vigente al conectar
# (22-09-2026, cierra el ciclo de reactivación desde Comercial ->
# "Gestionar Bajas"); en Sin Flota, además, CDB y FLOTA VC son obligatorios
# antes de poder conectar (ver _on_marcar_conectado_clicked). "Bajas" es de
# solo lectura salvo "Marcar como DESCONECTADO" (ver más abajo). Los KPI
# reutilizan comercial_services.calcular_kpis_vigencia en vez de duplicar el
# cálculo de vigencia de contrato.
#
# La tabla usa VolvoTableWidget + PandasTableModel -- el mismo componente
# que "Vista Completa" de Comercial y Clientes y Flota -- para que todas
# las tablas de la app compartan un único diseño.
# =========================================================

# Activaciones y Sin Flota muestran las mismas 4 columnas (con ESTADO
# COMERCIAL visible, a pedido explícito); Bajas conserva exactamente las
# columnas que ya tenía (INICIO/TÉRMINO CONTRATO), sin tocarla.
COLUMNAS_TABLA_ACTIVACIONES = ['VIN', 'FLOTA VC', 'CDB FLOTA', 'TIPO DE SERVICIO', 'FORMA DE CONTRATO', 'ESTADO COMERCIAL']
COLUMNAS_TABLA_BAJAS = ['VIN', 'FLOTA VC', 'CDB FLOTA', 'TIPO DE SERVICIO', 'FORMA DE CONTRATO', 'INICIO CONTRATO', 'TÉRMINO CONTRATO']
_COLUMNAS_POR_TAB = {
    0: COLUMNAS_TABLA_ACTIVACIONES,
    1: COLUMNAS_TABLA_ACTIVACIONES,
    2: COLUMNAS_TABLA_BAJAS,
    3: operaciones_services.COLUMNAS_CDB_SIN_CONTACTO,
    4: COLUMNAS_TABLA_ACTIVACIONES,
}
ANCHOS_COLUMNAS_ACTIVACIONES = {
    'VIN': 175, 'FLOTA VC': 450, 'CDB FLOTA': 110, 'CDB': 110, 'ESTADO COMERCIAL': 140,
    'TIPO DE SERVICIO': 150, 'FORMA DE CONTRATO': 140,
    'INICIO CONTRATO': 120, 'TÉRMINO CONTRATO': 120,
    'RUT': 130, 'UNIDADES': 110, 'VIGENTES': 110,
}
# Alto mínimo de fila: deja espacio al chip de ESTADO COMERCIAL y al editor
# de FLOTA VC/CDB (ver _ajustar_alto_filas)
ALTO_MINIMO_FILA = 44
# Holgura (px) para padding/márgenes del delegate al decidir si un texto cabe en una línea.
# Medido con Segoe UI 9pt: desde 8 px ya no hay diferencias con resizeRowsToContents(); se usa el doble.
_HOLGURA_TEXTO_UNA_LINEA = 16


def _es_latin1(texto):
    try:
        texto.encode('latin-1')
        return True
    except UnicodeEncodeError:
        return False


_FILTROS_EXTRA = (('FORMA DE CONTRATO', "Forma de contrato", 'fa5s.file-signature'),
                  ('TIPO DE SERVICIO', "Tipo de servicio", 'fa5s.concierge-bell'))


class BotonAccionOperaciones(estilo_com.BotonAccionRapida):
    """Acción rápida (mismo look que Comercial) cuyo setText/text actúan
    sobre el título, para que "Guardando..." y el texto original sigan
    funcionando igual que con el QPushButton anterior."""

    def __init__(self, icon_name, titulo, subtitulo, color, parent=None):
        super().__init__(color, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(36)
        self.setToolTip(subtitulo)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 10, 4)
        layout.setSpacing(8)

        icono = QFrame()
        icono.setFixedSize(26, 26)
        icono.setStyleSheet(estilo_com.qss_icono_accion(color))
        lay_icono = QVBoxLayout(icono)
        lay_icono.setContentsMargins(0, 0, 0, 0)
        lbl_icono = QLabel()
        lbl_icono.setPixmap(ThemeManager.icon_pixmap(icon_name, color=color, size=12))
        lbl_icono.setStyleSheet("background: transparent; border: none;")
        lay_icono.addWidget(lbl_icono, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icono)

        self._lbl_titulo = QLabel(titulo.strip())
        self._lbl_titulo.setToolTip(subtitulo)
        layout.addWidget(self._lbl_titulo, stretch=1)
        self._pintar_textos()

    def setText(self, texto):
        self._lbl_titulo.setText(str(texto).strip())

    def text(self):
        return self._lbl_titulo.text()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange:
            self._pintar_textos()

    def _pintar_textos(self):
        color = estilo_com.TINTA if self.isEnabled() else estilo_com.APAGADO
        self._lbl_titulo.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px; background: transparent; border: none;")

# Barra de búsqueda global (25-09-2026, pedido explícito -- antes
# search_input era solo un QLineEdit oculto para cumplir el contrato de
# MainWindow._on_global_search, sin ningún filter_table() real detrás, así
# que escribir en la barra global no hacía nada acá). Mismas 4 columnas que
# pidió el usuario; se define aparte de COLUMNAS_BUSQUEDA_COMERCIAL de
# comercial.py porque las columnas visibles/buscables de cada módulo son
# independientes, no porque RUT sea exclusivo de aquí (ambas lo incluyen).
COLUMNAS_BUSQUEDA_OPERACIONES = [COL_VIN, COL_RAZON_SOCIAL, COL_CDB_FLOTA, COL_RUT, COL_ID]
COLUMNAS_BUSQUEDA_EXACTAS_OPERACIONES = [COL_ID]

# Columnas editables directo en la tabla (Activaciones/Sin Flota, ver
# OperacionesTableModel._COLUMNAS_EDITABLES): únicas donde tiene sentido
# pegar con Ctrl+V sobre varias celdas seleccionadas a la vez (ver
# _custom_key_press_operaciones).
_COLUMNAS_PEGADO_MASIVO = {'FLOTA VC', 'CDB FLOTA'}

# Campos de la ficha del panel flotante: (etiqueta, nombre de columna en
# df_master, tipo). "copiable" (CHASIS) se copia con un clic; "titulo" es
# el nombre grande de la ficha; "chip" va en una celda con el color del
# catálogo (mismo componente que la ficha de Comercial).
CAMPOS_DETALLE_ACTIVACIONES = [
    ("CHASIS", "CHASIS", "copiable"),
    ("Razón Social", "RAZÓN SOCIAL", "titulo"),
    ("Estado activación", "ESTADO DE ACTIVACIÓN ACTUAL", "chip"),
    ("Forma de contrato", "FORMA DE CONTRATO", "chip"),
    ("Tipo de servicio", "TIPO DE SERVICIO", "chip"),
    ("Modelo", "MODELO", "chip"),
    ("CDB comercial", "CDB", "copiable"),
    ("N° contrato", "ID", "copiable"),
    ("VIN", "VIN", "copiable"),
]

# Sub-pestañas con los campos CDB flota / Flota VC en el panel derecho
SUBTABS_CON_DATOS_FLOTA = (0, 1, 4)

# Índice de la sub-pestaña "Sin Flota" -- único lugar donde Luis debe
# completar CDB/FLOTA VC antes de poder conectar una unidad (ver
# _on_marcar_conectado_clicked/_actualizar_campos_sin_flota_visibles).
IDX_SIN_FLOTA = 1

# Sub-pestaña "Contactos" (05-10-2026): CDB sin contacto en contactos.xlsx,
# se agregan de a uno con el mismo formulario de Comercial/Clientes y Flotas.
IDX_CONTACTOS = 3

# Sub-pestaña "Datos de flota" (13-10-2026): contratos Vigentes y Conectados sin
# FLOTA VC; Operaciones la completa directo en la tabla.
IDX_DATOS_FLOTA = 4

# Las tres sub-pestañas se arman en vivo desde df_master (ver
# _refrescar_cola); sus reglas de filtro viven en operaciones_services.
SUBTABS = [
    ("Activaciones", "fa5s.file-alt"),
    ("Sin Flota", "fa5s.truck-loading"),
    ("Bajas", "fa5s.users"),
    ("Contactos", "fa5s.address-book"),
    ("Conectados", "fa5s.truck"),
]

_FILTROS_POR_TAB = {
    0: operaciones_services.filtrar_activaciones,
    1: operaciones_services.filtrar_sin_flota,
    2: operaciones_services.filtrar_bajas,
    IDX_DATOS_FLOTA: operaciones_services.filtrar_conectados_vigentes,
}


class OperacionesTableModel(PandasTableModel):
    """Igual que PandasTableModel, salvo que solo FLOTA VC y CDB son
    editables (24-09-2026, a pedido explícito: hoy no se podía corregir
    esos campos directo en la tabla de Activaciones/Sin Flota, como sí se
    puede en "Vista Completa" de comercial.py). VIN y ESTADO COMERCIAL
    siguen de solo lectura -- ese último solo cambia vía los botones
    "Marcar como...", nunca a mano, para no romper el alineamiento con
    ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ. En "Bajas" la edición queda
    bloqueada igual (VolvoTableWidget.setEditTriggers(NoEditTriggers) en
    esa sub-pestaña, ver _actualizar_seleccion_y_campos_sin_flota), así
    que estos flags nunca llegan a activarse ahí en la práctica."""
    _COLUMNAS_EDITABLES = {'FLOTA VC', 'CDB FLOTA'}
    solo_lectura = False

    def flags(self, index):
        flags = super().flags(index)
        col_name = self._df.columns[index.column()]
        if col_name in self._COLUMNAS_EDITABLES and not self.solo_lectura:
            return flags | Qt.ItemFlag.ItemIsEditable
        return flags & ~Qt.ItemFlag.ItemIsEditable


# =========================================================
# HILO DE GUARDADO ASÍNCRONO (mismo mecanismo que comercial.py: ExcelWriter
# corre en un QThread aparte para no congelar la interfaz mientras escribe).
# =========================================================
class SaveExcelThread(QThread):
    finished_signal = pyqtSignal(bool)

    def __init__(self, writer, changes, module_name="Sistema"):
        super().__init__()
        self.writer = writer
        self.changes = changes
        self.module_name = module_name

    def run(self):
        success = self.writer.update_cells(self.changes, module_name=self.module_name)
        self.finished_signal.emit(success)


class OperacionesModule(QWidget):
    """Pestañas "Activaciones", "Sin Flota", "Bajas" (leen/escriben
    PruebasFM.xlsx vía DataManager/ExcelWriter, igual que comercial.py) y
    "Contactos" (CDB sin contacto en contactos.xlsx)."""

    def __init__(self):
        super().__init__()

        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.df_master = pd.DataFrame()
        # Snapshot completo (todas las columnas) de la cola visible por
        # sub-pestaña (0=Activaciones, 1=Sin Flota, 2=Bajas).
        self._cola_full = {i: pd.DataFrame() for i in range(len(SUBTABS))}
        # Filtro adicional por cliente (botón "Filtrar"), por sub-pestaña.
        # None = sin filtro (se ven todos los clientes de esa cola).
        # Solo para marcar el botón "Filtrar" mientras excluye clientes
        self._data_dirty = False
        self._vins_en_guardado = []
        self._vins_en_guardado_baja = []
        self._cambios_en_guardado_baja = {}

        # Compat con MainWindow._on_global_search: espera un search_input,
        # aunque esta pantalla no filtra nada por texto libre todavía.
        self.search_input = QLineEdit()
        self.search_input.hide()

        self.data_manager.data_ready.connect(self._on_global_data_ready)
        self.data_manager.load_error.connect(self._on_load_error)
        self.data_manager.contactos_ready.connect(self._on_contactos_ready)

        self._setup_ui()
        self.load_data()

    # --- Compat con MainWindow (closeEvent y _trigger_load_data) ---
    def load_data(self):
        self._data_dirty = False
        self.df_master = self.data_manager.get_contratos_actuales_df()
        self._registrar_ejecutivos_nuevos()
        self._actualizar_contadores_subtabs()
        self._refrescar_tabla_actual()

    def _registrar_ejecutivos_nuevos(self):
        """Deja en el directorio (sin correo) a los ejecutivos que PruebasFM ya usa y aún no figuran."""
        df = self.df_master
        if df is None or df.empty or 'EJECUTIVO' not in df.columns:
            return
        try:
            ejecutivos_service.registrar_ejecutivos_nuevos(df['EJECUTIVO'].dropna().astype(str).unique())
        except Exception:
            pass

    def refresh_if_dirty(self):
        if self._data_dirty:
            self.load_data()

    def _on_global_data_ready(self):
        self._rehabilitar_recargar()
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def _on_load_error(self, error_msg):
        self._rehabilitar_recargar()
        QMessageBox.critical(self, "Error al Cargar", f"Ocurrió un problema:\n{error_msg}")

    def _on_contactos_ready(self):
        self._actualizar_contadores_subtabs()
        if self.subtabs.currentIndex() == IDX_CONTACTOS:
            self._refrescar_tabla_actual()

    def _setup_ui(self):
        # Mismo estilo que la Nueva interfaz de Comercial (comercial_estilo.py)
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Contenedor propio: "Ampliar" lo oculta y la transición de sub-pestaña lo anima
        self._kpi_contenedor = QWidget()
        fila_kpis = self._build_kpi_row()
        fila_kpis.setContentsMargins(0, 4, 0, 0)
        self._kpi_contenedor.setLayout(fila_kpis)
        main_layout.addWidget(self._kpi_contenedor)

        main_layout.addWidget(self._build_subtabs())
        self._contenido = self._build_tabla_card()
        main_layout.addWidget(self._contenido, stretch=1)

        self._transicion_kpis = TransicionFundidoSubida(self, self._kpi_contenedor, BACKGROUND)
        self._transicion_contenido = TransicionFundidoSubida(self, self._contenido, BACKGROUND)

        # Detalle y acciones: panel flotante fuera del layout (la tabla usa
        # todo el ancho); aparece solo con alguna fila seleccionada
        self._panel_detalle = self._build_detalle_card()
        estilo_com.crear_sombra_panel(self._panel_detalle)
        self._panel_detalle.hide()
        self._panel_abierto = False
        self._anim_panel = QPropertyAnimation(self._panel_detalle, b"pos", self)
        estilo_com.configurar_animacion_panel(self._anim_panel)
        self._anim_panel.finished.connect(self._on_anim_panel_terminada)
        self._anim_panel.valueChanged.connect(lambda _v: self._ajustar_barra_bajo_panel())

    # ---------------------------------------------------------------
    # Panel flotante (mismo comportamiento que las acciones rápidas de Comercial)
    # ---------------------------------------------------------------
    def _geometria_panel(self, abierto):
        return estilo_com.geometria_panel_flotante(self, abierto)

    def _mostrar_panel(self, mostrar):
        panel = getattr(self, '_panel_detalle', None)
        if panel is None or mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        self._anim_panel.stop()
        if mostrar:
            estilo_com.montar_panel_sobre_encabezado(self, panel, lambda: self._panel_abierto)
            if not panel.isVisible():
                panel.setGeometry(self._geometria_panel(False))
                panel.show()
            panel.raise_()
            estilo_com.fijar_sombra_panel(panel, True)
        self._anim_panel.setStartValue(panel.pos())
        self._anim_panel.setEndValue(self._geometria_panel(mostrar).topLeft())
        self._anim_panel.start()

    def _on_anim_panel_terminada(self):
        if not self._panel_abierto:
            self._panel_detalle.hide()
            estilo_com.fijar_sombra_panel(self._panel_detalle, False)
        self._ajustar_barra_bajo_panel()

    def _ajustar_barra_bajo_panel(self):
        """Corre los botones de la barra de la bandeja hacia la izquierda
        para que el panel flotante no los tape."""
        barra, panel = self._barra_bandeja, self._panel_detalle
        solape = 0
        if panel.isVisible():
            borde_derecho = barra.mapTo(panel.parentWidget(), QPoint(barra.width(), 0)).x()
            solape = max(0, borde_derecho - panel.x() + 4)
        barra.layout().setContentsMargins(15, 12, 15 + solape, 12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        panel = getattr(self, '_panel_detalle', None)
        if panel is not None and panel.isVisible():
            self._anim_panel.stop()
            QTimer.singleShot(0, self._reubicar_panel)

    def _reubicar_panel(self):
        panel = self._panel_detalle
        if not panel.isVisible():
            return
        panel.setGeometry(self._geometria_panel(self._panel_abierto))
        if not self._panel_abierto:
            panel.hide()
        self._ajustar_barra_bajo_panel()

    # ---------------------------------------------------------------
    # Sub-pestañas
    # ---------------------------------------------------------------
    def _build_subtabs(self):
        # Mismas sub-pestañas que Comercial: solo texto y contador de unidades
        self.subtabs = QTabBar()
        self._badges_subtabs = []
        for i, (nombre, _icono) in enumerate(SUBTABS):
            self.subtabs.addTab(nombre)
            badge = QLabel("0")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(34, 20)
            if i == IDX_DATOS_FLOTA:
                # Conectados lleva además un contador rojo con las filas urgentes
                contenedor_badges = QWidget()
                fila_badges = QHBoxLayout(contenedor_badges)
                fila_badges.setContentsMargins(0, 0, 0, 0)
                fila_badges.setSpacing(4)
                self._badge_urgentes = QLabel("0")
                self._badge_urgentes.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._badge_urgentes.setFixedHeight(20)
                self._badge_urgentes.setStyleSheet(
                    f"background-color: {DANGER}; color: white; border-radius: 10px; "
                    "padding: 0px 8px; font-size: 11px; font-weight: bold; min-width: 10px;")
                self._badge_urgentes.hide()
                fila_badges.addWidget(badge)
                fila_badges.addWidget(self._badge_urgentes)
                self.subtabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, contenedor_badges)
            else:
                self.subtabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, badge)
            self._badges_subtabs.append(badge)
        self.subtabs.currentChanged.connect(self._estilizar_badges_subtabs)
        self._estilizar_badges_subtabs()
        self.subtabs.setExpanding(False)
        self.subtabs.setDrawBase(False)
        self.subtabs.setStyleSheet(estilo_com.QSS_SUBPESTANAS + "QTabBar::tab { padding-right: 6px; } "
            "QTabBar::tab:selected { color: #1B2B4E; border-bottom: 3px solid #1B2B4E; }")
        self.subtabs.currentChanged.connect(self._on_subtab_cambiada)

        contenedor = QFrame()
        contenedor.setObjectName("contenedorSubpestanasComercial")
        contenedor.setStyleSheet(estilo_com.QSS_CONTENEDOR_SUBPESTANAS)
        fila = QHBoxLayout(contenedor)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.addWidget(self.subtabs)
        fila.addStretch()
        return contenedor

    def _estilizar_badges_subtabs(self, *_):
        actual = self.subtabs.currentIndex()
        for i, badge in enumerate(self._badges_subtabs):
            fondo, texto = ("#E3E8F0", "#1B2B4E") if i == actual else ("#EEF2F6", estilo_com.APAGADO)
            badge.setStyleSheet(
                f"background-color: {fondo}; color: {texto}; border-radius: 10px; "
                "padding: 0px 8px; font-size: 11px; font-weight: bold; min-width: 10px;"
            )

    def _actualizar_contadores_subtabs(self):
        """Unidades de cada cola junto al nombre de su sub-pestaña (sin búsqueda ni filtro de cliente)."""
        df = self.df_master
        hay_datos = df is not None and not df.empty
        for i, badge in enumerate(self._badges_subtabs):
            n = 0
            if hay_datos:
                try:
                    if i == IDX_CONTACTOS:
                        n = len(operaciones_services.filtrar_cdb_sin_contacto(df, self.data_manager.get_contactos_df()))
                    else:
                        n = len(_FILTROS_POR_TAB[i](df))
                except Exception:
                    n = 0
            if i == IDX_DATOS_FLOTA:
                urgentes = 0
                if hay_datos:
                    try:
                        urgentes = len(operaciones_services.filtrar_conectados_sin_flota_vc(df))
                    except Exception:
                        urgentes = 0
                self._badge_urgentes.setText(str(urgentes))
                self._badge_urgentes.setVisible(urgentes > 0)
                self._badge_urgentes.setToolTip(
                    f"{urgentes} sin Flota VC o CDB Flota: revisar primero" if urgentes else "")
                self.subtabs.setTabText(i, SUBTABS[i][0])
            if badge.text() != str(n):
                badge.setText(str(n))
                # El ancho crece con la cifra (miles de unidades) y se avisa a la barra para recolocar
                badge.setFixedWidth(max(34, badge.fontMetrics().horizontalAdvance(str(n)) + 24))
                self.subtabs.setTabText(i, SUBTABS[i][0])
        # El contenedor de Conectados cambia de ancho al aparecer o crecer el contador rojo
        contenedor_badges = self._badge_urgentes.parentWidget()
        contenedor_badges.adjustSize()
        self.subtabs.setTabText(IDX_DATOS_FLOTA, SUBTABS[IDX_DATOS_FLOTA][0])

    def _on_subtab_cambiada(self, _idx):
        # Foto de lo visible antes de repintar, para la transición
        fotos = []
        for transicion, contenedor in ((self._transicion_kpis, self._kpi_contenedor),
                                       (self._transicion_contenido, self._contenido)):
            if contenedor.isVisible():
                transicion.terminar()
                fotos.append((transicion, contenedor.grab()))
        self._refrescar_tabla_actual()
        for transicion, foto in fotos:
            transicion.iniciar(foto)

    # ---------------------------------------------------------------
    # KPIs por sub-pestaña (06-10-2026): mismas tarjetas que el HTML v2 de
    # Operaciones y mismo diseño que las de Comercial (TarjetaKpiResumen).
    # Son informativas: no filtran la cola. Activaciones y Sin Flota
    # comparten las 4 tarjetas, calculadas sobre ambas colas juntas.
    # ---------------------------------------------------------------
    _KPIS_PENDIENTES_ACTIVACION = [
        ("pendientes", "Pendientes de activación", PRIMARY,
         "Unidades en la cola de Activaciones más las de Sin Flota.", "activaciones + sin flota"),
        ("activando", "En proceso de activación", WARNING,
         "ESTADO DE ACTIVACIÓN ACTUAL = Activando.", "unidades en gestión"),
        ("no_entregado", "Pendientes por no entrega", WARNING,
         "ESTADO DE ACTIVACIÓN ACTUAL = No entregado.", "falta la entrega"),
        ("sin_flota", "Pendientes por asignación de flota", DANGER,
         "Unidades en la cola de Sin Flota (todavía no aparecen en Volvo Connect).", "sin flota en VC"),
    ]

    _KPI_SPECS = {
        0: _KPIS_PENDIENTES_ACTIVACION,
        1: _KPIS_PENDIENTES_ACTIVACION,
        2: [("bajas", "Bajas pendientes", DANGER,
             "Unidades de la cola de Bajas: siguen Conectadas a la espera de la desconexión física.",
             "bajas por cerrar")],
        3: [("cdb_sin_contacto", "CDB sin contacto", DANGER,
             "CDB de RM_JAVI que no tienen ningún contacto en contactos.xlsx.",
             "sin contacto registrado")],
        IDX_DATOS_FLOTA: [("conectados_vigentes", "Conectados y vigentes", PRIMARY,
                           "Contratos Vigentes cuya unidad está Conectada. FLOTA VC y CDB FLOTA se editan en el panel.",
                           "contratos"),
                          ("sin_flota_vc", "Sin flota o CDB", DANGER,
                           "Contratos Vigentes y Conectados que no tienen FLOTA VC o CDB FLOTA.",
                           "por completar")],
    }

    def _build_kpi_row(self):
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self._kpi_cards = []
        for _ in range(4):
            card = estilo_com.TarjetaKpiResumen()
            card.setCheckable(False)
            card.setCursor(Qt.CursorShape.ArrowCursor)
            # Las pestañas con menos de 4 tarjetas dejan el hueco, como el HTML
            politica = card.sizePolicy()
            politica.setRetainSizeWhenHidden(True)
            card.setSizePolicy(politica)
            self._kpi_cards.append(card)
            kpi_row.addWidget(card, stretch=1)
        return kpi_row

    def _calcular_kpis(self, idx, cola):
        """clave -> (valor, fracción 0-1 sobre la base de esa tarjeta).
        `cola` es la cola de `idx` sin filtro de cliente ni búsqueda."""
        df = self.df_master
        if idx in (0, 1):
            def cola_de(i):
                if i == idx:
                    return cola
                return _FILTROS_POR_TAB[i](df) if df is not None else pd.DataFrame()
            activaciones, sin_flota = cola_de(0), cola_de(1)
            parcial = operaciones_services.calcular_kpis_activaciones(activaciones)
            pendientes = len(activaciones) + len(sin_flota)
            valores = {
                "pendientes": pendientes, "activando": parcial["activando"],
                "no_entregado": parcial["no_entregado"], "sin_flota": len(sin_flota),
            }
            return {k: (v, (v / pendientes) if pendientes else 0.0) for k, v in valores.items()}
        if idx == 2:
            return {"bajas": (len(cola), 1.0 if len(cola) else 0.0)}
        if idx == IDX_DATOS_FLOTA:
            por_completar = len(operaciones_services.filtrar_conectados_sin_flota_vc(cola))
            return {"conectados_vigentes": (len(cola), 1.0 if len(cola) else 0.0),
                    "sin_flota_vc": (por_completar, (por_completar / len(cola)) if len(cola) else 0.0)}
        total_cdb = 0
        if df is not None and not df.empty and COL_CDB_FLOTA in df.columns:
            cdb = df[COL_CDB_FLOTA].astype(str).str.strip()
            total_cdb = cdb[~cdb.str.upper().isin(['', 'NAN', 'NONE', '-', 'NAT'])].nunique()
        return {"cdb_sin_contacto": (len(cola), (len(cola) / total_cdb) if total_cdb else 0.0)}

    def _actualizar_kpis(self, idx, cola):
        specs = self._KPI_SPECS.get(idx, self._KPI_SPECS[0])
        valores = self._calcular_kpis(idx, cola)
        for i, card in enumerate(self._kpi_cards):
            if i >= len(specs):
                card.hide()
                continue
            clave, titulo, color, tooltip, pie = specs[i]
            card.definir(titulo, color, tooltip)
            card.configurar(False, color)
            card.setCursor(Qt.CursorShape.ArrowCursor)
            valor, fraccion = valores[clave]
            card.actualizar(valor, fraccion, pie)
            card.show()

    # ---------------------------------------------------------------
    # TARJETA CENTRAL: sub-pestañas + tabla
    # ---------------------------------------------------------------
    def _build_tabla_card(self):
        # Barra de opciones y tabla en tarjetas separadas, como en Comercial
        externo = QWidget()
        layout_externo = QVBoxLayout(externo)
        layout_externo.setContentsMargins(0, 0, 0, 0)
        layout_externo.setSpacing(12)
        frame = QFrame()
        frame.setObjectName("bandejaOperaciones")
        frame.setStyleSheet(estilo_com.qss_tarjeta("bandejaOperaciones"))
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        barra = QFrame()
        barra.setObjectName("barraBandejaOperaciones")
        barra.setStyleSheet(
            "QFrame#barraBandejaOperaciones { background-color: #1B2B4E; border: none; border-radius: 14px; }")
        layout_externo.addWidget(barra)
        layout_externo.addWidget(frame, stretch=1)
        top_row = QHBoxLayout(barra)
        top_row.setContentsMargins(15, 7, 15, 7)
        top_row.setSpacing(8)
        self._barra_bandeja = barra

        # Título de la cola y resumen ("N unidades en M flotas"), como en Comercial
        self.lbl_titulo_bandeja = QLabel(SUBTABS[0][0])
        self.lbl_titulo_bandeja.setStyleSheet("color: white; font-size: 15px; font-weight: 800; background: transparent;")
        self.lbl_resumen_bandeja = QLabel("")
        self.lbl_resumen_bandeja.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
        lbl_seccion = QWidget()
        lay_titulo = QVBoxLayout(lbl_seccion)
        lay_titulo.setContentsMargins(0, 0, 0, 0)
        lay_titulo.setSpacing(0)
        lay_titulo.addWidget(self.lbl_titulo_bandeja)
        lay_titulo.addWidget(self.lbl_resumen_bandeja)

        # "&&" muestra un "&" literal (un "&" solo es atajo de teclado en Qt).
        self.btn_exportar_vin_cdb = QPushButton()
        self.btn_exportar_vin_cdb.setIcon(ThemeManager.icon('fa5s.file-excel', color='white'))
        self.btn_exportar_vin_cdb.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_exportar_vin_cdb.setToolTip(
            "Guarda en el Escritorio un Excel con VIN, CDB y plan de la tabla visible\n"
            "(solo las filas seleccionadas, si hay alguna)."
        )
        self.btn_exportar_vin_cdb.clicked.connect(self._on_exportar_vin_cdb_clicked)

        self.btn_exportar_contactos = QPushButton()
        self.btn_exportar_contactos.setIcon(ThemeManager.icon('fa5s.file-export', color=TEXT_SECONDARY))
        self.btn_exportar_contactos.setCursor(Qt.CursorShape.PointingHandCursor)
        estilo_com.aplicar_estilo_boton_barra(self.btn_exportar_contactos, 'neutro')
        self.btn_exportar_contactos.setToolTip(
            "Genera un Excel con los datos de contacto de los clientes en cola,\n"
            "para pasárselo al ejecutivo asignado."
        )
        self.btn_exportar_contactos.clicked.connect(self._on_exportar_contactos_clicked)

        # Filtros por columna: mismo selector que Comercial, solo icono
        self._selectores_filtro = {'cliente': estilo_com.SelectorFiltroPopup("Cliente", "Todos los clientes", 'fa5s.user-tie')}
        for col, titulo, icono in _FILTROS_EXTRA:
            self._selectores_filtro[col] = estilo_com.SelectorFiltroPopup(titulo, f"Todas ({titulo.lower()})", icono)
        for selector in self._selectores_filtro.values():
            selector.set_compacto(True)
            selector.cambiado.connect(lambda _v, s=selector: self._on_filtro_cambiado(s))
        self._orden_filtros = []
        self.btn_limpiar_filtros = QPushButton()
        self.btn_limpiar_filtros.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_limpiar_filtros.setIcon(ThemeManager.icon('fa5s.trash-alt', color=TEXT_SECONDARY))
        self.btn_limpiar_filtros.setToolTip("Quitar los filtros")
        self.btn_limpiar_filtros.clicked.connect(self._limpiar_filtros)

        # Solo en Conectados: muestra las unidades sin Flota VC o CDB flota
        self.btn_faltantes = QPushButton()
        self.btn_faltantes.setCheckable(True)
        self.btn_faltantes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_faltantes.setIcon(ThemeManager.icon('fa5s.exclamation-triangle', color=TEXT_SECONDARY))
        estilo_com.aplicar_estilo_boton_barra(self.btn_faltantes, 'neutro')
        self.btn_faltantes.toggled.connect(self._on_faltantes_toggled)
        self._solo_faltantes = False
        self.btn_faltantes.hide()

        # Solo en Conectados: rojo si un CDB flota tiene varias Flota VC; al pulsarlo filtra esas unidades
        self.btn_cdb_varias = QPushButton()
        self.btn_cdb_varias.setCheckable(True)
        self.btn_cdb_varias.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cdb_varias.setIcon(ThemeManager.icon('fa5s.code-branch', color=TEXT_SECONDARY))
        estilo_com.aplicar_estilo_boton_barra(self.btn_cdb_varias, 'neutro')
        self.btn_cdb_varias.toggled.connect(self._on_cdb_varias_toggled)
        self._solo_cdb_varias = False
        self._cdb_varias_cantidad = 0
        self.btn_cdb_varias.hide()

        # "Ampliar": oculta las tarjetas KPI para darle más alto a la tabla
        self.btn_ampliar = QPushButton()
        self.btn_ampliar.setCheckable(True)
        self.btn_ampliar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ampliar.setIcon(ThemeManager.icon('fa5s.expand', color=TEXT_SECONDARY))
        self.btn_ampliar.setToolTip("Ampliar tabla (oculta las tarjetas de resumen)")
        estilo_com.aplicar_estilo_boton_barra(self.btn_ampliar, 'neutro')
        self.btn_ampliar.toggled.connect(self._on_ampliar_toggled)
        estilo_com.sincronizar_boton_kpi(self.btn_ampliar)

        # Power BI (Notas de Venta) y Recargar, como en la barra de Comercial
        self.btn_power_bi = QPushButton()
        self.btn_power_bi.setIcon(ThemeManager.icon('fa5s.chart-bar', color='white'))
        self.btn_power_bi.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_power_bi.setToolTip("Abrir Notas de Venta en Power BI")
        self.btn_power_bi.clicked.connect(self._abrir_notas_venta_bi)
        self.btn_recargar = QPushButton()
        self.btn_recargar.setIcon(ThemeManager.icon('fa5s.sync-alt', color='white'))
        self.btn_recargar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_recargar.setToolTip("Recargar")
        self.btn_recargar.clicked.connect(self._on_recargar_clicked)

        capsula_bi = QFrame()
        capsula_bi.setStyleSheet("QFrame { background: rgba(255,255,255,0.08); border-radius: 14px; }")
        lay_capsula_bi = QHBoxLayout(capsula_bi)
        lay_capsula_bi.setContentsMargins(5, 5, 5, 5)
        lay_capsula_bi.addWidget(self.btn_power_bi)
        estilo_com.preparar_boton_capsula(self.btn_power_bi)
        separador = QFrame()
        separador.setFixedSize(1, 28)
        separador.setStyleSheet("background: rgba(255,255,255,0.22);")
        top_row.addWidget(capsula_bi)
        top_row.addWidget(separador)
        top_row.addWidget(lbl_seccion)
        top_row.addStretch()
        # Tres grupos con encabezado: filtros, acciones y generales
        for titulo_grupo, botones in (
                ("Filtros", (self.btn_limpiar_filtros, *self._selectores_filtro.values(), self.btn_faltantes, self.btn_cdb_varias)),
                ("Acciones", (self.btn_exportar_vin_cdb, self.btn_exportar_contactos)),
                ("Generales", (self.btn_ampliar, self.btn_recargar))):
            grupo, lay_grupo = PantallaIngresosBase._crear_grupo_barra(titulo_grupo)
            for btn in botones:
                btn.setFixedWidth(44)
                lay_grupo.addWidget(btn)
                estilo_com.preparar_boton_capsula(btn)
            top_row.addWidget(grupo)
            grupo.show()
        self.btn_limpiar_filtros.hide()

        # Mismo componente y estilo de tabla que la bandeja de Comercial
        self.table = VolvoTableWidget()
        qss_tabla = estilo_com.QSS_TABLA + (
            "QHeaderView::section { background: #F7F8FC; color: #6B7A90; border-bottom: 1px solid #E3E8F0; }"
            "QTableView { alternate-background-color: #FFFFFF; }"
            "QTableView::item { border-left: none; }")
        self.table.setStyleSheet(qss_tabla)
        self.table.frozen_view.setStyleSheet(qss_tabla)
        # Sin arrastrar columnas ni "Fijar columna"; clic en el encabezado ordena
        self.table.horizontalHeader().setSectionsMovable(False)
        self.table.permitir_fijar_columna = False
        for header in (self.table.horizontalHeader(), self.table.frozen_view.horizontalHeader()):
            header.sectionDoubleClicked.disconnect()
            header.sectionHandleDoubleClicked.disconnect()
        self.table.horizontalHeader().sectionClicked.connect(self._on_encabezado_clicado)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.horizontalHeader().set_word_wrap_habilitado(True)
        estilo_com.aplicar_estilo_encabezado(self.table.horizontalHeader())
        self.table.horizontalHeader().set_estilo_encabezado(
            "#F7F8FC", "#F7F8FC", "#6B7A90", "#E3E8F0",
            separador=None, grosor_linea=1, alto_minimo=44, espaciado_letras=0.8,
            iconos_orden=True, radio_superior=13, texto_negrita_fuerte=True,
        )
        self.table.verticalHeader().setDefaultSectionSize(ALTO_MINIMO_FILA)
        self.table.menu_type = "solo_lectura"
        # Edit triggers reales se fijan por sub-pestaña en
        # _actualizar_seleccion_y_campos_sin_flota (Activaciones/Sin Flota
        # editables, Bajas de solo lectura); NoEditTriggers es solo el
        # valor inicial antes de la primera carga.
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Selección múltiple: "Marcar como CONECTADO" actúa solo sobre las
        # filas que el usuario seleccione (pedido explícito 18-09-2026), no
        # sobre todas las filas visibles de la pestaña.
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.sort_changed.connect(self._refrescar_tabla_actual)

        self.model = OperacionesTableModel(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.model.destacar_columnas_cliente()
        self.table.set_model_and_delegate(self.model)
        # Hover por fila y ESTADO COMERCIAL como chip, igual que Comercial
        self._delegado_celdas = estilo_com.DelegadoCeldasComercial([self.table, self.table.frozen_view])
        self.table.setItemDelegate(self._delegado_celdas)
        self.table.frozen_view.setItemDelegate(self._delegado_celdas)
        self.table.selectionModel().selectionChanged.connect(self._on_seleccion_cambiada)

        # Pegado masivo con Ctrl+V (25-09-2026, pedido explícito): pega el
        # mismo valor del portapapeles en todas las celdas seleccionadas de
        # una misma columna, pero solo si esa columna es FLOTA VC o CDB
        # (las únicas editables acá, ver OperacionesTableModel). Mismo
        # patrón que ya usa comercial.py (paste_dropdown_value_to_selection)
        # para columnas de catálogo, adaptado a texto libre en vez de un
        # dropdown.
        original_key_press = self.table.keyPressEvent

        def custom_key_press(event):
            if event.matches(QKeySequence.StandardKey.Paste):
                indexes = self.table.selectedIndexes()
                if indexes:
                    df_view = self.model.get_df()
                    col_idx = indexes[0].column()
                    if col_idx < len(df_view.columns) and df_view.columns[col_idx] in _COLUMNAS_PEGADO_MASIVO:
                        celdas_misma_columna = [idx for idx in indexes if idx.column() == col_idx]
                        if celdas_misma_columna:
                            self._pegar_valor_en_seleccion(celdas_misma_columna)
                            return
            original_key_press(event)

        self.table.keyPressEvent = custom_key_press

        layout.addWidget(self.table, stretch=1)

        return externo

    def _abrir_notas_venta_bi(self):
        if REPORTE_NOTAS_VENTAS_URL:
            QDesktopServices.openUrl(QUrl(REPORTE_NOTAS_VENTAS_URL))
        else:
            QMessageBox.warning(self, "Enlace Vacío", "No hay URL configurada para el Reporte de Notas de Ventas.\nPor favor, actualízalo en Configuración.")

    def _on_recargar_clicked(self):
        self.btn_recargar.setEnabled(False)
        self.btn_recargar.setToolTip("Cargando...")
        self.data_manager.load_data_async()
        QTimer.singleShot(12000, self._rehabilitar_recargar)

    def _rehabilitar_recargar(self):
        self.btn_recargar.setEnabled(True)
        self.btn_recargar.setToolTip("Recargar")

    def showEvent(self, event):
        super().showEvent(event)
        estilo_com.sincronizar_boton_kpi(getattr(self, 'btn_ampliar', None))

    def _on_ampliar_toggled(self, ampliada):
        estilo_com.guardar_kpi_ocultos(ampliada)
        self._kpi_contenedor.setVisible(not ampliada)
        self.btn_ampliar.setIcon(ThemeManager.icon('fa5s.compress' if ampliada else 'fa5s.expand', color=TEXT_SECONDARY))
        self.btn_ampliar.setToolTip(
            "Volver a mostrar las tarjetas de resumen" if ampliada else "Ampliar tabla (oculta las tarjetas de resumen)"
        )

    def _on_encabezado_clicado(self, logical_index):
        """Clic en un encabezado: ordena A→Z; un segundo clic invierte."""
        col_name = self.model.headerData(logical_index, Qt.Orientation.Horizontal)
        if not col_name:
            return
        if self.table._sort_column == col_name and self.table._sort_order == Qt.SortOrder.AscendingOrder:
            self.table._set_sort(col_name, Qt.SortOrder.DescendingOrder)
        else:
            self.table._set_sort(col_name, Qt.SortOrder.AscendingOrder)

    def _pegar_valor_en_seleccion(self, celdas):
        """Aplica el texto del portapapeles (una sola línea; si trae varias,
        se usa solo la primera) a todas las `celdas` seleccionadas -- mismo
        mecanismo que un usuario editando celda por celda (pasa por
        model.setData, así que queda resaltada como editada y la lee
        _valor_actual_celda al guardar)."""
        if self.model.solo_lectura:
            return
        clipboard_text = QApplication.clipboard().text().strip().splitlines()
        valor = clipboard_text[0].strip() if clipboard_text else ""
        if not valor:
            return
        for index in celdas:
            self.model.setData(index, valor, Qt.ItemDataRole.EditRole)

    def _reubicar_acciones(self):
        """Acomoda las acciones visibles de a dos por fila; si queda una
        sola en la última fila, ocupa el ancho completo."""
        grilla = self._grilla_acciones
        botones = [self.btn_marcar_conectado, self.btn_marcar_sin_flota,
                   self.btn_marcar_desconectado, self.btn_guardar_flota, self.btn_limpiar_flota,
                   self.btn_contactar_ejecutivo]
        for b in botones:
            grilla.removeWidget(b)
        visibles = [b for b in botones if not b.isHidden()]
        for i, b in enumerate(visibles):
            ultimo_solo = i == len(visibles) - 1 and len(visibles) % 2 == 1
            grilla.addWidget(b, i // 2, i % 2, 1, 2 if ultimo_solo else 1)

    def _refrescar_tabla_actual(self):
        idx = self.subtabs.currentIndex()
        self._actualizar_seleccion_y_campos_sin_flota(idx)
        self._refrescar_cola(idx)
        self._actualizar_estado_botones()
        # En el panel solo se muestran las acciones de la sub-pestaña activa
        self.btn_marcar_conectado.setVisible(idx in (0, IDX_SIN_FLOTA))
        self.btn_marcar_sin_flota.setVisible(idx == 0)
        self.btn_marcar_desconectado.setVisible(idx == 2)
        self.btn_guardar_flota.setVisible(idx in SUBTABS_CON_DATOS_FLOTA)
        self.btn_limpiar_flota.setVisible(idx == IDX_SIN_FLOTA)
        self._reubicar_acciones()
        self._bloque_datos_flota.setVisible(idx in SUBTABS_CON_DATOS_FLOTA)
        self.btn_exportar_vin_cdb.setVisible(idx != IDX_CONTACTOS)
        self.btn_faltantes.setVisible(idx == IDX_DATOS_FLOTA)
        self.btn_cdb_varias.setVisible(idx == IDX_DATOS_FLOTA)
        self._bloque_unidad.setVisible(idx != IDX_CONTACTOS)
        self._bloque_contacto.setVisible(idx == IDX_CONTACTOS)
        if idx != IDX_CONTACTOS:
            self._quitar_formulario_contacto()

    def _actualizar_seleccion_y_campos_sin_flota(self, idx):
        """Selección múltiple en todas las sub-pestañas salvo Contactos. CDB
        flota y Flota VC se escriben en el panel derecho (Activaciones, Sin
        Flota y Datos de flota) y valen para todas las unidades seleccionadas;
        la tabla queda de solo lectura."""
        if idx == IDX_CONTACTOS:
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        else:
            self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # CDB flota y Flota VC se escriben en el panel derecho (aplican a todas
        # las unidades seleccionadas); la tabla es solo de lectura
        self.model.solo_lectura = True
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def _actualizar_boton_faltantes(self, cantidad):
        self.btn_faltantes.setToolTip(
            f"Muestra solo las {cantidad} unidad(es) sin Flota VC o CDB flota (\"SIN FLOTA\" y \"NO EXISTE EN VC\" cuentan como faltantes)."
            if cantidad else "No hay unidades sin Flota VC ni CDB flota.")

    def _on_faltantes_toggled(self, activo):
        self._solo_faltantes = activo
        if activo:
            estilo_com.aplicar_estilo_boton_barra(self.btn_faltantes, 'activo')
            self.btn_faltantes.setIcon(ThemeManager.icon('fa5s.exclamation-triangle', color=estilo_com.PRIMARIO))
        else:
            estilo_com.aplicar_estilo_boton_barra(self.btn_faltantes, 'neutro')
            self.btn_faltantes.setIcon(ThemeManager.icon('fa5s.exclamation-triangle', color=TEXT_SECONDARY))
        self._refrescar_tabla_actual()
        if activo and self.model.get_df().empty:
            self.btn_faltantes.setChecked(False)
            QMessageBox.information(self, "Unidades sin flota", "Todas las unidades Conectadas tienen Flota VC y CDB flota.")

    def _actualizar_boton_cdb_varias(self, cantidad):
        self._cdb_varias_cantidad = cantidad
        if self.btn_cdb_varias.isChecked():
            return
        if cantidad:
            estilo_com.aplicar_estilo_boton_barra(self.btn_cdb_varias, 'alerta')
            self.btn_cdb_varias.setIcon(ThemeManager.icon('fa5s.code-branch', color=estilo_com.ROJO))
            self.btn_cdb_varias.setToolTip(
                f"{cantidad} unidad(es) tienen un CDB flota con más de una Flota VC. Click para mostrarlas.")
        else:
            estilo_com.aplicar_estilo_boton_barra(self.btn_cdb_varias, 'neutro')
            self.btn_cdb_varias.setIcon(ThemeManager.icon('fa5s.code-branch', color=TEXT_SECONDARY))
            self.btn_cdb_varias.setToolTip("Ningún CDB flota tiene varias Flota VC.")

    def _on_cdb_varias_toggled(self, activo):
        self._solo_cdb_varias = activo
        if activo:
            estilo_com.aplicar_estilo_boton_barra(self.btn_cdb_varias, 'activo')
            self.btn_cdb_varias.setIcon(ThemeManager.icon('fa5s.code-branch', color=estilo_com.PRIMARIO))
            self.btn_cdb_varias.setToolTip("Mostrando solo los CDB flota con varias Flota VC. Click para volver a todas.")
        self._refrescar_tabla_actual()
        if activo and self.model.get_df().empty:
            self.btn_cdb_varias.setChecked(False)
            QMessageBox.information(self, "CDB con varias flotas", "Ningún CDB flota tiene varias Flota VC en esta lista.")
        elif not activo:
            self._actualizar_boton_cdb_varias(self._cdb_varias_cantidad)

    def _refrescar_cola(self, idx):
        columnas_tab = _COLUMNAS_POR_TAB[idx]
        df = self.df_master
        if df is None or df.empty:
            full = pd.DataFrame(columns=columnas_tab)
        elif idx == IDX_CONTACTOS:
            full = operaciones_services.filtrar_cdb_sin_contacto(df, self.data_manager.get_contactos_df())
        else:
            full = _FILTROS_POR_TAB[idx](df)

        cola_sin_filtrar = full
        full = self._aplicar_filtros_columna(idx, full)

        # Búsqueda global (25-09-2026, pedido explícito): reutiliza
        # construir_mascara_busqueda, mismo mecanismo que comercial.py, sobre
        # VIN/RAZÓN SOCIAL/CDB/RUT (COLUMNAS_BUSQUEDA_OPERACIONES).
        search_text = self.search_input.text().strip().lower()
        if search_text and not full.empty:
            mascara = comercial_services.construir_mascara_busqueda(
                full, search_text, COLUMNAS_BUSQUEDA_OPERACIONES, COLUMNAS_BUSQUEDA_EXACTAS_OPERACIONES)
            full = full[mascara]

        # Orden por defecto en Activaciones (24-09-2026, a pedido explícito):
        # primero las unidades con ESTADO COMERCIAL=Vigente (el caso que
        # antes vivía en "Conectividad"), el resto sin un criterio adicional
        # (queda en el orden que ya trae df_master). Solo se aplica cuando
        # Luis no eligió ordenar manualmente una columna -- self.table.
        # apply_sort() más abajo respeta y sobreescribe este orden si hay uno
        # manual activo, igual que hace con cualquier otro orden previo.
        if idx == 0 and not full.empty and COL_ESTADO_COMERCIAL in full.columns:
            es_vigente = full[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper() == 'VIGENTE'
            full = pd.concat([full[es_vigente], full[~es_vigente]]).reset_index(drop=True)

        # Conectados: primero las filas con Flota VC o CDB Flota faltante (arreglos urgentes)
        if idx == IDX_DATOS_FLOTA:
            pendiente = operaciones_services.mascara_flota_pendiente(full) if not full.empty else None
            self._actualizar_boton_faltantes(0 if pendiente is None else int(pendiente.sum()))
            if pendiente is not None:
                if self._solo_faltantes:
                    full = full[pendiente].reset_index(drop=True)
                else:
                    full = pd.concat([full[pendiente], full[~pendiente]]).reset_index(drop=True)
            varias = operaciones_services.mascara_cdb_con_varias_flotas(full) if not full.empty else None
            self._actualizar_boton_cdb_varias(0 if varias is None else int(varias.sum()))
            if varias is not None and self._solo_cdb_varias:
                full = full[varias].reset_index(drop=True)
                if COL_CDB_FLOTA in full.columns:
                    full = full.sort_values([COL_CDB_FLOTA, COL_FLOTA_VC], kind="mergesort").reset_index(drop=True)

        self._cola_full[idx] = full
        self._actualizar_titulo_barra(idx, full)
        self._actualizar_kpis(idx, cola_sin_filtrar)
        cols = [c for c in columnas_tab if c in full.columns]
        df_tabla = full[cols].copy() if not full.empty else pd.DataFrame(columns=cols)
        df_tabla = self.table.apply_sort(df_tabla)

        # FLOTA VC: a más texto, más alto la fila (no truncar/scrollear al
        # costado) -- pedido explícito 18-09-2026. Se calcula la altura UNA
        # sola vez con resizeRowsToContents() en vez de dejar el header en
        # modo ResizeToContents "vivo": ese modo recalcula el alto de TODAS
        # las filas en cada cambio (scroll, resize de columna, set_data),
        # lo que con la sombra de VolvoTableWidget (QGraphicsDropShadowEffect)
        # se vuelve visiblemente lento. Fixed conserva la altura ya calculada
        # sin seguir recalculando.
        self.table.setWordWrap(True)

        self.model.set_data(df_tabla)
        for i, col in enumerate(df_tabla.columns):
            self.table.setColumnWidth(i, ANCHOS_COLUMNAS_ACTIVACIONES.get(col, 140))
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        # Bug visual (25-09-2026, pedido explícito): con texto corto,
        # resizeRowsToContents() podía dejar filas más bajas que lo que
        # necesita el editor de celda (QLineEdit) de FLOTA VC/CDB, cortando
        # visualmente las letras al escribir. Se fuerza una altura mínima
        # después de calcular el contenido, sin afectar filas que ya
        # necesitaban ser más altas (texto largo en FLOTA VC).
        self._ajustar_alto_filas()

        # set_data quita la selección sin avisar: el panel se cierra
        self._limpiar_panel_detalle()
        self._quitar_formulario_contacto()
        self._mostrar_panel(False)

    def _actualizar_titulo_barra(self, idx, full):
        self.lbl_titulo_bandeja.setText(SUBTABS[idx][0])
        if full is None or full.empty:
            self.lbl_resumen_bandeja.setText("0 unidades" if idx != IDX_CONTACTOS else "0 CDB")
            return
        flotas = 0
        if COL_FLOTA_VC in full.columns:
            serie = full[COL_FLOTA_VC].astype(str).str.strip()
            flotas = serie[~serie.str.upper().isin(['', 'NAN', 'NONE', '-', 'NAT', *operaciones_services.FLOTAS_VC_NO_REALES])].nunique()
        n = len(full)
        if idx == IDX_CONTACTOS:
            unidades = f"{n} CDB sin contacto"
        else:
            unidades = f"{n} {'unidad' if n == 1 else 'unidades'}"
        self.lbl_resumen_bandeja.setText(f"{unidades} en {flotas} {'flota' if flotas == 1 else 'flotas'}")

    def _filas_posiblemente_multilinea(self):
        """Máscara de filas con algún texto que podría no caber en una línea
        con el ancho actual de su columna (conservadora: ante la duda, True)."""
        df = self.model.get_df()
        multilinea = np.zeros(len(df), dtype=bool)
        fuente_tabla = self.table.font()
        for i, col in enumerate(df.columns):
            fuente = self.model.data(self.model.index(0, i), Qt.ItemDataRole.FontRole)
            fuente = fuente.resolve(fuente_tabla) if fuente is not None else fuente_tabla
            metricas = QFontMetrics(fuente)
            disponible = self.table.columnWidth(i) - _HOLGURA_TEXTO_UNA_LINEA
            textos = ["" if pd.isna(v) else str(v) for v in df[col].tolist()]
            # Fuera de Latin-1 (emoji, CJK) Qt usa fuentes de respaldo con otro alto de línea: se mide siempre
            dudosos = {t: ('\n' in t or not _es_latin1(t) or metricas.horizontalAdvance(t) > disponible)
                       for t in set(textos)}
            multilinea |= np.fromiter((dudosos[t] for t in textos), dtype=bool, count=len(textos))
        return multilinea

    def _ajustar_alto_filas(self):
        """Mismo resultado que resizeRowsToContents() + mínimo ALTO_MINIMO_FILA,
        pero pide el sizeHint solo a filas que podrían ocupar más de una línea.
        resizeRowsToContents() recorría todas las celdas de todas las filas en
        el hilo de UI (varios segundos con colas de miles de unidades)."""
        vheader = self.table.verticalHeader()
        n = vheader.count()
        if n == 0:
            return
        multilinea = self._filas_posiblemente_multilinea()
        simples = np.flatnonzero(~multilinea)
        # Qt usa max(sizeHint de la fila, sectionSizeHint del encabezado); en una fila
        # de una línea el encabezado domina. Solo se asume ese alto si es constante y
        # el contenido medido queda holgadamente por debajo.
        muestra = [int(r) for r in simples[:20]] + [int(r) for r in simples[-1:]]
        altos_encabezado = {vheader.sectionSizeHint(r) for r in muestra}
        alto_contenido = max((self.table.sizeHintForRow(r) for r in muestra), default=0)
        alto_simple = max([ALTO_MINIMO_FILA] + list(altos_encabezado))
        if len(altos_encabezado) > 1 or alto_contenido + 4 > alto_simple:
            self.table.resizeRowsToContents()
            filas_a_medir = []
        else:
            for r in simples:
                vheader.resizeSection(int(r), alto_simple)
            filas_a_medir = np.flatnonzero(multilinea)
        for r in filas_a_medir:
            self.table.resizeRowToContents(int(r))
        for row in range(n):
            if vheader.sectionSize(row) < ALTO_MINIMO_FILA:
                vheader.resizeSection(row, ALTO_MINIMO_FILA)

    def filter_table(self):
        """Contrato esperado por MainWindow._on_global_search (25-09-2026):
        antes OperacionesModule solo tenía `search_input` para cumplir la
        interfaz, sin ningún filtro real detrás -- escribir en la barra de
        búsqueda global no hacía nada acá. Reaplica la cola actual con el
        texto ya cargado en self.search_input (ver _refrescar_cola)."""
        self._refrescar_tabla_actual()

    def _actualizar_estado_botones(self):
        idx = self.subtabs.currentIndex()
        cola_activa = self._cola_full.get(idx, pd.DataFrame())
        self.btn_exportar_contactos.setEnabled(idx == 0 and not cola_activa.empty)
        self.btn_exportar_vin_cdb.setEnabled(not self.model.get_df().empty)
        # "Marcar como CONECTADO" tiene sentido en Activaciones y Sin Flota
        # (resolver la unidad hacia CONECTADO); "Marcar como SIN FLOTA" solo
        # en Activaciones (sacar de ahí una unidad que todavía no aparece en
        # Volvo Connect); "Marcar como DESCONECTADO" es exclusiva de Bajas.
        # No depende solo de la señal selectionChanged: al cambiar de
        # sub-pestaña el modelo se reemplaza y la selección previa queda
        # obsoleta, así que se recalcula explícitamente para no dejar el
        # botón habilitado con VIN de la pestaña anterior.
        self.btn_marcar_conectado.setEnabled(idx in (0, IDX_SIN_FLOTA) and bool(self._get_selected_vins()))
        self.btn_marcar_sin_flota.setEnabled(idx == 0 and bool(self._get_selected_vins()))
        self.btn_marcar_desconectado.setEnabled(idx == 2 and bool(self._obtener_vins_baja_seleccionados()))
        self.btn_guardar_flota.setEnabled(self._flota_editable(self._get_selected_vins(), idx))
        self.btn_limpiar_flota.setEnabled(idx == IDX_SIN_FLOTA and bool(self._get_selected_vins()))
        self.btn_contactar_ejecutivo.setEnabled(idx != IDX_CONTACTOS and bool(self._get_selected_vins()))

    # ---------------------------------------------------------------
    # ACCIÓN: "Contactar ejecutivo" -- borrador de Outlook (sin enviar) para
    # el ejecutivo de cada unidad seleccionada; los correos salen de
    # Ejecutivos_VC.csv (ver ejecutivos_service).
    # ---------------------------------------------------------------
    @staticmethod
    def _html_borrador_ejecutivo(nombre, filas):
        def celda(valor):
            valor = '' if pd.isna(valor) else str(valor).strip()
            return html_escape(valor if valor and valor.lower() != 'nan' else '-')

        columnas = [("Cliente", "RAZÓN SOCIAL"), ("Chasis", "CHASIS"), ("VIN", "VIN"), ("CDB flota", "CDB FLOTA"),
                    ("Flota", "FLOTA VC"), ("Estado de activación", "ESTADO DE ACTIVACIÓN ACTUAL")]
        estilo_th = "background:#F3F5F9;color:#1B2B4E;padding:6px 10px;border:1px solid #E3E8F0;text-align:left;"
        estilo_td = "padding:6px 10px;border:1px solid #E3E8F0;"
        encabezado = ''.join(f'<th style="{estilo_th}">{t}</th>' for t, _ in columnas)
        cuerpo = ''.join(
            '<tr>' + ''.join(f'<td style="{estilo_td}">{celda(f.get(c, ""))}</td>' for _, c in columnas) + '</tr>'
            for f in filas
        )
        primer_nombre = str(nombre).split()[0] if str(nombre).strip() else ''
        return (
            f"<p>Hola {html_escape(primer_nombre)},</p>"
            f'<table style="border-collapse:collapse;font-family:Segoe UI,Arial,sans-serif;font-size:12px;">'
            f"<tr>{encabezado}</tr>{cuerpo}</table>"
            "<p>Quedo atento a tus comentarios.</p><p>Saludos</p>"
        )

    def _on_contactar_ejecutivo_clicked(self):
        vins = {v.upper() for v in self._get_selected_vins()}
        full = self._cola_full.get(self.subtabs.currentIndex(), pd.DataFrame())
        if not vins or full.empty or 'VIN' not in full.columns:
            return
        seleccion = full[full['VIN'].astype(str).str.strip().str.upper().isin(vins)]
        if seleccion.empty:
            return

        directorio = ejecutivos_service.leer_ejecutivos()
        por_ejecutivo, sin_correo = {}, []
        for _, fila in seleccion.iterrows():
            nombre = str(fila.get('EJECUTIVO', '')).strip()
            ejecutivo = ejecutivos_service.buscar_ejecutivo(nombre, directorio)
            correo = str(ejecutivo['correo']).strip() if ejecutivo else ''
            if not correo:
                if (nombre or '(sin ejecutivo)') not in sin_correo:
                    sin_correo.append(nombre or '(sin ejecutivo)')
                continue
            grupo = por_ejecutivo.setdefault(correo, {'nombre': ejecutivo['nombre'], 'filas': []})
            grupo['filas'].append(fila)

        borradores = []
        for correo, grupo in por_ejecutivo.items():
            filas = grupo['filas']
            if len(filas) == 1:
                asunto = f"Consulta Operaciones - {str(filas[0].get('RAZÓN SOCIAL', '')).strip()} - {str(filas[0].get('CHASIS', '')).strip()}"
            else:
                asunto = f"Consulta Operaciones - {len(filas)} unidades"
            borradores.append((correo, asunto, self._html_borrador_ejecutivo(grupo['nombre'], filas)))

        if sin_correo:
            DialogoAccion.aviso(
                self, "Ejecutivo sin correo",
                "No hay correo registrado para: " + ", ".join(sin_correo) + ".\n\n"
                "Agrégalo en el archivo de ejecutivos:\n" + ejecutivos_service.get_ejecutivos_csv_path(),
            ).exec()
        if not borradores:
            return

        from src.ui.mail_dialog import BorradorEjecutivoThread
        self.btn_contactar_ejecutivo.setEnabled(False)
        self._borrador_ejecutivo_thread = BorradorEjecutivoThread(borradores)
        self._borrador_ejecutivo_thread.finished_signal.connect(self._on_borradores_ejecutivo_listos)
        self._borrador_ejecutivo_thread.start()

    def _on_borradores_ejecutivo_listos(self, abiertos, fallidos):
        self._actualizar_estado_botones()
        if fallidos:
            DialogoAccion.aviso(
                self, "No se pudo abrir Outlook",
                f"No se pudieron abrir {fallidos} borrador(es). Verifica que Outlook esté instalado y abierto.",
            ).exec()

    def _get_selected_vins(self):
        df_visible = self.model.get_df()
        if df_visible.empty or 'VIN' not in df_visible.columns:
            return []
        filas = sorted({idx.row() for idx in self.table.selectionModel().selectedRows()})
        col_vin = df_visible.columns.get_loc('VIN')
        return [str(df_visible.iat[r, col_vin]).strip() for r in filas if 0 <= r < len(df_visible)]

    # BAJA SOLICITADA (23-09-2026, ciclo de baja anticipada Comercial ->
    # Vigentes -> Operaciones): "Marcar como DESCONECTADO" ahora también
    # actúa sobre BAJA SOLICITADA (antes solo BAJA exacto), promoviéndola a
    # BAJA -- ver operaciones_services.calcular_cambios_marcar_desconectado.
    # Ya no se reutiliza comercial_services.filtrar_gestionar_bajas (que a
    # propósito excluye BAJA SOLICITADA para la vista propia de Comercial
    # "Gestionar Bajas") porque acá el criterio de elegibilidad es distinto.
    _ESTADOS_COMERCIAL_ELEGIBLES_DESCONECTAR = {VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA}

    def _obtener_vins_baja_seleccionados(self):
        """Subconjunto de la selección actual (sub-pestaña "Bajas") cuyo
        ESTADO COMERCIAL es BAJA o BAJA SOLICITADA (22-09-2026, cierre del
        ciclo de BAJA; ampliado 23-09-2026 al ciclo de baja anticipada --
        ver "Marcar como DESCONECTADO" más abajo)."""
        vins_seleccionados = self._get_selected_vins()
        if not vins_seleccionados:
            return []
        cola = self._cola_full.get(2, pd.DataFrame())
        if cola.empty or COL_ESTADO_COMERCIAL not in cola.columns or COL_VIN not in cola.columns:
            return []
        estado = cola[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
        solo_baja = cola[estado.isin(self._ESTADOS_COMERCIAL_ELEGIBLES_DESCONECTAR)]
        if solo_baja.empty:
            return []
        vins_baja = set(solo_baja[COL_VIN].astype(str).str.strip().str.upper())
        return [v for v in vins_seleccionados if v.strip().upper() in vins_baja]

    def _fila_contacto_seleccionada(self):
        """(CDB, FLOTA VC) de la fila elegida en "Contactos", o None."""
        df = self.model.get_df()
        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if len(filas) != 1 or df.empty or COL_CDB_FLOTA not in df.columns or not 0 <= filas[0] < len(df):
            return None
        fila = df.iloc[filas[0]]
        flota = fila.get(COL_FLOTA_VC, '')
        return str(fila[COL_CDB_FLOTA]).strip(), '' if pd.isna(flota) else str(flota).strip()

    def _quitar_formulario_contacto(self):
        formulario = self._form_contacto
        if formulario is None:
            return
        self._form_contacto = None
        self._lay_contacto.removeWidget(formulario)
        formulario.hide()
        formulario.setParent(None)
        formulario.deleteLater()

    def _mostrar_formulario_contacto(self):
        """Clic en una fila de "Contactos": abre en el panel lateral el mismo
        formulario de Comercial y de Clientes y Flotas (ContactosAddDialog
        incrustado) con el CDB y la FLOTA VC de la fila ya cargados."""
        elegido = self._fila_contacto_seleccionada()
        self._quitar_formulario_contacto()
        if elegido is None:
            self._mostrar_panel(False)
            return
        cdb, flota = elegido
        formulario = ContactosAddDialog(self._bloque_contacto, cdb_prefill=cdb,
                                        flota_prefill=flota or None, embebido=True)
        formulario.setWindowFlags(Qt.WindowType.Widget)
        formulario.accepted.connect(self._on_formulario_contacto_aceptado)
        formulario.rejected.connect(self.table.clearSelection)
        self._lay_contacto.addWidget(formulario)
        formulario.show()
        self._form_contacto = formulario
        self._lbl_titulo_panel.setText("Agregar contacto")
        self._mostrar_panel(True)

    def _on_formulario_contacto_aceptado(self):
        formulario = self._form_contacto
        if formulario is None:
            return
        nuevo = formulario.get_data()
        nuevo['ID'] = contactos_service.generar_nuevo_id_contacto(self.data_manager.get_contactos_df())
        mostrar_guardando(self, "Agregando el contacto…")
        self.table.setEnabled(False)
        self._hilo_agregar_contacto = AddContactoThread(self.writer, nuevo)
        self._hilo_agregar_contacto.finished_signal.connect(self._on_agregar_contacto_finished)
        self._hilo_agregar_contacto.start()

    def _on_agregar_contacto_finished(self, success, nuevo):
        self.table.setEnabled(True)
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se pudo agregar el contacto. Verifica si contactos.xlsx está abierto.")
            self._mostrar_formulario_contacto()
            return
        terminar_guardando(self, texto_exito="Contacto agregado")
        self.data_manager.load_contactos_async()

    def _on_seleccion_cambiada(self):
        idx = self.subtabs.currentIndex()
        if idx == IDX_CONTACTOS:
            self._mostrar_formulario_contacto()
            return
        vins = self._get_selected_vins()
        self.btn_marcar_conectado.setEnabled(idx in (0, IDX_SIN_FLOTA) and bool(vins))
        self.btn_marcar_sin_flota.setEnabled(idx == 0 and bool(vins))
        self.btn_marcar_desconectado.setEnabled(idx == 2 and bool(self._obtener_vins_baja_seleccionados()))
        self.btn_guardar_flota.setEnabled(self._flota_editable(vins, idx))
        self.btn_limpiar_flota.setEnabled(idx == IDX_SIN_FLOTA and bool(vins))
        self.btn_contactar_ejecutivo.setEnabled(bool(vins))

        self._mostrar_panel(bool(vins))
        self._lbl_titulo_panel.setText(
            "Unidad seleccionada" if len(vins) <= 1 else f"{len(vins)} unidades seleccionadas"
        )
        if idx in SUBTABS_CON_DATOS_FLOTA:
            self._cargar_campos_flota(vins)
        if not vins:
            self._limpiar_panel_detalle()
            return

        current_row = self.table.currentIndex().row()
        df_visible = self.model.get_df()
        full = self._cola_full.get(idx, pd.DataFrame())
        if 0 <= current_row < len(df_visible) and 'VIN' in df_visible.columns and not full.empty:
            vin = str(df_visible.iat[current_row, df_visible.columns.get_loc('VIN')]).strip().upper()
            fila = full[full['VIN'].astype(str).str.strip().str.upper() == vin]
            if not fila.empty:
                self._pintar_panel_detalle(fila.iloc[0])
                return
        self._limpiar_panel_detalle()

    # ---------------------------------------------------------------
    # BOTÓN "Filtrar" -- checklist de clientes (RAZÓN SOCIAL) presentes en
    # la sub-pestaña activa, mismo lenguaje visual que el filtro de
    # encabezado de Comercial (comercial.py::_show_header_filter_menu),
    # pero acotado a un único criterio con sentido para una cola de
    # operaciones: por qué cliente/s se quiere ver.
    # ---------------------------------------------------------------
    @staticmethod
    def _columna_filtro(idx):
        return COL_FLOTA_VC if idx == IDX_CONTACTOS else 'RAZÓN SOCIAL'

    def _aplicar_filtros_columna(self, idx, full):
        """Cada filtro ofrece solo los valores que existen con lo elegido en los
        demás; luego deja las filas que cumplen todos."""
        columnas = {'cliente': self._columna_filtro(idx), **{c: c for c, _t, _i in _FILTROS_EXTRA}}
        series = {k: (full[c].astype(str).str.strip() if not full.empty and c in full.columns else None)
                  for k, c in columnas.items()}
        for clave, selector in self._selectores_filtro.items():
            if series[clave] is None:
                selector.set_opciones([])
                continue
            mascara = pd.Series(True, index=full.index)
            for otra, otro in self._selectores_filtro.items():
                if otra != clave and series[otra] is not None and otro.valor() is not None:
                    mascara &= series[otra] == otro.valor()
            conteo = series[clave][mascara].value_counts()
            items = [(v, f"{v} ({n})") for v, n in sorted(conteo.items()) if v and v.lower() not in ('-', 'nan', 'none')]
            selector.set_opciones([(None, items)])
        self._orden_filtros[:] = [s for s in self._orden_filtros if s.valor() is not None]
        mascara = pd.Series(True, index=full.index)
        for clave, selector in self._selectores_filtro.items():
            if series[clave] is not None and selector.valor() is not None:
                mascara &= series[clave] == selector.valor()
        self.btn_limpiar_filtros.setVisible(any(s.valor() is not None for s in self._selectores_filtro.values()))
        return full[mascara]

    def _on_filtro_cambiado(self, selector):
        estilo_com.encadenar_filtros(self._orden_filtros, selector)
        self._refrescar_tabla_actual()

    def _limpiar_filtros(self):
        for selector in self._selectores_filtro.values():
            selector.blockSignals(True)
            selector.limpiar()
            selector.blockSignals(False)
        self._orden_filtros.clear()
        self._refrescar_tabla_actual()

    # ---------------------------------------------------------------
    # BOTÓN "Exportar contactos" -- pedido de Javiera: darle al ejecutivo
    # los datos de contacto de los clientes de Activaciones. Se resuelve
    # como un Excel descargable (no hay definición de a quién/cómo
    # entregarlo automáticamente), cruzando por CDB contra Contactos.xlsx
    # -- misma fuente que usa src/ui/contactos.py, no un archivo nuevo.
    # ---------------------------------------------------------------
    def _on_exportar_contactos_clicked(self):
        full = self._cola_full.get(0, pd.DataFrame())
        if full.empty:
            return

        vins = self._get_selected_vins()
        if vins:
            vins_upper = {v.strip().upper() for v in vins}
            df_base = full[full['VIN'].astype(str).str.strip().str.upper().isin(vins_upper)]
        else:
            df_base = full

        if df_base.empty:
            QMessageBox.information(self, "Exportar contactos", "No hay unidades para exportar.")
            return

        df_contactos = self.data_manager.get_contactos_df()
        df_resultado = operaciones_services.armar_export_contactos_ejecutivo(df_base, df_contactos)
        if df_resultado.empty:
            QMessageBox.information(self, "Exportar contactos", "No hay datos para exportar.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", "Contactos_Activaciones.xlsx", "Archivos Excel (*.xlsx)"
        )
        if not filepath:
            return

        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(list(df_resultado.columns))
            for _, fila in df_resultado.iterrows():
                ws.append(["" if pd.isna(v) else v for v in fila.tolist()])
            wb.save(filepath)
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ---------------------------------------------------------------
    # BOTÓN "Exportar VIN & CDB" (29-09-2026, a pedido explícito): VIN y CDB
    # de la tabla visible (con ediciones en celda incluidas; solo las filas
    # seleccionadas si hay alguna), guardado directo en el Escritorio.
    # ---------------------------------------------------------------
    def _on_exportar_vin_cdb_clicked(self):
        df_visible = self.model.get_df()
        columnas = [c for c in ('VIN', 'CDB FLOTA', 'TIPO DE SERVICIO') if c in df_visible.columns]
        if df_visible.empty or not columnas:
            QMessageBox.information(self, "Exportar VIN & CDB", "No hay unidades para exportar.")
            return

        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        df_export = df_visible.iloc[filas] if filas else df_visible
        df_export = df_export[columnas].rename(columns={'TIPO DE SERVICIO': 'PLAN'})
        columnas = list(df_export.columns)

        pestana = self.subtabs.tabText(self.subtabs.currentIndex()).strip().replace(" ", "_")
        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        base = os.path.join(carpeta, f"VIN_CDB_{pestana}_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}")
        filepath, n = f"{base}.xlsx", 2
        while os.path.exists(filepath):
            filepath, n = f"{base}_{n}.xlsx", n + 1

        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(columnas)
            for fila in df_export.itertuples(index=False):
                ws.append(["" if pd.isna(v) else str(v) for v in fila])
            wb.save(filepath)
            QMessageBox.information(self, "Exportado",
                f"{len(df_export)} unidades guardadas en el Escritorio:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ---------------------------------------------------------------
    # PANEL FLOTANTE: ficha de la unidad + acciones (mismo diseño que las
    # acciones rápidas de Comercial)
    # ---------------------------------------------------------------
    def _build_detalle_card(self):
        # Nace colgado del módulo: armarlo suelto y moverlo después le
        # reaplicaba los estilos a todo el panel
        frame = QFrame(self)
        frame.setObjectName("accionesRapidasComercial")
        frame.setStyleSheet(estilo_com.QSS_PANEL_FLOTANTE)
        marco = QVBoxLayout(frame)
        marco.setContentsMargins(1, 1, 1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        scroll.viewport().setAutoFillBackground(False)
        contenido = QWidget()
        contenido.setAutoFillBackground(False)
        contenido.setStyleSheet("background: transparent;")
        scroll.setWidget(contenido)
        marco.addWidget(scroll)

        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        fila_titulo = QHBoxLayout()
        self._lbl_titulo_panel = self._titulo_seccion("Unidad seleccionada")
        fila_titulo.addWidget(self._lbl_titulo_panel)
        fila_titulo.addStretch()
        btn_cerrar = QPushButton()
        btn_cerrar.setIcon(ThemeManager.icon('fa5s.times', color=estilo_com.APAGADO))
        btn_cerrar.setFixedSize(26, 26)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setToolTip("Cerrar (quita la selección)")
        btn_cerrar.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        btn_cerrar.clicked.connect(lambda: self.table.clearSelection())
        fila_titulo.addWidget(btn_cerrar)
        layout.addLayout(fila_titulo)

        self._detalle_labels = {}
        self._bloque_unidad = QWidget()
        lay_u = QVBoxLayout(self._bloque_unidad)
        lay_u.setContentsMargins(0, 0, 0, 0)
        lay_u.setSpacing(10)
        lay_u.addWidget(self._build_ficha_hero())
        grilla = QGridLayout()
        grilla.setSpacing(6)
        celdas = [(c, e) for e, c, t in CAMPOS_DETALLE_ACTIVACIONES if t == "chip"]
        for i, (campo_col, etiqueta) in enumerate(celdas):
            celda, lbl_valor = estilo_com.crear_celda_ficha(etiqueta)
            grilla.addWidget(celda, i // 2, i % 2)
            self._detalle_labels[campo_col] = lbl_valor
        lay_u.addLayout(grilla)

        lay_u.addSpacing(4)
        self._bloque_datos_flota = self._build_bloque_datos_flota()
        self._bloque_datos_flota.hide()
        lay_u.addWidget(self._bloque_datos_flota)

        lay_u.addSpacing(4)
        lay_u.addWidget(self._titulo_seccion("Acciones"))
        self._grilla_acciones = QGridLayout()
        self._grilla_acciones.setSpacing(6)
        lay_u.addLayout(self._grilla_acciones)

        self.btn_marcar_conectado = BotonAccionOperaciones(
            'fa5s.check-circle', 'Conectado',
            "La unidad queda CONECTADA y su estado comercial pasa a Vigente. Si estaba en Activación Pendiente, "
            "se pide la fecha de activación en Volvo Connect como inicio del contrato; la duración se completa en Comercial.",
            estilo_com.AZUL, self._bloque_unidad)
        self.btn_marcar_conectado.setEnabled(False)
        self.btn_marcar_conectado.clicked.connect(self._on_marcar_conectado_clicked)

        # "Marcar como SIN FLOTA" (24-09-2026, a pedido explícito): saca de
        # Activaciones una unidad que todavía no aparece en Volvo Connect;
        # solo tiene sentido en Activaciones (idx 0, ver
        # _actualizar_estado_botones/_on_seleccion_cambiada) -- una unidad
        # en Sin Flota ya está SIN FLOTA, no tiene caso volver a marcarla.
        # Mismo color que "Marcar como DESCONECTADO" (29-09-2026, a pedido explícito).
        self.btn_marcar_sin_flota = BotonAccionOperaciones(
            'fa5s.truck-loading', 'Sin flota',
            "Todavía no aparece en Volvo Connect: sale de Activaciones.", estilo_com.ROJO, self._bloque_unidad)
        self.btn_marcar_sin_flota.setEnabled(False)
        self.btn_marcar_sin_flota.clicked.connect(self._on_marcar_sin_flota_clicked)

        # "Marcar como DESCONECTADO" (22-09-2026): cierra el ciclo de BAJA
        # (Comercial -> Operaciones -> Comercial), solo tiene sentido en la
        # sub-pestaña "Bajas" (idx 2, ver _actualizar_estado_botones/
        # _on_seleccion_cambiada). Rojo (25-09-2026, pedido explícito) para
        # que la acción se note como lo que es -- confirmar una baja.
        self.btn_marcar_desconectado = BotonAccionOperaciones(
            'fa5s.unlink', 'Desconectado',
            "Confirma la baja con FECHA DE BAJA de hoy.", estilo_com.ROJO, self._bloque_unidad)
        self.btn_marcar_desconectado.setEnabled(False)
        self.btn_marcar_desconectado.clicked.connect(self._on_marcar_desconectado_clicked)

        self.btn_guardar_flota = BotonAccionOperaciones(
            'fa5s.save', 'Guardar flota',
            "Guarda la Flota VC y el CDB flota escritos arriba; el contrato no cambia de estado.", estilo_com.AZUL, self._bloque_unidad)
        self.btn_guardar_flota.setEnabled(False)
        self.btn_guardar_flota.clicked.connect(self._on_guardar_flota_clicked)

        self.btn_limpiar_flota = BotonAccionOperaciones(
            'fa5s.eraser', 'Limpiar flota',
            "Deja Flota VC y CDB flota en \"-\" en todas las unidades seleccionadas, sean o no de la misma empresa.",
            estilo_com.ROJO, self._bloque_unidad)
        self.btn_limpiar_flota.setEnabled(False)
        self.btn_limpiar_flota.clicked.connect(self._on_limpiar_flota_clicked)

        self.btn_contactar_ejecutivo = BotonAccionOperaciones(
            'fa5s.envelope', 'Contactar ejecutivo',
            "Abre un borrador en Outlook para el ejecutivo de la unidad.", estilo_com.AZUL, self._bloque_unidad)
        self.btn_contactar_ejecutivo.setEnabled(False)
        self.btn_contactar_ejecutivo.clicked.connect(self._on_contactar_ejecutivo_clicked)
        self._reubicar_acciones()
        layout.addWidget(self._bloque_unidad)

        self._bloque_contacto = QWidget()
        self._lay_contacto = QVBoxLayout(self._bloque_contacto)
        self._lay_contacto.setContentsMargins(0, 0, 0, 0)
        self._lay_contacto.setSpacing(10)
        self._form_contacto = None
        self._bloque_contacto.hide()
        layout.addWidget(self._bloque_contacto)

        layout.addStretch()
        return frame

    # ---------------------------------------------------------------
    # DATOS DE FLOTA: Flota VC y CDB flota se editan en el panel derecho
    # (no en la tabla). Si el CDB ya tiene una Flota VC en el RM, se completa
    # sola y se avisa cuando se escribe otra distinta.
    # ---------------------------------------------------------------
    _QSS_CAMPO_FLOTA = (
        "QLineEdit { background: #FFFFFF; border: 1px solid #D5DCE8; border-radius: 10px; padding: 0 10px; "
        "min-height: 34px; font-size: 12px; font-weight: 600; color: #1B2B4E; }"
        "QLineEdit:focus { border: 1px solid #1B2B4E; }")

    def _build_bloque_datos_flota(self):
        bloque = QWidget()
        lay = QVBoxLayout(bloque)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._titulo_seccion("Datos de flota"))

        def etiqueta(texto):
            lbl = QLabel(texto)
            lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; font-weight: bold; background: transparent;")
            return lbl

        self._rellenando_flota = False
        self._cache_mapas_flota = (None, {}, {})
        lay.addWidget(etiqueta("CDB flota"))
        self.txt_cdb_flota = QLineEdit()
        self.txt_cdb_flota.setStyleSheet(self._QSS_CAMPO_FLOTA)
        self.txt_cdb_flota.textEdited.connect(self._on_cdb_flota_editado)
        lay.addWidget(self.txt_cdb_flota)
        lay.addWidget(etiqueta("Flota VC"))
        self.txt_flota_vc = QLineEdit()
        self.txt_flota_vc.setStyleSheet(self._QSS_CAMPO_FLOTA)
        self.txt_flota_vc.textEdited.connect(self._on_flota_vc_editada)
        lay.addWidget(self.txt_flota_vc)
        self._completer_cdb = QCompleter([], self.txt_cdb_flota)
        self._completer_cdb.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer_cdb.setFilterMode(Qt.MatchFlag.MatchContains)
        self.txt_cdb_flota.setCompleter(self._completer_cdb)
        self._completer_flota = QCompleter([], self.txt_flota_vc)
        self._completer_flota.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer_flota.setFilterMode(Qt.MatchFlag.MatchContains)
        self.txt_flota_vc.setCompleter(self._completer_flota)

        self.lbl_aviso_flota = QLabel("")
        self.lbl_aviso_flota.setWordWrap(True)
        self.lbl_aviso_flota.setStyleSheet(
            "color: #92400E; background: #FEF3C7; border-radius: 8px; padding: 6px 8px; font-size: 11px; font-weight: 600;")
        self.lbl_aviso_flota.hide()
        lay.addWidget(self.lbl_aviso_flota)

        self.lbl_aviso_empresas = QLabel(
            "Seleccionaste unidades de distintas empresas: para editar la Flota VC y el CDB flota "
            "juntas, deben tener la misma razón social o RUT.")
        self.lbl_aviso_empresas.setWordWrap(True)
        self.lbl_aviso_empresas.setStyleSheet(
            "color: #92400E; background: #FEF3C7; border-radius: 8px; padding: 6px 8px; font-size: 11px; font-weight: 600;")
        self.lbl_aviso_empresas.hide()
        lay.addWidget(self.lbl_aviso_empresas)
        return bloque

    @staticmethod
    def _texto_flota_limpio(valor):
        texto = '' if valor is None or pd.isna(valor) else str(valor).strip()
        texto = texto[:-2] if texto.endswith('.0') else texto
        return '' if texto.upper() in ('', '-', 'NAN', 'NONE', 'NAT', '<NA>') else texto

    def _mapas_flota(self):
        """(CDB mayúsculas -> [Flota VC], Flota VC mayúsculas -> [CDB]) de todo el RM."""
        df = self.df_master
        clave = (id(df), len(df) if df is not None else 0)
        if self._cache_mapas_flota[0] == clave:
            return self._cache_mapas_flota[1], self._cache_mapas_flota[2]
        por_cdb, por_flota = {}, {}
        if df is not None and not df.empty and COL_CDB_FLOTA in df.columns and COL_FLOTA_VC in df.columns:
            pares = df[[COL_CDB_FLOTA, COL_FLOTA_VC]].drop_duplicates()
            for cdb, flota in zip(pares[COL_CDB_FLOTA], pares[COL_FLOTA_VC]):
                cdb, flota = self._texto_flota_limpio(cdb), self._texto_flota_limpio(flota)
                if not cdb or not flota or flota.upper() in operaciones_services.FLOTAS_VC_NO_REALES:
                    continue
                if flota not in por_cdb.setdefault(cdb.upper(), []):
                    por_cdb[cdb.upper()].append(flota)
                if cdb not in por_flota.setdefault(flota.upper(), []):
                    por_flota[flota.upper()].append(cdb)
        self._cache_mapas_flota = (clave, por_cdb, por_flota)
        return por_cdb, por_flota

    def _poner_texto_flota(self, campo, texto):
        campo.blockSignals(True)
        campo.setText(texto)
        campo.blockSignals(False)

    def _cargar_campos_flota(self, vins):
        por_cdb, por_flota = self._mapas_flota()
        self._completer_cdb.model().setStringList(sorted(por_cdb.keys()))
        self._completer_flota.model().setStringList(sorted({f for lista in por_cdb.values() for f in lista}))
        cdb = flota = ''
        placeholder = "Sin cambios"
        mezcladas = len(vins) > 1 and not self._vins_misma_empresa(vins, self.subtabs.currentIndex())
        cola = self._cola_full.get(self.subtabs.currentIndex(), pd.DataFrame())
        if len(vins) == 1:
            if not cola.empty:
                fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == vins[0].strip().upper()]
                if not fila.empty:
                    cdb = self._texto_flota_limpio(fila.iloc[0].get(COL_CDB_FLOTA))
                    flota = self._texto_flota_limpio(fila.iloc[0].get(COL_FLOTA_VC))
            placeholder = "Sin dato"
        elif not mezcladas and not cola.empty:
            # Varias unidades de una misma empresa: si todas traen el mismo
            # valor, el panel lo muestra en vez de quedar en blanco.
            claves = {v.strip().upper() for v in vins}
            filas = cola[cola['VIN'].astype(str).str.strip().str.upper().isin(claves)]
            if len(filas) == len(claves):
                cdbs = {self._texto_flota_limpio(v) for v in filas[COL_CDB_FLOTA]}
                flotas = {self._texto_flota_limpio(v) for v in filas[COL_FLOTA_VC]}
                if len(cdbs) == 1:
                    cdb = next(iter(cdbs))
                if len(flotas) == 1:
                    flota = next(iter(flotas))
                if len(cdbs) > 1 or len(flotas) > 1:
                    placeholder = "Varios valores"
        if mezcladas:
            placeholder = "Una sola empresa"
        self.txt_cdb_flota.setPlaceholderText(placeholder)
        self.txt_flota_vc.setPlaceholderText(placeholder)
        self.txt_cdb_flota.setEnabled(not mezcladas)
        self.txt_flota_vc.setEnabled(not mezcladas)
        self.lbl_aviso_empresas.setVisible(mezcladas)
        self._poner_texto_flota(self.txt_cdb_flota, cdb)
        self._poner_texto_flota(self.txt_flota_vc, flota)
        self._actualizar_aviso_flota()

    def _on_cdb_flota_editado(self, texto):
        por_cdb, _ = self._mapas_flota()
        flotas = por_cdb.get(texto.strip().upper(), [])
        if flotas:
            self._completer_flota.model().setStringList(flotas)
            if len(flotas) == 1:
                self._poner_texto_flota(self.txt_flota_vc, flotas[0])
        self._actualizar_aviso_flota()

    def _on_flota_vc_editada(self, texto):
        _, por_flota = self._mapas_flota()
        cdbs = por_flota.get(texto.strip().upper(), [])
        if len(cdbs) == 1 and not self.txt_cdb_flota.text().strip():
            self._poner_texto_flota(self.txt_cdb_flota, cdbs[0])
        self._actualizar_aviso_flota()

    def _flotas_conocidas_del_cdb(self):
        cdb = self.txt_cdb_flota.text().strip()
        por_cdb, _ = self._mapas_flota()
        return por_cdb.get(cdb.upper(), []) if cdb else []

    def _aviso_flota_distinta(self):
        """Texto de aviso si la Flota VC escrita no es ninguna de las que el RM ya
        asocia a ese CDB flota; '' si coincide o no hay nada que comparar."""
        flota = self.txt_flota_vc.text().strip()
        conocidas = self._flotas_conocidas_del_cdb()
        if flota and conocidas and flota.upper() not in {f.upper() for f in conocidas}:
            return f"El CDB {self.txt_cdb_flota.text().strip()} ya está asociado a: {', '.join(conocidas)}."
        return ''

    def _actualizar_aviso_flota(self):
        aviso = self._aviso_flota_distinta()
        self.lbl_aviso_flota.setText(aviso)
        self.lbl_aviso_flota.setVisible(bool(aviso))

    @staticmethod
    def _titulo_seccion(texto):
        lbl = QLabel(texto)
        fuente = lbl.font()
        fuente.setCapitalization(QFont.Capitalization.AllUppercase)
        lbl.setFont(fuente)
        lbl.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        return lbl

    def _build_ficha_hero(self):
        """Iniciales + Razón social + Chasis (clic para copiar) y VIN."""
        hero = QFrame()
        hero.setObjectName("fichaHeroComercial")
        hero.setStyleSheet(estilo_com.QSS_FICHA_HERO)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(12, 12, 12, 12)
        hero_layout.setSpacing(12)
        self._ficha_avatar = QLabel("--")
        self._ficha_avatar.setFixedSize(46, 46)
        self._ficha_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ficha_avatar.setStyleSheet(estilo_com.QSS_FICHA_AVATAR)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        nombre = QLabel("—")
        nombre.setWordWrap(True)
        nombre.setStyleSheet(estilo_com.QSS_FICHA_NOMBRE)
        self._detalle_labels['RAZÓN SOCIAL'] = nombre

        nombre.setCursor(Qt.CursorShape.PointingHandCursor)
        nombre.setToolTip("Clic para copiar")
        nombre.mousePressEvent = lambda event: self._copiar_valor_detalle('RAZÓN SOCIAL')

        textos.addWidget(nombre)
        for prefijo, campo_col in (("Chasis", 'CHASIS'), ("CDB comercial", 'CDB'),
                                   ("N° contrato", 'ID'), ("VIN", 'VIN')):
            textos.addLayout(self._fila_copiable(prefijo, campo_col))
        hero_layout.addWidget(self._ficha_avatar)
        hero_layout.addLayout(textos, stretch=1)
        return hero

    def _fila_copiable(self, prefijo, campo_col):
        """Fila 'Prefijo valor [icono]' de la ficha; un clic copia el valor."""
        fila = QHBoxLayout()
        fila.setSpacing(4)
        etiqueta = QLabel(prefijo)
        etiqueta.setStyleSheet(estilo_com.QSS_FICHA_CHASIS)
        valor = QLabel("—")
        valor.setStyleSheet(estilo_com.QSS_FICHA_CHASIS + " font-weight: bold;")
        valor.setCursor(Qt.CursorShape.PointingHandCursor)
        valor.setToolTip("Clic para copiar")
        valor.mousePressEvent = lambda event, c=campo_col: self._copiar_valor_detalle(c)
        icono_copiar = QLabel()
        icono_copiar.setPixmap(ThemeManager.icon_pixmap('fa5s.copy', color=TEXT_MUTED, size=11))
        icono_copiar.setStyleSheet("background: transparent; border: none;")
        fila.addWidget(etiqueta)
        fila.addWidget(valor)
        fila.addWidget(icono_copiar)
        fila.addStretch()
        self._detalle_labels[campo_col] = valor
        return fila

    def _copiar_valor_detalle(self, campo_col):
        texto = self._detalle_labels[campo_col].text()
        if texto and texto != "—":
            QApplication.clipboard().setText(texto)

    def _pintar_panel_detalle(self, fila):
        for etiqueta, campo_col, tipo in CAMPOS_DETALLE_ACTIVACIONES:
            valor = fila.get(campo_col, "")
            valor = "" if pd.isna(valor) else str(valor).strip()
            if valor.lower() in ("nan", "nat"):
                valor = ""
            if campo_col == COL_ID:
                valor = comercial_services._normalizar_id_contrato(valor)
            elif campo_col == COL_CDB:
                valor = self._texto_flota_limpio(valor)
            lbl = self._detalle_labels[campo_col]
            if tipo == "chip":
                estilo_com.pintar_chip_ficha(lbl, valor)
            else:
                lbl.setText(valor or "—")
        self._ficha_avatar.setText(estilo_com.iniciales(self._detalle_labels['RAZÓN SOCIAL'].text()))

    def _limpiar_panel_detalle(self):
        for etiqueta, campo_col, tipo in CAMPOS_DETALLE_ACTIVACIONES:
            lbl = self._detalle_labels[campo_col]
            if tipo == "chip":
                estilo_com.pintar_chip_ficha(lbl, "")
            else:
                lbl.setText("—")
        self._ficha_avatar.setText("--")

    # ---------------------------------------------------------------
    # ACCIÓN: "Marcar como CONECTADO" -- escribe de verdad en PruebasFM.xlsx
    # (mismo mecanismo que comercial.py: ExcelWriter.update_cells vía
    # SaveExcelThread, y actualización de DataManager.df_master al terminar).
    # Disponible tanto en Activaciones como en Sin Flota: en ambos casos el
    # operador está resolviendo una unidad hacia el estado CONECTADO, y en
    # ambos se fuerza además ESTADO COMERCIAL = Vigente (22-09-2026, cierra
    # el ciclo de reactivación Comercial "Gestionar Bajas" -> Operaciones).
    # Desde Sin Flota (24-09-2026, a pedido explícito), CDB y FLOTA VC son
    # obligatorios (se editan en la tabla) y se guardan junto con el
    # cambio de estado en la misma operación -- ExcelWriter.update_cells ya
    # soporta varias columnas por VIN en una sola llamada.
    # ---------------------------------------------------------------
    def _valor_actual_celda(self, vin, col_name):
        """Valor vigente (editado o no) de `col_name` para `vin` en la
        tabla visible de la sub-pestaña activa -- fuente de verdad para
        FLOTA VC/CDB al guardar (24-09-2026, ver _COLUMNAS_EDITABLES en
        OperacionesTableModel). A diferencia de _cola_full (que guarda el
        valor tal como llegó de la última carga real), self.model.get_df()
        refleja cualquier edición en memoria que el usuario haya hecho
        directo en la celda antes de presionar "Marcar como...", que es
        donde se guarda de verdad (no hay un botón de guardado aparte)."""
        df_visible = self.model.get_df()
        if df_visible.empty or 'VIN' not in df_visible.columns or col_name not in df_visible.columns:
            return None
        mask = df_visible['VIN'].astype(str).str.strip().str.upper() == str(vin).strip().upper()
        fila = df_visible[mask]
        if fila.empty:
            return None
        valor = fila.iloc[0][col_name]
        return '' if pd.isna(valor) else str(valor).strip()

    def _vins_misma_empresa(self, vins, idx):
        """True si todas las unidades comparten razón social o RUT."""
        if len(vins) <= 1:
            return True
        cola = self._cola_full.get(idx, pd.DataFrame())
        if cola.empty:
            return False
        claves = {str(v).strip().upper() for v in vins}
        filas = cola[cola['VIN'].astype(str).str.strip().str.upper().isin(claves)]
        if filas.empty:
            return False

        def unico(col):
            if col not in filas.columns:
                return False
            valores = {self._texto_flota_limpio(v).upper() for v in filas[col]}
            return len(valores) == 1 and '' not in valores

        return unico(COL_RAZON_SOCIAL) or unico(COL_RUT)

    def _flota_editable(self, vins, idx):
        return idx in SUBTABS_CON_DATOS_FLOTA and bool(vins) and self._vins_misma_empresa(vins, idx)

    def _flota_efectiva(self, vin, idx):
        """(CDB flota, Flota VC) con que queda una unidad al guardar: lo escrito
        en el panel (vale para todas las seleccionadas) y, si ese campo está
        vacío, el dato que ya tiene la unidad."""
        cola = self._cola_full.get(idx, pd.DataFrame())
        cdb_act = flota_act = ''
        if not cola.empty:
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == str(vin).strip().upper()]
            if not fila.empty:
                cdb_act = self._texto_flota_limpio(fila.iloc[0].get(COL_CDB_FLOTA))
                flota_act = self._texto_flota_limpio(fila.iloc[0].get(COL_FLOTA_VC))
        return (self.txt_cdb_flota.text().strip() or cdb_act, self.txt_flota_vc.text().strip() or flota_act)

    def _solo_contratos_abiertos(self, vins, idx):
        abiertos, cerrados = operaciones_services.separar_vins_contrato_abierto(self._cola_full.get(idx, pd.DataFrame()), vins)
        if cerrados:
            DialogoAccion.aviso(
                self, "Contrato finalizado",
                "Estos VIN tienen un contrato en baja: solo se pueden desconectar. Si el cliente vuelve, "
                "Comercial crea un contrato nuevo.",
                items=cerrados, titulo_items="VIN con contrato finalizado",
            ).exec()
        return abiertos

    def _confirmar_conexion(self, filas, vins, idx, pendientes):
        """Panel de confirmación de "Conectado": tabla con el CDB flota y la
        Flota VC que quedarán en cada unidad y, si hay unidades en Activación
        Pendiente, la fecha de activación en Volvo Connect (será su inicio de
        contrato). Devuelve la fecha DD-MM-YYYY ('' si no se pidió fecha) o
        None si se cancela."""
        n = len(vins)
        sin_duracion = [v for v in pendientes if operaciones_services.duracion_sin_dato(filas[v])]
        con_fecha = [v for v in pendientes if str(filas[v].get('INICIO CONTRATO', '')).strip().upper() not in ('', '-', 'NAN', 'NAT')]

        if pendientes:
            descripcion = (f"{'La unidad estaba' if len(pendientes) == 1 else f'{len(pendientes)} unidades estaban'} en Activación Pendiente. "
                           "Indica la fecha en que se activó en Volvo Connect: será el inicio del contrato.")
            if con_fecha:
                descripcion += f" Reemplaza el inicio que ya tienen {len(con_fecha)} de ellas."
        else:
            descripcion = "Revisa el CDB flota y la Flota VC que quedarán en cada unidad antes de conectar."

        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        selector = None
        if pendientes:
            etiqueta = QLabel("Fecha de activación en Volvo Connect")
            etiqueta.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
            lay.addWidget(etiqueta)
            selector = SelectorFecha(QDate.currentDate(), QDate.currentDate())
            lay.addWidget(selector, alignment=Qt.AlignmentFlag.AlignLeft)
            if sin_duracion:
                aviso = QLabel(
                    f"{'1 unidad no tiene' if len(sin_duracion) == 1 else f'{len(sin_duracion)} unidades no tienen'} duración: "
                    "el término del contrato no se calculará hasta que Comercial la complete.")
                aviso.setWordWrap(True)
                aviso.setStyleSheet(f"color: {WARNING}; font-size: 12px; font-weight: bold;")
                lay.addWidget(aviso)
            lay.addSpacing(4)

        titulo_tabla = QLabel(f"Unidades a conectar ({n})")
        titulo_tabla.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        lay.addWidget(titulo_tabla)

        tabla = QTableWidget(n, 3)
        tabla.setHorizontalHeaderLabels(["VIN", "CDB flota", "Flota VC"])
        tabla.verticalHeader().hide()
        tabla.verticalHeader().setDefaultSectionSize(32)
        tabla.setShowGrid(False)
        tabla.setAlternatingRowColors(True)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tabla.setTextElideMode(Qt.TextElideMode.ElideRight)
        tabla.setWordWrap(False)
        cab = tabla.horizontalHeader()
        cab.setHighlightSections(False)
        cab.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        cab.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tabla.setColumnWidth(0, 175)
        tabla.setColumnWidth(1, 110)
        tabla.setStyleSheet(f"""
            QTableWidget {{ background-color: #FFFFFF; alternate-background-color: #F8FAFC; border: 1px solid #E3E8F0;
                            border-radius: 10px; color: {TEXT_PRIMARY}; font-size: 12px; outline: none; }}
            QTableWidget::item {{ padding: 0 10px; border: none; }}
            QHeaderView::section {{ background-color: #F3F5F9; color: {TEXT_SECONDARY}; font-size: 11px; font-weight: bold;
                                    border: none; border-bottom: 1px solid #E3E8F0; padding: 6px 10px; text-align: left; }}
        """)
        for fila_i, v in enumerate(vins):
            cdb_v, flota_v = self._flota_efectiva(v, idx)
            for col, texto in enumerate((v.strip().upper(), cdb_v, flota_v)):
                celda = QTableWidgetItem(texto)
                celda.setToolTip(texto)
                celda.setFlags(Qt.ItemFlag.ItemIsEnabled)
                tabla.setItem(fila_i, col, celda)
        tabla.setFixedHeight(min(262, 44 + 32 * n))
        lay.addWidget(tabla)

        dialogo = DialogoAccion(
            self, " Confirmar conexión",
            icon_name="fa5s.calendar-check" if pendientes else "fa5s.check-circle", icon_color=PRIMARY, icon_bg_color="#DBEAFE",
            titulo="Fecha de inicio del contrato" if pendientes else "Confirmar conexión", subtitulo=None, descripcion=descripcion,
            botones=[{'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                     {'texto': 'Conectar', 'clase': 'primary', 'rol': 'accept'}],
            widget_extra=cuerpo, ancho=640)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        return selector.date().toString("dd-MM-yyyy") if selector is not None else ''

    def _on_marcar_conectado_clicked(self):
        idx = self.subtabs.currentIndex()
        vins = self._solo_contratos_abiertos(self._get_selected_vins(), idx)
        if not vins:
            return

        # CDB flota y Flota VC son obligatorios para conectar. Lo escrito en el
        # panel vale para todas las unidades seleccionadas; con un campo vacío
        # cada unidad conserva el suyo. Se valida cada VIN por separado.
        faltantes = [
            v for v in vins
            if not self._flota_efectiva(v, idx)[0]
            or self._flota_efectiva(v, idx)[1].upper() in ('', operaciones_services.FLOTA_VC_NO_EXISTE)
        ]
        if faltantes:
            DialogoAccion.aviso(
                self, "Faltan datos",
                "CDB flota y Flota VC son obligatorios antes de marcar como CONECTADO. "
                "Escríbelos en el panel (\"NO EXISTE EN VC\" no sirve para conectar). "
                "Faltan en estos VIN:",
                items=faltantes, titulo_items="VIN sin CDB flota o Flota VC",
            ).exec()
            return

        # Cada VIN recalcula su propia ETAPA GESTIÓN con la matriz de
        # negocio (ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ, ver
        # operaciones_services.calcular_cambios_marcar_conectado) en vez de
        # aplicar el mismo diccionario de cambios a todos -- alineado con
        # el riesgo detectado 24-09-2026 (ETAPA GESTIÓN transitoria e
        # inconsistente con la matriz si no se recalcula aquí).
        cola = self._cola_full.get(idx, pd.DataFrame())
        filas = {}
        for v in vins:
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == v.strip().upper()]
            filas[v.strip().upper()] = fila.iloc[0].to_dict() if not fila.empty else {}

        # Unidades en Activación Pendiente: su inicio de contrato es la fecha
        # en que se activan en Volvo Connect, que elige quien conecta.
        pendientes = [v for v, f in filas.items() if operaciones_services.es_activacion_pendiente(f)]
        fecha_inicio = self._confirmar_conexion(filas, vins, idx, pendientes)
        if fecha_inicio is None:
            return
        fecha_inicio = fecha_inicio or None

        self._vins_en_guardado = vins
        changes = {}
        for v in vins:
            v_upper = v.strip().upper()
            fila_dict = filas[v_upper]
            cdb_v, flota_vc_v = self._flota_efectiva(v, idx)
            cambios = operaciones_services.calcular_cambios_marcar_conectado(
                fila_dict, cdb=cdb_v, flota_vc=flota_vc_v, fecha_inicio=fecha_inicio)
            changes[v_upper] = {'VIN': v.strip(), 'cambios': cambios}
        comercial_services.agregar_id_a_cambios(changes, self.df_master)

        # Guardado para que _on_marcar_conectado_finished aplique en RAM
        # exactamente lo mismo que se acaba de escribir en el Excel/CSV
        # real, sin volver a leer currentIndex() (que puede haber cambiado
        # mientras el guardado estaba en curso).
        self._cambios_conectado_por_vin = changes

        self.btn_marcar_conectado.setEnabled(False)
        self.btn_marcar_conectado.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando VIN como CONECTADO…")

        self.save_thread = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread.finished_signal.connect(self._on_marcar_conectado_finished)
        self.save_thread.start()

    def _on_marcar_conectado_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_marcar_conectado.setText('Conectado')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, getattr(self, '_cambios_conectado_por_vin', {})
                )

            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_marcar_conectado.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    # ---------------------------------------------------------------
    # ACCIÓN: "Marcar como SIN FLOTA" (24-09-2026, a pedido explícito) --
    # para camiones que todavía no aparecen en Volvo Connect. Solo tiene
    # sentido en Activaciones (idx 0, ver _actualizar_estado_botones); saca
    # la unidad de Activaciones (ya no cumple ESTADO DE ACTIVACIÓN ACTUAL en
    # {Activando, No entregado}) y, según ESTADO_COMERCIAL_ACTIVACION_
    # ETAPA_MATRIZ (constants.py), pasa a la nueva pestaña "Sin Flota" si su
    # ESTADO COMERCIAL es Activación Pendiente o Vigente (las únicas dos
    # filas que la matriz manda a OPERACIONES para SIN FLOTA); si es
    # cualquier otro ESTADO COMERCIAL (Revisar/Vencido/Baja/Baja Solicitada),
    # la matriz la manda a COMERCIAL y la unidad pasa a gestionarse desde
    # ahí, no desde Operaciones -- ver calcular_cambios_marcar_sin_flota, que
    # recalcula ETAPA GESTIÓN con esa misma matriz al guardar (24-09-2026,
    # corrige un riesgo detectado el mismo día: sin este recálculo, una
    # unidad Vigente+Activando marcada Sin Flota quedaba sin cola visible en
    # ningún lado de la app). No toca ESTADO COMERCIAL, solo ESTADO DE
    # ACTIVACIÓN ACTUAL y ETAPA GESTIÓN.
    # ---------------------------------------------------------------
    def _on_marcar_sin_flota_clicked(self):
        vins = self._solo_contratos_abiertos(self._get_selected_vins(), 0)
        if not vins:
            return

        self._vins_en_guardado = vins
        # Cada VIN recalcula su propia ETAPA GESTIÓN con la matriz de
        # negocio (ver operaciones_services.calcular_cambios_marcar_sin_flota)
        # -- una unidad cuyo ESTADO COMERCIAL no da OPERACIONES para SIN
        # FLOTA (solo Activación Pendiente y Vigente lo hacen) pasa a
        # ETAPA GESTIÓN=COMERCIAL de inmediato, sin depender de la próxima
        # carga real.
        cola = self._cola_full.get(0, pd.DataFrame())
        changes = {}
        for v in vins:
            v_upper = v.strip().upper()
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == v_upper]
            fila_dict = fila.iloc[0].to_dict() if not fila.empty else {}
            # Igual que al conectar: lo escrito en el panel, o el dato actual de cada unidad
            cdb_v, flota_vc_v = self._flota_efectiva(v, 0)
            cambios = operaciones_services.calcular_cambios_marcar_sin_flota(
                fila_dict, cdb=cdb_v, flota_vc=flota_vc_v
            )
            changes[v_upper] = {'VIN': v.strip(), 'cambios': cambios}
        comercial_services.agregar_id_a_cambios(changes, self.df_master)
        self._cambios_sin_flota_por_vin = changes

        self.btn_marcar_sin_flota.setEnabled(False)
        self.btn_marcar_sin_flota.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando VIN como SIN FLOTA…")

        self.save_thread_sin_flota = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_sin_flota.finished_signal.connect(self._on_marcar_sin_flota_finished)
        self.save_thread_sin_flota.start()

    def _on_marcar_sin_flota_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_marcar_sin_flota.setText('Sin flota')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, getattr(self, '_cambios_sin_flota_por_vin', {})
                )

            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_marcar_sin_flota.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    # ---------------------------------------------------------------
    # ACCIÓN: "Guardar datos de flota" (13-10-2026) -- contratos Vigentes y
    # Conectados: se guarda lo escrito en los campos CDB flota / Flota VC del
    # panel, sin tocar estados. Con varias unidades, un campo vacío conserva
    # el valor de cada una; cada unidad debe quedar con ambos datos.
    # ---------------------------------------------------------------
    def _on_guardar_flota_clicked(self):
        vins = self._get_selected_vins()
        if not vins or not self._flota_editable(vins, self.subtabs.currentIndex()):
            return
        nueva_flota = self.txt_flota_vc.text().strip()
        nuevo_cdb = self.txt_cdb_flota.text().strip()
        cola = self._cola_full.get(self.subtabs.currentIndex(), pd.DataFrame())
        actuales = {}
        if not cola.empty:
            for _, fila in cola.iterrows():
                actuales[str(fila['VIN']).strip().upper()] = (
                    self._texto_flota_limpio(fila.get(COL_FLOTA_VC)), self._texto_flota_limpio(fila.get(COL_CDB_FLOTA)))

        changes, faltantes = {}, []
        for v in vins:
            flota_act, cdb_act = actuales.get(v.strip().upper(), ('', ''))
            flota, cdb = nueva_flota or flota_act, nuevo_cdb or cdb_act
            if not flota or not cdb:
                faltantes.append(v)
            elif (flota, cdb) != (flota_act, cdb_act):
                changes[v.strip().upper()] = {'VIN': v.strip(), 'cambios': {COL_FLOTA_VC: flota, COL_CDB_FLOTA: cdb}}
        if faltantes:
            DialogoAccion.aviso(
                self, "Faltan datos",
                "Escribe la Flota VC y el CDB flota en el panel para estos VIN:",
                items=faltantes, titulo_items="VIN sin Flota VC o CDB flota",
            ).exec()
            return
        if not changes:
            QMessageBox.information(self, "Sin cambios", "Los datos escritos son iguales a los que ya tiene la unidad.")
            return
        aviso = self._aviso_flota_distinta()
        if aviso and QMessageBox.question(
                self, "Flota VC distinta",
                f"{aviso}\n\nLa Flota VC escrita es otra. ¿Guardar de todos modos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        flota_por_cdb = {c['cambios'][COL_CDB_FLOTA]: c['cambios'][COL_FLOTA_VC] for c in changes.values()}
        extras = operaciones_services.construir_cambios_propagar_flota(self.df_master, flota_por_cdb, changes.keys())
        if extras:
            detalle = "\n".join(f"• CDB {cdb}: {flota}" for cdb, flota in flota_por_cdb.items())
            respuesta = QMessageBox.question(
                self, "Aplicar a las demás unidades",
                f"Hay {len(extras)} unidad(es) más con el mismo CDB flota y sin Flota VC:\n{detalle}\n\n"
                "¿Completarles también esa Flota VC?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if respuesta == QMessageBox.StandardButton.Yes:
                changes.update(extras)
        vins = [c['VIN'] for c in changes.values()]
        comercial_services.agregar_id_a_cambios(changes, self.df_master)
        self._vins_en_guardado_flota = vins
        self._cambios_en_guardado_flota = changes

        self.btn_guardar_flota.setEnabled(False)
        self.btn_guardar_flota.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Guardando datos de flota…")

        self.save_thread_flota = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_flota.finished_signal.connect(self._on_guardar_flota_finished)
        self.save_thread_flota.start()

    def _on_guardar_flota_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_guardar_flota.setText('Guardar flota')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, self._cambios_en_guardado_flota)
            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_guardar_flota.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    def _on_limpiar_flota_clicked(self):
        """"Limpiar flota" (Sin Flota): Flota VC y CDB flota quedan en "-" en
        todas las unidades seleccionadas, sin exigir que sean de la misma empresa."""
        vins = self._get_selected_vins()
        if not vins:
            return
        if QMessageBox.question(
                self, "Limpiar flota",
                f"Flota VC y CDB flota quedarán en \"-\" en {len(vins)} unidad(es). ¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        changes = {v.strip().upper(): {'VIN': v.strip(), 'cambios': {COL_FLOTA_VC: '-', COL_CDB_FLOTA: '-'}} for v in vins}
        comercial_services.agregar_id_a_cambios(changes, self.df_master)
        self._cambios_en_guardado_flota = changes

        self.btn_limpiar_flota.setEnabled(False)
        self.btn_limpiar_flota.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Limpiando datos de flota…")
        self.save_thread_flota = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_flota.finished_signal.connect(self._on_limpiar_flota_finished)
        self.save_thread_flota.start()

    def _on_limpiar_flota_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_limpiar_flota.setText('Limpiar flota')
        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, self._cambios_en_guardado_flota)
            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_limpiar_flota.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    # ---------------------------------------------------------------
    # ACCIÓN: "Marcar como DESCONECTADO" -- cierra el ciclo de BAJA
    # (Comercial -> Operaciones -> Comercial), exclusivamente para
    # ESTADO COMERCIAL == "BAJA" (nunca BAJA SOLICITADA, ver
    # _obtener_vins_baja_seleccionados). Mismo mecanismo de guardado que
    # "Marcar como CONECTADO" (SaveExcelThread + ExcelWriter.update_cells),
    # pero a diferencia de esa acción SÍ recalcula y persiste ETAPA GESTIÓN
    # junto con ESTADO DE ACTIVACIÓN ACTUAL, reutilizando la matriz de
    # negocio existente (operaciones_services.calcular_cambios_marcar_
    # desconectado -> DataFrameFormatter.calcular_etapa_gestion_esperada) y
    # comercial_services.aplicar_cambios_pendientes para la actualización en
    # RAM (mismo helper que ya usa comercial.py, no una nueva reimplementación
    # del mask-por-VIN).
    # ---------------------------------------------------------------
    def _on_marcar_desconectado_clicked(self):
        vins = self._obtener_vins_baja_seleccionados()
        if not vins:
            return

        cola = self._cola_full.get(2, pd.DataFrame())
        changes = {}
        for v in vins:
            v_upper = v.strip().upper()
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == v_upper]
            fila_dict = fila.iloc[0].to_dict() if not fila.empty else {}
            cambios = operaciones_services.calcular_cambios_marcar_desconectado(fila_dict)
            changes[v_upper] = {'VIN': v.strip(), 'cambios': cambios}
        comercial_services.agregar_id_a_cambios(changes, self.df_master)

        self._vins_en_guardado_baja = vins
        self._cambios_en_guardado_baja = changes

        self.btn_marcar_desconectado.setEnabled(False)
        self.btn_marcar_desconectado.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando VIN como DESCONECTADO…")

        self.save_thread_desconectado = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_desconectado.finished_signal.connect(self._on_marcar_desconectado_finished)
        self.save_thread_desconectado.start()

    def _on_marcar_desconectado_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_marcar_desconectado.setText('Desconectado')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, self._cambios_en_guardado_baja
                )

            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_marcar_desconectado.setEnabled(bool(self._obtener_vins_baja_seleccionados()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()
