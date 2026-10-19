import pandas as pd
import qtawesome as qta
import os
import re
import shutil
import time
from src.core.cdb_columnas import cdb_a_memoria, cdb_a_disco
from src.core.constants import INDUSTRIA_MAP
from datetime import datetime
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QPushButton, QMessageBox, QLineEdit, QComboBox, QMenu,
                             QListWidget, QListWidgetItem, QWidgetAction, QHeaderView, QTextEdit,
                             QApplication, QTabWidget, QTabBar,
                             QAbstractItemView, QProgressDialog, QScrollArea, QGridLayout,
                             QGraphicsDropShadowEffect, QCheckBox, QSpinBox)
from PyQt6.QtCore import (Qt, QSize, QThread, pyqtSignal, QTimer, QSettings, QUrl, QPoint, QStandardPaths,
                          QPropertyAnimation, QEasingCurve, QEvent, QRect)
from PyQt6.QtGui import QDesktopServices, QKeySequence, QFontMetrics, QFont, QColor

from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core import excel_writer_csv_backend
from src.core.perf_log import medir
from src.services import comercial_services
from src.services import cm_bajas_service
from src.services import mail_sync_service
from src.services import mail_service
from src.services import contactos_service
from src.services import justtime_service
from src.ui.mail_dialog import MailDialog
from src.ui.comercial_agregar import ComercialUnidadFormWidget
from src.ui.importar_powerbi import iniciar_importacion_power_bi
from src.ui.contactos_agregar import ContactosAddDialog
from src.ui.contactos import AddContactoThread
from src.ui.custom_table import (AppTableWidget, PandasTableModel, ExportExcelThread,
                                 _FONDO_CATALOGO, _TEXTO_CATALOGO)
from src.ui import comercial_estilo as estilo_com
from src.ui.transiciones import TransicionFundidoSubida
from src.ui.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.dialogo_accion import DialogoAccion
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *     
import config.settings
from config.settings import RM_REPORTE_PATH, REPORTE_NOTAS_VENTAS_URL
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.constants import (
    RM_CONTRATOS_COLUMN_ALIASES, RM_CONTRATOS_COLUMNAS_AUTORIZADAS,
    PRUEBAS_FM_COLUMNAS_LOCALES, COLUMNAS_TECNICAS_SYNC, RM_CONTRATOS_PAGO_CM_PATTERN,
    COL_ESTADO_COMERCIAL, ESTADO_COMERCIAL_CORRECCIONES_RM, ESTADO_ACTIVACION_CORRECCIONES_RM,
    VALOR_ESTADO_COMERCIAL_BAJA,
    VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA,
    COL_ETAPA_GESTION, VALOR_ESTADO_COMERCIAL_VENCIDO, COL_ID,
    ESTADOS_COMERCIAL_CORREGIBLES_A_VENCIDO, COL_TIPO_FACTURACION, COL_FORMA_CONTRATO,
    COL_ESTADO_ACTIVACION, ESTADO_CONECTADO, VALOR_TIPO_FACT_SIN_REGISTRO,
    VALOR_ESTADO_COMERCIAL_VIGENTE, VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE,
    COL_RAZON_SOCIAL, COL_CHASIS, DROPDOWN_OPTIONS_UNIDAD,
)

# =========================================================
# HILOS DE TRABAJO ASÍNCRONO
# =========================================================
class SaveExcelThread(QThread):
    finished_signal = pyqtSignal(bool)
    # LogApp.csv releido en este mismo hilo de fondo justo despues de un
    # guardado exitoso (ExcelWriter.update_cells ya le agrego las lineas
    # nuevas via _log_changes): permite que quien construyo el hilo propague
    # el resultado a DataManager.set_logs_df() en el hilo principal, sin que
    # Historial (historial.py y el historial por VIN de general.py) quede
    # desactualizado hasta presionar "Recargar" -- mismo patron que ya usa
    # RMReporteSyncWorker.success_signal / SyncRMReporteDialog.handle_success. No
    # se emite si el guardado fallo o si la relectura del CSV fallo.
    logs_actualizados_signal = pyqtSignal(object)

    def __init__(self, writer, changes, module_name="Sistema"):
        super().__init__()
        self.writer = writer
        self.changes = changes
        self.module_name = module_name

    def run(self):
        success = self.writer.update_cells(self.changes, module_name=self.module_name)
        if success:
            df_logs = self.writer.leer_logs_actual()
            if df_logs is not None:
                self.logs_actualizados_signal.emit(df_logs)
        self.finished_signal.emit(success)

class AddRowThread(QThread):
    finished_signal = pyqtSignal(bool, dict)
    
    def __init__(self, writer, new_data, module_name="Sistema"):
        super().__init__()
        self.writer = writer
        self.new_data = new_data
        self.module_name = module_name
        
    def run(self):
        success = self.writer.add_new_row(self.new_data, module_name=self.module_name)
        self.finished_signal.emit(success, self.new_data)

class EnviarPapeleraThread(QThread):
    """Envía a la papelera, por ID, una lista de (vin, id_contrato). Emite
    (todo_ok, [(vin, id)] de los que sí se eliminaron)."""
    finished_signal = pyqtSignal(bool, list)

    def __init__(self, writer, items, module_name="Sistema"):
        super().__init__()
        self.writer = writer
        self.items = items
        self.module_name = module_name

    def run(self):
        eliminados = []
        for vin, id_contrato in self.items:
            if id_contrato:
                ok = self.writer.delete_row(module_name=self.module_name, keys_dict={'ID': id_contrato})
            else:
                ok = self.writer.delete_row(vin, module_name=self.module_name)
            if not ok:
                break
            eliminados.append((vin, id_contrato))
        self.finished_signal.emit(len(eliminados) == len(self.items), eliminados)

class KeepOpenMenu(QMenu):
    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.pos())
        if action and action.isCheckable():
            action.trigger()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

# Columnas donde busca el texto libre (barra local de Vista Completa y barra
# global de MainWindow). Unica lista compartida por _ComercialModuleLegacy.
# filter_table() y ComercialModule._refresh_new_ui_data() para no duplicarla.
# RUT agregado 28-09-2026, a pedido explicito.
COLUMNAS_BUSQUEDA_COMERCIAL = ['VIN', 'CHASIS', 'FLOTA VC', 'FLOTA VC 2', 'CDB', 'CDB FLOTA', 'RAZÓN SOCIAL', 'RUT']
# N° Contrato (ID): solo calza por igualdad exacta, ver construir_mascara_busqueda
COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL = [COL_ID]

# Columnas donde busca el texto libre de la sub-pestaña "Revisión CM" (ver
# ComercialModule._construir_df_revision_cm). Distinta de
# COLUMNAS_BUSQUEDA_COMERCIAL porque esta bandeja no lee df_base (PruebasFM),
# sino CasosBajaCM.csv (cm_bajas_service), que trae su propio VIN/CHASIS.
COLUMNAS_BUSQUEDA_REVISION_CM = ['RAZÓN SOCIAL', 'CHASIS', 'VIN', 'N CONTRATO 3PC']

# Filtros integrados en el encabezado de Vista Completa (ver FilterHeaderView
# en custom_table.py): TODAS las columnas visibles de self.df_base son
# filtrables -- ver _refrescar_opciones_header_filter, que arma las opciones
# dinámicamente a partir de las columnas reales, sin listarlas a mano. Solo
# se excluyen columnas técnicas que nunca son visibles para el usuario.
HEADER_FILTER_COLUMNAS_EXCLUIDAS = {
    'N°',           # numeración de fila, recalculada en cada filter_table(): filtrar por ella no tendría sentido
    'PAGO CM_NUM',  # valor técnico detrás de la columna visible 'PAGO CM' (ver filter_table)
}
# Misma asimetría que ya existía en el filtro original: ESTADO COMERCIAL y
# ESTADO DE ACTIVACIÓN ACTUAL comparan en minúsculas; el resto de columnas
# (nuevas incluidas) usa comparación exacta (solo strip), como ya hacían
# EJECUTIVO/INDUSTRIA/PERIODO INTERNO.
HEADER_FILTER_CASE_INSENSITIVE = {'ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL'}
# PERIODO INTERNO ya ordenaba sus opciones en forma descendente (periodos más
# recientes primero); se preserva ese único caso especial de orden.
HEADER_FILTER_ORDEN_DESCENDENTE = {'PERIODO INTERNO'}

# Ancho por defecto (px) de columnas en las tablas de Comercial. RAZÓN SOCIAL
# recibe un ancho mayor para mostrar la razón social completa sin truncar;
# el resto conserva el ancho estándar que ya usaba Vista Completa. Solo fija
# el ancho INICIAL: el resize manual (modo Interactive de QHeaderView, el que
# ya traían estas tablas) sigue funcionando igual.
COMERCIAL_COL_WIDTH_DEFAULT = 140
COMERCIAL_COL_WIDTH_RAZON_SOCIAL = 300

# Ancho mínimo (px) que se le respeta a cualquier columna de new_ui_table al
# redistribuir anchos (ver ComercialModule._on_new_ui_header_resized): evita
# que una columna quede en 0px (invisible) cuando se comprime para hacerle
# espacio a otra que el usuario ensanchó a mano.
NEW_UI_COL_WIDTH_MINIMO = 60

# Columnas de texto largo: se muestran completas en varias líneas y la fila crece (AppTableWidget.set_columnas_ajuste_texto).
COMERCIAL_COLUMNAS_AJUSTE_TEXTO = ['RAZÓN SOCIAL', 'FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ACTIVACIÓN ACTUAL']

# Alto de fila de la bandeja de la Nueva interfaz (23-09-2026, a pedido
# explícito): con el alto estándar (38px, AppTableWidget._setup_style) una
# razón social larga se cortaba salvo que se ensanchara la columna a mano.
# En vez de eso, la fila se hace más alta y RAZÓN SOCIAL se muestra con
# ajuste de línea (ver _build_new_ui_bandeja) para verla completa sin tocar
# el ancho. Se aplica solo a new_ui_table (y su frozen_view, ver
# AppTableWidget._setup_frozen_view) -- no a AppTableWidget en general,
# que sigue en 38px para el resto de la app (Vista Completa incluida).
COMERCIAL_NEW_UI_ROW_HEIGHT = 44

# Estilo por defecto de los botones de "Acciones rápidas" (ver
# ComercialModule._build_new_ui_accion_button). Se extrae como constante
# porque "Agregar contacto" necesita poder volver a este estilo neutro
# cuando no hay exactamente un VIN seleccionado (ver
# _aplicar_estilo_agregar_contacto), sin repetir el mismo bloque de QSS
# en dos lugares.
ACCION_RAPIDA_BUTTON_STYLE_DEFAULT = f"""
    QPushButton {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; text-align: left; padding: 8px; }}
    QPushButton:hover {{ border: 1px solid {PRIMARY}; background-color: #F8FAFC; }}
    QPushButton:disabled {{ background-color: #F3F4F6; border: 1px solid #E5E7EB; }}
"""


def _aplicar_anchos_columnas_comercial(table, columnas, ancho_col_0=None, ancho_razon_social=None):
    """Punto único donde se fija el ancho inicial de columnas de una tabla de
    Comercial, por nombre de columna. Usado tanto por
    _ComercialModuleLegacy.filter_table() (Vista Completa) como por
    ComercialModule._refresh_new_ui_data() (bandeja de la Nueva interfaz),
    para no duplicar esta configuración en dos lugares.

    - `ancho_col_0`: si se indica, fuerza ese ancho para la columna 0 sin
      importar su nombre (usado por Vista Completa para 'N°').
    - `ancho_razon_social`: si se indica, RAZÓN SOCIAL recibe ese ancho en vez
      del estándar. Se deja explícito (no siempre COMERCIAL_COL_WIDTH_RAZON_SOCIAL)
      porque "Gestionar CM" no forma parte de las vistas donde se pidió
      ensanchar RAZÓN SOCIAL."""
    for i, nombre_col in enumerate(columnas):
        if i == 0 and ancho_col_0 is not None:
            table.setColumnWidth(i, ancho_col_0)
            continue
        if nombre_col == 'RAZÓN SOCIAL' and ancho_razon_social is not None:
            table.setColumnWidth(i, ancho_razon_social)
        else:
            table.setColumnWidth(i, COMERCIAL_COL_WIDTH_DEFAULT)


# Padding (px) sumado al ancho de texto medido con QFontMetrics, para que la
# columna no quede pegada al borde del contenido/encabezado. Solo se usa como
# respaldo para columnas sin entrada en NEW_UI_SUBTAB_COLUMN_WIDTHS.
_NEW_UI_COL_WIDTH_PADDING = 28
# CHASIS siempre son 7 dígitos (ver _aplicar_anchos_columnas_new_ui): ancho
# de referencia para medir el contenido, no el encabezado (mismo respaldo).
_NEW_UI_CHASIS_MUESTRA = "0000000"

# Anchos calibrados a mano por el usuario (30-09-2026, herramienta de
# calibración hecha a medida) contra la tabla real medida en su equipo
# (1147px de panel, escala de interfaz "Pequeño"). Reemplazan la heurística
# anterior (QFontMetrics + reparto automático del sobrante hacia RAZÓN
# SOCIAL), que dejaba nombres largos partidos en 2 líneas en "Gestionar
# Bajas" y demasiado espacio vacío en la última columna. Clave = índice de
# NEW_UI_SUBTAB_COLUMNS; la última columna de cada sub-pestaña NO figura acá
# a propósito -- se sigue estirando sola vía setStretchLastSection (ver
# _build_new_ui_bandeja). Una columna sin entrada cae al cálculo por
# contenido de _aplicar_anchos_columnas_new_ui.
NEW_UI_SUBTAB_COLUMN_WIDTHS = {
    2: {'RAZÓN SOCIAL': 380, 'CHASIS': 85, 'FORMA DE CONTRATO': 129},
    0: {'RAZÓN SOCIAL': 286, 'CHASIS': 90, 'FORMA DE CONTRATO': 130, 'TÉRMINO CONTRATO': 105, 'ESTADO COMERCIAL': 140},
    1: {'RAZÓN SOCIAL': 383, 'CHASIS': 90, 'ESTADO DE ACTIVACIÓN ACTUAL': 170},
    3: {'RAZÓN SOCIAL': 243, 'CHASIS': 90, 'FECHA TERMINO CM': 140, 'ESTADO DEL CM': 120, 'PAGO CM': 110},
}


def _aplicar_anchos_columnas_new_ui(table, columnas, anchos_fijos=None):
    """Ancho inicial de columnas exclusivo de new_ui_table (las 6
    sub-pestañas de la Nueva interfaz de Comercial), separado de
    _aplicar_anchos_columnas_comercial (28-09-2026, a pedido explícito) para
    no afectar Vista Completa, que sigue usando anchos fijos.

    `anchos_fijos` (dict nombre_columna -> px) son los valores calibrados a
    mano (ver NEW_UI_SUBTAB_COLUMN_WIDTHS) que llaman los call sites de
    _refresh_new_ui_data. Cualquier columna sin entrada ahí (la última
    siempre, más "Avisos"/columnas nuevas sin calibrar) cae al cálculo por
    contenido de su propio texto de encabezado (QFontMetrics), salvo CHASIS,
    que se ajusta a su contenido (siempre 7 dígitos) en vez de al encabezado.

    Envuelta con el mismo flag que usa ComercialModule._on_new_ui_header_resized
    (30-09-2026) para que ese redistribuidor de anchos -- pensado solo para el
    resize manual del usuario -- no se dispare mientras se fijan estos anchos
    iniciales."""
    anchos_fijos = anchos_fijos or {}
    table._ajustando_anchos_new_ui = True
    try:
        fm_header = QFontMetrics(table.horizontalHeader().font())
        fm_celda = QFontMetrics(table.font())
        for i, nombre_col in enumerate(columnas):
            if nombre_col in anchos_fijos:
                table.setColumnWidth(i, anchos_fijos[nombre_col])
            elif nombre_col == 'CHASIS':
                ancho = max(fm_celda.horizontalAdvance(_NEW_UI_CHASIS_MUESTRA),
                            fm_header.horizontalAdvance(nombre_col))
                table.setColumnWidth(i, ancho + _NEW_UI_COL_WIDTH_PADDING)
            else:
                table.setColumnWidth(i, fm_header.horizontalAdvance(nombre_col) + _NEW_UI_COL_WIDTH_PADDING)
    finally:
        table._ajustando_anchos_new_ui = False


def _formatear_pago_cm_para_mostrar(valor):
    """Formatea un valor crudo de PAGO CM (tal como viene de CasosBajaCM.csv,
    ej. '15000') al mismo formato monetario ($XX.XXX) que ya usa Vista
    Completa/contratos.py, reutilizando comercial_services.parsear_pago_cm en
    vez de duplicar la fórmula. Solo para mostrar en pantalla: no modifica
    CasosBajaCM.csv ni el valor que usa la lógica de Confirmar Baja."""
    resultado, dato = comercial_services.parsear_pago_cm(valor)
    return dato["formato"] if resultado == "valido" else str(valor)


def _valor_esta_vacio(v):
    """True si v debe tratarse como vacío (NaN, None, '', o texto tipo 'nan'/'NaT').
    0 y cualquier valor con contenido real no se consideran vacíos."""
    if pd.isna(v):
        return True
    if isinstance(v, str) and v.strip().upper() in ('', 'NAN', 'NONE', 'NAT', '<NA>'):
        return True
    return False

def _normalizar_vacios_a_guion(df, columnas_excluir=None):
    """Reemplaza toda celda vacía del DataFrame por '-' antes de escribir a Excel.

    columnas_excluir: columnas que deben quedar tal cual (vacío = vacío/pendiente,
    no se fuerza a '-'). Usada por 'DURACIÓN (MESES)': un vacío ahí significa que
    la contraparte comercial todavía no gestionó el dato, y no debe interpretarse como mensual
    (ver calcular_termino en DataFrameFormatter, que solo trata '-' como mensual)."""
    df = df.copy()
    columnas_excluir = set(columnas_excluir or [])
    for col in df.columns:
        if col in columnas_excluir:
            continue
        df[col] = df[col].map(lambda v: "-" if _valor_esta_vacio(v) else v)
    return df

def _normalizar_id_contrato(valor):
    """ID del RM como texto entero ('115'), sin '.0' ni espacios; vacío si no hay."""
    if _valor_esta_vacio(valor):
        return ""
    texto = str(valor).strip()
    return texto[:-2] if texto.endswith('.0') else texto


class RMReporteSyncWorker(QThread):
    """SOLO MODO DESARROLLADOR: esta sincronización (RM_CONTRATOS -> PruebasFM) se usa
    únicamente durante el desarrollo y las pruebas. En producción la opción
    desaparece de la app y el usuario no podrá utilizarla."""
    log_signal = pyqtSignal(str)
    success_signal = pyqtSignal(str, object, object)  # (mensaje, df_final, df_logs_actualizado o None)
    error_signal = pyqtSignal(str)

    def run(self):
        try:
            if not os.path.exists(RM_REPORTE_PATH): raise Exception(f"No se encontró el archivo de la contraparte comercial en:\n{RM_REPORTE_PATH}")
            if not os.path.exists(config.settings.EXCEL_PATH): raise Exception("No se encontró el archivo RM_CONTRATOS.csv.")

            temp_dir = os.path.join(os.getcwd(), 'data', 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            temp_reporte_path = os.path.join(temp_dir, 'temp_rm_reporte.xlsx')
            
            self.log_signal.emit("[SISTEMA] Creando copia temporal de lectura para evitar colapsos de red...")
            try: shutil.copy2(RM_REPORTE_PATH, temp_reporte_path)
            except Exception as e: raise Exception(f"No se pudo copiar el RM de la contraparte comercial. Asegúrate de que ella no lo esté guardando en este momento.\n{e}")

            self.log_signal.emit(f"[LECTURA] Extrayendo datos maestros desde copia temporal RM_CONTRATOS...")
            df_reporte = pd.read_excel(temp_reporte_path, sheet_name='BBDD')
            
            self.log_signal.emit(f"[LECTURA] Leyendo base local RM_CONTRATOS...")
            # Fase 2 (migracion PruebasFM.xlsx -> .csv, 23-09-2026): esta
            # lectura (para el merge/preservar columnas locales) tambien
            # depende del formato de EXCEL_PATH, igual que la escritura
            # final de mas abajo -- sin esto, la sincronizacion fallaria de
            # entrada contra un RM_CONTRATOS.csv, antes de llegar siquiera a
            # escribir nada.
            if config.settings.EXCEL_PATH.lower().endswith('.csv'):
                df_pruebas = cdb_a_memoria(pd.read_csv(config.settings.EXCEL_PATH, dtype=str, keep_default_na=False))
            else:
                df_pruebas = pd.read_excel(config.settings.EXCEL_PATH, sheet_name='BBDD (2)')

            df_reporte['VIN_CLEAN'] = df_reporte['VIN'].astype(str).str.replace(r'\s+', '', regex=True).str.upper()
            df_pruebas['VIN_CLEAN'] = df_pruebas['VIN'].astype(str).str.replace(r'\s+', '', regex=True).str.upper()

            self.log_signal.emit("[CRUCE] Aplicando reglas de renombrado y limpieza...")
            renames = dict(RM_CONTRATOS_COLUMN_ALIASES)
            for col in df_reporte.columns:
                if RM_CONTRATOS_PAGO_CM_PATTERN.match(str(col).strip()): renames[col] = 'PAGO CM'
            df_reporte.rename(columns=renames, inplace=True)
            
            if 'INDUSTRIA' in df_reporte.columns:
                self.log_signal.emit("[LIMPIEZA] Estandarizando idioma y nombres de Industrias...")
                def limpiar_industria(val):
                    val_str = str(val).strip().upper()
                    if val_str in ['NAN', 'NONE', '<NA>', '', '-', '0', '0.0']: return "NO DEFINIDA"
                    if val_str in INDUSTRIA_MAP: return INDUSTRIA_MAP[val_str]
                    return val_str
                df_reporte['INDUSTRIA'] = df_reporte['INDUSTRIA'].apply(limpiar_industria)

            if COL_ESTADO_COMERCIAL in df_reporte.columns:
                self.log_signal.emit("[LIMPIEZA] Corrigiendo errores de digitación en Estado Comercial...")
                def corregir_estado_comercial(val):
                    val_str = str(val).strip().upper()
                    return ESTADO_COMERCIAL_CORRECCIONES_RM.get(val_str, val)
                df_reporte[COL_ESTADO_COMERCIAL] = df_reporte[COL_ESTADO_COMERCIAL].apply(corregir_estado_comercial)

            if COL_ESTADO_ACTIVACION in df_reporte.columns:
                antes = df_reporte[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
                n_unificados = int(antes.isin(ESTADO_ACTIVACION_CORRECCIONES_RM).sum())
                if n_unificados:
                    self.log_signal.emit(f"[LIMPIEZA] {n_unificados} unidad(es) 'No entregado' pasan a 'Sin flota'...")
                    df_reporte[COL_ESTADO_ACTIVACION] = [ESTADO_ACTIVACION_CORRECCIONES_RM.get(v, o)
                                                      for v, o in zip(antes, df_reporte[COL_ESTADO_ACTIVACION])]

            for col_cdb in ('CDB FLOTA', 'CDB'):
                if col_cdb in df_reporte.columns:
                    df_reporte[col_cdb] = (df_reporte[col_cdb].fillna('').astype(str).str.strip()
                                        .str.replace(r'^(\d+)\.0$', r'\1', regex=True)
                                        .replace({'nan': '', 'NaN': '', '<NA>': '', 'None': ''}))

            self.log_signal.emit("[LIMPIEZA] Verificando y auto-completando números de CHASIS...")
            if 'CHASIS' not in df_reporte.columns: df_reporte['CHASIS'] = ""
            df_reporte['CHASIS'] = df_reporte['VIN_CLEAN'].apply(lambda x: x[-7:] if isinstance(x, str) and len(x) >= 7 else x)

            if 'DURACIÓN (MESES)' in df_reporte.columns:
                def safe_duracion_sync(val):
                    if pd.isna(val) or str(val).strip() in ['', 'nan', 'NaN', '<NA>', 'None']: return ""
                    val_str = str(val).strip().upper()
                    if val_str in ['-', 'MENSUAL']: return val_str
                    try:
                        num = float(val)
                        # Regla confirmada con la contraparte comercial: duracion >= 100 se normaliza a '-'
                        # (calcular_termino en DataFrameFormatter la traduce luego a MENSUAL).
                        if num >= 100: return "-"
                        return str(int(round(num)))
                    except (ValueError, TypeError): return val_str
                df_reporte['DURACIÓN (MESES)'] = df_reporte['DURACIÓN (MESES)'].apply(safe_duracion_sync)

            self.log_signal.emit("[SEGURIDAD] Filtrando columnas del RM a las autorizadas por el sistema...")
            cols_reporte_autorizadas = [c for c in RM_CONTRATOS_COLUMNAS_AUTORIZADAS if c in df_reporte.columns]
            df_reporte = df_reporte[cols_reporte_autorizadas + ['VIN_CLEAN']]

            cols_to_preserve = [c for c in PRUEBAS_FM_COLUMNAS_LOCALES if c in df_pruebas.columns]

            self.log_signal.emit("[LIMPIEZA] Purgando filas clonadas o duplicadas en memoria...")
            if COL_ID in df_reporte.columns:
                df_reporte[COL_ID] = df_reporte[COL_ID].map(_normalizar_id_contrato)
                df_reporte = df_reporte.sort_values(by=COL_ID, key=lambda s: s.eq(''), kind='stable')
            df_reporte = df_reporte.drop_duplicates(subset=['VIN_CLEAN'], keep='first')
            df_locales = df_pruebas.drop_duplicates(subset=['VIN_CLEAN'], keep='last')[['VIN_CLEAN'] + cols_to_preserve].copy()

            self.log_signal.emit("[CRUCE] Fusionando bases de datos (1 a 1 perfecto)...")
            df_final = pd.merge(df_reporte, df_locales, on='VIN_CLEAN', how='left')

            # Lista explícita y cerrada: RM autorizado + locales autorizadas. No depende
            # de list(df_pruebas.columns), asi que una columna no autorizada del RM no
            # entra aunque coincida de nombre con algo que ya existiera en PruebasFM.
            columnas_finales = [c for c in (RM_CONTRATOS_COLUMNAS_AUTORIZADAS + PRUEBAS_FM_COLUMNAS_LOCALES)
                                 if c not in COLUMNAS_TECNICAS_SYNC]

            # --- AUTO-HEALING: una columna autorizada entra aunque PruebasFM no la tuviera aún ---
            for col in columnas_finales:
                if col not in df_final.columns:
                    df_final[col] = ""
                    self.log_signal.emit(f"[AUTO-HEAL] Agregando columna autorizada faltante: {col}")

            df_final = df_final[columnas_finales]

            # Nuevo (23-09-2026, a pedido explícito): unifica automáticamente
            # los clientes con el mismo RUT+CDB pero Razón Social distinta
            # (típico error de tipeo al cargar, ver GeneralModule ->
            # pestaña Duplicados) en cada sincronización con RM_CONTRATOS. Se
            # aplica ANTES de armar df_new_cmp (más abajo) para que el
            # renombrado quede registrado como un cambio más en LogApp.csv
            # por el mismo mecanismo de diff/auditoría que ya usa esta
            # sincronización -- no se duplica ese logging aquí.
            df_final, _mapa_razon_social_unificada = comercial_services.unificar_razon_social_duplicada(df_final)
            if _mapa_razon_social_unificada:
                self.log_signal.emit(
                    f"[UNIFICACIÓN] {len(_mapa_razon_social_unificada)} Razón(es) Social(es) duplicada(s) "
                    f"unificada(s) por RUT+CDB (se conservó la de más unidades)."
                )

            # Estados de JustTime al catálogo (30-09-2026, a pedido explícito);
            # antes de la auditoría para que cada corrección quede en LogApp
            df_final, n_justtime_limpios = justtime_service.normalizar_columna_justtime(df_final)
            if n_justtime_limpios:
                self.log_signal.emit(f"[LIMPIEZA] {n_justtime_limpios} estado(s) de JustTime llevados al catálogo.")

            writer = ExcelWriter()
            writer._crear_backup(config.settings.EXCEL_PATH)
            if not writer.last_backup_ok:
                self.error_signal.emit("No se pudo crear la copia de seguridad de RM_CONTRATOS.csv antes de sincronizar. La operación fue cancelada y no se realizó ningún cambio.")
                return

            # La sincronización ya no escribe en LogApp.csv (historial de cambios);
            # la comparación solo sirve para el resumen y la papelera.
            self.log_signal.emit("[AUDITORÍA] Comparando cambios...")
            
            df_old = df_pruebas.drop_duplicates('VIN_CLEAN').set_index('VIN_CLEAN')
            df_new_cmp = df_final.copy()
            df_new_cmp['VIN_CLEAN'] = df_new_cmp['VIN'].astype(str).str.replace(r'\s+', '', regex=True).str.upper()
            df_new_cmp = df_new_cmp.drop_duplicates('VIN_CLEAN').set_index('VIN_CLEAN')
            
            vins_old = set(df_old.index)
            vins_new = set(df_new_cmp.index)
            
            agregados = vins_new - vins_old
                
            eliminados = vins_old - vins_new
            headers_local = list(df_pruebas.columns)
            if 'VIN_CLEAN' in headers_local: headers_local.remove('VIN_CLEAN')
            if eliminados:
                filas_eliminadas = df_old.loc[sorted(eliminados), headers_local].values.tolist()
                writer._log_deleted_lote(headers_local, filas_eliminadas, module_name="Sincronización Nube")
                
            comunes = vins_new.intersection(vins_old)
            cols_to_check = [c for c in columnas_finales if c in df_old.columns]
            
            def clean_val(v):
                if pd.isna(v) or str(v).strip() in ['nan', 'None', '']: return ""
                if isinstance(v, (pd.Timestamp, datetime)): return str(v).split()[0] 
                try: return str(round(float(v), 4))
                except (ValueError, TypeError): return str(v).strip()
            
            cambios_celdas = 0
            for vin in comunes:
                for col in cols_to_check:
                    old_str = clean_val(df_old.at[vin, col])
                    new_str = clean_val(df_new_cmp.at[vin, col])
                    if old_str != new_str:
                        cambios_celdas += 1

            df_logs_actualizado = None

            self.log_signal.emit("[LIMPIEZA] Convirtiendo celdas vacías a '-'...")
            # 'DURACIÓN (MESES)' vacía queda excluida: significa que la contraparte comercial aún no
            # gestionó ese dato (pendiente), no un contrato mensual. Solo '-' explícito
            # (o 'MENSUAL', normalizado luego en DataFrameFormatter.clean) representa mensual.
            df_final = _normalizar_vacios_a_guion(df_final, columnas_excluir=['DURACIÓN (MESES)', COL_ID])

            # El RM trae "No encontrado" o "0" en los CDB cuando no halló el código: no es un CDB.
            for col_cdb in ('CDB', 'CDB FLOTA'):
                if col_cdb in df_final.columns:
                    df_final[col_cdb] = df_final[col_cdb].map(
                        lambda v: '-' if re.fullmatch(r'0+(\.0+)?|NO ENCONTRADO', str(v).strip().upper()) else v)

            # Normalización determinística de TIPO DE FACTURACION (24-09-2026,
            # a pedido explícito): solo completa el caso sin ambigüedad (FORMA
            # DE CONTRATO con una única opción válida en la matriz), nunca toca
            # un valor real ya asignado. Va DESPUÉS de _normalizar_vacios_a_guion
            # de arriba a propósito: ahí "sin asignar" ya es siempre '' o '-',
            # nunca NaN, así que la función reutiliza esa normalización en vez
            # de reimplementarla. Se guarda en RM_CONTRATOS.csv (a diferencia de la
            # detección informativa de más abajo, que no escribe nada) porque
            # es la única corrección de este tipo que no depende de una
            # decisión de negocio pendiente en RM_CONTRATOS.xlsx.
            n_sin_asignar_antes_normalizar = comercial_services.contar_forma_contrato_sin_tipo_facturacion_asignado(df_final)
            df_final = comercial_services.normalizar_tipo_facturacion_por_forma_contrato(df_final)

            # ETAPA GESTIÓN (25-09-2026, corrección de bug real de datos):
            # esta columna salió de RM_CONTRATOS_COLUMNAS_AUTORIZADAS y pasó a
            # PRUEBAS_FM_COLUMNAS_LOCALES (constants.py) -- ya no se trae el
            # valor crudo desde RM_CONTRATOS.xlsx (que en los datos reales traía
            # basura: el número de CHASIS pegado por error, y miles de filas
            # con el valor legado 'CLIENTE'). Se recalcula aquí, ANTES de
            # escribir a disco (a diferencia de DataFrameFormatter.clean()
            # más abajo, que solo prepara la copia en RAM) para que el
            # archivo persistido en PruebasFM ya quede con el valor correcto
            # de la matriz de negocio, no con el que sea que haya traído el
            # merge. Reutiliza la misma función que ya usa clean() y
            # comercial_services.detectar_contradicciones_etapa_gestion, sin
            # reimplementar la regla.
            self.log_signal.emit("[LIMPIEZA] Recalculando ETAPA GESTIÓN con la matriz de negocio (se ignora el valor crudo de RM_CONTRATOS)...")
            if COL_ETAPA_GESTION in df_final.columns:
                df_final[COL_ETAPA_GESTION] = DataFrameFormatter.calcular_etapa_gestion_df(df_final)

            self.log_signal.emit("[ESCRITURA] Inyectando datos actualizados a RM_CONTRATOS.csv...")

            # Fase 2 (migracion PruebasFM.xlsx -> .csv, 23-09-2026): unico
            # cambio de esta fase en RMReporteSyncWorker -- el merge, limpieza,
            # renombrados, calculo de diffs y logging de arriba no se tocan.
            # CSV no tiene concepto de hoja, asi que el reemplazo total del
            # dataset usa el mismo patron atomico (temporal -> fsync ->
            # copy2) ya validado en excel_writer_csv_backend, sin
            # reimplementarlo aqui.
            # Se marca como guardado propio (igual que ExcelWriter) para que el
            # watchdog no lo tome como un cambio externo y dispare snapshot +
            # recarga completa justo después de sincronizar.
            dm_guardado = DataManager()
            dm_guardado.is_app_saving = True
            dm_guardado.save_timestamp = time.time()
            try:
                if config.settings.EXCEL_PATH.lower().endswith('.csv'):
                    temp_pruebas = os.path.join(temp_dir, 'temp_pruebas_sync.csv')
                    try:
                        excel_writer_csv_backend._escribir_csv_atomico(cdb_a_disco(df_final), config.settings.EXCEL_PATH, temp_pruebas)
                    except PermissionError:
                        raise Exception("¡El archivo RM_CONTRATOS.csv está abierto! Ciérralo para poder guardar.")
                    except Exception as e:
                        raise Exception(f"Error escribiendo el CSV: {e}")
                else:
                    temp_pruebas = os.path.join(temp_dir, 'temp_pruebas_sync.xlsx')
                    shutil.copy2(config.settings.EXCEL_PATH, temp_pruebas)

                    try:
                        with pd.ExcelWriter(temp_pruebas, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer_pd:
                            df_final.to_excel(writer_pd, sheet_name='BBDD (2)', index=False)

                        shutil.copy2(temp_pruebas, config.settings.EXCEL_PATH)
                    except PermissionError:
                        raise Exception("¡El archivo RM_CONTRATOS.xlsx está abierto! Ciérralo en Excel para poder guardar.")
                    except Exception as e:
                        raise Exception(f"Error escribiendo el Excel: {e}")
            finally:
                dm_guardado.save_timestamp = time.time()
                dm_guardado.is_app_saving = False

            try: 
                os.remove(temp_reporte_path)
                os.remove(temp_pruebas)
            except: pass

            mensaje_final = (
                f"¡Sincronización exitosa y Auditada!\n\n"
                f"Total procesados: {len(df_final)}\n"
                f"Nuevos agregados: {len(agregados)}\n"
                f"Eliminados enviados a papelera: {len(eliminados)}\n"
                f"Celdas actualizadas: {cambios_celdas}"
            )
            if not writer.last_backup_ok:
                mensaje_final += "\n\n⚠️ Aviso: no se pudo crear la copia de seguridad previa a esta sincronización. Revisa 'Estado del Sistema' en Configuración."

            # B-7 (auditoria de rendimiento, 18-09-2026): DataFrameFormatter.clean()
            # se ejecuta AQUI, en el QThread, en vez de en handle_success() (Main
            # Thread) como antes -- medido en ~8-11s sobre ~12.000 filas, bloqueaba
            # la UI completa. El Excel ya se escribio arriba con df_final SIN clean()
            # (igual que antes: el archivo en disco no cambia), clean() solo prepara
            # la version que queda en RAM (dm.df_master), que es exactamente lo mismo
            # que hacia handle_success() antes de este cambio -- no es codigo nuevo,
            # solo se traslado de hilo. clean() es pandas/logging puro (sin Qt), asi
            # que corre igual de bien aqui; si lanza ValueError (columnas faltantes),
            # ahora queda atrapado por el except de mas abajo como cualquier otro
            # error de esta sincronizacion, en vez de escapar sin control desde un
            # slot de Main Thread.
            self.log_signal.emit("[LIMPIEZA] Normalizando datos para la vista en memoria (ETAPA GESTIÓN, fechas, catálogos)...")
            with medir(f"B-7 RMReporteSyncWorker.run > DataFrameFormatter.clean ({len(df_final)} filas)", hilo="WORKER"):
                df_final = DataFrameFormatter.clean(df_final)

            # Resumen informativo (24-09-2026, a pedido explícito). Reutiliza
            # tal cual las mismas funciones/matriz que ya usa el botón
            # "Revisar inconsistencias" -- no se duplica la lógica de
            # negocio. Tres categorías, sin mezclarlas:
            # - normalizados automáticamente: ya se escribieron arriba (único
            #   caso sin ambigüedad -- ver normalizar_tipo_facturacion_por_forma_contrato).
            # - aún sin asignar: la matriz permite más de una opción (ej.
            #   CONVERSION/VENTA) o FORMA DE CONTRATO no está en la matriz;
            #   nadie puede decidir esto por la contraparte comercial, no se toca.
            # - inconsistentes reales: ya tienen un valor, pero no calza con
            #   la matriz para su FORMA DE CONTRATO. Nunca se corrigen solos
            #   (TIPO DE FACTURACION es un campo gobernado por RM_CONTRATOS.xlsx,
            #   ver RM_CONTRATOS_COLUMNAS_AUTORIZADAS/PRUEBAS_FM_COLUMNAS_LOCALES
            #   vacía) -- quedan para revisión manual.
            n_sin_asignar = comercial_services.contar_forma_contrato_sin_tipo_facturacion_asignado(df_final)
            n_normalizados = n_sin_asignar_antes_normalizar - n_sin_asignar
            n_inconsistentes = len(comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion(df_final))
            if n_normalizados:
                self.log_signal.emit(
                    f"[NORMALIZACIÓN] {n_normalizados} unidad(es) con TIPO DE FACTURACION "
                    f"completado automáticamente según la matriz de negocio (única opción posible)."
                )
                mensaje_final += f"\n\n{n_normalizados} unidad(es) con TIPO DE FACTURACION normalizado automáticamente según la matriz."
            if n_inconsistentes:
                self.log_signal.emit(
                    f"[VALIDACIÓN] {n_inconsistentes} combinación(es) FORMA DE CONTRATO / TIPO DE FACTURACION "
                    f"no cumplen la matriz de negocio -- revisar con 'Revisar inconsistencias'."
                )
                mensaje_final += (
                    f"\n{n_inconsistentes} combinación(es) FORMA DE CONTRATO / TIPO DE FACTURACION "
                    f"requieren revisión (botón \"Revisar inconsistencias\" en Vista Completa)."
                )
            if n_sin_asignar:
                mensaje_final += f"\n{n_sin_asignar} unidad(es) con TIPO DE FACTURACION aún sin asignar porque la matriz permite múltiples opciones."

            self.success_signal.emit(mensaje_final, df_final, df_logs_actualizado)

        except Exception as e:
            try: os.remove(temp_reporte_path)
            except: pass
            self.error_signal.emit(str(e))

class SyncRMReporteDialog(QDialog):
    """SOLO MODO DESARROLLADOR: esta sincronización (RM_CONTRATOS -> PruebasFM) se usa
    únicamente durante el desarrollo y las pruebas. En producción la opción
    desaparece de la app y el usuario no podrá utilizarla."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sincronización Maestra (RM_CONTRATOS de la contraparte comercial -> RM_CONTRATOS.csv)")
        self.resize(700, 400)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")
        self.worker = None
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        lbl_term = QLabel("Consola de Sincronización Unidireccional:")
        ThemeManager.style_subtitle(lbl_term)
        main_layout.addWidget(lbl_term)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setStyleSheet(f"background-color: {TEXT_PRIMARY}; color: {SUCCESS}; font-family: Consolas; font-size: 11px; padding: 10px; border-radius: 6px;")
        main_layout.addWidget(self.terminal, stretch=1)

        btn_layout = QHBoxLayout()
        self.btn_cancel = QPushButton(" Cancelar / Cerrar")
        ThemeManager.apply_danger_button(self.btn_cancel)
        self.btn_cancel.clicked.connect(self.close)

        self.btn_start = QPushButton(" Iniciar Sincronización")
        self.btn_start.setIcon(ThemeManager.icon('fa5s.sync', color='white'))
        ThemeManager.apply_primary_button(self.btn_start)
        self.btn_start.clicked.connect(self.start_sync)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_start)
        main_layout.addLayout(btn_layout)

    def write_log(self, text):
        self.terminal.append(f"> {text}")
        scrollbar = self.terminal.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_sync(self):
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(False) 
        self.terminal.clear()
        
        self.worker = RMReporteSyncWorker()
        self.worker.log_signal.connect(self.write_log)
        self.worker.success_signal.connect(self.handle_success)
        self.worker.error_signal.connect(self.handle_error)
        self.worker.start()

    def handle_success(self, msg, df_final, df_logs_actualizado):
        self.btn_cancel.setEnabled(True)

        dm = DataManager()
        # B-7 (auditoria de rendimiento, 18-09-2026): DataFrameFormatter.clean()
        # ya se ejecuto DENTRO de RMReporteSyncWorker.run() (ver mas arriba, antes
        # del success_signal.emit), no aqui -- df_final llega ya limpio. Antes
        # este with medir() media ~8-11s en Main Thread; se deja para poder
        # comprobar en consola que el costo de este callback bajo.
        with medir(f"B-7 handle_success ({len(df_final)} filas, clean() ya hecho en Worker)"):
            dm.df_master = df_final
        if df_logs_actualizado is not None:
            # set_logs_df solo asigna en RAM y emite logs_updated; no vuelve
            # a leer el CSV (ya se leyo en el worker, fuera del hilo principal).
            dm.set_logs_df(df_logs_actualizado)

        QMessageBox.information(self, "Proceso Completado", msg)
        self.accept()

    def handle_error(self, error_msg):
        self.btn_cancel.setEnabled(True)
        QMessageBox.critical(self, "Error Fatal", error_msg)
        self.btn_start.setEnabled(True)
        
    def reject(self):
        # Esc cierra el diálogo sin pasar por closeEvent
        if self.worker and self.worker.isRunning():
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Operación Crítica", "La base de datos se está modificando.\nNo puedes cerrar la ventana hasta que el proceso termine, de lo contrario dañarás el archivo de PruebasFM.")
            event.ignore()
        else:
            event.accept()

# =========================================================
# MÓDULO COMERCIAL PRINCIPAL (implementación actual, preservada intacta)
# =========================================================
class _ComercialModuleLegacy(QWidget):
    def __init__(self, tabla_diferida=False):
        super().__init__()
        self.settings = QSettings("GestorApp", "ComercialSettings")
        # Embebido y oculto en ComercialModule: la tabla propia solo se llena
        # cuando se necesita (exportar a Excel o mostrarla), ver _asegurar_tabla
        self._tabla_diferida = tabla_diferida
        self._tabla_pendiente = False

        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        
        self.pending_changes = {}
        self._skip_self_triggered_reload = False
        # Actualizacion diferida por visibilidad (ver general.py para el
        # detalle del mecanismo): data_ready mientras este modulo esta oculto
        # solo marca dirty, no reprocesa. _skip_self_triggered_reload se sigue
        # evaluando primero, sin cambios.
        self._data_dirty = False

        self._column_items = []
        # Filtros integrados en el encabezado de la tabla (ver
        # FilterHeaderView): valores disponibles y seleccionados por columna.
        # "Sin filtro" == seleccionados cubre todos los valores disponibles.
        self._header_filter_options = {}
        self._header_filter_selected = {}
        
        self.search_input = QLineEdit()
        self.search_input.hide()
        
        self.current_kpi_filter = "total" 
        
        self.data_manager.data_ready.connect(self._on_global_data_ready)
        self.data_manager.load_error.connect(self._on_load_error)
        
        # Catálogo compartido con las demás pantallas que abren el formulario de unidad
        self.dropdown_options = {k: list(v) for k, v in DROPDOWN_OPTIONS_UNIDAD.items()}
        
        self._setup_ui()
        self.load_data()

    def _create_filter_menu(self, btn, list_widget, items_list, check_all_func, uncheck_all_func):
        menu = QMenu(self)
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        action_layout = QHBoxLayout()
        btn_check = QPushButton("Marcar Todos")
        ThemeManager.apply_success_button(btn_check)
        btn_check.clicked.connect(check_all_func)
        
        btn_uncheck = QPushButton("Desmarcar Todos")
        ThemeManager.apply_danger_button(btn_uncheck)
        btn_uncheck.clicked.connect(uncheck_all_func)
        
        action_layout.addWidget(btn_check)
        action_layout.addWidget(btn_uncheck)
        
        list_widget.setFixedSize(260, 300) 
        
        layout.addLayout(action_layout)
        layout.addWidget(list_widget)
        
        action_widget = QWidgetAction(menu)
        action_widget.setDefaultWidget(widget)
        menu.addAction(action_widget)
        btn.setMenu(menu)
        return menu

    def _create_compact_filter_block(self, layout, title, widget):
        vbox = QVBoxLayout()
        vbox.setSpacing(2) 
        
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 10px; color: #64748B; font-weight: bold;")
        
        vbox.addWidget(lbl)
        vbox.addWidget(widget)
        layout.addLayout(vbox)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12) 

        header_layout = QHBoxLayout()

        self.btn_toggle_kpi = QPushButton(" Ocultar KPIs")
        self.btn_toggle_kpi.setIcon(ThemeManager.icon('fa5s.eye-slash', color=TEXT_SECONDARY))
        self.btn_toggle_kpi.setCursor(Qt.CursorShape.PointingHandCursor)
        ThemeManager.apply_secondary_button(self.btn_toggle_kpi)
        self.btn_toggle_kpi.clicked.connect(self._toggle_kpis)

        header_layout.addStretch()
        header_layout.addWidget(self.btn_toggle_kpi)
        main_layout.addLayout(header_layout)

        self.kpi_widget = QWidget() 
        self.kpi_layout = QHBoxLayout(self.kpi_widget)
        self.kpi_layout.setContentsMargins(0, 0, 0, 0)
        self.kpi_layout.setSpacing(12) 
        
        self.btn_kpi_vencidas = self._create_interactive_kpi(
            "VENCIDAS (TÉRMINO)", "fa5s.calendar-times", "#FEE2E2", DANGER, "vencidas",
            tooltip="Camiones cuyo TÉRMINO CONTRATO ya pasó (fecha anterior a hoy).\nNo incluye contratos MENSUAL, que nunca vencen.\n\nHaz clic para filtrar la tabla por esta categoría."
        )
        self.btn_kpi_activas = self._create_interactive_kpi(
            "ACTIVAS (TÉRMINO)", "fa5s.check-circle", "#D1FAE5", SUCCESS, "activas",
            tooltip="Camiones con contrato vigente: MENSUAL, o con TÉRMINO CONTRATO igual o posterior a hoy.\n\nHaz clic para filtrar la tabla por esta categoría."
        )
        self.btn_kpi_xvencer = self._create_interactive_kpi(
            "<= 30 DIAS X VENCER", "fa5s.clock", "#FEF3C7", WARNING, "xvencer",
            tooltip="Camiones cuyo contrato vence dentro de los próximos 30 días HÁBILES (lunes a viernes, sin feriados).\nNo incluye contratos ya vencidos ni MENSUAL.\n\nHaz clic para filtrar la tabla por esta categoría."
        )
        self.btn_kpi_total = self._create_interactive_kpi(
            "TOTAL CAMIONES", "fa5s.chart-bar", "#DBEAFE", PRIMARY, "total",
            tooltip="Total de camiones cargados actualmente en Comercial, sin filtrar.\n\nHaz clic para quitar el filtro y ver todos."
        )
        
        self.btn_kpi_vencidas.clicked.connect(lambda: self._apply_kpi_filter("vencidas"))
        self.btn_kpi_activas.clicked.connect(lambda: self._apply_kpi_filter("activas"))
        self.btn_kpi_xvencer.clicked.connect(lambda: self._apply_kpi_filter("xvencer"))
        self.btn_kpi_total.clicked.connect(lambda: self._apply_kpi_filter("total"))
        
        main_layout.addWidget(self.kpi_widget)

        self.controls_frame = QFrame()
        ThemeManager.apply_card_style(self.controls_frame)
        
        controls_layout = QHBoxLayout(self.controls_frame)
        controls_layout.setContentsMargins(10, 10, 10, 10)
        controls_layout.setSpacing(10)
        
        # Abre el reporte de Notas de Venta en Power BI para consulta manual
        # (filtrar por los últimos 7 dígitos del CHASIS/VIN). No autocompleta
        # nada ni lee el Excel: solo abre el link en el navegador.
        self.btn_notas_venta_bi = QPushButton("BI")
        self.btn_notas_venta_bi.setFixedSize(32, 32)
        self.btn_notas_venta_bi.setStyleSheet("background-color: #F5C518; color: #1F2937; border-radius: 16px; font-weight: bold;")
        self.btn_notas_venta_bi.setToolTip("Abrir Notas de Venta en Power BI")
        self.btn_notas_venta_bi.clicked.connect(self._open_notas_venta_bi)

        self.btn_advanced_filters = QPushButton(" Filtros")
        self.btn_advanced_filters.setIcon(ThemeManager.icon('fa5s.filter', color=TEXT_SECONDARY))
        self.btn_advanced_filters.setCheckable(True)
        ThemeManager.apply_secondary_button(self.btn_advanced_filters)
        self.btn_advanced_filters.toggled.connect(self._toggle_advanced_filters)
        
        self.btn_export_excel = QPushButton(" Excel")
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='white'))
        ThemeManager.apply_success_button(self.btn_export_excel)
        self.btn_export_excel.clicked.connect(self._exportar_excel)
        
        # Alerta de contradicciones ETAPA GESTIÓN vs. reglas de negocio
        # (SIN REGISTRO / ESTADO COMERCIAL). Pequeño y discreto a propósito:
        # solo detecta e informa, no corrige nada automáticamente.
        # Checkable (25-09-2026, a pedido explícito -- mismo pedido que ya
        # tenía btn_revisar_inconsistencias_forma_contrato: "que actualice la
        # tabla de la vista completa"): en vez de abrir un QMessageBox con un
        # dump de texto, filtra la MISMA tabla de Vista Completa mostrando
        # solo los VIN que no cumplen (ver _toggle_filtro_contradicciones_etapa_gestion).
        self.btn_alerta_etapa = QPushButton(" 0")
        self.btn_alerta_etapa.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_alerta_etapa.setCheckable(True)
        ThemeManager.apply_secondary_button(self.btn_alerta_etapa)
        self.btn_alerta_etapa.setIcon(ThemeManager.icon('fa5s.exclamation-triangle', color=TEXT_SECONDARY))
        self.btn_alerta_etapa.setToolTip("Sin contradicciones detectadas en ETAPA GESTIÓN")
        self.btn_alerta_etapa.toggled.connect(self._toggle_filtro_contradicciones_etapa_gestion)
        self._df_contradicciones_etapa = pd.DataFrame()
        self._filtro_contradicciones_etapa_activo = False

        # Revisión de datos históricos contra FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
        # (24-09-2026, a pedido explícito): mismo criterio que btn_alerta_etapa
        # arriba -- solo detecta y muestra, nunca corrige nada automáticamente.
        # Checkable (25-09-2026, a pedido explícito: "quiero que actualice la
        # tabla de la vista completa no me abra una pestaña aparte"): en vez
        # de un diálogo separado, filtra la MISMA tabla de Vista Completa
        # (mismo patrón que btn_advanced_filters/KPIs, ver
        # _toggle_filtro_inconsistencias_forma_contrato/filter_table).
        self.btn_revisar_inconsistencias_forma_contrato = QPushButton(" Revisar inconsistencias")
        self.btn_revisar_inconsistencias_forma_contrato.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_revisar_inconsistencias_forma_contrato.setCheckable(True)
        ThemeManager.apply_secondary_button(self.btn_revisar_inconsistencias_forma_contrato)
        self.btn_revisar_inconsistencias_forma_contrato.setIcon(ThemeManager.icon('fa5s.clipboard-check', color=TEXT_SECONDARY))
        self.btn_revisar_inconsistencias_forma_contrato.setToolTip(
            "Filtra la tabla a las unidades cuya combinación de FORMA DE CONTRATO / TIPO DE FACTURACION "
            "no cumple la matriz de negocio. No corrige nada automáticamente.\n\n"
            "Nota: TIPO DE FACTURACION proviene de RM_CONTRATOS.xlsx y se sobrescribe en cada sincronización -- "
            "una corrección hecha solo aquí puede volver a quedar inconsistente si el RM no se actualiza también."
        )
        self.btn_revisar_inconsistencias_forma_contrato.toggled.connect(self._toggle_filtro_inconsistencias_forma_contrato)
        self._df_inconsistencias_forma_contrato = pd.DataFrame()
        self._filtro_inconsistencias_forma_contrato_activo = False

        self.btn_reload = QPushButton(" Recargar")
        self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(self.btn_reload)
        self.btn_reload.clicked.connect(self._trigger_reload)

        self.btn_sync_reporte = QPushButton(" Sincronizar RM_CONTRATOS")
        self.btn_sync_reporte.setIcon(ThemeManager.icon('fa5s.cloud-download-alt', color='white'))
        self.btn_sync_reporte.setStyleSheet(f"background-color: #8B5CF6; color: white; border-radius: 6px; font-weight: bold; padding: 6px 12px;") 
        self.btn_sync_reporte.clicked.connect(self._open_sync_dialog)
        
        self.btn_save = QPushButton(" Guardar")
        self.btn_save.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        ThemeManager.apply_primary_button(self.btn_save)
        self.btn_save.clicked.connect(self.confirm_save)

        controls_layout.addWidget(self.btn_notas_venta_bi)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_advanced_filters)
        controls_layout.addWidget(self.btn_export_excel)
        controls_layout.addWidget(self.btn_alerta_etapa)
        controls_layout.addWidget(self.btn_revisar_inconsistencias_forma_contrato)
        controls_layout.addWidget(self.btn_reload)
        controls_layout.addWidget(self.btn_sync_reporte)
        controls_layout.addWidget(self.btn_save)
        
        main_layout.addWidget(self.controls_frame)

        self.advanced_filters_frame = QFrame()
        ThemeManager.apply_card_style(self.advanced_filters_frame)
        self.advanced_filters_frame.hide()
        
        advanced_layout = QHBoxLayout(self.advanced_filters_frame)
        advanced_layout.setContentsMargins(10, 8, 10, 8) 
        advanced_layout.setSpacing(12)

        # Los filtros de columna (antes solo Ejecutivo / Estado Comercial /
        # Estado de Activación / Industria / Periodo Interno) vivían aquí como
        # botones independientes; ahora TODA columna visible de la tabla tiene
        # su filtro integrado en el encabezado (ver FilterHeaderView,
        # _refrescar_opciones_header_filter y _on_header_filter_button_clicked).

        self.btn_columns = QPushButton(" Ocultar/Mostrar")
        self.btn_columns.setIcon(ThemeManager.icon('fa5s.columns', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(self.btn_columns)
        self.list_columnas = QListWidget()
        # Se conecta una sola vez aquí (antes vivía en load_data y se acumulaba
        # una conexión extra en cada recarga).
        self.list_columnas.itemChanged.connect(self._on_columna_item_changed)
        self.menu_columnas = self._create_filter_menu(
            self.btn_columns, self.list_columnas, self._column_items,
            lambda: self._set_all_columns(True), lambda: self._set_all_columns(False)
        )
        self._create_compact_filter_block(advanced_layout, "Columnas:", self.btn_columns)

        self.btn_close_filters = QPushButton()
        self.btn_close_filters.setIcon(ThemeManager.icon('fa5s.times', color=DANGER)) 
        self.btn_close_filters.setFixedSize(30, 30)
        self.btn_close_filters.setStyleSheet(f"border: 1px solid {DANGER}; border-radius: 6px; background-color: #FEF2F2;")
        self.btn_close_filters.clicked.connect(self._clear_and_hide_advanced_filters)

        advanced_layout.addStretch()
        advanced_layout.addWidget(self.btn_close_filters, alignment=Qt.AlignmentFlag.AlignBottom)
        
        main_layout.addWidget(self.advanced_filters_frame)

        self.table = AppTableWidget()
        self.table.menu_type = "comercial"
        self.table.action_editar_unidad.connect(self._handle_editar_unidad)
        self.table.item_edited.connect(self.on_item_edited)
        self.table.sort_changed.connect(self.filter_table)

        self.model = PandasTableModel()
        self.table.set_model_and_delegate(self.model, self.dropdown_options)

        # Qué columnas son filtrables se decide dinámicamente en
        # _refrescar_opciones_header_filter (llamado desde load_data), no
        # aquí: en este punto todavía no existe self.df_base.
        self.table.horizontalHeader().filter_button_clicked.connect(self._on_header_filter_button_clicked)

        original_key_press = self.table.keyPressEvent

        def custom_key_press(event):
            if event.matches(QKeySequence.StandardKey.Paste):
                indexes = self.table.selectedIndexes()
                if indexes:
                    df_view = self.model.get_df()
                    col_idx_actual = indexes[0].column()
                    if col_idx_actual < len(df_view.columns):
                        col_name_actual = df_view.columns[col_idx_actual]
                        if col_name_actual in self.dropdown_options:
                            selected_cells_same_col = [idx for idx in indexes if idx.column() == col_idx_actual]
                            if selected_cells_same_col:
                                self.paste_dropdown_value_to_selection(col_name_actual, selected_cells_same_col)
                                return
            original_key_press(event)

        self.table.keyPressEvent = custom_key_press

        main_layout.addWidget(self.table)

    def paste_dropdown_value_to_selection(self, col_name, selected_cells):
        clipboard_text = QApplication.clipboard().text().strip()
        if not clipboard_text:
            return

        resultado, valor = comercial_services.validar_valor_pegado(col_name, clipboard_text, self.dropdown_options)

        if resultado == "sin_opciones":
            return

        if resultado == "invalido":
            QMessageBox.warning(self, "Pegado Inválido", valor)
            return  # Interrumpe el pegado, conservando el valor original de cada celda

        valor_correcto = valor
        for idx in selected_cells:
            self.model.setData(idx, valor_correcto, Qt.ItemDataRole.EditRole)

    def _open_notas_venta_bi(self):
        """Abre el reporte de Notas de Venta en Power BI para consulta manual
        (el usuario filtra por los últimos 7 dígitos del CHASIS/VIN). No lee
        ni parsea ningún Excel: solo abre el link en el navegador."""
        if REPORTE_NOTAS_VENTAS_URL:
            QDesktopServices.openUrl(QUrl(REPORTE_NOTAS_VENTAS_URL))
        else:
            QMessageBox.warning(self, "Enlace Vacío", "No hay URL configurada para el Reporte de Notas de Ventas.\nPor favor, actualízalo en Configuración.")

    def _create_interactive_kpi(self, title, icon_name, icon_bg_color, text_color, filter_id, tooltip=""):
        btn = QPushButton()
        btn.setObjectName(f"kpi_{filter_id}")
        btn.setFixedHeight(70)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setCheckable(True)
        if tooltip:
            btn.setToolTip(tooltip)
        btn.setStyleSheet(f"""
            QPushButton {{ background-color: {SURFACE}; border-radius: 10px; border: 1px solid {BORDER}; text-align: left; }}
            QPushButton:hover {{ border: 1px solid #9CA3AF; }}
            QPushButton:checked {{ border: 2px solid {text_color}; background-color: #F8FAFC; }}
        """)
        
        layout = QHBoxLayout(btn)
        layout.setContentsMargins(12, 10, 15, 10)
        layout.setSpacing(12)
        
        icon_frame = QFrame()
        icon_frame.setFixedSize(40, 40)
        icon_frame.setStyleSheet(f"background-color: {icon_bg_color}; border-radius: 8px; border: none;")
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap(icon_name, color=text_color, size=20))
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        
        text_layout = QVBoxLayout()
        text_layout.setSpacing(0) 
        
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {text_color}; font-size: 10px; font-weight: bold; background: transparent; border: none;")
        val_lbl = QLabel("0")
        val_lbl.setObjectName("val_label")
        val_lbl.setStyleSheet(f"color: {text_color}; font-size: 20px; font-weight: bold; background: transparent; border: none;")
        
        text_layout.addWidget(title_lbl)
        text_layout.addWidget(val_lbl)
        
        layout.addWidget(icon_frame)
        layout.addLayout(text_layout)
        layout.addStretch()
        self.kpi_layout.addWidget(btn)
        return btn

    def _update_kpi_value(self, btn, value):
        lbl = btn.findChild(QLabel, "val_label")
        if lbl: lbl.setText(str(value))

    def _apply_kpi_filter(self, filter_id):
        for btn in [self.btn_kpi_vencidas, self.btn_kpi_activas, self.btn_kpi_xvencer, self.btn_kpi_total]:
            if btn.objectName() != f"kpi_{filter_id}":
                btn.setChecked(False)
        
        btn_clicked = self.findChild(QPushButton, f"kpi_{filter_id}")
        if btn_clicked.isChecked():
            self.current_kpi_filter = filter_id
        else:
            self.current_kpi_filter = "total"
            self.btn_kpi_total.setChecked(True)
            
        self.filter_table()

    def _trigger_reload(self):
        self.btn_reload.setText(" Cargando...")
        self.btn_reload.setIcon(qta.icon('fa5s.sync', color=TEXT_SECONDARY, animation=qta.Spin(self.btn_reload)))
        self.btn_reload.setEnabled(False) 
        self.btn_save.setEnabled(False)
        
        self.data_manager.load_data_async()
        QTimer.singleShot(12000, self._force_unlock_buttons)

    def _force_unlock_buttons(self):
        if not self.btn_reload.isEnabled():
            self.btn_reload.setText(" Recargar")
            self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
            self.btn_reload.setEnabled(True)
            self.btn_save.setEnabled(True)

    def _on_global_data_ready(self):
        try:
            if self._skip_self_triggered_reload:
                self._skip_self_triggered_reload = False
            elif getattr(self, 'es_visible', self.isVisible)():
                self.load_data()
            else:
                self._data_dirty = True
        except Exception as e:
            pass
        finally:
            self.btn_reload.setText(" Recargar")
            self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
            self.btn_reload.setEnabled(True)

            self.btn_save.setText(" Guardar")
            self.btn_save.setIcon(ThemeManager.icon('fa5s.save', color='white'))
            self.btn_save.setEnabled(True)

    def refresh_if_dirty(self):
        """Llamado por MainWindow._trigger_load_data al navegar a este modulo.
        Protege pending_changes: si hay ediciones sin guardar, nunca las
        descarta en silencio -- reutiliza el mismo patron de dialogo de 3
        opciones que MainWindow._on_snapshot_finished usa para el caso
        analogo de sincronizacion externa (Guardar / Descartar y Recargar /
        Cancelar), en vez de forzar un load_data() que las borraria."""
        if not self._data_dirty:
            return

        if self.pending_changes:
            self._confirmar_recarga_con_cambios_pendientes()
        else:
            self.load_data()

    def _confirmar_recarga_con_cambios_pendientes(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Base de datos modificada")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText("La base de datos cambió mientras tenías cambios sin guardar en Comercial.")
        msg.setInformativeText(
            "Tienes cambios sin guardar en esta pantalla.\n\n"
            "• Si presionas 'Guardar mis cambios', se aplicarán a la base de datos.\n"
            "• Si presionas 'Descartar y Recargar', perderás tus cambios y verás los datos actualizados."
        )
        btn_guardar = msg.addButton("Guardar mis cambios", QMessageBox.ButtonRole.AcceptRole)
        btn_recargar = msg.addButton("Descartar y Recargar", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)

        msg.exec()

        if msg.clickedButton() == btn_guardar:
            self.confirm_save()
        elif msg.clickedButton() == btn_recargar:
            self.load_data()
        # Cancelar: no hace nada -- sigue dirty=True y con pending_changes
        # intactos hasta la proxima vez que el usuario entre a este modulo.

    def _on_load_error(self, error_msg):
        self.btn_reload.setText(" Recargar")
        self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
        self.btn_reload.setEnabled(True)
        self.btn_save.setEnabled(True)
        QMessageBox.critical(self, "Error al Cargar", f"Ocurrió un problema al leer los datos:\n{error_msg}")

    def _actualizar_alerta_etapa_gestion(self):
        """Refresca el botón de alerta con el número de filas cuyo ETAPA
        GESTIÓN actual contradice la regla de negocio centralizada en
        DataFrameFormatter.calcular_etapa_gestion_esperada (vía
        comercial_services.detectar_contradicciones_etapa_gestion). Solo
        detecta e informa: no modifica ninguna fila. No toca el estilo si el
        filtro está activo (ver _toggle_filtro_contradicciones_etapa_gestion,
        que controla ese estilo mientras el botón está presionado)."""
        count = len(self._df_contradicciones_etapa)
        self.btn_alerta_etapa.setText(f" {count}")
        if getattr(self, '_filtro_contradicciones_etapa_activo', False):
            return
        if count > 0:
            self.btn_alerta_etapa.setIcon(ThemeManager.icon('fa5s.exclamation-triangle', color=estilo_com.ROJO))
            estilo_com.aplicar_estilo_boton_barra(self.btn_alerta_etapa, 'alerta')
            self.btn_alerta_etapa.setToolTip(
                f"{count} fila(s) contradicen las reglas de ETAPA GESTIÓN. Click para filtrar la tabla."
            )
        else:
            self.btn_alerta_etapa.setIcon(ThemeManager.icon('fa5s.exclamation-triangle', color=TEXT_SECONDARY))
            estilo_com.aplicar_estilo_boton_barra(self.btn_alerta_etapa, 'neutro')
            self.btn_alerta_etapa.setToolTip("Sin contradicciones detectadas en ETAPA GESTIÓN")

    def _toggle_filtro_contradicciones_etapa_gestion(self, checked):
        """Botón de alerta ETAPA GESTIÓN (25-09-2026, a pedido explícito --
        mismo pedido que ya resolvió btn_revisar_inconsistencias_forma_contrato:
        "que actualice la tabla de la vista completa y muestre esos VIN que
        no cumplen"): reemplaza el QMessageBox con un dump de texto por el
        mismo mecanismo de filtro checkable sobre la tabla de Vista Completa
        (self.table/self.model, vía filter_table), mismo patrón que
        _toggle_filtro_inconsistencias_forma_contrato. Solo detecta y
        filtra -- nunca corrige nada automáticamente."""
        if checked and (self._df_contradicciones_etapa is None or self._df_contradicciones_etapa.empty):
            self.btn_alerta_etapa.blockSignals(True)
            self.btn_alerta_etapa.setChecked(False)
            self.btn_alerta_etapa.blockSignals(False)
            QMessageBox.information(
                self, "Contradicciones ETAPA GESTIÓN",
                "No se encontraron filas que contradigan las reglas de gestión."
            )
            return

        self._filtro_contradicciones_etapa_activo = checked
        if checked:
            estilo_com.aplicar_estilo_boton_barra(self.btn_alerta_etapa, 'activo')
            self.btn_alerta_etapa.setIcon(ThemeManager.icon('fa5s.exclamation-triangle', color=estilo_com.PRIMARIO))
        else:
            self._actualizar_alerta_etapa_gestion()

        self.filter_table()

    def _toggle_filtro_inconsistencias_forma_contrato(self, checked):
        """Ver FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ (constants.py) y
        comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion.
        25-09-2026, a pedido explícito ("quiero que actualice la tabla de la
        vista completa no me abra una pestaña aparte"): reemplaza el diálogo
        separado que tenía antes -- filtra la MISMA tabla de Vista Completa
        (self.table/self.model, vía filter_table) mostrando solo las
        unidades inconsistentes, con las columnas completas de siempre.
        Solo detecta y filtra -- NUNCA corrige nada automáticamente: la
        corrección sigue siendo el menú contextual "Editar Unidad" que esa
        misma tabla ya ofrece (self.table.action_editar_unidad, conectado en
        _setup_ui), que abre ComercialAgregarDialog con las validaciones
        reales de la matriz."""
        if checked and (self._df_inconsistencias_forma_contrato is None or self._df_inconsistencias_forma_contrato.empty):
            self.btn_revisar_inconsistencias_forma_contrato.blockSignals(True)
            self.btn_revisar_inconsistencias_forma_contrato.setChecked(False)
            self.btn_revisar_inconsistencias_forma_contrato.blockSignals(False)
            QMessageBox.information(
                self, "Revisar inconsistencias",
                "No se encontraron combinaciones de FORMA DE CONTRATO / TIPO DE FACTURACION "
                "que contradigan la matriz de negocio."
            )
            return

        self._filtro_inconsistencias_forma_contrato_activo = checked
        if checked:
            estilo_com.aplicar_estilo_boton_barra(self.btn_revisar_inconsistencias_forma_contrato, 'activo')
            self.btn_revisar_inconsistencias_forma_contrato.setIcon(ThemeManager.icon('fa5s.clipboard-check', color=estilo_com.PRIMARIO))
        else:
            estilo_com.aplicar_estilo_boton_barra(self.btn_revisar_inconsistencias_forma_contrato, 'neutro')
            self.btn_revisar_inconsistencias_forma_contrato.setIcon(ThemeManager.icon('fa5s.clipboard-check', color=TEXT_SECONDARY))

        self.filter_table()

    def _toggle_advanced_filters(self, checked):
        self.advanced_filters_frame.setVisible(checked)
        if checked:
            self.btn_advanced_filters.setStyleSheet(f"padding: 6px 12px; border: 1px solid {PRIMARY}; border-radius: 6px; background-color: #E0F2FE; color: {PRIMARY}; font-weight: bold;")
            self.btn_advanced_filters.setIcon(ThemeManager.icon('fa5s.filter', color=PRIMARY))
        else:
            ThemeManager.apply_secondary_button(self.btn_advanced_filters)
            self.btn_advanced_filters.setIcon(ThemeManager.icon('fa5s.filter', color=TEXT_SECONDARY))

    def _toggle_kpis(self):
        is_visible = self.kpi_widget.isVisible()
        self.kpi_widget.setVisible(not is_visible)
        if is_visible:
            self.btn_toggle_kpi.setText(" Mostrar KPIs")
            self.btn_toggle_kpi.setIcon(ThemeManager.icon('fa5s.eye', color=TEXT_SECONDARY))
        else:
            self.btn_toggle_kpi.setText(" Ocultar KPIs")
            self.btn_toggle_kpi.setIcon(ThemeManager.icon('fa5s.eye-slash', color=TEXT_SECONDARY))

    def _populate_filter_list(self, list_widget, items_storage, items_data, default_state=Qt.CheckState.Checked):
        list_widget.clear()
        items_storage.clear()
        for data in items_data:
            item = QListWidgetItem(str(data))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(default_state)
            list_widget.addItem(item)
            items_storage.append(item)
            
    def _update_filter_button_text(self, btn, items_list, base_text):
        activos = sum(1 for i in items_list if i.checkState() in (Qt.CheckState.Checked, 2))
        total = len(items_list)
        if activos == total or activos == 0:
            btn.setText(f" {base_text}")
        else:
            btn.setText(f" {base_text} ({activos})")

    def _set_all_columns(self, is_checked):
        self.list_columnas.blockSignals(True) 
        state = Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked
        for item in self._column_items:
            item.setCheckState(state)
            col_idx = item.data(Qt.ItemDataRole.UserRole)
            self.table.setColumnHidden(col_idx, not is_checked)
        self.list_columnas.blockSignals(False)
        self._update_filter_button_text(self.btn_columns, self._column_items, "Columnas")
        self._save_column_settings() 

    def _on_columna_item_changed(self, item):
        col_idx = item.data(Qt.ItemDataRole.UserRole)
        is_hidden = item.checkState() == Qt.CheckState.Unchecked
        self.table.setColumnHidden(col_idx, is_hidden)
        self._update_filter_button_text(self.btn_columns, self._column_items, "Columnas")
        self._save_column_settings() 
        
    def _save_column_settings(self):
        hidden_cols = []
        for item in self._column_items:
            if item.checkState() == Qt.CheckState.Unchecked:
                hidden_cols.append(item.text())
        self.settings.setValue("hidden_columns", hidden_cols)

    def _refrescar_opciones_header_filter(self):
        """Recalcula, a partir de self.df_base, las opciones disponibles y
        resetea a "todo seleccionado" (sin filtro) el filtro de encabezado de
        CADA columna visible (ver HEADER_FILTER_COLUMNAS_EXCLUIDAS para las
        pocas columnas técnicas que quedan afuera) -- igual que hacía el
        mecanismo anterior de QListWidget en cada load_data(), pero ahora sin
        listar columnas a mano: si mañana aparece una columna nueva en
        df_base, recibe su filtro automáticamente. Separado de load_data()
        para que los tests puedan reconstruir df_base manualmente y luego
        llamar esto sin pasar por DataManager."""
        columnas_filtrables = [c for c in self.df_base.columns if c not in HEADER_FILTER_COLUMNAS_EXCLUIDAS]

        self._header_filter_options = {}
        self._header_filter_selected = {}
        for col in columnas_filtrables:
            # pd.unique primero: la regla se evalúa sobre los valores
            # distintos, no fila por fila (mismo resultado, mucho menos trabajo).
            valores = sorted(
                {str(v).strip() for v in pd.unique(self.df_base[col]) if not _valor_esta_vacio(v)},
                reverse=(col in HEADER_FILTER_ORDEN_DESCENDENTE)
            )
            self._header_filter_options[col] = valores
            self._header_filter_selected[col] = set(valores)

        self.table.set_header_filterable_columns(columnas_filtrables)

    def _apply_header_filter(self, col_name, selected_values):
        """Punto único de entrada para cambiar el filtro de una columna con
        botón en el encabezado: lo usan tanto el menú desplegable (Aplicar /
        Limpiar / Todos) como los tests, sin pasar por la UI."""
        self._header_filter_selected[col_name] = set(selected_values)
        self.filter_table()

    def _on_header_filter_button_clicked(self, col_name, global_point):
        self._show_header_filter_menu(col_name, global_point)

    def _show_header_filter_menu(self, col_name, global_point):
        opciones = self._header_filter_options.get(col_name, [])
        seleccionados = self._header_filter_selected.get(col_name, set(opciones))

        menu = QMenu(self)
        menu.setStyleSheet(f"QMenu {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 3px; }}")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        lbl_title = QLabel(f"Filtrar {col_name}")
        lbl_title.setStyleSheet(f"font-size: 10px; font-weight: bold; color: {TEXT_SECONDARY};")
        layout.addWidget(lbl_title)

        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Buscar...")
        search_edit.setFixedHeight(24)
        ThemeManager.apply_search_bar(search_edit)
        layout.addWidget(search_edit)

        # Ancho fijo + alto MÁXIMO (no fijo): con pocas opciones el menú queda
        # compacto, y con muchas la lista deja de crecer y muestra su propio
        # scroll vertical en vez de empujar el menú fuera de la pantalla.
        list_widget = QListWidget()
        list_widget.setFixedWidth(210)
        list_widget.setMaximumHeight(170)
        list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        item_todos = QListWidgetItem("Todos")
        item_todos.setFlags(item_todos.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item_todos.setCheckState(Qt.CheckState.Checked if opciones and len(seleccionados) == len(opciones) else Qt.CheckState.Unchecked)
        list_widget.addItem(item_todos)

        valor_items = []
        for valor in opciones:
            item = QListWidgetItem(valor)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if valor in seleccionados else Qt.CheckState.Unchecked)
            list_widget.addItem(item)
            valor_items.append(item)

        def _on_item_changed(changed_item):
            list_widget.blockSignals(True)
            if changed_item is item_todos:
                state = item_todos.checkState()
                for it in valor_items:
                    it.setCheckState(state)
            else:
                todo_marcado = all(it.checkState() == Qt.CheckState.Checked for it in valor_items)
                item_todos.setCheckState(Qt.CheckState.Checked if todo_marcado else Qt.CheckState.Unchecked)
            list_widget.blockSignals(False)

        list_widget.itemChanged.connect(_on_item_changed)

        def _on_search_text(text):
            texto = text.strip().lower()
            for it in valor_items:
                it.setHidden(texto not in it.text().lower())

        search_edit.textChanged.connect(_on_search_text)

        layout.addWidget(list_widget)

        btn_row = QHBoxLayout()
        btn_limpiar = QPushButton("Limpiar")
        ThemeManager.apply_danger_button(btn_limpiar)
        btn_aplicar = QPushButton("Aplicar")
        ThemeManager.apply_primary_button(btn_aplicar)
        btn_row.addWidget(btn_limpiar)
        btn_row.addWidget(btn_aplicar)
        layout.addLayout(btn_row)

        def _limpiar():
            self._apply_header_filter(col_name, opciones)
            menu.close()

        def _aplicar():
            seleccion_actual = {it.text() for it in valor_items if it.checkState() == Qt.CheckState.Checked}
            self._apply_header_filter(col_name, seleccion_actual)
            menu.close()

        btn_limpiar.clicked.connect(_limpiar)
        btn_aplicar.clicked.connect(_aplicar)

        action_widget = QWidgetAction(menu)
        action_widget.setDefaultWidget(container)
        menu.addAction(action_widget)

        menu.exec(self._punto_menu_dentro_de_pantalla(global_point, container))

    def _punto_menu_dentro_de_pantalla(self, global_point, container):
        """Ajusta el punto de apertura del menú para que quede completo
        dentro del área visible de la pantalla (sin tapar la barra de tareas
        de Windows), sin importar qué tan cerca del borde se abrió."""
        container.adjustSize()
        ancho_estimado = container.sizeHint().width() + 20
        alto_estimado = container.sizeHint().height() + 20

        screen = QApplication.screenAt(global_point) or QApplication.primaryScreen()
        if screen is None:
            return global_point

        area = screen.availableGeometry()
        x = min(global_point.x(), area.right() - ancho_estimado)
        y = min(global_point.y(), area.bottom() - alto_estimado)
        x = max(x, area.left())
        y = max(y, area.top())
        return QPoint(x, y)

    def _clear_and_hide_advanced_filters(self):
        """Botón "X" del panel de filtros avanzados: los filtros de columna
        que antes vivían en este panel (Ejecutivo, Estado Comercial, Estado
        Activación, Industria, Periodo) ahora están integrados en el
        encabezado de la tabla, cada uno con su propio "Limpiar". Este panel
        solo conserva "Columnas", así que el botón únicamente lo oculta."""
        self.btn_advanced_filters.setChecked(False)

    # Callback fijado por ComercialModule.__init__ (self.legacy.on_editar_unidad_solicitado
    # = self._iniciar_edicion_unidad) -- ver _handle_editar_unidad. _ComercialModuleLegacy
    # nunca se instancia por fuera de ComercialModule (único punto de construcción en todo
    # el proyecto, ver ComercialModule.__init__), así que en la práctica siempre queda
    # asignado; el default None es solo una red de seguridad defensiva.
    on_editar_unidad_solicitado = None
    # Ídem, invocado por _on_editar_unidad_finished tras un guardado exitoso
    # (ver ComercialModule._on_edicion_unidad_guardada): devuelve la pestaña
    # "Unidad nueva" a modo crear en vez de dejarla mostrando la edición ya
    # guardada.
    on_edicion_unidad_guardada = None

    def _handle_editar_unidad(self, row, vin, desde_por_gestionar=False, forzar_activacion_pendiente=False,
                               desde_vigentes=False):
        """Localiza los datos actuales de esta unidad y delega la edición a
        ComercialModule (self.on_editar_unidad_solicitado), que la muestra en
        la pestaña "Unidad nueva" en modo edición (25-09-2026, refactor: antes
        abría ComercialAgregarDialog como ventana modal aquí mismo -- ver
        ComercialModule._iniciar_edicion_unidad/_on_unidad_nueva_confirmada,
        que ahora hacen ese trabajo con ComercialUnidadFormWidget embebido).

        `desde_por_gestionar` (22-09-2026, ampliado a "Gestionar Bajas" a
        pedido explícito; ajustado 25-09-2026): True cuando se edita desde
        "Por gestionar" o desde "Gestionar Bajas" (caso "cliente interesado
        en volver") del nuevo UI de Comercial (ver
        _on_accion_editar_unidad_clicked) -- activa `restringir_activacion`
        en el formulario (pestaña Operaciones SIEMPRE de solo lectura, sin
        importar el tipo de unidad) y bloquea ETAPA GESTIÓN.

        `forzar_activacion_pendiente` (25-09-2026, a pedido explícito):
        ya calculado por el llamador (ver
        ComercialModule._es_unidad_sin_contrato_sin_registro) -- True solo
        si la unidad es realmente "Sin Contrato"/"Sin Registro". Fuerza y
        restringe ESTADO COMERCIAL="Activación Pendiente" y ESTADO DE
        ACTIVACIÓN ACTUAL="Activando" -- el resto de las unidades de "Por
        gestionar" solo ven Operaciones bloqueada, sin ningún valor
        forzado. El "Editar" de Vista Completa (legacy,
        action_editar_unidad) y las demás sub-pestañas siguen sin esta
        restricción.

        `desde_vigentes` (25-09-2026, a pedido explícito): True cuando se
        edita desde "Vigentes" -- activa el modo restringido propio de esa
        sub-pestaña (ver `restringir_vigentes` en ComercialAgregarDialog):
        quita "Vencido"/"Activación Pendiente" del combo ESTADO COMERCIAL y
        deja de solo lectura toda la pestaña Operaciones, sin forzar ningún
        valor (a diferencia de `desde_por_gestionar`)."""
        if self.df_base.empty or 'VIN' not in self.df_base.columns:
            return
        coincidencias = self.df_base[self.df_base['VIN'].astype(str).str.strip() == str(vin).strip()]
        if coincidencias.empty:
            QMessageBox.warning(self, "Unidad no encontrada", f"No se encontró la unidad con VIN {vin} en los datos actuales.")
            return
        fila = coincidencias.iloc[0]
        datos_actuales = {col: ('' if pd.isna(val) else str(val)) for col, val in fila.items()}

        if self.on_editar_unidad_solicitado is None:
            return
        self.on_editar_unidad_solicitado(
            datos_actuales,
            restringir_activacion=desde_por_gestionar,
            forzar_activacion_pendiente=forzar_activacion_pendiente,
            restringir_vigentes=desde_vigentes,
        )

    def guardar_edicion_unidad(self, vin, cambios):
        """Guarda `cambios` (dict campo->valor nuevo, ya diffeados contra los
        datos originales) sobre la unidad `vin`: mismo SaveExcelThread/
        ExcelWriter.update_cells de siempre. Extraído de _handle_editar_unidad
        (25-09-2026) para que ComercialModule._on_unidad_nueva_confirmada
        pueda invocarlo directamente tras confirmar el formulario embebido en
        "Unidad nueva", sin pasar por un diálogo modal."""
        self.btn_save.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Guardando cambios de la unidad…")
        self._editar_unidad_thread = SaveExcelThread(
            self.writer, comercial_services.agregar_id_a_cambios({vin: {'VIN': vin, 'cambios': cambios}}, self.df_base),
            module_name="Comercial"
        )
        self._editar_unidad_thread.finished_signal.connect(
            lambda success: self._on_editar_unidad_finished(success, vin, cambios)
        )
        self._editar_unidad_thread.logs_actualizados_signal.connect(self.data_manager.set_logs_df)
        self._editar_unidad_thread.start()

    def _on_editar_unidad_finished(self, success, vin, cambios):
        QApplication.restoreOverrideCursor()
        self.btn_save.setEnabled(True)
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.critical(self, "Error", "No se pudieron guardar los cambios de la unidad.")
            return
        guardado_listo(self)
        dm = self.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(
                dm.df_master, comercial_services.agregar_id_a_cambios({vin: {'cambios': cambios}}, self.df_base)
            )
            dm.data_ready.emit()
        vin_final = cambios.get('VIN', vin)
        terminar_guardando(self)
        if self.on_edicion_unidad_guardada is not None:
            self.on_edicion_unidad_guardada(vin_final, cambios)


    def load_data(self):
        self._data_dirty = False
        self.pending_changes.clear()
        self.df_base = comercial_services.preparar_df_base_comercial(self.data_manager.get_comercial_df())

        # Instrumentacion temporal (auditoria de rendimiento B-6, 18-09-2026):
        # mide el costo real del apply(axis=1) sobre el df completo en Main
        # Thread. No cambia el comportamiento.
        with medir(f"B-6 detectar_contradicciones_etapa_gestion ({len(self.df_base)} filas)"):
            self._df_contradicciones_etapa = comercial_services.detectar_contradicciones_etapa_gestion(self.df_base)
        self._actualizar_alerta_etapa_gestion()

        self._df_inconsistencias_forma_contrato = comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion(self.df_base)

        if self.df_base.empty:
            self._tabla_pendiente = False
            self.model.set_data(pd.DataFrame())
            return

        if self._tabla_diferida and not self.isVisible():
            self._tabla_pendiente = True
            return
        self._poblar_tabla()

    def _asegurar_tabla(self):
        if self._tabla_pendiente:
            self._poblar_tabla()

    def showEvent(self, event):
        super().showEvent(event)
        self._asegurar_tabla()

    def _exportar_excel(self):
        self._asegurar_tabla()
        self.table.export_to_excel("Reporte_Comercial")

    def _poblar_tabla(self):
        """KPIs, filtros de encabezado, lista de columnas y tabla propia."""
        self._tabla_pendiente = False
        kpis = comercial_services.calcular_kpis_vigencia(self.df_base)
        self._update_kpi_value(self.btn_kpi_total, kpis["total"])
        self._update_kpi_value(self.btn_kpi_vencidas, kpis["vencidas"])
        self._update_kpi_value(self.btn_kpi_activas, kpis["activas"])
        self._update_kpi_value(self.btn_kpi_xvencer, kpis["xvencer"])
        self._preparar_columnas_tabla()
        self.btn_kpi_total.setChecked(True)
        self.current_kpi_filter = "total"
        self.filter_table()

    def _preparar_columnas_tabla(self):
        self._tabla_pendiente = False
        self._refrescar_opciones_header_filter()

        hidden_cols = self.settings.value("hidden_columns", [], type=list)
        self.list_columnas.clear()
        self._column_items = []
        for col_idx, col_name in enumerate(self.df_base.columns):
            if col_name in ['N°', 'PAGO CM_NUM']: continue 
                
            item = QListWidgetItem(col_name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            
            if col_name in hidden_cols:
                self.table.setColumnHidden(col_idx, True)
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                self.table.setColumnHidden(col_idx, False)
                item.setCheckState(Qt.CheckState.Checked)
                
            item.setData(Qt.ItemDataRole.UserRole, col_idx) 
            self.list_columnas.addItem(item)
            self._column_items.append(item)

    def filter_table(self):
        if self.df_base.empty: return
        if self._tabla_pendiente:
            self._preparar_columnas_tabla()

        search_text = self.search_input.text().lower()
        
        df_f = self.df_base.copy()

        if self.current_kpi_filter in ("vencidas", "activas", "xvencer"):
            clasif = comercial_services.clasificar_vigencia_contrato(df_f)
            if self.current_kpi_filter == "vencidas":
                df_f = df_f[clasif['vencido']]
            elif self.current_kpi_filter == "activas":
                df_f = df_f[clasif['activo']]
            elif self.current_kpi_filter == "xvencer":
                df_f = df_f[clasif['por_vencer']]

        # Filtro "Revisar inconsistencias" (25-09-2026, a pedido explícito):
        # se combina con el resto de los filtros de esta tabla (KPI,
        # encabezado, búsqueda) en vez de abrir una pantalla aparte -- mismo
        # criterio de composición AND que ya usan los demás.
        # Dentro de ComercialModule los avisos filtran la bandeja, no esta
        # tabla (así Excel sigue exportando todo)
        avisos_filtran = getattr(self, '_avisos_filtran_tabla', True)
        if avisos_filtran and getattr(self, '_filtro_inconsistencias_forma_contrato_activo', False):
            df_f = comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion(df_f)

        # Filtro de alerta ETAPA GESTIÓN (25-09-2026, a pedido explícito,
        # mismo criterio de composición AND que el filtro de arriba): ver
        # _toggle_filtro_contradicciones_etapa_gestion.
        if avisos_filtran and getattr(self, '_filtro_contradicciones_etapa_activo', False):
            df_f = comercial_services.detectar_contradicciones_etapa_gestion(df_f)

        # Filtros integrados en el encabezado: TODA columna de
        # _header_filter_options (ver _refrescar_opciones_header_filter) tiene
        # su propio filtro. Misma semántica que el mecanismo anterior de
        # checkboxes (0 seleccionados -> vacío; todos -> sin filtro;
        # subconjunto -> isin), preservando la asimetría de
        # mayúsculas/minúsculas por columna (HEADER_FILTER_CASE_INSENSITIVE).
        columnas_filtro_activas = set()
        for col_name, opciones in list(self._header_filter_options.items()):
            if not opciones or col_name not in df_f.columns:
                continue
            seleccionados = self._header_filter_selected.get(col_name, set(opciones))
            if 0 < len(seleccionados) < len(opciones):
                columnas_filtro_activas.add(col_name)

            if len(seleccionados) == 0:
                df_f = df_f.iloc[0:0]
            elif len(seleccionados) < len(opciones):
                serie = df_f[col_name].astype(str).str.strip()
                valores_comparar = seleccionados
                if col_name in HEADER_FILTER_CASE_INSENSITIVE:
                    serie = serie.str.lower()
                    valores_comparar = {v.lower() for v in seleccionados}
                df_f = df_f[serie.isin(valores_comparar)]

        self.table.set_header_filter_active_columns(columnas_filtro_activas)

        if search_text:
            final_mask = comercial_services.construir_mascara_busqueda(
                df_f, search_text, COLUMNAS_BUSQUEDA_COMERCIAL, COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL)
            df_f = df_f[final_mask]

        if self.pending_changes:
            df_f = comercial_services.aplicar_cambios_pendientes(df_f, self.pending_changes)

        if 'PAGO CM' in df_f.columns:
            df_f['PAGO CM'] = df_f['PAGO CM_NUM'].apply(lambda x: f"$-" if x==0 else f"{'-' if x<0 else ''}${int(abs(x)+0.5):,}".replace(",", "."))
        df_f = df_f.drop(columns=['PAGO CM_NUM'], errors='ignore')

        # Ordenamiento tipo Excel elegido por el usuario. Se aplica DESPUÉS de
        # inyectar pending_changes (arriba) y ANTES de numerar N°, para que el
        # número de fila quede secuencial en el orden visual final y el
        # recálculo de _edited_cells de abajo (que itera por posición) siga
        # apuntando a la fila correcta.
        df_f = self.table.apply_sort(df_f)

        df_f['N°'] = range(1, len(df_f) + 1)

        self.model.set_data(df_f)
        
        if self.pending_changes:
            for r in range(len(df_f)):
                v_val = str(df_f.iat[r, df_f.columns.get_loc('VIN')]).strip().upper()
                if v_val in self.pending_changes:
                    for c_name in self.pending_changes[v_val]['cambios']:
                        if c_name in df_f.columns:
                            c_idx = df_f.columns.get_loc(c_name)
                            self.model._edited_cells.add((r, c_idx))
        
        try:
            _aplicar_anchos_columnas_comercial(
                self.table, list(df_f.columns),
                ancho_col_0=50, ancho_razon_social=COMERCIAL_COL_WIDTH_RAZON_SOCIAL,
            )
        except Exception: pass

    def on_item_edited(self, row, col_name, new_value):
        if col_name == 'N°': 
            return 
            
        df_actual = self.model.get_df()
        vin_value = str(df_actual.iat[row, df_actual.columns.get_loc('VIN')]).strip().upper()
        
        if vin_value not in self.pending_changes:
            self.pending_changes[vin_value] = {'VIN': vin_value, 'cambios': {}}
            if 'ID' in df_actual.columns:
                id_fila = comercial_services._normalizar_id_contrato(df_actual.iat[row, df_actual.columns.get_loc('ID')])
                if id_fila:
                    self.pending_changes[vin_value]['ID'] = id_fila

        if col_name == 'DURACIÓN (MESES)':
            resultado, valor = comercial_services.validar_duracion(new_value)

            if resultado == "invalido":
                QMessageBox.warning(self, "Error", valor)
                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = ""
                self.model.layoutChanged.emit()
                return

            if resultado == "mensual":
                self.pending_changes[vin_value]['cambios']['DURACIÓN (MESES)'] = '-'
                df_actual.iat[row, df_actual.columns.get_loc('DURACIÓN (MESES)')] = '-'
                if 'TÉRMINO CONTRATO' in df_actual.columns:
                    self.pending_changes[vin_value]['cambios']['TÉRMINO CONTRATO'] = 'MENSUAL'
                    df_actual.iat[row, df_actual.columns.get_loc('TÉRMINO CONTRATO')] = 'MENSUAL'
            else:  # "vacio" o "numerico"
                self.pending_changes[vin_value]['cambios'][col_name] = valor

        elif col_name in ['INICIO CONTRATO', 'INICIO', 'TERMINO']:
            resultado, valor = comercial_services.validar_fecha_ddmmyyyy(new_value)

            if resultado == "invalido":
                QMessageBox.warning(self, "Error de Formato", valor)
                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = ""
                self.model.layoutChanged.emit()
                return

            self.pending_changes[vin_value]['cambios'][col_name] = valor

        elif col_name == 'PAGO CM':
            resultado, dato = comercial_services.parsear_pago_cm(new_value)

            if resultado == "invalido":
                QMessageBox.warning(self, "Error", "El pago debe ser un número válido.")

                old_row = self.df_base[self.df_base['VIN'].str.strip().str.upper() == vin_value]
                old_val = old_row.iloc[0]['PAGO CM_NUM'] if not old_row.empty else 0
                old_formato = comercial_services.formatear_pago_cm(old_val)

                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = old_formato
                self.model.layoutChanged.emit()
                return

            self.pending_changes[vin_value]['cambios'][col_name] = dato["num"]
            df_actual.iat[row, df_actual.columns.get_loc(col_name)] = dato["formato"]

        else:
            self.pending_changes[vin_value]['cambios'][col_name] = new_value

        limpieza_sin_contrato = comercial_services.aplica_regla_sin_contrato(col_name, new_value)
        for col_limpia, valor_limpia in limpieza_sin_contrato.items():
            if col_limpia in df_actual.columns:
                self.pending_changes[vin_value]['cambios'][col_limpia] = valor_limpia
                df_actual.iat[row, df_actual.columns.get_loc(col_limpia)] = valor_limpia
                self.model._edited_cells.add((row, df_actual.columns.get_loc(col_limpia)))

        limpieza_terminated_cm = comercial_services.aplica_regla_terminated_cm(col_name, new_value)
        for col_limpia, valor_limpia in limpieza_terminated_cm.items():
            if col_limpia in df_actual.columns:
                self.pending_changes[vin_value]['cambios'][col_limpia] = valor_limpia
                df_actual.iat[row, df_actual.columns.get_loc(col_limpia)] = valor_limpia
                self.model._edited_cells.add((row, df_actual.columns.get_loc(col_limpia)))

        if col_name in ['INICIO CONTRATO', 'DURACIÓN (MESES)']:
            from dateutil.relativedelta import relativedelta

            inicio_str = self.pending_changes[vin_value]['cambios'].get('INICIO CONTRATO', str(df_actual.iat[row, df_actual.columns.get_loc('INICIO CONTRATO')]))
            duracion_str = self.pending_changes[vin_value]['cambios'].get('DURACIÓN (MESES)', str(df_actual.iat[row, df_actual.columns.get_loc('DURACIÓN (MESES)')]))

            if inicio_str and str(inicio_str).strip() != "" and str(inicio_str).lower() != 'nan':
                if duracion_str and str(duracion_str).strip() not in ["", "-", "MENSUAL", "nan"]:
                    try:
                        fecha_inicio = pd.to_datetime(str(inicio_str).strip(), dayfirst=True).to_pydatetime()
                        meses_a_sumar = int(float(duracion_str))
                        fecha_termino = fecha_inicio + relativedelta(months=meses_a_sumar)
                        termino_str = fecha_termino.strftime("%d-%m-%Y")
                        
                        if 'TÉRMINO CONTRATO' in df_actual.columns:
                            self.pending_changes[vin_value]['cambios']['TÉRMINO CONTRATO'] = termino_str
                            df_actual.iat[row, df_actual.columns.get_loc('TÉRMINO CONTRATO')] = termino_str
                            
                    except Exception as e:
                        pass

        self.model.layoutChanged.emit()

    def confirm_save(self):
        valid = {k: d for k, d in self.pending_changes.items() if d.get('cambios')}
        if not valid: return QMessageBox.information(self, "Sin cambios", "No hay datos modificados.")

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirmar")
        msg.setText("Se aplicarán en la nube.")
        msg.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Save:
            # Medicion Fase 0 (auditoria de rendimiento, 17-09-2026): linea
            # base "guardado -> interfaz nuevamente disponible", tomada como
            # referencia para Comercial (el modulo con la cascada mas pesada
            # tras data_ready). Se cierra en _on_save_finished. Ver
            # src/core/perf_log.py.
            self._t_inicio_guardado = time.perf_counter()
            self.btn_save.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            mostrar_guardando(self)
            df_actual = self.model.get_df()
            df_actual = comercial_services.aplicar_cambios_pendientes(df_actual, valid)
            self.model.set_data(df_actual)
            self.save_thread = SaveExcelThread(self.writer, valid, module_name="Comercial")
            self.save_thread.finished_signal.connect(self._on_save_finished)
            self.save_thread.logs_actualizados_signal.connect(self.data_manager.set_logs_df)
            self.save_thread.start()

    def _on_save_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_save.setEnabled(True)
        if success:
            guardado_listo(self)
            try:
                dm = self.data_manager
                if not dm.df_master.empty:
                    df_m_copy = dm.df_master.copy()
                    df_m_copy = comercial_services.aplicar_cambios_pendientes(df_m_copy, self.pending_changes)
                    dm.df_master = df_m_copy

                    # Fase 1 de la auditoria de rendimiento (17-09-2026): se
                    # evaluo deduplicar esta llamada usando un flag en el
                    # DataManager (se ejecuta de nuevo, idempotente, desde
                    # MainWindow._on_data_loaded_success al emitir data_ready
                    # unas lineas mas abajo), pero se revirtio -- un flag
                    # compartido en el singleton puede quedar "pegado" entre
                    # tests/flujos que no pasan por el consumidor esperado
                    # (ver test_main_window.TestDataLoadedTriggersRevisionCmReconciliation),
                    # y el riesgo de saltarse silenciosamente una
                    # reconciliacion real en produccion no vale el ahorro de
                    # una lectura+escritura extra de CasosBajaCM.csv.
                    try:
                        cm_bajas_service.procesar_reconciliacion_estado_expired(
                            df_pruebas_actual=dm.df_master,
                            periodo_deteccion=datetime.now().strftime('%Y-%m'),
                            casos_path=config.settings.CASOS_BAJA_CM_PATH,
                        )
                    except Exception as e:
                        print(f"No se pudo reconciliar los casos de Revisión CM por estado Expired: {e}")

                self.pending_changes.clear()
                self._data_dirty = False
                self.df_base = comercial_services.preparar_df_base_comercial(self.data_manager.get_comercial_df())

                kpis = comercial_services.calcular_kpis_vigencia(self.df_base)
                self._update_kpi_value(self.btn_kpi_total, kpis["total"])
                self._update_kpi_value(self.btn_kpi_vencidas, kpis["vencidas"])
                self._update_kpi_value(self.btn_kpi_activas, kpis["activas"])
                self._update_kpi_value(self.btn_kpi_xvencer, kpis["xvencer"])

                self._skip_self_triggered_reload = True
                self.data_manager.data_ready.emit()

                # Cierre de la medicion Fase 0 iniciada en confirm_save(): la
                # cascada sincrona de data_ready.emit() (todos los modulos
                # visibles conectados) ya termino de ejecutarse en la linea
                # anterior, asi que aqui la interfaz vuelve a estar disponible.
                # Se mide antes del QMessageBox de exito (que es un modal
                # bloqueante aparte, no parte del costo de guardado).
                if hasattr(self, '_t_inicio_guardado'):
                    duracion_ms = (time.perf_counter() - self._t_inicio_guardado) * 1000
                    print(f"[PERF] guardado (Comercial) -> interfaz nuevamente disponible: {duracion_ms:.0f} ms")

                terminar_guardando(self)
            except Exception as e:
                print(f"Fallo en inyección RAM: {e}")
                terminar_guardando(self, exito=False)
                self._trigger_reload()
        else:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se guardaron los cambios. SharePoint puede estar bloqueando el archivo. Intenta de nuevo.")

    def _open_sync_dialog(self):
        dialog = SyncRMReporteDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.data_manager.data_ready.emit()


# =========================================================
# DIÁLOGO MODERNO REUTILIZABLE (Confirmar baja de CM)
# =========================================================
class DialogoAccionCm(DialogoAccion):
    """Estados del flujo "Confirmar baja" y demás acciones de Gestionar CM
    sobre la tarjeta compartida DialogoAccion (ver src/ui/dialogo_accion.py)."""

    @classmethod
    def confirmacion(cls, parent, vins):
        """Diálogo previo a confirmar: reemplaza el QMessageBox.question de
        antes. `vins` es la lista (ya deduplicada) de VIN seleccionados en
        Gestionar CM. Acento rojo/danger en el botón principal: es una
        acción de negocio importante (limpia datos de contrato CM)."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Confirmar baja de CM",
            icon_name="fa5s.file-signature", icon_color=PRIMARY, icon_bg_color="#EFF6FF",
            titulo="Confirmar baja de CM",
            subtitulo=f"{cantidad} {plural} seleccionado{'s' if cantidad != 1 else ''}",
            descripcion=(
                "Se cambiará el estado de CM a Terminated y se limpiarán los datos de "
                "contrato CM (N Contrato 3PC, fechas, tipo y pago) de los vehículos seleccionados."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Confirmar baja', 'clase': 'danger', 'rol': 'accept'},
            ],
        )

    @classmethod
    def vins_faltantes_en_correos(cls, parent, vins):
        """Aviso cuando uno o mas VIN seleccionados en Gestionar CM no
        estan en Correo.xlsx (desactualizado respecto a Comercial, ver
        mail_sync_service.cruzar_correos_maestro): no abre MailDialog
        preseleccionado; ofrece abrir el Gestor de Correos normal para que
        el usuario sincronice manualmente (nunca se dispara sola). Boton
        principal en rol 'accept' == "voy a abrir el Gestor de Correos"."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " VIN sin registro en Correos",
            icon_name="fa5s.exclamation-triangle", icon_color=WARNING, icon_bg_color="#FEF3C7",
            titulo="Faltan VIN en Correos.csv",
            subtitulo=f"{cantidad} {plural} sin registro",
            descripcion=(
                "Estos VIN no están en Correos.csv todavía (la base de correos está "
                "desactualizada respecto a Comercial). Sincroniza primero desde el "
                "Gestor de Correos (Sincronizar BBDD Correos) y vuelve a intentar Enviar Correo."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Abrir Gestor de Correos', 'clase': 'primary', 'rol': 'accept'},
            ],
        )

    @classmethod
    def confirmacion_enviar_operaciones(cls, parent, vins, estado_destino=VALOR_ESTADO_COMERCIAL_BAJA):
        """Diálogo previo a "Enviar a operaciones" (22-09-2026): el cliente
        rechazó la renovación (o cualquier otro motivo de baja detectado en
        Comercial) y la unidad debe pasar a gestión de Operaciones. Mismo
        patrón visual que confirmacion() (baja de CM), acento danger porque
        también es una acción de negocio importante.

        `estado_destino` (23-09-2026): BAJA en todas las sub-pestañas salvo
        "Vigentes", que envía BAJA SOLICITADA (ciclo de baja anticipada, ver
        _on_accion_enviar_operaciones_clicked) -- el texto refleja el estado
        real que va a quedar, no siempre "Baja"."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Enviar a operaciones",
            icon_name="fa5s.bolt", icon_color=DANGER, icon_bg_color="#FEE2E2",
            titulo="Enviar a operaciones",
            subtitulo=f"{cantidad} {plural} seleccionado{'s' if cantidad != 1 else ''}",
            descripcion=(
                f"Se cambiará ESTADO COMERCIAL a \"{estado_destino.title()}\" en los vehículos "
                "seleccionados. Dejarán de aparecer en Renovaciones y quedarán a la espera de que "
                "Operaciones confirme la desconexión."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Enviar a operaciones', 'clase': 'danger', 'rol': 'accept'},
            ],
        )

    @classmethod
    def exito_enviar_operaciones(cls, parent, cantidad):
        """Reemplaza el QMessageBox.information del resultado exitoso de
        "Enviar a operaciones" (ver confirmacion_enviar_operaciones)."""
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Enviado a operaciones",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Enviado a operaciones",
            subtitulo=f"{cantidad} {plural} actualizado{'s' if cantidad != 1 else ''}",
            descripcion="ESTADO COMERCIAL se cambió a \"Baja\" y se guardó correctamente.",
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )

    @classmethod
    def confirmacion_marcar_vencidos(cls, parent, vins):
        """Diálogo previo a "Marcar como Vencido" (sub-pestaña Vencidos,
        23-09-2026): a diferencia de confirmacion_enviar_operaciones, `vins`
        no viene de la selección de la tabla, sino de TODOS los vehículos
        de la bandeja "Vencidos" cuyo ESTADO COMERCIAL todavía no dice
        "Vencido" (ver ComercialModule._on_accion_marcar_vencido_clicked).
        Mismo patrón visual que confirmacion_enviar_operaciones."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Marcar como Vencido",
            icon_name="fa5s.calendar-times", icon_color=DANGER, icon_bg_color="#FEE2E2",
            titulo="Marcar como Vencido",
            subtitulo=f"{cantidad} {plural} desactualizado{'s' if cantidad != 1 else ''}",
            descripcion=(
                "Se cambiará ESTADO COMERCIAL a \"Vencido\" en los vehículos de esta lista "
                "cuyo TÉRMINO CONTRATO ya pasó pero siguen en \"Vigente\" o \"Activación "
                "Pendiente\" (posible error humano al no actualizar el estado). No se "
                "modifican los que ya están en Baja, Baja Solicitada o Revisar: esos estados "
                "reflejan una decisión de negocio ya tomada."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Marcar como Vencido', 'clase': 'danger', 'rol': 'accept'},
            ],
        )

    @classmethod
    def exito_marcar_vencidos(cls, parent, cantidad):
        """Reemplaza el QMessageBox.information del resultado exitoso de
        "Marcar como Vencido" (ver confirmacion_marcar_vencidos)."""
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Vencidos actualizados",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Vencidos actualizados",
            subtitulo=f"{cantidad} {plural} actualizado{'s' if cantidad != 1 else ''}",
            descripcion="ESTADO COMERCIAL se cambió a \"Vencido\" y se guardó correctamente.",
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )

    @classmethod
    def confirmacion_marcar_vigentes(cls, parent, vins):
        """Diálogo previo a "Marcar como Vigente" (sub-pestaña Vigentes,
        24-09-2026, pedido explícito del usuario): `vins` viene de TODOS los
        vehículos de la bandeja "Vigentes" con ESTADO COMERCIAL =
        "Activación Pendiente" Y ESTADO DE ACTIVACIÓN ACTUAL = "Conectado"
        (ver ComercialModule._on_accion_marcar_vigente_clicked) -- unidades
        que Servicios Conectados ya muestra conectadas pero cuyo ESTADO COMERCIAL
        quedó desactualizado (error humano). Mismo patrón visual que
        confirmacion_marcar_vencidos."""
        cantidad = len(vins)
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Marcar como Vigente",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Marcar como Vigente",
            subtitulo=f"{cantidad} {plural} desactualizado{'s' if cantidad != 1 else ''}",
            descripcion=(
                "Se cambiará ESTADO COMERCIAL a \"Vigente\" en los vehículos de esta lista "
                "que ya figuran \"Conectado\" pero siguen en \"Activación Pendiente\" "
                "(posible error humano al no actualizar el estado)."
            ),
            items=vins,
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Marcar como Vigente', 'clase': 'primary', 'rol': 'accept'},
            ],
        )

    @classmethod
    def exito_marcar_vigentes(cls, parent, cantidad):
        """Reemplaza el QMessageBox.information del resultado exitoso de
        "Marcar como Vigente" (ver confirmacion_marcar_vigentes)."""
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Vigentes actualizados",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Vigentes actualizados",
            subtitulo=f"{cantidad} {plural} actualizado{'s' if cantidad != 1 else ''}",
            descripcion="ESTADO COMERCIAL se cambió a \"Vigente\" y se guardó correctamente.",
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )

    @classmethod
    def exito(cls, parent, cantidad):
        """Reemplaza el QMessageBox.information del resultado exitoso."""
        plural = "vehículo" if cantidad == 1 else "vehículos"
        return cls(
            parent, " Baja confirmada",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo="Baja confirmada",
            subtitulo=f"{cantidad} {plural} actualizado{'s' if cantidad != 1 else ''}",
            descripcion="La baja del CM se confirmó y guardó correctamente.",
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )


# =========================================================
# CONTENEDOR DE PESTAÑAS COMERCIAL
# =========================================================
class ComercialModule(QWidget):
    """Contenedor de pestañas para el módulo Comercial: prepara el espacio
    para la futura interfaz ("Nueva interfaz") sin tocar en nada la
    implementación actual, que queda intacta en _ComercialModuleLegacy bajo
    la pestaña "Interfaz antigua (actual)".

    MainWindow, los tests y cualquier otro código que siga instanciando
    ComercialModule() y usando sus atributos/métodos directamente (table,
    model, load_data, refresh_if_dirty, pending_changes, confirm_save, etc.)
    debe seguir funcionando sin cambios: los accesos que no pertenecen a
    este contenedor se reenvían transparentemente a self.legacy vía
    __getattr__/__setattr__, en vez de duplicar la lógica o crear una
    segunda instancia completa del módulo.
    """

    # Columnas de la bandeja de la Nueva interfaz, configuradas por sub-pestaña
    # (config aprobada con el usuario: máx. 6 columnas, informativas para esa
    # vista puntual — VIN queda fuera de las 4 vistas a propósito, pero sigue
    # disponible en self.legacy.df_base para el buscador global). No un
    # dataset ni una carga aparte de self.legacy.df_base. Se dejan con el
    # mismo nombre que trae df_base (mayúsculas) porque PandasTableModel
    # colorea celdas como "ESTADO COMERCIAL" comparando ese nombre exacto de
    # columna. "DÍAS RESTANTES" es la única columna calculada (ver
    # _refresh_new_ui_data): no viene de df_base, se agrega en memoria a
    # partir de comercial_services.clasificar_vigencia_contrato().
    # "Gestionar CM" (antes "Revisión CM") no sale de
    # df_base/PruebasFM como las otras: sale de CasosBajaCM.csv (ver
    # _construir_df_revision_cm). Se usan los nombres de columna reales de
    # cm_bajas_service.CASOS_BAJA_CM_COLUMNS (p.ej. "ESTADO_CASO", no
    # "ESTADO CASO") para no inventar un alias. "MOTIVO" es la única columna
    # calculada de esta sub-pestaña: traduce ORIGEN_CASO
    # (AUSENCIA_3PC/ESTADO_EXPIRED, valores técnicos) a texto amigable
    # ("Ausente de 3PC"/"Contrato expirado") vía
    # cm_bajas_service.ORIGEN_CASO_MOTIVO_MAP -- ORIGEN_CASO en sí no se
    # muestra como columna aparte para no duplicar la misma información.
    # Orden de sub-pestañas (28-09-2026, a pedido explícito): Por gestionar,
    # Renovaciones, Gestionar Bajas (antes "Vencidos"), Vigentes, Ofrecer y
    # reactivar (antes "Gestionar Bajas"), Gestionar CM. Ver los .addTab(...)
    # en _build_new_ui_tab para el orden visual real.
    # EJECUTIVO (0/1/2), ETAPA GESTIÓN (0) y OBSERVACIONES (2) se sacaron de
    # estas listas a pedido del usuario (14-09-2026): quedan ocultas solo en
    # esta bandeja visual -- siguen existiendo en df_base/self.legacy.df_base
    # y en cualquier lógica que las use (filtros de negocio, pending_changes,
    # etc.), que trabajan sobre df_base ANTES de este recorte a columnas
    # visibles (ver _refresh_new_ui_data).
    NEW_UI_SUBTAB_COLUMNS = {
        2: ["RAZÓN SOCIAL", "CHASIS", "FORMA DE CONTRATO", "ESTADO COMERCIAL"],
        # "Renovar clientes": fusión (a pedido explícito) de Renovaciones, Gestionar
        # Bajas (vencidos) y Vigentes; columnas provisorias a redefinir.
        0: ["RAZÓN SOCIAL", "CHASIS", "FORMA DE CONTRATO", "TÉRMINO CONTRATO", "ESTADO COMERCIAL", "ESTADO DE ACTIVACIÓN ACTUAL"],
        1: ["RAZÓN SOCIAL", "CHASIS", "ESTADO DE ACTIVACIÓN ACTUAL", "FECHA DE BAJA"],
        3: ["RAZÓN SOCIAL", "CHASIS", "FECHA TERMINO CM", "ESTADO DEL CM", "PAGO CM", "MOTIVO"],
    }

    # Índice de la sub-pestaña "Gestionar Bajas" (antes "Vencidos") dentro de
    # new_ui_subtabs -- la única, junto con "Gestionar CM", con un panel de
    # acciones rápidas propio además del común (ver
    # _toggle_acciones_rapidas_panel).
    _NEW_UI_SUBTAB_RENOVAR_CLIENTES = 0

    # Índice de la sub-pestaña "Gestionar CM" (antes "Revisión CM") dentro de
    # new_ui_subtabs. Vive aparte (no en _NEW_UI_SUBTAB_FILTERS) porque su
    # fuente de datos es CasosBajaCM.csv, no df_base -- no encaja en el
    # contrato "filtro(df_base) -> subset de df_base" que usan las otras.
    _NEW_UI_SUBTAB_REVISION_CM = 3

    # Pseudo sub-pestaña mientras un aviso (etapa gestión / inconsistencias)
    # está activo: la bandeja muestra esas unidades de toda la base y solo
    # quedan las acciones rápidas comunes
    _NEW_UI_SUBTAB_AVISOS = -1
    _COLUMNAS_BANDEJA_AVISOS = [
        "RAZÓN SOCIAL", "CHASIS", "ESTADO COMERCIAL", "ETAPA GESTIÓN", "FORMA DE CONTRATO", "TIPO DE FACTURACION",
    ]
    _COLUMNAS_BANDEJA_INCONSISTENCIAS = [
        "RAZÓN SOCIAL", "CHASIS", "ESTADO COMERCIAL", "ESTADO DE ACTIVACIÓN ACTUAL", "FORMA DE CONTRATO", "TIPO DE FACTURACION",
    ]

    # Índices donde "Enviar a operaciones" no corresponde (confirmado con el
    # usuario, 23-09-2026) y queda deshabilitado (ver
    # _actualizar_estado_acciones_rapidas):
    # - "Por gestionar": el camino correcto es Editar Unidad, que ya deriva
    #   la unidad a Operaciones solo vía la matriz de negocio
    #   (ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ). Usar el botón aquí
    #   marcaría por error ESTADO COMERCIAL = Baja sobre una unidad que en
    #   realidad está entrando en activación, no dándose de baja.
    # - "Gestionar CM": ya tiene su propia acción real ("Confirmar baja",
    #   ver _on_accion_cm_confirmar_baja_clicked); no corresponde además
    #   marcar ESTADO COMERCIAL = Baja con este botón.
    _NEW_UI_SUBTAB_POR_GESTIONAR = 2

    # Columna por la que se agrupa cada sub-pestaña: "Por gestionar" por
    # RAZÓN SOCIAL, las demás por FLOTA VC. Al elegir un grupo la bandeja
    # lista sus unidades con las columnas de NEW_UI_SUBTAB_COLUMNS.
    _NEW_UI_SUBTAB_NOMBRES = ("Renovar contratos", "Recuperar clientes", "Nuevas oportunidades", "Oportunidades CM")
    _NEW_UI_SUBTABS_AGRUPADAS_POR_RAZON_SOCIAL = {_NEW_UI_SUBTAB_POR_GESTIONAR}
    _NEW_UI_VALOR_SIN_GRUPO = "(Sin dato)"
    _NEW_UI_COL_UNIDADES = "UNIDADES"
    _NEW_UI_ANCHOS_VISTA_GRUPOS = {'FLOTA VC': 300, 'RAZÓN SOCIAL': 380}

    # Índice de "Vigentes": única sub-pestaña donde "Enviar a operaciones"
    # representa una baja ANTICIPADA (siniestro u otro problema, unidad
    # todavía Conectada y con contrato vigente) en vez de una baja por
    # vencimiento/rechazo de renovación -- ver
    # _on_accion_enviar_operaciones_clicked, que por eso fija BAJA SOLICITADA
    # en vez de BAJA directo solo para este caso.
    
    # Índice de "Ofrecer y reactivar" (antes "Gestionar Bajas") -- ver
    # _on_accion_editar_unidad_clicked, que activa el mismo modo de edición
    # restringida que "Por gestionar" (caso "cliente interesado en volver").
    _NEW_UI_SUBTAB_OFRECER_REACTIVAR = 1

    # Índice de "Renovaciones" -- único uso: calcular_kpis_renovaciones/
    # obtener_masks_kpi_renovaciones necesitan además self.legacy.
    # data_manager.get_contactos_df() (para la tarjeta "Sin contactos"), a
    # diferencia del resto de sub-pestañas (ver _refresh_new_ui_data).
    
    # Filtro de negocio real por cada sub-pestaña de new_ui_subtabs (mismo
    # orden en que se agregan en _build_new_ui_tab). "Ofrecer y reactivar"
    # (antes "Bajas"/"Gestionar Bajas") aqui es exclusivamente ESTADO
    # COMERCIAL = BAJA -- Bajas CM es un proceso aparte y NO debe mezclarse
    # en esta pestaña (ver auditoria).
    _NEW_UI_SUBTAB_FILTERS = {
        2: comercial_services.filtrar_por_gestionar,   # "Nuevas oportunidades"
        0: comercial_services.filtrar_renovar_clientes, # "Renovar clientes"
        1: comercial_services.filtrar_gestionar_bajas, # "Recuperar clientes" (NO Bajas CM)
    }

    # Función que calcula los KPI de cada sub-pestaña (25-09-2026, a pedido
    # explícito: antes las 6 sub-pestañas mostraban siempre las mismas 4
    # tarjetas de calcular_kpis_vigencia(), sin relación con la regla de
    # negocio real de cada una -- ver comercial_services.py, sección "KPI
    # POR SUB-PESTAÑA"). Recibe la bandeja ya filtrada (df_bandeja en
    # _refresh_new_ui_data) y devuelve un dict {clave: valor} que debe
    # calzar con las claves de _NEW_UI_KPI_SPECS para ese mismo índice.
    _NEW_UI_KPI_FUNCS = {
        2: comercial_services.calcular_kpis_por_gestionar,
        0: comercial_services.calcular_kpis_renovar_clientes,
        1: comercial_services.calcular_kpis_gestionar_bajas,
        3: comercial_services.calcular_kpis_gestionar_cm,
    }

    # Contenido de las 4 tarjetas KPI por sub-pestaña: (clave, título,
    # icono, color de fondo del icono, color de texto, tooltip, subtítulo
    # opcional). Las claves deben calzar exactamente con las que devuelve
    # la función correspondiente en _NEW_UI_KPI_FUNCS -- ver
    # _aplicar_kpi_spec_actual. Las tarjetas cuya clave aparece en
    # _NEW_UI_KPI_FILTRABLE_KEYS (28-09-2026, a pedido explícito) son
    # clicables y filtran la tabla -- ver _on_new_ui_kpi_card_clicked.
    _NEW_UI_KPI_SPECS = {
        2: [  # "Nuevas oportunidades" (antes "Por gestionar")
            ("total", "UNIDADES POTENCIALES", "fa5s.tasks", "#D1FAE5", SUCCESS,
             "Unidades con ESTADO DE ACTIVACIÓN ACTUAL = No aplica.", "unidades sin Servicios Conectados"),
            ("clientes_totales", "CLIENTES TOTALES", "fa5s.building", "#DBEAFE", PRIMARY,
             "Número de RAZÓN SOCIAL distintas dentro de esta bandeja.", "cartera de oportunidades"),
            ("contactados", "CLIENTES CONTACTADOS", "fa5s.envelope", "#FEF3C7", WARNING,
             "Clientes con algún correo registrado en Historial_Envios_VC.csv en los últimos 14 días."),
            ("sin_gestionar", "CLIENTES SIN GESTIONAR", "fa5s.user-clock", "#FEE2E2", DANGER,
             "Clientes sin ningún correo registrado en los últimos 14 días (incluye los que no tienen correo cargado)."),
        ],
        0: [  # "Renovar contratos"
            ("total", "TOTAL DE FLOTA", "fa5s.sync-alt", "#DBEAFE", "#64748B",
             "Unión de Renovaciones, Vencidos y Vigentes.", "unidades en cartera"),
            ("vencidas", "UNIDADES VENCIDAS", "fa5s.calendar-times", "#FEE2E2", DANGER,
             "ESTADO COMERCIAL = Vencido o TÉRMINO CONTRATO ya vencido."),
            ("por_vencer", "VENCEN EN 30 DÍAS", "fa5s.exclamation-triangle", "#FEF3C7", WARNING,
             "Unidades vigentes y conectadas cuyo TÉRMINO CONTRATO vence dentro de los próximos 30 días."),
            ("vigentes", "VIGENTES", "fa5s.check-circle", "#D1FAE5", SUCCESS,
             "Unidades Vigente o Activación Pendiente con contrato al día."),
        ],
        1: [  # "Recuperar clientes" (antes "Gestionar Bajas")
            ("total", "UNIDADES POTENCIALES", "fa5s.user-slash", "#D1FAE5", SUCCESS,
             "Unidades con ESTADO COMERCIAL = Baja.", "unidades dadas de baja"),
            ("clientes_totales", "CLIENTES TOTALES", "fa5s.building", "#DBEAFE", PRIMARY,
             "Número de RAZÓN SOCIAL distintas dentro de esta bandeja.", "cartera de oportunidades"),
            ("contactados", "CLIENTES CONTACTADOS", "fa5s.envelope", "#FEF3C7", WARNING,
             "Clientes con algún correo registrado en Historial_Envios_VC.csv en los últimos 14 días."),
            ("sin_gestionar", "CLIENTES SIN GESTIONAR", "fa5s.user-clock", "#FEE2E2", DANGER,
             "Clientes sin ningún correo registrado en los últimos 14 días (incluye los que no tienen correo cargado)."),
        ],
        3: [  # "Oportunidades CM" (antes "Gestionar CM")
            ("clientes_afectados", "CLIENTES AFECTADOS", "fa5s.building", "#E2E8F0", "#64748B",
             "Razones sociales distintas con casos PENDIENTE en CasosBajaCM.csv.", "con CM sin cobertura"),
            ("total", "UNIDADES CM", "fa5s.clipboard-list", "#E2E8F0", "#64748B",
             "Casos PENDIENTE en CasosBajaCM.csv.", "sin cobertura ni pago de CM"),
            ("contactados", "CLIENTES CONTACTADOS", "fa5s.envelope", "#FEF3C7", WARNING,
             "Clientes con algún correo registrado en Historial_Envios_VC.csv en los últimos 14 días."),
            ("sin_gestionar", "CLIENTES SIN GESTIONAR", "fa5s.user-clock", "#FEE2E2", DANGER,
             "Clientes sin ningún correo registrado en los últimos 14 días (incluye los que no tienen correo cargado)."),
        ],
    }

    # Claves clicables (filtran la tabla) por sub-pestaña -- estático, no se
    # deriva en runtime de las funciones de máscara para no tener que
    # invocarlas solo para conocer sus keys. "Oportunidades CM" (3) se
    # volvió clicable el 05-10-2026, a pedido explícito.
    _NEW_UI_KPI_FILTRABLE_KEYS = {
        0: {'total', 'vencidas', 'por_vencer', 'vigentes'},
        2: {'contactados', 'sin_gestionar', 'total'},
        1: {'contactados', 'sin_gestionar', 'total'},
        3: {'contactados', 'sin_gestionar', 'total'},
    }

    # Función que calcula las máscaras booleanas por fila detrás de cada
    # tarjeta clicable (mismas funciones que ya usa comercial_services.py
    # para las tarjetas -- ver _NEW_UI_KPI_FUNCS). Se aplican sobre
    # df_bandeja en _refresh_new_ui_data al hacer clic en una tarjeta.
    _NEW_UI_KPI_MASK_FUNCS = {
        0: comercial_services.obtener_masks_kpi_renovar_clientes,
        2: comercial_services.obtener_masks_kpi_por_gestionar,
        1: comercial_services.obtener_masks_kpi_gestionar_bajas,
        3: comercial_services.obtener_masks_kpi_gestionar_cm,
    }

    # Orden por defecto (sin clic manual) del bloque de unidades YA vencidas
    # dentro de "DÍAS RESTANTES": el más vencido va primero. Antes existía
    # una excepción para la sub-pestaña "Vencimientos" (eliminada
    # 14-09-2026); sin esa sub-pestaña no queda ninguna excepción.
    _NEW_UI_VENCIDOS_RECIENTES_PRIMERO = set()

    _OWN_ATTRS = {
        'legacy', 'tabs', 'new_ui_tab', 'new_ui_table', 'new_ui_model', 'new_ui_kpi_labels', 'new_ui_subtabs',
        '_new_ui_kpi_cards', '_new_ui_kpi_filtro_por_subtab',
        'new_ui_search_input', 'acciones_rapidas_comunes', 'acciones_rapidas_cm', 'acciones_rapidas_vencidos',
        'acciones_rapidas_vigentes', 'acciones_rapidas_papelera', 'btn_accion_papelera',
        'btn_accion_cm_enviar_correo', 'btn_accion_editar_unidad', 'btn_accion_agregar_contacto',
        'btn_accion_enviar_operaciones', 'btn_accion_cm_confirmar_baja', 'btn_accion_cm_exportar_lista',
        'btn_accion_marcar_vencido', 'btn_accion_renovar', 'btn_accion_ver_general', 'btn_accion_crear_contrato',
        'btn_accion_marcar_vigente', 'acciones_rapidas_inconsistencias', 'btn_accion_arreglar_tipo_fact',
        # "Unidad nueva" (25-09-2026, refactor: alta/edición de unidades
        # centralizada en Comercial, ver _build_unidad_nueva_tab).
        'unidad_nueva_tab', 'unidad_nueva_form', 'btn_unidad_nueva_importar_powerbi',
        'btn_unidad_nueva_restablecer',
        '_unidad_nueva_vin_en_edicion', '_unidad_nueva_datos_originales', '_unidad_nueva_restricciones',
        '_add_unidad_thread', '_importar_powerbi_worker', '_unidad_nueva_form_layout',
        '_unidad_nueva_loading_lbl',
        # Rediseño visual (comercial_estilo.py)
        'selector_pestanas', '_delegado_celdas', 'btn_ampliar_bandeja',
        '_new_ui_kpi_contenedor', '_new_ui_contenido', '_transicion_kpis', '_transicion_contenido',
        '_ficha', 'txt_observaciones', 'btn_guardar_observaciones', '_observaciones_vin',
        '_observaciones_thread', '_vin_a_reseleccionar',
        '_panel_acciones', '_anim_panel_acciones', '_panel_acciones_abierto', 'btn_cerrar_panel_acciones',
        '_barra_bandeja', '_badges_subtabs',
        '_new_ui_grupo_abierto', '_new_ui_en_grupos', '_new_ui_grupos_df', 'btn_volver_grupos', 'lbl_grupo_abierto', 'lbl_titulo_bandeja', 'btn_unidad_nueva_volver',
    }

    def __init__(self):
        super().__init__()
        # Inter para toda la pantalla. setFont no alcanza a los widgets con
        # QSS propio: la familia se declara también en la cascada de estilos
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)

        self.legacy = _ComercialModuleLegacy(tabla_diferida=True)
        # "Editar Unidad" (Vista Completa y Nueva interfaz) ya no abre
        # ComercialAgregarDialog como ventana modal: _handle_editar_unidad
        # (dentro de self.legacy) delega en este callback, que muestra la
        # pestaña "Unidad nueva" en modo edición (ver _iniciar_edicion_unidad).
        self.legacy.on_editar_unidad_solicitado = self._iniciar_edicion_unidad
        # Avisa a ComercialModule cuando una edición se guardó con éxito, para
        # devolver el formulario embebido a un estado coherente de "crear"
        # (25-09-2026, a pedido explícito -- ver _on_edicion_unidad_guardada).
        self.legacy.on_edicion_unidad_guardada = self._on_edicion_unidad_guardada

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        # La barra propia queda oculta: se cambia de pestaña con el control
        # segmentado (estilo_com.SelectorSegmentado), creado más abajo.
        self.tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
        self.tabs.tabBar().hide()

        self.new_ui_kpi_labels = {}
        # Filtro de tarjeta KPI activo por sub-pestaña (28-09-2026, a pedido
        # explícito): dict {índice de sub-pestaña -> key|None}. Se recuerda
        # por sub-pestaña, no se resetea al cambiar de sub-pestaña -- ver
        # _on_new_ui_kpi_card_clicked/_actualizar_seleccion_visual_kpi.
        self._new_ui_kpi_filtro_por_subtab = {}
        # Agrupación de la bandeja: grupo abierto por sub-pestaña (None = se
        # ven los grupos) -- ver _preparar_vista_agrupada.
        self._new_ui_grupo_abierto = {}
        self._new_ui_en_grupos = False
        self._new_ui_grupos_df = None
        self.new_ui_tab = self._build_new_ui_tab()
        self.tabs.addTab(self.new_ui_tab, "Comercial")
        self.unidad_nueva_tab = self._build_unidad_nueva_tab()
        self.tabs.addTab(self.unidad_nueva_tab, "Gestión de unidades")
        # "Vista Completa" ya no se muestra: legacy sigue como motor de datos
        # y guardado de la Nueva interfaz, oculto
        self.legacy.setParent(self)
        self.legacy.hide()
        self.legacy.es_visible = self.isVisible
        self.legacy._avisos_filtran_tabla = False

        # MainWindow._get_active_submodule() detecta "modulos con sub-tabs"
        # mirando hasattr(widget, 'tabs') y, si existe, llama refresh_if_dirty/
        # load_data sobre self.tabs.currentWidget() en vez de sobre el
        # contenedor -- ComercialModule cae en ese caso porque tambien expone
        # su propio self.tabs (Comercial / Vista Completa). new_ui_tab es un
        # QWidget sin datos propios, asi que necesita el mismo contrato que
        # _ComercialModuleLegacy para que MainWindow pueda refrescarlo cuando
        # queda como pestaña activa por defecto.
        self.new_ui_tab.refresh_if_dirty = self._on_new_ui_tab_refresh_if_dirty
        self.tabs.currentChanged.connect(self._actualizar_boton_encabezado)

        # MainWindow._on_global_search() maneja el widget activo mirando
        # hasattr(widget, 'search_input') y, si existe, le setea el texto y
        # llama a widget.filter_table() -- exactamente el mismo contrato que
        # ya cumple _ComercialModuleLegacy. new_ui_tab no tenia ninguno de
        # los dos, asi que la barra de busqueda global quedaba sin efecto en
        # esta pestaña. new_ui_search_input es un QLineEdit oculto (mismo
        # patron que self.search_input en _ComercialModuleLegacy): solo
        # guarda el texto, _refresh_new_ui_data() lo lee y arma la mascara de
        # busqueda con comercial_services.construir_mascara_busqueda() sobre
        # los datos completos (VIN incluido) antes de recortar a las columnas
        # visibles de la sub-pestaña activa.
        self.new_ui_search_input = QLineEdit()
        self.new_ui_search_input.hide()
        self.new_ui_tab.search_input = self.new_ui_search_input
        self.new_ui_tab.filter_table = self._refresh_new_ui_data

        # "Comercial" (Nueva interfaz) queda activa por defecto; "Vista
        # Completa" sigue disponible para la funcionalidad completa de edicion.
        self.tabs.setCurrentIndex(0)
        self.tabs.currentChanged.connect(self._on_internal_tab_changed)

        # El selector ya no se muestra: se llega al formulario con los botones
        # "Editar unidad"/"Crear unidad" de la bandeja (ver _build_new_ui_tab).
        self.selector_pestanas = estilo_com.SelectorSegmentado(self.tabs)
        self.selector_pestanas.setParent(self)
        self.selector_pestanas.hide()
        layout.addWidget(self.tabs)

        # "Agregar contacto" pinta su botón azul/rojo según si el CDB del
        # VIN seleccionado ya tiene contacto en contactos.xlsx (ver
        # _actualizar_estado_acciones_rapidas). Tras agregar uno nuevo se
        # recarga contactos.xlsx con data_manager.load_contactos_async()
        # (mismo mecanismo que general.py), que al terminar emite
        # contactos_ready -- sin este connect, el botón seguiría rojo
        # después de agregar el primer contacto de una empresa hasta el
        # próximo cambio de selección.
        self.legacy.data_manager.contactos_ready.connect(self._actualizar_estado_acciones_rapidas)

        # Sin este connect, la bandeja de "Comercial" (Nueva interfaz, incluye
        # "Por gestionar") quedaba desactualizada tras guardar una edición
        # (ej. Editar Unidad) hasta que el usuario cambiaba de módulo y volvía
        # (lo que sí dispara _on_new_ui_tab_refresh_if_dirty). self.legacy ya
        # se conecta a data_ready para refrescar df_base (_on_global_data_ready),
        # y esa conexión se hizo primero (dentro de _ComercialModuleLegacy()
        # más arriba), así que esta se ejecuta después, con df_base ya al día.
        self.legacy.data_manager.data_ready.connect(self._on_data_ready_refrescar_new_ui)
        self.legacy.data_manager.correos_registrados.connect(self._on_correos_registrados)

        self._refresh_new_ui_data()

    def _on_new_ui_tab_refresh_if_dirty(self):
        """Contraparte de _ComercialModuleLegacy.refresh_if_dirty() para
        new_ui_tab (ver comentario en __init__): reenvia a self.legacy,
        que es quien realmente conserva df_base y pending_changes, y luego
        repinta la bandeja de Comercial con lo que haya quedado en memoria."""
        self.legacy.refresh_if_dirty()
        self._refresh_new_ui_data()

    # ---------------------------------------------------------------
    # "Unidad nueva" (25-09-2026): alta y edición de unidades centralizadas
    # en Comercial, en una pestaña principal propia -- ver comentario de
    # clase de ComercialModule. Reutiliza ComercialUnidadFormWidget
    # (comercial_agregar.py), el mismo formulario que antes vivía dentro de
    # ComercialAgregarDialog, ahora embebido en vez de modal. Una única
    # instancia persiste durante toda la vida de ComercialModule y alterna
    # entre modo "crear" (self._unidad_nueva_vin_en_edicion is None) y modo
    # "editar" (guarda el VIN y los datos originales de la unidad en
    # edición, para poder diffear contra lo que el usuario guarde).
    # ---------------------------------------------------------------
    def _build_unidad_nueva_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        # Márgenes/espaciado reducidos (25-09-2026, corrección de diseño: con
        # el formulario embebido -- que ya trae su propio encabezado + fila
        # de periodo/etapa + pestañas -- el margen de 15px/10px que usan las
        # demás pestañas de Comercial le dejaba muy poca altura disponible y
        # los campos terminaban comprimidos/superpuestos, ver también el
        # reordenamiento de secciones en comercial_agregar.py).
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(4)

        self.btn_unidad_nueva_volver = QPushButton(" Volver a la bandeja")
        self.btn_unidad_nueva_volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color=estilo_com.TINTA))
        self.btn_unidad_nueva_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unidad_nueva_volver.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {estilo_com.TINTA}; border: none; padding: 6px 4px; "
            "font-size: 13px; font-weight: 700; } QPushButton:hover { color: #1B2B4E; text-decoration: underline; }")
        self.btn_unidad_nueva_volver.clicked.connect(self._volver_a_bandeja)
        layout.addWidget(self.btn_unidad_nueva_volver, alignment=Qt.AlignmentFlag.AlignLeft)

        # El botón "Importar Excel Power BI" ya no vive en una fila propia
        # arriba del formulario -- se agrega junto a Cancelar/Guardar
        # Registro recién cuando el formulario se construye (ver
        # _asegurar_unidad_nueva_form), a pedido explícito del usuario.

        # ComercialUnidadFormWidget se construye RECIÉN al primer uso real
        # (ver _asegurar_unidad_nueva_form), no acá (25-09-2026, corrección
        # de regresión de rendimiento reportada por el usuario: construirlo
        # siempre al abrir Comercial -- con datos reales, ~1000+ opciones en
        # FLOTA VC y los lookups RUT->Razón Social/CDB de
        # _construir_lookups -- agregaba varios cientos de ms bloqueando el
        # hilo principal EN CADA primera entrada a Comercial, incluso si el
        # usuario nunca visitaba "Unidad nueva"). Solo se guarda el layout
        # donde insertarlo cuando corresponda.
        self._unidad_nueva_form_layout = layout
        self.unidad_nueva_form = None
        self._unidad_nueva_vin_en_edicion = None
        self._unidad_nueva_datos_originales = None
        self._unidad_nueva_restricciones = {}

        # Aviso de carga (25-09-2026, corrección de regresión de UX: sin esto
        # la pestaña se quedaba en blanco, congelada 1-2 segundos, mientras
        # _asegurar_unidad_nueva_form construía el formulario completo en el
        # hilo principal -- ver _on_internal_tab_changed, que ahora difiere
        # esa construcción con QTimer.singleShot(0, ...) para que Qt alcance
        # a pintar este aviso antes de bloquear). Se retira en
        # _asegurar_unidad_nueva_form apenas el formulario real está listo.
        self._unidad_nueva_loading_lbl = QLabel("Cargando formulario...")
        self._unidad_nueva_loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._unidad_nueva_loading_lbl.setStyleSheet(
            "font-size: 14px; color: #64748B; font-weight: bold; padding: 60px;"
        )
        layout.addWidget(self._unidad_nueva_loading_lbl)
        return tab

    def _asegurar_unidad_nueva_form(self):
        """Construye ComercialUnidadFormWidget la primera vez que realmente
        se necesita (clic en la pestaña "Unidad nueva" o en "Editar
        Unidad") -- ver comentario en _build_unidad_nueva_tab. Llamadas
        posteriores son no-op."""
        if self.unidad_nueva_form is not None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self._unidad_nueva_loading_lbl is not None:
                self._unidad_nueva_form_layout.removeWidget(self._unidad_nueva_loading_lbl)
                self._unidad_nueva_loading_lbl.deleteLater()
                self._unidad_nueva_loading_lbl = None

            # getattr con default (25-09-2026, corrección de regresión
            # detectada en test_06_construccion_no_duplica_la_carga_de_datos):
            # ese test parchea _ComercialModuleLegacy.load_data a un no-op
            # para verificar que construir ComercialModule no dispare una
            # segunda carga -- con load_data neutralizado, self.legacy.df_base
            # nunca llega a asignarse (load_data() es quien lo crea).
            # self.legacy.df_base directo funciona en la app real (load_data()
            # real ya corrió dentro de _ComercialModuleLegacy() antes de
            # llegar aquí), pero no debe asumirse en todos los escenarios.
            df_base_inicial = getattr(self.legacy, 'df_base', pd.DataFrame())
            flotas_unicas = sorted({
                v for v in df_base_inicial.get('FLOTA VC', pd.Series(dtype=str)).astype(str).str.strip()
                if v and v != 'nan'
            })
            # dropdown_options: reutiliza self.legacy.dropdown_options (el
            # catálogo de Comercial), NO el que usaba general.py
            # (DROPDOWN_OPTIONS_NUEVO_CLIENTE) -- diff hecha explícitamente
            # (25-09-2026): eran iguales salvo que a este le faltaba "Revisar"
            # en FORMA DE CONTRATO, agregado el 24-09-2026 en comercial.py como
            # corrección de negocio (ver comentario en __init__ de
            # _ComercialModuleLegacy) y nunca replicado en general.py. Con el
            # alta ahora usando el formulario COMPLETO (sin
            # restringir_alta_desde_general), esa opción faltante sí es
            # visible/relevante -- se usa el catálogo correcto en vez de
            # arrastrar el gap. DROPDOWN_OPTIONS_NUEVO_CLIENTE queda eliminado.
            self.unidad_nueva_form = ComercialUnidadFormWidget(
                flotas_unicas, self.legacy.dropdown_options, df_base_inicial, self.unidad_nueva_tab,
            )
            self.unidad_nueva_form.formulario_confirmado.connect(self._on_unidad_nueva_confirmada)
            self.unidad_nueva_form.formulario_cancelado.connect(self._on_unidad_nueva_cancelada)
            self.unidad_nueva_form.nuevo_contrato_solicitado.connect(self._on_nuevo_contrato_solicitado)
            self._unidad_nueva_form_layout.addWidget(self.unidad_nueva_form, 1)

            # Botón "Restablecer" (25-09-2026, a pedido explícito: "un boton
            # que limpie la informacion como si nunca hubieran preicionado
            # el boton de Editar unidad") -- descarta cualquier cambio sin
            # guardar y vuelve a dejar el formulario tal como quedó la
            # primera vez que se entró (misma unidad recién cargada en modo
            # editar, o en blanco en modo crear). Abajo a la izquierda,
            # junto a "Importar Excel Power BI" -- ver agregar_boton_pie.
            self.btn_unidad_nueva_restablecer = QPushButton(" Restablecer")
            self.btn_unidad_nueva_restablecer.setIcon(qta.icon('fa5s.undo', color='#0F1B33'))
            self.btn_unidad_nueva_restablecer.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_unidad_nueva_restablecer.setStyleSheet(
                "QPushButton { background-color: #FFFFFF; color: #0F1B33; border: 1px solid #DCE3EC; "
                "padding: 0 16px; min-height: 40px; border-radius: 8px; font-weight: 600; font-size: 13px; } "
                "QPushButton:hover { background-color: #F1F4F9; } "
                "QPushButton:pressed { background-color: #E8ECF4; }"
            )
            self.btn_unidad_nueva_restablecer.clicked.connect(self._resetear_formulario_unidad_nueva)
            self.unidad_nueva_form.agregar_boton_pie(self.btn_unidad_nueva_restablecer)

            # Botón de importación Power BI (25-09-2026: movido desde
            # General -- mismo iniciar_importacion_power_bi, mismo
            # ComercialAgregarDialog en modo lote, solo cambia desde dónde
            # se dispara; reubicado 25-09-2026 a pedido explícito: abajo a
            # la izquierda junto al botón "Restablecer" -- ver
            # ComercialUnidadFormWidget.agregar_boton_pie -- con letra e
            # ícono blancos en vez de gris oscuro).
            self.btn_unidad_nueva_importar_powerbi = QPushButton(" Importar Excel Power BI")
            self.btn_unidad_nueva_importar_powerbi.setIcon(qta.icon('fa5s.cloud-upload-alt', color='#B7791F'))
            self.btn_unidad_nueva_importar_powerbi.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_unidad_nueva_importar_powerbi.setStyleSheet(
                "QPushButton { background-color: #FFFFFF; color: #0F1B33; border: 1px solid #DCE3EC; "
                "padding: 0 16px; min-height: 40px; border-radius: 8px; font-weight: 600; font-size: 13px; } "
                "QPushButton:hover { background-color: #F1F4F9; } "
                "QPushButton:pressed { background-color: #E8ECF4; }"
            )
            self.btn_unidad_nueva_importar_powerbi.clicked.connect(self._abrir_importar_powerbi)
            self.unidad_nueva_form.agregar_boton_pie(self.btn_unidad_nueva_importar_powerbi)
        finally:
            QApplication.restoreOverrideCursor()

    def _iniciar_edicion_unidad(self, datos_actuales, restringir_activacion=False,
                                 forzar_activacion_pendiente=False, restringir_vigentes=False):
        """Callback de self.legacy.on_editar_unidad_solicitado (ver
        _ComercialModuleLegacy._handle_editar_unidad): reemplaza la apertura
        de ComercialAgregarDialog como ventana modal por mostrar la pestaña
        "Unidad nueva" con el formulario en modo edición, precargado con
        `datos_actuales`. Mismas restricciones que antes recibía el diálogo
        (restringir_activacion/forzar_activacion_pendiente/restringir_vigentes),
        sin cambiar su significado."""
        self._asegurar_unidad_nueva_form()
        self._unidad_nueva_vin_en_edicion = datos_actuales.get('VIN')
        self._unidad_nueva_datos_originales = datos_actuales
        # Se guardan para que "Restablecer" (ver _resetear_formulario_unidad_nueva)
        # pueda recargar exactamente el mismo modo, sin pedirlas de nuevo.
        self._unidad_nueva_restricciones = {
            'restringir_activacion': restringir_activacion,
            'forzar_activacion_pendiente': forzar_activacion_pendiente,
            'restringir_vigentes': restringir_vigentes,
        }
        self.unidad_nueva_form.actualizar_datos_comercial(self.legacy.df_base)
        self.unidad_nueva_form.cargar_para_editar(
            datos_actuales,
            restringir_activacion=restringir_activacion,
            forzar_activacion_pendiente=forzar_activacion_pendiente,
            restringir_vigentes=restringir_vigentes,
        )
        # VIN bloqueado al editar (25-09-2026, a pedido explícito): el VIN
        # identifica la unidad que se está editando, no debe poder
        # cambiarse desde acá -- cargar_para_editar ya lo deja habilitado
        # (ver _habilitar_todos_los_campos), así que se bloquea después.
        self.unidad_nueva_form.inputs['VIN'].setEnabled(False)
        self.tabs.setCurrentWidget(self.unidad_nueva_tab)

    def _on_nuevo_contrato_solicitado(self):
        self._iniciar_nuevo_contrato(self._unidad_nueva_datos_originales)

    def _iniciar_nuevo_contrato(self, datos_unidad):
        """Abre "Unidad nueva" en modo "Nuevo contrato" sobre una unidad cuyo
        contrato actual está cerrado. Al guardar se agrega una fila nueva con
        ID nuevo; el contrato anterior queda intacto como historial."""
        self._asegurar_unidad_nueva_form()
        self._unidad_nueva_vin_en_edicion = None
        self._unidad_nueva_datos_originales = None
        self._unidad_nueva_restricciones = {}
        self._unidad_nueva_nuevo_contrato = datos_unidad
        self.unidad_nueva_form.actualizar_datos_comercial(self.legacy.df_base)
        self.unidad_nueva_form.cargar_para_nuevo_contrato(datos_unidad)
        self.tabs.setCurrentWidget(self.unidad_nueva_tab)

    def _resetear_formulario_unidad_nueva(self):
        """Botón "Restablecer" (ver _asegurar_unidad_nueva_form; aclarado
        25-09-2026: "Cancelar" ya limpia los datos -- "Restablecer" es para
        recuperar el dato original de un VIN buscado). En modo editar,
        vuelve a cargar la misma unidad desde los datos originales con las
        mismas restricciones (incluido el VIN bloqueado), descartando
        cualquier cambio sin guardar; en modo crear no hay dato original que
        recuperar, así que simplemente deja el formulario en blanco."""
        if self._unidad_nueva_datos_originales is not None:
            self._iniciar_edicion_unidad(self._unidad_nueva_datos_originales, **self._unidad_nueva_restricciones)
        elif getattr(self, '_unidad_nueva_nuevo_contrato', None) is not None:
            self._iniciar_nuevo_contrato(self._unidad_nueva_nuevo_contrato)
        else:
            self._entrar_modo_crear_unidad()

    def _entrar_modo_crear_unidad(self):
        """Deja "Unidad nueva" lista para dar de alta la siguiente unidad:
        se llama al cancelar el formulario y después de guardar (alta o
        edición) exitosamente -- nunca cierra la pestaña (a pedido
        explícito), solo la deja en un estado coherente para una nueva
        creación.

        También es el único punto de salida real de una importación Power
        BI (lote completo o cancelado, ver _abrir_importar_powerbi /
        _on_importar_powerbi_finished), así que de paso desbloquea
        "Comercial"/"Vista Completa" si _bloquear_tabs_durante_importacion_powerbi
        las había dejado deshabilitadas -- no-op si ya estaban habilitadas."""
        self._unidad_nueva_vin_en_edicion = None
        self._unidad_nueva_datos_originales = None
        self._unidad_nueva_restricciones = {}
        self._unidad_nueva_nuevo_contrato = None
        self.unidad_nueva_form.actualizar_datos_comercial(self.legacy.df_base)
        self.unidad_nueva_form.resetear_para_crear()
        for widget in (self.new_ui_tab,):
            idx = self.tabs.indexOf(widget)
            self.tabs.setTabEnabled(idx, True)
            self.tabs.setTabToolTip(idx, "")
        self._sincronizar_selector_pestanas()

    def _on_crear_nueva_unidad_clicked(self):
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.unidad_nueva_tab))
        if self._unidad_nueva_vin_en_edicion is not None or getattr(self, '_unidad_nueva_nuevo_contrato', None) is not None:
            self._entrar_modo_crear_unidad()

    def _volver_a_bandeja(self):
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.new_ui_tab))

    def _on_unidad_nueva_cancelada(self):
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _on_edicion_unidad_guardada(self, vin_final, cambios):
        """Callback de self.legacy.on_edicion_unidad_guardada (ver
        _ComercialModuleLegacy._on_editar_unidad_finished): se dispara solo
        tras un guardado exitoso, ya con dm.df_master actualizado y el
        QMessageBox de confirmación ya mostrado por self.legacy."""
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _on_unidad_nueva_confirmada(self, data):
        """Slot de ComercialUnidadFormWidget.formulario_confirmado: `data`
        es el dict que antes devolvía dialog.get_data(). Modo crear ->
        AddRowThread/comercial_services.agregar_fila (mismo flujo que tenía
        general.py._open_add_dialog/_on_add_finished, movido aquí). Modo
        editar -> diff contra self._unidad_nueva_datos_originales y
        self.legacy.guardar_edicion_unidad (mismo SaveExcelThread de
        siempre)."""
        if self._unidad_nueva_vin_en_edicion is None:
            id_nuevo = comercial_services.proximo_id_contrato(self.legacy.data_manager.df_master)
            if id_nuevo:
                data = {**data, 'ID': id_nuevo}
            self.unidad_nueva_form.setEnabled(False)
            mostrar_guardando(self, "Agregando la unidad nueva…")
            self._add_unidad_thread = AddRowThread(self.legacy.writer, data, module_name="Comercial")
            self._add_unidad_thread.finished_signal.connect(self._on_unidad_nueva_creada_finished)
            self._add_unidad_thread.start()
            return

        vin = self._unidad_nueva_vin_en_edicion
        datos_originales = self._unidad_nueva_datos_originales or {}
        cambios = {
            campo: valor for campo, valor in data.items()
            if str(datos_originales.get(campo, '')).strip() != str(valor).strip()
        }
        if not cambios:
            QMessageBox.information(self, "Sin cambios", "No se modificó ningún campo.")
            return
        self.legacy.guardar_edicion_unidad(vin, cambios)

    def _on_unidad_nueva_creada_finished(self, success, new_data):
        self.unidad_nueva_form.setEnabled(True)
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se pudo agregar el registro en SharePoint. Intenta de nuevo.")
            return
        guardado_listo(self, "Unidad agregada")
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.agregar_fila(dm.df_master, new_data)
            dm.data_ready.emit()
        terminar_guardando(self, texto_exito="Unidad agregada")
        n_contrato = f" (N° Contrato {new_data['ID']})" if new_data.get('ID') else ""
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _abrir_importar_powerbi(self):
        # Ya no abre una ventana modal aparte (25-09-2026, corrección a
        # pedido explícito: "me abre una pestaña en vez de rellenar el
        # formulario que ya tengo al frente") -- reutiliza self.unidad_nueva_form,
        # la misma instancia embebida en "Unidad nueva" (ver
        # ComercialUnidadFormWidget.iniciar_lote en comercial_agregar.py).
        # El botón se deshabilita/rehabilita adentro de
        # iniciar_importacion_power_bi según el estado real del lote (no con
        # un try/finally acá: el flujo ahora es asíncrono via señales, no un
        # exec() bloqueante).
        flotas_existentes = (
            self.legacy.df_base['FLOTA VC'].dropna().unique().tolist()
            if 'FLOTA VC' in self.legacy.df_base.columns else []
        )
        iniciar_importacion_power_bi(
            self, self.unidad_nueva_form, self.btn_unidad_nueva_importar_powerbi,
            flotas_existentes, self.legacy.dropdown_options, self.legacy.df_base,
            self.legacy.writer, self._on_importar_powerbi_finished, self._entrar_modo_crear_unidad,
            on_lote_iniciado=self._bloquear_tabs_durante_importacion_powerbi,
        )

    def _bloquear_tabs_durante_importacion_powerbi(self):
        """Bloquea "Comercial" y "Vista Completa" mientras dura una
        importación de Power BI (25-09-2026, a pedido explícito: bug real
        reportado por el usuario -- cambiar a "Comercial" y usar "Editar
        Unidad" a mitad de una importación sobrescribía, sin aviso, la
        unidad que el lote estaba completando, además de dejar pegados en
        pantalla el badge de chasis y el contador de progreso). Con las
        pestañas bloqueadas, la única salida es terminar el lote completo o
        cancelarlo -- ver _entrar_modo_crear_unidad, que las desbloquea."""
        tooltip = "Termina o cancela la importación de Power BI en curso para volver aquí."
        for widget in (self.new_ui_tab,):
            idx = self.tabs.indexOf(widget)
            self.tabs.setTabEnabled(idx, False)
            self.tabs.setTabToolTip(idx, tooltip)
        self._sincronizar_selector_pestanas()

    def _sincronizar_selector_pestanas(self):
        # getattr: _entrar_modo_crear_unidad puede correr antes de crear el selector
        selector = getattr(self, 'selector_pestanas', None)
        if selector is not None:
            selector.sincronizar_estado()

    def _on_importar_powerbi_finished(self, success):
        self.unidad_nueva_form.setEnabled(True)
        self.btn_unidad_nueva_importar_powerbi.setEnabled(True)
        if success:
            n = getattr(self, '_importar_powerbi_cantidad', 0)
            QMessageBox.information(
                self, "Importación completada",
                f"Se agregaron {n} unidad(es) nueva(s). Las encuentras en \"Nuevas oportunidades\"."
            )
            self.legacy.data_manager.load_data_async()
        else:
            QMessageBox.critical(self, "Error", "No se pudo escribir el lote importado en RM_CONTRATOS. No se realizó ningún cambio.")
        self._entrar_modo_crear_unidad()
        if success:
            self.new_ui_subtabs.setCurrentIndex(2)
            self._volver_a_bandeja()

    def _on_internal_tab_changed(self, index):
        """Replica el mismo hook que MainWindow._trigger_load_data aplica al
        navegar entre modulos (ver main_window.py), pero para el cambio de
        pestaña interno Nueva/Antigua: si la pestaña antigua quedo dirty
        mientras estaba oculta, se refresca al volver a mostrarla."""
        widget = self.tabs.widget(index)
        if widget is not self.new_ui_tab:
            self._ocultar_panel_acciones_al_instante()
        if hasattr(widget, 'refresh_if_dirty'):
            QTimer.singleShot(50, widget.refresh_if_dirty)
        elif hasattr(widget, 'load_data'):
            QTimer.singleShot(50, widget.load_data)

        # La Nueva interfaz no tiene carga propia: al volver a ella, solo
        # se repinta con los datos que _ComercialModuleLegacy ya tiene en
        # memoria (self.legacy.df_base), sin volver a pedirle nada a
        # DataManager.
        if widget is self.new_ui_tab:
            self._refresh_new_ui_data()

        # "Unidad nueva": primer clic real en la pestaña -- construye el
        # formulario recién ahora (ver _asegurar_unidad_nueva_form). Se
        # difiere con QTimer.singleShot(0, ...) (25-09-2026, corrección de
        # regresión de UX reportada por el usuario: el cambio de pestaña
        # tardaba 1-2 segundos en verse porque _asegurar_unidad_nueva_form
        # -con datos reales, ~1000+ opciones en FLOTA VC y los lookups
        # RUT->Razón Social/CDB- corre sincrónico DENTRO del propio
        # currentChanged, bloqueando el hilo principal antes de que Qt
        # alcance a pintar la pestaña ya seleccionada) -- mismo patrón que
        # _cargar_vista_general_inicial en main_window.py: se vuelve del
        # todo al event loop primero, así la pestaña ya cambiada y su aviso
        # "Cargando formulario..." (ver _build_unidad_nueva_tab) se pintan
        # de inmediato, y la construcción pesada sigue en la siguiente
        # vuelta del loop en vez de tapar la transición.
        if widget is self.unidad_nueva_tab and self.unidad_nueva_form is None:
            QTimer.singleShot(0, self._construir_unidad_nueva_form_diferido)

    def _construir_unidad_nueva_form_diferido(self):
        """Ver _on_internal_tab_changed: paso 2 (diferido) de la primera
        entrada a "Unidad nueva". No-op si el usuario ya cambió de pestaña
        de nuevo antes de que corriera (self.unidad_nueva_form seguiría
        None, pero _asegurar_unidad_nueva_form igual lo construye -- queda
        listo para la próxima vez que se seleccione la pestaña)."""
        ya_existia = self.unidad_nueva_form is not None
        self._asegurar_unidad_nueva_form()
        if not ya_existia:
            self._entrar_modo_crear_unidad()

    # ---------------------------------------------------------------
    # NUEVA INTERFAZ (en construcción por etapas -- ver conversación con
    # el usuario para el detalle de qué se decidió en cada bloque)
    # ---------------------------------------------------------------
    def boton_encabezado_visible(self):
        return self.tabs.currentWidget() is self.new_ui_tab

    def _actualizar_boton_encabezado(self, *_):
        # Sin padre (antes de que MainWindow lo ubique) no se debe mostrar
        if self.boton_encabezado.parent() is not None:
            self.boton_encabezado.setVisible(self.boton_encabezado_visible())

    def _build_new_ui_tab(self):
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        estilo_btn = (
            f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
            "border-radius: 12px; padding: 0 18px; min-height: 40px; font-size: 14px; font-weight: 700; } "
            "QPushButton:hover { background-color: #F1F4F9; } "
            f"QPushButton:disabled {{ color: #A9B4C6; background-color: #F5F7FA; }}")
        btn_crear = QPushButton(" Crear unidad")
        btn_crear.setIcon(ThemeManager.icon('fa5s.plus', color=estilo_com.TINTA))
        btn_crear.clicked.connect(self._on_crear_nueva_unidad_clicked)
        btn_crear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_crear.setStyleSheet(estilo_btn)
        # El botón vive en el encabezado de página de MainWindow, junto al título
        self.boton_encabezado = btn_crear

        # Contenedor propio: "Ampliar" lo oculta y la transición de
        # sub-pestaña lo anima
        self._new_ui_kpi_contenedor = QWidget()
        fila_kpis = self._build_new_ui_kpi_row()
        fila_kpis.setContentsMargins(0, 4, 0, 0)
        self._new_ui_kpi_contenedor.setLayout(fila_kpis)
        main_layout.addWidget(self._new_ui_kpi_contenedor)

        self.new_ui_subtabs = QTabBar()
        self._badges_subtabs = []
        for i, nombre in enumerate(self._NEW_UI_SUBTAB_NOMBRES):
            self.new_ui_subtabs.addTab(nombre)
            badge = QLabel("0")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(34, 20)
            self.new_ui_subtabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, badge)
            self._badges_subtabs.append(badge)
        self.new_ui_subtabs.currentChanged.connect(self._estilizar_badges_subtabs)
        self._estilizar_badges_subtabs()
        self.new_ui_subtabs.setTabToolTip(
            self._NEW_UI_SUBTAB_OFRECER_REACTIVAR,
            "Clientes que ya no tienen el servicio activo. Se les puede ofrecer contratar de nuevo.",
        )
        self.new_ui_subtabs.setExpanding(False)
        self.new_ui_subtabs.setDrawBase(False)
        self.new_ui_subtabs.setStyleSheet(estilo_com.QSS_SUBPESTANAS + "QTabBar::tab { padding-right: 6px; } "
            "QTabBar::tab:selected { color: #1B2B4E; border-bottom: 3px solid #1B2B4E; }")
        self.new_ui_subtabs.currentChanged.connect(self._on_new_ui_subtab_changed)
        self.new_ui_subtabs.tabBarClicked.connect(self._on_new_ui_subtab_clicked)
        # Contenedor con la línea inferior de ancho completo bajo las sub-pestañas
        contenedor_subtabs = QFrame()
        contenedor_subtabs.setObjectName("contenedorSubpestanasComercial")
        contenedor_subtabs.setStyleSheet(estilo_com.QSS_CONTENEDOR_SUBPESTANAS)
        fila_subtabs = QHBoxLayout(contenedor_subtabs)
        fila_subtabs.setContentsMargins(0, 0, 0, 0)
        fila_subtabs.addWidget(self.new_ui_subtabs)
        fila_subtabs.addStretch()
        main_layout.addWidget(contenedor_subtabs)

        self._new_ui_contenido = QWidget()
        content_row = QHBoxLayout(self._new_ui_contenido)
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(12)
        content_row.addWidget(self._build_new_ui_bandeja())
        main_layout.addWidget(self._new_ui_contenido, stretch=1)

        # Misma transición que al cambiar entre módulos (transiciones.py)
        self._transicion_kpis = TransicionFundidoSubida(tab, self._new_ui_kpi_contenedor, BACKGROUND)
        self._transicion_contenido = TransicionFundidoSubida(tab, self._new_ui_contenido, BACKGROUND)

        # Acciones rápidas: panel flotante fuera del layout (la tabla usa todo
        # el ancho); aparece sobre selector, KPIs y tabla solo con alguna fila
        # seleccionada. Cuelga del módulo para llegar hasta el borde superior
        self._panel_acciones = self._build_new_ui_acciones_rapidas()
        self._panel_acciones.setParent(self)
        estilo_com.crear_sombra_panel(self._panel_acciones)
        self._panel_acciones.hide()
        self._panel_acciones_abierto = False
        self._anim_panel_acciones = QPropertyAnimation(self._panel_acciones, b"pos", self)
        estilo_com.configurar_animacion_panel(self._anim_panel_acciones)
        self._anim_panel_acciones.finished.connect(self._on_anim_panel_acciones_terminada)
        self._anim_panel_acciones.valueChanged.connect(lambda _v: self._ajustar_barra_bajo_panel())
        return tab

    def _geometria_panel_acciones(self, abierto):
        # Mismo borde derecho e inferior que la bandeja; arriba, desde el tope del módulo
        tab = self.new_ui_tab
        margen = 15
        esquina = tab.mapTo(self, QPoint(tab.width(), tab.height()))
        ancho = max(320, min(400, int(tab.width() * 0.3)))
        return estilo_com.geometria_panel_flotante(self, abierto, derecha=esquina.x(), abajo=esquina.y(), ancho=ancho, margen=margen)

    def _ocultar_panel_acciones_al_instante(self):
        if getattr(self, '_panel_acciones', None) is None:
            return
        self._anim_panel_acciones.stop()
        self._panel_acciones_abierto = False
        combo_periodo = getattr(self, 'combo_periodo_interno', None)
        if combo_periodo is not None:
            combo_periodo.set_compacto(False)
        self._panel_acciones.hide()
        self._ajustar_barra_bajo_panel()

    def _mostrar_panel_acciones(self, mostrar):
        panel = getattr(self, '_panel_acciones', None)
        if panel is None:
            return
        mostrar = mostrar and self.tabs.currentWidget() is self.new_ui_tab
        if mostrar == self._panel_acciones_abierto:
            return
        self._panel_acciones_abierto = mostrar
        combo_periodo = getattr(self, 'combo_periodo_interno', None)
        if combo_periodo is not None:
            combo_periodo.set_compacto(mostrar)
        anim = self._anim_panel_acciones
        anim.stop()
        if mostrar:
            estilo_com.montar_panel_sobre_encabezado(self, panel, lambda: self._panel_acciones_abierto)
            if not panel.isVisible():
                panel.setGeometry(self._geometria_panel_acciones(False))
                panel.show()
            panel.raise_()
            estilo_com.fijar_sombra_panel(panel, True)
        anim.setStartValue(panel.pos())
        anim.setEndValue(self._geometria_panel_acciones(mostrar).topLeft())
        anim.start()

    def _on_anim_panel_acciones_terminada(self):
        if not self._panel_acciones_abierto:
            self._panel_acciones.hide()
            estilo_com.fijar_sombra_panel(self._panel_acciones, False)
        self._ajustar_barra_bajo_panel()

    def _ajustar_barra_bajo_panel(self):
        """Corre los botones de la barra de la bandeja hacia el espacio libre
        de la izquierda para que el panel flotante no los tape."""
        barra, panel = self._barra_bandeja, self._panel_acciones
        solape = 0
        if panel.isVisible():
            borde_derecho = barra.mapTo(panel.parentWidget(), QPoint(barra.width(), 0)).x()
            solape = max(0, borde_derecho - panel.x() + 4)
        barra.layout().setContentsMargins(15, 12, 15 + solape, 12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # El panel flotante cuelga del módulo: se reubica al cambiar el tamaño
        panel = self.__dict__.get('_panel_acciones')
        if panel is not None and panel.isVisible():
            self._anim_panel_acciones.stop()
            # El layout aún no reubicó la pestaña en este evento
            QTimer.singleShot(0, self._reubicar_panel_acciones)

    def _reubicar_panel_acciones(self):
        panel = self._panel_acciones
        if not panel.isVisible():
            return
        panel.setGeometry(self._geometria_panel_acciones(self._panel_acciones_abierto))
        if not self._panel_acciones_abierto:
            panel.hide()
        self._ajustar_barra_bajo_panel()

    def _build_new_ui_kpi_row(self):
        """Construye 4 tarjetas "slot" reutilizables (25-09-2026): antes
        cada tarjeta nacía fija con la clave/título de vigencia de
        contrato, igual en las 6 sub-pestañas. Ahora el contenido (título,
        icono, colores, tooltip y qué clave del dict de KPIs muestra cada
        una) se repinta por sub-pestaña en _aplicar_kpi_spec_actual, según
        _NEW_UI_KPI_SPECS -- las tarjetas en sí son el mismo widget durante
        toda la vida del módulo, solo cambia lo que muestran."""
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self._new_ui_kpi_cards = []
        for _ in range(4):
            self._new_ui_kpi_cards.append(self._build_new_ui_kpi_card())
        for slot in self._new_ui_kpi_cards:
            kpi_row.addWidget(slot['card'])
        return kpi_row

    def _build_new_ui_kpi_card(self):
        """Mismo look que los KPI interactivos de la interfaz antigua (ver
        _ComercialModuleLegacy._create_interactive_kpi): QPushButton
        checkable, para que las tarjetas puedan filtrar la tabla al hacer
        clic (28-09-2026, a pedido explícito) -- _aplicar_kpi_spec_actual
        rellena el contenido real de la sub-pestaña activa y decide, por
        tarjeta, si queda clicable o solo informativa (ver
        _NEW_UI_KPI_FILTRABLE_KEYS). Devuelve un dict con las referencias
        que hacen falta para repintarla (card/icon_frame/icon_lbl/
        title_lbl/val_lbl/subtitulo_lbl/key/seleccionable). El clic se
        conecta una sola vez aquí, por posición de slot (0-3): la clave que
        representa cada slot cambia según la sub-pestaña activa, así que
        _on_new_ui_kpi_card_clicked la resuelve en el momento del clic, no
        acá."""
        card = estilo_com.TarjetaKpiComercial()
        card.set_estilo_plano(True)
        card.setFixedHeight(92)
        card.setCheckable(False)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(0)

        icon_frame = QFrame()
        icon_frame.setFixedSize(36, 36)
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)

        icon_lbl = QLabel()
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        title_lbl = QLabel("")
        title_lbl.setWordWrap(True)
        val_lbl = QLabel("0")
        barra = estilo_com.BarraKpi()
        # Pie de la tarjeta: "% del total" + subtítulo del spec o "clic para filtrar"
        subtitulo_lbl = QLabel("")
        subtitulo_lbl.setStyleSheet(estilo_com.QSS_KPI_SUBTITULO)

        pill_lbl = QLabel("")
        pill_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill_lbl.setFixedHeight(20)
        icon_frame.hide()
        barra.hide()

        fila_pie = QHBoxLayout()
        fila_pie.setSpacing(10)
        fila_pie.addWidget(pill_lbl)
        fila_pie.addWidget(subtitulo_lbl, stretch=1)

        layout.addWidget(title_lbl)
        layout.addWidget(val_lbl)
        layout.addStretch()
        layout.addLayout(fila_pie)

        slot_idx = len(self._new_ui_kpi_cards)
        card.clicked.connect(lambda checked=False, i=slot_idx: self._on_new_ui_kpi_card_clicked(i))
        return {
            'card': card, 'icon_frame': icon_frame, 'icon_lbl': icon_lbl,
            'title_lbl': title_lbl, 'val_lbl': val_lbl, 'subtitulo_lbl': subtitulo_lbl,
            'pill_lbl': pill_lbl, 'barra': barra, 'key': None, 'seleccionable': False, 'subtitulo': None, 'color': PRIMARY,
        }

    def _aplicar_kpi_spec_actual(self, active_subtab):
        """Repinta las 4 tarjetas KPI (título, icono, colores, tooltip,
        subtítulo opcional) con el spec de la sub-pestaña activa
        (_NEW_UI_KPI_SPECS) y reconstruye self.new_ui_kpi_labels (clave ->
        QLabel de valor) para que _refresh_new_ui_data pueda seguir
        escribiendo los valores con el mismo `for key, lbl in
        self.new_ui_kpi_labels.items()` de siempre, ahora con las claves
        correctas para esta sub-pestaña. También decide, por tarjeta, si
        queda clicable (ver _NEW_UI_KPI_FILTRABLE_KEYS) -- el estado
        'checked' en sí lo fija _actualizar_seleccion_visual_kpi, llamado
        después de esta función."""
        specs = self._NEW_UI_KPI_SPECS.get(active_subtab, self._NEW_UI_KPI_SPECS[0])
        claves_filtrables = self._NEW_UI_KPI_FILTRABLE_KEYS.get(active_subtab, set())
        self.new_ui_kpi_labels = {}
        for slot, spec in zip(self._new_ui_kpi_cards, specs):
            key, title, icon_name, icon_bg_color, text_color, tooltip = spec[:6]
            subtitulo = spec[6] if len(spec) > 6 else None
            seleccionable = key in claves_filtrables

            slot['key'] = key
            slot['seleccionable'] = seleccionable
            slot['subtitulo'] = subtitulo
            slot['color'] = text_color
            slot['card'].setToolTip(tooltip)
            slot['icon_frame'].setStyleSheet(estilo_com.qss_icono_kpi(icon_bg_color))
            slot['icon_lbl'].setPixmap(ThemeManager.icon_pixmap(icon_name, color=text_color, size=16))
            slot['title_lbl'].setText(self._titulo_kpi_legible(title))
            slot['title_lbl'].setStyleSheet(
                f"color: {estilo_com.APAGADO}; font-size: 12px; font-weight: 500; background: transparent; border: none;")
            slot['val_lbl'].setStyleSheet(
                f"color: {estilo_com.TINTA}; font-size: 24px; font-weight: 800; background: transparent; border: none;")
            slot['subtitulo_lbl'].setStyleSheet(
                f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
            color_pildora = self._COLORES_PILDORA_KPI.get(str(text_color).upper(), text_color)
            color_q = QColor(color_pildora)
            slot['pill_lbl'].setStyleSheet(
                f"color: {color_pildora}; background-color: rgba({color_q.red()},{color_q.green()},{color_q.blue()},0.14); "
                "border-radius: 10px; padding: 0px 8px; font-size: 11px; font-weight: 800; border: none;")

            slot['card'].setCheckable(seleccionable)
            slot['card'].setCursor(Qt.CursorShape.PointingHandCursor if seleccionable else Qt.CursorShape.ArrowCursor)
            slot['card'].configurar(seleccionable, text_color)
            self.new_ui_kpi_labels[key] = slot['val_lbl']

    # Colores de la píldora de % del HTML v2 (verde, rojo, ámbar, azul marino, pizarra)
    _COLORES_PILDORA_KPI = {
        str(SUCCESS).upper(): estilo_com.VERDE,
        str(DANGER).upper(): estilo_com.ROJO,
        str(WARNING).upper(): estilo_com.AMBAR,
        str(PRIMARY).upper(): "#1B2A49",
        "#64748B": estilo_com.PIZARRA,
    }

    # KPIs que no son una parte de las unidades del total (cuentan empresas o
    # suman montos): muestran esta descripción en vez de "% del total".
    _NEW_UI_KPI_SIN_PORCENTAJE = {
        'clientes': "Razones sociales distintas",
        'sin_contactos': "CDB sin contacto registrado",
        'monto_riesgo': "Suma de PAGO CM pendiente",
    }

    @staticmethod
    def _titulo_kpi_legible(titulo):
        texto = titulo.capitalize()
        for a, b in ((" cm", " CM"), ("3pc", "3PC"), ("cdb", "CDB")):
            texto = texto.replace(a, b)
        return texto

    def _actualizar_barras_kpi(self, kpis):
        """Barra de proporción y pie de cada tarjeta KPI (como el HTML de
        referencia): valor / tarjeta "total" de la misma sub-pestaña."""
        def numero(valor):
            try:
                return float(valor)
            except (TypeError, ValueError):
                return None

        total = numero(kpis.get('total'))
        bases = kpis.get('_bases') or {}
        unidad = "casos" if getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM else "unidades"
        for slot in self._new_ui_kpi_cards:
            key = slot.get('key')
            pill = slot['pill_lbl']
            if key in self._NEW_UI_KPI_SIN_PORCENTAJE:
                pill.hide()
                texto = self._NEW_UI_KPI_SIN_PORCENTAJE[key]
            else:
                base = bases.get(key, total)
                valor = 1.0 if key == 'total' else ((numero(kpis.get(key, 0)) or 0.0) / base if base else 0.0)
                pill.setText(f"{round(valor * 100)} %")
                pill.show()
                if slot.get('subtitulo'):
                    texto = slot['subtitulo']
                elif key == 'total':
                    texto = f"{unidad} en cartera"
                elif key in bases:
                    texto = f"de {int(base or 0)} clientes"
                else:
                    texto = f"de {int(total or 0)} {unidad}"
            slot['subtitulo_lbl'].setText(texto)

    def _actualizar_seleccion_visual_kpi(self, active_subtab):
        """Refleja self._new_ui_kpi_filtro_por_subtab en el estado 'checked'
        de las tarjetas clicables de la sub-pestaña activa: sin filtro
        activo, la tarjeta "Total" queda marcada (mismo criterio que
        _apply_kpi_filter en la vista antigua)."""
        filtro_activo = self._new_ui_kpi_filtro_por_subtab.get(active_subtab)
        for slot in self._new_ui_kpi_cards:
            if not slot.get('seleccionable'):
                continue
            marcado = slot['key'] == filtro_activo or (filtro_activo is None and slot['key'] == 'total')
            slot['card'].blockSignals(True)
            slot['card'].setChecked(marcado)
            slot['card'].blockSignals(False)

    def _on_new_ui_kpi_card_clicked(self, slot_idx):
        """Clic en una tarjeta KPI clicable (28-09-2026, a pedido explícito):
        filtra new_ui_table por esa categoría, igual que ya hacían los KPI
        de Vista Completa (ver _ComercialModuleLegacy._apply_kpi_filter).
        Clic repetido sobre la misma tarjeta, o clic en "Total", limpia el
        filtro. El filtro se recuerda por sub-pestaña
        (self._new_ui_kpi_filtro_por_subtab), no se resetea al cambiar de
        sub-pestaña."""
        slot = self._new_ui_kpi_cards[slot_idx]
        key = slot.get('key')
        if not key or not slot.get('seleccionable'):
            return
        subtab = getattr(self, '_new_ui_active_subtab', 0)
        actual = self._new_ui_kpi_filtro_por_subtab.get(subtab)
        self._new_ui_kpi_filtro_por_subtab[subtab] = None if (key == 'total' or actual == key) else key
        self._refresh_new_ui_data()

    def _on_new_ui_header_resized(self, logical_index, old_size, new_size):
        """Reparte el ancho entre las columnas de new_ui_table para que la
        suma total nunca supere el ancho visible del panel (30-09-2026,
        reportado: al ensanchar una columna a mano, las siguientes quedaban
        empujadas fuera de la vista y, al no haber scroll horizontal
        (ScrollBarAlwaysOff en _build_new_ui_bandeja), no había forma de
        volver a verlas).

        Ajuste (30-09-2026, mismo día): la primera versión solo comprimía las
        demás columnas, así que la que se estaba arrastrando podía terminar
        ocupando toda la pantalla y dejar al resto en el mínimo. Ahora
        primero LIMITA la propia columna que se arrastra a un ancho máximo
        (el que deja a todas las demás, incluida la última, al menos en
        NEW_UI_COL_WIDTH_MINIMO) y recién después reparte lo que sobre/falte
        entre las columnas intermedias (ni la redimensionada ni la última:
        esa la sigue ajustando sola setStretchLastSection)."""
        if self.new_ui_table._ajustando_anchos_new_ui:
            return
        header = self.new_ui_table.horizontalHeader()
        ultima = header.count() - 1
        if header.count() < 3 or logical_index == ultima:
            return

        disponible = self.new_ui_table.viewport().width()
        otras = [i for i in range(header.count()) if i not in (logical_index, ultima)]
        if not otras:
            return

        # Limita la columna arrastrada: no puede crecer más allá de lo que
        # deja a las demás (incluida la última) su ancho mínimo.
        max_para_resized = max(
            NEW_UI_COL_WIDTH_MINIMO,
            disponible - (len(otras) + 1) * NEW_UI_COL_WIDTH_MINIMO,
        )
        tamano_final = new_size
        if new_size > max_para_resized:
            tamano_final = max_para_resized
            self.new_ui_table._ajustando_anchos_new_ui = True
            try:
                header.resizeSection(logical_index, tamano_final)
            finally:
                self.new_ui_table._ajustando_anchos_new_ui = False

        espacio_para_otras = disponible - tamano_final - NEW_UI_COL_WIDTH_MINIMO
        espacio_minimo_otras = len(otras) * NEW_UI_COL_WIDTH_MINIMO
        objetivo_otras = max(espacio_para_otras, espacio_minimo_otras)
        total_otras_actual = sum(header.sectionSize(i) for i in otras)

        if total_otras_actual <= objetivo_otras:
            return  # ya calza, nada que comprimir

        self.new_ui_table._ajustando_anchos_new_ui = True
        try:
            acumulado = 0
            for pos, i in enumerate(otras):
                if pos == len(otras) - 1:
                    nuevo = max(NEW_UI_COL_WIDTH_MINIMO, objetivo_otras - acumulado)
                else:
                    proporcion = header.sectionSize(i) / total_otras_actual
                    nuevo = max(NEW_UI_COL_WIDTH_MINIMO, round(objetivo_otras * proporcion))
                header.resizeSection(i, nuevo)
                acumulado += nuevo
        finally:
            self.new_ui_table._ajustando_anchos_new_ui = False

    def _build_new_ui_bandeja(self):
        # Barra de opciones y tabla en tarjetas separadas
        externo = QWidget()
        layout_externo = QVBoxLayout(externo)
        layout_externo.setContentsMargins(0, 0, 0, 0)
        layout_externo.setSpacing(12)
        frame = QFrame()
        frame.setObjectName("bandejaComercial")
        frame.setStyleSheet(estilo_com.qss_tarjeta("bandejaComercial"))
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        # Botones traídos desde la barra de Vista Completa (ya no se muestra)
        contenedor_barra = QFrame()
        contenedor_barra.setObjectName("barraBandejaComercial")
        contenedor_barra.setStyleSheet(
            "QFrame#barraBandejaComercial { background-color: #1B2B4E; border: none; border-radius: 14px; }")
        barra = QHBoxLayout(contenedor_barra)
        barra.setContentsMargins(15, 12, 15, 12)
        barra.setSpacing(8)
        self._barra_bandeja = contenedor_barra
        layout_externo.addWidget(contenedor_barra)
        layout_externo.addWidget(frame, stretch=1)
        lay_origen = self.legacy.controls_frame.layout()
        botones_derecha = (
            self.legacy.btn_export_excel, self.legacy.btn_alerta_etapa,
            self.legacy.btn_revisar_inconsistencias_forma_contrato, self.legacy.btn_reload,
        )
        for btn in (self.legacy.btn_notas_venta_bi,) + botones_derecha:
            lay_origen.removeWidget(btn)
        # La alerta de contradicciones de ETAPA GESTIÓN ya no se muestra en la
        # barra: su lugar lo ocupa "Marcar como Vencido" (14-10-2026, a pedido)
        self.legacy.btn_alerta_etapa.hide()
        self.btn_marcar_vencidos_barra = QPushButton(" 0")
        self.btn_marcar_vencidos_barra.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_marcar_vencidos_barra.setIcon(ThemeManager.icon('fa5s.calendar-times', color=TEXT_SECONDARY))
        self.btn_marcar_vencidos_barra.setMinimumWidth(44)
        self.btn_marcar_vencidos_barra.clicked.connect(self._on_marcar_todos_vencidos_clicked)
        self.btn_arreglar_inconsistencias_barra = QPushButton(" Arreglar (0)")
        self.btn_arreglar_inconsistencias_barra.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_arreglar_inconsistencias_barra.setIcon(ThemeManager.icon('fa5s.magic', color=TEXT_SECONDARY))
        self.btn_arreglar_inconsistencias_barra.clicked.connect(self._on_arreglar_inconsistencias_clicked)
        self.btn_arreglar_inconsistencias_barra.hide()
        self.legacy.btn_notas_venta_bi.setMinimumSize(0, 0)
        self.legacy.btn_notas_venta_bi.setMaximumSize(16777215, 16777215)
        self.legacy.btn_notas_venta_bi.setIcon(ThemeManager.icon('fa5s.chart-bar', color='white'))
        self.legacy.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='white'))
        for btn in (self.legacy.btn_revisar_inconsistencias_forma_contrato, self.legacy.btn_reload):
            estilo_com.aplicar_estilo_boton_barra(btn, 'neutro')

        # "Ampliar": oculta las tarjetas KPI para darle más alto a la tabla
        self.btn_ampliar_bandeja = QPushButton(" Ampliar")
        self.btn_ampliar_bandeja.setCheckable(True)
        self.btn_ampliar_bandeja.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ampliar_bandeja.setIcon(ThemeManager.icon('fa5s.expand', color=TEXT_SECONDARY))
        self.btn_ampliar_bandeja.setToolTip("Ampliar tabla (oculta las tarjetas de resumen)")
        estilo_com.aplicar_estilo_boton_barra(self.btn_ampliar_bandeja, 'neutro')
        self.btn_ampliar_bandeja.toggled.connect(self._on_ampliar_bandeja_toggled)
        estilo_com.sincronizar_boton_kpi(self.btn_ampliar_bandeja)

        self.btn_volver_grupos = QPushButton()
        self.btn_volver_grupos.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_volver_grupos.setIcon(ThemeManager.icon('fa5s.arrow-left', color=TEXT_SECONDARY))
        self.btn_volver_grupos.setToolTip("Volver a la lista de grupos")
        self.btn_volver_grupos.setFixedWidth(44)
        self.btn_volver_grupos.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.18); "
            "border-radius: 10px; min-height: 34px; } QPushButton:hover { background-color: rgba(255,255,255,0.20); }")
        self.btn_volver_grupos.setIcon(ThemeManager.icon('fa5s.arrow-left', color='white'))
        self.btn_volver_grupos.clicked.connect(self._on_volver_a_grupos_clicked)
        self.btn_volver_grupos.hide()

        separador = QFrame()
        separador.setFixedSize(1, 28)
        separador.setStyleSheet("background: rgba(255,255,255,0.22);")
        self.lbl_titulo_bandeja = QLabel()
        self.lbl_titulo_bandeja.setStyleSheet("color: white; font-size: 15px; font-weight: 800; background: transparent;")
        self.lbl_grupo_abierto = QLabel()
        self.lbl_grupo_abierto.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
        bloque_titulo = QWidget()
        lay_titulo = QVBoxLayout(bloque_titulo)
        lay_titulo.setContentsMargins(0, 0, 0, 0)
        lay_titulo.setSpacing(0)
        lay_titulo.addWidget(self.lbl_titulo_bandeja)
        lay_titulo.addWidget(self.lbl_grupo_abierto)

        # Filtro por PERIODO INTERNO: afecta KPIs, contadores y bandeja
        self.combo_periodo_interno = estilo_com.SelectorFiltroPopup("Periodo interno", self._TEXTO_TODOS_PERIODOS)
        self.combo_periodo_interno.cambiado.connect(self._on_periodo_interno_cambiado)
        self._periodo_interno_df = (None, None, None)

        barra.addWidget(self.btn_volver_grupos)
        capsula_bi = QFrame()
        capsula_bi.setStyleSheet("QFrame { background: rgba(255,255,255,0.08); border-radius: 14px; }")
        lay_capsula_bi = QHBoxLayout(capsula_bi)
        lay_capsula_bi.setContentsMargins(5, 5, 5, 5)
        lay_capsula_bi.addWidget(self.legacy.btn_notas_venta_bi)
        estilo_com.preparar_boton_capsula(self.legacy.btn_notas_venta_bi)
        barra.addWidget(capsula_bi)
        barra.addWidget(separador)
        barra.addWidget(bloque_titulo)
        barra.addStretch()
        barra.addWidget(self.combo_periodo_interno)
        capsula = QFrame()
        capsula.setStyleSheet("QFrame { background: rgba(255,255,255,0.08); border-radius: 14px; }")
        lay_capsula = QHBoxLayout(capsula)
        lay_capsula.setContentsMargins(5, 5, 5, 5)
        lay_capsula.setSpacing(4)
        for btn in (self.legacy.btn_export_excel, self.btn_marcar_vencidos_barra,
                    self.btn_arreglar_inconsistencias_barra,
                    self.legacy.btn_revisar_inconsistencias_forma_contrato,
                    self.btn_ampliar_bandeja, self.legacy.btn_reload):
            lay_capsula.addWidget(btn)
            estilo_com.preparar_boton_capsula(btn)
        barra.addWidget(capsula)
        self.legacy.btn_revisar_inconsistencias_forma_contrato.toggled.connect(self._on_aviso_bandeja_toggled)

        # Mismo componente de tabla que usan el resto de las pantallas
        # (AppTableWidget + PandasTableModel), en vez de un QTableWidget
        # aparte: así se hereda el mismo look (sombra, filas alternadas,
        # badges de color por estado) sin duplicar estilos a mano.
        self.new_ui_table = AppTableWidget()
        qss_tabla = estilo_com.QSS_TABLA + (
            "QHeaderView::section { background: #F7F8FC; color: #6B7A90; border-bottom: 1px solid #E3E8F0; }"
            "QTableView { alternate-background-color: #FFFFFF; }"
            "QTableView::item { border-left: none; }")
        self.new_ui_table.setStyleSheet(qss_tabla)
        self.new_ui_table.frozen_view.setStyleSheet(qss_tabla)

        # La barra vertical nace desde el borde superior (junto al encabezado):
        # se baja para que quede alineada con las filas.
        def _bajar_scrollbar():
            h = self.new_ui_table.horizontalHeader().height()
            if self.new_ui_table.property('_alto_scroll') != h:
                self.new_ui_table.setProperty('_alto_scroll', h)
                self.new_ui_table.setStyleSheet(qss_tabla + f"QScrollBar:vertical {{ margin-top: {h}px; }}")
        self.new_ui_table.horizontalHeader().geometriesChanged.connect(_bajar_scrollbar)
        self.new_ui_table.horizontalHeader().sectionResized.connect(lambda *_: _bajar_scrollbar())
        self.new_ui_table.menu_type = "solo_lectura"
        # Sin arrastrar columnas ni "Fijar columna"; clic en el encabezado ordena
        self.new_ui_table.horizontalHeader().setSectionsMovable(False)
        self.new_ui_table.permitir_fijar_columna = False
        # Sin autoajuste de ancho con doble clic (ni en la sección ni en el borde)
        for header in (self.new_ui_table.horizontalHeader(), self.new_ui_table.frozen_view.horizontalHeader()):
            header.sectionDoubleClicked.disconnect()
            header.sectionHandleDoubleClicked.disconnect()
        self.new_ui_table.horizontalHeader().sectionClicked.connect(self._on_new_ui_encabezado_clicado)
        self.new_ui_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # RAZÓN SOCIAL completa sin tener que ensanchar la columna a mano
        # (23-09-2026, a pedido explícito): ajuste de línea + fila más alta
        # (COMERCIAL_NEW_UI_ROW_HEIGHT) en vez del alto/elide estándar de
        # AppTableWidget. ElideNone es necesario porque _setup_style()
        # deja ElideRight por defecto (trunca con "..." en una sola línea),
        # lo que impedía el ajuste de línea aunque wordWrap estuviera activo.
        # Se aplica a la instancia (no a la clase AppTableWidget), así que
        # el resto de la app conserva el alto/elide estándar de 38px.
        self.new_ui_table.setWordWrap(True)
        self.new_ui_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.new_ui_table.verticalHeader().setDefaultSectionSize(COMERCIAL_NEW_UI_ROW_HEIGHT)
        # frozen_view (columna fijada, ver AppTableWidget._setup_frozen_view)
        # es una QTableView aparte con su propio verticalHeader -- sin este
        # ajuste, fijar una columna desalinearía sus filas contra las de la
        # vista principal en cuanto RAZÓN SOCIAL ocupara más de una línea.
        self.new_ui_table.frozen_view.verticalHeader().setDefaultSectionSize(COMERCIAL_NEW_UI_ROW_HEIGHT)
        # Interactive (no Stretch): permite fijar un ancho inicial por columna
        # (ver _aplicar_anchos_columnas_comercial, llamado desde
        # _refresh_new_ui_data) y que el usuario pueda seguir redimensionando
        # a mano -- Stretch bloqueaba el resize manual por completo.
        # setStretchLastSection cubre el espacio restante de la tabla con la
        # última columna en vez de dejarlo en blanco.
        self.new_ui_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.new_ui_table.horizontalHeader().setStretchLastSection(True)
        # Encabezado y celdas centrados + sin scroll lateral (28-09-2026, a
        # pedido explícito), solo en esta tabla (no en AppTableWidget en
        # general, que sigue alineada a la izquierda para el resto de la
        # app). Los anchos por columna (ver _aplicar_anchos_columnas_new_ui,
        # llamado desde _refresh_new_ui_data) se ajustan al texto de cada
        # encabezado -- junto con setStretchLastSection de arriba, el total
        # de columnas cabe en el ancho del panel sin necesitar scroll.
        self.new_ui_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        # Encabezado en varias líneas cuando el texto no entra en el ancho
        # actual de la columna (30-09-2026, a pedido explícito), en vez de
        # elidirse en una sola línea -- ver FilterHeaderView.set_word_wrap_habilitado.
        self.new_ui_table.horizontalHeader().set_word_wrap_habilitado(True)
        estilo_com.aplicar_estilo_encabezado(self.new_ui_table.horizontalHeader())
        self.new_ui_table.horizontalHeader().set_estilo_encabezado(
            "#F7F8FC", "#F7F8FC", "#6B7A90", "#E3E8F0",
            separador=None, grosor_linea=1, alto_minimo=44, espaciado_letras=0.8,
            iconos_orden=True, radio_superior=13, texto_negrita_fuerte=True,
        )
        self.new_ui_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Sin scroll horizontal (arriba), si el usuario ensancha una columna a
        # mano el resto puede quedar empujado fuera del panel visible, sin
        # forma de llegar a verlas (reportado 30-09-2026). Se comprimen las
        # demás columnas para que la suma siga calzando en el ancho visible
        # -- ver _on_new_ui_header_resized. El flag vive en la tabla (no en
        # self) porque _aplicar_anchos_columnas_new_ui también lo usa y solo
        # recibe la tabla, no el módulo.
        self.new_ui_table._ajustando_anchos_new_ui = False
        self.new_ui_table.horizontalHeader().sectionResized.connect(self._on_new_ui_header_resized)
        # Selección por fila completa: la bandeja es de solo lectura, y
        # "Revisión CM" necesita saber si hay una fila seleccionada para
        # habilitar/deshabilitar sus acciones rápidas (ver
        # _actualizar_estado_acciones_rapidas).
        self.new_ui_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # El estado de orden ("Ordenar A -> Z" del menú de encabezado) vive en
        # la propia AppTableWidget y no se aplica solo: cada pantalla debe
        # reaccionar a sort_changed y llamar a table.apply_sort() antes de
        # set_data() (mismo contrato que _ComercialModuleLegacy.filter_table()
        # con self.table). Sin esta conexión, elegir un orden no hacía nada.
        self.new_ui_table.sort_changed.connect(self._refresh_new_ui_data)

        # Texto centrado (ver arriba): PandasTableModel usa alineación
        # izquierda por defecto para el resto de la app, así que se pasa
        # explícita solo aquí.
        self.new_ui_model = PandasTableModel(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.new_ui_model.destacar_columnas_cliente()
        self.new_ui_table.set_model_and_delegate(self.new_ui_model)
        self._delegado_celdas = estilo_com.DelegadoCeldasComercial([self.new_ui_table, self.new_ui_table.frozen_view])
        self.new_ui_table.setItemDelegate(self._delegado_celdas)
        self.new_ui_table.frozen_view.setItemDelegate(self._delegado_celdas)
        # COMERCIAL_NEW_UI_ROW_HEIGHT pasa a ser el alto mínimo: si el texto necesita más de 2 líneas, la fila crece.
        self.new_ui_table.set_columnas_ajuste_texto(COMERCIAL_COLUMNAS_AJUSTE_TEXTO)
        self.new_ui_table.selectionModel().selectionChanged.connect(self._actualizar_estado_acciones_rapidas)
        self.new_ui_table.clicked.connect(self._on_new_ui_fila_clicada)
        # VIN no se muestra en ninguna de las 4 sub-pestañas (NEW_UI_SUBTAB_
        # COLUMNS), así que "Copiar VIN" del menú contextual (AppTableWidget.
        # _get_vin_for_row) necesita este resolver para no mostrar
        # "Desconocido" -- misma fuente y mismo criterio de orden que
        # _obtener_vins_seleccionados.
        self.new_ui_table.set_vin_resolver(self._resolver_vin_por_fila_new_ui)
        layout.addWidget(self.new_ui_table)

        # Solo icono (el texto lo reescriben otros flujos: se ignora)
        for btn, tip in ((self.legacy.btn_notas_venta_bi, "Abrir Notas de Venta en Power BI"),
                         (self.legacy.btn_export_excel, "Exportar a Excel"),
                         (self.legacy.btn_revisar_inconsistencias_forma_contrato, None),
                         (self.legacy.btn_reload, "Recargar"), (self.btn_ampliar_bandeja, None)):
            if tip:
                btn.setToolTip(tip)
            btn.setText("")
            btn.setFixedWidth(44)
            btn.setText = lambda *_a: None
        self._actualizar_boton_marcar_vencidos_barra()

        return externo

    def showEvent(self, event):
        super().showEvent(event)
        estilo_com.sincronizar_boton_kpi(getattr(self, 'btn_ampliar_bandeja', None))

    def _on_ampliar_bandeja_toggled(self, ampliada):
        estilo_com.guardar_kpi_ocultos(ampliada)
        self._new_ui_kpi_contenedor.setVisible(not ampliada)
        self.btn_ampliar_bandeja.setText(" Reducir" if ampliada else " Ampliar")
        self.btn_ampliar_bandeja.setIcon(ThemeManager.icon('fa5s.compress' if ampliada else 'fa5s.expand', color=TEXT_SECONDARY))
        self.btn_ampliar_bandeja.setToolTip(
            "Volver a mostrar las tarjetas de resumen" if ampliada else "Ampliar tabla (oculta las tarjetas de resumen)"
        )

    def _on_new_ui_encabezado_clicado(self, logical_index):
        """Clic en un encabezado: ordena por esa columna A→Z; un segundo clic
        en la misma invierte el orden (mismo estado que "Ordenar A → Z" del
        menú de clic derecho)."""
        col_name = self.new_ui_model.headerData(logical_index, Qt.Orientation.Horizontal)
        if not col_name:
            return
        tabla = self.new_ui_table
        if tabla._sort_column == col_name and tabla._sort_order == Qt.SortOrder.AscendingOrder:
            tabla._set_sort(col_name, Qt.SortOrder.DescendingOrder)
        else:
            tabla._set_sort(col_name, Qt.SortOrder.AscendingOrder)

    @staticmethod
    def _titulo_seccion(texto):
        lbl = QLabel(texto)
        fuente = lbl.font()
        fuente.setCapitalization(QFont.Capitalization.AllUppercase)
        lbl.setFont(fuente)
        lbl.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        return lbl

    def _build_new_ui_acciones_rapidas(self):
        frame = QFrame()
        frame.setObjectName("accionesRapidasComercial")
        frame.setStyleSheet(estilo_com.QSS_PANEL_FLOTANTE)
        marco = QVBoxLayout(frame)
        marco.setContentsMargins(1, 1, 1, 1)

        # Con ficha + acciones + observaciones el panel puede superar el alto
        # disponible en pantallas bajas: se desplaza en vez de cortarse
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

        self._ficha_contenedor = self._build_new_ui_ficha_unidad()
        layout.addWidget(self._ficha_contenedor)
        self._titulo_acciones = self._titulo_seccion("Acciones rápidas")
        layout.addWidget(self._titulo_acciones)

        # Un único panel de acciones comunes a las 4 sub-pestañas (Enviar
        # correo / Editar Unidad / Agregar contacto / Enviar a operaciones,
        # ver _build_new_ui_acciones_rapidas_comunes), más un panel aparte
        # con "Confirmar baja", exclusivo de "Gestionar CM" y que se agrega
        # a continuación del panel común solo en esa sub-pestaña (ver
        # _toggle_acciones_rapidas_panel). Antes existían dos paneles
        # mutuamente excluyentes (uno genérico decorativo y uno propio de
        # CM); se reemplazan aquí por este esquema común + extra.
        self.acciones_rapidas_comunes = self._build_new_ui_acciones_rapidas_comunes()
        self.acciones_rapidas_cm = self._build_new_ui_acciones_rapidas_solo_cm()
        self.acciones_rapidas_vencidos = self._build_new_ui_acciones_rapidas_solo_vencidos()
        self.acciones_rapidas_vigentes = self._build_new_ui_acciones_rapidas_solo_vigentes()
        self.acciones_rapidas_inconsistencias = self._build_new_ui_acciones_rapidas_solo_inconsistencias()
        layout.addWidget(self.acciones_rapidas_comunes)
        layout.addWidget(self.acciones_rapidas_cm)
        layout.addWidget(self.acciones_rapidas_vencidos)
        layout.addWidget(self.acciones_rapidas_vigentes)
        layout.addWidget(self.acciones_rapidas_inconsistencias)
        self.acciones_rapidas_papelera = self._build_new_ui_acciones_rapidas_solo_papelera()
        layout.addWidget(self.acciones_rapidas_papelera)
        self.acciones_rapidas_cm.hide()
        self.acciones_rapidas_vencidos.hide()
        self.acciones_rapidas_vigentes.hide()
        self.acciones_rapidas_inconsistencias.hide()
        self.acciones_rapidas_papelera.hide()
        self._toggle_acciones_rapidas_panel(self.new_ui_subtabs.currentIndex())

        self._renovar_modo_activo = False
        self._renovar_filas = {}
        self.panel_renovar = self._build_new_ui_panel_renovar()
        layout.addWidget(self.panel_renovar)
        self.panel_renovar.hide()

        # Observaciones de la unidad seleccionada (columna OBSERVACIONES)
        layout.addSpacing(6)
        layout.addWidget(self._titulo_seccion("Observaciones"))
        self.txt_observaciones = QTextEdit()
        self.txt_observaciones.setPlaceholderText("Escribe una observación sobre esta unidad…")
        self.txt_observaciones.setAcceptRichText(False)
        self.txt_observaciones.setFixedHeight(88)
        self.txt_observaciones.setStyleSheet(estilo_com.QSS_OBSERVACIONES)
        self.txt_observaciones.textChanged.connect(self._actualizar_boton_guardar_observaciones)
        layout.addWidget(self.txt_observaciones)
        self.btn_guardar_observaciones = QPushButton(" Guardar observación")
        self.btn_guardar_observaciones.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        self.btn_guardar_observaciones.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar_observaciones.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR)
        self.btn_guardar_observaciones.clicked.connect(self._on_guardar_observaciones_clicked)
        layout.addWidget(self.btn_guardar_observaciones)
        self._observaciones_vin = None
        self._cargar_observaciones(None, "")

        layout.addStretch()
        return frame

    def _build_new_ui_ficha_unidad(self):
        """Resumen de la unidad seleccionada arriba de las acciones rápidas:
        iniciales + Razón social + Chasis, y Forma de contrato, Estado
        comercial, Tipo de facturación y Estado de activación actual. Solo
        con exactamente una fila seleccionada (ver _actualizar_ficha_unidad)."""
        contenedor = QWidget()
        layout = QVBoxLayout(contenedor)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(10)

        fila_titulo = QHBoxLayout()
        fila_titulo.setContentsMargins(0, 0, 0, 0)
        titulo_ficha = self._titulo_seccion("Unidad seleccionada")
        fila_titulo.addWidget(titulo_ficha)
        fila_titulo.addStretch()
        self.btn_cerrar_panel_acciones = QPushButton()
        self.btn_cerrar_panel_acciones.setIcon(ThemeManager.icon('fa5s.times', color=estilo_com.APAGADO))
        self.btn_cerrar_panel_acciones.setFixedSize(26, 26)
        self.btn_cerrar_panel_acciones.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cerrar_panel_acciones.setToolTip("Cerrar (quita la selección)")
        self.btn_cerrar_panel_acciones.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        self.btn_cerrar_panel_acciones.clicked.connect(lambda: self.new_ui_table.clearSelection())
        fila_titulo.addWidget(self.btn_cerrar_panel_acciones)
        layout.addLayout(fila_titulo)

        vacio = QLabel("Hay unidades de distintas empresas seleccionadas: elige solo una para ver su detalle.")
        vacio.setWordWrap(True)
        vacio.setStyleSheet(estilo_com.QSS_FICHA_VACIA)
        layout.addWidget(vacio)

        detalle = QWidget()
        detalle_layout = QVBoxLayout(detalle)
        detalle_layout.setContentsMargins(0, 0, 0, 0)
        detalle_layout.setSpacing(8)

        hero = QFrame()
        hero.setObjectName("fichaHeroComercial")
        hero.setStyleSheet(estilo_com.QSS_FICHA_HERO)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(12, 12, 12, 12)
        hero_layout.setSpacing(12)
        avatar = QLabel("--")
        avatar.setFixedSize(46, 46)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(estilo_com.QSS_FICHA_AVATAR)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        nombre = QLabel("")
        nombre.setWordWrap(True)
        nombre.setStyleSheet(estilo_com.QSS_FICHA_NOMBRE)
        nombre.setCursor(Qt.CursorShape.PointingHandCursor)
        nombre.setToolTip("Clic para copiar")
        nombre.mousePressEvent = lambda event, lbl=nombre: self._copiar_texto_ficha(lbl.text())
        textos.addWidget(nombre)
        copiables = {}
        for prefijo, columna in (("Chasis", COL_CHASIS), ("RUT", 'RUT'), ("N° contrato", COL_ID), ("VIN", 'VIN')):
            fila_copiable, lbl_copiable = self._fila_copiable_ficha(prefijo)
            textos.addLayout(fila_copiable)
            copiables[columna] = lbl_copiable
        hero_layout.addWidget(avatar)
        hero_layout.addLayout(textos, stretch=1)
        detalle_layout.addWidget(hero)

        alerta_cdb = QLabel("")
        alerta_cdb.setWordWrap(True)
        alerta_cdb.setStyleSheet(
            f"background-color: {estilo_com.ROJO_SUAVE}; color: {estilo_com.ROJO}; border: 1px solid {estilo_com.ROJO};"
            "border-radius: 10px; padding: 8px 10px; font-size: 12px; font-weight: bold;")
        alerta_cdb.hide()
        detalle_layout.addWidget(alerta_cdb)

        grilla = QGridLayout()
        grilla.setSpacing(6)
        valores = {}
        for i, (columna, titulo) in enumerate((
            (COL_FORMA_CONTRATO, "Forma de contrato"), (COL_ESTADO_COMERCIAL, "Estado comercial"),
            (COL_TIPO_FACTURACION, "Tipo de facturación"), (COL_ESTADO_ACTIVACION, "Estado de activación"),
        )):
            celda, lbl_valor = estilo_com.crear_celda_ficha(titulo)
            grilla.addWidget(celda, i // 2, i % 2)
            valores[columna] = lbl_valor
        detalle_layout.addLayout(grilla)
        layout.addWidget(detalle)

        self._ficha = {
            'vacio': vacio, 'detalle': detalle, 'avatar': avatar,
            'nombre': nombre, 'copiables': copiables, 'valores': valores,
            'titulo': titulo_ficha, 'alerta_cdb': alerta_cdb,
        }
        detalle.hide()
        return contenedor

    def _fila_copiable_ficha(self, prefijo):
        """Fila 'Prefijo valor [icono]' de la ficha; un clic copia el valor."""
        fila = QHBoxLayout()
        fila.setSpacing(4)
        etiqueta = QLabel(prefijo)
        etiqueta.setStyleSheet(estilo_com.QSS_FICHA_CHASIS)
        valor = QLabel("—")
        valor.setStyleSheet(estilo_com.QSS_FICHA_CHASIS + " font-weight: bold;")
        valor.setCursor(Qt.CursorShape.PointingHandCursor)
        valor.setToolTip("Clic para copiar")
        valor.mousePressEvent = lambda event, lbl=valor: self._copiar_texto_ficha(lbl.text())
        icono = QLabel()
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.copy', color=estilo_com.APAGADO, size=11))
        icono.setStyleSheet("background: transparent; border: none;")
        fila.addWidget(etiqueta)
        fila.addWidget(valor)
        fila.addWidget(icono)
        fila.addStretch()
        return fila, valor

    @staticmethod
    def _copiar_texto_ficha(texto):
        if texto and texto not in ("—", "-"):
            QApplication.clipboard().setText(texto)

    def _fila_df_base_por_vin(self, vin):
        df = getattr(self.legacy, 'df_base', None)
        if not vin or df is None or df.empty or 'VIN' not in df.columns:
            return None
        pos = self._posicion_vin_en_df(df, vin)
        return None if pos is None else df.iloc[pos]

    def _posicion_vin_en_df(self, df, vin):
        """Posición de la primera fila de `df` con ese VIN. Usa un índice
        armado una vez por cada df_base (antes se recorrían ~12.000 VIN en
        cada clic); el acierto se verifica y, si falla, se recorre como antes."""
        clave = str(vin).strip().upper()
        cache = self.__dict__.get('_indice_vin_cache')
        if cache is None or cache[0] is not df or cache[1] != len(df):
            indice = {}
            for pos, v in enumerate(df['VIN'].astype(str).str.strip().str.upper().tolist()):
                indice.setdefault(v, pos)
            cache = (df, len(df), indice)
            self.__dict__['_indice_vin_cache'] = cache
        pos = cache[2].get(clave)
        col_vin = df.columns.get_loc('VIN')
        if pos is not None and str(df.iat[pos, col_vin]).strip().upper() == clave:
            return pos
        coincidencias = (df['VIN'].astype(str).str.strip().str.upper() == clave).to_numpy().nonzero()[0]
        return int(coincidencias[0]) if len(coincidencias) else None

    def _actualizar_ficha_unidad(self, vins_seleccion):
        ficha = getattr(self, '_ficha', None)
        if ficha is None:
            return
        filas = [self._fila_df_base_por_vin(v) for v in vins_seleccion]
        if not filas or any(f is None for f in filas):
            filas = []

        def texto_de(fila, columna):
            valor = str(fila.get(columna, '') if fila.get(columna) is not None else '').strip()
            return '-' if valor.upper() in ('', 'NAN', 'NONE') else valor

        # Varias unidades: la ficha muestra la empresa solo si es la misma para todas
        razones = {texto_de(f, COL_RAZON_SOCIAL) for f in filas}
        if len(razones) != 1:
            ficha['detalle'].hide()
            ficha['vacio'].show()
            ficha['titulo'].setText("Unidad seleccionada")
            self._cargar_observaciones(None, "")
            return

        multiple = len(filas) > 1
        fila = filas[0]

        def texto(columna):
            return texto_de(fila, columna)

        def comun(columna):
            valores = {texto_de(f, columna) for f in filas}
            return valores.pop() if len(valores) == 1 else "Varios"

        razon_social = texto(COL_RAZON_SOCIAL)
        ficha['titulo'].setText(f"{len(filas)} unidades seleccionadas" if multiple else "Unidad seleccionada")
        ficha['avatar'].setText(estilo_com.iniciales(razon_social))
        ficha['nombre'].setText(razon_social)
        for columna, lbl in ficha['copiables'].items():
            if multiple and columna in (COL_CHASIS, COL_ID, 'VIN'):
                valor = '-'
            elif columna == 'VIN':
                valor = str(vins_seleccion[0]).strip()
            elif columna == COL_ID:
                valor = comercial_services._normalizar_id_contrato(texto(columna))
            else:
                valor = texto(columna)
            lbl.setText(valor if valor and valor != '-' else "—")
        for columna, lbl in ficha['valores'].items():
            estilo_com.pintar_chip_ficha(lbl, comun(columna) if multiple else texto(columna))

        referencia = self._cdb_referencia_actual()
        malas = [f for f in filas if comercial_services.cdb_discrepante(f.get('CDB'), razon_social, referencia)]
        alerta = ficha['alerta_cdb']
        if malas:
            esperado = referencia.get(razon_social, '')
            if multiple:
                alerta.setText(f"⚠ {len(malas)} de {len(filas)} unidades tienen un CDB comercial distinto al de la empresa ({esperado}). "
                               "Selecciona una y usa «Editar contrato» para corregirlo.")
            else:
                actual = comercial_services.normalizar_cdb(fila.get('CDB')) or "vacío"
                alerta.setText(f"⚠ El CDB comercial de esta unidad ({actual}) no coincide con el de la empresa ({esperado}). "
                               "Usa «Editar contrato» para corregirlo.")
            alerta.show()
        else:
            alerta.hide()
        ficha['vacio'].hide()
        ficha['detalle'].show()

        if multiple:
            self._cargar_observaciones(None, "")
        else:
            observacion = texto('OBSERVACIONES')
            self._cargar_observaciones(vins_seleccion[0], "" if observacion == '-' else observacion)

    def _cargar_observaciones(self, vin, texto):
        """Carga en el cuadro la observación guardada de `vin` (None = sin
        unidad seleccionada: cuadro y botón deshabilitados)."""
        if not hasattr(self, 'txt_observaciones'):
            return
        if vin == self._observaciones_vin and vin is not None:
            return  # misma unidad: no se pisa lo que el usuario está escribiendo
        self._observaciones_vin = vin
        self.txt_observaciones.blockSignals(True)
        self.txt_observaciones.setPlainText(texto)
        self.txt_observaciones.blockSignals(False)
        self.txt_observaciones.setProperty('texto_guardado', texto)
        self.txt_observaciones.setEnabled(vin is not None)
        self._actualizar_boton_guardar_observaciones()

    def _actualizar_boton_guardar_observaciones(self):
        guardado = self.txt_observaciones.property('texto_guardado') or ""
        cambiado = self.txt_observaciones.toPlainText().strip() != str(guardado).strip()
        self.btn_guardar_observaciones.setEnabled(self._observaciones_vin is not None and cambiado)

    def _on_guardar_observaciones_clicked(self):
        """Guarda OBSERVACIONES de la unidad seleccionada con el mismo camino
        que las demás acciones (SaveExcelThread → ExcelWriter.update_cells,
        con backup y log)."""
        vin = self._observaciones_vin
        if not vin:
            return
        texto = self.txt_observaciones.toPlainText().strip()
        valid = comercial_services.agregar_id_a_cambios(
            {vin: {'VIN': vin, 'cambios': {'OBSERVACIONES': texto or '-'}}}, self.legacy.df_base)
        self.btn_guardar_observaciones.setEnabled(False)
        mostrar_guardando(self, "Guardando observación…")
        self._observaciones_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._observaciones_thread.finished_signal.connect(
            lambda success: self._on_guardar_observaciones_finished(success, valid, vin)
        )
        self._observaciones_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._observaciones_thread.start()

    def _on_guardar_observaciones_finished(self, success, valid, vin):
        if not success:
            terminar_guardando(self, exito=False)
            self._actualizar_boton_guardar_observaciones()
            DialogoAccionCm.error(
                self, "No se pudo guardar la observación. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()
        self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
        # Tras repintar la bandeja, vuelve a seleccionar la misma unidad
        self._observaciones_vin = None
        self._vin_a_reseleccionar = vin
        self._refresh_new_ui_data()
        self._reseleccionar_vin_pendiente()
        terminar_guardando(self)

    def _reseleccionar_vin_pendiente(self):
        vin = getattr(self, '_vin_a_reseleccionar', None)
        self._vin_a_reseleccionar = None
        es_revision_cm = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM
        df = getattr(self, '_new_ui_revision_cm_df' if es_revision_cm else '_new_ui_bandeja_actual_df', None)
        if not vin or df is None or df.empty or 'VIN' not in df.columns:
            return
        filas = df.reset_index(drop=True).index[df['VIN'].astype(str).str.strip().str.upper().values == vin]
        if len(filas):
            self.new_ui_table.selectRow(int(filas[0]))

    def _build_new_ui_acciones_rapidas_comunes(self):
        """Acciones comunes a las 4 sub-pestañas de Comercial. "Enviar
        correo" (ver _on_accion_cm_enviar_correo_clicked) abre MailDialog
        con los VIN seleccionados, con la plantilla "Aviso de Vencimiento"
        preseleccionada solo en "Gestionar CM". "Editar Unidad" (ver
        _on_accion_editar_unidad_clicked) reutiliza el mismo
        ComercialAgregarDialog/flujo de guardado de Vista Completa.
        "Agregar contacto" (ver _on_accion_agregar_contacto_clicked) abre
        el mismo ContactosAddDialog que ya usa Clientes y Flotas, con CDB/
        RAZÓN SOCIAL resueltos desde df_base por VIN. "Enviar a
        operaciones" todavía no tiene lógica conectada (fase siguiente).
        Todas se habilitan/deshabilitan según selección (ver
        _actualizar_estado_acciones_rapidas)."""
        widget = QWidget()
        layout = estilo_com.GrillaAcciones(widget)

        self.btn_accion_cm_enviar_correo = self._build_new_ui_accion_button(
            "fa5s.envelope", "Enviar correo", "Contactar al cliente", color=estilo_com.AZUL
        )
        self.btn_accion_editar_unidad = self._build_new_ui_accion_button(
            "fa5s.file-contract", "Editar contrato", "Modificar los datos del contrato", color=estilo_com.VIOLETA
        )
        self.btn_accion_ver_general = self._build_new_ui_accion_button(
            "fa5s.search", "Ver en General", "Consulta la unidad y sus contratos", color=estilo_com.AZUL
        )
        self.btn_accion_crear_contrato = self._build_new_ui_accion_button(
            "fa5s.file-signature", "Crear contrato", "Nuevo contrato con los datos de la unidad y del cliente",
            color=estilo_com.VERDE
        )
        self.btn_accion_agregar_contacto = self._build_new_ui_accion_button(
            "fa5s.user-plus", "Agregar contacto", "Registrar contacto de la empresa", color=estilo_com.VERDE
        )
        self.btn_accion_enviar_operaciones = self._build_new_ui_accion_button(
            "fa5s.bolt", "Enviar a operaciones", "Deriva la unidad a Operaciones", color=estilo_com.AMBAR
        )
        for btn in (
            self.btn_accion_cm_enviar_correo, self.btn_accion_editar_unidad, self.btn_accion_ver_general,
            self.btn_accion_crear_contrato, self.btn_accion_agregar_contacto, self.btn_accion_enviar_operaciones,
        ):
            btn.setEnabled(False)
        self.btn_accion_ver_general.setVisible(False)
        self.btn_accion_crear_contrato.setVisible(False)

        self.btn_accion_cm_enviar_correo.clicked.connect(self._on_accion_cm_enviar_correo_clicked)
        self.btn_accion_editar_unidad.clicked.connect(self._on_accion_editar_unidad_clicked)
        self.btn_accion_ver_general.clicked.connect(self._on_accion_ver_general_clicked)
        self.btn_accion_crear_contrato.clicked.connect(self._on_accion_crear_contrato_clicked)
        self.btn_accion_agregar_contacto.clicked.connect(self._on_accion_agregar_contacto_clicked)
        self.btn_accion_enviar_operaciones.clicked.connect(self._on_accion_enviar_operaciones_clicked)

        layout.agregar(self.btn_accion_cm_enviar_correo)
        layout.agregar(self.btn_accion_editar_unidad)
        layout.agregar(self.btn_accion_ver_general)
        layout.agregar(self.btn_accion_crear_contrato)
        layout.agregar(self.btn_accion_agregar_contacto)
        layout.agregar(self.btn_accion_enviar_operaciones)

        return widget

    def _build_new_ui_acciones_rapidas_solo_cm(self):
        """Acciones exclusivas de "Gestionar CM", agregadas al panel común
        (ver _toggle_acciones_rapidas_panel).

        "Exportar lista" (28-09-2026, a pedido explícito, ver docs/07):
        el equipo nunca da de baja el contrato CM, solo avisa a quien
        administra esos contratos -- guarda la bandeja visible en el
        Escritorio para que el usuario se la envíe manualmente. No
        depende de selección.

        "Confirmar baja" sí modifica datos reales (ver
        _on_accion_cm_confirmar_baja_clicked) y queda restringido a casos
        ORIGEN_CASO = AUSENCIA_3PC (ver _actualizar_estado_acciones_rapidas):
        para ESTADO_EXPIRED el equipo tampoco decide eso, solo avisa -- de
        ahí "Exportar lista"."""
        widget = QWidget()
        layout = estilo_com.GrillaAcciones(widget)

        self.btn_accion_cm_exportar_lista = self._build_new_ui_accion_button(
            "fa5s.file-export", "Exportar lista", "Guardar la bandeja visible en el Escritorio", color=estilo_com.PIZARRA
        )
        self.btn_accion_cm_exportar_lista.clicked.connect(self._on_accion_cm_exportar_lista_clicked)

        self.btn_accion_cm_confirmar_baja = self._build_new_ui_accion_button(
            "fa5s.check-circle", "Confirmar baja", "Cerrar el caso como baja de CM (solo Ausencia de 3PC)", color=estilo_com.ROJO
        )
        self.btn_accion_cm_confirmar_baja.setEnabled(False)
        self.btn_accion_cm_confirmar_baja.clicked.connect(self._on_accion_cm_confirmar_baja_clicked)

        layout.agregar(self.btn_accion_cm_exportar_lista)
        layout.agregar(self.btn_accion_cm_confirmar_baja)

        return widget

    def _build_new_ui_acciones_rapidas_solo_vencidos(self):
        """Acción exclusiva de "Vencidos" (23-09-2026), agregada al panel
        común (ver _toggle_acciones_rapidas_panel). Se habilita con las filas
        seleccionadas cuya fecha de término ya expiró y cuyo ESTADO
        COMERCIAL todavía no dice "Vencido" (ver
        _on_accion_marcar_vencido_clicked/_actualizar_boton_marcar_vencido).
        Modifica datos reales en PruebasFM.xlsx."""
        widget = QWidget()
        layout = estilo_com.GrillaAcciones(widget)

        self.btn_accion_marcar_vencido = self._build_new_ui_accion_button(
            "fa5s.calendar-times", "Marcar como Vencido", "Corrige el estado desactualizado", color=estilo_com.ROJO
        )
        self.btn_accion_marcar_vencido.setEnabled(False)
        self.btn_accion_marcar_vencido.clicked.connect(self._on_accion_marcar_vencido_clicked)

        self.btn_accion_renovar = self._build_new_ui_accion_button(
            "fa5s.redo-alt", "Renovar contrato", "Extiende los meses del contrato", color=estilo_com.VERDE
        )
        self.btn_accion_renovar.setEnabled(False)
        self.btn_accion_renovar.clicked.connect(self._on_accion_renovar_clicked)

        layout.agregar(self.btn_accion_marcar_vencido)
        layout.agregar(self.btn_accion_renovar)

        return widget

    def _build_new_ui_acciones_rapidas_solo_papelera(self):
        """Acción exclusiva de "Nuevas oportunidades": envía a la papelera
        contratos "SIN VC" (unidades que no quisieron o no respondieron al
        servicio). Ver _on_accion_papelera_clicked."""
        widget = QWidget()
        layout = estilo_com.GrillaAcciones(widget)

        self.btn_accion_papelera = self._build_new_ui_accion_button(
            "fa5s.trash-alt", "Enviar a papelera", "Solo contratos SIN VC", color=estilo_com.ROJO
        )
        self.btn_accion_papelera.setEnabled(False)
        self.btn_accion_papelera.clicked.connect(self._on_accion_papelera_clicked)
        layout.agregar(self.btn_accion_papelera)
        return widget

    def _vins_sin_vc_seleccionados(self):
        """VIN de la selección, solo si TODOS son SIN VC (forma de contrato
        Sin Contrato y tipo de facturación Sin Registro); si no, lista vacía."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_POR_GESTIONAR:
            return []
        vins, _ = self._obtener_vins_seleccionados()
        if vins and all(self._es_unidad_sin_contrato_sin_registro(vin) for vin in vins):
            return vins
        return []

    def _actualizar_boton_papelera(self):
        habilitado = bool(self._vins_sin_vc_seleccionados())
        self.btn_accion_papelera.setEnabled(habilitado)
        self.btn_accion_papelera.setToolTip("" if habilitado else "Solo se pueden enviar a la papelera contratos SIN VC.")

    def _on_accion_papelera_clicked(self):
        """Envía a la papelera (RegistroEliminado) el contrato actual de cada
        VIN SIN VC seleccionado, por ID. No se puede deshacer desde la app."""
        vins = self._vins_sin_vc_seleccionados()
        if not vins:
            return
        df_base = self.legacy.df_base
        contratos = comercial_services.agregar_id_a_cambios({vin: {} for vin in vins}, df_base)
        items = [(vin, contratos[vin].get('ID')) for vin in vins]

        confirmar = QMessageBox.question(
            self, "Enviar a papelera",
            f"Se enviarán a la papelera {len(items)} contrato(s) SIN VC. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmar != QMessageBox.StandardButton.Yes:
            return

        self.btn_accion_papelera.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Enviando a la papelera…")
        self._papelera_thread = EnviarPapeleraThread(self.legacy.writer, items, module_name="Comercial")
        self._papelera_thread.finished_signal.connect(lambda ok, hechos: self._on_papelera_finished(ok, hechos))
        self._papelera_thread.start()

    def _on_papelera_finished(self, success, eliminados):
        QApplication.restoreOverrideCursor()
        dm = self.legacy.data_manager
        if eliminados and not dm.df_master.empty:
            for vin, id_contrato in eliminados:
                dm.df_master = comercial_services.quitar_vin(dm.df_master, vin, id_contrato)
            dm.data_ready.emit()
            self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
            self._refresh_new_ui_data()
        self._actualizar_estado_acciones_rapidas()
        if success:
            guardado_listo(self, "Enviado a la papelera")
            terminar_guardando(self, texto_exito="Enviado a la papelera")
            QMessageBox.information(self, "Papelera", f"Se enviaron {len(eliminados)} contrato(s) a la papelera.")
        else:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(
                self, "Error",
                f"Se enviaron {len(eliminados)} contrato(s) a la papelera y el resto no se pudo eliminar. Intenta de nuevo.")

    def _build_new_ui_acciones_rapidas_solo_vigentes(self):
        """Acción exclusiva de "Vigentes" (24-09-2026, pedido explícito del
        usuario): igual que "Marcar como Vencido" en Vencidos, NO depende de
        la selección de la tabla -- actúa sobre TODOS los vehículos de la
        bandeja "Vigentes" con ESTADO COMERCIAL = "Activación Pendiente" Y
        ESTADO DE ACTIVACIÓN ACTUAL = "Conectado" (ver
        _on_accion_marcar_vigente_clicked/_actualizar_boton_marcar_vigente).
        Modifica datos reales en PruebasFM.xlsx."""
        widget = QWidget()
        layout = estilo_com.GrillaAcciones(widget)

        self.btn_accion_marcar_vigente = self._build_new_ui_accion_button(
            "fa5s.check-circle", "Marcar como Vigente", "Corrige el estado desactualizado", color=estilo_com.VERDE
        )
        self.btn_accion_marcar_vigente.setEnabled(False)
        self.btn_accion_marcar_vigente.clicked.connect(self._on_accion_marcar_vigente_clicked)

        layout.agregar(self.btn_accion_marcar_vigente)

        return widget

    def _build_new_ui_acciones_rapidas_solo_inconsistencias(self):
        """Acción exclusiva del modo "Revisar inconsistencias": corrige el
        TIPO DE FACTURACION de la selección (una o varias unidades) cuando
        la matriz de forma de contrato tiene una única opción válida."""
        widget = QWidget()
        layout = estilo_com.GrillaAcciones(widget)

        self.btn_accion_arreglar_tipo_fact = self._build_new_ui_accion_button(
            "fa5s.magic", "Arreglar tipo de facturación", "Corrige el tipo de facturación según la forma de contrato",
            color=estilo_com.AZUL
        )
        self.btn_accion_arreglar_tipo_fact.setEnabled(False)
        self.btn_accion_arreglar_tipo_fact.clicked.connect(self._on_arreglar_tipo_fact_seleccion_clicked)

        layout.agregar(self.btn_accion_arreglar_tipo_fact)

        return widget

    def _resolver_vin_por_fila_new_ui(self, row_idx):
        """VIN de una fila de new_ui_table por índice, para el resolver de
        AppTableWidget._get_vin_for_row (menú contextual "Copiar VIN").
        Misma fuente/orden que _obtener_vins_seleccionados, pero para una
        sola fila en vez de la selección completa."""
        if self._new_ui_en_grupos:
            return None
        es_revision_cm = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM
        df_fuente = getattr(self, '_new_ui_revision_cm_df', None) if es_revision_cm \
            else getattr(self, '_new_ui_bandeja_actual_df', None)
        if df_fuente is None or df_fuente.empty or row_idx >= len(df_fuente):
            return None
        vin = str(df_fuente.iloc[row_idx].get('VIN', '')).strip()
        return vin if vin and vin.upper() != 'NAN' else None

    def _obtener_vins_seleccionados(self):
        """Resuelve la selección actual de new_ui_table a una lista de VIN
        normalizados, deduplicados y en el orden de selección, junto con la
        fila original de cada uno -- para cualquiera de las 4 sub-pestañas.

        "Gestionar CM" resuelve contra _new_ui_revision_cm_df (CasosBajaCM.csv,
        con CASO_ID incluido); "Por gestionar"/"Renovaciones"/"Gestionar
        Bajas" resuelven contra _new_ui_bandeja_actual_df (subconjunto de
        df_base con todas sus columnas, aunque no todas se muestren). Ambos
        atributos se guardan en _refresh_new_ui_data justo antes de recortar
        a las columnas visibles, en el mismo orden que recibe el modelo.

        Compartido por "Enviar correo" (las 4 sub-pestañas) y "Confirmar
        baja" (solo Gestionar CM) para no resolver la selección dos veces
        con lógica distinta."""
        seleccion = self.new_ui_table.selectionModel().selectedRows()
        if not seleccion or self._new_ui_en_grupos:
            return [], {}

        es_revision_cm = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM
        df_fuente = getattr(self, '_new_ui_revision_cm_df', None) if es_revision_cm \
            else getattr(self, '_new_ui_bandeja_actual_df', None)
        if df_fuente is None or df_fuente.empty:
            return [], {}

        vins_ordenados = []
        filas_por_vin = {}
        for index in seleccion:
            row_idx = index.row()
            if row_idx >= len(df_fuente):
                continue
            fila = df_fuente.iloc[row_idx]
            vin = str(fila.get('VIN', '')).strip().upper()
            if not vin or vin == 'NAN' or vin in filas_por_vin:
                continue
            vins_ordenados.append(vin)
            filas_por_vin[vin] = fila

        return vins_ordenados, filas_por_vin

    def _on_accion_cm_enviar_correo_clicked(self):
        """Abre MailDialog con los VIN seleccionados en la sub-pestaña
        activa (cualquiera de las 4) ya buscados/marcados -- toda la
        validación de correo faltante, destinatarios y envío la sigue
        haciendo MailDialog, no se duplica aquí (ver
        mail_dialog.MailDialog._preseleccionar_vins).

        Si algún VIN seleccionado no está en Correo.xlsx (la base quedó
        desactualizada respecto a Comercial, ver mail_sync_service.
        cruzar_correos_maestro: toda fila de Comercial siempre queda en el
        cruce, tenga o no correo), no se abre el diálogo preseleccionado:
        se avisa cuáles VIN faltan y se ofrece abrir el Gestor de Correos
        normal (sin preselección) para que el usuario sincronice
        manualmente con "Sincronizar BBDD Correos" -- esa sincronización
        nunca se dispara sola desde acá.

        "Gestionar CM" mantiene la plantilla "Aviso de Vencimiento"
        preseleccionada (comportamiento original de esta sub-pestaña); las
        otras 3 abren MailDialog sin ninguna plantilla preseleccionada,
        para que el usuario la elija manualmente (ver conversación con el
        usuario, Fase 2)."""
        vins_ordenados, _ = self._obtener_vins_seleccionados()
        if not vins_ordenados:
            return

        faltantes = mail_sync_service.vins_faltantes_en_correos(vins_ordenados, config.settings.CORREOS_EXCEL_PATH)
        if faltantes:
            dialogo = DialogoAccionCm.vins_faltantes_en_correos(self, faltantes)
            if dialogo.exec() == QDialog.DialogCode.Accepted:
                MailDialog(parent=self).exec()
            return

        es_revision_cm = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM
        plantilla_inicial = mail_service.PLANTILLA_AVISO_VENCIMIENTO if es_revision_cm else None
        dialogo = MailDialog(parent=self, vins_preseleccionados=vins_ordenados, plantilla_inicial=plantilla_inicial)
        dialogo.exec()

    def _resolver_cdb_razon_social(self, vin):
        """CDB y RAZÓN SOCIAL de un VIN, resueltos siempre contra
        self.legacy.df_base (PruebasFM) -- fuente canónica de esos datos
        para cualquier VIN, independiente de la sub-pestaña activa. Se
        resuelve así (y no contra la bandeja de la sub-pestaña actual)
        porque "Gestionar CM" sale de CasosBajaCM.csv, que no trae CDB (ver
        cm_bajas_service.CASOS_BAJA_CM_COLUMNS). Devuelve ('', '') si el
        VIN no aparece en df_base."""
        df_base = self.legacy.df_base
        if df_base.empty or 'VIN' not in df_base.columns:
            return '', ''
        pos = self._posicion_vin_en_df(df_base, vin)
        if pos is None:
            return '', ''
        fila = df_base.iloc[pos]
        cdb = '' if pd.isna(fila.get('CDB')) else str(fila.get('CDB')).strip()
        razon_social = '' if pd.isna(fila.get('RAZÓN SOCIAL')) else str(fila.get('RAZÓN SOCIAL')).strip()
        return cdb, razon_social

    def _cdb_tiene_contacto(self, cdb):
        """True si existe al menos un contacto en contactos.xlsx
        (data_manager.get_contactos_df()) para ese CDB. La relación
        contacto <-> empresa es por CDB, nunca por VIN (ver conversación
        con el usuario, Fase 4): no se busca ninguna columna VIN dentro de
        contactos.xlsx porque no existe."""
        cdb_str = str(cdb).strip()
        if not cdb_str:
            return False
        df_contactos = self.legacy.data_manager.get_contactos_df()
        if df_contactos.empty or 'CDB' not in df_contactos.columns:
            return False
        return bool((df_contactos['CDB'].astype(str).str.strip() == cdb_str).any())

    def _aplicar_estilo_agregar_contacto(self, tiene_contacto):
        """Azul si el CDB del VIN seleccionado ya tiene contacto, rojo si
        no tiene ninguno; estilo neutro (con el mismo :disabled ya definido
        en ACCION_RAPIDA_BUTTON_STYLE_DEFAULT) cuando no hay exactamente un
        VIN seleccionado (tiene_contacto=None)."""
        btn = self.btn_accion_agregar_contacto
        if tiene_contacto is None:
            btn.setStyleSheet(getattr(btn, '_qss_por_defecto', ACCION_RAPIDA_BUTTON_STYLE_DEFAULT))
            self._pintar_icono_accion(btn, 'fa5s.user-plus', estilo_com.VERDE)
        elif tiene_contacto:
            self._pintar_icono_accion(btn, 'fa5s.user-check', estilo_com.VERDE)
        else:
            self._pintar_icono_accion(btn, 'fa5s.user-plus', estilo_com.ROJO)

    @staticmethod
    def _pintar_icono_accion(btn, icon_name, color):
        btn._icono_frame.setStyleSheet(estilo_com.qss_icono_accion(color))
        btn._icono_lbl.setPixmap(ThemeManager.icon_pixmap(icon_name, color=color, size=12))

    def _es_unidad_sin_contrato_sin_registro(self, vin):
        """True solo si la unidad con este VIN tiene FORMA DE CONTRATO='Sin
        Contrato' y TIPO DE FACTURACION='Sin Registro' (25-09-2026, ver
        _on_accion_editar_unidad_clicked): el caso real de una unidad recién
        creada desde comercial_agregar.py/general.py que todavía no fue
        gestionada comercialmente, único caso donde forzar ESTADO
        COMERCIAL/ESTADO DE ACTIVACIÓN ACTUAL al abrir "Por gestionar" tiene
        sentido de negocio."""
        df = self.df_base
        if df.empty or 'VIN' not in df.columns:
            return False
        coincidencias = df[df['VIN'].astype(str).str.strip() == str(vin).strip()]
        if coincidencias.empty:
            return False
        fila = coincidencias.iloc[0]
        forma = str(fila.get(COL_FORMA_CONTRATO, '')).strip().upper()
        tipo_fact = str(fila.get(COL_TIPO_FACTURACION, '')).strip().upper()
        return forma == 'SIN CONTRATO' and tipo_fact == VALOR_TIPO_FACT_SIN_REGISTRO

    def _on_accion_editar_unidad_clicked(self):
        """Reutiliza _ComercialModuleLegacy._handle_editar_unidad(row, vin)
        tal cual (mismo ComercialAgregarDialog en modo edición, mismo
        SaveExcelThread/ExcelWriter.update_cells, mismo backup y log a
        LogApp.csv que ya funciona en Vista Completa) -- self._handle_
        editar_unidad no es un método propio de ComercialModule, así que
        __getattr__ lo resuelve contra self.legacy automáticamente (ver
        __getattr__ más abajo); `row` no se usa dentro de ese método, solo
        `vin`, así que se pasa 0 como valor de relleno."""
        vins_ordenados, _ = self._obtener_vins_seleccionados()
        if len(vins_ordenados) != 1:
            return
        # Modo restringido (22-09-2026, ampliado a "Ofrecer y reactivar" --
        # antes "Gestionar Bajas" -- a pedido explícito): al editar desde
        # "Por gestionar" (índice 0) o desde "Ofrecer y reactivar" (índice
        # _NEW_UI_SUBTAB_OFRECER_REACTIVAR, caso "cliente interesado en
        # volver") -- Renovaciones y Gestionar CM mantienen edición completa.
        # "Vigentes" (índice _NEW_UI_SUBTAB_VIGENTES, 25-09-2026) tiene su
        # propio modo restringido (ver desde_vigentes en
        # _handle_editar_unidad/restringir_vigentes en
        # ComercialAgregarDialog): no fuerza valores, solo recorta ESTADO
        # COMERCIAL y bloquea Operaciones.
        #
        # Ajustado (25-09-2026, pedido explícito): "Por gestionar" ya no es
        # SOLO la unidad recién creada desde comercial_agregar.py/general.py
        # -- desde que _mask_revisar_hacia_comercial() amplió el filtro,
        # también caen ahí unidades reales con FORMA DE CONTRATO/TIPO DE
        # FACTURACION ya definidos (ej. combinaciones de "Revisar" que la
        # matriz manda a COMERCIAL). Operaciones se bloquea siempre para
        # cualquier unidad de "Por gestionar"/"Ofrecer y reactivar" (nadie
        # gestiona Operaciones desde este formulario), pero forzar
        # "Activación Pendiente"/"Activando" solo tiene sentido para la
        # unidad todavía sin contrato ni registro (el punto de partida real
        # del flujo de activación) -- ver forzar_activacion_pendiente.
        idx_activo = self.new_ui_subtabs.currentIndex()
        desde_por_gestionar = idx_activo in (self._NEW_UI_SUBTAB_POR_GESTIONAR, self._NEW_UI_SUBTAB_OFRECER_REACTIVAR)
        forzar_activacion_pendiente = desde_por_gestionar and self._es_unidad_sin_contrato_sin_registro(vins_ordenados[0])
        desde_vigentes = idx_activo == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES and self._unidad_vigente_en_curso(vins_ordenados[0])
        self._handle_editar_unidad(
            0, vins_ordenados[0], desde_por_gestionar=desde_por_gestionar,
            forzar_activacion_pendiente=forzar_activacion_pendiente, desde_vigentes=desde_vigentes,
        )
        # Con el CDB comercial distinto al de la empresa, el formulario abre posado en ese campo
        cdb, razon_social = self._resolver_cdb_razon_social(vins_ordenados[0])
        form = getattr(self, 'unidad_nueva_form', None)
        if form is not None and comercial_services.cdb_discrepante(cdb, razon_social, self._cdb_referencia_actual()):
            campo = form.inputs.get('CDB')
            if campo is not None and campo.isEnabled():
                campo.setFocus()
                campo.selectAll()

    def _on_accion_agregar_contacto_clicked(self):
        """Abre el mismo ContactosAddDialog que ya usa Clientes y Flotas
        (general.py._handle_agregar_contacto) y Contactos (contactos.py.
        _open_add_dialog), con CDB/RAZÓN SOCIAL resueltos desde df_base por
        el VIN seleccionado (ver _resolver_cdb_razon_social). Mismo
        mecanismo de guardado (AddContactoThread -> ExcelWriter.
        add_new_row, con su backup ya incluido) y mismo ID autogenerado
        (contactos_service.generar_nuevo_id_contacto). No valida
        duplicados: un mismo correo puede repetirse en otra empresa
        (decisión explícita, ver conversación con el usuario, Fase 4)."""
        vins_ordenados, _ = self._obtener_vins_seleccionados()
        if len(vins_ordenados) != 1:
            return
        cdb, razon_social = self._resolver_cdb_razon_social(vins_ordenados[0])

        dialog = ContactosAddDialog(self, cdb_prefill=cdb, flota_prefill=razon_social)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_data = dialog.get_data()
        new_data['ID'] = contactos_service.generar_nuevo_id_contacto(self.legacy.data_manager.get_contactos_df())

        self.btn_accion_agregar_contacto.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Agregando el contacto…")
        self._add_contacto_thread_comercial = AddContactoThread(self.legacy.writer, new_data)
        self._add_contacto_thread_comercial.finished_signal.connect(self._on_agregar_contacto_comercial_finished)
        self._add_contacto_thread_comercial.start()

    def _on_agregar_contacto_comercial_finished(self, success, new_data):
        QApplication.restoreOverrideCursor()
        # Recalcula habilitación Y color (no un simple setEnabled(True)):
        # la selección pudo no cambiar, pero el CDB recién agregado ya
        # tiene contacto ahora.
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se pudo agregar el contacto. Verifica si contactos.xlsx está abierto.")
            return
        terminar_guardando(self, texto_exito="Contacto agregado")
        # Mismo mecanismo de refresco que general.py: recarga contactos.xlsx
        # desde disco: al terminar emite contactos_ready, ya conectado a
        # _actualizar_estado_acciones_rapidas (ver __init__) para que el
        # botón refleje el nuevo contacto sin esperar un cambio de selección.
        self.legacy.data_manager.load_contactos_async()

    def _on_accion_cm_exportar_lista_clicked(self):
        """"Exportar lista" (28-09-2026, a pedido explícito): guarda la
        bandeja de "Gestionar CM" tal como se ve en pantalla (mismas
        columnas visibles, respeta la búsqueda activa -- esta sub-pestaña
        y el filtro de tarjeta KPI activo) directo en el Escritorio del
        usuario, sin diálogo de guardado. El equipo no da de baja el
        contrato CM: solo avisa a quien lo administra, y este archivo es
        lo que se les envía manualmente (ver docs/07, sección CM).

        Reutiliza ExportExcelThread (mismo usado por
        AppTableWidget.export_to_excel) en vez de reimplementar la
        escritura del Excel -- ya sabe reconvertir "PAGO CM" de texto
        formateado a número nativo."""
        df_visible = self.new_ui_model.get_df()
        if df_visible.empty:
            QMessageBox.information(self, "Exportar lista", "No hay casos pendientes para exportar.")
            return
        if getattr(self, '_export_cm_thread', None) is not None and self._export_cm_thread.isRunning():
            QMessageBox.information(self, "Exportar lista", "Ya hay una exportación en curso. Espera a que termine.")
            return

        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        filepath = os.path.join(carpeta, f"Casos_CM_Pendientes_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx")

        progreso = QProgressDialog("Generando Excel...", "", 0, 100, self)
        progreso.setWindowTitle("Exportando")
        progreso.setWindowModality(Qt.WindowModality.NonModal)
        progreso.setCancelButton(None)
        progreso.setMinimumDuration(0)
        progreso.setAutoClose(False)
        progreso.setValue(0)
        progreso.show()

        self._export_cm_thread = ExportExcelThread(df_visible.copy(), filepath, parent=self)
        self._export_cm_thread.progress_signal.connect(progreso.setValue)

        def _on_finished(success, ruta, error_msg):
            progreso.close()
            if not success:
                QMessageBox.critical(self, "Error", error_msg)

        self._export_cm_thread.finished_signal.connect(_on_finished)
        self._export_cm_thread.start()

    def _on_accion_cm_confirmar_baja_clicked(self):
        """Confirma la baja del CM de TODOS los casos seleccionados en
        "Gestionar CM" (selección múltiple habilitada solo en esta
        sub-pestaña, ver _toggle_acciones_rapidas_panel): misma regla de
        negocio que la edición manual de ESTADO DEL CM a 'Terminated' en
        Contratos CM / Vista Completa (ver
        comercial_services.aplica_regla_terminated_cm), aplicada aquí de
        forma explícita en vez de por edición de grilla, y para todos los
        VIN elegidos a la vez -- una sola escritura a PruebasFM (un solo
        SaveExcelThread con todos los cambios) y, si tiene éxito, una sola
        lectura/escritura de CasosBajaCM.csv (ver
        cm_bajas_service.procesar_confirmacion_baja_cm_multiple) para marcar
        todos los CASO_ID seleccionados como CONFIRMADA_BAJA. Con un único
        VIN seleccionado el resultado es idéntico al de antes (listas de un
        solo elemento)."""
        vins_ordenados, casos_por_vin = self._obtener_vins_seleccionados()
        if not vins_ordenados:
            return

        cambios_por_vin = comercial_services.aplica_regla_terminated_cm('ESTADO DEL CM', 'Terminated')
        cambios_por_vin = {'ESTADO DEL CM': 'Terminated', **cambios_por_vin}
        valid = comercial_services.agregar_id_a_cambios(
            {vin: {'VIN': vin, 'cambios': dict(cambios_por_vin)} for vin in vins_ordenados}, self.legacy.df_base)
        caso_ids = []
        for vin in vins_ordenados:
            caso_id = casos_por_vin[vin].get('CASO_ID')
            if caso_id is not None and str(caso_id).strip():
                caso_ids.append(caso_id)

        dialogo = DialogoAccionCm.confirmacion(self, vins_ordenados)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return

        self.btn_accion_cm_confirmar_baja.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Confirmando la baja del CM…")
        self._confirmar_baja_cm_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._confirmar_baja_cm_thread.finished_signal.connect(
            lambda success: self._on_confirmar_baja_cm_finished(success, valid, caso_ids)
        )
        self._confirmar_baja_cm_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._confirmar_baja_cm_thread.start()

    def _on_confirmar_baja_cm_finished(self, success, valid, caso_ids):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar la baja del CM. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            df_m_copy = dm.df_master.copy()
            df_m_copy = comercial_services.aplicar_cambios_pendientes(df_m_copy, valid)
            dm.df_master = df_m_copy

        try:
            cm_bajas_service.procesar_confirmacion_baja_cm_multiple(
                caso_ids=caso_ids,
                casos_path=config.settings.CASOS_BAJA_CM_PATH,
            )
        except Exception as e:
            print(f"No se pudo confirmar la baja de los casos CM {caso_ids}: {e}")

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _on_accion_enviar_operaciones_clicked(self):
        """"Enviar a operaciones" (22-09-2026, a pedido explícito): cambia
        ESTADO COMERCIAL Y ETAPA GESTIÓN a "OPERACIONES" de todos los VIN
        seleccionados, disponible en las sub-pestañas donde el botón sigue
        habilitado (ver _actualizar_estado_acciones_rapidas: deshabilitado
        en "Por gestionar" y "Gestionar CM"). Pensado para el flujo de
        Renovaciones (el cliente rechaza la renovación), pero no se
        restringe a esa sub-pestaña.

        ESTADO COMERCIAL (23-09-2026, ciclo de baja anticipada): desde
        "Vigentes" fija BAJA SOLICITADA en vez de BAJA directo -- ese caso es
        una unidad Conectada y con contrato vigente que se da de baja antes
        de tiempo (siniestro u otro problema), no una baja por vencimiento o
        rechazo de renovación. Operaciones -> Bajas la confirma como BAJA
        recién al marcarla DESCONECTADO (ver operaciones_services.
        calcular_cambios_marcar_desconectado). Las demás sub-pestañas siguen
        fijando BAJA directo, sin cambios.

        ETAPA GESTIÓN se recalcula vía DataFrameFormatter.calcular_etapa_gestion_esperada
        (25-09-2026, corrección de bug real: antes se forzaba a OPERACIONES
        SIEMPRE, sin importar ESTADO DE ACTIVACIÓN ACTUAL -- ver
        conversación con el usuario, incidente real donde 653 VIN enviados
        desde "Vencidos" a BAJA quedaron con ~270 contradiciendo la matriz,
        porque la mayoría ya estaba Desconectada y la matriz real dice
        COMERCIAL para BAJA+Desconectado, no OPERACIONES). Se calcula por
        VIN, con el ESTADO DE ACTIVACIÓN ACTUAL/TIPO DE FACTURACION reales de
        cada unidad (self.df_base) y el ESTADO COMERCIAL nuevo
        (estado_comercial_destino) -- misma función que ya usa
        ComercialAgregarDialog/clean()/detectar_contradicciones_etapa_gestion,
        sin reimplementar la regla.

        Emite data_manager.data_ready al terminar (26-09-2026: antes no se
        emitía) para que Operaciones (y cualquier otro módulo suscrito) se
        refresque solo, en vez de necesitar una recarga manual de la app."""
        vins_ordenados, _ = self._obtener_vins_seleccionados()
        if not vins_ordenados:
            return

        # Por unidad (ex "Vigentes"): vigente en curso -> baja anticipada
        # (BAJA SOLICITADA); el resto -> BAJA directo.
        en_renovar = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
        destino_por_vin = {
            vin: (VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA if en_renovar and self._unidad_vigente_en_curso(vin)
                  else VALOR_ESTADO_COMERCIAL_BAJA)
            for vin in vins_ordenados
        }
        destinos = set(destino_por_vin.values())
        estado_comercial_destino = destinos.pop() if len(destinos) == 1 else VALOR_ESTADO_COMERCIAL_BAJA

        dialogo = DialogoAccionCm.confirmacion_enviar_operaciones(self, vins_ordenados, estado_comercial_destino)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return

        df_base = self.df_base
        lookup_por_vin = {}
        if not df_base.empty and 'VIN' in df_base.columns:
            df_lookup = df_base.drop_duplicates('VIN', keep='last').set_index(
                df_base['VIN'].astype(str).str.strip().str.upper()
            )
            lookup_por_vin = df_lookup.to_dict('index')

        valid = {}
        for vin in vins_ordenados:
            fila_actual = lookup_por_vin.get(str(vin).strip().upper(), {})
            estado_vin = destino_por_vin[vin]
            row_para_matriz = {
                COL_ESTADO_COMERCIAL: estado_vin,
                COL_ESTADO_ACTIVACION: fila_actual.get(COL_ESTADO_ACTIVACION, ''),
                COL_TIPO_FACTURACION: fila_actual.get(COL_TIPO_FACTURACION, ''),
                COL_ETAPA_GESTION: fila_actual.get(COL_ETAPA_GESTION, ''),
            }
            nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada(row_para_matriz)
            valid[vin] = {'VIN': vin, 'cambios': {
                COL_ESTADO_COMERCIAL: estado_vin,
                COL_ETAPA_GESTION: nueva_etapa,
            }}
        comercial_services.agregar_id_a_cambios(valid, df_base)

        self.btn_accion_enviar_operaciones.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Enviando a Operaciones…")
        self._enviar_operaciones_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._enviar_operaciones_thread.finished_signal.connect(
            lambda success: self._on_enviar_operaciones_finished(success, valid)
        )
        self._enviar_operaciones_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._enviar_operaciones_thread.start()

    def _on_enviar_operaciones_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar el envío a operaciones. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            # A diferencia de _on_confirmar_baja_cm_finished/_on_editar_unidad_finished
            # (que solo actualizan la vista de Comercial), esta acción debe
            # reflejarse de inmediato en Operaciones -> Bajas: data_ready es la
            # señal que ese módulo ya escucha para refrescarse solo.
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _on_accion_marcar_vencido_clicked(self):
        """"Marcar como Vencido" (sub-pestaña Vencidos, 23-09-2026; pasó a
        actuar solo sobre las filas seleccionadas el 05-10-2026, a pedido
        explícito): actúa únicamente sobre las filas seleccionadas con
        fecha de término expirada (comercial_services.filtrar_vencidos)
        cuyo ESTADO COMERCIAL esté en ESTADOS_COMERCIAL_CORREGIBLES_A_
        VENCIDO (Vigente/Activación Pendiente). Decisión confirmada con el
        usuario (23-09-2026): NO toca Baja/Baja Solicitada/Revisar aunque la
        fecha ya haya pasado -- esos estados representan una decisión de
        negocio ya tomada, no un olvido. Mismo mecanismo de guardado que
        "Enviar a operaciones" (SaveExcelThread / ExcelWriter.update_cells,
        con su backup ya incluido)."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            return

        df_pendientes = self._pendientes_marcar_vencido_seleccionados()
        if df_pendientes.empty:
            return
        self._marcar_vencido_df(df_pendientes)

    def _on_marcar_todos_vencidos_clicked(self):
        """Botón de la barra: marca como Vencido TODAS las unidades de la
        cartera con término pasado y estado todavía Vigente / Activación
        Pendiente (misma regla y mismo guardado que la acción del panel)."""
        df_pendientes = self._unidades_pendientes_marcar_vencido(getattr(self.legacy, 'df_base', None))
        if df_pendientes is None or df_pendientes.empty:
            QMessageBox.information(
                self, "Marcar como Vencido",
                "No hay unidades con la fecha de término pasada y el estado sin actualizar.")
            return
        self._marcar_vencido_df(df_pendientes)

    def _actualizar_boton_marcar_vencidos_barra(self):
        """Contador del botón de la barra: unidades con término pasado y
        estado sin actualizar. Naranja con 1 o más; neutro con 0."""
        btn = getattr(self, 'btn_marcar_vencidos_barra', None)
        if btn is None:
            return
        df = getattr(self.legacy, 'df_base', None)
        cantidad = 0 if df is None or df.empty else len(self._unidades_pendientes_marcar_vencido(df))
        btn.setText(f" {cantidad}")
        if cantidad:
            btn.setIcon(ThemeManager.icon('fa5s.calendar-times', color=estilo_com.AMBAR))
            estilo_com.aplicar_estilo_boton_barra(btn, 'naranja')
            btn.setToolTip(
                f"{cantidad} unidad(es) con la fecha de término pasada siguen Vigente o en Activación Pendiente. "
                "Clic para marcarlas como Vencido.")
        else:
            btn.setIcon(ThemeManager.icon('fa5s.calendar-times', color=TEXT_SECONDARY))
            estilo_com.aplicar_estilo_boton_barra(btn, 'neutro')
            btn.setToolTip("Marcar como Vencido: no hay unidades con el estado desactualizado")

    def _marcar_vencido_df(self, df_pendientes):
        vins_ordenados = []
        vistos = set()
        for vin in df_pendientes.get('VIN', pd.Series(dtype=str)).astype(str).str.strip().str.upper():
            if not vin or vin == 'NAN' or vin in vistos:
                continue
            vistos.add(vin)
            vins_ordenados.append(vin)
        if not vins_ordenados:
            return

        # ETAPA GESTIÓN se recalcula acá (28-09-2026, corrección de bug real:
        # unidades Vigente+Activando marcadas Vencido quedaban con ETAPA
        # GESTIÓN=OPERACIONES desactualizada y seguían apareciendo en
        # Operaciones -> Activaciones) -- mismo patrón que
        # _on_accion_enviar_operaciones_clicked más arriba.
        estado_vencido = VALOR_ESTADO_COMERCIAL_VENCIDO.capitalize()
        df_lookup = df_pendientes.drop_duplicates('VIN', keep='last').set_index(
            df_pendientes['VIN'].astype(str).str.strip().str.upper()
        )
        lookup_por_vin = df_lookup.to_dict('index')

        valid = {}
        for vin in vins_ordenados:
            fila_actual = lookup_por_vin.get(vin, {})
            row_para_matriz = {
                COL_ESTADO_COMERCIAL: estado_vencido,
                COL_ESTADO_ACTIVACION: fila_actual.get(COL_ESTADO_ACTIVACION, ''),
                COL_TIPO_FACTURACION: fila_actual.get(COL_TIPO_FACTURACION, ''),
                COL_ETAPA_GESTION: fila_actual.get(COL_ETAPA_GESTION, ''),
            }
            nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada(row_para_matriz)
            # Se escribe "Vencido" (no "VENCIDO"); las comparaciones normalizan con upper()
            valid[vin] = {'VIN': vin, 'cambios': {
                COL_ESTADO_COMERCIAL: estado_vencido,
                COL_ETAPA_GESTION: nueva_etapa,
            }}
        comercial_services.agregar_id_a_cambios(valid, self.legacy.df_base)

        self.btn_accion_marcar_vencido.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando unidades como Vencido…")
        self._marcar_vencido_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._marcar_vencido_thread.finished_signal.connect(
            lambda success: self._on_marcar_vencido_finished(success, valid)
        )
        self._marcar_vencido_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._marcar_vencido_thread.start()

    def _on_marcar_vencido_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar la actualización de Vencidos. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            # Mismo criterio que _on_enviar_operaciones_finished: ESTADO
            # COMERCIAL cambió, así que cualquier otro módulo suscrito a
            # data_ready (ej. Operaciones) debe enterarse sin recarga manual.
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _on_accion_marcar_vigente_clicked(self):
        """"Marcar como Vigente" (sub-pestaña Vigentes, 24-09-2026, a pedido
        explícito): mismo mecanismo que "Marcar como Vencido" pero para el
        caso inverso -- la unidad ya está "Conectado" en Servicios Conectados
        (ESTADO DE ACTIVACIÓN ACTUAL, dato externo que manda) pero ESTADO
        COMERCIAL quedó atrás en "Activación Pendiente" por error humano. NO
        usa la selección de la tabla: actúa sobre TODOS los vehículos de la
        bandeja "Vigentes" actualmente visible (_new_ui_bandeja_actual_df,
        ya filtrada por comercial_services.filtrar_vigentes y por el texto
        de búsqueda si hay) que cumplan esa combinación. Mismo mecanismo de
        guardado que "Marcar como Vencido" (SaveExcelThread /
        ExcelWriter.update_cells, con su backup ya incluido)."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            return

        df_bandeja = getattr(self, '_new_ui_bandeja_actual_df', None)
        if df_bandeja is None or df_bandeja.empty or \
           COL_ESTADO_COMERCIAL not in df_bandeja.columns or COL_ESTADO_ACTIVACION not in df_bandeja.columns:
            return

        estado_com = df_bandeja[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
        estado_act = df_bandeja[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
        df_pendientes = df_bandeja[
            (estado_com == VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE) & (estado_act == ESTADO_CONECTADO)
        ]

        vins_ordenados = []
        vistos = set()
        for vin in df_pendientes.get('VIN', pd.Series(dtype=str)).astype(str).str.strip().str.upper():
            if not vin or vin == 'NAN' or vin in vistos:
                continue
            vistos.add(vin)
            vins_ordenados.append(vin)
        if not vins_ordenados:
            return

        valid = comercial_services.agregar_id_a_cambios({
            vin: {'VIN': vin, 'cambios': {COL_ESTADO_COMERCIAL: VALOR_ESTADO_COMERCIAL_VIGENTE.capitalize()}}
            for vin in vins_ordenados
        }, self.legacy.df_base)

        self.btn_accion_marcar_vigente.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando unidades como Vigente…")
        self._marcar_vigente_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._marcar_vigente_thread.finished_signal.connect(
            lambda success: self._on_marcar_vigente_finished(success, valid)
        )
        self._marcar_vigente_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._marcar_vigente_thread.start()

    def _on_marcar_vigente_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar la actualización de Vigentes. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _build_new_ui_accion_button(self, icon_name, titulo, subtitulo, color=None):
        color = color or estilo_com.AZUL
        # Fondo/borde animados al pasar el mouse (ver BotonAccionRapida)
        btn = estilo_com.BotonAccionRapida(color)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Estilo neutro al que vuelve "Agregar contacto" (ver _aplicar_estilo_agregar_contacto)
        btn._qss_por_defecto = estilo_com.QSS_ACCION_RAPIDA_TRANSPARENTE
        btn.setMinimumHeight(36)
        btn.setToolTip(subtitulo)

        layout = QHBoxLayout(btn)
        layout.setContentsMargins(6, 4, 10, 4)
        layout.setSpacing(8)

        icon_frame = QFrame()
        icon_frame.setFixedSize(26, 26)
        icon_frame.setStyleSheet(estilo_com.qss_icono_accion(color))
        icon_frame_layout = QVBoxLayout(icon_frame)
        icon_frame_layout.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap(icon_name, color=color, size=12))
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_frame_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_frame)
        btn._icono_frame = icon_frame
        btn._icono_lbl = icon_lbl

        titulo_lbl = QLabel(titulo)
        titulo_lbl.setToolTip(subtitulo)
        titulo_lbl.setStyleSheet(f"color: {estilo_com.TINTA}; font-weight: bold; font-size: 12px; background: transparent; border: none;")
        layout.addWidget(titulo_lbl, stretch=1)

        return btn

    def _on_new_ui_subtab_changed(self, index):
        """Cambiar de sub-pestaña en la Nueva interfaz debe filtrar la
        bandeja con la regla de negocio real correspondiente (ver
        _NEW_UI_SUBTAB_FILTERS), no solo cambiar una etiqueta visual."""
        # Elegir una sub-pestaña cierra el aviso que estuviera abierto
        fotos = self._fotos_para_transicion_subtab()
        if self._avisos_activos():
            for btn in (self.legacy.btn_alerta_etapa, self.legacy.btn_revisar_inconsistencias_forma_contrato):
                btn.setChecked(False)
        self._new_ui_active_subtab = index
        self._new_ui_grupo_abierto.clear()
        self._toggle_acciones_rapidas_panel(index)
        self._refresh_new_ui_data()
        for transicion, foto in fotos:
            transicion.iniciar(foto)
        if getattr(self, '_panel_acciones_abierto', False):
            self._panel_acciones.raise_()

    def _fotos_para_transicion_subtab(self):
        """Foto de KPIs y bandeja ANTES de repintar la sub-pestaña nueva
        (solo lo visible: con "Ampliar" activo no hay KPIs que animar)."""
        fotos = []
        for transicion, contenedor in (
            (getattr(self, '_transicion_kpis', None), getattr(self, '_new_ui_kpi_contenedor', None)),
            (getattr(self, '_transicion_contenido', None), getattr(self, '_new_ui_contenido', None)),
        ):
            if transicion is not None and contenedor is not None and contenedor.isVisible():
                transicion.terminar()
                fotos.append((transicion, contenedor.grab()))
        return fotos

    def _on_new_ui_subtab_clicked(self, index):
        # Clic en la sub-pestaña ya marcada: currentChanged no se emite
        if index == self.new_ui_subtabs.currentIndex() and self._avisos_activos():
            for btn in (self.legacy.btn_alerta_etapa, self.legacy.btn_revisar_inconsistencias_forma_contrato):
                btn.setChecked(False)

    def _avisos_activos(self):
        return bool(getattr(self.legacy, '_filtro_contradicciones_etapa_activo', False)
                    or getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False))

    def _on_aviso_bandeja_toggled(self, _checked=False):
        if self._avisos_activos():
            self._new_ui_active_subtab = self._NEW_UI_SUBTAB_AVISOS
        else:
            self._new_ui_active_subtab = self.new_ui_subtabs.currentIndex()
        self._toggle_acciones_rapidas_panel(self._new_ui_active_subtab)
        self._refresh_new_ui_data()
        self._actualizar_boton_arreglar_inconsistencias()

    def _actualizar_boton_arreglar_inconsistencias(self):
        """Visible solo con "Revisar inconsistencias" activo; muestra cuántas
        unidades se pueden corregir de forma automática."""
        btn = getattr(self, 'btn_arreglar_inconsistencias_barra', None)
        if btn is None:
            return
        activo = bool(getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False))
        btn.setVisible(activo)
        if not activo:
            return
        df = getattr(self.legacy, 'df_base', None)
        cantidad = 0 if df is None or df.empty else len(comercial_services.construir_correcciones_tipo_facturacion(df))
        btn.setText(f" Arreglar ({cantidad})")
        btn.setEnabled(cantidad > 0)
        if cantidad:
            btn.setToolTip(
                f"Corrige el TIPO DE FACTURACION de {cantidad} unidad(es) según su FORMA DE CONTRATO. "
                "Las que tienen más de una opción válida (Venta, Conversión) no se tocan.")
        else:
            btn.setToolTip("No hay unidades que se puedan corregir automáticamente.")

    def _on_arreglar_inconsistencias_clicked(self):
        """Botón de la barra: corrige todas las unidades que se pueden."""
        df = getattr(self.legacy, 'df_base', None)
        if df is None or df.empty:
            return
        correcciones = comercial_services.construir_correcciones_tipo_facturacion(df)
        if correcciones and (len(correcciones) == 1 or self._confirmar_arreglo_tipo_facturacion(correcciones)):
            self._aplicar_correcciones_tipo_facturacion(correcciones)

    def _correcciones_de_seleccion(self):
        """(VIN seleccionados, {VIN: tipo correcto}) de la selección de la bandeja."""
        n_seleccionadas = len(self.new_ui_table.selectionModel().selectedRows())
        df = getattr(self.legacy, 'df_base', None)
        if n_seleccionadas == 0 or df is None or df.empty:
            return [], {}
        vins, _ = self._obtener_vins_seleccionados()
        vins_norm = {str(v).strip().upper() for v in vins}
        seleccion = df[df['VIN'].astype(str).str.strip().str.upper().isin(vins_norm)]
        return vins, comercial_services.construir_correcciones_tipo_facturacion(seleccion)

    def _actualizar_boton_arreglar_tipo_fact(self):
        """Acción del panel derecho en "Revisar inconsistencias": se habilita
        si al menos una de las unidades seleccionadas se puede corregir."""
        btn = getattr(self, 'btn_accion_arreglar_tipo_fact', None)
        if btn is None or not self.acciones_rapidas_inconsistencias.isVisibleTo(self._panel_acciones):
            return
        vins, correcciones = self._correcciones_de_seleccion()
        btn.setEnabled(bool(correcciones))
        if not vins:
            btn.setToolTip("Selecciona una o varias unidades")
        elif not correcciones:
            btn.setToolTip(
                "Esta combinación no se puede corregir automáticamente: la forma de contrato tiene más de una "
                "opción válida (Venta, Conversión). Edita el contrato a mano." if len(vins) == 1
                else "Ninguna de las unidades seleccionadas se puede corregir automáticamente.")
        elif len(correcciones) < len(vins):
            btn.setToolTip(f"Se corregirán {len(correcciones)} de {len(vins)} unidades; el resto tiene más de una opción válida.")
        else:
            btn.setToolTip("Corrige el tipo de facturación según la forma de contrato")

    def _on_arreglar_tipo_fact_seleccion_clicked(self):
        vins, correcciones = self._correcciones_de_seleccion()
        if not correcciones:
            return
        if len(vins) > 1 and not self._confirmar_arreglo_tipo_facturacion(correcciones, len(vins)):
            return
        self._aplicar_correcciones_tipo_facturacion(correcciones)

    def _confirmar_arreglo_tipo_facturacion(self, correcciones, total_seleccionadas=None):
        """Resumen de cuántas unidades pasan de qué forma de contrato y tipo
        de facturación actual al tipo nuevo."""
        df = self.legacy.df_base
        base = df.drop_duplicates('VIN', keep='last')
        por_vin = base.set_index(base['VIN'].astype(str).str.strip().str.upper()).to_dict('index')
        conteo = {}
        for vin, nuevo in correcciones.items():
            fila = por_vin.get(vin, {})
            forma = str(fila.get('FORMA DE CONTRATO', '')).strip().upper() or '-'
            actual = str(fila.get(COL_TIPO_FACTURACION, '')).strip().upper() or '-'
            conteo[(forma, actual, nuevo)] = conteo.get((forma, actual, nuevo), 0) + 1
        lineas = [f"{forma}: {actual} → {nuevo}  ·  {n} unidad(es)"
                  for (forma, actual, nuevo), n in sorted(conteo.items())]
        descripcion = "Se cambia solo el tipo de facturación, según la forma de contrato."
        if total_seleccionadas and total_seleccionadas > len(correcciones):
            descripcion += (f" {total_seleccionadas - len(correcciones)} de las seleccionadas tienen más de una opción "
                            "válida y no se modifican.")
        dialogo = DialogoAccion(
            self, " Arreglar tipo de facturación",
            icon_name="fa5s.magic", icon_color=PRIMARY, icon_bg_color="#EFF6FF",
            titulo="Arreglar tipo de facturación",
            subtitulo=f"{len(correcciones)} unidad(es) se corregirán",
            descripcion=descripcion, items=lineas, titulo_items="Forma de contrato: tipo actual → nuevo",
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'},
            ],
        )
        return dialogo.exec() == QDialog.DialogCode.Accepted

    def _aplicar_correcciones_tipo_facturacion(self, correcciones):
        df = self.legacy.df_base

        lookup_por_vin = df.drop_duplicates('VIN', keep='last').set_index(
            df.drop_duplicates('VIN', keep='last')['VIN'].astype(str).str.strip().str.upper()
        ).to_dict('index')
        valid = {}
        for vin, tipo_nuevo in correcciones.items():
            fila_actual = lookup_por_vin.get(vin, {})
            cambios = {COL_TIPO_FACTURACION: tipo_nuevo}
            nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada({
                COL_ESTADO_COMERCIAL: fila_actual.get(COL_ESTADO_COMERCIAL, ''),
                COL_ESTADO_ACTIVACION: fila_actual.get(COL_ESTADO_ACTIVACION, ''),
                COL_TIPO_FACTURACION: tipo_nuevo,
                COL_ETAPA_GESTION: fila_actual.get(COL_ETAPA_GESTION, ''),
            })
            if str(nueva_etapa).strip().upper() != str(fila_actual.get(COL_ETAPA_GESTION, '')).strip().upper():
                cambios[COL_ETAPA_GESTION] = nueva_etapa
            valid[vin] = {'VIN': vin, 'cambios': cambios}
        comercial_services.agregar_id_a_cambios(valid, df)

        self.btn_arreglar_inconsistencias_barra.setEnabled(False)
        self.btn_accion_arreglar_tipo_fact.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Corrigiendo tipo de facturación…")
        self._arreglar_inconsistencias_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._arreglar_inconsistencias_thread.finished_signal.connect(
            lambda success: self._on_arreglar_inconsistencias_finished(success, valid)
        )
        self._arreglar_inconsistencias_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._arreglar_inconsistencias_thread.start()

    def _on_arreglar_inconsistencias_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        if not success:
            terminar_guardando(self, exito=False)
            self._actualizar_boton_arreglar_inconsistencias()
            self._actualizar_boton_arreglar_tipo_fact()
            DialogoAccionCm.error(
                self,
                "No se pudo guardar la corrección. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self.legacy._df_inconsistencias_forma_contrato = comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion(
            self.legacy.df_base)
        self._refresh_new_ui_data()
        self._actualizar_boton_arreglar_inconsistencias()
        self._actualizar_estado_acciones_rapidas()
        terminar_guardando(self)

    def _refresh_bandeja_avisos(self):
        """Bandeja con las unidades de toda la base que marcan los avisos
        activos (mismas reglas que filtraban la tabla de Vista Completa)."""
        solo_inconsistencias = (getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False)
                                and not getattr(self.legacy, '_filtro_contradicciones_etapa_activo', False))
        columnas = self._COLUMNAS_BANDEJA_INCONSISTENCIAS if solo_inconsistencias else self._COLUMNAS_BANDEJA_AVISOS
        self._salir_vista_agrupada()
        df = getattr(self.legacy, 'df_base', None)
        if df is None or df.empty:
            df = pd.DataFrame(columns=columnas)
        else:
            if getattr(self.legacy, '_filtro_contradicciones_etapa_activo', False):
                df = comercial_services.detectar_contradicciones_etapa_gestion(df)
            if getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False):
                df = comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion(df)
            search_text = self.new_ui_search_input.text().strip().lower()
            if search_text and not df.empty:
                df = df[comercial_services.construir_mascara_busqueda(
                df, search_text, COLUMNAS_BUSQUEDA_COMERCIAL, COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL)]
            df = self.new_ui_table.apply_sort(df)

        self._new_ui_bandeja_actual_df = df
        self.lbl_grupo_abierto.setText(f"{len(df)} unidades")
        cols_presentes = [c for c in columnas if c in df.columns]
        self.new_ui_model.set_data(df[cols_presentes])
        # "Avisos" no es una de las 6 sub-pestañas regulares (no tiene índice
        # en NEW_UI_SUBTAB_COLUMN_WIDTHS): solo RAZÓN SOCIAL recibe un ancho
        # fijo, el resto cae al cálculo por contenido.
        _aplicar_anchos_columnas_new_ui(
            self.new_ui_table, cols_presentes, anchos_fijos={'RAZÓN SOCIAL': COMERCIAL_COL_WIDTH_RAZON_SOCIAL},
        )
        self._actualizar_estado_acciones_rapidas()

    def _toggle_acciones_rapidas_panel(self, index):
        """El panel de acciones comunes (acciones_rapidas_comunes) se
        muestra siempre; "Gestionar CM" agrega además "Confirmar baja"
        (acciones_rapidas_cm), "Vencidos" agrega "Marcar como Vencido"
        (acciones_rapidas_vencidos, 23-09-2026) y "Vigentes" agrega "Marcar
        como Vigente" (acciones_rapidas_vigentes, 24-09-2026), cada uno a
        continuación. Las demás sub-pestañas solo muestran las 4 acciones
        comunes.

        new_ui_table es compartida por las 6 sub-pestañas. Antes solo
        "Gestionar CM" permitía elegir varios VIN a la vez; ahora "Enviar
        correo" y "Enviar a operaciones" también deben soportar selección
        múltiple en todas, así que la selección extendida (Ctrl/Shift+clic)
        queda activa siempre, sin distinción por sub-pestaña."""
        if getattr(self, '_renovar_modo_activo', False):
            if index == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
                return
            self._set_modo_renovar(False)
        es_revision_cm = index == self._NEW_UI_SUBTAB_REVISION_CM
        es_vencidos = es_vigentes = index == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
        self.acciones_rapidas_cm.setVisible(es_revision_cm)
        self.acciones_rapidas_vencidos.setVisible(es_vencidos)
        self.acciones_rapidas_vigentes.setVisible(es_vigentes)
        self.acciones_rapidas_papelera.setVisible(index == self._NEW_UI_SUBTAB_POR_GESTIONAR)
        self.acciones_rapidas_inconsistencias.setVisible(
            index == self._NEW_UI_SUBTAB_AVISOS
            and bool(getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False)))
        self.new_ui_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def _actualizar_estado_acciones_rapidas(self):
        """Habilita/deshabilita las acciones rápidas según la cantidad de
        filas seleccionadas en new_ui_table, sin importar la sub-pestaña
        activa ni la fuente de datos (df_base o CasosBajaCM.csv): alcanza
        con el conteo de filas seleccionadas.

        - 0 seleccionadas: todo deshabilitado.
        - 1 seleccionada: todo habilitado.
        - Varias seleccionadas: "Enviar correo" y "Enviar a operaciones" se
          habilitan (soportan múltiples VIN); "Editar Unidad" y "Agregar
          contacto" se deshabilitan (aplican a una sola unidad/CDB a la
          vez -- ver conversación con el usuario, fases 3 y 4).

        "Enviar a operaciones" queda además siempre deshabilitado en "Por
        gestionar" y "Gestionar CM" (ver _NEW_UI_SUBTAB_POR_GESTIONAR /
        _NEW_UI_SUBTAB_REVISION_CM): en "Por gestionar" el camino correcto
        es Editar Unidad; en "Gestionar CM" ya existe "Confirmar baja". En
        "Ofrecer y reactivar" (28-09-2026, a pedido explícito) queda
        deshabilitado salvo que la tarjeta KPI "Aún Conectada" sea el
        filtro activo de esa sub-pestaña (unidades que todavía no se
        desconectaron físicamente y a las que tiene sentido reofrecer el
        servicio).

        "Confirmar baja" sigue exclusivo de "Gestionar CM", pero además
        (28-09-2026, a pedido explícito) solo se habilita si TODAS las
        filas seleccionadas son casos ORIGEN_CASO = Ausencia de 3PC: el
        equipo no decide la baja de un contrato Expired, solo avisa (ver
        "Exportar lista" y docs/07).

        "Agregar contacto" además cambia de color según si el CDB del VIN
        seleccionado ya tiene contacto en contactos.xlsx (ver
        _cdb_tiene_contacto/_aplicar_estilo_agregar_contacto): azul si
        tiene, rojo si no, neutro si no hay exactamente un VIN
        seleccionado."""
        n_seleccionadas = len(self.new_ui_table.selectionModel().selectedRows())
        self.btn_accion_cm_enviar_correo.setEnabled(n_seleccionadas >= 1)
        self.btn_accion_editar_unidad.setEnabled(n_seleccionadas == 1)
        self.btn_accion_agregar_contacto.setEnabled(n_seleccionadas == 1)

        subtab_activa = getattr(self, '_new_ui_active_subtab', 0)
        activa_por_gestionar = subtab_activa == self._NEW_UI_SUBTAB_POR_GESTIONAR
        activa_cm = subtab_activa == self._NEW_UI_SUBTAB_REVISION_CM
        activa_ofrecer_reactivar = subtab_activa == self._NEW_UI_SUBTAB_OFRECER_REACTIVAR
        filtro_conectada_activo = self._new_ui_kpi_filtro_por_subtab.get(subtab_activa) == 'conectadas'
        permite_ofrecer_reactivar = not activa_ofrecer_reactivar or filtro_conectada_activo
        self.btn_accion_enviar_operaciones.setEnabled(
            n_seleccionadas >= 1 and not activa_por_gestionar and not activa_cm and permite_ofrecer_reactivar
        )
        if activa_por_gestionar:
            tooltip_enviar_operaciones = "No corresponde en \"Por gestionar\": usa \"Editar contrato\", que ya deriva la unidad a Operaciones."
        elif activa_cm:
            tooltip_enviar_operaciones = "No corresponde en \"Gestionar CM\": usa \"Confirmar baja\"."
        elif activa_ofrecer_reactivar and not filtro_conectada_activo:
            tooltip_enviar_operaciones = "Filtra por la tarjeta \"Aún Conectada\" para habilitar esta acción en \"Ofrecer y reactivar\"."
        else:
            tooltip_enviar_operaciones = ""
        self.btn_accion_enviar_operaciones.setToolTip(tooltip_enviar_operaciones)
        self.btn_accion_enviar_operaciones.setVisible(not activa_ofrecer_reactivar)

        vins_seleccion, casos_seleccion = self._obtener_vins_seleccionados() if n_seleccionadas >= 1 else ([], {})
        self._actualizar_acciones_contrato_cerrado(vins_seleccion if n_seleccionadas == 1 else [])
        self._actualizar_ficha_unidad(vins_seleccion)
        self._mostrar_panel_acciones(n_seleccionadas >= 1)

        if n_seleccionadas == 1:
            cdb, _ = self._resolver_cdb_razon_social(vins_seleccion[0]) if vins_seleccion else ('', '')
            self._aplicar_estilo_agregar_contacto(self._cdb_tiene_contacto(cdb) if cdb else False)
        else:
            self._aplicar_estilo_agregar_contacto(None)

        confirmar_baja_permitido = False
        tooltip_confirmar_baja = ""
        if activa_cm and n_seleccionadas >= 1:
            confirmar_baja_permitido = bool(casos_seleccion) and all(
                str(fila.get('ORIGEN_CASO', '')).strip().upper() == cm_bajas_service.ORIGEN_CASO_AUSENCIA_3PC
                for fila in casos_seleccion.values()
            )
            if not confirmar_baja_permitido:
                tooltip_confirmar_baja = "Confirmar baja solo aplica a casos de Ausencia de 3PC. Para Expired, usa \"Exportar lista\"."
        self.btn_accion_cm_confirmar_baja.setEnabled(confirmar_baja_permitido)
        self.btn_accion_cm_confirmar_baja.setToolTip(tooltip_confirmar_baja)

        self._actualizar_boton_marcar_vencido()
        self._actualizar_boton_marcar_vigente()
        self._actualizar_boton_renovar()
        self._actualizar_boton_papelera()
        self._actualizar_boton_arreglar_tipo_fact()
        self._renovar_actualizar_seleccion()

    def _estados_contrato_actual(self, vin):
        """(ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL) del contrato actual de `vin` en df_base."""
        df = self.legacy.df_base
        if df is None or df.empty or 'VIN' not in df.columns:
            return '', ''
        fila = df[df['VIN'].astype(str).str.strip().str.upper() == str(vin).strip().upper()]
        if fila.empty:
            return '', ''
        fila = fila.iloc[0]
        return str(fila.get(COL_ESTADO_COMERCIAL, '')), str(fila.get(COL_ESTADO_ACTIVACION, ''))

    def _actualizar_acciones_contrato_cerrado(self, vins):
        """Un contrato en Baja o Baja Solicitada está finalizado: en vez de
        "Editar Unidad" se ofrecen "Ver en General" y "Crear contrato" (este
        último solo si la matriz de nuevo contrato lo permite)."""
        cerrado, puede = False, False
        if len(vins) == 1:
            estado, activacion = self._estados_contrato_actual(vins[0])
            cerrado = comercial_services.es_contrato_cerrado(estado)
            puede = comercial_services.puede_crear_contrato(estado, activacion)
        self.btn_accion_editar_unidad.setVisible(not cerrado)
        self.btn_accion_ver_general.setVisible(cerrado)
        self.btn_accion_ver_general.setEnabled(cerrado)
        self.btn_accion_crear_contrato.setVisible(cerrado)
        self.btn_accion_crear_contrato.setEnabled(cerrado and puede)
        self.btn_accion_crear_contrato.setToolTip(
            "" if puede or not cerrado else
            "La unidad sigue Activando o Conectada: no se puede crear otro contrato todavía.")

    def _on_accion_ver_general_clicked(self):
        vins, _ = self._obtener_vins_seleccionados()
        if len(vins) != 1:
            return
        abrir = getattr(self.window(), 'abrir_unidad_en_general', None)
        if abrir is not None:
            abrir(vins[0])

    def _on_accion_crear_contrato_clicked(self):
        """Abre "Unidad nueva" en modo "Nuevo contrato" con los datos de la
        unidad y del cliente; las condiciones comerciales quedan en blanco."""
        vins, _ = self._obtener_vins_seleccionados()
        if len(vins) != 1:
            return
        estado, activacion = self._estados_contrato_actual(vins[0])
        if not comercial_services.puede_crear_contrato(estado, activacion):
            return
        df = self.legacy.df_base
        fila = df[df['VIN'].astype(str).str.strip().str.upper() == vins[0].strip().upper()].iloc[0]
        self._iniciar_nuevo_contrato({col: ('' if pd.isna(val) else str(val)) for col, val in fila.items()})

    def _filas_renovables_seleccionadas(self):
        """{vin: fila} de la selección actual que se puede renovar (ver
        comercial_services.calcular_renovacion). Solo en "Renovar contratos"."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            return {}
        _, filas_por_vin = self._obtener_vins_seleccionados()
        return {vin: fila for vin, fila in filas_por_vin.items() if comercial_services.calcular_renovacion(fila, 1)}

    def _actualizar_boton_renovar(self):
        self.btn_accion_renovar.setEnabled(bool(self._filas_renovables_seleccionadas()))

    def _on_accion_renovar_clicked(self):
        """"Renovar contrato": el panel derecho pasa a un formulario (meses y
        contratos a renovar) en vez de abrir una ventana aparte."""
        if not self._filas_renovables_seleccionadas():
            return
        self._set_modo_renovar(True)
        self._renovar_actualizar_seleccion()

    def _set_modo_renovar(self, activo):
        self._renovar_modo_activo = activo
        self.panel_renovar.setVisible(activo)
        self._titulo_acciones.setVisible(not activo)
        self.acciones_rapidas_comunes.setVisible(not activo)
        if activo:
            for w in (self.acciones_rapidas_cm, self.acciones_rapidas_vencidos,
                      self.acciones_rapidas_vigentes, self.acciones_rapidas_papelera,
                      self.acciones_rapidas_inconsistencias):
                w.hide()
        else:
            self._ficha_contenedor.show()

    def _salir_modo_renovar(self):
        self._set_modo_renovar(False)
        self._toggle_acciones_rapidas_panel(getattr(self, '_new_ui_active_subtab', 0))

    def _build_new_ui_panel_renovar(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(10)
        estilo_tarjeta = (
            f"QFrame#tarjetaRenovar {{ background-color: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; "
            "border-radius: 12px; } QFrame#tarjetaRenovar QLabel { background: transparent; border: none; }")

        cabecera = QHBoxLayout()
        cabecera.setSpacing(8)
        self.btn_renovar_volver = QPushButton()
        self.btn_renovar_volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color=estilo_com.APAGADO))
        self.btn_renovar_volver.setFixedSize(28, 28)
        self.btn_renovar_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_renovar_volver.setToolTip("Volver a las acciones rápidas")
        self.btn_renovar_volver.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        self.btn_renovar_volver.clicked.connect(self._salir_modo_renovar)
        self.lbl_renovar_titulo = QLabel("Renovar contrato")
        self.lbl_renovar_titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 14px; font-weight: 800;")
        cabecera.addWidget(self.btn_renovar_volver)
        cabecera.addWidget(self.lbl_renovar_titulo)
        cabecera.addStretch()
        lay.addLayout(cabecera)

        tarjeta_meses = QFrame()
        tarjeta_meses.setObjectName("tarjetaRenovar")
        tarjeta_meses.setStyleSheet(estilo_tarjeta)
        lay_meses = QVBoxLayout(tarjeta_meses)
        lay_meses.setContentsMargins(12, 10, 12, 12)
        lay_meses.setSpacing(8)
        lay_meses.addWidget(self._titulo_seccion("Meses a extender"))
        qss_paso = (f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; "
                    f"border-radius: 10px; color: {estilo_com.PRIMARIO}; font-size: 18px; font-weight: 700; }}"
                    f"QPushButton:hover {{ border: 1px solid {estilo_com.PRIMARIO}; }}")
        fila_meses = QHBoxLayout()
        fila_meses.setSpacing(8)
        self.btn_renovar_menos = QPushButton("−")
        self.btn_renovar_mas = QPushButton("+")
        for btn in (self.btn_renovar_menos, self.btn_renovar_mas):
            btn.setFixedSize(38, 38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(qss_paso)
        self.spin_renovar_meses = QSpinBox()
        self.spin_renovar_meses.setRange(1, 120)
        self.spin_renovar_meses.setValue(12)
        self.spin_renovar_meses.setSuffix(" meses")
        self.spin_renovar_meses.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_renovar_meses.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_renovar_meses.setFixedHeight(38)
        self.spin_renovar_meses.setStyleSheet(
            f"QSpinBox {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.PRIMARIO}; "
            f"border-radius: 10px; color: {estilo_com.TINTA}; font-size: 16px; font-weight: 700; }}")
        self.btn_renovar_menos.clicked.connect(lambda: self.spin_renovar_meses.stepBy(-1))
        self.btn_renovar_mas.clicked.connect(lambda: self.spin_renovar_meses.stepBy(1))
        fila_meses.addWidget(self.btn_renovar_menos)
        fila_meses.addWidget(self.spin_renovar_meses, stretch=1)
        fila_meses.addWidget(self.btn_renovar_mas)
        lay_meses.addLayout(fila_meses)

        fila_atajos = QHBoxLayout()
        fila_atajos.setSpacing(6)
        self._chips_renovar = {}
        qss_chip = (f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; "
                    f"border-radius: 12px; padding: 3px 12px; color: {estilo_com.APAGADO}; font-weight: 600; font-size: 11px; }}"
                    f"QPushButton:checked {{ background-color: {estilo_com.PRIMARIO_SUAVE}; color: {estilo_com.PRIMARIO}; "
                    f"border: 1px solid {estilo_com.PRIMARIO}; }}")
        for meses in (6, 12, 24, 36):
            chip = QPushButton(str(meses))
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(qss_chip)
            chip.clicked.connect(lambda _c=False, m=meses: self.spin_renovar_meses.setValue(m))
            fila_atajos.addWidget(chip)
            self._chips_renovar[meses] = chip
        fila_atajos.addStretch()
        lay_meses.addLayout(fila_atajos)
        lay.addWidget(tarjeta_meses)

        self.tarjeta_renovar_cambios = QFrame()
        self.tarjeta_renovar_cambios.setObjectName("tarjetaRenovar")
        self.tarjeta_renovar_cambios.setStyleSheet(estilo_tarjeta)
        lay_cambios = QVBoxLayout(self.tarjeta_renovar_cambios)
        lay_cambios.setContentsMargins(12, 10, 12, 12)
        lay_cambios.setSpacing(8)
        self.lbl_renovar_cambios_titulo = self._titulo_seccion("Lo que va a cambiar")
        lay_cambios.addWidget(self.lbl_renovar_cambios_titulo)
        self.chk_renovar_todas = QCheckBox("Seleccionar todas")
        qss_casilla = (f"::indicator {{ width: 16px; height: 16px; border: 1px solid {estilo_com.APAGADO}; "
                       f"border-radius: 4px; background: {estilo_com.SUPERFICIE}; }}"
                       f"::indicator:checked {{ background: {estilo_com.PRIMARIO}; border: 1px solid {estilo_com.PRIMARIO}; }}")
        self.chk_renovar_todas.setStyleSheet(
            f"QCheckBox {{ color: {estilo_com.TINTA}; font-weight: 700; font-size: 12px; background: transparent; spacing: 8px; }}"
            f"QCheckBox{qss_casilla}")
        self.chk_renovar_todas.clicked.connect(self._renovar_marcar_todas)
        lay_cambios.addWidget(self.chk_renovar_todas)
        self.lista_renovar = QListWidget()
        self.lista_renovar.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.lista_renovar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lista_renovar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.lista_renovar.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{ border-bottom: 1px solid {estilo_com.LINEA}; padding: 6px 2px; color: {estilo_com.TINTA}; font-size: 11px; }}"
            f"QListWidget{qss_casilla}")
        self.lista_renovar.itemChanged.connect(self._renovar_item_cambiado)
        lay_cambios.addWidget(self.lista_renovar)
        self.lbl_renovar_detalle = QLabel("")
        self.lbl_renovar_detalle.setWordWrap(True)
        self.lbl_renovar_detalle.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_renovar_detalle.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px;")
        lay_cambios.addWidget(self.lbl_renovar_detalle)
        lay.addWidget(self.tarjeta_renovar_cambios)

        self.lbl_renovar_omitidos = QLabel("")
        self.lbl_renovar_omitidos.setWordWrap(True)
        self.lbl_renovar_omitidos.setStyleSheet(
            f"background-color: #FFF1D6; color: {estilo_com.AMBAR}; border-radius: 10px; padding: 8px 10px; "
            "font-size: 11px; font-weight: 600;")
        lay.addWidget(self.lbl_renovar_omitidos)

        self.btn_renovar_confirmar = QPushButton("Renovar contrato")
        self.btn_renovar_confirmar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_renovar_confirmar.setMinimumHeight(40)
        self.btn_renovar_confirmar.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR)
        self.btn_renovar_confirmar.clicked.connect(self._on_renovar_confirmar_clicked)
        self.btn_renovar_cancelar = QPushButton("Cancelar")
        self.btn_renovar_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_renovar_cancelar.setMinimumHeight(40)
        self.btn_renovar_cancelar.setStyleSheet(
            f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 10px; "
            f"color: {estilo_com.APAGADO}; font-weight: 700; font-size: 13px; }}"
            f"QPushButton:hover {{ border: 1px solid {estilo_com.PRIMARIO}; color: {estilo_com.PRIMARIO}; }}")
        self.btn_renovar_cancelar.clicked.connect(self._salir_modo_renovar)
        lay.addWidget(self.btn_renovar_confirmar)
        lay.addWidget(self.btn_renovar_cancelar)

        self.spin_renovar_meses.valueChanged.connect(self._renovar_actualizar_vista)
        return panel

    @staticmethod
    def _texto_renovar(valor):
        texto = '' if valor is None else str(valor).strip()
        return '-' if texto.upper() in ('', 'NAN', 'NONE', 'NAT') else texto

    def _renovar_cambio_de_fila(self, fila, meses):
        """(duración, término, estado) antes y después de renovar `fila`."""
        cambios = comercial_services.calcular_renovacion(fila, meses) or {}
        estado = self._texto_renovar(fila.get(COL_ESTADO_COMERCIAL)).capitalize()
        return (
            (self._texto_renovar(fila.get('DURACIÓN (MESES)')), cambios.get('DURACIÓN (MESES)', '-')),
            (self._texto_renovar(fila.get('TÉRMINO CONTRATO')), cambios.get('TÉRMINO CONTRATO', '-')),
            (estado, cambios.get(COL_ESTADO_COMERCIAL, estado).capitalize()),
        )

    def _renovar_actualizar_seleccion(self):
        """Rearma la lista con la selección actual de la tabla. Conserva las
        marcas ya hechas; sin contratos renovables vuelve a las acciones."""
        if not getattr(self, '_renovar_modo_activo', False):
            return
        vins, _ = self._obtener_vins_seleccionados()
        renovables = self._filas_renovables_seleccionadas()
        if not renovables:
            self._salir_modo_renovar()
            return
        previas = {self.lista_renovar.item(i).data(Qt.ItemDataRole.UserRole):
                   self.lista_renovar.item(i).checkState() for i in range(self.lista_renovar.count())}
        self._renovar_filas = renovables
        self.lista_renovar.blockSignals(True)
        self.lista_renovar.clear()
        for vin, fila in renovables.items():
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, vin)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(previas.get(vin, Qt.CheckState.Checked))
            self.lista_renovar.addItem(item)
        self.lista_renovar.blockSignals(False)

        varios = len(renovables) > 1
        self._ficha_contenedor.setVisible(len(vins) == 1)
        self.lbl_renovar_titulo.setText("Renovar contratos" if varios else "Renovar contrato")
        self.lbl_renovar_cambios_titulo.setText("Contratos a renovar" if varios else "Lo que va a cambiar")
        self.chk_renovar_todas.setVisible(varios)
        self.lista_renovar.setVisible(varios)
        self.lbl_renovar_detalle.setVisible(True)
        omitidos = len(vins) - len(renovables)
        self.lbl_renovar_omitidos.setVisible(omitidos > 0)
        if omitidos > 0:
            self.lbl_renovar_omitidos.setText(
                f"{omitidos} de las filas seleccionadas no se pueden renovar (por ejemplo, duración MENSUAL) y se dejan igual.")
        self._renovar_actualizar_vista()

    def _renovar_actualizar_vista(self, *_):
        """Recalcula textos con los meses elegidos: atajos, lista, resumen y botón."""
        if not getattr(self, '_renovar_modo_activo', False) or not self._renovar_filas:
            return
        meses = self.spin_renovar_meses.value()
        for valor, chip in self._chips_renovar.items():
            chip.setChecked(valor == meses)
        marcados = 0
        self.lista_renovar.blockSignals(True)
        for i in range(self.lista_renovar.count()):
            item = self.lista_renovar.item(i)
            vin = item.data(Qt.ItemDataRole.UserRole)
            fila = self._renovar_filas.get(vin)
            if fila is None:
                continue
            _duracion, (termino_antes, termino_despues), _estado = self._renovar_cambio_de_fila(fila, meses)
            item.setText(f"{self._texto_renovar(fila.get(COL_RAZON_SOCIAL))} · {self._texto_renovar(fila.get(COL_CHASIS))}"
                         f"\n{termino_antes} → {termino_despues}")
            item.setSizeHint(QSize(0, 46))
            if item.checkState() == Qt.CheckState.Checked:
                marcados += 1
        self.lista_renovar.blockSignals(False)
        total = len(self._renovar_filas)
        self.lista_renovar.setFixedHeight(min(total, 4) * 46 + 4)
        self.chk_renovar_todas.blockSignals(True)
        self.chk_renovar_todas.setChecked(marcados == total)
        self.chk_renovar_todas.blockSignals(False)

        if total == 1:
            (dur_antes, dur_despues), (ter_antes, ter_despues), (est_antes, est_despues) = \
                self._renovar_cambio_de_fila(next(iter(self._renovar_filas.values())), meses)
            tachado = f"color:{estilo_com.APAGADO}; text-decoration:line-through;"
            self.lbl_renovar_detalle.setText(
                "<table cellspacing='4'>"
                f"<tr><td style='color:{estilo_com.APAGADO}'>Duración</td><td><span style='{tachado}'>{dur_antes} meses</span> → <b>{dur_despues} meses</b></td></tr>"
                f"<tr><td style='color:{estilo_com.APAGADO}'>Término</td><td><span style='{tachado}'>{ter_antes}</span> → <b>{ter_despues}</b></td></tr>"
                f"<tr><td style='color:{estilo_com.APAGADO}'>Estado</td><td><span style='{tachado}'>{est_antes}</span> → <b>{est_despues}</b></td></tr>"
                "</table>")
        else:
            self.lbl_renovar_detalle.setText(f"Se suman {meses} meses a {marcados} de {total} contratos.")
        if total == 1:
            self.btn_renovar_confirmar.setText("Renovar contrato")
        else:
            self.btn_renovar_confirmar.setText(f"Renovar {marcados} contrato(s)")
        self.btn_renovar_confirmar.setEnabled(marcados >= 1)

    def _renovar_item_cambiado(self, _item):
        self._renovar_actualizar_vista()

    def _renovar_marcar_todas(self, marcar):
        self.lista_renovar.blockSignals(True)
        for i in range(self.lista_renovar.count()):
            self.lista_renovar.item(i).setCheckState(Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
        self.lista_renovar.blockSignals(False)
        self._renovar_actualizar_vista()

    def _on_renovar_confirmar_clicked(self):
        filas = {}
        for i in range(self.lista_renovar.count()):
            item = self.lista_renovar.item(i)
            vin = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked and vin in self._renovar_filas:
                filas[vin] = self._renovar_filas[vin]
        if filas:
            self._ejecutar_renovacion(filas, self.spin_renovar_meses.value())

    def _ejecutar_renovacion(self, filas, meses):
        """Suma `meses` a DURACIÓN (MESES) de los contratos elegidos; el
        término se recalcula y el contrato conserva su ID."""
        self._salir_modo_renovar()
        valid = {}
        for vin, fila in filas.items():
            cambios = comercial_services.calcular_renovacion(fila, meses)
            if cambios.get(COL_ESTADO_COMERCIAL):
                row_para_matriz = {
                    COL_ESTADO_COMERCIAL: cambios[COL_ESTADO_COMERCIAL].capitalize(),
                    COL_ESTADO_ACTIVACION: fila.get(COL_ESTADO_ACTIVACION, ''),
                    COL_TIPO_FACTURACION: fila.get(COL_TIPO_FACTURACION, ''),
                    COL_ETAPA_GESTION: fila.get(COL_ETAPA_GESTION, ''),
                }
                cambios[COL_ETAPA_GESTION] = DataFrameFormatter.calcular_etapa_gestion_esperada(row_para_matriz)
                cambios[COL_ESTADO_COMERCIAL] = cambios[COL_ESTADO_COMERCIAL].capitalize()
            valid[vin] = {'VIN': vin, 'cambios': cambios}
        comercial_services.agregar_id_a_cambios(valid, self.legacy.df_base)

        self.btn_accion_renovar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Renovando contratos…")
        self._renovar_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._renovar_thread.finished_signal.connect(lambda success: self._on_renovar_finished(success, valid))
        self._renovar_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._renovar_thread.start()

    def _on_renovar_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self, "No se pudo guardar la renovación. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()
        self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self, texto_exito="Contratos renovados")
        QMessageBox.information(self, "Renovación", f"Se renovó {len(valid)} contrato(s).")

    def _unidades_pendientes_marcar_vencido(self, df_bandeja):
        # Solo unidades que cumplen la regla de Vencidos (fecha vencida o ya
        # marcadas) y cuyo ESTADO COMERCIAL es corregible a Vencido.
        if df_bandeja is None or df_bandeja.empty or COL_ESTADO_COMERCIAL not in df_bandeja.columns:
            return df_bandeja.iloc[0:0] if df_bandeja is not None else pd.DataFrame()
        estado = df_bandeja[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
        en_vencidos = df_bandeja.index.isin(comercial_services.filtrar_vencidos(df_bandeja).index)
        es_provision_mas = pd.Series(False, index=df_bandeja.index)
        for col in (COL_TIPO_FACTURACION, COL_FORMA_CONTRATO):
            if col in df_bandeja.columns:
                es_provision_mas |= df_bandeja[col].astype(str).str.strip().str.upper() == 'PROVISION +'
        return df_bandeja[estado.isin(ESTADOS_COMERCIAL_CORREGIBLES_A_VENCIDO) & en_vencidos & ~es_provision_mas]

    def _pendientes_marcar_vencido_seleccionados(self):
        """Subconjunto de las filas seleccionadas que se pueden marcar como
        Vencido (fecha expirada y estado corregible). Las demás filas
        seleccionadas se ignoran."""
        df_bandeja = getattr(self, '_new_ui_bandeja_actual_df', None)
        if df_bandeja is None or df_bandeja.empty or 'VIN' not in df_bandeja.columns:
            return pd.DataFrame()
        vins_seleccion, _ = self._obtener_vins_seleccionados()
        if not vins_seleccion:
            return df_bandeja.iloc[0:0]
        df_pendientes = self._unidades_pendientes_marcar_vencido(df_bandeja)
        vin_norm = df_pendientes['VIN'].astype(str).str.strip().str.upper()
        return df_pendientes[vin_norm.isin(set(vins_seleccion))]

    def _unidad_vigente_en_curso(self, vin):
        # Vigente / Activación Pendiente y con contrato aún no vencido por
        # fecha: el caso que antes vivía en "Vigentes" (baja anticipada,
        # edición restringida).
        df_base = getattr(self.legacy, 'df_base', None)
        if df_base is None or df_base.empty or 'VIN' not in df_base.columns:
            return False
        pos = self._posicion_vin_en_df(df_base, vin)
        if pos is None:
            return False
        fila = df_base.iloc[[pos]]
        return not comercial_services.filtrar_vigentes(fila).empty and comercial_services.filtrar_vencidos(fila).empty

    def _actualizar_boton_marcar_vencido(self):
        """"Marcar como Vencido" se habilita solo si, estando en "Renovar
        clientes", hay al menos una fila seleccionada con fecha de término
        expirada y ESTADO COMERCIAL corregible a Vencido. Se llama tanto
        desde _actualizar_estado_acciones_rapidas (cambios de
        selección/sub-pestaña) como desde _refresh_new_ui_data (cambios de
        datos: búsqueda, guardado, recarga)."""
        activa_vencidos = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
        hay_pendientes = activa_vencidos and not self._pendientes_marcar_vencido_seleccionados().empty
        self.btn_accion_marcar_vencido.setEnabled(hay_pendientes)

    def _actualizar_boton_marcar_vigente(self):
        """"Marcar como Vigente" no depende de la selección de la tabla (ver
        _build_new_ui_acciones_rapidas_solo_vigentes): se habilita solo si,
        estando en "Vigentes", la bandeja actual tiene al menos un vehículo
        con ESTADO COMERCIAL = "Activación Pendiente" Y ESTADO DE
        ACTIVACIÓN ACTUAL = "Conectado". Mismo patrón que
        _actualizar_boton_marcar_vencido."""
        activa_vigentes = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
        hay_pendientes = False
        if activa_vigentes:
            df_bandeja = getattr(self, '_new_ui_bandeja_actual_df', None)
            if df_bandeja is not None and not df_bandeja.empty and \
               COL_ESTADO_COMERCIAL in df_bandeja.columns and COL_ESTADO_ACTIVACION in df_bandeja.columns:
                estado_com = df_bandeja[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
                estado_act = df_bandeja[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
                hay_pendientes = bool((
                    (estado_com == VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE) & (estado_act == ESTADO_CONECTADO)
                ).any())
        self.btn_accion_marcar_vigente.setEnabled(activa_vigentes and hay_pendientes)

    def _construir_df_revision_cm(self):
        """Bandeja de "Revisión CM": casos PENDIENTE de CasosBajaCM.csv (ver
        cm_bajas_service.py), sin importar su ORIGEN_CASO -- incluye tanto
        VIN que tenían datos CM y dejaron de aparecer en el Excel mensual
        de 3PC (AUSENCIA_3PC) como VIN cuyo contrato pasó a ESTADO DEL CM =
        'Expired' (ESTADO_EXPIRED). No incluye REAPARECIDO (el caso ya se
        resolvió solo: el VIN reapareció en el 3PC, o el contrato dejó de
        estar Expired), MANTENIDO ni CONFIRMADA_BAJA (decisiones ya tomadas
        por la contraparte comercial: se respetan y no vuelven a esta bandeja).

        Agrega "MOTIVO" (texto amigable de ORIGEN_CASO, ver
        cm_bajas_service.ORIGEN_CASO_MOTIVO_MAP) para que la pestaña
        distinga el motivo de revisión sin exponer el valor técnico.

        No toca CasosBajaCM.csv ni PruebasFM: solo lee."""
        df_casos = cm_bajas_service.leer_casos_baja_cm(config.settings.CASOS_BAJA_CM_PATH)
        if df_casos.empty:
            return df_casos
        df_pendientes = df_casos[df_casos['ESTADO_CASO'] == cm_bajas_service.ESTADO_CASO_PENDIENTE].copy()
        df_pendientes['MOTIVO'] = df_pendientes['ORIGEN_CASO'].map(
            cm_bajas_service.ORIGEN_CASO_MOTIVO_MAP
        ).fillna(df_pendientes['ORIGEN_CASO'])
        return df_pendientes

    _TEXTO_TODOS_PERIODOS = "Todos los periodos"

    @staticmethod
    def _clave_orden_periodo(texto):
        """'Septiembre - 2026' -> (2026, 9) para ordenar del más reciente al más antiguo."""
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        mes, _, anio = str(texto).partition('-')
        mes, anio = mes.strip().lower(), anio.strip()
        return (int(anio) if anio.isdigit() else 0, meses.index(mes) + 1 if mes in meses else 0)

    @classmethod
    def _etiqueta_periodo(cls, texto):
        """'septiembre - 2026' -> 'Septiembre 2026'; otros valores se muestran capitalizados."""
        mes, _, anio = str(texto).partition('-')
        if anio.strip().isdigit():
            return f"{mes.strip().capitalize()} {anio.strip()}"
        return str(texto).strip().capitalize()

    def _sincronizar_combo_periodo_interno(self, df_base):
        """Ofrece los PERIODO INTERNO presentes agrupados por año (más reciente
        primero) y, al final, los valores que no son una fecha."""
        if df_base is None or 'PERIODO INTERNO' not in df_base.columns:
            periodos = []
        else:
            serie = df_base['PERIODO INTERNO'].dropna().astype(str).str.strip().str.lower()
            periodos = sorted({p for p in serie.unique() if p and p not in ('-', 'nan')},
                              key=self._clave_orden_periodo, reverse=True)
        if periodos == self.__dict__.get('_periodos_combo'):
            return
        self._periodos_combo = periodos
        por_anio, otros = {}, []
        for p in periodos:
            anio = self._clave_orden_periodo(p)[0]
            if anio:
                por_anio.setdefault(anio, []).append((p, self._etiqueta_periodo(p)))
            else:
                otros.append((p, self._etiqueta_periodo(p)))
        grupos = [(str(anio), items) for anio, items in por_anio.items()]
        if otros:
            grupos.append(("Otros", otros))
        self.combo_periodo_interno.set_opciones(grupos)

    def _on_periodo_interno_cambiado(self, _valor):
        self._refresh_new_ui_data()

    def _df_base_por_periodo(self, df_base):
        """df_base restringido al periodo elegido; el resultado se reutiliza
        mientras no cambien df_base ni el periodo, para no invalidar la caché
        de filtros por sub-pestaña."""
        self._sincronizar_combo_periodo_interno(df_base)
        periodo = self.combo_periodo_interno.valor()
        if df_base is None or periodo is None or 'PERIODO INTERNO' not in df_base.columns:
            return df_base
        origen, periodo_cache, filtrado = self._periodo_interno_df
        if origen is df_base and periodo_cache == periodo:
            return filtrado
        filtrado = df_base[df_base['PERIODO INTERNO'].astype(str).str.strip().str.lower() == periodo]
        self._periodo_interno_df = (df_base, periodo, filtrado)
        return filtrado

    def _filtrar_subtab_con_cache(self, subtab, df_base):
        """Filtro de negocio de la sub-pestaña, recordado mientras df_base sea
        el mismo objeto (solo se reasigna al recargar/guardar) y el día no
        cambie, para que alternar sub-pestañas no refiltre todo cada vez."""
        filtro = self._NEW_UI_SUBTAB_FILTERS.get(subtab)
        if filtro is None:
            return df_base
        clave = (datetime.now().date(), len(df_base))
        cache = self.__dict__.get('_cache_filtro_subtab')
        if cache is None or cache[0] is not df_base or cache[1] != clave:
            cache = (df_base, clave, {})
            self.__dict__['_cache_filtro_subtab'] = cache
        if subtab not in cache[2]:
            cache[2][subtab] = filtro(df_base)
        return cache[2][subtab]

    def _on_correos_registrados(self):
        """Un correo recién registrado cambia los KPI de contacto de
        "Recuperar clientes": se repinta al instante si esa pestaña está a la
        vista (si no, se actualiza al volver a ella)."""
        try:
            if self.new_ui_tab.isVisible() and getattr(self, '_new_ui_active_subtab', 0) in (1, 2, 3):
                self._refresh_new_ui_data()
        except Exception:
            pass

    def _on_data_ready_refrescar_new_ui(self):
        """Conectada a data_manager.data_ready (DataManager es singleton,
        ver __new__ en data_manager.py): como la señal es compartida entre
        instancias, un ComercialModule ya destruido a nivel C++ (ej. el de
        un test anterior) puede seguir conectado cuando otra instancia
        posterior emite data_ready, y llamar a _refresh_new_ui_data sobre
        widgets ya eliminados (o con datos que ya no calzan con lo que esa
        instancia vieja espera) puede lanzar cualquier excepción -- mismo
        riesgo y mismo patrón de defensa (except Exception genérico) que
        _on_global_data_ready en _ComercialModuleLegacy (más arriba).

        Si la pestaña no está visible no se repinta: al volver a ella,
        _on_new_ui_tab_refresh_if_dirty/_on_internal_tab_changed ya la
        refrescan (y con self.legacy.df_base al día)."""
        try:
            if not self.new_ui_tab.isVisible():
                return
            self._refresh_new_ui_data()
        except Exception:
            pass

    def _refresh_new_ui_data(self):
        """Repinta KPIs y bandeja de la Nueva interfaz con los datos que
        _ComercialModuleLegacy ya tiene cargados (self.legacy.df_base), sin
        pedirle nada nuevo a DataManager ni duplicar la carga. La bandeja se
        filtra por la regla de negocio de la sub-pestaña activa (ver
        _NEW_UI_SUBTAB_FILTERS), despues por el texto de busqueda (local o
        el que haya dejado MainWindow._on_global_search en
        new_ui_search_input) sobre los datos completos, y solo al final se
        recorta a las columnas configuradas para esa sub-pestaña
        (NEW_UI_SUBTAB_COLUMNS) -- asi una columna oculta como VIN sigue
        siendo buscable aunque no se muestre."""
        active_subtab = getattr(self, '_new_ui_active_subtab', 0)
        self._actualizar_boton_marcar_vencidos_barra()
        self.lbl_titulo_bandeja.setText(
            "Avisos de gestión" if active_subtab == self._NEW_UI_SUBTAB_AVISOS
            else self._NEW_UI_SUBTAB_NOMBRES[active_subtab]
        )
        if active_subtab == self._NEW_UI_SUBTAB_AVISOS:
            # Las tarjetas KPI conservan los valores de la sub-pestaña real
            self._refresh_bandeja_avisos()
            return
        columnas = self.NEW_UI_SUBTAB_COLUMNS.get(active_subtab, self.NEW_UI_SUBTAB_COLUMNS[0])
        self._aplicar_kpi_spec_actual(active_subtab)
        self._actualizar_seleccion_visual_kpi(active_subtab)

        df_base = self._df_base_por_periodo(getattr(self.legacy, 'df_base', None))
        self._actualizar_contadores_subtabs(df_base)
        if df_base is None or df_base.empty:
            self._salir_vista_agrupada()
            self.new_ui_model.set_data(pd.DataFrame(columns=columnas))
            self._new_ui_revision_cm_df = pd.DataFrame()
            self._new_ui_bandeja_actual_df = pd.DataFrame()
            for lbl in self.new_ui_kpi_labels.values():
                lbl.setText("0")
            self._actualizar_barras_kpi({})
            self._actualizar_estado_acciones_rapidas()
            return

        # "Revisión CM" no sale de df_base (PruebasFM): sale de
        # CasosBajaCM.csv, con su propio esquema de columnas (ver
        # _construir_df_revision_cm), y no tiene TÉRMINO CONTRATO -- no
        # encaja en el contrato "filtro(df_base) -> subset de df_base" de
        # _NEW_UI_SUBTAB_FILTERS ni en calcular_kpis_vigencia(), asi que se
        # resuelve aparte y se corta la funcion aqui.
        if active_subtab == self._NEW_UI_SUBTAB_REVISION_CM:
            df_bandeja = self._construir_df_revision_cm()

            search_text = self.new_ui_search_input.text().strip().lower()
            if search_text and not df_bandeja.empty:
                mascara = comercial_services.construir_mascara_busqueda(df_bandeja, search_text, COLUMNAS_BUSQUEDA_REVISION_CM)
                df_bandeja = df_bandeja[mascara]

            # Los KPI de vigencia (vencidas/activas/x-vencer) no aplican a
            # esta bandeja: no hay TÉRMINO CONTRATO en CasosBajaCM.csv (ver
            # comercial_services.calcular_kpis_gestionar_cm, desglose por
            # ORIGEN_CASO y PAGO CM en riesgo).
            razones_cm = self._razones_contactadas_por_correo()
            kpis_cm = comercial_services.calcular_kpis_gestionar_cm(df_bandeja, razones_cm)
            for key, lbl in self.new_ui_kpi_labels.items():
                lbl.setText(str(kpis_cm.get(key, 0)))
            self._actualizar_barras_kpi(kpis_cm)

            # Las tarjetas conservan sus cifras al filtrar: el filtro por
            # tarjeta se aplica después de calcularlas.
            filtro_cm = self._new_ui_kpi_filtro_por_subtab.get(active_subtab)
            if filtro_cm and filtro_cm != 'total' and not df_bandeja.empty:
                masks_cm = comercial_services.obtener_masks_kpi_gestionar_cm(df_bandeja, razones_cm)
                if filtro_cm in masks_cm:
                    df_bandeja = df_bandeja[masks_cm[filtro_cm]]

            df_bandeja, columnas_vista, en_grupos = self._preparar_vista_agrupada(active_subtab, df_bandeja, columnas)
            df_bandeja = self.new_ui_table.apply_sort(df_bandeja).reset_index(drop=True)
            # Guardado completo (con VIN y CASO_ID, aunque no se muestren)
            # para que _on_accion_cm_confirmar_baja_clicked pueda resolver
            # la fila seleccionada del modelo (que solo recibe las columnas
            # visibles) a su caso real. El orden coincide con el que recibe
            # el modelo porque se guarda justo antes de recortar columnas.
            self._new_ui_revision_cm_df = pd.DataFrame() if en_grupos else df_bandeja
            self._new_ui_grupos_df = df_bandeja if en_grupos else None
            cols_presentes = [c for c in columnas_vista if c in df_bandeja.columns]
            df_mostrar = df_bandeja[cols_presentes].copy()
            # Solo presentación: PAGO CM llega como texto crudo desde
            # CasosBajaCM.csv (ej. '15000'). _new_ui_revision_cm_df (arriba)
            # guarda el valor original -- _on_accion_cm_confirmar_baja_clicked
            # y el CSV no se ven afectados por este formateo.
            if 'PAGO CM' in df_mostrar.columns:
                df_mostrar['PAGO CM'] = df_mostrar['PAGO CM'].apply(_formatear_pago_cm_para_mostrar)
            self.new_ui_model.set_data(df_mostrar)
            _aplicar_anchos_columnas_new_ui(
                self.new_ui_table, cols_presentes,
                anchos_fijos=self._anchos_vista_grupos(cols_presentes) if en_grupos else NEW_UI_SUBTAB_COLUMN_WIDTHS.get(active_subtab),
            )
            self._actualizar_estado_acciones_rapidas()
            return

        df_bandeja = self._filtrar_subtab_con_cache(active_subtab, df_base)

        # Filtro por tarjeta KPI clicada (28-09-2026, a pedido explícito,
        # reemplaza el antiguo filtro de botones "Todos/Vigente/Vencido/
        # Activación Pendiente" exclusivo de "Vencidos"): se aplica DESPUÉS
        # del filtro de negocio de la sub-pestaña, nunca lo reemplaza -- ver
        # _NEW_UI_KPI_MASK_FUNCS/_on_new_ui_kpi_card_clicked. "Renovaciones"
        # es la única sub-pestaña cuyas máscaras necesitan además
        # contactos.xlsx (tarjeta "Sin contactos").
        kwargs_extra_kpi = {}
        if active_subtab in (1, 2):
            kwargs_extra_kpi['razones_contactadas'] = self._razones_contactadas_por_correo()
        mask_func = self._NEW_UI_KPI_MASK_FUNCS.get(active_subtab)
        filtro_key = self._new_ui_kpi_filtro_por_subtab.get(active_subtab)
        if mask_func is not None and filtro_key and filtro_key != 'total':
            masks = mask_func(df_bandeja, **kwargs_extra_kpi)
            if filtro_key in masks:
                df_bandeja = df_bandeja[masks[filtro_key]]

        search_text = self.new_ui_search_input.text().strip().lower()
        if search_text:
            mascara = comercial_services.construir_mascara_busqueda(
                df_bandeja, search_text, COLUMNAS_BUSQUEDA_COMERCIAL, COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL)
            df_bandeja = df_bandeja[mascara]

        # KPI dinamicos: se recalculan sobre la bandeja ya filtrada por
        # sub-pestaña, tarjeta clicada y busqueda, no sobre df_base completo,
        # para que reflejen inmediatamente los datos de la vista activa.
        # Cada sub-pestaña usa su propia función (ver _NEW_UI_KPI_FUNCS /
        # comercial_services.py, sección "KPI POR SUB-PESTAÑA") en vez de
        # calcular_kpis_vigencia para todas -- esta última no tiene sentido
        # fuera de "Renovaciones"/"Vencidos".
        kpi_func = self._NEW_UI_KPI_FUNCS.get(active_subtab, comercial_services.calcular_kpis_vigencia)
        kpis = kpi_func(df_bandeja, **kwargs_extra_kpi)
        for key, lbl in self.new_ui_kpi_labels.items():
            lbl.setText(str(kpis.get(key, 0)))
        self._actualizar_barras_kpi(kpis)

        if "DÍAS RESTANTES" in columnas:
            clasif = comercial_services.clasificar_vigencia_contrato(df_bandeja)
            df_bandeja = df_bandeja.copy()
            df_bandeja["DÍAS RESTANTES"] = clasif["dias_restantes"].apply(comercial_services.formatear_dias_restantes)

            # Orden por defecto (config aprobada con el usuario) mientras no
            # haya un orden manual activo (ver AppTableWidget.
            # has_active_sort/apply_sort, más abajo). El bloque de "por
            # vencer" (no vencido) siempre va primero, ordenado por el que
            # vence más pronto. El bloque de "ya vencido" va al final,
            # siempre con el más vencido primero (_NEW_UI_VENCIDOS_
            # RECIENTES_PRIMERO queda vacío desde que se eliminó la
            # sub-pestaña "Vencimientos"). Un clic en "Ordenar A -> Z" del
            # encabezado reemplaza todo esto por el orden genérico numérico
            # ascendente (ver comercial_services.parsear_dias_restantes y
            # AppTableWidget._parse_number_like).
            if not self.new_ui_table.has_active_sort():
                mask_vencido = clasif['vencido']
                recientes_primero = active_subtab in self._NEW_UI_VENCIDOS_RECIENTES_PRIMERO

                df_por_vencer = df_bandeja[~mask_vencido].assign(_dias=clasif['dias_restantes'][~mask_vencido]) \
                    .sort_values('_dias', na_position='last').drop(columns='_dias')
                df_vencido = df_bandeja[mask_vencido].assign(_dias=clasif['dias_restantes'][mask_vencido]) \
                    .sort_values('_dias', ascending=not recientes_primero, na_position='last').drop(columns='_dias')

                df_bandeja = pd.concat([df_por_vencer, df_vencido])

        bandeja_completa = df_bandeja
        df_bandeja, columnas_vista, en_grupos = self._preparar_vista_agrupada(active_subtab, df_bandeja, columnas)
        df_bandeja = self.new_ui_table.apply_sort(df_bandeja)
        self._new_ui_grupos_df = df_bandeja if en_grupos else None

        # Guardado completo (con VIN, aunque no se muestre) para que
        # _obtener_vins_seleccionados pueda resolver la fila seleccionada
        # del modelo (que solo recibe las columnas visibles) a su VIN real
        # en "Por gestionar"/"Renovaciones"/"Gestionar Bajas" -- mismo
        # mecanismo que _new_ui_revision_cm_df para "Gestionar CM". El
        # orden coincide con el que recibe el modelo porque se guarda justo
        # antes de recortar columnas.
        # En la vista de grupos no hay filas-unidad: las acciones masivas
        # ("Marcar como Vencido/Vigente") siguen viendo toda la bandeja.
        self._new_ui_bandeja_actual_df = bandeja_completa if en_grupos else df_bandeja

        cols_presentes = [c for c in columnas_vista if c in df_bandeja.columns]
        self.new_ui_model.set_data(df_bandeja[cols_presentes])
        _aplicar_anchos_columnas_new_ui(
            self.new_ui_table, cols_presentes,
            anchos_fijos=self._anchos_vista_grupos(cols_presentes) if en_grupos else NEW_UI_SUBTAB_COLUMN_WIDTHS.get(active_subtab),
        )
        self._actualizar_estado_acciones_rapidas()

    def _cdbs_por_razon_actual(self):
        """CDB comerciales distintos de cada RAZÓN SOCIAL sobre toda la base;
        se recalcula solo cuando cambia df_base."""
        df = getattr(self.legacy, 'df_base', None)
        cache = self.__dict__.get('_cache_cdbs_por_razon')
        if cache is None or cache[0] is not df or cache[1] != (0 if df is None else len(df)):
            cache = (df, 0 if df is None else len(df), comercial_services.cdbs_por_razon_social(df))
            self.__dict__['_cache_cdbs_por_razon'] = cache
        return cache[2]

    def _cdb_referencia_actual(self):
        """CDB más frecuente por RAZÓN SOCIAL sobre toda la base (no solo la
        bandeja); se recalcula solo cuando cambia df_base."""
        df = getattr(self.legacy, 'df_base', None)
        cache = self.__dict__.get('_cache_cdb_referencia')
        if cache is None or cache[0] is not df or cache[1] != (0 if df is None else len(df)):
            cache = (df, 0 if df is None else len(df), comercial_services.cdb_referencia_por_razon_social(df))
            self.__dict__['_cache_cdb_referencia'] = cache
        return cache[2]

    def _razones_contactadas_por_correo(self):
        """Clientes con correo enviado en la ventana de contacto (ver
        comercial_services.DIAS_VENTANA_CONTACTO_CORREO); se vuelve a leer
        el historial solo si cambió el archivo o el día."""
        from src.services import mail_registro
        ruta = mail_registro.get_historial_csv_path()
        try:
            mtime = os.path.getmtime(ruta)
        except OSError:
            mtime = None
        clave = (ruta, mtime, datetime.now().date())
        cache = self.__dict__.get('_cache_razones_contactadas')
        if cache is None or cache[0] != clave:
            razones = comercial_services.obtener_razones_contactadas_por_correo(mail_registro.leer_historial())
            cache = (clave, razones)
            self.__dict__['_cache_razones_contactadas'] = cache
        return cache[1]

    def _actualizar_contadores_subtabs(self, df_base):
        """Unidades de cada sub-pestaña junto a su nombre (sin búsqueda ni
        filtro de tarjeta)."""
        hay_datos = df_base is not None and not df_base.empty
        for i, nombre in enumerate(self._NEW_UI_SUBTAB_NOMBRES):
            n = 0
            if hay_datos:
                try:
                    if i == self._NEW_UI_SUBTAB_REVISION_CM:
                        n = self._contar_casos_cm()
                    else:
                        n = len(self._filtrar_subtab_con_cache(i, df_base))
                except Exception:
                    n = 0
            badge = self._badges_subtabs[i]
            if badge.text() != str(n):
                badge.setText(str(n))
                badge.setFixedWidth(max(34, badge.fontMetrics().horizontalAdvance(str(n)) + 24))
                self.new_ui_subtabs.setTabText(i, nombre)

    def _estilizar_badges_subtabs(self, *_):
        actual = self.new_ui_subtabs.currentIndex()
        for i, badge in enumerate(self._badges_subtabs):
            fondo, texto = ("#E3E8F0", "#1B2B4E") if i == actual else ("#EEF2F6", estilo_com.APAGADO)
            badge.setStyleSheet(
                f"background-color: {fondo}; color: {texto}; border-radius: 10px; "
                "padding: 0px 8px; font-size: 11px; font-weight: bold; min-width: 10px;"
            )

    def _contar_casos_cm(self):
        ruta = config.settings.CASOS_BAJA_CM_PATH
        try:
            mtime = os.path.getmtime(ruta)
        except OSError:
            mtime = None
        cache = self.__dict__.get('_cache_contador_cm')
        if cache is None or cache[0] != (ruta, mtime):
            cache = ((ruta, mtime), len(self._construir_df_revision_cm()))
            self.__dict__['_cache_contador_cm'] = cache
        return cache[1]

    def _clave_grupo_new_ui(self, subtab):
        return 'RAZÓN SOCIAL' if subtab in self._NEW_UI_SUBTABS_AGRUPADAS_POR_RAZON_SOCIAL else 'FLOTA VC'

    def _preparar_vista_agrupada(self, subtab, df, columnas):
        """Devuelve (df, columnas, en_grupos) según el estado de agrupación
        de la sub-pestaña: con un grupo abierto filtra sus unidades y deja
        las columnas normales; sin grupo abierto resume una fila por
        FLOTA VC (o RAZÓN SOCIAL en "Por gestionar") con su cantidad de
        unidades."""
        clave = self._clave_grupo_new_ui(subtab)
        abierto = self._new_ui_grupo_abierto.get(subtab)
        if clave not in df.columns:
            self._actualizar_barra_grupo(None)
            self._new_ui_en_grupos = False
            self.lbl_grupo_abierto.setText(f"{len(df)} unidades")
            return df, columnas, False

        sin_dato = self._NEW_UI_VALOR_SIN_GRUPO
        serie = df[clave].fillna('').astype(str).str.strip()
        serie = serie.mask(serie.str.upper().isin(['', 'NAN', 'NONE', 'NAT', '-', '<NA>']), sin_dato)

        if abierto is not None:
            self._actualizar_barra_grupo(clave, abierto)
            self._new_ui_en_grupos = False
            self.new_ui_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            df_grupo = df[serie == abierto]
            self.lbl_grupo_abierto.setText(f"{len(df_grupo)} unidades · {clave}: {abierto}")
            return df_grupo, columnas, False

        self._actualizar_barra_grupo(None)
        self._new_ui_en_grupos = True
        self.new_ui_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        col_unidades = self._NEW_UI_COL_UNIDADES
        grupos = df.assign(_grupo=serie).groupby('_grupo', sort=True)
        resumen = pd.DataFrame({clave: grupos.size().index, col_unidades: grupos.size().values})
        sustantivo = "clientes" if clave == 'RAZÓN SOCIAL' else "flotas"
        self.lbl_grupo_abierto.setText(f"{len(df)} unidades en {len(resumen)} {sustantivo}")
        columnas_vista = [clave]
        if subtab == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            idx = df.index
            masks = comercial_services.obtener_masks_kpi_renovar_clientes(df)
            conteos = pd.DataFrame({
                '_g': serie.values,
                'VENCEN EN 30 DÍAS': masks['por_vencer'].values,
                'VIGENTES': masks['vigentes'].values,
                'UNIDADES VENCIDAS': masks['vencidas'].values,
            }).groupby('_g', sort=True).sum()
            for col in ('VENCEN EN 30 DÍAS', 'VIGENTES', 'UNIDADES VENCIDAS'):
                resumen[col] = conteos[col].astype(int).values
            resumen['TOTAL UNIDADES'] = resumen.pop(col_unidades)
            orden = [clave, 'UNIDADES VENCIDAS', 'VENCEN EN 30 DÍAS', 'VIGENTES', 'TOTAL UNIDADES']
            return resumen[orden], orden, True
        if clave != 'RAZÓN SOCIAL' and 'RAZÓN SOCIAL' in df.columns:
            def _razon(s):
                valores = {str(v).strip() for v in s if str(v).strip() and str(v).strip().upper() != 'NAN'}
                return next(iter(valores)) if len(valores) == 1 else (f"Varios clientes ({len(valores)})" if valores else sin_dato)
            resumen['RAZÓN SOCIAL'] = grupos['RAZÓN SOCIAL'].agg(_razon).values
            columnas_vista.append('RAZÓN SOCIAL')
        if subtab == self._NEW_UI_SUBTAB_POR_GESTIONAR:
            # Todos los CDB comerciales del cliente (no solo los de la bandeja)
            if 'RUT' in df.columns:
                def _ruts(s):
                    valores = list(dict.fromkeys(str(v).strip() for v in s if str(v).strip().upper() not in ('', 'NAN', 'NONE', '-')))
                    return ", ".join(valores) or "-"
                resumen['RUT'] = grupos['RUT'].agg(_ruts).values
                columnas_vista.append('RUT')
            cdbs = self._cdbs_por_razon_actual()
            resumen['CDB COMERCIAL'] = [", ".join(cdbs.get(r, [])) or "-" for r in resumen[clave]]
            columnas_vista.append('CDB COMERCIAL')
        columnas_vista.append(col_unidades)
        return resumen, columnas_vista, True

    def _anchos_vista_grupos(self, columnas):
        # Reparte el ancho visible: la columna clave (y RAZÓN SOCIAL si está)
        # toman más espacio y las numéricas se reparten el resto por igual.
        total = max(self.new_ui_table.viewport().width(), 900)
        pesos = {c: (3.0 if c == 'RAZÓN SOCIAL' else 3.2 if i == 0 else 2.2 if c == 'CDB COMERCIAL' else 1.0)
                 for i, c in enumerate(columnas)}
        suma = sum(pesos.values())
        return {c: max(NEW_UI_COL_WIDTH_MINIMO, int(total * p / suma)) for c, p in pesos.items()}
    def _salir_vista_agrupada(self):
        self._actualizar_barra_grupo(None)
        self._new_ui_en_grupos = False
        self._new_ui_grupos_df = None
        self.lbl_grupo_abierto.setText("")
        self.new_ui_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def _actualizar_barra_grupo(self, clave, abierto=None):
        self.btn_volver_grupos.setVisible(clave is not None)

    def _on_new_ui_fila_clicada(self, index):
        if not self._new_ui_en_grupos or self._new_ui_grupos_df is None:
            return
        subtab = getattr(self, '_new_ui_active_subtab', 0)
        clave = self._clave_grupo_new_ui(subtab)
        fila = index.row()
        if fila < 0 or fila >= len(self._new_ui_grupos_df) or clave not in self._new_ui_grupos_df.columns:
            return
        self._new_ui_grupo_abierto[subtab] = str(self._new_ui_grupos_df.iloc[fila][clave])
        self._refresh_new_ui_data()

    def _on_volver_a_grupos_clicked(self):
        self._new_ui_grupo_abierto.pop(getattr(self, '_new_ui_active_subtab', 0), None)
        self._refresh_new_ui_data()

    def __getattr__(self, name):
        legacy = self.__dict__.get('legacy')
        if legacy is not None and hasattr(legacy, name):
            return getattr(legacy, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __setattr__(self, name, value):
        if name in ComercialModule._OWN_ATTRS or 'legacy' not in self.__dict__:
            super().__setattr__(name, value)
        else:
            setattr(self.legacy, name, value)

    def __delattr__(self, name):
        # unittest.mock.patch.object() restaura vía delattr (no setattr)
        # cuando el atributo parcheado no vivia en el __dict__ propio del
        # target -- que es siempre el caso aqui, porque __setattr__ ya lo
        # reenvia a self.legacy. Sin este espejo, ese delattr fallaria con
        # AttributeError contra el contenedor en vez de limpiar en legacy.
        if name in ComercialModule._OWN_ATTRS or 'legacy' not in self.__dict__:
            super().__delattr__(name)
        else:
            delattr(self.legacy, name)