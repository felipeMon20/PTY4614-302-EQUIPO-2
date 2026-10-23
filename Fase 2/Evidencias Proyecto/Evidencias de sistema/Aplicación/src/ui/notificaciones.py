"""Desplegable de notificaciones de la campana: un aviso por cada actualización
de un archivo (agrupado por día), con hora, archivo de origen y el detalle de
cada cambio al expandirlo."""
from datetime import datetime, timedelta

import qtawesome as qta
from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea)

ANCHO_PANEL = 400
ALTO_LISTA = 400
MAX_EVENTOS = 100
MAX_FILAS_DETALLE = 40

_TIPOS = {
    'Alta': ('fa5s.plus-circle', '#0F9D6E', '#DDF3EB', 'agregada', 'agregadas'),
    'Baja': ('fa5s.trash-alt', '#E04848', '#FBE3E3', 'eliminada', 'eliminadas'),
    'Modificación': ('fa5s.edit', '#1F6FEB', '#E6EFFD', 'modificada', 'modificadas'),
}
_ICONO_LOTE = ('fa5s.th-list', '#D98404', '#FBEBD0')


def _etiqueta_dia(fecha):
    hoy = datetime.now().date()
    if fecha.date() == hoy:
        return "Hoy"
    if fecha.date() == hoy - timedelta(days=1):
        return "Ayer"
    return fecha.strftime("%d-%m-%Y")


