import hashlib
import os
import threading
import time
from PyQt6.QtCore import pyqtSignal, QThread
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from src.core.data_manager import DataManager

# Ventana desde el último guardado propio (DataManager.save_timestamp) en la
# que se ignoran los eventos del archivo. OneDrive suele generar eventos
# tardíos tras subir el archivo, cuando is_app_saving ya volvió a False.
VENTANA_SILENCIO_GUARDADO_SEGUNDOS = 30
# Tope para un guardado todavía en curso (is_app_saving=True), por si la
# bandera quedara pegada tras un error.
MAX_DURACION_GUARDADO_SEGUNDOS = 300
# Silencio del archivo antes de avisar el cambio (agrupa eventos repetidos).
ESPERA_ESTABILIZAR_SEGUNDOS = 1.5

class ExcelHandler(FileSystemEventHandler):
    def __init__(self, filename, callback, ruta=None):
        super().__init__()
        self.filename = filename
        self.callback = callback
        self.ruta = ruta
        self._timer = None
        self._lock = threading.Lock()
        self._firma = self._calcular_firma()

    def _calcular_firma(self):
        """Huella del contenido del archivo; None si no se puede leer. Sirve
        para distinguir un cambio real de un simple 'toque' de OneDrive tras
        subir el archivo (mismo contenido, fecha distinta)."""
        if not self.ruta:
            return None
        try:
            with open(self.ruta, 'rb') as f:
                return hashlib.sha1(f.read()).hexdigest()
        except OSError:
            return None

    def on_modified(self, event):
        self._evento(event.is_directory, event.src_path)

    def on_created(self, event):
        self._evento(event.is_directory, event.src_path)

    def on_moved(self, event):
        # OneDrive/SharePoint reemplazan el archivo con un renombrado
        self._evento(event.is_directory, getattr(event, 'dest_path', ''))

    def _evento(self, es_directorio, ruta):
        if es_directorio or not ruta or not ruta.endswith(self.filename):
            return
        if self._silenciado():
            print(f"Watchdog ignorando cambio en {self.filename} (guardado propio hace menos de {VENTANA_SILENCIO_GUARDADO_SEGUNDOS}s).")
            self._programar(self._refrescar_firma)
            return
        # Un cambio suele producir varios eventos seguidos: se espera a que el
        # archivo deje de cambiar y se avisa una sola vez, sin descartar el último.
        self._programar(self._disparar)

    def _programar(self, accion):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(ESPERA_ESTABILIZAR_SEGUNDOS, accion)
            self._timer.daemon = True
            self._timer.start()

    def _refrescar_firma(self):
        """Tras un guardado propio, el contenido nuevo pasa a ser el de referencia."""
        self._firma = self._calcular_firma()

    @staticmethod
    def _silenciado():
        # Depende solo del tiempo desde el último guardado propio. Antes exigía
        # además is_app_saving=True, que ExcelWriter apaga apenas termina de
        # copiar, y los eventos tardíos pasaban como cambios externos.
        dm = DataManager()
        segundos_desde_guardado = time.time() - dm.save_timestamp
        guardado_en_curso = dm.is_app_saving and segundos_desde_guardado < MAX_DURACION_GUARDADO_SEGUNDOS
        return guardado_en_curso or segundos_desde_guardado < VENTANA_SILENCIO_GUARDADO_SEGUNDOS

    def _disparar(self):
        if self._silenciado():
            return
        firma = self._calcular_firma()
        if firma is not None and firma == self._firma:
            print(f"Watchdog ignorando {self.filename}: cambió la fecha pero no el contenido.")
            return
        self._firma = firma
        self.callback()

    def cancelar(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

class WatchdogThread(QThread):
    file_changed_signal = pyqtSignal()

    def __init__(self, watch_dir, filename):
        super().__init__()
        self.watch_dir = watch_dir
        self.filename = filename
        self.observer = None

    def run(self):
        event_handler = self._handler = ExcelHandler(
            self.filename, self._emit_signal, os.path.join(self.watch_dir, self.filename))
        self.observer = Observer()
        self.observer.schedule(event_handler, self.watch_dir, recursive=False)
        self.observer.start()
        
        try:
            while True:
                time.sleep(1)
        except Exception:
            self.observer.stop()
        self.observer.join()

    def _emit_signal(self):
        self.file_changed_signal.emit()

    def stop(self):
        handler = getattr(self, '_handler', None)
        if handler is not None:
            handler.cancelar()
        if self.observer:
            self.observer.stop()
            self.observer.join()