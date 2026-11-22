"""Cálculos del Dashboard (Gestión del negocio de Volvo Connect): foto actual de
la flota, movimiento mensual de altas y bajas, conexión por servicio y por
ejecutivo. Sin dependencias de interfaz."""
import os
import unicodedata
from datetime import date

import numpy as np
import pandas as pd

from src.core.constants import (COL_ID, COL_VIN, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_TIPO_SERVICIO,
                                COL_INICIO_CONTRATO, COL_FECHA_BAJA, COL_TERMINO_CONTRATO, COL_EJECUTIVO, COL_FORMA_CONTRATO, COL_FLOTA_VC,
                                COL_INDUSTRIA, COL_MODELO, COL_TIPO_FACTURACION, COL_RUT, COL_RAZON_SOCIAL, COL_PERIODO_INTERNO)
from src.core.dataframe_formatter import DataFrameFormatter
from src.services import ejecutivos_service
from src.services.comercial_services import contratos_actuales, clave_cliente_serie

MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
         "Octubre", "Noviembre", "Diciembre")
MESES_CORTOS = tuple(m[:3] for m in MESES)

# Orden en que se muestran los estados de la base no conectada
ESTADOS_NO_CONECTADA = ("DESCONECTADO", "ACTIVANDO", "NO ENTREGADO", "SIN FLOTA")

# Camiones que pasaron por Volvo Connect según su ESTADO COMERCIAL: "Revisar"
# solo cuenta si la unidad tiene un estado de activación real.
COMERCIAL_PASO_POR_VC = ("ACTIVACION PENDIENTE", "VIGENTE", "VENCIDO", "BAJA", "BAJA SOLICITADA")
ACTIVACION_REAL = ("ACTIVANDO", "CONECTADO", "DESCONECTADO")
MAX_EJECUTIVOS = 15

SIN_EJECUTIVO = "Sin ejecutivo"
# Contratos de prueba (duran cerca de un mes): se pueden dejar fuera de las cifras
FORMAS_PRUEBA = ("TEST", "DEMO")
# Provisiones: su TÉRMINO CONTRATO aún no es confiable, así que no se toma como baja
FORMAS_PROVISION = ("PROVISION", "PROVISION +")
COLUMNAS_FILTRO = ("EJECUTIVO", "FORMA", "SERVICIO", "FLOTA")
# Tipos de baja: con fecha de baja registrada, con baja solicitada, o deducida por término vencido (sin fecha de baja)
TIPO_BAJA_DADA, TIPO_BAJA_SOLICITADA, TIPO_BAJA_SIN_FECHA = 'dada', 'solicitada', 'sin_fecha'


def _fechas(serie):
    """Serie de Timestamps (NaT donde no hay fecha válida); parsea una vez por valor distinto."""
    mapa = {v: DataFrameFormatter.parsear_fecha_segura(v) for v in serie.dropna().unique()}
    return pd.to_datetime(serie.map(mapa), errors='coerce')


def _texto_mayus(serie):
    return serie.astype(str).str.strip().str.upper()


def _sin_tildes(serie):
    return serie.map(lambda v: unicodedata.normalize('NFKD', v).encode('ascii', 'ignore').decode())


def _eventos_alta_baja(df_master, vins):
    """Altas y bajas (DataFrames VIN, FECHA) de las unidades `vins`, mirando todos
    los contratos de cada VIN. Es alta el primer INICIO CONTRATO del VIN y el de
    cada contrato posterior cuyo contrato anterior tenía FECHA DE BAJA (la
    unidad volvió); un contrato nuevo sin baja previa es una renovación y no
    cuenta (el contrato reemplazado queda en estado Renovado, sin baja ni
    desconexión, y se ignoran su FECHA DE BAJA y su TÉRMINO CONTRATO). La salida
    de un contrato es su FECHA DE BAJA o, si no la tiene, su TÉRMINO CONTRATO
    cuando es una fecha real que ya pasó y la unidad ya está Desconectada o el
    contrato está en estado Vencido (MENSUAL no cuenta); una unidad con el
    término vencido que sigue Conectada o Activando y no está en estado
    Vencido no es baja todavía (ver `vencidas_sin_desconectar`).
    En los contratos de Provisión y Provisión + el término no cuenta, porque sus
    fechas todavía no se corrigen. Es baja cada salida de una unidad que tiene alta."""
    vacia = pd.DataFrame({'VIN': pd.Series([], dtype=str), 'FECHA': pd.Series([], dtype='datetime64[ns]')})
    if COL_INICIO_CONTRATO not in df_master.columns:
        return vacia, vacia.copy()
    cols = [c for c in (COL_VIN, COL_ID, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_FORMA_CONTRATO,
                        COL_INICIO_CONTRATO, COL_FECHA_BAJA, COL_TERMINO_CONTRATO) if c in df_master.columns]
    todas = df_master[cols].copy()
    todas[COL_VIN] = todas[COL_VIN].astype(str).str.strip().str.upper()
    todas = todas[todas[COL_VIN].isin(vins)]
    if todas.empty:
        return vacia, vacia.copy()
    orden = pd.to_numeric(todas[COL_ID], errors='coerce').fillna(-1).to_numpy() if COL_ID in todas.columns \
        else np.full(len(todas), -1.0)
    todas['_orden'] = orden
    todas['_pos'] = np.arange(len(todas))
    todas = todas.sort_values([COL_VIN, '_orden', '_pos'])
    inicio = _fechas(todas[COL_INICIO_CONTRATO])
    baja = _fechas(todas[COL_FECHA_BAJA]) if COL_FECHA_BAJA in todas.columns \
        else pd.Series(pd.NaT, index=todas.index, dtype='datetime64[ns]')
    if COL_TERMINO_CONTRATO in todas.columns:
        termino = _fechas(todas[COL_TERMINO_CONTRATO])
        if COL_FORMA_CONTRATO in todas.columns:
            termino = termino.where(~_sin_tildes(_texto_mayus(todas[COL_FORMA_CONTRATO])).isin(FORMAS_PROVISION))
        if COL_ESTADO_ACTIVACION in todas.columns:
            cuenta = _texto_mayus(todas[COL_ESTADO_ACTIVACION]) == 'DESCONECTADO'
            if COL_ESTADO_COMERCIAL in todas.columns:
                cuenta |= _texto_mayus(todas[COL_ESTADO_COMERCIAL]) == 'VENCIDO'
            termino = termino.where(cuenta)
        con_fecha_baja = baja.notna()
        baja = baja.fillna(termino)
    else:
        con_fecha_baja = baja.notna()
    baja = baja.where(baja <= pd.Timestamp(date.today()))
    if COL_ESTADO_COMERCIAL in todas.columns:
        baja = baja.where(_texto_mayus(todas[COL_ESTADO_COMERCIAL]) != 'RENOVADO')
    vin = todas[COL_VIN]
    primera_valida = inicio.notna() & (inicio.notna().groupby(vin).cumsum() == 1)
    vuelve = baja.groupby(vin).shift(1).notna()
    es_alta = inicio.notna() & (primera_valida | vuelve)
    vins_con_alta = set(vin[es_alta])
    con_baja = baja.notna() & vin.isin(vins_con_alta)
    altas = pd.DataFrame({'VIN': vin[es_alta].to_numpy(), 'FECHA': inicio[es_alta].to_numpy()})
    solicitada = (_texto_mayus(todas[COL_ESTADO_COMERCIAL]) == 'BAJA SOLICITADA') if COL_ESTADO_COMERCIAL in todas.columns \
        else pd.Series(False, index=todas.index)
    tipo = np.where(~con_fecha_baja, TIPO_BAJA_SIN_FECHA, np.where(solicitada, TIPO_BAJA_SOLICITADA, TIPO_BAJA_DADA))
    bajas = pd.DataFrame({'VIN': vin[con_baja].to_numpy(), 'FECHA': baja[con_baja].to_numpy(),
                          'TIPO': pd.Series(tipo, index=todas.index)[con_baja].to_numpy()})
    altas['FECHA'] = altas['FECHA'].astype('datetime64[ns]')
    bajas['FECHA'] = bajas['FECHA'].astype('datetime64[ns]')
    return altas, bajas


