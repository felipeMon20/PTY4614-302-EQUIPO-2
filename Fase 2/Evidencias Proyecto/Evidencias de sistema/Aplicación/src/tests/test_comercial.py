import os
import time
import csv
import shutil
import tempfile
import unittest
import builtins
import openpyxl
from datetime import datetime, timedelta
import pandas as pd
from PyQt6.QtCore import QEventLoop, QTimer, Qt, QItemSelection, QItemSelectionModel
import logging
from unittest.mock import patch
from PyQt6.QtWidgets import QMessageBox, QApplication, QPushButton, QDialog, QAbstractItemView, QLabel
from PyQt6.QtGui import QColor

import config.settings
from src.ui.comercial import (
    ComercialModule, _ComercialModuleLegacy, SaveExcelThread,
    DialogoAccionCm,
    NEW_UI_SUBTAB_COLUMN_WIDTHS, EnviarPapeleraThread,
)
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.dataframe_formatter import DataFrameFormatter
from src.services import comercial_services
from src.services.cm_bajas_service import (
    CASOS_BAJA_CM_COLUMNS, ESTADO_CASO_PENDIENTE, ESTADO_CASO_REAPARECIDO,
    ESTADO_CASO_MANTENIDO, ESTADO_CASO_CONFIRMADA_BAJA,
    ORIGEN_CASO_AUSENCIA_3PC, ORIGEN_CASO_ESTADO_EXPIRED,
    leer_casos_baja_cm, guardar_casos_baja_cm,
)
from src.theme.colors import WARNING, PRIMARY, DANGER

logger = logging.getLogger("TestRunner")

class TestComercial(unittest.TestCase):
    ASYNC_TIMEOUT_MS = 20000

    @staticmethod
    def _wait_until(predicate, timeout_ms=20000, interval_ms=20):
        """Procesa eventos Qt hasta que predicate sea True o venza el timeout."""
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
        logger.info("Instanciando Módulo Comercial y DataManager...")
        cls.dm = DataManager()
        
        # Forzamos la recarga asíncrona apuntando explícitamente a los datos del mock
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec() 
        
        cls.module = ComercialModule()

    def test_01_carga_datos_falsos(self):
        logger.info("[Test 01] Verificando que Comercial haya cargado los camiones de prueba...")
        df_actual = self.module.legacy.df_base

        self.assertFalse(df_actual.empty, "Fallo: Comercial no cargó datos.")
        self.assertTrue(len(df_actual) >= 2, f"Fallo: Se esperaban al menos 2 filas de prueba, se encontraron {len(df_actual)}.")
        logger.info(" -> Éxito: Los camiones de prueba fueron cargados.")

    @patch('PyQt6.QtWidgets.QMessageBox.warning')
    @patch('PyQt6.QtWidgets.QMessageBox.information')
    @patch('PyQt6.QtWidgets.QMessageBox.exec')
    def test_07_envio_a_papelera_asincrono(self, mock_exec, mock_info, mock_warn):
        """"Enviar a papelera" (solo contratos SIN VC) reemplaza a la antigua
        opción "Eliminar Camión": mismo borrado a RegistroEliminado, ahora
        por ID cuando el contrato lo tiene (los datos mock no traen ID, así
        que aquí cae al VIN)."""
        logger.info("[Test 07] Verificando el envío asíncrono a la papelera...")

        df_actual = self.module.legacy.df_base
        if len(df_actual) < 2:
            self.skipTest("No hay suficientes filas para probar la eliminación.")

        vin_a_eliminar = df_actual.iloc[1]['VIN']

        resultado = {}
        self.module._papelera_thread = EnviarPapeleraThread(
            self.module.legacy.writer, [(vin_a_eliminar, None)], module_name="Comercial")
        self.module._papelera_thread.finished_signal.connect(lambda ok, hechos: resultado.update(ok=ok, hechos=hechos))
        self.module._papelera_thread.start()

        finished = self._wait_until(lambda: 'ok' in resultado, timeout_ms=self.ASYNC_TIMEOUT_MS)
        self.assertTrue(finished, "Fallo: EnviarPapeleraThread no terminó dentro del timeout estipulado de 20s.")
        self.assertTrue(resultado['ok'])
        self.assertEqual(resultado['hechos'], [(vin_a_eliminar, None)])
        self.module._on_papelera_finished(resultado['ok'], resultado['hechos'])

        df_maestro = self.module.data_manager.df_master
        existe = (df_maestro['VIN'] == vin_a_eliminar).any()
        
        self.assertFalse(existe, "Fallo: El camión no fue eliminado de la memoria principal.")
        logger.info(" -> Éxito: El registro fue eliminado de forma síncrona y no quedan hilos rezagados.")


