import time
import unittest
import logging
from unittest.mock import patch
import pandas as pd
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QMessageBox, QApplication

from src.ui.provisiones import ProvisionesModule, _construir_registro_nuevo_desde_provisiones
from src.core.data_manager import DataManager
from src.services import provisiones_services
import config.settings

logger = logging.getLogger("TestRunner")

class TestProvisiones(unittest.TestCase):
    ASYNC_TIMEOUT_MS = 20000

    @staticmethod
    def _wait_until(predicate, timeout_ms=20000, interval_ms=20):
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            QApplication.processEvents()
            try:
                if predicate():
                    QApplication.processEvents()
                    return True
            except RuntimeError:
                pass
            time.sleep(interval_ms / 1000.0)

        QApplication.processEvents()
        try:
            return bool(predicate())
        except RuntimeError:
            return False

    @classmethod
    def setUpClass(cls):
        logger.info("--- Instanciando Módulo Provisiones ---")
        cls.dm = DataManager()
        
        cls.load_state = {"com_success": False, "com_error": None, "prov_success": False, "prov_error": None}
        
        def on_com_ready(): 
            cls.load_state["com_success"] = True
            cls.loop_com.quit()
            
        def on_com_error(err): 
            cls.load_state["com_error"] = err
            cls.loop_com.quit()
            
        cls.loop_com = QEventLoop()
        cls.dm.data_ready.connect(on_com_ready)
        cls.dm.load_error.connect(on_com_error)
        
        timer_com = QTimer()
        timer_com.setSingleShot(True)
        timer_com.timeout.connect(cls.loop_com.quit)
        
        cls.dm.load_data_async()
        timer_com.start(10000)
        cls.loop_com.exec() 
        timer_com.stop()
        
        if not cls.load_state["com_success"]:
            raise RuntimeError(f"TestProvisiones setUpClass: Error cargando Comercial. Detalle: {cls.load_state['com_error'] or 'Timeout'}")

        def on_prov_ready(): 
            cls.load_state["prov_success"] = True
            cls.loop_prov.quit()
            
        def on_prov_error(err): 
            cls.load_state["prov_error"] = err
            cls.loop_prov.quit()

        cls.loop_prov = QEventLoop()
        cls.dm.provisiones_ready.connect(on_prov_ready)
        cls.dm.load_provisiones_error.connect(on_prov_error)
        
        timer_prov = QTimer()
        timer_prov.setSingleShot(True)
        timer_prov.timeout.connect(cls.loop_prov.quit)
        
        cls.dm.load_provisiones_async()
        timer_prov.start(10000)
        cls.loop_prov.exec()
        timer_prov.stop()
        
        if not cls.load_state["prov_success"]:
            raise RuntimeError(f"TestProvisiones setUpClass: Error cargando Provisiones. Detalle: {cls.load_state['prov_error'] or 'Timeout'}")

        cls.module = ProvisionesModule()
        
        cls.loop_ui = QEventLoop()
        QTimer.singleShot(1000, cls.loop_ui.quit)
        cls.loop_ui.exec()

    def test_01_carga_datos_falsos(self):
        logger.info("[Test Provisiones 01] Verificando carga de provisiones...")
        df_actual = self.module.legacy.df_base

        self.assertFalse(df_actual.empty, "Fallo: La tabla Provisiones está vacía.")
        self.assertEqual(len(df_actual), 2, f"Fallo: Se esperaban 2 filas, se encontraron {len(df_actual)}.")
        logger.info(" -> Éxito: Los registros de provisión falsos fueron cargados.")

    def test_02_filtros_combos(self):
        logger.info("[Test Provisiones 02] Verificando filtros combinados (Mes / Plan)...")
        self.module.combo_plan.setCurrentText("FULL")
        
        df_filtrado = self.module.model.get_df()
        self.assertEqual(len(df_filtrado), 1, "Fallo: El filtro por plan no funcionó.")
        self.module.combo_plan.setCurrentText("Todos los Planes")
        logger.info(" -> Éxito: Los filtros de caja desplegable operan correctamente.")

    def test_03_edicion_y_matematica_financiera(self):
        """
        DEUDA DE TEST: Este test inyecta el estado que test_04 necesita para funcionar.
        Están estructuralmente acoplados. test_04 se saltará si este test no corre antes.
        """
        logger.info("[Test Provisiones 03] Verificando edición en vivo de Cobros (Dynafleet)...")
        df_actual = self.module.model.get_df()
        if df_actual.empty:
            self.skipTest("Se omite porque la tabla no cargó datos.")
            
        self.module.on_item_edited(row=0, col_name='DYNAFLEET', new_value='500000')
        self.module.on_item_edited(row=0, col_name='Plan', new_value='MEDIO + CIV')
        
        df_modificado = self.module.model.get_df()
        monto_prov = str(df_modificado.iat[0, df_modificado.columns.get_loc('Monto Provisionado')])
        
        # Capturamos las llaves maestras para la verificación física posterior en test_04
        self.__class__.edited_vin = str(df_modificado.iat[0, df_modificado.columns.get_loc('VIN')]).strip()
        self.__class__.edited_fecha = str(df_modificado.iat[0, df_modificado.columns.get_loc('AÑO - MES')]).strip()
        
        self.assertTrue("500.000" in monto_prov or "500000" in monto_prov, "Fallo: El Monto Provisionado no se calculó correctamente.")
        logger.info(" -> Éxito: La matemática de variables y formatos de dinero reaccionan en tiempo real.")

    def _dejar_contrato_en_forma_provision(self, vin):
        """El cruce a Comercial solo aplica a contratos de forma Provision."""
        df = self.module.data_manager.df_master
        df.loc[df['VIN'].astype(str).str.strip() == vin, 'FORMA DE CONTRATO'] = 'Provision'

    @patch('PyQt6.QtWidgets.QMessageBox.information')
    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    @patch('PyQt6.QtWidgets.QMessageBox.exec')
    def test_04_guardado_y_cruce_comercial(self, mock_exec, mock_warn, mock_info):
        logger.info("[Test Provisiones 04] Verificando Hilo de Guardado e Inyección a Comercial (Cross-Update)...")
        if not self.module.pending_changes:
            self.skipTest("No hay cambios en mochila para guardar (Depende de test_03).")
            
        mock_exec.return_value = QMessageBox.StandardButton.Save
        self._dejar_contrato_en_forma_provision(self.edited_vin)
        
        self.module.confirm_save()
        
        save_finished = self._wait_until(
            lambda: self.module.btn_save.isEnabled(),
            timeout_ms=self.ASYNC_TIMEOUT_MS
        )
        self.assertTrue(save_finished, "Fallo: SaveProvisionesThread no terminó dentro del timeout.")

        loop_seguro = QEventLoop()
        QTimer.singleShot(1500, loop_seguro.quit)
        loop_seguro.exec()
        
        self.assertEqual(len(self.module.pending_changes), 0, "Fallo: La mochila de cambios no se limpió.")

        # ======================================================================
        # VALIDACIÓN FÍSICA: Verificamos que no sea un Falso Positivo
        # ======================================================================
        df_excel_prov = pd.read_excel(config.settings.PROVISION_EXCEL_PATH, sheet_name="Prov", engine='openpyxl')
        
        mask_prov = (
            df_excel_prov['VIN'].astype(str).str.strip().eq(self.edited_vin) &
            df_excel_prov['AÑO - MES'].astype(str).str.contains(self.edited_fecha, regex=False, na=False)
        )
        self.assertEqual(int(mask_prov.sum()), 1, f"Fallo Físico: No se localizó la fila VIN={self.edited_vin} Fecha={self.edited_fecha} en el Excel de Provisiones.")
        
        fila_prov = df_excel_prov.loc[mask_prov].iloc[0]
        self.assertEqual(float(fila_prov.get('DYNAFLEET', 0)), 500000.0, "Fallo Físico: El DYNAFLEET no se guardó en el Excel.")
        self.assertEqual(str(fila_prov.get('Plan', '')).strip(), 'MEDIO + CIV', "Fallo Físico: El Plan no se guardó en el Excel.")
        
        dm = self.module.data_manager
        df_master = dm.df_master
        
        mask_comercial = df_master['VIN'].astype(str).str.strip().eq(self.edited_vin)
        self.assertEqual(int(mask_comercial.sum()), 1, f"Fallo RAM: El VIN {self.edited_vin} no existe en Comercial.")
        
        fila_comercial = df_master.loc[mask_comercial].iloc[0]
        self.assertEqual(str(fila_comercial.get('TIPO DE SERVICIO', '')).strip(), 'MEDIO + CIV', "Fallo Cross-Update: El Plan no se inyectó en TIPO DE SERVICIO de Comercial.")

        self.assertFalse(dm.is_app_saving, "Fallo: is_app_saving debería quedar en False al finalizar guardado exitoso.")

        logger.info(" -> Éxito Absoluto: Provisiones se guardó, inyectó en RAM Comercial y persistió en el Excel físico correctamente.")

    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    @patch('PyQt6.QtWidgets.QMessageBox.information')
    @patch('PyQt6.QtWidgets.QMessageBox.exec')
    def test_05_fallo_escritura_provisiones(self, mock_exec, mock_info, mock_warn):
        logger.info("[Test Provisiones 05] Verificando Escenario 2: Fallo en Provisiones (update_cells=False)...")
        mock_exec.return_value = QMessageBox.StandardButton.Save
        
        self.module.pending_changes = {
            "test_key": {
                "VIN": "YV2TEST0000900054",
                "AÑO - MES": "2026 - Agosto",
                "cambios": {"DYNAFLEET": 999999}
            }
        }
        
        dm = self.module.data_manager
        
        with patch.object(self.module.writer, 'update_cells', return_value=False) as mock_writer:
            self.module.confirm_save()
            
            save_finished = self._wait_until(
                lambda: self.module.btn_save.isEnabled(),
                timeout_ms=self.ASYNC_TIMEOUT_MS
            )
            self.assertTrue(save_finished, "Fallo: SaveProvisionesThread no terminó dentro del timeout.")
            
            self.assertEqual(mock_writer.call_count, 1, "Fallo: No debió intentar escribir Comercial si Provisiones falló.")
            mock_warn.assert_called()
            
            df_prov_ram = dm.get_provisiones_df()
            if not df_prov_ram.empty:
                val_ram = df_prov_ram[df_prov_ram['VIN'] == 'YV2TEST0000900054']['DYNAFLEET'].iloc[0]
                self.assertNotEqual(val_ram, 999999, "Fallo: La RAM no debió actualizarse tras fallo en Provisiones.")
                
            self.assertFalse(dm.is_app_saving, "Fallo: is_app_saving debe quedar en False tras fallo.")
            
        self.module.pending_changes.clear()
        logger.info(" -> Éxito: Fallo en Provisiones aborta antes de Comercial, no actualiza RAM y libera is_app_saving.")

    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    @patch('PyQt6.QtWidgets.QMessageBox.information')
    @patch('PyQt6.QtWidgets.QMessageBox.exec')
    def test_06_fallo_cruce_comercial(self, mock_exec, mock_info, mock_warn):
        logger.info("[Test Provisiones 06] Verificando Escenario 3: Provisiones OK + Comercial FAIL...")
        mock_exec.return_value = QMessageBox.StandardButton.Save
        
        self.module.pending_changes = {
            "test_key": {
                "VIN": "YV2TEST0000900054",
                "AÑO - MES": "2026 - Agosto",
                "cambios": {"Plan": "PLAN_FANTASMA"}
            }
        }
        
        dm = self.module.data_manager
        self._dejar_contrato_en_forma_provision('YV2TEST0000900054')
        
        with patch.object(self.module.writer, 'update_cells', side_effect=[True, False]) as mock_writer:
            self.module.confirm_save()
            
            save_finished = self._wait_until(
                lambda: self.module.btn_save.isEnabled(),
                timeout_ms=self.ASYNC_TIMEOUT_MS
            )
            self.assertTrue(save_finished, "Fallo: SaveProvisionesThread no terminó dentro del timeout.")
            
            self.assertEqual(mock_writer.call_count, 2, "Fallo: Debió intentar guardar Provisiones y luego Comercial.")
            mock_warn.assert_called()
            args, _ = mock_warn.call_args
            self.assertIn("Comercial", args[2], "Fallo: El mensaje de error debe advertir que Comercial falló.")
            
            df_com_ram = dm.get_comercial_df()
            if not df_com_ram.empty:
                plan_ram = df_com_ram[df_com_ram['VIN'] == 'YV2TEST0000900054']['TIPO DE SERVICIO'].iloc[0]
                self.assertNotEqual(plan_ram, "PLAN_FANTASMA", "Fallo: Comercial en RAM no debió actualizarse como si hubiera éxito.")
                
            self.assertFalse(dm.is_app_saving, "Fallo: is_app_saving debe quedar en False.")
            
        self.module.pending_changes.clear()
        logger.info(" -> Éxito: Fallo en Comercial se detecta, no produce falso éxito en RAM y advierte al usuario.")

    def test_07_menu_contextual_no_hereda_eliminar_camion(self):
        logger.info("[Test Provisiones 07] Verificando que la tabla no herede el menú contextual de Comercial...")
        self.assertNotEqual(
            self.module.table.menu_type, "comercial",
            "Fallo: la tabla de Provisiones no debe mostrar 'Eliminar Camión' (menu_type='comercial')."
        )
        logger.info(" -> Éxito: Provisiones ya no muestra la opción 'Eliminar Camión' en su menú contextual.")


