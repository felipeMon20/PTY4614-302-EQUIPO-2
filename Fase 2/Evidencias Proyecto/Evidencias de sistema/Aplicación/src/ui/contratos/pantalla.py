"""Pantalla Contratos (CM): empresas, flotas y contratos con tarjetas KPI, acciones y la importación del Excel."""
from src.theme.colors import PRIMARY, VOLVO_BLUE
import os
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QMessageBox, QLineEdit, QFileDialog, QApplication, QStackedWidget, QDialog, QPushButton
from PyQt6.QtCore import Qt, QEvent, QTimer
import config.settings
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.ui.compartido.custom_table import VolvoTableWidget, PandasTableModel, ExportExcelThread
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando, crear_tarjeta_carga
from src.ui.compartido.formulario_unidad import editar_unidad, PESTANA_JUSTTIME_CM
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.ingresos.base import PantallaIngresosBase, ComboFiltroBarra, boton_barra, estilo_combo_barra
from src.theme.theme_manager import ThemeManager
from src.services import cm_bajas_service
from src.services import comercial_services
from src.services import contratos_service as ct_service
from src.core.dataframe_formatter import DataFrameFormatter
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.core.constants import COL_ESTADO_COMERCIAL, COL_ETAPA_GESTION, COL_TIPO_FACTURACION, COL_FORMA_CONTRATO, VALOR_ESTADO_COMERCIAL_BAJA, COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM, TIPO_CM_OPCIONES, ESTADO_CM_OPCIONES, COL_RUT, COL_RAZON_SOCIAL, TIPO_CM_FORMA_CONTRATO_MAP, VALOR_TIPO_FACT_CM, COL_ESTADO_ACTIVACION, COL_CDB_FLOTA, ESTADOS_CM_SIN_PAGO, ESTADO_CM_PENDIENTE
from src.ui.contratos.base import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    logger,
    MODULE_ACCENT,
    _BADGE_COLOR,
    _BADGE_COLOR_DEFAULT,
    _formato_pago,
    SaveContratosThread,
    AnalisisImportacionThread,
    _TONOS_IMPORTACION,
    _COLOR_ACTIVACION,
    _AVISOS_UNIDAD,
    _FILTROS_UNIDAD,
    _COLUMNAS_UNIDAD,
    _dato_o_sin_dato,
    _pago_importacion,
    _numero_pago,
    _ItemOrden,
    _Interruptor,
    COL_CONTRATOS_TABLA,
    COL_VIGENTES_TABLA,
    COL_DESCONECTADOS_TABLA,
    COL_ACTIVANDO_TABLA,
    COL_AL_DIA_TABLA,
    COL_POR_ACTUALIZAR_TABLA,
    COL_SIN_PAGO_TABLA,
    COL_CDB_VARIOS,
    COL_FLOTA_VC_TABLA,
    _ETIQUETA_SITUACION_PAGO,
    _FilasPorVin,
    _COLUMNAS_EMPRESAS_CM,
    COL_EJECUTIVO_TABLA,
    COL_FORMA_ACTUAL_TABLA,
    COL_FACTURACION_ACTUAL_TABLA,
    COL_TIPO_CM_TABLA,
    COL_ESTADO_ACTUAL_TABLA,
    COL_ULTIMO_PAGO_TABLA,
    _COLUMNAS_FLOTAS_CM,
    _EXTRAS_COLA_CM,
    _COLAS_CM,
    COL_ACTIVACION_TABLA,
    _COLUMNAS_DETALLE_CM,
    _CHIP_VOLVO,
    _CHIP_VIGENTES,
    _CHIP_DESCONECTADOS,
    _CHIP_CDB_VARIOS,
    _CHIP_ACTIVANDO,
    _CHIPS_ACTIVACION,
    _CHIPS_CONTEO_EMPRESAS,
    _KPI_SPECS_CM,
)
from src.ui.contratos.dialogos import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    ResumenPasarACM,
    ExtenderDuracionDialog,
    VinsNuevosContratoAlertDialog,
    VincularContratoComercialDialog,
)
from src.ui.contratos.importacion_dialogo import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    ResumenImportacionDialog,
)
from src.ui.contratos.acciones import _AccionesContratosMixin
from src.ui.contratos.importacion import _ImportacionContratosMixin


