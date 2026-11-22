"""Motor de deteccion y persistencia de casos de Revision CM. Python/pandas
puro: no depende de PyQt6, QThread ni ningun widget.

Un caso de Revision CM puede originarse por dos motivos independientes
(ver ORIGEN_CASO), cada uno con su propia condicion de deteccion y cierre:

  - AUSENCIA_3PC: un VIN que tenia datos CM desaparece del Excel mensual
    de 3PC. Regla de negocio confirmada con Javiera: esto NO confirma una
    baja. Se cierra (REAPARECIDO) cuando el VIN vuelve a aparecer en el
    3PC (ver actualizar_casos_baja_cm).
  - ESTADO_EXPIRED: el contrato CM de un VIN queda en ESTADO DEL CM =
    'Expired' o 'Pendiente' (deteccion en tiempo real vs. el estado de
    PruebasFM, no una ausencia). Se cierra (REAPARECIDO) cuando ESTADO DEL CM
    deja de ser Expired o Pendiente -- pasa a Running o a Terminated (ver
    reconciliar_casos_estado_expired).

Ambos carriles son independientes entre si aunque compartan VIN: un caso
AUSENCIA_3PC nunca se cierra ni se crea por logica de ESTADO_EXPIRED, y
viceversa. Esta capa SOLO detecta/reconcilia el caso y mantiene su
ESTADO_CASO -- nunca modifica PruebasFM ni decide por si sola que
corresponde una baja. La revision final (Mantener / Confirmar baja) es una
etapa posterior, todavia no implementada aqui.
"""

import functools
import os
import tempfile
import threading
import time
from datetime import datetime

import pandas as pd

from src.core.constants import ESTADO_CM_PENDIENTE, ESTADOS_CM_SIN_PAGO,FORMA_CONTRATO_TIPO_CM_MAP, TIPO_FACTURACION_HABILITA_CM

# Serializa los ciclos leer -> modificar -> escribir de CasosBajaCM.csv: la
# reconciliación por data_ready corre en un hilo de fondo (MainWindow) y
# puede coincidir con los guardados de Comercial/Contratos en el hilo de UI.
_LOCK_CASOS_BAJA_CM = threading.RLock()


def _con_lock_casos(funcion):
    @functools.wraps(funcion)
    def envoltura(*args, **kwargs):
        with _LOCK_CASOS_BAJA_CM:
            return funcion(*args, **kwargs)
    return envoltura

# Estados posibles de un caso. En esta etapa solo se generan/transicionan
# PENDIENTE y REAPARECIDO: MANTENIDO y CONFIRMADA_BAJA quedan definidos para
# la etapa de revision de Javiera (aun no implementada), para no tener que
# migrar el esquema de CasosBajaCM.csv despues.
ESTADO_CASO_PENDIENTE = 'PENDIENTE'
ESTADO_CASO_REAPARECIDO = 'REAPARECIDO'
ESTADO_CASO_MANTENIDO = 'MANTENIDO'
ESTADO_CASO_CONFIRMADA_BAJA = 'CONFIRMADA_BAJA'
# El contrato del caso se finalizó (Baja sin pendientes) o fue reemplazado por otro.
ESTADO_CASO_CONTRATO_CERRADO = 'CONTRATO_CERRADO'

# Por que se genero el caso. Dos carriles independientes que nunca se
# tocan entre si: un caso ORIGEN_CASO=AUSENCIA_3PC solo se cierra por
# reaparicion en el 3PC (ver actualizar_casos_baja_cm); un caso
# ORIGEN_CASO=ESTADO_EXPIRED solo se cierra cuando ESTADO DEL CM deja de
# ser 'Expired' (ver reconciliar_casos_estado_expired). No confundir con
# ESTADO DEL CM (estado real del contrato: Running/Expired/Terminated) ni
# con ESTADO_CASO (estado del caso de revision).
ORIGEN_CASO_AUSENCIA_3PC = 'AUSENCIA_3PC'
ORIGEN_CASO_ESTADO_EXPIRED = 'ESTADO_EXPIRED'
# Contrato vencido de forma o facturación CM que no trae ningún dato del 3PC (29-10-2026)
ORIGEN_CASO_DATOS_3PC_VACIOS = 'DATOS_3PC_VACIOS'
# CM en Running con el término ya vencido y sin pago este mes, que el 3PC todavía no cierra (30-10-2026)
ORIGEN_CASO_RUNNING_VENCIDO = 'RUNNING_VENCIDO'

# Texto amigable de ORIGEN_CASO para la UI (Revision CM). El valor tecnico
# nunca se muestra directamente al usuario.
ORIGEN_CASO_MOTIVO_MAP = {
    ORIGEN_CASO_AUSENCIA_3PC: 'Ausente de 3PC',
    ORIGEN_CASO_ESTADO_EXPIRED: 'Contrato expirado',
    ORIGEN_CASO_DATOS_3PC_VACIOS: 'Datos vacíos en 3PC',
    ORIGEN_CASO_RUNNING_VENCIDO: 'Término vencido sin pago',
}
# Caso Expired de una unidad que hoy tiene otra forma de contrato y facturación (no CM): sus datos CM son
# antiguos y se resuelven con "Pasar a CM" o "Limpiar datos CM" (28-10-2026)
MOTIVO_DATOS_CM_ANTIGUOS = 'Datos CM antiguos'

