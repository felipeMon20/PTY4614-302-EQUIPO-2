"""Ficha de la unidad seleccionada y observaciones de Comercial."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QGridLayout
from PyQt6.QtCore import Qt
from src.services import comercial_services
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.compartido.copiar import hacer_copiable, escribir_portapapeles
from src.theme.theme_manager import ThemeManager
from src.core.constants import COL_ESTADO_COMERCIAL, COL_ID, COL_TIPO_FACTURACION, COL_FORMA_CONTRATO, COL_ESTADO_ACTIVACION, COL_RAZON_SOCIAL, COL_CHASIS
from src.ui.comercial.base import SaveExcelThread
from src.ui.comercial.dialogos import DialogoAccionCm
from src.ui.comercial.base import (
    SaveExcelThread,
)
from src.ui.comercial.dialogos import (
    DialogoAccionCm,
)


class _FichaComercialMixin:
    def _build_new_ui_ficha_unidad(self):
        """Resumen de la unidad seleccionada arriba de las acciones rápidas:
        iniciales + Razón social + Chasis, y Forma de contrato, Estado
        comercial, Tipo de facturación y Estado de activación actual. Solo
        con exactamente una fila seleccionada (ver _actualizar_ficha_unidad)."""
        contenedor = QWidget()
        layout = QVBoxLayout(contenedor)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(10)

        fila_titulo = QHBoxLayout()
        fila_titulo.setContentsMargins(0, 0, 0, 0)
        titulo_ficha = self._titulo_seccion("Unidad seleccionada")
        fila_titulo.addWidget(titulo_ficha)
        fila_titulo.addStretch()
        self.btn_cerrar_panel_acciones = QPushButton()
        self.btn_cerrar_panel_acciones.setIcon(ThemeManager.icon('fa5s.times', color=estilo_com.APAGADO))
        self.btn_cerrar_panel_acciones.setFixedSize(26, 26)
        self.btn_cerrar_panel_acciones.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cerrar_panel_acciones.setToolTip("Cerrar (quita la selección)")
        self.btn_cerrar_panel_acciones.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        self.btn_cerrar_panel_acciones.clicked.connect(lambda: self.new_ui_table.clearSelection())
        fila_titulo.addWidget(self.btn_cerrar_panel_acciones)
        layout.addLayout(fila_titulo)

        vacio = QLabel("Hay unidades de distintas empresas seleccionadas: elige solo una para ver su detalle.")
        vacio.setWordWrap(True)
        vacio.setStyleSheet(estilo_com.QSS_FICHA_VACIA)
        layout.addWidget(vacio)

        detalle = QWidget()
        detalle_layout = QVBoxLayout(detalle)
        detalle_layout.setContentsMargins(0, 0, 0, 0)
        detalle_layout.setSpacing(8)

        hero = QFrame()
        hero.setObjectName("fichaHeroComercial")
        hero.setStyleSheet(estilo_com.QSS_FICHA_HERO)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(12, 12, 12, 12)
        hero_layout.setSpacing(12)
        avatar = QLabel("--")
        avatar.setFixedSize(46, 46)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(estilo_com.QSS_FICHA_AVATAR)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        nombre = QLabel("")
        nombre.setWordWrap(True)
        nombre.setStyleSheet(estilo_com.QSS_FICHA_NOMBRE)
        hacer_copiable(nombre)
        textos.addWidget(nombre)
        copiables = {}
        for prefijo, columna in (("Chasis", COL_CHASIS), ("RUT", 'RUT'), ("N° contrato", COL_ID), ("VIN", 'VIN')):
            fila_copiable, lbl_copiable = self._fila_copiable_ficha(prefijo)
            textos.addLayout(fila_copiable)
            copiables[columna] = lbl_copiable
        hero_layout.addWidget(avatar)
        hero_layout.addLayout(textos, stretch=1)
        detalle_layout.addWidget(hero)

        alerta_cdb = QLabel("")
        alerta_cdb.setWordWrap(True)
        alerta_cdb.setStyleSheet(
            f"background-color: {estilo_com.ROJO_SUAVE}; color: {estilo_com.ROJO}; border: 1px solid {estilo_com.ROJO};"
            "border-radius: 10px; padding: 8px 10px; font-size: 12px; font-weight: bold;")
        alerta_cdb.hide()
        detalle_layout.addWidget(alerta_cdb)

        grilla = QGridLayout()
        grilla.setSpacing(6)
        valores = {}
        for i, (columna, titulo) in enumerate((
            (COL_FORMA_CONTRATO, "Forma de contrato"), (COL_ESTADO_COMERCIAL, "Estado comercial"),
            (COL_TIPO_FACTURACION, "Tipo de facturación"), (COL_ESTADO_ACTIVACION, "Estado de activación"),
        )):
            celda, lbl_valor = estilo_com.crear_celda_ficha(titulo)
            grilla.addWidget(celda, i // 2, i % 2)
            valores[columna] = lbl_valor
        detalle_layout.addLayout(grilla)
        layout.addWidget(detalle)

        self._ficha = {
            'vacio': vacio, 'detalle': detalle, 'avatar': avatar,
            'nombre': nombre, 'copiables': copiables, 'valores': valores,
            'titulo': titulo_ficha, 'alerta_cdb': alerta_cdb,
        }
        detalle.hide()
        return contenedor

    def _fila_copiable_ficha(self, prefijo):
        """Fila 'Prefijo valor [icono]' de la ficha; un clic copia el valor."""
        fila = QHBoxLayout()
        fila.setSpacing(4)
        etiqueta = QLabel(prefijo)
        etiqueta.setStyleSheet(estilo_com.QSS_FICHA_CHASIS)
        valor = QLabel("—")
        valor.setStyleSheet(estilo_com.QSS_FICHA_CHASIS + " font-weight: bold;")
        icono = QLabel()
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.copy', color=estilo_com.APAGADO, size=11))
        icono.setStyleSheet("background: transparent; border: none;")
        # Clic en el valor, en el prefijo o en el ícono copia y avisa "Copiado"
        hacer_copiable(valor, etiqueta, icono)
        fila.addWidget(etiqueta)
        fila.addWidget(valor)
        fila.addWidget(icono)
        fila.addStretch()
        return fila, valor

    @staticmethod
    def _copiar_texto_ficha(texto):
        if texto and texto not in ("—", "-"):
            escribir_portapapeles(texto)

    def _fila_df_base_por_vin(self, vin):
        df = getattr(self.legacy, 'df_base', None)
        if not vin or df is None or df.empty or 'VIN' not in df.columns:
            return None
        pos = self._posicion_vin_en_df(df, vin)
        return None if pos is None else df.iloc[pos]

    def _posicion_vin_en_df(self, df, vin):
        """Posición de la primera fila de `df` con ese VIN. Usa un índice
        armado una vez por cada df_base (antes se recorrían ~12.000 VIN en
        cada clic); el acierto se verifica y, si falla, se recorre como antes."""
        clave = str(vin).strip().upper()
        cache = self.__dict__.get('_indice_vin_cache')
        if cache is None or cache[0] is not df or cache[1] != len(df):
            indice = {}
            for pos, v in enumerate(df['VIN'].astype(str).str.strip().str.upper().tolist()):
                indice.setdefault(v, pos)
            cache = (df, len(df), indice)
            self.__dict__['_indice_vin_cache'] = cache
        pos = cache[2].get(clave)
        col_vin = df.columns.get_loc('VIN')
        if pos is not None and str(df.iat[pos, col_vin]).strip().upper() == clave:
            return pos
        coincidencias = (df['VIN'].astype(str).str.strip().str.upper() == clave).to_numpy().nonzero()[0]
        return int(coincidencias[0]) if len(coincidencias) else None

    def _actualizar_ficha_unidad(self, vins_seleccion):
        ficha = getattr(self, '_ficha', None)
        if ficha is None:
            return
        # Una sola extracción de las filas (leerlas una por una con iloc tardaba cientos de milisegundos con muchas unidades)
        df = getattr(self.legacy, 'df_base', None)
        posiciones = []
        if vins_seleccion and df is not None and not df.empty and 'VIN' in df.columns:
            posiciones = [self._posicion_vin_en_df(df, v) for v in vins_seleccion]
            if any(p is None for p in posiciones):
                posiciones = []
        filas = df.iloc[posiciones] if posiciones else None
        columnas_texto = {}

        def textos_de(columna):
            if columna not in columnas_texto:
                if filas is None or columna not in filas.columns:
                    valores = ['-'] * (0 if filas is None else len(filas))
                else:
                    limpios = filas[columna].astype(object).where(filas[columna].notna(), '').astype(str).str.strip().tolist()
                    valores = ['-' if v.upper() in ('', 'NAN', 'NONE') else v for v in limpios]
                columnas_texto[columna] = valores
            return columnas_texto[columna]

        # Varias unidades: la ficha muestra la empresa solo si es la misma para todas
        razones = set(textos_de(COL_RAZON_SOCIAL))
        if len(razones) != 1:
            ficha['detalle'].hide()
            ficha['vacio'].show()
            ficha['titulo'].setText("Unidad seleccionada")
            self._cargar_observaciones(None, "")
            return

        multiple = len(filas) > 1

        def texto(columna):
            return textos_de(columna)[0]

        def comun(columna):
            valores = set(textos_de(columna))
            return valores.pop() if len(valores) == 1 else "Varios"

        razon_social = texto(COL_RAZON_SOCIAL)
        ficha['titulo'].setText(f"{len(filas)} unidades seleccionadas" if multiple else "Unidad seleccionada")
        ficha['avatar'].setText(estilo_com.iniciales(razon_social))
        ficha['nombre'].setText(razon_social)
        for columna, lbl in ficha['copiables'].items():
            if multiple and columna in (COL_CHASIS, COL_ID, 'VIN'):
                valor = '-'
            elif columna == 'VIN':
                valor = str(vins_seleccion[0]).strip()
            elif columna == COL_ID:
                valor = comercial_services._normalizar_id_contrato(texto(columna))
            else:
                valor = texto(columna)
            lbl.setText(valor if valor and valor != '-' else "—")
        for columna, lbl in ficha['valores'].items():
            estilo_com.pintar_chip_ficha(lbl, comun(columna) if multiple else texto(columna))

        referencia = self._cdb_referencia_actual()
        cdbs = filas['CDB'].tolist() if 'CDB' in filas.columns else [None] * len(filas)
        malas = [c for c in cdbs if comercial_services.cdb_discrepante(c, razon_social, referencia)]
        alerta = ficha['alerta_cdb']
        if malas:
            esperado = referencia.get(razon_social, '')
            if multiple:
                alerta.setText(f"⚠ {len(malas)} de {len(filas)} unidades tienen un CDB comercial distinto al de la empresa ({esperado}). "
                               "Selecciona una y usa «Editar contrato» para corregirlo.")
            else:
                actual = comercial_services.normalizar_cdb(cdbs[0]) or "vacío"
                alerta.setText(f"⚠ El CDB comercial de esta unidad ({actual}) no coincide con el de la empresa ({esperado}). "
                               "Usa «Editar contrato» para corregirlo.")
            alerta.show()
        else:
            alerta.hide()
        ficha['vacio'].hide()
        ficha['detalle'].show()

        if multiple:
            self._cargar_observaciones(None, "")
        else:
            observacion = texto('OBSERVACIONES')
            self._cargar_observaciones(vins_seleccion[0], "" if observacion == '-' else observacion)

    def _cargar_observaciones(self, vin, texto):
        """Carga en el cuadro la observación guardada de `vin` (None = sin
        unidad seleccionada: cuadro y botón deshabilitados)."""
        if not hasattr(self, 'txt_observaciones'):
            return
        if vin == self._observaciones_vin and vin is not None:
            return  # misma unidad: no se pisa lo que el usuario está escribiendo
        self._observaciones_vin = vin
        self.txt_observaciones.blockSignals(True)
        self.txt_observaciones.setPlainText(texto)
        self.txt_observaciones.blockSignals(False)
        self.txt_observaciones.setProperty('texto_guardado', texto)
        self.txt_observaciones.setEnabled(vin is not None)
        self._actualizar_boton_guardar_observaciones()

    def _actualizar_boton_guardar_observaciones(self):
        guardado = self.txt_observaciones.property('texto_guardado') or ""
        cambiado = self.txt_observaciones.toPlainText().strip() != str(guardado).strip()
        self.btn_guardar_observaciones.setEnabled(self._observaciones_vin is not None and cambiado)

    def _on_guardar_observaciones_clicked(self):
        """Guarda OBSERVACIONES de la unidad seleccionada con el mismo camino
        que las demás acciones (SaveExcelThread → ExcelWriter.update_cells,
        con backup y log)."""
        vin = self._observaciones_vin
        if not vin:
            return
        texto = self.txt_observaciones.toPlainText().strip()
        valid = comercial_services.agregar_id_a_cambios(
            {vin: {'VIN': vin, 'cambios': {'OBSERVACIONES': texto or '-'}}}, self.legacy.df_base)
        self.btn_guardar_observaciones.setEnabled(False)
        mostrar_guardando(self, "Guardando observación…")
        self._observaciones_thread = SaveExcelThread(self.legacy.writer, valid, module_name="Comercial")
        self._observaciones_thread.finished_signal.connect(
            lambda success: self._on_guardar_observaciones_finished(success, valid, vin)
        )
        self._observaciones_thread.logs_actualizados_signal.connect(self.legacy.data_manager.set_logs_df)
        self._observaciones_thread.start()

    def _on_guardar_observaciones_finished(self, success, valid, vin):
        if not success:
            terminar_guardando(self, exito=False)
            self._actualizar_boton_guardar_observaciones()
            DialogoAccionCm.error(
                self, "No se pudo guardar la observación. SharePoint puede estar bloqueando el archivo. Intenta de nuevo."
            ).exec()
            return

        guardado_listo(self)
        dm = self.legacy.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, valid)
            dm.data_ready.emit()
        self.legacy.df_base = comercial_services.preparar_df_base_comercial(dm.get_comercial_df())
        # Tras repintar la bandeja, vuelve a seleccionar la misma unidad
        self._observaciones_vin = None
        self._vin_a_reseleccionar = vin
        self._refresh_new_ui_data()
        self._reseleccionar_vin_pendiente()
        terminar_guardando(self)

    def _reseleccionar_vin_pendiente(self):
        vin = getattr(self, '_vin_a_reseleccionar', None)
        self._vin_a_reseleccionar = None
        es_revision_cm = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM
        df = getattr(self, '_new_ui_revision_cm_df' if es_revision_cm else '_new_ui_bandeja_actual_df', None)
        if not vin or df is None or df.empty or 'VIN' not in df.columns:
            return
        filas = df.reset_index(drop=True).index[df['VIN'].astype(str).str.strip().str.upper().values == vin]
        if len(filas):
            self.new_ui_table.selectRow(int(filas[0]))
