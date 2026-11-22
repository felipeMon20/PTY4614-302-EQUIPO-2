import os
import re
import sys
import qtawesome as qta
from PyQt6.QtWidgets import (QMainWindow, QMessageBox, QScrollArea, QWidget, QHBoxLayout, QVBoxLayout,
                             QPushButton, QLabel, QStackedWidget, QFrame, QLineEdit, QMenu, QSizePolicy, QProgressBar, QApplication,
                             QTabWidget, QGraphicsOpacityEffect)
from PyQt6.QtCore import QThread, QTimer, Qt, QSize, QPropertyAnimation, QEasingCurve, QSettings, QPoint, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence, QPixmap, QPainter

import config.settings
from config.settings import EXCEL_PATH, WATCH_DIR
from src.core.data_manager import DataManager
from src.core.excel_reader import ExcelReader
from src.core.backup_manager import BackupWorker
from src.services import cm_bajas_service, cambios_archivos_service, comercial_services
from src.core.hilos import iniciar_hilo_retenido
from src.ui.compartido.esqueleto_carga import animar_cajas, animar_tabla_principal
from src.ui.compartido.transiciones import (TransicionFundidoSubida, TransicionCirculo, instalar_transicion_pestanas, ms_restantes_animacion,
                                 capturar)
from src.ui.marco.boton_tema import BotonTema
from src.ui.marco import barra_superior
from src.theme.tema import GestorTema, CLARO, OSCURO, color as tema_color
from src.ui.marco import sidebar_estilo as sidebar_estilo
from src.ui.marco.cabecera_camion import CabeceraCamion
from src.ui.marco.foto_menu import FotoMenu, AjusteAltoFoto
from src.theme import menu_fotos
from src.ui.compartido.comercial_estilo import fuente_comercial
from src.ui.compartido import comercial_estilo as estilo_com
from src.theme.colors import (BACKGROUND, TEXT_PRIMARY, TEXT_SECONDARY, SURFACE, BORDER, VOLVO_BLUE,
                               PRIMARY, SECONDARY, MODULE_DISPLAY_NAMES, MODULE_COLORS, DANGER)
import logging

logger = logging.getLogger(__name__)

# NOTA (imports diferidos): WatchdogThread, los 10 modulos de src.ui.* y
# MailDialog se importan de forma local, justo donde se usan (_start_watchdog,
# _instantiate_module, _open_mail_dialog) en vez de aqui arriba. Cada uno se
# usa en un unico punto del archivo (verificado), y ya se instancian de forma
# perezosa (solo cuando el usuario navega a esa seccion o el watchdog arranca
# tras la primera carga exitosa) — diferir tambien su import evita pagar ese
# costo antes de que la ventana principal exista.

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False): base_path = sys._MEIPASS
    else: base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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
# 12-11-2026: subió de 200 a 2000. La búsqueda usa una regex en árbol de prefijos
# (comercial_services.patron_de_terminos) y General ya no busca dos veces: con datos reales,
# 2000 VIN tardan ~0,6 s en General y ~0,3 s en Comercial y Operaciones.
MAX_TERMINOS_BUSQUEDA_GLOBAL = 2000

# Debounce del buscador global (auditoria de rendimiento, fase 1, 21-09-2026):
# _on_global_search() filtra y reconstruye la UI del modulo activo (tablas,
# tarjetas, pandas), y sin esto se ejecutaba integro en el hilo principal por
# CADA tecla -- incluido el auto-repeat de mantener una tecla apretada --
# congelando la app con datasets grandes. Con este retraso el QLineEdit sigue
# mostrando cada caracter al instante (no se toca su propio texto); solo se
# retrasa el filtrado real hasta que el usuario deja de escribir. Ver
# _on_global_search_text_changed/_ejecutar_busqueda_global_pendiente.
DEBOUNCE_BUSQUEDA_GLOBAL_MS = 250

# Cada cuánto se vuelve a mirar si hay una versión nueva publicada con la app abierta
INTERVALO_REVISION_ACTUALIZACION_MS = 10 * 60 * 1000

# Espera mínima antes de refrescar un módulo al navegar (valor histórico,
# se usa cuando no hay transición en curso).
ESPERA_MINIMA_REFRESCO_MS = 50
MARGEN_TRAS_TRANSICION_MS = 30

# Pausa entre el armado de un módulo y el siguiente durante la pantalla de carga inicial
ARRANQUE_ENTRE_MODULOS_MS = 60
# Espera tras abrir la app antes de armar en segundo plano las pantallas que faltan
PRECARGA_TRAS_ARRANQUE_MS = 1000
# Si la persona está usando el mouse o el teclado, la precarga espera (hasta ~10 s) para no dar tirones
PRECARGA_ESPERA_INACTIVIDAD_MS = 800
PRECARGA_REINTENTO_MS = 250
PRECARGA_MAX_APLAZAMIENTOS = 40