def _mascara_vencidas_sin_desconectar(actuales):
    """Contratos actuales con el término ya vencido (sin fecha de baja) cuya unidad sigue Conectada o
    Activando y que no están en estado Vencido: siguen siendo camiones activos, no se cuentan como baja
    hasta que se desconecten o pasen a Vencido."""
    sin = pd.Series(False, index=actuales.index)
    if COL_TERMINO_CONTRATO not in actuales.columns or COL_ESTADO_ACTIVACION not in actuales.columns:
        return sin
    termino = _fechas(actuales[COL_TERMINO_CONTRATO])
    if COL_FORMA_CONTRATO in actuales.columns:
        termino = termino.where(~_sin_tildes(_texto_mayus(actuales[COL_FORMA_CONTRATO])).isin(FORMAS_PROVISION))
    vencido = termino.notna() & (termino <= pd.Timestamp(date.today()))
    if COL_FECHA_BAJA in actuales.columns:
        vencido &= _fechas(actuales[COL_FECHA_BAJA]).isna()
    if COL_ESTADO_COMERCIAL in actuales.columns:
        # Renovado se ignora y Vencido ya cuenta como baja aunque la unidad siga conectada
        vencido &= ~_texto_mayus(actuales[COL_ESTADO_COMERCIAL]).isin(('RENOVADO', 'VENCIDO'))
    return vencido & _texto_mayus(actuales[COL_ESTADO_ACTIVACION]).isin(('CONECTADO', 'ACTIVANDO'))


def vins_vencidas_sin_desconectar(panorama):
    u = panorama['unidades']
    if 'VENCIDA' not in u.columns:
        return []
    return sorted(u.loc[u['VENCIDA'], 'VIN'])


def vencidas_sin_desconectar(panorama):
    return len(vins_vencidas_sin_desconectar(panorama))


def leer_directorio_ejecutivos():
    """Directorio de ejecutivos si ya existe; vacío si no (no crea el archivo)."""
    try:
        if os.path.exists(ejecutivos_service.get_ejecutivos_csv_path()):
            return ejecutivos_service.leer_ejecutivos()
    except Exception:
        pass
    return pd.DataFrame(columns=["id_ejecutivo", "nombre", "correo", "alias", "activo"])


def _ejecutivos_canonicos(serie, directorio):
    """(nombre del directorio, está activo) por cada fila. Sin directorio, el
    nombre queda como viene y se considera activo."""
    cache = {}
    for crudo in serie.dropna().astype(str).str.strip().unique():
        if ejecutivos_service.normalizar_nombre(crudo) in ejecutivos_service._NOMBRES_IGNORADOS:
            cache[crudo] = (SIN_EJECUTIVO, False)
            continue
        fila = ejecutivos_service.buscar_ejecutivo(crudo, directorio, incluir_inactivos=True) if not directorio.empty else None
        if fila:
            cache[crudo] = (fila['nombre'], str(fila['activo']).strip().upper() != 'NO')
        else:
            cache[crudo] = (crudo, directorio.empty)
    claves = serie.astype(str).str.strip()
    nombres = claves.map(lambda c: cache.get(c, (SIN_EJECUTIVO, False))[0])
    activos = claves.map(lambda c: cache.get(c, (SIN_EJECUTIVO, False))[1])
    return nombres, activos.astype(bool)


def _titulo(serie, vacio):
    """Texto legible: 'NO DEFINIDA' -> 'No definida'; las siglas cortas (CM) se dejan en mayúsculas."""
    limpio = serie.astype(str).str.strip()
    sin_dato = limpio.str.lower().isin(('', '-', 'nan', 'none', 'sin registro'))
    legible = limpio.map(lambda v: v if len(v) <= 3 else v[:1].upper() + v[1:].lower() if v.isupper() else v)
    return legible.where(~sin_dato, vacio)


