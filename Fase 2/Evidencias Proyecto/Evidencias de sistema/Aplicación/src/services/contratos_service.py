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
from src.services.cm_bajas_service import pago_cubre_mes_actual

from src.core.constants import (COL_RAZON_SOCIAL, COL_RUT, COL_VIN, COL_CHASIS, COL_ID, COL_ESTADO_COMERCIAL,
                                COL_ESTADO_ACTIVACION, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION, COL_CDB_FLOTA, COL_TIPO_SERVICIO,
                                FORMA_CONTRATO_TIPO_CM_MAP, TIPO_CM_FORMA_CONTRATO_MAP, TIPO_FACTURACION_HABILITA_CM,
                                COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM, ESTADOS_CM_SIN_PAGO)

COL_N_CONTRATO = "N CONTRATO 3PC"
COL_FECHA_INICIO_CM = "FECHA INICIO CM"
COL_FECHA_TERMINO_CM = "FECHA TERMINO CM"
COL_TIPO_CM = "TIPO DE CM"
COL_ESTADO_CM = "ESTADO DEL CM"
COL_PAGO_CM = "PAGO CM"

COLUMNAS_BASE = [
    COL_ID, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION, COL_VIN, COL_CHASIS,
    COL_RAZON_SOCIAL, COL_RUT,
    COL_CDB_FLOTA, "FLOTA VC", "EJECUTIVO",
    COL_N_CONTRATO, COL_FECHA_INICIO_CM, COL_FECHA_TERMINO_CM, COL_TIPO_CM, COL_ESTADO_CM, COL_PAGO_CM,
    COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM, COL_TIPO_SERVICIO,
]

# Columnas mostradas en el nivel 2 (tarjetas de contratos de una empresa ya
# elegida en el nivel 1). RAZÓN SOCIAL/RUT no se repiten aqui porque ya se
# conocen por el nivel 1 (quedan solo en el titulo de la pantalla).
COLUMNAS_DETALLE_EMPRESA = [
    COL_ID, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_VIN, COL_CHASIS, COL_N_CONTRATO, COL_FECHA_INICIO_CM,
    COL_FECHA_TERMINO_CM, COL_TIPO_CM, COL_ESTADO_CM, COL_PAGO_CM, COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM,
    COL_TIPO_SERVICIO,
]

_SIN_CONTRATO = ("-", "NAN", "")


def leer_excel_3pc(ruta):
    """Lee el Excel 3PC desde la hoja que trae los contratos, que no siempre es
    la primera (puede venir antes una tabla dinámica), y desde la fila de
    encabezado que tenga las columnas de VIN y N° de contrato. Si ninguna hoja
    las trae, devuelve la primera tal cual para que el llamador avise."""
    with pd.ExcelFile(ruta) as excel:
        for hoja in excel.sheet_names:
            muestra = excel.parse(hoja, header=None, nrows=30)
            for fila in range(len(muestra)):
                celdas = [str(v).strip().upper() for v in muestra.iloc[fila] if pd.notna(v)]
                if any('VIN' in c for c in celdas) and any('CONTRACT NO' in c for c in celdas):
                    return excel.parse(hoja, header=fila)
        return excel.parse(excel.sheet_names[0])


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


def vins_forma_y_facturacion_no_cm(df):
    """VIN (mayúsculas) de los contratos cuya forma de contrato y tipo de facturación no son de CM."""
    if df is None or df.empty or COL_VIN not in df.columns:
        return set()
    forma = df[COL_FORMA_CONTRATO] if COL_FORMA_CONTRATO in df.columns else pd.Series("", index=df.index)
    tipo = df[COL_TIPO_FACTURACION] if COL_TIPO_FACTURACION in df.columns else pd.Series("", index=df.index)
    no_cm = pd.Series([not _es_cm(f, t) for f, t in zip(forma, tipo)], index=df.index)
    return set(df.loc[no_cm, COL_VIN].astype(str).str.strip().str.upper())


def omitir_en_importacion(estado_3pc, fila_actual):
    """True si la importación del 3PC no debe volver a cargar datos CM en esta unidad: el 3PC la sigue
    listando con el CM ya vencido (Expired), pero la unidad ya no es CM (forma de contrato y facturación
    de otro tipo) y no tiene datos de CM, por ejemplo porque se limpiaron. Un CM vigente (Running) sí se
    carga siempre, porque puede ser una unidad que vuelve a CM."""
    if str(estado_3pc).strip().upper() != "EXPIRED":
        return False
    if _es_cm(fila_actual.get(COL_FORMA_CONTRATO, ""), fila_actual.get(COL_TIPO_FACTURACION, "")):
        return False
    return all(str(fila_actual.get(c, "")).strip().upper() in _SIN_DATO_CM for c in COLUMNAS_DATOS_CM)


