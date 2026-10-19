import unittest
from datetime import datetime, timedelta

import pandas as pd

from src.services.comercial_services import (
    procesar_df_comercial, calcular_kpis_vigencia, validar_valor_pegado, quitar_vin, agregar_fila,
    aplicar_cambios_pendientes, validar_duracion, validar_fecha_ddmmyyyy, parsear_pago_cm, formatear_pago_cm,
    detectar_contradicciones_etapa_gestion, aplica_regla_sin_contrato, COLUMNAS_LIMPIEZA_SIN_CONTRATO,
    aplica_regla_terminated_cm, COLUMNAS_LIMPIEZA_TERMINATED_CM,
    clasificar_vigencia_contrato, filtrar_renovaciones, filtrar_vencimientos, filtrar_gestionar_bajas,
    filtrar_por_gestionar, filtrar_vigentes, construir_mascara_busqueda, formatear_dias_restantes,
    parsear_dias_restantes, _calcular_etapa_gestion_esperada_vectorizado,
    detectar_inconsistencias_forma_contrato_tipo_facturacion,
    contar_forma_contrato_sin_tipo_facturacion_asignado,
    normalizar_tipo_facturacion_por_forma_contrato,
)
from src.core.dataframe_formatter import DataFrameFormatter


class TestProcesarDfComercial(unittest.TestCase):
    """Extraccion literal de ComercialModule._procesar_df_base(): funcion
    pura, sin PyQt/QThread/DataManager."""

    def test_cdb_formato_punto_cero(self):
        df = pd.DataFrame({'CDB': ['12345.0']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.iloc[0]['CDB'], '12345')

    def test_duracion_vacia(self):
        df = pd.DataFrame({'DURACIÓN (MESES)': ['']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.iloc[0]['DURACIÓN (MESES)'], '')

    def test_duracion_guion(self):
        df = pd.DataFrame({'DURACIÓN (MESES)': ['-'], 'TÉRMINO CONTRATO': ['15-03-2027']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.iloc[0]['DURACIÓN (MESES)'], '-')
        self.assertEqual(resultado.iloc[0]['TÉRMINO CONTRATO'], 'MENSUAL')

    def test_duracion_guion_con_termino_guion_no_informado_queda_guion(self):
        # VIN nuevo en RM_CONTRATOS: '-' / '-' significa dato aun no informado,
        # no mensual (misma regla que DataFrameFormatter.calcular_termino).
        df = pd.DataFrame({'DURACIÓN (MESES)': ['-'], 'TÉRMINO CONTRATO': ['-']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.iloc[0]['DURACIÓN (MESES)'], '-')
        self.assertEqual(resultado.iloc[0]['TÉRMINO CONTRATO'], '-')

    def test_duracion_guion_con_termino_mensual_explicito(self):
        df = pd.DataFrame({'DURACIÓN (MESES)': ['-'], 'TÉRMINO CONTRATO': ['MENSUAL']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.iloc[0]['DURACIÓN (MESES)'], '-')
        self.assertEqual(resultado.iloc[0]['TÉRMINO CONTRATO'], 'MENSUAL')

    def test_duracion_mensual(self):
        df = pd.DataFrame({'DURACIÓN (MESES)': ['MENSUAL'], 'TÉRMINO CONTRATO': ['15-03-2027']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.iloc[0]['DURACIÓN (MESES)'], 'MENSUAL')
        self.assertEqual(resultado.iloc[0]['TÉRMINO CONTRATO'], 'MENSUAL')

    def test_duracion_numerica(self):
        df = pd.DataFrame({'DURACIÓN (MESES)': [24.0], 'TÉRMINO CONTRATO': ['15-03-2027']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.iloc[0]['DURACIÓN (MESES)'], '24')
        # No es '-'/'MENSUAL': TÉRMINO CONTRATO no debe forzarse a 'MENSUAL'.
        self.assertEqual(resultado.iloc[0]['TÉRMINO CONTRATO'], '15-03-2027')

    def test_sin_columna_pago_cm(self):
        df = pd.DataFrame({'VIN': ['YV2TEST0001']})
        resultado = procesar_df_comercial(df)
        self.assertIn('PAGO CM_NUM', resultado.columns)
        self.assertEqual(resultado.iloc[0]['PAGO CM_NUM'], 0)

    def test_con_columna_pago_cm(self):
        df = pd.DataFrame({'PAGO CM': [1500.5, 'nan']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.iloc[0]['PAGO CM_NUM'], 1500.5)
        self.assertEqual(resultado.iloc[1]['PAGO CM_NUM'], 0)

    def test_agrega_columna_numero_al_inicio(self):
        df = pd.DataFrame({'VIN': ['YV2TEST0001']})
        resultado = procesar_df_comercial(df)
        self.assertEqual(resultado.columns[0], 'N°')
        self.assertEqual(resultado.iloc[0]['N°'], "")

    def test_df_vacio_se_retorna_igual(self):
        df = pd.DataFrame()
        resultado = procesar_df_comercial(df)
        self.assertTrue(resultado.empty)


class TestCalcularKpisVigencia(unittest.TestCase):
    """Extraccion literal del bloque de conteo de KPIs duplicado en
    ComercialModule.load_data() y _on_save_finished(). Funcion pura."""

    @staticmethod
    def _fecha(dias_desde_hoy):
        return (datetime.now().date() + timedelta(days=dias_desde_hoy)).strftime('%d-%m-%Y')

    def test_contrato_vencido(self):
        df = pd.DataFrame({'TÉRMINO CONTRATO': [self._fecha(-10)]})
        kpis = calcular_kpis_vigencia(df)
        self.assertEqual(kpis['vencidas'], 1)
        self.assertEqual(kpis['activas'], 0)
        self.assertEqual(kpis['xvencer'], 0)
        self.assertEqual(kpis['total'], 1)

    def test_contrato_activo_lejos_de_vencer(self):
        df = pd.DataFrame({'TÉRMINO CONTRATO': [self._fecha(365)]})
        kpis = calcular_kpis_vigencia(df)
        self.assertEqual(kpis['vencidas'], 0)
        self.assertEqual(kpis['activas'], 1)
        self.assertEqual(kpis['xvencer'], 0)

    def test_contrato_por_vencer_dentro_de_30_dias(self):
        df = pd.DataFrame({'TÉRMINO CONTRATO': [self._fecha(15)]})
        kpis = calcular_kpis_vigencia(df)
        self.assertEqual(kpis['vencidas'], 0)
        self.assertEqual(kpis['activas'], 1, "Un contrato por vencer sigue contando como activo (no excluyente).")
        self.assertEqual(kpis['xvencer'], 1)

    def test_contrato_mensual_siempre_activo_nunca_vencido(self):
        df = pd.DataFrame({'TÉRMINO CONTRATO': ['MENSUAL']})
        kpis = calcular_kpis_vigencia(df)
        self.assertEqual(kpis['vencidas'], 0)
        self.assertEqual(kpis['activas'], 1)
        self.assertEqual(kpis['xvencer'], 0)

    def test_combinacion_de_todos_los_casos(self):
        df = pd.DataFrame({'TÉRMINO CONTRATO': [
            self._fecha(-5),   # vencida
            self._fecha(500),  # activa, lejos
            self._fecha(10),   # activa + por vencer
            'MENSUAL',         # activa (mensual)
        ]})
        kpis = calcular_kpis_vigencia(df)
        self.assertEqual(kpis['total'], 4)
        self.assertEqual(kpis['vencidas'], 1)
        self.assertEqual(kpis['activas'], 3)
        self.assertEqual(kpis['xvencer'], 1)


class TestClasificarVigenciaContratoCalendario(unittest.TestCase):
    """Regla confirmada con la contraparte comercial: Renovaciones (y el KPI 'xvencer') se
    calculan en dias CALENDARIO, no habiles. Cubre los 5 casos limite
    explicitos: vencido, vence hoy, vence en 1 dia, vence en exactamente 30
    dias (incluido) y vence en 31 dias (excluido)."""

    @staticmethod
    def _fecha(dias_desde_hoy):
        return (datetime.now().date() + timedelta(days=dias_desde_hoy)).strftime('%d-%m-%Y')

    def _clasif_una_fila(self, dias_desde_hoy):
        df = pd.DataFrame({'TÉRMINO CONTRATO': [self._fecha(dias_desde_hoy)]})
        return clasificar_vigencia_contrato(df).iloc[0]

    def test_vencido_es_renovacion(self):
        fila = self._clasif_una_fila(-1)
        self.assertTrue(fila['vencido'])
        self.assertTrue(fila['es_renovacion'])

    def test_vence_hoy_es_renovacion(self):
        fila = self._clasif_una_fila(0)
        self.assertFalse(fila['vencido'])
        self.assertEqual(fila['dias_restantes'], 0)
        self.assertTrue(fila['por_vencer'])
        self.assertTrue(fila['es_renovacion'])

    def test_vence_en_1_dia_es_renovacion(self):
        fila = self._clasif_una_fila(1)
        self.assertTrue(fila['por_vencer'])
        self.assertTrue(fila['es_renovacion'])

    def test_vence_en_exactamente_30_dias_es_renovacion(self):
        fila = self._clasif_una_fila(30)
        self.assertEqual(fila['dias_restantes'], 30)
        self.assertTrue(fila['por_vencer'], "Fallo: el borde de 30 dias debe ser inclusive.")
        self.assertTrue(fila['es_renovacion'])

    def test_vence_en_31_dias_no_es_renovacion(self):
        fila = self._clasif_una_fila(31)
        self.assertFalse(fila['por_vencer'])
        self.assertFalse(fila['es_renovacion'])

    def test_dias_restantes_es_calendario_no_habil(self):
        # 30 dias calendario exactos, sin importar cuantos fines de semana
        # caigan en el medio: dias_restantes debe dar siempre 30, nunca un
        # valor reducido por conteo de dias habiles.
        fila = self._clasif_una_fila(30)
        self.assertEqual(fila['dias_restantes'], 30)

    def test_activa_lejos_de_vencer_no_es_renovacion(self):
        fila = self._clasif_una_fila(365)
        self.assertFalse(fila['vencido'])
        self.assertFalse(fila['por_vencer'])
        self.assertFalse(fila['es_renovacion'])

    def test_mensual_nunca_es_renovacion(self):
        df = pd.DataFrame({'TÉRMINO CONTRATO': ['MENSUAL']})
        fila = clasificar_vigencia_contrato(df).iloc[0]
        self.assertTrue(fila['activo'])
        self.assertFalse(fila['es_renovacion'])


class TestFormatearDiasRestantes(unittest.TestCase):
    """formatear_dias_restantes() solo formatea el valor numerico que ya
    entrega clasificar_vigencia_contrato()['dias_restantes']; no debe
    recalcular fechas ni cambiar la logica de calendario existente."""

    def test_positivo_indica_dias_restantes(self):
        self.assertEqual(formatear_dias_restantes(10), "10 días restantes")
        self.assertEqual(formatear_dias_restantes(1), "1 días restantes")

    def test_cero_indica_vence_hoy(self):
        self.assertEqual(formatear_dias_restantes(0), "Vence hoy")

    def test_negativo_indica_vencido_hace_n_dias(self):
        self.assertEqual(formatear_dias_restantes(-3), "Vencido hace 3 días")

    def test_nan_indica_guion(self):
        self.assertEqual(formatear_dias_restantes(float('nan')), "-")


class TestParsearDiasRestantes(unittest.TestCase):
    """parsear_dias_restantes() es el inverso de formatear_dias_restantes():
    lo usa AppTableWidget._parse_number_like (custom_table.py) para poder
    ordenar 'DÍAS RESTANTES' por magnitud numérica en vez de alfabéticamente
    (bug reportado: ordenar esa columna no reordenaba nada)."""

    def test_roundtrip_con_formatear_dias_restantes(self):
        for dias in (-496, -45, -1, 0, 1, 10, 365):
            texto = formatear_dias_restantes(dias)
            self.assertEqual(parsear_dias_restantes(texto), float(dias))

    def test_vencido_hace_n_dias_da_numero_negativo(self):
        self.assertEqual(parsear_dias_restantes("Vencido hace 45 días"), -45.0)

    def test_vence_hoy_da_cero(self):
        self.assertEqual(parsear_dias_restantes("Vence hoy"), 0.0)

    def test_n_dias_restantes_da_numero_positivo(self):
        self.assertEqual(parsear_dias_restantes("10 días restantes"), 10.0)

    def test_texto_no_reconocido_da_none(self):
        self.assertIsNone(parsear_dias_restantes("-"))
        self.assertIsNone(parsear_dias_restantes("EMPRESA PRUEBA S.A."))

    def test_reutiliza_clasificar_vigencia_contrato_sin_reimplementar_calendario(self):
        hoy = pd.Timestamp(datetime.now().date())
        df = pd.DataFrame({'TÉRMINO CONTRATO': [
            (hoy - timedelta(days=3)).strftime('%d-%m-%Y'),
            hoy.strftime('%d-%m-%Y'),
            (hoy + timedelta(days=10)).strftime('%d-%m-%Y'),
        ]})
        clasif = clasificar_vigencia_contrato(df, hoy=hoy)
        resultados = clasif['dias_restantes'].apply(formatear_dias_restantes).tolist()
        self.assertEqual(resultados, ["Vencido hace 3 días", "Vence hoy", "10 días restantes"])


class TestFiltrarRenovaciones(unittest.TestCase):
    """filtrar_renovaciones() (regla actualizada 28-09-2026, a pedido
    explícito): solo unidades por vencer dentro de 30 días calendario
    (incluyendo el mismo día, las ya vencidas quedan fuera -- van a
    "Vencidos"), con ESTADO COMERCIAL en (VIGENTE, REVISAR) y ESTADO DE
    ACTIVACIÓN ACTUAL = CONECTADO. Usa exclusivamente TÉRMINO CONTRATO (no
    FECHA TERMINO CM, que es un concepto de fecha distinto -- termino del
    contrato CM, no del contrato del cliente)."""

    @staticmethod
    def _fecha(dias_desde_hoy):
        return (datetime.now().date() + timedelta(days=dias_desde_hoy)).strftime('%d-%m-%Y')

    def _df(self, dias_desde_hoy, estado_comercial='Vigente', estado_activacion='Conectado', vin='V1'):
        return pd.DataFrame({
            'VIN': [vin],
            'TÉRMINO CONTRATO': [self._fecha(dias_desde_hoy)],
            'ESTADO COMERCIAL': [estado_comercial],
            'ESTADO DE ACTIVACIÓN ACTUAL': [estado_activacion],
        })

    def test_excluye_ya_vencido(self):
        resultado = filtrar_renovaciones(self._df(-10))
        self.assertTrue(resultado.empty, "Fallo: un contrato ya vencido debe ir a \"Vencidos\", no a Renovaciones.")

    def test_incluye_vence_hoy(self):
        resultado = filtrar_renovaciones(self._df(0))
        self.assertEqual(resultado['VIN'].tolist(), ['V1'])

    def test_incluye_dentro_de_30_dias(self):
        resultado = filtrar_renovaciones(self._df(15))
        self.assertEqual(resultado['VIN'].tolist(), ['V1'])

    def test_excluye_mas_de_30_dias(self):
        resultado = filtrar_renovaciones(self._df(31))
        self.assertTrue(resultado.empty)

    def test_excluye_mensual(self):
        df = self._df(15)
        df['TÉRMINO CONTRATO'] = 'MENSUAL'
        resultado = filtrar_renovaciones(df)
        self.assertTrue(resultado.empty)

    def test_no_usa_fecha_termino_cm(self):
        # TÉRMINO CONTRATO por vencer; FECHA TERMINO CM ya vencida. El
        # resultado debe depender solo de TÉRMINO CONTRATO.
        df = self._df(15)
        df['FECHA TERMINO CM'] = [self._fecha(-500)]
        resultado = filtrar_renovaciones(df)
        self.assertEqual(resultado['VIN'].tolist(), ['V1'], "Fallo: filtrar_renovaciones no debe fijarse en FECHA TERMINO CM.")

    def test_df_vacio_no_revienta(self):
        df = pd.DataFrame({'VIN': [], 'TÉRMINO CONTRATO': []})
        resultado = filtrar_renovaciones(df)
        self.assertTrue(resultado.empty)

    def test_sin_columna_termino_contrato_no_revienta(self):
        df = pd.DataFrame({'VIN': ['V1']})
        resultado = filtrar_renovaciones(df)
        self.assertTrue(resultado.empty)

    def test_excluye_no_conectado(self):
        df = pd.DataFrame({
            'VIN': ['CONECTADO', 'ACTIVANDO', 'DESCONECTADO'],
            'TÉRMINO CONTRATO': [self._fecha(15), self._fecha(15), self._fecha(15)],
            'ESTADO COMERCIAL': ['Vigente', 'Vigente', 'Vigente'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado', 'ACTIVANDO', 'Desconectado'],
        })
        resultado = filtrar_renovaciones(df)
        self.assertEqual(resultado['VIN'].tolist(), ['CONECTADO'])

    def test_sin_columna_estado_activacion_no_revienta(self):
        df = pd.DataFrame({
            'VIN': ['V1'],
            'TÉRMINO CONTRATO': [self._fecha(15)],
            'ESTADO COMERCIAL': ['Vigente'],
        })
        resultado = filtrar_renovaciones(df)
        self.assertEqual(resultado['VIN'].tolist(), ['V1'])

    def test_sin_columna_estado_comercial_no_revienta(self):
        df = pd.DataFrame({
            'VIN': ['V1'],
            'TÉRMINO CONTRATO': [self._fecha(15)],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado'],
        })
        resultado = filtrar_renovaciones(df)
        self.assertEqual(resultado['VIN'].tolist(), ['V1'])

    def test_incluye_vigente_y_excluye_revisar_y_el_resto(self):
        # Desde el 08-10-2026 Revisar va siempre a Nuevas oportunidades (matriz de destino).
        df = pd.DataFrame({
            'VIN': ['VIGENTE', 'REVISAR', 'BAJA', 'ACTIVACION_PENDIENTE'],
            'TÉRMINO CONTRATO': [self._fecha(15)] * 4,
            'ESTADO COMERCIAL': ['Vigente', 'Revisar', 'Baja', 'Activación Pendiente'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado'] * 4,
        })
        resultado = filtrar_renovaciones(df)
        self.assertEqual(sorted(resultado['VIN'].tolist()), ['VIGENTE'])


class TestFiltrarVencimientos(unittest.TestCase):
    """Panel Comercial -> Vencimientos (legado; ya no tiene sub-pestaña
    propia en la Nueva interfaz desde el 14-09-2026, ver "Renovaciones").
    Hoy delega en filtrar_renovaciones, así que hereda su regla actualizada
    (28-09-2026): solo por vencer dentro de 30 días (incluyendo hoy),
    ESTADO COMERCIAL en (VIGENTE, REVISAR) y CONECTADO. Los ya vencidos ya
    NO entran (van a "Vencidos")."""

    @staticmethod
    def _fecha(dias_desde_hoy):
        return (datetime.now().date() + timedelta(days=dias_desde_hoy)).strftime('%d-%m-%Y')

    def test_excluye_mensual_vencido_y_mas_de_30_dias(self):
        df = pd.DataFrame({
            'VIN': ['VENCIDO', 'POR_VENCER', 'LEJOS', 'MENSUAL'],
            'TÉRMINO CONTRATO': [self._fecha(-10), self._fecha(15), self._fecha(500), 'MENSUAL'],
            'ESTADO COMERCIAL': ['Vigente'] * 4,
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado'] * 4,
        })
        resultado = filtrar_vencimientos(df)
        self.assertEqual(resultado['VIN'].tolist(), ['POR_VENCER'])

    def test_excluye_ya_vencidos_sin_importar_antiguedad(self):
        df = pd.DataFrame({
            'VIN': ['RECIENTE', 'ANTIGUO'],
            'TÉRMINO CONTRATO': [self._fecha(-1), self._fecha(-496)],
            'ESTADO COMERCIAL': ['Vigente', 'Vigente'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado', 'Conectado'],
        })
        resultado = filtrar_vencimientos(df)
        self.assertTrue(resultado.empty, "Fallo: un contrato ya vencido debe ir a \"Vencidos\", no a Vencimientos.")


class TestFiltrarGestionarBajas(unittest.TestCase):
    """Regla ampliada (24-09-2026, pedido explícito del usuario): ESTADO
    COMERCIAL en (BAJA, BAJA SOLICITADA) -- antes solo tomaba 'BAJA' exacto
    y Baja Solicitada quedaba sin pestaña propia en Comercial."""

    def test_incluye_baja_y_baja_solicitada(self):
        df = pd.DataFrame({
            'VIN': ['V1', 'V2', 'V3', 'V4', 'V5'],
            'ESTADO COMERCIAL': ['BAJA', 'BAJA SOLICITADA', 'VIGENTE', 'VENCIDO', 'REVISAR'],
        })
        resultado = filtrar_gestionar_bajas(df)
        self.assertEqual(sorted(resultado['VIN'].tolist()), ['V1', 'V2'])

    def test_es_insensible_a_mayusculas_y_espacios(self):
        df = pd.DataFrame({'VIN': ['V1', 'V2'], 'ESTADO COMERCIAL': ['Baja', '  baja  ']})
        resultado = filtrar_gestionar_bajas(df)
        self.assertEqual(sorted(resultado['VIN'].tolist()), ['V1', 'V2'])

    def test_df_vacio_no_revienta(self):
        df = pd.DataFrame({'VIN': [], 'ESTADO COMERCIAL': []})
        self.assertTrue(filtrar_gestionar_bajas(df).empty)

    def test_sin_columna_no_revienta(self):
        df = pd.DataFrame({'VIN': ['V1']})
        self.assertTrue(filtrar_gestionar_bajas(df).empty)


class TestFiltrarPorGestionar(unittest.TestCase):
    """Regla confirmada con la contraparte comercial: ESTADO DE ACTIVACIÓN ACTUAL == 'NO
    APLICA', igualdad exacta. No debe confundirse con otros estados
    operacionales similares."""

    def test_incluye_solo_no_aplica_exacto(self):
        df = pd.DataFrame({
            'VIN': ['V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7'],
            'ESTADO DE ACTIVACIÓN ACTUAL': [
                'NO APLICA', 'ACTIVACION PENDIENTE', 'SIN FLOTA', 'NO ENTREGADO',
                'ACTIVANDO', 'CONECTADO', 'DESCONECTADO',
            ],
        })
        resultado = filtrar_por_gestionar(df)
        self.assertEqual(resultado['VIN'].tolist(), ['V1'])

    def test_df_vacio_no_revienta(self):
        df = pd.DataFrame({'VIN': [], 'ESTADO DE ACTIVACIÓN ACTUAL': []})
        self.assertTrue(filtrar_por_gestionar(df).empty)


class TestFiltrarVigentes(unittest.TestCase):
    """Regla confirmada con el usuario (21-09-2026): ESTADO COMERCIAL ==
    'VIGENTE', igualdad exacta -- cierre del flujo Comercial -> Operaciones
    -> Comercial para unidades nuevas (ver operaciones.py 'Marcar como
    CONECTADO' y la transición automática a Vigente)."""

    def test_incluye_solo_vigente_exacto(self):
        df = pd.DataFrame({
            'VIN': ['V1', 'V2', 'V3', 'V4'],
            'ESTADO COMERCIAL': ['VIGENTE', 'VENCIDO', 'BAJA', 'REVISAR'],
        })
        resultado = filtrar_vigentes(df)
        self.assertEqual(resultado['VIN'].tolist(), ['V1'])

    def test_es_insensible_a_mayusculas_y_espacios(self):
        df = pd.DataFrame({'VIN': ['V1', 'V2'], 'ESTADO COMERCIAL': ['Vigente', '  vigente  ']})
        resultado = filtrar_vigentes(df)
        self.assertEqual(sorted(resultado['VIN'].tolist()), ['V1', 'V2'])

    def test_df_vacio_no_revienta(self):
        df = pd.DataFrame({'VIN': [], 'ESTADO COMERCIAL': []})
        self.assertTrue(filtrar_vigentes(df).empty)

    def test_sin_columna_no_revienta(self):
        df = pd.DataFrame({'VIN': ['V1']})
        self.assertTrue(filtrar_por_gestionar(df).empty)


class TestConstruirMascaraBusqueda(unittest.TestCase):
    """Regresion del bug real: pegar listas grandes de VINs en la busqueda
    global congelaba la app (ver main_window.MultiSearchLineEdit). Esta
    version resuelve los terminos de una sola palabra (el caso de pegar una
    lista de VINs) con una unica regex por columna en vez de un
    `.str.contains()` por termino, preservando la misma semantica OR/AND que
    la implementacion anterior."""

    def _df(self):
        return pd.DataFrame({
            'VIN': ['YV2AAA111', 'YV2BBB222', 'YV2CCC333'],
            'CHASIS': ['A111', 'B222', 'C333'],
            'FLOTA VC': ['EMPRESA UNO', 'EMPRESA DOS', 'EMPRESA TRES'],
            'FLOTA VC 2': ['-', '-', '-'],
            'CDB': ['1001', '1002', '1003'],
            'RAZÓN SOCIAL': ['EMPRESA UNO SA', 'EMPRESA DOS SA', 'EMPRESA TRES SA'],
        })

    def _cols(self):
        return ['VIN', 'CHASIS', 'FLOTA VC', 'FLOTA VC 2', 'CDB', 'RAZÓN SOCIAL']

    def test_or_simple_de_un_solo_vin(self):
        df = self._df()
        mask = construir_mascara_busqueda(df, 'yv2bbb222', self._cols())
        self.assertEqual(df[mask]['VIN'].tolist(), ['YV2BBB222'])

    def test_or_de_multiples_vins_pegados(self):
        df = self._df()
        mask = construir_mascara_busqueda(df, 'yv2aaa111, yv2ccc333', self._cols())
        self.assertEqual(sorted(df[mask]['VIN'].tolist()), ['YV2AAA111', 'YV2CCC333'])

    def test_lista_grande_de_vins_no_existentes_no_rompe_ni_matchea(self):
        df = self._df()
        vins_falsos = ', '.join(f'vin{i:05d}' for i in range(2000))
        mask = construir_mascara_busqueda(df, vins_falsos, self._cols())
        self.assertFalse(mask.any())

    def test_and_dentro_de_un_termino(self):
        df = self._df()
        # "empresa uno" exige ambas palabras en la misma fila.
        mask = construir_mascara_busqueda(df, 'empresa uno', self._cols())
        self.assertEqual(df[mask]['VIN'].tolist(), ['YV2AAA111'])

    def test_and_no_matchea_si_falta_una_palabra(self):
        df = self._df()
        mask = construir_mascara_busqueda(df, 'empresa inexistente', self._cols())
        self.assertFalse(mask.any())

    def test_combinacion_or_de_terminos_simples_y_compuestos(self):
        df = self._df()
        mask = construir_mascara_busqueda(df, 'yv2ccc333, empresa uno', self._cols())
        self.assertEqual(sorted(df[mask]['VIN'].tolist()), ['YV2AAA111', 'YV2CCC333'])

    def test_busqueda_vacia_no_matchea_nada(self):
        df = self._df()
        mask = construir_mascara_busqueda(df, '', self._cols())
        self.assertFalse(mask.any())

    def test_terminos_con_caracteres_especiales_de_regex_no_revientan(self):
        df = pd.DataFrame({'VIN': ['A.B+C']})
        mask = construir_mascara_busqueda(df, 'a.b+c', ['VIN'])
        self.assertTrue(mask.iloc[0], "Fallo: el termino debe tratarse como texto literal, no como regex.")

    def test_columna_inexistente_se_ignora_sin_reventar(self):
        df = self._df()
        mask = construir_mascara_busqueda(df, 'yv2aaa111', self._cols() + ['COLUMNA_QUE_NO_EXISTE'])
        self.assertEqual(df[mask]['VIN'].tolist(), ['YV2AAA111'])


class TestValidarValorPegado(unittest.TestCase):
    """Extraccion literal de la validacion de
    ComercialModule.paste_dropdown_value_to_selection(). Funcion pura, sin
    acceso al portapapeles ni QMessageBox."""

    DROPDOWN_OPTIONS = {
        'ESTADO COMERCIAL': ["Vigente", "Vencido", "Baja", "Baja Solicitada", "Revisar"],
        'MODELO': ["FH", "FHE", "FHL", "FM", "FME", "FML", "FMX", "N/A", "VM"],
    }

    def test_columna_sin_opciones_configuradas(self):
        resultado, valor = validar_valor_pegado('VIN', 'algo', self.DROPDOWN_OPTIONS)
        self.assertEqual(resultado, "sin_opciones")
        self.assertIsNone(valor)

    def test_valor_valido_normaliza_capitalizacion(self):
        resultado, valor = validar_valor_pegado('ESTADO COMERCIAL', 'vigente', self.DROPDOWN_OPTIONS)
        self.assertEqual(resultado, "valido")
        self.assertEqual(valor, 'Vigente')

    def test_valor_invalido_devuelve_mensaje_con_opciones(self):
        resultado, mensaje = validar_valor_pegado('MODELO', 'CAMION_INEXISTENTE', self.DROPDOWN_OPTIONS)
        self.assertEqual(resultado, "invalido")
        self.assertIn('CAMION_INEXISTENTE', mensaje)
        self.assertIn('MODELO', mensaje)
        for opcion in self.DROPDOWN_OPTIONS['MODELO']:
            self.assertIn(opcion, mensaje)

    def test_valor_valido_en_otra_columna(self):
        resultado, valor = validar_valor_pegado('MODELO', 'fmx', self.DROPDOWN_OPTIONS)
        self.assertEqual(resultado, "valido")
        self.assertEqual(valor, 'FMX')


class TestValidarDuracion(unittest.TestCase):
    """Extraccion literal de la validacion de DURACION (MESES) en
    ComercialModule.on_item_edited()."""

    def test_vacio(self):
        self.assertEqual(validar_duracion(""), ("vacio", ""))

    def test_nan(self):
        self.assertEqual(validar_duracion("nan"), ("vacio", ""))
        self.assertEqual(validar_duracion("NaN"), ("vacio", ""))

    def test_guion(self):
        self.assertEqual(validar_duracion("-"), ("mensual", "-"))

    def test_mensual_mayusculas_y_minusculas(self):
        self.assertEqual(validar_duracion("MENSUAL"), ("mensual", "-"))
        self.assertEqual(validar_duracion("mensual"), ("mensual", "-"))

    def test_entero_positivo(self):
        self.assertEqual(validar_duracion("24"), ("numerico", "24"))

    def test_decimal_positivo_se_trunca(self):
        self.assertEqual(validar_duracion("2.5"), ("numerico", "2"))

    def test_cero_es_invalido(self):
        resultado, valor = validar_duracion("0")
        self.assertEqual(resultado, "invalido")
        self.assertIn("mayor a 0", valor)

    def test_negativo_es_invalido(self):
        resultado, valor = validar_duracion("-5")
        self.assertEqual(resultado, "invalido")

    def test_texto_invalido(self):
        resultado, valor = validar_duracion("abc")
        self.assertEqual(resultado, "invalido")

    def test_espacios_se_normalizan(self):
        self.assertEqual(validar_duracion("  24  "), ("numerico", "24"))
        self.assertEqual(validar_duracion("  -  "), ("mensual", "-"))
        self.assertEqual(validar_duracion("   "), ("vacio", ""))


class TestValidarFechaDdmmyyyy(unittest.TestCase):
    """Extraccion literal de la validacion de fecha en
    ComercialModule.on_item_edited()."""

    def test_fecha_valida(self):
        self.assertEqual(validar_fecha_ddmmyyyy("10-10-2026"), ("valido", "10-10-2026"))

    def test_fecha_valida_con_espacios(self):
        self.assertEqual(validar_fecha_ddmmyyyy("  10-10-2026  "), ("valido", "10-10-2026"))

    def test_vacio(self):
        self.assertEqual(validar_fecha_ddmmyyyy(""), ("vacio", ""))

    def test_nan(self):
        self.assertEqual(validar_fecha_ddmmyyyy("nan"), ("vacio", ""))

    def test_formato_incorrecto_slash(self):
        resultado, valor = validar_fecha_ddmmyyyy("10/10/2026")
        self.assertEqual(resultado, "invalido")
        self.assertIn("DD-MM-YYYY", valor)

    def test_formato_incorrecto_iso(self):
        resultado, valor = validar_fecha_ddmmyyyy("2026-10-10")
        self.assertEqual(resultado, "invalido")

    def test_fecha_invalida_dia_inexistente(self):
        resultado, valor = validar_fecha_ddmmyyyy("31-02-2026")
        self.assertEqual(resultado, "invalido")

    def test_texto_libre(self):
        resultado, valor = validar_fecha_ddmmyyyy("no es una fecha")
        self.assertEqual(resultado, "invalido")


class TestParsearPagoCm(unittest.TestCase):
    """Extraccion literal del parseo de PAGO CM en
    ComercialModule.on_item_edited(). No conoce self.df_base ni el fallback
    al valor anterior: eso permanece en comercial.py."""

    def test_con_signo_pesos_y_puntos_miles(self):
        resultado, dato = parsear_pago_cm("$1.234")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 1234.0)
        self.assertEqual(dato["formato"], "$1.234")

    def test_con_puntos_miles_sin_signo_pesos(self):
        resultado, dato = parsear_pago_cm("1.234")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 1234.0)
        self.assertEqual(dato["formato"], "$1.234")

    def test_con_signo_pesos_sin_puntos(self):
        resultado, dato = parsear_pago_cm("$1234")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 1234.0)
        self.assertEqual(dato["formato"], "$1.234")

    def test_sin_signo_pesos_ni_puntos(self):
        resultado, dato = parsear_pago_cm("1234")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 1234.0)
        self.assertEqual(dato["formato"], "$1.234")

    def test_vacio_se_interpreta_como_cero(self):
        resultado, dato = parsear_pago_cm("")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 0.0)
        self.assertEqual(dato["formato"], "$-")

    def test_cero_explicito(self):
        resultado, dato = parsear_pago_cm("0")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 0.0)
        self.assertEqual(dato["formato"], "$-")

    def test_valor_negativo(self):
        resultado, dato = parsear_pago_cm("-500")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], -500.0)
        self.assertEqual(dato["formato"], "-$500", "Fallo: el guion actual antepone el $, no queda '$-500'.")

    def test_valor_invalido(self):
        resultado, dato = parsear_pago_cm("abc")
        self.assertEqual(resultado, "invalido")
        self.assertIsNone(dato)

    def test_coma_y_punto_juntos_se_tratan_como_separadores_de_miles(self):
        # Comportamiento actual: '.' y ',' se eliminan por igual (no hay
        # separador decimal soportado), por lo que "1.234,56" colapsa a 123456.
        resultado, dato = parsear_pago_cm("1.234,56")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 123456.0)


class TestFormatearPagoCm(unittest.TestCase):
    """Extraccion literal de la formula de formato monetario, reutilizada
    tanto por parsear_pago_cm() como por el fallback de comercial.py cuando
    el valor pegado es invalido."""

    def test_cero(self):
        self.assertEqual(formatear_pago_cm(0), "$-")

    def test_positivo(self):
        self.assertEqual(formatear_pago_cm(1234.0), "$1.234")

    def test_negativo(self):
        self.assertEqual(formatear_pago_cm(-500.0), "-$500")


class TestQuitarVin(unittest.TestCase):
    """Extraccion literal de ComercialModule._on_del_finished()."""

    def test_elimina_solo_el_vin_indicado(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111', 'YV2BBB222', 'YV2CCC333']})
        resultado = quitar_vin(df, 'YV2BBB222')
        self.assertEqual(sorted(resultado['VIN'].tolist()), ['YV2AAA111', 'YV2CCC333'])

    def test_normaliza_espacios_y_mayusculas(self):
        df = pd.DataFrame({'VIN': [' yv2aaa111 ', 'YV2BBB222']})
        resultado = quitar_vin(df, 'YV2AAA111')
        self.assertEqual(resultado['VIN'].tolist(), ['YV2BBB222'])

    def test_vin_inexistente_no_elimina_nada(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111', 'YV2BBB222']})
        resultado = quitar_vin(df, 'YV2ZZZ999')
        self.assertEqual(len(resultado), 2)


class TestAgregarFila(unittest.TestCase):
    """Extraccion literal de ComercialModule._on_add_finished()."""

    def test_agrega_fila_al_final(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111'], 'MODELO': ['FH']})
        resultado = agregar_fila(df, {'VIN': 'YV2BBB222', 'MODELO': 'FM'})
        self.assertEqual(len(resultado), 2)
        self.assertEqual(resultado.iloc[1]['VIN'], 'YV2BBB222')

    def test_indice_queda_reseteado(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111']})
        resultado = agregar_fila(df, {'VIN': 'YV2BBB222'})
        self.assertEqual(list(resultado.index), [0, 1])


class TestAplicarCambiosPendientes(unittest.TestCase):
    """Extraccion literal (verificada identica) del patron duplicado en
    ComercialModule.filter_table(), confirm_save() y _on_save_finished()."""

    def test_aplica_cambio_al_vin_correcto(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111', 'YV2BBB222'], 'MODELO': ['FH', 'FM']})
        pending = {'YV2BBB222': {'VIN': 'YV2BBB222', 'cambios': {'MODELO': 'FMX'}}}
        resultado = aplicar_cambios_pendientes(df, pending)
        self.assertEqual(resultado.iloc[0]['MODELO'], 'FH')
        self.assertEqual(resultado.iloc[1]['MODELO'], 'FMX')

    def test_vin_de_pending_changes_que_ya_no_existe_se_ignora_silenciosamente(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111'], 'MODELO': ['FH']})
        pending = {'YV2ZZZ999': {'VIN': 'YV2ZZZ999', 'cambios': {'MODELO': 'FMX'}}}
        resultado = aplicar_cambios_pendientes(df, pending)
        self.assertEqual(resultado.iloc[0]['MODELO'], 'FH')

    def test_columna_de_pending_changes_que_no_existe_en_df_se_ignora(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111'], 'MODELO': ['FH']})
        pending = {'YV2AAA111': {'VIN': 'YV2AAA111', 'cambios': {'COLUMNA_INEXISTENTE': 'X'}}}
        resultado = aplicar_cambios_pendientes(df, pending)
        self.assertNotIn('COLUMNA_INEXISTENTE', resultado.columns)

    def test_multiples_vin_y_columnas(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111', 'YV2BBB222'], 'MODELO': ['FH', 'FM'], 'ESTADO COMERCIAL': ['Vigente', 'Vigente']})
        pending = {
            'YV2AAA111': {'VIN': 'YV2AAA111', 'cambios': {'MODELO': 'FMX'}},
            'YV2BBB222': {'VIN': 'YV2BBB222', 'cambios': {'ESTADO COMERCIAL': 'Vencido'}},
        }
        resultado = aplicar_cambios_pendientes(df, pending)
        self.assertEqual(resultado.iloc[0]['MODELO'], 'FMX')
        self.assertEqual(resultado.iloc[1]['ESTADO COMERCIAL'], 'Vencido')

    def test_pending_changes_vacio_no_modifica_nada(self):
        df = pd.DataFrame({'VIN': ['YV2AAA111'], 'MODELO': ['FH']})
        resultado = aplicar_cambios_pendientes(df, {})
        self.assertEqual(resultado.iloc[0]['MODELO'], 'FH')


class TestDetectarContradiccionesEtapaGestion(unittest.TestCase):
    """detectar_contradicciones_etapa_gestion() reutiliza
    DataFrameFormatter.calcular_etapa_gestion_esperada (misma fuente de
    verdad que DataFrameFormatter.clean()) para comparar ETAPA GESTIÓN actual
    vs esperada, sin reimplementar la regla de negocio. Regla vigente
    (21-09-2026, matriz de 2 ejes definida con el usuario): prioridad 3 ahora
    combina ESTADO COMERCIAL con ESTADO DE ACTIVACIÓN ACTUAL (antes solo
    miraba ESTADO COMERCIAL) -- ver ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ
    en constants.py. CLIENTE queda retirado del catálogo: la regla solo
    produce COMERCIAL u OPERACIONES."""

    @staticmethod
    def _df_una_fila(tipo_facturacion, estado_comercial, estado_activacion, etapa_gestion):
        return pd.DataFrame({
            'VIN': ['YV2TEST0001'],
            'TIPO DE FACTURACION': [tipo_facturacion],
            'ESTADO COMERCIAL': [estado_comercial],
            'ESTADO DE ACTIVACIÓN ACTUAL': [estado_activacion],
            'ETAPA GESTIÓN': [etapa_gestion],
        })

    def test_sin_registro_con_comercial_no_contradice(self):
        df = self._df_una_fila('SIN REGISTRO', 'Vigente', 'Conectado', 'COMERCIAL')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_sin_registro_con_operaciones_no_contradice_si_matriz_coincide(self):
        """25-09-2026, a pedido explícito ("la matriz de ESTADO COMERCIAL
        manda a todas las demás"): SIN REGISTRO ya no tiene prioridad sobre
        la matriz cuando esta define un valor. Activación Pendiente +
        Activando -> OPERACIONES vía matriz (independiente de TIPO DE
        FACTURACION), así que ya no contradice."""
        df = self._df_una_fila('SIN REGISTRO', 'Activacion pendiente', 'Activando', 'OPERACIONES')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_facturacion_manual_con_comercial_no_contradice(self):
        df = self._df_una_fila('FACTURACIÓN MANUAL', 'Vigente', 'Conectado', 'COMERCIAL')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_facturacion_manual_con_operaciones_contradice(self):
        df = self._df_una_fila('FACTURACIÓN MANUAL', 'Vigente', 'Conectado', 'OPERACIONES')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 1)

    def test_vigente_conectado_da_comercial_no_contradice(self):
        df = self._df_una_fila('CM', 'Vigente', 'Conectado', 'COMERCIAL')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_vigente_conectado_con_operaciones_contradice(self):
        df = self._df_una_fila('CM', 'Vigente', 'Conectado', 'OPERACIONES')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 1)

    def test_vigente_no_conectado_da_operaciones_no_contradice(self):
        """Antes de la matriz de 2 ejes, Vigente siempre forzaba CLIENTE sin
        mirar el estado técnico; ahora Vigente + cualquier estado que no sea
        Conectado apunta a OPERACIONES (regla confirmada 21-09-2026)."""
        df = self._df_una_fila('CM', 'Vigente', 'Activando', 'OPERACIONES')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_vigente_no_conectado_con_comercial_contradice(self):
        df = self._df_una_fila('CM', 'Vigente', 'Desconectado', 'COMERCIAL')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 1)

    def test_baja_conectado_da_operaciones_no_contradice(self):
        df = self._df_una_fila('CM', 'Baja', 'Conectado', 'OPERACIONES')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_baja_no_conectado_da_comercial_no_contradice(self):
        df = self._df_una_fila('CM', 'Baja', 'No aplica', 'COMERCIAL')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_baja_solicitada_conectado_da_operaciones_no_contradice(self):
        df = self._df_una_fila('CM', 'Baja Solicitada', 'Conectado', 'OPERACIONES')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_activacion_pendiente_activando_da_operaciones_no_contradice(self):
        df = self._df_una_fila('CM', 'Activacion pendiente', 'Activando', 'OPERACIONES')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_activacion_pendiente_conectado_da_comercial_no_contradice(self):
        df = self._df_una_fila('CM', 'Activacion pendiente', 'Conectado', 'COMERCIAL')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_vencido_siempre_comercial_sin_importar_activacion(self):
        for activacion in ('Activando', 'Conectado', 'Desconectado', 'No aplica', 'No entregado', 'Sin flota'):
            with self.subTest(activacion=activacion):
                df = self._df_una_fila('CM', 'Vencido', activacion, 'COMERCIAL')
                self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_revisar_activando_da_comercial_no_contradice(self):
        """25-09-2026, matriz actualizada por el usuario: REVISAR+ACTIVANDO
        pasó de OPERACIONES a COMERCIAL -- toda la fila de Revisar es
        COMERCIAL ahora, sin excepciones."""
        df = self._df_una_fila('CM', 'Revisar', 'Activando', 'COMERCIAL')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_revisar_activando_con_operaciones_contradice(self):
        df = self._df_una_fila('CM', 'Revisar', 'Activando', 'OPERACIONES')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 1)

    def test_revisar_conectado_da_comercial_no_contradice(self):
        df = self._df_una_fila('CM', 'Revisar', 'Conectado', 'COMERCIAL')
        self.assertEqual(len(detectar_contradicciones_etapa_gestion(df)), 0)

    def test_dataframe_con_varias_filas_cuenta_correctamente(self):
        df = pd.concat([
            self._df_una_fila('SIN REGISTRO', 'Vigente', 'Conectado', 'COMERCIAL'),      # OK
            self._df_una_fila('SIN REGISTRO', 'Vigente', 'Conectado', 'OPERACIONES'),    # contradice
            self._df_una_fila('CM', 'Vigente', 'Conectado', 'COMERCIAL'),                # OK
            self._df_una_fila('CM', 'Baja', 'Conectado', 'COMERCIAL'),                   # contradice (esperado OPERACIONES)
            self._df_una_fila('CM', 'Activacion pendiente', 'Activando', 'OPERACIONES'), # OK
        ], ignore_index=True)
        resultado = detectar_contradicciones_etapa_gestion(df)
        self.assertEqual(len(resultado), 2)

    def test_tipo_facturacion_vacio_no_lanza_error(self):
        df = self._df_una_fila('', 'Vigente', 'Conectado', 'COMERCIAL')
        resultado = detectar_contradicciones_etapa_gestion(df)
        self.assertEqual(len(resultado), 0)  # Vigente + Conectado -> COMERCIAL

    def test_estado_comercial_desconocido_no_provoca_crash(self):
        df = self._df_una_fila('CM', 'Estado Que No Existe', 'Conectado', 'CUALQUIER_COSA')
        resultado = detectar_contradicciones_etapa_gestion(df)
        self.assertEqual(len(resultado), 0)  # sin regla aplicable, se asume el valor actual como esperado

    def test_estado_activacion_desconocido_no_provoca_crash(self):
        df = self._df_una_fila('CM', 'Vigente', 'Estado Que No Existe', 'CUALQUIER_COSA')
        resultado = detectar_contradicciones_etapa_gestion(df)
        self.assertEqual(len(resultado), 0)  # ESTADO COMERCIAL conocido pero ACTIVACIÓN no -> se conserva el valor actual

    def test_dataframe_vacio_no_provoca_crash(self):
        df = pd.DataFrame({
            'VIN': [], 'TIPO DE FACTURACION': [], 'ESTADO COMERCIAL': [],
            'ESTADO DE ACTIVACIÓN ACTUAL': [], 'ETAPA GESTIÓN': [],
        })
        resultado = detectar_contradicciones_etapa_gestion(df)
        self.assertEqual(len(resultado), 0)

    def test_sin_columna_etapa_gestion_no_provoca_crash(self):
        df = pd.DataFrame({'VIN': ['YV2TEST0001'], 'TIPO DE FACTURACION': ['SIN REGISTRO'], 'ESTADO COMERCIAL': ['Vigente']})
        resultado = detectar_contradicciones_etapa_gestion(df)
        self.assertEqual(len(resultado), 0)

    def test_sin_registro_como_substring_de_un_valor_mas_largo_contradice_igual(self):
        """La regla original usa 'in' (substring), no '==', para SIN
        REGISTRO (ver DataFrameFormatter.calcular_etapa_gestion_esperada:
        `if VALOR_TIPO_FACT_SIN_REGISTRO in tipo_fact`). La version
        vectorizada debe preservar exactamente esa semantica de substring."""
        df = self._df_una_fila('CLIENTE - SIN REGISTRO HISTORICO', 'Vigente', 'Conectado', 'OPERACIONES')
        resultado = detectar_contradicciones_etapa_gestion(df)
        self.assertEqual(len(resultado), 1)  # deberia forzar COMERCIAL


class TestDetectarInconsistenciasFormaContratoTipoFacturacion(unittest.TestCase):
    """detectar_inconsistencias_forma_contrato_tipo_facturacion() reutiliza
    FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ (constants.py, matriz de la contraparte comercial,
    24-09-2026) como única fuente de verdad -- misma matriz que ya aplica en
    vivo ComercialAgregarDialog. Es una herramienta de solo DETECCIÓN para
    datos históricos: nunca modifica ninguna fila."""

    @staticmethod
    def _df_una_fila(vin, forma_contrato, tipo_facturacion):
        return pd.DataFrame({
            'VIN': [vin],
            'FORMA DE CONTRATO': [forma_contrato],
            'TIPO DE FACTURACION': [tipo_facturacion],
        })

    def test_combinacion_valida_no_aparece(self):
        # CMG solo admite CM segun la matriz.
        df = self._df_una_fila('YV2INC0001', 'CMG', 'CM')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 0)

    def test_combinacion_invalida_aparece(self):
        # Demo solo admite Sin Registro segun la matriz -- Cliente es invalido.
        df = self._df_una_fila('YV2INC0002', 'Demo', 'Cliente')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 1)

    def test_forma_de_contrato_no_incluida_en_matriz_no_se_marca(self):
        # 'Interno' (ese valor exacto) no es ninguna fila real de la matriz;
        # sea cual sea TIPO DE FACTURACION, no debe marcarse -- mismo
        # criterio "no reconocido no se restringe" que usa el propio
        # formulario en vivo.
        df = self._df_una_fila('YV2INC0003', 'Valor Legado Desconocido', 'Cliente')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 0)

    def test_se_reporta_correctamente_el_vin(self):
        df = self._df_una_fila('YV2INC0004', 'Venta', 'Interno')  # Venta solo admite Cliente/Facturacion Manual
        resultado = detectar_inconsistencias_forma_contrato_tipo_facturacion(df)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado.iloc[0]['VIN'], 'YV2INC0004')

    def test_se_reportan_correctamente_forma_y_tipo_facturacion_actuales(self):
        df = self._df_una_fila('YV2INC0005', 'Provision', 'Sin Registro')  # Provision solo admite Interno
        resultado = detectar_inconsistencias_forma_contrato_tipo_facturacion(df)
        self.assertEqual(resultado.iloc[0]['FORMA DE CONTRATO'], 'Provision')
        self.assertEqual(resultado.iloc[0]['TIPO DE FACTURACION'], 'Sin Registro')

    def test_tipo_facturacion_vacio_no_se_marca_aunque_forma_este_en_la_matriz(self):
        """'' significa 'todavia sin asignar', no una combinacion
        contradictoria (ver docstring de la funcion: confirmado contra los
        datos reales de RM_CONTRATOS.csv, mayoria de los casos)."""
        df = self._df_una_fila('YV2INC0006', 'Demo', '')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 0)

    def test_tipo_facturacion_guion_no_se_marca_aunque_forma_este_en_la_matriz(self):
        df = self._df_una_fila('YV2INC0007', 'Demo', '-')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 0)

    def test_forma_de_contrato_vacia_no_se_marca(self):
        df = self._df_una_fila('YV2INC0008', '', 'Cliente')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 0)

    def test_normalizacion_espacios_y_mayusculas_no_afecta_la_deteccion(self):
        # ' cmg ' con espacios/minusculas debe normalizar igual que 'CMG'.
        df = self._df_una_fila('YV2INC0009', ' cmg ', ' cm ')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 0)
        df2 = self._df_una_fila('YV2INC0010', ' cmg ', ' sin registro ')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df2)), 1)

    def test_conversion_admite_cliente_y_facturacion_manual(self):
        df_cliente = self._df_una_fila('YV2INC0011', 'Conversion', 'Cliente')
        df_fact_manual = self._df_una_fila('YV2INC0012', 'Conversion', 'Facturación Manual')
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df_cliente)), 0)
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df_fact_manual)), 0)

    def test_dataframe_vacio_no_falla(self):
        df = pd.DataFrame()
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 0)

    def test_dataframe_sin_columnas_necesarias_no_falla(self):
        df = pd.DataFrame({'VIN': ['YV2INC0013']})
        self.assertEqual(len(detectar_inconsistencias_forma_contrato_tipo_facturacion(df)), 0)

    def test_multiples_filas_mixtas_solo_marca_las_invalidas(self):
        df = pd.DataFrame({
            'VIN': ['YV2A', 'YV2B', 'YV2C', 'YV2D'],
            'FORMA DE CONTRATO': ['CMG', 'Demo', 'Provision', 'Sin Contrato'],
            'TIPO DE FACTURACION': ['CM', 'Cliente', 'Interno', '-'],
        })
        # CMG+CM valido, Demo+Cliente invalido (deberia ser Sin Registro),
        # Provision+Interno valido, Sin Contrato+'-' no se marca (sin asignar).
        resultado = detectar_inconsistencias_forma_contrato_tipo_facturacion(df)
        self.assertEqual(list(resultado['VIN']), ['YV2B'])


