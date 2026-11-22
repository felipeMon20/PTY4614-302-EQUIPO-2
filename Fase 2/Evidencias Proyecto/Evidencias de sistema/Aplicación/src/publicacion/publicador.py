"""Ventana para publicar una versión nueva de Gestor SSCC.

Hace el recorrido completo: pone el número de versión, compila con exe.bat, prueba que el
programa abre, sube el zip a la carpeta compartida con publicar.py, comprueba version.json
y limpia lo que dejó la compilación. Si algo falla antes de subir, no se publica nada y
config/settings.py vuelve a quedar como estaba. Se abre con Publicar_nueva_version.bat."""
import os
import re
import shutil
import subprocess
import sys
import time
from importlib.util import find_spec

CARPETA = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(CARPETA))
sys.path.insert(0, CARPETA)

from PyQt6.QtCore import QSettings, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPalette
from PyQt6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                             QPlainTextEdit, QProgressBar, QPushButton, QSizePolicy, QStackedWidget,
                             QVBoxLayout, QWidget)

import publicar

AJUSTES = os.path.join(RAIZ, "config", "settings.py")
DIST = os.path.join(RAIZ, "dist", "Gestor_SSCC")
EXE = os.path.join(DIST, "Gestor_SSCC.exe")
LOG_PUBLICADOR = os.path.join(RAIZ, "logs", "publicador.log")
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LIMITE_NOTAS = 150  # la ventana de actualización de la app resume las notas a este largo
# Nada de esto debe viajar dentro del paquete que reciben los demás
PROHIBIDOS_EN_PAQUETE = {"datos_prueba", "datos_prueba_base", "modo_datos.json", ".programador", "app_config.json"}

PASOS = [
    ("Poner el número de versión", 2),
    ("Compilar la aplicación", 55),
    ("Probar que el programa abre", 8),
    ("Comprimir y subir a la carpeta compartida", 25),
    ("Comprobar que quedó bien publicada", 5),
    ("Limpiar archivos temporales", 5),
]

CLARO = dict(bg="#EEF1F6", card="#FFFFFF", fg="#1A2233", muted="#5B667A", line="#D9DFEA", navy="#1B2B4E",
             field="#F7F9FC", ok="#1E7B4B", ok_bg="#E3F3EA", warn="#9A6200", warn_bg="#FFF1D6",
             bad="#B3261E", bad_bg="#FBE4E2", accent="#2F5FB3", prim="#1B2B4E", prim_h="#26396A")
OSCURO = dict(bg="#12182A", card="#1C2540", fg="#E7ECF7", muted="#9AA7C0", line="#2C3858", navy="#0F1830",
              field="#161F38", ok="#5ED394", ok_bg="#16382A", warn="#F2BE5C", warn_bg="#3A2D10",
              bad="#FF8D84", bad_bg="#40201E", accent="#7FA6EA", prim="#3A6BC4", prim_h="#4A7AD4")

QSS = """
QWidget {{ font-family: "Segoe UI"; font-size: 10pt; color: {fg}; }}
#ventana {{ background: {bg}; }}
QDialog, QMessageBox {{ background: {card}; }}
QMessageBox QLabel {{ background: transparent; color: {fg}; }}
QToolTip {{ background: {card}; color: {fg}; border: 1px solid {line}; padding: 4px 6px; }}
#tarjeta {{ background: {card}; border: 1px solid {line}; border-radius: 10px; }}
#encabezado {{ background: {navy}; border-top-left-radius: 10px; border-top-right-radius: 10px; }}
#encabezado QLabel {{ color: #FFFFFF; background: transparent; }}
#tituloVentana {{ font-size: 14pt; font-weight: 600; }}
#subtituloVentana {{ color: #C9D3E8; font-size: 9pt; }}
#pildora {{ background: rgba(255,255,255,0.14); border-radius: 11px; padding: 3px 12px; font-size: 9pt; }}
#enlaceEnc {{ background: transparent; color: #FFFFFF; border: 0; text-decoration: underline; font-size: 9pt; padding: 2px 4px; }}
#panelIzq {{ background: transparent; }}
#divisor {{ background: {line}; }}
#rotulo {{ color: {muted}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; }}
#caja {{ background: {field}; border: 1px solid {line}; border-radius: 8px; }}
#caja QLabel {{ background: transparent; }}
#cajaTitulo {{ color: {muted}; font-size: 8pt; }}
#cajaNumero {{ font-size: 15pt; font-weight: 600; }}
#detalle {{ color: {muted}; font-size: 8.5pt; }}
#pista {{ color: {muted}; font-size: 8.5pt; }}
#etiqueta {{ font-weight: 600; }}
QLineEdit, QPlainTextEdit {{ background: {field}; border: 1px solid {line}; border-radius: 7px; padding: 7px 9px; selection-background-color: {accent}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {accent}; }}
#log {{ font-family: "Cascadia Mono", Consolas; font-size: 8.5pt; color: {muted}; }}
QPushButton {{ border-radius: 7px; padding: 9px 18px; font-weight: 600; border: 1px solid {line}; background: transparent; }}
QPushButton:hover {{ background: {field}; }}
QPushButton#primario {{ background: {prim}; color: #FFFFFF; border: 0; padding: 10px 22px; }}
QPushButton#primario:hover {{ background: {prim_h}; }}
QPushButton#primario:disabled {{ background: {line}; color: {muted}; }}
QPushButton#enlace {{ border: 0; color: {accent}; text-decoration: underline; padding: 2px 4px; font-weight: 400; background: transparent; }}
QProgressBar {{ background: {field}; border: 1px solid {line}; border-radius: 6px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 5px; }}
#bannerOk {{ background: {ok_bg}; color: {ok}; border-radius: 8px; padding: 16px 18px; font-size: 11pt; }}
#bannerMal {{ background: {bad_bg}; color: {bad}; border-radius: 8px; padding: 16px 18px; font-size: 11pt; }}
"""