def obtener_empresas(df_filtrado):
    """Una fila por empresa (RAZÓN SOCIAL unica dentro del universo ya
    filtrado), con su RUT, la cantidad de contratos asociados, cuántos están
    Vigentes, cuántos Desconectados o Activando y su CDB FLOTA."""
    columnas_vacio = [COL_RAZON_SOCIAL, COL_RUT, "UNIDADES", "VIGENTES", "DESCONECTADOS", "ACTIVANDO", "RUNNING", "EXPIRED",
                      "AL_DIA", "POR_ACTUALIZAR", "SIN_PAGO", COL_CDB_FLOTA, "CDB_VARIOS", "FLOTA_VC", "EJECUTIVO"]
    if df_filtrado.empty or COL_RAZON_SOCIAL not in df_filtrado.columns:
        return pd.DataFrame(columns=columnas_vacio)

    agrupado = df_filtrado.groupby(COL_RAZON_SOCIAL, dropna=False)
    resumen = agrupado.size().reset_index(name="UNIDADES")

    if COL_RUT in df_filtrado.columns:
        rut_por_empresa = agrupado[COL_RUT].first().reset_index()
        resumen = resumen.merge(rut_por_empresa, on=COL_RAZON_SOCIAL, how="left")
        resumen = resumen[[COL_RAZON_SOCIAL, COL_RUT, "UNIDADES"]]

    def _conteo(columna, valor):
        if columna not in df_filtrado.columns:
            return pd.Series(0, index=resumen[COL_RAZON_SOCIAL])
        marcada = df_filtrado[columna].astype(str).str.strip().str.upper() == valor
        return marcada.groupby(df_filtrado[COL_RAZON_SOCIAL], dropna=False).sum()

    resumen["VIGENTES"] = resumen[COL_RAZON_SOCIAL].map(_conteo(COL_ESTADO_COMERCIAL, "VIGENTE")).fillna(0).astype(int)
    resumen["DESCONECTADOS"] = resumen[COL_RAZON_SOCIAL].map(_conteo(COL_ESTADO_ACTIVACION, "DESCONECTADO")).fillna(0).astype(int)
    resumen["ACTIVANDO"] = resumen[COL_RAZON_SOCIAL].map(_conteo(COL_ESTADO_ACTIVACION, "ACTIVANDO")).fillna(0).astype(int)
    resumen["RUNNING"] = resumen[COL_RAZON_SOCIAL].map(_conteo(COL_ESTADO_CM, "RUNNING")).fillna(0).astype(int)
    resumen["EXPIRED"] = resumen[COL_RAZON_SOCIAL].map(_conteo(COL_ESTADO_CM, "EXPIRED")).fillna(0).astype(int)
    for columna, situacion in (("AL_DIA", SITUACION_AL_DIA), ("POR_ACTUALIZAR", SITUACION_POR_ACTUALIZAR),
                               ("SIN_PAGO", SITUACION_SIN_PAGO)):
        resumen[columna] = resumen[COL_RAZON_SOCIAL].map(_conteo("SITUACION_PAGO", situacion.upper())).fillna(0).astype(int)

    # CDB FLOTA: solo el más repetido de la empresa (ambos si empatan); CDB_VARIOS
    # avisa que tiene más de uno distinto
    def _cdbs_limpios(valores):
        limpios = [str(v).strip() for v in valores]
        return [v for v in limpios if v.upper() not in ("", "-", "NAN", "NONE")]

    def _cdb_mas_repetido(valores):
        limpios = _cdbs_limpios(valores)
        if not limpios:
            return "-"
        conteo = pd.Series(limpios).value_counts()
        return ", ".join(sorted(conteo[conteo == conteo.max()].index))

    def _cdb_varios(valores):
        return len(set(_cdbs_limpios(valores))) > 1

    if COL_CDB_FLOTA in df_filtrado.columns:
        por_empresa = df_filtrado.groupby(COL_RAZON_SOCIAL, dropna=False)[COL_CDB_FLOTA]
        resumen[COL_CDB_FLOTA] = resumen[COL_RAZON_SOCIAL].map(por_empresa.agg(_cdb_mas_repetido)).fillna("-")
        resumen["CDB_VARIOS"] = resumen[COL_RAZON_SOCIAL].map(por_empresa.agg(_cdb_varios)).fillna(False).astype(bool)
    else:
        resumen[COL_CDB_FLOTA] = "-"
        resumen["CDB_VARIOS"] = False

    for columna, destino in (("FLOTA VC", "FLOTA_VC"), ("EJECUTIVO", "EJECUTIVO")):
        resumen[destino] = resumen[COL_RAZON_SOCIAL].map(_valor_mas_repetido(df_filtrado, columna)).fillna("-")

    return resumen.sort_values(COL_RAZON_SOCIAL, kind="mergesort").reset_index(drop=True)


