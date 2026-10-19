"""Modo claro/oscuro de toda la app (30-09-2026).

Los colores de la UI están escritos a mano en cientos de setStyleSheet, así
que el modo oscuro no reescribe cada llamada: QWidget.setStyleSheet queda
envuelto y, con el tema oscuro activo, cada hoja se convierte al vuelo
(convertir_qss). Al volver a claro se restaura la hoja original guardada en
la propiedad _PROP_ORIGINAL. Los widgets dibujados a mano (paintEvent) leen
sus colores con color() y escuchan GestorTema.tema_cambiado.
"""
import colorsys
import re

from PyQt6.QtCore import QEvent, QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QToolTip, QWidget

CLARO = "claro"
OSCURO = "oscuro"
CLAVE_AJUSTE = "tema_oscuro"

PALETAS = {
    CLARO: {
        'fondo': '#F8FAFC', 'superficie': '#FFFFFF', 'superficie_2': '#F1F5F9', 'borde': '#E5E7EB',
        'texto': '#1E293B', 'texto_2': '#475569', 'texto_tenue': '#94A3B8', 'primario': '#2563EB',
    },
    OSCURO: {
        'fondo': '#0B1220', 'superficie': '#131C2E', 'superficie_2': '#1A2540', 'borde': '#26324A',
        'texto': '#E5ECF6', 'texto_2': '#A3B1C6', 'texto_tenue': '#6B7A90', 'primario': '#4F8BF7',
    },
}

# Equivalencias explícitas de los neutros más usados; el resto se calcula.
_MAPA_FONDO = {
    'FFFFFF': '131C2E', 'F8FAFC': '0B1220', 'F9FAFB': '111A2B', 'F7F9FB': '111A2B', 'F8F9FA': '111A2B',
    'FFFCF5': '161E2F', 'F1F5F9': '1A2540', 'F3F4F6': '1A2540', 'EEF2F6': '1D2944', 'EEF1F6': '1D2944',
    'E8ECF1': '212D47', 'E2E8F0': '26324A', 'E5E7EB': '26324A', 'D5DFF0': '2E3B57', 'D5DDEA': '2E3B57',
    'D1D5DB': '33415E', 'CBD5E1': '33415E', '94A3B8': '4A5A76', '9CA3AF': '4A5A76',
}
_MAPA_TEXTO = {
    '1E293B': 'E5ECF6', '1F2937': 'E5ECF6', '1E2937': 'E5ECF6', '0F172A': 'F1F5FB', '111827': 'F1F5FB',
    '0F1B33': 'E5ECF6',
    '000000': 'E5ECF6', '334155': 'C9D3E3', '374151': 'C9D3E3', '475569': 'A3B1C6', '4B5563': 'A3B1C6',
    '52607A': 'A3B1C6', '64748B': '8794AA', '66748D': '8794AA', '6B7280': '8794AA', '003057': '9CC2FF',
    '002240': '9CC2FF', '1C6BBA': '6EA0FF', '2563EB': '6EA0FF', '1E40AF': '93C5FD', '991B1B': 'FCA5A5',
    'B91C1C': 'FCA5A5', '92400E': 'FCD34D', '065F46': '6EE7B7', '166534': '86EFAC', '5B21B6': 'C4B5FD',
    '0F766E': '5EEAD4', '115E59': '5EEAD4', '9D174D': 'F9A8D4', 'C2410C': 'FDBA74',
}

_PROPIEDADES_TEXTO = ('color', 'selection-color')
_RE_DECLARACION = re.compile(r'([A-Za-z-]+)(\s*:\s*)([^;{}]+)')
_RE_COLOR = re.compile(
    r'#(?P<hex>[0-9A-Fa-f]{8}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b'
    r'|(?P<fn>rgba?)\(\s*(?P<r>\d+)\s*,\s*(?P<g>\d+)\s*,\s*(?P<b>\d+)\s*(?P<resto>(?:,[^)]*)?)\)'
    r'|\b(?P<nombre>white|black)\b',
    re.IGNORECASE,
)


def _a_hex(r, g, b):
    return f"{round(r):02X}{round(g):02X}{round(b):02X}"


