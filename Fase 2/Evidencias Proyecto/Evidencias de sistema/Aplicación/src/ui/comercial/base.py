"""Hilos de guardado, constantes de columnas y ayudas de la bandeja de Comercial."""
from src.theme.colors import BORDER, PRIMARY, SURFACE
from PyQt6.QtCore import QThread, pyqtSignal, QEvent, QObject
from PyQt6.QtGui import QFontMetrics
from src.services import comercial_services
from src.core.constants import COL_ID
import logging


logger = logging.getLogger(__name__)


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
    # desactualizado hasta presionar "Recargar". No se emite si el guardado
    # fallo o si la relectura del CSV fallo.
    logs_actualizados_signal = pyqtSignal(object)

    def __init__(self, writer, changes, module_name="Sistema", contratos_nuevos=None):
        super().__init__()
        self.writer = writer
        self.changes = changes
        self.module_name = module_name
        self.contratos_nuevos = contratos_nuevos or []

    def run(self):
        success = self.writer.update_cells(self.changes, module_name=self.module_name)
        if success and self.contratos_nuevos:
            success = self.writer.add_new_rows_batch(self.contratos_nuevos, module_name=self.module_name)
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


class AddRowsThread(QThread):
    """Agrega varias unidades nuevas con un solo guardado. Emite (se_guardaron, filas)."""
    finished_signal = pyqtSignal(bool, list)

    def __init__(self, writer, filas, module_name="Sistema"):
        super().__init__()
        self.writer = writer
        self.filas = filas
        self.module_name = module_name

    def run(self):
        ok = bool(self.writer.add_new_rows_batch(self.filas, module_name=self.module_name))
        self.finished_signal.emit(ok, self.filas)


class AddRowRenovacionThread(QThread):
    """Agrega el contrato nuevo y, si se guardó, marca el anterior (por ID) como
    Renovado. Emite (se_agregó_el_nuevo, se_actualizó_el_anterior, datos_nuevos)."""
    finished_signal = pyqtSignal(bool, bool, dict)

    def __init__(self, writer, new_data, vin, id_anterior, cambios_anterior, module_name="Sistema"):
        super().__init__()
        self.writer = writer
        self.new_data = new_data
        self.vin = vin
        self.id_anterior = id_anterior
        self.cambios_anterior = cambios_anterior
        self.module_name = module_name

    def run(self):
        agregado = self.writer.add_new_row(self.new_data, module_name=self.module_name)
        anterior = False
        if agregado:
            anterior = self.writer.update_cells(
                {self.vin: {'VIN': self.vin, 'ID': self.id_anterior, 'cambios': self.cambios_anterior}},
                module_name=self.module_name)
        self.finished_signal.emit(agregado, anterior, self.new_data)


class AddRowsRenovacionThread(QThread):
    """Renovación de varias unidades: por cada una agrega el contrato nuevo y marca el anterior
    (por ID) como Renovado. Emite (lista de {'nuevo', 'vin', 'id_anterior', 'cambios_anterior',
    'anterior_ok'} de los que sí se agregaron, total pedido)."""
    finished_signal = pyqtSignal(list, int)

    def __init__(self, writer, renovaciones, module_name="Sistema"):
        super().__init__()
        self.writer = writer
        self.renovaciones = renovaciones
        self.module_name = module_name

    def run(self):
        # Dos guardados en total (contratos nuevos y contratos anteriores): reescribir el archivo
        # una vez por unidad llenaba de copias de conflicto a OneDrive
        hechos = []
        if self.writer.add_new_rows_batch([r['nuevo'] for r in self.renovaciones], module_name=self.module_name):
            anteriores = {
                r['vin']: {'VIN': r['vin'], 'ID': r['id_anterior'], 'cambios': r['cambios_anterior']}
                for r in self.renovaciones if r['cambios_anterior']}
            anterior_ok = bool(self.writer.update_cells(anteriores, module_name=self.module_name)) if anteriores else True
            hechos = [{**r, 'anterior_ok': anterior_ok} for r in self.renovaciones]
        self.finished_signal.emit(hechos, len(self.renovaciones))


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


