"""Acciones sobre unidades seleccionadas en Comercial: contacto, edición, exportación y casos CM."""
from src.theme.colors import PRIMARY
import pandas as pd
import os
from datetime import datetime
from PyQt6.QtWidgets import QDialog, QMessageBox, QApplication, QFileDialog
from PyQt6.QtCore import Qt, QStandardPaths
from src.services import comercial_services
from src.services import cm_bajas_service
from src.services import contratos_service as ct_service
from src.services import mail_sync_service
from src.services import contactos_service
from src.ui.compartido.mail_dialog import MailDialog
from src.ui.administracion.contactos_agregar import ContactosAddDialog
from src.ui.administracion.contactos import AddContactoThread
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.theme.theme_manager import ThemeManager
import config.settings
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.constants import COL_ESTADO_COMERCIAL, ESTADO_CM_PENDIENTE, VALOR_ESTADO_COMERCIAL_BAJA, COL_ETAPA_GESTION, COL_TIPO_FACTURACION, COL_FORMA_CONTRATO, COL_ESTADO_ACTIVACION, VALOR_TIPO_FACT_SIN_REGISTRO
from src.ui.comercial.base import logger, SaveExcelThread, ACCION_RAPIDA_BUTTON_STYLE_DEFAULT
from src.ui.comercial.dialogos import DialogoAccionCm
from src.ui.comercial.base import (
    ACCION_RAPIDA_BUTTON_STYLE_DEFAULT,
    SaveExcelThread,
    logger,
)
from src.ui.comercial.dialogos import (
    DialogoAccionCm,
)


