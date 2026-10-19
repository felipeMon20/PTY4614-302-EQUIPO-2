import unittest
import logging
from datetime import datetime

import pandas as pd
from PyQt6.QtWidgets import QApplication, QDialog

from src.ui.comercial_agregar import ComercialAgregarDialog

logger = logging.getLogger("TestRunner")

# Mismos valores oficiales que DROPDOWN_OPTIONS_NUEVO_CLIENTE['MODELO'] en
# src/ui/general.py: el combo MODELO de ComercialAgregarDialog no es
# editable, asi que solo puede quedar seleccionado un valor que ya este en
# esta lista.
_DROPDOWN_OPTIONS = {
    'MODELO': ["-", "FH", "FHE", "FHL", "FM", "FME", "FML", "FMX", "FL", "FE", "VM", "N/A"],
    'FORMA DE CONTRATO': [],
    'TIPO DE SERVICIO': [],
    'ESTADO COMERCIAL': [],
    'ESTADO DE ACTIVACIÓN ACTUAL': [],
}


class TestComercialAgregarDialogAutoModelo(unittest.TestCase):
    """Prueba de integracion del flujo real de ComercialAgregarDialog:
    escribir en el campo VIN dispara textChanged -> _auto_calculate_modelo
    -> src.services.vin_service.obtener_modelo_desde_vin -> el resultado se
    refleja en el QComboBox MODELO. No usa Excel reales ni app_config.json:
    el dialogo se instancia con dropdown_options/flotas_unicas mock y
    df_comercial=None."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self):
        return ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS, df_comercial=None)

    def test_posicion_r_completa_modelo_fh(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText("YV2RB00CXRA900064")
        self.assertEqual(dialog.inputs['MODELO'].currentText(), "FH")

    def test_posicion_r_mas_b40_completa_modelo_fhe(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText("YV2RB40CXRA900064")
        self.assertEqual(dialog.inputs['MODELO'].currentText(), "FHE")

    def test_posicion_x_completa_modelo_fm(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText("YV2XB00C0RA900056")
        self.assertEqual(dialog.inputs['MODELO'].currentText(), "FM")

    def test_posicion_x_mas_b40_completa_modelo_fme(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText("YV2XB40C0RA900056")
        self.assertEqual(dialog.inputs['MODELO'].currentText(), "FME")

    def test_posicion_k_completa_modelo_vm(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText("YV2KB00C0RA900056")
        self.assertEqual(dialog.inputs['MODELO'].currentText(), "VM")

    def test_posicion_t_completa_modelo_fl(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText("YV2TB00C0RA900056")
        self.assertEqual(dialog.inputs['MODELO'].currentText(), "FL")

    def test_posicion_v_completa_modelo_fe(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText("YV2VB00C0RA900056")
        self.assertEqual(dialog.inputs['MODELO'].currentText(), "FE")

    def test_codigo_desconocido_no_sobrescribe_modelo(self):
        dialog = self._make_dialog()
        # Deja MODELO con una seleccion manual previa, simulando que el
        # usuario ya habia elegido un valor a mano.
        dialog.inputs['MODELO'].setCurrentText("N/A")
        dialog.inputs['VIN'].setText("YV2ZB00C0RA900056")
        self.assertEqual(dialog.inputs['MODELO'].currentText(), "N/A")


class TestComercialAgregarDialogGestionUnidades(unittest.TestCase):
    """Pruebas de los ajustes del 16-09-2026: VIN duplicado en vivo, MODELO
    con default '-' y respeto de la elección manual, y ESTADO DE ENTREGA
    traspasado desde datos_iniciales (Power BI/edición). No usa Excel reales:
    df_comercial es un DataFrame en memoria construido a mano."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _df_comercial(self):
        return pd.DataFrame({
            'VIN': ['YV2EXISTENTE0001', 'YV2EXISTENTE0002'],
            'RUT': ['1-9', '2-7'],
            'RAZÓN SOCIAL': ['EMPRESA UNO', 'EMPRESA DOS'],
            'CDB': ['111', '222'],
            'EJECUTIVO': ['ANA', 'LUIS'],
            'FLOTA VC': ['FLOTA A', 'FLOTA B'],
            'INDUSTRIA': ['Minería', 'Minería'],
        })

    def _make_dialog(self, **kwargs):
        return ComercialAgregarDialog(
            flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS,
            df_comercial=self._df_comercial(), **kwargs
        )

    # --- Autocompletado por RUT ---
    # Reproduce el bug real reportado el 16-09-2026: PruebasFM guarda el RUT
    # con puntos y guion (ej. '31.431.765-6', mismo formato que
    # generar_mock_data.py), pero la comparación anterior era un match
    # exacto de texto -- cualquier RUT tecleado con un formato distinto
    # (sin puntos, sin guion, con espacios) no encontraba nada.
    def _df_comercial_rut_formateado(self):
        return pd.DataFrame({
            'VIN': ['YV2FMT0000001', 'YV2FMT0000002'],
            'RUT': ['31.431.765-6', '31.431.765-6'],
            'RAZÓN SOCIAL': ['TRANSPORTES DEMO SPA', 'TRANSPORTES DEMO SPA'],
            'CDB': ['5550001', '5550001'],
            'EJECUTIVO': ['CARLA SOTO', 'CARLA SOTO'],
            'FLOTA VC': ['FLOTA DEMO', 'FLOTA DEMO'],
            'INDUSTRIA': ['Minería', 'Minería'],
        })

    def test_autocompletado_rut_sin_puntos_ni_guion_encuentra_razon_social(self):
        dialog = ComercialAgregarDialog(
            flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS,
            df_comercial=self._df_comercial_rut_formateado(),
        )
        dialog.inputs['RUT'].setText('314317656')  # RUT real: 31.431.765-6, tecleado "limpio"
        self.assertEqual(dialog.inputs['RAZÓN SOCIAL'].text(), 'TRANSPORTES DEMO SPA')

    def test_autocompletado_rut_sin_puntos_ni_guion_trae_cdb_ejecutivo_industria(self):
        dialog = ComercialAgregarDialog(
            flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS,
            df_comercial=self._df_comercial_rut_formateado(),
        )
        dialog.inputs['RUT'].setText('31431765-6')  # con guion pero sin puntos
        self.assertEqual(dialog.inputs['CDB'].text(), '5550001')
        self.assertEqual(dialog.inputs['EJECUTIVO'].currentText(), 'CARLA SOTO')
        self.assertEqual(dialog.inputs['INDUSTRIA'].currentText(), 'Minería')

    def test_autocompletado_rut_con_espacios_tambien_funciona(self):
        dialog = ComercialAgregarDialog(
            flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS,
            df_comercial=self._df_comercial_rut_formateado(),
        )
        dialog.inputs['RUT'].setText(' 31.431.765-6 ')
        self.assertEqual(dialog.inputs['RAZÓN SOCIAL'].text(), 'TRANSPORTES DEMO SPA')

    def test_autocompletado_rut_razon_social_inconsistente_no_autocompleta(self):
        df = pd.DataFrame({
            'VIN': ['YV2INC0000001', 'YV2INC0000002'],
            'RUT': ['31.431.765-6', '31.431.765-6'],
            'RAZÓN SOCIAL': ['NOMBRE VIEJO SPA', 'NOMBRE NUEVO SPA'],
            'CDB': ['1', '1'],
            'EJECUTIVO': ['ANA', 'ANA'],
            'FLOTA VC': ['', ''],
            'INDUSTRIA': ['Minería', 'Minería'],
        })
        dialog = ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS, df_comercial=df)
        dialog.inputs['RUT'].setText('314317656')
        self.assertEqual(dialog.inputs['RAZÓN SOCIAL'].text(), '')
        self.assertIn('NOMBRE VIEJO SPA', dialog.inputs['RAZÓN SOCIAL'].toolTip())
        self.assertIn('NOMBRE NUEVO SPA', dialog.inputs['RAZÓN SOCIAL'].toolTip())

    # --- VIN duplicado ---
    def test_vin_nuevo_no_duplicado_guardar_habilitado(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText('YV2NUEVO0000009')
        self.assertTrue(dialog.btn_save.isEnabled())
        self.assertEqual(dialog.inputs['VIN'].styleSheet(), '')

    def test_vin_ya_existente_bloquea_guardar_y_pinta_rojo(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText('YV2EXISTENTE0002')
        self.assertFalse(dialog.btn_save.isEnabled())
        self.assertIn('#EF4444', dialog.inputs['VIN'].styleSheet())

    def test_vin_corregido_vuelve_a_estado_normal(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText('YV2EXISTENTE0002')
        self.assertFalse(dialog.btn_save.isEnabled())
        dialog.inputs['VIN'].setText('YV2EXISTENTE0002X')  # ya no coincide con ninguna fila
        self.assertTrue(dialog.btn_save.isEnabled())
        self.assertEqual(dialog.inputs['VIN'].styleSheet(), '')

    def test_vin_original_en_edicion_no_se_marca_duplicado(self):
        datos = {'VIN': 'YV2EXISTENTE0001', 'RAZÓN SOCIAL': 'EMPRESA UNO', 'RUT': '1-9', 'EJECUTIVO': 'ANA'}
        dialog = self._make_dialog(datos_iniciales=datos, modo_edicion=True)
        self.assertTrue(dialog.btn_save.isEnabled())
        self.assertEqual(dialog.inputs['VIN'].styleSheet(), '')

    def test_vin_duplicado_metodo_helper_lo_detecta(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText('YV2EXISTENTE0001')
        self.assertTrue(dialog._vin_duplicado(dialog._valor_widget('VIN').upper()))

    def test_chasis_se_recalcula_al_cambiar_vin(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText('YV2AAAAAAA334990')
        self.assertEqual(dialog.inputs['CHASIS'].text(), 'A900064')
        dialog.inputs['VIN'].setText('YV2BBBBBBB339736')
        self.assertEqual(dialog.inputs['CHASIS'].text(), 'B339736')

    # --- MODELO ---
    def test_modelo_inicia_en_guion_sin_vin(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.inputs['MODELO'].currentText(), '-')

    def test_modelo_manual_no_se_sobrescribe_con_nuevo_vin(self):
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText('YV2RB00CXRA900064')
        self.assertEqual(dialog.inputs['MODELO'].currentText(), 'FH')
        dialog.inputs['MODELO'].setCurrentText('VM')
        dialog._on_modelo_editado_manualmente(0)  # simula la señal `activated` de una elección real del usuario
        dialog.inputs['VIN'].setText('YV2XB00C0RA900056')  # decodificaría a FM
        self.assertEqual(dialog.inputs['MODELO'].currentText(), 'VM')

    # --- ESTADO DE ENTREGA ---
    def test_estado_entrega_vacio_por_defecto_es_guion(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.get_data()['ESTADO DE ENTREGA'], '-')

    def test_estado_entrega_se_traspasa_desde_datos_iniciales(self):
        dialog = self._make_dialog(datos_iniciales={'ESTADO DE ENTREGA': '08-09-2026'})
        self.assertEqual(dialog.get_data()['ESTADO DE ENTREGA'], '08-09-2026')

    # --- PERIODO INTERNO ---
    def test_periodo_interno_formato_por_defecto(self):
        dialog = self._make_dialog()
        hoy = datetime.now()
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        esperado = f"{meses[hoy.month - 1]} - {hoy.year}"
        self.assertEqual(dialog.get_data()['PERIODO INTERNO'], esperado)

    def test_periodo_interno_no_permite_anio_mayor_al_actual(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.spin_periodo_anio.maximum(), datetime.now().year)
        dialog.spin_periodo_anio.setValue(datetime.now().year + 5)
        self.assertEqual(dialog.spin_periodo_anio.value(), datetime.now().year)


# Mismas opciones reales que DROPDOWN_OPTIONS_NUEVO_CLIENTE en general.py,
# necesarias para reproducir el bug de precarga con valores legados/otra
# capitalizacion (el _DROPDOWN_OPTIONS de mas arriba deja estas listas
# vacias, lo que no alcanza para probar un mismatch de capitalizacion real).
_DROPDOWN_OPTIONS_REALES = {
    'MODELO': ["-", "FH", "FHE", "FHL", "FM", "FME", "FML", "FMX", "FL", "FE", "VM", "N/A"],
    'FORMA DE CONTRATO': ["-", "CMB", "CMG", "CMS", "Conversion", "Demo", "Provision", "Provision +", "Sin Contrato", "Test", "Venta"],
    'TIPO DE SERVICIO': ["-", "Basico", "Full", "Full + CIV", "Medio", "Medio + CIV"],
    'ESTADO DE ACTIVACIÓN ACTUAL': ["Activando", "Conectado", "Desconectado", "No aplica", "No entregado", "Sin flota"],
    'ESTADO COMERCIAL': ["Vigente", "Vencido", "Baja", "Baja Solicitada", "Revisar", "Activación Pendiente"],
    'ESTADO DEL CM': ["Running", "Expired", "Terminated", "-"],
}


class TestComercialAgregarDialogPrecargaValoresLegados(unittest.TestCase):
    """Bug reportado 15-09-2026: al editar una unidad real, campos que el
    usuario NO tocó (FORMA DE CONTRATO, ESTADO DE ACTIVACIÓN ACTUAL,
    PERIODO INTERNO) terminaban guardándose con otro valor. Causa raíz:
    QComboBox.setCurrentText() en un combo NO editable ignora en silencio
    cualquier texto que no sea un match EXACTO (case-sensitive) con un ítem
    existente -- si el valor real en PruebasFM tiene otra capitalización
    ('CONECTADO' en vez de 'Conectado') o ya no está en la lista oficial
    ('Revisar' como FORMA DE CONTRATO), el combo se queda en el default de
    "nueva unidad" (_DEFAULTS_INICIALES) en vez de mostrar el dato real, y
    ese default termina guardándose como si el usuario lo hubiera elegido."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self, datos_iniciales):
        return ComercialAgregarDialog(
            flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES,
            df_comercial=None, datos_iniciales=datos_iniciales, modo_edicion=True,
        )

    def test_valor_con_otra_capitalizacion_se_preserva_exacto(self):
        """ESTADO DE ACTIVACIÓN ACTUAL='CONECTADO' (mayúsculas) no calza
        exacto con la opción oficial 'Conectado' del combo -- antes del fix
        se perdía en silencio y quedaba en el default 'No aplica'."""
        dialog = self._make_dialog({'VIN': 'YV2LEGACY001', 'ESTADO DE ACTIVACIÓN ACTUAL': 'CONECTADO'})
        self.assertEqual(dialog.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].currentText(), 'CONECTADO')
        self.assertEqual(dialog.get_data()['ESTADO DE ACTIVACIÓN ACTUAL'], 'CONECTADO')

    def test_valor_legado_fuera_de_la_lista_oficial_se_preserva(self):
        """FORMA DE CONTRATO='Revisar' no es ninguna de las opciones
        oficiales del combo (dato legado/inconsistente en PruebasFM) --
        antes del fix se perdía en silencio y quedaba en el default 'Sin
        Contrato'."""
        dialog = self._make_dialog({'VIN': 'YV2LEGACY002', 'FORMA DE CONTRATO': 'Revisar'})
        self.assertEqual(dialog.inputs['FORMA DE CONTRATO'].currentText(), 'Revisar')
        self.assertEqual(dialog.get_data()['FORMA DE CONTRATO'], 'Revisar')

    def test_valor_que_si_calza_exacto_no_agrega_item_duplicado(self):
        """Caso normal (sin bug): un valor que sí está tal cual en la lista
        oficial no debe agregar ningún ítem nuevo al combo."""
        dialog_base = self._make_dialog({})
        total_items_antes = dialog_base.inputs['FORMA DE CONTRATO'].count()
        dialog = self._make_dialog({'VIN': 'YV2OK001', 'FORMA DE CONTRATO': 'Sin Contrato'})
        self.assertEqual(dialog.inputs['FORMA DE CONTRATO'].currentText(), 'Sin Contrato')
        self.assertEqual(dialog.inputs['FORMA DE CONTRATO'].count(), total_items_antes)

    def test_periodo_interno_minuscula_se_precarga_en_vez_de_usar_hoy(self):
        """PruebasFM trae 'agosto - 2022' en minúscula; antes del fix no
        calzaba con _MESES (capitalizado) y el combo/spin quedaban en el
        mes/año ACTUAL (default de "nueva unidad") en vez del período real."""
        dialog = self._make_dialog({'VIN': 'YV2LEGACY003', 'PERIODO INTERNO': 'agosto - 2022'})
        self.assertEqual(dialog.combo_periodo_mes.currentText(), 'Agosto')
        self.assertEqual(dialog.spin_periodo_anio.value(), 2022)
        self.assertEqual(dialog.get_data()['PERIODO INTERNO'], 'agosto - 2022')

    def test_periodo_interno_mayuscula_tambien_se_precarga(self):
        dialog = self._make_dialog({'VIN': 'YV2LEGACY004', 'PERIODO INTERNO': 'SEPTIEMBRE - 2024'})
        self.assertEqual(dialog.combo_periodo_mes.currentText(), 'Septiembre')
        self.assertEqual(dialog.spin_periodo_anio.value(), 2024)

    def test_periodo_interno_mes_invalido_no_falla_y_no_precarga(self):
        dialog = self._make_dialog({'VIN': 'YV2LEGACY005', 'PERIODO INTERNO': 'MesQueNoExiste - 2024'})
        # No debe reventar; se queda en el default (mes/año actual), sin lanzar excepcion.
        self.assertIsNotNone(dialog.combo_periodo_mes.currentText())


class TestComercialAgregarDialogFechaDeBaja(unittest.TestCase):
    """FECHA DE BAJA pasó a tener su propio widget en la pestaña Operaciones
    (16-09-2026, Fase 2 del rediseño): mismo patrón de autoformateo
    DD-MM-YYYY que ya usa INICIO CONTRATO (ver _on_inicio_contrato_changed),
    con la diferencia de que "-" es un valor válido (sin fecha de baja
    registrada), no un error ni un estado intermedio a completar."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self, **kwargs):
        return ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS, df_comercial=None, **kwargs)

    def test_existe_widget_fecha_de_baja(self):
        dialog = self._make_dialog()
        self.assertIn('FECHA DE BAJA', dialog.inputs)

    def test_valor_inicial_al_crear_unidad_es_guion(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '-')
        self.assertEqual(dialog.get_data()['FECHA DE BAJA'], '-')

    def test_autoformatea_digitos_a_ddmmyyyy(self):
        dialog = self._make_dialog()
        dialog.inputs['FECHA DE BAJA'].setText('16092026')
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '16-09-2026')

    def test_fecha_valida_no_marca_error(self):
        dialog = self._make_dialog()
        dialog.inputs['FECHA DE BAJA'].setText('16-09-2026')
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].styleSheet(), '')
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].toolTip(), '')

    def test_fecha_inexistente_en_calendario_marca_error(self):
        dialog = self._make_dialog()
        dialog.inputs['FECHA DE BAJA'].setText('31022026')  # 31 de febrero no existe
        self.assertIn('#EF4444', dialog.inputs['FECHA DE BAJA'].styleSheet())
        self.assertNotEqual(dialog.inputs['FECHA DE BAJA'].toolTip(), '')

    def test_usuario_puede_cambiar_guion_por_una_fecha(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '-')
        dialog.inputs['FECHA DE BAJA'].setText('01012026')
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '01-01-2026')

    def test_usuario_puede_volver_de_una_fecha_a_guion(self):
        dialog = self._make_dialog()
        dialog.inputs['FECHA DE BAJA'].setText('01012026')
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '01-01-2026')
        dialog.inputs['FECHA DE BAJA'].setText('-')
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '-')
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].styleSheet(), '')

    def test_get_data_guion_no_se_valida_como_fecha_invalida_al_guardar(self):
        """'-' debe poder guardarse sin disparar el QMessageBox de "Fecha
        Inválida" (mismo criterio que INICIO CONTRATO)."""
        dialog = self._make_dialog()
        dialog.inputs['VIN'].setText('YV2FECHABAJA001')
        dialog.inputs['RAZÓN SOCIAL'].setText('EMPRESA TEST')
        dialog.inputs['RUT'].setText('1-9')
        dialog.inputs['EJECUTIVO'].setCurrentText('ANA')
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '-')
        self.assertEqual(dialog.get_data()['FECHA DE BAJA'], '-')

    def test_precarga_fecha_real_desde_datos_iniciales(self):
        dialog = self._make_dialog(
            datos_iniciales={'VIN': 'YV2FECHABAJA002', 'FECHA DE BAJA': '05-03-2025'},
            modo_edicion=True,
        )
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '05-03-2025')
        self.assertEqual(dialog.get_data()['FECHA DE BAJA'], '05-03-2025')

    def test_precarga_guion_desde_datos_iniciales(self):
        """Si la unidad editada no tiene fecha de baja (columna en '-' en
        PruebasFM), debe mostrarse '-', no quedar vacío ni con otro default."""
        dialog = self._make_dialog(
            datos_iniciales={'VIN': 'YV2FECHABAJA003', 'FECHA DE BAJA': '-'},
            modo_edicion=True,
        )
        self.assertEqual(dialog.inputs['FECHA DE BAJA'].text(), '-')
        self.assertEqual(dialog.get_data()['FECHA DE BAJA'], '-')


class TestComercialAgregarDialogEtapaGestion(unittest.TestCase):
    """ETAPA GESTIÓN pasó a tener su propio indicador editable (16-09-2026,
    Fase 3 del rediseño): reutiliza tal cual
    DataFrameFormatter.calcular_etapa_gestion_esperada (sin reimplementar la
    regla) y ETAPA_GESTION_COLORES (sin paleta nueva). Usa
    _DROPDOWN_OPTIONS_REALES (no _DROPDOWN_OPTIONS) porque necesita que
    ESTADO COMERCIAL tenga sus valores reales disponibles en el combo -- con
    la lista vacía de _DROPDOWN_OPTIONS, _DEFAULTS_INICIALES no puede
    seleccionar 'Revisar' (QComboBox no editable ignora en silencio un
    setCurrentText que no calza con ningún ítem existente).

    TIPO DE FACTURACION todavía no tiene combo propio (pestaña "JustTime &
    CM", Fase 4): se simula ese disparador llamando directamente a
    _set_tipo_facturacion_actual(), el mismo método que la Fase 4 conectará
    al combo real."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self, **kwargs):
        return ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES, df_comercial=None, **kwargs)

    @staticmethod
    def _vigente_desconectado(dialog):
        """Vigente + Desconectado -> OPERACIONES en la matriz (la combinación
        con default 'No aplica' da COMERCIAL desde el 28-09-2026)."""
        dialog.inputs['ESTADO COMERCIAL'].setCurrentText('Vigente')
        dialog.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].setCurrentText('Desconectado')

    def test_existe_widget_etapa_gestion(self):
        dialog = self._make_dialog()
        self.assertIn('ETAPA GESTIÓN', dialog.inputs)

    def test_calculo_inicial_default_es_comercial(self):
        """Default de unidad nueva: ESTADO COMERCIAL='Revisar' + ESTADO DE
        ACTIVACIÓN ACTUAL='No aplica' (ambos _DEFAULTS_INICIALES) + TIPO DE
        FACTURACION='-' -> ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ da
        COMERCIAL."""
        dialog = self._make_dialog()
        self.assertEqual(dialog.inputs['ESTADO COMERCIAL'].currentText(), 'Revisar')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'COMERCIAL')
        self.assertEqual(dialog.get_data()['ETAPA GESTIÓN'], 'COMERCIAL')

    def test_color_se_aplica_segun_etapa(self):
        from src.core.constants import ETAPA_GESTION_COLORES
        dialog = self._make_dialog()
        color_comercial = ETAPA_GESTION_COLORES['COMERCIAL']
        self.assertIn(color_comercial, dialog.inputs['ETAPA GESTIÓN'].styleSheet())

    def test_cambio_estado_comercial_recalcula(self):
        """ESTADO DE ACTIVACIÓN ACTUAL se queda en su default 'No aplica' --
        Vigente + No aplica -> COMERCIAL en la matriz de 2 ejes (corregida el
        28-09-2026; antes daba OPERACIONES)."""
        dialog = self._make_dialog()
        dialog.inputs['ESTADO COMERCIAL'].setCurrentText('Vigente')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'COMERCIAL')

    def test_cambio_tipo_facturacion_ya_no_sobreescribe_matriz_definida(self):
        """25-09-2026, a pedido explícito ("la matriz de ESTADO COMERCIAL
        manda a todas las demás"): SIN REGISTRO/FACTURACIÓN MANUAL dejaron
        de tener prioridad sobre la matriz (ESTADO COMERCIAL, ESTADO DE
        ACTIVACIÓN ACTUAL) cuando esta sí define un valor -- Vigente +
        Desconectado -> OPERACIONES vía matriz, y eso ya no se pisa por
        TIPO DE FACTURACION (antes sí, ver el bug real que motivó el
        cambio: unidades enviadas a Baja desde Comercial con TIPO DE
        FACTURACION=SIN REGISTRO que seguían Conectadas nunca le llegaban a
        Operaciones)."""
        dialog = self._make_dialog()
        self._vigente_desconectado(dialog)
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')
        dialog._set_tipo_facturacion_actual('SIN REGISTRO')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')

    def test_sin_registro_no_sobreescribe_matriz_definida(self):
        dialog = self._make_dialog()
        self._vigente_desconectado(dialog)
        dialog._set_tipo_facturacion_actual('SIN REGISTRO')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')

    def test_facturacion_manual_no_sobreescribe_matriz_definida(self):
        dialog = self._make_dialog()
        self._vigente_desconectado(dialog)
        dialog._set_tipo_facturacion_actual('FACTURACIÓN MANUAL')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')

    def test_etapa_gestion_esta_siempre_deshabilitada(self):
        """22-09-2026, a pedido explícito: ETAPA GESTIÓN ya no admite
        edición manual en ningún modo -- el combo queda deshabilitado
        siempre, sin importar desde dónde se abra el diálogo. Reemplaza a
        test_edicion_manual_de_etapa (probaba el mecanismo de edición
        manual, ahora eliminado junto con _on_etapa_gestion_editada_
        manualmente/_etapa_manual)."""
        dialog = self._make_dialog()
        self.assertFalse(dialog.inputs['ETAPA GESTIÓN'].isEnabled())

    def test_cambiar_campo_no_disparador_no_afecta_etapa_gestion(self):
        """Cambiar un campo que no es disparador de la matriz (FLOTA VC) no
        debe alterar ETAPA GESTIÓN. Reemplaza a
        test_edicion_manual_se_mantiene_mientras_no_cambien_disparadores
        (probaba que una edición manual persistía; ya no existe edición
        manual, ver test_etapa_gestion_esta_siempre_deshabilitada)."""
        dialog = self._make_dialog()
        valor_previo = dialog.inputs['ETAPA GESTIÓN'].currentText()
        dialog.inputs['FLOTA VC'].setCurrentText('FLOTA X')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), valor_previo)

    def test_valor_forzado_se_sobrescribe_al_cambiar_estado_comercial(self):
        """Aunque el combo reciba un valor forzado directo (setCurrentText,
        sin pasar por la matriz) que no coincide con la regla de negocio, el
        siguiente cambio de ESTADO COMERCIAL debe recalcular y sobrescribirlo
        -- la matriz siempre gana. Reemplaza a
        test_cambio_estado_comercial_despues_de_manual_vuelve_a_automatico
        (probaba lo mismo contra el mecanismo de edición manual, ya
        eliminado)."""
        dialog = self._make_dialog()
        dialog.inputs['ETAPA GESTIÓN'].setCurrentText('OPERACIONES')  # forzado a mano, no coincide con la matriz de abajo
        dialog.inputs['ESTADO COMERCIAL'].setCurrentText('Vigente')  # Vigente + No aplica (default) -> COMERCIAL
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'COMERCIAL')

        dialog.inputs['ETAPA GESTIÓN'].setCurrentText('COMERCIAL')  # forzado de nuevo, ahora al reves del proximo resultado
        dialog.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].setCurrentText('Desconectado')  # Vigente + Desconectado -> OPERACIONES
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')

    def test_valor_forzado_se_sobrescribe_al_cambiar_tipo_facturacion(self):
        """Mismo criterio que test_valor_forzado_se_sobrescribe_al_cambiar_estado_comercial,
        pero con TIPO DE FACTURACION como disparador. Reemplaza a
        test_cambio_tipo_facturacion_despues_de_manual_vuelve_a_automatico.

        25-09-2026: TIPO DE FACTURACION sigue disparando el recálculo (ver
        _set_tipo_facturacion_actual) que sobreescribe cualquier valor
        forzado a mano -- eso no cambió. Lo que sí cambió es que, con la
        matriz definida (Vigente+No aplica), el NUEVO valor de TIPO DE
        FACTURACION ya no decide el resultado por sí solo (ver
        test_cambio_tipo_facturacion_ya_no_sobreescribe_matriz_definida):
        aquí se prueba que el recálculo se dispara y vuelve a dar el valor
        de la matriz, no que SIN REGISTRO fuerce COMERCIAL."""
        dialog = self._make_dialog()
        self._vigente_desconectado(dialog)  # -> OPERACIONES via matriz
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')

        dialog.inputs['ETAPA GESTIÓN'].setCurrentText('COMERCIAL')  # forzado a mano, no coincide con la matriz
        dialog._set_tipo_facturacion_actual('SIN REGISTRO')  # dispara el recálculo -- la matriz sigue mandando
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')

    def test_precarga_etapa_existente_se_preserva_sin_recalcular(self):
        """Unidad real con ESTADO COMERCIAL=Vigente y ESTADO DE ACTIVACIÓN
        ACTUAL=Desconectado (que daría OPERACIONES) pero ETAPA GESTIÓN=COMERCIAL
        ya guardado (ej. corregido a mano antes): al editar, debe mostrarse
        COMERCIAL tal cual viene, no recalcularse solo por abrir el
        formulario."""
        dialog = self._make_dialog(
            datos_iniciales={'VIN': 'YV2ETAPA001', 'ESTADO COMERCIAL': 'Vigente',
                             'ESTADO DE ACTIVACIÓN ACTUAL': 'Desconectado', 'ETAPA GESTIÓN': 'COMERCIAL'},
            modo_edicion=True,
        )
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'COMERCIAL')
        self.assertEqual(dialog.get_data()['ETAPA GESTIÓN'], 'COMERCIAL')

    def test_precarga_sin_etapa_existente_se_calcula(self):
        """Registro sin ETAPA GESTIÓN propia (ej. importado de Power BI): se
        calcula con la regla central en vez de dejarlo vacío. ESTADO DE
        ACTIVACIÓN ACTUAL tampoco viene en `datos`, así que se queda en su
        default 'No aplica' -> Vigente + No aplica = COMERCIAL."""
        dialog = self._make_dialog(
            datos_iniciales={'VIN': 'YV2ETAPA002', 'ESTADO COMERCIAL': 'Vigente'},
            modo_edicion=True,
        )
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'COMERCIAL')
        self.assertEqual(dialog.get_data()['ETAPA GESTIÓN'], 'COMERCIAL')


class TestComercialAgregarDialogModoLote(unittest.TestCase):
    """Importación Power BI, 16-09-2026: un único ComercialAgregarDialog
    recorre todos los registros del lote (sin cerrar/reabrir ventana). El
    timer de 350ms del overlay de transición no corre solo en el test: se
    llama _cargar_siguiente_registro_lote() directamente para simular que
    ya terminó, igual que haría QTimer.singleShot en la app real."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _lote(self):
        return [
            {'RUT': '1-9', 'RAZÓN SOCIAL': 'EMPRESA A', 'INDUSTRIA': 'Minería',
             'EJECUTIVO': 'ANA', 'CDB': '1', 'MODELO': 'FH', '_CHASIS_BI': 'CH0001',
             'ESTADO DE ENTREGA': '-', 'TIPO DE SERVICIO': 'Full', 'INICIO CONTRATO': '01-09-2026', 'DURACIÓN (MESES)': '-'},
            {'RUT': '2-7', 'RAZÓN SOCIAL': 'EMPRESA B', 'INDUSTRIA': 'Minería',
             'EJECUTIVO': 'LUIS', 'CDB': '2', 'MODELO': 'FM', '_CHASIS_BI': 'CH0002',
             'ESTADO DE ENTREGA': '08-09-2026', 'TIPO DE SERVICIO': 'Full', 'INICIO CONTRATO': '01-09-2026', 'DURACIÓN (MESES)': '-'},
        ]

    def _make_dialog(self):
        return ComercialAgregarDialog(
            flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES,
            df_comercial=pd.DataFrame(), registros_lote=self._lote(),
        )

    def _confirmar_y_guardar(self, dialog, vin):
        dialog.inputs['VIN'].setText(vin)
        dialog._confirmar_resumen = lambda: True  # evita el QMessageBox real del resumen
        dialog._validate_and_accept()

    def test_primer_registro_precargado_con_progreso_y_chasis_bi(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.inputs['RAZÓN SOCIAL'].text(), 'EMPRESA A')
        self.assertEqual(dialog.progreso, (1, 2))
        # isHidden() (no isVisible()): el diálogo nunca se muestra en el
        # test (no hay .show()), así que isVisible() daría False siempre
        # sin importar el estado real del widget -- isHidden() sí refleja
        # el setVisible(True/False) explícito hecho en el código.
        self.assertFalse(dialog._btn_chasis_bi.isHidden())
        self.assertIn('CH0001', dialog._btn_chasis_bi.text())

    def test_guardar_primer_registro_avanza_al_segundo_sin_cerrar_dialogo(self):
        dialog = self._make_dialog()
        self._confirmar_y_guardar(dialog, 'YV2LOTE0000001')
        dialog._cargar_siguiente_registro_lote()  # simula que ya pasó el overlay de 350ms

        # El primer registro ya quedó guardado en el lote en memoria (aunque
        # el diálogo no se cerró: accept() recién se llama al terminar todo).
        resultados_parciales = dialog.obtener_resultados_lote()
        self.assertEqual(len(resultados_parciales), 1)
        self.assertEqual(resultados_parciales[0]['VIN'], 'YV2LOTE0000001')
        self.assertEqual(dialog.inputs['RAZÓN SOCIAL'].text(), 'EMPRESA B')
        self.assertEqual(dialog.progreso, (2, 2))
        self.assertIn('CH0002', dialog._btn_chasis_bi.text())
        self.assertEqual(dialog.inputs['VIN'].text(), '')  # el campo se limpia para el siguiente registro

    def test_guardar_ultimo_registro_cierra_con_accept_y_lote_completo(self):
        dialog = self._make_dialog()
        self._confirmar_y_guardar(dialog, 'YV2LOTE0000001')
        dialog._cargar_siguiente_registro_lote()
        self._confirmar_y_guardar(dialog, 'YV2LOTE0000002')

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        resultados = dialog.obtener_resultados_lote()
        self.assertEqual(len(resultados), 2)
        self.assertEqual(resultados[0]['VIN'], 'YV2LOTE0000001')
        self.assertEqual(resultados[0]['RAZÓN SOCIAL'], 'EMPRESA A')
        self.assertEqual(resultados[1]['VIN'], 'YV2LOTE0000002')
        self.assertEqual(resultados[1]['ESTADO DE ENTREGA'], '08-09-2026')

    def test_cancelar_lote_confirmado_marca_cancelado_y_rechaza(self):
        dialog = self._make_dialog()
        dialog._cancelar_lote()
        self.assertTrue(dialog.lote_fue_cancelado())
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_boton_guardar_dice_finalizar_en_el_ultimo_registro(self):
        dialog = self._make_dialog()
        self.assertIn('continuar', dialog.btn_save.text())
        self._confirmar_y_guardar(dialog, 'YV2LOTE0000001')
        dialog._cargar_siguiente_registro_lote()
        self.assertIn('finalizar', dialog.btn_save.text())


class TestComercialAgregarDialogJustTimeCM(unittest.TestCase):
    """Pestaña "JustTime & CM" (16-09-2026, Fase 4 del rediseño): combo real
    de TIPO DE FACTURACION (texto amigable <-> valor real vía
    TIPO_FACTURACION_DISPLAY_MAP/_DISPLAY_A_REAL), habilitación de los
    bloques JustTime/CM (TIPO_FACTURACION_HABILITA_JUSTTIME/_CM), mapeo
    FORMA DE CONTRATO -> TIPO DE CM (FORMA_CONTRATO_TIPO_CM_MAP) y catálogos
    TIPO_CM_OPCIONES/ESTADO_CM_OPCIONES -- todo reutilizado desde
    constants.py (Fase 0), sin reimplementar nada acá. Usa
    _DROPDOWN_OPTIONS_REALES porque necesita FORMA DE CONTRATO con sus
    valores reales (CMG/CMB/CMS) disponibles en el combo."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self, **kwargs):
        return ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES, df_comercial=None, **kwargs)

    def _elegir_tipo_facturacion(self, dialog, texto_amigable):
        """Simula la elección real del usuario en el combo (señal
        `activated`, no `currentTextChanged` programático). NO sirve para
        llegar a 'CM': desde la corrección del 16-09-2026 (FORMA DE CONTRATO
        manda), 'CM' ya no se puede elegir a mano en el combo -- usar
        _activar_cm()."""
        dialog.inputs['TIPO DE FACTURACION'].setCurrentText(texto_amigable)
        dialog._on_tipo_facturacion_editado(0)

    def _activar_cm(self, dialog, forma='CMG'):
        """Único camino real para llegar a TIPO DE FACTURACION='CM' desde la
        corrección del 16-09-2026: FORMA DE CONTRATO manda (ver
        _sincronizar_tipo_facturacion_con_forma_contrato)."""
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText(forma)

    # --- Combo real: display amigable <-> valor real ---
    def test_combo_tipo_facturacion_muestra_opciones_amigables_en_orden(self):
        # "-" ya no es una opción elegible del catálogo (25-09-2026, a
        # pedido explícito: "eliminar la opción para escoger '-'") -- sigue
        # existiendo como valor real posible (datos legados/sin FORMA DE
        # CONTRATO reconocida), ver test_valor_real_a_display_amigable_en_precarga
        # y _set_combo_valor_precargado, solo deja de listarse de entrada.
        dialog = self._make_dialog()
        opciones = [dialog.inputs['TIPO DE FACTURACION'].itemText(i)
                    for i in range(dialog.inputs['TIPO DE FACTURACION'].count())]
        self.assertEqual(opciones, ['Cliente', 'Interno', 'Provision +', 'CM', 'Facturación Manual', 'Sin registro'])

    def test_display_amigable_a_valor_real_en_get_data(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Provision +')  # unico FORMA DE CONTRATO que admite 'Provision +'
        self._elegir_tipo_facturacion(dialog, 'Provision +')
        self.assertEqual(dialog.get_data()['TIPO DE FACTURACION'], 'PROVISION +')

    def test_valor_real_a_display_amigable_en_precarga(self):
        dialog = self._make_dialog(
            datos_iniciales={'VIN': 'YV2JT001', 'TIPO DE FACTURACION': 'INTERNO'},
            modo_edicion=True,
        )
        self.assertEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'Interno')
        self.assertEqual(dialog.get_data()['TIPO DE FACTURACION'], 'INTERNO')

    def test_no_se_agregan_valores_compuestos_inventados(self):
        # Verificación directa: ninguno de los valores prohibidos (que solo
        # aparecían en un test antiguo, no en el Excel real) es una opción real posible.
        from src.core.constants import TIPO_FACTURACION_DISPLAY_A_REAL as _MAPA_REAL
        self.assertNotIn('PROVISION + CLIENTE', _MAPA_REAL.values())
        self.assertNotIn('PROVISION + INTERNO', _MAPA_REAL.values())

    # --- Habilitación JustTime ---
    def test_justtime_habilitado_para_cliente(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Venta')  # unico grupo que admite 'Cliente'
        self._elegir_tipo_facturacion(dialog, 'Cliente')
        self.assertTrue(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())
        self.assertTrue(dialog.inputs['INICIO'].isEnabled())
        self.assertTrue(dialog.inputs['TERMINO'].isEnabled())

    def test_justtime_habilitado_para_interno(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Provision')  # unico FORMA DE CONTRATO que admite 'Interno'
        self._elegir_tipo_facturacion(dialog, 'Interno')
        self.assertTrue(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())

    def test_justtime_deshabilitado_para_provision_mas(self):
        """30-09-2026 (definido con el usuario): Provisión + ya no va a JustTime."""
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Provision +')  # unico FORMA DE CONTRATO que admite 'Provision +'
        self._elegir_tipo_facturacion(dialog, 'Provision +')
        self.assertFalse(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())

    def test_justtime_deshabilitado_para_cm(self):
        dialog = self._make_dialog()
        self._activar_cm(dialog)
        self.assertFalse(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())
        self.assertFalse(dialog.inputs['INICIO'].isEnabled())
        self.assertFalse(dialog.inputs['TERMINO'].isEnabled())

    def test_justtime_deshabilitado_para_facturacion_manual(self):
        """05-10-2026 (confirmado por la contraparte comercial): Facturación Manual NO va a JustTime."""
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Venta')  # admite 'Facturación Manual'
        self._elegir_tipo_facturacion(dialog, 'Facturación Manual')
        self.assertFalse(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())

    def test_justtime_deshabilitado_para_sin_registro(self):
        dialog = self._make_dialog()
        self._elegir_tipo_facturacion(dialog, 'Sin registro')
        self.assertFalse(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())

    def test_justtime_deshabilitado_por_defecto_con_guion(self):
        dialog = self._make_dialog()
        self.assertFalse(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())

    # --- Habilitación CM ---
    def test_cm_habilitado_para_cm(self):
        dialog = self._make_dialog()
        self._activar_cm(dialog)
        self.assertTrue(dialog.inputs['N CONTRATO 3PC'].isEnabled())
        self.assertTrue(dialog.inputs['TIPO DE CM'].isEnabled())
        self.assertTrue(dialog.inputs['ESTADO DEL CM'].isEnabled())
        self.assertTrue(dialog.inputs['FECHA INICIO CM'].isEnabled())
        self.assertTrue(dialog.inputs['FECHA TERMINO CM'].isEnabled())
        self.assertTrue(dialog.inputs['PAGO CM'].isEnabled())

    def test_cm_deshabilitado_para_cliente(self):
        dialog = self._make_dialog()
        self._elegir_tipo_facturacion(dialog, 'Cliente')
        self.assertFalse(dialog.inputs['TIPO DE CM'].isEnabled())

    def test_cm_deshabilitado_para_sin_registro(self):
        dialog = self._make_dialog()
        self._elegir_tipo_facturacion(dialog, 'Sin registro')
        self.assertFalse(dialog.inputs['TIPO DE CM'].isEnabled())

    # --- Mapeo FORMA DE CONTRATO -> TIPO DE CM ---
    def test_cmg_autocompleta_gold(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMG')
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), 'Gold')

    def test_cmb_autocompleta_blue(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMB')
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), 'Blue')

    def test_cms_autocompleta_silver(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMS')
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), 'Silver')

    def test_edicion_manual_de_tipo_cm_no_se_pisa_con_forma_de_contrato(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMG')
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), 'Gold')
        dialog.inputs['TIPO DE CM'].setCurrentText('Current Contract Type')
        dialog._on_tipo_cm_editado_manualmente(0)  # simula `activated`
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMS')  # ya no deberia pisarlo
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), 'Current Contract Type')

    # --- Catálogos ---
    def test_catalogo_tipo_de_cm_es_el_centralizado(self):
        from src.core.constants import TIPO_CM_OPCIONES
        dialog = self._make_dialog()
        opciones = [dialog.inputs['TIPO DE CM'].itemText(i) for i in range(dialog.inputs['TIPO DE CM'].count())]
        self.assertEqual(opciones, TIPO_CM_OPCIONES)

    def test_catalogo_estado_del_cm_es_el_centralizado(self):
        from src.core.constants import ESTADO_CM_OPCIONES
        dialog = self._make_dialog()
        opciones = [dialog.inputs['ESTADO DEL CM'].itemText(i) for i in range(dialog.inputs['ESTADO DEL CM'].count())]
        self.assertEqual(opciones, ESTADO_CM_OPCIONES)

    # --- Fechas (mismo patrón que FECHA DE BAJA) ---
    def test_fecha_inicio_cm_autoformatea_y_acepta_guion(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.inputs['FECHA INICIO CM'].text(), '-')
        dialog.inputs['FECHA INICIO CM'].setText('16092026')
        self.assertEqual(dialog.inputs['FECHA INICIO CM'].text(), '16-09-2026')
        dialog.inputs['FECHA INICIO CM'].setText('-')
        self.assertEqual(dialog.inputs['FECHA INICIO CM'].text(), '-')

    def test_fecha_termino_cm_fecha_invalida_marca_error(self):
        dialog = self._make_dialog()
        dialog.inputs['FECHA TERMINO CM'].setText('31022026')
        self.assertIn('#EF4444', dialog.inputs['FECHA TERMINO CM'].styleSheet())

    def test_justtime_inicio_termino_autoformatean_igual(self):
        dialog = self._make_dialog()
        dialog.inputs['INICIO'].setText('01012026')
        self.assertEqual(dialog.inputs['INICIO'].text(), '01-01-2026')
        dialog.inputs['TERMINO'].setText('01012027')
        self.assertEqual(dialog.inputs['TERMINO'].text(), '01-01-2027')

    # --- PAGO CM ---
    def test_pago_cm_valor_inicial_es_guion(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.inputs['PAGO CM'].text(), '-')
        self.assertEqual(dialog.get_data()['PAGO CM'], '-')

    def test_pago_cm_se_puede_editar_y_guardar_tal_cual(self):
        dialog = self._make_dialog()
        self._activar_cm(dialog)
        dialog.inputs['PAGO CM'].setText('150000')
        self.assertEqual(dialog.get_data()['PAGO CM'], '150000')

    # --- Precarga de valores existentes (no se pierde info por bloque deshabilitado) ---
    def test_precarga_no_borra_datos_cm_aunque_el_bloque_quede_deshabilitado(self):
        """Unidad real con TIPO DE FACTURACION que NO es CM, pero que
        conserva datos históricos de CM (ej. veniá de un contrato CM que ya
        terminó): esos datos deben seguir viéndose y guardándose tal cual,
        aunque el bloque quede deshabilitado para edición."""
        dialog = self._make_dialog(
            datos_iniciales={
                'VIN': 'YV2JT002', 'TIPO DE FACTURACION': 'SIN REGISTRO',
                'N CONTRATO 3PC': '3PC-9999', 'TIPO DE CM': 'Gold',
                'ESTADO DEL CM': 'Terminated', 'FECHA INICIO CM': '01-01-2020',
                'FECHA TERMINO CM': '01-01-2021', 'PAGO CM': '99000',
            },
            modo_edicion=True,
        )
        self.assertFalse(dialog.inputs['N CONTRATO 3PC'].isEnabled())
        self.assertEqual(dialog.inputs['N CONTRATO 3PC'].text(), '3PC-9999')
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), 'Gold')
        self.assertEqual(dialog.inputs['ESTADO DEL CM'].currentText(), 'Terminated')
        self.assertEqual(dialog.inputs['FECHA INICIO CM'].text(), '01-01-2020')
        self.assertEqual(dialog.inputs['PAGO CM'].text(), '$99.000')  # formateado como moneda para mostrar

        data = dialog.get_data()
        self.assertEqual(data['N CONTRATO 3PC'], '3PC-9999')
        self.assertEqual(data['TIPO DE CM'], 'Gold')
        self.assertEqual(data['PAGO CM'], '99000')

    def test_precarga_habilita_bloque_cm_si_corresponde(self):
        dialog = self._make_dialog(
            datos_iniciales={'VIN': 'YV2JT003', 'TIPO DE FACTURACION': 'CM'},
            modo_edicion=True,
        )
        self.assertTrue(dialog.inputs['TIPO DE CM'].isEnabled())

    # --- Sincronización con _tipo_facturacion_actual ---
    def test_cambio_de_combo_actualiza_holder_interno(self):
        dialog = self._make_dialog()
        self._activar_cm(dialog)
        self.assertEqual(dialog._tipo_facturacion_actual, 'CM')

    def test_precarga_sincroniza_holder_con_el_combo(self):
        dialog = self._make_dialog(
            datos_iniciales={'VIN': 'YV2JT004', 'TIPO DE FACTURACION': 'CLIENTE'},
            modo_edicion=True,
        )
        self.assertEqual(dialog._tipo_facturacion_actual, 'CLIENTE')
        self.assertEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'Cliente')

    # --- ETAPA GESTIÓN vía el combo real ---
    def test_combo_real_dispara_recalculo_de_etapa_gestion(self):
        """25-09-2026: el combo real de TIPO DE FACTURACION sigue disparando
        el recálculo, pero con la matriz definida (Vigente+Desconectado ->
        OPERACIONES) ya no la sobreescribe -- ver el cambio de prioridad en
        DataFrameFormatter.calcular_etapa_gestion_esperada."""
        dialog = self._make_dialog()
        dialog.inputs['ESTADO COMERCIAL'].setCurrentText('Vigente')
        dialog.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].setCurrentText('Desconectado')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')
        self._elegir_tipo_facturacion(dialog, 'Sin registro')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')

    def test_combo_real_facturacion_manual_no_sobreescribe_matriz_definida(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Venta')  # unico grupo que admite 'Facturación Manual'
        dialog.inputs['ESTADO COMERCIAL'].setCurrentText('Vigente')
        dialog.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].setCurrentText('Desconectado')
        self._elegir_tipo_facturacion(dialog, 'Facturación Manual')
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'OPERACIONES')

    def test_combo_real_cm_usa_logica_existente(self):
        dialog = self._make_dialog()
        dialog.inputs['ESTADO COMERCIAL'].setCurrentText('Baja')
        self._activar_cm(dialog)
        self.assertEqual(dialog.inputs['ETAPA GESTIÓN'].currentText(), 'COMERCIAL')

    # --- Modo lote ---
    def test_modo_lote_precarga_tipo_facturacion_por_registro(self):
        lote = [
            {'VIN': 'YV2LOTEJT01', 'RAZÓN SOCIAL': 'EMPRESA A', 'RUT': '1-9', 'EJECUTIVO': 'ANA', 'TIPO DE FACTURACION': 'CM',
             'FORMA DE CONTRATO': 'CMB',
             'TIPO DE SERVICIO': 'Full', 'INICIO CONTRATO': '01-09-2026', 'DURACIÓN (MESES)': '-'},
            {'VIN': 'YV2LOTEJT02', 'RAZÓN SOCIAL': 'EMPRESA B', 'RUT': '2-7', 'EJECUTIVO': 'LUIS', 'TIPO DE FACTURACION': 'CLIENTE',
             'FORMA DE CONTRATO': 'Venta',
             'TIPO DE SERVICIO': 'Full', 'INICIO CONTRATO': '01-09-2026', 'DURACIÓN (MESES)': '-'},
        ]
        dialog = ComercialAgregarDialog(
            flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES,
            df_comercial=pd.DataFrame(), registros_lote=lote,
        )
        self.assertEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'CM')
        self.assertTrue(dialog.inputs['TIPO DE CM'].isEnabled())

        dialog.inputs['VIN'].setText('YV2LOTEJT01')
        dialog._confirmar_resumen = lambda: True
        dialog._validate_and_accept()
        dialog._cargar_siguiente_registro_lote()

        self.assertEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'Cliente')
        self.assertEqual(dialog._tipo_facturacion_actual, 'CLIENTE')
        self.assertTrue(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())
        self.assertFalse(dialog.inputs['TIPO DE CM'].isEnabled())


class TestComercialAgregarDialogFormaContratoManda(unittest.TestCase):
    """Corrección del 16-09-2026 (feedback de prueba manual, post Fase 6):
    FORMA DE CONTRATO pasa a mandar sobre TIPO DE FACTURACION='CM', y los
    bloques JustTime/CM se limpian EN VIVO cuando dejan de corresponder
    (reemplaza la regla "no limpiar" de la Fase 4, decisión explícita del
    usuario). La precarga de datos reales sigue sin limpiar nada (decisión
    B): eso ya está cubierto por test_precarga_no_borra_datos_cm_aunque_el_bloque_quede_deshabilitado."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self, **kwargs):
        return ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES, df_comercial=None, **kwargs)

    def test_no_se_puede_elegir_cm_a_mano_sin_forma_de_contrato_cm(self):
        """FORMA DE CONTRATO sigue en 'Sin Contrato' (default): elegir 'CM'
        en el combo debe revertirse solo, sin aplicar el cambio."""
        dialog = self._make_dialog()
        dialog.inputs['TIPO DE FACTURACION'].setCurrentText('CM')
        dialog._on_tipo_facturacion_editado(0)
        self.assertNotEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'CM')
        self.assertNotEqual(dialog._tipo_facturacion_actual, 'CM')
        self.assertFalse(dialog.inputs['TIPO DE CM'].isEnabled())

    def test_forma_de_contrato_cmg_promueve_tipo_facturacion_a_cm(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMG')
        self.assertEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'CM')
        self.assertEqual(dialog._tipo_facturacion_actual, 'CM')
        self.assertTrue(dialog.inputs['TIPO DE CM'].isEnabled())
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), 'Gold')

    def test_forma_de_contrato_deja_de_ser_codigo_cm_saca_de_cm_y_limpia(self):
        """24-09-2026: al dejar de ser código CM, ya no vuelve siempre a '-'
        -- se fuerza al primer valor válido para el nuevo FORMA DE CONTRATO
        según FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ ('Venta' -> 'Cliente').
        El bloque CM se limpia igual porque 'Cliente' no lo habilita."""
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMG')
        dialog.inputs['N CONTRATO 3PC'].setText('3PC-VIVO')
        dialog.inputs['PAGO CM'].setText('50000')

        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Venta')  # ya no es código CM

        self.assertEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'Cliente')
        self.assertEqual(dialog._tipo_facturacion_actual, 'CLIENTE')
        self.assertEqual(dialog.inputs['N CONTRATO 3PC'].text(), '-')
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), '-')
        self.assertEqual(dialog.inputs['PAGO CM'].text(), '-')
        self.assertFalse(dialog.inputs['TIPO DE CM'].isEnabled())

    def test_cambio_en_vivo_de_justtime_a_otro_valor_limpia_justtime(self):
        """Reproduce el bug reportado: con JustTime completado, pasar a un
        TIPO DE FACTURACION que no va a JustTime debe limpiarlo. Actualizado
        30-09-2026: Cliente y Facturación Manual ahora van ambos a JustTime,
        así que el cambio se hace vía FORMA DE CONTRATO (Provision/Interno ->
        Sin Contrato/Sin registro), y el campo JustTime es un combo."""
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Provision')
        dialog.inputs['TIPO DE FACTURACION'].setCurrentText('Interno')
        dialog._on_tipo_facturacion_editado(0)
        dialog.inputs['CONTRATO CREADO EN JUSTTIME'].setCurrentText('Pendiente')
        dialog.inputs['INICIO'].setText('01012026')

        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('Sin Contrato')

        self.assertEqual(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].currentText(), '-')
        self.assertEqual(dialog.inputs['INICIO'].text(), '-')

    def test_precarga_de_datos_reales_inconsistentes_no_se_limpia(self):
        """Decisión B (16-09-2026): un registro real con TIPO DE FACTURACION
        ya guardado como 'CM' pero FORMA DE CONTRATO que no es un código CM
        (dato histórico inconsistente) se muestra tal cual al abrir, sin
        limpiar ni revertir nada."""
        dialog = self._make_dialog(
            datos_iniciales={
                'VIN': 'YV2INCONS001', 'FORMA DE CONTRATO': 'Revisar', 'TIPO DE FACTURACION': 'CM',
                'N CONTRATO 3PC': '3PC-HIST',
            },
            modo_edicion=True,
        )
        self.assertEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'CM')
        self.assertEqual(dialog.inputs['N CONTRATO 3PC'].text(), '3PC-HIST')
        self.assertEqual(dialog.get_data()['TIPO DE FACTURACION'], 'CM')

    # --- PAGO CM: formato moneda ---
    def test_pago_cm_se_autoformatea_como_moneda_mientras_se_escribe(self):
        dialog = self._make_dialog()
        dialog.inputs['PAGO CM'].setText('80000')
        self.assertEqual(dialog.inputs['PAGO CM'].text(), '$80.000')

    def test_pago_cm_guion_no_se_reformatea(self):
        dialog = self._make_dialog()
        dialog.inputs['PAGO CM'].setText('-')
        self.assertEqual(dialog.inputs['PAGO CM'].text(), '-')

    def test_pago_cm_get_data_devuelve_numero_crudo_sin_simbolos(self):
        dialog = self._make_dialog()
        dialog.inputs['PAGO CM'].setText('80000')
        self.assertEqual(dialog.get_data()['PAGO CM'], '80000')

    # --- Aviso visual de bloqueo ---
    def test_badge_bloqueo_cm_visible_cuando_deshabilitado(self):
        # isHidden() (no isVisible()): el diálogo nunca se muestra en el
        # test, así que isVisible() daría False siempre sin importar el
        # setVisible(True) explícito hecho en el código (mismo criterio que
        # ya usa TestComercialAgregarDialogModoLote con _btn_chasis_bi).
        # _badges_bloqueo['cm'] es un dict {'frame','icon','texto'} desde el
        # rediseño sin emojis (25-09-2026, a pedido explícito) -- antes era
        # un único QLabel con el texto "🔒 Bloqueado"/"🔓 Editable".
        dialog = self._make_dialog()
        self.assertFalse(dialog._badges_bloqueo['cm']['frame'].isHidden())
        self.assertIn('Bloqueado', dialog._badges_bloqueo['cm']['texto'].text())

    def test_badge_bloqueo_cm_cambia_a_editable_cuando_se_habilita(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMG')
        self.assertIn('Editable', dialog._badges_bloqueo['cm']['texto'].text())


class TestComercialAgregarDialogGetDataFase5(unittest.TestCase):
    """Fase 5 (16-09-2026): auditoría de get_data()/guardado para todos los
    campos que ganaron widget propio en las Fases 2-4 (FECHA DE BAJA, ETAPA
    GESTIÓN, TIPO DE FACTURACION, JustTime, CM). No reimplementa ninguna
    regla: solo verifica que _valor_widget()/get_data() devuelvan lo
    esperado en creación y en edición, y que COLUMNAS_EXTRA_DEFAULT_GUION no
    conserve campos que ya tienen widget. No dispara ningún QMessageBox
    (_confirmar_resumen se reemplaza cuando se llama _validate_and_accept)."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self, **kwargs):
        return ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES, df_comercial=None, **kwargs)

    def test_columnas_extra_default_guion_solo_tiene_observaciones(self):
        from src.ui.comercial_agregar import COLUMNAS_EXTRA_DEFAULT_GUION
        self.assertEqual(COLUMNAS_EXTRA_DEFAULT_GUION, ['OBSERVACIONES'])

    def test_crear_unidad_nueva_observaciones_queda_en_guion(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.get_data()['OBSERVACIONES'], '-')

    def test_editar_unidad_no_pisa_observaciones_con_guion(self):
        """En modo edición, OBSERVACIONES no se fuerza a '-' (no tiene
        widget, así que get_data() ni siquiera la incluye): quien orquesta
        el guardado de una edición es responsable de no pisarla, tal como
        ya documentaba el código antes de esta fase."""
        dialog = self._make_dialog(datos_iniciales={'VIN': 'YV2AUD001'}, modo_edicion=True)
        self.assertNotIn('OBSERVACIONES', dialog.get_data())

    # --- TIPO DE FACTURACION: las 7 conversiones completas display -> real ---
    def test_tabla_completa_tipo_facturacion_display_a_real(self):
        """Las 6 opciones de libre elección (CM queda fuera: desde el
        16-09-2026 solo se llega ahí vía FORMA DE CONTRATO, ver
        test_cm_solo_se_alcanza_via_forma_de_contrato). Cada caso fija primero
        un FORMA DE CONTRATO compatible según FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
        (24-09-2026): desde esa matriz, TIPO DE FACTURACION ya no es de libre
        elección sin importar FORMA DE CONTRATO -- ver
        TestComercialAgregarDialogFormaContratoManda."""
        conversiones = [
            ('Cliente', 'CLIENTE', 'Venta'),
            ('Interno', 'INTERNO', 'Provision'),
            ('Provision +', 'PROVISION +', 'Provision +'),
            ('Facturación Manual', 'FACTURACIÓN MANUAL', 'Venta'),
            ('Sin registro', 'SIN REGISTRO', 'Demo'),
            # '-' quitado de este recorrido (25-09-2026, a pedido explícito:
            # "eliminar la opción para escoger '-'" en TIPO DE FACTURACION) --
            # ya no es una opción de libre elección desde el combo; sigue
            # siendo un valor real posible vía datos legados/precarga, ver
            # test_valor_real_a_display_amigable_en_precarga.
        ]
        for texto_amigable, valor_real, forma_compatible in conversiones:
            with self.subTest(texto_amigable=texto_amigable):
                dialog = self._make_dialog()
                dialog.inputs['FORMA DE CONTRATO'].setCurrentText(forma_compatible)
                dialog.inputs['TIPO DE FACTURACION'].setCurrentText(texto_amigable)
                dialog._on_tipo_facturacion_editado(0)
                self.assertEqual(dialog.get_data()['TIPO DE FACTURACION'], valor_real)
                # Nunca debe quedar el texto amigable guardado por error.
                if texto_amigable != valor_real:
                    self.assertNotEqual(dialog.get_data()['TIPO DE FACTURACION'], texto_amigable)

    def test_cm_solo_se_alcanza_via_forma_de_contrato(self):
        dialog = self._make_dialog()
        dialog.inputs['FORMA DE CONTRATO'].setCurrentText('CMB')
        self.assertEqual(dialog.get_data()['TIPO DE FACTURACION'], 'CM')

    # --- Creación: valores iniciales correctos en get_data() ---
    def test_crear_unidad_nueva_get_data_campos_nuevos(self):
        dialog = self._make_dialog()
        data = dialog.get_data()
        self.assertEqual(data['FECHA DE BAJA'], '-')
        self.assertEqual(data['ETAPA GESTIÓN'], 'COMERCIAL')  # Revisar+'-' -> COMERCIAL (Fase 3)
        # FORMA DE CONTRATO default 'Sin Contrato' -> TIPO DE FACTURACION se
        # autocompleta con 'Sin Registro' (25-09-2026, corrección de bug: antes
        # quedaba en '-' aunque FORMA DE CONTRATO ya tuviera una única opción
        # válida en la matriz -- ver _tipo_facturacion_default_para_forma_contrato).
        self.assertEqual(data['TIPO DE FACTURACION'], 'SIN REGISTRO')
        self.assertEqual(data['CONTRATO CREADO EN JUSTTIME'], '-')
        self.assertEqual(data['INICIO'], '-')
        self.assertEqual(data['TERMINO'], '-')
        self.assertEqual(data['N CONTRATO 3PC'], '-')
        self.assertEqual(data['TIPO DE CM'], '-')
        self.assertEqual(data['ESTADO DEL CM'], '-')
        self.assertEqual(data['FECHA INICIO CM'], '-')
        self.assertEqual(data['FECHA TERMINO CM'], '-')
        self.assertEqual(data['PAGO CM'], '-')

    # --- Edición: la precarga no transforma los valores reales ---
    def test_editar_unidad_get_data_devuelve_exactamente_lo_precargado(self):
        datos_reales = {
            'VIN': 'YV2AUD002', 'RAZÓN SOCIAL': 'EMPRESA AUDITORIA', 'RUT': '9-1', 'EJECUTIVO': 'ANA',
            'FECHA DE BAJA': '05-03-2025',
            'ETAPA GESTIÓN': 'OPERACIONES',
            'TIPO DE FACTURACION': 'CM',
            'CONTRATO CREADO EN JUSTTIME': '-',
            'INICIO': '-',
            'TERMINO': '-',
            'N CONTRATO 3PC': '3PC-555',
            'TIPO DE CM': 'Silver',
            'ESTADO DEL CM': 'Running',
            'FECHA INICIO CM': '01-01-2024',
            'FECHA TERMINO CM': '01-01-2025',
            'PAGO CM': '250000',
        }
        dialog = self._make_dialog(datos_iniciales=datos_reales, modo_edicion=True)
        data = dialog.get_data()
        for campo, valor_esperado in datos_reales.items():
            if campo in ('VIN', 'RAZÓN SOCIAL', 'RUT', 'EJECUTIVO'):
                continue
            with self.subTest(campo=campo):
                self.assertEqual(data[campo], valor_esperado)

    def test_editar_unidad_con_justtime_real_no_transforma_fechas(self):
        dialog = self._make_dialog(
            datos_iniciales={
                'VIN': 'YV2AUD003', 'TIPO DE FACTURACION': 'INTERNO',
                'CONTRATO CREADO EN JUSTTIME': 'JT-4321',
                'INICIO': '10-02-2026', 'TERMINO': '10-02-2027',
            },
            modo_edicion=True,
        )
        data = dialog.get_data()
        self.assertEqual(data['TIPO DE FACTURACION'], 'INTERNO')
        self.assertEqual(data['CONTRATO CREADO EN JUSTTIME'], 'JT-4321')
        self.assertEqual(data['INICIO'], '10-02-2026')
        self.assertEqual(data['TERMINO'], '10-02-2027')
        self.assertTrue(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())


class TestComercialAgregarDialogLayout(unittest.TestCase):
    """Fase 6 (16-09-2026): auditoría de layout -- gap detectado, ninguna
    prueba existente verificaba las 4 pestañas ni qué campo vive en cuál.

    Actualizado 25-09-2026 (refactor "Unidad nueva" en comercial.py, a
    pedido explícito): las 4 pestañas originales (Cliente/Comercial/
    Operaciones/JustTime & CM) se probaron fusionadas en 2 (Comercial/
    Operaciones), pero con las 5 secciones apiladas en una sola pestaña el
    formulario quedaba demasiado alto y los campos se superponían en
    pantallas normales (reportado por el usuario) -- quedó en 3: "Comercial"
    (fusiona Cliente + Comercial), "Operaciones" (sin cambios) y
    "JustTime & CM" (separada de nuevo, con su propia pestaña). Ningún campo
    cambió de nombre ni de lógica, solo de pestaña visual."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self, **kwargs):
        return ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES, df_comercial=None, **kwargs)

    def test_existen_las_4_pestanas_en_orden(self):
        dialog = self._make_dialog()
        self.assertEqual(dialog.tabs.count(), 4)
        self.assertEqual(
            [dialog.tabs.tabText(i) for i in range(4)],
            ['Empresa & Unidad', 'Comercial', 'JustTime & CM', 'Operaciones'],
        )

    def test_campos_cliente_estan_en_pestana_empresa_y_unidad(self):
        dialog = self._make_dialog()
        tab = dialog.tabs.widget(0)
        for campo in ('RUT', 'RAZÓN SOCIAL', 'INDUSTRIA', 'VIN', 'CHASIS', 'MODELO'):
            with self.subTest(campo=campo):
                self.assertTrue(tab.isAncestorOf(dialog.inputs[campo]))

    def test_campos_comercial_estan_en_pestana_comercial(self):
        dialog = self._make_dialog()
        tab = dialog.tabs.widget(1)
        for campo in ('EJECUTIVO', 'FORMA DE CONTRATO', 'TIPO DE FACTURACION', 'TIPO DE SERVICIO', 'ESTADO COMERCIAL',
                      'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO'):
            with self.subTest(campo=campo):
                self.assertTrue(tab.isAncestorOf(dialog.inputs[campo]))

    def test_campos_operaciones_estan_en_pestana_operaciones(self):
        dialog = self._make_dialog()
        tab = dialog.tabs.widget(3)
        # Desde el 08-10-2026 el CDB comercial va en Cliente y en Operaciones va el CDB FLOTA
        for campo in ('FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ACTIVACIÓN ACTUAL', 'CDB FLOTA', 'ESTADO DE ENTREGA', 'FECHA DE BAJA'):
            with self.subTest(campo=campo):
                self.assertTrue(tab.isAncestorOf(dialog.inputs[campo]))
        self.assertFalse(tab.isAncestorOf(dialog.inputs['CDB']))

    def test_campos_justtime_cm_estan_en_pestana_justtime_cm(self):
        dialog = self._make_dialog()
        tab = dialog.tabs.widget(2)
        for campo in ('CONTRATO CREADO EN JUSTTIME', 'INICIO', 'TERMINO',
                      'N CONTRATO 3PC', 'TIPO DE CM', 'ESTADO DEL CM', 'FECHA INICIO CM',
                      'FECHA TERMINO CM', 'PAGO CM'):
            with self.subTest(campo=campo):
                self.assertTrue(tab.isAncestorOf(dialog.inputs[campo]))

    def test_etapa_gestion_y_periodo_interno_fuera_de_las_pestanas(self):
        """Visibles sin importar la pestaña activa (mismo criterio que el
        mockup): viven en el layout superior, no dentro del QTabWidget."""
        dialog = self._make_dialog()
        self.assertFalse(dialog.tabs.isAncestorOf(dialog.inputs['ETAPA GESTIÓN']))
        self.assertFalse(dialog.tabs.isAncestorOf(dialog.combo_periodo_mes))