# Columnas de datos CM que definen si una fila de PruebasFM "tiene CM
# asociado". No alcanza con mirar solo ESTADO DEL CM: un registro legado
# podria traer el numero de contrato sin estado, o viceversa. Se considera
# "con CM" si CUALQUIERA de estas columnas tiene un valor real (no vacio/'-').
COLUMNAS_CM_ASOCIACION = ['N CONTRATO 3PC', 'ESTADO DEL CM']

# Datos de la unidad/CM que se guardan en cada caso al detectarlo (ademas de
# VIN, periodo/fecha de deteccion y estado del caso).
COLUMNAS_INFO_UNIDAD = ['CHASIS', 'RAZÓN SOCIAL', 'FLOTA VC']
COLUMNAS_DATOS_CM = ['N CONTRATO 3PC', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'TIPO DE CM', 'ESTADO DEL CM', 'PAGO CM']

CASOS_BAJA_CM_COLUMNS = (
    ['CASO_ID', 'VIN', 'ID CONTRATO'] + COLUMNAS_INFO_UNIDAD + COLUMNAS_DATOS_CM +
    ['PERIODO_DETECCION', 'FECHA_DETECCION', 'ESTADO_CASO', 'ORIGEN_CASO', 'MESES_CONSECUTIVOS_AUSENTE']
)


def _valor_vacio(v):
    """True si v debe tratarse como 'sin dato' (NaN, None, '', '-', o texto
    tipo 'nan'/'NaT'). Mismo criterio usado en otras partes del proyecto
    (ver comercial.py::_valor_esta_vacio) para no inventar un segundo
    criterio de 'vacio'."""
    if pd.isna(v):
        return True
    s = str(v).strip()
    return s == '' or s.upper() in ('-', 'NAN', 'NONE', 'NAT', '<NA>')


def _contrato_finalizado_inactivo(row):
    """Contrato en Baja o Baja Solicitada cuya unidad ya no está Conectada ni
    Activando: no tiene nada pendiente y no debe generar casos."""
    estado = str(row.get('ESTADO COMERCIAL', '')).strip().upper()
    activacion = str(row.get('ESTADO DE ACTIVACIÓN ACTUAL', '')).strip().upper()
    return estado in ('BAJA', 'BAJA SOLICITADA') and activacion not in ('CONECTADO', 'ACTIVANDO')


def _texto_columna(df, columna):
    """Columna como texto en mayúsculas y sin espacios; '' si la columna no existe."""
    if columna not in df.columns:
        return pd.Series('', index=df.index)
    return df[columna].astype(str).str.strip().str.upper()


def _mascara_finalizado_inactivo(df):
    """Versión por columnas de `_contrato_finalizado_inactivo` para todo el DataFrame."""
    estado = _texto_columna(df, 'ESTADO COMERCIAL')
    activacion = _texto_columna(df, 'ESTADO DE ACTIVACIÓN ACTUAL')
    return estado.isin(('BAJA', 'BAJA SOLICITADA')) & ~activacion.isin(('CONECTADO', 'ACTIVANDO'))


def _solo_contratos_actuales(df_pruebas):
    from src.services.comercial_services import contratos_actuales
    return contratos_actuales(df_pruebas)


