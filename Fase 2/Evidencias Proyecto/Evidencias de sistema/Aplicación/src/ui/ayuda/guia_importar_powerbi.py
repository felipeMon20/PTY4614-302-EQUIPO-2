"""Paneles que se muestran dentro de Comercial al importar el Excel de Power BI:
la guía paso a paso (un paso por pantalla, con ilustraciones dibujadas) y la confirmación."""
from PyQt6.QtCore import QEasingCurve, Qt, QUrl, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPainter, QPixmap
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from config.settings import REPORTE_NOTAS_VENTAS_URL
from src.ui.compartido import aviso_enlace
from src.theme.theme_manager import ThemeManager
from src.ui.compartido import comercial_estilo as estilo_com
_AZUL_OSCURO = "#1B2B4E"
_VERDE_BI = "#1B3A3F"
_ESTILO_BOTON_SEC = (
    f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
    "border-radius: 10px; padding: 0 16px; min-height: 40px; font-weight: 700; font-size: 13px; } "
    "QPushButton:hover { background: #F1F4F9; }")
_ESTILO_BOTON_PRIM = (
    f"QPushButton {{ background: {_AZUL_OSCURO}; color: white; border: none; border-radius: 10px; "
    "padding: 0 20px; min-height: 40px; font-weight: 700; font-size: 13px; } "
    "QPushButton:hover { background: #2C4A80; } QPushButton:disabled { background: #8E9BB5; }")
_ESTILO_BOTON_TEXTO = (
    f"QPushButton {{ background: transparent; color: {estilo_com.APAGADO}; border: none; padding: 0 14px; "
    "min-height: 40px; font-weight: 700; font-size: 13px; } "
    f"QPushButton:hover {{ color: {estilo_com.TINTA}; }}")


def _boton(texto, estilo, icono=None, color_icono='white'):
    b = QPushButton(texto)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setStyleSheet(estilo)
    if icono:
        b.setIcon(ThemeManager.icon(icono, color=color_icono))
    return b


def _etq(texto, estilo="", ajustar=False, alinear=None):
    e = QLabel(texto)
    e.setStyleSheet(f"background: transparent; border: none; {estilo}")
    e.setWordWrap(ajustar)
    if alinear is not None:
        e.setAlignment(alinear)
    return e


def _caja(objeto, estilo, direccion='v', margenes=(0, 0, 0, 0), espacio=0):
    f = QFrame()
    f.setObjectName(objeto)
    f.setStyleSheet(f"QFrame#{objeto} {{ {estilo} }} QLabel {{ background: transparent; border: none; }}")
    lay = QVBoxLayout(f) if direccion == 'v' else QHBoxLayout(f)
    lay.setContentsMargins(*margenes)
    lay.setSpacing(espacio)
    return f, lay


# ---------------------------------------------------------------
# Ilustraciones: dibujadas con widgets, no son capturas de pantalla
# ---------------------------------------------------------------
def _campo_bi(titulo, valor, resaltado=False):
    borde = "#FCD34D" if resaltado else "rgba(255,255,255,0.35)"
    f, lay = _caja(f"campoBi{abs(hash((titulo, valor)))}", f"border: {'2px' if resaltado else '1px'} solid {borde}; border-radius: 6px;",
                   margenes=(6, 4, 6, 5), espacio=3)
    lay.addWidget(_etq(titulo, "color: white; font-size: 9px; font-weight: 700;"))
    lay.addWidget(_etq(valor, "background: white; color: #222; font-size: 9px; padding: 3px 4px; border-radius: 3px;"))
    return f


def _tira_bi(campos):
    f, lay = _caja("tiraBi", f"background: {_VERDE_BI}; border-radius: 10px;", 'h', (10, 10, 10, 10), 8)
    titulo = _etq("NOTAS DE VENTA", "color: white; background: #0F1B33; font-size: 11px; font-weight: 800; padding: 8px 10px; border-radius: 8px;")
    lay.addWidget(titulo)
    for t, v, r in campos:
        lay.addWidget(_campo_bi(t, v, r), 1)
    f.setMaximumWidth(480)
    return f


def _tarjeta_blanca(objeto, ancho=440):
    f, lay = _caja(objeto, "background: white; border: 1px solid #D5DCE8; border-radius: 10px;", 'v', (0, 0, 0, 0), 0)
    f.setMaximumWidth(ancho)
    return f, lay


