import unittest

import pandas as pd

from src.services.facturacion_manual_service import (
    filtrar_facturacion_manual, obtener_empresas, obtener_unidades_empresa,
    seleccionar_columnas_detalle, construir_contexto_empresa, COLUMNAS_DETALLE_EMPRESA,
)
from src.core.constants import COL_RAZON_SOCIAL, COL_RUT, COL_TIPO_FACTURACION


def _df_master_mock():
    return pd.DataFrame({
        "RAZÓN SOCIAL": ["MAQSA", "MAQSA", "GENERA", "CLIENTE X", "CLIENTE X"],
        "RUT": ["969670100", "969670100", "764188616", "111111111", "111111111"],
        "VIN": ["VIN1", "VIN2", "VIN3", "VIN4", "VIN5"],
        "CHASIS": ["E1", "E2", "E3", "E4", "E5"],
        "FLOTA VC": ["MAQSA", "MAQSA", "GENERA", "CLIENTE X", "CLIENTE X"],
        "TIPO DE SERVICIO": ["MEDIO", "MEDIO", "FULL", "BASICO", "BASICO"],
        "ESTADO COMERCIAL": ["VIGENTE", "VIGENTE", "VIGENTE", "VENCIDO", "VIGENTE"],
        "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO", "CONECTADO", "CONECTADO", "DESCONECTADO", "CONECTADO"],
        "MODELO": ["FM", "FM", "FMX", "FH", "FH"],
        "INICIO CONTRATO": ["01-01-2026"] * 5,
        "TÉRMINO CONTRATO": ["01-01-2027"] * 5,
        "TIPO DE FACTURACION": [
            "FACTURACIÓN MANUAL", "FACTURACIÓN MANUAL", "FACTURACIÓN MANUAL",
            "CM", "-",
        ],
    })


class TestFiltrarFacturacionManual(unittest.TestCase):
    """El valor real confirmado en PruebasFM.xlsx lleva tilde: 'FACTURACIÓN
    MANUAL'. Este filtro no debe aceptar variantes sin tilde ni otros valores
    de TIPO DE FACTURACION (CM, '-', etc.)."""

    def test_filtra_solo_facturacion_manual(self):
        resultado = filtrar_facturacion_manual(_df_master_mock())
        self.assertEqual(len(resultado), 3)
        self.assertTrue((resultado[COL_TIPO_FACTURACION] == "FACTURACIÓN MANUAL").all())

    def test_no_acepta_variante_sin_tilde(self):
        df = pd.DataFrame({
            COL_RAZON_SOCIAL: ["X"],
            COL_TIPO_FACTURACION: ["FACTURACION MANUAL"],
        })
        resultado = filtrar_facturacion_manual(df)
        self.assertTrue(resultado.empty)

    def test_df_vacio(self):
        resultado = filtrar_facturacion_manual(pd.DataFrame())
        self.assertTrue(resultado.empty)

    def test_columna_ausente(self):
        df = pd.DataFrame({COL_RAZON_SOCIAL: ["X"]})
        resultado = filtrar_facturacion_manual(df)
        self.assertTrue(resultado.empty)

    def test_no_modifica_el_original(self):
        df_master = _df_master_mock()
        copia = df_master.copy()
        filtrar_facturacion_manual(df_master)
        pd.testing.assert_frame_equal(df_master, copia)


