import unittest
from datetime import datetime

import pandas as pd

from src.core.dataframe_formatter import DataFrameFormatter


class TestCalcularTerminoContrato(unittest.TestCase):
    """Regresion del bug de intercambio dia/mes en calcular_termino (dentro de
    DataFrameFormatter.clean): antes del fix, una fecha nativa de Excel
    (datetime/Timestamp) se convertia a string ISO ANTES de calcular_termino,
    y esta la reparseaba con pd.to_datetime(format='mixed', dayfirst=True),
    lo que intercambiaba dia y mes cuando ambos eran <=12. Confirmado con
    datos reales de RM_JAVI/PruebasFM (Fase C): ~60% de los registros con
    duracion numerica quedaban con TÉRMINO CONTRATO incorrecto en cada
    load/reload/sync."""

    @staticmethod
    def _clean_termino(inicio, duracion, termino_previo=""):
        df = pd.DataFrame({
            'VIN': ['YV2TEST0001'],
            'CHASIS': ['TEST0001'],
            'INICIO CONTRATO': [inicio],
            'DURACIÓN (MESES)': [duracion],
            'TÉRMINO CONTRATO': [termino_previo],
        })
        resultado = DataFrameFormatter.clean(df)
        return str(resultado.iloc[0]['TÉRMINO CONTRATO']).strip()

    # --- Casos de regresion explicitos del bug reportado (datos reales) ---

    def test_regresion_caso_1_01_06_2026_mas_1_mes(self):
        self.assertEqual(self._clean_termino(datetime(2026, 6, 1), 1), '01-07-2026')

    def test_regresion_caso_2_03_04_2025_mas_1_mes(self):
        self.assertEqual(self._clean_termino(datetime(2025, 4, 3), 1), '03-05-2025')

    def test_regresion_caso_3_07_06_2025_mas_12_meses(self):
        self.assertEqual(self._clean_termino(datetime(2025, 6, 7), 12), '07-06-2026')

    # --- Distintos tipos/formatos de entrada para INICIO CONTRATO ---

    def test_tipo_datetime(self):
        self.assertEqual(self._clean_termino(datetime(2026, 6, 1), 1), '01-07-2026')

    def test_tipo_pandas_timestamp(self):
        self.assertEqual(self._clean_termino(pd.Timestamp(2026, 6, 1), 1), '01-07-2026')

    def test_tipo_string_iso_sin_hora(self):
        self.assertEqual(self._clean_termino('2026-06-01', 1), '01-07-2026')

    def test_tipo_string_iso_con_hora(self):
        self.assertEqual(self._clean_termino('2026-06-01 00:00:00', 1), '01-07-2026')

    def test_tipo_string_formato_negocio_ddmmyyyy(self):
        self.assertEqual(self._clean_termino('01-06-2026', 1), '01-07-2026')

    def test_dia_mayor_a_12_no_es_ambiguo_y_ya_funcionaba(self):
        # Control: con dia > 12 no existia forma de que ocurriera el swap;
        # confirma que el fix no rompe el caso que ya funcionaba.
        self.assertEqual(self._clean_termino(datetime(2025, 7, 28), 12), '28-07-2026')

    # --- Casos especiales que no deben romperse ---

    def test_duracion_guion_produce_mensual(self):
        self.assertEqual(self._clean_termino(datetime(2026, 6, 1), '-'), 'MENSUAL')

    def test_duracion_mensual_produce_mensual(self):
        self.assertEqual(self._clean_termino(datetime(2026, 6, 1), 'MENSUAL'), 'MENSUAL')

    def test_duracion_guion_reemplaza_termino_previo_con_fecha_real(self):
        # A diferencia de duracion vacia (que si conserva termino_previo, ver
        # test_duracion_vacia_conserva_termino_previo), '-' es una senal
        # explicita de mensual: debe reemplazar cualquier fecha real que
        # hubiera quedado de un contrato anterior con duracion numerica.
        self.assertEqual(
            self._clean_termino(datetime(2026, 6, 1), '-', termino_previo='15-03-2027'),
            'MENSUAL',
        )

    def test_duracion_guion_con_termino_guion_no_informado_queda_guion(self):
        # Caso VIN nuevo en RM_JAVI: DURACIÓN (MESES)='-' y TÉRMINO CONTRATO='-'
        # significa que el dato todavia NO esta informado/gestionado por
        # Javiera, no que el contrato sea mensual. Distinto de
        # test_duracion_guion_produce_mensual (termino_previo vacio) y de
        # test_duracion_guion_reemplaza_termino_previo_con_fecha_real (una
        # fecha real si confirma mensual): solo '-' explicito en AMBAS
        # columnas debe quedar pendiente.
        self.assertEqual(
            self._clean_termino(datetime(2026, 6, 1), '-', termino_previo='-'),
            '-',
        )

    def test_duracion_guion_con_termino_mensual_explicito_produce_mensual(self):
        self.assertEqual(
            self._clean_termino(datetime(2026, 6, 1), '-', termino_previo='MENSUAL'),
            'MENSUAL',
        )

    def test_duracion_mensual_reemplaza_termino_previo_con_fecha_real(self):
        self.assertEqual(
            self._clean_termino(datetime(2026, 6, 1), 'MENSUAL', termino_previo='15-03-2027'),
            'MENSUAL',
        )

    def test_duracion_mensual_normaliza_a_guion_en_ambas_columnas(self):
        # _clean_termino solo expone TÉRMINO CONTRATO; este test corre clean()
        # directo para confirmar que 'MENSUAL' en DURACIÓN (MESES) tambien se
        # normaliza a '-' (no solo TÉRMINO CONTRATO), como pide la regla de
        # negocio: "DURACIÓN (MESES) = MENSUAL -> normalizar a '-'".
        df = pd.DataFrame({
            'VIN': ['YV2TEST0001'],
            'CHASIS': ['TEST0001'],
            'INICIO CONTRATO': [datetime(2026, 6, 1)],
            'DURACIÓN (MESES)': ['MENSUAL'],
            'TÉRMINO CONTRATO': ['15-03-2027'],
        })
        resultado = DataFrameFormatter.clean(df)
        self.assertEqual(str(resultado.iloc[0]['DURACIÓN (MESES)']).strip(), '-')
        self.assertEqual(str(resultado.iloc[0]['TÉRMINO CONTRATO']).strip(), 'MENSUAL')

    def test_duracion_vacia_conserva_termino_previo(self):
        self.assertEqual(
            self._clean_termino(datetime(2026, 6, 1), '', termino_previo='15-03-2027'),
            '15-03-2027',
        )

    def test_duracion_vacia_sin_termino_previo_queda_vacio(self):
        self.assertEqual(self._clean_termino(datetime(2026, 6, 1), '', termino_previo=''), '')

    def test_duracion_vacia_no_se_interpreta_como_mensual_y_queda_vacia(self):
        # Regla confirmada: un vacio en DURACIÓN (MESES) significa que Javiera
        # todavia no gestiono el dato -- no debe convertirse en '-' ni en
        # 'MENSUAL'. Distinto de test_duracion_vacia_sin_termino_previo_queda_vacio,
        # que solo revisa TÉRMINO CONTRATO: aqui se confirma tambien que
        # DURACIÓN (MESES) en si misma permanece vacia tras clean().
        df = pd.DataFrame({
            'VIN': ['YV2TEST0001'],
            'CHASIS': ['TEST0001'],
            'INICIO CONTRATO': [datetime(2026, 6, 1)],
            'DURACIÓN (MESES)': [''],
            'TÉRMINO CONTRATO': [''],
        })
        resultado = DataFrameFormatter.clean(df)
        self.assertEqual(str(resultado.iloc[0]['DURACIÓN (MESES)']).strip(), '')
        self.assertNotEqual(str(resultado.iloc[0]['TÉRMINO CONTRATO']).strip().upper(), 'MENSUAL')

    def test_duracion_nan_conserva_termino_previo(self):
        self.assertEqual(
            self._clean_termino(datetime(2026, 6, 1), float('nan'), termino_previo='15-03-2027'),
            '15-03-2027',
        )

    # --- Fin de mes: la politica de calculo de meses (pd.DateOffset) no cambia ---

    def test_fin_de_mes_31_agosto_mas_6_meses(self):
        self.assertEqual(self._clean_termino(datetime(2026, 8, 31), 6), '28-02-2027')

    def test_fin_de_mes_31_enero_mas_1_mes(self):
        self.assertEqual(self._clean_termino(datetime(2026, 1, 31), 1), '28-02-2026')

    def test_fin_de_mes_31_diciembre_mas_2_meses(self):
        self.assertEqual(self._clean_termino(datetime(2025, 12, 31), 2), '28-02-2026')


