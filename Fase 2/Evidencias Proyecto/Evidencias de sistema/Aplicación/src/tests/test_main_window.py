import time
import unittest
import logging
from unittest.mock import MagicMock, patch

import pandas as pd
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QMessageBox, QLabel
from PyQt6.QtCore import QEventLoop, QTimer, Qt, QEvent
from PyQt6.QtGui import QKeyEvent, QKeySequence

from src.ui.main_window import MainWindow, MultiSearchLineEdit, MAX_TERMINOS_BUSQUEDA_GLOBAL, DEBOUNCE_BUSQUEDA_GLOBAL_MS
from src.ui.sidebar_estilo import ANCHO_EXPANDIDO, ANCHO_COLAPSADO

logger = logging.getLogger("TestRunner")


class FakeModuleConCambios:
    """Simula un modulo (Comercial/Operaciones/etc.) con una 'mochila' pending_changes propia."""
    def __init__(self, pending_changes=None):
        self.pending_changes = pending_changes or {}


class TestMainWindowSincronizacion(unittest.TestCase):
    """
    Cubre el bug de sincronizacion: _on_snapshot_finished solo revisaba
    workspace.currentWidget() para decidir si habia cambios sin guardar,
    ignorando pending_changes de modulos cargados que no estaban visibles
    en pantalla. Esto provocaba que data_manager.load_data_async() se
    disparara en silencio y borrara ediciones no guardadas de un modulo
    en segundo plano.
    """

    def _make_fake_window(self, loaded_modules, current_widget):
        win = MainWindow.__new__(MainWindow)  # No ejecuta __init__ (evita bootstrap pesado de UI/DataManager)
        win.notif_btn = MagicMock()
        win.notification_count = 0
        win.panel_notificaciones = MagicMock()
        win.workspace = MagicMock()
        win.workspace.currentWidget.return_value = current_widget
        win.loaded_modules = loaded_modules
        win.data_manager = MagicMock()
        win._trigger_save_on_current_module = MagicMock()
        win._update_notification_badge = MagicMock()
        return win

    def _configurar_dialogo_cancelar(self, mock_msgbox_cls):
        mock_instance = mock_msgbox_cls.return_value
        btn_cancelar = MagicMock(name="btn_cancelar")
        mock_instance.addButton.side_effect = [MagicMock(name="btn_guardar"), MagicMock(name="btn_recargar"), btn_cancelar]
        mock_instance.clickedButton.return_value = btn_cancelar
        return mock_instance

    @patch('src.ui.main_window.QMessageBox')
    def test_01_cambios_pendientes_en_modulo_no_visible_no_se_pierden(self, mock_msgbox_cls):
        logger.info("[MainWindow 01] Verificando que cambios pendientes en un modulo en segundo plano bloqueen la recarga silenciosa...")

        modulo_comercial = FakeModuleConCambios(pending_changes={'YV2X': {'VIN': 'YV2X', 'cambios': {'ESTADO COMERCIAL': 'Vigente'}}})
        modulo_provisiones = FakeModuleConCambios(pending_changes={})

        win = self._make_fake_window(
            loaded_modules={"Comercial": modulo_comercial, "Provisiones": modulo_provisiones},
            current_widget=modulo_provisiones,
        )
        mock_instance = self._configurar_dialogo_cancelar(mock_msgbox_cls)

        cambios_externos = [{'tipo': 'Editado', 'VIN': 'YV2X', 'campo': 'ESTADO', 'viejo': 'A', 'nuevo': 'B'}]
        MainWindow._on_snapshot_finished(win, cambios_externos)

        mock_instance.exec.assert_called_once()
        win.data_manager.load_data_async.assert_not_called()
        self.assertEqual(modulo_comercial.pending_changes, {'YV2X': {'VIN': 'YV2X', 'cambios': {'ESTADO COMERCIAL': 'Vigente'}}})
        logger.info(" -> Exito: la recarga automatica no se disparo en silencio; se respeto la mochila de Comercial.")

    @patch('src.ui.main_window.QMessageBox')
    def test_02_cambios_pendientes_en_mas_de_un_modulo_en_segundo_plano(self, mock_msgbox_cls):
        logger.info("[MainWindow 02] Verificando deteccion cuando VARIOS modulos en segundo plano tienen cambios...")

        modulo_comercial = FakeModuleConCambios(pending_changes={})
        modulo_provisiones = FakeModuleConCambios(pending_changes={})
        modulo_operaciones = FakeModuleConCambios(pending_changes={'ABC': {'cambios': {'X': 1}}})

        win = self._make_fake_window(
            loaded_modules={
                "Comercial": modulo_comercial,
                "Provisiones": modulo_provisiones,
                "Operaciones": modulo_operaciones,
            },
            current_widget=modulo_provisiones,
        )
        mock_instance = self._configurar_dialogo_cancelar(mock_msgbox_cls)

        MainWindow._on_snapshot_finished(win, [{'tipo': 'Editado', 'VIN': 'ZZZ', 'campo': 'X', 'viejo': '1', 'nuevo': '2'}])

        mock_instance.exec.assert_called_once()
        win.data_manager.load_data_async.assert_not_called()
        logger.info(" -> Exito: se detectaron cambios pendientes aunque no estuvieran en el primer modulo cargado.")

    @patch('src.ui.main_window.QMessageBox')
    def test_03_sin_cambios_pendientes_mantiene_recarga_automatica(self, mock_msgbox_cls):
        logger.info("[MainWindow 03] Verificando que sin cambios pendientes se mantiene la recarga automatica (comportamiento original)...")

        modulo_comercial = FakeModuleConCambios(pending_changes={})
        modulo_provisiones = FakeModuleConCambios(pending_changes={})

        win = self._make_fake_window(
            loaded_modules={"Comercial": modulo_comercial, "Provisiones": modulo_provisiones},
            current_widget=modulo_provisiones,
        )

        MainWindow._on_snapshot_finished(win, [{'tipo': 'Editado', 'VIN': 'ZZZ', 'campo': 'X', 'viejo': '1', 'nuevo': '2'}])

        mock_msgbox_cls.assert_not_called()
        win.data_manager.load_data_async.assert_called_once()
        logger.info(" -> Exito: sin cambios pendientes, la recarga automatica sigue funcionando igual que antes.")


