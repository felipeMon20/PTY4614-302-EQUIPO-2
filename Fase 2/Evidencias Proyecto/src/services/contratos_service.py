"""Logica de datos de Contratos (CM), separada de src/ui/contratos.py (mismo
patron que facturacion_manual_service.py): Python/pandas puro, sin PyQt6.
Trabaja siempre sobre una copia de DataManager().df_master (PruebasFM.xlsx ya
cargado en memoria) -- nunca lee el Excel de nuevo.

Replica para Contratos CM la navegacion de dos niveles ya usada en
Facturacion Manual (empresa -> unidad/VIN), a pedido explicito del usuario
(19-09-2026): mismo diseño de tarjetas, mismo color de titulo (MODULE_COLORS),
sin los checkboxes "Ocultar sin contrato (-)" / "Ocultar PAGO CM <= 0" que
existian antes en la barra de controles.
"""

import pandas as pd

from src.core.constants import (COL_RAZON_SOCIAL, COL_RUT, COL_VIN, COL_CHASIS, COL_ID, COL_ESTADO_COMERCIAL,
                                COL_ESTADO_ACTIVACION, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION,
                                FORMA_CONTRATO_TIPO_CM_MAP, TIPO_FACTURACION_HABILITA_CM)

COL_N_CONTRATO = "N CONTRATO 3PC"
COL_FECHA_INICIO_CM = "FECHA INICIO CM"
COL_FECHA_TERMINO_CM = "FECHA TERMINO CM"
COL_TIPO_CM = "TIPO DE CM"
COL_ESTADO_CM = "ESTADO DEL CM"
COL_PAGO_CM = "PAGO CM"

COLUMNAS_BASE = [
    COL_ID, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_VIN, COL_CHASIS, COL_RAZON_SOCIAL, COL_RUT, COL_N_CONTRATO,
    COL_FECHA_INICIO_CM, COL_FECHA_TERMINO_CM, COL_TIPO_CM, COL_ESTADO_CM, COL_PAGO_CM,
]

# Columnas mostradas en el nivel 2 (tarjetas de contratos de una empresa ya
# elegida en el nivel 1). RAZÓN SOCIAL/RUT no se repiten aqui porque ya se
# conocen por el nivel 1 (quedan solo en el titulo de la pantalla).
COLUMNAS_DETALLE_EMPRESA = [
    COL_ID, COL_ESTADO_COMERCIAL, COL_VIN, COL_CHASIS, COL_N_CONTRATO, COL_FECHA_INICIO_CM,
    COL_FECHA_TERMINO_CM, COL_TIPO_CM, COL_ESTADO_CM, COL_PAGO_CM,
]

_SIN_CONTRATO = ("-", "NAN", "")


def preparar_base_contratos(df_master):
    """Recorta df_master a COLUMNAS_BASE (solo las que existan) y normaliza
    los campos de texto. No filtra por N CONTRATO 3PC todavia -- eso lo hace
    filtrar_con_contrato(), separado para que el llamador decida si quiere el
    universo completo o solo el de contratos reales."""
    cols_disp = [c for c in COLUMNAS_BASE if c in df_master.columns]
    df_base = df_master[cols_disp].copy()

    for c in [COL_N_CONTRATO, COL_TIPO_CM, COL_ESTADO_CM, COL_FECHA_INICIO_CM, COL_FECHA_TERMINO_CM]:
        if c in df_base.columns:
            df_base[c] = df_base[c].fillna("-").astype(str).str.strip()

    if COL_PAGO_CM in df_base.columns:
        df_base["PAGO CM_NUM"] = pd.to_numeric(df_base[COL_PAGO_CM], errors="coerce").fillna(0)
    else:
        df_base["PAGO CM_NUM"] = 0

    return df_base


