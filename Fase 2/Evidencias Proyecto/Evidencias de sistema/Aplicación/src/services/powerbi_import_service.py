"""Lógica pura (sin PyQt6) para importar el Excel de Notas de Venta exportado
desde Power BI hacia Gestión de Unidades. Ver docs/07 y la conversación de
diseño del 15/16-09-2026: el Excel llega ya sin la protección IRM (el
usuario lo re-guarda como "Internal" antes de seleccionarlo en la app), así
que aquí solo se lee con pandas/openpyxl, se mapea y se valida -- no se
resuelve cifrado.
"""
import re
from collections import Counter

import pandas as pd

from src.services.ejecutivos_service import buscar_ejecutivo
from src.services.provisiones_services import mapear_industria
from src.services.vin_service import obtener_modelo_desde_vin

# Mapeo cerrado con Javiera (16-09-2026): columnas del Excel de Power BI
# (hoja "Export") -> columnas de PruebasFM. El resto de columnas del Excel
# (Chasis, Chasis_II, Patente, HDV, Fecha_Facturacion, y todas las de
# contacto/conectividad) queda fuera de este alcance.
MAPEO_COLUMNAS = {
    'VIN': 'VIN',
    'Rut': 'RUT',
    'Cliente': 'RAZÓN SOCIAL',
    'Industria': 'INDUSTRIA',
    'Vendedor': 'EJECUTIVO',
    'CDB': 'CDB',
}

# Fila de nota que Power BI agrega al final de la hoja "Export" con los
# filtros aplicados (ver conversación de diseño, ejemplo real observado).
_PREFIJO_FILTROS = "filtros aplicados"

_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
          "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _limpiar_valor(v):
    if pd.isna(v):
        return ''
    texto = str(v).strip()
    if texto.lower() in ('nan', 'none', 'nat', '<na>'):
        return ''
    return texto


def _limpiar_numero_texto(v):
    """Para RUT/CDB: pandas a veces castea estos valores a float (ej. Excel
    sin ceros a la izquierda), lo que deja un '.0' colgando al convertir a
    texto. Se quita igual que ya hace provisiones_services."""
    texto = _limpiar_valor(v)
    return texto[:-2] if texto.endswith('.0') else texto


def leer_hoja_export(filepath):
    """Lee la hoja 'Export' del Excel de Power BI. Devuelve (filas, texto_filtros):
    `filas` es la lista de pd.Series de datos reales (sin la fila 'Total' ni
    la nota de filtros aplicados al final); `texto_filtros` es el contenido
    de esa nota (o '' si no se encontró), usado luego para sugerir el
    PERIODO INTERNO. Lanza excepción si la hoja 'Export' no existe o no se
    puede leer -- el llamador decide cómo mostrarlo al usuario."""
    xls = pd.ExcelFile(filepath, engine='openpyxl')
    if 'Export' not in xls.sheet_names:
        raise ValueError("El Excel no tiene una hoja 'Export' (¿es realmente el reporte de Notas de Venta de Power BI?).")

    df = pd.read_excel(xls, sheet_name='Export', dtype={'Rut': str, 'CDB': str})
    if df.empty or 'Chasis' not in df.columns:
        raise ValueError("La hoja 'Export' no tiene el formato esperado (falta la columna 'Chasis').")

    texto_filtros = ''
    filas_validas = []
    for _, fila in df.iterrows():
        chasis = _limpiar_valor(fila.get('Chasis'))
        # Power BI vuelca la nota "Filtros aplicados: ..." en la misma
        # columna "Chasis" de la última fila de la hoja (no en una fila con
        # Chasis vacío) -- se detecta por el prefijo del texto.
        if chasis.lower().startswith(_PREFIJO_FILTROS):
            texto_filtros = chasis
            continue
        if not chasis or chasis.upper() == 'TOTAL':
            continue
        filas_validas.append(fila)

    return filas_validas, texto_filtros


_MODELOS_OFICIALES = ('FMX', 'FME', 'FML', 'FHE', 'FHL', 'FH', 'FM', 'FL', 'FE', 'VM')


