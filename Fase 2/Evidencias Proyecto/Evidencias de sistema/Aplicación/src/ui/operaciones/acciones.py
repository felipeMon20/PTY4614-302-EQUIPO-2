"""Acciones de Operaciones: marcar conectado, sin flota, desconectado, guardar y limpiar flota."""
from src.theme.colors import PRIMARY, TEXT_PRIMARY, TEXT_SECONDARY, WARNING
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHeaderView, QAbstractItemView, QMessageBox, QDialog, QApplication, QTableWidget, QTableWidgetItem
from PyQt6.QtCore import Qt, QDate
from src.core.constants import COL_CDB_FLOTA, COL_FLOTA_VC
from src.services import comercial_services, operaciones_services
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.ui.compartido.selector_fecha import SelectorFecha
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.operaciones.base import (
    IDX_ACTIVACIONES,
    IDX_BAJAS,
    IDX_NO_ENTREGADOS,
    IDX_SIN_FLOTA,
    MENSAJE_ERROR_GUARDADO,
    SaveExcelThread,
)


class _AccionesOperacionesMixin:
    def _confirmar_conexion(self, filas, vins, idx, pendientes):
        """Panel de confirmación de "Conectado": tabla con el CDB flota y la
        Flota VC que quedarán en cada unidad y, si hay unidades en Activación
        Pendiente sin inicio de contrato, la fecha de activación en Volvo
        Connect (será su inicio; el que ya existe se mantiene). Si alguna unidad no tiene fecha de entrega, pide también esa
        fecha (editable, hoy por defecto); si todas la tienen, no se muestra.
        Devuelve (fecha_inicio, fecha_entrega) en DD-MM-YYYY ('' si no se pidió)
        o None si se cancela."""
        n = len(vins)
        sin_entrega = [v for v in vins if operaciones_services.sin_fecha_entrega(filas[v.strip().upper()])]
        # El inicio que ya tiene un contrato se mantiene: la fecha solo se pide para los que no tienen
        sin_inicio = [v for v in pendientes if operaciones_services.sin_fecha_inicio(filas[v])]
        sin_duracion = [v for v in sin_inicio if operaciones_services.duracion_sin_dato(filas[v])]

        if sin_inicio:
            descripcion = ("La unidad estaba en Activación Pendiente y no tiene inicio de contrato. " if len(sin_inicio) == 1 else
                           f"{len(sin_inicio)} unidades estaban en Activación Pendiente y no tienen inicio de contrato. ")
            descripcion += "Indica la fecha en que se activó en Volvo Connect: será el inicio del contrato."
            if len(sin_inicio) < n:
                descripcion += " Las demás mantienen su inicio."
        else:
            descripcion = "Revisa el CDB flota y la Flota VC que quedarán en cada unidad antes de conectar."

        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        selector = None
        if sin_inicio:
            etiqueta = QLabel("Fecha de activación en Volvo Connect")
            etiqueta.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
            lay.addWidget(etiqueta)
            selector = SelectorFecha(QDate.currentDate(), QDate.currentDate())
            lay.addWidget(selector, alignment=Qt.AlignmentFlag.AlignLeft)
            if sin_duracion:
                aviso = QLabel(
                    f"{'1 unidad no tiene' if len(sin_duracion) == 1 else f'{len(sin_duracion)} unidades no tienen'} duración: "
                    "el término del contrato no se calculará hasta que Comercial la complete.")
                aviso.setWordWrap(True)
                aviso.setStyleSheet(f"color: {WARNING}; font-size: 12px; font-weight: bold;")
                lay.addWidget(aviso)
            lay.addSpacing(4)

        selector_entrega = None
        if sin_entrega:
            etiqueta_e = QLabel("Fecha de entrega del camión")
            etiqueta_e.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
            lay.addWidget(etiqueta_e)
            selector_entrega = SelectorFecha(QDate.currentDate(), QDate.currentDate())
            lay.addWidget(selector_entrega, alignment=Qt.AlignmentFlag.AlignLeft)
            if len(sin_entrega) < n:
                nota = QLabel(f"Se guarda solo en {'la unidad' if len(sin_entrega) == 1 else f'las {len(sin_entrega)} unidades'} que aún no tienen fecha de entrega.")
                nota.setWordWrap(True)
                nota.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
                lay.addWidget(nota)
            lay.addSpacing(4)

        titulo_tabla = QLabel(f"Unidades a conectar ({n})")
        titulo_tabla.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        lay.addWidget(titulo_tabla)

        tabla = QTableWidget(n, 3)
        tabla.setHorizontalHeaderLabels(["VIN", "CDB flota", "Flota VC"])
        tabla.verticalHeader().hide()
        tabla.verticalHeader().setDefaultSectionSize(32)
        tabla.setShowGrid(False)
        tabla.setAlternatingRowColors(True)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tabla.setTextElideMode(Qt.TextElideMode.ElideRight)
        tabla.setWordWrap(False)
        cab = tabla.horizontalHeader()
        cab.setHighlightSections(False)
        cab.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cab.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        cab.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        cab.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tabla.setColumnWidth(0, 175)
        tabla.setColumnWidth(1, 110)
        tabla.setStyleSheet(f"""
            QTableWidget {{ background-color: #FFFFFF; alternate-background-color: {estilo_com.FILA_ALTERNA}; border: 1px solid #E3E8F0;
                            border-radius: 10px; color: {TEXT_PRIMARY}; font-size: 12px; outline: none; }}
            QTableWidget::item {{ padding: 0 10px; border: none; }}
            QHeaderView::section {{ background-color: #F3F5F9; color: {TEXT_SECONDARY}; font-size: 11px; font-weight: bold;
                                    border: none; border-bottom: 1px solid #E3E8F0; padding: 6px 10px; text-align: left; }}
        """)
        for fila_i, v in enumerate(vins):
            cdb_v, flota_v = self._flota_efectiva(v, idx)
            for col, texto in enumerate((v.strip().upper(), cdb_v, flota_v)):
                celda = QTableWidgetItem(texto)
                celda.setToolTip(texto)
                celda.setFlags(Qt.ItemFlag.ItemIsEnabled)
                tabla.setItem(fila_i, col, celda)
        tabla.setFixedHeight(min(262, 44 + 32 * n))
        lay.addWidget(tabla)

        dialogo = DialogoAccion(
            self, " Confirmar conexión",
            icon_name="fa5s.calendar-check" if sin_inicio else "fa5s.check-circle", icon_color=PRIMARY, icon_bg_color="#DBEAFE",
            titulo="Fecha de inicio del contrato" if sin_inicio else "Confirmar conexión", subtitulo=None, descripcion=descripcion,
            botones=[{'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                     {'texto': 'Conectar', 'clase': 'primary', 'rol': 'accept'}],
            widget_extra=cuerpo, ancho=640)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        fecha_inicio = selector.date().toString("dd-MM-yyyy") if selector is not None else ''
        fecha_entrega = selector_entrega.date().toString("dd-MM-yyyy") if selector_entrega is not None else ''
        return fecha_inicio, fecha_entrega

    def _confirmar_baja(self, n):
        """Panel de confirmación de "Desconectado": pide la fecha de baja (hoy por
        defecto, puede ser pasada o futura). Devuelve DD-MM-YYYY o None si se cancela."""
        cuerpo = QWidget()
        cuerpo.setStyleSheet("background: transparent; border: none;")
        lay = QVBoxLayout(cuerpo)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        etiqueta = QLabel("Fecha de baja")
        etiqueta.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        lay.addWidget(etiqueta)
        selector = SelectorFecha(QDate.currentDate())
        lay.addWidget(selector, alignment=Qt.AlignmentFlag.AlignLeft)

        dialogo = DialogoAccion(
            self, " Confirmar baja", icon_name="fa5s.calendar-check", icon_color=PRIMARY, icon_bg_color="#DBEAFE",
            titulo="Fecha de baja", subtitulo=None,
            descripcion=(f"{'La unidad pasa' if n == 1 else f'{n} unidades pasan'} a Desconectado. "
                         "Indica la fecha de baja del contrato: puede ser anterior o posterior a hoy."),
            botones=[{'texto': 'Cancelar', 'clase': 'secondary', 'rol': 'reject'},
                     {'texto': 'Desconectar', 'clase': 'primary', 'rol': 'accept'}],
            widget_extra=cuerpo, ancho=520)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return None
        return selector.date().toString("dd-MM-yyyy")

    def _on_marcar_conectado_clicked(self):
        idx = self.subtabs.currentIndex()
        vins = self._solo_contratos_abiertos(self._get_selected_vins(), idx)
        if not vins:
            return
        sin_plan = self._vins_sin_plan(vins, idx)
        if sin_plan and self._plan_elegido() is None:
            DialogoAccion.aviso(
                self, "Faltan planes", "Elige el plan antes de marcar como CONECTADO. Faltan en estos VIN:",
                items=sin_plan, titulo_items="VIN sin plan",
            ).exec()
            return

        # CDB flota y Flota VC son obligatorios para conectar. Lo escrito en el
        # panel vale para todas las unidades seleccionadas; con un campo vacío
        # cada unidad conserva el suyo. Se valida cada VIN por separado.
        faltantes = [
            v for v in vins
            if not self._flota_efectiva(v, idx)[0]
            or self._flota_efectiva(v, idx)[1].upper() in ('', operaciones_services.FLOTA_VC_NO_EXISTE)
        ]
        if faltantes:
            DialogoAccion.aviso(
                self, "Faltan datos",
                "CDB flota y Flota VC son obligatorios antes de marcar como CONECTADO. "
                "Escríbelos en el panel (\"NO EXISTE EN VC\" no sirve para conectar). "
                "Faltan en estos VIN:",
                items=faltantes, titulo_items="VIN sin CDB flota o Flota VC",
            ).exec()
            return

        # Cada VIN recalcula su propia ETAPA GESTIÓN con la matriz de
        # negocio (ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ, ver
        # operaciones_services.calcular_cambios_marcar_conectado) en vez de
        # aplicar el mismo diccionario de cambios a todos -- alineado con
        # el riesgo detectado 24-09-2026 (ETAPA GESTIÓN transitoria e
        # inconsistente con la matriz si no se recalcula aquí).
        cola = self._cola_full.get(idx, pd.DataFrame())
        filas = {}
        for v in vins:
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == v.strip().upper()]
            filas[v.strip().upper()] = fila.iloc[0].to_dict() if not fila.empty else {}

        # Unidades en Activación Pendiente: su inicio de contrato es la fecha
        # en que se activan en Volvo Connect, que elige quien conecta.
        pendientes = [v for v, f in filas.items() if operaciones_services.es_activacion_pendiente(f)]
        fechas = self._confirmar_conexion(filas, vins, idx, pendientes)
        if fechas is None:
            return
        fecha_inicio = fechas[0] or None
        fecha_entrega = fechas[1] or None

        self._vins_en_guardado = vins
        changes = {}
        for v in vins:
            v_upper = v.strip().upper()
            fila_dict = filas[v_upper]
            cdb_v, flota_vc_v = self._flota_efectiva(v, idx)
            cambios = operaciones_services.calcular_cambios_marcar_conectado(
                fila_dict, cdb=cdb_v, flota_vc=flota_vc_v, fecha_inicio=fecha_inicio, fecha_entrega=fecha_entrega)
            changes[v_upper] = {'VIN': v.strip(), 'cambios': cambios}
        self._sumar_plan(changes, self._plan_a_guardar(vins, idx))
        comercial_services.agregar_id_a_cambios(changes, self.df_master)

        # Guardado para que _on_marcar_conectado_finished aplique en RAM
        # exactamente lo mismo que se acaba de escribir en el Excel/CSV
        # real, sin volver a leer currentIndex() (que puede haber cambiado
        # mientras el guardado estaba en curso).
        self._cambios_conectado_por_vin = changes

        self.btn_marcar_conectado.setEnabled(False)
        self.btn_marcar_conectado.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando VIN como CONECTADO…")

        self.save_thread = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread.finished_signal.connect(self._on_marcar_conectado_finished)
        self.save_thread.start()

    def _on_marcar_conectado_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_marcar_conectado.setText('Conectado')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, getattr(self, '_cambios_conectado_por_vin', {})
                )

            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_marcar_conectado.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    # ---------------------------------------------------------------
    # ACCIÓN: "Marcar como SIN FLOTA" (24-09-2026, a pedido explícito) --
    # para camiones que todavía no aparecen en Volvo Connect. Solo tiene
    # sentido en Activaciones (idx 0, ver _actualizar_estado_botones); saca
    # la unidad de Activaciones (ya no cumple ESTADO DE ACTIVACIÓN ACTUAL en
    # {Activando, No entregado}) y, según ESTADO_COMERCIAL_ACTIVACION_
    # ETAPA_MATRIZ (constants.py), pasa a la nueva pestaña "Sin Flota" si su
    # ESTADO COMERCIAL es Activación Pendiente o Vigente (las únicas dos
    # filas que la matriz manda a OPERACIONES para SIN FLOTA); si es
    # cualquier otro ESTADO COMERCIAL (Revisar/Vencido/Baja/Baja Solicitada),
    # la matriz la manda a COMERCIAL y la unidad pasa a gestionarse desde
    # ahí, no desde Operaciones -- ver calcular_cambios_marcar_sin_flota, que
    # recalcula ETAPA GESTIÓN con esa misma matriz al guardar (24-09-2026,
    # corrige un riesgo detectado el mismo día: sin este recálculo, una
    # unidad Vigente+Activando marcada Sin Flota quedaba sin cola visible en
    # ningún lado de la app). No toca ESTADO COMERCIAL, solo ESTADO DE
    # ACTIVACIÓN ACTUAL y ETAPA GESTIÓN.
    # ---------------------------------------------------------------
    def _on_marcar_sin_flota_clicked(self):
        """Desde Activaciones o desde No entregados (la entrega se hizo pero la unidad aún no aparece en Volvo Connect)."""
        idx = self.subtabs.currentIndex()
        vins = self._solo_contratos_abiertos(self._get_selected_vins(), idx)
        if not vins:
            return

        self._vins_en_guardado = vins
        # Cada VIN recalcula su propia ETAPA GESTIÓN con la matriz de
        # negocio (ver operaciones_services.calcular_cambios_marcar_sin_flota)
        # -- una unidad cuyo ESTADO COMERCIAL no da OPERACIONES para SIN
        # FLOTA (solo Activación Pendiente y Vigente lo hacen) pasa a
        # ETAPA GESTIÓN=COMERCIAL de inmediato, sin depender de la próxima
        # carga real.
        cola = self._cola_full.get(idx, pd.DataFrame())
        changes = {}
        for v in vins:
            v_upper = v.strip().upper()
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == v_upper]
            fila_dict = fila.iloc[0].to_dict() if not fila.empty else {}
            # Igual que al conectar: lo escrito en el panel, o el dato actual de cada unidad
            cdb_v, flota_vc_v = self._flota_efectiva(v, idx)
            cambios = operaciones_services.calcular_cambios_marcar_sin_flota(
                fila_dict, cdb=cdb_v, flota_vc=flota_vc_v
            )
            changes[v_upper] = {'VIN': v.strip(), 'cambios': cambios}
        self._sumar_plan(changes, self._plan_a_guardar(vins, idx))
        comercial_services.agregar_id_a_cambios(changes, self.df_master)
        self._cambios_sin_flota_por_vin = changes

        self.btn_marcar_sin_flota.setEnabled(False)
        self.btn_marcar_sin_flota.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando VIN como SIN FLOTA…")

        self.save_thread_sin_flota = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_sin_flota.finished_signal.connect(self._on_marcar_sin_flota_finished)
        self.save_thread_sin_flota.start()

    def _on_activacion_pendiente_clicked(self):
        """Sin Flota o No entregados -> Activaciones: solo las unidades cuyo estado de activación es el de esa pestaña."""
        idx = self.subtabs.currentIndex()
        esperado, nombre = ('NO ENTREGADO', 'No entregado') if idx == IDX_NO_ENTREGADOS else ('SIN FLOTA', 'Sin Flota')
        vins = self._solo_contratos_abiertos(self._get_selected_vins(), idx)
        cola = self._cola_full.get(idx, pd.DataFrame())
        changes, omitidos = {}, []
        for v in vins:
            v_upper = v.strip().upper()
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == v_upper]
            fila_dict = fila.iloc[0].to_dict() if not fila.empty else {}
            if str(fila_dict.get('ESTADO DE ACTIVACIÓN ACTUAL', '')).strip().upper() != esperado:
                omitidos.append(v_upper)
                continue
            changes[v_upper] = {'VIN': v.strip(), 'cambios': operaciones_services.calcular_cambios_activacion_pendiente(fila_dict)}
        if omitidos:
            detalle = ("(solo tienen datos de flota incompletos)" if idx == IDX_SIN_FLOTA else "")
            QMessageBox.information(
                self, "Activación Pendiente",
                f"{len(omitidos)} unidad(es) no se tocan porque su estado de activación no es {nombre} {detalle}".strip() + ".")
        if not changes:
            return
        comercial_services.agregar_id_a_cambios(changes, self.df_master)
        self._cambios_activacion_pendiente = changes
        self.btn_activacion_pendiente.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Devolviendo las unidades a Activaciones…")
        self.save_thread_activacion_pendiente = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_activacion_pendiente.finished_signal.connect(self._on_activacion_pendiente_finished)
        self.save_thread_activacion_pendiente.start()

    def _on_activacion_pendiente_finished(self, success):
        QApplication.restoreOverrideCursor()
        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, getattr(self, '_cambios_activacion_pendiente', {}))
            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_activacion_pendiente.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    def _vins_en_provisiones(self):
        """VIN que están en Provisiones: solo a ellos se les puede deshacer el envío."""
        df = getattr(self.data_manager, 'df_prov', None)
        clave = (id(df), len(df) if isinstance(df, pd.DataFrame) else 0)
        if getattr(self, '_cache_vins_prov', (None, set()))[0] != clave:
            vins = set(df['VIN'].astype(str).str.strip().str.upper()) if isinstance(df, pd.DataFrame) and 'VIN' in df.columns else set()
            self._cache_vins_prov = (clave, vins)
        return self._cache_vins_prov[1]

    def _es_envio_de_provisiones(self, fila):
        """True si el contrato actual lo envió Provisiones: tiene forma Provision y la provisión del VIN está ligada
        a ese contrato (una provisión antigua de otro contrato no cuenta; sin ID de contrato se acepta)."""
        vin = str(fila.get('VIN', '')).strip().upper()
        if vin not in self._vins_en_provisiones():
            return False
        if str(fila.get('FORMA DE CONTRATO', '')).strip().upper() != 'PROVISION':
            return False
        df = getattr(self.data_manager, 'df_prov', None)
        if isinstance(df, pd.DataFrame) and 'ID CONTRATO' in df.columns:
            ids = {comercial_services._normalizar_id_contrato(i) for i in df.loc[df['VIN'].astype(str).str.strip().str.upper() == vin, 'ID CONTRATO']}
            ids.discard('')
            actual = comercial_services._normalizar_id_contrato(fila.get('ID', ''))
            if ids and actual and actual not in ids:
                return False
        return True

    def _filas_devolvibles(self, vins):
        """[(VIN, fila)] de las unidades seleccionadas de Activaciones que están en Activación Pendiente."""
        cola = self._cola_full.get(IDX_ACTIVACIONES, pd.DataFrame())
        if cola is None or cola.empty or 'VIN' not in cola.columns:
            return []
        claves = cola['VIN'].astype(str).str.strip().str.upper()
        resultado = []
        for v in vins:
            v_upper = str(v).strip().upper()
            fila = cola[claves == v_upper]
            if fila.empty:
                continue
            fila_dict = fila.iloc[0].to_dict()
            estado = str(fila_dict.get('ESTADO COMERCIAL', '')).strip().upper().replace('Ó', 'O')
            if estado == 'ACTIVACION PENDIENTE':
                resultado.append((str(v).strip(), fila_dict))
        return resultado

    def _actualizar_boton_deshacer(self, idx, vins):
        """El botón está siempre en el panel de Activaciones y se habilita cuando hay unidades seleccionadas en Activación
        Pendiente. Dice «Deshacer envío» si todas las envió Provisiones y «Devolver a Comercial» en el resto de los casos
        (una venta, o sin selección)."""
        filas = self._filas_devolvibles(vins) if idx == IDX_ACTIVACIONES else []
        hay = bool(filas)
        todas_prov = hay and all(self._es_envio_de_provisiones(f) for _v, f in filas)
        self.btn_deshacer_envio.setText("Deshacer envío" if todas_prov else "Devolver a Comercial")
        if not hay:
            self.btn_deshacer_envio.setToolTip(
                "Selecciona unidades en Activación Pendiente para devolverlas a Nuevas oportunidades de Comercial.")
        else:
            self.btn_deshacer_envio.setToolTip(
                "La unidad vuelve a Nuevas oportunidades de Comercial y queda pendiente en Provisiones." if todas_prov else
                "La unidad vuelve a Nuevas oportunidades de Comercial, marcada como devuelta por Operaciones en Observaciones.")
        self.btn_deshacer_envio.setVisible(idx == IDX_ACTIVACIONES)
        self.btn_deshacer_envio.setEnabled(hay)
        self._reubicar_acciones()

    def _on_deshacer_envio_clicked(self):
        """Devuelve a Nuevas oportunidades de Comercial las unidades de Activaciones en Activación Pendiente
        (enviadas desde Provisiones o desde Comercial); quedan marcadas en Observaciones."""
        seleccion = self._solo_contratos_abiertos(self._get_selected_vins(), IDX_ACTIVACIONES)
        candidatas = self._filas_devolvibles(seleccion)
        cambios_por_vin, desde_prov = {}, 0
        for v, fila_dict in candidatas:
            cambios_por_vin[v.upper()] = {'VIN': v, 'cambios': operaciones_services.calcular_cambios_deshacer_envio(fila_dict)}
            desde_prov += 1 if self._es_envio_de_provisiones(fila_dict) else 0
        omitidos = [v for v in seleccion if str(v).strip().upper() not in cambios_por_vin]
        titulo = "Deshacer envío" if cambios_por_vin and desde_prov == len(cambios_por_vin) else "Devolver a Comercial"
        if not cambios_por_vin:
            QMessageBox.information(
                self, titulo, "Solo se puede devolver a Comercial una unidad que está en Activación Pendiente.")
            return
        detalle = "\n".join(f"• {v}" for v in list(cambios_por_vin)[:12]) + (
            f"\n… y {len(cambios_por_vin) - 12} más" if len(cambios_por_vin) > 12 else "")
        aviso_omitidas = f"\n\n{len(omitidos)} unidad(es) seleccionadas no se tocan porque no están en Activación Pendiente." if omitidos else ""
        aviso_prov = (f"\n\n{desde_prov} de ellas vienen de Provisiones y quedan pendientes ahí." if desde_prov else "")
        respuesta = QMessageBox.question(
            self, titulo,
            f"{len(cambios_por_vin)} unidad(es) vuelven a Nuevas oportunidades de Comercial y quedan marcadas "
            f"«{comercial_services.MARCA_DEVUELTO_OPERACIONES}» en Observaciones:"
            f"\n\n{detalle}{aviso_prov}{aviso_omitidas}\n\n¿Quieres continuar?")
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        comercial_services.agregar_id_a_cambios(cambios_por_vin, self.df_master)
        self._cambios_deshacer_por_vin = cambios_por_vin
        self.btn_deshacer_envio.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Devolviendo las unidades a Comercial…")
        self.save_thread_deshacer = SaveExcelThread(self.writer, cambios_por_vin, module_name="Operaciones")
        self.save_thread_deshacer.finished_signal.connect(self._on_deshacer_envio_finished)
        self.save_thread_deshacer.start()

    def _on_deshacer_envio_finished(self, success):
        QApplication.restoreOverrideCursor()
        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, getattr(self, '_cambios_deshacer_por_vin', {}))
            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self._actualizar_boton_deshacer(self.subtabs.currentIndex(), self._get_selected_vins())
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    def _on_marcar_sin_flota_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_marcar_sin_flota.setText('Sin flota')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, getattr(self, '_cambios_sin_flota_por_vin', {})
                )

            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_marcar_sin_flota.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    # ---------------------------------------------------------------
    # ACCIÓN: "No entregado" (04-11-2026) -- en Activaciones y en Sin flota: el camión no se
    # entregó y pasa a la pestaña No entregados. Cambia ESTADO DE ACTIVACIÓN ACTUAL
    # y recalcula ETAPA GESTIÓN con la matriz; no toca ESTADO COMERCIAL ni la flota.
    # ---------------------------------------------------------------
    def _on_marcar_no_entregado_clicked(self):
        idx = self.subtabs.currentIndex()
        vins = self._solo_contratos_abiertos(self._get_selected_vins(), idx)
        if not vins:
            return
        self._vins_en_guardado = vins
        cola = self._cola_full.get(idx, pd.DataFrame())
        changes = {}
        for v in vins:
            v_upper = v.strip().upper()
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == v_upper]
            fila_dict = fila.iloc[0].to_dict() if not fila.empty else {}
            changes[v_upper] = {'VIN': v.strip(), 'cambios': operaciones_services.calcular_cambios_marcar_no_entregado(fila_dict)}
        comercial_services.agregar_id_a_cambios(changes, self.df_master)
        self._cambios_no_entregado_por_vin = changes

        self.btn_marcar_no_entregado.setEnabled(False)
        self.btn_marcar_no_entregado.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando VIN como NO ENTREGADO…")

        self.save_thread_no_entregado = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_no_entregado.finished_signal.connect(self._on_marcar_no_entregado_finished)
        self.save_thread_no_entregado.start()

    def _on_marcar_no_entregado_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_marcar_no_entregado.setText('No entregado')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, getattr(self, '_cambios_no_entregado_por_vin', {})
                )
            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_marcar_no_entregado.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    # ---------------------------------------------------------------
    # ACCIÓN: "Guardar datos de flota" (13-10-2026) -- contratos Vigentes y
    # Conectados: se guarda lo escrito en los campos CDB flota / Flota VC del
    # panel, sin tocar estados. Con varias unidades, un campo vacío conserva
    # el valor de cada una; cada unidad debe quedar con ambos datos.
    # ---------------------------------------------------------------
    def _on_guardar_flota_clicked(self):
        vins = self._get_selected_vins()
        if not vins or not self._flota_editable(vins, self.subtabs.currentIndex()):
            return
        nueva_flota = self.txt_flota_vc.text().strip()
        nuevo_cdb = self.txt_cdb_flota.text().strip()
        cola = self._cola_full.get(self.subtabs.currentIndex(), pd.DataFrame())
        actuales = {}
        if not cola.empty:
            for _, fila in cola.iterrows():
                actuales[str(fila['VIN']).strip().upper()] = (
                    self._texto_flota_limpio(fila.get(COL_FLOTA_VC)), self._texto_flota_limpio(fila.get(COL_CDB_FLOTA)))

        changes, faltantes = {}, []
        for v in vins:
            flota_act, cdb_act = actuales.get(v.strip().upper(), ('', ''))
            flota, cdb = nueva_flota or flota_act, nuevo_cdb or cdb_act
            if not flota or not cdb:
                faltantes.append(v)
            elif (flota, cdb) != (flota_act, cdb_act):
                changes[v.strip().upper()] = {'VIN': v.strip(), 'cambios': {COL_FLOTA_VC: flota, COL_CDB_FLOTA: cdb}}
        if faltantes:
            DialogoAccion.aviso(
                self, "Faltan datos",
                "Escribe la Flota VC y el CDB flota en el panel para estos VIN:",
                items=faltantes, titulo_items="VIN sin Flota VC o CDB flota",
            ).exec()
            return
        planes = self._plan_a_guardar(vins, self.subtabs.currentIndex())
        if not changes and not planes:
            QMessageBox.information(self, "Sin cambios", "Los datos escritos son iguales a los que ya tiene la unidad.")
            return
        aviso = self._aviso_flota_distinta()
        if aviso and QMessageBox.question(
                self, "Flota VC distinta",
                f"{aviso}\n\nLa Flota VC escrita es otra. ¿Guardar de todos modos?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        flota_por_cdb = {c['cambios'][COL_CDB_FLOTA]: c['cambios'][COL_FLOTA_VC] for c in changes.values()}
        extras = operaciones_services.construir_cambios_propagar_flota(self.df_master, flota_por_cdb, changes.keys())
        if extras:
            detalle = "\n".join(f"• CDB {cdb}: {flota}" for cdb, flota in flota_por_cdb.items())
            respuesta = QMessageBox.question(
                self, "Aplicar a las demás unidades",
                f"Hay {len(extras)} unidad(es) más con el mismo CDB flota y sin Flota VC:\n{detalle}\n\n"
                "¿Completarles también esa Flota VC?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if respuesta == QMessageBox.StandardButton.Yes:
                changes.update(extras)
        self._sumar_plan(changes, planes)
        vins = [c['VIN'] for c in changes.values()]
        comercial_services.agregar_id_a_cambios(changes, self.df_master)
        self._vins_en_guardado_flota = vins
        self._cambios_en_guardado_flota = changes

        self.btn_guardar_flota.setEnabled(False)
        self.btn_guardar_flota.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Guardando datos de flota…")

        self.save_thread_flota = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_flota.finished_signal.connect(self._on_guardar_flota_finished)
        self.save_thread_flota.start()

    def _on_guardar_flota_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_guardar_flota.setText('Guardar flota')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, self._cambios_en_guardado_flota)
            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_guardar_flota.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    def _on_limpiar_flota_clicked(self):
        """"Limpiar flota" (Sin Flota): Flota VC y CDB flota quedan en "-" en
        todas las unidades seleccionadas, sin exigir que sean de la misma empresa."""
        vins = self._get_selected_vins()
        if not vins:
            return
        if QMessageBox.question(
                self, "Limpiar flota",
                f"Flota VC y CDB flota quedarán en \"-\" en {len(vins)} unidad(es). ¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        changes = {v.strip().upper(): {'VIN': v.strip(), 'cambios': {COL_FLOTA_VC: '-', COL_CDB_FLOTA: '-'}} for v in vins}
        comercial_services.agregar_id_a_cambios(changes, self.df_master)
        self._cambios_en_guardado_flota = changes

        self.btn_limpiar_flota.setEnabled(False)
        self.btn_limpiar_flota.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Limpiando datos de flota…")
        self.save_thread_flota = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_flota.finished_signal.connect(self._on_limpiar_flota_finished)
        self.save_thread_flota.start()

    def _on_limpiar_flota_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_limpiar_flota.setText('Limpiar flota')
        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, self._cambios_en_guardado_flota)
            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_limpiar_flota.setEnabled(bool(self._get_selected_vins()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()

    # ---------------------------------------------------------------
    # ACCIÓN: "Marcar como DESCONECTADO" -- cierra el ciclo de BAJA
    # (Comercial -> Operaciones -> Comercial), exclusivamente para
    # ESTADO COMERCIAL == "BAJA" (nunca BAJA SOLICITADA, ver
    # _obtener_vins_baja_seleccionados). Mismo mecanismo de guardado que
    # "Marcar como CONECTADO" (SaveExcelThread + ExcelWriter.update_cells),
    # pero a diferencia de esa acción SÍ recalcula y persiste ETAPA GESTIÓN
    # junto con ESTADO DE ACTIVACIÓN ACTUAL, reutilizando la matriz de
    # negocio existente (operaciones_services.calcular_cambios_marcar_
    # desconectado -> DataFrameFormatter.calcular_etapa_gestion_esperada) y
    # comercial_services.aplicar_cambios_pendientes para la actualización en
    # RAM (mismo helper que ya usa comercial.py, no una nueva reimplementación
    # del mask-por-VIN).
    # ---------------------------------------------------------------
    def _on_marcar_desconectado_clicked(self):
        vins = self._obtener_vins_baja_seleccionados()
        if not vins:
            return

        fecha_baja = self._confirmar_baja(len(vins))
        if fecha_baja is None:
            return

        cola = self._cola_full.get(IDX_BAJAS, pd.DataFrame())
        changes = {}
        for v in vins:
            v_upper = v.strip().upper()
            fila = cola[cola['VIN'].astype(str).str.strip().str.upper() == v_upper]
            fila_dict = fila.iloc[0].to_dict() if not fila.empty else {}
            cambios = operaciones_services.calcular_cambios_marcar_desconectado(fila_dict, fecha_baja=fecha_baja)
            changes[v_upper] = {'VIN': v.strip(), 'cambios': cambios}
        comercial_services.agregar_id_a_cambios(changes, self.df_master)

        self._vins_en_guardado_baja = vins
        self._cambios_en_guardado_baja = changes

        self.btn_marcar_desconectado.setEnabled(False)
        self.btn_marcar_desconectado.setText("  Guardando...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        mostrar_guardando(self, "Marcando VIN como DESCONECTADO…")

        self.save_thread_desconectado = SaveExcelThread(self.writer, changes, module_name="Operaciones")
        self.save_thread_desconectado.finished_signal.connect(self._on_marcar_desconectado_finished)
        self.save_thread_desconectado.start()

    def _on_marcar_desconectado_finished(self, success):
        QApplication.restoreOverrideCursor()
        self.btn_marcar_desconectado.setText('Desconectado')

        if success:
            guardado_listo(self)
            dm = self.data_manager
            if not dm.df_master.empty:
                dm.df_master = comercial_services.aplicar_cambios_pendientes(
                    dm.df_master, self._cambios_en_guardado_baja
                )

            self.load_data()
            dm.data_ready.emit()
            terminar_guardando(self)
        else:
            self.btn_marcar_desconectado.setEnabled(bool(self._obtener_vins_baja_seleccionados()))
            terminar_guardando(self, exito=False)
            DialogoAccion.error(self, MENSAJE_ERROR_GUARDADO).exec()