class Fallo(Exception):
    pass


class Cancelado(Exception):
    pass


# ---------------------------------------------------------------- utilidades sin interfaz

def leer_texto(ruta):
    with open(ruta, encoding="utf-8", newline="") as f:
        return f.read()


def escribir_texto(ruta, texto):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(texto)


def version_del_proyecto():
    m = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', leer_texto(AJUSTES), re.MULTILINE)
    return m.group(1) if m else None


def escribir_version(version):
    texto = leer_texto(AJUSTES)
    nuevo, n = re.subn(r'^(APP_VERSION\s*=\s*)"[^"]+"', rf'\g<1>"{version}"', texto, count=1, flags=re.MULTILINE)
    if n != 1:
        raise Fallo("No encontré la línea APP_VERSION en config/settings.py.")
    compile(nuevo, AJUSTES, "exec")  # PyInstaller no importa settings.py: una línea rota compilaría igual
    escribir_texto(AJUSTES, nuevo)


def version_valida(texto):
    return bool(re.fullmatch(r"\d+\.\d+\.\d+", texto.strip()))


def siguiente_version(*versiones):
    validas = [publicar.partes(v) for v in versiones if v and version_valida(v)]
    if not validas:
        return "1.0.0"
    a, b, c = max(validas)
    return f"{a}.{b}.{c + 1}"


def leer_manifiesto(destino):
    try:
        import json
        with open(os.path.join(destino, "version.json"), encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def destino_por_defecto():
    try:
        return publicar.carpeta_destino(None)
    except (SystemExit, OSError, ValueError):
        return ""


def app_abierta():
    try:
        salida = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Gestor_SSCC.exe", "/NH"], capture_output=True,
                                text=True, creationflags=SIN_VENTANA, timeout=10).stdout
        return "Gestor_SSCC.exe" in salida
    except (OSError, subprocess.SubprocessError):
        return False


def se_puede_escribir(carpeta):
    prueba = os.path.join(carpeta, f".prueba_escritura_{os.getpid()}")
    try:
        with open(prueba, "w") as f:
            f.write("ok")
        os.remove(prueba)
        return True
    except OSError:
        return False