def modelo_desde_tipo(tipo):
    """MODELO a partir del 'Tipo' de Power BI (ej. 'FMX13B 6x4 R' -> FMX,
    'FM GNL 6x2 T' -> FM, 'FH13B 6x2 T' -> FH): las letras iniciales, que
    deben ser un modelo oficial. Vacío si el Tipo viene vacío."""
    tipo = str(tipo or '').strip()
    if not tipo:
        return ''
    coincidencia = re.match(r'[A-Za-z]+', tipo)
    letras = coincidencia.group(0).upper() if coincidencia else ''
    for modelo in _MODELOS_OFICIALES:
        if letras == modelo:
            return modelo
    for modelo in _MODELOS_OFICIALES:
        if letras.startswith(modelo):
            return modelo
    return tipo[:2].strip()


def mapear_fila_powerbi(fila):
    """Convierte una fila cruda de la hoja 'Export' al diccionario de
    campos de PruebasFM que le corresponden, más `_CHASIS_BI`: el Chasis que
    entrega Power BI, guardado SOLO como identificador interno del registro
    durante la importación (nunca se usa para llenar el campo CHASIS del
    formulario, que siempre se deriva del VIN que ingresa la persona)."""
    datos = {}
    for col_bi, col_rm in MAPEO_COLUMNAS.items():
        valor = _limpiar_valor(fila.get(col_bi))
        if col_rm in ('RUT', 'CDB'):
            valor = _limpiar_numero_texto(fila.get(col_bi))
        if col_rm == 'INDUSTRIA':
            valor = mapear_industria(valor) if valor else ''
        if col_rm == 'VIN':
            valor = valor.upper()
        datos[col_rm] = valor

    tipo = _limpiar_valor(fila.get('Tipo'))
    datos['MODELO'] = modelo_desde_tipo(tipo)

    # Traspaso literal de la fecha de entrega (regla confirmada con Javiera,
    # 16-09-2026): si hay fecha, se conserva en formato DD-MM-YYYY; si
    # 'Fecha Entrega' viene vacía (NaN/NaT/None/texto vacío), ESTADO DE
    # ENTREGA queda en "-" (nunca NaN/NaT/None ni texto raro).
    fecha_entrega = fila.get('Fecha Entrega')
    if pd.isna(fecha_entrega) or _limpiar_valor(fecha_entrega) == '':
        datos['ESTADO DE ENTREGA'] = '-'
    elif hasattr(fecha_entrega, 'strftime'):
        datos['ESTADO DE ENTREGA'] = fecha_entrega.strftime('%d-%m-%Y')
    else:
        # Texto que no es un objeto fecha de pandas/Python: se intenta
        # parsear igual (Excel a veces trae la fecha como texto suelto);
        # si no calza con ningún formato reconocible, se conserva el texto
        # tal cual en vez de perderlo silenciosamente.
        texto = _limpiar_valor(fecha_entrega)
        try:
            datos['ESTADO DE ENTREGA'] = pd.to_datetime(texto, dayfirst=True).strftime('%d-%m-%Y')
        except (ValueError, TypeError):
            datos['ESTADO DE ENTREGA'] = texto

    datos['_CHASIS_BI'] = _limpiar_valor(fila.get('Chasis'))
    return datos


def detectar_periodo_desde_filtros(texto_filtros):
    """Best-effort: intenta deducir (mes, año) a partir de la nota "Filtros
    aplicados" que Power BI agrega a la hoja 'Export' (ver ejemplo real
    analizado: 'Incluido (1) 2026 (Año)' + una lista de meses EXCLUIDOS).
    Devuelve (None, None) si el texto no calza con ese patrón exacto -- no
    es un contrato estable de Power BI, es solo una sugerencia para
    prellenar el selector de PERIODO INTERNO; el usuario siempre puede
    corregirlo."""
    if not texto_filtros:
        return None, None

    texto_lower = texto_filtros.lower()

    m_anio = re.search(r'incluido\s*\(\d+\)\s*(\d{4})\s*\(a[ñn]o\)', texto_lower)
    if not m_anio:
        return None, None
    anio = int(m_anio.group(1))

    meses_excluidos = {mes for mes in _MESES if re.search(rf'\+\s*{mes}\s*\(mes\)', texto_lower)}
    meses_incluidos = [mes for mes in _MESES if mes not in meses_excluidos]

    if len(meses_incluidos) == 1:
        return meses_incluidos[0].capitalize(), anio
    return None, anio


