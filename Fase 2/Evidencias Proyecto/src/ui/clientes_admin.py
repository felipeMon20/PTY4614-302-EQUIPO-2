"""Administración de clientes: un cliente por RUT (sin RUT utilizable, por razón
social). Al seleccionar un cliente se abre un panel a la derecha, como las
acciones rápidas de Comercial, donde se cambia su razón social en todas sus
unidades y el RUT de una de sus razones; desde el formulario de una unidad ese
nombre queda bloqueado."""
import unicodedata

import pandas as pd
from PyQt6.QtCore import Qt, QPoint, QRect, QPropertyAnimation, QEasingCurve, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QFrame,
                             QMessageBox, QComboBox, QCheckBox, QScrollArea, QStackedWidget)

from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.services import comercial_services
from src.theme.colors import WARNING
from src.theme.theme_manager import ThemeManager
from src.ui import admin_estilo, comercial_estilo as estilo_com
from src.ui.custom_table import AppTableWidget
from src.ui.formulario_unidad import GuardadoUnidadesMixin
from src.ui.ingresos_base import ModeloTablaIngresos

SUBTABS = ("Todos", "Varias razones", "Sin RUT")
COLUMNAS = ["RUT", "RAZÓN SOCIAL", "OTRAS RAZONES", "UNIDADES"]


def _sin_formato(texto):
    """Texto sin mayúsculas, tildes ni espacios repetidos, para comparar nombres."""
    normal = unicodedata.normalize('NFKD', " ".join(str(texto).split()))
    return "".join(c for c in normal if not unicodedata.combining(c)).upper()


def _unidades(n):
    return f"{n} {'unidad' if n == 1 else 'unidades'}"


