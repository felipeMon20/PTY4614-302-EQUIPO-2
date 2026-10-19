"""Logica de negocio de Operaciones. Python/pandas puro: no depende de
PyQt6, QThread, QWidget, QMessageBox ni ningun widget.

Reglas confirmadas con el usuario (conversacion 21-09-2026, segunda ronda;
rediseño de Activaciones/Conectividad/Sin Flota, 24-09-2026):
- Activaciones: unidades con ESTADO DE ACTIVACION ACTUAL en Activando, No
  entregado o Desconectado (este ultimo agregado 24-09-2026, ver
  filtrar_activaciones). Sin condicion sobre ESTADO COMERCIAL -- esto incluye tanto las
  unidades "normales" en proceso de activacion como el caso que antes vivia
  en la pestaña "Conectividad" (ESTADO COMERCIAL=Vigente + ACTIVANDO: un
  camion con contrato vigente que deberia estar funcionando pero presenta
  un problema operacional). La pestaña "Conectividad" se elimino: ese caso
  ya estaba, y sigue estando, dentro de Activaciones (24-09-2026, a pedido
  explicito, confirmado con datos reales: las 82 unidades Vigente+Activando
  del CSV de produccion ya aparecian aca antes del rediseño).
- Sin Flota (24-09-2026, reemplaza el valor SIN FLOTA dentro de Activaciones
  por una pestaña propia): ESTADO COMERCIAL = Activacion Pendiente Y ESTADO
  DE ACTIVACION ACTUAL = Sin Flota. Unidades que todavia no aparecen en
  Servicios Conectados -- se sacan de Activaciones (antes SIN FLOTA era uno de los
  tres valores elegibles ahi) para que cada unidad viva en una sola cola, a
  pedido explicito. Ver filtrar_sin_flota() sobre el alias con/sin tilde de
  "Activación Pendiente".
- Bajas: TERMINO CONTRATO vencido O por vencer (<=30 dias, misma regla que
  Renovaciones de Comercial -- ver clasificar_vigencia_contrato().
  es_renovacion, ajustado 22-09-2026) Y ESTADO DE ACTIVACION ACTUAL =
  Conectado Y ETAPA GESTION = Operaciones -- unidades cuyo contrato ya
  termino o esta por terminar, pero que la app todavia no ha marcado como
  desconectadas.

Nota sobre la condicion "ETAPA GESTION = Operaciones" en Bajas: ETAPA
GESTION se recalcula automaticamente en cada carga/sincronizacion
(DataFrameFormatter.calcular_etapa_gestion_esperada). Confirmado
explicitamente con el usuario que se deja la condicion tal cual.

Nuevo (23-09-2026) -- ciclo de baja anticipada (Comercial "Vigentes" ->
Operaciones "Bajas" -> Comercial): un camion Vigente puede darse de baja
antes de su TERMINO CONTRATO (siniestro u otro problema, confirmado con el
usuario). Ese caso no pasa por "Enviar a operaciones" con ESTADO COMERCIAL =
BAJA directo, sino BAJA SOLICITADA (ver comercial.py::
_on_accion_enviar_operaciones_clicked), y no cumple la condicion de fecha de
filtrar_bajas (el contrato no esta vencido ni por vencer). filtrar_bajas
incluye entonces un OR explicito para BAJA SOLICITADA, independiente de la
fecha de termino."""

import pandas as pd
from datetime import date

from src.core.constants import (COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_ETAPA_GESTION,
                                COL_CDB_FLOTA, COL_RAZON_SOCIAL, COL_EJECUTIVO, COL_VIN, COL_TIPO_FACTURACION,
                                COL_FECHA_BAJA, COL_FLOTA_VC, ESTADO_ACTIVANDO, ESTADO_NO_ENTREGADO,
                                ESTADO_SIN_FLOTA, ESTADO_CONECTADO, ESTADO_DESCONECTADO,
                                VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA,
                                VALOR_ESTADO_COMERCIAL_VIGENTE, VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE,
                                VALOR_ETAPA_GESTION_OPERACIONES)
from src.core.dataframe_formatter import DataFrameFormatter
from src.services.comercial_services import clasificar_vigencia_contrato, es_contrato_cerrado