class TestDataLoadedTriggersRevisionCmReconciliation(unittest.TestCase):
    """Cuarto punto de disparo de Revision CM por ESTADO DEL CM=Expired
    (11-09-2026, pedido explicito del usuario): los otros tres puntos
    (guardar/importar en Contratos, guardar en Comercial) solo reaccionan a
    ediciones nuevas -- un VIN que YA estaba en Expired al cargar los datos
    (arranque, recarga manual, watchdog) nunca disparaba ninguno de esos
    tres. _on_data_loaded_success debe reconciliar con los datos recien
    cargados en cada data_ready, sin romper la carga si la reconciliacion
    falla. Desde el 28-09-2026 la reconciliación corre en
    ReconciliacionCasosExpiredThread: los tests esperan a que ese hilo
    termine antes de revisar el mock."""

    def _make_fake_window(self, df_master):
        win = MainWindow.__new__(MainWindow)
        # QMainWindow.__init__ hace falta para conectar finished del hilo
        # a un método de la ventana
        QMainWindow.__init__(win)
        win.menu_buttons = {"Vista General": MagicMock()}
        win.config_btn = MagicMock()
        fake_widget = MagicMock()
        win.workspace = MagicMock()
        win.workspace.currentWidget.return_value = fake_widget
        win.loaded_modules = {"Comercial": fake_widget}
        win.watcher_thread = MagicMock()
        win.data_manager = MagicMock()
        win.data_manager.df_master = df_master
        return win

    def _esperar_reconciliacion(self, win):
        hilo = getattr(win, '_reconciliacion_thread', None)
        if hilo is not None:
            self.assertTrue(hilo.wait(5000), "La reconciliación en segundo plano no terminó")

    @patch('src.ui.main_window.config.settings')
    @patch('src.ui.main_window.cm_bajas_service.procesar_reconciliacion_estado_expired')
    def test_reconcilia_al_cargar_datos_con_df_master_no_vacio(self, mock_reconciliar, mock_settings):
        mock_settings.CASOS_BAJA_CM_PATH = 'C:/fake/CasosBajaCM.csv'
        df = pd.DataFrame({'VIN': ['V1'], 'ESTADO DEL CM': ['Expired']})
        win = self._make_fake_window(df)

        MainWindow._on_data_loaded_success(win)
        self._esperar_reconciliacion(win)

        mock_reconciliar.assert_called_once()
        kwargs = mock_reconciliar.call_args.kwargs
        self.assertTrue(kwargs['df_pruebas_actual'].equals(df))
        self.assertEqual(kwargs['casos_path'], 'C:/fake/CasosBajaCM.csv')

    @patch('src.ui.main_window.cm_bajas_service.procesar_reconciliacion_estado_expired')
    def test_no_reconcilia_si_df_master_vacio(self, mock_reconciliar):
        win = self._make_fake_window(pd.DataFrame())

        MainWindow._on_data_loaded_success(win)
        self._esperar_reconciliacion(win)

        mock_reconciliar.assert_not_called()

    @patch('src.ui.main_window.cm_bajas_service.procesar_reconciliacion_estado_expired', side_effect=Exception("boom"))
    def test_error_en_reconciliacion_no_rompe_la_carga(self, mock_reconciliar):
        df = pd.DataFrame({'VIN': ['V1'], 'ESTADO DEL CM': ['Expired']})
        win = self._make_fake_window(df)

        try:
            MainWindow._on_data_loaded_success(win)
            self._esperar_reconciliacion(win)
        except Exception as e:
            self.fail(f"_on_data_loaded_success no debe propagar errores de reconciliacion: {e}")
        mock_reconciliar.assert_called_once()


