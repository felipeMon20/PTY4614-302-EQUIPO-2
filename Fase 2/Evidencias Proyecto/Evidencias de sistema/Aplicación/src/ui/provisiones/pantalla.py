"""Pantalla Provisiones: lista de clientes y registros, editor de panel y guardado de cambios."""
from src.core.constants import COL_RAZON_SOCIAL, COL_VIN, TIPO_FACTURACION_DISPLAY_MAP
from src.theme.colors import TEXT_SECONDARY, VOLVO_BLUE
from collections import Counter
from functools import lru_cache
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import QVBoxLayout, QFrame, QLabel, QPushButton, QMessageBox, QLineEdit, QApplication, QGridLayout, QComboBox, QSizePolicy
from PyQt6.QtCore import Qt, QTimer
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.comercial_agregar import _COMBO_CHEVRON_PATH
from src.ui.compartido.copiar import copiar_texto
from src.ui.compartido.formulario_unidad import GuardadoUnidadesMixin
from src.ui.ingresos.base import PantallaIngresosBase, ComboFiltroBarra, boton_barra, estilo_combo_barra
from src.services import provisiones_services
from src.services import comercial_services
from src.services.vin_service import obtener_modelo_desde_vin
from src.theme.theme_manager import ThemeManager
from src.ui.provisiones.base import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    logger,
    ProvisionesTableModel,
    COL_UF_REGISTRO,
    SaveProvisionesThread,
    _construir_registro_nuevo_desde_provisiones,
    MODULE_ACCENT_PROV,
    _PLAN_OPCIONES,
    _formato_moneda_prov,
    _CHIP_VOLVO,
    _CHIP_COBRO,
    _CHIP_VAR_NEGATIVA,
    _CHIP_VAR_POSITIVA,
    COL_PROV_CLIENTE,
    COL_PROV_EJECUTIVO,
    COL_PROV_REGISTROS,
    COL_PROV_CLAVE,
    COL_PROV_PERIODO,
    COL_PROV_PLAN,
    COL_PROV_DYNAFLEET,
    COL_PROV_MESES,
    COL_PROV_MONTO,
    COL_PROV_VALOR_PLAN,
    COL_PROV_VARIACION,
    COL_PROV_COBRO,
    COL_PROV_INDUSTRIA,
    COL_UNIDADES,
    COL_PROV_MODELO,
    _MARCA_SIN_CIV,
    _CHIP_SIN_CIV,
    COL_PROV_OBS,
    COL_PROV_ACTIVIDAD,
    _COLUMNAS_CLIENTES_PROV,
    _COLUMNAS_REGISTROS_PROV,
    _FRACCION_ANCHO_PROV,
    _EDITABLE_A_MOTOR,
    _ORIGEN_REGISTRO,
    _COLUMNAS_SIGNO_PROV,
    _VARIOS,
    _TODOS_MESES,
    _TODOS_PLANES,
    _modelos_sin_civ,
    _texto_modelo,
    _texto_celda,
    ModeloTablaProvisiones,
)
from src.ui.provisiones.dialogos import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    VincularComercialDialog,
    VinsHuerfanosAlertDialog,
    ProvisionFormDialog,
)
from src.ui.provisiones.sync import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    _PASOS_SYNC,
    _MENSAJE_PASO_SYNC,
    _ESPERA_DESCARGA_S,
    AnilloTiempo,
    PasoSync,
    SyncTerminalDialog,
)
from src.ui.provisiones.costos import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    FetchUfWorker,
    CostosDialog,
)
from src.ui.provisiones.legacy import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    _ProvisionesModuleLegacy,
)


_QSS_CAMPOS_PANEL = (
    f"QLineEdit, QComboBox {{ background-color: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA};"
    f" border-radius: 8px; padding: 0 8px; min-height: 26px; color: {estilo_com.TINTA}; font-size: 12px; }}"
    f"QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border: 1px solid {estilo_com.PRIMARIO}; }}"
    "QComboBox { padding-right: 0px; combobox-popup: 0; }"
    f"QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: top right; width: 24px; "
    f"border-left: 1px solid {estilo_com.LINEA}; border-top-right-radius: 7px; border-bottom-right-radius: 7px; background-color: #F7F8FC; }}"
    f"QComboBox::down-arrow {{ image: url({_COMBO_CHEVRON_PATH}); width: 10px; height: 10px; }}")


_PASTILLAS_ACTIVIDAD = {
    provisiones_services.ACTIVIDAD_PENDIENTE: ("#FEF3C7", "#92400E"),
    provisiones_services.ACTIVIDAD_ENVIADO: ("#D1FAE5", "#065F46"),
    "Parcial": ("#E0F2FE", "#0369A1"),
    provisiones_services.ACTIVIDAD_BAJA: ("#F3F4F6", "#4B5563"),
    provisiones_services.ACTIVIDAD_NO_APLICA: ("#F3F4F6", "#4B5563"),
    provisiones_services.ACTIVIDAD_SIN_COMERCIAL: ("#FEE2E2", "#991B1B"),
}


@lru_cache(maxsize=4096)
def _es_solo_cm(observacion):
    return provisiones_services.es_observacion_solo_cm(observacion)