def filtrar_con_contrato(df_base):
    """Universo real de Contratos CM: solo VIN con N CONTRATO 3PC distinto de
    '-'/'NAN'/''. Reemplaza al checkbox 'Ocultar sin contrato (-)' (por
    defecto siempre estaba activado) -- decision tomada junto al usuario
    (19-09-2026): esta pantalla es de contratos, no de todo el parque."""
    if df_base.empty or COL_N_CONTRATO not in df_base.columns:
        return df_base.copy()
    return df_base[~df_base[COL_N_CONTRATO].str.upper().isin(_SIN_CONTRATO)].copy()


COLUMNAS_DATOS_CM = [COL_N_CONTRATO, COL_FECHA_INICIO_CM, COL_FECHA_TERMINO_CM, COL_TIPO_CM, COL_ESTADO_CM, COL_PAGO_CM]
_SIN_DATO_CM = ("", "-", "NAN", "NONE", "NAT", "0", "0.0")


def _es_cm(forma_contrato, tipo_facturacion):
    return (str(forma_contrato).strip().upper() in FORMA_CONTRATO_TIPO_CM_MAP
            or str(tipo_facturacion).strip().upper() in TIPO_FACTURACION_HABILITA_CM)


def construir_cambios_limpieza_cm(df):
    """Lote que deja en "-" los datos de CM (N° contrato 3PC, fechas, tipo,
    estado y pago) de las unidades cuya FORMA DE CONTRATO y TIPO DE
    FACTURACION no son de CM y que aun tienen algun dato cargado. `df` es el
    df_master (contratos actuales). Formato de DataManager: {vin: {'VIN',
    'cambios'}}."""
    lote = {}
    if df is None or df.empty or COL_VIN not in df.columns:
        return lote
    columnas = [c for c in COLUMNAS_DATOS_CM if c in df.columns]
    if not columnas:
        return lote
    forma = df[COL_FORMA_CONTRATO] if COL_FORMA_CONTRATO in df.columns else pd.Series("", index=df.index)
    tipo = df[COL_TIPO_FACTURACION] if COL_TIPO_FACTURACION in df.columns else pd.Series("", index=df.index)
    con_dato = pd.concat(
        [~df[c].astype(str).str.strip().str.upper().isin(_SIN_DATO_CM) for c in columnas], axis=1).any(axis=1)
    no_cm = pd.Series([not _es_cm(f, t) for f, t in zip(forma, tipo)], index=df.index)
    for vin in df.loc[con_dato & no_cm, COL_VIN].astype(str).str.strip().str.upper():
        if vin:
            lote[vin] = {'VIN': vin, 'cambios': {c: "-" for c in columnas}}
    return lote


def obtener_empresas(df_filtrado):
    """Una fila por empresa (RAZÓN SOCIAL unica dentro del universo ya
    filtrado), con su RUT y la cantidad de contratos asociados."""
    columnas_vacio = [COL_RAZON_SOCIAL, COL_RUT, "UNIDADES"]
    if df_filtrado.empty or COL_RAZON_SOCIAL not in df_filtrado.columns:
        return pd.DataFrame(columns=columnas_vacio)

    agrupado = df_filtrado.groupby(COL_RAZON_SOCIAL, dropna=False)
    resumen = agrupado.size().reset_index(name="UNIDADES")

    if COL_RUT in df_filtrado.columns:
        rut_por_empresa = agrupado[COL_RUT].first().reset_index()
        resumen = resumen.merge(rut_por_empresa, on=COL_RAZON_SOCIAL, how="left")
        resumen = resumen[[COL_RAZON_SOCIAL, COL_RUT, "UNIDADES"]]

    return resumen.sort_values(COL_RAZON_SOCIAL, kind="mergesort").reset_index(drop=True)


def obtener_contratos_empresa(df_filtrado, empresa):
    """Filas de df_filtrado de una sola empresa (RAZÓN SOCIAL exacta),
    recortadas a COLUMNAS_DETALLE_EMPRESA (mas PAGO CM_NUM, util para
    ordenar/formatear en la UI sin recalcular)."""
    cols_vacio = COLUMNAS_DETALLE_EMPRESA + ["PAGO CM_NUM"]
    if df_filtrado.empty or COL_RAZON_SOCIAL not in df_filtrado.columns:
        return pd.DataFrame(columns=cols_vacio)

    df_empresa = df_filtrado[df_filtrado[COL_RAZON_SOCIAL] == empresa]
    cols_disp = [c for c in cols_vacio if c in df_empresa.columns]
    return df_empresa[cols_disp].copy()