def calcular_panorama(df_master, directorio=None):
    """Una fila por VIN (contrato actual) y las fechas de alta y baja por VIN
    para el movimiento mensual (ver `_eventos_alta_baja`). Las unidades con
    ESTADO DE ACTIVACIÓN ACTUAL = NO APLICA (sin servicio Volvo Connect) vienen en
    el panorama, pero los filtros las dejan fuera salvo que se pida incluirlas
    (`SIN_NO_APLICA`). Devuelve None si no hay datos."""
    if df_master is None or df_master.empty or COL_VIN not in df_master.columns:
        return None
    directorio = leer_directorio_ejecutivos() if directorio is None else directorio
    actuales = contratos_actuales(df_master)

    def texto(col):
        return actuales[col].astype(str).str.strip() if col in actuales.columns else pd.Series('', index=actuales.index)

    vacios = ('', '-', 'nan', 'none')
    unidades = pd.DataFrame({
        'VIN': texto(COL_VIN).str.upper(),
        'FLOTA': texto(COL_FLOTA_VC).where(~texto(COL_FLOTA_VC).str.lower().isin(vacios), ''),
        'FORMA': texto(COL_FORMA_CONTRATO).where(~texto(COL_FORMA_CONTRATO).str.lower().isin(vacios), ''),
        'SERVICIO': texto(COL_TIPO_SERVICIO).where(~texto(COL_TIPO_SERVICIO).str.lower().isin(vacios), ''),
        'ACTIVACION': texto(COL_ESTADO_ACTIVACION).str.upper(),
        'COMERCIAL': _sin_tildes(texto(COL_ESTADO_COMERCIAL).str.upper()),
    })
    unidades['INDUSTRIA'] = _titulo(texto(COL_INDUSTRIA), 'Sin definir')
    unidades['MODELO'] = texto(COL_MODELO).str.upper().replace('', 'Sin modelo')
    unidades['FACTURACION'] = _titulo(texto(COL_TIPO_FACTURACION), 'Sin registro')
    unidades['PERIODO'] = texto(COL_PERIODO_INTERNO).str.lower()
    unidades['CLIENTE'] = clave_cliente_serie(texto(COL_RUT), texto(COL_RAZON_SOCIAL))
    unidades['CLIENTE_NOMBRE'] = texto(COL_RAZON_SOCIAL).where(~texto(COL_RAZON_SOCIAL).str.lower().isin(vacios), 'Sin razón social')
    unidades['EJECUTIVO'], unidades['EJ_ACTIVO'] = _ejecutivos_canonicos(
        actuales[COL_EJECUTIVO] if COL_EJECUTIVO in actuales.columns else pd.Series('', index=actuales.index), directorio)
    unidades['INICIO'] = (_fechas(actuales[COL_INICIO_CONTRATO]) if COL_INICIO_CONTRATO in actuales.columns
                          else pd.NaT)
    unidades['VENCIDA'] = _mascara_vencidas_sin_desconectar(actuales)
    unidades = unidades.reset_index(drop=True)
    altas, bajas = _eventos_alta_baja(df_master, set(unidades['VIN']))
    return {'unidades': unidades, 'altas': altas, 'bajas': bajas}


def potenciales_sin_vc(panorama, hoy=None):
    """Camiones Sin VC (forma de contrato Sin Contrato y facturación Sin Registro): clientes
    potenciales que no son seguros. Devuelve cuántos hay, cuántos entraron este mes (según su
    PERIODO INTERNO, "mes - año") y de esos cuántos son de clientes que ya tienen unidades
    conectadas. No depende de los filtros del tablero."""
    hoy = hoy or date.today()
    vacio = {'total': 0, 'nuevos_mes': 0, 'nuevos_con_cliente_vc': 0}
    if panorama is None:
        return vacio
    u = panorama['unidades']
    if u.empty or 'PERIODO' not in u.columns:
        return vacio
    es_sin_vc = mascara_potenciales(u)
    nuevos = _mascara_nuevos_sin_vc(u, hoy)
    clientes_vc = set(u.loc[(u['ACTIVACION'] == 'CONECTADO') & ~es_sin_vc, 'CLIENTE'])
    return {'total': int(es_sin_vc.sum()), 'nuevos_mes': int(nuevos.sum()),
            'nuevos_con_cliente_vc': int((nuevos & u['CLIENTE'].isin(clientes_vc)).sum())}


def _mascara_nuevos_sin_vc(u, hoy):
    """Camiones Sin VC cuyo PERIODO INTERNO es el mes de `hoy`."""
    periodo = u['PERIODO'].str.replace(r'\s+', '', regex=True)
    return mascara_potenciales(u) & (periodo == f"{MESES[hoy.month - 1].lower()}-{hoy.year}")


def vins_nuevos_sin_vc(panorama, hoy=None):
    """VIN de los camiones Sin VC que entraron este mes (los que cuenta `potenciales_sin_vc`)."""
    if panorama is None or panorama['unidades'].empty or 'PERIODO' not in panorama['unidades'].columns:
        return []
    u = panorama['unidades']
    return sorted(u.loc[_mascara_nuevos_sin_vc(u, hoy or date.today()), 'VIN'])


def vins_vendidos_mes(panorama, periodo):
    """VIN de las unidades vendidas (altas) en `periodo`."""
    if panorama is None:
        return []
    altas = panorama['altas']
    return sorted(set(altas.loc[altas['FECHA'].dt.to_period('M') == periodo, 'VIN']))


def vins_vendidos_mes_estado(panorama, periodo, estado):
    """VIN de las unidades vendidas en `periodo` según cómo están hoy: 'conectadas' (Conectado, Activando, Sin flota
    y No entregado, como la tarjeta Conectados), 'desconectadas' o 'por_conectar' (los demás estados)."""
    vendidas = set(vins_vendidos_mes(panorama, periodo))
    if not vendidas:
        return []
    u = panorama['unidades']
    conectadas = set(u.loc[u['ACTIVACION'].isin(ESTADOS_TARJETA_CONECTADOS), 'VIN'])
    desconectadas = set(u.loc[u['ACTIVACION'] == 'DESCONECTADO', 'VIN'])
    if estado == 'conectadas':
        return sorted(vendidas & conectadas)
    if estado == 'desconectadas':
        return sorted(vendidas & desconectadas)
    return sorted(vendidas - conectadas - desconectadas)


