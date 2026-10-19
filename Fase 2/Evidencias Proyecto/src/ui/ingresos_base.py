"""Esqueleto compartido de las pantallas de Ingresos y Conciliación (JustTime,
Contratos CM y las que sigan): tarjetas KPI que filtran, barra azul de
opciones separada de la tabla (como Comercial), tabla de la app y panel
flotante con la ficha de la unidad. Solo apariencia y navegación empresas ->
unidades; la lógica de datos de cada pantalla vive en su módulo y en su
servicio."""
import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QHeaderView,
                             QAbstractItemView, QScrollArea, QGridLayout, QApplication, QComboBox)
from PyQt6.QtCore import Qt, QEvent, QRect, QRectF, QPointF, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PyQt6.QtGui import QGuiApplication, QColor, QFont, QPainter, QPen

from src.core.constants import COL_VIN, COL_CHASIS, COL_RAZON_SOCIAL
from src.ui import comercial_estilo as estilo_com
from src.ui.transiciones import TransicionFundidoSubida
from src.ui.custom_table import AppTableWidget, PandasTableModel
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *


class ModeloTablaIngresos(PandasTableModel):
    """Solo lectura. `resolver(columna, valor, es_fondo)` devuelve el color de
    la celda (fondo del chip o color del texto) o None para dejar el de la
    tabla."""

    def __init__(self, *args, resolver=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.resolver = resolver
        self.destacar_columnas_cliente()

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

    def _data_claro(self, index, role):
        if self.resolver is not None and index.isValid() and role in (
                Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole):
            valor = self._df.iat[index.row(), index.column()]
            color = self.resolver(self._df.columns[index.column()], "" if pd.isna(valor) else valor,
                                  role == Qt.ItemDataRole.BackgroundRole)
            if color is not None:
                return QColor(color)
        return super()._data_claro(index, role)


def boton_barra(texto, icono, variante='neutro', color_icono=None):
    btn = QPushButton(f" {texto}" if texto else "")
    btn.setIcon(ThemeManager.icon(icono, color=color_icono or TEXT_SECONDARY))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    estilo_com.aplicar_estilo_boton_barra(btn, variante)
    return btn


class ComboFiltroBarra(estilo_com.ComboTarjeta):
    """Combo de la barra azul; su lista se abre en la tarjeta flotante del
    resto de las pantallas. En modo compacto (cuando el panel flotante
    reduce el espacio) se dibuja como un botón con solo el ícono; un punto
    ámbar indica que hay un valor distinto al primero."""

    ANCHO_COMPACTO = 44

    def __init__(self, icono, titulo="", parent=None):
        super().__init__(titulo, parent)
        self._icono = icono
        self._titulo = titulo
        self._compacto = False
        self._ancho_normal = 0
        self._pix = None
        self.currentIndexChanged.connect(lambda _i: self._actualizar_tooltip())

    def set_compacto(self, compacto):
        if compacto == self._compacto:
            return
        self._compacto = compacto
        if compacto:
            self._ancho_normal = self.minimumWidth()
            self.setFixedWidth(self.ANCHO_COMPACTO)
        else:
            self.setMinimumWidth(self._ancho_normal)
            self.setMaximumWidth(16777215)
        self._actualizar_tooltip()
        self.update()

    def _actualizar_tooltip(self):
        self.setToolTip(f"{self._titulo}: {self.currentText()}" if self._compacto and self._titulo else "")

    def paintEvent(self, event):
        if not self._compacto:
            return super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        marco = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(255, 255, 255, 46 if self.underMouse() else 26))
        p.setPen(QPen(QColor(255, 255, 255, 46), 1))
        p.drawRoundedRect(marco, 10, 10)
        if self._pix is None:
            self._pix = ThemeManager.icon_pixmap(self._icono, color='white', size=16)
        lado = self._pix.deviceIndependentSize()
        p.drawPixmap(int(marco.center().x() - lado.width() / 2), int(marco.center().y() - lado.height() / 2), self._pix)
        if self.currentIndex() > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FBBF24"))
            p.drawEllipse(QPointF(marco.right() - 8, marco.top() + 8), 4, 4)


