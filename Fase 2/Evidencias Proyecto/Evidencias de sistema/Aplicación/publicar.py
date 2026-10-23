"""Publica la versión generada por exe.bat: comprime dist/Gestor_SSCC en Gestor_SSCC.zip,
lo sube a la carpeta compartida (reemplazando el anterior) y escribe version.json al final,
para que nadie vea la versión nueva antes de que el zip esté completo."""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime

RAIZ = os.path.dirname(os.path.abspath(__file__))
CARPETA_APP = os.path.join(RAIZ, "dist", "Gestor_SSCC")
NOMBRE_ZIP = "Gestor_SSCC.zip"
# Lo que la app crea junto al .exe al usarse y no debe viajar en el paquete
EXCLUIDOS = {"app_config.json", "data", "logs"}


def leer_constante(nombre):
    with open(os.path.join(RAIZ, "config", "settings.py"), encoding="utf-8") as f:
        encontrado = re.search(rf'^{nombre}\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
    if not encontrado:
        sys.exit(f"No se encontró {nombre} en config/settings.py.")
    return encontrado.group(1)


def carpeta_destino(arg):
    if arg:
        return arg
    with open(os.path.join(RAIZ, "app_config.json"), encoding="utf-8") as f:
        config = json.load(f)
    base = config.get("DATA_DIR") or os.path.dirname(config.get("EXCEL_PATH", ""))
    if not base:
        sys.exit("app_config.json no tiene DATA_DIR ni EXCEL_PATH; usa --destino.")
    return os.path.join(os.path.dirname(os.path.normpath(base)), leer_constante("CARPETA_ACTUALIZACIONES"))


def partes(version):
    return tuple(int(p) for p in version.split("."))


def comprimir(destino_zip):
    archivos = []
    for carpeta, subcarpetas, nombres in os.walk(CARPETA_APP):
        relativa = os.path.relpath(carpeta, CARPETA_APP)
        if relativa == ".":
            subcarpetas[:] = [d for d in subcarpetas if d not in EXCLUIDOS]
            nombres = [n for n in nombres if n not in EXCLUIDOS]
        archivos += [os.path.join(carpeta, n) for n in nombres]
    with zipfile.ZipFile(destino_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for i, ruta in enumerate(archivos, 1):
            z.write(ruta, os.path.join("Gestor_SSCC", os.path.relpath(ruta, CARPETA_APP)))
            if i % 500 == 0:
                print(f"  {i} de {len(archivos)} archivos")
    print(f"  {len(archivos)} archivos comprimidos")


def huella(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--notas", default=None, help="Texto que verá la persona en el aviso")
    ap.add_argument("--destino", default=None, help="Carpeta compartida (por defecto, junto a la carpeta de datos)")
    ap.add_argument("--forzar", action="store_true", help="Publica aunque la versión no sea mayor que la publicada")
    args = ap.parse_args()

    version = leer_constante("APP_VERSION")
    destino = carpeta_destino(args.destino)
    if not os.path.isfile(os.path.join(CARPETA_APP, "Gestor_SSCC.exe")):
        sys.exit("No existe dist\\Gestor_SSCC\\Gestor_SSCC.exe. Ejecuta primero exe.bat.")
    if not os.path.isdir(destino):
        sys.exit(f"No existe la carpeta de destino:\n  {destino}")

    ruta_manifiesto = os.path.join(destino, "version.json")
    if os.path.isfile(ruta_manifiesto) and not args.forzar:
        try:
            with open(ruta_manifiesto, encoding="utf-8-sig") as f:
                publicada = json.load(f)["version"]
            if partes(version) <= partes(publicada):
                sys.exit(f"La versión publicada ({publicada}) ya es igual o mayor que APP_VERSION ({version}). "
                         "Sube APP_VERSION en config/settings.py y compila de nuevo.")
        except (OSError, ValueError, KeyError):
            pass

    notas = args.notas
    if notas is None:
        notas = input("Notas de la versión (una línea): ").strip() if sys.stdin and sys.stdin.isatty() else ""

    print(f"Publicando la versión {version} en:\n  {destino}")
    with tempfile.TemporaryDirectory(prefix="publicar_gestor_") as tmp:
        zip_local = os.path.join(tmp, NOMBRE_ZIP)
        print("Comprimiendo...")
        comprimir(zip_local)
        tamano, sha256 = os.path.getsize(zip_local), huella(zip_local)

        print("Subiendo el zip (reemplaza al anterior)...")
        subiendo = os.path.join(destino, NOMBRE_ZIP + ".subiendo")
        shutil.copyfile(zip_local, subiendo)
        os.replace(subiendo, os.path.join(destino, NOMBRE_ZIP))

    manifiesto = {"version": version, "notas": notas, "zip": NOMBRE_ZIP, "tamano": tamano,
                  "sha256": sha256, "publicado": datetime.now().strftime("%Y-%m-%d %H:%M")}
    with open(ruta_manifiesto, "w", encoding="utf-8") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
    print(f"Listo: versión {version}, {tamano / 1024 / 1024:.0f} MB. version.json escrito al final.")


if __name__ == "__main__":
    main()