class ContratosModule(_AccionesContratosMixin, _ImportacionContratosMixin, PantallaIngresosBase):
    """Modulo 'Contratos (CM)': dos niveles (empresas -> contratos) con el
    esqueleto de Comercial/Operaciones (ver ingresos_base.py) y el color de
    acento del chip de titulo de main_window (MODULE_COLORS['Contratos (CM)']).

    Debajo sigue el mismo motor de datos/guardado que tenia la version en
    tabla (on_item_edited, pending_changes, confirm_save, self.model/
    self.table, ocultos) -- no se reescribio; la edicion pasa por el
    formulario de unidad compartido (formulario_unidad.py), que llama a
    on_item_edited una vez por campo y termina en confirm_save().

    Diseño decidido junto al usuario (05-10-2026, ampliado el 27-10-2026 a 6
    KPIs): Histórico de CM, CM Conectados, Ausentes de la carga, Por
    actualizar, Forma no es CM y Pago CM total; filtros de Estado y Tipo
    de CM en combos; 'Importar Excel CM' y 'Excel' como botones blancos de la
    barra. Desde el 19-09-2026 la pantalla solo muestra VIN con contrato (ver
    contratos_service.filtrar_con_contrato) y el boton 'Guardar' vive dentro
    del formulario de unidad.
    """

    AVATAR = "CM"
    TITULO = "Contratos (CM)"
    KPI_SPECS = _KPI_SPECS_CM
    CAMPOS_FICHA = [("Estado comercial", "ESTADO COMERCIAL"), ("Tipo de servicio", "TIPO DE SERVICIO"),
                    ("Forma de contrato", COL_FORMA_CONTRATO), ("Tipo de facturación", COL_TIPO_FACTURACION)]
    COLUMNAS_OCULTAS = PantallaIngresosBase.COLUMNAS_OCULTAS + (COL_CDB_VARIOS, 'ID')
    ALTO_FILA = 38
    ANCHOS_EMPRESAS = {COL_FLOTA_VC_TABLA: 250, COL_RAZON_SOCIAL: 250, COL_EJECUTIVO_TABLA: 150, COL_FORMA_ACTUAL_TABLA: 190,
                       COL_FACTURACION_ACTUAL_TABLA: 190, COL_TIPO_CM_TABLA: 150, COL_ESTADO_ACTUAL_TABLA: 170, COL_ULTIMO_PAGO_TABLA: 120, COL_RUT: 110, COL_CDB_FLOTA: 130, COL_CONTRATOS_TABLA: 110,
                       COL_AL_DIA_TABLA: 100, COL_POR_ACTUALIZAR_TABLA: 150, COL_SIN_PAGO_TABLA: 115}
    ANCHOS_DETALLE = {
        'ID': 80, COL_ACTIVACION_TABLA: 130, 'ESTADO COMERCIAL': 125, 'VIN': 165, 'CHASIS': 90, 'N CONTRATO 3PC': 125, 'FECHA INICIO CM': 115, 'FECHA TERMINO CM': 120,
        'TIPO DE CM': 95, 'ESTADO DEL CM': 105, 'PAGO CM': 100,
        COL_ULTIMO_PAGO_CM: 115, COL_FECHA_ULTIMO_PAGO_CM: 130,
    }

    def _pintar_tabla(self):
        """Sin scroll lateral: los anchos de ANCHOS_* son proporciones que se reparten en el ancho disponible."""
        super()._pintar_tabla()
        columnas = list(self.modelo.get_df().columns)
        if self.empresa_actual is None and self.current_kpi_filter in _COLAS_CM and COL_RAZON_SOCIAL in columnas:
            self.tabla.setColumnHidden(columnas.index(COL_RAZON_SOCIAL), True)
        self.tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabla.horizontalHeader().setStretchLastSection(False)
        if not self.__dict__.get('_filtro_ancho_instalado'):
            self._filtro_ancho_instalado = True
            self.tabla.viewport().installEventFilter(self)
        self._ajustar_ancho_tabla()

    def _ajustar_ancho_tabla(self):
        columnas = list(self.modelo.get_df().columns)
        anchos = self.ANCHOS_EMPRESAS if self.empresa_actual is None else self.ANCHOS_DETALLE
        visibles = [i for i in range(len(columnas)) if not self.tabla.isColumnHidden(i)]
        disponible = self.tabla.viewport().width()
        base = [anchos.get(columnas[i], 140) for i in visibles]
        if not visibles or disponible <= 0 or not sum(base):
            return
        factor = disponible / sum(base)
        usado = 0
        for pos, i in enumerate(visibles):
            ancho = disponible - usado if pos == len(visibles) - 1 else max(60, round(base[pos] * factor))
            self.tabla.setColumnWidth(i, ancho)
            usado += ancho

    def eventFilter(self, obj, event):
        # Este filtro también está instalado en toda la aplicación: puede recibir eventos de una pantalla ya vaciada
        tabla = self.__dict__.get('tabla')
        if tabla is not None and obj is tabla.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._ajustar_ancho_tabla)
        return super().eventFilter(obj, event)

    def __init__(self):
        super().__init__()
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.search_input = QLineEdit()
        self.search_input.hide()
        self.search_input.textChanged.connect(self.filter_table)
        self.current_kpi_filter = "total"  # al entrar queda marcado Total Conectados
        self.filtro_estado_cm = None
        self.filtro_tipo_cm = None
        self.filtro_precio = None
        self._vins_ausentes = set()
        self._vins_visibles = set()
        self._casos_a_cerrar = []
        self._vins_forma_no_cm = set()
        self._vins_activos = set()
        self._vins_datos_vacios = set()
        self.pending_changes = {}  # Mochila de edición manual (indexada por VIN)
        self.import_changes = {}   # Mochila de importación masiva
        self._data_dirty = False

        self.data_manager.data_ready.connect(self._on_global_data_ready)
        self.data_manager.load_error.connect(self._on_load_error)

        self._setup_ui()
        self.load_data()

    def _setup_ui(self):
        self.construir_base()

        self.combo_estado_cm = ComboFiltroBarra('fa5s.flag', "Estado del CM", multiple=True)
        self.combo_tipo_cm = ComboFiltroBarra('fa5s.tag', "Tipo de CM", multiple=True)
        self.combo_precio = ComboFiltroBarra('fa5s.dollar-sign', "Precio", multiple=True)
        for combo, ancho in ((self.combo_estado_cm, 170), (self.combo_tipo_cm, 160), (self.combo_precio, 150)):
            combo.setMinimumWidth(ancho)
            ThemeManager.apply_combo_box(combo)
            combo.setStyleSheet(estilo_combo_barra())
            combo.setMaxVisibleItems(9)
            self.agregar_filtro_compacto(combo)
        self.combo_estado_cm.seleccion_cambiada.connect(self._on_combo_estado_cm)
        self.combo_tipo_cm.seleccion_cambiada.connect(self._on_combo_tipo_cm)
        self.combo_precio.seleccion_cambiada.connect(self._on_combo_precio)

        self.btn_importar = boton_barra("", 'fa5s.plus')
        self.btn_importar.setToolTip("Importar Excel CM")
        self.btn_importar.clicked.connect(self.importar_excel_javiera)
        self.agregar_capsula(self.btn_importar)

        self.btn_pasar_todos = boton_barra("", 'fa5s.exchange-alt')
        self.btn_pasar_todos.clicked.connect(self._on_pasar_a_cm_todos_clicked)
        self.btn_pasar_todos.hide()
        self.agregar_capsula(self.btn_pasar_todos)

        self.btn_actualizar_todos = boton_barra("", 'fa5s.check-double')
        self.btn_actualizar_todos.clicked.connect(self._on_actualizar_estado_todos_clicked)
        self.btn_actualizar_todos.hide()
        self.agregar_capsula(self.btn_actualizar_todos)

        self.btn_export_excel = boton_barra("", 'fa5s.file-excel', 'excel')
        self.btn_export_excel.setToolTip("Exportar a Excel el detalle de todos los contratos de la lista")
        self.btn_export_excel.setFixedWidth(44)
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='#1B2B4E'))
        self.btn_export_excel.clicked.connect(self._exportar_detalle_excel)
        self.agregar_general(self.btn_export_excel)

        self.btn_reload = boton_barra("", 'fa5s.sync-alt')
        self.btn_reload.setToolTip("Recargar")
        self.btn_reload.clicked.connect(self.recargar_desde_cero)
        # Acciones rápidas con el mismo estilo que las de Comercial (grilla de a dos, se ocultan si no aplican)
        self._panel_botones = estilo_com.PanelAcciones(maestro=True)
        grilla = estilo_com.GrillaAcciones(self._panel_botones, impar_largo=True)
        self.btn_pasar_a_cm = self._boton_accion(
            'fa5s.exchange-alt', 'Pasar a CM', "Forma CMG, CMB o CMS y facturación CM según el tipo de CM", VOLVO_BLUE)
        self.btn_limpiar_cm = self._boton_accion(
            'fa5s.eraser', 'Limpiar datos CM', "Deja en '-' los datos del 3PC de contratos que ya no son CM", estilo_com.ROJO)
        self.btn_actualizar_estado = self._boton_accion(
            'fa5s.check-double', 'Marcar vigente', "Vigente si pagó este mes y está conectada; Vencido si estaba en Revisar y no pagó",
            estilo_com.VERDE)
        self.btn_extender = self._boton_accion(
            'fa5s.redo-alt', 'Extender duración', "Suma meses al contrato y recalcula su término", estilo_com.VERDE)
        self.btn_enviar_operaciones = self._boton_accion(
            'fa5s.bolt', 'Enviar a operaciones', "Pasa a Baja y deriva la unidad a Operaciones", estilo_com.AMBAR)
        self.btn_avisar = self._boton_accion(
            'fa5s.envelope', 'Avisar al cliente', "Correo de aviso de vencimiento", estilo_com.AZUL)
        self.btn_confirmar_baja = self._boton_accion(
            'fa5s.check-circle', 'Confirmar baja', "Deja el CM en Terminated y pasa el contrato a Baja", estilo_com.ROJO)
        self.btn_marcar_expired = self._boton_accion(
            'fa5s.calendar-times', 'Expired y Vencido',
            "Marca como Expired y Vencido un CM Running con el término vencido y sin pago este mes", estilo_com.ROJO)
        self.btn_editar_unidad = self._boton_accion(
            'fa5s.file-contract', 'Editar contrato', "Abre el formulario del contrato", estilo_com.VIOLETA)
        manejadores = ((self.btn_pasar_a_cm, self._on_pasar_a_cm_clicked),
                       (self.btn_limpiar_cm, self._on_limpiar_cm_clicked),
                       (self.btn_actualizar_estado, self._on_actualizar_estado_clicked),
                       (self.btn_extender, self._on_extender_clicked),
                       (self.btn_enviar_operaciones, self._on_enviar_operaciones_clicked),
                       (self.btn_avisar, self._on_avisar_clicked),
                       (self.btn_confirmar_baja, self._on_confirmar_baja_clicked),
                       (self.btn_marcar_expired, self._on_marcar_expired_clicked),
                       (self.btn_editar_unidad, self._on_editar_unidad_clicked))
        for boton, manejador in manejadores:
            boton.setEnabled(False)
            boton.clicked.connect(manejador)
            grilla.agregar(boton)
        self.agregar_accion_panel(self._panel_botones)

        # --- MOTOR DE DATOS OCULTO ---
        # self.table/self.model nunca se agregan a un layout visible: siguen
        # siendo el mismo motor de on_item_edited/confirm_save de antes (ver
        # docstring de la clase) y también alimentan 'Exportar Excel'
        # (VolvoTableWidget.export_to_excel), reutilizado sin duplicar su
        # lógica de formato de columnas monetarias.
        self.table = VolvoTableWidget()
        self.model = PandasTableModel()
        opciones_desplegables = {
            'TIPO DE CM': TIPO_CM_OPCIONES,
            'ESTADO DEL CM': ESTADO_CM_OPCIONES,
        }
        self.table.set_model_and_delegate(self.model, opciones_desplegables)

        # Pantalla de carga: la bandeja (barra + tabla) y la tarjeta de carga
        # comparten un QStackedWidget (0 = cargando, 1 = contenido)
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tarjeta_carga = crear_tarjeta_carga("Procesando datos en segundo plano…", "Esto tomará unos segundos.")
        self.lbl_loading_text = tarjeta_carga.lbl
        loading_layout.addWidget(tarjeta_carga, alignment=Qt.AlignmentFlag.AlignCenter)
        main_layout = self.layout()
        main_layout.removeWidget(self._contenido)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.loading_widget)  # Index 0
        self.stack.addWidget(self._contenido)      # Index 1
        main_layout.addWidget(self.stack, 1)
        self.stack.setCurrentIndex(1)

    # --------------------------------------------- ganchos de la pantalla base
    def resolver_color(self, columna, valor, es_fondo):
        en_forma_incorrecta = self.empresa_actual is None and self.current_kpi_filter == "forma_incorrecta"
        if columna in ('TIPO DE CM', 'ESTADO DEL CM') or (
                en_forma_incorrecta and columna in (COL_FORMA_ACTUAL_TABLA, COL_FACTURACION_ACTUAL_TABLA)):
            if str(valor).strip() in ("", "-"):
                return None
            colores = _BADGE_COLOR.get(str(valor).strip().upper(), _BADGE_COLOR_DEFAULT)
            return colores[0] if es_fondo else colores[1]
        if columna == COL_CONTRATOS_TABLA:
            return _CHIP_VOLVO[0 if es_fondo else 1]
        if columna == COL_CDB_FLOTA and self.empresa_actual is None and self.modelo.valor_fila_resuelta(COL_CDB_VARIOS) == "1":
            return _CHIP_CDB_VARIOS[0 if es_fondo else 1]
        if columna == COL_ACTIVACION_TABLA:
            colores = _CHIPS_ACTIVACION.get(str(valor).strip().upper())
            return colores[0 if es_fondo else 1] if colores else None
        if columna in _CHIPS_CONTEO_EMPRESAS and str(valor).strip() not in ("", "0"):
            return _CHIPS_CONTEO_EMPRESAS[columna][0 if es_fondo else 1]
        return None

    def colores_chip_ficha(self, columna, valor):
        if columna in ('TIPO DE CM', 'ESTADO DEL CM'):
            return _BADGE_COLOR.get(str(valor).strip().upper(), _BADGE_COLOR_DEFAULT)
        return None

    def on_kpi_clicado(self, clave):
        self.current_kpi_filter = "total" if self.current_kpi_filter == clave else clave
        if self.empresa_actual is not None:
            self.ir_a_lista_empresas()
        else:
            self.filter_table()

    def _on_combo_estado_cm(self):
        valor = self.combo_estado_cm.valores()
        if valor != self.filtro_estado_cm:
            self.filtro_estado_cm = valor
            self.filter_table()

    def _on_combo_tipo_cm(self):
        valor = self.combo_tipo_cm.valores()
        if valor != self.filtro_tipo_cm:
            self.filtro_tipo_cm = valor
            self.filter_table()

    def _on_combo_precio(self):
        valor = self.combo_precio.valores()
        if valor != self.filtro_precio:
            self.filtro_precio = valor
            self.filter_table()

    @staticmethod
    def _precios(df):
        """Pago CM de cada contrato como texto (lo que muestra la columna PAGO CM); '-' si no tiene pago."""
        columna = 'PAGO CM_NUM' if 'PAGO CM_NUM' in df.columns else 'PAGO CM'
        precio = pd.to_numeric(df[columna], errors='coerce').fillna(0) if columna in df.columns else pd.Series(0.0, index=df.index)
        return precio.round().astype(int).astype(str).where(precio > 0, '-')

    @staticmethod
    def _boton_accion(icono, titulo, subtitulo, color):
        """Misma acción rápida que usa Comercial: ícono en recuadro, título y ayuda en el tooltip."""
        btn = estilo_com.BotonAccionRapida(color, ocultar_si_bloqueado=True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(36)
        btn.setToolTip(subtitulo)
        lay = QHBoxLayout(btn)
        lay.setContentsMargins(6, 4, 10, 4)
        lay.setSpacing(8)
        marco = QFrame()
        marco.setFixedSize(26, 26)
        marco.setStyleSheet(estilo_com.qss_icono_accion(color))
        lay_marco = QVBoxLayout(marco)
        lay_marco.setContentsMargins(0, 0, 0, 0)
        lbl_icono = QLabel()
        lbl_icono.setPixmap(ThemeManager.icon_pixmap(icono, color=color, size=12))
        lbl_icono.setStyleSheet("background: transparent; border: none;")
        lay_marco.addWidget(lbl_icono, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(marco)
        btn._icono_frame = marco
        btn._icono_lbl = lbl_icono
        btn._titulo_lbl = QLabel(titulo)
        btn._titulo_lbl.setToolTip(subtitulo)
        btn._titulo_lbl.setStyleSheet(
            f"color: {estilo_com.TINTA}; font-weight: bold; font-size: 12px; background: transparent; border: none;")
        lay.addWidget(btn._titulo_lbl, stretch=1)
        return btn

    def on_fila_cambiada(self, fila, cantidad):
        if cantidad == 0:
            for boton in (self.btn_editar_unidad, self.btn_enviar_operaciones, self.btn_pasar_a_cm, self.btn_limpiar_cm,
                          self.btn_avisar, self.btn_confirmar_baja, self.btn_actualizar_estado, self.btn_extender,
                          self.btn_marcar_expired):
                boton.setEnabled(False)
            return
        avisos = []
        vin = str(fila.get('VIN', '')).strip().upper()
        if vin in self._vins_ausentes:
            avisos.append("⚠  Ausente de la última carga del Excel 3PC. Revisa si corresponde darla de baja.")
        if vin in self._vins_forma_no_cm:
            forma = str(fila.get(COL_FORMA_CONTRATO, '')).strip() or "otra distinta de CM"
            avisos.append(f"⚠  Trae un CM {fila.get('TIPO DE CM', '')} en el 3PC, pero su forma de contrato es "
                          f"{forma}. La importación no la cambia: revisa si corresponde.")
        self._pintar_panel(fila, cantidad, "\n".join(avisos))
        self.btn_editar_unidad.setEnabled(cantidad == 1)
        self.btn_enviar_operaciones.setEnabled(True)
        self.btn_avisar.setEnabled(True)
        cambios_cm = self._cambios_pasar_a_cm()
        self.btn_pasar_a_cm.setEnabled(bool(cambios_cm))
        formas = {c[COL_FORMA_CONTRATO] for c in cambios_cm.values()}
        self.btn_pasar_a_cm._titulo_lbl.setText(f"Pasar a {formas.pop()}" if len(formas) == 1 else "Pasar a CM")
        self.btn_limpiar_cm.setEnabled(bool(self._cambios_limpiar_cm()))
        self.btn_confirmar_baja.setEnabled(any(v.upper() in self._vins_ausentes for v in self._vins_seleccionados()))
        cambios_estado = self._cambios_estado_por_pago()
        self.btn_actualizar_estado.setEnabled(bool(cambios_estado))
        destinos = set(cambios_estado.values())
        self.btn_actualizar_estado._titulo_lbl.setText(
            f"Marcar {destinos.pop().lower()}" if len(destinos) == 1 else "Actualizar estado")
        self.btn_extender.setEnabled(bool(self._filas_extensibles()))
        self.btn_marcar_expired.setEnabled(bool(self._vins_running_terminados()))

    def al_cambiar_nivel(self):
        self.filter_table()

    def recargar_desde_cero(self):
        self.btn_reload.setEnabled(False)
        self.btn_importar.setEnabled(False)

        self.lbl_loading_text.setText("Recargando la base de datos maestra desde cero...")
        self.stack.setCurrentIndex(0)

        QApplication.processEvents()
        self.data_manager.load_data_async()

        QTimer.singleShot(12000, self._force_unlock_buttons)

    def _force_unlock_buttons(self):
        if not self.btn_reload.isEnabled():
            self.btn_reload.setEnabled(True)
            self.btn_importar.setEnabled(True)
            self.stack.setCurrentIndex(1)
            logger.debug("Seguro Anti-Congelamiento activado en Contratos.")

    def _on_global_data_ready(self):
        try:
            if self.isVisible():
                self.load_data()
            else:
                self._data_dirty = True
        except Exception:
            pass
        finally:
            self.btn_reload.setEnabled(True)
            self.btn_importar.setEnabled(True)
            self.stack.setCurrentIndex(1)

    def refresh_if_dirty(self):
        """Llamado por MainWindow._trigger_load_data al navegar a este
        modulo. Protege pending_changes con el mismo patron de dialogo de 3
        opciones que usa ComercialModule/OperacionesModule."""
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
        msg.setText("La base de datos cambió mientras tenías cambios sin guardar en Contratos.")
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

    def _on_load_error(self, error_msg):
        self.btn_reload.setEnabled(True)
        self.btn_importar.setEnabled(True)
        self.stack.setCurrentIndex(1)
        QMessageBox.critical(self, "Error al Cargar", f"Ocurrió un problema:\n{error_msg}")

    # =========================================================
    # CARGA DE DATOS: siempre desde DataManager().df_master, ya en RAM.
    # self.df_base ya viene recortado al universo real de contratos
    # (contratos_service.filtrar_con_contrato) -- reemplaza al viejo
    # checkbox 'Ocultar sin contrato (-)', que por defecto siempre estaba
    # activado.
    # =========================================================
    def _leer_vins_casos(self, origen):
        """VIN con un caso pendiente de CasosBajaCM.csv con ese origen (ver cm_bajas_service): 'Ausencia de 3PC'
        (estaban en el RM con CM y no vinieron en la última carga) o 'Datos 3PC vacíos'."""
        try:
            df_casos = cm_bajas_service.leer_casos_baja_cm(config.settings.CASOS_BAJA_CM_PATH)
        except Exception as e:
            logger.error(f"No se pudieron leer los casos de baja CM: {e}")
            return set()
        if df_casos.empty:
            return set()
        mascara = (df_casos['ESTADO_CASO'] == cm_bajas_service.ESTADO_CASO_PENDIENTE) & (df_casos['ORIGEN_CASO'] == origen)
        return {str(v).strip().upper() for v in df_casos.loc[mascara, 'VIN']}

    def _leer_vins_ausentes(self):
        return self._leer_vins_casos(cm_bajas_service.ORIGEN_CASO_AUSENCIA_3PC)

    def load_data(self):
        self._data_dirty = False
        self.pending_changes.clear()
        df_master = comercial_services.excluir_contratos_cerrados(
            self.data_manager.get_contratos_actuales_df())
        self._vins_ausentes = self._leer_vins_ausentes()
        self._vins_datos_vacios = self._leer_vins_casos(cm_bajas_service.ORIGEN_CASO_DATOS_3PC_VACIOS)
        if df_master.empty:
            self.df_base = pd.DataFrame()
            self.model.set_data(pd.DataFrame())
            self._vins_activos = set()
        else:
            df_base_completo = ct_service.preparar_base_contratos(df_master)
            # Las unidades CM a las que el 3PC dejó sin datos no tienen N° de contrato, pero cuentan en Baja de CM
            con_contrato = ct_service.filtrar_con_contrato(df_base_completo)
            vin_completo = df_base_completo['VIN'].astype(str).str.strip().str.upper()
            vacios = df_base_completo[vin_completo.isin(self._vins_datos_vacios) & ~df_base_completo.index.isin(con_contrato.index)]
            self.df_base = pd.concat([con_contrato, vacios]) if not vacios.empty else con_contrato
            if COL_ESTADO_ACTIVACION in df_master.columns:
                activa = df_master[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper().isin(('CONECTADO', 'ACTIVANDO'))
                self._vins_activos = set(df_master.loc[activa, 'VIN'].astype(str).str.strip().str.upper())
            else:
                self._vins_activos = set()
        self._vins_forma_no_cm = ct_service.unidades_forma_no_es_cm(self.df_base)

        empresas_disponibles = set(ct_service.obtener_empresas(self.df_base)[COL_RAZON_SOCIAL]) if not self.df_base.empty else set()
        if self.empresa_actual is not None and self.empresa_actual not in empresas_disponibles:
            self.empresa_actual = None
            self.actualizar_titulo()
        self.filter_table()

    def _poblar_filtros(self, df_global):
        """Estado, tipo y precio se encadenan: cada uno ofrece solo lo compatible con los otros dos, y lo marcado
        que deja de existir se suelta."""
        def compatible(excepto):
            d = df_global
            if excepto != 'estado' and self.filtro_estado_cm is not None and 'ESTADO DEL CM' in d.columns:
                d = d[d['ESTADO DEL CM'].isin(self.filtro_estado_cm)]
            if excepto != 'tipo' and self.filtro_tipo_cm is not None and 'TIPO DE CM' in d.columns:
                d = d[d['TIPO DE CM'].isin(self.filtro_tipo_cm)]
            if excepto != 'precio' and self.filtro_precio is not None:
                d = d[self._precios(d).isin(self.filtro_precio)]
            return d

        for _ in range(3):
            if 'ESTADO DEL CM' in df_global.columns:
                self._poblar_combo(self.combo_estado_cm, compatible('estado')['ESTADO DEL CM'], "Todos los estados", None)
            if 'TIPO DE CM' in df_global.columns:
                self._poblar_combo(self.combo_tipo_cm, compatible('tipo')['TIPO DE CM'], "Todos los tipos", None,
                                   etiquetas={tipo: forma for tipo, forma in TIPO_CM_FORMA_CONTRATO_MAP.items()})
            precios = self._precios(compatible('precio'))
            conteo = precios[precios != '-'].value_counts()
            opciones_precio = [(p, f"{_formato_pago(int(p))} ({conteo[p]})") for p in sorted(conteo.index, key=int)]
            sin_precio = int((precios == '-').sum())
            if sin_precio:
                opciones_precio.append(('-', f"$- Sin pago ({sin_precio})"))
            self.combo_precio.set_opciones_multiples("Todos los precios", opciones_precio)
            nuevos = (self.combo_estado_cm.valores(), self.combo_tipo_cm.valores(), self.combo_precio.valores())
            if nuevos == (self.filtro_estado_cm, self.filtro_tipo_cm, self.filtro_precio):
                break
            self.filtro_estado_cm, self.filtro_tipo_cm, self.filtro_precio = nuevos

    def _poblar_combo(self, combo, serie, titulo_todos, valor_actual, etiquetas=None):
        etiquetas = etiquetas or {}
        opciones = [(str(valor), f"{etiquetas.get(str(valor), valor)} ({cantidad})") for valor, cantidad in serie.value_counts().items()
                    if str(valor).strip() not in ("", "-")]
        combo.set_opciones_multiples(titulo_todos, opciones)

    def filter_table(self):
        if not hasattr(self, 'df_base') or self.df_base.empty:
            self.model.set_data(pd.DataFrame())
            for clave, tarjeta in self.botones_kpi.items():
                tarjeta.setChecked(False)
                tarjeta.actualizar("$-" if clave == "pago" else 0, None if clave == "pago" else 0.0, "")
            self._df_tabla = pd.DataFrame(columns=_COLUMNAS_EMPRESAS_CM)
            self._fila_por_vin = {}
            self.lbl_subtitulo.setText("0 empresas · 0 contratos")
            self.lbl_sin_resultados.setVisible(True)
            self._pintar_tabla()
            return

        df_global = self.df_base.copy()

        search_text = self.search_input.text().lower()
        if search_text:
            # RUT agregado 28-09-2026, a pedido explicito.
            cols = [c for c in ['VIN', 'CHASIS', COL_RAZON_SOCIAL, COL_RUT, 'FLOTA VC'] if c in df_global.columns]
            mask = comercial_services.construir_mascara_busqueda(
                df_global, search_text.strip(), cols, ('ID',))
            df_global = df_global[mask]

        situacion = ct_service.clasificar_situacion_pago(df_global)
        total_dinero = df_global[df_global['PAGO CM_NUM'] > 0]['PAGO CM_NUM'].sum() if 'PAGO CM_NUM' in df_global.columns else 0
        # Las cuatro tarjetas reparten Total Conectados sin repetir unidades: sus porcentajes suman 100
        categoria = ct_service.clasificar_kpi_cm(df_global, self._vins_activos,
                                                 self._vins_ausentes | self._vins_datos_vacios)
        claves = (ct_service.KPI_PENDIENTE, ct_service.KPI_BAJA, ct_service.KPI_AL_DIA, ct_service.KPI_FORMA_DISTINTA)
        cantidades = [int((categoria == c).sum()) for c in claves]
        porcentajes = dict(zip(claves, ct_service.porcentajes_enteros(cantidades)))
        conteo = dict(zip(claves, cantidades))
        total_activos = int((categoria != "").sum())
        pies = {ct_service.KPI_PENDIENTE: "aún en Activación Pendiente", ct_service.KPI_BAJA: "sin pago, fuera o vacíos en 3PC",
                ct_service.KPI_AL_DIA: "forma CM, pagadas este mes",
                ct_service.KPI_FORMA_DISTINTA: "Provisión o Conversión"}
        valores = {
            "total": (total_activos, 1.0 if total_activos else 0.0, "conectados y activando"),
            "pago": (_formato_pago(total_dinero), None, "suma de pagos CM"),
        }
        for c in claves:
            valores[c] = (conteo[c], porcentajes[c] / 100, pies[c])
        for clave, tarjeta in self.botones_kpi.items():
            valor, porcentaje, pie = valores[clave]
            tarjeta.setChecked(clave == self.current_kpi_filter)
            tarjeta.actualizar(valor, porcentaje, pie)

        self._poblar_filtros(df_global)

        df_f = df_global.copy()
        if self.current_kpi_filter == "total":
            df_f = df_f[categoria != ""]
        elif self.current_kpi_filter in claves:
            df_f = df_f[categoria == self.current_kpi_filter]
        elif self.current_kpi_filter == "pago":
            df_f = df_f[df_f['PAGO CM_NUM'] > 0]
        if self.filtro_estado_cm is not None and 'ESTADO DEL CM' in df_f.columns:
            df_f = df_f[df_f['ESTADO DEL CM'].isin(self.filtro_estado_cm)]
        if self.filtro_tipo_cm is not None and 'TIPO DE CM' in df_f.columns:
            df_f = df_f[df_f['TIPO DE CM'].isin(self.filtro_tipo_cm)]
        if self.filtro_precio is not None:
            df_f = df_f[self._precios(df_f).isin(self.filtro_precio)]

        # --- APLICAMOS LA PERSISTENCIA DE EDICIÓN AL DATAFRAME ---
        if self.pending_changes:
            for vin_key, data in self.pending_changes.items():
                mask = df_f['VIN'].astype(str).str.strip().str.upper() == vin_key
                if mask.any():
                    for col_c, val_c in data['cambios'].items():
                        if col_c in df_f.columns:
                            df_f[col_c] = df_f[col_c].astype(object)
                            df_f.loc[mask, col_c] = val_c

        if 'FECHA INICIO CM' in df_f.columns:
            df_f['_FECHA_SORT'] = pd.to_datetime(df_f['FECHA INICIO CM'], format='%d-%m-%Y', errors='coerce')
            df_f = df_f.sort_values(by='_FECHA_SORT', ascending=False, na_position='last')
            df_f = df_f.drop(columns=['_FECHA_SORT'])

        df_f['SITUACION_PAGO'] = situacion.reindex(df_f.index)
        if 'PAGO CM' in df_f.columns:
            df_f['PAGO CM'] = df_f['PAGO CM_NUM'].apply(_formato_pago)

        df_display = df_f.drop(columns=['PAGO CM_NUM'], errors='ignore')
        df_display.insert(0, 'N°', range(1, len(df_display) + 1))

        self.model.set_data(df_display)

        # --- REPINTAMOS DE NARANJA LAS CELDAS QUE HABÍAN SIDO EDITADAS (bookkeeping interno, sin tabla visible) ---
        if self.pending_changes:
            for r in range(len(df_display)):
                v_val = str(df_display.iat[r, df_display.columns.get_loc('VIN')]).strip().upper()
                if v_val in self.pending_changes:
                    for c_name in self.pending_changes[v_val]['cambios']:
                        if c_name in df_display.columns:
                            c_idx = df_display.columns.get_loc(c_name)
                            self.model._edited_cells.add((r, c_idx))

        # --- TABLA VISIBLE: mismas filas de df_display, mismas posiciones (0-based) que usa el modelo ---
        df_posicional = df_display.reset_index(drop=True)
        if self.empresa_actual is None:
            df_empresas = ct_service.obtener_empresas(df_posicional)
            self._df_tabla = (self._armar_tabla_flotas(df_empresas, df_posicional) if self.current_kpi_filter in _COLAS_CM
                              else self._armar_tabla_empresas(df_empresas))
            self._vins_visibles = {str(v).strip().upper() for v in df_posicional['VIN']}
            self.lbl_subtitulo.setText(f"{len(df_empresas)} empresas · {len(df_posicional)} contratos")
        else:
            df_contratos = ct_service.obtener_contratos_empresa(df_posicional, self.empresa_actual)
            self._df_tabla = self._armar_tabla_contratos(df_contratos)
            self._vins_visibles = {str(v).strip().upper() for v in df_contratos['VIN']} if 'VIN' in df_contratos.columns else set()
            self.lbl_subtitulo.setText(f"{len(df_contratos)} contratos")
        self._actualizar_boton_pasar_todos()
        self.lbl_sin_resultados.setVisible(self._df_tabla.empty)
        self._pintar_tabla()

    @staticmethod
    def _resumen_por_empresa(df, columna, etiquetas=None, con_conteo=True):
        """Por empresa, los valores de la columna con su cantidad ("CMG 3 · CMB 1"), o solo los valores si `con_conteo` es False."""
        if columna not in df.columns or df.empty:
            return {}
        valores = df[[COL_RAZON_SOCIAL, columna]].copy()
        valores[columna] = valores[columna].astype(str).str.strip().replace({"": "-", "nan": "-"})
        if etiquetas:
            valores[columna] = valores[columna].map(lambda v: etiquetas.get(v, v))
        conteo = valores.groupby([COL_RAZON_SOCIAL, columna]).size().reset_index(name="_n")
        conteo = conteo.sort_values([COL_RAZON_SOCIAL, "_n", columna], ascending=[True, False, True])
        conteo["_txt"] = conteo[columna] + (" " + conteo["_n"].astype(str) if con_conteo else "")
        return conteo.groupby(COL_RAZON_SOCIAL)["_txt"].agg(" · ".join).to_dict()

    @staticmethod
    def _ultimo_pago_por_empresa(df):
        if COL_FECHA_ULTIMO_PAGO_CM not in df.columns or df.empty:
            return {}
        fechas = pd.to_datetime(df[COL_FECHA_ULTIMO_PAGO_CM], dayfirst=True, errors="coerce")
        ultimo = fechas.groupby(df[COL_RAZON_SOCIAL]).max().dropna()
        return ultimo.dt.strftime("%d-%m-%Y").to_dict()

    def _armar_tabla_flotas(self, df_empresas, df_contratos):
        """Fase 1 de las colas: flota, empresa y contratos, más lo que importa en cada cola (ya afectada por la búsqueda)."""
        self._fila_por_vin = {}
        extras = _EXTRAS_COLA_CM.get(self.current_kpi_filter, ())
        if df_empresas.empty:
            return pd.DataFrame(columns=_COLUMNAS_FLOTAS_CM + list(extras))
        empresas = df_empresas[COL_RAZON_SOCIAL]
        tablas = {
            COL_FLOTA_VC_TABLA: df_empresas["FLOTA_VC"].astype(str).tolist(),
            COL_RAZON_SOCIAL: empresas.astype(str).tolist(),
            COL_CDB_FLOTA: df_empresas[COL_CDB_FLOTA].astype(str).tolist(),
            COL_CONTRATOS_TABLA: df_empresas["UNIDADES"].astype(int).astype(str).tolist(),
            COL_CDB_VARIOS: df_empresas["CDB_VARIOS"].map({True: "1", False: ""}).tolist(),
        }
        con_conteo = self.current_kpi_filter != "forma_incorrecta"
        fuentes = {
            COL_FORMA_ACTUAL_TABLA: lambda: self._resumen_por_empresa(df_contratos, COL_FORMA_CONTRATO, con_conteo=con_conteo),
            COL_FACTURACION_ACTUAL_TABLA: lambda: self._resumen_por_empresa(
                df_contratos, COL_TIPO_FACTURACION, con_conteo=con_conteo),
            COL_TIPO_CM_TABLA: lambda: self._resumen_por_empresa(
                df_contratos, 'TIPO DE CM', TIPO_CM_FORMA_CONTRATO_MAP, con_conteo=con_conteo),
            COL_ESTADO_ACTUAL_TABLA: lambda: self._resumen_por_empresa(df_contratos, COL_ESTADO_COMERCIAL),
            COL_ULTIMO_PAGO_TABLA: lambda: self._ultimo_pago_por_empresa(df_contratos),
        }
        for extra in extras:
            valores = fuentes[extra]()
            tablas[extra] = [valores.get(e, "-") for e in empresas]
        return pd.DataFrame(tablas, columns=_COLUMNAS_FLOTAS_CM + list(extras))

    def _actualizar_boton_pasar_todos(self):
        """"Pasar a CM los N": solo en la cola "CM Pagado, forma de contrato distinta", con los contratos de la lista
        que se ve."""
        visible = self.current_kpi_filter == "forma_incorrecta"
        cantidad = len(self._cambios_pasar_a_cm(self._vins_visibles)) if visible else 0
        self.btn_pasar_todos.setVisible(visible and cantidad > 0)
        self.btn_pasar_todos.setToolTip(
            f"Pasar a CM los {cantidad}: pasa a CMG, CMB o CMS todos los contratos que se ven en la lista (con resumen antes de guardar)")
        visible = self.current_kpi_filter == "por_actualizar"
        cantidad = len(self._cambios_estado_por_pago(self._vins_visibles)) if visible else 0
        self.btn_actualizar_todos.setVisible(visible and cantidad > 0)
        self.btn_actualizar_todos.setToolTip(
            f"Actualizar estado de los {cantidad}: Vigente si pagó este mes y está conectada; Vencido si estaba en Revisar y no pagó")

    def _armar_tabla_empresas(self, df_empresas):
        self._fila_por_vin = {}
        if df_empresas.empty:
            return pd.DataFrame(columns=_COLUMNAS_EMPRESAS_CM)
        ruts = df_empresas[COL_RUT].astype(str).tolist() if COL_RUT in df_empresas.columns else [""] * len(df_empresas)
        return pd.DataFrame({
            COL_FLOTA_VC_TABLA: df_empresas["FLOTA_VC"].astype(str).tolist(),
            COL_RAZON_SOCIAL: df_empresas[COL_RAZON_SOCIAL].astype(str).tolist(),
            COL_RUT: ruts,
            COL_CDB_FLOTA: df_empresas[COL_CDB_FLOTA].astype(str).tolist(),
            COL_CONTRATOS_TABLA: df_empresas["UNIDADES"].astype(int).astype(str).tolist(),
            COL_AL_DIA_TABLA: df_empresas["AL_DIA"].astype(int).astype(str).tolist(),
            COL_POR_ACTUALIZAR_TABLA: df_empresas["POR_ACTUALIZAR"].astype(int).astype(str).tolist(),
            COL_SIN_PAGO_TABLA: df_empresas["SIN_PAGO"].astype(int).astype(str).tolist(),
            COL_CDB_VARIOS: df_empresas["CDB_VARIOS"].map({True: "1", False: ""}).tolist(),
        }, columns=_COLUMNAS_EMPRESAS_CM)

    def _armar_tabla_contratos(self, df_contratos):
        self._fila_por_vin = {}
        if df_contratos.empty:
            return pd.DataFrame(columns=_COLUMNAS_DETALLE_CM)
        origen = {COL_ACTIVACION_TABLA: COL_ESTADO_ACTIVACION}
        df = pd.DataFrame({col: (df_contratos[origen.get(col, col)].astype(str).tolist() if origen.get(col, col) in df_contratos.columns
                                 else ["-"] * len(df_contratos)) for col in _COLUMNAS_DETALLE_CM})
        df[COL_ULTIMO_PAGO_CM] = [
            _formato_pago(float(v)) if pd.notna(pd.to_numeric(v, errors='coerce')) else '-' for v in df[COL_ULTIMO_PAGO_CM]]
        for pos, (row_idx, fila) in enumerate(df_contratos.iterrows()):
            registro = df.iloc[pos].to_dict()
            registro[COL_RAZON_SOCIAL] = self.empresa_actual
            registro['ESTADO COMERCIAL'] = str(fila.get('ESTADO COMERCIAL', '')).strip()
            registro['TIPO DE SERVICIO'] = str(fila.get('TIPO DE SERVICIO', '')).strip()
            registro[COL_FORMA_CONTRATO] = str(fila.get(COL_FORMA_CONTRATO, '')).strip()
            registro[COL_TIPO_FACTURACION] = str(fila.get(COL_TIPO_FACTURACION, '')).strip()
            registro['_ROW_IDX'] = int(row_idx)
            self._fila_por_vin[str(registro['VIN']).strip()] = registro
        return df

    def _abrir_form_contrato(self, row_idx, fila):
        """Mismo formulario de unidad que Comercial (formulario_unidad.py),
        abierto en "JustTime & CM" con Operaciones de solo lectura."""
        if comercial_services.es_contrato_cerrado(fila.get('ESTADO COMERCIAL', '')):
            QMessageBox.information(
                self, "Contrato finalizado",
                "Este contrato está en Baja y es de solo lectura. Si la unidad sigue conectada, Operaciones debe desconectarla.")
            return
        cambios = editar_unidad(self, self.data_manager.get_contratos_actuales_df(), fila.get('VIN', ''), PESTANA_JUSTTIME_CM)
        if cambios is None:
            return
        if not cambios:
            QMessageBox.information(self, "Sin cambios", "No se modificó ningún campo.")
            return
        self._aplicar_cambios_formulario(row_idx, cambios)

    def _aplicar_cambios_formulario(self, row_idx, cambios):
        """Aplica los campos del formulario reutilizando on_item_edited (uno
        por columna, mismo mecanismo que una edicion de celda) y termina con
        confirm_save()."""
        for col_name, new_value in cambios.items():
            self.on_item_edited(row_idx, col_name, new_value)
        self.confirm_save()

    # =========================================================
    # EVENTOS DE EDICIÓN MANUAL Y GUARDADO (sin cambios de comportamiento;
    # ahora invocado desde el formulario de unidad en vez de una celda de tabla)
    # =========================================================
    def on_item_edited(self, row, col_name, new_value):
        if col_name == 'N°':
            return

        df_actual = self.model.get_df()
        # UTILIZAMOS EL VIN COMO LLAVE MAESTRA INQUEBRANTABLE
        vin_value = str(df_actual.iat[row, df_actual.columns.get_loc('VIN')]).strip().upper()

        if vin_value not in self.pending_changes:
            self.pending_changes[vin_value] = {'VIN': vin_value, 'cambios': {}}

        # --- VALIDACIÓN INTELIGENTE DE FECHAS ---
        if col_name in ['FECHA INICIO CM', 'FECHA TERMINO CM']:
            val_limpio = str(new_value).strip()

            if val_limpio not in ["", "nan", "NaN", "-"]:
                try:
                    datetime.strptime(val_limpio, "%d-%m-%Y")
                    self.pending_changes[vin_value]['cambios'][col_name] = val_limpio
                except ValueError:
                    QMessageBox.warning(self, "Error de Formato", "La fecha debe ser estrictamente en formato: DD-MM-YYYY\n\nEjemplo válido: 15-08-2026")

                    old_row = self.df_base[self.df_base['VIN'].str.strip().str.upper() == vin_value]
                    old_val = old_row.iloc[0][col_name] if not old_row.empty else "-"

                    df_actual.iat[row, df_actual.columns.get_loc(col_name)] = str(old_val).strip()
                    self.model.layoutChanged.emit()
                    return
            else:
                self.pending_changes[vin_value]['cambios'][col_name] = "-"
                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = "-"

        # --- FORMATEADOR DE PAGO CM EN VIVO ---
        elif col_name == 'PAGO CM':
            val_limpio = str(new_value).replace('$', '').replace('.', '').replace(',', '').strip()
            try:
                val_num = float(val_limpio) if val_limpio else 0.0
                # Como texto: RM_JAVI.csv es dtype=str y un float abortaba el guardado
                self.pending_changes[vin_value]['cambios'][col_name] = str(val_num)

                formato = _formato_pago(val_num)
                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = formato

            except ValueError:
                QMessageBox.warning(self, "Error", "El pago debe ser un número válido.")

                old_row = self.df_base[self.df_base['VIN'].str.strip().str.upper() == vin_value]
                old_val = old_row.iloc[0]['PAGO CM_NUM'] if not old_row.empty else 0
                old_formato = _formato_pago(old_val)

                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = old_formato
                self.model.layoutChanged.emit()
                return

        else:
            self.pending_changes[vin_value]['cambios'][col_name] = new_value

        self.model.layoutChanged.emit()

    def confirm_save(self):
        comercial_services.agregar_id_a_cambios(self.pending_changes, self.data_manager.get_contratos_actuales_df())
        valid = {k: d for k, d in self.pending_changes.items() if d.get('cambios')}
        if not valid: return QMessageBox.information(self, "Sin cambios", "No hay datos modificados.")

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirmar")
        msg.setText("Se aplicarán y guardarán en la nube los cambios de los contratos.")
        msg.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Save:
            self._iniciar_guardado(valid)

    def _iniciar_guardado(self, valid, texto="Guardando contratos en la nube…", contratos_nuevos=None):
        self.btn_reload.setEnabled(False)
        self.btn_importar.setEnabled(False)

        mostrar_guardando(self, texto)

        self.save_thread = SaveContratosThread(self.writer, valid, contratos_nuevos=contratos_nuevos)
        self.save_thread.finished_signal.connect(self._on_save_finished)
        self.save_thread.start()

    def _on_save_finished(self, success):
        self.btn_reload.setEnabled(True)
        self.btn_importar.setEnabled(True)

        if success:
            guardado_listo(self)
            try:
                dm = self.data_manager
                if not dm.df_master.empty:
                    dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master.copy(), self.pending_changes)
                    for registro in getattr(self, '_contratos_nuevos_pendientes', []):
                        dm.df_master = comercial_services.agregar_fila(dm.df_master, registro)

                    try:
                        cm_bajas_service.procesar_reconciliacion_estado_expired(
                            df_pruebas_actual=dm.df_master,
                            periodo_deteccion=datetime.now().strftime('%Y-%m'),
                            casos_path=config.settings.CASOS_BAJA_CM_PATH,
                        )
                    except Exception as e:
                        logger.error(f"No se pudo reconciliar los casos de Revisión CM por estado Expired: {e}")

                self.pending_changes.clear()
                self._contratos_nuevos_pendientes = []
                self.load_data()
                if getattr(self, '_casos_a_cerrar', None):
                    try:
                        cm_bajas_service.procesar_confirmacion_baja_cm_multiple(
                            caso_ids=self._casos_a_cerrar, casos_path=config.settings.CASOS_BAJA_CM_PATH)
                    except Exception as e:
                        logger.error(f"No se pudo confirmar la baja de los casos CM: {e}")
                    self._casos_a_cerrar = []
                if getattr(self, '_emitir_data_ready_tras_guardar', False):
                    self._emitir_data_ready_tras_guardar = False
                    dm.data_ready.emit()
                self.stack.setCurrentIndex(1)
                terminar_guardando(self)
            except Exception as e:
                logger.warning(f"Error inyectando RAM en Contratos: {e}")
                terminar_guardando(self, exito=False)
                self.recargar_desde_cero()
        else:
            self._contratos_nuevos_pendientes = []
            terminar_guardando(self, exito=False)
            self.stack.setCurrentIndex(1)
            QMessageBox.warning(self, "Error", "No se guardaron los cambios. SharePoint puede estar bloqueando el archivo. Intenta de nuevo.")
