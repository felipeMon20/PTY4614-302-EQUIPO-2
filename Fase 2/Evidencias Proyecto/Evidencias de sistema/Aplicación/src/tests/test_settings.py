import os
import json
import time
import tempfile
import unittest

import config.settings as settings_module


class TestNormalizacionLogCsvPath(unittest.TestCase):
    """Problema 2: una config antigua que solo tiene LOG_EXCEL_PATH (el
    .xlsx legado) debe normalizarse automáticamente para tener también
    LOG_CSV_PATH (LogApp.csv, el historial oficial), sin romper el resto
    de la configuración existente ni repetirse en cada carga."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "app_config.json")
        self._config_file_original = settings_module.CONFIG_FILE
        settings_module.CONFIG_FILE = self.config_path

    def tearDown(self):
        settings_module.CONFIG_FILE = self._config_file_original
        self.temp_dir.cleanup()

    def _escribir_config(self, data):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def _leer_config_disco(self):
        with open(self.config_path, encoding='utf-8') as f:
            return json.load(f)

    def test_config_antigua_sin_log_csv_path_se_normaliza_automaticamente(self):
        self._escribir_config({
            "EXCEL_PATH": "C:\\datos\\PruebasFM.xlsx",
            "LOG_EXCEL_PATH": "C:\\datos\\LogApp.xlsx",
            "PROVISION_EXCEL_PATH": "C:\\datos\\provisionContratos.xlsx",
        })

        cfg = settings_module.load_config()

        self.assertEqual(cfg["LOG_CSV_PATH"], "C:\\datos\\LogApp.csv",
                          "Fallo: LOG_CSV_PATH debe derivarse automáticamente desde LOG_EXCEL_PATH.")
        # No debe romper ni alterar las demás rutas ya configuradas
        self.assertEqual(cfg["EXCEL_PATH"], "C:\\datos\\PruebasFM.xlsx")
        self.assertEqual(cfg["PROVISION_EXCEL_PATH"], "C:\\datos\\provisionContratos.xlsx")
        self.assertEqual(cfg["LOG_EXCEL_PATH"], "C:\\datos\\LogApp.xlsx",
                          "Fallo: LOG_EXCEL_PATH no debe eliminarse (se conserva como referencia del legado).")

        # La normalizacion es solo en memoria (ver comentario en load_config):
        # cargar la config no debe reescribir app_config.json por si sola,
        # para que un simple import (ej. correr los tests) no mute la config
        # real. Se persiste recien cuando el usuario guarda Configuración
        # normalmente (ese dict ya trae LOG_CSV_PATH derivado).
        en_disco = self._leer_config_disco()
        self.assertNotIn("LOG_CSV_PATH", en_disco,
                          "Fallo: load_config() no debe escribir en disco por si sola.")

    def test_config_con_log_csv_path_ya_definido_no_se_sobreescribe(self):
        self._escribir_config({
            "EXCEL_PATH": "C:\\datos\\PruebasFM.xlsx",
            "LOG_EXCEL_PATH": "C:\\datos\\LogApp.xlsx",
            "LOG_CSV_PATH": "D:\\otra_ruta\\LogApp_personalizado.csv",
        })

        cfg = settings_module.load_config()

        self.assertEqual(cfg["LOG_CSV_PATH"], "D:\\otra_ruta\\LogApp_personalizado.csv",
                          "Fallo: un LOG_CSV_PATH ya configurado explícitamente no debe pisarse.")

    def test_config_sin_log_excel_path_ni_log_csv_path_queda_vacio(self):
        self._escribir_config({"EXCEL_PATH": "C:\\datos\\PruebasFM.xlsx"})

        cfg = settings_module.load_config()

        self.assertEqual(cfg.get("LOG_CSV_PATH", ""), "",
                          "Fallo: sin LOG_EXCEL_PATH no hay nada que derivar; debe quedar vacío, no inventarse una ruta.")

    def test_load_config_nunca_escribe_en_disco_por_si_sola(self):
        """Critico: load_config() se ejecuta automaticamente cada vez que
        algo importa config.settings (incluyendo correr los tests). No debe
        reescribir app_config.json como efecto secundario de un import."""
        self._escribir_config({
            "EXCEL_PATH": "C:\\datos\\PruebasFM.xlsx",
            "LOG_EXCEL_PATH": "C:\\datos\\LogApp.xlsx",
        })
        mtime_original = os.path.getmtime(self.config_path)

        time.sleep(0.05)
        settings_module.load_config()
        settings_module.load_config()

        self.assertEqual(os.path.getmtime(self.config_path), mtime_original,
                          "Fallo: load_config() no debe modificar app_config.json en disco.")


if __name__ == '__main__':
    unittest.main(verbosity=2)
