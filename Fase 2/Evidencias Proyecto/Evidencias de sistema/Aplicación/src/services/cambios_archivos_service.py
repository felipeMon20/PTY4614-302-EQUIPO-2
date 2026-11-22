"""Detección de cambios externos en los archivos que vigila la aplicación además del Registro Maestro
(Provisiones y Contactos). Lógica pura, sin interfaz.

Cada archivo se resume en una instantánea {clave de fila: datos} guardada en data/cache (local, no en la
carpeta sincronizada); al avisar el vigilante de archivos se lee de nuevo y se comparan las dos, igual que
ExcelReader hace con el Registro Maestro. Los cambios salen en el mismo formato que usa el panel de
notificaciones: tipo (Alta, Baja, Modificación), VIN (el identificador a mostrar), campo, viejo y nuevo."""
import hashlib
import logging
import os
import pickle
import shutil
import time
import uuid

import pandas as pd

import config.settings

logger = logging.getLogger(__name__)

ETIQUETA_RM = "Registro Maestro"
ENTIDAD_RM = ("unidad", "unidades", "f")
# Cantidad de cambios a partir de la cual se asume un cambio de formato y no uno real (igual que ExcelReader)
MAX_CAMBIOS_REALES = 200

ARCHIVOS = {
    "provisiones": {"etiqueta": "Provisiones", "entidad": ("registro", "registros", "m"), "ruta": "PROVISION_EXCEL_PATH"},
    "contactos": {"etiqueta": "Contactos", "entidad": ("contacto", "contactos", "m"), "ruta": "CONTACTOS_EXCEL_PATH"},
    "casos_cm": {"etiqueta": "Oportunidades CM", "entidad": ("caso", "casos", "m"), "ruta": "CASOS_BAJA_CM_PATH",
                 "fila": "Caso"},
}

TIPO_CARGA_MASIVA = "Carga masiva"
# Columnas listadas en el aviso de una carga masiva (las que más filas cambiaron)
MAX_CAMPOS_CARGA_MASIVA = 12
_ESTADOS_CASO_TEXTO = {
    "PENDIENTE": "Pendiente", "REAPARECIDO": "Reapareció en 3PC", "MANTENIDO": "Mantenido",
    "CONFIRMADA_BAJA": "Baja confirmada", "CONTRATO_CERRADO": "Contrato cerrado",
}

_COLUMNAS_CLAVE_PROV = ("AÑO - MES", "VIN", "ID CONTRATO")
_IGNORADAS_CONTACTOS = ("ID", "Fecha de extracción")


def etiqueta(clave):
    return ARCHIVOS[clave]["etiqueta"]


def entidad(clave):
    return ARCHIVOS[clave]["entidad"]


def ruta_de(clave):
    return getattr(config.settings, ARCHIVOS[clave]["ruta"], "") or ""


def _ruta_instantanea(clave, ruta):
    carpeta = os.path.join(os.getcwd(), "data", "cache")
    os.makedirs(carpeta, exist_ok=True)
    huella = hashlib.md5(os.path.abspath(ruta or "").lower().encode("utf-8")).hexdigest()[:12]
    return os.path.join(carpeta, f"snapshot_{clave}_{huella}.pkl")


def _texto(valor):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    if texto.lower() in ("nan", "nat", "none"):
        return ""
    return texto[:-2] if texto.endswith(".0") and texto[:-2].lstrip("-").isdigit() else texto


def _leer_hojas(ruta, hojas):
    """{hoja: DataFrame de texto}; con `hojas=None`, solo la primera. Se lee desde una copia temporal: el
    original puede estar bloqueado por OneDrive o abierto en Excel."""
    carpeta_temp = os.path.join(os.getcwd(), "data", "temp")
    os.makedirs(carpeta_temp, exist_ok=True)
    copia = os.path.join(carpeta_temp, f"ghost_cmp_{uuid.uuid4().hex}{os.path.splitext(ruta)[1]}")
    origen = ruta
    for intento in range(3):
        try:
            shutil.copy2(ruta, copia)
            origen = copia
            break
        except PermissionError:
            if intento < 2:
                time.sleep(1)
    try:
        with pd.ExcelFile(origen) as xls:
            if hojas is None:
                return {xls.sheet_names[0]: xls.parse(0, dtype=str)}
            return {h: xls.parse(h, dtype=str) for h in hojas if h in xls.sheet_names}
    finally:
        if origen == copia:
            try:
                os.remove(copia)
            except OSError:
                pass


