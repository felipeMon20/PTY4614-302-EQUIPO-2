import time
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QEventLoop
from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget

from src.core.data_manager import DataManager
from src.ui.general import GeneralModule
from src.ui.comercial import ComercialModule
from src.ui.contratos import ContratosModule
from src.ui.historial import HistorialModule
from src.ui.configuracion import ConfiguracionModule


def _esperar_prep_thread_general(modulo, timeout_ms=20000, interval_ms=20):
    """Espera a que GeneralDataPrepThread (disparado por
    GeneralModule.load_data(), ver auditoria de rendimiento fase 4,
    21-09-2026) termine de aplicar su resultado. Antes load_data() era
    sincrono dentro de __init__; ahora dispara un QThread real, asi que
    "isVisible() no importa para la carga inicial" (lo que prueba
    TestGeneralCargaInicial) sigue siendo cierto, pero hay que esperar a que
    el worker termine antes de poder verificarlo. No se importa el
    equivalente de test_general.py a proposito (mismo criterio ya usado en
    este archivo: no acoplar archivos de test entre si con un helper
    'privado')."""
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if not modulo._prep_en_curso:
            QApplication.processEvents()
            return True
        time.sleep(interval_ms / 1000.0)
    return False


def _cargar_datos_sincronos(dm):
    """Fuerza una carga completa de DataManager y bloquea hasta que termine
    (data_ready o load_error), igual que el resto de la suite (ver
    test_comercial.py)."""
    loop = QEventLoop()
    dm.data_ready.connect(loop.quit)
    dm.load_error.connect(loop.quit)
    dm.load_data_async()
    loop.exec()


def _configurar_dialogo(mock_msgbox_cls, boton_elegido):
    """Configura el QMessageBox mockeado (patrón ya usado en
    test_main_window.py) para simular que el usuario hizo clic en
    'Guardar mis cambios' (0), 'Descartar y Recargar' (1) o 'Cancelar' (2)."""
    mock_instance = mock_msgbox_cls.return_value
    botones = [MagicMock(name="btn_guardar"), MagicMock(name="btn_recargar"), MagicMock(name="btn_cancelar")]
    mock_instance.addButton.side_effect = botones
    mock_instance.clickedButton.return_value = botones[boton_elegido]
    return mock_instance


