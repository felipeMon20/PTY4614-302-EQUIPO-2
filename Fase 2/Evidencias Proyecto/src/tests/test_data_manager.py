import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

import config.settings
from src.core.data_manager import MainDataLoaderThread, formatear_columna_fecha_legado


def _formatear_valor(val):
    """Helper de test: aplica formatear_columna_fecha_legado() a un unico
    valor, envolviendolo en una Serie de una fila. La funcion real siempre
    opera sobre una columna completa (ver MainDataLoaderThread.run()), pero
    para probar casos individuales alcanza con una Serie de largo 1."""
    return formatear_columna_fecha_legado(pd.Series([val], dtype=object)).iloc[0]


class TestFormatearColumnaFechaLegadoCasosBase(unittest.TestCase):
    """Fase 2.1/2.2 (auditoria de rendimiento, 17-09-2026): protege el
    comportamiento EXACTO de formatear_columna_fecha_legado() (columnas
    INICIO/TERMINO/ESTADO DE ENTREGA/PERIODO INTERNO de PruebasFM, ver
    MainDataLoaderThread.run()) -- version vectorizada que reemplazo al
    procesamiento celda por celda anterior (safe_date_format, ya eliminado).
    Los valores esperados fueron calculados ejecutando la funcion original
    ANTES de vectorizar, no asumidos -- incluyen un bug conocido de
    pd.to_datetime(dayfirst=True) con fechas ISO ambiguas (dia/mes
    intercambiados cuando ambos son <=12, mismo bug ya documentado en
    dataframe_formatter.py para calcular_termino) que se preserva a
    proposito, no se corrige aqui."""

    def test_none(self):
        self.assertEqual(_formatear_valor(None), "")

    def test_float_nan(self):
        self.assertEqual(_formatear_valor(float('nan')), "")

    def test_pandas_nat(self):
        self.assertEqual(_formatear_valor(pd.NaT), "")

    def test_cadena_vacia(self):
        self.assertEqual(_formatear_valor(""), "")

    def test_cadena_solo_espacios(self):
        self.assertEqual(_formatear_valor("   "), "")

    def test_literal_nan_minuscula(self):
        self.assertEqual(_formatear_valor("nan"), "")

    def test_literal_nan_mayuscula(self):
        self.assertEqual(_formatear_valor("NaN"), "")

    def test_literal_nan_todo_mayuscula(self):
        self.assertEqual(_formatear_valor("NAN"), "")

    def test_guion_se_conserva_tal_cual(self):
        # '-' no cae en ninguno de los casos especiales (vacio/MENSUAL): pasa
        # por el intento de parseo de fecha, falla, y se devuelve tal cual.
        self.assertEqual(_formatear_valor("-"), "-")

    def test_mensual_mayuscula(self):
        self.assertEqual(_formatear_valor("MENSUAL"), "MENSUAL")

    def test_mensual_minuscula(self):
        self.assertEqual(_formatear_valor("mensual"), "MENSUAL")

    def test_mensual_capitalizado(self):
        self.assertEqual(_formatear_valor("Mensual"), "MENSUAL")

    def test_mensual_mezclado(self):
        self.assertEqual(_formatear_valor("MeNsUaL"), "MENSUAL")

    def test_fecha_string_ddmmyyyy(self):
        # Formato de negocio (dia/mes ya en el orden que dayfirst=True espera):
        # no hay ambiguedad, se conserva igual.
        self.assertEqual(_formatear_valor("05-03-2025"), "05-03-2025")

    def test_fecha_string_iso_con_bug_swap_dia_mes(self):
        # Bug conocido: '2025-04-10' (ISO, dia=10 mes=04) con
        # pd.to_datetime(dayfirst=True) intercambia dia/mes cuando ambos son
        # <=12. Resultado real confirmado ejecutando la funcion original
        # antes de vectorizar: '04-10-2025' (NO '10-04-2025'). Se preserva
        # tal cual, no se corrige aqui.
        self.assertEqual(_formatear_valor("2025-04-10"), "04-10-2025")

    def test_fecha_string_iso_con_hora_pegada(self):
        # El primer token (antes del espacio) es lo unico que se parsea;
        # mismo bug de swap que el caso anterior.
        self.assertEqual(_formatear_valor("2025-04-10 00:00:00"), "04-10-2025")

    def test_fecha_datetime_nativo(self):
        # str(datetime(...)) genera 'YYYY-MM-DD HH:MM:SS', que cae en el
        # mismo camino (y mismo bug de swap) que el string ISO con hora.
        self.assertEqual(_formatear_valor(datetime(2025, 4, 10)), "04-10-2025")

    def test_fecha_pandas_timestamp(self):
        self.assertEqual(_formatear_valor(pd.Timestamp("2025-04-10")), "04-10-2025")

    def test_texto_no_fecha_se_conserva_periodo_interno(self):
        # Caso real de PERIODO INTERNO: nunca es una fecha, siempre pasa sin
        # cambios por la excepcion de parseo.
        self.assertEqual(_formatear_valor("agosto - 2022"), "agosto - 2022")

    def test_texto_no_fecha_generico_se_conserva(self):
        self.assertEqual(_formatear_valor("texto cualquiera"), "texto cualquiera")

    def test_edge_case_nan_con_espacios_no_se_trata_como_vacio(self):
        # Bug/comportamiento real confirmado: la comparacion contra "nan" se
        # hace sobre el string SIN recortar (str_s, no texto), asi que
        # " NaN " (con espacios) NO coincide con "nan" y cae en el intento de
        # parseo de fecha; al fallar, devuelve el texto recortado 'NaN' (con
        # mayusculas originales), no ''. Distinto de "NaN" exacto (sin
        # espacios), que SI se trata como vacio. Se preserva tal cual.
        self.assertEqual(_formatear_valor(" NaN "), "NaN")
        self.assertEqual(_formatear_valor("NaN"), "")


