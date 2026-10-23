"""Logica de negocio de Comercial extraida de src/ui/comercial.py (ver
auditoria previa). Python/pandas puro: no depende de PyQt6, QThread,
QWidget, QMessageBox ni ningun widget."""

import re
from datetime import datetime

import numpy as np
import pandas as pd

from src.core.constants import (COL_ETAPA_GESTION, COL_ESTADO_ACTIVACION, ESTADO_DESCONECTADO, ESTADO_CONECTADO,
                                ESTADO_ACTIVANDO,
                                COL_ESTADO_COMERCIAL, COL_TIPO_FACTURACION, COL_FORMA_CONTRATO,
                                VALOR_TIPO_FACT_SIN_REGISTRO, VALOR_TIPO_FACT_FACTURACION_MANUAL,
                                ESTADO_COMERCIAL_ACTIVACION_ETAPA_FLAT,
                                VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA,
                                VALOR_ESTADO_COMERCIAL_VENCIDO, VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE,
                                VALOR_ESTADO_COMERCIAL_REVISAR, VALOR_ESTADO_COMERCIAL_VIGENTE,
                                COL_RUT, COL_CDB, COL_RAZON_SOCIAL, COL_PERIODO_INTERNO,
                                FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ)
from src.core.dataframe_formatter import DataFrameFormatter
from src.services.cm_bajas_service import ORIGEN_CASO_AUSENCIA_3PC, ORIGEN_CASO_ESTADO_EXPIRED

# Caché de DataFrameFormatter.parsear_fecha_segura por valor (depende solo
# del valor): clasificar_vigencia_contrato se llama varias veces por
# refresco sobre los mismos datos. La clave incluye el tipo para no mezclar
# valores que Python considera iguales (1, 1.0, True).
_CACHE_FECHAS_PARSEADAS = {}
_MAX_CACHE_FECHAS_PARSEADAS = 50000


def _parsear_fecha_cacheada(valor):
    try:
        clave = (type(valor), valor)
        return _CACHE_FECHAS_PARSEADAS[clave]
    except KeyError:
        pass
    except TypeError:
        return DataFrameFormatter.parsear_fecha_segura(valor)
    resultado = DataFrameFormatter.parsear_fecha_segura(valor)
    if len(_CACHE_FECHAS_PARSEADAS) >= _MAX_CACHE_FECHAS_PARSEADAS:
        _CACHE_FECHAS_PARSEADAS.clear()
    _CACHE_FECHAS_PARSEADAS[clave] = resultado
    return resultado


def aplicar_por_valor_unico(serie, funcion):
    """Mismo resultado que serie.apply(funcion) para una función pura, pero
    evaluándola una vez por valor distinto (CDB, duración, flotas y estados
    se repiten mucho). Solo en columnas de texto: con tipos mezclados,
    pd.factorize junta 1, 1.0 y True y el resultado podría cambiar."""
    if pd.api.types.infer_dtype(serie, skipna=True) not in ('string', 'empty'):
        return serie.apply(funcion)
    codigos, unicos = pd.factorize(serie, use_na_sentinel=True)
    resultados = [funcion(v) for v in unicos]
    vacios = codigos == -1
    if vacios.any():
        resultados.append(funcion(serie[vacios].iloc[0]))
        codigos = np.where(vacios, len(resultados) - 1, codigos)
    valores = np.empty(len(resultados), dtype=object)
    valores[:] = resultados
    return pd.Series(valores[codigos], index=serie.index, name=serie.name)


def procesar_df_comercial(df):
    """Extraccion literal de ComercialModule._procesar_df_base(): limpia CDB
    (quita sufijo '.0'), normaliza DURACION (MESES), fuerza TERMINO CONTRATO
    a 'MENSUAL' cuando la duracion es '-'/'MENSUAL', calcula PAGO CM_NUM y
    agrega la columna 'N°' vacia al inicio."""
    if df.empty:
        return df

    def clean_cdb(val):
        if pd.isna(val): return ""
        v_str = str(val).strip()
        if v_str.lower() in ['nan', 'none', '<na>', '']: return ""
        if v_str.endswith('.0'): return v_str[:-2]
        return v_str
    for col_cdb in ('CDB', 'CDB FLOTA'):
        if col_cdb in df.columns:
            df[col_cdb] = aplicar_por_valor_unico(df[col_cdb], clean_cdb)

    if 'DURACIÓN (MESES)' in df.columns:
        def clean_duracion_ui(val):
            if pd.isna(val) or str(val).strip() in ['', 'nan', 'NaN', '<NA>', 'None']: return ""
            val_str = str(val).strip().upper()
            if val_str in ['-', 'MENSUAL']: return val_str
            try: return str(int(round(float(val))))
            except (ValueError, TypeError): return val_str

        df['DURACIÓN (MESES)'] = aplicar_por_valor_unico(df['DURACIÓN (MESES)'], clean_duracion_ui)

    if 'TÉRMINO CONTRATO' in df.columns:
        # 'MENSUAL' en DURACIÓN (MESES) siempre fuerza TÉRMINO CONTRATO='MENSUAL'.
        # '-' en DURACIÓN (MESES) tambien lo fuerza, SALVO que TÉRMINO CONTRATO ya
        # sea '-' explicito: ese combo significa que el dato aun no fue informado
        # (ver DataFrameFormatter.calcular_termino, misma regla), no que sea mensual.
        termino_actual = df['TÉRMINO CONTRATO'].astype(str).str.strip().str.upper()
        mask_mensual_texto = df['DURACIÓN (MESES)'] == 'MENSUAL'
        mask_guion_informado = (df['DURACIÓN (MESES)'] == '-') & (termino_actual != '-')
        mask_mensual_fix = mask_mensual_texto | mask_guion_informado
        df.loc[mask_mensual_fix, 'TÉRMINO CONTRATO'] = 'MENSUAL'

    if 'PAGO CM' in df.columns:
        df['PAGO CM_NUM'] = pd.to_numeric(df['PAGO CM'], errors='coerce').fillna(0)
    else:
        df['PAGO CM_NUM'] = 0

    df.insert(0, 'N°', "")
    return df


def _normalizar_id_contrato(valor):
    """ID de contrato como texto entero ('115'); '' si viene vacío o inválido."""
    if valor is None or pd.isna(valor):
        return ''
    texto = str(valor).strip()
    if texto.lower() in ('nan', 'none', '-', '<na>'):
        return ''
    return texto[:-2] if texto.endswith('.0') else texto


def _ids_normalizados(df):
    return df['ID'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)


def agregar_id_a_cambios(cambios, df_base):
    """Agrega el ID del contrato actual de cada VIN a los cambios
    ({vin: {'VIN': ..., 'cambios': ...}}) para que el escritor y la memoria
    ubiquen ese contrato y no otro con el mismo VIN. Sin columna ID en
    `df_base` no toca nada. Muta y devuelve `cambios`."""
    if df_base is None or df_base.empty or 'ID' not in df_base.columns or 'VIN' not in df_base.columns:
        return cambios
    ids = pd.Series(_ids_normalizados(df_base).to_numpy(),
                    index=df_base['VIN'].astype(str).str.strip().str.upper().to_numpy())
    ids = ids[~ids.index.duplicated(keep='last')]
    for vin_key, data in cambios.items():
        id_contrato = _normalizar_id_contrato(ids.get(str(vin_key).strip().upper()))
        if id_contrato:
            data['ID'] = id_contrato
    return cambios


def contratos_actuales(df):
    """Una fila por VIN: el contrato actual, que es el de mayor ID (el último
    creado). Los demás contratos del mismo VIN son historial y no entran a las
    bandejas. Sin columna ID, o con VIN únicos, devuelve `df` tal cual; entre
    filas sin ID de un mismo VIN gana la última del archivo."""
    if df is None or df.empty or 'VIN' not in df.columns:
        return df
    vin = df['VIN'].astype(str).str.strip().str.upper()
    if not vin.duplicated().any():
        return df
    if 'ID' in df.columns:
        orden = pd.to_numeric(df['ID'], errors='coerce').fillna(-1).to_numpy()
    else:
        orden = np.full(len(df), -1.0)
    ranking = pd.DataFrame({'vin': vin.to_numpy(), 'orden': orden, 'pos': np.arange(len(df))})
    conservar = ranking.sort_values(['orden', 'pos']).drop_duplicates('vin', keep='last')['pos'].to_numpy()
    mascara = np.zeros(len(df), dtype=bool)
    mascara[conservar] = True
    return df[mascara]


def contratos_anteriores(df, vin):
    """Contratos de `vin` que no son el actual, del más reciente al más antiguo
    (mismo criterio de orden que `contratos_actuales`). Vacío si el VIN tiene
    un solo contrato o `df` no trae VIN."""
    if df is None or df.empty or 'VIN' not in df.columns:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    filas = df[df['VIN'].astype(str).str.strip().str.upper() == str(vin).strip().upper()]
    if len(filas) < 2:
        return filas.iloc[0:0]
    if 'ID' in filas.columns:
        orden = pd.to_numeric(filas['ID'], errors='coerce').fillna(-1).to_numpy()
    else:
        orden = np.full(len(filas), -1.0)
    ranking = pd.DataFrame({'orden': orden, 'pos': np.arange(len(filas))}).sort_values(['orden', 'pos'], ascending=False)
    return filas.iloc[ranking['pos'].to_numpy()[1:]]


def es_contrato_cerrado(estado_comercial):
    """Un contrato en Baja o Baja Solicitada está finalizado: solo lectura."""
    return str(estado_comercial).strip().upper() in {VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA}


def proximo_id_contrato(df):
    """ID del contrato siguiente (máximo + 1) como texto; '' si `df` no tiene ID."""
    if df is None or 'ID' not in df.columns:
        return ''
    ids = pd.to_numeric(_ids_normalizados(df), errors='coerce')
    return str(int(ids.max()) + 1) if ids.notna().any() else '1'


def puede_crear_contrato(estado_comercial, estado_activacion):
    """Matriz de nuevo contrato sobre un mismo VIN: solo si el contrato actual
    está en Baja o Baja Solicitada y la unidad no sigue Activando ni Conectada
    (Desconectado, No aplica, No entregado y Sin flota sí admiten). También
    admite Revisar con No aplica, el caso de las unidades "SIN VC"."""
    activacion = str(estado_activacion).strip().upper()
    if str(estado_comercial).strip().upper() == VALOR_ESTADO_COMERCIAL_REVISAR:
        return activacion == 'NO APLICA'
    return es_contrato_cerrado(estado_comercial) and activacion not in {ESTADO_ACTIVANDO, ESTADO_CONECTADO}


def excluir_contratos_finalizados_inactivos(df):
    """Quita los contratos en Baja o Baja Solicitada que ya no tienen nada
    pendiente (unidad que no está Activando ni Conectada). Los finalizados que
    siguen conectados se conservan: Operaciones debe desconectarlos."""
    if df is None or df.empty or COL_ESTADO_COMERCIAL not in df.columns:
        return df
    if COL_ESTADO_ACTIVACION in df.columns:
        activacion = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    else:
        activacion = pd.Series('', index=df.index)
    cerrado = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper().isin(
        {VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA})
    inactivo = ~activacion.isin({ESTADO_ACTIVANDO, ESTADO_CONECTADO})
    return df[~(cerrado & inactivo)]


def excluir_contratos_cerrados(df):
    """Quita todos los contratos en Baja o Baja Solicitada, estén o no
    conectados todavía."""
    if df is None or df.empty or COL_ESTADO_COMERCIAL not in df.columns:
        return df
    return df[~df[COL_ESTADO_COMERCIAL].map(es_contrato_cerrado)]


def vins_con_contrato_abierto(df):
    """VIN (mayúsculas) cuyo contrato actual no permite crear otro (ver
    puede_crear_contrato)."""
    if df is None or df.empty or 'VIN' not in df.columns or 'ESTADO COMERCIAL' not in df.columns:
        return set()
    actuales = contratos_actuales(df)
    if COL_ESTADO_ACTIVACION in actuales.columns:
        activacion = actuales[COL_ESTADO_ACTIVACION]
    else:
        activacion = pd.Series('', index=actuales.index)
    puede = [puede_crear_contrato(e, a) for e, a in zip(actuales['ESTADO COMERCIAL'], activacion)]
    vins = actuales.loc[~np.array(puede, dtype=bool), 'VIN'].astype(str).str.strip().str.upper()
    return set(vins) - {''}


def puede_renovar_con_nuevo_contrato(estado_comercial, estado_activacion=''):
    """Un contrato Vigente o Vencido se puede reemplazar por uno nuevo; también una unidad
    en Revisar que ya está Conectada (todavía sin contrato)."""
    estado = str(estado_comercial).strip().upper()
    if estado == VALOR_ESTADO_COMERCIAL_REVISAR:
        return str(estado_activacion).strip().upper() == ESTADO_CONECTADO
    return estado in {VALOR_ESTADO_COMERCIAL_VIGENTE, VALOR_ESTADO_COMERCIAL_VENCIDO}


def cambios_contrato_renovado(fila):
    """Cambios del contrato anterior cuando lo reemplaza uno nuevo: queda en
    estado Renovado (historial) y, si estaba en JustTime como Si o Pendiente,
    pasa a Eliminar porque el contrato nuevo ocupa su lugar."""
    cambios = {COL_ESTADO_COMERCIAL: 'Renovado'}
    estado_jt = str(fila.get('CONTRATO CREADO EN JUSTTIME', '')).strip().upper()
    if estado_jt in {'SI', 'PENDIENTE'}:
        cambios['CONTRATO CREADO EN JUSTTIME'] = 'Eliminar'
    return cambios


