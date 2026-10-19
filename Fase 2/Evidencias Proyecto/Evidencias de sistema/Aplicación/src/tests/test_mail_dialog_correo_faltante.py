import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from src.ui import comercial_estilo as estilo_com
from src.ui.mail_dialog import MailDialog
from src.ui.contactos_agregar import ContactosAddDialog


def _ensure_app():
    if QApplication.instance() is None:
        QApplication([])


def _df_correos():
    return pd.DataFrame({
        "VIN": ["VIN_CON_CORREO", "VIN_SIN_CORREO"],
        "CHASIS": ["CHA1", "CHA2"],
        "RAZÓN SOCIAL": ["EMPRESA CON CORREO", "EMPRESA SIN CORREO"],
        "RUT": ["31.423.846-1", "31.439.684-0"],
        "TIPO DE SERVICIO": ["FULL", "FULL"],
        "FECHA TERMINO": ["01-01-2027", "01-01-2027"],
        "CORREO ELECTRÓNICO": ["contacto@empresa.example", ""],
    })


def _df_comercial():
    return pd.DataFrame({
        "VIN": ["VIN_CON_CORREO", "VIN_SIN_CORREO"],
        "CDB": ["99991", "99992"],
        "CDB FLOTA": ["50001", "50002"],
    })


class TestMailDialogCeldaCorreoFaltante(unittest.TestCase):
    """Casos 1, 2 y 3 del punto 18 (auditoría/implementación 'Agregar correo
    relacionado a esta empresa'): render de la celda roja/negrita y
    resolución de CDB/Razón Social para el menú contextual."""

    @classmethod
    def setUpClass(cls):
        _ensure_app()

    def _build_dialog(self, df_correos=None, df_comercial=None, **mail_dialog_kwargs):
        df_correos = _df_correos() if df_correos is None else df_correos
        df_comercial = _df_comercial() if df_comercial is None else df_comercial

        self._tmp_dir = tempfile.mkdtemp()
        correos_path = os.path.join(self._tmp_dir, "Correos.csv")
        df_correos.to_csv(correos_path, index=False)

        mock_dm_instance = MagicMock()
        mock_dm_instance.get_comercial_df.return_value = df_comercial

        with patch('src.ui.mail_dialog.CORREOS_EXCEL_PATH', correos_path), \
             patch('src.ui.mail_dialog.DataManager', return_value=mock_dm_instance):
            dialog = MailDialog(**mail_dialog_kwargs)
        return dialog

    def test_registro_sin_correo_se_marca_como_faltante(self):
        # B-5 (auditoria de rendimiento, 18-09-2026): dialog.table pasó de
        # QTableWidget a QTableView + MailCorreosTableModel (ver mail_dialog.py).
        # QTableView no tiene .item(); el mismo dato/estilo/tooltip que antes
        # se leía de un QTableWidgetItem ahora se lee vía model.data(index, role).
        # Desde el 08-10-2026 la tabla va agrupada por cliente: la fila de una
        # empresa sin correo dice "Sin correo" en rojo (ya no hay tooltip con
        # el CDB ni negrita en la razón social).
        dialog = self._build_dialog()
        modelo = dialog.model
        row = next(r for r in range(modelo.rowCount()) if modelo.clave_de_fila(r) == "EMPRESA SIN CORREO")

        idx_correo = modelo.index(row, 3)
        self.assertEqual(modelo.data(idx_correo, Qt.ItemDataRole.DisplayRole), "Sin correo")
        self.assertEqual(modelo.data(idx_correo, Qt.ItemDataRole.BackgroundRole).name().lower(), estilo_com.ROJO_SUAVE.lower())

    def test_registro_con_correo_no_se_marca(self):
        dialog = self._build_dialog()
        modelo = dialog.model
        row = next(r for r in range(modelo.rowCount()) if modelo.clave_de_fila(r) == "EMPRESA CON CORREO")

        idx_correo = modelo.index(row, 3)
        self.assertEqual(modelo.data(idx_correo, Qt.ItemDataRole.DisplayRole), "1 correo")
        fondo = modelo.data(idx_correo, Qt.ItemDataRole.BackgroundRole)
        self.assertTrue(fondo is None or fondo.name().lower() != estilo_com.ROJO_SUAVE.lower())

    def test_resolucion_cdb_y_razon_social_para_fila_sin_correo(self):
        dialog = self._build_dialog()
        row = dialog.df_display.index[dialog.df_display["VIN"] == "VIN_SIN_CORREO"][0]

        cdb, razon_social, sin_correo = dialog._resolver_cdb_razonsocial_por_fila(row)
        self.assertEqual(cdb, "50002")
        self.assertEqual(razon_social, "EMPRESA SIN CORREO")
        self.assertTrue(sin_correo)

    def test_resolucion_para_fila_con_correo_no_marca_sin_correo(self):
        dialog = self._build_dialog()
        row = dialog.df_display.index[dialog.df_display["VIN"] == "VIN_CON_CORREO"][0]

        cdb, razon_social, sin_correo = dialog._resolver_cdb_razonsocial_por_fila(row)
        self.assertEqual(cdb, "50001")
        self.assertFalse(sin_correo)


