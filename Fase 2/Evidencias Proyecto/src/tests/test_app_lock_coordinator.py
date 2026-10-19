import time
import unittest
from unittest.mock import patch

from src.core.data_manager import DataManager
from src.core.file_lock_monitor import FileLockMonitor
from src.core.app_lock_coordinator import AppLockCoordinator

ARCHIVOS_PRINCIPALES = {
    "registro_maestro": "C:\\ficticio\\rm.xlsx",
    "provisiones": "C:\\ficticio\\prov.xlsx",
    "bbdd_clientes_cm": "C:\\ficticio\\bbdd.xlsx",
    "administradores_contactos": "C:\\ficticio\\contactos.xlsx",
}


def _crear_monitor_y_coordinador(umbral_ocupado=3, umbral_disponible=2):
    monitor = FileLockMonitor(
        archivos=dict(ARCHIVOS_PRINCIPALES),
        umbral_confirmar_ocupado=umbral_ocupado,
        umbral_confirmar_disponible=umbral_disponible,
    )
    coordinador = AppLockCoordinator(monitor.estado_cambiado)
    return monitor, coordinador


def _tick_con_resultados(monitor, resultados_por_clave):
    """resultados_por_clave: {clave: bool_bloqueado} para un unico tick."""
    with patch.object(monitor, '_esta_bloqueado_ahora', side_effect=lambda ruta: resultados_por_clave.get(
            next(c for c, r in monitor._archivos.items() if r == ruta), False)):
        monitor.tick()


class TestAppLockCoordinatorTodosDisponibles(unittest.TestCase):
    """1. Todos los archivos disponibles -> aplicacion no bloqueada."""

    def test_todos_disponibles_no_bloquea(self):
        monitor, coordinador = _crear_monitor_y_coordinador()
        for _ in range(5):
            _tick_con_resultados(monitor, {})
        self.assertFalse(coordinador.esta_bloqueada())
        self.assertEqual(coordinador.archivos_ocupados(), set())


class TestAppLockCoordinatorUnArchivoOcupado(unittest.TestCase):
    """2 y 3. Cualquiera de los 4 archivos, ocupado de forma individual, debe bloquear la app."""

    def test_un_archivo_ocupado_bloquea(self):
        monitor, coordinador = _crear_monitor_y_coordinador(umbral_ocupado=3)
        for _ in range(3):
            _tick_con_resultados(monitor, {"provisiones": True})
        self.assertTrue(coordinador.esta_bloqueada())
        self.assertEqual(coordinador.archivos_ocupados(), {"provisiones"})

    def test_cualquiera_de_los_cuatro_archivos_bloquea_individualmente(self):
        for clave in ARCHIVOS_PRINCIPALES:
            with self.subTest(clave=clave):
                monitor, coordinador = _crear_monitor_y_coordinador(umbral_ocupado=3)
                for _ in range(3):
                    _tick_con_resultados(monitor, {clave: True})
                self.assertTrue(coordinador.esta_bloqueada(), f"Fallo: '{clave}' ocupado debe bloquear la app.")
                self.assertEqual(coordinador.archivos_ocupados(), {clave})


class TestAppLockCoordinatorDosArchivosOcupados(unittest.TestCase):
    """4. Dos archivos ocupados simultaneamente -> bloqueo, y solo se libera
    cuando el ULTIMO de ellos vuelve a estar disponible."""

    def setUp(self):
        self.monitor, self.coordinador = _crear_monitor_y_coordinador(umbral_ocupado=2, umbral_disponible=2)

    def test_dos_archivos_ocupados_simultaneamente_bloquea(self):
        for _ in range(2):
            _tick_con_resultados(self.monitor, {"provisiones": True, "bbdd_clientes_cm": True})
        self.assertTrue(self.coordinador.esta_bloqueada())
        self.assertEqual(self.coordinador.archivos_ocupados(), {"provisiones", "bbdd_clientes_cm"})

    def test_liberar_solo_uno_de_los_dos_mantiene_bloqueada_la_app(self):
        for _ in range(2):
            _tick_con_resultados(self.monitor, {"provisiones": True, "bbdd_clientes_cm": True})
        self.assertTrue(self.coordinador.esta_bloqueada())

        # Se libera 'provisiones' pero 'bbdd_clientes_cm' sigue ocupado.
        for _ in range(2):
            _tick_con_resultados(self.monitor, {"bbdd_clientes_cm": True})
        self.assertTrue(self.coordinador.esta_bloqueada(),
                         "Fallo: la app debe seguir bloqueada mientras quede al menos un archivo ocupado.")
        self.assertEqual(self.coordinador.archivos_ocupados(), {"bbdd_clientes_cm"})


