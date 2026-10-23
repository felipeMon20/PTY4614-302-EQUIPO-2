import pandas as pd
import qtawesome as qta
import os
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QPushButton, QMessageBox, QLineEdit, QMenu, QApplication,
                             QHeaderView, QDialog, QTabWidget, QListWidget, QListWidgetItem, QWidgetAction,
                             QStackedWidget, QProgressBar, QFileDialog)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QColor, QFont

from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.hilos import iniciar_hilo_retenido
from src.theme.theme_manager import ThemeManager
from src.ui.custom_table import VolvoTableWidget, PandasTableModel
from src.ui import admin_estilo, comercial_estilo as estilo_com
from src.ui.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando, crear_tarjeta_carga
from src.ui.contactos_agregar import ContactosAddDialog
from src.ui.dialogo_accion import DialogoAccion
from src.ui.esqueleto_carga import animar_sobre_tabla
from src.theme import tema
from src.services import contactos_service, powerbi_cache_service
import config.settings
from config.settings import POWERBI_EXCEL_PATH
from src.theme.colors import BACKGROUND, SUCCESS, TEXT_PRIMARY, TEXT_SECONDARY, SURFACE, BORDER, PRIMARY, DANGER

_COLUMNAS_VALIDADAS = ('Nombre', 'Apellidos', 'Correo electrónico', 'Número móvil')
_FONDO_INVALIDO = '#FEE2E2'

# =========================================================
# HILOS DE TRABAJO ASÍNCRONO (CRUD CONTACTOS)
# =========================================================
class SaveContactosThread(QThread):
    finished_signal = pyqtSignal(bool)

    def __init__(self, writer, changes):
        super().__init__()
        self.writer = writer
        self.changes = changes

    def run(self):
        success = self.writer.update_cells(self.changes, module_name="Contactos", custom_filepath=config.settings.CONTACTOS_EXCEL_PATH)
        self.finished_signal.emit(success)

class AddContactoThread(QThread):
    finished_signal = pyqtSignal(bool, dict)
    
    def __init__(self, writer, new_data):
        super().__init__()
        self.writer = writer
        self.new_data = new_data
        
    def run(self):
        success = self.writer.add_new_row(self.new_data, module_name="Contactos", custom_filepath=config.settings.CONTACTOS_EXCEL_PATH)
        self.finished_signal.emit(success, self.new_data)

class ImportarContactosThread(QThread):
    finished_signal = pyqtSignal(bool, int)

    def __init__(self, writer, lote):
        super().__init__()
        self.writer = writer
        self.lote = lote

    def run(self):
        success = self.writer.add_new_rows_batch(
            self.lote, module_name="Contactos (Importación)", custom_filepath=config.settings.CONTACTOS_EXCEL_PATH)
        self.finished_signal.emit(success, len(self.lote))

class DeleteContactoThread(QThread):
    finished_signal = pyqtSignal(bool, dict)
    
    def __init__(self, writer, keys_dict):
        super().__init__()
        self.writer = writer
        self.keys_dict = keys_dict
        
    def run(self):
        success = self.writer.delete_row(module_name="Contactos", custom_filepath=config.settings.CONTACTOS_EXCEL_PATH, keys_dict=self.keys_dict)
        self.finished_signal.emit(success, self.keys_dict)

