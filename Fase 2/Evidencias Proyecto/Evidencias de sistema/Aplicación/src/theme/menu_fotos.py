import os
import random

from PyQt6.QtCore import QSettings

# Fotos oficiales de Volvo Trucks, ya recortadas en vertical y con los colores apagados (src/assets/menu_fotos)
FOTOS = (
    ("puente", "FH16 bajo puente"),
    ("reflejo", "Cabina y reflejo"),
    ("bosque", "Bosque"),
    ("atardecer", "Atardecer y agua"),
    ("tormenta", "Frontal, tormenta"),
    ("polvo", "FH16, polvo"),
)
# Altura (0 arriba, 1 abajo) donde está el camión en cada foto, para centrar las miniaturas
FOCO_Y = {"puente": 0.58, "reflejo": 0.46, "bosque": 0.66, "atardecer": 0.48, "tormenta": 0.42, "polvo": 0.60}
ALEATORIO = "aleatorio"
_CLAVE = "menu_foto"


def _settings():
    return QSettings("VolvoApp", "Dashboard")


def get_modo():
    valor = _settings().value(_CLAVE, ALEATORIO, type=str)
    return valor if valor == ALEATORIO or valor in dict(FOTOS) else ALEATORIO


def set_modo(modo):
    if modo == ALEATORIO or modo in dict(FOTOS):
        _settings().setValue(_CLAVE, modo)


def foto_a_mostrar():
    """Id de la foto fija elegida, o una al azar si el modo es aleatorio."""
    modo = get_modo()
    return random.choice(FOTOS)[0] if modo == ALEATORIO else modo


def ruta_foto(carpeta_assets, foto_id):
    return os.path.join(carpeta_assets, "menu_fotos", f"{foto_id}.jpg")