def _desde_hls(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return _a_hex(r * 255, g * 255, b * 255)


def _fondo_oscuro(hex6):
    if hex6 in _MAPA_FONDO:
        return _MAPA_FONDO[hex6]
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if l >= 0.80:
        if s < 0.15:
            if l >= 0.97:
                return '131C2E'
            if l >= 0.93:
                return '1A2540'
            return '26324A' if l >= 0.88 else '33415E'
        # Fondos pastel (chips, avisos): mismo tono, oscuro y algo apagado
        return _desde_hls(h, 0.18 + max(0.0, 0.95 - l) * 0.5, min(s, 0.55))
    if l >= 0.6 and s < 0.15:
        return '3A4A66'
    return hex6


def _texto_oscuro(hex6):
    if hex6 in _MAPA_TEXTO:
        return _MAPA_TEXTO[hex6]
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    if s < 0.15:
        return _desde_hls(h, 0.93 - l * 0.45, s) if l <= 0.6 else hex6
    if l < 0.5:
        return _desde_hls(h, 0.72, min(s, 0.85))
    if l < 0.6:
        return _desde_hls(h, 0.66, s)
    return hex6


def _convertir_valor(valor, es_texto):
    convertir = _texto_oscuro if es_texto else _fondo_oscuro

    def _reemplazo(m):
        if m.group('hex'):
            crudo = m.group('hex').upper()
            if len(crudo) == 3:
                return '#' + convertir(''.join(c * 2 for c in crudo))
            if len(crudo) == 8:
                return '#' + crudo[:2] + convertir(crudo[2:])
            return '#' + convertir(crudo)
        if m.group('fn'):
            nuevo = convertir(_a_hex(*(min(255, int(m.group(k))) for k in ('r', 'g', 'b'))))
            r, g, b = (int(nuevo[i:i + 2], 16) for i in (0, 2, 4))
            return f"{m.group('fn')}({r}, {g}, {b}{m.group('resto')})"
        nombre = m.group('nombre').lower()
        if es_texto:
            return '#' + _MAPA_TEXTO['000000'] if nombre == 'black' else m.group(0)
        return '#' + _MAPA_FONDO['FFFFFF'] if nombre == 'white' else m.group(0)

    return _RE_COLOR.sub(_reemplazo, valor)


_cache_conversion = {}
_cache_inverso = {}


def convertir_qss(qss):
    """Hoja de estilo clara -> oscura. Los colores de texto (color,
    selection-color) se aclaran; fondos y bordes se oscurecen. Los colores
    saturados (botones, acentos) se conservan."""
    if not qss:
        return qss
    convertido = _cache_conversion.get(qss)
    if convertido is None:
        def _decl(m):
            prop = m.group(1).lower()
            return m.group(1) + m.group(2) + _convertir_valor(m.group(3), prop in _PROPIEDADES_TEXTO)
        convertido = _RE_DECLARACION.sub(_decl, qss)
        _cache_conversion[qss] = convertido
        _cache_inverso[convertido] = qss
    return convertido


_cache_colores = {}


def _color_tema(valor, es_texto):
    if not es_oscuro():
        return QColor(valor)
    clave = (valor.rgba() if isinstance(valor, QColor) else str(valor), es_texto)
    color_cacheado = _cache_colores.get(clave)
    if color_cacheado is None:
        base = QColor(valor)
        convertir = _texto_oscuro if es_texto else _fondo_oscuro
        color_cacheado = QColor('#' + convertir(base.name()[1:].upper()))
        color_cacheado.setAlpha(base.alpha())
        _cache_colores[clave] = color_cacheado
    return QColor(color_cacheado)


def version_oscura(valor, es_texto=False):
    """Equivalente oscuro de un color, sin importar el tema activo (para
    precalcular y cachear ambas versiones)."""
    base = QColor(valor)
    convertir = _texto_oscuro if es_texto else _fondo_oscuro
    resultado = QColor('#' + convertir(base.name()[1:].upper()))
    resultado.setAlpha(base.alpha())
    return resultado


def fondo(valor):
    """Color de fondo/borde (hex o QColor) para widgets pintados a mano:
    tal cual en claro, oscurecido en oscuro."""
    return _color_tema(valor, False)


def texto(valor):
    """Color de texto para widgets pintados a mano: aclarado en oscuro."""
    return _color_tema(valor, True)


# ----------------------------------------------------------------------
# Envoltura de QWidget.setStyleSheet
# ----------------------------------------------------------------------
_PROP_ORIGINAL = "_qss_tema_claro"
_set_style_sheet_original = QWidget.setStyleSheet
_estado = {'oscuro': False, 'hubo_oscuro': False}


def es_oscuro():
    return _estado['oscuro']


def color(token):
    return QColor(PALETAS[OSCURO if es_oscuro() else CLARO][token])


def _original_de(widget, qss):
    """Si el código armó la hoja a partir de la ya convertida
    (w.setStyleSheet(w.styleSheet() + ...)), recupera la versión clara."""
    if qss in _cache_inverso:
        return _cache_inverso[qss]
    previo = widget.property(_PROP_ORIGINAL)
    if previo:
        actual = widget.styleSheet()
        if actual and qss.startswith(actual):
            return previo + qss[len(actual):]
    return qss


def _set_style_sheet_tematizado(widget, qss):
    if not _estado['hubo_oscuro']:
        _set_style_sheet_original(widget, qss)
        return
    qss = _original_de(widget, qss or "")
    if _estado['oscuro'] and qss:
        widget.setProperty(_PROP_ORIGINAL, qss)
        _set_style_sheet_original(widget, convertir_qss(qss))
    else:
        if widget.property(_PROP_ORIGINAL) is not None:
            widget.setProperty(_PROP_ORIGINAL, None)
        _set_style_sheet_original(widget, qss)


def _instalar_envoltura():
    if QWidget.setStyleSheet is not _set_style_sheet_tematizado:
        QWidget.setStyleSheet = _set_style_sheet_tematizado


def _paleta(oscuro):
    p = QPalette()
    if not oscuro:
        # Misma paleta clara que fijaba main.py antes del modo oscuro
        for rol, rgb in (
            (QPalette.ColorRole.Window, (240, 240, 240)), (QPalette.ColorRole.WindowText, (0, 0, 0)),
            (QPalette.ColorRole.Base, (255, 255, 255)), (QPalette.ColorRole.AlternateBase, (245, 245, 245)),
            (QPalette.ColorRole.ToolTipBase, (255, 255, 255)), (QPalette.ColorRole.ToolTipText, (0, 0, 0)),
            (QPalette.ColorRole.Text, (0, 0, 0)), (QPalette.ColorRole.Button, (240, 240, 240)),
            (QPalette.ColorRole.ButtonText, (0, 0, 0)),
        ):
            p.setColor(rol, QColor(*rgb))
        return p
    for rol, hexa in (
        (QPalette.ColorRole.Window, '#0B1220'), (QPalette.ColorRole.WindowText, '#E5ECF6'),
        (QPalette.ColorRole.Base, '#131C2E'), (QPalette.ColorRole.AlternateBase, '#162036'),
        (QPalette.ColorRole.ToolTipBase, '#1A2540'), (QPalette.ColorRole.ToolTipText, '#E5ECF6'),
        (QPalette.ColorRole.Text, '#E5ECF6'), (QPalette.ColorRole.Button, '#1A2540'),
        (QPalette.ColorRole.ButtonText, '#E5ECF6'), (QPalette.ColorRole.BrightText, '#FFFFFF'),
        (QPalette.ColorRole.Highlight, '#2563EB'), (QPalette.ColorRole.HighlightedText, '#FFFFFF'),
        (QPalette.ColorRole.PlaceholderText, '#6B7A90'), (QPalette.ColorRole.Link, '#6EA0FF'),
        (QPalette.ColorRole.Light, '#2A3756'), (QPalette.ColorRole.Midlight, '#222E48'),
        (QPalette.ColorRole.Mid, '#1A2540'), (QPalette.ColorRole.Dark, '#080E1A'),
        (QPalette.ColorRole.Shadow, '#000000'),
    ):
        p.setColor(rol, QColor(hexa))
    for rol in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, rol, QColor('#5B6B84'))
    return p


