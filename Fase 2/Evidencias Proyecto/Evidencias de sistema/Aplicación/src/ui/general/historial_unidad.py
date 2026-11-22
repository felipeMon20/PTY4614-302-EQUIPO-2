"""Piezas visuales del Historial de una unidad: ciclo de vida (activación, conexión y baja) y cambios agrupados por día."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QGridLayout, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal
from src.theme.colors import BORDER, TEXT_MUTED, TEXT_PRIMARY
from src.theme.theme_manager import ThemeManager

# (color fuerte, color de fondo) por tono
_TONOS = {
    'verde': ('#0F9D6E', '#DDF3EB'), 'rojo': ('#D6453F', '#FBE3E3'), 'azul': ('#1F6FEB', '#E3EDFD'),
    'gris': ('#52607A', '#EAEEF4'), 'ambar': ('#B86E00', '#FDF0D5'),
}
_FONDO_SUAVE = '#F6F8FC'
_ICONOS_PASO = {'activacion': ('fa5s.bolt', 'ambar'), 'conexion': ('fa5s.wifi', 'verde'), 'baja': ('fa5s.power-off', 'rojo')}


def _etiqueta(texto, estilo, ajustar=False):
    lbl = QLabel(str(texto))
    lbl.setStyleSheet(f"{estilo} background: transparent; border: none;")
    lbl.setWordWrap(ajustar)
    return lbl


def _pastilla(texto, color, fondo, tamano=10, subrayado=False):
    lbl = QLabel(str(texto))
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color: {color}; background-color: {fondo}; border: none; border-radius: 8px; padding: 1px 8px; "
                      f"font-size: {tamano}px; font-weight: bold;" + (" text-decoration: line-through;" if subrayado else ""))
    lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
    return lbl


def _icono(nombre, color, tam):
    lbl = QLabel()
    lbl.setPixmap(ThemeManager.icon_pixmap(nombre, color=color, size=tam))
    lbl.setStyleSheet("background: transparent; border: none;")
    return lbl


def titulo_seccion(texto, etiqueta=None):
    fila = QHBoxLayout()
    fila.setContentsMargins(0, 0, 0, 0)
    fila.setSpacing(10)
    lbl = _etiqueta(texto.upper(), f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 800; letter-spacing: 1px;")
    fila.addWidget(lbl)
    if etiqueta:
        tag = QLabel(etiqueta)
        tag.setStyleSheet(f"color: {TEXT_MUTED}; background-color: {_FONDO_SUAVE}; border: 1px solid {BORDER}; "
                          "border-radius: 9px; padding: 1px 10px; font-size: 10px; font-weight: bold;")
        fila.addWidget(tag)
    fila.addStretch()
    cont = QWidget()
    cont.setLayout(fila)
    return cont


class _PasoCicloVida(QFrame):
    """Un hito: pasó a activación, se conectó o se dio de baja."""

    def __init__(self, hito, parent=None):
        super().__init__(parent)
        icono, tono = _ICONOS_PASO[hito['clave']]
        fuerte, fondo = _TONOS[tono]
        vigente = hito['clave'] == 'baja' and not hito['alcanzado'] and hito.get('vigente')
        if vigente:
            fuerte, fondo, icono = _TONOS['verde'][0], _TONOS['verde'][1], 'fa5s.check'
        elif not hito['alcanzado']:
            fuerte, fondo = TEXT_MUTED, '#EAEEF4'
        self.setObjectName("pasoCiclo")
        borde = "1px solid " + BORDER if (hito['alcanzado'] or vigente) else "1px dashed #C9D2E2"
        self.setStyleSheet(f"QFrame#pasoCiclo {{ background-color: {'#FFFFFF' if (hito['alcanzado'] or vigente) else 'transparent'}; "
                           f"border: {borde}; border-radius: 13px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 11, 13, 11)
        lay.setSpacing(2)

        cab = QHBoxLayout()
        cab.setSpacing(9)
        punto = QLabel()
        punto.setFixedSize(30, 30)
        punto.setAlignment(Qt.AlignmentFlag.AlignCenter)
        punto.setPixmap(ThemeManager.icon_pixmap(icono, color=fuerte, size=14))
        punto.setStyleSheet(f"background-color: {fondo}; border: none; border-radius: 15px;")
        cab.addWidget(punto)
        cab.addWidget(_etiqueta(hito['titulo'], f"color: {TEXT_MUTED}; font-size: 12px; font-weight: bold;", True), 1)
        lay.addLayout(cab)
        lay.addSpacing(4)

        if hito['alcanzado']:
            lay.addWidget(_etiqueta(hito['fecha'], f"color: {TEXT_PRIMARY}; font-size: 19px; font-weight: 800;"))
            lay.addWidget(_etiqueta(f"{hito['hora']} h" if hito['hora'] else " ", f"color: {TEXT_MUTED}; font-size: 12px; font-weight: bold;"))
            fuente_texto, fuente_tono = ("Historial", 'azul') if hito.get('fuente') == 'historial' else ("Contrato", 'gris')
            chips = QHBoxLayout()
            chips.setSpacing(5)
            chips.addWidget(_pastilla(fuente_texto, *_TONOS[fuente_tono]))
            if hito.get('tras'):
                chips.addWidget(_pastilla(hito['tras'], *_TONOS['verde']))
            chips.addStretch()
            lay.addSpacing(4)
            lay.addLayout(chips)
            if hito.get('detalle'):
                lay.addWidget(_etiqueta(hito['detalle'], f"color: {TEXT_MUTED}; font-size: 11px;", True))
        elif vigente:
            lay.addWidget(_etiqueta("Sin baja", "color: #0F9D6E; font-size: 19px; font-weight: 800;"))
            lay.addWidget(_etiqueta("Unidad vigente", f"color: {TEXT_MUTED}; font-size: 11px;"))
        else:
            lay.addWidget(_etiqueta("Sin registro", f"color: {TEXT_MUTED}; font-size: 16px; font-weight: bold;"))
            lay.addWidget(_etiqueta("No hay fecha en el historial ni en el contrato", f"color: {TEXT_MUTED}; font-size: 11px;", True))
        lay.addStretch(1)


def crear_ciclo_vida(datos):
    """Tres hitos en fila, unidos por flechas, y debajo cuánto lleva (o estuvo) conectada la unidad."""
    cont = QWidget()
    cont.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(cont)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(titulo_seccion("Ciclo de vida"))
    fila = QHBoxLayout()
    fila.setSpacing(6)
    for i, hito in enumerate(datos['hitos']):
        if i:
            fila.addWidget(_icono('fa5s.chevron-right', '#B7C2D6', 11), 0, Qt.AlignmentFlag.AlignVCenter)
        fila.addWidget(_PasoCicloVida(hito), 1)
    lay.addLayout(fila)
    if datos.get('resumen_conexion'):
        cerrada = datos['hitos'][2]['alcanzado']
        fuerte, fondo = _TONOS['gris'] if cerrada else _TONOS['verde']
        pastilla = QLabel(datos['resumen_conexion'])
        pastilla.setStyleSheet(f"color: {fuerte}; background-color: {fondo}; border: none; border-radius: 12px; "
                               "padding: 4px 13px; font-size: 12px; font-weight: bold;")
        pastilla.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        lay.addWidget(pastilla, 0, Qt.AlignmentFlag.AlignLeft)
    return cont


class _CabezaClicable(QFrame):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _TarjetaGuardado(QFrame):
    """Los cambios guardados juntos: título, hora, módulo y, desplegable, cada campo con su antes y ahora."""
    alto_cambiado = pyqtSignal()

    def __init__(self, g, parent=None):
        super().__init__(parent)
        fuerte, _ = _TONOS.get(g['tono'], _TONOS['gris'])
        self.setObjectName("guardadoHistorial")
        self.setStyleSheet(f"QFrame#guardadoHistorial {{ background-color: #FFFFFF; border: 1px solid {BORDER}; "
                           f"border-left: 4px solid {fuerte}; border-radius: 12px; }}")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabeza = _CabezaClicable()
        cabeza.setCursor(Qt.CursorShape.PointingHandCursor)
        cabeza.setStyleSheet("QFrame { background: transparent; border: none; }")
        fila = QHBoxLayout(cabeza)
        fila.setContentsMargins(12, 9, 12, 9)
        fila.setSpacing(9)
        hora = QLabel(g['hora'])
        hora.setStyleSheet(f"color: {TEXT_MUTED}; background-color: {_FONDO_SUAVE}; border: none; border-radius: 7px; "
                           "padding: 2px 8px; font-size: 11px; font-weight: bold;")
        fila.addWidget(hora)
        fila.addWidget(_etiqueta(g['titulo'], f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 800;", True))
        if g['modulo']:
            color, fondo = _TONOS['verde'] if g['modulo'] == 'Comercial' else _TONOS['azul']
            fila.addWidget(_pastilla(g['modulo'], color, fondo))
        fila.addStretch(1)
        cuenta = f"{g['n']} {'campo' if g['n'] == 1 else 'campos'}"
        fila.addWidget(_etiqueta(cuenta, f"color: {TEXT_MUTED}; font-size: 11px; font-weight: bold;"))
        self._flecha = QLabel()
        self._flecha.setStyleSheet("background: transparent; border: none;")
        fila.addWidget(self._flecha)
        raiz.addWidget(cabeza)

        if g['chips']:
            chips = QWidget()
            chips.setStyleSheet("background: transparent;")
            lay_chips = QHBoxLayout(chips)
            lay_chips.setContentsMargins(12, 0, 12, 9)
            lay_chips.setSpacing(6)
            for texto in g['chips']:
                lay_chips.addWidget(_pastilla(texto, *_TONOS['gris'], tamano=11))
            lay_chips.addStretch()
            raiz.addWidget(chips)

        self._cuerpo = QFrame()
        self._cuerpo.setStyleSheet(f"QFrame {{ background-color: {_FONDO_SUAVE}; border: none; border-top: 1px solid {BORDER}; "
                                   "border-bottom-right-radius: 12px; }")
        grilla = QGridLayout(self._cuerpo)
        grilla.setContentsMargins(12, 6, 12, 8)
        grilla.setHorizontalSpacing(12)
        grilla.setVerticalSpacing(5)
        grilla.setColumnMinimumWidth(0, 150)
        grilla.setColumnStretch(1, 1)
        for i, f in enumerate(g['filas']):
            grilla.addWidget(_etiqueta(f['campo'].upper(), f"color: {TEXT_MUTED}; font-size: 10px; font-weight: 800; letter-spacing: 1px;", True),
                             i, 0, Qt.AlignmentFlag.AlignTop)
            cambio = QHBoxLayout()
            cambio.setSpacing(7)
            if f['antes'] and f['antes'] != '-':
                cambio.addWidget(_pastilla(f['antes'], *_TONOS['rojo'], tamano=12, subrayado=True))
                cambio.addWidget(_icono('fa5s.long-arrow-alt-right', TEXT_MUTED, 12))
            cambio.addWidget(_pastilla(f['ahora'], *_TONOS['verde'], tamano=12))
            cambio.addStretch(1)
            grilla.addLayout(cambio, i, 1)
        raiz.addWidget(self._cuerpo)

        self._abrir(not g['creado'] and g['n'] <= 8)
        cabeza.clicked.connect(lambda: self._abrir(not self._cuerpo.isVisible(), avisar=True))

    def _abrir(self, abierto, avisar=False):
        self._cuerpo.setVisible(abierto)
        self._flecha.setPixmap(ThemeManager.icon_pixmap('fa5s.chevron-up' if abierto else 'fa5s.chevron-down', color=TEXT_MUTED, size=10))
        if avisar:
            self.alto_cambiado.emit()


def crear_dia(dia, al_cambiar_alto):
    """Encabezado del día («11-11-2026 · Hoy») y una tarjeta por cada guardado de ese día."""
    cont = QWidget()
    cont.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(cont)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(7)
    cab = QHBoxLayout()
    cab.setSpacing(9)
    cab.addWidget(_etiqueta(dia['dia'], f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: 800;"))
    if dia['rel']:
        cab.addWidget(_etiqueta(dia['rel'], f"color: {TEXT_MUTED}; font-size: 11px; font-weight: bold;"))
    linea = QFrame()
    linea.setFixedHeight(1)
    linea.setStyleSheet(f"background-color: {BORDER}; border: none;")
    cab.addWidget(linea, 1, Qt.AlignmentFlag.AlignVCenter)
    lay.addLayout(cab)
    for g in dia['guardados']:
        tarjeta = _TarjetaGuardado(g)
        tarjeta.alto_cambiado.connect(al_cambiar_alto)
        lay.addWidget(tarjeta)
    return cont
