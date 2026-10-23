"""Hilos y estado compartido de la actualización. Se importa en el arranque, así que
solo usa PyQt6.QtCore; la lógica (src/services/actualizador_service.py) se carga
dentro de los hilos para no restarle tiempo a la animación de inicio."""
from datetime import datetime

from PyQt6.QtCore import QObject, QSettings, QThread, pyqtSignal

CLAVE_VERSION_AVISADA = "actualizacion_version_avisada"


class _HiloChequeo(QThread):
    resultado = pyqtSignal(object)

    def run(self):
        try:
            from src.services import actualizador_service
            self.resultado.emit(actualizador_service.leer_manifiesto())
        except Exception as e:
            print(f"[ACTUALIZADOR] No se pudo revisar la carpeta de actualizaciones: {e}")
            self.resultado.emit(None)


class HiloDescarga(QThread):
    progreso = pyqtSignal(str, int, str)
    listo = pyqtSignal(str, str)
    fallo = pyqtSignal(str)

    def __init__(self, manifiesto):
        super().__init__()
        self._manifiesto = manifiesto
        self._cancelar = False

    def cancelar(self):
        self._cancelar = True

    def run(self):
        from src.services import actualizador_service as servicio
        ultimo = [None]

        def avanzar(fase, porcentaje, detalle):
            if (fase, porcentaje) != ultimo[0]:
                ultimo[0] = (fase, porcentaje)
                self.progreso.emit(fase, porcentaje, detalle)

        try:
            temporal, raiz = servicio.descargar_y_extraer(self._manifiesto, avanzar, lambda: self._cancelar)
            self.listo.emit(temporal, raiz)
        except servicio.ActualizacionCancelada:
            self.fallo.emit("")
        except servicio.ActualizacionError as e:
            self.fallo.emit(str(e))
        except Exception as e:
            self.fallo.emit(f"No se pudo descargar la actualización: {e}")


class ControlActualizacion(QObject):
    """Resultado de la última revisión; lo leen el aviso del arranque y Configuración."""
    cambio = pyqtSignal()
    _unica = None

    @classmethod
    def instancia(cls):
        if cls._unica is None:
            cls._unica = cls()
        return cls._unica

    def __init__(self):
        super().__init__()
        self.manifiesto = None
        self.revision_en_curso = False
        self.ultima_revision = None
        self._hilo = None

    @staticmethod
    def _ajustes():
        return QSettings("VolvoApp", "Dashboard")

    def buscar(self):
        if self.revision_en_curso:
            return
        self.revision_en_curso = True
        self._hilo = _HiloChequeo()
        self._hilo.resultado.connect(self._al_resultado)
        self._hilo.start()
        self.cambio.emit()

    def _al_resultado(self, manifiesto):
        self.manifiesto = manifiesto
        self.revision_en_curso = False
        self.ultima_revision = datetime.now()
        self.cambio.emit()

    @property
    def version_instalada(self):
        import config.settings
        return config.settings.APP_VERSION

    def disponible(self):
        if self.manifiesto is None:
            return False
        from src.services.actualizador_service import es_mas_nueva
        return es_mas_nueva(self.manifiesto["version"], self.version_instalada)

    def debe_avisar(self):
        """Una sola vez por versión publicada, aunque la persona no responda."""
        if not self.disponible():
            return False
        return self._ajustes().value(CLAVE_VERSION_AVISADA, "", type=str) != self.manifiesto["version"]

    def marcar_avisada(self):
        self._ajustes().setValue(CLAVE_VERSION_AVISADA, self.manifiesto["version"])
