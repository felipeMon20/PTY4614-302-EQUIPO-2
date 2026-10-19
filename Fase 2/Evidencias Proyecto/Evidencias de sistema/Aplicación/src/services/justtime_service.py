"""Lógica de datos de JustTime, separada de src/ui/justtime.py (mismo patrón
que contratos_service.py/facturacion_manual_service.py). Python/pandas puro,
sin PyQt6. Trabaja sobre una copia de DataManager().df_master.

CONTRATO CREADO EN JUSTTIME llega tal como está en PruebasFM (texto libre
heredado del RM): acá solo se clasifica contra JUSTTIME_ESTADO_OPCIONES, sin
modificar el dato. Los valores fuera del catálogo quedan "Por corregir" con
un estado sugerido (CONTRATO_JUSTTIME_MAP) que la contraparte comercial aplica a mano.
"""

import pandas as pd

from src.core.constants import (
    COL_ID, COL_VIN, COL_CHASIS, COL_RAZON_SOCIAL, COL_RUT, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION,
    COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_ETAPA_GESTION, COL_CONTRATO_JUSTTIME,
    COL_FECHA_INICIO_FACT, COL_FECHA_TERMINO_FACT, JUSTTIME_ESTADO_OPCIONES, JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_PENDIENTE, JUSTTIME_ESTADO_NO_APLICA, JUSTTIME_ESTADO_ELIMINAR,
    CONTRATO_JUSTTIME_MAP, TIPO_FACTURACION_HABILITA_JUSTTIME, VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_INTERNO,
)

COLUMNAS_BASE = [
    COL_ID, COL_VIN, COL_CHASIS, COL_RAZON_SOCIAL, COL_RUT, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION,
    COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_ETAPA_GESTION, COL_CONTRATO_JUSTTIME,
    COL_FECHA_INICIO_FACT, COL_FECHA_TERMINO_FACT,
]

# Columnas calculadas (no existen en PruebasFM)
COL_ESTADO_JT = "_ESTADO_JT"          # estado del catálogo, o POR_CORREGIR
COL_SUGERENCIA = "_SUGERENCIA_JT"     # estado sugerido para un valor fuera del catálogo
COL_INCONSISTENCIA = "_INCONSISTENCIA_JT"  # texto del problema, '' si no hay

POR_CORREGIR = "Por corregir"
ESTADOS_COMERCIALES_BAJA = {"BAJA", "BAJA SOLICITADA"}
_CATALOGO_POR_CLAVE = {e.upper(): e for e in JUSTTIME_ESTADO_OPCIONES}


def _clave(valor):
    texto = "" if valor is None or pd.isna(valor) else str(valor)
    return " ".join(texto.split()).upper()


def estado_canonico(valor):
    """Estado del catálogo que corresponde a `valor` (sin distinguir
    mayúsculas ni espacios), o None si no es un valor del catálogo. Vacío
    cuenta como "-"."""
    clave = _clave(valor)
    if clave in ('', 'NAN', 'NONE'):
        return JUSTTIME_ESTADO_NO_APLICA
    return _CATALOGO_POR_CLAVE.get(clave)


def estado_sugerido(valor):
    """Estado del catálogo sugerido para una variante antigua, o None."""
    return CONTRATO_JUSTTIME_MAP.get(_clave(valor))


def normalizar_columna_justtime(df):
    """Limpieza usada por la sincronización con RM_CONTRATOS: cada valor pasa a su
    estado del catálogo (sin distinguir mayúsculas) o al estado sugerido para
    su variante antigua. Vacío y valores desconocidos no se tocan. Devuelve
    (df, cantidad de celdas cambiadas)."""
    if COL_CONTRATO_JUSTTIME not in df.columns:
        return df, 0
    originales = df[COL_CONTRATO_JUSTTIME]

    def limpiar(valor):
        if _clave(valor) in ('', 'NAN', 'NONE'):
            return valor
        return estado_canonico(valor) or estado_sugerido(valor) or valor

    limpios = originales.map(limpiar)
    cambiados = int((limpios.astype(str) != originales.astype(str)).sum())
    df = df.copy()
    df[COL_CONTRATO_JUSTTIME] = limpios
    return df, cambiados


def va_a_justtime(tipo_facturacion):
    return _clave(tipo_facturacion) in TIPO_FACTURACION_HABILITA_JUSTTIME