def mascara_potenciales(u):
    """Camiones Sin VC: forma de contrato Sin Contrato y facturación Sin Registro."""
    return (_sin_tildes(u['FORMA'].str.upper()) == 'SIN CONTRATO') & (u['FACTURACION'].str.upper() == 'SIN REGISTRO')


def opciones_filtro(panorama):
    """Valores disponibles para los filtros: ejecutivos activos, formas de contrato y servicios."""
    if panorama is None:
        return {c: [] for c in COLUMNAS_FILTRO}
    u = panorama['unidades']
    ejecutivos = u.loc[u['EJ_ACTIVO'] & (u['EJECUTIVO'] != SIN_EJECUTIVO), 'EJECUTIVO']
    return {
        'EJECUTIVO': sorted(ejecutivos.unique()),
        'FORMA': sorted(v for v in u['FORMA'].unique() if v),
        'FLOTA': sorted(v for v in u['FLOTA'].unique() if v),
        'SERVICIO': sorted(v for v in u['SERVICIO'].unique() if v),
    }


ORDEN_PLANES = ("basico", "medio", "full")


def partes_servicio(texto):
    """('plan', tiene CIV, tiene SZ) de un tipo de servicio como 'MEDIO + CIV + SZ'."""
    partes = [p.strip().casefold() for p in str(texto).split('+')]
    plan = partes[0].replace('á', 'a') if partes else ''
    return plan, 'civ' in partes[1:], 'sz' in partes[1:]


def planes_servicio(panorama):
    """[(clave, etiqueta)] de los planes presentes: básico, medio y full primero."""
    if panorama is None:
        return []
    etiquetas = {}
    for valor in panorama['unidades']['SERVICIO'].unique():
        plan = partes_servicio(valor)[0]
        if plan:
            etiquetas.setdefault(plan, str(valor).split('+')[0].strip().capitalize())
    orden = sorted(etiquetas, key=lambda p: (ORDEN_PLANES.index(p) if p in ORDEN_PLANES else len(ORDEN_PLANES), p))
    return [(p, etiquetas[p]) for p in orden]


def anios_inicio(panorama):
    """Años en que iniciaron los contratos actuales, del más reciente al más antiguo."""
    if panorama is None:
        return []
    return sorted({int(a) for a in panorama['unidades']['INICIO'].dropna().dt.year}, reverse=True)


def _mascara_periodo(inicio, filtro):
    """Unidades cuyo contrato actual inició en el año y/o mes indicados."""
    mascara = pd.Series(True, index=inicio.index)
    if filtro.get('anio'):
        mascara &= inicio.dt.year == filtro['anio']
    if filtro.get('meses'):
        mascara &= inicio.dt.month.isin(list(filtro['meses']))
    return mascara


def periodos_del_filtro(periodo, hoy=None, anio_min=None):
    """Meses (pd.Period, del más antiguo al más nuevo) que muestran los gráficos mensuales según
    el filtro de periodo: un año = sus meses hasta hoy; meses sueltos = esos meses de cada año.
    Devuelve None cuando no hay filtro de periodo (se usan los últimos 12 meses)."""
    if not periodo or not (periodo.get('anio') or periodo.get('meses')):
        return None
    hoy = hoy or date.today()
    actual = pd.Period(year=hoy.year, month=hoy.month, freq='M')
    meses = sorted(periodo.get('meses') or [])
    if periodo.get('anio'):
        candidatos = [pd.Period(year=periodo['anio'], month=m, freq='M') for m in (meses or range(1, 13))]
    else:
        desde = min(anio_min or hoy.year, hoy.year)
        candidatos = [pd.Period(year=a, month=m, freq='M') for a in range(desde, hoy.year + 1) for m in meses]
    return [p for p in candidatos if p <= actual][-12:]


def tiene_complemento(unidades, clave):
    """True si alguna unidad incluye el complemento ('civ' o 'sz') en su servicio."""
    indice = 1 if clave == 'civ' else 2
    return any(partes_servicio(v)[indice] for v in unidades['SERVICIO'].dropna().unique())


def meses_inicio(panorama):
    """Números de mes (1-12) en que iniciaron contratos las unidades."""
    if panorama is None:
        return []
    return sorted({int(m) for m in panorama['unidades']['INICIO'].dropna().dt.month})


def _mascara_servicio(serie, filtro):
    """Unidades cuyo servicio cumple el plan y los CIV / SZ marcados."""
    info = {v: partes_servicio(v) for v in serie.dropna().unique()}
    mascara = pd.Series(True, index=serie.index)
    if filtro.get('plan'):
        planes = [filtro['plan']] if isinstance(filtro['plan'], str) else list(filtro['plan'])
        mascara &= serie.map({v: i[0] for v, i in info.items()}).fillna('').isin(planes)
    if filtro.get('civ'):
        mascara &= serie.map({v: i[1] for v, i in info.items()}).fillna(False).astype(bool)
    if filtro.get('sz'):
        mascara &= serie.map({v: i[2] for v, i in info.items()}).fillna(False).astype(bool)
    return mascara


# Máscaras ya calculadas de las unidades en uso: cambiar un filtro reutiliza las de los demás
_CACHE_MASCARAS = {'u': None, 'm': {}}


def _mascara_cacheada(u, clave, calcular):
    cache = _CACHE_MASCARAS
    if cache['u'] is not u:
        cache['u'], cache['m'] = u, {}
    mascara = cache['m'].get(clave)
    if mascara is None:
        mascara = cache['m'][clave] = calcular()
    return mascara