class TestMailDialogPreseleccionDesdeGestionarCM(unittest.TestCase):
    """Cubre los parametros opcionales de MailDialog usados por
    comercial.py (Gestionar CM -> Enviar Correo): vins_preseleccionados y
    plantilla_inicial. Sin ellos, MailDialog debe comportarse exactamente
    igual que antes (ver test_sin_parametros_se_comporta_como_siempre)."""

    @classmethod
    def setUpClass(cls):
        _ensure_app()

    def _build_dialog(self, df_correos=None, df_comercial=None, **mail_dialog_kwargs):
        df_correos = _df_correos() if df_correos is None else df_correos
        df_comercial = _df_comercial() if df_comercial is None else df_comercial

        self._tmp_dir = tempfile.mkdtemp()
        correos_path = os.path.join(self._tmp_dir, "Correos.csv")
        df_correos.to_csv(correos_path, index=False)

        mock_dm_instance = MagicMock()
        mock_dm_instance.get_comercial_df.return_value = df_comercial

        with patch('src.ui.mail_dialog.CORREOS_EXCEL_PATH', correos_path), \
             patch('src.ui.mail_dialog.DataManager', return_value=mock_dm_instance):
            dialog = MailDialog(**mail_dialog_kwargs)
        return dialog

    def _df_correos_tres_vin(self):
        return pd.DataFrame({
            "VIN": ["VIN_UNO", "VIN_DOS", "VIN_TRES"],
            "CHASIS": ["CHA1", "CHA2", "CHA3"],
            "RAZÓN SOCIAL": ["EMPRESA UNO", "EMPRESA DOS", "EMPRESA TRES"],
            "RUT": ["31.423.846-1", "31.439.684-0", "31.447.603-9"],
            "TIPO DE SERVICIO": ["FULL", "FULL", "FULL"],
            "FECHA TERMINO": ["01-01-2027", "01-01-2027", "01-01-2027"],
            "CORREO ELECTRÓNICO": ["uno@empresa.example", "dos@empresa.example", "tres@empresa.example"],
        })

    def test_un_vin_preseleccionado_queda_marcado(self):
        dialog = self._build_dialog(df_correos=self._df_correos_tres_vin(), vins_preseleccionados=["VIN_UNO"])
        self.assertEqual(dialog.checked_vins, {"VIN_UNO"})
        self.assertEqual(set(dialog.df_display["VIN"]), {"VIN_UNO"})

    def test_multiples_vin_preseleccionados_quedan_marcados(self):
        dialog = self._build_dialog(
            df_correos=self._df_correos_tres_vin(), vins_preseleccionados=["VIN_UNO", "VIN_TRES"]
        )
        self.assertEqual(dialog.checked_vins, {"VIN_UNO", "VIN_TRES"})
        self.assertEqual(set(dialog.df_display["VIN"]), {"VIN_UNO", "VIN_TRES"})

    def test_preseleccion_es_insensible_a_mayusculas(self):
        dialog = self._build_dialog(df_correos=self._df_correos_tres_vin(), vins_preseleccionados=["vin_dos"])
        self.assertEqual(dialog.checked_vins, {"VIN_DOS"})

    def test_plantilla_inicial_queda_seleccionada(self):
        dialog = self._build_dialog(plantilla_inicial="Aviso de Vencimiento")
        self.assertEqual(dialog.combo_plantilla.currentText(), "Aviso de Vencimiento")
        self.assertTrue(dialog.txt_asunto.isReadOnly())
        self.assertTrue(dialog.txt_asunto.text())

    def test_sin_parametros_se_comporta_como_siempre(self):
        dialog = self._build_dialog()
        self.assertEqual(dialog.checked_vins, set())
        self.assertEqual(dialog.combo_plantilla.currentIndex(), 0)
        self.assertEqual(dialog.search_bar.text(), "")


class TestContactosAddDialogPrefillBloqueado(unittest.TestCase):
    """Caso 4 del punto 18: el formulario reutilizado recibe CDB y Flota
    precargados y bloqueados cuando se abre desde Correos."""

    @classmethod
    def setUpClass(cls):
        _ensure_app()

    @patch('src.ui.contactos_agregar.ContactosAddDialog._load_flotas_dict', lambda self: None)
    def test_cdb_y_flota_quedan_precargados_y_bloqueados(self):
        dialog = ContactosAddDialog(cdb_prefill="50002", flota_prefill="EMPRESA SIN CORREO")

        self.assertEqual(dialog.inputs['CDB'].text(), "50002")
        self.assertTrue(dialog.inputs['CDB'].isReadOnly())

        self.assertEqual(dialog.inputs['Flota'].text(), "EMPRESA SIN CORREO")
        self.assertTrue(dialog.inputs['Flota'].isReadOnly())

    @patch('src.ui.contactos_agregar.ContactosAddDialog._load_flotas_dict', lambda self: None)
    def test_sin_prefill_el_formulario_se_comporta_como_siempre(self):
        dialog = ContactosAddDialog()

        self.assertEqual(dialog.inputs['CDB'].text(), "")
        self.assertFalse(dialog.inputs['CDB'].isReadOnly())
        self.assertFalse(dialog.inputs['Flota'].isReadOnly())

    @patch('src.ui.contactos_agregar.ContactosAddDialog._load_flotas_dict', lambda self: None)
    def test_flota_prefill_prevalece_sobre_autocompletado_powerbi(self):
        dialog = ContactosAddDialog(cdb_prefill="10001", flota_prefill="RAZÓN SOCIAL DE CORREOS")
        dialog.dict_flotas = {'10001': 'NOMBRE DISTINTO EN POWER BI'}

        # Reaplicamos el prefill como lo haría _apply_prefill tras _on_cdb_changed
        dialog._apply_prefill()

        self.assertEqual(dialog.inputs['Flota'].text(), "RAZÓN SOCIAL DE CORREOS")
        self.assertTrue(dialog.inputs['Flota'].isReadOnly())


if __name__ == '__main__':
    unittest.main()
