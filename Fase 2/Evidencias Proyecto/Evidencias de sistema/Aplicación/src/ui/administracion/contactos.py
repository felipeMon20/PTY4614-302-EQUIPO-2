import pandas as pd
import qtawesome as qta
import os
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QPushButton, QMessageBox, QLineEdit, QMenu, QApplication,
                             QHeaderView, QDialog, QTabWidget, QListWidget, QListWidgetItem, QWidgetAction,
                             QStackedWidget, QProgressBar, QFileDialog)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal, QTimer, QModelIndex
from PyQt6.QtGui import QAction, QColor, QFont

from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.hilos import iniciar_hilo_retenido
from src.theme.theme_manager import ThemeManager
from src.ui.compartido.menu_contextual import crear_menu, texto_corto
from src.ui.compartido.custom_table import VolvoTableWidget, PandasTableModel
from src.ui.administracion import estilo as admin_estilo
from src.ui.administracion import listas as admin_listas
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.comercial_agregar import _COMBO_CHEVRON_PATH
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando, crear_tarjeta_carga
from src.ui.administracion.contactos_agregar import ContactosAddDialog
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.ui.compartido.esqueleto_carga import animar_sobre_tabla
from src.theme import tema
from src.services import contactos_service, powerbi_cache_service
import config.settings
from config.settings import POWERBI_EXCEL_PATH
from src.theme.colors import BACKGROUND, SUCCESS, TEXT_PRIMARY, TEXT_SECONDARY, SURFACE, BORDER, PRIMARY, DANGER
import logging

logger = logging.getLogger(__name__)

