import logging
import os
import pandas as pd
import qtawesome as qta
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
                             QLabel, QPushButton, QMessageBox, QLineEdit, QComboBox,
                             QFileDialog, QApplication, QStackedWidget, QProgressBar,
                             QScrollArea, QDialog, QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem, QAbstractItemView)
from PyQt6.QtCore import Qt, QEvent, QSize, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QColor
import config.settings
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.ui.custom_table import VolvoTableWidget, PandasTableModel
from src.ui.transiciones import cambiar_pagina_animada
from src.ui.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando, crear_tarjeta_carga
from src.ui.formulario_unidad import editar_unidad, PESTANA_JUSTTIME_CM
from src.ui import comercial_estilo as estilo_com
from src.ui.ingresos_base import PantallaIngresosBase, ComboFiltroBarra, boton_barra, estilo_combo_barra
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *
from src.services import cm_bajas_service
from src.services import comercial_services
from src.services import contratos_service as ct_service
from src.services import provisiones_services
from src.core.constants import (TIPO_CM_OPCIONES, ESTADO_CM_OPCIONES, COL_RUT, COL_RAZON_SOCIAL,
                                 TIPO_CM_FORMA_CONTRATO_MAP, VALOR_TIPO_FACT_CM, COL_ESTADO_ACTIVACION, COL_CDB_FLOTA)

logger = logging.getLogger(__name__)

MODULE_ACCENT = MODULE_COLORS.get("Contratos (CM)", PRIMARY)

# Colores de badge para TIPO DE CM / ESTADO DEL CM (valores reales del Excel
# 3PC, ver importar_excel_javiera). Mismo lenguaje visual que el _badge de
# facturacion_manual.py, con sus propios valores porque este modulo trabaja
# con estados en ingles (Running/Expired/Terminated), no con los estados
# comerciales en español que usa esa pantalla.
_BADGE_COLOR = {
    "RUNNING": ("#D1FAE5", "#065F46"),
    "EXPIRED": ("#FEE2E2", "#991B1B"),
    "EXPIRADO": ("#FEE2E2", "#991B1B"),
    "TERMINATED": ("#FEE2E2", "#991B1B"),
    "GOLD": ("#FEF3C7", "#92400E"),
    "BLUE": ("#DBEAFE", "#1E40AF"),
    "SILVER": ("#F3F4F6", "#4B5563"),
}
_BADGE_COLOR_DEFAULT = ("#F3F4F6", TEXT_SECONDARY)


def _formato_pago(valor_num):
    try:
        valor_num = float(valor_num)
    except (TypeError, ValueError):
        valor_num = 0.0
    if valor_num == 0:
        return "$-"
    signo = "-" if valor_num < 0 else ""
    return f"{signo}${int(abs(valor_num) + 0.5):,}".replace(",", ".")


# =========================================================
# MOTOR DE GUARDADO ASÍNCRONO DE CONTRATOS
# =========================================================
class SaveContratosThread(QThread):
    finished_signal = pyqtSignal(bool)

    def __init__(self, writer, changes, module_name="Contratos CM", contratos_nuevos=None):
        super().__init__()
        self.writer = writer
        self.changes = changes
        self.module_name = module_name
        self.contratos_nuevos = contratos_nuevos or []

    def run(self):
        success = self.writer.update_cells(self.changes, module_name=self.module_name) if self.changes else True
        if success and self.contratos_nuevos:
            success = self.writer.add_new_rows_batch(self.contratos_nuevos, module_name=self.module_name)
        self.finished_signal.emit(success)


# =========================================================
# RESUMEN DE IMPORTACIÓN (reemplaza al QMessageBox.question genérico)
# =========================================================
class ResumenImportacionDialog(QDialog):
    """Panel previo a inyectar un import de Contratos CM a la Base
    Comercial (ver ContratosModule.importar_excel_javiera), con el resumen
    de lo que va a pasar antes de confirmar: mismo patron visual que
    DialogoAccionCm/VinsHuerfanosAlertDialog (tarjeta blanca sobre fondo
    gris), agregando una grilla de KPI y las filas de cambio de estado
    porque aca la info es numerica.

    Los VIN "que no vienen este mes" son los mismos que ya detecta
    cm_bajas_service.detectar_posibles_bajas_cm() para Gestionar CM -- no
    se reinventa una segunda deteccion, solo se muestran aca ademas, con un
    boton para copiarlos al portapapeles."""

    def __init__(self, resumen, nombre_archivo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importación de Contratos CM")
        self.setMinimumWidth(480)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        encabezado = QHBoxLayout()
        encabezado.setSpacing(12)
        icono = QLabel()
        icono.setPixmap(ThemeManager.icon('fa5s.file-invoice', color=PRIMARY).pixmap(QSize(28, 28)))
        encabezado.addWidget(icono)
        titulo_wrap = QVBoxLayout()
        titulo_wrap.setSpacing(2)
        titulo = QLabel(f"{nombre_archivo} analizado")
        titulo.setWordWrap(True)
        ThemeManager.style_subtitle(titulo)
        titulo_wrap.addWidget(titulo)
        subtitulo = QLabel(f"Comparado contra la Base Comercial actual · {resumen['total_coincidencias']} VIN con coincidencia")
        subtitulo.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        titulo_wrap.addWidget(subtitulo)
        encabezado.addLayout(titulo_wrap, stretch=1)
        layout.addLayout(encabezado)

        kpis = QGridLayout()
        kpis.setSpacing(8)
        specs_kpi = [
            (str(resumen['total_filas_excel']), "Filas en el Excel", PRIMARY),
            (str(resumen['total_actualizados']), "Se actualizarán", SUCCESS),
            (str(resumen['total_sin_cambios']), "Sin cambios en el Excel", TEXT_PRIMARY),
            (str(len(resumen['vins_ausentes'])), "No vienen este mes", TEXT_PRIMARY),
            (str(len(resumen['vins_nuevos'])), "Sin ficha en Comercial", WARNING if resumen['vins_nuevos'] else TEXT_PRIMARY),
        ]
        for i, (valor, etiqueta, color) in enumerate(specs_kpi):
            kpis.addWidget(self._kpi_card(valor, etiqueta, color), 0, i)
        layout.addLayout(kpis)

        if resumen['pasan_a_expired'] or resumen['pasan_a_terminated']:
            seccion_titulo = QLabel("CAMBIOS DE ESTADO DETECTADOS")
            seccion_titulo.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10.5px; font-weight: bold; letter-spacing: 0.4px;")
            layout.addWidget(seccion_titulo)

            if resumen['pasan_a_expired']:
                layout.addWidget(self._fila_estado(f"Pasan a Expired con esta importación", resumen['pasan_a_expired'], WARNING))
            if resumen['pasan_a_terminated']:
                layout.addWidget(self._fila_estado(f"Pasan a Terminated con esta importación", resumen['pasan_a_terminated'], DANGER))

        if resumen.get('contratos_nuevos'):
            layout.addWidget(self._fila_estado(
                "Contratos nuevos (unidades en baja cuyo CM está Expired)",
                len(resumen['contratos_nuevos']), PRIMARY
            ))

        if resumen['vins_nuevos']:
            layout.addWidget(self._fila_estado(
                "VIN sin ficha en Comercial (se podrán vincular después de importar)",
                len(resumen['vins_nuevos']), WARNING
            ))

        vins_ausentes = resumen['vins_ausentes']
        if vins_ausentes:
            fila_ausentes_titulo = QHBoxLayout()
            lbl_ausentes = QLabel(f"{len(vins_ausentes)} VIN con CM que no vienen en este Excel")
            lbl_ausentes.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11.5px; font-weight: bold;")
            fila_ausentes_titulo.addWidget(lbl_ausentes, stretch=1)
            btn_copiar = QPushButton(" Copiar VIN")
            btn_copiar.setIcon(ThemeManager.icon('fa5s.copy', color=TEXT_SECONDARY))
            ThemeManager.apply_secondary_button(btn_copiar)
            btn_copiar.clicked.connect(lambda: self._copiar_vins_ausentes(vins_ausentes))
            fila_ausentes_titulo.addWidget(btn_copiar)
            layout.addLayout(fila_ausentes_titulo)

            lista = QListWidget()
            lista.setStyleSheet(f"""
                QListWidget {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
                QListWidget::item {{ padding: 4px 6px; color: {TEXT_PRIMARY}; font-size: 11.5px; }}
            """)
            lista.setMaximumHeight(110)
            for info in vins_ausentes:
                razon_social = info.get(COL_RAZON_SOCIAL, '-')
                lista.addItem(QListWidgetItem(f"{info.get('VIN', '-')} · {razon_social}"))
            layout.addWidget(lista)

            aviso = QLabel(
                "No aparecer en el Excel de este mes no se considera una baja. Esos "
                "contratos no se modifican y siguen como estaban en Comercial."
            )
            aviso.setWordWrap(True)
            aviso.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 10px;")
            layout.addWidget(aviso)

        botones = QHBoxLayout()
        botones.addStretch()
        self.btn_cancelar = QPushButton(" Cancelar")
        ThemeManager.apply_secondary_button(self.btn_cancelar)
        self.btn_cancelar.clicked.connect(self.reject)
        botones.addWidget(self.btn_cancelar)

        self.btn_confirmar = QPushButton(" Inyectar a Comercial")
        self.btn_confirmar.setIcon(ThemeManager.icon('fa5s.check', color='white'))
        ThemeManager.apply_primary_button(self.btn_confirmar)
        self.btn_confirmar.clicked.connect(self.accept)
        botones.addWidget(self.btn_confirmar)
        layout.addLayout(botones)

    def _kpi_card(self, valor, etiqueta, color):
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px; }}")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 10, 8, 10)
        card_layout.setSpacing(3)
        lbl_valor = QLabel(valor)
        lbl_valor.setStyleSheet(f"color: {color}; font-size: 19px; font-weight: 800; background: transparent; border: none;")
        lbl_valor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(lbl_valor)
        lbl_etiqueta = QLabel(etiqueta)
        lbl_etiqueta.setWordWrap(True)
        lbl_etiqueta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_etiqueta.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9.5px; font-weight: bold; background: transparent; border: none;")
        card_layout.addWidget(lbl_etiqueta)
        return card

    def _fila_estado(self, texto, cantidad, color):
        fila = QFrame()
        fila.setStyleSheet(f"QFrame {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px; }}")
        fila_layout = QHBoxLayout(fila)
        fila_layout.setContentsMargins(12, 8, 12, 8)
        punto = QLabel()
        punto.setFixedSize(8, 8)
        punto.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        fila_layout.addWidget(punto)
        lbl_texto = QLabel(texto)
        lbl_texto.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; background: transparent; border: none;")
        fila_layout.addWidget(lbl_texto, stretch=1)
        lbl_cantidad = QLabel(str(cantidad))
        lbl_cantidad.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: 800; background: transparent; border: none;")
        fila_layout.addWidget(lbl_cantidad)
        return fila

    def _copiar_vins_ausentes(self, vins_ausentes):
        texto = "\n".join(info.get('VIN', '') for info in vins_ausentes)
        QApplication.clipboard().setText(texto)


