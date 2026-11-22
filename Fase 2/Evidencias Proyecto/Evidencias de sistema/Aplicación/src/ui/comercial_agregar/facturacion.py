"""Tipo de facturación, bloqueos y avisos de corrección del formulario de unidad."""
from PyQt6.QtWidgets import QComboBox, QPushButton
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
import qtawesome as qta
from src.core.constants import TIPO_FACTURACION_DISPLAY_MAP, TIPO_FACTURACION_DISPLAY_A_REAL, TIPO_FACTURACION_HABILITA_JUSTTIME, TIPO_FACTURACION_HABILITA_CM, FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
from src.ui.comercial_agregar.base import (
    _CAMPOS_BLOQUE_CM,
    _CAMPOS_BLOQUE_JUSTTIME,
    _ORDEN_TIPO_FACTURACION,
    _ORDEN_TIPO_FACTURACION_SIN_GUION,
)


class _TipoFacturacionFormularioMixin:
    def _set_badge_bloqueo(self, key, habilitado):
        """Aviso visual explícito de si una sección (JustTime/CM/Operaciones)
        está bloqueada o editable (16-09-2026; rediseñado 25-09-2026 a
        pedido explícito: sin emojis -- ícono qtawesome + "pill" de color en
        vez de 🔒/🔓 como caracteres de texto). El atenuado por
        `setEnabled(False)` de Qt no bastaba para notarlo a simple vista."""
        badge = getattr(self, '_badges_bloqueo', {}).get(key)
        if badge is None:
            return
        color = '#1F7A55' if habilitado else '#66748D'
        bg = '#E7F4EE' if habilitado else '#EEF2F6'
        icono = 'fa5s.unlock' if habilitado else 'fa5s.lock'
        texto = 'Editable' if habilitado else 'Bloqueado'
        badge['icon'].setPixmap(qta.icon(icono, color=color).pixmap(11, 11))
        badge['texto'].setText(texto)
        badge['texto'].setStyleSheet(f"font-size: 11px; font-weight: 600; letter-spacing: 0; background: transparent; border: none; color: {color};")
        badge['frame'].setStyleSheet(f"QFrame#badgeBloqueo {{ background-color: {bg}; border: 1px solid #DCE3EC; border-radius: 8px; }}")
        badge['frame'].setVisible(True)

    def _tipo_facturacion_validos_actual(self):
        """Set de valores REALES de TIPO DE FACTURACION permitidos para el
        FORMA DE CONTRATO vigente, según FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
        (constants.py, matriz entregada por Javiera, 24-09-2026). None si
        FORMA DE CONTRATO no está en la matriz (valor legado/no reconocido):
        en ese caso no se restringe nada, mismo criterio que el resto de las
        matrices de negocio del sistema.

        FORMA DE CONTRATO='-' (placeholder, "todavía sin elegir") es un caso
        especial exclusivo de este diálogo (25-09-2026, a pedido explícito):
        NO se agrega a la matriz de constants.py porque esa matriz también
        alimenta detectar_inconsistencias_forma_contrato_tipo_facturacion()/
        normalizar_tipo_facturacion_por_forma_contrato() en
        comercial_services.py (auditoría de datos históricos y
        sincronización con RM_JAVI), donde FORMA DE CONTRATO='-' nunca
        debe marcarse ni tocarse. Acá, en cambio, mientras el usuario no
        elige una FORMA DE CONTRATO real, TIPO DE FACTURACION tampoco
        debería quedar editable con el catálogo completo."""
        forma = self.inputs['FORMA DE CONTRATO'].currentText().strip().upper()
        if forma == '-':
            return {'-'}
        return FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(forma)

    def _actualizar_habilitacion_tipo_facturacion(self):
        """TIPO DE FACTURACION queda bloqueado cuando FORMA DE CONTRATO solo
        admite un único valor posible en FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
        -- no hay nada que elegir (25-09-2026, a pedido explícito: "no se
        pueda modificar ya que depende de forma de contrato... algunas solo
        tiene una opcion, ahi no es necesario que se pueda modificar").
        Queda editable cuando admite más de una opción (CONVERSION/VENTA:
        Cliente o Facturación Manual) o cuando FORMA DE CONTRATO no está en
        la matriz (valor legado, sin restricción). No pisa un bloqueo ya
        aplicado por _aplicar_restriccion_alta_general -- se llama antes de
        esa restricción en _aplicar_datos_iniciales."""
        validos = self._tipo_facturacion_validos_actual()
        self.inputs['TIPO DE FACTURACION'].setEnabled(validos is None or len(validos) > 1)
        self._actualizar_alerta_tipo_facturacion()

    def _crear_boton_corregir_tipo_facturacion(self):
        btn = QPushButton()
        btn.setIcon(qta.icon('fa5s.exclamation-triangle', color='#B42318'))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setAutoDefault(False)
        btn.setStyleSheet(
            "QPushButton { background-color: #FEF2F2; color: #B42318; border: 1px solid #EF4444; border-radius: 8px;"
            " padding: 5px 10px; font-size: 12px; font-weight: 600; text-align: left; }"
            "QPushButton:hover { background-color: #FEE2E2; }")
        btn.clicked.connect(self._corregir_tipo_facturacion)
        btn.setVisible(False)
        return btn

    def _tipo_facturacion_correcto(self):
        """Valor REAL al que corresponde corregir cuando el TIPO DE FACTURACION
        cargado no cumple la matriz para la FORMA DE CONTRATO vigente; None si
        es coherente (o la forma no está en la matriz, o aún no se elige)."""
        if self.inputs['FORMA DE CONTRATO'].currentText().strip() in ('', '-'):
            return None
        validos = self._tipo_facturacion_validos_actual()
        if not validos or str(self._tipo_facturacion_actual).strip().upper() in validos:
            return None
        return next((v for v in _ORDEN_TIPO_FACTURACION if v in validos), None)

    def _actualizar_alerta_tipo_facturacion(self):
        """Marca en rojo el TIPO DE FACTURACION incoherente con la matriz y
        muestra el botón para corregirlo, solo en ese caso."""
        btn = getattr(self, '_btn_corregir_tipo_fact', None)
        if btn is None or 'TIPO DE FACTURACION' not in self.inputs:
            return
        widget = self.inputs['TIPO DE FACTURACION']
        correcto = self._tipo_facturacion_correcto()
        if correcto is None:
            if btn.isVisible() or widget.styleSheet():
                widget.setStyleSheet("")
                widget.setToolTip("")
            btn.setVisible(False)
            return
        destino = TIPO_FACTURACION_DISPLAY_MAP.get(correcto, correcto)
        widget.setStyleSheet("border: 1px solid #EF4444; background-color: #FEF2F2; color: #B42318;")
        widget.setToolTip(f"No corresponde a la forma de contrato {self.inputs['FORMA DE CONTRATO'].currentText()}. Corrígelo a {destino}.")
        btn.setText(f" Corregir a {destino}")
        btn.setVisible(True)

    def _corregir_tipo_facturacion(self):
        correcto = self._tipo_facturacion_correcto()
        if correcto is None:
            return
        self._sincronizar_tipo_facturacion_con_forma_contrato()
        self._actualizar_alerta_tipo_facturacion()

    def _on_tipo_facturacion_editado(self, index):
        """Se dispara solo cuando el usuario elige un valor del combo TIPO
        DE FACTURACION con el mouse/teclado (señal `activated`, mismo patrón
        que MODELO/ETAPA GESTIÓN). Traduce el texto amigable mostrado al
        valor REAL (TIPO_FACTURACION_DISPLAY_A_REAL) antes de propagarlo.

        FORMA DE CONTRATO manda sobre TIPO DE FACTURACION (generalizado
        24-09-2026 a partir de FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ; antes
        solo cubría el caso 'CM'): si el valor elegido no está entre los
        permitidos para el FORMA DE CONTRATO vigente, la selección se
        revierte sin aplicar ningún cambio. En la práctica el combo ya solo
        ofrece los valores válidos (ver _sincronizar_tipo_facturacion_con_forma_contrato,
        que reconstruye sus ítems), así que esto es una defensa adicional
        para el instante en que FORMA DE CONTRATO aún no se ha tocado en
        vivo. Esto es exclusivo de la interacción en vivo: la precarga de una
        unidad real con esta combinación "inconsistente" ya guardada NUNCA
        pasa por este método (ver _aplicar_datos_iniciales, que setea el
        combo directamente con blockSignals), así que no se pierde ningún
        dato histórico al abrir el formulario."""
        widget = self.inputs['TIPO DE FACTURACION']
        texto_amigable = widget.currentText()
        valor_real = TIPO_FACTURACION_DISPLAY_A_REAL.get(texto_amigable, texto_amigable)

        validos = self._tipo_facturacion_validos_actual()
        if validos is not None and valor_real not in validos:
            widget.blockSignals(True)
            widget.setCurrentText(TIPO_FACTURACION_DISPLAY_MAP.get(self._tipo_facturacion_actual, self._tipo_facturacion_actual))
            widget.blockSignals(False)
            return

        self._aplicar_tipo_facturacion_programatico(valor_real)

    def _aplicar_tipo_facturacion_programatico(self, valor_real):
        """Punto único que aplica un nuevo TIPO DE FACTURACION (ya sea por
        elección real del usuario en el combo, o porque FORMA DE CONTRATO lo
        fuerza -- ver _sincronizar_tipo_facturacion_con_forma_contrato):
        actualiza el combo, el holder, ETAPA GESTIÓN, la habilitación de
        bloques y dispara la limpieza en vivo del bloque que deja de
        corresponder (16-09-2026, decisión explícita del usuario: reemplaza
        la regla "no limpiar" de la Fase 4 -- ver _limpiar_bloques_si_corresponde)."""
        widget = self.inputs['TIPO DE FACTURACION']
        valor_anterior = self._tipo_facturacion_actual
        widget.blockSignals(True)
        widget.setCurrentText(TIPO_FACTURACION_DISPLAY_MAP.get(valor_real, valor_real))
        widget.blockSignals(False)
        self._set_tipo_facturacion_actual(valor_real)
        self._actualizar_habilitacion_justtime_cm()
        self._limpiar_bloques_si_corresponde(valor_anterior, valor_real)
        self._reconciliar_justtime_por_tipo(valor_anterior, valor_real)
        self._autocompletar_duracion_mensual()
        self._actualizar_resumen()

    def _limpiar_bloques_si_corresponde(self, valor_anterior, valor_nuevo):
        """Limpia a '-' los campos de un bloque (JustTime o CM) cuando ese
        bloque pasa de habilitado a deshabilitado por el cambio de TIPO DE
        FACTURACION. Solo actúa en la transición habilitado->deshabilitado;
        si el bloque sigue habilitado (ej. de 'Cliente' a 'Interno') o si ya
        estaba deshabilitado, no toca nada. Exclusivo de cambios EN VIVO
        (nunca se llama durante la precarga), por decisión explícita del
        usuario: los datos reales existentes nunca se limpian solo por abrir
        el formulario."""
        anterior = str(valor_anterior).strip().upper()
        nuevo = str(valor_nuevo).strip().upper()

        edicion_manual = self.modo_edicion and not self._justtime_automatico()
        if anterior in TIPO_FACTURACION_HABILITA_JUSTTIME and nuevo not in TIPO_FACTURACION_HABILITA_JUSTTIME \
                and not edicion_manual:
            self._limpiar_bloque(_CAMPOS_BLOQUE_JUSTTIME)

        if anterior in TIPO_FACTURACION_HABILITA_CM and nuevo not in TIPO_FACTURACION_HABILITA_CM:
            self._limpiar_bloque(_CAMPOS_BLOQUE_CM)
            self._tipo_cm_manual = False

    def _limpiar_bloque(self, campos):
        for campo in campos:
            widget = self.inputs[campo]
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentText('-')
            else:
                widget.setText('-')
            widget.setStyleSheet("")
            widget.setToolTip("")
            widget.blockSignals(False)

    def _sincronizar_tipo_facturacion_con_forma_contrato(self):
        """FORMA DE CONTRATO manda sobre TIPO DE FACTURACION (generalizado
        24-09-2026 a partir de FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ; antes
        solo cubría el caso 'CM' -> CMG/CMB/CMS). Reconstruye las opciones
        del combo TIPO DE FACTURACION al subconjunto válido para el FORMA DE
        CONTRATO vigente; si ese subconjunto tiene un único valor posible, lo
        fuerza automáticamente (mismo comportamiento que antes tenía el caso
        CM, ahora generalizado también a DEMO/PROVISION/PROVISION +/REVISAR/
        SIN CONTRATO/TEST). Si tiene más de un valor posible (CONVERSION/
        VENTA: Cliente o Facturación Manual), solo restringe las opciones sin
        forzar ninguna -- el usuario elige entre las válidas. Si FORMA DE
        CONTRATO no está en la matriz, no restringe nada (catálogo completo).
        Solo aplica en vivo: no se conecta a nada durante la precarga (ver
        _aplicar_datos_iniciales, que precarga TIPO DE FACTURACION aparte)."""
        validos = self._tipo_facturacion_validos_actual()
        widget = self.inputs['TIPO DE FACTURACION']
        valor_actual = str(self._tipo_facturacion_actual).strip().upper()

        nuevos_valores = (
            list(_ORDEN_TIPO_FACTURACION_SIN_GUION) if validos is None
            else [v for v in _ORDEN_TIPO_FACTURACION if v in validos]
        )
        # "-" quitado del catálogo elegible (25-09-2026, mismo pedido que en
        # _create_widget), salvo que sea la ÚNICA opción válida para el
        # FORMA DE CONTRATO vigente (ej. datos legados con FORMA DE
        # CONTRATO='-') -- en ese caso se conserva para no dejar el combo
        # sin ninguna opción.
        sin_guion = [v for v in nuevos_valores if v != '-']
        if sin_guion:
            nuevos_valores = sin_guion
        widget.blockSignals(True)
        widget.clear()
        widget.addItems([TIPO_FACTURACION_DISPLAY_MAP[v] for v in nuevos_valores])
        widget.blockSignals(False)

        if validos is None or valor_actual in validos:
            # Sigue siendo válido (o no hay restricción para este FORMA DE
            # CONTRATO): solo se actualizó la lista de opciones, el valor
            # elegido no cambia.
            widget.blockSignals(True)
            widget.setCurrentText(TIPO_FACTURACION_DISPLAY_MAP.get(valor_actual, valor_actual))
            widget.blockSignals(False)
        else:
            # Ya no es válido para el nuevo FORMA DE CONTRATO: se fuerza al
            # primer valor permitido (el único posible si la fila tiene una
            # sola opción; el primero de la lista si tiene más de una, ej.
            # CONVERSION/VENTA -> Cliente).
            self._aplicar_tipo_facturacion_programatico(nuevos_valores[0])

        self._actualizar_habilitacion_tipo_facturacion()