_COLUMNAS_VALIDADAS = ('Nombre', 'Apellidos', 'Correo electrónico', 'Número móvil')
_FONDO_INVALIDO = '#FEE2E2'
_QSS_CAMPOS_PANEL = (
    f"QLineEdit {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid #DCE3EC; "
    "border-radius: 10px; padding: 0 12px; min-height: 34px; font-size: 12px; font-weight: 600; }"
    "QLineEdit:focus { border: 1px solid #1B2B4E; }"
    "QLineEdit:read-only { background: #F1F5F9; color: #64748B; }"
    "QLineEdit[error=\"true\"] { border: 1px solid #E04848; background: #FEF2F2; }")

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
        
        self._busqueda_previa = ""
        # Administradores de flota: primero la lista de flotas (CDB, Flota) y, al
        # elegir una, sus contactos. None = lista de flotas.
        self._flota_abierta = None
        self._contacto_id = None
        self.filtered_flotas = pd.DataFrame()
        
        self.data_manager.contactos_ready.connect(self._on_data_ready)
        self.data_manager.load_contactos_error.connect(self._on_load_error)
        self._data_dirty = False
        self._firma_cargada = None
        self.data_manager.data_ready.connect(self._marcar_dirty)

        self._setup_ui()
        self.table_plat.clicked.connect(self._on_table_plat_clicked)
        
        self.load_data(clear_pending=False, repintar=False)

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
        cuerpo = QWidget()
        fila = QHBoxLayout(cuerpo)
        fila.setContentsMargins(0, 12, 0, 0)
        fila.setSpacing(12)
        fila.addWidget(self._crear_caja_secciones())
        fila.addWidget(self._crear_caja_tabla(), 1)
        fila.addWidget(self._crear_caja_detalle())
        main_layout.addWidget(cuerpo, 1)
        self._actualizar_barra()
        self._mostrar_vacio()
        self._actualizar_pendientes()

    # ------------------------------------------------------------ caja izquierda
    def _crear_caja_secciones(self):
        caja = admin_estilo.caja_con_encabezado("cajaSeccionesContactos", "Contactos", "Directorio")
        caja.marco.setFixedWidth(250)
        lay = caja.cuerpo

        lista = QWidget()
        lay_lista = QVBoxLayout(lista)
        lay_lista.setContentsMargins(8, 8, 8, 8)
        lay_lista.setSpacing(4)
        self._botones_sec = []
        for i, (nombre, icono) in enumerate((("Administradores de flotas", 'fa5s.user-tie'),
                                             ("Director de empresas", 'fa5s.building'))):
            boton, badge = admin_estilo.boton_seccion(nombre, icono)
            badge.hide()
            boton.clicked.connect(lambda _c, k=i: self.tabs.setCurrentIndex(k))
            lay_lista.addWidget(boton)
            self._botones_sec.append(boton)
        lay.addWidget(lista)

        bloque_acciones = admin_estilo.bloque_caja("Acciones")
        self.btn_importar = admin_estilo.boton_accion("Importar del bot", 'fa5s.file-import')
        self.btn_importar.setToolTip("Importar contactos nuevos desde el Excel del bot de Volvo Connect")
        self.btn_importar.clicked.connect(self._importar_contactos_bot)
        self.btn_corregir_tel = admin_estilo.boton_accion("Corregir teléfonos", 'fa5s.magic')
        self.btn_corregir_tel.setToolTip("Corrige al formato +56 9 XXXX XXXX los números que se pueden arreglar solos")
        self.btn_corregir_tel.clicked.connect(self._corregir_telefonos)
        self.btn_export_excel = admin_estilo.boton_accion("Exportar a Excel", 'fa5s.file-excel')
        self.btn_export_excel.clicked.connect(self._export_current_tab)
        self.btn_reload = admin_estilo.boton_accion("Descartar cambios", 'fa5s.undo')
        self.btn_reload.setToolTip("Deshace los cambios sin guardar y vuelve a leer el archivo")
        # Descartar borra pending_changes pasando clear_pending=True; solo se ve con cambios pendientes
        self.btn_reload.clicked.connect(lambda: self.load_data(clear_pending=True))
        self.btn_reload.hide()
        for boton in (self.btn_importar, self.btn_corregir_tel, self.btn_export_excel, self.btn_reload):
            bloque_acciones.layout().addWidget(boton)
        lay.addWidget(bloque_acciones)
        lay.addStretch(1)
        return caja.marco

    # ------------------------------------------------------------ caja central
    def _crear_caja_tabla(self):
        self._caja = admin_estilo.caja_con_encabezado("cajaTablaContactos", "Administradores de flotas", "")
        self.btn_volver = QPushButton("  Volver a la lista")
        self.btn_volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color="white"))
        self.btn_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_volver.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.45); "
            "border-radius: 10px; padding: 6px 14px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background: rgba(255,255,255,0.25); }")
        self.btn_volver.clicked.connect(self._volver_a_flotas)
        self._caja.fila_cab.insertWidget(0, self.btn_volver)
        self._caja.fila_cab.insertSpacing(1, 10)

        self.content_stack = QStackedWidget()

        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(
            crear_tarjeta_carga("Cargando directorio de contactos y empresas…", "Esto tomará unos segundos."),
            alignment=Qt.AlignmentFlag.AlignCenter)
        self.content_stack.addWidget(self.loading_widget)

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")

        # Tabla de contactos: solo lectura, se edita en el panel de la derecha
        self.table_plat = VolvoTableWidget()
        self.table_plat.menu_type = "contactos"
        self.table_plat.action_eliminar.connect(self._handle_eliminar)
        self.table_plat.item_edited.connect(self.on_item_edited)

        self.model_plat = PandasTableModel(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.model_plat.flags = lambda index: Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

        original_data_method = getattr(self.model_plat.__class__, 'data')
        def custom_data(index, role=Qt.ItemDataRole.DisplayRole):
            col_name = self.model_plat._df.columns[index.column()]
            if col_name == '★':
                is_pinned = self.model_plat._valor_celda(index.row(), index.column())
                if role == Qt.ItemDataRole.DecorationRole:
                    if is_pinned: return qta.icon('fa5s.star', color='#F59E0B')
                    else: return qta.icon('fa5s.star', color='#D1D5DB')
                elif role == Qt.ItemDataRole.DisplayRole: return ""
            if col_name in _COLUMNAS_VALIDADAS and role in (Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ToolTipRole):
                motivo = contactos_service.motivo_dato_invalido(col_name, self.model_plat._valor_celda(index.row(), index.column()))
                if motivo:
                    if role == Qt.ItemDataRole.ToolTipRole:
                        return f"Dato inválido: {motivo}"
                    return tema.fondo(QColor(_FONDO_INVALIDO)) if tema.es_oscuro() else QColor(_FONDO_INVALIDO)
            if col_name == 'Fecha de extracción' and role == Qt.ItemDataRole.DisplayRole:
                return str(original_data_method(self.model_plat, index, role)).split(" ")[0]
            return original_data_method(self.model_plat, index, role)

        self.model_plat.data = custom_data
        self.table_plat.setModel(self.model_plat)
        admin_estilo.estilar_tabla(self.table_plat)
        self.table_plat.selectionModel().currentRowChanged.connect(self._on_fila_contacto)

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
        # Mismo contrato que ComercialModule: main_window._get_active_submodule
        # desciende hasta tabs.currentWidget(), así que la pestaña activa necesita
        # su propio search_input/filter_tables para que el buscador global le llegue.
        self.table_plat.search_input = self.search_input
        self.table_plat.filter_tables = self.filter_tables

        # Directorio de empresas (BBDD CLIENTES CM)
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
        self.table_emp.clicked.connect(lambda index: self._mostrar_empresa(index.row()))

        for tabla in (self.table_plat, self.table_flotas, self.table_emp):
            tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.content_stack.addWidget(self.tabs)
        self._caja.cuerpo.addWidget(self.content_stack, 1)
        return self._caja.marco

    # ------------------------------------------------------------ caja derecha
    def _crear_caja_detalle(self):
        self._det = admin_estilo.caja_con_encabezado("cajaDetalleContactos", "Contacto", "")
        self._det.marco.setFixedWidth(340)
        self.btn_add = QPushButton("  Agregar")
        self.btn_add.setToolTip("Agregar un contacto nuevo")
        self.btn_add.setIcon(ThemeManager.icon('fa5s.plus', color="white"))
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.setStyleSheet(self.btn_volver.styleSheet())
        self.btn_add.clicked.connect(self._open_add_dialog)
        self._det.fila_cab.addWidget(self.btn_add)
        self.pila_det = QStackedWidget()
        self.pila_det.addWidget(self._pagina_vacia())
        self.pila_det.addWidget(self._pagina_formulario())
        self.pila_det.addWidget(self._pagina_nuevo())
        self.pila_det.addWidget(self._pagina_empresa())
        self._det.cuerpo.addWidget(self.pila_det, 1)

        self._pie_det, lay_pie = admin_estilo.crear_pie()
        self.btn_save = admin_estilo.boton_pie("Guardar cambios", "primario", 'fa5s.save')
        self.btn_save.clicked.connect(self.confirm_save)
        lay_pie.addWidget(self.btn_save)
        self._det.cuerpo.addWidget(self._pie_det)
        return self._det.marco

    def _pagina_vacia(self):
        pagina, self._mostrar_cartel = admin_estilo.estado_vacio()
        return pagina

    def _pagina_formulario(self):
        pagina = QWidget()
        pagina.setStyleSheet(admin_estilo.QSS_CAMPOS_DETALLE)
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        self._campos = {}
        self.lbl_nombre_contacto = admin_estilo.nombre_detalle()
        lay.addWidget(self.lbl_nombre_contacto)
        fila_chips = QHBoxLayout()
        fila_chips.setSpacing(6)
        self.chip_flota = QLabel()
        self.chip_cdb = QLabel()
        self.chip_flota.setStyleSheet(estilo_com.qss_chip("#E3E8F0", "#1B2B4E"))
        self.chip_cdb.setStyleSheet(estilo_com.qss_chip("#E0F2FE", "#0369A1"))
        fila_chips.addWidget(self.chip_flota)
        fila_chips.addWidget(self.chip_cdb)
        fila_chips.addStretch()
        lay.addLayout(fila_chips)

        def campo(titulo, clave, solo_lectura=False):
            lay.addWidget(admin_estilo.rotulo_campo(titulo))
            w = QLineEdit()
            w.setReadOnly(solo_lectura)
            if not solo_lectura:
                w.editingFinished.connect(lambda c=clave: self._confirmar_campo(c))
            lay.addWidget(w)
            self._campos[clave] = w

        campo("Flota", 'Flota', True)
        campo("CDB", 'CDB', True)
        campo("Nombre", 'Nombre')
        campo("Apellidos", 'Apellidos')
        campo("Correo electrónico", 'Correo electrónico')
        campo("Número móvil", 'Número móvil')
        self.lbl_info_contacto = admin_listas.texto("", color=estilo_com.APAGADO, tam=11)
        self.lbl_info_contacto.setWordWrap(True)
        lay.addWidget(self.lbl_info_contacto)
        self.lbl_pendiente = admin_listas.texto("", color="#D98404", tam=11, negrita=True)
        lay.addWidget(self.lbl_pendiente)
        lay.addStretch(1)
        self.btn_eliminar_contacto = admin_estilo.boton_pie("Eliminar contacto", "peligro", 'fa5s.trash-alt')
        self.btn_eliminar_contacto.clicked.connect(self._eliminar_contacto_panel)
        lay.addWidget(self.btn_eliminar_contacto)
        return pagina

    def _pagina_nuevo(self):
        pagina = QWidget()
        self._lay_nuevo = QVBoxLayout(pagina)
        self._lay_nuevo.setContentsMargins(14, 12, 14, 12)
        self._form_nuevo = None
        return pagina

    def _pagina_empresa(self):
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(14, 12, 14, 12)
        self._lay_empresa = QVBoxLayout()
        self._lay_empresa.setSpacing(6)
        lay.addLayout(self._lay_empresa)
        lay.addStretch(1)
        return pagina

    def _actualizar_pie(self):
        # Mientras se llena el formulario de nuevo contacto solo queda su propio botón de guardar
        libre = self.tabs.currentIndex() == 0 and self.pila_det.currentIndex() != 2
        self._pie_det.setVisible(libre)
        self.btn_add.setVisible(libre)

    def _titulo_detalle(self, titulo, subtitulo=""):
        self._det.lbl_titulo.setText(titulo)
        self._det.lbl_subtitulo.setText(subtitulo)

    def _texto_vacio(self):
        """(título, detalle) del cartel sin selección."""
        if self.tabs.currentIndex() == 1:
            return "Selecciona una empresa", "Elige una fila de la tabla para ver su detalle."
        if self._flota_abierta is None:
            return "Abre una flota", "Abre una flota de la lista para ver y editar sus contactos."
        return "Selecciona un contacto", "Elige una fila de la tabla para ver y editar sus datos."

    def _cerrar_formulario_nuevo(self):
        if self._form_nuevo is not None:
            self._lay_nuevo.removeWidget(self._form_nuevo)
            self._form_nuevo.hide()
            self._form_nuevo.deleteLater()
            self._form_nuevo = None

    def _mostrar_vacio(self):
        self._cerrar_formulario_nuevo()
        self._contacto_id = None
        titulo, detalle = self._texto_vacio()
        self._mostrar_cartel('fa5s.address-card', titulo, detalle)
        self._titulo_detalle("Detalle", "Contacto" if self.tabs.currentIndex() == 0 else "Empresa")
        self.pila_det.setCurrentIndex(0)
        self._actualizar_pie()

    # ---- contacto seleccionado
    def _fila_actual(self):
        if not self._contacto_id:
            return None
        df = self.model_plat.get_df()
        if df.empty or 'ID' not in df.columns:
            return None
        ids = [self._normalize_id(v) for v in df['ID']]
        return ids.index(self._contacto_id) if self._contacto_id in ids else None

    def _on_fila_contacto(self, actual, _previo):
        if not actual.isValid() or self._flota_abierta is None or self.tabs.currentIndex() != 0:
            return
        df = self.model_plat.get_df()
        if df.empty or actual.row() >= len(df) or 'ID' not in df.columns:
            return
        self._cerrar_formulario_nuevo()
        self._contacto_id = self._normalize_id(df.iat[actual.row(), df.columns.get_loc('ID')])
        self.pila_det.setCurrentIndex(1)
        self._refrescar_panel()

    def _restaurar_seleccion(self):
        """Tras repintar la tabla, deja marcado el contacto del panel y refresca sus datos."""
        if self._flota_abierta is None or self.pila_det.currentIndex() != 1:
            return
        fila = self._fila_actual()
        if fila is None:
            self._mostrar_vacio()
            return
        seleccion = self.table_plat.selectionModel()
        seleccion.blockSignals(True)
        self.table_plat.setCurrentIndex(self.model_plat.index(fila, 1))
        seleccion.blockSignals(False)
        self._refrescar_panel()

    def _refrescar_panel(self):
        if self.pila_det.currentIndex() != 1:
            return
        fila = self._fila_actual()
        if fila is None:
            self._mostrar_vacio()
            return
        df = self.model_plat.get_df()

        def valor(col):
            if col not in df.columns:
                return ""
            v = str(df.iat[fila, df.columns.get_loc(col)]).strip()
            return "" if v.lower() in ("nan", "none", "nat") else v

        for clave, w in self._campos.items():
            w.blockSignals(True)
            w.setText(valor(clave))
            w.blockSignals(False)
            motivo = contactos_service.motivo_dato_invalido(clave, w.text()) if clave in _COLUMNAS_VALIDADAS else ""
            w.setProperty("error", bool(motivo))
            w.setToolTip(f"Dato inválido: {motivo}" if motivo else "")
            w.style().unpolish(w)
            w.style().polish(w)
        nombre = f"{valor('Nombre')} {valor('Apellidos')}".strip()
        self._titulo_detalle("Detalle", "Contacto")
        self.lbl_nombre_contacto.setText(nombre or "Sin nombre")
        self.chip_flota.setText(valor('Flota') or "Sin flota")
        self.chip_cdb.setText(f"CDB {valor('CDB')}" if valor('CDB') else "Sin CDB")
        fecha = valor('Fecha de extracción').split(" ")[0]
        self.lbl_info_contacto.setText(f"ID {self._contacto_id}" + (f"  ·  Última actualización {fecha}" if fecha else ""))
        pendiente = bool(self.pending_changes.get(self._contacto_id, {}).get('cambios'))
        self.lbl_pendiente.setText("Cambios sin guardar" if pendiente else "")

    def _confirmar_campo(self, clave):
        fila = self._fila_actual()
        if fila is None:
            return
        df = self.model_plat.get_df()
        actual = str(df.iat[fila, df.columns.get_loc(clave)]).strip()
        actual = "" if actual.lower() in ("nan", "none", "nat") else actual
        nuevo = self._campos[clave].text().strip()
        if nuevo == actual:
            return
        self.on_item_edited(fila, clave, nuevo)
        self._refrescar_panel()

    def _eliminar_contacto_panel(self):
        fila = self._fila_actual()
        if fila is not None:
            self._handle_eliminar(fila, "")

    # ---- empresa seleccionada
    def _mostrar_empresa(self, fila):
        df = self.model_emp.get_df()
        if df.empty or fila < 0 or fila >= len(df):
            return
        while self._lay_empresa.count():
            item = self._lay_empresa.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        nombre = ""
        for col in df.columns:
            if col == 'Nombre':
                v = str(df.iat[fila, df.columns.get_loc(col)]).strip()
                nombre = "" if v.lower() in ("nan", "none") else v
        self._lay_empresa.addWidget(admin_estilo.nombre_detalle(nombre or "Empresa"))
        chip_lectura = QLabel("Solo lectura (Power BI)")
        chip_lectura.setStyleSheet(estilo_com.qss_chip("#E3E8F0", "#1B2B4E"))
        self._lay_empresa.addWidget(chip_lectura, 0, Qt.AlignmentFlag.AlignLeft)
        for col in df.columns:
            v = str(df.iat[fila, df.columns.get_loc(col)]).strip()
            v = "" if v.lower() in ("nan", "none") else v
            self._lay_empresa.addWidget(admin_estilo.rotulo_campo(str(col)))
            self._lay_empresa.addWidget(admin_listas.texto(v or "-", tam=12, negrita=True, seleccionable=True))
        self._titulo_detalle("Detalle", "Empresa")
        self.pila_det.setCurrentIndex(3)

    # ---- agregar contacto
    def _pendientes_guardar(self):
        return sum(1 for d in self.pending_changes.values() if d.get('cambios'))

    def _actualizar_pendientes(self):
        n = self._pendientes_guardar()
        self.btn_save.setText("  " + (f"Guardar cambios ({n})" if n else "Guardar cambios"))
        if getattr(self, 'btn_reload', None) is not None:
            self.btn_reload.setVisible(n > 0)


    # ==========================================
    # LÓGICAS CRUD CON ID FÍSICO PERMANENTE
    # ==========================================
    def abrir_alta_flota(self, cdb, flota):
        """Abre el formulario de nuevo contacto con `cdb` y `flota` completados (llamado desde Clientes y Flota).
        Si la pantalla está recargando, espera a que termine: la recarga limpia el panel derecho."""
        self._alta_pendiente = (str(cdb), str(flota))
        if self.content_stack.currentIndex() == 1:
            self.refresh_if_dirty()
        if self.content_stack.currentIndex() == 1:
            self._aplicar_alta_pendiente()

    def _aplicar_alta_pendiente(self):
        pendiente, self._alta_pendiente = self.__dict__.get('_alta_pendiente'), None
        if pendiente is None:
            return
        if self.tabs.currentIndex() != 0:
            self.tabs.setCurrentIndex(0)
        if self._flota_abierta is not None:
            self._volver_a_flotas()
        self._open_add_dialog(prefill=pendiente)

    def _open_add_dialog(self, _marcado=False, prefill=None):
        self._cerrar_formulario_nuevo()
        self.table_plat.clearSelection()
        self.table_plat.setCurrentIndex(QModelIndex())
        cdb, flota = prefill or (self._flota_abierta if self._flota_abierta is not None else (None, None))
        formulario = ContactosAddDialog(self, cdb_prefill=cdb or None, flota_prefill=flota or None, embebido=True)
        formulario.setWindowFlags(Qt.WindowType.Widget)
        formulario.accepted.connect(self._on_formulario_aceptado)
        formulario.rejected.connect(self._mostrar_vacio)
        self._lay_nuevo.addWidget(formulario)
        formulario.show()
        self._form_nuevo = formulario
        self._contacto_id = None
        self._titulo_detalle("Detalle", "Nuevo contacto")
        self.pila_det.setCurrentIndex(2)
        self._actualizar_pie()

    def _on_formulario_aceptado(self):
        formulario = self._form_nuevo
        if formulario is None:
            return
        new_data = formulario.get_data()
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
            self._mostrar_vacio()
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
        self._actualizar_pendientes()

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
        self._actualizar_pendientes()
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
                logger.warning(f"Fallo inyectando RAM en Contactos: {e}")
                
            # ÚNICO MOMENTO DE LIMPIEZA AUTOMÁTICA TRAS GUARDAR CON ÉXITO
            self.pending_changes.clear()
            self._actualizar_pendientes()
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
    def _on_tab_changed(self):
        self._actualizar_barra()
        self._actualizar_kpis()
        self._mostrar_vacio()

        if not self.df_plataforma.empty:
            self.filter_tables()

    def _actualizar_barra(self):
        es_admins = self.tabs.currentIndex() == 0
        en_detalle = es_admins and self._flota_abierta is not None
        for i, boton in enumerate(self._botones_sec):
            boton.setChecked(i == self.tabs.currentIndex())
        self.btn_volver.setVisible(en_detalle)
        for w in (self.btn_importar, self.btn_corregir_tel):
            w.setVisible(es_admins)
        self._actualizar_pie()

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
        self._mostrar_vacio()
        animar_sobre_tabla(self.table_plat, 350)

    def _volver_a_flotas(self):
        self._flota_abierta = None
        self.stack_plat.setCurrentIndex(0)
        self._actualizar_barra()
        self.render_table()
        self._actualizar_kpis()
        self._mostrar_vacio()
        animar_sobre_tabla(self.table_flotas, 350)

    def _export_current_tab(self):
        if self.tabs.currentIndex() == 0:
            if self._flota_abierta is None:
                self.table_flotas.export_to_excel("Flotas_Contactos")
                return
            self.table_plat.export_to_excel("Contactos_Plataforma")
        else:
            df = self.model_emp.get_df()
            if df.empty:
                return QMessageBox.warning(self, "Exportar", "No hay datos visibles.")
            ruta, _ = QFileDialog.getSaveFileName(self, "Guardar Excel", "Empresas_PowerBI.xlsx", "Archivos Excel (*.xlsx)")
            if ruta:
                from src.ui.compartido.exportacion import iniciar_exportacion
                iniciar_exportacion(self, df, ruta, titulo="Empresas PowerBI")

    def load_data(self, clear_pending=False, repintar=True):
        """Método central de recarga. Protege pending_changes a menos que se indique clear_pending=True.
        `repintar=False` evita forzar un repintado mientras el módulo aún se está construyendo."""
        self.btn_reload.setEnabled(False)
        if clear_pending:
            self.pending_changes.clear()
            self._actualizar_pendientes()
        self._data_dirty = False
        self._firma_cargada = self._firma_archivos()

        self._plataforma_cargada = False
        self._empresas_cargada = False
        self.content_stack.setCurrentIndex(0)
        if repintar:
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
            if self.__dict__.get('_alta_pendiente') is not None:
                self._aplicar_alta_pendiente()

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
        logger.warning(f"No se pudo cargar 'Director de empresas' desde BBDD CLIENTES CM: {error_msg}")
        self.df_empresas = pd.DataFrame()
        self._on_tab_changed()
        self.filter_tables()
        self._empresas_cargada = True
        self._check_carga_completa()

    def _actualizar_kpis(self):
        """Título y resumen de la caja de la tabla."""
        df = self.df_plataforma
        total = len(df)
        flotas = int(df['Flota'].astype(str).str.strip().replace("", pd.NA).dropna().nunique()) if total and 'Flota' in df.columns else 0
        if self.tabs.currentIndex() == 0 and self._flota_abierta is not None:
            cdb, flota = self._flota_abierta
            n = len(self.model_plat.get_df())
            self._caja.lbl_titulo.setText(flota or "Sin flota")
            self._caja.lbl_subtitulo.setText(f"CDB {cdb or '-'} · {n} contactos")
        elif self.tabs.currentIndex() == 0:
            self._caja.lbl_titulo.setText("Administradores de flotas")
            self._caja.lbl_subtitulo.setText(f"{flotas} flotas · {total} contactos")
        else:
            self._caja.lbl_titulo.setText("Director de empresas")
            self._caja.lbl_subtitulo.setText(f"{len(self.df_empresas)} directores de empresa")

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
        
        if search_text != self._busqueda_previa:
            self._busqueda_previa = search_text
            if self.tabs.currentIndex() == 1:
                animar_sobre_tabla(self.table_emp, 650)

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
            self._restaurar_seleccion()
            
            try:
                anchos = {'★': 52, 'Nombre': 190, 'Apellidos': 190, 'Correo electrónico': 320, 'Número móvil': 170,
                          'Fecha de extracción': 160}
                # ID, CDB, Flota y Rol no se muestran: la flota ya se eligió en la lista y todos son administradores
                self._ajustar_columnas(self.table_plat, list(self.model_plat._df.columns), anchos,
                                       ('Nombre', 'Apellidos', 'Correo electrónico'))
            except Exception: pass
            
        elif not is_plat and not df_view.empty:
            self.model_emp.set_data(df_view)
            try:
                # Teléfono, Categoría y Responsable quedan solo en el panel y en el Excel exportado
                anchos = {'CDB': 120, 'Nombre': 260, 'RUT': 110, 'Correo electrónico': 230, 'Dirección': 250, 'Comuna': 130}
                self._ajustar_columnas(self.table_emp, list(self.model_emp._df.columns), anchos,
                                       ('Nombre', 'Correo electrónico', 'Dirección'))
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

    @staticmethod
    def _ajustar_columnas(tabla, columnas, anchos, flexibles):
        """Las columnas flexibles se reparten el ancho sobrante, así la tabla nunca necesita scroll lateral."""
        cab = tabla.horizontalHeader()
        for i, nombre in enumerate(columnas):
            tabla.setColumnHidden(i, nombre not in anchos)
            if nombre not in anchos:
                continue
            if nombre in flexibles:
                cab.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                cab.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                tabla.setColumnWidth(i, anchos[nombre])
        cab.setStretchLastSection(False)

    def _pintar_lista_flotas(self):
        df = self.table_flotas.apply_sort(self.filtered_flotas) if not self.filtered_flotas.empty else self.filtered_flotas
        self.model_flotas.set_data(df.reset_index(drop=True))
        try:
            self._ajustar_columnas(self.table_flotas, list(self.model_flotas._df.columns),
                                   {'CDB': 170, 'Flota': 460, 'Contactos': 130}, ('Flota',))
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

        menu = crear_menu(self)

        action_copy_cell = menu.accion(f"Copiar: '{texto_corto(celda_seleccionada)}'",
                                       habilitada=bool(celda_seleccionada) and col != 0)
        menu.addSeparator()

        sin_correo = not correo or correo.lower() == "nan"
        sin_tel = not telefono or telefono.lower() == "nan" or telefono == "-"
        action_copy_mail = menu.accion(f"Copiar correo ({correo if correo else 'N/A'})", 'fa5s.envelope', '#2563EB', not sin_correo)
        action_copy_tel = menu.accion(f"Copiar teléfono ({telefono if telefono else 'N/A'})", 'fa5s.phone-alt', '#10B981', not sin_tel)

        menu.addSeparator()
        action_delete = menu.accion("Eliminar administrador", 'fa5s.trash-alt', DANGER)

        selected = menu.exec(self.table_plat.viewport().mapToGlobal(pos))
        
        if selected == action_copy_cell: QApplication.clipboard().setText(celda_seleccionada)
        elif selected == action_copy_mail: QApplication.clipboard().setText(correo)
        elif selected == action_copy_tel: QApplication.clipboard().setText(telefono)
        elif selected == action_delete:
            self._handle_eliminar(row, "ficticio")