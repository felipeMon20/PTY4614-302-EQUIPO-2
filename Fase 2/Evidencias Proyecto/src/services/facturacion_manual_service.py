"""Logica de datos de Facturacion Manual, separada de src/ui/facturacion_manual.py
(mismo patron que src/services/provisiones_services.py): Python/pandas puro, sin
PyQt6. Trabaja siempre sobre una copia de DataManager().df_master (PruebasFM.xlsx
ya cargado en memoria) -- nunca lee el Excel de nuevo.

Valores y columnas reales confirmados contra PruebasFM.xlsx de produccion (ver
informe de investigacion de la carpeta real de Facturacion Manual, 19-09-2026):
el valor de TIPO DE FACTURACION es "FACTURACIÓN MANUAL" (con tilde) -- se
reutiliza la constante ya existente en src.core.constants, no se redefine aqui.

Fuera de alcance de esta fase (ver informe): OC/HES, precio UF, monto CLP y
cualquier dato que solo exista en 'Facturación Manual - BBDD.xlsx' real, no en
PruebasFM.xlsx.
"""

import pandas as pd

from src.core.constants import (
    COL_TIPO_FACTURACION, VALOR_TIPO_FACT_FACTURACION_MANUAL,
    COL_RAZON_SOCIAL, COL_RUT, COL_VIN, COL_CHASIS,
    COL_TIPO_SERVICIO, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION,
    COL_FLOTA_VC, COL_MODELO,
)

# Columnas mostradas en el nivel 2 (tarjetas de unidades de una empresa ya
# elegida en el nivel 1, ver src/ui/facturacion_manual.py). Definidas junto
# al usuario (19-09-2026): RAZÓN SOCIAL/RUT no se repiten aquí porque ya se
# conocen por el nivel 1 (quedan solo en el título de la pantalla).
COLUMNAS_DETALLE_EMPRESA = [
    COL_VIN, COL_CHASIS, COL_TIPO_SERVICIO, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION,
]


def filtrar_facturacion_manual(df_master):
    """Devuelve solo las filas con TIPO DE FACTURACION == 'FACTURACIÓN MANUAL'
    del contrato actual de cada VIN, sin los contratos en Baja que ya no tienen
    pendientes (la unidad dejó de facturarse). No modifica df_master."""
    if df_master.empty or COL_TIPO_FACTURACION not in df_master.columns:
        return pd.DataFrame(columns=df_master.columns)
    from src.services.comercial_services import contratos_actuales, excluir_contratos_finalizados_inactivos
    vigentes = excluir_contratos_finalizados_inactivos(contratos_actuales(df_master))
    return vigentes[vigentes[COL_TIPO_FACTURACION] == VALOR_TIPO_FACT_FACTURACION_MANUAL].copy()


def seleccionar_columnas_detalle(df_filtrado):
    """Recorta df_filtrado a COLUMNAS_DETALLE_EMPRESA, conservando solo las
    que realmente existan (mismo criterio que ContratosModule.load_data:
    'cols_disp = [c for c in cols_ideales if c in df_master.columns]')."""
    cols_disp = [c for c in COLUMNAS_DETALLE_EMPRESA if c in df_filtrado.columns]
    return df_filtrado[cols_disp].copy()


def obtener_empresas(df_filtrado):
    """Una fila por empresa (RAZÓN SOCIAL unica dentro del universo ya
    filtrado a Facturacion Manual), con su RUT y la cantidad de unidades/VIN
    asociadas (dato derivado del propio df, no inventado)."""
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


def obtener_unidades_empresa(df_filtrado, empresa):
    """Filas de df_filtrado correspondientes a una sola empresa (RAZÓN
    SOCIAL exacta), ya recortadas a COLUMNAS_DETALLE_EMPRESA."""
    if df_filtrado.empty or COL_RAZON_SOCIAL not in df_filtrado.columns:
        return pd.DataFrame(columns=COLUMNAS_DETALLE_EMPRESA)

    df_empresa = df_filtrado[df_filtrado[COL_RAZON_SOCIAL] == empresa]
    return seleccionar_columnas_detalle(df_empresa)


