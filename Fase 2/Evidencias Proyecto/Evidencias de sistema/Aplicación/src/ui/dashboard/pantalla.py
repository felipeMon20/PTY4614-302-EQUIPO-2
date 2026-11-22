"""Dashboard de Volvo Connect: filtros, cálculo del panorama y tarjetas del tablero Resumen."""
from datetime import date
import qtawesome as qta
from PyQt6.QtCore import QSize, QTimer, QVariantAnimation, Qt, QPropertyAnimation, QEasingCurve, QPoint, QRect, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QButtonGroup, QCheckBox, QFrame, QLineEdit, QGraphicsDropShadowEffect, QHBoxLayout, QListWidget, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget
from src.core.data_manager import DataManager
from src.ui.compartido.comercial_estilo import ComboTarjeta
from src.ui.compartido.esqueleto_carga import EsqueletoCarga
from src.services import dashboard_services as servicio
from src.services import metas_service
from src.ui.dashboard.base import (  # noqa: F401 (se reexportan: otros módulos los importan desde aquí)
    FONDO,
    TINTA,
    APAGADO,
    LINEA,
    MARINO,
    AZUL,
    AZUL_SUAVE,
    TONO_MEDIO,
    TONO_SUAVE,
    TONO_CLARO,
    ROJO,
    ROJO_TEXTO,
    ROJO_SUAVE,
    COLORES_ESTADO,
    _RELLENO_OSCURO,
    _BOTON_OSCURO,
    _relleno,
    _con_tema,
    _fondo_boton,
    _estilo_principal,
    _estilo_marca,
    _Punto,
    _num,
    _pct,
    _etiqueta,
    _icono_en_circulo,
    _leyenda,
    _TarjetaAcento,
    BarraProporcion,
)
from src.ui.dashboard.graficos import (  # noqa: F401 (se reexportan: otros módulos los importan desde aquí)
    _GraficoBase,
    GraficoMesAMes,
    _DetalleMes,
    GraficoMetas,
    BarrasServicio,
    BarrasEjecutivo,
    _LineaCarga,
    _FilasConTooltip,
    BarrasFuga,
    BarrasClientes,
)
from src.ui.dashboard.selector import SelectorDeslizante
from src.ui.dashboard.controles import (  # noqa: F401 (se reexportan: otros módulos los importan desde aquí)
    SelectorMultiple,
    SelectorPeriodo,
    _CalculoPanorama,
    _IgnorarRueda,
)


class PanelMetas(QFrame):
    """Tarjeta flotante para fijar la meta mensual de unidades vendidas. Guarda en
    MetasVC.csv (carpeta de datos compartida)."""
    cambio = pyqtSignal()
    cerrar = pyqtSignal()
    ANCHO = 300

    _ESTILO_SPIN = ("QSpinBox { background: white; color: #0F1B33; border: 1px solid #D9DEE8; border-radius: 9px; "
                    "padding: 6px 8px; font-size: 13px; font-weight: 600; } QSpinBox:focus { border-color: #1B2B4E; }")
    _ESTILO_BOTON = ("QPushButton { background: #F7F9FC; color: #1B2B4E; border: 1px solid #D9DEE8; border-radius: 10px; "
                     "padding: 9px 12px; font-size: 12px; font-weight: 700; } QPushButton:hover { background: #EEF2F8; }")
    def __init__(self, parent, incrustado=False):
        super().__init__(parent)
        self.setObjectName("panelMetas")
        self._metas = {}
        self._metas_civ = {}
        self._sin_rueda = _IgnorarRueda(self)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        if incrustado:
            # Dentro de la caja de filtros: sin marco, sombra ni título (el botón Metas hace de encabezado)
            self.setStyleSheet("QFrame#panelMetas { background: transparent; border: none; }")
            lay.setContentsMargins(10, 8, 10, 10)
            lay.setSpacing(6)
        else:
            self.setStyleSheet("QFrame#panelMetas { background: white; border: 1px solid #E3E8F0; border-radius: 16px; }")
            sombra = QGraphicsDropShadowEffect(self)
            sombra.setBlurRadius(30)
            sombra.setOffset(0, 8)
            sombra.setColor(QColor(27, 43, 78, 60))
            self.setGraphicsEffect(sombra)
            lay.setContentsMargins(18, 14, 18, 16)
            fila_titulo = QHBoxLayout()
            fila_titulo.addWidget(_etiqueta("Meta del mes", f"color: {TINTA}; font-size: 15px; font-weight: 800;"), 1)
            boton_cerrar = QPushButton()
            boton_cerrar.setIcon(qta.icon('fa5s.times', color=_relleno(MARINO).name()))
            boton_cerrar.setFixedSize(30, 30)
            boton_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
            boton_cerrar.setToolTip("Cerrar")
            boton_cerrar.setStyleSheet(self._ESTILO_BOTON.replace("padding: 9px 12px;", "padding: 0;"))
            boton_cerrar.clicked.connect(self.cerrar.emit)
            fila_titulo.addWidget(boton_cerrar)
            lay.addLayout(fila_titulo)
            subtitulo = _etiqueta("Unidades vendidas que se propone el equipo. Los meses pasados no se pueden cambiar.",
                                  f"color: {APAGADO}; font-size: 11px;")
            subtitulo.setWordWrap(True)
            lay.addWidget(subtitulo)

        hoy = date.today()
        estilo_campo = f"color: {APAGADO}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
        fila_periodo = QHBoxLayout()
        fila_periodo.setSpacing(8)
        caja_anio = QVBoxLayout()
        caja_anio.setSpacing(3)
        caja_anio.addWidget(_etiqueta("AÑO", estilo_campo))
        self.cmb_anio = ComboTarjeta("Año")
        self.cmb_anio.setStyleSheet(DashboardModule._ESTILO_COMBO.replace("min-width: 150px;", "min-width: 60px;"))
        for anio in (hoy.year, hoy.year + 1):
            self.cmb_anio.addItem(str(anio), anio)
        caja_anio.addWidget(self.cmb_anio)
        caja_mes = QVBoxLayout()
        caja_mes.setSpacing(3)
        caja_mes.addWidget(_etiqueta("MES", estilo_campo))
        self.cmb_mes = ComboTarjeta("Mes")
        self.cmb_mes.setStyleSheet(DashboardModule._ESTILO_COMBO.replace("min-width: 150px;", "min-width: 90px;"))
        for i, nombre in enumerate(servicio.MESES, start=1):
            self.cmb_mes.addItem(nombre, i)
        self.cmb_mes.setCurrentIndex(hoy.month - 1)
        caja_mes.addWidget(self.cmb_mes)
        if incrustado:
            for combo in (self.cmb_anio, self.cmb_mes):
                combo.setStyleSheet(combo.styleSheet().replace("padding: 7px 12px;", "padding: 7px 8px;"))
            self.cmb_anio.setFixedWidth(68)
            self.cmb_mes.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        fila_periodo.addLayout(caja_anio)
        fila_periodo.addLayout(caja_mes, 1)
        lay.addLayout(fila_periodo)

        lay.addWidget(_etiqueta("META DE UNIDADES" if incrustado else "META DE UNIDADES VENDIDAS", estilo_campo))
        self.spin_meta = self._spin()
        lay.addWidget(self.spin_meta)
        lay.addWidget(_etiqueta("META CON CIV", estilo_campo))
        self.spin_meta_civ = self._spin()
        lay.addWidget(self.spin_meta_civ)
        for campo in (self.cmb_anio, self.cmb_mes, self.spin_meta, self.spin_meta_civ):
            campo.installEventFilter(self._sin_rueda)
        self.cmb_anio.currentIndexChanged.connect(self._refrescar)
        self.cmb_mes.currentIndexChanged.connect(self._refrescar)

        self.lbl_estado = _etiqueta("", f"color: {ROJO_TEXTO}; font-size: 11px;")
        self.lbl_estado.setWordWrap(True)
        if incrustado:
            self.lbl_estado.setMinimumHeight(30)
            self.spin_meta.setMinimumHeight(34)
            self.spin_meta_civ.setMinimumHeight(34)
            self.lbl_estado.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self.lbl_estado)
        guardar = QPushButton("Guardar metas")
        guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        guardar.setStyleSheet(_estilo_principal(10, '10px 12px', 13))
        guardar.clicked.connect(self._guardar)
        self.btn_guardar = guardar
        _con_tema(self)
        lay.addWidget(guardar)

    def refrescar_tema(self):
        self.btn_guardar.setStyleSheet(_estilo_principal(10, '10px 12px', 13))

    def alto_para(self, ancho):
        alto = self.layout().totalHeightForWidth(ancho)
        return alto if alto > 0 else self.layout().sizeHint().height()

    def _spin(self):
        spin = QSpinBox()
        spin.setRange(0, 100000)
        spin.setMinimumHeight(38)
        spin.setStyleSheet(self._ESTILO_SPIN)
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        return spin

    def abrir(self, metas, metas_civ=None):
        self._metas = metas
        self._metas_civ = metas_civ or {}
        self._refrescar()

    def _periodo(self):
        return self.cmb_anio.currentData(), self.cmb_mes.currentData()

    def _es_pasado(self):
        anio, mes = self._periodo()
        hoy = date.today()
        return (anio, mes) < (hoy.year, hoy.month)

    def _refrescar(self, *_):
        pasado = self._es_pasado()
        self.spin_meta.setValue(self._metas.get(self._periodo(), 0))
        self.spin_meta_civ.setValue(self._metas_civ.get(self._periodo(), 0))
        self.spin_meta.setEnabled(not pasado)
        self.spin_meta_civ.setEnabled(not pasado)
        self.btn_guardar.setEnabled(not pasado)
        self._mostrar_estado("Los meses pasados no se pueden modificar." if pasado else "", False)

    def _mostrar_estado(self, texto, ok):
        self.lbl_estado.setStyleSheet(f"color: {MARINO if ok else ROJO_TEXTO}; font-size: 11px; background: transparent; border: none;")
        self.lbl_estado.setText(texto)

    def _guardar(self):
        anio, mes = self._periodo()
        ok, mensaje = metas_service.guardar_metas(anio, {mes: self.spin_meta.value()}, {mes: self.spin_meta_civ.value()})
        self._mostrar_estado("Metas guardadas." if ok else mensaje, ok)
        if ok:
            self.cambio.emit()