def _valor_mas_repetido(df, columna):
    """Por empresa, el valor no vacío más repetido de la columna (Serie indexada por RAZÓN SOCIAL)."""
    if columna not in df.columns:
        return pd.Series(dtype=object)
    valores = df[[COL_RAZON_SOCIAL, columna]].copy()
    valores[columna] = valores[columna].astype(str).str.strip()
    valores = valores[~valores[columna].str.upper().isin(("", "-", "NAN", "NONE"))]
    conteo = valores.groupby([COL_RAZON_SOCIAL, columna]).size().reset_index(name="_n")
    conteo = conteo.sort_values([COL_RAZON_SOCIAL, "_n", columna], ascending=[True, False, True])
    return conteo.drop_duplicates(COL_RAZON_SOCIAL).set_index(COL_RAZON_SOCIAL)[columna]


def obtener_contratos_empresa(df_filtrado, empresa):
    """Filas de df_filtrado de una sola empresa (RAZÓN SOCIAL exacta),
    recortadas a COLUMNAS_DETALLE_EMPRESA (mas PAGO CM_NUM, util para
    ordenar/formatear en la UI sin recalcular)."""
    cols_vacio = COLUMNAS_DETALLE_EMPRESA + ["PAGO CM_NUM", COL_FORMA_CONTRATO, COL_TIPO_FACTURACION]
    if df_filtrado.empty or COL_RAZON_SOCIAL not in df_filtrado.columns:
        return pd.DataFrame(columns=cols_vacio)

    df_empresa = df_filtrado[df_filtrado[COL_RAZON_SOCIAL] == empresa]
    cols_disp = [c for c in cols_vacio if c in df_empresa.columns]
    return df_empresa[cols_disp].copy()


def unidades_forma_no_es_cm(df):
    """VIN (mayúsculas) de las unidades cuyo TIPO DE CM del 3PC corresponde a
    una forma de contrato CM (Gold, Blue, Silver) pero cuya FORMA DE CONTRATO
    es otra: Provisión, Conversión, Venta... La importación no las modifica."""
    columnas = (COL_VIN, COL_TIPO_CM, COL_FORMA_CONTRATO)
    if df is None or df.empty or not all(c in df.columns for c in columnas):
        return set()
    esperada = df[COL_TIPO_CM].astype(str).str.strip().map(TIPO_CM_FORMA_CONTRATO_MAP)
    forma = df[COL_FORMA_CONTRATO].astype(str).str.strip().str.upper()
    mascara = esperada.notna() & (forma != esperada.fillna("").str.upper())
    return set(df.loc[mascara, COL_VIN].astype(str).str.strip().str.upper())


def es_desconectada_en_baja(fila):
    """Contrato actual en Baja o Baja Solicitada con la unidad Desconectada."""
    from src.services.comercial_services import es_contrato_cerrado
    return (es_contrato_cerrado(fila.get(COL_ESTADO_COMERCIAL, ""))
            and str(fila.get(COL_ESTADO_ACTIVACION, "")).strip().upper() == "DESCONECTADO")


