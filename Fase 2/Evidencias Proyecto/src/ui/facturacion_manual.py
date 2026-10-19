import logging
import os

import pandas as pd
from PyQt6.QtCore import Qt, QStandardPaths, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit,
                             QMessageBox, QComboBox, QCheckBox, QFileDialog)

import config.settings
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.constants import COL_RAZON_SOCIAL, COL_VIN
from src.services import facturacion_manual_service as fm_service
from src.ui import comercial_estilo as estilo_com
from src.ui import facturacion_manual_pdf as fm_pdf
from src.ui.custom_table import AppTableWidget, PandasTableModel
from src.ui.formulario_unidad import GuardadoUnidadesMixin, PESTANA_JUSTTIME_CM
from src.ui.ingresos_base import (PantallaIngresosBase, ModeloTablaIngresos, ComboFiltroBarra, boton_barra,
                                  estilo_combo_barra, aplicar_estilo_tabla_lectura)
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *

logger = logging.getLogger(__name__)

COL_CLAVE_FM = "_CLAVE"
COL_CLIENTE = "CLIENTE"
COL_RUT_FM = "RUT"
COL_TIPO_FM = "TIPO"
COL_UNIDADES_FM = "UNIDADES"
COL_PRECIO_FM = "PRECIO UF"
COL_PAGO_FM = "PAGO CLP"
COL_ETAPA_FM = "ETAPA"
COL_PERIODO_FM = "PERÍODO"

_COLUMNAS_LISTA = [COL_CLAVE_FM, COL_CLIENTE, COL_RUT_FM, COL_TIPO_FM, COL_UNIDADES_FM, COL_PRECIO_FM,
                   COL_PAGO_FM, COL_ETAPA_FM]
_COLUMNAS_UNIDADES_EDITOR = ["FLOTA", "RUT", "N° CONTRATO", "VIN", "PLAN", "PRECIO UF"]

_KPI_SPECS = [
    ("Empresas con facturación manual", "empresas", "#0F766E", "Empresas con unidades por facturar en el período."),
    ("Unidades en facturación manual", "unidades", "#1F6FEB", "Suma de unidades de las empresas del período."),
    ("Pendiente por facturar", "pendiente", "#4338CA", "Empresas con etapa de gestión Pendiente."),
    ("Pago total facturación", "pago", BRAND_BLUE, "Suma del pago registrado de las empresas del período."),
]

_TIPOS_TEXTO = {fm_service.TIPO_OC: "OC", fm_service.TIPO_FACTURA_MANUAL: "Factura manual"}
_CHIP_TIPO = {"OC": ("#E1EAF4", BRAND_BLUE), "FACTURA MANUAL": ("#CCFBF1", "#115E59")}
_CHIP_ETAPA = {"PENDIENTE": ("#FEF3C7", "#92400E"), "FACTURADO": ("#D1FAE5", "#065F46"),
              "SIN REGISTRO": ("#FEE2E2", "#991B1B")}
_CHIP_EMPRESA = ("#E1EAF4", BRAND_BLUE)
_NIVELES = [("BASICO", "BÁSICO"), ("MEDIO", "MEDIO"), ("FULL", "FULL")]


def _clp(valor):
    return "$" + f"{int(round(valor)):,}".replace(",", ".")


def _num(valor, decimales=2):
    return f"{valor:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _precio_texto(precio):
    if precio is None or pd.isna(precio):
        return "—"
    texto = f"{float(precio):.4f}".rstrip("0")
    entero, _, dec = texto.partition(".")
    return f"{entero},{dec.ljust(2, '0')}"


def _valor_o_none(valor):
    return None if valor is None or (not isinstance(valor, str) and pd.isna(valor)) else valor


