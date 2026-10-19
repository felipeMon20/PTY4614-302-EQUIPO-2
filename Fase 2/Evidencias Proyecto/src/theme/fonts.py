from PyQt6.QtGui import QFont

# Fuentes estandarizadas
FONT_FAMILY = "Segoe UI, Inter, Roboto, sans-serif"

def get_font(size=10, bold=False):
    font = QFont("Segoe UI", size)
    font.setBold(bold)
    return font

TITLE_FONT = get_font(20, bold=True)
SUBTITLE_FONT = get_font(14, bold=True)
BODY_FONT = get_font(10, bold=False)
SMALL_BOLD_FONT = get_font(11, bold=True)