# =========================================================
# VIN NUEVOS SIN FICHA EN COMERCIAL (mismo camino que Provisiones)
# =========================================================
class VinsNuevosContratoAlertDialog(QDialog):
    """Alerta simple (30-09-2026) para los VIN que trae el Excel de
    Contratos CM (3PC) pero que todavia no tienen fila en Comercial (RM):
    hoy importar_excel_javiera() los ignora en silencio porque solo
    actualiza VIN que ya existen. Mismo patron visual y misma idea que
    provisiones.py::VinsHuerfanosAlertDialog -- unico camino para
    resolverlos es abrir VincularContratoComercialDialog."""

    def __init__(self, vins_nuevos, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Contratos nuevos sin ficha en Comercial")
        self.setMinimumWidth(440)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)

        encabezado = QHBoxLayout()
        encabezado.setSpacing(12)
        icono = QLabel()
        icono.setPixmap(ThemeManager.icon('fa5s.truck-loading', color=PRIMARY).pixmap(QSize(30, 30)))
        encabezado.addWidget(icono)
        titulo = QLabel(f"{len(vins_nuevos)} contrato(s) sin ficha en Comercial")
        titulo.setWordWrap(True)
        ThemeManager.style_subtitle(titulo)
        encabezado.addWidget(titulo, stretch=1)
        layout.addLayout(encabezado)

        explicacion = QLabel(
            "El Excel de Contratos CM trae datos para estos VIN, pero todavía no existen en la "
            "Base Comercial (PruebasFM) -- hoy quedan ignorados. Podés vincularlos ahora con un "
            "cliente que ya exista en Comercial (Razón Social, RUT, CDB) usando el nombre que trae "
            "el propio Excel, o hacerlo más tarde."
        )
        explicacion.setWordWrap(True)
        explicacion.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(explicacion)

        lista = QListWidget()
        lista.addItems([f"{info['VIN']} · {info.get('CLIENTE', '-')}" for info in vins_nuevos])
        lista.setMaximumHeight(130)
        layout.addWidget(lista)

        botones = QHBoxLayout()
        botones.addStretch()
        self.btn_despues = QPushButton(" Más tarde")
        ThemeManager.apply_secondary_button(self.btn_despues)
        self.btn_despues.clicked.connect(self.reject)
        botones.addWidget(self.btn_despues)

        self.btn_vincular = QPushButton(" Vincular ahora")
        self.btn_vincular.setIcon(ThemeManager.icon('fa5s.link', color='white'))
        ThemeManager.apply_primary_button(self.btn_vincular)
        self.btn_vincular.clicked.connect(self.accept)
        botones.addWidget(self.btn_vincular)
        layout.addLayout(botones)


