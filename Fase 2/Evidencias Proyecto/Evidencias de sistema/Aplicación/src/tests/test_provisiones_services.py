import unittest

import pandas as pd

from src.services.provisiones_services import (
    formatear_moneda, validar_cantidad_meses, parsear_dynafleet, calcular_montos_provision,
    limpiar_cantidad_meses_display, construir_cambios_provisiones, convertir_periodo_interno,
    parsear_numero_uf, mapear_industria, normalizar_cliente, construir_lookup_razon_social,
    buscar_candidatos_por_cliente, mapear_tipo_servicio_desde_plan,
)


class TestFormatearMoneda(unittest.TestCase):
    """Extraccion literal de la formula de formato monetario repetida en
    ProvisionesModule.on_item_edited() y filter_table()."""

    def test_cero(self):
        self.assertEqual(formatear_moneda(0), "$-")

    def test_positivo(self):
        self.assertEqual(formatear_moneda(500000), "$500.000")

    def test_negativo(self):
        self.assertEqual(formatear_moneda(-500), "-$500")

    def test_redondeo_hacia_arriba(self):
        self.assertEqual(formatear_moneda(499.6), "$500")


class TestValidarCantidadMeses(unittest.TestCase):
    """Extraccion literal de la validacion de 'Cantidad de Meses' en
    ProvisionesModule.on_item_edited()."""

    def test_vacio(self):
        self.assertEqual(validar_cantidad_meses(""), ("vacio", ""))

    def test_nan(self):
        self.assertEqual(validar_cantidad_meses("nan"), ("vacio", ""))
        self.assertEqual(validar_cantidad_meses("NaN"), ("vacio", ""))

    def test_guion(self):
        self.assertEqual(validar_cantidad_meses("-"), ("mensual", "-"))

    def test_mensual_mayusculas_y_minusculas(self):
        self.assertEqual(validar_cantidad_meses("MENSUAL"), ("mensual", "-"))
        self.assertEqual(validar_cantidad_meses("mensual"), ("mensual", "-"))

    def test_entero_positivo(self):
        self.assertEqual(validar_cantidad_meses("12"), ("numerico", "12"))

    def test_decimal_positivo_se_trunca(self):
        self.assertEqual(validar_cantidad_meses("2.5"), ("numerico", "2"))

    def test_cero_es_invalido(self):
        resultado, valor = validar_cantidad_meses("0")
        self.assertEqual(resultado, "invalido")
        self.assertIn("mayor a 0", valor)

    def test_negativo_es_invalido(self):
        resultado, valor = validar_cantidad_meses("-5")
        self.assertEqual(resultado, "invalido")

    def test_texto_invalido(self):
        resultado, valor = validar_cantidad_meses("abc")
        self.assertEqual(resultado, "invalido")

    def test_espacios_se_normalizan(self):
        self.assertEqual(validar_cantidad_meses("  12  "), ("numerico", "12"))
        self.assertEqual(validar_cantidad_meses("  -  "), ("mensual", "-"))
        self.assertEqual(validar_cantidad_meses("   "), ("vacio", ""))


class TestParsearDynafleet(unittest.TestCase):
    """Extraccion literal del parseo de DYNAFLEET en
    ProvisionesModule.on_item_edited(). No conoce self.df_base ni el
    fallback al valor anterior: eso permanece en provisiones.py."""

    def test_con_signo_pesos_y_puntos_miles(self):
        resultado, dato = parsear_dynafleet("$500.000")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 500000.0)
        self.assertEqual(dato["formato"], "$500.000")

    def test_sin_signo_pesos_ni_puntos(self):
        resultado, dato = parsear_dynafleet("500000")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 500000.0)
        self.assertEqual(dato["formato"], "$500.000")

    def test_vacio_se_interpreta_como_cero(self):
        resultado, dato = parsear_dynafleet("")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], 0.0)
        self.assertEqual(dato["formato"], "$-")

    def test_valor_negativo(self):
        resultado, dato = parsear_dynafleet("-500")
        self.assertEqual(resultado, "valido")
        self.assertEqual(dato["num"], -500.0)
        self.assertEqual(dato["formato"], "-$500")

    def test_valor_invalido(self):
        resultado, dato = parsear_dynafleet("abc")
        self.assertEqual(resultado, "invalido")
        self.assertIsNone(dato)