def _instantanea_contactos(ruta):
    # Como ContactosLoaderThread: la primera hoja del libro
    df = next(iter(_leer_hojas(ruta, None).values()), pd.DataFrame())
    datos = {}
    if df.empty or "ID" not in df.columns:
        return datos
    for _, fila in df.iterrows():
        id_ = _texto(fila["ID"])
        if not id_:
            continue
        nombre = " ".join(p for p in (_texto(fila.get("Nombre")), _texto(fila.get("Apellidos"))) if p) or f"ID {id_}"
        datos[f"id:{id_}"] = {
            "id": nombre, "es_vin": False, "contexto": "",
            "vals": {c: _texto(fila[c]) for c in df.columns if c not in _IGNORADAS_CONTACTOS},
        }
    return datos


def _instantanea_provisiones(ruta):
    hojas = _leer_hojas(ruta, ["Prov", "Variables", "Planes"])
    datos = {}
    prov = hojas.get("Prov", pd.DataFrame())
    if not prov.empty and all(c in prov.columns for c in ("AÑO - MES", "VIN")):
        vistas = {}
        for _, fila in prov.iterrows():
            partes = [_texto(fila.get(c)) for c in _COLUMNAS_CLAVE_PROV]
            base = "prov:" + "|".join(partes)
            vistas[base] = vistas.get(base, 0) + 1
            clave = base if vistas[base] == 1 else f"{base}#{vistas[base]}"
            datos[clave] = {
                "id": partes[1] or "(sin VIN)", "es_vin": bool(partes[1]), "contexto": partes[0],
                "vals": {c: _texto(fila[c]) for c in prov.columns if c not in _COLUMNAS_CLAVE_PROV},
            }
    for hoja, prefijo, etiqueta_fila in (("Variables", "var", "Variable"), ("Planes", "plan", "Plan")):
        df = hojas.get(hoja, pd.DataFrame())
        if df.empty:
            continue
        for _, fila in df.iterrows():
            nombre = _texto(fila.iloc[0])
            if not nombre:
                continue
            datos[f"{prefijo}:{nombre}"] = {
                "id": nombre, "es_vin": False, "contexto": etiqueta_fila,
                "vals": {c: _texto(fila[c]) for c in df.columns[1:]},
            }
    return datos


def _instantanea_casos_cm(ruta):
    """Casos de Oportunidades CM: solo el estado del caso (sus datos CM ya se vigilan en el Registro Maestro)."""
    from src.services import cm_bajas_service
    df = cm_bajas_service.leer_casos_baja_cm(ruta)
    datos = {}
    if df.empty or "CASO_ID" not in df.columns:
        return datos
    for _, fila in df.iterrows():
        caso = _texto(fila.get("CASO_ID"))
        if not caso:
            continue
        origen = _texto(fila.get("ORIGEN_CASO"))
        estado = _texto(fila.get("ESTADO_CASO"))
        vin = _texto(fila.get("VIN"))
        datos[f"caso:{caso}"] = {
            "id": vin or f"Caso {caso}", "es_vin": bool(vin),
            "contexto": cm_bajas_service.ORIGEN_CASO_MOTIVO_MAP.get(origen, origen),
            "vals": {"Estado del caso": _ESTADOS_CASO_TEXTO.get(estado.upper(), estado)},
        }
    return datos


def leer_instantanea(clave, ruta):
    if clave == "contactos":
        return _instantanea_contactos(ruta)
    if clave == "provisiones":
        return _instantanea_provisiones(ruta)
    if clave == "casos_cm":
        return _instantanea_casos_cm(ruta)
    raise ValueError(f"Archivo no vigilado: {clave}")


def resumir_carga_masiva(cambios):
    """Un cambio de cientos de filas (importación del 3PC, corrección en bloque) se resume en un solo aviso:
    cuántas filas cambió cada columna, en vez de no avisar nada."""
    claves = lambda filas: {c.get("clave", c["VIN"]) for c in filas}
    total = len(claves(cambios))
    grupos = {}
    for c in cambios:
        nombre = {"Alta": "Agregados", "Baja": "Eliminados"}.get(c["tipo"], str(c["campo"]).split(" (")[0])
        grupos.setdefault(nombre, []).append(c)
    orden = sorted(grupos.items(), key=lambda g: -len(claves(g[1])))
    resumen_ = []
    for nombre, filas in orden[:MAX_CAMPOS_CARGA_MASIVA]:
        n = len(claves(filas))
        resumen_.append({"tipo": TIPO_CARGA_MASIVA, "VIN": nombre, "clave": f"campo:{nombre}", "es_vin": False,
                         "campo": f"{n} {'fila' if n == 1 else 'filas'}", "viejo": "", "nuevo": "", "total": total})
    if len(orden) > MAX_CAMPOS_CARGA_MASIVA:
        resto = len(orden) - MAX_CAMPOS_CARGA_MASIVA
        resumen_.append({"tipo": TIPO_CARGA_MASIVA, "VIN": f"y {resto} columnas más", "clave": "campo:resto",
                         "es_vin": False, "campo": "", "viejo": "", "nuevo": "", "total": total})
    return resumen_