def aviso_registro(r):
    """Texto de aviso para un registro del período ('' si no hay nada que avisar)."""
    if not r["RUT"]:
        return ("Esta fila no tiene RUT en facturacionManual.xlsx: sin RUT no se pueden traer sus unidades "
                "de RM_CONTRATOS. Complétalo en el Excel y recarga.")
    if r["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM:
        return ("Empresa con unidades en Facturación Manual en RM_CONTRATOS y sin fila de este mes en "
                "facturacionManual.xlsx. La fila se crea al guardar el precio o al marcar la etapa.")
    en_pf, en_excel = int(r["UNIDADES_PF"]), int(r["UNIDADES_EXCEL"])
    if en_pf == 0:
        return "RM_CONTRATOS no tiene unidades con facturación manual para este RUT."
    if en_pf != en_excel:
        if r["ETAPA"] == fm_service.ETAPA_FACTURADO:
            return (f"Mes ya facturado: se mantienen las {en_excel} unidades del Excel. "
                    f"RM_CONTRATOS tiene hoy {en_pf}.")
        return (f"El Excel decía {en_excel} unidades y RM_CONTRATOS tiene {en_pf}. "
                f"Se usan las de RM_CONTRATOS y el Excel se actualiza al guardar.")
    return ""


class EditorFacturacion(QWidget):
    """Pantalla de edición de una flota: resumen de precios, detalle de
    unidades y panel lateral con nivel de servicio, precio UF y total."""

    volver = pyqtSignal()
    exportar_pdf = pyqtSignal()
    guardar = pyqtSignal()
    unidad_doble_clic = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registro = None
        self._uf = 0.0
        self._cantidad = 0
        self._build()

    @staticmethod
    def _tarjeta(nombre):
        marco = QFrame()
        marco.setObjectName(nombre)
        marco.setStyleSheet(estilo_com.qss_tarjeta(nombre))
        return marco

    @staticmethod
    def _titulo(texto):
        lbl = QLabel(texto)
        lbl.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        return lbl

    def _build(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(12)

        barra = QFrame()
        barra.setObjectName("barraEditorFM")
        barra.setStyleSheet("QFrame#barraEditorFM { background-color: #1B2B4E; border: none; border-radius: 14px; }")
        fila = QHBoxLayout(barra)
        fila.setContentsMargins(15, 12, 15, 12)
        fila.setSpacing(10)
        self.btn_volver = QPushButton()
        self.btn_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_volver.setIcon(ThemeManager.icon('fa5s.arrow-left', color='white'))
        self.btn_volver.setToolTip("Volver a la lista (o botón lateral del mouse)")
        self.btn_volver.setFixedWidth(44)
        self.btn_volver.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.18); "
            "border-radius: 10px; min-height: 34px; } QPushButton:hover { background-color: rgba(255,255,255,0.20); }")
        self.btn_volver.clicked.connect(self.volver.emit)
        self.lbl_empresa = QLabel("")
        self.lbl_empresa.setStyleSheet("color: white; font-size: 15px; font-weight: 800; background: transparent;")
        self.lbl_sub = QLabel("")
        self.lbl_sub.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(self.lbl_empresa)
        textos.addWidget(self.lbl_sub)
        self.btn_pdf = boton_barra("Exportar a PDF", 'fa5s.file-pdf', 'excel')
        self.btn_pdf.setIcon(ThemeManager.icon('fa5s.file-pdf', color='#1B2B4E'))
        self.btn_pdf.clicked.connect(self.exportar_pdf.emit)
        fila.addWidget(self.btn_volver)
        fila.addLayout(textos)
        fila.addStretch()
        fila.addWidget(self.btn_pdf)
        raiz.addWidget(barra)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        izquierda = QVBoxLayout()
        izquierda.setSpacing(12)

        resumen = self._tarjeta("resumenPreciosFM")
        lay_res = QVBoxLayout(resumen)
        lay_res.setContentsMargins(18, 14, 18, 16)
        lay_res.setSpacing(10)
        lay_res.addWidget(self._titulo("RESUMEN PRECIOS"))
        fila_res = QHBoxLayout()
        fila_res.setSpacing(10)
        self.val_unidades = self._tile("Unidades conectadas", fila_res)
        self.val_neto_uf = self._tile("Precio neto total UF", fila_res)
        self.val_neto_clp = self._tile("Precio neto total CLP", fila_res)
        lay_res.addLayout(fila_res)
        izquierda.addWidget(resumen)

        detalle = self._tarjeta("detalleUnidadesFM")
        lay_det = QVBoxLayout(detalle)
        lay_det.setContentsMargins(1, 14, 1, 1)
        lay_det.setSpacing(8)
        cab = QHBoxLayout()
        cab.setContentsMargins(17, 0, 17, 0)
        cab.addWidget(self._titulo("DETALLE DE UNIDADES"))
        self.lbl_cuenta = QLabel("")
        self.lbl_cuenta.setStyleSheet(
            f"background: #E1EAF4; color: {BRAND_BLUE}; border-radius: 10px; padding: 2px 10px;"
            " font-size: 11px; font-weight: 800;")
        cab.addWidget(self.lbl_cuenta)
        cab.addStretch()
        lay_det.addLayout(cab)
        self.lbl_aviso = QLabel("")
        self.lbl_aviso.setWordWrap(True)
        self.lbl_aviso.setStyleSheet(
            "background-color: #FEF2F2; color: #B91C1C; border: 1px solid #FECACA; border-radius: 10px;"
            " padding: 8px 10px; font-size: 11px; font-weight: 600; margin: 0 16px;")
        self.lbl_aviso.hide()
        lay_det.addWidget(self.lbl_aviso)

        self.tabla = AppTableWidget()
        aplicar_estilo_tabla_lectura(self.tabla, 42)
        self.modelo = ModeloTablaIngresos(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.tabla.set_model_and_delegate(self.modelo)
        self._delegado = estilo_com.DelegadoCeldasComercial([self.tabla, self.tabla.frozen_view])
        self.tabla.setItemDelegate(self._delegado)
        self.tabla.frozen_view.setItemDelegate(self._delegado)
        self.tabla.doubleClicked.connect(self._on_doble_clic)
        self.tabla.frozen_view.doubleClicked.connect(self._on_doble_clic)
        lay_det.addWidget(self.tabla, 1)
        izquierda.addWidget(detalle, 1)
        cuerpo.addLayout(izquierda, 1)

        lateral = self._tarjeta("panelPreciosFM")
        lateral.setFixedWidth(350)
        lay_lat = QVBoxLayout(lateral)
        lay_lat.setContentsMargins(18, 14, 18, 18)
        lay_lat.setSpacing(5)
        lay_lat.addWidget(self._titulo("RESUMEN"))
        self.lbl_cliente = self._par("Cliente", lay_lat)
        self.lbl_rut = self._par("RUT", lay_lat)

        lay_lat.addWidget(self._etiqueta("Tipo de gestión"))
        self.combo_tipo = estilo_com.ComboTarjeta("Tipo de gestión")
        self.combo_tipo.addItem("Sin definir", "")
        self.combo_tipo.addItem("OC (orden de compra)", fm_service.TIPO_OC)
        self.combo_tipo.addItem("Factura manual", fm_service.TIPO_FACTURA_MANUAL)
        ThemeManager.apply_combo_box(self.combo_tipo)
        self.combo_tipo.currentIndexChanged.connect(self._refrescar)
        lay_lat.addWidget(self.combo_tipo)

        lay_lat.addWidget(self._etiqueta("Nivel de servicio"))
        self.combo_nivel = estilo_com.ComboTarjeta("Nivel de servicio")
        for clave, texto in _NIVELES:
            self.combo_nivel.addItem(texto, clave)
        ThemeManager.apply_combo_box(self.combo_nivel)
        self.combo_nivel.currentIndexChanged.connect(self._al_cambiar_nivel)
        lay_lat.addWidget(self.combo_nivel)

        fila_chk = QHBoxLayout()
        fila_chk.addWidget(self._etiqueta("Complementarios"))
        fila_chk.addSpacing(8)
        self.chk_civ = QCheckBox("CIV")
        self.chk_civ.toggled.connect(self._refrescar)
        self.chk_safety = QCheckBox("Safety Zone")
        self.chk_safety.setEnabled(False)
        self.chk_safety.setToolTip("Próximamente")
        chip_prox = QLabel("Próximamente")
        chip_prox.setStyleSheet(
            "background: #EEF1F6; color: #6B7A90; border-radius: 9px; padding: 1px 8px;"
            " font-size: 10px; font-weight: 700;")
        fila_chk.addWidget(self.chk_civ)
        fila_chk.addSpacing(10)
        fila_chk.addWidget(self.chk_safety)
        fila_chk.addWidget(chip_prox)
        fila_chk.addStretch()
        lay_lat.addLayout(fila_chk)

        lay_lat.addWidget(self._etiqueta("Precio UF por unidad"))
        fila_precio = QHBoxLayout()
        self.input_precio = QLineEdit()
        self.input_precio.setPlaceholderText("0,00")
        self.input_precio.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d{0,4}([.,]\d{0,4})?$")))
        self.input_precio.setMinimumHeight(34)
        self.input_precio.textChanged.connect(self._refrescar)
        sufijo = QLabel("UF")
        sufijo.setStyleSheet("color: #6B7A90; font-weight: 800; background: transparent;")
        fila_precio.addWidget(self.input_precio, 1)
        fila_precio.addWidget(sufijo)
        lay_lat.addLayout(fila_precio)
        self.lbl_por_unidades = QLabel("")
        self.lbl_por_unidades.setStyleSheet("color: #6B7A90; font-size: 11px; background: transparent;")
        lay_lat.addWidget(self.lbl_por_unidades)

        caja_total = QFrame()
        caja_total.setObjectName("totalFM")
        caja_total.setStyleSheet("QFrame#totalFM { background: #F4F7FB; border-radius: 12px; }")
        lay_tot = QVBoxLayout(caja_total)
        caja_total.setMinimumHeight(96)
        lay_tot.setContentsMargins(14, 8, 14, 8)
        lay_tot.setSpacing(2)
        t_total = QLabel("Total mensual")
        t_total.setStyleSheet("color: #6B7A90; font-size: 11px; font-weight: 600; background: transparent;")
        self.lbl_total_uf = QLabel("0,00 UF")
        self.lbl_total_uf.setStyleSheet("color: #0F1B33; font-size: 22px; font-weight: 800; background: transparent;")
        self.lbl_total_uf.setMinimumHeight(30)
        self.lbl_total_clp = QLabel("$0 CLP")
        self.lbl_total_clp.setStyleSheet(f"color: {BRAND_BLUE}; font-size: 13px; font-weight: 700; background: transparent;")
        self.lbl_uf_dia = QLabel("")
        self.lbl_uf_dia.setStyleSheet("color: #6B7A90; font-size: 10px; background: transparent;")
        self.lbl_total_clp.setMinimumHeight(20)
        self.lbl_uf_dia.setMinimumHeight(14)
        lay_tot.addWidget(t_total)
        lay_tot.addWidget(self.lbl_total_uf)
        lay_tot.addWidget(self.lbl_total_clp)
        lay_tot.addWidget(self.lbl_uf_dia)
        lay_lat.addWidget(caja_total)
        lay_lat.addStretch()

        self.btn_guardar = QPushButton("Guardar facturación  →")
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.setMinimumHeight(40)
        self.btn_guardar.setStyleSheet(
            "QPushButton { background-color: #1B2B4E; color: white; border: none; border-radius: 12px;"
            " font-weight: 800; font-size: 13px; } QPushButton:hover { background-color: #26396A; }"
            " QPushButton:disabled { background-color: #C5CCDA; }")
        self.btn_guardar.clicked.connect(self.guardar.emit)
        lay_lat.addWidget(self.btn_guardar)
        cuerpo.addWidget(lateral)
        raiz.addLayout(cuerpo, 1)

    @staticmethod
    def _etiqueta(texto):
        lbl = QLabel(texto)
        lbl.setStyleSheet("color: #6B7A90; font-size: 11px; font-weight: 700; background: transparent;")
        return lbl

    def _par(self, titulo, layout):
        layout.addWidget(self._etiqueta(titulo))
        valor = QLabel("—")
        valor.setWordWrap(True)
        valor.setStyleSheet("color: #0F1B33; font-size: 13px; font-weight: 700; background: transparent;")
        layout.addWidget(valor)
        return valor

    @staticmethod
    def _tile(titulo, layout):
        caja = QFrame()
        caja.setObjectName("tileFM")
        caja.setStyleSheet("QFrame#tileFM { background: #F7F8FC; border: 1px solid #E3E8F0; border-radius: 12px; }")
        lay = QVBoxLayout(caja)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)
        t = QLabel(titulo)
        t.setStyleSheet("color: #6B7A90; font-size: 11px; font-weight: 600; background: transparent; border: none;")
        v = QLabel("—")
        v.setStyleSheet("color: #0F1B33; font-size: 22px; font-weight: 800; background: transparent; border: none;")
        lay.addWidget(t)
        lay.addWidget(v)
        layout.addWidget(caja, 1)
        return v

    # --------------------------------------------------------------- datos
    def cargar(self, registro, df_unidades, uf, nivel, civ, periodo_texto):
        self._registro = registro
        self._uf = uf or 0.0
        self._cantidad = int(registro["UNIDADES"])
        self._df_unidades = df_unidades
        self.lbl_empresa.setText(registro["CLIENTE"])
        self.lbl_sub.setText(f"Editor de facturación manual · {periodo_texto}")
        self.lbl_cliente.setText(registro["CLIENTE"])
        self.lbl_rut.setText(fm_service.formatear_rut(registro["RUT"]))
        for w in (self.combo_nivel, self.chk_civ, self.input_precio, self.combo_tipo):
            w.blockSignals(True)
        self.combo_tipo.setCurrentIndex(max(0, self.combo_tipo.findData(registro["TIPO"])))
        self.combo_nivel.setCurrentIndex(max(0, self.combo_nivel.findData(nivel)))
        self.chk_civ.setChecked(civ and self.nivel() != "BASICO")
        self.chk_civ.setEnabled(self.nivel() != "BASICO")
        precio = _valor_o_none(registro["PRECIO"])
        self.input_precio.setText("" if precio is None else _precio_texto(precio))
        for w in (self.combo_nivel, self.chk_civ, self.input_precio, self.combo_tipo):
            w.blockSignals(False)
        self.lbl_por_unidades.setText(f"× {self._cantidad} {'unidad' if self._cantidad == 1 else 'unidades'}")
        self.lbl_uf_dia.setText(f"UF del día: ${_num(self._uf)}" if self._uf > 0 else "UF del día no disponible")
        n_pf = len(df_unidades)
        self.lbl_cuenta.setText(str(n_pf))
        aviso = aviso_registro(registro)
        self.lbl_aviso.setText(aviso)
        self.lbl_aviso.setVisible(bool(aviso))
        self._refrescar()

    def _al_cambiar_nivel(self, *_args):
        basico = self.nivel() == "BASICO"
        if basico:
            self.chk_civ.setChecked(False)
        self.chk_civ.setEnabled(not basico)
        self.chk_civ.setToolTip("El plan Básico no admite CIV" if basico else "")
        self._refrescar()

    def precio(self):
        return fm_service.parsear_precio(self.input_precio.text())

    def nivel(self):
        return self.combo_nivel.currentData()

    def tipo(self):
        return self.combo_tipo.currentData() or ""

    def valor_plan(self):
        """Valor de TIPO DE SERVICIO en PruebasFM (ej. 'MEDIO + CIV')."""
        return self.nivel() + (" + CIV" if self.chk_civ.isChecked() else "")

    def plan_texto(self):
        return self.combo_nivel.currentText() + (" + CIV" if self.chk_civ.isChecked() else "")

    def totales(self):
        return fm_service.calcular_totales(self.precio(), self._cantidad, self._uf)

    def _refrescar(self, *_args):
        if self._registro is None:
            return
        precio = self.precio()
        neto_uf, neto_clp = self.totales()
        pago_guardado = _valor_o_none(self._registro["PAGO"])
        self.val_unidades.setText(str(self._cantidad))
        if neto_uf is None:
            self.val_neto_uf.setText("—")
            self.val_neto_clp.setText(_clp(pago_guardado) if pago_guardado is not None else "—")
            self.lbl_total_uf.setText("0,00 UF")
            self.lbl_total_clp.setText(f"{_clp(pago_guardado)} CLP (registrado)" if pago_guardado is not None else "$0 CLP")
        else:
            self.val_neto_uf.setText(_num(neto_uf))
            self.val_neto_clp.setText(_clp(neto_clp) if neto_clp is not None else "—")
            self.lbl_total_uf.setText(f"{_num(neto_uf)} UF")
            self.lbl_total_clp.setText(f"{_clp(neto_clp)} CLP" if neto_clp is not None else "UF no disponible")
        self.btn_guardar.setEnabled(precio is not None and neto_clp is not None and bool(self.tipo()))
        vins = self._df_unidades["VIN"].astype(str).tolist() if "VIN" in self._df_unidades.columns else []
        ids = self._df_unidades["ID"].astype(str).tolist() if "ID" in self._df_unidades.columns else ["-"] * len(vins)
        filas = [
            [self._registro["CLIENTE"], fm_service.formatear_rut(self._registro["RUT"]), str(i), str(v), self.plan_texto(),
             _precio_texto(precio)]
            for v, i in zip(vins, ids)
        ]
        self.modelo.set_data(pd.DataFrame(filas, columns=_COLUMNAS_UNIDADES_EDITOR))
        anchos = {"FLOTA": 300, "RUT": 130, "N° CONTRATO": 110, "VIN": 190, "PLAN": 130, "PRECIO UF": 110}
        for i, col in enumerate(_COLUMNAS_UNIDADES_EDITOR):
            self.tabla.setColumnWidth(i, anchos[col])

    def _on_doble_clic(self, index):
        df = self.modelo.get_df()
        if df.empty or not (0 <= index.row() < len(df)):
            return
        self.unidad_doble_clic.emit(str(df.iat[index.row(), df.columns.get_loc("VIN")]))


