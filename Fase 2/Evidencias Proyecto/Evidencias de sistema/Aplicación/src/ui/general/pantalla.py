"""Pantalla General: clientes, flotas, unidades y detalle de cada VIN."""
from src.theme.colors import BORDER, SURFACE, TEXT_MUTED
import os
import re
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QStackedWidget, QDialog, QMessageBox, QScrollArea, QLineEdit, QSizePolicy
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QEvent
from PyQt6.QtGui import QPainter
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.hilos import iniciar_hilo_retenido
from src.core.constants import COL_RAZON_SOCIAL, COL_RUT, COL_CDB_FLOTA, COL_VIN, COL_CHASIS, COL_FLOTA_VC, COL_TIPO_SERVICIO, COL_ESTADO_ACTIVACION, COL_EJECUTIVO, COL_ESTADO_COMERCIAL
from src.services import comercial_services, contactos_service
from src.ui.comercial import SaveExcelThread
from src.ui.administracion.contactos_agregar import ContactosAddDialog
from src.ui.administracion.contactos import AddContactoThread
from src.ui.compartido.esqueleto_carga import EsqueletoCarga
from src.ui.compartido.marco_tema import MarcoTema, PROP_TRANSPARENTE_FORZADO
from src.theme import tema as _tema_gestor
from src.theme.theme_manager import ThemeManager
from config.settings import POWERBI_EXCEL_PATH
from src.services import general_services
from src.ui.general.base import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    COLUMNAS_CLIENTES,
    COLUMNAS_FLOTAS,
    COLUMNAS_HISTORIAL,
    COLUMNAS_UNIDADES,
    ESTADO_ACTIVACION_CONECTADO,
    _FLOTA_VC_SIN_FLOTA,
    _calcular_vigencia,
    _clave_flota_texto,
    _flota_valida,
    _formatear_fecha_contrato,
    _mes_anio,
    _texto_duracion,
    logger,
    AZUL,
    AZUL_HOVER,
    TINTE_CLARO,
    LINEA_AZUL,
    TEXTO_SOBRE_AZUL,
    QSS_BOTON_AZUL,
    _boton_azul,
    QSS_BOTON_MINIMO,
    _boton_minimo,
    _boton_sobre_azul,
    _GrupoControles,
    _con_transicion_derecha,
    _crear_estado_vacio,
    _fijar_ancho_chip,
    _crear_invitacion,
    _PIXMAP_WIFI_DESCONECTADO,
    _pixmap_wifi_desconectado,
    _KpiCompacto,
    _tarjeta_blanca,
    ANCHO_MAX_CAJA_IZQUIERDA,
    ANCHO_MAX_CAJA_DERECHA,
    NUM_COLUMNAS_LISTA,
    FONDO_GENERAL,
    BORDE_CAJA_GENERAL,
    COLOR_CDB_FLOTA_MINORITARIO,
    COLUMNAS_UNIDADES_VISIBLES,
    COLUMNAS_BUSQUEDA_UNIDADES,
    _FICHA_VIN_GRUPOS,
    ESTADO_ACTIVACION_COLORES,
    _FILTROS_UNIDADES,
    _COLUMNAS_TABLA_FLOTA,
    _OPCIONES_TAMANO_PAGINA,
    _TARJETAS_POR_PAGINA,
    PowerBiDirectorEmpresaLoaderThread,
    _precarga_director_pbi,
    diferir_director_empresa_pbi,
    precargar_director_empresa_pbi,
    GeneralDataPrepThread,
    _StackedWidgetTamañoActual,
    _EtiquetaElidida,
    QSS_PESTANAS_SUBRAYADAS,
    QSS_CONTENEDOR_PESTANAS,
    QSS_PESTANAS_CLARAS,
    QSS_PESTANAS_CLARAS_JUSTAS,
    QSS_PESTANAS_HOJA,
    QSS_PESTANAS_HOJA_JUSTAS,
    QSS_CONTENEDOR_PESTANAS_CLARO,
    CopyableLabel,
    CopyableChip,
    CopyableTitulo,
    CopyableValueLabel,
    _EtiquetaElididaCopiable,
    _ACCENT_GENERAL,
    QSS_TARJETAS_CLIENTE,
    _EtiquetaDosLineas,
    _GrillaTarjetas,
    GeneralClienteCard,
    GeneralDuplicadoCard,
    QSS_TARJETAS_UNIDAD,
    _FICHA_VIN_SECCIONES,
    _EnlaceLabel,
    FiltroValoresBoton,
    _PAL_VERDE,
    _PAL_AMARILLO,
    _PAL_ROJO,
    _PAL_GRIS,
    _PAL_NARANJA,
    GRIS_TARJETA,
    _color_estado_comercial,
    _color_estado_activacion,
    _color_forma_facturacion,
    _es_sin_vc,
    _crear_pildora,
    GeneralUnidadFila,
    _repulir_seleccion,
    GeneralFlotaFila,
    _ContratoAnteriorCard,
    _PildoraDato,
    _ChipEstados,
    _IconoContrato,
    _icono_contrato,
    _punto_estado,
    _paleta_tarjeta,
    _paleta_fechas,
    GeneralUnidadCard,
    GeneralFlotaCard,
    _ESTADOS_FLOTA,
    _BarraEstadosFlota,
    _BloqueEstadoFlota,
    _BloqueResumenCliente,
    _FilaClienteFlota,
    _ChipCopiaLista,
    _RESUMEN_CELDA_FLOTA,
    _COLUMNAS_EXPORT_FLOTA,
    _DelegadoTextoSinInvertir,
    _resumir_celda_flota,
)
from src.ui.general.tarjetas import contar_civ_sz
from src.ui.general.vin import _VinGeneralMixin
from src.ui.general.cliente_detalle import _ClienteDetalleGeneralMixin
from src.ui.general.lista_clientes import _ListaClientesGeneralMixin
from src.ui.general.flotas import _FlotasGeneralMixin
from src.ui.general.lista_unidades import _ListaUnidadesGeneralMixin
from src.ui.general.detalle_enlaces import _DetalleEnlacesGeneralMixin
from src.ui.general.controles import _ControlesGeneralMixin


