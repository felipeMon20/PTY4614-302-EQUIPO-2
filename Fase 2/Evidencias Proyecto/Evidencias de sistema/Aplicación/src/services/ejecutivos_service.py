"""Directorio de ejecutivos (nombre -> correo) en Ejecutivos_VC.csv.

PruebasFM solo guarda el nombre del ejecutivo como texto en cada unidad, así
que este archivo es la tabla aparte que lo relaciona con su correo: una fila
por ejecutivo con un id estable (EJE-001...), su nombre tal como aparece en
PruebasFM, el correo y, opcionalmente, alias con otras grafías del mismo
nombre separadas por "|". Vive junto al historial de correos (carpeta
compartida), así que ambos PCs ven y editan los mismos datos.
"""
import csv
import logging
import os
import re
import unicodedata
import uuid

import pandas as pd

import config.settings
from src.services import mail_registro

logger = logging.getLogger(__name__)

_COLUMNAS = ["id_ejecutivo", "nombre", "correo", "alias", "activo"]
_NOMBRES_IGNORADOS = {"", "-", "nan", "none", "desconocido", "no aplica"}

# Directorio inicial de ejemplo (nombre en el RM, correo, alias). Datos ficticios
# de esta versión pública; en producción el archivo lo mantiene el negocio.
_SEMILLA = [
    ("Andres Muestra Silva", "andres.muestra.silva@ejemplo.com", ""),
    ("Carlos Ficticio Diaz", "carlos.ficticio.diaz@ejemplo.com", ""),
    ("Claudia Test Fuentes", "claudia.test.fuentes@ejemplo.com", ""),
    ("Juan Prueba Soto", "juan.prueba.soto@ejemplo.com", "Juan Carlos Prueba"),
    ("Maria Demo Rojas", "maria.demo.rojas@ejemplo.com", ""),
    ("Paula Ejemplo Muñoz", "paula.ejemplo.munoz@ejemplo.com", ""),
]


def get_ejecutivos_csv_path():
    configurada = (getattr(config.settings, 'EJECUTIVOS_PATH', '') or '').strip()
    if configurada and os.path.isdir(os.path.dirname(configurada)):
        return configurada
    return os.path.join(mail_registro._sharepoint_dir(), 'Ejecutivos_VC.csv')


def normalizar_nombre(texto):
    """Minúsculas, sin tildes ni puntuación y con espacios simples."""
    sin_tildes = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', sin_tildes.lower()).split())


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
    """Crea Ejecutivos_VC.csv con los correos conocidos si todavía no existe.
    Nunca pisa un archivo existente. Devuelve la ruta."""
    path = get_ejecutivos_csv_path()
    if os.path.exists(path):
        return path
    try:
        _escribir(path, [[f"EJE-{i:03d}", nombre, correo, alias, "SI"]
                         for i, (nombre, correo, alias) in enumerate(_SEMILLA, start=1)])
    except Exception as e:
        logger.error(f"No se pudo crear el directorio de ejecutivos: {e}")
    return path


def leer_ejecutivos():
    """Directorio completo como DataFrame de texto (vacío si no se puede leer)."""
    path = asegurar_archivo()
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    except Exception as e:
        logger.error(f"No se pudo leer el directorio de ejecutivos: {e}")
        return pd.DataFrame(columns=_COLUMNAS)
    for col in _COLUMNAS:
        if col not in df.columns:
            df[col] = ""
    return df[_COLUMNAS]


def buscar_ejecutivo(nombre, directorio=None, incluir_inactivos=False):
    """Fila (dict) del ejecutivo que corresponde a `nombre`, o None. Coincide
    por nombre o alias sin importar mayúsculas/tildes; si no hay coincidencia
    exacta, acepta un nombre más largo que contenga el nombre y apellido
    registrados (ej. "Leonardo Gomez Correa")."""
    directorio = leer_ejecutivos() if directorio is None else directorio
    consulta = normalizar_nombre(nombre)
    if not consulta or consulta in _NOMBRES_IGNORADOS or directorio.empty:
        return None
    activos = directorio if incluir_inactivos else directorio[directorio['activo'].str.strip().str.upper() != 'NO']
    candidatos = []
    for _, fila in activos.iterrows():
        claves = [normalizar_nombre(fila['nombre'])] + [normalizar_nombre(a) for a in str(fila['alias']).split('|')]
        for clave in filter(None, claves):
            if clave == consulta:
                return fila.to_dict()
            partes = clave.split()
            if len(partes) >= 2 and set(partes) <= set(consulta.split()):
                candidatos.append((len(partes), fila.to_dict()))
    if candidatos:
        return max(candidatos, key=lambda c: c[0])[1]
    return None


def correo_de(nombre, directorio=None):
    """Correo del ejecutivo o '' si no existe o está sin correo."""
    fila = buscar_ejecutivo(nombre, directorio)
    return str(fila['correo']).strip() if fila else ''


