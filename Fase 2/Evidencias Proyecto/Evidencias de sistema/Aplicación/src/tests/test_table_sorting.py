import unittest
import logging
from datetime import datetime, timedelta
import pandas as pd
from unittest.mock import patch
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QMenu

import config.settings
from src.ui.custom_table import VolvoTableWidget, PandasTableModel
from src.services import comercial_services
from src.theme.colors import SUCCESS, DANGER, WARNING, TEXT_MUTED

logger = logging.getLogger("TestRunner")


class TestVolvoTableWidgetSorting(unittest.TestCase):
    """Pruebas puras (sin Excel/DataManager) del ordenamiento tipo Excel
    agregado a VolvoTableWidget: apply_sort() y el ciclo asc -> desc ->
    orden original disparado por clic de encabezado."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_table(self, df):
        table = VolvoTableWidget()
        model = PandasTableModel()
        model.set_data(df)
        table.setModel(model)
        return table

    def test_ordenamiento_ascendente_texto(self):
        df = pd.DataFrame({'Nombre': ['Carlos', 'ana', 'Beto']})
        table = self._make_table(df)
        table._sort_column, table._sort_order = 'Nombre', Qt.SortOrder.AscendingOrder

        resultado = table.apply_sort(df)
        self.assertEqual(list(resultado['Nombre']), ['ana', 'Beto', 'Carlos'])

    def test_ordenamiento_descendente_texto(self):
        df = pd.DataFrame({'Nombre': ['Carlos', 'ana', 'Beto']})
        table = self._make_table(df)
        table._sort_column, table._sort_order = 'Nombre', Qt.SortOrder.DescendingOrder

        resultado = table.apply_sort(df)
        self.assertEqual(list(resultado['Nombre']), ['Carlos', 'Beto', 'ana'])

    def test_ordenamiento_numerico_con_formato_dinero_chileno(self):
        # '$1.234' = 1234, '$-' = 0 (no ausente), '-$500' = -500
        df = pd.DataFrame({'Monto': ['$1.234', '$-', '-$500']})
        table = self._make_table(df)
        table._sort_column, table._sort_order = 'Monto', Qt.SortOrder.AscendingOrder

        resultado = table.apply_sort(df)
        self.assertEqual(list(resultado['Monto']), ['-$500', '$-', '$1.234'])

    def test_ordenamiento_fechas_dd_mm_yyyy(self):
        df = pd.DataFrame({'Fecha': ['15-08-2026', '01-01-2026', '20-12-2025']})
        table = self._make_table(df)
        table._sort_column, table._sort_order = 'Fecha', Qt.SortOrder.AscendingOrder

        resultado = table.apply_sort(df)
        self.assertEqual(list(resultado['Fecha']), ['20-12-2025', '01-01-2026', '15-08-2026'])

    def test_valores_vacios_van_siempre_al_final(self):
        df = pd.DataFrame({'Duracion': ['12', '-', '3']})
        table = self._make_table(df)

        table._sort_column, table._sort_order = 'Duracion', Qt.SortOrder.AscendingOrder
        asc = table.apply_sort(df)
        self.assertEqual(list(asc['Duracion']), ['3', '12', '-'])

        table._sort_order = Qt.SortOrder.DescendingOrder
        desc = table.apply_sort(df)
        self.assertEqual(list(desc['Duracion']), ['12', '3', '-'])

    def test_sin_ordenamiento_activo_devuelve_orden_original(self):
        df = pd.DataFrame({'Nombre': ['Carlos', 'ana', 'Beto']})
        table = self._make_table(df)
        # Estado inicial: sin ordenamiento
        self.assertIsNone(table._sort_column)

        resultado = table.apply_sort(df)
        self.assertEqual(list(resultado['Nombre']), ['Carlos', 'ana', 'Beto'])

    def test_columna_ordenada_ya_no_existe_no_lanza_error(self):
        df_original = pd.DataFrame({'Nombre': ['Carlos', 'ana', 'Beto']})
        table = self._make_table(df_original)
        table._sort_column, table._sort_order = 'ColumnaQueYaNoExiste', Qt.SortOrder.AscendingOrder

        df_nuevo = pd.DataFrame({'Otro': [1, 2, 3]})
        try:
            resultado = table.apply_sort(df_nuevo)
        except Exception as e:
            self.fail(f"apply_sort no debe lanzar excepción si la columna no existe: {e}")
        self.assertEqual(list(resultado['Otro']), [1, 2, 3])

    def test_set_sort_asc_desc_y_clear_sort_vuelve_al_original(self):
        """El ordenamiento ya no se dispara por clic izquierdo en el
        encabezado (desactivado a propósito, ver custom_table.py) sino por
        el menú contextual (clic derecho -> 'Ordenar A → Z'/'Ordenar Z → A'),
        que internamente llama a _set_sort()/_clear_sort()."""
        df = pd.DataFrame({'Nombre': ['Carlos', 'ana', 'Beto']})
        table = self._make_table(df)

        cambios = {'n': 0}
        table.sort_changed.connect(lambda: cambios.__setitem__('n', cambios['n'] + 1))

        # 'Ordenar A → Z' en el menú contextual de la columna 'Nombre'
        table._set_sort('Nombre', Qt.SortOrder.AscendingOrder)
        self.assertEqual(table._sort_column, 'Nombre')
        self.assertEqual(table._sort_order, Qt.SortOrder.AscendingOrder)

        # 'Ordenar Z → A' en la misma columna
        table._set_sort('Nombre', Qt.SortOrder.DescendingOrder)
        self.assertEqual(table._sort_column, 'Nombre')
        self.assertEqual(table._sort_order, Qt.SortOrder.DescendingOrder)

        # _clear_sort() vuelve al orden original (sin columna activa)
        table._clear_sort()
        self.assertIsNone(table._sort_column)
        self.assertIsNone(table._sort_order)

        self.assertEqual(cambios['n'], 3, "sort_changed debe emitirse en cada uno de los 3 cambios")

    def test_elegir_otra_columna_en_el_menu_reemplaza_el_orden_activo(self):
        df = pd.DataFrame({'Nombre': ['Carlos', 'ana'], 'Empresa': ['X', 'Y']})
        table = self._make_table(df)

        table._set_sort('Nombre', Qt.SortOrder.AscendingOrder)
        table._set_sort('Nombre', Qt.SortOrder.DescendingOrder)
        table._set_sort('Empresa', Qt.SortOrder.AscendingOrder)  # elegido desde el menú de otra columna

        self.assertEqual(table._sort_column, 'Empresa')
        self.assertEqual(table._sort_order, Qt.SortOrder.AscendingOrder)

    def test_combinacion_filtro_y_orden(self):
        """Simula el patrón real: filtrar primero (reduce filas) y luego
        aplicar el ordenamiento activo del usuario, como hace cada
        filter_table() de las pantallas."""
        df = pd.DataFrame({'Nombre': ['Carlos', 'ana', 'Beto', 'Diego'], 'Activo': [True, True, False, True]})
        table = self._make_table(df)
        table._sort_column, table._sort_order = 'Nombre', Qt.SortOrder.AscendingOrder

        df_filtrado = df[df['Activo']].copy()  # descarta 'Beto'
        resultado = table.apply_sort(df_filtrado)

        self.assertEqual(list(resultado['Nombre']), ['ana', 'Carlos', 'Diego'])

    def test_orden_persiste_entre_llamadas_sucesivas_con_distintos_df(self):
        """El estado de orden vive en el widget, no en el DataFrame: debe
        seguir aplicándose aunque cambie el contenido filtrado entre
        llamadas (búsqueda, recarga, etc.)."""
        df1 = pd.DataFrame({'Nombre': ['Carlos', 'ana', 'Beto']})
        table = self._make_table(df1)
        table._sort_column, table._sort_order = 'Nombre', Qt.SortOrder.AscendingOrder

        self.assertEqual(list(table.apply_sort(df1)['Nombre']), ['ana', 'Beto', 'Carlos'])

        df2 = pd.DataFrame({'Nombre': ['Zoe', 'Ana']})  # simula una nueva búsqueda
        self.assertEqual(list(table.apply_sort(df2)['Nombre']), ['Ana', 'Zoe'])


class TestVolvoTableWidgetMenuEliminados(unittest.TestCase):
    """menu_type='eliminados' (pestaña Papelera de Historial) debe ofrecer
    'Restaurar Fila' deshabilitada: ExcelWriter no implementa restore_row, y
    antes esta acción quedaba habilitada aunque terminara lanzando
    AttributeError al confirmarla."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_restaurar_fila_esta_deshabilitada(self):
        df = pd.DataFrame({"VIN": ["YV2AAA"], "MODELO": ["FM"]})
        table = VolvoTableWidget()
        table.menu_type = "eliminados"
        model = PandasTableModel()
        model.set_data(df)
        table.setModel(model)

        capturado = {}

        def fake_exec(self_menu, *args, **kwargs):
            capturado['acciones'] = {a.text(): a.isEnabled() for a in self_menu.actions()}
            return None

        with patch.object(table, 'rowAt', return_value=0), \
             patch.object(QMenu, 'exec', new=fake_exec):
            table._show_context_menu(QPoint(0, 0))

        self.assertIn("Restaurar Fila", capturado['acciones'])
        self.assertFalse(capturado['acciones']["Restaurar Fila"], "Fallo: 'Restaurar Fila' debe estar deshabilitada.")


