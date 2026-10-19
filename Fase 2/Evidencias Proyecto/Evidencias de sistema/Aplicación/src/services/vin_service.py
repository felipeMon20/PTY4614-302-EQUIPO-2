"""Deduccion del MODELO de un camion a partir de su VIN. Logica pura de
Python (sin PyQt6 ni dependencias de UI): unicamente interpreta la posicion 4
(familia/modelo base) y, para el caso de propulsion electrica, las posiciones
5-7 (codigo 'B40'). No deduce ningun otro atributo del vehiculo (ejes,
cabina, motor, potencia, año, pais, carroceria, version, transmision,
equipamiento, etc.).

Los valores devueltos deben ser exactamente alguno de los oficiales del
combo MODELO de ComercialAgregarDialog (DROPDOWN_OPTIONS_NUEVO_CLIENTE en
src/ui/general.py, replicada tambien en ComercialModule.dropdown_options en
src/ui/comercial.py: "FH", "FHE", "FHL", "FM", "FME", "FML", "FMX", "FL",
"FE", "VM", "N/A"), que no se modifica desde aqui. 'A' y 'J' representan
generaciones anteriores de FH/FM respectivamente, pero el valor de MODELO no
distingue generacion: ambos colapsan al mismo valor oficial ("FH"/"FM")."""

# Posicion 4 del VIN (indice 3 en Python) -> modelo base, usando unicamente
# valores oficiales del combo MODELO. 'A' (FH generacion anterior) y 'J' (FM
# generacion anterior) colapsan a los mismos valores que 'R'/'X' porque
# MODELO no distingue generacion.
_MODELO_POR_POSICION_4 = {
    'A': 'FH',
    'J': 'FM',
    'R': 'FH',
    'X': 'FM',
    'K': 'VM',
    'P': 'VM',
    'T': 'FL',
    'V': 'FE',
}

# Posicion 4 + posiciones 5-7 == 'B40' (propulsion electrica Empresa Demo/BEV) -> modelo electrico.
_MODELO_ELECTRICO_POR_POSICION_4 = {
    'R': 'FHE',
    'X': 'FME',
}

_CODIGO_PROPULSION_ELECTRICA = 'B40'


def obtener_modelo_desde_vin(vin):
    """Deduce unicamente el MODELO del camion a partir del VIN, segun la
    posicion 4 (familia/modelo base) y, si las posiciones 5-7 son 'B40'
    (propulsion electrica Empresa Demo/BEV), la variante electrica correspondiente.
    Normaliza `vin` a mayusculas/sin espacios antes de leer las posiciones.
    Devuelve uno de los valores oficiales del combo MODELO, o None si el VIN
    es demasiado corto o la posicion 4 no coincide con ninguna regla
    confirmada (nunca inventa un modelo)."""
    vin_norm = str(vin).strip().upper()
    if len(vin_norm) < 4:
        return None

    posicion_4 = vin_norm[3]
    if posicion_4 not in _MODELO_POR_POSICION_4:
        return None

    if len(vin_norm) >= 7 and vin_norm[4:7] == _CODIGO_PROPULSION_ELECTRICA:
        modelo_electrico = _MODELO_ELECTRICO_POR_POSICION_4.get(posicion_4)
        if modelo_electrico:
            return modelo_electrico

    return _MODELO_POR_POSICION_4[posicion_4]