class TestTriggerLoadDataUsaRefreshIfDirty(unittest.TestCase):
    """_trigger_load_data() es el hook de navegacion existente (clic de
    sidebar / cambio de tab) que la solucion de actualizacion diferida por
    visibilidad reutiliza (ver auditoria): si el modulo expone
    refresh_if_dirty() (General/Comercial/Operaciones/Contratos/Historial),
    se usa eso en vez de load_data() directo, para no reprocesar si no esta
    dirty. Los modulos sin ese metodo (Provisiones, Contactos,
    Instalaciones, Configuracion, Dashboard) conservan el comportamiento
    original: load_data() incondicional en cada navegacion."""

    def _esperar_timer(self):
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

    def test_modulo_con_refresh_if_dirty_usa_ese_metodo_no_load_data(self):
        modulo = MagicMock()

        MainWindow._trigger_load_data(None, modulo)
        self._esperar_timer()

        modulo.refresh_if_dirty.assert_called_once()
        modulo.load_data.assert_not_called()

    def test_modulo_sin_refresh_if_dirty_mantiene_load_data_incondicional(self):
        modulo = MagicMock(spec=['load_data'])

        MainWindow._trigger_load_data(None, modulo)
        self._esperar_timer()

        modulo.load_data.assert_called_once()

    def test_modulo_none_no_lanza_excepcion(self):
        MainWindow._trigger_load_data(None, None)