class ProvisionesModule(GuardadoUnidadesMixin, PantallaIngresosBase):
    """Pantalla 'Provisiones': clientes -> registros (VIN x período). Los
    accesos que no pertenecen a la pantalla (model, table, combo_plan,
    on_item_edited, confirm_save, btn_save, etc.; ver
    src/tests/test_provisiones.py) se reenvían al motor self.legacy, igual que
    antes con las pestañas."""

    AVATAR = "PR"
    TITULO = "Provisiones"
    CAMPOS_FICHA = [
        ("Monto provisionado", COL_PROV_MONTO), ("Valor plan", COL_PROV_VALOR_PLAN),
        ("Variación", COL_PROV_VARIACION),
    ]
    COLUMNAS_FICHA = 3
    COL_CLAVE = COL_PROV_CLAVE
    COL_EMPRESA = COL_PROV_CLIENTE
    COLUMNAS_OCULTAS = (COL_PROV_CLAVE, COL_VIN)  # el VIN oculto trae todos los del grupo (menú Copiar VIN)
    COL_COPIA = COL_VIN
    ETIQUETA_COPIA = "VIN"
    SELECCION_EN_NIVEL_1 = True
    CLASE_MODELO = ModeloTablaProvisiones
    ANCHOS_DETALLE = {
        COL_PROV_CLIENTE: 260, COL_UNIDADES: 100, COL_PROV_ACTIVIDAD: 110, COL_PROV_PERIODO: 120, COL_PROV_INDUSTRIA: 130, COL_PROV_PLAN: 120, COL_PROV_MESES: 80,
        COL_PROV_DYNAFLEET: 110, COL_PROV_VALOR_PLAN: 110, COL_PROV_MONTO: 130, COL_PROV_VARIACION: 120,
    }
    ANCHOS_EMPRESAS = ANCHOS_DETALLE
    _PREFIJO_VARIOS_DYNAFLEET = "C|"

    _ATTRS_LEGACY = {'pending_changes', 'df_base'}
    MODULO_LOG = "Provisiones (Enviar a Operaciones)"

    def __init__(self):
        super().__init__()
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)
        # Nace con su padre: reparentarlo ya armado re-aplicaba los estilos a toda la tabla oculta
        self.legacy = _ProvisionesModuleLegacy(self)
        self.legacy.hide()

        self.search_input = QLineEdit()
        self.search_input.hide()
        self.filtro_periodo = ""
        self.filtro_plan = ""
        self.incluir_monto_cero = False
        self.filtro_actividad = ""
        self._cache_actividad = (None, {}, {})
        self._df_filtrado_prov = pd.DataFrame()
        self._grupos = {}
        self._grupo_de_registro = {}
        self._autocompletados = set()
        self._periodos_combo_actuales = []
        self._df_clientes = None

        self._setup_ui()
        self.legacy.data_manager.provisiones_ready.connect(self._refresh_new_ui_data)
        self._refresh_new_ui_data()

    def _setup_ui(self):
        self.construir_base()

        self.combo_periodo_prov = ComboFiltroBarra('fa5s.calendar-alt', "Mes")
        self.combo_periodo_prov.addItem(_TODOS_MESES, "")
        self.combo_plan_prov = ComboFiltroBarra('fa5s.layer-group', "Plan", multiple=True)
        self.combo_plan_prov.addItem(_TODOS_PLANES, "")
        for plan in _PLAN_OPCIONES:
            self.combo_plan_prov.addItem(plan, plan)
        self.combo_monto_prov = ComboFiltroBarra('fa5s.dollar-sign', "Dynafleet")
        self.combo_monto_prov.addItem("Con monto", "")
        self.combo_monto_prov.addItem("Incluir monto 0", "todos")
        self.combo_actividad_prov = ComboFiltroBarra('fa5s.paper-plane', "Actividad")
        self.combo_actividad_prov.addItem("Toda la actividad", "")
        self.combo_actividad_prov.addItem("Pendientes de enviar", "pendiente")
        self.combo_actividad_prov.addItem("Enviadas a Operaciones", "enviado")
        for combo, ancho in ((self.combo_periodo_prov, 160), (self.combo_plan_prov, 150), (self.combo_monto_prov, 170),
                             (self.combo_actividad_prov, 190)):
            combo.setMinimumWidth(ancho)
            ThemeManager.apply_combo_box(combo)
            combo.setStyleSheet(estilo_combo_barra())
            combo.setMaxVisibleItems(9)
            self.agregar_filtro_compacto(combo)
        self.combo_periodo_prov.currentIndexChanged.connect(self._on_filtro_cambiado)
        self.combo_plan_prov.seleccion_cambiada.connect(self._on_filtro_cambiado)
        self.combo_monto_prov.currentIndexChanged.connect(self._on_filtro_cambiado)
        self.combo_actividad_prov.currentIndexChanged.connect(self._on_filtro_cambiado)

        self.btn_descartar_prov = boton_barra("", 'fa5s.undo')
        self.btn_descartar_prov.setToolTip("Descartar los cambios sin guardar")
        self.btn_descartar_prov.clicked.connect(self._descartar_cambios)
        self.agregar_capsula(self.btn_descartar_prov)
        self.btn_guardar_prov = boton_barra("", 'fa5s.save')
        self.btn_guardar_prov.setToolTip("Guardar los cambios")
        self.btn_guardar_prov.setFixedWidth(44)
        self.btn_guardar_prov.clicked.connect(self._guardar_cambios)
        self.agregar_capsula(self.btn_guardar_prov)

        self.btn_excel_prov = boton_barra("", 'fa5s.file-excel', 'excel')
        self.btn_excel_prov.setToolTip("Exportar a Excel")
        self.btn_excel_prov.setFixedWidth(44)
        self.btn_excel_prov.setIcon(ThemeManager.icon('fa5s.file-excel', color='#1B2B4E'))
        self.btn_excel_prov.clicked.connect(self._exportar_excel)
        self.agregar_general(self.btn_excel_prov)

        self.btn_copiar_vins_prov = boton_barra("", 'fa5s.copy')
        self.btn_copiar_vins_prov.setIcon(ThemeManager.icon('fa5s.copy', color='#1B2B4E'))
        self.btn_copiar_vins_prov.clicked.connect(self._copiar_vins_filtrados)
        self.agregar_blanco(self.btn_copiar_vins_prov)
        self._actualizar_boton_copiar_vins()

        self.btn_sync_prov = boton_barra("", 'fa5s.plus')
        self.btn_sync_prov.setToolTip("Sincronización de SharePoint (Auto-ETL)")
        self.btn_sync_prov.clicked.connect(self.legacy.open_sync_dialog)
        self.agregar_capsula(self.btn_sync_prov)

        self.btn_ajustes_prov = boton_barra("", 'fa5s.cog')
        self.btn_ajustes_prov.setToolTip("Ajustes de costos")
        self.btn_ajustes_prov.clicked.connect(self.legacy.open_costos_dialog)
        self.agregar_capsula(self.btn_ajustes_prov)

        self.btn_editar_prov = estilo_com.BotonAccionPanel(
            'fa5s.edit', 'Editar provisión',
            "Abre el formulario del registro (Dynafleet, cantidad de meses y plan).", VOLVO_BLUE)
        self.btn_editar_prov.setEnabled(False)
        self.btn_editar_prov.clicked.connect(self._on_editar_clicado)
        self.agregar_accion_panel(self.btn_editar_prov)
        self.btn_editar_prov.hide()
        self.btn_enviar_prov = estilo_com.BotonAccionPanel(
            'fa5s.paper-plane', 'Enviar a Operaciones',
            "Pasa las unidades pendientes seleccionadas a Activaciones de Operaciones.", "#16A34A")
        self.btn_enviar_prov.setEnabled(False)
        self.btn_enviar_prov.clicked.connect(self._on_enviar_clicado)
        self.agregar_accion_panel(self.btn_enviar_prov)
        self._construir_editor_panel()

        self._cache_mapas_prov = (None, {}, {})
        self._cache_modelos = (None, {})
        self._actualizar_estado_guardar()

    # --------------------------------------------- ganchos de la pantalla base
    def resolver_color(self, columna, valor, es_fondo):
        texto = str(valor).strip()
        if columna == COL_PROV_REGISTROS:
            return _CHIP_VOLVO[0 if es_fondo else 1]
        if columna == COL_PROV_ACTIVIDAD:
            colores = _PASTILLAS_ACTIVIDAD.get(texto)
            return colores[0 if es_fondo else 1] if colores else None
        if columna == COL_PROV_COBRO:
            colores = _CHIP_COBRO.get(texto.upper())
            return colores[0 if es_fondo else 1] if colores else None
        if columna in _COLUMNAS_SIGNO_PROV:
            colores = self._colores_variacion(texto)
            return colores[0 if es_fondo else 1] if colores else None
        if columna == COL_PROV_DYNAFLEET and texto.endswith(" Dynafleet"):
            return _CHIP_SIN_CIV[0 if es_fondo else 1]
        if columna == COL_PROV_MODELO and texto.endswith(_MARCA_SIN_CIV):
            return _CHIP_SIN_CIV[0 if es_fondo else 1]
        return None

    def colores_chip_ficha(self, columna, valor):
        if columna in _COLUMNAS_SIGNO_PROV:
            return self._colores_variacion(str(valor).strip())
        if columna == COL_PROV_COBRO:
            return _CHIP_COBRO.get(str(valor).strip().upper())
        return None

    @staticmethod
    def _colores_variacion(texto):
        if texto.startswith('-') and texto != '-':
            return _CHIP_VAR_NEGATIVA
        if texto.startswith('$') and texto != '$-':
            return _CHIP_VAR_POSITIVA
        return None

    def on_fila_cambiada(self, fila, cantidad):
        self._actualizar_boton_enviar()
        if cantidad == 0:
            self.btn_editar_prov.setEnabled(False)
            self._editor_panel.hide()
            self._actualizar_estado_guardar()
            return
        self._pintar_panel(fila, cantidad)
        self.btn_editar_prov.setEnabled(cantidad == 1)
        self._cargar_editor_panel(cantidad == 1)
        self._actualizar_estado_guardar()

    # ---------------------------------------------------- enviar a Operaciones
    def _datos_de_unidades_en_rm(self):
        """(clave, {VIN: (actividad, enviable)}, {VIN: (forma, facturación)}) de los contratos actuales; se recalcula
        solo cuando cambian los datos de Comercial."""
        df = self.legacy.data_manager.df_master
        clave = (id(df), len(df) if isinstance(df, pd.DataFrame) else 0)
        if self._cache_actividad[0] != clave:
            actuales = self.legacy.data_manager.get_contratos_actuales_df()
            formas = {}
            if isinstance(actuales, pd.DataFrame) and not actuales.empty and 'VIN' in actuales.columns:
                def col(nombre):
                    return actuales[nombre].astype(str).str.strip() if nombre in actuales.columns else pd.Series('', index=actuales.index)
                formas = dict(zip(actuales['VIN'].astype(str).str.strip().str.upper(),
                                  zip(col('FORMA DE CONTRATO'), col('TIPO DE FACTURACION'))))
            self._cache_actividad = (clave, provisiones_services.mapa_actividad(actuales), formas)
        return self._cache_actividad

    def _actividad_de_unidades(self):
        return self._datos_de_unidades_en_rm()[1]

    def _formas_de_unidades(self):
        return self._datos_de_unidades_en_rm()[2]

    def _vins_enviables_seleccionados(self):
        vins = []
        for clave in self._vins_seleccionados():
            vins += self._fila_por_vin.get(clave, {}).get('_ENVIABLES', [])
        return list(dict.fromkeys(vins))

    def _actualizar_boton_enviar(self):
        n = len(self._vins_enviables_seleccionados())
        self.btn_enviar_prov.setEnabled(n > 0)
        self.btn_enviar_prov.setToolTip(
            f"Enviar {n} unidad(es) a Activaciones de Operaciones" if n else
            "Selecciona unidades pendientes con la provisión guardada (forma Provision, Sin Servicio o Revisar y activación No aplica)")

    def _on_enviar_clicado(self):
        vins = self._vins_enviables_seleccionados()
        if not vins:
            return
        actuales = self.legacy.data_manager.get_contratos_actuales_df()
        filas = {str(v).strip().upper(): fila for v, fila in zip(actuales['VIN'], actuales.to_dict('records'))}
        lote = {vin: {'VIN': vin, 'cambios': provisiones_services.cambios_enviar_a_operaciones(filas[vin])}
                for vin in vins if vin in filas}
        if not lote:
            return
        detalle = "\n".join(f"• {vin}" for vin in list(lote)[:12]) + (f"\n… y {len(lote) - 12} más" if len(lote) > 12 else "")
        caja = QMessageBox(self)
        caja.setIcon(QMessageBox.Icon.Question)
        caja.setWindowTitle("Enviar a Operaciones")
        caja.setText(f"Se enviarán {len(lote)} unidad(es) a Activaciones de Operaciones. Quedarán en Activación Pendiente "
                     f"y Activando, con el mes actual como inicio y periodo interno.\n\n{detalle}\n\n¿Quieres continuar?")
        enviar = caja.addButton("Enviar a Operaciones", QMessageBox.ButtonRole.AcceptRole)
        cancelar = caja.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        caja.setDefaultButton(cancelar)
        caja.exec()
        if caja.clickedButton() is enviar:
            self.guardar_lote_unidades(lote, "Enviando a Operaciones…")

    def _on_lote_unidades_guardado(self, ok, lote):
        super()._on_lote_unidades_guardado(ok, lote)
        if ok:
            QTimer.singleShot(0, self._refresh_new_ui_data)

    # ------------------------------------------- edición directa en el panel
    def _construir_editor_panel(self):
        self._editor_panel = QFrame()
        self._editor_panel.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QVBoxLayout(self._editor_panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self._titulo_editor("Editar provisión"))
        self._lbl_unidades_prov = QLabel("")
        self._lbl_unidades_prov.setWordWrap(True)
        self._lbl_unidades_prov.setStyleSheet(
            f"background: transparent; border: none; color: {estilo_com.APAGADO}; font-size: 11px;")
        lay.addWidget(self._lbl_unidades_prov)
        lay.addWidget(self._titulo_editor("Observación", pequeno=True))
        self._lbl_obs_prov = QLabel("-")
        self._lbl_obs_prov.setWordWrap(True)
        self._lbl_obs_prov.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_obs_prov.setStyleSheet(
            f"background: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; border-radius: 8px;"
            f" padding: 4px 8px; color: {estilo_com.TINTA}; font-size: 11px;")
        lay.addWidget(self._lbl_obs_prov)
        self._ed_plan = estilo_com.ComboTarjeta("Plan")
        self._ed_plan.addItems(["—"] + _PLAN_OPCIONES)
        self._ed_meses = QLineEdit()
        self._ed_meses.setPlaceholderText("Varios")
        self._ed_dyna = QLineEdit()
        self._ed_dyna.setReadOnly(True)
        self._ed_forma = estilo_com.ComboTarjeta("Forma de contrato")
        self._ed_forma.addItems(provisiones_services.OPCIONES_FORMA)
        self._ed_fact = estilo_com.ComboTarjeta("Tipo de facturación")
        grilla = QGridLayout()
        grilla.setContentsMargins(0, 2, 0, 0)
        grilla.setHorizontalSpacing(8)
        grilla.setVerticalSpacing(2)
        campos = (("Plan", self._ed_plan), ("Cantidad de meses", self._ed_meses),
                  ("Forma de contrato", self._ed_forma), ("Tipo de facturación", self._ed_fact),
                  ("Cobro Dynafleet (solo lectura)", self._ed_dyna))
        for i, (etiqueta, campo) in enumerate(campos):
            fila, columna = divmod(i, 2)
            campo.setStyleSheet(_QSS_CAMPOS_PANEL)
            if isinstance(campo, QComboBox):
                campo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                campo.setMinimumContentsLength(1)
                campo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            grilla.addWidget(self._titulo_editor(etiqueta, pequeno=True), fila * 2, columna)
            grilla.addWidget(campo, fila * 2 + 1, columna)
        grilla.setColumnStretch(0, 1)
        grilla.setColumnStretch(1, 1)
        lay.addLayout(grilla)
        self._ed_forma.currentIndexChanged.connect(self._al_cambiar_forma_panel)
        self._ed_fact.currentIndexChanged.connect(self._aplicar_forma_desde_panel)
        self._ed_dyna.setStyleSheet(_QSS_CAMPOS_PANEL + f"QLineEdit {{ color: {estilo_com.APAGADO}; }}")
        self._ed_plan.currentIndexChanged.connect(
            lambda i: i > 0 and self._aplicar_desde_panel(COL_PROV_PLAN, self._ed_plan.currentText()))
        for campo, columna in ((self._ed_meses, COL_PROV_MESES),):
            temporizador = QTimer(self)
            temporizador.setSingleShot(True)
            temporizador.setInterval(450)
            temporizador.timeout.connect(lambda c=campo, col=columna: self._aplicar_desde_panel(col, c.text()))
            campo.textEdited.connect(lambda _t, t=temporizador: t.start())
            campo.editingFinished.connect(lambda c=campo, col=columna, t=temporizador: (
                t.stop(), self._aplicar_desde_panel(col, c.text())))
        self.btn_guardar_panel_prov = QPushButton(" Guardar")
        self.btn_guardar_panel_prov.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        self.btn_guardar_panel_prov.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar_panel_prov.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR)
        self.btn_guardar_panel_prov.setEnabled(False)
        self.btn_guardar_panel_prov.clicked.connect(self._guardar_cambios)
        lay.addWidget(self.btn_guardar_panel_prov)
        self._editor_panel.hide()
        self._lay_acciones.insertWidget(0, self._editor_panel)

    @staticmethod
    def _titulo_editor(texto, pequeno=False):
        lbl = QLabel(texto.upper() if not pequeno else texto)
        lbl.setStyleSheet(
            f"background: transparent; border: none; color: {estilo_com.APAGADO}; font-size: {'11' if pequeno else '10'}px;"
            f" font-weight: {'500' if pequeno else '700'};")
        return lbl

    def _fila_seleccionada(self):
        filas = sorted({idx.row() for idx in self.tabla.selectionModel().selectedRows()})
        return filas[0] if len(filas) == 1 else None

    def _vines_de_fila(self, fila):
        df = self.modelo.get_df()
        if fila is None or not (0 <= fila < len(df)):
            return []
        clave = str(df.iat[fila, df.columns.get_loc(COL_PROV_CLAVE)]).strip()
        return [m[0] for m in self._grupos.get(clave, {}).get('miembros', [])]

    def _actualizar_texto_unidades(self, fila, plan):
        df = self.modelo.get_df()
        vines = self._vines_de_fila(fila)
        chasis = [v[-7:] for v in vines[:12]]
        texto = f"Se aplica a {len(vines)} unidad(es): " + ", ".join(chasis) + ("…" if len(vines) > 12 else "")
        clave = str(df.iat[fila, df.columns.get_loc(COL_PROV_CLAVE)]).strip()
        invalidos = _modelos_sin_civ(self._grupos.get(clave, {}).get('modelos', []), plan)
        if invalidos:
            texto += f"\nEl modelo {', '.join(invalidos)} no admite CIV."
        self._lbl_unidades_prov.setText(texto)

    def _copiar_chasis(self):
        vines = self._vines_de_fila(self._fila_seleccionada())
        if vines:
            copiar_texto("\n".join(vines), self._ficha_chasis)

    def _cargar_editor_panel(self, visible):
        fila = self._fila_seleccionada()
        df = self.modelo.get_df()
        if not visible or fila is None or not (0 <= fila < len(df)):
            self._editor_panel.hide()
            return
        def valor(col):
            return str(df.iat[fila, df.columns.get_loc(col)]).strip() if col in df.columns else ""
        clave_fila = valor(COL_PROV_CLAVE)
        self._lbl_obs_prov.setText(str(self._fila_por_vin.get(clave_fila, {}).get(COL_PROV_OBS, "-")) or "-")
        self._actualizar_texto_unidades(fila, valor(COL_PROV_PLAN))
        plan = valor(COL_PROV_PLAN)
        pos = next((i for i in range(self._ed_plan.count()) if self._ed_plan.itemText(i).upper() == plan.upper()), -1)
        self._ed_plan.blockSignals(True)
        self._ed_plan.setCurrentIndex(max(pos, 0))
        self._ed_plan.blockSignals(False)
        self._ed_meses.setText("" if valor(COL_PROV_MESES) in ("-", "$-", _VARIOS) else valor(COL_PROV_MESES))
        self._ed_dyna.setText("" if valor(COL_PROV_DYNAFLEET) in ("-", "$-") else valor(COL_PROV_DYNAFLEET))
        self._cargar_forma_panel(clave_fila)
        self._editor_panel.show()

    def _llenar_facturaciones(self, forma, seleccionada):
        self._ed_fact.blockSignals(True)
        self._ed_fact.clear()
        for real in provisiones_services.facturaciones_de_forma(forma):
            self._ed_fact.addItem(TIPO_FACTURACION_DISPLAY_MAP.get(real, real), real)
        self._ed_fact.setCurrentIndex(max(0, self._ed_fact.findData(str(seleccionada).strip().upper())))
        self._ed_fact.blockSignals(False)

    def _cargar_forma_panel(self, clave):
        """Forma de contrato y facturación del grupo: lo elegido y sin guardar, o lo que ya tiene en el Registro
        Maestro, o lo que sugiere la observación. Solo se pueden cambiar mientras la unidad está pendiente."""
        grupo = self._grupos.get(clave)
        if not grupo or not grupo['miembros']:
            return
        vin, periodo = grupo['miembros'][0]
        elegido = self.legacy.pending_changes.get(f"{vin.strip().upper()}_{periodo.strip().upper()}", {}).get('rm')
        opciones = {f.upper(): f for f in provisiones_services.OPCIONES_FORMA}
        if elegido:
            forma, facturacion = elegido['forma'], elegido.get('facturacion', '')
        else:
            forma_rm, facturacion_rm = self._formas_de_unidades().get(vin.strip().upper(), ('', ''))
            if forma_rm.upper() in opciones and forma_rm.upper() != 'SIN CONTRATO':
                forma, facturacion = opciones[forma_rm.upper()], facturacion_rm
            else:
                forma, facturacion = provisiones_services.forma_sugerida(self._fila_por_vin.get(clave, {}).get(COL_PROV_OBS, ''))
        self._ed_forma.blockSignals(True)
        self._ed_forma.setCurrentIndex(max(0, self._ed_forma.findText(forma)))
        self._ed_forma.blockSignals(False)
        self._llenar_facturaciones(forma, facturacion)
        editable = self._fila_por_vin.get(clave, {}).get(COL_PROV_ACTIVIDAD, '') in (provisiones_services.ACTIVIDAD_PENDIENTE, "Parcial")
        self._ed_forma.setEnabled(editable)
        self._ed_fact.setEnabled(editable)

    def _al_cambiar_forma_panel(self, _i=None):
        self._llenar_facturaciones(self._ed_forma.currentText(), "")
        self._aplicar_forma_desde_panel()

    def _aplicar_forma_desde_panel(self, _i=None):
        """Deja pendiente la forma de contrato y la facturación elegidas para todas las unidades del grupo."""
        fila = self._fila_seleccionada()
        df = self.modelo.get_df()
        if fila is None or not (0 <= fila < len(df)):
            return
        clave = str(df.iat[fila, df.columns.get_loc(COL_PROV_CLAVE)]).strip()
        grupo = self._grupos.get(clave)
        if not grupo:
            return
        elegido = {'forma': self._ed_forma.currentText(), 'facturacion': self._ed_fact.currentData() or ""}
        for vin, periodo in grupo['miembros']:
            llave = f"{vin.strip().upper()}_{periodo.strip().upper()}"
            pendiente = self.legacy.pending_changes.setdefault(
                llave, {'VIN': vin.strip().upper(), 'AÑO - MES': periodo.strip().upper(), 'cambios': {}})
            pendiente['rm'] = dict(elegido)
        self.modelo.celdas_pendientes = self._celdas_pendientes()
        self._actualizar_estado_guardar()

    def _aplicar_desde_panel(self, columna, texto):
        fila = self._fila_seleccionada()
        df = self.modelo.get_df()
        if fila is None or not (0 <= fila < len(df)):
            return
        actual = str(df.iat[fila, df.columns.get_loc(columna)]).strip()
        if str(texto).strip() == ("" if actual in ("-", "$-") else actual):
            return
        self._registrar_edicion(fila, columna, str(texto))
        registro = dict(self._fila_por_vin.get(str(df.iat[fila, df.columns.get_loc(COL_PROV_CLAVE)]).strip(), {}))
        registro.update({c: df.iat[fila, df.columns.get_loc(c)] for c in df.columns})
        self._pintar_panel(registro, 1)
        self._actualizar_texto_unidades(fila, str(df.iat[fila, df.columns.get_loc(COL_PROV_PLAN)]))

    def al_cambiar_nivel(self):
        self.search_input.clear()
        self._repintar_nivel_prov()

    def _vins_seleccionados(self):
        return [c for c in super()._vins_seleccionados() if not c.startswith(self._PREFIJO_VARIOS_DYNAFLEET)]

    def _on_click_celda(self, index):
        """Una empresa con más de un Dynafleet aparece en una sola fila: al hacerle clic se abre el detalle por Dynafleet."""
        df = self.modelo.get_df()
        if self.empresa_actual is not None or df.empty or not (0 <= index.row() < len(df)) or COL_PROV_CLAVE not in df.columns:
            return
        if str(df.iat[index.row(), df.columns.get_loc(COL_PROV_CLAVE)]).startswith(self._PREFIJO_VARIOS_DYNAFLEET):
            empresa = str(df.iat[index.row(), df.columns.get_loc(COL_PROV_CLIENTE)])
            QTimer.singleShot(0, lambda: self.mostrar_detalle_empresa(empresa))

    def _on_filtro_cambiado(self, _i=None):
        self.filtro_periodo = self.combo_periodo_prov.currentData() or ""
        self.filtro_plan = self.combo_plan_prov.valores() or ""
        self.incluir_monto_cero = self.combo_monto_prov.currentData() == "todos"
        self.filtro_actividad = self.combo_actividad_prov.currentData() or ""
        self._refresh_new_ui_data()

    def filter_table(self):
        self._refresh_new_ui_data()

    def refresh_if_dirty(self):
        """Mismo contrato que tenía la pestaña: recarga en cada visita salvo
        que DataManager.df_prov sea el mismo objeto de la última carga. Cada
        vez que se entra a la pantalla el combo de mes vuelve al período más
        reciente."""
        cambio_mes = self._seleccionar_mes_reciente()
        if self.legacy.data_manager.df_prov is getattr(self.legacy, '_df_prov_origen', None):
            if cambio_mes:
                self._refresh_new_ui_data()
            return
        self.legacy.load_data()
        self._refresh_new_ui_data()

    def _seleccionar_mes_reciente(self):
        """Deja el combo en el primer período (el más reciente). Devuelve True
        si cambió la selección."""
        if self.combo_periodo_prov.count() < 2 or self.combo_periodo_prov.currentIndex() == 1:
            return False
        self.combo_periodo_prov.blockSignals(True)
        self.combo_periodo_prov.setCurrentIndex(1)
        self.combo_periodo_prov.blockSignals(False)
        self.filtro_periodo = self.combo_periodo_prov.currentData() or ""
        return True

    def load_data(self):
        self.legacy.load_data()
        self._refresh_new_ui_data()

    def _exportar_excel(self):
        """Exporta los registros del mes seleccionado (uno por unidad, con
        los filtros y cambios pendientes que se ven en pantalla)."""
        df = self._df_filtrado_prov
        if df is None or df.empty:
            QMessageBox.warning(self, "Exportar", "No hay datos visibles.")
            return
        columnas = ['AÑO - MES', 'VIN', 'CLIENTE', 'EJECUTIVO', 'OBSERVACIONES', 'Plan', 'Cantidad de Meses',
                    'DYNAFLEET', 'Valor Plan', 'Monto Provisionado', 'VAR']
        salida = df[[c for c in columnas if c in df.columns]].copy().reset_index(drop=True)
        # El nombre lleva el mes en que se gestiona (hoy), no el de los datos
        hoy = datetime.now()
        nombre_mes = next((m for m, n in provisiones_services.MESES_A_NUM.items() if n == hoy.month), str(hoy.month))
        self.legacy.model.set_data(salida)
        try:
            self.legacy.table.export_to_excel(f"Reporte_Provisiones_{hoy.year}_{nombre_mes}")
        finally:
            self.legacy.filter_table()

    # ------------------------------------------------------------ edición
    def _on_editar_clicado(self):
        claves = self._vins_seleccionados()
        if len(claves) != 1:
            return
        fila = self._fila_por_vin.get(claves[0], {})
        if fila and fila.get('_FILA_FORM'):
            self._abrir_form_provision(fila['_FILA_FORM'], fila.get(COL_RAZON_SOCIAL))

    def _industria_de_razon_social(self, razon_social):
        """Industria de Comercial para la razón social (sin RUT ni CDB, solo
        por nombre normalizado). Si hay varias, la más frecuente; '-' si no
        hay coincidencia."""
        df = self.legacy.data_manager.df_master
        if not isinstance(df, pd.DataFrame) or df.empty or not razon_social \
                or 'RAZÓN SOCIAL' not in df.columns or 'INDUSTRIA' not in df.columns:
            return "-"

        def norm(serie):
            return serie.astype(str).str.upper().str.split().str.join(" ")

        objetivo = " ".join(str(razon_social).upper().split())
        industrias = df.loc[norm(df['RAZÓN SOCIAL']) == objetivo, 'INDUSTRIA'].astype(str).str.strip()
        industrias = industrias[~industrias.isin(['', '-', 'nan', 'None'])]
        return industrias.mode().iloc[0] if not industrias.empty else "-"

    def _abrir_form_provision(self, fila, cliente=None):
        uf, _civ = self.legacy.data_manager.get_variables()
        planes_data = self.legacy.data_manager.get_costos()
        cliente = cliente or self.empresa_actual
        industria = self._industria_de_razon_social(cliente)
        dialog = ProvisionFormDialog(cliente, fila, planes_data, uf, parent=self, industria=industria)
        dialog.guardado.connect(self._aplicar_cambios_formulario)
        dialog.exec()

    def _fila_index_en_legacy_model(self, vin, periodo):
        df = self.legacy.model.get_df()
        if df.empty or 'VIN' not in df.columns:
            return None
        serie_vin = df['VIN'].astype(str).str.strip().str.upper()
        mask = serie_vin == vin.strip().upper()
        if 'AÑO - MES' in df.columns:
            serie_periodo = df['AÑO - MES'].astype(str).str.strip().str.upper()
            mask &= serie_periodo == periodo.strip().upper()
        posiciones = mask.to_numpy().nonzero()[0]
        return int(posiciones[0]) if len(posiciones) else None

    def _aplicar_cambios_formulario(self, vin, periodo, cambios):
        """Aplica los campos del formulario reutilizando on_item_edited (uno
        por columna) + confirm_save() del motor, igual que ContratoFormDialog
        en contratos.py. El registro puede no estar en la vista actual del
        motor si sus propios filtros lo ocultan: en ese caso se amplía el
        modelo momentáneamente a df_base completo y se restaura el filtro al
        terminar."""
        if getattr(self.legacy, '_tabla_pendiente', False):
            self.legacy.filter_table()
        row = self._fila_index_en_legacy_model(vin, periodo)
        restaurar_filtro = False
        if row is None:
            self.legacy.model.set_data(self.legacy.df_base)
            restaurar_filtro = True
            row = self._fila_index_en_legacy_model(vin, periodo)

        if row is None:
            QMessageBox.warning(
                self, "No encontrado",
                "No se pudo ubicar este registro para guardarlo. Recarga Provisiones e intenta de nuevo.",
            )
            if restaurar_filtro:
                self.legacy.filter_table()
            return

        for col_name, new_value in cambios.items():
            self.legacy.on_item_edited(row, col_name, new_value)

        self.legacy.confirm_save()

        if restaurar_filtro:
            self.legacy.filter_table()

    # ------------------------------------------------------------- datos
    def _actualizar_opciones_periodo(self, df_base):
        """Repuebla el combo de mes solo si cambió el conjunto de períodos
        (así no se pierde la selección en cada recálculo)."""
        periodos = provisiones_services.obtener_periodos_disponibles(df_base)
        if periodos == self._periodos_combo_actuales:
            return
        anteriores = set(self._periodos_combo_actuales)
        self._periodos_combo_actuales = periodos
        primera_carga = self.combo_periodo_prov.count() < 2
        seleccion_previa = self.combo_periodo_prov.currentData() or ""
        self.combo_periodo_prov.blockSignals(True)
        self.combo_periodo_prov.clear()
        self.combo_periodo_prov.addItem(_TODOS_MESES, "")
        for periodo in periodos:
            self.combo_periodo_prov.addItem(periodo, periodo)
        idx = self.combo_periodo_prov.findData(seleccion_previa)
        if primera_carga and periodos:
            idx = 1
        elif periodos and periodos[0] not in anteriores:
            # Llegó un mes nuevo (la sincronización con SharePoint): se muestra de inmediato, con sus cambios pendientes a la vista
            idx = self.combo_periodo_prov.findData(periodos[0])
        self.combo_periodo_prov.setCurrentIndex(idx if idx >= 0 else 0)
        self.filtro_periodo = self.combo_periodo_prov.currentData() or ""
        self.combo_periodo_prov.blockSignals(False)

    def _refresh_new_ui_data(self):
        """Recalcula el universo filtrado (búsqueda + cambios pendientes +
        filtros) una sola vez; navegar entre niveles solo repinta."""
        df_base = getattr(self.legacy, 'df_base', pd.DataFrame())
        if df_base is None or df_base.empty:
            self._df_filtrado_prov = pd.DataFrame()
            self._df_clientes = None
            self._actualizar_boton_copiar_vins()
            self._repintar_nivel_prov()
            return

        self._actualizar_opciones_periodo(df_base)
        self._autocompletar_desde_observacion(df_base)
        df = df_base.copy()

        pending = getattr(self.legacy, 'pending_changes', {}) or {}
        if pending and 'VIN' in df.columns and 'AÑO - MES' in df.columns:
            # Una sola pasada: normalizar todas las filas por cada cambio
            # pendiente tardaba segundos con cientos de autocompletados
            cambios_por_col = {}
            for data in pending.values():
                llave = f"{str(data.get('VIN', '')).strip().upper()}|{str(data.get('AÑO - MES', '')).strip().upper()}"
                for col_c, val_c in data.get('cambios', {}).items():
                    if col_c in df.columns:
                        cambios_por_col.setdefault(col_c, {})[llave] = val_c
            if cambios_por_col:
                llaves = (df['VIN'].astype(str).str.strip().str.upper() + '|'
                          + df['AÑO - MES'].astype(str).str.strip().str.upper())
                for col_c, valores in cambios_por_col.items():
                    tiene = llaves.isin(list(valores))
                    if tiene.any():
                        df[col_c] = df[col_c].astype(object)
                        df.loc[tiene, col_c] = llaves[tiene].map(valores).to_numpy()

        texto = self.search_input.text().strip().lower()
        if texto:
            cols = [c for c in ['VIN', 'CLIENTE', 'EJECUTIVO'] if c in df.columns]
            mask = comercial_services.construir_mascara_busqueda(df, texto, cols)
            df = df[mask]

        if 'DYNAFLEET' in df.columns and not self.incluir_monto_cero:
            df = df[pd.to_numeric(df['DYNAFLEET'], errors='coerce').fillna(0) > 0]
        if self.filtro_plan and 'Plan' in df.columns:
            df = df[df['Plan'].astype(str).str.strip().str.upper().isin({p.upper() for p in self.filtro_plan})]
        if self.filtro_periodo and 'AÑO - MES' in df.columns:
            df = df[df['AÑO - MES'].astype(str).str.strip() == self.filtro_periodo]
        if self.filtro_actividad and 'VIN' in df.columns and not df.empty:
            mapa = self._actividad_de_unidades()
            actividades = df['VIN'].astype(str).str.strip().str.upper().map(lambda v: mapa.get(v, ('', False))[0])
            solo_cm = df['OBSERVACIONES'].astype(str).map(_es_solo_cm) if 'OBSERVACIONES' in df.columns else False
            objetivo = provisiones_services.ACTIVIDAD_PENDIENTE if self.filtro_actividad == 'pendiente' else provisiones_services.ACTIVIDAD_ENVIADO
            df = df[(actividades == objetivo) & ~solo_cm]

        self._df_filtrado_prov = df
        self._df_clientes = None
        self._actualizar_boton_copiar_vins()
        self._repintar_nivel_prov()

    def _vins_filtrados(self):
        """VIN únicos (en orden) del universo filtrado que se ve en pantalla."""
        df = self._df_filtrado_prov
        if df is None or df.empty or 'VIN' not in df.columns:
            return []
        serie = df['VIN'].astype(str).str.strip()
        serie = serie[~serie.str.lower().isin(['', 'nan', 'none', '-'])]
        return serie.drop_duplicates().tolist()

    def _actualizar_boton_copiar_vins(self):
        """Solo se puede copiar con un mes elegido en el filtro."""
        boton = getattr(self, 'btn_copiar_vins_prov', None)
        if boton is None:
            return
        n = len(self._vins_filtrados()) if self.filtro_periodo else 0
        boton.setEnabled(n > 0)
        boton.setToolTip(
            f"Copiar los {n} VIN de {self.filtro_periodo} (con el filtro de plan aplicado) para pegarlos en la búsqueda"
            if n > 0 else "Elige un mes en el filtro para copiar sus VIN")

    def _copiar_vins_filtrados(self):
        vins = self._vins_filtrados()
        if not vins or not self.filtro_periodo:
            return
        QApplication.clipboard().setText(", ".join(vins))
        boton = self.btn_copiar_vins_prov
        boton.setText(" Copiados")
        QTimer.singleShot(2200, lambda: boton.setText(""))
        try:
            from src.ui.marco.main_window import MAX_TERMINOS_BUSQUEDA_GLOBAL as limite
        except Exception:
            limite = 200
        if len(vins) > limite:
            QMessageBox.information(
                self, "Lista larga",
                f"Se copiaron {len(vins)} VIN, pero la barra de búsqueda admite {limite} a la vez al pegar. "
                f"Si pegas la lista completa solo se usarán los primeros {limite}.")

    def _repintar_nivel_prov(self):
        """Una sola tabla con todos los registros filtrados (sin agrupar)."""
        df = self._df_filtrado_prov
        if df is None or df.empty:
            self._fila_por_vin = {}
            self._df_tabla = pd.DataFrame(columns=_COLUMNAS_REGISTROS_PROV)
            self.lbl_subtitulo.setText(self._texto_uf("0 clientes · 0 registros"))
            self.lbl_sin_resultados.setVisible(True)
            self.modelo.celdas_pendientes = self._celdas_pendientes()
            self._pintar_tabla()
            self._actualizar_estado_guardar()
            return

        self._df_tabla = self._armar_tabla_registros(df)
        clientes = df['CLIENTE'].nunique() if 'CLIENTE' in df.columns else 0
        self.lbl_subtitulo.setText(self._texto_uf(f"{clientes} clientes · {len(df)} registros"))
        self.lbl_sin_resultados.setVisible(self._df_tabla.empty)
        self.modelo.celdas_pendientes = self._celdas_pendientes()
        self._pintar_tabla()
        self._ajustar_columnas_prov()
        self._actualizar_estado_guardar()

    def _ajustar_columnas_prov(self):
        """Reparte el ancho de la tabla entre las columnas para que no haya
        scroll horizontal; Cliente ocupa lo que sobra."""
        df = self.modelo.get_df()
        if df.empty:
            return
        total = max(600, self.tabla.viewport().width())
        usado = 0
        for i, col in enumerate(df.columns):
            if col in self.COLUMNAS_OCULTAS or col == COL_PROV_CLIENTE:
                continue
            ancho = int(total * _FRACCION_ANCHO_PROV.get(col, 0.08))
            self.tabla.setColumnWidth(i, ancho)
            usado += ancho
        if COL_PROV_CLIENTE in df.columns:
            self.tabla.setColumnWidth(df.columns.get_loc(COL_PROV_CLIENTE), max(200, total - usado))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'modelo') and self.legacy is not None:
            QTimer.singleShot(0, self._ajustar_columnas_prov)

    # ---------------------------------------- edición en la celda y guardado
    def _celdas_pendientes(self):
        """{(clave VIN|período en mayúsculas, columna de la tabla)} con cambios sin guardar."""
        inverso = {motor: tabla for tabla, motor in _EDITABLE_A_MOTOR.items()}
        celdas = set()
        for datos in (getattr(self.legacy, 'pending_changes', {}) or {}).values():
            registro = f"{str(datos.get('VIN', '')).strip().upper()}|{str(datos.get('AÑO - MES', '')).strip().upper()}"
            clave = self._grupo_de_registro.get(registro, registro).upper()
            for columna_motor in datos.get('cambios', {}):
                if columna_motor in inverso:
                    celdas.add((clave, inverso[columna_motor]))
            if datos.get('rm'):
                celdas.add((clave, '_FORMA'))
        return celdas

    def _actualizar_estado_guardar(self):
        n = len(self._celdas_pendientes())
        boton, descartar = getattr(self, 'btn_guardar_prov', None), getattr(self, 'btn_descartar_prov', None)
        if boton is None:
            return
        boton.setEnabled(n > 0)
        descartar.setVisible(n > 0)
        # El Guardar de la barra es de respaldo: con el panel de la derecha a la vista se guarda desde ahí
        editor = getattr(self, '_editor_panel', None)
        boton.setVisible(n > 0 and (editor is None or editor.isHidden()))
        panel = getattr(self, 'btn_guardar_panel_prov', None)
        if panel is not None:
            panel.setEnabled(n > 0)
            panel.setText(f" Guardar ({n})" if n else " Guardar")
        if n > 0:
            boton.setText("")
            boton.setIcon(ThemeManager.icon('fa5s.save', color="#FBBF24"))
            estilo_com.aplicar_estilo_boton_barra(boton, 'naranja')
            boton.setToolTip(f"Guardar: {n} cambio(s) sin guardar")
        else:
            boton.setText("")
            boton.setIcon(ThemeManager.icon('fa5s.save', color=TEXT_SECONDARY))
            estilo_com.aplicar_estilo_boton_barra(boton, 'neutro')
            boton.setToolTip("Guardar: edita Plan o Meses directo en la tabla")

    def _guardar_cambios(self):
        if not self.legacy.pending_changes:
            return
        otros_meses = Counter(str(d['AÑO - MES']).strip() for d in self.legacy.pending_changes.values()
                              if d.get('cambios') and self.filtro_periodo and str(d['AÑO - MES']).strip() != self.filtro_periodo)
        if otros_meses:
            detalle = ", ".join(f"{mes}: {n}" for mes, n in sorted(otros_meses.items()))
            caja = QMessageBox(self)
            caja.setIcon(QMessageBox.Icon.Question)
            caja.setWindowTitle("Confirmar guardado")
            caja.setText(f"{sum(otros_meses.values())} de los cambios pendientes están en meses que no estás viendo ({detalle}).\n\n"
                         "Se guardarán todos los cambios pendientes. Guardar no envía unidades a Operaciones.\n\n¿Quieres continuar?")
            guardar = caja.addButton("Guardar todo", QMessageBox.ButtonRole.AcceptRole)
            cancelar = caja.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            caja.setDefaultButton(cancelar)
            caja.exec()
            if caja.clickedButton() is not guardar:
                return
        self.legacy.confirm_save()
        self._actualizar_estado_guardar()

    def _descartar_cambios(self):
        self.legacy.pending_changes.clear()
        self._refresh_new_ui_data()

    def _mapa_modelos(self):
        """VIN -> modelo, desde Comercial; si no tiene, se deduce del VIN."""
        df = self.legacy.data_manager.df_master
        clave = (id(df), len(df) if isinstance(df, pd.DataFrame) else 0)
        if self._cache_modelos[0] == clave:
            return self._cache_modelos[1]
        mapa = {}
        if isinstance(df, pd.DataFrame) and not df.empty and 'VIN' in df.columns and COL_PROV_MODELO in df.columns:
            vin = df['VIN'].astype(str).str.strip().str.upper()
            modelo = df[COL_PROV_MODELO].astype(str).str.strip().str.upper()
            validos = ~modelo.isin(['', '-', 'NAN', 'NONE', '<NA>'])
            mapa = dict(zip(vin[validos], modelo[validos]))
        self._cache_modelos = (clave, mapa)
        return mapa

    def _mapas_prov(self):
        """(razón social normalizada -> industria más frecuente, VIN -> observaciones) desde Comercial."""
        df = self.legacy.data_manager.df_master
        clave = (id(df), len(df) if isinstance(df, pd.DataFrame) else 0)
        if self._cache_mapas_prov[0] == clave:
            return self._cache_mapas_prov[1], self._cache_mapas_prov[2]
        industrias, observaciones = {}, {}
        if isinstance(df, pd.DataFrame) and not df.empty:
            def norm(serie):
                return serie.astype(str).str.upper().str.split().str.join(" ")
            vacios = ['', '-', 'nan', 'None', '<NA>']
            if 'RAZÓN SOCIAL' in df.columns and 'INDUSTRIA' in df.columns:
                aux = pd.DataFrame({'r': norm(df['RAZÓN SOCIAL']), 'i': df['INDUSTRIA'].astype(str).str.strip()})
                aux = aux[~aux['i'].isin(vacios)]
                industrias = aux.groupby('r')['i'].agg(lambda s: s.mode().iloc[0]).to_dict()
        self._cache_mapas_prov = (clave, industrias, observaciones)
        return industrias, observaciones

    def _registrar_edicion(self, fila, columna, valor):
        """Una celda editada: valida, deja el cambio pendiente (mismo formato
        que el motor de guardado), recalcula montos y actualiza la fila sin
        repintar toda la tabla."""
        df_tabla = self.modelo.get_df()
        if not (0 <= fila < len(df_tabla)) or COL_PROV_CLAVE not in df_tabla.columns:
            return
        clave = str(df_tabla.iat[fila, df_tabla.columns.get_loc(COL_PROV_CLAVE)])
        grupo = self._grupos.get(clave)
        if not grupo:
            return
        motor = _EDITABLE_A_MOTOR[columna]
        if columna == COL_PROV_MESES:
            resultado, dato = provisiones_services.validar_cantidad_meses(valor)
            if resultado == "invalido":
                QMessageBox.warning(self, "Error", dato)
                return
            nuevo = dato
        else:
            nuevo = str(valor).strip()

        df = self._df_filtrado_prov
        serie_vin = df['VIN'].astype(str).str.strip().str.upper()
        serie_per = df['AÑO - MES'].astype(str).str.strip().str.upper()
        primero = None
        for vin, periodo in grupo['miembros']:
            mascara = (serie_vin == vin.strip().upper()) & (serie_per == periodo.strip().upper())
            if not mascara.any():
                continue
            resumen = self._aplicar_cambio_unidad(df, mascara, vin, periodo, {motor: nuevo})
            primero = primero or resumen
        if primero is None:
            return

        fmt = provisiones_services.formatear_moneda
        visibles = {
            COL_PROV_PLAN: primero['plan'],
            COL_PROV_MESES: primero['cambios'].get('Cantidad de Meses', None),
            COL_PROV_VALOR_PLAN: fmt(primero['valor_plan']), COL_PROV_MONTO: fmt(primero['monto']),
            COL_PROV_VARIACION: fmt(primero['variacion']),
        }
        if COL_PROV_MODELO in df_tabla.columns:
            visibles[COL_PROV_MODELO] = _texto_modelo(grupo.get('modelos', []), primero['plan'])
        for col_tabla, texto in visibles.items():
            if texto is not None and col_tabla in df_tabla.columns:
                df_tabla.iat[fila, df_tabla.columns.get_loc(col_tabla)] = _texto_celda(texto)
        self.modelo.celdas_pendientes = self._celdas_pendientes()
        self.modelo.dataChanged.emit(
            self.modelo.index(fila, 0), self.modelo.index(fila, len(df_tabla.columns) - 1))
        self._actualizar_estado_guardar()

    def _calcular_cambios_unidad(self, actual, cambios):
        """Agrega Monto, Valor plan y Variación a `cambios` para un registro,
        con lo ya guardado en `actual` para lo que no cambia."""
        def numero(valor_celda, defecto):
            try:
                return float(str(valor_celda).replace('$', '').replace('.', '').replace(',', '').strip())
            except ValueError:
                return defecto

        dyna = cambios['DYNAFLEET'] if 'DYNAFLEET' in cambios else pd.to_numeric(actual.get('DYNAFLEET'), errors='coerce')
        dyna = 0.0 if pd.isna(dyna) else float(dyna)
        meses_txt = cambios.get('Cantidad de Meses', actual.get('Cantidad de Meses', ''))
        meses = numero(meses_txt, 1.0) if str(meses_txt).strip() not in ('', '-', 'MENSUAL', 'nan') else 1.0
        plan = cambios.get('Plan', str(actual.get('Plan', '')).strip())
        uf, _civ = self.legacy.data_manager.get_variables()
        monto, valor_plan, variacion = provisiones_services.calcular_montos_provision(
            dyna, meses, plan, self.legacy.data_manager.get_costos(), uf)
        completos = dict(cambios)
        completos.update({'Monto Provisionado': monto, 'Valor Plan': valor_plan, 'VAR': variacion})
        return completos, {'plan': plan, 'dyna': dyna, 'monto': monto, 'valor_plan': valor_plan,
                           'variacion': variacion, 'cambios': completos}

    def _aplicar_cambio_unidad(self, df, mascara, vin, periodo, cambios):
        """Deja pendiente el cambio de un registro (formato del motor de
        guardado) y lo refleja en el DataFrame filtrado."""
        completos, resumen = self._calcular_cambios_unidad(df[mascara].iloc[0], cambios)
        llave = f"{vin.strip().upper()}_{periodo.strip().upper()}"
        pendiente = self.legacy.pending_changes.setdefault(
            llave, {'VIN': vin.strip().upper(), 'AÑO - MES': periodo.strip().upper(), 'cambios': {}})
        pendiente['cambios'].update(completos)
        for col_motor, val in completos.items():
            if col_motor in df.columns:
                if df[col_motor].dtype != object:
                    df[col_motor] = df[col_motor].astype(object)
                df.loc[mascara, col_motor] = val
        return resumen

    def _autocompletar_desde_observacion(self, df):
        """Completa Plan y Meses vacíos con lo que dice la observación del
        propio registro y los guarda enseguida (cada registro se intenta una
        sola vez). Si el guardado falla, quedan como cambios pendientes (en
        ámbar) para guardarlos a mano."""
        if df is None or df.empty or 'OBSERVACIONES' not in df.columns or 'DYNAFLEET' not in df.columns:
            return
        vacios = ('', '-', '0', 'NAN', 'NONE')
        candidatos = df[(pd.to_numeric(df['DYNAFLEET'], errors='coerce').fillna(0) > 0)
                        & ~df['OBSERVACIONES'].astype(str).str.strip().str.upper().isin(vacios)]
        # Los ya intentados se descartan antes de recorrer fila por fila
        def normalizar(col):
            if col not in candidatos.columns:
                return [""] * len(candidatos)
            return [str(v).strip().upper() for v in candidatos[col]]
        vins, periodos = normalizar('VIN'), normalizar('AÑO - MES')
        nuevos = [f"{v}_{p}" not in self._autocompletados for v, p in zip(vins, periodos)]
        if not any(nuevos):
            return
        guardables = set()
        for (_i, fila), vin, periodo in zip(candidatos[nuevos].iterrows(),
                                            (v for v, n in zip(vins, nuevos) if n),
                                            (p for p, n in zip(periodos, nuevos) if n)):
            llave = f"{vin}_{periodo}"
            if llave in self._autocompletados:
                continue
            self._autocompletados.add(llave)
            plan_obs, meses_obs = provisiones_services.interpretar_observacion(fila.get('OBSERVACIONES'))
            plan_actual = str(fila.get('Plan', '')).strip().upper()
            meses_actual = pd.to_numeric(fila.get('Cantidad de Meses'), errors='coerce')
            sin_plan = plan_actual in vacios
            sin_meses = pd.isna(meses_actual) or meses_actual <= 0 or (meses_actual == 1 and sin_plan)
            cambios = {}
            if plan_obs and sin_plan:
                cambios['Plan'] = plan_obs
            if meses_obs and sin_meses:
                cambios['Cantidad de Meses'] = meses_obs
            if not cambios:
                continue
            completos, _resumen = self._calcular_cambios_unidad(fila, cambios)
            pendiente = self.legacy.pending_changes.setdefault(
                llave, {'VIN': vin, 'AÑO - MES': periodo, 'cambios': {}})
            for columna, valor in completos.items():
                pendiente['cambios'].setdefault(columna, valor)
            guardables.add(llave)
        if guardables:
            QTimer.singleShot(0, lambda: self._guardar_autocompletados(guardables))

    def _guardar_autocompletados(self, claves):
        """Guarda de inmediato lo autocompletado (solo esas filas; no envía nada a Operaciones)."""
        hilo = getattr(self.legacy, 'save_thread', None)
        if hilo is not None and hilo.isRunning():
            QTimer.singleShot(800, lambda: self._guardar_autocompletados(claves))
            return
        self.legacy.confirm_save(claves)

    def _texto_uf(self, texto):
        mes = self.combo_periodo_prov.currentText() if self.combo_periodo_prov.currentData() else ""
        try:
            uf, _civ = self.legacy.data_manager.get_variables()
            texto = f"{texto} · UF ${uf:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            pass
        return f"{texto} · {mes}" if mes else texto

    def _armar_tabla_clientes(self, df_clientes):
        self._fila_por_vin = {}
        if df_clientes.empty:
            return pd.DataFrame(columns=_COLUMNAS_CLIENTES_PROV)
        ejecutivos = df_clientes['EJECUTIVO'].tolist() if 'EJECUTIVO' in df_clientes.columns else [""] * len(df_clientes)
        return pd.DataFrame({
            COL_PROV_CLIENTE: [_texto_celda(c) if c not in (None, "") else "Sin cliente" for c in df_clientes['CLIENTE']],
            COL_PROV_EJECUTIVO: [_texto_celda(e) for e in ejecutivos],
            COL_PROV_REGISTROS: df_clientes['REGISTROS'].astype(int).astype(str).tolist(),
        }, columns=_COLUMNAS_CLIENTES_PROV)

    def _columnas_tabla_prov(self):
        columnas = list(_COLUMNAS_REGISTROS_PROV)
        if not self.filtro_periodo:
            columnas.insert(columnas.index(COL_PROV_CLIENTE) + 1, COL_PROV_PERIODO)
        return columnas

    def _armar_tabla_registros(self, df_cliente):
        """Una fila por empresa + período + Dynafleet: las unidades con el
        mismo cobro comparten plan, así que se editan juntas. Si una empresa
        tiene más de un Dynafleet, los grupos menores quedan marcados como
        excepción."""
        self._fila_por_vin = {}
        self._grupos = {}
        self._grupo_de_registro = {}
        columnas = self._columnas_tabla_prov()
        if df_cliente.empty:
            return pd.DataFrame(columns=columnas)

        def texto(col):
            if col in df_cliente.columns:
                return df_cliente[col].map(_texto_celda)
            return pd.Series("-", index=df_cliente.index)

        fmt = provisiones_services.formatear_moneda

        def moneda(col):
            if col in df_cliente.columns:
                return pd.to_numeric(df_cliente[col], errors='coerce').fillna(0).map(fmt)
            return pd.Series("$-", index=df_cliente.index)

        cliente = texto('CLIENTE').replace('-', 'Sin cliente')
        aux = pd.DataFrame({
            'cli': cliente, 'norm': cliente.str.upper().str.split().str.join(" "),
            'per': texto('AÑO - MES'), 'vin': texto('VIN'),
            'dyna': pd.to_numeric(df_cliente.get('DYNAFLEET'), errors='coerce').fillna(0).round(0),
            'plan': texto('Plan'), 'meses': texto('Cantidad de Meses'), 'obs': texto('OBSERVACIONES'),
            'vp': moneda('Valor Plan'), 'monto': moneda('Monto Provisionado'), 'var': moneda('VAR'),
            'dyna_txt': moneda('DYNAFLEET'),
        })
        industrias, _ = self._mapas_prov()
        modelo_de_vin = self._mapa_modelos()
        actividades = self._actividad_de_unidades()
        # Grupos armados en una pasada sobre listas: con pandas por grupo
        # tardaba ~4 ms por empresa
        col = {k: aux[k].tolist() for k in aux.columns}
        posiciones_grupo = {}
        for i, llave in enumerate(zip(col['norm'], col['per'], col['dyna'])):
            posiciones_grupo.setdefault(llave, []).append(i)

        def valor_grupo(nombre, posiciones):
            distintos = dict.fromkeys(col[nombre][p] for p in posiciones)
            return next(iter(distintos)) if len(distintos) == 1 else _VARIOS

        def moda(valores):
            conteo = Counter(valores)
            maximo = max(conteo.values())
            return min(v for v, n in conteo.items() if n == maximo)

        def crear_fila(clave, norm, per, posiciones, dyna_txt):
            miembros = [(col['vin'][p], col['per'][p]) for p in posiciones]
            modelos = sorted({
                modelo_de_vin.get(v.strip().upper()) or obtener_modelo_desde_vin(v) or "-" for v, _ in miembros} - {"-"})
            observaciones = [col['obs'][p] for p in posiciones if col['obs'][p] != '-']
            vistas, enviables = [], []
            for p in posiciones:
                vin = col['vin'][p].strip().upper()
                if _es_solo_cm(col['obs'][p]):
                    vistas.append(provisiones_services.ACTIVIDAD_NO_APLICA)
                    continue
                actividad, enviable = actividades.get(vin, (provisiones_services.ACTIVIDAD_SIN_COMERCIAL, False))
                vistas.append(actividad)
                if enviable:
                    enviables.append(vin)
            return {
                COL_PROV_CLAVE: clave, COL_VIN: "\n".join(v for v, _ in miembros), COL_PROV_CLIENTE: col['cli'][posiciones[0]],
                '_NORM': norm, '_N': len(posiciones), '_POS': posiciones, '_MODELOS': modelos, '_MIEMBROS': miembros,
                COL_PROV_PERIODO: per, COL_UNIDADES: str(len(posiciones)),
                COL_PROV_ACTIVIDAD: vistas[0] if len(set(vistas)) == 1 else "Parcial", '_ENVIABLES': enviables,
                COL_PROV_INDUSTRIA: industrias.get(norm, "NO DEFINIDO"),
                COL_PROV_MODELO: _texto_modelo(modelos, " ".join(dict.fromkeys(col['plan'][p] for p in posiciones))),
                COL_PROV_PLAN: valor_grupo('plan', posiciones), COL_PROV_MESES: valor_grupo('meses', posiciones),
                COL_PROV_DYNAFLEET: dyna_txt, COL_PROV_VALOR_PLAN: valor_grupo('vp', posiciones),
                COL_PROV_MONTO: valor_grupo('monto', posiciones), COL_PROV_VARIACION: valor_grupo('var', posiciones),
                COL_PROV_OBS: moda(observaciones) if observaciones else "-",
                '_VINES': [m[0] for m in miembros],
            }

        filas = []
        for (norm, per, dyna), posiciones in posiciones_grupo.items():
            clave = f"G|{norm}|{per}|{int(dyna)}"
            fila = crear_fila(clave, norm, per, posiciones, col['dyna_txt'][posiciones[0]])
            self._grupos[clave] = {'miembros': fila['_MIEMBROS'], 'modelos': fila['_MODELOS']}
            for vin, periodo in fila['_MIEMBROS']:
                self._grupo_de_registro[f"{vin.strip().upper()}|{periodo.strip().upper()}"] = clave
            filas.append(fila)
        if self.empresa_actual is not None:
            objetivo = " ".join(str(self.empresa_actual).upper().split())
            filas = [f for f in filas if f['_NORM'] == objetivo]
        else:
            # Una empresa con más de un Dynafleet en el mismo período queda en una sola fila; su detalle está al abrirla
            lotes = {}
            for f in filas:
                lotes.setdefault((f['_NORM'], f[COL_PROV_PERIODO]), []).append(f)
            filas = []
            for (norm, per), lote in lotes.items():
                if len(lote) == 1:
                    filas.append(lote[0])
                    continue
                posiciones = [p for f in lote for p in f['_POS']]
                filas.append(crear_fila(f"{self._PREFIJO_VARIOS_DYNAFLEET}{norm}|{per}", norm, per, posiciones, f"{len(lote)} Dynafleet"))
        por_cliente_periodo = {}
        for i, fila in enumerate(filas):
            por_cliente_periodo.setdefault((fila['_NORM'], fila[COL_PROV_PERIODO]), []).append(i)
        for indices in por_cliente_periodo.values():
            if len(indices) > 1:
                principal = max(indices, key=lambda i: filas[i]['_N'])
                for i in indices:
                    if i != principal:
                        filas[i][COL_PROV_CLIENTE] = f"{filas[i][COL_PROV_CLIENTE]} · otro Dynafleet"
        df = pd.DataFrame(filas)
        df = df.sort_values(['_NORM', COL_PROV_PERIODO, '_N'], ascending=[True, False, False],
                            kind="stable").reset_index(drop=True)
        for registro in df.to_dict('records'):
            registro[COL_RAZON_SOCIAL] = registro[COL_PROV_CLIENTE]
            vines = registro['_VINES']
            registro[COL_VIN] = vines[0] if len(vines) == 1 else f"{len(vines)} unidades"
            self._fila_por_vin[registro[COL_PROV_CLAVE]] = registro
        return df[columnas]

    # --------------------------------------------- reenvío al motor oculto
    def __getattr__(self, name):
        legacy = self.__dict__.get('legacy')
        if legacy is not None and hasattr(legacy, name):
            return getattr(legacy, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __setattr__(self, name, value):
        if name in ProvisionesModule._ATTRS_LEGACY and 'legacy' in self.__dict__:
            setattr(self.legacy, name, value)
        else:
            super().__setattr__(name, value)
