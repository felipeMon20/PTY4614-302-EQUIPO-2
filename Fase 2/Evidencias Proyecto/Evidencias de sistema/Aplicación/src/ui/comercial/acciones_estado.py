"""Acciones de Comercial que cambian el estado: enviar a Operaciones, vencido y vigente."""
from src.theme.colors import TEXT_SECONDARY
import pandas as pd
from datetime import datetime
from PyQt6.QtWidgets import QDialog, QMessageBox, QApplication
from PyQt6.QtCore import Qt
from src.services import comercial_services
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.theme.theme_manager import ThemeManager
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.constants import COL_ESTADO_COMERCIAL, VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA, COL_ETAPA_GESTION, VALOR_ESTADO_COMERCIAL_VENCIDO, COL_TIPO_FACTURACION, COL_ESTADO_ACTIVACION, VALOR_ESTADO_COMERCIAL_VIGENTE
from src.ui.comercial.base import SaveExcelThread
from src.ui.comercial.dialogos import DialogoAccionCm
from src.ui.comercial.base import (
    SaveExcelThread,
)
from src.ui.comercial.dialogos import (
    DialogoAccionCm,
)


class _AccionesEstadoComercialMixin:
    def _on_accion_enviar_operaciones_clicked(self):
        """"Enviar a operaciones" (22-09-2026, a pedido explícito): cambia
        ESTADO COMERCIAL Y ETAPA GESTIÓN a "OPERACIONES" de todos los VIN
        seleccionados, disponible en las sub-pestañas donde el botón sigue
        habilitado (ver _actualizar_estado_acciones_rapidas: deshabilitado
        en "Por gestionar" y "Gestionar CM"). Pensado para el flujo de
        Renovaciones (el cliente rechaza la renovación), pero no se
        restringe a esa sub-pestaña.

        ESTADO COMERCIAL (23-09-2026, ciclo de baja anticipada): desde
        "Vigentes" fija BAJA SOLICITADA en vez de BAJA directo -- ese caso es
        una unidad Conectada y con contrato vigente que se da de baja antes
        de tiempo (siniestro u otro problema), no una baja por vencimiento o
        rechazo de renovación. Operaciones -> Bajas la confirma como BAJA
        recién al marcarla DESCONECTADO (ver operaciones_services.
        calcular_cambios_marcar_desconectado). Las demás sub-pestañas siguen
        fijando BAJA directo, sin cambios.

        ETAPA GESTIÓN se recalcula vía DataFrameFormatter.calcular_etapa_gestion_esperada
        (25-09-2026, corrección de bug real: antes se forzaba a OPERACIONES
        SIEMPRE, sin importar ESTADO DE ACTIVACIÓN ACTUAL -- ver
        conversación con el usuario, incidente real donde 653 VIN enviados
        desde "Vencidos" a BAJA quedaron con ~270 contradiciendo la matriz,
        porque la mayoría ya estaba Desconectada y la matriz real dice
        COMERCIAL para BAJA+Desconectado, no OPERACIONES). Se calcula por
        VIN, con el ESTADO DE ACTIVACIÓN ACTUAL/TIPO DE FACTURACION reales de
        cada unidad (self.df_base) y el ESTADO COMERCIAL nuevo
        (estado_comercial_destino) -- misma función que ya usa
        ComercialAgregarDialog/clean()/detectar_contradicciones_etapa_gestion,
        sin reimplementar la regla.

        Emite data_manager.data_ready al terminar (26-09-2026: antes no se
        emitía) para que Operaciones (y cualquier otro módulo suscrito) se
        refresque solo, en vez de necesitar una recarga manual de la app."""
        vins_ordenados, _ = self._obtener_vins_seleccionados()
        if not vins_ordenados:
            return

        # Por unidad (ex "Vigentes"): vigente en curso -> baja anticipada
        # (BAJA SOLICITADA); el resto -> BAJA directo.
        en_renovar = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
        destino_por_vin = {
            vin: (VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA if en_renovar and self._unidad_vigente_en_curso(vin)
                  else VALOR_ESTADO_COMERCIAL_BAJA)
            for vin in vins_ordenados
        }
        destinos = set(destino_por_vin.values())
        estado_comercial_destino = destinos.pop() if len(destinos) == 1 else VALOR_ESTADO_COMERCIAL_BAJA

        dialogo = DialogoAccionCm.confirmacion_enviar_operaciones(self, vins_ordenados, estado_comercial_destino)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return

        df_base = self.df_base
        lookup_por_vin = {}
        if not df_base.empty and 'VIN' in df_base.columns:
            df_lookup = df_base.drop_duplicates('VIN', keep='last').set_index(
                df_base['VIN'].astype(str).str.strip().str.upper()
            )
            lookup_por_vin = df_lookup.to_dict('index')

        valid = {}
        for vin in vins_ordenados:
            fila_actual = lookup_por_vin.get(str(vin).strip().upper(), {})
            estado_vin = destino_por_vin[vin]
            row_para_matriz = {
                COL_ESTADO_COMERCIAL: estado_vin,
                COL_ESTADO_ACTIVACION: fila_actual.get(COL_ESTADO_ACTIVACION, ''),
                COL_TIPO_FACTURACION: fila_actual.get(COL_TIPO_FACTURACION, ''),
                COL_ETAPA_GESTION: fila_actual.get(COL_ETAPA_GESTION, ''),
            }
            nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada(row_para_matriz)
            valid[vin] = {'VIN': vin, 'cambios': {
                COL_ESTADO_COMERCIAL: estado_vin,
                COL_ETAPA_GESTION: nueva_etapa,
            }}
        comercial_services.agregar_id_a_cambios(valid, df_base)

        self.btn_accion_enviar_operaciones.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Enviando a Operaciones…")
        self._enviar_operaciones_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._enviar_operaciones_thread.finished_signal.connect(
            lambda success: self._on_enviar_operaciones_finished(success, valid)
        )
        self._enviar_operaciones_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._enviar_operaciones_thread.start()

    def _on_enviar_operaciones_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar el envío a operaciones. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            # A diferencia de _on_confirmar_baja_cm_finished/_on_editar_unidad_finished
            # (que solo actualizan la vista de Comercial), esta acción debe
            # reflejarse de inmediato en Operaciones -> Bajas: data_ready es la
            # señal que ese módulo ya escucha para refrescarse solo.
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _on_accion_marcar_vencido_clicked(self):
        """"Marcar como Vencido" (sub-pestaña Vencidos, 23-09-2026; pasó a
        actuar solo sobre las filas seleccionadas el 05-10-2026, a pedido
        explícito): actúa únicamente sobre las filas seleccionadas con
        fecha de término expirada (comercial_services.filtrar_vencidos)
        cuyo ESTADO COMERCIAL esté en ESTADOS_COMERCIAL_CORREGIBLES_A_
        VENCIDO (Vigente/Activación Pendiente). Decisión confirmada con el
        usuario (23-09-2026): NO toca Baja/Baja Solicitada/Revisar aunque la
        fecha ya haya pasado -- esos estados representan una decisión de
        negocio ya tomada, no un olvido. Mismo mecanismo de guardado que
        "Enviar a operaciones" (SaveExcelThread / ExcelWriter.update_cells,
        con su backup ya incluido)."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            return

        df_pendientes = self._pendientes_marcar_vencido_seleccionados()
        if df_pendientes.empty:
            return
        self._marcar_vencido_df(df_pendientes)

    def _on_marcar_todos_vencidos_clicked(self):
        """Botón de la barra: marca como Vencido TODAS las unidades de la
        cartera con término pasado y estado todavía Vigente / Activación
        Pendiente (misma regla y mismo guardado que la acción del panel)."""
        df_pendientes = self._unidades_pendientes_marcar_vencido(getattr(self.legacy, 'df_base', None))
        if df_pendientes is None or df_pendientes.empty:
            QMessageBox.information(
                self, "Marcar como Vencido",
                "No hay unidades con la fecha de término pasada y el estado sin actualizar.")
            return
        self._marcar_vencido_df(df_pendientes)

    def _sincronizar_grupos_barra(self):
        """Los botones de Revisión solo se ven si hay inconsistencias o diferencias de fechas
        (o si su filtro está activo); el grupo se oculta cuando no le queda ningún botón."""
        legacy = self.legacy
        for btn, df in ((legacy.btn_revisar_inconsistencias_forma_contrato,
                         getattr(legacy, '_df_inconsistencias_forma_contrato', None)),
                        (legacy.btn_revisar_fechas_contrato, getattr(legacy, '_df_fechas_contrato', None))):
            hay = df is not None and not df.empty
            btn.setVisible(hay or btn.isChecked())
        for grupo, botones in (
                (getattr(self, '_grupo_revision_barra', None),
                 (legacy.btn_revisar_inconsistencias_forma_contrato, legacy.btn_revisar_fechas_contrato)),
                (getattr(self, '_grupo_acciones_barra', None),
                 (self.btn_marcar_vencidos_barra, self.btn_arreglar_inconsistencias_barra, self.btn_arreglar_fechas_barra))):
            if grupo is not None:
                grupo.setVisible(any(not b.isHidden() for b in botones))

    def _actualizar_boton_marcar_vencidos_barra(self):
        """Contador del botón de la barra: unidades con término pasado y
        estado sin actualizar. Rojo con 1 o más; neutro con 0."""
        btn = getattr(self, 'btn_marcar_vencidos_barra', None)
        if btn is None:
            return
        df = getattr(self.legacy, 'df_base', None)
        if df is None or df.empty:
            cantidad = 0
        else:
            # Depende solo de df_base y del día: no se recalcula en cada refresco de la bandeja
            clave = (datetime.now().date(), len(df))
            cache = self.__dict__.get('_cache_pendientes_vencido')
            if cache is None or cache[0] is not df or cache[1] != clave:
                cache = (df, clave, len(self._unidades_pendientes_marcar_vencido(df)))
                self.__dict__['_cache_pendientes_vencido'] = cache
            cantidad = cache[2]
        btn.setText(f" {cantidad}")
        btn.setVisible(bool(cantidad))
        self._sincronizar_grupos_barra()
        if cantidad:
            btn.setIcon(ThemeManager.icon('fa5s.calendar-times', color=estilo_com.ROJO))
            estilo_com.aplicar_estilo_boton_barra(btn, 'rojo')
            btn.setToolTip(
                f"{cantidad} unidad(es) con la fecha de término pasada siguen Vigente o en Activación Pendiente. "
                "Clic para marcarlas como Vencido.")
        else:
            btn.setIcon(ThemeManager.icon('fa5s.calendar-times', color=TEXT_SECONDARY))
            estilo_com.aplicar_estilo_boton_barra(btn, 'neutro')
            btn.setToolTip("Marcar como Vencido: no hay unidades con el estado desactualizado")

    def _marcar_vencido_df(self, df_pendientes):
        vins_ordenados = []
        vistos = set()
        for vin in df_pendientes.get('VIN', pd.Series(dtype=str)).astype(str).str.strip().str.upper():
            if not vin or vin == 'NAN' or vin in vistos:
                continue
            vistos.add(vin)
            vins_ordenados.append(vin)
        if not vins_ordenados:
            return

        # ETAPA GESTIÓN se recalcula acá (28-09-2026, corrección de bug real:
        # unidades Vigente+Activando marcadas Vencido quedaban con ETAPA
        # GESTIÓN=OPERACIONES desactualizada y seguían apareciendo en
        # Operaciones -> Activaciones) -- mismo patrón que
        # _on_accion_enviar_operaciones_clicked más arriba.
        estado_vencido = VALOR_ESTADO_COMERCIAL_VENCIDO.capitalize()
        df_lookup = df_pendientes.drop_duplicates('VIN', keep='last').set_index(
            df_pendientes['VIN'].astype(str).str.strip().str.upper()
        )
        lookup_por_vin = df_lookup.to_dict('index')

        valid = {}
        for vin in vins_ordenados:
            fila_actual = lookup_por_vin.get(vin, {})
            row_para_matriz = {
                COL_ESTADO_COMERCIAL: estado_vencido,
                COL_ESTADO_ACTIVACION: fila_actual.get(COL_ESTADO_ACTIVACION, ''),
                COL_TIPO_FACTURACION: fila_actual.get(COL_TIPO_FACTURACION, ''),
                COL_ETAPA_GESTION: fila_actual.get(COL_ETAPA_GESTION, ''),
            }
            nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada(row_para_matriz)
            # Se escribe "Vencido" (no "VENCIDO"); las comparaciones normalizan con upper()
            valid[vin] = {'VIN': vin, 'cambios': {
                COL_ESTADO_COMERCIAL: estado_vencido,
                COL_ETAPA_GESTION: nueva_etapa,
            }}
        comercial_services.agregar_id_a_cambios(valid, self.legacy.df_base)

        self.btn_accion_marcar_vencido.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando unidades como Vencido…")
        self._marcar_vencido_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._marcar_vencido_thread.finished_signal.connect(
            lambda success: self._on_marcar_vencido_finished(success, valid)
        )
        self._marcar_vencido_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._marcar_vencido_thread.start()

    def _on_marcar_vencido_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar la actualización de Vencidos. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            # Mismo criterio que _on_enviar_operaciones_finished: ESTADO
            # COMERCIAL cambió, así que cualquier otro módulo suscrito a
            # data_ready (ej. Operaciones) debe enterarse sin recarga manual.
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _on_accion_marcar_vigente_clicked(self):
        """"Marcar como Vigente" (sub-pestaña Vigentes, 24-09-2026, a pedido
        explícito): mismo mecanismo que "Marcar como Vencido" pero para el
        caso inverso -- la unidad ya está "Conectado" en Volvo Connect
        (ESTADO DE ACTIVACIÓN ACTUAL, dato externo que manda) pero ESTADO
        COMERCIAL quedó atrás en "Activación Pendiente" por error humano. NO
        usa la selección de la tabla: actúa sobre TODOS los vehículos de la
        bandeja "Vigentes" actualmente visible (_new_ui_bandeja_actual_df,
        ya filtrada por comercial_services.filtrar_vigentes y por el texto
        de búsqueda si hay) que cumplan esa combinación. Mismo mecanismo de
        guardado que "Marcar como Vencido" (SaveExcelThread /
        ExcelWriter.update_cells, con su backup ya incluido)."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            return

        df_bandeja = getattr(self, '_new_ui_bandeja_actual_df', None)
        if df_bandeja is None:
            return
        df_pendientes = comercial_services.pendientes_marcar_vigente(df_bandeja)

        vins_ordenados = []
        vistos = set()
        for vin in df_pendientes.get('VIN', pd.Series(dtype=str)).astype(str).str.strip().str.upper():
            if not vin or vin == 'NAN' or vin in vistos:
                continue
            vistos.add(vin)
            vins_ordenados.append(vin)
        if not vins_ordenados:
            return

        valid = comercial_services.agregar_id_a_cambios({
            vin: {'VIN': vin, 'cambios': {COL_ESTADO_COMERCIAL: VALOR_ESTADO_COMERCIAL_VIGENTE.capitalize()}}
            for vin in vins_ordenados
        }, self.legacy.df_base)

        self.btn_accion_marcar_vigente.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando unidades como Vigente…")
        self._marcar_vigente_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._marcar_vigente_thread.finished_signal.connect(
            lambda success: self._on_marcar_vigente_finished(success, valid)
        )
        self._marcar_vigente_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._marcar_vigente_thread.start()

    def _on_marcar_vigente_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar la actualización de Vigentes. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)
