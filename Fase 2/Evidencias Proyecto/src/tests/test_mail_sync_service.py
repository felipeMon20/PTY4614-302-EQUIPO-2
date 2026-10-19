import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.services import mail_sync_service
from src.services.mail_sync_service import (
    cruzar_correos_maestro, guardar_correos_excel, vins_faltantes_en_correos, ExcelWriter,
)


def _comercial(**overrides):
    fila = {
        'CDB': '99999', 'CDB FLOTA': '12345', 'VIN': '9BWZZZ377VT900053', 'CHASIS': 'CHS001',
        'RAZÓN SOCIAL': 'TRANSPORTES ACME', 'RUT': '31.455.522-3',
        'TIPO DE SERVICIO': 'FULL', 'TERMINO': '31-12-2026',
    }
    fila.update(overrides)
    return pd.DataFrame([fila])


class TestCruzarCorreosMaestro(unittest.TestCase):
    """Cruce Comercial + Contactos por CDB FLOTA (desde el 08-10-2026; Power BI
    y el CDB comercial ya no participan). El helper _comercial usa un CDB
    comercial distinto del CDB FLOTA para comprobar que solo se usa este
    ultimo. Funcion pura, sin PyQt/QThread/DataManager."""

    def test_match_normal(self):
        df_comercial = _comercial()
        df_pbi = pd.DataFrame([{'CDB': '12345', 'Nombre': 'ACME SPA', 'RUT': '31.463.441-8'}])
        df_contactos = pd.DataFrame([{'CDB': '12345', 'Correo electrónico': 'contacto@acme.example'}])

        resultado = cruzar_correos_maestro(df_comercial, df_pbi, df_contactos)

        self.assertEqual(len(resultado), 1)
        fila = resultado.iloc[0]
        self.assertEqual(fila['VIN'], '9BWZZZ377VT900053')
        self.assertEqual(fila['CHASIS'], 'CHS001')
        # Razon social y RUT salen de Comercial; el Nombre/RUT de Power BI no se usan.
        self.assertEqual(fila['RAZÓN SOCIAL'], 'TRANSPORTES ACME')
        self.assertEqual(fila['RUT'], '31.455.522-3')
        self.assertEqual(fila['TIPO DE SERVICIO'], 'FULL')
        self.assertEqual(fila['FECHA TERMINO'], '31-12-2026')
        self.assertEqual(fila['CORREO ELECTRÓNICO'], 'contacto@acme.example')

    def test_sin_match(self):
        df_comercial = _comercial(**{'CDB FLOTA': '99999'})
        df_pbi = pd.DataFrame([{'CDB': '11111', 'Nombre': 'OTRA EMPRESA', 'RUT': '2-8'}])
        df_contactos = pd.DataFrame([{'CDB': '11111', 'Correo electrónico': 'otro@empresa.example'}])

        resultado = cruzar_correos_maestro(df_comercial, df_pbi, df_contactos)

        self.assertEqual(len(resultado), 1, "La fila de Comercial debe incluirse aunque no haya match.")
        fila = resultado.iloc[0]
        self.assertEqual(fila['RAZÓN SOCIAL'], 'TRANSPORTES ACME')
        self.assertEqual(fila['RUT'], '31.455.522-3')
        self.assertEqual(fila['CORREO ELECTRÓNICO'], '')

    def test_power_bi_no_completa_razon_social_ni_rut(self):
        df_comercial = _comercial(**{'RAZÓN SOCIAL': '', 'RUT': ''})
        df_pbi = pd.DataFrame([
            {'CDB': '12345', 'Nombre': 'PRIMERA COINCIDENCIA', 'RUT': '11-1'},
            {'CDB': '12345', 'Nombre': 'SEGUNDA COINCIDENCIA', 'RUT': '22-2'},
        ])
        df_contactos = pd.DataFrame(columns=['CDB', 'Correo electrónico'])

        resultado = cruzar_correos_maestro(df_comercial, df_pbi, df_contactos)

        fila = resultado.iloc[0]
        self.assertEqual(fila['RAZÓN SOCIAL'], '')
        self.assertEqual(fila['RUT'], '')

    def test_multiples_contactos_se_concatenan_con_punto_y_coma(self):
        df_comercial = _comercial()
        df_pbi = pd.DataFrame(columns=['CDB', 'Nombre', 'RUT'])
        df_contactos = pd.DataFrame([
            {'CDB': '12345', 'Correo electrónico': 'correo1@empresa.example'},
            {'CDB': '12345', 'Correo electrónico': 'correo2@empresa.example'},
        ])

        resultado = cruzar_correos_maestro(df_comercial, df_pbi, df_contactos)

        self.assertEqual(resultado.iloc[0]['CORREO ELECTRÓNICO'], 'correo1@empresa.example; correo2@empresa.example')

    def test_correos_duplicados_del_mismo_cdb_no_se_repiten(self):
        df_comercial = _comercial()
        df_pbi = pd.DataFrame(columns=['CDB', 'Nombre', 'RUT'])
        df_contactos = pd.DataFrame([
            {'CDB': '12345', 'Correo electrónico': 'correo1@empresa.example'},
            {'CDB': '12345', 'Correo electrónico': 'correo1@empresa.example'},
        ])

        resultado = cruzar_correos_maestro(df_comercial, df_pbi, df_contactos)

        self.assertEqual(resultado.iloc[0]['CORREO ELECTRÓNICO'], 'correo1@empresa.example')

    def test_sin_fallback_de_razon_social_desde_power_bi_cuando_comercial_vacio(self):
        df_comercial = _comercial(**{'RAZÓN SOCIAL': ''})
        df_pbi = pd.DataFrame([{'CDB': '12345', 'Nombre': 'EMPRESA TEST', 'RUT': '9-9'}])
        df_contactos = pd.DataFrame(columns=['CDB', 'Correo electrónico'])

        resultado = cruzar_correos_maestro(df_comercial, df_pbi, df_contactos)

        fila = resultado.iloc[0]
        self.assertEqual(fila['RAZÓN SOCIAL'], '')
        self.assertEqual(fila['RUT'], '31.455.522-3')

    def test_razon_social_vacia_equivalente_nan_none_cero_queda_vacia(self):
        for valor_vacio in ['', 'nan', 'None', '<NA>', '0', '0.0']:
            with self.subTest(valor_vacio=valor_vacio):
                df_comercial = _comercial(**{'RAZÓN SOCIAL': valor_vacio})
                df_pbi = pd.DataFrame([{'CDB': '12345', 'Nombre': 'EMPRESA FALLBACK', 'RUT': ''}])
                df_contactos = pd.DataFrame(columns=['CDB', 'Correo electrónico'])

                resultado = cruzar_correos_maestro(df_comercial, df_pbi, df_contactos)

                self.assertEqual(resultado.iloc[0]['RAZÓN SOCIAL'], '')

    def test_comercial_vacio_no_lanza_excepcion_y_devuelve_vacio(self):
        # La validacion "Comercial vacio -> error" sigue viviendo en
        # CorreosSyncWorker.run() (no se movio aqui): la funcion pura, dada
        # una entrada vacia, simplemente no produce filas.
        df_comercial = pd.DataFrame()
        df_pbi = pd.DataFrame([{'CDB': '12345', 'Nombre': 'X', 'RUT': 'Y'}])
        df_contactos = pd.DataFrame([{'CDB': '12345', 'Correo electrónico': 'x@x.example'}])

        resultado = cruzar_correos_maestro(df_comercial, df_pbi, df_contactos)

        self.assertTrue(resultado.empty)

    def test_termino_contrato_como_fallback_de_termino(self):
        df_comercial = pd.DataFrame([{
            'CDB': '1', 'VIN': 'V1', 'CHASIS': 'C1',
            'RAZÓN SOCIAL': 'ACME', 'RUT': '1-1',
            'TIPO DE SERVICIO': 'FULL', 'TÉRMINO CONTRATO': '15-06-2027',
        }])
        resultado = cruzar_correos_maestro(df_comercial, pd.DataFrame(), pd.DataFrame())
        self.assertEqual(resultado.iloc[0]['FECHA TERMINO'], '15-06-2027')

    def test_variante_razon_social_con_tilde_ra(self):
        df_comercial = pd.DataFrame([{
            'CDB': '1', 'VIN': 'V1', 'CHASIS': 'C1',
            'RÁZON SOCIAL': 'ACME VARIANTE', 'RUT': '1-1',
            'TIPO DE SERVICIO': 'FULL', 'TERMINO': '01-01-2027',
        }])
        resultado = cruzar_correos_maestro(df_comercial, pd.DataFrame(), pd.DataFrame())
        self.assertEqual(resultado.iloc[0]['RAZÓN SOCIAL'], 'ACME VARIANTE')

    def test_no_agrega_columna_flota(self):
        resultado = cruzar_correos_maestro(_comercial(), pd.DataFrame(), pd.DataFrame())
        self.assertNotIn('FLOTA', resultado.columns)
        self.assertNotIn('Flota', resultado.columns)
        self.assertIn('RAZÓN SOCIAL', resultado.columns)

    def test_no_deja_columna_cdb_oculto(self):
        resultado = cruzar_correos_maestro(_comercial(), pd.DataFrame(), pd.DataFrame())
        self.assertNotIn('_CDB_OCULTO', resultado.columns)