def filtrar_activaciones(df):
    """Panel Operaciones -> Activaciones. Ver docstring del modulo.

    Alineado con ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ (constants.py,
    la matriz de negocio confirmada con la contraparte comercial, 24-09-2026): además de
    ESTADO DE ACTIVACIÓN ACTUAL en {Activando, No entregado, Desconectado},
    exige ETAPA GESTIÓN = Operaciones -- sin esta segunda condición,
    combinaciones que la matriz manda a COMERCIAL (ej. VENCIDO+Activando,
    BAJA+No entregado) seguían apareciendo aquí igual. ETAPA GESTIÓN es la
    misma columna que ya recalcula DataFrameFormatter en cada carga/
    sincronización y que "Marcar como CONECTADO"/"Marcar como SIN FLOTA"
    recalculan al guardar (ver calcular_cambios_marcar_conectado/
    calcular_cambios_marcar_sin_flota), así que no hace falta reimplementar
    la regla de la matriz aquí.

    Desconectado agregado (24-09-2026, pedido explícito del usuario): le
    pasa a Vigente y Activación Pendiente (ambas usan
    _FILA_OPERACIONES_SALVO_CONECTADO, que manda Desconectado a
    OPERACIONES) y no tenía ninguna cola en Operaciones. Como ESTADO
    COMERCIAL manda, se resuelve igual que Activando/No entregado: la
    unidad cae en Activaciones y se corrige con "Marcar como CONECTADO"
    (que ya fuerza ESTADO COMERCIAL -> Vigente, ver
    calcular_cambios_marcar_conectado) -- no hace falta una cola nueva."""
    if df.empty or COL_ESTADO_ACTIVACION not in df.columns or COL_ETAPA_GESTION not in df.columns:
        return df.iloc[0:0]

    estado_activacion = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    etapa_gestion = df[COL_ETAPA_GESTION].astype(str).str.strip().str.upper()
    mask = estado_activacion.isin({ESTADO_ACTIVANDO, ESTADO_NO_ENTREGADO, ESTADO_DESCONECTADO}) & \
        (etapa_gestion == VALOR_ETAPA_GESTION_OPERACIONES)
    # Desde el 15-10-2026 la sincronización RM_CONTRATOS convierte No entregado en
    # Sin flota; aquí se conserva solo para datos anteriores. Una baja con
    # Activando va a Bajas.
    if COL_ESTADO_COMERCIAL in df.columns:
        estado_com = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
        mask = mask & ~estado_com.isin({VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA})
    return df[mask]


def filtrar_sin_flota(df):
    """Panel Operaciones -> Sin Flota (24-09-2026, ver docstring del
    modulo). Alineado con ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ: ESTADO
    DE ACTIVACIÓN ACTUAL = Sin Flota Y ETAPA GESTIÓN = Operaciones -- la
    matriz solo produce OPERACIONES para SIN FLOTA cuando ESTADO COMERCIAL
    es Activación Pendiente o Vigente (las demás filas dan COMERCIAL), así
    que usar ETAPA GESTIÓN en vez de comparar ESTADO COMERCIAL a mano cubre
    ambos casos automáticamente y evita que una unidad quede sin cola
    visible en Operaciones (riesgo detectado 24-09-2026: Vigente+Activando
    -> "Marcar como SIN FLOTA" -> Vigente+Sin Flota, que antes no calzaba
    en ningún filtro)."""
    if df.empty or COL_ESTADO_ACTIVACION not in df.columns or COL_ETAPA_GESTION not in df.columns:
        return df.iloc[0:0]

    estado_activacion = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    etapa_gestion = df[COL_ETAPA_GESTION].astype(str).str.strip().str.upper()
    mask = (estado_activacion == ESTADO_SIN_FLOTA) & (etapa_gestion == VALOR_ETAPA_GESTION_OPERACIONES)
    return df[mask]


def filtrar_conectados_vigentes(df):
    """Panel Operaciones -> Datos de flota: todos los contratos Vigentes cuya
    unidad está Conectada. Operaciones revisa y corrige FLOTA VC y CDB FLOTA
    directo en la tabla; los que tienen alguno vacío se obtienen con
    filtrar_conectados_sin_flota_vc."""
    if df.empty or COL_ESTADO_COMERCIAL not in df.columns or COL_ESTADO_ACTIVACION not in df.columns:
        return df.iloc[0:0]
    estado_comercial = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
    estado_activacion = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    return df[(estado_comercial == VALOR_ESTADO_COMERCIAL_VIGENTE.upper()) & (estado_activacion == ESTADO_CONECTADO)]


# FLOTA VC que no corresponde a una flota real de Servicios Conectados: "NO EXISTE EN VC" (la
# unidad no está en VC, típico de "No aplica") y "SIN FLOTA" (aún sin asignar).
FLOTAS_VC_NO_REALES = {'SIN FLOTA', 'NO EXISTE EN VC'}