class TestCalcularEtapaGestion(unittest.TestCase):
    """ETAPA GESTIÓN debe calcularse dentro de DataFrameFormatter.clean(), no
    depender del valor que venga escrito manualmente desde RM_JAVI.

    Orden de prioridades (reordenado 25-09-2026, a pedido explícito del
    usuario -- "la matriz de ESTADO COMERCIAL manda a todas las demás";
    antes SIN REGISTRO/FACTURACIÓN MANUAL tenían la prioridad más alta,
    causando un bug real: unidades enviadas a Baja desde Comercial que
    seguían Conectadas pero tenían TIPO DE FACTURACION=SIN REGISTRO nunca
    le llegaban a Operaciones para la desconexión física):
    Prioridad 1 (21-09-2026, matriz de 2 ejes definida con el usuario):
    (ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL) -> ETAPA GESTIÓN vía
    ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ -- gana siempre que la
    combinación esté definida, incluso sobre TIPO DE FACTURACION.
    Prioridad 2: TIPO DE FACTURACION contiene SIN REGISTRO, o es
    FACTURACIÓN MANUAL -> COMERCIAL. Solo aplica cuando la matriz NO
    definió nada para esa fila.
    Prioridad 3 (fallback final): se conserva el valor de ETAPA GESTIÓN que
    ya traía la fila. CLIENTE queda retirado del catálogo: la regla solo
    produce COMERCIAL u OPERACIONES."""

    @staticmethod
    def _clean_etapa(tipo_facturacion=None, estado_comercial=None, estado_activacion=None, etapa_previa=""):
        data = {
            'VIN': ['YV2TEST0001'],
            'CHASIS': ['TEST0001'],
            'ETAPA GESTIÓN': [etapa_previa],
        }
        if tipo_facturacion is not None:
            data['TIPO DE FACTURACION'] = [tipo_facturacion]
        if estado_comercial is not None:
            data['ESTADO COMERCIAL'] = [estado_comercial]
        if estado_activacion is not None:
            data['ESTADO DE ACTIVACIÓN ACTUAL'] = [estado_activacion]

        df = pd.DataFrame(data)
        resultado = DataFrameFormatter.clean(df)
        return str(resultado.iloc[0]['ETAPA GESTIÓN']).strip()

    # --- Prioridad 2: SIN REGISTRO gana SOLO si la matriz no definió nada ---

    def test_sin_registro_con_vigente_da_comercial(self):
        """Vigente+Conectado ya da COMERCIAL por la matriz misma (prioridad
        1): este caso no distingue entre las dos prioridades, pero confirma
        que SIN REGISTRO sigue sin romper nada cuando coincide con la
        matriz."""
        self.assertEqual(self._clean_etapa('SIN REGISTRO', 'Vigente', 'Conectado'), 'COMERCIAL')

    def test_sin_registro_no_sobreescribe_matriz_definida_activacion_pendiente(self):
        """25-09-2026: Activación Pendiente+Activando -> OPERACIONES por la
        matriz (prioridad 1); SIN REGISTRO ya no lo pisa (antes daba
        COMERCIAL)."""
        self.assertEqual(self._clean_etapa('SIN REGISTRO', 'Activacion pendiente', 'Activando'), 'OPERACIONES')

    def test_sin_registro_no_sobreescribe_matriz_definida_baja_solicitada(self):
        """25-09-2026: Baja Solicitada+Conectado -> OPERACIONES por la
        matriz (prioridad 1); SIN REGISTRO ya no lo pisa (antes daba
        COMERCIAL) -- este es justo el caso real del bug reportado
        (unidades enviadas a Baja que seguían Conectadas)."""
        self.assertEqual(self._clean_etapa('SIN REGISTRO', 'Baja Solicitada', 'Conectado'), 'OPERACIONES')

    def test_sin_registro_con_vencido_da_comercial(self):
        self.assertEqual(self._clean_etapa('SIN REGISTRO', 'Vencido', 'Conectado'), 'COMERCIAL')

    def test_sin_registro_minusculas_y_espacios_tambien_funciona(self):
        self.assertEqual(self._clean_etapa('  sin registro  ', 'Vigente', 'Conectado'), 'COMERCIAL')

    # --- Prioridad 2: FACTURACIÓN MANUAL gana SOLO si la matriz no definió nada ---

    def test_facturacion_manual_con_vigente_conectado_da_comercial(self):
        self.assertEqual(self._clean_etapa('FACTURACIÓN MANUAL', 'Vigente', 'Conectado'), 'COMERCIAL')

    # --- Prioridad 1: matriz (ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL) ---

    def test_cm_con_vigente_conectado_da_comercial(self):
        self.assertEqual(self._clean_etapa('CM', 'Vigente', 'Conectado'), 'COMERCIAL')

    def test_cm_con_vigente_no_conectado_da_operaciones(self):
        """Antes de la matriz de 2 ejes, Vigente siempre daba CLIENTE sin
        mirar el estado técnico; ahora Vigente + no-Conectado apunta a
        OPERACIONES."""
        self.assertEqual(self._clean_etapa('CM', 'Vigente', 'Activando'), 'OPERACIONES')

    def test_cm_con_activacion_pendiente_activando_da_operaciones(self):
        self.assertEqual(self._clean_etapa('CM', 'Activacion pendiente', 'Activando'), 'OPERACIONES')

    def test_cm_con_activacion_pendiente_conectado_da_comercial(self):
        self.assertEqual(self._clean_etapa('CM', 'Activacion pendiente', 'Conectado'), 'COMERCIAL')

    def test_cm_con_baja_conectado_da_operaciones(self):
        self.assertEqual(self._clean_etapa('CM', 'Baja', 'Conectado'), 'OPERACIONES')

    def test_cm_con_baja_no_conectado_da_comercial(self):
        self.assertEqual(self._clean_etapa('CM', 'Baja', 'No aplica'), 'COMERCIAL')

    def test_cm_con_vencido_da_comercial_sin_importar_activacion(self):
        self.assertEqual(self._clean_etapa('CM', 'Vencido', 'Conectado'), 'COMERCIAL')
        self.assertEqual(self._clean_etapa('CM', 'Vencido', 'Activando'), 'COMERCIAL')

    def test_provision_cliente_con_vigente_conectado_da_comercial(self):
        self.assertEqual(self._clean_etapa('PROVISION + CLIENTE', 'Vigente', 'Conectado'), 'COMERCIAL')

    def test_provision_interno_con_vigente_no_conectado_da_operaciones(self):
        self.assertEqual(self._clean_etapa('PROVISION + INTERNO', 'Vigente', 'Sin flota'), 'OPERACIONES')

    def test_tipo_facturacion_vacio_aplica_matriz_de_estado_comercial(self):
        self.assertEqual(self._clean_etapa('', 'Vigente', 'Conectado'), 'COMERCIAL')

    # --- Casos limite: no debe romper clean() ni borrar datos ---

    def test_tipo_facturacion_ausente_no_rompe_clean(self):
        self.assertEqual(
            self._clean_etapa(tipo_facturacion=None, estado_comercial='Vigente', estado_activacion='Conectado'),
            'COMERCIAL',
        )

    def test_estado_comercial_desconocido_conserva_etapa_previa(self):
        self.assertEqual(
            self._clean_etapa('CM', 'Estado Que No Existe', 'Conectado', etapa_previa='OPERACIONES'),
            'OPERACIONES',
        )

    def test_estado_activacion_desconocido_conserva_etapa_previa(self):
        self.assertEqual(
            self._clean_etapa('CM', 'Vigente', 'Estado Que No Existe', etapa_previa='OPERACIONES'),
            'OPERACIONES',
        )

    def test_estado_comercial_vacio_conserva_etapa_previa(self):
        self.assertEqual(
            self._clean_etapa('CM', '', 'Conectado', etapa_previa='COMERCIAL'),
            'COMERCIAL',
        )

    def test_estado_activacion_ausente_conserva_etapa_previa(self):
        """Columna nueva de la matriz (21-09-2026): si no llega en el
        DataFrame, clean() no debe romperse y debe conservar el valor
        previo, mismo criterio que las demás columnas de la regla."""
        self.assertEqual(
            self._clean_etapa('CM', 'Vigente', estado_activacion=None, etapa_previa='OPERACIONES'),
            'OPERACIONES',
        )


