import os
import re
import sys
import qtawesome as qta
from PyQt6.QtWidgets import (QMainWindow, QMessageBox, QScrollArea, QWidget, QHBoxLayout, QVBoxLayout,
                             QPushButton, QLabel, QStackedWidget, QFrame, QLineEdit, QMenu, QSizePolicy, QProgressBar, QApplication,
                             QTabWidget, QGraphicsOpacityEffect)
from PyQt6.QtCore import QThread, QTimer, Qt, QSize, QPropertyAnimation, QEasingCurve, QSettings, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence, QPixmap

import config.settings
from config.settings import EXCEL_PATH, WATCH_DIR
from src.core.data_manager import DataManager
from src.core.excel_reader import ExcelReader
from src.core.backup_manager import BackupWorker
from src.core.perf_log import medir
from src.services import cm_bajas_service
from src.ui.transiciones import TransicionFundidoSubida, TransicionCirculo, instalar_transicion_pestanas, ms_restantes_animacion
from src.ui.boton_tema import BotonTema
from src.theme.tema import GestorTema, CLARO, OSCURO
from src.ui import sidebar_estilo
from src.ui.comercial_estilo import fuente_comercial
from src.ui import comercial_estilo as estilo_com
from src.theme.colors import (BACKGROUND, TEXT_PRIMARY, TEXT_SECONDARY, SURFACE, BORDER, BRAND_BLUE,
                               PRIMARY, SECONDARY, MODULE_DISPLAY_NAMES, MODULE_COLORS, DANGER)

# NOTA (imports diferidos): WatchdogThread, los 10 modulos de src.ui.* y
# MailDialog se importan de forma local, justo donde se usan (_start_watchdog,
# _instantiate_module, _open_mail_dialog) en vez de aqui arriba. Cada uno se
# usa en un unico punto del archivo (verificado), y ya se instancian de forma
# perezosa (solo cuando el usuario navega a esa seccion o el watchdog arranca
# tras la primera carga exitosa) — diferir tambien su import evita pagar ese
# costo antes de que la ventana principal exista.

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False): base_path = sys._MEIPASS
    else: base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)

# =========================================================
# CLASE PERSONALIZADA PARA PEGAR MÚLTIPLES VINS DE EXCEL
# =========================================================
# Limite de elementos que la busqueda global admite de una sola vez. Motivo
# (bug real reportado): pegar una lista de ~1548 VINs congelaba la app
# durante ~20s (Windows la marca "No responde" a partir de ~5s) porque cada
# modulo activo recorre la lista completa de terminos contra sus columnas de
# busqueda. Comercial ya se optimizo (ver
# comercial_services.construir_mascara_busqueda, ~0.9s para 1548 terminos),
# pero el resto de los modulos que escuchan esta misma barra global
# (Contratos, Operaciones, Provisiones, etc.) siguen con un costo
# proporcional a la cantidad de terminos pegados. Este limite protege a
# cualquiera de ellos, sin depender de que cada uno se optimice por separado.
MAX_TERMINOS_BUSQUEDA_GLOBAL = 200

# Debounce del buscador global (auditoria de rendimiento, fase 1, 21-09-2026):
# _on_global_search() filtra y reconstruye la UI del modulo activo (tablas,
# tarjetas, pandas), y sin esto se ejecutaba integro en el hilo principal por
# CADA tecla -- incluido el auto-repeat de mantener una tecla apretada --
# congelando la app con datasets grandes. Con este retraso el QLineEdit sigue
# mostrando cada caracter al instante (no se toca su propio texto); solo se
# retrasa el filtrado real hasta que el usuario deja de escribir. Ver
# _on_global_search_text_changed/_ejecutar_busqueda_global_pendiente.
DEBOUNCE_BUSQUEDA_GLOBAL_MS = 250

# Espera mínima antes de refrescar un módulo al navegar (valor histórico,
# se usa cuando no hay transición en curso).
ESPERA_MINIMA_REFRESCO_MS = 50
MARGEN_TRAS_TRANSICION_MS = 30


def _ms_restantes_transiciones(ventana, modulo):
    """Lo que falta de las animaciones que afectan al módulo: la transición
    entre módulos, el fundido del sidebar y la de las pestañas que lo
    contienen. Tolera ventana=None (tests que llaman _trigger_load_data sin
    una MainWindow real)."""
    restantes = [
        ms_restantes_animacion(getattr(ventana, '_fade_anim', None)),
    ]
    transicion = getattr(ventana, '_transicion_modulo', None)
    if isinstance(transicion, TransicionFundidoSubida):
        restantes.append(transicion.ms_restantes())

    widget = modulo if isinstance(modulo, QWidget) else None
    while widget is not None:
        transicion_tabs = getattr(widget, '_transicion_pestanas', None)
        if isinstance(transicion_tabs, TransicionFundidoSubida):
            restantes.append(transicion_tabs.ms_restantes())
        widget = widget.parentWidget()
    return max(restantes)


def _refrescar_modulo_tras_transicion(ventana, modulo):
    espera = max(ESPERA_MINIMA_REFRESCO_MS, _ms_restantes_transiciones(ventana, modulo) + MARGEN_TRAS_TRANSICION_MS)
    QTimer.singleShot(espera, lambda: _refrescar_modulo_visible(ventana, modulo))


def _refrescar_modulo_visible(ventana, modulo):
    # Módulos con refresh_if_dirty() (General, Comercial, Operaciones,
    # Contratos, Historial) solo reprocesan si quedaron marcados dirty; el
    # resto conserva load_data() incondicional en cada visita.
    if hasattr(modulo, 'refresh_if_dirty'):
        modulo.refresh_if_dirty()
    elif hasattr(modulo, 'load_data'):
        modulo.load_data()

    # Solo se vuelve a filtrar si el texto del módulo quedó distinto al de la
    # barra global: filtrar siempre reconstruía tarjetas/tablas completas en
    # cada navegación. Si el texto es el mismo, el load_data de arriba ya
    # filtra con él.
    search_bar = getattr(ventana, 'search_bar', None)
    if search_bar is not None and hasattr(modulo, 'search_input'):
        texto = search_bar.text()
        if modulo.search_input.text() != texto:
            ventana._aplicar_busqueda_a_modulo(modulo, texto)


class MultiSearchLineEdit(QLineEdit):
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Paste):
            text = QApplication.clipboard().text()
            if text:
                clean_text = text.replace('\n', ', ').replace('\r', '').replace('\t', ', ')
                clean_text = re.sub(r',\s*,', ',', clean_text).strip(', ')

                terminos = [t for t in clean_text.split(',') if t.strip()]
                if len(terminos) > MAX_TERMINOS_BUSQUEDA_GLOBAL:
                    clean_text = ', '.join(terminos[:MAX_TERMINOS_BUSQUEDA_GLOBAL])
                    QMessageBox.warning(
                        self, "Búsqueda muy grande",
                        f"Se pegaron {len(terminos)} elementos, pero la búsqueda admite "
                        f"hasta {MAX_TERMINOS_BUSQUEDA_GLOBAL} a la vez para no congelar la aplicación.\n\n"
                        f"Se buscarán únicamente los primeros {MAX_TERMINOS_BUSQUEDA_GLOBAL}. "
                        "Divide la lista en bloques más pequeños para buscar el resto."
                    )

                self.insert(clean_text)
            return
        super().keyPressEvent(event)

# =========================================================
# MOTOR DE AUDITORÍA ASÍNCRONA (El Detective del Watchdog)
# =========================================================
class CompareSnapshotThread(QThread):
    finished_signal = pyqtSignal(list)

    def __init__(self, reader):
        super().__init__()
        self.reader = reader

    def run(self):
        try:
            # Una sola lectura + clean(): se compara contra el snapshot y la
            # misma lectura queda precargada en DataManager, así la recarga
            # posterior (load_data_async) no vuelve a leer el archivo.
            from src.core.data_manager import leer_datos_principales
            ruta = config.settings.EXCEL_PATH
            mtime = os.path.getmtime(ruta)
            payload = leer_datos_principales(ruta)
            cambios = self.reader.compare_snapshot_desde_df(payload[0])
            DataManager().guardar_precarga_principal(payload, ruta, mtime)
            self.finished_signal.emit(cambios)
        except Exception as e:
            print(f"Error en CompareSnapshotThread: {e}")
            self.finished_signal.emit([])

class ActualizarBaseNotificacionesThread(QThread):
    """Deja la base de comparación de las notificaciones al día con los datos
    que acaba de guardar la propia app, para que no aparezcan después como
    cambios ajenos."""

    def __init__(self, reader, df):
        super().__init__()
        self.reader = reader
        self.df = df

    def run(self):
        try:
            self.reader.compare_snapshot_desde_df(self.df)
        except Exception as e:
            print(f"Error en ActualizarBaseNotificacionesThread: {e}")