def _ms_sin_actividad():
    """Milisegundos desde el último mouse o tecla en todo Windows; muy alto si no se puede saber."""
    try:
        import ctypes

        class _UltimaEntrada(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = _UltimaEntrada(ctypes.sizeof(_UltimaEntrada), 0)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 10 ** 9
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    except Exception:
        return 10 ** 9


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


def _refrescar_modulo_tras_transicion(ventana, modulo, token=None):
    """`token` identifica el último pedido de refresco: si el usuario ya pasó a otra pantalla
    antes de que corra este, se descarta (el módulo se refresca igual la próxima vez que se abre)."""
    espera = max(ESPERA_MINIMA_REFRESCO_MS, _ms_restantes_transiciones(ventana, modulo) + MARGEN_TRAS_TRANSICION_MS)

    def refrescar():
        if token is None or getattr(ventana, '_token_refresco', token) == token:
            _refrescar_modulo_visible(ventana, modulo)
    QTimer.singleShot(espera, refrescar)


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


class _FondoVentana(QWidget):
    """Contenedor central que pinta el fondo de la ventana según el tema (sustituye la regla QMainWindow de la hoja global)."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), tema_color('fondo'))
        p.end()


class MultiSearchLineEdit(QLineEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El tope por defecto de Qt (32.767 caracteres) cortaba la lista a mitad de un VIN
        self.setMaxLength(MAX_TERMINOS_BUSQUEDA_GLOBAL * 40)

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
            logger.warning(f"Error en CompareSnapshotThread: {e}", exc_info=True)
            self.finished_signal.emit([])

class CompararArchivoThread(QThread):
    """Provisiones o Contactos cambiaron fuera de la app: lee el archivo y lo compara con la base guardada
    (modo 'comparar'), o solo deja la base al día (modo 'base': primera vez o tras un guardado propio)."""
    finished_signal = pyqtSignal(list)

    def __init__(self, clave, modo="comparar"):
        super().__init__()
        self.clave = clave
        self.modo = modo

    def run(self):
        cambios = []
        try:
            ruta = cambios_archivos_service.ruta_de(self.clave)
            if ruta and os.path.exists(ruta):
                if self.modo == "comparar":
                    cambios = cambios_archivos_service.comparar_y_actualizar(self.clave, ruta)
                elif self.modo == "asegurar":
                    cambios_archivos_service.asegurar_base(self.clave, ruta)
                else:
                    cambios_archivos_service.actualizar_base(self.clave, ruta)
        except Exception as e:
            logger.warning(f"Error en CompararArchivoThread ({self.clave}, {self.modo}): {e}", exc_info=True)
        self.finished_signal.emit(cambios)


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
            logger.warning(f"Error en ActualizarBaseNotificacionesThread: {e}", exc_info=True)


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
            logger.warning(f"No se pudo reconciliar los casos de Revisión CM por estado Expired al cargar datos: {e}")


class AjusteFacturacionManualThread(QThread):
    """Ajusta en facturacionManual.xlsx las unidades de las razones ya facturadas que perdieron
    unidades en RM_JAVI (fuera del hilo de UI)."""
    ajustado = pyqtSignal(object)

    def __init__(self, ruta, df_master):
        super().__init__()
        self.ruta = ruta
        self.df_master = df_master

    def run(self):
        from src.services import facturacion_manual_service as fm_service
        try:
            detalle, error = fm_service.ajustar_unidades_facturadas(self.ruta, self.df_master)
        except Exception as e:
            logger.warning(f"No se pudo ajustar Facturación Manual al RM: {e}")
            return
        if error:
            logger.warning(f"No se pudo ajustar Facturación Manual al RM: {error}")
        elif detalle:
            self.ajustado.emit(detalle)


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
            logger.warning(f"No se pudo corregir ESTADO COMERCIAL de unidades conectadas: {e}")
            ok = False
        self.finished_signal.emit(ok, self.cambios)


class MainWindow(QMainWindow):
    _cargando_inicial = False
    _pantalla_pendiente = None

    # Avance de la carga inicial (0 a 1) y aviso de que todas las pantallas están listas
    progreso_arranque = pyqtSignal(float)
    arranque_listo = pyqtSignal()

    def __init__(self, arranque_oculto=False):
        """Con `arranque_oculto` la ventana se arma invisible e inactiva y se muestra con revelar()
        cuando todas las pantallas están cargadas (la pantalla de inicio sigue a la vista mientras tanto)."""
        super().__init__()
        if arranque_oculto:
            self.setWindowOpacity(0.0)
            self.setEnabled(False)
        self.setWindowTitle("Gestor SSCC")
        self.setWindowIcon(QApplication.windowIcon())

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
        self._cargando_inicial = True
        self._show_loading_screen()

        # Fase 6: el banner de bloqueo vive FUERA de self.central_widget a
        # proposito. Qt propaga setEnabled(False) a todos los descendientes
        # de un widget deshabilitado (los pinta atenuados/"grises"), y este
        # banner debe seguir viendose con sus colores reales (rojo/blanco)
        # exactamente cuando central_widget esta deshabilitado. Por eso el
        # widget central real de la ventana pasa a ser este contenedor
        # (root_widget), con el banner y central_widget como hermanos.
        self._setup_lock_banner()

        root_widget = _FondoVentana()
        root_layout = QVBoxLayout(root_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.lock_banner)
        root_layout.addWidget(self.central_widget)
        self.setCentralWidget(root_widget)
        self._root_widget = root_widget
        GestorTema.instancia().registrar_ventana(self)

        self.settings = QSettings("VolvoApp", "Dashboard")
        self._load_settings()

        self.data_manager = DataManager()
        self.data_manager.data_ready.connect(self._on_data_loaded_success)
        self.data_manager.load_error.connect(self._on_data_load_error)
        
        self.data_manager.load_data_async()
        # Contactos se lee ya, con la pantalla de carga a la vista. BBDD CLIENTES
        # CM (13 MB) espera a que la app esté abierta: su espejo CSV se rehace en
        # 11-17 s cada vez que cambia el Excel y congelaría la animación
        self.data_manager.load_contactos_async()
        from src.ui.general import diferir_director_empresa_pbi
        diferir_director_empresa_pbi()

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

    def contenedores_tema(self):
        """Ventana y contenedores sin estilo propio: la hoja global del tema va en sus hijos, no aquí."""
        return [self, self._root_widget, self.central_widget, self.content_area]

    def pila_tema(self):
        return self.workspace

    def _on_boton_tema(self, oscuro, origen=None):
        """`origen`: widget desde cuyo centro se expande la transición (por defecto, el botón de la barra)."""
        modo = OSCURO if oscuro else CLARO
        contenedor = self.centralWidget()
        if contenedor is None or not self.isVisible():
            GestorTema.instancia().aplicar(modo)
            return
        if GestorTema.instancia().modo == modo:
            return
        ref = origen if origen is not None else self.btn_tema
        centro = ref.mapTo(contenedor, ref.rect().center())

        def _cambiar():
            GestorTema.instancia().aplicar(modo)
            self.btn_tema.reiniciar_animacion()

        self._transicion_tema.iniciar(contenedor, centro, _cambiar)

    def _on_tema_cambiado(self, modo):
        raiz = getattr(self, '_root_widget', None)
        if raiz is not None:
            raiz.update()
        if self.btn_tema.isChecked() != (modo == OSCURO):
            self.btn_tema.fijar_sin_animar(modo == OSCURO)
        self._estilo_contadores(modo)

    @staticmethod
    def _crear_pill_contador(nombre):
        pill = QLabel()
        pill.setObjectName(nombre)
        pill.setFixedHeight(22)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.hide()
        return pill

    def _estilo_contadores(self, modo):
        base = "font-size: 11px; font-weight: 600; border-radius: 11px; padding: 0 10px;"
        if modo == OSCURO:
            buscados = f"background: #27303F; color: #C3CEDF; border: 1px solid #3A4558; {base}"
            seleccion = f"background: #0B3B66; color: #FFFFFF; border: 1px solid #3F6FA3; {base}"
        else:
            buscados = f"background: #EEF1F5; color: #003057; border: 1px solid #D5DCE6; {base}"
            seleccion = f"background: #003057; color: #FFFFFF; border: 1px solid #003057; {base}"
        self.pill_buscados.setStyleSheet(f"QLabel#pillBuscados {{ {buscados} }}")
        self.pill_seleccion.setStyleSheet(f"QLabel#pillSeleccion {{ {seleccion} }}")
        faltantes = ("background: #4A1D22; color: #FCA5A5; border: 1px solid #8B2E36;" if modo == OSCURO
                     else "background: #FDECEC; color: #B91C1C; border: 1px solid #F3B4B4;")
        self.chip_faltantes.setStyleSheet(f"QLabel#chipFaltantes {{ {faltantes} {base} }}")
        if self.pill_datos is not None:
            if config.settings.DATOS_DE_PRUEBA:
                datos = ("background: #1E3A33; color: #8FE3C0; border: 1px solid #2F6B58;" if modo == OSCURO
                         else "background: #E3F6EE; color: #0B6B4B; border: 1px solid #A8DEC6;")
            else:
                datos = ("background: #4A1D22; color: #FCA5A5; border: 1px solid #8B2E36;" if modo == OSCURO
                         else "background: #FDECEC; color: #B91C1C; border: 1px solid #F3B4B4;")
            self.pill_datos.setStyleSheet(f"QLabel#pillDatos {{ {datos} {base} font-weight: 700; }}")

    def _actualizar_contador_busqueda(self, texto):
        from src.services import contadores_busqueda as cb
        lista = cb.terminos(texto)
        self.chip_faltantes.poner([])
        if not lista:
            self.pill_buscados.hide()
            return
        resumen = f"{len(lista)} {cb.etiqueta(lista)}"
        if cb.son_vins(lista):
            df = getattr(DataManager(), 'df_master', None)
            if df is not None:
                if self._indice_coincidencias is None:
                    self._indice_coincidencias = cb.IndiceCoincidencias()
                estados = self._indice_coincidencias.estados(df, lista)
                n = sum(estados)
                resumen += f" · {n} encontrado{'' if n == 1 else 's'}"
                originales = [t.strip().upper() for t in str(texto).split(',') if t.strip()]
                self.chip_faltantes.poner([v for v, ok in zip(originales, estados) if not ok])
        self.pill_buscados.setText(resumen)
        self.pill_buscados.show()

    def _vigilar_seleccion(self):
        """Mantiene enganchada la tabla visible de la pantalla activa; el conteo sale de su selectionChanged."""
        if not self.isVisible() or self._cargando_inicial:
            return
        activo = self._get_active_submodule(self.workspace.currentWidget())
        try:
            vigente = (self._tabla_sel is not None and self._tabla_sel.isVisible()
                       and self._tabla_sel.selectionModel() is self._sel_modelo and activo is self._sel_modulo)
        except RuntimeError:
            vigente = False
        if vigente or (self._tabla_sel is None and activo is self._sel_modulo and activo is None):
            return
        # Sin tabla en la pantalla (tarjetas): si recorrer el árbol de widgets sale caro, se espera 20 veces lo que
        # tardó (hasta 5 s) antes de volver a mirar; si sale barato, se sigue mirando cada 350 ms
        import time as _tiempo
        ahora = _tiempo.monotonic()
        if (self._tabla_sel is None and activo is not None and activo is self._sel_modulo
                and ahora < self.__dict__.get('_sel_no_antes_de', 0.0)):
            return
        inicio_escaneo = ahora
        if self._sel_modelo is not None:
            try:
                self._sel_modelo.selectionChanged.disconnect(self._programar_conteo_seleccion)
            except (TypeError, RuntimeError):
                pass
        self._tabla_sel = self._sel_modelo = None
        self._sel_modulo = activo
        if activo is not None:
            from PyQt6.QtWidgets import QAbstractItemView
            tablas = [t for t in activo.findChildren(QAbstractItemView) if t.isVisible() and t.selectionModel() is not None]
            if tablas:
                self._tabla_sel = max(tablas, key=lambda t: t.viewport().width() * t.viewport().height())
                self._sel_modelo = self._tabla_sel.selectionModel()
                self._sel_modelo.selectionChanged.connect(self._programar_conteo_seleccion)
        duracion = _tiempo.monotonic() - inicio_escaneo
        self._sel_no_antes_de = _tiempo.monotonic() + (min(5.0, duracion * 20) if duracion > 0.03 else 0.0)
        self._actualizar_contador_seleccion()

    def _programar_conteo_seleccion(self, *_):
        self._timer_conteo_sel.start()

    def _actualizar_contador_seleccion(self):
        try:
            n = len(self._sel_modelo.selectedRows()) if self._sel_modelo is not None else 0
        except RuntimeError:
            n = 0
        if n:
            self.pill_seleccion.setText(f"{n} seleccionado{'' if n == 1 else 's'}")
            self.pill_seleccion.show()
        else:
            self.pill_seleccion.hide()

    def _show_loading_screen(self):
        from src.ui.compartido.guardado_overlay import crear_tarjeta_carga
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
        self._on_data_loaded_success_impl()

    def _on_data_loaded_success_impl(self):
        logger.info("Excel cargado en memoria exitosamente.")
        self.progreso_arranque.emit(0.86)
        self._actualizar_contador_busqueda(self.search_bar.text())
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
        self._ajustar_facturacion_manual_en_fondo()
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
        """Una unidad "Conectado" en Volvo Connect no puede seguir en ESTADO
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

    def _ajustar_facturacion_manual_en_fondo(self):
        """Si una unidad sale de Facturación Manual o se da de baja, el Excel de facturación de los
        meses en curso y anterior queda igual al RM sin pasar por "Ajustar a RM"."""
        dm = self.data_manager
        ruta = config.settings.FACTURACION_MANUAL_PATH
        if dm.df_master is None or dm.df_master.empty or not ruta or not os.path.exists(ruta):
            return
        hilo = getattr(self, '_ajuste_fm_thread', None)
        if hilo is not None and hilo.isRunning():
            return
        self._ajuste_fm_thread = AjusteFacturacionManualThread(ruta, dm.df_master.copy())
        self._ajuste_fm_thread.ajustado.connect(self._on_facturacion_manual_ajustada)
        self._ajuste_fm_thread.start()

    def _on_facturacion_manual_ajustada(self, detalle):
        for cliente, periodo, antes, ahora in detalle:
            logger.info(f"Facturación Manual ajustada al RM: {cliente} ({periodo}) de {antes} a {ahora} unidades.")
        modulo = self.loaded_modules.get("Facturación Manual")
        if modulo is not None:
            modulo._data_dirty = True
            if modulo.isVisible():
                modulo.load_data()

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
            from src.ui.general import GeneralModule
            module = GeneralModule()
            self.loaded_modules["Vista General"] = module
            self.workspace.addWidget(module)

            # Con Vista General lista, el resto de las pantallas se arman con la
            # pantalla de carga a la vista, y recién entonces se abre la primera.
            module.primera_carga_lista.connect(self._arrancar_precarga)

    def _arrancar_precarga(self):
        """Vista General ya está lista: la app se abre y el resto de las pantallas se arma después, de a una."""
        self._pre_pendientes = [n for n in self.menu_buttons if n not in self.loaded_modules]
        self._pre_aplazadas = 0
        self.progreso_arranque.emit(0.99)
        self._terminar_arranque()
        QTimer.singleShot(PRECARGA_TRAS_ARRANQUE_MS, self._precargar_en_arranque)

    def _precargar_en_arranque(self):
        """Arma y carga de a un módulo por vuelta del event loop, con la app ya abierta. Si la persona
        entra antes a una pantalla pendiente, `_load_module` la arma en ese momento."""
        try:
            if self._pre_pendientes:
                if _ms_sin_actividad() < PRECARGA_ESPERA_INACTIVIDAD_MS and self._pre_aplazadas < PRECARGA_MAX_APLAZAMIENTOS:
                    self._pre_aplazadas += 1
                    QTimer.singleShot(PRECARGA_REINTENTO_MS, self._precargar_en_arranque)
                    return
                self._pre_aplazadas = 0
                nombre = self._pre_pendientes.pop(0)
                if self._asegurar_modulo(nombre):
                    activo = self._get_active_submodule(self.loaded_modules.get(nombre))
                    if activo is not None:
                        _refrescar_modulo_visible(self, activo)
                QTimer.singleShot(ARRANQUE_ENTRE_MODULOS_MS, self._precargar_en_arranque)
            else:
                self._lanzar_director_pbi()
        except Exception as e:
            logger.warning(f"[PRECARGA] Se detuvo la precarga de las pantallas: {e}")
            self._lanzar_director_pbi()

    @staticmethod
    def _lanzar_director_pbi():
        from src.ui.general import precargar_director_empresa_pbi
        precargar_director_empresa_pbi()

    def _terminar_arranque(self):
        """Todas las pantallas listas: se abre la que el usuario eligió durante la carga o Vista General."""
        self._cargando_inicial = False
        pendiente, self._pantalla_pendiente = self._pantalla_pendiente, None
        if self.workspace.currentWidget() is self.loading_page:
            self._on_menu_clicked(pendiente if pendiente in self.menu_buttons else "Vista General")
        self.arranque_listo.emit()

    def revelar(self):
        """Muestra la ventana ya armada (ver `arranque_oculto`)."""
        self.setEnabled(True)
        self.setWindowOpacity(1.0)
        # Al cambiar la opacidad Windows puede soltar el ícono de la barra de tareas: se vuelve a fijar
        self.setWindowIcon(QApplication.windowIcon())
        self.raise_()
        self.activateWindow()
        QTimer.singleShot(400, self._programar_aviso_actualizacion)
        # Respaldo por si la precarga de pantallas no llega a su fin
        QTimer.singleShot(15000, self._lanzar_director_pbi)

    def _programar_aviso_actualizacion(self):
        from src.core.actualizador import ControlActualizacion
        control = ControlActualizacion.instancia()
        control.cambio.connect(self._mostrar_aviso_actualizacion)
        self._mostrar_aviso_actualizacion()
        # Con la app abierta durante horas también se detectan versiones publicadas después
        self._timer_revision_actualizacion = QTimer(self)
        self._timer_revision_actualizacion.setInterval(INTERVALO_REVISION_ACTUALIZACION_MS)
        self._timer_revision_actualizacion.timeout.connect(control.buscar)
        self._timer_revision_actualizacion.start()

    def _mostrar_aviso_actualizacion(self):
        from src.core.actualizador import ControlActualizacion
        control = ControlActualizacion.instancia()
        if self._cargando_inicial or not control.debe_avisar():
            return
        from src.ui.marco.dialogo_actualizacion import TarjetaAviso
        control.marcar_avisada()
        TarjetaAviso(self, control).mostrar()

    def _on_backup_automatico_finalizado(self, resultado):
        if not resultado:
            return 
        if resultado.get("error_fatal"):
            logger.error(f"[BACKUP AUTOMÁTICO] No se pudo completar: {resultado['error_fatal']}")
        elif resultado.get("fallidos"):
            logger.warning(f"[BACKUP AUTOMÁTICO] Completado con advertencias. Fallidos: {resultado['fallidos']}")
        else:
            logger.info(f"[BACKUP AUTOMÁTICO] Snapshot semanal creado en: {resultado.get('carpeta')}")

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
        self._cargando_inicial = False
        self.arranque_listo.emit()

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
            logger.warning("Watchdog omitido: No hay una ruta de Excel válida configurada.")
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
        self._iniciar_vigilantes_extra()

    def _invalidar_workbook_cache_excel_principal(self):
        from src.core.workbook_cache import WorkbookCache
        WorkbookCache.instancia().invalidar(EXCEL_PATH)

    def _on_excel_modified(self):
        estado = self.__dict__.get('estado_sync')
        if estado is not None:
            estado.detectando(cambios_archivos_service.ETIQUETA_RM)

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

    def _flotas_por_vin(self):
        """{VIN: FLOTA VC} del contrato actual, para nombrar la flota en los avisos de gestión CM."""
        df = getattr(self.data_manager, 'df_master', None)
        if df is None or df.empty or not {'VIN', 'FLOTA VC'} <= set(df.columns):
            return {}
        vins = df['VIN'].astype(str).str.strip().str.upper()
        flotas = df['FLOTA VC'].astype(str).str.strip()
        return dict(zip(vins, flotas))

    def _on_snapshot_finished(self, cambios):
        panel = self.__dict__.get('panel_notificaciones')
        if panel is not None:
            panel.fijar_revision()
            if cambios:
                cambios = comercial_services.avisos_gestion_cm(cambios, self._flotas_por_vin())
                panel.registrar(cambios_archivos_service.ETIQUETA_RM, cambios, cambios_archivos_service.ENTIDAD_RM)
        estado = self.__dict__.get('estado_sync')
        if estado is not None:
            estado.actualizado(cambios_archivos_service.ETIQUETA_RM,
                               cambios_archivos_service.resumen(cambios, cambios_archivos_service.ENTIDAD_RM))

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

    # ------------------------------------------------------------------
    # Provisiones y Contactos: aviso y recarga cuando cambian fuera de la app
    # ------------------------------------------------------------------
    @staticmethod
    def _archivos_vigilados():
        return (cambios_archivos_service.ETIQUETA_RM,) + tuple(
            cambios_archivos_service.etiqueta(c) for c in cambios_archivos_service.ARCHIVOS)

    def _iniciar_vigilantes_extra(self):
        if '_vigilantes_extra' in self.__dict__:
            return
        from src.core.file_watcher import WatchdogThread
        self._vigilantes_extra = {}
        self._hilos_comparacion = {}
        self._comparacion_pendiente = set()
        for clave in cambios_archivos_service.ARCHIVOS:
            ruta = cambios_archivos_service.ruta_de(clave)
            if not ruta or not os.path.exists(ruta):
                continue
            hilo = WatchdogThread(os.path.dirname(ruta), os.path.basename(ruta))
            # El vigilante ya ignora los guardados propios; aquí llega un cambio externo
            hilo.file_changed_signal.connect(lambda c=clave: self._on_archivo_extra_modificado(c))
            hilo.start()
            self._vigilantes_extra[clave] = hilo
            # La base inicial se crea con calma, para no competir con el arranque
            QTimer.singleShot(30000, lambda c=clave: self._lanzar_comparacion(c, "asegurar"))
        self.data_manager.provisiones_ready.connect(lambda: self._actualizar_base_extra("provisiones"))
        self.data_manager.contactos_ready.connect(lambda: self._actualizar_base_extra("contactos"))

    def _lanzar_comparacion(self, clave, modo):
        previo = self._hilos_comparacion.get(clave)
        if previo is not None and previo.isRunning():
            if modo == "comparar":
                self._comparacion_pendiente.add(clave)
            return
        if modo == "asegurar" and self.__dict__.get('estado_sync') is not None:
            self.estado_sync.revisado(cambios_archivos_service.etiqueta(clave))
        hilo = CompararArchivoThread(clave, modo)
        if modo == "comparar":
            hilo.finished_signal.connect(lambda cambios, c=clave: self._on_comparacion_extra(c, cambios))
        else:
            hilo.finished_signal.connect(lambda _cambios, c=clave: self._relanzar_si_pendiente(c))
        self._hilos_comparacion[clave] = hilo
        iniciar_hilo_retenido(hilo)

    def _relanzar_si_pendiente(self, clave):
        if clave in self._comparacion_pendiente:
            self._comparacion_pendiente.discard(clave)
            self._lanzar_comparacion(clave, "comparar")

    def _on_archivo_extra_modificado(self, clave):
        estado = self.__dict__.get('estado_sync')
        if estado is not None:
            estado.detectando(cambios_archivos_service.etiqueta(clave))
        self._lanzar_comparacion(clave, "comparar")

    def _on_comparacion_extra(self, clave, cambios):
        etiqueta = cambios_archivos_service.etiqueta(clave)
        entidad = cambios_archivos_service.entidad(clave)
        panel = self.__dict__.get('panel_notificaciones')
        if panel is not None:
            panel.fijar_revision()
            if cambios:
                panel.registrar(etiqueta, cambios, entidad)
        estado = self.__dict__.get('estado_sync')
        if estado is not None:
            estado.actualizado(etiqueta, cambios_archivos_service.resumen(cambios, entidad))
        pantallas = [str(n) for n, w in self.loaded_modules.items() if getattr(w, 'pending_changes', None)]
        if pantallas:
            logger.info(f"{etiqueta} cambió fuera de la app; no se recarga porque hay cambios sin guardar en: {', '.join(pantallas)}.")
        elif clave == "provisiones":
            self.data_manager.load_provisiones_async()
        elif clave == "contactos":
            self.data_manager.load_contactos_async()
        elif clave == "casos_cm" and cambios:
            self._refrescar_oportunidades_cm()
        self._relanzar_si_pendiente(clave)

    def _refrescar_oportunidades_cm(self):
        """Oportunidades CM lee CasosBajaCM.csv al repintar: basta con repintarla si está a la vista."""
        modulo = self.loaded_modules.get("Comercial")
        if modulo is None:
            return
        from src.ui.comercial.pantalla import ComercialModule
        comercial = modulo if isinstance(modulo, ComercialModule) else next(iter(modulo.findChildren(ComercialModule)), None)
        if comercial is not None and getattr(comercial, '_new_ui_active_subtab', None) == comercial._NEW_UI_SUBTAB_REVISION_CM:
            comercial._refresh_new_ui_data()

    def _actualizar_base_extra(self, clave):
        """Tras un guardado propio, la base de comparación pasa a ser el archivo ya guardado: así esos
        cambios no aparecen después como ajenos."""
        import time
        from src.core.file_watcher import VENTANA_SILENCIO_GUARDADO_SEGUNDOS
        try:
            if time.time() - float(self.data_manager.save_timestamp) > VENTANA_SILENCIO_GUARDADO_SEGUNDOS:
                return
        except (TypeError, ValueError):
            return
        self._lanzar_comparacion(clave, "base")

    def _update_notification_badge(self):
        self.notif_btn.fijar_contador(self.notification_count)

    def _on_no_leidos_cambiado(self, cantidad):
        if cantidad > self.notification_count:
            self.notif_btn.sonar()
        self.notification_count = cantidad
        self._update_notification_badge()

    def _show_notifications(self):
        """La campana abre y cierra el panel. Si el panel acaba de cerrarse por el mismo clic
        (clic fuera, sobre la campana), no se vuelve a abrir."""
        import time
        menu = self.notif_menu
        if menu.isVisible():
            menu.setVisible(False)
            return
        if time.monotonic() - menu.cerrado_en < 0.3:
            return
        if self.notification_count > 0:
            self.notification_count = 0
            self._update_notification_badge()
        ancla = self.__dict__.get('capsula') or self.notif_btn
        derecha = ancla.mapToGlobal(ancla.rect().bottomRight())
        menu.mostrar(QPoint(derecha.x() - menu.sizeHint().width() + 1, derecha.y() + 6))

    def closeEvent(self, event):
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("sidebar_expanded", self._sidebar_previo if self._sidebar_bloqueado else self.sidebar_expanded)

        if "Operaciones" in self.loaded_modules:
            self.loaded_modules["Operaciones"].table.save_state()
        if "Provisiones" in self.loaded_modules:
            self.loaded_modules["Provisiones"].table.save_state()
            
        if hasattr(self, 'watcher_thread'):
            self.watcher_thread.stop()
        for vigilante in self.__dict__.get('_vigilantes_extra', {}).values():
            vigilante.stop()
        if hasattr(self, 'file_lock_monitor_thread'):
            self.file_lock_monitor_thread.stop()
        # No cortar una escritura de CasosBajaCM.csv a medias.
        hilo_reconciliacion = getattr(self, '_reconciliacion_thread', None)
        if hilo_reconciliacion is not None and hilo_reconciliacion.isRunning():
            hilo_reconciliacion.wait(10000)
        super().closeEvent(event)

    def _setup_sidebar(self):
        # Estilo de volvo-dashboard-v2.html (ver sidebar_estilo.py): el
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
        cabecera_layout.setContentsMargins(0, 0, 0, 0)
        # Un solo dibujo: el camión sigue el borde del menú (ver CabeceraCamion)
        self.cabecera_camion = CabeceraCamion(get_resource_path(os.path.join("src", "assets")))
        self.cabecera_camion.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cabecera_camion.setToolTip("Ocultar/Mostrar menú lateral")
        self.cabecera_camion.mousePressEvent = lambda e: self._toggle_sidebar()
        cabecera_layout.addWidget(self.cabecera_camion)
        self.sidebar_layout.addWidget(self.cabecera_sidebar)

        self.sidebar_content = QWidget()
        content_layout = QVBoxLayout(self.sidebar_content)
        content_layout.setContentsMargins(sidebar_estilo.MARGEN_NAV, 0, sidebar_estilo.MARGEN_NAV, 20)
        content_layout.setSpacing(4)
        self.sidebar_layout.addWidget(self.sidebar_content)

        self.etiqueta_menu_sidebar = QLabel("MENÚ")
        self.etiqueta_menu_sidebar.setStyleSheet(sidebar_estilo.QSS_ETIQUETA)
        self.etiqueta_menu_sidebar.setContentsMargins(12, 22, 0, 8)
        # Alto fijo con el texto puesto: al plegar la etiqueta queda vacía y no debe subir los botones
        self.etiqueta_menu_sidebar.setFixedHeight(self.etiqueta_menu_sidebar.sizeHint().height())
        content_layout.addWidget(self.etiqueta_menu_sidebar)

        # Menús con iconos adaptados para parecerse más a la imagen
        menus = [
            ("Dashboard", "fa5s.chart-pie", "Dashboard BI",
                [("Resumen", "fa5s.chart-line"), ("Qué mejorar", "fa5s.crosshairs")]),
            ("Clientes y Flota", "fa5s.building", "Vista General", None),
            ("Comercial", "fa5s.handshake", "Comercial", None),
            ("Operaciones", "fa5s.shipping-fast", "Operaciones", None),
            ("Ingresos y Conciliación", "fa5s.balance-scale", "Ingresos y Conciliación",
                [("Provisiones", "fa5s.piggy-bank"), ("Contratos (CM)", "fa5s.file-signature"),
                 ("Facturación Manual", "fa5s.file-invoice-dollar"), ("JustTime", "fa5s.stopwatch")]),
            ("Administración", "fa5s.archive", "Administración",
                [("Historial", "fa5s.history"), ("Instalaciones", "fa5s.satellite-dish"),
                 ("Contactos", "fa5s.address-book"), ("Catálogos", "fa5s.user-tie"),
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
            btn.setFixedHeight(46)

            atajo = f" · Ctrl+{self._PANTALLAS_ATAJO.index(internal_key) + 1}" if internal_key in self._PANTALLAS_ATAJO else ""
            btn.setToolTip(f"Ir a {display_text}{atajo}")
            btn.clicked.connect(lambda checked, t=internal_key: self._on_menu_clicked(t))

            content_layout.addWidget(btn)
            self.menu_buttons[internal_key] = btn

        content_layout.addStretch()
        self.sidebar.registrar_botones(self.menu_buttons.values())

        # Foto de un camión Volvo al pie del sidebar (elegida en Configuración, o al azar al abrir la
        # app). Va en el layout externo, sin márgenes, para cubrir el sidebar de borde a borde. Llena
        # el alto libre hasta un tope y se funde con el degradado por arriba (ver FotoMenu).
        self.truck_decoration = FotoMenu(get_resource_path(os.path.join("src", "assets")), sidebar_estilo.ANCHO_EXPANDIDO)
        self.sidebar_layout.addWidget(self.truck_decoration)
        self._ajuste_foto_menu = AjusteAltoFoto(self.sidebar, self.cabecera_sidebar, self.sidebar_content,
                                                self.truck_decoration)
        self.aplicar_foto_menu()

        self._aplicar_estado_sidebar(True)
        self.main_layout.addWidget(self.sidebar)

    def aplicar_foto_menu(self, animado=False):
        """Pone la foto del pie del menú según Configuración (fija o al azar)."""
        self.truck_decoration.set_foto(menu_fotos.foto_a_mostrar(), animado)

    def _aplicar_estado_sidebar(self, expandido, animado=False):
        """Contenido del menú lateral expandido o plegado. Con `animado` el
        camión no se oculta aquí: se queda mientras el menú se cierra (el borde
        lo va recortando) y se oculta al terminar la animación."""
        self.etiqueta_menu_sidebar.setText("MENÚ" if expandido else "")
        # Al plegar con animación los botones conservan texto y estilo hasta el final: con el
        # texto vacío el ícono se centra en el botón que aún está ancho y salta
        if expandido or not animado:
            self._estilo_botones_menu(expandido)
            self.truck_decoration.setVisible(expandido)
        self.sidebar.update()

    def _estilo_botones_menu(self, expandido):
        for key, btn in self.menu_buttons.items():
            btn.setText(self.menu_texts[key] if expandido else "")
            btn.setStyleSheet(sidebar_estilo.qss_boton_menu(colapsado=not expandido))

    def _on_sidebar_animation_finished(self):
        self._sidebar_animating = False
        if not self.sidebar_expanded:
            self._estilo_botones_menu(False)
        self.truck_decoration.setVisible(self.sidebar_expanded)
        self._descongelar_workspace()

    def _congelar_workspace(self):
        # Evita relayouts del módulo activo en cada cuadro de la animación
        if not hasattr(self, 'workspace') or not self.workspace.isVisible():
            return
        if self.workspace.currentWidget() in [self.loaded_modules.get(n) for n in self.PAGINAS_SIDEBAR_VIVO]:
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

    def _fijar_sidebar(self, expandido):
        """Cambia el menú lateral sin animar (al entrar o salir de una pantalla que lo bloquea)."""
        if self.sidebar_expanded == expandido:
            return
        self.animation.stop()
        self._sidebar_animating = False
        ancho = sidebar_estilo.ANCHO_EXPANDIDO if expandido else sidebar_estilo.ANCHO_COLAPSADO
        self.sidebar.setMinimumWidth(ancho)
        self.sidebar.setMaximumWidth(ancho)
        self.sidebar_expanded = expandido
        self._aplicar_estado_sidebar(expandido)

    def _ajustar_sidebar_a_pagina(self, module_name):
        """El Dashboard va con el menú plegado y sin poder desplegarlo; al salir
        vuelve al estado que tenía el usuario."""
        bloqueado = module_name in self.PAGINAS_SIDEBAR_PLEGADO
        if bloqueado and not self._sidebar_bloqueado:
            self._sidebar_previo = self.sidebar_expanded
            self._fijar_sidebar(False)
        elif not bloqueado and self._sidebar_bloqueado:
            self._fijar_sidebar(self._sidebar_previo)
        self._sidebar_bloqueado = bloqueado
        self.cabecera_camion.setCursor(Qt.CursorShape.ArrowCursor if bloqueado else Qt.CursorShape.PointingHandCursor)

    def _toggle_sidebar(self):
        if self._sidebar_animating or self._sidebar_bloqueado:
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
        self._aplicar_estado_sidebar(self.sidebar_expanded, animado=True)
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
        self.search_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        # Debounce (ver DEBOUNCE_BUSQUEDA_GLOBAL_MS): el filtrado real
        # (_on_global_search) se dispara desde el timeout del timer, no desde
        # cada tecla directamente.
        self._global_search_timer = QTimer(self)
        self._global_search_timer.setSingleShot(True)
        self._global_search_timer.timeout.connect(self._ejecutar_busqueda_global_pendiente)
        self._pending_search_text = ""
        self.search_bar.textChanged.connect(self._on_global_search_text_changed)

        # Cifras junto al buscador: términos buscados y filas seleccionadas en la tabla visible
        self.pill_buscados = self._crear_pill_contador("pillBuscados")
        self.pill_seleccion = barra_superior.PildoraSeleccion()
        self.pill_seleccion.hide()
        self.chip_faltantes = barra_superior.ChipFaltantes()
        self.chip_faltantes.setObjectName("chipFaltantes")
        self.chip_faltantes.hide()
        # Solo el programador ve con qué datos trabaja la app (Configuración > Avanzado)
        self.pill_datos = None
        if config.settings.MODO_PROGRAMADOR:
            prueba = config.settings.DATOS_DE_PRUEBA
            self.pill_datos = self._crear_pill_contador("pillDatos")
            self.pill_datos.setText("Datos falsos" if prueba else "Datos reales")
            self.pill_datos.setToolTip("La app usa los datos de prueba de la carpeta datos_prueba" if prueba
                                       else "La app usa los datos reales de SharePoint: lo que se guarde queda en producción")
            from src.ui.marco.konami import DetectorKonami
            self._konami = DetectorKonami(self)
        self.pill_buscados.setToolTip("Términos en el buscador y cuántos aparecen en el Registro Maestro (VIN, chasis o RUT)")
        self.pill_seleccion.setToolTip("Filas seleccionadas en la tabla de esta pantalla")
        self._indice_coincidencias = None
        self._tabla_sel = self._sel_modelo = self._sel_modulo = None
        self._timer_conteo_sel = QTimer(self)
        self._timer_conteo_sel.setSingleShot(True)
        self._timer_conteo_sel.setInterval(80)
        self._timer_conteo_sel.timeout.connect(self._actualizar_contador_seleccion)
        self._timer_vigilar_sel = QTimer(self)
        self._timer_vigilar_sel.setInterval(350)
        self._timer_vigilar_sel.timeout.connect(self._vigilar_seleccion)
        self._timer_vigilar_sel.start()

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

        self.estado_sync = barra_superior.EstadoSincronizacion(self._archivos_vigilados())

        self.mail_btn = mail_btn = barra_superior.BotonIcono(
            'fa5s.envelope', "Generar y enviar correos automáticos (Cruza con Contactos CDB)", rebote=True)
        mail_btn.clicked.connect(self._open_mail_dialog)

        self.notif_btn = barra_superior.BotonIcono('fa5s.bell', "Ver registro de modificaciones en la nube")
        self.notif_btn.clicked.connect(self._show_notifications)

        from src.ui.compartido.notificaciones import MenuAnimado
        self.notif_menu = MenuAnimado(self)
        self.notif_menu.boton_ancla = self.notif_btn
        self.notif_menu.setStyleSheet("""
            QMenu { background-color: transparent; border: 1px solid #D5DCE8; border-radius: 17px; padding: 0px; }
        """)
        
        from PyQt6.QtWidgets import QWidgetAction
        from src.ui.compartido.notificaciones import PanelNotificaciones
        self.panel_notificaciones = PanelNotificaciones(archivos_vigilados=self._archivos_vigilados(), parent=self.notif_menu)
        self.panel_notificaciones.no_leidos_cambiado.connect(self._on_no_leidos_cambiado)
        menu_action = QWidgetAction(self.notif_menu)
        menu_action.setDefaultWidget(self.panel_notificaciones)
        self.notif_menu.addAction(menu_action)
        self.notif_menu.aboutToHide.connect(self.panel_notificaciones.marcar_leidos)

        self.config_btn = barra_superior.BotonIcono(
            'fa5s.cog', "Configuración (rutas de archivos, respaldos y ajustes)", giro=120.0)
        self.config_btn.setEnabled(False)
        self.config_btn.clicked.connect(self._go_to_configuracion)

        gestor_tema = GestorTema.instancia()
        self.btn_tema = BotonTema(gestor_tema.modo == OSCURO)
        self.btn_tema.toggled.connect(self._on_boton_tema)
        self._transicion_tema = TransicionCirculo(self)
        gestor_tema.tema_cambiado.connect(self._on_tema_cambiado)
        self._on_tema_cambiado(gestor_tema.modo)

        def _estados_busqueda(lista):
            df = getattr(DataManager(), 'df_master', None)
            if df is None:
                return None
            if self._indice_coincidencias is None:
                from src.services import contadores_busqueda as cb
                self._indice_coincidencias = cb.IndiceCoincidencias()
            return self._indice_coincidencias.estados(df, lista)

        self.buscador = barra_superior.BuscadorPildora(self.search_bar, self.pill_buscados, _estados_busqueda)
        self.capsula = barra_superior.CapsulaAcciones(
            ([self.pill_datos] if self.pill_datos is not None else [])
            + [self.estado_sync, self.notif_btn, mail_btn, barra_superior._Separador(), self.btn_tema, self.config_btn])
        if self.pill_datos is not None:
            # Con padre ya asignado: mostrarla antes abría una ventanita suelta que parpadeaba
            self.pill_datos.show()

        header_layout.setSpacing(12)
        header_layout.addWidget(self.buscador, 1)
        header_layout.addWidget(self.chip_faltantes, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(self.pill_seleccion, 0, Qt.AlignmentFlag.AlignVCenter)
        header_layout.addWidget(self.capsula)

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
        shortcut_f5.activated.connect(self._recargar_datos_atajo)
        
        shortcut_find = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_find.activated.connect(self._focus_search_bar)

        # Pantallas: Ctrl+1..6 en el orden del menú lateral; subpestañas: Alt+1..5 y Ctrl+Tab
        for numero, clave in enumerate(self._PANTALLAS_ATAJO, start=1):
            QShortcut(QKeySequence(f"Ctrl+{numero}"), self).activated.connect(lambda c=clave: self._on_menu_clicked(c))
        for numero in range(1, 6):
            QShortcut(QKeySequence(f"Alt+{numero}"), self).activated.connect(lambda n=numero: self._ir_a_subpestana(n - 1))
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(lambda: self._mover_subpestana(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self).activated.connect(lambda: self._mover_subpestana(-1))
        QShortcut(QKeySequence("Ctrl+,"), self).activated.connect(self._abrir_configuracion_atajo)
        QShortcut(QKeySequence("F1"), self).activated.connect(self._abrir_ayuda_atajos)

    _PANTALLAS_ATAJO = ("Dashboard BI", "Vista General", "Comercial", "Operaciones", "Ingresos y Conciliación", "Administración")

    def _franja_subpestanas(self):
        """Subpestañas de la pantalla visible: (índices visibles, índice actual, función para abrir un índice) o None."""
        pantalla = self.workspace.currentWidget()
        if pantalla is None:
            return None
        es_grupo = any(pantalla is self.loaded_modules.get(k) for k in self.group_definitions)
        grupo = getattr(pantalla, 'tabs', None) if es_grupo else None
        if grupo is not None:
            selector = getattr(pantalla, 'selector_grupo', None)

            def abrir_grupo(i):
                tabs_clic = getattr(selector, 'tabBarClicked', None)
                if tabs_clic is not None:
                    tabs_clic.emit(i)
                grupo.setCurrentIndex(i)
            indices = [i for i in range(grupo.count()) if grupo.isTabEnabled(i)]
            return indices, grupo.currentIndex(), abrir_grupo
        barra = getattr(pantalla, 'new_ui_subtabs', None)
        if barra is not None:
            def abrir_barra(i):
                barra.tabBarClicked.emit(i)
                barra.setCurrentIndex(i)
            indices = [i for i in range(barra.count()) if barra.isTabVisible(i) and barra.isTabEnabled(i)]
            return indices, barra.currentIndex(), abrir_barra
        botones = getattr(pantalla, '_nav_buttons', None)
        if botones:
            indices = [i for i, b in enumerate(botones) if b.isEnabled()]
            actual = next((i for i, b in enumerate(botones) if b.isChecked()), 0)
            return indices, actual, lambda i: botones[i].click()
        return None

    def _ir_a_subpestana(self, posicion):
        franja = self._franja_subpestanas()
        if franja is None:
            return
        indices, _actual, abrir = franja
        if 0 <= posicion < len(indices):
            abrir(indices[posicion])

    def _mover_subpestana(self, paso):
        franja = self._franja_subpestanas()
        if franja is None:
            return
        indices, actual, abrir = franja
        if len(indices) < 2:
            return
        posicion = indices.index(actual) if actual in indices else 0
        abrir(indices[(posicion + paso) % len(indices)])

    def _abrir_configuracion_atajo(self):
        if self.config_btn.isEnabled():
            self._go_to_configuracion()

    def _abrir_ayuda_atajos(self):
        """F1: abre Configuración > Ayuda, donde está la lista de atajos."""
        if not self.config_btn.isEnabled():
            return
        self._go_to_configuracion()
        config = self.loaded_modules.get("Configuración")
        if config is not None and hasattr(config, '_botones_seccion'):
            config._botones_seccion[4].setChecked(True)
            config._cambiar_seccion(4)

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

    def _recargar_datos_atajo(self):
        """F5: vuelve a leer los archivos de datos, en cualquier pantalla."""
        pantallas = [str(n) for n, w in self.loaded_modules.items() if getattr(w, 'pending_changes', None)]
        if pantallas:
            respuesta = QMessageBox.question(
                self, "Recargar datos",
                "Tienes cambios sin guardar en: " + ", ".join(pantallas) + ".\n\n"
                "Si recargas, se descartarán. ¿Quieres recargar igual?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if respuesta != QMessageBox.StandardButton.Yes:
                return
        self.data_manager.load_data_async()
        self.data_manager.load_provisiones_async()
        self.data_manager.load_contactos_async()

    def _focus_search_bar(self):
        self.search_bar.setFocus()
        self.search_bar.selectAll()

    def _instantiate_module(self, module_name):
        module = self._instantiate_module_impl(module_name)
        if module is not None:
            for sub_tabs in module.findChildren(QTabWidget):
                instalar_transicion_pestanas(sub_tabs)
        return module

    def _instantiate_module_impl(self, module_name):
        if module_name == "Vista General":
            from src.ui.general import GeneralModule
            module = GeneralModule()
        elif module_name == "Resumen":
            from src.ui.dashboard.resumen import DashboardResumenModule
            module = DashboardResumenModule()
        elif module_name == "Qué mejorar":
            from src.ui.dashboard.mejorar import DashboardMejorarModule
            module = DashboardMejorarModule()
        elif module_name == "Comercial":
            from src.ui.comercial import ComercialModule
            module = ComercialModule()
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
            from src.ui.facturacion_manual.pantalla import FacturacionManualModule
            module = FacturacionManualModule()
        elif module_name == "JustTime":
            from src.ui.ingresos.justtime import JustTimeModule
            module = JustTimeModule()
        elif module_name == "Instalaciones":
            from src.ui.administracion.instalaciones import InstalacionesModule
            module = InstalacionesModule()
        elif module_name == "Historial":
            from src.ui.administracion.historial import HistorialModule
            module = HistorialModule()
        elif module_name == "Contactos":
            from src.ui.administracion.contactos import ContactosModule
            module = ContactosModule()
        elif module_name == "Catálogos":
            from src.ui.administracion.catalogos import CatalogosModule
            module = CatalogosModule()
        elif module_name == "Clientes":
            from src.ui.administracion.clientes import ClientesAdminModule
            module = ClientesAdminModule()
        elif module_name == "Configuración":
            from src.ui.marco.configuracion import ConfiguracionModule
            module = ConfiguracionModule()
        else:
            return None
        self.loaded_modules[module_name] = module
        return module

    def _build_group_module(self, group_key):
        return self._build_group_module_impl(group_key)

    def _build_group_module_impl(self, group_key):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        # La barra nativa se oculta: las pestañas del grupo se eligen con el
        # mismo selector segmentado de Comercial
        if group_key == "Dashboard BI":
            from src.ui.dashboard.deslizamiento import TabsVerticales
            tabs = TabsVerticales()
        else:
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
        pestanas_bajo_kpi = group_key in ("Ingresos y Conciliación", "Administración", "Dashboard BI")

        def _colocar_selector(modulo):
            lay = modulo.layout() if pestanas_bajo_kpi else None
            if lay is None:
                return
            previo = getattr(modulo, '_selector_grupo', None)
            if previo is not None:
                envoltura_previa = getattr(previo, '_envoltura', None)
                lay.removeWidget(envoltura_previa or previo)
                (envoltura_previa or previo).deleteLater()
            if group_key in ("Administración", "Dashboard BI"):
                from src.ui.administracion.estilo import EncabezadoAdministracion
                _titulo, _sub, _miembros = self._ENCABEZADOS_GRUPO[group_key]
                selector_modulo = EncabezadoAdministracion(
                    tabs, _titulo, _sub, separado=bool(getattr(modulo, 'ENCABEZADO_SEPARADO', False)),
                    subtitulos=self._PROPOSITO_PESTANA if group_key == "Dashboard BI" else None,
                    compacto=group_key == "Dashboard BI")
            else:
                selector_modulo = estilo_com.SelectorSubpestanas(tabs)
            selector_modulo.tabBarClicked.connect(tabs.tabBar().tabBarClicked.emit)
            kpi = getattr(modulo, '_kpi_contenedor', None)
            posicion = lay.indexOf(kpi) + 1 if kpi is not None and lay.indexOf(kpi) >= 0 else 0
            a_insertar = selector_modulo
            if group_key == "Dashboard BI":
                # El encabezado deja a su izquierda un hueco para la caja de filtros, que sube a su altura (ver el Resumen)
                envoltura = QWidget()
                fila_env = QHBoxLayout(envoltura)
                fila_env.setContentsMargins(0, 0, 0, 0)
                fila_env.setSpacing(0)
                hueco = QWidget()
                hueco.setFixedWidth(0)
                fila_env.addWidget(hueco)
                fila_env.addWidget(selector_modulo, 1)
                selector_modulo._envoltura = envoltura
                modulo._hueco_cabecera = hueco
                a_insertar = envoltura
            lay.insertWidget(posicion, a_insertar)
            modulo._selector_grupo = selector_modulo
            if group_key == "Dashboard BI":
                getattr(modulo, '_reubicar_filtros', lambda: None)()

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
            # El selector del módulo debe marcar ya la pestaña nueva: la transición fotografía
            # la pantalla en este mismo cambio, antes de que corran los demás selectores
            selector_actual = getattr(tabs.widget(idx), '_selector_grupo', None)
            if selector_actual is not None:
                selector_actual._sincronizar(idx)
            self._trigger_load_data(self._get_active_submodule(tabs.currentWidget()))
            if group_key == "Dashboard BI":
                getattr(tabs.widget(idx), 'mostrar_cambio_pestana', lambda: None)()
            elif group_key == "Administración":
                animar_cajas(tabs.widget(idx))
            elif group_key == "Ingresos y Conciliación":
                animar_tabla_principal(tabs.widget(idx))
            sub_name = tabs.tabText(idx)
            self._update_module_chip(sub_name)

        tabs.currentChanged.connect(_on_tab_changed)
        # Se instala después de _on_tab_changed para animar ya el módulo materializado
        # El Dashboard y Administración cambian de pestaña con el esqueleto de carga, no con la foto que se desvanece
        if group_key not in ("Dashboard BI", "Administración", "Ingresos y Conciliación"):
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

    PAGINAS_SIDEBAR_PLEGADO = ("Dashboard BI",)
    # Pantallas cuya tabla se estira en vivo con el menú, sin la foto congelada
    PAGINAS_SIDEBAR_VIVO = ("Comercial", "Operaciones", "Vista General", "Ingresos y Conciliación",
                            "Administración", "Configuración")
    _sidebar_bloqueado = False
    _sidebar_previo = True

    _ENCABEZADOS_PAGINA = {
        "Dashboard BI": ("Dashboard", "Resumen general de la flota y los indicadores del negocio."),
        "Vista General": ("Clientes y Flota", "Clientes, contratos y su estado en la flota."),
        "Comercial": ("Gestión comercial", "Unidades y clientes que requieren una acción del equipo."),
        "Operaciones": ("Operaciones", "Cola de operaciones: activaciones, unidades sin flota y bajas."),
        "Configuración": ("Configuración", "Rutas de archivos, respaldos y ajustes del sistema."),
    }
    _PROPOSITO_PESTANA = {
        "Resumen": "Cómo está el negocio hoy: camiones activos, entradas y salidas, ventas del mes y metas.",
        "Qué mejorar": "Dónde actuar: clientes por recuperar o a quienes ofrecer el servicio, dónde se pierden camiones y cómo conecta cada ejecutivo.",
    }
    _ENCABEZADOS_GRUPO = {
        "Dashboard BI": (
            "Dashboard",
            "Volvo Connect · Gestión del negocio.",
            ("Resumen", "Qué mejorar")),
        "Ingresos y Conciliación": (
            "Ingresos y Conciliación",
            "Provisiones, contratos CM, facturación manual y conciliación JustTime.",
            ("Provisiones", "Contratos (CM)", "Facturación Manual", "JustTime")),
        "Administración": (
            "Administración",
            "Historial de cambios, instalaciones, contactos, catálogos y clientes del sistema.",
            ("Historial", "Instalaciones", "Contactos", "Catálogos", "Clientes")),
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
        buscador = self.__dict__.get('buscador')
        if buscador is not None:
            buscador.fijar_modo_flota(module_name in ("Dashboard BI", "Resumen", "Qué mejorar"))
        # Clientes y Flota dibuja su propio título para que la caja derecha suba al borde
        # Administración dibuja su propio encabezado (panel azul con las pestañas)
        self.page_head.setVisible(module_name not in (
            "Vista General", "Dashboard BI", "Resumen", "Qué mejorar", "Configuración",
            "Administración", "Historial", "Instalaciones", "Contactos", "Catálogos", "Clientes"))
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
        return capturar(self.workspace)

    def _asegurar_modulo(self, module_name):
        """Construye el módulo y lo agrega al workspace sin mostrarlo, si aún no existe.
        Devuelve False si el nombre no corresponde a ningún módulo."""
        if module_name in self.loaded_modules:
            return True
        if module_name in self.group_definitions:
            module = self._build_group_module(module_name)
        else:
            module = self._instantiate_module(module_name)
        if module is None:
            return False
        self.workspace.addWidget(module)
        return True

    def _load_module(self, module_name):
        foto_anterior = self._foto_para_transicion(module_name)

        if not self._asegurar_modulo(module_name):
            return

        self.workspace.setCurrentWidget(self.loaded_modules[module_name])
        self._ajustar_sidebar_a_pagina(module_name)
        self._aplicar_busqueda_vin_antes_de_mostrar(self._get_active_submodule(self.loaded_modules[module_name]))

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

    def _aplicar_busqueda_vin_antes_de_mostrar(self, modulo):
        """Una búsqueda por VIN se aplica antes de la transición, para que las pestañas que se ocultan no se vean
        aparecer un instante (el resto de las búsquedas se aplican después, ver _refrescar_modulo_tras_transicion)."""
        barra = getattr(self, 'search_bar', None)
        if barra is None or modulo is None or not hasattr(modulo, 'search_input'):
            return
        texto = barra.text()
        if modulo.search_input.text() != texto:
            from src.services import localizador_vin
            if localizador_vin.extraer_vins(texto):
                self._aplicar_busqueda_a_modulo(modulo, texto)

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
        token = None
        if self is not None:
            self._token_refresco = getattr(self, '_token_refresco', 0) + 1
            token = self._token_refresco
        QTimer.singleShot(0, lambda: _refrescar_modulo_tras_transicion(self, modulo, token))

    def _on_menu_clicked(self, clicked_text):
        for text, btn in self.menu_buttons.items():
            if text == clicked_text: btn.setChecked(True)
            else: btn.setChecked(False)

        if self._cargando_inicial:
            # Los datos siguen cargando: se sigue viendo la pantalla de carga y la elegida se abre al terminar
            self._pantalla_pendiente = clicked_text
            return

        self._load_module(clicked_text)

        modulo_actual = self._get_active_submodule(self.loaded_modules.get(clicked_text))
        self._trigger_load_data(modulo_actual)

    def abrir_unidad_en_general(self, vin):
        """Lleva a Clientes y Flota -> Unidades con `vin` seleccionado (ficha en la caja derecha)."""
        self._on_menu_clicked("Vista General")
        general = self.loaded_modules.get("Vista General")
        if general is not None:
            general._abrir_unidad_en_pestana_unidades(vin)

    def abrir_vin_en(self, pantalla, vin):
        """Lleva a Comercial u Operaciones con el VIN en la búsqueda global, para ver esa unidad allí."""
        self.search_bar.setText(vin)
        self._on_menu_clicked(pantalla)

    def abrir_nuevo_contacto_flota(self, cdb, flota):
        """Lleva a Administración > Contactos con el formulario de nuevo administrador de flota ya con `cdb` y `flota`."""
        self._on_menu_clicked("Administración")
        grupo = self.loaded_modules.get("Administración")
        if grupo is None:
            return
        tabs = grupo.tabs
        for i in range(tabs.count()):
            if tabs.tabText(i) == "Contactos":
                tabs.setCurrentIndex(i)
                modulo = tabs.widget(i)
                if hasattr(modulo, 'abrir_alta_flota'):
                    modulo.abrir_alta_flota(cdb, flota)
                return

    def abrir_contratos_en_general(self, vins, titulo):
        """Lleva a Clientes y Flota -> Contratos mostrando solo las unidades `vins` (sin pasar por el buscador, que tiene tope)."""
        from src.ui.compartido.guardado_overlay import mostrar_guardando, terminar_guardando
        # Velo con spinner mientras se arma la lista: la pantalla General tarda en pintar miles de tarjetas
        mostrar_guardando(self, "Abriendo los contratos…", titulo, demora="Está tardando más de lo normal. La lista sigue cargando.")

        def abrir():
            try:
                self._on_menu_clicked("Vista General")
                general = self.loaded_modules.get("Vista General")
                if general is not None:
                    general.mostrar_contratos_de_vins(vins, titulo)
            finally:
                QTimer.singleShot(450, lambda: terminar_guardando(self, exito=False))

        QTimer.singleShot(60, abrir)

    def abrir_flotas_en_general(self, vins, titulo):
        """Lleva a Clientes y Flota -> Flotas con las flotas de las unidades `vins`; la caja derecha abre la primera
        con esas unidades a la vista."""
        from src.ui.compartido.guardado_overlay import mostrar_guardando, terminar_guardando
        mostrar_guardando(self, "Abriendo las flotas…", titulo, demora="Está tardando más de lo normal. La lista sigue cargando.")

        def abrir():
            n_flotas = None
            try:
                self._on_menu_clicked("Vista General")
                general = self.loaded_modules.get("Vista General")
                if general is not None:
                    n_flotas = general.mostrar_flotas_de_vins(vins, titulo)
            finally:
                QTimer.singleShot(450, lambda: terminar_guardando(self, exito=False))
            if n_flotas == 0:
                general._quitar_filtro_vins_flotas()
                from src.ui.compartido.dialogo_accion import DialogoAccion
                DialogoAccion.aviso(self, "Sin flotas", "Estas unidades no tienen una Flota VC asignada, por eso no hay flotas que mostrar.").exec()

        QTimer.singleShot(60, abrir)

    def abrir_cliente_en_general(self, clave, vins, titulo):
        """Lleva a Clientes y Flota -> Cliente con ese cliente y sus unidades `vins` a la vista (también las que
        no tienen Flota VC). Si el cliente no está en General, cae a Flotas."""
        from src.ui.compartido.guardado_overlay import mostrar_guardando, terminar_guardando
        mostrar_guardando(self, "Abriendo el cliente…", titulo, demora="Está tardando más de lo normal. La lista sigue cargando.")

        def abrir():
            abierto = False
            try:
                self._on_menu_clicked("Vista General")
                general = self.loaded_modules.get("Vista General")
                if general is not None:
                    abierto = general.mostrar_cliente_de_vins(clave, vins)
            finally:
                QTimer.singleShot(450, lambda: terminar_guardando(self, exito=False))
            if not abierto:
                self.abrir_flotas_en_general(vins, titulo)

        QTimer.singleShot(60, abrir)

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
        buscador = self.__dict__.get('buscador')
        # En el Dashboard solo se sugieren flotas (filtrado liviano): se responde antes
        rapido = buscador is not None and getattr(buscador, '_modo_flota', False)
        self._global_search_timer.start(90 if rapido else DEBOUNCE_BUSQUEDA_GLOBAL_MS)

    def _ejecutar_busqueda_global_pendiente(self):
        """Timeout del debounce: recien aca se ejecuta el filtrado real,
        exactamente igual que antes (_on_global_search sin cambios)."""
        self._actualizar_contador_busqueda(self._pending_search_text)
        self._on_global_search(self._pending_search_text)
        self._buscar_en_pantallas_ocultas(self._pending_search_text)

    PAUSA_BUSQUEDA_FONDO_MS = 150

    def _buscar_en_pantallas_ocultas(self, texto):
        """Deja la búsqueda ya aplicada en las demás pantallas abiertas, una por vez y con pausas para no
        trabar la actual: así al cambiar de pantalla los datos ya están filtrados. Un texto nuevo cancela la ronda."""
        self._token_busqueda_fondo = self.__dict__.get('_token_busqueda_fondo', 0) + 1
        token = self._token_busqueda_fondo
        actual = self._get_active_submodule(self.workspace.currentWidget())
        pendientes = []
        for nombre, raiz in self.loaded_modules.items():
            modulo = self._get_active_submodule(raiz)
            if modulo is not None and modulo is not actual and hasattr(modulo, 'search_input') and modulo not in pendientes:
                pendientes.append(modulo)

        def siguiente():
            if token != self._token_busqueda_fondo or self._cargando_inicial:
                return
            while pendientes:
                modulo = pendientes.pop(0)
                try:
                    if modulo.isVisible() or modulo.search_input.text() == texto:
                        continue
                    self._aplicar_busqueda_a_modulo(modulo, texto)
                except RuntimeError:   # la pantalla se cerró mientras tanto
                    continue
                break
            if pendientes:
                QTimer.singleShot(self.PAUSA_BUSQUEDA_FONDO_MS, siguiente)

        QTimer.singleShot(self.PAUSA_BUSQUEDA_FONDO_MS, siguiente)

    def _on_global_search(self, text):
        current_widget = self._get_active_submodule(self.workspace.currentWidget())
        if not current_widget: return
        self._animar_busqueda_en_tabla(current_widget)
        self._aplicar_busqueda_a_modulo(current_widget, text)

    DURACION_ANIMACION_BUSQUEDA_MS = 650

    def _animar_busqueda_en_tabla(self, modulo):
        """Esqueleto corto sobre la tabla más grande visible del módulo al
        buscar. General ya anima sus propias cajas."""
        if hasattr(modulo, '_animar_carga_breve') or getattr(modulo, '_sin_animacion_busqueda', False):
            return
        from PyQt6.QtWidgets import QAbstractItemView
        tablas = [t for t in modulo.findChildren(QAbstractItemView) if t.isVisible()]
        if not tablas:
            return
        tabla = max(tablas, key=lambda t: t.viewport().width() * t.viewport().height())
        from src.ui.compartido.esqueleto_carga import animar_sobre_tabla
        animar_sobre_tabla(tabla, self.DURACION_ANIMACION_BUSQUEDA_MS)

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
        from src.ui.compartido.mail_dialog import MailDialog
        dialog = MailDialog(parent=self)
        dialog.exec()