class GeneralModule(_VinGeneralMixin, _ClienteDetalleGeneralMixin, _ListaClientesGeneralMixin, _FlotasGeneralMixin, _ListaUnidadesGeneralMixin, _DetalleEnlacesGeneralMixin, _ControlesGeneralMixin, QWidget):
    """Módulo 'Clientes y Flota' (nombre de clase histórico: GeneralModule,
    mapeado desde el Sidebar en main_window.py bajo la clave interna
    'Vista General'). Caja izquierda: navegación Cliente/Flota/Unidades, con
    "Cliente" implementada (tabla resumida + filtro de Industria + alta de
    registro). Caja derecha: detalle del cliente seleccionado en la tabla
    (KPIs + pestañas Resumen/Unidades/Contactos, solo "Resumen"
    implementada por ahora)."""

    # Emitida una única vez, la primera vez que GeneralDataPrepThread termina
    # con datos reales (ver _on_prep_finished) -- usada por
    # MainWindow._cargar_vista_general_inicial (24-09-2026, a pedido
    # explícito) para no mostrar la pestaña vacía mientras arma clientes/
    # flota/unidades, extendiendo en su lugar la pantalla de carga.
    primera_carga_lista = pyqtSignal()

    # Página de left_stack que abre cada botón de pestaña, en orden visible (Flota, Cliente, Contratos)
    _VISTAS_NAV = [2, 0, 1]

    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.df_clientes_base = pd.DataFrame(columns=COLUMNAS_CLIENTES)
        self.df_unidades_base = pd.DataFrame(columns=COLUMNAS_UNIDADES)
        self.df_comercial_raw = pd.DataFrame()
        self._df_clientes_visible = pd.DataFrame(columns=COLUMNAS_CLIENTES)
        # VIN que se muestran en Contratos cuando se llega desde el Dashboard, y su título; None = sin filtro
        self._filtro_vins = None
        self._titulo_filtro_vins = ""
        self._filtro_vins_flotas = None
        self._titulo_filtro_flotas = ""

        self._selected_cdb = None
        self._selected_cdbs_flota = []
        self._selected_cliente_key = None
        # Pares (RUT, CDB) normalizados que aparecen en más de una fila de
        # df_clientes_base -- es decir, más de una Razón Social distinta
        # comparte el mismo RUT+CDB (típico error de tipeo/duplicado de
        # carga). Se recalcula en _on_prep_finished junto con df_clientes_base
        # (ver _calcular_claves_duplicadas_rut_cdb). Vacío hasta la primera carga.
        self._clientes_con_varias_razones = set()
        # Clave de cliente -> texto del aviso de flotas incoherentes (ver _calcular_avisos_flota)
        self._clientes_aviso_flota = {}
        # (RUT, CDB) del grupo de duplicados actualmente mostrado en la
        # pestaña Duplicados, o None -- ver _populate_duplicados_detalle /
        # _on_unificar_razon_social_clicked.
        self._grupo_duplicados_actual = None
        # VIN seleccionado en la caja izquierda -> Unidades: único estado
        # compartido entre la ficha y el historial de la caja derecha (ver
        # _show_vin_detalle/_show_vin_vacio) -- nunca dos estados
        # independientes que puedan desincronizarse.
        self._vin_seleccionado = None
        self._df_unidades_visible = pd.DataFrame(columns=COLUMNAS_UNIDADES)

        # Tarjetas de la caja izquierda (Cliente/Flota/Unidades, 20-09-2026):
        # reemplazan las tablas anteriores. Cada dict mapea una clave de
        # negocio estable (CDB / "CDB||Flota VC" / VIN) al widget de tarjeta
        # ya construido en el último render, para poder resaltar/desresaltar
        # solo 2 tarjetas al hacer clic (set_selected) en vez de reconstruir
        # toda la lista -- misma lección de rendimiento que provisiones.py
        # (evitar reconstrucciones masivas de tarjetas en cada clic).
        self._cliente_cards = {}
        self._unidad_cards = {}

        # Paginación de cada lista (ver _TARJETAS_POR_PAGINA): DataFrame
        # filtrado actual + página (0-based) que se está mostrando. Los
        # controles "‹ Anterior | Página X de Y | Siguiente ›" (arriba y
        # abajo de cada lista, ver _crear_controles_paginacion) se
        # inicializan en _build_cliente_view/_build_flota_view/
        # _build_unidades_view, antes de que exista cualquier dato.
        self._clientes_df_paginado = pd.DataFrame()
        self._clientes_pagina_actual = 0
        self._clientes_tam_pagina = _TARJETAS_POR_PAGINA
        self._unidades_df_paginado = pd.DataFrame()
        self._unidades_pagina_actual = 0
        self._unidades_tam_pagina = _TARJETAS_POR_PAGINA

        # Pestaña Flota (28-10-2026): una fila por Flota VC, con la misma paginación y render diferido
        self.df_flotas_base = pd.DataFrame(columns=COLUMNAS_FLOTAS)
        self._df_flotas_visible = pd.DataFrame(columns=COLUMNAS_FLOTAS)
        self._flotas_df_paginado = pd.DataFrame(columns=COLUMNAS_FLOTAS)
        self._flotas_pagina_actual = 0
        self._flotas_tam_pagina = _TARJETAS_POR_PAGINA
        self._flotas_pendiente_render = False
        self._flotas_orden_asc = True
        self._flotas_orden_campo = 'nombre'
        self._flota_cards = {}
        self._selected_flota_key = None
        self._df_flota_actual = pd.DataFrame()

        # Render diferido de pestañas ocultas (auditoria de rendimiento,
        # Fase 5, 21-09-2026): filter_table()/_on_prep_finished() actualizan
        # las 3 listas ante cada búsqueda/orden/refresh de datos, pero solo
        # UNA sub-pestaña de Cliente/Flota/Unidades es visible a la vez
        # (self.left_stack). Reconstruir las tarjetas de las otras 2 -- que
        # nadie está viendo -- medía ~1s (página 200) a ~4.5s (página 1000)
        # de trabajo invisible en cada búsqueda. Ahora _render_clientes_cards/
        # _render_flota_cards/_render_unidades_cards solo pintan si su
        # pestaña está visible; si no, marcan esta bandera True y
        # _switch_left_view pinta recién al entrar (ver
        # _renderizar_pestana_si_pendiente). Los DataFrames/estado lógico
        # (_df_*_visible, paginación) se actualizan siempre, sin importar
        # esta bandera -- solo se difiere la construcción de widgets.
        self._clientes_pendiente_render = False
        self._unidades_pendiente_render = False

        # Orden alfabético de cada lista de tarjetas (botón "Ordenar" por
        # pestaña, reemplaza el clic en encabezado de columna que tenían las
        # tablas anteriores). True = ascendente (A-Z).
        self._clientes_orden_asc = True
        self._unidades_orden_asc = True
        # Columna por la que ordena Unidades ('Estado Comercial' o 'Estado Activación');
        # None = por Razón Social.
        self._unidades_orden_columna = None
        # Campo por el que ordena cada lista: 'nombre' (A-Z/Z-A, por
        # defecto) o 'unidades' (Más unidades/Menos unidades, 24-09-2026,
        # a pedido explícito). Solo aplica a Cliente y Flota -- Unidades
        # es una tabla por VIN, no tiene un conteo que ordenar.
        self._clientes_orden_campo = 'nombre'
        # CDB -> {'correo': ..., 'telefono': ...} del "Director de empresas"
        # (BBDD CLIENTES CM.xlsx, Power BI) -- dato de la EMPRESA, no de cada
        # contacto individual (esos ya traen su propio correo/teléfono desde
        # contactos.xlsx). Se muestra aparte, resaltado, en vez de pisar el
        # correo de cada contacto. Se carga de forma perezosa/asíncrona (ver
        # _load_pbi_director_empresa_async); hasta entonces queda vacío y
        # simplemente no se muestra la tarjeta de Director de empresa.
        self._pbi_director_empresa_por_cdb = {}
        self._pbi_director_empresa_thread = None
        # True mientras la lectura de BBDD CLIENTES CM está pedida y no ha llegado
        self._pbi_director_pendiente = False
        # Argumentos base (sin Dirección/Comuna) del último cliente
        # renderizado en "Información del cliente", para poder refrescar
        # solo esa caja cuando Power BI llega tarde (ver
        # _refrescar_info_cliente_pbi).
        self._info_cliente_base_args = None

        # Favoritos de contactos: mismo archivo compartido y misma lógica
        # (contactos_service) que usa contactos.py, para que marcar/desmarcar
        # un favorito acá se refleje también en el módulo Contactos.
        self.pinned_file = os.path.join(os.getcwd(), 'config', 'pinned_contacts.json')
        self.pinned_contacts = contactos_service.cargar_favoritos(self.pinned_file)

        # Actualizacion diferida por visibilidad: si data_ready llega mientras
        # este modulo no es el widget visible (QStackedWidget/QTabWidget lo
        # tiene oculto), no se reprocesa el DataFrame de inmediato -- solo se
        # marca dirty y se recalcula recien cuando el usuario vuelve a entrar
        # (ver MainWindow._trigger_load_data -> refresh_if_dirty).
        self._data_dirty = False

        # Guard de reentrancia de GeneralDataPrepThread (auditoria de
        # rendimiento, fase 4, 21-09-2026): _prep_thread guarda el worker
        # actualmente en vuelo (o None si todavia no se lanzo ninguno).
        # _prep_en_curso es la bandera que realmente gobierna el guard --
        # se pone en True justo antes de start() y en False al principio de
        # _on_prep_finished(); se usa una bandera propia en vez de
        # self._prep_thread.isRunning() porque QThread no garantiza que
        # isRunning() ya sea False en el instante exacto en que se procesa
        # la señal de finalización en el hilo principal (ventana de carrera
        # teorica entre "el hilo emitio la señal" y "Qt marco el hilo como
        # terminado"); una bandera de Python que nosotros mismos controlamos
        # es determinista sin depender de ese detalle interno.
        # _prep_pendiente es un dirty flag independiente de _data_dirty (ese
        # es por VISIBILIDAD; este es por WORKER OCUPADO -- pueden darse a la
        # vez y son condiciones distintas): si load_data() se llama mientras
        # _prep_en_curso es True, no se lanza un segundo worker, se marca
        # _prep_pendiente y _on_prep_finished vuelve a llamar load_data()
        # (con el snapshot mas reciente de DataManager) apenas el worker
        # actual termine -- asi un resultado viejo nunca puede pisar a uno
        # mas nuevo.
        self._prep_thread = None
        self._prep_en_curso = False
        self._prep_pendiente = False
        self._primera_carga_emitida = False

        # Buscador global de MainWindow (self.search_bar): MainWindow lo
        # detecta vía hasattr(current_widget, 'search_input') y le fija el
        # texto directamente (ver MainWindow._on_global_search), mismo patrón
        # que ComercialModule/ContactosModule/etc. Oculto porque el campo
        # visible es el de MainWindow, no uno propio de este módulo. Solo
        # afecta la caja izquierda -> Unidades (ver filter_table más abajo);
        # nunca toca la caja derecha (selección de cliente/CDB, KPIs,
        # Contactos), que sigue su propio ciclo de vida independiente.
        self.search_input = QLineEdit()
        self.search_input.hide()

        self._setup_ui()

        self.data_manager.data_ready.connect(self._on_data_ready)
        self.data_manager.load_error.connect(self._on_error)
        self.data_manager.contactos_ready.connect(self._on_contactos_ready)
        # Historial por VIN (caja derecha -> Unidades -> Historial): se
        # refresca solo con esta señal ligera (ver DataManager.set_logs_df),
        # sin pasar por data_ready/load_data (que reconstruye clientes/
        # flota/unidades completos y podría perder la selección actual).
        self.data_manager.logs_updated.connect(self._on_logs_updated)

        # Contactos y BBDD CLIENTES CM se lanzan recién tras la primera carga
        # (ver _iniciar_cargas_secundarias): en paralelo competían por el GIL
        # con el armado de tarjetas y congelaban la pantalla de carga.
        self._cargas_secundarias_iniciadas = False
        self.load_data()

    def _iniciar_cargas_secundarias(self):
        # Contactos se carga de forma perezosa (solo el módulo Contactos la
        # disparaba antes): sin esto, "Contactos encontrados" queda vacío
        # hasta que el usuario visita ese módulo al menos una vez.
        # Si ya se está leyendo (precarga de MainWindow), no se pide otra vuelta
        if self.data_manager.get_contactos_df().empty and getattr(self.data_manager, 'is_loading_contactos', False) is not True:
            self.data_manager.load_contactos_async()
        self._load_pbi_director_empresa_async()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), _tema_gestor.fondo(FONDO_GENERAL))
        p.end()

    def _al_cambiar_tema(self, *_):
        self.update()

    def _setup_ui(self):
        _tema_gestor.GestorTema.instancia().tema_cambiado.connect(self._al_cambiar_tema)
        self.setObjectName("moduloGeneral")
        # Fondo pintado (paintEvent) y sin hoja propia: así el cambio de tema no repolariza toda la pantalla
        self.setProperty(PROP_TRANSPARENTE_FORZADO, True)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(6)

        # ==========================================
        # ENCABEZADO (compacto: el título del módulo ahora vive en el
        # chip del header de main_window.py)
        # ==========================================
        # El encabezado de página de main_window se oculta para este módulo
        # (ver _update_module_chip): el título y las pestañas Cliente/Unidades
        # viven dentro de la caja izquierda (ver _setup_left_box), que lleva el
        # mismo marco que la derecha (23-10-2026); el borde azul de ambas cajas
        # se quitó el 28-10-2026 (a pedido de Javiera).
        boxes_layout = QHBoxLayout()
        boxes_layout.setSpacing(15)

        self.left_box = MarcoTema(SURFACE, BORDE_CAJA_GENERAL, 1, 17)
        self.right_box = MarcoTema(SURFACE, BORDE_CAJA_GENERAL, 1, 17)
        for caja in (self.left_box, self.right_box):
            caja.setObjectName("cajaGeneral")

        # Anchos acotados (07-10-2026, a pedido explícito) y política Ignored:
        # el ancho de cada caja lo fijan estos topes y no el texto que
        # contengan (antes un nombre largo ensanchaba la caja derecha).
        self.left_box.setMaximumWidth(ANCHO_MAX_CAJA_IZQUIERDA)
        self.left_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.right_box.setMaximumWidth(ANCHO_MAX_CAJA_DERECHA)
        self.right_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

        # Izquierda angosta (lista de una columna) / derecha más ancha (a pedido
        # de Javiera, 28-10-2026): antes 5:3, ahora 2:3.
        # Espacios con factor 0 a ambos lados: solo reciben lo que sobra cuando
        # las cajas llegan a su tope, y así el bloque queda centrado (20-10-2026)
        boxes_layout.addStretch(0)
        boxes_layout.addWidget(self.left_box, stretch=2)
        boxes_layout.addWidget(self.right_box, stretch=3)
        boxes_layout.addStretch(0)
        main_layout.addLayout(boxes_layout, stretch=1)

        self._setup_left_box()
        self._setup_right_box()

        # Se crean al final para quedar encima del contenido de cada caja
        self._esqueleto_izq = EsqueletoCarga(self._hoja_izquierda, 'grilla')
        self._esqueleto_der = EsqueletoCarga(self.right_box, 'ficha')

    def _esqueletos(self):
        # __dict__.get: tolera instancias creadas con __new__ en los tests
        return [e for e in (self.__dict__.get('_esqueleto_izq'), self.__dict__.get('_esqueleto_der')) if e is not None]

    DURACION_ANIMACION_BREVE_MS = 300

    def _animar_carga_breve(self, solo_izquierda=False):
        """Esqueleto corto al cambiar de pestaña o buscar. Si hay una carga
        real en curso ya hay esqueleto y no se toca."""
        if self.__dict__.get('_prep_en_curso'):
            return
        esqueletos = self._esqueletos()
        if not esqueletos:
            return
        if solo_izquierda:
            esqueletos = esqueletos[:1]
        for esqueleto in esqueletos:
            esqueleto.iniciar_ya(rapido=True)
        timer = self.__dict__.get('_timer_animacion_breve')
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._terminar_animacion_breve)
            self._timer_animacion_breve = timer
        self._esqueletos_breves = esqueletos
        timer.start(self.DURACION_ANIMACION_BREVE_MS)

    DURACION_ESQUELETO_DERECHA_MS = 35
    FUNDIDO_ESQUELETO_DERECHA_MS = 70

    def _portada_derecha_visible(self):
        """Portada azul de la ficha que se ve en la caja derecha (queda fuera del esqueleto)."""
        actual = self.right_stack.currentWidget()
        if actual is None:
            return None
        for portada in actual.findChildren(QFrame, "fichaPortada"):
            if portada.isVisible():
                return portada
        return None

    def _animar_esqueleto_derecha(self):
        """Esqueleto casi instantáneo sobre la caja derecha al elegir otro
        elemento o cambiar de pestaña en ella. La portada azul no se cubre."""
        if self.__dict__.get('_prep_en_curso'):
            return
        esqueleto = self.__dict__.get('_esqueleto_der')
        if esqueleto is None:
            return
        esqueleto.FUNDIDO_RAPIDO_MS = self.FUNDIDO_ESQUELETO_DERECHA_MS
        esqueleto.debajo_de = self._portada_derecha_visible
        esqueleto.fijar_forma('hoja')
        self.right_box.layout().activate()
        esqueleto.iniciar_ya(rapido=True)
        timer = self.__dict__.get('_timer_esqueleto_derecha')
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._terminar_esqueleto_derecha)
            self._timer_esqueleto_derecha = timer
        timer.start(self.DURACION_ESQUELETO_DERECHA_MS)

    def _terminar_esqueleto_derecha(self):
        if self.__dict__.get('_prep_en_curso'):
            return
        esqueleto = self.__dict__.get('_esqueleto_der')
        if esqueleto is not None:
            esqueleto.terminar()

    def _terminar_animacion_breve(self):
        if self.__dict__.get('_prep_en_curso'):
            return
        for esqueleto in self.__dict__.get('_esqueletos_breves', []):
            esqueleto.terminar()

    # ==========================================
    # CONTROLES SUPERIORES (fuera de las cajas)
    # ==========================================
    def _setup_top_controls(self, main_layout):
        barra = QFrame()
        barra.setObjectName("barraPestanasGeneral")
        barra.setStyleSheet(QSS_CONTENEDOR_PESTANAS_CLARO)
        controls_layout = QHBoxLayout(barra)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)

        self.btn_nav_flota = QPushButton("Flotas")
        self.btn_nav_cliente = QPushButton("Cliente")
        self.btn_nav_unidades = QPushButton("Contratos")
        # Orden visible: Flota, Cliente, Contratos. Cada botón abre la página de left_stack
        # de _VISTAS_NAV (Cliente 0 y Contratos 1 conservan su índice; Flota es la 2)
        self._nav_buttons = [self.btn_nav_flota, self.btn_nav_cliente, self.btn_nav_unidades]

        # Mismo estilo tipo pestaña que Ingreso y Conciliación / Comercial:
        # borde de color por estado (normal/seleccionada) y hover.
        nav_tab_style = QSS_PESTANAS_HOJA
        for btn, vista in zip(self._nav_buttons, self._VISTAS_NAV):
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(nav_tab_style)
            btn.clicked.connect(lambda checked, idx=vista: self._switch_left_view(idx))
            controls_layout.addWidget(btn)
        self.btn_nav_flota.setChecked(True)

        # Mismo botón/patrón que btn_advanced_filters en comercial.py (texto
        # " Filtros" + ícono, botón secundario estándar, sin tamaño fijo
        # cuadrado), reimplementado aquí en vez de importado para no tocar
        # comercial.py. Agrupado junto a Cliente/Flota/Unidades (a pedido
        # explícito), en vez de aislado al otro extremo de la fila.
        #
        # Único botón "Filtros" de este módulo: solo visible en la pestaña
        # "Unidades" (ver _switch_left_view). El filtro de Industria vivía
        # antes en un botón propio de Cliente; se movió acá junto a Razón
        # Social/Estado Activación a pedido explícito (15-09-2026), ya que
        # 'Industria/s' es visible como columna en Unidades, no en Cliente.
        self.btn_filtro_unidades = QPushButton(" Filtros")
        self.btn_filtro_unidades.setIcon(ThemeManager.icon('fa5s.filter', color=AZUL))
        self.btn_filtro_unidades.setCheckable(True)
        self.btn_filtro_unidades.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_sobre_azul(self.btn_filtro_unidades)
        self.btn_filtro_unidades.toggled.connect(self._toggle_filtro_unidades)
        self.btn_filtro_unidades.set_compacto = lambda compacto: (
            self.btn_filtro_unidades.setText("" if compacto else " Filtros"),
            self.btn_filtro_unidades.setToolTip("Filtros" if compacto else ""))
        self.btn_filtro_unidades.hide()
        controls_layout.addWidget(self.btn_filtro_unidades)

        # "+ Nuevo Cliente" / "Importar Excel Power BI" (alta de unidades)
        # quitados de General (25-09-2026, refactor: esa responsabilidad
        # quedó centralizada en Comercial -> pestaña "Unidad nueva", ver
        # ComercialModule._build_unidad_nueva_tab/_abrir_importar_powerbi en
        # comercial.py). General conserva solo consulta/ficha/historial de
        # clientes y unidades.
        controls_layout.addStretch()
        # Los controles de la lista de Cliente (aviso de flotas, cantidad y orden) se
        # agregan aquí, a la derecha, desde _build_cliente_view
        self._barra_nav_layout = controls_layout

        main_layout.addWidget(barra)

    # ==========================================
    # CAJA DERECHA: detalle del cliente seleccionado
    # ==========================================
    def _setup_right_box(self):
        layout = QVBoxLayout(self.right_box)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(10)

        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._build_cliente_vacio_view())     # index 0
        # index 1 (detalle de cliente: KPIs + pestañas Resumen/Unidades/
        # Contactos/Historial) es el subárbol más pesado del módulo y el
        # estado inicial SIEMPRE es el índice 0 ("selecciona un cliente");
        # se construye recién la primera vez que el usuario selecciona una
        # fila (ver _ensure_detalle_view_built, llamado desde
        # _show_cliente_detalle), no durante el primer render de la ventana.
        self._detalle_view_built = False
        self.right_stack.addWidget(QWidget())                            # index 1 (placeholder)
        self.right_stack.addWidget(self._build_flota_sin_cdb_view())     # index 2
        # index 3/4: contexto de VIN (caja izquierda -> Unidades), separado
        # del contexto de cliente (índices 0/1/2) -- ver _switch_left_view,
        # que decide cuál mostrar según la pestaña izquierda activa.
        self.right_stack.addWidget(self._build_vin_vacio_view())         # index 3
        self.right_stack.addWidget(self._build_vin_detalle_view())       # index 4
        # index 5/6: contexto de Flota (pestaña Flota, la que se abre primero)
        self.right_stack.addWidget(self._build_flota_vacio_view())       # index 5
        self.right_stack.addWidget(self._build_flota_detalle_view())     # index 6
        self.right_stack.setCurrentIndex(5)

        # El scroll ya NO envuelve toda la caja derecha (encabezado + KPIs +
        # pestañas Resumen/Unidades/Contactos quedaban desplazándose junto
        # con el contenido, a pedido explícito se corrige): ahora vive
        # únicamente alrededor de self.detalle_stack, dentro de
        # _build_cliente_detalle_view (ver self.detalle_scroll ahí), para
        # que solo el contenido de la pestaña activa se desplace y el resto
        # quede fijo.
        layout.addWidget(self.right_stack, stretch=1)

    def _ensure_detalle_view_built(self):
        """Construye el detalle de cliente (índice 1 de right_stack) la
        primera vez que hace falta, reemplazando el placeholder vacío que
        dejó _setup_right_box(). Reemplazo en el MISMO índice (remove +
        insert en la posición 1) para no correr el índice 2
        (_build_flota_sin_cdb_view), que ya existe desde el arranque."""
        if self._detalle_view_built:
            return
        placeholder = self.right_stack.widget(1)
        self.right_stack.removeWidget(placeholder)
        placeholder.deleteLater()
        self.right_stack.insertWidget(1, self._build_cliente_detalle_view())
        self._detalle_view_built = True
        if self.__dict__.get('_alto_portadas') is not None:
            self._sincronizar_alto_portadas()

    # ==========================================
    # CAJA IZQUIERDA: navegación Cliente / Flota / Unidades
    # ==========================================
    def _setup_left_box(self):
        layout = QVBoxLayout(self.left_box)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        hoja = MarcoTema(SURFACE, radio=16)
        hoja.setObjectName("hojaGeneral")
        lay_cont = QVBoxLayout(hoja)
        lay_cont.setContentsMargins(0, 0, 0, 0)
        lay_cont.setSpacing(0)

        portada = QFrame()
        portada.setObjectName("fichaPortada")
        portada.setStyleSheet(
            f"QFrame#fichaPortada {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {AZUL_HOVER}, stop:1 {AZUL}); "
            "border-top-left-radius: 16px; border-top-right-radius: 16px; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }"
            "QFrame#fichaPortada QLabel { background: transparent; border: none; }")
        lay_p = QVBoxLayout(portada)
        lay_p.setContentsMargins(16, 16, 16, 0)
        lay_p.setSpacing(2)

        lbl_titulo = QLabel("Clientes y Flota")
        lbl_titulo.setStyleSheet("color: white; font-size: 24px; font-weight: 800;")
        lbl_subtitulo = QLabel("Clientes, contratos y su estado en la flota.")
        lbl_subtitulo.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 13.5px;")
        lay_p.addWidget(lbl_titulo)
        # Con la caja angosta, el contador y las casillas de cada pestaña van a la derecha del subtítulo
        # (en la barra de pestañas ya no caben)
        lbl_subtitulo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._fila_subtitulo_layout = QHBoxLayout()
        self._fila_subtitulo_layout.setSpacing(8)
        self._fila_subtitulo_layout.addWidget(lbl_subtitulo, 1)
        # Recoge el espacio cuando el subtítulo se oculta, para que las casillas queden a la derecha
        self._fila_subtitulo_layout.addStretch(0)
        lay_p.addLayout(self._fila_subtitulo_layout)
        lay_p.addSpacing(8)
        self._setup_top_controls(lay_p)
        # Con la caja angosta los controles de la pestaña bajan a esta fila (ver _acomodar_portada_izquierda)
        self._fila_controles = QWidget()
        self._fila_controles.setStyleSheet("background: transparent;")
        self._fila_controles_layout = QHBoxLayout(self._fila_controles)
        self._fila_controles_layout.setContentsMargins(0, 6, 0, 0)
        self._fila_controles_layout.setSpacing(8)
        self._fila_controles_layout.addStretch()
        self._fila_controles.hide()
        lay_p.addWidget(self._fila_controles)
        self._lbl_subtitulo_izq = lbl_subtitulo
        lay_cont.addWidget(portada)
        self._portada_izq = portada
        portada.installEventFilter(self)
        self._modo_estrecho = 0

        self._hoja_izquierda = MarcoTema(SURFACE, radios=(0, 0, 16, 16))
        self._hoja_izquierda.setObjectName("hojaIzquierda")
        lay_hoja = QVBoxLayout(self._hoja_izquierda)
        lay_hoja.setContentsMargins(15, 15, 15, 15)
        lay_hoja.setSpacing(10)
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self._build_cliente_view())
        self.left_stack.addWidget(self._build_unidades_view())
        self.left_stack.addWidget(self._build_flota_view())
        # Se abre en Flota: los controles de Cliente quedan ocultos hasta entrar a esa pestaña
        self.left_stack.setCurrentIndex(2)
        self._controles_cliente.hide()
        self._extras_cliente.hide()
        self._controles_unidades.agregar_existente(self.btn_filtro_unidades)
        lay_hoja.addWidget(self.left_stack, stretch=1)
        lay_cont.addWidget(self._hoja_izquierda, stretch=1)
        layout.addWidget(hoja, stretch=1)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.__dict__.get('_alto_portadas_listo'):
            self._alto_portadas_listo = True
            QTimer.singleShot(0, self._sincronizar_alto_portadas)
        self._programar_prerender_pestanas(600)

    def _sincronizar_alto_portadas(self, recalcular=False):
        """La portada de la ficha de unidad (caja derecha) toma el alto de la portada izquierda para que
        el título, las pestañas y el inicio del contenido queden alineados entre las dos cajas."""
        izquierda = self.__dict__.get('_portada_izq')
        if izquierda is None:
            return
        try:
            alto = self.__dict__.get('_alto_portadas')
            if alto is None or recalcular:
                izquierda.setMinimumHeight(0)
                izquierda.setMaximumHeight(16777215)
                izquierda.layout().activate()
                izquierda.ensurePolished()
                alto = self._alto_portadas = izquierda.sizeHint().height()
            for portada in (izquierda, *self.__dict__.get('_portadas_unidad', [])):
                portada.setFixedHeight(alto)
        except RuntimeError:
            pass

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Type.Resize and objeto is self.__dict__.get('_portada_izq'):
            QTimer.singleShot(0, self._acomodar_portada_izquierda)
        return super().eventFilter(objeto, evento)

    def _acomodar_portada_izquierda(self):
        """Con la caja izquierda angosta (menú lateral abierto, pantalla pequeña o interfaz grande) las
        pestañas y los controles no caben en una línea: los controles bajan a su propia fila y el
        subtítulo se oculta si estorba a las casillas de la derecha."""
        portada = self.__dict__.get('_portada_izq')
        if portada is None or 'left_stack' not in self.__dict__:
            return
        try:
            indice = self.left_stack.currentIndex()
            grupos = {0: (self._controles_cliente, self._extras_cliente),
                      1: (self._controles_unidades, self._extras_unidades),
                      2: (self._controles_flota, self._extras_flota)}
            controles, extras = grupos[indice]
            disponible = portada.width() - 32
            if disponible <= 64:
                return
            espaciado = self._barra_nav_layout.spacing()

            def cabe(modo):
                """Modo 0: todo en una línea; 1: pestañas justas y controles cortos; 2: controles en otra fila."""
                estilo = QSS_PESTANAS_HOJA_JUSTAS if modo == 1 else QSS_PESTANAS_HOJA
                for boton in self._nav_buttons:
                    boton.setStyleSheet(estilo)
                    boton.ensurePolished()
                for grupo, _extras in grupos.values():
                    grupo.compactar(modo == 1)
                ancho_tabs = sum(b.sizeHint().width() for b in self._nav_buttons) + espaciado * (len(self._nav_buttons) - 1)
                return ancho_tabs + espaciado + controles.ancho_necesario() <= disponible

            modo = 0 if cabe(0) else (1 if cabe(1) else 2)
            if modo == 2:
                cabe(0)
            ancho_subtitulo = self._lbl_subtitulo_izq.fontMetrics().horizontalAdvance(self._lbl_subtitulo_izq.text())
            sin_subtitulo = ancho_subtitulo + extras.ancho_necesario() + 16 > disponible
            if modo == self._modo_estrecho and sin_subtitulo != self._lbl_subtitulo_izq.isVisibleTo(portada):
                return
            hubo_fila = self._modo_estrecho == 2
            self._modo_estrecho = modo
            portada.setUpdatesEnabled(False)
            destino = self._fila_controles_layout if modo == 2 else self._barra_nav_layout
            for grupo, _extras in grupos.values():
                grupo.mover_a(destino)
            self._fila_controles.setVisible(modo == 2)
            self._lbl_subtitulo_izq.setVisible(not sin_subtitulo)
            self._fila_subtitulo_layout.setStretch(1, 1 if sin_subtitulo else 0)
            if hubo_fila != (modo == 2) or self.__dict__.get('_alto_portadas') is None:
                self._sincronizar_alto_portadas(recalcular=True)
            portada.setUpdatesEnabled(True)
        except RuntimeError:
            pass

    def _switch_left_view(self, index):
        cambio = self.left_stack.currentIndex() != index
        for vista, btn in zip(self._VISTAS_NAV, self._nav_buttons):
            btn.setChecked(vista == index)
        self.left_stack.setCurrentIndex(index)
        esqueleto = self.__dict__.get('_esqueleto_izq')
        if esqueleto is not None:
            esqueleto.fijar_forma('grilla_contratos' if index == 1 else 'grilla')
        # Único botón de filtros del módulo (Razón Social/Estado Activación/
        # Industria): solo aplica a Unidades, se oculta en las demás pestañas
        # en vez de dejarlo inerte. Se cambian con el repintado suspendido y el
        # layout ya calculado para que no se vean botones a medio acomodar.
        portada = self.__dict__.get('_portada_izq')
        if portada is not None:
            portada.setUpdatesEnabled(False)
        self.btn_filtro_unidades.setVisible(index == 1)
        self._controles_cliente.setVisible(index == 0)
        self._controles_unidades.setVisible(index == 1)
        self._extras_cliente.setVisible(index == 0)
        self._extras_unidades.setVisible(index == 1)
        self._actualizar_aviso_filtro_vins()
        self._controles_flota.setVisible(index == 2)
        self._extras_flota.setVisible(index == 2)
        self._actualizar_aviso_filtro_flotas()
        if portada is not None:
            self._barra_nav_layout.invalidate()
            self._barra_nav_layout.activate()
            portada.layout().invalidate()
            portada.layout().activate()
            portada.setUpdatesEnabled(True)
            portada.repaint()
            self._acomodar_portada_izquierda()
        if cambio:
            self._animar_carga_breve()
        self._renderizar_pestana_si_pendiente(index)

    def _programar_prerender_pestanas(self, demora_ms=400):
        timer = self.__dict__.get('_timer_prerender')
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._prerenderizar_pestana_oculta)
            self._timer_prerender = timer
        timer.start(demora_ms)

    def _prerenderizar_pestana_oculta(self):
        """Con la pantalla ya cargada y en reposo, pinta de a una las pestañas que quedaron pendientes
        (primera página de tarjetas) para que el primer cambio a ellas no tenga que construirlas."""
        if self.__dict__.get('_prep_en_curso') or not self.isVisible():
            return
        actual = self.left_stack.currentIndex()
        pestanas = ((1, '_unidades_pendiente_render', self._pintar_pagina_unidades),
                    (2, '_flotas_pendiente_render', self._pintar_pagina_flotas),
                    (0, '_clientes_pendiente_render', self._pintar_pagina_clientes))
        try:
            for indice, bandera, pintar in pestanas:
                if indice != actual and getattr(self, bandera):
                    pintar()
                    setattr(self, bandera, False)
                    if indice in (0, 1):
                        self.__dict__.setdefault('_sin_sincronizar_seleccion', set()).add(indice)
                    self._programar_prerender_pestanas(40)
                    return
        except RuntimeError:
            pass

    def _renderizar_pestana_si_pendiente(self, index):
        """Pinta las tarjetas de la pestaña recién mostrada solo si quedó
        pendiente (ver _render_clientes_cards/_render_flota_cards/
        _render_unidades_cards): mientras esa pestaña no era visible,
        filter_table()/_on_prep_finished() actualizaron el DataFrame/página
        pero no construyeron widgets. Si no hay nada pendiente, no hace
        nada -- volver a una pestaña sin cambios no debe reconstruir sus
        tarjetas (Fase 5, 21-09-2026)."""
        sincronizo_unidades = False
        sin_sincronizar = self.__dict__.setdefault('_sin_sincronizar_seleccion', set())
        if index == 0 and (self._clientes_pendiente_render or 0 in sin_sincronizar):
            if self._clientes_pendiente_render:
                self._pintar_pagina_clientes()
                self._clientes_pendiente_render = False
            sin_sincronizar.discard(0)
            self._sincronizar_seleccion_cliente(self._df_clientes_visible)
        elif index == 1 and (self._unidades_pendiente_render or 1 in sin_sincronizar):
            if self._unidades_pendiente_render:
                self._pintar_pagina_unidades()
                self._unidades_pendiente_render = False
            sin_sincronizar.discard(1)
            self._sincronizar_seleccion_vin()
            sincronizo_unidades = True
        elif index == 2 and self._flotas_pendiente_render:
            self._pintar_pagina_flotas()
            self._flotas_pendiente_render = False

        if index == 2:
            # Flota: la caja derecha muestra la flota seleccionada, o la invitación a elegir una
            fila = self._buscar_flota_por_clave(self._selected_flota_key)
            if fila is not None:
                self._show_flota_detalle(fila)
            else:
                self._show_flota_vacio()
        elif index == 1:
            # Unidades: la caja derecha pasa a mostrar el contexto de VIN
            # (ficha + historial de la unidad seleccionada, o el estado
            # vacío si todavía no se eligió ninguna). Si la sincronización de
            # arriba ya la armó, no se repite.
            if sincronizo_unidades:
                pass
            elif self._vin_seleccionado:
                self._show_vin_detalle(self._vin_seleccionado)
            else:
                self._show_vin_vacio()
        elif self.right_stack.currentIndex() in (3, 4, 5, 6):
            # Se sale de Unidades o de Flota y la caja derecha estaba mostrando el
            # contexto de VIN o de flota: vuelve a reflejar la última selección de
            # cliente (o el estado vacío original) en vez de dejar la ficha
            # de VIN visible fuera de su pestaña.
            cliente_row = self._buscar_cliente_por_clave(self._selected_cliente_key)
            if cliente_row is not None:
                self._show_cliente_detalle(cliente_row)
            else:
                self._show_cliente_vacio()

    # ==========================================
    # PESTAÑA "CONTACTOS" (caja derecha, detalle de cliente): mismos
    # contactos que la caja "Contactos encontrados" del Resumen (mismo cruce
    # por CDB, mismo correo desde Power BI), pero sin el límite de alto de
    # esa caja -- este es el destino del botón "Ver todos". Se puebla en
    # _populate_contactos_encontrados(), que llena ambos contenedores.
    # ==========================================
    def _build_detalle_contactos_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        self.lbl_detalle_contactos_titulo = QLabel("CONTACTOS DEL CLIENTE")
        self.lbl_detalle_contactos_titulo.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        header_row.addWidget(self.lbl_detalle_contactos_titulo)
        header_row.addStretch()

        # Movido desde la caja "Contactos encontrados" del Resumen (a pedido
        # explícito): arriba de la pestaña, fuera del QScrollArea de abajo,
        # para que quede fijo al hacer scroll en vez de desplazarse con las
        # tarjetas.
        self.btn_agregar_contacto = QPushButton(" + Agregar contacto")
        self.btn_agregar_contacto.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_agregar_contacto.setStyleSheet(f"""
            QPushButton {{ background-color: {AZUL}; color: white; border: none;
                          border-radius: 8px; padding: 6px 12px; font-weight: bold; font-size: 11px; }}
            QPushButton:hover {{ background-color: {AZUL_HOVER}; }}
            QPushButton:disabled {{ background-color: {BORDER}; color: {TEXT_MUTED}; }}
        """)
        self.btn_agregar_contacto.clicked.connect(self._handle_agregar_contacto)
        header_row.addWidget(self.btn_agregar_contacto)
        layout.addLayout(header_row)

        contactos_tab_scroll = QScrollArea()
        contactos_tab_scroll.setWidgetResizable(True)
        contactos_tab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        contactos_tab_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        contactos_tab_scroll.viewport().setStyleSheet("background: transparent;")

        contactos_tab_container = QWidget()
        contactos_tab_container.setStyleSheet("background: transparent;")
        self.contactos_tab_layout = QVBoxLayout(contactos_tab_container)
        self.contactos_tab_layout.setContentsMargins(0, 2, 4, 2)
        self.contactos_tab_layout.setSpacing(8)
        contactos_tab_scroll.setWidget(contactos_tab_container)

        layout.addWidget(contactos_tab_scroll, stretch=1)
        return widget

    # ==========================================
    # PESTAÑA "DUPLICADOS" (23-09-2026, a pedido explícito): lista los otros
    # clientes (Razón Social) que comparten el mismo RUT+CDB que el
    # actualmente seleccionado -- ver _calcular_claves_duplicadas_rut_cdb /
    # _populate_duplicados_detalle. Solo se muestra cuando corresponde (ver
    # btn_detalle_duplicados.setVisible en _populate_duplicados_detalle).
    # ==========================================
    def _build_detalle_duplicados_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        aviso = QFrame()
        aviso.setObjectName("avisoRazones")
        aviso.setStyleSheet("QFrame#avisoRazones { background-color: #FFF7ED; border: 1px solid #FED7AA; border-radius: 10px; }"
                            "QFrame#avisoRazones QLabel { background: transparent; border: none; }")
        aviso_layout = QVBoxLayout(aviso)
        aviso_layout.setContentsMargins(14, 10, 14, 10)
        aviso_layout.setSpacing(2)
        lbl_aviso_titulo = QLabel("Este RUT tiene más de una razón social")
        lbl_aviso_titulo.setStyleSheet("color: #9A3412; font-size: 12px; font-weight: bold;")
        lbl_aviso_texto = QLabel("Puede ser el mismo cliente escrito de formas distintas. "
                                 "La principal es la que tiene más unidades.")
        lbl_aviso_texto.setWordWrap(True)
        lbl_aviso_texto.setStyleSheet("color: #9A3412; font-size: 11px;")
        aviso_layout.addWidget(lbl_aviso_titulo)
        aviso_layout.addWidget(lbl_aviso_texto)
        layout.addWidget(aviso)

        # Unificación manual (23-09-2026, a pedido explícito): conserva la
        # Razón Social con más unidades del grupo (mismo criterio que
        # la antigua sincronización RM_JAVI aplicaba automáticamente,
        # ver comercial_services.detectar_grupos_razon_social_duplicada) y
        # renombra las demás a esa misma. Reescribe PruebasFM de verdad, por
        # eso pide confirmación antes de ejecutar.
        self.btn_unificar_razon_social = QPushButton("Unificar en una sola razón social")
        self.btn_unificar_razon_social.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unificar_razon_social.setStyleSheet(f"""
            QPushButton {{ background-color: {AZUL}; color: white; border: 1px solid {AZUL};
                          border-radius: 10px; padding: 8px 14px; font-weight: bold; font-size: 11px; }}
            QPushButton:hover {{ background-color: {AZUL_HOVER}; border: 1px solid {AZUL_HOVER}; }}
            QPushButton:disabled {{ background-color: #C5CCDA; border: 1px solid #C5CCDA; color: #F3F5F9; }}
        """)
        self.btn_unificar_razon_social.clicked.connect(self._on_unificar_razon_social_clicked)
        layout.addWidget(self.btn_unificar_razon_social)

        duplicados_scroll = QScrollArea()
        duplicados_scroll.setWidgetResizable(True)
        duplicados_scroll.setFrameShape(QFrame.Shape.NoFrame)
        duplicados_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        duplicados_scroll.viewport().setStyleSheet("background: transparent;")

        duplicados_container = QWidget()
        duplicados_container.setStyleSheet("background: transparent;")
        self.duplicados_tab_layout = QVBoxLayout(duplicados_container)
        self.duplicados_tab_layout.setContentsMargins(0, 2, 0, 2)
        self.duplicados_tab_layout.setSpacing(4)
        duplicados_scroll.setWidget(duplicados_container)

        layout.addWidget(duplicados_scroll, stretch=1)
        return widget

    def _razones_del_cliente(self, clave):
        """[(razón social, unidades)] de un cliente, de mayor a menor."""
        if self.df_comercial_raw.empty or '_clave_cliente' not in self.df_comercial_raw.columns:
            return []
        filas = self.df_comercial_raw[self.df_comercial_raw['_clave_cliente'] == clave]
        conteo = filas[COL_RAZON_SOCIAL].astype(str).str.strip().value_counts()
        return [(r, int(n)) for r, n in conteo.items()]

    def _unidades_por_razon(self, clave):
        """{razón social: [(VIN, chasis, estado de activación, estado comercial)]}
        de las unidades de un cliente."""
        df = self.df_comercial_raw
        if df.empty or '_clave_cliente' not in df.columns or COL_VIN not in df.columns:
            return {}
        filas = df[df['_clave_cliente'] == clave]

        def texto(col):
            return filas[col].astype(str).str.strip() if col in filas.columns else pd.Series('-', index=filas.index)

        tabla = pd.DataFrame({'razon': texto(COL_RAZON_SOCIAL), 'vin': texto(COL_VIN), 'chasis': texto(COL_CHASIS),
                              'act': texto(COL_ESTADO_ACTIVACION), 'com': texto(COL_ESTADO_COMERCIAL)})
        resultado = {}
        for razon, grupo in tabla.groupby('razon', sort=False):
            resultado[razon] = list(zip(grupo['vin'], grupo['chasis'], grupo['act'], grupo['com']))
        return resultado

    def _populate_duplicados_detalle(self, clave):
        """Puebla la pestaña Duplicados con las razones sociales que tiene el
        cliente seleccionado (mismo RUT) y muestra/oculta btn_detalle_duplicados
        según corresponda. Se llama desde _show_cliente_detalle."""
        layout = self.duplicados_tab_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        hay_duplicados = clave in self._clientes_con_varias_razones
        self.btn_detalle_duplicados.setVisible(hay_duplicados)
        # None cuando no hay duplicados, para que el botón nunca actúe sobre
        # un cliente obsoleto.
        self._grupo_duplicados_actual = clave if hay_duplicados else None
        if not hay_duplicados:
            # Si el usuario estaba viendo esta pestaña y el nuevo cliente ya
            # no tiene duplicados, vuelve a Resumen.
            if self.detalle_stack.currentIndex() == 4:
                self._switch_detalle_view(0)
            layout.addStretch()
            return

        razones = self._razones_del_cliente(clave)
        self.btn_detalle_duplicados.setText(f"Razones ({len(razones)})")
        unidades_por_razon = self._unidades_por_razon(clave)
        for i, (razon, unidades) in enumerate(razones):
            layout.addWidget(GeneralDuplicadoCard(razon, unidades, principal=(i == 0),
                                                  unidades=unidades_por_razon.get(razon, []),
                                                  al_abrir_unidad=self._abrir_unidad_en_pestana_unidades))
        layout.addStretch()

    def _seleccionar_cliente_por_clave(self, clave):
        """Navega al cliente indicado: actualiza la caja derecha siempre, y
        la tarjeta resaltada de la caja izquierda si está en la lista
        visible (mismo mecanismo que _on_cliente_card_clicked)."""
        df_v = self._df_clientes_visible
        if 'Clave' in df_v.columns:
            posiciones = (df_v['Clave'].astype(str) == str(clave)).to_numpy().nonzero()[0]
            if len(posiciones):
                self._on_cliente_card_clicked(int(posiciones[0]))
                return

        # El cliente no está en la lista filtrada (ej. el buscador lo
        # excluye): se actualiza igual la caja derecha.
        fila = self._buscar_cliente_por_clave(clave)
        if fila is not None:
            self._show_cliente_detalle(fila)

    # ==========================================
    # UNIFICACIÓN MANUAL DE RAZÓN SOCIAL DUPLICADA (23-09-2026, a pedido
    # explícito): botón "Unificar en una sola Razón Social" de la pestaña
    # Duplicados. Misma lógica de detección/ganadora que aplica
    # automáticamente la antigua sincronización con RM_JAVI
    # (comercial_services.detectar_grupos_razon_social_duplicada), pero
    # acotada al grupo (RUT, CDB) que el usuario está viendo y con
    # confirmación explícita antes de escribir.
    # ==========================================
    def _on_unificar_razon_social_clicked(self):
        clave = self._grupo_duplicados_actual
        if not clave or self.df_comercial_raw.empty:
            return

        razones = self._razones_del_cliente(clave)
        if len(razones) < 2:
            QMessageBox.information(self, "Nada que unificar",
                "Este RUT tiene una sola Razón Social en este momento.")
            return

        ganadora = razones[0][0]
        perdedoras = [r for r, _ in razones[1:]]
        detalle_perdedoras = "\n".join(f"  • \"{r}\" ({n} unidad(es))" for r, n in razones[1:])
        mensaje = (
            f"Se va a unificar este cliente en una sola Razón Social:\n\n"
            f"Se conserva: \"{ganadora}\" ({razones[0][1]} unidad(es), la de más unidades)\n\n"
            f"Se renombrarán a esa misma Razón Social:\n{detalle_perdedoras}\n\n"
            f"Esto modifica PruebasFM de verdad (con copia de seguridad previa, como cualquier guardado). ¿Confirmar?"
        )
        respuesta = QMessageBox.question(self, "Unificar Razón Social", mensaje,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        df_grupo = self.df_comercial_raw[self.df_comercial_raw['_clave_cliente'] == clave]
        filas_a_cambiar = df_grupo[df_grupo[COL_RAZON_SOCIAL].astype(str).str.strip().isin(perdedoras)]
        changes_dict = {
            str(vin): {'VIN': vin, 'cambios': {'RAZÓN SOCIAL': ganadora}}
            for vin in filas_a_cambiar['VIN']
        }
        if not changes_dict:
            return
        comercial_services.agregar_id_a_cambios(changes_dict, self.df_comercial_raw)

        self.btn_unificar_razon_social.setEnabled(False)
        self._unificar_razon_social_thread = SaveExcelThread(self.writer, changes_dict, module_name="Vista General (Unificación de duplicados)")
        self._unificar_razon_social_thread.finished_signal.connect(
            lambda success: self._on_unificar_razon_social_finished(success, changes_dict, ganadora)
        )
        self._unificar_razon_social_thread.logs_actualizados_signal.connect(self.data_manager.set_logs_df)
        self._unificar_razon_social_thread.start()

    def _on_unificar_razon_social_finished(self, success, changes_dict, ganadora):
        self.btn_unificar_razon_social.setEnabled(True)
        if not success:
            QMessageBox.critical(self, "Error", "No se pudo guardar la unificación de Razón Social en PruebasFM.")
            return

        dm = self.data_manager
        if not dm.df_master.empty:
            # aplicar_cambios_pendientes compara la llave tal cual contra
            # VIN ya normalizado (mayúsculas/sin espacios) del propio
            # df_master -- la llave debe venir normalizada igual (ver su
            # docstring), a diferencia de 'VIN' dentro de 'cambios' (usado
            # por ExcelWriter.update_cells más arriba), que no lo requiere.
            pending = {
                str(data['VIN']).strip().upper(): {'cambios': data['cambios'], 'ID': data.get('ID')}
                for data in changes_dict.values()
            }
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, pending)
            dm.data_ready.emit()

    @staticmethod
    def _cdbs_flota_de_unidades(df_unidades):
        """CDB flota distintos de las unidades de un cliente, en orden de aparición."""
        cdbs = []
        if COL_CDB_FLOTA in df_unidades.columns:
            for valor in df_unidades[COL_CDB_FLOTA].astype(str).str.strip():
                valor = valor[:-2] if valor.endswith('.0') else valor
                if valor.upper() not in ('', '-', 'NAN', 'NONE', '<NA>', 'NO ENCONTRADO') and valor not in cdbs:
                    cdbs.append(valor)
        return cdbs

    def _pintar_chip_cdb_flota(self, df_unidades):
        """Chip copiable con el CDB flota del cliente; si sus unidades tienen
        varios, muestra el primero y copia todos separados por coma."""
        cdbs = self._cdbs_flota_de_unidades(df_unidades)
        chip = self.lbl_detalle_cdb_flota
        if not cdbs:
            chip.set_value("CDB Flota", "-")
            chip.setToolTip("Este cliente no tiene CDB flota")
        elif len(cdbs) == 1:
            chip.set_value("CDB Flota", cdbs[0])
        else:
            chip.set_value("CDB Flota", ", ".join(cdbs))
            chip.setToolTip("Clic para copiar todos:\n" + "\n".join(cdbs))

    @_con_transicion_derecha
    def _show_cliente_vacio(self):
        self._clave_detalle_mostrada = None
        self._selected_cdb = None
        self._selected_cdbs_flota = []
        self._selected_cliente_key = None
        if hasattr(self, 'tabla_cliente_unidades'):
            self._cliente_df_unidades = pd.DataFrame()
            self._cliente_unidades_construidas = False
        if hasattr(self, 'flotas_detalle_layout'):
            self._pintar_flotas_detalle([])
        if hasattr(self, 'contactos_encontrados_layout'):
            df_vacio = pd.DataFrame(columns=['CDB', 'Nombre', 'Apellidos', 'Número móvil'])
            self.lbl_ver_todos_contactos.setToolTip("Ver todos (0)")
            self._fijar_conteo_contactos(self._btn_conteo_directores, 0)
            self._fijar_conteo_contactos(self._btn_conteo_administradores, 0)
            self.btn_agregar_admin_resumen.hide()
            self.lbl_detalle_contactos_titulo.setText("CONTACTOS DEL CLIENTE (0)")
            self._populate_contact_cards(self.contactos_encontrados_layout, df_vacio, "")
            self._populate_contact_cards(self.contactos_tab_layout, df_vacio, "")
        self.right_stack.setCurrentIndex(0)

    @_con_transicion_derecha
    def _show_cliente_detalle(self, cliente_row):
        self._ensure_detalle_view_built()
        razon_social = str(cliente_row['Razón Social'])
        self._razon_detalle_actual = razon_social
        self._clave_detalle_mostrada = self._clave_cliente(cliente_row)
        rut = cliente_row['RUT']
        industria = cliente_row['Industria/s']
        cdb = cliente_row['CDB']

        self.lbl_detalle_title.set_texto(razon_social)
        self.lbl_detalle_industria.set_value("Industria", industria)
        self.lbl_detalle_rut.set_value("RUT", rut)
        self.lbl_detalle_cdb.set_value("CDB Comercial", cdb)

        clave = self._clave_cliente(cliente_row)
        if '_clave_cliente' in self.df_comercial_raw.columns:
            df_unidades = self.df_comercial_raw[self.df_comercial_raw['_clave_cliente'] == clave]
        else:
            df_unidades = pd.DataFrame()

        total_unidades = len(df_unidades)
        self._pintar_chip_cdb_flota(df_unidades)

        if total_unidades > 0 and COL_ESTADO_ACTIVACION in df_unidades.columns:
            conectadas = int((df_unidades[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper() == ESTADO_ACTIVACION_CONECTADO).sum())
        else:
            conectadas = 0
        civ_count, sz_count = contar_civ_sz(df_unidades)
        self.bloque_resumen_cliente.actualizar(total_unidades, conectadas, civ_count, sz_count)

        flotas = sorted(n for n, _ in self._flotas_de_unidades(df_unidades))
        # Una sola flota: su nombre; varias: solo el conteo (la lista completa
        # queda en el tooltip); ninguna: aviso. Los "-" no cuentan.
        if not flotas:
            flotas_txt = "Sin flota asignada"
        elif len(flotas) == 1:
            flotas_txt = flotas[0]
        else:
            flotas_txt = f"{len(flotas)} flotas"
        self._info_cliente_flotas_tooltip = "\n".join(flotas) if len(flotas) > 1 else (flotas[0] if flotas else "")

        ejecutivo = ""
        if COL_EJECUTIVO in df_unidades.columns:
            ejecutivos_validos = [str(e).strip() for e in df_unidades[COL_EJECUTIVO].dropna().unique() if str(e).strip()]
            ejecutivo = ejecutivos_validos[0] if ejecutivos_validos else ""

        director_empresa = self._pbi_director_empresa_por_cdb.get(str(cdb).strip(), {})
        direccion = director_empresa.get('direccion', '')
        comuna = director_empresa.get('comuna', '')

        # Guardado para poder re-renderizar Dirección/Comuna si Power BI
        # (async, ver _load_pbi_director_empresa_async) termina de cargar
        # DESPUÉS de que el usuario ya seleccionó este cliente -- mismo caso
        # que ya resolvía _on_pbi_director_empresa_loaded para "Contactos
        # encontrados", ver _refrescar_info_cliente_pbi.
        self._info_cliente_base_args = (razon_social, rut, cdb, industria, ejecutivo, total_unidades, flotas_txt)
        self._render_info_cliente(*self._info_cliente_base_args, direccion=direccion, comuna=comuna)
        self._selected_cdb = cdb
        self._selected_cdbs_flota = self._cdbs_flota_de_unidades(df_unidades)
        self._selected_cliente_key = clave
        self._populate_contactos_encontrados(cdb)
        self._populate_unidades_detalle(self._selected_cliente_key)
        self._pintar_flotas_detalle(self._flotas_de_unidades(df_unidades), self._cdb_por_flota(df_unidades))
        self._populate_duplicados_detalle(self._selected_cliente_key)

        self.right_stack.setCurrentIndex(1)
        # Al cambiar de cliente se mantiene la pestaña que se estaba viendo (Razones vuelve a Resumen si ya no aplica)
        self._switch_detalle_view(self.detalle_stack.currentIndex())

    def _filtrar_contactos_por_cdb(self, df_contactos, cdb):
        """Razón Social seleccionada -> CDB -> Contactos asociados (caja
        derecha, apartado Contactos). Devuelve TODOS los contactos de ese
        CDB (sin limitar cantidad ni elegir uno solo) y ninguno de otro CDB.
        Función pura (no usa self.*)."""
        if df_contactos.empty or 'CDB' not in df_contactos.columns:
            return df_contactos.iloc[0:0].copy()

        # `cdb` puede ser un código o una lista (cliente con varios CDB flota)
        codigos = [cdb] if isinstance(cdb, str) else list(cdb)
        validos = {str(c).strip() for c in codigos
                   if str(c).strip().lower() not in ('', '-', 'nan', 'none', '<na>')}
        if not validos:
            return df_contactos.iloc[0:0].copy()

        return df_contactos[df_contactos['CDB'].astype(str).str.strip().isin(validos)]

    @staticmethod
    def _crear_aviso_cargando_directores():
        from src.ui.compartido.guardado_overlay import _Spinner
        aviso = QFrame()
        aviso.setStyleSheet(f"QFrame {{ background: transparent; border: none; }} QLabel {{ color: {TEXT_MUTED}; font-size: 12px; }}")
        fila = QHBoxLayout(aviso)
        fila.setContentsMargins(0, 6, 0, 6)
        fila.setSpacing(10)
        fila.addWidget(_Spinner(aviso, tamano=22))
        fila.addWidget(QLabel("Cargando directores, espere…"), 1)
        return aviso

    def _populate_contact_cards(self, layout, encontrados, director_empresa=None):
        """Llena `layout` con una tarjeta por contacto (_create_contacto_card),
        cada una con su PROPIO Nombre + Apellido | Correo | Número móvil
        desde contactos.xlsx (no se pisa con ningún dato de Power BI). Si
        `director_empresa` trae correo y/o teléfono (BBDD CLIENTES CM.xlsx,
        Power BI), se antepone una tarjeta aparte y resaltada para ese dato
        de la EMPRESA (_create_director_empresa_card) -- distinto de los
        contactos individuales. Usado tanto por la caja "Contactos
        encontrados" del Resumen como por la pestaña "Contactos" completa
        (mismos datos, dos contenedores distintos porque un QWidget no
        puede vivir en dos layouts a la vez)."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if getattr(self, '_pbi_director_pendiente', False):
            layout.addWidget(self._crear_aviso_cargando_directores())

        if director_empresa and (director_empresa.get('correo') or director_empresa.get('telefono')):
            layout.addWidget(self._create_director_empresa_card(
                director_empresa.get('correo', ''), director_empresa.get('telefono', ''),
            ))

        if encontrados.empty:
            lbl_vacio = QLabel("No se encontraron contactos para este CDB flota.")
            lbl_vacio.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 8px 0;")
            lbl_vacio.setWordWrap(True)
            layout.addWidget(lbl_vacio)
        else:
            # Favoritos primero (mismo criterio que contactos.py), luego por
            # ID ascendente.
            if 'ID' in encontrados.columns:
                encontrados = contactos_service.ordenar_por_favoritos_e_id(encontrados, self.pinned_contacts)
            for _, fila in encontrados.iterrows():
                contact_id = contactos_service.normalizar_id_contacto(fila.get('ID', '')) or None
                tarjeta = self._create_contacto_card(
                    str(fila.get('Nombre', '')).strip(),
                    str(fila.get('Apellidos', '')).strip(),
                    str(fila.get('Correo electrónico', '')).strip(),
                    str(fila.get('Número móvil', '')).strip(),
                    contact_id=contact_id,
                )
                layout.addWidget(tarjeta)

        layout.addStretch()

    def _populate_contactos_encontrados(self, cdb):
        df_contactos = self.data_manager.get_contactos_df()
        cdb_str = str(cdb).strip()
        # Los contactos se cruzan por CDB flota; el director de empresa y la
        # dirección (Power BI) siguen por el CDB comercial.
        encontrados = self._filtrar_contactos_por_cdb(df_contactos, getattr(self, '_selected_cdbs_flota', []))

        self.lbl_ver_todos_contactos.setToolTip(f"Ver todos ({len(encontrados)})")
        self.lbl_detalle_contactos_titulo.setText(f"CONTACTOS DEL CLIENTE ({len(encontrados)})")

        director_empresa = self._pbi_director_empresa_por_cdb.get(cdb_str)
        hay_director = bool(director_empresa and (director_empresa.get('correo') or director_empresa.get('telefono')))
        self._fijar_conteo_contactos(self._btn_conteo_directores, 1 if hay_director else 0)
        self._fijar_conteo_contactos(self._btn_conteo_administradores, len(encontrados))
        self.btn_agregar_admin_resumen.setVisible(len(encontrados) == 0)

        self._populate_contact_cards(self.contactos_encontrados_layout, encontrados, director_empresa)
        self._populate_contact_cards(self.contactos_tab_layout, encontrados, director_empresa)

    # ==========================================
    # ALTA DE CONTACTO (Ficha de cliente -> pestaña Contactos -> "Agregar
    # contacto"): mismo ContactosAddDialog, AddContactoThread,
    # contactos_service.generar_nuevo_id_contacto y ExcelWriter.add_new_row
    # que ya usa ContactosModule (contactos.py). Un contacto se relaciona
    # con la empresa por CDB, nunca por VIN (ver conversación con el
    # usuario, Fase 4) -- cdb_prefill/flota_prefill usan el CDB y la Razón
    # Social del cliente actualmente seleccionado. Se permiten
    # explícitamente contactos duplicados (mismo correo/nombre en otra
    # empresa): decisión de negocio confirmada, no se agrega ninguna
    # validación nueva de duplicados ni de formato.
    # ==========================================
    def _handle_agregar_contacto(self):
        if self._selected_cliente_key is None:
            return
        cliente_row = self._buscar_cliente_por_clave(self._selected_cliente_key)
        razon_social = str(cliente_row['Razón Social']) if cliente_row is not None else ''
        cdb_flota = self._selected_cdbs_flota[0] if self._selected_cdbs_flota else None

        dialog = ContactosAddDialog(self, cdb_prefill=cdb_flota, flota_prefill=razon_social)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_data = dialog.get_data()
        new_data['ID'] = contactos_service.generar_nuevo_id_contacto(self.data_manager.get_contactos_df())

        self.btn_agregar_contacto.setEnabled(False)
        self._add_contacto_thread = AddContactoThread(self.writer, new_data)
        self._add_contacto_thread.finished_signal.connect(self._on_agregar_contacto_finished)
        self._add_contacto_thread.start()

    def _on_agregar_contacto_finished(self, success, new_data):
        self.btn_agregar_contacto.setEnabled(True)
        if not success:
            QMessageBox.warning(self, "Error", "No se pudo agregar el contacto. Verifica si contactos.xlsx está abierto.")
            return
        # Recarga contactos.xlsx desde disco (mismo mecanismo que
        # ContactosModule.load_data): al terminar emite contactos_ready, ya
        # conectado a _on_contactos_ready, que repuebla la pestaña Contactos
        # del cliente activo -- no se duplica ese refresco aquí.
        self.data_manager.load_contactos_async()

    # Alta de registro (ComercialAgregarDialog -> AddRowThread) e importación
    # Power BI, ambas movidas a Comercial -> pestaña "Unidad nueva"
    # (25-09-2026, refactor: ver comercial.py, ComercialModule
    # ._on_unidad_nueva_confirmada / _abrir_importar_powerbi). General ya no
    # tiene responsabilidad de creación de unidades.

    # ==========================================
    # DATOS
    # ==========================================
    def _on_data_ready(self):
        try:
            if self.isVisible():
                self.load_data()
            else:
                self._data_dirty = True
        except Exception as e:
            logger.warning(f"Error silencioso en Clientes y Flota: {e}")

    def refresh_if_dirty(self):
        """Llamado por MainWindow._trigger_load_data al navegar a este modulo.
        Sin pending_changes que proteger (vista de solo lectura): si quedo
        marcado dirty por un data_ready recibido mientras estaba oculto,
        recalcula ahora; si no, no hace nada (evita un load_data() de mas)."""
        if self._data_dirty:
            self.load_data()

    def _on_error(self, error_msg):
        logger.error(f"Error al cargar Clientes y Flota: {error_msg}")

    def _on_logs_updated(self):
        """LogApp.csv se actualizó en RAM (DataManager.set_logs_df, ej. tras
        guardar un cambio en Comercial): repuebla únicamente el historial
        del VIN actualmente seleccionado, si hay uno -- no toca la ficha, no
        pierde la selección, no reconstruye clientes/flota/unidades (eso
        sigue siendo trabajo de data_ready/load_data)."""
        if self._vin_seleccionado:
            self._render_historial_vin(self._eventos_historial_de_vin(self._vin_seleccionado))

    def _on_contactos_ready(self):
        # Si ya había un cliente seleccionado cuando Contactos terminó de
        # cargar en segundo plano, refresca su caja de "Contactos encontrados"
        # con los datos recién llegados en vez de dejarla vacía.
        if self._selected_cdb is not None:
            self._populate_contactos_encontrados(self._selected_cdb)
        if getattr(self, '_selected_flota_key', None) is not None:
            self._populate_contactos_flota()

    # ==========================================
    # DIRECTOR DE EMPRESA: BBDD CLIENTES CM.xlsx (Power BI)
    # ==========================================
    def _load_pbi_director_empresa_async(self):
        # Si MainWindow ya lo precargó, se reutiliza en vez de leer de nuevo
        precarga = _precarga_director_pbi
        if precarga['mapa'] is not None:
            self._on_pbi_director_empresa_loaded(precarga['mapa'])
            return
        if precarga['hilo'] is not None and precarga['hilo'].isRunning():
            self._pbi_director_pendiente = True
            precarga['hilo'].data_loaded_signal.connect(self._on_pbi_director_empresa_loaded)
            return
        if precarga['diferida']:
            self._pbi_director_pendiente = True
            precarga['esperando'].append(self)
            return
        if not POWERBI_EXCEL_PATH or not os.path.exists(POWERBI_EXCEL_PATH):
            return
        self._pbi_director_pendiente = True
        self._pbi_director_empresa_thread = PowerBiDirectorEmpresaLoaderThread(POWERBI_EXCEL_PATH)
        self._pbi_director_empresa_thread.data_loaded_signal.connect(self._on_pbi_director_empresa_loaded)
        iniciar_hilo_retenido(self._pbi_director_empresa_thread)

    def _on_pbi_director_empresa_loaded(self, mapa_director_empresa):
        self._pbi_director_empresa_por_cdb = mapa_director_empresa
        self._pbi_director_pendiente = False
        # Igual que _on_contactos_ready: si ya había un cliente seleccionado
        # cuando Power BI terminó de cargar en segundo plano, refresca la
        # caja de "Contactos encontrados" para que muestre la tarjeta de
        # Director de empresa recién llegada en vez de esperar a una nueva
        # selección.
        if self._selected_cdb is not None:
            self._populate_contactos_encontrados(self._selected_cdb)
            self._refrescar_info_cliente_pbi(self._selected_cdb)
        if getattr(self, '_selected_flota_key', None) is not None:
            self._populate_contactos_flota()

    def _refrescar_info_cliente_pbi(self, cdb):
        """Re-renderiza SOLO la caja "Información del cliente" con
        Dirección/Comuna una vez que Power BI termina de cargar (ver
        _on_pbi_director_empresa_loaded). No reutiliza _show_cliente_detalle
        completo a propósito: eso también resetea right_stack/detalle_view a
        "Resumen", perdiendo la pestaña en la que el usuario esté parado."""
        if getattr(self, '_info_cliente_base_args', None) is None:
            return
        if str(self._info_cliente_base_args[2]).strip() != str(cdb).strip():
            return
        director_empresa = self._pbi_director_empresa_por_cdb.get(str(cdb).strip(), {})
        self._render_info_cliente(
            *self._info_cliente_base_args,
            direccion=director_empresa.get('direccion', ''),
            comuna=director_empresa.get('comuna', ''),
        )

    _construir_mapa_director_empresa_pbi = staticmethod(general_services.construir_mapa_director_empresa_pbi)

    _build_clientes_df = staticmethod(general_services.build_clientes_df)

    _calcular_claves_con_varias_razones = staticmethod(general_services.claves_con_varias_razones)

    _calcular_avisos_flota = staticmethod(general_services.calcular_avisos_flota)

    _build_unidades_df = staticmethod(general_services.build_unidades_df)

    def load_data(self):
        """Dispara GeneralDataPrepThread (procesar_df_comercial + los 3
        _build_*_df + listas de filtro, ver esa clase) en vez de calcularlo
        aca mismo de forma sincrona (auditoria de rendimiento, fase 4,
        21-09-2026). El snapshot (get_comercial_df() ya hace .copy()) se toma
        aca, en el hilo de UI, antes de pasarlo al worker.

        Guard de reentrancia: si ya hay un worker corriendo, no se lanza uno
        nuevo -- se marca _prep_pendiente y _on_prep_finished se encarga de
        volver a llamar load_data() (con el snapshot mas reciente) apenas
        el worker actual termine, para que un resultado viejo nunca pueda
        pisar a uno mas nuevo."""
        self._data_dirty = False

        if self._prep_en_curso:
            self._prep_pendiente = True
            return

        self._prep_en_curso = True
        derecho = self.__dict__.get('_esqueleto_der')
        if derecho is not None:
            derecho.debajo_de = None
            derecho.fijar_forma('ficha')
        for esqueleto in self._esqueletos():
            esqueleto.iniciar()
        snapshot = self.data_manager.get_comercial_df()
        self._prep_thread = GeneralDataPrepThread(snapshot)
        self._prep_thread.data_prepared_signal.connect(self._on_prep_finished)
        iniciar_hilo_retenido(self._prep_thread)

    def _on_prep_finished(self, resultado):
        """Hilo de UI: aplica el resultado de GeneralDataPrepThread. Mismo
        trabajo que antes hacia load_data() despues del calculo pesado
        (guardar los DataFrames, poblar listas de filtro con QListWidget, y
        construir las tarjetas), sin cambios de comportamiento."""
        self._prep_en_curso = False
        self.df_comercial_raw, self.df_clientes_base, self.df_unidades_base = resultado

        # El hilo ya dejó listas las claves, los avisos y las flotas; sin eso (o si no corresponden a este
        # resultado) se calculan aquí como antes
        extras = getattr(getattr(self, '_prep_thread', None), 'extras', None)
        if extras is not None and extras[0] is resultado[0]:
            (self.df_comercial_raw, self._clientes_con_varias_razones,
             self._clientes_aviso_flota, self.df_flotas_base) = extras[1]
        else:
            extras = None
            if COL_RUT in self.df_comercial_raw.columns and COL_RAZON_SOCIAL in self.df_comercial_raw.columns:
                self.df_comercial_raw = self.df_comercial_raw.assign(_clave_cliente=comercial_services.clave_cliente_serie(
                    self.df_comercial_raw[COL_RUT], self.df_comercial_raw[COL_RAZON_SOCIAL]))
            self._clientes_con_varias_razones = self._calcular_claves_con_varias_razones(self.df_comercial_raw)
            self._clientes_aviso_flota = self._calcular_avisos_flota(self.df_comercial_raw)
        try:
            chk_avisos = self.chk_solo_avisos_flota
        except (AttributeError, RuntimeError):
            chk_avisos = None
        if chk_avisos is not None:
            chk_avisos.setText(f"Solo con aviso de flotas ({len(self._clientes_aviso_flota)})")

        if extras is None:
            if COL_FLOTA_VC in self.df_comercial_raw.columns:
                self.df_comercial_raw = self.df_comercial_raw.assign(_clave_flota=self._claves_flota(self.df_comercial_raw))
            self.df_flotas_base = self._build_flotas_df(self.df_comercial_raw)

        self._poblar_filtros_unidades()

        self.filter_clientes()
        self.filter_unidades()
        self.filter_flotas()

        try:
            if not self._primera_carga_emitida:
                self._primera_carga_emitida = True
                self.primera_carga_lista.emit()
        except (AttributeError, RuntimeError):
            # Instancias creadas con GeneralModule.__new__ (sin pasar por
            # __init__, ver TestLoadDataGuardDeReentrancia) no tienen el
            # QObject subyacente inicializado y no pueden emitir señales --
            # no aplica en producción, donde siempre se pasa por __init__.
            pass

        # En la app ya vienen precargadas desde MainWindow (pantalla de carga);
        # esto solo lee lo que falte
        if not self.__dict__.get('_cargas_secundarias_iniciadas', True):
            self._cargas_secundarias_iniciadas = True
            QTimer.singleShot(300, self._iniciar_cargas_secundarias)

        if self._prep_pendiente:
            # El esqueleto sigue a la vista hasta que termine la carga nueva
            self._prep_pendiente = False
            self.load_data()
        else:
            for esqueleto in self._esqueletos():
                esqueleto.terminar()
            self._programar_prerender_pestanas(600)

    def filter_clientes(self):
        if self.df_clientes_base.empty:
            self._df_clientes_visible = pd.DataFrame(columns=COLUMNAS_CLIENTES)
            self._render_clientes_cards(self._df_clientes_visible)
            self._sincronizar_seleccion_cliente(self._df_clientes_visible)
            return

        # El filtro de Industria se movió a la pestaña Unidades (junto a
        # Razón Social/Estado Activación, a pedido explícito 15-09-2026):
        # esta lista ya no filtra por Industria/s.
        df_f = self.df_clientes_base.copy()

        texto_busqueda = self.search_input.text()
        df_filtrado = self._aplicar_busqueda_clientes(df_f, texto_busqueda)
        claves_vin, self._vins_busqueda = self._claves_por_vin_buscado(texto_busqueda)
        if claves_vin:
            # Un VIN buscado también trae a su cliente
            df_f = df_f[df_f.index.isin(df_filtrado.index) | df_f['Clave'].astype(str).isin(claves_vin)]
        else:
            df_f = df_filtrado

        chk_avisos = getattr(self, 'chk_solo_avisos_flota', None)
        if chk_avisos is not None and chk_avisos.isChecked():
            df_f = df_f[df_f['Clave'].astype(str).isin(self._clientes_aviso_flota)]

        columna_orden = {'unidades': 'Total unidades', 'flotas': 'Total flotas'}.get(self._clientes_orden_campo, 'Razón Social')
        df_f = df_f.sort_values(by=columna_orden, ascending=self._clientes_orden_asc, na_position='last')
        df_f = df_f.reset_index(drop=True)

        # Fuente que usa _on_cliente_card_clicked/_sincronizar_seleccion_
        # cliente para mapear fila -> cliente.
        self._df_clientes_visible = df_f

        self._render_clientes_cards(df_f)
        self._sincronizar_seleccion_cliente(df_f)
        self._abrir_cliente_de_vin_buscado(df_f, claves_vin)

    def _claves_por_vin_buscado(self, texto_busqueda):
        """(claves de cliente, VIN encontrados) para los términos de la
        búsqueda que parecen un VIN (8 a 17 letras/dígitos). Con 17 caracteres
        el VIN debe coincidir completo; con menos, basta que lo contenga."""
        terminos = {t.upper() for t in re.split(r'[,\s;]+', texto_busqueda.strip()) if re.fullmatch(r'[A-Za-z0-9]{8,17}', t)}
        df = self.df_unidades_base
        if not terminos or df.empty or 'VIN' not in df.columns or 'Clave' not in df.columns:
            return set(), set()
        vins = df['VIN'].astype(str).str.strip().str.upper()
        completos = [t for t in terminos if len(t) == 17]
        parciales = [t for t in terminos if len(t) < 17]
        mascara = vins.isin(completos)
        for t in parciales:
            mascara |= vins.str.contains(t, regex=False)
        if not mascara.any():
            return set(), set()
        return set(df.loc[mascara, 'Clave'].astype(str)), set(vins[mascara])

    def _abrir_cliente_de_vin_buscado(self, df_visible, claves_vin):
        """Con un VIN en la búsqueda: abre el primer cliente que lo tiene y
        deja su pestaña Unidades a la vista (el VIN sale primero y resaltado,
        ver _populate_unidades_detalle). Si los VIN son de varios clientes no abre ninguno."""
        if len(claves_vin) != 1 or self.left_stack.currentIndex() != 0 or 'Clave' not in df_visible.columns:
            return
        for clave in df_visible['Clave'].astype(str):
            if clave in claves_vin:
                self._seleccionar_cliente_por_clave(clave)
                self._switch_detalle_view(1)
                return

    @staticmethod
    def _aplicar_filtros_unidades(df_unidades, filtros):
        """Deja las unidades que cumplen todos los filtros activos.
        `filtros`: {columna: None | conjunto de valores en mayúsculas}; None no
        filtra. Con un filtro activo, un valor vacío o '-' no coincide. Función
        pura (no usa self.*)."""
        df_f = df_unidades
        for columna, claves in filtros.items():
            if claves is None or columna not in df_f.columns:
                continue
            df_f = df_f[df_f[columna].astype(str).map(_clave_flota_texto).isin(claves)]
        return df_f

    def _poblar_filtros_unidades(self):
        """Las opciones y cantidades de cada filtro salen de las unidades que
        cumplen los demás filtros y la búsqueda (como en Comercial)."""
        base = self.df_unidades_base
        if not base.empty and hasattr(self, 'search_input'):
            base = self._buscar_en_unidades(base)
        base = self._aplicar_filtro_vins(self._aplicar_rango_fecha_baja(base))
        mascaras = {}
        for columna, boton in self._filtros_unidades.items():
            claves = boton.seleccion()
            if claves is not None and columna in base.columns:
                mascaras[columna] = base[columna].astype(str).map(_clave_flota_texto).isin(claves)
        for columna, boton in self._filtros_unidades.items():
            if columna not in base.columns:
                boton.set_valores([])
                continue
            sub = base
            otras = [m for c, m in mascaras.items() if c != columna]
            if otras:
                mascara = otras[0]
                for m in otras[1:]:
                    mascara = mascara & m
                sub = base[mascara]
            boton.set_valores(FiltroValoresBoton.valores_distintos(sub[columna]))

    def _aplicar_filtro_vins(self, df):
        if self._filtro_vins is None or df.empty or 'VIN' not in df.columns:
            return df
        return df[df['VIN'].astype(str).str.strip().str.upper().isin(self._filtro_vins)]

    def mostrar_contratos_de_vins(self, vins, titulo):
        """Contratos mostrando solo estas unidades (por ejemplo las bajas de un mes del Dashboard).
        Quita los demás filtros para que se vean todas; el botón de la barra quita este."""
        self._filtro_vins = {str(v).strip().upper() for v in vins}
        self._titulo_filtro_vins = f"{titulo} ({len(self._filtro_vins)})"
        for boton in self._filtros_unidades.values():
            boton.limpiar()
        self._filtro_fecha_baja.limpiar()
        self.chk_ocultar_sin_vc.setChecked(False)
        self._switch_left_view(1)
        self.filter_unidades()

    def mostrar_flotas_de_vins(self, vins, titulo):
        """Flotas con estas unidades (por ejemplo las bajas de un mes del Dashboard): la lista muestra solo
        esas flotas y la caja derecha abre la primera con sus unidades, las pedidas primero y seleccionadas.
        Devuelve cuántas flotas hay; el botón de la barra quita el filtro."""
        self._filtro_vins_flotas = {str(v).strip().upper() for v in vins}
        self._titulo_filtro_flotas = f"{titulo} ({len(self._filtro_vins_flotas)})"
        self._switch_left_view(2)
        self.filter_flotas()
        self._actualizar_aviso_filtro_flotas()
        return len(self._df_flotas_visible)

    def _quitar_filtro_vins_flotas(self):
        self._filtro_vins_flotas = None
        self._actualizar_aviso_filtro_flotas()
        self.filter_flotas()

    def _actualizar_aviso_filtro_flotas(self):
        boton = self.__dict__.get('btn_filtro_vins_flotas')
        if boton is None:
            return
        activo = self._filtro_vins_flotas is not None
        boton.setText(f"{self._titulo_filtro_flotas}  \u2715" if activo else "")
        boton.setVisible(activo and self.left_stack.currentIndex() == 2)

    def _quitar_filtro_vins(self):
        self._filtro_vins = None
        self._actualizar_aviso_filtro_vins()
        self.filter_unidades()

    def _actualizar_aviso_filtro_vins(self):
        boton = self.__dict__.get('btn_filtro_vins')
        if boton is None:
            return
        activo = self._filtro_vins is not None
        boton.setText(f"{self._titulo_filtro_vins}  \u2715" if activo else "")
        boton.setVisible(activo and self.left_stack.currentIndex() == 1)

    def _aplicar_rango_fecha_baja(self, df):
        rango = self._filtro_fecha_baja.rango() if '_filtro_fecha_baja' in self.__dict__ else None
        return df if rango is None else general_services.filtrar_por_rango_fechas(df, 'Fecha de Baja', *rango)

    def _limpiar_filtros_unidades(self):
        for boton in self._filtros_unidades.values():
            boton.limpiar()
        self._filtro_fecha_baja.limpiar()
        self.filter_unidades()

    @staticmethod
    def _aplicar_busqueda_clientes(df, texto_busqueda):
        """Buscador global sobre la lista de Cliente: coincide con cualquiera
        de las razones sociales del cliente, su RUT (con o sin puntos y
        guion) o su CDB. Términos separados por coma se combinan con OR."""
        texto = texto_busqueda.strip().lower()
        if not texto or df.empty or 'Busqueda' not in df.columns:
            return df
        terminos = []
        for termino in texto.split(','):
            termino = termino.strip()
            plano = re.sub(r'[\.\-]', '', termino)
            terminos.append(plano if re.fullmatch(r'[0-9k]{5,}', plano) else termino)
        mascara = comercial_services.construir_mascara_busqueda(df, ','.join(terminos), ['Busqueda'])
        return df[mascara]

    def _buscar_en_unidades(self, df):
        """La búsqueda global sobre `df` (las unidades base o un recorte suyo). Se resuelve una sola vez por
        texto sobre todas las unidades y se reutiliza: los filtros y la lista la pedían dos veces."""
        texto = self.search_input.text()
        base = self.df_unidades_base
        guardada = self.__dict__.get('_busqueda_unidades_cache')
        if guardada is None or guardada[0] is not base or guardada[1] != texto:
            encontradas = self._aplicar_busqueda_unidades(base, texto)
            guardada = (base, texto, None if encontradas is base else encontradas.index)
            self._busqueda_unidades_cache = guardada
        indices = guardada[2]
        return df if indices is None else df[df.index.isin(indices)]

    @staticmethod
    def _aplicar_busqueda_unidades(df_unidades, texto_busqueda):
        """Buscador global de MainWindow (self.search_bar) sobre la caja
        izquierda -> Unidades: cada término puede coincidir en Razón Social,
        VIN, CDB o RUT (COLUMNAS_BUSQUEDA_UNIDADES) indistintamente. Reutiliza
        comercial_services.construir_mascara_busqueda (auditoria de
        rendimiento B-2, 18-09-2026) en vez del loop propio anterior
        (O(términos x columnas) con un .str.contains() por cada uno): medido
        ~1.4-1.9s al pegar 200 VINs (límite de MAX_TERMINOS_BUSQUEDA_GLOBAL
        en main_window.py) contra ~47ms de construir_mascara_busqueda para
        el mismo caso en comercial.py, que ya resuelve esto con una sola
        regex de alternancia por columna. Efecto colateral (bug real
        corregido, no solo de rendimiento): el loop anterior separaba solo
        por espacio, así que un texto pegado con comas (MultiSearchLineEdit
        pega listas separadas por coma) quedaba con las comas pegadas a cada
        VIN y los exigía todos con AND -- en la práctica 0 resultados al
        pegar más de un término. construir_mascara_busqueda interpreta ','
        como OR entre términos (igual que en comercial.py), por lo que pegar
        varios VINs ahora sí encuentra cada uno. Para un solo término o
        varias palabras sin coma (el caso de tipeo normal) el resultado es
        idéntico al de antes: AND entre esas palabras, OR entre columnas.
        Función pura (no usa self.*): no modifica df_unidades ni el
        DataFrame original, devuelve una copia filtrada."""
        texto = texto_busqueda.strip().lower()
        if not texto or df_unidades.empty:
            return df_unidades

        columnas = [c for c in COLUMNAS_BUSQUEDA_UNIDADES if c in df_unidades.columns]
        if not columnas:
            return df_unidades

        mask = comercial_services.construir_mascara_busqueda(df_unidades, texto, columnas)
        return df_unidades[mask]

    def filter_table(self):
        """Punto de enganche del buscador global de MainWindow
        (self.search_bar en main_window.py): MainWindow detecta
        search_input + filter_table vía hasattr y llama esto después de
        fijarle el texto (ver MainWindow._on_global_search). Reaplica el
        filtrado de las 2 sub-pestañas de la caja izquierda (Cliente/Unidades):
        Cliente busca en todas sus razones sociales, RUT y CDB (ver
        _aplicar_busqueda_clientes) y Unidades en Razón Social, VIN, CDB o RUT
        (ver COLUMNAS_BUSQUEDA_UNIDADES). Nunca toca
        ningún estado de la caja derecha (selección de cliente/CDB, KPIs,
        Contactos, filtros), que sigue su propio ciclo de vida independiente
        del buscador."""
        self._animar_carga_breve(solo_izquierda=True)
        self.filter_clientes()
        self.filter_unidades()
        self.filter_flotas()

    def filter_unidades(self):
        if self.df_unidades_base.empty:
            self._df_unidades_visible = pd.DataFrame(columns=COLUMNAS_UNIDADES)
            self._render_unidades_cards(self._df_unidades_visible)
            self._vin_seleccionado = None
            self._show_vin_vacio()
            return

        self._poblar_filtros_unidades()
        filtros = {columna: boton.seleccion() for columna, boton in self._filtros_unidades.items()}
        df_f = self._aplicar_filtros_unidades(self.df_unidades_base, filtros)
        df_f = self._aplicar_rango_fecha_baja(df_f)
        df_f = self._aplicar_filtro_vins(df_f)
        df_f = self._buscar_en_unidades(df_f)
        if self.chk_ocultar_sin_vc.isChecked() and not df_f.empty:
            sin_vc = [_es_sin_vc(ec, ea, fc, tf) for ec, ea, fc, tf in zip(
                df_f['Estado Comercial'], df_f['Estado Activación'], df_f['Forma de Contrato'], df_f['Tipo de Facturación'])]
            df_f = df_f[[not s for s in sin_vc]]

        columna = self._unidades_orden_columna
        if columna and columna in df_f.columns:
            # Vacíos y '-' van siempre al final
            df_f = df_f.assign(_orden=df_f[columna].astype(str).str.strip().replace({'': None, '-': None}))
            df_f = df_f.sort_values(by=['_orden', 'Razón Social', 'VIN'],
                                    ascending=[self._unidades_orden_asc, True, True], na_position='last')
            df_f = df_f.drop(columns='_orden')
        else:
            df_f = df_f.sort_values(by=['Razón Social', 'VIN'], ascending=self._unidades_orden_asc, na_position='last')
        df_f = df_f.reset_index(drop=True)

        # Fuente que usa _on_unidad_card_clicked/_sincronizar_seleccion_vin
        # para mapear fila -> VIN (mismo rol que _df_clientes_visible para Cliente).
        self._df_unidades_visible = df_f

        self._render_unidades_cards(df_f)
        self._sincronizar_seleccion_vin()

    def _populate_unidades_detalle(self, clave):
        """Caja derecha, apartado "Unidades": los contratos del cliente seleccionado (por su clave, ver
        _clave_cliente). La tabla se pinta al abrir la pestaña."""
        if '_clave_cliente' in self.df_comercial_raw.columns:
            df_raw = self.df_comercial_raw[self.df_comercial_raw['_clave_cliente'] == str(clave)]
        else:
            df_raw = pd.DataFrame()
        self._cliente_df_unidades = self._preparar_df_contratos(df_raw)
        self._cliente_unidades_construidas = False
        for boton in self._filtros_cliente_unidades.values():
            boton.set_valores([])
            boton.limpiar()
        if self.detalle_stack.currentIndex() == 1:
            self._iniciar_unidades_cliente()
