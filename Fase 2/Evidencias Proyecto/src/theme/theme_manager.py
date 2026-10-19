import qtawesome as qta
from PyQt6.QtCore import QSize

from src.theme.fonts import TITLE_FONT, SMALL_BOLD_FONT

class ThemeManager:
    # Cache compartida de iconos QtAwesome (auditoria de rendimiento, fase 2,
    # 21-09-2026): qta.icon(name, color=...) renderiza el glifo de la fuente
    # de iconos a un QIcon nuevo en cada llamada, y .pixmap(QSize(...)) vuelve
    # a rasterizarlo. Los modulos con tarjetas (General/Comercial/
    # Provisiones) llaman qta.icon() con los mismos pares (nombre, color)
    # cientos de veces por refresh/pagina. Se cachea por (nombre, color) el
    # QIcon y por (nombre, color, tamano) el QPixmap ya renderizado, y se
    # reutiliza la misma instancia en vez de volver a renderizar -- mismo
    # icono, mismo color, mismo tamano, solo se evita recalcularlo.
    #
    # NO usar para iconos animados (qta.icon(..., animation=qta.Spin(widget))):
    # esos van ligados a un widget concreto y no deben compartirse ni
    # cachearse; siguen llamando a qta.icon(...) directo en el sitio de uso.
    _icon_cache = {}
    _pixmap_cache = {}

    @classmethod
    def icon(cls, name, color=None):
        """QIcon de QtAwesome cacheado por (nombre, color). Reemplazo directo
        de qta.icon(name, color=color) para setIcon()/QAction(); no usar con
        iconos animados (ver nota de la clase)."""
        clave = (name, color)
        icono = cls._icon_cache.get(clave)
        if icono is None:
            icono = qta.icon(name, color=color)
            cls._icon_cache[clave] = icono
        return icono

    @classmethod
    def icon_pixmap(cls, name, color=None, size=16):
        """QPixmap ya renderizado de un icono de QtAwesome (cuadrado, lado
        'size'), cacheado por (nombre, color, tamano). Reemplazo directo de
        qta.icon(name, color=color).pixmap(QSize(size, size))."""
        clave = (name, color, size)
        pixmap = cls._pixmap_cache.get(clave)
        if pixmap is None:
            pixmap = cls.icon(name, color).pixmap(QSize(size, size))
            cls._pixmap_cache[clave] = pixmap
        return pixmap

    @staticmethod
    def apply_card_style(widget):
        widget.setProperty("class", "card")
        widget.style().polish(widget)

    @staticmethod
    def apply_primary_button(btn):
        btn.setProperty("class", "primary")
        btn.style().polish(btn)

    @staticmethod
    def apply_success_button(btn):
        btn.setProperty("class", "success")
        btn.style().polish(btn)

    @staticmethod
    def apply_danger_button(btn):
        btn.setProperty("class", "danger")
        btn.style().polish(btn)

    @staticmethod
    def apply_secondary_button(btn):
        btn.setProperty("class", "secondary")
        btn.style().polish(btn)

    @staticmethod
    def apply_search_bar(line_edit):
        line_edit.setProperty("class", "search_bar")
        line_edit.style().polish(line_edit)

    @staticmethod
    def apply_combo_box(combo):
        combo.setProperty("class", "combo_box")
        combo.style().polish(combo)

    @staticmethod
    def style_title(label):
        label.setFont(TITLE_FONT)
        label.setProperty("class", "title")
        label.style().polish(label)
        
    @staticmethod
    def style_subtitle(label):
        label.setFont(SMALL_BOLD_FONT)
        label.setProperty("class", "subtitle")
        label.style().polish(label)