"""Notificaciones de la barra superior.

PanelNotificaciones: desplegable de la campana, un aviso por cada actualización de un archivo vigilado
(agrupado por día), con hora, archivo de origen y el detalle de cada cambio al expandirlo. Clic derecho
sobre un cambio copia su VIN; sobre el encabezado de un aviso, todos los VIN del aviso.

EstadoSincronizacion: pastilla del encabezado con el estado de los archivos vigilados (al día, detectando
cambios o actualizado)."""
import time
from datetime import datetime, timedelta

import qtawesome as qta
from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal, QVariantAnimation, QEasingCurve, QPoint, QEvent
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QScrollArea,
                             QMenu, QApplication, QToolTip)

from src.theme import tema
from src.ui.compartido import comercial_estilo as estilo_com

class MenuAnimado(QMenu):
    """Menú que sube y se desvanece al abrirse y baja y se desvanece al cerrarse (también al hacer clic fuera)."""

    DESPLAZAMIENTO = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        # Ventana sin marco ni sombra nativa y con fondo translúcido: así se ven las esquinas redondeadas
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._cuadro)
        self._anim.finished.connect(self._termino_anim)
        self._cerrando = False
        self._cierre_listo = False
        self._sin_fantasma = False
        self._destino = QPoint()
        self.cerrado_en = 0.0
        self.boton_ancla = None  # botón que abre el menú: un clic sobre él mientras está abierto solo lo cierra

    def showEvent(self, event):
        QApplication.instance().installEventFilter(self)
        super().showEvent(event)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self.cerrado_en = time.monotonic()
        if not self._sin_fantasma and self.windowOpacity() > 0.5:
            self._desvanecer_copia()
        self._sin_fantasma = False
        super().hideEvent(event)

    def _desvanecer_copia(self):
        """Qt cierra los menús al hacer clic fuera sin pasar por setVisible: se anima una foto del panel."""
        from PyQt6.QtWidgets import QLabel
        foto = self.grab()
        copia = QLabel(self.parentWidget())
        copia.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        copia.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        copia.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        copia.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        copia.setPixmap(foto)
        copia.resize(foto.size() / foto.devicePixelRatio())
        base = self.pos()
        copia.move(base)
        copia.setWindowOpacity(1.0)
        copia.show()
        anim = QVariantAnimation(copia)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setDuration(150)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)

        def _paso(v):
            v = float(v)
            copia.setWindowOpacity(max(0.0, min(1.0, v)))
            copia.move(base.x(), base.y() - round(self.DESPLAZAMIENTO * (1 - v)))
        anim.valueChanged.connect(_paso)
        anim.finished.connect(copia.deleteLater)
        anim.start()

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.MouseButtonPress and self.boton_ancla is not None and self.isVisible()):
            try:
                if self.boton_ancla.rect().contains(self.boton_ancla.mapFromGlobal(event.globalPosition().toPoint())):
                    self.setVisible(False)
                    return True
            except (AttributeError, RuntimeError):
                pass
        return False

    def mostrar(self, punto):
        self._anim.stop()
        self._cerrando = False
        self._cierre_listo = False
        self.setWindowOpacity(0.0)
        self.popup(punto)
        self._destino = self.pos()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._cuadro(0.0)
        self._anim.start()

    def _cuadro(self, v):
        v = float(v)
        self.setWindowOpacity(max(0.0, min(1.0, v)))
        self.move(self._destino.x(), self._destino.y() - round(self.DESPLAZAMIENTO * (1 - v)))

    def _termino_anim(self):
        if self._cerrando:
            self._cierre_listo = True
            self.setVisible(False)

    def setVisible(self, visible):
        if not visible and self.isVisible() and not self._cierre_listo:
            if not self._cerrando:
                self._cerrando = True
                self._anim.stop()
                self._anim.setStartValue(float(self.windowOpacity()))
                self._anim.setEndValue(0.0)
                self._anim.setDuration(150)
                self._anim.setEasingCurve(QEasingCurve.Type.InCubic)
                self._anim.start()
            return
        if not visible:
            self._sin_fantasma = self._cerrando or self._cierre_listo
            self._cerrando = False
            self._cierre_listo = False
            self.cerrado_en = time.monotonic()
        super().setVisible(visible)


