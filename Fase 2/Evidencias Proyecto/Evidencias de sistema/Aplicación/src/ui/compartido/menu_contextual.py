"""Menú de clic derecho común a todas las pantallas (tablas de General, Comercial, Operaciones, Ingresos, etc.)."""
from PyQt6.QtCore import Qt, QVariantAnimation, QEasingCurve
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from src.theme.theme_manager import ThemeManager

QSS_MENU_CONTEXTUAL = """
    QMenu { background-color: #FFFFFF; border: 1px solid #DCE3EE; border-radius: 12px; padding: 6px; }
    QMenu::item { color: #1B2B4E; font-size: 12px; font-weight: 600; padding: 8px 18px 8px 10px; margin: 1px 0px; border-radius: 8px; }
    QMenu::item:selected { background-color: #E8F0FE; color: #1F6FEB; }
    QMenu::item:disabled { color: #A3AEC0; background: transparent; }
    QMenu::icon { padding-left: 6px; }
    QMenu::separator { height: 1px; background: #E8EDF5; margin: 5px 8px; }
"""

COLOR_ICONO = '#64748B'


class MenuContextual(QMenu):
    """QMenu con el diseño común y una aparición suave (fundido de 110 ms, solo al abrirse)."""

    def __init__(self, padre=None):
        super().__init__(padre)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(QSS_MENU_CONTEXTUAL)
        self._fundido = QVariantAnimation(self)
        self._fundido.setStartValue(0.0)
        self._fundido.setEndValue(1.0)
        self._fundido.setDuration(110)
        self._fundido.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fundido.valueChanged.connect(lambda v: self.setWindowOpacity(float(v)))

    def showEvent(self, evento):
        self.setWindowOpacity(0.0)
        super().showEvent(evento)
        self._fundido.start()

    def accion(self, texto, icono='fa5s.copy', color=COLOR_ICONO, habilitada=True):
        """Agrega una opción con ícono y devuelve su QAction."""
        accion = QAction(ThemeManager.icon(icono, color=color), texto, self)
        accion.setEnabled(habilitada)
        self.addAction(accion)
        return accion


def crear_menu(padre=None):
    return MenuContextual(padre)


def texto_corto(valor, maximo=20):
    valor = str(valor)
    return valor if len(valor) < maximo else valor[:maximo - 3] + "..."