def _esta_de_baja_o_desconectada(estado_comercial, estado_activacion):
    """Las unidades dadas de baja (o en solicitud de baja) o desconectadas
    no se marcan como inconsistentes (pedido del usuario, 02-10-2026)."""
    return _clave(estado_comercial) in ESTADOS_COMERCIALES_BAJA or _clave(estado_activacion) == "DESCONECTADO"


def _finalizado_sin_pendientes(estado_comercial, estado_activacion):
    """Contrato en Baja o Baja Solicitada cuya unidad ya no está Conectada ni Activando."""
    return _clave(estado_comercial) in ESTADOS_COMERCIALES_BAJA and _clave(estado_activacion) not in ("CONECTADO", "ACTIVANDO")


def _inconsistencia(tipo_facturacion, estado):
    """Regla confirmada por la contraparte comercial (05-10-2026): solo CLIENTE e INTERNO van
    a JustTime; FACTURACIÓN MANUAL y PROVISION + no."""
    if estado == POR_CORREGIR:
        return "Estado escrito con un formato antiguo"
    en_justtime = va_a_justtime(tipo_facturacion)
    if en_justtime and estado == JUSTTIME_ESTADO_NO_APLICA:
        return "Su tipo de facturación va a JustTime y no tiene estado"
    if not en_justtime and estado in (JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_PENDIENTE):
        return "Su tipo de facturación no va a JustTime"
    return ""


def _inconsistencia_contrato(tipo_facturacion, estado, estado_comercial, estado_activacion):
    """Un contrato finalizado sin pendientes solo se marca si sigue como Si o
    Pendiente en JustTime (falta eliminarlo); el resto de reglas no le aplican."""
    if _finalizado_sin_pendientes(estado_comercial, estado_activacion):
        if estado in (JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_PENDIENTE):
            return "Contrato finalizado: falta eliminarlo en JustTime"
        return ""
    if _esta_de_baja_o_desconectada(estado_comercial, estado_activacion):
        return ""
    return _inconsistencia(tipo_facturacion, estado)


def preparar_base_justtime(df_master):
    """Universo de la pantalla: unidades cuyo tipo de facturación va a
    JustTime o que tienen algún estado distinto de "-". Agrega las columnas
    calculadas COL_ESTADO_JT, COL_SUGERENCIA y COL_INCONSISTENCIA."""
    from src.services.comercial_services import contratos_actuales
    df_master = contratos_actuales(df_master)
    cols_disp = [c for c in COLUMNAS_BASE if c in df_master.columns]
    df = df_master[cols_disp].copy()
    for col in COLUMNAS_BASE:
        if col not in df.columns:
            df[col] = ""
    df[COLUMNAS_BASE] = df[COLUMNAS_BASE].fillna("").astype(str)

    canonicos = df[COL_CONTRATO_JUSTTIME].map(estado_canonico)
    df[COL_ESTADO_JT] = canonicos.fillna(POR_CORREGIR)
    df[COL_SUGERENCIA] = df[COL_CONTRATO_JUSTTIME].map(estado_sugerido).where(canonicos.isna(), "").fillna("")
    df[COL_INCONSISTENCIA] = [
        _inconsistencia_contrato(tipo, estado, com, act)
        for tipo, estado, com, act in zip(
            df[COL_TIPO_FACTURACION], df[COL_ESTADO_JT], df[COL_ESTADO_COMERCIAL], df[COL_ESTADO_ACTIVACION]
        )
    ]

    # Un contrato finalizado sin pendientes y sin estado JustTime no tiene nada que revisar
    finalizado_sin_estado = [
        _finalizado_sin_pendientes(com, act) and estado == JUSTTIME_ESTADO_NO_APLICA
        for com, act, estado in zip(df[COL_ESTADO_COMERCIAL], df[COL_ESTADO_ACTIVACION], df[COL_ESTADO_JT])
    ]
    en_universo = (df[COL_TIPO_FACTURACION].map(va_a_justtime) | (df[COL_ESTADO_JT] != JUSTTIME_ESTADO_NO_APLICA)) \
        & ~pd.Series(finalizado_sin_estado, index=df.index)
    return df[en_universo].reset_index(drop=True)


FILTRO_TODOS = "todos"
FILTRO_POR_CORREGIR = "por_corregir"
FILTRO_INCONSISTENCIAS = "inconsistencias"
FILTRO_CON_ESTADO = "con_estado"  # todo menos las unidades con "-"
FILTRO_DEBERIAN_ESTAR = "deberian_estar"  # su tipo de facturación va a JustTime
FILTRO_JT_INTERNO = "jt_interno"  # TIPO DE FACTURACION = INTERNO
FILTRO_JT_CLIENTE = "jt_cliente"  # TIPO DE FACTURACION = CLIENTE

