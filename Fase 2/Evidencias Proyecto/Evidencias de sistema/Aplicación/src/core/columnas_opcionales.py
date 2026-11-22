"""Columnas del Registro Maestro que se crean solas la primera vez que se necesitan.

Evita editar a mano el archivo compartido: la columna se agrega vacía al leer o al
guardar, y el respaldo previo al guardado ya cubre el cambio de esquema."""
from src.core.constants import COLUMNAS_OPCIONALES_RM


def asegurar_columnas_opcionales(df, solo_las_de=None):
    """Agrega vacías las columnas opcionales que falten. Con `solo_las_de` (un
    {id: {'cambios': {...}}} de guardado) agrega solo las que ese guardado escribe."""
    if df is None or 'VIN' not in df.columns:
        return df
    pedidas = None
    if solo_las_de is not None:
        pedidas = {col for datos in solo_las_de.values() for col in datos.get('cambios', {})}
    faltantes = [c for c in COLUMNAS_OPCIONALES_RM if c not in df.columns and (pedidas is None or c in pedidas)]
    if not faltantes:
        return df
    df = df.copy()
    for col in faltantes:
        df[col] = ''
    return df