def filtrar_conectados_sin_flota_vc(df):
    """Panel Operaciones -> Datos de flota: contratos Vigentes y Conectados a los
    que les falta FLOTA VC o CDB FLOTA. Ya están funcionando, así que no pasan por
    Activaciones ni Sin Flota; Operaciones completa los datos para regularizarlos."""
    if df.empty or COL_ESTADO_COMERCIAL not in df.columns or COL_ESTADO_ACTIVACION not in df.columns \
            or COL_FLOTA_VC not in df.columns or COL_CDB_FLOTA not in df.columns:
        return df.iloc[0:0]

    estado_comercial = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
    estado_activacion = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    mask = (estado_comercial == VALOR_ESTADO_COMERCIAL_VIGENTE.upper()) \
        & (estado_activacion == ESTADO_CONECTADO) & mascara_flota_pendiente(df)
    return df[mask]


def mascara_flota_pendiente(df):
    """Filas con FLOTA VC o CDB FLOTA faltante ('', '-', 'nan', 'SIN FLOTA' o
    'NO EXISTE EN VC' en la flota). Sin esas columnas no marca ninguna."""
    if df.empty or COL_FLOTA_VC not in df.columns or COL_CDB_FLOTA not in df.columns:
        return pd.Series(False, index=df.index)
    vacios = {'', 'NAN', 'NONE', '-', 'NAT'}
    sin_flota_vc = df[COL_FLOTA_VC].astype(str).str.strip().str.upper().isin(vacios | FLOTAS_VC_NO_REALES)
    sin_cdb_flota = df[COL_CDB_FLOTA].astype(str).str.strip().str.upper().isin(vacios)
    return sin_flota_vc | sin_cdb_flota


def construir_mapa_flota_por_cdb(df):
    """CDB (mayusculas) -> lista ordenada de FLOTA VC ya asociadas a ese CDB
    en `df`. Usado por Operaciones -> Sin Flota para sugerir FLOTA VC en
    cuanto el consultor de operaciones ingresa un CDB ya conocido (24-09-2026, a pedido explicito);
    mismo criterio que ComercialAgregarDialog._construir_lookups
    (flota_by_cdb), reimplementado aqui como funcion pura en vez de
    importar un metodo privado de un QDialog. CDB sin FLOTA VC asociada, o
    df vacio/sin esas columnas, devuelve un mapa vacio -- quien llama debe
    tratar "sin CDB" como "sin sugerencias", no como "todas las flotas"."""
    if df.empty or COL_CDB_FLOTA not in df.columns or COL_FLOTA_VC not in df.columns:
        return {}

    aux = df[[COL_CDB_FLOTA, COL_FLOTA_VC]].astype(str).apply(lambda s: s.str.strip())
    aux = aux[(aux[COL_CDB_FLOTA] != "") & (aux[COL_FLOTA_VC] != "") & ~aux[COL_FLOTA_VC].str.upper().isin(FLOTAS_VC_NO_REALES)]
    if aux.empty:
        return {}

    mapa = {}
    for cdb_key, grupo in aux.groupby(aux[COL_CDB_FLOTA].str.upper()):
        mapa[cdb_key] = sorted({v for v in grupo[COL_FLOTA_VC] if v})
    return mapa