class TestContarFormaContratoSinTipoFacturacionAsignado(unittest.TestCase):
    """contar_forma_contrato_sin_tipo_facturacion_asignado() es el conteo
    complementario a detectar_inconsistencias_forma_contrato_tipo_facturacion:
    cuenta lo que esa función deliberadamente NO marca (TIPO DE FACTURACION
    vacío/'-' con FORMA DE CONTRATO reconocido). Reutiliza la misma
    FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ, sin duplicar la consulta."""

    def test_cuenta_guion_con_forma_reconocida(self):
        df = pd.DataFrame({'VIN': ['A'], 'FORMA DE CONTRATO': ['Demo'], 'TIPO DE FACTURACION': ['-']})
        self.assertEqual(contar_forma_contrato_sin_tipo_facturacion_asignado(df), 1)

    def test_cuenta_vacio_con_forma_reconocida(self):
        df = pd.DataFrame({'VIN': ['A'], 'FORMA DE CONTRATO': ['Demo'], 'TIPO DE FACTURACION': ['']})
        self.assertEqual(contar_forma_contrato_sin_tipo_facturacion_asignado(df), 1)

    def test_no_cuenta_forma_no_reconocida(self):
        df = pd.DataFrame({'VIN': ['A'], 'FORMA DE CONTRATO': ['Valor Legado'], 'TIPO DE FACTURACION': ['-']})
        self.assertEqual(contar_forma_contrato_sin_tipo_facturacion_asignado(df), 0)

    def test_no_cuenta_combinacion_valida(self):
        df = pd.DataFrame({'VIN': ['A'], 'FORMA DE CONTRATO': ['CMG'], 'TIPO DE FACTURACION': ['CM']})
        self.assertEqual(contar_forma_contrato_sin_tipo_facturacion_asignado(df), 0)

    def test_no_cuenta_combinacion_inconsistente_real(self):
        # Esta la debe contar detectar_inconsistencias_..., no esta funcion.
        df = pd.DataFrame({'VIN': ['A'], 'FORMA DE CONTRATO': ['Demo'], 'TIPO DE FACTURACION': ['Cliente']})
        self.assertEqual(contar_forma_contrato_sin_tipo_facturacion_asignado(df), 0)

    def test_dataframe_vacio_no_falla(self):
        self.assertEqual(contar_forma_contrato_sin_tipo_facturacion_asignado(pd.DataFrame()), 0)

    def test_suma_correctamente_varias_filas(self):
        df = pd.DataFrame({
            'VIN': ['A', 'B', 'C', 'D'],
            'FORMA DE CONTRATO': ['Demo', 'Sin Contrato', 'CMG', 'Valor Legado'],
            'TIPO DE FACTURACION': ['-', '', 'CM', '-'],
        })
        self.assertEqual(contar_forma_contrato_sin_tipo_facturacion_asignado(df), 2)


