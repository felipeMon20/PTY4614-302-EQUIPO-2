import datetime
import gc
import sys
import os
import time
import traceback
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QPixmap, QIcon, QImage, QPainter
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
import PyQt6.QtWebEngineWidgets 
from src.ui.pantalla_inicio import PantallaInicio

INTERVALO_GIL_ARRANQUE = 0.001
INTERVALO_GIL_NORMAL = 0.005
ESPERA_MAXIMA_IMPORTS_MS = 1500

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def load_stylesheet(app):
    style_path = get_resource_path(os.path.join('src', 'assets', 'styles.qss'))
    if os.path.exists(style_path):
        with open(style_path, "r", encoding='utf-8') as f:
            app.setStyleSheet(f.read())

def create_white_background_icon(image_path):
    if not os.path.exists(image_path):
        return QIcon()
    original_pixmap = QPixmap(image_path)
    if original_pixmap.isNull():
        return QIcon()

    size = max(original_pixmap.width(), original_pixmap.height())
    padded_size = int(size * 1.2) 
    
    background = QImage(padded_size, padded_size, QImage.Format.Format_ARGB32_Premultiplied)
    background.fill(Qt.GlobalColor.white) 

    painter = QPainter(background)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    
    x = int((padded_size - original_pixmap.width()) / 2)
    y = int((padded_size - original_pixmap.height()) / 2)
    
    painter.drawPixmap(x, y, original_pixmap)
    painter.end()

    return QIcon(QPixmap.fromImage(background))

def _calentar_pandas():
    """pandas importa sus lectores y conversores la primera vez que se usan;
    se fuerzan aquí, antes de que empiece la animación."""
    import io
    import pandas as pd
    import openpyxl  # noqa: F401
    from src.core.dataframe_formatter import DataFrameFormatter  # noqa: F401
    from src.core.excel_writer import migrar_historial_legacy  # noqa: F401
    df = pd.read_csv(io.StringIO("A,B\n01-02-2024,x\n"), dtype=str, keep_default_na=False)
    fechas = pd.to_datetime(df["A"].str.split().str[0], dayfirst=True, format='mixed', errors='coerce')
    fechas.dt.strftime('%d-%m-%Y')


class PrecargaDatosThread(QThread):
    """Lee y limpia el archivo principal mientras corre la animación. Si
    falla, MainWindow vuelve a intentarlo y muestra su propia pantalla de
    error."""

    # Importar pandas retiene el GIL en tramos largos: la animación arranca
    # recién cuando esto termina, con la ventana mostrando solo el fondo
    importado = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.resultado = None

    def run(self):
        try:
            import config.settings
            from src.core.data_manager import leer_datos_principales
            _calentar_pandas()
            self.importado.emit()
            ruta = config.settings.EXCEL_PATH
            mtime = os.path.getmtime(ruta)
            self.resultado = (leer_datos_principales(ruta), ruta, mtime)
        except Exception as e:
            print(f"Precarga de arranque no disponible: {e}")
            self.importado.emit()


class CustomSplashScreen(PantallaInicio):
    """La animación corre en el hilo de la interfaz y la lectura de datos en
    PrecargaDatosThread. MainWindow se construye recién cuando la animación
    terminó y los datos están leídos: su load_data_async toma la precarga del
    DataManager y no vuelve a leer el archivo."""

    def __init__(self):
        super().__init__(get_resource_path(os.path.join('src', 'assets')))
        self.main_window = None
        self._precarga = PrecargaDatosThread()
        self._precarga.importado.connect(self._iniciar_animacion)
        self._precarga.finished.connect(self._on_precarga_lista)

    def start_animation(self):
        # El recolector de basura de Python también congela todos los hilos
        # al recorrer los DataFrames recién leídos; se reactiva al terminar
        gc.disable()
        QTimer.singleShot(30, self._precarga.start)
        QTimer.singleShot(ESPERA_MAXIMA_IMPORTS_MS, self._iniciar_animacion)

    def _iniciar_animacion(self):
        if not self.animando():
            self.iniciar()

    def _on_precarga_lista(self):
        sys.setswitchinterval(INTERVALO_GIL_NORMAL)
        self._iniciar_animacion()
        if self._precarga.resultado is not None:
            from src.core.data_manager import DataManager
            DataManager().guardar_precarga_principal(*self._precarga.resultado)
        self.terminar(self._abrir_aplicacion)

    def _abrir_aplicacion(self):
        gc.enable()
        try:
            from src.ui.main_window import MainWindow
            self.main_window = MainWindow()
            self.main_window.show()
        except Exception as e:
            self._manejar_error_fatal(e)

    def _manejar_error_fatal(self, e):
        gc.enable()
        self.detener()
        self.close()

        # --- CAPTURA Y REGISTRO DE ERROR CRÍTICO EN LOGS ---
        error_detallado = traceback.format_exc()
        print(error_detallado)

        try:
            log_dir = os.path.join(os.getcwd(), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, 'sistema.log'), 'a', encoding='utf-8') as log_file:
                log_file.write(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] - ERROR CRÍTICO EN ARRANQUE:\n{error_detallado}\n")
        except Exception:
            pass

        # Mostramos el error exacto en pantalla para que la contraparte comercial (o tú) lo vean de inmediato
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setWindowTitle("Error Crítico de Inicialización")
        msg.setText("La aplicación encontró un fallo fatal al arrancar.")
        msg.setInformativeText(str(e))
        msg.setDetailedText(error_detallado)
        msg.exec()
        sys.exit(1)

