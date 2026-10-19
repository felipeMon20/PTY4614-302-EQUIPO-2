"""Normalización de valores justo antes de escribirlos en PruebasFM, para que
distintas fuentes (formulario, importación de Power BI, sincronización de
Provisiones) no dejen el mismo dato con grafías distintas."""
import re

_PATRON_PERIODO = re.compile(r'^\s*([A-Za-zÁÉÍÓÚÑáéíóúñ]+)\s*-\s*(\d{4})\s*$')


def normalizar_periodo_interno(valor):
    """"Septiembre - 2026" / "SEPTIEMBRE - 2026" -> "septiembre - 2026", que es
    como PruebasFM guarda el periodo. Cualquier otro valor (ej. "NO APLICA",
    "-") se devuelve igual."""
    if not isinstance(valor, str):
        return valor
    coincide = _PATRON_PERIODO.match(valor)
    if not coincide:
        return valor
    return f"{coincide.group(1).lower()} - {coincide.group(2)}"


def normalizar_para_escritura(columna, valor):
    if columna == 'PERIODO INTERNO':
        return normalizar_periodo_interno(valor)
    return valor