def estilo_combo_barra():
    return (
        "QComboBox { background-color: rgba(255,255,255,0.10); color: white; border: 1px solid rgba(255,255,255,0.18);"
        " border-radius: 10px; padding: 0 12px; min-height: 34px; font-weight: 600; font-size: 12px; }"
        "QComboBox:hover { background-color: rgba(255,255,255,0.18); }"
        "QComboBox::drop-down { border: none; width: 22px; }"
        "QComboBox QAbstractItemView { background: white; color: #0F1B33; selection-background-color: #E8F0FE;"
        " selection-color: #0F1B33; outline: none; }")


def aplicar_estilo_tabla_lectura(tabla, alto_fila=42, extra_qss=""):
    """Deja una AppTableWidget con el aspecto de la tabla de Comercial,
    de solo lectura y sin las acciones de columna (fijar, mover)."""
    qss = estilo_com.QSS_TABLA + (
        "QHeaderView::section { background: #F7F8FC; color: #6B7A90; border-bottom: 1px solid #E3E8F0; }"
        "QTableView { alternate-background-color: #FFFFFF; }"
        "QTableView::item { border-left: none; }") + extra_qss
    tabla.setStyleSheet(qss)
    tabla.frozen_view.setStyleSheet(qss)
    tabla.horizontalHeader().setSectionsMovable(False)
    tabla.permitir_fijar_columna = False
    for header in (tabla.horizontalHeader(), tabla.frozen_view.horizontalHeader()):
        header.sectionDoubleClicked.disconnect()
        header.sectionHandleDoubleClicked.disconnect()
    tabla.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    tabla.horizontalHeader().set_word_wrap_habilitado(True)
    estilo_com.aplicar_estilo_encabezado(tabla.horizontalHeader())
    tabla.horizontalHeader().set_estilo_encabezado(
        "#F7F8FC", "#F7F8FC", "#6B7A90", "#E3E8F0",
        separador=None, grosor_linea=1, alto_minimo=44, espaciado_letras=0.8,
        iconos_orden=True, radio_superior=13, texto_negrita_fuerte=True,
    )
    tabla.verticalHeader().setDefaultSectionSize(alto_fila)
    tabla.menu_type = "solo_lectura"
    tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    tabla.horizontalHeader().setStretchLastSection(True)
    tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    tabla.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)


