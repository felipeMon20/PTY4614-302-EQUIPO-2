"""Pantalla Operaciones: cola de unidades por conectar, panel de detalle y acciones sobre flota y activación."""
from src.theme.colors import BACKGROUND, TEXT_SECONDARY
from html import escape as html_escape
import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit, QHeaderView, QAbstractItemView, QMessageBox, QApplication
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QUrl
from PyQt6.QtGui import QKeySequence, QFontMetrics, QDesktopServices
import config.settings
from config.settings import REPORTE_NOTAS_VENTAS_URL
from src.ui.compartido import aviso_enlace
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.constants import COL_VIN, COL_ESTADO_COMERCIAL, VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA, COL_CDB_FLOTA, COL_FLOTA_VC
from src.services import comercial_services, operaciones_services, contactos_service, ejecutivos_service
from src.services import localizador_vin, cm_bajas_service
from src.ui.compartido.custom_table import VolvoTableWidget
from src.ui.administracion.contactos import AddContactoThread
from src.ui.administracion.contactos_agregar import ContactosAddDialog
from src.ui.compartido.guardado_overlay import mostrar_guardando, terminar_guardando
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.ui.ingresos.base import PantallaIngresosBase
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.transiciones import TransicionFundidoSubida
from src.ui.compartido.panel_ubicacion_vin import PanelUbicacionVin
from src.theme.theme_manager import ThemeManager
from src.ui.operaciones.base import (  # noqa: F401 (se reexportan: otros módulos los importan desde aquí)
    _IgnorarSeleccionClicDerecho,
    MENSAJE_ERROR_GUARDADO,
    SIN_PLAN,
    _texto_cantidad,
    COLUMNAS_TABLA_ACTIVACIONES,
    COLUMNAS_TABLA_BAJAS,
    _COLUMNAS_POR_TAB,
    ANCHOS_COLUMNAS_ACTIVACIONES,
    ALTO_MINIMO_FILA,
    _HOLGURA_TEXTO_UNA_LINEA,
    _es_latin1,
    _FILTROS_EXTRA,
    BotonAccionOperaciones,
    COLUMNAS_BUSQUEDA_OPERACIONES,
    COLUMNAS_BUSQUEDA_EXACTAS_OPERACIONES,
    _COLUMNAS_PEGADO_MASIVO,
    CAMPOS_DETALLE_ACTIVACIONES,
    SUBTABS_CON_DATOS_FLOTA,
    IDX_ACTIVACIONES,
    IDX_SIN_FLOTA,
    IDX_NO_ENTREGADOS,
    IDX_CONTACTOS,
    IDX_DATOS_FLOTA,
    SUBTABS,
    _FILTROS_POR_TAB,
    OperacionesTableModel,
    SaveExcelThread,
)
from src.ui.operaciones.panel import _PanelOperacionesMixin
from src.ui.operaciones.exportar import _ExportarOperacionesMixin
from src.ui.operaciones.detalle import _DetalleOperacionesMixin
from src.ui.operaciones.acciones import _AccionesOperacionesMixin
from src.ui.operaciones.fechas_baja import _FechasBajaOperacionesMixin, IDX_BAJAS