def calcular_resumen_importacion(df_master, cambios_comercial, total_filas_excel, vins_ausentes_info, vins_nuevos_info=None,
                                 contratos_nuevos=None):
    """Resumen mostrado en el panel previo a inyectar un import de Contratos
    CM (ver contratos.py::importar_excel_reporte). No decide ni modifica
    nada -- solo compara `cambios_comercial` (lo que ya calculo
    importar_excel_reporte) contra el valor ACTUAL de cada VIN en
    `df_master` para saber cuantos de esos cambios son reales.

    `vins_ausentes_info` es la lista de dicts que devuelve
    cm_bajas_service.detectar_posibles_bajas_cm() para este mismo import
    (mismo criterio de "tenia CM y no vino este mes" que ya usa Gestionar CM
    -- no se reinventa una segunda deteccion)."""
    resultado = {
        "total_filas_excel": total_filas_excel,
        "total_coincidencias": len(cambios_comercial),
        "total_actualizados": 0,
        "total_sin_cambios": 0,
        "pasan_a_expired": 0,
        "pasan_a_terminated": 0,
        "vins_ausentes": vins_ausentes_info,
        "vins_nuevos": vins_nuevos_info or [],
        "contratos_nuevos": contratos_nuevos or [],
    }

    if not cambios_comercial or df_master.empty or COL_VIN not in df_master.columns:
        return resultado

    df_idx = df_master.set_index(df_master[COL_VIN].astype(str).str.strip().str.upper())

    for vin, data in cambios_comercial.items():
        cambios = data.get("cambios", {})
        if vin not in df_idx.index:
            continue
        fila_actual = df_idx.loc[vin]

        hay_cambio = False
        for col, valor_nuevo in cambios.items():
            if col not in df_idx.columns:
                continue
            valor_actual = fila_actual[col]
            if str(valor_actual).strip() != str(valor_nuevo).strip():
                hay_cambio = True
                break

        if hay_cambio:
            resultado["total_actualizados"] += 1
        else:
            resultado["total_sin_cambios"] += 1

        estado_anterior = str(fila_actual.get(COL_ESTADO_CM, "-")).strip().upper()
        estado_nuevo = str(cambios.get(COL_ESTADO_CM, estado_anterior)).strip().upper()
        if estado_nuevo != estado_anterior:
            if estado_nuevo == "EXPIRED":
                resultado["pasan_a_expired"] += 1
            elif estado_nuevo == "TERMINATED":
                resultado["pasan_a_terminated"] += 1

    return resultado


