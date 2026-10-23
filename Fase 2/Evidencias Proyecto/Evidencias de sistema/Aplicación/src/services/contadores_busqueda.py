"""Cifras del buscador global del header: cuántos términos hay y cuántos aparecen en los datos."""
import re

COLUMNAS_COINCIDENCIA = ("VIN", "CHASIS", "RUT")
_PARECE_VIN = re.compile(r'^[a-z0-9]{8,}$')


def terminos(texto):
    """Términos separados por coma, como los interpretan las pantallas al filtrar."""
    return [t.strip().lower() for t in str(texto).split(',') if t.strip()]


def son_vins(lista):
    return bool(lista) and all(_PARECE_VIN.match(t) for t in lista)


def etiqueta(lista):
    uno = len(lista) == 1
    if son_vins(lista):
        return "VIN" if uno else "VINs"
    return "término" if uno else "términos"


class IndiceCoincidencias:
    """Texto en minúsculas de VIN, chasis y RUT del Registro Maestro; se arma una vez por carga de datos."""

    def __init__(self):
        self._df = None
        self._texto = ""

    def contar(self, df, lista):
        if df is not self._df:
            valores = set()
            for col in COLUMNAS_COINCIDENCIA:
                if col in df.columns:
                    valores.update(df[col].astype(str).str.lower().unique())
            self._texto = "\n".join(valores)
            self._df = df
        return sum(1 for t in lista if t in self._texto)
