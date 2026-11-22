"""Armado de los grupos de acciones rápidas de Comercial, papelera y paso a Conversión."""
from datetime import datetime
from PyQt6.QtWidgets import QMessageBox, QApplication
from PyQt6.QtCore import Qt
from src.services import comercial_services
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.core.constants import VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_FACTURACION_MANUAL
from src.ui.comercial.base import SaveExcelThread, EnviarPapeleraThread
from src.ui.comercial.dialogos import DialogoAccionCm
from src.ui.comercial.base import (
    EnviarPapeleraThread,
    SaveExcelThread,
)
from src.ui.comercial.dialogos import (
    DialogoAccionCm,
)


class _ArmadoAccionesComercialMixin:
    def _build_new_ui_acciones_rapidas_comunes(self):
        """Acciones comunes a las 4 sub-pestañas de Comercial. "Enviar
        correo" (ver _on_accion_cm_enviar_correo_clicked) abre MailDialog
        con los VIN seleccionados, con la plantilla "Aviso de Vencimiento"
        preseleccionada solo en "Gestionar CM". "Editar Unidad" (ver
        _on_accion_editar_unidad_clicked) reutiliza el mismo
        ComercialAgregarDialog/flujo de guardado de Vista Completa.
        "Agregar contacto" (ver _on_accion_agregar_contacto_clicked) abre
        el mismo ContactosAddDialog que ya usa Clientes y Flotas, con CDB/
        RAZÓN SOCIAL resueltos desde df_base por VIN. "Enviar a
        operaciones" todavía no tiene lógica conectada (fase siguiente).
        Todas se habilitan/deshabilitan según selección (ver
        _actualizar_estado_acciones_rapidas)."""
        widget = estilo_com.PanelAcciones(maestro=True)
        layout = estilo_com.GrillaAcciones(widget, impar_largo=True)
        self._grilla_maestra = layout

        self.btn_accion_cm_enviar_correo = self._build_new_ui_accion_button(
            "fa5s.envelope", "Enviar correo", "Contactar al cliente", color=estilo_com.AZUL
        )
        self.btn_accion_editar_unidad = self._build_new_ui_accion_button(
            "fa5s.file-contract", "Editar contrato", "Modificar los datos del contrato", color=estilo_com.VIOLETA
        )
        self.btn_accion_ver_general = self._build_new_ui_accion_button(
            "fa5s.search", "Ver en General", "Consulta la unidad y sus contratos", color=estilo_com.AZUL
        )
        self.btn_accion_crear_contrato = self._build_new_ui_accion_button(
            "fa5s.file-signature", "Crear contrato", "Nuevo contrato con los datos de la unidad y del cliente",
            color=estilo_com.VERDE
        )
        self.btn_accion_agregar_contacto = self._build_new_ui_accion_button(
            "fa5s.user-plus", "Agregar contacto", "Registrar contacto de la empresa", color=estilo_com.VERDE
        )
        self.btn_accion_enviar_operaciones = self._build_new_ui_accion_button(
            "fa5s.bolt", "Enviar a operaciones", "Deriva la unidad a Operaciones", color=estilo_com.AMBAR
        )
        self.btn_accion_fecha_baja = self._build_new_ui_accion_button(
            "fa5s.calendar-plus", "Asignar fecha de baja",
            "Graba la fecha de baja de las unidades desconectadas que no la tienen", color=estilo_com.ROJO
        )
        for btn in (
            self.btn_accion_cm_enviar_correo, self.btn_accion_editar_unidad, self.btn_accion_ver_general,
            self.btn_accion_crear_contrato, self.btn_accion_agregar_contacto, self.btn_accion_enviar_operaciones,
            self.btn_accion_fecha_baja,
        ):
            btn.setEnabled(False)
        self.btn_accion_ver_general.setVisible(False)
        self.btn_accion_crear_contrato.setVisible(False)
        self.btn_accion_fecha_baja.setVisible(False)

        self.btn_accion_cm_enviar_correo.clicked.connect(self._on_accion_cm_enviar_correo_clicked)
        self.btn_accion_editar_unidad.clicked.connect(self._on_accion_editar_unidad_clicked)
        self.btn_accion_ver_general.clicked.connect(self._on_accion_ver_general_clicked)
        self.btn_accion_crear_contrato.clicked.connect(self._on_accion_crear_contrato_clicked)
        self.btn_accion_agregar_contacto.clicked.connect(self._on_accion_agregar_contacto_clicked)
        self.btn_accion_enviar_operaciones.clicked.connect(self._on_accion_enviar_operaciones_clicked)
        self.btn_accion_fecha_baja.clicked.connect(self._on_accion_fecha_baja_clicked)

        layout.agregar(self.btn_accion_cm_enviar_correo)
        layout.agregar(self.btn_accion_editar_unidad)
        layout.agregar(self.btn_accion_ver_general)
        layout.agregar(self.btn_accion_crear_contrato)
        layout.agregar(self.btn_accion_agregar_contacto)
        layout.agregar(self.btn_accion_enviar_operaciones)
        layout.agregar(self.btn_accion_fecha_baja)

        return widget

    def _build_new_ui_acciones_rapidas_solo_cm(self):
        """Acciones exclusivas de "Gestionar CM", agregadas al panel común
        (ver _toggle_acciones_rapidas_panel).

        "Exportar lista" (28-09-2026, a pedido explícito, ver docs/07):
        el equipo nunca da de baja el contrato CM, solo avisa a quien
        administra esos contratos -- guarda la bandeja visible en el
        Escritorio para que el usuario se la envíe manualmente. No
        depende de selección.

        "Confirmar baja" sí modifica datos reales (ver
        _on_accion_cm_confirmar_baja_clicked) y queda restringido a casos
        ORIGEN_CASO = AUSENCIA_3PC (ver _actualizar_estado_acciones_rapidas):
        para ESTADO_EXPIRED el equipo tampoco decide eso, solo avisa -- de
        ahí "Exportar lista"."""
        widget = estilo_com.PanelAcciones()
        layout = estilo_com.GrillaAcciones(widget, maestra=self._grilla_maestra)

        self.btn_accion_cm_exportar_lista = self._build_new_ui_accion_button(
            "fa5s.file-export", "Exportar lista", "Guardar la bandeja visible en el Escritorio", color=estilo_com.PIZARRA
        )
        self.btn_accion_cm_exportar_lista.clicked.connect(self._on_accion_cm_exportar_lista_clicked)

        self.btn_accion_cm_confirmar_baja = self._build_new_ui_accion_button(
            "fa5s.check-circle", "Confirmar baja", "Cerrar el caso como baja de CM (solo Ausencia de 3PC)", color=estilo_com.ROJO
        )
        self.btn_accion_cm_confirmar_baja.setEnabled(False)
        self.btn_accion_cm_confirmar_baja.clicked.connect(self._on_accion_cm_confirmar_baja_clicked)

        self.btn_accion_cm_marcar_pendiente = self._build_new_ui_accion_button(
            "fa5s.hourglass-half", "Marcar pendiente",
            "El cliente no pagó y aún no hay respuesta de quien administra el CM: el estado del CM pasa a Pendiente y sigue en esta bandeja",
            color=estilo_com.VIOLETA
        )
        self.btn_accion_cm_marcar_pendiente.setEnabled(False)
        self.btn_accion_cm_marcar_pendiente.clicked.connect(self._on_accion_cm_marcar_pendiente_clicked)

        # Los dos primeros de todos los botones del panel (28-10-2026); "Exportar lista" ya no se muestra
        self.btn_accion_cm_pasar_a_cm = self._build_new_ui_accion_button(
            "fa5s.exchange-alt", "Pasar a CM", "Forma CMG, CMB o CMS y facturación CM según el tipo de CM",
            color=estilo_com.AZUL)
        self.btn_accion_cm_pasar_a_cm.setEnabled(False)
        self.btn_accion_cm_pasar_a_cm.clicked.connect(self._on_accion_cm_pasar_a_cm_clicked)
        self.btn_accion_cm_limpiar = self._build_new_ui_accion_button(
            "fa5s.eraser", "Limpiar datos CM", "Deja en '-' los datos del 3PC de contratos que ya no son CM",
            color=estilo_com.ROJO)
        self.btn_accion_cm_limpiar.setEnabled(False)
        self.btn_accion_cm_limpiar.clicked.connect(self._on_accion_cm_limpiar_clicked)

        layout.agregar(self.btn_accion_cm_pasar_a_cm, 0)
        layout.agregar(self.btn_accion_cm_limpiar, 1)
        layout.agregar(self.btn_accion_cm_marcar_pendiente)
        layout.agregar(self.btn_accion_cm_confirmar_baja)

        return widget

    def _build_new_ui_acciones_rapidas_solo_vencidos(self):
        """Acción exclusiva de "Vencidos" (23-09-2026), agregada al panel
        común (ver _toggle_acciones_rapidas_panel). Se habilita con las filas
        seleccionadas cuya fecha de término ya expiró y cuyo ESTADO
        COMERCIAL todavía no dice "Vencido" (ver
        _on_accion_marcar_vencido_clicked/_actualizar_boton_marcar_vencido).
        Modifica datos reales en PruebasFM.xlsx."""
        widget = estilo_com.PanelAcciones()
        layout = estilo_com.GrillaAcciones(widget, maestra=self._grilla_maestra)

        self.btn_accion_marcar_vencido = self._build_new_ui_accion_button(
            "fa5s.calendar-times", "Marcar como Vencido", "Corrige el estado desactualizado", color=estilo_com.ROJO
        )
        self.btn_accion_marcar_vencido.setEnabled(False)
        self.btn_accion_marcar_vencido.clicked.connect(self._on_accion_marcar_vencido_clicked)

        self.btn_accion_renovar = self._build_new_ui_accion_button(
            "fa5s.redo-alt", "Extender duración", "Extiende los meses del contrato", color=estilo_com.VERDE
        )
        self.btn_accion_renovar.setEnabled(False)
        self.btn_accion_renovar.clicked.connect(self._on_accion_renovar_clicked)

        self.btn_accion_renovar_nuevo = self._build_new_ui_accion_button(
            "fa5s.file-contract", "Renovar contrato",
            "Reemplaza este contrato por uno nuevo (ej. Provisión a Conversión); el actual queda como Renovado",
            color=estilo_com.AZUL
        )
        self.btn_accion_renovar_nuevo.setEnabled(False)
        self.btn_accion_renovar_nuevo.clicked.connect(self._on_accion_renovar_nuevo_clicked)

        layout.agregar(self.btn_accion_marcar_vencido)
        layout.agregar(self.btn_accion_renovar)
        layout.agregar(self.btn_accion_renovar_nuevo)
        self._grilla_acciones_vencidos = layout

        return widget

    def _build_new_ui_acciones_rapidas_solo_papelera(self):
        """Acción exclusiva de "Nuevas oportunidades": envía a la papelera
        contratos "SIN VC" (unidades que no quisieron o no respondieron al
        servicio). Ver _on_accion_papelera_clicked."""
        widget = estilo_com.PanelAcciones()
        layout = estilo_com.GrillaAcciones(widget, maestra=self._grilla_maestra)

        self.btn_accion_papelera = self._build_new_ui_accion_button(
            "fa5s.trash-alt", "Enviar a papelera", "Solo contratos SIN VC", color=estilo_com.ROJO
        )
        self.btn_accion_papelera.setEnabled(False)
        self.btn_accion_papelera.clicked.connect(self._on_accion_papelera_clicked)
        layout.agregar(self.btn_accion_papelera)
        return widget

    def _build_new_ui_acciones_rapidas_solo_conversion(self):
        """Acción de "Recuperar clientes" y "Renovar contratos": pasa varias unidades de Provisión a
        Conversión con facturación manual (ver _on_accion_a_conversion_clicked)."""
        widget = estilo_com.PanelAcciones()
        layout = estilo_com.GrillaAcciones(widget, maestra=self._grilla_maestra)
        self.btn_accion_a_conversion = self._build_new_ui_accion_button(
            "fa5s.exchange-alt", "A Facturación Manual", "Pasar unidades de Provisión a Facturación Manual", color=estilo_com.VERDE
        )
        self.btn_accion_a_conversion.setEnabled(False)
        self.btn_accion_a_conversion.clicked.connect(self._on_accion_a_conversion_clicked)
        layout.agregar(self.btn_accion_a_conversion)
        return widget

    def _actualizar_boton_a_conversion(self, vins, filas):
        habilitado = bool(vins) and all(comercial_services.es_forma_provision(filas[v]) for v in vins)
        self.btn_accion_a_conversion.setEnabled(habilitado)
        self.btn_accion_a_conversion.setToolTip(
            "Pasa las unidades seleccionadas a Facturación Manual (Conversión), Vigente y Conectado." if habilitado
            else "Solo se pueden pasar unidades cuya forma de contrato sea Provisión.")

    def _on_accion_a_conversion_clicked(self):
        """Pasa de una vez las unidades seleccionadas de Provisión a Conversión: Facturación
        Manual, Vigente y Conectado (Comercial, sin pasar por Operaciones), inicio el día 1 del
        mes actual, duración mensual ("-") y sin fecha de baja. Mismo guardado que "Marcar como
        Vigente" (SaveExcelThread, con su backup)."""
        vins, filas = self._obtener_vins_seleccionados()
        if not vins or not all(comercial_services.es_forma_provision(filas[v]) for v in vins):
            return
        inicio = datetime.now().replace(day=1).strftime("%d-%m-%Y")
        confirmar = QMessageBox.question(
            self, "Pasar a Facturación Manual",
            f"Se pasarán {len(vins)} unidad(es) de Provisión a:\n\n"
            "• Forma de contrato: Conversion\n"
            "• Tipo de facturación: Facturación Manual\n"
            "• Estado comercial: Vigente y estado de activación: Conectado (quedan en Comercial)\n"
            f"• Inicio del contrato: {inicio}\n"
            "• Duración: mensual (\"-\")\n"
            "• Se borra la fecha de baja\n\n"
            "Se guarda con copia de seguridad.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmar != QMessageBox.StandardButton.Yes:
            return
        valid = comercial_services.cambios_provision_a_conversion(filas, self.legacy.df_base)
        self.btn_accion_a_conversion.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Pasando unidades a Conversión…")
        self._a_conversion_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._a_conversion_thread.finished_signal.connect(lambda success: self._on_a_conversion_finished(success, valid))
        self._a_conversion_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._a_conversion_thread.start()

    def _on_a_conversion_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self, "No se pudo guardar el cambio a Conversión. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return
        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()
        self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _vins_sin_vc_seleccionados(self):
        """VIN de la selección, solo si TODOS son SIN VC (forma de contrato
        Sin Contrato y tipo de facturación Sin Registro); si no, lista vacía."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_POR_GESTIONAR:
            return []
        vins, _ = self._obtener_vins_seleccionados()
        if vins and all(self._es_unidad_sin_contrato_sin_registro(vin) for vin in vins):
            return vins
        return []

    def _actualizar_boton_papelera(self):
        habilitado = bool(self._vins_sin_vc_seleccionados())
        self.btn_accion_papelera.setEnabled(habilitado)
        self.btn_accion_papelera.setToolTip("" if habilitado else "Solo se pueden enviar a la papelera contratos SIN VC.")

    def _on_accion_papelera_clicked(self):
        """Envía a la papelera (RegistroEliminado) el contrato actual de cada
        VIN SIN VC seleccionado, por ID. No se puede deshacer desde la app."""
        vins = self._vins_sin_vc_seleccionados()
        if not vins:
            return
        df_base = self.legacy.df_base
        contratos = comercial_services.agregar_id_a_cambios({vin: {} for vin in vins}, df_base)
        items = [(vin, contratos[vin].get('ID')) for vin in vins]

        confirmar = QMessageBox.question(
            self, "Enviar a papelera",
            f"Se enviarán a la papelera {len(items)} contrato(s) SIN VC. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmar != QMessageBox.StandardButton.Yes:
            return

        self.btn_accion_papelera.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Enviando a la papelera…")
        self._papelera_thread = EnviarPapeleraThread(self.legacy.writer, items, module_name="Comercial")
        self._papelera_thread.finished_signal.connect(lambda ok, hechos: self._on_papelera_finished(ok, hechos))
        self._papelera_thread.start()

    def _on_papelera_finished(self, success, eliminados):
        QApplication.restoreOverrideCursor()
        dm = self.legacy.data_manager
        if eliminados and not dm.df_master.empty:
            for vin, id_contrato in eliminados:
                dm.df_master = comercial_services.quitar_vin(dm.df_master, vin, id_contrato)
            dm.data_ready.emit()
            self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
            self._refresh_new_ui_data()
        self._actualizar_estado_acciones_rapidas()
        if success:
            guardado_listo(self, "Enviado a la papelera")
            terminar_guardando(self, texto_exito="Enviado a la papelera")
            QMessageBox.information(self, "Papelera", f"Se enviaron {len(eliminados)} contrato(s) a la papelera.")
        else:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(
                self, "Error",
                f"Se enviaron {len(eliminados)} contrato(s) a la papelera y el resto no se pudo eliminar. Intenta de nuevo.")

    def _build_new_ui_acciones_rapidas_solo_vigentes(self):
        """Acción exclusiva de "Vigentes" (24-09-2026, pedido explícito del
        usuario): igual que "Marcar como Vencido" en Vencidos, NO depende de
        la selección de la tabla -- actúa sobre TODOS los vehículos de la
        bandeja "Vigentes" con ESTADO COMERCIAL = "Activación Pendiente" Y
        ESTADO DE ACTIVACIÓN ACTUAL = "Conectado" (ver
        _on_accion_marcar_vigente_clicked/_actualizar_boton_marcar_vigente).
        Modifica datos reales en PruebasFM.xlsx."""
        widget = self.acciones_rapidas_vencidos
        layout = self._grilla_acciones_vencidos

        self.btn_accion_marcar_vigente =self._build_new_ui_accion_button(
            "fa5s.check-circle", "Marcar como Vigente", "Corrige el estado desactualizado", color=estilo_com.VERDE
        )
        self.btn_accion_marcar_vigente.setEnabled(False)
        self.btn_accion_marcar_vigente.clicked.connect(self._on_accion_marcar_vigente_clicked)

        layout.agregar(self.btn_accion_marcar_vigente)

        return widget

    def _build_new_ui_acciones_rapidas_solo_inconsistencias(self):
        """Acción exclusiva del modo "Revisar inconsistencias": corrige el
        TIPO DE FACTURACION de la selección (una o varias unidades) cuando
        la matriz de forma de contrato tiene una única opción válida."""
        widget = estilo_com.PanelAcciones()
        layout = estilo_com.GrillaAcciones(widget, maestra=self._grilla_maestra)

        self.btn_accion_arreglar_tipo_fact = self._build_new_ui_accion_button(
            "fa5s.magic", "Arreglar tipo de facturación", "Corrige el tipo de facturación según la forma de contrato",
            color=estilo_com.AZUL
        )
        self.btn_accion_arreglar_tipo_fact.setEnabled(False)
        self.btn_accion_arreglar_tipo_fact.clicked.connect(self._on_arreglar_tipo_fact_seleccion_clicked)

        layout.agregar(self.btn_accion_arreglar_tipo_fact)

        self.btn_accion_asignar_tipo_fact = self._build_new_ui_accion_button(
            "fa5s.user", "Facturar a cliente", "Las unidades de Venta o Conversión seleccionadas se facturan al cliente",
            color=estilo_com.VERDE
        )
        self.btn_accion_asignar_tipo_fact.setEnabled(False)
        self.btn_accion_asignar_tipo_fact.clicked.connect(
            lambda: self._on_asignar_tipo_fact_clicked(VALOR_TIPO_FACT_CLIENTE))
        layout.agregar(self.btn_accion_asignar_tipo_fact)

        self.btn_accion_asignar_tipo_fact_manual = self._build_new_ui_accion_button(
            "fa5s.file-invoice-dollar", "Facturación manual",
            "Las unidades de Venta o Conversión seleccionadas pasan a facturación manual",
            color=estilo_com.AZUL
        )
        self.btn_accion_asignar_tipo_fact_manual.setEnabled(False)
        self.btn_accion_asignar_tipo_fact_manual.clicked.connect(
            lambda: self._on_asignar_tipo_fact_clicked(VALOR_TIPO_FACT_FACTURACION_MANUAL))
        layout.agregar(self.btn_accion_asignar_tipo_fact_manual)

        return widget

    def _build_new_ui_acciones_rapidas_solo_fechas(self):
        """Acción exclusiva de "Revisar fechas": graba el término calculado de
        la selección (una o varias unidades)."""
        widget = estilo_com.PanelAcciones()
        layout = estilo_com.GrillaAcciones(widget, maestra=self._grilla_maestra)
        self.btn_accion_fecha_real = self._build_new_ui_accion_button(
            "fa5s.calendar-check", "Fecha real", "Graba en el archivo el término calculado (inicio + duración)",
            color=estilo_com.AZUL
        )
        self.btn_accion_fecha_real.setEnabled(False)
        self.btn_accion_fecha_real.clicked.connect(self._on_fecha_real_seleccion_clicked)
        layout.agregar(self.btn_accion_fecha_real)
        return widget

    def _resolver_vin_por_fila_new_ui(self, row_idx):
        """VIN de una fila de new_ui_table por índice, para el resolver de
        VolvoTableWidget._get_vin_for_row (menú contextual "Copiar VIN").
        Misma fuente/orden que _obtener_vins_seleccionados, pero para una
        sola fila en vez de la selección completa."""
        if self._new_ui_en_grupos:
            return None
        es_revision_cm = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM
        df_fuente = getattr(self, '_new_ui_revision_cm_df', None) if es_revision_cm \
            else getattr(self, '_new_ui_bandeja_actual_df', None)
        if df_fuente is None or df_fuente.empty or row_idx >= len(df_fuente):
            return None
        vin = str(df_fuente.iloc[row_idx].get('VIN', '')).strip()
        return vin if vin and vin.upper() != 'NAN' else None
