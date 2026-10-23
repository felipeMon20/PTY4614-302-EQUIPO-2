import os
import time
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import config.settings
from src.core.backup_manager import BackupManager


class TestBackupManagerSnapshot(unittest.TestCase):
    """Snapshot completo (usado tanto por el backup manual como por el
    automatico semanal): copia unicamente los archivos maestros definidos
    explicitamente en config.settings, nunca por escaneo de carpetas."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.origen_dir = os.path.join(self.temp_dir.name, "origen")
        os.makedirs(self.origen_dir, exist_ok=True)

        self.manager = BackupManager()
        self.manager.auto_dir = os.path.join(self.temp_dir.name, "backup_auto")
        self.manager.manual_dir = os.path.join(self.temp_dir.name, "backupManual")
        self.manager.state_file = os.path.join(self.temp_dir.name, ".last_auto_backup.json")

        self.excel_path = self._crear_archivo("PruebasFM.xlsx")
        # LOG_EXCEL_PATH apunta a un .xlsx que NO existe: lo que debe
        # respaldarse es su .csv (historial oficial migrado), no el xlsx.
        self.log_xlsx_path = os.path.join(self.origen_dir, "LogApp.xlsx")
        self.log_csv_path = self._crear_archivo("LogApp.csv")
        self.deleted_path = self._crear_archivo("RegistroEliminado.xlsx")
        self.prov_path = self._crear_archivo("provisionFelipe.xlsx")

        self._patches = [
            patch.object(config.settings, 'EXCEL_PATH', self.excel_path),
            patch.object(config.settings, 'LOG_EXCEL_PATH', self.log_xlsx_path),
            patch.object(config.settings, 'LOG_CSV_PATH', self.log_csv_path),
            patch.object(config.settings, 'DELETED_LOG_EXCEL_PATH', self.deleted_path),
            patch.object(config.settings, 'PROVISION_EXCEL_PATH', self.prov_path),
            patch.object(config.settings, 'INSTALACIONES_PATH', ""),
            patch.object(config.settings, 'RM_JAVI_PATH', ""),
            patch.object(config.settings, 'POWERBI_EXCEL_PATH', ""),
            patch.object(config.settings, 'CONTACTOS_EXCEL_PATH', ""),
            patch.object(config.settings, 'CORREOS_EXCEL_PATH', ""),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.temp_dir.cleanup()

    def _crear_archivo(self, nombre, contenido="dato"):
        ruta = os.path.join(self.origen_dir, nombre)
        with open(ruta, 'w', encoding='utf-8') as f:
            f.write(contenido)
        return ruta

    def test_snapshot_copia_solo_los_archivos_maestros_configurados(self):
        resultado = self.manager.crear_backup_manual()

        self.assertIsNone(resultado.get("error_fatal"))
        self.assertTrue(os.path.isdir(resultado["carpeta"]))

        nombres_copiados = set(os.listdir(resultado["carpeta"]))
        self.assertEqual(
            nombres_copiados,
            {"PruebasFM.xlsx", "LogApp.csv", "RegistroEliminado.xlsx", "provisionFelipe.xlsx"},
        )
        self.assertNotIn("LogApp.xlsx", nombres_copiados, "Fallo: no debe copiarse el .xlsx legado, solo LogApp.csv.")

    def test_snapshot_incluye_logapp_csv_como_historial(self):
        resultado = self.manager.crear_backup_manual()
        self.assertIn("LogApp.csv", resultado["copiados"])

    def test_snapshot_omite_archivos_que_no_existen(self):
        os.remove(self.prov_path)
        resultado = self.manager.crear_backup_manual()

        self.assertIn("provisionFelipe.xlsx", resultado["omitidos"])
        self.assertNotIn("provisionFelipe.xlsx", resultado["copiados"])
        self.assertIn("PruebasFM.xlsx", resultado["copiados"])

    def test_snapshot_registra_fallidos_sin_detener_los_demas(self):
        real_copy2 = shutil.copy2

        def copy2_falla_selectivo(origen, destino):
            if os.path.basename(origen) == "provisionFelipe.xlsx":
                raise PermissionError("bloqueado")
            return real_copy2(origen, destino)

        with patch('src.core.backup_manager.shutil.copy2', side_effect=copy2_falla_selectivo):
            resultado = self.manager.crear_backup_manual()

        self.assertIn("provisionFelipe.xlsx", resultado["fallidos"])
        self.assertIn("PruebasFM.xlsx", resultado["copiados"])
        self.assertIn("LogApp.csv", resultado["copiados"])

    def test_snapshot_nunca_incluye_directorios_de_backup_ni_temp_ni_codigo(self):
        resultado = self.manager.crear_backup_manual()
        nombres = set(os.listdir(resultado["carpeta"]))
        prohibidos = {"backups", "backup_auto", "backupManual", "temp"}
        self.assertTrue(nombres.isdisjoint(prohibidos))
        self.assertTrue(all(not n.endswith(".py") for n in nombres))

    def test_snapshot_falla_total_no_deja_carpeta_vacia(self):
        for ruta in [self.excel_path, self.log_csv_path, self.deleted_path, self.prov_path]:
            os.remove(ruta)

        resultado = self.manager.crear_backup_manual()

        self.assertEqual(resultado.get("error_fatal"), "No se pudo copiar ningun archivo maestro (todos fallaron o no existen).")
        contenidos = os.listdir(self.manager.manual_dir) if os.path.exists(self.manager.manual_dir) else []
        self.assertEqual(contenidos, [], "Fallo: no debe quedar ninguna carpeta de snapshot vacia.")

    def test_snapshot_manual_no_se_autoelimina_al_crear_varios(self):
        base = datetime(2026, 1, 1, 10, 0, 0)
        with patch('src.core.backup_manager.datetime') as mock_dt:
            mock_dt.now.side_effect = [base.replace(second=i) for i in range(3)]
            carpetas = [self.manager.crear_backup_manual()["carpeta"] for _ in range(3)]

        for carpeta in carpetas:
            self.assertTrue(os.path.isdir(carpeta), "Fallo: los backups manuales no deben autoeliminarse.")
        self.assertEqual(len(set(carpetas)), 3)


class TestBackupManagerRetencionYProgramacion(unittest.TestCase):
    """Retencion de 5 snapshots automaticos y disparo semanal (solo viernes,
    maximo uno por semana ISO)."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.origen_dir = os.path.join(self.temp_dir.name, "origen")
        os.makedirs(self.origen_dir, exist_ok=True)

        self.manager = BackupManager()
        self.manager.auto_dir = os.path.join(self.temp_dir.name, "backup_auto")
        self.manager.manual_dir = os.path.join(self.temp_dir.name, "backupManual")
        self.manager.state_file = os.path.join(self.temp_dir.name, ".last_auto_backup.json")

        self.excel_path = os.path.join(self.origen_dir, "PruebasFM.xlsx")
        with open(self.excel_path, 'w', encoding='utf-8') as f:
            f.write("dato")

        self._patches = [
            patch.object(config.settings, 'EXCEL_PATH', self.excel_path),
            patch.object(config.settings, 'LOG_EXCEL_PATH', ""),
            patch.object(config.settings, 'LOG_CSV_PATH', ""),
            patch.object(config.settings, 'DELETED_LOG_EXCEL_PATH', ""),
            patch.object(config.settings, 'PROVISION_EXCEL_PATH', ""),
            patch.object(config.settings, 'INSTALACIONES_PATH', ""),
            patch.object(config.settings, 'RM_JAVI_PATH', ""),
            patch.object(config.settings, 'POWERBI_EXCEL_PATH', ""),
            patch.object(config.settings, 'CONTACTOS_EXCEL_PATH', ""),
            patch.object(config.settings, 'CORREOS_EXCEL_PATH', ""),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.temp_dir.cleanup()

    def _carpetas_auto(self):
        if not os.path.exists(self.manager.auto_dir):
            return []
        return [d for d in os.listdir(self.manager.auto_dir) if os.path.isdir(os.path.join(self.manager.auto_dir, d))]

    def test_retencion_elimina_los_mas_antiguos_y_deja_solo_el_maximo(self):
        os.makedirs(self.manager.auto_dir, exist_ok=True)
        base_time = datetime(2026, 1, 1).timestamp()
        carpetas = []
        for i in range(7):
            carpeta = os.path.join(self.manager.auto_dir, f"2026-01-{i+1:02d}_100000")
            os.makedirs(carpeta)
            ts = base_time + i * 86400
            os.utime(carpeta, (ts, ts))
            carpetas.append(carpeta)

        self.manager._aplicar_retencion(self.manager.auto_dir, 5)

        restantes = sorted(self._carpetas_auto())
        self.assertEqual(len(restantes), 5, "Fallo: deben quedar exactamente 5 snapshots automaticos.")
        esperados = sorted([os.path.basename(c) for c in carpetas[2:]])  # los 5 mas recientes
        self.assertEqual(restantes, esperados)

    def test_backup_semanal_no_pendiente_si_no_es_viernes(self):
        with patch('src.core.backup_manager.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 7, 10, 0, 0)  # lunes
            self.assertFalse(self.manager.backup_semanal_pendiente())

    def test_backup_semanal_pendiente_el_viernes_sin_backup_previo(self):
        with patch('src.core.backup_manager.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 4, 9, 0, 0)  # viernes
            self.assertTrue(self.manager.backup_semanal_pendiente())

    def test_no_crea_dos_backups_automaticos_el_mismo_viernes(self):
        viernes = datetime(2026, 9, 4, 9, 0, 0)
        with patch('src.core.backup_manager.datetime') as mock_dt:
            mock_dt.now.return_value = viernes
            primero = self.manager.crear_backup_automatico_si_corresponde()
            segundo = self.manager.crear_backup_automatico_si_corresponde()

        self.assertIsNotNone(primero)
        self.assertTrue(primero.get("copiados"))
        self.assertIsNone(segundo, "Fallo: no debe crear un segundo backup automatico la misma semana.")
        self.assertEqual(len(self._carpetas_auto()), 1)

    def test_permite_backup_automatico_la_semana_siguiente(self):
        with patch('src.core.backup_manager.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 4, 9, 0, 0)  # viernes
            primero = self.manager.crear_backup_automatico_si_corresponde()

        with patch('src.core.backup_manager.datetime') as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 11, 9, 0, 0)  # viernes siguiente
            segundo = self.manager.crear_backup_automatico_si_corresponde()

        self.assertIsNotNone(primero)
        self.assertIsNotNone(segundo, "Fallo: la semana siguiente si debe permitir un nuevo backup automatico.")
        self.assertEqual(len(self._carpetas_auto()), 2)

    def test_backup_automatico_no_marca_la_semana_si_todo_fallo(self):
        with patch.object(config.settings, 'EXCEL_PATH', os.path.join(self.origen_dir, "no_existe.xlsx")):
            with patch('src.core.backup_manager.datetime') as mock_dt:
                mock_dt.now.return_value = datetime(2026, 9, 4, 9, 0, 0)  # viernes
                resultado = self.manager.crear_backup_automatico_si_corresponde()
                self.assertIn("error_fatal", resultado)
                # Como no se pudo copiar nada, la semana no debe quedar marcada como respaldada
                self.assertTrue(self.manager.backup_semanal_pendiente())


if __name__ == '__main__':
    unittest.main(verbosity=2)