def detectar_vins_duplicados(lote):
    """VIN repetidos dentro del propio lote que se está por importar (antes
    de escribir nada)."""
    vistos, duplicados = set(), set()
    for registro in lote:
        vin = str(registro.get('VIN', '')).strip().upper()
        if not vin:
            continue
        if vin in vistos:
            duplicados.add(vin)
        vistos.add(vin)
    return sorted(duplicados)


def detectar_vins_existentes(lote, df_comercial):
    """VIN del lote que ya existen en PruebasFM: intentar darlos de alta con
    add_new_rows_batch duplicaría la fila en el Excel, así que se bloquean
    antes de escribir (la unidad ya existente se edita, no se vuelve a
    crear)."""
    if df_comercial is None or not isinstance(df_comercial, pd.DataFrame) or df_comercial.empty or 'VIN' not in df_comercial.columns:
        return []
    vins_existentes = set(df_comercial['VIN'].astype(str).str.strip().str.upper())
    return sorted({
        str(registro.get('VIN', '')).strip().upper()
        for registro in lote
        if str(registro.get('VIN', '')).strip().upper() in vins_existentes
    })


def _flotas_unicas_por_cdb(df_comercial):
    """CDB -> FLOTA VC, solo cuando el CDB tiene una única flota conocida en
    PruebasFM (con varias no hay un valor que elegir sin intervención)."""
    if (df_comercial is None or not isinstance(df_comercial, pd.DataFrame) or df_comercial.empty
            or 'CDB' not in df_comercial.columns or 'FLOTA VC' not in df_comercial.columns):
        return {}
    aux = df_comercial[['CDB', 'FLOTA VC']].fillna('').astype(str).apply(lambda s: s.str.strip())
    aux = aux[(aux['CDB'] != '') & (~aux['FLOTA VC'].isin(['', '-', 'nan', 'None']))]
    por_cdb = aux.groupby(aux['CDB'].str.upper())['FLOTA VC'].unique()
    return {cdb: flotas[0] for cdb, flotas in por_cdb.items() if len(flotas) == 1}


def _catalogo_ejecutivos(df_comercial):
    """Nombres de EJECUTIVO ya usados en PruebasFM: {minúsculas: grafía más frecuente}."""
    if (df_comercial is None or not isinstance(df_comercial, pd.DataFrame) or df_comercial.empty
            or 'EJECUTIVO' not in df_comercial.columns):
        return {}
    conteo = df_comercial['EJECUTIVO'].dropna().astype(str).str.strip().value_counts()
    catalogo = {}
    for nombre in conteo.index:
        if nombre and nombre.lower() not in ('-', 'nan', 'none'):
            catalogo.setdefault(nombre.lower(), nombre)
    return catalogo


def _resolver_ejecutivo_detallado(vendedor, catalogo, directorio=None):
    """(nombre, resuelto). Power BI entrega el vendedor completo y con
    puntuación ("Miguel Angel Gonzalez .") mientras PruebasFM guarda nombre +
    primer apellido ("Miguel Gonzalez"). Primero se busca en el directorio
    Ejecutivos_VC.csv (nombre o alias, devuelve el nombre canónico) y luego
    entre los ejecutivos ya usados en PruebasFM; si no hay coincidencia se
    conserva el nombre limpio con resuelto=False."""
    limpio = ' '.join(re.sub(r'[.,;]', ' ', str(vendedor)).split())
    if not limpio:
        return '', True
    if directorio is not None:
        fila = buscar_ejecutivo(limpio, directorio, incluir_inactivos=True)
        if fila:
            return str(fila['nombre']).strip(), True
    if limpio.lower() in catalogo:
        return catalogo[limpio.lower()], True
    tokens = set(limpio.lower().split())
    # El catálogo viene ordenado por frecuencia: ante varias coincidencias gana la más usada
    for clave, nombre in catalogo.items():
        partes = clave.split()
        if len(partes) >= 2 and all(p in tokens for p in partes):
            return nombre, True
    return limpio, False