class TestActualizacionDiferidaComercial(unittest.TestCase):
    """Cubre el mecanismo generico de actualizacion diferida por visibilidad
    + dirty flag (data_ready -> solo el modulo visible ejecuta load_data();
    los demas quedan dirty y se actualizan al volver a entrar) sobre
    ComercialModule, que ademas es el unico de los 5 modulos afectados con
    _skip_self_triggered_reload."""

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        _cargar_datos_sincronos(cls.dm)

    def setUp(self):
        self.modulo = ComercialModule()
        self.modulo._data_dirty = False
        self.modulo.pending_changes = {}
        self.modulo._skip_self_triggered_reload = False

    def test_01_modulo_visible_ejecuta_load_data_en_data_ready(self):
        # ComercialModule ahora abre por defecto en la pestaña "Comercial"
        # (new_ui_tab), no en "Vista Completa" (_ComercialModuleLegacy): la
        # visibilidad que importa para este mecanismo es la de
        # _ComercialModuleLegacy en si (ver _on_global_data_ready), asi que
        # hay que activar explicitamente esa sub-pestaña.
        self.modulo.tabs.setCurrentIndex(1)
        self.modulo.show()
        QApplication.processEvents()
        with patch.object(self.modulo, 'load_data', wraps=self.modulo.load_data) as spy_load:
            self.dm.data_ready.emit()
            spy_load.assert_called_once()
        self.assertFalse(self.modulo._data_dirty)

    def test_02_modulo_no_visible_no_ejecuta_load_data(self):
        self.modulo.hide()
        QApplication.processEvents()
        with patch.object(self.modulo, 'load_data', wraps=self.modulo.load_data) as spy_load:
            self.dm.data_ready.emit()
            spy_load.assert_not_called()

    def test_03_modulo_no_visible_queda_marcado_dirty(self):
        self.modulo.hide()
        QApplication.processEvents()
        self.dm.data_ready.emit()
        self.assertTrue(self.modulo._data_dirty)

    def test_04_refresh_if_dirty_ejecuta_load_data_si_estaba_dirty(self):
        self.modulo._data_dirty = True
        with patch.object(self.modulo, 'load_data', wraps=self.modulo.load_data) as spy_load:
            self.modulo.refresh_if_dirty()
            spy_load.assert_called_once()

    def test_05_refresh_if_dirty_limpia_el_flag(self):
        self.modulo._data_dirty = True
        self.modulo.refresh_if_dirty()
        self.assertFalse(self.modulo._data_dirty)

    def test_06_refresh_if_dirty_no_hace_nada_si_no_esta_dirty(self):
        self.modulo._data_dirty = False
        with patch.object(self.modulo, 'load_data', wraps=self.modulo.load_data) as spy_load:
            self.modulo.refresh_if_dirty()
            spy_load.assert_not_called()

    @patch('src.ui.comercial.QMessageBox')
    def test_07_pending_changes_no_se_pierden_si_usuario_cancela(self, mock_msgbox_cls):
        self.modulo._data_dirty = True
        self.modulo.pending_changes = {
            'YV2TEST0000000001': {'VIN': 'YV2TEST0000000001', 'cambios': {'ESTADO COMERCIAL': 'Vigente'}}
        }
        mock_instance = _configurar_dialogo(mock_msgbox_cls, boton_elegido=2)  # Cancelar

        with patch.object(self.modulo, 'load_data', wraps=self.modulo.load_data) as spy_load:
            self.modulo.refresh_if_dirty()
            spy_load.assert_not_called()

        mock_instance.exec.assert_called_once()
        self.assertEqual(len(self.modulo.pending_changes), 1, "Cancelar no debe descartar los cambios pendientes.")
        self.assertTrue(self.modulo._data_dirty, "Sigue pendiente de refrescar: el usuario no eligio ninguna accion definitiva.")

    @patch('src.ui.comercial.QMessageBox')
    def test_08_descartar_y_recargar_limpia_pending_changes_y_dirty(self, mock_msgbox_cls):
        self.modulo._data_dirty = True
        self.modulo.pending_changes = {
            'YV2TEST0000000001': {'VIN': 'YV2TEST0000000001', 'cambios': {'ESTADO COMERCIAL': 'Vigente'}}
        }
        _configurar_dialogo(mock_msgbox_cls, boton_elegido=1)  # Descartar y Recargar

        self.modulo.refresh_if_dirty()

        self.assertEqual(self.modulo.pending_changes, {}, "Descartar y Recargar debe limpiar la mochila de cambios (mismo comportamiento que load_data() siempre tuvo).")
        self.assertFalse(self.modulo._data_dirty)

    @patch('src.ui.comercial.QMessageBox')
    def test_09_guardar_mis_cambios_invoca_confirm_save_sin_descartar_nada(self, mock_msgbox_cls):
        self.modulo._data_dirty = True
        self.modulo.pending_changes = {
            'YV2TEST0000000001': {'VIN': 'YV2TEST0000000001', 'cambios': {'ESTADO COMERCIAL': 'Vigente'}}
        }
        _configurar_dialogo(mock_msgbox_cls, boton_elegido=0)  # Guardar mis cambios

        with patch.object(self.modulo, 'confirm_save') as spy_confirm_save, \
             patch.object(self.modulo, 'load_data', wraps=self.modulo.load_data) as spy_load:
            self.modulo.refresh_if_dirty()
            spy_confirm_save.assert_called_once()
            spy_load.assert_not_called()

        # confirm_save() (ya probado en test_comercial.py) es quien
        # eventualmente limpia pending_changes via _on_save_finished tras el
        # guardado real; aqui solo verificamos que se invoco correctamente y
        # que nada se descarto en el camino.
        self.assertEqual(len(self.modulo.pending_changes), 1)

    def test_10_skip_self_triggered_reload_tiene_prioridad_sobre_dirty(self):
        """La auditoria exigio explicitamente que _skip_self_triggered_reload
        se siga evaluando ANTES que la logica de visible/dirty (cross-updates
        Provisiones -> Comercial)."""
        self.modulo.hide()
        QApplication.processEvents()
        self.modulo._skip_self_triggered_reload = True

        with patch.object(self.modulo, 'load_data', wraps=self.modulo.load_data) as spy_load:
            self.dm.data_ready.emit()
            spy_load.assert_not_called()

        self.assertFalse(self.modulo._skip_self_triggered_reload, "Debe consumirse (volver a False) igual que antes del cambio.")
        self.assertFalse(self.modulo._data_dirty, "No debe quedar dirty: el propio modulo ya sabe que sus datos estan al dia (el fue quien origino el cambio).")


