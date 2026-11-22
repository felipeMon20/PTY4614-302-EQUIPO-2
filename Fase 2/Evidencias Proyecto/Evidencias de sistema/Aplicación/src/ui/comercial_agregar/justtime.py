"""Estado y fechas de JustTime dentro del formulario de unidad."""
from datetime import datetime
import pandas as pd
from PyQt6.QtWidgets import QComboBox
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.constants import TIPO_FACTURACION_HABILITA_JUSTTIME, TIPO_FACTURACION_HABILITA_CM, JUSTTIME_ESTADO_OPCIONES, JUSTTIME_ESTADO_PENDIENTE, JUSTTIME_ESTADO_NO_APLICA, JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_ELIMINAR, JUSTTIME_ESTADO_REVISAR_PAGO
from src.ui.comercial_agregar.base import (
    _CAMPOS_BLOQUE_CM,
    _CAMPOS_BLOQUE_JUSTTIME,
    _ESTADOS_COMERCIALES_FIN,
    _ESTADOS_JT_CORREGIBLES,
)


class _JustTimeFormularioMixin:
    # ------------------------------------------------------------------
    # Pestaña "JustTime & CM": TIPO DE FACTURACION como disparador de la
    # habilitación de bloques, y mapeo FORMA DE CONTRATO -> TIPO DE CM
    # (16-09-2026)
    # ------------------------------------------------------------------
    def _actualizar_habilitacion_justtime_cm(self):
        """Habilita/deshabilita los campos de cada bloque según el valor
        REAL vigente de TIPO DE FACTURACION (self._tipo_facturacion_actual),
        usando los mismos catálogos de habilitación centralizados en
        constants.py (TIPO_FACTURACION_HABILITA_JUSTTIME/_CM) -- no se
        reimplementa la condición aquí. Deshabilitar un bloque NUNCA borra
        ni modifica el valor que ya tenga cada campo (ver conversación con
        el usuario, 16-09-2026): una unidad real con datos de CM/JustTime
        que hoy no corresponden al TIPO DE FACTURACION vigente los conserva
        intactos, solo deja de poder editarlos hasta que vuelvan a
        corresponder."""
        valor = str(self._tipo_facturacion_actual).strip().upper()
        habilita_justtime = valor in TIPO_FACTURACION_HABILITA_JUSTTIME
        habilita_cm = valor in TIPO_FACTURACION_HABILITA_CM
        for campo in _CAMPOS_BLOQUE_JUSTTIME:
            self.inputs[campo].setEnabled(habilita_justtime)
        for campo in _CAMPOS_BLOQUE_CM:
            self.inputs[campo].setEnabled(habilita_cm)
        self._set_badge_bloqueo('justtime', habilita_justtime)
        self._set_badge_bloqueo('cm', habilita_cm)
        if self._justtime_automatico():
            self._aplicar_justtime_nuevo_contrato()
        else:
            self._ajustar_justtime_manual()

    def _tipo_va_a_justtime(self):
        return str(self._tipo_facturacion_actual).strip().upper() in TIPO_FACTURACION_HABILITA_JUSTTIME

    def _poner_estado_justtime(self, estado):
        combo = self.inputs['CONTRATO CREADO EN JUSTTIME']
        combo.blockSignals(True)
        if combo.findText(estado) < 0:
            combo.addItem(estado)
        combo.setCurrentText(estado)
        combo.blockSignals(False)

    def _poner_fechas_justtime(self, inicio, termino):
        for campo, valor in (('INICIO', inicio), ('TERMINO', termino)):
            widget = self.inputs[campo]
            widget.blockSignals(True)
            widget.setText(valor or JUSTTIME_ESTADO_NO_APLICA)
            widget.blockSignals(False)

    def _ajustar_justtime_correccion(self):
        """Unidad cuyo tipo de facturación no va a JustTime pero sigue con
        estado Si, Pendiente o Revisar pago: el estado se puede corregir a lo
        que indica la matriz (Si/Revisar pago -> Eliminar, Pendiente -> "-");
        las fechas siguen bloqueadas."""
        combo = self.inputs['CONTRATO CREADO EN JUSTTIME']
        actual = combo.currentText().strip()
        original = (getattr(self, '_jt_original', None) or {}).get('estado', '')
        base = actual if actual in _ESTADOS_JT_CORREGIBLES else (original if original in _ESTADOS_JT_CORREGIBLES else '')
        if not base:
            combo.setEnabled(False)
            return
        destino = JUSTTIME_ESTADO_NO_APLICA if base == JUSTTIME_ESTADO_PENDIENTE else JUSTTIME_ESTADO_ELIMINAR
        opciones = [base, destino]
        if [combo.itemText(i) for i in range(combo.count())] != opciones:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(opciones)
            combo.setCurrentText(actual if actual in opciones else base)
            combo.blockSignals(False)
        combo.setEnabled(True)
        self._set_badge_bloqueo('justtime', True)
        for campo in ('INICIO', 'TERMINO'):
            self.inputs[campo].setEnabled(False)

    def _completar_fechas_justtime(self):
        """Inicio y término de JustTime vacíos con un estado vigente: el inicio
        es el primer día del mes de INICIO CONTRATO y el término suma la
        duración (queda vacío si el contrato es mensual)."""
        if self.inputs['CONTRATO CREADO EN JUSTTIME'].currentText().strip() not in _ESTADOS_JT_CORREGIBLES:
            return
        vacio = ('', JUSTTIME_ESTADO_NO_APLICA)
        if self.inputs['INICIO'].text().strip() not in vacio or self.inputs['TERMINO'].text().strip() not in vacio:
            return
        inicio = DataFrameFormatter.parsear_fecha_segura(self._valor_widget('INICIO CONTRATO'))
        if pd.isna(inicio):
            return
        inicio = inicio.replace(day=1)
        duracion = self._valor_widget('DURACIÓN (MESES)').strip()
        termino = ''
        if duracion.isdigit() and int(duracion) > 0:
            termino = (inicio + pd.DateOffset(months=int(duracion))).strftime("%d-%m-%Y")
        self._poner_fechas_justtime(inicio.strftime("%d-%m-%Y"), termino)

    def _reconciliar_justtime_por_tipo(self, anterior, nuevo):
        """Edición manual: al cambiar el tipo de facturación, volver al tipo
        original deja JustTime como estaba al abrir; pasar a un tipo que no va
        a JustTime lleva el estado a lo que indica la matriz."""
        if not self.modo_edicion or self._justtime_automatico():
            return
        habilita = TIPO_FACTURACION_HABILITA_JUSTTIME
        if (str(anterior).strip().upper() in habilita) == (str(nuevo).strip().upper() in habilita):
            return
        original = getattr(self, '_jt_original', None)
        if original and str(nuevo).strip().upper() == original['tipo']:
            self._poner_estado_justtime(original['estado'])
            self._poner_fechas_justtime(original['inicio'], original['termino'])
        elif str(nuevo).strip().upper() not in habilita:
            estado = self.inputs['CONTRATO CREADO EN JUSTTIME'].currentText().strip()
            if estado in (JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_REVISAR_PAGO):
                self._poner_estado_justtime(JUSTTIME_ESTADO_ELIMINAR)
            elif estado == JUSTTIME_ESTADO_PENDIENTE:
                self._poner_estado_justtime(JUSTTIME_ESTADO_NO_APLICA)
                self._poner_fechas_justtime('', '')
        self._ajustar_justtime_manual()

    def _ajustar_justtime_manual(self, *_args):
        """JustTime en edición manual: "-" (ya salió de JustTime) solo se
        ofrece si el contrato terminó y las fechas quedan siempre bloqueadas."""
        combo = self.inputs['CONTRATO CREADO EN JUSTTIME']
        if self._justtime_automatico():
            return
        if not self._tipo_va_a_justtime():
            if self.modo_edicion:
                self._ajustar_justtime_correccion()
            return
        if not combo.isEnabled():
            return
        actual = combo.currentText().strip()
        terminado = self.inputs['ESTADO COMERCIAL'].currentText().strip().upper() in _ESTADOS_COMERCIALES_FIN
        opciones = [o for o in JUSTTIME_ESTADO_OPCIONES if o != JUSTTIME_ESTADO_NO_APLICA or terminado or actual == JUSTTIME_ESTADO_NO_APLICA]
        if [combo.itemText(i) for i in range(combo.count())] != opciones:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(opciones)
            self._set_combo_valor_precargado(combo, actual)
            combo.blockSignals(False)
        for campo in ('INICIO', 'TERMINO'):
            self.inputs[campo].setEnabled(False)
        self._completar_fechas_justtime()

    def _on_justtime_elegido(self, *_args):
        """Las fechas nunca se editan a mano: elegir "-" las limpia (guardando
        las vigentes) y volver a otro estado las recupera."""
        elegido = self.inputs['CONTRATO CREADO EN JUSTTIME'].currentText().strip()
        inicio, termino = self.inputs['INICIO'], self.inputs['TERMINO']
        vacio = ('', JUSTTIME_ESTADO_NO_APLICA)
        if elegido == JUSTTIME_ESTADO_NO_APLICA:
            if inicio.text().strip() not in vacio or termino.text().strip() not in vacio:
                self._fechas_justtime_guardadas = (inicio.text(), termino.text())
            inicio.setText(JUSTTIME_ESTADO_NO_APLICA)
            termino.setText(JUSTTIME_ESTADO_NO_APLICA)
        else:
            guardadas = getattr(self, '_fechas_justtime_guardadas', None)
            if guardadas and inicio.text().strip() in vacio and termino.text().strip() in vacio:
                inicio.setText(guardadas[0])
                termino.setText(guardadas[1])
        self._ajustar_justtime_manual()

    def _justtime_automatico(self):
        """Contrato nuevo (botón Nuevo contrato, alta de unidad o unidad de
        Nuevas oportunidades sin estado de JustTime): JustTime se completa
        solo. En cualquier otra edición, o si la unidad ya trae un estado
        propio, queda manual."""
        if getattr(self, 'modo_nuevo_contrato', False):
            return True
        if self.modo_edicion:
            return getattr(self, '_jt_auto_edicion', False)
        if getattr(self, '_modo_lote', False):
            return False
        actual = self.inputs['CONTRATO CREADO EN JUSTTIME'].currentText().strip()
        return actual in ('', JUSTTIME_ESTADO_NO_APLICA, JUSTTIME_ESTADO_PENDIENTE)

    def _aplicar_justtime_nuevo_contrato(self):
        """En "Nuevo contrato", si el tipo de facturación va a JustTime
        (Cliente o Interno), el contrato nace "Pendiente" y bloqueado, el
        inicio es el primer día del mes actual y el término suma la duración
        en meses a ese día (queda vacío si el contrato es mensual). Los tres
        campos quedan bloqueados. Con otro tipo de facturación no se toca
        nada: el bloque sigue deshabilitado."""
        if str(self._tipo_facturacion_actual).strip().upper() not in TIPO_FACTURACION_HABILITA_JUSTTIME:
            return
        inicio = datetime.now().replace(day=1)
        duracion = self.inputs['DURACIÓN (MESES)'].text().strip()
        termino = ''
        if duracion.isdigit() and int(duracion) > 0:
            from dateutil.relativedelta import relativedelta
            termino = (inicio + relativedelta(months=int(duracion))).strftime("%d-%m-%Y")
        valores = {
            'CONTRATO CREADO EN JUSTTIME': JUSTTIME_ESTADO_PENDIENTE,
            'INICIO': inicio.strftime("%d-%m-%Y"),
            'TERMINO': termino,
        }
        for campo, valor in valores.items():
            widget = self.inputs[campo]
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(valor)
            else:
                widget.setText(valor)
            widget.blockSignals(False)
            widget.setEnabled(False)

    def _on_duracion_nuevo_contrato(self, _texto=''):
        if self._justtime_automatico():
            self._aplicar_justtime_nuevo_contrato()