def resolver_ejecutivo(vendedor, catalogo, directorio=None):
    return _resolver_ejecutivo_detallado(vendedor, catalogo, directorio)[0]


def _normalizar_rut(rut):
    return re.sub(r'[^0-9A-Z]', '', str(rut).upper())


def _datos_por_rut(df_comercial):
    """RUT normalizado -> razón social más frecuente, CDB y ejecutivos que ya
    tiene en PruebasFM."""
    if (df_comercial is None or not isinstance(df_comercial, pd.DataFrame) or df_comercial.empty
            or 'RUT' not in df_comercial.columns):
        return {}
    cols = ['RUT', 'RAZÓN SOCIAL', 'CDB', 'EJECUTIVO']
    aux = pd.DataFrame({c: (df_comercial[c] if c in df_comercial.columns else '') for c in cols})
    aux = aux.fillna('').astype(str).apply(lambda s: s.str.strip())
    vacios = ('', '-', 'nan', 'none')
    datos = {}
    for rut, razon, cdb, ejecutivo in zip(aux['RUT'], aux['RAZÓN SOCIAL'], aux['CDB'], aux['EJECUTIVO']):
        clave = _normalizar_rut(rut)
        if not clave:
            continue
        d = datos.setdefault(clave, {'razones': Counter(), 'cdbs': set(), 'ejecutivos': set()})
        if razon.lower() not in vacios:
            d['razones'][razon] += 1
        if cdb.lower() not in vacios:
            d['cdbs'].add(cdb[:-2] if cdb.endswith('.0') else cdb)
        if ejecutivo.lower() not in vacios:
            d['ejecutivos'].add(ejecutivo)
    return datos


def _vins_reactivables(df_comercial):
    """VIN cuyo contrato actual permite crear otro (baja y unidad que no sigue
    Activando ni Conectada, ver comercial_services.puede_crear_contrato)."""
    from src.services.comercial_services import contratos_actuales, es_contrato_cerrado, puede_crear_contrato
    if (not isinstance(df_comercial, pd.DataFrame) or df_comercial.empty
            or 'VIN' not in df_comercial.columns or 'ESTADO COMERCIAL' not in df_comercial.columns):
        return set()
    actuales = contratos_actuales(df_comercial)
    if 'ESTADO DE ACTIVACIÓN ACTUAL' in actuales.columns:
        activacion = actuales['ESTADO DE ACTIVACIÓN ACTUAL']
    else:
        activacion = pd.Series('', index=actuales.index)
    return {
        str(vin).strip().upper()
        for vin, estado, act in zip(actuales['VIN'], actuales['ESTADO COMERCIAL'], activacion)
        if es_contrato_cerrado(estado) and puede_crear_contrato(estado, act)
    }