ANCHO_PANEL = 420
ALTO_LISTA = 380
MAX_EVENTOS = 100
MAX_FILAS_DETALLE = 40
# Entidad por defecto de los avisos: (singular, plural, género) para concordar «agregada/agregado»
ENTIDAD_UNIDAD = ("unidad", "unidades", "f")

_TIPOS = {
    'Alta': ('fa5s.plus-circle', '#0F9D6E', '#DDF3EB', 'agregad'),
    'Baja': ('fa5s.trash-alt', '#E04848', '#FBE3E3', 'eliminad'),
    'Modificación': ('fa5s.edit', '#1F6FEB', '#E6EFFD', 'modificad'),
    'Renovación': ('fa5s.sync-alt', '#7C4DDE', '#EFE9FC', 'renovad'),
    # Cientos de filas de una vez: un solo aviso con cuántas filas cambió cada columna
    'Carga masiva': ('fa5s.layer-group', '#D98404', '#FBEBD0', 'modificad'),
}
# Estado de gestión de Oportunidades CM (Negociación, Espera, Sin gestión): su aviso va primero
_TIPOS = {'Gestión CM': ('fa5s.handshake', '#0F766E', '#DDF3EF', 'actualizad'), **_TIPOS}
# Los avisos de renovación hablan de contratos, sea cual sea la entidad del archivo
ENTIDAD_CONTRATO = ("contrato", "contratos", "m")
_TIPOS_CON_CAMBIO = ('Modificación', 'Renovación', 'Gestión CM')   # muestran «antes → ahora»
_ICONO_LOTE = ('fa5s.th-list', '#D98404', '#FBEBD0')


def _px(nombre, color, tam):
    """Ícono del color pedido en claro y su equivalente aclarado en oscuro."""
    return qta.icon(nombre, color=tema.texto(color).name()).pixmap(QSize(tam, tam))


def _etiqueta_dia(fecha):
    hoy = datetime.now().date()
    if fecha.date() == hoy:
        return "Hoy"
    if fecha.date() == hoy - timedelta(days=1):
        return "Ayer"
    return fecha.strftime("%d-%m-%Y")


def hace_cuanto(fecha):
    segundos = (datetime.now() - fecha).total_seconds()
    if segundos < 60:
        return "ahora"
    if segundos < 3600:
        return f"hace {int(segundos // 60)} min"
    if segundos < 86400 and fecha.date() == datetime.now().date():
        return f"hace {int(segundos // 3600)} h"
    return fecha.strftime("%d-%m %H:%M")


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


def _boton_icono(nombre, tooltip, accion):
    btn = QPushButton()
    btn.setFixedSize(32, 32)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tooltip)
    btn.setIcon(qta.icon(nombre, color=tema.texto('#66748D').name()))
    btn.setIconSize(QSize(15, 15))
    btn.setStyleSheet("QPushButton { background: transparent; border: none; border-radius: 9px; }"
                      "QPushButton:hover { background-color: #E6EFFD; }")
    btn.clicked.connect(accion)
    return btn


