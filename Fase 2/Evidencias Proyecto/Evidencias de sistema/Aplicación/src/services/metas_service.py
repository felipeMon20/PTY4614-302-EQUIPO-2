"""Metas de unidades vendidas de Volvo Connect y el registro de los meses ya
cerrados (MetasVC.csv). Una fila por año y mes con la meta del equipo y, para los
meses cerrados, cuántas unidades se vendieron y cuántas estaban conectadas al
registrarlos. Vive en la carpeta de datos compartida, así que todos los PCs ven
las mismas metas."""
import csv
import logging
import os
import uuid
from datetime import datetime

import pandas as pd

import config.settings
from src.services import mail_registro

logger = logging.getLogger(__name__)

_COLUMNAS = ["anio", "mes", "meta_unidades", "vendidas", "conectadas", "registrado"]


def get_metas_csv_path():
    configurada = (getattr(config.settings, 'METAS_VC_PATH', '') or '').strip()
    if configurada and os.path.isdir(os.path.dirname(configurada)):
        return configurada
    return os.path.join(mail_registro._sharepoint_dir(), 'MetasVC.csv')


def _escribir(path, filas):
    tmp = path + f".{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
            escritor = csv.writer(f)
            escritor.writerow(_COLUMNAS)
            escritor.writerows(filas)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def asegurar_archivo():
    """Crea MetasVC.csv vacío (solo encabezado) si todavía no existe. Nunca pisa
    uno existente. Devuelve la ruta."""
    path = get_metas_csv_path()
    if not os.path.exists(path):
        try:
            _escribir(path, [])
        except Exception as e:
            logger.error(f"No se pudo crear el archivo de metas: {e}")
    return path


def _leer():
    path = asegurar_archivo()
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    except Exception as e:
        logger.error(f"No se pudo leer el archivo de metas: {e}")
        return pd.DataFrame(columns=_COLUMNAS)
    for col in _COLUMNAS:
        if col not in df.columns:
            df[col] = ""
    return df[_COLUMNAS]


def _entero(valor):
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _a_dict(df):
    filas = {}
    for fila in df.itertuples(index=False):
        anio, mes = _entero(fila.anio), _entero(fila.mes)
        if anio is None or mes is None or not 1 <= mes <= 12:
            continue
        filas[(anio, mes)] = {c: getattr(fila, c) for c in _COLUMNAS[2:]}
    return filas


def _guardar(filas):
    _escribir(get_metas_csv_path(),
              [[anio, mes] + [datos.get(c, "") for c in _COLUMNAS[2:]] for (anio, mes), datos in sorted(filas.items())])


def leer_metas():
    """{(año, mes): meta de unidades vendidas} de los meses que tienen meta."""
    metas = {}
    for clave, datos in _a_dict(_leer()).items():
        meta = _entero(datos['meta_unidades'])
        if meta is not None:
            metas[clave] = meta
    return metas


def leer_registro():
    """{(año, mes): (vendidas, conectadas)} de los meses ya registrados."""
    registro = {}
    for clave, datos in _a_dict(_leer()).items():
        vendidas, conectadas = _entero(datos['vendidas']), _entero(datos['conectadas'])
        if vendidas is not None and conectadas is not None:
            registro[clave] = (vendidas, conectadas)
    return registro


def guardar_metas(anio, metas_por_mes):
    """Guarda la meta de cada mes (1-12) del año. Conserva el registro de cierres.
    Devuelve (ok, mensaje)."""
    hoy = datetime.now()
    if any((int(anio), int(mes)) < (hoy.year, hoy.month) for mes in metas_por_mes):
        return False, "Los meses pasados no se pueden modificar."
    try:
        filas = _a_dict(_leer())
        for mes, meta in metas_por_mes.items():
            datos = filas.setdefault((int(anio), int(mes)), {})
            datos['meta_unidades'] = str(int(meta)) if meta else ""
        _guardar({k: v for k, v in filas.items() if any(str(x).strip() for x in v.values())})
    except Exception as e:
        return False, f"No se pudo guardar las metas (¿el archivo está abierto?): {e}"
    return True, ""


def registrar_cierres(cierres):
    """Registra, sin pisar los ya registrados, los meses cerrados recibidos como
    [(año, mes, vendidas, conectadas)]. Devuelve cuántos agregó."""
    try:
        filas = _a_dict(_leer())
        ahora = datetime.now().strftime('%Y-%m-%d %H:%M')
        agregados = 0
        for anio, mes, vendidas, conectadas in cierres:
            datos = filas.setdefault((int(anio), int(mes)), {})
            if _entero(datos.get('vendidas')) is not None:
                continue
            datos.update({'vendidas': str(int(vendidas)), 'conectadas': str(int(conectadas)), 'registrado': ahora})
            agregados += 1
        if agregados:
            _guardar(filas)
        return agregados
    except Exception as e:
        logger.error(f"No se pudieron registrar los cierres: {e}")
        return 0


def limpiar_registro():
    """Borra los cierres registrados (no las metas) para que se vuelvan a calcular."""
    try:
        filas = _a_dict(_leer())
        for datos in filas.values():
            datos.update({'vendidas': "", 'conectadas': "", 'registrado': ""})
        _guardar({k: v for k, v in filas.items() if any(str(x).strip() for x in v.values())})
    except Exception as e:
        return False, f"No se pudo recalcular los cierres: {e}"
    return True, ""
