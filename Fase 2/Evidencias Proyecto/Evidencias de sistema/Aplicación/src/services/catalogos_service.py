"""Catálogos editables del formulario de unidad (Catalogos_VC.csv).

Guarda, junto a Ejecutivos_VC.csv (carpeta compartida), los valores de los
combos Modelo, Industria y Tipo de servicio, las traducciones de industria
(texto en inglés de Power BI -> nombre en español) y los textos de industria
que la importación no supo traducir. Sin archivo, los combos usan los valores
del código (constants.py); el archivo solo se crea al agregar algo desde
Administración. Una fila por valor: catalogo, valor, extra, activo.
"""
import csv
import logging
import os
import re
import uuid
from datetime import datetime

import pandas as pd

from src.core.constants import DROPDOWN_OPTIONS_UNIDAD, INDUSTRIA_MAP
from src.services import ejecutivos_service

logger = logging.getLogger(__name__)

MODELO = "modelo"
INDUSTRIA = "industria"
SERVICIO = "servicio"
TRADUCCION = "traduccion"
PENDIENTE = "pendiente"
COMPLEMENTO = "complemento"
CATALOGOS_EDITABLES = (MODELO, INDUSTRIA, SERVICIO)
COMPLEMENTOS_DE_FABRICA = (("CIV", "CIV"), ("SZ", "Safety Zone"))

_COLUMNAS = ["catalogo", "valor", "extra", "activo"]
_COLUMNA_UNIDADES = {MODELO: "MODELO", INDUSTRIA: "INDUSTRIA", SERVICIO: "TIPO DE SERVICIO", COMPLEMENTO: "TIPO DE SERVICIO"}
_cache = {}
_pendientes_memoria = {}


def get_catalogos_csv_path():
    return os.path.join(os.path.dirname(ejecutivos_service.get_ejecutivos_csv_path()), 'Catalogos_VC.csv')


def _base_servicio(valor):
    return str(valor).split('+')[0].strip()


def valores_de_fabrica(catalogo):
    """Valores que trae el código para cada catálogo."""
    if catalogo == MODELO:
        return [v for v in DROPDOWN_OPTIONS_UNIDAD['MODELO'] if v != '-']
    if catalogo == INDUSTRIA:
        return sorted(set(INDUSTRIA_MAP.values()))
    if catalogo == SERVICIO:
        return list(dict.fromkeys(_base_servicio(v) for v in DROPDOWN_OPTIONS_UNIDAD['TIPO DE SERVICIO'] if v != '-'))
    if catalogo == COMPLEMENTO:
        return [codigo for codigo, _nombre in COMPLEMENTOS_DE_FABRICA]
    return []


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
    _cache.clear()


def _filas_de_fabrica():
    filas = [[cat, v, "", "SI"] for cat in CATALOGOS_EDITABLES for v in valores_de_fabrica(cat)]
    return filas + [[COMPLEMENTO, codigo, nombre, "SI"] for codigo, nombre in COMPLEMENTOS_DE_FABRICA]


def asegurar_archivo():
    """Crea Catalogos_VC.csv con los valores del código si no existe. Nunca
    pisa un archivo existente. Devuelve la ruta."""
    path = get_catalogos_csv_path()
    if not os.path.exists(path):
        try:
            _escribir(path, _filas_de_fabrica())
        except Exception as e:
            logger.error(f"No se pudo crear el archivo de catálogos: {e}")
    return path


def leer(crear=False):
    """Todas las filas del archivo como DataFrame de texto. Con `crear=False`
    y sin archivo devuelve los valores de fábrica sin escribir nada."""
    path = get_catalogos_csv_path()
    if crear:
        asegurar_archivo()
    if not os.path.exists(path):
        return pd.DataFrame(_filas_de_fabrica(), columns=_COLUMNAS)
    try:
        mtime = os.path.getmtime(path)
        if _cache.get('path') == path and _cache.get('mtime') == mtime:
            return _cache['df'].copy()
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding='utf-8-sig')
    except Exception as e:
        logger.error(f"No se pudo leer el archivo de catálogos: {e}")
        return pd.DataFrame(_filas_de_fabrica(), columns=_COLUMNAS)
    for col in _COLUMNAS:
        if col not in df.columns:
            df[col] = ""
    df = df[_COLUMNAS]
    _cache.update(path=path, mtime=mtime, df=df)
    return df.copy()


def _es_activo(valor):
    return str(valor).strip().upper() != 'NO'