_TIPO_POR_FILTRO = {FILTRO_JT_INTERNO: VALOR_TIPO_FACT_INTERNO, FILTRO_JT_CLIENTE: VALOR_TIPO_FACT_CLIENTE}


def filtrar(df_base, filtro):
    """`filtro`: FILTRO_TODOS, FILTRO_INCONSISTENCIAS, FILTRO_POR_CORREGIR o
    un estado de JUSTTIME_ESTADO_OPCIONES."""
    if df_base.empty or filtro in (None, FILTRO_TODOS):
        return df_base.copy()
    if filtro == FILTRO_INCONSISTENCIAS:
        return df_base[df_base[COL_INCONSISTENCIA] != ""].copy()
    if filtro == FILTRO_DEBERIAN_ESTAR:
        return df_base[df_base[COL_TIPO_FACTURACION].map(va_a_justtime)].copy()
    if filtro in _TIPO_POR_FILTRO:
        return df_base[df_base[COL_TIPO_FACTURACION].map(_clave) == _clave(_TIPO_POR_FILTRO[filtro])].copy()
    if filtro == FILTRO_CON_ESTADO:
        return df_base[df_base[COL_ESTADO_JT] != JUSTTIME_ESTADO_NO_APLICA].copy()
    if filtro == FILTRO_POR_CORREGIR:
        return df_base[df_base[COL_ESTADO_JT] == POR_CORREGIR].copy()
    return df_base[df_base[COL_ESTADO_JT] == filtro].copy()


def buscar(df, texto):
    """Mismo criterio que Contratos: cada término busca en VIN, CHASIS,
    RAZÓN SOCIAL y RUT."""
    texto = (texto or "").strip().lower()
    if not texto or df.empty:
        return df
    cols = [c for c in (COL_VIN, COL_CHASIS, COL_RAZON_SOCIAL, COL_RUT) if c in df.columns]
    from src.services import comercial_services
    mask = comercial_services.construir_mascara_busqueda(df, texto, cols, (COL_ID,))
    return df[mask]


def calcular_kpis(df_base):
    kpis = {estado: 0 for estado in JUSTTIME_ESTADO_OPCIONES}
    kpis[FILTRO_POR_CORREGIR] = 0
    kpis[FILTRO_INCONSISTENCIAS] = 0
    kpis[FILTRO_TODOS] = len(df_base)
    kpis[FILTRO_CON_ESTADO] = 0
    kpis[FILTRO_DEBERIAN_ESTAR] = 0
    kpis[FILTRO_JT_INTERNO] = 0
    kpis[FILTRO_JT_CLIENTE] = 0
    if df_base.empty:
        return kpis
    kpis[FILTRO_DEBERIAN_ESTAR] = int(df_base[COL_TIPO_FACTURACION].map(va_a_justtime).sum())
    claves_tipo = df_base[COL_TIPO_FACTURACION].map(_clave)
    for filtro, tipo in _TIPO_POR_FILTRO.items():
        kpis[filtro] = int((claves_tipo == _clave(tipo)).sum())
    kpis[FILTRO_CON_ESTADO] = int((df_base[COL_ESTADO_JT] != JUSTTIME_ESTADO_NO_APLICA).sum())
    for estado, cantidad in df_base[COL_ESTADO_JT].value_counts().items():
        if estado == POR_CORREGIR:
            kpis[FILTRO_POR_CORREGIR] = int(cantidad)
        elif estado in kpis:
            kpis[estado] = int(cantidad)
    kpis[FILTRO_INCONSISTENCIAS] = int((df_base[COL_INCONSISTENCIA] != "").sum())
    return kpis


def obtener_empresas(df):
    """Una fila por RAZÓN SOCIAL con cantidad de unidades y cuántas tienen
    alguna inconsistencia, ordenadas por las que requieren atención."""
    if df.empty:
        return pd.DataFrame(columns=[COL_RAZON_SOCIAL, COL_RUT, "UNIDADES", "ATENCION"])
    agrupado = df.assign(_ATENCION=(df[COL_INCONSISTENCIA] != "").astype(int)).groupby(
        COL_RAZON_SOCIAL, dropna=False
    ).agg(**{
        COL_RUT: (COL_RUT, 'first'),
        "UNIDADES": (COL_VIN, 'count'),
        "ATENCION": ('_ATENCION', 'sum'),
    }).reset_index()
    return agrupado.sort_values(["ATENCION", "UNIDADES", COL_RAZON_SOCIAL], ascending=[False, False, True])