def cerrar_casos_de_contratos_terminados(df_casos, df_pruebas_actual):
    """Completa ID CONTRATO en los casos que no lo tienen (con el contrato
    actual de su VIN) y cierra como CONTRATO_CERRADO los PENDIENTE cuyo
    contrato ya no existe como actual o quedó finalizado sin pendientes.
    Devuelve un DataFrame nuevo."""
    df_casos = _asegurar_columnas_y_backfill_origen(df_casos.copy())
    if df_casos.empty or df_pruebas_actual is None or df_pruebas_actual.empty \
            or 'VIN' not in df_pruebas_actual.columns or 'ID' not in df_pruebas_actual.columns:
        return df_casos[CASOS_BAJA_CM_COLUMNS]

    ids = df_pruebas_actual['ID'].astype(str).str.strip()
    ids = ids.where(~ids.str.endswith('.0'), ids.str[:-2])
    con_id = (ids != '') & (ids.str.lower() != 'nan')
    vins = df_pruebas_actual['VIN'].astype(str).str.strip().str.upper()
    id_por_vin = dict(zip(vins[con_id], ids[con_id]))
    activos = set(ids[con_id & ~_mascara_finalizado_inactivo(df_pruebas_actual)])

    df_casos['ID CONTRATO'] = df_casos['ID CONTRATO'].astype(object)
    vin_norm = df_casos['VIN'].astype(str).str.strip().str.upper()
    sin_id = df_casos['ID CONTRATO'].astype(str).str.strip() == ''
    df_casos.loc[sin_id, 'ID CONTRATO'] = vin_norm[sin_id].map(id_por_vin).fillna('')

    ids_caso = df_casos['ID CONTRATO'].astype(str).str.strip()
    cerrar = (df_casos['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE) & (ids_caso != '') & ~ids_caso.isin(activos)
    df_casos.loc[cerrar, 'ESTADO_CASO'] = ESTADO_CASO_CONTRATO_CERRADO
    return df_casos[CASOS_BAJA_CM_COLUMNS]


def tiene_datos_cm(row):
    """True si la fila de PruebasFM tiene informacion CM asociada. Se
    considera 'con CM' si N CONTRATO 3PC (identificador del contrato) o
    ESTADO DEL CM tienen un valor real -- no alcanza con verificar una sola
    columna (ver COLUMNAS_CM_ASOCIACION)."""
    return any(not _valor_vacio(row.get(col, '')) for col in COLUMNAS_CM_ASOCIACION)


def detectar_posibles_bajas_cm(df_pruebas_antes, vins_en_nuevo_listado, periodo_deteccion, hoy=None):
    """Compara el estado CM de PruebasFM ANTES de aplicar el nuevo Excel
    mensual de CM contra el conjunto de VIN presentes en ese nuevo Excel.

    Un VIN es "posible Baja CM" si:
      - tenia datos CM asociados en PruebasFM (ver tiene_datos_cm), Y
      - no aparece en `vins_en_nuevo_listado` (comparacion por VIN,
        normalizado a mayusculas/sin espacios).

    No modifica `df_pruebas_antes` ni decide nada sobre PruebasFM: solo
    identifica candidatos. Devuelve una lista de dicts (uno por VIN
    detectado), listos para ser procesados por actualizar_casos_baja_cm().
    """
    if hoy is None:
        hoy = datetime.now()

    if df_pruebas_antes.empty or 'VIN' not in df_pruebas_antes.columns:
        return []

    vins_nuevo_norm = {str(v).strip().upper() for v in vins_en_nuevo_listado}
    fecha_deteccion = hoy.strftime('%Y-%m-%d %H:%M:%S')

    detecciones = []
    for _, row in df_pruebas_antes.iterrows():
        vin_norm = str(row.get('VIN', '')).strip().upper()
        if not vin_norm or vin_norm == 'NAN':
            continue
        if not tiene_datos_cm(row):
            continue
        if vin_norm in vins_nuevo_norm:
            continue
        if _contrato_finalizado_inactivo(row):
            continue
        # CM ya dado de baja: conserva sus datos como historial y no vuelve a ser caso
        if str(row.get('ESTADO DEL CM', '')).strip().upper() == 'TERMINATED':
            continue

        deteccion = {'VIN': vin_norm, 'ID CONTRATO': str(row.get('ID', '')).strip()}
        for col in COLUMNAS_INFO_UNIDAD + COLUMNAS_DATOS_CM:
            deteccion[col] = row.get(col, '')
        deteccion['PERIODO_DETECCION'] = periodo_deteccion
        deteccion['FECHA_DETECCION'] = fecha_deteccion
        detecciones.append(deteccion)

    return detecciones


def _siguiente_caso_id(df_casos):
    if df_casos.empty or 'CASO_ID' not in df_casos.columns:
        return 1
    ids = pd.to_numeric(df_casos['CASO_ID'], errors='coerce').dropna()
    return int(ids.max()) + 1 if not ids.empty else 1


def _asegurar_columnas_y_backfill_origen(df_casos):
    """Garantiza que df_casos tenga todas las CASOS_BAJA_CM_COLUMNS y que
    ORIGEN_CASO nunca quede vacio: cualquier caso sin origen (CSV generado
    antes de que existiera esta columna, o fixture de test que no la seteo)
    solo pudo venir de la deteccion por ausencia en el 3PC -- es la unica
    que existia antes de agregar ORIGEN_CASO. Muta y devuelve `df_casos`."""
    if df_casos.empty:
        df_casos = pd.DataFrame(columns=CASOS_BAJA_CM_COLUMNS)
    for col in CASOS_BAJA_CM_COLUMNS:
        if col not in df_casos.columns:
            df_casos[col] = ''
    df_casos['ORIGEN_CASO'] = df_casos['ORIGEN_CASO'].astype(object)
    mask_sin_origen = df_casos['ORIGEN_CASO'].astype(str).str.strip() == ''
    df_casos.loc[mask_sin_origen, 'ORIGEN_CASO'] = ORIGEN_CASO_AUSENCIA_3PC
    return df_casos


def actualizar_casos_baja_cm(df_casos, detecciones, vins_en_nuevo_listado, hoy=None):
    """Aplica sobre `df_casos` (un caso por fila) las detecciones de esta
    corrida, evitando duplicados y marcando reapariciones. Alcance limitado
    SIEMPRE a ORIGEN_CASO=AUSENCIA_3PC: nunca lee ni modifica un caso con
    ORIGEN_CASO=ESTADO_EXPIRED (ver reconciliar_casos_estado_expired), aun
    si comparten el mismo VIN -- son carriles independientes.

      1. Reaparicion: cualquier caso AUSENCIA_3PC con ESTADO_CASO ==
         PENDIENTE cuyo VIN SI este en `vins_en_nuevo_listado` pasa a
         REAPARECIDO. Se cierra ese caso como historico; no se crea ninguno
         nuevo por este movimiento.
      2. Para cada VIN detectado como posible baja este mes (`detecciones`):
         - si ya existe un caso AUSENCIA_3PC PENDIENTE abierto para ese VIN,
           se actualiza en el mismo lugar (FECHA_DETECCION mas reciente,
           MESES_CONSECUTIVOS_AUSENTE + 1) -- NO se crea un caso nuevo. Esto
           cubre tanto "se reimporta el mismo archivo" como "el VIN sigue
           ausente un mes despues": mismo evento, mismo caso.
         - si no existe un caso AUSENCIA_3PC PENDIENTE abierto para ese VIN
           (nunca tuvo uno, o el unico que tuvo ya quedo REAPARECIDO/cerrado),
           se crea un caso PENDIENTE nuevo con CASO_ID nuevo. Esto cubre
           explicitamente "el VIN desaparece de nuevo despues de haber
           reaparecido": es un evento distinto, no se reabre ni se
           sobrescribe el caso REAPARECIDO anterior.

    Casos MANTENIDO/CONFIRMADA_BAJA/REAPARECIDO existentes nunca se
    modifican aqui (son historicos, fuera del alcance de esta funcion).

    No toca PruebasFM. Devuelve un DataFrame nuevo (no muta `df_casos`).
    """
    if hoy is None:
        hoy = datetime.now()

    df_casos = _asegurar_columnas_y_backfill_origen(df_casos.copy())

    vins_nuevo_norm = {str(v).strip().upper() for v in vins_en_nuevo_listado}

    # 1) Reaparicion (solo carril AUSENCIA_3PC).
    if not df_casos.empty:
        mask_reaparece = (
            (df_casos['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE) &
            (df_casos['ORIGEN_CASO'] == ORIGEN_CASO_AUSENCIA_3PC) &
            (df_casos['VIN'].astype(str).str.strip().str.upper().isin(vins_nuevo_norm))
        )
        df_casos.loc[mask_reaparece, 'ESTADO_CASO'] = ESTADO_CASO_REAPARECIDO

    # 2) Detecciones de este mes: actualizar caso abierto o crear uno nuevo
    # (mismo carril AUSENCIA_3PC).
    siguiente_id = _siguiente_caso_id(df_casos)
    filas_nuevas = []
    for deteccion in detecciones:
        vin_norm = deteccion['VIN']
        mask_abierto = (
            (df_casos['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE) &
            (df_casos['ORIGEN_CASO'] == ORIGEN_CASO_AUSENCIA_3PC) &
            (df_casos['VIN'].astype(str).str.strip().str.upper() == vin_norm)
        )
        if mask_abierto.any():
            idx = df_casos[mask_abierto].index[0]
            df_casos.at[idx, 'FECHA_DETECCION'] = deteccion['FECHA_DETECCION']
            actual = df_casos.at[idx, 'MESES_CONSECUTIVOS_AUSENTE']
            try:
                actual_num = int(actual) if str(actual).strip() != '' else 0
            except ValueError:
                actual_num = 0
            df_casos.at[idx, 'MESES_CONSECUTIVOS_AUSENTE'] = str(actual_num + 1)
        else:
            nueva_fila = {col: deteccion.get(col, '') for col in CASOS_BAJA_CM_COLUMNS}
            nueva_fila['CASO_ID'] = str(siguiente_id)
            nueva_fila['ESTADO_CASO'] = ESTADO_CASO_PENDIENTE
            nueva_fila['ORIGEN_CASO'] = ORIGEN_CASO_AUSENCIA_3PC
            nueva_fila['MESES_CONSECUTIVOS_AUSENTE'] = '1'
            siguiente_id += 1
            filas_nuevas.append(nueva_fila)

    if filas_nuevas:
        df_casos = pd.concat([df_casos, pd.DataFrame(filas_nuevas)], ignore_index=True)

    return df_casos[CASOS_BAJA_CM_COLUMNS]


def detectar_casos_expired_actuales(df_pruebas_actual, periodo_deteccion, hoy=None):
    """Devuelve un candidato a caso (dict) por cada VIN cuyo ESTADO DEL CM
    actual en `df_pruebas_actual` es 'Expired' o 'Pendiente'. A diferencia de
    detectar_posibles_bajas_cm, no compara contra una version anterior: el
    evento aqui es el estado ACTUAL del contrato (Running/Expired/
    Terminated), no una desaparicion del 3PC. No modifica
    `df_pruebas_actual`."""
    if hoy is None:
        hoy = datetime.now()

    if df_pruebas_actual.empty or 'VIN' not in df_pruebas_actual.columns or 'ESTADO DEL CM' not in df_pruebas_actual.columns:
        return []

    fecha_deteccion = hoy.strftime('%Y-%m-%d %H:%M:%S')
    mask_expired = df_pruebas_actual['ESTADO DEL CM'].astype(str).str.strip().str.upper().isin(ESTADOS_CM_SIN_PAGO)

    detecciones = []
    for _, row in df_pruebas_actual[mask_expired].iterrows():
        vin_norm = str(row.get('VIN', '')).strip().upper()
        if not vin_norm or vin_norm == 'NAN' or _contrato_finalizado_inactivo(row):
            continue
        deteccion = {'VIN': vin_norm, 'ID CONTRATO': str(row.get('ID', '')).strip()}
        for col in COLUMNAS_INFO_UNIDAD + COLUMNAS_DATOS_CM:
            deteccion[col] = row.get(col, '')
        deteccion['PERIODO_DETECCION'] = periodo_deteccion
        deteccion['FECHA_DETECCION'] = fecha_deteccion
        detecciones.append(deteccion)

    return detecciones


def _es_unidad_cm(row):
    forma = str(row.get('FORMA DE CONTRATO', '')).strip().upper()
    tipo = str(row.get('TIPO DE FACTURACION', row.get('TIPO DE FACTURACIÓN', ''))).strip().upper()
    return forma in FORMA_CONTRATO_TIPO_CM_MAP or tipo in TIPO_FACTURACION_HABILITA_CM


def mascara_datos_3pc_vacios(df):
    """Filas Vigentes o Vencidas de forma o facturación CM sin N° de contrato 3PC y sin ESTADO DEL CM; una
    marcada Pendiente sigue contando para que el caso no se cierre al marcarla."""
    columnas = {'ESTADO COMERCIAL', 'ESTADO DEL CM', 'N CONTRATO 3PC'}
    if df is None or df.empty or not columnas <= set(df.columns):
        return pd.Series(False, index=df.index if df is not None else None)
    estado = df['ESTADO COMERCIAL'].astype(str).str.strip().str.upper().isin(('VIGENTE', 'VENCIDO'))
    estado_cm = df['ESTADO DEL CM'].astype(str).str.strip().str.upper()
    sin_estado = _vacio_columna(df['ESTADO DEL CM']) | (estado_cm == ESTADO_CM_PENDIENTE.upper())
    sin_3pc = sin_estado & _vacio_columna(df['N CONTRATO 3PC'])
    return estado & sin_3pc & _mascara_unidad_cm(df)


def _vacio_columna(serie):
    """Versión por columnas de `_valor_vacio`."""
    return serie.isna() | serie.astype(str).str.strip().str.upper().isin(('', '-', 'NAN', 'NONE', 'NAT', '<NA>'))


def _mascara_unidad_cm(df):
    """Versión por columnas de `_es_unidad_cm`."""
    forma = _texto_columna(df, 'FORMA DE CONTRATO')
    tipo = _texto_columna(df, 'TIPO DE FACTURACION' if 'TIPO DE FACTURACION' in df.columns else 'TIPO DE FACTURACIÓN')
    return forma.isin(tuple(FORMA_CONTRATO_TIPO_CM_MAP)) | tipo.isin(tuple(TIPO_FACTURACION_HABILITA_CM))


def detectar_casos_datos_3pc_vacios(df_pruebas_actual, periodo_deteccion, hoy=None):
    """Un candidato a caso por cada contrato actual Vencido de forma o facturación CM que no trae ni N° de
    contrato 3PC ni ESTADO DEL CM: debería estar en el 3PC y no llegó nada. Mismo formato que
    detectar_casos_expired_actuales."""
    if hoy is None:
        hoy = datetime.now()
    columnas = {'VIN', 'ESTADO COMERCIAL', 'ESTADO DEL CM', 'N CONTRATO 3PC'}
    if df_pruebas_actual is None or df_pruebas_actual.empty or not columnas <= set(df_pruebas_actual.columns):
        return []
    fecha_deteccion = hoy.strftime('%Y-%m-%d %H:%M:%S')
    detecciones = []
    for _, row in df_pruebas_actual[mascara_datos_3pc_vacios(df_pruebas_actual)].iterrows():
        vin_norm = str(row.get('VIN', '')).strip().upper()
        if not vin_norm or vin_norm == 'NAN':
            continue
        deteccion = {'VIN': vin_norm, 'ID CONTRATO': str(row.get('ID', '')).strip()}
        for col in COLUMNAS_INFO_UNIDAD + COLUMNAS_DATOS_CM:
            deteccion[col] = row.get(col, '')
        deteccion['PERIODO_DETECCION'] = periodo_deteccion
        deteccion['FECHA_DETECCION'] = fecha_deteccion
        detecciones.append(deteccion)
    return detecciones


DIAS_AVISO_TERMINO_SIN_PAGO = 7


def pago_cubre_mes_actual(fecha, pago, hoy=None):
    """Serie booleana: el pago CM cubre el mes de hoy. Un pago dura el mes siguiente al
    que se hizo (como una suscripción), así que sirve el del mes anterior o el de este mes."""
    hoy = pd.Timestamp(hoy) if hoy is not None else pd.Timestamp.now()
    fecha = pd.to_datetime(fecha, errors='coerce', format='%d-%m-%Y')
    pago = pd.to_numeric(pago, errors='coerce').fillna(0)
    return (fecha.dt.to_period('M') >= hoy.to_period('M') - 1) & (pago > 0)


def mascara_running_vencido_sin_pago(df, hoy=None):
    """CM en Running sin pago este mes cuyo término ya venció o vence en los próximos
    DIAS_AVISO_TERMINO_SIN_PAGO días: el 3PC todavía no lo cierra."""
    columnas = {'ESTADO DEL CM', 'FECHA TERMINO CM', 'FECHA ULTIMO PAGO CM'}
    if df is None or df.empty or not columnas <= set(df.columns):
        return pd.Series(False, index=df.index if df is not None else None)
    hoy = pd.Timestamp(hoy) if hoy is not None else pd.Timestamp.now()
    running = df['ESTADO DEL CM'].astype(str).str.strip().str.upper() == 'RUNNING'
    termino = pd.to_datetime(df['FECHA TERMINO CM'], errors='coerce', format='%d-%m-%Y')
    vencido = termino.dt.normalize() <= hoy.normalize() + pd.Timedelta(days=DIAS_AVISO_TERMINO_SIN_PAGO)
    columna_pago = 'PAGO CM_NUM' if 'PAGO CM_NUM' in df.columns else 'PAGO CM'
    pago = df[columna_pago] if columna_pago in df.columns else pd.Series(0, index=df.index)
    return running & vencido & ~pago_cubre_mes_actual(df['FECHA ULTIMO PAGO CM'], pago, hoy)


def detectar_casos_running_vencido(df_pruebas_actual, periodo_deteccion, hoy=None):
    """Un candidato a caso por cada contrato actual en Running con el término vencido y sin pago este mes.
    Mismo formato que detectar_casos_expired_actuales."""
    if hoy is None:
        hoy = datetime.now()
    if df_pruebas_actual is None or df_pruebas_actual.empty or 'VIN' not in df_pruebas_actual.columns:
        return []
    fecha_deteccion = hoy.strftime('%Y-%m-%d %H:%M:%S')
    detecciones = []
    for _, row in df_pruebas_actual[mascara_running_vencido_sin_pago(df_pruebas_actual, hoy)].iterrows():
        vin_norm = str(row.get('VIN', '')).strip().upper()
        if not vin_norm or vin_norm == 'NAN' or _contrato_finalizado_inactivo(row):
            continue
        deteccion = {'VIN': vin_norm, 'ID CONTRATO': str(row.get('ID', '')).strip()}
        for col in COLUMNAS_INFO_UNIDAD + COLUMNAS_DATOS_CM:
            deteccion[col] = row.get(col, '')
        deteccion['PERIODO_DETECCION'] = periodo_deteccion
        deteccion['FECHA_DETECCION'] = fecha_deteccion
        detecciones.append(deteccion)
    return detecciones


def reconciliar_casos_estado_expired(df_casos, detecciones, vins_expired_actual, hoy=None):
    """Carril ESTADO_EXPIRED de `reconciliar_casos_por_origen`."""
    return reconciliar_casos_por_origen(df_casos, ORIGEN_CASO_ESTADO_EXPIRED, detecciones, vins_expired_actual, hoy)


def reconciliar_casos_por_origen(df_casos, origen, detecciones, vins_actuales, hoy=None):
    """Aplica sobre `df_casos` las detecciones de ESTADO DEL CM = 'Expired'
    actuales, en un carril propio (ORIGEN_CASO=ESTADO_EXPIRED) que nunca
    toca ni es tocado por los casos ORIGEN_CASO=AUSENCIA_3PC, aun si
    comparten VIN:

      1. Cierre: cualquier caso ESTADO_EXPIRED con ESTADO_CASO == PENDIENTE
         cuyo VIN YA NO este en `vins_expired_actual` (paso a Running o a
         Terminated) se marca REAPARECIDO -- deja de aparecer en Revision
         CM. No se crea un caso nuevo por este cierre, y no se toca
         ESTADO DEL CM ni ningun campo de PruebasFM.
      2. Para cada VIN detectado como Expired ahora (`detecciones`): si ya
         existe un caso ESTADO_EXPIRED PENDIENTE abierto para ese VIN no se
         toca (conserva su FECHA_DETECCION original, así el archivo no cambia
         en cada carga); si no existe, se crea uno nuevo con CASO_ID nuevo.

    No toca PruebasFM. Devuelve un DataFrame nuevo (no muta `df_casos`)."""
    if hoy is None:
        hoy = datetime.now()

    df_casos = _asegurar_columnas_y_backfill_origen(df_casos.copy())
    vins_expired_norm = {str(v).strip().upper() for v in vins_actuales}

    # 1) Cierre de casos que ya no cumplen la condicion (solo el carril `origen`).
    if not df_casos.empty:
        mask_cierre = (
            (df_casos['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE) &
            (df_casos['ORIGEN_CASO'] == origen) &
            (~df_casos['VIN'].astype(str).str.strip().str.upper().isin(vins_expired_norm))
        )
        df_casos.loc[mask_cierre, 'ESTADO_CASO'] = ESTADO_CASO_REAPARECIDO

    # 2) Detecciones actuales: actualizar caso abierto o crear uno nuevo
    # (mismo carril ESTADO_EXPIRED).
    siguiente_id = _siguiente_caso_id(df_casos)
    filas_nuevas = []
    for deteccion in detecciones:
        vin_norm = deteccion['VIN']
        mask_abierto = (
            (df_casos['ESTADO_CASO'] == ESTADO_CASO_PENDIENTE) &
            (df_casos['ORIGEN_CASO'] == origen) &
            (df_casos['VIN'].astype(str).str.strip().str.upper() == vin_norm)
        )
        if not mask_abierto.any():
            nueva_fila = {col: deteccion.get(col, '') for col in CASOS_BAJA_CM_COLUMNS}
            nueva_fila['CASO_ID'] = str(siguiente_id)
            nueva_fila['ESTADO_CASO'] = ESTADO_CASO_PENDIENTE
            nueva_fila['ORIGEN_CASO'] = origen
            nueva_fila['MESES_CONSECUTIVOS_AUSENTE'] = ''
            siguiente_id += 1
            filas_nuevas.append(nueva_fila)

    if filas_nuevas:
        df_casos = pd.concat([df_casos, pd.DataFrame(filas_nuevas)], ignore_index=True)

    return df_casos[CASOS_BAJA_CM_COLUMNS]


@_con_lock_casos
def leer_casos_baja_cm(path):
    """Lee CasosBajaCM.csv. Si no existe (primera vez), devuelve un
    DataFrame vacio con el esquema correcto -- no crea el archivo (eso lo
    hace guardar_casos_baja_cm()). Compatibilidad: un CSV de produccion
    generado antes de que existiera ORIGEN_CASO (o con la columna vacia)
    se migra en memoria a ORIGEN_CASO=AUSENCIA_3PC -- la unica deteccion
    que existia hasta ahora -- sin necesidad de tocar el archivo real."""
    if not path or not os.path.exists(path):
        return pd.DataFrame(columns=CASOS_BAJA_CM_COLUMNS)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    return _asegurar_columnas_y_backfill_origen(df)[CASOS_BAJA_CM_COLUMNS]


# Momento del último guardado de CasosBajaCM.csv hecho por esta app: el aviso de cambios lo ignora
_ULTIMA_ESCRITURA_PROPIA = [0.0]
VENTANA_ESCRITURA_PROPIA_S = 30


def escritura_propia_reciente():
    return time.time() - _ULTIMA_ESCRITURA_PROPIA[0] < VENTANA_ESCRITURA_PROPIA_S


def guardar_casos_baja_cm(df_casos, path):
    """Persiste `df_casos` en `path` (CSV, mismo formato simple que
    LogApp.csv). No hace nada si `path` no esta configurado."""
    if not path:
        return
    directorio = os.path.dirname(path)
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    # Archivo temporal en la misma carpeta y reemplazo: otro PC o OneDrive
    # nunca ven el CSV a medio escribir.
    fd, temporal = tempfile.mkstemp(suffix='.tmp', dir=directorio or None)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as archivo:
            df_casos.to_csv(archivo, index=False)
        os.replace(temporal, path)
        _ULTIMA_ESCRITURA_PROPIA[0] = time.time()
    except Exception:
        if os.path.exists(temporal):
            os.remove(temporal)
        raise


ESPERA_ARCHIVO_AUSENTE_S = 2


def _esperar_si_archivo_ausente(path):
    """Si CasosBajaCM.csv no existe pero su carpeta ya tiene archivos (carpeta
    compartida en uso), espera un momento antes de leerlo: OneDrive puede estar
    reemplazándolo, y leerlo como vacío haría crear uno nuevo desde el caso 1."""
    if not path or os.path.exists(path):
        return
    directorio = os.path.dirname(path)
    if directorio and os.path.isdir(directorio) and os.listdir(directorio):
        time.sleep(ESPERA_ARCHIVO_AUSENTE_S)


@_con_lock_casos
def procesar_deteccion_baja_cm(df_pruebas_antes, vins_en_nuevo_listado, periodo_deteccion, casos_path, hoy=None):
    """Punto de integracion unico para contratos.py: detecta posibles Bajas
    CM comparando el estado de PruebasFM ANTES del import contra el nuevo
    listado, actualiza/crea los casos correspondientes (sin duplicar,
    marcando reapariciones) y persiste el resultado. Nunca toca PruebasFM ni
    decide una baja: solo detecta y registra el caso para revision
    posterior de Javiera."""
    df_pruebas_antes = _solo_contratos_actuales(df_pruebas_antes)
    df_casos = cerrar_casos_de_contratos_terminados(leer_casos_baja_cm(casos_path), df_pruebas_antes)
    detecciones = detectar_posibles_bajas_cm(df_pruebas_antes, vins_en_nuevo_listado, periodo_deteccion, hoy=hoy)
    df_casos_actualizado = actualizar_casos_baja_cm(df_casos, detecciones, vins_en_nuevo_listado, hoy=hoy)
    guardar_casos_baja_cm(df_casos_actualizado, casos_path)
    return df_casos_actualizado


def confirmar_baja_caso(df_casos, caso_id):
    """Etapa de revision (Confirmar baja) que faltaba implementar: marca el
    caso con CASO_ID == `caso_id` como ESTADO_CASO=CONFIRMADA_BAJA, sin
    tocar ningun otro caso ni columna. No decide si corresponde a
    ORIGEN_CASO=AUSENCIA_3PC o ESTADO_EXPIRED: eso ya quedo fijado cuando el
    caso se creo. La limpieza de PruebasFM (ESTADO DEL CM -> Terminated y
    demas campos CM) es responsabilidad de quien llama a esta funcion (ver
    comercial.py::_on_accion_cm_confirmar_baja_clicked), no de aqui.

    Devuelve un DataFrame nuevo (no muta `df_casos`)."""
    df_casos = _asegurar_columnas_y_backfill_origen(df_casos.copy())
    mask = df_casos['CASO_ID'].astype(str).str.strip() == str(caso_id).strip()
    df_casos.loc[mask, 'ESTADO_CASO'] = ESTADO_CASO_CONFIRMADA_BAJA
    return df_casos[CASOS_BAJA_CM_COLUMNS]


@_con_lock_casos
def procesar_confirmacion_baja_cm(caso_id, casos_path):
    """Punto de integracion unico para comercial.py: marca el caso
    `caso_id` como CONFIRMADA_BAJA en CasosBajaCM.csv y persiste el
    resultado. No toca PruebasFM."""
    df_casos = leer_casos_baja_cm(casos_path)
    df_casos_actualizado = confirmar_baja_caso(df_casos, caso_id)
    guardar_casos_baja_cm(df_casos_actualizado, casos_path)
    return df_casos_actualizado


def confirmar_baja_casos(df_casos, caso_ids):
    """Version para varios casos a la vez de confirmar_baja_caso(): marca
    como ESTADO_CASO=CONFIRMADA_BAJA todos los CASO_ID en `caso_ids` (lista
    o cualquier iterable), en una sola pasada sobre `df_casos`, sin tocar
    ningun caso que no este en la lista. Una lista vacia no modifica nada.
    confirmar_baja_caso() sigue existiendo intacta para el caso de un solo
    CASO_ID (ver comercial.py: seleccionar un unico VIN en Gestionar CM
    sigue pasando por el mismo camino de guardado, solo que con una lista
    de un elemento).

    Devuelve un DataFrame nuevo (no muta `df_casos`)."""
    df_casos = _asegurar_columnas_y_backfill_origen(df_casos.copy())
    if not caso_ids:
        return df_casos[CASOS_BAJA_CM_COLUMNS]
    ids_norm = {str(c).strip() for c in caso_ids}
    mask = df_casos['CASO_ID'].astype(str).str.strip().isin(ids_norm)
    df_casos.loc[mask, 'ESTADO_CASO'] = ESTADO_CASO_CONFIRMADA_BAJA
    return df_casos[CASOS_BAJA_CM_COLUMNS]


@_con_lock_casos
def procesar_confirmacion_baja_cm_multiple(caso_ids, casos_path):
    """Punto de integracion unico para comercial.py cuando se confirma la
    baja de varios casos a la vez (seleccion multiple en Gestionar CM):
    una sola lectura y una sola escritura de CasosBajaCM.csv para todos los
    `caso_ids`, en vez de llamar a procesar_confirmacion_baja_cm() una vez
    por caso (evita N lecturas/escrituras del mismo archivo). No toca
    PruebasFM. Una lista vacia no escribe el archivo."""
    if not caso_ids:
        return leer_casos_baja_cm(casos_path)
    df_casos = leer_casos_baja_cm(casos_path)
    df_casos_actualizado = confirmar_baja_casos(df_casos, caso_ids)
    guardar_casos_baja_cm(df_casos_actualizado, casos_path)
    return df_casos_actualizado


@_con_lock_casos
def procesar_reconciliacion_estado_expired(df_pruebas_actual, periodo_deteccion, casos_path, hoy=None):
    """Punto de integracion unico para comercial.py/contratos.py: a partir
    del estado ACTUAL de PruebasFM (ya guardado -- despues de un import de
    3PC o de guardar una edicion manual de ESTADO DEL CM), detecta las
    unidades en 'Expired' y reconcilia (crea/refresca/cierra) los casos de
    Revision CM con ORIGEN_CASO=ESTADO_EXPIRED. Nunca toca PruebasFM ni los
    casos ORIGEN_CASO=AUSENCIA_3PC (ver reconciliar_casos_estado_expired)."""
    df_pruebas_actual = _solo_contratos_actuales(df_pruebas_actual)
    _esperar_si_archivo_ausente(casos_path)
    df_leido = leer_casos_baja_cm(casos_path)
    df_casos = cerrar_casos_de_contratos_terminados(df_leido, df_pruebas_actual)
    detecciones_vacios = detectar_casos_datos_3pc_vacios(df_pruebas_actual, periodo_deteccion, hoy=hoy)
    vins_vacios = {d['VIN'] for d in detecciones_vacios}
    # Una unidad sin datos del 3PC marcada Pendiente sigue en su caso, no pasa al carril Expired
    detecciones = [d for d in detectar_casos_expired_actuales(df_pruebas_actual, periodo_deteccion, hoy=hoy)
                   if d['VIN'] not in vins_vacios]

    vins_expired_actual = []
    if not df_pruebas_actual.empty and 'VIN' in df_pruebas_actual.columns and 'ESTADO DEL CM' in df_pruebas_actual.columns:
        mask = df_pruebas_actual['ESTADO DEL CM'].astype(str).str.strip().str.upper().isin(ESTADOS_CM_SIN_PAGO)
        vins_expired_actual = [v for v in df_pruebas_actual.loc[mask, 'VIN'].astype(str).str.strip().str.upper()
                               if v not in vins_vacios]

    df_casos_actualizado = reconciliar_casos_estado_expired(df_casos, detecciones, vins_expired_actual, hoy=hoy)
    df_casos_actualizado = reconciliar_casos_por_origen(
        df_casos_actualizado, ORIGEN_CASO_DATOS_3PC_VACIOS, detecciones_vacios, list(vins_vacios), hoy=hoy)
    detecciones_rv = detectar_casos_running_vencido(df_pruebas_actual, periodo_deteccion, hoy=hoy)
    df_casos_actualizado = reconciliar_casos_por_origen(
        df_casos_actualizado, ORIGEN_CASO_RUNNING_VENCIDO, detecciones_rv, [d['VIN'] for d in detecciones_rv], hoy=hoy)
    existe = bool(casos_path) and os.path.exists(casos_path)
    sin_cambios = existe and df_casos_actualizado.reset_index(drop=True).astype(str).equals(
        df_leido.reset_index(drop=True).astype(str))
    if not sin_cambios:
        guardar_casos_baja_cm(df_casos_actualizado, casos_path)
    return df_casos_actualizado