def filtrar_bajas(df):
    """Panel Operaciones -> Bajas. Ver docstring del modulo. Reutiliza
    clasificar_vigencia_contrato (misma fuente que los KPI y Renovaciones de
    Comercial) para la condicion de fecha, en vez de reimplementar el
    parseo de fechas.

    Condicion de fecha (22-09-2026, ajustada a pedido explicito): vencido O
    por vencer dentro de 30 dias calendario (mismo 'es_renovacion' que ya
    usa Comercial -> Renovaciones), no solo estrictamente vencido. Antes una
    unidad enviada desde Renovaciones con "Enviar a operaciones" (Comercial
    -> ESTADO COMERCIAL=BAJA, ETAPA GESTION=OPERACIONES) quedaba visible en
    Comercial -> Gestionar Bajas pero invisible aca hasta que el contrato
    vencia de verdad; con el OR, Operaciones ve la unidad de inmediato.

    Baja anticipada (23-09-2026): una unidad enviada desde Comercial ->
    Vigentes queda en ESTADO COMERCIAL = BAJA SOLICITADA (ver
    comercial.py::_on_accion_enviar_operaciones_clicked), sin que su
    TÉRMINO CONTRATO este vencido ni por vencer -- es_renovacion no la
    captura. Se agrega como condicion alternativa, independiente de la
    fecha de termino.

    Ampliado (25-09-2026, a pedido explícito, corrección de bug real):
    ESTADO COMERCIAL = BAJA (no solo BAJA SOLICITADA) también bypasea la
    condición de fecha. Antes una unidad enviada a Baja con TÉRMINO
    CONTRATO='MENSUAL' o sin TÉRMINO CONTRATO ('-') nunca calzaba con
    es_renovacion (esas condiciones nunca "vencen" por diseño), así que
    aunque Comercial ya hubiera decidido la baja, la unidad se quedaba sin
    aparecer nunca en esta cola -- Operaciones no se enteraba de que debía
    desconectarla. Si Comercial ya marcó BAJA, la decisión ya está tomada:
    no debería depender de si el contrato tiene fecha de término o no."""
    if df.empty or 'TÉRMINO CONTRATO' not in df.columns or \
       COL_ESTADO_COMERCIAL not in df.columns or \
       COL_ESTADO_ACTIVACION not in df.columns or COL_ETAPA_GESTION not in df.columns:
        return df.iloc[0:0]

    es_renovacion = clasificar_vigencia_contrato(df)['es_renovacion']
    estado_comercial = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
    estado_activacion = df[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper()
    etapa_gestion = df[COL_ETAPA_GESTION].astype(str).str.strip().str.upper()

    es_baja_ya_decidida = estado_comercial.isin(
        {VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA}
    )
    conectada = (estado_activacion == ESTADO_CONECTADO) & (es_renovacion | es_baja_ya_decidida)
    # Matriz de destino: una baja con Activando también es de Bajas.
    activando_en_baja = (estado_activacion == ESTADO_ACTIVANDO) & es_baja_ya_decidida
    mask = (conectada | activando_en_baja) & (etapa_gestion == VALOR_ETAPA_GESTION_OPERACIONES)
    return df[mask]


def separar_vins_contrato_abierto(cola, vins):
    """(abiertos, cerrados): de `vins`, los que tienen un contrato actual abierto
    en `cola` y los que lo tienen en Baja o Baja Solicitada. Conectar o marcar
    Sin Flota solo corresponde a contratos abiertos; sobre uno finalizado la
    única acción de Operaciones es desconectar."""
    if cola is None or cola.empty or COL_VIN not in cola.columns or COL_ESTADO_COMERCIAL not in cola.columns:
        return list(vins), []
    cerrados_cola = {
        str(v).strip().upper()
        for v, estado in zip(cola[COL_VIN], cola[COL_ESTADO_COMERCIAL]) if es_contrato_cerrado(estado)
    }
    abiertos = [v for v in vins if str(v).strip().upper() not in cerrados_cola]
    cerrados = [v for v in vins if str(v).strip().upper() in cerrados_cola]
    return abiertos, cerrados


def calcular_cambios_marcar_desconectado(fila):
    """Cambios a aplicar cuando Operaciones -> Bajas marca una unidad como
    DESCONECTADO (22-09-2026, cierre del ciclo Comercial -> Operaciones ->
    Comercial para BAJA, ver conversación con el usuario): ESTADO DE
    ACTIVACIÓN ACTUAL -> Desconectado, y ETAPA GESTIÓN recalculada con la
    única fuente de verdad de esa regla (DataFrameFormatter.
    calcular_etapa_gestion_esperada, misma matriz que usa el resto de la
    app) en vez de una regla aparte.

    `fila` es un dict-like (fila de DataFrame o dict plano) con al menos
    ESTADO COMERCIAL/TIPO DE FACTURACION/ETAPA GESTIÓN vigentes de esa
    unidad. Esta función es pura y no decide elegibilidad: quien la llama
    (operaciones.py) es responsable de invocarla solo para unidades con
    ESTADO COMERCIAL en (BAJA, BAJA SOLICITADA) -- ver
    _obtener_vins_baja_seleccionados en operaciones.py.

    Nuevo (23-09-2026, confirmado con el usuario):
    - FECHA DE BAJA se autocompleta siempre con la fecha de hoy (DD-MM-YYYY,
      mismo formato que valida el resto de la app -- ver docs "Validación de
      Fechas de Baja"), sin importar el origen de la unidad.
    - Si la unidad llegaba como BAJA SOLICITADA (ciclo de baja anticipada,
      Comercial -> Vigentes -> "Enviar a operaciones"), ESTADO COMERCIAL se
      promueve a BAJA: esta acción es la confirmación real de la baja. Si ya
      era BAJA, queda igual (idempotente)."""
    estado_comercial_actual = fila.get(COL_ESTADO_COMERCIAL, '')
    nuevo_estado_comercial = (
        VALOR_ESTADO_COMERCIAL_BAJA
        if str(estado_comercial_actual).strip().upper() == VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA
        else estado_comercial_actual
    )
    nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: nuevo_estado_comercial,
        COL_ESTADO_ACTIVACION: ESTADO_DESCONECTADO,
        COL_TIPO_FACTURACION: fila.get(COL_TIPO_FACTURACION, ''),
        COL_ETAPA_GESTION: fila.get(COL_ETAPA_GESTION, ''),
    })
    return {
        COL_ESTADO_COMERCIAL: nuevo_estado_comercial,
        COL_ESTADO_ACTIVACION: ESTADO_DESCONECTADO,
        COL_ETAPA_GESTION: nueva_etapa,
        COL_FECHA_BAJA: date.today().strftime('%d-%m-%Y'),
    }