class TestComercialTabsEstructura(unittest.TestCase):
    """Cubre la estructura de ComercialModule: dos pestañas principales
    ('Comercial', la nueva interfaz, y 'Gestión de unidades', alta/edición
    centralizada). 'Vista Completa' ya no se muestra (29-09-2026, a pedido
    explícito): _ComercialModuleLegacy sigue existiendo oculto como motor de
    datos y guardado de la nueva interfaz. Verifica que siga funcionando, que
    no se duplique la carga de datos ni se cree una segunda instancia."""

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

    @staticmethod
    def _wait_until(predicate, timeout_ms=1000, interval_ms=20):
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if predicate():
                return True
            time.sleep(interval_ms / 1000.0)
        QApplication.processEvents()
        return bool(predicate())

    def test_01_tiene_exactamente_dos_pestanas(self):
        modulo = ComercialModule()
        self.assertEqual(modulo.tabs.count(), 2, "Fallo: Comercial debe tener exactamente 2 pestañas.")

    def test_02_primera_pestana_es_comercial(self):
        modulo = ComercialModule()
        self.assertEqual(modulo.tabs.tabText(0), "Comercial")

    def test_02b_segunda_pestana_es_gestion_de_unidades(self):
        modulo = ComercialModule()
        self.assertEqual(modulo.tabs.tabText(1), "Gestión de unidades")

    def test_03_vista_completa_ya_no_es_pestana(self):
        modulo = ComercialModule()
        textos = [modulo.tabs.tabText(i) for i in range(modulo.tabs.count())]
        self.assertNotIn("Vista Completa", textos)
        self.assertEqual(modulo.tabs.indexOf(modulo.legacy), -1)

    def test_04_interfaz_antigua_es_la_implementacion_real_y_sigue_funcional(self):
        modulo = ComercialModule()
        self.assertIsInstance(modulo.legacy, _ComercialModuleLegacy)
        self.assertIs(modulo.legacy.parent(), modulo,
                      "Fallo: la interfaz antigua debe seguir viviendo dentro de ComercialModule (oculta).")
        self.assertTrue(modulo.legacy.isHidden(), "Fallo: la interfaz antigua no debe mostrarse.")

        self.assertFalse(modulo.legacy.df_base.empty, "Fallo: la interfaz antigua debe seguir cargando los datos como antes.")

        # Acceso transparente (delegado, sin duplicar logica) a la API de siempre.
        for attr in ('df_base', 'load_data', 'refresh_if_dirty', 'guardar_edicion_unidad'):
            self.assertTrue(hasattr(modulo, attr), f"Fallo: ComercialModule perdió el atributo/método '{attr}'.")

    def test_05_primera_pestana_no_es_la_interfaz_antigua(self):
        modulo = ComercialModule()
        placeholder = modulo.tabs.widget(0)
        self.assertIsNot(placeholder, modulo.legacy)

    def test_05b_nueva_interfaz_reusa_kpis_bandeja_y_datos_de_la_interfaz_antigua(self):
        """La Nueva interfaz (4 sub-pestañas desde el 08-10-2026) calcula los
        KPI y la bandeja de la sub-pestaña activa sobre self.legacy.df_base,
        sin segunda carga de datos. Por defecto abre "Renovar contratos"
        (índice 0), que muestra primero una fila por FLOTA VC."""
        modulo = ComercialModule()

        self.assertEqual(set(modulo.new_ui_kpi_labels.keys()), {"total", "vencidas", "por_vencer", "vigentes"})
        df_esperada = comercial_services.filtrar_renovar_clientes(modulo._df_base_por_periodo(modulo.legacy.df_base))
        kpis_esperados = comercial_services.calcular_kpis_renovar_clientes(df_esperada)
        for key, lbl in modulo.new_ui_kpi_labels.items():
            self.assertEqual(lbl.text(), str(kpis_esperados[key]))

        model = modulo.new_ui_model
        headers = [model.headerData(i, Qt.Orientation.Horizontal) for i in range(model.columnCount())]
        self.assertTrue(modulo._new_ui_en_grupos, "Fallo: sin grupo abierto la bandeja resume una fila por flota.")
        self.assertEqual(headers, ["FLOTA VC", "UNIDADES VENCIDAS", "VENCEN EN 30 DÍAS", "VIGENTES", "TOTAL UNIDADES"])
        serie = df_esperada["FLOTA VC"].fillna('').astype(str).str.strip()
        serie = serie.mask(serie.str.upper().isin(['', 'NAN', 'NONE', 'NAT', '-', '<NA>']), modulo._NEW_UI_VALOR_SIN_GRUPO)
        self.assertEqual(model.rowCount(), serie.nunique())

        self.assertEqual(
            [modulo.new_ui_subtabs.tabText(i) for i in range(modulo.new_ui_subtabs.count())],
            ["Renovar contratos", "Recuperar clientes", "Nuevas oportunidades", "Oportunidades CM"],
        )
    def test_06_construccion_no_duplica_la_carga_de_datos(self):
        with patch.object(_ComercialModuleLegacy, 'load_data', autospec=True) as mock_load:
            ComercialModule()
        self.assertEqual(mock_load.call_count, 1,
                          "Fallo: crear las dos pestañas no debe disparar una segunda carga de datos ni una segunda instancia funcional.")

    def test_07_una_sola_instancia_legacy_por_modulo(self):
        modulo = ComercialModule()
        legacy_widgets = modulo.findChildren(_ComercialModuleLegacy)
        self.assertEqual(len(legacy_widgets), 1, "Fallo: debe existir una única instancia funcional de Comercial, no dos.")

    def test_08_navegacion_entre_pestanas_respeta_refresh_if_dirty(self):
        """Volver a la pestaña 'Comercial' con datos marcados como sucios
        recarga una sola vez a través de la interfaz antigua oculta."""
        modulo = ComercialModule()
        modulo.show()
        QApplication.processEvents()
        try:
            self.assertFalse(modulo.legacy.isVisible(), "Fallo: la interfaz antigua no debe mostrarse.")
            modulo.tabs.setCurrentIndex(1)
            QApplication.processEvents()

            modulo._data_dirty = True
            with patch.object(modulo, 'load_data', wraps=modulo.load_data) as spy_load:
                modulo.tabs.setCurrentIndex(0)
                QApplication.processEvents()
                self._wait_until(lambda: spy_load.called, timeout_ms=1000)

            spy_load.assert_called_once()
            self.assertFalse(modulo._data_dirty, "Fallo: refresh_if_dirty debió limpiar el flag al volver a 'Comercial'.")
        finally:
            modulo.hide()

    def test_09b_subpestanas_filtran_con_reglas_reales(self):
        """Las sub-pestañas de la Nueva interfaz (Renovar contratos /
        Recuperar clientes / Nuevas oportunidades) ejecutan filtros de
        negocio reales al cambiar de índice. "Oportunidades CM" (índice 3)
        no sale de df_base y se cubre aparte en TestComercialRevisionCM."""
        modulo = ComercialModule()
        modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["A", "B", "C", "D"],
            "VIN": ["V1", "V2", "V3", "V4"],
            "CHASIS": ["C1", "C2", "C3", "C4"],
            "TIPO DE SERVICIO": ["Full", "Full", "Full", "Full"],
            "ESTADO COMERCIAL": ["VIGENTE", "BAJA", "VIGENTE", "VIGENTE"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO", "DESCONECTADO", "NO APLICA", "CONECTADO"],
            "TÉRMINO CONTRATO": [
                (datetime.now().date() + timedelta(days=10)).strftime('%d-%m-%Y'),   # por vencer
                "MENSUAL",
                "MENSUAL",
                (datetime.now().date() + timedelta(days=365)).strftime('%d-%m-%Y'),  # vigente, lejos de vencer
            ],
        })

        # Sin columna FLOTA VC la bandeja de Renovar contratos y Recuperar
        # clientes se ve plana; Nuevas oportunidades siempre agrupa por razón
        # social, así que se abre el grupo para ver sus unidades.
        modulo._on_new_ui_subtab_changed(0)  # "Renovar contratos"
        self.assertEqual(modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["C1", "C4"])

        modulo._on_new_ui_subtab_changed(1)  # "Recuperar clientes"
        self.assertEqual(modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["C2"])

        modulo._on_new_ui_subtab_changed(2)  # "Nuevas oportunidades"
        modulo._new_ui_grupo_abierto[2] = "C"
        modulo._refresh_new_ui_data()
        self.assertEqual(modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["C3"])
    def test_09_pestana_comercial_expone_refresh_if_dirty_para_mainwindow(self):
        """MainWindow._get_active_submodule() resuelve self.tabs.currentWidget()
        cuando el modulo expone 'tabs' (ver comentario en ComercialModule.__init__),
        asi que new_ui_tab necesita el mismo contrato que _ComercialModuleLegacy
        para poder refrescarse al quedar activo por defecto."""
        modulo = ComercialModule()
        modulo.show()
        QApplication.processEvents()
        try:
            self.assertIs(modulo.tabs.currentWidget(), modulo.new_ui_tab)
            self.assertTrue(hasattr(modulo.new_ui_tab, 'refresh_if_dirty'),
                             "Fallo: new_ui_tab debe exponer refresh_if_dirty para que MainWindow pueda refrescarlo.")

            modulo._data_dirty = True
            with patch.object(modulo, 'load_data', wraps=modulo.load_data) as spy_load:
                modulo.new_ui_tab.refresh_if_dirty()
                self._wait_until(lambda: spy_load.called, timeout_ms=1000)

            spy_load.assert_called_once()
            self.assertFalse(modulo._data_dirty)
        finally:
            modulo.hide()

    def test_10_columnas_configuradas_por_subpestana_maximo_seis(self):
        """Columnas por sub-pestaña (NEW_UI_SUBTAB_COLUMNS, máx. 6): se
        muestran las configuradas que existan en la base, en ese orden.
        "Oportunidades CM" no sale de df_base y se cubre en
        TestComercialRevisionCM. VIN queda fuera a propósito (sigue siendo
        buscable, ver test_13 a test_16)."""
        modulo = ComercialModule()
        modulo.legacy.df_base = pd.DataFrame({
            "EJECUTIVO": ["E1", "E2"],
            "RAZÓN SOCIAL": ["A", "B"],
            "VIN": ["V1", "V2"],
            "CHASIS": ["C1", "C2"],
            "FORMA DE CONTRATO": ["CMG", "CMB"],
            "TIPO DE SERVICIO": ["Full", "Medio"],
            "ESTADO COMERCIAL": ["VIGENTE", "BAJA"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["NO APLICA", "DESCONECTADO"],
            "ETAPA GESTIÓN": ["CLIENTE", "COMERCIAL"],
            "FECHA DE BAJA": ["", "15-08-2026"],
            "OBSERVACIONES": ["", "Vencido"],
            "TÉRMINO CONTRATO": ["MENSUAL", "15-08-2026"],
        })

        columnas_esperadas = {
            0: ["RAZÓN SOCIAL", "CHASIS", "FORMA DE CONTRATO", "TÉRMINO CONTRATO", "ESTADO COMERCIAL", "ESTADO DE ACTIVACIÓN ACTUAL"],
            1: ["RAZÓN SOCIAL", "CHASIS", "ESTADO DE ACTIVACIÓN ACTUAL", "FECHA DE BAJA"],
            2: ["RAZÓN SOCIAL", "CHASIS", "FORMA DE CONTRATO", "ESTADO COMERCIAL", "VOLVO CONNECT"],
        }
        for idx, esperado in columnas_esperadas.items():
            modulo._on_new_ui_subtab_changed(idx)
            if idx == 2:
                # Nuevas oportunidades agrupa por razón social: se abre el grupo para ver las unidades
                modulo._new_ui_grupo_abierto[2] = "A"
                modulo._refresh_new_ui_data()
            headers = [
                modulo.new_ui_model.headerData(i, Qt.Orientation.Horizontal)
                for i in range(modulo.new_ui_model.columnCount())
            ]
            self.assertEqual(headers, esperado, f"Fallo en columnas de la sub-pestaña índice {idx}.")
            self.assertLessEqual(len(headers), 6, "Fallo: ninguna sub-pestaña debe superar las 6 columnas.")
    def test_11_cambiar_de_subpestana_reutiliza_la_misma_tabla(self):
        """El cambio dinámico de columnas debe hacerse sobre la misma
        instancia de tabla/modelo (una sola tabla reutilizable), no creando
        una tabla nueva por cada sub-pestaña."""
        modulo = ComercialModule()
        tabla_antes, modelo_antes = modulo.new_ui_table, modulo.new_ui_model

        for idx in (1, 2, 3, 0):
            modulo._on_new_ui_subtab_changed(idx)
            self.assertIs(modulo.new_ui_table, tabla_antes)
            self.assertIs(modulo.new_ui_model, modelo_antes)

    def test_11b_ejecutivo_etapa_gestion_observaciones_ocultas_pero_siguen_en_df_base(self):
        """Ajuste pedido por el usuario (14-09-2026): EJECUTIVO no debe verse
        en Por gestionar/Renovaciones/Gestionar Bajas, ETAPA GESTIÓN no debe
        verse en Por gestionar, y OBSERVACIONES no debe verse en Gestionar
        Bajas -- pero ninguna de las tres debe desaparecer de df_base (los
        filtros de negocio siguen necesitándolas)."""
        modulo = ComercialModule()
        modulo.legacy.df_base = pd.DataFrame({
            "EJECUTIVO": ["E1", "E2"],
            "RAZÓN SOCIAL": ["A", "B"],
            "VIN": ["V1", "V2"],
            "CHASIS": ["C1", "C2"],
            "FORMA DE CONTRATO": ["CMG", "CMB"],
            "TIPO DE SERVICIO": ["Full", "Medio"],
            "ESTADO COMERCIAL": ["VIGENTE", "BAJA"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["NO APLICA", "DESCONECTADO"],
            "ETAPA GESTIÓN": ["CLIENTE", "COMERCIAL"],
            "FECHA DE BAJA": ["", "15-08-2026"],
            "OBSERVACIONES": ["", "Vencido"],
            "TÉRMINO CONTRATO": ["MENSUAL", "15-08-2026"],
        })

        for idx in (0, 1, 2):
            modulo._on_new_ui_subtab_changed(idx)
            headers = list(modulo.new_ui_model.get_df().columns)
            self.assertNotIn("EJECUTIVO", headers, f"Fallo: EJECUTIVO visible en sub-pestaña {idx}.")

        modulo._on_new_ui_subtab_changed(0)  # "Por gestionar"
        self.assertNotIn("ETAPA GESTIÓN", list(modulo.new_ui_model.get_df().columns))

        modulo._on_new_ui_subtab_changed(2)  # "Gestionar Bajas"
        self.assertNotIn("OBSERVACIONES", list(modulo.new_ui_model.get_df().columns))

        # Las tres columnas siguen intactas en la fuente real de datos.
        for col in ("EJECUTIVO", "ETAPA GESTIÓN", "OBSERVACIONES"):
            self.assertIn(col, modulo.legacy.df_base.columns,
                           f"Fallo: {col} no debería eliminarse de df_base, solo ocultarse.")

    def test_11c_razon_social_recibe_ancho_mayor_en_las_4_subpestanas(self):
        """RAZÓN SOCIAL recibe en cada sub-pestaña el ancho calibrado en
        NEW_UI_SUBTAB_COLUMN_WIDTHS (mayor que el estándar) al abrirla, sin
        que el usuario tenga que redimensionar a mano. "Oportunidades CM"
        queda fuera a propósito (no estaba en el pedido)."""
        modulo = ComercialModule()
        modulo.legacy.df_base = pd.DataFrame({
            "EJECUTIVO": ["E1", "E2"],
            "RAZÓN SOCIAL": ["A", "B"],
            "VIN": ["V1", "V2"],
            "CHASIS": ["C1", "C2"],
            "FORMA DE CONTRATO": ["CMG", "CMB"],
            "TIPO DE SERVICIO": ["Full", "Medio"],
            "ESTADO COMERCIAL": ["VIGENTE", "BAJA"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["NO APLICA", "DESCONECTADO"],
            "ETAPA GESTIÓN": ["CLIENTE", "COMERCIAL"],
            "FECHA DE BAJA": ["", "15-08-2026"],
            "OBSERVACIONES": ["", "Vencido"],
            "TÉRMINO CONTRATO": ["MENSUAL", "15-08-2026"],
        })

        for idx in (0, 1, 2):
            modulo._on_new_ui_subtab_changed(idx)
            if idx == 2:
                modulo._new_ui_grupo_abierto[2] = "A"
                modulo._refresh_new_ui_data()
            headers = list(modulo.new_ui_model.get_df().columns)
            col_idx = headers.index('RAZÓN SOCIAL')
            ancho_esperado = NEW_UI_SUBTAB_COLUMN_WIDTHS[idx]['RAZÓN SOCIAL']
            self.assertGreater(ancho_esperado, 140)  # mayor que el ancho estándar de columna
            self.assertEqual(
                modulo.new_ui_table.columnWidth(col_idx), ancho_esperado,
                f"Fallo: RAZÓN SOCIAL no recibió el ancho calibrado en la sub-pestaña índice {idx}.",
            )
    def test_12_renovar_contratos_muestra_termino_de_contrato_y_no_dias_restantes(self):
        """"Renovar contratos" une renovaciones, vencidos y vigentes y muestra
        TÉRMINO CONTRATO; la columna DÍAS RESTANTES ya no existe en la bandeja
        (el formato de días se cubre en TestFormatearDiasRestantes)."""
        modulo = ComercialModule()
        hoy = datetime.now().date()
        modulo.legacy.df_base = pd.DataFrame({
            "EJECUTIVO": ["E1", "E2", "E3"],
            "RAZÓN SOCIAL": ["A", "B", "C"],
            "VIN": ["V1", "V2", "V3"],
            "CHASIS": ["C1", "C2", "C3"],
            "FORMA DE CONTRATO": ["CMG", "CMG", "CMG"],
            "TIPO DE SERVICIO": ["Full", "Full", "Full"],
            "ESTADO COMERCIAL": ["VENCIDO", "VIGENTE", "VIGENTE"],
            "TÉRMINO CONTRATO": [
                (hoy - timedelta(days=3)).strftime('%d-%m-%Y'),
                hoy.strftime('%d-%m-%Y'),
                (hoy + timedelta(days=10)).strftime('%d-%m-%Y'),
            ],
        })

        modulo._on_new_ui_subtab_changed(0)  # "Renovar contratos"
        df = modulo.new_ui_model.get_df()
        self.assertNotIn("DÍAS RESTANTES", df.columns)
        self.assertIn("TÉRMINO CONTRATO", df.columns)
        self.assertEqual(sorted(df["CHASIS"].tolist()), ["C1", "C2", "C3"],
                         "Fallo: Renovar contratos debe incluir vencidos, por vencer y vigentes.")
    def test_13_busqueda_global_encuentra_por_vin_aunque_no_sea_columna_visible(self):
        """Simula exactamente el contrato de MainWindow._on_global_search():
        setear texto en new_ui_tab.search_input y llamar a
        new_ui_tab.filter_table(). VIN nunca es columna visible de la Nueva
        interfaz, pero debe seguir siendo buscable porque la máscara se
        arma sobre los datos completos, antes de recortar columnas."""
        modulo = ComercialModule()
        fecha_por_vencer = (datetime.now().date() + timedelta(days=10)).strftime('%d-%m-%Y')
        modulo.legacy.df_base = pd.DataFrame({
            "EJECUTIVO": ["E1", "E2"],
            "RAZÓN SOCIAL": ["EMPRESA UNO", "EMPRESA DOS"],
            "VIN": ["YV2ABCDEF0000001", "YV2ABCDEF0000002"],
            "CHASIS": ["0000001", "0000002"],
            "FORMA DE CONTRATO": ["CMG", "CMG"],
            "TIPO DE SERVICIO": ["Full", "Full"],
            "ESTADO COMERCIAL": ["VIGENTE", "VIGENTE"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO", "CONECTADO"],
            "ETAPA GESTIÓN": ["CLIENTE", "CLIENTE"],
            "TÉRMINO CONTRATO": [fecha_por_vencer, fecha_por_vencer],
        })

        self.assertTrue(hasattr(modulo.new_ui_tab, 'search_input'),
                         "Fallo: new_ui_tab debe exponer search_input para que MainWindow._on_global_search lo use.")
        self.assertTrue(hasattr(modulo.new_ui_tab, 'filter_table'),
                         "Fallo: new_ui_tab debe exponer filter_table para que MainWindow._on_global_search lo use.")

        modulo._on_new_ui_subtab_changed(0)  # "Renovar contratos" (VIN tampoco es columna visible aquí)
        modulo.new_ui_tab.search_input.setText("YV2ABCDEF0000002")
        modulo.new_ui_tab.filter_table()

        df = modulo.new_ui_model.get_df()
        self.assertNotIn("VIN", df.columns, "Fallo: VIN no debe ser columna visible de Renovar contratos.")
        self.assertEqual(df["CHASIS"].tolist(), ["0000002"])
    def test_14_busqueda_global_encuentra_por_razon_social_y_chasis(self):
        modulo = ComercialModule()
        fecha_por_vencer = (datetime.now().date() + timedelta(days=10)).strftime('%d-%m-%Y')
        modulo.legacy.df_base = pd.DataFrame({
            "EJECUTIVO": ["E1", "E2"],
            "RAZÓN SOCIAL": ["EMPRESA UNO", "EMPRESA DOS"],
            "VIN": ["V1", "V2"],
            "CHASIS": ["0000001", "0000002"],
            "FORMA DE CONTRATO": ["CMG", "CMG"],
            "ESTADO COMERCIAL": ["VIGENTE", "VIGENTE"],
            "TÉRMINO CONTRATO": [fecha_por_vencer, fecha_por_vencer],
            "ETAPA GESTIÓN": ["CLIENTE", "CLIENTE"],
        })
        modulo._on_new_ui_subtab_changed(0)  # "Renovar contratos" (ambas filas por vencer, pasan el filtro)

        modulo.new_ui_tab.search_input.setText("empresa dos")
        modulo.new_ui_tab.filter_table()
        self.assertEqual(modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["0000002"])

        modulo.new_ui_tab.search_input.setText("0000001")
        modulo.new_ui_tab.filter_table()
        self.assertEqual(modulo.new_ui_model.get_df()["RAZÓN SOCIAL"].tolist(), ["EMPRESA UNO"])
    def test_15_busqueda_global_respeta_subpestana_activa(self):
        """La búsqueda debe combinarse con el filtro de negocio de la
        sub-pestaña activa, no reemplazarlo."""
        modulo = ComercialModule()
        fecha_por_vencer = (datetime.now().date() + timedelta(days=10)).strftime('%d-%m-%Y')
        modulo.legacy.df_base = pd.DataFrame({
            "EJECUTIVO": ["E1", "E2"],
            "RAZÓN SOCIAL": ["EMPRESA UNO", "EMPRESA UNO"],
            "VIN": ["V1", "V2"],
            "CHASIS": ["0000001", "0000002"],
            "FORMA DE CONTRATO": ["CMG", "CMG"],
            "ESTADO COMERCIAL": ["VIGENTE", "BAJA"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO", "DESCONECTADO"],
            "TÉRMINO CONTRATO": [fecha_por_vencer, fecha_por_vencer],
            "ETAPA GESTIÓN": ["CLIENTE", "CLIENTE"],
        })

        modulo.new_ui_tab.search_input.setText("empresa uno")

        modulo._on_new_ui_subtab_changed(1)  # "Recuperar clientes": solo bajas Desconectadas, etc.
        modulo.new_ui_tab.filter_table()
        self.assertEqual(modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["0000002"])

        # "Renovar contratos": solo 0000001 (Vigente y Conectada); 0000002 es una baja
        modulo._on_new_ui_subtab_changed(0)
        modulo.new_ui_tab.filter_table()
        self.assertEqual(modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["0000001"])
    def test_16_busqueda_global_usa_construir_mascara_busqueda(self):
        """No debe existir una segunda implementación del algoritmo de
        búsqueda: la Nueva interfaz debe delegar en la misma función
        vectorizada de comercial_services."""
        modulo = ComercialModule()
        modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["A"], "VIN": ["V1"], "CHASIS": ["C1"],
            "EJECUTIVO": ["E1"], "FORMA DE CONTRATO": ["CMG"],
            "ESTADO COMERCIAL": ["VIGENTE"], "TÉRMINO CONTRATO": ["MENSUAL"],
            "ETAPA GESTIÓN": ["CLIENTE"],
        })
        # La mascara se construye igual aunque el filtro de "Renovaciones"
        # termine dejando la bandeja vacia (MENSUAL no pasa ese filtro): lo
        # que este test verifica es que se llama a la funcion compartida,
        # no cuantas filas devuelve.
        modulo._on_new_ui_subtab_changed(1)  # "Renovaciones"
        modulo.new_ui_tab.search_input.setText("v1")

        with patch.object(comercial_services, 'construir_mascara_busqueda',
                           wraps=comercial_services.construir_mascara_busqueda) as spy:
            modulo.new_ui_tab.filter_table()

        spy.assert_called_once()

    def test_17_ordenar_columna_reordena_la_bandeja(self):
        """Elegir 'Ordenar A -> Z'/'Z -> A' en el menú de encabezado de la
        bandeja de la Nueva interfaz debe reordenar las filas (mismo
        mecanismo que dispara el menú: VolvoTableWidget._set_sort())."""
        modulo = ComercialModule()
        modulo.legacy.df_base = pd.DataFrame({
            "EJECUTIVO": ["C", "A", "B"],
            "RAZÓN SOCIAL": ["Empresa C", "Empresa A", "Empresa B"],
            "VIN": ["V1", "V2", "V3"],
            "CHASIS": ["C1", "C2", "C3"],
            "FORMA DE CONTRATO": ["CMG", "CMG", "CMG"],
            "TIPO DE SERVICIO": ["Full", "Full", "Full"],
            "ESTADO COMERCIAL": ["VIGENTE", "VIGENTE", "VIGENTE"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO", "CONECTADO", "CONECTADO"],
            "ETAPA GESTIÓN": ["CLIENTE", "CLIENTE", "CLIENTE"],
            "TÉRMINO CONTRATO": ["MENSUAL", "MENSUAL", "MENSUAL"],
        })
        modulo._on_new_ui_subtab_changed(0)  # "Renovar contratos" (RAZÓN SOCIAL es la 1ra columna)

        self.assertEqual(modulo.new_ui_model.get_df()["RAZÓN SOCIAL"].tolist(), ["Empresa C", "Empresa A", "Empresa B"])

        modulo.new_ui_table._set_sort("RAZÓN SOCIAL", Qt.SortOrder.AscendingOrder)
        self.assertEqual(modulo.new_ui_model.get_df()["RAZÓN SOCIAL"].tolist(), ["Empresa A", "Empresa B", "Empresa C"])

        modulo.new_ui_table._set_sort("RAZÓN SOCIAL", Qt.SortOrder.DescendingOrder)
        self.assertEqual(modulo.new_ui_model.get_df()["RAZÓN SOCIAL"].tolist(), ["Empresa C", "Empresa B", "Empresa A"])
    def _df_dias_restantes_mixto(self):
        # Actualizado 28-09-2026 (regla de "Renovaciones" endurecida, a
        # pedido explícito): ya vencido queda fuera de Renovaciones (va a
        # "Vencidos"), así que las 4 filas usan ESTADO COMERCIAL Vigente y
        # términos "por vencer" a distintas distancias -- solo VENCE_LEJOS
        # (300 días) queda excluido, por superar los 30 días de umbral.
        hoy = datetime.now().date()
        return pd.DataFrame({
            "EJECUTIVO": ["E1", "E2", "E3", "E4"],
            "RAZÓN SOCIAL": ["A", "B", "C", "D"],
            "VIN": ["V1", "V2", "V3", "V4"],
            "CHASIS": ["VENCE_20", "VENCE_10", "VENCE_PRONTO", "VENCE_LEJOS"],
            "FORMA DE CONTRATO": ["CMG"] * 4,
            "ESTADO COMERCIAL": ["VIGENTE", "VIGENTE", "VIGENTE", "VIGENTE"],
            "TÉRMINO CONTRATO": [
                (hoy + timedelta(days=20)).strftime('%d-%m-%Y'),   # por vencer, 20 días
                (hoy + timedelta(days=10)).strftime('%d-%m-%Y'),   # por vencer, 10 días
                (hoy + timedelta(days=3)).strftime('%d-%m-%Y'),    # vence pronto
                (hoy + timedelta(days=300)).strftime('%d-%m-%Y'),  # vence lejos
            ],
        })

    def test_18_termino_contrato_ordena_cronologicamente_no_como_texto(self):
        """Ordenar TÉRMINO CONTRATO (dd-mm-aaaa) debe ser cronológico: como
        texto '05-11-2027' quedaría antes que '12-10-2027'."""
        modulo = ComercialModule()
        modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["A", "B", "C"],
            "VIN": ["V1", "V2", "V3"],
            "CHASIS": ["NOV_2027", "OCT_2027", "ENE_2028"],
            "FORMA DE CONTRATO": ["CMG"] * 3,
            "ESTADO COMERCIAL": ["VIGENTE"] * 3,
            "TÉRMINO CONTRATO": ["05-11-2027", "12-10-2027", "20-01-2028"],
        })
        modulo._on_new_ui_subtab_changed(0)  # "Renovar contratos"

        modulo.new_ui_table._set_sort("TÉRMINO CONTRATO", Qt.SortOrder.AscendingOrder)
        self.assertEqual(modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["OCT_2027", "NOV_2027", "ENE_2028"])

        modulo.new_ui_table._set_sort("TÉRMINO CONTRATO", Qt.SortOrder.DescendingOrder)
        self.assertEqual(modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["ENE_2028", "NOV_2027", "OCT_2027"])
    def test_19_sin_orden_manual_la_bandeja_conserva_el_orden_de_la_base(self):
        """Ya no hay orden por urgencia: mientras el usuario no ordene por
        una columna, las unidades salen en el orden de la base."""
        modulo = ComercialModule()
        modulo.legacy.df_base = self._df_dias_restantes_mixto()

        modulo._on_new_ui_subtab_changed(0)  # "Renovar contratos", sin clic de orden
        self.assertEqual(
            modulo.new_ui_model.get_df()["CHASIS"].tolist(),
            ["VENCE_20", "VENCE_10", "VENCE_PRONTO", "VENCE_LEJOS"],
        )
    def test_20_orden_manual_reemplaza_al_orden_por_defecto(self):
        """Una vez que el usuario hace clic en el encabezado, ese orden manda
        por sobre el orden de la base."""
        modulo = ComercialModule()
        modulo.legacy.df_base = self._df_dias_restantes_mixto()
        modulo._on_new_ui_subtab_changed(0)

        modulo.new_ui_table._set_sort("RAZÓN SOCIAL", Qt.SortOrder.DescendingOrder)
        self.assertEqual(modulo.new_ui_model.get_df()["RAZÓN SOCIAL"].tolist(), ["D", "C", "B", "A"])


class TestComercialRevisionCM(unittest.TestCase):
    """Cubre la sub-pestaña "Gestionar CM" (antes "Revisión CM"; renombrada
    14-09-2026) -- bandeja de revisión de posibles Bajas CM detectadas por
    cm_bajas_service.py, persistidas en CasosBajaCM.csv. No duplica la
    lógica de detección/persistencia (ver test_cm_bajas_service.py y
    test_contratos.py): solo cubre que la pestaña consuma correctamente los
    casos ya existentes, respete las decisiones ya tomadas
    (MANTENIDO/CONFIRMADA_BAJA) y que "Enviar correo" sea puramente visual.
    "Confirmar baja" sí modifica datos reales: ver TestConfirmarBajaCM."""

    REVISION_CM_INDEX = 3

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

        # Igual que TestComercialTabsEstructura: asegura que DataManager
        # (singleton) tenga datos cargados antes de construir ComercialModule,
        # para no depender del orden de ejecución de otras clases de test.
        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

    def _fila_caso(self, **overrides):
        fila = {c: '' for c in CASOS_BAJA_CM_COLUMNS}
        fila.update(overrides)
        return fila

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.casos_path = os.path.join(self.temp_dir.name, "CasosBajaCM_Test.csv")

        df_casos = pd.DataFrame([
            self._fila_caso(
                CASO_ID='1', VIN='VIN_PENDIENTE', CHASIS='C1',
                **{'RAZÓN SOCIAL': 'Empresa Pendiente', 'N CONTRATO 3PC': '3PC-1',
                   'FECHA INICIO CM': '01-01-2025', 'FECHA TERMINO CM': '01-01-2026',
                   'TIPO DE CM': 'Silver', 'ESTADO DEL CM': 'RUNNING', 'PAGO CM': '15000',
                   'PERIODO_DETECCION': '2026-08', 'ESTADO_CASO': ESTADO_CASO_PENDIENTE,
                   'MESES_CONSECUTIVOS_AUSENTE': '1'}
            ),
            self._fila_caso(
                CASO_ID='2', VIN='VIN_REAPARECIDO',
                **{'CHASIS': 'C2', 'RAZÓN SOCIAL': 'Empresa Reaparecida', 'ESTADO DEL CM': 'RUNNING',
                   'ESTADO_CASO': ESTADO_CASO_REAPARECIDO, 'MESES_CONSECUTIVOS_AUSENTE': '1'}
            ),
            self._fila_caso(
                CASO_ID='3', VIN='VIN_MANTENIDO',
                **{'CHASIS': 'C3', 'RAZÓN SOCIAL': 'Empresa Mantenida', 'ESTADO DEL CM': 'RUNNING',
                   'ESTADO_CASO': ESTADO_CASO_MANTENIDO, 'MESES_CONSECUTIVOS_AUSENTE': '2'}
            ),
            self._fila_caso(
                CASO_ID='4', VIN='VIN_CONFIRMADO',
                **{'CHASIS': 'C4', 'RAZÓN SOCIAL': 'Empresa Confirmada', 'ESTADO DEL CM': 'RUNNING',
                   'ESTADO_CASO': ESTADO_CASO_CONFIRMADA_BAJA, 'MESES_CONSECUTIVOS_AUSENTE': '3'}
            ),
        ])[CASOS_BAJA_CM_COLUMNS]
        guardar_casos_baja_cm(df_casos, self.casos_path)
        self._csv_original = leer_casos_baja_cm(self.casos_path)

        self._patch_path = patch.object(config.settings, 'CASOS_BAJA_CM_PATH', self.casos_path)
        self._patch_path.start()

        self.modulo = ComercialModule()
        # df_base no vacío (cualquier dato basta): la bandeja "Gestionar CM" no
        # sale de df_base, pero _refresh_new_ui_data corta antes si está vacío.
        self.modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["X"], "VIN": ["X1"], "CHASIS": ["XC1"],
            "ESTADO COMERCIAL": ["VIGENTE"], "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO"],
            "TÉRMINO CONTRATO": ["MENSUAL"],
        })

    def tearDown(self):
        self._patch_path.stop()
        self.temp_dir.cleanup()

    def _abrir_bandeja_cm(self):
        """Oportunidades CM abre primero una fila por flota: abre el grupo
        "(Sin dato)" (los casos de prueba no traen FLOTA VC) para ver las unidades."""
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        self.modulo._new_ui_grupo_abierto[self.REVISION_CM_INDEX] = self.modulo._NEW_UI_VALOR_SIN_GRUPO
        self.modulo._refresh_new_ui_data()

    def test_01_pestana_gestionar_cm_se_construye_como_cuarta_subpestana(self):
        textos = [self.modulo.new_ui_subtabs.tabText(i) for i in range(self.modulo.new_ui_subtabs.count())]
        self.assertEqual(textos, ["Renovar contratos", "Recuperar clientes", "Nuevas oportunidades", "Oportunidades CM"])
        self.assertEqual(textos[self.REVISION_CM_INDEX], "Oportunidades CM")

    def test_02_casos_pendientes_aparecen_en_la_tabla(self):
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        df = self.modulo.new_ui_model.get_df()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['RAZÓN SOCIAL'], 'Empresa Pendiente')

    def test_03_casos_reaparecido_mantenido_confirmada_baja_no_vuelven_a_aparecer(self):
        """Reaparecido ya no requiere revisión (el contrato volvió a
        aparecer); Mantenido/Confirmada baja son decisiones de Javiera ya
        tomadas y deben respetarse, no volver como pendientes."""
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        razones = self.modulo.new_ui_model.get_df()['RAZÓN SOCIAL'].tolist()
        self.assertNotIn('Empresa Reaparecida', razones)
        self.assertNotIn('Empresa Mantenida', razones)
        self.assertNotIn('Empresa Confirmada', razones)

    def test_04_columnas_esperadas(self):
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        model = self.modulo.new_ui_model
        headers = [model.headerData(i, Qt.Orientation.Horizontal) for i in range(model.columnCount())]
        self.assertTrue(self.modulo._new_ui_en_grupos, "Fallo: sin grupo abierto se resume una fila por flota.")
        self.assertEqual(headers, ["FLOTA VC", "RAZÓN SOCIAL", "UNIDADES"])

        self._abrir_bandeja_cm()
        headers = [model.headerData(i, Qt.Orientation.Horizontal) for i in range(model.columnCount())]
        self.assertEqual(headers, [
            "ACTIVACIÓN", "ESTADO COMERCIAL", "CHASIS", "FECHA INICIO CM", "FECHA TERMINO CM", "TIPO DE CM",
            "ESTADO DEL CM", "PAGO CM", "MOTIVO",
        ])

    def test_04b_motivo_traduce_ausencia_3pc_para_casos_sin_origen_explicito(self):
        """Los fixtures de este test (setUp) no setean ORIGEN_CASO -- deben
        migrarse a AUSENCIA_3PC al leerse (compatibilidad con CSV viejos,
        ver cm_bajas_service.leer_casos_baja_cm) y mostrar 'Ausente de 3PC'."""
        self._abrir_bandeja_cm()
        df = self.modulo.new_ui_model.get_df()
        self.assertEqual(df.iloc[0]['MOTIVO'], 'Ausente de 3PC')

    def test_04c_pago_cm_se_muestra_con_formato_monetario(self):
        """PAGO CM llega crudo desde CasosBajaCM.csv (texto sin formato, ej.
        '15000'). En pantalla debe verse como '$15.000'. El valor original
        (en el CSV y en _new_ui_revision_cm_df) no debe modificarse -- solo
        cambia lo que pinta el modelo de la tabla."""
        self._abrir_bandeja_cm()
        df_mostrado = self.modulo.new_ui_model.get_df()
        self.assertEqual(df_mostrado.iloc[0]['PAGO CM'], '$15.000')

        # El valor crudo sigue intacto en la copia que usa Confirmar Baja.
        df_interno = self.modulo._new_ui_revision_cm_df
        self.assertEqual(str(df_interno.iloc[0]['PAGO CM']), '15000')

        # Y el CSV en disco tampoco se tocó.
        df_csv = leer_casos_baja_cm(self.casos_path)
        fila_csv = df_csv[df_csv['VIN'] == 'VIN_PENDIENTE'].iloc[0]
        self.assertEqual(str(fila_csv['PAGO CM']), '15000')

    def test_05_sin_seleccion_las_acciones_cm_quedan_deshabilitadas(self):
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        self.assertFalse(self.modulo.btn_accion_cm_enviar_correo.isEnabled())
        self.assertFalse(self.modulo.btn_accion_cm_confirmar_baja.isEnabled())

    def test_06_seleccionar_una_fila_habilita_enviar_correo_y_confirmar_baja(self):
        self._abrir_bandeja_cm()
        self.modulo.new_ui_table.selectRow(0)
        self.assertTrue(self.modulo.btn_accion_cm_enviar_correo.isEnabled())
        self.assertTrue(self.modulo.btn_accion_cm_confirmar_baja.isEnabled())

    def test_07_enviar_correo_no_modifica_ningun_dato(self):
        """"Confirmar baja" sí modifica datos reales desde esta etapa (ver
        TestConfirmarBajaCM); "Enviar correo" solo abre MailDialog (ver
        TestEnviarCorreoCM), nunca escribe en CasosBajaCM.csv."""
        self._abrir_bandeja_cm()
        self.modulo.new_ui_table.selectRow(0)

        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=[]), \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            mock_mail_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()

        df_releido = leer_casos_baja_cm(self.casos_path)
        pd.testing.assert_frame_equal(
            df_releido.reset_index(drop=True), self._csv_original.reset_index(drop=True)
        )

    def test_08_no_afecta_las_subpestanas_existentes_de_comercial(self):
        self.modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["A"], "VIN": ["V1"], "CHASIS": ["C1"],
            "ESTADO COMERCIAL": ["BAJA"], "ESTADO DE ACTIVACIÓN ACTUAL": ["DESCONECTADO"],
            "TÉRMINO CONTRATO": ["MENSUAL"],
        })
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        self.modulo._on_new_ui_subtab_changed(1)  # "Recuperar clientes": baja desconectada
        self.assertEqual(self.modulo.new_ui_model.get_df()["CHASIS"].tolist(), ["C1"])

        self.modulo._on_new_ui_subtab_changed(2)  # "Nuevas oportunidades": una baja no entra
        self.assertEqual(len(self.modulo.new_ui_model.get_df()), 0)

    def test_09_la_busqueda_global_sigue_funcionando_en_revision_cm(self):
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)

        self.modulo.new_ui_search_input.setText("pendiente")
        self.modulo._refresh_new_ui_data()
        df = self.modulo.new_ui_model.get_df()
        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]['RAZÓN SOCIAL'], 'Empresa Pendiente')

        self.modulo.new_ui_search_input.setText("texto_que_no_existe")
        self.modulo._refresh_new_ui_data()
        self.assertEqual(len(self.modulo.new_ui_model.get_df()), 0)

    def test_10_el_ordenamiento_de_la_tabla_sigue_funcionando_en_revision_cm(self):
        df_casos = leer_casos_baja_cm(self.casos_path)
        segunda_fila = df_casos.iloc[0].copy()
        segunda_fila['CASO_ID'] = '5'
        segunda_fila['VIN'] = 'VIN_PENDIENTE_2'
        segunda_fila['RAZÓN SOCIAL'] = 'Amazonas Ltda'
        segunda_fila['CHASIS'] = 'A9'
        df_casos = pd.concat([df_casos, pd.DataFrame([segunda_fila])], ignore_index=True)
        guardar_casos_baja_cm(df_casos, self.casos_path)

        self._abrir_bandeja_cm()
        self.modulo.new_ui_table._set_sort("CHASIS", Qt.SortOrder.AscendingOrder)
        chasis = self.modulo.new_ui_model.get_df()['CHASIS'].tolist()
        self.assertEqual(chasis, ["A9", "C1"])


