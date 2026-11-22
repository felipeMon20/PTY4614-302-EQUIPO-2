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
                             QGraphicsDropShadowEffect, QGridLayout, QScrollArea, QTableWidget, QTableWidgetItem, QCheckBox,
                             QSizePolicy)
from PyQt6.QtCore import (Qt, QSize, QThread, pyqtSignal, QStandardPaths, QEvent, QPoint, QRect,
                          QTimer, QPropertyAnimation, QEasingCurve, QUrl, QDate)
from PyQt6.QtGui import QKeySequence, QFontMetrics, QColor, QFont, QDesktopServices
from PyQt6.QtCore import QObject


class _IgnorarSeleccionClicDerecho(QObject):
    """El clic derecho abre el menú de la fila sin seleccionarla ni cambiar la selección actual."""

    _EVENTOS = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick)

    def eventFilter(self, objeto, evento):
        return evento.type() in self._EVENTOS and evento.button() == Qt.MouseButton.RightButton
import config.settings
from config.settings import REPORTE_NOTAS_VENTAS_URL
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.constants import (COL_VIN, COL_ESTADO_COMERCIAL, VALOR_ESTADO_COMERCIAL_BAJA,
                                VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA,
                                COL_RAZON_SOCIAL, COL_CDB_FLOTA, COL_RUT, COL_FLOTA_VC, COL_ID, COL_ESTADO_ACTIVACION,
                                COL_CDB)
from src.services import comercial_services, operaciones_services, contactos_service, ejecutivos_service
from src.services import localizador_vin, cm_bajas_service
from src.ui.compartido.custom_table import VolvoTableWidget, PandasTableModel
from src.ui.administracion.contactos import AddContactoThread
from src.ui.administracion.contactos_agregar import ContactosAddDialog
from src.ui.comercial_agregar import _COMBO_CHEVRON_PATH, _QSS_CHECK_SERVICIO
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.ui.compartido.copiar import hacer_copiable, escribir_portapapeles
from src.ui.compartido.selector_fecha import SelectorFecha
from src.ui.ingresos.base import PantallaIngresosBase
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.transiciones import TransicionFundidoSubida, capturar
from src.ui.compartido.esqueleto_carga import animar_sobre_tabla
from src.ui.compartido.panel_ubicacion_vin import PanelUbicacionVin
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *

MENSAJE_ERROR_GUARDADO = "No se pudo actualizar el estado. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
SIN_PLAN = "SIN PLAN"


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
# Orden de las sub-pestañas: 0 Activaciones, 1 Sin Flota, 2 No entregados, 3 Bajas, 4 Contactos, 5 Conectados
_COLUMNAS_POR_TAB = {
    0: COLUMNAS_TABLA_ACTIVACIONES,
    1: COLUMNAS_TABLA_ACTIVACIONES,
    2: COLUMNAS_TABLA_ACTIVACIONES,
    3: COLUMNAS_TABLA_BAJAS,
    4: operaciones_services.COLUMNAS_CDB_SIN_CONTACTO,
    5: COLUMNAS_TABLA_ACTIVACIONES,
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
SUBTABS_CON_DATOS_FLOTA = (0, 1, 2, 5)

# Sub-pestaña "Activaciones": unidades Activando o Desconectadas que Operaciones debe gestionar.
IDX_ACTIVACIONES = 0

# Índice de la sub-pestaña "Sin Flota" -- único lugar donde Luis debe
# completar CDB/FLOTA VC antes de poder conectar una unidad (ver
# _on_marcar_conectado_clicked/_actualizar_campos_sin_flota_visibles).
IDX_SIN_FLOTA = 1

# Sub-pestaña "No entregados" (04-11-2026): unidades con ESTADO DE ACTIVACIÓN ACTUAL = No entregado.
# Antes estaban en Activaciones; se pasan desde ahí con el botón "No entregado".
IDX_NO_ENTREGADOS = 2

# Sub-pestaña "Bajas": unidades que Comercial dio de baja y Operaciones debe desconectar.
IDX_BAJAS = 3

# Sub-pestaña "Contactos" (05-10-2026): CDB sin contacto en contactos.xlsx,
# se agregan de a uno con el mismo formulario de Comercial/Clientes y Flotas.
IDX_CONTACTOS = 4

# Sub-pestaña "Datos de flota" (13-10-2026): contratos Vigentes y Conectados sin
# FLOTA VC; Operaciones la completa directo en la tabla.
IDX_DATOS_FLOTA = 5

# Las sub-pestañas se arman en vivo desde df_master (ver
# _refrescar_cola); sus reglas de filtro viven en operaciones_services.
SUBTABS = [
    ("Activaciones", "fa5s.file-alt"),
    ("Sin Flota", "fa5s.truck-loading"),
    ("No entregados", "fa5s.box-open"),
    ("Bajas", "fa5s.users"),
    ("Contactos", "fa5s.address-book"),
    ("Conectados", "fa5s.truck"),
]

_FILTROS_POR_TAB = {
    IDX_ACTIVACIONES: operaciones_services.filtrar_activaciones,
    IDX_SIN_FLOTA: operaciones_services.filtrar_sin_flota,
    IDX_NO_ENTREGADOS: operaciones_services.filtrar_no_entregados,
    IDX_BAJAS: operaciones_services.filtrar_bajas,
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