def registrar_ejecutivos_nuevos(nombres):
    """Agrega al directorio, sin correo, los ejecutivos de PruebasFM que aún
    no figuran (ni por nombre ni por alias), para que se pueda completar su
    correo en el archivo. Devuelve los nombres agregados."""
    directorio = leer_ejecutivos()
    path = get_ejecutivos_csv_path()
    pendientes, vistos = [], set()
    for nombre in nombres:
        limpio = ' '.join(str(nombre).split())
        clave = normalizar_nombre(limpio)
        if clave in _NOMBRES_IGNORADOS or clave in vistos:
            continue
        vistos.add(clave)
        if buscar_ejecutivo(limpio, directorio, incluir_inactivos=True) is None:
            pendientes.append(limpio)
    if not pendientes:
        return []
    try:
        numeros = [int(m.group(1)) for m in (re.match(r'EJE-(\d+)$', str(i)) for i in directorio['id_ejecutivo']) if m]
        siguiente = max(numeros, default=0) + 1
        filas = directorio.values.tolist()
        for i, nombre in enumerate(pendientes):
            filas.append([f"EJE-{siguiente + i:03d}", nombre, "", "", "SI"])
        _escribir(path, filas)
    except Exception as e:
        logger.error(f"No se pudieron registrar ejecutivos nuevos: {e}")
        return []
    return pendientes


_PATRON_CORREO = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _claves_de(fila):
    return {c for c in [normalizar_nombre(fila['nombre'])] + [normalizar_nombre(a) for a in str(fila['alias']).split('|')] if c}


def _validar(directorio, id_ejecutivo, nombre, correo, alias):
    """Mensaje de error o '' si los datos son válidos. El nombre y los alias no
    pueden coincidir con los de otro ejecutivo."""
    if not ' '.join(str(nombre).split()):
        return "El nombre es obligatorio."
    if correo and not _PATRON_CORREO.match(correo):
        return "El correo no tiene un formato válido."
    propias = {normalizar_nombre(nombre)} | {normalizar_nombre(a) for a in str(alias).split('|') if normalizar_nombre(a)}
    for _, fila in directorio.iterrows():
        if fila['id_ejecutivo'] == id_ejecutivo:
            continue
        repetidas = propias & _claves_de(fila)
        if repetidas:
            return f"Ya existe otro ejecutivo con ese nombre o alias: {fila['nombre']}."
    return ""


def _normalizar_alias(alias):
    vistos, salida = set(), []
    for a in str(alias).split('|'):
        limpio = ' '.join(a.split())
        clave = normalizar_nombre(limpio)
        if clave and clave not in vistos:
            vistos.add(clave)
            salida.append(limpio)
    return '|'.join(salida)


def agregar_ejecutivo(nombre, correo='', alias=''):
    """Crea un ejecutivo nuevo. Devuelve (ok, mensaje)."""
    directorio = leer_ejecutivos()
    nombre, correo = ' '.join(str(nombre).split()), str(correo).strip().lower()
    alias = _normalizar_alias(alias)
    error = _validar(directorio, None, nombre, correo, alias)
    if error:
        return False, error
    numeros = [int(m.group(1)) for m in (re.match(r'EJE-(\d+)$', str(i)) for i in directorio['id_ejecutivo']) if m]
    filas = directorio.values.tolist()
    filas.append([f"EJE-{max(numeros, default=0) + 1:03d}", nombre, correo, alias, "SI"])
    try:
        _escribir(get_ejecutivos_csv_path(), filas)
    except Exception as e:
        return False, f"No se pudo guardar el directorio (¿el archivo está abierto?): {e}"
    return True, ""


def actualizar_ejecutivo(id_ejecutivo, nombre, correo, alias, activo=True):
    """Edita un ejecutivo. Si cambia el nombre, el anterior pasa a alias para
    que las unidades de PruebasFM que aún lo usan sigan encontrando su correo.
    Devuelve (ok, mensaje)."""
    directorio = leer_ejecutivos()
    coincide = directorio['id_ejecutivo'] == id_ejecutivo
    if not coincide.any():
        return False, "El ejecutivo ya no existe en el directorio."
    anterior = directorio.loc[coincide, 'nombre'].iloc[0]
    nombre, correo = ' '.join(str(nombre).split()), str(correo).strip().lower()
    alias = _normalizar_alias(alias)
    if nombre and normalizar_nombre(nombre) != normalizar_nombre(anterior):
        alias = _normalizar_alias(f"{alias}|{anterior}")
    alias = '|'.join(a for a in alias.split('|') if normalizar_nombre(a) != normalizar_nombre(nombre))
    error = _validar(directorio, id_ejecutivo, nombre, correo, alias)
    if error:
        return False, error
    directorio.loc[coincide, ['nombre', 'correo', 'alias', 'activo']] = [nombre, correo, alias, "SI" if activo else "NO"]
    try:
        _escribir(get_ejecutivos_csv_path(), directorio.values.tolist())
    except Exception as e:
        return False, f"No se pudo guardar el directorio (¿el archivo está abierto?): {e}"
    return True, ""


def unidades_por_ejecutivo(nombres_en_unidades, directorio=None):
    """{id_ejecutivo: cantidad de unidades} contando los nombres de PruebasFM
    (una entrada por unidad) que corresponden a cada ejecutivo del directorio."""
    directorio = leer_ejecutivos() if directorio is None else directorio
    conteo = {}
    for nombre, cantidad in pd.Series(list(nombres_en_unidades)).dropna().astype(str).str.strip().value_counts().items():
        fila = buscar_ejecutivo(nombre, directorio, incluir_inactivos=True)
        if fila:
            conteo[fila['id_ejecutivo']] = conteo.get(fila['id_ejecutivo'], 0) + int(cantidad)
    return conteo