def _escena_abrir():
    f, lay = _tarjeta_blanca("escAbrir")
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(8)
    lay.addWidget(_etq("app.powerbi.com / Notas de Venta",
                       "color: #66748D; background: #EEF2F8; border-radius: 8px; padding: 6px 10px; font-size: 10px;"))
    lay.addWidget(_tira_bi([("Fecha Facturación", "2026 (Año) + octubre", False), ("Modelo", "Todas", False)]))
    lay.addWidget(_etq("Abrir Power BI", f"color: white; background: {estilo_com.PRIMARIO}; border-radius: 6px; padding: 6px 12px; "
                                         "font-size: 11px; font-weight: 700;"), alignment=Qt.AlignmentFlag.AlignLeft)
    return f


def _escena_filtros():
    return _tira_bi([("Fecha Facturación", "2026 (Año) + octub…", True), ("Fecha Entrega", "Todas", False),
                     ("Modelo", "Todas", False), ("Cliente", "Search", False)])


def _escena_tabla():
    f, lay = _tarjeta_blanca("escTabla")
    barra = QHBoxLayout()
    barra.setContentsMargins(8, 6, 8, 2)
    barra.addStretch(1)
    for i, simbolo in enumerate(("★", "□", "≡", "•••")):
        destacado = i == 3
        barra.addWidget(_etq(
            simbolo, f"color: {estilo_com.PRIMARIO if destacado else '#66748D'}; "
                     f"background: {'#E8F0FE' if destacado else 'white'}; "
                     f"border: {'2px solid #1F6FEB' if destacado else '1px solid #D5DCE8'}; border-radius: 5px; "
                     "font-size: 10px; font-weight: 800; padding: 2px 6px;"))
    lay.addLayout(barra)
    filas = (("Cliente", "Tipo", "Industria", True, False),
             ("Metalmecánica Mecsion", "VM360 6X2R", "Industrial", False, False),
             ("Collao Inversiones", "FMX13B 6x4 R", "Mining", False, True),
             ("Servicios Generales RJ", "FH13B 6x4 T", "Mining", False, False))
    for a, b, c, cabecera, seleccionada in filas:
        fila, fl = _caja(f"filaT{abs(hash((a, b)))}", "background: #14213A;" if cabecera else
                         f"background: {'#DCE8FD' if seleccionada else 'white'}; border-bottom: 1px solid #E3E8F0;",
                         'h', (8, 5, 8, 5), 8)
        color = "white" if cabecera else "#1b2430"
        for t, peso in ((a, 2), (b, 1), (c, 1)):
            fl.addWidget(_etq(t, f"color: {color}; font-size: 10px; font-weight: {600 if cabecera else 400};"), peso)
        lay.addWidget(fila)
    return f


def _escena_exportar():
    cont = QWidget()
    lay = QHBoxLayout(cont)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(14)
    menu, ml = _caja("escMenu", "background: white; border: 1px solid #D5DCE8; border-radius: 10px;", 'v', (6, 6, 6, 6), 2)
    for texto, resaltado in (("Compartir", False), ("Mostrar como tabla", False), ("Exportar datos", True), ("Obtener información", False)):
        ml.addWidget(_etq(texto, f"color: {'#1F6FEB' if resaltado else '#44506A'}; font-size: 11px; "
                                 f"font-weight: {700 if resaltado else 400}; padding: 6px 10px; border-radius: 6px; "
                                 f"background: {'#E8F0FE' if resaltado else 'transparent'};"))
    lay.addWidget(menu)
    modal, dl = _caja("escModal", "background: white; border: 1px solid #D5DCE8; border-radius: 10px;", 'v', (12, 12, 12, 12), 6)
    dl.addWidget(_etq("¿Qué datos quieres exportar?", "color: #1b2430; font-size: 11px; font-weight: 700;"))
    dl.addWidget(_etq("●  Datos con el diseño actual", "color: #1b2430; font-size: 10px;"))
    dl.addWidget(_etq("○  Datos resumidos", "color: #66748D; font-size: 10px;"))
    dl.addWidget(_etq("Exportar", f"color: white; background: {estilo_com.PRIMARIO}; border-radius: 5px; padding: 5px 10px; "
                                  "font-size: 10px; font-weight: 700;"), alignment=Qt.AlignmentFlag.AlignLeft)
    lay.addWidget(modal)
    return cont