class TestSidebarToggleAnimacion(unittest.TestCase):
    """Cubre el fix de fluidez del sidebar: los clics recibidos mientras la
    animacion de apertura/cierre esta en curso deben ignorarse (guardado en
    _sidebar_animating), en vez de reiniciar la animacion con un valor de
    arranque desactualizado y producir un salto visual (tiron)."""

    def _make_sidebar_window(self):
        # QMainWindow.__init__ es necesario (no basta MainWindow.__new__ a
        # secas) para que las señales de QPropertyAnimation disparadas de
        # forma asincrona por el motor de animacion lleguen a los slots de
        # Python durante los tests.
        win = MainWindow.__new__(MainWindow)
        QMainWindow.__init__(win)
        win.sidebar_expanded = True
        win.menu_buttons = {}
        win.menu_icons = {}
        win.menu_texts = {}
        win.loaded_modules = {}
        win.notification_count = 0
        win.central_widget = QWidget()
        win.main_layout = QHBoxLayout(win.central_widget)
        win.main_layout.setContentsMargins(0, 0, 0, 0)
        win.main_layout.setSpacing(0)
        win._setup_sidebar()
        return win

    def _esperar_animacion(self, win, timeout_ms=2000):
        if win.animation.state() == win.animation.State.Stopped:
            return
        loop = QEventLoop()
        win.animation.finished.connect(loop.quit)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

    def test_estado_inicial_no_animando_y_ancho_expandido(self):
        win = self._make_sidebar_window()
        self.assertFalse(win._sidebar_animating)
        self.assertTrue(win.sidebar_expanded)
        self.assertEqual(win.sidebar.minimumWidth(), ANCHO_EXPANDIDO)

    def test_click_cierra_sidebar_correctamente(self):
        win = self._make_sidebar_window()
        win._toggle_sidebar()
        self.assertTrue(win._sidebar_animating)
        self.assertFalse(win.sidebar_expanded)
        self._esperar_animacion(win)
        self.assertFalse(win._sidebar_animating)
        self.assertEqual(win.sidebar.minimumWidth(), ANCHO_COLAPSADO)
        self.assertEqual(win.sidebar.maximumWidth(), ANCHO_COLAPSADO)

    def test_click_abre_sidebar_correctamente_desde_colapsado(self):
        win = self._make_sidebar_window()
        win._toggle_sidebar()
        self._esperar_animacion(win)

        win._toggle_sidebar()
        self.assertTrue(win.sidebar_expanded)
        self._esperar_animacion(win)
        self.assertEqual(win.sidebar.minimumWidth(), ANCHO_EXPANDIDO)
        self.assertEqual(win.sidebar.maximumWidth(), ANCHO_EXPANDIDO)

    def test_clics_repetidos_durante_animacion_se_ignoran_sin_saltos(self):
        win = self._make_sidebar_window()
        win._toggle_sidebar()  # arranca cierre expandido -> colapsado

        loop = QEventLoop()
        QTimer.singleShot(80, loop.quit)
        loop.exec()

        # La animación mueve minimumWidth/maximumWidth; width() no cambia en
        # una ventana que no se muestra
        width_mid_animacion = win.sidebar.minimumWidth()
        self.assertTrue(ANCHO_COLAPSADO < width_mid_animacion < ANCHO_EXPANDIDO,
                        "La animacion deberia estar a mitad de camino")

        # Clics repetidos mientras anima: deben ignorarse (sin reiniciar ni
        # saltar de ancho) y no deben quedar en cola.
        for _ in range(5):
            win._toggle_sidebar()

        self.assertEqual(win.sidebar.minimumWidth(), width_mid_animacion,
                          "Un clic durante la animacion no debe alterar el ancho actual (evita el salto/tiron)")
        self.assertFalse(win.sidebar_expanded, "El estado logico no debe haberse revertido por los clics ignorados")

    def test_doble_clic_rapido_termina_colapsado(self):
        win = self._make_sidebar_window()
        win._toggle_sidebar()
        win._toggle_sidebar()
        self._esperar_animacion(win)
        self.assertFalse(win._sidebar_animating)
        self.assertEqual(win.sidebar.minimumWidth(), ANCHO_COLAPSADO, "Debe terminar exactamente colapsado, nunca a medio ancho")

    def test_no_queda_a_medio_ancho_tras_multiples_ciclos_rapidos(self):
        win = self._make_sidebar_window()
        for _ in range(6):
            win._toggle_sidebar()
            self._esperar_animacion(win)

        self.assertFalse(win._sidebar_animating)
        self.assertIn(win.sidebar.minimumWidth(), (ANCHO_COLAPSADO, ANCHO_EXPANDIDO))
        self.assertEqual(win.sidebar.minimumWidth(), win.sidebar.maximumWidth())