_CAMPOS_PROPIOS_RENOVACION = (
    'RUT', 'RAZÓN SOCIAL', 'INDUSTRIA', 'VIN', 'CHASIS', 'MODELO', 'CDB', 'EJECUTIVO', 'FLOTA VC', 'FLOTA VC 2',
    'CDB FLOTA', 'ESTADO DE ACTIVACIÓN ACTUAL', 'ESTADO DE ENTREGA', 'PERIODO INTERNO')


def armar_renovaciones_multiples(data, datos_por_vin, prototipo, id_inicial):
    """Contratos nuevos de una renovación de varias unidades. `data` es lo que devolvió el
    formulario (cargado con la primera unidad, `prototipo`); `datos_por_vin` es {vin: datos
    del contrato actual}. Cada contrato nuevo toma de su unidad lo propio (cliente, VIN, flota,
    activación, periodo) y del formulario las condiciones comerciales, JustTime y CM; el tipo de
    servicio solo se aplica a todas si se cambió respecto de la primera unidad. Devuelve una
    lista de {'vin', 'id_anterior', 'cambios_anterior', 'nuevo'} con IDs consecutivos."""
    resultado = []
    siguiente = int(id_inicial) if str(id_inicial).strip().isdigit() else None
    for vin, datos in datos_por_vin.items():
        nuevo = dict(data)
        for campo in _CAMPOS_PROPIOS_RENOVACION:
            valor = datos.get(campo)
            if valor is not None and str(valor).strip() not in ('', 'nan', 'NaN', 'None'):
                nuevo[campo] = str(valor).strip()
        if str(data.get('TIPO DE SERVICIO', '')).strip() == str(prototipo.get('TIPO DE SERVICIO', '')).strip():
            propio = str(datos.get('TIPO DE SERVICIO', '')).strip()
            if propio and propio.lower() != 'nan':
                nuevo['TIPO DE SERVICIO'] = propio
        nuevo[COL_ETAPA_GESTION] = DataFrameFormatter.calcular_etapa_gestion_esperada(pd.Series(nuevo))
        if siguiente is not None:
            nuevo['ID'] = str(siguiente)
            siguiente += 1
        resultado.append({
            'vin': vin, 'id_anterior': str(datos.get('ID', '')).strip(),
            'cambios_anterior': cambios_contrato_renovado(datos), 'nuevo': nuevo})
    return resultado


def calcular_renovacion(fila, meses_extra, nuevo_inicio=None):
    """Cambios de una renovación: suma `meses_extra` a DURACIÓN (MESES) y
    recalcula TÉRMINO CONTRATO desde el inicio; el contrato conserva su ID. Con
    `nuevo_inicio` (fecha) el inicio también cambia a ese día. Un contrato
    Vencido vuelve a Vigente. Devuelve None si la fila no es renovable (estado
    distinto de Vigente/Vencido, duración no numérica como MENSUAL o '-', o sin
    fecha de inicio válida cuando no se da `nuevo_inicio`)."""
    estado = str(fila.get(COL_ESTADO_COMERCIAL, '')).strip().upper()
    if estado not in {VALOR_ESTADO_COMERCIAL_VIGENTE, VALOR_ESTADO_COMERCIAL_VENCIDO} or meses_extra < 1:
        return None
    try:
        duracion = int(float(str(fila.get('DURACIÓN (MESES)', '')).strip().replace(',', '.')))
    except ValueError:
        return None
    inicio = pd.Timestamp(nuevo_inicio) if nuevo_inicio is not None else DataFrameFormatter.parsear_fecha_segura(fila.get('INICIO CONTRATO'))
    if pd.isna(inicio):
        return None
    nueva_duracion = duracion + int(meses_extra)
    cambios = {
        'DURACIÓN (MESES)': str(nueva_duracion),
        'TÉRMINO CONTRATO': (inicio + pd.DateOffset(months=nueva_duracion)).strftime("%d-%m-%Y"),
    }
    if nuevo_inicio is not None:
        cambios['INICIO CONTRATO'] = inicio.strftime("%d-%m-%Y")
    if estado == VALOR_ESTADO_COMERCIAL_VENCIDO:
        cambios[COL_ESTADO_COMERCIAL] = VALOR_ESTADO_COMERCIAL_VIGENTE
    return cambios


def preparar_df_base_comercial(df):
    """df_base de Comercial: datos preparados y solo el contrato actual de cada VIN."""
    return contratos_actuales(procesar_df_comercial(df))


def clasificar_vigencia_contrato(df, dias_alerta=30, hoy=None):
    """Clasifica cada fila de `df` según TÉRMINO CONTRATO. Fuente centralizada
    de vigencia: reemplaza los calculos duplicados que antes vivian por
    separado en calcular_kpis_vigencia() y en ComercialModule.filter_table().

    IMPORTANTE (regla de negocio confirmada con Javiera): esta funcion usa
    exclusivamente TÉRMINO CONTRATO (termino del contrato pagado por el
    cliente) y dias CALENDARIO. Nunca debe usarse FECHA TERMINO CM (termino
    del contrato CM) para esta clasificacion -- son conceptos de fecha
    distintos y no intercambiables; FECHA TERMINO CM se maneja aparte, dentro
    de la logica especifica de CM (contratos.py).

    Devuelve un DataFrame con el mismo indice que `df` y columnas:
      - es_mensual: bool — TÉRMINO CONTRATO == 'MENSUAL' (case-insensitive)
      - fecha_valida: bool — el valor parsea a una fecha real (False para
        vacio, '-', 'nan', o cualquier texto no-fecha; 'MENSUAL' tampoco
        parsea como fecha, por eso es_mensual es una columna aparte)
      - vencido: bool — fecha_valida & (fecha < hoy), comparacion de
        CALENDARIO pura (fecha ya pasada).
      - dias_restantes: float (NaN si no fecha_valida) — diferencia en DIAS
        CALENDARIO entre la fecha y hoy ((fecha - hoy).dias): >= 0 si la
        fecha es hoy o futura, < 0 si ya paso. No usa dias habiles: una
        fecha que cae sabado o domingo cuenta exactamente igual que
        cualquier otro dia.
      - activo: bool — es_mensual | (fecha_valida & ~vencido)
      - por_vencer: bool — fecha_valida & ~vencido & (dias_restantes <=
        dias_alerta). El `~vencido` es obligatorio para mantener este KPI
        historico (x-vencer) excluyente de "vencidas".
      - es_renovacion: bool — vencido | por_vencer. Union de ambos: un
        contrato pertenece a Renovaciones si YA vencio O si vence dentro de
        los proximos `dias_alerta` dias calendario (borde inclusive: vence
        exactamente en 30 dias SI cuenta, en 31 dias NO). A diferencia de
        vencido/por_vencer (que se mantienen separados para los KPI
        historicos de Vista Completa), esta es la condicion que debe usar
        cualquier vista/bandeja de "Renovaciones".

    Filas con fecha invalida (vacia, '-', texto no parseable) y no
    mensuales quedan con fecha_valida=False y
    vencido=activo=por_vencer=es_renovacion=False (se cuentan en 'total'
    pero en ningun otro KPI), igual que el comportamiento anterior.
    """
    if hoy is None:
        hoy = pd.Timestamp(datetime.now().date())

    raw = df['TÉRMINO CONTRATO'].astype(str)
    es_mensual = raw.str.strip().str.upper() == 'MENSUAL'
    # DataFrameFormatter.parsear_fecha_segura (25-09-2026, corrección de bug
    # real: pd.to_datetime(dayfirst=True) directo sobre TÉRMINO CONTRATO
    # intercambiaba día/mes en fechas ISO con hora como "2026-02-12
    # 04:00:00" -- ver el mismo bug ya corregido antes en
    # DataFrameFormatter.clean() para INICIO CONTRATO/TÉRMINO CONTRATO
    # calculado). Se aplica elemento por elemento (no vectorizable) porque
    # decide el formato de cada valor según su forma real, no una sola regla
    # global para toda la columna.
    # pd.to_datetime() envolviendo el .apply() (en vez de encadenar .dt
    # directo): con `df` vacío, .apply() sobre una Series vacía devuelve
    # dtype 'object' (no datetime64), y encadenar .dt ahí revienta con
    # AttributeError -- bug real detectado 28-09-2026 al endurecer
    # filtrar_renovaciones() (ahora puede llegar aquí con una bandeja
    # legítimamente vacía). pd.to_datetime() normaliza el dtype tanto para
    # el caso vacío como para el caso normal, sin cambiar ningún valor ya
    # parseado por parsear_fecha_segura.
    fechas = pd.to_datetime(df['TÉRMINO CONTRATO'].apply(_parsear_fecha_cacheada)).dt.normalize()
    fecha_valida = fechas.notna()

    vencido = fecha_valida & (fechas < hoy)
    activo = es_mensual | (fecha_valida & ~vencido)

    dias_restantes = pd.Series(np.nan, index=df.index)
    if fecha_valida.any():
        dias_restantes[fecha_valida] = (fechas[fecha_valida] - hoy).dt.days

    por_vencer = fecha_valida & ~vencido & (dias_restantes <= dias_alerta)
    es_renovacion = vencido | por_vencer

    return pd.DataFrame({
        'es_mensual': es_mensual,
        'fecha_valida': fecha_valida,
        'vencido': vencido,
        'activo': activo,
        'dias_restantes': dias_restantes,
        'por_vencer': por_vencer,
        'es_renovacion': es_renovacion,
    }, index=df.index)


def clasificar_fecha_termino(valor, dias_alerta=30, hoy=None):
    """Version de un solo valor de clasificar_vigencia_contrato(), para
    consumidores que no manejan un DataFrame completo (p. ej. el color de
    celda de PandasTableModel en custom_table.py). No reimplementa ninguna
    regla: arma un DataFrame de una fila y reusa clasificar_vigencia_contrato()
    para no terminar con una segunda fuente de verdad sobre vigencia.

    Devuelve un dict con las mismas claves que una fila de
    clasificar_vigencia_contrato(): es_mensual, fecha_valida, vencido,
    activo, dias_restantes, por_vencer, es_renovacion."""
    df_temp = pd.DataFrame({'TÉRMINO CONTRATO': [valor]})
    fila = clasificar_vigencia_contrato(df_temp, dias_alerta=dias_alerta, hoy=hoy).iloc[0]
    return fila.to_dict()


def formatear_dias_restantes(dias_restantes):
    """Texto legible para la columna calculada 'DÍAS RESTANTES' de la Nueva
    interfaz de Comercial (Vencimientos/Renovaciones), a partir del valor
    numerico que ya entrega clasificar_vigencia_contrato()['dias_restantes'].
    No recalcula fechas ni cambia el signo/valor: solo formatea.

    - NaN (fecha invalida o MENSUAL, ver clasificar_vigencia_contrato) -> '-'
    - > 0 -> 'N días restantes'
    - == 0 -> 'Vence hoy'
    - < 0 -> 'Vencido hace N días'
    """
    if pd.isna(dias_restantes):
        return "-"
    dias = int(dias_restantes)
    if dias > 0:
        return f"{dias} días restantes"
    if dias == 0:
        return "Vence hoy"
    return f"Vencido hace {abs(dias)} días"


_PATRON_DIAS_RESTANTES = re.compile(r'^vencido hace (\d+) d[ií]as?$', re.IGNORECASE)
_PATRON_DIAS_RESTANTES_FUTURO = re.compile(r'^(\d+) d[ií]as? restantes?$', re.IGNORECASE)


def parsear_dias_restantes(texto):
    """Inverso de formatear_dias_restantes(): recupera el numero de dias con
    signo a partir del texto ya formateado (usado por
    VolvoTableWidget._parse_number_like en custom_table.py para poder
    ordenar la columna 'DÍAS RESTANTES' por magnitud numerica en vez de
    alfabeticamente). Unica fuente de verdad sobre el patron de texto:
    custom_table.py no debe reimplementar estas expresiones regulares.
    Devuelve None si `texto` no calza con ningun patron conocido (p. ej. '-')."""
    s = str(texto).strip()
    if s.lower() == 'vence hoy':
        return 0.0
    m = _PATRON_DIAS_RESTANTES.match(s)
    if m:
        return -float(m.group(1))
    m = _PATRON_DIAS_RESTANTES_FUTURO.match(s)
    if m:
        return float(m.group(1))
    return None


def calcular_kpis_vigencia(df, dias_alerta=30):
    """Extraccion literal del bloque de conteo de KPIs duplicado en
    ComercialModule.load_data() y ComercialModule._on_save_finished():
    vencidas/activas/x-vencer se calculan contra TÉRMINO CONTRATO, tratando
    'MENSUAL' como siempre activo/nunca vencido. 'xvencer' usa
    dias_alerta dias CALENDARIO (no habiles), via
    clasificar_vigencia_contrato(); 'vencidas'/'activas' mantienen el mismo
    significado (comparacion de calendario) que antes."""
    clasif = clasificar_vigencia_contrato(df, dias_alerta=dias_alerta)

    return {
        "total": len(df),
        "vencidas": int(clasif['vencido'].sum()),
        "activas": int(clasif['activo'].sum()),
        "xvencer": int(clasif['por_vencer'].sum()),
    }


