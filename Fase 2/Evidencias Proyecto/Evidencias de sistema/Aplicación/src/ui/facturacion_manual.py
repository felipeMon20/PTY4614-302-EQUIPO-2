import logging
import os
import time

import pandas as pd
from PyQt6.QtCore import Qt, QStandardPaths, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator
from PyQt6.QtCore import QRegularExpression
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit,
                             QMessageBox, QComboBox, QCheckBox, QFileDialog, QApplication, QSizePolicy)

import config.settings
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.constants import COL_RAZON_SOCIAL, COL_VIN
from src.services import facturacion_manual_service as fm_service
from src.services import provisiones_services
from src.ui import comercial_estilo as estilo_com
from src.ui import facturacion_manual_pdf as fm_pdf
from src.ui import facturacion_manual_excel as fm_excel
from src.ui.facturacion_mes_panel import PanelFacturacionMes
from src.ui.custom_table import VolvoTableWidget, PandasTableModel
from src.ui.formulario_unidad import GuardadoUnidadesMixin, PESTANA_JUSTTIME_CM
from src.ui.selector_fecha import _CHEVRON
from src.ui.ingresos_base import (PantallaIngresosBase, ModeloTablaIngresos, ComboFiltroBarra, boton_barra,
                                  estilo_combo_barra, aplicar_estilo_tabla_lectura)
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *

logger = logging.getLogger(__name__)

COL_CLAVE_FM = "_CLAVE"
COL_CLIENTE = "FLOTA VC"
COL_RUT_FM = "RUT"
COL_TIPO_FM = "TIPO"
COL_UNIDADES_FM = "UNIDADES"
COL_PRECIO_FM = "PRECIO UF"
COL_PAGO_FM = "PAGO CLP"
COL_ETAPA_FM = "ETAPA"
COL_PERIODO_FM = "PERÍODO"

COL_RAZONES_FM = "RAZONES SOCIALES"

_COLUMNAS_LISTA = [COL_CLAVE_FM, COL_CLIENTE, COL_RAZONES_FM, COL_UNIDADES_FM, COL_ETAPA_FM]
_COLUMNAS_UNIDADES_EDITOR = ["RAZÓN SOCIAL", "RUT", "N° CONTRATO", "VIN", "PLAN", "PRECIO UF"]

_KPI_SPECS = [
    ("Flotas con facturación manual", "empresas", "#0F766E", "Flotas con unidades por facturar en el período."),
    ("Unidades en facturación manual", "unidades", "#1F6FEB", "Suma de unidades de las flotas del período."),
    ("Pendiente por facturar", "pendiente", "#4338CA", "Flotas con etapa de gestión Pendiente."),
    ("Pago total facturación", "pago", VOLVO_BLUE, "Suma del pago registrado de las flotas del período."),
]

_TIPOS_TEXTO = {fm_service.TIPO_OC: "OC", fm_service.TIPO_FACTURA_MANUAL: "Factura manual"}
_CHIP_TIPO = {"OC": ("#E1EAF4", VOLVO_BLUE), "FACTURA MANUAL": ("#CCFBF1", "#115E59")}
_CHIP_ETAPA = {"PENDIENTE": ("#FEF3C7", "#92400E"), "FACTURADO": ("#D1FAE5", "#065F46"),
              "SIN REGISTRO": ("#FEE2E2", "#991B1B")}
_CHIP_ETAPA["PARCIAL"] = ("#FFEDD5", "#9A3412")
_CHIP_VOLVO = ("#E1EAF4", VOLVO_BLUE)


def _chip_etapa(valor):
    texto = str(valor).strip().upper()
    return _CHIP_ETAPA.get("PARCIAL" if texto.startswith("PARCIAL") else texto)
_NIVELES = [("BASICO", "BÁSICO"), ("MEDIO", "MEDIO"), ("FULL", "FULL")]

_QSS_COMBO_EDITOR = f"""
    QComboBox[class="combo_box"] {{
        background-color: #FFFFFF; border: 1px solid #DCE3EC; border-radius: 8px;
        padding: 6px 10px; color: #0F1B33; font-weight: 500; font-size: 13px; combobox-popup: 0;
    }}
    QComboBox[class="combo_box"]:hover {{ border: 1px solid #B9C6DA; }}
    QComboBox[class="combo_box"]:focus, QComboBox[class="combo_box"]:on {{ border: 1px solid #1B2B4E; }}
    QComboBox[class="combo_box"]:disabled {{ background-color: #F5F7FA; color: #8A97AB; border: 1px solid #E3E8F0; }}
    QComboBox[class="combo_box"]::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right; width: 26px;
        border-left: 1px solid #E3E8F0; border-top-right-radius: 7px; border-bottom-right-radius: 7px;
        background-color: #F7F8FC;
    }}
    QComboBox[class="combo_box"]::down-arrow {{
        image: url({_CHEVRON.replace(chr(92), '/')}); width: 11px; height: 11px;
    }}
"""
_QSS_CHECK_EDITOR = (
    "QCheckBox { background: transparent; border: none; color: #0F1B33; font-weight: 600; spacing: 8px; }"
    "QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid #66748D; border-radius: 5px; background: #FFFFFF; }"
    "QCheckBox::indicator:hover { border-color: #1B2B4E; }"
    "QCheckBox::indicator:checked { background-color: #1B2B4E; border-color: #1B2B4E; }"
)
_QSS_BOTON_GUARDAR_EDITOR = (
    "QPushButton { background-color: #1B2B4E; color: white; border: 1px solid #1B2B4E; padding: 0 20px;"
    " min-height: 40px; border-radius: 8px; font-weight: 600; font-size: 13px; }"
    " QPushButton:hover { background-color: #2B3D63; border-color: #2B3D63; }"
    " QPushButton:pressed { background-color: #15213D; }"
    " QPushButton:disabled { background-color: #A9B4C6; border-color: #A9B4C6; }")