class TestActualizacionDiferidaOtrosModulos(unittest.TestCase):
    """Verifica que Contratos (el otro modulo con pending_changes) sigue el
    mismo patron generico que Comercial.

    Operaciones quedo fuera de esta clase desde el 14-09-2026: su interfaz
    fue reemplazada por una maqueta puramente visual (ver operaciones.py),
    sin DataManager/pending_changes/_data_dirty reales -- refresh_if_dirty
    y load_data siguen existiendo solo como no-ops de compatibilidad con
    MainWindow, asi que el mecanismo de actualizacion diferida que este
    caso cubria ya no aplica a ese modulo."""

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        _cargar_datos_sincronos(cls.dm)

    def test_contratos_no_visible_marca_dirty_y_protege_pending_changes(self):
        modulo = ContratosModule()
        modulo.hide()
        QApplication.processEvents()

        with patch.object(modulo, 'load_data', wraps=modulo.load_data) as spy_load:
            self.dm.data_ready.emit()
            spy_load.assert_not_called()
        self.assertTrue(modulo._data_dirty)

        modulo.pending_changes = {'YV2TEST0000000001': {'cambios': {'ESTADO DEL CM': 'Running'}}}
        with patch('src.ui.contratos.QMessageBox') as mock_msgbox_cls:
            _configurar_dialogo(mock_msgbox_cls, boton_elegido=2)  # Cancelar
            modulo.refresh_if_dirty()
        self.assertEqual(len(modulo.pending_changes), 1, "No debe perder cambios pendientes al cancelar.")


class TestHistorialDualSenal(unittest.TestCase):
    """HistorialModule comparte load_data() entre data_ready (debe respetar
    visible/dirty) y logs_updated (debe seguir siendo inmediato, sin pasar
    por el dirty flag)."""

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        _cargar_datos_sincronos(cls.dm)

    def setUp(self):
        self.modulo = HistorialModule()

    def test_data_ready_respeta_visibilidad(self):
        self.modulo.hide()
        QApplication.processEvents()
        with patch.object(self.modulo, 'load_data', wraps=self.modulo.load_data) as spy_load:
            self.dm.data_ready.emit()
            spy_load.assert_not_called()
        self.assertTrue(self.modulo._data_dirty)

    def test_logs_updated_no_espera_visibilidad_ni_dirty(self):
        # logs_updated se conecta directo a self.load_data en __init__ (no
        # pasa por _on_data_ready), asi que un patch.object() posterior sobre
        # la instancia no intercepta esa conexion -- se verifica el efecto
        # real (el propio load_data() limpia _data_dirty al ejecutar) en vez
        # de contar llamadas por mock.
        self.modulo.hide()
        QApplication.processEvents()
        self.modulo._data_dirty = True  # simula que habia quedado pendiente

        self.dm.logs_updated.emit()
        QApplication.processEvents()

        self.assertFalse(
            self.modulo._data_dirty,
            "logs_updated debe seguir disparando load_data() de inmediato, sin pasar por el dirty flag."
        )