class TestComercialAgregarDialogFase6Auditoria(unittest.TestCase):
    """Fase 6 (16-09-2026): cierra brechas puntuales de cobertura detectadas
    en la auditoría final -- bloque CM deshabilitado por defecto al crear,
    un round-trip combinado de TODOS los campos nuevos (fecha de baja, etapa
    gestión, tipo de facturación, JustTime, CM) con un bloque deshabilitado,
    y ausencia de contaminación de estado entre registros de un lote."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_dialog(self, **kwargs):
        return ComercialAgregarDialog(flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES, df_comercial=None, **kwargs)

    def test_cm_deshabilitado_por_defecto_al_crear(self):
        dialog = self._make_dialog()
        self.assertFalse(dialog.inputs['TIPO DE CM'].isEnabled())
        self.assertFalse(dialog.inputs['N CONTRATO 3PC'].isEnabled())

    def test_round_trip_completo_con_bloque_cm_deshabilitado(self):
        """Combina FECHA DE BAJA + ETAPA GESTIÓN + TIPO DE FACTURACION (que
        deja JustTime habilitado y CM deshabilitado) + JustTime real + datos
        CM heredados que deben conservarse aunque el bloque quede
        deshabilitado para edición."""
        datos_reales = {
            'VIN': 'YV2ROUNDTRIP001', 'RAZÓN SOCIAL': 'EMPRESA ROUND TRIP', 'RUT': '5-5', 'EJECUTIVO': 'ANA',
            'FECHA DE BAJA': '12-05-2024',
            'ETAPA GESTIÓN': 'OPERACIONES',
            'TIPO DE FACTURACION': 'INTERNO',
            'CONTRATO CREADO EN JUSTTIME': 'JT-9001',
            'INICIO': '01-03-2026',
            'TERMINO': '01-03-2027',
            # Datos CM heredados de un contrato ya terminado: el bloque
            # queda deshabilitado porque TIPO DE FACTURACION ya no es 'CM'.
            'N CONTRATO 3PC': '3PC-7777',
            'TIPO DE CM': 'Blue',
            'ESTADO DEL CM': 'Terminated',
            'FECHA INICIO CM': '01-01-2019',
            'FECHA TERMINO CM': '01-01-2020',
            'PAGO CM': '80000',
        }
        dialog = self._make_dialog(datos_iniciales=datos_reales, modo_edicion=True)

        self.assertTrue(dialog.inputs['CONTRATO CREADO EN JUSTTIME'].isEnabled())
        self.assertFalse(dialog.inputs['TIPO DE CM'].isEnabled())

        data = dialog.get_data()
        for campo, valor_esperado in datos_reales.items():
            if campo in ('VIN', 'RAZÓN SOCIAL', 'RUT', 'EJECUTIVO'):
                continue
            with self.subTest(campo=campo):
                self.assertEqual(data[campo], valor_esperado)

    def test_modo_lote_no_contamina_estado_entre_registros(self):
        """Un registro con TIPO DE CM editado a mano y datos propios de CM
        no debe dejar rastro en el siguiente registro del mismo lote (que
        no trae esos datos). ETAPA GESTIÓN queda fuera de este caso desde
        22-09-2026 (ya no admite edición manual en ningún modo, ver
        test_etapa_gestion_esta_siempre_deshabilitada)."""
        lote = [
            {'VIN': 'YV2LOTEAUD01', 'RAZÓN SOCIAL': 'EMPRESA A', 'RUT': '1-9', 'EJECUTIVO': 'ANA',
             'TIPO DE FACTURACION': 'CM', 'FORMA DE CONTRATO': 'CMB', 'N CONTRATO 3PC': '3PC-LOTE1',
             'FECHA INICIO CM': '01-01-2024', 'PAGO CM': '123456',
             'TIPO DE SERVICIO': 'Full', 'INICIO CONTRATO': '01-09-2026', 'DURACIÓN (MESES)': '-'},
            {'VIN': 'YV2LOTEAUD02', 'RAZÓN SOCIAL': 'EMPRESA B', 'RUT': '2-7', 'EJECUTIVO': 'LUIS'},
        ]
        dialog = ComercialAgregarDialog(
            flotas_unicas=[], dropdown_options=_DROPDOWN_OPTIONS_REALES,
            df_comercial=pd.DataFrame(), registros_lote=lote,
        )
        dialog.inputs['TIPO DE CM'].setCurrentText('Current Contract Type')
        dialog._on_tipo_cm_editado_manualmente(0)
        self.assertTrue(dialog._tipo_cm_manual)

        dialog.inputs['VIN'].setText('YV2LOTEAUD01')
        dialog._confirmar_resumen = lambda: True
        dialog._validate_and_accept()
        dialog._cargar_siguiente_registro_lote()

        self.assertFalse(dialog._tipo_cm_manual)
        # Segundo registro sin FORMA DE CONTRATO propio -> vuelve al default
        # 'Sin Contrato', que a su vez autocompleta TIPO DE FACTURACION con
        # su única opción válida en la matriz ('Sin Registro'), no '-'
        # (25-09-2026, ver _tipo_facturacion_default_para_forma_contrato).
        self.assertEqual(dialog._tipo_facturacion_actual, 'SIN REGISTRO')
        self.assertEqual(dialog.inputs['TIPO DE FACTURACION'].currentText(), 'Sin registro')
        self.assertEqual(dialog.inputs['N CONTRATO 3PC'].text(), '-')
        self.assertEqual(dialog.inputs['FECHA INICIO CM'].text(), '-')
        self.assertEqual(dialog.inputs['PAGO CM'].text(), '-')
        self.assertEqual(dialog.inputs['TIPO DE CM'].currentText(), '-')
        self.assertFalse(dialog.inputs['TIPO DE CM'].isEnabled())


class TestComercialUnidadFormContratosPorId(unittest.TestCase):
    """Fase 2 (09-10-2026): el formulario embebido según el estado del
    contrato: N° Contrato al editar, contrato en baja de solo lectura con el
    botón "Crear nuevo contrato", y modo "Nuevo contrato"."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def setUp(self):
        from src.ui.comercial_agregar import ComercialUnidadFormWidget
        df = pd.DataFrame({
            'ID': ['1', '2'], 'VIN': ['YV2AAA00000900054', 'YV2AAA00000900055'],
            'ESTADO COMERCIAL': ['Baja', 'Vigente'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Desconectado', 'Conectado'],
        })
        self.form = ComercialUnidadFormWidget([], _DROPDOWN_OPTIONS_REALES, df)
        self.baja = {
            'ID': '1', 'VIN': 'YV2AAA00000900054', 'ESTADO COMERCIAL': 'Baja',
            'ESTADO DE ACTIVACIÓN ACTUAL': 'Desconectado', 'RAZÓN SOCIAL': 'ACME', 'RUT': '1-9', 'CDB': '555',
            'FORMA DE CONTRATO': 'Venta', 'TIPO DE FACTURACION': 'CLIENTE', 'INICIO CONTRATO': '01-01-2024',
            'DURACIÓN (MESES)': '12', 'PERIODO INTERNO': 'Enero - 2024',
        }

    def test_contrato_en_baja_queda_en_solo_lectura_con_boton_de_nuevo_contrato(self):
        self.form.cargar_para_editar(dict(self.baja))
        self.assertIn('N° Contrato 1', self.form._subtitle_lbl.text())
        self.assertEqual(sum(w.isEnabled() for w in self.form.inputs.values()), 0)
        self.assertFalse(self.form.btn_save.isEnabled())
        self.assertFalse(self.form._btn_nuevo_contrato.isHidden())

    def test_baja_con_unidad_conectada_no_ofrece_nuevo_contrato(self):
        self.form.cargar_para_editar(dict(self.baja, **{'ESTADO DE ACTIVACIÓN ACTUAL': 'Conectado'}))
        self.assertFalse(self.form.btn_save.isEnabled())
        self.assertTrue(self.form._btn_nuevo_contrato.isHidden())

    def test_contrato_abierto_se_edita_y_el_periodo_estandar_queda_bloqueado(self):
        abierto = dict(self.baja, **{'ID': '2', 'ESTADO COMERCIAL': 'Vigente'})
        self.form.cargar_para_editar(abierto)
        self.assertTrue(self.form.btn_save.isEnabled())
        self.assertFalse(self.form.combo_periodo_mes.isEnabled())
        self.assertTrue(self.form._btn_nuevo_contrato is None or self.form._btn_nuevo_contrato.isHidden())

    def test_periodo_interno_fuera_de_estandar_sigue_editable(self):
        abierto = dict(self.baja, **{'ESTADO COMERCIAL': 'Vigente', 'PERIODO INTERNO': 'No aplica'})
        self.form.cargar_para_editar(abierto)
        self.assertTrue(self.form.combo_periodo_mes.isEnabled())

    def test_nuevo_contrato_hereda_unidad_y_cliente_y_deja_condiciones_en_blanco(self):
        self.form.cargar_para_nuevo_contrato(dict(self.baja))
        self.assertTrue(self.form.modo_nuevo_contrato)
        self.assertEqual(self.form._title_lbl.text(), 'Nuevo contrato')
        self.assertFalse(self.form.inputs['VIN'].isEnabled())
        datos = self.form.get_data()
        self.assertEqual(datos['VIN'], 'YV2AAA00000900054')
        self.assertEqual(datos['RAZÓN SOCIAL'], 'ACME')
        self.assertEqual(datos['FORMA DE CONTRATO'], '-')
        self.assertEqual(datos['INICIO CONTRATO'], '-')
        self.assertEqual(datos['ESTADO COMERCIAL'], 'Activación Pendiente')
        self.assertEqual(datos['ESTADO DE ACTIVACIÓN ACTUAL'], 'Activando')
        self.assertNotIn('ID', datos)
        self.assertFalse(self.form.combo_periodo_mes.isEnabled())
        self.assertTrue(self.form.btn_save.isEnabled())

    def test_nuevo_contrato_sobre_vin_con_contrato_abierto_bloquea_guardar(self):
        self.form.cargar_para_nuevo_contrato(dict(self.baja, **{'VIN': 'YV2AAA00000900055'}))
        self.assertFalse(self.form.btn_save.isEnabled())

    def test_volver_a_crear_unidad_limpia_los_modos_de_contrato(self):
        self.form.cargar_para_editar(dict(self.baja))
        self.form.resetear_para_crear()
        self.assertFalse(self.form.modo_nuevo_contrato)
        self.assertTrue(self.form.inputs['VIN'].isEnabled())
        self.assertTrue(self.form.combo_periodo_mes.isEnabled())
        self.assertTrue(self.form._btn_nuevo_contrato.isHidden())
        self.assertEqual(self.form._title_lbl.text(), 'Crear Nueva Unidad')


if __name__ == '__main__':
    unittest.main()