def _escena_habilitar():
    f, lay = _caja("escExcel", "background: #1E1E24; border-radius: 10px;", 'v')
    f.setMaximumWidth(480)
    barra, bl = _caja("escExcelBarra", "background: #7A5C10; border-top-left-radius: 10px; border-top-right-radius: 10px;",
                      'h', (12, 8, 12, 8), 8)
    bl.addWidget(_etq("PROTECTED VIEW  Be careful, this file may have come from an unsafe source.",
                      "color: #F8EBC6; font-size: 10px;"), 1)
    bl.addWidget(_etq("Enable Editing", "color: white; background: #2B2B33; border: 2px solid #FCD34D; border-radius: 5px; "
                                        "padding: 3px 8px; font-size: 10px; font-weight: 700;"))
    lay.addWidget(barra)
    cuerpo = _etq("A1  Chasis   Chasis_II   VIN\nE217098   E217098   93KPZ60C9VE217098\nE218490   E218490   93KPZ60C0VE218490",
                  "color: #9aa0ae; font-family: Consolas, monospace; font-size: 10px; padding: 10px 12px;")
    lay.addWidget(cuerpo)
    return f


def _escena_sensibilidad():
    f, lay = _caja("escSens", "background: #26262E; border-radius: 10px;", 'v')
    f.setFixedWidth(270)
    lay.addWidget(_etq("Detalle.xlsx  ·  Confidential", "color: #E6E8EE; background: #1E1E24; font-size: 11px; font-weight: 700; "
                                                        "padding: 8px 12px; border-top-left-radius: 10px; border-top-right-radius: 10px;"))
    for texto, color, resaltado in (("Open", "#3F8F2A", False), ("Internal   ← elige esta", "#4C8DF6", True),
                                    ("Confidential  ✓", "#9aa0ae", False), ("Strictly Confidential", "#9aa0ae", False)):
        lay.addWidget(_etq(f"●  {texto}", f"color: {'#FFFFFF' if resaltado else '#E6E8EE'}; font-size: 11px; "
                                          f"font-weight: {700 if resaltado else 400}; padding: 8px 12px; "
                                          f"background: {'#1B2E55' if resaltado else 'transparent'};"))
    return f


def _escena_seleccionar():
    cont = QWidget()
    lay = QHBoxLayout(cont)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(14)
    archivo, al = _caja("escArchivo", "background: white; border: 1px solid #D5DCE8; border-radius: 12px;", 'h', (14, 12, 16, 12), 10)
    al.addWidget(_etq("X", "color: white; background: #1D6F42; border-radius: 5px; font-size: 13px; font-weight: 800;"
                           "padding: 6px 9px;"))
    al.addWidget(_etq("Detalle.xlsx", "color: #1b2430; font-size: 12px; font-weight: 700;"))
    al.addWidget(_etq("Interno", "color: #065F46; background: #D1FAE5; border-radius: 6px; padding: 2px 7px; font-size: 10px;"))
    lay.addWidget(archivo)
    flecha = QLabel()
    flecha.setPixmap(ThemeManager.icon_pixmap('fa5s.arrow-right', color=estilo_com.PRIMARIO, size=22))
    lay.addWidget(flecha)
    lay.addWidget(_etq("Seleccionar archivo", f"color: white; background: {estilo_com.PRIMARIO}; border-radius: 8px; "
                                              "padding: 9px 14px; font-size: 11px; font-weight: 700;"))
    return cont


_FACTOR_ESCENA = 1.35


def _ampliar(widget, factor, padre):
    """Dibuja la ilustración a mayor escala (vectorial, sin pixelar) para llenar el panel."""
    widget.setParent(padre)
    widget.hide()
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    widget.ensurePolished()
    widget.adjustSize()
    ancho, alto = widget.width(), widget.height()
    destino = QPixmap(int(ancho * factor * 2), int(alto * factor * 2))
    destino.setDevicePixelRatio(2)
    destino.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(destino)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.scale(factor, factor)
    widget.render(pintor)
    pintor.end()
    etiqueta = QLabel()
    etiqueta.setPixmap(destino)
    etiqueta.setStyleSheet("background: transparent; border: none;")
    widget.deleteLater()
    return etiqueta


