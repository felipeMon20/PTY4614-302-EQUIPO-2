"""Prepara una copia de trabajo con los datos de prueba (ficticios) y deja
app_config.json apuntando a ella, para abrir la aplicación sin acceso a los
archivos reales de la empresa.

Uso (desde la raíz del proyecto):
    python preparar_demo.py            # crea datos_demo/ y app_config.json
    python preparar_demo.py --forzar   # vuelve a copiar y sobrescribe la config

La aplicación modifica los archivos que abre; por eso trabaja sobre la copia
datos_demo/ y deja intactos los originales de duoc/archivos de referencia.
"""
import json
import os
import shutil
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
ORIGEN = os.path.join(RAIZ, "duoc", "archivos de referencia")
DESTINO = os.path.join(RAIZ, "datos_demo")
CONFIG = os.path.join(RAIZ, "app_config.json")
OMITIR = {"cargas nuevas", "obsoletos", "app_config_referencia.json"}


def copiar_datos(forzar):
    if os.path.isdir(DESTINO) and not forzar:
        print(f"Se conserva {DESTINO} (usa --forzar para recrearla).")
        return
    if os.path.isdir(DESTINO):
        shutil.rmtree(DESTINO)
    os.makedirs(DESTINO)
    for nombre in os.listdir(ORIGEN):
        if nombre in OMITIR:
            continue
        origen = os.path.join(ORIGEN, nombre)
        if os.path.isfile(origen):
            shutil.copy2(origen, os.path.join(DESTINO, nombre))
    print(f"Datos de prueba copiados a {DESTINO}")


def escribir_config(forzar):
    if os.path.exists(CONFIG) and not forzar:
        print(f"Ya existe {CONFIG}; no se modifica (usa --forzar para sobrescribirla).")
        return
    config = {
        "DATA_DIR": DESTINO,
        "RM_JAVI_PATH": os.path.join(DESTINO, "RM_JAVI_VOLVO CONNECT.xlsx"),
        "PROVISIONES_SHAREPOINT_URL": "",
        "REPORTE_NOTAS_VENTAS_URL": "",
        "POWERBI_EMBED_URL": "",
    }
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    print(f"Configuración escrita en {CONFIG}")


if __name__ == "__main__":
    forzar = "--forzar" in sys.argv[1:]
    if not os.path.isdir(ORIGEN):
        sys.exit(f"No se encontró {ORIGEN}")
    copiar_datos(forzar)
    escribir_config(forzar)
    print("Listo. Ejecuta: python main.py")