class TestVisibilidadDentroDeTabs(unittest.TestCase):
    """Un submodulo dentro de un QTabWidget (Administracion / Ingresos y
    Conciliacion) solo debe considerarse visible si su grupo Y su tab estan
    activos -- no basta con que el grupo este en pantalla."""

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        _cargar_datos_sincronos(cls.dm)

    def test_submodulo_en_tab_no_activo_no_es_visible(self):
        tabs = QTabWidget()
        modulo_historial = HistorialModule()
        otro_tab = QWidget()
        tabs.addTab(otro_tab, "Otro")
        tabs.addTab(modulo_historial, "Historial")
        tabs.setCurrentIndex(0)  # Historial queda en el tab NO activo
        tabs.show()
        QApplication.processEvents()

        self.assertFalse(modulo_historial.isVisible(), "El tab no activo no debe reportarse visible.")

        with patch.object(modulo_historial, 'load_data', wraps=modulo_historial.load_data) as spy_load:
            self.dm.data_ready.emit()
            spy_load.assert_not_called()
        self.assertTrue(modulo_historial._data_dirty)

        tabs.setCurrentIndex(1)  # ahora Historial es el tab activo
        QApplication.processEvents()
        self.assertTrue(modulo_historial.isVisible(), "Al activar su tab, debe reportarse visible.")

        modulo_historial.refresh_if_dirty()
        self.assertFalse(modulo_historial._data_dirty)


class TestConfiguracionSinCambios(unittest.TestCase):
    """ConfiguracionModule quedo explicitamente fuera del alcance: su
    actualizacion es liviana y debe seguir corriendo siempre, sin flag
    dirty."""

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        _cargar_datos_sincronos(cls.dm)

    def test_configuracion_no_tiene_mecanismo_dirty(self):
        modulo = ConfiguracionModule()
        self.assertFalse(hasattr(modulo, '_data_dirty'))
        self.assertFalse(hasattr(modulo, 'refresh_if_dirty'))

    def test_configuracion_actualiza_siempre_este_visible_o_no(self):
        # data_ready se conecta directo a self.update_health_panel en
        # __init__: un patch.object() posterior sobre la instancia no
        # intercepta esa conexion (PyQt ya capturo el metodo original al
        # conectar), asi que se verifica el efecto real sobre la UI en vez
        # de contar llamadas por mock.
        modulo = ConfiguracionModule()
        modulo.hide()
        QApplication.processEvents()
        modulo.card_rows['val_lbl'].setText("PLACEHOLDER_ANTES_DE_EMITIR")

        self.dm.data_ready.emit()
        QApplication.processEvents()

        self.assertNotEqual(
            modulo.card_rows['val_lbl'].text(), "PLACEHOLDER_ANTES_DE_EMITIR",
            "update_health_panel debe correr sin importar la visibilidad (no tiene mecanismo dirty)."
        )


class TestGeneralCargaInicial(unittest.TestCase):
    """La auditoria exigio explicitamente NO introducir un caso especial
    para la carga inicial de GeneralModule: debe seguir llamando load_data()
    de forma incondicional en su constructor, sin depender de isVisible()."""

    @classmethod
    def setUpClass(cls):
        cls.dm = DataManager()
        _cargar_datos_sincronos(cls.dm)

    def test_general_carga_datos_en_el_constructor_sin_necesitar_ser_visible(self):
        # No se llama a .show(): isVisible() es False en este punto, y aun
        # asi la carga inicial debe haber corrido (igual que antes del
        # cambio, ver GeneralModule.__init__ -> self.load_data()) -- ahora
        # load_data() dispara GeneralDataPrepThread en vez de calcular todo
        # de forma sincrona (auditoria de rendimiento, fase 4, 21-09-2026),
        # asi que hay que esperar a que termine antes de verificarlo.
        modulo = GeneralModule()
        self.assertFalse(modulo.isVisible())
        listo = _esperar_prep_thread_general(modulo)
        self.assertTrue(listo, "GeneralDataPrepThread no termino dentro del timeout.")
        self.assertFalse(modulo.df_clientes_base.empty, "La carga inicial de General no debe depender de isVisible().")
        self.assertFalse(modulo._data_dirty)

    def test_general_visible_actualiza_en_data_ready_y_no_visible_marca_dirty(self):
        modulo = GeneralModule()
        modulo.hide()
        QApplication.processEvents()

        with patch.object(modulo, 'load_data', wraps=modulo.load_data) as spy_load:
            self.dm.data_ready.emit()
            spy_load.assert_not_called()
        self.assertTrue(modulo._data_dirty)

        modulo.show()
        QApplication.processEvents()
        with patch.object(modulo, 'load_data', wraps=modulo.load_data) as spy_load:
            self.dm.data_ready.emit()
            spy_load.assert_called_once()
        self.assertFalse(modulo._data_dirty)


if __name__ == '__main__':
    unittest.main()