class TestBajaNoLimpiaCamposContractualesAlCargar(unittest.TestCase):
    """La regla de limpieza al elegir 'Sin Contrato' (ver
    comercial_services.aplica_regla_sin_contrato) se dispara SOLO ante la
    edición explícita del usuario en Vista Completa (comercial.py::
    on_item_edited). DataFrameFormatter.clean() -- el paso que corre en cada
    carga/sincronización -- NO debe reproducir esa limpieza de forma
    retroactiva: una fila ya en ESTADO COMERCIAL = Baja con datos
    contractuales antiguos debe conservarlos intactos con solo cargar el
    Excel, sin ninguna acción del usuario."""

    @staticmethod
    def _cargar_fila_baja():
        df = pd.DataFrame({
            'VIN': ['YV2TEST0001'],
            'CHASIS': ['TEST0001'],
            'FORMA DE CONTRATO': ['VENTA'],
            'TIPO DE SERVICIO': ['MEDIO'],
            'INICIO CONTRATO': ['2024-04-30'],
            'DURACIÓN (MESES)': [36],
            'TÉRMINO CONTRATO': [''],
            'ESTADO COMERCIAL': ['BAJA'],
        })
        return DataFrameFormatter.clean(df).iloc[0]

    def test_forma_contrato_no_se_reemplaza_por_sin_contrato(self):
        fila = self._cargar_fila_baja()
        self.assertEqual(fila['FORMA DE CONTRATO'], 'Venta')

    def test_tipo_de_servicio_conserva_su_valor(self):
        fila = self._cargar_fila_baja()
        self.assertEqual(fila['TIPO DE SERVICIO'], 'Medio')

    def test_inicio_contrato_conserva_su_valor(self):
        fila = self._cargar_fila_baja()
        self.assertEqual(fila['INICIO CONTRATO'], '30-04-2024')

    def test_duracion_meses_conserva_su_valor(self):
        fila = self._cargar_fila_baja()
        self.assertEqual(fila['DURACIÓN (MESES)'], '36')

    def test_termino_contrato_se_sigue_calculando_normalmente_no_se_borra(self):
        fila = self._cargar_fila_baja()
        self.assertEqual(fila['TÉRMINO CONTRATO'], '30-04-2027')


