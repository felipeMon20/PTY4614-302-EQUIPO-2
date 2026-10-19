"""
FileLockMonitor: deteccion conservadora de "archivo ocupado" para los 4
archivos principales (Registro Maestro, Provisiones, BBDD Clientes CM,
Administradores Contactos).

Limitacion conocida y aceptada a proposito (ver auditoria Fase 4): con el
stack actual (sin Microsoft Graph/Entra) es imposible distinguir de forma
fiable "Excel abierto por otro usuario" de "bloqueo transitorio de
sincronizacion de OneDrive/SharePoint". Este modulo NO intenta esa
distincion. Solo informa un booleano "ocupado/disponible" por archivo, y
reduce falsos positivos exigiendo que el bloqueo persista varios ciclos de
sondeo consecutivos antes de confirmarlo (ver umbral_confirmar_ocupado).

Esta fase es solo de deteccion: no bloquea la app, no muestra UI y no cierra
Excel. Ver CLAUDE.md / auditoria Fase 4 para el alcance completo.
"""
import os
import time
import logging
from PyQt6.QtCore import QObject, QThread, pyqtSignal

logger = logging.getLogger(__name__)

# Etiquetas visibles (mismo texto ya usado en Configuracion, Fase 1) para que
# quien reutilice este monitor en la UI (Fase 5+) no tenga que redefinirlas.
ETIQUETAS_ARCHIVOS_PRINCIPALES = {
    "registro_maestro": "Registro Maestro (RM)",
    "provisiones": "Proviciones",
    "bbdd_clientes_cm": "BBDD Clientes CM",
    "administradores_contactos": "Administradores contactos",
}

# Misma ventana de silencio (10s) que ya usa ExcelHandler en file_watcher.py
# para ignorar el propio guardado de la app. Se replica aqui (no se importa
# desde alli) porque en file_watcher.py esta hardcodeada inline, sin
# constante exportable.
VENTANA_SILENCIO_GUARDADO_SEGUNDOS = 10


def rutas_archivos_principales():
    """Lee las rutas vigentes de los 4 archivos principales desde
    config.settings en el momento de la llamada (no al importar este
    modulo), para reflejar siempre la configuracion actual."""
    import config.settings as settings
    return {
        "registro_maestro": settings.EXCEL_PATH,
        "provisiones": settings.PROVISION_EXCEL_PATH,
        "bbdd_clientes_cm": settings.POWERBI_EXCEL_PATH,
        "administradores_contactos": settings.CONTACTOS_EXCEL_PATH,
    }