class PantallaIngresosBase(QWidget):
    """Base de una pantalla de dos niveles (empresas -> unidades).

    La subclase define:
      AVATAR, TITULO, KPI_SPECS = [(titulo, clave, color, ayuda), ...]
      CAMPOS_FICHA = [(etiqueta, columna), ...]  (celdas del panel)
      COLUMNAS_EMPRESAS / COLUMNAS_DETALLE y sus anchos
    y llama a `construir_base()` desde su `_setup_ui`. Mientras arma la
    pantalla puede agregar widgets con `agregar_filtro`, `agregar_blanco` y
    `agregar_capsula`, y las acciones del panel con `agregar_accion_panel`.
    """

    AVATAR = "--"
    TITULO = ""
    KPI_SPECS = []
    CAMPOS_FICHA = []
    COLUMNAS_FICHA = 2
    ALTO_FILA = 42
    COL_CLAVE = COL_VIN
    COL_EMPRESA = COL_RAZON_SOCIAL
    COLUMNAS_OCULTAS = (COL_VIN,)
    COL_COPIA = COL_CHASIS
    ETIQUETA_COPIA = "Chasis"
    MOSTRAR_VIN_FICHA = True
    SELECCION_EN_NIVEL_1 = False
    ANCHOS_EMPRESAS = {}
    ANCHOS_DETALLE = {}
    NIVEL_UNICO = False  # una sola tabla con todos los registros, sin lista de empresas
    CLASE_MODELO = ModeloTablaIngresos
    CLASE_DELEGADO = estilo_com.DelegadoCeldasComercial

    # ---------------------------------------------------------- construcción
    def construir_base(self, tabla_extra_qss=""):
        self.empresa_actual = None
        self._historial = [None]
        self._historial_idx = 0
        self._df_tabla = pd.DataFrame()
        self._fila_por_vin = {}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        self._kpi_contenedor = QWidget()
        fila_kpis = QHBoxLayout(self._kpi_contenedor)
        fila_kpis.setSpacing(12)
        fila_kpis.setContentsMargins(0, 4, 0, 0)
        self.botones_kpi = {}
        for titulo, clave, color, ayuda in self.KPI_SPECS:
            tarjeta = estilo_com.TarjetaKpiResumen()
            tarjeta.definir(titulo, color, ayuda)
            tarjeta.clicked.connect(lambda _c=False, k=clave: self.on_kpi_clicado(k))
            self.botones_kpi[clave] = tarjeta
            fila_kpis.addWidget(tarjeta)
        main_layout.addWidget(self._kpi_contenedor)
        self._kpi_ocultos = False
        self.aplicar_visibilidad_kpi()

        self._contenido = self._build_bandeja(tabla_extra_qss)
        main_layout.addWidget(self._contenido, 1)

        # Panel flotante fuera del layout: aparece con unidades seleccionadas
        self._panel_detalle = self._build_detalle_card()
        self._panel_detalle.setParent(self)
        estilo_com.crear_sombra_panel(self._panel_detalle)
        self._panel_detalle.hide()
        self._panel_abierto = False
        self._anim_panel = QPropertyAnimation(self._panel_detalle, b"pos", self)
        estilo_com.configurar_animacion_panel(self._anim_panel)
        self._anim_panel.finished.connect(self._on_anim_panel_terminada)
        self._anim_panel.valueChanged.connect(lambda _v: self._ajustar_barra_bajo_panel())

        app = QGuiApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _build_bandeja(self, tabla_extra_qss):
        # Barra de opciones y tabla en tarjetas separadas, como en Comercial
        externo = QWidget()
        layout_externo = QVBoxLayout(externo)
        layout_externo.setContentsMargins(0, 0, 0, 0)
        layout_externo.setSpacing(12)

        marco = QFrame()
        marco.setObjectName("bandejaIngresos")
        marco.setStyleSheet(estilo_com.qss_tarjeta("bandejaIngresos"))
        capas = QVBoxLayout(marco)
        capas.setContentsMargins(1, 1, 1, 1)
        capas.setSpacing(0)

        barra = QFrame()
        barra.setObjectName("barraBandejaComercial")
        barra.setStyleSheet("QFrame#barraBandejaComercial { background-color: #1B2B4E; border: none; border-radius: 14px; }")
        fila = QHBoxLayout(barra)
        fila.setContentsMargins(15, 12, 15, 12)
        fila.setSpacing(8)
        self._barra_bandeja = barra
        layout_externo.addWidget(barra)
        layout_externo.addWidget(marco, 1)

        self.btn_volver = QPushButton()
        self.btn_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color='white'))
        self.btn_volver.setToolTip("Volver a la lista de empresas (o botón lateral del mouse)")
        self.btn_volver.setFixedWidth(44)
        self.btn_volver.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.18); "
            "border-radius: 10px; min-height: 34px; } QPushButton:hover { background-color: rgba(255,255,255,0.20); }")
        self.btn_volver.clicked.connect(self.ir_a_lista_empresas)
        self.btn_volver.hide()

        self.lbl_titulo = QLabel(self.TITULO)
        self.lbl_titulo.setStyleSheet("color: white; font-size: 15px; font-weight: 800; background: transparent;")
        self.lbl_subtitulo = QLabel("")
        self.lbl_subtitulo.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
        bloque_titulo = QWidget()
        lay_titulo = QVBoxLayout(bloque_titulo)
        lay_titulo.setContentsMargins(0, 0, 0, 0)
        lay_titulo.setSpacing(0)
        lay_titulo.addWidget(self.lbl_titulo)
        lay_titulo.addWidget(self.lbl_subtitulo)

        self._zona_filtros = QHBoxLayout()
        self._zona_filtros.setSpacing(8)
        self._zona_blancos = QHBoxLayout()
        self._zona_blancos.setSpacing(8)
        self._capsula = QFrame()
        self._capsula.setStyleSheet("QFrame { background: rgba(255,255,255,0.08); border-radius: 14px; }")
        self._lay_capsula = QHBoxLayout(self._capsula)
        self._lay_capsula.setContentsMargins(5, 5, 5, 5)
        self._lay_capsula.setSpacing(4)

        fila.addWidget(self.btn_volver)
        fila.addWidget(bloque_titulo)
        fila.addStretch()
        fila.addLayout(self._zona_filtros)
        fila.addLayout(self._zona_blancos)
        fila.addWidget(self._capsula)

        # Mostrar u ocultar las tarjetas KPI (el "Ampliar" de Comercial)
        self.btn_ampliar = None
        if self.KPI_SPECS:
            self.btn_ampliar = QPushButton()
            self.btn_ampliar.setCheckable(True)
            self.btn_ampliar.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_ampliar.setIcon(ThemeManager.icon('fa5s.expand', color=TEXT_SECONDARY))
            self.btn_ampliar.setToolTip("Ampliar tabla (oculta las tarjetas de resumen)")
            self.btn_ampliar.setFixedWidth(44)
            self.btn_ampliar.toggled.connect(self._on_ampliar_toggled)
            estilo_com.preparar_boton_capsula(self.btn_ampliar)
            self._ubicar_boton_ampliar()
            estilo_com.sincronizar_boton_kpi(self.btn_ampliar)

        self.tabla = self._crear_tabla(tabla_extra_qss)
        capas.addWidget(self.tabla, 1)

        self.lbl_sin_resultados = QLabel("No hay resultados para este filtro.")
        self.lbl_sin_resultados.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sin_resultados.setStyleSheet(
            f"color: {estilo_com.APAGADO}; font-size: 12px; padding: 30px; background: transparent; border: none;")
        self.lbl_sin_resultados.hide()
        capas.addWidget(self.lbl_sin_resultados)
        return externo

    def _crear_tabla(self, tabla_extra_qss):
        # Mismo componente y estilo de tabla que la bandeja de Comercial
        tabla = AppTableWidget()
        aplicar_estilo_tabla_lectura(tabla, self.ALTO_FILA, tabla_extra_qss)
        tabla.horizontalHeader().sectionClicked.connect(self._on_encabezado_clicado)
        tabla.sort_changed.connect(self._pintar_tabla)
        self.modelo = self.CLASE_MODELO(
            resolver=self.resolver_color, alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        tabla.set_model_and_delegate(self.modelo)
        self._delegado_celdas = self.CLASE_DELEGADO([tabla, tabla.frozen_view])
        tabla.setItemDelegate(self._delegado_celdas)
        tabla.frozen_view.setItemDelegate(self._delegado_celdas)
        tabla.selectionModel().selectionChanged.connect(self._on_seleccion_cambiada)
        tabla.clicked.connect(self._on_click_celda)
        tabla.frozen_view.clicked.connect(self._on_click_celda)
        return tabla

    # ----------------------------------------------- piezas que arma la subclase
    def agregar_filtro(self, widget):
        self._zona_filtros.addWidget(widget)

    def agregar_blanco(self, boton):
        """Los antiguos botones blancos ahora van en la cápsula azul, con el
        mismo estilo que el resto de los botones de la barra."""
        self.agregar_capsula(boton)

    def agregar_capsula(self, boton):
        self._lay_capsula.addWidget(boton)
        estilo_com.preparar_boton_capsula(boton)
        self._ubicar_boton_ampliar()

    def _ubicar_boton_ampliar(self):
        """"Ampliar" queda siempre penúltimo en la cápsula, como en Comercial
        (el último es Recargar)."""
        if getattr(self, 'btn_ampliar', None) is None:
            return
        self._lay_capsula.removeWidget(self.btn_ampliar)
        self._lay_capsula.insertWidget(max(0, self._lay_capsula.count() - 1), self.btn_ampliar)

    def aplicar_visibilidad_kpi(self, ocultar_ademas=False):
        """Las tarjetas se ven si la pantalla las define, la persona no las
        ocultó y la pantalla no pide esconderlas (ej. el editor de una fila)."""
        self._kpi_contenedor.setVisible(bool(self.KPI_SPECS) and not self._kpi_ocultos and not ocultar_ademas)

    def showEvent(self, event):
        super().showEvent(event)
        estilo_com.sincronizar_boton_kpi(getattr(self, 'btn_ampliar', None))

    def _on_ampliar_toggled(self, ampliada):
        estilo_com.guardar_kpi_ocultos(ampliada)
        self._kpi_ocultos = ampliada
        self.aplicar_visibilidad_kpi(getattr(self, '_kpi_oculto_por_pantalla', False))
        self.btn_ampliar.setIcon(ThemeManager.icon('fa5s.compress' if ampliada else 'fa5s.expand', color=TEXT_SECONDARY))
        self.btn_ampliar.setToolTip(
            "Volver a mostrar las tarjetas de resumen" if ampliada else "Ampliar tabla (oculta las tarjetas de resumen)")

    def agregar_accion_panel(self, boton):
        self._lay_acciones.addWidget(boton)

    def resolver_color(self, columna, valor, es_fondo):
        """Color de una celda (chip o texto); la subclase lo sobreescribe."""
        return None

    def colores_chip_ficha(self, columna, valor):
        """(fondo, texto) para una celda de la ficha, o None para usar el
        catálogo de la tabla."""
        return None

    def on_kpi_clicado(self, clave):
        pass

    def on_fila_cambiada(self, fila, cantidad):
        """Se llama al seleccionar unidades; la subclase puede ajustar el panel."""

    # ------------------------------------------------------- panel flotante
    def _geometria_panel(self, abierto):
        return estilo_com.geometria_panel_flotante(self, abierto)

    def _mostrar_panel(self, mostrar):
        panel = self._panel_detalle
        if mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        self._modo_compacto_barra(mostrar)
        self._anim_panel.stop()
        if mostrar:
            estilo_com.montar_panel_sobre_encabezado(self, panel, lambda: self._panel_abierto)
            if not panel.isVisible():
                panel.setGeometry(self._geometria_panel(False))
                panel.show()
            panel.raise_()
            estilo_com.fijar_sombra_panel(panel, True)
        self._anim_panel.setStartValue(panel.pos())
        self._anim_panel.setEndValue(self._geometria_panel(mostrar).topLeft())
        self._anim_panel.start()

    def _modo_compacto_barra(self, compacto):
        """Con el panel abierto, filtros y botones blancos pasan a solo ícono
        (el texto queda como ayuda emergente) para que quepan en la barra."""
        for zona in (self._zona_filtros, self._zona_blancos):
            for i in range(zona.count()):
                w = zona.itemAt(i).widget()
                if isinstance(w, ComboFiltroBarra):
                    w.set_compacto(compacto)
                elif isinstance(w, QPushButton):
                    if compacto and w.property("texto_original") is None:
                        w.setProperty("texto_original", w.text())
                        w.setProperty("ancho_original", w.minimumWidth())
                        w.setText("")
                        w.setToolTip(w.toolTip() or str(w.property("texto_original")).strip())
                        w.setFixedWidth(ComboFiltroBarra.ANCHO_COMPACTO)
                    elif not compacto and w.property("texto_original") is not None:
                        w.setText(w.property("texto_original"))
                        w.setMinimumWidth(w.property("ancho_original") or 0)
                        w.setMaximumWidth(16777215)
                        w.setProperty("texto_original", None)

    def _on_anim_panel_terminada(self):
        if not self._panel_abierto:
            self._panel_detalle.hide()
            estilo_com.fijar_sombra_panel(self._panel_detalle, False)
        self._ajustar_barra_bajo_panel()

    def _ajustar_barra_bajo_panel(self):
        """Corre los botones de la barra hacia la izquierda para que el panel
        flotante no los tape."""
        barra, panel = self._barra_bandeja, self._panel_detalle
        solape = 0
        if panel.isVisible():
            borde_derecho = barra.mapTo(panel.parentWidget(), QPoint(barra.width(), 0)).x()
            solape = max(0, borde_derecho - panel.x() + 4)
        barra.layout().setContentsMargins(15, 12, 15 + solape, 12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        panel = getattr(self, '_panel_detalle', None)
        if panel is not None and panel.isVisible():
            self._anim_panel.stop()
            QTimer.singleShot(0, self._reubicar_panel)

    def _reubicar_panel(self):
        panel = self._panel_detalle
        if not panel.isVisible():
            return
        panel.setGeometry(self._geometria_panel(self._panel_abierto))
        if not self._panel_abierto:
            panel.hide()
        self._ajustar_barra_bajo_panel()

    @staticmethod
    def _titulo_seccion(texto):
        lbl = QLabel(texto)
        fuente = lbl.font()
        fuente.setCapitalization(QFont.Capitalization.AllUppercase)
        lbl.setFont(fuente)
        lbl.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        return lbl

    def _build_detalle_card(self):
        frame = QFrame()
        frame.setObjectName("accionesRapidasComercial")
        frame.setStyleSheet(estilo_com.QSS_PANEL_FLOTANTE)
        marco = QVBoxLayout(frame)
        marco.setContentsMargins(1, 1, 1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        scroll.viewport().setAutoFillBackground(False)
        contenido = QWidget()
        contenido.setAutoFillBackground(False)
        contenido.setStyleSheet("background: transparent;")
        scroll.setWidget(contenido)
        marco.addWidget(scroll)

        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        fila_titulo = QHBoxLayout()
        self._lbl_titulo_panel = self._titulo_seccion("Unidad seleccionada")
        fila_titulo.addWidget(self._lbl_titulo_panel)
        fila_titulo.addStretch()
        btn_cerrar = QPushButton()
        btn_cerrar.setIcon(ThemeManager.icon('fa5s.times', color=estilo_com.APAGADO))
        btn_cerrar.setFixedSize(26, 26)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setToolTip("Cerrar (quita la selección)")
        btn_cerrar.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        btn_cerrar.clicked.connect(lambda: self.tabla.clearSelection())
        fila_titulo.addWidget(btn_cerrar)
        layout.addLayout(fila_titulo)

        self._detalle_labels = {}
        layout.addWidget(self._build_ficha_hero())
        grilla = QGridLayout()
        grilla.setSpacing(6)
        for i, (etiqueta, columna) in enumerate(self.CAMPOS_FICHA):
            celda, lbl_valor = estilo_com.crear_celda_ficha(etiqueta)
            grilla.addWidget(celda, i // self.COLUMNAS_FICHA, i % self.COLUMNAS_FICHA)
            self._detalle_labels[columna] = lbl_valor
        layout.addLayout(grilla)

        self._lbl_aviso_panel = QLabel("")
        self._lbl_aviso_panel.setWordWrap(True)
        self._lbl_aviso_panel.setStyleSheet(
            "background-color: #FEF2F2; color: #B91C1C; border: 1px solid #FECACA; border-radius: 10px;"
            " padding: 8px 10px; font-size: 11px; font-weight: 600;")
        self._lbl_aviso_panel.hide()
        layout.addWidget(self._lbl_aviso_panel)

        layout.addSpacing(4)
        layout.addWidget(self._titulo_seccion("Acciones"))
        self._lay_acciones = QVBoxLayout()
        self._lay_acciones.setSpacing(10)
        layout.addLayout(self._lay_acciones)
        layout.addStretch()
        return frame

    def _build_ficha_hero(self):
        """Iniciales + razón social + chasis (clic para copiar) y VIN."""
        hero = QFrame()
        hero.setObjectName("fichaHeroComercial")
        hero.setStyleSheet(estilo_com.QSS_FICHA_HERO)
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(12, 12, 12, 12)
        hero_layout.setSpacing(12)
        self._ficha_avatar = QLabel("--")
        self._ficha_avatar.setFixedSize(46, 46)
        self._ficha_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ficha_avatar.setStyleSheet(estilo_com.QSS_FICHA_AVATAR)

        textos = QVBoxLayout()
        textos.setSpacing(2)
        self._ficha_nombre = QLabel("—")
        self._ficha_nombre.setWordWrap(True)
        self._ficha_nombre.setStyleSheet(estilo_com.QSS_FICHA_NOMBRE)

        fila_chasis = QHBoxLayout()
        fila_chasis.setSpacing(4)
        prefijo = QLabel(self.ETIQUETA_COPIA)
        prefijo.setStyleSheet(estilo_com.QSS_FICHA_CHASIS)
        self._ficha_chasis = QLabel("—")
        self._ficha_chasis.setStyleSheet(estilo_com.QSS_FICHA_CHASIS + " font-weight: bold;")
        self._ficha_chasis.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ficha_chasis.setToolTip("Clic para copiar")
        self._ficha_chasis.mousePressEvent = lambda event: self._copiar_chasis()
        icono_copiar = QLabel()
        icono_copiar.setPixmap(ThemeManager.icon_pixmap('fa5s.copy', color=TEXT_MUTED, size=11))
        icono_copiar.setStyleSheet("background: transparent; border: none;")
        fila_chasis.addWidget(prefijo)
        fila_chasis.addWidget(self._ficha_chasis)
        fila_chasis.addWidget(icono_copiar)
        fila_chasis.addStretch()

        self._ficha_vin = QLabel("")
        self._ficha_vin.setWordWrap(True)
        self._ficha_vin.setStyleSheet(estilo_com.QSS_FICHA_CHASIS)

        textos.addWidget(self._ficha_nombre)
        textos.addLayout(fila_chasis)
        textos.addWidget(self._ficha_vin)
        hero_layout.addWidget(self._ficha_avatar)
        hero_layout.addLayout(textos, stretch=1)
        return hero

    def _copiar_chasis(self):
        texto = self._ficha_chasis.text()
        if texto and texto != "—":
            QApplication.clipboard().setText(texto)

    def _pintar_panel(self, fila, cantidad, aviso=""):
        for _etiqueta, columna in self.CAMPOS_FICHA:
            valor = str(fila.get(columna, "") or "").strip()
            lbl = self._detalle_labels[columna]
            colores = self.colores_chip_ficha(columna, valor)
            if colores is not None and valor not in ("", "-"):
                lbl.setText(estilo_com.texto_chip_con_punto(valor))
                lbl.setStyleSheet(estilo_com.qss_chip_ficha(colores[0], colores[1]))
            else:
                estilo_com.pintar_chip_ficha(lbl, valor)
        razon = str(fila.get(COL_RAZON_SOCIAL, "") or "").strip() or "—"
        self._ficha_nombre.setText(razon)
        self._ficha_avatar.setText(estilo_com.iniciales(razon))
        self._ficha_chasis.setText(str(fila.get(self.COL_COPIA, "") or "—"))
        self._ficha_vin.setText(f"VIN {fila.get(COL_VIN, '')}")
        self._ficha_vin.setVisible(self.MOSTRAR_VIN_FICHA and self.COL_COPIA != COL_VIN)
        if aviso:
            self._lbl_aviso_panel.setText(aviso)
            self._lbl_aviso_panel.show()
        else:
            self._lbl_aviso_panel.hide()
        self._lbl_titulo_panel.setText("Unidad seleccionada" if cantidad == 1 else f"{cantidad} unidades seleccionadas")

    # ------------------------------------------------------------- tabla
    def _vins_seleccionados(self):
        df = self.modelo.get_df()
        if (self.empresa_actual is None and not self.SELECCION_EN_NIVEL_1 and not self.NIVEL_UNICO) or df.empty or self.COL_CLAVE not in df.columns:
            return []
        filas = sorted({idx.row() for idx in self.tabla.selectionModel().selectedRows()})
        col = df.columns.get_loc(self.COL_CLAVE)
        return [str(df.iat[r, col]).strip() for r in filas if 0 <= r < len(df)]

    def _on_seleccion_cambiada(self, *_args):
        vins = self._vins_seleccionados()
        if not vins:
            self._mostrar_panel(False)
            self.on_fila_cambiada({}, 0)
            return
        fila = self._fila_por_vin.get(vins[0], {})
        self.on_fila_cambiada(fila, len(vins))
        self._mostrar_panel(True)

    def _pintar_tabla(self):
        df = self.tabla.apply_sort(self._df_tabla.copy()) if not self._df_tabla.empty else self._df_tabla
        self.modelo.set_data(df)
        anchos = self.ANCHOS_EMPRESAS if self.empresa_actual is None and not self.NIVEL_UNICO else self.ANCHOS_DETALLE
        for i, col in enumerate(df.columns):
            self.tabla.setColumnWidth(i, anchos.get(col, 140))
            self.tabla.setColumnHidden(i, col in self.COLUMNAS_OCULTAS)
        self.tabla.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.tabla.verticalHeader().setDefaultSectionSize(self.ALTO_FILA)
        self._mostrar_panel(False)

    def _on_encabezado_clicado(self, logical_index):
        """Clic en un encabezado: ordena A→Z; un segundo clic invierte."""
        col_name = self.modelo.headerData(logical_index, Qt.Orientation.Horizontal)
        if not col_name:
            return
        if self.tabla._sort_column == col_name and self.tabla._sort_order == Qt.SortOrder.AscendingOrder:
            self.tabla._set_sort(col_name, Qt.SortOrder.DescendingOrder)
        else:
            self.tabla._set_sort(col_name, Qt.SortOrder.AscendingOrder)

    def _on_click_celda(self, index):
        """En la lista de empresas, un clic abre la empresa."""
        if self.empresa_actual is not None or self.NIVEL_UNICO:
            return
        df = self.modelo.get_df()
        if df.empty or not (0 <= index.row() < len(df)) or self.COL_EMPRESA not in df.columns:
            return
        empresa = str(df.iat[index.row(), df.columns.get_loc(self.COL_EMPRESA)])
        QTimer.singleShot(0, lambda: self.mostrar_detalle_empresa(empresa))

    # ---------------------------------------------------------- navegación
    def actualizar_titulo(self):
        self.lbl_titulo.setText(self.TITULO if self.empresa_actual is None else f"{self.TITULO} — {self.empresa_actual}")
        self.btn_volver.setVisible(self.empresa_actual is not None)

    def _ir_a(self, empresa, agregar_historial=True):
        self.empresa_actual = empresa
        if agregar_historial:
            self._historial = self._historial[:self._historial_idx + 1]
            if self._historial[-1] != empresa:
                self._historial.append(empresa)
                self._historial_idx = len(self._historial) - 1
        self.actualizar_titulo()
        self._animar_cambio_nivel()

    def _animar_cambio_nivel(self):
        """Fundido entre la lista de empresas y el detalle de una empresa."""
        contenedor = self._contenido
        padre = contenedor.parentWidget()
        if padre is None or not contenedor.isVisible():
            self.al_cambiar_nivel()
            return
        transicion = getattr(self, '_transicion_nivel', None)
        if transicion is None:
            transicion = TransicionFundidoSubida(padre, contenedor)
            transicion.DESPLAZAMIENTO_PX = 8
            transicion._anim.setDuration(170)
            self._transicion_nivel = transicion
        transicion.terminar()
        foto = contenedor.grab()
        self.al_cambiar_nivel()
        transicion.iniciar(foto)

    def al_cambiar_nivel(self):
        """La subclase vuelve a calcular y pintar la tabla."""

    def ir_a_lista_empresas(self):
        self._ir_a(None)

    def mostrar_detalle_empresa(self, empresa):
        self._ir_a(empresa)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            if event.button() == Qt.MouseButton.XButton1 and self._historial_idx > 0:
                self._historial_idx -= 1
                self._ir_a(self._historial[self._historial_idx], agregar_historial=False)
                return True
            if event.button() == Qt.MouseButton.XButton2 and self._historial_idx < len(self._historial) - 1:
                self._historial_idx += 1
                self._ir_a(self._historial[self._historial_idx], agregar_historial=False)
                return True
        return super().eventFilter(obj, event)