class PanelCliente(QFrame):
    """Panel lateral con la edición del cliente seleccionado."""

    cerrar_pedido = pyqtSignal()
    guardar_razon = pyqtSignal(str, str)
    guardar_rut = pyqtSignal(str, str, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("accionesRapidasComercial")
        self.setStyleSheet(estilo_com.QSS_PANEL_FLOTANTE)
        self.cliente = None
        self._razones = []
        self._otros = {}
        marco = QVBoxLayout(self)
        marco.setContentsMargins(1, 1, 1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        scroll.viewport().setAutoFillBackground(False)
        contenido = QWidget()
        contenido.setAutoFillBackground(False)
        contenido.setObjectName("cuerpoPanelCliente")
        contenido.setStyleSheet(
            "QWidget#cuerpoPanelCliente { background: transparent; }"
            f"QLineEdit, QComboBox {{ background-color: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; "
            f"border-radius: 10px; padding: 6px 10px; color: {estilo_com.TINTA}; font-size: 12px; }}"
            f"QLineEdit:focus, QComboBox:focus {{ border: 1px solid {estilo_com.PRIMARIO}; }}")
        scroll.setWidget(contenido)
        marco.addWidget(scroll)

        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(8)

        fila_titulo = QHBoxLayout()
        lbl_titulo = QLabel("CLIENTE")
        lbl_titulo.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        fila_titulo.addWidget(lbl_titulo)
        fila_titulo.addStretch()
        btn_cerrar = QPushButton()
        btn_cerrar.setIcon(ThemeManager.icon('fa5s.times', color=estilo_com.APAGADO))
        btn_cerrar.setFixedSize(26, 26)
        btn_cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cerrar.setToolTip("Cerrar (quita la selección)")
        btn_cerrar.setStyleSheet(estilo_com.QSS_BOTON_CERRAR_PANEL)
        btn_cerrar.clicked.connect(self.cerrar_pedido.emit)
        fila_titulo.addWidget(btn_cerrar)
        lay.addLayout(fila_titulo)

        self.lbl_nombre = QLabel("")
        self.lbl_nombre.setWordWrap(True)
        self.lbl_nombre.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 15px; font-weight: 800; background: transparent;")
        lay.addWidget(self.lbl_nombre)
        self.fila_chips = QHBoxLayout()
        self.fila_chips.setSpacing(6)
        self.chip_rut = QLabel("")
        self.chip_unidades = QLabel("")
        self.chip_razones = QLabel("")
        self.chip_rut.setStyleSheet(estilo_com.qss_chip(estilo_com.PIZARRA_SUAVE, estilo_com.TINTA))
        self.chip_unidades.setStyleSheet(estilo_com.qss_chip("#E0F2FE", "#0369A1"))
        self.chip_razones.setStyleSheet(estilo_com.qss_chip("#FEE2E2", "#B91C1C"))
        for chip in (self.chip_rut, self.chip_unidades, self.chip_razones):
            self.fila_chips.addWidget(chip)
        self.fila_chips.addStretch()
        lay.addLayout(self.fila_chips)

        lay.addSpacing(4)
        selector = QFrame()
        selector.setObjectName("selectorPanelCliente")
        selector.setStyleSheet(f"QFrame#selectorPanelCliente {{ background-color: {estilo_com.PIZARRA_SUAVE}; border-radius: 12px; }}")
        fila_sel = QHBoxLayout(selector)
        fila_sel.setContentsMargins(4, 4, 4, 4)
        fila_sel.setSpacing(4)
        self.pila = QStackedWidget()
        self._pestanas = []
        for i, texto in enumerate(("Razón social", "RUT")):
            btn = QPushButton(texto)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {estilo_com.APAGADO}; border: none; border-radius: 9px; "
                "padding: 7px 0px; font-size: 12px; font-weight: 700; }"
                f"QPushButton:checked {{ background-color: {estilo_com.SUPERFICIE}; color: {estilo_com.PRIMARIO}; }}")
            btn.clicked.connect(lambda _c, k=i: self._ir_a_pestana(k))
            fila_sel.addWidget(btn, 1)
            self._pestanas.append(btn)
        lay.addWidget(selector)
        lay.addWidget(self.pila)

        pag_razon = QWidget()
        lr = QVBoxLayout(pag_razon)
        lr.setContentsMargins(0, 6, 0, 0)
        lr.setSpacing(8)
        lr.addWidget(self._titulo_seccion("Nueva razón social"))
        self.txt_razon = QLineEdit()
        self.txt_razon.textChanged.connect(self._actualizar_razon)
        lr.addWidget(self.txt_razon)
        self.lbl_aviso_razon = self._aviso(estilo_com.APAGADO)
        self.lbl_choque_razon = self._aviso(WARNING, negrita=True)
        lr.addWidget(self.lbl_aviso_razon)
        lr.addWidget(self.lbl_choque_razon)
        self.btn_razon = self._boton_guardar("Guardar razón social")
        self.btn_razon.clicked.connect(self._on_guardar_razon)
        lr.addWidget(self.btn_razon)
        lr.addStretch()
        self.pila.addWidget(pag_razon)

        pag_rut = QWidget()
        lt = QVBoxLayout(pag_rut)
        lt.setContentsMargins(0, 6, 0, 0)
        lt.setSpacing(8)
        lt.addWidget(self._titulo_seccion("Razón social a corregir"))
        self.cmb_razon = QComboBox()
        self.cmb_razon.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_razon.setMinimumContentsLength(10)
        self.cmb_razon.currentIndexChanged.connect(self._actualizar_rut)
        lt.addWidget(self.cmb_razon)
        lt.addWidget(self._titulo_seccion("RUT nuevo"))
        self.txt_rut = QLineEdit()
        self.txt_rut.setPlaceholderText("Sin puntos ni guion. Ej: 763764309")
        self.txt_rut.textChanged.connect(self._actualizar_rut)
        lt.addWidget(self.txt_rut)
        self.chk_nombre = QCheckBox("")
        self.chk_nombre.setStyleSheet("background: transparent;")
        self.chk_nombre.hide()
        lt.addWidget(self.chk_nombre)
        self.lbl_aviso_rut = self._aviso(estilo_com.APAGADO)
        lt.addWidget(self.lbl_aviso_rut)
        self.btn_rut = self._boton_guardar("Guardar RUT")
        self.btn_rut.clicked.connect(self._on_guardar_rut)
        lt.addWidget(self.btn_rut)
        lt.addStretch()
        self.pila.addWidget(pag_rut)

        lay.addStretch()
        self._ir_a_pestana(0)

    def _ir_a_pestana(self, indice):
        self.pila.setCurrentIndex(indice)
        for i, btn in enumerate(self._pestanas):
            btn.setChecked(i == indice)

    @staticmethod
    def _titulo_seccion(texto):
        lbl = QLabel(texto.upper())
        lbl.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        return lbl

    @staticmethod
    def _aviso(color, negrita=False):
        lbl = QLabel("")
        lbl.setWordWrap(True)
        peso = "700" if negrita else "400"
        lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: {peso}; background: transparent; border: none;")
        return lbl

    @staticmethod
    def _boton_guardar(texto):
        btn = QPushButton(texto)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR)
        return btn

    def set_cliente(self, cliente, razones, otros_clientes):
        """Carga el cliente (dict de resumen_clientes), sus razones
        [(nombre, unidades)] y los demás clientes."""
        self.cliente = cliente
        self._razones = razones
        self._otros = {c["CLAVE"]: c for c in otros_clientes}
        self.lbl_nombre.setText(str(cliente["RAZÓN SOCIAL"]))
        self.chip_rut.setText(f"RUT {cliente['RUT']}")
        self.chip_unidades.setText(_unidades(int(cliente["UNIDADES"])))
        self.chip_razones.setText(f"{len(razones)} razones")
        self.chip_razones.setVisible(len(razones) > 1)
        self.txt_razon.blockSignals(True)
        self.txt_razon.setText(str(cliente["RAZÓN SOCIAL"]))
        self.txt_razon.blockSignals(False)
        self.cmb_razon.blockSignals(True)
        self.cmb_razon.clear()
        for razon, n in razones:
            self.cmb_razon.addItem(f"{razon}  ({_unidades(n)})", razon)
        self.cmb_razon.blockSignals(False)
        self.txt_rut.blockSignals(True)
        self.txt_rut.clear()
        self.txt_rut.blockSignals(False)
        self._actualizar_razon()
        self._actualizar_rut()

    # ---------------------------------------------------------- razón social
    def _actualizar_razon(self):
        if self.cliente is None:
            return
        nuevo = self.txt_razon.text().strip()
        n = int(self.cliente["UNIDADES"])
        self.lbl_aviso_razon.setText(f"Se cambiará en {_unidades(n)} de este cliente.")
        choque = None
        if nuevo:
            clave_nueva = _sin_formato(nuevo)
            choque = next((o for o in self._otros.values() if _sin_formato(o["RAZÓN SOCIAL"]) == clave_nueva), None)
        if choque is not None:
            self.lbl_choque_razon.setText(
                f"Ya existe un cliente con ese nombre (RUT {choque['RUT']}, {_unidades(int(choque['UNIDADES']))}). "
                "Seguirán siendo clientes distintos porque su RUT es distinto.")
            self.lbl_choque_razon.show()
        else:
            self.lbl_choque_razon.hide()
        self.btn_razon.setEnabled(bool(nuevo))

    def _on_guardar_razon(self):
        nuevo = self.txt_razon.text().strip()
        if self.cliente is not None and nuevo:
            self.guardar_razon.emit(self.cliente["CLAVE"], nuevo)

    # ------------------------------------------------------------------- RUT
    def _destino(self):
        llave = comercial_services.rut_llave(self.txt_rut.text())
        return self._otros.get(f"RUT:{llave}") if llave else None

    def _actualizar_rut(self):
        if self.cliente is None:
            return
        razon = self.cmb_razon.currentData()
        n = next((n for r, n in self._razones if r == razon), 0)
        llave = comercial_services.rut_llave(self.txt_rut.text())
        destino = self._destino()
        misma = bool(llave) and f"RUT:{llave}" == self.cliente["CLAVE"]
        self.chk_nombre.hide()
        if not llave:
            texto = "Escribe el RUT nuevo para la razón social elegida."
        elif misma:
            texto = "Ese ya es el RUT actual de este cliente."
        elif destino is not None:
            texto = (f"Este RUT ya pertenece a {destino['RAZÓN SOCIAL']} ({_unidades(int(destino['UNIDADES']))}). "
                     f"Las {_unidades(n)} de esta razón se unirán a ese cliente.")
            if _sin_formato(destino["RAZÓN SOCIAL"]) != _sin_formato(razon or ""):
                self.chk_nombre.setText(f"Usar también el nombre «{destino['RAZÓN SOCIAL']}»")
                self.chk_nombre.show()
        else:
            texto = f"Se asignará ese RUT en {_unidades(n)}; el CDB no se modifica."
        self.lbl_aviso_rut.setText(texto)
        self.btn_rut.setEnabled(bool(llave) and not misma and bool(razon))

    def _on_guardar_rut(self):
        if self.cliente is None:
            return
        destino = self._destino()
        usar_nombre = destino is not None and not self.chk_nombre.isHidden() and self.chk_nombre.isChecked()
        self.guardar_rut.emit(self.cliente["CLAVE"], self.cmb_razon.currentData(), self.txt_rut.text().strip(),
                              destino["RAZÓN SOCIAL"] if usar_nombre else None)