class TestObtenerEmpresas(unittest.TestCase):
    def test_una_fila_por_empresa_con_conteo_de_unidades(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        empresas = obtener_empresas(df_filtrado)

        self.assertEqual(set(empresas[COL_RAZON_SOCIAL]), {"MAQSA", "GENERA"})
        fila_maqsa = empresas[empresas[COL_RAZON_SOCIAL] == "MAQSA"].iloc[0]
        self.assertEqual(fila_maqsa["UNIDADES"], 2)
        self.assertEqual(fila_maqsa[COL_RUT], "969670100")

        fila_genera = empresas[empresas[COL_RAZON_SOCIAL] == "GENERA"].iloc[0]
        self.assertEqual(fila_genera["UNIDADES"], 1)

    def test_ordenado_alfabeticamente(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        empresas = obtener_empresas(df_filtrado)
        self.assertEqual(list(empresas[COL_RAZON_SOCIAL]), ["GENERA", "MAQSA"])

    def test_df_vacio(self):
        resultado = obtener_empresas(pd.DataFrame())
        self.assertTrue(resultado.empty)
        self.assertIn("UNIDADES", resultado.columns)


class TestObtenerUnidadesEmpresa(unittest.TestCase):
    def test_devuelve_solo_las_filas_de_la_empresa(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        unidades = obtener_unidades_empresa(df_filtrado, "MAQSA")

        self.assertEqual(len(unidades), 2)
        self.assertEqual(set(unidades["VIN"]), {"VIN1", "VIN2"})

    def test_empresa_sin_registros_en_facturacion_manual(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        unidades = obtener_unidades_empresa(df_filtrado, "CLIENTE X")
        self.assertTrue(unidades.empty)

    def test_recorta_a_columnas_de_detalle(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        unidades = obtener_unidades_empresa(df_filtrado, "MAQSA")
        self.assertEqual(list(unidades.columns), COLUMNAS_DETALLE_EMPRESA)

    def test_df_vacio(self):
        resultado = obtener_unidades_empresa(pd.DataFrame(), "MAQSA")
        self.assertTrue(resultado.empty)


class TestSeleccionarColumnasDetalle(unittest.TestCase):
    def test_conserva_solo_columnas_existentes(self):
        df = pd.DataFrame({"VIN": ["X"], "COLUMNA_INEXISTENTE": [1]})
        resultado = seleccionar_columnas_detalle(df)
        self.assertEqual(list(resultado.columns), ["VIN"])


class TestConstruirContextoEmpresa(unittest.TestCase):
    """Contexto minimo para la futura plantilla (ver informe 'Preparar
    contexto de plantilla', 19-09-2026): solo datos confirmados/derivables
    de df_master. No debe incluir OC/HES/precio UF/monto CLP -- eso depende
    de 'Facturación Manual - BBDD.xlsx' real, fuera de alcance de esta fase."""

    def test_datos_de_empresa(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        contexto = construir_contexto_empresa("MAQSA", df_filtrado)

        self.assertEqual(contexto["empresa"], {"razon_social": "MAQSA", "rut": "969670100"})
        self.assertEqual(contexto["cantidad_unidades"], 2)

    def test_unidades_con_alias_en_espanol_simple(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        contexto = construir_contexto_empresa("MAQSA", df_filtrado)

        vins = {u["vin"] for u in contexto["unidades"]}
        self.assertEqual(vins, {"VIN1", "VIN2"})
        primera = contexto["unidades"][0]
        self.assertEqual(
            set(primera.keys()),
            {"vin", "chasis", "tipo_servicio", "estado_comercial", "estado_activacion", "flota_vc", "modelo"},
        )

    def test_no_incluye_campos_de_la_bbdd_real(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        contexto = construir_contexto_empresa("MAQSA", df_filtrado)

        claves_prohibidas = {"oc", "hes", "precio_uf", "monto_clp", "n_oc", "cc"}
        self.assertFalse(claves_prohibidas & set(contexto.keys()))
        for unidad in contexto["unidades"]:
            self.assertFalse(claves_prohibidas & set(unidad.keys()))

    def test_empresa_sin_rut(self):
        df = pd.DataFrame({
            COL_RAZON_SOCIAL: ["SIN RUT SPA"],
            "VIN": ["VIN9"],
            COL_TIPO_FACTURACION: ["FACTURACIÓN MANUAL"],
        })
        df_filtrado = filtrar_facturacion_manual(df)
        contexto = construir_contexto_empresa("SIN RUT SPA", df_filtrado)
        self.assertIsNone(contexto["empresa"]["rut"])

    def test_empresa_sin_registros(self):
        df_filtrado = filtrar_facturacion_manual(_df_master_mock())
        contexto = construir_contexto_empresa("EMPRESA_INEXISTENTE", df_filtrado)
        self.assertEqual(contexto["cantidad_unidades"], 0)
        self.assertEqual(contexto["unidades"], [])

    def test_df_vacio(self):
        contexto = construir_contexto_empresa("MAQSA", pd.DataFrame())
        self.assertEqual(contexto["cantidad_unidades"], 0)
        self.assertIsNone(contexto["empresa"]["rut"])


if __name__ == '__main__':
    unittest.main()