class TestConstruirRegistroNuevoDesdeProvisiones(unittest.TestCase):
    """_construir_registro_nuevo_desde_provisiones(): arma el registro nuevo
    para vincular un VIN huérfano de Provisiones con Comercial, reutilizando
    los defaults/cálculos de 'Gestión de Unidades' (no reimplementa ninguna
    regla de negocio, ver comercial_agregar.py)."""

    def test_defaults_de_unidad_nueva_se_aplican(self):
        registro = _construir_registro_nuevo_desde_provisiones("9BVRG30C9TE900018", "Full", "24", candidato=None)
        self.assertEqual(registro["ESTADO COMERCIAL"], "Revisar")
        self.assertEqual(registro["ESTADO DE ACTIVACIÓN ACTUAL"], "No aplica")
        self.assertEqual(registro["FORMA DE CONTRATO"], "Sin Contrato")
        self.assertEqual(registro["TIPO DE FACTURACION"], "SIN REGISTRO")
        self.assertEqual(registro["INDUSTRIA"], "NO DEFINIDA")
        self.assertEqual(registro["OBSERVACIONES"], "Viene de Provisiones")
        for campo in ("FECHA DE BAJA", "ESTADO DE ENTREGA"):
            self.assertEqual(registro[campo], "-")
        # INICIO/TERMINO (30-09-2026) salen de las fechas de JustTime calculadas
        # desde el mes actual y la cantidad de meses, ya no quedan en "-".
        inicio, termino = provisiones_services.calcular_fechas_justtime("24")
        self.assertEqual(registro["INICIO"], inicio)
        self.assertEqual(registro["TERMINO"], termino)
        # CONTRATO CREADO EN JUSTTIME (30-09-2026, a pedido explícito): una
        # unidad nueva de Provisiones queda "Pendiente" de gestión en
        # JustTime, no "-" -- Provisión no implica contrato ya creado, pero
        # tampoco es "sin dato": hay una acción real por hacer.
        self.assertEqual(registro["CONTRATO CREADO EN JUSTTIME"], "Pendiente")
        self.assertEqual(registro["INICIO CONTRATO"], "")
        self.assertEqual(registro["TÉRMINO CONTRATO"], "")

    def test_chasis_y_modelo_se_derivan_del_vin(self):
        registro = _construir_registro_nuevo_desde_provisiones("9BVRG30C9TE900018", "Full", "24")
        self.assertEqual(registro["CHASIS"], "E900018")
        self.assertEqual(registro["MODELO"], "FH")

    def test_etapa_gestion_se_calcula_con_la_matriz_existente(self):
        registro = _construir_registro_nuevo_desde_provisiones("9BVRG30C9TE900018", "Full", "24")
        self.assertEqual(registro["ETAPA GESTIÓN"], "COMERCIAL")

    def test_plan_y_meses_se_copian_de_provisiones(self):
        registro = _construir_registro_nuevo_desde_provisiones("9BVRG30C9TE900018", "Medio", "12")
        self.assertEqual(registro["TIPO DE SERVICIO"], "Medio")
        self.assertEqual(registro["DURACIÓN (MESES)"], "12")

    def test_plan_placeholder_0_no_se_copia(self):
        registro = _construir_registro_nuevo_desde_provisiones("9BVRG30C9TE900018", "0", "12")
        self.assertEqual(registro["TIPO DE SERVICIO"], "-")

    def test_candidato_comercial_completa_razon_social_rut_cdb_ejecutivo(self):
        candidato = {"RAZÓN SOCIAL": "Transportes Nihuil Limitada", "RUT": "31.455.522-3", "CDB": "999", "EJECUTIVO": "Juan Perez"}
        registro = _construir_registro_nuevo_desde_provisiones("9BVRG30C9TE900018", "Full", "24", candidato=candidato)
        self.assertEqual(registro["RAZÓN SOCIAL"], "Transportes Nihuil Limitada")
        self.assertEqual(registro["RUT"], "31.455.522-3")
        self.assertEqual(registro["CDB"], "999")
        self.assertEqual(registro["EJECUTIVO"], "Juan Perez")

    def test_sin_candidato_datos_comerciales_quedan_vacios(self):
        registro = _construir_registro_nuevo_desde_provisiones("9BVRG30C9TE900018", "Full", "24", candidato=None)
        self.assertEqual(registro["RAZÓN SOCIAL"], "")
        self.assertEqual(registro["RUT"], "")
        self.assertEqual(registro["CDB"], "")
        self.assertEqual(registro["EJECUTIVO"], "")