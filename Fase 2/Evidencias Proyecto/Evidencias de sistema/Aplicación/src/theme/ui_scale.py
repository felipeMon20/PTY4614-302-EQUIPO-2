import os

from PyQt6.QtCore import QSettings

# Mediano (0.85) es el tamaño por defecto: con 1.0 la caja izquierda de General no alcanzaba para sus controles.
NIVELES_ESCALA = {
    "pequeno": ("Pequeño", 0.75),
    "mediano": ("Mediano", 0.85),
}
NIVEL_POR_DEFECTO = "mediano"
# Clave nueva: lo guardado con la escala anterior (Pequeño 0.85 / Mediano 1.0) vuelve al Mediano de hoy
_CLAVE = "ui_scale_v2"


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