class TestEnviarCorreoCM(unittest.TestCase):
    """Cubre la acción rápida "Enviar correo" de "Gestionar CM" (ver
    comercial.py::_on_accion_cm_enviar_correo_clicked): abre MailDialog con
    los VIN seleccionados preseleccionados y la plantilla "Aviso de
    Vencimiento" cuando todos están en Correos.csv, o avisa cuáles VIN
    faltan y ofrece abrir el Gestor de Correos sin preselección cuando no.
    No abre un MailDialog real (evita leer Correos.csv real y bloquear el
    test en un exec() modal): parchea MailDialog y el chequeo de VIN
    faltantes de mail_sync_service."""

    REVISION_CM_INDEX = 3

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()

    def _fila_caso(self, **overrides):
        fila = {c: '' for c in CASOS_BAJA_CM_COLUMNS}
        fila.update(overrides)
        return fila

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.casos_path = os.path.join(self.temp_dir.name, "CasosBajaCM_Test.csv")

        df_casos = pd.DataFrame([
            self._fila_caso(
                CASO_ID='1', VIN='VIN_UNO', CHASIS='C1',
                **{'RAZÓN SOCIAL': 'Empresa Uno', 'ESTADO DEL CM': 'Expired',
                   'ESTADO_CASO': ESTADO_CASO_PENDIENTE}
            ),
            self._fila_caso(
                CASO_ID='2', VIN='VIN_DOS', CHASIS='C2',
                **{'RAZÓN SOCIAL': 'Empresa Dos', 'ESTADO DEL CM': 'Expired',
                   'ESTADO_CASO': ESTADO_CASO_PENDIENTE}
            ),
        ])[CASOS_BAJA_CM_COLUMNS]
        guardar_casos_baja_cm(df_casos, self.casos_path)
        self._csv_original = leer_casos_baja_cm(self.casos_path)

        self._patch_path = patch.object(config.settings, 'CASOS_BAJA_CM_PATH', self.casos_path)
        self._patch_path.start()

        self.modulo = ComercialModule()
        self.modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["X"], "VIN": ["X1"], "CHASIS": ["XC1"],
            "ESTADO COMERCIAL": ["VIGENTE"], "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO"],
            "TÉRMINO CONTRATO": ["MENSUAL"],
        })
        # Oportunidades CM abre primero una fila por flota: se abre el grupo
        # "(Sin dato)" (los casos no traen FLOTA VC) para poder seleccionar unidades.
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        self.modulo._new_ui_grupo_abierto[self.REVISION_CM_INDEX] = self.modulo._NEW_UI_VALOR_SIN_GRUPO
        self.modulo._refresh_new_ui_data()

    def tearDown(self):
        self._patch_path.stop()
        self.temp_dir.cleanup()

    def _seleccionar_filas(self, indices):
        tabla = self.modulo.new_ui_table
        modelo = self.modulo.new_ui_model
        sel_model = tabla.selectionModel()
        sel_model.clearSelection()
        ultima_columna = max(modelo.columnCount() - 1, 0)
        seleccion = QItemSelection()
        for row in indices:
            seleccion.select(modelo.index(row, 0), modelo.index(row, ultima_columna))
        sel_model.select(seleccion, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def test_01_un_vin_presente_abre_mail_dialog_preseleccionado(self):
        self._seleccionar_filas([0])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=[]) as mock_check, \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            mock_mail_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()

        mock_check.assert_called_once_with(['VIN_UNO'], config.settings.CORREOS_EXCEL_PATH)
        mock_mail_dialog.assert_called_once_with(
            parent=self.modulo, vins_preseleccionados=['VIN_UNO'], plantilla_inicial="Aviso de Vencimiento"
        )
        mock_mail_dialog.return_value.exec.assert_called_once()

    def test_02_multiples_vin_presentes_se_entregan_todos(self):
        self._seleccionar_filas([0, 1])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=[]), \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            mock_mail_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()

        mock_mail_dialog.assert_called_once_with(
            parent=self.modulo, vins_preseleccionados=['VIN_UNO', 'VIN_DOS'],
            plantilla_inicial="Aviso de Vencimiento",
        )

    def test_03_vin_faltante_no_abre_mail_dialog_preseleccionado_y_muestra_aviso(self):
        self._seleccionar_filas([0, 1])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=['VIN_DOS']), \
             patch('src.ui.comercial.DialogoAccionCm.exec', return_value=QDialog.DialogCode.Rejected) as mock_exec, \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            self.modulo.btn_accion_cm_enviar_correo.click()

        mock_exec.assert_called_once()
        mock_mail_dialog.assert_not_called()

    def test_04_vin_faltante_y_usuario_acepta_abre_gestor_de_correos_sin_preseleccion(self):
        self._seleccionar_filas([0, 1])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=['VIN_DOS']), \
             patch('src.ui.comercial.DialogoAccionCm.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            mock_mail_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()

        mock_mail_dialog.assert_called_once_with(parent=self.modulo)
        mock_mail_dialog.return_value.exec.assert_called_once()

    def test_05_vin_faltante_no_dispara_sincronizacion_automatica(self):
        """La sincronización (cruzar_correos_maestro / guardar_correos_excel)
        es exclusivamente manual dentro de MailDialog -- Enviar Correo nunca
        debe invocarla, ni cuando faltan VIN ni cuando el usuario cancela."""
        self._seleccionar_filas([0])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=['VIN_UNO']), \
             patch('src.ui.comercial.DialogoAccionCm.exec', return_value=QDialog.DialogCode.Rejected), \
             patch('src.ui.comercial.mail_sync_service.cruzar_correos_maestro') as mock_cruce, \
             patch('src.ui.comercial.mail_sync_service.guardar_correos_excel') as mock_guardar:
            self.modulo.btn_accion_cm_enviar_correo.click()

        mock_cruce.assert_not_called()
        mock_guardar.assert_not_called()

    def test_06_reintento_tras_sincronizar_vuelve_a_comprobar_correos(self):
        """No se guarda estado entre clics: cada clic en Enviar Correo
        vuelve a llamar vins_faltantes_en_correos, así que un segundo
        intento tras sincronizar (ya sin VIN faltantes) sí abre el diálogo
        preseleccionado."""
        self._seleccionar_filas([0])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=['VIN_UNO']), \
             patch('src.ui.comercial.DialogoAccionCm.exec', return_value=QDialog.DialogCode.Rejected), \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            self.modulo.btn_accion_cm_enviar_correo.click()
        mock_mail_dialog.assert_not_called()

        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=[]), \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog_2:
            mock_mail_dialog_2.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()
        mock_mail_dialog_2.assert_called_once_with(
            parent=self.modulo, vins_preseleccionados=['VIN_UNO'], plantilla_inicial="Aviso de Vencimiento"
        )

    def test_07_no_modifica_casosbajacm_ni_prueba_sfm(self):
        casos_antes = leer_casos_baja_cm(self.casos_path)
        df_master_antes = self.modulo.data_manager.df_master.copy()

        self._seleccionar_filas([0])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=[]), \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            mock_mail_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()

        pd.testing.assert_frame_equal(
            leer_casos_baja_cm(self.casos_path).reset_index(drop=True), casos_antes.reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(
            self.modulo.data_manager.df_master.reset_index(drop=True), df_master_antes.reset_index(drop=True)
        )


class TestEnviarCorreoOtrasSubpestanas(unittest.TestCase):
    """Cubre "Enviar correo" generalizado a "Por gestionar"/"Renovaciones"/
    "Gestionar Bajas" (Fase 2, ver comercial.py::
    _on_accion_cm_enviar_correo_clicked y _obtener_vins_seleccionados):
    mismo flujo que en "Gestionar CM" (TestEnviarCorreoCM), pero resolviendo
    la selección contra _new_ui_bandeja_actual_df (subset de df_base) en vez
    de _new_ui_revision_cm_df, con "Conoce Volvo Connect" preseleccionada
    (Nuevas oportunidades, 21-10-2026; antes sin plantilla). No abre un
    MailDialog real: parchea MailDialog y el chequeo de VIN faltantes."""

    POR_GESTIONAR_INDEX = 2  # "Nuevas oportunidades"

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def setUp(self):
        self.modulo = ComercialModule()
        # "Nuevas oportunidades": ESTADO DE ACTIVACIÓN ACTUAL == 'NO APLICA'
        # (ver comercial_services.filtrar_por_gestionar). Agrupa por razón
        # social: ambas unidades son del mismo cliente y se abre ese grupo.
        # VIN no se muestra, pero debe seguir resolviéndose vía
        # _new_ui_bandeja_actual_df.
        self.modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["Empresa Uno", "Empresa Uno"],
            "VIN": ["VIN_UNO", "VIN_DOS"],
            "CHASIS": ["C1", "C2"],
            "FORMA DE CONTRATO": ["X", "X"],
            "ESTADO COMERCIAL": ["VIGENTE", "VIGENTE"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["NO APLICA", "NO APLICA"],
            "TÉRMINO CONTRATO": ["MENSUAL", "MENSUAL"],
        })
        self.modulo._on_new_ui_subtab_changed(self.POR_GESTIONAR_INDEX)
        self.modulo._new_ui_grupo_abierto[self.POR_GESTIONAR_INDEX] = "Empresa Uno"
        self.modulo._refresh_new_ui_data()

    def _seleccionar_filas(self, indices):
        tabla = self.modulo.new_ui_table
        modelo = self.modulo.new_ui_model
        sel_model = tabla.selectionModel()
        sel_model.clearSelection()
        ultima_columna = max(modelo.columnCount() - 1, 0)
        seleccion = QItemSelection()
        for row in indices:
            seleccion.select(modelo.index(row, 0), modelo.index(row, ultima_columna))
        sel_model.select(seleccion, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def test_01_un_vin_abre_mail_dialog_con_conoce_volvo_connect_preseleccionada(self):
        self._seleccionar_filas([0])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=[]) as mock_check, \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            mock_mail_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()

        mock_check.assert_called_once_with(['VIN_UNO'], config.settings.CORREOS_EXCEL_PATH)
        mock_mail_dialog.assert_called_once_with(
            parent=self.modulo, vins_preseleccionados=['VIN_UNO'], plantilla_inicial="Conoce Volvo Connect"
        )
        mock_mail_dialog.return_value.exec.assert_called_once()

    def test_02_multiples_vin_se_entregan_todos_con_su_plantilla(self):
        self._seleccionar_filas([0, 1])
        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=[]), \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            mock_mail_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()

        mock_mail_dialog.assert_called_once_with(
            parent=self.modulo, vins_preseleccionados=['VIN_UNO', 'VIN_DOS'], plantilla_inicial="Conoce Volvo Connect",
        )

    def test_03_gestionar_cm_conserva_su_plantilla_preseleccionada(self):
        """Verifica que generalizar el botón a las otras 3 sub-pestañas no
        haya afectado el comportamiento original de "Gestionar CM" (ver
        también TestEnviarCorreoCM, con fixtures propias más completas para
        el flujo end-to-end). Simula el estado que dejaría _refresh_new_ui_data
        al entrar a "Gestionar CM" (sin depender de CasosBajaCM.csv real):
        no se puede usar patch.object sobre métodos de ComercialModule
        porque su __setattr__ personalizado reenvía cualquier atributo no
        declarado en _OWN_ATTRS hacia self.legacy, y un método de la clase
        no se resuelve por ahí."""
        self.modulo._new_ui_active_subtab = 3  # "Gestionar CM"
        df_cm = pd.DataFrame({"VIN": ["VIN_CM_1"], "RAZÓN SOCIAL": ["Empresa CM"]})
        self.modulo._new_ui_revision_cm_df = df_cm
        self.modulo.new_ui_model.set_data(df_cm[["RAZÓN SOCIAL"]])
        self.modulo.new_ui_table.selectRow(0)

        with patch('src.ui.comercial.mail_sync_service.vins_faltantes_en_correos', return_value=[]), \
             patch('src.ui.comercial.acciones_unidad.MailDialog') as mock_mail_dialog:
            mock_mail_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            self.modulo.btn_accion_cm_enviar_correo.click()

        mock_mail_dialog.assert_called_once_with(
            parent=self.modulo, vins_preseleccionados=['VIN_CM_1'],
            plantilla_inicial="Aviso de Vencimiento",
        )


