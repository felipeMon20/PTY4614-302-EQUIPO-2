"""Panel de detalle de Operaciones: ficha, plan, datos de flota y avisos."""
from src.theme.colors import TEXT_MUTED
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit, QCompleter, QGridLayout, QScrollArea, QCheckBox, QSizePolicy
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from src.core.constants import COL_RAZON_SOCIAL, COL_CDB_FLOTA, COL_RUT, COL_FLOTA_VC, COL_ID, COL_CDB
from src.services import catalogos_service, comercial_services, operaciones_services
from src.ui.comercial_agregar import _COMBO_CHEVRON_PATH
from src.ui.compartido.combo_multiple import ComboMultiple
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.ui.compartido.copiar import hacer_copiable, escribir_portapapeles
from src.ui.compartido import comercial_estilo as estilo_com
from src.theme.theme_manager import ThemeManager
from src.ui.operaciones.base import (
    BotonAccionOperaciones,
    CAMPOS_DETALLE_ACTIVACIONES,
    IDX_ACTIVACIONES,
    IDX_NO_ENTREGADOS,
    IDX_SIN_FLOTA,
    SIN_PLAN,
    SUBTABS_CON_DATOS_FLOTA,
)


class _DetalleOperacionesMixin:
    # ---------------------------------------------------------------
    # PANEL FLOTANTE: ficha de la unidad + acciones (mismo diseño que las
    # acciones rápidas de Comercial)
    # ---------------------------------------------------------------
    def _build_detalle_card(self):
        # Nace colgado del módulo: armarlo suelto y moverlo después le
        # reaplicaba los estilos a todo el panel
        frame = QFrame(self)
        frame.setObjectName("accionesRapidasComercial")
        frame.setStyleSheet(estilo_com.QSS_PANEL_FLOTANTE)
        marco = QVBoxLayout(frame)
        marco.setContentsMargins(1, 1, 1, 1)

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

        fila_titulo = QHBoxLayout()
        self._lbl_titulo_panel = self._titulo_seccion("Unidad seleccionada")
        fila_titulo.addWidget(self._lbl_titulo_panel)
        fila_titulo.addStretch()
        btn_cerrar = QPushButton()
        btn_cerrar.setIcon(ThemeManager.icon('fa5s.times', color=estilo_com.APAGADO))
        btn_cerrar.setFixedSize(26, 26)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setToolTip("Cerrar (quita la selección)")
        btn_cerrar.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        btn_cerrar.clicked.connect(lambda: self.table.clearSelection())
        fila_titulo.addWidget(btn_cerrar)
        layout.addLayout(fila_titulo)

        self._detalle_labels = {}
        self._bloque_unidad = QWidget()
        lay_u = QVBoxLayout(self._bloque_unidad)
        lay_u.setContentsMargins(0, 0, 0, 0)
        lay_u.setSpacing(10)
        lay_u.addWidget(self._build_ficha_hero())
        grilla = QGridLayout()
        grilla.setSpacing(6)
        celdas = [(c, e) for e, c, t in CAMPOS_DETALLE_ACTIVACIONES if t == "chip"]
        for i, (campo_col, etiqueta) in enumerate(celdas):
            celda, lbl_valor = estilo_com.crear_celda_ficha(etiqueta)
            grilla.addWidget(celda, i // 2, i % 2)
            self._detalle_labels[campo_col] = lbl_valor
        lay_u.addLayout(grilla)

        self._vins_plan_actuales = frozenset()
        self._bloque_plan = self._build_bloque_plan()
        self._bloque_plan.hide()
        lay_u.addWidget(self._bloque_plan)

        lay_u.addSpacing(4)
        self._bloque_datos_flota = self._build_bloque_datos_flota()
        self._bloque_datos_flota.hide()
        lay_u.addWidget(self._bloque_datos_flota)

        lay_u.addSpacing(4)
        lay_u.addWidget(self._titulo_seccion("Acciones"))
        self._grilla_acciones = QGridLayout()
        self._grilla_acciones.setSpacing(6)
        lay_u.addLayout(self._grilla_acciones)

        self.btn_marcar_conectado = BotonAccionOperaciones(
            'fa5s.check-circle', 'Conectado',
            "La unidad queda CONECTADA y su estado comercial pasa a Vigente. Si estaba en Activación Pendiente, "
            "se pide la fecha de activación en Volvo Connect como inicio del contrato; la duración se completa en Comercial.",
            estilo_com.AZUL, self._bloque_unidad)
        self.btn_marcar_conectado.setEnabled(False)
        self.btn_marcar_conectado.clicked.connect(self._on_marcar_conectado_clicked)
        self._tooltip_conectado = self.btn_marcar_conectado.toolTip()

        # "Marcar como SIN FLOTA" (24-09-2026, a pedido explícito): saca de
        # Activaciones una unidad que todavía no aparece en Volvo Connect;
        # solo tiene sentido en Activaciones (idx 0, ver
        # _actualizar_estado_botones/_on_seleccion_cambiada) -- una unidad
        # en Sin Flota ya está SIN FLOTA, no tiene caso volver a marcarla.
        # Mismo color que "Marcar como DESCONECTADO" (29-09-2026, a pedido explícito).
        self.btn_marcar_sin_flota = BotonAccionOperaciones(
            'fa5s.truck-loading', 'Sin flota',
            "Todavía no aparece en Volvo Connect: pasa a la cola de Sin Flota.", estilo_com.ROJO, self._bloque_unidad)
        self.btn_marcar_sin_flota.setEnabled(False)
        self.btn_marcar_sin_flota.clicked.connect(self._on_marcar_sin_flota_clicked)

        # "No entregado" (04-11-2026): solo en Activaciones; la unidad pasa a la pestaña No entregados
        self.btn_marcar_no_entregado = BotonAccionOperaciones(
            'fa5s.box-open', 'No entregado',
            "El camión no se entregó: pasa a la cola de No entregados.", estilo_com.ROJO, self._bloque_unidad)
        self.btn_marcar_no_entregado.setEnabled(False)
        self.btn_marcar_no_entregado.clicked.connect(self._on_marcar_no_entregado_clicked)

        self.btn_activacion_pendiente = BotonAccionOperaciones(
            'fa5s.hourglass-half', 'Activación Pendiente',
            "La unidad vuelve a la cola de Activaciones (Estado de activación: Activando).", estilo_com.AZUL,
            self._bloque_unidad)
        self.btn_activacion_pendiente.setEnabled(False)
        self.btn_activacion_pendiente.clicked.connect(self._on_activacion_pendiente_clicked)

        self.btn_deshacer_envio = BotonAccionOperaciones(
            'fa5s.undo', 'Devolver a Comercial',
            "Selecciona unidades en Activación Pendiente para devolverlas a Nuevas oportunidades de Comercial.", estilo_com.AZUL,
            self._bloque_unidad)
        self.btn_deshacer_envio.setEnabled(False)
        self.btn_deshacer_envio.clicked.connect(self._on_deshacer_envio_clicked)

        # "Marcar como DESCONECTADO" (22-09-2026): cierra el ciclo de BAJA
        # (Comercial -> Operaciones -> Comercial), solo tiene sentido en la
        # sub-pestaña "Bajas" (idx 2, ver _actualizar_estado_botones/
        # _on_seleccion_cambiada). Rojo (25-09-2026, pedido explícito) para
        # que la acción se note como lo que es -- confirmar una baja.
        self.btn_marcar_desconectado = BotonAccionOperaciones(
            'fa5s.unlink', 'Desconectado',
            "Confirma la baja y deja elegir la fecha de baja.", estilo_com.ROJO, self._bloque_unidad)
        self.btn_marcar_desconectado.setEnabled(False)
        self.btn_marcar_desconectado.clicked.connect(self._on_marcar_desconectado_clicked)

        self.btn_guardar_flota = BotonAccionOperaciones(
            'fa5s.save', 'Guardar flota',
            "Guarda la Flota VC y el CDB flota escritos arriba; el contrato no cambia de estado.", estilo_com.AZUL, self._bloque_unidad)
        self.btn_guardar_flota.setEnabled(False)
        self.btn_guardar_flota.clicked.connect(self._on_guardar_flota_clicked)

        self.btn_limpiar_flota = BotonAccionOperaciones(
            'fa5s.eraser', 'Limpiar flota',
            "Deja Flota VC y CDB flota en \"-\" en todas las unidades seleccionadas, sean o no de la misma empresa.",
            estilo_com.ROJO, self._bloque_unidad)
        self.btn_limpiar_flota.setEnabled(False)
        self.btn_limpiar_flota.clicked.connect(self._on_limpiar_flota_clicked)

        self.btn_contactar_ejecutivo = BotonAccionOperaciones(
            'fa5s.envelope', 'Contactar ejecutivo',
            "Abre un borrador en Outlook para el ejecutivo de la unidad.", estilo_com.AZUL, self._bloque_unidad)
        self.btn_contactar_ejecutivo.setEnabled(False)
        self.btn_contactar_ejecutivo.clicked.connect(self._on_contactar_ejecutivo_clicked)
        self._reubicar_acciones()
        layout.addWidget(self._bloque_unidad)

        self._bloque_fecha_baja = self._build_bloque_fecha_baja()
        self._bloque_fecha_baja.hide()
        layout.addWidget(self._bloque_fecha_baja)

        self._bloque_contacto = QWidget()
        self._lay_contacto = QVBoxLayout(self._bloque_contacto)
        self._lay_contacto.setContentsMargins(0, 0, 0, 0)
        self._lay_contacto.setSpacing(10)
        self._form_contacto = None
        self._bloque_contacto.hide()
        layout.addWidget(self._bloque_contacto)

        layout.addStretch()
        return frame

    # ---------------------------------------------------------------
    # ASIGNAR PLAN: unidades SIN PLAN (por ejemplo, un contrato nuevo creado
    # desde el 3PC que pasó a Activando). El plan es el tipo de servicio:
    # Básico, Medio o Full, más las casillas CIV y SZ. El bloque solo aparece
    # cuando todas las unidades seleccionadas están sin plan, y mientras no
    # tengan plan no se pueden marcar como conectadas.
    # ---------------------------------------------------------------
    # Mismo combo, flecha y casillas CIV/SZ que el formulario de Comercial
    # (comercial_agregar.py): el combo abre su lista en tarjeta (ComboTarjeta).
    _QSS_COMBO_PLAN = (
        "QComboBox { background-color: #FFFFFF; border: 1px solid #DCE3EC; border-radius: 8px; padding: 4px 10px; "
        "color: #0F1B33; font-weight: 500; font-size: 13px; combobox-popup: 0; }"
        "QComboBox:hover { border: 1px solid #B9C6DA; }"
        "QComboBox:focus, QComboBox:on { border: 1px solid #1B2B4E; }"
        "QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; "
        "border-left: 1px solid #E3E8F0; border-top-right-radius: 7px; border-bottom-right-radius: 7px; "
        "background-color: #F7F8FC; }"
        f"QComboBox::down-arrow {{ image: url({_COMBO_CHEVRON_PATH}); width: 11px; height: 11px; }}")

    def _build_bloque_plan(self):
        marco = QFrame()
        marco.setObjectName("bloquePlan")
        marco.setStyleSheet("QFrame#bloquePlan { background: #FFF5F5; border: 1px solid #F3B8B8; border-radius: 12px; }"
                            "QLabel { background: transparent; border: none; }")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(6)
        fila = QHBoxLayout()
        titulo = QLabel("Asignar plan")
        titulo.setStyleSheet("color: #991B1B; font-size: 13px; font-weight: 800;")
        self.lbl_plan_anterior = QLabel("")
        self.lbl_plan_anterior.setStyleSheet("color: #7F1D1D; font-size: 11px;")
        fila.addWidget(titulo, 1)
        fila.addWidget(self.lbl_plan_anterior)
        lay.addLayout(fila)

        controles = QHBoxLayout()
        controles.setSpacing(10)
        self.cmb_plan = estilo_com.ComboTarjeta("Tipo de servicio")
        self.cmb_plan.setStyleSheet(self._QSS_COMBO_PLAN)
        self.cmb_plan.setFixedHeight(32)
        self.cmb_plan.addItem("Elige el plan…", None)
        for plan in operaciones_services.planes_base():
            self.cmb_plan.addItem(plan if plan != "Basico" else "Básico", plan)
        self.cmb_plan.currentIndexChanged.connect(self._on_plan_cambiado)
        self.cmb_plan_complementos = ComboMultiple("Complementos", catalogos_service.complementos)
        self.cmb_plan_complementos.setStyleSheet(self._QSS_COMBO_PLAN)
        self.cmb_plan_complementos.setFixedHeight(32)
        self.cmb_plan_complementos.cambiado.connect(self._on_plan_cambiado)
        controles.addWidget(self.cmb_plan, 1)
        controles.addWidget(self.cmb_plan_complementos, 1)
        lay.addLayout(controles)

        ayuda = QLabel("Se guarda junto con Conectado, Sin flota o Guardar flota.")
        ayuda.setStyleSheet("color: #7F1D1D; font-size: 10.5px;")
        lay.addWidget(ayuda)
        return marco

    def _plan_elegido(self):
        base = self.cmb_plan.currentData()
        if base is None:
            return None
        return operaciones_services.armar_plan(base, self.cmb_plan_complementos.seleccion())

    def _on_plan_cambiado(self, *_args):
        self._actualizar_boton_conectado(self._get_selected_vins(), self.subtabs.currentIndex())

    def _vins_sin_plan(self, vins, idx):
        """VIN de la selección que no tienen plan, tal como están en la lista de `idx`."""
        cola = self._cola_full.get(idx, pd.DataFrame())
        if cola.empty or not vins or 'VIN' not in cola.columns:
            return []
        claves = {str(v).strip().upper() for v in vins}
        filas = cola[cola['VIN'].astype(str).str.strip().str.upper().isin(claves)]
        if filas.empty:
            return []
        return [str(v).strip() for v in filas.loc[operaciones_services.mascara_sin_plan(filas), 'VIN']]

    def _plan_a_guardar(self, vins, idx):
        """{VIN en mayúsculas: (VIN, plan)} de las unidades seleccionadas sin plan, si se eligió uno."""
        plan = self._plan_elegido()
        if plan is None:
            return {}
        return {v.upper(): (v, plan) for v in self._vins_sin_plan(vins, idx)}

    @staticmethod
    def _sumar_plan(changes, planes):
        """Agrega el plan elegido a los cambios de la acción que se está guardando."""
        for vin_upper, (vin, plan) in planes.items():
            entrada = changes.setdefault(vin_upper, {'VIN': vin, 'cambios': {}})
            entrada['cambios']['TIPO DE SERVICIO'] = plan

    def _plan_del_contrato_anterior(self, vin):
        df = self.data_manager.df_master
        if df is None or df.empty:
            return ""
        anteriores = comercial_services.contratos_anteriores(df, vin)
        if anteriores.empty or 'TIPO DE SERVICIO' not in anteriores.columns:
            return ""
        plan = str(anteriores.iloc[0]['TIPO DE SERVICIO']).strip()
        return "" if plan.upper() in ('', '-', 'NAN', 'NONE') else plan.upper()

    def _actualizar_bloque_plan(self, vins, idx):
        """Muestra "Asignar plan" si alguna unidad seleccionada está sin plan; el plan
        elegido se aplica a esas unidades al guardar con una de las acciones del panel."""
        sin_plan = self._vins_sin_plan(vins, idx) if idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA, IDX_NO_ENTREGADOS) else []
        claves = frozenset(v.upper() for v in sin_plan)
        if claves != self._vins_plan_actuales:
            self._vins_plan_actuales = claves
            self.cmb_plan.blockSignals(True)
            self.cmb_plan.setCurrentIndex(0)
            self.cmb_plan.blockSignals(False)
            self.cmb_plan_complementos.set_seleccion([], emitir=False)
        if len(sin_plan) == 1:
            anterior = self._plan_del_contrato_anterior(sin_plan[0])
            texto = f"Contrato anterior: {anterior}" if anterior else ""
        elif sin_plan:
            texto = f"{len(sin_plan)} unidades sin plan"
        else:
            texto = ""
        self.lbl_plan_anterior.setText(texto)
        self._bloque_plan.setVisible(bool(sin_plan))
        self._actualizar_boton_conectado(vins, idx)

    def _actualizar_boton_conectado(self, vins, idx):
        """"Conectado" queda bloqueado mientras haya unidades sin plan y no se haya elegido uno."""
        falta_plan = bool(vins) and bool(self._vins_sin_plan(vins, idx)) and self._plan_elegido() is None
        self.btn_marcar_conectado.setEnabled(
            idx in (IDX_ACTIVACIONES, IDX_SIN_FLOTA, IDX_NO_ENTREGADOS) and bool(vins) and not falta_plan)
        self.btn_marcar_conectado.setToolTip(
            "Elige el plan para poder marcar la unidad como conectada." if falta_plan else self._tooltip_conectado)

    # ---------------------------------------------------------------
    # DATOS DE FLOTA: Flota VC y CDB flota se editan en el panel derecho
    # (no en la tabla). Si el CDB ya tiene una Flota VC en el RM, se completa
    # sola y se avisa cuando se escribe otra distinta.
    # ---------------------------------------------------------------
    _QSS_CAMPO_FLOTA = (
        "QLineEdit { background: #FFFFFF; border: 1px solid #D5DCE8; border-radius: 10px; padding: 0 10px; "
        "min-height: 34px; font-size: 12px; font-weight: 600; color: #1B2B4E; }"
        "QLineEdit:focus { border: 1px solid #1B2B4E; }")

    def _build_bloque_datos_flota(self):
        bloque = QWidget()
        lay = QVBoxLayout(bloque)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        cab = QHBoxLayout()
        cab.setContentsMargins(0, 0, 0, 0)
        cab.addWidget(self._titulo_seccion("Datos de flota"))
        cab.addStretch()
        self.btn_limpiar_campos_flota = QPushButton("Limpiar datos")
        self.btn_limpiar_campos_flota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_limpiar_campos_flota.setToolTip("Vacía los dos campos del panel; no cambia nada hasta guardar")
        self.btn_limpiar_campos_flota.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {estilo_com.APAGADO}; font-size: 11px; font-weight: bold; padding: 2px 4px; }}"
            "QPushButton:hover { color: #1F6FEB; text-decoration: underline; }")
        self.btn_limpiar_campos_flota.clicked.connect(self._limpiar_campos_flota)
        cab.addWidget(self.btn_limpiar_campos_flota)
        lay.addLayout(cab)

        def etiqueta(texto):
            lbl = QLabel(texto)
            lbl.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px; font-weight: bold; background: transparent;")
            return lbl

        self._rellenando_flota = False
        self._cache_mapas_flota = (None, {}, {})
        lay.addWidget(etiqueta("CDB flota"))
        self.txt_cdb_flota = QLineEdit()
        self.txt_cdb_flota.setStyleSheet(self._QSS_CAMPO_FLOTA)
        self.txt_cdb_flota.textEdited.connect(self._on_cdb_flota_editado)
        lay.addWidget(self.txt_cdb_flota)
        lay.addWidget(etiqueta("Flota VC"))
        self.txt_flota_vc = QLineEdit()
        self.txt_flota_vc.setStyleSheet(self._QSS_CAMPO_FLOTA)
        self.txt_flota_vc.textEdited.connect(self._on_flota_vc_editada)
        lay.addWidget(self.txt_flota_vc)
        self._completer_cdb = QCompleter([], self.txt_cdb_flota)
        self._completer_cdb.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer_cdb.setFilterMode(Qt.MatchFlag.MatchContains)
        self.txt_cdb_flota.setCompleter(self._completer_cdb)
        self._completer_flota = QCompleter([], self.txt_flota_vc)
        self._completer_flota.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer_flota.setFilterMode(Qt.MatchFlag.MatchContains)
        self.txt_flota_vc.setCompleter(self._completer_flota)
        # Elegir una opción de la lista no dispara textEdited: se completa el otro campo igual
        self._cdb_autocompletado = False
        self._completer_cdb.activated.connect(self._on_cdb_flota_editado)
        self._completer_flota.activated.connect(self._on_flota_vc_editada)

        self.lbl_aviso_flota = QLabel("")
        self.lbl_aviso_flota.setWordWrap(True)
        self.lbl_aviso_flota.setStyleSheet(
            "color: #92400E; background: #FEF3C7; border-radius: 8px; padding: 6px 8px; font-size: 11px; font-weight: 600;")
        self.lbl_aviso_flota.hide()
        lay.addWidget(self.lbl_aviso_flota)

        self.lbl_aviso_empresas = QLabel(
            "Seleccionaste unidades de distintas empresas: para editar la Flota VC y el CDB flota "
            "juntas, deben tener la misma razón social o RUT.")
        self.lbl_aviso_empresas.setWordWrap(True)
        self.lbl_aviso_empresas.setStyleSheet(
            "color: #92400E; background: #FEF3C7; border-radius: 8px; padding: 6px 8px; font-size: 11px; font-weight: 600;")
        self.lbl_aviso_empresas.hide()
        lay.addWidget(self.lbl_aviso_empresas)
        return bloque

    @staticmethod
    def _texto_flota_limpio(valor):
        texto = '' if valor is None or pd.isna(valor) else str(valor).strip()
        texto = texto[:-2] if texto.endswith('.0') else texto
        return '' if texto.upper() in ('', '-', 'NAN', 'NONE', 'NAT', '<NA>') else texto

    def _mapas_flota(self):
        """(CDB mayúsculas -> [Flota VC], Flota VC mayúsculas -> [CDB]) de todo el RM."""
        df = self.df_master
        clave = (id(df), len(df) if df is not None else 0)
        if self._cache_mapas_flota[0] == clave:
            return self._cache_mapas_flota[1], self._cache_mapas_flota[2]
        por_cdb, por_flota = {}, {}
        if df is not None and not df.empty and COL_CDB_FLOTA in df.columns and COL_FLOTA_VC in df.columns:
            pares = df[[COL_CDB_FLOTA, COL_FLOTA_VC]].drop_duplicates()
            for cdb, flota in zip(pares[COL_CDB_FLOTA], pares[COL_FLOTA_VC]):
                cdb, flota = self._texto_flota_limpio(cdb), self._texto_flota_limpio(flota)
                if not cdb or not flota or flota.upper() in operaciones_services.FLOTAS_VC_NO_REALES:
                    continue
                if flota not in por_cdb.setdefault(cdb.upper(), []):
                    por_cdb[cdb.upper()].append(flota)
                if cdb not in por_flota.setdefault(flota.upper(), []):
                    por_flota[flota.upper()].append(cdb)
        self._cache_mapas_flota = (clave, por_cdb, por_flota)
        return por_cdb, por_flota

    def _poner_texto_flota(self, campo, texto):
        campo.blockSignals(True)
        campo.setText(texto)
        campo.blockSignals(False)

    def _cargar_campos_flota(self, vins):
        por_cdb, por_flota = self._mapas_flota()
        self._completer_cdb.model().setStringList(sorted(por_cdb.keys()))
        self._completer_flota.model().setStringList(sorted({f for lista in por_cdb.values() for f in lista}))
        cdb = flota = ''
        placeholder = "Sin cambios"
        mezcladas = len(vins) > 1 and not self._vins_misma_empresa(vins, self.subtabs.currentIndex())
        cola = self._cola_full.get(self.subtabs.currentIndex(), pd.DataFrame())
        if len(vins) == 1:
            if not cola.empty:
                fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == vins[0].strip().upper()]
                if not fila.empty:
                    cdb = self._texto_flota_limpio(fila.iloc[0].get(COL_CDB_FLOTA))
                    flota = self._texto_flota_limpio(fila.iloc[0].get(COL_FLOTA_VC))
            placeholder = "Sin dato"
        elif not mezcladas and not cola.empty:
            # Varias unidades de una misma empresa: si todas traen el mismo
            # valor, el panel lo muestra en vez de quedar en blanco.
            claves = {v.strip().upper() for v in vins}
            filas = cola[cola['VIN'].astype(str).str.strip().str.upper().isin(claves)]
            if len(filas) == len(claves):
                cdbs = {self._texto_flota_limpio(v) for v in filas[COL_CDB_FLOTA]}
                flotas = {self._texto_flota_limpio(v) for v in filas[COL_FLOTA_VC]}
                if len(cdbs) == 1:
                    cdb = next(iter(cdbs))
                if len(flotas) == 1:
                    flota = next(iter(flotas))
                if len(cdbs) > 1 or len(flotas) > 1:
                    placeholder = "Varios valores"
        if mezcladas:
            placeholder = "Una sola empresa"
        self.txt_cdb_flota.setPlaceholderText(placeholder)
        self.txt_flota_vc.setPlaceholderText(placeholder)
        self.txt_cdb_flota.setEnabled(not mezcladas)
        self.txt_flota_vc.setEnabled(not mezcladas)
        self.lbl_aviso_empresas.setVisible(mezcladas)
        self._poner_texto_flota(self.txt_cdb_flota, cdb)
        self._poner_texto_flota(self.txt_flota_vc, flota)
        self._cdb_autocompletado = False
        self._actualizar_aviso_flota()

    def _limpiar_campos_flota(self):
        por_cdb, _ = self._mapas_flota()
        self._poner_texto_flota(self.txt_cdb_flota, '')
        self._poner_texto_flota(self.txt_flota_vc, '')
        self._completer_cdb.model().setStringList(sorted(por_cdb.keys()))
        self._completer_flota.model().setStringList(sorted({f for lista in por_cdb.values() for f in lista}))
        self._cdb_autocompletado = False
        self._actualizar_aviso_flota()
        self.txt_cdb_flota.setFocus()

    def _on_cdb_flota_editado(self, texto):
        # Lo que escribe la persona deja de ser un CDB puesto por la aplicación
        self._cdb_autocompletado = False
        por_cdb, _ = self._mapas_flota()
        flotas = por_cdb.get(texto.strip().upper(), [])
        if flotas:
            self._completer_flota.model().setStringList(flotas)
            if len(flotas) == 1:
                self._poner_texto_flota(self.txt_flota_vc, flotas[0])
        else:
            self._completer_flota.model().setStringList(sorted({f for lista in por_cdb.values() for f in lista}))
        self._actualizar_aviso_flota()

    def _on_flota_vc_editada(self, texto):
        por_cdb, por_flota = self._mapas_flota()
        cdbs = por_flota.get(texto.strip().upper(), [])
        # Se completa el CDB si está vacío o si lo había puesto la aplicación para otra flota
        if len(cdbs) == 1 and (not self.txt_cdb_flota.text().strip() or self._cdb_autocompletado):
            self._poner_texto_flota(self.txt_cdb_flota, cdbs[0])
            self._cdb_autocompletado = True
        if cdbs:
            self._completer_cdb.model().setStringList(sorted(c.upper() for c in cdbs))
        else:
            self._completer_cdb.model().setStringList(sorted(por_cdb.keys()))
        self._actualizar_aviso_flota()

    def _flotas_conocidas_del_cdb(self):
        cdb = self.txt_cdb_flota.text().strip()
        por_cdb, _ = self._mapas_flota()
        return por_cdb.get(cdb.upper(), []) if cdb else []

    def _aviso_flota_distinta(self):
        """Texto de aviso si la Flota VC escrita no es ninguna de las que el RM ya
        asocia a ese CDB flota; '' si coincide o no hay nada que comparar."""
        flota = self.txt_flota_vc.text().strip()
        conocidas = self._flotas_conocidas_del_cdb()
        if flota and conocidas and flota.upper() not in {f.upper() for f in conocidas}:
            return f"El CDB {self.txt_cdb_flota.text().strip()} ya está asociado a: {', '.join(conocidas)}."
        return ''

    def _actualizar_aviso_flota(self):
        aviso = self._aviso_flota_distinta()
        self.lbl_aviso_flota.setText(aviso)
        self.lbl_aviso_flota.setVisible(bool(aviso))

    @staticmethod
    def _titulo_seccion(texto):
        lbl = QLabel(texto)
        fuente = lbl.font()
        fuente.setCapitalization(QFont.Capitalization.AllUppercase)
        lbl.setFont(fuente)
        lbl.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        return lbl

    def _build_ficha_hero(self):
        """Iniciales + Razón social + Chasis (clic para copiar) y VIN."""
        hero = QFrame()
        hero.setObjectName("fichaHeroComercial")
        hero.setStyleSheet(estilo_com.QSS_FICHA_HERO)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(12, 12, 12, 12)
        hero_layout.setSpacing(12)
        self._ficha_avatar = QLabel("--")
        self._ficha_avatar.setFixedSize(46, 46)
        self._ficha_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ficha_avatar.setStyleSheet(estilo_com.QSS_FICHA_AVATAR)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        nombre = QLabel("—")
        nombre.setWordWrap(True)
        nombre.setStyleSheet(estilo_com.QSS_FICHA_NOMBRE)
        self._detalle_labels['RAZÓN SOCIAL'] = nombre

        hacer_copiable(nombre)

        textos.addWidget(nombre)
        for prefijo, campo_col in (("Chasis", 'CHASIS'), ("CDB comercial", 'CDB'),
                                   ("N° contrato", 'ID'), ("VIN", 'VIN')):
            textos.addLayout(self._fila_copiable(prefijo, campo_col))
        hero_layout.addWidget(self._ficha_avatar)
        hero_layout.addLayout(textos, stretch=1)
        return hero

    def _fila_copiable(self, prefijo, campo_col):
        """Fila 'Prefijo valor [icono]' de la ficha; un clic copia el valor."""
        fila = QHBoxLayout()
        fila.setSpacing(4)
        etiqueta = QLabel(prefijo)
        etiqueta.setStyleSheet(estilo_com.QSS_FICHA_CHASIS)
        valor = QLabel("—")
        valor.setStyleSheet(estilo_com.QSS_FICHA_CHASIS + " font-weight: bold;")
        icono_copiar = QLabel()
        icono_copiar.setPixmap(ThemeManager.icon_pixmap('fa5s.copy', color=TEXT_MUTED, size=11))
        icono_copiar.setStyleSheet("background: transparent; border: none;")
        # Clic en el valor, en el prefijo o en el ícono copia y avisa "Copiado"
        hacer_copiable(valor, etiqueta, icono_copiar)
        fila.addWidget(etiqueta)
        fila.addWidget(valor)
        fila.addWidget(icono_copiar)
        fila.addStretch()
        self._detalle_labels[campo_col] = valor
        return fila

    def _copiar_valor_detalle(self, campo_col):
        texto = self._detalle_labels[campo_col].text()
        if texto and texto != "—":
            escribir_portapapeles(texto)

    def _pintar_panel_detalle(self, fila):
        for etiqueta, campo_col, tipo in CAMPOS_DETALLE_ACTIVACIONES:
            valor = fila.get(campo_col, "")
            valor = "" if pd.isna(valor) else str(valor).strip()
            if valor.lower() in ("nan", "nat"):
                valor = ""
            if campo_col == COL_ID:
                valor = comercial_services._normalizar_id_contrato(valor)
            elif campo_col == COL_CDB:
                valor = self._texto_flota_limpio(valor)
            elif (campo_col == 'TIPO DE SERVICIO'
                    and self.subtabs.currentIndex() in (IDX_ACTIVACIONES, IDX_SIN_FLOTA, IDX_NO_ENTREGADOS)
                    and valor.upper() in ('', '-')):
                valor = SIN_PLAN
            lbl = self._detalle_labels[campo_col]
            if tipo == "chip":
                estilo_com.pintar_chip_ficha(lbl, valor)
            else:
                lbl.setText(valor or "—")
        self._ficha_avatar.setText(estilo_com.iniciales(self._detalle_labels['RAZÓN SOCIAL'].text()))

    def _limpiar_panel_detalle(self):
        self._bloque_plan.hide()
        for etiqueta, campo_col, tipo in CAMPOS_DETALLE_ACTIVACIONES:
            lbl = self._detalle_labels[campo_col]
            if tipo == "chip":
                estilo_com.pintar_chip_ficha(lbl, "")
            else:
                lbl.setText("—")
        self._ficha_avatar.setText("--")

    # ---------------------------------------------------------------
    # ACCIÓN: "Marcar como CONECTADO" -- escribe de verdad en PruebasFM.xlsx
    # (mismo mecanismo que comercial.py: ExcelWriter.update_cells vía
    # SaveExcelThread, y actualización de DataManager.df_master al terminar).
    # Disponible tanto en Activaciones como en Sin Flota: en ambos casos el
    # operador está resolviendo una unidad hacia el estado CONECTADO, y en
    # ambos se fuerza además ESTADO COMERCIAL = Vigente (22-09-2026, cierra
    # el ciclo de reactivación Comercial "Gestionar Bajas" -> Operaciones).
    # Desde Sin Flota (24-09-2026, a pedido explícito), CDB y FLOTA VC son
    # obligatorios (se editan en la tabla) y se guardan junto con el
    # cambio de estado en la misma operación -- ExcelWriter.update_cells ya
    # soporta varias columnas por VIN en una sola llamada.
    # ---------------------------------------------------------------
    def _valor_actual_celda(self, vin, col_name):
        """Valor vigente (editado o no) de `col_name` para `vin` en la
        tabla visible de la sub-pestaña activa -- fuente de verdad para
        FLOTA VC/CDB al guardar (24-09-2026, ver _COLUMNAS_EDITABLES en
        OperacionesTableModel). A diferencia de _cola_full (que guarda el
        valor tal como llegó de la última carga real), self.model.get_df()
        refleja cualquier edición en memoria que el usuario haya hecho
        directo en la celda antes de presionar "Marcar como...", que es
        donde se guarda de verdad (no hay un botón de guardado aparte)."""
        df_visible = self.model.get_df()
        if df_visible.empty or 'VIN' not in df_visible.columns or col_name not in df_visible.columns:
            return None
        mask = df_visible['VIN'].astype(str).str.strip().str.upper() == str(vin).strip().upper()
        fila = df_visible[mask]
        if fila.empty:
            return None
        valor = fila.iloc[0][col_name]
        return '' if pd.isna(valor) else str(valor).strip()

    def _vins_misma_empresa(self, vins, idx):
        """True si todas las unidades comparten razón social o RUT."""
        if len(vins) <= 1:
            return True
        cola = self._cola_full.get(idx, pd.DataFrame())
        if cola.empty:
            return False
        claves = {str(v).strip().upper() for v in vins}
        filas = cola[cola['VIN'].astype(str).str.strip().str.upper().isin(claves)]
        if filas.empty:
            return False

        def unico(col):
            if col not in filas.columns:
                return False
            valores = {self._texto_flota_limpio(v).upper() for v in filas[col]}
            return len(valores) == 1 and '' not in valores

        return unico(COL_RAZON_SOCIAL) or unico(COL_RUT)

    def _flota_editable(self, vins, idx):
        return idx in SUBTABS_CON_DATOS_FLOTA and bool(vins) and self._vins_misma_empresa(vins, idx)

    def _flota_efectiva(self, vin, idx):
        """(CDB flota, Flota VC) con que queda una unidad al guardar: lo escrito
        en el panel (vale para todas las seleccionadas) y, si ese campo está
        vacío, el dato que ya tiene la unidad."""
        cola = self._cola_full.get(idx, pd.DataFrame())
        cdb_act = flota_act = ''
        if not cola.empty:
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == str(vin).strip().upper()]
            if not fila.empty:
                cdb_act = self._texto_flota_limpio(fila.iloc[0].get(COL_CDB_FLOTA))
                flota_act = self._texto_flota_limpio(fila.iloc[0].get(COL_FLOTA_VC))
        return (self.txt_cdb_flota.text().strip() or cdb_act, self.txt_flota_vc.text().strip() or flota_act)

    def _solo_contratos_abiertos(self, vins, idx):
        abiertos, cerrados = operaciones_services.separar_vins_contrato_abierto(self._cola_full.get(idx, pd.DataFrame()), vins)
        if cerrados:
            DialogoAccion.aviso(
                self, "Contrato finalizado",
                "Estos VIN tienen un contrato en baja: solo se pueden desconectar. Si el cliente vuelve, "
                "Comercial crea un contrato nuevo.",
                items=cerrados, titulo_items="VIN con contrato finalizado",
            ).exec()
        return abiertos
