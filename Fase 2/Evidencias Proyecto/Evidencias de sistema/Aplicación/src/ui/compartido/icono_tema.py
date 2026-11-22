"""Íconos de etiqueta que cambian de color con el tema: el de claro tal cual y, en oscuro, blanco."""
from PyQt6.QtCore import QObject

from src.theme import tema
from src.theme.theme_manager import ThemeManager

BLANCO_OSCURO = '#F1F5FB'


class _Repintor(QObject):
    """Hijo de la etiqueta: se destruye con ella y su conexión al tema se corta sola."""

    def __init__(self, etiqueta, nombre, color, tam, color_oscuro):
        super().__init__(etiqueta)
        self._e, self._datos = etiqueta, (nombre, color, tam, color_oscuro)
        tema.GestorTema.instancia().tema_cambiado.connect(self.pintar)
        self.pintar()

    def pintar(self, *_):
        nombre, color, tam, color_oscuro = self._datos
        elegido = color_oscuro if tema.es_oscuro() else color
        try:
            self._e.setPixmap(ThemeManager.icon_pixmap(nombre, color=elegido, size=tam))
        except RuntimeError:
            pass


def fijar_icono_tema(etiqueta, nombre, color, tam, color_oscuro=BLANCO_OSCURO):
    """Pone el ícono en `etiqueta` y lo vuelve a pintar al cambiar el tema (en oscuro, `color_oscuro`)."""
    for previo in etiqueta.findChildren(_Repintor):
        previo.setParent(None)
        previo.deleteLater()
    _Repintor(etiqueta, nombre, color, tam, color_oscuro)
