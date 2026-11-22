"""Cartera de los ejecutivos: qué contratos tiene cada uno, por cliente (razón
social), y los cambios de ejecutivo en bloque (reasignar cartera, asignar un
cliente, eliminar un ejecutivo). Solo calcula: arma los cambios en el formato
de ExcelWriter.update_cells y quien llama los guarda."""
import pandas as pd

from src.services import ejecutivos_service
from src.services.comercial_services import contratos_actuales

COL_EJECUTIVO = 'EJECUTIVO'
COL_CLIENTE = 'RAZÓN SOCIAL'
NOMBRE_DESCONOCIDO = ejecutivos_service.NOMBRE_DESCONOCIDO
_SIN_CLIENTE = "(Sin razón social)"


def _texto_cliente(serie):
    limpio = serie.fillna('').astype(str).str.strip()
    return limpio.where(~limpio.str.lower().isin(['', '-', 'nan', 'none']), _SIN_CLIENTE)


def _preparar(df):
    """Copia con índice limpio y las columnas que se usan siempre presentes."""
    base = df.reset_index(drop=True).copy()
    for col in (COL_EJECUTIVO, COL_CLIENTE, 'VIN'):
        if col not in base.columns:
            base[col] = ''
    return base


def ids_de_filas(df, directorio):
    """Serie con el id del ejecutivo de cada fila ('' si el texto no corresponde
    a nadie del directorio, por ejemplo Desconocido o vacío)."""
    nombres = df[COL_EJECUTIVO].fillna('').astype(str).str.strip()
    ids = {}
    for nombre in nombres.unique():
        fila = ejecutivos_service.buscar_ejecutivo(nombre, directorio, incluir_inactivos=True)
        ids[nombre] = fila['id_ejecutivo'] if fila else ''
    return nombres.map(ids)


def conteo_por_ejecutivo(df, directorio):
    """{id_ejecutivo: VIN} y la cantidad de VIN sin ejecutivo del directorio
    (Desconocido, vacío o un nombre que no existe). Cuenta solo el contrato
    actual de cada VIN: los contratos anteriores no suman."""
    if df is None or df.empty or COL_EJECUTIVO not in df.columns:
        return {}, 0
    base = _preparar(df)
    ids = ids_de_filas(base, directorio)[_es_actual(base)]
    conteo = ids[ids != ''].value_counts().to_dict()
    return {k: int(v) for k, v in conteo.items()}, int((ids == '').sum())


def _es_actual(df):
    """Máscara de las filas que son el contrato actual de su VIN."""
    return df.index.isin(contratos_actuales(df).index)


def cartera(df, id_ejecutivo, directorio):
    """Cartera de un ejecutivo, solo con el contrato actual de cada VIN. Devuelve
    un dict con `actuales` y `clientes`: una entrada por cliente con sus
    contratos y los camiones de otros ejecutivos en ese mismo cliente (`otros` y
    `otro_nombre`, el que más tiene). Ordenado de mayor a menor."""
    vacio = {'actuales': 0, 'clientes': []}
    if df is None or df.empty or COL_EJECUTIVO not in df.columns:
        return vacio
    base = _preparar(df)
    ids = ids_de_filas(base, directorio)
    base['_cliente'] = _texto_cliente(base[COL_CLIENTE])
    base['_actual'] = _es_actual(base)
    propias = base[(ids == id_ejecutivo) & base['_actual']]
    if propias.empty:
        return vacio
    ajenas = base[(ids != id_ejecutivo) & base['_actual']]
    ajenas_por_cliente = {}
    for cliente, grupo in ajenas[ajenas['_cliente'].isin(set(propias['_cliente']))].groupby('_cliente'):
        nombres = grupo[COL_EJECUTIVO].fillna('').astype(str).str.strip().replace('', NOMBRE_DESCONOCIDO)
        top = nombres.value_counts()
        ajenas_por_cliente[cliente] = (len(grupo), str(top.index[0]))
    clientes = []
    for cliente, grupo in propias.groupby('_cliente'):
        otros, otro_nombre = ajenas_por_cliente.get(cliente, (0, ''))
        clientes.append({'cliente': cliente, 'actuales': int(len(grupo)), 'otros': otros, 'otro_nombre': otro_nombre})
    clientes.sort(key=lambda c: (-c['actuales'], c['cliente'].lower()))
    return {'actuales': int(len(propias)), 'clientes': clientes}


