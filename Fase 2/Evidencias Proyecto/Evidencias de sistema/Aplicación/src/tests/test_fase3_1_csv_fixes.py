"""Pruebas de Fase 3.1 (correccion de los 3 hallazgos bloqueantes de Fase 3,
23-09-2026): soporte CSV en ExcelReader (Watchdog), ExcelWriter.add_new_rows_batch
(importacion Power BI) y DataManager.get_system_health (conteo de backups).
No tocan PruebasFM.xlsx real ni EXCEL_PATH real: todo corre sobre archivos
temporales, con config.settings/os.listdir parcheados por test (mismo patron
que test_excel_writer_csv_backend.py / test_fase2_csv_integration.py)."""

import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import config.settings
from src.core.excel_reader import ExcelReader
from src.core.excel_writer import ExcelWriter
from src.core.data_manager import DataManager, MainDataLoaderThread

COLUMNAS_COMERCIAL = [
    'VIN', 'CHASIS', 'MODELO', 'FLOTA VC', 'FLOTA VC 2', 'EJECUTIVO', 'RUT', 'CDB',
    'FORMA DE CONTRATO', 'TIPO DE SERVICIO', 'ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL',
    'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO', 'TIPO DE FACTURACIÓN',
    'CONTRATO CREADO EN JUSTTIME', 'INICIO', 'TERMINO', 'N CONTRATO 3PC',
    'ESTADO DEL CM', 'PAGO CM', 'RAZÓN SOCIAL',
]

FILAS_COMERCIAL = [
    ['YV2AAA0000000001', 'E000001', 'FH540', 'FLOTA A', '-', 'JUAN PEREZ', '76123456-7', '9990001',
     'ARRIENDO', 'FULL', 'Vigente', 'Activo', '01-01-2025', '12', '01-01-2026', 'MENSUAL',
     'SI', '01-01-2025', '01-06-2025', '-', '-', '-', 'EMPRESA UNO SPA'],
    ['YV2BBB0000000002', 'E000002', 'FMX500', 'FLOTA B', '-', 'ANA SOTO', '77654321-K', '9990002',
     'ARRIENDO', 'BASICO', 'Vigente', 'Activo', '15-03-2024', '-', 'MENSUAL', 'MENSUAL',
     'SI', '-', '-', '-', '-', '-', 'EMPRESA DOS LTDA'],
]


def _crear_csv_comercial(ruta):
    pd.DataFrame(FILAS_COMERCIAL, columns=COLUMNAS_COMERCIAL).to_csv(ruta, index=False, encoding='utf-8-sig')


def _crear_xlsx_comercial(ruta):
    df = pd.DataFrame(FILAS_COMERCIAL, columns=COLUMNAS_COMERCIAL)
    with pd.ExcelWriter(ruta, engine='openpyxl') as w:
        df.to_excel(w, sheet_name='BBDD (2)', index=False)


