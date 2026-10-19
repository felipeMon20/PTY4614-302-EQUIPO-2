"""Cache de lectura para BBDD CLIENTES CM.xlsx (Power BI, "del equipo Power BI").

BBDD CLIENTES CM.xlsx es ~13 MB / 53k filas y se lee de forma independiente
en 5 sitios (contactos.py, instalaciones.py, mail_dialog.py,
contactos_agregar.py, general.py), cada uno pagando entre 11 y 17 segundos
de I/O porque no existe ningun cache compartido para este archivo en
DataManager. Es un export externo generado por Power BI fuera de esta app
y esta app JAMAS lo escribe, asi que no puede "migrarse" a CSV como se hizo
con Correos.xlsx (B-5.2, 18-09-2026) -- lo que se genera aqui es un espejo
CSV interno en data/cache/, regenerado automaticamente cuando el .xlsx de
origen cambia (comparando mtime), que los 5 sitios leen en su lugar
(~0.5s en vez de ~11-17s). El .xlsx sigue siendo la unica fuente de verdad;
si el cache falla por cualquier motivo, se cae a la lectura directa del
.xlsx (mismo comportamiento que existia antes de este cache)."""

import hashlib
import os

import openpyxl
import pandas as pd

from src.core.perf_log import medir

_CACHE_DIR = os.path.join(os.getcwd(), 'data', 'cache')


def _ruta_cache(ruta_xlsx):
    # Nombre del cache derivado de la ruta absoluta del .xlsx de origen (no
    # un nombre fijo): test_main.py apunta POWERBI_EXCEL_PATH a un Excel
    # mock distinto durante la suite de tests, y con un nombre fijo el cache
    # generado con datos mock quedaria con un mtime mas nuevo que el .xlsx
    # real, sirviendo datos mock como si fueran validos la proxima vez que
    # la app corra con la configuracion real (bug detectado en esta misma
    # auditoria, 23-09-2026, al correr test_main.py tras implementar esto).
    ruta_abs = os.path.abspath(ruta_xlsx)
    hash_ruta = hashlib.sha1(ruta_abs.encode('utf-8')).hexdigest()[:16]
    return os.path.join(_CACHE_DIR, f'bbdd_clientes_cm_{hash_ruta}.csv')


def _cache_vigente(ruta_xlsx, ruta_csv):
    if not os.path.exists(ruta_csv):
        return False
    return os.path.getmtime(ruta_csv) >= os.path.getmtime(ruta_xlsx)


def _limpiar_cache_huerfano(ruta_csv_vigente):
    """Deja un único archivo en _CACHE_DIR: el de la fuente que se acaba de
    leer con éxito (`ruta_csv_vigente`). Corregido (25-09-2026): el nombre
    del cache depende del hash de la ruta absoluta de origen (ver
    _ruta_cache) para no mezclar datos reales con datos mock -- pero cada
    ruta de origen distinta genera su propio archivo, y ninguno se borraba
    nunca. En la práctica esto acumuló ~65 archivos huérfanos en
    data/cache/ (detectado 25-09-2026): la mayoría de tests unitarios de
    PowerBiDirectorEmpresaLoaderThread/ContactosAddDialog usan
    tempfile.TemporaryDirectory() para simular el .xlsx de Power BI -- la
    carpeta temporal se autodestruye al terminar el test, pero el cache que
    quedó apuntando a esa ruta ya inexistente no. Se ejecuta después de una
    lectura exitosa (nunca antes, para no dejar data/cache/ sin ningún
    archivo válido si la regeneración fallara)."""
    try:
        if not os.path.isdir(_CACHE_DIR):
            return
        nombre_vigente = os.path.basename(ruta_csv_vigente)
        for nombre in os.listdir(_CACHE_DIR):
            if nombre == nombre_vigente:
                continue
            if nombre.startswith('bbdd_clientes_cm_') and nombre.endswith('.csv'):
                try:
                    os.remove(os.path.join(_CACHE_DIR, nombre))
                except OSError:
                    pass
    except OSError:
        pass


def _regenerar_cache(ruta_xlsx, ruta_csv):
    # openpyxl read_only=True: mismo patron ya validado en
    # PowerBiDirectorEmpresaLoaderThread (src/ui/general.py) -- mas rapido
    # que pd.read_excel por defecto para un archivo de este tamano.
    wb = openpyxl.load_workbook(ruta_xlsx, read_only=True, data_only=True)
    # Primera hoja por posicion (wb[wb.sheetnames[0]]), NO wb.active: en
    # BBDD CLIENTES CM.xlsx la hoja "activa" (la pestaña seleccionada al
    # guardar el archivo) es "Report", mientras que los 5 sitios que leian
    # este archivo con pd.read_excel(ruta) siempre usaron sheet_name=0 por
    # defecto, es decir la primera hoja ("Clientes Camiones"). Detectado
    # durante esta auditoria (23-09-2026) al comparar el cache contra una
    # lectura directa -- wb.active habria devuelto la hoja equivocada.
    ws = wb[wb.sheetnames[0]]
    filas = list(ws.iter_rows(values_only=True))
    wb.close()

    if not filas:
        df = pd.DataFrame()
    else:
        headers = [str(h).strip() if h is not None else "" for h in filas[0]]
        df = pd.DataFrame(filas[1:], columns=headers)

    os.makedirs(_CACHE_DIR, exist_ok=True)
    df.to_csv(ruta_csv, index=False, encoding='utf-8-sig')


def leer_bbdd_clientes_cm(ruta_xlsx, columnas=None):
    """Devuelve el DataFrame completo de BBDD CLIENTES CM.xlsx, usando (y
    regenerando si hace falta) el espejo CSV de data/cache/. Sin dtype
    forzado a proposito: se lee con la inferencia de tipos por defecto de
    pandas para reproducir el mismo comportamiento (NaN en vacios, columnas
    numericas como int/float) que ya esperan los 5 sitios que llamaban
    pd.read_excel(ruta_xlsx) directamente.

    `columnas` (opcional): lee solo esas columnas del cache (las que no
    existan se ignoran). La inferencia de tipos es por columna, así que el
    resultado es igual al de leer todo y quedarse con ellas, pero mucho más
    liviano para el hilo que lo lee."""
    if not ruta_xlsx or not os.path.exists(ruta_xlsx):
        return pd.DataFrame()

    usecols = None
    if columnas is not None:
        pedidas = set(columnas)
        usecols = lambda c: c in pedidas

    ruta_csv = _ruta_cache(ruta_xlsx)
    try:
        if not _cache_vigente(ruta_xlsx, ruta_csv):
            with medir("BBDD CLIENTES CM: regenerar cache CSV", hilo="WORKER"):
                _regenerar_cache(ruta_xlsx, ruta_csv)
        with medir("BBDD CLIENTES CM: lectura desde cache CSV", hilo="WORKER"):
            df = pd.read_csv(ruta_csv, usecols=usecols)
        _limpiar_cache_huerfano(ruta_csv)
        return df
    except Exception:
        # Fallback: si el cache falla por cualquier motivo (csv corrupto,
        # permisos, disco lleno, etc.), se cae al comportamiento anterior a
        # este cache -- lectura directa del .xlsx.
        try:
            return pd.read_excel(ruta_xlsx, usecols=usecols)
        except Exception:
            return pd.DataFrame()