class FacturacionManualModule(GuardadoUnidadesMixin, PantallaIngresosBase):
    """Pantalla 'Facturación Manual' (Ingresos y Conciliación): lista de las
    empresas a facturar en un período (desde facturacionManual.xlsx), con
    KPIs, etapa de gestión editable en lote y, al abrir una empresa, el
    editor de su flota (precio UF, total con la UF del día y PDF).

    Las unidades de cada flota salen de PruebasFM (TIPO DE FACTURACION =
    Facturación Manual) por RUT. Desde el 05-10-2026; el diseño anterior era
    una lista de tarjetas sin datos de precios."""

    MODULO_LOG = "Facturación Manual"
    AVATAR = "FM"
    TITULO = "Facturación Manual"
    KPI_SPECS = _KPI_SPECS
    CAMPOS_FICHA = [
        ("Tipo", COL_TIPO_FM), ("Etapa de gestión", COL_ETAPA_FM), ("Unidades", COL_UNIDADES_FM),
        ("Precio unitario (UF)", COL_PRECIO_FM), ("Pago (CLP)", COL_PAGO_FM), ("Período", COL_PERIODO_FM),
    ]
    COL_CLAVE = COL_CLAVE_FM
    COL_EMPRESA = COL_CLIENTE
    COLUMNAS_OCULTAS = (COL_CLAVE_FM,)
    COL_COPIA = COL_RUT_FM
    ETIQUETA_COPIA = "RUT"
    MOSTRAR_VIN_FICHA = False
    SELECCION_EN_NIVEL_1 = True
    ANCHOS_EMPRESAS = {COL_CLIENTE: 420, COL_RUT_FM: 140, COL_TIPO_FM: 160, COL_UNIDADES_FM: 120,
                       COL_PRECIO_FM: 130, COL_PAGO_FM: 150, COL_ETAPA_FM: 140}
    ANCHOS_DETALLE = ANCHOS_EMPRESAS

    def __init__(self):
        super().__init__()
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.search_input = QLineEdit()
        self.search_input.hide()
        self.search_input.textChanged.connect(self.filter_table)
        self.df_registros = pd.DataFrame(columns=fm_service.COLUMNAS_REGISTROS_FM)
        self.df_filtrado = pd.DataFrame()
        self.filtro_periodo = ""
        self.filtro_tipo = ""
        self.filtro_etapa = ""
        self.current_kpi_filter = "empresas"
        self._data_dirty = False
        self._mtime = None
        self._ruta = ""

        self.data_manager.data_ready.connect(self._on_global_data_ready)
        self._setup_ui()
        self.load_data()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        self.construir_base()

        self.combo_periodo = ComboFiltroBarra('fa5s.calendar-alt', "Período")
        self.combo_tipo = ComboFiltroBarra('fa5s.file-invoice', "Tipo")
        self.combo_etapa = ComboFiltroBarra('fa5s.tasks', "Etapa de gestión")
        self.combo_tipo.addItem("Todos los tipos", "")
        self.combo_tipo.addItem("OC", fm_service.TIPO_OC)
        self.combo_tipo.addItem("Factura manual", fm_service.TIPO_FACTURA_MANUAL)
        self.combo_etapa.addItem("Todas las etapas", "")
        self.combo_etapa.addItem("Pendiente", "PENDIENTE")
        self.combo_etapa.addItem("Facturado", fm_service.ETAPA_FACTURADO)
        self.combo_etapa.addItem("Sin registro del mes", "SIN_REGISTRO")
        for combo, ancho in ((self.combo_periodo, 170), (self.combo_tipo, 160), (self.combo_etapa, 170)):
            combo.setMinimumWidth(ancho)
            ThemeManager.apply_combo_box(combo)
            combo.setStyleSheet(estilo_combo_barra())
            combo.setMaxVisibleItems(9)
            combo.currentIndexChanged.connect(self._on_filtro_cambiado)
            self.agregar_filtro(combo)

        self.btn_export_excel = boton_barra("Excel", 'fa5s.file-excel', 'excel')
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='#1B2B4E'))
        self.btn_export_excel.clicked.connect(lambda: self.table_export.export_to_excel("Reporte_Facturacion_Manual"))
        self.agregar_blanco(self.btn_export_excel)

        self.btn_reload = boton_barra("", 'fa5s.sync-alt')
        self.btn_reload.setToolTip("Recargar")
        self.btn_reload.clicked.connect(self.recargar)
        self.agregar_capsula(self.btn_reload)

        self.table_export = AppTableWidget()
        self.model_export = PandasTableModel()
        self.table_export.setModel(self.model_export)

        self.btn_abrir_editor = estilo_com.BotonAccionPanel(
            'fa5s.edit', 'Abrir editor', "Revisa la flota, define el precio UF y genera el PDF.", BRAND_BLUE)
        self.btn_abrir_editor.setEnabled(False)
        self.btn_abrir_editor.clicked.connect(self._on_abrir_editor_clicado)
        self.agregar_accion_panel(self.btn_abrir_editor)
        self.btn_facturado = estilo_com.BotonAccionPanel(
            'fa5s.check-circle', 'Marcar como Facturado', "Aplica a todas las empresas seleccionadas.", "#16A34A")
        self.btn_facturado.clicked.connect(lambda: self._marcar_etapa(fm_service.ETAPA_FACTURADO))
        self.agregar_accion_panel(self.btn_facturado)
        self.btn_pendiente = estilo_com.BotonAccionPanel(
            'fa5s.clock', 'Marcar como Pendiente', "Aplica a todas las empresas seleccionadas.", "#4338CA")
        self.btn_pendiente.clicked.connect(lambda: self._marcar_etapa(fm_service.ETAPA_PENDIENTE))
        self.agregar_accion_panel(self.btn_pendiente)

        self.tabla.doubleClicked.connect(self._on_doble_clic_lista)
        self.tabla.frozen_view.doubleClicked.connect(self._on_doble_clic_lista)

        self.editor = EditorFacturacion()
        self.editor.volver.connect(self.ir_a_lista_empresas)
        self.editor.guardar.connect(self._guardar_facturacion)
        self.editor.exportar_pdf.connect(self._exportar_pdf)
        self.editor.unidad_doble_clic.connect(lambda vin: self.editar_y_guardar_unidad(vin, PESTANA_JUSTTIME_CM))
        self.editor.hide()
        self.layout().addWidget(self.editor, 1)

    # --------------------------------------------- ganchos de la pantalla base
    def resolver_color(self, columna, valor, es_fondo):
        texto = str(valor).strip().upper()
        if columna == COL_TIPO_FM:
            colores = _CHIP_TIPO.get(texto)
        elif columna == COL_ETAPA_FM:
            colores = _CHIP_ETAPA.get(texto)
        elif columna == COL_UNIDADES_FM:
            colores = _CHIP_EMPRESA
        else:
            return None
        return colores[0 if es_fondo else 1] if colores else None

    def colores_chip_ficha(self, columna, valor):
        if columna == COL_TIPO_FM:
            return _CHIP_TIPO.get(str(valor).strip().upper())
        if columna == COL_ETAPA_FM:
            return _CHIP_ETAPA.get(str(valor).strip().upper())
        return None

    def _on_click_celda(self, index):
        """La lista solo selecciona; el editor se abre con doble clic o con el
        botón del panel."""

    def on_kpi_clicado(self, clave):
        self.current_kpi_filter = "empresas" if self.current_kpi_filter == clave or clave == "empresas" else clave
        self.filter_table()

    def _on_filtro_cambiado(self, _i):
        self.filtro_periodo = self.combo_periodo.currentData() or ""
        self.filtro_tipo = self.combo_tipo.currentData() or ""
        self.filtro_etapa = self.combo_etapa.currentData() or ""
        self.filter_table()

    def on_fila_cambiada(self, fila, cantidad):
        if cantidad == 0:
            for btn in (self.btn_abrir_editor, self.btn_facturado, self.btn_pendiente):
                btn.setEnabled(False)
            return
        aviso = aviso_registro(fila["_REGISTRO"]) if "_REGISTRO" in fila else ""
        self._pintar_panel(fila, cantidad, aviso)
        self._lbl_titulo_panel.setText("Empresa seleccionada" if cantidad == 1 else f"{cantidad} empresas seleccionadas")
        self.btn_abrir_editor.setEnabled(cantidad == 1)
        self.btn_facturado.setEnabled(True)
        self.btn_pendiente.setEnabled(True)

    # ------------------------------------------------------------------ datos
    def _ruta_excel(self):
        return config.settings.FACTURACION_MANUAL_PATH

    def load_data(self):
        self._data_dirty = False
        self._ruta = self._ruta_excel()
        try:
            self._mtime = os.path.getmtime(self._ruta) if self._ruta and os.path.exists(self._ruta) else None
            self.df_registros = fm_service.leer_registros_fm(self._ruta)
        except Exception as e:
            logger.error(f"No se pudo leer facturacionManual.xlsx: {e}")
            self.df_registros = pd.DataFrame(columns=fm_service.COLUMNAS_REGISTROS_FM)
        self.df_filtrado = fm_service.filtrar_facturacion_manual(self.data_manager.df_master)
        self._poblar_periodos()
        self.filter_table()

    def _claves_periodos(self):
        claves = set(fm_service.periodos_disponibles(self.df_registros))
        claves.add(fm_service.periodo_anterior())
        return sorted(claves, reverse=True)

    def _poblar_periodos(self):
        claves = self._claves_periodos()
        previo = self.combo_periodo.currentData() or ""
        self.combo_periodo.blockSignals(True)
        self.combo_periodo.clear()
        for clave in claves:
            self.combo_periodo.addItem(fm_service.etiqueta_periodo(clave), clave)
        idx = self.combo_periodo.findData(previo) if previo else -1
        if idx < 0:
            idx = self.combo_periodo.findData(fm_service.periodo_por_defecto(claves))
        self.combo_periodo.setCurrentIndex(max(0, idx))
        self.combo_periodo.blockSignals(False)
        self.filtro_periodo = self.combo_periodo.currentData() or ""

    def _seleccionar_periodo_reciente(self):
        claves = self._claves_periodos()
        idx = self.combo_periodo.findData(fm_service.periodo_por_defecto(claves))
        if idx >= 0 and idx != self.combo_periodo.currentIndex():
            self.combo_periodo.blockSignals(True)
            self.combo_periodo.setCurrentIndex(idx)
            self.combo_periodo.blockSignals(False)
            self.filtro_periodo = self.combo_periodo.currentData() or ""
            return True
        return False

    def recargar(self):
        self.data_manager.load_data_async()
        self.load_data()

    def refresh_if_dirty(self):
        cambio_archivo = False
        try:
            ruta = self._ruta_excel()
            mtime = os.path.getmtime(ruta) if ruta and os.path.exists(ruta) else None
            cambio_archivo = ruta != self._ruta or mtime != self._mtime
        except OSError:
            pass
        if self._data_dirty or cambio_archivo:
            self.load_data()
        elif self.empresa_actual is None and self._seleccionar_periodo_reciente():
            self.filter_table()

    def _on_global_data_ready(self):
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def _alcance_periodo(self):
        if not self.filtro_periodo:
            return pd.DataFrame(columns=fm_service.COLUMNAS_REGISTROS_PERIODO)
        incluir_sin_registro = self.filtro_periodo == fm_service.periodo_por_defecto(self._claves_periodos())
        df = fm_service.armar_registros_periodo(self.df_registros, self.df_filtrado, self.filtro_periodo,
                                                incluir_sin_registro)
        texto = self.search_input.text().strip().lower()
        if texto:
            mascara = df["CLIENTE"].str.lower().str.contains(texto, regex=False) | \
                df["RUT"].str.lower().str.contains(texto, regex=False)
            df = df[mascara]
        return df

    def filter_table(self):
        if self.empresa_actual is not None:
            return
        base = self._alcance_periodo()
        empresas = len(base)
        unidades = int(base["UNIDADES"].sum()) if not base.empty else 0
        pendientes = int(self._es_pendiente(base).sum()) if not base.empty else 0
        pago = float(base["PAGO"].fillna(0).sum()) if not base.empty else 0.0
        valores = {
            "empresas": (empresas, 1.0 if empresas else 0.0, "con unidades por facturar"),
            "unidades": (unidades, None, f"promedio {_num(unidades / empresas, 1) if empresas else '0'} por empresa"),
            "pendiente": (pendientes, (pendientes / empresas) if empresas else 0.0, "etapa de gestión pendiente"),
            "pago": (_clp(pago), None, "suma de los pagos registrados"),
        }
        for clave, tarjeta in self.botones_kpi.items():
            valor, porcentaje, pie = valores[clave]
            tarjeta.setChecked(clave == self.current_kpi_filter and clave != "empresas")
            tarjeta.actualizar(valor, porcentaje, pie)

        df = base
        if self.filtro_tipo:
            df = df[df["TIPO"] == self.filtro_tipo]
        etapa = self.filtro_etapa or ("PENDIENTE" if self.current_kpi_filter == "pendiente" else "")
        if etapa == "PENDIENTE":
            df = df[self._es_pendiente(df)]
        elif etapa == "SIN_REGISTRO":
            df = df[df["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM]
        elif etapa:
            df = df[(df["ETAPA"] == etapa) & (df["ORIGEN"] == fm_service.ORIGEN_EXCEL)]
        df = df.sort_values("CLIENTE", kind="mergesort")

        self._armar_tabla(df)
        self.lbl_subtitulo.setText(self._texto_subtitulo(df))
        self.lbl_sin_resultados.setVisible(self._df_tabla.empty)
        self._pintar_tabla()

    @staticmethod
    def _es_pendiente(df):
        """Etapa Pendiente o empresa sin fila del mes (aún no se factura)."""
        return (df["ETAPA"] == fm_service.ETAPA_PENDIENTE) | (df["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM)

    def _texto_subtitulo(self, df):
        uf = self._uf_vigente()
        texto = f"{len(df)} empresas · {int(df['UNIDADES'].sum()) if not df.empty else 0} unidades"
        return f"{texto} · UF ${_num(uf)}" if uf > 0 else texto

    def _uf_vigente(self):
        try:
            return float(self.data_manager.get_variables()[0] or 0)
        except (TypeError, ValueError, IndexError, AttributeError):
            return 0.0

    def _armar_tabla(self, df):
        self._fila_por_vin = {}
        if df.empty:
            self._df_tabla = pd.DataFrame(columns=_COLUMNAS_LISTA)
            self.model_export.set_data(pd.DataFrame())
            return
        filas = []
        for r in df.to_dict("records"):
            clave = f"{fm_service.clave_periodo(r['PERIODO'])}|{r['RUT']}|{r['CLIENTE']}"
            precio = _valor_o_none(r["PRECIO"])
            pago = _valor_o_none(r["PAGO"])
            sin_registro = r["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM
            fila = {
                COL_CLAVE_FM: clave, COL_CLIENTE: r["CLIENTE"], COL_RUT_FM: fm_service.formatear_rut(r["RUT"]),
                COL_TIPO_FM: _TIPOS_TEXTO.get(r["TIPO"], r["TIPO"] or "—"), COL_UNIDADES_FM: str(r["UNIDADES"]),
                COL_PRECIO_FM: _precio_texto(precio), COL_PAGO_FM: _clp(pago) if pago is not None else "—",
                COL_ETAPA_FM: "Sin registro" if sin_registro else (r["ETAPA"] or "—"),
            }
            filas.append(fila)
            ficha = dict(fila)
            ficha[COL_RAZON_SOCIAL] = r["CLIENTE"]
            ficha[COL_PERIODO_FM] = fm_service.etiqueta_periodo(fm_service.clave_periodo(r["PERIODO"]))
            ficha["_REGISTRO"] = r
            ficha["_ENTRADA"] = f"{r['RUT']}|{r['CLIENTE']}"
            self._fila_por_vin[clave] = ficha
        self._df_tabla = pd.DataFrame(filas, columns=_COLUMNAS_LISTA)
        self.model_export.set_data(self._df_tabla.drop(columns=[COL_CLAVE_FM]))

    # ------------------------------------------------------------ navegación
    def al_cambiar_nivel(self):
        en_editor = self.empresa_actual is not None
        self._kpi_oculto_por_pantalla = en_editor
        self.aplicar_visibilidad_kpi(en_editor)
        self._contenido.setVisible(not en_editor)
        self.editor.setVisible(en_editor)
        self._mostrar_panel(False)
        if not en_editor:
            self.filter_table()
            return
        registro = self._registro_actual()
        if registro is None:
            self.ir_a_lista_empresas()
            return
        unidades = fm_service.unidades_de_rut(self.df_filtrado, registro["RUT"])
        nivel, civ = fm_service.nivel_servicio_dominante(unidades)
        self.editor.cargar(registro, unidades, self._uf_vigente(), nivel, civ,
                           fm_service.etiqueta_periodo(self.filtro_periodo))

    def _registro_actual(self):
        base = self._alcance_periodo()
        if base.empty or self.empresa_actual is None:
            return None
        rut, _, cliente = self.empresa_actual.partition("|")
        coincide = base[(base["RUT"] == rut) & (base["CLIENTE"] == cliente)]
        return coincide.iloc[0].to_dict() if not coincide.empty else None

    def _on_abrir_editor_clicado(self):
        claves = self._vins_seleccionados()
        if len(claves) == 1:
            self._ir_a(self._fila_por_vin[claves[0]]["_ENTRADA"])

    def _on_doble_clic_lista(self, index):
        if self.empresa_actual is not None:
            return
        df = self.modelo.get_df()
        if df.empty or not (0 <= index.row() < len(df)):
            return
        ficha = self._fila_por_vin.get(str(df.iat[index.row(), df.columns.get_loc(COL_CLAVE_FM)]))
        if ficha:
            self._ir_a(ficha["_ENTRADA"])

    # ------------------------------------------------------------- acciones
    def _marcar_etapa(self, etapa):
        claves = self._vins_seleccionados()
        cambios, nuevas = [], []
        for clave in claves:
            r = self._fila_por_vin[clave]["_REGISTRO"]
            if r["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM:
                nuevas.append({"periodo": fm_service.clave_periodo(r["PERIODO"]),
                               "valores": self._valores_fila_nueva(r, {"etapa": etapa})})
            elif r["ETAPA"] != etapa:
                cambios.append({"fila": int(r["FILA"]), "cliente": r["CLIENTE"],
                                "periodo": fm_service.clave_periodo(r["PERIODO"]), "valores": {"etapa": etapa}})
        if not cambios and not nuevas:
            QMessageBox.information(self, "Sin cambios", f"Las empresas seleccionadas ya están como {etapa}.")
            return
        ok, mensaje = fm_service.guardar_registros_fm(self._ruta, cambios, nuevas)
        if not ok:
            QMessageBox.critical(self, "No se pudo guardar", mensaje)
            return
        self.load_data()

    @staticmethod
    def _valores_fila_nueva(r, extra):
        """Celdas de una fila nueva del Excel para una empresa que solo existía
        en PruebasFM."""
        rut = r["RUT"]
        valores = {"cliente": r["CLIENTE"], "rut": int(rut) if rut.isdigit() else rut,
                   "unidades": int(r["UNIDADES"])}
        if r["TIPO"]:
            valores["tipo"] = r["TIPO"]
        valores.update(extra)
        return valores

    def _guardar_facturacion(self):
        registro = self._registro_actual()
        precio = self.editor.precio()
        neto_uf, neto_clp = self.editor.totales()
        if registro is None or precio is None or neto_clp is None:
            return
        nueva = registro["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM
        pregunta = QMessageBox.question(
            self, "Guardar facturación",
            f"Se {'creará la fila del mes' if nueva else 'guardará'} para {registro['CLIENTE']}:\n\n"
            f"• Tipo: {_TIPOS_TEXTO.get(self.editor.tipo(), self.editor.tipo())}\n"
            f"• Precio unitario: {_precio_texto(precio)} UF × {int(registro['UNIDADES'])} unidades\n"
            f"• Total: {_num(neto_uf)} UF = {_clp(neto_clp)}\n"
            f"• Plan de la flota: {self.editor.valor_plan()}\n\n"
            "En facturacionManual.xlsx y el plan en RM_CONTRATOS (con copia de seguridad).")
        if pregunta != QMessageBox.StandardButton.Yes:
            return
        valores = {"precio": precio, "pago": neto_clp, "tipo": self.editor.tipo()}
        if nueva:
            ok, mensaje = fm_service.guardar_registros_fm(self._ruta, [], [{
                "periodo": fm_service.clave_periodo(registro["PERIODO"]),
                "valores": self._valores_fila_nueva(registro, {**valores, "etapa": fm_service.ETAPA_PENDIENTE})}])
        else:
            if registro["ETAPA"] != fm_service.ETAPA_FACTURADO:
                valores["unidades"] = int(registro["UNIDADES"])
            ok, mensaje = fm_service.guardar_registros_fm(self._ruta, [{
                "fila": int(registro["FILA"]), "cliente": registro["CLIENTE"],
                "periodo": fm_service.clave_periodo(registro["PERIODO"]), "valores": valores}])
        if not ok:
            QMessageBox.critical(self, "No se pudo guardar", mensaje)
            return
        self.ir_a_lista_empresas()
        self.load_data()
        self._aplicar_plan_a_unidades()

    def _aplicar_plan_a_unidades(self):
        """Escribe el plan elegido en TIPO DE SERVICIO de las unidades de la
        flota que aún tengan otro valor (PruebasFM)."""
        unidades = self.editor._df_unidades
        if unidades.empty or "VIN" not in unidades.columns or fm_service.COL_TIPO_SERVICIO not in unidades.columns:
            return
        plan = self.editor.valor_plan()
        lote = {}
        for vin, actual in zip(unidades["VIN"].astype(str), unidades[fm_service.COL_TIPO_SERVICIO].astype(str)):
            vin = vin.strip().upper()
            if vin and actual.strip().upper() != plan:
                lote[vin] = {"VIN": vin, "cambios": {fm_service.COL_TIPO_SERVICIO: plan}}
        if lote:
            self.guardar_lote_unidades(lote, "Actualizando el plan de la flota…")

    def _exportar_pdf(self):
        registro = self._registro_actual()
        precio = self.editor.precio()
        neto_uf, neto_clp = self.editor.totales()
        if registro is None:
            return
        if precio is None:
            QMessageBox.information(self, "Falta el precio", "Ingresa el precio UF por unidad para generar el PDF.")
            return
        periodo = registro["PERIODO"]
        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF", os.path.join(carpeta, fm_pdf.nombre_sugerido(registro["CLIENTE"], periodo.year, periodo.month)),
            "PDF (*.pdf)")
        if not ruta:
            return
        unidades = self.editor._df_unidades
        vins = unidades["VIN"].astype(str).tolist() if "VIN" in unidades.columns else []
        rut = fm_service.formatear_rut(registro["RUT"])
        try:
            fm_pdf.generar_pdf(ruta, {
                "cliente": registro["CLIENTE"], "anio": periodo.year, "mes": periodo.month,
                "fecha_emision": fm_pdf.fecha_emision(), "uf": self._uf_vigente(),
                "unidades_n": int(registro["UNIDADES"]), "neto_uf": neto_uf, "neto_clp": neto_clp,
                "filas": [(registro["CLIENTE"], rut, v, self.editor.plan_texto(), precio) for v in vins],
            })
        except Exception as e:
            QMessageBox.critical(self, "No se pudo generar el PDF", str(e))
            return
        return
