import os
import threading
import logging
import openpyxl

logger = logging.getLogger(__name__)


class WorkbookCache:
    """Cachea Workbooks de openpyxl en memoria, uno por ruta absoluta, para
    evitar repetir load_workbook() (costoso en archivos grandes, ver
    docs/12) en guardados consecutivos sobre el mismo archivo dentro de la
    misma sesion.

    Singleton independiente (mismo patron __new__ que DataManager), pero sin
    fusionarse con el: DataManager conoce DataFrames para la UI, este
    servicio solo conoce Workbooks de openpyxl para escritura. Ninguna otra
    parte de la app debe tocar el Workbook cacheado directamente -- solo
    ExcelWriter.

    Vigencia: mtime + tamaño del archivo en disco (sin hash, ver analisis de
    rendimiento -- hashear el contenido cuesta lo mismo que evitar). No
    persiste entre ejecuciones: es un diccionario en memoria de este
    proceso, se pierde al cerrar la app.
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._inicializado = False
                    cls._instance = obj
        return cls._instance

    def __init__(self):
        if self._inicializado:
            return
        # clave (ruta normalizada) -> {'wb': Workbook, 'fingerprint': (mtime, size)}
        self._entradas = {}
        self._entradas_lock = threading.Lock()
        # clave -> threading.Lock(), uno por ruta. Protege el ciclo completo
        # de escritura (obtener -> modificar -> save -> copy2 -> fingerprint),
        # no solo la entrega del Workbook -- ver ExcelWriter.
        self._locks_por_ruta = {}
        self._inicializado = True

    @staticmethod
    def instancia():
        return WorkbookCache()

    @staticmethod
    def _normalizar(ruta):
        return os.path.normcase(os.path.abspath(ruta))

    def lock_para(self, ruta):
        """Devuelve el threading.Lock exclusivo de esta ruta (se crea una
        vez, se reutiliza siempre). Un guardado sobre otra ruta usa otro
        Lock y no queda bloqueado por este."""
        clave = self._normalizar(ruta)
        with self._entradas_lock:
            lock = self._locks_por_ruta.get(clave)
            if lock is None:
                lock = threading.Lock()
                self._locks_por_ruta[clave] = lock
            return lock

    def _fingerprint_actual(self, ruta):
        try:
            stat = os.stat(ruta)
            return (stat.st_mtime, stat.st_size)
        except OSError:
            return None

    def esta_vigente(self, ruta):
        """True si hay un Workbook cacheado para esta ruta y su fingerprint
        coincide con el estado actual del archivo en disco. Debe llamarse
        con el lock_para(ruta) ya tomado por el llamador (mismo criterio que
        obtener_workbook)."""
        clave = self._normalizar(ruta)
        entrada = self._entradas.get(clave)
        if entrada is None:
            return False
        actual = self._fingerprint_actual(ruta)
        return actual is not None and actual == entrada['fingerprint']

    def obtener_workbook(self, ruta):
        """Devuelve el Workbook vigente para esta ruta, cacheado o recien
        cargado. El llamador debe tener tomado lock_para(ruta) antes de
        invocar esto (no es thread-safe por si solo)."""
        clave = self._normalizar(ruta)
        if self.esta_vigente(ruta):
            logger.info(f"WorkbookCache: reutilizando Workbook en memoria para '{os.path.basename(ruta)}'.")
            return self._entradas[clave]['wb']

        if clave in self._entradas:
            self._cerrar_entrada(self._entradas.pop(clave))

        logger.info(f"WorkbookCache: cargando Workbook fresco para '{os.path.basename(ruta)}'.")
        wb = openpyxl.load_workbook(ruta)
        self._entradas[clave] = {'wb': wb, 'fingerprint': self._fingerprint_actual(ruta)}
        return wb

    def actualizar_fingerprint(self, ruta):
        """Se llama SOLO despues de que el archivo real (target_file) ya
        quedo escrito en disco (shutil.copy2 final ya ejecutado), para que
        el propio guardado no invalide su propia entrada en el siguiente
        ciclo."""
        clave = self._normalizar(ruta)
        entrada = self._entradas.get(clave)
        if entrada is None:
            return
        actual = self._fingerprint_actual(ruta)
        if actual is not None:
            entrada['fingerprint'] = actual

    def invalidar(self, ruta):
        """Descarta el Workbook cacheado porque el archivo cambio por fuera
        de la app (Watchdog confirmo un cambio genuino, o el chequeo pasivo
        de mtime/tamaño no coincidio). El siguiente obtener_workbook() carga
        de nuevo desde disco."""
        clave = self._normalizar(ruta)
        with self._entradas_lock:
            entrada = self._entradas.pop(clave, None)
        if entrada is not None:
            logger.info(f"WorkbookCache: invalidado '{os.path.basename(ruta)}' (cambio externo detectado).")
            self._cerrar_entrada(entrada)

    def descartar(self, ruta):
        """Descarta el Workbook cacheado porque la propia app no confia mas
        en su estado (fallo durante el guardado, o el Workbook pudo quedar
        con mutaciones parciales sin persistir de un intento anterior fallido).
        Mismo efecto que invalidar(); se mantiene como metodo separado
        porque el motivo es distinto (interno vs. externo) y puede ser util
        distinguirlo en logs."""
        clave = self._normalizar(ruta)
        with self._entradas_lock:
            entrada = self._entradas.pop(clave, None)
        if entrada is not None:
            logger.info(f"WorkbookCache: descartado '{os.path.basename(ruta)}' (error o mutacion no confiable).")
            self._cerrar_entrada(entrada)

    @staticmethod
    def _cerrar_entrada(entrada):
        try:
            entrada['wb'].close()
        except Exception:
            pass

    def tiene_cache(self, ruta):
        """Solo para inspeccion/diagnostico manual (ej. piloto). No la usa
        ExcelWriter."""
        clave = self._normalizar(ruta)
        return clave in self._entradas