def clientes_para_asignar(df, directorio):
    """Todos los clientes con sus contratos actuales, quién los tiene hoy y
    cuántos están sin ejecutivo activo (inactivo, Desconocido o vacío). Los que
    tienen camiones sin ejecutivo activo van primero."""
    if df is None or df.empty or COL_CLIENTE not in df.columns:
        return []
    base = _preparar(df)
    ids = ids_de_filas(base, directorio)
    inactivos = {fila['id_ejecutivo'] for _i, fila in directorio.iterrows()
                 if str(fila['activo']).strip().upper() == 'NO'}
    base['_cliente'] = _texto_cliente(base[COL_CLIENTE])
    base['_actual'] = _es_actual(base)
    base['_sin_activo'] = (ids == '') | ids.isin(inactivos)
    nombres_ejecutivo = {fila['id_ejecutivo']: fila['nombre'] for _i, fila in directorio.iterrows()}
    base['_dueno'] = ids.map(lambda i: nombres_ejecutivo.get(i, NOMBRE_DESCONOCIDO))
    actuales = base[base['_actual']]
    por_dueno = (actuales.groupby(['_cliente', '_dueno']).size().reset_index(name='n')
                 .sort_values('n', ascending=False, kind='stable'))
    duenos = {}
    for cliente, dueno, n in zip(por_dueno['_cliente'], por_dueno['_dueno'], por_dueno['n']):
        duenos.setdefault(cliente, []).append((str(dueno), int(n)))
    sin_activo = actuales.groupby('_cliente')['_sin_activo'].sum()
    filas = [{'cliente': cliente, 'contratos': sum(n for _d, n in lista),
              'sin_activo': int(sin_activo.get(cliente, 0)), 'duenos': lista}
             for cliente, lista in duenos.items()]
    filas.sort(key=lambda c: (-c['sin_activo'], c['cliente'].lower()))
    return filas


def _cambios(df, filas, nuevo):
    """Cambios en el formato de update_cells: uno por contrato (clave VIN|ID)."""
    cambios = {}
    tiene_id = 'ID' in df.columns
    for _i, fila in filas.iterrows():
        vin = str(fila['VIN']).strip()
        id_contrato = str(fila['ID']).strip() if tiene_id else ''
        if id_contrato.endswith('.0'):
            id_contrato = id_contrato[:-2]
        datos = {'VIN': vin, 'cambios': {COL_EJECUTIVO: nuevo}}
        if id_contrato and id_contrato.lower() not in ('nan', 'none', '-'):
            datos['ID'] = id_contrato
        cambios[f"{vin}|{id_contrato}"] = datos
    return cambios


def plan_reasignar(df, id_origen, clientes, destino, directorio):
    """Cambios para pasar a `destino` (nombre) el contrato actual de cada VIN de
    `id_origen` en los `clientes` elegidos. Solo cambia el ejecutivo: el estado
    del contrato (por ejemplo Baja Solicitada) no se toca. Los camiones de otros
    ejecutivos y los contratos anteriores no se tocan."""
    base = _preparar(df)
    ids = ids_de_filas(base, directorio)
    cliente = _texto_cliente(base[COL_CLIENTE])
    mascara = (ids == id_origen) & cliente.isin(set(clientes)) & _es_actual(base)
    return _cambios(base, base[mascara], destino)


def contratos_a_asignar(df, cliente, solo_sin_activo, directorio):
    """Contratos actuales del cliente que pasarían a un ejecutivo: los que no
    tienen ejecutivo activo, o todos si `solo_sin_activo` es False."""
    base = _preparar(df)
    ids = ids_de_filas(base, directorio)
    mascara = (_texto_cliente(base[COL_CLIENTE]) == cliente) & _es_actual(base)
    if solo_sin_activo:
        inactivos = {fila['id_ejecutivo'] for _i, fila in directorio.iterrows()
                     if str(fila['activo']).strip().upper() == 'NO'}
        mascara &= (ids == '') | ids.isin(inactivos)
    return base[mascara]


def plan_asignar_cliente(df, cliente, destino, solo_sin_activo, directorio):
    filas = contratos_a_asignar(df, cliente, solo_sin_activo, directorio)
    return _cambios(df, filas, destino)


def plan_eliminar(df, id_ejecutivo, directorio):
    """Cambios que dejan como Desconocido todos los contratos del ejecutivo, también los
    anteriores: si conservaran su nombre, el alta automática lo volvería a crear."""
    base = _preparar(df)
    ids = ids_de_filas(base, directorio)
    return _cambios(base, base[ids == id_ejecutivo], NOMBRE_DESCONOCIDO)