class _TarjetaEvento(QFrame):
    def __init__(self, evento, parent=None):
        super().__init__(parent)
        self.setObjectName("ntfTarjeta")
        self.setStyleSheet("QFrame#ntfTarjeta { background-color: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 13px; }"
                           "QFrame#ntfTarjeta:hover { border-color: #C7D5EC; }")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        icono_nombre, color, fondo_icono = evento['icono']

        cabeza = _Cabeza()
        cabeza.setObjectName("ntfCabeza")
        cabeza.setCursor(Qt.CursorShape.PointingHandCursor)
        cabeza.setStyleSheet("QFrame#ntfCabeza { background: transparent; border: none; }")
        fila = QHBoxLayout(cabeza)
        fila.setContentsMargins(0, 0, 12, 0)
        fila.setSpacing(11)

        # Franja de color: solo en avisos sin leer
        acento = QFrame()
        acento.setFixedWidth(4)
        acento.setStyleSheet(f"background-color: {'transparent' if evento['leido'] else color}; border: none; "
                             "border-top-left-radius: 12px; border-bottom-left-radius: 12px;")
        fila.addWidget(acento)

        icono = QLabel()
        icono.setFixedSize(38, 38)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(_px(icono_nombre, color, 17))
        icono.setStyleSheet(f"background-color: {fondo_icono}; border-radius: 12px;")
        fila.addWidget(icono, 0, Qt.AlignmentFlag.AlignVCenter)

        textos = QVBoxLayout()
        textos.setContentsMargins(0, 10, 0, 10)
        textos.setSpacing(2)
        linea1 = QHBoxLayout()
        linea1.setSpacing(7)
        titulo = QLabel(evento['titulo'])
        titulo.setStyleSheet("color: #0F1B33; font-size: 13px; font-weight: 800; background: transparent;")
        linea1.addWidget(titulo)
        linea1.addStretch()
        n = len(evento['detalle'])
        if evento['detalle'][0].get('tipo') == 'Carga masiva':
            cuenta = QLabel("Resumen")
        else:
            cuenta = QLabel(f"{n} {'cambio' if n == 1 else 'cambios'}")
        cuenta.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: 800; background-color: {fondo_icono}; "
                             "border-radius: 8px; padding: 2px 8px;")
        linea1.addWidget(cuenta)
        linea2 = QHBoxLayout()
        linea2.setSpacing(7)
        chip = QLabel(evento['archivo'].upper())
        chip.setStyleSheet("color: #52607A; font-size: 9px; font-weight: 800; letter-spacing: 0.5px; "
                           "background-color: #F1F5F9; border-radius: 6px; padding: 2px 7px;")
        hoy = evento['fecha'].date() == datetime.now().date()
        cuando = (f"{hace_cuanto(evento['fecha'])}  ·  {evento['fecha'].strftime('%H:%M')}" if hoy
                  else evento['fecha'].strftime('%d-%m-%Y  ·  %H:%M'))
        sub = QLabel(cuando)
        sub.setStyleSheet("color: #66748D; font-size: 12px; background: transparent;")
        linea2.addWidget(chip)
        linea2.addWidget(sub)
        linea2.addStretch()
        textos.addLayout(linea1)
        textos.addLayout(linea2)
        fila.addLayout(textos, 1)

        self._flecha = QLabel()
        self._flecha.setPixmap(_px('fa5s.chevron-down', '#66748D', 10))
        self._flecha.setStyleSheet("background: transparent;")
        fila.addWidget(self._flecha, 0, Qt.AlignmentFlag.AlignVCenter)
        for hijo in (acento, icono, titulo, chip, cuenta, sub, self._flecha):
            hijo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        raiz.addWidget(cabeza)

        self._detalle = QWidget()
        self._detalle.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(self._detalle)
        lay.setContentsMargins(14, 0, 14, 10)
        lay.setSpacing(6)
        por_id = {}
        for d in evento['detalle'][:MAX_FILAS_DETALLE]:
            por_id.setdefault(d['VIN'], []).append(d)
        self._es_vin = all(d.get('es_vin', True) for d in evento['detalle'])
        self._todos_vin = list(dict.fromkeys(str(d['VIN']) for d in evento['detalle']))
        for identificador, filas in por_id.items():
            bloque = self._bloque(identificador, filas)
            bloque.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            bloque.customContextMenuRequested.connect(
                lambda pos, b=bloque, v=identificador: self._menu_copiar(b.mapToGlobal(pos), v))
            lay.addWidget(bloque)
        if len(evento['detalle']) > MAX_FILAS_DETALLE:
            mas = QLabel(f"y {len(evento['detalle']) - MAX_FILAS_DETALLE} cambios más")
            mas.setStyleSheet("color: #66748D; font-size: 11px; padding: 4px 2px; background: transparent;")
            lay.addWidget(mas)
        self._detalle.hide()
        raiz.addWidget(self._detalle)
        cabeza.clicked.connect(self._alternar)
        cabeza.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        cabeza.customContextMenuRequested.connect(lambda pos, c=cabeza: self._menu_copiar(c.mapToGlobal(pos), None))

    def _menu_copiar(self, pos_global, identificador):
        """Clic derecho: copiar el VIN del cambio, o todos los VIN del aviso."""
        palabra = "VIN" if self._es_vin else "identificador"
        from src.ui.compartido.menu_contextual import crear_menu
        menu = crear_menu(self)
        n = len(self._todos_vin)
        copiar_uno = menu.accion(f"Copiar {palabra}", 'fa5s.barcode') if identificador else None
        copiar_todos = menu.accion(
            f"Copiar los {n} {palabra if self._es_vin else 'identificadores'} de este aviso",
            'fa5s.clone') if n > 1 or not identificador else None
        elegido = menu.exec(pos_global)
        if elegido is None:
            return
        QApplication.clipboard().setText(identificador if elegido is copiar_uno else "\n".join(self._todos_vin))
        QToolTip.showText(pos_global, f"{palabra.capitalize()} copiado" if elegido is copiar_uno else f"{n} copiados")

    def _bloque(self, identificador, filas):
        es_vin = filas[0].get('es_vin', True)
        marco = QFrame()
        marco.setObjectName("ntfVin")
        marco.setStyleSheet("QFrame#ntfVin { background-color: #F7F9FC; border: 1px solid #EDF1F7; border-radius: 10px; }")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(11, 8, 11, 8)
        lay.setSpacing(4)
        cab = QLabel(identificador)
        fuente = "font-family: Consolas; font-size: 11px;" if es_vin else "font-size: 12px;"
        cab.setStyleSheet(f"color: #0F1B33; {fuente} font-weight: 700; background: transparent; border: none;")
        lay.addWidget(cab)
        for d in filas:
            f = QHBoxLayout()
            f.setSpacing(8)
            largo = d['tipo'] in _TIPOS_CON_CAMBIO and len(str(d['viejo'])) + len(str(d['nuevo'])) > 30
            campo = QLabel(str(d['campo']))
            if not largo:
                campo.setFixedWidth(128)
            campo.setWordWrap(True)
            campo.setStyleSheet("color: #66748D; font-size: 11px; background: transparent; border: none;")
            if largo:
                # Valores largos: el campo arriba y el cambio debajo, para que no se salga del bloque
                lay.addWidget(campo)
            else:
                f.addWidget(campo, 0, Qt.AlignmentFlag.AlignTop)
            if d['tipo'] in _TIPOS_CON_CAMBIO:
                viejo = QLabel(str(d['viejo']))
                viejo.setStyleSheet("color: #E04848; background-color: #FBE3E3; font-size: 11px; border-radius: 5px; padding: 1px 6px;")
                flecha = QLabel("→")
                flecha.setStyleSheet("color: #66748D; font-size: 11px; background: transparent; border: none;")
                nuevo = QLabel(str(d['nuevo']))
                nuevo.setStyleSheet("color: #0F9D6E; background-color: #DDF3EB; font-size: 11px; font-weight: 700; "
                                    "border-radius: 5px; padding: 1px 6px;")
                f.addWidget(viejo)
                f.addWidget(flecha)
                f.addWidget(nuevo)
            f.addStretch()
            lay.addLayout(f)
        return marco

    def _alternar(self):
        visible = not self._detalle.isVisible()
        self._detalle.setVisible(visible)
        self._flecha.setPixmap(_px('fa5s.chevron-up' if visible else 'fa5s.chevron-down', '#66748D', 10))