def comparar(viejo, nuevo, fila="Registro"):
    """Cambios entre dos instantáneas, en el formato del panel de notificaciones."""
    cambios = []
    for k in nuevo.keys() - viejo.keys():
        n = nuevo[k]
        cambios.append({"tipo": "Alta", "VIN": n["id"], "clave": k, "es_vin": n["es_vin"],
                        "campo": f"{fila} nuevo" + (f" ({n['contexto']})" if n["contexto"] else ""),
                        "viejo": "-", "nuevo": "Agregado"})
    for k in viejo.keys() - nuevo.keys():
        v = viejo[k]
        cambios.append({"tipo": "Baja", "VIN": v["id"], "clave": k, "es_vin": v["es_vin"],
                        "campo": f"{fila} eliminado" + (f" ({v['contexto']})" if v["contexto"] else ""),
                        "viejo": "Existía", "nuevo": "Eliminado"})
    for k in viejo.keys() & nuevo.keys():
        v, n = viejo[k], nuevo[k]
        for col in n["vals"]:
            antes, despues = v["vals"].get(col, ""), n["vals"][col]
            if antes != despues:
                cambios.append({"tipo": "Modificación", "VIN": n["id"], "clave": k, "es_vin": n["es_vin"],
                                "campo": col + (f" ({n['contexto']})" if n["contexto"] else ""),
                                "viejo": antes or "Vacío", "nuevo": despues or "Vacío"})
    return cambios


def _guardar(ruta_pkl, datos):
    try:
        with open(ruta_pkl, "wb") as f:
            pickle.dump(datos, f)
    except Exception as e:
        logger.warning(f"No se pudo guardar la base de comparación de {os.path.basename(ruta_pkl)}: {e}")


def comparar_y_actualizar(clave, ruta):
    """Cambios desde la última instantánea; deja la nueva como base. La primera vez solo crea la base."""
    ruta_pkl = _ruta_instantanea(clave, ruta)
    nuevo = leer_instantanea(clave, ruta)
    if not nuevo:
        return []
    if not os.path.exists(ruta_pkl):
        _guardar(ruta_pkl, nuevo)
        return []
    try:
        with open(ruta_pkl, "rb") as f:
            viejo = pickle.load(f)
    except Exception as e:
        logger.warning(f"Base de comparación ilegible ({clave}): {e}")
        _guardar(ruta_pkl, nuevo)
        return []
    _guardar(ruta_pkl, nuevo)
    if clave == "casos_cm":
        from src.services import cm_bajas_service
        if cm_bajas_service.escritura_propia_reciente():
            return []  # lo escribió esta misma app: la base ya quedó al día
    cambios = comparar(viejo, nuevo, ARCHIVOS[clave].get("fila", "Registro"))
    if len(cambios) > MAX_CAMBIOS_REALES:
        logger.info(f"{clave}: {len(cambios)} cambios; se avisan resumidos como carga masiva.")
        return resumir_carga_masiva(cambios)
    return cambios


def actualizar_base(clave, ruta):
    """Deja la base al día con el archivo tal como está (tras un guardado propio, o la primera vez)."""
    nuevo = leer_instantanea(clave, ruta)
    if nuevo:
        _guardar(_ruta_instantanea(clave, ruta), nuevo)


def asegurar_base(clave, ruta):
    """Crea la base si todavía no existe (no pisa la de una sesión anterior)."""
    if not os.path.exists(_ruta_instantanea(clave, ruta)):
        actualizar_base(clave, ruta)


def resumen(cambios, entidad_):
    """«6 unidades» / «sin diferencias»: cuántas filas distintas cambiaron."""
    n = len({c.get("clave", c["VIN"]) for c in cambios})
    if not n:
        return "sin diferencias"
    return f"{n} {entidad_[0] if n == 1 else entidad_[1]}"