class ReconciliacionCasosExpiredThread(QThread):
    """Reconciliación de Revisión CM por ESTADO DEL CM = Expired
    (cm_bajas_service) fuera del hilo de UI."""

    def __init__(self, df_master, casos_path):
        super().__init__()
        self.df_master = df_master
        self.casos_path = casos_path

    def run(self):
        from datetime import datetime
        try:
            cm_bajas_service.procesar_reconciliacion_estado_expired(
                df_pruebas_actual=self.df_master,
                periodo_deteccion=datetime.now().strftime('%Y-%m'),
                casos_path=self.casos_path,
            )
        except Exception as e:
            print(f"No se pudo reconciliar los casos de Revisión CM por estado Expired al cargar datos: {e}")


class CorreccionEstadoComercialThread(QThread):
    """Guarda en PruebasFM el ESTADO COMERCIAL corregido de las unidades que ya
    están conectadas, fuera del hilo de UI."""
    finished_signal = pyqtSignal(bool, object)

    def __init__(self, cambios):
        super().__init__()
        self.cambios = cambios

    def run(self):
        try:
            from src.core.excel_writer import ExcelWriter
            ok = bool(ExcelWriter().update_cells(self.cambios, module_name="Sistema"))
        except Exception as e:
            print(f"No se pudo corregir ESTADO COMERCIAL de unidades conectadas: {e}")
            ok = False
        self.finished_signal.emit(ok, self.cambios)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gestor SSCC")
        
        self.setWindowFlags(Qt.WindowType.Window | 
                            Qt.WindowType.WindowTitleHint | 
                            Qt.WindowType.WindowSystemMenuHint |
                            Qt.WindowType.WindowMinimizeButtonHint | 
                            Qt.WindowType.WindowCloseButtonHint |
                            Qt.WindowType.WindowMaximizeButtonHint)
        
        self.setMinimumSize(1200, 700)

        self.sidebar_expanded = True
        self.menu_buttons = {}
        self.menu_icons = {}
        self.menu_texts = {}
        self.loaded_modules = {}
        self.notification_count = 0 

        self.central_widget = QWidget()
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.reader = ExcelReader()

        self._setup_sidebar()
        self._setup_content_area()
        self._show_loading_screen()

        # Fase 6: el banner de bloqueo vive FUERA de self.central_widget a
        # proposito. Qt propaga setEnabled(False) a todos los descendientes
        # de un widget deshabilitado (los pinta atenuados/"grises"), y este
        # banner debe seguir viendose con sus colores reales (rojo/blanco)
        # exactamente cuando central_widget esta deshabilitado. Por eso el
        # widget central real de la ventana pasa a ser este contenedor
        # (root_widget), con el banner y central_widget como hermanos.
        self._setup_lock_banner()

        root_widget = QWidget()
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.lock_banner)
        root_layout.addWidget(self.central_widget)
        self.setCentralWidget(root_widget)
        GestorTema.instancia().registrar_ventana(self)

        self.settings = QSettings("GestorApp", "Dashboard")
        self._load_settings()

        self.data_manager = DataManager()
        self.data_manager.data_ready.connect(self._on_data_loaded_success)
        self.data_manager.load_error.connect(self._on_data_load_error)
        
        self.data_manager.load_data_async()
        # Contactos y BBDD CLIENTES CM se leen ya, con la pantalla de carga a
        # la vista: si se leen después compiten con el primer módulo que se abre
        self.data_manager.load_contactos_async()
        from src.ui.general import precargar_director_empresa_pbi
        precargar_director_empresa_pbi()

        self._backup_auto_worker = BackupWorker(modo="auto")
        self._backup_auto_worker.finished_signal.connect(self._on_backup_automatico_finalizado)
        self._backup_auto_worker.start()

        self._start_file_lock_monitor()

        self._setup_shortcuts()

    def _load_settings(self):
        geom = self.settings.value("window_geometry")
        if geom:
            self.restoreGeometry(geom)
        else:
            self.showMaximized() 

        self.sidebar_expanded = self.settings.value("sidebar_expanded", True, type=bool)
        if not self.sidebar_expanded:
            collapsed_width = sidebar_estilo.ANCHO_COLAPSADO
            self.sidebar.setMinimumWidth(collapsed_width)
            self.sidebar.setMaximumWidth(collapsed_width)
            self._aplicar_estado_sidebar(False)

    def _on_boton_tema(self, oscuro):
        modo = OSCURO if oscuro else CLARO
        contenedor = self.centralWidget()
        if contenedor is None or not self.isVisible():
            GestorTema.instancia().aplicar(modo)
            return
        centro = self.btn_tema.mapTo(contenedor, self.btn_tema.rect().center())

        def _cambiar():
            GestorTema.instancia().aplicar(modo)
            self.btn_tema.reiniciar_animacion()

        self._transicion_tema.iniciar(contenedor, centro, _cambiar)

    def _on_tema_cambiado(self, modo):
        color_icono = '#C3CEDF' if modo == OSCURO else '#4B5563'
        self.mail_btn.setIcon(qta.icon('fa5s.envelope', color=color_icono))
        self.notif_btn.setIcon(qta.icon('fa5s.bell', color=color_icono))
        self.config_btn.setIcon(qta.icon('fa5s.cog', color=color_icono))
        if self.btn_tema.isChecked() != (modo == OSCURO):
            self.btn_tema.fijar_sin_animar(modo == OSCURO)

    def _show_loading_screen(self):
        from src.ui.guardado_overlay import crear_tarjeta_carga
        self.loading_page = QWidget()
        layout = QVBoxLayout(self.loading_page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(
            crear_tarjeta_carga("Cargando y formateando bases de datos…", "Esto tomará unos segundos."),
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self.workspace.addWidget(self.loading_page)
        self.workspace.setCurrentWidget(self.loading_page)

    def _on_data_loaded_success(self):
        # Medicion Fase 0 (auditoria de rendimiento, 17-09-2026): tiempo de
        # este handler -- ver src/core/perf_log.py. Desde la Fase 2
        # (17-09-2026) esta medicion YA NO incluye la construccion de Vista
        # General: eso se difiere con QTimer.singleShot(0, ...) para no
        # bloquear la aparicion de MainWindow (ver comentario mas abajo,
        # antes de la linea que programa _cargar_vista_general_inicial).
        # Ese costo se sigue viendo aparte, en la medicion
        # "instanciar módulo: Vista General".
        with medir("data_ready -> _on_data_loaded_success (sin incluir Vista General, diferida)"):
            self._on_data_loaded_success_impl()

    def _on_data_loaded_success_impl(self):
        print("Excel cargado en memoria exitosamente.")
        for btn in self.menu_buttons.values():
            btn.setEnabled(True)
        self.config_btn.setEnabled(True)

        # Cuarto punto de disparo de Revisión CM por ESTADO DEL CM = Expired
        # (11-09-2026, pedido explícito del usuario): los otros tres puntos
        # (guardar/importar en Contratos, guardar en Comercial) solo
        # reaccionan a ediciones nuevas. Un VIN que YA estaba en Expired al
        # cargar los datos (arranque, recarga manual, watchdog) nunca
        # disparaba ninguno de esos tres, así que su caso nunca se generaba
        # hasta que alguien guardara algo sin relación. data_ready se emite
        # en cada carga real de PruebasFM (y también tras guardados de
        # Comercial, donde ya se reconcilia aparte -- reconciliar de nuevo
        # aquí es inofensivo, la función es idempotente). No toca
        # PruebasFM.xlsx, solo CasosBajaCM.csv.
        #
        # Fase 1 de la auditoria de rendimiento (17-09-2026): se evaluo
        # deduplicar esta llamada con un flag compartido en el DataManager
        # cuando ya se acababa de reconciliar desde Comercial, pero se
        # revirtio por el riesgo de que ese flag quede "pegado" fuera del
        # ciclo esperado (ver test_main_window.TestDataLoadedTriggersRevisionCmReconciliation)
        # y termine saltandose una reconciliacion real. Se mantiene la doble
        # ejecucion ocasional (idempotente, solo I/O de un CSV chico) en vez
        # de arriesgar ese silencioso "se salta cuando no debia".
        #
        # Auditoría 28-09-2026: se ejecuta en un hilo de fondo (lee y escribe
        # CasosBajaCM.csv en la carpeta de OneDrive en cada data_ready).
        self._reconciliar_casos_expired_en_fondo()
        self._actualizar_base_notificaciones_tras_guardado_propio()
        self._corregir_estado_comercial_conectados()

        current_widget = self.workspace.currentWidget()
        if current_widget is None or current_widget not in self.loaded_modules.values():
            self.menu_buttons["Vista General"].setChecked(True)
            # Fase 2 (auditoria de rendimiento, 17-09-2026): construir Vista
            # General (instanciar GeneralModule + agregarlo al workspace) es
            # la parte mas pesada de este callback (ver medicion con
            # perf_log: ~75-80% del tiempo total de data_ready ->
            # _on_data_loaded_success). Ejecutada sincronicamente, la
            # ventana principal no se pintaba hasta que Vista General ya
            # estaba completamente construida y cargada.
            # QTimer.singleShot(0, ...) devuelve el control al event loop de
            # inmediato: MainWindow se pinta (ya con su pantalla de carga,
            # ver _show_loading_screen) y la construccion de Vista General
            # continua en la siguiente vuelta del loop, con la ventana ya
            # visible. No hay condicion de carrera (Qt sigue de un solo
            # hilo) ni carga duplicada: _cargar_vista_general_inicial
            # reevalua el mismo chequeo de currentWidget al ejecutarse.
            QTimer.singleShot(0, self._cargar_vista_general_inicial)

        if not hasattr(self, 'watcher_thread'):
            self._start_watchdog()

    def _actualizar_base_notificaciones_tras_guardado_propio(self):
        # La base de comparación solo se actualizaba al detectar un cambio externo:
        # las ediciones propias se acumulaban y salían como aviso tardío cuando
        # OneDrive tocaba el archivo pasada la ventana de silencio.
        import time
        from src.core.file_watcher import VENTANA_SILENCIO_GUARDADO_SEGUNDOS
        dm = self.data_manager
        try:
            if time.time() - float(dm.save_timestamp) > VENTANA_SILENCIO_GUARDADO_SEGUNDOS:
                return
        except (TypeError, ValueError):
            return
        if dm.df_master is None or dm.df_master.empty:
            return
        for nombre in ('_base_notif_thread', 'compare_thread'):
            hilo = getattr(self, nombre, None)
            if hilo is not None and hilo.isRunning():
                return
        self._base_notif_thread = ActualizarBaseNotificacionesThread(self.reader, dm.df_master.copy())
        self._base_notif_thread.start()

    def _corregir_estado_comercial_conectados(self):
        """Una unidad "Conectado" en Servicios Conectados no puede seguir en ESTADO
        COMERCIAL "Activación Pendiente": se pasa a Vigente (misma regla que el
        botón "Marcar como Vigente" de Comercial). Cada VIN se intenta una sola
        vez por sesión, para no reintentar en bucle si el guardado falla."""
        from src.core.constants import (COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, ESTADO_CONECTADO,
                                        VALOR_ESTADO_COMERCIAL_VIGENTE)
        dm = self.data_manager
        df = dm.df_master
        if df is None or df.empty or getattr(dm, 'is_app_saving', False):
            return
        if COL_ESTADO_COMERCIAL not in df.columns or COL_ESTADO_ACTIVACION not in df.columns or 'VIN' not in df.columns:
            return
        hilo = getattr(self, '_correccion_estado_thread', None)
        if hilo is not None and hilo.isRunning():
            return
        estado_com = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper().str.replace('Ó', 'O')
        estado_act = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
        vins = df.loc[(estado_com == 'ACTIVACION PENDIENTE') & (estado_act == ESTADO_CONECTADO), 'VIN']
        intentados = getattr(self, '_vins_autocorregidos', set())
        cambios = {}
        for vin in vins.astype(str).str.strip().str.upper():
            if vin and vin != 'NAN' and vin not in intentados and vin not in cambios:
                cambios[vin] = {'VIN': vin, 'cambios': {COL_ESTADO_COMERCIAL: VALOR_ESTADO_COMERCIAL_VIGENTE}}
        if not cambios:
            return
        self._vins_autocorregidos = intentados | set(cambios)
        self._correccion_estado_thread = CorreccionEstadoComercialThread(cambios)
        self._correccion_estado_thread.finished_signal.connect(self._on_correccion_estado_finalizada)
        self._correccion_estado_thread.start()

    def _on_correccion_estado_finalizada(self, ok, cambios):
        if not ok:
            return
        from src.services import comercial_services
        dm = self.data_manager
        if dm.df_master is not None and not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, cambios)
            dm.data_ready.emit()

    def _reconciliar_casos_expired_en_fondo(self):
        dm = self.data_manager
        if dm.df_master is None or dm.df_master.empty:
            return
        # Un solo hilo a la vez: si llega otro data_ready mientras corre, se
        # relanza al terminar con el df_master más reciente.
        hilo_actual = getattr(self, '_reconciliacion_thread', None)
        if hilo_actual is not None and hilo_actual.isRunning():
            self._reconciliacion_pendiente = True
            return
        self._reconciliacion_pendiente = False
        self._reconciliacion_thread = ReconciliacionCasosExpiredThread(
            dm.df_master.copy(), config.settings.CASOS_BAJA_CM_PATH
        )
        self._reconciliacion_thread.finished.connect(self._on_reconciliacion_finalizada)
        self._reconciliacion_thread.start()

    def _on_reconciliacion_finalizada(self):
        if getattr(self, '_reconciliacion_pendiente', False):
            self._reconciliar_casos_expired_en_fondo()

    def _cargar_vista_general_inicial(self):
        current_widget = self.workspace.currentWidget()
        if current_widget is None or current_widget not in self.loaded_modules.values():
            # Se instancia (y arranca su propia carga async, ver
            # GeneralDataPrepThread) sin pasar todavía por _load_module: esa
            # función haría setCurrentWidget de inmediato y mostraría la
            # pestaña ya armada pero sin tarjetas (auditoría de rendimiento,
            # 24-09-2026 -- Vista General agrupa/ordena todo el comercial
            # real, que puede tomar varios segundos y antes quedaba a la
            # vista vacía mientras tanto). En su lugar se deja la pantalla
            # "Cargando y formateando bases de datos..." (_show_loading_screen)
            # puesta hasta que Vista General avise que ya tiene sus
            # clientes/flota/unidades listos (primera_carga_lista).
            with medir("instanciar módulo: Vista General"):
                from src.ui.general import GeneralModule
                module = GeneralModule()
            self.loaded_modules["Vista General"] = module
            self.workspace.addWidget(module)

            def _mostrar_vista_general_cuando_este_lista():
                # Si el usuario ya navegó a otro módulo mientras Vista
                # General terminaba de cargar en segundo plano, no lo
                # interrumpimos -- solo mostramos el resultado si seguimos
                # en la pantalla de carga.
                if self.workspace.currentWidget() is self.loading_page:
                    self.workspace.setCurrentWidget(module)
                    self._update_module_chip("Vista General")

            module.primera_carga_lista.connect(_mostrar_vista_general_cuando_este_lista)

    def _on_backup_automatico_finalizado(self, resultado):
        if not resultado:
            return 
        if resultado.get("error_fatal"):
            print(f"[BACKUP AUTOMÁTICO] No se pudo completar: {resultado['error_fatal']}")
        elif resultado.get("fallidos"):
            print(f"[BACKUP AUTOMÁTICO] Completado con advertencias. Fallidos: {resultado['fallidos']}")
        else:
            print(f"[BACKUP AUTOMÁTICO] Snapshot semanal creado en: {resultado.get('carpeta')}")

    def _on_data_load_error(self, error):
        if hasattr(self, 'watcher_thread'):
            self.watcher_thread.stop()
            
        self.loading_page.hide()
        
        for btn in self.menu_buttons.values():
            btn.setChecked(False)
            btn.setEnabled(False)
        # Configuración es lo único accesible sin datos, para corregir las rutas
        self.config_btn.setEnabled(True)

        error_widget = QWidget()
        err_layout = QVBoxLayout(error_widget)
        err_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        err_layout.setSpacing(15)

        lbl_icon = QLabel()
        lbl_icon.setPixmap(qta.icon('fa5s.exclamation-triangle', color='#EF4444').pixmap(QSize(60, 60)))
        lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_err = QLabel(f"<b style='font-size: 20px; color: #EF4444;'>Error Crítico: No se encontró la Base de Datos</b><br><br>"
                         f"<span style='color: #4B5563; font-size: 14px;'>{error}</span><br><br>"
                         f"<span style='color: #1E293B; font-size: 14px;'>Por favor, ingresa a <b>Configuración</b> para actualizar las rutas de tus archivos Excel.</span>")
        lbl_err.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_go_config = QPushButton(" Ir a Configuración para Arreglar Rutas")
        btn_go_config.setIcon(qta.icon('fa5s.cog', color='white'))
        btn_go_config.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_go_config.setStyleSheet("background-color: #1C6BBA; color: white; border-radius: 6px; font-weight: bold; padding: 12px 24px; font-size: 14px;")
        
        btn_go_config.clicked.connect(self._go_to_configuracion)

        err_layout.addStretch()
        err_layout.addWidget(lbl_icon)
        err_layout.addWidget(lbl_err)
        err_layout.addSpacing(10)
        err_layout.addWidget(btn_go_config, alignment=Qt.AlignmentFlag.AlignCenter)
        err_layout.addStretch()

        self.workspace.addWidget(error_widget)
        self.workspace.setCurrentWidget(error_widget)
        self.loaded_modules.clear()

    def _start_file_lock_monitor(self):
        # Fase 5: bloqueo funcional de la app cuando alguno de los 4
        # archivos principales esta confirmado OCUPADO por FileLockMonitor.
        # Independiente de la carga de datos (no espera a data_ready ni al
        # watchdog): arranca en paralelo, en su propio QThread, y solo
        # actua cuando el propio monitor confirma un cambio real de estado
        # (nunca antes de que pueda determinarlo correctamente).
        from src.core.file_lock_monitor import FileLockMonitorThread
        from src.core.app_lock_coordinator import AppLockCoordinator

        self.file_lock_monitor_thread = FileLockMonitorThread()
        self.app_lock_coordinator = AppLockCoordinator(self.file_lock_monitor_thread.estado_cambiado)
        self.app_lock_coordinator.estado_app_cambiado.connect(self._on_app_lock_state_changed)
        self.app_lock_coordinator.archivos_ocupados_cambiado.connect(self._on_archivos_ocupados_cambiado)
        self.file_lock_monitor_thread.start()

    def _setup_lock_banner(self):
        # Fase 6: banner rojo permanente mientras la app este bloqueada.
        # Oculto por defecto (hide()): un widget oculto no reserva espacio
        # en el layout, asi que no deja hueco vacio cuando no hay nada
        # bloqueado.
        self.lock_banner = QFrame()
        self.lock_banner.setObjectName("lock_banner")
        self.lock_banner.setStyleSheet(f"""
            QFrame#lock_banner {{ background-color: {DANGER}; }}
            QFrame#lock_banner QLabel {{ background: transparent; color: white; }}
        """)

        banner_layout = QHBoxLayout(self.lock_banner)
        banner_layout.setContentsMargins(24, 12, 24, 12)
        banner_layout.setSpacing(14)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(qta.icon('fa5s.exclamation-triangle', color='white').pixmap(QSize(26, 26)))

        texto_layout = QVBoxLayout()
        texto_layout.setSpacing(2)

        titulo_lbl = QLabel("Aplicación bloqueada")
        titulo_lbl.setStyleSheet("font-size: 15px; font-weight: bold;")

        descripcion_lbl = QLabel("Uno o más archivos principales están siendo utilizados por Excel. Cierra Excel para continuar.")
        descripcion_lbl.setStyleSheet("font-size: 12px;")
        descripcion_lbl.setWordWrap(True)

        self.lock_banner_archivos_lbl = QLabel("")
        self.lock_banner_archivos_lbl.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.lock_banner_archivos_lbl.setWordWrap(True)

        texto_layout.addWidget(titulo_lbl)
        texto_layout.addWidget(descripcion_lbl)
        texto_layout.addWidget(self.lock_banner_archivos_lbl)

        banner_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignTop)
        banner_layout.addLayout(texto_layout, stretch=1)

        self.lock_banner.hide()

    def _actualizar_banner_archivos_ocupados(self):
        from src.core.file_lock_monitor import ETIQUETAS_ARCHIVOS_PRINCIPALES
        claves_ocupadas = self.app_lock_coordinator.archivos_ocupados()
        # Se recorre ETIQUETAS_ARCHIVOS_PRINCIPALES (orden fijo) en vez del
        # set devuelto por el coordinador (orden no garantizado), para que
        # la lista siempre aparezca en el mismo orden aunque cambie cual se
        # libero primero.
        nombres = [etiqueta for clave, etiqueta in ETIQUETAS_ARCHIVOS_PRINCIPALES.items() if clave in claves_ocupadas]
        self.lock_banner_archivos_lbl.setText("• " + "\n• ".join(nombres) if nombres else "")

    def _on_app_lock_state_changed(self, bloqueada):
        # Bloqueo funcional (Fase 5, sin cambios): deshabilita toda la
        # interfaz mientras algun archivo principal este confirmado
        # ocupado. setEnabled(False) es reversible con una sola linea y no
        # interrumpe el hilo principal de Qt (no hay freeze: solo deja de
        # aceptar interaccion).
        self.central_widget.setEnabled(not bloqueada)

        # Fase 6: alerta visual permanente mientras dure el bloqueo.
        if bloqueada:
            self._actualizar_banner_archivos_ocupados()
        self.lock_banner.setVisible(bloqueada)

    def _on_archivos_ocupados_cambiado(self):
        # Se dispara aunque el booleano agregado no cambie (ej. con dos
        # archivos ocupados, se libera solo uno): mantiene la lista visible
        # del banner sincronizada con el conjunto real, incluso mientras la
        # app sigue bloqueada.
        self._actualizar_banner_archivos_ocupados()

    def _start_watchdog(self):
        if not EXCEL_PATH or not os.path.exists(EXCEL_PATH):
            print("Watchdog omitido: No hay una ruta de Excel válida configurada.")
            return

        from src.core.file_watcher import WatchdogThread
        filename = os.path.basename(EXCEL_PATH)
        if WATCH_DIR and os.path.exists(WATCH_DIR):
            self.watcher_thread = WatchdogThread(WATCH_DIR, filename)
            self.watcher_thread.file_changed_signal.connect(self._on_excel_modified)
            # WorkbookCache (piloto 22-09-2026): esta señal ya llega filtrada
            # por ExcelHandler.on_modified (ignora los guardados propios de
            # la app via DataManager.is_app_saving/save_timestamp), asi que
            # aqui siempre es un cambio externo genuino de EXCEL_PATH -- el
            # unico archivo que este WatchdogThread observa.
            self.watcher_thread.file_changed_signal.connect(self._invalidar_workbook_cache_excel_principal)
            self.watcher_thread.start()

    def _invalidar_workbook_cache_excel_principal(self):
        from src.core.workbook_cache import WorkbookCache
        WorkbookCache.instancia().invalidar(EXCEL_PATH)

    def _on_excel_modified(self):
        from datetime import datetime
        current_time = datetime.now().strftime("%H:%M:%S")
        self.last_update_label.setText(f"Última act. Excel: {current_time}")
        self.last_update_label.setStyleSheet("color: #D97706; font-weight: bold;") 
        
        self.notif_btn.setIcon(qta.icon('fa5s.sync', color='#1C6BBA', animation=qta.Spin(self.notif_btn)))
        
        self.compare_thread = CompareSnapshotThread(self.reader)
        self.compare_thread.finished_signal.connect(self._on_snapshot_finished)
        self.compare_thread.start()

    @staticmethod
    def _detalle_archivo_modificado():
        """Texto del aviso: qué archivo cambió, dónde está y cuándo se modificó."""
        from datetime import datetime
        nombre = os.path.basename(EXCEL_PATH) if EXCEL_PATH else "la base de datos"
        texto = f"Se detectaron cambios recientes en el archivo {nombre}."
        try:
            modificado = datetime.fromtimestamp(os.path.getmtime(EXCEL_PATH)).strftime("%d-%m-%Y %H:%M:%S")
            texto += f"\nÚltima modificación: {modificado}\nUbicación: {os.path.dirname(EXCEL_PATH)}"
        except (OSError, TypeError):
            pass
        return texto + "\nPuede haberlo cambiado otra persona o la sincronización de OneDrive/SharePoint."

    def _on_snapshot_finished(self, cambios):
        self.notif_btn.setIcon(qta.icon('fa5s.bell', color='#C3CEDF' if GestorTema.instancia().modo == OSCURO else '#4B5563'))
        
        panel = self.__dict__.get('panel_notificaciones')
        if cambios and panel is not None:
            panel.registrar("RM_CONTRATOS", cambios)

        # Aunque la comparación no encuentre diferencias (columnas fuera del
        # snapshot, lectura a medias, auto-heal), el watchdog ya confirmó un
        # cambio externo: los datos se recargan igual.
        has_pending_changes = False
        pantallas_pendientes = []

        for nombre_modulo, loaded_widget in self.loaded_modules.items():
            if hasattr(loaded_widget, 'pending_changes') and loaded_widget.pending_changes:
                has_pending_changes = True
                pantallas_pendientes.append(str(nombre_modulo))

        if has_pending_changes:
            msg = QMessageBox(self)
            msg.setWindowTitle("Base de datos modificada")
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setText(self._detalle_archivo_modificado())
            msg.setInformativeText("Tienes cambios sin guardar en: " + (", ".join(pantallas_pendientes) or "tu pantalla actual") + ".\n\n"
                                   "• Si presionas 'Guardar mis cambios', sobrescribirás la base de datos.\n"
                                   "• Si deseas ver los cambios externos, descarta tu trabajo presionando 'Recargar'.")
            
            btn_guardar = msg.addButton("Guardar mis cambios", QMessageBox.ButtonRole.AcceptRole)
            btn_recargar = msg.addButton("Descartar y Recargar", QMessageBox.ButtonRole.DestructiveRole)
            msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)

            msg.exec()

            if msg.clickedButton() == btn_guardar:
                self._trigger_save_on_current_module()
            elif msg.clickedButton() == btn_recargar:
                self.data_manager.load_data_async()
        else:
            self.data_manager.load_data_async()

    def _update_notification_badge(self):
        if self.notification_count > 0:
            texto = str(self.notification_count) if self.notification_count < 100 else "99+"
            self.badge_label.setText(texto)
            # El círculo se ensancha hacia la izquierda según la cifra, sin salirse del botón
            ancho = max(16, self.badge_label.fontMetrics().horizontalAdvance(texto) + 10)
            self.badge_label.setFixedSize(ancho, 16)
            self.badge_label.move(36 - ancho, 0)
            self.badge_label.show()
        else:
            self.badge_label.hide()

    def _on_no_leidos_cambiado(self, cantidad):
        self.notification_count = cantidad
        self._update_notification_badge()

    def _show_notifications(self):
        if self.notification_count > 0:
            self.notification_count = 0
            self._update_notification_badge()
        self.notif_menu.exec(self.notif_btn.mapToGlobal(self.notif_btn.rect().bottomLeft()))

    def closeEvent(self, event):
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("sidebar_expanded", self.sidebar_expanded)
        
        if "Comercial" in self.loaded_modules:
            self.loaded_modules["Comercial"].table.save_state()
        if "Operaciones" in self.loaded_modules:
            self.loaded_modules["Operaciones"].table.save_state()
        if "Provisiones" in self.loaded_modules:
            self.loaded_modules["Provisiones"].table.save_state()
            
        if hasattr(self, 'watcher_thread'):
            self.watcher_thread.stop()
        if hasattr(self, 'file_lock_monitor_thread'):
            self.file_lock_monitor_thread.stop()
        # No cortar una escritura de CasosBajaCM.csv a medias.
        hilo_reconciliacion = getattr(self, '_reconciliacion_thread', None)
        if hilo_reconciliacion is not None and hilo_reconciliacion.isRunning():
            hilo_reconciliacion.wait(10000)
        super().closeEvent(event)

    def _setup_sidebar(self):
        # Estilo de dashboard-v2.html (ver sidebar_estilo.py): el
        # degradado y la barra del ítem activo los pinta FondoSidebar
        fuente_comercial(self.font())  # registra Inter
        self.sidebar = sidebar_estilo.FondoSidebar()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(sidebar_estilo.ANCHO_EXPANDIDO)

        self._sidebar_animating = False

        self.animation = QPropertyAnimation(self.sidebar, b"minimumWidth")
        self.animation.setDuration(250)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuart)
        self.animation.valueChanged.connect(self.sidebar.setMaximumWidth)
        self.animation.finished.connect(self._on_sidebar_animation_finished)

        # Layout externo sin márgenes: permite que la foto del camión llegue
        # hasta los bordes del sidebar. El contenido con márgenes vive en
        # sidebar_content, dentro de este layout.
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_layout.setSpacing(0)

        # Cabecera: marca a la izquierda y botón para plegar/desplegar
        self.cabecera_sidebar = QFrame()
        self.cabecera_sidebar.setObjectName("cabeceraSidebar")
        self.cabecera_sidebar.setFixedHeight(84)
        self.cabecera_sidebar.setStyleSheet(sidebar_estilo.QSS_CABECERA)
        cabecera_layout = QHBoxLayout(self.cabecera_sidebar)
        cabecera_layout.setContentsMargins(22, 0, 16, 0)

        self.logo_container = QWidget()
        self.logo_container.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logo_container.setToolTip("Ocultar/Mostrar menú lateral")
        self.logo_container.mousePressEvent = lambda e: self._toggle_sidebar()
        logo_layout = QVBoxLayout(self.logo_container)
        logo_layout.setContentsMargins(0, 0, 0, 0)
        logo_layout.setSpacing(3)
        logo_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.empresa_lbl = QLabel("EMPRESA")
        self.empresa_lbl.setStyleSheet(sidebar_estilo.QSS_MARCA)
        self.sistema_lbl = QLabel("Sistema de Gestión")
        self.sistema_lbl.setStyleSheet(sidebar_estilo.QSS_SUBTITULO)
        logo_layout.addWidget(self.empresa_lbl)
        logo_layout.addWidget(self.sistema_lbl)
        cabecera_layout.addWidget(self.logo_container, stretch=1)

        self.btn_plegar_sidebar = QPushButton()
        self.btn_plegar_sidebar.setFixedSize(34, 34)
        self.btn_plegar_sidebar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_plegar_sidebar.setStyleSheet(sidebar_estilo.QSS_BOTON_PLEGAR)
        self.btn_plegar_sidebar.clicked.connect(self._toggle_sidebar)
        cabecera_layout.addWidget(self.btn_plegar_sidebar)
        self.sidebar_layout.addWidget(self.cabecera_sidebar)

        self.sidebar_content = QWidget()
        content_layout = QVBoxLayout(self.sidebar_content)
        content_layout.setContentsMargins(sidebar_estilo.MARGEN_NAV, 0, sidebar_estilo.MARGEN_NAV, 20)
        content_layout.setSpacing(4)
        self.sidebar_layout.addWidget(self.sidebar_content)

        self.etiqueta_menu_sidebar = QLabel("MENÚ")
        self.etiqueta_menu_sidebar.setStyleSheet(sidebar_estilo.QSS_ETIQUETA)
        self.etiqueta_menu_sidebar.setContentsMargins(12, 22, 0, 8)
        content_layout.addWidget(self.etiqueta_menu_sidebar)

        # Menús con iconos adaptados para parecerse más a la imagen
        menus = [
            ("Dashboard", "fa5s.chart-pie", "Dashboard BI", None),
            ("Clientes y Flota", "fa5s.building", "Vista General", None),
            ("Comercial", "fa5s.handshake", "Comercial", None),
            ("Operaciones", "fa5s.shipping-fast", "Operaciones", None),
            ("Ingresos y Conciliación", "fa5s.balance-scale", "Ingresos y Conciliación",
                [("Provisiones", "fa5s.piggy-bank"), ("Contratos (CM)", "fa5s.file-signature"),
                 ("Facturación Manual", "fa5s.file-invoice-dollar"), ("JustTime", "fa5s.stopwatch")]),
            ("Administración", "fa5s.archive", "Administración",
                [("Historial", "fa5s.history"), ("Instalaciones", "fa5s.satellite-dish"),
                 ("Contactos", "fa5s.address-book"), ("Ejecutivos", "fa5s.user-tie"),
                 ("Clientes", "fa5s.building")]),
        ]
        # Configuración no vive en el sidebar: tiene su propio botón en el header

        self.group_definitions = {}

        for display_text, icon_name, internal_key, group_keys in menus:
            self.menu_icons[internal_key] = icon_name
            self.menu_texts[internal_key] = f"   {display_text}" # Espaciado interno tras el ícono
            if group_keys:
                self.group_definitions[internal_key] = group_keys

            btn = sidebar_estilo.BotonMenuSidebar(self.menu_texts[internal_key])
            btn.setIcon(qta.icon(icon_name, color='#D5DFF0', color_active='white', color_on='white'))
            btn.setIconSize(QSize(17, 17))
            btn.setStyleSheet(sidebar_estilo.qss_boton_menu(colapsado=False))
            btn.setCheckable(True)

            btn.setToolTip(f"Ir a {display_text}")
            btn.setEnabled(False)
            btn.clicked.connect(lambda checked, t=internal_key: self._on_menu_clicked(t))

            content_layout.addWidget(btn)
            self.menu_buttons[internal_key] = btn

        content_layout.addStretch()
        self.sidebar.registrar_botones(self.menu_buttons.values())

        # Foto del camión Empresa Demo FH al pie del sidebar. Se agrega al layout
        # externo (sin márgenes) para que cubra el sidebar de borde a borde,
        # en vez de quedar recortada por los márgenes del contenido. El PNG
        # ya trae el cielo de la parte superior desvanecido a transparente
        # (ver sidebar_truck.png) para que se funda con el degradado en vez
        # de cortar en un borde recto.
        self.truck_decoration = QLabel()
        self.truck_decoration.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.truck_decoration.setScaledContents(True)
        truck_pixmap = QPixmap(get_resource_path(os.path.join("src", "assets", "sidebar_truck.png")))
        aspect_ratio = truck_pixmap.height() / truck_pixmap.width() if truck_pixmap.width() else 1
        ancho = sidebar_estilo.ANCHO_EXPANDIDO
        self.truck_decoration.setFixedSize(ancho, round(ancho * aspect_ratio))
        self.truck_decoration.setPixmap(truck_pixmap)
        self.sidebar_layout.addWidget(self.truck_decoration)

        self._aplicar_estado_sidebar(True)
        self.main_layout.addWidget(self.sidebar)

    def _aplicar_estado_sidebar(self, expandido):
        """Contenido del menú lateral expandido o plegado (sin animar el ancho)."""
        self.logo_container.setVisible(expandido)
        self.etiqueta_menu_sidebar.setText("MENÚ" if expandido else "")
        self.btn_plegar_sidebar.setIcon(qta.icon('fa5s.angle-double-left' if expandido else 'fa5s.angle-double-right',
                                                 color='white'))
        self.btn_plegar_sidebar.setToolTip("Ocultar menú lateral" if expandido else "Mostrar menú lateral")
        centrado = (sidebar_estilo.ANCHO_COLAPSADO - self.btn_plegar_sidebar.width()) // 2
        self.cabecera_sidebar.layout().setContentsMargins(22 if expandido else centrado, 0,
                                                          16 if expandido else centrado, 0)
        for key, btn in self.menu_buttons.items():
            btn.setText(self.menu_texts[key] if expandido else "")
            btn.setStyleSheet(sidebar_estilo.qss_boton_menu(colapsado=not expandido))
        self.truck_decoration.setVisible(expandido)
        self.sidebar.update()

    def _on_sidebar_animation_finished(self):
        self._sidebar_animating = False
        self._descongelar_workspace()

    def _congelar_workspace(self):
        # Evita relayouts del módulo activo en cada cuadro de la animación
        if not hasattr(self, 'workspace') or not self.workspace.isVisible():
            return
        self._transicion_modulo.terminar()
        self._fade_anim.stop()
        self._fade_overlay.hide()
        self._snapshot_effect.setOpacity(1.0)
        self._workspace_snapshot.setPixmap(self.workspace.grab())
        self._workspace_snapshot.show()
        self.workspace.hide()
        self._dim_anim.start()

    def _descongelar_workspace(self):
        if not hasattr(self, '_workspace_snapshot') or not self._workspace_snapshot.isVisible():
            return
        self._dim_anim.stop()
        foto = self._workspace_snapshot.pixmap()
        self.workspace.show()
        self._workspace_snapshot.hide()
        self._workspace_snapshot.clear()

        # Funde la foto anterior sobre el contenido ya reacomodado
        self.content_area.layout().activate()
        self._fade_overlay.setPixmap(foto)
        self._fade_overlay.setGeometry(self.workspace.geometry())
        self._fade_overlay.raise_()
        self._fade_overlay.show()
        self._fade_anim.setStartValue(self._snapshot_effect.opacity())
        self._fade_anim.start()
        # Si llegó un data_ready mientras estaba oculto, el módulo quedó dirty
        self._trigger_load_data(self._get_active_submodule(self.workspace.currentWidget()))

    def _toggle_sidebar(self):
        if self._sidebar_animating:
            return  # Ignora clics mientras la animacion esta en curso (evita snaps/estados intermedios)

        standard_width = sidebar_estilo.ANCHO_EXPANDIDO
        collapsed_width = sidebar_estilo.ANCHO_COLAPSADO
        self._sidebar_animating = True
        if self.sidebar_expanded:
            self.animation.setStartValue(standard_width)
            self.animation.setEndValue(collapsed_width)
        else:
            self.animation.setStartValue(collapsed_width)
            self.animation.setEndValue(standard_width)
        self.sidebar_expanded = not self.sidebar_expanded
        self._aplicar_estado_sidebar(self.sidebar_expanded)
        self._congelar_workspace()
        self.animation.start()

    def _setup_content_area(self):
        self.content_area = QWidget()
        content_layout = QVBoxLayout(self.content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.header = QFrame()
        self.header.setObjectName("header")
        self.header.setFixedHeight(70)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(30, 0, 30, 0)

        self.search_bar = MultiSearchLineEdit()
        self.search_bar.setPlaceholderText(" Buscar Múltiples VINs, Chasis o RUT (pega listas)...")
        self.search_bar.setFixedWidth(400) 
        self.search_bar.addAction(qta.icon('fa5s.search', color='#9CA3AF'), QLineEdit.ActionPosition.LeadingPosition)
        self.search_bar.setToolTip("Buscar registros globalmente (Atajo: Ctrl+F)")
        # Debounce (ver DEBOUNCE_BUSQUEDA_GLOBAL_MS): el filtrado real
        # (_on_global_search) se dispara desde el timeout del timer, no desde
        # cada tecla directamente.
        self._global_search_timer = QTimer(self)
        self._global_search_timer.setSingleShot(True)
        self._global_search_timer.timeout.connect(self._ejecutar_busqueda_global_pendiente)
        self._pending_search_text = ""
        self.search_bar.textChanged.connect(self._on_global_search_text_changed)

        # Encabezado de página (título + descripción, como el HTML v2); lo
        # actualiza _update_module_chip al cambiar de pantalla
        self.page_head = QWidget()
        fila_head = QHBoxLayout(self.page_head)
        fila_head.setContentsMargins(15, 18, 15, 0)
        head_layout = QVBoxLayout()
        head_layout.setSpacing(3)
        self.page_title = QLabel("")
        self.page_title.setStyleSheet(
            "color: #0F1B33; font-size: 24px; font-weight: 800; background: transparent; border: none;")
        self.page_sub = QLabel("")
        self.page_sub.setStyleSheet(
            "color: #66748D; font-size: 13.5px; background: transparent; border: none;")
        head_layout.addWidget(self.page_title)
        head_layout.addWidget(self.page_sub)
        fila_head.addLayout(head_layout)
        fila_head.addStretch()
        # Botón propio de la pantalla activa (ej. "Crear unidad" de Comercial)
        self.page_acciones = QHBoxLayout()
        fila_head.addLayout(self.page_acciones)
        fila_head.setAlignment(self.page_acciones, Qt.AlignmentFlag.AlignBottom)

        self.last_update_label = QLabel("Actualizado: Recién")
        self.last_update_label.setStyleSheet("color: #6B7280; font-size: 13px;")

        self.mail_btn = mail_btn = QPushButton()
        mail_btn.setIcon(qta.icon('fa5s.envelope', color='#4B5563'))
        mail_btn.setProperty("class", "secondary")
        mail_btn.setFixedSize(36, 36)
        mail_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mail_btn.setToolTip("Generar y enviar correos automáticos (Cruza con Contactos CDB)")
        mail_btn.clicked.connect(self._open_mail_dialog)

        notif_container = QWidget()
        notif_container.setFixedSize(36, 36)
        
        self.notif_btn = QPushButton(notif_container)
        self.notif_btn.setIcon(qta.icon('fa5s.bell', color='#4B5563'))
        self.notif_btn.setProperty("class", "secondary")
        self.notif_btn.setFixedSize(36, 36)
        self.notif_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.notif_btn.setToolTip("Ver registro de modificaciones en la nube")
        self.notif_btn.clicked.connect(self._show_notifications)
        
        self.badge_label = QLabel(notif_container)
        self.badge_label.setStyleSheet("""
            QLabel { background-color: #EF4444; color: white; border-radius: 8px; font-weight: bold; font-size: 10px; font-family: 'Segoe UI'; }
        """)
        self.badge_label.setFixedSize(16, 16)
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge_label.move(20, 0)
        self.badge_label.raise_()
        self.badge_label.hide() 
        
        self.notif_menu = QMenu(self)
        self.notif_menu.setStyleSheet("""
            QMenu { background-color: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px; padding: 4px; }
        """)
        
        from PyQt6.QtWidgets import QWidgetAction
        from src.ui.notificaciones import PanelNotificaciones
        self.panel_notificaciones = PanelNotificaciones(archivos_vigilados=("RM_CONTRATOS",), parent=self.notif_menu)
        self.panel_notificaciones.no_leidos_cambiado.connect(self._on_no_leidos_cambiado)
        menu_action = QWidgetAction(self.notif_menu)
        menu_action.setDefaultWidget(self.panel_notificaciones)
        self.notif_menu.addAction(menu_action)
        self.notif_menu.aboutToHide.connect(self.panel_notificaciones.marcar_leidos)

        self.config_btn = QPushButton()
        self.config_btn.setIcon(qta.icon('fa5s.cog', color='#4B5563'))
        self.config_btn.setProperty("class", "secondary")
        self.config_btn.setFixedSize(36, 36)
        self.config_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.config_btn.setToolTip("Configuración (rutas de archivos, respaldos y ajustes)")
        self.config_btn.setEnabled(False)
        self.config_btn.clicked.connect(self._go_to_configuracion)

        gestor_tema = GestorTema.instancia()
        self.btn_tema = BotonTema(gestor_tema.modo == OSCURO)
        self.btn_tema.toggled.connect(self._on_boton_tema)
        self._transicion_tema = TransicionCirculo(self)
        gestor_tema.tema_cambiado.connect(self._on_tema_cambiado)
        self._on_tema_cambiado(gestor_tema.modo)

        header_layout.addWidget(self.search_bar)
        header_layout.addStretch()
        header_layout.addWidget(self.last_update_label)
        header_layout.addSpacing(15) 
        header_layout.addWidget(mail_btn)
        header_layout.addSpacing(5)
        header_layout.addWidget(notif_container)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.btn_tema)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.config_btn)

        self.workspace = QStackedWidget()
        self.workspace.setObjectName("main_content_area")

        # Foto del workspace mostrada durante la animación del sidebar
        self._workspace_snapshot = QLabel()
        self._workspace_snapshot.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._workspace_snapshot.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._workspace_snapshot.setStyleSheet(f"background-color: {BACKGROUND};")
        self._workspace_snapshot.hide()
        self._snapshot_effect = QGraphicsOpacityEffect(self._workspace_snapshot)
        self._workspace_snapshot.setGraphicsEffect(self._snapshot_effect)
        self._dim_anim = QPropertyAnimation(self._snapshot_effect, b"opacity", self)
        self._dim_anim.setDuration(250)
        self._dim_anim.setStartValue(1.0)
        self._dim_anim.setEndValue(0.6)
        self._dim_anim.setEasingCurve(QEasingCurve.Type.OutQuad)

        # Capa flotante para el fundido final (fuera del layout)
        self._fade_overlay = QLabel(self.content_area)
        self._fade_overlay.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._fade_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._fade_overlay.hide()
        self._fade_effect = QGraphicsOpacityEffect(self._fade_overlay)
        self._fade_overlay.setGraphicsEffect(self._fade_effect)
        self._fade_anim = QPropertyAnimation(self._fade_effect, b"opacity", self)
        self._fade_anim.setDuration(200)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_anim.finished.connect(self._fade_overlay.hide)
        self._fade_anim.finished.connect(self._fade_overlay.clear)

        self._transicion_modulo = TransicionFundidoSubida(self.content_area, self.workspace, BACKGROUND)

        content_layout.addWidget(self.header)
        content_layout.addWidget(self.page_head)
        content_layout.addWidget(self.workspace, 1)
        content_layout.addWidget(self._workspace_snapshot, 1)
        self.main_layout.addWidget(self.content_area)

    def _setup_shortcuts(self):
        shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_save.activated.connect(self._trigger_save_on_current_module)
        
        shortcut_f5 = QShortcut(QKeySequence("F5"), self)
        shortcut_f5.activated.connect(self._trigger_save_on_current_module)
        
        shortcut_find = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_find.activated.connect(self._focus_search_bar)

    def _trigger_save_on_current_module(self):
        current_widget = self._get_active_submodule(self.workspace.currentWidget())
        if not current_widget: return
            
        if hasattr(current_widget, 'btn_save_changes'): 
            current_widget.btn_save_changes.click()
        elif hasattr(current_widget, 'btn_save'):
            current_widget.btn_save.click()
        elif hasattr(current_widget, 'btn_save_config'):
            current_widget.btn_save_config.click()
        else:
            QMessageBox.information(self, "Información", "El módulo actual no tiene acciones pendientes por guardar.")

    def _focus_search_bar(self):
        self.search_bar.setFocus()
        self.search_bar.selectAll()

    def _instantiate_module(self, module_name):
        # Medicion Fase 0 (auditoria de rendimiento, 17-09-2026): tiempo de
        # construccion de cada modulo al abrirlo por primera vez -- ver
        # src/core/perf_log.py.
        with medir(f"instanciar módulo: {module_name}"):
            module = self._instantiate_module_impl(module_name)
        if module is not None:
            for sub_tabs in module.findChildren(QTabWidget):
                instalar_transicion_pestanas(sub_tabs)
        return module

    def _instantiate_module_impl(self, module_name):
        if module_name == "Vista General":
            from src.ui.general import GeneralModule
            module = GeneralModule()
        elif module_name == "Dashboard BI":
            from src.ui.dashboard import DashboardModule
            module = DashboardModule()
        elif module_name == "Comercial":
            from src.ui.comercial import ComercialModule
            module = ComercialModule()
            module.table.set_table_id("comercial")
        elif module_name == "Operaciones":
            from src.ui.operaciones import OperacionesModule
            module = OperacionesModule()
            module.table.set_table_id("operaciones")
        elif module_name == "Provisiones":
            from src.ui.provisiones import ProvisionesModule
            module = ProvisionesModule()
            module.table.set_table_id("provisiones")
        elif module_name == "Contratos (CM)":
            from src.ui.contratos import ContratosModule
            module = ContratosModule()
        elif module_name == "Facturación Manual":
            from src.ui.facturacion_manual import FacturacionManualModule
            module = FacturacionManualModule()
        elif module_name == "JustTime":
            from src.ui.justtime import JustTimeModule
            module = JustTimeModule()
        elif module_name == "Instalaciones":
            from src.ui.instalaciones import InstalacionesModule
            module = InstalacionesModule()
        elif module_name == "Historial":
            from src.ui.historial import HistorialModule
            module = HistorialModule()
        elif module_name == "Contactos":
            from src.ui.contactos import ContactosModule
            module = ContactosModule()
        elif module_name == "Ejecutivos":
            from src.ui.ejecutivos import EjecutivosModule
            module = EjecutivosModule()
        elif module_name == "Clientes":
            from src.ui.clientes_admin import ClientesAdminModule
            module = ClientesAdminModule()
        elif module_name == "Configuración":
            from src.ui.configuracion import ConfiguracionModule
            module = ConfiguracionModule()
        else:
            return None
        self.loaded_modules[module_name] = module
        return module

    def _build_group_module(self, group_key):
        # Medicion Fase 0 (auditoria de rendimiento, 17-09-2026): tiempo de
        # construir TODAS las sub-pestañas del grupo (ej. "Administración")
        # de una sola vez -- ver src/core/perf_log.py.
        with medir(f"construir grupo: {group_key}"):
            return self._build_group_module_impl(group_key)

    def _build_group_module_impl(self, group_key):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # La barra nativa se oculta: las pestañas del grupo se eligen con el
        # mismo selector segmentado de Comercial
        tabs = QTabWidget()
        tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
        tabs.tabBar().hide()

        # Solo se construye la primera pestaña; el resto queda como marcador
        # y se instancia al seleccionarla por primera vez (_materializar_tab).
        tab_index_by_key = {}
        tab_icons = {}
        for sub_name, icon_name in self.group_definitions[group_key]:
            tab_icons[sub_name] = qta.icon(icon_name, color=TEXT_SECONDARY)
            sub_module = self.loaded_modules.get(sub_name)
            if sub_module is None and not tab_index_by_key:
                sub_module = self._instantiate_module(sub_name)
            if sub_module is None:
                sub_module = QWidget()
                sub_module._submodulo_pendiente = sub_name
            tab_index_by_key[sub_name] = tabs.addTab(sub_module, tab_icons[sub_name], sub_name)

        # Ingresos y Administración: las pestañas del grupo van bajo los KPI de
        # cada pantalla (como las sub-pestañas de Comercial), no sobre ellos.
        pestanas_bajo_kpi = group_key in ("Ingresos y Conciliación", "Administración")

        def _colocar_selector(modulo):
            lay = modulo.layout() if pestanas_bajo_kpi else None
            if lay is None:
                return
            previo = getattr(modulo, '_selector_grupo', None)
            if previo is not None:
                lay.removeWidget(previo)
                previo.deleteLater()
            selector_modulo = estilo_com.SelectorSubpestanas(tabs)
            selector_modulo.tabBarClicked.connect(tabs.tabBar().tabBarClicked.emit)
            kpi = getattr(modulo, '_kpi_contenedor', None)
            posicion = lay.indexOf(kpi) + 1 if kpi is not None and lay.indexOf(kpi) >= 0 else 0
            lay.insertWidget(posicion, selector_modulo)
            modulo._selector_grupo = selector_modulo

        def _materializar_tab(idx):
            marcador = tabs.widget(idx)
            sub_name = getattr(marcador, '_submodulo_pendiente', None)
            if sub_name is None:
                return
            sub_module = self.loaded_modules.get(sub_name) or self._instantiate_module(sub_name)
            tabs.blockSignals(True)
            tabs.removeTab(idx)
            tabs.insertTab(idx, sub_module, tab_icons[sub_name], sub_name)
            _colocar_selector(sub_module)
            tabs.setCurrentIndex(idx)
            tabs.blockSignals(False)
            # Con las señales bloqueadas el selector nuevo nació marcando la
            # pestaña vecina que quedó activa al reemplazar el marcador
            selector_nuevo = getattr(sub_module, '_selector_grupo', None)
            if selector_nuevo is not None:
                selector_nuevo._sincronizar(idx)
            marcador.deleteLater()

        def _on_tab_changed(idx):
            _materializar_tab(idx)
            self._trigger_load_data(self._get_active_submodule(tabs.currentWidget()))
            sub_name = tabs.tabText(idx)
            self._update_module_chip(sub_name)

        tabs.currentChanged.connect(_on_tab_changed)
        # Se instala después de _on_tab_changed para animar ya el módulo materializado
        instalar_transicion_pestanas(tabs)

        # La transición espera tabBarClicked, que la barra oculta ya no emite
        if pestanas_bajo_kpi:
            selector = None
            for i in range(tabs.count()):
                _colocar_selector(tabs.widget(i))
                selector = selector or getattr(tabs.widget(i), '_selector_grupo', None)
        else:
            fila_selector = QHBoxLayout()
            fila_selector.setContentsMargins(15, 14, 15, 0)
            selector = estilo_com.SelectorSegmentado(tabs)
            selector._grupo.idPressed.connect(tabs.tabBar().tabBarClicked.emit)
            fila_selector.addWidget(selector)
            fila_selector.addStretch()
            layout.addLayout(fila_selector)
        layout.addWidget(tabs)
        container.selector_grupo = selector
        container.tabs = tabs
        container.tab_index_by_key = tab_index_by_key
        self.loaded_modules[group_key] = container
        return container

    _ENCABEZADOS_PAGINA = {
        "Dashboard BI": ("Dashboard", "Resumen general de la flota y los indicadores del negocio."),
        "Vista General": ("Clientes y Flota", "Clientes, unidades y su estado en la flota."),
        "Comercial": ("Gestión comercial", "Unidades y clientes que requieren una acción del equipo."),
        "Operaciones": ("Operaciones", "Cola de operaciones: activaciones, unidades sin flota y bajas."),
        "Configuración": ("Configuración", "Rutas de archivos, respaldos y ajustes del sistema."),
    }
    _ENCABEZADOS_GRUPO = {
        "Ingresos y Conciliación": (
            "Ingresos y Conciliación",
            "Provisiones, contratos CM, facturación manual y conciliación JustTime.",
            ("Provisiones", "Contratos (CM)", "Facturación Manual", "JustTime")),
        "Administración": (
            "Administración",
            "Historial de cambios, instalaciones, contactos, ejecutivos y clientes del sistema.",
            ("Historial", "Instalaciones", "Contactos", "Ejecutivos", "Clientes")),
    }

    def _update_module_chip(self, module_name):
        titulo, sub = self._ENCABEZADOS_PAGINA.get(
            module_name, (MODULE_DISPLAY_NAMES.get(module_name, module_name), ""))
        for grupo_titulo, grupo_sub, miembros in self._ENCABEZADOS_GRUPO.values():
            if module_name in miembros:
                titulo, sub = grupo_titulo, grupo_sub
        self.page_title.setText(titulo)
        self.page_sub.setText(sub)
        self.page_sub.setVisible(bool(sub))
        # Clientes y Flota dibuja su propio título para que la caja derecha suba al borde
        self.page_head.setVisible(module_name != "Vista General")
        for i in range(self.page_acciones.count()):
            self.page_acciones.itemAt(i).widget().hide()
        boton = getattr(self.loaded_modules.get(module_name), 'boton_encabezado', None)
        if boton is not None:
            if self.page_acciones.indexOf(boton) < 0:
                self.page_acciones.addWidget(boton)
            boton.setVisible(self.loaded_modules[module_name].boton_encabezado_visible())

    def _foto_para_transicion(self, module_name):
        # Solo entre módulos reales (no desde la pantalla de carga o de error)
        actual = self.workspace.currentWidget()
        if actual is None or not self.workspace.isVisible():
            return None
        if actual is self.loaded_modules.get(module_name) or actual not in self.loaded_modules.values():
            return None
        self._transicion_modulo.terminar()
        return self.workspace.grab()

    def _load_module(self, module_name):
        foto_anterior = self._foto_para_transicion(module_name)

        if module_name not in self.loaded_modules:
            if module_name in self.group_definitions:
                module = self._build_group_module(module_name)
            else:
                module = self._instantiate_module(module_name)
                if module is None:
                    return
            self.workspace.addWidget(module)

        self.workspace.setCurrentWidget(self.loaded_modules[module_name])

        if module_name in self.group_definitions:
            group_widget = self.loaded_modules[module_name]
            active_sub_name = group_widget.tabs.tabText(group_widget.tabs.currentIndex())
            self._update_module_chip(active_sub_name)
        else:
            self._update_module_chip(module_name)

        if foto_anterior is not None:
            # El encabezado de página puede aparecer u ocultarse: la capa debe tomar la posición final del workspace
            self.content_area.layout().activate()
            self._transicion_modulo.iniciar(foto_anterior)

    def _get_active_submodule(self, widget):
        # Recursivo: un modulo dentro de un grupo (Provisiones/Contratos/
        # Facturacion Manual) puede a su vez tener sus propias sub-pestañas
        # internas (ver ProvisionesModule/ComercialModule, patron
        # legacy + pestaña nueva). Un solo salto se detenia en el modulo,
        # sin llegar a la pestaña interna realmente visible.
        while widget is not None and hasattr(widget, 'tabs'):
            widget = widget.tabs.currentWidget()
        return widget

    def _trigger_load_data(self, modulo):
        if not modulo:
            return
        # El refresco (ver _refrescar_modulo_visible) corre al terminar la transición de pantalla en curso,
        # no durante ella: hacerlo a mitad de los 260 ms congelaba cuadros
        # de la animación (docs/12 §8.2). El tick 0 es necesario porque en
        # un cambio de pestaña la transición arranca después de este
        # llamado (ver _on_tab_changed / instalar_transicion_pestanas).
        QTimer.singleShot(0, lambda: _refrescar_modulo_tras_transicion(self, modulo))

    def _on_menu_clicked(self, clicked_text):
        for text, btn in self.menu_buttons.items():
            if text == clicked_text: btn.setChecked(True)
            else: btn.setChecked(False)

        self._load_module(clicked_text)

        modulo_actual = self._get_active_submodule(self.loaded_modules.get(clicked_text))
        self._trigger_load_data(modulo_actual)

    def abrir_unidad_en_general(self, vin):
        """Lleva a Clientes y Flota -> Unidades con `vin` seleccionado (ficha en la caja derecha)."""
        self._on_menu_clicked("Vista General")
        general = self.loaded_modules.get("Vista General")
        if general is not None:
            general._abrir_unidad_en_pestana_unidades(vin)

    def _go_to_configuracion(self):
        for btn in self.menu_buttons.values():
            btn.setChecked(False)
        self._load_module("Configuración")
        self._trigger_load_data(self.loaded_modules.get("Configuración"))

    def _on_global_search_text_changed(self, text):
        """Slot real conectado a search_bar.textChanged: NO filtra de
        inmediato. Guarda el texto pendiente y (re)inicia el timer de
        debounce; cada tecla nueva reinicia la espera, asi que solo la ultima
        pausa real dispara _ejecutar_busqueda_global_pendiente (ver
        DEBOUNCE_BUSQUEDA_GLOBAL_MS)."""
        self._pending_search_text = text
        self._global_search_timer.start(DEBOUNCE_BUSQUEDA_GLOBAL_MS)

    def _ejecutar_busqueda_global_pendiente(self):
        """Timeout del debounce: recien aca se ejecuta el filtrado real,
        exactamente igual que antes (_on_global_search sin cambios)."""
        self._on_global_search(self._pending_search_text)

    def _on_global_search(self, text):
        # Instrumentacion temporal (auditoria de rendimiento B-2, 18-09-2026):
        # mide el costo real de UN disparo de _on_global_search (ya con
        # debounce aplicado desde _ejecutar_busqueda_global_pendiente, ver
        # DEBOUNCE_BUSQUEDA_GLOBAL_MS) sobre el modulo activo. No cambia el
        # comportamiento del filtrado en si, solo agrega la medicion.
        with medir(f"B-2 _on_global_search('{text[:30]}', {len(text)} chars)"):
            current_widget = self._get_active_submodule(self.workspace.currentWidget())
            if not current_widget: return
            self._aplicar_busqueda_a_modulo(current_widget, text)

    def _aplicar_busqueda_a_modulo(self, modulo, text):
        """Aplica el texto de la barra de búsqueda global a un módulo puntual
        (search_input + filter_table/filter_tables). Se usa tanto al escribir
        en la barra (_on_global_search) como al navegar hacia un módulo (ver
        _trigger_load_data): sin esto, un módulo que no estaba visible cuando
        se escribió o se borró el texto quedaba con un filtro desactualizado
        -- ej. limpiar la búsqueda estando en Comercial no se reflejaba en
        Vista General hasta volver a escribir algo ahí."""
        if hasattr(modulo, 'search_input'):
            modulo.search_input.blockSignals(True)
            modulo.search_input.setText(text)
            modulo.search_input.blockSignals(False)

            if hasattr(modulo, 'filter_table'):
                modulo.filter_table()
            elif hasattr(modulo, 'filter_tables'):
                modulo.filter_tables()

    def _open_mail_dialog(self):
        from src.ui.mail_dialog import MailDialog
        # Medicion Fase 0 (auditoria de rendimiento, 17-09-2026): solo la
        # construccion (lectura de Correos.csv + render de tabla), no el
        # tiempo que el dialogo modal queda abierto -- ver src/core/perf_log.py.
        with medir("abrir mail_dialog (construcción)"):
            dialog = MailDialog(parent=self)
        dialog.exec()