def revisar(destino):
    """Devuelve la lista de revisiones (estado, título, detalle); estado: ok, warn o bad."""
    r = []
    faltan = [m for m in ("PyInstaller", "PyQt6", "openpyxl", "pandas", "qtawesome") if find_spec(m) is None]
    if faltan:
        r.append(("bad", "Faltan programas de Python: " + ", ".join(faltan),
                  "Abre una consola en la carpeta del proyecto y ejecuta: pip install -r requirements.txt"))
    else:
        r.append(("ok", "Python y PyInstaller instalados", f"Python {sys.version.split()[0]}"))

    if not destino:
        r.append(("bad", "No sé dónde publicar", "Elige la carpeta compartida con el botón «Cambiar» de arriba."))
    elif not os.path.isdir(destino):
        r.append(("bad", "No encuentro la carpeta compartida", destino))
    elif not se_puede_escribir(destino):
        r.append(("bad", "No puedo escribir en la carpeta compartida",
                  "Pide acceso de escritura a esa carpeta y vuelve a revisar."))
    else:
        partes_ruta = os.path.normpath(destino).split(os.sep)
        r.append(("ok", "Puedo escribir en la carpeta compartida", "…\\" + "\\".join(partes_ruta[-2:])))

    texto = leer_texto(AJUSTES)
    if re.search(r"^MODO_PROGRAMADOR\s*=\s*True\b", texto, re.MULTILINE):
        r.append(("bad", "El modo programador está fijo en el código",
                  "Debe activarse con el archivo .programador, no escrito en config/settings.py."))
    else:
        r.append(("ok", "El paquete saldrá sin modo programador ni datos falsos", ""))

    faltantes = [n for n in ("exe.bat", "publicar.py") if not os.path.isfile(os.path.join(CARPETA, n))]
    if faltantes:
        r.append(("bad", "Faltan archivos del proyecto: " + ", ".join(faltantes), ""))

    if app_abierta():
        r.append(("warn", "Hay una copia de Gestor SSCC abierta",
                  "Se puede publicar, pero se omitirá la prueba de que el programa abre."))
    else:
        r.append(("ok", "No hay otra copia de Gestor SSCC abierta", ""))
    return r


# ---------------------------------------------------------------- trabajo en segundo plano