class _AccionesUnidadComercialMixin:
    def _filas_seleccionadas(self):
        """Filas seleccionadas de new_ui_table. Mientras se actualizan las acciones (que lo piden muchas veces) se
        leen una sola vez: `selectedRows` consulta cada celda del modelo y con cientos de filas tarda."""
        cache = self.__dict__.get('_filas_sel_actualizacion')
        if cache is not None:
            return cache
        if self.__dict__.get('_new_ui_en_grupos'):
            return ()
        return tuple(i.row() for i in self.new_ui_table.selectionModel().selectedRows())

    def _obtener_vins_seleccionados(self):
        """Resuelve la selección actual de new_ui_table a una lista de VIN
        normalizados, deduplicados y en el orden de selección, junto con la
        fila original de cada uno -- para cualquiera de las 4 sub-pestañas.

        "Gestionar CM" resuelve contra _new_ui_revision_cm_df (CasosBajaCM.csv,
        con CASO_ID incluido); "Por gestionar"/"Renovaciones"/"Gestionar
        Bajas" resuelven contra _new_ui_bandeja_actual_df (subconjunto de
        df_base con todas sus columnas, aunque no todas se muestren). Ambos
        atributos se guardan en _refresh_new_ui_data justo antes de recortar
        a las columnas visibles, en el mismo orden que recibe el modelo.

        Compartido por "Enviar correo" (las 4 sub-pestañas) y "Confirmar
        baja" (solo Gestionar CM) para no resolver la selección dos veces
        con lógica distinta."""
        seleccion = self._filas_seleccionadas()
        if not seleccion or self._new_ui_en_grupos:
            return [], {}

        es_revision_cm = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM
        df_fuente = getattr(self, '_new_ui_revision_cm_df', None) if es_revision_cm \
            else getattr(self, '_new_ui_bandeja_actual_df', None)
        if df_fuente is None or df_fuente.empty:
            return [], {}

        filas_sel = tuple(r for r in seleccion if r < len(df_fuente))
        # Un cambio de selección lo pide varias veces (acciones, ficha, renovar...): se resuelve una sola vez
        cache = self.__dict__.get('_cache_vins_seleccion')
        if cache is not None and cache[0] is df_fuente and cache[1] == filas_sel:
            return list(cache[2]), dict(cache[3])

        vins_ordenados = []
        filas_por_vin = {}
        if filas_sel:
            sub = df_fuente.iloc[list(filas_sel)]
            valores = sub.to_numpy(dtype=object)
            columnas = sub.columns
            posicion_vin = columnas.get_loc('VIN') if 'VIN' in columnas else None
            for i, row_idx in enumerate(filas_sel):
                crudo = valores[i][posicion_vin] if posicion_vin is not None else ''
                vin = str(crudo).strip().upper() if crudo is not None and not pd.isna(crudo) else ''
                if not vin or vin == 'NAN' or vin in filas_por_vin:
                    continue
                vins_ordenados.append(vin)
                filas_por_vin[vin] = pd.Series(valores[i], index=columnas, name=sub.index[i])

        self.__dict__['_cache_vins_seleccion'] = (df_fuente, filas_sel, tuple(vins_ordenados), dict(filas_por_vin))
        return vins_ordenados, filas_por_vin

    def _on_accion_cm_enviar_correo_clicked(self):
        """Abre MailDialog con los VIN seleccionados en la sub-pestaña
        activa (cualquiera de las 4) ya buscados/marcados -- toda la
        validación de correo faltante, destinatarios y envío la sigue
        haciendo MailDialog, no se duplica aquí (ver
        mail_dialog.MailDialog._preseleccionar_vins).

        Si algún VIN seleccionado no está en Correos.csv (la base quedó
        desactualizada respecto a Comercial, ver mail_sync_service.
        cruzar_correos_maestro: toda fila de Comercial siempre queda en el
        cruce, tenga o no correo), no se abre el diálogo preseleccionado:
        se avisa cuáles VIN faltan y se ofrece abrir el Gestor de Correos
        normal (sin preselección) para que el usuario sincronice
        manualmente con "Sincronizar BBDD Correos" -- esa sincronización
        nunca se dispara sola desde acá.

        Plantilla preseleccionada según la sub-pestaña (ver
        _PLANTILLA_CORREO_POR_SUBTAB): "Aviso de Vencimiento" en Gestionar
        CM, "Reactivación" en Recuperar clientes y "Conoce Volvo Connect" en
        Nuevas oportunidades. Renovar contratos abre sin plantilla. El
        usuario puede cambiarla en el diálogo."""
        vins_ordenados, _ = self._obtener_vins_seleccionados()
        if not vins_ordenados:
            return

        faltantes = mail_sync_service.vins_faltantes_en_correos(vins_ordenados, config.settings.CORREOS_EXCEL_PATH)
        if faltantes:
            dialogo = DialogoAccionCm.vins_faltantes_en_correos(self, faltantes)
            if dialogo.exec() == QDialog.DialogCode.Accepted:
                MailDialog(parent=self).exec()
            return

        plantilla_inicial = self._PLANTILLA_CORREO_POR_SUBTAB.get(getattr(self, '_new_ui_active_subtab', 0))
        dialogo = MailDialog(parent=self, vins_preseleccionados=vins_ordenados, plantilla_inicial=plantilla_inicial)
        dialogo.exec()

    def _resolver_cdb_razon_social(self, vin):
        """CDB y RAZÓN SOCIAL de un VIN, resueltos siempre contra
        self.legacy.df_base (PruebasFM) -- fuente canónica de esos datos
        para cualquier VIN, independiente de la sub-pestaña activa. Se
        resuelve así (y no contra la bandeja de la sub-pestaña actual)
        porque "Gestionar CM" sale de CasosBajaCM.csv, que no trae CDB (ver
        cm_bajas_service.CASOS_BAJA_CM_COLUMNS). Devuelve ('', '') si el
        VIN no aparece en df_base."""
        df_base = self.legacy.df_base
        if df_base.empty or 'VIN' not in df_base.columns:
            return '', ''
        pos = self._posicion_vin_en_df(df_base, vin)
        if pos is None:
            return '', ''
        fila = df_base.iloc[pos]
        cdb = '' if pd.isna(fila.get('CDB')) else str(fila.get('CDB')).strip()
        razon_social = '' if pd.isna(fila.get('RAZÓN SOCIAL')) else str(fila.get('RAZÓN SOCIAL')).strip()
        return cdb, razon_social

    def _cdb_tiene_contacto(self, cdb):
        """True si existe al menos un contacto en contactos.xlsx
        (data_manager.get_contactos_df()) para ese CDB. La relación
        contacto <-> empresa es por CDB, nunca por VIN (ver conversación
        con el usuario, Fase 4): no se busca ninguna columna VIN dentro de
        contactos.xlsx porque no existe."""
        cdb_str = str(cdb).strip()
        if not cdb_str:
            return False
        df_contactos = self.legacy.data_manager.get_contactos_df()
        if df_contactos.empty or 'CDB' not in df_contactos.columns:
            return False
        return bool((df_contactos['CDB'].astype(str).str.strip() == cdb_str).any())

    def _aplicar_estilo_agregar_contacto(self, tiene_contacto):
        """Azul si el CDB del VIN seleccionado ya tiene contacto, rojo si
        no tiene ninguno; estilo neutro (con el mismo :disabled ya definido
        en ACCION_RAPIDA_BUTTON_STYLE_DEFAULT) cuando no hay exactamente un
        VIN seleccionado (tiene_contacto=None)."""
        btn = self.btn_accion_agregar_contacto
        if tiene_contacto is None:
            btn.setStyleSheet(getattr(btn, '_qss_por_defecto', ACCION_RAPIDA_BUTTON_STYLE_DEFAULT))
            self._pintar_icono_accion(btn, 'fa5s.user-plus', estilo_com.VERDE)
        elif tiene_contacto:
            self._pintar_icono_accion(btn, 'fa5s.user-check', estilo_com.VERDE)
        else:
            self._pintar_icono_accion(btn, 'fa5s.user-plus', estilo_com.ROJO)

    @staticmethod
    def _pintar_icono_accion(btn, icon_name, color):
        btn._icono_frame.setStyleSheet(estilo_com.qss_icono_accion(color))
        btn._icono_lbl.setPixmap(ThemeManager.icon_pixmap(icon_name, color=color, size=12))

    def _es_unidad_sin_contrato_sin_registro(self, vin):
        """True solo si la unidad con este VIN tiene FORMA DE CONTRATO='Sin
        Contrato' y TIPO DE FACTURACION='Sin Registro' (25-09-2026, ver
        _on_accion_editar_unidad_clicked): el caso real de una unidad recién
        creada desde comercial_agregar.py/general.py que todavía no fue
        gestionada comercialmente, único caso donde forzar ESTADO
        COMERCIAL/ESTADO DE ACTIVACIÓN ACTUAL al abrir "Por gestionar" tiene
        sentido de negocio."""
        df = self.df_base
        if df.empty or 'VIN' not in df.columns:
            return False
        coincidencias = df[df['VIN'].astype(str).str.strip().str.upper() == str(vin).strip().upper()]
        if coincidencias.empty:
            return False
        fila = coincidencias.iloc[0]
        forma =str(fila.get(COL_FORMA_CONTRATO, '')).strip().upper()
        tipo_fact = str(fila.get(COL_TIPO_FACTURACION, '')).strip().upper()
        return forma == 'SIN CONTRATO' and tipo_fact == VALOR_TIPO_FACT_SIN_REGISTRO

    def _puede_editar_en_bloque(self, vins):
        """Dos o más unidades de "Nuevas oportunidades" sin contrato ni registro: se editan juntas con los mismos valores."""
        if len(vins) < 2 or self.new_ui_subtabs.currentIndex() != self._NEW_UI_SUBTAB_POR_GESTIONAR:
            return False
        df = self.df_base
        if df is None or df.empty or 'VIN' not in df.columns:
            return False
        claves = {str(v).strip().upper() for v in vins}
        seleccion = df[df['VIN'].astype(str).str.strip().str.upper().isin(claves)]
        if len(seleccion) != len(claves):
            return False
        forma = seleccion[COL_FORMA_CONTRATO].astype(str).str.strip().str.upper() == 'SIN CONTRATO'
        tipo = seleccion[COL_TIPO_FACTURACION].astype(str).str.strip().str.upper() == VALOR_TIPO_FACT_SIN_REGISTRO
        return bool((forma & tipo).all())

    def _on_accion_editar_unidad_clicked(self):
        """Reutiliza _ComercialModuleLegacy._handle_editar_unidad(row, vin)
        tal cual (mismo ComercialAgregarDialog en modo edición, mismo
        SaveExcelThread/ExcelWriter.update_cells, mismo backup y log a
        LogApp.csv que ya funciona en Vista Completa) -- self._handle_
        editar_unidad no es un método propio de ComercialModule, así que
        __getattr__ lo resuelve contra self.legacy automáticamente (ver
        __getattr__ más abajo); `row` no se usa dentro de ese método, solo
        `vin`, así que se pasa 0 como valor de relleno."""
        vins_ordenados, _ = self._obtener_vins_seleccionados()
        if self._puede_editar_en_bloque(vins_ordenados):
            claves = {v.strip().upper() for v in vins_ordenados}
            df = self.df_base
            seleccion = df[df['VIN'].astype(str).str.strip().str.upper().isin(claves)]
            datos_por_vin = {
                str(fila['VIN']).strip().upper(): {col: ('' if pd.isna(val) else str(val)) for col, val in fila.items()}
                for _, fila in seleccion.iterrows()}
            if len(datos_por_vin) > 1:
                self._iniciar_edicion_multiple(datos_por_vin)
            return
        if len(vins_ordenados) != 1:
            return
        # Modo restringido (22-09-2026, ampliado a "Ofrecer y reactivar" --
        # antes "Gestionar Bajas" -- a pedido explícito): al editar desde
        # "Por gestionar" (índice 0) o desde "Ofrecer y reactivar" (índice
        # _NEW_UI_SUBTAB_OFRECER_REACTIVAR, caso "cliente interesado en
        # volver") -- Renovaciones y Gestionar CM mantienen edición completa.
        # "Vigentes" (índice _NEW_UI_SUBTAB_VIGENTES, 25-09-2026) tiene su
        # propio modo restringido (ver desde_vigentes en
        # _handle_editar_unidad/restringir_vigentes en
        # ComercialAgregarDialog): no fuerza valores, solo recorta ESTADO
        # COMERCIAL y bloquea Operaciones.
        #
        # Ajustado (25-09-2026, pedido explícito): "Por gestionar" ya no es
        # SOLO la unidad recién creada desde comercial_agregar.py/general.py
        # -- desde que _mask_revisar_hacia_comercial() amplió el filtro,
        # también caen ahí unidades reales con FORMA DE CONTRATO/TIPO DE
        # FACTURACION ya definidos (ej. combinaciones de "Revisar" que la
        # matriz manda a COMERCIAL). Operaciones se bloquea siempre para
        # cualquier unidad de "Por gestionar"/"Ofrecer y reactivar" (nadie
        # gestiona Operaciones desde este formulario), pero forzar
        # "Activación Pendiente"/"Activando" solo tiene sentido para la
        # unidad todavía sin contrato ni registro (el punto de partida real
        # del flujo de activación) -- ver forzar_activacion_pendiente.
        idx_activo = self.new_ui_subtabs.currentIndex()
        desde_por_gestionar = idx_activo in (self._NEW_UI_SUBTAB_POR_GESTIONAR, self._NEW_UI_SUBTAB_OFRECER_REACTIVAR)
        forzar_activacion_pendiente = desde_por_gestionar and self._es_unidad_sin_contrato_sin_registro(vins_ordenados[0])
        desde_vigentes = idx_activo == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES and self._unidad_vigente_en_curso(vins_ordenados[0])
        self._handle_editar_unidad(
            0, vins_ordenados[0], desde_por_gestionar=desde_por_gestionar,
            forzar_activacion_pendiente=forzar_activacion_pendiente, desde_vigentes=desde_vigentes,
            vin_editable=True,
        )
        form = getattr(self, 'unidad_nueva_form', None)
        combo_forma = form.inputs.get('FORMA DE CONTRATO') if form is not None else None
        if combo_forma is not None:
            bloquear_forma = idx_activo == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
            if bloquear_forma:
                combo_forma.setEnabled(False)
            combo_forma.setToolTip("Para cambiar la forma de contrato usa \"Renovar contrato\"." if bloquear_forma else "")
        # Con el CDB comercial distinto al de la empresa, el formulario abre posado en ese campo
        cdb, razon_social = self._resolver_cdb_razon_social(vins_ordenados[0])
        if form is not None and comercial_services.cdb_discrepante(cdb, razon_social, self._cdb_referencia_actual()):
            campo = form.inputs.get('CDB')
            if campo is not None and campo.isEnabled():
                campo.setFocus()
                campo.selectAll()

    def _on_accion_agregar_contacto_clicked(self):
        """Abre el mismo ContactosAddDialog que ya usa Clientes y Flotas
        (general.py._handle_agregar_contacto) y Contactos (contactos.py.
        _open_add_dialog), con CDB/RAZÓN SOCIAL resueltos desde df_base por
        el VIN seleccionado (ver _resolver_cdb_razon_social). Mismo
        mecanismo de guardado (AddContactoThread -> ExcelWriter.
        add_new_row, con su backup ya incluido) y mismo ID autogenerado
        (contactos_service.generar_nuevo_id_contacto). No valida
        duplicados: un mismo correo puede repetirse en otra empresa
        (decisión explícita, ver conversación con el usuario, Fase 4)."""
        vins_ordenados, _ = self._obtener_vins_seleccionados()
        if len(vins_ordenados) != 1:
            return
        cdb, razon_social = self._resolver_cdb_razon_social(vins_ordenados[0])

        dialog = ContactosAddDialog(self, cdb_prefill=cdb, flota_prefill=razon_social)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_data = dialog.get_data()
        new_data['ID'] = contactos_service.generar_nuevo_id_contacto(self.legacy.data_manager.get_contactos_df())

        self.btn_accion_agregar_contacto.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Agregando el contacto…")
        self._add_contacto_thread_comercial = AddContactoThread(self.legacy.writer, new_data)
        self._add_contacto_thread_comercial.finished_signal.connect(self._on_agregar_contacto_comercial_finished)
        self._add_contacto_thread_comercial.start()

    def _on_agregar_contacto_comercial_finished(self, success, new_data):
        QApplication.restoreOverrideCursor()
        # Recalcula habilitación Y color (no un simple setEnabled(True)):
        # la selección pudo no cambiar, pero el CDB recién agregado ya
        # tiene contacto ahora.
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se pudo agregar el contacto. Verifica si contactos.xlsx está abierto.")
            return
        terminar_guardando(self, texto_exito="Contacto agregado")
        # Mismo mecanismo de refresco que general.py: recarga contactos.xlsx
        # desde disco: al terminar emite contactos_ready, ya conectado a
        # _actualizar_estado_acciones_rapidas (ver __init__) para que el
        # botón refleje el nuevo contacto sin esperar un cambio de selección.
        self.legacy.data_manager.load_contactos_async()

    _COLUMNAS_EXPORT_BANDEJA = (
        'FLOTA VC', 'RAZÓN SOCIAL', 'RUT', 'CDB FLOTA', 'EJECUTIVO', 'VIN', 'CHASIS', 'ESTADO COMERCIAL',
        'ESTADO DE ACTIVACIÓN ACTUAL', 'ETAPA GESTIÓN', 'FORMA DE CONTRATO', 'TIPO DE FACTURACION', 'TIPO DE SERVICIO',
        'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO', 'DÍAS RESTANTES', 'N CONTRATO 3PC', 'TIPO DE CM',
        'ESTADO DEL CM', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'PAGO CM', 'MOTIVO', 'PERIODO_DETECCION')

    def _exportar_excel_bandeja(self):
        """Excel de la pestaña que se ve (con su tarjeta, búsqueda y orden), un contrato por fila con sus datos."""
        subtab = getattr(self, '_new_ui_active_subtab', 0)
        if subtab == self._NEW_UI_SUBTAB_AVISOS:
            self.new_ui_table.export_to_excel("Avisos_de_gestion")
            return
        if subtab == self._NEW_UI_SUBTAB_REVISION_CM:
            df = getattr(self, '_new_ui_revision_cm_completo', None)
        else:
            df = getattr(self, '_new_ui_bandeja_actual_df', None)
        if df is None or df.empty:
            QMessageBox.information(self, "Exportar", "No hay datos visibles.")
            return
        nombre = self._NEW_UI_SUBTAB_NOMBRES[subtab]
        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar Excel", os.path.join(carpeta, f"Reporte_{nombre.replace(' ', '_')}.xlsx"), "Archivos Excel (*.xlsx)")
        if not ruta:
            return
        columnas = [c for c in self._COLUMNAS_EXPORT_BANDEJA if c in df.columns]
        extras = [c for c in self.new_ui_model.get_df().columns if c in df.columns and c not in columnas]
        salida = df[columnas + extras].reset_index(drop=True)
        from src.ui.compartido.exportacion import iniciar_exportacion
        iniciar_exportacion(self, salida, ruta, atributo_hilo='_export_bandeja_thread', titulo=nombre)

    def _on_accion_cm_exportar_lista_clicked(self):
        """"Exportar lista" (28-09-2026, a pedido explícito): guarda la
        bandeja de "Gestionar CM" tal como se ve en pantalla (mismas
        columnas visibles, respeta la búsqueda activa -- esta sub-pestaña
        y el filtro de tarjeta KPI activo) directo en el Escritorio del
        usuario, sin diálogo de guardado. El equipo no da de baja el
        contrato CM: solo avisa a quien lo administra, y este archivo es
        lo que se les envía manualmente (ver docs/07, sección CM).

        Reutiliza ExportExcelThread (mismo usado por
        VolvoTableWidget.export_to_excel) en vez de reimplementar la
        escritura del Excel -- ya sabe reconvertir "PAGO CM" de texto
        formateado a número nativo."""
        df_visible = self.new_ui_model.get_df()
        if df_visible.empty:
            QMessageBox.information(self, "Exportar lista", "No hay casos pendientes para exportar.")
            return
        if getattr(self, '_export_cm_thread', None) is not None and self._export_cm_thread.isRunning():
            QMessageBox.information(self, "Exportar lista", "Ya hay una exportación en curso. Espera a que termine.")
            return

        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        filepath = os.path.join(carpeta, f"Casos_CM_Pendientes_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx")

        from src.ui.compartido.exportacion import iniciar_exportacion
        iniciar_exportacion(self, df_visible.copy(), filepath, atributo_hilo='_export_cm_thread', titulo="Casos CM pendientes")

    def _on_accion_cm_confirmar_baja_clicked(self):
        """Confirma la baja del CM de TODOS los casos seleccionados en
        "Gestionar CM" (selección múltiple habilitada solo en esta
        sub-pestaña, ver _toggle_acciones_rapidas_panel): ESTADO DEL CM pasa
        a 'Terminated' (sin borrar los datos del CM) y el contrato a BAJA para
        que Operaciones desconecte la unidad, para todos los
        VIN elegidos a la vez -- una sola escritura a PruebasFM (un solo
        SaveExcelThread con todos los cambios) y, si tiene éxito, una sola
        lectura/escritura de CasosBajaCM.csv (ver
        cm_bajas_service.procesar_confirmacion_baja_cm_multiple) para marcar
        todos los CASO_ID seleccionados como CONFIRMADA_BAJA. Con un único
        VIN seleccionado el resultado es idéntico al de antes (listas de un
        solo elemento)."""
        vins_ordenados, casos_por_vin = self._obtener_vins_seleccionados()
        if not vins_ordenados:
            return

        # La baja del CM no borra sus datos (quedan como historial del contrato):
        # el contrato pasa a BAJA y Operaciones desconecta la unidad.
        df_base = self.legacy.df_base
        lookup_por_vin = {}
        if not df_base.empty and 'VIN' in df_base.columns:
            df_lookup = df_base.drop_duplicates('VIN', keep='last').copy()
            df_lookup.index = df_lookup['VIN'].astype(str).str.strip().str.upper()
            lookup_por_vin = df_lookup.to_dict('index')
        cambios_por_vin = {}
        for vin in vins_ordenados:
            fila_actual = lookup_por_vin.get(str(vin).strip().upper(), {})
            nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada({
                COL_ESTADO_COMERCIAL: VALOR_ESTADO_COMERCIAL_BAJA,
                COL_ESTADO_ACTIVACION: fila_actual.get(COL_ESTADO_ACTIVACION, ''),
                COL_TIPO_FACTURACION: fila_actual.get(COL_TIPO_FACTURACION, ''),
                COL_ETAPA_GESTION: fila_actual.get(COL_ETAPA_GESTION, ''),
            })
            cambios_por_vin[vin] = {'VIN': vin, 'cambios': {
                'ESTADO DEL CM': 'Terminated',
                COL_ESTADO_COMERCIAL: VALOR_ESTADO_COMERCIAL_BAJA,
                COL_ETAPA_GESTION: nueva_etapa,
            }}
        valid = comercial_services.agregar_id_a_cambios(cambios_por_vin, df_base)
        caso_ids = []
        for vin in vins_ordenados:
            caso_id = casos_por_vin[vin].get('CASO_ID')
            if caso_id is not None and str(caso_id).strip():
                caso_ids.append(caso_id)

        dialogo = DialogoAccionCm.confirmacion(self, vins_ordenados)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return

        self.btn_accion_cm_confirmar_baja.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Confirmando la baja del CM…")
        self._confirmar_baja_cm_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._confirmar_baja_cm_thread.finished_signal.connect(
            lambda success: self._on_confirmar_baja_cm_finished(success, valid, caso_ids)
        )
        self._confirmar_baja_cm_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._confirmar_baja_cm_thread.start()

    def _filas_base_por_vin(self, vins):
        """Contratos actuales (df_base) de los VIN indicados."""
        df = self.legacy.df_base
        if df is None or df.empty or 'VIN' not in df.columns or not vins:
            return pd.DataFrame()
        claves = {str(v).strip().upper() for v in vins}
        return df[df['VIN'].astype(str).str.strip().str.upper().isin(claves)]

    @staticmethod
    def _cambios_pasar_a_cm_de_filas(filas):
        """{VIN: cambios} de los contratos cuyo tipo de CM pide otra forma de contrato (CMG, CMB o CMS)."""
        cambios = {}
        for _, fila in filas.iterrows():
            nuevo = ct_service.cambio_opcional_a_cm(fila.get('TIPO DE CM', ''), fila.get(COL_FORMA_CONTRATO, ''))
            if nuevo:
                cambios[str(fila['VIN']).strip().upper()] = nuevo
        return cambios

    def _confirmar_accion_cm(self, titulo, icono, subtitulo, descripcion, lineas):
        dialogo = DialogoAccion(
            self, f" {titulo}", icon_name=icono, icon_color=PRIMARY, icon_bg_color="#EFF6FF",
            titulo=titulo, subtitulo=subtitulo, descripcion=descripcion, items=lineas, titulo_items="Cambios",
            botones=[{'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                     {'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}])
        return dialogo.exec() == QDialog.DialogCode.Accepted

    def _guardar_cambios_oportunidades_cm(self, cambios, texto, mensaje_error, contratos_nuevos=None):
        valid = comercial_services.agregar_id_a_cambios(cambios, self.legacy.df_base)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, texto)
        self._cambios_cm_thread = SaveExcelThread(
            self.legacy.writer, valid, module_name="Comercial", contratos_nuevos=contratos_nuevos)
        self._cambios_cm_thread.finished_signal.connect(
            lambda success: self._on_cambios_oportunidades_cm_finished(success, valid, mensaje_error, contratos_nuevos))
        self._cambios_cm_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._cambios_cm_thread.start()

    def _on_cambios_oportunidades_cm_finished(self, success, valid, mensaje_error, contratos_nuevos=None):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(self, mensaje_error).exec()
            return
        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master.copy(), valid)
            for registro in contratos_nuevos or []:
                dm.df_master = comercial_services.agregar_fila(dm.df_master, registro)
            dm.data_ready.emit()
        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _on_accion_cm_pasar_a_cm_clicked(self):
        """"Pasar a CM": los contratos seleccionados cuyo tipo de CM es Gold, Blue o Silver pasan a la forma de
        contrato CMG, CMB o CMS y a facturación CM (misma regla y resumen que en Contratos (CM))."""
        vins, _ = self._obtener_vins_seleccionados()
        filas_base = self._filas_base_por_vin(vins)
        cambios_por_vin = self._cambios_pasar_a_cm_de_filas(filas_base)
        if not cambios_por_vin:
            return
        from src.ui.contratos import ResumenPasarACM
        por_vin = {str(f['VIN']).strip().upper(): f for _, f in filas_base.iterrows()}
        siguiente_id = comercial_services.proximo_id_contrato(self.legacy.data_manager.df_master)
        vins_provision = {vin for vin in cambios_por_vin
                          if siguiente_id and ct_service.es_forma_provision(por_vin.get(vin, {}).get(COL_FORMA_CONTRATO, ''))}
        filas = []
        for vin, nuevo in cambios_por_vin.items():
            fila = por_vin.get(vin, {})
            filas.append({
                'vin': vin,
                'forma_antes': str(fila.get(COL_FORMA_CONTRATO, '-')).strip() or '-', 'forma_ahora': nuevo[COL_FORMA_CONTRATO],
                'fact_antes': str(fila.get(COL_TIPO_FACTURACION, '-')).strip() or '-', 'fact_ahora': nuevo[COL_TIPO_FACTURACION],
                'contrato_nuevo': vin in vins_provision})
        if ResumenPasarACM(self, filas).exec() != QDialog.DialogCode.Accepted:
            return
        cambios = {}
        contratos_nuevos = []
        for vin, nuevo in cambios_por_vin.items():
            fila = por_vin.get(vin, {})
            if vin in vins_provision:
                anterior, registro = ct_service.construir_renovacion_provision_a_cm(fila, nuevo, siguiente_id)
                siguiente_id = str(int(siguiente_id) + 1)
                cambios[vin] = {'VIN': vin, 'cambios': anterior}
                contratos_nuevos.append(registro)
                continue
            datos = dict(nuevo)
            etapa = DataFrameFormatter.calcular_etapa_gestion_esperada({
                COL_ESTADO_COMERCIAL: fila.get(COL_ESTADO_COMERCIAL, ''),
                COL_ESTADO_ACTIVACION: fila.get(COL_ESTADO_ACTIVACION, ''),
                COL_TIPO_FACTURACION: nuevo[COL_TIPO_FACTURACION],
                COL_ETAPA_GESTION: fila.get(COL_ETAPA_GESTION, ''),
            })
            if str(etapa).strip().upper() != str(fila.get(COL_ETAPA_GESTION, '')).strip().upper():
                datos[COL_ETAPA_GESTION] = etapa
            cambios[vin] = {'VIN': vin, 'cambios': datos}
        self._guardar_cambios_oportunidades_cm(
            cambios, "Cambiando la forma de contrato…",
            "No se pudo guardar el cambio de forma de contrato. SharePoint puede estar bloqueando el archivo. Intenta de nuevo.",
            contratos_nuevos)

    def _on_accion_cm_limpiar_clicked(self):
        """"Limpiar datos CM": deja en '-' los datos del 3PC de los contratos seleccionados que ya no son CM
        (ver contratos_service.construir_cambios_limpieza_cm). La importación mensual no los vuelve a cargar
        mientras el 3PC los traiga vencidos (contratos_service.omitir_en_importacion)."""
        vins, _ = self._obtener_vins_seleccionados()
        cambios = ct_service.construir_cambios_limpieza_cm(self._filas_base_por_vin(vins))
        if not cambios:
            return
        if not self._confirmar_accion_cm(
                "Limpiar datos CM", 'fa5s.eraser', f"{len(cambios)} contrato(s) dejan de ser CM",
                "Su forma de contrato y su facturación no son de CM, pero aún traen datos antiguos del 3PC. "
                "Mientras el 3PC los siga listando como vencidos, la importación no los vuelve a cargar.",
                [f"{len(cambios)} contrato(s) quedan sin N° de contrato 3PC, fechas, tipo, estado ni pago del CM",
                 "El último pago y su fecha se conservan", "El cambio queda en el historial"]):
            return
        self._guardar_cambios_oportunidades_cm(
            cambios, "Limpiando los datos del CM…",
            "No se pudo limpiar los datos del CM. SharePoint puede estar bloqueando el archivo. Intenta de nuevo.")

    @staticmethod
    def _vins_por_marcar_pendiente(casos_por_vin):
        """VIN de casos por contrato expirado o sin datos del 3PC que todavía no están en Pendiente."""
        return [vin for vin, fila in casos_por_vin.items()
                if str(fila.get('ORIGEN_CASO', '')).strip().upper() in (
                    cm_bajas_service.ORIGEN_CASO_ESTADO_EXPIRED, cm_bajas_service.ORIGEN_CASO_DATOS_3PC_VACIOS)
                and str(fila.get('ESTADO DEL CM', '')).strip().upper() != ESTADO_CM_PENDIENTE.upper()]

    def _on_accion_cm_marcar_pendiente_clicked(self):
        """"Marcar pendiente": los casos Expired seleccionados pasan a ESTADO
        DEL CM = Pendiente (a la espera de la respuesta de quien administra
        el CM). Siguen en "Oportunidades CM" porque Pendiente mantiene abierto
        su caso (ver constants.ESTADOS_CM_SIN_PAGO)."""
        _, casos_por_vin = self._obtener_vins_seleccionados()
        vins = self._vins_por_marcar_pendiente(casos_por_vin)
        if not vins:
            return
        valid = comercial_services.agregar_id_a_cambios(
            {vin: {'VIN': vin, 'cambios': {'ESTADO DEL CM': ESTADO_CM_PENDIENTE}} for vin in vins},
            self.legacy.df_base)

        self.btn_accion_cm_marcar_pendiente.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando como pendientes…")
        self._marcar_pendiente_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._marcar_pendiente_thread.finished_signal.connect(
            lambda success: self._on_marcar_pendiente_finished(success, valid)
        )
        self._marcar_pendiente_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._marcar_pendiente_thread.start()

    def _on_marcar_pendiente_finished(self, success, valid):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar el estado Pendiente. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master.copy(), valid)
            dm.data_ready.emit()

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)

    def _on_confirmar_baja_cm_finished(self, success, valid, caso_ids):
        QApplication.restoreOverrideCursor()
        self._actualizar_estado_acciones_rapidas()
        if not success:
            terminar_guardando(self, exito=False)
            DialogoAccionCm.error(
                self,
                "No se pudo guardar la baja del CM. SharePoint puede estar "
                "bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            df_m_copy = dm.df_master.copy()
            df_m_copy = comercial_services.aplicar_cambios_pendientes(df_m_copy, valid)
            dm.df_master = df_m_copy
            dm.data_ready.emit()

        try:
            cm_bajas_service.procesar_confirmacion_baja_cm_multiple(
                caso_ids=caso_ids,
                casos_path=config.settings.CASOS_BAJA_CM_PATH,
            )
        except Exception as e:
            logger.error(f"No se pudo confirmar la baja de los casos CM {caso_ids}: {e}", exc_info=True)

        self.legacy.df_base = comercial_services.preparar_df_base_comercial(self.legacy.data_manager.get_comercial_df())
        self._refresh_new_ui_data()
        terminar_guardando(self)