def _mascara_unidades(u, filtros):
    mascara = pd.Series(True, index=u.index)
    for columna, valor in filtros.items():
        if valor:
            if columna == 'SIN_PRUEBAS':
                mascara &= _mascara_cacheada(u, 'SIN_PRUEBAS', lambda: ~u['FORMA'].str.upper().isin(FORMAS_PRUEBA))
            elif columna == 'SIN_NO_APLICA':
                mascara &= _mascara_cacheada(u, 'SIN_NO_APLICA', lambda: u['ACTIVACION'] != 'NO APLICA')
            elif columna == 'PERIODO':
                for parte in ('anio', 'meses'):
                    if valor.get(parte):
                        mascara &= _mascara_cacheada(u, ('PERIODO', parte, repr(valor[parte])),
                                                     lambda parte=parte: _mascara_periodo(u['INICIO'], {parte: valor[parte]}))
            elif isinstance(valor, dict):
                for parte in ('plan', 'civ', 'sz'):
                    if valor.get(parte):
                        mascara &= _mascara_cacheada(u, (columna, parte, repr(valor[parte])),
                                                     lambda parte=parte: _mascara_servicio(u[columna], {parte: valor[parte]}))
            elif isinstance(valor, (list, tuple, set, frozenset)):
                mascara &= _mascara_cacheada(u, (columna, 'lista', repr(sorted(map(str, valor)))),
                                             lambda: u[columna].isin(list(valor)))
            else:
                mascara &= _mascara_cacheada(u, (columna, 'valor', repr(valor)), lambda: (
                    u[columna] == valor if (u[columna] == valor).any()
                    else u[columna].astype(str).str.contains(valor, case=False, regex=False)))
    return mascara


def unidades_filtradas(panorama, **filtros):
    """Solo las unidades que cumplen los filtros (más liviano que `filtrar_panorama`,
    sirve para saber qué opciones quedan disponibles en cada filtro)."""
    u = panorama['unidades']
    return u[_mascara_unidades(u, filtros)]


def filtrar_panorama(panorama, **filtros):
    """Panorama restringido a las unidades que cumplen los filtros no vacíos
    (EJECUTIVO, FORMA, FLOTA, SERVICIO como {'plan', 'civ', 'sz'} y PERIODO como {'anio', 'mes'})."""
    if panorama is None:
        return None
    u = panorama['unidades']
    mascara = _mascara_unidades(u, filtros)
    if mascara.all():
        return panorama
    sub = u[mascara]
    vins = set(sub['VIN'])
    return {'unidades': sub.reset_index(drop=True),
            'altas': panorama['altas'][panorama['altas']['VIN'].isin(vins)].reset_index(drop=True),
            'bajas': panorama['bajas'][panorama['bajas']['VIN'].isin(vins)].reset_index(drop=True)}


# Estados que suma la tarjeta Conectados (pedido del usuario, 12-11-2026): conectados de verdad más los que
# aún no se conectan pero siguen vigentes (Activando, Sin flota, No entregado)
ESTADOS_TARJETA_CONECTADOS = ('CONECTADO', 'ACTIVANDO', 'SIN FLOTA', 'NO ENTREGADO')


def _mascara_sin_facturacion(unidades):
    """Unidades cuyo tipo de facturación está en «Sin registro» (también cuando viene vacío)."""
    return unidades['FACTURACION'].astype(str).str.strip().str.upper().isin(('SIN REGISTRO', ''))


def vins_sin_cobertura(unidades):
    """VIN de los camiones conectados (los de la tarjeta Conectados) que aún no tienen facturación registrada."""
    mascara = unidades['ACTIVACION'].isin(ESTADOS_TARJETA_CONECTADOS) & _mascara_sin_facturacion(unidades)
    return sorted(set(unidades.loc[mascara, 'VIN']))


def calcular_kpis(unidades):
    """Cifras de las cuatro tarjetas a partir de las unidades (una fila por VIN)."""
    universo = len(unidades)
    activacion = unidades['ACTIVACION']
    conectadas = int((activacion == 'CONECTADO').sum())
    no_conectada = universo - conectadas
    desglose = [(estado, int((activacion == estado).sum())) for estado in ESTADOS_NO_CONECTADA]
    otros = no_conectada - sum(n for _, n in desglose)
    if otros > 0:
        desglose.append(("OTROS", otros))
    servicio = unidades['SERVICIO'].str.upper()
    con_producto = activacion.isin(ESTADOS_TARJETA_CONECTADOS)
    base_producto = int(con_producto.sum())
    con_cobertura = con_producto & ~_mascara_sin_facturacion(unidades)
    civ = int((servicio.str.contains('CIV', na=False) & con_producto).sum())
    sz = int((servicio.str.contains(r'\bSZ\b', regex=True, na=False) & con_producto).sum())
    return {
        'universo': universo,
        'conectadas': conectadas,
        # Tarjeta Conectados del Resumen y base de CIV / Safety Zone (ver ESTADOS_TARJETA_CONECTADOS)
        'con_producto': base_producto,
        'desglose_conectados': [(e, int((activacion == e).sum())) for e in ESTADOS_TARJETA_CONECTADOS],
        # Cobertura comercial: de esos conectados, los que ya tienen su facturación registrada
        'cobertura': int(con_cobertura.sum()),
        'cobertura_pct': int(con_cobertura.sum()) / base_producto if base_producto else 0.0,
        'take_rate': conectadas / universo if universo else 0.0,
        'civ': civ,
        'civ_pct': civ / base_producto if base_producto else 0.0,
        'sz': sz,
        'sz_pct': sz / base_producto if base_producto else 0.0,
        'no_conectada': no_conectada,
        'desglose_no_conectada': desglose,
    }