# =========================================================
# WORKER: Sincronizador de Power BI (David)
# =========================================================
class PowerBiSyncWorker(QThread):
    log_signal = pyqtSignal(str)          
    preview_signal = pyqtSignal(object) 
    error_signal = pyqtSignal(str)        

    def __init__(self, df_comercial):
        super().__init__()
        self.df_comercial = df_comercial

    def run(self):
        try:
            if not POWERBI_EXCEL_PATH or not os.path.exists(POWERBI_EXCEL_PATH):
                raise Exception("La ruta de 'BBDD CLIENTES CM' no está configurada o el archivo no existe.\nVe a Configuración para enlazar el archivo de David.")

            self.log_signal.emit("[SISTEMA] Leyendo BBDD CLIENTES CM (cache CSV interno)...")
            df_bbdd = powerbi_cache_service.leer_bbdd_clientes_cm(POWERBI_EXCEL_PATH)
            
            cdbs_activos = self.df_comercial['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().unique().tolist()
            if 'CDB' not in df_bbdd.columns: 
                raise Exception("El archivo de David no tiene la columna 'CDB'. Verifica el formato.")
                
            self.log_signal.emit("[CRUZANDO] Limpiando decimales fantasma y filtrando base gigante...")
            
            df_bbdd['CDB'] = df_bbdd['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
            df_filtrado = df_bbdd[df_bbdd['CDB'].isin(cdbs_activos)].copy()
            
            self.log_signal.emit(f"[INFO] Rescatamos {len(df_filtrado)} empresas con contratos activos.")
            
            columnas_requeridas = ['CDB', 'Nombre', 'RUT', 'Teléfono', 'Correo electrónico', 'Dirección', 'Comuna', 'Categoría', 'Responsable']
            columnas_finales = [c for c in columnas_requeridas if c in df_filtrado.columns]
            
            df_final = df_filtrado[columnas_finales].drop_duplicates(subset=['CDB'])
            self.preview_signal.emit(df_final)

        except Exception as e:
            self.error_signal.emit(f"Error fatal: {str(e)}")

# =========================================================
# EL SÚPER-MÓDULO DE CONTACTOS (CRUD COMPLETO)
# =========================================================
class ContactosModule(QWidget):
    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        
        self.pending_changes = {} # Mochila temporal de ediciones en RAM
        # Fase 1 de la auditoria de rendimiento (17-09-2026): se evaluo un
        # guard de visibilidad como en general.py/comercial.py/contratos.py,
        # pero se revirtio -- a diferencia de data_ready/logs_updated,
        # contactos_ready solo lo dispara load_contactos_async(), que en la
        # practica solo llama este mismo modulo (self-triggered) o
        # general.py una unica vez al arranque si el df todavia esta vacio
        # (momento en que Contactos ni siquiera esta instanciado todavia).
        # No habia reprocesamiento oculto real que evitar.

        self.last_save_success = None
        self.last_add_success = None
        self.last_delete_success = None
        self.df_plataforma = pd.DataFrame()
        self.df_empresas = pd.DataFrame()

        # Controlan cuándo ocultar la pantalla de carga: se necesitan ambas
        # fuentes listas (contactos.xlsx y BBDD CLIENTES CM), ya que se piden
        # en paralelo mediante dos QThread independientes.
        self._plataforma_cargada = False
        self._empresas_cargada = False
        # Guard contra la creacion de un segundo PowerBiSyncWorker mientras
        # el anterior sigue corriendo (ver auditoria: cualquier CRUD exitoso
        # llama a load_data(), que puede solaparse con un Reload manual).
        self._empresas_loading = False

        self.search_input = QLineEdit()
        self.search_input.hide()
        
        self.filtered_plat = pd.DataFrame()
        self.filtered_emp = pd.DataFrame()
        
        self.pinned_file = os.path.join(os.getcwd(), 'config', 'pinned_contacts.json')
        self.pinned_contacts = self.load_pinned()
        
        self._filter_items = [] 
        # Administradores de flota: primero la lista de flotas (CDB, Flota) y, al
        # elegir una, sus contactos. None = lista de flotas.
        self._flota_abierta = None
        self.filtered_flotas = pd.DataFrame()
        
        self.data_manager.contactos_ready.connect(self._on_data_ready)
        self.data_manager.load_contactos_error.connect(self._on_load_error)
        self._data_dirty = False
        self._firma_cargada = None
        self.data_manager.data_ready.connect(self._marcar_dirty)

        self._setup_ui()
        self.table_plat.clicked.connect(self._on_table_plat_clicked)
        
        self.load_data(clear_pending=False)

    def load_pinned(self):
        return contactos_service.cargar_favoritos(self.pinned_file)

    def save_pinned(self):
        contactos_service.guardar_favoritos(self.pinned_file, self.pinned_contacts)

    def _normalize_id(self, val):
        """Normalización robusta y absoluta de IDs (soporta int, float, str, con o sin .0)."""
        return contactos_service.normalizar_id_contacto(val)

    def _migrate_pinned_contacts(self):
        """Convierte favoritos antiguos a IDs físicos permanentes de forma segura."""
        nuevos = contactos_service.migrar_favoritos_legacy(self.pinned_contacts, self.df_plataforma)
        if nuevos is not None:
            self.pinned_contacts = nuevos
            self.save_pinned()

    def _get_contact_key(self, row_data):
        """Extrae el ID físico limpio usando la normalización robusta."""
        return self._normalize_id(row_data.get('ID', ''))

    def _setup_ui(self):
        main_layout = admin_estilo.raiz_pantalla(self)

        contenedor_tabs, self.subtabs, self._badges = admin_estilo.subpestanas(
            ("Administradores de flotas", "Director de empresas"))
        main_layout.addWidget(contenedor_tabs)
        admin_estilo.animar_subpestanas(self, self.subtabs)

        self._barra = admin_estilo.barra_opciones('fa5s.address-book', "Contactos", "")
        main_layout.addWidget(self._barra.marco)

        # Filtro por flota/empresa: la lista con casillas vive en un menú
        self.lbl_filtro = admin_estilo.etiqueta_barra("Filtrar Flota:")
        self._barra.zona_filtros.addWidget(self.lbl_filtro)

        self.btn_volver = admin_estilo.boton_capsula(self._barra, 'fa5s.arrow-left', "Volver a la lista de flotas", QPushButton())
        self.btn_volver.clicked.connect(self._volver_a_flotas)

        self.btn_add = admin_estilo.boton_capsula(self._barra, 'fa5s.plus', "Agregar Nuevo Contacto", QPushButton())
        self.btn_add.clicked.connect(self._open_add_dialog)

        self.btn_importar = admin_estilo.boton_capsula(
            self._barra, 'fa5s.file-import', "Importar contactos nuevos desde el Excel del bot de Volvo Connect", QPushButton())
        self.btn_importar.clicked.connect(self._importar_contactos_bot)

        self.btn_save = admin_estilo.boton_capsula(self._barra, 'fa5s.save', "Guardar cambios", QPushButton())
        self.btn_save.clicked.connect(self.confirm_save)

        self.btn_corregir_tel = admin_estilo.boton_capsula(
            self._barra, 'fa5s.magic', "Corrige al formato +56 9 XXXX XXXX los números que se pueden arreglar solos",
            QPushButton())
        self.btn_corregir_tel.clicked.connect(self._corregir_telefonos)

        self.btn_filtro_lista = admin_estilo.boton_capsula(self._barra, 'fa5s.filter', "Filtrar", QPushButton(), grupo='filtros')
        self.btn_filtro_lista.setStyleSheet(self.btn_filtro_lista.styleSheet() + "QPushButton::menu-indicator { image: none; width: 0; }")

        self.menu_filtro = QMenu(self)
        self.menu_filtro.setStyleSheet(
            "QMenu { background-color: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 12px; padding: 6px; }")
        self.menu_filtro_widget = QWidget()
        self.menu_filtro_layout = QVBoxLayout(self.menu_filtro_widget)
        self.menu_filtro_layout.setContentsMargins(6, 6, 6, 6)
        self.menu_filtro_layout.setSpacing(8)

        btn_action_layout = QHBoxLayout()
        estilo_mini = (
            "QPushButton { background: #F7F9FC; color: #0F1B33; border: 1px solid #E3E8F0; border-radius: 9px; "
            "padding: 6px 12px; font-weight: 700; } QPushButton:hover { background: #E8F0FE; }")
        self.btn_check_all = QPushButton("Marcar Todos")
        self.btn_check_all.setStyleSheet(estilo_mini)
        self.btn_check_all.clicked.connect(lambda: self._set_all_filters(True))

        self.btn_uncheck_all = QPushButton("Desmarcar")
        self.btn_uncheck_all.setStyleSheet(estilo_mini)
        self.btn_uncheck_all.clicked.connect(lambda: self._set_all_filters(False))

        btn_action_layout.addWidget(self.btn_check_all)
        btn_action_layout.addWidget(self.btn_uncheck_all)

        self.list_filtros = QListWidget()
        self.list_filtros.setFixedSize(300, 300)
        self.list_filtros.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { padding: 6px 8px; border-radius: 8px; color: #0F1B33; }"
            "QListWidget::item:hover { background: #F1F4F9; }")
        self.menu_filtro_layout.addLayout(btn_action_layout)
        self.menu_filtro_layout.addWidget(self.list_filtros)

        self.action_filtro_widget = QWidgetAction(self.menu_filtro)
        self.action_filtro_widget.setDefaultWidget(self.menu_filtro_widget)
        self.menu_filtro.addAction(self.action_filtro_widget)
        self.btn_filtro_lista.setMenu(self.menu_filtro)

        self.btn_export_excel = admin_estilo.boton_capsula(self._barra, 'fa5s.file-excel', "Exportar Excel", QPushButton(), grupo='generales')
        self.btn_export_excel.clicked.connect(self._export_current_tab)

        self.btn_reload = admin_estilo.boton_capsula(self._barra, 'fa5s.sync-alt', "Recargar", QPushButton(), grupo='generales')
        # El botón explícito Recargar borra pending_changes pasando clear_pending=True
        self.btn_reload.clicked.connect(lambda: self.load_data(clear_pending=True))

        marco_tabla, capas_tabla = admin_estilo.tarjeta_contenido("tarjetaContactos")

        self.content_stack = QStackedWidget()

        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(
            crear_tarjeta_carga("Cargando directorio de contactos y empresas…", "Esto tomará unos segundos."),
            alignment=Qt.AlignmentFlag.AlignCenter)

        self.content_stack.addWidget(self.loading_widget)

        self.tabs = QTabWidget()

        # TABLA DE CONTACTOS (CRUD SIN PAGINACIÓN - MOSTRANDO ID REAL DEL EXCEL)
        self.table_plat = VolvoTableWidget()
        self.table_plat.menu_type = "contactos" 
        self.table_plat.action_eliminar.connect(self._handle_eliminar)
        self.table_plat.item_edited.connect(self.on_item_edited)
        
        self.model_plat = PandasTableModel(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        
        def custom_flags(index):
            col_name = self.model_plat._df.columns[index.column()]
            columnas_editables = ['Nombre', 'Apellidos', 'Correo electrónico', 'Número móvil']
            if col_name in columnas_editables:
                return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable
            return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            
        self.model_plat.flags = custom_flags
        
        original_data_method = getattr(self.model_plat.__class__, 'data') 
        def custom_data(index, role=Qt.ItemDataRole.DisplayRole):
            col_name = self.model_plat._df.columns[index.column()]
            if col_name == '★':
                is_pinned = self.model_plat._df.iat[index.row(), index.column()]
                if role == Qt.ItemDataRole.DecorationRole:
                    if is_pinned: return qta.icon('fa5s.star', color='#F59E0B') 
                    else: return qta.icon('fa5s.star', color='#D1D5DB') 
                elif role == Qt.ItemDataRole.DisplayRole: return ""
            if col_name in _COLUMNAS_VALIDADAS and role in (Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ToolTipRole):
                motivo = contactos_service.motivo_dato_invalido(col_name, self.model_plat._df.iat[index.row(), index.column()])
                if motivo:
                    if role == Qt.ItemDataRole.ToolTipRole:
                        return f"Dato inválido: {motivo}"
                    return tema.fondo(QColor(_FONDO_INVALIDO)) if tema.es_oscuro() else QColor(_FONDO_INVALIDO)
            if col_name == 'Fecha de extracción' and role == Qt.ItemDataRole.DisplayRole:
                return str(original_data_method(self.model_plat, index, role)).split(" ")[0]
            return original_data_method(self.model_plat, index, role)
            
        self.model_plat.data = custom_data
        self.table_plat.setModel(self.model_plat)
        admin_estilo.estilar_tabla(self.table_plat, editable=True)
        
        self.table_plat.customContextMenuRequested.disconnect()
        self.table_plat.customContextMenuRequested.connect(self._show_contactos_context_menu)
        self.table_plat.sort_changed.connect(self.filter_tables)

        # Lista de flotas (CDB, Flota): al hacer clic se muestran sus contactos
        self.table_flotas = VolvoTableWidget()
        self.table_flotas.menu_type = "general"
        self.table_flotas.sort_changed.connect(self.filter_tables)
        self.model_flotas = PandasTableModel(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.model_flotas.flags = lambda index: Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        self.table_flotas.setModel(self.model_flotas)
        admin_estilo.estilar_tabla(self.table_flotas)
        self.table_flotas.clicked.connect(self._abrir_flota)

        self.stack_plat = QStackedWidget()
        self.stack_plat.addWidget(self.table_flotas)
        self.stack_plat.addWidget(self.table_plat)
        self.tabs.addTab(self.stack_plat, "Administradores de flotas")
        self.stack_plat.search_input = self.search_input
        self.stack_plat.filter_tables = self.filter_tables
        self.table_flotas.search_input = self.search_input
        self.table_flotas.filter_tables = self.filter_tables
        # Mismo contrato que ComercialModule (ver new_ui_tab.search_input/
        # filter_table en comercial.py): main_window._get_active_submodule
        # desciende hasta tabs.currentWidget() cuando el módulo tiene 'tabs',
        # así que la pestaña activa necesita su propio search_input/
        # filter_tables para que el buscador global (Ctrl+F) le llegue.
        self.table_plat.search_input = self.search_input
        self.table_plat.filter_tables = self.filter_tables

        # TABLA DE BBDD DAVID
        self.table_emp = VolvoTableWidget()
        self.table_emp.menu_type = "general"  # directorio de solo lectura: sin "Eliminar Camión"
        self.table_emp.sort_changed.connect(self.filter_tables)
        self.model_emp = PandasTableModel(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.model_emp.flags = lambda index: Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        self.table_emp.setModel(self.model_emp)
        admin_estilo.estilar_tabla(self.table_emp)
        self.tabs.addTab(self.table_emp, "Director de empresas (Power BI)")
        self.table_emp.search_input = self.search_input
        self.table_emp.filter_tables = self.filter_tables

        admin_estilo.enlazar_tabs(self.subtabs, self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.content_stack.addWidget(self.tabs)
        capas_tabla.addWidget(self.content_stack, 1)
        main_layout.addWidget(marco_tabla, stretch=1)

    # ==========================================
    # LÓGICAS CRUD CON ID FÍSICO PERMANENTE
    # ==========================================
    def _open_add_dialog(self):
        dialog = ContactosAddDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_data = dialog.get_data()
            new_data['ID'] = contactos_service.generar_nuevo_id_contacto(self.df_plataforma)

            self.last_add_success = None
            self.btn_add.setEnabled(False)
            mostrar_guardando(self, "Agregando el contacto…")
            self.add_thread = AddContactoThread(self.writer, new_data)
            self.add_thread.finished_signal.connect(self._on_add_finished)
            self.add_thread.start()
            
    def _on_add_finished(self, success, new_data):
        self.last_add_success = success
        self.btn_add.setEnabled(True)
        if success:
            terminar_guardando(self, texto_exito="Contacto agregado")
            # Al agregar un nuevo registro sí recargamos de forma limpia
            self.load_data(clear_pending=True)
        else:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se pudo agregar el registro en SharePoint. Verifica si contactos.xlsx está abierto.")

    def _importar_contactos_bot(self):
        """Agrega a contactos.xlsx los administradores nuevos del Excel que genera el bot."""
        ruta, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar Excel del bot (Administradores de flota)", "", "Excel (*.xlsx)")
        if not ruta:
            return
        try:
            df_bot = contactos_service.leer_administradores_bot(ruta)
        except Exception as e:
            QMessageBox.critical(self, "No se pudo leer el Excel", str(e))
            return
        resultado = contactos_service.construir_contactos_nuevos(df_bot, self.df_plataforma)
        registros = resultado['registros']
        omitidos = []
        if resultado['existentes']:
            omitidos.append(f"{resultado['existentes']} ya estaban en contactos.xlsx (no se modifican)")
        if resultado['repetidos']:
            omitidos.append(f"{resultado['repetidos']} repetidos dentro del Excel")
        if resultado['incompletos']:
            omitidos.append(f"{resultado['incompletos']} sin CDB o sin nombre y correo")
        detalle = ("\n\nNo se importan:\n- " + "\n- ".join(omitidos)) if omitidos else ""
        if not registros:
            QMessageBox.information(self, "Sin contactos nuevos",
                                    "Todos los contactos del Excel ya existen en contactos.xlsx." + detalle)
            return
        revisar = (f"\n\n{resultado['por_revisar']} tienen un nombre, correo o teléfono por corregir "
                   "(quedarán marcados en rojo).") if resultado['por_revisar'] else ""
        respuesta = QMessageBox.question(
            self, "Confirmar importación",
            f"Se agregarán {len(registros)} contacto(s) nuevo(s) a contactos.xlsx.{revisar}{detalle}\n\n¿Confirmar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        self.btn_importar.setEnabled(False)
        mostrar_guardando(self, "Importando contactos…")
        self.importar_thread = ImportarContactosThread(self.writer, registros)
        self.importar_thread.finished_signal.connect(self._on_importar_finished)
        self.importar_thread.start()

    def _on_importar_finished(self, success, cantidad):
        self.btn_importar.setEnabled(True)
        if success:
            terminar_guardando(self, texto_exito="Contactos importados")
            self.load_data()
        else:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se pudo importar. Verifica si contactos.xlsx está abierto.")

    def on_item_edited(self, row, col_name, new_value):
        """Captura la edición del usuario y registra el cambio en pending_changes de forma infalible."""
        if self.tabs.currentIndex() != 0: return
        if col_name in ['★', 'ID']: return

        df_actual = self.model_plat.get_df()
        if df_actual.empty or row < 0 or row >= len(df_actual) or col_name not in df_actual.columns:
            return

        # Obtenemos el ID físico único de la fila editada
        raw_id = df_actual.iat[row, df_actual.columns.get_loc('ID')]
        id_val = self._normalize_id(raw_id)

        if id_val not in self.pending_changes:
            self.pending_changes[id_val] = {
                'keys': {'ID': id_val},
                'cambios': {}
            }

        if col_name == 'Número móvil':
            new_value = contactos_service.normalizar_telefono_ingresado(new_value)
            if contactos_service.validar_telefono(new_value)[0]:
                new_value = contactos_service.formatear_telefono_internacional(new_value)

        motivo = contactos_service.motivo_dato_invalido(col_name, new_value)
        if not motivo and col_name == 'Correo electrónico' and str(new_value).strip():
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                resultado = contactos_service.verificar_dominio_correo(new_value, timeout=3.0)
            finally:
                QApplication.restoreOverrideCursor()
            if resultado in (contactos_service.DOMINIO_NO_EXISTE, contactos_service.DOMINIO_SIN_CORREO):
                motivo = f"El dominio \"{str(new_value).strip().rsplit('@', 1)[1]}\" no puede recibir correo."
        if motivo:
            if not self.pending_changes[id_val]['cambios']:
                del self.pending_changes[id_val]
            # Se avisa fuera del commit del editor y se repinta el valor anterior
            QTimer.singleShot(0, lambda: self._rechazar_edicion(col_name, new_value, motivo))
            return

        valor_final = str(new_value).strip()
        self.pending_changes[id_val]['cambios'][col_name] = valor_final

        # Inyección temporal en RAM sobre el modelo actual para respuesta visual inmediata
        df_actual[col_name] = df_actual[col_name].astype(object)
        df_actual.iat[row, df_actual.columns.get_loc(col_name)] = valor_final

        if 'Fecha de extracción' in df_actual.columns:
            fecha_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            self.pending_changes[id_val]['cambios']['Fecha de extracción'] = fecha_str
            df_actual['Fecha de extracción'] = df_actual['Fecha de extracción'].astype(object)
            df_actual.iat[row, df_actual.columns.get_loc('Fecha de extracción')] = fecha_str
            self.model_plat._edited_cells.add((row, df_actual.columns.get_loc('Fecha de extracción')))

        self.model_plat._edited_cells.add((row, df_actual.columns.get_loc(col_name)))
        self.model_plat.layoutChanged.emit()

    def _rechazar_edicion(self, col_name, valor, motivo):
        self.filter_tables()
        DialogoAccion.aviso(self, "Dato inválido", f"{col_name}: \"{valor}\"\n{motivo}\n\nSe mantuvo el valor anterior.").exec()

    def _corregir_telefonos(self):
        df_base = contactos_service.aplicar_cambios_pendientes_contactos(
            self.df_plataforma.copy().astype(object), self.pending_changes)
        propuestas = contactos_service.proponer_correcciones_telefono(df_base)
        if not propuestas:
            DialogoAccion.exito_generico(self, "Teléfonos en orden", None,
                                         "No hay números que se puedan corregir automáticamente.").exec()
            return
        cantidad = len(propuestas)
        dialogo = DialogoAccion(
            self, " Corregir teléfonos",
            icon_name="fa5s.magic", icon_color=PRIMARY, icon_bg_color="#EFF6FF",
            titulo="Corregir teléfonos",
            subtitulo=f"{cantidad} número{'s' if cantidad != 1 else ''} se puede{'n' if cantidad != 1 else ''} corregir",
            descripcion=("Se pasarán al formato con código de país. Quedarán marcados en naranjo "
                         "como cambios pendientes: revísalos y presiona Guardar para escribirlos en la nube."),
            items=[f"{p['antes']}  →  {p['despues']}   ({p['Nombre'] or 'ID ' + p['ID']})" for p in propuestas],
            titulo_items="Cambios propuestos",
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Aplicar correcciones', 'clase': 'primary', 'rol': 'accept'},
            ],
        )
        dialogo.setFixedWidth(560)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        fecha_str = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        for p in propuestas:
            cambio = self.pending_changes.setdefault(p['ID'], {'keys': {'ID': p['ID']}, 'cambios': {}})
            cambio['cambios']['Número móvil'] = p['despues']
            if 'Fecha de extracción' in self.df_plataforma.columns:
                cambio['cambios']['Fecha de extracción'] = fecha_str
        self.filter_tables()

    def confirm_save(self):
        valid = {id_v: d for id_v, d in self.pending_changes.items() if d.get('cambios')}
        if not valid: return QMessageBox.information(self, "Sin cambios", "No hay datos de contactos modificados para guardar.")

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirmar Edición")
        msg.setText("Los cambios se sobrescribirán directamente en la nube de SharePoint.")
        msg.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Save:
            self.last_save_success = None
            self.btn_save.setEnabled(False)
            mostrar_guardando(self, "Guardando el directorio de Contactos…")
            self.save_thread = SaveContactosThread(self.writer, valid)
            self.save_thread.finished_signal.connect(self._on_save_finished)
            self.save_thread.start()

    def _on_save_finished(self, success):
        self.last_save_success = success
        self.btn_save.setEnabled(True)
        if success:
            guardado_listo(self)
            try:
                dm = self.data_manager
                if not dm.df_contactos.empty:
                    df_m = dm.df_contactos.copy()
                    df_m = contactos_service.aplicar_cambios_pendientes_contactos(df_m, self.pending_changes)
                    dm.df_contactos = df_m
            except Exception as e:
                print(f"Fallo inyectando RAM en Contactos: {e}")
                
            # ÚNICO MOMENTO DE LIMPIEZA AUTOMÁTICA TRAS GUARDAR CON ÉXITO
            self.pending_changes.clear()
            terminar_guardando(self)
            self.load_data(clear_pending=False)
        else:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "SharePoint bloqueó el guardado o el archivo está abierto en Excel. Intenta de nuevo.")

    def _handle_eliminar(self, row, texto_ficticio):
        df_actual = self.model_plat.get_df()
        if df_actual.empty or row < 0 or row >= len(df_actual):
            return

        id_val = self._normalize_id(df_actual.iat[row, df_actual.columns.get_loc('ID')])
        correo_val = str(df_actual.iat[row, df_actual.columns.get_loc('Correo electrónico')]).strip()
        nombre_val = str(df_actual.iat[row, df_actual.columns.get_loc('Nombre')]).strip()
        flota_val = str(df_actual.iat[row, df_actual.columns.get_loc('Flota')]).strip()
        
        msg = QMessageBox(self)
        msg.setWindowTitle("Eliminar Contacto")
        msg.setText(f"¿Estás completamente seguro de eliminar a este administrador?\n\nEmpresa: {flota_val}\nNombre: {nombre_val}\nCorreo: {correo_val}")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.last_delete_success = None
            # Deshabilita la tabla mientras corre el thread de borrado (mismo
            # patron que btn_add/btn_save): evita que una segunda eliminacion
            # sobrescriba self.del_thread mientras el anterior sigue corriendo.
            self.table_plat.setEnabled(False)
            keys_dict = {'ID': id_val}
            self.del_thread = DeleteContactoThread(self.writer, keys_dict)
            self.del_thread.finished_signal.connect(self._on_del_finished)
            self.del_thread.start()

    def _on_del_finished(self, success, keys_dict):
        self.last_delete_success = success
        self.table_plat.setEnabled(True)
        if success:
            QMessageBox.information(self, "Eliminado", "El administrador fue eliminado correctamente.")
            self.load_data(clear_pending=True)
        else:
            QMessageBox.warning(self, "Error", "No se pudo eliminar el contacto. Puede que el Excel esté abierto.")

    # ==========================================
    # LÓGICAS DE PANTALLA Y FILTROS
    # ==========================================
    def _set_all_filters(self, is_checked):
        self.list_filtros.blockSignals(True) 
        state = Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked
        for item in self._filter_items:
            item.setCheckState(state)
        self.list_filtros.blockSignals(False)
        self.filter_tables()

    def _on_filter_item_changed(self, item):
        self.filter_tables()

    def _on_tab_changed(self):
        self._actualizar_barra()

        try:
            self.list_filtros.itemChanged.disconnect(self._on_filter_item_changed)
        except (TypeError, RuntimeError):
            pass
        
        self.list_filtros.blockSignals(True)
        self.list_filtros.clear()
        self._filter_items = []
        
        elementos = []
        if self.tabs.currentIndex() == 1 and not self.df_empresas.empty and 'Nombre' in self.df_empresas.columns:
            self.lbl_filtro.setText("Filtrar Empresa:")
            elementos = sorted([str(n).strip() for n in self.df_empresas['Nombre'].dropna().unique() if str(n).strip() != ''])
            
        for elemento in elementos:
            item = QListWidgetItem(elemento)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked) 
            self.list_filtros.addItem(item)
            self._filter_items.append(item)
            
        self.list_filtros.itemChanged.connect(self._on_filter_item_changed)
        self.list_filtros.blockSignals(False)
        
        if not self.df_plataforma.empty:
            self.filter_tables()

    def _actualizar_barra(self):
        es_admins = self.tabs.currentIndex() == 0
        en_detalle = es_admins and self._flota_abierta is not None
        self.btn_volver.setVisible(en_detalle)
        for w in (self.btn_add, self.btn_save, self.btn_corregir_tel):
            w.setVisible(es_admins)
        for w in (self.lbl_filtro, self.btn_filtro_lista):
            w.setVisible(not es_admins)

    def _abrir_flota(self, index):
        if index.row() < 0:
            return
        df = self.model_flotas.get_df()
        if df.empty or index.row() >= len(df):
            return
        self._flota_abierta = (str(df.iat[index.row(), df.columns.get_loc('CDB')]).strip(),
                               str(df.iat[index.row(), df.columns.get_loc('Flota')]).strip())
        self.stack_plat.setCurrentIndex(1)
        self._actualizar_barra()
        self.render_table()
        self._actualizar_kpis()
        animar_sobre_tabla(self.table_plat, 350)

    def _volver_a_flotas(self):
        self._flota_abierta = None
        self.stack_plat.setCurrentIndex(0)
        self._actualizar_barra()
        self.render_table()
        self._actualizar_kpis()
        animar_sobre_tabla(self.table_flotas, 350)

    def _export_current_tab(self):
        if self.tabs.currentIndex() == 0:
            if self._flota_abierta is None:
                self.table_flotas.export_to_excel("Flotas_Contactos")
                return
            self.table_plat.export_to_excel("Contactos_Plataforma")
        else:
            self.table_emp.export_to_excel("Empresas_PowerBI")

    def load_data(self, clear_pending=False):
        """Método central de recarga. Protege pending_changes a menos que se indique clear_pending=True."""
        self.btn_reload.setEnabled(False)
        if clear_pending:
            self.pending_changes.clear()
        self._data_dirty = False
        self._firma_cargada = self._firma_archivos()

        self._plataforma_cargada = False
        self._empresas_cargada = False
        self.content_stack.setCurrentIndex(0)
        QApplication.processEvents()

        self.data_manager.load_contactos_async()
        self._load_empresas_async()

        QTimer.singleShot(12000, self._force_unlock_content)

    def _marcar_dirty(self):
        self._data_dirty = True

    @staticmethod
    def _firma_archivos():
        firma = []
        for ruta in (config.settings.CONTACTOS_EXCEL_PATH, POWERBI_EXCEL_PATH):
            try:
                firma.append((ruta, os.path.getmtime(ruta) if ruta else None))
            except OSError:
                firma.append((ruta, None))
        return tuple(firma)

    def refresh_if_dirty(self):
        """Al volver a la pantalla solo se relee si cambió el RM (data_ready) o
        alguno de los dos archivos. Releer en cada visita también disparaba
        contactos_ready, y General, Operaciones y Comercial reprocesaban."""
        if self._data_dirty or self._firma_archivos() != self._firma_cargada:
            self.load_data(clear_pending=False)

    def _check_carga_completa(self):
        """Solo oculta la pantalla de carga cuando ambas fuentes (contactos.xlsx
        y BBDD CLIENTES CM) terminaron, con éxito o con error."""
        if self._plataforma_cargada and self._empresas_cargada:
            self.btn_reload.setEnabled(True)
            self.content_stack.setCurrentIndex(1)

    def _force_unlock_content(self):
        """Red de seguridad: si algo dejó colgada la carga sin emitir señal,
        no queremos que la pantalla se quede pegada en el spinner para siempre."""
        if self.content_stack.currentIndex() == 0:
            self.btn_reload.setEnabled(True)
            self.content_stack.setCurrentIndex(1)

    def _load_empresas_async(self):
        """Carga 'Director de empresas' en vivo desde BBDD CLIENTES CM (POWERBI_EXCEL_PATH),
        filtrando por los CDB activos en Comercial. Reemplaza la lectura de direcciones.xlsx,
        que era solo un snapshot manual de esta misma fuente."""
        # Guard: si ya hay un PowerBiSyncWorker corriendo, no se crea uno
        # nuevo. Sin esto, dos llamadas a load_data() muy seguidas (ej. un
        # clic en "Recargar" mientras un guardado/alta/baja en curso dispara
        # su propio load_data() al terminar) sobrescriben self.empresas_thread
        # y pierden la referencia al thread anterior mientras sigue corriendo.
        if self._empresas_loading:
            return
        self._empresas_loading = True
        self.empresas_thread = PowerBiSyncWorker(self.data_manager.get_comercial_df())
        self.empresas_thread.preview_signal.connect(self._on_empresas_loaded)
        self.empresas_thread.error_signal.connect(self._on_empresas_load_error)
        iniciar_hilo_retenido(self.empresas_thread)

    def _on_empresas_loaded(self, df_resultado):
        self._empresas_loading = False
        self.df_empresas = df_resultado.fillna("")
        self._on_tab_changed()
        self.filter_tables()
        self._actualizar_kpis()
        self._empresas_cargada = True
        self._check_carga_completa()

    def _on_empresas_load_error(self, error_msg):
        self._empresas_loading = False
        print(f"No se pudo cargar 'Director de empresas' desde BBDD CLIENTES CM: {error_msg}")
        self.df_empresas = pd.DataFrame()
        self._on_tab_changed()
        self.filter_tables()
        self._empresas_cargada = True
        self._check_carga_completa()

    def _actualizar_kpis(self):
        """Contadores de las sub-pestañas y subtítulo de la barra."""
        df = self.df_plataforma
        total = len(df)
        flotas = int(df['Flota'].astype(str).str.strip().replace("", pd.NA).dropna().nunique()) if total and 'Flota' in df.columns else 0
        admin_estilo.actualizar_contador(self.subtabs, self._badges, 0, total)
        admin_estilo.actualizar_contador(self.subtabs, self._badges, 1, len(self.df_empresas))
        if self.tabs.currentIndex() == 0 and self._flota_abierta is not None:
            cdb, flota = self._flota_abierta
            n = len(self.model_plat.get_df())
            self._barra.lbl_subtitulo.setText(f"{flota or 'Sin flota'} · CDB {cdb or '-'} · {n} contactos")
        elif self.tabs.currentIndex() == 0:
            self._barra.lbl_subtitulo.setText(f"{flotas} flotas · {total} contactos")
        else:
            self._barra.lbl_subtitulo.setText(f"{len(self.df_empresas)} directores de empresa")

    def _on_data_ready(self):
        self.df_plataforma = self.data_manager.get_contactos_df()

        if not self.df_plataforma.empty and 'CDB' in self.df_plataforma.columns:
            self.df_plataforma['CDB'] = self.df_plataforma['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip()

        self._migrate_pinned_contacts()
        self._on_tab_changed()
        self.filter_tables()
        self._actualizar_kpis()
        self._plataforma_cargada = True
        self._check_carga_completa()

    def _on_load_error(self, error_msg):
        self._plataforma_cargada = True
        self._check_carga_completa()
        QMessageBox.warning(self, "Error de Lectura", f"No se pudo cargar el directorio:\n\n{error_msg}")

    def _on_table_plat_clicked(self, index):
        if index.column() < 0 or index.row() < 0: return
        df_actual = self.model_plat.get_df()
        col_name = df_actual.columns[index.column()]
        if col_name == '★':
            contact_key = self._get_contact_key(df_actual.iloc[index.row()])
            if contact_key in self.pinned_contacts: 
                self.pinned_contacts.remove(contact_key)
            else: 
                self.pinned_contacts.append(contact_key)
            self.save_pinned()
            self.filter_tables()

    def filter_tables(self):
        """Aplica filtros, búsqueda global y overlay seguro sobre el maestro Read-Only."""
        if self.table_plat.state() == VolvoTableWidget.State.EditingState:
            self.table_plat.setFocus()

        search_text = self.search_input.text().lower()
        
        elementos_marcados = [i.text().strip() for i in self._filter_items if i.checkState() in (Qt.CheckState.Checked, 2)]
        todos_marcados = len(elementos_marcados) == len(self._filter_items)
        ninguno_marcado = len(elementos_marcados) == 0
        
        # 1. Copia maestra base convertida a tipo object (READ-ONLY)
        df_p = self.df_plataforma.copy().astype(object)
        
        if not df_p.empty:
            if 'ID' in df_p.columns:
                df_p['ID'] = df_p['ID'].apply(self._normalize_id)

            # --- 2. OVERLAY MAESTRO DE CAMBIOS PENDIENTES ---
            df_p = contactos_service.aplicar_cambios_pendientes_contactos(df_p, self.pending_changes)

            # 4. Búsqueda Global
            cols_busqueda = ['CDB', 'Flota', 'Nombre', 'Apellidos', 'Correo electrónico', 'Número móvil']
            df_p = contactos_service.buscar_texto_global(df_p, cols_busqueda, search_text)

            # 5. Ordenamiento estricto por ID (orden "original" de esta pantalla:
            # favoritos primero, luego por ID ascendente)
            df_p = contactos_service.ordenar_por_favoritos_e_id(df_p, self.pinned_contacts)

            # 6. Si el usuario eligió ordenar por una columna (clic de
            # encabezado / menú contextual), esa elección manda por completo
            # y reemplaza el agrupamiento de favoritos+ID de arriba — igual
            # que en Excel, clicar un encabezado reordena toda la tabla. Al
            # tercer clic (sin ordenamiento activo) apply_sort no hace nada y
            # se vuelve a ver el orden "favoritos primero + ID" de siempre.
            df_p = self.table_plat.apply_sort(df_p)

        self.filtered_plat = df_p
        self.filtered_flotas = self._resumen_flotas(df_p)

        df_e = self.df_empresas.copy()
        if not df_e.empty:
            if self.tabs.currentIndex() == 1 and 'Nombre' in df_e.columns:
                df_e = contactos_service.aplicar_filtro_checkbox(df_e, 'Nombre', elementos_marcados, todos_marcados, ninguno_marcado)

            df_e = contactos_service.buscar_texto_global(df_e, list(df_e.columns), search_text)
            df_e = self.table_emp.apply_sort(df_e)
        self.filtered_emp = df_e
        
        self.render_table()

    def render_table(self):
        """Dibuja la tabla completa manteniendo el orden por ID y las celdas naranjas."""
        is_plat = self.tabs.currentIndex() == 0
        df_target = self.filtered_plat if is_plat else self.filtered_emp
        
        df_view = df_target.copy().astype(object)
        if is_plat:
            self._pintar_lista_flotas()
            if self._flota_abierta is not None:
                cdb, flota = self._flota_abierta
                mascara = (df_view['CDB'].astype(str).str.strip() == cdb) & (df_view['Flota'].astype(str).str.strip() == flota) \
                    if not df_view.empty else []
                df_view = df_view[mascara] if not df_view.empty else df_view
                if df_view.empty:
                    QTimer.singleShot(0, self._volver_a_flotas)
        
        if is_plat and not df_view.empty:
            if '★' in df_view.columns:
                df_view = df_view.drop(columns=['★'])
            df_view.insert(0, '★', df_view.apply(lambda row: self._get_contact_key(row) in self.pinned_contacts, axis=1))
            
            # --- 6. RECONSTRUCCIÓN EXACTA DE COORDENADAS NARANJAS ---
            edited_coords = set()
            if self.pending_changes and 'ID' in df_view.columns:
                for r in range(len(df_view)):
                    raw_id = df_view.iat[r, df_view.columns.get_loc('ID')]
                    id_val = self._normalize_id(raw_id).upper()
                    
                    if id_val in self.pending_changes:
                        for col_c in self.pending_changes[id_val]['cambios'].keys():
                            if col_c in df_view.columns:
                                col_idx = df_view.columns.get_loc(col_c)
                                edited_coords.add((r, col_idx))
                                
            self.model_plat.set_data(df_view)
            
            if edited_coords:
                self.model_plat._edited_cells = edited_coords
                self.model_plat.layoutChanged.emit()
            
            try:
                anchos = {'★': 52, 'Nombre': 190, 'Apellidos': 190, 'Correo electrónico': 320, 'Número móvil': 170,
                          'Fecha de extracción': 160}
                for i, nombre in enumerate(self.model_plat._df.columns):
                    # ID, CDB, Flota y Rol no se muestran: la flota ya se eligió en la lista y todos son administradores
                    self.table_plat.setColumnHidden(i, nombre not in anchos)
                    if nombre in anchos:
                        self.table_plat.setColumnWidth(i, anchos[nombre])

                self.table_plat.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
                self.table_plat.horizontalHeader().setStretchLastSection(True)
            except Exception: pass
            
        elif not is_plat and not df_view.empty:
            self.model_emp.set_data(df_view)
            try:
                self.table_emp.setColumnWidth(0, 60)
                self.table_emp.setColumnWidth(1, 140)
                self.table_emp.setColumnWidth(2, 280)
                self.table_emp.setColumnWidth(4, 170)
                self.table_emp.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
                self.table_emp.horizontalHeader().setStretchLastSection(True)
            except Exception: pass
            
        else:
            if is_plat: self.model_plat.set_data(pd.DataFrame())
            else: self.model_emp.set_data(pd.DataFrame())

    # ---- Lista de flotas ----
    @staticmethod
    def _resumen_flotas(df):
        """Una fila por (CDB, Flota) con la cantidad de contactos."""
        if df is None or df.empty or 'Flota' not in df.columns:
            return pd.DataFrame(columns=['CDB', 'Flota', 'Contactos'])
        base = pd.DataFrame({
            'CDB': df['CDB'].astype(str).str.strip() if 'CDB' in df.columns else "",
            'Flota': df['Flota'].astype(str).str.strip(),
        }).replace({"nan": "", "None": ""})
        resumen = base.groupby(['CDB', 'Flota'], sort=False).size().reset_index(name='Contactos')
        return resumen.sort_values('Flota', key=lambda s: s.str.casefold(), kind='mergesort').reset_index(drop=True)

    def _pintar_lista_flotas(self):
        df = self.table_flotas.apply_sort(self.filtered_flotas) if not self.filtered_flotas.empty else self.filtered_flotas
        self.model_flotas.set_data(df.reset_index(drop=True))
        try:
            for i, (nombre, ancho) in enumerate((('CDB', 170), ('Flota', 460), ('Contactos', 130))):
                if nombre in self.model_flotas._df.columns:
                    self.table_flotas.setColumnWidth(self.model_flotas._df.columns.get_loc(nombre), ancho)
            self.table_flotas.horizontalHeader().setStretchLastSection(True)
        except Exception:
            pass

    def _show_contactos_context_menu(self, pos):
        if self.tabs.currentIndex() != 0: return 
        
        index = self.table_plat.indexAt(pos)
        if not index.isValid(): return 
        
        row = index.row()
        col = index.column()
        df_actual = self.model_plat.get_df()
        
        celda_seleccionada = str(df_actual.iat[row, col]).strip()
        if celda_seleccionada == "nan" or celda_seleccionada == "None": celda_seleccionada = ""

        correo, telefono = "", ""
        if 'Correo electrónico' in df_actual.columns: correo = str(df_actual.iat[row, df_actual.columns.get_loc('Correo electrónico')]).strip()
        if 'Número móvil' in df_actual.columns: telefono = str(df_actual.iat[row, df_actual.columns.get_loc('Número móvil')]).strip()

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #E5E7EB; border-radius: 6px; padding: 4px; } 
            QMenu::item { padding: 6px 25px; border-radius: 4px; color: #1E293B; font-weight: bold; } 
            QMenu::item:selected { background-color: #F3F4F6; color: #1C6BBA; }
        """)
        
        texto_mostrar = celda_seleccionada if len(celda_seleccionada) < 20 else celda_seleccionada[:17] + "..."
        action_copy_cell = QAction(qta.icon('fa5s.copy', color='#6B7280'), f"Copiar: '{texto_mostrar}'", self)
        
        if not celda_seleccionada or col == 0: 
            action_copy_cell.setEnabled(False)
            
        menu.addAction(action_copy_cell)
        menu.addSeparator() 

        action_copy_mail = QAction(qta.icon('fa5s.envelope', color='#2563EB'), f"Copiar Correo ({correo if correo else 'N/A'})", self)
        action_copy_tel = QAction(qta.icon('fa5s.phone-alt', color='#10B981'), f"Copiar Teléfono ({telefono if telefono else 'N/A'})", self)
        
        if not correo or correo.lower() == "nan": action_copy_mail.setEnabled(False)
        if not telefono or telefono.lower() == "nan" or telefono == "-": action_copy_tel.setEnabled(False)

        menu.addAction(action_copy_mail)
        menu.addAction(action_copy_tel)
        
        menu.addSeparator()
        action_delete = QAction(qta.icon('fa5s.trash-alt', color=DANGER), "Eliminar Administrador", self)
        menu.addAction(action_delete)

        selected = menu.exec(self.table_plat.viewport().mapToGlobal(pos))
        
        if selected == action_copy_cell: QApplication.clipboard().setText(celda_seleccionada)
        elif selected == action_copy_mail: QApplication.clipboard().setText(correo)
        elif selected == action_copy_tel: QApplication.clipboard().setText(telefono)
        elif selected == action_delete:
            self._handle_eliminar(row, "ficticio")