# Columnas incluidas en el contexto de facturacion (ver construir_contexto_empresa):
# unicamente columnas confirmadas en PruebasFM.xlsx (BBDD (2)) real. FLOTA VC y
# MODELO se agregan aqui ademas de COLUMNAS_DETALLE_EMPRESA porque son las
# columnas de df_master mas cercanas a 'Flota'/'Nombre' de los documentos EDP
# reales encontrados en la carpeta de Facturacion Manual (ver informe de
# investigacion, 19-09-2026) -- con la salvedad de que 'Nombre' en esos
# documentos es una patente y no existe ninguna columna de patente en
# PruebasFM (ver PENDIENTE DE CONFIRMAR CON CONTRAPARTE COMERCIAL en el informe de esta
# fase). No se agrega nada mas: precio UF, monto CLP, N° OC, HES y CC solo
# existen en 'Facturación Manual - BBDD.xlsx' real, que esta fase
# deliberadamente no conecta a la aplicacion.
COLUMNAS_CONTEXTO_UNIDAD = [
    COL_VIN, COL_CHASIS, COL_TIPO_SERVICIO, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION,
    COL_FLOTA_VC, COL_MODELO,
]

_ALIAS_CONTEXTO_UNIDAD = {
    COL_VIN: "vin",
    COL_CHASIS: "chasis",
    COL_TIPO_SERVICIO: "tipo_servicio",
    COL_ESTADO_COMERCIAL: "estado_comercial",
    COL_ESTADO_ACTIVACION: "estado_activacion",
    COL_FLOTA_VC: "flota_vc",
    COL_MODELO: "modelo",
}


def construir_contexto_empresa(empresa, df_filtrado):
    """Contexto minimo para la futura plantilla DOCX, con SOLO datos
    confirmados o derivados directamente de df_master (PruebasFM.xlsx) para
    una empresa ya filtrada a Facturacion Manual. No incluye precio UF,
    monto CLP, N° OC, HES ni CC: esos dependen de 'Facturación Manual -
    BBDD.xlsx' real y de decisiones aun pendientes con la contraparte comercial (ver informe
    de esta fase, 19-09-2026) -- agregarlos aqui como claves en None seria
    inventar estructura sin un dato real detras. Cuando esa informacion se
    confirme, se agrega como una clave nueva de este mismo dict, no como un
    contexto separado."""
    df_empresa = df_filtrado[df_filtrado[COL_RAZON_SOCIAL] == empresa] if (
        not df_filtrado.empty and COL_RAZON_SOCIAL in df_filtrado.columns
    ) else df_filtrado.iloc[0:0]

    rut = None
    if COL_RUT in df_empresa.columns and not df_empresa.empty:
        primer_rut = df_empresa[COL_RUT].iloc[0]
        rut = None if pd.isna(primer_rut) else primer_rut

    unidades = []
    columnas_disponibles = [c for c in COLUMNAS_CONTEXTO_UNIDAD if c in df_empresa.columns]
    for _, fila in df_empresa[columnas_disponibles].iterrows():
        unidades.append({_ALIAS_CONTEXTO_UNIDAD[col]: fila[col] for col in columnas_disponibles})

    return {
        "empresa": {"razon_social": empresa, "rut": rut},
        "unidades": unidades,
        "cantidad_unidades": len(unidades),
    }


# =========================================================
# FACTURACIÓN MENSUAL POR EMPRESA (facturacionManual.xlsx, 05-10-2026)
# Una fila por (período, cliente): tipo (OC / Factura manual), N° de unidades,
# precio unitario mensual en UF, pago en CLP y etapa de gestión.
# =========================================================
import copy
import os
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

