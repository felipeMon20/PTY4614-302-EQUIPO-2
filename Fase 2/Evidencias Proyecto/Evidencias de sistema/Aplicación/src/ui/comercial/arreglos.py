"""Arreglos de fechas, inconsistencias y tipo de facturación de Comercial."""
import pandas as pd
from src.theme.colors import PRIMARY
from src.theme.theme_manager import ThemeManager
from PyQt6.QtWidgets import QDialog, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
from PyQt6.QtCore import Qt, QDate
from src.services import comercial_services, operaciones_services
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.selector_fecha import CalendarioEmbebido
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.constants import COL_ESTADO_COMERCIAL, COL_ETAPA_GESTION, COL_TIPO_FACTURACION, COL_ESTADO_ACTIVACION, COL_FECHA_BAJA, VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_FACTURACION_MANUAL
from src.ui.comercial.base import SaveExcelThread
from src.ui.comercial.dialogos import DialogoAccionCm
from src.ui.comercial.base import (
    SaveExcelThread,
)
from src.ui.comercial.dialogos import (
    DialogoAccionCm,
)


class _ArreglosComercialMixin:
    def _actualizar_boton_arreglar_fechas(self):
        """Visible solo con "Revisar fechas" activo; cuenta los contratos que se corrigen."""
        activo = bool(getattr(self.legacy, '_filtro_fechas_contrato_activo', False))
        self.btn_arreglar_fechas_barra.setVisible(activo)
        if not activo:
            return
        cantidad = len(comercial_services.construir_correcciones_termino(
            self.legacy._df_fechas_contrato, self.legacy.df_base))
        self.btn_arreglar_fechas_barra.setText(f" Arreglar fechas ({cantidad})")
        self.btn_arreglar_fechas_barra.setEnabled(cantidad > 0)
        self.btn_arreglar_fechas_barra.setToolTip(
            f"Graba en el archivo el término calculado (inicio + duración) de {cantidad} contrato(s).")

    def _actualizar_boton_fecha_real(self):
        btn = getattr(self, 'btn_accion_fecha_real', None)
        if btn is None or not self.acciones_rapidas_fechas.isVisibleTo(self._panel_acciones):
            return
        vins, _ = self._obtener_vins_seleccionados()
        btn.setEnabled(bool(vins))
        btn.setToolTip("Graba en el archivo el término calculado de las unidades seleccionadas"
                       if vins else "Selecciona una o varias unidades")

    def _filas_sin_fecha_baja(self):
        """Contratos actuales de la selección con la unidad Desconectada y sin FECHA DE BAJA: no cuentan
        como baja en ningún mes del Dashboard hasta que se les asigne una."""
        vins, _ = self._obtener_vins_seleccionados()
        df = getattr(self.legacy, 'df_base', None)
        if not vins or df is None or df.empty or 'VIN' not in df.columns or COL_ESTADO_ACTIVACION not in df.columns:
            return pd.DataFrame()
        sel = comercial_services.contratos_actuales(df[self._vin_normalizados_base().isin(set(vins))])
        desconectada = sel[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper() == 'DESCONECTADO'
        fecha = sel[COL_FECHA_BAJA] if COL_FECHA_BAJA in sel.columns else pd.Series('', index=sel.index)
        sin_fecha = fecha.fillna('').astype(str).str.strip().str.lower().isin(('', '-', 'nan', 'none'))
        return sel[desconectada & sin_fecha]

    def _actualizar_boton_fecha_baja(self):
        """Muestra el botón solo si la selección tiene unidades por fechar; si el panel de fecha está abierto
        lo mantiene al día con la selección y lo cierra cuando ya no queda ninguna."""
        btn = getattr(self, 'btn_accion_fecha_baja', None)
        if btn is None:
            return
        n = len(self._filas_sin_fecha_baja())
        btn.setVisible(n > 0)
        btn.setEnabled(n > 0)
        btn.setToolTip(f"Graba la fecha de baja de {n} unidad(es) desconectada(s) que no la tienen" if n else "")
        if self.__dict__.get('_fecha_baja_modo_activo'):
            if n:
                self._pintar_panel_fecha_baja(n)
            else:
                self._set_modo_fecha_baja(False)

    def _build_new_ui_panel_fecha_baja(self):
        """Panel de la caja derecha para elegir la fecha de baja (reemplaza a las acciones rápidas mientras está abierto)."""
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(10)
        cabecera = QHBoxLayout()
        cabecera.setSpacing(8)
        volver = QPushButton()
        volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color=estilo_com.APAGADO))
        volver.setFixedSize(28, 28)
        volver.setCursor(Qt.CursorShape.PointingHandCursor)
        volver.setToolTip("Volver a las acciones rápidas")
        volver.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        volver.clicked.connect(lambda: self._set_modo_fecha_baja(False))
        titulo = QLabel("Asignar fecha de baja")
        titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 14px; font-weight: 800;")
        cabecera.addWidget(volver)
        cabecera.addWidget(titulo)
        cabecera.addStretch()
        lay.addLayout(cabecera)

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaFechaBaja")
        tarjeta.setStyleSheet(
            f"QFrame#tarjetaFechaBaja {{ background-color: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; "
            "border-radius: 12px; } QFrame#tarjetaFechaBaja QLabel { background: transparent; border: none; }")
        lay_t = QVBoxLayout(tarjeta)
        lay_t.setContentsMargins(12, 10, 12, 12)
        lay_t.setSpacing(8)
        self.lbl_fecha_baja_resumen = QLabel("")
        self.lbl_fecha_baja_resumen.setWordWrap(True)
        self.lbl_fecha_baja_resumen.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_fecha_baja_resumen.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 12px;")
        lay_t.addWidget(self.lbl_fecha_baja_resumen)
        self.lbl_fecha_baja_nueva = QLabel("")
        self.lbl_fecha_baja_nueva.setStyleSheet(f"color: {estilo_com.AZUL}; font-size: 13px; font-weight: 800;")
        lay_t.addWidget(self.lbl_fecha_baja_nueva)
        self.calendario_fecha_baja_comercial = CalendarioEmbebido(QDate.currentDate())
        self.calendario_fecha_baja_comercial.fecha_elegida.connect(
            lambda f: self.lbl_fecha_baja_nueva.setText(f"Fecha de baja: {f.toString('dd-MM-yyyy')}"))
        lay_t.addWidget(self.calendario_fecha_baja_comercial, alignment=Qt.AlignmentFlag.AlignHCenter)
        aviso = QLabel("Solo se graba la fecha de baja: el estado y los demás datos del contrato no cambian. "
                       "Con ella la baja cuenta en ese mes en el Dashboard.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 11px;")
        lay_t.addWidget(aviso)
        lay.addWidget(tarjeta)

        self.btn_fecha_baja_guardar = QPushButton(" Guardar fecha")
        self.btn_fecha_baja_guardar.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        self.btn_fecha_baja_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fecha_baja_guardar.setMinimumHeight(40)
        self.btn_fecha_baja_guardar.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR)
        self.btn_fecha_baja_guardar.clicked.connect(self._on_guardar_fecha_baja_clicked)
        cancelar = QPushButton("Cancelar")
        cancelar.setCursor(Qt.CursorShape.PointingHandCursor)
        cancelar.setMinimumHeight(40)
        cancelar.setStyleSheet(
            f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 10px; "
            f"color: {estilo_com.APAGADO}; font-weight: 700; font-size: 13px; }}"
            f"QPushButton:hover {{ border: 1px solid {estilo_com.PRIMARIO}; color: {estilo_com.PRIMARIO}; }}")
        cancelar.clicked.connect(lambda: self._set_modo_fecha_baja(False))
        lay.addWidget(self.btn_fecha_baja_guardar)
        lay.addWidget(cancelar)
        return panel

    def _set_modo_fecha_baja(self, activo):
        self.__dict__['_fecha_baja_modo_activo'] = activo
        self.panel_fecha_baja.setVisible(activo)
        self._titulo_acciones.setVisible(not activo)
        self.acciones_rapidas_comunes.setVisible(not activo)
        self._mostrar_ficha_y_observaciones(not activo)
        if activo:
            for w in (self.acciones_rapidas_cm, self.acciones_rapidas_vencidos, self.acciones_rapidas_vigentes,
                      self.acciones_rapidas_papelera, self.acciones_rapidas_conversion,
                      self.acciones_rapidas_inconsistencias, self.acciones_rapidas_fechas):
                w.hide()
        else:
            self._toggle_acciones_rapidas_panel(getattr(self, '_new_ui_active_subtab', 0))

    def _mostrar_ficha_y_observaciones(self, visible):
        """Con el panel de fecha abierto, la caja derecha solo muestra ese panel: se ocultan la ficha de arriba y las observaciones."""
        for w in (self._ficha_contenedor, self.__dict__.get('_titulo_observaciones'), self.txt_observaciones,
                  self.btn_guardar_observaciones):
            if w is not None:
                w.setVisible(visible)

    def _pintar_panel_fecha_baja(self, n):
        total = len(self._filas_seleccionadas())
        texto = f"<b>{n} unidad{'' if n == 1 else 'es'} desconectada{'' if n == 1 else 's'}</b> sin fecha de baja."
        if total > n:
            texto += f" Las otras {total - n} seleccionadas no cambian."
        self.lbl_fecha_baja_resumen.setText(texto)

    def _on_accion_fecha_baja_clicked(self):
        n = len(self._filas_sin_fecha_baja())
        if not n:
            return
        hoy = QDate.currentDate()
        self.calendario_fecha_baja_comercial.poner_fecha(hoy)
        self.lbl_fecha_baja_nueva.setText(f"Fecha de baja: {hoy.toString('dd-MM-yyyy')}")
        self._pintar_panel_fecha_baja(n)
        self._set_modo_fecha_baja(True)

    def _on_guardar_fecha_baja_clicked(self):
        filas = self._filas_sin_fecha_baja()
        if filas.empty:
            self._set_modo_fecha_baja(False)
            return
        fecha = self.calendario_fecha_baja_comercial.fecha().toString("dd-MM-yyyy")
        cambios = operaciones_services.calcular_cambios_fecha_baja(fecha)
        valid = {}
        for vin in filas['VIN'].astype(str).str.strip().str.upper():
            valid[vin] = {'VIN': vin, 'cambios': dict(cambios)}
        comercial_services.agregar_id_a_cambios(valid, self.legacy.df_base)
        self.btn_fecha_baja_guardar.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Guardando la fecha de baja…")
        self._fecha_baja_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._fecha_baja_thread.finished_signal.connect(lambda success: self._on_fecha_baja_finished(success, valid))
        self._fecha_baja_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._fecha_baja_thread.start()

    def _on_fecha_baja_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self.btn_fecha_baja_guardar.setEnabled(True)
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self, "No se pudo guardar la fecha de baja. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return
        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()
        self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
        self._set_modo_fecha_baja(False)
        self._refresh_new_ui_data()
        self._actualizar_estado_acciones_rapidas()
        terminar_guardando(self)

    def _on_fecha_real_seleccion_clicked(self):
        vins, _ = self._obtener_vins_seleccionados()
        if vins:
            self._arreglar_fechas(vins)

    def _on_arreglar_fechas_clicked(self):
        self._arreglar_fechas(None)

    def _arreglar_fechas(self, vins):
        correcciones = comercial_services.construir_correcciones_termino(
            self.legacy._df_fechas_contrato, self.legacy.df_base, vins)
        if not correcciones:
            return
        if len(correcciones) > 1:
            dialogo = DialogoAccion(
                self, " Arreglar fechas", icon_name="fa5s.magic", icon_color=PRIMARY, icon_bg_color="#EFF6FF",
                titulo="Arreglar fechas", subtitulo=f"{len(correcciones)} contrato(s) se corregirán",
                descripcion="Se graba en el archivo el término calculado con INICIO CONTRATO + DURACIÓN (MESES). "
                            "No cambia ninguna otra columna.",
                botones=[{'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                         {'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}])
            if dialogo.exec() != QDialog.DialogCode.Accepted:
                return
        self.btn_arreglar_fechas_barra.setEnabled(False)
        self.btn_accion_fecha_real.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Corrigiendo fechas…")
        self._arreglar_fechas_thread = SaveExcelThread(self.legacy.writer, correcciones, module_name="Comercial")
        self._arreglar_fechas_thread.finished_signal.connect(
            lambda success: self._on_arreglar_fechas_finished(success, correcciones))
        self._arreglar_fechas_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._arreglar_fechas_thread.start()

    def _on_arreglar_fechas_finished(self, success, correcciones):
        QApplication.restoreOverrideCursor()
        if not success:
            terminar_guardando(self, exito=False)
            self._actualizar_boton_arreglar_fechas()
            self._actualizar_boton_fecha_real()
            DialogoAccionCm.error(
                self, "No se pudo guardar la corrección. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return
        guardado_listo(self)
        dm = self.legacy.data_manager
        for vin, data in correcciones.items():
            dm.termino_distinto_de_duracion.pop(
                comercial_services._clave_contrato(vin, data.get('ID', '')), None)
        self.legacy._df_fechas_contrato = comercial_services.filtrar_termino_distinto_de_duracion(
            self.legacy.df_base, dm.termino_distinto_de_duracion)
        self.legacy._actualizar_tooltip_fechas_contrato()
        if self.legacy._df_fechas_contrato.empty:
            self.legacy.btn_revisar_fechas_contrato.setChecked(False)
        else:
            self._refresh_new_ui_data()
        self._actualizar_boton_arreglar_fechas()
        self._actualizar_estado_acciones_rapidas()
        terminar_guardando(self)

    def _actualizar_boton_arreglar_inconsistencias(self):
        """Visible solo con "Revisar inconsistencias" activo; muestra cuántas
        unidades se pueden corregir de forma automática."""
        btn = getattr(self, 'btn_arreglar_inconsistencias_barra', None)
        if btn is None:
            return
        activo = bool(getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False))
        btn.setVisible(activo)
        if not activo:
            return
        df = getattr(self.legacy, 'df_base', None)
        cantidad = 0 if df is None or df.empty else len(comercial_services.construir_correcciones_tipo_facturacion(df))
        btn.setText(f" Arreglar ({cantidad})")
        btn.setEnabled(cantidad > 0)
        if cantidad:
            btn.setToolTip(
                f"Corrige el TIPO DE FACTURACION de {cantidad} unidad(es) según su FORMA DE CONTRATO. "
                "Las que tienen más de una opción válida (Venta, Conversión) no se tocan.")
        else:
            btn.setToolTip("No hay unidades que se puedan corregir automáticamente.")

    def _on_arreglar_inconsistencias_clicked(self):
        """Botón de la barra: corrige todas las unidades que se pueden."""
        df = getattr(self.legacy, 'df_base', None)
        if df is None or df.empty:
            return
        correcciones = comercial_services.construir_correcciones_tipo_facturacion(df)
        if correcciones and (len(correcciones) == 1 or self._confirmar_arreglo_tipo_facturacion(correcciones)):
            self._aplicar_correcciones_tipo_facturacion(correcciones)

    def _correcciones_de_seleccion(self):
        """(VIN seleccionados, {VIN: tipo correcto}) de la selección de la bandeja."""
        n_seleccionadas = len(self._filas_seleccionadas())
        df = getattr(self.legacy, 'df_base', None)
        if n_seleccionadas == 0 or df is None or df.empty:
            return [], {}
        vins, _ = self._obtener_vins_seleccionados()
        vins_norm = {str(v).strip().upper() for v in vins}
        seleccion = df[df['VIN'].astype(str).str.strip().str.upper().isin(vins_norm)]
        return vins, comercial_services.construir_correcciones_tipo_facturacion(seleccion)

    def _actualizar_boton_arreglar_tipo_fact(self):
        """Acción del panel derecho en "Revisar inconsistencias": se habilita
        si al menos una de las unidades seleccionadas se puede corregir."""
        btn = getattr(self, 'btn_accion_arreglar_tipo_fact', None)
        if btn is None or not self.acciones_rapidas_inconsistencias.isVisibleTo(self._panel_acciones):
            return
        vins, correcciones = self._correcciones_de_seleccion()
        btn.setEnabled(bool(correcciones))
        self._actualizar_boton_asignar_tipo_fact(vins)
        if not vins:
            btn.setToolTip("Selecciona una o varias unidades")
        elif not correcciones:
            btn.setToolTip(
                "Esta combinación no se puede corregir automáticamente: la forma de contrato tiene más de una "
                "opción válida (Venta, Conversión). Edita el contrato a mano." if len(vins) == 1
                else "Ninguna de las unidades seleccionadas se puede corregir automáticamente.")
        elif len(correcciones) < len(vins):
            btn.setToolTip(f"Se corregirán {len(correcciones)} de {len(vins)} unidades; el resto tiene más de una opción válida.")
        else:
            btn.setToolTip("Corrige el tipo de facturación según la forma de contrato")

    def _on_arreglar_tipo_fact_seleccion_clicked(self):
        vins, correcciones = self._correcciones_de_seleccion()
        if not correcciones:
            return
        if len(vins) > 1 and not self._confirmar_arreglo_tipo_facturacion(correcciones, len(vins)):
            return
        self._aplicar_correcciones_tipo_facturacion(correcciones)

    def _candidatas_asignar_tipo_fact(self, vins):
        """Selección que admite elegir Cliente o Facturación Manual (Venta y Conversión)."""
        df = getattr(self.legacy, 'df_base', None)
        if not vins or df is None or df.empty:
            return df.iloc[0:0] if df is not None else None
        vins_norm = {str(v).strip().upper() for v in vins}
        seleccion = df[df['VIN'].astype(str).str.strip().str.upper().isin(vins_norm)]
        return seleccion.drop_duplicates('VIN', keep='last')

    def _actualizar_boton_asignar_tipo_fact(self, vins):
        botones = ((getattr(self, 'btn_accion_asignar_tipo_fact', None), VALOR_TIPO_FACT_CLIENTE, "se facturan al cliente"),
                   (getattr(self, 'btn_accion_asignar_tipo_fact_manual', None), VALOR_TIPO_FACT_FACTURACION_MANUAL,
                    "pasan a facturación manual"))
        seleccion = self._candidatas_asignar_tipo_fact(vins)
        for btn, tipo, texto in botones:
            if btn is None:
                continue
            elegibles = 0
            if seleccion is not None and not seleccion.empty:
                elegibles = len(comercial_services.construir_asignacion_tipo_facturacion(seleccion, tipo))
            btn.setEnabled(elegibles > 0)
            if not vins:
                btn.setToolTip("Selecciona una o varias unidades de Venta o Conversión")
            elif not elegibles:
                btn.setToolTip("Solo aplica a unidades de Venta o Conversión que aún no tienen este tipo")
            else:
                btn.setToolTip(f"{elegibles} unidad(es) de Venta o Conversión {texto}")

    def _on_asignar_tipo_fact_clicked(self, tipo):
        """Aplica `tipo` (Cliente o Facturación Manual) de inmediato a las
        unidades seleccionadas de Venta o Conversión."""
        vins, _ = self._correcciones_de_seleccion()
        seleccion = self._candidatas_asignar_tipo_fact(vins)
        if seleccion is None or seleccion.empty:
            return
        asignacion = comercial_services.construir_asignacion_tipo_facturacion(seleccion, tipo)
        if asignacion:
            self._aplicar_correcciones_tipo_facturacion(asignacion)
    def _confirmar_arreglo_tipo_facturacion(self, correcciones, total_seleccionadas=None):
        """Resumen de cuántas unidades pasan de qué forma de contrato y tipo
        de facturación actual al tipo nuevo."""
        df = self.legacy.df_base
        base = df.drop_duplicates('VIN', keep='last')
        por_vin = base.set_index(base['VIN'].astype(str).str.strip().str.upper()).to_dict('index')
        conteo = {}
        for vin, nuevo in correcciones.items():
            fila = por_vin.get(vin, {})
            forma = str(fila.get('FORMA DE CONTRATO', '')).strip().upper() or '-'
            actual = str(fila.get(COL_TIPO_FACTURACION, '')).strip().upper() or '-'
            conteo[(forma, actual, nuevo)] = conteo.get((forma, actual, nuevo), 0) + 1
        lineas = [f"{forma}: {actual} → {nuevo}  ·  {n} unidad(es)"
                  for (forma, actual, nuevo), n in sorted(conteo.items())]
        descripcion = "Se cambia solo el tipo de facturación, según la forma de contrato."
        if total_seleccionadas and total_seleccionadas > len(correcciones):
            descripcion += (f" {total_seleccionadas - len(correcciones)} de las seleccionadas tienen más de una opción "
                            "válida y no se modifican.")
        dialogo = DialogoAccion(
            self, " Arreglar tipo de facturación",
            icon_name="fa5s.magic", icon_color=PRIMARY, icon_bg_color="#EFF6FF",
            titulo="Arreglar tipo de facturación",
            subtitulo=f"{len(correcciones)} unidad(es) se corregirán",
            descripcion=descripcion, items=lineas, titulo_items="Forma de contrato: tipo actual → nuevo",
            botones=[
                {'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                {'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'},
            ],
        )
        return dialogo.exec() == QDialog.DialogCode.Accepted

    def _aplicar_correcciones_tipo_facturacion(self, correcciones):
        df = self.legacy.df_base

        lookup_por_vin = df.drop_duplicates('VIN', keep='last').set_index(
            df.drop_duplicates('VIN', keep='last')['VIN'].astype(str).str.strip().str.upper()
        ).to_dict('index')
        valid = {}
        for vin, tipo_nuevo in correcciones.items():
            fila_actual = lookup_por_vin.get(vin, {})
            cambios = {COL_TIPO_FACTURACION: tipo_nuevo}
            nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada({
                COL_ESTADO_COMERCIAL: fila_actual.get(COL_ESTADO_COMERCIAL, ''),
                COL_ESTADO_ACTIVACION: fila_actual.get(COL_ESTADO_ACTIVACION, ''),
                COL_TIPO_FACTURACION: tipo_nuevo,
                COL_ETAPA_GESTION: fila_actual.get(COL_ETAPA_GESTION, ''),
            })
            if str(nueva_etapa).strip().upper() != str(fila_actual.get(COL_ETAPA_GESTION, '')).strip().upper():
                cambios[COL_ETAPA_GESTION] = nueva_etapa
            valid[vin] = {'VIN': vin, 'cambios': cambios}
        comercial_services.agregar_id_a_cambios(valid, df)

        self.btn_arreglar_inconsistencias_barra.setEnabled(False)
        self.btn_accion_arreglar_tipo_fact.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Corrigiendo tipo de facturación…")
        self._arreglar_inconsistencias_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._arreglar_inconsistencias_thread.finished_signal.connect(
            lambda success: self._on_arreglar_inconsistencias_finished(success, valid)
        )
        self._arreglar_inconsistencias_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._arreglar_inconsistencias_thread.start()

    def _on_arreglar_inconsistencias_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        if not success:
            terminar_guardando(self, exito=False)
            self._actualizar_boton_arreglar_inconsistencias()
            self._actualizar_boton_arreglar_tipo_fact()
            DialogoAccionCm.error(
                self,
                "No se pudo guardar la corrección. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self.legacy._df_inconsistencias_forma_contrato = comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion(
            self.legacy.df_base)
        self._refresh_new_ui_data()
        self._actualizar_boton_arreglar_inconsistencias()
        self._actualizar_estado_acciones_rapidas()
        terminar_guardando(self)