class _FakeSaveThreadSignal:
    """Reemplazo minimo de pyqtSignal para simular SaveExcelThread sin
    lanzar un QThread real (mismo objetivo que @patch('...SaveExcelThread.
    start') en otros tests, pero acá se necesita además invocar el callback
    de finished_signal de forma sincrona)."""

    def __init__(self):
        self._slot = None

    def connect(self, slot):
        self._slot = slot

    def emit(self, *args):
        if self._slot is not None:
            self._slot(*args)


class _FakeSaveThread:
    def __init__(self, writer, changes, module_name="Sistema"):
        self.writer = writer
        self.changes = changes
        self.module_name = module_name
        self.finished_signal = _FakeSaveThreadSignal()
        # SaveExcelThread real también expone esta señal (ver comercial.py);
        # se agrega acá tal cual, sin emitirla (nunca se llama a
        # writer.leer_logs_actual() en este fake), para que el
        # .connect(...) que hace el código real no reviente con
        # AttributeError al usar este reemplazo en los tests.
        self.logs_actualizados_signal = _FakeSaveThreadSignal()

    def start(self):
        self.finished_signal.emit(True)


class _FakeAddContactoThreadComercial:
    """Mismo rol que _FakeSaveThread (arriba), pero con la firma real de
    AddContactoThread (contactos.py): __init__(writer, new_data) y
    finished_signal(bool, dict). Evita tocar contactos.xlsx real durante
    los tests de "Agregar contacto" en Comercial."""

    def __init__(self, writer, new_data):
        self.writer = writer
        self.new_data = new_data
        self.finished_signal = _FakeSaveThreadSignal()

    def start(self):
        self.finished_signal.emit(True, self.new_data)


