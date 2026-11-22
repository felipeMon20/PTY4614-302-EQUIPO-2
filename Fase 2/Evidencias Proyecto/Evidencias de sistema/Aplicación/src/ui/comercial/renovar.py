"""Modo Renovar de Comercial: panel, selección y ejecución de renovaciones."""
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QMessageBox, QListWidget, QListWidgetItem, QApplication, QAbstractItemView, QCheckBox, QSpinBox
from PyQt6.QtCore import Qt, QSize, QDate
from src.services import comercial_services
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.compartido.selector_fecha import SelectorFecha
from src.theme.theme_manager import ThemeManager
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.constants import COL_ESTADO_COMERCIAL, COL_ETAPA_GESTION, COL_TIPO_FACTURACION, COL_ESTADO_ACTIVACION, COL_RAZON_SOCIAL, COL_CHASIS
from src.ui.comercial.base import SaveExcelThread
from src.ui.comercial.dialogos import DialogoAccionCm
from src.ui.comercial.base import (
    SaveExcelThread,
)
from src.ui.comercial.dialogos import (
    DialogoAccionCm,
)


class _RenovarComercialMixin:
    def _vin_normalizados_base(self):
        """VIN de df_base en mayúsculas y sin espacios, calculado una sola vez por cada versión de df_base
        (se pedía por cada unidad seleccionada y recorría las ~12.000 filas cada vez)."""
        df = self.legacy.df_base
        cache = self.__dict__.get('_cache_vin_base')
        if cache is None or cache[0] is not df:
            cache = self.__dict__['_cache_vin_base'] = (df, df['VIN'].astype(str).str.strip().str.upper())
        return cache[1]

    def _estados_contrato_actual(self, vin):
        """(ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL) del contrato actual de `vin` en df_base."""
        df = self.legacy.df_base
        if df is None or df.empty or 'VIN' not in df.columns:
            return '', ''
        fila = df[self._vin_normalizados_base() == str(vin).strip().upper()]
        if fila.empty:
            return '', ''
        fila = fila.iloc[0]
        return str(fila.get(COL_ESTADO_COMERCIAL, '')), str(fila.get(COL_ESTADO_ACTIVACION, ''))

    def _estados_contratos_actuales(self, vins):
        """[(ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL)] de los contratos actuales de `vins`, en una sola pasada."""
        df = self.legacy.df_base
        if not vins or df is None or df.empty or 'VIN' not in df.columns:
            return []
        claves = {str(v).strip().upper() for v in vins}
        sel = df[self._vin_normalizados_base().isin(claves)]
        activacion = sel[COL_ESTADO_ACTIVACION] if COL_ESTADO_ACTIVACION in sel.columns else [''] * len(sel)
        return list(zip(sel[COL_ESTADO_COMERCIAL].astype(str), activacion))

    def _actualizar_acciones_contrato_cerrado(self, vins):
        """Un contrato en Baja o Baja Solicitada está finalizado: en vez de
        "Editar Unidad" se ofrecen "Ver en General" y "Crear contrato" (este
        último solo si la matriz de nuevo contrato lo permite)."""
        cerrado, puede = False, False
        estados = self._estados_contratos_actuales(vins)
        if estados:
            cerrado = all(comercial_services.es_contrato_cerrado(e) for e, _ in estados)
            puede = cerrado and all(comercial_services.puede_crear_contrato(e, a) for e, a in estados)
        multiple = len(vins) > 1
        self.btn_accion_editar_unidad.setVisible(not (cerrado and not multiple))
        self.btn_accion_ver_general.setVisible(cerrado and not multiple)
        self.btn_accion_ver_general.setEnabled(cerrado and not multiple)
        self.btn_accion_crear_contrato.setVisible(cerrado)
        self.btn_accion_crear_contrato.setEnabled(cerrado and puede)
        self.btn_accion_crear_contrato._titulo_lbl.setText("Crear contratos" if multiple else "Crear contrato")
        self.btn_accion_crear_contrato.setToolTip(
            "" if puede or not cerrado else
            "Alguna unidad sigue Activando o Conectada: no se puede crear otro contrato todavía.")

    def _on_accion_ver_general_clicked(self):
        vins, _ = self._obtener_vins_seleccionados()
        if len(vins) != 1:
            return
        abrir = getattr(self.window(), 'abrir_unidad_en_general', None)
        if abrir is not None:
            abrir(vins[0])

    def _on_accion_crear_contrato_clicked(self):
        """Abre "Unidad nueva" en modo "Nuevo contrato" con los datos de la
        unidad y del cliente; las condiciones comerciales quedan en blanco."""
        vins, _ = self._obtener_vins_seleccionados()
        if not vins:
            return
        if len(self._estados_contratos_actuales(vins)) != len(vins) or not all(
                comercial_services.puede_crear_contrato(e, a) for e, a in self._estados_contratos_actuales(vins)):
            return
        df = self.legacy.df_base
        claves = [v.strip().upper() for v in vins]
        vin_df = df['VIN'].astype(str).str.strip().str.upper()
        datos_por_vin = {}
        for _, fila in df[vin_df.isin(claves)].iterrows():
            datos_por_vin[str(fila['VIN']).strip().upper()] = {col: ('' if pd.isna(val) else str(val)) for col, val in fila.items()}
        if len(datos_por_vin) > 1:
            self._iniciar_nuevo_contrato_multiple(datos_por_vin)
            return
        self._iniciar_nuevo_contrato(next(iter(datos_por_vin.values())))

    def _filas_renovables_seleccionadas(self):
        """{vin: fila} de la selección actual que se puede renovar (ver
        comercial_services.calcular_renovacion). Solo en "Renovar contratos"."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            return {}
        _, filas_por_vin = self._obtener_vins_seleccionados()
        return {vin: fila for vin, fila in filas_por_vin.items() if comercial_services.calcular_renovacion(fila, 1)}

    def _actualizar_boton_renovar(self):
        self.btn_accion_renovar.setEnabled(bool(self._filas_renovables_seleccionadas()))
        self.btn_accion_renovar_nuevo.setEnabled(
            self._vin_para_renovar_con_nuevo_contrato() is not None or bool(self._vins_para_renovar_multiple()))

    def _vins_para_renovar_multiple(self):
        """VIN de la selección (2 o más) en "Renovar contratos" si todos se pueden reemplazar por
        un contrato nuevo; lista vacía en otro caso."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            return []
        vins, _ = self._obtener_vins_seleccionados()
        if len(vins) < 2:
            return []
        estados = self._estados_contratos_actuales(vins)
        if len(estados) != len(vins):
            return []
        for estado, activacion in estados:
            if not comercial_services.puede_renovar_con_nuevo_contrato(estado, activacion):
                return []
        return vins

    def _iniciar_renovacion_multiple(self, vins):
        df = self.legacy.df_base
        datos_por_vin = {}
        for vin in vins:
            fila = df[df['VIN'].astype(str).str.strip().str.upper() == vin.strip().upper()].iloc[0]
            datos_por_vin[vin.strip().upper()] = {col: ('' if pd.isna(val) else str(val)) for col, val in fila.items()}
        primero = next(iter(datos_por_vin.values()))
        self._iniciar_nuevo_contrato(primero, renovacion={
            'datos_por_vin': datos_por_vin, 'prototipo': dict(primero)})

    def _vin_para_renovar_con_nuevo_contrato(self):
        """VIN de la única unidad seleccionada en "Renovar contratos" cuyo
        contrato es Vigente o Vencido (o está en Revisar y Conectada); None en cualquier otro caso."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            return None
        vins, _ = self._obtener_vins_seleccionados()
        if len(vins) != 1:
            return None
        estado, activacion = self._estados_contrato_actual(vins[0])
        return vins[0] if comercial_services.puede_renovar_con_nuevo_contrato(estado, activacion) else None

    def _on_accion_renovar_nuevo_clicked(self):
        """"Nuevo contrato": abre el formulario de contrato nuevo precargado con
        la unidad (ver ComercialUnidadFormWidget.cargar_para_nuevo_contrato,
        modo renovación). Al guardar, el contrato actual pasa a Renovado."""
        multiples = self._vins_para_renovar_multiple()
        if multiples:
            self._iniciar_renovacion_multiple(multiples)
            return
        vin = self._vin_para_renovar_con_nuevo_contrato()
        if vin is None:
            return
        df = self.legacy.df_base
        fila = df[df['VIN'].astype(str).str.strip().str.upper() == vin.strip().upper()].iloc[0]
        datos = {col: ('' if pd.isna(val) else str(val)) for col, val in fila.items()}
        self._iniciar_nuevo_contrato(datos, renovacion={
            'vin': vin.strip().upper(), 'id': str(datos.get('ID', '')).strip(),
            'cambios': comercial_services.cambios_contrato_renovado(datos)})

    def _on_accion_renovar_clicked(self):
        """"Renovar contrato": el panel derecho pasa a un formulario (meses y
        contratos a renovar) en vez de abrir una ventana aparte."""
        if not self._filas_renovables_seleccionadas():
            return
        self.chk_renovar_inicio.setChecked(False)
        self.selector_renovar_inicio.setDate(QDate.currentDate())
        self._set_modo_renovar(True)
        self._renovar_actualizar_seleccion()

    def _set_modo_renovar(self, activo):
        self._renovar_modo_activo = activo
        self.panel_renovar.setVisible(activo)
        self._titulo_acciones.setVisible(not activo)
        self.acciones_rapidas_comunes.setVisible(not activo)
        if activo:
            for w in (self.acciones_rapidas_cm, self.acciones_rapidas_vencidos,
                      self.acciones_rapidas_vigentes, self.acciones_rapidas_papelera,
                      self.acciones_rapidas_conversion,
                      self.acciones_rapidas_inconsistencias, self.acciones_rapidas_fechas):
                w.hide()
        else:
            self._ficha_contenedor.show()

    def _salir_modo_renovar(self):
        self._set_modo_renovar(False)
        self._toggle_acciones_rapidas_panel(getattr(self, '_new_ui_active_subtab', 0))

    def _build_new_ui_panel_renovar(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(10)
        estilo_tarjeta = (
            f"QFrame#tarjetaRenovar {{ background-color: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; "
            "border-radius: 12px; } QFrame#tarjetaRenovar QLabel { background: transparent; border: none; }")

        cabecera = QHBoxLayout()
        cabecera.setSpacing(8)
        self.btn_renovar_volver = QPushButton()
        self.btn_renovar_volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color=estilo_com.APAGADO))
        self.btn_renovar_volver.setFixedSize(28, 28)
        self.btn_renovar_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_renovar_volver.setToolTip("Volver a las acciones rápidas")
        self.btn_renovar_volver.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        self.btn_renovar_volver.clicked.connect(self._salir_modo_renovar)
        self.lbl_renovar_titulo = QLabel("Extender duración")
        self.lbl_renovar_titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 14px; font-weight: 800;")
        cabecera.addWidget(self.btn_renovar_volver)
        cabecera.addWidget(self.lbl_renovar_titulo)
        cabecera.addStretch()
        lay.addLayout(cabecera)

        tarjeta_meses = QFrame()
        tarjeta_meses.setObjectName("tarjetaRenovar")
        tarjeta_meses.setStyleSheet(estilo_tarjeta)
        lay_meses = QVBoxLayout(tarjeta_meses)
        lay_meses.setContentsMargins(12, 10, 12, 12)
        lay_meses.setSpacing(8)
        lay_meses.addWidget(self._titulo_seccion("Meses a extender"))
        qss_paso = (f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; "
                    f"border-radius: 10px; color: {estilo_com.PRIMARIO}; font-size: 18px; font-weight: 700; }}"
                    f"QPushButton:hover {{ border: 1px solid {estilo_com.PRIMARIO}; }}")
        fila_meses = QHBoxLayout()
        fila_meses.setSpacing(8)
        self.btn_renovar_menos = QPushButton("−")
        self.btn_renovar_mas = QPushButton("+")
        for btn in (self.btn_renovar_menos, self.btn_renovar_mas):
            btn.setFixedSize(38, 38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(qss_paso)
        self.spin_renovar_meses = QSpinBox()
        self.spin_renovar_meses.setRange(1, 120)
        self.spin_renovar_meses.setValue(12)
        self.spin_renovar_meses.setSuffix(" meses")
        self.spin_renovar_meses.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_renovar_meses.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_renovar_meses.setFixedHeight(38)
        self.spin_renovar_meses.setStyleSheet(
            f"QSpinBox {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.PRIMARIO}; "
            f"border-radius: 10px; color: {estilo_com.TINTA}; font-size: 16px; font-weight: 700; }}")
        self.btn_renovar_menos.clicked.connect(lambda: self.spin_renovar_meses.stepBy(-1))
        self.btn_renovar_mas.clicked.connect(lambda: self.spin_renovar_meses.stepBy(1))
        fila_meses.addWidget(self.btn_renovar_menos)
        fila_meses.addWidget(self.spin_renovar_meses, stretch=1)
        fila_meses.addWidget(self.btn_renovar_mas)
        lay_meses.addLayout(fila_meses)

        fila_atajos = QHBoxLayout()
        fila_atajos.setSpacing(6)
        self._chips_renovar = {}
        qss_chip = (f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; "
                    f"border-radius: 12px; padding: 3px 12px; color: {estilo_com.APAGADO}; font-weight: 600; font-size: 11px; }}"
                    f"QPushButton:checked {{ background-color: {estilo_com.PRIMARIO_SUAVE}; color: {estilo_com.PRIMARIO}; "
                    f"border: 1px solid {estilo_com.PRIMARIO}; }}")
        for meses in (6, 12, 24, 36):
            chip = QPushButton(str(meses))
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(qss_chip)
            chip.clicked.connect(lambda _c=False, m=meses: self.spin_renovar_meses.setValue(m))
            fila_atajos.addWidget(chip)
            self._chips_renovar[meses] = chip
        fila_atajos.addStretch()
        lay_meses.addLayout(fila_atajos)

        lay_inicio = QHBoxLayout()
        lay_inicio.setSpacing(8)
        self.chk_renovar_inicio = QCheckBox("Cambiar inicio")
        self.chk_renovar_inicio.setStyleSheet(
            f"QCheckBox {{ color: {estilo_com.TINTA}; font-weight: 700; font-size: 12px; background: transparent; spacing: 8px; }}"
            f"QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {estilo_com.APAGADO}; "
            f"border-radius: 4px; background: {estilo_com.SUPERFICIE}; }}"
            f"QCheckBox::indicator:checked {{ background: {estilo_com.PRIMARIO}; border: 1px solid {estilo_com.PRIMARIO}; }}")
        self.selector_renovar_inicio = SelectorFecha(QDate.currentDate())
        self.selector_renovar_inicio.setEnabled(False)
        self.chk_renovar_inicio.toggled.connect(self.selector_renovar_inicio.setEnabled)
        self.chk_renovar_inicio.toggled.connect(self._renovar_actualizar_vista)
        self.selector_renovar_inicio.dateChanged.connect(self._renovar_actualizar_vista)
        lay_inicio.addWidget(self.chk_renovar_inicio)
        lay_inicio.addStretch()
        lay_inicio.addWidget(self.selector_renovar_inicio)
        lay_meses.addLayout(lay_inicio)
        lay.addWidget(tarjeta_meses)

        self.tarjeta_renovar_cambios = QFrame()
        self.tarjeta_renovar_cambios.setObjectName("tarjetaRenovar")
        self.tarjeta_renovar_cambios.setStyleSheet(estilo_tarjeta)
        lay_cambios = QVBoxLayout(self.tarjeta_renovar_cambios)
        lay_cambios.setContentsMargins(12, 10, 12, 12)
        lay_cambios.setSpacing(8)
        self.lbl_renovar_cambios_titulo = self._titulo_seccion("Lo que va a cambiar")
        lay_cambios.addWidget(self.lbl_renovar_cambios_titulo)
        self.chk_renovar_todas = QCheckBox("Seleccionar todas")
        qss_casilla = (f"::indicator {{ width: 16px; height: 16px; border: 1px solid {estilo_com.APAGADO}; "
                       f"border-radius: 4px; background: {estilo_com.SUPERFICIE}; }}"
                       f"::indicator:checked {{ background: {estilo_com.PRIMARIO}; border: 1px solid {estilo_com.PRIMARIO}; }}")
        self.chk_renovar_todas.setStyleSheet(
            f"QCheckBox {{ color: {estilo_com.TINTA}; font-weight: 700; font-size: 12px; background: transparent; spacing: 8px; }}"
            f"QCheckBox{qss_casilla}")
        self.chk_renovar_todas.clicked.connect(self._renovar_marcar_todas)
        lay_cambios.addWidget(self.chk_renovar_todas)
        self.lista_renovar = QListWidget()
        self.lista_renovar.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.lista_renovar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lista_renovar.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.lista_renovar.setStyleSheet(
            f"QListWidget {{ background: transparent; border: none; outline: none; }}"
            f"QListWidget::item {{ border-bottom: 1px solid {estilo_com.LINEA}; padding: 6px 2px; color: {estilo_com.TINTA}; font-size: 11px; }}"
            f"QListWidget{qss_casilla}")
        self.lista_renovar.itemChanged.connect(self._renovar_item_cambiado)
        lay_cambios.addWidget(self.lista_renovar)
        self.lbl_renovar_detalle = QLabel("")
        self.lbl_renovar_detalle.setWordWrap(True)
        self.lbl_renovar_detalle.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_renovar_detalle.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px;")
        lay_cambios.addWidget(self.lbl_renovar_detalle)
        lay.addWidget(self.tarjeta_renovar_cambios)

        self.lbl_renovar_omitidos = QLabel("")
        self.lbl_renovar_omitidos.setWordWrap(True)
        self.lbl_renovar_omitidos.setStyleSheet(
            f"background-color: #FFF1D6; color: {estilo_com.AMBAR}; border-radius: 10px; padding: 8px 10px; "
            "font-size: 11px; font-weight: 600;")
        lay.addWidget(self.lbl_renovar_omitidos)

        self.btn_renovar_confirmar = QPushButton("Extender duración")
        self.btn_renovar_confirmar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_renovar_confirmar.setMinimumHeight(40)
        self.btn_renovar_confirmar.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR)
        self.btn_renovar_confirmar.clicked.connect(self._on_renovar_confirmar_clicked)
        self.btn_renovar_cancelar = QPushButton("Cancelar")
        self.btn_renovar_cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_renovar_cancelar.setMinimumHeight(40)
        self.btn_renovar_cancelar.setStyleSheet(
            f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 10px; "
            f"color: {estilo_com.APAGADO}; font-weight: 700; font-size: 13px; }}"
            f"QPushButton:hover {{ border: 1px solid {estilo_com.PRIMARIO}; color: {estilo_com.PRIMARIO}; }}")
        self.btn_renovar_cancelar.clicked.connect(self._salir_modo_renovar)
        lay.addWidget(self.btn_renovar_confirmar)
        lay.addWidget(self.btn_renovar_cancelar)

        self.spin_renovar_meses.valueChanged.connect(self._renovar_actualizar_vista)
        return panel

    @staticmethod
    def _texto_renovar(valor):
        texto = '' if valor is None else str(valor).strip()
        return '-' if texto.upper() in ('', 'NAN', 'NONE', 'NAT') else texto

    def _renovar_nuevo_inicio(self):
        """Fecha de inicio elegida para todos los contratos, o None si no se cambia."""
        if not self.chk_renovar_inicio.isChecked():
            return None
        return self.selector_renovar_inicio.date().toPyDate()

    def _renovar_cambio_de_fila(self, fila, meses):
        """(duración, término, estado) antes y después de renovar `fila`."""
        cambios = comercial_services.calcular_renovacion(fila, meses, self._renovar_nuevo_inicio()) or {}
        estado = self._texto_renovar(fila.get(COL_ESTADO_COMERCIAL)).capitalize()
        return (
            (self._texto_renovar(fila.get('DURACIÓN (MESES)')), cambios.get('DURACIÓN (MESES)', '-')),
            (self._texto_renovar(fila.get('TÉRMINO CONTRATO')), cambios.get('TÉRMINO CONTRATO', '-')),
            (estado, cambios.get(COL_ESTADO_COMERCIAL, estado).capitalize()),
        )

    def _renovar_actualizar_seleccion(self):
        """Rearma la lista con la selección actual de la tabla. Conserva las
        marcas ya hechas; sin contratos renovables vuelve a las acciones."""
        if not getattr(self, '_renovar_modo_activo', False):
            return
        vins, _ = self._obtener_vins_seleccionados()
        renovables = self._filas_renovables_seleccionadas()
        if not renovables:
            self._salir_modo_renovar()
            return
        previas = {self.lista_renovar.item(i).data(Qt.ItemDataRole.UserRole):
                   self.lista_renovar.item(i).checkState() for i in range(self.lista_renovar.count())}
        self._renovar_filas = renovables
        self.lista_renovar.blockSignals(True)
        self.lista_renovar.clear()
        for vin, fila in renovables.items():
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, vin)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(previas.get(vin, Qt.CheckState.Checked))
            self.lista_renovar.addItem(item)
        self.lista_renovar.blockSignals(False)

        varios = len(renovables) > 1
        self._ficha_contenedor.setVisible(False)
        self.lbl_renovar_titulo.setText("Extender duración")
        self.lbl_renovar_cambios_titulo.setText("Contratos a renovar" if varios else "Lo que va a cambiar")
        self.chk_renovar_todas.setVisible(varios)
        self.lista_renovar.setVisible(varios)
        self.lbl_renovar_detalle.setVisible(True)
        omitidos = len(vins) - len(renovables)
        self.lbl_renovar_omitidos.setVisible(omitidos > 0)
        if omitidos > 0:
            self.lbl_renovar_omitidos.setText(
                f"{omitidos} de las filas seleccionadas no se pueden renovar (por ejemplo, duración MENSUAL) y se dejan igual.")
        self._renovar_actualizar_vista()

    def _renovar_actualizar_vista(self, *_):
        """Recalcula textos con los meses elegidos: atajos, lista, resumen y botón."""
        if not getattr(self, '_renovar_modo_activo', False) or not self._renovar_filas:
            return
        meses = self.spin_renovar_meses.value()
        for valor, chip in self._chips_renovar.items():
            chip.setChecked(valor == meses)
        marcados = 0
        self.lista_renovar.blockSignals(True)
        for i in range(self.lista_renovar.count()):
            item = self.lista_renovar.item(i)
            vin = item.data(Qt.ItemDataRole.UserRole)
            fila = self._renovar_filas.get(vin)
            if fila is None:
                continue
            _duracion, (termino_antes, termino_despues), _estado = self._renovar_cambio_de_fila(fila, meses)
            item.setText(f"{self._texto_renovar(fila.get(COL_RAZON_SOCIAL))} · {self._texto_renovar(fila.get(COL_CHASIS))}"
                         f"\n{termino_antes} → {termino_despues}")
            item.setSizeHint(QSize(0, 46))
            if item.checkState() == Qt.CheckState.Checked:
                marcados += 1
        self.lista_renovar.blockSignals(False)
        total = len(self._renovar_filas)
        self.lista_renovar.setFixedHeight(min(total, 4) * 46 + 4)
        self.chk_renovar_todas.blockSignals(True)
        self.chk_renovar_todas.setChecked(marcados == total)
        self.chk_renovar_todas.blockSignals(False)

        nuevo_inicio = self._renovar_nuevo_inicio()
        if total == 1:
            fila_unica = next(iter(self._renovar_filas.values()))
            (dur_antes, dur_despues), (ter_antes, ter_despues), (est_antes, est_despues) = \
                self._renovar_cambio_de_fila(fila_unica, meses)
            tachado = f"color:{estilo_com.APAGADO}; text-decoration:line-through;"
            fila_inicio = ""
            if nuevo_inicio is not None:
                fila_inicio = (f"<tr><td style='color:{estilo_com.APAGADO}'>Inicio</td><td><span style='{tachado}'>"
                               f"{self._texto_renovar(fila_unica.get('INICIO CONTRATO'))}</span> → "
                               f"<b>{nuevo_inicio.strftime('%d-%m-%Y')}</b></td></tr>")
            self.lbl_renovar_detalle.setText(
                f"<b>{self._texto_renovar(fila_unica.get(COL_RAZON_SOCIAL))}</b> · {self._texto_renovar(fila_unica.get(COL_CHASIS))}"
                "<table cellspacing='4'>" + fila_inicio +
                ""
                f"<tr><td style='color:{estilo_com.APAGADO}'>Duración</td><td><span style='{tachado}'>{dur_antes} meses</span> → <b>{dur_despues} meses</b></td></tr>"
                f"<tr><td style='color:{estilo_com.APAGADO}'>Término</td><td><span style='{tachado}'>{ter_antes}</span> → <b>{ter_despues}</b></td></tr>"
                f"<tr><td style='color:{estilo_com.APAGADO}'>Estado</td><td><span style='{tachado}'>{est_antes}</span> → <b>{est_despues}</b></td></tr>"
                "</table>")
        else:
            texto = f"Se suman {meses} meses a {marcados} de {total} contratos."
            if nuevo_inicio is not None:
                texto += f" El inicio pasa a {nuevo_inicio.strftime('%d-%m-%Y')} en todos."
            self.lbl_renovar_detalle.setText(texto)
        if total == 1:
            self.btn_renovar_confirmar.setText("Extender duración")
        else:
            self.btn_renovar_confirmar.setText(f"Extender {marcados} contrato(s)")
        self.btn_renovar_confirmar.setEnabled(marcados >= 1)

    def _renovar_item_cambiado(self, _item):
        self._renovar_actualizar_vista()

    def _renovar_marcar_todas(self, marcar):
        self.lista_renovar.blockSignals(True)
        for i in range(self.lista_renovar.count()):
            self.lista_renovar.item(i).setCheckState(Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
        self.lista_renovar.blockSignals(False)
        self._renovar_actualizar_vista()

    def _on_renovar_confirmar_clicked(self):
        filas = {}
        for i in range(self.lista_renovar.count()):
            item = self.lista_renovar.item(i)
            vin = item.data(Qt.ItemDataRole.UserRole)
            if item.checkState() == Qt.CheckState.Checked and vin in self._renovar_filas:
                filas[vin] = self._renovar_filas[vin]
        if filas:
            self._ejecutar_renovacion(filas, self.spin_renovar_meses.value())

    def _ejecutar_renovacion(self, filas, meses):
        """Suma `meses` a DURACIÓN (MESES) de los contratos elegidos; el
        término se recalcula y el contrato conserva su ID."""
        nuevo_inicio = self._renovar_nuevo_inicio()
        self._salir_modo_renovar()
        valid = {}
        for vin, fila in filas.items():
            cambios = comercial_services.calcular_renovacion(fila, meses, nuevo_inicio)
            if cambios.get(COL_ESTADO_COMERCIAL):
                row_para_matriz = {
                    COL_ESTADO_COMERCIAL: cambios[COL_ESTADO_COMERCIAL].capitalize(),
                    COL_ESTADO_ACTIVACION: fila.get(COL_ESTADO_ACTIVACION, ''),
                    COL_TIPO_FACTURACION: fila.get(COL_TIPO_FACTURACION, ''),
                    COL_ETAPA_GESTION: fila.get(COL_ETAPA_GESTION, ''),
                }
                cambios[COL_ETAPA_GESTION] = DataFrameFormatter.calcular_etapa_gestion_esperada(row_para_matriz)
                cambios[COL_ESTADO_COMERCIAL] = cambios[COL_ESTADO_COMERCIAL].capitalize()
            valid[vin] = {'VIN': vin, 'cambios': cambios}
        comercial_services.agregar_id_a_cambios(valid, self.legacy.df_base)

        self.btn_accion_renovar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Renovando contratos…")
        self._renovar_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._renovar_thread.finished_signal.connect(lambda success: self._on_renovar_finished(success, valid))
        self._renovar_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._renovar_thread.start()

    def _on_renovar_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self, "No se pudo guardar la renovación. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        refrescos = self.__dict__.get('_n_refrescos', 0)
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            # df_base al día antes de avisar: el aviso (data_ready) repinta esta bandeja una vez
            self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
            dm.data_ready.emit()
        else:
            self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
        if self.__dict__.get('_n_refrescos', 0) == refrescos:   # nadie la repintó (p. ej. pestaña oculta)
            self._refresh_new_ui_data()
        terminar_guardando(self, texto_exito="Contratos renovados")
        QMessageBox.information(self, "Renovación", f"Se renovó {len(valid)} contrato(s).")