class TestFormaContratoProvisionMas(unittest.TestCase):
    """Actualizado (30-09-2026, a pedido explícito): la regla que forzaba
    'PROVISION +' a DURACIÓN (MESES)='-' / TÉRMINO CONTRATO='MENSUAL' sin
    excepción se desactivó (ver dataframe_formatter.py). RM_JAVI siempre trae
    una fecha real de término para estas filas; la regla la sobrescribía y
    ocultaba contratos ya caducados (391 de 561 filas reales al momento de
    desactivarla). 'PROVISION +' ahora sigue exactamente la misma regla
    general de DURACIÓN/TÉRMINO que cualquier otro valor de FORMA DE
    CONTRATO (ver TestFormaContratoProvisionMas vs. 'PROVISION' sin '+' y
    'VENTA' más abajo: mismo resultado en los tres casos)."""

    @staticmethod
    def _cargar_fila(forma_contrato, duracion='12', termino_previo='15-03-2027'):
        df = pd.DataFrame({
            'VIN': ['YV2TEST0001'],
            'CHASIS': ['TEST0001'],
            'FORMA DE CONTRATO': [forma_contrato],
            'INICIO CONTRATO': [datetime(2026, 6, 1)],
            'DURACIÓN (MESES)': [duracion],
            'TÉRMINO CONTRATO': [termino_previo],
        })
        return DataFrameFormatter.clean(df).iloc[0]

    def test_provision_mas_ya_no_fuerza_duracion_guion(self):
        fila = self._cargar_fila('PROVISION +', duracion='12', termino_previo='')
        self.assertEqual(str(fila['DURACIÓN (MESES)']).strip(), '12')

    def test_provision_mas_ya_no_fuerza_termino_mensual(self):
        fila = self._cargar_fila('PROVISION +', duracion='12', termino_previo='')
        self.assertEqual(str(fila['TÉRMINO CONTRATO']).strip(), '01-06-2027')

    def test_provision_mas_minusculas_sigue_la_regla_general(self):
        fila = self._cargar_fila('provision + cliente', duracion='12', termino_previo='')
        self.assertEqual(str(fila['DURACIÓN (MESES)']).strip(), '12')
        self.assertEqual(str(fila['TÉRMINO CONTRATO']).strip(), '01-06-2027')

    def test_provision_mas_con_guion_guion_queda_no_informado(self):
        # Ya no hay sobrescritura especial: '-'/'-' es el mismo caso "dato
        # aún no informado" que aplica a cualquier FORMA DE CONTRATO (ver
        # test_duracion_guion_con_termino_guion_no_informado_queda_guion).
        fila = self._cargar_fila('PROVISION +', duracion='-', termino_previo='-')
        self.assertEqual(str(fila['DURACIÓN (MESES)']).strip(), '-')
        self.assertEqual(str(fila['TÉRMINO CONTRATO']).strip(), '-')

    def test_provision_sin_mas_mismo_resultado_que_provision_mas(self):
        # FORMA DE CONTRATO='PROVISION' (sin '+') es un valor de catálogo
        # distinto, pero ya no hay ninguna regla especial que lo diferencie
        # de 'PROVISION +' en DURACIÓN/TÉRMINO.
        fila = self._cargar_fila('PROVISION', duracion='12', termino_previo='')
        self.assertEqual(str(fila['DURACIÓN (MESES)']).strip(), '12')
        self.assertEqual(str(fila['TÉRMINO CONTRATO']).strip(), '01-06-2027')

    def test_provision_sin_mas_con_duracion_guion_sigue_siendo_mensual(self):
        # Control: la regla general de duración (no la especial de
        # 'PROVISION +', que ya no existe) sigue vigente para todos.
        fila = self._cargar_fila('PROVISION', duracion='-', termino_previo='15-03-2027')
        self.assertEqual(str(fila['DURACIÓN (MESES)']).strip(), '-')
        self.assertEqual(str(fila['TÉRMINO CONTRATO']).strip(), 'MENSUAL')

    def test_otra_forma_contrato_mismo_resultado(self):
        fila = self._cargar_fila('VENTA', duracion='12', termino_previo='')
        self.assertEqual(str(fila['DURACIÓN (MESES)']).strip(), '12')
        self.assertEqual(str(fila['TÉRMINO CONTRATO']).strip(), '01-06-2027')