class Publicacion(QThread):
    paso = pyqtSignal(int, str)      # índice del paso, estado: run, ok, warn, bad
    linea = pyqtSignal(str)
    puede_cancelar = pyqtSignal(bool)
    fin = pyqtSignal(bool, str, str)  # éxito, título, detalle

    def __init__(self, version, notas, destino):
        super().__init__()
        self.version, self.notas, self.destino = version, notas, destino
        self.cancelado = False
        self._proc = None
        self.registro = []

    def cancelar(self):
        self.cancelado = True
        self._matar()

    def _matar(self):
        p = self._proc
        if p and p.poll() is None:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, creationflags=SIN_VENTANA)

    def _anotar(self, texto):
        self.registro.append(texto)
        self.linea.emit(texto)

    def _revisar_cancelado(self):
        if self.cancelado:
            raise Cancelado()

    def _ejecutar(self, args, cwd=RAIZ):
        entorno = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        self._proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                      encoding="utf-8", errors="replace", env=entorno, creationflags=SIN_VENTANA)
        salida = []
        for linea in self._proc.stdout:
            linea = linea.rstrip()
            if linea:
                salida.append(linea)
                self._anotar(linea)
        codigo = self._proc.wait()
        self._proc = None
        self._revisar_cancelado()
        return codigo, salida

    def run(self):
        texto_original = leer_texto(AJUSTES)
        tocado = subido = False
        resultado = None
        try:
            self.paso.emit(0, "run")
            escribir_version(self.version)
            tocado = True
            self.paso.emit(0, "ok")
            self._compilar()
            self._probar()
            self._revisar_cancelado()
            self.puede_cancelar.emit(False)
            self._subir()
            subido = True
            detalle = self._comprobar()
            resultado = (True, f"Versión {self.version} publicada.", detalle)
        except Cancelado:
            resultado = (False, "Publicación cancelada.", "No se publicó nada y el proyecto quedó como estaba.")
        except Fallo as e:
            if subido:
                resultado = (False, "Se subió el paquete, pero la comprobación falló.", str(e))
            else:
                resultado = (False, "No se publicó nada.", f"{e}\nLa versión publicada sigue igual y tu proyecto quedó como estaba.")
        except Exception as e:  # cualquier imprevisto: se informa en vez de dejar la ventana colgada
            resultado = (False, "No se publicó nada.", f"Error inesperado: {e}")
        finally:
            if tocado and not subido:
                escribir_texto(AJUSTES, texto_original)
            self._limpiar()
            self._guardar_registro()
        self.fin.emit(*resultado)

    def _compilar(self):
        self._revisar_cancelado()
        self.paso.emit(1, "run")
        codigo, salida = self._ejecutar(["cmd", "/c", os.path.join(CARPETA, "exe.bat"), "sinpausa"])
        texto = "\n".join(salida)
        if not os.path.isfile(EXE) or ("completed successfully" not in texto and "Build complete" not in texto):
            pista = ""
            if "No module named" in texto:
                pista = "\nFalta un programa de Python. Ejecuta: pip install -r requirements.txt"
            raise Fallo("La compilación falló." + pista)
        sobran = set()
        for _, carpetas, archivos in os.walk(DIST):
            sobran |= PROHIBIDOS_EN_PAQUETE & (set(carpetas) | set(archivos))
        if sobran:
            raise Fallo("El paquete trae archivos que no deben viajar: " + ", ".join(sorted(sobran)))
        self.paso.emit(1, "ok")

    @staticmethod
    def _opciones_prueba():
        """La prueba de apertura no debe mostrar ventanas: si el paquete trae el plugin sin pantalla de Qt, corre con
        él; si no, el programa se abre minimizado y sin tomar el foco."""
        hay_sin_pantalla = any(n.lower().startswith("qoffscreen") for _r, _c, nombres in os.walk(DIST) for n in nombres)
        if hay_sin_pantalla:
            return {"env": dict(os.environ, QT_QPA_PLATFORM="offscreen"), "creationflags": SIN_VENTANA}
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = 7  # SW_SHOWMINNOACTIVE
        return {"startupinfo": info}

    def _probar(self):
        self._revisar_cancelado()
        if app_abierta():
            self._anotar("Hay una copia abierta de Gestor SSCC: se omite la prueba de apertura.")
            self.paso.emit(2, "warn")
            return
        self.paso.emit(2, "run")
        self._proc = subprocess.Popen([EXE], cwd=DIST, **self._opciones_prueba())
        for _ in range(75):
            time.sleep(0.2)
            self._revisar_cancelado()
            if self._proc.poll() is not None:
                break
        cerro = self._proc.poll()
        self._matar()
        self._proc = None
        for sobrante in ("app_config.json", "data", "logs"):
            ruta = os.path.join(DIST, sobrante)
            if os.path.isdir(ruta):
                shutil.rmtree(ruta, ignore_errors=True)
            elif os.path.isfile(ruta):
                os.remove(ruta)
        if cerro is not None:
            raise Fallo(f"El programa compilado se cerró solo al abrir (código {cerro}).")
        self.paso.emit(2, "ok")

    def _subir(self):
        self._revisar_cancelado()
        self.paso.emit(3, "run")
        codigo, salida = self._ejecutar([sys.executable, os.path.join(CARPETA, "publicar.py"), "--notas", self.notas,
                                         "--destino", self.destino])
        if codigo != 0:
            raise Fallo("No se pudo subir el paquete a la carpeta compartida: " + (salida[-1] if salida else ""))
        self.paso.emit(3, "ok")

    def _comprobar(self):
        self.paso.emit(4, "run")
        man = leer_manifiesto(self.destino)
        if not man or man.get("version") != self.version:
            raise Fallo("version.json no dice la versión nueva.")
        zip_subido = os.path.join(self.destino, man.get("zip", publicar.NOMBRE_ZIP))
        if not os.path.isfile(zip_subido) or os.path.getsize(zip_subido) != man.get("tamano"):
            raise Fallo("El tamaño del zip subido no coincide con version.json.")
        self.paso.emit(4, "ok")
        return f"Tamaño del zip: {man['tamano'] / 1024 / 1024:.1f} MB. version.json y el zip coinciden."

    def _limpiar(self):
        self.paso.emit(5, "run")
        try:
            for nombre in ("build", "dist"):
                shutil.rmtree(os.path.join(RAIZ, nombre), ignore_errors=True)
            spec = os.path.join(RAIZ, "Gestor_SSCC.spec")
            if os.path.isfile(spec):
                os.remove(spec)
            self.paso.emit(5, "ok")
        except OSError:
            self.paso.emit(5, "warn")

    def _guardar_registro(self):
        try:
            os.makedirs(os.path.dirname(LOG_PUBLICADOR), exist_ok=True)
            with open(LOG_PUBLICADOR, "w", encoding="utf-8") as f:
                f.write("\n".join(self.registro))
        except OSError:
            pass


# ---------------------------------------------------------------- interfaz

def _punto(estado, tema):
    etiqueta = QLabel({"ok": "✓", "warn": "!", "bad": "!", "run": "", "espera": "·"}[estado])
    etiqueta.setFixedSize(20, 20)
    etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
    colores = {"ok": (tema["ok_bg"], tema["ok"]), "warn": (tema["warn_bg"], tema["warn"]),
               "bad": (tema["bad_bg"], tema["bad"]), "run": (tema["field"], tema["accent"]),
               "espera": (tema["field"], tema["muted"])}[estado]
    etiqueta.setStyleSheet(f"background:{colores[0]}; color:{colores[1]}; border-radius:10px; font-weight:700; font-size:9pt;")
    return etiqueta


