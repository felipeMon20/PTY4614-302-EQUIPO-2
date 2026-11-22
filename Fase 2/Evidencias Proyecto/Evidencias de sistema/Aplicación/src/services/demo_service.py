"""Restauración de los datos de demostración: copia la carpeta base (datos_prueba_base)
sobre datos_prueba. Solo trabaja con las dos carpetas que recibe; no conoce los datos reales."""
import os
import shutil


def restaurar_datos_demostracion(base, destino):
    """Copia cada archivo de `base` a `destino`, reemplazando lo que haya.
    Devuelve los nombres copiados."""
    if os.path.abspath(base) == os.path.abspath(destino):
        raise ValueError("La carpeta base y el destino son la misma.")
    if not os.path.isdir(base):
        raise FileNotFoundError(f"No se encuentra la carpeta base: {base}")
    os.makedirs(destino, exist_ok=True)
    copiados = []
    for nombre in sorted(os.listdir(base)):
        origen = os.path.join(base, nombre)
        if os.path.isfile(origen):
            shutil.copy2(origen, os.path.join(destino, nombre))
            copiados.append(nombre)
    return copiados