def _pastilla_check(chk):
    """CIV/SZ dentro de una pastilla, como en el formulario de Comercial."""
    chk.setCursor(Qt.CursorShape.PointingHandCursor)
    chk.setStyleSheet(_QSS_CHECK_EDITOR)
    pastilla = QFrame()
    pastilla.setObjectName("pastillaServicioFM")
    pastilla.setStyleSheet(
        "QFrame#pastillaServicioFM { background-color: #EEF2F6; border: 1px solid #DCE3EC; border-radius: 13px; }")
    lay = QHBoxLayout(pastilla)
    lay.setContentsMargins(8, 3, 8, 3)
    lay.setSpacing(0)
    lay.addWidget(chk)
    pastilla.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    pastilla.setMinimumWidth(chk.sizeHint().width() + 16)
    return pastilla


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
                "de RM_JAVI. Complétalo en el Excel y recarga.")
    if r["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM:
        return ("Flota con unidades en Facturación Manual en RM_JAVI y sin fila de este mes en "
                "facturacionManual.xlsx. Se crea una fila por RUT al guardar el precio o al marcar la etapa.")
    en_pf, en_excel = int(r["UNIDADES_PF"]), int(r["UNIDADES_EXCEL"])
    if en_pf == 0:
        return "RM_JAVI no tiene unidades con facturación manual para este RUT."
    if en_pf != en_excel and r["ETAPA"] == fm_service.ETAPA_FACTURADO:
        return (f"Mes ya facturado: se mantienen las {en_excel} unidades del Excel. "
                f"RM_JAVI tiene hoy {en_pf}.")
    return ""


def puede_ajustar_a_rm(r):
    """True si la razón está facturada con unidades distintas a las de RM_JAVI (y RM_JAVI tiene)."""
    return (bool(r["RUT"]) and r["ORIGEN"] != fm_service.ORIGEN_PRUEBASFM
            and r["ETAPA"] == fm_service.ETAPA_FACTURADO
            and 0 < int(r["UNIDADES_PF"]) != int(r["UNIDADES_EXCEL"]))


def armar_datos_documento(registro, df_unidades, plan, precio, uf, uf_facturada, cantidad, precio_fijo=None):
    """Datos de una razón social para el PDF y el Excel: sus unidades, el plan, el precio y
    los totales (los mismos que muestra el editor). Con `precio_fijo` (neto en CLP) no hay
    precio por unidad ni neto en UF."""
    periodo = registro["PERIODO"]
    if precio_fijo is not None:
        precio, neto_uf, neto_clp = None, None, int(precio_fijo)
    else:
        neto_uf, neto_clp = fm_service.calcular_totales(precio, cantidad, uf)
    vins = df_unidades["VIN"].astype(str).tolist() if "VIN" in df_unidades.columns else []
    ruts = df_unidades["RUT"].astype(str).tolist() if "RUT" in df_unidades.columns else ["-"] * len(vins)
    return {
        "cliente": registro["CLIENTE"], "anio": periodo.year, "mes": periodo.month,
        "fecha_emision": fm_pdf.fecha_emision(), "uf": uf,
        "uf_etiqueta": "UF de facturación" if uf_facturada else "UF hoy",
        "unidades_n": cantidad, "neto_uf": neto_uf, "neto_clp": neto_clp, "precio_uf": precio,
        "precio_fijo": precio_fijo is not None,
        "filas": [(registro["FLOTA"], fm_service.formatear_rut(rut), v, plan, precio) for v, rut in zip(vins, ruts)],
    }


def aviso_flota(flota):
    """Aviso de una flota: el primero de sus razones sociales que tenga algo que avisar."""
    for r in flota["RAZONES"]:
        aviso = aviso_registro(r)
        if aviso:
            return aviso if flota["N_RAZONES"] == 1 else f"{r['CLIENTE']}: {aviso}"
    return ""


class EditorFacturacion(QWidget):
    """Pantalla de edición de una flota: resumen de precios, detalle de
    unidades y panel lateral con nivel de servicio, precio UF y total."""

    volver = pyqtSignal()
    exportar_pdf = pyqtSignal()
    exportar_excel = pyqtSignal()
    actualizar_uf = pyqtSignal()
    guardar = pyqtSignal()
    unidad_doble_clic = pyqtSignal(str)
    razon_cambiada = pyqtSignal(str)
    ajustar_a_rm = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._registro = None
        self._uf = 0.0
        self.uf_facturada = False
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
        self.btn_excel = boton_barra("Exportar a Excel", 'fa5s.file-excel', 'excel')
        self.btn_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='#1B2B4E'))
        self.btn_excel.clicked.connect(self.exportar_excel.emit)
        fila.addWidget(self.btn_volver)
        fila.addLayout(textos)
        fila.addStretch()
        self.btn_uf = boton_barra("Actualizar UF", 'fa5s.dollar-sign', 'excel')
        self.btn_uf.setIcon(ThemeManager.icon('fa5s.dollar-sign', color='#1B2B4E'))
        self.btn_uf.clicked.connect(self.actualizar_uf.emit)
        fila.addWidget(self.btn_uf)
        fila.addWidget(self.btn_excel)
        fila.addWidget(self.btn_pdf)
        raiz.addWidget(barra)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        izquierda = QVBoxLayout()
        izquierda.setSpacing(12)

        detalle = self._tarjeta("detalleUnidadesFM")
        lay_det = QVBoxLayout(detalle)
        lay_det.setContentsMargins(1, 14, 1, 1)
        lay_det.setSpacing(8)
        cab = QHBoxLayout()
        cab.setContentsMargins(17, 0, 17, 0)
        cab.addWidget(self._titulo("DETALLE DE UNIDADES"))
        self.lbl_cuenta = QLabel("")
        self.lbl_cuenta.setStyleSheet(
            f"background: #E1EAF4; color: {VOLVO_BLUE}; border-radius: 10px; padding: 2px 10px;"
            " font-size: 11px; font-weight: 800;")
        cab.addWidget(self.lbl_cuenta)
        cab.addSpacing(10)
        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Buscar múltiples VINs o chasis (pega la lista)…")
        self.buscador.setClearButtonEnabled(True)
        self.buscador.setFixedWidth(340)
        self.buscador.setStyleSheet(
            "QLineEdit { background: white; border: 1px solid #E3E8F0; border-radius: 10px; padding: 5px 10px;"
            " font-size: 12px; color: #0F1B33; } QLineEdit:focus { border: 1px solid #1F6FEB; }")
        self.buscador.textChanged.connect(self._refrescar)
        cab.addWidget(self.buscador)
        self.lbl_busqueda = QLabel("")
        self.lbl_busqueda.hide()
        cab.addWidget(self.lbl_busqueda)
        cab.addStretch()
        self.val_unidades = self._chip_resumen("Conectadas", cab)
        self.val_neto_uf = self._chip_resumen("Neto UF", cab)
        self.val_neto_clp = self._chip_resumen("Neto CLP", cab)
        lay_det.addLayout(cab)
        self.lbl_aviso = QLabel("")
        self.lbl_aviso.setWordWrap(True)
        self.lbl_aviso.setStyleSheet(
            "background-color: #FEF2F2; color: #B91C1C; border: 1px solid #FECACA; border-radius: 10px;"
            " padding: 8px 10px; font-size: 11px; font-weight: 600; margin: 0 16px;")
        self.btn_ajustar_rm = QPushButton("Ajustar a RM")
        self.btn_ajustar_rm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ajustar_rm.setToolTip("Deja las unidades de este mes igual a las de RM_JAVI y recalcula el total con la misma UF.")
        self.btn_ajustar_rm.setStyleSheet(
            "QPushButton { background: #B91C1C; color: white; border: none; border-radius: 10px; padding: 8px 14px;"
            " font-size: 11px; font-weight: 700; } QPushButton:hover { background: #991B1B; }")
        self.btn_ajustar_rm.clicked.connect(self.ajustar_a_rm.emit)
        self.btn_ajustar_rm.hide()
        self.fila_aviso = QWidget()
        lay_aviso = QHBoxLayout(self.fila_aviso)
        lay_aviso.setContentsMargins(0, 0, 16, 0)
        lay_aviso.setSpacing(0)
        lay_aviso.addWidget(self.lbl_aviso, 1)
        lay_aviso.addWidget(self.btn_ajustar_rm)
        self.fila_aviso.hide()
        lay_det.addWidget(self.fila_aviso)

        self.tabla = VolvoTableWidget()
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
        lateral.setFixedWidth(360)
        lay_lat = QVBoxLayout(lateral)
        lay_lat.setContentsMargins(16, 14, 16, 16)
        lay_lat.setSpacing(7)
        self.lbl_cliente = QLabel("")
        self.lbl_cliente.setWordWrap(True)
        self.lbl_cliente.setStyleSheet("color: #0F1B33; font-size: 13px; font-weight: 800; background: transparent;")
        lay_lat.addWidget(self.lbl_cliente)

        lay_lat.addWidget(self._etiqueta("Razón social a facturar"))
        self.combo_razon = estilo_com.ComboTarjeta("Razón social a facturar")
        ThemeManager.apply_combo_box(self.combo_razon)
        self.combo_razon.setStyleSheet(_QSS_COMBO_EDITOR)
        self.combo_razon.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo_razon.setMinimumContentsLength(10)
        self.combo_razon.currentIndexChanged.connect(self._on_razon_elegida)
        lay_lat.addWidget(self.combo_razon)
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet("color: #6B7A90; font-size: 11px; font-weight: 600; background: transparent;")
        lay_lat.addWidget(self.lbl_info)

        fila_combos = QHBoxLayout()
        fila_combos.setSpacing(8)
        col_tipo, col_nivel = QVBoxLayout(), QVBoxLayout()
        col_tipo.setSpacing(3)
        col_nivel.setSpacing(3)
        col_tipo.addWidget(self._etiqueta("Tipo de gestión"))
        self.combo_tipo = estilo_com.ComboTarjeta("Tipo de gestión")
        self.combo_tipo.addItem("Sin definir", "")
        self.combo_tipo.addItem("OC", fm_service.TIPO_OC)
        self.combo_tipo.addItem("Factura manual", fm_service.TIPO_FACTURA_MANUAL)
        ThemeManager.apply_combo_box(self.combo_tipo)
        self.combo_tipo.setStyleSheet(_QSS_COMBO_EDITOR)
        self.combo_tipo.currentIndexChanged.connect(self._refrescar)
        col_tipo.addWidget(self.combo_tipo)
        col_nivel.addWidget(self._etiqueta("Nivel de servicio"))
        self.combo_nivel = estilo_com.ComboTarjeta("Nivel de servicio")
        for clave, texto in _NIVELES:
            self.combo_nivel.addItem(texto, clave)
        ThemeManager.apply_combo_box(self.combo_nivel)
        self.combo_nivel.setStyleSheet(_QSS_COMBO_EDITOR)
        self.combo_nivel.currentIndexChanged.connect(self._al_cambiar_nivel)
        col_nivel.addWidget(self.combo_nivel)
        fila_combos.addLayout(col_tipo, 1)
        fila_combos.addLayout(col_nivel, 1)
        lay_lat.addLayout(fila_combos)

        fila_chk = QHBoxLayout()
        fila_chk.addWidget(self._etiqueta("Complementarios"))
        fila_chk.addSpacing(8)
        self.chk_civ = QCheckBox("CIV")
        self.chk_civ.toggled.connect(self._refrescar)
        self.chk_sz = QCheckBox("SZ")
        self.chk_sz.setToolTip("Safety Zone")
        self.chk_sz.toggled.connect(self._refrescar)
        fila_chk.addWidget(_pastilla_check(self.chk_civ))
        fila_chk.addWidget(_pastilla_check(self.chk_sz))
        fila_chk.addStretch()
        lay_lat.addLayout(fila_chk)

        fila_precio = QHBoxLayout()
        fila_precio.setSpacing(8)
        fila_precio.addWidget(self._etiqueta("Precio UF"))
        self.input_precio = QLineEdit()
        self.input_precio.setPlaceholderText("0,00")
        self.input_precio.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d{0,4}([.,]\d{0,4})?$")))
        self.input_precio.setMinimumHeight(34)
        self.input_precio.textChanged.connect(self._refrescar)
        self.lbl_por_unidades = QLabel("")
        self.lbl_por_unidades.setStyleSheet("color: #6B7A90; font-size: 12px; font-weight: 800; background: transparent;")
        fila_precio.addWidget(self.input_precio, 1)
        fila_precio.addWidget(self.lbl_por_unidades)
        lay_lat.addLayout(fila_precio)

        self.chk_fijo = QCheckBox("Precio fijo (monto neto en CLP)")
        self.chk_fijo.setToolTip("El cliente paga un monto fijo al mes: se guarda ese Neto CLP y la flota queda Facturada")
        self.chk_fijo.toggled.connect(self._al_cambiar_fijo)
        lay_lat.addWidget(_pastilla_check(self.chk_fijo))
        self.fila_fijo = QWidget()
        lay_fijo = QHBoxLayout(self.fila_fijo)
        lay_fijo.setContentsMargins(0, 0, 0, 0)
        lay_fijo.setSpacing(8)
        lay_fijo.addWidget(self._etiqueta("Neto CLP"))
        self.input_fijo = QLineEdit()
        self.input_fijo.setPlaceholderText("$0")
        self.input_fijo.setValidator(QRegularExpressionValidator(QRegularExpression(r"^[\d.]{0,12}$")))
        self.input_fijo.setMinimumHeight(34)
        self.input_fijo.textChanged.connect(self._refrescar)
        lay_fijo.addWidget(self.input_fijo, 1)
        self.fila_fijo.hide()
        lay_lat.addWidget(self.fila_fijo)

        caja_total = QFrame()
        caja_total.setObjectName("totalFM")
        caja_total.setStyleSheet("QFrame#totalFM { background: #F4F7FB; border-radius: 12px; }")
        lay_tot = QVBoxLayout(caja_total)
        lay_tot.setContentsMargins(14, 8, 14, 10)
        lay_tot.setSpacing(1)
        t_total = QLabel("Total mensual")
        t_total.setStyleSheet("color: #6B7A90; font-size: 11px; font-weight: 600; background: transparent;")
        self.lbl_uf_dia = QLabel("")
        self.lbl_uf_dia.setStyleSheet("color: #6B7A90; font-size: 10px; background: transparent;")
        fila_tit = QHBoxLayout()
        fila_tit.addWidget(t_total)
        fila_tit.addStretch()
        fila_tit.addWidget(self.lbl_uf_dia)
        self.lbl_total_uf = QLabel("0,00 UF")
        self.lbl_total_uf.setStyleSheet("color: #0F1B33; font-size: 22px; font-weight: 800; background: transparent;")
        self.lbl_total_uf.setMinimumHeight(30)
        self.lbl_total_clp = QLabel("$0 CLP")
        self.lbl_total_clp.setStyleSheet(f"color: {VOLVO_BLUE}; font-size: 13px; font-weight: 700; background: transparent;")
        self.lbl_total_clp.setMinimumHeight(20)
        lay_tot.addLayout(fila_tit)
        lay_tot.addWidget(self.lbl_total_uf)
        lay_tot.addWidget(self.lbl_total_clp)
        lay_lat.addWidget(caja_total)
        lay_lat.addStretch()

        self.btn_guardar = QPushButton("Guardar facturación  →")
        self.btn_guardar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar.setMinimumHeight(40)
        self.btn_guardar.setStyleSheet(_QSS_BOTON_GUARDAR_EDITOR)
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
    def _chip_resumen(titulo, layout):
        caja = QFrame()
        caja.setObjectName("chipResumenFM")
        caja.setStyleSheet("QFrame#chipResumenFM { background: #F7F8FC; border: 1px solid #E3E8F0; border-radius: 10px; }")
        lay = QHBoxLayout(caja)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(6)
        t = QLabel(titulo)
        t.setStyleSheet("color: #6B7A90; font-size: 11px; font-weight: 600; background: transparent; border: none;")
        v = QLabel("—")
        v.setStyleSheet("color: #0F1B33; font-size: 12px; font-weight: 800; background: transparent; border: none;")
        lay.addWidget(t)
        lay.addWidget(v)
        layout.addWidget(caja)
        return v

    # --------------------------------------------------------------- datos
    def _on_razon_elegida(self, _indice):
        rut = self.combo_razon.currentData()
        if rut is not None and self._registro is not None and rut != self._registro["RUT"]:
            self.razon_cambiada.emit(rut)

    def cargar(self, registro, df_unidades, uf, nivel, civ, periodo_texto, sz=False, razones=()):
        """`razones` son las razones sociales de la flota como (RUT, texto): cada una se
        factura y se exporta por separado."""
        self._registro = registro
        self.combo_razon.blockSignals(True)
        self.combo_razon.clear()
        for rut, texto in razones:
            self.combo_razon.addItem(texto, rut)
        self.combo_razon.setCurrentIndex(max(0, self.combo_razon.findData(registro["RUT"])))
        self.combo_razon.setEnabled(len(razones) > 1)
        self.combo_razon.setToolTip(self.combo_razon.currentText())
        self.combo_razon.blockSignals(False)
        self._cantidad = int(registro["UNIDADES"])
        uf_facturada = None
        if registro["ETAPA"] == fm_service.ETAPA_FACTURADO:
            uf_facturada = fm_service.uf_de_facturacion(
                _valor_o_none(registro["PRECIO"]), self._cantidad, _valor_o_none(registro["PAGO"]))
        self.uf_facturada = uf_facturada is not None
        self._uf = uf_facturada or uf or 0.0
        self._df_unidades = df_unidades
        self.buscador.blockSignals(True)
        self.buscador.clear()
        self.buscador.blockSignals(False)
        self.lbl_empresa.setText(registro["CLIENTE"])
        self.lbl_sub.setText(f"Flota {registro['FLOTA']} · Editor de facturación manual · {periodo_texto}")
        self.lbl_cliente.setText(f"Flota VC · {registro['FLOTA']}")
        etapa = "Sin registro" if registro["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM else (registro["ETAPA"] or "—")
        self.lbl_info.setText(f"RUT {fm_service.formatear_rut(registro['RUT'])} · {registro['UNIDADES']} u. · {etapa}")
        for w in (self.combo_nivel, self.chk_civ, self.chk_sz, self.input_precio, self.combo_tipo):
            w.blockSignals(True)
        self.combo_tipo.setCurrentIndex(max(0, self.combo_tipo.findData(registro["TIPO"])))
        self.combo_nivel.setCurrentIndex(max(0, self.combo_nivel.findData(nivel)))
        self.chk_civ.setChecked(civ and self.nivel() != "BASICO")
        self.chk_civ.setEnabled(self.nivel() != "BASICO")
        self.chk_sz.setChecked(sz)
        precio = _valor_o_none(registro["PRECIO"])
        self.input_precio.setText("" if precio is None else _precio_texto(precio))
        pago = _valor_o_none(registro["PAGO"])
        es_fijo = precio is None and pago is not None and registro["ETAPA"] == fm_service.ETAPA_FACTURADO
        self.chk_fijo.blockSignals(True)
        self.chk_fijo.setChecked(es_fijo)
        self.chk_fijo.blockSignals(False)
        self.input_fijo.blockSignals(True)
        self.input_fijo.setText(f"{int(pago):,}".replace(",", ".") if es_fijo else "")
        self.input_fijo.blockSignals(False)
        self.fila_fijo.setVisible(es_fijo)
        self.input_precio.setEnabled(not es_fijo)
        self.lbl_por_unidades.setVisible(not es_fijo)
        self.btn_guardar.setText("Guardar y marcar facturado  →" if es_fijo else "Guardar facturación  →")
        for w in (self.combo_nivel, self.chk_civ, self.chk_sz, self.input_precio, self.combo_tipo):
            w.blockSignals(False)
        self.lbl_por_unidades.setText(f"UF × {self._cantidad}")
        self.lbl_por_unidades.setToolTip(f"Precio por unidad × {self._cantidad} {'unidad' if self._cantidad == 1 else 'unidades'}")
        if self._uf > 0:
            self.lbl_uf_dia.setText(f"{'UF de facturación' if self.uf_facturada else 'UF del día'}: ${_num(self._uf)}")
        else:
            self.lbl_uf_dia.setText("UF del día no disponible")
        n_pf = len(df_unidades)
        self.lbl_cuenta.setText(str(n_pf))
        aviso = aviso_registro(registro)
        self.lbl_aviso.setText(aviso)
        self.lbl_aviso.setVisible(bool(aviso))
        self.fila_aviso.setVisible(bool(aviso))
        self.btn_ajustar_rm.setVisible(puede_ajustar_a_rm(registro))
        self._refrescar()

    def _al_cambiar_fijo(self, activo):
        self.fila_fijo.setVisible(activo)
        self.input_precio.setEnabled(not activo)
        self.lbl_por_unidades.setVisible(not activo)
        self.btn_guardar.setText("Guardar y marcar facturado  →" if activo else "Guardar facturación  →")
        self._refrescar()

    def fijo(self):
        """Neto CLP fijo escrito (entero positivo) cuando la opción está marcada; None si no."""
        if not self.chk_fijo.isChecked():
            return None
        digitos = "".join(c for c in self.input_fijo.text() if c.isdigit())
        return int(digitos) if digitos and int(digitos) > 0 else None

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
        return self.nivel() + self._extras_plan()

    def plan_texto(self):
        return self.combo_nivel.currentText() + self._extras_plan()

    def _extras_plan(self):
        return (" + CIV" if self.chk_civ.isChecked() else "") + (" + SZ" if self.chk_sz.isChecked() else "")

    def totales(self):
        return fm_service.calcular_totales(self.precio(), self._cantidad, self._uf)

    def cambiar_uf(self, uf):
        """Aplica una UF nueva sin tocar lo que el usuario ya escribió; las flotas
        facturadas conservan la UF con la que se facturaron."""
        if self._registro is None or self.uf_facturada:
            return
        self._uf = uf
        self.lbl_uf_dia.setText(f"UF del día: ${_num(uf)}")
        self._refrescar()

    def datos_documento(self):
        """Datos de la flota abierta para el PDF y el Excel (mismos totales que
        muestra el editor)."""
        return armar_datos_documento(self._registro, self._df_unidades, self.plan_texto(), self.precio(),
                                     self._uf, self.uf_facturada, self._cantidad, self.fijo())

    def _mostrar_resultado_busqueda(self, encontradas, faltan, pegados):
        """Resultado de la búsqueda; no cambia el total de la flota ni el cálculo."""
        texto = f"{pegados - len(faltan)} de {pegados} están en la flota"
        if faltan:
            texto += " · No están: " + ", ".join(faltan[:5]) + ("…" if len(faltan) > 5 else "")
        color = "#B91C1C" if faltan else "#065F46"
        self.lbl_busqueda.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; background: transparent;")
        self.lbl_busqueda.setText(texto)
        self.lbl_busqueda.setToolTip("\n".join(faltan))
        self.lbl_busqueda.show()

    def _vins_unidades(self):
        return self._df_unidades["VIN"].astype(str).tolist() if "VIN" in self._df_unidades.columns else []

    def _columna_unidades(self, columna):
        """Valores de una columna de las unidades abiertas ('-' si no existe)."""
        if columna in self._df_unidades.columns:
            return self._df_unidades[columna].astype(str).tolist()
        return ["-"] * len(self._df_unidades)

    def _refrescar(self, *_args):
        if self._registro is None:
            return
        precio = self.precio()
        neto_uf, neto_clp = self.totales()
        pago_guardado = _valor_o_none(self._registro["PAGO"])
        self.val_unidades.setText(str(self._cantidad))
        fijo = self.fijo()
        if self.chk_fijo.isChecked():
            precio = None
            self.val_neto_uf.setText("—")
            self.val_neto_clp.setText(_clp(fijo) if fijo else "—")
            self.lbl_total_uf.setText("Precio fijo")
            self.lbl_total_clp.setText(f"{_clp(fijo)} CLP" if fijo else "$0 CLP")
            self.btn_guardar.setEnabled(fijo is not None and bool(self.tipo()))
        elif neto_uf is None:
            self.val_neto_uf.setText("—")
            self.val_neto_clp.setText(_clp(pago_guardado) if pago_guardado is not None else "—")
            self.lbl_total_uf.setText("0,00 UF")
            self.lbl_total_clp.setText(f"{_clp(pago_guardado)} CLP (registrado)" if pago_guardado is not None else "$0 CLP")
        else:
            self.val_neto_uf.setText(_num(neto_uf))
            self.val_neto_clp.setText(_clp(neto_clp) if neto_clp is not None else "—")
            self.lbl_total_uf.setText(f"{_num(neto_uf)} UF")
            self.lbl_total_clp.setText(f"{_clp(neto_clp)} CLP" if neto_clp is not None else "UF no disponible")
        if not self.chk_fijo.isChecked():
            self.btn_guardar.setEnabled(precio is not None and neto_clp is not None and bool(self.tipo()))
        vins = self._vins_unidades()
        ids = self._df_unidades["ID"].astype(str).tolist() if "ID" in self._df_unidades.columns else ["-"] * len(vins)
        filas = [
            [razon, fm_service.formatear_rut(rut), str(i), str(v), self.plan_texto(), _precio_texto(precio)]
            for v, i, razon, rut in zip(vins, ids, self._columna_unidades(COL_RAZON_SOCIAL), self._columna_unidades("RUT"))
        ]
        tabla = pd.DataFrame(filas, columns=_COLUMNAS_UNIDADES_EDITOR)
        texto = self.buscador.text().strip()
        if texto:
            mascara, faltan, pegados = fm_service.buscar_unidades_en_lista(self._df_unidades, texto)
            tabla = tabla[mascara]
            self._mostrar_resultado_busqueda(sum(mascara), faltan, pegados)
        else:
            self.lbl_busqueda.hide()
        self.modelo.set_data(tabla)
        anchos = {"RAZÓN SOCIAL": 300, "RUT": 130, "N° CONTRATO": 110, "VIN": 190, "PLAN": 130, "PRECIO UF": 110}
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
        ("Razones sociales", COL_RAZONES_FM), ("Etapa de gestión", COL_ETAPA_FM), ("Unidades", COL_UNIDADES_FM),
        ("Período", COL_PERIODO_FM),
    ]
    COL_CLAVE = COL_CLAVE_FM
    COL_EMPRESA = COL_CLIENTE
    COLUMNAS_OCULTAS = (COL_CLAVE_FM,)
    COL_COPIA = COL_RUT_FM
    ETIQUETA_COPIA = "RUT"
    MOSTRAR_VIN_FICHA = False
    SELECCION_EN_NIVEL_1 = True
    ANCHOS_EMPRESAS = {COL_CLIENTE: 480, COL_RAZONES_FM: 170, COL_UNIDADES_FM: 130, COL_ETAPA_FM: 220}
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
        self._razon_elegida = (None, None)
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
            self.agregar_filtro_compacto(combo)

        self.btn_export_excel = boton_barra("", 'fa5s.file-excel', 'excel')
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='#1B2B4E'))
        self.btn_export_excel.setToolTip("Exportar la lista a Excel")
        self.btn_export_excel.setFixedWidth(44)
        self.btn_export_excel.clicked.connect(lambda: self.table_export.export_to_excel("Reporte_Facturacion_Manual"))
        self.agregar_general(self.btn_export_excel)

        self.btn_uf = boton_barra("", 'fa5s.dollar-sign', 'excel')
        self.btn_uf.setIcon(ThemeManager.icon('fa5s.dollar-sign', color='#1B2B4E'))
        self.btn_uf.setToolTip("Actualizar UF: busca la UF de hoy en internet y la guarda en Variables")
        self.btn_uf.setFixedWidth(44)
        self.btn_uf.clicked.connect(self.actualizar_uf)
        self.agregar_blanco(self.btn_uf)

        self.btn_generar_mes = boton_barra("", 'fa5s.folder-open', 'excel')
        self.btn_generar_mes.setIcon(ThemeManager.icon('fa5s.folder-open', color='#1B2B4E'))
        self.btn_generar_mes.setToolTip("Generar la facturación del mes: una carpeta por razón social con su PDF y su Excel")
        self.btn_generar_mes.setFixedWidth(44)
        self.btn_generar_mes.clicked.connect(self._generar_facturacion_del_mes)
        self.agregar_blanco(self.btn_generar_mes)

        self.btn_reload = boton_barra("", 'fa5s.sync-alt')
        self.btn_reload.setToolTip("Recargar")
        self.btn_reload.clicked.connect(self.recargar)
        self.agregar_general(self.btn_reload)

        self.table_export = VolvoTableWidget()
        self.model_export = PandasTableModel()
        self.table_export.setModel(self.model_export)

        self.btn_abrir_editor = estilo_com.BotonAccionCompacta(
            'fa5s.edit', 'Abrir editor', "Revisa la flota, define el precio UF y genera el PDF.", VOLVO_BLUE)
        self.btn_abrir_editor.setEnabled(False)
        self.btn_abrir_editor.clicked.connect(self._on_abrir_editor_clicado)
        self.agregar_accion_panel(self.btn_abrir_editor)
        self.btn_facturado = estilo_com.BotonAccionCompacta(
            'fa5s.check-circle', 'Marcar como Facturado', "Aplica a todas las flotas seleccionadas.", "#16A34A")
        self.btn_facturado.clicked.connect(lambda: self._marcar_etapa(fm_service.ETAPA_FACTURADO))
        self.agregar_accion_panel(self.btn_facturado)
        self.btn_pendiente = estilo_com.BotonAccionCompacta(
            'fa5s.clock', 'Marcar como Pendiente', "Aplica a todas las flotas seleccionadas.", "#4338CA")
        self.btn_pendiente.clicked.connect(lambda: self._marcar_etapa(fm_service.ETAPA_PENDIENTE))
        self.agregar_accion_panel(self.btn_pendiente)
        self.btn_exp_excel = estilo_com.BotonAccionCompacta(
            'fa5s.file-excel', 'Exportar a Excel', "Un archivo por cada razón social de las flotas seleccionadas.", "#15803D")
        self.btn_exp_excel.clicked.connect(lambda: self._exportar_razones("Excel"))
        self.agregar_accion_panel(self.btn_exp_excel)
        self.btn_exp_pdf = estilo_com.BotonAccionCompacta(
            'fa5s.file-pdf', 'Exportar a PDF', "Un archivo por cada razón social de las flotas seleccionadas.", "#B91C1C")
        self.btn_exp_pdf.clicked.connect(lambda: self._exportar_razones("PDF"))
        self.agregar_accion_panel(self.btn_exp_pdf)

        self.tabla.doubleClicked.connect(self._on_doble_clic_lista)
        self.tabla.frozen_view.doubleClicked.connect(self._on_doble_clic_lista)

        self.editor = EditorFacturacion()
        self.editor.volver.connect(self.ir_a_lista_empresas)
        self.editor.razon_cambiada.connect(self._on_razon_cambiada)
        self.editor.guardar.connect(self._guardar_facturacion)
        self.editor.ajustar_a_rm.connect(self._ajustar_a_rm)
        self.editor.exportar_pdf.connect(self._exportar_pdf)
        self.editor.exportar_excel.connect(self._exportar_excel)
        self.editor.actualizar_uf.connect(self.actualizar_uf)
        self.editor.unidad_doble_clic.connect(lambda vin: self.editar_y_guardar_unidad(vin, PESTANA_JUSTTIME_CM))
        self.editor.hide()
        self.layout().addWidget(self.editor, 1)

    # --------------------------------------------- ganchos de la pantalla base
    def resolver_color(self, columna, valor, es_fondo):
        texto = str(valor).strip().upper()
        if columna == COL_TIPO_FM:
            colores = _CHIP_TIPO.get(texto)
        elif columna == COL_ETAPA_FM:
            colores = _chip_etapa(texto)
        elif columna == COL_UNIDADES_FM:
            colores = _CHIP_VOLVO
        else:
            return None
        return colores[0 if es_fondo else 1] if colores else None

    def colores_chip_ficha(self, columna, valor):
        if columna == COL_TIPO_FM:
            return _CHIP_TIPO.get(str(valor).strip().upper())
        if columna == COL_ETAPA_FM:
            return _chip_etapa(valor)
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
            for btn in (self.btn_abrir_editor, self.btn_facturado, self.btn_pendiente, self.btn_exp_excel, self.btn_exp_pdf):
                btn.setEnabled(False)
            return
        aviso = aviso_flota(fila["_REGISTRO"]) if "_REGISTRO" in fila else ""
        self._pintar_panel(fila, cantidad, aviso)
        self._ficha_chasis.setToolTip("Clic para copiar" + (f": {fila['_RUTS']}" if fila.get("_RUTS") else ""))
        self._lbl_titulo_panel.setText("Flota seleccionada" if cantidad == 1 else f"{cantidad} flotas seleccionadas")
        self.btn_abrir_editor.setEnabled(cantidad == 1)
        self.btn_facturado.setEnabled(True)
        self.btn_pendiente.setEnabled(True)
        self.btn_exp_excel.setEnabled(True)
        self.btn_exp_pdf.setEnabled(True)

    def _copiar_chasis(self):
        fila = next(iter(self._filas_seleccionadas()), None)
        texto = (fila or {}).get("_RUTS") or self._ficha_chasis.text()
        if texto and texto != "—":
            QApplication.clipboard().setText(texto)

    def _filas_seleccionadas(self):
        return [self._fila_por_vin[v] for v in self._vins_seleccionados() if v in self._fila_por_vin]

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
        claves.update((fm_service.periodo_anterior(), fm_service.periodo_actual()))
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
            idx = self.combo_periodo.findData(fm_service.periodo_actual())
        self.combo_periodo.setCurrentIndex(max(0, idx))
        self.combo_periodo.blockSignals(False)
        self.filtro_periodo = self.combo_periodo.currentData() or ""
        self._mes_visto = fm_service.periodo_actual()
        self.combo_periodo._actualizar_tooltip()

    def _seleccionar_periodo_reciente(self):
        """Si cambió el mes desde la última vez, vuelve al mes en curso; si no,
        respeta el período que eligió el usuario."""
        actual = fm_service.periodo_actual()
        if actual == getattr(self, '_mes_visto', None):
            return False
        self._mes_visto = actual
        idx = self.combo_periodo.findData(actual)
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
        incluir_sin_registro = self.filtro_periodo in fm_service.periodos_con_sin_registro(self._claves_periodos())
        df = fm_service.armar_registros_periodo(self.df_registros, self.df_filtrado, self.filtro_periodo,
                                                incluir_sin_registro)
        return df

    def _registros_busqueda(self, df):
        """Registros (razones sociales) que coinciden con la búsqueda global por razón social,
        RUT o flota."""
        texto = self.search_input.text().strip().lower()
        if not texto or df.empty:
            return df
        mascara = df["CLIENTE"].str.lower().str.contains(texto, regex=False) | \
            df["RUT"].str.lower().str.contains(texto, regex=False) | \
            df["FLOTA"].str.lower().str.contains(texto, regex=False)
        return df[mascara]

    def filter_table(self):
        if self.empresa_actual is not None:
            return
        base = self._registros_busqueda(self._alcance_periodo())
        todas = fm_service.agrupar_flotas(base)
        empresas = len(todas)
        unidades = sum(f["UNIDADES"] for f in todas)
        pendientes = sum(1 for f in todas if f["ETAPA"] == fm_service.ETAPA_PENDIENTE or f["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM)
        pago = float(base["PAGO"].fillna(0).sum()) if not base.empty else 0.0
        valores = {
            "empresas": (empresas, 1.0 if empresas else 0.0, "con unidades por facturar"),
            "unidades": (unidades, None, f"promedio {_num(unidades / empresas, 1) if empresas else '0'} por flota"),
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
        flotas = fm_service.agrupar_flotas(base, visibles=df)

        self._armar_tabla(flotas)
        self.lbl_subtitulo.setText(self._texto_subtitulo(flotas))
        self.lbl_sin_resultados.setVisible(self._df_tabla.empty)
        self._pintar_tabla()

    @staticmethod
    def _es_pendiente(df):
        """Etapa Pendiente o empresa sin fila del mes (aún no se factura)."""
        return (df["ETAPA"] == fm_service.ETAPA_PENDIENTE) | (df["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM)

    def _texto_subtitulo(self, flotas):
        uf = self._uf_vigente()
        razones = sum(f["N_RAZONES"] for f in flotas)
        texto = f"{len(flotas)} flotas · {razones} razones sociales · {sum(f['UNIDADES'] for f in flotas)} unidades"
        if uf > 0:
            texto += f" · UF ${_num(uf)}"
        if self.filtro_periodo:
            texto += f" · {fm_service.etiqueta_periodo(self.filtro_periodo)}"
        return texto

    def actualizar_uf(self):
        """Busca la UF en internet (sin bloquear la pantalla) y, con confirmación,
        la guarda en Variables de provisionFelipe.xlsx como hace Provisiones."""
        if getattr(self, '_uf_worker', None) is not None:
            return
        from src.ui.provisiones import FetchUfWorker
        for boton in (self.btn_uf, self.editor.btn_uf):
            boton.setEnabled(False)
            boton.setText(" Buscando UF…")
        self._uf_worker = FetchUfWorker()
        self._uf_worker.uf_fetched.connect(self._on_uf_obtenida)
        self._uf_worker.error_signal.connect(self._on_uf_error)
        self._uf_worker.finished.connect(self._fin_busqueda_uf)
        self._uf_worker.start()

    def _fin_busqueda_uf(self):
        self._uf_worker = None
        for boton in (self.btn_uf, self.editor.btn_uf):
            boton.setEnabled(True)
            boton.setText("Actualizar UF")

    def _on_uf_error(self, error):
        QMessageBox.warning(self, "No se pudo obtener la UF",
                            f"No hay conexión con el servicio de UF:\n{error}\nPuedes ingresarla en Provisiones > Costos.")

    def _on_uf_obtenida(self, nueva):
        actual = self._uf_vigente()
        if abs(nueva - actual) < 0.005:
            QMessageBox.information(self, "UF al día", f"La UF ya es ${_num(actual)}.")
            return
        respuesta = QMessageBox.question(
            self, "Actualizar UF",
            f"UF obtenida: ${_num(nueva)}\nUF guardada: ${_num(actual)}\n\n"
            "Se guardará en Variables de provisionFelipe.xlsx (con copia de seguridad) y la usarán "
            "Provisiones y Facturación Manual. ¿Actualizar?")
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        ruta = config.settings.PROVISION_EXCEL_PATH
        try:
            self.writer._crear_backup(ruta)
            if not self.writer.last_backup_ok:
                QMessageBox.critical(self, "Error", "No se pudo crear la copia de seguridad. No se cambió la UF.")
                return
            dm = self.data_manager
            dm.is_app_saving = True
            dm.save_timestamp = time.time()
            if not provisiones_services.escribir_uf_en_variables(ruta, nueva):
                dm.is_app_saving = False
                QMessageBox.warning(self, "No se pudo guardar", "provisionFelipe.xlsx no tiene la fila UF en la hoja Variables.")
                return
        except Exception as e:
            self.data_manager.is_app_saving = False
            QMessageBox.critical(self, "No se pudo guardar la UF", f"Cierra el archivo si está abierto en Excel.\n{e}")
            return
        self.data_manager.valor_uf = nueva
        self.data_manager.load_provisiones_async()
        self.editor.cambiar_uf(nueva)
        if self.empresa_actual is None:
            self.filter_table()

    def _uf_vigente(self):
        try:
            return float(self.data_manager.get_variables()[0] or 0)
        except (TypeError, ValueError, IndexError, AttributeError):
            return 0.0

    def _armar_tabla(self, flotas):
        """Una fila por flota (agrupar_flotas). Los precios y pagos no se muestran aquí: cada
        razón social de la flota tiene los suyos, que se ven y se editan al abrirla."""
        self._fila_por_vin = {}
        if not flotas:
            self._df_tabla = pd.DataFrame(columns=_COLUMNAS_LISTA)
            self.model_export.set_data(pd.DataFrame())
            return
        filas = []
        for f in flotas:
            clave = f"{fm_service.clave_periodo(f['PERIODO'])}|{f['GRUPO']}"
            sin_registro = f["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM
            estados = [
                "Sin registro" if r["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM else (r["ETAPA"] or "—")
                for r in f["RAZONES"]]
            if sin_registro:
                etapa = "Sin registro"
            elif len(set(estados)) > 1:
                faltan = estados.count("Sin registro")
                etapa = f"Parcial · {faltan} sin registro" if faltan else f"Parcial · {estados.count(fm_service.ETAPA_PENDIENTE)} pendiente"
            else:
                etapa = f["ETAPA"] or "—"
            fila = {
                COL_CLAVE_FM: clave, COL_CLIENTE: f["FLOTA"], COL_RAZONES_FM: str(f["N_RAZONES"]),
                COL_UNIDADES_FM: str(f["UNIDADES"]), COL_ETAPA_FM: etapa,
            }
            filas.append(fila)
            ficha = dict(fila)
            ficha[COL_RAZON_SOCIAL] = f["FLOTA"]
            ruts = [fm_service.formatear_rut(r["RUT"]) for r in f["RAZONES"]]
            ficha[COL_RUT_FM] = ruts[0] if len(ruts) == 1 else f"{len(ruts)} RUT distintos"
            ficha["_RUTS"] = ", ".join(ruts)
            ficha[COL_PERIODO_FM] = fm_service.etiqueta_periodo(fm_service.clave_periodo(f["PERIODO"]))
            ficha["_REGISTRO"] = f
            ficha["_ENTRADA"] = f["GRUPO"]
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
        self._cargar_editor()

    def _cargar_editor(self):
        """Abre en el editor la razón social elegida de la flota actual (la primera si no hay
        una elegida)."""
        flota = self._flota_actual()
        registro = self._registro_actual(flota)
        if registro is None:
            self.ir_a_lista_empresas()
            return
        unidades = fm_service.unidades_de_registro(self.df_filtrado, registro)
        nivel, civ = fm_service.nivel_servicio_dominante(unidades)
        razones = [(r["RUT"], self._texto_razon(r)) for r in flota["RAZONES"]]
        self.editor.cargar(registro, unidades, self._uf_vigente(), nivel, civ,
                           fm_service.etiqueta_periodo(self.filtro_periodo), fm_service.tiene_safety_zone(unidades),
                           razones)

    @staticmethod
    def _texto_razon(r):
        etapa = "Sin registro" if r["ORIGEN"] == fm_service.ORIGEN_PRUEBASFM else (r["ETAPA"] or "—")
        return f"{r['CLIENTE']} · {etapa}"

    def _flota_actual(self):
        """La flota abierta, con todas sus razones sociales del período (sin filtros)."""
        base = self._alcance_periodo()
        if base.empty or self.empresa_actual is None:
            return None
        flotas = fm_service.agrupar_flotas(base[base["GRUPO"] == self.empresa_actual])
        return flotas[0] if flotas else None

    def _registro_actual(self, flota=None):
        """Registro de la razón social abierta en el editor."""
        flota = flota or self._flota_actual()
        if flota is None:
            return None
        elegida = self._razon_elegida[1] if self._razon_elegida[0] == self.empresa_actual else None
        for r in flota["RAZONES"]:
            if r["RUT"] == elegida:
                return r
        return flota["RAZONES"][0]

    def _on_razon_cambiada(self, rut):
        self._razon_elegida = (self.empresa_actual, rut)
        self._cargar_editor()

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
        cambios, nuevas = [], []
        for clave in self._vins_seleccionados():
            for razon in self._fila_por_vin[clave]["_REGISTRO"]["RAZONES"]:
                c, n = fm_service.armar_guardado(razon, {"etapa": etapa})
                cambios += c
                nuevas += n
        if not cambios and not nuevas:
            QMessageBox.information(self, "Sin cambios", f"Las flotas seleccionadas ya están como {etapa}.")
            return
        ok, mensaje = fm_service.guardar_registros_fm(self._ruta, cambios, nuevas)
        if not ok:
            QMessageBox.critical(self, "No se pudo guardar", mensaje)
            return
        self.load_data()

    def _guardar_facturacion(self):
        registro = self._registro_actual()
        precio = self.editor.precio()
        neto_uf, neto_clp = self.editor.totales()
        fijo = self.editor.fijo()
        if registro is not None and fijo is not None:
            self._guardar_precio_fijo(registro, fijo)
            return
        if registro is None or precio is None or neto_clp is None:
            return
        pregunta = QMessageBox.question(
            self, "Guardar facturación",
            f"Se guardará para {registro['CLIENTE']} (RUT {fm_service.formatear_rut(registro['RUT'])}):\n\n"
            f"• Tipo: {_TIPOS_TEXTO.get(self.editor.tipo(), self.editor.tipo())}\n"
            f"• Precio unitario: {_precio_texto(precio)} UF × {int(registro['UNIDADES'])} unidades\n"
            f"• Total: {_num(neto_uf)} UF = {_clp(neto_clp)}\n"
            f"• Plan de sus unidades: {self.editor.valor_plan()}\n\n"
            "En facturacionManual.xlsx y el plan en RM_JAVI (con copia de seguridad). "
            "Las otras razones sociales de la flota no cambian.")
        if pregunta != QMessageBox.StandardButton.Yes:
            return
        cambios, nuevas = fm_service.armar_guardado(
            registro, {"precio": precio, "tipo": self.editor.tipo()}, self.editor._uf)
        ok, mensaje = fm_service.guardar_registros_fm(self._ruta, cambios, nuevas)
        if not ok:
            QMessageBox.critical(self, "No se pudo guardar", mensaje)
            return
        self.load_data()
        self._cargar_editor()
        self._aplicar_plan_a_unidades()

    def _ajustar_a_rm(self):
        """Deja las unidades de la razón ya facturada igual a las de RM_JAVI: el RM manda."""
        registro = self._registro_actual()
        if registro is None or not puede_ajustar_a_rm(registro):
            return
        cambios, nuevas = fm_service.armar_ajuste_a_rm(registro)
        if not cambios:
            return
        antes, ahora = int(registro["UNIDADES_EXCEL"]), int(registro["UNIDADES_PF"])
        pregunta = QMessageBox.question(
            self, "Ajustar a RM_JAVI",
            f"{registro['CLIENTE']} (RUT {fm_service.formatear_rut(registro['RUT'])}) pasará de {antes} a {ahora} unidades "
            "en facturacionManual.xlsx.\n\n"
            "Si el mes tiene precio por unidad, el total se recalcula con la misma UF con que se facturó; "
            "el precio fijo no cambia.\n\nSe guarda con copia de seguridad.")
        if pregunta != QMessageBox.StandardButton.Yes:
            return
        ok, mensaje = fm_service.guardar_registros_fm(self._ruta, cambios, nuevas)
        if not ok:
            QMessageBox.critical(self, "No se pudo guardar", mensaje)
            return
        self.load_data()
        self._cargar_editor()

    def _guardar_precio_fijo(self, registro, fijo):
        """Guarda el Neto CLP fijo como pago de la razón social, sin precio unitario, y la deja Facturada."""
        pregunta = QMessageBox.question(
            self, "Guardar precio fijo",
            f"Se guardará para {registro['CLIENTE']} (RUT {fm_service.formatear_rut(registro['RUT'])}):\n\n"
            f"• Tipo: {_TIPOS_TEXTO.get(self.editor.tipo(), self.editor.tipo())}\n"
            f"• Precio fijo mensual: {_clp(fijo)} CLP neto ({int(registro['UNIDADES'])} unidades)\n"
            f"• Etapa: Facturado\n"
            f"• Plan de sus unidades: {self.editor.valor_plan()}\n\n"
            "En facturacionManual.xlsx y el plan en RM_JAVI (con copia de seguridad). "
            "Las otras razones sociales de la flota no cambian.")
        if pregunta != QMessageBox.StandardButton.Yes:
            return
        cambios, nuevas = fm_service.armar_guardado(registro, {"precio_fijo": fijo, "tipo": self.editor.tipo()})
        ok, mensaje = fm_service.guardar_registros_fm(self._ruta, cambios, nuevas)
        if not ok:
            QMessageBox.critical(self, "No se pudo guardar", mensaje)
            return
        self.load_data()
        self._cargar_editor()
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

    def _datos_exportacion(self, formato, nombre_sugerido, filtro):
        """(ruta, datos) para exportar la flota abierta al PDF o al Excel; None si
        se cancela o falta el precio."""
        registro = self._registro_actual()
        precio = self.editor.precio()
        neto_uf, neto_clp = self.editor.totales()
        if registro is None:
            return None
        if precio is None and self.editor.fijo() is None:
            QMessageBox.information(self, "Falta el precio", f"Ingresa el precio UF por unidad (o el precio fijo) para generar el {formato}.")
            return None
        periodo = registro["PERIODO"]
        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        ruta, _ = QFileDialog.getSaveFileName(
            self, f"Guardar {formato}", os.path.join(carpeta, nombre_sugerido(registro["CLIENTE"], periodo.year, periodo.month)),
            filtro)
        if not ruta:
            return None
        return ruta, self.editor.datos_documento()

    def _datos_documento_razon(self, r):
        """(datos, motivo) del documento de una razón social, con el precio guardado en el Excel y
        sus unidades de PruebasFM; si falta algo, datos es None y el motivo dice qué."""
        precio = _valor_o_none(r["PRECIO"])
        pago = _valor_o_none(r["PAGO"])
        fijo = int(pago) if precio is None and pago and r["ETAPA"] == fm_service.ETAPA_FACTURADO else None
        if precio is None and fijo is None:
            return None, "no tiene precio guardado"
        unidades = fm_service.unidades_de_registro(self.df_filtrado, r)
        if unidades.empty:
            return None, "no tiene unidades en Facturación Manual"
        nivel, civ = fm_service.nivel_servicio_dominante(unidades)
        plan = (dict(_NIVELES)[nivel] + (" + CIV" if civ and nivel != "BASICO" else "")
                + (" + SZ" if fm_service.tiene_safety_zone(unidades) else ""))
        cantidad = int(r["UNIDADES"])
        if fijo is not None:
            return armar_datos_documento(r, unidades, plan, None, 0, False, cantidad, fijo), ""
        uf_facturada = None
        if r["ETAPA"] == fm_service.ETAPA_FACTURADO:
            uf_facturada = fm_service.uf_de_facturacion(precio, cantidad, _valor_o_none(r["PAGO"]))
        uf = uf_facturada or self._uf_vigente()
        if not uf:
            return None, "no hay valor de UF"
        return armar_datos_documento(r, unidades, plan, precio, uf, uf_facturada is not None, cantidad), ""

    @staticmethod
    def _ruta_libre(carpeta, nombre, usadas):
        """Ruta dentro de `carpeta` que no pisa un archivo existente ni otro de este lote."""
        base, extension = os.path.splitext(nombre)
        ruta, n = os.path.join(carpeta, nombre), 2
        while os.path.exists(ruta) or ruta.lower() in usadas:
            ruta = os.path.join(carpeta, f"{base} ({n}){extension}")
            n += 1
        usadas.add(ruta.lower())
        return ruta

    def _exportar_razones(self, formato):
        """Exporta un PDF o un Excel por cada razón social de las flotas seleccionadas, cada uno
        con sus propios montos (nunca se unen). Usa el precio guardado de cada razón social; las
        que no lo tienen se omiten y se avisa."""
        razones = [r for clave in self._vins_seleccionados() for r in self._fila_por_vin[clave]["_REGISTRO"]["RAZONES"]]
        if not razones:
            return
        modulo, generar = (fm_pdf, fm_pdf.generar_pdf) if formato == "PDF" else (fm_excel, fm_excel.generar_excel)
        documentos, omitidas = [], []
        for r in razones:
            datos, motivo = self._datos_documento_razon(r)
            if datos is None:
                omitidas.append(f"• {r['CLIENTE']}: {motivo}")
            else:
                documentos.append((r, datos))
        if not documentos:
            QMessageBox.information(self, f"Exportar a {formato}",
                                    "Ninguna razón social tiene lo necesario para generar el documento:\n\n" + "\n".join(omitidas))
            return
        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        if len(documentos) == 1:
            nombre = modulo.nombre_sugerido(documentos[0][0]["CLIENTE"])
            ruta, _ = QFileDialog.getSaveFileName(
                self, f"Guardar {formato}", os.path.join(carpeta, nombre), "PDF (*.pdf)" if formato == "PDF" else "Excel (*.xlsx)")
            if not ruta:
                return
            rutas = [ruta]
            destino = os.path.dirname(ruta)
        else:
            destino = QFileDialog.getExistingDirectory(self, f"Carpeta donde guardar los {formato} (uno por razón social)", carpeta)
            if not destino:
                return
            usadas = set()
            rutas = [self._ruta_libre(destino, modulo.nombre_sugerido(r["CLIENTE"]), usadas) for r, _d in documentos]
        generados, fallidas = 0, []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for (r, datos), ruta in zip(documentos, rutas):
                try:
                    generar(ruta, datos)
                    generados += 1
                except Exception as e:
                    fallidas.append(f"• {r['CLIENTE']}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        if generados == 1 and not omitidas and not fallidas:
            return
        texto = f"Se generaron {generados} {formato} (uno por razón social) en:\n{destino}"
        if omitidas:
            texto += "\n\nNo se generaron por falta de datos:\n" + "\n".join(omitidas)
        if fallidas:
            texto += "\n\nError al generar:\n" + "\n".join(fallidas)
        QMessageBox.information(self, f"Exportar a {formato}", texto)

    def _generar_facturacion_del_mes(self):
        """Genera el PDF y el Excel de todas las razones sociales del período elegido, en
        "facturacion MM_AAAA/<razón social>/". Las que no tienen precio guardado, unidades o UF
        no se generan y se listan al final. Un archivo ya generado antes se reemplaza."""
        if not self.filtro_periodo:
            return
        razones = self._alcance_periodo().to_dict("records")
        if not razones:
            QMessageBox.information(self, "Generar facturación", "No hay razones sociales en este período.")
            return
        anio, mes = self.filtro_periodo.split("-")
        etiqueta = fm_service.etiqueta_periodo(self.filtro_periodo)
        carpeta = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        base = QFileDialog.getExistingDirectory(
            self, f"Carpeta donde crear «facturacion {mes}_{anio}» ({etiqueta})", carpeta)
        if not base:
            return
        raiz = os.path.join(base, f"facturacion {mes}_{anio}")
        try:
            os.makedirs(raiz, exist_ok=True)
        except OSError as e:
            QMessageBox.critical(self, "No se pudo crear la carpeta", f"{raiz}\n{e}")
            return
        PanelFacturacionMes(self, razones, self._datos_documento_razon, raiz, etiqueta).exec()

    def _exportar_pdf(self):
        exportacion = self._datos_exportacion("PDF", fm_pdf.nombre_sugerido, "PDF (*.pdf)")
        if exportacion is None:
            return
        try:
            fm_pdf.generar_pdf(*exportacion)
        except Exception as e:
            QMessageBox.critical(self, "No se pudo generar el PDF", str(e))

    def _exportar_excel(self):
        exportacion = self._datos_exportacion("Excel", fm_excel.nombre_sugerido, "Excel (*.xlsx)")
        if exportacion is None:
            return
        try:
            fm_excel.generar_excel(*exportacion)
        except Exception as e:
            QMessageBox.critical(self, "No se pudo generar el Excel", str(e))