def construir_altas_nuevas(filas, df_comercial, plantilla, periodo_interno, directorio_ejecutivos=None):
    """Convierte las filas del Excel de Power BI en registros listos para
    escribir en PruebasFM, descartando los VIN que ya existen. `plantilla` es
    el registro base con los valores por defecto de una unidad nueva (mismos
    que el formulario "Unidad nueva"). Solo el VIN es obligatorio. Reglas:
    RAZÓN SOCIAL = la ya registrada para ese RUT en PruebasFM (evita
    renombres), si no la de Power BI; CDB = el de Power BI, si falta el único
    que tenga ese RUT en PruebasFM, si no "-"; EJECUTIVO = nombre canónico del
    directorio de ejecutivos, si falta el único del RUT, si no "-". Devuelve
    un dict con `registros` (los nuevos), las listas de VIN omitidos
    (`existentes`, `repetidos` dentro del propio Excel, `incompletos` sin VIN)
    y `ejecutivos_sin_coincidencia` (nombres que no calzan con ningún
    ejecutivo conocido).

    Un VIN que ya existe no se importa. Si su contrato actual está en baja y
    la unidad no sigue Activando ni Conectada, se informa aparte en
    `reactivables` (en vez de `existentes`) para que el usuario decida si
    crea un contrato nuevo."""
    reactivables_posibles = _vins_reactivables(df_comercial)
    reactivables = []
    vins_existentes = set()
    if (isinstance(df_comercial, pd.DataFrame) and not df_comercial.empty
            and 'VIN' in df_comercial.columns):
        vins_existentes = set(df_comercial['VIN'].dropna().astype(str).str.strip().str.upper())
    flotas = _flotas_unicas_por_cdb(df_comercial)
    ejecutivos = _catalogo_ejecutivos(df_comercial)
    por_rut = _datos_por_rut(df_comercial)

    registros, existentes, repetidos, incompletos = [], [], [], []
    sin_coincidencia = set()
    vistos = set()
    for fila in filas:
        datos = mapear_fila_powerbi(fila)
        vin = datos.get('VIN', '')
        if not vin:
            incompletos.append(datos.get('_CHASIS_BI', '') or '(sin VIN)')
            continue

        conocido = por_rut.get(_normalizar_rut(datos.get('RUT', ''))) if datos.get('RUT') else None
        if conocido and conocido['razones']:
            datos['RAZÓN SOCIAL'] = conocido['razones'].most_common(1)[0][0]
        if not datos.get('CDB') and conocido and len(conocido['cdbs']) == 1:
            datos['CDB'] = next(iter(conocido['cdbs']))

        ejecutivo, resuelto = _resolver_ejecutivo_detallado(datos.get('EJECUTIVO', ''), ejecutivos, directorio_ejecutivos)
        if not ejecutivo and conocido and len(conocido['ejecutivos']) == 1:
            ejecutivo = next(iter(conocido['ejecutivos']))
        elif ejecutivo and not resuelto:
            sin_coincidencia.add(ejecutivo)
        datos['EJECUTIVO'] = ejecutivo

        for campo in ('RUT', 'RAZÓN SOCIAL', 'CDB', 'EJECUTIVO'):
            if not datos.get(campo):
                datos[campo] = '-'
        if vin in vins_existentes:
            (reactivables if vin in reactivables_posibles else existentes).append(vin)
            continue
        if vin in vistos:
            repetidos.append(vin)
            continue
        vistos.add(vin)

        registro = dict(plantilla)
        registro.update({k: v for k, v in datos.items() if v and not k.startswith('_')})
        registro['CHASIS'] = vin[-7:]
        # El Tipo de Power BI manda (distingue FMX de FM); el VIN solo se usa si no vino Tipo
        if not datos.get('MODELO'):
            modelo = obtener_modelo_desde_vin(vin)
            if modelo:
                registro['MODELO'] = modelo
        flota = flotas.get(datos.get('CDB', '').upper())
        if flota:
            registro['FLOTA VC'] = flota
        registro['PERIODO INTERNO'] = periodo_interno
        registros.append(registro)

    return {'registros': registros, 'existentes': existentes, 'reactivables': reactivables,
            'repetidos': repetidos, 'incompletos': incompletos,
            'ejecutivos_sin_coincidencia': sorted(sin_coincidencia)}


def validar_lote(lote, df_comercial):
    """Errores que bloquean la escritura final del lote completo (ninguno
    se guarda hasta que el lote entero sea válido). No revalida los campos
    obligatorios por unidad: eso ya lo exige ComercialAgregarDialog antes de
    dejar avanzar cada registro durante la importación."""
    errores = []

    duplicados = detectar_vins_duplicados(lote)
    if duplicados:
        errores.append(f"VIN repetidos dentro del propio Excel importado: {', '.join(duplicados)}.")

    existentes = detectar_vins_existentes(lote, df_comercial)
    if existentes:
        errores.append(
            "VIN que ya existen en PruebasFM (edita esas unidades desde Comercial en vez de "
            f"volver a crearlas): {', '.join(existentes)}."
        )

    return errores