class VincularContratoComercialDialog(QDialog):
    """Único camino para resolver un VIN de Contratos CM sin ficha en
    Comercial. A diferencia de provisiones.py::VincularComercialDialog (que
    saca el 'CLIENTE' de Provisiones), acá el nombre del cliente viene
    directo del propio Excel de Javiera (columna "Current Invoicing
    Customer Name"), así que no hace falta cruzar con otro archivo. Busca
    candidatos contra la Razón Social ya existente en Comercial con
    provisiones_services.buscar_candidatos_por_cliente() (función pura,
    sin nada específico de Provisiones) y arma el registro nuevo con
    contratos_service.construir_registro_nuevo_desde_contrato_cm(), que
    reutiliza los mismos defaults de 'Gestión de Unidades'."""

    vin_resuelto = pyqtSignal(str)

    def __init__(self, vins_pendientes, data_manager, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Vincular con Comercial (RM)")
        self.resize(760, 560)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")
        self.data_manager = data_manager
        self.vins_pendientes = list(vins_pendientes)
        self.candidatos_actuales = []
        self._add_thread = None
        self._setup_ui()
        self._cargar_vin_actual()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("VIN a vincular:"))
        self.combo_vin = estilo_com.ComboTarjeta("VIN a vincular")
        self.combo_vin.addItems([info['VIN'] for info in self.vins_pendientes])
        self.combo_vin.currentIndexChanged.connect(self._cargar_vin_actual)
        layout.addWidget(self.combo_vin)

        self.lbl_cliente = QLabel()
        self.lbl_cliente.setWordWrap(True)
        self.lbl_cliente.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self.lbl_cliente)

        layout.addWidget(QLabel("Coincidencias encontradas en Comercial (selecciona una; ninguna si no corresponde):"))
        self.tabla_candidatos = QTableWidget(0, 4)
        self.tabla_candidatos.setHorizontalHeaderLabels(["Razón Social", "RUT", "CDB", "Ejecutivo"])
        self.tabla_candidatos.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tabla_candidatos.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tabla_candidatos.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla_candidatos.horizontalHeader().setStretchLastSection(True)
        self.tabla_candidatos.itemSelectionChanged.connect(self._actualizar_preview)
        layout.addWidget(self.tabla_candidatos, stretch=1)

        self.lbl_preview = QLabel()
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 11px; padding: 8px; background-color: white; border-radius: 6px;"
        )
        layout.addWidget(self.lbl_preview)

        btn_layout = QHBoxLayout()
        self.btn_cerrar = QPushButton(" Cerrar")
        ThemeManager.apply_secondary_button(self.btn_cerrar)
        self.btn_cerrar.clicked.connect(self.close)

        self.btn_confirmar = QPushButton(" Confirmar y Crear en RM")
        ThemeManager.apply_primary_button(self.btn_confirmar)
        self.btn_confirmar.clicked.connect(self._confirmar)

        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cerrar)
        btn_layout.addWidget(self.btn_confirmar)
        layout.addLayout(btn_layout)

    def _vin_actual(self):
        idx = self.combo_vin.currentIndex()
        if idx < 0 or idx >= len(self.vins_pendientes):
            return None
        return self.vins_pendientes[idx]

    def _cargar_vin_actual(self):
        self.tabla_candidatos.setRowCount(0)
        self.candidatos_actuales = []
        self.lbl_preview.clear()

        info = self._vin_actual()
        if not info:
            self.lbl_cliente.setText("")
            self.btn_confirmar.setEnabled(False)
            return

        cliente = info.get('CLIENTE', '')
        self.lbl_cliente.setText(f'Cliente en el Excel de Contratos: "{cliente}"')
        self.candidatos_actuales = provisiones_services.buscar_candidatos_por_cliente(
            self.data_manager.df_master, cliente
        )

        self.tabla_candidatos.setRowCount(len(self.candidatos_actuales))
        for row, cand in enumerate(self.candidatos_actuales):
            for col, campo in enumerate(['RAZÓN SOCIAL', 'RUT', 'CDB', 'EJECUTIVO']):
                self.tabla_candidatos.setItem(row, col, QTableWidgetItem(str(cand.get(campo, ''))))

        self.btn_confirmar.setEnabled(True)
        self._actualizar_preview()

    def _candidato_seleccionado(self):
        filas = self.tabla_candidatos.selectionModel().selectedRows() if self.tabla_candidatos.selectionModel() else []
        if not filas:
            return None
        return self.candidatos_actuales[filas[0].row()]

    def _actualizar_preview(self):
        info = self._vin_actual()
        if not info:
            return
        registro = ct_service.construir_registro_nuevo_desde_contrato_cm(info['VIN'], info, self._candidato_seleccionado())
        self.lbl_preview.setText(
            f"VIN: {registro['VIN']}  ·  CHASIS: {registro['CHASIS']}  ·  MODELO: {registro['MODELO']}\n"
            f"Razón Social: {registro['RAZÓN SOCIAL'] or '(sin coincidencia)'}  ·  "
            f"RUT: {registro['RUT'] or '-'}  ·  CDB: {registro['CDB'] or '-'}  ·  "
            f"Ejecutivo: {registro['EJECUTIVO'] or '-'}\n"
            f"N° Contrato 3PC: {registro['N CONTRATO 3PC']}  ·  "
            f"Tipo de CM: {registro['TIPO DE CM']}  ·  Estado del CM: {registro['ESTADO DEL CM']}\n"
            f"Fecha Inicio CM: {registro['FECHA INICIO CM']}  ·  Fecha Término CM: {registro['FECHA TERMINO CM']}  ·  "
            f"Pago CM: {registro['PAGO CM']}\n"
            f"Estado Comercial: {registro['ESTADO COMERCIAL']}  ·  "
            f"Forma de Contrato: {registro['FORMA DE CONTRATO']}  ·  "
            f"Etapa Gestión: {registro['ETAPA GESTIÓN']}\n"
            f"Observaciones: {registro['OBSERVACIONES']}"
        )

    def _confirmar(self):
        info = self._vin_actual()
        if not info:
            return
        candidato = self._candidato_seleccionado()
        if candidato is None:
            respuesta = QMessageBox.question(
                self, "Sin coincidencia comercial",
                f"No seleccionaste ninguna coincidencia para el VIN {info['VIN']}. Se creará igual, pero sin "
                "Razón Social/RUT/CDB/Ejecutivo (quedará marcado para revisión manual).\n\n¿Continuar?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

        registro = ct_service.construir_registro_nuevo_desde_contrato_cm(info['VIN'], info, candidato)
        id_nuevo = comercial_services.proximo_id_contrato(self.data_manager.df_master)
        if id_nuevo:
            registro['ID'] = id_nuevo

        from src.ui.comercial import AddRowThread
        self.btn_confirmar.setEnabled(False)
        self._add_thread = AddRowThread(ExcelWriter(), registro, module_name="Contratos CM (Vinculación RM)")
        self._add_thread.finished_signal.connect(lambda ok, data: self._on_creado(ok, data, info['VIN']))
        self._add_thread.start()

    def _on_creado(self, success, new_data, vin):
        self.btn_confirmar.setEnabled(True)
        if not success:
            QMessageBox.warning(self, "Error", f"No se pudo crear el registro para VIN {vin} en la Base Comercial.")
            return

        dm = self.data_manager
        if not dm.df_master.empty:
            dm.df_master = comercial_services.agregar_fila(dm.df_master, new_data)
            dm.data_ready.emit()

        QMessageBox.information(self, "Vinculado", f"Se creó el registro para VIN {vin} en la Base Comercial.")
        self.vins_pendientes = [info for info in self.vins_pendientes if info['VIN'] != vin]
        self.vin_resuelto.emit(vin)

        self.combo_vin.blockSignals(True)
        self.combo_vin.clear()
        self.combo_vin.addItems([info['VIN'] for info in self.vins_pendientes])
        self.combo_vin.blockSignals(False)

        if not self.vins_pendientes:
            QMessageBox.information(self, "Listo", "No quedan VIN pendientes por vincular.")
            self.accept()
            return
        self._cargar_vin_actual()


# =========================================================
# CLASE PRINCIPAL DEL MÓDULO CONTRATOS
# =========================================================
COL_CONTRATOS_TABLA = "CONTRATOS"
COL_VIGENTES_TABLA = "VIGENTES"
COL_DESCONECTADOS_TABLA = "DESCONECTADOS"
COL_ACTIVANDO_TABLA = "ACTIVANDO"
COL_CDB_VARIOS = "CDB_VARIOS"
_COLUMNAS_EMPRESAS_CM = [COL_RAZON_SOCIAL, COL_RUT, COL_CDB_FLOTA, COL_VIGENTES_TABLA, COL_DESCONECTADOS_TABLA,
                         COL_ACTIVANDO_TABLA, COL_CONTRATOS_TABLA, COL_CDB_VARIOS]
COL_ACTIVACION_TABLA = "ACTIVACIÓN"
_COLUMNAS_DETALLE_CM = [
    'ID', COL_ACTIVACION_TABLA, 'VIN', 'CHASIS', 'N CONTRATO 3PC', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'TIPO DE CM', 'ESTADO DEL CM', 'PAGO CM',
]
_CHIP_VOLVO = ("#E1EAF4", VOLVO_BLUE)
_CHIP_VIGENTES = ("#E3F6EE", "#0F9D6E")
_CHIP_DESCONECTADOS = ("#FDE5E5", "#E04848")
_CHIP_CDB_VARIOS = ("#FEF3C7", "#92400E")
_CHIP_ACTIVANDO = ("#FFF1D6", "#B45309")
_CHIPS_ACTIVACION = {"CONECTADO": _CHIP_VIGENTES, "DESCONECTADO": _CHIP_DESCONECTADOS, "ACTIVANDO": _CHIP_ACTIVANDO}
_CHIPS_CONTEO_EMPRESAS = {COL_VIGENTES_TABLA: _CHIP_VIGENTES, COL_DESCONECTADOS_TABLA: _CHIP_DESCONECTADOS,
                         COL_ACTIVANDO_TABLA: _CHIP_ACTIVANDO}

# (título, clave, color, descripción)
_KPI_SPECS_CM = [
    ("Unidades con CM", "total", "#1F6FEB", "Unidades con un contrato de mantenimiento (N° Contrato 3PC)."),
    ("Con CM y VC", "vc", "#0F766E", "Unidades con contrato CM cuyo estado de activación es Conectado en Volvo Connect."),
    ("Ausentes de la carga", "ausentes", DANGER,
     "Unidades que están en el RM con contrato CM pero no vinieron en la última carga del Excel 3PC. "
     "Hay que revisar si corresponde darlas de baja."),
    ("Pago CM total", "pago", "#B45309", "Suma de PAGO CM de los contratos mostrados."),
]


class ContratosModule(PantallaIngresosBase):
    """Modulo 'Contratos (CM)': dos niveles (empresas -> contratos) con el
    esqueleto de Comercial/Operaciones (ver ingresos_base.py) y el color de
    acento del chip de titulo de main_window (MODULE_COLORS['Contratos (CM)']).

    Debajo sigue el mismo motor de datos/guardado que tenia la version en
    tabla (on_item_edited, pending_changes, confirm_save, self.model/
    self.table, ocultos) -- no se reescribio; la edicion pasa por el
    formulario de unidad compartido (formulario_unidad.py), que llama a
    on_item_edited una vez por campo y termina en confirm_save().

    Diseño decidido junto al usuario (05-10-2026): KPIs Unidades con CM, Con
    CM y VC, Ausentes de la carga y Pago CM total; filtros de Estado y Tipo
    de CM en combos; 'Importar Excel CM' y 'Excel' como botones blancos de la
    barra. Desde el 19-09-2026 la pantalla solo muestra VIN con contrato (ver
    contratos_service.filtrar_con_contrato) y el boton 'Guardar' vive dentro
    del formulario de unidad.
    """

    AVATAR = "CM"
    TITULO = "Contratos (CM)"
    KPI_SPECS = _KPI_SPECS_CM
    CAMPOS_FICHA = [
        ("N° Contrato", "ID"), ("N° Contrato 3PC", "N CONTRATO 3PC"), ("Tipo de CM", "TIPO DE CM"),
        ("Estado del CM", "ESTADO DEL CM"), ("Pago CM", "PAGO CM"),
        ("Inicio CM", "FECHA INICIO CM"), ("Término CM", "FECHA TERMINO CM"),
    ]
    COLUMNAS_OCULTAS = PantallaIngresosBase.COLUMNAS_OCULTAS + (COL_CDB_VARIOS, 'ID')
    ANCHOS_EMPRESAS = {COL_RAZON_SOCIAL: 400, COL_RUT: 140, COL_CDB_FLOTA: 170, COL_VIGENTES_TABLA: 120,
                       COL_DESCONECTADOS_TABLA: 150, COL_ACTIVANDO_TABLA: 120, COL_CONTRATOS_TABLA: 130}
    ANCHOS_DETALLE = {
        'ID': 80, COL_ACTIVACION_TABLA: 160, 'VIN': 170, 'CHASIS': 110, 'N CONTRATO 3PC': 150, 'FECHA INICIO CM': 140, 'FECHA TERMINO CM': 150,
        'TIPO DE CM': 120, 'ESTADO DEL CM': 130, 'PAGO CM': 120,
    }

    def __init__(self):
        super().__init__()
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.search_input = QLineEdit()
        self.search_input.hide()
        self.search_input.textChanged.connect(self.filter_table)
        self.current_kpi_filter = "total"
        self.filtro_estado_cm = ""
        self.filtro_tipo_cm = ""
        self._vins_ausentes = set()
        self._vins_conectados = set()
        self.pending_changes = {}  # Mochila de edición manual (indexada por VIN)
        self.import_changes = {}   # Mochila de importación masiva
        self._data_dirty = False

        self.data_manager.data_ready.connect(self._on_global_data_ready)
        self.data_manager.load_error.connect(self._on_load_error)

        self._setup_ui()
        self.load_data()

    def _setup_ui(self):
        self.construir_base()

        self.combo_estado_cm = ComboFiltroBarra('fa5s.flag', "Estado del CM")
        self.combo_tipo_cm = ComboFiltroBarra('fa5s.tag', "Tipo de CM")
        for combo, ancho in ((self.combo_estado_cm, 170), (self.combo_tipo_cm, 160)):
            combo.setMinimumWidth(ancho)
            ThemeManager.apply_combo_box(combo)
            combo.setStyleSheet(estilo_combo_barra())
            combo.setMaxVisibleItems(9)
            self.agregar_filtro_compacto(combo)
        self.combo_estado_cm.currentIndexChanged.connect(self._on_combo_estado_cm)
        self.combo_tipo_cm.currentIndexChanged.connect(self._on_combo_tipo_cm)

        self.btn_importar = boton_barra("", 'fa5s.plus')
        self.btn_importar.setToolTip("Importar Excel CM")
        self.btn_importar.clicked.connect(self.importar_excel_javiera)
        self.agregar_capsula(self.btn_importar)

        self.btn_export_excel = boton_barra("", 'fa5s.file-excel', 'excel')
        self.btn_export_excel.setToolTip("Exportar a Excel")
        self.btn_export_excel.setFixedWidth(44)
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='#1B2B4E'))
        self.btn_export_excel.clicked.connect(lambda: self.table.export_to_excel("Reporte_CM"))
        self.agregar_general(self.btn_export_excel)

        self.btn_reload = boton_barra("", 'fa5s.sync-alt')
        self.btn_reload.setToolTip("Recargar")
        self.btn_reload.clicked.connect(self.recargar_desde_cero)
        self.agregar_general(self.btn_reload)

        self.btn_editar_unidad = estilo_com.BotonAccionPanel(
            'fa5s.edit', 'Editar unidad',
            "Abre el formulario de la unidad en la pestaña JustTime & CM.", VOLVO_BLUE)
        self.btn_editar_unidad.setEnabled(False)
        self.btn_editar_unidad.clicked.connect(self._on_editar_unidad_clicked)
        self.agregar_accion_panel(self.btn_editar_unidad)

        # --- MOTOR DE DATOS OCULTO ---
        # self.table/self.model nunca se agregan a un layout visible: siguen
        # siendo el mismo motor de on_item_edited/confirm_save de antes (ver
        # docstring de la clase) y también alimentan 'Exportar Excel'
        # (VolvoTableWidget.export_to_excel), reutilizado sin duplicar su
        # lógica de formato de columnas monetarias.
        self.table = VolvoTableWidget()
        self.model = PandasTableModel()
        opciones_desplegables = {
            'TIPO DE CM': TIPO_CM_OPCIONES,
            'ESTADO DEL CM': ESTADO_CM_OPCIONES,
        }
        self.table.set_model_and_delegate(self.model, opciones_desplegables)

        # Pantalla de carga: la bandeja (barra + tabla) y la tarjeta de carga
        # comparten un QStackedWidget (0 = cargando, 1 = contenido)
        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tarjeta_carga = crear_tarjeta_carga("Procesando datos en segundo plano…", "Esto tomará unos segundos.")
        self.lbl_loading_text = tarjeta_carga.lbl
        loading_layout.addWidget(tarjeta_carga, alignment=Qt.AlignmentFlag.AlignCenter)
        main_layout = self.layout()
        main_layout.removeWidget(self._contenido)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.loading_widget)  # Index 0
        self.stack.addWidget(self._contenido)      # Index 1
        main_layout.addWidget(self.stack, 1)
        self.stack.setCurrentIndex(1)

    # --------------------------------------------- ganchos de la pantalla base
    def resolver_color(self, columna, valor, es_fondo):
        if columna in ('TIPO DE CM', 'ESTADO DEL CM'):
            if str(valor).strip() in ("", "-"):
                return None
            colores = _BADGE_COLOR.get(str(valor).strip().upper(), _BADGE_COLOR_DEFAULT)
            return colores[0] if es_fondo else colores[1]
        if columna == COL_CONTRATOS_TABLA:
            return _CHIP_VOLVO[0 if es_fondo else 1]
        if columna == COL_CDB_FLOTA and self.empresa_actual is None and self.modelo.valor_fila_resuelta(COL_CDB_VARIOS) == "1":
            return _CHIP_CDB_VARIOS[0 if es_fondo else 1]
        if columna == COL_ACTIVACION_TABLA:
            colores = _CHIPS_ACTIVACION.get(str(valor).strip().upper())
            return colores[0 if es_fondo else 1] if colores else None
        if columna in _CHIPS_CONTEO_EMPRESAS and str(valor).strip() not in ("", "0"):
            return _CHIPS_CONTEO_EMPRESAS[columna][0 if es_fondo else 1]
        return None

    def colores_chip_ficha(self, columna, valor):
        if columna in ('TIPO DE CM', 'ESTADO DEL CM'):
            return _BADGE_COLOR.get(str(valor).strip().upper(), _BADGE_COLOR_DEFAULT)
        return None

    def on_kpi_clicado(self, clave):
        self.current_kpi_filter = "total" if self.current_kpi_filter == clave else clave
        self.filter_table()

    def _on_combo_estado_cm(self, _i):
        valor = self.combo_estado_cm.currentData() or ""
        if valor != self.filtro_estado_cm:
            self.filtro_estado_cm = valor
            self.filter_table()

    def _on_combo_tipo_cm(self, _i):
        valor = self.combo_tipo_cm.currentData() or ""
        if valor != self.filtro_tipo_cm:
            self.filtro_tipo_cm = valor
            self.filter_table()

    def on_fila_cambiada(self, fila, cantidad):
        if cantidad == 0:
            self.btn_editar_unidad.setEnabled(False)
            return
        aviso = ""
        if str(fila.get('VIN', '')).strip().upper() in self._vins_ausentes:
            aviso = "⚠  Ausente de la última carga del Excel 3PC. Revisa si corresponde darla de baja."
        self._pintar_panel(fila, cantidad, aviso)
        self.btn_editar_unidad.setEnabled(cantidad == 1)

    def _on_editar_unidad_clicked(self):
        vins = self._vins_seleccionados()
        if len(vins) != 1:
            return
        fila = self._fila_por_vin.get(vins[0], {})
        self._abrir_form_contrato(int(fila.get('_ROW_IDX', 0)), fila)

    def al_cambiar_nivel(self):
        self.search_input.clear()
        self.filter_table()

    def recargar_desde_cero(self):
        self.btn_reload.setEnabled(False)
        self.btn_importar.setEnabled(False)

        self.lbl_loading_text.setText("Recargando la base de datos maestra desde cero...")
        self.stack.setCurrentIndex(0)

        QApplication.processEvents()
        self.data_manager.load_data_async()

        QTimer.singleShot(12000, self._force_unlock_buttons)

    def _force_unlock_buttons(self):
        if not self.btn_reload.isEnabled():
            self.btn_reload.setEnabled(True)
            self.btn_importar.setEnabled(True)
            self.stack.setCurrentIndex(1)
            print("Seguro Anti-Congelamiento activado en Contratos.")

    def _on_global_data_ready(self):
        try:
            if self.isVisible():
                self.load_data()
            else:
                self._data_dirty = True
        except Exception:
            pass
        finally:
            self.btn_reload.setEnabled(True)
            self.btn_importar.setEnabled(True)
            self.stack.setCurrentIndex(1)

    def refresh_if_dirty(self):
        """Llamado por MainWindow._trigger_load_data al navegar a este
        modulo. Protege pending_changes con el mismo patron de dialogo de 3
        opciones que usa ComercialModule/OperacionesModule."""
        if not self._data_dirty:
            return

        if self.pending_changes:
            self._confirmar_recarga_con_cambios_pendientes()
        else:
            self.load_data()

    def _confirmar_recarga_con_cambios_pendientes(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Base de datos modificada")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText("La base de datos cambió mientras tenías cambios sin guardar en Contratos.")
        msg.setInformativeText(
            "Tienes cambios sin guardar en esta pantalla.\n\n"
            "• Si presionas 'Guardar mis cambios', se aplicarán a la base de datos.\n"
            "• Si presionas 'Descartar y Recargar', perderás tus cambios y verás los datos actualizados."
        )
        btn_guardar = msg.addButton("Guardar mis cambios", QMessageBox.ButtonRole.AcceptRole)
        btn_recargar = msg.addButton("Descartar y Recargar", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)

        msg.exec()

        if msg.clickedButton() == btn_guardar:
            self.confirm_save()
        elif msg.clickedButton() == btn_recargar:
            self.load_data()

    def _on_load_error(self, error_msg):
        self.btn_reload.setEnabled(True)
        self.btn_importar.setEnabled(True)
        self.stack.setCurrentIndex(1)
        QMessageBox.critical(self, "Error al Cargar", f"Ocurrió un problema:\n{error_msg}")

    # =========================================================
    # CARGA DE DATOS: siempre desde DataManager().df_master, ya en RAM.
    # self.df_base ya viene recortado al universo real de contratos
    # (contratos_service.filtrar_con_contrato) -- reemplaza al viejo
    # checkbox 'Ocultar sin contrato (-)', que por defecto siempre estaba
    # activado.
    # =========================================================
    def _leer_vins_ausentes(self):
        """VIN con un caso pendiente de 'Ausencia de 3PC': estaban en el RM
        con CM y no vinieron en la última carga del Excel (ver
        cm_bajas_service)."""
        try:
            df_casos = cm_bajas_service.leer_casos_baja_cm(config.settings.CASOS_BAJA_CM_PATH)
        except Exception as e:
            logger.error(f"No se pudieron leer los casos de baja CM: {e}")
            return set()
        if df_casos.empty:
            return set()
        mascara = (df_casos['ESTADO_CASO'] == cm_bajas_service.ESTADO_CASO_PENDIENTE) & \
                  (df_casos['ORIGEN_CASO'] == cm_bajas_service.ORIGEN_CASO_AUSENCIA_3PC)
        return {str(v).strip().upper() for v in df_casos.loc[mascara, 'VIN']}

    def load_data(self):
        self._data_dirty = False
        self.pending_changes.clear()
        df_master = comercial_services.excluir_contratos_cerrados(
            self.data_manager.get_contratos_actuales_df())
        if df_master.empty:
            self.df_base = pd.DataFrame()
            self.model.set_data(pd.DataFrame())
            self._vins_conectados = set()
        else:
            df_base_completo = ct_service.preparar_base_contratos(df_master)
            self.df_base = ct_service.filtrar_con_contrato(df_base_completo)
            if COL_ESTADO_ACTIVACION in df_master.columns:
                conectada = df_master[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper() == 'CONECTADO'
                self._vins_conectados = set(df_master.loc[conectada, 'VIN'].astype(str).str.strip().str.upper())
            else:
                self._vins_conectados = set()
        self._vins_ausentes = self._leer_vins_ausentes()

        empresas_disponibles = set(ct_service.obtener_empresas(self.df_base)[COL_RAZON_SOCIAL]) if not self.df_base.empty else set()
        if self.empresa_actual is not None and self.empresa_actual not in empresas_disponibles:
            self.empresa_actual = None
            self.actualizar_titulo()
        self.filter_table()

    def _poblar_combo(self, combo, serie, titulo_todos, valor_actual):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(titulo_todos, "")
        for valor, cantidad in serie.value_counts().items():
            if str(valor).strip() in ("", "-"):
                continue
            combo.addItem(f"{valor} ({cantidad})", str(valor))
        pos = combo.findData(valor_actual)
        combo.setCurrentIndex(pos if pos >= 0 else 0)
        combo.blockSignals(False)

    def filter_table(self):
        if not hasattr(self, 'df_base') or self.df_base.empty:
            self.model.set_data(pd.DataFrame())
            for clave, tarjeta in self.botones_kpi.items():
                tarjeta.setChecked(False)
                tarjeta.actualizar("$-" if clave == "pago" else 0, None if clave == "pago" else 0.0, "")
            self._df_tabla = pd.DataFrame(columns=_COLUMNAS_EMPRESAS_CM)
            self._fila_por_vin = {}
            self.lbl_subtitulo.setText("0 empresas · 0 contratos")
            self.lbl_sin_resultados.setVisible(True)
            self._pintar_tabla()
            return

        df_global = self.df_base.copy()

        search_text = self.search_input.text().lower()
        if search_text:
            # RUT agregado 28-09-2026, a pedido explicito.
            cols = [c for c in ['VIN', 'CHASIS', COL_RAZON_SOCIAL, COL_RUT] if c in df_global.columns]
            mask = comercial_services.construir_mascara_busqueda(
                df_global, search_text.strip(), cols, ('ID',))
            df_global = df_global[mask]

        vin_norm = df_global['VIN'].astype(str).str.strip().str.upper()
        total_cm = len(df_global)
        con_vc = int(vin_norm.isin(self._vins_conectados).sum())
        ausentes = int(vin_norm.isin(self._vins_ausentes).sum())
        total_dinero = df_global[df_global['PAGO CM_NUM'] > 0]['PAGO CM_NUM'].sum() if 'PAGO CM_NUM' in df_global.columns else 0

        def fraccion(valor):
            return (valor / total_cm) if total_cm else 0.0

        valores = {
            "total": (total_cm, 1.0, "contratos de mantenimiento"),
            "vc": (con_vc, fraccion(con_vc), f"de {total_cm} unidades"),
            "ausentes": (ausentes, fraccion(ausentes), "por revisar su baja"),
            "pago": (_formato_pago(total_dinero), None, "suma de pagos CM"),
        }
        for clave, tarjeta in self.botones_kpi.items():
            valor, porcentaje, pie = valores[clave]
            tarjeta.setChecked(clave == self.current_kpi_filter)
            tarjeta.actualizar(valor, porcentaje, pie)

        self._poblar_combo(self.combo_estado_cm, df_global['ESTADO DEL CM'], "Todos los estados", self.filtro_estado_cm) \
            if 'ESTADO DEL CM' in df_global.columns else None
        self._poblar_combo(self.combo_tipo_cm, df_global['TIPO DE CM'], "Todos los tipos", self.filtro_tipo_cm) \
            if 'TIPO DE CM' in df_global.columns else None

        df_f = df_global.copy()
        if self.current_kpi_filter == "vc":
            df_f = df_f[vin_norm.isin(self._vins_conectados)]
        elif self.current_kpi_filter == "ausentes":
            df_f = df_f[vin_norm.isin(self._vins_ausentes)]
        elif self.current_kpi_filter == "pago":
            df_f = df_f[df_f['PAGO CM_NUM'] > 0]
        if self.filtro_estado_cm and 'ESTADO DEL CM' in df_f.columns:
            df_f = df_f[df_f['ESTADO DEL CM'] == self.filtro_estado_cm]
        if self.filtro_tipo_cm and 'TIPO DE CM' in df_f.columns:
            df_f = df_f[df_f['TIPO DE CM'] == self.filtro_tipo_cm]

        # --- APLICAMOS LA PERSISTENCIA DE EDICIÓN AL DATAFRAME ---
        if self.pending_changes:
            for vin_key, data in self.pending_changes.items():
                mask = df_f['VIN'].astype(str).str.strip().str.upper() == vin_key
                if mask.any():
                    for col_c, val_c in data['cambios'].items():
                        if col_c in df_f.columns:
                            df_f[col_c] = df_f[col_c].astype(object)
                            df_f.loc[mask, col_c] = val_c

        if 'FECHA INICIO CM' in df_f.columns:
            df_f['_FECHA_SORT'] = pd.to_datetime(df_f['FECHA INICIO CM'], format='%d-%m-%Y', errors='coerce')
            df_f = df_f.sort_values(by='_FECHA_SORT', ascending=False, na_position='last')
            df_f = df_f.drop(columns=['_FECHA_SORT'])

        if 'PAGO CM' in df_f.columns:
            df_f['PAGO CM'] = df_f['PAGO CM_NUM'].apply(_formato_pago)

        df_display = df_f.drop(columns=['PAGO CM_NUM'], errors='ignore')
        df_display.insert(0, 'N°', range(1, len(df_display) + 1))

        self.model.set_data(df_display)

        # --- REPINTAMOS DE NARANJA LAS CELDAS QUE HABÍAN SIDO EDITADAS (bookkeeping interno, sin tabla visible) ---
        if self.pending_changes:
            for r in range(len(df_display)):
                v_val = str(df_display.iat[r, df_display.columns.get_loc('VIN')]).strip().upper()
                if v_val in self.pending_changes:
                    for c_name in self.pending_changes[v_val]['cambios']:
                        if c_name in df_display.columns:
                            c_idx = df_display.columns.get_loc(c_name)
                            self.model._edited_cells.add((r, c_idx))

        # --- TABLA VISIBLE: mismas filas de df_display, mismas posiciones (0-based) que usa el modelo ---
        df_posicional = df_display.reset_index(drop=True)
        if self.empresa_actual is None:
            df_empresas = ct_service.obtener_empresas(df_posicional)
            self._df_tabla = self._armar_tabla_empresas(df_empresas)
            self.lbl_subtitulo.setText(f"{len(df_empresas)} empresas · {len(df_posicional)} contratos")
        else:
            df_contratos = ct_service.obtener_contratos_empresa(df_posicional, self.empresa_actual)
            self._df_tabla = self._armar_tabla_contratos(df_contratos)
            self.lbl_subtitulo.setText(f"{len(df_contratos)} contratos")
        self.lbl_sin_resultados.setVisible(self._df_tabla.empty)
        self._pintar_tabla()

    def _armar_tabla_empresas(self, df_empresas):
        self._fila_por_vin = {}
        if df_empresas.empty:
            return pd.DataFrame(columns=_COLUMNAS_EMPRESAS_CM)
        ruts = df_empresas[COL_RUT].astype(str).tolist() if COL_RUT in df_empresas.columns else [""] * len(df_empresas)
        return pd.DataFrame({
            COL_RAZON_SOCIAL: df_empresas[COL_RAZON_SOCIAL].astype(str).tolist(),
            COL_RUT: ruts,
            COL_CDB_FLOTA: df_empresas[COL_CDB_FLOTA].astype(str).tolist(),
            COL_VIGENTES_TABLA: df_empresas["VIGENTES"].astype(int).astype(str).tolist(),
            COL_DESCONECTADOS_TABLA: df_empresas["DESCONECTADOS"].astype(int).astype(str).tolist(),
            COL_ACTIVANDO_TABLA: df_empresas["ACTIVANDO"].astype(int).astype(str).tolist(),
            COL_CONTRATOS_TABLA: df_empresas["UNIDADES"].astype(int).astype(str).tolist(),
            COL_CDB_VARIOS: df_empresas["CDB_VARIOS"].map({True: "1", False: ""}).tolist(),
        }, columns=_COLUMNAS_EMPRESAS_CM)

    def _armar_tabla_contratos(self, df_contratos):
        self._fila_por_vin = {}
        if df_contratos.empty:
            return pd.DataFrame(columns=_COLUMNAS_DETALLE_CM)
        origen = {COL_ACTIVACION_TABLA: COL_ESTADO_ACTIVACION}
        df = pd.DataFrame({col: (df_contratos[origen.get(col, col)].astype(str).tolist() if origen.get(col, col) in df_contratos.columns
                                 else ["-"] * len(df_contratos)) for col in _COLUMNAS_DETALLE_CM})
        for pos, (row_idx, fila) in enumerate(df_contratos.iterrows()):
            registro = df.iloc[pos].to_dict()
            registro[COL_RAZON_SOCIAL] = self.empresa_actual
            registro['ESTADO COMERCIAL'] = str(fila.get('ESTADO COMERCIAL', '')).strip()
            registro['_ROW_IDX'] = int(row_idx)
            self._fila_por_vin[str(registro['VIN']).strip()] = registro
        return df

    def _abrir_form_contrato(self, row_idx, fila):
        """Mismo formulario de unidad que Comercial (formulario_unidad.py),
        abierto en "JustTime & CM" con Operaciones de solo lectura."""
        if comercial_services.es_contrato_cerrado(fila.get('ESTADO COMERCIAL', '')):
            QMessageBox.information(
                self, "Contrato finalizado",
                "Este contrato está en Baja y es de solo lectura. Si la unidad sigue conectada, Operaciones debe desconectarla.")
            return
        cambios = editar_unidad(self, self.data_manager.get_contratos_actuales_df(), fila.get('VIN', ''), PESTANA_JUSTTIME_CM)
        if cambios is None:
            return
        if not cambios:
            QMessageBox.information(self, "Sin cambios", "No se modificó ningún campo.")
            return
        self._aplicar_cambios_formulario(row_idx, cambios)

    def _aplicar_cambios_formulario(self, row_idx, cambios):
        """Aplica los campos del formulario reutilizando on_item_edited (uno
        por columna, mismo mecanismo que una edicion de celda) y termina con
        confirm_save()."""
        for col_name, new_value in cambios.items():
            self.on_item_edited(row_idx, col_name, new_value)
        self.confirm_save()

    # =========================================================
    # EVENTOS DE EDICIÓN MANUAL Y GUARDADO (sin cambios de comportamiento;
    # ahora invocado desde el formulario de unidad en vez de una celda de tabla)
    # =========================================================
    def on_item_edited(self, row, col_name, new_value):
        if col_name == 'N°':
            return

        df_actual = self.model.get_df()
        # UTILIZAMOS EL VIN COMO LLAVE MAESTRA INQUEBRANTABLE
        vin_value = str(df_actual.iat[row, df_actual.columns.get_loc('VIN')]).strip().upper()

        if vin_value not in self.pending_changes:
            self.pending_changes[vin_value] = {'VIN': vin_value, 'cambios': {}}

        # --- VALIDACIÓN INTELIGENTE DE FECHAS ---
        if col_name in ['FECHA INICIO CM', 'FECHA TERMINO CM']:
            val_limpio = str(new_value).strip()

            if val_limpio not in ["", "nan", "NaN", "-"]:
                try:
                    datetime.strptime(val_limpio, "%d-%m-%Y")
                    self.pending_changes[vin_value]['cambios'][col_name] = val_limpio
                except ValueError:
                    QMessageBox.warning(self, "Error de Formato", "La fecha debe ser estrictamente en formato: DD-MM-YYYY\n\nEjemplo válido: 15-08-2026")

                    old_row = self.df_base[self.df_base['VIN'].str.strip().str.upper() == vin_value]
                    old_val = old_row.iloc[0][col_name] if not old_row.empty else "-"

                    df_actual.iat[row, df_actual.columns.get_loc(col_name)] = str(old_val).strip()
                    self.model.layoutChanged.emit()
                    return
            else:
                self.pending_changes[vin_value]['cambios'][col_name] = "-"
                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = "-"

        # --- FORMATEADOR DE PAGO CM EN VIVO ---
        elif col_name == 'PAGO CM':
            val_limpio = str(new_value).replace('$', '').replace('.', '').replace(',', '').strip()
            try:
                val_num = float(val_limpio) if val_limpio else 0.0
                # Como texto: RM_JAVI.csv es dtype=str y un float abortaba el guardado
                self.pending_changes[vin_value]['cambios'][col_name] = str(val_num)

                formato = _formato_pago(val_num)
                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = formato

            except ValueError:
                QMessageBox.warning(self, "Error", "El pago debe ser un número válido.")

                old_row = self.df_base[self.df_base['VIN'].str.strip().str.upper() == vin_value]
                old_val = old_row.iloc[0]['PAGO CM_NUM'] if not old_row.empty else 0
                old_formato = _formato_pago(old_val)

                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = old_formato
                self.model.layoutChanged.emit()
                return

        else:
            self.pending_changes[vin_value]['cambios'][col_name] = new_value

        self.model.layoutChanged.emit()

    def confirm_save(self):
        comercial_services.agregar_id_a_cambios(self.pending_changes, self.data_manager.get_contratos_actuales_df())
        valid = {k: d for k, d in self.pending_changes.items() if d.get('cambios')}
        if not valid: return QMessageBox.information(self, "Sin cambios", "No hay datos modificados.")

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirmar")
        msg.setText("Se aplicarán y guardarán en la nube los cambios de los contratos.")
        msg.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Save:
            self._iniciar_guardado(valid)

    def _iniciar_guardado(self, valid, texto="Guardando contratos en la nube…"):
        self.btn_reload.setEnabled(False)
        self.btn_importar.setEnabled(False)

        mostrar_guardando(self, texto)

        self.save_thread = SaveContratosThread(self.writer, valid)
        self.save_thread.finished_signal.connect(self._on_save_finished)
        self.save_thread.start()

    def _on_save_finished(self, success):
        self.btn_reload.setEnabled(True)
        self.btn_importar.setEnabled(True)

        if success:
            guardado_listo(self)
            try:
                dm = self.data_manager
                if not dm.df_master.empty:
                    dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master.copy(), self.pending_changes)

                    try:
                        cm_bajas_service.procesar_reconciliacion_estado_expired(
                            df_pruebas_actual=dm.df_master,
                            periodo_deteccion=datetime.now().strftime('%Y-%m'),
                            casos_path=config.settings.CASOS_BAJA_CM_PATH,
                        )
                    except Exception as e:
                        logger.error(f"No se pudo reconciliar los casos de Revisión CM por estado Expired: {e}")

                self.pending_changes.clear()
                self.load_data()
                self.stack.setCurrentIndex(1)
                terminar_guardando(self)
            except Exception as e:
                print(f"Error inyectando RAM en Contratos: {e}")
                terminar_guardando(self, exito=False)
                self.recargar_desde_cero()
        else:
            terminar_guardando(self, exito=False)
            self.stack.setCurrentIndex(1)
            QMessageBox.warning(self, "Error", "No se guardaron los cambios. SharePoint puede estar bloqueando el archivo. Intenta de nuevo.")

    # =========================================================
    # IMPORTACIÓN MASIVA (sin cambios de comportamiento)
    # =========================================================
    def importar_excel_javiera(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Seleccionar Excel de Contratos", "", "Excel (*.xlsx *.xls)")
        if not filepath: return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            from src.ui.comercial_agregar import _MESES
            df_import = pd.read_excel(filepath)
            df_import.columns = df_import.columns.astype(str).str.strip().str.upper()

            col_vin = next((c for c in df_import.columns if 'VIN NO' in c or 'VIN' in c), None)
            col_contrato = next((c for c in df_import.columns if 'CONTRACT NO' in c), None)
            col_inicio = next((c for c in df_import.columns if 'START DATE' in c), None)
            col_termino = next((c for c in df_import.columns if 'EXPIRING DATE' in c), None)
            col_estado = next((c for c in df_import.columns if 'CONTRACT STATUS' in c), None)
            col_tipo = next((c for c in df_import.columns if 'CONTRACT TYPE' in c), None)
            col_pago = next((c for c in df_import.columns if 'NET AMOUNT' in c), None)
            col_cliente = next((c for c in df_import.columns if 'CUSTOMER NAME' in c), None)

            if not col_vin:
                raise Exception("El archivo no contiene una columna identificable de VIN (Ej. 'VIN No').")

            df_import['VIN_CLEAN'] = df_import[col_vin].astype(str).str.replace(r'\s+', '', regex=True).str.upper()
            df_import = df_import.drop_duplicates(subset=['VIN_CLEAN'], keep='last')
            df_import = df_import.set_index('VIN_CLEAN')

            df_master = comercial_services.contratos_actuales(self.data_manager.df_master)
            vins_comercial = df_master['VIN'].astype(str).str.replace(r'\s+', '', regex=True).str.upper().tolist()

            # --- DETECCIÓN DE POSIBLES BAJAS CM (separada de la actualización normal) ---
            # detectar_posibles_bajas_cm() es pura (no persiste nada): se usa
            # aca para mostrar los VIN ausentes en ResumenImportacionDialog,
            # y ademas se persiste mas abajo via procesar_deteccion_baja_cm
            # (mismo criterio que ya usa Gestionar CM, sin duplicar logica).
            vins_ausentes_info = []
            try:
                vins_ausentes_info = cm_bajas_service.detectar_posibles_bajas_cm(
                    df_pruebas_antes=df_master.copy(),
                    vins_en_nuevo_listado=list(df_import.index),
                    periodo_deteccion=datetime.now().strftime('%Y-%m'),
                )
                cm_bajas_service.procesar_deteccion_baja_cm(
                    df_pruebas_antes=df_master.copy(),
                    vins_en_nuevo_listado=list(df_import.index),
                    periodo_deteccion=datetime.now().strftime('%Y-%m'),
                    casos_path=config.settings.CASOS_BAJA_CM_PATH,
                )
            except Exception as e:
                logger.error(f"No se pudo actualizar los casos de posible Baja CM: {e}")

            cambios_comercial = {}

            def limpiar_fecha(val):
                if pd.isna(val) or str(val).strip() in ['NaT', 'nan', '']: return "-"
                try: return pd.to_datetime(val).strftime("%d-%m-%Y")
                except: return str(val)

            # FORMA DE CONTRATO que puede ser sobrescrita por la regla CMG/
            # CMB/CMS (30-09-2026, a pedido explícito tras revisar una copia
            # del RM_JAVI real: 167 VIN con TIPO DE CM Gold/Blue/Silver ya
            # tenían FORMA DE CONTRATO=PROVISION/PROVISION +/CONVERSION/
            # VENTA/REVISAR -- clasificaciones de negocio distintas y
            # válidas que la regla NO debe pisar). Solo se aplica si el VIN
            # todavía no tiene una FORMA DE CONTRATO "real" asignada.
            FORMAS_CONTRATO_SOBREESCRIBIBLES = {'', '-', 'SIN CONTRATO', 'CMG', 'CMB', 'CMS'}

            def datos_cm_de_fila(row, estado_cm_anterior=None, forma_contrato_anterior=None):
                cambios = {}
                cambios['N CONTRATO 3PC'] = str(row.get(col_contrato, '-')) if pd.notna(row.get(col_contrato)) else '-'
                cambios['FECHA INICIO CM'] = limpiar_fecha(row.get(col_inicio))
                cambios['FECHA TERMINO CM'] = limpiar_fecha(row.get(col_termino))
                cambios['TIPO DE CM'] = str(row.get(col_tipo, '-')) if pd.notna(row.get(col_tipo)) else '-'
                cambios['ESTADO DEL CM'] = str(row.get(col_estado, '-')) if pd.notna(row.get(col_estado)) else '-'
                try:
                    pago_val = float(row.get(col_pago, 0))
                    # Bug real detectado (30-09-2026, simulación contra copia
                    # de RM_JAVI.csv real): guardar un float acá rompía el
                    # guardado completo en el backend CSV real (dtype=str),
                    # que aborta con "Invalid value ... for dtype 'str'" al
                    # intentar escribir un float -- fallaba en silencio
                    # (success=False) y ningún cambio del import masivo
                    # quedaba guardado. Los tests existentes no lo detectaban
                    # porque prueban contra el backend .xlsx legado, no
                    # contra el .csv real. Se guarda como texto, igual que
                    # el resto de las columnas de RM_JAVI.csv.
                    cambios['PAGO CM'] = str(pago_val) if pd.notna(pago_val) else '0.0'
                except:
                    cambios['PAGO CM'] = '0.0'

                # Regla de negocio confirmada (30-09-2026): un TIPO DE CM
                # Gold/Blue/Silver implica FORMA DE CONTRATO=CMG/CMB/CMS y
                # TIPO DE FACTURACION=CM, tanto en VIN nuevos como ya
                # existentes en Comercial -- pero solo si la FORMA DE
                # CONTRATO actual no es ya una clasificación de negocio
                # distinta (ver FORMAS_CONTRATO_SOBREESCRIBIBLES arriba). Un
                # TIPO DE CM sin mapeo ('-' o 'Current Contract Type') no
                # fuerza ningún cambio acá.
                forma_contrato = TIPO_CM_FORMA_CONTRATO_MAP.get(cambios['TIPO DE CM'])
                forma_contrato_previa_norm = str(forma_contrato_anterior).strip().upper() if forma_contrato_anterior is not None else ''
                if forma_contrato and forma_contrato_previa_norm in FORMAS_CONTRATO_SOBREESCRIBIBLES:
                    cambios['FORMA DE CONTRATO'] = forma_contrato
                    cambios['TIPO DE FACTURACION'] = VALOR_TIPO_FACT_CM

                # ESTADO COMERCIAL (30-09-2026, corregido a pedido explícito:
                # mismo criterio que ESTADO DE ACTIVACIÓN ACTUAL): un VIN que
                # ya existe en Comercial NO se toca, salvo que su ESTADO DEL
                # CM recién pase a "Expired" con ESTE import (no lo estaba
                # antes) -- ahí sí se marca "Revisar" para que alguien lo
                # mire. `estado_cm_anterior=None` (VIN nuevo, ver
                # contratos_service.construir_registro_nuevo_desde_contrato_cm)
                # no aplica esta condición: ese caso ya queda en "Revisar"
                # por default, igual que cualquier unidad creada desde cero.
                paso_a_expired_ahora = (
                    cambios['ESTADO DEL CM'].strip().upper() == 'EXPIRED'
                    and estado_cm_anterior is not None
                    and str(estado_cm_anterior).strip().upper() != 'EXPIRED'
                )
                if paso_a_expired_ahora:
                    cambios['ESTADO COMERCIAL'] = 'Revisar'
                return cambios

            estado_cm_actual_por_vin = dict(zip(vins_comercial, df_master.get('ESTADO DEL CM', pd.Series(dtype=str))))
            forma_contrato_actual_por_vin = dict(zip(vins_comercial, df_master.get('FORMA DE CONTRATO', pd.Series(dtype=str))))

            filas_actuales_por_vin = dict(zip(vins_comercial, df_master.to_dict('records')))
            contratos_nuevos = []
            siguiente_id = comercial_services.proximo_id_contrato(self.data_manager.df_master)

            for vin in vins_comercial:
                if vin == 'NAN' or not vin: continue

                if vin not in df_import.index:
                    # Regla de negocio confirmada con Javiera: que un VIN
                    # desaparezca del Excel mensual de CM NO confirma una
                    # baja. La fila simplemente no se toca.
                    continue

                # Contrato actual en baja: es de solo lectura, nunca se
                # actualiza. Si su CM llega Expired y la unidad admite otro
                # contrato (matriz de nuevo contrato) se crea uno nuevo.
                fila_actual = filas_actuales_por_vin.get(vin, {})
                if comercial_services.es_contrato_cerrado(fila_actual.get('ESTADO COMERCIAL', '')):
                    fila_cm = datos_cm_de_fila(df_import.loc[vin])
                    if (str(fila_cm.get('ESTADO DEL CM', '')).strip().upper() == 'EXPIRED'
                            and comercial_services.puede_crear_contrato(
                                fila_actual.get('ESTADO COMERCIAL', ''), fila_actual.get('ESTADO DE ACTIVACIÓN ACTUAL', ''))):
                        registro = ct_service.construir_registro_nuevo_desde_contrato_cm(vin, fila_cm, fila_actual)
                        for campo in ('INDUSTRIA', 'FLOTA VC', 'FLOTA VC 2', 'CDB FLOTA'):
                            if str(fila_actual.get(campo, '')).strip() not in ('', 'nan'):
                                registro[campo] = fila_actual[campo]
                        registro['PERIODO INTERNO'] = f"{_MESES[datetime.now().month - 1]} - {datetime.now().year}".lower()
                        if siguiente_id:
                            registro['ID'] = siguiente_id
                            siguiente_id = str(int(siguiente_id) + 1)
                        contratos_nuevos.append(registro)
                    continue

                cambios_comercial[vin] = {
                    'VIN': vin,
                    'cambios': datos_cm_de_fila(
                        df_import.loc[vin],
                        estado_cm_anterior=estado_cm_actual_por_vin.get(vin),
                        forma_contrato_anterior=forma_contrato_actual_por_vin.get(vin),
                    )
                }

            # El CM actualiza solo el contrato actual del VIN, no los anteriores
            comercial_services.agregar_id_a_cambios(cambios_comercial, df_master)

            # --- VIN del Excel que NO tienen fila en Comercial (RM) ---
            # Antes quedaban ignorados en silencio (nunca se creaba la
            # ficha ni se completaba Razón Social/RUT/etc). Mismo camino
            # que Provisiones (VincularComercialDialog): se ofrece
            # vincularlos con un cliente ya existente usando el nombre que
            # trae el propio Excel de Javiera (Current Invoicing Customer
            # Name), en vez de crearlos a ciegas.
            vins_comercial_set = set(vins_comercial)
            vins_nuevos_info = []
            if col_cliente:
                for vin in df_import.index:
                    if vin == 'NAN' or not vin or vin in vins_comercial_set:
                        continue
                    row = df_import.loc[vin]
                    info = {'VIN': vin, 'CLIENTE': str(row.get(col_cliente, '-')) if pd.notna(row.get(col_cliente)) else '-'}
                    info.update(datos_cm_de_fila(row))
                    vins_nuevos_info.append(info)
            self.import_vins_nuevos = vins_nuevos_info

            QApplication.restoreOverrideCursor()

            if cambios_comercial or contratos_nuevos:
                resumen = ct_service.calcular_resumen_importacion(
                    df_master, cambios_comercial, len(df_import), vins_ausentes_info, vins_nuevos_info,
                    contratos_nuevos,
                )
                dialogo = ResumenImportacionDialog(resumen, os.path.basename(filepath), self)
                if dialogo.exec() == QDialog.DialogCode.Accepted:
                    self.btn_reload.setEnabled(False)
                    self.btn_importar.setEnabled(False)

                    self.lbl_loading_text.setText("Comparando e inyectando miles de contratos... Esto tomará unos segundos.")
                    self.stack.setCurrentIndex(0)
                    QApplication.processEvents()

                    self.import_changes = cambios_comercial
                    self.import_contratos_nuevos = contratos_nuevos

                    self.save_thread = SaveContratosThread(
                        self.writer, cambios_comercial, "Contratos CM (Masivo)", contratos_nuevos)
                    self.save_thread.finished_signal.connect(self._on_import_finished)
                    self.save_thread.start()
            elif vins_nuevos_info:
                # Sin coincidencias para actualizar, pero el Excel trae VIN
                # que no tienen ficha en Comercial: se ofrece igual el
                # camino de vinculación, sin pasar por ResumenImportacionDialog
                # (no hay nada que "inyectar" sobre registros existentes).
                self._mostrar_alerta_vins_nuevos()

        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Error al importar", f"Ocurrió un problema:\n{str(e)}")

    def _on_import_finished(self, success):
        self.btn_reload.setEnabled(True)
        self.btn_importar.setEnabled(True)

        if success:
            df_m = self.data_manager.df_master.copy()
            if not df_m.empty:
                df_m = comercial_services.aplicar_cambios_pendientes(df_m, self.import_changes)
                for registro in getattr(self, 'import_contratos_nuevos', []):
                    df_m = comercial_services.agregar_fila(df_m, registro)
                self.import_contratos_nuevos = []
                self.data_manager.df_master = df_m

                try:
                    cm_bajas_service.procesar_reconciliacion_estado_expired(
                        df_pruebas_actual=comercial_services.contratos_actuales(self.data_manager.df_master),
                        periodo_deteccion=datetime.now().strftime('%Y-%m'),
                        casos_path=config.settings.CASOS_BAJA_CM_PATH,
                    )
                except Exception as e:
                    logger.error(f"No se pudo reconciliar los casos de Revisión CM por estado Expired: {e}")

                # Avisa a Comercial/Vista General que df_master cambió en RAM
                # (mismo patrón que VincularContratoComercialDialog._on_creado
                # y provisiones.py::_on_save_finished): sin esto, el import
                # masivo de CM solo se veía reflejado ahí tras un Recargar
                # manual.
                self.data_manager.data_ready.emit()

            self.load_data()
            self.stack.setCurrentIndex(1)
            self._mostrar_alerta_vins_nuevos()
        else:
            self.stack.setCurrentIndex(1)
            QMessageBox.warning(self, "Error", "No se pudo actualizar el Excel Comercial (puede estar bloqueado).")

    def _mostrar_alerta_vins_nuevos(self):
        vins_nuevos = getattr(self, 'import_vins_nuevos', [])
        if not vins_nuevos:
            return
        alerta = VinsNuevosContratoAlertDialog(vins_nuevos, self)
        if alerta.exec() == QDialog.DialogCode.Accepted:
            dialogo = VincularContratoComercialDialog(vins_nuevos, self.data_manager, self)
            dialogo.vin_resuelto.connect(lambda vin: self.load_data())
            dialogo.exec()