class DashboardModule(QWidget):
    _sin_animacion_busqueda = True  # sus propios gráficos y listas ya animan al buscar
    ANCHO_MAXIMO = 1260
    CON_TITULO = False  # el encabezado del grupo (pestañas del Dashboard) ya muestra el título
    _ESTILO_COMBO = (
        "QComboBox { background: white; color: #0F1B33; border: 1px solid #D9DEE8; border-radius: 9px; "
        "padding: 7px 12px; font-size: 12px; font-weight: 700; min-width: 150px; }"
        "QComboBox:hover { border-color: #B9C6DA; }"
        "QComboBox::drop-down { border: none; width: 22px; }"
        "QComboBox QAbstractItemView { background: white; color: #0F1B33; selection-background-color: #E3E8F1; "
        "selection-color: #0F1B33; border: 1px solid #D9DEE8; }")

    # La flota de la barra de búsqueda es una sola para todas las pestañas del Dashboard
    _flota_compartida = ""

    @property
    def _flota(self):
        return DashboardModule._flota_compartida

    @_flota.setter
    def _flota(self, valor):
        DashboardModule._flota_compartida = valor

    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.data_manager.data_ready.connect(self._on_data_ready)
        self._data_dirty = True
        self._panorama = None
        self._panorama_vista = None
        self._metas = {}
        self._metas_civ = {}
        self._registro = {}
        self._panel_abierto = False
        self.search_input = QLineEdit(self)
        self.search_input.hide()
        self._ultimo_texto = ""
        self._unidades_actuales = None
        self._segmento_fuga = "INDUSTRIA"
        self._solo_parciales = False
        self._botones_segmento = []
        self._flotas = []
        self._orden_filtros = []
        _con_tema(self)
        self._calculo = None
        self._recarga_pendiente = False
        self._firma_metas = None
        self._vigia_metas = QTimer(self)
        self._vigia_metas.setInterval(20000)
        self._vigia_metas.timeout.connect(self._vigilar_metas)
        self._vigia_metas.start()
        self._fin_carga = QTimer(self)
        self._fin_carga.setSingleShot(True)
        self._fin_carga.timeout.connect(lambda: self._esqueleto.terminar())
        self._sugerencias = QListWidget(self)
        self._sugerencias.hide()
        self._sugerencias.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sugerencias.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._sugerencias.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._anim_lista = QVariantAnimation(self)
        self._anim_lista.setDuration(180)
        self._anim_lista.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_lista.valueChanged.connect(self._alto_lista)
        self._carga_barra = _LineaCarga(self)
        self._barra_conectada = False
        self._sugerencias.setStyleSheet(
            "QListWidget { background: white; color: #0F1B33; border: 1px solid #E5E7EB; border-radius: 16px; "
            "padding: 8px; font-size: 13px; font-weight: 500; outline: none; } "
            "QListWidget::item { padding: 7px 12px; border-radius: 10px; } "
            "QListWidget::item:hover { background: #E6EFFD; color: #1F6FEB; }")
        sombra = QGraphicsDropShadowEffect(self._sugerencias)
        sombra.setBlurRadius(26)
        sombra.setOffset(0, 6)
        sombra.setColor(QColor(0, 0, 0, 45))
        self._sugerencias.setGraphicsEffect(sombra)
        self._sugerencias.itemClicked.connect(self._elegir_sugerencia)
        self._setup_ui()

    # ------------------------------------------------------------------ interfaz
    def refrescar_tema(self):
        self.btn_quitar.setIcon(qta.icon('fa5s.times', color=_relleno(MARINO).name()))
        self.chk_pruebas.setStyleSheet(_estilo_marca())
        self.chk_no_aplica.setStyleSheet(_estilo_marca())
        for boton in self._botones_segmento:
            boton.setStyleSheet(self._estilo_segmento())
        self.btn_metas.setStyleSheet(_estilo_principal(9, '9px 16px', 12))
        for marca in self.chk_servicio.values():
            marca.setStyleSheet(_estilo_marca())

    def _setup_ui(self):
        self.setStyleSheet(f"DashboardModule {{ background: {FONDO}; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        externo = QVBoxLayout(self)
        externo.setContentsMargins(0, 0, 0, 0)
        externo.setSpacing(0)
        cabecera = QWidget()
        self._cabecera = cabecera
        cabecera.setObjectName("cabeceraDash")
        cabecera.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        cabecera.setStyleSheet(f"QWidget#cabeceraDash {{ background: {FONDO}; }}")
        fija = QHBoxLayout(cabecera)
        fija.setContentsMargins(24, 14, 24, 10)
        columna_fija = QWidget()
        columna_fija.setStyleSheet("background: transparent;")
        columna_fija.setMaximumWidth(self.ANCHO_MAXIMO)
        fija.addStretch(1)
        fija.addWidget(columna_fija, 100)
        fija.addStretch(1)
        lay_fija = QVBoxLayout(columna_fija)
        lay_fija.setContentsMargins(0, 0, 0, 0)
        lay_fija.setSpacing(10)
        if self.CON_TITULO:
            lay_fija.addLayout(self._crear_titulo())
        lay_fija.addWidget(self._crear_filtros())
        externo.addWidget(cabecera)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        externo.addWidget(scroll, 1)
        contenido = QWidget()
        contenido.setStyleSheet("background: transparent;")
        scroll.setWidget(contenido)
        scroll.verticalScrollBar().valueChanged.connect(lambda _: self._sugerencias.hide())
        centrado = QHBoxLayout(contenido)
        centrado.setContentsMargins(24, 4, 24, 14)
        columna = QWidget()
        columna.setMaximumWidth(self.ANCHO_MAXIMO)
        centrado.addStretch(1)
        centrado.addWidget(columna, 100)
        centrado.addStretch(1)
        lay = QVBoxLayout(columna)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        lay.addLayout(self._crear_kpis())
        lay.addWidget(self._crear_seccion_mes_a_mes())
        lay.addWidget(self._crear_seccion_metas())
        lay.addLayout(self._crear_fila_servicio_ejecutivo(), 1)
        lay.addLayout(self._crear_fila_fuga_clientes())
        self._esqueleto = EsqueletoCarga(columna, 'dashboard', QColor(FONDO))

        self.panel_metas = PanelMetas(self)
        self.panel_metas.cambio.connect(self._on_metas_cambiaron)
        self.panel_metas.cerrar.connect(lambda: self._mostrar_panel(False))
        self.panel_metas.hide()
        self._anim_panel = QPropertyAnimation(self.panel_metas, b"geometry", self)
        self._anim_panel.setDuration(220)
        self._anim_panel.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_panel.finished.connect(self._al_terminar_animacion)

    @staticmethod
    def _tarjeta(titulo, subtitulo):
        """Tarjeta blanca con título y subtítulo; devuelve (tarjeta, layout)."""
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaDash")
        tarjeta.setStyleSheet(f"QFrame#tarjetaDash {{ background: white; border: 1px solid {LINEA}; border-radius: 16px; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)
        cabecera = QVBoxLayout()
        cabecera.setSpacing(2)
        cabecera.addWidget(_etiqueta(titulo, f"color: {TINTA}; font-size: 13px; font-weight: 700;"))
        sub = _etiqueta(subtitulo, f"color: {APAGADO}; font-size: 11px;")
        sub.setWordWrap(True)
        cabecera.addWidget(sub)
        lay.addLayout(cabecera)
        return tarjeta, lay

    def _crear_titulo(self):
        caja = QVBoxLayout()
        caja.setSpacing(3)
        fila = QHBoxLayout()
        fila.setSpacing(10)
        fila.addWidget(_etiqueta("VOLVO CONNECT", f"color: {MARINO}; font-size: 18px; font-weight: 800; letter-spacing: 1px;"))
        separador = QFrame()
        separador.setFixedSize(1, 22)
        separador.setStyleSheet("background: #C5CEDD; border: none;")
        fila.addWidget(separador)
        fila.addWidget(_etiqueta("Gestión del Negocio", f"color: {TINTA}; font-size: 18px; font-weight: 700;"))
        fila.addStretch()
        caja.addLayout(fila)
        caja.addWidget(_etiqueta(
            "Un vistazo a la flota con servicio Volvo Connect, desde el Registro Maestro. "
            "Los filtros afectan todas las tarjetas y gráficos.", f"color: {APAGADO}; font-size: 11px;"))
        return caja

    def _crear_filtros(self):
        marco = QFrame()
        marco.setObjectName("filtrosDash")
        marco.setStyleSheet(f"QFrame#filtrosDash {{ background: white; border: 1px solid {LINEA}; border-radius: 14px; }}")
        fila = QHBoxLayout(marco)
        fila.setContentsMargins(12, 8, 12, 8)
        fila.setSpacing(8)
        self.filtros = {}
        nombres = {"EJECUTIVO": "Ejecutivo", "FORMA": "Contrato", "SERVICIO": "Plan", "PERIODO": "Período"}
        for columna, nombre in nombres.items():
            if columna == "PERIODO":
                separador = QFrame()
                separador.setFixedSize(1, 22)
                separador.setStyleSheet(f"background: {LINEA}; border: none;")
                fila.addSpacing(4)
                fila.addWidget(separador)
                fila.addSpacing(4)
            plural = {"EJECUTIVO": "ejecutivos", "FORMA": "contratos", "SERVICIO": "planes"}.get(columna)
            combo = (SelectorPeriodo(nombre) if columna == "PERIODO"
                     else SelectorMultiple(nombre, plural, abreviar=False) if plural else ComboTarjeta(nombre))
            ancho = {"EJECUTIVO": 160, "FORMA": 110, "SERVICIO": 100, "PERIODO": 150}[columna]
            if not plural and columna != "PERIODO":
                combo.setStyleSheet(self._ESTILO_COMBO.replace("min-width: 150px;", "min-width: 40px;"))
            combo.setFixedWidth(ancho)
            combo.setToolTip(f"Filtrar por {nombre.lower()}" + (" de inicio de contrato" if columna == "PERIODO" else "")
                             + (". Puedes elegir varios." if plural else ""))
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
            combo.currentIndexChanged.connect(lambda _i, k=columna: self._cambio_filtro(k))
            fila.addWidget(combo)
            self.filtros[columna] = combo
            if columna == "SERVICIO":
                self.chk_servicio = {}
                for clave in ("CIV", "SZ"):
                    marca = QCheckBox(clave)
                    marca.setCursor(Qt.CursorShape.PointingHandCursor)
                    marca.setStyleSheet(_estilo_marca())
                    marca.setToolTip(f"Solo unidades con {clave}")
                    marca.stateChanged.connect(lambda _e, k=clave: self._cambio_filtro(k))
                    fila.addWidget(marca)
                    self.chk_servicio[clave.lower()] = marca
        fila.addSpacing(4)
        self.chk_pruebas = QCheckBox("Pruebas")
        self.chk_pruebas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_pruebas.setStyleSheet(_estilo_marca())
        self.chk_pruebas.setToolTip("Incluir los contratos de prueba (Test y Demo). Por defecto quedan fuera de las cifras.")
        self.chk_pruebas.stateChanged.connect(self._cambio_pruebas)
        fila.addWidget(self.chk_pruebas)
        self.chk_no_aplica = QCheckBox("No aplica")
        self.chk_no_aplica.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_no_aplica.setStyleSheet(_estilo_marca())
        self.chk_no_aplica.setToolTip("Incluir los contratos con activación No aplica, que nunca pasaron por Volvo Connect. "
                                      "Por defecto quedan fuera de las cifras.")
        self.chk_no_aplica.stateChanged.connect(self._cambio_pruebas)
        fila.addWidget(self.chk_no_aplica)
        fila.addStretch(1)
        self.btn_quitar = QPushButton()
        self.btn_quitar.setFixedSize(36, 36)
        self.btn_quitar.setIcon(qta.icon('fa5s.times', color=_relleno(MARINO).name()))
        self.btn_quitar.setToolTip("Quitar filtros")
        self.btn_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_quitar.setStyleSheet(
            "QPushButton { background: #F7F9FC; border: 1px solid #D9DEE8; border-radius: 9px; } "
            "QPushButton:hover { background: #EEF2F8; } QPushButton:disabled { background: transparent; border-color: #E3E8F0; }")
        self.btn_quitar.clicked.connect(self._quitar_filtros)
        fila.addWidget(self.btn_quitar)
        self.btn_metas = QPushButton(" Metas")
        self.btn_metas.setIcon(qta.icon('fa5s.bullseye', color='white'))
        self.btn_metas.setToolTip("Configurar las metas de unidades vendidas")
        self.btn_metas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_metas.setStyleSheet(_estilo_principal(9, '9px 16px', 12))
        self.btn_metas.clicked.connect(lambda: self._mostrar_panel(True))
        fila.addWidget(self.btn_metas)
        return marco

    def _crear_kpis(self):
        fila = QHBoxLayout()
        fila.setSpacing(14)
        self._kpi = {}
        for clave, color in (("universo", MARINO), ("conectadas", MARINO), ("complementarios", MARINO), ("no_conectada", ROJO)):
            tarjeta = _TarjetaAcento(color)
            tarjeta.setFixedHeight(172)
            tarjeta.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            lay = QVBoxLayout(tarjeta)
            lay.setContentsMargins(18, 12, 14, 12)
            lay.setSpacing(5)
            self._kpi[clave] = lay
            fila.addWidget(tarjeta, 1)
        self._armar_kpi_universo()
        self._armar_kpi_conectadas()
        self._armar_kpi_complementarios()
        self._armar_kpi_no_conectada()
        return fila

    @staticmethod
    def _cabecera_kpi(lay, titulo, icono, color, fondo):
        fila = QHBoxLayout()
        fila.addWidget(_etiqueta(titulo.upper(), f"color: {APAGADO}; font-size: 11px; font-weight: 700; letter-spacing: 1px;"))
        fila.addStretch()
        fila.addWidget(_icono_en_circulo(icono, color, fondo, tam=28, lado_icono=12, redondo=True))
        lay.addLayout(fila)

    @staticmethod
    def _pie_kpi(lay, izquierda, color):
        fila = QHBoxLayout()
        fila.addWidget(_etiqueta(izquierda, f"color: {APAGADO}; font-size: 11px; font-weight: 600;"))
        fila.addStretch()
        derecha = _etiqueta("—", f"color: {color}; font-size: 11px; font-weight: 700;")
        fila.addWidget(derecha)
        lay.addLayout(fila)
        return derecha

    def _armar_kpi_universo(self):
        lay = self._kpi["universo"]
        self._cabecera_kpi(lay, "Universo comercial", 'fa5s.truck', MARINO, AZUL_SUAVE)
        self.lbl_universo = _etiqueta("—", f"color: {TINTA}; font-size: 28px; font-weight: 800;")
        lay.addWidget(self.lbl_universo)
        self.barra_universo = BarraProporcion()
        lay.addWidget(self.barra_universo)
        lay.addStretch(1)
        self.lbl_universo_pct = self._pie_kpi(lay, "Unidades distintas (VIN)", MARINO)

    def _armar_kpi_conectadas(self):
        lay = self._kpi["conectadas"]
        self._cabecera_kpi(lay, "Con Volvo Connect", 'fa5s.wifi', MARINO, AZUL_SUAVE)
        self.lbl_conectadas = _etiqueta("—", f"color: {TINTA}; font-size: 28px; font-weight: 800;")
        lay.addWidget(self.lbl_conectadas)
        self.barra_conectadas = BarraProporcion()
        lay.addWidget(self.barra_conectadas)
        lay.addStretch(1)
        self.lbl_take_rate = self._pie_kpi(lay, "Take rate", MARINO)

    def _armar_kpi_complementarios(self):
        lay = self._kpi["complementarios"]
        self._cabecera_kpi(lay, "Productos complementarios", 'fa5s.th-large', MARINO, AZUL_SUAVE)
        fila = QHBoxLayout()
        fila.setSpacing(12)
        self.lbl_civ, self.barra_civ, self.lbl_civ_pct = self._columna_producto(fila, "CIV")
        separador = QFrame()
        separador.setFixedWidth(1)
        separador.setStyleSheet(f"background: {LINEA}; border: none;")
        fila.insertWidget(1, separador)
        self.lbl_sz, self.barra_sz, self.lbl_sz_pct = self._columna_producto(fila, "Safety Zone")
        lay.addLayout(fila)
        lay.addStretch(1)

    @staticmethod
    def _columna_producto(fila, nombre):
        col = QVBoxLayout()
        col.setSpacing(5)
        linea = QHBoxLayout()
        linea.setSpacing(6)
        valor = _etiqueta("—", f"color: {TINTA}; font-size: 28px; font-weight: 800;")
        linea.addWidget(valor)
        linea.addStretch()
        col.addLayout(linea)
        barra = BarraProporcion()
        col.addWidget(barra)
        pct = _etiqueta("—", f"color: {APAGADO}; font-size: 11px; font-weight: 600;")
        col.addWidget(pct)
        col.addStretch(1)
        fila.addLayout(col, 1)
        return valor, barra, pct

    def _armar_kpi_no_conectada(self):
        lay = self._kpi["no_conectada"]
        self._cabecera_kpi(lay, "Base no conectada", 'fa5s.ban', ROJO, ROJO_SUAVE)
        self.lbl_no_conectada = _etiqueta("—", f"color: {TINTA}; font-size: 28px; font-weight: 800;")
        lay.addWidget(self.lbl_no_conectada)
        self.barra_no_conectada = BarraProporcion()
        lay.addWidget(self.barra_no_conectada)
        self.caja_desglose = QVBoxLayout()
        self.caja_desglose.setSpacing(1)
        lay.addLayout(self.caja_desglose)
        lay.addStretch(1)

    def _crear_seccion_mes_a_mes(self):
        tarjeta, lay = self._tarjeta(
            "Conectados y desconectados, mes a mes",
            "Arriba el mes más nuevo, abajo el más antiguo. Un mes sale bien si se conectaron más unidades de las que se desconectaron.")
        lay.setContentsMargins(0, 16, 0, 16)
        lay.itemAt(0).layout().setContentsMargins(18, 0, 18, 0)
        self.grafico_mes = GraficoMesAMes()
        lay.addWidget(self.grafico_mes)
        self.lbl_sin_fecha = _etiqueta("", f"color: {APAGADO}; font-size: 11px; margin: 0 18px;")
        self.lbl_sin_fecha.setWordWrap(True)
        lay.addWidget(self.lbl_sin_fecha)
        return tarjeta

    def _crear_seccion_metas(self):
        tarjeta, lay = self._tarjeta(
            "Unidades vendidas por mes y meta",
            "Cada columna son las unidades vendidas en el mes, según su estado hoy: conectadas (abajo), por conectar "
            "y desconectadas o de baja (arriba, en rojo). La marca punteada es la meta de ese mes.")
        barra = QHBoxLayout()
        barra.setSpacing(12)
        barra.addWidget(_leyenda((("Conectadas", MARINO), ("Por conectar", TONO_CLARO), ("Desconectadas", ROJO))))
        self.lbl_meta_nota = _etiqueta("", f"color: {APAGADO}; font-size: 11px;")
        barra.addWidget(self.lbl_meta_nota)
        barra.addStretch(1)
        self._meses_metas = 6
        self.btn_meses_metas = QPushButton()
        self.btn_meses_metas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_meses_metas.setStyleSheet(PanelMetas._ESTILO_BOTON)
        self.btn_meses_metas.clicked.connect(self._alternar_meses_metas)
        barra.addWidget(self.btn_meses_metas)
        lay.addLayout(barra)
        self.grafico_metas = GraficoMetas()
        self.grafico_metas.setMinimumHeight(250)
        self.grafico_metas.detalle_mes = self._detalle_mes
        lay.addWidget(self.grafico_metas)
        return tarjeta

    def _crear_fila_servicio_ejecutivo(self):
        fila = QHBoxLayout()
        fila.setSpacing(14)
        tarjeta_s, lay_s = self._tarjeta("Conexión por tipo de servicio",
                                         "Porcentaje conectado de cada servicio, del que mejor conecta al que peor")
        lay_s.addWidget(_leyenda((("Plan Básico", TONO_CLARO), ("Plan Medio", TONO_MEDIO), ("Plan Full", MARINO))))
        self.grafico_servicio = BarrasServicio()
        lay_s.addWidget(self.grafico_servicio, 1)
        lay_s.addWidget(_etiqueta("CIV y SZ se suman al plan.", f"color: {APAGADO}; font-size: 11px;"))
        tarjeta_e, lay_e = self._tarjeta(
            "Camiones con Volvo Connect por ejecutivo",
            "Camiones que pasaron por Volvo Connect, según el ejecutivo que vendió el camión. Solo ejecutivos activos. "
            "Se muestran hasta 15, de más a menos. Cada fila: conectados / por conectar / desconectados = total.")
        lay_e.addWidget(_leyenda((("Conectados", MARINO), ("Por conectar", TONO_CLARO), ("Desconectados", ROJO))))
        self.grafico_ejecutivo = BarrasEjecutivo()
        lay_e.addWidget(self.grafico_ejecutivo, 1)
        self.lbl_ej_nota = _etiqueta("", f"color: {APAGADO}; font-size: 11px;")
        self.lbl_ej_nota.setWordWrap(True)
        lay_e.addWidget(self.lbl_ej_nota)
        for tarjeta in (tarjeta_s, tarjeta_e):
            tarjeta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        fila.addWidget(tarjeta_s, 1)
        fila.addWidget(tarjeta_e, 1)
        return fila

    @staticmethod
    def _estilo_segmento():
        return ("QPushButton { background: transparent; color: #1B2B4E; border: none; border-radius: 8px; "
                "padding: 6px 12px; font-size: 12px; font-weight: 700; } "
                "QPushButton:checked { background: transparent; color: white; }")

    def _segmentos(self, opciones, al_elegir):
        """Botones de a uno para cambiar de vista, con una pastilla que se desliza; devuelve el widget que los contiene."""
        caja = SelectorDeslizante()
        for i, (clave, texto) in enumerate(opciones):
            boton = QPushButton(texto)
            boton.setCheckable(True)
            boton.setChecked(i == 0)
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(self._estilo_segmento())
            boton.clicked.connect(lambda _c, k=clave: al_elegir(k))
            caja.agregar(boton)
            self._botones_segmento.append(boton)
        return caja

    def _mini_cifra(self):
        caja = QFrame()
        caja.setStyleSheet("QFrame { background: #F7F9FC; border: 1px solid #E3E8F0; border-radius: 12px; }")
        caja.setFixedHeight(80)
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        valor = _etiqueta("—", f"color: {TINTA}; font-size: 18px; font-weight: 800;")
        texto = _etiqueta("", f"color: {APAGADO}; font-size: 10px;")
        texto.setWordWrap(True)
        lay.addWidget(valor)
        lay.addWidget(texto)
        return caja, valor, texto

    def _crear_fila_fuga_clientes(self):
        fila = QHBoxLayout()
        fila.setSpacing(14)
        tarjeta_f, lay_f = self._tarjeta(
            "Dónde se pierden clientes",
            "Porcentaje de unidades desconectadas en cada grupo, del que más pierde al que menos. "
            "La marca vertical es el promedio de todo el universo.")
        lay_f.addWidget(self._segmentos((("INDUSTRIA", "Industria"), ("MODELO", "Modelo"), ("FACTURACION", "Facturación")),
                                        self._elegir_segmento_fuga), 0, Qt.AlignmentFlag.AlignLeft)
        cifras_f = QHBoxLayout()
        cifras_f.setSpacing(8)
        self._cifras_fuga = []
        for _ in range(3):
            caja, valor, texto = self._mini_cifra()
            cifras_f.addWidget(caja, 1)
            self._cifras_fuga.append((valor, texto))
        lay_f.addLayout(cifras_f)
        self.grafico_fuga = BarrasFuga()
        lay_f.addWidget(self.grafico_fuga, 1)
        self.lbl_fuga_nota = _etiqueta("", f"color: {APAGADO}; font-size: 11px;")
        self.lbl_fuga_nota.setWordWrap(True)
        lay_f.addWidget(self.lbl_fuga_nota)
        tarjeta_c, lay_c = self._tarjeta(
            "Clientes a recuperar",
            "Clientes con más unidades desconectadas. Los parciales todavía tienen unidades conectadas: "
            "son los más fáciles de recuperar con una llamada.")
        lay_c.addWidget(self._segmentos((("TODOS", "Más desconectadas"), ("PARCIALES", "Solo parciales")),
                                        self._elegir_vista_clientes), 0, Qt.AlignmentFlag.AlignLeft)
        cifras = QHBoxLayout()
        cifras.setSpacing(8)
        self._cifras_clientes = []
        for _ in range(3):
            caja, valor, texto = self._mini_cifra()
            cifras.addWidget(caja, 1)
            self._cifras_clientes.append((valor, texto))
        lay_c.addLayout(cifras)
        self.grafico_clientes = BarrasClientes()
        lay_c.addWidget(self.grafico_clientes, 1)
        nota_c = _etiqueta("Parcial: el cliente aún tiene unidades conectadas. Todas: ya no le queda ninguna. "
                           "Pasa el mouse por un nombre para verlo completo.", f"color: {APAGADO}; font-size: 11px;")
        nota_c.setWordWrap(True)
        lay_c.addWidget(nota_c)
        for tarjeta in (tarjeta_f, tarjeta_c):
            tarjeta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            tarjeta.layout().itemAt(0).layout().itemAt(1).widget().setMinimumHeight(34)
        fila.addWidget(tarjeta_f, 1)
        fila.addWidget(tarjeta_c, 1)
        return fila

    def _elegir_segmento_fuga(self, clave):
        self._segmento_fuga = clave
        self._pintar_fuga_clientes()

    def _elegir_vista_clientes(self, clave):
        self._solo_parciales = clave == "PARCIALES"
        self._pintar_fuga_clientes()

    def _pintar_fuga_clientes(self):
        unidades = self._unidades_actuales
        if unidades is None:
            self.grafico_fuga.set_datos([])
            self.grafico_clientes.set_datos([])
            self.lbl_fuga_nota.setText("")
            for valor, texto in self._cifras_clientes + self._cifras_fuga:
                valor.setText("—")
                texto.setText("")
            return
        fuga = servicio.fuga_por_segmento(unidades, self._segmento_fuga)
        self.grafico_fuga.set_datos(fuga['filas'], fuga['promedio'])
        self.lbl_fuga_nota.setText("Solo se muestran los grupos con unidades suficientes.")
        peor = fuga['filas'][0] if fuga['filas'] else None
        for (valor, texto), (cifra, descripcion) in zip(self._cifras_fuga, (
                (_pct(fuga['promedio']), "del universo está desconectado"),
                (_pct(peor['tasa']) if peor else "—", f"{peor['nombre']}, el que más pierde" if peor else ""),
                (_num(int((unidades['ACTIVACION'] == 'DESCONECTADO').sum())), "unidades desconectadas"))):
            valor.setText(cifra)
            texto.setText(descripcion)
        rec = servicio.clientes_a_recuperar(unidades, self._solo_parciales)
        self.grafico_clientes.set_datos(rec['filas'])
        for (valor, texto), (cifra, descripcion) in zip(self._cifras_clientes, (
                (_num(rec['con_desconexiones']), "clientes con unidades desconectadas"),
                (_pct(rec['pct_top10']), "de las desconexiones están en 10 clientes"),
                (_num(rec['parciales']), "clientes que aún tienen unidades conectadas"))):
            valor.setText(cifra)
            texto.setText(descripcion)

    # ------------------------------------------------------------------ panel de metas
    def _geometria_panel(self, abierto):
        ancho = min(PanelMetas.ANCHO, self.width() - 24)
        x = self.width() - ancho - 16 if abierto else self.width()
        return QRect(x, self._cabecera.height() + 4, ancho, self.panel_metas.alto_para(ancho))

    def _mostrar_panel(self, mostrar):
        if mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        self._anim_panel.stop()
        if mostrar:
            self.panel_metas.abrir(self._metas, self._metas_civ)
            self.panel_metas.setGeometry(self._geometria_panel(False))
            self.panel_metas.show()
            self.panel_metas.raise_()
        self._anim_panel.setStartValue(self.panel_metas.geometry())
        self._anim_panel.setEndValue(self._geometria_panel(mostrar))
        self._anim_panel.start()

    def _al_terminar_animacion(self):
        if not self._panel_abierto:
            self.panel_metas.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._panel_abierto:
            self.panel_metas.setGeometry(self._geometria_panel(True))

    def _on_metas_cambiaron(self):
        self._cargar_metas()
        self._registrar_cierres()
        self.panel_metas._metas = self._metas
        self.panel_metas._metas_civ = self._metas_civ
        self._repintar()

    # ------------------------------------------------------------------ datos
    def refresh_if_dirty(self):
        if self._data_dirty:
            self.load_data()
        else:
            self._vigilar_metas()

    def _vigilar_metas(self):
        """Las metas viven en una carpeta compartida: si otra persona las cambió, se leen de nuevo y se repinta."""
        if self._panorama is None or not self.isVisible() or metas_service.firma_archivo() == self._firma_metas:
            return
        self._cargar_metas()
        self.panel_metas._metas = self._metas
        self.panel_metas._metas_civ = self._metas_civ
        self._repintar()

    # El panorama calculado se comparte entre las pestañas del Dashboard hasta que lleguen datos nuevos: la segunda
    # pestaña no lo recalcula (era lo que más tardaba al abrirla por primera vez)
    _CACHE_PANORAMA = None
    _VERSION_DATOS = 0
    _adelantada = None   # versión de datos ya pintada al deslizar la pestaña (ver preparar_deslizamiento)

    def preparar_deslizamiento(self):
        """Antes de fotografiar esta pestaña para deslizarla: se pinta ya con los datos en caché, así la foto sale
        completa y la carga que la ventana dispara al cambiar de pestaña no vuelve a repintar durante la animación."""
        self._adelantada = None
        self.load_data()
        if DashboardModule._CACHE_PANORAMA is not None:
            self._adelantada = DashboardModule._VERSION_DATOS

    def _on_data_ready(self):
        DashboardModule._VERSION_DATOS += 1
        DashboardModule._CACHE_PANORAMA = None
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def load_data(self):
        """Calcula el panorama en segundo plano mientras corre la animación de carga."""
        self._data_dirty = False
        if self._adelantada == DashboardModule._VERSION_DATOS:
            self._adelantada = None
            return
        if self._calculo is not None and self._calculo.isRunning():
            self._recarga_pendiente = True
            return
        cache = DashboardModule._CACHE_PANORAMA
        if cache is not None:
            self._al_calcular(cache[0], cacheado=True)
            return
        if self._panorama is None:
            self._esqueleto.iniciar_ya()
        else:
            self._esqueleto.iniciar()
        self._version_calculo = DashboardModule._VERSION_DATOS
        self._calculo =_CalculoPanorama(self.data_manager.get_comercial_df(), self)
        self._calculo.terminado.connect(self._al_calcular)
        self._calculo.start()

    def _al_calcular(self, panorama, cacheado=False):
        if not cacheado and getattr(self, '_version_calculo', None) == DashboardModule._VERSION_DATOS:
            DashboardModule._CACHE_PANORAMA = (panorama,)
        igual = cacheado and self._panorama is panorama and self._firma_pintada == self._firma_actual()
        self._panorama = panorama
        if igual:
            # La pestaña ya está pintada con estos datos y estos filtros: no se vuelve a calcular nada
            self._esqueleto.terminar()
            return
        self._llenar_filtros()
        if not (cacheado and getattr(self, '_cierres_version', None) == DashboardModule._VERSION_DATOS):
            self._registrar_cierres()
            self._cierres_version = DashboardModule._VERSION_DATOS
        self._cargar_metas()
        self._repintar()
        self._esqueleto.terminar()
        if self._recarga_pendiente:
            self._recarga_pendiente = False
            QTimer.singleShot(0, self.load_data)

    def _cargar_metas(self):
        self._firma_metas = metas_service.firma_archivo()
        self._metas = metas_service.leer_metas()
        self._metas_civ = metas_service.leer_metas_civ()
        self._registro = metas_service.leer_registro()

    def _registrar_cierres(self):
        """Guarda una sola vez cuánto se vendió y cuánto estaba conectado de cada
        mes ya cerrado, para no recalcularlo a cada rato."""
        if self._panorama is None:
            return
        actual = date.today()
        cierres = [(m['periodo'].year, m['periodo'].month, m['vendidas'], m['conectadas'])
                   for m in servicio.calcular_mensual(servicio.filtrar_panorama(self._panorama, SIN_PRUEBAS=True, SIN_NO_APLICA=True))
                   if (m['periodo'].year, m['periodo'].month) < (actual.year, actual.month)]
        if metas_service.registrar_cierres(cierres):
            self._registro = metas_service.leer_registro()

    # ------------------------------------------------------------------ filtros jerárquicos
    _CLAVES_FILTRO = ("EJECUTIVO", "FORMA", "SERVICIO", "CIV", "SZ", "PERIODO", "FLOTA")
    _TITULOS_FILTRO = {"EJECUTIVO": "Ejecutivo", "FORMA": "Contrato", "SERVICIO": "Plan", "PERIODO": "Período"}

    def _valor_filtro(self, clave):
        if clave == "FLOTA":
            return self._flota
        if clave in ("CIV", "SZ"):
            return self.chk_servicio[clave.lower()].isChecked()
        return self.filtros[clave].currentData() or ""

    def _limpiar_filtro(self, clave):
        if clave == "FLOTA":
            self._flota = ""
            self.search_input.setText("")
            barra = getattr(self.window(), 'search_bar', None)
            if barra is not None and barra.text():
                barra.blockSignals(True)
                barra.setText("")
                barra.blockSignals(False)
            return
        control = self.chk_servicio[clave.lower()] if clave in ("CIV", "SZ") else self.filtros[clave]
        control.blockSignals(True)
        control.setChecked(False) if clave in ("CIV", "SZ") else control.setCurrentIndex(0)
        control.blockSignals(False)

    @staticmethod
    def _filtros_de(valores):
        """Argumentos de `filtrar_panorama` a partir de los valores de cada filtro."""
        servicio_f = {"plan": valores.get("SERVICIO", ""), "civ": bool(valores.get("CIV")), "sz": bool(valores.get("SZ"))}
        elegido = valores.get("PERIODO") or {}
        periodo = {"anio": elegido.get("anio", ""), "meses": elegido.get("meses") or []}
        return {"SIN_PRUEBAS": not valores.get("PRUEBAS"), "SIN_NO_APLICA": not valores.get("NO_APLICA"),
                "EJECUTIVO": valores.get("EJECUTIVO", ""), "FORMA": valores.get("FORMA", ""), "FLOTA": valores.get("FLOTA", ""),
                "SERVICIO": servicio_f if any(servicio_f.values()) else "",
                "PERIODO": periodo if any(periodo.values()) else ""}

    def _valores_actuales(self, excluir=()):
        valores = {c: self._valor_filtro(c) for c in self._CLAVES_FILTRO if c not in excluir}
        valores["PRUEBAS"] = self.chk_pruebas.isChecked()
        valores["NO_APLICA"] = self.chk_no_aplica.isChecked()
        return valores

    def _cambio_pruebas(self, _estado=None):
        """Incluir o no los contratos de prueba no es un filtro del orden: reajusta las listas y repinta."""
        self._llenar_filtros()
        self._filtrar_animado()

    def _cambio_filtro(self, clave):
        """Cada filtro depende del orden en que se eligieron: al cambiar o quitar uno,
        se limpian los que se eligieron después, y cada lista muestra solo lo compatible."""
        orden = self._orden_filtros
        if clave in orden:
            posicion = orden.index(clave)
            posteriores = orden[posicion + 1:]
            del orden[posicion + 1:]
            for otra in posteriores:
                self._limpiar_filtro(otra)
            if not self._valor_filtro(clave):
                orden.remove(clave)
        elif self._valor_filtro(clave):
            orden.append(clave)
        self._llenar_filtros()
        self._filtrar_animado()

    def _llenar_filtros(self):
        """Rellena cada filtro con lo que queda disponible según los demás elegidos."""
        if self._panorama is None:
            return
        self._orden_filtros[:] = [c for c in self._orden_filtros if self._valor_filtro(c)]
        for clave in ("EJECUTIVO", "FORMA", "SERVICIO", "PERIODO", "FLOTA", "CIV", "SZ"):
            sub = {"unidades": servicio.unidades_filtradas(
                self._panorama, **self._filtros_de(self._valores_actuales(excluir=(clave,))))}
            if clave in ("CIV", "SZ"):
                marca = self.chk_servicio[clave.lower()]
                marca.setEnabled(marca.isChecked() or servicio.tiene_complemento(sub['unidades'], clave.lower()))
                continue
            if clave == "FLOTA":
                self._flotas = servicio.opciones_filtro(sub)["FLOTA"]
                if self._flota and self._flota not in self._flotas:
                    self._limpiar_filtro("FLOTA")
                continue
            if clave == "SERVICIO":
                pares = [(etiqueta, valor) for valor, etiqueta in servicio.planes_servicio(sub)]
            elif clave == "PERIODO":
                inicio = sub['unidades']['INICIO'].dropna()
                anio = (self._valor_filtro("PERIODO") or {}).get("anio")
                meses_de = inicio[inicio.dt.year == anio] if anio else inicio
                self.filtros["PERIODO"].set_opciones(sorted({int(a) for a in inicio.dt.year}, reverse=True),
                                                     sorted({int(m) for m in meses_de.dt.month}))
                continue
            else:
                pares = [(v, v) for v in servicio.opciones_filtro(sub)[clave]]
            combo = self.filtros[clave]
            if isinstance(combo, SelectorMultiple):
                combo.set_opciones(pares)
                continue
            actual = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(self._TITULOS_FILTRO[clave], "")
            for etiqueta, valor in pares:
                combo.addItem(etiqueta, valor)
            indice = combo.findData(actual) if actual else 0
            combo.setCurrentIndex(max(0, indice))
            combo.blockSignals(False)
        self._orden_filtros[:] = [c for c in self._orden_filtros if self._valor_filtro(c)]

    def _quitar_filtros(self):
        for clave in self._CLAVES_FILTRO:
            self._limpiar_filtro(clave)
        self._orden_filtros.clear()
        self._llenar_filtros()
        self._filtrar_animado()

    def filter_table(self):
        """Lo llama la ventana al escribir en su barra de búsqueda: aquí sugiere
        flotas bajo la barra y filtra solo al elegir una. Vacía, limpia el filtro."""
        texto = self.search_input.text().strip()
        barra = getattr(self.window(), 'search_bar', None)
        if not texto:
            self._carga_barra.detener()
            self._ocultar_lista()
            if self._ultimo_texto:
                self._ultimo_texto = ""
                if self._flota:
                    self._flota = ""
                    self._cambio_filtro("FLOTA")
            return
        self._ultimo_texto = texto
        self._carga_barra.detener()
        if barra is None or not barra.hasFocus() or texto == self._flota:
            self._ocultar_lista()
            return
        coinciden = [f for f in self._flotas if texto.casefold() in f.casefold()]
        self._sugerencias.clear()
        self._sugerencias.addItems(coinciden[:10])
        if not coinciden:
            self._ocultar_lista()
            return
        ventana = self.window()
        if self._sugerencias.parent() is not ventana:
            self._sugerencias.setParent(ventana)
            barra.installEventFilter(self)
        origen, ancho = self._ancla_sugerencias(barra)
        self._sugerencias.setFixedWidth(max(ancho, 260))
        self._sugerencias.move(origen + QPoint(0, 6))
        self._animar_lista(min(len(coinciden), 10) * 30 + 18)

    def _ancla_sugerencias(self, barra):
        """(esquina inferior izquierda, ancho) bajo la que se coloca la lista: la píldora de búsqueda, sin su halo."""
        ventana = self.window()
        pildora = getattr(ventana, 'buscador', None)
        if pildora is None:
            return barra.mapTo(ventana, barra.rect().bottomLeft()), barra.width()
        m = pildora.MARGEN
        return pildora.mapTo(ventana, QPoint(m, pildora.height() - m)), pildora.width() - 2 * m

    def _animar_lista(self, alto):
        """La lista baja desde la barra hasta su alto; al cerrar sube y desaparece."""
        self._anim_lista.stop()
        if not self._sugerencias.isVisible():
            self._sugerencias.setFixedHeight(1)
            self._sugerencias.show()
        self._sugerencias.raise_()
        self._anim_lista.setStartValue(float(self._sugerencias.height()))
        self._anim_lista.setEndValue(float(alto))
        self._anim_lista.start()

    def _ocultar_lista(self):
        if self._sugerencias.isVisible():
            self._animar_lista(0)

    def _alto_lista(self, valor):
        alto = int(valor)
        if alto <= 0:
            self._sugerencias.hide()
        else:
            self._sugerencias.setFixedHeight(alto)

    def _al_escribir_barra(self, texto):
        """Línea de carga bajo la barra mientras se esperan las sugerencias."""
        if not self.isVisible() or not texto.strip():
            self._carga_barra.detener()
            return
        barra = self.window().search_bar
        ventana = self.window()
        if self._carga_barra.parent() is not ventana:
            self._carga_barra.setParent(ventana)
        origen, ancho = self._ancla_sugerencias(barra)
        self._carga_barra.setGeometry(QRect(origen + QPoint(18, -3), QSize(max(ancho - 36, 0), 3)))
        self._carga_barra.iniciar()

    def showEvent(self, event):
        super().showEvent(event)
        if self._panorama is None and DashboardModule._CACHE_PANORAMA is None:
            QTimer.singleShot(0, self._esqueleto.iniciar_ya)
        barra = getattr(self.window(), 'search_bar', None)
        if barra is not None and not self._barra_conectada:
            self._barra_conectada = True
            barra.textChanged.connect(self._al_escribir_barra)

    def _elegir_sugerencia(self, item):
        valor = item.text()
        self._sugerencias.hide()
        self._ultimo_texto = valor
        barra = getattr(self.window(), 'search_bar', None)
        if barra is not None:
            barra.setText(valor)
        self._flota = valor
        self._cambio_filtro("FLOTA")

    def _filtrar_animado(self, *_):
        """Al aplicar o sacar un filtro, muestra la animación de carga y luego repinta."""
        # El cálculo toma un cuarto de segundo o menos: se repinta de inmediato y el esqueleto (que solo aparece si
        # la carga pasa de su retraso) se quita al terminar, sin esperas fijas
        self._esqueleto.iniciar(rapido=True)
        QTimer.singleShot(0, self._repintar_y_terminar)

    def _repintar_y_terminar(self):
        self._repintar()
        self._esqueleto.terminar()

    def mostrar_cambio_pestana(self):
        """Al llegar desde otra pestaña del Dashboard: esqueleto breve en vez de un salto."""
        if self._panorama is None:
            return
        # Con los datos ya calculados no hace falta esqueleto: la pestaña aparece de inmediato
        if self._flota != getattr(self, '_flota_pintada', self._flota):
            self._esqueleto.iniciar_ya(rapido=True)
            self._llenar_filtros()
            self._repintar()
            self._fin_carga.start(150)

    def hideEvent(self, event):
        self._sugerencias.hide()
        super().hideEvent(event)

    _firma_pintada = None

    def _firma_actual(self):
        return (DashboardModule._VERSION_DATOS, repr(self._valores_actuales()))

    def _filtros_activos(self):
        self._flota_pintada = self._flota
        self._firma_pintada = self._firma_actual()
        return self._filtros_de(self._valores_actuales())

    # ------------------------------------------------------------------ pintado
    def _repintar(self, *_):
        activos = self._filtros_activos()
        filtrando = any(v for k, v in activos.items() if k not in ("SIN_PRUEBAS", "SIN_NO_APLICA"))
        self.btn_quitar.setEnabled(filtrando)
        if self._panorama is None:
            self._pintar_kpis(None)
            for grafico in (self.grafico_mes, self.grafico_metas, self.grafico_servicio, self.grafico_ejecutivo):
                grafico.set_datos([])
            self.lbl_ej_nota.setText("")
            self.lbl_sin_fecha.hide()
            self._unidades_actuales = None
            self._pintar_fuga_clientes()
            return
        sub = servicio.filtrar_panorama(self._panorama, **activos)
        self._panorama_vista = sub
        unidades = sub['unidades']
        self._pintar_kpis(servicio.calcular_kpis(unidades))
        anios = servicio.anios_inicio(self._panorama)
        periodos = servicio.periodos_del_filtro(activos.get("PERIODO"), anio_min=anios[-1] if anios else None)
        mensual = servicio.calcular_mensual(sub, periodos=periodos)
        self._pintar_mes_a_mes(mensual)
        sin_fecha = servicio.desconectadas_sin_fecha(sub)
        self.lbl_sin_fecha.setText(
            f"{_num(sin_fecha)} unidades con estado Desconectado no tienen fecha de baja ni de término, "
            "así que no aparecen en ningún mes de este gráfico." if sin_fecha else "")
        self.lbl_sin_fecha.setVisible(bool(sin_fecha))
        self._pintar_metas(mensual, filtrando, periodos is not None)
        self.grafico_servicio.set_datos(servicio.conexion_por_servicio(unidades))
        ejecutivos = servicio.camiones_por_ejecutivo(unidades)
        self.grafico_ejecutivo.set_datos(ejecutivos['filas'])
        self._unidades_actuales = unidades
        self._pintar_fuga_clientes()
        self.lbl_ej_nota.setText(
            f"{_num(ejecutivos['de_inactivos'])} unidades de ejecutivos que ya no están no aparecen en la lista. "
            "Cuentan los estados Activación pendiente, Vigente, Vencido, Baja, Baja solicitada y Revisar "
            "(este último solo con activación activando, conectado o desconectado).")

    def _detalle_mes(self, periodo):
        if periodo is None or self._panorama_vista is None:
            return None
        return servicio.detalle_clientes_mes(self._panorama_vista, periodo)

    @staticmethod
    def _etiqueta_mes(periodo, corta=False):
        nombre = servicio.MESES_CORTOS[periodo.month - 1] if corta else servicio.MESES[periodo.month - 1]
        return nombre if corta else f"{nombre} {periodo.year}"

    def _pintar_mes_a_mes(self, mensual):
        self.grafico_mes.set_datos([dict(m, etiqueta=self._etiqueta_mes(m['periodo'])) for m in reversed(mensual)])

    def _alternar_meses_metas(self):
        self._meses_metas = 12 if self._meses_metas == 6 else 6
        self.btn_meses_metas.setText("Ver menos" if self._meses_metas > 6 else "Ver 6 meses más")
        self.grafico_metas.set_visibles(self._meses_metas, animado=True)

    def _pintar_metas(self, mensual, filtrando, por_periodo=False, filtrando_meta=None):
        """`filtrando`: hay algún filtro (los cierres registrados ya no sirven). `filtrando_meta`: hay un filtro que
        recorta las ventas del equipo; Año y Mes no lo hacen, así que con ellos la meta se sigue mostrando."""
        sin_meta = filtrando if filtrando_meta is None else filtrando_meta
        datos = []
        varios_anios = len({m['periodo'].year for m in mensual}) > 1
        self.btn_meses_metas.setVisible(len(mensual) > 6 and not por_periodo)
        self.btn_meses_metas.setText("Ver menos" if self._meses_metas > 6 else "Ver 6 meses más")
        for m in mensual:
            clave = (m['periodo'].year, m['periodo'].month)
            # Cada columna son los camiones vendidos ese mes y su estado de hoy (no lo registrado al cierre del mes);
            # conectadas reúne Conectado, Activando, Sin flota y No entregado, como la tarjeta Conectados
            vendidas, conectadas = m['vendidas'], m['conectadas_total']
            etiqueta = self._etiqueta_mes(m['periodo'], corta=True) + (f" {str(m['periodo'].year)[2:]}" if varios_anios else "")
            conectadas = min(conectadas, vendidas)
            datos.append({'etiqueta': etiqueta, 'periodo': m['periodo'], 'vendidas': vendidas, 'conectadas': conectadas,
                          'desconectadas': min(m.get('desconectadas', 0), vendidas - conectadas),
                          'meta': None if sin_meta else self._metas.get(clave)})
        self.grafico_metas.set_datos(datos)
        self.grafico_metas.set_visibles(len(datos) if por_periodo else self._meses_metas)
        if sin_meta:
            self.lbl_meta_nota.setText("Meta: solo sin filtros")
        elif not any(d['meta'] for d in datos):
            self.lbl_meta_nota.setText("Aún no hay metas definidas")
        else:
            self.lbl_meta_nota.setText("Metas del equipo de Volvo Connect")

    def _pintar_kpis(self, k):
        etiquetas = (self.lbl_universo, self.lbl_conectadas, self.lbl_no_conectada, self.lbl_civ, self.lbl_sz,
                     self.lbl_universo_pct, self.lbl_take_rate, self.lbl_civ_pct, self.lbl_sz_pct)
        barras = (self.barra_universo, self.barra_conectadas, self.barra_civ, self.barra_sz, self.barra_no_conectada)
        self._vaciar_desglose()
        if k is None:
            for lbl in etiquetas:
                lbl.setText("—")
            for barra in barras:
                barra.set_tramos([])
            return
        self.lbl_universo.setText(_num(k['universo']))
        self.lbl_universo_pct.setText("100%")
        self.barra_universo.set_tramos([(1.0, MARINO)])
        self.lbl_conectadas.setText(_num(k['conectadas']))
        self.lbl_take_rate.setText(_pct(k['take_rate']))
        self.barra_conectadas.set_tramos([(k['take_rate'], MARINO)])
        self.lbl_civ.setText(_num(k['civ']))
        self.lbl_civ_pct.setText(f"CIV · {_pct(k['civ_pct'])} de VC")
        self.barra_civ.set_tramos([(k['civ_pct'], MARINO)])
        self.lbl_sz.setText(_num(k['sz']))
        self.lbl_sz_pct.setText(f"SZ · {_pct(k['sz_pct'])} de VC")
        self.barra_sz.set_tramos([(k['sz_pct'], TONO_MEDIO)])
        self.lbl_no_conectada.setText(_num(k['no_conectada']))
        total = k['no_conectada'] or 1
        estados = sorted((d for d in k['desglose_no_conectada'] if d[1] > 0), key=lambda d: -d[1])
        self.barra_no_conectada.set_tramos([(n / total, COLORES_ESTADO.get(e, TONO_CLARO)) for e, n in estados])
        visibles = estados[:4]
        if len(estados) > 4:
            visibles.append(("OTROS", sum(n for _, n in estados[4:])))
        for estado, n in visibles:
            self.caja_desglose.addWidget(self._fila_desglose(estado, n, n / total))

    def _vaciar_desglose(self):
        while self.caja_desglose.count():
            item = self.caja_desglose.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _fila_desglose(estado, n, fraccion):
        contenedor = QWidget()
        fila = QHBoxLayout(contenedor)
        fila.setContentsMargins(0, 0, 0, 0)
        fila.setSpacing(6)
        fila.addWidget(_Punto(COLORES_ESTADO.get(estado, TONO_CLARO), 8))
        fila.addWidget(_etiqueta(estado.capitalize(), f"color: {APAGADO}; font-size: 11px; font-weight: 600;"))
        fila.addStretch()
        fila.addWidget(_etiqueta(f"{_num(n)} · {_pct(fraccion)}", f"color: {TINTA}; font-size: 11px; font-weight: 700;"))
        return contenedor