# Columnas donde busca el texto libre de la barra global de MainWindow
# (ver ComercialModule._refresh_new_ui_data).
# RUT agregado 28-09-2026, a pedido explicito.
COLUMNAS_BUSQUEDA_COMERCIAL = ['VIN', 'CHASIS', 'FLOTA VC', 'FLOTA VC 2', 'CDB', 'CDB FLOTA', 'RAZÓN SOCIAL', 'RUT']


# N° Contrato (ID): solo calza por igualdad exacta, ver construir_mascara_busqueda
COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL = [COL_ID]


# Columnas donde busca el texto libre de la sub-pestaña "Revisión CM" (ver
# ComercialModule._construir_df_revision_cm). Distinta de
# COLUMNAS_BUSQUEDA_COMERCIAL porque esta bandeja no lee df_base (PruebasFM),
# sino CasosBajaCM.csv (cm_bajas_service), que trae su propio VIN/CHASIS.
COLUMNAS_BUSQUEDA_REVISION_CM = ['RAZÓN SOCIAL', 'CHASIS', 'VIN', 'N CONTRATO 3PC']


# Ancho (px) de RAZÓN SOCIAL en las tablas de Comercial, para mostrarla completa sin truncar
COMERCIAL_COL_WIDTH_RAZON_SOCIAL = 300


# Ancho mínimo (px) que se le respeta a cualquier columna de new_ui_table al
# redistribuir anchos (ver ComercialModule._on_new_ui_header_resized): evita
# que una columna quede en 0px (invisible) cuando se comprime para hacerle
# espacio a otra que el usuario ensanchó a mano.
NEW_UI_COL_WIDTH_MINIMO = 60


# Columnas de texto largo: se muestran completas en varias líneas y la fila crece (VolvoTableWidget.set_columnas_ajuste_texto).
COMERCIAL_COLUMNAS_AJUSTE_TEXTO = ['RAZÓN SOCIAL', 'FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ACTIVACIÓN ACTUAL']


# Alto de fila de la bandeja de la Nueva interfaz (23-09-2026, a pedido
# explícito): con el alto estándar (38px, VolvoTableWidget._setup_style) una
# razón social larga se cortaba salvo que se ensanchara la columna a mano.
# En vez de eso, la fila se hace más alta y RAZÓN SOCIAL se muestra con
# ajuste de línea (ver _build_new_ui_bandeja) para verla completa sin tocar
# el ancho. Se aplica solo a new_ui_table (y su frozen_view, ver
# VolvoTableWidget._setup_frozen_view) -- no a VolvoTableWidget en general,
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
    2: {'RAZÓN SOCIAL': 380, 'CHASIS': 85, 'MODELO': 90, 'FORMA DE CONTRATO': 129},
    0: {'RAZÓN SOCIAL': 286, 'CHASIS': 90, 'MODELO': 90, 'TIPO DE SERVICIO': 130, 'FORMA DE CONTRATO': 130, 'INICIO CONTRATO': 105, 'TÉRMINO CONTRATO': 105, 'ESTADO COMERCIAL': 140},
    1: {'RAZÓN SOCIAL': 383, 'CHASIS': 90, 'MODELO': 90, 'TIPO DE SERVICIO': 130, 'ESTADO DE ACTIVACIÓN ACTUAL': 170},
    3: {'GESTIÓN': 125, 'ACTIVACIÓN': 125, 'ESTADO COMERCIAL': 130, 'CHASIS': 90, 'FECHA INICIO CM': 120,
        'FECHA TERMINO CM': 135, 'TIPO DE CM': 95, 'ESTADO DEL CM': 115, 'PAGO CM': 100, 'ULTIMO PAGO CM': 125,
        'FECHA ULTIMO PAGO CM': 150},
}


class _FiltroAnchoViewport(QObject):
    """Avisa cada vez que cambia el ancho útil de la tabla (menú lateral,
    barra de desplazamiento, ventana) para reacomodar sus columnas."""

    def __init__(self, tabla, al_cambiar):
        super().__init__(tabla)
        self._al_cambiar = al_cambiar

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Type.Resize:
            self._al_cambiar()
        return False


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
