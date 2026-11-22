"""Registro de la aplicación en logs/sistema.log.

Reúne tres cosas: el log rotativo, el manejo de errores que ningún bloque
try/except atrapó, y una marca de sesión que sirve de canario: si al abrir la
app queda la marca de la sesión anterior, esa sesión no cerró con normalidad.
"""
import logging
import os
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler

from config.directorio_app import BASE_DIR

DIR_LOGS = os.path.join(BASE_DIR, 'logs')
RUTA_LOG = os.path.join(DIR_LOGS, 'sistema.log')
RUTA_MARCA_SESION = os.path.join(BASE_DIR, 'data', '.sesion_activa')

TAMANO_MAXIMO_LOG = 1_000_000
COPIAS_LOG = 3
ESPERA_AVISO_SEGUNDOS = 15
ESPERA_REPETIDO_SEGUNDOS = 5

logger = logging.getLogger(__name__)


def configurar_logging():
    """Deja el logger raíz escribiendo en un archivo que rota al llegar al
    tope. Si ya hay handlers (por ejemplo los de la suite de pruebas) no hace nada."""
    raiz = logging.getLogger()
    if raiz.handlers:
        return
    os.makedirs(DIR_LOGS, exist_ok=True)
    handlers = [RotatingFileHandler(RUTA_LOG, maxBytes=TAMANO_MAXIMO_LOG, backupCount=COPIAS_LOG, encoding='utf-8')]
    # En el ejecutable sin consola no hay stderr
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=handlers)


# ---------------------------------------------------------------------------
# Errores no atrapados
# ---------------------------------------------------------------------------
_ultimo_error = ("", 0.0)
_ultimo_aviso = 0.0
_aviso_abierto = False
_puente = None


def _registrar_excepcion(tipo, valor, traza):
    global _ultimo_error
    if issubclass(tipo, KeyboardInterrupt):
        sys.__excepthook__(tipo, valor, traza)
        return
    clave = f"{tipo.__name__}: {valor}"
    ahora = time.monotonic()
    repetido = clave == _ultimo_error[0] and ahora - _ultimo_error[1] < ESPERA_REPETIDO_SEGUNDOS
    _ultimo_error = (clave, ahora)
    if repetido:
        return
    logger.critical("Error no controlado: %s", clave, exc_info=(tipo, valor, traza))
    if _puente is not None:
        _puente.error.emit(clave)


def _registrar_excepcion_hilo(args):
    _registrar_excepcion(args.exc_type, args.exc_value, args.exc_traceback)


def instalar_manejo_de_errores():
    """Sin esto, una excepción dentro de un slot de PyQt6 cierra la aplicación sin
    dejar rastro. Con esto se registra en el log, se avisa a la persona y la app
    sigue abierta. Debe llamarse con la QApplication ya creada, en el hilo principal."""
    global _puente
    from PyQt6.QtCore import QObject, Qt, pyqtSignal

    class _Puente(QObject):
        error = pyqtSignal(str)

    _puente = _Puente()
    _puente.error.connect(_avisar_a_la_persona, Qt.ConnectionType.QueuedConnection)
    sys.excepthook = _registrar_excepcion
    threading.excepthook = _registrar_excepcion_hilo


def _avisar_a_la_persona(detalle):
    global _ultimo_aviso, _aviso_abierto
    ahora = time.monotonic()
    if _aviso_abierto or ahora - _ultimo_aviso < ESPERA_AVISO_SEGUNDOS:
        return
    _aviso_abierto = True
    try:
        from PyQt6.QtWidgets import QMessageBox
        caja = QMessageBox()
        caja.setIcon(QMessageBox.Icon.Warning)
        caja.setWindowTitle("Error inesperado")
        caja.setText("Ocurrió un error inesperado. Puedes seguir usando la aplicación; "
                     "si algo no responde como esperas, ciérrala y ábrela de nuevo.")
        caja.setInformativeText(f"El detalle quedó guardado en logs/sistema.log.\n\n{detalle}")
        caja.exec()
    except Exception:
        logger.exception("No se pudo mostrar el aviso de error")
    finally:
        _aviso_abierto = False
        _ultimo_aviso = time.monotonic()


# ---------------------------------------------------------------------------
# Congelamientos de la interfaz
# ---------------------------------------------------------------------------
UMBRAL_CONGELADO_SEGUNDOS = 1.5


def instalar_vigia_de_congelamientos():
    """Si la interfaz no atiende eventos por más de UMBRAL_CONGELADO_SEGUNDOS, deja en el log qué estaba haciendo
    el hilo principal (una sola vez por congelamiento) para poder ubicar el origen. Llamar desde el hilo principal."""
    import traceback
    from PyQt6.QtCore import QTimer

    principal = threading.get_ident()
    latido = [time.monotonic()]
    reloj = QTimer()
    reloj.setInterval(250)
    reloj.timeout.connect(lambda: latido.__setitem__(0, time.monotonic()))
    reloj.start()

    def vigilar():
        avisado = 0.0
        while True:
            time.sleep(0.5)
            parado = time.monotonic() - latido[0]
            if parado < UMBRAL_CONGELADO_SEGUNDOS:
                avisado = 0.0
                continue
            if avisado == 0.0 or parado - avisado > 5:
                avisado = parado
                marco = sys._current_frames().get(principal)
                pila = "".join(traceback.format_stack(marco)[-12:]) if marco else "sin pila"
                # INFO y no WARNING: queda en el log para ubicar el origen, pero no aparece como alerta al usuario
                logger.info("Interfaz sin responder %.1f s. El hilo principal estaba en:\n%s", parado, pila)

    threading.Thread(target=vigilar, name="vigia-congelamientos", daemon=True).start()
    return reloj


# ---------------------------------------------------------------------------
# Canario de sesión
# ---------------------------------------------------------------------------
def iniciar_sesion():
    """Registra el inicio. Si la marca de la sesión anterior sigue en disco, esa
    sesión terminó sin pasar por cerrar_sesion (cierre forzado, caída, corte)."""
    import config.settings
    try:
        if os.path.exists(RUTA_MARCA_SESION):
            with open(RUTA_MARCA_SESION, 'r', encoding='utf-8') as f:
                previa = f.read().strip()
            logger.warning("La sesión anterior terminó sin cierre normal (%s)", previa or "sin detalle")
        os.makedirs(os.path.dirname(RUTA_MARCA_SESION), exist_ok=True)
        with open(RUTA_MARCA_SESION, 'w', encoding='utf-8') as f:
            f.write(f"iniciada {datetime.now():%Y-%m-%d %H:%M:%S}, versión {config.settings.APP_VERSION}")
    except OSError as e:
        logger.warning("No se pudo escribir la marca de sesión: %s", e)
    modo = "datos de prueba" if config.settings.DATOS_DE_PRUEBA else "datos reales"
    logger.info("Sesión iniciada: versión %s, %s", config.settings.APP_VERSION, modo)


def cerrar_sesion():
    try:
        if os.path.exists(RUTA_MARCA_SESION):
            os.remove(RUTA_MARCA_SESION)
    except OSError as e:
        logger.warning("No se pudo quitar la marca de sesión: %s", e)
    logger.info("Sesión cerrada con normalidad")