class TestAppLockCoordinatorVueltaANormal(unittest.TestCase):
    """5. Todos disponibles nuevamente -> desbloqueo."""

    def test_todos_disponibles_de_nuevo_desbloquea(self):
        monitor, coordinador = _crear_monitor_y_coordinador(umbral_ocupado=2, umbral_disponible=2)
        for _ in range(2):
            _tick_con_resultados(monitor, {"registro_maestro": True})
        self.assertTrue(coordinador.esta_bloqueada())

        for _ in range(2):
            _tick_con_resultados(monitor, {})
        self.assertFalse(coordinador.esta_bloqueada())
        self.assertEqual(coordinador.archivos_ocupados(), set())


class TestAppLockCoordinatorTransitorioNoBloquea(unittest.TestCase):
    """6. Un unico PermissionError/transitorio (que no llega al umbral de
    confirmacion de FileLockMonitor) no debe bloquear la app."""

    def test_bloqueo_unico_no_bloquea_la_app(self):
        monitor, coordinador = _crear_monitor_y_coordinador(umbral_ocupado=3)
        _tick_con_resultados(monitor, {"administradores_contactos": True})
        self.assertFalse(coordinador.esta_bloqueada())

    def test_bloqueo_transitorio_que_se_libera_antes_del_umbral_no_bloquea(self):
        monitor, coordinador = _crear_monitor_y_coordinador(umbral_ocupado=3)
        _tick_con_resultados(monitor, {"administradores_contactos": True})
        _tick_con_resultados(monitor, {"administradores_contactos": True})
        _tick_con_resultados(monitor, {})  # se libera justo antes de confirmar (umbral=3)
        _tick_con_resultados(monitor, {})
        self.assertFalse(coordinador.esta_bloqueada(),
                          "Fallo: un bloqueo transitorio que no persiste no debe bloquear la app.")


class TestAppLockCoordinatorGuardadoPropio(unittest.TestCase):
    """7. El guardado propio de la aplicacion (DataManager.is_app_saving)
    no debe generar un bloqueo de la app, igual que ya ocurre a nivel de
    FileLockMonitor (Fase 4)."""

    def setUp(self):
        self.dm = DataManager()
        self.dm.is_app_saving = False

    def tearDown(self):
        self.dm.is_app_saving = False

    def test_bloqueo_durante_guardado_propio_no_bloquea_la_app(self):
        monitor, coordinador = _crear_monitor_y_coordinador(umbral_ocupado=2)
        self.dm.is_app_saving = True
        self.dm.save_timestamp = time.time()

        for _ in range(3):
            _tick_con_resultados(monitor, {"registro_maestro": True})

        self.assertFalse(coordinador.esta_bloqueada(),
                          "Fallo: un bloqueo detectado durante el guardado propio de la app no debe bloquear la app.")