def resultado_comercial(df_master, vins=None):
    """Por mes de INICIO CONTRATO, cuántos contratos reemplazan a uno anterior de la misma unidad y de qué tipo:
    renovación (el anterior quedó Renovado), upgrade (el plan sube de Básico a Medio o Full, o de Medio a Full) y
    regularización (la unidad pasa de Sin registro de facturación a tenerla registrada). Un DataFrame con una fila
    por contrato nuevo y las columnas PERIODO, RENOVACION, UPGRADE y REGULARIZACION."""
    cols = [COL_VIN, COL_INICIO_CONTRATO, COL_ESTADO_COMERCIAL, COL_TIPO_SERVICIO, COL_TIPO_FACTURACION]
    vacio = pd.DataFrame(columns=['PERIODO', 'RENOVACION', 'UPGRADE', 'REGULARIZACION'])
    if df_master is None or df_master.empty or any(c not in df_master.columns for c in cols):
        return vacio
    d = df_master[cols].copy()
    d['VIN'] = d[COL_VIN].astype(str).str.strip().str.upper()
    if vins is not None:
        d = d[d['VIN'].isin(set(vins))]
    d['INI'] = _fechas(d[COL_INICIO_CONTRATO])
    d = d.dropna(subset=['INI']).sort_values(['VIN', 'INI'])
    rango = {'basico': 1, 'medio': 2, 'full': 3}
    servicios = d[COL_TIPO_SERVICIO].astype(str)
    d['PLAN'] = servicios.map({v: rango.get(partes_servicio(v)[0], 0) for v in servicios.unique()})
    d['SIN_FACT'] = d[COL_TIPO_FACTURACION].astype(str).str.strip().str.lower().isin(('', 'nan', 'none', 'sin registro', 'sin definir'))
    g = d.groupby('VIN')
    previo_estado = g[COL_ESTADO_COMERCIAL].shift().fillna('').astype(str).str.upper()
    previo_plan, previo_sin = g['PLAN'].shift(), g['SIN_FACT'].shift()
    tiene_previo = previo_plan.notna()
    out = pd.DataFrame({'PERIODO': d['INI'].dt.to_period('M'),
                        'RENOVACION': tiene_previo & (previo_estado == 'RENOVADO'),
                        'UPGRADE': tiene_previo & (previo_plan > 0) & (d['PLAN'] > previo_plan),
                        'REGULARIZACION': tiene_previo & (previo_sin == True) & ~d['SIN_FACT']})  # noqa: E712
    return out[tiene_previo].reset_index(drop=True)


def mix_planes(unidades):
    """Plan (básico, medio o full) y complementos (CIV, SZ) de las unidades con Volvo Connect (las de la tarjeta
    Conectados). Cada plan trae su cantidad, cuántas llevan CIV, SZ o ambos y sus VIN."""
    con = unidades[unidades['ACTIVACION'].isin(ESTADOS_TARJETA_CONECTADOS)]
    info = {v: partes_servicio(v) for v in con['SERVICIO'].unique()}
    plan = con['SERVICIO'].map({v: x[0] for v, x in info.items()})
    civ = con['SERVICIO'].map({v: x[1] for v, x in info.items()}).astype(bool)
    sz = con['SERVICIO'].map({v: x[2] for v, x in info.items()}).astype(bool)
    base = len(con)
    nombres = {'basico': "Básico", 'medio': "Medio", 'full': "Full"}

    def resumen(clave, nombre, mascara):
        return {'clave': clave, 'nombre': nombre, 'n': int(mascara.sum()), 'pct': int(mascara.sum()) / base if base else 0.0,
                'civ': int((mascara & civ).sum()), 'sz': int((mascara & sz).sum()), 'ambos': int((mascara & civ & sz).sum()),
                'vins': sorted(con.loc[mascara, 'VIN'].unique())}
    planes = [resumen(c, n, plan == c) for c, n in nombres.items()]
    sin_plan = ~plan.isin(list(nombres))
    if sin_plan.any():
        planes.append(resumen('', "Sin plan", sin_plan))
    return {'base': base, 'planes': planes,
            'civ': int(civ.sum()), 'sz': int(sz.sum()), 'ambos': int((civ & sz).sum()),
            'vins_civ': sorted(con.loc[civ, 'VIN'].unique()), 'vins_sz': sorted(con.loc[sz, 'VIN'].unique())}


def calcular_mensual(panorama, n_meses=12, hoy=None, periodos=None):
    """Por cada uno de los últimos `n_meses` meses, o de los `periodos` dados (el más antiguo
    primero): unidades vendidas (altas), de ellas cuántas están conectadas y cuántas
    desconectadas hoy, bajas y neto."""
    hoy = hoy or date.today()
    final = pd.Period(year=hoy.year, month=hoy.month, freq='M')
    meses = periodos if periodos is not None else [final - k for k in range(n_meses - 1, -1, -1)]
    altas, bajas = panorama['altas'], panorama['bajas']
    conectadas = set(panorama['unidades'].loc[panorama['unidades']['ACTIVACION'] == 'CONECTADO', 'VIN'])
    desconectadas = set(panorama['unidades'].loc[panorama['unidades']['ACTIVACION'] == 'DESCONECTADO', 'VIN'])
    en_tarjeta = set(panorama['unidades'].loc[panorama['unidades']['ACTIVACION'].isin(ESTADOS_TARJETA_CONECTADOS), 'VIN'])
    alta_p = altas['FECHA'].dt.to_period('M')
    baja_p = bajas['FECHA'].dt.to_period('M')
    tipo_baja = bajas['TIPO'] if 'TIPO' in bajas.columns else pd.Series(TIPO_BAJA_DADA, index=bajas.index)
    alta_con_p = alta_p[altas['VIN'].isin(conectadas)]
    alta_des_p = alta_p[altas['VIN'].isin(desconectadas)]
    alta_tar_p = alta_p[altas['VIN'].isin(en_tarjeta)]
    serie = []
    for p in meses:
        vendidas = int((alta_p == p).sum())
        n_bajas = int((baja_p == p).sum())
        # 'conectadas_total': vendidas en Conectado, Activando, Sin flota o No entregado, como la tarjeta Conectados
        serie.append({'periodo': p, 'vendidas': vendidas, 'conectadas': int((alta_con_p == p).sum()),
                      'conectadas_total': int((alta_tar_p == p).sum()),
                      'desconectadas': int((alta_des_p == p).sum()),
                      'bajas': n_bajas, 'neto': vendidas - n_bajas,
                      'bajas_dadas': int(((baja_p == p) & (tipo_baja == TIPO_BAJA_DADA)).sum()),
                      'bajas_solicitadas': int(((baja_p == p) & (tipo_baja == TIPO_BAJA_SOLICITADA)).sum()),
                      'bajas_sin_fecha': int(((baja_p == p) & (tipo_baja == TIPO_BAJA_SIN_FECHA)).sum()),
                      'base': int((alta_p <= p).sum() - (baja_p <= p).sum())})
    return serie


