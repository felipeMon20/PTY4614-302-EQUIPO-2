"""Logica de negocio del cruce/ETL que genera Correos.csv (antes
Correos.xlsx, migrado en B-5.2 -- 18-09-2026: solo se usaba como
almacenamiento tabular plano, sin formulas ni multiples hojas) a partir de
Comercial (PruebasFM), Power BI (BBDD CLIENTES CM) y Contactos, mas la
persistencia del resultado en disco. Python/pandas puro: no depende de
PyQt6, QThread, QObject, QMessageBox ni ningun widget."""

import os
import pandas as pd

from src.core.excel_writer import ExcelWriter


def cruzar_correos_maestro(df_comercial, df_pbi=None, df_contactos=None):
    """Cruza Comercial (base maestra, ya en RAM) con Contactos (unica fuente
    de correos electronicos) por CDB FLOTA. `df_pbi` se conserva solo por
    compatibilidad de firma: BBDD CLIENTES CM ya no participa del cruce.

    Reglas:
      - Clave de cruce: CDB FLOTA normalizado de cada camion contra la
        columna CDB de Contactos. El CDB comercial no se usa.
      - Contactos: NO se deduplica; se concatenan todos los correos unicos
        de un mismo CDB con "; " (un CDB puede tener varios contactos).
      - Razon Social/RUT: solo los de Comercial.
      - Toda fila de Comercial se incluye en el resultado, tenga o no match.
    """
    from src.services.comercial_services import contratos_actuales
    # Correos.csv tiene una fila por VIN: se cruza el contrato actual de cada uno
    df_comercial = contratos_actuales(df_comercial)
    if df_contactos is None:
        df_contactos = pd.DataFrame()
    if not df_contactos.empty and 'CDB' in df_contactos.columns:
        df_contactos = df_contactos.copy()
        df_contactos['CDB_MATCH'] = df_contactos['CDB'].astype(str).str.replace(r'\.0$', '', regex=True).str.replace(r'\s+', '', regex=True).str.upper()

    registros = []

    for _, row in df_comercial.iterrows():
        cdb_raw = str(row.get('CDB FLOTA', '')).replace('.0', '').replace(' ', '').upper()
        vin = str(row.get('VIN', '')).strip()
        chasis = str(row.get('CHASIS', '')).strip()
        plan = str(row.get('TIPO DE SERVICIO', '')).strip()
        # TERMINO es el fin de facturación; el de contrato es TÉRMINO CONTRATO
        termino = str(row.get('TÉRMINO CONTRATO', row.get('TERMINO', ''))).strip()

        rs_raw = str(row.get('RÁZON SOCIAL', row.get('RAZÓN SOCIAL', row.get('RAZON SOCIAL', '')))).strip()
        razon_social = "" if rs_raw.lower() in ['nan', 'none', '<na>', '0', '0.0', ''] else rs_raw

        rut_raw = str(row.get('RUT', '')).strip()
        rut = "" if rut_raw.lower() in ['nan', 'none', '<na>', ''] else rut_raw

        correo_contacto = ""

        if cdb_raw not in ('', '-', 'NAN') and not df_contactos.empty and cdb_raw in df_contactos['CDB_MATCH'].values:
            ct_match = df_contactos[df_contactos['CDB_MATCH'] == cdb_raw]
            correos_unicos = []

            for _, c_match in ct_match.iterrows():
                co = str(c_match.get('Correo electrónico', c_match.get('Correo', ''))).strip()
                if co and co.lower() not in ['nan', 'none', '']:
                    if co not in correos_unicos:
                        correos_unicos.append(co)

            correo_contacto = "; ".join(correos_unicos)

        registros.append({
            "VIN": vin,
            "CHASIS": chasis,
            "RAZÓN SOCIAL": razon_social,
            "RUT": rut,
            "TIPO DE SERVICIO": plan,
            "FECHA TERMINO": termino,
            "CORREO ELECTRÓNICO": correo_contacto,
        })

    return pd.DataFrame(registros)


def vins_faltantes_en_correos(vins, ruta):
    """VIN de `vins` que no aparecen en la columna VIN de Correos.csv, en
    el mismo orden de entrada. Un VIN "falta" cuando Correos.csv quedo
    desactualizado respecto a Comercial (cruzar_correos_maestro siempre
    incluye toda fila de Comercial, tenga o no correo) -- no confundir con
    "VIN presente pero sin correo asignado", que MailDialog ya resuelve por
    su cuenta (celda roja + mail_service.validar_destinatarios).

    B-5.2 (migracion XLSX -> CSV, 18-09-2026): dtype=str + keep_default_na=False
    (mismo patron que LogApp.csv/CasosBajaCM.csv en el resto del proyecto),
    para que VIN/CDB/RUT no pierdan ceros iniciales ni se conviertan
    valores como '' en NaN."""
    if not vins:
        return []
    if not ruta or not os.path.exists(ruta):
        return list(vins)
    try:
        df_correos = pd.read_csv(ruta, dtype=str, keep_default_na=False)
    except Exception:
        return list(vins)
    if 'VIN' not in df_correos.columns:
        return list(vins)

    vins_existentes = set(df_correos['VIN'].astype(str).str.strip().str.upper())
    return [v for v in vins if str(v).strip().upper() not in vins_existentes]


def guardar_correos_excel(df, ruta):
    """Crea backup con ExcelWriter._crear_backup() (mecanismo existente, sin
    modificarlo salvo la correccion de extension del propio backup -- ver
    excel_writer.py) y, solo si el backup fue exitoso, escribe `df` en
    `ruta`. Nunca lanza excepcion: devuelve (ok, mensaje) para que la UI
    decida que QMessageBox mostrar.

    B-5.2 (migracion XLSX -> CSV, 18-09-2026): `ruta` ahora apunta a
    Correos.csv, no a Correos.xlsx -- se escribe con to_csv() en vez de
    to_excel(). encoding='utf-8-sig' (mismo criterio que _log_changes en
    excel_writer.py) para que Excel/SharePoint muestren bien los acentos de
    columnas como 'RAZÓN SOCIAL'/'CORREO ELECTRÓNICO' si alguien abre el
    CSV directamente. El nombre de esta funcion se conserva tal cual
    (guardar_correos_excel) para no ampliar el alcance de la migracion
    renombrando algo que no es estrictamente necesario para que funcione."""
    try:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        writer_backup = ExcelWriter()
        writer_backup._crear_backup(ruta)
        if not writer_backup.last_backup_ok:
            return False, "No se pudo crear la copia de seguridad de Correos.csv. La operación fue cancelada y no se realizó ningún cambio."

        df.to_csv(ruta, index=False, encoding='utf-8-sig')
        return True, f"¡El archivo 'Correos.csv' ha sido guardado exitosamente en SharePoint!\nRuta: {ruta}"
    except PermissionError:
        return False, "El archivo Correos.csv está abierto por alguien más en SharePoint. Ciérralo y vuelve a intentar."
    except Exception as e:
        return False, str(e)
