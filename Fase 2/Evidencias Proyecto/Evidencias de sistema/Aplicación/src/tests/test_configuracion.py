import unittest
from unittest.mock import patch

import config.settings
from src.ui.configuracion import ConfiguracionModule


class TestConfiguracionHistorialCsv(unittest.TestCase):
    """Problema 2: Configuración debe mostrar y permitir editar LogApp.csv
    (LOG_CSV_PATH) como historial oficial, en vez de LogApp.xlsx
    (LOG_EXCEL_PATH); el resto de rutas Excel maestras no deben verse
    afectadas por este cambio."""

    def setUp(self):
        self._patches = [
            patch.object(config.settings, 'LOG_CSV_PATH', 'C:\\datos\\LogApp.csv'),
            patch.object(config.settings, 'LOG_EXCEL_PATH', 'C:\\datos\\LogApp.xlsx'),
        ]
        for p in self._patches:
            p.start()
        self.module = ConfiguracionModule()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_configuracion_usa_log_csv_path_como_campo_del_historial(self):
        self.assertIn('LOG_CSV_PATH', self.module.path_inputs,
                       "Fallo: el campo de historial debe estar atado a LOG_CSV_PATH.")
        self.assertNotIn('LOG_EXCEL_PATH', self.module.path_inputs,
                          "Fallo: LOG_EXCEL_PATH ya no debe exponerse como campo editable en Configuración "
                          "(no debe seguir mostrándose LogApp.xlsx como ruta activa).")

    def test_otros_campos_de_rutas_maestras_no_se_ven_afectados(self):
        # El cambio del campo de historial no debe tocar ninguno de los
        # demás campos de archivos Excel maestros reales.
        for clave in ['EXCEL_PATH', 'PROVISION_EXCEL_PATH', 'INSTALACIONES_PATH',
                      'RM_JAVI_PATH', 'CONTACTOS_EXCEL_PATH',
                      'CORREOS_EXCEL_PATH', 'POWERBI_EXCEL_PATH', 'DELETED_LOG_EXCEL_PATH']:
            self.assertIn(clave, self.module.path_inputs, f"Fallo: el campo '{clave}' no debería haberse eliminado.")

    def test_selector_de_archivos_permite_csv_para_el_historial(self):
        with patch('src.ui.configuracion.QFileDialog.getOpenFileName') as mock_dialog:
            mock_dialog.return_value = ('', '')
            self.module._browse_file('LOG_CSV_PATH', self.module.path_inputs['LOG_CSV_PATH'])
            filtro_usado = mock_dialog.call_args[0][3]
            self.assertIn('*.csv', filtro_usado, "Fallo: el selector para el historial debe permitir *.csv.")

    def test_selector_de_otros_campos_sigue_pidiendo_excel(self):
        with patch('src.ui.configuracion.QFileDialog.getOpenFileName') as mock_dialog:
            mock_dialog.return_value = ('', '')
            self.module._browse_file('EXCEL_PATH', self.module.path_inputs['EXCEL_PATH'])
            filtro_usado = mock_dialog.call_args[0][3]
            self.assertIn('*.xlsx', filtro_usado)
            self.assertNotIn('*.csv', filtro_usado,
                              "Fallo: los campos de archivos maestros reales no deben cambiar su filtro de selección.")


class TestConfiguracionCasosBajaCmPath(unittest.TestCase):
    """CASOS_BAJA_CM_PATH (CasosBajaCM.csv, ver cm_bajas_service.py) debe
    quedar expuesto y editable en Configuración, sin rutas hardcodeadas: el
    usuario puede seleccionarlo desde acá, igual que LOG_CSV_PATH."""

    def setUp(self):
        self.module = ConfiguracionModule()

    def test_casos_baja_cm_path_es_un_campo_editable(self):
        self.assertIn('CASOS_BAJA_CM_PATH', self.module.path_inputs,
                       "Fallo: CASOS_BAJA_CM_PATH debe exponerse como campo editable en Configuración.")

    def test_selector_de_casos_baja_cm_permite_csv(self):
        with patch('src.ui.configuracion.QFileDialog.getOpenFileName') as mock_dialog:
            mock_dialog.return_value = ('', '')
            self.module._browse_file('CASOS_BAJA_CM_PATH', self.module.path_inputs['CASOS_BAJA_CM_PATH'])
            filtro_usado = mock_dialog.call_args[0][3]
            self.assertIn('*.csv', filtro_usado, "Fallo: el selector de Casos de Revisión CM debe permitir *.csv.")


if __name__ == '__main__':
    unittest.main(verbosity=2)
