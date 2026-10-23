import os
import re
import time
import tempfile
import unittest
import logging
from unittest.mock import patch

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox, QDialog

import config.settings
from src.ui.contactos import ContactosModule
from src.ui.contactos_agregar import ContactosAddDialog

logger = logging.getLogger("TestRunner")

class TestContactos(unittest.TestCase):
    """Pruebas de Contactos con esperas deterministas para los QThread."""

    ASYNC_TIMEOUT_MS = 20000

    @staticmethod
    def _wait_until(predicate, timeout_ms=20000, interval_ms=20):
        print(f"[TRACING TEST] _wait_until INICIADO con timeout {timeout_ms}ms")
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        iteraciones = 0
        while time.monotonic() < deadline:
            QApplication.processEvents()
            try:
                if predicate():
                    QApplication.processEvents()
                    print(f"[TRACING TEST] _wait_until CONDICION CUMPLIDA (Iteración {iteraciones})")
                    return True
            except RuntimeError:
                pass
            time.sleep(interval_ms / 1000.0)
            iteraciones += 1
            if iteraciones % 100 == 0:
                print(f"[TRACING TEST] _wait_until sigue esperando... (Iteración {iteraciones})")

        QApplication.processEvents()
        try:
            res = bool(predicate())
            print(f"[TRACING TEST] _wait_until TIMEOUT ALCANZADO (20 segs). Resultado: {res}")
            return res
        except RuntimeError:
            print("[TRACING TEST] _wait_until TIMEOUT con RuntimeError")
            return False

    @classmethod
    def setUpClass(cls):
        print("[TRACING TEST] 1. Entrando TestContactos.setUpClass")
        logger.info("--- Instanciando Módulo Contactos ---")

        with patch('PyQt6.QtWidgets.QMessageBox.warning'), \
             patch('PyQt6.QtWidgets.QMessageBox.information'):
            
            print("[TRACING TEST] 2. Instanciando ContactosModule()")
            cls.module = ContactosModule()
            print("[TRACING TEST] 3. ContactosModule instanciado completamente")
            
            dm = cls.module.data_manager

            print(f"[TRACING TEST] 4. Estado: df_plataforma.empty = {cls.module.df_plataforma.empty}, dm.is_loading_contactos = {dm.is_loading_contactos}")
            if cls.module.df_plataforma.empty and not dm.is_loading_contactos:
                print("[TRACING TEST] 4.1 Disparando load_contactos_async manualmente desde test")
                dm.load_contactos_async()

            print("[TRACING TEST] 5. Ejecutando _wait_until para esperar los datos")
            loaded = cls._wait_until(
                lambda: (not dm.is_loading_contactos) and (
                    not cls.module.df_plataforma.empty or bool(dm.last_contactos_error)
                ),
                timeout_ms=cls.ASYNC_TIMEOUT_MS,
            )
            print(f"[TRACING TEST] 6. Salida de _wait_until. loaded = {loaded}")

            if not loaded:
                print("[TRACING TEST] 7. ABORTANDO: Se agotó el timeout")
                raise RuntimeError(
                    "Timeout preparando Contactos. "
                    f"is_loading_contactos={dm.is_loading_contactos}, "
                    f"error={dm.last_contactos_error!r}"
                )
            if dm.last_contactos_error:
                print("[TRACING TEST] 7. ABORTANDO: Error reportado por DataManager")
                raise RuntimeError(f"Error cargando Contactos: {dm.last_contactos_error}")
            
            print("[TRACING TEST] 8. setUpClass terminado con éxito")

    def test_01_carga_datos_falsos(self):
        logger.info("[Test Contactos 01] Verificando carga de administradores de flota...")
        df_actual = self.module.model_plat.get_df()
        self.assertFalse(df_actual.empty, "Fallo: La tabla Contactos está vacía.")
        self.assertEqual(len(df_actual), 2, f"Fallo: Se esperaban 2 filas, se encontraron {len(df_actual)}.")
        logger.info(" -> Éxito: Los registros de contactos falsos fueron cargados.")

    def test_02_lista_de_flotas_abre_sus_contactos(self):
        logger.info("[Test Contactos 02] Verificando lista de flotas y apertura de una flota...")
        if self.module.model_flotas.get_df().empty:
            self.skipTest("Sin flotas. Se omite.")

        self.module._volver_a_flotas()
        df_flotas = self.module.model_flotas.get_df()
        self.assertEqual(self.module.stack_plat.currentIndex(), 0, "Fallo: no se muestra la lista de flotas.")

        self.module._abrir_flota(self.module.model_flotas.index(0, 0))
        cdb, flota = self.module._flota_abierta
        df_contactos = self.module.model_plat.get_df()
        self.assertEqual(self.module.stack_plat.currentIndex(), 1, "Fallo: no se abrió el detalle de la flota.")
        self.assertFalse(df_contactos.empty, "Fallo: la flota abierta no muestra contactos.")
        self.assertTrue((df_contactos['Flota'].astype(str).str.strip() == flota).all()
                        and (df_contactos['CDB'].astype(str).str.strip() == cdb).all(),
                        "Fallo: aparecen contactos de otra flota.")

        self.module._volver_a_flotas()
        self.assertEqual(len(self.module.model_flotas.get_df()), len(df_flotas))
        logger.info(" -> Éxito: la flota abre solo sus contactos y se puede volver a la lista.")

    def test_03_edicion_formato_y_llave_original(self):
        logger.info("[Test Contactos 03] Verificando edición, teléfono y llave compuesta original...")
        df_actual = self.module.model_plat.get_df()
        if df_actual.empty:
            self.skipTest("Se omite porque la tabla no cargó datos.")

        row = 0
        source_index = df_actual.index[row]
        original_id = self.module._normalize_id(self.module.df_plataforma.loc[source_index, 'ID'])
        original_cdb = str(self.module.df_plataforma.loc[source_index, 'CDB']).strip()
        original_nombre = str(self.module.df_plataforma.loc[source_index, 'Nombre']).strip()
        original_correo = str(self.module.df_plataforma.loc[source_index, 'Correo electrónico']).strip()
        nombre_editado = f"{original_nombre} QA"

        self.module.on_item_edited(row=row, col_name='Número móvil', new_value='56912345678')
        df_modificado = self.module.model_plat.get_df()
        telefono_formateado = str(df_modificado.iat[row, df_modificado.columns.get_loc('Número móvil')])
        self.assertEqual(
            telefono_formateado,
            '+56 9 1234 5678',
            "Fallo: El teléfono no se formateó al estándar corporativo (+56 9).",
        )

        self.module.on_item_edited(row=0, col_name='Nombre', new_value=nombre_editado)

        # Soportar tanto índice numérico como ID en pending_changes
        change_key = source_index if source_index in self.module.pending_changes else list(self.module.pending_changes.keys())[0]
        self.assertIn(change_key, self.module.pending_changes)
        keys = self.module.pending_changes[change_key]['keys']
        # El diseño actual usa el ID físico permanente como llave única de guardado.
        self.assertEqual(keys['ID'], original_id, "Fallo: La llave de guardado no usa el ID físico del contacto.")
        self.assertEqual(self.module.pending_changes[change_key]['cambios']['Nombre'], nombre_editado)

        self.__class__.edited_cdb = original_cdb
        self.__class__.edited_correo = original_correo
        self.__class__.edited_nombre = nombre_editado

        logger.info(" -> Éxito: El teléfono se formatea y Nombre conserva la llave original para guardar.")

    @patch('PyQt6.QtWidgets.QMessageBox.information')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    @patch('PyQt6.QtWidgets.QMessageBox.exec')
    def test_04_guardado_asincrono(self, mock_exec, mock_warn, mock_info):
        logger.info("[Test Contactos 04] Verificando guardado y recarga como dos etapas independientes...")
        if not self.module.pending_changes:
            self.skipTest("No hay cambios en mochila para guardar.")

        mock_exec.return_value = QMessageBox.StandardButton.Save
        dm = self.module.data_manager

        idle_before = self._wait_until(
            lambda: not dm.is_loading_contactos,
            timeout_ms=self.ASYNC_TIMEOUT_MS,
        )
        self.assertTrue(
            idle_before,
            f"Fallo: DataManager no quedó libre antes de guardar. Error: {dm.last_contactos_error}",
        )

        self.module.confirm_save()

        save_finished = self._wait_until(
            lambda: self.module.last_save_success is not None,
            timeout_ms=self.ASYNC_TIMEOUT_MS,
        )
        self.assertTrue(save_finished, "Fallo: SaveContactosThread no terminó dentro del timeout.")
        self.assertTrue(
            self.module.last_save_success,
            "Fallo: ExcelWriter devolvió False. La fila no fue encontrada, el archivo está bloqueado o hubo un error de escritura.",
        )
        self.assertEqual(len(self.module.pending_changes), 0, "Fallo: La mochila no se limpió después de guardar.")

        reload_finished = self._wait_until(
            lambda: not dm.is_loading_contactos,
            timeout_ms=self.ASYNC_TIMEOUT_MS,
        )
        self.assertTrue(
            reload_finished,
            f"Fallo: Timeout recargando Contactos tras guardar. Error: {dm.last_contactos_error}",
        )
        self.assertFalse(dm.last_contactos_error, f"Fallo de lectura tras guardar: {dm.last_contactos_error}")
        self.assertEqual(len(dm.get_contactos_df()), 2, "Fallo: La recarga no devolvió los 2 contactos esperados.")

        df_excel = pd.read_excel(config.settings.CONTACTOS_EXCEL_PATH).fillna("")
        mask = (
            df_excel['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.strip().eq(self.edited_cdb)
            & df_excel['Correo electrónico'].astype(str).str.strip().eq(self.edited_correo)
        )
        self.assertEqual(int(mask.sum()), 1, "Fallo: No se encontró de forma única el contacto guardado en el Excel.")
        fila = df_excel.loc[mask].iloc[0]
        self.assertEqual(str(fila['Nombre']).strip(), self.edited_nombre, "Fallo: La edición de Nombre no llegó al Excel.")
        self.assertEqual(str(fila['Número móvil']).strip(), '+56 9 1234 5678', "Fallo: El teléfono formateado no llegó al Excel.")

        logger.info(" -> Éxito: Guardado y recarga terminaron correctamente y el Excel contiene los cambios.")

    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    @patch('PyQt6.QtWidgets.QMessageBox.information')
    @patch('PyQt6.QtWidgets.QMessageBox.exec')
    def test_05_eliminacion_llave_compuesta(self, mock_exec, mock_info, mock_warn):
        logger.info("[Test Contactos 05] Verificando Eliminación Segura (Llave Compuesta)...")
        mock_exec.return_value = QMessageBox.StandardButton.Yes
        dm = self.module.data_manager

        idle_before = self._wait_until(
            lambda: not dm.is_loading_contactos,
            timeout_ms=self.ASYNC_TIMEOUT_MS,
        )
        self.assertTrue(idle_before, "Fallo: DataManager no quedó libre antes de eliminar.")

        df_actual = self.module.model_plat.get_df()
        if len(df_actual) <= 1:
            self.skipTest("No hay dos contactos disponibles para probar eliminación.")

        self.module._handle_eliminar(row=1, texto_ficticio="ficticio")

        delete_finished = self._wait_until(
            lambda: self.module.last_delete_success is not None,
            timeout_ms=self.ASYNC_TIMEOUT_MS,
        )
        self.assertTrue(delete_finished, "Fallo: DeleteContactoThread no terminó dentro del timeout.")
        self.assertTrue(self.module.last_delete_success, "Fallo: ExcelWriter.delete_row devolvió False.")

        reload_finished = self._wait_until(
            lambda: not dm.is_loading_contactos,
            timeout_ms=self.ASYNC_TIMEOUT_MS,
        )
        self.assertTrue(
            reload_finished,
            f"Fallo: Timeout recargando tras eliminar. Error: {dm.last_contactos_error}",
        )
        self.assertFalse(dm.last_contactos_error, f"Fallo de lectura tras eliminar: {dm.last_contactos_error}")

        df_contactos = dm.get_contactos_df()
        self.assertEqual(len(df_contactos), 1, f"Fallo: La memoria dice que hay {len(df_contactos)} registros y debería haber 1.")
        df_excel = pd.read_excel(config.settings.CONTACTOS_EXCEL_PATH)
        self.assertEqual(len(df_excel), 1, "Fallo: El Excel físico no quedó con 1 contacto después de eliminar.")
        logger.info(" -> Éxito: El contacto fue eliminado y la recarga terminó sin heredar estados del test anterior.")

    @patch('src.ui.contactos_agregar.ContactosAddDialog._load_flotas_dict', lambda self: None)
    def test_06_dialogo_agregar_autocompletado_validacion_y_get_data(self):
        logger.info("[Test Contactos 06] Verificando contactos_agregar: CDB, validación, teléfono y get_data...")
        dialog = ContactosAddDialog()
        dialog.dict_flotas = {'10001': 'EMPRESA AUTOMATICA'}

        dialog.inputs['CDB'].setText('10001')
        self.assertEqual(dialog.inputs['Flota'].text(), 'EMPRESA AUTOMATICA')
        self.assertTrue(dialog.inputs['Flota'].isReadOnly(), "Fallo: Flota debería bloquearse para un CDB conocido.")

        dialog.inputs['CDB'].setText('99999')
        self.assertEqual(dialog.inputs['Flota'].text(), '')
        self.assertFalse(dialog.inputs['Flota'].isReadOnly(), "Fallo: Flota debería ser editable para un CDB desconocido.")

        with patch('PyQt6.QtWidgets.QMessageBox.warning') as mock_warning:
            dialog.inputs['CDB'].setText('')
            dialog.inputs['Flota'].setText('')
            dialog._validate_and_accept()
            mock_warning.assert_called_once()

        dialog.inputs['CDB'].setText('99999')
        dialog.inputs['Flota'].setText('EMPRESA MANUAL')
        dialog.inputs['Nombre'].setText('Contacto')
        dialog.inputs['Número móvil'].setText('912345678')
        dialog._validate_and_accept()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.inputs['Número móvil'].text(), '+56 9 1234 5678')

        data = dialog.get_data()
        self.assertEqual(data['CDB'], '99999')
        self.assertEqual(data['Flota'], 'EMPRESA MANUAL')
        self.assertEqual(data['Rol'], 'Administrador de flota')
        self.assertRegex(data['Fecha de extracción'], r'^\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}$')
        logger.info(" -> Éxito: contactos_agregar valida, autocompleta, formatea y entrega los datos esperados.")

    def test_07_dialogo_agregar_carga_diccionario_powerbi(self):
        logger.info("[Test Contactos 07] Verificando precarga asíncrona (QThread) de CDB/Flota desde Power BI...")
        with tempfile.TemporaryDirectory() as tmp:
            powerbi_path = os.path.join(tmp, 'powerbi.xlsx')
            pd.DataFrame({
                'CDB': [12345.0, '67890'],
                'Nombre': ['FLOTA UNO', 'FLOTA DOS'],
            }).to_excel(powerbi_path, index=False)

            with patch('src.ui.contactos_agregar.POWERBI_EXCEL_PATH', powerbi_path):
                dialog = ContactosAddDialog()
                self.assertFalse(
                    dialog.inputs['CDB'].isEnabled(),
                    "Fallo: el campo CDB debería quedar deshabilitado mientras carga Power BI.",
                )
                cargado = self._wait_until(
                    lambda: bool(dialog.dict_flotas),
                    timeout_ms=self.ASYNC_TIMEOUT_MS,
                )

            self.assertTrue(cargado, "Fallo: PowerBiFlotasLoaderThread no terminó dentro del timeout.")
            self.assertEqual(dialog.dict_flotas.get('12345'), 'FLOTA UNO')
            self.assertEqual(dialog.dict_flotas.get('67890'), 'FLOTA DOS')
            self.assertTrue(
                dialog.inputs['CDB'].isEnabled(),
                "Fallo: el campo CDB debería volver a habilitarse tras cargar Power BI.",
            )
        logger.info(" -> Éxito: PowerBiFlotasLoaderThread normaliza los CDB y construye el diccionario sin bloquear la UI.")

    def test_08_excel_writer_no_reporta_exito_si_no_encuentra_fila(self):
        logger.info("[Test Contactos 08] Verificando que ExcelWriter no silencie llaves inexistentes...")
        cambios_inexistentes = {
            'fila_que_no_existe': {
                'keys': {
                    'CDB': 'CDB_INEXISTENTE',
                    'Correo electrónico': 'nadie@inexistente.cl',
                    'Nombre': 'Nadie',
                },
                'cambios': {'Nombre': 'No Debe Guardarse'},
            }
        }
        ok = self.module.writer.update_cells(
            cambios_inexistentes,
            module_name='ContactosTest',
            custom_filepath=config.settings.CONTACTOS_EXCEL_PATH,
        )
        self.assertFalse(ok, "Fallo: update_cells devolvió True aunque no encontró la fila objetivo.")
        logger.info(" -> Éxito: ExcelWriter reporta False cuando la llave compuesta no existe.")

    def test_09_director_de_empresas_no_hereda_eliminar_camion(self):
        logger.info("[Test Contactos 09] Verificando menú contextual de 'Director de empresas'...")
        self.assertNotEqual(
            self.module.table_emp.menu_type, "comercial",
            "Fallo: 'Director de empresas' no debe mostrar 'Eliminar Camión' (menu_type='comercial')."
        )
        logger.info(" -> Éxito: 'Director de empresas' ya no muestra la opción 'Eliminar Camión'.")