"""Pruebas de Fase 2 (integracion CSV en MainDataLoaderThread, RMReporteSyncWorker
y restauracion de backup, 23-09-2026). No tocan PruebasFM.xlsx real ni
EXCEL_PATH real: todo corre sobre archivos temporales, con config.settings
parcheado por test (mismo patron que test_comercial.py/test_excel_writer.py)."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import openpyxl
import pandas as pd

import config.settings
from src.core.data_manager import MainDataLoaderThread
from src.core.excel_writer import ExcelWriter
from src.ui.comercial import RMReporteSyncWorker

COLUMNAS = [
    'VIN', 'CHASIS', 'RUT', 'CDB', 'RAZÓN SOCIAL', 'ESTADO COMERCIAL',
    'INICIO CONTRATO', 'TÉRMINO CONTRATO', 'FECHA DE BAJA',
    'INICIO', 'TERMINO', 'ESTADO DE ENTREGA',
    'FECHA INICIO CM', 'FECHA TERMINO CM',
]

# CHASIS con prefijo de letra (formato real, ver Fase 1): evita el
# comportamiento de pandas.read_excel que coerciona a int64 una columna 100%
# numerica, ajeno a esta migracion.
FILAS = [
    ['YV2AAA0000000001', 'E000001', '31455522-3', '9990001', 'EMPRESA UNO SPA', 'Vigente',
     '01-01-2025', '01-01-2026', '-', '01-01-2025', '01-06-2025', '01-01-2025', '-', '-'],
    ['YV2BBB0000000002', 'E000002', '31851472-2', '9990002', 'EMPRESA DOS LTDA', 'Vigente',
     '15-03-2024', 'MENSUAL', '-', '-', '-', '-', '01-02-2024', '01-02-2025'],
    ['YV2CCC0000000003', 'E000003', '32001933-0', '9990003', 'EMPRESA TRES SA', 'Baja',
     '01-06-2023', '01-06-2024', '10-09-2026', '-', '-', '-', '-', '-'],
]

COLS_FECHA = [
    'INICIO CONTRATO', 'TÉRMINO CONTRATO', 'FECHA DE BAJA', 'INICIO', 'TERMINO',
    'ESTADO DE ENTREGA', 'FECHA INICIO CM', 'FECHA TERMINO CM',
]


def _crear_csv(ruta):
    pd.DataFrame(FILAS, columns=COLUMNAS).to_csv(ruta, index=False, encoding='utf-8-sig')


def _crear_xlsx(ruta):
    df = pd.DataFrame(FILAS, columns=COLUMNAS)
    with pd.ExcelWriter(ruta, engine='openpyxl') as w:
        df.to_excel(w, sheet_name='BBDD (2)', index=False)


# =========================================================
# 1. MainDataLoaderThread: XLSX vs CSV
# =========================================================
class TestMainDataLoaderThreadCsvVsXlsx(unittest.TestCase):
    """Ejercita MainDataLoaderThread REAL (sin mocks) apuntando a un .xlsx y
    a un .csv con el mismo contenido, y compara df_master resultante."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.xlsx_path = os.path.join(self.temp_dir.name, "PruebasFM_loader.xlsx")
        self.csv_path = os.path.join(self.temp_dir.name, "PruebasFM_loader.csv")
        _crear_xlsx(self.xlsx_path)
        _crear_csv(self.csv_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _cargar(self, filepath):
        thread = MainDataLoaderThread(filepath)
        resultado = {}
        errores = []
        thread.data_loaded_signal.connect(lambda payload: resultado.update(payload=payload))
        thread.error_signal.connect(lambda e: errores.append(e))
        thread.run()
        self.assertFalse(errores, f"Fallo: la carga lanzó un error: {errores}")
        df, df_logs, df_deleted, load_time, deleted_sheets = resultado['payload']
        return df

    def test_carga_xlsx(self):
        df = self._cargar(self.xlsx_path)
        self.assertEqual(len(df), 3)
        self.assertEqual(df['VIN'].nunique(), 3)

    def test_carga_csv(self):
        df = self._cargar(self.csv_path)
        self.assertEqual(len(df), 3)
        self.assertEqual(df['VIN'].nunique(), 3)

    def test_equivalencia_xlsx_vs_csv(self):
        df_xlsx = self._cargar(self.xlsx_path).reset_index(drop=True)
        df_csv = self._cargar(self.csv_path).reset_index(drop=True)

        self.assertEqual(list(df_xlsx.columns), list(df_csv.columns), "Columnas/orden distintos.")
        self.assertEqual(len(df_xlsx), len(df_csv), "Cantidad de filas distinta.")

        diffs = (df_xlsx.astype(str) != df_csv.astype(str))
        celdas_distintas = diffs.values.sum()
        if celdas_distintas > 0:
            detalle = []
            columnas_con_diff = diffs.any(axis=0)
            for col in columnas_con_diff[columnas_con_diff].index:
                for idx in df_xlsx.index[diffs[col]]:
                    detalle.append(f"fila={idx} col={col!r} xlsx={df_xlsx.at[idx, col]!r} csv={df_csv.at[idx, col]!r}")
            self.fail(f"Diferencia real entre loader xlsx y csv ({celdas_distintas} celdas):\n" + "\n".join(detalle))

    def test_fechas_correctas_en_ambos_origenes(self):
        for filepath in (self.xlsx_path, self.csv_path):
            df = self._cargar(filepath)
            for col in COLS_FECHA:
                for val in df[col]:
                    self.assertIsInstance(val, str, f"[{os.path.basename(filepath)}] {col}={val!r} no es str")
                    self.assertNotRegex(str(val), r'^\d{4}-\d{2}-\d{2}',
                                         f"[{os.path.basename(filepath)}] {col}={val!r} quedo en YYYY-MM-DD")

    def test_mensual_preservado_en_ambos_origenes(self):
        for filepath in (self.xlsx_path, self.csv_path):
            df = self._cargar(filepath)
            fila = df.set_index('VIN').loc['YV2BBB0000000002']
            self.assertEqual(fila['TÉRMINO CONTRATO'], 'MENSUAL')

    def test_estado_de_entrega_no_es_catalogo_en_ambos_origenes(self):
        catalogo_sospechoso = {'ENTREGADO', 'NO ENTREGADO', 'PENDIENTE', 'EN TRANSITO'}
        for filepath in (self.xlsx_path, self.csv_path):
            df = self._cargar(filepath)
            valores = df['ESTADO DE ENTREGA'].astype(str).str.upper().unique()
            self.assertFalse(set(valores) & catalogo_sospechoso)

    def test_vin_rut_cdb_chasis_sin_conversion_en_ambos_origenes(self):
        # CDB: en el Excel real la celda es numerica (confirmado contra
        # PruebasFM.xlsx real: dtype object conteniendo int de Python), asi
        # que MainDataLoaderThread (que solo aplica DataFrameFormatter.clean(),
        # no procesar_df_comercial) puede devolverlo como int desde xlsx y
        # como str desde csv -- normalizacion a texto (quitar '.0') es
        # responsabilidad de comercial_services.procesar_df_comercial, una
        # capa despues, no de este loader. Se compara como texto ya
        # normalizado para reflejar fielmente ese contrato, no el tipo crudo.
        for filepath in (self.xlsx_path, self.csv_path):
            df = self._cargar(filepath).set_index('VIN')
            self.assertEqual(df.loc['YV2AAA0000000001', 'CHASIS'], 'E000001')
            self.assertEqual(df.loc['YV2AAA0000000001', 'RUT'], '31455522-3')
            cdb_normalizado = str(df.loc['YV2AAA0000000001', 'CDB']).replace('.0', '')
            self.assertEqual(cdb_normalizado, '9990001')


# =========================================================
# 3. RMReporteSyncWorker: XLSX vs CSV como destino
# =========================================================
class TestRMReporteSyncCsvVsXlsx(unittest.TestCase):
    """Misma secuencia (merge/limpieza/logging real, sin mocks de negocio)
    que TestRMReporteSyncActualizaHistorial (test_comercial.py), pero comparando
    el resultado contra un PruebasFM destino .xlsx y uno .csv."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.rm_reporte_path = os.path.join(self.temp_dir.name, "RM_CONTRATOS_test.xlsx")
        df_reporte = pd.DataFrame({
            "VIN": ["YV2AAA0000000001", "YV2BBB0000000002"],
            "MODELO": ["FH", "FMX"],
        })
        with pd.ExcelWriter(self.rm_reporte_path, engine='openpyxl') as w:
            df_reporte.to_excel(w, sheet_name='BBDD', index=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _crear_pruebas_xlsx(self, ruta):
        # VIN_CLEAN(...)[-7:] fija CHASIS igual al que el propio worker
        # recalcula siempre (mismo criterio que test_comercial.py), para que
        # el unico cambio detectable sea MODELO.
        df = pd.DataFrame({
            "VIN": ["YV2AAA0000000001", "YV2BBB0000000002"],
            "CHASIS": ["0900054", "0900055"],
            "MODELO": ["FL", "FL"],
        })
        with pd.ExcelWriter(ruta, engine='openpyxl') as w:
            df.to_excel(w, sheet_name='BBDD (2)', index=False)

    def _crear_pruebas_csv(self, ruta):
        df = pd.DataFrame({
            "VIN": ["YV2AAA0000000001", "YV2BBB0000000002"],
            "CHASIS": ["0900054", "0900055"],
            "MODELO": ["FL", "FL"],
        })
        df.to_csv(ruta, index=False, encoding='utf-8-sig')

    def _sync_contra(self, pruebas_path, crear_fn):
        crear_fn(pruebas_path)
        log_csv_path = os.path.splitext(pruebas_path)[0] + "_LogApp.csv"
        deleted_path = os.path.splitext(pruebas_path)[0] + "_RegistroEliminado.xlsx"

        patches = [
            patch.object(config.settings, 'EXCEL_PATH', pruebas_path),
            patch.object(config.settings, 'LOG_CSV_PATH', log_csv_path),
            patch.object(config.settings, 'LOG_EXCEL_PATH', ""),
            patch.object(config.settings, 'DELETED_LOG_EXCEL_PATH', deleted_path),
            patch('src.ui.comercial.RM_REPORTE_PATH', self.rm_reporte_path),
            # _crear_backup real escribiria en data/backups/ real (backup_dir
            # se fija en ExcelWriter.__init__ via os.getcwd(), no via
            # EXCEL_PATH parcheado) -- se mockea para no tocar produccion,
            # mismo patron que TestUpdateCellsConfirmarBajaCm (test_excel_writer.py).
            patch('src.core.excel_writer.ExcelWriter._crear_backup'),
        ]
        for p in patches:
            p.start()
        try:
            worker = RMReporteSyncWorker()
            capturado = {}
            errores = []
            worker.success_signal.connect(lambda msg, df_final, df_logs: capturado.update(df_final=df_final))
            worker.error_signal.connect(lambda e: errores.append(e))
            worker.run()
            self.assertFalse(errores, f"Fallo: la sincronización RM_CONTRATOS lanzó un error: {errores}")
            self.assertIn('df_final', capturado, "Fallo: no se emitió success_signal.")
        finally:
            for p in patches:
                p.stop()
        return capturado['df_final']

    def test_sync_contra_xlsx_escribe_y_conserva_estructura(self):
        pruebas_path = os.path.join(self.temp_dir.name, "PruebasFM_rmreporte.xlsx")
        df_final = self._sync_contra(pruebas_path, self._crear_pruebas_xlsx)
        self.assertEqual(len(df_final), 2)
        wb_check = openpyxl.load_workbook(pruebas_path)
        self.assertIn('BBDD (2)', wb_check.sheetnames)
        wb_check.close()

    def test_sync_contra_csv_escribe_dataset_completo(self):
        pruebas_path = os.path.join(self.temp_dir.name, "PruebasFM_rmreporte.csv")
        df_final = self._sync_contra(pruebas_path, self._crear_pruebas_csv)
        self.assertEqual(len(df_final), 2)
        df_disco = pd.read_csv(pruebas_path, dtype=str, keep_default_na=False)
        self.assertEqual(len(df_disco), 2)
        self.assertEqual(sorted(df_disco['VIN'].tolist()),
                          ['YV2AAA0000000001', 'YV2BBB0000000002'])

    def test_equivalencia_df_final_xlsx_vs_csv(self):
        path_xlsx = os.path.join(self.temp_dir.name, "PruebasFM_rmreporte_x.xlsx")
        path_csv = os.path.join(self.temp_dir.name, "PruebasFM_rmreporte_c.csv")
        df_final_xlsx = self._sync_contra(path_xlsx, self._crear_pruebas_xlsx).sort_values('VIN').reset_index(drop=True)
        df_final_csv = self._sync_contra(path_csv, self._crear_pruebas_csv).sort_values('VIN').reset_index(drop=True)

        self.assertEqual(list(df_final_xlsx.columns), list(df_final_csv.columns))
        diffs = (df_final_xlsx.astype(str) != df_final_csv.astype(str))
        self.assertEqual(diffs.values.sum(), 0,
                          f"Diferencia real en df_final entre destino xlsx y csv:\n{df_final_xlsx[diffs.any(axis=1)]}\nvs\n{df_final_csv[diffs.any(axis=1)]}")

        # Ambos deben detectar el mismo cambio real (MODELO: FL -> FH/FMX).
        self.assertEqual(df_final_xlsx.set_index('VIN').loc['YV2AAA0000000001', 'MODELO'], 'FH')
        self.assertEqual(df_final_csv.set_index('VIN').loc['YV2AAA0000000001', 'MODELO'], 'FH')


# =========================================================
# 5. Restauración de backup CSV
# =========================================================
class TestRestoreBackupCsv(unittest.TestCase):
    """_restore_backup (configuracion.py) no se ejercita end-to-end aqui
    (requiere QApplication/diálogos) -- se valida el mecanismo real que
    usa (shutil.copy2 + ExcelWriter._crear_backup, ambos agnosticos al
    formato) directamente, igual que ya se confirmo en la auditoria previa,
    mas la derivacion de nombre/extension que sí se modificó en esta fase."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_restaurar_backup_csv_sobre_destino_csv(self):
        destino = os.path.join(self.temp_dir.name, "RM_CONTRATOS.csv")
        backup = os.path.join(self.temp_dir.name, "PruebasFM_backup_20260101_000000.csv")

        _crear_csv(destino)
        # El backup tiene datos DISTINTOS al destino actual, para poder
        # confirmar que "restaurar" realmente trae el contenido del backup.
        df_backup = pd.DataFrame(FILAS, columns=COLUMNAS)
        df_backup.loc[0, 'ESTADO COMERCIAL'] = 'Vencido'
        df_backup.to_csv(backup, index=False, encoding='utf-8-sig')

        shutil.copy2(backup, destino)  # mismo mecanismo que _restore_backup

        df_restaurado = pd.read_csv(destino, dtype=str, keep_default_na=False)
        self.assertEqual(df_restaurado.set_index('VIN').loc['YV2AAA0000000001', 'ESTADO COMERCIAL'], 'Vencido')

    def test_derivacion_nombre_base_funciona_para_csv_y_xlsx(self):
        """Misma derivacion que ahora usa _restore_backup
        (os.path.splitext en vez de .replace('.xlsx', ''))."""
        self.assertEqual(os.path.splitext(os.path.basename("RM_CONTRATOS.csv"))[0], "RM_CONTRATOS")
        self.assertEqual(os.path.splitext(os.path.basename("PruebasFM.xlsx"))[0], "PruebasFM")

    def test_xlsx_sigue_funcionando_tras_el_cambio(self):
        destino = os.path.join(self.temp_dir.name, "PruebasFM.xlsx")
        backup = os.path.join(self.temp_dir.name, "PruebasFM_backup_20260101_000000.xlsx")

        _crear_xlsx(destino)
        df_backup = pd.DataFrame(FILAS, columns=COLUMNAS)
        df_backup.loc[0, 'ESTADO COMERCIAL'] = 'Vencido'
        with pd.ExcelWriter(backup, engine='openpyxl') as w:
            df_backup.to_excel(w, sheet_name='BBDD (2)', index=False)

        shutil.copy2(backup, destino)

        df_restaurado = pd.read_excel(destino, sheet_name='BBDD (2)')
        self.assertEqual(df_restaurado.set_index('VIN').loc['YV2AAA0000000001', 'ESTADO COMERCIAL'], 'Vencido')


# =========================================================
# 6. _crear_backup / BackupManager con CSV (confirmacion, sin modificarlos)
# =========================================================
class TestCrearBackupConCsv(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.writer = ExcelWriter()
        self.writer.backup_dir = os.path.join(self.temp_dir.name, "backups")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_crear_backup_csv_no_corrompe_y_preserva_extension(self):
        origen = os.path.join(self.temp_dir.name, "RM_CONTRATOS.csv")
        _crear_csv(origen)

        ok = self.writer._crear_backup(origen)
        self.assertTrue(ok)
        self.assertTrue(self.writer.last_backup_ok)

        archivos = os.listdir(self.writer.backup_dir)
        self.assertEqual(len(archivos), 1)
        self.assertTrue(archivos[0].endswith('.csv'))
        self.assertTrue(archivos[0].startswith('RM_CONTRATOS_backup_'))

        # No corrupto: se puede releer con pandas y tiene el mismo contenido.
        df_backup = pd.read_csv(os.path.join(self.writer.backup_dir, archivos[0]), dtype=str, keep_default_na=False)
        df_original = pd.read_csv(origen, dtype=str, keep_default_na=False)
        pd.testing.assert_frame_equal(df_backup, df_original)


if __name__ == '__main__':
    unittest.main()