class OperacionesModule(_PanelOperacionesMixin, _ExportarOperacionesMixin, _DetalleOperacionesMixin, _FechasBajaOperacionesMixin, _AccionesOperacionesMixin, QWidget):
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

        # Dónde está el VIN buscado cuando no está en Operaciones (ver _localizar_vin_buscado)
        self._ubicacion_vin_destino = None
        self._panel_ubicacion_vin = PanelUbicacionVin(self, [self._kpi_contenedor, self._contenido])
        self._panel_ubicacion_vin.ir_clicked.connect(self._on_ir_ubicacion_vin)

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
        self._layout_tarjeta_tabla = layout

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
        self._selectores_filtro = {'cliente': estilo_com.SelectorFiltroPopup("Cliente", "Todos los clientes", 'fa5s.user-tie', multiple=True)}
        for col, titulo, icono in _FILTROS_EXTRA:
            self._selectores_filtro[col] = estilo_com.SelectorFiltroPopup(titulo, f"Todas ({titulo.lower()})", icono, multiple=True)
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

        # En Activaciones y Sin Flota: rojo si hay unidades SIN PLAN; al pulsarlo filtra esas unidades
        self.btn_sin_plan = QPushButton()
        self.btn_sin_plan.setCheckable(True)
        self.btn_sin_plan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sin_plan.setIcon(ThemeManager.icon('fa5s.tags', color=TEXT_SECONDARY))
        estilo_com.aplicar_estilo_boton_barra(self.btn_sin_plan, 'neutro')
        self.btn_sin_plan.toggled.connect(self._on_sin_plan_toggled)
        self._solo_sin_plan = False
        self._sin_plan_cantidad = 0
        self.btn_sin_plan.hide()

        self._crear_controles_fechas_baja()

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
        top_row.addWidget(self.btn_volver_flotas)
        top_row.addStretch()
        # Tres grupos con encabezado: filtros, acciones y generales
        for titulo_grupo, botones in (
                ("Filtros", (self.btn_limpiar_filtros, *self._selectores_filtro.values(), self.btn_faltantes, self.btn_cdb_varias,
                                       self.btn_sin_plan, self.btn_fechas_baja)),
                ("Acciones", (self.btn_exportar_vin_cdb, self.btn_exportar_contactos)),
                ("Generales", (self.btn_ampliar,))):
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
            f"QTableView {{ alternate-background-color: {estilo_com.FILA_ALTERNA}; }}"
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
        self._filtro_clic_derecho = _IgnorarSeleccionClicDerecho(self)
        for vista in (self.table, self.table.frozen_view):
            vista.viewport().installEventFilter(self._filtro_clic_derecho)

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
            aviso_enlace.avisar_enlace_faltante(self, "Notas de Venta (Power BI)")

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
        botones = [self.btn_marcar_conectado, self.btn_marcar_sin_flota, self.btn_marcar_no_entregado,
                   self.btn_activacion_pendiente,
                   self.btn_deshacer_envio, self.btn_marcar_desconectado, self.btn_guardar_flota, self.btn_limpiar_flota,
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
        self.btn_marcar_conectado.setVisible(idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA, IDX_NO_ENTREGADOS))
        self.btn_marcar_sin_flota.setVisible(idx in (IDX_ACTIVACIONES, IDX_NO_ENTREGADOS))
        self.btn_marcar_no_entregado.setVisible(idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA))
        self.btn_activacion_pendiente.setVisible(idx in (IDX_SIN_FLOTA, IDX_NO_ENTREGADOS))
        self.btn_deshacer_envio.setVisible(idx == IDX_ACTIVACIONES)   # fijo en Activaciones; se habilita con la selección
        self.btn_marcar_desconectado.setVisible(idx == IDX_BAJAS)
        self.btn_guardar_flota.setVisible(idx in SUBTABS_CON_DATOS_FLOTA)
        self.btn_limpiar_flota.setVisible(idx in (IDX_SIN_FLOTA, IDX_NO_ENTREGADOS))
        self._reubicar_acciones()
        self._bloque_datos_flota.setVisible(idx in SUBTABS_CON_DATOS_FLOTA)
        self.btn_exportar_vin_cdb.setVisible(idx != IDX_CONTACTOS)
        self.btn_faltantes.setVisible(idx == IDX_DATOS_FLOTA)
        self.btn_cdb_varias.setVisible(idx == IDX_DATOS_FLOTA)
        self.btn_sin_plan.setVisible(idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA, IDX_NO_ENTREGADOS))
        self._bloque_unidad.setVisible(idx != IDX_CONTACTOS)
        self._bloque_contacto.setVisible(idx == IDX_CONTACTOS)
        if idx != IDX_CONTACTOS:
            self._quitar_formulario_contacto()
        self._actualizar_visibilidad_fechas_baja(idx)

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

    def _actualizar_boton_sin_plan(self, cantidad):
        self._sin_plan_cantidad = cantidad
        if self.btn_sin_plan.isChecked():
            return
        if cantidad:
            estilo_com.aplicar_estilo_boton_barra(self.btn_sin_plan, 'alerta')
            self.btn_sin_plan.setIcon(ThemeManager.icon('fa5s.tags', color=estilo_com.ROJO))
            self.btn_sin_plan.setToolTip(f"{cantidad} unidad(es) sin plan. Click para mostrarlas y asignarles uno.")
        else:
            estilo_com.aplicar_estilo_boton_barra(self.btn_sin_plan, 'neutro')
            self.btn_sin_plan.setIcon(ThemeManager.icon('fa5s.tags', color=TEXT_SECONDARY))
            self.btn_sin_plan.setToolTip("Todas las unidades de esta lista tienen plan.")

    def _on_sin_plan_toggled(self, activo):
        self._solo_sin_plan = activo
        if activo:
            estilo_com.aplicar_estilo_boton_barra(self.btn_sin_plan, 'activo')
            self.btn_sin_plan.setIcon(ThemeManager.icon('fa5s.tags', color=estilo_com.PRIMARIO))
            self.btn_sin_plan.setToolTip("Mostrando solo las unidades sin plan. Click para volver a todas.")
        self._refrescar_tabla_actual()
        if activo and self.model.get_df().empty:
            self.btn_sin_plan.setChecked(False)
            QMessageBox.information(self, "Unidades sin plan", "Todas las unidades de esta lista tienen plan.")
        elif not activo:
            self._actualizar_boton_sin_plan(self._sin_plan_cantidad)

    def _refrescar_cola(self, idx):
        if idx == IDX_BAJAS and self._modo_fechas_baja:
            self._refrescar_fechas_baja()
            return
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

        if idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA, IDX_NO_ENTREGADOS):
            sin_plan = operaciones_services.mascara_sin_plan(full) if not full.empty else None
            self._actualizar_boton_sin_plan(0 if sin_plan is None else int(sin_plan.sum()))
            if sin_plan is not None and self._solo_sin_plan:
                full = full[sin_plan].reset_index(drop=True)

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
        if idx == IDX_ACTIVACIONES and not full.empty and COL_ESTADO_COMERCIAL in full.columns:
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
        if idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA, IDX_NO_ENTREGADOS) and 'TIPO DE SERVICIO' in df_tabla.columns and not df_tabla.empty:
            df_tabla.loc[operaciones_services.mascara_sin_plan(df_tabla), 'TIPO DE SERVICIO'] = SIN_PLAN
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
        self._localizar_vin_buscado()
        self._refrescar_tabla_actual()

    # ---------------------------------------------------------------
    # Búsqueda por VIN: lleva a la cola donde está la unidad y deja las pestañas visibles; con varios VIN
    # va a la primera cola que tenga alguno. Si no está aquí, dice dónde está.
    # ---------------------------------------------------------------
    def _localizar_vin_buscado(self):
        vins_texto = localizador_vin.extraer_vins(self.search_input.text())
        if not vins_texto:
            for i in range(self.subtabs.count()):
                self.subtabs.setTabVisible(i, True)
            self.subtabs.updateGeometry()
            self._panel_ubicacion_vin.hide()
            self._ubicacion_vin_destino = None
            return
        # Al llegar desde otra pantalla con el VIN en la búsqueda, los datos pueden estar sin recargar todavía
        if self._data_dirty:
            self.load_data()
        df = self.df_master
        # Las colas se revisan una sola vez con todos los VIN encontrados (por término eran miles de filtrados)
        indice = localizador_vin.IndiceVins(df)
        vins = set()
        for termino in vins_texto:
            vins |= indice.buscar(termino)
        pestanas = localizador_vin.pestanas_operaciones(vins, df) if vins else []
        if pestanas:
            self._panel_ubicacion_vin.hide()
            self._ubicacion_vin_destino = None
            for i in range(self.subtabs.count()):
                self.subtabs.setTabVisible(i, True)
            if self.subtabs.currentIndex() not in pestanas:
                self.subtabs.setCurrentIndex(pestanas[0])
            return
        self._mostrar_ubicacion_fuera_de_operaciones(vins_texto[0])

    def _mostrar_ubicacion_fuera_de_operaciones(self, termino):
        df_com = comercial_services.preparar_df_base_comercial(self.data_manager.get_comercial_df())
        casos = cm_bajas_service.leer_casos_baja_cm(config.settings.CASOS_BAJA_CM_PATH)
        vins = localizador_vin.vins_de_termino(termino, df_com, casos)
        pestanas = localizador_vin.pestanas_comercial(vins, df_com, casos) if vins else []
        for i in range(self.subtabs.count()):
            self.subtabs.setTabVisible(i, True)
        if pestanas:
            self._ubicacion_vin_destino = ("Comercial", pestanas[0])
            self._panel_ubicacion_vin.mostrar_destino(
                sorted(vins)[0], localizador_vin.descripcion("Comercial", pestanas[0]))
        else:
            self._ubicacion_vin_destino = None
            self._panel_ubicacion_vin.mostrar_no_encontrado(sorted(vins)[0] if vins else termino)

    def _on_ir_ubicacion_vin(self):
        destino = self._ubicacion_vin_destino
        ventana = self.window()
        if destino and hasattr(ventana, '_on_menu_clicked'):
            ventana._on_menu_clicked(destino[0])

    def _actualizar_estado_botones(self):
        idx = self.subtabs.currentIndex()
        cola_activa = self._cola_full.get(idx, pd.DataFrame())
        self.btn_exportar_contactos.setEnabled(idx in (IDX_ACTIVACIONES, IDX_DATOS_FLOTA, IDX_CONTACTOS) and not cola_activa.empty)
        self.btn_exportar_vin_cdb.setEnabled(not self.model.get_df().empty)
        # "Marcar como CONECTADO" tiene sentido en Activaciones y Sin Flota
        # (resolver la unidad hacia CONECTADO); "Marcar como SIN FLOTA" solo
        # en Activaciones (sacar de ahí una unidad que todavía no aparece en
        # Volvo Connect); "Marcar como DESCONECTADO" es exclusiva de Bajas.
        # No depende solo de la señal selectionChanged: al cambiar de
        # sub-pestaña el modelo se reemplaza y la selección previa queda
        # obsoleta, así que se recalcula explícitamente para no dejar el
        # botón habilitado con VIN de la pestaña anterior.
        self._actualizar_boton_conectado(self._get_selected_vins(), idx)
        self.btn_marcar_sin_flota.setEnabled(idx in (IDX_ACTIVACIONES, IDX_NO_ENTREGADOS) and bool(self._get_selected_vins()))
        self.btn_marcar_no_entregado.setEnabled(idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA) and bool(self._get_selected_vins()))
        self.btn_activacion_pendiente.setEnabled(idx in (IDX_SIN_FLOTA, IDX_NO_ENTREGADOS) and bool(self._get_selected_vins()))
        self._actualizar_boton_deshacer(idx, self._get_selected_vins())
        self.btn_marcar_desconectado.setEnabled(idx == IDX_BAJAS and bool(self._obtener_vins_baja_seleccionados()))
        self.btn_guardar_flota.setEnabled(self._flota_editable(self._get_selected_vins(), idx))
        self.btn_limpiar_flota.setEnabled(idx in (IDX_SIN_FLOTA, IDX_NO_ENTREGADOS) and bool(self._get_selected_vins()))
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

        from src.ui.compartido.mail_dialog import BorradorEjecutivoThread
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
        cola = self._cola_full.get(IDX_BAJAS, pd.DataFrame())
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
        if idx == IDX_BAJAS and self._modo_fechas_baja:
            self._on_seleccion_fechas_baja()
            return
        if idx == IDX_CONTACTOS:
            self._mostrar_formulario_contacto()
            return
        vins = self._get_selected_vins()
        self._actualizar_boton_conectado(vins, idx)
        self.btn_marcar_sin_flota.setEnabled(idx in (IDX_ACTIVACIONES, IDX_NO_ENTREGADOS) and bool(vins))
        self.btn_marcar_no_entregado.setEnabled(idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA) and bool(vins))
        self.btn_activacion_pendiente.setEnabled(idx in (IDX_SIN_FLOTA, IDX_NO_ENTREGADOS) and bool(vins))
        self._actualizar_boton_deshacer(idx, vins)
        self.btn_marcar_desconectado.setEnabled(idx == IDX_BAJAS and bool(self._obtener_vins_baja_seleccionados()))
        self.btn_guardar_flota.setEnabled(self._flota_editable(vins, idx))
        self.btn_limpiar_flota.setEnabled(idx in (IDX_SIN_FLOTA, IDX_NO_ENTREGADOS) and bool(vins))
        self.btn_contactar_ejecutivo.setEnabled(bool(vins))

        self._mostrar_panel(bool(vins))
        self._lbl_titulo_panel.setText(
            "Unidad seleccionada" if len(vins) <= 1 else f"{len(vins)} unidades seleccionadas"
        )
        if idx in SUBTABS_CON_DATOS_FLOTA:
            self._cargar_campos_flota(vins)
        self._actualizar_bloque_plan(vins, idx)
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
                    mascara &= otro.coincide(series[otra])
            conteo = series[clave][mascara].value_counts()
            items = [(v, f"{v} ({n})") for v, n in sorted(conteo.items()) if v and v.lower() not in ('-', 'nan', 'none')]
            selector.set_opciones([(None, items)])
        self._orden_filtros[:] = [s for s in self._orden_filtros if s.valor() is not None]
        mascara = pd.Series(True, index=full.index)
        for clave, selector in self._selectores_filtro.items():
            if series[clave] is not None and selector.valor() is not None:
                mascara &= selector.coincide(series[clave])
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
