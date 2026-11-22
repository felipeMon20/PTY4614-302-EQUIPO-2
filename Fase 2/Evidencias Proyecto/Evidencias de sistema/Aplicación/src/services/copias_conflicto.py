"""Copias de conflicto que OneDrive/SharePoint deja junto a los archivos de datos
(ej. LogApp-NOMBREEQUIPO.csv). Lógica pura, sin interfaz: detecta las copias,
resume en qué difieren del original y las elimina."""
import csv
import os
import re
from collections import Counter

import config.settings
from config.rutas import ARCHIVOS_DE_DATOS, nombres_aceptados

MUESTRA_FILAS = 5
# Archivos de la app cuyo original se conserva; el resto de la carpeta no se toca
_SUFIJO = r"-([A-Za-z0-9_\-]{1,40})"


def _carpetas_de_datos():
    carpetas = []
    candidatas = [getattr(config.settings, "DATA_DIR", "")]
    candidatas += [getattr(config.settings, clave, "") for clave in ARCHIVOS_DE_DATOS]
    for ruta in candidatas:
        if not ruta:
            continue
        carpeta = ruta if os.path.isdir(ruta) else os.path.dirname(ruta)
        if carpeta and os.path.isdir(carpeta) and carpeta not in carpetas:
            carpetas.append(carpeta)
    return carpetas


def _patrones():
    """[(patron, etiqueta, nombre_original)] para cada archivo estándar."""
    patrones = []
    for clave, (etiqueta, _estandar, _oblig) in ARCHIVOS_DE_DATOS.items():
        for nombre in nombres_aceptados(clave):
            raiz, ext = os.path.splitext(nombre)
            patrones.append((re.compile("^" + re.escape(raiz) + _SUFIJO + re.escape(ext) + "$", re.IGNORECASE),
                             etiqueta, nombre))
    return patrones


def _es_copia(nombre):
    """(etiqueta, nombre_original, equipo) si `nombre` es una copia de conflicto."""
    for patron, etiqueta, original in _patrones():
        m = patron.match(nombre)
        if m:
            return etiqueta, original, m.group(1)
    return None


def buscar_copias():
    """Copias de conflicto presentes junto a los archivos de datos."""
    copias = []
    for carpeta in _carpetas_de_datos():
        try:
            nombres = os.listdir(carpeta)
        except OSError:
            continue
        minusculas = {n.lower(): n for n in nombres}
        for nombre in nombres:
            hallazgo = _es_copia(nombre)
            if not hallazgo:
                continue
            etiqueta, original, equipo = hallazgo
            ruta = os.path.join(carpeta, nombre)
            if not os.path.isfile(ruta):
                continue
            ruta_original = os.path.join(carpeta, minusculas.get(original.lower(), original))
            copias.append({"copia": ruta, "original": ruta_original if os.path.exists(ruta_original) else "",
                           "archivo": etiqueta, "equipo": equipo, "nombre": nombre,
                           "modificado": os.path.getmtime(ruta), "tamano": os.path.getsize(ruta)})
    return sorted(copias, key=lambda c: c["modificado"], reverse=True)


def _leer_filas(ruta):
    """{hoja: [filas como listas de texto]}; la primera fila es el encabezado.
    Los CSV usan una sola hoja ''."""
    if ruta.lower().endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
        try:
            return {h.title: [["" if v is None else str(v).strip() for v in fila]
                              for fila in h.iter_rows(values_only=True) if any(v is not None for v in fila)]
                    for h in wb.worksheets}
        finally:
            wb.close()
    with open(ruta, "r", encoding="utf-8-sig", newline="") as f:
        return {"": [[c.strip() for c in fila] for fila in csv.reader(f) if any(fila)]}


_COLUMNAS_IDENTIDAD = ("VIN", "CHASIS", "RAZÓN SOCIAL", "NOMBRE", "ASUNTO")


def _identidad(fila, indice):
    """Texto corto que identifica un registro: su ID y un par de columnas reconocibles."""
    partes = [fila[0]] if fila else []
    for nombre in _COLUMNAS_IDENTIDAD:
        pos = indice.get(nombre)
        if pos is not None and pos < len(fila) and fila[pos] and len(partes) < 3:
            partes.append(fila[pos])
    return " · ".join(partes)