def construir_cambios_estado(vins, estado):
    """Lote para SaveExcelThread: {vin: {'VIN': vin, 'cambios': {...}}}."""
    if estado not in JUSTTIME_ESTADO_OPCIONES:
        raise ValueError(f"Estado JustTime no válido: {estado}")
    return {
        str(vin).strip().upper(): {'VIN': str(vin).strip().upper(), 'cambios': {COL_CONTRATO_JUSTTIME: estado}}
        for vin in vins if str(vin).strip()
    }


def estado_segun_matriz(inconsistencia, estado, sugerencia=""):
    """Estado JustTime que deja la unidad coherente con la matriz (qué
    tipos de facturación van a JustTime), o None si no hay corrección.
    Una unidad que no debe estar en JustTime pasa a "Eliminar" si ya está
    creada (Si) y a "-" si nunca se creó (Pendiente)."""
    if not inconsistencia:
        return None
    if inconsistencia.startswith("Estado escrito"):
        return sugerencia or None
    if inconsistencia.startswith("Su tipo de facturación va a JustTime"):
        return JUSTTIME_ESTADO_PENDIENTE
    if estado == JUSTTIME_ESTADO_SI:
        return JUSTTIME_ESTADO_ELIMINAR
    if estado == JUSTTIME_ESTADO_PENDIENTE:
        return JUSTTIME_ESTADO_NO_APLICA
    return None


def construir_cambios_matriz(df):
    """Lote que corrige cada unidad inconsistente de `df` según la matriz
    (ver estado_segun_matriz). Las unidades sin corrección posible se omiten."""
    lote = {}
    for vin, inconsistencia, estado, sugerencia in zip(
            df[COL_VIN], df[COL_INCONSISTENCIA], df[COL_ESTADO_JT], df[COL_SUGERENCIA]):
        nuevo = estado_segun_matriz(inconsistencia, estado, sugerencia)
        clave = str(vin).strip().upper()
        if nuevo and clave:
            lote[clave] = {'VIN': clave, 'cambios': {COL_CONTRATO_JUSTTIME: nuevo}}
    return lote


def _tiene_fecha(valor):
    return _clave(valor) not in ('', '-', 'NAN', 'NONE', 'NAT')


def construir_cambios_limpieza(df):
    """Lote que deja en "-" los tres datos de JustTime (estado, inicio y
    término) de las unidades cuyo tipo de facturación no va a JustTime y que
    ya salieron de JustTime (estado "Eliminar") o solo conservan fechas
    sueltas. Las que siguen en JustTime (Si, Pendiente, Revisar pago) no se
    tocan: primero hay que sacarlas."""
    lote = {}
    for vin, tipo, estado, inicio, termino in zip(
            df[COL_VIN], df[COL_TIPO_FACTURACION], df[COL_ESTADO_JT], df[COL_FECHA_INICIO_FACT], df[COL_FECHA_TERMINO_FACT]):
        clave = str(vin).strip().upper()
        if not clave or va_a_justtime(tipo):
            continue
        fechas = _tiene_fecha(inicio) or _tiene_fecha(termino)
        if estado == JUSTTIME_ESTADO_ELIMINAR or (estado == JUSTTIME_ESTADO_NO_APLICA and fechas):
            lote[clave] = {'VIN': clave, 'cambios': {
                COL_CONTRATO_JUSTTIME: JUSTTIME_ESTADO_NO_APLICA,
                COL_FECHA_INICIO_FACT: JUSTTIME_ESTADO_NO_APLICA,
                COL_FECHA_TERMINO_FACT: JUSTTIME_ESTADO_NO_APLICA,
            }}
    return lote


def construir_cambios_sugeridos(df):
    """Lote que aplica el estado sugerido a cada unidad "Por corregir" de
    `df` que tenga sugerencia."""
    con_sugerencia = df[(df[COL_ESTADO_JT] == POR_CORREGIR) & (df[COL_SUGERENCIA] != "")]
    return {
        str(vin).strip().upper(): {'VIN': str(vin).strip().upper(), 'cambios': {COL_CONTRATO_JUSTTIME: sugerencia}}
        for vin, sugerencia in zip(con_sugerencia[COL_VIN], con_sugerencia[COL_SUGERENCIA])
    }
