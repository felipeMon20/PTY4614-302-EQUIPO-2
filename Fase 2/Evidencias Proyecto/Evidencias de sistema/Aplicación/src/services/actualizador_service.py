"""Actualización de la aplicación sin interfaz: lee lo publicado en la carpeta
compartida, descarga y valida el zip, y prepara el reemplazo de la instalación.
Los hilos y las ventanas viven en src/core/actualizador.py y src/ui/dialogo_actualizacion.py."""
import json
import os
import sys

import config.settings as ajustes

NOMBRE_MANIFIESTO = "version.json"
NOMBRE_ZIP = "Gestor_SSCC.zip"
_BLOQUE = 1024 * 1024
_MB = 1024 * 1024


class ActualizacionError(Exception):
    """Fallo con un mensaje que se puede mostrar tal cual a la persona."""


class ActualizacionCancelada(Exception):
    pass


def carpeta_publicacion():
    """Carpeta compartida con el zip y version.json, hermana de la carpeta de datos."""
    base = ajustes.DATA_DIR or (os.path.dirname(ajustes.EXCEL_PATH) if ajustes.EXCEL_PATH else "")
    if not base:
        return ""
    return os.path.join(os.path.dirname(os.path.normpath(base)), ajustes.CARPETA_ACTUALIZACIONES)


def _partes(version):
    try:
        return tuple(int(p) for p in str(version).strip().lstrip("vV").split("."))
    except ValueError:
        return None


def es_mas_nueva(publicada, instalada):
    a, b = _partes(publicada), _partes(instalada)
    return a is not None and b is not None and a > b