class TestCalcularMontosProvision(unittest.TestCase):
    """Extraccion literal del bloque de calculo en vivo de 'Monto
    Provisionado' / 'Valor Plan' / 'VAR' en
    ProvisionesModule.on_item_edited()."""

    PLANES = [
        {"nombre": "Basico", "uf_mult": 1.0},
        {"nombre": "Full", "uf_mult": 2.0},
    ]
    UF = 39000.0

    def test_calculo_basico(self):
        monto, valor_plan, var = calcular_montos_provision(500000, 5, "Basico", self.PLANES, self.UF)
        self.assertEqual(monto, 100000.0)
        self.assertEqual(valor_plan, 39000.0)
        self.assertEqual(var, 61000.0)

    def test_meses_cero_se_trata_como_uno(self):
        monto, _, _ = calcular_montos_provision(500000, 0, "Basico", self.PLANES, self.UF)
        self.assertEqual(monto, 500000.0)

    def test_plan_no_encontrado_usa_cero(self):
        _, valor_plan, _ = calcular_montos_provision(0, 1, "Plan Inexistente", self.PLANES, self.UF)
        self.assertEqual(valor_plan, 0.0)

    def test_variacion_negativa(self):
        monto, valor_plan, var = calcular_montos_provision(10000, 1, "Full", self.PLANES, self.UF)
        self.assertEqual(valor_plan, 78000.0)
        self.assertEqual(var, 10000.0 - 78000.0)
        self.assertLess(var, 0)


class TestLimpiarCantidadMesesDisplay(unittest.TestCase):
    """Extraccion literal de clean_meses_ui(), aplicada en
    ProvisionesModule.load_data()."""

    def test_valor_nan(self):
        self.assertEqual(limpiar_cantidad_meses_display(float('nan')), "")

    def test_valor_vacio(self):
        self.assertEqual(limpiar_cantidad_meses_display(""), "")
        self.assertEqual(limpiar_cantidad_meses_display("None"), "")

    def test_guion_y_mensual_se_preservan(self):
        self.assertEqual(limpiar_cantidad_meses_display("-"), "-")
        self.assertEqual(limpiar_cantidad_meses_display("mensual"), "MENSUAL")

    def test_numero_se_redondea_a_entero_string(self):
        self.assertEqual(limpiar_cantidad_meses_display(12.0), "12")
        self.assertEqual(limpiar_cantidad_meses_display("11.6"), "12")

    def test_texto_no_numerico_se_preserva_en_mayusculas(self):
        self.assertEqual(limpiar_cantidad_meses_display("raro"), "RARO")


class TestConstruirCambiosProvisiones(unittest.TestCase):
    """Extraccion literal del primer bucle de SaveProvisionesThread.run()."""

    def test_normaliza_vin_y_fecha(self):
        pending = {
            "key1": {"VIN": " yv2aaa111 ", "AÑO - MES": " 2026 - Marzo ", "cambios": {"Plan": "Full"}}
        }
        resultado = construir_cambios_provisiones(pending)
        self.assertEqual(resultado["key1"]["keys"], {"VIN": "YV2AAA111", "AÑO - MES": "2026 - Marzo"})
        self.assertEqual(resultado["key1"]["cambios"], {"Plan": "Full"})

    def test_multiples_entradas(self):
        pending = {
            "k1": {"VIN": "AAA", "AÑO - MES": "2026 - Enero", "cambios": {}},
            "k2": {"VIN": "BBB", "AÑO - MES": "2026 - Febrero", "cambios": {}},
        }
        resultado = construir_cambios_provisiones(pending)
        self.assertEqual(len(resultado), 2)


class TestConvertirPeriodoInterno(unittest.TestCase):
    """Extraccion literal del calculo de PERIODO INTERNO en
    SaveProvisionesThread.run()."""

    def test_ano_primero(self):
        self.assertEqual(convertir_periodo_interno("2026 - Marzo"), "Marzo - 2026")

    def test_mes_primero_no_se_modifica(self):
        self.assertEqual(convertir_periodo_interno("Marzo - 2026"), "Marzo - 2026")

    def test_sin_guion_no_se_modifica(self):
        self.assertEqual(convertir_periodo_interno("Marzo 2026"), "Marzo 2026")

    def test_formato_no_reconocido_no_se_modifica(self):
        self.assertEqual(convertir_periodo_interno("a-b-c"), "a-b-c")


class TestParsearNumeroUf(unittest.TestCase):
    """Extraccion literal del parseo numerico en CostosDialog.save_and_close()."""

    def test_con_coma_decimal(self):
        self.assertEqual(parsear_numero_uf("39123,45"), 39123.45)

    def test_con_punto_decimal(self):
        self.assertEqual(parsear_numero_uf("39123.45"), 39123.45)

    def test_texto_invalido_lanza_value_error(self):
        with self.assertRaises(ValueError):
            parsear_numero_uf("abc")


class TestMapearIndustria(unittest.TestCase):
    """Extraccion literal del mapeo de INDUSTRIA en RescateWorker.run()."""

    def test_valor_vacio_o_nulo_conocido(self):
        for val in ['', 'nan', 'None', '<NA>', '-', '0', '0.0']:
            self.assertEqual(mapear_industria(val), "NO DEFINIDA")

    def test_valor_mapeado(self):
        self.assertEqual(mapear_industria("mining"), "Minería")
        self.assertEqual(mapear_industria("FORESTAL"), "Forestal")

    def test_valor_no_mapeado_se_preserva(self):
        self.assertEqual(mapear_industria("Otro Rubro"), "OTRO RUBRO")