class TestNormalizarTipoFacturacionPorFormaContrato(unittest.TestCase):
    """normalizar_tipo_facturacion_por_forma_contrato() -- 24-09-2026, a
    pedido explícito: completa TIPO DE FACTURACION solo cuando está sin
    asignar (vacío/'-'/NaN) Y la matriz tiene exactamente una opción válida
    para ese FORMA DE CONTRATO. Nunca toca un valor real ya asignado (válido
    o no), y nunca fuerza nada cuando la matriz permite más de una opción."""

    @staticmethod
    def _df(forma_contrato, tipo_facturacion):
        return pd.DataFrame({'VIN': ['YV2N001'], 'FORMA DE CONTRATO': [forma_contrato], 'TIPO DE FACTURACION': [tipo_facturacion]})

    def _resultado(self, forma_contrato, tipo_facturacion):
        df = self._df(forma_contrato, tipo_facturacion)
        return normalizar_tipo_facturacion_por_forma_contrato(df).iloc[0]['TIPO DE FACTURACION']

    def test_sin_contrato_guion_termina_sin_registro(self):
        self.assertEqual(self._resultado('Sin Contrato', '-'), 'SIN REGISTRO')

    def test_provision_guion_termina_interno(self):
        self.assertEqual(self._resultado('Provision', '-'), 'INTERNO')

    def test_cmb_guion_termina_cm(self):
        self.assertEqual(self._resultado('CMB', '-'), 'CM')

    def test_cmg_guion_termina_cm(self):
        self.assertEqual(self._resultado('CMG', '-'), 'CM')

    def test_cms_guion_termina_cm(self):
        self.assertEqual(self._resultado('CMS', '-'), 'CM')

    def test_demo_guion_termina_sin_registro(self):
        self.assertEqual(self._resultado('Demo', '-'), 'SIN REGISTRO')

    def test_revisar_guion_termina_sin_registro(self):
        self.assertEqual(self._resultado('Revisar', '-'), 'SIN REGISTRO')

    def test_test_guion_termina_sin_registro(self):
        self.assertEqual(self._resultado('Test', '-'), 'SIN REGISTRO')

    def test_provision_mas_guion_termina_provision_mas(self):
        self.assertEqual(self._resultado('Provision +', '-'), 'PROVISION +')

    def test_conversion_guion_permanece_guion(self):
        # Dos opciones validas (Cliente/Facturacion Manual): no se toca.
        self.assertEqual(self._resultado('Conversion', '-'), '-')

    def test_venta_guion_permanece_guion(self):
        self.assertEqual(self._resultado('Venta', '-'), '-')

    def test_valor_real_valido_no_se_modifica(self):
        self.assertEqual(self._resultado('CMG', 'CM'), 'CM')

    def test_valor_real_invalido_no_se_modifica_y_sigue_detectable(self):
        # Demo solo admite Sin Registro -- 'Cliente' es un valor real
        # incompatible, no debe tocarse aquí.
        df = self._df('Demo', 'Cliente')
        resultado = normalizar_tipo_facturacion_por_forma_contrato(df)
        self.assertEqual(resultado.iloc[0]['TIPO DE FACTURACION'], 'Cliente')
        # y debe seguir siendo detectable como inconsistencia real.
        inconsistencias = detectar_inconsistencias_forma_contrato_tipo_facturacion(resultado)
        self.assertEqual(len(inconsistencias), 1)

    def test_vacio_y_nan_reciben_mismo_tratamiento_que_guion(self):
        self.assertEqual(self._resultado('Sin Contrato', ''), 'SIN REGISTRO')
        self.assertEqual(self._resultado('Sin Contrato', float('nan')), 'SIN REGISTRO')

    def test_forma_de_contrato_no_reconocida_no_se_toca(self):
        self.assertEqual(self._resultado('Valor Legado Desconocido', '-'), '-')

    def test_no_muta_el_dataframe_original(self):
        df_original = self._df('Sin Contrato', '-')
        normalizar_tipo_facturacion_por_forma_contrato(df_original)
        self.assertEqual(df_original.iloc[0]['TIPO DE FACTURACION'], '-')

    def test_dataframe_vacio_no_falla(self):
        resultado = normalizar_tipo_facturacion_por_forma_contrato(pd.DataFrame())
        self.assertTrue(resultado.empty)

    def test_multiples_filas_mixtas(self):
        df = pd.DataFrame({
            'VIN': ['A', 'B', 'C', 'D', 'E'],
            'FORMA DE CONTRATO': ['CMG', 'Conversion', 'Demo', 'Sin Contrato', 'Provision'],
            'TIPO DE FACTURACION': ['-', '-', 'Cliente', '', '-'],
        })
        resultado = normalizar_tipo_facturacion_por_forma_contrato(df)
        self.assertEqual(list(resultado['TIPO DE FACTURACION']), ['CM', '-', 'Cliente', 'SIN REGISTRO', 'INTERNO'])