def filas_catalogo(catalogo):
    """Filas (dict valor/extra/activo) del catálogo, en el orden del archivo.
    Si el archivo existe pero no trae el catálogo, se usan los valores de fábrica."""
    if catalogo == COMPLEMENTO:
        return [{'valor': c, 'extra': n, 'activo': a} for c, n, a in _filas_complementos()]
    df = leer()
    sub = df[df['catalogo'] == catalogo]
    if sub.empty and catalogo in CATALOGOS_EDITABLES and not (df['catalogo'] == catalogo).any():
        return [{'valor': v, 'extra': '', 'activo': True} for v in valores_de_fabrica(catalogo)]
    return [{'valor': r['valor'], 'extra': r['extra'], 'activo': _es_activo(r['activo'])} for _, r in sub.iterrows()]


def valores(catalogo, solo_activos=True):
    return [f['valor'] for f in filas_catalogo(catalogo) if f['activo'] or not solo_activos]


def _clave(texto):
    return ejecutivos_service.normalizar_nombre(texto)


def opciones_formulario(opciones_base):
    """Copia del diccionario de combos del formulario con MODELO, INDUSTRIA
    (no está en el diccionario, se usa aparte) y TIPO DE SERVICIO tomados de
    los catálogos. Ante cualquier fallo devuelve las opciones sin cambios."""
    salida = {k: list(v) for k, v in opciones_base.items()}
    try:
        salida['MODELO'] = ['-'] + valores(MODELO)
        base = list(opciones_base.get('TIPO DE SERVICIO', []))
        planes_base = {_base_servicio(v) for v in base if v != '-'}
        activos = valores(SERVICIO)
        inactivos = {_clave(v) for v in valores(SERVICIO, solo_activos=False)} - {_clave(v) for v in activos}
        resultado = [v for v in base if v == '-' or _clave(_base_servicio(v)) not in inactivos]
        for plan in activos:
            if plan not in planes_base:
                resultado += [plan, f"{plan} + CIV"]
        salida['TIPO DE SERVICIO'] = resultado
    except Exception as e:
        logger.error(f"No se pudieron aplicar los catálogos al formulario: {e}")
        return {k: list(v) for k, v in opciones_base.items()}
    return salida


def industrias_formulario():
    try:
        valores_activos = valores(INDUSTRIA)
    except Exception:
        valores_activos = []
    return sorted(valores_activos or valores_de_fabrica(INDUSTRIA))


def modelos_activos():
    try:
        return valores(MODELO)
    except Exception:
        return valores_de_fabrica(MODELO)


# ------------------------------------------------- planes y complementos
def _filas_complementos():
    """[(código, nombre, activo)] en el orden del catálogo; sin filas propias, los de fábrica.
    En el archivo, `valor` es el código (ej. SZ) y `extra` el nombre que se muestra."""
    try:
        df = leer()
        sub = df[df['catalogo'] == COMPLEMENTO]
    except Exception:
        sub = None
    if sub is None or sub.empty:
        return [(codigo, nombre, True) for codigo, nombre in COMPLEMENTOS_DE_FABRICA]
    return [(str(r['valor']).strip().upper(), str(r['extra']).strip() or str(r['valor']).strip(), _es_activo(r['activo']))
            for _, r in sub.iterrows() if str(r['valor']).strip()]


def complementos(solo_activos=True):
    """[(código, nombre)] de los complementos del plan (CIV, SZ...), en el orden en que se arma el texto."""
    return [(c, n) for c, n, activo in _filas_complementos() if activo or not solo_activos]


def planes_base(orden_preferido=()):
    """Planes base activos del catálogo de tipos de servicio; los de `orden_preferido` van primero, en ese orden."""
    try:
        bases = [_base_servicio(v) for v in valores(SERVICIO)]
    except Exception:
        bases = valores_de_fabrica(SERVICIO)
    bases = list(dict.fromkeys(b for b in bases if b and b != '-'))
    claves = {_clave(b): b for b in bases}
    primeros = [claves[_clave(p)] for p in orden_preferido if _clave(p) in claves]
    return primeros + [b for b in bases if b not in primeros]


def partir_tipo_servicio(valor):
    """'Medio + CIV + SZ' -> ('Medio', ['CIV', 'SZ']). Si el texto trae un sufijo que no es un complemento
    conocido, el valor completo queda como plan base (valor legado)."""
    partes = [p.strip() for p in str(valor).split('+')]
    extras = {p.upper() for p in partes[1:] if p}
    orden = [c for c, _n in complementos(solo_activos=False)]
    if extras <= set(orden):
        return partes[0], [c for c in orden if c in extras]
    return str(valor).strip(), []


def armar_tipo_servicio(base, seleccion=()):
    """Plan base más sus complementos, en el orden del catálogo: 'Medio' + ['SZ', 'CIV'] -> 'Medio + CIV + SZ'."""
    elegidos = {str(c).strip().upper() for c in seleccion}
    return base + ''.join(f" + {c}" for c, _n in complementos(solo_activos=False) if c in elegidos)


# ---------------------------------------------------------------- edición
def _guardar_filas(filas):
    try:
        _escribir(get_catalogos_csv_path(), filas)
    except Exception as e:
        return False, f"No se pudo guardar el catálogo (¿el archivo está abierto?): {e}"
    return True, ""


