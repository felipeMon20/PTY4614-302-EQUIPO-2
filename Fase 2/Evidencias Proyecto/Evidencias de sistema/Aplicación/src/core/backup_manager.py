import os
import uuid
import json
import shutil
import logging
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal
import config.settings

logger = logging.getLogger(__name__)

# Nombres de atributos de config.settings que apuntan a archivos locales
# maestros del sistema. Se listan de forma explicita (nunca por escaneo de
# carpetas) para que un snapshot nunca incluya accidentalmente data/backups,
# data/backup_auto, data/backupManual, data/temp ni codigo fuente.
_CLAVES_ARCHIVOS_MAESTROS = [
    "EXCEL_PATH",
    "DELETED_LOG_EXCEL_PATH",
    "PROVISION_EXCEL_PATH",
    "INSTALACIONES_PATH",
    "RM_JAVI_PATH",
    "POWERBI_EXCEL_PATH",
    "CONTACTOS_EXCEL_PATH",
    "CORREOS_EXCEL_PATH",
]


def _rutas_snapshot():
    # El historial que se respalda es LOG_CSV_PATH (LogApp.csv, el oficial),
    # no LOG_EXCEL_PATH (el .xlsx legado, que ya no forma parte del snapshot).
    rutas = []
    for clave in _CLAVES_ARCHIVOS_MAESTROS:
        valor = getattr(config.settings, clave, "")
        if valor:
            rutas.append(valor)

    log_csv_path = getattr(config.settings, "LOG_CSV_PATH", "")
    if log_csv_path:
        rutas.append(log_csv_path)

    return rutas


class BackupManager:
    """Snapshots completos del sistema (automatico semanal y manual).

    Es un mecanismo independiente y complementario a ExcelWriter._crear_backup:
    _crear_backup respalda UN archivo justo antes de modificarlo (proteccion
    transaccional de grano fino); BackupManager respalda TODOS los archivos
    maestros de una vez, como una foto completa del sistema en un momento
    dado (proteccion de desastre / punto de restauracion). No se mezclan.
    """

    def __init__(self):
        self.auto_dir = os.path.join(os.getcwd(), 'data', 'backup_auto')
        self.manual_dir = os.path.join(os.getcwd(), 'data', 'backupManual')
        self.state_file = os.path.join(os.getcwd(), 'data', '.last_auto_backup.json')

    # ------------------------------------------------------------------
    # Nucleo comun
    # ------------------------------------------------------------------
    def _crear_snapshot(self, destino_base):
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        snapshot_dir_tmp = os.path.join(destino_base, f".tmp_{timestamp}_{uuid.uuid4().hex[:8]}")
        snapshot_dir_final = os.path.join(destino_base, timestamp)

        resultado = {"copiados": [], "omitidos": [], "fallidos": [], "carpeta": None}

        try:
            os.makedirs(snapshot_dir_tmp, exist_ok=True)
        except Exception as e:
            logger.error(f"No se pudo crear el directorio de snapshot: {e}")
            resultado["error_fatal"] = str(e)
            return resultado

        for ruta_origen in _rutas_snapshot():
            nombre = os.path.basename(ruta_origen)
            if not os.path.exists(ruta_origen):
                resultado["omitidos"].append(nombre)
                continue
            try:
                shutil.copy2(ruta_origen, os.path.join(snapshot_dir_tmp, nombre))
                resultado["copiados"].append(nombre)
            except Exception as e:
                logger.warning(f"Fallo al copiar '{nombre}' en el snapshot: {e}")
                resultado["fallidos"].append(nombre)

        if not resultado["copiados"]:
            try:
                shutil.rmtree(snapshot_dir_tmp, ignore_errors=True)
            except Exception:
                pass
            resultado["error_fatal"] = "No se pudo copiar ningun archivo maestro (todos fallaron o no existen)."
            logger.error(resultado["error_fatal"])
            return resultado

        try:
            os.replace(snapshot_dir_tmp, snapshot_dir_final)
        except Exception as e:
            logger.error(f"No se pudo finalizar el snapshot: {e}")
            resultado["error_fatal"] = str(e)
            return resultado

        resultado["carpeta"] = snapshot_dir_final
        logger.info(
            f"Snapshot completo creado en '{snapshot_dir_final}': "
            f"{len(resultado['copiados'])} copiados, {len(resultado['fallidos'])} fallidos, "
            f"{len(resultado['omitidos'])} omitidos."
        )
        return resultado

    def _aplicar_retencion(self, destino_base, maximo):
        if not os.path.exists(destino_base):
            return
        carpetas = [
            os.path.join(destino_base, d) for d in os.listdir(destino_base)
            if os.path.isdir(os.path.join(destino_base, d)) and not d.startswith(".")
        ]
        carpetas.sort(key=os.path.getmtime)
        while len(carpetas) > maximo:
            mas_vieja = carpetas.pop(0)
            try:
                shutil.rmtree(mas_vieja, ignore_errors=True)
                logger.info(f"Snapshot antiguo eliminado por retencion: '{mas_vieja}'.")
            except Exception as e:
                logger.warning(f"No se pudo eliminar el snapshot antiguo '{mas_vieja}': {e}")

    # ------------------------------------------------------------------
    # Backup manual: bajo demanda, sin retencion automatica
    # ------------------------------------------------------------------
    def crear_backup_manual(self):
        os.makedirs(self.manual_dir, exist_ok=True)
        return self._crear_snapshot(self.manual_dir)

    # ------------------------------------------------------------------
    # Backup automatico semanal: al iniciar, los viernes, maximo 1 por semana
    # ------------------------------------------------------------------
    def _semana_actual(self):
        iso = datetime.now().isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"

    def _leer_estado(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _guardar_estado(self, semana):
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {"ultima_semana_respaldada": semana, "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                    f, indent=4
                )
        except Exception as e:
            logger.warning(f"No se pudo guardar el estado del backup automatico: {e}")

    def backup_semanal_pendiente(self):
        """True si hoy es viernes y todavia no existe un backup automatico
        exitoso registrado para la semana ISO actual."""
        if datetime.now().weekday() != 4:  # 0=lunes ... 4=viernes
            return False
        estado = self._leer_estado()
        return estado.get("ultima_semana_respaldada") != self._semana_actual()

    def crear_backup_automatico_si_corresponde(self):
        if not self.backup_semanal_pendiente():
            return None
        os.makedirs(self.auto_dir, exist_ok=True)
        resultado = self._crear_snapshot(self.auto_dir)
        if resultado.get("copiados"):
            self._guardar_estado(self._semana_actual())
            self._aplicar_retencion(self.auto_dir, 5)
        return resultado


class BackupWorker(QThread):
    """Ejecuta un snapshot completo (automatico o manual) fuera del hilo
    principal de Qt, para no congelar la interfaz mientras se copian los
    archivos maestros."""

    finished_signal = pyqtSignal(dict)

    def __init__(self, modo="auto"):
        super().__init__()
        self.modo = modo  # "auto" o "manual"

    def run(self):
        try:
            manager = BackupManager()
            if self.modo == "manual":
                resultado = manager.crear_backup_manual()
            else:
                resultado = manager.crear_backup_automatico_si_corresponde()
            self.finished_signal.emit(resultado if resultado is not None else {})
        except Exception as e:
            logger.error(f"Fallo inesperado en BackupWorker ({self.modo}): {e}")
            self.finished_signal.emit({"error_fatal": str(e)})