def _comparar_hoja(filas_c, filas_o, acum):
    if not filas_c or not filas_o:
        acum["nuevos_copia"] += max(len(filas_c) - 1, 0)
        acum["nuevos_original"] += max(len(filas_o) - 1, 0)
        return
    enc_c, enc_o = filas_c[0], filas_o[0]
    datos_c, datos_o = filas_c[1:], filas_o[1:]
    llave = enc_c[0]
    ids_c, ids_o = [f[0] for f in datos_c if f], [f[0] for f in datos_o if f]
    unicas = (llave in enc_o and enc_o.index(llave) == 0 and len(set(ids_c)) == len(ids_c) == len(datos_c)
              and len(set(ids_o)) == len(ids_o) == len(datos_o) and "" not in ids_c and "" not in ids_o)
    if not unicas:
        # Sin identificador único: se comparan filas completas
        c, o = Counter(map(tuple, datos_c)), Counter(map(tuple, datos_o))
        acum["modo_filas"] = True
        acum["nuevos_copia"] += sum((c - o).values())
        acum["nuevos_original"] += sum((o - c).values())
        for fila in list(c - o)[:MUESTRA_FILAS]:
            acum["ej_nuevos"].append(" | ".join(fila)[:160])
        return
    por_id_c, por_id_o = {f[0]: f for f in datos_c}, {f[0]: f for f in datos_o}
    indice_c = {n.upper(): i for i, n in enumerate(enc_c)}
    acum["nuevos_copia"] += len(por_id_c.keys() - por_id_o.keys())
    acum["nuevos_original"] += len(por_id_o.keys() - por_id_c.keys())
    for id_ in por_id_c.keys() - por_id_o.keys():
        if len(acum["ej_nuevos"]) < MUESTRA_FILAS:
            acum["ej_nuevos"].append(_identidad(por_id_c[id_], indice_c))
    comunes = [n for n in enc_c if n in enc_o]
    pos_c, pos_o = {n: enc_c.index(n) for n in comunes}, {n: enc_o.index(n) for n in comunes}
    for id_ in por_id_c.keys() & por_id_o.keys():
        fc, fo = por_id_c[id_], por_id_o[id_]
        difieren = [n for n in comunes[1:]
                    if (fc[pos_c[n]] if pos_c[n] < len(fc) else "") != (fo[pos_o[n]] if pos_o[n] < len(fo) else "")]
        if not difieren:
            continue
        acum["modificados"] += 1
        acum["columnas"].update(difieren)
        if len(acum["ej_modificados"]) < MUESTRA_FILAS:
            n = difieren[0]
            v_c = fc[pos_c[n]] if pos_c[n] < len(fc) else ""
            v_o = fo[pos_o[n]] if pos_o[n] < len(fo) else ""
            acum["ej_modificados"].append(
                f"{_identidad(fc, indice_c)} — {n}: copia «{v_c[:40] or 'vacío'}», original «{v_o[:40] or 'vacío'}»")


def comparar(info):
    """Resume la diferencia entre la copia y su original y da un veredicto
    simple. Solo lee. nivel: 'ok' (se puede eliminar), 'viejo' (la copia quedó
    desfasada) o 'revisar' (la copia tiene algo que el original no tiene)."""
    base = {"error": "", "sin_original": False, "nivel": "revisar", "veredicto": ""}
    if not info["original"]:
        base.update(sin_original=True, veredicto="El original no existe: esta copia es la única versión.")
        return base
    try:
        hojas_c, hojas_o = _leer_filas(info["copia"]), _leer_filas(info["original"])
    except Exception as e:
        base["error"] = f"No se pudo leer para comparar: {e}"
        return base
    acum = {"nuevos_copia": 0, "nuevos_original": 0, "modificados": 0, "columnas": Counter(),
            "ej_nuevos": [], "ej_modificados": [], "modo_filas": False}
    for hoja in sorted(set(hojas_c) | set(hojas_o)):
        _comparar_hoja(hojas_c.get(hoja, []), hojas_o.get(hoja, []), acum)
    copia_mas_nueva = info["modificado"] > os.path.getmtime(info["original"])
    base.update(acum, copia_mas_nueva=copia_mas_nueva, columnas=acum["columnas"].most_common(5))
    if not acum["nuevos_copia"] and not acum["modificados"] and not acum["nuevos_original"]:
        base.update(nivel="ok", veredicto="Idéntica al original. Se puede eliminar sin perder nada.")
    elif not acum["nuevos_copia"] and not copia_mas_nueva:
        base.update(nivel="viejo", veredicto="Versión antigua: el original ya tiene todo lo de la copia y es más reciente. "
                                              "Se puede eliminar.")
    elif not acum["nuevos_copia"] and not acum["modificados"]:
        base.update(nivel="ok", veredicto="La copia no tiene nada que el original no tenga. Se puede eliminar.")
    else:
        base.update(nivel="revisar", veredicto="Conviene revisar: la copia tiene datos que el original no tiene "
                                                "o más recientes que él.")
    return base

_CACHE_COMPARACION = {}


def _clave_cache(info):
    """La comparación solo cambia si cambia la copia o su original."""
    original = info.get("original") or ""
    try:
        marca_original = (os.path.getmtime(original), os.path.getsize(original)) if original else (0, 0)
    except OSError:
        marca_original = (-1, -1)
    return (info["copia"], info["modificado"], info["tamano"], original, marca_original)


def resultado_en_cache(info):
    """Resultado de `comparar` ya calculado para esta copia, o None."""
    return _CACHE_COMPARACION.get(_clave_cache(info))


def comparar_cacheado(info):
    """`comparar` con memoria: leer y cruzar dos archivos completos tarda cientos de ms
    y la pestaña de conflictos se vuelve a pintar con cada recarga. Los errores no se guardan."""
    clave = _clave_cache(info)
    resultado = _CACHE_COMPARACION.get(clave)
    if resultado is None:
        resultado = comparar(info)
        if not resultado["error"]:
            if len(_CACHE_COMPARACION) > 50:
                _CACHE_COMPARACION.clear()
            _CACHE_COMPARACION[clave] = resultado
    return resultado


def eliminar(info, crear_backup):
    """Respalda la copia con `crear_backup(ruta) -> bool` y la elimina. Solo
    actúa sobre archivos que siguen siendo copias de conflicto."""
    ruta = info["copia"]
    if not _es_copia(os.path.basename(ruta)) or not os.path.isfile(ruta):
        return False, "El archivo ya no es una copia de conflicto."
    if not crear_backup(ruta):
        return False, "No se pudo crear el respaldo previo; no se eliminó nada."
    try:
        os.remove(ruta)
    except PermissionError:
        return False, "El archivo está abierto o bloqueado."
    except OSError as e:
        return False, str(e)
    return True, ""