# (nombre corto, ícono, título, texto, escena)
PASOS = (
    ("Abrir Power BI", 'fa5s.external-link-alt', "Abre el reporte de Notas de Venta",
     "Entra al reporte en Power BI. Con el botón de abajo se abre en tu navegador; vuelve a esta guía cuando tengas la lista.",
     _escena_abrir),
    ("Filtrar la lista", 'fa5s.filter', "Deja la lista que necesitas",
     "Hoy se filtra por Fecha Facturación (año y mes). Puede cambiar en el futuro: lo importante es que la tabla muestre "
     "las unidades que quieres traer.", _escena_filtros),
    ("Opciones de la tabla", 'fa5s.hand-pointer', "Selecciona una fila y abre las opciones",
     "Haz clic en una fila de la tabla. Arriba a la derecha aparecen unos botones: presiona los tres puntitos.", _escena_tabla),
    ("Exportar datos", 'fa5s.download', "Elige Exportar datos y descarga",
     "En el menú elige Exportar datos. Deja marcada la opción que viene por defecto (datos con el diseño actual) y presiona "
     "Exportar. Se descarga Detalle.xlsx.", _escena_exportar),
    ("Habilitar edición", 'fa5s.lock-open', "Abre el Excel y habilita la edición",
     "Abre el archivo descargado. Arriba aparece una franja amarilla: presiona Habilitar edición (Enable Editing).",
     _escena_habilitar),
    ("Sensibilidad", 'fa5s.shield-alt', "Cambia la sensibilidad a Interno",
     "Arriba, junto al nombre del archivo, abre Sensibilidad y cambia Confidencial por Interno (Internal). Sin esto la app "
     "no puede leer el archivo.", _escena_sensibilidad),
    ("Seleccionar archivo", 'fa5s.folder-open', "Guarda, cierra y elige el archivo",
     "Guarda el Excel y ciérralo. Luego presiona Seleccionar archivo y elige el Detalle que acabas de guardar.",
     _escena_seleccionar),
)


class _FilaPaso(QFrame):
    clicked = pyqtSignal()

    def __init__(self, nombre, icono):
        super().__init__()
        self._icono = icono
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)
        self._circulo = QLabel()
        self._circulo.setFixedSize(30, 30)
        self._circulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._circulo)
        self._texto = QLabel(nombre)
        lay.addWidget(self._texto, 1)
        self.establecer_estado('pendiente')

    def establecer_estado(self, estado):
        paleta = {
            'pendiente': (estilo_com.SUPERFICIE, estilo_com.APAGADO, estilo_com.LINEA, estilo_com.APAGADO, 'transparent', 600),
            'hecho': ("#D1FAE5", "#065F46", "#D1FAE5", estilo_com.APAGADO, 'transparent', 600),
            'actual': (_AZUL_OSCURO, "white", _AZUL_OSCURO, estilo_com.TINTA, estilo_com.PRIMARIO_SUAVE, 700),
        }[estado]
        fondo, icono, borde, texto, fondo_fila, peso = paleta
        self._circulo.setStyleSheet(f"background: {fondo}; border: 1px solid {borde}; border-radius: 15px;")
        nombre_icono = 'fa5s.check' if estado == 'hecho' else self._icono
        self._circulo.setPixmap(ThemeManager.icon_pixmap(nombre_icono, color=icono, size=14))
        self._texto.setStyleSheet(f"background: transparent; color: {texto}; font-size: 12px; font-weight: {peso};")
        self.setStyleSheet(f"_FilaPaso {{ background: {fondo_fila}; border-radius: 10px; }}")

    def mousePressEvent(self, evento):
        self.clicked.emit()


