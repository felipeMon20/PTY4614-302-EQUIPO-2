"""Autocompletados y cálculos de fechas, chasis, modelo, VIN y pago CM del formulario de unidad."""
from datetime import datetime
from PyQt6.QtWidgets import QComboBox
from src.services.vin_service import obtener_modelo_desde_vin
from src.services import catalogos_service, comercial_services
from src.theme.colors import DANGER
from src.core.constants import TIPO_FACTURACION_DISPLAY_A_REAL, FORMA_CONTRATO_TIPO_CM_MAP


class _CalculosFormularioMixin:
    def _autocompletar_tipo_cm(self):
        """FORMA DE CONTRATO -> TIPO DE CM, vía el único mapa centralizado
        FORMA_CONTRATO_TIPO_CM_MAP (constants.py, Fase 0): no se reimplementa
        la relación CMG/CMB/CMS -> Gold/Blue/Silver aquí. No hace nada si el
        usuario ya eligió TIPO DE CM manualmente (ver
        _on_tipo_cm_editado_manualmente), ni si FORMA DE CONTRATO no
        corresponde a ninguno de los 3 códigos de mantenimiento (en ese caso
        el bloque completo ya quedó en '-' vía
        _sincronizar_tipo_facturacion_con_forma_contrato, así que tampoco
        hay nada que autocompletar)."""
        if self._tipo_cm_manual:
            return
        forma = self.inputs['FORMA DE CONTRATO'].currentText().strip().upper()
        tipo_cm = FORMA_CONTRATO_TIPO_CM_MAP.get(forma)
        if tipo_cm:
            self.inputs['TIPO DE CM'].setCurrentText(tipo_cm)

    def _on_tipo_cm_editado_manualmente(self, index):
        """Se dispara solo cuando el usuario elige TIPO DE CM con el
        mouse/teclado (señal `activated`, mismo patrón que MODELO/ETAPA
        GESTIÓN): a partir de aquí, el autocompletado por FORMA DE CONTRATO
        deja de pisar la elección."""
        self._tipo_cm_manual = True

    # ------------------------------------------------------------------
    # Validación en vivo de VIN duplicado (edición y alta)
    # ------------------------------------------------------------------
    def _vin_duplicado(self, vin_upper):
        """True si `vin_upper` (ya en mayúsculas/strip) ya existe en Comercial
        en OTRA unidad, o ya fue confirmado en un registro anterior de este
        mismo lote de importación Power BI (ver _vins_usados_en_lote /
        _avanzar_lote). El VIN original de la unidad en edición se considera
        válido contra sí mismo."""
        if not vin_upper:
            return False
        if self.modo_edicion and vin_upper == self._vin_original:
            return False
        if self.modo_renovacion:
            return False
        if self.modo_nuevo_contrato:
            return vin_upper in self._vins_con_contrato_abierto
        return vin_upper in self._vins_existentes or vin_upper in self._vins_usados_en_lote

    def _validar_vin_duplicado(self):
        """Marca el campo VIN en rojo y deshabilita Guardar si el VIN ya
        pertenece a otra unidad -- sin QMessageBox ni popups, para no
        interrumpir mientras el usuario escribe o pega el VIN (tanto tecleo
        como Ctrl+V disparan textChanged)."""
        if self._modo_varias:
            return
        vin_upper = self.inputs['VIN'].text().strip().upper()
        widget = self.inputs['VIN']
        if self._vin_duplicado(vin_upper):
            widget.setStyleSheet("border: 1px solid #EF4444; background-color: #FEF2F2;")
            widget.setToolTip(
                "Esta unidad no admite otro contrato: el actual no está en baja o la unidad sigue Activando o Conectada."
                if self.modo_nuevo_contrato else "Ya existe una unidad con este VIN en Comercial.")
            self.btn_save.setEnabled(False)
        else:
            widget.setStyleSheet("")
            widget.setToolTip("")
            self.btn_save.setEnabled(not self._contrato_cerrado)

    # ------------------------------------------------------------------
    # Cálculos automáticos (idénticos a la versión anterior)
    # ------------------------------------------------------------------
    def _auto_calculate_chasis(self):
        vin_text = self.inputs['VIN'].text().strip()
        if len(vin_text) >= 7:
            self.inputs['CHASIS'].setText(vin_text[-7:])
        else:
            self.inputs['CHASIS'].setText("")

    def _on_modelo_editado_manualmente(self, index):
        """Se dispara solo cuando el usuario elige un valor del combo MODELO
        con el mouse/teclado (señal `activated`, no `currentTextChanged`):
        a partir de aquí, cambiar el VIN ya no vuelve a pisar la elección."""
        self._modelo_manual = True

    def _auto_calculate_modelo(self):
        """Autocompleta MODELO a partir del VIN (ver src/services/vin_service.py:
        solo la posicion 4, y 5-7 para la variante electrica). El combo MODELO
        no es editable, asi que setCurrentText solo tiene efecto si el modelo
        deducido coincide exactamente con una de sus opciones oficiales; si el
        service no reconoce el codigo (o el VIN es muy corto), no se toca el
        campo. No hace nada si el usuario ya eligió MODELO manualmente (ver
        _on_modelo_editado_manualmente)."""
        if self._modelo_manual:
            return
        vin_text = self.inputs['VIN'].text().strip()
        modelo = obtener_modelo_desde_vin(vin_text)
        if modelo:
            self.inputs['MODELO'].setCurrentText(modelo)

    def _on_inicio_contrato_changed(self, texto):
        """Autoformatea INICIO CONTRATO mientras se escribe/pega: deja solo
        dígitos (las letras ya las bloquea el validador del campo) y va
        insertando los guiones DD-MM-YYYY solo, sin que el usuario tenga que
        tipearlos (ej. '09092026' -> '09-09-2026'). Luego dispara el mismo
        cálculo de TÉRMINO CONTRATO de siempre."""
        solo_digitos = ''.join(ch for ch in texto if ch.isdigit())[:8]
        if len(solo_digitos) > 4:
            formateado = f"{solo_digitos[:2]}-{solo_digitos[2:4]}-{solo_digitos[4:]}"
        elif len(solo_digitos) > 2:
            formateado = f"{solo_digitos[:2]}-{solo_digitos[2:]}"
        else:
            formateado = solo_digitos

        widget = self.inputs['INICIO CONTRATO']
        if formateado != texto:
            widget.blockSignals(True)
            widget.setText(formateado)
            widget.blockSignals(False)

        # Con la fecha completa (10 caracteres), valida que exista de verdad
        # en el calendario (ej. 31-02-2026 no existe) y lo marca en rojo al
        # instante, sin esperar a que se presione Guardar.
        if len(formateado) == 10:
            try:
                datetime.strptime(formateado, "%d-%m-%Y")
                widget.setStyleSheet("")
                widget.setToolTip("")
            except ValueError:
                widget.setStyleSheet("border: 1px solid #EF4444; background-color: #FEF2F2;")
                widget.setToolTip("Esa fecha no existe en el calendario (ej. 31 de febrero).")
        else:
            widget.setStyleSheet("")
            widget.setToolTip("")

        self._auto_calculate_termino()

    def _auto_calculate_termino(self):
        """Calcula matemáticamente en tiempo real la fecha de término del contrato."""
        inicio_str = self.inputs['INICIO CONTRATO'].text().strip()
        duracion_str = self.inputs['DURACIÓN (MESES)'].text().strip().upper()

        if not inicio_str:
            self.inputs['TÉRMINO CONTRATO'].setText("")
            self._actualizar_color_termino_contrato()
            return

        if duracion_str == 'MENSUAL' or duracion_str == '-':
            self.inputs['TÉRMINO CONTRATO'].setText("MENSUAL")
            self._actualizar_color_termino_contrato()
            return

        try:
            # Revisa si el usuario tipeó la fecha correcta (DD-MM-YYYY)
            fecha_inicio = datetime.strptime(inicio_str, "%d-%m-%Y")

            # Si hay un número de meses, aplica la matemática
            if duracion_str.isdigit() and int(duracion_str) > 0:
                from dateutil.relativedelta import relativedelta
                meses = int(duracion_str)
                fecha_termino = fecha_inicio + relativedelta(months=meses)
                self.inputs['TÉRMINO CONTRATO'].setText(fecha_termino.strftime("%d-%m-%Y"))
            else:
                self.inputs['TÉRMINO CONTRATO'].setText("")

        except ValueError:
            # Si la fecha no está completa aún, vacía la de término por precaución
            self.inputs['TÉRMINO CONTRATO'].setText("")

        self._actualizar_color_termino_contrato()

    def _actualizar_color_termino_contrato(self):
        """TÉRMINO CONTRATO ya vencido se resalta en rojo (25-09-2026, a
        pedido explícito: "puede haber fechas vencidas y el usuario no se
        entera"), sin importar desde qué pantalla se abrió este formulario
        -- se llama tanto al recalcular (_auto_calculate_termino) como al
        precargar una unidad existente (_aplicar_datos_iniciales). Reutiliza
        comercial_services.clasificar_fecha_termino (misma regla de
        "vencido" que ya usan los KPI de Vista Completa/Comercial: fecha de
        calendario ya pasada; MENSUAL y "-"/vacío nunca cuentan)."""
        widget = self.inputs['TÉRMINO CONTRATO']
        clasif = comercial_services.clasificar_fecha_termino(widget.text().strip())
        widget.setStyleSheet(f"color: {DANGER}; font-weight: bold;" if clasif['vencido'] else "")

    def _on_fecha_generica_widget_changed(self, texto):
        """Wrapper sin lambda para conectar textChanged a _on_fecha_generica_changed:
        identifica el campo por el emisor (self.sender()) en vez de capturarlo en un
        closure. Las lambdas que capturaban self en textChanged.connect() creaban un
        ciclo de referencia (widget hijo -> lambda -> self) que gc.collect() no lograba
        romper, dejando el diálogo y sus widgets vivos tras close()+deleteLater()."""
        sender = self.sender()
        field_name = next(nombre for nombre, widget in self.inputs.items() if widget is sender)
        self._on_fecha_generica_changed(field_name, texto)

    def _on_fecha_generica_changed(self, field_name, texto):
        """Autoformatea un campo de fecha simple (sin cálculo dependiente)
        igual que _on_inicio_contrato_changed: mismo patrón DD-MM-YYYY
        armado solo a partir de los dígitos tipeados/pegados, con una
        diferencia: "-" es un valor válido (significa "sin fecha
        registrada", no un error), así que si el texto es exactamente "-"
        se deja tal cual, sin pasarlo por el armado de dígitos (que lo
        convertiría en cadena vacía). Generalizado (16-09-2026) a partir de
        _on_fecha_baja_changed para reutilizarlo también en INICIO, TERMINO,
        FECHA INICIO CM y FECHA TERMINO CM (pestaña "JustTime & CM"), que
        tienen el mismo comportamiento y ningún campo derivado."""
        widget = self.inputs[field_name]
        if texto.strip() == '-':
            widget.setStyleSheet("")
            widget.setToolTip("")
            return

        solo_digitos = ''.join(ch for ch in texto if ch.isdigit())[:8]
        if len(solo_digitos) > 4:
            formateado = f"{solo_digitos[:2]}-{solo_digitos[2:4]}-{solo_digitos[4:]}"
        elif len(solo_digitos) > 2:
            formateado = f"{solo_digitos[:2]}-{solo_digitos[2:]}"
        else:
            formateado = solo_digitos

        if formateado != texto:
            widget.blockSignals(True)
            widget.setText(formateado)
            widget.blockSignals(False)

        if len(formateado) == 10:
            try:
                datetime.strptime(formateado, "%d-%m-%Y")
                widget.setStyleSheet("")
                widget.setToolTip("")
            except ValueError:
                widget.setStyleSheet("border: 1px solid #EF4444; background-color: #FEF2F2;")
                widget.setToolTip("Esa fecha no existe en el calendario (ej. 31 de febrero).")
        else:
            widget.setStyleSheet("")
            widget.setToolTip("")

    def _on_fecha_baja_changed(self, texto):
        """FECHA DE BAJA no tiene ningún campo derivado (a diferencia de
        INICIO CONTRATO, que recalcula TÉRMINO CONTRATO): delega en el
        formateo genérico de fechas simples."""
        self._on_fecha_generica_changed('FECHA DE BAJA', texto)

    def _on_pago_cm_changed(self, texto):
        """Autoformatea PAGO CM como moneda ("$80.000") mientras se escribe,
        mismo criterio de presentación que ya usa Contratos CM
        (contratos.py, _formatear_pago_cm_para_mostrar): "-" es un valor
        válido (sin pago registrado), no se reformatea. El valor que
        finalmente se guarda (ver _valor_widget) es siempre el número crudo
        sin símbolos, nunca este texto formateado -- PAGO CM sigue siendo
        una columna numérica en PruebasFM, esto es solo presentación."""
        widget = self.inputs['PAGO CM']
        if texto.strip() == '-':
            return
        solo_digitos = ''.join(ch for ch in texto if ch.isdigit())
        if not solo_digitos:
            return  # se deja vacío; get_data() lo normaliza a "-" al guardar
        formateado = f"${int(solo_digitos):,}".replace(",", ".")
        if formateado != texto:
            widget.blockSignals(True)
            widget.setText(formateado)
            widget.blockSignals(False)

    # ------------------------------------------------------------------
    # Validación y datos (idénticos a la versión anterior)
    # ------------------------------------------------------------------
    def _valor_widget(self, campo):
        widget = self.inputs[campo]
        if campo == 'PAGO CM':
            # El widget muestra "$80.000" (presentación); lo que se guarda
            # es siempre el número crudo sin símbolos, porque PAGO CM sigue
            # siendo una columna numérica en PruebasFM (ver contratos.py,
            # que hace lo mismo al guardar: solo formatea para mostrar).
            texto = widget.text().strip()
            if not texto or texto == '-':
                return texto
            return ''.join(ch for ch in texto if ch.isdigit())
        if campo == 'TIPO DE FACTURACION':
            # El combo muestra el texto amigable (Cliente, Provision +...);
            # lo que se guarda/valida es siempre el valor REAL (constants.py
            # TIPO_FACTURACION_DISPLAY_A_REAL), nunca el texto de presentación.
            texto_amigable = widget.currentText().strip()
            return TIPO_FACTURACION_DISPLAY_A_REAL.get(texto_amigable, texto_amigable)
        if campo == 'TIPO DE SERVICIO':
            base = widget.currentText().strip()
            if base in ('', '-'):
                return base
            return catalogos_service.armar_tipo_servicio(base, self.combo_complementos.seleccion())
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return widget.text().strip()