class TestAppLockCoordinatorSenalEstadoCambiado(unittest.TestCase):
    """8. El estado se actualiza correctamente (y la señal se emite en el
    momento correcto) cuando FileLockMonitor emite estado_cambiado."""

    def test_senal_se_emite_solo_en_las_transiciones_reales(self):
        monitor, coordinador = _crear_monitor_y_coordinador(umbral_ocupado=2, umbral_disponible=2)
        emitidos = []
        coordinador.estado_app_cambiado.connect(lambda bloqueada: emitidos.append(bloqueada))

        _tick_con_resultados(monitor, {"registro_maestro": True})
        self.assertEqual(emitidos, [], "Fallo: no debe emitirse nada antes de confirmar el primer archivo ocupado.")

        _tick_con_resultados(monitor, {"registro_maestro": True})
        self.assertEqual(emitidos, [True], "Fallo: debe emitirse True exactamente al confirmarse el primer archivo ocupado.")

        # Un segundo archivo se confirma ocupado mientras el primero sigue
        # ocupado: la app ya estaba bloqueada, no debe volver a emitir.
        _tick_con_resultados(monitor, {"registro_maestro": True, "provisiones": True})
        _tick_con_resultados(monitor, {"registro_maestro": True, "provisiones": True})
        self.assertEqual(emitidos, [True], "Fallo: no debe volver a emitirse True si la app ya estaba bloqueada.")

        # Se libera 'registro_maestro' pero 'provisiones' sigue ocupado: no debe desbloquear.
        _tick_con_resultados(monitor, {"provisiones": True})
        _tick_con_resultados(monitor, {"provisiones": True})
        self.assertEqual(emitidos, [True], "Fallo: no debe desbloquear mientras quede un archivo ocupado.")

        # Se libera el ultimo archivo ocupado: ahi si debe emitir False.
        _tick_con_resultados(monitor, {})
        _tick_con_resultados(monitor, {})
        self.assertEqual(emitidos, [True, False], "Fallo: debe emitirse False exactamente al liberarse el ultimo archivo ocupado.")


class TestAppLockCoordinatorArchivosOcupadosCambiado(unittest.TestCase):
    """Fase 6: archivos_ocupados_cambiado() debe reflejar cualquier cambio
    del CONJUNTO de archivos ocupados, incluso cuando el booleano agregado
    (estado_app_cambiado) no cambia -- necesario para que la alerta visual
    pueda mostrar la lista actualizada de archivos ocupados mientras la app
    sigue bloqueada."""

    def setUp(self):
        self.monitor, self.coordinador = _crear_monitor_y_coordinador(umbral_ocupado=2, umbral_disponible=2)
        self.eventos_conjunto = []
        self.coordinador.archivos_ocupados_cambiado.connect(lambda: self.eventos_conjunto.append(self.coordinador.archivos_ocupados()))

    def test_se_emite_al_confirmarse_el_primer_archivo_ocupado(self):
        for _ in range(2):
            _tick_con_resultados(self.monitor, {"registro_maestro": True})
        self.assertEqual(self.eventos_conjunto, [{"registro_maestro"}])

    def test_se_emite_al_agregarse_un_segundo_archivo_ocupado_aunque_la_app_ya_estuviera_bloqueada(self):
        for _ in range(2):
            _tick_con_resultados(self.monitor, {"registro_maestro": True})
        self.assertTrue(self.coordinador.esta_bloqueada())

        for _ in range(2):
            _tick_con_resultados(self.monitor, {"registro_maestro": True, "provisiones": True})

        self.assertEqual(self.eventos_conjunto[-1], {"registro_maestro", "provisiones"},
                          "Fallo: el conjunto debe reflejar ambos archivos ocupados.")

    def test_se_emite_al_liberar_solo_uno_de_dos_archivos_ocupados_sin_desbloquear_la_app(self):
        for _ in range(2):
            _tick_con_resultados(self.monitor, {"registro_maestro": True, "provisiones": True})
        self.eventos_conjunto.clear()

        for _ in range(2):
            _tick_con_resultados(self.monitor, {"provisiones": True})  # se libera 'registro_maestro'

        self.assertTrue(self.coordinador.esta_bloqueada(), "Fallo: debe seguir bloqueada, 'provisiones' sigue ocupado.")
        self.assertEqual(self.eventos_conjunto[-1], {"provisiones"},
                          "Fallo: el conjunto debe actualizarse a solo 'provisiones' tras liberar 'registro_maestro'.")

    def test_no_se_emite_si_el_conjunto_no_cambia_realmente(self):
        for _ in range(2):
            _tick_con_resultados(self.monitor, {})
        self.assertEqual(self.eventos_conjunto, [],
                          "Fallo: no debe emitirse nada si nunca hubo un cambio real en el conjunto de archivos ocupados.")


if __name__ == '__main__':
    unittest.main(verbosity=2)