class TestGuardarCorreosExcel(unittest.TestCase):
    """guardar_correos_excel(): backup (mecanismo real de ExcelWriter, sin
    modificarlo salvo la correccion de extension del propio backup) antes
    de escribir; si el backup falla, no se escribe nada. B-5.2 (migracion
    XLSX -> CSV, 18-09-2026): el nombre de la funcion y de esta clase de
    test se conservan tal cual (ver mail_sync_service.py), solo cambio el
    formato de archivo que produce."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.temp_dir.name, "Correos.csv")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_guarda_el_csv_cuando_el_backup_es_exitoso(self):
        df = pd.DataFrame([{"RAZÓN SOCIAL": "ACME"}])

        # Aisla ExcelWriter.backup_dir (basado en os.getcwd()) dentro del
        # temp_dir de este test, para no escribir en data/backups/ real.
        with patch('src.core.excel_writer.os.getcwd', return_value=self.temp_dir.name):
            ok, mensaje = guardar_correos_excel(df, self.ruta)

        self.assertTrue(ok)
        self.assertTrue(os.path.exists(self.ruta))
        self.assertIn("guardado exitosamente", mensaje)

    def test_no_escribe_el_csv_si_el_backup_falla(self):
        df = pd.DataFrame([{"RAZÓN SOCIAL": "ACME"}])

        class _ExcelWriterBackupFallido:
            def __init__(self):
                self.last_backup_ok = True

            def _crear_backup(self, ruta):
                self.last_backup_ok = False
                return False

        with patch('src.services.mail_sync_service.ExcelWriter', _ExcelWriterBackupFallido):
            ok, mensaje = guardar_correos_excel(df, self.ruta)

        self.assertFalse(ok)
        self.assertFalse(os.path.exists(self.ruta))
        self.assertIn("copia de seguridad", mensaje)


class TestVinsFaltantesEnCorreos(unittest.TestCase):
    """vins_faltantes_en_correos(): usado por comercial.py (Gestionar CM ->
    Enviar Correo) para detectar VIN que Correos.csv aun no tiene -- no
    confundir con "VIN presente pero sin correo asignado" (celda vacia),
    que MailDialog ya resuelve por su cuenta."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.temp_dir.name, "Correos.csv")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _guardar(self, vins):
        pd.DataFrame({"VIN": vins, "CORREO ELECTRÓNICO": ["" for _ in vins]}).to_csv(self.ruta, index=False)

    def test_todos_presentes_devuelve_lista_vacia(self):
        self._guardar(["VIN1", "VIN2"])
        self.assertEqual(vins_faltantes_en_correos(["VIN1", "VIN2"], self.ruta), [])

    def test_detecta_los_que_faltan_preservando_orden_de_entrada(self):
        self._guardar(["VIN1"])
        self.assertEqual(vins_faltantes_en_correos(["VIN1", "VIN2", "VIN3"], self.ruta), ["VIN2", "VIN3"])

    def test_comparacion_insensible_a_mayusculas_y_espacios(self):
        self._guardar(["vin1  "])
        self.assertEqual(vins_faltantes_en_correos(["  VIN1"], self.ruta), [])

    def test_archivo_inexistente_marca_todos_como_faltantes(self):
        ruta_inexistente = os.path.join(self.temp_dir.name, "no_existe.csv")
        self.assertEqual(vins_faltantes_en_correos(["VIN1", "VIN2"], ruta_inexistente), ["VIN1", "VIN2"])

    def test_lista_vacia_de_entrada_no_lee_el_archivo(self):
        self.assertEqual(vins_faltantes_en_correos([], self.ruta), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