def construir_contrato_nuevo_desde_anterior(fila_anterior, fila_cm, periodo_interno=""):
    """Contrato nuevo de una unidad que vino en el 3PC pero estaba Desconectada
    en Baja: copia los datos del contrato anterior, lo manda a activar en
    Operaciones (Activación Pendiente / Activando) y le carga los datos del
    3PC. `fila_cm` es lo que arma importar_excel_javiera para el VIN. El ID lo
    pone quien lo agrega. JustTime queda Pendiente solo si el tipo de
    facturación va a JustTime: el contrato nuevo aún no existe allá."""
    from src.core.constants import TIPO_FACTURACION_HABILITA_JUSTTIME
    from src.core.dataframe_formatter import DataFrameFormatter
    from src.core.constants import COL_ETAPA_GESTION

    plantilla = construir_registro_nuevo_desde_contrato_cm("", {})
    columnas = set(plantilla) | {"CDB FLOTA", "PERIODO INTERNO"}
    registro = {c: ("" if pd.isna(v) else str(v)) for c, v in fila_anterior.items() if c in columnas}
    registro.update({
        "ESTADO COMERCIAL": "Activación Pendiente",
        "ESTADO DE ACTIVACIÓN ACTUAL": "Activando",
        "FECHA DE BAJA": "-",
        "INICIO": "-",
        "TERMINO": "-",
        # Sin plan: Operaciones lo asigna al activar la unidad
        COL_TIPO_SERVICIO: "-",
        COL_N_CONTRATO: fila_cm.get(COL_N_CONTRATO, "-"),
        COL_FECHA_INICIO_CM: fila_cm.get(COL_FECHA_INICIO_CM, "-"),
        COL_FECHA_TERMINO_CM: fila_cm.get(COL_FECHA_TERMINO_CM, "-"),
        COL_TIPO_CM: fila_cm.get(COL_TIPO_CM, "-"),
        COL_ESTADO_CM: fila_cm.get(COL_ESTADO_CM, "-"),
        COL_PAGO_CM: fila_cm.get(COL_PAGO_CM, "-"),
        COL_ULTIMO_PAGO_CM: fila_cm.get(COL_ULTIMO_PAGO_CM, ""),
        COL_FECHA_ULTIMO_PAGO_CM: fila_cm.get(COL_FECHA_ULTIMO_PAGO_CM, ""),
    })
    if periodo_interno:
        registro["PERIODO INTERNO"] = periodo_interno
    if fila_cm.get(COL_FORMA_CONTRATO):
        registro[COL_FORMA_CONTRATO] = fila_cm[COL_FORMA_CONTRATO]
        registro[COL_TIPO_FACTURACION] = fila_cm.get(COL_TIPO_FACTURACION, registro.get(COL_TIPO_FACTURACION, ""))
    va_a_justtime = str(registro.get(COL_TIPO_FACTURACION, "")).strip().upper() in TIPO_FACTURACION_HABILITA_JUSTTIME
    registro["CONTRATO CREADO EN JUSTTIME"] = "Pendiente" if va_a_justtime else "-"
    registro[COL_ETAPA_GESTION] = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: registro["ESTADO COMERCIAL"],
        COL_ESTADO_ACTIVACION: registro["ESTADO DE ACTIVACIÓN ACTUAL"],
        COL_TIPO_FACTURACION: registro.get(COL_TIPO_FACTURACION, ""),
        COL_ETAPA_GESTION: "",
    })
    registro["VIN"] = str(fila_anterior.get(COL_VIN, "")).strip().upper()
    return registro


def es_forma_provision(forma):
    """True solo para la forma Provision (no Provision +), con o sin tilde."""
    import unicodedata
    texto = unicodedata.normalize('NFKD', str(forma).strip()).encode('ascii', 'ignore').decode().upper()
    return texto == "PROVISION"


def construir_renovacion_provision_a_cm(fila, cambios_cm, id_nuevo):
    """Pasar una Provision a CM crea un contrato nuevo y deja la Provision como contrato anterior.
    `fila` es el contrato actual, `cambios_cm` lo que devuelve cambio_opcional_a_cm e `id_nuevo` el ID
    del contrato nuevo. Devuelve (cambios del contrato anterior, registro del contrato nuevo).
    El anterior queda Renovado, con JustTime en Eliminar si estaba en Si o Pendiente, y sin los datos
    del 3PC, que pasan al nuevo. El nuevo conserva el INICIO CONTRATO, con duración "-" y término
    MENSUAL, y no va a JustTime salvo que su facturación lo habilite."""
    from src.core.constants import COL_ETAPA_GESTION, COL_INICIO_CONTRATO, COL_DURACION_MESES, COL_TERMINO_CONTRATO
    from src.core.dataframe_formatter import DataFrameFormatter
    from src.services.comercial_services import cambios_contrato_renovado

    def texto(valor):
        return "" if pd.isna(valor) else str(valor)

    plantilla = construir_registro_nuevo_desde_contrato_cm("", {})
    columnas = set(plantilla) | {"CDB FLOTA", "PERIODO INTERNO"}
    nuevo = {c: texto(v) for c, v in dict(fila).items() if c in columnas}
    estado_anterior = str(fila.get(COL_ESTADO_COMERCIAL, "")).strip().upper()
    if estado_anterior in ("VIGENTE", "VENCIDO") and str(fila.get(COL_ESTADO_CM, "")).strip().upper() != "EXPIRED":
        nuevo[COL_ESTADO_COMERCIAL] = "Vigente"
    nuevo.update(cambios_cm)
    nuevo.update({
        "ID": str(id_nuevo),
        COL_INICIO_CONTRATO: texto(fila.get(COL_INICIO_CONTRATO, "")),
        COL_DURACION_MESES: "-",
        COL_TERMINO_CONTRATO: "MENSUAL",
        "FECHA DE BAJA": "-",
    })
    from src.core.constants import TIPO_FACTURACION_HABILITA_JUSTTIME
    va_a_justtime = str(nuevo.get(COL_TIPO_FACTURACION, "")).strip().upper() in TIPO_FACTURACION_HABILITA_JUSTTIME
    nuevo["CONTRATO CREADO EN JUSTTIME"] = "Pendiente" if va_a_justtime else "-"
    nuevo[COL_ETAPA_GESTION] = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: nuevo.get(COL_ESTADO_COMERCIAL, ""),
        COL_ESTADO_ACTIVACION: nuevo.get(COL_ESTADO_ACTIVACION, ""),
        COL_TIPO_FACTURACION: nuevo.get(COL_TIPO_FACTURACION, ""),
        COL_ETAPA_GESTION: texto(fila.get(COL_ETAPA_GESTION, "")),
    })
    anterior = cambios_contrato_renovado(fila)
    anterior.update({c: "-" for c in COLUMNAS_DATOS_CM if c in dict(fila)})
    anterior.update({c: "" for c in (COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM) if c in dict(fila)})
    return anterior, nuevo