def calcular_cambios_marcar_conectado(fila, cdb=None, flota_vc=None):
    """Cambios a aplicar cuando Operaciones (Activaciones o Sin Flota)
    marca una unidad como CONECTADO (24-09-2026, alineado con
    ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ -- ver riesgo detectado el
    mismo día: sin recalcular ETAPA GESTIÓN aquí, quedaba un valor
    transitorio inconsistente con la matriz hasta la próxima carga real).
    ESTADO DE ACTIVACIÓN ACTUAL -> Conectado, ESTADO COMERCIAL -> Vigente
    (cierra el ciclo de reactivación Comercial "Gestionar Bajas" ->
    Operaciones, 22-09-2026), y ETAPA GESTIÓN recalculada con la misma
    matriz (DataFrameFormatter.calcular_etapa_gestion_esperada) sobre el
    estado ya actualizado -- mismo patrón que
    calcular_cambios_marcar_desconectado. Si `cdb`/`flota_vc` vienen
    informados (obligatorios desde Sin Flota, ver operaciones.py), se
    incluyen también en el resultado para guardarse en la misma
    operación."""
    nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: 'Vigente',
        COL_ESTADO_ACTIVACION: ESTADO_CONECTADO,
        COL_TIPO_FACTURACION: fila.get(COL_TIPO_FACTURACION, ''),
        COL_ETAPA_GESTION: fila.get(COL_ETAPA_GESTION, ''),
    })
    cambios = {
        COL_ESTADO_COMERCIAL: 'Vigente',
        COL_ESTADO_ACTIVACION: ESTADO_CONECTADO,
        COL_ETAPA_GESTION: nueva_etapa,
    }
    if cdb is not None:
        cambios[COL_CDB_FLOTA] = cdb
    if flota_vc is not None:
        cambios[COL_FLOTA_VC] = flota_vc
    return cambios


FLOTA_VC_NO_EXISTE = "NO EXISTE EN VC"


def construir_cambios_propagar_flota(df, flota_por_cdb, excluir_vins=()):
    """Lote que completa FLOTA VC en las unidades de `df` que tienen un CDB
    FLOTA de `flota_por_cdb` ({cdb: flota}) y no tienen Flota VC (vacía o
    "-"). No toca las que ya tienen una flota ni las marcadas "NO EXISTE EN
    VC", ni las de `excluir_vins`."""
    lote = {}
    if df is None or df.empty or COL_CDB_FLOTA not in df.columns or COL_FLOTA_VC not in df.columns or not flota_por_cdb:
        return lote
    flotas = {str(c).strip().upper(): f for c, f in flota_por_cdb.items() if str(c).strip() and str(f).strip()}
    excluidos = {str(v).strip().upper() for v in excluir_vins}
    cdbs = df[COL_CDB_FLOTA].astype(str).str.strip().str.replace(r'\.0$', '', regex=True).str.upper()
    sin_flota = df[COL_FLOTA_VC].astype(str).str.strip().str.upper().isin(['', '-', 'NAN', 'NONE', 'NAT'])
    for vin, cdb in zip(df.loc[sin_flota, COL_VIN], cdbs[sin_flota]):
        clave = str(vin).strip().upper()
        if clave and clave not in excluidos and cdb in flotas:
            lote[clave] = {'VIN': str(vin).strip(), 'cambios': {COL_FLOTA_VC: flotas[cdb]}}
    return lote