class PanelNotificaciones(QWidget):
    """Contenido del menú de la campana. Emite la cantidad de avisos sin leer."""

    no_leidos_cambiado = pyqtSignal(int)

    def __init__(self, archivos_vigilados=(), parent=None):
        super().__init__(parent)
        self._eventos = []
        self._archivos = tuple(archivos_vigilados)
        self.setFixedWidth(ANCHO_PANEL)
        self.setObjectName("panelNotificaciones")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QWidget#panelNotificaciones { background-color: #FFFFFF; border-radius: 16px; }")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        cabecera = QHBoxLayout()
        cabecera.setContentsMargins(16, 14, 12, 10)
        cabecera.setSpacing(11)
        marca = QLabel()
        marca.setFixedSize(36, 36)
        marca.setAlignment(Qt.AlignmentFlag.AlignCenter)
        marca.setPixmap(_px('fa5s.bell', '#1F6FEB', 16))
        marca.setStyleSheet("background-color: #E6EFFD; border-radius: 11px;")
        self._marca = marca
        cabecera.addWidget(marca)
        bloque = QVBoxLayout()
        bloque.setSpacing(0)
        titulo = QLabel("Notificaciones")
        titulo.setStyleSheet("color: #0F1B33; font-size: 15px; font-weight: 800; background: transparent;")
        self._resumen = QLabel()
        self._resumen.setStyleSheet("color: #66748D; font-size: 12px; background: transparent;")
        bloque.addWidget(titulo)
        bloque.addWidget(self._resumen)
        cabecera.addLayout(bloque, 1)
        cabecera.addWidget(_boton_icono('fa5s.check-double', "Marcar todo como leído", self.marcar_leidos))
        cabecera.addWidget(_boton_icono('fa5s.trash-alt', "Limpiar la lista", self.limpiar))
        raiz.addLayout(cabecera)

        linea = QFrame()
        linea.setFixedHeight(1)
        linea.setStyleSheet("background-color: #E3E8F0; border: none;")
        raiz.addWidget(linea)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(ALTO_LISTA)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        self._cuerpo = QWidget()
        self._cuerpo.setStyleSheet("background: transparent;")
        self._lista = QVBoxLayout(self._cuerpo)
        self._lista.setContentsMargins(12, 4, 12, 10)
        self._lista.setSpacing(8)
        self._scroll.setWidget(self._cuerpo)
        raiz.addWidget(self._scroll)

        self._pie = QFrame()
        self._pie.setObjectName("ntfPie")
        self._pie.setStyleSheet("QFrame#ntfPie { background-color: #F7F9FC; border-top: 1px solid #E3E8F0; "
                                "border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; }")
        fila_pie = QHBoxLayout(self._pie)
        fila_pie.setContentsMargins(16, 9, 16, 9)
        fila_pie.setSpacing(7)
        punto = QLabel()
        punto.setFixedSize(8, 8)
        punto.setStyleSheet("background-color: #0F9D6E; border-radius: 4px;")
        fila_pie.addWidget(punto)
        lbl_vigilados = QLabel("Vigilando: " + " · ".join(self._archivos))
        lbl_vigilados.setWordWrap(True)
        lbl_vigilados.setStyleSheet("color: #52607A; font-size: 11px; font-weight: 600; background: transparent; border: none;")
        fila_pie.addWidget(lbl_vigilados, 1)
        self._lbl_revision = QLabel("")
        self._lbl_revision.setStyleSheet("color: #66748D; font-size: 11px; background: transparent; border: none;")
        fila_pie.addWidget(self._lbl_revision)
        raiz.addWidget(self._pie)
        self._pie.setVisible(bool(self._archivos))
        tema.GestorTema.instancia().tema_cambiado.connect(self._al_cambiar_tema)
        self._repintar()

    def _al_cambiar_tema(self, *_):
        self._marca.setPixmap(_px('fa5s.bell', '#1F6FEB', 16))
        self._repintar()

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        # Un clic en cualquier parte del panel no debe llegar al QMenu que lo contiene
        event.accept()

    def fijar_revision(self, fecha=None):
        """Hora de la última comprobación de los archivos, en el pie del panel."""
        self._lbl_revision.setText(f"Revisado {(fecha or datetime.now()).strftime('%H:%M')}")

    @staticmethod
    def _titulo(unidades, tipo, entidad):
        singular, plural, genero = ENTIDAD_CONTRATO if tipo == 'Renovación' else entidad
        participio = _TIPOS[tipo][3] + ('a' if genero == 'f' else 'o') + ('' if unidades == 1 else 's')
        if tipo == 'Gestión CM':
            return f"Gestión CM: {unidades} {singular if unidades == 1 else plural} {participio}"
        if tipo == 'Carga masiva':
            return f"Carga masiva: {unidades} {singular if unidades == 1 else plural}"
        return f"{unidades} {singular if unidades == 1 else plural} {participio}"

    def registrar(self, archivo, cambios, entidad=ENTIDAD_UNIDAD, fecha=None):
        """Agrega un aviso por tipo de cambio de una actualización de `archivo`."""
        if not cambios:
            return
        ahora = fecha or datetime.now()
        nuevos = []
        for tipo in _TIPOS:
            filas = [c for c in cambios if c['tipo'] == tipo]
            if not filas:
                continue
            unidades = filas[0].get('total') if tipo == 'Carga masiva' else len({c.get('clave', c['VIN']) for c in filas})
            icono = _TIPOS[tipo][:3] if tipo != 'Modificación' or unidades == 1 else _ICONO_LOTE
            nuevos.append({
                'fecha': ahora, 'archivo': archivo, 'leido': False, 'icono': icono, 'detalle': filas,
                'titulo': self._titulo(unidades, tipo, entidad),
            })
        self._eventos = (nuevos + self._eventos)[:MAX_EVENTOS]
        self.fijar_revision(ahora)
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
        n = self.no_leidos()
        self._resumen.setText("Todo al día" if not self._eventos else
                              (f"{n} sin leer" if n else f"{len(self._eventos)} avisos, todos leídos"))
        while self._lista.count():
            item = self._lista.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        if not self._eventos:
            self._lista.addStretch()
            icono = QLabel()
            icono.setFixedSize(60, 60)
            icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icono.setPixmap(_px('fa5s.bell-slash', '#8794AA', 24))
            icono.setStyleSheet("background-color: #F1F5F9; border-radius: 30px;")
            self._lista.addWidget(icono, 0, Qt.AlignmentFlag.AlignHCenter)
            t = QLabel("Todo al día")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setStyleSheet("color: #0F1B33; font-size: 14px; font-weight: 800; background: transparent; padding-top: 6px;")
            s = QLabel("Aquí te avisaremos cuando alguien\nmodifique los datos que vigila la aplicación.")
            s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            s.setStyleSheet("color: #66748D; font-size: 12px; background: transparent;")
            self._lista.addWidget(t)
            self._lista.addWidget(s)
            self._lista.addStretch()
            return
        ultimo = None
        for e in self._eventos:
            dia = _etiqueta_dia(e['fecha'])
            if dia != ultimo:
                fila = QWidget()
                fila.setStyleSheet("background: transparent;")
                lay = QHBoxLayout(fila)
                lay.setContentsMargins(4, 8, 4, 0)
                lay.setSpacing(8)
                lbl = QLabel(dia.upper())
                lbl.setStyleSheet("color: #66748D; font-size: 10px; font-weight: 800; letter-spacing: 1px; background: transparent;")
                raya = QFrame()
                raya.setFixedHeight(1)
                raya.setStyleSheet("background-color: #E3E8F0; border: none;")
                lay.addWidget(lbl)
                lay.addWidget(raya, 1)
                self._lista.addWidget(fila)
                ultimo = dia
            self._lista.addWidget(_TarjetaEvento(e))
        self._lista.addStretch()