def construir_filas_por_unidad(df_master, cambios_comercial, contratos_nuevos, cambios_opcionales):
    """Una fila por unidad con algo relevante que revisar antes de importar: cambia
    de forma de contrato, pasa a Expired, recibe un contrato nuevo o trae CM con
    una forma de contrato que no es CM (`cambios_opcionales`: lo que haría el
    interruptor, queda en `forma_opcional` y `tipo_opcional`). `categorias`
    dice por cuáles. Valores "antes" salen del RM y "después" de lo que se va
    a guardar."""
    if df_master is None or df_master.empty or COL_VIN not in df_master.columns:
        return []
    df_idx = df_master.set_index(df_master[COL_VIN].astype(str).str.strip().str.upper())
    df_idx = df_idx[~df_idx.index.duplicated(keep="last")]

    def val(fila, col):
        texto = str(fila.get(col, "")).strip()
        return "-" if texto.lower() in ("", "nan", "none") else texto

    filas = {}

    def fila_base(vin):
        actual = df_idx.loc[vin]
        return filas.setdefault(vin, {
            "vin": vin, "cliente": val(actual, COL_RAZON_SOCIAL),
            "activacion_antes": val(actual, COL_ESTADO_ACTIVACION), "activacion_despues": "",
            "forma_antes": val(actual, COL_FORMA_CONTRATO), "forma_despues": val(actual, COL_FORMA_CONTRATO),
            "tipo_antes": val(actual, COL_TIPO_FACTURACION), "tipo_despues": val(actual, COL_TIPO_FACTURACION),
            "cm_antes": val(actual, COL_ESTADO_CM), "cm_despues": val(actual, COL_ESTADO_CM),
            "pago_antes": val(actual, COL_PAGO_CM), "pago_despues": val(actual, COL_PAGO_CM),
            "categorias": [],
        })

    def marcar(fila, categoria):
        if categoria not in fila["categorias"]:
            fila["categorias"].append(categoria)

    for vin, data in cambios_comercial.items():
        if vin not in df_idx.index:
            continue
        cambios = data.get("cambios", {})
        actual = df_idx.loc[vin]
        forma_cambia = (COL_FORMA_CONTRATO in cambios
                        and str(cambios[COL_FORMA_CONTRATO]).strip().upper() != val(actual, COL_FORMA_CONTRATO).upper())
        pasa_a_expired = (str(cambios.get(COL_ESTADO_CM, "")).strip().upper() == "EXPIRED"
                          and val(actual, COL_ESTADO_CM).upper() not in ESTADOS_CM_SIN_PAGO)
        if not (forma_cambia or pasa_a_expired):
            continue
        fila = fila_base(vin)
        fila["cm_despues"] = str(cambios.get(COL_ESTADO_CM, fila["cm_despues"])).strip()
        fila["pago_despues"] = str(cambios.get(COL_PAGO_CM, fila["pago_despues"])).strip()
        if forma_cambia:
            fila["forma_despues"] = str(cambios[COL_FORMA_CONTRATO]).strip()
            fila["tipo_despues"] = str(cambios.get(COL_TIPO_FACTURACION, fila["tipo_despues"])).strip()
            marcar(fila, "forma")
        if pasa_a_expired:
            marcar(fila, "expired")

    for registro in contratos_nuevos or []:
        vin = str(registro.get("VIN", "")).strip().upper()
        if vin not in df_idx.index:
            continue
        fila = fila_base(vin)
        fila["activacion_despues"] = str(registro.get("ESTADO DE ACTIVACIÓN ACTUAL", "")).strip()
        fila["cm_despues"] = str(registro.get(COL_ESTADO_CM, fila["cm_despues"])).strip()
        fila["pago_despues"] = str(registro.get(COL_PAGO_CM, fila["pago_despues"])).strip()
        marcar(fila, "nuevo")

    for vin, cambios in (cambios_opcionales or {}).items():
        if vin in df_idx.index:
            fila = fila_base(vin)
            fila["forma_opcional"] = str(cambios[COL_FORMA_CONTRATO]).strip()
            fila["tipo_opcional"] = str(cambios[COL_TIPO_FACTURACION]).strip()
            marcar(fila, "otra_forma")

    return list(filas.values())


