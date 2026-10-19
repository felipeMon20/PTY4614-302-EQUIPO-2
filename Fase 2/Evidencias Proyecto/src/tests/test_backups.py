import os
import unittest
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch
import openpyxl
from PyQt6.QtWidgets import QMessageBox
import config.settings
from src.core.excel_writer import ExcelWriter


class TestBackups(unittest.TestCase):
    """Punto B: valida el mecanismo central de respaldo (_crear_backup),
    reutilizado ahora por los puntos de escritura que antes lo evitaban."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.writer = ExcelWriter()
        self.writer.backup_dir = os.path.join(self.temp_dir.name, "backups")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _crear_excel_simple(self, path, valor="A"):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws['A1'] = valor
        wb.save(path)
        wb.close()

    def test_crea_backup_con_nombre_correcto_y_preserva_original(self):
        origen = os.path.join(self.temp_dir.name, "PruebasFM_Test.xlsx")
        self._crear_excel_simple(origen, "original")

        ok = self.writer._crear_backup(origen)

        self.assertTrue(ok)
        self.assertTrue(self.writer.last_backup_ok)
        backups = os.listdir(self.writer.backup_dir)
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].startswith("PruebasFM_Test_backup_"))
        self.assertTrue(backups[0].endswith(".xlsx"))

        wb_check = openpyxl.load_workbook(origen)
        self.assertEqual(wb_check.active['A1'].value, "original", "Fallo: el archivo original no debe modificarse al crear el backup.")
        wb_check.close()

        backup_path = os.path.join(self.writer.backup_dir, backups[0])
        wb_backup = openpyxl.load_workbook(backup_path)
        self.assertEqual(wb_backup.active['A1'].value, "original")
        wb_backup.close()

    def test_archivo_inexistente_no_falla_y_no_crea_nada(self):
        origen = os.path.join(self.temp_dir.name, "no_existe_todavia.xlsx")
        ok = self.writer._crear_backup(origen)

        self.assertTrue(ok, "Fallo: si no hay archivo que respaldar todavia, no debe tratarse como error.")
        self.assertTrue(self.writer.last_backup_ok)
        self.assertFalse(os.path.exists(self.writer.backup_dir) and os.listdir(self.writer.backup_dir))

    def test_fallo_en_copia_no_interrumpe_y_marca_last_backup_ok_false(self):
        origen = os.path.join(self.temp_dir.name, "PruebasFM_Test2.xlsx")
        self._crear_excel_simple(origen)

        with patch('src.core.excel_writer.shutil.copy2', side_effect=PermissionError("bloqueado")):
            ok = self.writer._crear_backup(origen)  # no debe lanzar excepcion

        self.assertFalse(ok)
        self.assertFalse(self.writer.last_backup_ok, "Fallo: last_backup_ok debe quedar en False para que la UI pueda avisar.")

    def test_destino_no_disponible_no_interrumpe_y_marca_last_backup_ok_false(self):
        origen = os.path.join(self.temp_dir.name, "PruebasFM_Test3.xlsx")
        self._crear_excel_simple(origen)

        with patch('src.core.excel_writer.os.makedirs', side_effect=OSError("disco lleno o sin permisos")):
            ok = self.writer._crear_backup(origen)  # no debe lanzar excepcion

        self.assertFalse(ok)
        self.assertFalse(self.writer.last_backup_ok)

    def test_retencion_mantiene_solo_los_ultimos_10_por_archivo(self):
        origen = os.path.join(self.temp_dir.name, "contactos_Test.xlsx")
        self._crear_excel_simple(origen)

        # _crear_backup nombra el archivo con resolucion de 1 segundo
        # (%Y%m%d_%H%M%S). Para probar la poda sin esperar 12 segundos reales,
        # se fuerza un datetime.now() distinto (1s de diferencia) en cada
        # llamada; el mtime real de cada copia sigue siendo unico de todas formas.
        base = datetime(2026, 1, 1, 10, 0, 0)
        with patch('src.core.excel_writer.datetime') as mock_dt:
            mock_dt.now.side_effect = [base + timedelta(seconds=i) for i in range(12)]
            for _ in range(12):
                self.writer._crear_backup(origen)

        backups = [f for f in os.listdir(self.writer.backup_dir) if f.startswith("contactos_Test_backup_")]
        self.assertEqual(len(backups), 10, "Fallo: deben conservarse solo los ultimos 10 backups de este archivo.")

    def test_backups_de_archivos_distintos_no_interfieren_entre_si(self):
        origen_a = os.path.join(self.temp_dir.name, "PruebasFM_Test.xlsx")
        origen_b = os.path.join(self.temp_dir.name, "provisionContratos_Test.xlsx")
        self._crear_excel_simple(origen_a)
        self._crear_excel_simple(origen_b)

        base = datetime(2026, 1, 1, 10, 0, 0)
        with patch('src.core.excel_writer.datetime') as mock_dt:
            mock_dt.now.side_effect = [base + timedelta(seconds=i) for i in range(11)]
            for _ in range(11):
                self.writer._crear_backup(origen_a)
        self.writer._crear_backup(origen_b)

        backups_a = [f for f in os.listdir(self.writer.backup_dir) if f.startswith("PruebasFM_Test_backup_")]
        backups_b = [f for f in os.listdir(self.writer.backup_dir) if f.startswith("provisionContratos_Test_backup_")]
        self.assertEqual(len(backups_a), 10, "Fallo: la poda de PruebasFM no debe verse afectada por Provisiones.")
        self.assertEqual(len(backups_b), 1, "Fallo: el backup de Provisiones no debio ser podado ni afectado por el de PruebasFM.")


class TestPuntoCAbortaEscrituraSiBackupFalla(unittest.TestCase):
    """Punto C: update_cells, add_new_row, delete_row y overwrite_dataframe
    deben abortar la escritura (sin tocar el archivo original) si el backup
    previo (_crear_backup) fallo, en vez de escribir igual como ocurria antes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.writer = ExcelWriter()
        self.writer.backup_dir = os.path.join(self.temp_dir.name, "backups")
        self.writer.temp_dir = os.path.join(self.temp_dir.name, "temp")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _crear_excel_comercial(self, path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "BBDD (2)"
        ws.append(["VIN", "MODELO"])
        ws.append(["YV2TEST0001", "FM"])
        wb.save(path)
        wb.close()

    def _forzar_backup_fallido(self):
        def falla(*a, **k):
            self.writer.last_backup_ok = False
            return False
        return patch.object(self.writer, '_crear_backup', side_effect=falla)

    def test_update_cells_aborta_si_backup_falla(self):
        excel_path = os.path.join(self.temp_dir.name, "PruebasFM_puntoC.xlsx")
        self._crear_excel_comercial(excel_path)
        mtime_original = os.path.getmtime(excel_path)

        with self._forzar_backup_fallido():
            resultado = self.writer.update_cells(
                {"fila1": {"keys": {"VIN": "YV2TEST0001"}, "cambios": {"MODELO": "FMX"}}},
                module_name="Test", custom_filepath=excel_path, sheet_name="BBDD (2)"
            )

        self.assertFalse(resultado, "Fallo: update_cells debe devolver False si el backup previo fallo.")
        self.assertEqual(os.path.getmtime(excel_path), mtime_original, "Fallo: el archivo original no debe modificarse.")
        wb_check = openpyxl.load_workbook(excel_path)
        self.assertEqual(wb_check["BBDD (2)"].cell(row=2, column=2).value, "FM", "Fallo: el valor no debio cambiar.")
        wb_check.close()

    def test_add_new_row_aborta_si_backup_falla(self):
        excel_path = os.path.join(self.temp_dir.name, "PruebasFM_puntoC_add.xlsx")
        self._crear_excel_comercial(excel_path)
        mtime_original = os.path.getmtime(excel_path)

        with self._forzar_backup_fallido():
            resultado = self.writer.add_new_row({"VIN": "YV2NUEVO", "MODELO": "FH"}, module_name="Test", custom_filepath=excel_path)

        self.assertFalse(resultado)
        self.assertEqual(os.path.getmtime(excel_path), mtime_original)
        wb_check = openpyxl.load_workbook(excel_path)
        self.assertEqual(wb_check["BBDD (2)"].max_row, 2, "Fallo: no debio agregarse ninguna fila nueva.")
        wb_check.close()

    def test_delete_row_aborta_si_backup_falla(self):
        excel_path = os.path.join(self.temp_dir.name, "PruebasFM_puntoC_del.xlsx")
        self._crear_excel_comercial(excel_path)
        mtime_original = os.path.getmtime(excel_path)

        with self._forzar_backup_fallido():
            resultado = self.writer.delete_row(primary_key_val="YV2TEST0001", module_name="Test", custom_filepath=excel_path)

        self.assertFalse(resultado)
        self.assertEqual(os.path.getmtime(excel_path), mtime_original)
        wb_check = openpyxl.load_workbook(excel_path)
        self.assertEqual(wb_check["BBDD (2)"].max_row, 2, "Fallo: la fila no debio eliminarse.")
        wb_check.close()

    def test_overwrite_dataframe_aborta_si_backup_falla(self):
        import pandas as pd
        excel_path = os.path.join(self.temp_dir.name, "PruebasFM_puntoC_overwrite.xlsx")
        self._crear_excel_comercial(excel_path)
        mtime_original = os.path.getmtime(excel_path)

        with self._forzar_backup_fallido():
            df_nuevo = pd.DataFrame({"VIN": ["YV2OTRO"], "MODELO": ["FMX"]})
            resultado = self.writer.overwrite_dataframe(df_nuevo, sheet_name="BBDD (2)", custom_filepath=excel_path)

        self.assertFalse(resultado)
        self.assertEqual(os.path.getmtime(excel_path), mtime_original)

    def test_backup_exitoso_permite_escritura_normal(self):
        """Control: con backup exitoso (comportamiento real, sin mockear), la escritura procede normalmente."""
        excel_path = os.path.join(self.temp_dir.name, "PruebasFM_puntoC_ok.xlsx")
        self._crear_excel_comercial(excel_path)

        resultado = self.writer.update_cells(
            {"fila1": {"keys": {"VIN": "YV2TEST0001"}, "cambios": {"MODELO": "FMX"}}},
            module_name="Test", custom_filepath=excel_path, sheet_name="BBDD (2)"
        )
        self.assertTrue(resultado)
        self.assertTrue(self.writer.last_backup_ok)
        wb_check = openpyxl.load_workbook(excel_path)
        self.assertEqual(wb_check["BBDD (2)"].cell(row=2, column=2).value, "FMX")
        wb_check.close()

    def test_permission_error_en_backup_marca_last_backup_ok_false_y_aborta(self):
        excel_path = os.path.join(self.temp_dir.name, "PruebasFM_puntoC_perm.xlsx")
        self._crear_excel_comercial(excel_path)

        with patch('src.core.excel_writer.shutil.copy2', side_effect=PermissionError("bloqueado")):
            resultado = self.writer.update_cells(
                {"fila1": {"keys": {"VIN": "YV2TEST0001"}, "cambios": {"MODELO": "FMX"}}},
                module_name="Test", custom_filepath=excel_path, sheet_name="BBDD (2)"
            )

        self.assertFalse(resultado)
        self.assertFalse(self.writer.last_backup_ok)
        wb_check = openpyxl.load_workbook(excel_path)
        self.assertEqual(wb_check["BBDD (2)"].cell(row=2, column=2).value, "FM", "Fallo: no debio escribirse con backup fallido por PermissionError.")
        wb_check.close()

    def test_oserror_en_backup_marca_last_backup_ok_false_y_aborta(self):
        excel_path = os.path.join(self.temp_dir.name, "PruebasFM_puntoC_os.xlsx")
        self._crear_excel_comercial(excel_path)
        self.writer.backup_dir = os.path.join(self.temp_dir.name, "backups_inexistente")

        with patch('src.core.excel_writer.os.makedirs', side_effect=OSError("disco lleno o sin permisos")):
            resultado = self.writer.add_new_row({"VIN": "YV2X", "MODELO": "FH"}, module_name="Test", custom_filepath=excel_path)

        self.assertFalse(resultado)
        self.assertFalse(self.writer.last_backup_ok)
        wb_check = openpyxl.load_workbook(excel_path)
        self.assertEqual(wb_check["BBDD (2)"].max_row, 2, "Fallo: no debio agregarse fila con backup fallido por OSError.")
        wb_check.close()


class TestLogDeletedNoDestruyeRegistroExistente(unittest.TestCase):
    """_log_deleted no debe destruir RegistroEliminado.xlsx ante un fallo de
    lectura (antes hacia os.remove + reconstruia el libro desde cero), y
    debe respaldarlo con _crear_backup antes de guardar, igual que el resto
    de ExcelWriter."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.writer = ExcelWriter()
        self.writer.backup_dir = os.path.join(self.temp_dir.name, "backups")
        self.writer.deleted_filepath = os.path.join(self.temp_dir.name, "RegistroEliminado_Test.xlsx")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _crear_registro_existente(self, filas=1):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Comercial"
        ws.append(["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO", "VIN"])
        for i in range(filas):
            ws.append(["2026-08-01 09:00:00", "Comercial", f"YV2EXISTENTE{i}"])
        wb.save(self.writer.deleted_filepath)
        wb.close()

    def test_fallo_de_lectura_no_elimina_el_archivo_existente(self):
        self._crear_registro_existente(filas=2)
        with open(self.writer.deleted_filepath, 'rb') as f:
            contenido_original = f.read()

        with patch('src.core.excel_writer.openpyxl.load_workbook', side_effect=Exception("archivo corrupto simulado")):
            self.writer._log_deleted(["VIN"], ["YV2NUEVO"], "Comercial")

        self.assertTrue(os.path.exists(self.writer.deleted_filepath),
                         "Fallo: el archivo no debe eliminarse ante un fallo de lectura.")
        with open(self.writer.deleted_filepath, 'rb') as f:
            contenido_tras_fallo = f.read()
        self.assertEqual(contenido_original, contenido_tras_fallo,
                          "Fallo: el archivo existente no debe modificarse si la lectura falla.")

    def test_fallo_de_lectura_no_deja_archivo_corrupto(self):
        self._crear_registro_existente(filas=1)

        with patch('src.core.excel_writer.openpyxl.load_workbook', side_effect=Exception("archivo corrupto simulado")):
            self.writer._log_deleted(["VIN"], ["YV2NUEVO"], "Comercial")

        # El archivo debe seguir siendo un xlsx valido y legible, con los datos originales intactos
        wb_check = openpyxl.load_workbook(self.writer.deleted_filepath)
        ws_check = wb_check["Comercial"]
        self.assertEqual(ws_check.max_row, 2, "Fallo: debe conservarse solo el encabezado + la fila original (sin la nueva).")
        wb_check.close()

    def test_escritura_normal_registra_la_fila_correctamente(self):
        self.writer._log_deleted(["VIN", "MODELO"], ["YV2NUEVO", "FH"], "Comercial")

        self.assertTrue(os.path.exists(self.writer.deleted_filepath))
        wb_check = openpyxl.load_workbook(self.writer.deleted_filepath)
        ws_check = wb_check["Comercial"]
        self.assertEqual(ws_check.max_row, 2)  # encabezado + 1 fila
        self.assertEqual(ws_check.cell(row=2, column=3).value, "YV2NUEVO")
        self.assertEqual(ws_check.cell(row=2, column=4).value, "FH")
        wb_check.close()

    def test_backup_se_genera_antes_del_save_y_refleja_el_estado_previo(self):
        self._crear_registro_existente(filas=1)

        self.writer._log_deleted(["VIN"], ["YV2NUEVO"], "Comercial")

        self.assertTrue(os.path.exists(self.writer.backup_dir),
                         "Fallo: deberia haberse creado un backup antes de guardar.")
        backups = [f for f in os.listdir(self.writer.backup_dir) if f.startswith("RegistroEliminado_Test_backup_")]
        self.assertEqual(len(backups), 1, "Fallo: debe existir exactamente un backup del estado previo al guardado.")

        wb_backup = openpyxl.load_workbook(os.path.join(self.writer.backup_dir, backups[0]))
        ws_backup = wb_backup["Comercial"]
        self.assertEqual(ws_backup.max_row, 2,
                          "Fallo: el backup debe reflejar el estado ANTES de agregar la nueva fila (encabezado + 1 fila original).")
        wb_backup.close()


class TestLogDeletedSeparaPorModuloYEsquema(unittest.TestCase):
    """RegistroEliminado.xlsx debe guardar una hoja por modulo (module_name),
    cada una con el esquema propio de su origen (sin esquema artificial comun
    ni relleno de columnas inexistentes), sin sobrescribir filas historicas y
    sin desplazar columnas si el esquema de origen cambia entre eliminaciones."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.writer = ExcelWriter()
        self.writer.backup_dir = os.path.join(self.temp_dir.name, "backups")
        self.writer.deleted_filepath = os.path.join(self.temp_dir.name, "RegistroEliminado_Test.xlsx")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_modulos_distintos_generan_hojas_separadas_con_su_propio_esquema(self):
        self.writer._log_deleted(["ID", "Nombre", "Correo electrónico"], ["458", "Ana", "ana@x.example"], "Contactos")
        self.writer._log_deleted(["VIN", "MODELO", "CDB"], ["YV2ABC0001", "FM", "999"], "Comercial")

        wb = openpyxl.load_workbook(self.writer.deleted_filepath)
        self.assertIn("Contactos", wb.sheetnames)
        self.assertIn("Comercial", wb.sheetnames)

        ws_contactos = wb["Contactos"]
        self.assertEqual(
            [c.value for c in ws_contactos[1]],
            ["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO", "ID", "Nombre", "Correo electrónico"]
        )
        self.assertEqual(ws_contactos.max_row, 2, "Fallo: la hoja Contactos no debe recibir filas de Comercial.")

        ws_comercial = wb["Comercial"]
        self.assertEqual(
            [c.value for c in ws_comercial[1]],
            ["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO", "VIN", "MODELO", "CDB"]
        )
        self.assertEqual(ws_comercial.max_row, 2, "Fallo: la hoja Comercial no debe recibir filas de Contactos.")
        wb.close()

    def test_segundo_registro_del_mismo_modulo_se_agrega_sin_sobrescribir(self):
        self.writer._log_deleted(["VIN"], ["YV2AAA"], "Comercial")
        self.writer._log_deleted(["VIN"], ["YV2BBB"], "Comercial")

        wb = openpyxl.load_workbook(self.writer.deleted_filepath)
        ws = wb["Comercial"]
        self.assertEqual(ws.max_row, 3, "Fallo: deben existir encabezado + 2 filas, sin sobrescribir la primera.")
        self.assertEqual(ws.cell(row=2, column=3).value, "YV2AAA")
        self.assertEqual(ws.cell(row=3, column=3).value, "YV2BBB")
        wb.close()

    def test_hoja_nueva_se_crea_automaticamente_si_no_existe(self):
        self.writer._log_deleted(["VIN"], ["YV2AAA"], "Comercial")
        # RegistroEliminado.xlsx ya existe (con hoja "Comercial"); "Provisiones" es nueva.
        self.writer._log_deleted(["VIN", "AÑO - MES"], ["YV2ZZZ", "2026 - Julio"], "Provisiones")

        wb = openpyxl.load_workbook(self.writer.deleted_filepath)
        self.assertIn("Provisiones", wb.sheetnames)
        ws_prov = wb["Provisiones"]
        self.assertEqual([c.value for c in ws_prov[1]], ["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO", "VIN", "AÑO - MES"])
        self.assertEqual(ws_prov.max_row, 2)

        # La hoja Comercial ya existente no debe verse afectada por la hoja nueva.
        ws_com = wb["Comercial"]
        self.assertEqual(ws_com.max_row, 2)
        wb.close()

    def test_esquema_distinto_en_el_mismo_modulo_crea_hoja_versionada_sin_tocar_la_original(self):
        self.writer._log_deleted(["VIN", "MODELO"], ["YV2AAA", "FM"], "Comercial")
        # El Excel de origen de "Comercial" cambio de esquema (se agrego una columna nueva).
        self.writer._log_deleted(["VIN", "MODELO", "INDUSTRIA"], ["YV2BBB", "FH", "Minería"], "Comercial")

        wb = openpyxl.load_workbook(self.writer.deleted_filepath)
        self.assertIn("Comercial", wb.sheetnames)
        self.assertIn("Comercial (2)", wb.sheetnames)

        ws_original = wb["Comercial"]
        self.assertEqual([c.value for c in ws_original[1]], ["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO", "VIN", "MODELO"])
        self.assertEqual(ws_original.max_row, 2, "Fallo: la hoja original no debe recibir la fila con el esquema nuevo.")
        self.assertEqual(ws_original.cell(row=2, column=3).value, "YV2AAA")

        ws_v2 = wb["Comercial (2)"]
        self.assertEqual([c.value for c in ws_v2[1]], ["FECHA Y HORA DE ELIMINACIÓN", "MÓDULO", "VIN", "MODELO", "INDUSTRIA"])
        self.assertEqual(ws_v2.max_row, 2)
        self.assertEqual(ws_v2.cell(row=2, column=3).value, "YV2BBB")
        wb.close()


class TestRestoreBackupValidation(unittest.TestCase):
    """Valida el guard agregado en configuracion.py::_restore_backup que
    impide restaurar sobre EXCEL_PATH un backup que en realidad pertenece
    a otro archivo (ej. un backup de Contactos o Provisiones)."""

    def setUp(self):
        from src.ui.configuracion import ConfiguracionModule
        self.module = ConfiguracionModule()

    def test_bloquea_restaurar_backup_de_otro_archivo(self):
        backup_ajeno = os.path.join(os.getcwd(), 'data', 'backups', "contactos_Test_backup_20260101_000000.xlsx")

        with patch('src.ui.configuracion.QFileDialog.getOpenFileName', return_value=(backup_ajeno, '')), \
             patch('src.ui.configuracion.QMessageBox.critical') as mock_critical, \
             patch('src.ui.configuracion.QMessageBox.question') as mock_question, \
             patch('src.ui.configuracion.shutil.copy2') as mock_copy:
            self.module._restore_backup()

        mock_critical.assert_called_once()
        mock_question.assert_not_called()
        mock_copy.assert_not_called()

    def test_permite_continuar_con_backup_del_archivo_correcto(self):
        # configuracion.py importa EXCEL_PATH con "from config.settings import EXCEL_PATH"
        # al momento de cargarse el modulo, asi que el valor vigente en ese
        # modulo (no en config.settings, que puede haberse recargado despues)
        # es el que _restore_backup usa realmente para comparar.
        from src.ui.configuracion import EXCEL_PATH as EXCEL_PATH_EN_USO
        nombre_base = os.path.splitext(os.path.basename(EXCEL_PATH_EN_USO))[0]  # igual que configuracion.py (xlsx o csv)
        backup_correcto = os.path.join(os.getcwd(), 'data', 'backups', f"{nombre_base}_backup_20260101_000000.xlsx")

        with patch('src.ui.configuracion.QFileDialog.getOpenFileName', return_value=(backup_correcto, '')), \
             patch('src.ui.configuracion.QMessageBox.critical') as mock_critical, \
             patch('src.ui.configuracion.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as mock_question, \
             patch('src.ui.configuracion.shutil.copy2') as mock_copy:
            self.module._restore_backup()

        mock_critical.assert_not_called()
        mock_question.assert_called_once()
        mock_copy.assert_not_called()  # el usuario respondio "No" a la confirmacion final

    def test_backup_del_estado_actual_falla_cancela_la_restauracion(self):
        from src.ui.configuracion import EXCEL_PATH as EXCEL_PATH_EN_USO
        nombre_base = os.path.splitext(os.path.basename(EXCEL_PATH_EN_USO))[0]  # igual que configuracion.py (xlsx o csv)
        backup_correcto = os.path.join(os.getcwd(), 'data', 'backups', f"{nombre_base}_backup_20260101_000000.xlsx")

        def backup_fallido(self, target_filepath=None):
            self.last_backup_ok = False
            return False

        with patch('src.ui.configuracion.QFileDialog.getOpenFileName', return_value=(backup_correcto, '')), \
             patch('src.ui.configuracion.QMessageBox.critical') as mock_critical, \
             patch('src.ui.configuracion.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
             patch('src.core.excel_writer.ExcelWriter._crear_backup', new=backup_fallido), \
             patch('src.ui.configuracion.shutil.copy2') as mock_copy:
            self.module._restore_backup()

        mock_critical.assert_called_once()
        mock_copy.assert_not_called()

    def test_backup_del_estado_actual_exitoso_permite_restaurar(self):
        from src.ui.configuracion import EXCEL_PATH as EXCEL_PATH_EN_USO
        nombre_base = os.path.splitext(os.path.basename(EXCEL_PATH_EN_USO))[0]  # igual que configuracion.py (xlsx o csv)
        backup_correcto = os.path.join(os.getcwd(), 'data', 'backups', f"{nombre_base}_backup_20260101_000000.xlsx")

        def backup_exitoso(self, target_filepath=None):
            self.last_backup_ok = True
            return True

        with patch('src.ui.configuracion.QFileDialog.getOpenFileName', return_value=(backup_correcto, '')), \
             patch('src.ui.configuracion.QMessageBox.critical') as mock_critical, \
             patch('src.ui.configuracion.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
             patch('src.ui.configuracion.QMessageBox.information') as mock_info, \
             patch('src.core.excel_writer.ExcelWriter._crear_backup', new=backup_exitoso), \
             patch('src.ui.configuracion.shutil.copy2') as mock_copy, \
             patch('src.ui.configuracion.QProcess'), \
             patch('src.ui.configuracion.QApplication.quit'):
            self.module._restore_backup()

        mock_critical.assert_not_called()
        mock_copy.assert_called_once_with(backup_correcto, EXCEL_PATH_EN_USO)
        mock_info.assert_called_once()

    def test_backup_del_estado_actual_ocurre_antes_de_restaurar(self):
        from src.ui.configuracion import EXCEL_PATH as EXCEL_PATH_EN_USO
        nombre_base = os.path.splitext(os.path.basename(EXCEL_PATH_EN_USO))[0]  # igual que configuracion.py (xlsx o csv)
        backup_correcto = os.path.join(os.getcwd(), 'data', 'backups', f"{nombre_base}_backup_20260101_000000.xlsx")

        llamadas = []

        def backup_exitoso(self, target_filepath=None):
            llamadas.append('crear_backup_estado_actual')
            self.last_backup_ok = True
            return True

        def copy2_fake(origen, destino):
            llamadas.append('restaurar_backup_elegido')

        with patch('src.ui.configuracion.QFileDialog.getOpenFileName', return_value=(backup_correcto, '')), \
             patch('src.ui.configuracion.QMessageBox.critical'), \
             patch('src.ui.configuracion.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes), \
             patch('src.ui.configuracion.QMessageBox.information'), \
             patch('src.core.excel_writer.ExcelWriter._crear_backup', new=backup_exitoso), \
             patch('src.ui.configuracion.shutil.copy2', side_effect=copy2_fake), \
             patch('src.ui.configuracion.QProcess'), \
             patch('src.ui.configuracion.QApplication.quit'):
            self.module._restore_backup()

        self.assertEqual(llamadas, ['crear_backup_estado_actual', 'restaurar_backup_elegido'],
                          "Fallo: el backup del estado actual debe crearse ANTES de restaurar el backup elegido.")


if __name__ == '__main__':
    unittest.main()