class TestFormatearColumnaFechaLegadoColumnaCompleta(unittest.TestCase):
    """La funcion real siempre procesa una columna entera de una vez (no
    valor por valor): estos tests cubren la columna completa, incluyendo
    mezcla de tipos dentro de la misma Serie (como ocurre en los datos
    reales de INICIO/TERMINO/ESTADO DE ENTREGA, que mezclan str y datetime
    nativo segun como Excel/openpyxl tipo cada celda)."""

    def test_columna_mixta_todos_los_casos_a_la_vez(self):
        entradas = [
            None, float('nan'), pd.NaT, "", "   ",
            "nan", "NaN", "NAN", " NaN ",
            "-",
            "MENSUAL", "mensual", "Mensual", "MeNsUaL",
            "05-03-2025",
            "2025-04-10",
            "2025-04-10 00:00:00",
            datetime(2025, 4, 10),
            pd.Timestamp("2025-04-10"),
            "agosto - 2022",
            "texto cualquiera",
        ]
        esperado = [
            "", "", "", "", "",
            "", "", "", "NaN",
            "-",
            "MENSUAL", "MENSUAL", "MENSUAL", "MENSUAL",
            "05-03-2025",
            "04-10-2025",
            "04-10-2025",
            "04-10-2025",
            "04-10-2025",
            "agosto - 2022",
            "texto cualquiera",
        ]
        serie = pd.Series(entradas, dtype=object)
        obtenido = list(formatear_columna_fecha_legado(serie))
        self.assertEqual(obtenido, esperado)

    def test_columna_todo_vacia_no_falla(self):
        serie = pd.Series([None, float('nan'), pd.NaT], dtype=object)
        resultado = formatear_columna_fecha_legado(serie)
        self.assertEqual(list(resultado), ["", "", ""])

    def test_columna_todo_mensual_no_falla(self):
        serie = pd.Series(["MENSUAL", "mensual", "Mensual"], dtype=object)
        resultado = formatear_columna_fecha_legado(serie)
        self.assertEqual(list(resultado), ["MENSUAL", "MENSUAL", "MENSUAL"])

    def test_columna_todo_fechas_no_falla(self):
        serie = pd.Series(["05-03-2025", "06-03-2025", "07-03-2025"], dtype=object)
        resultado = formatear_columna_fecha_legado(serie)
        self.assertEqual(list(resultado), ["05-03-2025", "06-03-2025", "07-03-2025"])

    def test_periodo_interno_realista_no_se_altera(self):
        # Caso real de PruebasFM: PERIODO INTERNO nunca contiene fechas.
        serie = pd.Series(["agosto - 2022", "julio - 2025", "marzo - 2025"], dtype=object)
        resultado = formatear_columna_fecha_legado(serie)
        self.assertEqual(list(resultado), ["agosto - 2022", "julio - 2025", "marzo - 2025"])

    def test_estado_de_entrega_realista_mezcla_guion_y_fechas(self):
        # Caso real de ESTADO DE ENTREGA: mezcla dominante de '-' (no
        # entregado) con fechas reales de entrega.
        serie = pd.Series(["-", "05-03-2025", "-", "-", "06-03-2025"], dtype=object)
        resultado = formatear_columna_fecha_legado(serie)
        self.assertEqual(list(resultado), ["-", "05-03-2025", "-", "-", "06-03-2025"])