NOMBRE_INSTANCIA_UNICA = "gestor.sscc.gestion.instancia"


def _traer_al_frente():
    for ventana in QApplication.topLevelWidgets():
        if ventana.isVisible() and ventana.parentWidget() is None:
            if ventana.isMinimized():
                ventana.showNormal()
            ventana.raise_()
            ventana.activateWindow()
            return


def _asegurar_instancia_unica():
    """Devuelve el servidor local que identifica a esta instancia, o None si ya
    había otra abierta (a la que se avisa para que se muestre)."""
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    socket = QLocalSocket()
    socket.connectToServer(NOMBRE_INSTANCIA_UNICA)
    if socket.waitForConnected(500):
        socket.write(b"mostrar")
        socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return None
    # Si nadie respondió, un servidor huérfano de un cierre abrupto se descarta
    QLocalServer.removeServer(NOMBRE_INSTANCIA_UNICA)
    servidor = QLocalServer(QApplication.instance())
    if not servidor.listen(NOMBRE_INSTANCIA_UNICA):
        return servidor  # sin control de instancia única, pero la app sigue abriendo

    def _atender():
        conexion = servidor.nextPendingConnection()
        if conexion is not None:
            conexion.readyRead.connect(lambda: (conexion.readAll(), _traer_al_frente()))
            conexion.disconnected.connect(conexion.deleteLater)
    servidor.newConnection.connect(_atender)
    return servidor


def main():
    # 1. Le decimos a Windows que ignore el modo oscuro para esta app
    os.environ["QT_QPA_PLATFORM"] = "windows:darkmode=0"

    from src.theme.ui_scale import aplicar_escala_al_entorno
    aplicar_escala_al_entorno()

    app = QApplication(sys.argv)

    # Una sola instancia: si ya hay una abierta se la trae al frente y esta se cierra
    servidor_unico = _asegurar_instancia_unica()
    if servidor_unico is None:
        return

    # 2. Estilo "Fusion"; la paleta (clara u oscura, la última que usó la
    # persona) la fija GestorTema junto con styles.qss
    app.setStyle("Fusion")
    load_stylesheet(app)
    from src.theme.tema import GestorTema
    GestorTema.instancia().inicializar(app)
    # Los QMessageBox de toda la app se muestran como tarjetas modernas
    from src.ui.mensajes import instalar as instalar_mensajes
    instalar_mensajes()

    # Primer arranque o carpeta movida: ofrece buscar y configurar las rutas solo
    from src.ui.asistente_rutas import revisar_rutas_al_arrancar
    if revisar_rutas_al_arrancar():
        return

    logo_path = get_resource_path(os.path.join('src', 'assets', 'splash_logo.png'))
    app_icon = create_white_background_icon(logo_path)
    
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
        try:
            import ctypes
            myappid = 'gestor.sscc.gestion.1'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass

    sys.setswitchinterval(INTERVALO_GIL_ARRANQUE)
    splash = CustomSplashScreen()
    splash.show()
    splash.start_animation()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()