class TestEditarUnidadComercial(unittest.TestCase):
    """Cubre "Editar Unidad" en las 4 sub-pestañas de Comercial (ver
    comercial.py::_on_accion_editar_unidad_clicked): reutiliza
    _ComercialModuleLegacy._handle_editar_unidad tal cual.

    Actualizado 25-09-2026 (refactor "Unidad nueva", a pedido explícito):
    "Editar Unidad" ya NO abre ComercialAgregarDialog como ventana modal --
    cambia a la pestaña principal "Unidad nueva" y precarga el mismo
    formulario (ComercialUnidadFormWidget) en modo edición. El guardado
    sigue siendo el mismo SaveExcelThread de siempre (ver
    _ComercialModuleLegacy.guardar_edicion_unidad), sin una segunda
    implementación. Mismo patrón de fixture que TestEnviarCorreoOtrasSubpestanas
    (Fase 2)."""

    POR_GESTIONAR_INDEX = 0

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def setUp(self):
        self.modulo = ComercialModule()
        # Unidades Vigente + Conectado: entran en "Renovar contratos" (índice 0),
        # que sin columna FLOTA VC muestra una fila por unidad.
        self.modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["Empresa Uno", "Empresa Dos"],
            "VIN": ["VIN_UNO", "VIN_DOS"],
            "CHASIS": ["C1", "C2"],
            "CDB": ["CDB_UNO", "CDB_DOS"],
            "FORMA DE CONTRATO": ["X", "X"],
            "ESTADO COMERCIAL": ["VIGENTE", "VIGENTE"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO", "CONECTADO"],
            "TÉRMINO CONTRATO": ["MENSUAL", "MENSUAL"],
        })
        self.modulo._on_new_ui_subtab_changed(self.POR_GESTIONAR_INDEX)

    def _seleccionar_filas(self, indices):
        tabla = self.modulo.new_ui_table
        modelo = self.modulo.new_ui_model
        sel_model = tabla.selectionModel()
        sel_model.clearSelection()
        ultima_columna = max(modelo.columnCount() - 1, 0)
        seleccion = QItemSelection()
        for row in indices:
            seleccion.select(modelo.index(row, 0), modelo.index(row, ultima_columna))
        sel_model.select(seleccion, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def test_01_sin_seleccion_boton_deshabilitado(self):
        self.modulo.new_ui_table.clearSelection()
        self.assertFalse(self.modulo.btn_accion_editar_unidad.isEnabled())

    def test_02_multiples_vin_boton_deshabilitado(self):
        self._seleccionar_filas([0, 1])
        self.assertFalse(self.modulo.btn_accion_editar_unidad.isEnabled())

    def test_03_un_vin_boton_habilitado(self):
        self._seleccionar_filas([0])
        self.assertTrue(self.modulo.btn_accion_editar_unidad.isEnabled())

    def test_04_clic_con_un_vin_muestra_la_pestana_unidad_nueva_en_modo_edicion(self):
        self._seleccionar_filas([0])
        self.modulo.btn_accion_editar_unidad.click()

        self.assertIs(self.modulo.tabs.currentWidget(), self.modulo.unidad_nueva_tab)
        self.assertTrue(self.modulo.unidad_nueva_form.modo_edicion)
        self.assertEqual(self.modulo.unidad_nueva_form.inputs['VIN'].text(), 'VIN_UNO')
        self.assertEqual(self.modulo._unidad_nueva_vin_en_edicion, 'VIN_UNO')

    def test_05_cancelar_no_modifica_datos(self):
        self._seleccionar_filas([0])
        df_master_antes = self.modulo.legacy.data_manager.df_master.copy()
        self.modulo.btn_accion_editar_unidad.click()
        # "Cancelar" del formulario embebido emite formulario_cancelado, que
        # ComercialModule traduce en volver a modo crear -- sin tocar datos.
        self.modulo.unidad_nueva_form._handle_cancelar()

        self.assertIsNone(self.modulo._unidad_nueva_vin_en_edicion)
        pd.testing.assert_frame_equal(
            self.modulo.legacy.data_manager.df_master.reset_index(drop=True),
            df_master_antes.reset_index(drop=True),
        )


class TestAgregarContactoComercial(unittest.TestCase):
    """Cubre "Agregar contacto" en las 4 sub-pestañas de Comercial (ver
    comercial.py::_on_accion_agregar_contacto_clicked/
    _actualizar_estado_acciones_rapidas). Mismo ContactosAddDialog/
    AddContactoThread/contactos_service.generar_nuevo_id_contacto que ya
    usa Clientes y Flotas (general.py), pero CDB/RAZÓN SOCIAL se resuelven
    desde la fila del VIN seleccionado en df_base (_resolver_cdb_razon_social),
    no desde una lista de clientes -- Comercial navega por VIN, no por
    cliente. No usa la AddContactoThread real (evita tocar contactos.xlsx
    real): se reemplaza por _FakeAddContactoThreadComercial, que sí emite
    finished_signal de verdad (a diferencia de un MagicMock crudo, que
    dejaría el botón deshabilitado para el resto de los tests de la clase,
    ver el problema ya encontrado y corregido en TestAgregarContactoCliente
    de test_general.py). Tampoco abre el diálogo real: se parchea
    ContactosAddDialog."""

    POR_GESTIONAR_INDEX = 0

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def setUp(self):
        self.modulo = ComercialModule()
        self.modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["Empresa Uno", "Empresa Dos"],
            "VIN": ["VIN_UNO", "VIN_DOS"],
            "CHASIS": ["C1", "C2"],
            "CDB": ["CDB_UNO", "CDB_DOS"],
            "FORMA DE CONTRATO": ["X", "X"],
            "ESTADO COMERCIAL": ["VIGENTE", "VIGENTE"],
            "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO", "CONECTADO"],
            "TÉRMINO CONTRATO": ["MENSUAL", "MENSUAL"],
        })
        self._df_contactos_original = self.modulo.legacy.data_manager.df_contactos.copy()
        # CDB_UNO tiene contacto (Pedro); CDB_DOS no tiene ninguno.
        self.modulo.legacy.data_manager.df_contactos = pd.DataFrame({
            'ID': [1], 'CDB': ['CDB_UNO'], 'Flota': ['Empresa Uno'],
            'Nombre': ['Pedro'], 'Apellidos': ['Prueba'],
            'Correo electrónico': ['pedro@empresa.cl'], 'Número móvil': ['+56911111111'],
        })
        self.modulo._on_new_ui_subtab_changed(self.POR_GESTIONAR_INDEX)

    def tearDown(self):
        self.modulo.legacy.data_manager.df_contactos = self._df_contactos_original
        # Red de seguridad (mismo motivo que test_general.py.TestAgregarContactoCliente):
        # evita que un thread que no emitió finished_signal deje el botón
        # deshabilitado para el resto de los tests de esta clase.
        self.modulo.btn_accion_agregar_contacto.setEnabled(True)

    def _seleccionar_filas(self, indices):
        tabla = self.modulo.new_ui_table
        modelo = self.modulo.new_ui_model
        sel_model = tabla.selectionModel()
        sel_model.clearSelection()
        ultima_columna = max(modelo.columnCount() - 1, 0)
        seleccion = QItemSelection()
        for row in indices:
            seleccion.select(modelo.index(row, 0), modelo.index(row, ultima_columna))
        sel_model.select(seleccion, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def test_01_sin_seleccion_boton_deshabilitado(self):
        self.modulo.new_ui_table.clearSelection()
        self.assertFalse(self.modulo.btn_accion_agregar_contacto.isEnabled())

    def test_02_multiples_vin_boton_deshabilitado(self):
        self._seleccionar_filas([0, 1])
        self.assertFalse(self.modulo.btn_accion_agregar_contacto.isEnabled())

    def test_03_un_vin_con_cdb_con_contacto_icono_verde(self):
        from src.ui.compartido import comercial_estilo as estilo_com
        self._seleccionar_filas([0])  # VIN_UNO -> CDB_UNO, tiene contacto
        icono = self.modulo.btn_accion_agregar_contacto._icono_frame.styleSheet()
        self.assertEqual(icono, estilo_com.qss_icono_accion(estilo_com.VERDE))

    def test_04_un_vin_con_cdb_sin_contacto_icono_rojo(self):
        from src.ui.compartido import comercial_estilo as estilo_com
        self._seleccionar_filas([1])  # VIN_DOS -> CDB_DOS, sin contacto
        icono = self.modulo.btn_accion_agregar_contacto._icono_frame.styleSheet()
        self.assertEqual(icono, estilo_com.qss_icono_accion(estilo_com.ROJO))

    def test_05_clic_abre_contactosadddialog_con_cdb_y_razon_social_correctos(self):
        self._seleccionar_filas([1])
        with patch('src.ui.comercial.acciones_unidad.ContactosAddDialog') as mock_dialog:
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.modulo.btn_accion_agregar_contacto.click()

        mock_dialog.assert_called_once()
        _, kwargs = mock_dialog.call_args
        self.assertEqual(kwargs.get('cdb_prefill'), 'CDB_DOS')
        self.assertEqual(kwargs.get('flota_prefill'), 'Empresa Dos')

    def test_06_guardar_usa_addcontactothread_con_el_writer_y_el_id_generado(self):
        self._seleccionar_filas([1])
        nuevos_datos = {
            'CDB': 'CDB_DOS', 'Flota': 'Empresa Dos', 'Nombre': 'Ana', 'Apellidos': 'Test',
            'Correo electrónico': 'ana@empresa.cl', 'Número móvil': '+56922222222',
            'Rol': 'Administrador de flota',
        }
        with patch('src.ui.comercial.acciones_unidad.ContactosAddDialog') as mock_dialog, \
             patch('src.ui.comercial.acciones_unidad.AddContactoThread', _FakeAddContactoThreadComercial):
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_dialog.return_value.get_data.return_value = nuevos_datos
            self.modulo.btn_accion_agregar_contacto.click()

        thread_usado = self.modulo._add_contacto_thread_comercial
        self.assertIs(thread_usado.writer, self.modulo.legacy.writer)
        self.assertEqual(thread_usado.new_data['CDB'], 'CDB_DOS')
        self.assertIn('ID', thread_usado.new_data)

    def test_07_correo_existente_en_otra_empresa_no_bloquea_el_guardado(self):
        """Decisión explícita (Fase 4): un mismo correo puede repetirse en
        más de una empresa -- no debe existir ninguna validación que lo
        impida ni que cancele el guardado."""
        self._seleccionar_filas([1])
        nuevos_datos = {
            'CDB': 'CDB_DOS', 'Flota': 'Empresa Dos', 'Nombre': 'Pedro', 'Apellidos': 'Prueba',
            'Correo electrónico': 'pedro@empresa.cl',  # mismo correo que el contacto de CDB_UNO
            'Número móvil': '+56911111111', 'Rol': 'Administrador de flota',
        }
        with patch('src.ui.comercial.acciones_unidad.ContactosAddDialog') as mock_dialog, \
             patch('src.ui.comercial.acciones_unidad.AddContactoThread', _FakeAddContactoThreadComercial):
            mock_dialog.return_value.exec.return_value = QDialog.DialogCode.Accepted
            mock_dialog.return_value.get_data.return_value = nuevos_datos
            self.modulo.btn_accion_agregar_contacto.click()

        thread_usado = self.modulo._add_contacto_thread_comercial
        self.assertEqual(thread_usado.new_data['Correo electrónico'], 'pedro@empresa.cl')


class TestConfirmarBajaCM(unittest.TestCase):
    """Cubre la acción rápida "Confirmar baja" de "Gestionar CM" (ver
    comercial.py::_on_accion_cm_confirmar_baja_clicked): debe aplicar la
    misma regla de negocio que editar ESTADO DEL CM a mano a 'Terminated'
    (ver TestReglaTerminatedCm y
    TestReconciliacionEstadoExpiredAlGuardarEnComercial), pero disparada
    explícitamente desde la bandeja de revisión, sobre TODOS los VIN
    seleccionados a la vez (selección múltiple, ver
    _toggle_acciones_rapidas_panel), marcando cada caso como
    CONFIRMADA_BAJA en vez de esperar a que la reconciliación automática lo
    marque como REAPARECIDO. No usa la SaveExcelThread real (evita tocar el
    Excel real durante el test): la reemplaza por _FakeSaveThread, que
    invoca el callback de éxito de forma síncrona -- mismo patrón que
    @patch('...SaveExcelThread.start') usado en otros tests de este
    archivo, pero necesitando además que el finished_signal se dispare.
    Tampoco muestra el diálogo real (bloquearía el test en un exec() modal):
    parchea DialogoAccionCm.exec para devolver Accepted/Rejected según el
    escenario.

    PruebasFM (mock) solo trae 2 camiones reales -- insuficiente para
    probar selección de 5 VIN con verificación de ESTADO DEL CM/limpieza de
    campos. Por eso setUp agrega VIN sintéticos directamente en
    data_manager.df_master (en memoria, nunca se escriben al Excel real:
    SaveExcelThread está parcheada) junto al único VIN real, para tener 5
    filas de PruebasFM verificables sin depender de cuántos camiones trae
    el mock."""

    REVISION_CM_INDEX = 3

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()
        # Snapshot limpio de df_master ANTES de que ningún test de esta
        # clase le agregue filas sintéticas: DataManager es un singleton
        # compartido por toda la batería, así que cada setUp debe reiniciar
        # df_master desde este snapshot -- si en cambio se agregaran filas
        # sintéticas sobre el df_master ya mutado por el test anterior, se
        # acumularían VIN duplicados entre tests (el mismo VIN_SINTETICO_N
        # repetido, uno ya confirmado por un test previo y otro nuevo), y
        # _fila_master() podría leer el duplicado equivocado.
        cls.df_master_original = cls.dm.df_master.copy()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.casos_path = os.path.join(self.temp_dir.name, "CasosBajaCM_Test.csv")
        self._patch_path = patch.object(config.settings, 'CASOS_BAJA_CM_PATH', self.casos_path)
        self._patch_path.start()

        self.modulo = ComercialModule()
        self.modulo.data_manager.df_master = self.df_master_original.copy()
        df_master = self.modulo.data_manager.df_master
        if df_master.empty:
            self.skipTest("Se omite test por PruebasFM vacío.")
        vin_real = str(df_master.iat[0, df_master.columns.get_loc('VIN')]).strip().upper()

        # 4 VIN sintéticos adicionales (clonados de la primera fila real) +
        # el VIN real = 5 filas de PruebasFM verificables. Se reemplaza
        # df_master completo en cada setUp (no se acumula entre tests: el
        # DataManager es un singleton compartido por toda la batería). Las 5
        # arrancan en ESTADO DEL CM='Expired' (mismo estado que declaran sus
        # casos en CasosBajaCM.csv, ver más abajo) para poder distinguir
        # "cambió a Terminated" de "quedó en su estado original" en los
        # asserts de selección parcial/regresión.
        fila_base = df_master.iloc[0].to_dict()
        fila_base['ESTADO DEL CM'] = 'Expired'
        df_master = df_master.copy()
        df_master.loc[0, 'ESTADO DEL CM'] = 'Expired'
        filas_sinteticas = []
        for i in range(2, 6):
            fila = dict(fila_base)
            fila['VIN'] = f'VIN_SINTETICO_{i}'
            fila['CHASIS'] = f'SINT-{i}'
            fila['RAZÓN SOCIAL'] = f'Empresa Sintetica {i}'
            filas_sinteticas.append(fila)
        self.modulo.data_manager.df_master = pd.concat(
            [df_master, pd.DataFrame(filas_sinteticas)], ignore_index=True
        )

        # self.vins[i] <-> CASO_ID str(10 + i), en el mismo orden en que
        # aparecen en la bandeja (sin sort activo, CasosBajaCM.csv se lee en
        # el orden en que se escribió).
        self.vins = [vin_real] + [f'VIN_SINTETICO_{i}' for i in range(2, 6)]
        self.caso_ids = [str(10 + i) for i in range(len(self.vins))]

        def _fila_caso(**overrides):
            fila = {c: '' for c in CASOS_BAJA_CM_COLUMNS}
            fila.update(overrides)
            return fila

        df_casos = pd.DataFrame([
            _fila_caso(
                CASO_ID=caso_id, VIN=vin, CHASIS=f'C{i}',
                **{'RAZÓN SOCIAL': f'Empresa {i}', 'ESTADO DEL CM': 'Expired',
                   # "Confirmar baja" solo se habilita para casos de Ausencia de 3PC
                   # (el equipo no decide la baja de un contrato Expired, solo avisa)
                   'ESTADO_CASO': ESTADO_CASO_PENDIENTE, 'ORIGEN_CASO': ORIGEN_CASO_AUSENCIA_3PC}
            )
            for i, (vin, caso_id) in enumerate(zip(self.vins, self.caso_ids))
        ])[CASOS_BAJA_CM_COLUMNS]
        guardar_casos_baja_cm(df_casos, self.casos_path)

        # df_base no vacío (cualquier dato basta): la bandeja "Gestionar CM"
        # no sale de df_base, pero _refresh_new_ui_data corta antes si está
        # vacío (ver comercial.py).
        self.modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["X"], "VIN": ["X1"], "CHASIS": ["XC1"],
            "ESTADO COMERCIAL": ["VIGENTE"], "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO"],
            "TÉRMINO CONTRATO": ["MENSUAL"],
        })

        # Oportunidades CM abre primero una fila por flota: se abre el grupo
        # "(Sin dato)" (los casos no traen FLOTA VC) para poder seleccionar unidades.
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        self.modulo._new_ui_grupo_abierto[self.REVISION_CM_INDEX] = self.modulo._NEW_UI_VALOR_SIN_GRUPO
        self.modulo._refresh_new_ui_data()

    def tearDown(self):
        self._patch_path.stop()
        self.temp_dir.cleanup()

    def _seleccionar_filas(self, indices):
        """Selección múltiple real vía QItemSelectionModel (no selectRow(),
        que reemplaza la selección por una sola fila y no ejercita
        ExtendedSelection)."""
        tabla = self.modulo.new_ui_table
        modelo = self.modulo.new_ui_model
        sel_model = tabla.selectionModel()
        sel_model.clearSelection()
        ultima_columna = max(modelo.columnCount() - 1, 0)
        seleccion = QItemSelection()
        for row in indices:
            seleccion.select(modelo.index(row, 0), modelo.index(row, ultima_columna))
        sel_model.select(seleccion, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

    def _confirmar_seleccion(self, indices, aceptar=True):
        self._seleccionar_filas(indices)
        resultado = QDialog.DialogCode.Accepted if aceptar else QDialog.DialogCode.Rejected
        with patch('src.ui.comercial.DialogoAccionCm.exec', return_value=resultado), \
             patch('src.ui.comercial.acciones_unidad.SaveExcelThread', new=_FakeSaveThread):
            self.modulo.btn_accion_cm_confirmar_baja.click()

    def _fila_master(self, vin):
        df_master = self.modulo.data_manager.df_master
        mask = df_master['VIN'].astype(str).str.strip().str.upper() == vin
        return df_master[mask].iloc[0]

    def _caso(self, caso_id):
        df_casos = leer_casos_baja_cm(self.casos_path)
        return df_casos[df_casos['CASO_ID'] == caso_id].iloc[0]

    def test_01_seleccion_de_un_solo_vin_sigue_funcionando_igual(self):
        """Regresión: seleccionar 1 sola fila debe dar exactamente el mismo
        resultado que antes de agregar selección múltiple."""
        self.assertEqual(self.modulo.new_ui_table.selectionMode(), QAbstractItemView.SelectionMode.ExtendedSelection)

        self._confirmar_seleccion([0])

        fila = self._fila_master(self.vins[0])
        self.assertEqual(fila['ESTADO DEL CM'], 'Terminated')
        self.assertEqual(fila['ESTADO COMERCIAL'], 'BAJA')
        for col in ('N CONTRATO 3PC', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'TIPO DE CM', 'PAGO CM'):
            self.assertEqual(fila[col], self.df_master_original.iloc[0][col], f"Fallo: '{col}' debe conservarse.")

        self.assertEqual(self._caso(self.caso_ids[0])['ESTADO_CASO'], ESTADO_CASO_CONFIRMADA_BAJA)

        razones_pendientes = self.modulo.new_ui_model.get_df()['CHASIS'].tolist()
        self.assertNotIn('C0', razones_pendientes,
                          "Fallo: el caso confirmado no debería seguir apareciendo como pendiente en Gestionar CM.")

        # Los otros 4 no seleccionados deben quedar intactos.
        for i in range(1, 5):
            self.assertEqual(self._caso(self.caso_ids[i])['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)
            self.assertEqual(self._fila_master(self.vins[i])['ESTADO DEL CM'], 'Expired')

    def test_02_cinco_vin_seleccionados_confirma_los_cinco(self):
        self._confirmar_seleccion([0, 1, 2, 3, 4])

        for vin, caso_id in zip(self.vins, self.caso_ids):
            fila = self._fila_master(vin)
            self.assertEqual(fila['ESTADO DEL CM'], 'Terminated', f"Fallo: {vin} no quedó Terminated.")
            self.assertEqual(fila['ESTADO COMERCIAL'], 'BAJA', f"Fallo: {vin} no quedó en BAJA.")
            for col in ('N CONTRATO 3PC', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'TIPO DE CM', 'PAGO CM'):
                self.assertEqual(fila[col], self.df_master_original.iloc[0][col], f"Fallo: {vin}.{col} debe conservarse.")
            self.assertEqual(self._caso(caso_id)['ESTADO_CASO'], ESTADO_CASO_CONFIRMADA_BAJA,
                              f"Fallo: caso {caso_id} no quedó CONFIRMADA_BAJA.")

        # Ninguno de los 5 casos confirmados sigue en la bandeja de pendientes.
        razones_pendientes = self.modulo.new_ui_model.get_df()['CHASIS'].tolist()
        self.assertEqual(razones_pendientes, [])

    def test_03_seleccion_parcial_no_afecta_los_no_seleccionados(self):
        """5 casos pendientes, se seleccionan solo 2: solo esos 2 cambian,
        los otros 3 quedan pendientes y sin tocar en PruebasFM."""
        self._confirmar_seleccion([1, 3])

        for i in (1, 3):
            self.assertEqual(self._fila_master(self.vins[i])['ESTADO DEL CM'], 'Terminated')
            self.assertEqual(self._caso(self.caso_ids[i])['ESTADO_CASO'], ESTADO_CASO_CONFIRMADA_BAJA)

        for i in (0, 2, 4):
            self.assertEqual(self._caso(self.caso_ids[i])['ESTADO_CASO'], ESTADO_CASO_PENDIENTE,
                              f"Fallo: el caso {self.caso_ids[i]} no debía modificarse.")
            self.assertEqual(self._fila_master(self.vins[i])['ESTADO DEL CM'], 'Expired',
                              f"Fallo: PruebasFM de {self.vins[i]} no debía modificarse.")

        razones_pendientes = self.modulo.new_ui_model.get_df()['CHASIS'].tolist()
        self.assertEqual(sorted(razones_pendientes), ['C0', 'C2', 'C4'])

    def test_04_cancelar_no_modifica_nada(self):
        casos_antes = leer_casos_baja_cm(self.casos_path)
        df_master_antes = self.modulo.data_manager.df_master.copy()

        self._confirmar_seleccion([0, 1, 2], aceptar=False)

        pd.testing.assert_frame_equal(
            leer_casos_baja_cm(self.casos_path).reset_index(drop=True), casos_antes.reset_index(drop=True)
        )
        pd.testing.assert_frame_equal(
            self.modulo.data_manager.df_master.reset_index(drop=True), df_master_antes.reset_index(drop=True)
        )

    def test_05_dialogo_de_confirmacion_recibe_todos_los_vin_seleccionados(self):
        """Verifica que el diálogo realmente se construye con los 3 VIN
        seleccionados (no solo el primero), capturando la instancia real
        que arma _on_accion_cm_confirmar_baja_clicked antes de parchear
        exec()."""
        instancias = []
        original_init = DialogoAccionCm.__init__

        def _init_espia(self_dialogo, *args, **kwargs):
            original_init(self_dialogo, *args, **kwargs)
            instancias.append(self_dialogo)

        self._seleccionar_filas([0, 1, 2])
        with patch.object(DialogoAccionCm, '__init__', _init_espia), \
             patch('src.ui.comercial.DialogoAccionCm.exec', return_value=QDialog.DialogCode.Rejected), \
             patch('src.ui.comercial.acciones_unidad.SaveExcelThread', new=_FakeSaveThread):
            self.modulo.btn_accion_cm_confirmar_baja.click()

        self.assertEqual(len(instancias), 1, "Fallo: debía construirse un único diálogo de confirmación.")
        dialogo = instancias[0]
        self.assertIsNotNone(dialogo.lista_items)
        self.assertEqual(dialogo.lista_items.count(), 3)
        vins_en_lista = [dialogo.lista_items.item(i).text() for i in range(dialogo.lista_items.count())]
        self.assertEqual(vins_en_lista, self.vins[:3])


class TestDialogoAccionCm(unittest.TestCase):
    """Cubre el componente visual DialogoAccionCm (reemplazo de los
    QMessageBox usados antes por "Confirmar baja" de Gestionar CM): una
    sola clase reutilizada por los 3 estados (confirmación/éxito/error) vía
    sus classmethods, sin exec() real (evita bloquear el test en un diálogo
    modal): se valida el contrato accept()/reject() -> result() en su
    lugar, que es lo mismo que exec() usa internamente."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _boton(self, dialogo, texto):
        return next(b for b in dialogo.findChildren(QPushButton) if b.text() == texto)

    def test_confirmacion_muestra_la_cantidad_de_vin(self):
        vins = ['VIN1', 'VIN2', 'VIN3', 'VIN4']
        dialogo = DialogoAccionCm.confirmacion(None, vins)
        textos = [lbl.text() for lbl in dialogo.findChildren(QLabel)]
        self.assertTrue(any('4' in t and 'vehículos' in t for t in textos),
                         f"Fallo: no se encontró la cantidad '4 vehículos' en los labels: {textos}")

    def test_confirmacion_lista_todos_los_vin_seleccionados(self):
        vins = ['VIN1', 'VIN2', 'VIN3']
        dialogo = DialogoAccionCm.confirmacion(None, vins)
        self.assertEqual(dialogo.lista_items.count(), 3)
        textos = [dialogo.lista_items.item(i).text() for i in range(dialogo.lista_items.count())]
        self.assertEqual(textos, vins)

    def test_confirmacion_boton_confirmar_acepta(self):
        dialogo = DialogoAccionCm.confirmacion(None, ['VIN1'])
        self._boton(dialogo, 'Confirmar baja').click()
        self.assertEqual(dialogo.result(), QDialog.DialogCode.Accepted)

    def test_confirmacion_boton_cancelar_rechaza(self):
        dialogo = DialogoAccionCm.confirmacion(None, ['VIN1'])
        self._boton(dialogo, 'Cancelar').click()
        self.assertEqual(dialogo.result(), QDialog.DialogCode.Rejected)

    def test_exito_no_muestra_lista_de_vin(self):
        dialogo = DialogoAccionCm.exito(None, 5)
        self.assertIsNone(dialogo.lista_items)

    def test_exito_muestra_la_cantidad_procesada(self):
        dialogo = DialogoAccionCm.exito(None, 5)
        textos = [lbl.text() for lbl in dialogo.findChildren(QLabel)]
        self.assertTrue(any('5' in t for t in textos), f"Fallo: no se encontró la cantidad en los labels: {textos}")

    def test_exito_boton_aceptar_acepta(self):
        dialogo = DialogoAccionCm.exito(None, 1)
        self._boton(dialogo, 'Aceptar').click()
        self.assertEqual(dialogo.result(), QDialog.DialogCode.Accepted)

    def test_error_muestra_el_mensaje_real(self):
        mensaje = "SharePoint está bloqueando el archivo de prueba."
        dialogo = DialogoAccionCm.error(None, mensaje)
        textos = [lbl.text() for lbl in dialogo.findChildren(QLabel)]
        self.assertTrue(any(mensaje in t for t in textos), f"Fallo: no se encontró el mensaje real en los labels: {textos}")

    def test_error_boton_aceptar_acepta(self):
        dialogo = DialogoAccionCm.error(None, "boom")
        self._boton(dialogo, 'Aceptar').click()
        self.assertEqual(dialogo.result(), QDialog.DialogCode.Accepted)


class TestConfirmarBajaCmFlujoRealDeGuardado(unittest.TestCase):
    """Prueba el flujo COMPLETO de "Confirmar baja" con el ExcelWriter REAL,
    no con _FakeSaveThread: Gestionar CM (clic) -> SaveExcelThread (real,
    ejecutado sincrónicamente) -> ExcelWriter.update_cells() (real, contra
    un PruebasFM.xlsx temporal) -> LogApp.csv (real, temporal) ->
    CasosBajaCM.csv (real, temporal).

    Nace directamente del bug encontrado: TestConfirmarBajaCM (más arriba)
    reemplaza SaveExcelThread por _FakeSaveThread, que nunca invoca
    ExcelWriter.update_cells() de verdad -- por eso los 742 tests pasaban
    aunque `valid[vin]` no tuviera la clave 'VIN' y el guardado real fallara
    siempre. Esta clase existe para que un bug así no vuelva a pasar
    inadvertido: aquí si se ejercita el ExcelWriter real.

    SaveExcelThread.start() se parchea para llamar a self.run() en el mismo
    hilo (sin QThread real) -- evita la complejidad de sincronizar con un
    QEventLoop en el test, pero el código que corre en start()/run() es el
    real y sin mocks: mismo self.writer.update_cells(...) que en producción."""

    REVISION_CM_INDEX = 3

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

        cls.dm = DataManager()
        cls.loop = QEventLoop()
        cls.dm.data_ready.connect(cls.loop.quit)
        cls.dm.load_error.connect(cls.loop.quit)
        cls.dm.load_data_async()
        cls.loop.exec()
        cls.df_master_original = cls.dm.df_master.copy()
        cls.df_logs_original = cls.dm.df_logs.copy()

    COLUMNAS_EXCEL = ['VIN', 'ESTADO DEL CM', 'ESTADO COMERCIAL', 'ETAPA GESTIÓN',
                      'N CONTRATO 3PC', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'TIPO DE CM', 'PAGO CM']

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.casos_path = os.path.join(self.temp_dir.name, "CasosBajaCM_Test.csv")
        self.excel_path = os.path.join(self.temp_dir.name, "PruebasFM_Test.xlsx")
        self._patch_path = patch.object(config.settings, 'CASOS_BAJA_CM_PATH', self.casos_path)
        self._patch_path.start()

        if self.df_master_original.empty:
            self.skipTest("Se omite test por PruebasFM vacío.")

        # Reset ANTES de construir ComercialModule(): DataManager es un
        # singleton compartido por toda la batería, y _ComercialModuleLegacy
        # lee data_manager.df_master de inmediato en su propio __init__
        # (load_data() -> calcular_kpis_vigencia()) para armar sus KPI. Si un
        # test anterior (de esta clase o de otra) dejó df_master con un
        # DataFrame sintético incompleto (sin 'TÉRMINO CONTRATO', etc.), la
        # sola construcción de ComercialModule() revienta antes de llegar al
        # cuerpo del test.
        self.dm.df_master = self.df_master_original.copy()

        self.modulo = ComercialModule()
        # ExcelWriter REAL, pero apuntando a archivos temporales (nunca al
        # PruebasFM.xlsx/LogApp.csv reales) y sin backup real (mismo patron
        # que TestExcelWriter: @patch de _crear_backup en cada test, ver abajo).
        self.modulo.legacy.writer.filepath = self.excel_path
        self.modulo.legacy.writer.log_filepath = ""
        self.modulo.legacy.writer.log_csv_filepath = os.path.join(self.temp_dir.name, "LogApp_Test.csv")

        self.modulo.legacy.df_base = pd.DataFrame({
            "RAZÓN SOCIAL": ["X"], "VIN": ["X1"], "CHASIS": ["XC1"],
            "ESTADO COMERCIAL": ["VIGENTE"], "ESTADO DE ACTIVACIÓN ACTUAL": ["CONECTADO"],
            "TÉRMINO CONTRATO": ["MENSUAL"],
        })

    def tearDown(self):
        self._patch_path.stop()
        self.temp_dir.cleanup()
        # No dejar en el singleton un df_master/df_logs sintético para la
        # siguiente clase de test que se ejecute en la misma batería. df_logs
        # también queda "sucio" ahora que SaveExcelThread.logs_actualizados_signal
        # está conectada a set_logs_df() en confirm_save/_handle_editar_unidad/
        # _on_accion_cm_confirmar_baja_clicked.
        self.dm.df_master = self.df_master_original.copy()
        self.dm.df_logs = self.df_logs_original.copy()

    def _fila_master_sintetica(self, vin, estado_del_cm='Expired'):
        """Clona una fila real completa (todas las columnas de PruebasFM,
        no solo VIN/ESTADO DEL CM) para no romper calcular_kpis_vigencia()
        u otro codigo que dependa de columnas como 'TÉRMINO CONTRATO' al
        reconstruir un ComercialModule() en el siguiente test."""
        fila = self.df_master_original.iloc[0].to_dict()
        fila['VIN'] = vin
        fila['ESTADO DEL CM'] = estado_del_cm
        return fila

    def _crear_excel_pruebas_fm(self, filas):
        """filas: lista de dicts {columna: valor} usando self.COLUMNAS_EXCEL."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(self.COLUMNAS_EXCEL)
        for fila in filas:
            ws.append([fila.get(c, '') for c in self.COLUMNAS_EXCEL])
        wb.save(self.excel_path)
        wb.close()

    def _crear_casos_pendientes(self, vins_y_ids):
        def _fila_caso(**overrides):
            fila = {c: '' for c in CASOS_BAJA_CM_COLUMNS}
            fila.update(overrides)
            return fila

        df_casos = pd.DataFrame([
            _fila_caso(
                CASO_ID=caso_id, VIN=vin, CHASIS=f'C{i}',
                **{'RAZÓN SOCIAL': f'Empresa {i}', 'ESTADO DEL CM': 'Expired',
                   'ESTADO_CASO': ESTADO_CASO_PENDIENTE, 'ORIGEN_CASO': ORIGEN_CASO_AUSENCIA_3PC}
            )
            for i, (vin, caso_id) in enumerate(vins_y_ids)
        ])[CASOS_BAJA_CM_COLUMNS]
        guardar_casos_baja_cm(df_casos, self.casos_path)

    def _leer_celda_excel(self, vin, columna):
        wb = openpyxl.load_workbook(self.excel_path)
        ws = wb.active
        idx_vin = self.COLUMNAS_EXCEL.index('VIN')
        idx_col = self.COLUMNAS_EXCEL.index(columna)
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[idx_vin] == vin:
                wb.close()
                return row[idx_col]
        wb.close()
        self.fail(f"VIN {vin} no encontrado en el Excel temporal.")

    def _leer_log(self):
        path = self.modulo.legacy.writer.log_csv_filepath
        if not os.path.exists(path):
            return pd.DataFrame(columns=["FECHA Y HORA", "MÓDULO", "IDENTIFICADOR", "CAMPO MODIFICADO", "VALOR ANTERIOR", "NUEVO VALOR"])
        return pd.read_csv(path, dtype=str, encoding='utf-8-sig')

    def _abrir_bandeja_cm(self):
        """Oportunidades CM abre primero una fila por flota: abre el grupo
        "(Sin dato)" (los casos no traen FLOTA VC) para ver y seleccionar unidades."""
        self.modulo._on_new_ui_subtab_changed(self.REVISION_CM_INDEX)
        self.modulo._new_ui_grupo_abierto[self.REVISION_CM_INDEX] = self.modulo._NEW_UI_VALOR_SIN_GRUPO
        self.modulo._refresh_new_ui_data()

    def _seleccionar_y_confirmar(self, indices):
        tabla = self.modulo.new_ui_table
        modelo = self.modulo.new_ui_model
        sel_model = tabla.selectionModel()
        sel_model.clearSelection()
        ultima_columna = max(modelo.columnCount() - 1, 0)
        seleccion = QItemSelection()
        for row in indices:
            seleccion.select(modelo.index(row, 0), modelo.index(row, ultima_columna))
        sel_model.select(seleccion, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

        with patch('src.ui.comercial.DialogoAccionCm.exec', return_value=QDialog.DialogCode.Accepted), \
             patch.object(SaveExcelThread, 'start', new=lambda self_thread: self_thread.run()), \
             patch('src.core.excel_writer.ExcelWriter._crear_backup'):
            self.modulo.btn_accion_cm_confirmar_baja.click()

    @patch('src.ui.comercial.QMessageBox.information')  # no interviene, pero por si acaso
    def test_un_vin_flujo_real_completo(self, _mock_info):
        vin = 'YV2REAL0000000001'
        self._crear_excel_pruebas_fm([
            {'VIN': vin, 'ESTADO DEL CM': 'Expired', 'ESTADO COMERCIAL': 'Vigente', 'ETAPA GESTIÓN': 'PENDIENTE_TEST',
             'N CONTRATO 3PC': '3PC-1', 'FECHA INICIO CM': '01-01-2025', 'FECHA TERMINO CM': '01-01-2026',
             'TIPO DE CM': 'Silver', 'PAGO CM': '15000'},
        ])
        self._crear_casos_pendientes([(vin, '10')])

        # data_manager.df_master necesita esta fila para que
        # aplicar_cambios_pendientes / _fila_master tengan algo que verificar
        # en memoria (independiente del Excel real, pero con el mismo VIN).
        self.modulo.data_manager.df_master = pd.DataFrame([self._fila_master_sintetica(vin)])

        self._abrir_bandeja_cm()
        self._seleccionar_y_confirmar([0])

        # 1) PruebasFM.xlsx (temporal, real): Expired -> Terminated, contrato en BAJA y datos del CM intactos.
        self.assertEqual(self._leer_celda_excel(vin, 'ESTADO DEL CM'), 'Terminated')
        self.assertEqual(self._leer_celda_excel(vin, 'ESTADO COMERCIAL'), 'BAJA')
        self.assertEqual(self._leer_celda_excel(vin, 'N CONTRATO 3PC'), '3PC-1')
        self.assertEqual(self._leer_celda_excel(vin, 'TIPO DE CM'), 'Silver')
        self.assertEqual(self._leer_celda_excel(vin, 'PAGO CM'), '15000')

        # 2) LogApp.csv (temporal, real): una línea por columna que cambió.
        df_log = self._leer_log()
        self.assertEqual(len(df_log), 3, "Fallo: deben quedar 3 líneas de log (ESTADO DEL CM, ESTADO COMERCIAL y ETAPA GESTIÓN).")
        fila_estado = df_log[df_log['CAMPO MODIFICADO'] == 'ESTADO DEL CM'].iloc[0]
        self.assertEqual(fila_estado['IDENTIFICADOR'], vin)
        self.assertEqual(fila_estado['MÓDULO'], 'Comercial')
        self.assertEqual(fila_estado['VALOR ANTERIOR'], 'Expired')
        self.assertEqual(fila_estado['NUEVO VALOR'], 'Terminated')

        # 3) CasosBajaCM.csv (temporal, real): CASO_ID -> CONFIRMADA_BAJA.
        df_casos = leer_casos_baja_cm(self.casos_path)
        self.assertEqual(df_casos[df_casos['CASO_ID'] == '10'].iloc[0]['ESTADO_CASO'], ESTADO_CASO_CONFIRMADA_BAJA)

    @patch('src.ui.comercial.QMessageBox.information')
    def test_multiples_vin_flujo_real_una_sola_escritura(self, _mock_info):
        vins = ['YV2REAL0000000002', 'YV2REAL0000000003', 'YV2REAL0000000004']
        vin_no_seleccionado = 'YV2REAL0000000005'
        filas_excel = [
            {'VIN': v, 'ESTADO DEL CM': 'Expired', 'ESTADO COMERCIAL': 'Vigente', 'ETAPA GESTIÓN': 'PENDIENTE_TEST',
             'N CONTRATO 3PC': f'3PC-{i}', 'FECHA INICIO CM': '01-01-2025', 'FECHA TERMINO CM': '01-01-2026',
             'TIPO DE CM': 'Silver', 'PAGO CM': str(10000 * (i + 1))}
            for i, v in enumerate(vins + [vin_no_seleccionado])
        ]
        self._crear_excel_pruebas_fm(filas_excel)
        caso_ids = ['20', '21', '22', '29']
        self._crear_casos_pendientes(list(zip(vins + [vin_no_seleccionado], caso_ids)))

        filas_master = [self._fila_master_sintetica(v) for v in vins + [vin_no_seleccionado]]
        self.modulo.data_manager.df_master = pd.DataFrame(filas_master)

        self._abrir_bandeja_cm()

        # Espía sobre SaveExcelThread para probar que es UNA sola instancia
        # (una sola escritura por lote), no una por VIN.
        instancias_thread = []
        thread_original_init = SaveExcelThread.__init__

        def _init_espia(self_thread, *args, **kwargs):
            thread_original_init(self_thread, *args, **kwargs)
            instancias_thread.append(self_thread)

        with patch.object(SaveExcelThread, '__init__', _init_espia):
            self._seleccionar_y_confirmar([0, 1, 2])  # los 3 primeros; vin_no_seleccionado queda fuera

        self.assertEqual(len(instancias_thread), 1, "Fallo: debe ser una sola SaveExcelThread para todo el lote.")
        self.assertEqual(set(instancias_thread[0].changes.keys()), set(vins),
                          "Fallo: el lote de la única SaveExcelThread debe traer los 3 VIN seleccionados.")

        # 1) PruebasFM.xlsx real: los 3 seleccionados cambian.
        for vin in vins:
            self.assertEqual(self._leer_celda_excel(vin, 'ESTADO DEL CM'), 'Terminated')
            self.assertEqual(self._leer_celda_excel(vin, 'ESTADO COMERCIAL'), 'BAJA')
            self.assertNotEqual(self._leer_celda_excel(vin, 'N CONTRATO 3PC'), '-')

        # El VIN no seleccionado permanece intacto en el Excel real.
        self.assertEqual(self._leer_celda_excel(vin_no_seleccionado, 'ESTADO DEL CM'), 'Expired')
        self.assertEqual(self._leer_celda_excel(vin_no_seleccionado, 'ESTADO COMERCIAL'), 'Vigente')
        self.assertEqual(self._leer_celda_excel(vin_no_seleccionado, 'PAGO CM'), str(10000 * 4))

        # 2) LogApp.csv real: 3 líneas por cada VIN seleccionado, ninguna del no seleccionado.
        df_log = self._leer_log()
        self.assertEqual(len(df_log), 9, "Fallo: 3 VIN x 3 columnas = 9 líneas de log.")
        for vin in vins:
            self.assertEqual(len(df_log[df_log['IDENTIFICADOR'] == vin]), 3)
        self.assertNotIn(vin_no_seleccionado, df_log['IDENTIFICADOR'].tolist())

        # 3) CasosBajaCM.csv real: los 3 seleccionados a CONFIRMADA_BAJA, el resto pendiente.
        df_casos = leer_casos_baja_cm(self.casos_path)
        for caso_id in caso_ids[:3]:
            self.assertEqual(df_casos[df_casos['CASO_ID'] == caso_id].iloc[0]['ESTADO_CASO'], ESTADO_CASO_CONFIRMADA_BAJA)
        self.assertEqual(df_casos[df_casos['CASO_ID'] == '29'].iloc[0]['ESTADO_CASO'], ESTADO_CASO_PENDIENTE)


class TestSaveExcelThreadLogsActualizadosSignal(unittest.TestCase):
    """Causa raiz del historial desactualizado hasta presionar "Recargar"
    (15-09-2026): _on_save_finished (y equivalentes) inyectaban df_master en
    RAM y emitian data_ready, pero nunca releian LogApp.csv ni actualizaban
    DataManager.df_logs -- Historial (historial.py y el historial por VIN de
    general.py) seguian leyendo el df_logs viejo hasta un load_data_async()
    completo. Esta clase prueba que SaveExcelThread ahora relee LogApp.csv
    en su propio hilo (via ExcelWriter.leer_logs_actual) y emite
    logs_actualizados_signal con el resultado -- listo para conectarse a
    DataManager.set_logs_df(), como ya hacen confirm_save/_handle_editar_
    unidad/_on_accion_cm_confirmar_baja_clicked en comercial.py."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.excel_path = os.path.join(self.temp_dir.name, "PruebasFM_signal_test.xlsx")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["VIN", "MODELO"])
        ws.append(["YV2SIGNAL001", "FM"])
        wb.save(self.excel_path)
        wb.close()

        self.writer = ExcelWriter()
        self.writer.filepath = self.excel_path
        self.writer.log_csv_filepath = os.path.join(self.temp_dir.name, "LogApp_signal_test.csv")
        self._patch_backup = patch.object(ExcelWriter, '_crear_backup', return_value=True)
        self._patch_backup.start()

    def tearDown(self):
        self._patch_backup.stop()
        self.temp_dir.cleanup()

    def test_guardado_exitoso_emite_logs_actualizados_con_el_cambio_nuevo(self):
        cambios = {"YV2SIGNAL001": {"VIN": "YV2SIGNAL001", "cambios": {"MODELO": "FH"}}}
        thread = SaveExcelThread(self.writer, cambios, module_name="Comercial")

        recibidos = []
        thread.logs_actualizados_signal.connect(lambda df: recibidos.append(df))
        thread.run()  # sincronico: sin start(), no hace falta un QThread real

        self.assertEqual(len(recibidos), 1, "Fallo: logs_actualizados_signal debe emitirse una vez tras un guardado exitoso.")
        df_logs = recibidos[0]
        self.assertEqual(len(df_logs), 1)
        self.assertEqual(df_logs.iloc[0]["IDENTIFICADOR"], "YV2SIGNAL001")
        self.assertEqual(df_logs.iloc[0]["VALOR ANTERIOR"], "FM")
        self.assertEqual(df_logs.iloc[0]["NUEVO VALOR"], "FH")

    def test_guardado_fallido_no_emite_logs_actualizados(self):
        cambios = {"VIN_INEXISTENTE": {"VIN": "VIN_INEXISTENTE", "cambios": {"MODELO": "FH"}}}
        thread = SaveExcelThread(self.writer, cambios, module_name="Comercial")

        recibidos = []
        thread.logs_actualizados_signal.connect(lambda df: recibidos.append(df))
        thread.run()

        self.assertEqual(recibidos, [], "Fallo: no debe emitirse logs_actualizados_signal si el guardado no tuvo exito.")

    def test_dos_guardados_sucesivos_emiten_el_historial_acumulado(self):
        """Simula el paso 12-14 del caso de prueba concreto: modificar el
        mismo VIN una segunda vez debe reflejar AMBOS cambios en la segunda
        emision, no solo el ultimo."""
        cambios1 = {"YV2SIGNAL001": {"VIN": "YV2SIGNAL001", "cambios": {"MODELO": "FH"}}}
        SaveExcelThread(self.writer, cambios1, module_name="Comercial").run()

        cambios2 = {"YV2SIGNAL001": {"VIN": "YV2SIGNAL001", "cambios": {"MODELO": "FM"}}}
        thread2 = SaveExcelThread(self.writer, cambios2, module_name="Comercial")
        recibidos = []
        thread2.logs_actualizados_signal.connect(lambda df: recibidos.append(df))
        thread2.run()

        self.assertEqual(len(recibidos), 1)
        self.assertEqual(len(recibidos[0]), 2, "Fallo: la segunda relectura debe traer los 2 eventos acumulados en LogApp.csv.")


class TestSetLogsDfIntegracionConGeneralModule(unittest.TestCase):
    """Extremo a extremo (sin QThread real, sin UI de Comercial): confirma
    que DataManager.set_logs_df -- el mismo mecanismo que ahora dispara
    SaveExcelThread.logs_actualizados_signal -- efectivamente deja
    get_logs_df() con el cambio nuevo disponible de inmediato, que es lo
    unico que historial.py y el historial por VIN de general.py necesitan
    para refrescarse solos (ver DataManager.logs_updated)."""

    def setUp(self):
        # DataManager es un singleton compartido por toda la bateria: se
        # respalda y restaura df_logs para no dejar el DataFrame sintetico
        # de este test puesto para clases que corran despues.
        self.dm = DataManager()
        self._df_logs_original = self.dm.df_logs.copy()

    def tearDown(self):
        self.dm.df_logs = self._df_logs_original

    def test_set_logs_df_actualiza_get_logs_df_y_emite_logs_updated(self):
        dm = self.dm
        df_nuevo = pd.DataFrame({
            "FECHA Y HORA": ["2026-09-15 10:00:00"], "MÓDULO": ["Comercial"],
            "IDENTIFICADOR": ["YV2SIGNAL001"], "CAMPO MODIFICADO": ["MODELO"],
            "VALOR ANTERIOR": ["FM"], "NUEVO VALOR": ["FH"],
        })

        señal_emitida = []
        dm.logs_updated.connect(lambda: señal_emitida.append(True))
        dm.set_logs_df(df_nuevo)

        self.assertTrue(señal_emitida, "Fallo: set_logs_df debe emitir logs_updated.")
        pd.testing.assert_frame_equal(dm.get_logs_df().reset_index(drop=True), df_nuevo.reset_index(drop=True))