def detalle_clientes_mes(panorama, periodo, limite=8):
    """Clientes de las unidades vendidas (altas) en `periodo`: por cada uno cuántas
    están conectadas, activando y desconectadas hoy y el total, de más a menos
    unidades. Devuelve las `limite` primeras filas, cuántos clientes quedaron fuera
    y el total de unidades del mes."""
    vacio = {'filas': [], 'otros': 0, 'total': 0}
    altas = panorama['altas']
    vins = set(altas.loc[altas['FECHA'].dt.to_period('M') == periodo, 'VIN'])
    if not vins:
        return vacio
    u = panorama['unidades']
    u = u[u['VIN'].isin(vins)]
    if u.empty:
        return vacio
    por_cliente = pd.DataFrame({
        'clave': u['CLIENTE'], 'nombre': u['CLIENTE_NOMBRE'],
        'conectadas': u['ACTIVACION'] == 'CONECTADO', 'activando': u['ACTIVACION'] == 'ACTIVANDO',
        'desconectadas': u['ACTIVACION'] == 'DESCONECTADO',
    }).groupby('clave').agg(nombre=('nombre', 'first'), conectadas=('conectadas', 'sum'), activando=('activando', 'sum'),
                            desconectadas=('desconectadas', 'sum'), total=('nombre', 'size'))
    por_cliente = por_cliente.sort_values(['total', 'nombre'], ascending=[False, True])
    filas = [{'nombre': f['nombre'], 'conectadas': int(f['conectadas']), 'activando': int(f['activando']),
              'desconectadas': int(f['desconectadas']), 'total': int(f['total'])}
             for _, f in por_cliente.head(limite).iterrows()]
    return {'filas': filas, 'otros': max(0, len(por_cliente) - limite), 'total': int(len(u))}


def vins_desconectadas_sin_fecha(panorama):
    """VIN de las unidades con estado Desconectado que no tienen ninguna fecha de baja ni de
    término: no pueden ubicarse en un mes del comparativo."""
    u = panorama['unidades']
    con_fecha = set(panorama['bajas']['VIN'])
    return sorted(u.loc[(u['ACTIVACION'] == 'DESCONECTADO') & ~u['VIN'].isin(con_fecha), 'VIN'])


def desconectadas_sin_fecha(panorama):
    return len(vins_desconectadas_sin_fecha(panorama))


def conexion_por_servicio(unidades):
    """Por tipo de servicio: unidades, conectadas y porcentaje conectado, del que
    mejor conecta al que peor."""
    filas = []
    for servicio, grupo in unidades[unidades['SERVICIO'] != ''].groupby('SERVICIO'):
        n = len(grupo)
        con = int((grupo['ACTIVACION'] == 'CONECTADO').sum())
        filas.append({'servicio': servicio, 'n': n, 'conectadas': con, 'pct': con / n})
    return sorted(filas, key=lambda f: (-f['pct'], -f['n'], f['servicio']))


def _paso_por_vc(unidades):
    comercial, activacion = unidades['COMERCIAL'], unidades['ACTIVACION']
    return comercial.isin(COMERCIAL_PASO_POR_VC) | ((comercial == 'REVISAR') & activacion.isin(ACTIVACION_REAL))


