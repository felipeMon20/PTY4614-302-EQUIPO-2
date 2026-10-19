import os
import json
import sys

from config.rutas import completar_rutas, CLAVES_OBSOLETAS

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_FILE = os.path.join(BASE_DIR, "app_config.json")

# Muestra herramientas de desarrollo (pestaña Avanzado de Configuración). El
# programador lo pone en True aquí o define GESTOR_SSCC_PROGRAMADOR=1 en su
# entorno; el ejecutable que recibe el usuario común lo deja en False.
MODO_PROGRAMADOR = False or os.environ.get("GESTOR_SSCC_PROGRAMADOR") == "1"

# Diccionario maestro de estructura. Será la fuente de verdad si falta el archivo.
DEFAULT_CONFIG = {
    "DATA_DIR": "",
    "EXCEL_PATH": "",
    "LOG_EXCEL_PATH": "",
    "LOG_CSV_PATH": "",
    "DELETED_LOG_EXCEL_PATH": "",
    "PROVISION_EXCEL_PATH": "",
    "INSTALACIONES_PATH": "",
    "RM_REPORTE_PATH": "",
    "POWERBI_EXCEL_PATH": "",
    "CONTACTOS_EXCEL_PATH": "",
    "CORREOS_EXCEL_PATH": "",
    "CASOS_BAJA_CM_PATH": "",
    "FACTURACION_MANUAL_PATH": "",
    "EJECUTIVOS_PATH": "",
    "PROVISIONES_SHAREPOINT_URL": "",
    "REPORTE_NOTAS_VENTAS_URL": "",
    "POWERBI_URL": ""
}

def load_config():
    # Bootstrap seguro: Si no existe, crea uno garantizando la estructura del DEFAULT_CONFIG
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
            # Aseguramos que las llaves nuevas existan incluso en configs antiguas
            for key in DEFAULT_CONFIG:
                if key not in user_config:
                    user_config[key] = DEFAULT_CONFIG[key]

        # Carpeta de datos (DATA_DIR): las rutas que queden vacías se derivan
        # de ella con los nombres estándar (config/rutas.py). Una ruta ya
        # definida siempre tiene prioridad. Solo en memoria, no escribe a disco.
        completar_rutas(user_config)

        # Normalizacion en memoria: LogApp.csv es el historial oficial (ver
        # excel_writer.migrar_historial_legacy). Si una config antigua solo
        # tiene LOG_EXCEL_PATH (el .xlsx legado) y todavia no tiene
        # LOG_CSV_PATH explicito, se deriva aqui. LOG_EXCEL_PATH se conserva
        # despues de esto solo como referencia para ubicar el .xlsx legado a
        # migrar; el historial en uso pasa a depender exclusivamente de
        # LOG_CSV_PATH. A proposito NO se escribe a disco solo por cargar la
        # config (evitaria que un simple import reescriba app_config.json);
        # queda persistido la proxima vez que el usuario guarde Configuración
        # normalmente, momento en el que este mismo valor ya derivado se
        # incluye en el diccionario que se guarda.
        if not user_config.get("LOG_CSV_PATH") and user_config.get("LOG_EXCEL_PATH"):
            user_config["LOG_CSV_PATH"] = os.path.splitext(user_config["LOG_EXCEL_PATH"])[0] + ".csv"

        # CasosBajaCM.csv (motor de deteccion de posibles Bajas CM) vive por
        # defecto junto a PruebasFM.xlsx, igual que RegistroEliminado.xlsx.
        # Misma logica de derivacion en memoria que LOG_CSV_PATH arriba: no
        # se escribe a disco solo por cargar la config.
        if not user_config.get("CASOS_BAJA_CM_PATH") and user_config.get("EXCEL_PATH"):
            user_config["CASOS_BAJA_CM_PATH"] = os.path.join(
                os.path.dirname(user_config["EXCEL_PATH"]), "CasosBajaCM.csv"
            )

        # facturacionManual.xlsx vive por defecto junto a provisionContratos.xlsx
        # (misma derivación en memoria, sin escribir a disco).
        if not user_config.get("FACTURACION_MANUAL_PATH") and user_config.get("PROVISION_EXCEL_PATH"):
            user_config["FACTURACION_MANUAL_PATH"] = os.path.join(
                os.path.dirname(user_config["PROVISION_EXCEL_PATH"]), "facturacionManual.xlsx"
            )

        return user_config
    except Exception:
        return DEFAULT_CONFIG

def save_config(new_config):
    # Se descartan las claves de versiones anteriores que nada lee
    limpia = {k: v for k, v in new_config.items() if k not in CLAVES_OBSOLETAS}
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(limpia, f, indent=4)

_current_config = load_config()

# --- RUTAS LOCALES ---
DATA_DIR = _current_config.get("DATA_DIR", "")
EXCEL_PATH = _current_config.get("EXCEL_PATH", "")
LOG_EXCEL_PATH = _current_config.get("LOG_EXCEL_PATH", "")
LOG_CSV_PATH = _current_config.get("LOG_CSV_PATH", "")
DELETED_LOG_EXCEL_PATH = _current_config.get("DELETED_LOG_EXCEL_PATH", "")
PROVISION_EXCEL_PATH = _current_config.get("PROVISION_EXCEL_PATH", "")
INSTALACIONES_PATH = _current_config.get("INSTALACIONES_PATH", "")
RM_REPORTE_PATH = _current_config.get("RM_REPORTE_PATH", "")
POWERBI_EXCEL_PATH = _current_config.get("POWERBI_EXCEL_PATH", "")
CONTACTOS_EXCEL_PATH = _current_config.get("CONTACTOS_EXCEL_PATH", "")
CORREOS_EXCEL_PATH = _current_config.get("CORREOS_EXCEL_PATH", "")
CASOS_BAJA_CM_PATH = _current_config.get("CASOS_BAJA_CM_PATH", "")
FACTURACION_MANUAL_PATH = _current_config.get("FACTURACION_MANUAL_PATH", "")
EJECUTIVOS_PATH = _current_config.get("EJECUTIVOS_PATH", "")

# --- ENLACES WEB Y NUBE ---
PROVISIONES_SHAREPOINT_URL = _current_config.get("PROVISIONES_SHAREPOINT_URL", "")
REPORTE_NOTAS_VENTAS_URL = _current_config.get("REPORTE_NOTAS_VENTAS_URL", "")
POWERBI_EMBED_URL = _current_config.get("POWERBI_EMBED_URL", "")

WATCH_DIR = os.path.dirname(EXCEL_PATH) if EXCEL_PATH and os.path.exists(EXCEL_PATH) else ""