# =========================================================
# KPI POR SUB-PESTAÑA DE LA NUEVA INTERFAZ DE COMERCIAL (25-09-2026, a
# pedido explícito: las 4 tarjetas de vigencia de calcular_kpis_vigencia()
# se mostraban igual en las 6 sub-pestañas, sin relación con la regla de
# negocio real de cada una -- ver docs/07 §"Módulo Comercial" y la
# investigación previa en el chat). Cada función recibe la bandeja YA
# filtrada por _NEW_UI_SUBTAB_FILTERS (o _construir_df_revision_cm para
# "Gestionar CM") y devuelve únicamente las claves que esa sub-pestaña usa
# -- ver _NEW_UI_KPI_SPECS en comercial.py.
# =========================================================
def obtener_masks_kpi_por_gestionar(df, razones_contactadas=None):
    """Máscaras booleanas por fila detrás de calcular_kpis_por_gestionar,
    reutilizadas también para filtrar la tabla al hacer clic en una tarjeta
    KPI (ver _NEW_UI_KPI_MASK_FUNCS en comercial.py)."""
    if df.empty:
        return {}
    estado = df.get(COL_ESTADO_COMERCIAL, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    forma = df.get(COL_FORMA_CONTRATO, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    return {
        "revisar": estado == 'REVISAR',
        "sin_contrato": forma == 'SIN CONTRATO',
        **_masks_contacto(df, razones_contactadas),
    }


def calcular_kpis_por_gestionar(df, razones_contactadas=None):
    """"Por gestionar" (ESTADO DE ACTIVACIÓN ACTUAL = NO APLICA): desglose
    por ESTADO COMERCIAL en vez de vigencia de contrato (esta bandeja no se
    define por TÉRMINO CONTRATO)."""
    if df.empty:
        return {"clientes": 0, "revisar": 0, "sin_contrato": 0, "total": 0, "clientes_totales": 0,
                "contactados": 0, "sin_gestionar": 0, "_bases": {}}
    masks = obtener_masks_kpi_por_gestionar(df, razones_contactadas)
    kpis = _kpis_contacto(df, razones_contactadas)
    kpis.update({
        "clientes": kpis["clientes_totales"],
        "revisar": int(masks["revisar"].sum()),
        "sin_contrato": int(masks["sin_contrato"].sum()),
    })
    return kpis


def _mask_sin_contacto(df, df_contactos):
    """True para las filas cuyo CDB no tiene ningún contacto registrado en
    contactos.xlsx. Sin datos de contactos disponibles, no se marca ninguna
    fila como "sin contacto" (más seguro que asumir que todas lo están)."""
    if df_contactos is None or df_contactos.empty or 'CDB' not in df_contactos.columns or COL_CDB not in df.columns:
        return pd.Series(False, index=df.index)
    cdbs_con_contacto = set(df_contactos['CDB'].astype(str).str.strip())
    return ~df[COL_CDB].astype(str).str.strip().isin(cdbs_con_contacto)


def obtener_masks_kpi_renovaciones(df, df_contactos=None, dias_alerta=30):
    if df.empty:
        return {}
    clasif = clasificar_vigencia_contrato(df, dias_alerta=dias_alerta)
    urgentes = clasif['por_vencer'] & (clasif['dias_restantes'] <= 7)
    return {
        "sin_contactos": _mask_sin_contacto(df, df_contactos),
        "urgentes": urgentes,
    }


def calcular_kpis_renovaciones(df, dias_alerta=30, df_contactos=None):
    """"Renovaciones" (vencido o por vencer <=30 días): agrega "urgentes"
    (vencen en <=7 días) para priorizar, "sin_contactos" (CDB sin contacto
    registrado) y "clientes" (RAZÓN SOCIAL distintas)."""
    if df.empty:
        return {"sin_contactos": 0, "clientes": 0, "urgentes": 0, "total": 0}
    masks = obtener_masks_kpi_renovaciones(df, df_contactos=df_contactos, dias_alerta=dias_alerta)
    return {
        "sin_contactos": int(masks["sin_contactos"].sum()),
        "clientes": int(df.get(COL_RAZON_SOCIAL, pd.Series(dtype=str)).nunique()),
        "urgentes": int(masks["urgentes"].sum()),
        "total": len(df),
    }


# Un cliente cuenta como contactado si recibió algún correo (cualquier plantilla)
# registrado en Historial_Envios_VC.csv dentro de esta ventana.
DIAS_VENTANA_CONTACTO_CORREO = 14


def _normalizar_razon_social(valor):
    return " ".join(str(valor).upper().split())


def obtener_razones_contactadas_por_correo(df_historial, dias=DIAS_VENTANA_CONTACTO_CORREO, hoy=None):
    """Razones sociales (normalizadas) con al menos un correo registrado en los
    últimos `dias` días. Sin historial devuelve un conjunto vacío."""
    if df_historial is None or df_historial.empty or not {'razon_social', 'fecha_hora'} <= set(df_historial.columns):
        return set()
    hoy = pd.Timestamp(hoy) if hoy is not None else pd.Timestamp(datetime.now())
    fechas = pd.to_datetime(df_historial['fecha_hora'], errors='coerce')
    recientes = df_historial.loc[fechas >= hoy - pd.Timedelta(days=dias), 'razon_social']
    return {n for n in (_normalizar_razon_social(v) for v in recientes) if n and n != 'NAN'}


def _masks_contacto(df, razones_contactadas):
    razon = df.get(COL_RAZON_SOCIAL, pd.Series("", index=df.index)).map(_normalizar_razon_social)
    contactados = razon.isin(razones_contactadas or set())
    return {"contactados": contactados, "sin_gestionar": ~contactados}


def _kpis_contacto(df, razones_contactadas):
    """Unidades potenciales (total), clientes totales y cuántos de esos
    clientes ya recibieron un correo o siguen sin gestionar. `_bases` indica
    la base de porcentaje de las tarjetas que cuentan clientes."""
    masks = _masks_contacto(df, razones_contactadas)
    razon = df.get(COL_RAZON_SOCIAL, pd.Series("", index=df.index)).map(_normalizar_razon_social)
    clientes = int(razon.nunique())
    contactados = int(razon[masks["contactados"]].nunique())
    return {
        "total": len(df),
        "clientes_totales": clientes,
        "contactados": contactados,
        "sin_gestionar": clientes - contactados,
        "_bases": {"clientes_totales": clientes, "contactados": clientes, "sin_gestionar": clientes},
    }


def obtener_masks_kpi_gestionar_bajas(df, razones_contactadas=None):
    if df.empty:
        return {}
    estado_activ = df.get(COL_ESTADO_ACTIVACION, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    return {
        "conectadas": estado_activ == 'CONECTADO',
        "desconectadas": estado_activ == 'DESCONECTADO',
        **_masks_contacto(df, razones_contactadas),
    }


def calcular_kpis_gestionar_bajas(df, razones_contactadas=None):
    """"Recuperar clientes" (ESTADO COMERCIAL = BAJA): unidades potenciales,
    clientes totales y cuántos de esos clientes ya recibieron un correo
    (`razones_contactadas`) o siguen sin gestionar. `_bases` indica la base
    de porcentaje de las tarjetas que cuentan clientes en vez de unidades."""
    if df.empty:
        return {"total": 0, "clientes_totales": 0, "contactados": 0, "sin_gestionar": 0,
                "conectadas": 0, "desconectadas": 0, "clientes": 0, "_bases": {}}
    masks = obtener_masks_kpi_gestionar_bajas(df, razones_contactadas)
    kpis = _kpis_contacto(df, razones_contactadas)
    kpis.update({
        "conectadas": int(masks["conectadas"].sum()),
        "desconectadas": int(masks["desconectadas"].sum()),
        "clientes": kpis["clientes_totales"],
    })
    return kpis


def obtener_masks_kpi_gestionar_cm(df_casos, razones_contactadas=None):
    """Máscaras por fila detrás de las tarjetas clicables de "Oportunidades CM"
    (ver _NEW_UI_KPI_MASK_FUNCS en comercial.py)."""
    if df_casos.empty:
        return {}
    origen = df_casos.get('ORIGEN_CASO', pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    monto = pd.to_numeric(df_casos.get('PAGO CM', pd.Series(dtype=str)), errors='coerce').fillna(0)
    return {
        "ausencia_3pc": origen == ORIGEN_CASO_AUSENCIA_3PC,
        "expired": origen == ORIGEN_CASO_ESTADO_EXPIRED,
        "monto_riesgo": monto > 0,
        **_masks_contacto(df_casos, razones_contactadas),
    }


def calcular_kpis_gestionar_cm(df_casos, razones_contactadas=None):
    """"Gestionar CM": `df_casos` es la salida de
    ComercialModule._construir_df_revision_cm() (casos PENDIENTE de
    CasosBajaCM.csv, con la columna MOTIVO ya agregada) -- no sale de
    df_base, así que calcular_kpis_vigencia no aplica (no tiene TÉRMINO
    CONTRATO). Desglosa por ORIGEN_CASO (ver cm_bajas_service) y suma
    PAGO CM en riesgo."""
    if df_casos.empty:
        return {"total": 0, "ausencia_3pc": 0, "expired": 0, "monto_riesgo": "$-",
                "clientes_afectados": 0, "contactados": 0, "sin_gestionar": 0, "_bases": {}}
    origen = df_casos.get('ORIGEN_CASO', pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    monto = pd.to_numeric(df_casos.get('PAGO CM', pd.Series(dtype=str)), errors='coerce').fillna(0)
    kpis = _kpis_contacto(df_casos, razones_contactadas)
    clientes = kpis.pop("clientes_totales")
    kpis["_bases"] = {"clientes_afectados": clientes, "contactados": clientes, "sin_gestionar": clientes}
    kpis.update({
        "clientes_afectados": clientes,
        "ausencia_3pc": int((origen == ORIGEN_CASO_AUSENCIA_3PC).sum()),
        "expired": int((origen == ORIGEN_CASO_ESTADO_EXPIRED).sum()),
        "monto_riesgo": formatear_pago_cm(monto.sum()),
    })
    return kpis


def obtener_masks_kpi_vigentes(df):
    if df.empty:
        return {}
    estado_activ = df.get(COL_ESTADO_ACTIVACION, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    return {
        "desconectadas": estado_activ == 'DESCONECTADO',
        "activando": estado_activ == 'ACTIVANDO',
        "conectadas": estado_activ == 'CONECTADO',
    }


def calcular_kpis_vigentes(df):
    """"Vigentes" (ESTADO COMERCIAL = VIGENTE): el propósito de esta
    bandeja es confirmar que la unidad ya llegó a Conectado -- "activando"
    (Operaciones todavía se está encargando) es el caso accionable."""
    if df.empty:
        return {"total": 0, "conectadas": 0, "activando": 0, "desconectadas": 0}
    masks = obtener_masks_kpi_vigentes(df)
    return {
        "total": len(df),
        "conectadas": int(masks["conectadas"].sum()),
        "activando": int(masks["activando"].sum()),
        "desconectadas": int(masks["desconectadas"].sum()),
    }


def obtener_masks_kpi_vencidos(df):
    if df.empty:
        return {}
    estado = df.get(COL_ESTADO_COMERCIAL, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    ya_marcado = estado == VALOR_ESTADO_COMERCIAL_VENCIDO
    estado_activ = df.get(COL_ESTADO_ACTIVACION, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    return {
        "desfase": ~ya_marcado,
        "ya_marcado": ya_marcado,
        "conectadas": estado_activ == 'CONECTADO',
    }


def calcular_kpis_vencidos(df):
    """"Gestionar Bajas" (antes "Vencidos"; unión estado=Vencido | fecha
    vencida): el valor de esta bandeja es detectar el DESFASE entre ambas
    señales (unidad con fecha ya vencida pero que todavía no dice "Vencido"
    en ESTADO COMERCIAL, el caso que motivó este panel) -- se separa de las
    que ya están correctamente marcadas."""
    if df.empty:
        return {"total": 0, "desfase": 0, "ya_marcado": 0, "conectadas": 0}
    masks = obtener_masks_kpi_vencidos(df)
    return {
        "total": len(df),
        "desfase": int(masks["desfase"].sum()),
        "ya_marcado": int(masks["ya_marcado"].sum()),
        "conectadas": int(masks["conectadas"].sum()),
    }


def filtrar_renovaciones(df):
    """Panel Comercial -> Renovaciones (regla actualizada 28-09-2026, a
    pedido explicito): solo unidades con TÉRMINO CONTRATO por vencer dentro
    de los proximos 30 dias calendario, incluyendo las que vencen hoy
    (clasificar_vigencia_contrato().por_vencer). Las ya vencidas quedan
    fuera (van a "Vencidos").

    Ademas exige ESTADO COMERCIAL en (VIGENTE, REVISAR) y ESTADO DE
    ACTIVACIÓN ACTUAL = CONECTADO (case-insensitive). filtrar_vencimientos()
    delega en esta funcion, asi que hereda la misma regla."""
    if df.empty or 'TÉRMINO CONTRATO' not in df.columns:
        return df.iloc[0:0]
    clasif = clasificar_vigencia_contrato(df)
    resultado = df[clasif['por_vencer']]
    if COL_ESTADO_ACTIVACION in resultado.columns:
        conectado = resultado[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper() == ESTADO_CONECTADO
        resultado = resultado[conectado]
    if COL_ESTADO_COMERCIAL in resultado.columns:
        estados_validos = {VALOR_ESTADO_COMERCIAL_VIGENTE, VALOR_ESTADO_COMERCIAL_REVISAR}
        en_estado = resultado[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper().isin(estados_validos)
        resultado = resultado[en_estado]
    # Matriz de destino: Revisar siempre va a Nuevas oportunidades.
    confusa = _mask_revisar_hacia_comercial(df)
    if confusa.any():
        resultado = resultado[~confusa.loc[resultado.index]]
    return resultado


def filtrar_vencimientos(df):
    """Panel Comercial -> Vencimientos (regla pedida por el usuario,
    11-09-2026): excluye MENSUAL (nunca vence) y las unidades con más de 30
    días calendario restantes para vencer. Hoy esa condición es exactamente
    la misma que clasificar_vigencia_contrato().es_renovacion (vencido |
    por_vencer <=30 días) -- MENSUAL ya queda fuera de ambas banderas porque
    no parsea como fecha (fecha_valida=False). Se expone como función
    aparte de filtrar_renovaciones (en vez de reusarla directo en
    comercial.py) para que Vencimientos y Renovaciones puedan definirse con
    reglas distintas en el futuro sin tocar la Nueva interfaz; por ahora no
    duplica lógica, delega en la misma clasificación."""
    return filtrar_renovaciones(df)


def _mask_revisar_hacia_comercial(df):
    """Unidades con ESTADO COMERCIAL = 'Revisar' cuya combinación con ESTADO
    DE ACTIVACIÓN ACTUAL da ETAPA GESTIÓN = 'COMERCIAL' en
    ESTADO_COMERCIAL_ACTIVACION_ETAPA_FLAT -- hoy (25-09-2026, matriz
    actualizada por el usuario: REVISAR+ACTIVANDO pasó de OPERACIONES a
    COMERCIAL) eso es TODA la fila de Revisar, sin excepciones.
    Generalizado (24-09-2026, pedido explícito del usuario) desde la versión
    original que solo cubría Activando/Sin flota: cualquier combinación de
    Revisar que la matriz mande a COMERCIAL debe caer en Por gestionar, no
    solo esas dos. Reutiliza la misma matriz que ya usa
    _calcular_etapa_gestion_esperada_vectorizado, sin reimplementar la regla
    -- un cambio futuro en la matriz se refleja acá automáticamente, sin
    tocar este código.
    Usada por filtrar_vencidos (para excluirlas) y filtrar_por_gestionar
    (para incluirlas).

    Excepción (22-10-2026, pedido de Javiera): Revisar + Conectado ya no va a
    Nuevas oportunidades sino a Renovar contratos (ver mascara_revisar_conectado)."""
    if df.empty or COL_ESTADO_COMERCIAL not in df.columns or COL_ESTADO_ACTIVACION not in df.columns:
        return pd.Series(False, index=df.index)
    estado_com_norm = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
    estado_act_norm = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    es_revisar = estado_com_norm == VALOR_ESTADO_COMERCIAL_REVISAR
    clave_matriz = estado_com_norm + "||" + estado_act_norm
    etapa = clave_matriz.map(ESTADO_COMERCIAL_ACTIVACION_ETAPA_FLAT)
    return es_revisar & (etapa == 'COMERCIAL') & (estado_act_norm != ESTADO_CONECTADO)


def mascara_revisar_conectado(df):
    """Unidades con ESTADO COMERCIAL = Revisar que ya están Conectadas: se gestionan
    en Renovar contratos, donde se les crea el contrato."""
    if df.empty or COL_ESTADO_COMERCIAL not in df.columns or COL_ESTADO_ACTIVACION not in df.columns:
        return pd.Series(False, index=df.index)
    estado_com = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
    estado_act = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    return (estado_com == VALOR_ESTADO_COMERCIAL_REVISAR) & (estado_act == ESTADO_CONECTADO)


def filtrar_revisar_conectados(df):
    return df[mascara_revisar_conectado(df)]


def filtrar_vencidos(df):
    """Panel Comercial -> Vencidos (pedido explícito del usuario, 23-09-2026):
    unión de dos condiciones, no la misma regla que Renovaciones/
    filtrar_vencimientos (que solo mira la fecha dentro de una ventana de 30
    días) -- 1) ESTADO COMERCIAL ya dice 'Vencido', 2) TÉRMINO CONTRATO ya
    pasó en el calendario aunque ESTADO COMERCIAL diga otra cosa (ej.
    'Vigente' desactualizado por error humano, el caso que motivó este
    panel).

    Excluye ESTADO COMERCIAL en (BAJA, BAJA SOLICITADA) -- ajustado a pedido
    explícito del usuario (23-09-2026): una unidad dada de baja se da de
    baja ANTES de que llegue su TÉRMINO CONTRATO, así que si ya está en Baja
    o Baja Solicitada no cuenta como "vencida" para este panel, aunque la
    fecha ya haya pasado (mismo criterio de exclusión que ya usa
    filtrar_renovaciones)."""
    if df.empty:
        return df.iloc[0:0]

    fecha_vencida = pd.Series(False, index=df.index)
    if 'TÉRMINO CONTRATO' in df.columns:
        clasif = clasificar_vigencia_contrato(df)
        fecha_vencida = clasif['vencido']

    estado_vencido = pd.Series(False, index=df.index)
    estado_norm = None
    if COL_ESTADO_COMERCIAL in df.columns:
        estado_norm = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
        estado_vencido = estado_norm == VALOR_ESTADO_COMERCIAL_VENCIDO

    resultado = df[fecha_vencida | estado_vencido]

    if estado_norm is not None:
        estados_baja = {VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA}
        en_baja = estado_norm.loc[resultado.index].isin(estados_baja)
        resultado = resultado[~en_baja]

    # 24-09-2026: Revisar -> COMERCIAL (según la matriz) se saca de Vencidos
    # y se gestiona desde Por gestionar (ver _mask_revisar_hacia_comercial).
    confusa = _mask_revisar_hacia_comercial(df)
    if confusa.any():
        resultado = resultado[~confusa.loc[resultado.index]]

    # Matriz de destino: lo que la matriz manda a Operaciones (ej. Vigente + Activando) no es de Comercial.
    if estado_norm is not None and COL_ESTADO_ACTIVACION in df.columns and not resultado.empty:
        estado_res = estado_norm.loc[resultado.index]
        activ_res = resultado[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
        resultado = resultado[(estado_res + "||" + activ_res).map(ESTADO_COMERCIAL_ACTIVACION_ETAPA_FLAT) != 'OPERACIONES']
        # Vigente / Activación pendiente + No aplica es de Nuevas oportunidades aunque la fecha haya pasado.
        no_aplica_ajeno = (activ_res.loc[resultado.index] == 'NO APLICA') & \
            (estado_norm.loc[resultado.index] != VALOR_ESTADO_COMERCIAL_VENCIDO)
        resultado = resultado[~no_aplica_ajeno]

    return resultado


def filtrar_gestionar_bajas(df):
    """Panel Comercial -> Gestionar bajas: ESTADO COMERCIAL en (BAJA, BAJA
    SOLICITADA). Ampliado (24-09-2026, pedido explícito del usuario) para
    incluir BAJA SOLICITADA -- antes solo tomaba 'BAJA' exacto y Baja
    Solicitada quedaba sin pestaña propia (salvo el caso casual de ESTADO DE
    ACTIVACIÓN ACTUAL = 'No aplica', que ya caía en Por gestionar). No debe
    confundirse con Bajas CM (proceso aparte, basado en ausencia en el Excel
    mensual de CM) ni con Bajas de Operaciones (basado en ESTADO DE
    ACTIVACIÓN ACTUAL)."""
    if df.empty or 'ESTADO COMERCIAL' not in df.columns:
        return df.iloc[0:0]
    estado_norm = df['ESTADO COMERCIAL'].astype(str).str.strip().str.upper()
    es_baja = estado_norm.isin({VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA})
    # Matriz de destino: con Activando o Conectado la baja la gestiona Operaciones -> Bajas.
    if COL_ESTADO_ACTIVACION in df.columns:
        activacion_norm = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
        es_baja = es_baja & ~activacion_norm.isin({ESTADO_ACTIVANDO, ESTADO_CONECTADO})
    return df[es_baja]


def normalizar_cdb(valor):
    """CDB como texto comparable: sin espacios ni '.0' final; '' si está vacío."""
    texto = "" if valor is None or pd.isna(valor) else str(valor).strip()
    texto = re.sub(r'\.0$', '', texto).replace(' ', '')
    return "" if texto.upper() in ('', '-', 'NAN', 'NONE') else texto.upper()


def cdb_referencia_por_razon_social(df):
    """CDB comercial más frecuente de cada RAZÓN SOCIAL (el que se toma como
    el correcto). Ante un empate gana el que aparece primero."""
    if df is None or df.empty or 'RAZÓN SOCIAL' not in df.columns or 'CDB' not in df.columns:
        return {}
    datos = pd.DataFrame({
        'razon': df['RAZÓN SOCIAL'].astype(str).str.strip(),
        'cdb': df['CDB'].map(normalizar_cdb),
    })
    datos = datos[(datos['razon'] != '') & (datos['cdb'] != '')]
    if datos.empty:
        return {}
    conteo = datos.groupby(['razon', 'cdb'], sort=False).size().reset_index(name='n')
    conteo = conteo.sort_values('n', ascending=False, kind='stable')
    return dict(zip(conteo['razon'].drop_duplicates(), conteo.drop_duplicates('razon')['cdb']))


def cdbs_por_razon_social(df):
    """{RAZÓN SOCIAL: [CDB comerciales distintos]}, el más frecuente primero."""
    if df is None or df.empty or 'RAZÓN SOCIAL' not in df.columns or 'CDB' not in df.columns:
        return {}
    datos = pd.DataFrame({
        'razon': df['RAZÓN SOCIAL'].astype(str).str.strip(),
        'cdb': df['CDB'].map(normalizar_cdb),
    })
    datos = datos[(datos['razon'] != '') & (datos['cdb'] != '')]
    conteo = datos.groupby(['razon', 'cdb'], sort=False).size().reset_index(name='n')
    conteo = conteo.sort_values('n', ascending=False, kind='stable')
    # Una pasada en vez de un groupby por razón social (~5 veces más rápido con miles de clientes)
    resultado = {}
    for razon, cdb in zip(conteo['razon'], conteo['cdb']):
        resultado.setdefault(razon, []).append(cdb)
    return resultado


def cdb_discrepante(cdb, razon_social, referencia):
    """True si la empresa tiene un CDB de referencia y el de la unidad es otro
    (o está vacío)."""
    esperado = referencia.get(str(razon_social).strip())
    return bool(esperado) and normalizar_cdb(cdb) != esperado


def filtrar_por_gestionar(df):
    """Panel Comercial -> Por gestionar (regla confirmada con Javiera):
    ESTADO DE ACTIVACIÓN ACTUAL == 'NO APLICA', igualdad EXACTA (no
    'contains'), para no confundir con 'ACTIVACION PENDIENTE', 'SIN FLOTA',
    'NO ENTREGADO', 'ACTIVANDO', 'CONECTADO' ni 'DESCONECTADO'.

    Además (24-09-2026, pedido explícito del usuario) incluye cualquier
    combinación de Revisar que la matriz de negocio mande a COMERCIAL -- ver
    _mask_revisar_hacia_comercial. Esta segunda condición NO amplía la
    regla NO APLICA para el resto de la app: solo agrega las combinaciones
    de Revisar que antes no tenían pestaña propia."""
    if df.empty or 'ESTADO DE ACTIVACIÓN ACTUAL' not in df.columns:
        return df.iloc[0:0]
    no_aplica = df['ESTADO DE ACTIVACIÓN ACTUAL'].astype(str).str.strip().str.upper() == 'NO APLICA'
    # Matriz de destino: Baja y Vencido con No aplica van a Recuperar clientes / Renovar contratos.
    if COL_ESTADO_COMERCIAL in df.columns:
        estado_com = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
        no_aplica = no_aplica & ~estado_com.isin({VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA,
                                                  VALOR_ESTADO_COMERCIAL_VENCIDO})
    return df[no_aplica | _mask_revisar_hacia_comercial(df)]


OBSERVACION_VIENE_DE_PROVISIONES = 'Viene de Provisiones'


def filtrar_vigentes(df):
    """Panel Comercial -> Vigentes (21-09-2026, cierre del flujo Comercial ->
    Operaciones -> Comercial para unidades nuevas): ESTADO COMERCIAL en
    (VIGENTE, ACTIVACIÓN PENDIENTE). Ampliado (24-09-2026, pedido explícito
    del usuario) para incluir ACTIVACIÓN PENDIENTE -- comparte exactamente
    la misma fila de ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ
    (_FILA_OPERACIONES_SALVO_CONECTADO) que VIGENTE, y antes no tenía
    ninguna pestaña propia en Comercial (solo aparecía por casualidad si la
    fecha coincidía con Vencidos/Renovaciones).
    Distinta de filtrar_por_gestionar (que mira ESTADO DE ACTIVACIÓN ACTUAL,
    no ESTADO COMERCIAL): una unidad Vigente + Conectada ya no cumple
    'NO APLICA', así que no vuelve a aparecer en "Por gestionar"."""
    if df.empty or 'ESTADO COMERCIAL' not in df.columns:
        return df.iloc[0:0]
    estado_norm = df['ESTADO COMERCIAL'].astype(str).str.strip().str.upper()
    # Los datos traen "ACTIVACION PENDIENTE" sin tilde; se acepta con y sin tilde.
    estados = {VALOR_ESTADO_COMERCIAL_VIGENTE, VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE, 'ACTIVACION PENDIENTE'}
    mask = estado_norm.isin(estados)
    # Matriz de destino: solo Conectado es "vigente"; el resto de estados es de Operaciones o Nuevas oportunidades.
    if COL_ESTADO_ACTIVACION in df.columns:
        mask = mask & (df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper() == ESTADO_CONECTADO)
    return df[mask]


def pendientes_marcar_vigente(df):
    """Unidades que "Marcar como Vigente" corrige, ya Conectadas: las que quedaron en
    Activación Pendiente y los contratos MENSUAL en Vencido (un mensual no vence por fecha)."""
    if df.empty or COL_ESTADO_COMERCIAL not in df.columns or COL_ESTADO_ACTIVACION not in df.columns:
        return df.iloc[0:0]
    estado_com = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
    estado_act = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    pendiente = estado_com.isin((VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE, 'ACTIVACION PENDIENTE'))
    mensual_vencido = pd.Series(False, index=df.index)
    if 'TÉRMINO CONTRATO' in df.columns:
        mensual_vencido = (estado_com == VALOR_ESTADO_COMERCIAL_VENCIDO) & \
                          (df['TÉRMINO CONTRATO'].astype(str).str.strip().str.upper() == 'MENSUAL')
    return df[(pendiente | mensual_vencido) & (estado_act == ESTADO_CONECTADO)]


def es_forma_provision(fila):
    """True si FORMA DE CONTRATO de la unidad (dict o fila) es exactamente Provisión."""
    return str(fila.get('FORMA DE CONTRATO', '')).strip().upper() in ('PROVISION', 'PROVISIÓN')


def cambios_provision_a_conversion(filas, df_base, hoy=None):
    """Cambios {vin: {'VIN', 'cambios', 'ID'}} que pasan unidades de Provisión a Conversión con
    facturación manual: Vigente y Conectada (la matriz las deja en Comercial, sin pasar por
    Operaciones), inicio el día 1 del mes, duración "-" (mensual) y sin fecha de baja.
    `filas` es {vin: fila}. JustTime sigue la regla del formulario: FACTURACIÓN MANUAL no va a
    JustTime, así que un contrato Si o Revisar pago queda en Eliminar y uno Pendiente en "-"."""
    from src.core.constants import (
        COL_FORMA_CONTRATO, COL_TIPO_FACTURACION, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_INICIO_CONTRATO,
        COL_DURACION_MESES, COL_TERMINO_CONTRATO, COL_FECHA_BAJA, COL_ETAPA_GESTION, COL_CONTRATO_JUSTTIME,
        COL_FECHA_INICIO_FACT, COL_FECHA_TERMINO_FACT, VALOR_TIPO_FACT_FACTURACION_MANUAL,
        VALOR_ESTADO_COMERCIAL_VIGENTE, ESTADO_CONECTADO, JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_REVISAR_PAGO,
        JUSTTIME_ESTADO_ELIMINAR, JUSTTIME_ESTADO_PENDIENTE, JUSTTIME_ESTADO_NO_APLICA,
        ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ)

    hoy = hoy or datetime.now()
    etapa = ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ[VALOR_ESTADO_COMERCIAL_VIGENTE][ESTADO_CONECTADO]
    base = {
        COL_FORMA_CONTRATO: 'Conversion',
        COL_TIPO_FACTURACION: VALOR_TIPO_FACT_FACTURACION_MANUAL,
        COL_ESTADO_COMERCIAL: VALOR_ESTADO_COMERCIAL_VIGENTE.capitalize(),
        COL_ESTADO_ACTIVACION: ESTADO_CONECTADO.capitalize(),
        COL_INICIO_CONTRATO: hoy.replace(day=1).strftime("%d-%m-%Y"),
        COL_DURACION_MESES: '-',
        COL_TERMINO_CONTRATO: 'MENSUAL',
        COL_FECHA_BAJA: '',
        COL_ETAPA_GESTION: etapa,
    }
    cambios = {}
    for vin, fila in filas.items():
        celdas = dict(base)
        estado_jt = str(fila.get(COL_CONTRATO_JUSTTIME, '')).strip()
        if estado_jt in (JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_REVISAR_PAGO):
            celdas[COL_CONTRATO_JUSTTIME] = JUSTTIME_ESTADO_ELIMINAR
        elif estado_jt == JUSTTIME_ESTADO_PENDIENTE:
            celdas[COL_CONTRATO_JUSTTIME] = JUSTTIME_ESTADO_NO_APLICA
            celdas[COL_FECHA_INICIO_FACT] = ''
            celdas[COL_FECHA_TERMINO_FACT] = ''
        cambios[vin] = {'VIN': vin, 'cambios': celdas}
    return agregar_id_a_cambios(cambios, df_base)


def filtrar_renovar_clientes(df):
    """Panel Comercial -> Renovar clientes: unión de las antiguas
    sub-pestañas Renovaciones, Gestionar Bajas (vencidos) y Vigentes, más las
    unidades Revisar ya Conectadas. Cada regla sigue siendo la de su función original."""
    if df.empty:
        return df.iloc[0:0]
    indices = set()
    for filtro in (filtrar_renovaciones, filtrar_vencidos, filtrar_vigentes, filtrar_revisar_conectados):
        indices.update(filtro(df).index)
    return df[df.index.isin(indices)]


def obtener_masks_kpi_renovar_clientes(df):
    """Máscaras de las tarjetas de "Renovar clientes". Se reparten sin
    solaparse: vencidas, por vencer en 30 días y vigentes (el resto)."""
    vencidas = pd.Series(df.index.isin(filtrar_vencidos(df).index), index=df.index)
    por_vencer = pd.Series(df.index.isin(filtrar_renovaciones(df).index), index=df.index) & ~vencidas
    al_dia = pd.Series(df.index.isin(filtrar_vigentes(df).index), index=df.index) | mascara_revisar_conectado(df)
    vigentes = al_dia & ~vencidas & ~por_vencer
    return {"vencidas": vencidas, "por_vencer": por_vencer, "vigentes": vigentes}


def calcular_kpis_renovar_clientes(df, masks=None):
    """KPI de "Renovar clientes" sobre la bandeja ya filtrada. `masks`: las de
    obtener_masks_kpi_renovar_clientes(df) si ya están calculadas."""
    if df.empty:
        return {"total": 0, "vencidas": 0, "por_vencer": 0, "vigentes": 0}
    if masks is None:
        masks = obtener_masks_kpi_renovar_clientes(df)
    return {
        "total": len(df),
        "vencidas": int(masks["vencidas"].sum()),
        "por_vencer": int(masks["por_vencer"].sum()),
        "vigentes": int(masks["vigentes"].sum()),
    }


def construir_mascara_busqueda(df, search_text, columnas, columnas_exactas=()):
    """Mascara booleana del buscador de texto libre de comercial.py
    (filter_table), incluyendo el pegado masivo de VINs vía
    MultiSearchLineEdit (ver main_window.py).

    Semantica preservada: terminos separados por ',' se combinan con OR;
    dentro de un mismo termino, palabras separadas por espacio se combinan
    con AND (ej. "empresa vencido" exige ambas palabras, en cualquier
    columna). `search_text` ya debe venir en minusculas (mismo contrato que
    el codigo anterior en comercial.py).

    Los terminos de una sola palabra (el caso tipico al pegar una lista de
    VINs/CDB) se resuelven con UNA sola expresion regular por columna
    (alternancia 'term1|term2|...'), no con un `.str.contains()` por
    termino y por columna: la version anterior escalaba
    O(terminos x columnas) y con listas de miles de VINs pegados tardaba
    mas de 20 segundos, congelando la interfaz (medido: ~1548 terminos ->
    ~20.6s con el loop anterior, ~0.9s con esta version vectorizada). Los
    terminos compuestos (AND) se resuelven termino a termino porque en la
    practica son pocos (nunca se pegan listas masivas de frases).

    `columnas_exactas` (p. ej. 'ID', el N° Contrato) solo calzan por igualdad
    con el termino, no por 'contiene': buscar '12' no debe traer los
    contratos 112 o 1203."""
    or_terms = [t.strip() for t in str(search_text).split(',') if t.strip()]
    if not or_terms:
        return pd.Series(False, index=df.index)

    columnas_presentes = [c for c in columnas if c in df.columns]
    exactas_presentes = [c for c in columnas_exactas if c in df.columns]
    exactas = {
        c: df[c].astype(str).str.strip().str.replace(r'\.0$', '', regex=True).str.lower() for c in exactas_presentes
    }

    terminos_simples = []
    terminos_compuestos = []
    for or_term in or_terms:
        and_terms = [t.strip() for t in or_term.split() if t.strip()]
        if len(and_terms) == 1:
            terminos_simples.append(and_terms[0])
        elif len(and_terms) > 1:
            terminos_compuestos.append(and_terms)

    final_mask = pd.Series(False, index=df.index)

    if terminos_simples and columnas_presentes:
        patron = '|'.join(re.escape(t.lower()) for t in terminos_simples)
        for col in columnas_presentes:
            final_mask |= df[col].astype(str).str.lower().str.contains(patron, na=False, regex=True)
    if terminos_simples:
        buscados = {t.lower() for t in terminos_simples}
        for serie in exactas.values():
            final_mask |= serie.isin(buscados)

    for and_terms in terminos_compuestos:
        and_mask = pd.Series(True, index=df.index)
        for a_term in and_terms:
            col_mask = pd.Series(False, index=df.index)
            for col in columnas_presentes:
                col_mask |= df[col].astype(str).str.lower().str.contains(a_term, na=False, regex=False)
            for serie in exactas.values():
                col_mask |= serie == a_term.lower()
            and_mask &= col_mask
        final_mask |= and_mask

    return final_mask


def validar_valor_pegado(col_name, texto_portapapeles, dropdown_options):
    """Extraccion literal de la validacion de
    ComercialModule.paste_dropdown_value_to_selection() (el texto del
    portapapeles ya viene resuelto/no vacio: leer el portapapeles sigue
    siendo responsabilidad de comercial.py). No muestra mensajes; devuelve
    una tupla (resultado, valor_o_mensaje):
      - ("sin_opciones", None): la columna no tiene opciones validas
        configuradas en dropdown_options; comercial.py no debe hacer nada.
      - ("invalido", mensaje): el valor no esta en la lista permitida;
        comercial.py debe mostrar `mensaje` en un QMessageBox.warning y no
        modificar ninguna celda.
      - ("valido", valor_correcto): comercial.py debe aplicar
        `valor_correcto` (con la capitalizacion exacta de dropdown_options)
        a las celdas seleccionadas.
    """
    opciones_validas = dropdown_options.get(col_name, [])
    if not opciones_validas:
        return "sin_opciones", None

    clipboard_upper = texto_portapapeles.upper()
    opciones_upper = {opc.upper(): opc for opc in opciones_validas}

    if clipboard_upper not in opciones_upper:
        mensaje = (
            f"El valor '{texto_portapapeles}' no es un valor válido para '{col_name}'.\n\n"
            "Opciones permitidas:\n- " + "\n- ".join(opciones_validas)
        )
        return "invalido", mensaje

    return "valido", opciones_upper[clipboard_upper]


# Tope de DURACIÓN (MESES) (20-10-2026, a pedido del usuario): una duración
# absurda llevaba el término fuera del calendario y hacía fallar la carga
DURACION_MAXIMA_MESES = 99


def validar_duracion(valor):
    """Extraccion literal de la validacion de DURACION (MESES) en
    ComercialModule.on_item_edited() (rama `col_name == 'DURACIÓN (MESES)'`).
    No muestra mensajes ni toca ninguna celda; devuelve una tupla
    (resultado, valor_o_mensaje):
      - ("vacio", ""): valor vacio o 'nan'; comercial.py debe guardar "" en
        pending_changes sin tocar TÉRMINO CONTRATO.
      - ("mensual", "-"): valor '-' o 'MENSUAL' (case-insensitive);
        comercial.py debe fijar DURACIÓN (MESES)='-' y forzar
        TÉRMINO CONTRATO='MENSUAL' (esa relacion NO cambia en esta fase).
      - ("numerico", "24"): numero > 0, normalizado a entero string;
        comercial.py debe guardarlo tal cual en pending_changes.
      - ("invalido", mensaje): comercial.py debe mostrar `mensaje` en un
        QMessageBox.warning, revertir la celda y no guardar el cambio.
    """
    val_limpio = str(valor).strip()
    if val_limpio == "" or val_limpio.upper() == 'NAN':
        return "vacio", ""
    if val_limpio == '-' or val_limpio.upper() == 'MENSUAL':
        return "mensual", "-"
    if val_limpio.replace('.', '', 1).isdigit() and 0 < float(val_limpio) < DURACION_MAXIMA_MESES + 1:
        return "numerico", str(int(float(val_limpio)))
    return "invalido", f"La duración debe ser un número mayor a 0 y de hasta {DURACION_MAXIMA_MESES} meses, o un guion '-'."


def validar_fecha_ddmmyyyy(valor):
    """Extraccion literal de la validacion de fecha en
    ComercialModule.on_item_edited() (rama
    `col_name in ['INICIO CONTRATO', 'INICIO', 'TERMINO']`). Preserva la
    asimetria exacta del original entre `strip()` (para detectar vacio) y
    `lower()` sin strip (para detectar 'nan' literal). No muestra mensajes ni
    toca ninguna celda; devuelve una tupla (resultado, valor_o_mensaje):
      - ("vacio", ""): valor vacio o 'nan'; comercial.py debe guardar "" en
        pending_changes.
      - ("valido", "10-10-2026"): fecha valida en formato DD-MM-YYYY (ya
        strip-eada); comercial.py debe guardarla en pending_changes.
      - ("invalido", mensaje): comercial.py debe mostrar `mensaje` en un
        QMessageBox.warning, revertir la celda y no guardar el cambio.
    """
    valor_str = str(valor)
    if valor_str.strip() != "" and valor_str.lower() != 'nan':
        try:
            datetime.strptime(valor_str.strip(), "%d-%m-%Y")
            return "valido", valor_str.strip()
        except ValueError:
            return "invalido", "La fecha debe ser: DD-MM-YYYY\nEjemplo: 10-08-2026"
    return "vacio", ""


def formatear_pago_cm(valor_num):
    """Extraccion literal de la formula de formato monetario usada en
    ComercialModule.on_item_edited() (rama `col_name == 'PAGO CM'`), tanto
    para el valor recien parseado como para el valor anterior que la UI
    obtiene de self.df_base cuando el valor pegado es invalido. No agrega
    redondeos ni separadores nuevos: reproduce exactamente
    `f"$-" if v==0 else f"{'-' if v<0 else ''}${int(abs(v)+0.5):,}".replace(",", ".")`."""
    return f"$-" if valor_num == 0 else f"{'-' if valor_num < 0 else ''}${int(abs(valor_num)+0.5):,}".replace(",", ".")


def parsear_pago_cm(valor):
    """Extraccion literal del parseo de PAGO CM en
    ComercialModule.on_item_edited(): quita '$', '.' y ',' (mismo orden,
    mismos caracteres — no agrega separadores decimales nuevos) y convierte a
    float (vacio -> 0.0). No conoce PyQt6, `self` ni el fallback al valor
    anterior: eso sigue siendo responsabilidad de comercial.py contra
    `self.df_base['PAGO CM_NUM']`. Devuelve una tupla (resultado, dato):
      - ("valido", {"num": 1500.0, "formato": "$1.500"}): comercial.py debe
        guardar `num` en pending_changes y `formato` en la celda.
      - ("invalido", None): comercial.py debe mostrar QMessageBox.warning,
        buscar el valor anterior en self.df_base y formatearlo con
        formatear_pago_cm().
    """
    val_limpio = str(valor).replace('$', '').replace('.', '').replace(',', '').strip()
    try:
        val_num = float(val_limpio) if val_limpio else 0.0
    except ValueError:
        return "invalido", None
    return "valido", {"num": val_num, "formato": formatear_pago_cm(val_num)}


def quitar_vin(df, vin, id_contrato=None):
    """Extraccion literal de ComercialModule._on_del_finished(): filtra del
    DataFrame la fila cuyo VIN (normalizado a mayusculas/sin espacios)
    coincide con `vin`. Con `id_contrato` (y columna ID) quita solo ese contrato."""
    id_contrato = _normalizar_id_contrato(id_contrato)
    if id_contrato and 'ID' in df.columns:
        return df[_ids_normalizados(df) != id_contrato]
    return df[df['VIN'].astype(str).str.strip().str.upper() != str(vin).strip().upper()]


def agregar_fila(df, new_data):
    """Extraccion literal de ComercialModule._on_add_finished(): concatena
    `new_data` (dict de una fila nueva) al final del DataFrame."""
    df_new = pd.DataFrame([new_data])
    return pd.concat([df, df_new], ignore_index=True)


def detectar_contradicciones_etapa_gestion(df):
    """Filas cuyo ETAPA GESTIÓN actual NO coincide con la etapa que le
    correspondería según la regla de negocio centralizada en
    DataFrameFormatter.calcular_etapa_gestion_esperada (la misma que aplica
    DataFrameFormatter.clean() en cada carga/sincronización).

    La comparación usa _calcular_etapa_gestion_esperada_vectorizado(), una
    version vectorizada (Serie completa, sin apply(axis=1) fila por fila) de
    esa misma regla -- ver el docstring de esa función para el detalle de
    por qué se traduce aparte en vez de reusar directo
    calcular_etapa_gestion_esperada(row), y la cobertura de equivalencia en
    TestDetectarContradiccionesEtapaGestion/TestCalcularEtapaGestionEsperadaVectorizadoEquivaleARowWise
    (src/tests/test_comercial_services.py).

    Devuelve el subconjunto de `df` con contradicciones (DataFrame vacío si
    no hay ninguna, o si el DataFrame de entrada no tiene ETAPA GESTIÓN)."""
    if df.empty or COL_ETAPA_GESTION not in df.columns:
        return df.iloc[0:0]

    etapa_esperada_norm = _calcular_etapa_gestion_esperada_vectorizado(df)
    etapa_actual_norm = df[COL_ETAPA_GESTION].astype(str).str.strip().str.upper()

    mask = etapa_actual_norm != etapa_esperada_norm
    return df[mask]


def detectar_inconsistencias_forma_contrato_tipo_facturacion(df):
    """Filas cuya combinación (FORMA DE CONTRATO, TIPO DE FACTURACION) actual
    NO cumple FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ (constants.py, matriz de
    negocio entregada por Javiera, 24-09-2026) -- la misma matriz que ya
    aplica en vivo ComercialAgregarDialog
    (_sincronizar_tipo_facturacion_con_forma_contrato), reutilizada tal cual
    (no se duplica). Es una herramienta de solo DETECCIÓN para datos
    históricos previos a la regla: nunca modifica ni sugiere el valor
    correcto, eso lo decide el usuario/negocio (ver botón "Revisar
    inconsistencias" en Vista Completa, comercial.py).

    Reglas de normalización/exclusión (confirmadas contra RM_JAVI.csv real,
    24-09-2026, antes de implementar -- ver conversación con el usuario):
    - FORMA DE CONTRATO se normaliza con `.strip().upper()`, igual que en
      ComercialAgregarDialog. Un valor que no esté en la matriz (legado/no
      reconocido, incluido vacío) NUNCA se marca -- mismo criterio "lo no
      reconocido no se restringe" que el resto de las matrices de negocio
      del sistema.
    - TIPO DE FACTURACION vacío o '-' NUNCA se marca, aunque su FORMA DE
      CONTRATO sí esté en la matriz: significa "todavía sin asignar", no una
      combinación contradictoria. En los datos reales, la mayoría de las
      filas con FORMA DE CONTRATO reconocido tienen TIPO DE FACTURACION en
      '-' (unidades sin procesar aún) -- tratar eso como "inconsistencia"
      ahogaría en ruido los ~1.000 casos reales donde sí hay dos valores
      concretos que se contradicen entre sí."""
    cols_necesarias = {'FORMA DE CONTRATO', COL_TIPO_FACTURACION}
    if df.empty or not cols_necesarias.issubset(df.columns):
        return df.iloc[0:0]

    forma_norm = df['FORMA DE CONTRATO'].astype(str).str.strip().str.upper()
    tf_norm = df[COL_TIPO_FACTURACION].astype(str).str.strip().str.upper()

    def _es_inconsistente(forma, tf):
        if tf in ('', '-'):
            return False
        validos = FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(forma)
        if validos is None:
            return False
        return tf not in validos

    mask = [_es_inconsistente(f, t) for f, t in zip(forma_norm, tf_norm)]
    return df[mask]


def contar_forma_contrato_sin_tipo_facturacion_asignado(df):
    """Cuenta filas cuyo FORMA DE CONTRATO está en
    FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ pero TIPO DE FACTURACION sigue
    vacío/'-' ("todavía no gestionado" -- ver
    detectar_inconsistencias_forma_contrato_tipo_facturacion, que por eso
    mismo NO las cuenta como inconsistencia). Puramente informativo: se usa
    junto al conteo de inconsistencias reales para diferenciar ambos casos
    en el mensaje de sincronización (RMJaviSyncWorker, comercial.py), sin
    reimplementar la consulta a la matriz -- solo referencia el mismo dict."""
    cols_necesarias = {'FORMA DE CONTRATO', COL_TIPO_FACTURACION}
    if df.empty or not cols_necesarias.issubset(df.columns):
        return 0

    forma_norm = df['FORMA DE CONTRATO'].astype(str).str.strip().str.upper()
    tf_norm = df[COL_TIPO_FACTURACION].astype(str).str.strip().str.upper()

    mask = forma_norm.isin(FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.keys()) & tf_norm.isin(['', '-'])
    return int(mask.sum())


def _clave_contrato(vin, id_contrato):
    return (str(vin).strip().upper(), _normalizar_id_contrato(id_contrato))


def detectar_termino_distinto_de_duracion(df_crudo):
    """Contratos cuyo TÉRMINO CONTRATO original del archivo no coincide con
    INICIO CONTRATO + DURACIÓN (MESES). Debe recibir el df ANTES de
    DataFrameFormatter.clean(), que recalcula el término y taparía la
    diferencia. Devuelve {(VIN, ID): término original}.

    Solo compara filas con inicio y término que sean fechas reales y duración
    numérica; las Bajas se excluyen porque su término es la fecha de baja."""
    columnas = {'VIN', 'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO'}
    if df_crudo is None or df_crudo.empty or not columnas.issubset(df_crudo.columns):
        return {}
    estados = (df_crudo['ESTADO COMERCIAL'].astype(str).str.strip().str.upper().tolist()
               if 'ESTADO COMERCIAL' in df_crudo.columns else [''] * len(df_crudo))
    ids = df_crudo['ID'].tolist() if 'ID' in df_crudo.columns else [''] * len(df_crudo)
    cache = {}
    resultado = {}
    # Cada fecha distinta se interpreta una sola vez (las filas casi nunca
    # repiten la terna inicio, duración y término, pero sí cada fecha)
    fechas = {}

    def parsear(valor):
        if valor not in fechas:
            fechas[valor] = DataFrameFormatter.parsear_fecha_segura(valor)
        return fechas[valor]

    for vin, id_contrato, estado, inicio, duracion, termino in zip(
            df_crudo['VIN'].tolist(), ids, estados, df_crudo['INICIO CONTRATO'].tolist(),
            df_crudo['DURACIÓN (MESES)'].tolist(), df_crudo['TÉRMINO CONTRATO'].tolist()):
        if estado in (VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA):
            continue
        clave = (inicio, duracion, termino)
        if clave not in cache:
            cache[clave] = _termino_original_si_difiere(inicio, duracion, termino, parsear)
        if cache[clave]:
            resultado[_clave_contrato(vin, id_contrato)] = cache[clave]
    return resultado


def _termino_original_si_difiere(inicio, duracion, termino, parsear=DataFrameFormatter.parsear_fecha_segura):
    try:
        meses = int(float(str(duracion).strip().replace(',', '.')))
    except (ValueError, OverflowError):
        return ''
    if not 0 < meses <= DURACION_MAXIMA_MESES:
        return ''
    inicio_dt = parsear(inicio) if str(inicio).strip() not in ('', '-') else pd.NaT
    texto_termino = str(termino).strip()
    if pd.isna(inicio_dt) or texto_termino.upper() in ('', '-', 'MENSUAL', 'NAN'):
        return ''
    termino_dt = parsear(termino)
    if pd.isna(termino_dt):
        return ''
    if termino_dt.normalize() == (inicio_dt + pd.DateOffset(months=meses)).normalize():
        return ''
    return termino_dt.strftime('%d-%m-%Y')


def construir_correcciones_termino(df_fechas, df_base, vins=None):
    """Cambios para dejar en el archivo el TÉRMINO CONTRATO calculado (inicio +
    duración) de los contratos de `df_fechas`; `vins` limita a la selección.
    Marca 'escribir_termino' porque el escritor ignora esa columna por defecto."""
    if df_fechas is None or df_fechas.empty or 'TÉRMINO CONTRATO' not in df_fechas.columns:
        return {}
    permitidos = {str(v).strip().upper() for v in vins} if vins is not None else None
    cambios = {}
    for vin, termino in zip(df_fechas['VIN'].tolist(), df_fechas['TÉRMINO CONTRATO'].tolist()):
        vin = str(vin).strip().upper()
        if permitidos is not None and vin not in permitidos:
            continue
        if pd.isna(DataFrameFormatter.parsear_fecha_segura(termino)) or str(termino).strip().upper() in ('', '-', 'MENSUAL'):
            continue
        cambios[vin] = {'VIN': vin, 'cambios': {'TÉRMINO CONTRATO': str(termino).strip()}, 'escribir_termino': True}
    return agregar_id_a_cambios(cambios, df_base)


def filtrar_termino_distinto_de_duracion(df, discrepancias):
    """Filas de `df` (df_base) cuyo contrato está en `discrepancias`, con la
    columna 'TÉRMINO EN ARCHIVO' (el valor original) al final."""
    if df is None or df.empty or not discrepancias or 'VIN' not in df.columns:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    ids = df['ID'].tolist() if 'ID' in df.columns else [''] * len(df)
    originales = [discrepancias.get(_clave_contrato(v, i), '') for v, i in zip(df['VIN'].tolist(), ids)]
    serie = pd.Series(originales, index=df.index)
    mascara = serie != ''
    resultado = df[mascara].copy()
    resultado['TÉRMINO EN ARCHIVO'] = serie[mascara]
    return resultado


def normalizar_tipo_facturacion_por_forma_contrato(df):
    """Completa TIPO DE FACTURACION cuando está "sin asignar" (vacío/'-') y
    FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ tiene EXACTAMENTE una opción
    válida para el FORMA DE CONTRATO de esa fila -- es el único caso sin
    ambigüedad de negocio real (no existe otra opción posible entre la cual
    "adivinar"). Usada por RMJaviSyncWorker (comercial.py), 24-09-2026, a
    pedido explícito, justo después de _normalizar_vacios_a_guion (donde
    "sin asignar" ya suele ser '' o '-'). Trata NaN igual que vacío/'-' de
    forma robusta por cuenta propia (con pd.isna(), sin reimplementar
    _normalizar_vacios_a_guion): esta función también se prueba/usa de forma
    independiente contra datos crudos de RM_JAVI (lectura de Excel, donde
    una celda vacía SÍ llega como NaN real, no como texto).

    Reglas (misma matriz, sin duplicarla):
    - FORMA DE CONTRATO con 1 sola opción válida (CMB/CMG/CMS -> CM,
      DEMO/REVISAR/SIN CONTRATO/TEST -> SIN REGISTRO, PROVISION -> INTERNO,
      PROVISION + -> PROVISION +) y TIPO DE FACTURACION vacío/'-' -> se
      completa con esa única opción.
    - FORMA DE CONTRATO con 2+ opciones válidas (CONVERSION/VENTA) -> NUNCA
      se toca, aunque esté vacío: no hay forma de decidir cuál de las dos
      corresponde sin que sea el negocio quien lo defina.
    - FORMA DE CONTRATO no reconocido en la matriz -> no se toca.
    - Un TIPO DE FACTURACION que YA tiene un valor real (sea o no válido
      según la matriz) NUNCA se modifica aquí -- eso es exactamente lo que
      detectar_inconsistencias_forma_contrato_tipo_facturacion() debe seguir
      detectando para revisión manual, nunca autocorregirse.

    Devuelve una copia de `df` (no muta el original)."""
    cols_necesarias = {'FORMA DE CONTRATO', COL_TIPO_FACTURACION}
    if df.empty or not cols_necesarias.issubset(df.columns):
        return df

    df = df.copy()
    # astype(object) antes de asignar (24-09-2026): si TIPO DE FACTURACION
    # llega con dtype numerico puro (ej. una columna 100% NaN recien leida
    # de Excel, sin ningun texto todavia), pandas no deja escribir un string
    # directo ahi (LossySetitemError) -- object admite cualquier valor sin
    # perder los datos existentes.
    df[COL_TIPO_FACTURACION] = df[COL_TIPO_FACTURACION].astype(object)
    forma_norm = df['FORMA DE CONTRATO'].astype(str).str.strip().str.upper()
    tf_norm = df[COL_TIPO_FACTURACION].apply(lambda v: '' if pd.isna(v) else str(v).strip().upper())
    sin_asignar = tf_norm.isin(['', '-'])

    def _opcion_unica(forma):
        validos = FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(forma)
        if validos is not None and len(validos) == 1:
            return next(iter(validos))
        return None

    valor_a_forzar = forma_norm.map(_opcion_unica)
    mask = sin_asignar & valor_a_forzar.notna()
    df.loc[mask, COL_TIPO_FACTURACION] = valor_a_forzar[mask]
    return df


def construir_correcciones_tipo_facturacion(df):
    """{VIN: TIPO DE FACTURACION correcto} para las filas que
    detectar_inconsistencias_forma_contrato_tipo_facturacion marca, solo
    cuando la matriz tiene UNA única opción para su FORMA DE CONTRATO. Las
    de 2+ opciones (CONVERSION/VENTA) no se incluyen: no hay forma de saber
    cuál corresponde. FORMA DE CONTRATO manda, igual que en
    normalizar_tipo_facturacion_por_forma_contrato."""
    inconsistentes = detectar_inconsistencias_forma_contrato_tipo_facturacion(df)
    if inconsistentes.empty or 'VIN' not in inconsistentes.columns:
        return {}
    formas = inconsistentes['FORMA DE CONTRATO'].astype(str).str.strip().str.upper()
    vins = inconsistentes['VIN'].astype(str).str.strip().str.upper()
    correcciones = {}
    for vin, forma in zip(vins, formas):
        validos = FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(forma)
        if vin and vin != 'NAN' and validos is not None and len(validos) == 1:
            correcciones[vin] = next(iter(validos))
    return correcciones


def _calcular_etapa_gestion_esperada_vectorizado(df):
    """Version vectorizada de DataFrameFormatter.calcular_etapa_gestion_esperada(row),
    normalizada en mayúsculas (lista para comparar contra ETAPA GESTIÓN ya
    normalizada). Traduce las mismas 3 prioridades de esa función fila-por-fila,
    leyendo los mismos mapas/constantes (ESTADO_COMERCIAL_ACTIVACION_ETAPA_FLAT,
    VALOR_TIPO_FACT_SIN_REGISTRO, VALOR_TIPO_FACT_FACTURACION_MANUAL) para que
    un cambio en esos valores se refleje acá automáticamente -- lo único que
    se traduce a mano es la forma de la regla (3 prioridades), no los datos.

    Orden de prioridades reordenado (25-09-2026, a pedido explícito del
    usuario -- "la matriz de ESTADO COMERCIAL manda a todas las demás", ver
    el mismo cambio y su motivación en calcular_etapa_gestion_esperada):
    Prioridad 1: la matriz de 2 ejes (ESTADO COMERCIAL, ESTADO DE
    ACTIVACIÓN ACTUAL) -- vive en constants.py como diccionario anidado
    (ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ, usado por la versión
    fila-por-fila) y como su versión aplanada de un solo nivel
    (ESTADO_COMERCIAL_ACTIVACION_ETAPA_FLAT, con llaves "ESTADO||ACTIVACION"),
    pensada para un único .map() vectorizado sin tener que iterar -- gana
    siempre que la combinación esté definida, incluso sobre TIPO DE
    FACTURACION. Prioridad 2 (antes prioridad 1/2, ahora solo aplica cuando
    la matriz no definió nada para esa fila): TIPO DE FACTURACION SIN
    REGISTRO/FACTURACIÓN MANUAL -> COMERCIAL. Prioridad 3 (fallback final):
    se conserva ETAPA GESTIÓN actual.

    NO se reemplaza calcular_etapa_gestion_esperada(row) por un wrapper de
    esta función (como sí hace clasificar_fecha_termino() con
    clasificar_vigencia_contrato()) porque esa versión fila-por-fila también
    se usa en DataFrameFormatter.clean() y en comercial_agregar.py fuera del
    alcance de esta optimización -- ver conversación de la auditoría de
    rendimiento, fase 3, 21-09-2026. Si se agrega una prioridad nueva a la
    regla, hay que replicarla acá también; la equivalencia entre ambas
    versiones está cubierta por
    TestCalcularEtapaGestionEsperadaVectorizadoEquivaleARowWise."""
    if COL_TIPO_FACTURACION in df.columns:
        tipo_fact = df[COL_TIPO_FACTURACION].astype(str).str.strip().str.upper()
    else:
        tipo_fact = pd.Series('', index=df.index)

    if COL_ESTADO_COMERCIAL in df.columns:
        estado = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
    else:
        estado = pd.Series('', index=df.index)

    if COL_ESTADO_ACTIVACION in df.columns:
        activacion = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    else:
        activacion = pd.Series('', index=df.index)

    etapa_actual = df[COL_ETAPA_GESTION] if COL_ETAPA_GESTION in df.columns else pd.Series('', index=df.index)

    cond_sin_registro = tipo_fact.str.contains(VALOR_TIPO_FACT_SIN_REGISTRO, regex=False, na=False)
    cond_facturacion_manual = tipo_fact == VALOR_TIPO_FACT_FACTURACION_MANUAL

    clave_matriz = estado + '||' + activacion
    etapa_por_matriz = clave_matriz.map(ESTADO_COMERCIAL_ACTIVACION_ETAPA_FLAT)

    etapa_prioridad_2 = pd.Series('COMERCIAL', index=df.index).where(
        cond_sin_registro | cond_facturacion_manual, etapa_actual
    )
    etapa_esperada = etapa_por_matriz.where(etapa_por_matriz.notna(), etapa_prioridad_2)
    return etapa_esperada.astype(str).str.strip().str.upper()


COLUMNAS_LIMPIEZA_SIN_CONTRATO = [
    'TIPO DE SERVICIO', 'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO',
]


def aplica_regla_sin_contrato(col_name, new_value):
    """Regla de negocio confirmada (ver conversación con Javiera): cuando el
    usuario edita manualmente FORMA DE CONTRATO en Vista Completa y el nuevo
    valor es 'Sin Contrato', se deben limpiar a '-' TIPO DE SERVICIO,
    INICIO CONTRATO, DURACIÓN (MESES) y TÉRMINO CONTRATO de esa misma fila.

    Se dispara SOLO ante la edición explícita de FORMA DE CONTRATO (columna y
    valor nuevo ya resueltos por comercial.py::on_item_edited, incluyendo el
    caso de pegado vía paste_dropdown_value_to_selection). No se debe llamar
    al cargar/recalcular el DataFrame completo, y no hay regla inversa: pasar
    de 'Sin Contrato' a cualquier otro valor no reconstruye estos campos.

    Devuelve un dict {columna: '-'} a fusionar en pending_changes; {} si la
    edición no corresponde a este caso (no es FORMA DE CONTRATO, o el nuevo
    valor no es 'Sin Contrato')."""
    if col_name != 'FORMA DE CONTRATO':
        return {}
    if str(new_value).strip().upper() != 'SIN CONTRATO':
        return {}
    return {col: '-' for col in COLUMNAS_LIMPIEZA_SIN_CONTRATO}


def aplicar_cambios_pendientes(df, pending_changes):
    """Extraccion literal del patron duplicado (verificado identico) en
    ComercialModule.filter_table(), confirm_save() y _on_save_finished():
    aplica sobre `df` los cambios de `pending_changes`
    ({vin_key: {'cambios': {columna: valor, ...}}}), usando VIN como llave
    (normalizado a mayusculas/sin espacios al comparar). Si el cambio trae
    `ID` (y `df` tiene esa columna) se aplica solo a ese contrato, aunque el
    VIN esté repetido. Si un vin_key ya no existe en `df`, se ignora
    silenciosamente, igual que las tres implementaciones originales. Muta
    `df` in-place (mismo comportamiento previo) y lo retorna."""
    ids_df = None
    for vin_key, data in pending_changes.items():
        id_contrato = _normalizar_id_contrato(data.get('ID'))
        if id_contrato and 'ID' in df.columns:
            if ids_df is None:
                ids_df = _ids_normalizados(df)
            mask = ids_df == id_contrato
        else:
            mask = df['VIN'].astype(str).str.strip().str.upper() == vin_key
        if mask.any():
            for col, val in data['cambios'].items():
                if col in df.columns:
                    df[col] = df[col].astype(object)
                    df.loc[mask, col] = val
    return df


_MESES_ES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4, 'mayo': 5, 'junio': 6,
    'julio': 7, 'agosto': 8, 'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}


def _parsear_periodo_interno(valor):
    """Convierte un valor de PERIODO INTERNO (ej. 'agosto - 2022') en una
    tupla (año, mes) comparable. None si no tiene el formato esperado (ej.
    'NO APLICA' o vacío)."""
    partes = str(valor).strip().lower().split('-')
    if len(partes) != 2:
        return None
    mes = _MESES_ES.get(partes[0].strip())
    anio_txt = partes[1].strip()
    if mes is None or not anio_txt.isdigit():
        return None
    return (int(anio_txt), mes)


def _elegir_razon_social_ganadora(valores_en_orden, grupo, conteo, tiene_estado, tiene_periodo):
    """Desempate cuando dos o más RAZÓN SOCIAL de un mismo grupo RUT+CDB
    tienen la misma cantidad de unidades (empate revisado contra datos
    reales del CSV, 24-09-2026, a pedido explícito). Orden de criterios:
    1) más unidades; 2) si empatan, la que tenga alguna unidad CONECTADA;
    3) si ninguna está conectada, la que tenga algún ESTADO DE ACTIVACIÓN
    ACTUAL real (distinto de 'NO APLICA'); 4) la que tenga el PERIODO
    INTERNO más reciente; 5) como último recurso, la primera en orden de
    aparición, para que el resultado sea siempre determinístico."""
    max_conteo = conteo.max()
    candidatos = [v for v in valores_en_orden if conteo[v] == max_conteo]
    if len(candidatos) == 1:
        return candidatos[0]

    if tiene_estado:
        estados = grupo.groupby(COL_RAZON_SOCIAL)[COL_ESTADO_ACTIVACION].apply(
            lambda s: set(str(x).strip().upper() for x in s)
        )
        con_conectado = [v for v in candidatos if 'CONECTADO' in estados.get(v, set())]
        if con_conectado:
            candidatos = con_conectado
        else:
            con_estado_real = [v for v in candidatos if estados.get(v, set()) - {'NO APLICA', ''}]
            if con_estado_real:
                candidatos = con_estado_real
        if len(candidatos) == 1:
            return candidatos[0]

    if tiene_periodo:
        periodos = grupo.groupby(COL_RAZON_SOCIAL)[COL_PERIODO_INTERNO].apply(
            lambda s: max((p for p in (_parsear_periodo_interno(x) for x in s) if p), default=None)
        )
        con_periodo = [(v, periodos.get(v)) for v in candidatos if periodos.get(v) is not None]
        if con_periodo:
            periodo_mas_reciente = max(p for _, p in con_periodo)
            candidatos = [v for v, p in con_periodo if p == periodo_mas_reciente]
        if len(candidatos) == 1:
            return candidatos[0]

    return next(v for v in valores_en_orden if v in candidatos)


def detectar_grupos_razon_social_duplicada(df):
    """Agrupa `df` por (RUT, CDB) no vacíos y devuelve, para cada grupo con
    más de una RAZÓN SOCIAL distinta, un dict {razon_social_perdedora:
    razon_social_ganadora} -- la ganadora es la que tiene más filas (VIN) en
    ese grupo (mismo criterio que "Total unidades" en GeneralModule); ver
    _elegir_razon_social_ganadora para el criterio de desempate cuando hay
    empate en unidades. No modifica `df`. Usado tanto por el botón manual
    "Unificar Razón Social" (Vista General -> pestaña Duplicados) como por
    RMJaviSyncWorker (aplicado automáticamente en cada sincronización,
    23-09-2026, a pedido explícito) -- misma detección que
    GeneralModule._calcular_claves_duplicadas_rut_cdb, pero a nivel de fila
    (VIN) en vez de a nivel de cliente ya agrupado."""
    mapa = {}
    if df.empty or COL_RUT not in df.columns or COL_CDB not in df.columns or COL_RAZON_SOCIAL not in df.columns:
        return mapa

    columnas = [COL_RUT, COL_CDB, COL_RAZON_SOCIAL]
    tiene_estado = COL_ESTADO_ACTIVACION in df.columns
    tiene_periodo = COL_PERIODO_INTERNO in df.columns
    if tiene_estado:
        columnas.append(COL_ESTADO_ACTIVACION)
    if tiene_periodo:
        columnas.append(COL_PERIODO_INTERNO)

    aux = df[columnas].copy()
    # fillna: con los vacíos reales (NaN) astype(str) ya no los vuelve 'nan' y
    # terminaban como llave de grupo (KeyError: nan al contar razones sociales)
    for col in (COL_RUT, COL_CDB, COL_RAZON_SOCIAL):
        aux[col] = aux[col].fillna('').astype(str).str.strip()
    vacio_o_nan = lambda s: (s == '') | (s.str.lower() == 'nan')
    # '-' en RUT o CDB y "SIN RUT" son "sin dato": nunca agrupan clientes distintos
    sin_valor = lambda s: vacio_o_nan(s) | (s == '-') | (s.str.upper() == 'SIN RUT')
    aux = aux[~sin_valor(aux[COL_RUT]) & ~sin_valor(aux[COL_CDB]) & ~vacio_o_nan(aux[COL_RAZON_SOCIAL])]
    if aux.empty:
        return mapa

    for _, grupo in aux.groupby([COL_RUT, COL_CDB], sort=False):
        valores_en_orden = list(dict.fromkeys(grupo[COL_RAZON_SOCIAL]))
        if len(valores_en_orden) <= 1:
            continue
        conteo = grupo[COL_RAZON_SOCIAL].value_counts()
        ganadora = _elegir_razon_social_ganadora(valores_en_orden, grupo, conteo, tiene_estado, tiene_periodo)
        for perdedora in valores_en_orden:
            if perdedora != ganadora:
                mapa[perdedora] = ganadora

    # Filas sin CDB (05-10-2026): si su RUT tiene un único CDB en el resto de la
    # base y su razón social no aparece con CDB en ningún lado, es el mismo
    # cliente con otra grafía (ej. "MAXAM CHILE S.A." / "MAXAM CHILE SA") y se
    # unifica con la razón social ganadora de ese RUT. No se rellena el CDB.
    base = df[[COL_RUT, COL_CDB, COL_RAZON_SOCIAL]].copy()
    for col in base.columns:
        base[col] = base[col].fillna('').astype(str).str.strip()
    sin_dato = lambda s: s.isna() | vacio_o_nan(s) | (s == '-') | (s.str.upper() == 'SIN RUT')
    con_cdb = base[~sin_dato(base[COL_RUT]) & ~sin_dato(base[COL_CDB]) & ~sin_dato(base[COL_RAZON_SOCIAL])]
    sin_cdb = base[~sin_dato(base[COL_RUT]) & sin_dato(base[COL_CDB]) & ~sin_dato(base[COL_RAZON_SOCIAL])]
    cdb_por_rut = con_cdb.groupby(COL_RUT)[COL_CDB].nunique()
    ruts_con_un_cdb = set(cdb_por_rut[cdb_por_rut == 1].index)
    nombres_con_cdb = set(con_cdb[COL_RAZON_SOCIAL])
    candidatas = sin_cdb[sin_cdb[COL_RUT].isin(ruts_con_un_cdb)][[COL_RUT, COL_RAZON_SOCIAL]].drop_duplicates()
    for rut, nombre in candidatas.itertuples(index=False):
        if nombre in nombres_con_cdb or nombre in mapa:
            continue
        nombres_del_rut = con_cdb.loc[con_cdb[COL_RUT] == rut, COL_RAZON_SOCIAL].map(lambda n: mapa.get(n, n))
        mapa[nombre] = nombres_del_rut.value_counts().idxmax()
    return mapa


_RUT_SIN_DATO = {'', '-', 'NAN', 'NONE', '<NA>', 'SINRUT'}


def rut_llave(valor):
    """RUT normalizado (sin puntos, guion ni espacios, en mayúsculas) o ''
    si no hay un RUT utilizable ('', '-', 'SIN RUT', etc.)."""
    texto = re.sub(r'[\.\-\s]', '', str(valor).upper())
    return '' if texto in _RUT_SIN_DATO else texto


def clave_cliente(rut, razon_social):
    """Identidad de un cliente: su RUT normalizado; sin RUT utilizable, su
    razón social."""
    llave = rut_llave(rut)
    return f"RUT:{llave}" if llave else f"RS:{str(razon_social).strip()}"


def clave_cliente_serie(rut, razon_social):
    """Versión vectorizada de clave_cliente para dos Series alineadas."""
    r = rut.astype(str).str.upper().str.replace(r'[\.\-\s]', '', regex=True)
    sin_rut = r.isin(_RUT_SIN_DATO)
    return ('RUT:' + r).where(~sin_rut, 'RS:' + razon_social.astype(str).str.strip())


COLUMNAS_RESUMEN_CLIENTES = ["CLAVE", "RUT", "RAZÓN SOCIAL", "OTRAS RAZONES", "UNIDADES"]


def resumen_clientes(df):
    """Un cliente por fila (identidad por RUT; sin RUT utilizable, por razón
    social): su razón social más frecuente, las otras razones con las que
    aparece y su cantidad de unidades."""
    vacio = pd.DataFrame(columns=COLUMNAS_RESUMEN_CLIENTES)
    if df is None or df.empty or 'RUT' not in df.columns or 'RAZÓN SOCIAL' not in df.columns:
        return vacio
    razon = df['RAZÓN SOCIAL'].astype(str).str.strip()
    aux = pd.DataFrame({
        'clave': clave_cliente_serie(df['RUT'], razon),
        'rut': df['RUT'].astype(str).str.strip(),
        'razon': razon,
    })
    aux = aux[~aux['razon'].str.lower().isin(['', 'nan', 'none', '-']) & aux['clave'].notna()]
    # Una pasada sobre listas: value_counts por cliente tardaba ~0,3 ms por cliente
    conteos, ruts, unidades = {}, {}, {}
    for clave, rut, razon_txt in zip(aux['clave'].tolist(), aux['rut'].tolist(), aux['razon'].tolist()):
        conteo = conteos.setdefault(clave, {})
        if isinstance(razon_txt, str):
            conteo[razon_txt] = conteo.get(razon_txt, 0) + 1
        unidades[clave] = unidades.get(clave, 0) + 1
        if clave not in ruts and rut_llave(rut):
            ruts[clave] = rut
    filas = []
    for clave, conteo in conteos.items():
        if not conteo:
            continue
        razones = sorted(conteo, key=conteo.get, reverse=True)
        filas.append((clave, ruts.get(clave, 'Sin RUT'), razones[0], ', '.join(razones[1:]) or '-', unidades[clave]))
    return pd.DataFrame(filas, columns=COLUMNAS_RESUMEN_CLIENTES) if filas else vacio


def cambios_razon_social_cliente(df, clave, nueva_razon):
    """Lote {VIN: {'VIN', 'cambios'}} que deja `nueva_razon` en todas las
    filas del cliente `clave` que aún tengan otra razón social."""
    if df is None or df.empty or 'RUT' not in df.columns or 'RAZÓN SOCIAL' not in df.columns or 'VIN' not in df.columns:
        return {}
    nueva = str(nueva_razon).strip()
    razon = df['RAZÓN SOCIAL'].astype(str).str.strip()
    filas = df[(clave_cliente_serie(df['RUT'], razon) == clave) & (razon != nueva)]
    lote = {}
    for vin in filas['VIN'].astype(str):
        vin_limpio = vin.strip().upper()
        lote[vin_limpio] = {'VIN': vin_limpio, 'cambios': {'RAZÓN SOCIAL': nueva}}
    return lote


def razones_de_cliente(df, clave):
    """[(razón social, unidades)] del cliente `clave`, de mayor a menor."""
    if df is None or df.empty or 'RUT' not in df.columns or 'RAZÓN SOCIAL' not in df.columns:
        return []
    razon = df['RAZÓN SOCIAL'].astype(str).str.strip()
    conteo = razon[clave_cliente_serie(df['RUT'], razon) == clave].value_counts()
    return [(r, int(n)) for r, n in conteo.items()]


def cambios_rut_razon_cliente(df, clave, razon, nuevo_rut, nueva_razon=None):
    """Lote {VIN: {'VIN', 'cambios'}} que deja `nuevo_rut` en las filas del
    cliente `clave` con esa razón social (y `nueva_razon`, si se indica). Si
    el RUT ya existe en otras filas se reutiliza su formato de texto."""
    if df is None or df.empty or not all(c in df.columns for c in ('RUT', 'RAZÓN SOCIAL', 'VIN')):
        return {}
    llave = rut_llave(nuevo_rut)
    if not llave:
        return {}
    existentes = df['RUT'].astype(str).str.strip()
    coincide = existentes[existentes.map(rut_llave) == llave]
    rut_txt = coincide.iloc[0] if not coincide.empty else llave
    razon_serie = df['RAZÓN SOCIAL'].astype(str).str.strip()
    filas = df[(clave_cliente_serie(df['RUT'], razon_serie) == clave) & (razon_serie == str(razon).strip())]
    lote = {}
    for vin in filas['VIN'].astype(str):
        vin_limpio = vin.strip().upper()
        cambios = {'RUT': rut_txt}
        if nueva_razon:
            cambios['RAZÓN SOCIAL'] = str(nueva_razon).strip()
        lote[vin_limpio] = {'VIN': vin_limpio, 'cambios': cambios}
    return lote


def _cdb_serie(df):
    """CDB como texto; '-' donde falta (vacío, nan o none)."""
    texto = df['CDB'].fillna('').astype(str).str.strip()
    return texto.where(~texto.str.lower().isin(['', 'nan', 'none']), '-')


def cdbs_por_cliente(df):
    """{clave de cliente: [(CDB, unidades)]}, de mayor a menor y con '-' (unidades
    sin CDB) al final. Pensado para recibir los contratos actuales."""
    if df is None or df.empty or not all(c in df.columns for c in ('RUT', 'RAZÓN SOCIAL', 'CDB')):
        return {}
    razon = df['RAZÓN SOCIAL'].astype(str).str.strip()
    claves = clave_cliente_serie(df['RUT'], razon)
    con_nombre = ~razon.str.lower().isin(['', 'nan', 'none', '-'])
    conteos = {}
    for clave, cdb in zip(claves[con_nombre].tolist(), _cdb_serie(df)[con_nombre].tolist()):
        conteo = conteos.setdefault(clave, {})
        conteo[cdb] = conteo.get(cdb, 0) + 1
    return {clave: sorted(conteo.items(), key=lambda kv: (kv[0] == '-', -kv[1])) for clave, conteo in conteos.items()}


def cambios_cdb_cliente(df, clave, cdb_origen, nuevo_cdb):
    """Lote {VIN: {'VIN', 'cambios'}} que deja `nuevo_cdb` (1 a 10 dígitos) en
    las unidades del cliente `clave` que tengan otro CDB. Con `cdb_origen`
    ('-' para las que no tienen), solo las que hoy tienen ese CDB."""
    if df is None or df.empty or not all(c in df.columns for c in ('RUT', 'RAZÓN SOCIAL', 'CDB', 'VIN')):
        return {}
    nuevo = str(nuevo_cdb).strip()
    if not re.fullmatch(r'\d{1,10}', nuevo):
        return {}
    razon = df['RAZÓN SOCIAL'].astype(str).str.strip()
    cdb = _cdb_serie(df)
    mascara = (clave_cliente_serie(df['RUT'], razon) == clave) & (cdb != nuevo)
    if cdb_origen is not None:
        mascara &= cdb == cdb_origen
    lote = {}
    for vin in df.loc[mascara, 'VIN'].astype(str):
        vin_limpio = vin.strip().upper()
        lote[vin_limpio] = {'VIN': vin_limpio, 'cambios': {'CDB': nuevo}}
    return lote


def unificar_razon_social_duplicada(df):
    """Aplica detectar_grupos_razon_social_duplicada sobre `df` y reemplaza
    en la columna RAZÓN SOCIAL cada nombre perdedor por el ganador de su
    grupo (mismo RUT+CDB). Devuelve (df_resultado, mapa_aplicado) -- mapa
    vacío si no había nada que unificar. No muta `df` (trabaja sobre una
    copia); si no hay nada que unificar devuelve el mismo `df` recibido, sin
    copiarlo innecesariamente."""
    mapa = detectar_grupos_razon_social_duplicada(df)
    if not mapa:
        return df, {}
    df = df.copy()
    df[COL_RAZON_SOCIAL] = df[COL_RAZON_SOCIAL].astype(str).str.strip().replace(mapa)
    return df, mapa
