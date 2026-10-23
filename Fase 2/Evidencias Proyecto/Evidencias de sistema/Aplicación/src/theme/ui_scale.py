import os

from PyQt6.QtCore import QSettings

# Mediano (1.0) es el tamaño con el que se diseñó la interfaz.
NIVELES_ESCALA = {
    "pequeno": ("Pequeño", 0.85),
    "mediano": ("Mediano", 1.0),
    "grande": ("Grande", 1.25),
}
NIVEL_POR_DEFECTO = "mediano"
_CLAVE = "ui_scale"


def _settings():
    return QSettings("VolvoApp", "Dashboard")


def get_nivel_escala():
    nivel = _settings().value(_CLAVE, NIVEL_POR_DEFECTO, type=str)
    return nivel if nivel in NIVELES_ESCALA else NIVEL_POR_DEFECTO


def set_nivel_escala(nivel):
    if nivel in NIVELES_ESCALA:
        _settings().setValue(_CLAVE, nivel)


def aplicar_escala_al_entorno():
    # Debe llamarse antes de crear QApplication: Qt solo lee QT_SCALE_FACTOR al arrancar.
    # Se fija siempre (incluso 1.0) porque el proceso reiniciado hereda el entorno del anterior.
    os.environ["QT_SCALE_FACTOR"] = str(NIVELES_ESCALA[get_nivel_escala()][1])
