import os
import time
import tempfile
import unittest
from unittest.mock import patch

from src.core.data_manager import DataManager
from src.core.file_lock_monitor import FileLockMonitor


class TestFileLockMonitorArchivoDisponible(unittest.TestCase):
    """Caso base con un archivo real (sin mocks del sistema operativo):
    un archivo cerrado y sin nada bloqueandolo debe reportarse disponible."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.ruta = os.path.join(self.temp_dir.name, "archivo_libre.xlsx")
        with open(self.ruta, 'w', encoding='utf-8') as f:
            f.write("dato")
        self.monitor = FileLockMonitor(archivos={"archivo": self.ruta})

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_archivo_disponible_nunca_se_confirma_ocupado(self):
        for _ in range(5):
            self.monitor.tick()
        self.assertFalse(self.monitor.esta_ocupado("archivo"),
                          "Fallo: un archivo real, cerrado y sin bloqueo, no debe reportarse como ocupado.")


class TestFileLockMonitorConfirmacion(unittest.TestCase):
    """Logica de confirmacion por persistencia, sin depender de bloqueos de
    OS reales (se mockea _esta_bloqueado_ahora para controlar exactamente
    la secuencia de resultados de cada sondeo)."""

    def setUp(self):
        self.monitor = FileLockMonitor(
            archivos={"archivo": "C:\\ruta\\ficticia.xlsx"},
            umbral_confirmar_ocupado=3,
            umbral_confirmar_disponible=2,
        )

    def _tick_con_resultado(self, bloqueado):
        with patch.object(self.monitor, '_esta_bloqueado_ahora', return_value=bloqueado):
            self.monitor.tick()

    def test_permission_error_persistente_termina_confirmando_ocupado(self):
        # 3 sondeos consecutivos bloqueados (umbral_confirmar_ocupado=3)
        self._tick_con_resultado(True)
        self.assertFalse(self.monitor.esta_ocupado("archivo"), "Fallo: no debe confirmarse ocupado con un solo sondeo bloqueado.")
        self._tick_con_resultado(True)
        self.assertFalse(self.monitor.esta_ocupado("archivo"), "Fallo: no debe confirmarse ocupado con solo dos sondeos bloqueados.")
        self._tick_con_resultado(True)
        self.assertTrue(self.monitor.esta_ocupado("archivo"), "Fallo: tres sondeos bloqueados consecutivos deben confirmar OCUPADO.")

    def test_bloqueo_unico_no_confirma_ocupado(self):
        # Un solo fallo (ej. un PermissionError aislado) no debe marcar el
        # archivo como ocupado: es exactamente el escenario de un blip
        # transitorio de OneDrive.
        self._tick_con_resultado(True)
        self.assertFalse(self.monitor.esta_ocupado("archivo"))
        self._tick_con_resultado(False)
        self.assertFalse(self.monitor.esta_ocupado("archivo"))

    def test_bloqueo_transitorio_que_desaparece_no_confirma_ocupado(self):
        # Simula un bloqueo de OneDrive de 2 sondeos que se libera antes de
        # llegar al umbral de confirmacion (3): nunca debe confirmarse.
        self._tick_con_resultado(True)
        self._tick_con_resultado(True)
        self._tick_con_resultado(False)
        self._tick_con_resultado(False)
        self.assertFalse(self.monitor.esta_ocupado("archivo"),
                          "Fallo: un bloqueo transitorio que se libera antes del umbral no debe confirmarse como ocupado.")

    def test_bloqueo_que_persiste_se_confirma_y_se_mantiene(self):
        for _ in range(3):
            self._tick_con_resultado(True)
        self.assertTrue(self.monitor.esta_ocupado("archivo"))
        # Sigue bloqueado en sondeos posteriores: debe seguir confirmado.
        self._tick_con_resultado(True)
        self._tick_con_resultado(True)
        self.assertTrue(self.monitor.esta_ocupado("archivo"))

    def test_vuelve_de_ocupado_a_disponible_tras_umbral_de_recuperacion(self):
        for _ in range(3):
            self._tick_con_resultado(True)
        self.assertTrue(self.monitor.esta_ocupado("archivo"))

        # umbral_confirmar_disponible=2: un solo sondeo libre no alcanza.
        self._tick_con_resultado(False)
        self.assertTrue(self.monitor.esta_ocupado("archivo"), "Fallo: no debe liberarse con un solo sondeo disponible.")

        self._tick_con_resultado(False)
        self.assertFalse(self.monitor.esta_ocupado("archivo"), "Fallo: dos sondeos disponibles consecutivos deben liberar el archivo.")

    def test_emite_senal_estado_cambiado_solo_al_confirmar_cambios(self):
        emitidos = []
        self.monitor.estado_cambiado.connect(lambda clave, ocupado: emitidos.append((clave, ocupado)))

        self._tick_con_resultado(True)
        self._tick_con_resultado(True)
        self.assertEqual(emitidos, [], "Fallo: no debe emitirse ninguna señal antes de confirmar el cambio de estado.")

        self._tick_con_resultado(True)
        self.assertEqual(emitidos, [("archivo", True)], "Fallo: debe emitirse una señal exactamente al confirmar OCUPADO.")

        self._tick_con_resultado(False)
        self._tick_con_resultado(False)
        self.assertEqual(emitidos, [("archivo", True), ("archivo", False)],
                          "Fallo: debe emitirse una señal exactamente al confirmar la vuelta a DISPONIBLE.")


class TestFileLockMonitorCuatroArchivosIndependientes(unittest.TestCase):
    """Los 4 archivos principales deben rastrearse de forma independiente:
    que uno se confirme ocupado no debe afectar el estado de los otros."""

    def setUp(self):
        self.monitor = FileLockMonitor(
            archivos={
                "registro_maestro": "C:\\ficticio\\rm.xlsx",
                "provisiones": "C:\\ficticio\\prov.xlsx",
                "bbdd_clientes_cm": "C:\\ficticio\\bbdd.xlsx",
                "administradores_contactos": "C:\\ficticio\\contactos.xlsx",
            },
            umbral_confirmar_ocupado=2,
        )

    def test_solo_el_archivo_bloqueado_se_confirma_ocupado(self):
        def resultado_por_ruta(ruta):
            return "prov.xlsx" in ruta

        with patch.object(self.monitor, '_esta_bloqueado_ahora', side_effect=lambda ruta: resultado_por_ruta(ruta)):
            self.monitor.tick()
            self.monitor.tick()

        estados = self.monitor.obtener_estados()
        self.assertEqual(estados, {
            "registro_maestro": False,
            "provisiones": True,
            "bbdd_clientes_cm": False,
            "administradores_contactos": False,
        })

    def test_las_cuatro_claves_estan_presentes_desde_el_inicio(self):
        estados = self.monitor.obtener_estados()
        self.assertEqual(set(estados.keys()), {
            "registro_maestro", "provisiones", "bbdd_clientes_cm", "administradores_contactos",
        })
        self.assertTrue(all(v is False for v in estados.values()))


class TestFileLockMonitorIgnoraGuardadoPropio(unittest.TestCase):
    """El propio guardado de la app (DataManager.is_app_saving) no debe
    hacer avanzar los contadores de confirmacion, aunque el archivo
    aparezca momentaneamente bloqueado durante ese guardado."""

    def setUp(self):
        self.monitor = FileLockMonitor(
            archivos={"archivo": "C:\\ruta\\ficticia.xlsx"},
            umbral_confirmar_ocupado=2,
        )
        self.dm = DataManager()
        self.dm.is_app_saving = False

    def tearDown(self):
        self.dm.is_app_saving = False

    def test_bloqueo_durante_guardado_propio_no_se_confirma(self):
        self.dm.is_app_saving = True
        self.dm.save_timestamp = time.time()

        with patch.object(self.monitor, '_esta_bloqueado_ahora', return_value=True):
            # Aunque el umbral es 2, ambos sondeos caen dentro de la
            # ventana de silencio del guardado propio: nunca deben contarse.
            self.monitor.tick()
            self.monitor.tick()

        self.assertFalse(self.monitor.esta_ocupado("archivo"),
                          "Fallo: un bloqueo detectado durante la ventana de guardado propio no debe confirmarse como ocupado.")

    def test_deja_de_ignorar_una_vez_terminada_la_ventana_de_silencio(self):
        self.dm.is_app_saving = True
        # save_timestamp ya vencido (fuera de la ventana de silencio de 10s).
        self.dm.save_timestamp = time.time() - 999

        with patch.object(self.monitor, '_esta_bloqueado_ahora', return_value=True):
            self.monitor.tick()
            self.monitor.tick()

        self.assertTrue(self.monitor.esta_ocupado("archivo"),
                         "Fallo: fuera de la ventana de silencio, un bloqueo persistente sí debe confirmarse aunque is_app_saving siga en True.")


if __name__ == '__main__':
    unittest.main(verbosity=2)
