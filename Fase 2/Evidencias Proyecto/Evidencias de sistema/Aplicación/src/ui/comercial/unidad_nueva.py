"""Alta, edición y renovación de unidades desde la pestaña Unidad nueva de Comercial, e importación desde Power BI."""
import pandas as pd
import qtawesome as qta
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QMessageBox, QApplication
from PyQt6.QtCore import Qt, QTimer
from src.services import comercial_services
from src.ui.comercial_agregar import ComercialUnidadFormWidget
from src.ui.ayuda.importar_powerbi import cerrar_paneles_importacion, iniciar_importacion_power_bi
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.theme.theme_manager import ThemeManager
from src.ui.comercial.base import AddRowThread, AddRowRenovacionThread, AddRowsRenovacionThread, SaveExcelThread
from src.ui.comercial.base import (
    AddRowRenovacionThread,
    AddRowThread,
    AddRowsRenovacionThread,
    AddRowsThread,
)


class _UnidadNuevaComercialMixin:
    # ---------------------------------------------------------------
    # "Unidad nueva" (25-09-2026): alta y edición de unidades centralizadas
    # en Comercial, en una pestaña principal propia -- ver comentario de
    # clase de ComercialModule. Reutiliza ComercialUnidadFormWidget
    # (comercial_agregar.py), el mismo formulario que antes vivía dentro de
    # ComercialAgregarDialog, ahora embebido en vez de modal. Una única
    # instancia persiste durante toda la vida de ComercialModule y alterna
    # entre modo "crear" (self._unidad_nueva_vin_en_edicion is None) y modo
    # "editar" (guarda el VIN y los datos originales de la unidad en
    # edición, para poder diffear contra lo que el usuario guarde).
    # ---------------------------------------------------------------
    def _build_unidad_nueva_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        # Márgenes/espaciado reducidos (25-09-2026, corrección de diseño: con
        # el formulario embebido -- que ya trae su propio encabezado + fila
        # de periodo/etapa + pestañas -- el margen de 15px/10px que usan las
        # demás pestañas de Comercial le dejaba muy poca altura disponible y
        # los campos terminaban comprimidos/superpuestos, ver también el
        # reordenamiento de secciones en comercial_agregar.py).
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(4)

        self.btn_unidad_nueva_volver = QPushButton(" Volver a la bandeja")
        self.btn_unidad_nueva_volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color=estilo_com.TINTA))
        self.btn_unidad_nueva_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unidad_nueva_volver.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {estilo_com.TINTA}; border: none; padding: 6px 4px; "
            "font-size: 13px; font-weight: 700; } QPushButton:hover { color: #1B2B4E; text-decoration: underline; }")
        self.btn_unidad_nueva_volver.clicked.connect(self._volver_a_bandeja)
        layout.addWidget(self.btn_unidad_nueva_volver, alignment=Qt.AlignmentFlag.AlignLeft)

        # El botón "Importar Excel Power BI" ya no vive en una fila propia
        # arriba del formulario -- se agrega junto a Cancelar/Guardar
        # Registro recién cuando el formulario se construye (ver
        # _asegurar_unidad_nueva_form), a pedido explícito del usuario.

        # ComercialUnidadFormWidget se construye RECIÉN al primer uso real
        # (ver _asegurar_unidad_nueva_form), no acá (25-09-2026, corrección
        # de regresión de rendimiento reportada por el usuario: construirlo
        # siempre al abrir Comercial -- con datos reales, ~1000+ opciones en
        # FLOTA VC y los lookups RUT->Razón Social/CDB de
        # _construir_lookups -- agregaba varios cientos de ms bloqueando el
        # hilo principal EN CADA primera entrada a Comercial, incluso si el
        # usuario nunca visitaba "Unidad nueva"). Solo se guarda el layout
        # donde insertarlo cuando corresponda.
        self._unidad_nueva_form_layout = layout
        self.unidad_nueva_form = None
        self._unidad_nueva_vin_en_edicion = None
        self._unidad_nueva_datos_originales = None
        self._unidad_nueva_restricciones = {}

        # Aviso de carga (25-09-2026, corrección de regresión de UX: sin esto
        # la pestaña se quedaba en blanco, congelada 1-2 segundos, mientras
        # _asegurar_unidad_nueva_form construía el formulario completo en el
        # hilo principal -- ver _on_internal_tab_changed, que ahora difiere
        # esa construcción con QTimer.singleShot(0, ...) para que Qt alcance
        # a pintar este aviso antes de bloquear). Se retira en
        # _asegurar_unidad_nueva_form apenas el formulario real está listo.
        self._unidad_nueva_loading_lbl = QLabel("Cargando formulario...")
        self._unidad_nueva_loading_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._unidad_nueva_loading_lbl.setStyleSheet(
            "font-size: 14px; color: #64748B; font-weight: bold; padding: 60px;"
        )
        layout.addWidget(self._unidad_nueva_loading_lbl)
        return tab

    def _asegurar_unidad_nueva_form(self):
        """Construye ComercialUnidadFormWidget la primera vez que realmente
        se necesita (clic en la pestaña "Unidad nueva" o en "Editar
        Unidad") -- ver comentario en _build_unidad_nueva_tab. Llamadas
        posteriores son no-op."""
        if self.unidad_nueva_form is not None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self._unidad_nueva_loading_lbl is not None:
                self._unidad_nueva_form_layout.removeWidget(self._unidad_nueva_loading_lbl)
                self._unidad_nueva_loading_lbl.deleteLater()
                self._unidad_nueva_loading_lbl = None

            # getattr con default (25-09-2026, corrección de regresión
            # detectada en test_06_construccion_no_duplica_la_carga_de_datos):
            # ese test parchea _ComercialModuleLegacy.load_data a un no-op
            # para verificar que construir ComercialModule no dispare una
            # segunda carga -- con load_data neutralizado, self.legacy.df_base
            # nunca llega a asignarse (load_data() es quien lo crea).
            # self.legacy.df_base directo funciona en la app real (load_data()
            # real ya corrió dentro de _ComercialModuleLegacy() antes de
            # llegar aquí), pero no debe asumirse en todos los escenarios.
            df_base_inicial = getattr(self.legacy, 'df_base', pd.DataFrame())
            flotas_unicas = sorted({
                v for v in df_base_inicial.get('FLOTA VC', pd.Series(dtype=str)).astype(str).str.strip()
                if v and v != 'nan'
            })
            # dropdown_options: reutiliza self.legacy.dropdown_options (el
            # catálogo de Comercial), NO el que usaba general.py
            # (DROPDOWN_OPTIONS_NUEVO_CLIENTE) -- diff hecha explícitamente
            # (25-09-2026): eran iguales salvo que a este le faltaba "Revisar"
            # en FORMA DE CONTRATO, agregado el 24-09-2026 en comercial.py como
            # corrección de negocio (ver comentario en __init__ de
            # _ComercialModuleLegacy) y nunca replicado en general.py. Con el
            # alta ahora usando el formulario COMPLETO (sin
            # restringir_alta_desde_general), esa opción faltante sí es
            # visible/relevante -- se usa el catálogo correcto en vez de
            # arrastrar el gap. DROPDOWN_OPTIONS_NUEVO_CLIENTE queda eliminado.
            self.unidad_nueva_form = ComercialUnidadFormWidget(
                flotas_unicas, self.legacy.dropdown_options, df_base_inicial, self.unidad_nueva_tab,
            )
            self.unidad_nueva_form.formulario_confirmado.connect(self._on_unidad_nueva_confirmada)
            self.unidad_nueva_form.formulario_cancelado.connect(self._on_unidad_nueva_cancelada)
            self.unidad_nueva_form.varias_unidades_confirmadas.connect(self._on_varias_unidades_confirmadas)
            self.unidad_nueva_form.nuevo_contrato_solicitado.connect(self._on_nuevo_contrato_solicitado)
            self._unidad_nueva_form_layout.addWidget(self.unidad_nueva_form, 1)

            # Botón "Restablecer" (25-09-2026, a pedido explícito: "un boton
            # que limpie la informacion como si nunca hubieran preicionado
            # el boton de Editar unidad") -- descarta cualquier cambio sin
            # guardar y vuelve a dejar el formulario tal como quedó la
            # primera vez que se entró (misma unidad recién cargada en modo
            # editar, o en blanco en modo crear). Abajo a la izquierda,
            # junto a "Importar Excel Power BI" -- ver agregar_boton_pie.
            self.btn_unidad_nueva_restablecer = QPushButton(" Restablecer")
            self.btn_unidad_nueva_restablecer.setIcon(qta.icon('fa5s.undo', color='#0F1B33'))
            self.btn_unidad_nueva_restablecer.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_unidad_nueva_restablecer.setStyleSheet(
                "QPushButton { background-color: #FFFFFF; color: #0F1B33; border: 1px solid #DCE3EC; "
                "padding: 0 16px; min-height: 40px; border-radius: 8px; font-weight: 600; font-size: 13px; } "
                "QPushButton:hover { background-color: #F1F4F9; } "
                "QPushButton:pressed { background-color: #E8ECF4; }"
            )
            self.btn_unidad_nueva_restablecer.clicked.connect(self._resetear_formulario_unidad_nueva)
            self.unidad_nueva_form.agregar_boton_pie(self.btn_unidad_nueva_restablecer)

            # Botón de importación Power BI (25-09-2026: movido desde
            # General -- mismo iniciar_importacion_power_bi, mismo
            # ComercialAgregarDialog en modo lote, solo cambia desde dónde
            # se dispara; reubicado 25-09-2026 a pedido explícito: abajo a
            # la izquierda junto al botón "Restablecer" -- ver
            # ComercialUnidadFormWidget.agregar_boton_pie -- con letra e
            # ícono blancos en vez de gris oscuro).
            self.btn_unidad_nueva_importar_powerbi = QPushButton(" Importar Excel Power BI")
            self.btn_unidad_nueva_importar_powerbi.setIcon(qta.icon('fa5s.cloud-upload-alt', color='#B7791F'))
            self.btn_unidad_nueva_importar_powerbi.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_unidad_nueva_importar_powerbi.setStyleSheet(
                "QPushButton { background-color: #FFFFFF; color: #0F1B33; border: 1px solid #DCE3EC; "
                "padding: 0 16px; min-height: 40px; border-radius: 8px; font-weight: 600; font-size: 13px; } "
                "QPushButton:hover { background-color: #F1F4F9; } "
                "QPushButton:pressed { background-color: #E8ECF4; }"
            )
            self.btn_unidad_nueva_importar_powerbi.clicked.connect(self._abrir_importar_powerbi)
            self.unidad_nueva_form.agregar_boton_pie(self.btn_unidad_nueva_importar_powerbi)
        finally:
            QApplication.restoreOverrideCursor()

    def _iniciar_edicion_multiple(self, datos_por_vin):
        """"Editar contratos" de Nuevas oportunidades: unidades sin contrato ni registro que reciben los mismos
        valores de Comercial y JustTime & CM; entran a Activación como en la edición de una sola."""
        primero = next(iter(datos_por_vin.values()))
        self._iniciar_edicion_unidad(primero, restringir_activacion=True, forzar_activacion_pendiente=True,
                                     cantidad=len(datos_por_vin))
        self._unidad_nueva_edicion_multiple = {'datos_por_vin': datos_por_vin, 'prototipo': dict(primero)}

    def _iniciar_edicion_unidad(self, datos_actuales, restringir_activacion=False,
                                 forzar_activacion_pendiente=False, restringir_vigentes=False,
                                 vin_editable=False, cantidad=1):
        """Callback de self.legacy.on_editar_unidad_solicitado (ver
        _ComercialModuleLegacy._handle_editar_unidad): reemplaza la apertura
        de ComercialAgregarDialog como ventana modal por mostrar la pestaña
        "Unidad nueva" con el formulario en modo edición, precargado con
        `datos_actuales`. Mismas restricciones que antes recibía el diálogo
        (restringir_activacion/forzar_activacion_pendiente/restringir_vigentes),
        sin cambiar su significado."""
        self._asegurar_unidad_nueva_form()
        cerrar_paneles_importacion(self.unidad_nueva_form)
        self._unidad_nueva_edicion_multiple = None
        self._unidad_nueva_vin_en_edicion = datos_actuales.get('VIN')
        self._unidad_nueva_datos_originales = datos_actuales
        # Se guardan para que "Restablecer" (ver _resetear_formulario_unidad_nueva)
        # pueda recargar exactamente el mismo modo, sin pedirlas de nuevo.
        self._unidad_nueva_restricciones = {
            'restringir_activacion': restringir_activacion,
            'forzar_activacion_pendiente': forzar_activacion_pendiente,
            'restringir_vigentes': restringir_vigentes,
            'vin_editable': vin_editable,
        }
        self.unidad_nueva_form.actualizar_datos_comercial(self.legacy.df_base)
        self.unidad_nueva_form.cargar_para_editar(
            datos_actuales,
            restringir_activacion=restringir_activacion,
            forzar_activacion_pendiente=forzar_activacion_pendiente,
            restringir_vigentes=restringir_vigentes,
            cantidad=cantidad,
        )
        # El VIN solo se corrige desde "Editar contrato" (26-10-2026); en el
        # resto de los accesos al formulario sigue bloqueado.
        self.unidad_nueva_form.inputs['VIN'].setEnabled(bool(vin_editable))
        self.tabs.setCurrentWidget(self.unidad_nueva_tab)

    def _on_nuevo_contrato_solicitado(self):
        self._iniciar_nuevo_contrato(self._unidad_nueva_datos_originales)

    def _iniciar_nuevo_contrato(self, datos_unidad, renovacion=None):
        cantidad = len((renovacion or {}).get('datos_por_vin', {})) or 1
        self._iniciar_nuevo_contrato_n(datos_unidad, renovacion, cantidad)

    def _iniciar_nuevo_contrato_n(self, datos_unidad, renovacion, cantidad):
        """Abre "Unidad nueva" en modo "Nuevo contrato" sobre una unidad cuyo
        contrato actual está cerrado. Al guardar se agrega una fila nueva con
        ID nuevo; el contrato anterior queda intacto como historial. Con
        `renovacion` ({'vin', 'id', 'cambios'}) el contrato actual sigue
        abierto y al guardar pasa a Renovado."""
        self._asegurar_unidad_nueva_form()
        self._unidad_nueva_vin_en_edicion = None
        self._unidad_nueva_datos_originales = None
        self._unidad_nueva_restricciones = {}
        self._unidad_nueva_nuevo_contrato = datos_unidad
        self._unidad_nueva_renovacion = renovacion
        self._unidad_nueva_reactivacion_multiple = None
        self.unidad_nueva_form.actualizar_datos_comercial(self.legacy.df_base)
        self.unidad_nueva_form.cargar_para_nuevo_contrato(
            datos_unidad, renovacion=renovacion is not None, cantidad=cantidad)
        self.tabs.setCurrentWidget(self.unidad_nueva_tab)

    def _iniciar_nuevo_contrato_multiple(self, datos_por_vin):
        """"Crear contratos": un contrato nuevo por cada unidad con el contrato cerrado, con las mismas
        condiciones del formulario; entran a Activación de Operaciones."""
        primero = next(iter(datos_por_vin.values()))
        self._iniciar_nuevo_contrato_n(primero, None, len(datos_por_vin))
        self._unidad_nueva_reactivacion_multiple = {'datos_por_vin': datos_por_vin, 'prototipo': dict(primero)}

    def _resetear_formulario_unidad_nueva(self):
        """Botón "Restablecer" (ver _asegurar_unidad_nueva_form; aclarado
        25-09-2026: "Cancelar" ya limpia los datos -- "Restablecer" es para
        recuperar el dato original de un VIN buscado). En modo editar,
        vuelve a cargar la misma unidad desde los datos originales con las
        mismas restricciones (incluido el VIN bloqueado), descartando
        cualquier cambio sin guardar; en modo crear no hay dato original que
        recuperar, así que simplemente deja el formulario en blanco."""
        if getattr(self, '_unidad_nueva_edicion_multiple', None):
            self._iniciar_edicion_multiple(self._unidad_nueva_edicion_multiple['datos_por_vin'])
        elif self._unidad_nueva_datos_originales is not None:
            self._iniciar_edicion_unidad(self._unidad_nueva_datos_originales, **self._unidad_nueva_restricciones)
        elif getattr(self, '_unidad_nueva_reactivacion_multiple', None):
            self._iniciar_nuevo_contrato_multiple(self._unidad_nueva_reactivacion_multiple['datos_por_vin'])
        elif getattr(self, '_unidad_nueva_nuevo_contrato', None) is not None:
            self._iniciar_nuevo_contrato(self._unidad_nueva_nuevo_contrato,
                                         renovacion=getattr(self, '_unidad_nueva_renovacion', None))
        else:
            self._entrar_modo_crear_unidad()

    def _entrar_modo_crear_unidad(self):
        """Deja "Unidad nueva" lista para dar de alta la siguiente unidad:
        se llama al cancelar el formulario y después de guardar (alta o
        edición) exitosamente -- nunca cierra la pestaña (a pedido
        explícito), solo la deja en un estado coherente para una nueva
        creación.

        También es el único punto de salida real de una importación Power
        BI (lote completo o cancelado, ver _abrir_importar_powerbi /
        _on_importar_powerbi_finished), así que de paso desbloquea
        "Comercial"/"Vista Completa" si _bloquear_tabs_durante_importacion_powerbi
        las había dejado deshabilitadas -- no-op si ya estaban habilitadas."""
        cerrar_paneles_importacion(self.unidad_nueva_form)
        self._unidad_nueva_vin_en_edicion = None
        self._unidad_nueva_datos_originales = None
        self._unidad_nueva_restricciones = {}
        self._unidad_nueva_nuevo_contrato = None
        self._unidad_nueva_renovacion = None
        self._unidad_nueva_reactivacion_multiple = None
        self._unidad_nueva_edicion_multiple = None
        self.unidad_nueva_form.actualizar_datos_comercial(self.legacy.df_base)
        self.unidad_nueva_form.resetear_para_crear()
        for widget in (self.new_ui_tab,):
            idx = self.tabs.indexOf(widget)
            self.tabs.setTabEnabled(idx, True)
            self.tabs.setTabToolTip(idx, "")
        self._sincronizar_selector_pestanas()

    def _on_crear_nueva_unidad_clicked(self):
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.unidad_nueva_tab))
        if self._unidad_nueva_vin_en_edicion is not None or getattr(self, '_unidad_nueva_nuevo_contrato', None) is not None:
            self._entrar_modo_crear_unidad()

    def _volver_a_bandeja(self):
        if self.unidad_nueva_form is not None:
            cerrar_paneles_importacion(self.unidad_nueva_form)
        self.tabs.setCurrentIndex(self.tabs.indexOf(self.new_ui_tab))

    def _on_unidad_nueva_cancelada(self):
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _on_edicion_unidad_guardada(self, vin_final, cambios):
        """Callback de self.legacy.on_edicion_unidad_guardada (ver
        _ComercialModuleLegacy._on_editar_unidad_finished): se dispara solo
        tras un guardado exitoso, ya con dm.df_master actualizado y el
        QMessageBox de confirmación ya mostrado por self.legacy."""
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _on_unidad_nueva_confirmada(self, data):
        """Slot de ComercialUnidadFormWidget.formulario_confirmado: `data`
        es el dict que antes devolvía dialog.get_data(). Modo crear ->
        AddRowThread/comercial_services.agregar_fila (mismo flujo que tenía
        general.py._open_add_dialog/_on_add_finished, movido aquí). Modo
        editar -> diff contra self._unidad_nueva_datos_originales y
        self.legacy.guardar_edicion_unidad (mismo SaveExcelThread de
        siempre)."""
        if self._unidad_nueva_vin_en_edicion is None:
            id_nuevo = comercial_services.proximo_id_contrato(self.legacy.data_manager.df_master)
            if id_nuevo:
                data = {**data, 'ID': id_nuevo}
            reactivacion = getattr(self, '_unidad_nueva_reactivacion_multiple', None)
            if reactivacion:
                self._guardar_nuevos_contratos_multiples(data, reactivacion)
                return
            renovacion = getattr(self, '_unidad_nueva_renovacion', None)
            if renovacion and renovacion.get('datos_por_vin'):
                self._guardar_renovacion_multiple(data, renovacion)
                return
            if renovacion:
                self.unidad_nueva_form.setEnabled(False)
                mostrar_guardando(self, "Guardando el contrato nuevo…")
                self._renovacion_thread = AddRowRenovacionThread(
                    self.legacy.writer, data, renovacion['vin'], renovacion['id'], renovacion['cambios'],
                    module_name="Comercial")
                self._renovacion_thread.finished_signal.connect(self._on_renovacion_finished)
                self._renovacion_thread.start()
                return
            self.unidad_nueva_form.setEnabled(False)
            mostrar_guardando(self, "Agregando la unidad nueva…")
            self._add_unidad_thread = AddRowThread(self.legacy.writer, data, module_name="Comercial")
            self._add_unidad_thread.finished_signal.connect(self._on_unidad_nueva_creada_finished)
            self._add_unidad_thread.start()
            return

        edicion_multiple = getattr(self, '_unidad_nueva_edicion_multiple', None)
        if edicion_multiple:
            self._guardar_edicion_multiple(data, edicion_multiple)
            return

        vin = self._unidad_nueva_vin_en_edicion
        datos_originales = self._unidad_nueva_datos_originales or {}
        cambios = {
            campo: valor for campo, valor in data.items()
            if str(datos_originales.get(campo, '')).strip() != str(valor).strip()
        }
        if not cambios:
            QMessageBox.information(self, "Sin cambios", "No se modificó ningún campo.")
            return
        if 'VIN' in cambios and not self._confirmar_cambio_vin(vin, cambios['VIN']):
            return
        self.legacy.guardar_edicion_unidad(vin, cambios)

    def _guardar_edicion_multiple(self, data, edicion):
        """Mismos valores de Comercial y JustTime & CM para todas las unidades seleccionadas."""
        por_vin = comercial_services.calcular_cambios_edicion_multiple(
            data, edicion['datos_por_vin'], edicion['prototipo'])
        if not por_vin:
            QMessageBox.information(self, "Sin cambios", "No se modificó ningún campo.")
            return
        cambios = comercial_services.agregar_id_a_cambios(
            {vin: {'VIN': vin, 'cambios': c} for vin, c in por_vin.items()}, self.legacy.df_base)
        self.unidad_nueva_form.setEnabled(False)
        mostrar_guardando(self, f"Guardando {len(cambios)} contratos…")
        self._editar_multiple_thread = SaveExcelThread(self.legacy.writer, cambios, module_name="Comercial")
        self._editar_multiple_thread.finished_signal.connect(
            lambda ok, c=cambios: self._on_edicion_multiple_finished(ok, c))
        self._editar_multiple_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._editar_multiple_thread.start()

    def _on_edicion_multiple_finished(self, success, cambios):
        self.unidad_nueva_form.setEnabled(True)
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.critical(self, "Error", "No se pudieron guardar los cambios de los contratos. No se cambió nada.")
            return
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, cambios)
            dm.data_ready.emit()
        terminar_guardando(self, texto_exito=f"{len(cambios)} contratos actualizados")
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _confirmar_cambio_vin(self, vin_anterior, vin_nuevo):
        anteriores = comercial_services.contratos_anteriores(self.legacy.df_base, vin_anterior)
        texto = f"Vas a cambiar el VIN de este contrato:\n\n{vin_anterior}  →  {str(vin_nuevo).strip().upper()}"
        if not anteriores.empty:
            texto += (f"\n\nLa unidad tiene {len(anteriores)} contrato(s) anterior(es) que conservarán el VIN "
                      f"{vin_anterior} y dejarán de asociarse a este contrato.")
        respuesta = QMessageBox.question(
            self, "Confirmar cambio de VIN", texto,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return respuesta == QMessageBox.StandardButton.Yes

    def _guardar_renovacion_multiple(self, data, renovacion):
        """Un contrato nuevo por cada unidad seleccionada, con las condiciones del formulario."""
        renovaciones = comercial_services.armar_renovaciones_multiples(
            data, renovacion['datos_por_vin'], renovacion['prototipo'], data.get('ID', ''))
        self.unidad_nueva_form.setEnabled(False)
        mostrar_guardando(self, f"Renovando {len(renovaciones)} contratos…")
        self._renovacion_multiple_thread = AddRowsRenovacionThread(self.legacy.writer, renovaciones, module_name="Comercial")
        self._renovacion_multiple_thread.finished_signal.connect(self._on_renovacion_multiple_finished)
        self._renovacion_multiple_thread.start()

    def _guardar_nuevos_contratos_multiples(self, data, reactivacion):
        """Un contrato nuevo por cada unidad seleccionada, con las condiciones del formulario."""
        contratos = comercial_services.armar_contratos_nuevos_multiples(
            data, reactivacion['datos_por_vin'], reactivacion['prototipo'], data.get('ID', ''))
        self.unidad_nueva_form.setEnabled(False)
        mostrar_guardando(self, f"Creando {len(contratos)} contratos…")
        self._renovacion_multiple_thread = AddRowsRenovacionThread(self.legacy.writer, contratos, module_name="Comercial")
        self._renovacion_multiple_thread.finished_signal.connect(self._on_renovacion_multiple_finished)
        self._renovacion_multiple_thread.start()

    def _on_renovacion_multiple_finished(self, hechos, total):
        self.unidad_nueva_form.setEnabled(True)
        es_reactivacion = bool(getattr(self, '_unidad_nueva_reactivacion_multiple', None))
        dm = self.legacy.data_manager
        if hechos and not dm.df_master.empty:
            for r in hechos:
                dm.df_master = comercial_services.agregar_fila(dm.df_master, r['nuevo'])
                if r['anterior_ok'] and r['id_anterior'] and r['cambios_anterior']:
                    dm.df_master = comercial_services.aplicar_cambios_pendientes(
                        dm.df_master, {r['vin']: {'VIN': r['vin'], 'ID': r['id_anterior'], 'cambios': r['cambios_anterior']}})
            dm.data_ready.emit()
        sin_anterior = [r['vin'] for r in hechos if not r['anterior_ok']]
        if len(hechos) == total:
            terminar_guardando(self, texto_exito=f"{total} contratos {'creados' if es_reactivacion else 'renovados'}")
        else:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(
                self, "Creación incompleta" if es_reactivacion else "Renovación incompleta",
                f"Se {'crearon' if es_reactivacion else 'renovaron'} {len(hechos)} de {total} contratos. El resto no se pudo "
                "guardar (SharePoint puede estar bloqueando el archivo): vuelve a seleccionarlos y repite la acción.")
        if sin_anterior:
            QMessageBox.warning(
                self, "Contrato anterior sin actualizar",
                "Se crearon los contratos nuevos, pero no se pudo marcar como Renovado el contrato anterior de: "
                + ", ".join(sin_anterior) + ".\nComo el nuevo tiene un N° Contrato mayor ya es el vigente; avisa para corregirlo.")
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _on_renovacion_finished(self, agregado, anterior_actualizado, new_data):
        self.unidad_nueva_form.setEnabled(True)
        if not agregado:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se pudo guardar el contrato nuevo. No se cambió nada. Intenta de nuevo.")
            return
        renovacion = getattr(self, '_unidad_nueva_renovacion', None) or {}
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.agregar_fila(dm.df_master, new_data)
            if anterior_actualizado and renovacion.get('id'):
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, {renovacion['vin']: {'VIN': renovacion['vin'], 'ID': renovacion['id'],
                                                      'cambios': renovacion['cambios']}})
            dm.data_ready.emit()
        terminar_guardando(self, texto_exito="Contrato nuevo creado")
        if not anterior_actualizado:
            QMessageBox.warning(
                self, "Contrato anterior sin actualizar",
                "El contrato nuevo se guardó, pero no se pudo marcar el anterior como Renovado. "
                "Como el nuevo tiene un N° Contrato mayor ya es el vigente; avisa para corregir el estado del anterior.")
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _on_unidad_nueva_creada_finished(self, success, new_data):
        self.unidad_nueva_form.setEnabled(True)
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(self, "Error", "No se pudo agregar el registro en SharePoint. Intenta de nuevo.")
            return
        guardado_listo(self, "Unidad agregada")
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.agregar_fila(dm.df_master, new_data)
            dm.data_ready.emit()
        terminar_guardando(self, texto_exito="Unidad agregada")
        n_contrato = f" (N° Contrato {new_data['ID']})" if new_data.get('ID') else ""
        self._entrar_modo_crear_unidad()
        self._volver_a_bandeja()

    def _on_varias_unidades_confirmadas(self, unidades):
        """Alta de varias unidades con los mismos datos: IDs consecutivos y un solo guardado."""
        inicial = comercial_services.proximo_id_contrato(self.legacy.data_manager.df_master)
        if inicial.isdigit():
            for i, unidad in enumerate(unidades):
                unidad['ID'] = str(int(inicial) + i)
        self.unidad_nueva_form.setEnabled(False)
        mostrar_guardando(self, f"Agregando {len(unidades)} unidades nuevas…")
        self._add_varias_thread = AddRowsThread(self.legacy.writer, unidades, module_name="Comercial")
        self._add_varias_thread.finished_signal.connect(self._on_varias_unidades_creadas)
        self._add_varias_thread.start()

    def _on_varias_unidades_creadas(self, success, unidades):
        self.unidad_nueva_form.setEnabled(True)
        if not success:
            terminar_guardando(self, exito=False)
            QMessageBox.warning(
                self, "Error",
                "No se pudieron agregar las unidades en SharePoint. No se guardó ninguna. Intenta de nuevo.")
            return
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            for unidad in unidades:
                dm.df_master = comercial_services.agregar_fila(dm.df_master, unidad)
            dm.data_ready.emit()
        terminar_guardando(self, texto_exito=f"{len(unidades)} unidades agregadas")
        self._entrar_modo_crear_unidad()
        self.new_ui_subtabs.setCurrentIndex(2)
        self._volver_a_bandeja()

    def _abrir_importar_powerbi(self):
        # Ya no abre una ventana modal aparte (25-09-2026, corrección a
        # pedido explícito: "me abre una pestaña en vez de rellenar el
        # formulario que ya tengo al frente") -- reutiliza self.unidad_nueva_form,
        # la misma instancia embebida en "Unidad nueva" (ver
        # ComercialUnidadFormWidget.iniciar_lote en comercial_agregar.py).
        # El botón se deshabilita/rehabilita adentro de
        # iniciar_importacion_power_bi según el estado real del lote (no con
        # un try/finally acá: el flujo ahora es asíncrono via señales, no un
        # exec() bloqueante).
        flotas_existentes = (
            self.legacy.df_base['FLOTA VC'].dropna().unique().tolist()
            if 'FLOTA VC' in self.legacy.df_base.columns else []
        )
        iniciar_importacion_power_bi(
            self, self.unidad_nueva_form, self.btn_unidad_nueva_importar_powerbi,
            flotas_existentes, self.legacy.dropdown_options, self.legacy.df_base,
            self.legacy.writer, self._on_importar_powerbi_finished, self._entrar_modo_crear_unidad,
            on_lote_iniciado=self._bloquear_tabs_durante_importacion_powerbi,
        )

    def _bloquear_tabs_durante_importacion_powerbi(self):
        """Bloquea "Comercial" y "Vista Completa" mientras dura una
        importación de Power BI (25-09-2026, a pedido explícito: bug real
        reportado por el usuario -- cambiar a "Comercial" y usar "Editar
        Unidad" a mitad de una importación sobrescribía, sin aviso, la
        unidad que el lote estaba completando, además de dejar pegados en
        pantalla el badge de chasis y el contador de progreso). Con las
        pestañas bloqueadas, la única salida es terminar el lote completo o
        cancelarlo -- ver _entrar_modo_crear_unidad, que las desbloquea."""
        tooltip = "Termina o cancela la importación de Power BI en curso para volver aquí."
        for widget in (self.new_ui_tab,):
            idx = self.tabs.indexOf(widget)
            self.tabs.setTabEnabled(idx, False)
            self.tabs.setTabToolTip(idx, tooltip)
        self._sincronizar_selector_pestanas()

    def _sincronizar_selector_pestanas(self):
        # getattr: _entrar_modo_crear_unidad puede correr antes de crear el selector
        selector = getattr(self, 'selector_pestanas', None)
        if selector is not None:
            selector.sincronizar_estado()

    def _on_importar_powerbi_finished(self, success):
        self.unidad_nueva_form.setEnabled(True)
        self.btn_unidad_nueva_importar_powerbi.setEnabled(True)
        if success:
            n = getattr(self, '_importar_powerbi_cantidad', 0)
            QMessageBox.information(
                self, "Importación completada",
                f"Se agregaron {n} unidad(es) nueva(s). Las encuentras en \"Nuevas oportunidades\"."
            )
            self.legacy.data_manager.load_data_async()
        else:
            QMessageBox.critical(self, "Error", "No se pudo escribir el lote importado en RM_JAVI. No se realizó ningún cambio.")
        self._entrar_modo_crear_unidad()
        if success:
            self.new_ui_subtabs.setCurrentIndex(2)
            self._volver_a_bandeja()

    def _on_internal_tab_changed(self, index):
        """Replica el mismo hook que MainWindow._trigger_load_data aplica al
        navegar entre modulos (ver main_window.py), pero para el cambio de
        pestaña interno Nueva/Antigua: si la pestaña antigua quedo dirty
        mientras estaba oculta, se refresca al volver a mostrarla."""
        widget = self.tabs.widget(index)
        if widget is not self.new_ui_tab:
            self._ocultar_panel_acciones_al_instante()
        if hasattr(widget, 'refresh_if_dirty'):
            QTimer.singleShot(50, widget.refresh_if_dirty)
        elif hasattr(widget, 'load_data'):
            QTimer.singleShot(50, widget.load_data)

        # La Nueva interfaz no tiene carga propia: al volver a ella, solo
        # se repinta con los datos que _ComercialModuleLegacy ya tiene en
        # memoria (self.legacy.df_base), sin volver a pedirle nada a
        # DataManager.
        if widget is self.new_ui_tab:
            self._refresh_new_ui_data()

        # "Unidad nueva": primer clic real en la pestaña -- construye el
        # formulario recién ahora (ver _asegurar_unidad_nueva_form). Se
        # difiere con QTimer.singleShot(0, ...) (25-09-2026, corrección de
        # regresión de UX reportada por el usuario: el cambio de pestaña
        # tardaba 1-2 segundos en verse porque _asegurar_unidad_nueva_form
        # -con datos reales, ~1000+ opciones en FLOTA VC y los lookups
        # RUT->Razón Social/CDB- corre sincrónico DENTRO del propio
        # currentChanged, bloqueando el hilo principal antes de que Qt
        # alcance a pintar la pestaña ya seleccionada) -- mismo patrón que
        # _cargar_vista_general_inicial en main_window.py: se vuelve del
        # todo al event loop primero, así la pestaña ya cambiada y su aviso
        # "Cargando formulario..." (ver _build_unidad_nueva_tab) se pintan
        # de inmediato, y la construcción pesada sigue en la siguiente
        # vuelta del loop en vez de tapar la transición.
        if widget is self.unidad_nueva_tab and self.unidad_nueva_form is None:
            QTimer.singleShot(0, self._construir_unidad_nueva_form_diferido)

    def _construir_unidad_nueva_form_diferido(self):
        """Ver _on_internal_tab_changed: paso 2 (diferido) de la primera
        entrada a "Unidad nueva". No-op si el usuario ya cambió de pestaña
        de nuevo antes de que corriera (self.unidad_nueva_form seguiría
        None, pero _asegurar_unidad_nueva_form igual lo construye -- queda
        listo para la próxima vez que se seleccione la pestaña)."""
        ya_existia = self.unidad_nueva_form is not None
        self._asegurar_unidad_nueva_form()
        if not ya_existia:
            self._entrar_modo_crear_unidad()