def calcular_cambios_marcar_sin_flota(fila, cdb=None, flota_vc=None):
    """Cambios a aplicar cuando Operaciones -> Activaciones marca una
    unidad como SIN FLOTA (24-09-2026, ver calcular_cambios_marcar_
    conectado): ESTADO DE ACTIVACIÓN ACTUAL -> Sin Flota (no toca ESTADO
    COMERCIAL) y ETAPA GESTIÓN recalculada con la matriz de negocio sobre
    el estado ya actualizado -- así una unidad cuyo ESTADO COMERCIAL no da
    OPERACIONES para SIN FLOTA (ver ESTADO_COMERCIAL_ACTIVACION_ETAPA_
    MATRIZ: solo Activación Pendiente y Vigente lo hacen) queda con ETAPA
    GESTIÓN=COMERCIAL de inmediato, en vez de un valor transitorio.
    `cdb`/`flota_vc` (24-09-2026, edición directa de celda en Activaciones,
    ver operaciones.py): si vienen informados se incluyen también en el
    resultado, para guardar en la misma operación una corrección hecha en
    la tabla antes de marcar la unidad."""
    nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: fila.get(COL_ESTADO_COMERCIAL, ''),
        COL_ESTADO_ACTIVACION: ESTADO_SIN_FLOTA,
        COL_TIPO_FACTURACION: fila.get(COL_TIPO_FACTURACION, ''),
        COL_ETAPA_GESTION: fila.get(COL_ETAPA_GESTION, ''),
    })
    cambios = {
        COL_ESTADO_ACTIVACION: ESTADO_SIN_FLOTA,
        COL_ETAPA_GESTION: nueva_etapa,
    }
    if cdb is not None:
        cambios[COL_CDB_FLOTA] = cdb
    flota_actual = flota_vc if flota_vc is not None else fila.get(COL_FLOTA_VC, '')
    if str(flota_actual).strip().upper() in ('', '-', 'NAN', 'NONE', 'NAT'):
        flota_vc = FLOTA_VC_NO_EXISTE
    if flota_vc is not None:
        cambios[COL_FLOTA_VC] = flota_vc
    return cambios


_COLUMNAS_EXPORT_CONTACTOS = [
    COL_CDB_FLOTA, COL_RAZON_SOCIAL, COL_EJECUTIVO, 'VINES PENDIENTES',
    'NOMBRE CONTACTO', 'APELLIDOS CONTACTO', 'CORREO CONTACTO', 'TELÉFONO CONTACTO',
]


def armar_export_contactos_ejecutivo(df_unidades, df_contactos):
    """Cruza las unidades de Activaciones (agrupadas por CDB) con sus
    contactos registrados en Contactos.xlsx (cruce por CDB, igual que hace
    contactos.py), para que un ejecutivo reciba en un solo Excel el listado
    de clientes pendientes y a quien contactar. Si un CDB no tiene ningun
    contacto registrado, igual aparece una fila (con los campos de contacto
    vacios) para que quede visible que falta gestionarlo -- no se omite la
    fila silenciosamente."""
    if df_unidades.empty or COL_CDB_FLOTA not in df_unidades.columns:
        return pd.DataFrame(columns=_COLUMNAS_EXPORT_CONTACTOS)

    df_unidades = df_unidades.copy()
    df_unidades[COL_CDB_FLOTA] = df_unidades[COL_CDB_FLOTA].astype(str).str.strip()

    agg = {COL_VIN: lambda vins: ', '.join(sorted({str(v).strip() for v in vins}))}
    if COL_RAZON_SOCIAL in df_unidades.columns:
        agg[COL_RAZON_SOCIAL] = 'first'
    if COL_EJECUTIVO in df_unidades.columns:
        agg[COL_EJECUTIVO] = 'first'
    resumen = df_unidades.groupby(COL_CDB_FLOTA).agg(agg).reset_index()
    resumen = resumen.rename(columns={COL_VIN: 'VINES PENDIENTES'})

    contactos_por_cdb = {}
    if not df_contactos.empty and 'CDB' in df_contactos.columns:
        df_contactos = df_contactos.copy()
        df_contactos['CDB'] = df_contactos['CDB'].astype(str).str.strip()
        for cdb, grupo in df_contactos.groupby('CDB'):
            contactos_por_cdb[cdb] = grupo

    filas = []
    for _, cliente in resumen.iterrows():
        base = {
            COL_CDB_FLOTA: cliente.get(COL_CDB_FLOTA, ''),
            COL_RAZON_SOCIAL: cliente.get(COL_RAZON_SOCIAL, ''),
            COL_EJECUTIVO: cliente.get(COL_EJECUTIVO, ''),
            'VINES PENDIENTES': cliente.get('VINES PENDIENTES', ''),
        }
        contactos = contactos_por_cdb.get(str(cliente.get(COL_CDB_FLOTA, '')).strip())
        if contactos is None or contactos.empty:
            filas.append({**base, 'NOMBRE CONTACTO': '', 'APELLIDOS CONTACTO': '',
                          'CORREO CONTACTO': '', 'TELÉFONO CONTACTO': ''})
        else:
            for _, contacto in contactos.iterrows():
                filas.append({
                    **base,
                    'NOMBRE CONTACTO': contacto.get('Nombre', ''),
                    'APELLIDOS CONTACTO': contacto.get('Apellidos', ''),
                    'CORREO CONTACTO': contacto.get('Correo electrónico', ''),
                    'TELÉFONO CONTACTO': contacto.get('Número móvil', ''),
                })

    return pd.DataFrame(filas, columns=_COLUMNAS_EXPORT_CONTACTOS)