class TestCalcularEtapaGestionEsperadaVectorizadoEquivaleARowWise(unittest.TestCase):
    """Fase 3 de la auditoria de rendimiento de UI (21-09-2026):
    detectar_contradicciones_etapa_gestion() usaba df.apply(axis=1) fila por
    fila sobre DataFrameFormatter.calcular_etapa_gestion_esperada(); ahora
    usa _calcular_etapa_gestion_esperada_vectorizado(), que traduce la MISMA
    regla (prioridades 1-3) sin apply(axis=1). Este test compara, fila a
    fila, la version vectorizada contra la version row-wise original sobre
    un DataFrame que cubre las 3 prioridades, sus combinaciones, columnas
    faltantes y valores NaN/vacios -- si algun dia se agrega una prioridad
    nueva a la regla y no se replica en la version vectorizada, esto debe
    fallar."""

    def _comparar_fila_a_fila(self, df):
        esperado_row_wise = df.apply(DataFrameFormatter.calcular_etapa_gestion_esperada, axis=1)
        esperado_row_wise_norm = esperado_row_wise.astype(str).str.strip().str.upper()
        esperado_vectorizado = _calcular_etapa_gestion_esperada_vectorizado(df)
        pd.testing.assert_series_equal(
            esperado_vectorizado.reset_index(drop=True),
            esperado_row_wise_norm.reset_index(drop=True),
            check_names=False,
        )

    def test_equivalencia_en_casos_completos_y_borde(self):
        df = pd.DataFrame({
            'TIPO DE FACTURACION': [
                'SIN REGISTRO', 'CLIENTE - SIN REGISTRO HISTORICO', 'FACTURACIÓN MANUAL',
                'CM', 'CM', 'CM', 'CM', 'CM', 'CM', 'CM',
                '', None, 'CM',
            ],
            'ESTADO COMERCIAL': [
                'Vigente', 'Vigente', 'Vigente',
                'Vigente', 'Baja', 'Baja Solicitada', 'Revisar', 'Vencido',
                'Activacion pendiente', 'Activación Pendiente',
                'Vigente', 'Vigente', 'Estado Que No Existe',
            ],
            'ESTADO DE ACTIVACIÓN ACTUAL': [
                'Conectado', 'Conectado', 'Conectado',
                'Conectado', 'Conectado', 'Conectado', 'Activando', 'No aplica',
                'Activando', 'Activando',
                'Desconectado', 'No entregado', 'Sin flota',
            ],
            'ETAPA GESTIÓN': [
                'COMERCIAL', 'COMERCIAL', 'COMERCIAL',
                'COMERCIAL', 'OPERACIONES', 'OPERACIONES', 'OPERACIONES', 'COMERCIAL',
                'OPERACIONES', 'OPERACIONES',
                'OPERACIONES', 'OPERACIONES', 'CUALQUIER_COSA',
            ],
        })
        self._comparar_fila_a_fila(df)

    def test_equivalencia_sin_columna_tipo_facturacion(self):
        df = pd.DataFrame({
            'ESTADO COMERCIAL': ['Vigente', 'Baja'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado', 'Conectado'],
            'ETAPA GESTIÓN': ['COMERCIAL', 'OPERACIONES'],
        })
        self._comparar_fila_a_fila(df)

    def test_equivalencia_sin_columna_estado_comercial(self):
        df = pd.DataFrame({
            'TIPO DE FACTURACION': ['CM', 'SIN REGISTRO'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado', 'Conectado'],
            'ETAPA GESTIÓN': ['COMERCIAL', 'COMERCIAL'],
        })
        self._comparar_fila_a_fila(df)

    def test_equivalencia_sin_columna_estado_activacion(self):
        """Columna nueva de la prioridad 3 (21-09-2026): también necesita
        fallback si falta, igual que TIPO DE FACTURACION/ESTADO COMERCIAL."""
        df = pd.DataFrame({
            'TIPO DE FACTURACION': ['CM', 'CM'],
            'ESTADO COMERCIAL': ['Vigente', 'Baja'],
            'ETAPA GESTIÓN': ['COMERCIAL', 'OPERACIONES'],
        })
        self._comparar_fila_a_fila(df)

    def test_equivalencia_con_nan_en_etapa_gestion_y_fallback_al_valor_actual(self):
        df = pd.DataFrame({
            'TIPO DE FACTURACION': ['CM'],
            'ESTADO COMERCIAL': ['Estado Que No Existe'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado'],
            'ETAPA GESTIÓN': [None],
        })
        self._comparar_fila_a_fila(df)


class TestAplicaReglaSinContrato(unittest.TestCase):
    """Regla confirmada con la contraparte comercial: al editar FORMA DE CONTRATO a
    'Sin Contrato' en Vista Completa, se limpian a '-' TIPO DE SERVICIO,
    INICIO CONTRATO, DURACIÓN (MESES) y TÉRMINO CONTRATO. Función pura: no
    conoce pending_changes, PyQt ni el DataFrame completo (eso es
    responsabilidad de comercial.py::on_item_edited)."""

    def _assert_limpia_los_cuatro_campos(self, resultado):
        self.assertEqual(set(resultado.keys()), set(COLUMNAS_LIMPIEZA_SIN_CONTRATO))
        for col in COLUMNAS_LIMPIEZA_SIN_CONTRATO:
            self.assertEqual(resultado[col], '-')

    def test_venta_a_sin_contrato_limpia_cuatro_campos(self):
        # El valor "anterior" (Venta) es irrelevante para la función: solo
        # importa la columna editada y el valor nuevo.
        resultado = aplica_regla_sin_contrato('FORMA DE CONTRATO', 'Sin Contrato')
        self._assert_limpia_los_cuatro_campos(resultado)

    def test_provision_a_sin_contrato_limpia_cuatro_campos(self):
        resultado = aplica_regla_sin_contrato('FORMA DE CONTRATO', 'Sin Contrato')
        self._assert_limpia_los_cuatro_campos(resultado)

    def test_test_a_sin_contrato_limpia_cuatro_campos(self):
        resultado = aplica_regla_sin_contrato('FORMA DE CONTRATO', 'Sin Contrato')
        self._assert_limpia_los_cuatro_campos(resultado)

    def test_cualquier_otro_valor_a_sin_contrato_limpia_cuatro_campos(self):
        resultado = aplica_regla_sin_contrato('FORMA DE CONTRATO', 'Sin Contrato')
        self._assert_limpia_los_cuatro_campos(resultado)

    def test_es_insensible_a_mayusculas_y_espacios(self):
        resultado = aplica_regla_sin_contrato('FORMA DE CONTRATO', '  sin contrato  ')
        self._assert_limpia_los_cuatro_campos(resultado)

    def test_columna_distinta_no_hace_nada(self):
        resultado = aplica_regla_sin_contrato('TIPO DE SERVICIO', 'Sin Contrato')
        self.assertEqual(resultado, {})

    def test_valor_nuevo_no_es_sin_contrato_no_hace_nada(self):
        resultado = aplica_regla_sin_contrato('FORMA DE CONTRATO', 'Venta')
        self.assertEqual(resultado, {})

    def test_sin_contrato_hacia_otro_valor_no_aplica_regla_inversa(self):
        # Cambiar DESDE 'Sin Contrato' hacia otro valor no debe reconstruir
        # nada: la función solo mira el valor NUEVO, nunca el anterior.
        resultado = aplica_regla_sin_contrato('FORMA DE CONTRATO', 'Venta')
        self.assertEqual(resultado, {})


class TestAplicaReglaTerminatedCm(unittest.TestCase):
    """Regla confirmada: al editar ESTADO DEL CM a 'Terminated' (en Comercial
    Vista Completa o en Contratos CM), se limpian a '-' N CONTRATO 3PC,
    FECHA INICIO CM, FECHA TERMINO CM, TIPO DE CM y PAGO CM. ESTADO DEL CM
    en si NO se limpia. Función pura, mismo contrato que
    aplica_regla_sin_contrato: no conoce pending_changes ni PyQt6."""

    def _assert_limpia_los_cinco_campos(self, resultado):
        self.assertEqual(set(resultado.keys()), set(COLUMNAS_LIMPIEZA_TERMINATED_CM))
        for col in COLUMNAS_LIMPIEZA_TERMINATED_CM:
            self.assertEqual(resultado[col], '-')
        self.assertNotIn('ESTADO DEL CM', resultado, "ESTADO DEL CM no debe limpiarse a sí mismo.")

    def test_running_a_terminated_limpia_cinco_campos(self):
        resultado = aplica_regla_terminated_cm('ESTADO DEL CM', 'Terminated')
        self._assert_limpia_los_cinco_campos(resultado)

    def test_es_insensible_a_mayusculas_y_espacios(self):
        resultado = aplica_regla_terminated_cm('ESTADO DEL CM', '  TERMINATED  ')
        self._assert_limpia_los_cinco_campos(resultado)

    def test_columna_distinta_no_hace_nada(self):
        resultado = aplica_regla_terminated_cm('TIPO DE CM', 'Terminated')
        self.assertEqual(resultado, {})

    def test_valor_nuevo_no_es_terminated_no_hace_nada(self):
        resultado = aplica_regla_terminated_cm('ESTADO DEL CM', 'Running')
        self.assertEqual(resultado, {})

    def test_terminated_hacia_otro_valor_no_aplica_regla_inversa(self):
        # Cambiar DESDE 'Terminated' hacia otro valor no debe reconstruir
        # nada: la función solo mira el valor NUEVO, nunca el anterior.
        resultado = aplica_regla_terminated_cm('ESTADO DEL CM', 'Running')
        self.assertEqual(resultado, {})


class TestContratosPorId(unittest.TestCase):
    """Fase 2 (contratos por ID, 09-10-2026): contrato actual por VIN, cambios
    y borrado por ID, matriz de nuevo contrato, renovación y búsqueda exacta
    por N° Contrato."""

    @staticmethod
    def _df():
        return pd.DataFrame({
            'ID': ['1', '2', '3'], 'VIN': ['A', 'B', 'B'],
            'ESTADO COMERCIAL': ['Vigente', 'Baja', 'Vigente'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Conectado', 'Desconectado', 'Conectado'],
            'X': ['', '', ''],
        })

    def test_contratos_actuales_deja_el_mayor_id_por_vin(self):
        from src.services.comercial_services import contratos_actuales
        self.assertEqual(contratos_actuales(self._df())['ID'].tolist(), ['1', '3'])

    def test_contratos_actuales_sin_columna_id_gana_la_ultima_fila(self):
        from src.services.comercial_services import contratos_actuales
        df = pd.DataFrame({'VIN': ['A', 'A', 'B'], 'X': ['uno', 'dos', 'tres']})
        self.assertEqual(contratos_actuales(df)['X'].tolist(), ['dos', 'tres'])

    def test_contratos_anteriores_excluye_el_actual_y_ordena_por_id_descendente(self):
        from src.services.comercial_services import contratos_anteriores
        df = pd.DataFrame({'ID': ['4', '9', '7', '2'], 'VIN': ['b', 'B', ' B ', 'A']})
        self.assertEqual(contratos_anteriores(df, 'B')['ID'].tolist(), ['7', '4'])
        self.assertTrue(contratos_anteriores(df, 'A').empty)
        self.assertTrue(contratos_anteriores(df, 'NO EXISTE').empty)
        self.assertTrue(contratos_anteriores(pd.DataFrame(), 'B').empty)

    def test_agregar_id_a_cambios_usa_el_contrato_actual(self):
        from src.services.comercial_services import agregar_id_a_cambios, contratos_actuales
        base = contratos_actuales(self._df())
        cambios = agregar_id_a_cambios({'B': {'cambios': {'X': 'k'}}, 'Z': {'cambios': {}}}, base)
        self.assertEqual(cambios['B']['ID'], '3')
        self.assertNotIn('ID', cambios['Z'])

    def test_aplicar_cambios_con_id_solo_toca_ese_contrato(self):
        df = self._df()
        aplicar_cambios_pendientes(df, {'B': {'ID': '3', 'cambios': {'X': 'k'}}})
        self.assertEqual(df['X'].tolist(), ['', '', 'k'])

    def test_aplicar_cambios_sin_id_mantiene_el_comportamiento_por_vin(self):
        df = self._df()
        aplicar_cambios_pendientes(df, {'B': {'cambios': {'X': 'k'}}})
        self.assertEqual(df['X'].tolist(), ['', 'k', 'k'])

    def test_quitar_vin_por_id_y_por_vin(self):
        self.assertEqual(quitar_vin(self._df(), 'B', '3')['ID'].tolist(), ['1', '2'])
        self.assertEqual(quitar_vin(self._df(), 'B')['ID'].tolist(), ['1'])

    def test_proximo_id_contrato(self):
        from src.services.comercial_services import proximo_id_contrato
        self.assertEqual(proximo_id_contrato(self._df()), '4')
        self.assertEqual(proximo_id_contrato(pd.DataFrame({'VIN': ['A']})), '')

    def test_matriz_nuevo_contrato(self):
        from src.services.comercial_services import puede_crear_contrato
        esperado = {
            ('Baja', 'Desconectado'): True, ('Baja Solicitada', 'Desconectado'): True,
            ('Baja', 'No aplica'): True, ('Baja', 'No entregado'): True, ('Baja Solicitada', 'Sin flota'): True,
            ('Revisar', 'No aplica'): True,
            ('Baja', 'Conectado'): False, ('Baja', 'Activando'): False, ('Baja Solicitada', 'Conectado'): False,
            ('Vigente', 'Desconectado'): False, ('Vigente', 'Conectado'): False, ('Vencido', 'Desconectado'): False,
            ('Revisar', 'Conectado'): False, ('Activación Pendiente', 'Activando'): False,
        }
        for (estado, activacion), puede in esperado.items():
            self.assertEqual(puede_crear_contrato(estado, activacion), puede, f"{estado} x {activacion}")

    def test_vins_con_contrato_abierto_usa_el_contrato_actual(self):
        from src.services.comercial_services import vins_con_contrato_abierto
        # A: Vigente + Conectado (bloquea); B: el actual (ID 3) es Vigente (bloquea)
        self.assertEqual(vins_con_contrato_abierto(self._df()), {'A', 'B'})
        df = self._df().iloc[[1]]
        self.assertEqual(vins_con_contrato_abierto(df), set())

    def test_calcular_renovacion_suma_meses_y_recalcula_el_termino(self):
        from src.services.comercial_services import calcular_renovacion
        fila = {'ESTADO COMERCIAL': 'Vigente', 'DURACIÓN (MESES)': '12', 'INICIO CONTRATO': '15-03-2025'}
        self.assertEqual(calcular_renovacion(fila, 12), {'DURACIÓN (MESES)': '24', 'TÉRMINO CONTRATO': '15-03-2027'})

    def test_calcular_renovacion_de_vencido_vuelve_a_vigente(self):
        from src.services.comercial_services import calcular_renovacion
        fila = {'ESTADO COMERCIAL': 'Vencido', 'DURACIÓN (MESES)': '12', 'INICIO CONTRATO': '15-03-2025'}
        self.assertEqual(calcular_renovacion(fila, 6)['ESTADO COMERCIAL'], 'VIGENTE')

    def test_calcular_renovacion_no_aplica_a_mensual_baja_ni_sin_inicio(self):
        from src.services.comercial_services import calcular_renovacion
        base = {'ESTADO COMERCIAL': 'Vigente', 'DURACIÓN (MESES)': '12', 'INICIO CONTRATO': '15-03-2025'}
        self.assertIsNone(calcular_renovacion({**base, 'DURACIÓN (MESES)': 'MENSUAL'}, 6))
        self.assertIsNone(calcular_renovacion({**base, 'ESTADO COMERCIAL': 'Baja'}, 6))
        self.assertIsNone(calcular_renovacion({**base, 'INICIO CONTRATO': '-'}, 6))
        self.assertIsNone(calcular_renovacion(base, 0))

    def test_busqueda_por_n_contrato_es_exacta(self):
        df = pd.DataFrame({'ID': ['12', '112', '1203'], 'VIN': ['A', 'B', 'C']})
        mascara = construir_mascara_busqueda(df, '12', ['VIN'], ['ID'])
        self.assertEqual(mascara.tolist(), [True, False, False])
        mascara = construir_mascara_busqueda(df, '112,1203', ['VIN'], ['ID'])
        self.assertEqual(mascara.tolist(), [False, True, True])

    def test_vins_reactivables_de_power_bi_solo_incluye_bajas_que_admiten_contrato(self):
        from src.services.powerbi_import_service import _vins_reactivables
        df = pd.DataFrame({
            'ID': ['1', '2', '3', '4'], 'VIN': ['A', 'B', 'C', 'D'],
            'ESTADO COMERCIAL': ['Baja', 'Baja', 'Vigente', 'Revisar'],
            'ESTADO DE ACTIVACIÓN ACTUAL': ['Desconectado', 'Conectado', 'Conectado', 'No aplica'],
        })
        self.assertEqual(_vins_reactivables(df), {'A'})


if __name__ == '__main__':
    unittest.main()
