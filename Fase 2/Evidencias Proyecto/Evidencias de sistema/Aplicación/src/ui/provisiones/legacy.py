"""Pantalla de Provisiones anterior, que sigue sirviendo de motor de datos de la nueva."""
from src.theme.colors import SUCCESS, TEXT_SECONDARY
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QMessageBox, QLineEdit, QDialog, QStackedWidget, QApplication
from PyQt6.QtCore import Qt, QTimer
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.ui.compartido.custom_table import VolvoTableWidget
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando, crear_tarjeta_carga
from src.services import provisiones_services
from src.services import comercial_services
from src.theme.theme_manager import ThemeManager
from PyQt6.QtGui import QKeySequence
from src.ui.provisiones.base import (
    ProvisionesTableModel,
    SaveProvisionesThread,
    logger,
)
from src.ui.provisiones.costos import (
    CostosDialog,
)
from src.ui.provisiones.dialogos import (
    VincularComercialDialog,
    VinsHuerfanosAlertDialog,
)
from src.ui.provisiones.sync import (
    SyncTerminalDialog,
)


class _ProvisionesModuleLegacy(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.data_manager.provisiones_ready.connect(self._on_data_ready)
        self.data_manager.load_provisiones_error.connect(self._on_load_error)
        self.pending_changes = {}
        # Fase 1 de la auditoria de rendimiento (17-09-2026): se evaluo
        # agregar aqui el mismo guard de visibilidad que general.py/
        # comercial.py/contratos.py, pero se revirtio -- a diferencia de
        # data_ready/logs_updated (que se disparan por CUALQUIER guardado en
        # CUALQUIER modulo), provisiones_ready SOLO se emite como consecuencia
        # de una accion propia de este modulo (load_provisiones_async() no lo
        # llama nadie mas, ver DataManager); en uso real, si esta señal llega,
        # es porque el usuario esta usando Provisiones en ese momento. Agregar
        # el guard no evitaba trabajo real (no hay reprocesamiento oculto que
        # prevenir) y sí rompia el refresco esperado tras guardar/recargar.
        self.search_input = QLineEdit()
        self.search_input.hide()
        self._setup_ui()
        # La primera lectura del Excel parte después de la transición de
        # entrada: si corre mientras se arma el grupo le quita el GIL a la UI
        self.btn_reload.setEnabled(False)
        self.btn_save.setEnabled(False)
        QTimer.singleShot(300, self._trigger_reload)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()

        self.lbl_uf_status = QLabel("")
        self.lbl_uf_status.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {SUCCESS}; padding-left: 15px;")

        self.btn_ajustes = QPushButton(" Ajustes de Costos")
        self.btn_ajustes.setIcon(ThemeManager.icon('fa5s.cog', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(self.btn_ajustes)
        self.btn_ajustes.clicked.connect(self.open_costos_dialog)

        header_layout.addWidget(self.lbl_uf_status)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_ajustes)
        main_layout.addLayout(header_layout)

        self.controls_frame = QFrame()
        ThemeManager.apply_card_style(self.controls_frame)
        controls_layout = QHBoxLayout(self.controls_frame)
        
        self.btn_add_sync = QPushButton()
        self.btn_add_sync.setIcon(ThemeManager.icon('fa5s.plus', color='white')) 
        self.btn_add_sync.setFixedSize(32, 32)
        self.btn_add_sync.setStyleSheet(f"background-color: {SUCCESS}; border-radius: 16px;")
        self.btn_add_sync.clicked.connect(self.open_sync_dialog)

        # --- FILTRO FECHAS ---
        self.combo_fecha = estilo_com.ComboTarjeta("Mes")
        self.combo_fecha.addItem("Todos los Meses")
        ThemeManager.apply_combo_box(self.combo_fecha)
        self.combo_fecha.setMaxVisibleItems(8)                           # <--- LÍNEA NUEVA
        self.combo_fecha.view().setMaximumHeight(250)                    # <--- LÍNEA NUEVA
        self.combo_fecha.currentTextChanged.connect(self.filter_table)
        
        # --- FILTRO PLANES ---
        self.combo_plan = estilo_com.ComboTarjeta("Plan")
        self.combo_plan.addItem("Todos los Planes")
        ThemeManager.apply_combo_box(self.combo_plan)
        self.combo_plan.setMaxVisibleItems(8)                            # <--- LÍNEA NUEVA
        self.combo_plan.view().setMaximumHeight(250)                     # <--- LÍNEA NUEVA
        self.combo_plan.currentTextChanged.connect(self.filter_table)

        from PyQt6.QtWidgets import QCheckBox
        self.chk_ocultar_ceros = QCheckBox("Ocultar Dynafleet = 0")
        self.chk_ocultar_ceros.setChecked(True) 
        self.chk_ocultar_ceros.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {TEXT_SECONDARY}; margin-left: 10px;")
        self.chk_ocultar_ceros.stateChanged.connect(self.filter_table)

        self.btn_export_excel = QPushButton(" Excel")
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='white'))
        ThemeManager.apply_success_button(self.btn_export_excel)
        self.btn_export_excel.clicked.connect(lambda: self.table.export_to_excel("Reporte_Provisiones"))
        
        self.btn_reload = QPushButton(" Recargar")
        self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(self.btn_reload)
        self.btn_reload.clicked.connect(lambda: self._trigger_reload(is_manual_reload=True))

        self.btn_save = QPushButton(" Guardar")
        self.btn_save.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        ThemeManager.apply_primary_button(self.btn_save)
        self.btn_save.clicked.connect(self.confirm_save)

        controls_layout.addWidget(self.btn_add_sync) 
        controls_layout.addWidget(self.combo_fecha) 
        controls_layout.addWidget(self.combo_plan)
        controls_layout.addWidget(self.chk_ocultar_ceros)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_export_excel)
        controls_layout.addWidget(self.btn_reload)
        controls_layout.addWidget(self.btn_save) 
        main_layout.addWidget(self.controls_frame)

        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(
            crear_tarjeta_carga("Procesando datos financieros…", "Esto tomará unos segundos."),
            alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(self.loading_widget)

        self.table_widget_container = QWidget()
        table_layout = QVBoxLayout(self.table_widget_container)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.table = VolvoTableWidget()
        self.table.menu_type = "general"  # Provisiones no tiene "Eliminar Camión"
        self.model = ProvisionesTableModel(self)
        self.table.set_model_and_delegate(self.model, {'Plan': ["Basico", "Medio", "Full", "Full + CIV", "Medio + CIV"]})
        self.table.item_edited.connect(self.on_item_edited)
        self.table.sort_changed.connect(self.filter_table)

        original_key_press = self.table.keyPressEvent
        
        def custom_key_press(event):
            if event.matches(QKeySequence.StandardKey.Paste):
                indexes = self.table.selectedIndexes()
                if indexes:
                    df_view = self.model.get_df()
                    if 'Plan' in df_view.columns:
                        plan_col_idx = df_view.columns.get_loc('Plan')
                        selected_plan_cells = [idx for idx in indexes if idx.column() == plan_col_idx]
                        if selected_plan_cells:
                            self.paste_plan_to_selection(selected_plan_cells)
                            return
            original_key_press(event)
            
        self.table.keyPressEvent = custom_key_press
        table_layout.addWidget(self.table)
        self.stack.addWidget(self.table_widget_container)

    def paste_plan_to_selection(self, selected_plan_cells):
        clipboard_text = QApplication.clipboard().text().strip()
        if not clipboard_text:
            return
            
        # 1. Definir los valores permitidos para la columna 'Plan'
        opciones_validas = ["Basico", "Medio", "Full", "Full + CIV", "Medio + CIV"]
        
        # 2. Normalizamos el portapapeles (ignora mayúsculas/minúsculas y espacios extra)
        clipboard_upper = clipboard_text.upper()
        opciones_upper = {opc.upper(): opc for opc in opciones_validas}
        
        # 3. Validación: Si el texto copiado no está en la lista de opciones...
        if clipboard_upper not in opciones_upper:
            QMessageBox.warning(
                self, 
                "Pegado Inválido", 
                f"El valor '{clipboard_text}' no es un Plan válido.\n\nOpciones permitidas:\n- " + "\n- ".join(opciones_validas)
            )
            return # Interrumpe el pegado, conservando el valor original de cada celda

        # 4. Si pasó la validación, usamos el valor exacto del diccionario para evitar problemas de capitalización
        valor_correcto = opciones_upper[clipboard_upper]
            
        for idx in selected_plan_cells:
            self.model.setData(idx, valor_correcto, Qt.ItemDataRole.EditRole)

    def open_sync_dialog(self):
        dialog = SyncTerminalDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted: self._trigger_reload(is_manual_reload=True)

    def on_item_edited(self, row, col_name, new_value):
        if getattr(self, '_is_updating', False): return
        self._is_updating = True
        
        try:
            df_actual = self.model.get_df()
            vin_value = str(df_actual.iat[row, df_actual.columns.get_loc('VIN')]).strip().upper()
            fecha_value = str(df_actual.iat[row, df_actual.columns.get_loc('AÑO - MES')]).strip().upper()

            if col_name in ['Monto Provisionado', 'Valor Plan', 'VAR']: return

            unique_key = f"{vin_value}_{fecha_value}"
            if unique_key not in self.pending_changes: 
                self.pending_changes[unique_key] = {'VIN': vin_value, 'AÑO - MES': fecha_value, 'cambios': {}}
            
            columnas_afectadas = []

            if col_name == 'Cantidad de Meses':
                resultado, valor = provisiones_services.validar_cantidad_meses(new_value)

                if resultado == "invalido":
                    QMessageBox.warning(self, "Error", valor)
                    df_actual.iat[row, df_actual.columns.get_loc(col_name)] = ""

                    col_err_idx = df_actual.columns.get_loc(col_name)
                    idx = self.model.index(row, col_err_idx)
                    self.model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
                    return

                if resultado == "mensual":
                    self.pending_changes[unique_key]['cambios']['Cantidad de Meses'] = '-'
                    df_actual.iat[row, df_actual.columns.get_loc('Cantidad de Meses')] = '-'
                else:  # "vacio" o "numerico"
                    self.pending_changes[unique_key]['cambios'][col_name] = valor

            elif col_name == 'DYNAFLEET':
                resultado, dato = provisiones_services.parsear_dynafleet(new_value)

                if resultado == "invalido":
                    QMessageBox.warning(self, "Error", "El cobro (Dynafleet) debe ser un número válido.")
                    old_row = self.df_base[(self.df_base['VIN'] == vin_value) & (self.df_base['AÑO - MES'] == fecha_value)]
                    old_val_raw = old_row.iloc[0]['DYNAFLEET'] if not old_row.empty else 0
                    try:
                        old_num = float(str(old_val_raw).replace('$', '').replace('.', '').replace(',', '').strip()) if old_val_raw else 0.0
                    except Exception:
                        old_num = 0.0
                    old_formato = provisiones_services.formatear_moneda(old_num)

                    df_actual.iat[row, df_actual.columns.get_loc(col_name)] = old_formato

                    col_err_idx = df_actual.columns.get_loc(col_name)
                    idx = self.model.index(row, col_err_idx)
                    self.model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
                    return

                self.pending_changes[unique_key]['cambios'][col_name] = dato["num"]
                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = dato["formato"]
                new_value = dato["formato"]
                columnas_afectadas.append(df_actual.columns.get_loc(col_name))
            else:
                self.pending_changes[unique_key]['cambios'][col_name] = new_value

            try:
                uf, civ = self.data_manager.get_variables()
                planes_data = self.data_manager.get_costos()

                col_dynafleet_idx = df_actual.columns.get_loc('DYNAFLEET') if 'DYNAFLEET' in df_actual.columns else None
                col_meses_idx = df_actual.columns.get_loc('Cantidad de Meses') if 'Cantidad de Meses' in df_actual.columns else None
                col_plan_idx = df_actual.columns.get_loc('Plan') if 'Plan' in df_actual.columns else None

                val_dynafleet = 0.0
                val_meses = 1.0
                nombre_plan = ""

                if col_dynafleet_idx is not None:
                    val_raw = str(df_actual.iat[row, col_dynafleet_idx]).replace('$', '').replace('.', '')
                    if val_raw and val_raw != '$-': val_dynafleet = float(val_raw)
                if col_name == 'DYNAFLEET':
                    val_raw = str(new_value).replace('$', '').replace('.', '')
                    if val_raw and val_raw != '$-': val_dynafleet = float(val_raw)

                if col_meses_idx is not None:
                    val_raw = df_actual.iat[row, col_meses_idx]
                    if pd.notna(val_raw) and str(val_raw).strip() not in ["", "-", "MENSUAL"]: val_meses = float(val_raw)
                if col_name == 'Cantidad de Meses':
                    if str(new_value).strip() not in ["", "-", "MENSUAL"]: val_meses = float(new_value)

                if col_plan_idx is not None:
                    nombre_plan = str(df_actual.iat[row, col_plan_idx]).strip()
                if col_name == 'Plan':
                    nombre_plan = str(new_value).strip()

                monto_prov, valor_plan_exacto, variacion = provisiones_services.calcular_montos_provision(
                    val_dynafleet, val_meses, nombre_plan, planes_data, uf
                )

                if 'Monto Provisionado' in df_actual.columns:
                    df_actual.iat[row, df_actual.columns.get_loc('Monto Provisionado')] = provisiones_services.formatear_moneda(monto_prov)
                    self.pending_changes[unique_key]['cambios']['Monto Provisionado'] = monto_prov
                    columnas_afectadas.append(df_actual.columns.get_loc('Monto Provisionado'))

                if 'Valor Plan' in df_actual.columns:
                    df_actual.iat[row, df_actual.columns.get_loc('Valor Plan')] = provisiones_services.formatear_moneda(valor_plan_exacto)
                    self.pending_changes[unique_key]['cambios']['Valor Plan'] = valor_plan_exacto
                    columnas_afectadas.append(df_actual.columns.get_loc('Valor Plan'))

                if 'VAR' in df_actual.columns:
                    df_actual.iat[row, df_actual.columns.get_loc('VAR')] = provisiones_services.formatear_moneda(variacion)
                    self.pending_changes[unique_key]['cambios']['VAR'] = variacion
                    columnas_afectadas.append(df_actual.columns.get_loc('VAR'))

                col_edit_idx = df_actual.columns.get_loc(col_name)
                if col_edit_idx not in columnas_afectadas:
                    columnas_afectadas.append(col_edit_idx)
                
                for c_idx in set(columnas_afectadas):
                    idx = self.model.index(row, c_idx)
                    self.model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole])

            except Exception as e:
                logger.warning(f"Error calculando en vivo: {e}")
        
        finally:
            self._is_updating = False

    def confirm_save(self, claves=None):
        """Guarda los cambios pendientes; con `claves` (guardado automático) solo esos, sin avisar si no hay."""
        origen = self.pending_changes if claves is None else {k: self.pending_changes[k] for k in claves if k in self.pending_changes}
        valid = {k: d for k, d in origen.items() if d.get('cambios') or d.get('rm')}
        if not valid:
            return QMessageBox.information(self, "Aviso", "No hay cambios.") if claves is None else None
        self._claves_guardando = set(valid) if claves is not None else None
        self.btn_save.setEnabled(False)
        self.btn_reload.setEnabled(False)

        mostrar_guardando(self, "Guardando provisiones y sincronizando con Comercial…")

        self.save_thread = SaveProvisionesThread(valid, self.writer, self.data_manager)
        self.save_thread.finished_signal.connect(self._on_save_finished)
        self.save_thread.start()

    def _on_save_finished(self, success, pending_data, vins_huerfanos, cross_updates):
        self.btn_save.setEnabled(True)
        self.btn_reload.setEnabled(True)
        
        if success:
            guardado_listo(self)
            try:
                dm = self.data_manager
                if not dm.df_prov.empty:
                    df_m = dm.df_prov.copy()
                    for key, data in pending_data.items():
                        vin_val = str(data['VIN']).strip()
                        mes_val = str(data['AÑO - MES']).strip()
                        mask = (df_m['VIN'].astype(str).str.strip() == vin_val) & (df_m['AÑO - MES'].astype(str).str.strip() == mes_val)
                        if mask.any():
                            for col, val in data['cambios'].items():
                                if col in df_m.columns:
                                    df_m[col] = df_m[col].astype(object) 
                                    df_m.loc[mask, col] = val
                    dm.df_prov = df_m
                
                if cross_updates and not dm.df_master.empty:
                    dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, cross_updates)
                    # Avisa a Comercial/Vista General que df_master cambió en
                    # RAM (mismo patrón que VincularComercialDialog._on_creado):
                    # sin esto quedaban desactualizados hasta un Recargar
                    # manual, porque el único punto que emitía data_ready era
                    # una recarga completa desde disco (load_data_async),
                    # nunca disparada por este flujo (cross_updates ya evita
                    # esa relectura por rendimiento).
                    dm.data_ready.emit()

                solo = getattr(self, '_claves_guardando', None)
                if solo:
                    for clave in solo:
                        self.pending_changes.pop(clave, None)
                else:
                    self.pending_changes.clear()
                self._claves_guardando = None
                self._trigger_reload(is_manual_reload=False)
                
                vins_cerrados = list(getattr(self.save_thread, 'vins_cerrados', []))
                vins_omitidos = list(getattr(self.save_thread, 'vins_omitidos', []))

                def _avisar_resultado():
                    terminar_guardando(self)
                    if vins_huerfanos:
                        self._show_rescue_dialog(vins_huerfanos)
                    if vins_omitidos:
                        self._avisar_vins_omitidos(vins_omitidos)
                    if vins_cerrados:
                        self._ofrecer_contrato_nuevo(vins_cerrados)
                QTimer.singleShot(800, _avisar_resultado)

            except Exception as e:
                logger.warning(f"Fallo inyectando RAM en Provisiones: {e}")
                terminar_guardando(self, exito=False)
                self._trigger_reload(global_reload=True, is_manual_reload=False)
        else:
            terminar_guardando(self, exito=False)
            self.stack.setCurrentIndex(1)
            error_msg = pending_data.get('error', 'Error desconocido.')
            QMessageBox.warning(self, "Error", f"No se pudo guardar el archivo:\n{error_msg}")

    def _avisar_vins_omitidos(self, vins_omitidos):
        detalle = "\n".join(f"• {vin} (forma de contrato: {forma or '-'})" for vin, forma in vins_omitidos)
        QMessageBox.information(
            self, "Provisiones guardadas",
            "Se guardó en Provisiones. Los datos no pasaron a Comercial porque el contrato actual de estos VIN "
            "no es de forma Provision:\n\n" + detalle)

    def _ofrecer_contrato_nuevo(self, vins_cerrados):
        detalle = "\n".join(f"• {vin}" for vin, _ in vins_cerrados)
        respuesta = QMessageBox.question(
            self, "Contrato finalizado",
            "Se guardó en Provisiones. Estos VIN tienen su contrato finalizado (Baja), así que no se modificó "
            "Comercial:\n\n" + detalle + "\n\n¿Crear un contrato nuevo de forma Provision para estas unidades?")
        if respuesta == QMessageBox.StandardButton.Yes:
            VincularComercialDialog(vins_cerrados, self.data_manager, self, nuevo_contrato=True).exec()

    def _show_rescue_dialog(self, vins_huerfanos):
        alerta = VinsHuerfanosAlertDialog(vins_huerfanos, self)
        if alerta.exec() != QDialog.DialogCode.Accepted:
            return
        if getattr(alerta, 'eleccion', None) == 'importar':
            from src.ui.compartido import saltos
            saltos.abrir_importacion_power_bi()
            return
        dialog = VincularComercialDialog(vins_huerfanos, self.data_manager, self)
        dialog.exec()

    def _trigger_reload(self, global_reload=False, is_manual_reload=False):
        if is_manual_reload:
            self.pending_changes.clear()


        self.btn_reload.setEnabled(False)
        self.btn_save.setEnabled(False)
        
        self.stack.setCurrentIndex(0)
        QApplication.processEvents() 
        
        self._ejecutar_cargas(global_reload)
        QTimer.singleShot(12000, self._force_unlock_buttons)

    def _force_unlock_buttons(self):
        if not self.btn_reload.isEnabled():
            self.btn_reload.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.stack.setCurrentIndex(1) 

    def _ejecutar_cargas(self, global_reload):
        self.data_manager.load_provisiones_async()
        if global_reload:
            self.data_manager.load_data_async()

    def _on_data_ready(self):
        try:
            self.load_data()
        except Exception as e:
            logger.warning(f"Error silencioso matemático en Provisiones: {e}")
        finally:
            self.btn_reload.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.stack.setCurrentIndex(1)

    def _on_load_error(self, error_msg):
        self.btn_reload.setEnabled(True)
        self.stack.setCurrentIndex(1)
        QMessageBox.critical(self, "Error", error_msg)

    def load_data(self):
        uf, _ = self.data_manager.get_variables()
        self.lbl_uf_status.setText(f"UF del día: ${uf:,.2f}".replace(",", "."))
        # Referencia (no copia) del origen, para saber si los datos cambiaron
        # desde esta carga (ver ProvisionesModule._on_new_ui_tab_refresh_if_dirty).
        self._df_prov_origen = self.data_manager.df_prov
        df_raw = self.data_manager.get_provisiones_df()
        self.df_base = df_raw.copy() if not df_raw.empty else df_raw
        
        if not self.df_base.empty and 'Cantidad de Meses' in self.df_base.columns:
            self.df_base['Cantidad de Meses'] = self.df_base['Cantidad de Meses'].apply(provisiones_services.limpiar_cantidad_meses_display)
        
        if not self.df_base.empty and 'AÑO - MES' in self.df_base.columns:
            fechas_str = self.df_base['AÑO - MES'].astype(str)
            fechas_unicas = [f.strip() for f in fechas_str.unique() if f.strip() and f.strip().lower() != 'nan']
            meses_a_num = {'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6, 'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12}
            fechas_ordenadas = sorted(fechas_unicas, key=lambda f: (int(f.split("-")[0].strip()), meses_a_num.get(f.split("-")[1].strip().capitalize(), 0)) if "-" in f else (0,0), reverse=True)
            fecha_previa = self.combo_fecha.currentText()
            self.combo_fecha.blockSignals(True)
            self.combo_fecha.clear(); self.combo_fecha.addItem("Todos los Meses"); self.combo_fecha.addItems(fechas_ordenadas)
            idx_fecha = self.combo_fecha.findText(fecha_previa)
            self.combo_fecha.setCurrentIndex(idx_fecha if idx_fecha >= 0 else 0)
            self.combo_fecha.blockSignals(False)
        
        if not self.df_base.empty and 'Plan' in self.df_base.columns:
            planes_unicos = [p.strip() for p in self.df_base['Plan'].astype(str).unique() if p.strip() and p.strip().lower() != 'nan']
            plan_previo = self.combo_plan.currentText()
            self.combo_plan.blockSignals(True)
            self.combo_plan.clear(); self.combo_plan.addItem("Todos los Planes"); self.combo_plan.addItems(sorted(planes_unicos))
            idx_plan = self.combo_plan.findText(plan_previo)
            self.combo_plan.setCurrentIndex(idx_plan if idx_plan >= 0 else 0)
            self.combo_plan.blockSignals(False)

        # La tabla (formatea montos de todas las filas) solo se arma si
        # "Vista Completa" está a la vista; al mostrarla se vuelve a llamar
        # load_data (ProvisionesModule._on_internal_tab_changed).
        if self.isVisible():
            self.filter_table()
        else:
            self._tabla_pendiente = True

    def filter_table(self):
        self._tabla_pendiente = False
        if self.df_base.empty: return
        search_text = self.search_input.text().lower()
        f_fecha, f_plan = self.combo_fecha.currentText(), self.combo_plan.currentText()
        ocultar_ceros = getattr(self, 'chk_ocultar_ceros', None) and self.chk_ocultar_ceros.isChecked()
        
        df_f = self.df_base.copy()
        if f_fecha != "Todos los Meses": df_f = df_f[df_f['AÑO - MES'].astype(str).str.strip() == f_fecha]
        if f_plan != "Todos los Planes": df_f = df_f[df_f['Plan'].astype(str).str.strip() == f_plan]
        if ocultar_ceros and 'DYNAFLEET' in df_f.columns: df_f = df_f[pd.to_numeric(df_f['DYNAFLEET'], errors='coerce').fillna(0) > 0]
                
        if search_text:
            cols = [c for c in ['VIN', 'CLIENTE', 'EJECUTIVO'] if c in df_f.columns]
            or_terms = [t.strip() for t in search_text.split(',') if t.strip()]
            
            final_mask = pd.Series(False, index=df_f.index)
            for or_term in or_terms:
                and_terms = [t.strip() for t in or_term.split() if t.strip()]
                and_mask = pd.Series(True, index=df_f.index)
                
                for a_term in and_terms:
                    col_mask = pd.Series(False, index=df_f.index)
                    for col in cols: 
                        col_mask |= df_f[col].astype(str).str.lower().str.contains(a_term, na=False, regex=False)
                    and_mask &= col_mask
                    
                final_mask |= and_mask
                
            df_f = df_f[final_mask]

        if hasattr(self, 'pending_changes') and self.pending_changes:
            for key, data in self.pending_changes.items():
                v_val = str(data['VIN']).strip().upper()
                # AÑADIDO .UPPER() AQUÍ
                m_val = str(data['AÑO - MES']).strip().upper() 
                
                # AÑADIDO .UPPER() A LA MÁSCARA DEL DATAFRAME
                mask = (df_f['VIN'].astype(str).str.strip().str.upper() == v_val) & \
                       (df_f['AÑO - MES'].astype(str).str.strip().str.upper() == m_val)
                
                if mask.any():
                    for col_c, val_c in data['cambios'].items():
                        if col_c in df_f.columns:
                            df_f[col_c] = df_f[col_c].astype(object) 
                            df_f.loc[mask, col_c] = val_c
            
        df_display = df_f.copy()
        for col in ['Monto Provisionado', 'Valor Plan', 'VAR', 'DYNAFLEET']:
            if col in df_display.columns:
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce').fillna(0).apply(provisiones_services.formatear_moneda)

        # Ordenamiento tipo Excel elegido por el usuario (clic de encabezado /
        # menú contextual). No afecta a df_base ni a ningún dato persistido:
        # es un no-op si no hay ordenamiento activo. ProvisionesTableModel
        # calcula el resaltado naranja dinámicamente por VIN+AÑO-MES (no por
        # coordenada fija), así que reordenar filas aquí no lo desincroniza.
        df_display = self.table.apply_sort(df_display)

        self.model.set_data(df_display)

    def open_costos_dialog(self):
        if CostosDialog(self).exec() == QDialog.DialogCode.Accepted: self._trigger_reload(is_manual_reload=True)
