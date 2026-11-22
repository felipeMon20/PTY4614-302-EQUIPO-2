"""Reglas por RUT, CDB, etapa de gestión y restricciones de edición del formulario de unidad."""
import re
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.constants import COL_ESTADO_COMERCIAL, COL_TIPO_FACTURACION, COL_ETAPA_GESTION, COL_ESTADO_ACTIVACION, ETAPA_GESTION_COLORES
from src.ui.comercial_agregar.base import (
    _CAMPOS_COMERCIAL_BLOQUEABLES_ALTA_GENERAL,
    _CAMPOS_JUSTTIME_CM_BLOQUEABLES_ALTA_GENERAL,
    _CAMPOS_OPERACIONES_BLOQUEABLES_ALTA_GENERAL,
)


class _ReglasFormularioMixin:
    @staticmethod
    def _quitar_guion_si_hay_numero(campo, texto):
        if len(texto) > 1 and texto.startswith('-'):
            campo.setText(texto.lstrip('-'))

    @staticmethod
    def _normalizar_vin_escrito(campo, texto):
        limpio = re.sub(r'[^A-Za-z0-9]', '', texto).upper()
        if limpio != texto:
            cursor = campo.cursorPosition() - (len(texto) - len(limpio))
            campo.setText(limpio)
            campo.setCursorPosition(max(0, cursor))

    # ------------------------------------------------------------------
    # Autocompletado a partir del RUT
    # ------------------------------------------------------------------
    def _on_rut_completado(self):
        try:
            self._autocompletar_por_rut()
        finally:
            self._actualizar_bloqueo_razon_social()
            self._actualizar_bloqueo_cdb()

    def _actualizar_bloqueo_cdb(self):
        """El CDB comercial es editable en todos los casos, salvo cuando el
        RUT ya tiene un único CDB conocido: entonces debe coincidir con el del
        RUT y no se cambia desde aquí. Con un RUT nuevo o con varios CDB
        queda libre."""
        campo = self.inputs.get('CDB')
        if campo is None:
            return
        entry = self._rut_lookup.get(self._normalizar_rut(self.inputs['RUT'].text().strip()))
        cdbs = entry['CDB'] if entry else []
        bloquear = len(cdbs) == 1
        if getattr(self, '_cdb_bloqueado', False) and not bloquear:
            campo.clear()
        self._cdb_bloqueado = bloquear
        if bloquear and campo.text().strip() != cdbs[0]:
            campo.setText(cdbs[0])
        campo.setEnabled(not bloquear)
        campo.setToolTip("Debe coincidir con el CDB de este RUT." if bloquear else "")

    def _actualizar_bloqueo_razon_social(self):
        """Al editar una unidad, si su RUT ya existe con una única razón
        social, ese nombre es del cliente (todas las unidades de ese RUT) y no
        se cambia desde aquí: se edita en Administración → Clientes. Cambiar
        el RUT mueve solo esta unidad: con un RUT conocido el nombre se
        autocompleta y queda bloqueado; con uno nuevo queda libre."""
        campo = self.inputs.get('RAZÓN SOCIAL')
        if campo is None:
            return
        entry = self._rut_lookup.get(self._normalizar_rut(self.inputs['RUT'].text().strip()))
        bloquear = bool(entry) and len(entry['RAZÓN SOCIAL']) == 1
        if getattr(self, '_razon_bloqueada', False) and not bloquear:
            # Pasó de un RUT con nombre a uno sin nombre conocido: se vacía
            # para no dejar el nombre de otro cliente en el RUT nuevo.
            campo.clear()
        self._razon_bloqueada = bloquear
        campo.setEnabled(not bloquear)
        if bloquear:
            campo.setToolTip("Este RUT ya tiene nombre: se cambia para todas sus unidades en Administración → Clientes.")

    def _autocompletar_por_rut(self):
        """En vivo, con cada cambio en el campo RUT (tipeo o pegado),
        autocompleta RAZÓN SOCIAL y CDB si ese RUT tiene un único valor
        conocido en Comercial (un mismo RUT puede tener varias unidades; si
        hay varias RAZÓN SOCIAL/CDB distintas para el mismo RUT -- datos
        inconsistentes -- no se autocompleta nada, para no sobrescribir con
        un valor arbitrario: se deja una pista visual en el tooltip del
        campo). INDUSTRIA se autocompleta siempre con la más frecuente
        (moda) para ese RUT, editable por el usuario si corresponde otra.
        Para EJECUTIVO: si hay uno solo lo autocompleta; si hay más de uno,
        los deja disponibles como opciones del combo (o se puede escribir
        uno nuevo) en vez de imponer uno. Todo opcional/editable: si el RUT
        es nuevo (no existe en Comercial) no cambia nada y el usuario
        completa todo a mano."""
        rut = self.inputs['RUT'].text().strip()
        entry = self._rut_lookup.get(self._normalizar_rut(rut)) if rut else None
        if not entry:
            return

        razones = entry['RAZÓN SOCIAL']
        campo_razon = self.inputs['RAZÓN SOCIAL']
        if len(razones) == 1:
            campo_razon.setText(razones[0])
            campo_razon.setToolTip("")
        elif len(razones) > 1:
            # Dato inconsistente en Comercial (mismo RUT con más de una razón
            # social registrada): no se elige una al azar, se avisa y se deja
            # que el usuario decida.
            campo_razon.setToolTip("Este RUT tiene varias Razones Sociales registradas en Comercial:\n- " + "\n- ".join(razones))

        cdbs = entry['CDB']
        if len(cdbs) == 1:
            # setText dispara textChanged -> _actualizar_flota_vc_por_cdb
            # automáticamente (misma conexión que si el CDB se escribe/pega
            # a mano), así que no hace falta llamarlo aquí de nuevo.
            self.inputs['CDB'].setText(cdbs[0])

        industria_moda = entry['INDUSTRIA_MODA']
        if industria_moda:
            self.inputs['INDUSTRIA'].setCurrentText(industria_moda)

        ejecutivos = entry['EJECUTIVO']
        combo_ejecutivo = self.inputs['EJECUTIVO']
        combo_ejecutivo.blockSignals(True)
        combo_ejecutivo.clear()
        combo_ejecutivo.addItems([""] + ejecutivos + [e for e in self._ejecutivos_todos if e not in ejecutivos])
        combo_ejecutivo.setCurrentText(ejecutivos[0] if len(ejecutivos) == 1 else "")
        combo_ejecutivo.blockSignals(False)

    def _actualizar_flota_vc_por_cdb(self):
        """FLOTA VC (opcional) se filtra a las flotas ya asociadas al CDB
        ingresado; si el CDB no tiene flotas conocidas (o está vacío),
        vuelve a ofrecer el listado completo. FLOTA VC 2 no se toca:
        también es opcional pero nunca se autocompleta ni se filtra."""
        cdb = self.inputs['CDB'].text().strip()
        opciones = self._flota_by_cdb.get(cdb.upper()) if cdb else None

        combo_flota = self.inputs['FLOTA VC']
        texto_actual = combo_flota.currentText()
        combo_flota.blockSignals(True)
        combo_flota.clear()
        combo_flota.addItems([""] + (opciones if opciones else self.flotas_unicas))
        combo_flota.setCurrentText(texto_actual)
        combo_flota.blockSignals(False)

    # ------------------------------------------------------------------
    # ETAPA GESTIÓN: recálculo automático (reutiliza la regla central de
    # negocio) + edición manual (16-09-2026)
    # ------------------------------------------------------------------
    def _aplicar_color_etapa_gestion(self, valor):
        """Colorea el texto del combo ETAPA GESTIÓN igual que la tabla de
        Unidades (general.py): solo color de texto en negrita, sin fondo,
        usando la misma paleta ETAPA_GESTION_COLORES (sin crear una nueva)."""
        color = ETAPA_GESTION_COLORES.get(str(valor).strip().upper())
        widget = self.inputs['ETAPA GESTIÓN']
        if color:
            widget.setStyleSheet(f"QComboBox {{ color: {color}; font-weight: bold; }}")
        else:
            # Valor legado/no reconocido (ver _set_combo_valor_precargado):
            # se preserva tal cual, sin forzar un color que no le corresponde.
            widget.setStyleSheet("")

    def _set_etapa_gestion_widget(self, valor):
        """Selecciona `valor` en el combo ETAPA GESTIÓN (deshabilitado, sin
        interacción de usuario posible) y aplica su color. Mismo criterio de
        preservar valores legados que _set_combo_valor_precargado: si `valor`
        no está entre las 2 opciones oficiales, se agrega tal cual en vez de
        descartarlo."""
        widget = self.inputs['ETAPA GESTIÓN']
        widget.blockSignals(True)
        self._set_combo_valor_precargado(widget, str(valor))
        widget.blockSignals(False)
        self._aplicar_color_etapa_gestion(valor)

    def _recalcular_etapa_gestion(self, *_args):
        """Recalcula ETAPA GESTIÓN reutilizando tal cual la única fuente de
        verdad de esta regla de negocio (DataFrameFormatter.calcular_etapa_gestion_esperada),
        sin reimplementarla en la UI. Se llama al cambiar cualquiera de sus
        3 disparadores (ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL --
        agregado 21-09-2026 junto con la matriz de 2 ejes -- y TIPO DE
        FACTURACION). El combo está siempre deshabilitado (22-09-2026, a
        pedido explícito: la regla de negocio debe respetarse siempre, sin
        importar desde dónde se abra el formulario), así que este es el
        único lugar que cambia su valor. `*_args` absorbe el argumento que
        Qt pasa en `currentTextChanged` (el texto nuevo), que no se necesita
        acá porque se vuelve a leer el valor actual directamente del widget."""
        row = {
            COL_ESTADO_COMERCIAL: self.inputs['ESTADO COMERCIAL'].currentText(),
            COL_ESTADO_ACTIVACION: self.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].currentText(),
            COL_TIPO_FACTURACION: self._tipo_facturacion_actual,
            COL_ETAPA_GESTION: self.inputs['ETAPA GESTIÓN'].currentText(),
        }
        nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada(row)
        self._set_etapa_gestion_widget(nueva_etapa)

    def _aplicar_restriccion_activacion(self, forzar_activacion_pendiente):
        """Modo restringido al editar una unidad desde "Por gestionar" o
        "Gestionar Bajas" (ver `restringir_activacion` en __init__). Deja
        SIEMPRE de solo lectura toda la pestaña Operaciones, sin importar el
        tipo de unidad (25-09-2026, ajustado a pedido explícito: antes esto
        solo se aplicaba cuando además se forzaba el estado, dejando
        Operaciones editable para el resto de las unidades de "Por
        gestionar" -- ver también _aplicar_restriccion_operaciones_solo_lectura).

        `forzar_activacion_pendiente` (ver el parámetro homónimo en
        __init__) además fuerza ESTADO COMERCIAL="Activación Pendiente"
        (restringiendo el combo a esa única opción) y ESTADO DE ACTIVACIÓN
        ACTUAL="Activando" -- exclusivo de la unidad real "Sin Contrato"/
        "Sin Registro"; el resto de las unidades de "Por gestionar" solo ven
        Operaciones bloqueada, sin que se les fuerce ningún valor.

        ETAPA GESTIÓN no se toca acá: está siempre deshabilitada (ver
        combo_etapa.setEnabled(False) en _setup_ui), sin importar el modo."""
        self._aplicar_restriccion_operaciones_solo_lectura()

        if forzar_activacion_pendiente:
            combo_estado_comercial = self.inputs['ESTADO COMERCIAL']
            combo_estado_comercial.blockSignals(True)
            combo_estado_comercial.clear()
            combo_estado_comercial.addItem('Activación Pendiente')
            combo_estado_comercial.setCurrentText('Activación Pendiente')
            combo_estado_comercial.blockSignals(False)
            combo_estado_comercial.setEnabled(False)

            combo_activacion = self.inputs['ESTADO DE ACTIVACIÓN ACTUAL']
            combo_activacion.setCurrentText('Activando')

    def _aplicar_restriccion_operaciones_solo_lectura(self):
        """Deja de solo lectura toda la pestaña Operaciones (CDB/FLOTA VC/
        FLOTA VC 2/ESTADO DE ACTIVACIÓN ACTUAL/ESTADO DE ENTREGA/FECHA DE
        BAJA), sin forzar ni tocar ningún valor -- separado de
        _aplicar_restriccion_activacion (25-09-2026) porque también lo usa
        el caso "Por gestionar" sin `forzar_activacion_pendiente`. CDB
        agregado 25-09-2026 al moverse de "Empresa" a esta pestaña."""
        self.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].setEnabled(False)
        for campo in ('CDB FLOTA', 'FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ENTREGA', 'FECHA DE BAJA'):
            self.inputs[campo].setEnabled(False)
        # Insignia "🔒 Bloqueado" en el encabezado de la sección (25-09-2026,
        # a pedido explícito: "quiero que cuando esta bloqueada el campo se
        # resalte con algo") -- mismo mecanismo que ya usan JustTime/CM
        # (ver _set_badge_bloqueo), reutilizado acá en vez de inventar un
        # aviso nuevo. Los campos en sí también cambian de color vía QSS
        # (ver QLineEdit:disabled/QComboBox:disabled en _init_form).
        self._set_badge_bloqueo('operativa', False)

    def _aplicar_restriccion_vigentes(self):
        """Modo restringido al editar una unidad desde "Vigentes" (ver
        `restringir_vigentes` en __init__). A diferencia de
        _aplicar_restriccion_activacion, no fuerza ningún valor fijo: solo
        recorta las opciones del combo ESTADO COMERCIAL (una unidad Vigente
        no se marca a mano como "Vencido" -- eso lo decide la fecha de
        TÉRMINO CONTRATO o el botón "Marcar como Vencido" en Vencidos -- ni
        "vuelve" a "Activación Pendiente", el punto de partida del flujo de
        activación) y deja de solo lectura toda la pestaña Operaciones,
        incluido ESTADO DE ACTIVACIÓN ACTUAL, que solo debe cambiar vía las
        acciones de Operaciones (Marcar como CONECTADO/SIN FLOTA/
        DESCONECTADO), nunca a mano desde este formulario. "Baja"/"Baja
        Solicitada" quedan disponibles en el combo: Operaciones debe seguir
        recibiéndolas según sus propias reglas de negocio (ver
        operaciones_services.py) -- ETAPA GESTIÓN se recalcula solo, igual
        que siempre (ver _recalcular_etapa_gestion)."""
        combo_estado_comercial = self.inputs['ESTADO COMERCIAL']
        actual = combo_estado_comercial.currentText()
        for valor in ('Vencido', 'Activación Pendiente'):
            if valor == actual:
                continue
            idx = combo_estado_comercial.findText(valor)
            if idx >= 0:
                combo_estado_comercial.removeItem(idx)

        for campo in ('CDB FLOTA', 'FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ACTIVACIÓN ACTUAL', 'ESTADO DE ENTREGA', 'FECHA DE BAJA'):
            self.inputs[campo].setEnabled(False)
        self._set_badge_bloqueo('operativa', False)

    def _aplicar_restriccion_alta_general(self):
        """Ver `restringir_alta_desde_general` en __init__. Bloquea Comercial
        (excepto EJECUTIVO), Operaciones y JustTime & CM completas, sin
        borrar ningún valor -- una unidad importada de Power BI conserva lo
        que traiga el Excel, solo queda de solo lectura desde este
        formulario. Se llama tanto al final de __init__ como al final de
        _aplicar_datos_iniciales (necesario en modo lote: cada registro nuevo
        pasa por _actualizar_habilitacion_justtime_cm, que reactivaría estos
        mismos campos según TIPO DE FACTURACION si no se re-bloquearan
        después)."""
        for campo in (
            _CAMPOS_COMERCIAL_BLOQUEABLES_ALTA_GENERAL
            + _CAMPOS_OPERACIONES_BLOQUEABLES_ALTA_GENERAL
            + _CAMPOS_JUSTTIME_CM_BLOQUEABLES_ALTA_GENERAL
        ):
            if campo in self.inputs:
                self.inputs[campo].setEnabled(False)

    def _set_tipo_facturacion_actual(self, valor):
        """Punto único para actualizar TIPO DE FACTURACION (siempre el valor
        REAL, ej. 'CLIENTE', nunca el texto amigable del combo) y disparar
        el recálculo de ETAPA GESTIÓN. Único lugar que escribe
        self._tipo_facturacion_actual fuera de la precarga/reset, para no
        tener dos fuentes de verdad independientes (ver
        _on_tipo_facturacion_editado, que es quien lo llama desde el combo
        real de la pestaña "JustTime & CM")."""
        self._tipo_facturacion_actual = valor
        self._recalcular_etapa_gestion()
        self._actualizar_alerta_tipo_facturacion()