class TestNormalizarCliente(unittest.TestCase):
    """normalizar_cliente(): mayusculas, sin espacios sobrantes, sin tildes
    (no se agrega esa infraestructura, ver docstring de la funcion)."""

    def test_normaliza_mayusculas_y_espacios(self):
        self.assertEqual(normalizar_cliente("  transportes   michea spa  "), "TRANSPORTES MICHEA SPA")

    def test_none_es_vacio(self):
        self.assertEqual(normalizar_cliente(None), "")


class TestConstruirLookupRazonSocial(unittest.TestCase):
    """construir_lookup_razon_social(): agrupa por RAZÓN SOCIAL normalizada
    preservando las combinaciones reales de RUT/CDB/EJECUTIVO."""

    def test_df_vacio_devuelve_lookup_vacio(self):
        self.assertEqual(construir_lookup_razon_social(pd.DataFrame()), {})

    def test_agrupa_preservando_combinaciones_reales(self):
        df = pd.DataFrame({
            "RAZÓN SOCIAL": ["Transportes Bello", "Transportes Bello", "Otra Empresa"],
            "RUT": ["111", "111", "222"],
            "CDB": ["A1", "A2", "B1"],
            "EJECUTIVO": ["Juan", "Juan", "Ana"],
        })
        lookup = construir_lookup_razon_social(df)
        self.assertEqual(len(lookup["TRANSPORTES BELLO"]), 2)
        cdbs = {c["CDB"] for c in lookup["TRANSPORTES BELLO"]}
        self.assertEqual(cdbs, {"A1", "A2"})


class TestBuscarCandidatosPorCliente(unittest.TestCase):
    """buscar_candidatos_por_cliente(): match exacto normalizado primero;
    si no hay, coincidencia por contencion de texto (sin fuzzy agresivo)."""

    def setUp(self):
        self.df = pd.DataFrame({
            "RAZÓN SOCIAL": ["Transportes Bello e Hijos", "Transportes Bello e Hijos", "Transportes Nihuil"],
            "RUT": ["111", "111", "333"],
            "CDB": ["A1", "A2", "C1"],
            "EJECUTIVO": ["Juan", "Juan", "Pedro"],
        })

    def test_cliente_con_unica_coincidencia(self):
        candidatos = buscar_candidatos_por_cliente(self.df, "Transportes Nihuil")
        self.assertEqual(len(candidatos), 1)
        self.assertEqual(candidatos[0]["CDB"], "C1")

    def test_cliente_con_multiples_cdb(self):
        candidatos = buscar_candidatos_por_cliente(self.df, "Transportes Bello e Hijos")
        self.assertEqual(len(candidatos), 2)
        self.assertEqual({c["CDB"] for c in candidatos}, {"A1", "A2"})

    def test_cliente_con_coincidencia_por_contencion(self):
        candidatos = buscar_candidatos_por_cliente(self.df, "TRANSPORTES BELLO")
        self.assertEqual(len(candidatos), 2)

    def test_cliente_sin_coincidencia(self):
        self.assertEqual(buscar_candidatos_por_cliente(self.df, "Empresa Inexistente SPA"), [])

    def test_cliente_vacio(self):
        self.assertEqual(buscar_candidatos_por_cliente(self.df, ""), [])

    def test_cliente_muy_corto_no_dispara_contencion_agresiva(self):
        self.assertEqual(buscar_candidatos_por_cliente(self.df, "SA"), [])


class TestMapearTipoServicioDesdePlan(unittest.TestCase):
    """mapear_tipo_servicio_desde_plan(): copia directa si coincide EXACTO
    (salvo mayusculas/minusculas) con el catalogo oficial; si no, '-' para
    revision manual (decision confirmada con el usuario, sin inventar)."""

    def test_valores_del_catalogo_se_copian_directo(self):
        for valor in ["Basico", "Full", "Full + CIV", "Medio", "Medio + CIV", "-"]:
            self.assertEqual(mapear_tipo_servicio_desde_plan(valor), valor)

    def test_diferencia_de_capitalizacion_se_normaliza(self):
        self.assertEqual(mapear_tipo_servicio_desde_plan("MEDIO + CIV"), "Medio + CIV")

    def test_placeholder_0_queda_en_guion(self):
        self.assertEqual(mapear_tipo_servicio_desde_plan("0"), "-")

    def test_vacio_o_nan_queda_en_guion(self):
        self.assertEqual(mapear_tipo_servicio_desde_plan(""), "-")
        self.assertEqual(mapear_tipo_servicio_desde_plan(float('nan')), "-")


if __name__ == '__main__':
    unittest.main()