def calcular_resumen_importacion(df_master, cambios_comercial, total_filas_excel, vins_ausentes_info, vins_nuevos_info=None,
                                 contratos_nuevos=None, cambios_opcionales=None):
    """Resumen mostrado en el panel previo a inyectar un import de Contratos
    CM (ver contratos.py::importar_excel_javiera). No decide ni modifica
    nada -- solo compara `cambios_comercial` (lo que ya calculo
    importar_excel_javiera) contra el valor ACTUAL de cada VIN en
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
        "forma_facturacion": calcular_cambios_forma_facturacion(df_master, cambios_comercial, cambios_opcionales),
    }
    resultado["filas_unidad"] = construir_filas_por_unidad(df_master, cambios_comercial, contratos_nuevos, cambios_opcionales)

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
            if estado_nuevo == "EXPIRED" and estado_anterior not in ESTADOS_CM_SIN_PAGO:
                resultado["pasan_a_expired"] += 1
            elif estado_nuevo == "TERMINATED":
                resultado["pasan_a_terminated"] += 1

    return resultado


FORMAS_QUE_PASAN_A_CM = {'', '-', 'SIN CONTRATO', 'REVISAR', 'CMG', 'CMB', 'CMS'}


SITUACION_AL_DIA = "al_dia"
SITUACION_POR_ACTUALIZAR = "por_actualizar"
SITUACION_SIN_PAGO = "sin_pago"


def _estado_comercial_normalizado(valor):
    return str(valor).strip().upper().replace("Ó", "O")


def pagado_este_mes(df, hoy=None):
    """Serie booleana: el último pago CM cubre este mes (el pago dura el mes siguiente al que se hizo)."""
    columna_pago = "PAGO CM_NUM" if "PAGO CM_NUM" in df.columns else "PAGO CM"
    pago = df[columna_pago] if columna_pago in df.columns else pd.Series(0, index=df.index)
    return pago_cubre_mes_actual(df[COL_FECHA_ULTIMO_PAGO_CM], pago, hoy)


def mascara_running_pagado_forma_incorrecta(df, hoy=None):
    """CM Running con pago este mes cuya forma de contrato no es CMG, CMB o CMS o cuya facturación no es CM."""
    from src.core.constants import VALOR_TIPO_FACT_CM
    if df is None or df.empty or COL_ESTADO_CM not in df.columns or COL_FECHA_ULTIMO_PAGO_CM not in df.columns:
        return pd.Series(False, index=df.index if df is not None else None)
    running = df[COL_ESTADO_CM].astype(str).str.strip().str.upper() == "RUNNING"
    forma = (df[COL_FORMA_CONTRATO] if COL_FORMA_CONTRATO in df.columns else pd.Series("", index=df.index))
    facturacion = (df[COL_TIPO_FACTURACION] if COL_TIPO_FACTURACION in df.columns else pd.Series("", index=df.index))
    forma_ok = forma.astype(str).str.strip().str.upper().isin(FORMA_CONTRATO_TIPO_CM_MAP)
    facturacion_ok = facturacion.astype(str).str.strip().str.upper() == VALOR_TIPO_FACT_CM
    return running & pagado_este_mes(df, hoy) & ~(forma_ok & facturacion_ok)


KPI_BAJA, KPI_PENDIENTE, KPI_FORMA_DISTINTA, KPI_AL_DIA = "baja", "pendiente", "forma_incorrecta", "al_dia"


def clasificar_kpi_cm(df, vins_activos, vins_baja_extra=(), hoy=None):
    """Reparte las unidades Conectadas o Activando (`vins_activos`) en las tarjetas de Contratos (CM) sin repetir
    ninguna, para que sus porcentajes sumen 100 % (12-11-2026, pedido de Javiera). En orden:
    baja = sin CM Running pagado este mes (Expired o sin pago) o con un caso pendiente en `vins_baja_extra`
    (ausente de la carga 3PC o datos 3PC vacíos); pendiente = estado comercial Activación Pendiente;
    forma_incorrecta = pagado pero con forma de contrato o facturación que no es CM; al_dia = el resto.
    Las unidades que no están Conectadas ni Activando quedan con ''."""
    if df is None:
        return pd.Series(dtype=object)
    resultado = pd.Series("", index=df.index, dtype=object)
    if df.empty or COL_VIN not in df.columns:
        return resultado
    vin = df[COL_VIN].astype(str).str.strip().str.upper()
    activo = vin.isin(set(vins_activos))
    running = (df[COL_ESTADO_CM].astype(str).str.strip().str.upper() == "RUNNING") if COL_ESTADO_CM in df.columns \
        else pd.Series(False, index=df.index)
    pagado = running & pagado_este_mes(df, hoy) if COL_FECHA_ULTIMO_PAGO_CM in df.columns else pd.Series(False, index=df.index)
    estado = df[COL_ESTADO_COMERCIAL].map(_estado_comercial_normalizado) if COL_ESTADO_COMERCIAL in df.columns \
        else pd.Series("", index=df.index)
    resultado[activo] = KPI_AL_DIA
    resultado[activo & mascara_running_pagado_forma_incorrecta(df, hoy)] = KPI_FORMA_DISTINTA
    resultado[activo & (estado == "ACTIVACION PENDIENTE")] = KPI_PENDIENTE
    resultado[activo & (~pagado | vin.isin(set(vins_baja_extra)))] = KPI_BAJA
    return resultado


def porcentajes_enteros(cantidades):
    """Porcentajes enteros que suman exactamente 100 (método del mayor resto); todo 0 si no hay nada."""
    total = sum(cantidades)
    if not total:
        return [0] * len(cantidades)
    exactos = [c * 100 / total for c in cantidades]
    enteros = [int(e) for e in exactos]
    faltan = 100 - sum(enteros)
    for i in sorted(range(len(exactos)), key=lambda i: exactos[i] - enteros[i], reverse=True)[:faltan]:
        enteros[i] += 1
    return enteros


def _fila_pagada(fila, hoy=None):
    pago = fila.get("PAGO CM_NUM", fila.get(COL_PAGO_CM))
    return bool(pago_cubre_mes_actual(pd.Series([fila.get(COL_FECHA_ULTIMO_PAGO_CM)]), pd.Series([pago]), hoy).iloc[0])


def clasificar_situacion_pago(df, hoy=None):
    """Situación de cada contrato según el pago del mes (matriz de docs/07, Contratos CM):
    al_dia = CM Running con pago este mes y estado comercial Vigente o Activación pendiente;
    por_actualizar = CM Running con pago este mes pero estado comercial Vencido o Revisar;
    sin_pago = CM Expired o sin pago que cubra este mes (el pago dura el mes siguiente al que se hizo)."""
    if df.empty or COL_ESTADO_COMERCIAL not in df.columns or COL_FECHA_ULTIMO_PAGO_CM not in df.columns:
        return pd.Series(SITUACION_SIN_PAGO, index=df.index, dtype=object)
    estado = df[COL_ESTADO_COMERCIAL].map(_estado_comercial_normalizado)
    running = df[COL_ESTADO_CM].astype(str).str.strip().str.upper() == "RUNNING" if COL_ESTADO_CM in df.columns \
        else pd.Series(False, index=df.index)
    con_pago = running & pagado_este_mes(df, hoy)
    al_dia = con_pago & estado.isin(("VIGENTE", "ACTIVACION PENDIENTE"))
    por_actualizar = con_pago & estado.isin(("VENCIDO", "REVISAR"))
    resultado = pd.Series(SITUACION_SIN_PAGO, index=df.index, dtype=object)
    resultado[al_dia] = SITUACION_AL_DIA
    resultado[por_actualizar] = SITUACION_POR_ACTUALIZAR
    return resultado


def es_running_terminado_sin_pago(fila, hoy=None):
    """CM en Running con el término ya vencido y sin pago este mes: el 3PC todavía no lo cierra."""
    if str(fila.get(COL_ESTADO_CM, "")).strip().upper() != "RUNNING":
        return False
    hoy = pd.Timestamp(hoy) if hoy is not None else pd.Timestamp.now()
    termino = pd.to_datetime(fila.get(COL_FECHA_TERMINO_CM), errors="coerce", format="%d-%m-%Y")
    if pd.isna(termino) or termino.normalize() >= hoy.normalize():
        return False
    return not _fila_pagada(fila, hoy)


def estado_comercial_por_pago(fila, hoy=None):
    """Estado al que pasa un contrato Vencido o Revisar según el pago del mes: Vigente si la unidad está
    Conectada, el CM está Running y pagó este mes; Vencido si estaba en Revisar y no pagó. None si no cambia."""
    estado = _estado_comercial_normalizado(fila.get(COL_ESTADO_COMERCIAL, ""))
    if estado not in ("VENCIDO", "REVISAR"):
        return None
    pagado = _fila_pagada(fila, hoy)
    conectada = str(fila.get(COL_ESTADO_ACTIVACION, "")).strip().upper() == "CONECTADO"
    running = str(fila.get(COL_ESTADO_CM, "")).strip().upper() == "RUNNING"
    if pagado and conectada and running:
        return "Vigente"
    if estado == "REVISAR" and not pagado:
        return "Vencido"
    return None


def cambio_opcional_a_cm(tipo_cm, forma_actual):
    """Provisión, Conversión o Venta con un tipo de CM del 3PC: pasarlas a
    CMG/CMB/CMS y facturación CM es opcional (interruptor del resumen). Las
    formas de FORMAS_QUE_PASAN_A_CM pasan siempre y no entran aquí. Devuelve
    los cambios o None."""
    from src.core.constants import VALOR_TIPO_FACT_CM
    forma_cm = TIPO_CM_FORMA_CONTRATO_MAP.get(str(tipo_cm).strip())
    actual = str(forma_actual).strip().upper()
    if forma_cm and actual not in FORMAS_QUE_PASAN_A_CM and actual != forma_cm.upper():
        return {COL_FORMA_CONTRATO: forma_cm, COL_TIPO_FACTURACION: VALOR_TIPO_FACT_CM}
    return None


def calcular_cambios_forma_facturacion(df_master, cambios_comercial, cambios_opcionales=None):
    """Qué cambia en FORMA DE CONTRATO y TIPO DE FACTURACION con un import del
    3PC, para avisarlo antes de inyectar: cuántas unidades cambian siempre y de
    qué valor a cuál, cuántas están conectadas o desconectadas, y las unidades
    Provisión, Conversión o Venta que el interruptor puede pasar a CM
    (`cambios_opcionales`, {vin: cambios}). Compara contra el valor actual de
    `df_master`; no modifica nada."""
    from collections import Counter

    resultado = {"forma": [], "tipo": [], "unidades": 0, "conectadas": 0, "desconectadas": 0, "otras": 0,
                 "cm_otra_forma": {}, "opcionales": []}
    if not cambios_comercial or df_master is None or df_master.empty or COL_VIN not in df_master.columns:
        return resultado

    df_idx = df_master.set_index(df_master[COL_VIN].astype(str).str.strip().str.upper())
    df_idx = df_idx[~df_idx.index.duplicated(keep="last")]

    def valor(fila, col):
        texto = str(fila.get(col, "")).strip()
        return "-" if texto.lower() in ("", "nan", "none") else texto

    formas, tipos = Counter(), Counter()
    otra_forma = {}
    for vin, data in cambios_comercial.items():
        if vin not in df_idx.index:
            continue
        cambios = data.get("cambios", {})
        fila = df_idx.loc[vin]
        forma_ant, tipo_ant = valor(fila, COL_FORMA_CONTRATO), valor(fila, COL_TIPO_FACTURACION)
        cambia_forma = COL_FORMA_CONTRATO in cambios and str(cambios[COL_FORMA_CONTRATO]).strip().upper() != forma_ant.upper()
        cambia_tipo = COL_TIPO_FACTURACION in cambios and str(cambios[COL_TIPO_FACTURACION]).strip().upper() != tipo_ant.upper()
        if cambia_forma:
            formas[(forma_ant, str(cambios[COL_FORMA_CONTRATO]).strip())] += 1
        if cambia_tipo:
            tipos[(tipo_ant, str(cambios[COL_TIPO_FACTURACION]).strip())] += 1
        if cambia_forma or cambia_tipo:
            resultado["unidades"] += 1
            activacion = valor(fila, COL_ESTADO_ACTIVACION).upper()
            if activacion == "CONECTADO":
                resultado["conectadas"] += 1
            elif activacion == "DESCONECTADO":
                resultado["desconectadas"] += 1
            else:
                resultado["otras"] += 1

    opcionales = Counter()
    for vin, cambios in (cambios_opcionales or {}).items():
        if vin not in df_idx.index:
            continue
        forma_ant = valor(df_idx.loc[vin], COL_FORMA_CONTRATO)
        otra_forma.setdefault(forma_ant.upper(), []).append(vin)
        opcionales[(forma_ant.upper(), str(cambios[COL_FORMA_CONTRATO]).strip())] += 1

    resultado["forma"] = formas.most_common()
    resultado["tipo"] = tipos.most_common()
    resultado["opcionales"] = opcionales.most_common()
    resultado["cm_otra_forma"] = dict(sorted(otra_forma.items(), key=lambda kv: -len(kv[1])))
    return resultado


def construir_registro_nuevo_desde_contrato_cm(vin, fila_cm, candidato=None):
    """Arma el registro completo de una unidad nueva de Comercial a partir
    de un VIN que trae el Excel de Contratos CM (3PC de Javiera) pero que
    todavia no tiene ficha en Comercial. Mismo patron que
    provisiones.py::_construir_registro_nuevo_desde_provisiones (reutiliza
    los defaults de comercial_agregar.py, no reinventa reglas de negocio),
    pero al reves: aca SI hay datos reales de contrato CM (N CONTRATO 3PC,
    fechas, tipo, estado, pago -- ya vienen en `fila_cm`, la misma forma
    que arma importar_excel_javiera) y NO hay plan/duracion de Provisiones,
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
        COL_ULTIMO_PAGO_CM: fila_cm.get(COL_ULTIMO_PAGO_CM, ''),
        COL_FECHA_ULTIMO_PAGO_CM: fila_cm.get(COL_FECHA_ULTIMO_PAGO_CM, ''),
        'OBSERVACIONES': 'Viene de Contratos CM (3PC)',
        'ETAPA GESTIÓN': etapa_gestion,
    }