def _filas_actuales():
    asegurar_archivo()
    filas = leer()[_COLUMNAS].values.tolist()
    if not any(f[0] == COMPLEMENTO for f in filas):
        # Archivo creado antes de existir este catálogo: se escriben los de fábrica para no perderlos al agregar uno
        filas += [[COMPLEMENTO, codigo, nombre, "SI"] for codigo, nombre in COMPLEMENTOS_DE_FABRICA]
    return filas


def agregar_valor(catalogo, valor):
    """Agrega un valor a un catálogo. Devuelve (ok, mensaje)."""
    valor = ' '.join(str(valor).split())
    if not valor or valor == '-':
        return False, "Escribe un valor."
    if any(_clave(f['valor']) == _clave(valor) for f in filas_catalogo(catalogo)):
        return False, "Ese valor ya existe en el catálogo."
    filas = _filas_actuales()
    filas.append([catalogo, valor, "", "SI"])
    return _guardar_filas(filas)


def agregar_complemento(codigo, nombre):
    """Agrega un complemento del plan (por ejemplo SZ / Safety Zone). El código es lo que se escribe
    en TIPO DE SERVICIO ('Medio + SZ'): solo letras y números, sin espacios. Devuelve (ok, mensaje)."""
    codigo = str(codigo).strip().upper()
    nombre = ' '.join(str(nombre).split()) or codigo
    if not re.fullmatch(r'[A-Z0-9]{1,8}', codigo):
        return False, "El código lleva solo letras y números, sin espacios (hasta 8 caracteres). Ej: SZ."
    if _clave(codigo) in {_clave(b) for b in planes_base()}:
        return False, "Ese código es el nombre de un plan."
    existentes = filas_catalogo(COMPLEMENTO)
    if any(_clave(f['valor']) == _clave(codigo) or _clave(f['extra']) == _clave(nombre) for f in existentes):
        return False, "Ya existe un complemento con ese código o ese nombre."
    filas = _filas_actuales()
    filas.append([COMPLEMENTO, codigo, nombre, "SI"])
    return _guardar_filas(filas)


def guardar_nombre_complemento(codigo, nombre):
    """Cambia el nombre con que se muestra un complemento (el código no cambia). Devuelve (ok, mensaje)."""
    nombre = ' '.join(str(nombre).split())
    if not nombre:
        return False, "Escribe un nombre."
    filas = _filas_actuales()
    if any(f[0] == COMPLEMENTO and f[1] != codigo and _clave(f[2]) == _clave(nombre) for f in filas):
        return False, "Ya existe un complemento con ese nombre."
    hubo = False
    for fila in filas:
        if fila[0] == COMPLEMENTO and fila[1] == codigo:
            fila[2] = nombre
            hubo = True
    return _guardar_filas(filas) if hubo else (False, "El complemento ya no existe.")


def cambiar_activo(catalogo, valor, activo):
    filas = _filas_actuales()
    hubo = False
    for fila in filas:
        if fila[0] == catalogo and fila[1] == valor:
            fila[3] = "SI" if activo else "NO"
            hubo = True
    return _guardar_filas(filas) if hubo else (False, "El valor ya no existe.")


def es_de_fabrica(catalogo, valor):
    return _clave(valor) in {_clave(v) for v in valores_de_fabrica(catalogo)}


def guardar_precio_servicio(valor, multiplicador):
    """Deja anotado en el catálogo el multiplicador de UF del tipo de servicio (la fuente del precio es la
    hoja Planes de las provisiones). Devuelve (ok, mensaje)."""
    filas = _filas_actuales()
    hubo = False
    for fila in filas:
        if fila[0] == SERVICIO and fila[1] == valor:
            fila[2] = f"{float(multiplicador):g}"
            hubo = True
    return _guardar_filas(filas) if hubo else (False, "El valor ya no existe.")


def eliminar_valor(catalogo, valor):
    filas = [f for f in _filas_actuales() if not (f[0] == catalogo and f[1] == valor)]
    return _guardar_filas(filas)


def unidades_por_valor(catalogo, df_unidades):
    """{valor del catálogo (clave normalizada): unidades que lo usan}."""
    columna = _COLUMNA_UNIDADES.get(catalogo)
    if df_unidades is None or df_unidades.empty or columna not in df_unidades.columns:
        return {}
    conteo = {}
    for texto, n in df_unidades[columna].fillna('').astype(str).str.strip().value_counts().items():
        if catalogo == COMPLEMENTO:
            for codigo in partir_tipo_servicio(texto)[1]:
                conteo[_clave(codigo)] = conteo.get(_clave(codigo), 0) + int(n)
            continue
        if catalogo == INDUSTRIA:
            from src.services.provisiones_services import mapear_industria
            texto = mapear_industria(texto)
        elif catalogo == SERVICIO:
            texto = _base_servicio(texto)
        clave = _clave(texto)
        conteo[clave] = conteo.get(clave, 0) + int(n)
    return conteo


