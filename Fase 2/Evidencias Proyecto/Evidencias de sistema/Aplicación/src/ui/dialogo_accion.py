"""Tarjeta moderna de confirmación/éxito/error compartida por Comercial y
Operaciones (antes vivía solo en comercial.py como DialogoAccionCm)."""
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
                             QPushButton, QListWidget, QListWidgetItem, QAbstractItemView)

from src.theme.theme_manager import ThemeManager
from src.theme.colors import *

DURACION_ENTRADA_MS = 160


class DialogoAccion(QDialog):
    """QDialog con fondo gris y una tarjeta blanca adentro: icono en círculo,
    título, subtítulo de color, descripción, lista opcional de VIN y botones.
    Cada spec de botón: {'texto', 'clase': primary|danger|secondary,
    'rol': accept|reject}."""

    def __init__(self, parent, titulo_ventana, icon_name, icon_color, icon_bg_color,
                 titulo, subtitulo, descripcion, items=None, botones=None,
                 titulo_items="VIN seleccionados"):
        super().__init__(parent)
        self.setWindowTitle(titulo_ventana)
        self.setModal(True)
        # Más ancho cuando hay 3 o más botones, para que no se aprieten
        self.setFixedWidth(max(420, 150 * len(botones or []) + 100))
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {SURFACE}; border-radius: 14px; border: 1px solid {BORDER}; }}")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 20)
        card_layout.setSpacing(12)

        icon_frame = QFrame()
        icon_frame.setFixedSize(64, 64)
        icon_frame.setStyleSheet(f"background-color: {icon_bg_color}; border-radius: 32px; border: none;")
        icon_inner_layout = QVBoxLayout(icon_frame)
        icon_inner_layout.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap(icon_name, color=icon_color, size=30))
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_inner_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(icon_frame)

        titulo_lbl = QLabel(titulo)
        titulo_lbl.setWordWrap(True)
        titulo_lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: bold; background: transparent; border: none;")
        card_layout.addWidget(titulo_lbl)

        if subtitulo:
            subtitulo_lbl = QLabel(subtitulo)
            subtitulo_lbl.setWordWrap(True)
            subtitulo_lbl.setStyleSheet(f"color: {icon_color}; font-size: 13px; font-weight: bold; background: transparent; border: none;")
            card_layout.addWidget(subtitulo_lbl)

        if descripcion:
            desc_lbl = QLabel(descripcion)
            desc_lbl.setWordWrap(True)
            desc_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; background: transparent; border: none;")
            card_layout.addWidget(desc_lbl)

        self.lista_items = None
        if items:
            items_titulo = QLabel(f"{titulo_items} ({len(items)})")
            items_titulo.setStyleSheet("color: #374151; font-size: 11px; font-weight: bold; background: transparent; border: none; margin-top: 4px;")
            card_layout.addWidget(items_titulo)

            self.lista_items = QListWidget()
            self.lista_items.setStyleSheet(f"""
                QListWidget {{ background-color: {BACKGROUND}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
                QListWidget::item {{ padding: 4px 6px; color: {TEXT_PRIMARY}; font-size: 12px; }}
            """)
            # Altura máxima con scroll interno para selecciones grandes
            self.lista_items.setMaximumHeight(160)
            self.lista_items.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            for vin in items:
                self.lista_items.addItem(QListWidgetItem(vin))
            card_layout.addWidget(self.lista_items)

        botones_row = QHBoxLayout()
        botones_row.addStretch()
        for spec in botones or []:
            btn = QPushButton(spec['texto'])
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumWidth(110)
            clase = spec.get('clase', 'secondary')
            if clase == 'primary':
                ThemeManager.apply_primary_button(btn)
            elif clase == 'danger':
                ThemeManager.apply_danger_button(btn)
            else:
                ThemeManager.apply_secondary_button(btn)
            if spec.get('icono'):
                btn.setIcon(QIcon(ThemeManager.icon_pixmap(spec['icono'], color=TEXT_SECONDARY, size=14)))
            rol = spec.get('rol')
            if 'accion' in spec:
                btn.clicked.connect(spec['accion'])
                btn.setAutoDefault(False)
            elif rol == 'accept':
                btn.clicked.connect(self.accept)
                btn.setDefault(True)
            elif rol == 'reject':
                btn.clicked.connect(self.reject)
            if spec.get('default'):
                btn.setDefault(True)
            botones_row.addWidget(btn)
        card_layout.addLayout(botones_row)

        layout.addWidget(card)

        self._anim_entrada = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_entrada.setDuration(DURACION_ENTRADA_MS)
        self._anim_entrada.setStartValue(0.0)
        self._anim_entrada.setEndValue(1.0)
        self._anim_entrada.setEasingCurve(QEasingCurve.Type.OutCubic)

    def showEvent(self, event):
        super().showEvent(event)
        self._anim_entrada.start()

    @classmethod
    def exito_generico(cls, parent, titulo, subtitulo, descripcion):
        return cls(
            parent, f" {titulo}",
            icon_name="fa5s.check-circle", icon_color=SUCCESS, icon_bg_color="#D1FAE5",
            titulo=titulo, subtitulo=subtitulo, descripcion=descripcion,
            botones=[{'texto': 'Aceptar', 'clase': 'primary', 'rol': 'accept'}],
        )

    @classmethod
    def aviso(cls, parent, titulo, descripcion, items=None, titulo_items="VIN seleccionados"):
        return cls(
            parent, f" {titulo}",
            icon_name="fa5s.exclamation-triangle", icon_color=WARNING, icon_bg_color="#FEF3C7",
            titulo=titulo, subtitulo=None, descripcion=descripcion,
            items=items, titulo_items=titulo_items,
            botones=[{'texto': 'Entendido', 'clase': 'primary', 'rol': 'accept'}],
        )

    @classmethod
    def error(cls, parent, mensaje):
        """Muestra el mensaje real recibido, sin ocultar información útil."""
        return cls(
            parent, " No se pudo guardar",
            icon_name="fa5s.exclamation-triangle", icon_color=DANGER, icon_bg_color="#FEE2E2",
            titulo="No se pudo guardar",
            subtitulo=None,
            descripcion=mensaje,
            botones=[{'texto': 'Aceptar', 'clase': 'secondary', 'rol': 'accept'}],
        )