class _Cabeza(QFrame):
    """Cabecera clicable de una tarjeta (un QPushButton con layout interno no calcula su alto)."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        event.accept()

    def mouseReleaseEvent(self, event):
        # Si el clic no se acepta, sube hasta el QMenu y este se cierra
        event.accept()


class _TarjetaEvento(QFrame):
    def __init__(self, evento, parent=None):
        super().__init__(parent)
        self.setObjectName("ntfTarjeta")
        fondo = "#E6EFFD" if not evento['leido'] else "#F7F9FC"
        self.setStyleSheet(f"QFrame#ntfTarjeta {{ background-color: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 12px; }}")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabeza = _Cabeza()
        cabeza.setObjectName("ntfCabeza")
        cabeza.setCursor(Qt.CursorShape.PointingHandCursor)
        cabeza.setStyleSheet(f"QFrame#ntfCabeza {{ background-color: {fondo}; border: none; border-radius: 11px; }}"
                             "QFrame#ntfCabeza:hover { background-color: #EEF3FB; }")
        fila = QHBoxLayout(cabeza)
        fila.setContentsMargins(10, 9, 10, 9)
        fila.setSpacing(10)

        icono_nombre, color, fondo_icono = evento['icono']
        icono = QLabel()
        icono.setFixedSize(34, 34)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(qta.icon(icono_nombre, color=color).pixmap(QSize(16, 16)))
        icono.setStyleSheet(f"background-color: {fondo_icono}; border-radius: 10px;")
        icono.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        fila.addWidget(icono, 0, Qt.AlignmentFlag.AlignTop)

        textos = QVBoxLayout()
        textos.setSpacing(1)
        linea1 = QHBoxLayout()
        linea1.setSpacing(6)
        titulo = QLabel(evento['titulo'])
        titulo.setStyleSheet("color: #0F1B33; font-size: 13px; font-weight: 700; background: transparent;")
        chip = QLabel(evento['archivo'].upper())
        chip.setStyleSheet("color: #66748D; font-size: 9px; font-weight: 800; letter-spacing: 0.5px; "
                           "background-color: #F7F9FC; border: 1px solid #E3E8F0; border-radius: 6px; padding: 1px 6px;")
        linea1.addWidget(titulo)
        linea1.addWidget(chip)
        linea1.addStretch()
        sin_leer = "" if evento['leido'] else " · sin leer"
        sub = QLabel(f"Actualización de las {evento['fecha'].strftime('%H:%M')}{sin_leer}")
        sub.setStyleSheet("color: #66748D; font-size: 12px; background: transparent;")
        textos.addLayout(linea1)
        textos.addWidget(sub)
        fila.addLayout(textos, 1)

        self._flecha = QLabel()
        self._flecha.setPixmap(qta.icon('fa5s.chevron-down', color='#66748D').pixmap(QSize(10, 10)))
        self._flecha.setStyleSheet("background: transparent;")
        fila.addWidget(self._flecha, 0, Qt.AlignmentFlag.AlignTop)
        for hijo in (titulo, chip, sub, self._flecha):
            hijo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        raiz.addWidget(cabeza)

        self._detalle = QWidget()
        self._detalle.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self._detalle)
        lay.setContentsMargins(12, 2, 12, 8)
        lay.setSpacing(0)
        filas = evento['detalle']
        for d in filas[:MAX_FILAS_DETALLE]:
            lay.addWidget(self._fila_detalle(d))
        if len(filas) > MAX_FILAS_DETALLE:
            mas = QLabel(f"y {len(filas) - MAX_FILAS_DETALLE} cambios más")
            mas.setStyleSheet("color: #66748D; font-size: 11px; padding: 6px 0;")
            lay.addWidget(mas)
        self._detalle.hide()
        raiz.addWidget(self._detalle)
        cabeza.clicked.connect(self._alternar)

    @staticmethod
    def _fila_detalle(d):
        marco = QFrame()
        marco.setStyleSheet("QFrame { border-top: 1px dashed #E3E8F0; background: transparent; }")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(0, 5, 0, 5)
        lay.setSpacing(2)
        encabezado = QLabel(f"<span style=\"font-family: Consolas; font-size: 11px; color: #0F1B33;\">{d['VIN']}</span>"
                            f"&nbsp;&nbsp;<span style=\"color: #66748D; font-size: 11px;\">{d['campo']}</span>")
        encabezado.setStyleSheet("border: none; background: transparent;")
        lay.addWidget(encabezado)
        if d['tipo'] == 'Modificación':
            cambio = QLabel(f"<span style=\"background-color: #FBE3E3; color: #E04848;\">&nbsp;<s>{d['viejo']}</s>&nbsp;</span>"
                            f"&nbsp;→&nbsp;<span style=\"background-color: #DDF3EB; color: #0F9D6E;\">&nbsp;{d['nuevo']}&nbsp;</span>")
            cambio.setStyleSheet("border: none; background: transparent; font-size: 11px; color: #66748D;")
            cambio.setWordWrap(True)
            lay.addWidget(cambio)
        return marco

    def _alternar(self):
        visible = not self._detalle.isVisible()
        self._detalle.setVisible(visible)
        nombre = 'fa5s.chevron-up' if visible else 'fa5s.chevron-down'
        self._flecha.setPixmap(qta.icon(nombre, color='#66748D').pixmap(QSize(10, 10)))


class PanelNotificaciones(QWidget):
    """Contenido del menú de la campana. Emite la cantidad de avisos sin leer."""

    no_leidos_cambiado = pyqtSignal(int)

    def __init__(self, archivos_vigilados=(), parent=None):
        super().__init__(parent)
        self._eventos = []
        self.setFixedWidth(ANCHO_PANEL)
        self.setObjectName("panelNotificaciones")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#panelNotificaciones { background-color: #FFFFFF; }")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabecera = QHBoxLayout()
        cabecera.setContentsMargins(14, 12, 10, 6)
        titulo = QLabel("Notificaciones")
        titulo.setStyleSheet("color: #0F1B33; font-size: 14px; font-weight: 800;")
        cabecera.addWidget(titulo, 1)
        for texto, accion in (("Marcar todo como leído", self.marcar_leidos), ("Limpiar", self.limpiar)):
            btn = QPushButton(texto)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("QPushButton { color: #1F6FEB; background: transparent; border: none; border-radius: 8px; "
                              "font-size: 12px; font-weight: 700; padding: 4px 6px; }"
                              "QPushButton:hover { background-color: #E6EFFD; }")
            btn.clicked.connect(accion)
            cabecera.addWidget(btn)
        raiz.addLayout(cabecera)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(ALTO_LISTA)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._cuerpo = QWidget()
        self._cuerpo.setStyleSheet("background: transparent;")
        self._lista = QVBoxLayout(self._cuerpo)
        self._lista.setContentsMargins(10, 0, 10, 8)
        self._lista.setSpacing(6)
        self._scroll.setWidget(self._cuerpo)
        raiz.addWidget(self._scroll)

        pie = QLabel("Archivos vigilados: " + " · ".join(archivos_vigilados) if archivos_vigilados else "")
        pie.setWordWrap(True)
        pie.setStyleSheet("color: #66748D; font-size: 11px; background-color: #F7F9FC; border-top: 1px solid #E3E8F0; padding: 9px 14px;")
        raiz.addWidget(pie)
        pie.setVisible(bool(archivos_vigilados))
        self._repintar()

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        # Un clic en cualquier parte del panel no debe llegar al QMenu que lo contiene
        event.accept()

    def registrar(self, archivo, cambios):
        """Agrega un aviso por tipo de cambio de una actualización de `archivo`."""
        if not cambios:
            return
        ahora = datetime.now()
        nuevos = []
        for tipo, (_i, _c, _f, singular, plural) in _TIPOS.items():
            filas = [c for c in cambios if c['tipo'] == tipo]
            if not filas:
                continue
            unidades = len({c['VIN'] for c in filas})
            icono = _TIPOS[tipo][:3] if tipo != 'Modificación' or unidades == 1 else _ICONO_LOTE
            nuevos.append({
                'fecha': ahora, 'archivo': archivo, 'leido': False, 'icono': icono, 'detalle': filas,
                'titulo': f"{unidades} {'unidad' if unidades == 1 else 'unidades'} {singular if unidades == 1 else plural}",
            })
        self._eventos = (nuevos + self._eventos)[:MAX_EVENTOS]
        self._repintar()
        self.no_leidos_cambiado.emit(self.no_leidos())

    def no_leidos(self):
        return sum(1 for e in self._eventos if not e['leido'])

    def marcar_leidos(self):
        for e in self._eventos:
            e['leido'] = True
        self._repintar()
        self.no_leidos_cambiado.emit(0)

    def limpiar(self):
        self._eventos = []
        self._repintar()
        self.no_leidos_cambiado.emit(0)

    def _repintar(self):
        while self._lista.count():
            item = self._lista.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if not self._eventos:
            vacio = QLabel("No hay modificaciones recientes")
            vacio.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vacio.setStyleSheet("color: #66748D; font-size: 12px; padding: 40px 10px; background: transparent;")
            self._lista.addWidget(vacio)
            self._lista.addStretch()
            return
        ultimo = None
        for e in self._eventos:
            dia = _etiqueta_dia(e['fecha'])
            if dia != ultimo:
                lbl = QLabel(dia.upper())
                lbl.setStyleSheet("color: #66748D; font-size: 10px; font-weight: 800; letter-spacing: 0.9px; "
                                  "padding: 8px 4px 2px; background: transparent;")
                self._lista.addWidget(lbl)
                ultimo = dia
            self._lista.addWidget(_TarjetaEvento(e))
        self._lista.addStretch()
