"""Catálogo de archivos de datos de la app y utilidades para ubicarlos a partir
de una sola carpeta, sin escribir rutas en el código: aquí solo viven los
NOMBRES estándar de los archivos. Lógica pura (sin PyQt) usada por
config/settings.py, la pantalla de Configuración y el asistente de arranque."""
import os
import time

# clave de app_config.json -> (etiqueta visible, nombre estándar, obligatorio)
ARCHIVOS_DE_DATOS = {
    "EXCEL_PATH": ("Registro Maestro", "Registro Maestro.csv", True),
    "LOG_CSV_PATH": ("Historial de cambios", "LogApp.csv", True),
    "DELETED_LOG_EXCEL_PATH": ("Papelera", "RegistroEliminado.xlsx", True),
    "PROVISION_EXCEL_PATH": ("Provisiones", "provisionFelipe.xlsx", True),
    "INSTALACIONES_PATH": ("Instalaciones", "Instalaciones.xlsx", True),
    "CONTACTOS_EXCEL_PATH": ("Administradores de flota (contactos)", "contactos.xlsx", True),
    "CORREOS_EXCEL_PATH": ("Correos", "Correos.csv", True),
    "CASOS_BAJA_CM_PATH": ("Casos de revisión CM", "CasosBajaCM.csv", False),
    "POWERBI_EXCEL_PATH": ("BBDD Clientes CM", "BBDD CLIENTES CM.xlsx", True),
    "FACTURACION_MANUAL_PATH": ("Facturación manual", "facturacionManual.xlsx", False),
    "EJECUTIVOS_PATH": ("Directorio de ejecutivos", "Ejecutivos_VC.csv", False),
    "METAS_VC_PATH": ("Metas de Volvo Connect", "MetasVC.csv", False),
    # Suele vivir en otra carpeta del equipo: se busca, pero no se deriva a ciegas
    "RM_JAVI_PATH": ("RM Javiera", "RM_JAVI_VOLVO CONNECT.xlsx", False),
}

# Claves que se derivan de la carpeta de datos cuando están vacías
# Se elige a mano en Configuración > Avanzado (modo programador), no se lista en Archivos
CLAVES_SOLO_PROGRAMADOR = ("RM_JAVI_PATH",)

CLAVES_DERIVABLES =tuple(k for k in ARCHIVOS_DE_DATOS if k != "RM_JAVI_PATH")

# Claves de versiones anteriores que nada lee y se eliminan al guardar
CLAVES_OBSOLETAS = ("CUSTOMER_EXCEL_PATH", "POWERBI_URL")

# Nombres anteriores de un archivo (20-10-2026: RM_JAVI.csv pasó a llamarse
# Registro Maestro.csv). Se aceptan ambos mientras convivan en las carpetas.
NOMBRES_ANTERIORES = {"EXCEL_PATH": ("RM_JAVI.csv",)}


def nombres_aceptados(clave):
    """Nombres con que puede llamarse el archivo de `clave`, el estándar primero."""
    return (ARCHIVOS_DE_DATOS[clave][1],) + NOMBRES_ANTERIORES.get(clave, ())


def resolver_nombre_anterior(clave, ruta):
    """Si `ruta` no existe pero el mismo archivo existe en su carpeta con otro
    nombre aceptado, devuelve esa ruta; si no, devuelve `ruta` sin cambios."""
    if not ruta or os.path.exists(ruta) or clave not in ARCHIVOS_DE_DATOS:
        return ruta
    carpeta = os.path.dirname(ruta)
    for nombre in nombres_aceptados(clave):
        candidata = os.path.join(carpeta, nombre)
        if os.path.exists(candidata):
            return candidata
    return ruta

# Carpetas que nunca se recorren al buscar (copias de respaldo, cachés, etc.)
_CARPETAS_IGNORADAS = ("backup", "backups", "backup_auto", "__pycache__", "node_modules", "appdata", "$recycle.bin")


def completar_rutas(config):
    """Rellena, en el diccionario recibido, las rutas vacías con
    DATA_DIR + nombre estándar. Una ruta ya definida nunca se pisa."""
    carpeta = (config.get("DATA_DIR") or "").strip()
    if not carpeta:
        return config
    for clave in CLAVES_DERIVABLES:
        if not config.get(clave):
            config[clave] = resolver_nombre_anterior(clave, os.path.join(carpeta, ARCHIVOS_DE_DATOS[clave][1]))
    return config


def estado_archivo(ruta):
    """(existe, tamaño en bytes, fecha de modificación) de una ruta."""
    try:
        info = os.stat(ruta)
        return True, info.st_size, info.st_mtime
    except (OSError, TypeError, ValueError):
        return False, 0, 0.0


def _recorrer(raiz, profundidad):
    """Directorios bajo `raiz` hasta `profundidad` niveles, sin entrar a los ignorados."""
    pendientes = [(raiz, 0)]
    while pendientes:
        carpeta, nivel = pendientes.pop(0)
        yield carpeta
        if nivel >= profundidad:
            continue
        try:
            with os.scandir(carpeta) as it:
                for entrada in it:
                    nombre = entrada.name.lower()
                    if entrada.is_dir(follow_symlinks=False) and nombre not in _CARPETAS_IGNORADAS \
                            and not nombre.startswith('.'):
                        pendientes.append((entrada.path, nivel + 1))
        except OSError:
            continue


def descubrir_archivos(carpeta_base, subir=1, profundidad=2):
    """Busca cada archivo estándar dentro de `carpeta_base` (y hasta
    `profundidad` niveles hacia abajo) y, si no aparece, también en las
    `subir` carpetas superiores (para el RM de Javiera y otros que viven en
    carpetas hermanas). Devuelve {clave: ruta} solo con los encontrados; si
    hay varias copias gana la más cercana a `carpeta_base`."""
    if not carpeta_base or not os.path.isdir(carpeta_base):
        return {}
    raices = [os.path.abspath(carpeta_base)]
    for _ in range(subir):
        padre = os.path.dirname(raices[-1])
        if padre and padre != raices[-1]:
            raices.append(padre)

    pendientes = {clave: [n.lower() for n in nombres_aceptados(clave)] for clave in ARCHIVOS_DE_DATOS}
    encontrados = {}
    for indice, raiz in enumerate(raices):
        # La raíz superior se recorre con más profundidad para llegar a carpetas hermanas
        for carpeta in _recorrer(raiz, profundidad if indice == 0 else profundidad + 1):
            try:
                nombres = {n.lower(): n for n in os.listdir(carpeta)}
            except OSError:
                continue
            for clave, candidatos in list(pendientes.items()):
                for nombre in candidatos:
                    if nombre in nombres:
                        encontrados[clave] = os.path.join(carpeta, nombres[nombre])
                        del pendientes[clave]
                        break
        if not pendientes:
            break
    return encontrados


def buscar_carpeta_de_datos(inicio, profundidad=4, limite_seg=10.0):
    """Busca desde `inicio` (normalmente la carpeta del usuario) la carpeta que
    contiene el Registro Maestro con su nombre estándar. Devuelve su ruta o
    None. Corta a los `limite_seg` segundos para no dejar la app esperando."""
    marcadores = {n.lower() for n in nombres_aceptados("EXCEL_PATH")}
    limite = time.monotonic() + limite_seg
    for carpeta in _recorrer(inicio, profundidad):
        if time.monotonic() > limite:
            return None
        try:
            if marcadores & {n.lower() for n in os.listdir(carpeta)}:
                return carpeta
        except OSError:
            continue
    return None