def leer_manifiesto(carpeta=None):
    """Datos de version.json o None si no existe, no se puede leer o está mal formado."""
    carpeta = carpeta_publicacion() if carpeta is None else carpeta
    if not carpeta:
        return None
    try:
        with open(os.path.join(carpeta, NOMBRE_MANIFIESTO), "r", encoding="utf-8-sig") as f:
            datos = json.load(f)
        version = str(datos["version"]).strip()
        if _partes(version) is None:
            return None
        return {
            "version": version,
            "notas": str(datos.get("notas") or "").strip(),
            "zip": os.path.basename(str(datos.get("zip") or NOMBRE_ZIP)),
            "tamano": int(datos.get("tamano") or 0),
            "sha256": str(datos.get("sha256") or "").lower(),
            "carpeta": carpeta,
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def puede_instalar():
    """Solo el ejecutable se reemplaza a sí mismo; desde el código fuente no se toca nada."""
    return bool(getattr(sys, "frozen", False))


def carpeta_instalacion():
    return os.path.dirname(sys.executable)


def descargar_y_extraer(manifiesto, progreso, cancelado, instalacion=None):
    """Copia el zip publicado a una carpeta temporal, valida tamaño y huella y extrae
    solo los archivos que difieren de la instalación (todos, si no hay instalación).
    `progreso(fase, porcentaje, detalle)` informa el avance y `cancelado()` permite abortar.
    Devuelve (carpeta temporal, carpeta con los archivos nuevos); la lista de archivos
    obsoletos queda en `eliminar.txt` dentro de la carpeta temporal."""
    import shutil
    import tempfile
    if instalacion is None and puede_instalar():
        instalacion = carpeta_instalacion()
    if instalacion:
        _comprobar_escritura(instalacion)
    temporal = tempfile.mkdtemp(prefix="gestor_sscc_upd_")
    try:
        copia = os.path.join(temporal, "paquete.zip")
        _copiar(os.path.join(manifiesto["carpeta"], manifiesto["zip"]), copia, manifiesto, progreso, cancelado)
        raiz = _extraer_cambios(copia, os.path.join(temporal, "nuevo"), instalacion, temporal, progreso, cancelado)
        os.remove(copia)
        return temporal, raiz
    except BaseException:
        shutil.rmtree(temporal, ignore_errors=True)
        raise


def _comprobar_escritura(carpeta):
    import tempfile
    try:
        with tempfile.TemporaryFile(dir=carpeta):
            pass
    except OSError:
        raise ActualizacionError(
            f"No hay permiso para escribir en {carpeta}. Mueve la aplicación a una carpeta propia, "
            "por ejemplo C:\\Gestor_SSCC, y vuelve a intentar.")


def _copiar(origen, destino, manifiesto, progreso, cancelado):
    import hashlib
    try:
        total = os.path.getsize(origen)
    except OSError:
        raise ActualizacionError("No se encontró el paquete en la carpeta compartida.")
    if manifiesto["tamano"] and total != manifiesto["tamano"]:
        raise ActualizacionError("El paquete aún se está sincronizando desde OneDrive. Inténtalo de nuevo en unos minutos.")
    huella = hashlib.sha256()
    copiado = 0
    try:
        with open(origen, "rb") as entrada, open(destino, "wb") as salida:
            while True:
                if cancelado():
                    raise ActualizacionCancelada()
                bloque = entrada.read(_BLOQUE)
                if not bloque:
                    break
                salida.write(bloque)
                huella.update(bloque)
                copiado += len(bloque)
                progreso("descarga", copiado * 100 // max(total, 1), f"{copiado / _MB:.0f} de {total / _MB:.0f} MB")
    except OSError as e:
        raise ActualizacionError(f"No se pudo copiar el paquete: {e}")
    if copiado != total:
        raise ActualizacionError("La copia del paquete quedó incompleta.")
    if manifiesto["sha256"] and huella.hexdigest() != manifiesto["sha256"]:
        raise ActualizacionError("El paquete descargado no coincide con el publicado.")


def _extraer_cambios(zip_ruta, destino, instalacion, temporal, progreso, cancelado):
    """Extrae solo lo que cambió respecto a `instalacion` (mismo tamaño y CRC32 = igual)
    y anota en eliminar.txt los archivos de _internal que ya no vienen en el paquete."""
    import zipfile
    os.makedirs(destino, exist_ok=True)
    base = os.path.realpath(destino)
    try:
        with zipfile.ZipFile(zip_ruta) as paquete:
            miembros = [m for m in paquete.infolist() if not m.is_dir()]
            prefijo = _prefijo_de_la_app(miembros, _nombre_exe())
            miembros = [m for m in miembros if m.filename.startswith(prefijo)]
            total = sum(m.file_size for m in miembros) or 1
            hecho = nuevos = 0
            for miembro in miembros:
                if cancelado():
                    raise ActualizacionCancelada()
                hecho += miembro.file_size
                relativa = miembro.filename[len(prefijo):]
                if instalacion and _es_igual(os.path.join(instalacion, *relativa.split("/")), miembro):
                    progreso("extraccion", hecho * 100 // total, "Comparando con la versión instalada")
                    continue
                objetivo = os.path.realpath(os.path.join(destino, miembro.filename))
                if os.path.commonpath([base, objetivo]) != base:
                    raise ActualizacionError("El paquete contiene rutas no válidas.")
                paquete.extract(miembro, destino)
                nuevos += 1
                progreso("extraccion", hecho * 100 // total, f"Preparando {nuevos} archivos que cambiaron")
            progreso("extraccion", 100, f"{nuevos} de {len(miembros)} archivos cambiaron")
            obsoletos = _archivos_obsoletos(instalacion, {m.filename[len(prefijo):] for m in miembros}) if instalacion else []
    except zipfile.BadZipFile:
        raise ActualizacionError("El paquete está dañado.")
    except OSError as e:
        raise ActualizacionError(f"No se pudo preparar el paquete: {e}")
    with open(os.path.join(temporal, "eliminar.txt"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(obsoletos))
    raiz = os.path.join(destino, *prefijo.rstrip("/").split("/")) if prefijo else destino
    os.makedirs(raiz, exist_ok=True)
    return raiz


def _nombre_exe():
    return os.path.basename(sys.executable) if puede_instalar() else "Gestor_SSCC.exe"


def _prefijo_de_la_app(miembros, exe):
    """Carpeta del zip que contiene el .exe y _internal ('Gestor_SSCC/'), o '' si están en la raíz."""
    nombres = [m.filename for m in miembros]
    for prefijo in ("", *sorted({n.split("/")[0] + "/" for n in nombres if "/" in n})):
        if exe in (n[len(prefijo):] for n in nombres if n.startswith(prefijo)) \
                and any(n.startswith(prefijo + "_internal/") for n in nombres):
            return prefijo
    raise ActualizacionError("El paquete no contiene la aplicación.")


def _es_igual(ruta, miembro):
    import zlib
    try:
        if os.path.getsize(ruta) != miembro.file_size:
            return False
        crc = 0
        with open(ruta, "rb") as f:
            for bloque in iter(lambda: f.read(_BLOQUE), b""):
                crc = zlib.crc32(bloque, crc)
        return crc == miembro.CRC
    except OSError:
        return False


def _archivos_obsoletos(instalacion, relativas_nuevas):
    """Archivos de _internal que están instalados y ya no vienen en el paquete."""
    obsoletos = []
    interna = os.path.join(instalacion, "_internal")
    for carpeta, _, archivos in os.walk(interna):
        for nombre in archivos:
            relativa = os.path.relpath(os.path.join(carpeta, nombre), instalacion).replace("\\", "/")
            if relativa not in relativas_nuevas:
                obsoletos.append(relativa.replace("/", "\\"))
    return obsoletos


def escribir_reemplazo(temporal, raiz_nueva, instalacion, exe, pid):
    """Crea el .bat que espera el cierre de la app, copia la versión nueva sobre la
    instalación (sin tocar app_config.json) y la vuelve a abrir. Devuelve su ruta."""
    def q(ruta):
        return str(ruta).replace("%", "%%")

    nombre = os.path.splitext(exe)[0]
    log = os.path.join(os.path.dirname(os.path.normpath(temporal)), "gestor_sscc_actualizacion.log")
    espera = ("powershell -NoProfile -Command \"Wait-Process -Id %PID% -Timeout 25 -ErrorAction SilentlyContinue; "
              "if ((Get-Process -Id %PID% -ErrorAction SilentlyContinue).ProcessName -eq '%NOMBRE%') { exit 1 } else { exit 0 }\"")
    lineas = [
        "@echo off",
        "chcp 65001 >nul",
        f'set "PID={int(pid)}"',
        f'set "NOMBRE={q(nombre)}"',
        f'set "ORIGEN={q(raiz_nueva)}"',
        f'set "DESTINO={q(instalacion)}"',
        f'set "TEMPORAL={q(temporal)}"',
        f'set "LOG={q(log)}"',
        espera,
        "if errorlevel 1 taskkill /F /T /PID %PID% >nul 2>&1",
        'echo [%date% %time%] Actualizando %DESTINO% >> "%LOG%"',
        'robocopy "%ORIGEN%" "%DESTINO%" /E /XF app_config.json /R:30 /W:1 /NP /NFL /NDL /NJH >> "%LOG%"',
        "if errorlevel 8 goto fallo",
        'if exist "%TEMPORAL%\\eliminar.txt" for /f "usebackq delims=" %%F in ("%TEMPORAL%\\eliminar.txt") do del /f /q "%DESTINO%\\%%F" >nul 2>&1',
        "goto abrir",
        ":fallo",
        'echo [%date% %time%] La copia fallo >> "%LOG%"',
        ":abrir",
        f'start "" "%DESTINO%\\{q(exe)}"',
        'rmdir /s /q "%TEMPORAL%"',
        '(goto) 2>nul & del "%~f0"',
        "",
    ]
    ruta = os.path.normpath(temporal) + ".bat"
    with open(ruta, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(lineas))
    return ruta


def lanzar_reemplazo(temporal, raiz_nueva):
    """Deja listo y arranca el reemplazo; la app debe cerrarse enseguida."""
    import subprocess
    if not puede_instalar():
        raise ActualizacionError("La instalación automática solo funciona en el ejecutable.")
    ruta = escribir_reemplazo(temporal, raiz_nueva, carpeta_instalacion(), os.path.basename(sys.executable), os.getpid())
    subprocess.Popen(["cmd.exe", "/c", ruta], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True,
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
