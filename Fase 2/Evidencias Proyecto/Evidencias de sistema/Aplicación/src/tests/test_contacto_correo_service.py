import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from src.core.excel_writer import ExcelWriter
from src.services import contacto_correo_service


def _comercial(**overrides):
    base = {'VIN': 'VIN0001', 'CDB': '99999', 'CDB FLOTA': '50001'}
    base.update(overrides)
    return pd.DataFrame([base])


def _contactos(**overrides):
    base = {'CDB': '50001', 'Correo electrónico': 'nuevo@empresa.cl'}
    base.update(overrides)
    return pd.DataFrame([base])


class TestActualizarCorreoPorCdb(unittest.TestCase):
    """Caso 5 y 6 del punto 18: al agregar un contacto, Correos.csv recibe
    el correo nuevo para ese CDB y conserva el resto de sus datos intactos.
    B-5.2 (migracion XLSX -> CSV, 18-09-2026): actualizar_correo_por_cdb ya
    no usa ExcelWriter.update_cells (openpyxl-only), lee/parcha/escribe el
    CSV directamente -- ver contacto_correo_service.py."""

    def _preparar_correos_csv(self, tmp_dir, filas):
        ruta = os.path.join(tmp_dir, "Correos.csv")
        pd.DataFrame(filas).to_csv(ruta, index=False)
        return ruta

    def test_actualiza_solo_el_correo_del_vin_del_cdb_afectado(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._preparar_correos_csv(tmp, [
                {"VIN": "VIN0001", "CHASIS": "CHA1", "RAZÓN SOCIAL": "EMPRESA UNO", "RUT": "1-1",
                 "TIPO DE SERVICIO": "FULL", "FECHA TERMINO": "01-01-2027", "CORREO ELECTRÓNICO": ""},
                {"VIN": "VIN0002", "CHASIS": "CHA2", "RAZÓN SOCIAL": "EMPRESA DOS", "RUT": "2-2",
                 "TIPO DE SERVICIO": "MEDIO", "FECHA TERMINO": "MENSUAL", "CORREO ELECTRÓNICO": "otra@empresa.cl"},
            ])

            with patch('src.core.excel_writer.os.getcwd', return_value=tmp):
                ok, msg, vins = contacto_correo_service.actualizar_correo_por_cdb(
                    "50001", _comercial(), _contactos(), ruta
                )

            self.assertTrue(ok, msg)
            self.assertEqual(vins, ["VIN0001"])

            df_final = pd.read_csv(ruta, dtype=str, keep_default_na=False)
            fila1 = df_final[df_final["VIN"] == "VIN0001"].iloc[0]
            fila2 = df_final[df_final["VIN"] == "VIN0002"].iloc[0]

            self.assertEqual(fila1["CORREO ELECTRÓNICO"], "nuevo@empresa.cl")
            # El resto de columnas de la fila afectada no se pierde
            self.assertEqual(fila1["RAZÓN SOCIAL"], "EMPRESA UNO")
            self.assertEqual(fila1["RUT"], "1-1")
            self.assertEqual(fila1["TIPO DE SERVICIO"], "FULL")
            self.assertEqual(fila1["FECHA TERMINO"], "01-01-2027")

            # La fila de otro CDB queda completamente intacta
            self.assertEqual(fila2["CORREO ELECTRÓNICO"], "otra@empresa.cl")
            self.assertEqual(fila2["RAZÓN SOCIAL"], "EMPRESA DOS")

    def test_cdb_sin_camiones_en_comercial_no_actualiza_nada(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._preparar_correos_csv(tmp, [
                {"VIN": "VIN0001", "CHASIS": "CHA1", "RAZÓN SOCIAL": "EMPRESA UNO", "RUT": "1-1",
                 "TIPO DE SERVICIO": "FULL", "FECHA TERMINO": "01-01-2027", "CORREO ELECTRÓNICO": ""},
            ])

            ok, msg, vins = contacto_correo_service.actualizar_correo_por_cdb(
                "99999", _comercial(), _contactos(), ruta
            )

            self.assertFalse(ok)
            self.assertEqual(vins, [])

    def test_multiples_vin_del_mismo_cdb_se_actualizan_todos(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._preparar_correos_csv(tmp, [
                {"VIN": "VIN0001", "CHASIS": "CHA1", "RAZÓN SOCIAL": "EMPRESA UNO", "RUT": "1-1",
                 "TIPO DE SERVICIO": "FULL", "FECHA TERMINO": "01-01-2027", "CORREO ELECTRÓNICO": ""},
                {"VIN": "VIN0002", "CHASIS": "CHA2", "RAZÓN SOCIAL": "EMPRESA UNO", "RUT": "1-1",
                 "TIPO DE SERVICIO": "FULL", "FECHA TERMINO": "01-01-2027", "CORREO ELECTRÓNICO": ""},
            ])
            df_comercial = pd.DataFrame([
                {"VIN": "VIN0001", "CDB": "99999", "CDB FLOTA": "50001"},
                {"VIN": "VIN0002", "CDB": "99999", "CDB FLOTA": "50001"},
            ])

            with patch('src.core.excel_writer.os.getcwd', return_value=tmp):
                ok, msg, vins = contacto_correo_service.actualizar_correo_por_cdb(
                    "50001", df_comercial, _contactos(), ruta
                )

            self.assertTrue(ok, msg)
            self.assertEqual(set(vins), {"VIN0001", "VIN0002"})

            df_final = pd.read_csv(ruta, dtype=str, keep_default_na=False)
            self.assertTrue((df_final["CORREO ELECTRÓNICO"] == "nuevo@empresa.cl").all())


if __name__ == '__main__':
    unittest.main()