class TestMainDataLoaderThreadLecturaExcelPrincipal(unittest.TestCase):
    """Protege el comportamiento de MainDataLoaderThread.run() -- lectura
    de PruebasFM (hoja 'BBDD (2)') + DataFrameFormatter.clean() +
    formatear_columna_fecha_legado(), de punta a punta. Usa un Excel
    temporal generado en el test (mismo patron que test_excel_writer.py:
    TestExcelWriter), NO el archivo real de produccion."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self._log_excel_patch = patch.object(
            config.settings, 'LOG_EXCEL_PATH', os.path.join(self.temp_dir.name, "no_existe_log.xlsx"))
        self._log_csv_patch = patch.object(
            config.settings, 'LOG_CSV_PATH', os.path.join(self.temp_dir.name, "no_existe_log.csv"))
        self._deleted_patch = patch.object(
            config.settings, 'DELETED_LOG_EXCEL_PATH', os.path.join(self.temp_dir.name, "no_existe_deleted.xlsx"))
        self._log_excel_patch.start()
        self._log_csv_patch.start()
        self._deleted_patch.start()

    def tearDown(self):
        self._log_excel_patch.stop()
        self._log_csv_patch.stop()
        self._deleted_patch.stop()
        self.temp_dir.cleanup()

    def _crear_excel_prueba(self):
        excel_path = os.path.join(self.temp_dir.name, "PruebasFM_engine_test.xlsx")
        df = pd.DataFrame({
            'VIN': ['YV2A', 'YV2B', 'YV2C'],
            'CHASIS': ['C1', 'C2', 'C3'],
            'INICIO': ['-', None, datetime(2025, 4, 10)],
            'TERMINO': ['-', '-', '05-03-2025'],
            'ESTADO DE ENTREGA': ['-', 'MENSUAL', '-'],
            'PERIODO INTERNO': ['agosto - 2024', 'agosto - 2022', 'julio - 2025'],
        })
        df.to_excel(excel_path, index=False, sheet_name='BBDD (2)')
        return excel_path

    def _cargar_df(self, excel_path):
        resultado = {}

        def capturar(payload):
            df, df_logs, df_deleted, load_time, deleted_sheets = payload
            resultado['df'] = df

        thread = MainDataLoaderThread(excel_path)
        thread.data_loaded_signal.connect(capturar)
        thread.run()  # ejecucion sincronica directa (sin QThread real), mismo patron que test_excel_writer.py
        self.assertIn('df', resultado, "El hilo no emitio datos -- revisar error_signal (archivo invalido o corrupto).")
        return resultado['df']

    def test_filas_y_columnas(self):
        excel_path = self._crear_excel_prueba()
        df = self._cargar_df(excel_path)
        self.assertEqual(len(df), 3)
        self.assertEqual(
            list(df.columns),
            ['VIN', 'CHASIS', 'INICIO', 'TERMINO', 'ESTADO DE ENTREGA', 'PERIODO INTERNO'],
        )

    def test_valores_columnas_fecha_legado_tras_pipeline_completo(self):
        # Verifica el resultado FINAL (ya pasado por clean() +
        # formatear_columna_fecha_legado dentro de run()), no la lectura
        # cruda -- exactamente lo que ve el resto de la aplicacion.
        excel_path = self._crear_excel_prueba()
        df = self._cargar_df(excel_path)

        # INICIO fila 3 (datetime(2025, 4, 10), 10 de abril): '10-04-2025' es
        # el valor correcto (25-09-2026, fix de dataframe_formatter.py --
        # antes 'INICIO'/'TERMINO'/'ESTADO DE ENTREGA' no estaban en la lista
        # date_columns de DataFrameFormatter.clean(), que tenía los nombres
        # de columna de ANTES del renombrado RM_CONTRATOS_COLUMN_ALIASES y nunca
        # calzaban). Antes del fix, clean() no tocaba esta columna y el
        # Timestamp crudo llegaba tal cual a formatear_columna_fecha_legado(),
        # que sí re-parsea vía pd.to_datetime(dayfirst=True, format='mixed')
        # -- ahí es donde vive el bug de fechas ISO ambiguas ya documentado
        # (ver docstring de formatear_columna_fecha_legado), y producía
        # '04-10-2025' (día/mes invertido, año 2025 mal calculado como
        # octubre). Ahora clean() formatea el Timestamp directo con
        # .strftime() (sin re-parsear texto), así que nunca llega a activar
        # ese bug -- formatear_columna_fecha_legado solo recibe después un
        # '10-04-2025' ya correcto y lo deja intacto.
        self.assertEqual(list(df['INICIO']), ['-', '', '10-04-2025'])
        self.assertEqual(list(df['TERMINO']), ['-', '-', '05-03-2025'])
        self.assertEqual(list(df['ESTADO DE ENTREGA']), ['-', 'MENSUAL', '-'])
        self.assertEqual(list(df['PERIODO INTERNO']), ['agosto - 2024', 'agosto - 2022', 'julio - 2025'])

    def test_vin_y_chasis_no_se_alteran(self):
        excel_path = self._crear_excel_prueba()
        df = self._cargar_df(excel_path)
        self.assertEqual(list(df['VIN']), ['YV2A', 'YV2B', 'YV2C'])
        self.assertEqual(list(df['CHASIS']), ['C1', 'C2', 'C3'])


if __name__ == '__main__':
    unittest.main()
