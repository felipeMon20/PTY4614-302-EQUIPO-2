"""Carga por lote, resumen de confirmación y lectura de datos del formulario de unidad."""
from datetime import datetime
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QPushButton, QMessageBox, QFrame, QApplication, QWidget
from PyQt6.QtCore import Qt, QTimer
import qtawesome as qta
from src.theme.colors import DANGER, SUCCESS
from src.core.normalizacion import normalizar_periodo_interno
from src.core.constants import TIPO_FACTURACION_DISPLAY_MAP
from src.ui.comercial_agregar.base import (
    COLUMNAS_EXTRA_DEFAULT_GUION,
    _DEFAULTS_INICIALES,
    _ETIQUETAS_CAMPO,
    _EtiquetaElidida,
    _MESES,
    _RESUMEN_GRUPOS,
    _tipo_facturacion_default_para_forma_contrato,
)


class _LoteFormularioMixin:
    # ------------------------------------------------------------------
    # Modo lote (importación Power BI): un solo diálogo para todos los
    # registros, sin cerrar/reabrir ventana entre uno y otro.
    # ------------------------------------------------------------------
    def obtener_resultados_lote(self):
        """Lista de dicts (uno por registro, ya con get_data() aplicado) del
        lote completo. Solo tiene sentido llamarlo después de que exec()
        devolvió Accepted en modo lote."""
        return self._lote_resultados

    def lote_fue_cancelado(self):
        return self._lote_cancelado

    def _actualizar_texto_guardar(self):
        if self._modo_lote:
            es_ultimo = self._lote_indice >= len(self._lote) - 1
            self.btn_save.setText(" Guardar y finalizar" if es_ultimo else " Guardar y continuar")
        elif self._modo_varias:
            n = len(self._unidades_validas())
            self.btn_save.setText(f" Crear {n} unidad{'' if n == 1 else 'es'}")
        elif self.modo_edicion:
            self.btn_save.setText(" Guardar Cambios")
        elif self.modo_nuevo_contrato:
            self.btn_save.setText(" Crear contrato")
        else:
            self.btn_save.setText(" Guardar Registro")

    def _actualizar_progreso_visual(self):
        if not self.progreso:
            self._badge_progreso.setVisible(False)
            return
        indice, total = self.progreso
        self._badge_progreso.setText(f" {indice} / {total} ")
        self._badge_progreso.setVisible(True)

    def _actualizar_boton_chasis_bi(self):
        if self._chasis_bi_actual:
            self._btn_chasis_bi.setText(f"CHASIS: {self._chasis_bi_actual}")
            self._btn_chasis_bi.setVisible(True)
        else:
            self._btn_chasis_bi.setVisible(False)

    def _copiar_chasis_bi(self):
        if not self._chasis_bi_actual:
            return
        QApplication.clipboard().setText(self._chasis_bi_actual)
        self._btn_chasis_bi.setText(f"CHASIS: {self._chasis_bi_actual}  ✓ Copiado")
        QTimer.singleShot(1200, self._actualizar_boton_chasis_bi)

    def _handle_cancelar(self):
        if not self._modo_lote:
            self._on_formulario_cancelado()
            return

        # Confirmación en español, con los botones diferenciados por color
        # (Sí = rojo/destructivo, No = verde/continuar) -- sin usar los
        # Yes/No estándar de Qt. Mismo comportamiento de siempre: "Sí"
        # descarta TODO el lote sin escribir nada; "No" vuelve al registro
        # actual sin tocar nada.
        msg = QMessageBox(self)
        msg.setWindowTitle("Cancelar importación")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText("¿Está seguro de cancelar la importación?")
        msg.setInformativeText(
            f"Se descartarán los {len(self._lote_resultados)} de {len(self._lote)} registro(s) ya "
            "completados en este lote. No se ha escrito nada todavía en PruebasFM."
        )
        btn_si = msg.addButton("Sí", QMessageBox.ButtonRole.YesRole)
        btn_si.setStyleSheet(f"background-color: {DANGER}; color: white; font-weight: bold; padding: 6px 16px; border-radius: 6px;")
        btn_no = msg.addButton("No", QMessageBox.ButtonRole.NoRole)
        btn_no.setStyleSheet(f"background-color: {SUCCESS}; color: white; font-weight: bold; padding: 6px 16px; border-radius: 6px;")
        msg.setDefaultButton(btn_no)
        msg.exec()

        if msg.clickedButton() is btn_si:
            self._cancelar_lote()
        # "No": no hace nada, sigue en el registro actual tal cual estaba.

    def _cancelar_lote(self):
        self._lote_cancelado = True
        self._on_lote_cancelado()

    def _avanzar_lote(self):
        datos_confirmados = self.get_data()
        self._lote_resultados.append(datos_confirmados)
        vin_confirmado = str(datos_confirmados.get('VIN', '')).strip().upper()
        if vin_confirmado:
            self._vins_usados_en_lote.add(vin_confirmado)
        self._lote_indice += 1

        if self._lote_indice >= len(self._lote):
            # Lote completo: cada subclase decide qué hacer (ver
            # _on_lote_completado()/_on_lote_cancelado(), mismo patrón que
            # _on_formulario_confirmado()/_on_formulario_cancelado()).
            self._on_lote_completado()
            return

        self._mostrar_transicion_lote()

    def _mostrar_transicion_lote(self):
        """Overlay breve entre un registro y el siguiente: se oculta el
        formulario y se muestra "Cargando siguiente unidad" (con spinner)
        encima del mismo diálogo (nunca se cierra ni se vuelve a abrir una
        ventana)."""
        self._contenido_widget.setVisible(False)
        self._overlay_transicion.setVisible(True)
        QTimer.singleShot(350, self._cargar_siguiente_registro_lote)

    def _resetear_campos_a_default(self):
        """Vuelve cada campo a su estado inicial (mismos defaults que
        _create_widget) antes de precargar el siguiente registro del lote.
        TIPO DE FACTURACION se excluye del bucle genérico (su primer ítem
        del combo es "Cliente", no "-": ver _ORDEN_TIPO_FACTURACION) y se
        resetea aparte, junto con el estado interno que depende de él."""
        for campo, widget in self.inputs.items():
            if campo == 'TIPO DE FACTURACION':
                continue
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                if campo in _DEFAULTS_INICIALES:
                    # _set_combo_valor_precargado para combos NO editables
                    # (25-09-2026): MODELO/TIPO DE SERVICIO/TIPO DE CM
                    # siguen por defecto en "-" aunque ya no esté en su
                    # catálogo de opciones (ver _create_widget) -- setText
                    # directo silenciosamente no haría nada en un combo no
                    # editable si el texto no es un ítem existente.
                    if widget.isEditable():
                        widget.setCurrentText(_DEFAULTS_INICIALES[campo])
                    else:
                        self._set_combo_valor_precargado(widget, _DEFAULTS_INICIALES[campo])
                else:
                    widget.setCurrentIndex(0)
            elif campo in ('CHASIS', 'DURACIÓN (MESES)'):
                widget.setText("")
            elif campo in (
                'TÉRMINO CONTRATO', 'INICIO CONTRATO', 'FECHA DE BAJA', 'ESTADO DE ENTREGA',
                'INICIO', 'TERMINO', 'FECHA INICIO CM', 'FECHA TERMINO CM',
                'N CONTRATO 3PC', 'PAGO CM',
            ):
                widget.setText("-")
            else:
                widget.setText("")
            # Solo si tenía un estilo propio (ej. borde rojo de validación):
            # reaplicar una hoja vacía igual vuelve a calcular el estilo
            if widget.styleSheet():
                widget.setStyleSheet("")
            widget.setToolTip("")
            widget.blockSignals(False)

        self.combo_complementos.set_seleccion([], emitir=False)

        self._tipo_facturacion_actual = _tipo_facturacion_default_para_forma_contrato(
            _DEFAULTS_INICIALES['FORMA DE CONTRATO']
        )
        widget_tf = self.inputs['TIPO DE FACTURACION']
        widget_tf.blockSignals(True)
        # _set_combo_valor_precargado (25-09-2026): igual que MODELO/TIPO DE
        # SERVICIO/TIPO DE CM, por si el default calculado fuera "-" (ya no
        # está en el catálogo base del combo, ver _create_widget).
        self._set_combo_valor_precargado(widget_tf, TIPO_FACTURACION_DISPLAY_MAP[self._tipo_facturacion_actual])
        widget_tf.setStyleSheet("")
        widget_tf.setToolTip("")
        widget_tf.blockSignals(False)

        self._modelo_manual = False
        self._tipo_cm_manual = False
        self._recalcular_etapa_gestion()
        self._actualizar_habilitacion_justtime_cm()
        self._actualizar_habilitacion_tipo_facturacion()
        hoy = datetime.now()
        self.combo_periodo_mes.setCurrentText(_MESES[hoy.month - 1])
        self.spin_periodo_anio.setValue(hoy.year)

    def _cargar_siguiente_registro_lote(self):
        self._resetear_campos_a_default()

        datos = self._lote[self._lote_indice]
        self._chasis_bi_actual = datos.get('_CHASIS_BI', '')
        _forma_contrato_registro = datos.get('FORMA DE CONTRATO') or _DEFAULTS_INICIALES['FORMA DE CONTRATO']
        self._tipo_facturacion_actual = datos.get('TIPO DE FACTURACION') or \
            _tipo_facturacion_default_para_forma_contrato(_forma_contrato_registro)
        self.progreso = (self._lote_indice + 1, len(self._lote))

        self._aplicar_datos_iniciales(datos)
        self._actualizar_progreso_visual()
        self._actualizar_boton_chasis_bi()
        self._actualizar_texto_guardar()
        self._validar_vin_duplicado()

        self._overlay_transicion.setVisible(False)
        self._contenido_widget.setVisible(True)

    # Color e ícono de cada tarjeta del resumen de confirmación
    _ESTILO_RESUMEN = {
        "Cliente": ('fa5s.building', '#1B2B4E', '#E6ECF6'),
        "Comercial": ('fa5s.file-contract', '#1B2B4E', '#E6ECF6'),
        "Operaciones": ('fa5s.truck', '#1B2B4E', '#E6ECF6'),
        "JustTime & CM": ('fa5s.stopwatch', '#1B2B4E', '#E6ECF6'),
    }
    # Datos del cliente que van en el encabezado del resumen y no se repiten en su tarjeta
    _RESUMEN_EN_ENCABEZADO = ('RUT', 'RAZÓN SOCIAL', 'VIN', 'CHASIS')

    def _crear_tarjeta_resumen(self, titulo, pares):
        """Tarjeta compacta del resumen de confirmación: encabezado y una fila
        por dato con valor (valores largos acortados con "..."). Los datos
        vacíos se juntan en una sola línea al final."""
        icono, color, suave = self._ESTILO_RESUMEN[titulo]
        card = QFrame()
        card.setObjectName("tarjetaResumen")
        card.setStyleSheet("QFrame#tarjetaResumen { background-color: white; border: 1px solid #E3E8F0; border-radius: 10px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(1, 1, 1, 6)
        lay.setSpacing(0)

        enc = QFrame()
        enc.setStyleSheet(f"QFrame {{ background-color: {suave}; border: none; border-top-left-radius: 9px; border-top-right-radius: 9px; }}")
        enc_lay = QHBoxLayout(enc)
        enc_lay.setContentsMargins(12, 5, 12, 5)
        enc_lay.setSpacing(7)
        lbl_icono = QLabel()
        lbl_icono.setPixmap(qta.icon(icono, color=color).pixmap(11, 11))
        lbl_icono.setStyleSheet("background: transparent; border: none;")
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; background: transparent; border: none;")
        enc_lay.addWidget(lbl_icono)
        enc_lay.addWidget(lbl_titulo)
        enc_lay.addStretch()
        lay.addWidget(enc)

        def vacio(valor):
            return str(valor).strip() in ('', '-', 'nan')

        llenos = [(c, v) for c, v in pares if not vacio(v)]
        vacios = [c for c, v in pares if vacio(v)]
        for i, (campo, valor) in enumerate(llenos):
            fila = QWidget()
            fila_lay = QHBoxLayout(fila)
            fila_lay.setContentsMargins(12, 3, 12, 3)
            fila_lay.setSpacing(10)
            lbl_campo = QLabel(_ETIQUETAS_CAMPO.get(campo, campo).capitalize())
            lbl_campo.setStyleSheet("color: #66748D; font-size: 10px; background: transparent; border: none;")
            lbl_valor = _EtiquetaElidida(valor)
            lbl_valor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_valor.setStyleSheet("color: #0F1B33; font-size: 11px; font-weight: 600; background: transparent; border: none;")
            fila_lay.addWidget(lbl_campo)
            fila_lay.addWidget(lbl_valor, 1)
            if i:
                separador = QFrame()
                separador.setFixedHeight(1)
                separador.setStyleSheet("background-color: #EEF1F6; border: none;")
                lay.addWidget(separador)
            lay.addWidget(fila)
        if vacios:
            nombres = ", ".join(_ETIQUETAS_CAMPO.get(c, c).capitalize() for c in vacios)
            lbl_vacios = QLabel(f"Sin dato: {nombres}")
            lbl_vacios.setWordWrap(True)
            lbl_vacios.setContentsMargins(12, 4, 12, 0)
            lbl_vacios.setStyleSheet("color: #A7B1C2; font-size: 10px; background: transparent; border: none;")
            lay.addWidget(lbl_vacios)
        lay.addStretch(1)
        return card

    def _confirmar_resumen(self):
        """Resumen compacto de todos los campos antes de guardar: encabezado
        con la empresa y el VIN y cuatro tarjetas en dos columnas, sin
        desplazamiento. Devuelve True si el usuario confirma ("Confirmar y
        guardar"), o False si elige volver al formulario (en cuyo caso no se
        modifica ni se limpia ningún dato ingresado)."""
        data = self.get_data()

        dialog = QDialog(self)
        dialog.setWindowTitle("Confirmar " + ("cambios" if self.modo_edicion else "nueva unidad"))
        dialog.setStyleSheet("QDialog { background-color: #F6F8FB; }")
        dialog.setFixedWidth(760)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        cabecera = QHBoxLayout()
        cabecera.setSpacing(10)
        icono = QLabel()
        icono.setFixedSize(32, 32)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(qta.icon('fa5s.clipboard-check', color='#1B2B4E').pixmap(15, 15))
        icono.setStyleSheet("background: #E6ECF6; border-radius: 10px;")
        titulo = QLabel("Confirmar " + ("cambios" if self.modo_edicion else "nueva unidad"))
        titulo.setStyleSheet("color: #0F1B33; font-size: 15px; font-weight: 700;")
        chip = QLabel(f"Periodo interno \u00b7 {data.get('PERIODO INTERNO', '')}")
        chip.setStyleSheet("background: #E6ECF6; color: #1B2B4E; font-size: 10px; font-weight: 700; padding: 4px 10px; border-radius: 10px;")
        cabecera.addWidget(icono)
        cabecera.addWidget(titulo, 1)
        cabecera.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(cabecera)

        # Encabezado de la empresa y la unidad
        ident = QFrame()
        ident.setObjectName("identResumen")
        ident.setStyleSheet("QFrame#identResumen { background: white; border: 1px solid #E3E8F0; border-radius: 10px; } "
                            "QLabel { background: transparent; border: none; }")
        ident_lay = QVBoxLayout(ident)
        ident_lay.setContentsMargins(12, 7, 12, 7)
        ident_lay.setSpacing(1)
        nombre = _EtiquetaElidida(data.get('RAZÓN SOCIAL', '') or 'Sin razón social')
        nombre.setStyleSheet("color: #0F1B33; font-size: 13px; font-weight: 700;")
        partes = [f"VIN {data.get('VIN', '')}"]
        for etiqueta, campo in (("Chasis", 'CHASIS'), ("RUT", 'RUT')):
            if data.get(campo):
                partes.append(f"{etiqueta} {data[campo]}")
        detalle = _EtiquetaElidida("  \u00b7  ".join(partes))
        detalle.setStyleSheet("color: #66748D; font-size: 10px;")
        ident_lay.addWidget(nombre)
        ident_lay.addWidget(detalle)
        layout.addWidget(ident)

        grupos = []
        for titulo_g, campos in _RESUMEN_GRUPOS:
            if titulo_g == "Cliente":
                campos = [c for c in campos if c not in self._RESUMEN_EN_ENCABEZADO]
            grupos.append((titulo_g, self._crear_tarjeta_resumen(titulo_g, [(c, data.get(c, '')) for c in campos])))
        tarjetas = dict(grupos)
        # Rejilla de 2 x 2: las tarjetas de una misma fila quedan del mismo alto
        columnas = QGridLayout()
        columnas.setSpacing(8)
        columnas.setColumnStretch(0, 1)
        columnas.setColumnStretch(1, 1)
        for posicion, nombre_g in enumerate(("Cliente", "Operaciones", "Comercial", "JustTime & CM")):
            columnas.addWidget(tarjetas[nombre_g], posicion // 2, posicion % 2)
        layout.addLayout(columnas)

        pie = QHBoxLayout()
        pie.setSpacing(8)
        btn_volver = QPushButton("Volver al formulario")
        btn_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_volver.setStyleSheet("QPushButton { background: white; border: 1px solid #D9DEE8; color: #3B4A66; padding: 7px 14px; border-radius: 8px; font-weight: 600; font-size: 11px; }")
        btn_volver.clicked.connect(dialog.reject)
        btn_confirmar = QPushButton(" Confirmar y guardar")
        btn_confirmar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_confirmar.setIcon(qta.icon('fa5s.check', color='white'))
        btn_confirmar.setStyleSheet("QPushButton { background: #1B2B4E; color: white; border: none; padding: 7px 16px; border-radius: 8px; font-weight: 700; font-size: 11px; }")
        btn_confirmar.clicked.connect(dialog.accept)
        pie.addStretch()
        pie.addWidget(btn_volver)
        pie.addWidget(btn_confirmar)
        layout.addLayout(pie)

        return dialog.exec() == QDialog.DialogCode.Accepted

    def get_data(self):
        data = {key: self._valor_widget(key) for key in self.inputs}

        # VIN y CHASIS siempre en mayúsculas: las bandejas buscan la unidad por
        # el VIN en mayúsculas y uno guardado en minúsculas no se encontraba.
        for campo in ('VIN', 'CHASIS'):
            if data.get(campo):
                data[campo] = data[campo].strip().upper()

        # Campos de fecha simples y de texto de JustTime/CM: si quedaron
        # vacíos, se guardan como "-" (mismo criterio que el resto del
        # proyecto usa para celdas vacías, ver _normalizar_vacios_a_guion en
        # comercial.py). DURACIÓN (MESES) NO entra en esta regla: vacío ahí
        # significa "pendiente", no "-" (ver DataFrameFormatter.calcular_termino).
        for campo in (
            'INICIO CONTRATO', 'TÉRMINO CONTRATO', 'FECHA DE BAJA', 'ESTADO DE ENTREGA',
            'INICIO', 'TERMINO', 'FECHA INICIO CM', 'FECHA TERMINO CM',
            'CONTRATO CREADO EN JUSTTIME', 'N CONTRATO 3PC', 'PAGO CM',
        ):
            if not data.get(campo):
                data[campo] = '-'

        # Periodo interno seleccionado por el usuario (o precargado), no el
        # mes actual inyectado en silencio.
        data['PERIODO INTERNO'] = normalizar_periodo_interno(
            f"{self.combo_periodo_mes.currentText()} - {self.spin_periodo_anio.value()}")

        # Columnas que no viven en este formulario (hoy solo OBSERVACIONES:
        # los campos de JustTime/CM y FECHA DE BAJA ya tienen su propio
        # widget desde las Fases 2 y 4): siempre "-" AL CREAR una unidad
        # nueva (definido con Javiera). En modo edición no se tocan, por si
        # ya tuvieran un dato real que este formulario no muestra ni debe
        # pisar con "-".
        if not self.modo_edicion:
            for campo in COLUMNAS_EXTRA_DEFAULT_GUION:
                data[campo] = '-'

        return data