class _FiltroGlobos(QObject):
    """Muestra los tooltips sin colgarlos del widget: si el widget tiene una
    hoja con reglas de QLabel/transparencia, el globo la heredaba y salía
    como un cuadro negro."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.ToolTip and isinstance(obj, QWidget):
            texto = obj.toolTip()
            if texto:
                QToolTip.showText(event.globalPos(), texto, None)
                return True
        return False


class GestorTema(QObject):
    """Único punto que cambia el tema. Emite tema_cambiado(modo) después de
    aplicar paleta y hojas de estilo."""
    tema_cambiado = pyqtSignal(str)
    _instancia = None

    @classmethod
    def instancia(cls):
        if cls._instancia is None:
            cls._instancia = cls()
        return cls._instancia

    def __init__(self):
        super().__init__()
        self._qss_app_claro = None
        # Tema con el que quedó la hoja global de la aplicación. Cambiarla
        # con la app abierta repolea todos los widgets (~1,4 s con dos
        # módulos cargados), así que solo se fija al arrancar; al alternar,
        # la hoja global del tema nuevo va sobre las ventanas principales
        # (~0,3 s) y los diálogos/menús hijos la heredan.
        self._oscuro_en_app = False
        self._ventanas = []

    @property
    def modo(self):
        return OSCURO if es_oscuro() else CLARO

    def inicializar(self, app):
        """Se llama una vez al arrancar, después de cargar styles.qss."""
        _instalar_envoltura()
        self._filtro_globos = _FiltroGlobos(app)
        app.installEventFilter(self._filtro_globos)
        self._qss_app_claro = app.styleSheet()
        oscuro = QSettings("GestorApp", "Dashboard").value(CLAVE_AJUSTE, False, type=bool)
        self._oscuro_en_app = oscuro
        if oscuro:
            app.setStyleSheet(convertir_qss(self._qss_app_claro))
        self.aplicar(OSCURO if oscuro else CLARO, guardar=False, forzar=True)

    def registrar_ventana(self, ventana):
        """Ventana principal (sin padre) que debe recibir la hoja global al
        alternar el tema. No debe tener una hoja propia."""
        if ventana not in self._ventanas:
            self._ventanas.append(ventana)
            ventana.destroyed.connect(lambda *_: self._ventanas.remove(ventana) if ventana in self._ventanas else None)
            self._aplicar_hoja_global(ventana)

    def alternar(self):
        self.aplicar(CLARO if es_oscuro() else OSCURO)

    def aplicar(self, modo, guardar=True, forzar=False):
        oscuro = modo == OSCURO
        if oscuro == es_oscuro() and not forzar:
            return
        app = QApplication.instance()
        _instalar_envoltura()
        if self._qss_app_claro is None:
            self._qss_app_claro = app.styleSheet()
        _estado['oscuro'] = oscuro
        _estado['hubo_oscuro'] = _estado['hubo_oscuro'] or oscuro

        app.setPalette(_paleta(oscuro))
        if _estado['hubo_oscuro']:
            self._reaplicar_hojas_de_widgets(oscuro)
        for ventana in list(self._ventanas):
            self._aplicar_hoja_global(ventana)
        if guardar:
            QSettings("GestorApp", "Dashboard").setValue(CLAVE_AJUSTE, oscuro)
        self.tema_cambiado.emit(self.modo)

    def _aplicar_hoja_global(self, ventana):
        if es_oscuro() == self._oscuro_en_app:
            hoja = ""
        else:
            hoja = convertir_qss(self._qss_app_claro) if es_oscuro() else (self._qss_app_claro or "")
        if ventana.styleSheet() != hoja:
            _set_style_sheet_original(ventana, hoja)

    def _reaplicar_hojas_de_widgets(self, oscuro):
        """Los widgets visibles se reestilizan al instante; los ocultos
        (otras pestañas, paneles cerrados) esperan a mostrarse, que es donde
        setStyleSheet cuesta más y nadie lo ve."""
        for widget in QApplication.allWidgets():
            if widget in self._ventanas:
                continue
            if widget.isVisible():
                self._sincronizar_widget(widget, oscuro)
            elif widget.styleSheet() or widget.property(_PROP_ORIGINAL) is not None:
                widget.installEventFilter(self)

    @staticmethod
    def _sincronizar_widget(widget, oscuro):
        original = widget.property(_PROP_ORIGINAL)
        if oscuro:
            if original is not None:
                return
            qss = widget.styleSheet()
            if not qss:
                return
            convertido = convertir_qss(qss)
            if convertido != qss:
                widget.setProperty(_PROP_ORIGINAL, qss)
                _set_style_sheet_original(widget, convertido)
        elif original is not None:
            widget.setProperty(_PROP_ORIGINAL, None)
            _set_style_sheet_original(widget, original)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            obj.removeEventFilter(self)
            self._sincronizar_widget(obj, es_oscuro())
        return False
