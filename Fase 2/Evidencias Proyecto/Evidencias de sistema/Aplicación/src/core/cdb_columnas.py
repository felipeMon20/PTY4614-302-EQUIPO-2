"""Nombre de la columna de CDB comercial: en el archivo RM_JAVI.csv se llama
"CDB COMERCIAL", pero dentro de la app se sigue usando "CDB" (COL_CDB). La
conversión ocurre solo al leer y al escribir ese archivo."""

CDB_COMERCIAL_EN_DISCO = "CDB COMERCIAL"
CDB_EN_MEMORIA = "CDB"


def cdb_a_memoria(df):
    if df is not None and CDB_COMERCIAL_EN_DISCO in df.columns and CDB_EN_MEMORIA not in df.columns:
        return df.rename(columns={CDB_COMERCIAL_EN_DISCO: CDB_EN_MEMORIA})
    return df


def cdb_a_disco(df):
    if df is not None and CDB_EN_MEMORIA in df.columns and CDB_COMERCIAL_EN_DISCO not in df.columns:
        return df.rename(columns={CDB_EN_MEMORIA: CDB_COMERCIAL_EN_DISCO})
    return df


def asegurar_cdb_flota(df):
    """PruebasFM que aún no trae CDB FLOTA (antes de la primera sincronización): se agrega vacía."""
    if df is not None and 'VIN' in df.columns and CDB_EN_MEMORIA in df.columns and 'CDB FLOTA' not in df.columns:
        df = df.copy()
        df['CDB FLOTA'] = ''
    return df