def fuga_por_segmento(unidades, columna, minimo=30, limite=10):
    """% de unidades desconectadas en cada grupo de `columna` (INDUSTRIA, MODELO o
    FACTURACION), del que más pierde al que menos, y el promedio de todo el universo.
    Los grupos muy pequeños se dejan fuera para no mostrar porcentajes engañosos."""
    if unidades.empty:
        return {'promedio': 0.0, 'filas': []}
    desconectada = unidades['ACTIVACION'] == 'DESCONECTADO'
    resumen = pd.DataFrame({'grupo': unidades[columna], 'des': desconectada,
                            'con': unidades['ACTIVACION'] == 'CONECTADO'}).groupby('grupo').agg(
        size=('des', 'size'), sum=('des', 'sum'), con=('con', 'sum'))
    resumen = resumen[resumen['size'] >= min(minimo, max(3, len(unidades) // 40))]
    filas = [{'nombre': str(nombre), 'n': int(f['size']), 'des': int(f['sum']), 'con': int(f['con']),
              'tasa': float(f['sum'] / f['size'])} for nombre, f in resumen.iterrows()]
    filas.sort(key=lambda f: (-f['tasa'], -f['n']))
    filas = filas[:limite]
    perdidos = unidades[desconectada & (unidades['CLIENTE_NOMBRE'] != 'Sin razón social')]
    por_cliente = perdidos.groupby([columna, 'CLIENTE_NOMBRE']).size().sort_values(ascending=False)
    for f in filas:
        grupo = por_cliente[por_cliente.index.get_level_values(0) == f['nombre']] if not por_cliente.empty else por_cliente
        f['clientes'] = [(str(c), int(n)) for (_g, c), n in grupo.head(3).items()]
    return {'promedio': float(desconectada.mean()), 'filas': filas}


def clientes_a_recuperar(unidades, solo_parciales=False, limite=8):
    """Clientes con unidades desconectadas, de más a menos. Un cliente es 'parcial'
    si todavía tiene unidades conectadas (los más fáciles de recuperar)."""
    vacio = {'filas': [], 'con_desconexiones': 0, 'pct_top10': 0.0, 'parciales': 0}
    if unidades.empty:
        return vacio
    por_cliente = pd.DataFrame({
        'clave': unidades['CLIENTE'], 'nombre': unidades['CLIENTE_NOMBRE'],
        'con': unidades['ACTIVACION'] == 'CONECTADO', 'des': unidades['ACTIVACION'] == 'DESCONECTADO',
    }).groupby('clave').agg(nombre=('nombre', 'first'), con=('con', 'sum'), des=('des', 'sum'))
    con_des = por_cliente[por_cliente['des'] > 0]
    if con_des.empty:
        return vacio
    parciales = con_des[con_des['con'] > 0]
    base = parciales if solo_parciales else con_des
    top = base.sort_values(['des', 'con'], ascending=False).head(limite)
    return {
        'filas': [{'nombre': f['nombre'], 'con': int(f['con']), 'des': int(f['des'])} for _, f in top.iterrows()],
        'con_desconexiones': len(con_des),
        'pct_top10': float(con_des['des'].nlargest(10).sum() / con_des['des'].sum()),
        'parciales': len(parciales),
    }


def clientes_a_contactar(unidades, potenciales):
    """Clientes con camiones desconectados (a recuperar) o sin servicio de Volvo Connect (para ofrecerlo).
    `unidades` son las del tablero y `potenciales` las mismas con las No aplica incluidas, de donde salen los
    camiones Sin VC. Por cliente: cuántos camiones conectados, desconectados y sin servicio, sus ejecutivos
    activos, los VIN a contactar (desconectados y sin servicio) y la acción: 'rec', 'ofr' o 'amb' (ambas).
    Los clientes vienen de más a menos camiones por contactar."""
    vacio = {'filas': [], 'con_desconectados': 0, 'para_ofrecer': 0, 'ya_usan': 0, 'ambas': 0}
    sin = potenciales[mascara_potenciales(potenciales)] if not potenciales.empty else potenciales
    base = unidades[~unidades['VIN'].isin(set(sin['VIN']))] if not unidades.empty else unidades

    def tabla(u, es_sin):
        return pd.DataFrame({
            'cliente': u['CLIENTE'], 'nombre': u['CLIENTE_NOMBRE'], 'vin': u['VIN'],
            'con': (u['ACTIVACION'] == 'CONECTADO') & (not es_sin), 'des': (u['ACTIVACION'] == 'DESCONECTADO') & (not es_sin),
            'sin': es_sin, 'ej': u['EJECUTIVO'], 'ej_ok': u['EJ_ACTIVO'] & (u['EJECUTIVO'] != SIN_EJECUTIVO)})

    todo = pd.concat([tabla(base, False), tabla(sin, True)], ignore_index=True)
    if todo.empty:
        return vacio
    resumen = todo.groupby('cliente').agg(nombre=('nombre', 'first'), con=('con', 'sum'), des=('des', 'sum'), sin=('sin', 'sum'))
    resumen = resumen[((resumen['des'] > 0) | (resumen['sin'] > 0)) & (resumen['nombre'] != 'Sin razón social')]
    if resumen.empty:
        return vacio
    resumen['total'] = resumen['des'] + resumen['sin']
    resumen = resumen.sort_values(['total', 'nombre'], ascending=[False, True])
    sub = todo[todo['cliente'].isin(resumen.index)]
    vins = sub[sub['des'] | sub['sin']].groupby('cliente')['vin'].agg(lambda s: sorted(set(s)))
    ejecutivos = sub[sub['ej_ok']].groupby('cliente')['ej'].agg(lambda s: sorted(set(s)))
    filas = []
    for clave, f in resumen.iterrows():
        des, sin_n = int(f['des']), int(f['sin'])
        filas.append({'clave': clave, 'nombre': f['nombre'], 'con': int(f['con']), 'des': des, 'sin': sin_n,
                      'ejecutivos': ejecutivos.get(clave, []), 'vins': vins.get(clave, []),
                      'accion': 'amb' if des and sin_n else ('rec' if des else 'ofr')})
    return {'filas': filas, 'con_desconectados': sum(1 for f in filas if f['des']),
            'para_ofrecer': sum(1 for f in filas if f['sin']), 'ya_usan': sum(1 for f in filas if f['des'] and f['con']),
            'ambas': sum(1 for f in filas if f['des'] and f['sin'])}


def por_ejecutivo_contactar(unidades, potenciales, clientes, limite=6):
    """Cartera de cada ejecutivo activo (conectados, por conectar, desconectados y sin servicio) y a
    cuántos clientes de `clientes` (filas de `clientes_a_contactar`) tiene por contactar. Un cliente con
    varios ejecutivos cuenta para cada uno. Vienen de más a menos clientes por contactar."""
    datos = {f['ejecutivo']: {'ejecutivo': f['ejecutivo'], 'conectadas': f['conectadas'], 'por_conectar': f['por_conectar'],
                              'desconectadas': f['desconectadas'], 'sin': 0, 'k': 0}
             for f in camiones_por_ejecutivo(unidades, limite=10 ** 6)['filas']}
    sin = potenciales[mascara_potenciales(potenciales)] if not potenciales.empty else potenciales
    if not sin.empty:
        activos = sin[sin['EJ_ACTIVO'] & (sin['EJECUTIVO'] != SIN_EJECUTIVO)]
        for nombre, n in activos.groupby('EJECUTIVO').size().items():
            datos.setdefault(nombre, {'ejecutivo': nombre, 'conectadas': 0, 'por_conectar': 0, 'desconectadas': 0, 'sin': 0, 'k': 0})['sin'] = int(n)
    for cliente in clientes:
        for nombre in cliente['ejecutivos']:
            if nombre in datos:
                datos[nombre]['k'] += 1
    filas = sorted(datos.values(), key=lambda f: (-f['k'], -(f['conectadas'] + f['por_conectar'] + f['desconectadas'] + f['sin']), f['ejecutivo']))
    return filas[:limite]


def camiones_por_ejecutivo(unidades, limite=MAX_EJECUTIVOS):
    """Camiones que pasaron por Volvo Connect según el ejecutivo que los vendió
    (solo ejecutivos activos, los `limite` con más unidades) y cuántos están
    conectados, por conectar y desconectados. `de_inactivos` cuenta los de
    ejecutivos que ya no están."""
    vc = unidades[_paso_por_vc(unidades)]
    activos = vc[vc['EJ_ACTIVO'] & (vc['EJECUTIVO'] != SIN_EJECUTIVO)]
    filas = []
    for ejecutivo, grupo in activos.groupby('EJECUTIVO'):
        con = int((grupo['ACTIVACION'] == 'CONECTADO').sum())
        des = int((grupo['ACTIVACION'] == 'DESCONECTADO').sum())
        filas.append({'ejecutivo': ejecutivo, 'n': len(grupo), 'conectadas': con, 'desconectadas': des,
                      'por_conectar': len(grupo) - con - des})
    filas.sort(key=lambda f: (-f['n'], f['ejecutivo']))
    return {'filas': filas[:limite], 'de_inactivos': int(len(vc) - len(activos))}