MESES_ES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
            "Septiembre", "Octubre", "Noviembre", "Diciembre"]
ETAPA_PENDIENTE = "Pendiente"
ETAPA_FACTURADO = "Facturado"
ETAPAS_FM = [ETAPA_PENDIENTE, ETAPA_FACTURADO]
TIPO_OC = "OC"
TIPO_FACTURA_MANUAL = "FACTURA MANUAL"

COLS_FM_XLSX = {
    "periodo": "Periodo", "cliente": "Cliente", "rut": "Rut", "tipo": "Tipo", "unidades": "N° Unidades",
    "precio": "Precio unitario mensual", "pago": "Facturacion Pago", "etapa": "Etapa gestion",
}
COLUMNAS_REGISTROS_FM = ["FILA", "PERIODO", "CLIENTE", "RUT", "TIPO", "UNIDADES", "PRECIO", "PAGO", "ETAPA"]


def normalizar_rut(valor):
    """Solo dígitos y K en mayúscula (el Excel trae 761961918 y PruebasFM
    puede traer puntos o guion)."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    if texto.endswith(".0"):
        texto = texto[:-2]
    return "".join(c for c in texto.upper() if c.isdigit() or c == "K")


def formatear_rut(valor):
    rut = normalizar_rut(valor)
    if len(rut) < 2:
        return rut or "-"
    cuerpo, dv = rut[:-1], rut[-1]
    return f"{int(cuerpo):,}".replace(",", ".") + "-" + dv if cuerpo.isdigit() else rut


def _numero(valor):
    """Número o None si la celda trae '-', texto o está vacía."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return None if pd.isna(valor) else float(valor)
    try:
        return float(str(valor).strip().replace(",", "."))
    except ValueError:
        return None