class TestInstalacionesMenuType(unittest.TestCase):
    """Instalaciones no tiene test file propio ni carga datos asíncronos en su
    constructor (load_local_data() es síncrono y de solo lectura), así que se
    puede instanciar directo. Se omite si no corre dentro del sandbox de
    test_main.py, para nunca leer accidentalmente el Instalaciones.xlsx real."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])
        path = (getattr(config.settings, 'INSTALACIONES_PATH', '') or '').replace('\\', '/')
        if 'mock_data' not in path:
            raise unittest.SkipTest(
                "Requiere el entorno sandbox de test_main.py (INSTALACIONES_PATH no apunta a mock_data)."
            )

    def test_instalaciones_no_hereda_eliminar_camion(self):
        logger.info("[Test Instalaciones] Verificando que la tabla no herede el menú contextual de Comercial...")
        from src.ui.instalaciones import InstalacionesModule
        module = InstalacionesModule()
        self.assertNotEqual(
            module.table.menu_type, "comercial",
            "Fallo: la tabla de Instalaciones no debe mostrar 'Eliminar Camión' (menu_type='comercial')."
        )
        logger.info(" -> Éxito: Instalaciones ya no muestra la opción 'Eliminar Camión' en su menú contextual.")


class TestPandasTableModelHeaderData(unittest.TestCase):
    """Bug real reportado: al abrir Comercial con el Excel real (columnas
    reducidas de 34 a 33 respecto a la última vez que se guardó el estado
    del header con VolvoTableWidget.set_table_id), Qt seguía pidiendo
    headerData(33, ...) -- fuera de rango para un DataFrame de 33 columnas
    -- y PandasTableModel.headerData() indexaba directo sobre
    self._df.columns sin validar el rango, crasheando con IndexError."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_seccion_fuera_de_rango_no_lanza_indexerror(self):
        df = pd.DataFrame({'A': [1], 'B': [2], 'C': [3]})
        model = PandasTableModel()
        model.set_data(df)

        try:
            resultado = model.headerData(33, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        except IndexError:
            self.fail("headerData() no debe lanzar IndexError con section fuera de rango.")
        self.assertIsNone(resultado)

    def test_seccion_dentro_de_rango_sigue_funcionando(self):
        df = pd.DataFrame({'A': [1], 'B': [2], 'C': [3]})
        model = PandasTableModel()
        model.set_data(df)

        self.assertEqual(model.headerData(1, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole), 'B')

    def test_seccion_negativa_no_lanza_indexerror(self):
        df = pd.DataFrame({'A': [1]})
        model = PandasTableModel()
        model.set_data(df)

        try:
            resultado = model.headerData(-1, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        except IndexError:
            self.fail("headerData() no debe lanzar IndexError con section negativo.")
        self.assertIsNone(resultado)


class TestPandasTableModelTerminoContratoForeground(unittest.TestCase):
    """Fase 3 de la auditoria de rendimiento de UI (21-09-2026):
    PandasTableModel.data() llamaba comercial_services.clasificar_fecha_termino(val)
    -- que reconstruye un DataFrame de 1 fila y reparsea la fecha -- por
    CADA celda pintada de la columna TÉRMINO CONTRATO (ForegroundRole se pide
    por cada celda visible en cada repintado). Ahora usa
    comercial_services.clasificar_vigencia_contrato() una sola vez sobre la
    columna completa (cacheado en el modelo) y solo hace un lookup por fila.
    Este test cubre que el color resultante por celda no cambio, y que la
    cache se invalida correctamente (set_data nuevo, o cambio de dia
    calendario)."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    @staticmethod
    def _fecha(dias_desde_hoy):
        return (datetime.now().date() + timedelta(days=dias_desde_hoy)).strftime('%d-%m-%Y')

    def _color_termino(self, model, fila):
        index = model.index(fila, model._df.columns.get_loc('TÉRMINO CONTRATO'))
        return model.data(index, Qt.ItemDataRole.ForegroundRole)

    def test_colores_por_fila_segun_vigencia(self):
        df = pd.DataFrame({'TÉRMINO CONTRATO': [
            'MENSUAL',                 # es_mensual -> SUCCESS
            '',                        # sin fecha valida -> TEXT_MUTED
            self._fecha(-5),           # vencido -> DANGER
            self._fecha(10),           # por vencer (dentro de 30 dias) -> WARNING
            self._fecha(365),          # vigente, lejos de vencer -> SUCCESS
        ]})
        model = PandasTableModel()
        model.set_data(df)

        self.assertEqual(self._color_termino(model, 0).name(), QColor(SUCCESS).name())
        self.assertEqual(self._color_termino(model, 1).name(), QColor(TEXT_MUTED).name())
        self.assertEqual(self._color_termino(model, 2).name(), QColor(DANGER).name())
        self.assertEqual(self._color_termino(model, 3).name(), QColor(WARNING).name())
        self.assertEqual(self._color_termino(model, 4).name(), QColor(SUCCESS).name())

    def test_set_data_invalida_la_cache_anterior(self):
        df_vencido = pd.DataFrame({'TÉRMINO CONTRATO': [self._fecha(-5)]})
        model = PandasTableModel()
        model.set_data(df_vencido)
        self.assertEqual(self._color_termino(model, 0).name(), QColor(DANGER).name())

        df_mensual = pd.DataFrame({'TÉRMINO CONTRATO': ['MENSUAL']})
        model.set_data(df_mensual)
        self.assertEqual(self._color_termino(model, 0).name(), QColor(SUCCESS).name(),
                          "Fallo: debio recalcular tras set_data(), no reusar la clasificacion del DataFrame anterior.")

    def test_cache_se_recalcula_si_cambio_el_dia_desde_el_ultimo_calculo(self):
        # Vence hoy -> por_vencer -> WARNING (ver TestClasificarVigenciaContratoCalendario).
        df = pd.DataFrame({'TÉRMINO CONTRATO': [self._fecha(0)]})
        model = PandasTableModel()
        model.set_data(df)
        self.assertEqual(self._color_termino(model, 0).name(), QColor(WARNING).name())

        # Se simula una cache "vieja" (de otro dia) con una clasificacion
        # deliberadamente incorrecta: si data() no detecta el cambio de dia y
        # reusa esto tal cual, el color devuelto seria DANGER en vez de WARNING.
        model._clasif_termino_hoy = pd.Timestamp(datetime.now().date()) - pd.Timedelta(days=1)
        df_corrupto = comercial_services.clasificar_vigencia_contrato(df).copy()
        df_corrupto['vencido'] = True
        df_corrupto['por_vencer'] = False
        model._clasif_termino_df = df_corrupto

        self.assertEqual(self._color_termino(model, 0).name(), QColor(WARNING).name(),
                          "Fallo: debio recalcular la clasificacion al detectar que 'hoy' cambio, no reusar la cache vieja.")


class TestSetTableIdDescartaEstadoDesactualizado(unittest.TestCase):
    """VolvoTableWidget.set_table_id(): si el estado de columnas guardado en
    QSettings quedó con más columnas de las que tiene el modelo actual --
    p.ej. el Excel real perdió una columna desde la última vez que se
    guardó ese estado -- restaurarlo no debe dejar el header con secciones
    "fantasma" (más allá de las columnas reales) ni volver a crashear
    headerData() para ninguna sección del header resultante."""

    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def _make_table(self, df):
        table = VolvoTableWidget()
        model = PandasTableModel()
        model.set_data(df)
        table.setModel(model)
        return table

    def test_estado_con_mas_columnas_que_el_modelo_se_descarta(self):
        # 1) Genera un estado "guardado" real con 5 columnas (simula una
        # sesión anterior con el Excel viejo, de más columnas).
        tabla_vieja = self._make_table(pd.DataFrame({c: [1] for c in ['A', 'B', 'C', 'D', 'E']}))
        estado_guardado = tabla_vieja.horizontalHeader().saveState()

        # 2) Tabla nueva con un modelo de solo 3 columnas (el Excel real
        # actual), como al reabrir Comercial tras perder una columna.
        tabla_nueva = self._make_table(pd.DataFrame({c: [1] for c in ['A', 'B', 'C']}))

        store = {f"table_state_test_desactualizado": estado_guardado}

        class _FakeSettings:
            def __init__(self, *args, **kwargs):
                pass

            def value(self, key, default=None, type=None):
                return store.get(key, default)

            def setValue(self, key, value):
                store[key] = value

            def remove(self, key):
                store.pop(key, None)

        with patch('src.ui.custom_table.QSettings', _FakeSettings):
            tabla_nueva.set_table_id("test_desactualizado")

        self.assertEqual(
            tabla_nueva.horizontalHeader().count(), 3,
            "El header no debe quedar con más secciones que columnas tiene el modelo actual.",
        )

        # 3) headerData ya no debe crashear para ninguna sección del header actual.
        modelo = tabla_nueva.model()
        for seccion in range(tabla_nueva.horizontalHeader().count() + 2):
            try:
                modelo.headerData(seccion, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            except IndexError:
                self.fail(f"headerData({seccion}) no debe lanzar IndexError.")


if __name__ == '__main__':
    unittest.main(verbosity=2)