class TestMultiSearchLineEditLimite(unittest.TestCase):
    """Regresion del bug real reportado: pegar una lista muy grande de VINs
    (~1548) en la barra de busqueda global congelaba la app durante ~20s
    (Windows la marca 'No responde' a partir de ~5s). MultiSearchLineEdit
    debe truncar el pegado a MAX_TERMINOS_BUSQUEDA_GLOBAL elementos y avisar
    al usuario, en vez de insertar la lista completa sin limite."""

    def _simular_pegado(self, texto_portapapeles):
        QApplication.clipboard().setText(texto_portapapeles)
        widget = MultiSearchLineEdit()
        evento = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        widget.keyPressEvent(evento)
        return widget

    def test_lista_dentro_del_limite_se_pega_completa(self):
        vins = [f"VIN{i:05d}" for i in range(50)]
        with patch.object(QMessageBox, 'warning') as mock_warning:
            widget = self._simular_pegado("\n".join(vins))
        mock_warning.assert_not_called()
        terminos = [t for t in widget.text().split(',') if t.strip()]
        self.assertEqual(len(terminos), 50)

    def test_lista_que_excede_el_limite_se_trunca(self):
        vins = [f"VIN{i:05d}" for i in range(1548)]
        with patch.object(QMessageBox, 'warning') as mock_warning:
            widget = self._simular_pegado("\n".join(vins))

        terminos = [t.strip() for t in widget.text().split(',') if t.strip()]
        self.assertEqual(len(terminos), MAX_TERMINOS_BUSQUEDA_GLOBAL,
                          "Fallo: el texto pegado debe truncarse exactamente al límite configurado.")
        self.assertEqual(terminos, vins[:MAX_TERMINOS_BUSQUEDA_GLOBAL],
                          "Fallo: deben conservarse los primeros elementos pegados, en el mismo orden.")
        mock_warning.assert_called_once()

    def test_exactamente_en_el_limite_no_avisa(self):
        vins = [f"VIN{i:05d}" for i in range(MAX_TERMINOS_BUSQUEDA_GLOBAL)]
        with patch.object(QMessageBox, 'warning') as mock_warning:
            widget = self._simular_pegado("\n".join(vins))
        mock_warning.assert_not_called()
        terminos = [t for t in widget.text().split(',') if t.strip()]
        self.assertEqual(len(terminos), MAX_TERMINOS_BUSQUEDA_GLOBAL)

    def test_pegado_vacio_no_revienta(self):
        with patch.object(QMessageBox, 'warning') as mock_warning:
            widget = self._simular_pegado("")
        mock_warning.assert_not_called()
        self.assertEqual(widget.text(), "")