class ClientesAdminModule(GuardadoUnidadesMixin, QWidget):
    MODULO_LOG = "Administración (Clientes)"

    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.df_clientes = pd.DataFrame(columns=comercial_services.COLUMNAS_RESUMEN_CLIENTES)
        self.df_tabla = pd.DataFrame(columns=COLUMNAS)
        self._data_dirty = False
        self._clave_panel = None
        self._panel_abierto = False

        self.search_input = QLineEdit()
        self.search_input.hide()

        self._setup_ui()
        self.data_manager.data_ready.connect(self._on_data_ready)
        self.load_data()

    # ------------------------------------------------------------ interfaz
    def _setup_ui(self):
        layout = admin_estilo.raiz_pantalla(self)

        contenedor_tabs, self.subtabs, self._badges = admin_estilo.subpestanas(SUBTABS)
        self.subtabs.currentChanged.connect(lambda _i: self._pintar_tabla())
        layout.addWidget(contenedor_tabs)

        self._barra = admin_estilo.barra_opciones('fa5s.building', "Clientes", "")
        layout.addWidget(self._barra.marco)

        self.btn_exportar = admin_estilo.boton_capsula(self._barra, 'fa5s.file-excel', "Exportar a Excel")
        self.btn_exportar.clicked.connect(lambda: self.table.export_to_excel("Clientes"))
        self.btn_recargar = admin_estilo.boton_capsula(self._barra, 'fa5s.sync-alt', "Recargar")
        self.btn_recargar.clicked.connect(self.load_data)

        marco, capas = admin_estilo.tarjeta_contenido("tarjetaClientesAdmin")
        self.table = AppTableWidget()
        self.table.menu_type = "solo_lectura"
        admin_estilo.estilar_tabla(self.table)
        self.model = ModeloTablaIngresos(
            resolver=self._color_celda, alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.table.set_model_and_delegate(self.model)
        self.table.sort_changed.connect(self._pintar_tabla)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._actualizar_panel())
        capas.addWidget(self.table, 1)
        layout.addWidget(marco, 1)

        self.panel = PanelCliente()
        self.panel.setParent(self)
        estilo_com.crear_sombra_panel(self.panel)
        self.panel.hide()
        self.panel.cerrar_pedido.connect(self.table.clearSelection)
        self.panel.guardar_razon.connect(self._on_guardar_razon)
        self.panel.guardar_rut.connect(self._on_guardar_rut)
        self._anim_panel = QPropertyAnimation(self.panel, b"pos", self)
        self._anim_panel.setDuration(240)
        self._anim_panel.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_panel.finished.connect(self._on_anim_terminada)
        self._anim_panel.valueChanged.connect(lambda _v: self._ajustar_barra_bajo_panel())
        self._actualizar_panel()

    @staticmethod
    def _color_celda(columna, valor, es_fondo):
        if columna == "OTRAS RAZONES" and valor != "-" and not es_fondo:
            return "#E04848"
        if columna == "RUT" and valor == "Sin RUT" and not es_fondo:
            return "#D98404"
        return None

    # ------------------------------------------------------- panel flotante
    def _geometria_panel(self, abierto):
        return estilo_com.geometria_panel_flotante(self, abierto)

    def _mostrar_panel(self, mostrar):
        if mostrar == self._panel_abierto:
            return
        self._panel_abierto = mostrar
        self._anim_panel.stop()
        if mostrar:
            estilo_com.montar_panel_sobre_encabezado(self, self.panel, lambda: self._panel_abierto)
            if not self.panel.isVisible():
                self.panel.setGeometry(self._geometria_panel(False))
                self.panel.show()
            self.panel.raise_()
        self._anim_panel.setStartValue(self.panel.pos())
        self._anim_panel.setEndValue(self._geometria_panel(mostrar).topLeft())
        self._anim_panel.start()

    def _on_anim_terminada(self):
        if not self._panel_abierto:
            self.panel.hide()
        self._ajustar_barra_bajo_panel()

    def _ajustar_barra_bajo_panel(self):
        """Corre los botones de la barra hacia la izquierda para que el panel no los tape."""
        solape = 0
        if self.panel.isVisible():
            borde = self._barra.marco.mapTo(self.panel.parentWidget(), QPoint(self._barra.marco.width(), 0)).x()
            solape = max(0, borde - self.panel.x() + 4)
            estilo_com.sombra_segun_posicion(self.panel, self._geometria_panel(False).x(), self._geometria_panel(True).x())
        self._barra.marco.layout().setContentsMargins(15, 12, 15 + solape, 12)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.__dict__.get('panel') is not None and self.panel.isVisible():
            self._anim_panel.stop()
            QTimer.singleShot(0, self._reubicar_panel)

    def _reubicar_panel(self):
        if not self.panel.isVisible():
            return
        self.panel.setGeometry(self._geometria_panel(self._panel_abierto))
        if not self._panel_abierto:
            self.panel.hide()
        self._ajustar_barra_bajo_panel()

    def _actualizar_panel(self):
        self.btn_exportar.setEnabled(not self.df_tabla.empty)
        cliente = self._cliente_seleccionado()
        if cliente is None:
            self._clave_panel = None
            self._mostrar_panel(False)
            return
        if cliente["CLAVE"] != self._clave_panel:
            self._clave_panel = cliente["CLAVE"]
            otros = [c for c in self.df_clientes.to_dict('records') if c["CLAVE"] != cliente["CLAVE"]]
            razones = comercial_services.razones_de_cliente(self.data_manager.get_comercial_df(), cliente["CLAVE"])
            self.panel.set_cliente(cliente, razones, otros)
        self._mostrar_panel(True)

    # --------------------------------------------------------------- datos
    def load_data(self):
        self._data_dirty = False
        self.df_clientes = comercial_services.resumen_clientes(self.data_manager.get_comercial_df())
        self._clave_panel = None
        self._actualizar_kpis_y_contadores()
        self._pintar_tabla()

    def refresh_if_dirty(self):
        if self._data_dirty:
            self.load_data()

    def _on_data_ready(self):
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def _filtrar_subtab(self, df, idx):
        if df.empty:
            return df
        if idx == 1:
            return df[df["OTRAS RAZONES"] != "-"]
        if idx == 2:
            return df[df["CLAVE"].str.startswith("RS:")]
        return df

    def _actualizar_kpis_y_contadores(self):
        df = self.df_clientes
        total = len(df)
        varias = int((df["OTRAS RAZONES"] != "-").sum()) if total else 0
        sin_rut = int(df["CLAVE"].str.startswith("RS:").sum()) if total else 0
        for i in range(len(SUBTABS)):
            admin_estilo.actualizar_contador(self.subtabs, self._badges, i, len(self._filtrar_subtab(df, i)))
        unidades = int(df["UNIDADES"].sum()) if total else 0
        self._barra.lbl_subtitulo.setText(f"{total} clientes · {varias} con varias razones · {unidades} unidades")

    def _pintar_tabla(self):
        df = self._filtrar_subtab(self.df_clientes, self.subtabs.currentIndex())
        df = df[COLUMNAS] if not df.empty else pd.DataFrame(columns=COLUMNAS)
        texto = self.search_input.text().strip().lower()
        if texto and not df.empty:
            mascara = df.astype(str).apply(lambda col: col.str.lower().str.contains(texto, regex=False)).any(axis=1)
            df = df[mascara]
        self.df_tabla = self.table.apply_sort(df).reset_index(drop=True)
        self.model.set_data(self.df_tabla)
        for col, ancho in (("RUT", 150), ("RAZÓN SOCIAL", 360), ("OTRAS RAZONES", 360), ("UNIDADES", 110)):
            if col in self.df_tabla.columns:
                self.table.setColumnWidth(self.df_tabla.columns.get_loc(col), ancho)
        self._actualizar_panel()

    def filter_table(self):
        self._pintar_tabla()

    # ----------------------------------------------------------- acciones
    def _cliente_seleccionado(self):
        filas = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        if len(filas) != 1 or not (0 <= filas[0] < len(self.df_tabla)):
            return None
        fila = self.df_tabla.iloc[filas[0]]
        coincide = self.df_clientes[(self.df_clientes["RUT"] == fila["RUT"])
                                    & (self.df_clientes["RAZÓN SOCIAL"] == fila["RAZÓN SOCIAL"])]
        return coincide.iloc[0].to_dict() if not coincide.empty else None

    def _on_guardar_razon(self, clave, nueva_razon):
        lote = comercial_services.cambios_razon_social_cliente(
            self.data_manager.get_comercial_df(), clave, nueva_razon)
        if not lote:
            QMessageBox.information(self, "Sin cambios", "Todas las unidades de este cliente ya tienen esa razón social.")
            return
        self.guardar_lote_unidades(lote, "Guardando la razón social del cliente…")

    def _on_guardar_rut(self, clave, razon, nuevo_rut, nueva_razon):
        lote = comercial_services.cambios_rut_razon_cliente(
            self.data_manager.get_comercial_df(), clave, razon, nuevo_rut, nueva_razon)
        if not lote:
            QMessageBox.information(self, "Sin cambios", "No hay unidades para actualizar con esos datos.")
            return
        self.guardar_lote_unidades(lote, "Guardando el RUT de la razón social…")
