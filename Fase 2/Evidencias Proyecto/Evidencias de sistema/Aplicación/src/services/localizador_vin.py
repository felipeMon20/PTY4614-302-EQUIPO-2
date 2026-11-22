"""Dónde está un VIN hoy: en qué bandeja de Comercial y en qué cola de Operaciones. Lo usa la barra de búsqueda
para llevar a la pantalla correcta. Python/pandas puro: no depende de PyQt6."""

import re

import pandas as pd

from src.services import comercial_services, operaciones_services
from src.services import cm_bajas_service

NOMBRES_COMERCIAL = {0: "Renovar contratos", 1: "Recuperar clientes", 2: "Nuevas oportunidades", 3: "Oportunidades CM"}
# Operaciones: Contactos (4) se arma por CDB, no por VIN, así que no entra
NOMBRES_OPERACIONES = {0: "Activaciones", 1: "Sin Flota", 2: "No entregados", 3: "Bajas", 5: "Conectados"}

_FILTROS_COMERCIAL = {
    0: comercial_services.filtrar_renovar_clientes,
    1: comercial_services.filtrar_gestionar_bajas,
    2: comercial_services.filtrar_por_gestionar,
}
_FILTROS_OPERACIONES = {
    0: operaciones_services.filtrar_activaciones,
    1: operaciones_services.filtrar_sin_flota,
    2: operaciones_services.filtrar_no_entregados,
    3: operaciones_services.filtrar_bajas,
    5: operaciones_services.filtrar_conectados_vigentes,
}


def extraer_vins(texto):
    """Términos del texto que parecen un VIN (8 a 17 letras y dígitos, con al menos una letra y un dígito), en
    mayúsculas y en orden. Una palabra sola ("maquinaria") o un RUT sin puntos no cuenta: se busca como texto."""
    vistos = []
    for t in re.split(r'[,\s;]+', str(texto or '').strip()):
        if re.fullmatch(r'(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]{8,17}', t) and t.upper() not in vistos:
            vistos.append(t.upper())
    return vistos


def _vins_coincidentes(serie_vin, termino):
    """VIN completos de `serie_vin` que cumplen el término: igual si trae 17 caracteres, que lo contenga si trae menos."""
    vins = serie_vin.astype(str).str.strip().str.upper()
    mascara = vins == termino if len(termino) == 17 else vins.str.contains(termino, regex=False)
    return set(vins[mascara])


def _tiene(df, vins):
    if df is None or df.empty or 'VIN' not in df.columns:
        return False
    return bool(df['VIN'].astype(str).str.strip().str.upper().isin(vins).any())


class IndiceVins:
    """VIN de uno o más DataFrames normalizados una sola vez: con cientos de términos, buscar cada uno con
    vins_de_termino volvía a limpiar la columna completa por término (1000 VIN: ~6 s en Comercial)."""

    def __init__(self, *dfs):
        valores = set()
        for df in dfs:
            if df is not None and not df.empty and 'VIN' in df.columns:
                valores.update(df['VIN'].astype(str).str.strip().str.upper())
        self._vins = valores
        self._serie = None

    def buscar(self, termino):
        """Igual que vins_de_termino: el VIN exacto si trae 17 caracteres, los que lo contienen si trae menos."""
        if len(termino) == 17:
            return {termino} if termino in self._vins else set()
        if self._serie is None:
            self._serie = pd.Series(sorted(self._vins), dtype=object)
        return set(self._serie[self._serie.str.contains(termino, regex=False)])


def vins_de_termino(termino, *dfs):
    """VIN completos que corresponden al término en cualquiera de los `dfs`."""
    encontrados = set()
    for df in dfs:
        if df is not None and not df.empty and 'VIN' in df.columns:
            encontrados |= _vins_coincidentes(df['VIN'], termino)
    return encontrados


def pestanas_comercial(vins, df_base, df_casos_cm):
    """Índices de las bandejas de Comercial donde está alguno de `vins`, en el orden de las pestañas."""
    ubicadas = []
    for idx, filtro in _FILTROS_COMERCIAL.items():
        try:
            if _tiene(filtro(df_base), vins):
                ubicadas.append(idx)
        except Exception:
            continue
    if df_casos_cm is not None and not df_casos_cm.empty and 'ESTADO_CASO' in df_casos_cm.columns:
        estado = df_casos_cm['ESTADO_CASO'].astype(str).str.strip().str.upper()
        pendientes = df_casos_cm[estado == cm_bajas_service.ESTADO_CASO_PENDIENTE.upper()]
        if _tiene(pendientes, vins):
            ubicadas.append(3)
    return sorted(ubicadas)


def pestanas_operaciones(vins, df_actuales):
    """Índices de las colas de Operaciones donde está alguno de `vins`, en el orden de las pestañas."""
    ubicadas = []
    for idx, filtro in _FILTROS_OPERACIONES.items():
        try:
            if _tiene(filtro(df_actuales), vins):
                ubicadas.append(idx)
        except Exception:
            continue
    return sorted(ubicadas)


def descripcion(modulo, indice):
    """Texto del destino, por ejemplo "Operaciones → Sin Flota"."""
    nombres = NOMBRES_COMERCIAL if modulo == "Comercial" else NOMBRES_OPERACIONES
    return f"{modulo} → {nombres.get(indice, '')}"