# ---------------------------------------------------- industria: traducción
def traducciones_propias():
    """{TEXTO EN INGLÉS EN MAYÚSCULAS: nombre en español} agregadas por el equipo."""
    df = leer()
    sub = df[df['catalogo'] == TRADUCCION]
    return {str(r['valor']).strip().upper(): r['extra'] for _, r in sub.iterrows() if r['extra']}


def traducir_industria(texto_mayusculas):
    """Traducción propia de un texto de industria, o None si no hay."""
    if not os.path.exists(get_catalogos_csv_path()):
        return None
    return traducciones_propias().get(texto_mayusculas)


def traducciones():
    """Lista de dicts {origen_texto, destino, propia} con las traducciones del
    código (INDUSTRIA_MAP) y las del equipo; las del equipo mandan."""
    propias = traducciones_propias()
    filas = [{'texto': k.upper(), 'destino': v, 'propia': False}
             for k, v in INDUSTRIA_MAP.items() if k.upper() not in propias]
    filas += [{'texto': k, 'destino': v, 'propia': True} for k, v in propias.items()]
    return sorted(filas, key=lambda f: (f['destino'].lower(), f['texto']))


def pendientes():
    """Textos de industria sin traducción: lista de dicts {texto, unidades, fecha}."""
    df = leer()
    sub = df[df['catalogo'] == PENDIENTE]
    salida = []
    for _, r in sub.iterrows():
        n, _, fecha = str(r['extra']).partition('|')
        salida.append({'texto': r['valor'], 'unidades': int(n) if n.isdigit() else 0, 'fecha': fecha})
    return salida


def _industria_conocida(texto_mayusculas):
    if texto_mayusculas == 'NO DEFINIDA' or texto_mayusculas in INDUSTRIA_MAP:
        return True
    if texto_mayusculas in traducciones_propias():
        return True
    return any(_clave(v) == _clave(texto_mayusculas) for v in valores(INDUSTRIA, solo_activos=False))


def anotar_pendiente(texto_mayusculas):
    """Cuenta en memoria un texto de industria que la importación no reconoce;
    `volcar_pendientes` lo guarda al terminar el lote."""
    if not texto_mayusculas or _industria_conocida(texto_mayusculas):
        return
    _pendientes_memoria[texto_mayusculas] = _pendientes_memoria.get(texto_mayusculas, 0) + 1


def volcar_pendientes():
    """Guarda los textos anotados sumándolos a los pendientes existentes."""
    if not _pendientes_memoria:
        return
    nuevos = dict(_pendientes_memoria)
    _pendientes_memoria.clear()
    try:
        filas = _filas_actuales()
        hoy = datetime.now().strftime('%d-%m-%Y')
        existentes = {f[1]: f for f in filas if f[0] == PENDIENTE}
        for texto, n in nuevos.items():
            if texto in existentes:
                previo = str(existentes[texto][2]).partition('|')[0]
                existentes[texto][2] = f"{(int(previo) if previo.isdigit() else 0) + n}|{hoy}"
            else:
                filas.append([PENDIENTE, texto, f"{n}|{hoy}", "SI"])
        _guardar_filas(filas)
    except Exception as e:
        logger.error(f"No se pudieron guardar las industrias por traducir: {e}")


def quitar_traduccion(texto_origen):
    """Quita la traducción del equipo; el texto vuelve a la de fábrica (si la tiene)."""
    texto_origen = ' '.join(str(texto_origen).split()).upper()
    filas = [f for f in _filas_actuales() if not (f[0] == TRADUCCION and str(f[1]).strip().upper() == texto_origen)]
    return _guardar_filas(filas)


def guardar_traduccion(texto_origen, destino):
    """Guarda (o cambia) la traducción de un texto de industria, la agrega a
    los valores de Industria si es nueva y quita el pendiente."""
    texto_origen = ' '.join(str(texto_origen).split()).upper()
    destino = ' '.join(str(destino).split())
    if not texto_origen or not destino:
        return False, "Escribe cómo se llama en español."
    filas = [f for f in _filas_actuales()
             if not (f[0] in (TRADUCCION, PENDIENTE) and str(f[1]).strip().upper() == texto_origen)]
    existente = next((f for f in filas if f[0] == INDUSTRIA and _clave(f[1]) == _clave(destino)), None)
    if existente is None:
        filas.append([INDUSTRIA, destino, "", "SI"])
    else:
        destino = existente[1]
        existente[3] = "SI"
    filas.append([TRADUCCION, texto_origen, destino, "SI"])
    return _guardar_filas(filas)
