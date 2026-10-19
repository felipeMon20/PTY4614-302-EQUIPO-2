"""Puente entre Contactos y Correos.csv: cuando se agrega un contacto nuevo
para un CDB desde MailDialog, recalcula el correo agregado de ese CDB
reutilizando mail_sync_service.cruzar_correos_maestro() (sin modificarlo).

B-5.2 (migracion XLSX -> CSV, 18-09-2026): antes parcheaba las filas VIN
afectadas reutilizando ExcelWriter.update_cells() (openpyxl puro, carga el
workbook, ubica la fila por 'keys' y edita la celda) -- update_cells() es
generico y lo usan otros modulos (Comercial, Provisiones) sobre archivos
.xlsx reales, asi que NO se modifico para soportar CSV (habria sido tocar
un escritor compartido para un caso que no es el suyo). En su lugar, esta
funcion ahora lee/parcha/escribe el CSV directamente con pandas, y sigue
reutilizando ExcelWriter()._crear_backup() (generico, ya funciona para
cualquier extension) para la misma proteccion de backup previo que tenia
antes."""

import os

import pandas as pd

from src.core.excel_writer import ExcelWriter
from src.services import mail_sync_service


def actualizar_correo_por_cdb(cdb, df_comercial, df_contactos, ruta_correos):
    """Recalcula y persiste el 'CORREO ELECTRÓNICO' en Correos.csv para
    todos los VIN de Comercial que pertenecen a `cdb`, sin tocar ninguna
    otra columna ni fila. Devuelve (ok, mensaje, vins_actualizados)."""
    cdb_match = str(cdb).replace('.0', '').replace(' ', '').upper().strip()

    if df_comercial.empty or 'CDB FLOTA' not in df_comercial.columns:
        return False, "La tabla Comercial está vacía o no tiene columna CDB FLOTA.", []

    cdb_col_norm = df_comercial['CDB FLOTA'].astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\s+', '', regex=True).str.upper()
    df_comercial_cdb = df_comercial[cdb_col_norm == cdb_match]

    if df_comercial_cdb.empty:
        return False, f"No se encontró ningún camión en Comercial para el CDB flota {cdb}.", []

    df_resultado = mail_sync_service.cruzar_correos_maestro(df_comercial_cdb, pd.DataFrame(), df_contactos)

    correos_por_vin = {}
    for _, row in df_resultado.iterrows():
        vin = str(row.get('VIN', '')).strip()
        if not vin:
            continue
        correos_por_vin[vin] = row.get('CORREO ELECTRÓNICO', '')

    if not correos_por_vin:
        return False, "No se encontraron VIN válidos para actualizar en Correos.csv.", []

    if not os.path.exists(ruta_correos):
        return False, "No se pudo actualizar Correos.csv (¿archivo abierto o los VIN no existen todavía en Correos.csv?).", []

    writer_backup = ExcelWriter()
    writer_backup._crear_backup(ruta_correos)
    if not writer_backup.last_backup_ok:
        return False, "No se pudo crear la copia de seguridad de Correos.csv. No se modificó nada.", []

    try:
        df_correos = pd.read_csv(ruta_correos, dtype=str, keep_default_na=False)
    except Exception as e:
        return False, f"No se pudo leer Correos.csv: {e}", []

    if 'VIN' not in df_correos.columns:
        return False, "No se pudo actualizar Correos.csv (¿archivo abierto o los VIN no existen todavía en Correos.csv?).", []

    vin_col_norm = df_correos['VIN'].astype(str).str.strip()
    vins_actualizados = []
    for vin, correo in correos_por_vin.items():
        mask = vin_col_norm == vin
        if mask.any():
            df_correos.loc[mask, 'CORREO ELECTRÓNICO'] = correo
            vins_actualizados.append(vin)

    if not vins_actualizados:
        return False, "No se pudo actualizar Correos.csv (¿archivo abierto o los VIN no existen todavía en Correos.csv?).", []

    try:
        df_correos.to_csv(ruta_correos, index=False, encoding='utf-8-sig')
    except Exception as e:
        return False, f"No se pudo escribir Correos.csv: {e}", vins_actualizados

    return True, f"Correos.csv actualizado para {len(vins_actualizados)} camión(es).", vins_actualizados