class _Deslizante(QWidget):
    """Muestra una página y, al cambiarla, la desliza hacia un lado mientras entra la nueva."""
    DURACION_MS = 280

    def __init__(self, parent=None):
        super().__init__(parent)
        self._actual = None
        self._saliente = None
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.DURACION_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._mover)
        self._anim.finished.connect(self._terminar)
        self._direccion = 1

    def cambiar(self, pagina, direccion):
        self._terminar()
        pagina.setParent(self)
        if self._actual is None or not self.isVisible():
            if self._actual is not None:
                self._descartar(self._actual)
            self._actual = pagina
            pagina.setGeometry(self.rect())
            pagina.show()
            return
        self._saliente, self._actual = self._actual, pagina
        self._direccion = direccion
        pagina.setGeometry(self.rect().translated(0, direccion * self.height()))
        pagina.show()
        self._anim.start()

    @staticmethod
    def _descartar(pagina):
        pagina.hide()
        pagina.setParent(None)
        pagina.deleteLater()

    def _mover(self, t):
        alto = self.height()
        self._actual.move(0, int(self._direccion * alto * (1 - t)))
        if self._saliente is not None:
            self._saliente.move(0, int(-self._direccion * alto * t))

    def _terminar(self):
        if self._anim.state() == QVariantAnimation.State.Running:
            self._anim.stop()
        if self._saliente is not None:
            self._descartar(self._saliente)
            self._saliente = None
        if self._actual is not None:
            self._actual.setGeometry(self.rect())

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        if self._actual is not None and self._anim.state() != QVariantAnimation.State.Running:
            self._actual.setGeometry(self.rect())