# =========================================================
# KPI POR SUB-PESTAÑA (25-09-2026, a pedido explícito: las 4 tarjetas de
# calcular_kpis_vigencia() se calculaban sobre df_master completo, sin
# relación con la sub-pestaña activa ni con la regla de negocio real de
# cada una -- ver docs/07 §"Módulo de Operaciones" y la investigación
# previa en el chat). Cada función recibe la cola YA filtrada
# (_FILTROS_POR_TAB de operaciones.py, self._cola_full[idx]) y devuelve
# solo las claves que esa sub-pestaña usa -- ver _KPI_SPECS en operaciones.py.
# =========================================================
def calcular_kpis_activaciones(df):
    """"Activaciones": desglose por ESTADO DE ACTIVACIÓN ACTUAL (Activando
    vs No entregado) y cuántas son el caso "Vigente + Activando" (ex-
    pestaña "Conectividad", ver docstring del módulo) -- contrato vigente
    con un problema operacional, el caso de mayor urgencia dentro de esta
    cola."""
    if df.empty:
        return {"total": 0, "activando": 0, "no_entregado": 0, "vigente_activando": 0}
    estado_activ = df.get(COL_ESTADO_ACTIVACION, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    estado_com = df.get(COL_ESTADO_COMERCIAL, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    vigente_activando = (estado_com == VALOR_ESTADO_COMERCIAL_VIGENTE) & (estado_activ == ESTADO_ACTIVANDO)
    return {
        "total": len(df),
        "activando": int((estado_activ == ESTADO_ACTIVANDO).sum()),
        "no_entregado": int((estado_activ == ESTADO_NO_ENTREGADO).sum()),
        "vigente_activando": int(vigente_activando.sum()),
    }


def calcular_kpis_sin_flota(df):
    """"Sin Flota": cuántas unidades ya tienen CDB y FLOTA VC completos
    (listas para "Marcar como CONECTADO" de inmediato) vs a cuántas les
    falta el dato, y el desglose por ESTADO COMERCIAL (Activación
    Pendiente vs Vigente, los únicos dos que la matriz manda a Operaciones
    para SIN FLOTA -- ver ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ)."""
    if df.empty:
        return {"total": 0, "listas": 0, "pendientes_datos": 0, "activacion_pendiente": 0}
    cdb = df.get(COL_CDB_FLOTA, pd.Series(dtype=str)).astype(str).str.strip()
    flota_vc = df.get(COL_FLOTA_VC, pd.Series(dtype=str)).astype(str).str.strip()
    listas = (cdb != '') & (cdb.str.upper() != 'NAN') & (flota_vc != '') & ~flota_vc.str.upper().isin({'NAN'} | FLOTAS_VC_NO_REALES)
    estado_com = df.get(COL_ESTADO_COMERCIAL, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    return {
        "total": len(df),
        "listas": int(listas.sum()),
        "pendientes_datos": int((~listas).sum()),
        "activacion_pendiente": int((estado_com == VALOR_ESTADO_COMERCIAL_ACTIVACION_PENDIENTE).sum()),
    }


def calcular_kpis_bajas(df):
    """"Bajas": desglose por ESTADO COMERCIAL (Baja vs Baja Solicitada,
    esta última todavía necesita "Marcar como DESCONECTADO" para
    confirmarse) y cuántas siguen Conectadas (esperando la desconexión
    física)."""
    if df.empty:
        return {"total": 0, "baja": 0, "baja_solicitada": 0, "conectadas": 0}
    estado_com = df.get(COL_ESTADO_COMERCIAL, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    estado_activ = df.get(COL_ESTADO_ACTIVACION, pd.Series(dtype=str)).astype(str).str.strip().str.upper()
    return {
        "total": len(df),
        "baja": int((estado_com == VALOR_ESTADO_COMERCIAL_BAJA).sum()),
        "baja_solicitada": int((estado_com == VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA).sum()),
        "conectadas": int((estado_activ == ESTADO_CONECTADO).sum()),
    }


# =========================================================
# CONTACTOS (05-10-2026, a pedido explícito): CDB de PruebasFM que todavía no
# tienen ningún contacto en contactos.xlsx. La relación contacto <-> empresa
# es por CDB, nunca por VIN.
# =========================================================
COLUMNAS_CDB_SIN_CONTACTO = [COL_CDB_FLOTA, COL_FLOTA_VC, 'RUT', 'UNIDADES', 'VIGENTES']


def _dato_o_vacio(serie):
    texto = serie.astype(str).str.strip()
    sin_dato = serie.isna() | texto.str.upper().isin(['', 'NAN', 'NONE', '-', 'NAT'])
    return texto.where(sin_dato.eq(False), '')


def filtrar_cdb_sin_contacto(df, df_contactos):
    """Una fila por CDB (dato real, no vacío ni '-') que no aparece en la
    columna CDB de contactos.xlsx: FLOTA VC y RUT más frecuentes del CDB,
    cantidad de UNIDADES y cuántas están VIGENTES (para priorizar). Sin
    contactos cargados devuelve vacío en vez de marcar todos los CDB."""
    vacio = pd.DataFrame(columns=COLUMNAS_CDB_SIN_CONTACTO)
    if df is None or df.empty or COL_CDB_FLOTA not in df.columns:
        return vacio
    if df_contactos is None or df_contactos.empty or 'CDB' not in df_contactos.columns:
        return vacio

    con_contacto = set(_dato_o_vacio(df_contactos['CDB'])) - {''}
    if COL_ESTADO_COMERCIAL in df.columns:
        vigente = df[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper() == VALOR_ESTADO_COMERCIAL_VIGENTE
    else:
        vigente = pd.Series(False, index=df.index)
    base = pd.DataFrame({
        COL_CDB_FLOTA: _dato_o_vacio(df[COL_CDB_FLOTA]),
        COL_FLOTA_VC: _dato_o_vacio(df[COL_FLOTA_VC]) if COL_FLOTA_VC in df.columns else '',
        'RUT': _dato_o_vacio(df['RUT']) if 'RUT' in df.columns else '',
        'VIGENTE': vigente,
    })
    base = base[(base[COL_CDB_FLOTA] != '') & ~base[COL_CDB_FLOTA].isin(con_contacto)
                & (base[COL_FLOTA_VC].str.upper() != 'NO EXISTE EN VC')]
    if base.empty:
        return vacio

    def mas_frecuente(columna, cdbs):
        """Valor más repetido por CDB (vectorizado; empate: el primero que aparece)."""
        datos = base.loc[base[columna] != '', [COL_CDB_FLOTA, columna]]
        if datos.empty:
            return pd.Series('', index=cdbs)
        conteo = datos.groupby([COL_CDB_FLOTA, columna], sort=False).size().reset_index(name='n')
        ganador = conteo.sort_values('n', ascending=False, kind='stable').drop_duplicates(COL_CDB_FLOTA)
        return ganador.set_index(COL_CDB_FLOTA)[columna].reindex(cdbs).fillna('')

    grupos = base.groupby(COL_CDB_FLOTA, sort=False)
    cdbs = grupos.size().index
    resultado = pd.DataFrame({
        COL_CDB_FLOTA: list(cdbs),
        COL_FLOTA_VC: mas_frecuente(COL_FLOTA_VC, cdbs).tolist(),
        'RUT': mas_frecuente('RUT', cdbs).tolist(),
        'UNIDADES': [int(n) for n in grupos.size().values],
        'VIGENTES': [int(n) for n in grupos['VIGENTE'].sum().values],
    })
    return resultado.sort_values(
        ['VIGENTES', 'UNIDADES', COL_CDB_FLOTA], ascending=[False, False, True]).reset_index(drop=True)


def calcular_kpis_cdb_sin_contacto(df):
    """KPI de "Contactos": CDB sin contacto, unidades que cubren, flotas
    distintas y cuántos CDB tienen al menos una unidad vigente."""
    if df.empty:
        return {"total": 0, "unidades": 0, "clientes": 0, "vigentes": 0}
    flotas = df[COL_FLOTA_VC].astype(str).str.strip()
    return {
        "total": len(df),
        "unidades": int(df['UNIDADES'].sum()),
        "clientes": int(flotas[flotas != ''].nunique()),
        "vigentes": int((df['VIGENTES'] > 0).sum()),
    }