class TestGlobalSearchDebounce(unittest.TestCase):
    """Fase 1 de la auditoria de rendimiento de UI (21-09-2026):
    _on_global_search() filtra y reconstruye la UI del modulo activo (tablas,
    tarjetas, pandas) y antes se ejecutaba integro en el hilo principal por
    CADA tecla -- incluido el auto-repeat de mantener una tecla apretada --
    congelando la app con datasets grandes. Ahora search_bar.textChanged solo
    dispara _on_global_search_text_changed (guarda texto pendiente + reinicia
    el timer); el filtrado real (_on_global_search, sin cambios) se ejecuta
    una sola vez, recien cuando el usuario deja de escribir por
    DEBOUNCE_BUSQUEDA_GLOBAL_MS."""

    def _make_window(self):
        win = MainWindow.__new__(MainWindow)  # No ejecuta __init__ (evita bootstrap pesado de UI/DataManager)
        win._global_search_timer = QTimer()
        win._global_search_timer.setSingleShot(True)
        win._global_search_timer.timeout.connect(lambda: MainWindow._ejecutar_busqueda_global_pendiente(win))
        win._pending_search_text = ""
        win._on_global_search = MagicMock()
        return win

    def _esperar(self, ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def test_teclas_rapidas_no_disparan_filtrado_de_inmediato(self):
        win = self._make_window()
        for ch in "ABC":
            MainWindow._on_global_search_text_changed(win, ch)
        win._on_global_search.assert_not_called()

    def test_varias_teclas_rapidas_disparan_un_solo_filtrado_con_el_texto_final(self):
        win = self._make_window()
        for texto_parcial in ("E", "EM", "EMP", "EMPR"):
            MainWindow._on_global_search_text_changed(win, texto_parcial)
        self._esperar(DEBOUNCE_BUSQUEDA_GLOBAL_MS + 150)
        win._on_global_search.assert_called_once_with("EMPR")

    def test_pausa_larga_entre_teclas_dispara_un_filtrado_por_cada_pausa(self):
        win = self._make_window()
        MainWindow._on_global_search_text_changed(win, "A")
        self._esperar(DEBOUNCE_BUSQUEDA_GLOBAL_MS + 150)
        MainWindow._on_global_search_text_changed(win, "AB")
        self._esperar(DEBOUNCE_BUSQUEDA_GLOBAL_MS + 150)

        self.assertEqual(win._on_global_search.call_count, 2)
        win._on_global_search.assert_any_call("A")
        win._on_global_search.assert_any_call("AB")

    def test_busqueda_vacia_tambien_se_debounce_y_llega_al_final(self):
        """Limpiar el buscador (texto vacio) debe seguir restaurando el
        modulo tras el debounce, igual que con cualquier otro texto."""
        win = self._make_window()
        MainWindow._on_global_search_text_changed(win, "EMPRESA")
        MainWindow._on_global_search_text_changed(win, "")
        self._esperar(DEBOUNCE_BUSQUEDA_GLOBAL_MS + 150)
        win._on_global_search.assert_called_once_with("")


class _FakeAppLockCoordinator:
    """Doble minimo de AppLockCoordinator: expone solo lo que
    MainWindow._on_app_lock_state_changed/_actualizar_banner_archivos_ocupados
    consultan, sin depender de FileLockMonitor real ni de hilos."""

    def __init__(self, claves_ocupadas=None, bloqueada=False):
        self._claves_ocupadas = set(claves_ocupadas or [])
        self._bloqueada = bloqueada

    def archivos_ocupados(self):
        return set(self._claves_ocupadas)

    def esta_bloqueada(self):
        return self._bloqueada


class TestMainWindowLockBanner(unittest.TestCase):
    """Fase 6: banner rojo de bloqueo. Mismo patron que el resto del archivo
    (MainWindow.__new__ sin ejecutar __init__) para probar los metodos de
    presentacion sin arrancar hilos ni DataManager reales."""

    def _make_window_con_banner(self, claves_ocupadas=None, bloqueada=False):
        win = MainWindow.__new__(MainWindow)
        win.central_widget = QWidget()
        win.lock_banner = QWidget()
        win.lock_banner.hide()
        win.lock_banner_archivos_lbl = QLabel("")
        win.app_lock_coordinator = _FakeAppLockCoordinator(claves_ocupadas, bloqueada)
        return win

    def test_bloqueada_true_muestra_banner_y_deshabilita_central_widget(self):
        win = self._make_window_con_banner(claves_ocupadas={"provisiones"})
        MainWindow._on_app_lock_state_changed(win, True)
        self.assertTrue(win.lock_banner.isVisible())
        self.assertFalse(win.central_widget.isEnabled())

    def test_bloqueada_false_oculta_banner_y_habilita_central_widget(self):
        win = self._make_window_con_banner()
        MainWindow._on_app_lock_state_changed(win, True)
        MainWindow._on_app_lock_state_changed(win, False)
        self.assertFalse(win.lock_banner.isVisible())
        self.assertTrue(win.central_widget.isEnabled())

    def test_banner_muestra_nombres_amigables_no_claves_tecnicas(self):
        win = self._make_window_con_banner(claves_ocupadas={"provisiones"})
        MainWindow._on_app_lock_state_changed(win, True)
        texto = win.lock_banner_archivos_lbl.text()
        self.assertIn("Proviciones", texto)
        self.assertNotIn("provisiones", texto)

    def test_banner_muestra_los_dos_archivos_ocupados_simultaneamente(self):
        win = self._make_window_con_banner(claves_ocupadas={"registro_maestro", "provisiones"})
        MainWindow._on_app_lock_state_changed(win, True)
        texto = win.lock_banner_archivos_lbl.text()
        self.assertIn("Registro Maestro (RM)", texto)
        self.assertIn("Proviciones", texto)

    def test_banner_se_actualiza_cuando_solo_cambia_el_conjunto_sin_desbloquear(self):
        win = self._make_window_con_banner(claves_ocupadas={"registro_maestro", "provisiones"}, bloqueada=True)
        MainWindow._on_app_lock_state_changed(win, True)
        self.assertIn("Registro Maestro (RM)", win.lock_banner_archivos_lbl.text())

        # Se libera 'registro_maestro'; la app sigue bloqueada (solo cambia
        # el conjunto), por eso se dispara _on_archivos_ocupados_cambiado,
        # no _on_app_lock_state_changed.
        win.app_lock_coordinator._claves_ocupadas = {"provisiones"}
        MainWindow._on_archivos_ocupados_cambiado(win)

        texto = win.lock_banner_archivos_lbl.text()
        self.assertNotIn("Registro Maestro (RM)", texto)
        self.assertIn("Proviciones", texto)
        self.assertTrue(win.lock_banner.isVisible(), "Fallo: el banner debe seguir visible, la app sigue bloqueada.")


if __name__ == '__main__':
    unittest.main(verbosity=2)