def construir_registro_nuevo_desde_contrato_cm(vin, fila_cm, candidato=None):
    """Arma el registro completo de una unidad nueva de Comercial a partir
    de un VIN que trae el Excel de Contratos CM (3PC de la contraparte comercial) pero que
    todavia no tiene ficha en Comercial. Mismo patron que
    provisiones.py::_construir_registro_nuevo_desde_provisiones (reutiliza
    los defaults de comercial_agregar.py, no reinventa reglas de negocio),
    pero al reves: aca SI hay datos reales de contrato CM (N CONTRATO 3PC,
    fechas, tipo, estado, pago -- ya vienen en `fila_cm`, la misma forma
    que arma importar_excel_reporte) y NO hay plan/duracion de Provisiones,
    que quedan en blanco para completar despues a mano.

    `candidato` es una de las combinaciones {RAZÓN SOCIAL, RUT, CDB,
    EJECUTIVO} que devuelve provisiones_services.buscar_candidatos_por_cliente(),
    o None si el usuario no eligio ninguna coincidencia (el registro queda
    parcial, sin inventar esos datos)."""
    from src.core.constants import COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_TIPO_FACTURACION, COL_ETAPA_GESTION
    from src.core.dataframe_formatter import DataFrameFormatter
    from src.services.vin_service import obtener_modelo_desde_vin
    from src.ui.comercial_agregar import _DEFAULTS_INICIALES, _tipo_facturacion_default_para_forma_contrato

    vin = str(vin).strip().upper()
    chasis = vin[-7:] if len(vin) >= 7 else ""
    modelo = obtener_modelo_desde_vin(vin) or _DEFAULTS_INICIALES['MODELO']

    # FORMA DE CONTRATO (30-09-2026): si fila_cm ya trae CMG/CMB/CMS (ver
    # contratos.py::datos_cm_de_fila, misma regla que se aplica a un VIN ya
    # existente), se usa eso; si no, queda el default de "Gestión de
    # Unidades". TIPO DE FACTURACION se sigue derivando de FORMA DE
    # CONTRATO via FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ (CMG/CMB/CMS ->
    # CM automaticamente), sin reinventar esa regla acá.
    forma_contrato = fila_cm.get('FORMA DE CONTRATO') or _DEFAULTS_INICIALES['FORMA DE CONTRATO']
    tipo_facturacion = _tipo_facturacion_default_para_forma_contrato(forma_contrato)
    estado_comercial = _DEFAULTS_INICIALES['ESTADO COMERCIAL']
    # ESTADO DE ACTIVACIÓN ACTUAL (30-09-2026, a pedido explícito): un VIN
    # que no existía en Comercial queda en "No aplica" para que el usuario
    # lo vea en "Por gestionar" -- mismo default que ya usa "Gestión de
    # Unidades" al crear una unidad nueva, no hace falta forzarlo aparte.
    estado_activacion = _DEFAULTS_INICIALES['ESTADO DE ACTIVACIÓN ACTUAL']

    etapa_gestion = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: estado_comercial,
        COL_ESTADO_ACTIVACION: estado_activacion,
        COL_TIPO_FACTURACION: tipo_facturacion,
        COL_ETAPA_GESTION: '',
    })

    candidato = candidato or {}
    return {
        'VIN': vin,
        'CHASIS': chasis,
        'MODELO': modelo,
        'RAZÓN SOCIAL': candidato.get('RAZÓN SOCIAL', ''),
        'RUT': candidato.get('RUT', ''),
        'CDB': candidato.get('CDB', ''),
        'EJECUTIVO': candidato.get('EJECUTIVO', ''),
        'INDUSTRIA': _DEFAULTS_INICIALES['INDUSTRIA'],
        'FORMA DE CONTRATO': forma_contrato,
        'TIPO DE FACTURACION': tipo_facturacion,
        'ESTADO COMERCIAL': estado_comercial,
        'ESTADO DE ACTIVACIÓN ACTUAL': estado_activacion,
        'FLOTA VC': _DEFAULTS_INICIALES['FLOTA VC'],
        'FLOTA VC 2': _DEFAULTS_INICIALES['FLOTA VC 2'],
        'TIPO DE SERVICIO': _DEFAULTS_INICIALES['TIPO DE SERVICIO'],
        'DURACIÓN (MESES)': '',
        'INICIO CONTRATO': '',
        'TÉRMINO CONTRATO': '',
        'FECHA DE BAJA': '-',
        'CONTRATO CREADO EN JUSTTIME': '-',
        'INICIO': '-',
        'TERMINO': '-',
        'ESTADO DE ENTREGA': '-',
        'N CONTRATO 3PC': fila_cm.get(COL_N_CONTRATO, '-'),
        'FECHA INICIO CM': fila_cm.get(COL_FECHA_INICIO_CM, '-'),
        'FECHA TERMINO CM': fila_cm.get(COL_FECHA_TERMINO_CM, '-'),
        'TIPO DE CM': fila_cm.get(COL_TIPO_CM, '-'),
        'ESTADO DEL CM': fila_cm.get(COL_ESTADO_CM, '-'),
        'PAGO CM': fila_cm.get(COL_PAGO_CM, '-'),
        'OBSERVACIONES': 'Viene de Contratos CM (3PC)',
        'ETAPA GESTIÓN': etapa_gestion,
    }