class Ventana(QWidget):
    GIRO = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self):
        super().__init__()
        self.ajustes = QSettings("Volvo", "PublicadorGestorSSCC")
        guardado = self.ajustes.value("tema", "", str)
        del_sistema = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        self.oscuro = guardado == "oscuro" or (guardado != "claro" and del_sistema)
        self.t = OSCURO if self.oscuro else CLARO
        self.destino = self.ajustes.value("destino", "", str) or destino_por_defecto()
        self.hilo = None
        self.revisiones = []
        self.publicada = None
        self._giro = 0
        self._inicio_paso = {}
        self._tiempos = {}

        self.setObjectName("ventana")
        self.setWindowTitle("Publicar Gestor SSCC")
        icono = os.path.join(RAIZ, "src", "assets", "volvo.ico")
        if os.path.isfile(icono):
            self.setWindowIcon(QIcon(icono))
        self._aplicar_estilo()
        self.setMinimumSize(960, 660)
        self.resize(1000, 700)
        self._construir()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tic)
        self._refrescar()

    def _aplicar_estilo(self):
        t = self.t
        paleta = QPalette()
        for rol, clave in ((QPalette.ColorRole.Window, "card"), (QPalette.ColorRole.Base, "field"),
                           (QPalette.ColorRole.AlternateBase, "card"), (QPalette.ColorRole.Button, "card"),
                           (QPalette.ColorRole.WindowText, "fg"), (QPalette.ColorRole.Text, "fg"),
                           (QPalette.ColorRole.ButtonText, "fg"), (QPalette.ColorRole.ToolTipBase, "card"),
                           (QPalette.ColorRole.ToolTipText, "fg"), (QPalette.ColorRole.PlaceholderText, "muted"),
                           (QPalette.ColorRole.Highlight, "accent")):
            paleta.setColor(rol, QColor(t[clave]))
        paleta.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        QApplication.setPalette(paleta)
        self.setStyleSheet(QSS.format(**t))

    # --- construcción
    def _construir(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 18, 18, 18)
        tarjeta = QFrame(objectName="tarjeta")
        raiz.addWidget(tarjeta)
        cuerpo = QVBoxLayout(tarjeta)
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(0)

        enc = QFrame(objectName="encabezado")
        he = QHBoxLayout(enc)
        he.setContentsMargins(24, 16, 24, 16)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(QLabel("Publicar nueva versión de Gestor SSCC", objectName="tituloVentana"))
        subtitulo = QLabel("Compila la aplicación y la deja disponible para que los demás se actualicen desde su propia app.",
                           objectName="subtituloVentana")
        subtitulo.setWordWrap(True)
        textos.addWidget(subtitulo)
        he.addLayout(textos, 1)
        self.pildora = QLabel(objectName="pildora")
        he.addWidget(self.pildora, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_cambiar = QPushButton("Cambiar", objectName="enlaceEnc")
        self.btn_cambiar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cambiar.clicked.connect(self._cambiar_destino)
        he.addWidget(self.btn_cambiar, 0, Qt.AlignmentFlag.AlignVCenter)
        self.btn_tema = QPushButton("Modo claro" if self.oscuro else "Modo oscuro", objectName="enlaceEnc")
        self.btn_tema.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tema.clicked.connect(self._alternar_tema)
        he.addWidget(self.btn_tema, 0, Qt.AlignmentFlag.AlignVCenter)
        cuerpo.addWidget(enc)

        franja = QHBoxLayout()
        franja.setContentsMargins(0, 0, 0, 0)
        franja.setSpacing(0)
        cuerpo.addLayout(franja, 1)

        izq = QWidget(objectName="panelIzq")
        izq.setMinimumWidth(360)
        li = QVBoxLayout(izq)
        li.setContentsMargins(24, 20, 24, 20)
        li.setSpacing(14)
        li.addWidget(QLabel("ANTES DE PUBLICAR", objectName="rotulo"))
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self.num_publicada = self._caja_version("Publicada hoy", fila)
        self.num_proyecto = self._caja_version("En este proyecto", fila)
        li.addLayout(fila)
        self.lista_rev = QVBoxLayout()
        self.lista_rev.setSpacing(10)
        li.addLayout(self.lista_rev)
        li.addStretch(1)
        self.btn_revisar = QPushButton("Volver a revisar")
        self.btn_revisar.clicked.connect(self._refrescar)
        li.addWidget(self.btn_revisar, 0, Qt.AlignmentFlag.AlignLeft)
        franja.addWidget(izq, 5)

        franja.addWidget(QFrame(objectName="divisor", maximumWidth=1, minimumWidth=1))

        self.pila = QStackedWidget()
        franja.addWidget(self.pila, 6)
        self.pila.addWidget(self._pagina_formulario())
        self.pila.addWidget(self._pagina_avance())
        self.pila.addWidget(self._pagina_resultado())

    def _caja_version(self, titulo, fila):
        caja = QFrame(objectName="caja")
        v = QVBoxLayout(caja)
        v.setContentsMargins(12, 9, 12, 9)
        v.setSpacing(0)
        v.addWidget(QLabel(titulo, objectName="cajaTitulo"))
        numero = QLabel("—", objectName="cajaNumero")
        v.addWidget(numero)
        fila.addWidget(caja, 1)
        return numero

    def _pagina_formulario(self):
        p = QWidget()
        v = QVBoxLayout(p)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(8)
        v.addWidget(QLabel("VERSIÓN NUEVA", objectName="rotulo"))
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Número de versión", objectName="etiqueta"))
        self.btn_sugerida = QPushButton("", objectName="enlace")
        self.btn_sugerida.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_sugerida.clicked.connect(lambda: self.campo_version.setText(self.sugerida))
        fila.addWidget(self.btn_sugerida)
        fila.addStretch(1)
        v.addLayout(fila)
        self.campo_version = QLineEdit()
        self.campo_version.textChanged.connect(self._validar)
        v.addWidget(self.campo_version)
        self.pista_version = QLabel(objectName="pista")
        self.pista_version.setWordWrap(True)
        v.addWidget(self.pista_version)
        v.addSpacing(8)
        v.addWidget(QLabel("Qué cambió (lo verán todos al actualizar)", objectName="etiqueta"))
        self.campo_notas = QPlainTextEdit()
        self.campo_notas.setPlaceholderText("Por ejemplo: Avisos cuando falta un enlace y cajas de detalle iguales en Administración.")
        self.campo_notas.setMinimumHeight(96)
        self.campo_notas.textChanged.connect(self._validar)
        v.addWidget(self.campo_notas, 1)
        self.pista_notas = QLabel(objectName="pista")
        v.addWidget(self.pista_notas)
        v.addSpacing(6)
        fila = QHBoxLayout()
        self.aviso_boton = QLabel("Tarda unos minutos. No cierres esta ventana.", objectName="pista")
        self.aviso_boton.setWordWrap(True)
        fila.addWidget(self.aviso_boton, 1)
        self.btn_publicar = QPushButton("Publicar", objectName="primario")
        self.btn_publicar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_publicar.clicked.connect(self._publicar)
        fila.addWidget(self.btn_publicar)
        v.addLayout(fila)
        return p

    def _pagina_avance(self):
        p = QWidget()
        v = QVBoxLayout(p)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(10)
        self.titulo_avance = QLabel("", objectName="rotulo")
        v.addWidget(self.titulo_avance)
        self.filas_pasos = []
        for i, (texto, _) in enumerate(PASOS):
            fila = QHBoxLayout()
            fila.setSpacing(10)
            icono = QLabel()
            icono.setFixedSize(20, 20)
            nombre = QLabel(texto)
            tiempo = QLabel("", objectName="detalle")
            fila.addWidget(icono)
            fila.addWidget(nombre, 1)
            fila.addWidget(tiempo)
            v.addLayout(fila)
            self.filas_pasos.append((icono, nombre, tiempo))
        self.barra = QProgressBar()
        self.barra.setRange(0, 1000)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(10)
        v.addSpacing(4)
        v.addWidget(self.barra)
        self.registro = QPlainTextEdit(objectName="log")
        self.registro.setReadOnly(True)
        self.registro.setMaximumBlockCount(300)
        v.addWidget(self.registro, 1)
        fila = QHBoxLayout()
        fila.addStretch(1)
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.clicked.connect(self._cancelar)
        fila.addWidget(self.btn_cancelar)
        v.addLayout(fila)
        return p

    def _pagina_resultado(self):
        p = QWidget()
        v = QVBoxLayout(p)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        self.titulo_res = QLabel("RESULTADO", objectName="rotulo")
        v.addWidget(self.titulo_res)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.banner)
        self.detalle_res = QPlainTextEdit(objectName="log")
        self.detalle_res.setReadOnly(True)
        self.detalle_res.setMaximumHeight(160)
        v.addWidget(self.detalle_res)
        v.addStretch(1)
        fila = QHBoxLayout()
        self.btn_abrir = QPushButton("Abrir carpeta compartida")
        self.btn_abrir.clicked.connect(lambda: os.path.isdir(self.destino) and os.startfile(self.destino))
        self.btn_copiar = QPushButton("Copiar detalle")
        self.btn_copiar.clicked.connect(self._copiar)
        self.btn_final = QPushButton("Cerrar", objectName="primario")
        self.btn_final.clicked.connect(self._terminar)
        fila.addWidget(self.btn_abrir)
        fila.addWidget(self.btn_copiar)
        fila.addStretch(1)
        fila.addWidget(self.btn_final)
        v.addLayout(fila)
        return p

    # --- estado de la página de preparación
    def _refrescar(self):
        proyecto = version_del_proyecto()
        man = leer_manifiesto(self.destino) if self.destino and os.path.isdir(self.destino) else None
        self.publicada = man.get("version") if man else None
        self.num_publicada.setText(self.publicada or "—")
        self.num_proyecto.setText(proyecto or "—")
        self.pildora.setText("Carpeta: " + (os.path.basename(os.path.normpath(self.destino)) if self.destino else "sin elegir"))
        self.pildora.setToolTip(self.destino)
        self.sugerida = siguiente_version(proyecto, self.publicada)
        self.btn_sugerida.setText(f"usar {self.sugerida}")
        if not self.campo_version.text():
            self.campo_version.setText(self.sugerida)
        self.revisiones = revisar(self.destino)
        self._pintar_revisiones()

    def _alternar_tema(self):
        self.oscuro = not self.oscuro
        self.ajustes.setValue("tema", "oscuro" if self.oscuro else "claro")
        self.t = OSCURO if self.oscuro else CLARO
        self._aplicar_estilo()
        self.btn_tema.setText("Modo claro" if self.oscuro else "Modo oscuro")
        self._pintar_revisiones()
        if hasattr(self, "_estados"):
            self._pintar_pasos()

    def _pintar_revisiones(self):
        while self.lista_rev.count():
            item = self.lista_rev.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._vaciar(item.layout())
        for estado, titulo, detalle in self.revisiones:
            fila = QHBoxLayout()
            fila.setSpacing(10)
            fila.addWidget(_punto(estado, self.t), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(0)
            lbl = QLabel(titulo)
            lbl.setWordWrap(True)
            col.addWidget(lbl)
            if detalle:
                d = QLabel(detalle, objectName="detalle")
                d.setWordWrap(True)
                col.addWidget(d)
            fila.addLayout(col, 1)
            cont = QWidget()
            cont.setLayout(fila)
            self.lista_rev.addWidget(cont)
        self._validar()

    def _vaciar(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _validar(self):
        v = self.campo_version.text().strip()
        notas = " ".join(self.campo_notas.toPlainText().split())
        motivo = ""
        if not version_valida(v):
            self.pista_version.setText("Escribe tres números separados por puntos, por ejemplo 1.2.1.")
            motivo = "Falta un número de versión válido."
        elif self.publicada and publicar.partes(v) <= publicar.partes(self.publicada):
            self.pista_version.setText(f"Tiene que ser mayor que la publicada ({self.publicada}).")
            motivo = "La versión tiene que ser mayor que la publicada."
        else:
            self.pista_version.setText(f"Tiene que ser mayor que la publicada ({self.publicada or 'ninguna todavía'}).")
        largo = len(notas)
        self.pista_notas.setText(f"{largo} de {LIMITE_NOTAS} caracteres. En la app se muestra resumido a una línea.")
        if not notas and not motivo:
            motivo = "Escribe qué cambió."
        elif largo > LIMITE_NOTAS and not motivo:
            motivo = f"Las notas pasan de {LIMITE_NOTAS} caracteres."
        if any(e == "bad" for e, _, _ in self.revisiones) and not motivo:
            motivo = "Hay revisiones en rojo a la izquierda."
        self.btn_publicar.setText(f"Publicar versión {v}" if version_valida(v) else "Publicar")
        self.btn_publicar.setEnabled(not motivo)
        self.aviso_boton.setText(motivo or "Tarda unos minutos. No cierres esta ventana.")

    def _cambiar_destino(self):
        elegido = QFileDialog.getExistingDirectory(self, "Carpeta compartida de actualizaciones", self.destino or RAIZ)
        if elegido:
            self.destino = os.path.normpath(elegido)
            self.ajustes.setValue("destino", self.destino)
            self.campo_version.clear()
            self._refrescar()

    # --- publicación
    def _publicar(self):
        version = self.campo_version.text().strip()
        notas = " ".join(self.campo_notas.toPlainText().split())
        aviso = QMessageBox(self)
        aviso.setWindowTitle("Confirmar publicación")
        aviso.setText(f"Se publicará la versión {version}.")
        aviso.setInformativeText("Quienes tengan la app instalada verán el aviso de actualización. El paquete anterior se reemplaza en la carpeta compartida.")
        publicar_btn = aviso.addButton("Publicar", QMessageBox.ButtonRole.AcceptRole)
        aviso.addButton("Volver", QMessageBox.ButtonRole.RejectRole)
        aviso.exec()
        if aviso.clickedButton() is not publicar_btn:
            return
        self.registro.clear()
        self.titulo_avance.setText(f"PUBLICANDO {version}")
        self._tiempos = {}
        self._inicio_paso = {}
        self._estados = ["espera"] * len(PASOS)
        self._pintar_pasos()
        self.barra.setValue(0)
        self._objetivo = 0
        self.btn_cancelar.setEnabled(True)
        self.pila.setCurrentIndex(1)
        self.hilo = Publicacion(version, notas, self.destino)
        self.hilo.paso.connect(self._on_paso)
        self.hilo.linea.connect(self._on_linea)
        self.hilo.puede_cancelar.connect(self.btn_cancelar.setEnabled)
        self.hilo.fin.connect(self._on_fin)
        self._timer.start()
        self.hilo.start()

    def _cancelar(self):
        if self.hilo:
            self.btn_cancelar.setEnabled(False)
            self.btn_cancelar.setText("Cancelando…")
            self.hilo.cancelar()

    def _on_paso(self, i, estado):
        self._estados[i] = estado
        if estado == "run":
            self._inicio_paso[i] = time.time()
            self._objetivo = sum(p for _, p in PASOS[:i + 1]) * 10
        else:
            self._tiempos[i] = time.time() - self._inicio_paso.get(i, time.time())
            self.barra.setValue(max(self.barra.value(), sum(p for _, p in PASOS[:i + 1]) * 10))
        self._pintar_pasos()

    def _on_linea(self, texto):
        self.registro.appendPlainText(texto)

    def _tic(self):
        self._giro = (self._giro + 1) % len(self.GIRO)
        if self.barra.value() < self._objetivo:
            self.barra.setValue(self.barra.value() + max(1, int((self._objetivo - self.barra.value()) * 0.04)))
        self._pintar_pasos()

    def _pintar_pasos(self):
        for i, (icono, nombre, tiempo) in enumerate(self.filas_pasos):
            estado = self._estados[i]
            if estado == "run":
                icono.setText(self.GIRO[self._giro])
                icono.setStyleSheet(f"color:{self.t['accent']}; font-size:12pt; background:transparent;")
                icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
                nombre.setStyleSheet("font-weight:600;")
                seg = int(time.time() - self._inicio_paso.get(i, time.time()))
                tiempo.setText(f"{seg // 60}:{seg % 60:02d}")
            else:
                p = _punto(estado, self.t)
                icono.setText(p.text())
                icono.setStyleSheet(p.styleSheet())
                icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
                nombre.setStyleSheet(f"color:{self.t['muted']};" if estado == "espera" else "")
                seg = int(self._tiempos.get(i, 0))
                tiempo.setText(f"{seg // 60}:{seg % 60:02d}" if i in self._tiempos else "")

    def _on_fin(self, ok, titulo, detalle):
        self._timer.stop()
        self.barra.setValue(1000 if ok else self.barra.value())
        if ok:
            self.banner.setObjectName("bannerOk")
            self.banner.setText(f"<b>{titulo}</b><br>La gente verá el aviso de actualización la próxima vez que abra la app.")
            self.btn_final.setText("Cerrar")
        else:
            self.banner.setObjectName("bannerMal")
            self.banner.setText(f"<b>{titulo}</b>")
            self.btn_final.setText("Volver a intentar")
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.detalle_res.setPlainText(detalle)
        self._ok_final = ok
        self.btn_abrir.setVisible(ok)
        self.btn_cancelar.setText("Cancelar")
        self.pila.setCurrentIndex(2)

    def _copiar(self):
        QGuiApplication.clipboard().setText("\n".join(self.hilo.registro) if self.hilo else self.detalle_res.toPlainText())
        self.btn_copiar.setText("Copiado")
        QTimer.singleShot(1500, lambda: self.btn_copiar.setText("Copiar detalle"))

    def _terminar(self):
        if getattr(self, "_ok_final", False):
            self.close()
        else:
            self.campo_version.clear()
            self.pila.setCurrentIndex(0)
            self._refrescar()

    def closeEvent(self, evento):
        if self.hilo and self.hilo.isRunning():
            QMessageBox.information(self, "Publicando", "Espera a que termine la publicación o pulsa Cancelar.")
            evento.ignore()
            return
        evento.accept()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    try:
        ventana = Ventana()
    except Exception as e:
        QMessageBox.critical(None, "Publicador", f"No se pudo abrir el publicador:\n{e}")
        return 1
    ventana.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