def _texto(valor):
    """Texto de una celda; vacío si la celda está vacía (NaN)."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    return str(valor).strip()


def clave_periodo(ts):
    return f"{ts.year}-{ts.month:02d}"


def texto_periodo(ts):
    return f"{MESES_ES[ts.month - 1]} {ts.year}"


def leer_registros_fm(ruta):
    """DataFrame con una fila por registro de la hoja. FILA es el número de
    fila de Excel (para escribir de vuelta). Las filas sin período o sin
    cliente se ignoran."""
    if not ruta or not os.path.exists(ruta):
        return pd.DataFrame(columns=COLUMNAS_REGISTROS_FM)
    bruto = pd.read_excel(ruta, sheet_name=0, dtype=object)
    registros = []
    for pos, fila in enumerate(bruto.to_dict("records"), start=2):
        periodo = pd.to_datetime(fila.get(COLS_FM_XLSX["periodo"]), errors="coerce")
        cliente = _texto(fila.get(COLS_FM_XLSX["cliente"]))
        if pd.isna(periodo) or not cliente or cliente.lower() == "nan":
            continue
        unidades = _numero(fila.get(COLS_FM_XLSX["unidades"]))
        etapa = _texto(fila.get(COLS_FM_XLSX["etapa"]))
        registros.append({
            "FILA": pos, "PERIODO": periodo.to_pydatetime(), "CLIENTE": cliente,
            "RUT": normalizar_rut(fila.get(COLS_FM_XLSX["rut"])),
            "TIPO": _texto(fila.get(COLS_FM_XLSX["tipo"])).upper(),
            "UNIDADES": int(unidades) if unidades is not None else 0,
            "PRECIO": _numero(fila.get(COLS_FM_XLSX["precio"])),
            "PAGO": _numero(fila.get(COLS_FM_XLSX["pago"])),
            "ETAPA": etapa if etapa in ETAPAS_FM else "",
        })
    return pd.DataFrame(registros, columns=COLUMNAS_REGISTROS_FM)


def periodos_disponibles(df_registros):
    """Claves 'AAAA-MM' de más reciente a más antigua."""
    if df_registros.empty:
        return []
    return sorted({clave_periodo(p) for p in df_registros["PERIODO"]}, reverse=True)


def periodo_por_defecto(claves, hoy=None):
    """El período más reciente anterior al mes en curso (se factura el mes
    vencido); si no hay, el más reciente que exista."""
    if not claves:
        return ""
    hoy = hoy or datetime.now()
    actual = f"{hoy.year}-{hoy.month:02d}"
    anteriores = [c for c in claves if c < actual]
    return max(anteriores) if anteriores else max(claves)


def etiqueta_periodo(clave):
    anio, mes = clave.split("-")
    return f"{MESES_ES[int(mes) - 1]} {anio}"


def calcular_totales(precio_uf, unidades, uf):
    """(neto_uf, neto_clp) con Decimal para evitar errores de coma flotante.
    neto_uf redondeado a 2 decimales y neto_clp a pesos enteros; None si falta
    el precio o la UF."""
    if precio_uf is None:
        return None, None
    neto_uf = (Decimal(str(precio_uf)) * Decimal(int(unidades))).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if not uf or uf <= 0:
        return float(neto_uf), None
    neto_clp = (Decimal(str(precio_uf)) * Decimal(int(unidades)) * Decimal(str(uf))).quantize(Decimal("1"), ROUND_HALF_UP)
    return float(neto_uf), int(neto_clp)


def parsear_precio(texto):
    """Precio escrito por el usuario ('0,55' o '0.55'); None si está vacío o
    no es un número positivo."""
    valor = _numero(texto)
    return valor if valor is not None and valor > 0 else None


def unidades_de_rut(df_filtrado, rut):
    """Unidades de PruebasFM (ya filtradas a Facturación Manual) de un RUT."""
    if df_filtrado.empty or COL_RUT not in df_filtrado.columns:
        return df_filtrado.iloc[0:0]
    objetivo = normalizar_rut(rut)
    return df_filtrado[df_filtrado[COL_RUT].map(normalizar_rut) == objetivo]


def nivel_servicio_dominante(df_unidades):
    """('BASICO'|'MEDIO'|'FULL', con_civ) más frecuente en TIPO DE SERVICIO."""
    if df_unidades.empty or COL_TIPO_SERVICIO not in df_unidades.columns:
        return "MEDIO", False
    serie = df_unidades[COL_TIPO_SERVICIO].astype(str).str.strip().str.upper()
    serie = serie[~serie.isin(["", "-", "NAN"])]
    if serie.empty:
        return "MEDIO", False
    tipo = serie.value_counts().idxmax()
    civ = "CIV" in tipo
    base = tipo.replace("+ CIV", "").replace("CIV", "").replace("Á", "A").strip()
    return (base if base in ("BASICO", "MEDIO", "FULL") else "MEDIO"), civ


def guardar_cambios_fm(ruta, cambios):
    """Escribe en facturacionManual.xlsx. `cambios` es una lista de
    {'fila': n, 'cliente': str, 'periodo': 'AAAA-MM', 'valores': {clave: valor}}
    con claves de COLS_FM_XLSX. Verifica que la fila siga siendo ese cliente y
    período antes de escribir, hace backup previo y reemplaza el archivo solo
    si todo salió bien. Devuelve (ok, mensaje)."""
    import openpyxl
    from src.core.excel_writer import ExcelWriter

    if not cambios:
        return True, ""
    writer = ExcelWriter()
    writer._crear_backup(ruta)
    if not writer.last_backup_ok:
        return False, "No se pudo crear la copia de seguridad; no se guardó nada."
    try:
        wb = openpyxl.load_workbook(ruta)
        ws = wb.worksheets[0]
        cabeceras = {str(c.value).strip(): i for i, c in enumerate(ws[1], start=1) if c.value}
        for cambio in cambios:
            fila = cambio["fila"]
            cliente = str(ws.cell(fila, cabeceras[COLS_FM_XLSX["cliente"]]).value or "").strip()
            periodo = pd.to_datetime(ws.cell(fila, cabeceras[COLS_FM_XLSX["periodo"]]).value, errors="coerce")
            if cliente != cambio["cliente"] or pd.isna(periodo) or clave_periodo(periodo) != cambio["periodo"]:
                return False, "El Excel cambió desde que se cargó. Recarga e inténtalo de nuevo."
            for clave, valor in cambio["valores"].items():
                ws.cell(fila, cabeceras[COLS_FM_XLSX[clave]]).value = valor
        temporal = os.path.join(tempfile.gettempdir(), "facturacionManual_guardado.xlsx")
        wb.save(temporal)
        shutil.copy2(temporal, ruta)
    except PermissionError:
        return False, "El archivo está abierto en otro programa. Ciérralo e inténtalo de nuevo."
    except Exception as e:
        return False, f"No se pudo guardar: {e}"
    return True, ""


# =========================================================
# LISTA DEL PERÍODO: PruebasFM define quién se factura y cuántas unidades
# tiene; facturacionManual.xlsx aporta tipo, precio, pago y etapa del mes
# (05-10-2026).
# =========================================================
ORIGEN_EXCEL = "excel"
ORIGEN_PRUEBASFM = "pruebasfm"
COLUMNAS_REGISTROS_PERIODO = COLUMNAS_REGISTROS_FM + ["UNIDADES_EXCEL", "UNIDADES_PF", "ORIGEN"]


def resumen_unidades_fm(df_fm):
    """Una fila por RUT con unidades en Facturación Manual: RUT, RAZON (la más
    frecuente) y N (cantidad de unidades)."""
    if df_fm.empty or COL_RUT not in df_fm.columns or COL_RAZON_SOCIAL not in df_fm.columns:
        return pd.DataFrame(columns=["RUT", "RAZON", "N"])
    d = pd.DataFrame({
        "RUT": df_fm[COL_RUT].map(normalizar_rut),
        "RAZON": df_fm[COL_RAZON_SOCIAL].astype(str).str.strip(),
    })
    d = d[d["RUT"] != ""]
    if d.empty:
        return pd.DataFrame(columns=["RUT", "RAZON", "N"])
    grupos = d.groupby("RUT")
    return pd.DataFrame({
        "RUT": list(grupos.size().index),
        "RAZON": [g["RAZON"].value_counts().idxmax() for _, g in grupos],
        "N": [int(n) for n in grupos.size().values],
    })


def armar_registros_periodo(df_excel, df_fm, clave, incluir_sin_registro):
    """Registros de un período ('AAAA-MM').

    - Cada fila del Excel del período, con UNIDADES tomadas de PruebasFM por
      RUT. Un registro ya Facturado conserva las unidades del Excel (su pago
      se calculó con esa cantidad); lo mismo una fila sin RUT.
    - Si `incluir_sin_registro`, cada RUT con unidades en PruebasFM que no
      tiene fila ese mes (ORIGEN pruebasfm, FILA None).
    UNIDADES_EXCEL y UNIDADES_PF permiten avisar las diferencias."""
    resumen = resumen_unidades_fm(df_fm)
    n_pf = dict(zip(resumen["RUT"], resumen["N"]))
    registros = []
    ruts_con_fila = set()
    if not df_excel.empty:
        deldf = df_excel[df_excel["PERIODO"].map(clave_periodo) == clave]
        for r in deldf.to_dict("records"):
            en_pf = int(n_pf.get(r["RUT"], 0)) if r["RUT"] else int(r["UNIDADES"])
            conserva_excel = r["ETAPA"] == ETAPA_FACTURADO or not r["RUT"]
            r = dict(r)
            r["UNIDADES_EXCEL"] = int(r["UNIDADES"])
            r["UNIDADES_PF"] = en_pf
            r["UNIDADES"] = int(r["UNIDADES"]) if conserva_excel else en_pf
            r["ORIGEN"] = ORIGEN_EXCEL
            registros.append(r)
            if r["RUT"]:
                ruts_con_fila.add(r["RUT"])
    if incluir_sin_registro and not resumen.empty:
        anio, mes = (int(x) for x in clave.split("-"))
        for rut, razon, n in zip(resumen["RUT"], resumen["RAZON"], resumen["N"]):
            if rut in ruts_con_fila:
                continue
            registros.append({
                "FILA": None, "PERIODO": datetime(anio, mes, 1), "CLIENTE": razon, "RUT": rut, "TIPO": "",
                "UNIDADES": int(n), "PRECIO": None, "PAGO": None, "ETAPA": "",
                "UNIDADES_EXCEL": 0, "UNIDADES_PF": int(n), "ORIGEN": ORIGEN_PRUEBASFM,
            })
    return pd.DataFrame(registros, columns=COLUMNAS_REGISTROS_PERIODO)


def periodo_anterior(hoy=None):
    """Clave 'AAAA-MM' del mes anterior al actual (el que se está facturando)."""
    hoy = hoy or datetime.now()
    anio, mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    return f"{anio}-{mes:02d}"


def guardar_registros_fm(ruta, cambios, nuevas=None):
    """Como guardar_cambios_fm, y además agrega filas nuevas al final de la
    hoja. `nuevas` es una lista de {'periodo': 'AAAA-MM', 'valores': {clave:
    valor}} con claves de COLS_FM_XLSX (periodo, cliente, rut, tipo, unidades,
    precio, pago, etapa). Todo en un solo guardado con backup previo."""
    import openpyxl
    from src.core.excel_writer import ExcelWriter

    nuevas = nuevas or []
    if not cambios and not nuevas:
        return True, ""
    writer = ExcelWriter()
    writer._crear_backup(ruta)
    if not writer.last_backup_ok:
        return False, "No se pudo crear la copia de seguridad; no se guardó nada."
    try:
        wb = openpyxl.load_workbook(ruta)
        ws = wb.worksheets[0]
        cabeceras = {str(c.value).strip(): i for i, c in enumerate(ws[1], start=1) if c.value}
        for cambio in cambios:
            fila = cambio["fila"]
            cliente = str(ws.cell(fila, cabeceras[COLS_FM_XLSX["cliente"]]).value or "").strip()
            periodo = pd.to_datetime(ws.cell(fila, cabeceras[COLS_FM_XLSX["periodo"]]).value, errors="coerce")
            if cliente != cambio["cliente"] or pd.isna(periodo) or clave_periodo(periodo) != cambio["periodo"]:
                return False, "El Excel cambió desde que se cargó. Recarga e inténtalo de nuevo."
            for clave, valor in cambio["valores"].items():
                ws.cell(fila, cabeceras[COLS_FM_XLSX[clave]]).value = valor
        siguiente = max((r for r in range(2, ws.max_row + 1)
                         if ws.cell(r, cabeceras[COLS_FM_XLSX["cliente"]]).value), default=1) + 1
        for nueva in nuevas:
            anio, mes = (int(x) for x in nueva["periodo"].split("-"))
            valores = {"periodo": datetime(anio, mes, 1), **nueva["valores"]}
            for clave, valor in valores.items():
                celda = ws.cell(siguiente, cabeceras[COLS_FM_XLSX[clave]])
                celda.value = valor
                if siguiente > 2:
                    celda._style = copy.copy(ws.cell(siguiente - 1, celda.column)._style)
            siguiente += 1
        temporal = os.path.join(tempfile.gettempdir(), "facturacionManual_guardado.xlsx")
        wb.save(temporal)
        shutil.copy2(temporal, ruta)
    except PermissionError:
        return False, "El archivo está abierto en otro programa. Ciérralo e inténtalo de nuevo."
    except Exception as e:
        return False, f"No se pudo guardar: {e}"
    return True, ""