# =========================================================
# A. ExcelReader: soporte CSV (snapshot/lectura/comparacion)
# =========================================================
class TestExcelReaderCsv(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _reader_para(self, filepath):
        reader = ExcelReader()
        reader.filepath = filepath
        reader.snapshot_path = os.path.join(self.temp_dir.name, ".snapshot_comercial_test.pkl")
        return reader

    def test_lectura_comercial_xlsx_sigue_funcionando(self):
        ruta = os.path.join(self.temp_dir.name, "PruebasFM_reader.xlsx")
        _crear_xlsx_comercial(ruta)
        reader = self._reader_para(ruta)
        data = reader.get_commercial_data()
        self.assertEqual(len(data), 2)
        vins = {r['VIN'] for r in data}
        self.assertEqual(vins, {'YV2AAA0000000001', 'YV2BBB0000000002'})

    def test_lectura_comercial_csv_funciona(self):
        ruta = os.path.join(self.temp_dir.name, "PruebasFM_reader.csv")
        _crear_csv_comercial(ruta)
        reader = self._reader_para(ruta)
        data = reader.get_commercial_data()
        self.assertEqual(len(data), 2)
        vins = {r['VIN'] for r in data}
        self.assertEqual(vins, {'YV2AAA0000000001', 'YV2BBB0000000002'})

    def test_lectura_general_y_operaciones_csv_funcionan(self):
        ruta = os.path.join(self.temp_dir.name, "PruebasFM_reader2.csv")
        _crear_csv_comercial(ruta)
        reader = self._reader_para(ruta)
        data_general = reader.get_general_data()
        data_operaciones = reader.get_operaciones_data()
        self.assertEqual(len(data_general), 2)
        self.assertEqual(len(data_operaciones), 2)
        self.assertIn('RAZÓN SOCIAL', data_general[0])

    def test_compare_snapshot_csv_detecta_cambio_externo(self):
        ruta = os.path.join(self.temp_dir.name, "PruebasFM_reader3.csv")
        _crear_csv_comercial(ruta)
        reader = self._reader_para(ruta)

        # Snapshot inicial (equivalente a la primera carga de la app).
        self.assertTrue(reader.create_snapshot())

        # Cambio externo controlado: se simula "alguien mas edito el CSV"
        # reescribiendo el archivo directamente, sin pasar por ExcelWriter.
        df = pd.read_csv(ruta, dtype=str, keep_default_na=False)
        df.loc[df['VIN'] == 'YV2AAA0000000001', 'ESTADO COMERCIAL'] = 'Baja'
        df.to_csv(ruta, index=False, encoding='utf-8-sig')

        cambios = reader.compare_snapshot()
        self.assertTrue(cambios, "Fallo: compare_snapshot() no detecto el cambio externo en CSV.")
        campos_cambiados = {c['campo'] for c in cambios}
        self.assertIn('ESTADO COMERCIAL', campos_cambiados)
        cambio_estado = next(c for c in cambios if c['campo'] == 'ESTADO COMERCIAL')
        self.assertEqual(cambio_estado['VIN'], 'YV2AAA0000000001')
        self.assertEqual(cambio_estado['nuevo'], 'Baja')

    def test_compare_snapshot_xlsx_sigue_funcionando(self):
        ruta = os.path.join(self.temp_dir.name, "PruebasFM_reader4.xlsx")
        _crear_xlsx_comercial(ruta)
        reader = self._reader_para(ruta)

        self.assertTrue(reader.create_snapshot())

        df = pd.read_excel(ruta)
        df.loc[df['VIN'] == 'YV2BBB0000000002', 'ESTADO COMERCIAL'] = 'Baja'
        with pd.ExcelWriter(ruta, engine='openpyxl') as w:
            df.to_excel(w, sheet_name='BBDD (2)', index=False)

        cambios = reader.compare_snapshot()
        self.assertTrue(cambios, "Fallo: compare_snapshot() dejo de funcionar para XLSX tras el cambio.")
        campos_cambiados = {c['campo'] for c in cambios}
        self.assertIn('ESTADO COMERCIAL', campos_cambiados)


# =========================================================
# B. ExcelWriter.add_new_rows_batch: soporte CSV (importacion Power BI)
# =========================================================
COLUMNAS_BATCH = [
    'VIN', 'CHASIS', 'MODELO', 'RAZÓN SOCIAL', 'ESTADO COMERCIAL', 'INICIO CONTRATO',
]

FILA_EXISTENTE = ['YV2ZZZ0000000000', 'E000000', 'FH540', 'EMPRESA EXISTENTE', 'Vigente', '01-01-2020']


class TestAddNewRowsBatch(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.writer = ExcelWriter()
        self.writer.log_filepath = ""
        self.writer.log_csv_filepath = os.path.join(self.temp_dir.name, "LogApp_test.csv")
        self.writer.deleted_filepath = os.path.join(self.temp_dir.name, "RegistroEliminado_test.xlsx")

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch('src.core.excel_writer.ExcelWriter._crear_backup')
    def test_batch_csv_agrega_lote_y_persiste(self, mock_backup):
        csv_path = os.path.join(self.temp_dir.name, "PruebasFM_batch.csv")
        pd.DataFrame([FILA_EXISTENTE], columns=COLUMNAS_BATCH).to_csv(csv_path, index=False, encoding='utf-8-sig')

        lote = [
            {'VIN': 'YV2NEW0000000001', 'CHASIS': 'E100001', 'MODELO': 'FMX500',
             'RAZÓN SOCIAL': 'EMPRESA POWERBI UNO', 'ESTADO COMERCIAL': 'Vigente', 'INICIO CONTRATO': '01-01-2026'},
            {'VIN': 'YV2NEW0000000002', 'CHASIS': 'E100002', 'MODELO': 'FH540',
             'RAZÓN SOCIAL': 'EMPRESA POWERBI DOS', 'ESTADO COMERCIAL': 'Vigente', 'INICIO CONTRATO': '02-01-2026'},
        ]

        res = self.writer.add_new_rows_batch(lote, module_name="Test PowerBI", custom_filepath=csv_path)
        self.assertTrue(res)

        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        self.assertEqual(len(df), 3)  # 1 existente + 2 del lote
        fila1 = df[df['VIN'] == 'YV2NEW0000000001'].iloc[0]
        self.assertEqual(fila1['MODELO'], 'FMX500')
        self.assertEqual(fila1['RAZÓN SOCIAL'], 'EMPRESA POWERBI UNO')
        fila2 = df[df['VIN'] == 'YV2NEW0000000002'].iloc[0]
        self.assertEqual(fila2['RAZÓN SOCIAL'], 'EMPRESA POWERBI DOS')
        # La fila preexistente no debe alterarse.
        fila_vieja = df[df['VIN'] == 'YV2ZZZ0000000000'].iloc[0]
        self.assertEqual(fila_vieja['MODELO'], 'FH540')

        # Persistencia: recarga real via MainDataLoaderThread (simula reinicio).
        thread = MainDataLoaderThread(csv_path)
        resultado = {}
        thread.data_loaded_signal.connect(lambda payload: resultado.update(payload=payload))
        thread.run()
        df_recargado = resultado['payload'][0]
        self.assertEqual(len(df_recargado), 3)
        self.assertIn('YV2NEW0000000001', df_recargado['VIN'].values)
        self.assertIn('YV2NEW0000000002', df_recargado['VIN'].values)

    @patch('src.core.excel_writer.ExcelWriter._crear_backup')
    def test_batch_xlsx_sigue_funcionando(self, mock_backup):
        xlsx_path = os.path.join(self.temp_dir.name, "PruebasFM_batch.xlsx")
        with pd.ExcelWriter(xlsx_path, engine='openpyxl') as w:
            pd.DataFrame([FILA_EXISTENTE], columns=COLUMNAS_BATCH).to_excel(w, sheet_name='BBDD (2)', index=False)

        lote = [
            {'VIN': 'YV2NEW0000000003', 'CHASIS': 'E100003', 'MODELO': 'FH540',
             'RAZÓN SOCIAL': 'EMPRESA POWERBI TRES', 'ESTADO COMERCIAL': 'Vigente', 'INICIO CONTRATO': '03-01-2026'},
        ]

        res = self.writer.add_new_rows_batch(lote, module_name="Test PowerBI", custom_filepath=xlsx_path)
        self.assertTrue(res)

        df = pd.read_excel(xlsx_path)
        self.assertEqual(len(df), 2)
        fila_nueva = df[df['VIN'] == 'YV2NEW0000000003'].iloc[0]
        self.assertEqual(fila_nueva['RAZÓN SOCIAL'], 'EMPRESA POWERBI TRES')

    def test_batch_vacio_no_hace_nada(self):
        csv_path = os.path.join(self.temp_dir.name, "PruebasFM_batch_vacio.csv")
        pd.DataFrame([FILA_EXISTENTE], columns=COLUMNAS_BATCH).to_csv(csv_path, index=False, encoding='utf-8-sig')
        res = self.writer.add_new_rows_batch([], module_name="Test", custom_filepath=csv_path)
        self.assertTrue(res)
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        self.assertEqual(len(df), 1)


# =========================================================
# C. DataManager.get_system_health: conteo de backups por extension real
# =========================================================
class TestGetSystemHealthBackupCount(unittest.TestCase):
    def setUp(self):
        self.dm = DataManager()

    @patch('os.listdir')
    def test_conteo_backups_xlsx(self, mock_listdir):
        mock_listdir.return_value = [
            'PruebasFM_backup_1.xlsx', 'PruebasFM_backup_2.xlsx', 'PruebasFM_backup_3.csv', 'notas.txt',
        ]
        with patch.object(config.settings, 'EXCEL_PATH', 'C:/ruta/ficticia/PruebasFM.xlsx'):
            health = self.dm.get_system_health()
        self.assertEqual(health['backups_count'], 2)

    @patch('os.listdir')
    def test_conteo_backups_csv(self, mock_listdir):
        mock_listdir.return_value = [
            'PruebasFM_backup_1.xlsx', 'PruebasFM_backup_2.csv', 'PruebasFM_backup_3.csv', 'notas.txt',
        ]
        with patch.object(config.settings, 'EXCEL_PATH', 'C:/ruta/ficticia/RM_JAVI.csv'):
            health = self.dm.get_system_health()
        self.assertEqual(health['backups_count'], 2)


if __name__ == '__main__':
    unittest.main()
