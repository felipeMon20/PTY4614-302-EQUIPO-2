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

import re
import unicodedata

import pandas as pd

from src.core.constants import (
    COL_TIPO_FACTURACION, VALOR_TIPO_FACT_FACTURACION_MANUAL,
    COL_RAZON_SOCIAL, COL_RUT, COL_VIN, COL_CHASIS,
    COL_TIPO_SERVICIO, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION,
    COL_FLOTA_VC, COL_MODELO, VALOR_ESTADO_COMERCIAL_VIGENTE, ESTADO_CONECTADO,
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
    del contrato actual de cada VIN, que además estén VIGENTE y CONECTADO: las
    unidades en Activación Pendiente o Activando todavía no se facturan, y los
    contratos en Baja ya dejaron de facturarse. No modifica df_master."""
    if df_master.empty or COL_TIPO_FACTURACION not in df_master.columns:
        return pd.DataFrame(columns=df_master.columns)
    from src.services.comercial_services import contratos_actuales, excluir_contratos_finalizados_inactivos
    vigentes = excluir_contratos_finalizados_inactivos(contratos_actuales(df_master))
    filtrado = vigentes[vigentes[COL_TIPO_FACTURACION] == VALOR_TIPO_FACT_FACTURACION_MANUAL]
    for columna, valor in ((COL_ESTADO_COMERCIAL, VALOR_ESTADO_COMERCIAL_VIGENTE), (COL_ESTADO_ACTIVACION, ESTADO_CONECTADO)):
        if columna in filtrado.columns:
            filtrado = filtrado[filtrado[columna].astype(str).str.strip().str.upper() == valor]
    return filtrado.copy()


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
# PruebasFM (ver PENDIENTE DE CONFIRMAR CON JAVIERA en el informe de esta
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
    BBDD.xlsx' real y de decisiones aun pendientes con Javiera (ver informe
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


def periodos_con_sin_registro(claves, hoy=None):
    """Períodos donde se listan las empresas de PruebasFM que aún no tienen fila:
    el que se está facturando (mes vencido) y el mes en curso, para poder
    adelantar el trabajo."""
    hoy = hoy or datetime.now()
    return {periodo_por_defecto(claves, hoy), f"{hoy.year}-{hoy.month:02d}"}


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


def uf_de_facturacion(precio_uf, unidades, pago_clp):
    """UF con la que se calculó un pago ya registrado (pago / (precio × unidades)),
    a 4 decimales para que al recalcular dé el mismo pago; None si falta algún dato."""
    if precio_uf is None or pago_clp is None or not unidades or precio_uf <= 0 or pago_clp <= 0:
        return None
    return round(float(Decimal(str(pago_clp)) / (Decimal(str(precio_uf)) * Decimal(int(unidades)))), 4)


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


def _flota_serie(df):
    """FLOTA VC de cada unidad; la razón social cuando la flota viene vacía."""
    razon = df[COL_RAZON_SOCIAL].astype(str).str.strip() if COL_RAZON_SOCIAL in df.columns else pd.Series("", index=df.index)
    if COL_FLOTA_VC not in df.columns:
        return razon
    flota = df[COL_FLOTA_VC].astype(str).str.strip()
    return flota.where(~flota.str.upper().isin(["", "-", "NAN", "NONE"]), razon)


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
    base = tipo.replace("+ CIV", "").replace("CIV", "").replace("+ SZ", "").replace("SZ", "").replace("Á", "A").strip(" +")
    return (base if base in ("BASICO", "MEDIO", "FULL") else "MEDIO"), civ


def tiene_safety_zone(df_unidades):
    """True si el plan más frecuente de la flota incluye Safety Zone (SZ)."""
    if df_unidades.empty or COL_TIPO_SERVICIO not in df_unidades.columns:
        return False
    serie = df_unidades[COL_TIPO_SERVICIO].astype(str).str.strip().str.upper()
    serie = serie[~serie.isin(["", "-", "NAN"])]
    if serie.empty:
        return False
    partes = {p.strip() for p in serie.value_counts().idxmax().split("+")[1:]}
    return "SZ" in partes


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
COLUMNAS_REGISTROS_PERIODO = COLUMNAS_REGISTROS_FM + [
    "UNIDADES_EXCEL", "UNIDADES_PF", "ORIGEN", "FLOTA", "CLAVE_FLOTA", "GRUPO", "RUTS", "FILAS"]


def clave_flota(texto):
    """FLOTA VC sin tildes, mayúsculas ni espacios repetidos, para comparar nombres."""
    normal = unicodedata.normalize('NFKD', " ".join(str(texto).split()))
    return "".join(c for c in normal if not unicodedata.combining(c)).upper()


def resumen_unidades_fm(df_fm):
    """Una fila por razón social (RUT) y FLOTA VC con unidades en Facturación
    Manual: RUT, RAZON (razón social más frecuente), FLOTA (nombre más
    frecuente), CLAVE_FLOTA (clave_flota) y N (unidades)."""
    columnas = ["RUT", "RAZON", "FLOTA", "CLAVE_FLOTA", "N"]
    if df_fm.empty or COL_RUT not in df_fm.columns or COL_RAZON_SOCIAL not in df_fm.columns:
        return pd.DataFrame(columns=columnas)
    flota = _flota_serie(df_fm)
    d = pd.DataFrame({
        "RUT": df_fm[COL_RUT].map(normalizar_rut), "RAZON": df_fm[COL_RAZON_SOCIAL].astype(str).str.strip(),
        "FLOTA": flota, "CLAVE_FLOTA": flota.map(clave_flota)})
    d = d[d["RUT"] != ""]
    if d.empty:
        return pd.DataFrame(columns=columnas)
    filas = [(rut, g["RAZON"].value_counts().idxmax(), g["FLOTA"].value_counts().idxmax(), clave, len(g))
             for (rut, clave), g in d.groupby(["RUT", "CLAVE_FLOTA"])]
    return pd.DataFrame(filas, columns=columnas)


def _asignar_flotas(filas, n_rut):
    """Clave de flota de cada fila del Excel del período (None si no tiene RUT o
    su RUT no tiene unidades). Primero por el nombre de la fila, que puede ser la
    flota o llevarla entre paréntesis ("RAZÓN SOCIAL (FLOTA)"); el resto toma la
    flota más grande de su RUT que aún no tenga fila de ese RUT."""
    por_rut = {}
    for rut, clave in n_rut:
        por_rut.setdefault(rut, []).append(clave)
    asignadas, tomadas = [None] * len(filas), set()
    for i, r in enumerate(filas):
        if not r["RUT"]:
            continue
        nombre = clave_flota(r["CLIENTE"])
        coinciden = [c for c in por_rut.get(r["RUT"], []) if (r["RUT"], c) not in tomadas
                     and (c == nombre or (len(c) >= 6 and c in nombre))]
        if coinciden:
            asignadas[i] = max(coinciden, key=len)
            tomadas.add((r["RUT"], asignadas[i]))
    for i, r in enumerate(filas):
        if asignadas[i] is not None or not r["RUT"] or r["RUT"] not in por_rut:
            continue
        libres = [c for c in por_rut[r["RUT"]] if (r["RUT"], c) not in tomadas] or por_rut[r["RUT"]]
        asignadas[i] = max(libres, key=lambda c: n_rut[(r["RUT"], c)])
        tomadas.add((r["RUT"], asignadas[i]))
    return asignadas


def _primero(valores, vacio=None):
    return next((v for v in valores if v is not None and not (isinstance(v, float) and pd.isna(v)) and v != ""), vacio)


def _registro_base(periodo, filas):
    """Campos comunes de un registro a partir de sus filas del Excel (precio y
    tipo de la primera que los tenga, pago sumado, etapa Facturado solo si
    todas lo están)."""
    etapas = [f["ETAPA"] for f in filas]
    pagos = [f["PAGO"] for f in filas if f["PAGO"] is not None and not pd.isna(f["PAGO"])]
    if filas and all(e == ETAPA_FACTURADO for e in etapas):
        etapa = ETAPA_FACTURADO
    else:
        etapa = ETAPA_PENDIENTE if any(etapas) else ""
    return {
        "FILA": filas[0]["FILA"] if filas else None, "PERIODO": periodo,
        "TIPO": _primero([f["TIPO"] for f in filas], ""), "PRECIO": _primero([f["PRECIO"] for f in filas]),
        "PAGO": sum(pagos) if pagos else None, "ETAPA": etapa,
        "UNIDADES_EXCEL": sum(int(f["UNIDADES"]) for f in filas), "FILAS": filas,
    }


def armar_registros_periodo(df_excel, df_fm, clave, incluir_sin_registro):
    """Registros de un período ('AAAA-MM'), uno por razón social (RUT) y FLOTA
    VC: cada razón social se factura y se envía por separado, con su propio
    precio, total, PDF y Excel; los montos nunca se suman entre razones.

    - CLIENTE es la razón social, FLOTA la FLOTA VC (agrupa las razones en la
      lista) y GRUPO la clave de esa agrupación. Sus unidades salen de
      PruebasFM; FILAS son las filas del Excel del período que le corresponden
      (cada fila se liga a la flota de su RUT, o por nombre si el RUT tiene
      varias flotas). Un registro Facturado conserva las unidades del Excel (su
      pago se calculó con esa cantidad).
    - Una fila del Excel sin RUT o con un RUT sin unidades en PruebasFM queda
      como registro propio (su propio GRUPO).
    - Si `incluir_sin_registro`, cada razón social con unidades en PruebasFM que
      no tiene fila ese mes (ORIGEN pruebasfm).
    UNIDADES_EXCEL y UNIDADES_PF permiten avisar las diferencias."""
    anio, mes = (int(x) for x in clave.split("-"))
    periodo = datetime(anio, mes, 1)
    resumen = resumen_unidades_fm(df_fm)
    n_rut = {(r, c): int(n) for r, c, n in zip(resumen["RUT"], resumen["CLAVE_FLOTA"], resumen["N"])}
    razon_de = {(r, c): z for r, c, z in zip(resumen["RUT"], resumen["CLAVE_FLOTA"], resumen["RAZON"])}
    nombres_flota = {}
    for c, nombre, n in zip(resumen["CLAVE_FLOTA"], resumen["FLOTA"], resumen["N"]):
        nombres = nombres_flota.setdefault(c, {})
        nombres[nombre] = nombres.get(nombre, 0) + int(n)
    filas = []
    if not df_excel.empty:
        filas = [dict(f) for f in df_excel[df_excel["PERIODO"].map(clave_periodo) == clave].to_dict("records")]
    por_razon, sueltas = {}, []
    for f, c in zip(filas, _asignar_flotas(filas, n_rut)):
        if c is None:
            sueltas.append(f)
        else:
            por_razon.setdefault((f["RUT"], c), []).append(f)
    registros = []
    for (rut, c), n in n_rut.items():
        propias = por_razon.get((rut, c), [])
        if not propias and not incluir_sin_registro:
            continue
        base = _registro_base(periodo, propias)
        registros.append({
            **base, "CLIENTE": razon_de[(rut, c)], "FLOTA": max(nombres_flota[c], key=nombres_flota[c].get),
            "RUT": rut, "UNIDADES": base["UNIDADES_EXCEL"] if base["ETAPA"] == ETAPA_FACTURADO else n,
            "UNIDADES_PF": n, "ORIGEN": ORIGEN_EXCEL if propias else ORIGEN_PRUEBASFM,
            "CLAVE_FLOTA": c, "GRUPO": c, "RUTS": [(rut, n)],
        })
    for f in sueltas:
        base = _registro_base(periodo, [f])
        en_pf = 0 if f["RUT"] else int(f["UNIDADES"])
        registros.append({
            **base, "CLIENTE": f["CLIENTE"], "FLOTA": f["CLIENTE"], "RUT": f["RUT"],
            "UNIDADES": base["UNIDADES_EXCEL"] if base["ETAPA"] == ETAPA_FACTURADO or not f["RUT"] else 0,
            "UNIDADES_PF": en_pf, "ORIGEN": ORIGEN_EXCEL, "CLAVE_FLOTA": "",
            "GRUPO": f"SUELTA|{f['RUT']}|{f['CLIENTE']}|{f['FILA']}", "RUTS": [],
        })
    return pd.DataFrame(registros, columns=COLUMNAS_REGISTROS_PERIODO)


def agrupar_flotas(df_razones, visibles=None):
    """Una entrada por FLOTA VC a partir de los registros por razón social:
    FLOTA, RAZONES (sus registros, por nombre), N_RAZONES, UNIDADES, ETAPA y
    ORIGEN. Su etapa es Facturado solo si todas sus razones lo están; sin
    registro si ninguna tiene fila del mes; si no, Pendiente. No suma precios
    ni pagos: cada razón social los tiene por separado. `visibles` (registros ya
    filtrados) limita qué flotas se devuelven, pero cada una describe a todas
    sus razones."""
    if df_razones is None or df_razones.empty:
        return []
    grupos = {}
    for r in df_razones.to_dict("records"):
        grupos.setdefault(r["GRUPO"], []).append(r)
    permitidos = None if visibles is None else set(visibles["GRUPO"])
    flotas = []
    for grupo, razones in grupos.items():
        if permitidos is not None and grupo not in permitidos:
            continue
        sin_registro = all(r["ORIGEN"] == ORIGEN_PRUEBASFM for r in razones)
        if all(r["ETAPA"] == ETAPA_FACTURADO for r in razones):
            etapa = ETAPA_FACTURADO
        else:
            etapa = "" if sin_registro else ETAPA_PENDIENTE
        flotas.append({
            "GRUPO": grupo, "FLOTA": razones[0]["FLOTA"], "PERIODO": razones[0]["PERIODO"],
            "RAZONES": sorted(razones, key=lambda r: (str(r["CLIENTE"]), str(r["RUT"]))), "N_RAZONES": len(razones),
            "UNIDADES": sum(int(r["UNIDADES"]) for r in razones), "ETAPA": etapa,
            "ORIGEN": ORIGEN_PRUEBASFM if sin_registro else ORIGEN_EXCEL,
        })
    return sorted(flotas, key=lambda f: str(f["FLOTA"]))


def buscar_unidades_en_lista(df_unidades, texto):
    """Compara una lista pegada (VIN, chasis o terminación del VIN de 6 o más
    caracteres, separados por espacios, comas, punto y coma o saltos de línea)
    con las unidades de la flota abierta. Devuelve (máscara de las unidades que
    están en la lista, valores pegados que no están en la flota, cantidad de
    valores pegados distintos). Solo sirve para comprobar: no cambia las unidades
    ni el total de la flota."""
    valores = list(dict.fromkeys(t for t in re.split(r"[\s,;]+", str(texto).upper()) if t))
    n = len(df_unidades)
    if n == 0 or "VIN" not in df_unidades.columns:
        return [False] * n, valores, len(valores)
    vins = df_unidades["VIN"].astype(str).str.strip().str.upper()
    chasis = df_unidades["CHASIS"].astype(str).str.strip().str.upper() if "CHASIS" in df_unidades.columns else vins
    mascara = pd.Series(False, index=df_unidades.index)
    faltan = []
    for valor in valores:
        coincide = (vins == valor) | (chasis == valor)
        if len(valor) >= 6:
            coincide |= vins.str.endswith(valor)
        if coincide.any():
            mascara |= coincide
        else:
            faltan.append(valor)
    return mascara.tolist(), faltan, len(valores)


def unidades_de_registro(df_filtrado, registro):
    """Unidades de PruebasFM (ya filtradas a Facturación Manual) de un registro:
    las de su RUT y su flota, o todas las de su RUT si es una fila suelta del Excel."""
    unidades = unidades_de_rut(df_filtrado, registro["RUT"])
    if unidades.empty or not registro["CLAVE_FLOTA"]:
        return unidades
    return unidades[_flota_serie(unidades).map(clave_flota) == registro["CLAVE_FLOTA"]]


def armar_guardado(registro, valores, uf=None):
    """(cambios, nuevas) para escribir una razón social en el Excel, listos para
    guardar_registros_fm. `valores` son las celdas: {'etapa'} o {'precio', 'tipo'};
    con precio, el pago se calcula con las unidades de esa razón social y la UF.
    Cada fila existente se actualiza (las ya Facturadas conservan sus unidades) y,
    si no tiene fila ese mes, se crea una nueva con el nombre "RAZÓN SOCIAL
    (FLOTA)" cuando la flota no es el mismo nombre."""
    periodo = clave_periodo(registro["PERIODO"])
    unidades_rut = dict(registro["RUTS"])

    fijo_pendiente = [valores.get("precio_fijo")]

    def celdas_cobro(n):
        if fijo_pendiente[0] is not None:
            # Precio fijo: el monto neto en CLP se guarda como pago, sin precio unitario, y queda Facturado.
            # Con varias filas del mismo RUT el monto va una sola vez, en la primera
            celdas = {"tipo": valores["tipo"], "precio": "-", "etapa": ETAPA_FACTURADO}
            if fijo_pendiente[0]:
                celdas["pago"] = int(fijo_pendiente[0])
                fijo_pendiente[0] = 0
            return celdas
        celdas = {k: valores[k] for k in ("precio", "tipo") if k in valores}
        if "precio" in valores:
            pago = calcular_totales(valores["precio"], n, uf)[1]
            if pago is not None:
                celdas["pago"] = pago
        return celdas

    cambios, nuevas = [], []
    for fila in registro["FILAS"]:
        facturada = fila["ETAPA"] == ETAPA_FACTURADO
        if registro["RUTS"]:
            n = int(fila["UNIDADES"]) if facturada else unidades_rut.get(fila["RUT"], 0)
        else:
            n = int(registro["UNIDADES"])
        if "etapa" in valores:
            if fila["ETAPA"] == valores["etapa"]:
                continue
            celdas = {"etapa": valores["etapa"]}
        else:
            celdas = celdas_cobro(n)
            if not facturada:
                celdas["unidades"] = n
        cambios.append({"fila": int(fila["FILA"]), "cliente": fila["CLIENTE"], "periodo": periodo, "valores": celdas})
    con_fila = {f["RUT"] for f in registro["FILAS"]}
    for rut, n in registro["RUTS"]:
        if rut in con_fila:
            continue
        nombre = registro["CLIENTE"]
        clave_razon, clave_f = clave_flota(nombre), clave_flota(registro["FLOTA"])
        if clave_f and clave_f != clave_razon and clave_f not in clave_razon:
            nombre = f"{nombre} ({registro['FLOTA']})"
        celdas = {"cliente": nombre, "rut": int(rut) if rut.isdigit() else rut, "unidades": int(n)}
        if "etapa" in valores:
            celdas["etapa"] = valores["etapa"]
            if registro["TIPO"]:
                celdas["tipo"] = registro["TIPO"]
        else:
            celdas.update(celdas_cobro(n))
            celdas.setdefault("etapa", ETAPA_PENDIENTE)
        nuevas.append({"periodo": periodo, "valores": celdas})
    return cambios, nuevas


def armar_ajuste_a_rm(registro):
    """(cambios, nuevas) que dejan las unidades de una razón social ya facturada igual a las
    de RM_JAVI. El pago con precio por unidad se recalcula con la misma UF con que se facturó;
    el precio fijo conserva su monto. La primera fila del RUT toma todas las unidades."""
    periodo = clave_periodo(registro["PERIODO"])
    restantes = int(registro["UNIDADES_PF"])
    cambios = []
    for fila in registro["FILAS"]:
        n, restantes = restantes, 0
        anteriores = int(fila["UNIDADES"])
        if n == anteriores:
            continue
        celdas = {"unidades": n}
        precio, pago = fila["PRECIO"], fila["PAGO"]
        if isinstance(precio, (int, float)) and not pd.isna(precio) and pago is not None and not pd.isna(pago):
            uf = uf_de_facturacion(precio, anteriores, pago)
            nuevo = calcular_totales(precio, n, uf)[1] if uf else None
            if nuevo is not None:
                celdas["pago"] = nuevo
        cambios.append({"fila": int(fila["FILA"]), "cliente": fila["CLIENTE"], "periodo": periodo, "valores": celdas})
    return cambios, []


def periodo_actual(hoy=None):
    """Clave 'AAAA-MM' del mes en curso."""
    hoy = hoy or datetime.now()
    return f"{hoy.year}-{hoy.month:02d}"


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