class TestNormalizaEstadoDelCm(unittest.TestCase):
    """DataFrameFormatter.clean() debe normalizar ESTADO DEL CM a un unico
    formato (Running/Expired/Terminated), sin importar si el dato llego en
    mayusculas (import 3PC) o mezclado a mano -- mismo patron que
    TIPO_SERVICIO_MAP/FORMA_CONTRATO_MAP/ESTADO_COMERCIAL_MAP (ver
    ESTADO_DEL_CM_MAP en constants.py). Se aplica en cada carga/sync, asi
    que corre igual para Comercial (Vista Completa) y para Contratos CM,
    sin duplicar la logica en cada pantalla."""

    @staticmethod
    def _cargar_fila(estado_cm):
        df = pd.DataFrame({
            'VIN': ['YV2TEST0001'],
            'CHASIS': ['TEST0001'],
            'ESTADO DEL CM': [estado_cm],
        })
        return DataFrameFormatter.clean(df).iloc[0]

    def test_running_todo_mayusculas_se_normaliza(self):
        self.assertEqual(self._cargar_fila('RUNNING')['ESTADO DEL CM'], 'Running')

    def test_expired_todo_mayusculas_se_normaliza(self):
        self.assertEqual(self._cargar_fila('EXPIRED')['ESTADO DEL CM'], 'Expired')

    def test_terminated_todo_mayusculas_se_normaliza(self):
        self.assertEqual(self._cargar_fila('TERMINATED')['ESTADO DEL CM'], 'Terminated')

    def test_ya_normalizado_se_conserva_igual(self):
        self.assertEqual(self._cargar_fila('Running')['ESTADO DEL CM'], 'Running')

    def test_valor_no_reconocido_se_conserva_sin_modificar(self):
        self.assertEqual(self._cargar_fila('-')['ESTADO DEL CM'], '-')

    def test_expirado_en_espanol_se_normaliza_a_expired(self):
        """Dato real detectado en PruebasFM (12 filas, 11-09-2026): alguien
        escribio 'Expirado' directamente en Excel, fuera del desplegable de
        la app. Sin este alias quedaba 'intacto' y por lo tanto invisible
        para cm_bajas_service.detectar_casos_expired_actuales()."""
        self.assertEqual(self._cargar_fila('Expirado')['ESTADO DEL CM'], 'Expired')
        self.assertEqual(self._cargar_fila('EXPIRADO')['ESTADO DEL CM'], 'Expired')


if __name__ == '__main__':
    unittest.main()