class PanelGuiaImportarPowerBI(QFrame):
    seleccionar_clicked = pyqtSignal()
    cancelado = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelGuiaBi")
        self.setStyleSheet(
            f"QFrame#panelGuiaBi {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 16px; }}")
        self._paso = 0
        raiz = QHBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        riel, rl = _caja("rielGuiaBi", f"background: {estilo_com.SUPERFICIE_2}; border-top-left-radius: 16px; "
                                       f"border-bottom-left-radius: 16px; border-right: 1px solid {estilo_com.LINEA};",
                         'v', (12, 16, 12, 16), 2)
        riel.setFixedWidth(230)
        rl.addWidget(_etq("IMPORTAR DESDE POWER BI", f"color: {estilo_com.APAGADO}; font-size: 10px; font-weight: 700; "
                                                      "letter-spacing: 1px; padding: 0 8px 8px 8px;"))
        self._filas = []
        for i, (nombre, icono, *_resto) in enumerate(PASOS):
            fila = _FilaPaso(nombre, icono)
            fila.clicked.connect(lambda i=i: self._ir_a(i))
            rl.addWidget(fila)
            self._filas.append(fila)
        rl.addStretch(1)
        self._btn_abrir = _boton(" Abrir Power BI", _ESTILO_BOTON_PRIM, 'fa5s.external-link-alt')
        self._btn_abrir.setToolTip("Abre el reporte de Notas de Venta en el navegador")
        self._btn_abrir.clicked.connect(self._abrir_power_bi)
        if not (REPORTE_NOTAS_VENTAS_URL or "").strip():
            self._btn_abrir.setEnabled(False)
            self._btn_abrir.setToolTip("Falta el enlace del reporte: agrégalo en Configuración > Enlaces.")
        rl.addWidget(self._btn_abrir)
        self._btn_archivo = _boton(" Seleccionar archivo", _ESTILO_BOTON_PRIM, 'fa5s.folder-open')
        self._btn_archivo.setToolTip("Elige el Excel que descargaste de Power BI")
        self._btn_archivo.clicked.connect(self.seleccionar_clicked)
        rl.addWidget(self._btn_archivo)
        raiz.addWidget(riel)

        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(24, 20, 24, 16)
        cuerpo.setSpacing(10)
        self._zona = _Deslizante()
        cuerpo.addWidget(self._zona, 1)

        pie = QHBoxLayout()
        pie.setSpacing(8)
        self._btn_atras = _boton("", _ESTILO_BOTON_TEXTO)
        self._btn_atras.clicked.connect(self._atras)
        pie.addWidget(self._btn_atras)
        pie.addStretch(1)
        self._puntos = []
        for _ in PASOS:
            p = QFrame()
            p.setFixedHeight(7)
            pie.addWidget(p)
            self._puntos.append(p)
        pie.addStretch(1)
        self._btn_sig = _boton("", _ESTILO_BOTON_PRIM)
        self._btn_sig.clicked.connect(self._siguiente)
        pie.addWidget(self._btn_sig)
        cuerpo.addLayout(pie)
        raiz.addLayout(cuerpo, 1)
        self._pintar(0)

    def reiniciar(self):
        self._paso = 0
        self._pintar(0)

    def _ir_a(self, i):
        if i == self._paso:
            return
        direccion = 1 if i > self._paso else -1
        self._paso = i
        self._pintar(direccion)

    def _atras(self):
        if self._paso == 0:
            self.cancelado.emit()
        else:
            self._ir_a(self._paso - 1)

    def _siguiente(self):
        if self._paso == len(PASOS) - 1:
            self.seleccionar_clicked.emit()
        else:
            self._ir_a(self._paso + 1)

    def _abrir_power_bi(self):
        if REPORTE_NOTAS_VENTAS_URL:
            QDesktopServices.openUrl(QUrl(REPORTE_NOTAS_VENTAS_URL))
        else:
            self._btn_abrir.setEnabled(False)
            self._btn_abrir.setToolTip("No hay URL del reporte configurada (Configuración).")

    def _crear_pagina(self):
        nombre, icono, titulo, texto, escena = PASOS[self._paso]
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        banner, bl = _caja("bannerGuiaBi",
                           f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_AZUL_OSCURO}, stop:1 #2C4A80); border-radius: 14px;",
                           'v', (22, 16, 22, 18), 6)
        bl.addWidget(_etq(f"PASO {self._paso + 1} DE {len(PASOS)}",
                          "color: #CFE0FF; background: rgba(255,255,255,0.14); border-radius: 9px; padding: 2px 10px; "
                          "font-size: 10px; font-weight: 800; letter-spacing: 1px;"), alignment=Qt.AlignmentFlag.AlignLeft)
        bl.addWidget(_etq(titulo, "color: white; font-size: 24px; font-weight: 800;", True))
        bl.addWidget(_etq(texto, "color: #C9D6EE; font-size: 13px;", True))
        lay.addWidget(banner)

        if self._paso == 0 and not (REPORTE_NOTAS_VENTAS_URL or "").strip():
            lay.addWidget(aviso_enlace.crear_aviso_enlace(
                "Falta el enlace del reporte de Notas de Venta",
                "Sin el enlace no se puede abrir Power BI desde aquí. Agrégalo en Configuración, sección Enlaces. "
                "Si ya tienes el Excel descargado, puedes seguir con Seleccionar archivo.",
                aviso_enlace.abrir_configuracion_enlaces))

        marco, ml = _caja("escenaGuiaBi", f"background: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; border-radius: 14px;",
                          'v', (20, 18, 20, 18))
        ml.setAlignment(Qt.AlignmentFlag.AlignCenter)
        marco.setSizePolicy(marco.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Maximum)
        ml.addWidget(_ampliar(escena(), _FACTOR_ESCENA, marco), alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(marco)
        lay.addStretch(1)
        return pagina

    def _pintar(self, direccion):
        self._zona.cambiar(self._crear_pagina(), direccion)
        for i, fila in enumerate(self._filas):
            fila.establecer_estado('hecho' if i < self._paso else 'actual' if i == self._paso else 'pendiente')
        for i, p in enumerate(self._puntos):
            actual = i == self._paso
            p.setFixedWidth(20 if actual else 7)
            p.setStyleSheet(f"background: {_AZUL_OSCURO if actual else estilo_com.LINEA}; border-radius: 3px;")
        self._btn_atras.setText(" Cancelar" if self._paso == 0 else " Atrás")
        self._btn_atras.setIcon(ThemeManager.icon('fa5s.arrow-left', color=estilo_com.APAGADO))
        if self._paso == len(PASOS) - 1:
            self._btn_sig.setText(" Seleccionar archivo")
            self._btn_sig.setIcon(ThemeManager.icon('fa5s.folder-open', color='white'))
            self._btn_sig.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        else:
            self._btn_sig.setText("Siguiente ")
            self._btn_sig.setIcon(ThemeManager.icon('fa5s.arrow-right', color='white'))
            self._btn_sig.setLayoutDirection(Qt.LayoutDirection.RightToLeft)


class PanelConfirmarImportacion(QFrame):
    confirmado = pyqtSignal()
    cancelado = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelConfirmarBi")
        self.setStyleSheet("QFrame#panelConfirmarBi { background: transparent; border: none; }")
        externo = QVBoxLayout(self)
        externo.addStretch(1)
        self._tarjeta, lay = _caja(
            "tarjetaConfirmarBi", f"background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 18px;",
            'v', (24, 24, 24, 24), 16)
        self._tarjeta.setFixedWidth(580)
        externo.addWidget(self._tarjeta, alignment=Qt.AlignmentFlag.AlignHCenter)
        externo.addStretch(2)

        cab = QHBoxLayout()
        cab.setSpacing(14)
        icono = QLabel()
        icono.setFixedSize(48, 48)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setStyleSheet(f"background: {estilo_com.PRIMARIO_SUAVE}; border-radius: 14px;")
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.cloud-upload-alt', color=estilo_com.PRIMARIO, size=24))
        cab.addWidget(icono)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(_etq("Confirmar importación", f"color: {estilo_com.TINTA}; font-size: 20px; font-weight: 800;"))
        textos.addWidget(_etq("Revisa el resumen antes de agregar las unidades a Comercial.",
                              f"color: {estilo_com.APAGADO}; font-size: 13px;", True))
        cab.addLayout(textos, 1)
        lay.addLayout(cab)

        self._cifras = QHBoxLayout()
        self._cifras.setSpacing(10)
        lay.addLayout(self._cifras)
        self._aviso, al = _caja("avisoConfirmarBi", "background: #FEF3C7; border-radius: 12px;", 'h', (12, 10, 12, 10), 10)
        ic = QLabel()
        ic.setPixmap(ThemeManager.icon_pixmap('fa5s.info-circle', color="#92400E", size=16))
        al.addWidget(ic, alignment=Qt.AlignmentFlag.AlignTop)
        al.addWidget(_etq("Las unidades que ya traen Volvo Connect aparecen primero en Nuevas oportunidades "
                          "para gestionarlas lo antes posible.", "color: #92400E; font-size: 12px;", True), 1)
        lay.addWidget(self._aviso)
        self._detalle = _etq("", f"color: {estilo_com.APAGADO}; font-size: 12px;", True)
        lay.addWidget(self._detalle)

        pie = QHBoxLayout()
        pie.addStretch(1)
        btn_cancelar = _boton("Cancelar", _ESTILO_BOTON_TEXTO)
        btn_cancelar.clicked.connect(self.cancelado)
        pie.addWidget(btn_cancelar)
        self._btn_ok = _boton("", _ESTILO_BOTON_PRIM, 'fa5s.check')
        self._btn_ok.clicked.connect(self.confirmado)
        pie.addWidget(self._btn_ok)
        lay.addLayout(pie)

    def _cifra(self, valor, texto, fondo, color_valor, color_texto):
        f, lay = _caja(f"cifraBi{abs(hash(texto))}", f"background: {fondo}; border: 1px solid {estilo_com.LINEA if fondo == estilo_com.SUPERFICIE_2 else fondo}; "
                                                    "border-radius: 12px;", 'v', (14, 12, 14, 12), 4)
        lay.addWidget(_etq(str(valor), f"color: {color_valor}; font-size: 26px; font-weight: 800;"))
        lay.addWidget(_etq(texto, f"color: {color_texto}; font-size: 11px;", True))
        f.setMinimumHeight(96)
        return f

    def mostrar(self, nuevas, con_volvo_connect, omitidas, detalle=""):
        while self._cifras.count():
            item = self._cifras.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
        self._cifras.addWidget(self._cifra(nuevas, "unidades nuevas a Nuevas oportunidades", estilo_com.SUPERFICIE_2,
                                           estilo_com.TINTA, estilo_com.APAGADO), 1)
        if con_volvo_connect:
            self._cifras.addWidget(self._cifra(con_volvo_connect, "ya traen Volvo Connect y quedan resaltadas", "#FEF3C7",
                                               "#92400E", "#92400E"), 1)
        if omitidas:
            self._cifras.addWidget(self._cifra(omitidas, "no se importan (ya existían, repetidas o sin VIN)", estilo_com.SUPERFICIE_2,
                                               estilo_com.APAGADO, estilo_com.APAGADO), 1)
        self._aviso.setVisible(bool(con_volvo_connect))
        self._detalle.setText(detalle)
        self._detalle.setVisible(bool(detalle))
        self._btn_ok.setText(f" Importar {nuevas} unidad{'es' if nuevas != 1 else ''}")