class FileLockMonitor(QObject):
    """Mantiene el estado ocupado/disponible de un conjunto de archivos.

    Responsabilidad unica: decidir, con un criterio conservador, si cada
    archivo esta "ocupado" en este momento. No sabe (ni lo intenta saber)
    quien lo tiene abierto.

    Uso tipico:
        monitor = FileLockMonitor()      # usa las rutas de config.settings
        monitor.estado_cambiado.connect(...)
        monitor.tick()                   # una pasada de verificacion

    `tick()` es deliberadamente sincrono y sin sleep: quien decide la
    cadencia real (polling en un hilo, o llamadas directas en un test) es
    quien lo invoca. Ver FileLockMonitorThread para el uso en segundo plano.
    """

    # (clave_archivo, ocupado)
    estado_cambiado = pyqtSignal(str, bool)

    def __init__(self, archivos=None, umbral_confirmar_ocupado=3,
                 umbral_confirmar_disponible=2,
                 ventana_silencio_guardado=VENTANA_SILENCIO_GUARDADO_SEGUNDOS):
        super().__init__()

        # Si no se pasan rutas explicitas, se leen de config.settings en
        # este instante (no antes): permite testear con rutas de prueba sin
        # tocar la configuracion real, y en produccion siempre parte de la
        # configuracion vigente.
        self._archivos = dict(archivos) if archivos is not None else rutas_archivos_principales()

        if umbral_confirmar_ocupado < 1:
            raise ValueError("umbral_confirmar_ocupado debe ser >= 1")
        if umbral_confirmar_disponible < 1:
            raise ValueError("umbral_confirmar_disponible debe ser >= 1")

        self.umbral_confirmar_ocupado = umbral_confirmar_ocupado
        self.umbral_confirmar_disponible = umbral_confirmar_disponible
        self.ventana_silencio_guardado = ventana_silencio_guardado

        self._estados = {
            clave: {
                "ocupado_confirmado": False,
                "contador_bloqueado": 0,
                "contador_disponible": 0,
            }
            for clave in self._archivos
        }

    # ------------------------------------------------------------------
    # Deteccion de bajo nivel
    # ------------------------------------------------------------------
    def _esta_bloqueado_ahora(self, ruta):
        """Intento de apertura en modo lectura/escritura sin truncar ni
        modificar contenido ('r+b'): es el mismo tipo de operacion que ya
        dispara PermissionError en ExcelWriter/MainDataLoaderThread cuando
        Excel (u OneDrive sincronizando) tiene el archivo bloqueado. No
        distingue la causa del bloqueo -- ver limitaciones en el informe de
        la Fase 4.

        Si el archivo no existe o la ruta esta vacia, se considera "no
        bloqueado" (False): la ausencia del archivo es un problema distinto
        (configuracion/ruta invalida), fuera del alcance de este detector.
        """
        if not ruta or not os.path.exists(ruta):
            return False
        try:
            with open(ruta, 'r+b'):
                pass
            return False
        except PermissionError:
            return True
        except OSError:
            # Otros fallos de IO (ej. ruta de red momentaneamente
            # inalcanzable) se tratan igual que un bloqueo: mismo criterio
            # conservador, y quedan sujetos a la misma confirmacion por
            # persistencia antes de reportarse como ocupado.
            return True

    # ------------------------------------------------------------------
    # Maquina de confirmacion (evita falsos positivos transitorios)
    # ------------------------------------------------------------------
    def _debe_ignorar_por_guardado_propio(self):
        from src.core.data_manager import DataManager
        dm = DataManager()
        if not dm.is_app_saving:
            return False
        return (time.time() - dm.save_timestamp) < self.ventana_silencio_guardado

    def _procesar_archivo(self, clave, ruta):
        if self._debe_ignorar_por_guardado_propio():
            # Ciclo completamente omitido: no cuenta ni como bloqueo ni como
            # disponibilidad. El guardado propio de la app nunca debe hacer
            # avanzar (ni retroceder) los contadores de confirmacion.
            return

        estado = self._estados[clave]
        bloqueado_ahora = self._esta_bloqueado_ahora(ruta)

        if bloqueado_ahora:
            estado["contador_bloqueado"] += 1
            estado["contador_disponible"] = 0
            if not estado["ocupado_confirmado"] and estado["contador_bloqueado"] >= self.umbral_confirmar_ocupado:
                estado["ocupado_confirmado"] = True
                logger.info(f"FileLockMonitor: '{clave}' confirmado OCUPADO tras {estado['contador_bloqueado']} sondeos consecutivos.")
                self.estado_cambiado.emit(clave, True)
        else:
            estado["contador_disponible"] += 1
            estado["contador_bloqueado"] = 0
            if estado["ocupado_confirmado"] and estado["contador_disponible"] >= self.umbral_confirmar_disponible:
                estado["ocupado_confirmado"] = False
                logger.info(f"FileLockMonitor: '{clave}' vuelve a DISPONIBLE tras {estado['contador_disponible']} sondeos consecutivos.")
                self.estado_cambiado.emit(clave, False)

    def tick(self):
        """Una pasada de verificacion sobre los 4 archivos. Sincrono."""
        for clave, ruta in self._archivos.items():
            self._procesar_archivo(clave, ruta)

    # ------------------------------------------------------------------
    # Consultas de estado
    # ------------------------------------------------------------------
    def esta_ocupado(self, clave):
        return self._estados[clave]["ocupado_confirmado"]

    def obtener_estados(self):
        """{clave: bool_ocupado} para los 4 archivos monitoreados."""
        return {clave: info["ocupado_confirmado"] for clave, info in self._estados.items()}

    def claves_monitoreadas(self):
        return list(self._archivos.keys())


class FileLockMonitorThread(QThread):
    """Envoltorio de segundo plano para FileLockMonitor: llama a tick() de
    forma periodica sin bloquear el hilo principal de Qt. Mismo patron ya
    usado por WatchdogThread (src/core/file_watcher.py): un QThread con un
    bucle propio y un flag de parada.

    No se conecta todavia a ninguna parte de la UI (eso queda para una fase
    posterior); solo expone la senal estado_cambiado para quien lo use.
    """

    estado_cambiado = pyqtSignal(str, bool)

    def __init__(self, monitor=None, intervalo_segundos=5):
        super().__init__()
        self.monitor = monitor if monitor is not None else FileLockMonitor()
        self.intervalo_segundos = intervalo_segundos
        self._detener = False
        self.monitor.estado_cambiado.connect(self.estado_cambiado.emit)

    def run(self):
        # Sub-pasos de 0.1s para que stop() responda casi de inmediato en
        # vez de esperar hasta el proximo intervalo completo.
        pasos_por_intervalo = max(1, int(self.intervalo_segundos / 0.1))
        while not self._detener:
            self.monitor.tick()
            for _ in range(pasos_por_intervalo):
                if self._detener:
                    break
                time.sleep(0.1)

    def stop(self):
        self._detener = True
