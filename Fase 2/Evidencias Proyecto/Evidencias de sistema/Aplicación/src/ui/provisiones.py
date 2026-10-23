import shutil
from collections import Counter

import pandas as pd
import qtawesome as qta
import os
import time
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame,
                             QLabel, QPushButton, QMessageBox, QLineEdit, QComboBox,
                             QFormLayout, QGroupBox, QDialog, QGridLayout, QHeaderView, QTextEdit,
                             QStackedWidget, QProgressBar, QApplication, QListView, QListWidget,
                             QTabWidget, QScrollArea, QTableWidget, QTableWidgetItem, QAbstractItemView)
from PyQt6.QtCore import (Qt, QSize, QThread, pyqtSignal, QTimer,
                          QAbstractListModel, QModelIndex, QRectF, QRect)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.ui.custom_table import VolvoTableWidget, PandasTableModel
from src.ui import comercial_estilo as estilo_com
from src.ui.ingresos_base import (PantallaIngresosBase, ModeloTablaIngresos, ComboFiltroBarra, boton_barra, estilo_combo_barra,
                                  aplicar_estilo_tabla_lectura)
from src.ui.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando, crear_tarjeta_carga
from src.core.sharepoint_sync import SharePointSyncWorker
from src.core.dataframe_formatter import DataFrameFormatter
from src.services import provisiones_services
from src.services import comercial_services
from src.services.vin_service import obtener_modelo_desde_vin
# AddRowThread/_DEFAULTS_INICIALES/_tipo_facturacion_default_para_forma_contrato
# (comercial.py/comercial_agregar.py) se importan de forma local donde se usan:
# importarlos aquí cargaba todo Comercial al abrir Provisiones.
import config.settings
from config.settings import PROVISIONES_SHAREPOINT_URL
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *
from src.theme import tema
from src.core.constants import *
from PyQt6.QtGui import QKeySequence

# =========================================================
# MODELO ESPECÍFICO PARA TABLA DE PROVISIONES (Alternativa A)
# =========================================================
class ProvisionesTableModel(PandasTableModel):
    def __init__(self, parent_module, df=pd.DataFrame(), parent=None):
        super().__init__(df, parent)
        self.parent_module = parent_module

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return super().data(index, role)
        if role not in (Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.FontRole):
            return super().data(index, role)

        col_name = self._df.columns[index.column()]

        # Centralizamos la verificación de celda modificada para hacerla inmutable
        is_pending = False
        if hasattr(self.parent_module, 'pending_changes') and self.parent_module.pending_changes:
            df_view = self._df
            if index.row() < len(df_view):
                # .strip().upper() garantiza 100% de acierto al quitar filtros
                vin_val = str(df_view.iat[index.row(), df_view.columns.get_loc('VIN')]).strip().upper()
                fecha_val = str(df_view.iat[index.row(), df_view.columns.get_loc('AÑO - MES')]).strip().upper()
                unique_key = f"{vin_val}_{fecha_val}"
                
                if unique_key in self.parent_module.pending_changes and col_name in self.parent_module.pending_changes[unique_key]['cambios']:
                    is_pending = True

        if role == Qt.ItemDataRole.ForegroundRole:
            if is_pending: return tema.texto(WARNING) # Texto naranja para celda editada
            
            if col_name == 'VAR':
                val_str = str(self._df.iat[index.row(), index.column()])
                if "-" in val_str: return tema.texto(DANGER) 
                elif val_str.strip() in ["$0", "$-0", "0", ""]: return super().data(index, role)
                else: return tema.texto(SUCCESS) 
            return super().data(index, role)
            
        elif role == Qt.ItemDataRole.BackgroundRole:
            if is_pending: return tema.fondo("#FEF3C7") # Fondo Naranja Suave
            return super().data(index, role)
            
        elif role == Qt.ItemDataRole.FontRole:
            if is_pending: 
                font = QFont()
                font.setBold(True)
                return font
            return super().data(index, role)

        return super().data(index, role)

    def flags(self, index):
        flags = super().flags(index)
        col_name = self._df.columns[index.column()]
        if col_name in ['Monto Provisionado', 'Valor Plan', 'VAR']: 
            return flags & ~Qt.ItemFlag.ItemIsEditable
        return flags

# =========================================================
# MOTOR DE GUARDADO ASÍNCRONO DE PROVISIONES
# =========================================================
COL_UF_REGISTRO = "UF"


class SaveProvisionesThread(QThread):
    finished_signal = pyqtSignal(bool, dict, list, dict)

    def _uf_vigente(self):
        try:
            uf, _civ = self.data_manager.get_variables()
            uf = round(float(uf), 2)
            return uf if uf > 0 else None
        except (TypeError, ValueError, AttributeError):
            return None

    def __init__(self, pending_data, writer, data_manager):
        super().__init__()
        self.pending_data = pending_data
        self.writer = writer
        self.data_manager = data_manager
        self.vins_cerrados = []
        self.vins_omitidos = []

    def _id_contrato_en_prov(self, vin, fecha):
        """ID CONTRATO ya guardado en la fila de Provisiones (vacío si no hay)."""
        df = getattr(self.data_manager, 'df_prov', None)
        if not isinstance(df, pd.DataFrame) or df.empty or provisiones_services.COL_ID_CONTRATO_PROV not in df.columns:
            return ''
        mask = (df['VIN'].astype(str).str.strip().str.upper() == vin) & (df['AÑO - MES'].astype(str).str.strip() == fecha)
        if not mask.any():
            return ''
        return comercial_services._normalizar_id_contrato(df.loc[mask, provisiones_services.COL_ID_CONTRATO_PROV].iloc[0])

    def run(self):
        try:
            provisiones_changes = provisiones_services.construir_cambios_provisiones(self.pending_data)

            # Cada provisión se cruza con el contrato actual del VIN; solo uno abierto
            # y de forma Provision recibe cambios (ver resolver_destino_provision).
            df_comercial = self.data_manager.get_contratos_actuales_df()
            destinos = {}
            columna_id = provisiones_services.COL_ID_CONTRATO_PROV
            estampa_id = False
            for key, data in self.pending_data.items():
                target_vin = str(data['VIN']).strip().upper()
                target_fecha = str(data['AÑO - MES']).strip()
                id_prov = self._id_contrato_en_prov(target_vin, target_fecha)
                destino = provisiones_services.resolver_destino_provision(df_comercial, target_vin, id_prov)
                destinos[key] = destino
                if destino['id'] and not id_prov and destino['estado'] != 'huerfano':
                    provisiones_changes[key]['cambios'] = {**provisiones_changes[key]['cambios'], columna_id: destino['id']}
                    estampa_id = True

            # La UF vigente al guardar queda registrada en cada fila editada
            uf_guardado = self._uf_vigente()
            if uf_guardado:
                for cambio in provisiones_changes.values():
                    cambio['cambios'] = {**cambio['cambios'], COL_UF_REGISTRO: uf_guardado}

            columnas_nuevas = ([COL_UF_REGISTRO] if uf_guardado else []) + ([columna_id] if estampa_id else [])
            success_prov = self.writer.update_cells(
                provisiones_changes,
                module_name="Provisiones",
                custom_filepath=config.settings.PROVISION_EXCEL_PATH,
                sheet_name="Prov",
                columnas_nuevas=columnas_nuevas or None
            )

            if not success_prov:
                raise Exception("No se pudo guardar en Provisiones (¿fila no encontrada o archivo bloqueado?).")

            cross_updates = {}
            vins_huerfanos = []
            self.vins_cerrados = []
            self.vins_omitidos = []

            for key, data in self.pending_data.items():
                target_vin = str(data['VIN']).strip().upper()
                target_fecha = str(data['AÑO - MES']).strip()
                cambios = data.get('cambios', {})
                destino = destinos[key]
                if destino['estado'] == 'historica':
                    continue

                cambios_com = {'PERIODO INTERNO': provisiones_services.periodo_interno_desde_provision(target_fecha)}

                if 'Plan' in cambios: cambios_com['TIPO DE SERVICIO'] = cambios['Plan']
                if 'Cantidad de Meses' in cambios:
                    val_meses = str(cambios['Cantidad de Meses']).strip()
                    if val_meses == '-' or val_meses.upper() == 'MENSUAL':
                        cambios_com['DURACIÓN (MESES)'] = '-'
                        cambios_com['TÉRMINO CONTRATO'] = 'MENSUAL'
                    else:
                        cambios_com['DURACIÓN (MESES)'] = val_meses
                        inicio_val = destino['fila'].get('INICIO CONTRATO', '')
                        if pd.notna(inicio_val) and str(inicio_val).strip() != "":
                            try:
                                from dateutil.relativedelta import relativedelta
                                fecha_ini = pd.to_datetime(str(inicio_val).strip(), dayfirst=True).to_pydatetime()
                                fecha_fin = fecha_ini + relativedelta(months=int(float(val_meses)))
                                cambios_com['TÉRMINO CONTRATO'] = fecha_fin.strftime("%d-%m-%Y")
                            except: pass

                if destino['estado'] == 'ok':
                    cross_updates[target_vin] = {'VIN': target_vin, 'ID': destino['id'], 'cambios': cambios_com}
                elif destino['estado'] == 'cerrado':
                    if target_vin not in [v[0] for v in self.vins_cerrados]:
                        self.vins_cerrados.append((target_vin, cambios_com))
                elif destino['estado'] == 'no_provision':
                    if target_vin not in [v[0] for v in self.vins_omitidos]:
                        self.vins_omitidos.append((target_vin, str(destino['fila'].get('FORMA DE CONTRATO', '')).strip()))
                else:
                    if target_vin not in [v[0] for v in vins_huerfanos]:
                        vins_huerfanos.append((target_vin, cambios_com))

            if cross_updates:
                success_comercial = self.writer.update_cells(cross_updates, module_name="Provisiones (Sinc. Auto)")
                if not success_comercial:
                    raise Exception("Provisiones guardado OK. Falló el cruce a Comercial (¿Archivo bloqueado?). Recarga la App.")

            self.finished_signal.emit(True, self.pending_data, vins_huerfanos, cross_updates)

        except PermissionError:
            self.finished_signal.emit(False, {"error": "Permiso denegado. Archivo bloqueado por SharePoint."}, [], {})
        except Exception as e:
            self.finished_signal.emit(False, {"error": str(e)}, [], {})


def _construir_registro_nuevo_desde_provisiones(vin, plan, cantidad_meses, candidato=None, forma_contrato=None):
    """Arma el registro completo de una unidad nueva de Comercial a partir
    de un VIN huérfano de Provisiones, reutilizando tal cual los defaults y
    cálculos que ya usa 'Gestión de Unidades' (comercial_agregar.py) -- no
    se reimplementa ninguna regla de negocio acá, solo se arma el dict de
    entrada para AddRowThread/comercial_services.agregar_fila, igual que ya
    hace ComercialUnidadFormWidget.get_data(). `candidato` es una de las
    combinaciones {RAZÓN SOCIAL, RUT, CDB, EJECUTIVO} que devuelve
    provisiones_services.buscar_candidatos_por_cliente(), o None si el
    usuario no encontró/eligió ninguna coincidencia (punto 11: el registro
    queda parcial, sin inventar esos datos).

    CONTRATO CREADO EN JUSTTIME/INICIO/TERMINO (30-09-2026, análisis
    completo en la conversación -- ver también instalaciones.py histórico
    y JUSTTIME_ESTADO_OPCIONES/CONTRATO_JUSTTIME_MAP en constants.py):
    Provisión NO implica contrato creado en JustTime -- el registro queda
    en 'Pendiente' (hay una gestión por hacer), nunca 'Si' (eso solo lo
    confirma Javiera a mano contra el sistema externo, que esta app no
    puede consultar). INICIO/TERMINO se calculan con
    provisiones_services.calcular_fechas_justtime(), a partir del mes
    ACTUAL (mes en que se vincula, no el mes que Provisiones tenía
    registrado -- confirmado con el usuario: en la práctica el mes que
    queda en el RM es el mes real de la vinculación, ej. Provisiones dice
    Agosto pero si se vincula en Septiembre el INICIO que corresponde es
    Septiembre)."""
    from src.ui.comercial_agregar import _DEFAULTS_INICIALES, _tipo_facturacion_default_para_forma_contrato
    vin = str(vin).strip().upper()
    chasis = vin[-7:] if len(vin) >= 7 else ""
    modelo = obtener_modelo_desde_vin(vin) or _DEFAULTS_INICIALES['MODELO']

    forma_contrato_explicita = bool(forma_contrato)
    forma_contrato = forma_contrato or _DEFAULTS_INICIALES['FORMA DE CONTRATO']
    tipo_facturacion = _tipo_facturacion_default_para_forma_contrato(forma_contrato)
    estado_comercial = _DEFAULTS_INICIALES['ESTADO COMERCIAL']
    estado_activacion = _DEFAULTS_INICIALES['ESTADO DE ACTIVACIÓN ACTUAL']

    etapa_gestion = DataFrameFormatter.calcular_etapa_gestion_esperada({
        COL_ESTADO_COMERCIAL: estado_comercial,
        COL_ESTADO_ACTIVACION: estado_activacion,
        COL_TIPO_FACTURACION: tipo_facturacion,
        COL_ETAPA_GESTION: '',
    })

    candidato = candidato or {}
    inicio_justtime, termino_justtime = provisiones_services.calcular_fechas_justtime(cantidad_meses)
    return {
        'VIN': vin,
        'CHASIS': chasis,
        'MODELO': modelo,
        'RAZÓN SOCIAL': candidato.get('RAZÓN SOCIAL', ''),
        'RUT': candidato.get('RUT', ''),
        'CDB': candidato.get('CDB', ''),
        'EJECUTIVO': candidato.get('EJECUTIVO', ''),
        'INDUSTRIA': _DEFAULTS_INICIALES['INDUSTRIA'],
        'FORMA DE CONTRATO': forma_contrato,
        'TIPO DE FACTURACION': tipo_facturacion,
        'ESTADO COMERCIAL': estado_comercial,
        'ESTADO DE ACTIVACIÓN ACTUAL': estado_activacion,
        'FLOTA VC': _DEFAULTS_INICIALES['FLOTA VC'],
        'FLOTA VC 2': _DEFAULTS_INICIALES['FLOTA VC 2'],
        'TIPO DE CM': _DEFAULTS_INICIALES['TIPO DE CM'],
        'ESTADO DEL CM': _DEFAULTS_INICIALES['ESTADO DEL CM'],
        'TIPO DE SERVICIO': provisiones_services.mapear_tipo_servicio_desde_plan(plan)
        if not (forma_contrato_explicita and provisiones_services.mapear_tipo_servicio_desde_plan(plan) == '-') else 'Basico',
        'DURACIÓN (MESES)': cantidad_meses if cantidad_meses not in (None, '') else '',
        'INICIO CONTRATO': '',
        'TÉRMINO CONTRATO': '',
        'FECHA DE BAJA': '-',
        'CONTRATO CREADO EN JUSTTIME': 'Pendiente',
        'INICIO': inicio_justtime,
        'TERMINO': termino_justtime,
        'ESTADO DE ENTREGA': '-',
        'N CONTRATO 3PC': '-',
        'FECHA INICIO CM': '-',
        'FECHA TERMINO CM': '-',
        'PAGO CM': '-',
        'OBSERVACIONES': comercial_services.OBSERVACION_VIENE_DE_PROVISIONES,
        'ETAPA GESTIÓN': etapa_gestion,
    }


class VincularComercialDialog(QDialog):
    """Único camino para resolver un VIN huérfano de Provisiones (30-09-2026:
    el Rescate vía Reporte de Notas de Venta/Power BI se eliminó por
    completo; hasta el 28-09-2026 esta clase era solo la alternativa que no
    dependía de ese reporte). Busca el 'CLIENTE' de un VIN huérfano de
    Provisiones directamente contra la Razón Social ya existente en
    Comercial, y arma el registro nuevo reutilizando
    _construir_registro_nuevo_desde_provisiones (misma lógica de 'Gestión de
    Unidades', sin duplicarla). Se abre desde VinsHuerfanosAlertDialog (ver
    ProvisionesModule._show_rescue_dialog) al confirmar "Vincular ahora"."""

    vin_resuelto = pyqtSignal(str)

    def __init__(self, vins_pendientes, data_manager, parent=None, nuevo_contrato=False):
        super().__init__(parent)
        # nuevo_contrato: el VIN ya existe pero su contrato está en Baja; se crea
        # otro de forma Provision heredando el cliente del contrato finalizado.
        self.nuevo_contrato = nuevo_contrato
        self.setWindowTitle("Crear contrato de Provisión" if nuevo_contrato else "Vincular con Comercial (RM)")
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
        self.combo_vin.addItems([v for v, _ in self.vins_pendientes])
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
            return None, None
        return self.vins_pendientes[idx]

    def _forma_contrato(self):
        return 'Provision' if self.nuevo_contrato else None

    def _candidato_contrato_anterior(self, vin):
        """Cliente del contrato finalizado del VIN, como único candidato."""
        actuales = self.data_manager.get_contratos_actuales_df()
        destino = provisiones_services.resolver_destino_provision(actuales, vin)
        fila = destino['fila']
        if not fila:
            return None, ''
        candidato = {c: str(fila.get(c, '') if pd.notna(fila.get(c, '')) else '').strip()
                     for c in ('RAZÓN SOCIAL', 'RUT', 'CDB', 'EJECUTIVO')}
        return candidato, destino['id']

    def _vin_ya_existe_en_rm(self, vin):
        df_master = self.data_manager.df_master
        if not isinstance(df_master, pd.DataFrame) or df_master.empty or 'VIN' not in df_master.columns:
            return False
        vins_existentes = set(df_master['VIN'].dropna().astype(str).str.strip().str.upper())
        return vin in vins_existentes

    def _cargar_vin_actual(self):
        self.tabla_candidatos.setRowCount(0)
        self.candidatos_actuales = []
        self.lbl_preview.clear()

        vin, _ = self._vin_actual()
        if not vin:
            self.lbl_cliente.setText("")
            self.btn_confirmar.setEnabled(False)
            return

        if self.nuevo_contrato:
            candidato, id_anterior = self._candidato_contrato_anterior(vin)
            self.lbl_cliente.setText(
                f"El VIN {vin} tiene su contrato N° {id_anterior or '-'} finalizado. Se creará un contrato nuevo de "
                "forma Provision con el mismo cliente.")
            self.candidatos_actuales = [candidato] if candidato else []
            self.tabla_candidatos.setRowCount(len(self.candidatos_actuales))
            for row, cand in enumerate(self.candidatos_actuales):
                for col, campo in enumerate(['RAZÓN SOCIAL', 'RUT', 'CDB', 'EJECUTIVO']):
                    self.tabla_candidatos.setItem(row, col, QTableWidgetItem(str(cand.get(campo, ''))))
            if self.candidatos_actuales:
                self.tabla_candidatos.selectRow(0)
            self.btn_confirmar.setEnabled(True)
            self._actualizar_preview()
            return

        if self._vin_ya_existe_en_rm(vin):
            # Caso B (VIN ya existe): solo se informa, no se autocompleta ni
            # se sobrescribe nada -- decisión confirmada con el usuario.
            self.lbl_cliente.setText(
                f"El VIN {vin} YA EXISTE en la Base Comercial. No se creará un duplicado ni se "
                "modificarán sus datos actuales; revísalo manualmente en Comercial si corresponde."
            )
            self.btn_confirmar.setEnabled(False)
            return

        cliente = ""
        df_prov = self.data_manager.df_prov
        if isinstance(df_prov, pd.DataFrame) and not df_prov.empty and 'CLIENTE' in df_prov.columns and 'VIN' in df_prov.columns:
            fila = df_prov[df_prov['VIN'].astype(str).str.strip().str.upper() == vin]
            if not fila.empty:
                cliente = str(fila.iloc[0]['CLIENTE'])

        self.lbl_cliente.setText(f'Cliente en Provisiones: "{cliente}"')
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

    def _datos_provision_actuales(self):
        _, cambios_com = self._vin_actual()
        cambios_com = cambios_com or {}
        return cambios_com.get('TIPO DE SERVICIO', ''), cambios_com.get('DURACIÓN (MESES)', '')

    def _actualizar_preview(self):
        vin, _ = self._vin_actual()
        if not vin:
            return
        plan, meses = self._datos_provision_actuales()
        registro = _construir_registro_nuevo_desde_provisiones(
            vin, plan, meses, candidato=self._candidato_seleccionado(), forma_contrato=self._forma_contrato())
        self.lbl_preview.setText(
            f"VIN: {registro['VIN']}  ·  CHASIS: {registro['CHASIS']}  ·  MODELO: {registro['MODELO']}\n"
            f"Razón Social: {registro['RAZÓN SOCIAL'] or '(sin coincidencia)'}  ·  "
            f"RUT: {registro['RUT'] or '-'}  ·  CDB: {registro['CDB'] or '-'}  ·  "
            f"Ejecutivo: {registro['EJECUTIVO'] or '-'}\n"
            f"Estado Comercial: {registro['ESTADO COMERCIAL']}  ·  "
            f"Forma de Contrato: {registro['FORMA DE CONTRATO']}  ·  "
            f"Tipo de Facturación: {registro['TIPO DE FACTURACION']}  ·  "
            f"Etapa Gestión: {registro['ETAPA GESTIÓN']}\n"
            f"Tipo de Servicio: {registro['TIPO DE SERVICIO']}  ·  "
            f"Duración (meses): {registro['DURACIÓN (MESES)']}\n"
            f"JustTime: {registro['CONTRATO CREADO EN JUSTTIME']}  ·  "
            f"Inicio: {registro['INICIO']}  ·  Término: {registro['TERMINO']}\n"
            f"Observaciones: {registro['OBSERVACIONES']}"
        )

    def _confirmar(self):
        vin, _ = self._vin_actual()
        if not vin:
            return
        candidato = self._candidato_seleccionado()
        if candidato is None:
            respuesta = QMessageBox.question(
                self, "Sin coincidencia comercial",
                f"No seleccionaste ninguna coincidencia para el VIN {vin}. Se creará igual, pero sin "
                "Razón Social/RUT/CDB/Ejecutivo (quedará marcado para revisión manual).\n\n¿Continuar?",
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return

        plan, meses = self._datos_provision_actuales()
        registro = _construir_registro_nuevo_desde_provisiones(
            vin, plan, meses, candidato=candidato, forma_contrato=self._forma_contrato())

        from src.ui.comercial import AddRowThread
        self.btn_confirmar.setEnabled(False)
        self._add_thread = AddRowThread(ExcelWriter(), registro, module_name="Provisiones (Vinculación RM)")
        self._add_thread.finished_signal.connect(lambda ok, data: self._on_creado(ok, data, vin))
        self._add_thread.start()

    def _on_creado(self, success, new_data, vin):
        self.btn_confirmar.setEnabled(True)
        if not success:
            QMessageBox.warning(self, "Error", f"No se pudo crear el registro para VIN {vin} en la Base Comercial.")
            return

        dm = self.data_manager
        if self.nuevo_contrato:
            # El ID del contrato nuevo lo asigna el archivo: se recarga para traerlo.
            dm.load_data_async()
        elif not dm.df_master.empty:
            dm.df_master = comercial_services.agregar_fila(dm.df_master, new_data)
            dm.data_ready.emit()

        QMessageBox.information(self, "Vinculado", f"Se creó el registro para VIN {vin} en la Base Comercial.")
        self.vins_pendientes = [(v, c) for v, c in self.vins_pendientes if v != vin]
        self.vin_resuelto.emit(vin)

        self.combo_vin.blockSignals(True)
        self.combo_vin.clear()
        self.combo_vin.addItems([v for v, _ in self.vins_pendientes])
        self.combo_vin.blockSignals(False)

        if not self.vins_pendientes:
            QMessageBox.information(self, "Listo", "No quedan VIN pendientes por vincular.")
            self.accept()
            return
        self._cargar_vin_actual()


class VinsHuerfanosAlertDialog(QDialog):
    """Alerta simple (30-09-2026, reemplaza al ex dialogo de "Rescate de
    Contratos Huerfanos", que abria directo un flujo tipo terminal): informa
    en lenguaje simple que hay VIN nuevos en Provisiones sin fila en
    Comercial, y deja que el usuario elija abrir VincularComercialDialog
    ahora o posponerlo -- unico camino que queda para resolverlos. El
    Rescate via Reporte de Notas de Venta/Power BI (RescateWorker/
    RescateDialog/EsperaReporteNVWorker) se elimino por completo, a pedido
    explicito: dependia de un archivo externo y un flujo largo que se
    prefiere evitar."""

    def __init__(self, vins_huerfanos, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camiones nuevos en Provisiones")
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
        titulo = QLabel(f"{len(vins_huerfanos)} camion(es) sin ficha en Comercial")
        titulo.setWordWrap(True)
        ThemeManager.style_subtitle(titulo)
        encabezado.addWidget(titulo, stretch=1)
        layout.addLayout(encabezado)

        explicacion = QLabel(
            "Provisiones tiene datos para estos VIN, pero todavia no existen en la Base Comercial "
            "(PruebasFM). Podes vincularlos ahora con un cliente que ya exista en Comercial (Razon "
            "Social, RUT, CDB) y gestionarlos despues desde ahi, o hacerlo mas tarde."
        )
        explicacion.setWordWrap(True)
        explicacion.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(explicacion)

        lista = QListWidget()
        lista.addItems([v for v, _ in vins_huerfanos])
        lista.setMaximumHeight(130)
        layout.addWidget(lista)

        botones = QHBoxLayout()
        botones.addStretch()
        self.btn_despues = QPushButton(" Mas tarde")
        ThemeManager.apply_secondary_button(self.btn_despues)
        self.btn_despues.clicked.connect(self.reject)
        botones.addWidget(self.btn_despues)

        self.btn_vincular = QPushButton(" Vincular ahora")
        self.btn_vincular.setIcon(ThemeManager.icon('fa5s.link', color='white'))
        ThemeManager.apply_primary_button(self.btn_vincular)
        self.btn_vincular.clicked.connect(self.accept)
        botones.addWidget(self.btn_vincular)
        layout.addLayout(botones)


# (título, ayuda) de cada paso del proceso; coinciden con las fases de SharePointSyncWorker
_PASOS_SYNC = [
    ("Descargar archivo", "Abrimos SharePoint en tu navegador y esperamos la descarga."),
    ("Leer y adaptar", "Tomamos la hoja del año en curso y la dejamos con el formato de Provisiones."),
    ("Comparar", "Buscamos los contratos (VIN + mes) que aún no están en tu Excel."),
    ("Revisar", "Confirmas los registros nuevos antes de agregarlos."),
    ("Guardar", "Respaldo, escritura de las filas nuevas y fórmulas."),
]
_MENSAJE_PASO_SYNC = [
    ("Descargando desde SharePoint",
     "Se abrió SharePoint en tu navegador. Si te pide iniciar sesión en Microsoft 365, hazlo: "
     "la descarga empieza sola y la app la detecta en tu carpeta Descargas."),
    ("Leyendo el archivo", "Tomamos la hoja del año en curso y la dejamos con las columnas y el formato de Provisiones."),
    ("Buscando contratos nuevos", "Comparamos cada VIN y mes con tu Excel para no duplicar nada."),
    ("Revisa los registros nuevos", ""),
    ("Guardando en tu Excel",
     "Primero hacemos una copia de seguridad y luego agregamos las filas con sus fórmulas. No cierres la ventana."),
]
_ESPERA_DESCARGA_S = 60


class AnilloTiempo(QWidget):
    """Anillo con un número al centro: cuenta regresiva durante la espera de la
    descarga y arco giratorio con el tiempo transcurrido en el resto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 132)
        self.fraccion = None
        self.texto = ""
        self.subtexto = ""
        self.color = QColor(VOLVO_BLUE)
        self.quieto = True

    def definir(self, texto, subtexto, fraccion=None, color=None, quieto=False):
        self.texto, self.subtexto, self.fraccion, self.quieto = texto, subtexto, fraccion, quieto
        self.color = QColor(color or VOLVO_BLUE)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        marco = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        p.setPen(QPen(QColor("#E3E8F0"), 9))
        p.drawArc(marco, 0, 360 * 16)
        p.setPen(QPen(self.color, 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if self.fraccion is not None:
            p.drawArc(marco, 90 * 16, -int(360 * 16 * max(0.0, min(1.0, self.fraccion))))
        elif not self.quieto:
            inicio = 90 - int((time.monotonic() * 220) % 360)
            p.drawArc(marco, inicio * 16, -110 * 16)
        p.setPen(QColor("#0F1B33"))
        fuente = p.font()
        fuente.setPixelSize(26)
        fuente.setBold(True)
        p.setFont(fuente)
        p.drawText(QRectF(self.rect()).adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter, self.texto)
        p.setPen(QColor("#6B7A90"))
        fuente.setPixelSize(10)
        fuente.setBold(False)
        p.setFont(fuente)
        p.drawText(QRectF(self.rect()).adjusted(0, 30, 0, 30), Qt.AlignmentFlag.AlignCenter, self.subtexto)


class PasoSync(QFrame):
    """Una fila del paso a paso: círculo de estado, título y descripción."""

    ESTILOS = {
        "pendiente": ("#EEF1F6", "#6B7A90", "#6B7A90"),
        "activo": (VOLVO_BLUE, "white", "#0F1B33"),
        "hecho": ("#16A34A", "white", "#0F1B33"),
        "error": ("#DC2626", "white", "#0F1B33"),
    }

    def __init__(self, numero, titulo, descripcion, parent=None):
        super().__init__(parent)
        self.numero = numero
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)
        self.badge = QLabel(str(numero))
        self.badge.setFixedSize(28, 28)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        textos = QVBoxLayout()
        textos.setSpacing(1)
        self.lbl_titulo = QLabel(titulo)
        self.lbl_desc = QLabel(descripcion)
        self.lbl_desc.setWordWrap(True)
        textos.addWidget(self.lbl_titulo)
        textos.addWidget(self.lbl_desc)
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(textos, 1)
        self.estado = None
        self.definir("pendiente")

    def definir(self, estado):
        if estado == self.estado:
            return
        self.estado = estado
        fondo, texto, titulo = self.ESTILOS[estado]
        simbolo = {"hecho": "✓", "error": "!"}.get(estado, str(self.numero))
        self.badge.setText(simbolo)
        self.badge.setStyleSheet(
            f"background: {fondo}; color: {texto}; border-radius: 14px; font-weight: 800; font-size: 13px;")
        self.lbl_titulo.setStyleSheet(
            f"color: {titulo}; font-size: 13px; font-weight: 700; background: transparent;")
        self.lbl_desc.setStyleSheet("color: #6B7A90; font-size: 11px; background: transparent;")
        activo = estado == "activo"
        self.setStyleSheet(
            f"PasoSync {{ background: {'#EEF3FA' if activo else 'transparent'}; border-radius: 12px; }}")


class SyncTerminalDialog(QDialog):
    """Sincronización con SharePoint explicada paso a paso: lista de pasos,
    anillo de tiempo, previsualización con la tabla de Comercial y resultado.
    El proceso real sigue en SharePointSyncWorker; aquí solo se traducen sus
    mensajes de registro a pasos."""

    PAG_PROGRESO, PAG_REVISION, PAG_RESULTADO = 0, 1, 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sincronización de SharePoint (Auto-ETL)")
        self.resize(1100, 680)
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO + "QDialog { background-color: #F4F6FA; }")
        self.sharepoint_url = PROVISIONES_SHAREPOINT_URL
        self.worker = None
        self._paso = -1
        self._t0 = None
        self._inicio_paso = None
        self._finalizado = False
        self._setup_ui()
        self._reloj = QTimer(self)
        self._reloj.setInterval(40)
        self._reloj.timeout.connect(self._tick)

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 18, 20, 16)
        raiz.setSpacing(14)

        cabecera = QFrame()
        cabecera.setObjectName("cabeceraSync")
        cabecera.setStyleSheet("QFrame#cabeceraSync { background-color: #1B2B4E; border-radius: 14px; }")
        fila = QHBoxLayout(cabecera)
        fila.setContentsMargins(16, 12, 16, 12)
        fila.setSpacing(12)
        titulos = QVBoxLayout()
        titulos.setSpacing(0)
        t = QLabel("Sincronizar con SharePoint")
        t.setStyleSheet("color: white; font-size: 16px; font-weight: 800; background: transparent;")
        s = QLabel("Trae los contratos nuevos del Excel de Provisiones y los agrega a tu archivo.")
        s.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
        titulos.addWidget(t)
        titulos.addWidget(s)
        fila.addLayout(titulos, 1)
        raiz.addWidget(cabecera)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(14)

        lateral = QFrame()
        lateral.setObjectName("pasosSync")
        lateral.setFixedWidth(300)
        lateral.setStyleSheet(estilo_com.qss_tarjeta("pasosSync"))
        lay_pasos = QVBoxLayout(lateral)
        lay_pasos.setContentsMargins(10, 12, 10, 12)
        lay_pasos.setSpacing(2)
        titulo_pasos = QLabel("PASO A PASO")
        titulo_pasos.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        lay_pasos.addWidget(titulo_pasos)
        self.pasos = []
        for i, (titulo, desc) in enumerate(_PASOS_SYNC, start=1):
            paso = PasoSync(i, titulo, desc)
            self.pasos.append(paso)
            lay_pasos.addWidget(paso)
        lay_pasos.addStretch()
        cuerpo.addWidget(lateral)

        self.paginas = QStackedWidget()
        self.paginas.addWidget(self._build_pagina_progreso())
        self.paginas.addWidget(self._build_pagina_revision())
        self.paginas.addWidget(self._build_pagina_resultado())
        cuerpo.addWidget(self.paginas, 1)
        raiz.addLayout(cuerpo, 1)

        botones = QHBoxLayout()
        self.btn_cancel = QPushButton(" Cancelar")
        ThemeManager.apply_secondary_button(self.btn_cancel)
        self.btn_cancel.clicked.connect(self.close)

        self.btn_start = QPushButton(" Iniciar descarga")
        self.btn_start.setIcon(ThemeManager.icon('fa5s.cloud-download-alt', color='white'))
        ThemeManager.apply_primary_button(self.btn_start)
        self.btn_start.clicked.connect(self.start_sync)

        self.btn_inject = QPushButton(" Agregar registros")
        self.btn_inject.setIcon(ThemeManager.icon('fa5s.magic', color='white'))
        ThemeManager.apply_success_button(self.btn_inject)
        self.btn_inject.clicked.connect(self.inject_data)
        self.btn_inject.hide()

        self.btn_cerrar = QPushButton(" Cerrar")
        ThemeManager.apply_primary_button(self.btn_cerrar)
        self.btn_cerrar.clicked.connect(self.accept)
        self.btn_cerrar.hide()

        botones.addStretch()
        botones.addWidget(self.btn_cancel)
        botones.addWidget(self.btn_start)
        botones.addWidget(self.btn_inject)
        botones.addWidget(self.btn_cerrar)
        raiz.addLayout(botones)

    @staticmethod
    def _tarjeta(nombre):
        marco = QFrame()
        marco.setObjectName(nombre)
        marco.setStyleSheet(estilo_com.qss_tarjeta(nombre))
        return marco

    def _build_pagina_progreso(self):
        marco = self._tarjeta("progresoSync")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(24, 22, 24, 16)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.anillo = AnilloTiempo()
        self.anillo.definir("Listo", "para empezar", quieto=True)
        lay.addWidget(self.anillo, 0, Qt.AlignmentFlag.AlignHCenter)

        self.lbl_titulo_paso = QLabel("Todo listo para sincronizar")
        self.lbl_titulo_paso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_titulo_paso.setStyleSheet("color: #0F1B33; font-size: 17px; font-weight: 800; background: transparent;")
        self.lbl_ayuda_paso = QLabel(
            "Al pulsar «Iniciar descarga» se abre SharePoint en tu navegador. Si te pide iniciar sesión, "
            "hazlo; la descarga comienza sola y puedes seguir el avance aquí.")
        self.lbl_ayuda_paso.setWordWrap(True)
        self.lbl_ayuda_paso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_ayuda_paso.setStyleSheet("color: #52607A; font-size: 12px; background: transparent;")
        lay.addWidget(self.lbl_titulo_paso)
        lay.addWidget(self.lbl_ayuda_paso)

        lay.addStretch()
        self.btn_detalle = QPushButton("Ver detalle técnico")
        self.btn_detalle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detalle.setCheckable(True)
        self.btn_detalle.setStyleSheet(
            "QPushButton { color: #6B7A90; font-size: 11px; font-weight: 700; border: none; background: transparent; }"
            "QPushButton:hover { color: #1B2B4E; }")
        self.btn_detalle.toggled.connect(self._alternar_detalle)
        lay.addWidget(self.btn_detalle, 0, Qt.AlignmentFlag.AlignHCenter)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setFixedHeight(120)
        self.terminal.setStyleSheet(
            "background-color: #F7F8FC; color: #334155; border: 1px solid #E3E8F0; border-radius: 10px;"
            " font-family: Consolas; font-size: 11px; padding: 8px;")
        self.terminal.hide()
        lay.addWidget(self.terminal)
        return marco

    def _build_pagina_revision(self):
        marco = self._tarjeta("revisionSync")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        fila = QHBoxLayout()
        self.lbl_titulo_revision = QLabel("Registros nuevos")
        self.lbl_titulo_revision.setStyleSheet(
            "color: #0F1B33; font-size: 16px; font-weight: 800; background: transparent;")
        self.chip_cantidad = QLabel("0")
        self.chip_cantidad.setStyleSheet(
            f"background: #E1EAF4; color: {VOLVO_BLUE}; border-radius: 11px; padding: 3px 12px;"
            " font-size: 11px; font-weight: 800;")
        fila.addWidget(self.lbl_titulo_revision)
        fila.addWidget(self.chip_cantidad)
        fila.addStretch()
        lay.addLayout(fila)

        aviso = QLabel(
            "Se agregan al final de la hoja «Prov» de provisionFelipe.xlsx con Plan vacío y 0 meses; "
            "después defines el plan y los meses en cada registro. Antes se guarda una copia de seguridad.")
        aviso.setWordWrap(True)
        aviso.setStyleSheet("color: #52607A; font-size: 11px; background: transparent;")
        lay.addWidget(aviso)

        self.preview_table = VolvoTableWidget()
        aplicar_estilo_tabla_lectura(self.preview_table, 42)
        self.preview_model = ModeloTablaIngresos(
            alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.preview_table.set_model_and_delegate(self.preview_model)
        self._delegado_preview = estilo_com.DelegadoCeldasComercial([self.preview_table, self.preview_table.frozen_view])
        self.preview_table.setItemDelegate(self._delegado_preview)
        self.preview_table.frozen_view.setItemDelegate(self._delegado_preview)
        lay.addWidget(self.preview_table, 1)
        return marco

    def _build_pagina_resultado(self):
        marco = self._tarjeta("resultadoSync")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(10)
        lay.addStretch()
        self.icono_resultado = QLabel()
        self.icono_resultado.setFixedSize(76, 76)
        self.icono_resultado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icono_resultado, 0, Qt.AlignmentFlag.AlignHCenter)
        self.lbl_titulo_resultado = QLabel("")
        self.lbl_titulo_resultado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_titulo_resultado.setStyleSheet("color: #0F1B33; font-size: 20px; font-weight: 800; background: transparent;")
        self.lbl_detalle_resultado = QLabel("")
        self.lbl_detalle_resultado.setWordWrap(True)
        self.lbl_detalle_resultado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_detalle_resultado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_detalle_resultado.setStyleSheet("color: #52607A; font-size: 12px; background: transparent;")
        lay.addWidget(self.lbl_titulo_resultado)
        lay.addWidget(self.lbl_detalle_resultado)
        lay.addStretch()
        return marco

    def _alternar_detalle(self, visible):
        self.terminal.setVisible(visible)
        self.btn_detalle.setText("Ocultar detalle técnico" if visible else "Ver detalle técnico")

    # ------------------------------------------------------------ progreso
    def _set_paso(self, indice, estado="activo"):
        self._paso = indice
        self._inicio_paso = time.monotonic()
        for i, paso in enumerate(self.pasos):
            paso.definir("hecho" if i < indice else ("pendiente" if i > indice else estado))
        titulo, ayuda = _MENSAJE_PASO_SYNC[indice]
        self.lbl_titulo_paso.setText(titulo)
        self.lbl_ayuda_paso.setText(ayuda)

    def _tick(self):
        if self._t0 is None:
            return
        transcurrido = time.monotonic() - self._t0
        if self._paso == 0 and self._inicio_paso is not None:
            restante = max(0, _ESPERA_DESCARGA_S - (time.monotonic() - self._inicio_paso))
            self.anillo.definir(f"{int(restante + 0.99)}s", "espera máxima", fraccion=restante / _ESPERA_DESCARGA_S)
        else:
            minutos, segundos = divmod(int(transcurrido), 60)
            self.anillo.definir(f"{minutos}:{segundos:02d}", "transcurrido")

    def _detener_reloj(self):
        self._reloj.stop()
        if self._t0 is not None:
            minutos, segundos = divmod(int(time.monotonic() - self._t0), 60)
            return f"{minutos}:{segundos:02d}"
        return "0:00"

    def write_log(self, text):
        self.terminal.append(f"> {text}")
        scrollbar = self.terminal.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        if "Archivo atrapado" in text or "[PROCESANDO]" in text:
            self._set_paso(1)
        elif "[COMPARANDO]" in text:
            self._set_paso(2)
        elif "Creando copia" in text:
            self._set_paso(4)

    # --------------------------------------------------------------- flujo
    def start_sync(self):
        self.btn_start.setEnabled(False)
        self.terminal.clear()
        self.paginas.setCurrentIndex(self.PAG_PROGRESO)
        self._t0 = time.monotonic()
        self._set_paso(0)
        self._reloj.start()
        self.worker = SharePointSyncWorker(self.sharepoint_url)
        self.worker.log_signal.connect(self.write_log)
        self.worker.preview_signal.connect(self.show_preview)
        self.worker.success_signal.connect(self.handle_success)
        self.worker.error_signal.connect(self.handle_error)
        self.worker.start()

    def show_preview(self, df_nuevos):
        self._reloj.stop()
        self._set_paso(3)
        df_display = df_nuevos.copy()
        if 'DYNAFLEET' in df_display.columns: df_display = df_display.drop(columns=['DYNAFLEET'])
        self.preview_model.set_data(df_display)
        anchos = {'AÑO - MES': 160, 'VIN': 170, 'CLIENTE': 220, 'EJECUTIVO': 150}
        for i, col in enumerate(df_display.columns):
            self.preview_table.setColumnWidth(i, anchos.get(col, 200))
        self.chip_cantidad.setText(f"{len(df_nuevos)} {'registro' if len(df_nuevos) == 1 else 'registros'}")
        self.paginas.setCurrentIndex(self.PAG_REVISION)
        self.btn_start.hide()
        self.btn_inject.setText(f" Agregar {len(df_nuevos)} {'registro' if len(df_nuevos) == 1 else 'registros'}")
        self.btn_inject.show()

    def inject_data(self):
        self.btn_inject.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.paginas.setCurrentIndex(self.PAG_PROGRESO)
        self._t0 = time.monotonic()
        self._set_paso(4)
        self._reloj.start()
        self.worker.is_injecting = True
        self.worker.start()

    def _mostrar_resultado(self, icono, color, fondo, titulo, detalle):
        self.icono_resultado.setPixmap(ThemeManager.icon_pixmap(icono, color=color, size=34))
        self.icono_resultado.setStyleSheet(f"background: {fondo}; border-radius: 38px;")
        self.lbl_titulo_resultado.setText(titulo)
        self.lbl_detalle_resultado.setText(detalle)
        self.paginas.setCurrentIndex(self.PAG_RESULTADO)

    def handle_success(self, status):
        tiempo = self._detener_reloj()
        self._finalizado = True
        self.btn_start.hide()
        self.btn_inject.hide()
        self.btn_cancel.hide()
        self.btn_cerrar.show()
        if status == "ZERO":
            for paso in self.pasos[:3]:
                paso.definir("hecho")
            self._mostrar_resultado('fa5s.check', "#065F46", "#D1FAE5", "Todo al día",
                                    f"No hay contratos nuevos para agregar. Tiempo total: {tiempo}.")
            return
        for paso in self.pasos:
            paso.definir("hecho")
        cantidad = len(self.worker.new_data_df) if self.worker.new_data_df is not None else 0
        self._mostrar_resultado('fa5s.check', "#065F46", "#D1FAE5", "Proceso completado",
                                f"Se agregaron {cantidad} registros a provisionFelipe.xlsx. Tiempo total: {tiempo}.")

    def handle_error(self, error_msg):
        self._detener_reloj()
        if 0 <= self._paso < len(self.pasos):
            self.pasos[self._paso].definir("error")
        self._mostrar_resultado('fa5s.exclamation', "#991B1B", "#FEE2E2", "No se pudo completar", error_msg)
        self.btn_start.setText(" Reintentar")
        self.btn_start.setEnabled(True)
        self.btn_start.show()
        self.btn_inject.hide()
        self.btn_cancel.setEnabled(True)

    def reject(self):
        if self._finalizado:
            self.accept()
        else:
            self._reloj.stop()
            super().reject()


class FetchUfWorker(QThread):
    uf_fetched = pyqtSignal(float)
    error_signal = pyqtSignal(str)

    def run(self):
        try:
            import requests, re, urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            url = os.environ.get("GESTOR_SSCC_UF_URL", "").strip()
            if not url:
                self.error_signal.emit("Sin URL de UF: define la variable de entorno GESTOR_SSCC_UF_URL o ingresa el valor a mano.")
                return
            response = requests.get(url, timeout=10, verify=False) 
            if response.status_code == 200:
                text_response = response.text.replace(',', '.') 
                matches = re.findall(r'\b\d{5}(?:\.\d{1,2})?\b', text_response)
                if matches: 
                    self.uf_fetched.emit(float(matches[0]))
                    return
            self.error_signal.emit("No se pudo extraer la UF.")
        except Exception as e:
            self.error_signal.emit(str(e))

class CostosDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajustes de Costos y UF")
        self.resize(580, 450)
        self.setStyleSheet(f"QDialog {{ background-color: {SURFACE}; }}")
        self.data_manager = DataManager()
        self.row_widgets = []
        self.uf_worker = None
        self._setup_ui()
        self.load_current_data()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        group_vars = QGroupBox("Variables Globales")
        vars_layout = QHBoxLayout(group_vars)

        self.input_uf = QLineEdit()
        ThemeManager.apply_search_bar(self.input_uf) 
        
        self.btn_fetch_uf = QPushButton(" Obtener UF Web")
        self.btn_fetch_uf.setIcon(ThemeManager.icon('fa5s.globe', color='white'))
        ThemeManager.apply_primary_button(self.btn_fetch_uf)
        self.btn_fetch_uf.clicked.connect(self.fetch_uf_web)
        
        uf_layout = QHBoxLayout()
        uf_layout.addWidget(self.input_uf)
        uf_layout.addWidget(self.btn_fetch_uf)
        
        self.input_civ = QLineEdit()
        ThemeManager.apply_search_bar(self.input_civ)

        form_uf = QFormLayout(); form_uf.addRow("Valor UF ($):", uf_layout)
        form_civ = QFormLayout(); form_civ.addRow("Valor CIV (UF):", self.input_civ)
        
        vars_layout.addLayout(form_uf)
        vars_layout.addLayout(form_civ)
        main_layout.addWidget(group_vars)

        group_planes = QGroupBox("Catálogo de Planes")
        self.grid_planes = QGridLayout(group_planes)
        main_layout.addWidget(group_planes)

        btn_layout = QHBoxLayout()
        btn_cancel = QPushButton("Cancelar")
        ThemeManager.apply_secondary_button(btn_cancel)
        btn_cancel.clicked.connect(self.reject)
        
        btn_save = QPushButton(" Guardar")
        btn_save.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        ThemeManager.apply_success_button(btn_save)
        btn_save.clicked.connect(self.save_and_close)
        
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        main_layout.addLayout(btn_layout)

    def fetch_uf_web(self):
        self.btn_fetch_uf.setEnabled(False)
        self.btn_fetch_uf.setText(" Buscando...")
        self.uf_worker = FetchUfWorker()
        self.uf_worker.uf_fetched.connect(self._on_uf_fetched)
        self.uf_worker.error_signal.connect(self._on_uf_error)
        self.uf_worker.start()

    def _on_uf_fetched(self, valor_uf):
        self.input_uf.setText(f"{valor_uf:g}")
        self.btn_fetch_uf.setText(" Obtener UF Web")
        self.btn_fetch_uf.setEnabled(True)

    def _on_uf_error(self, error):
        self.btn_fetch_uf.setText(" Obtener UF Web")
        self.btn_fetch_uf.setEnabled(True)
        QMessageBox.warning(self, "Error de Conexión", f"No se pudo obtener la UF de internet:\n{error}\nPuedes ingresarla manualmente.")

    def load_current_data(self):
        uf, civ = self.data_manager.get_variables()
        self.input_uf.setText(f"{uf:g}")
        self.input_civ.setText(f"{civ:g}")
        planes_data = self.data_manager.get_costos()
        
        for i, plan_data in enumerate(planes_data):
            row_idx = i + 1
            inp_nombre = QLineEdit(plan_data['nombre']); inp_nombre.setReadOnly(True)
            ThemeManager.apply_search_bar(inp_nombre)
            
            mult_val = plan_data.get('uf_mult', 0)
            inp_mult = QLineEdit(f"{mult_val:g}")
            ThemeManager.apply_search_bar(inp_mult)
            is_locked = "+ CIV" in str(plan_data['nombre']).upper()
            if is_locked: inp_mult.setReadOnly(True)
            
            inp_clp = QLineEdit(f"${float(plan_data.get('clp', 0)):,.0f}".replace(",", "."))
            inp_clp.setReadOnly(True)
            ThemeManager.apply_search_bar(inp_clp)
            
            self.grid_planes.addWidget(inp_nombre, row_idx, 0)
            self.grid_planes.addWidget(inp_mult, row_idx, 1)
            self.grid_planes.addWidget(inp_clp, row_idx, 2)
            self.row_widgets.append({'inp_nombre': inp_nombre, 'inp_mult': inp_mult, 'is_locked': is_locked})

    def save_and_close(self):
        try:
            import openpyxl
            writer_backup = ExcelWriter()
            writer_backup._crear_backup(config.settings.PROVISION_EXCEL_PATH)
            if not writer_backup.last_backup_ok:
                QMessageBox.critical(self, "Error", "No se pudo crear la copia de seguridad de provisionFelipe.xlsx. La operación fue cancelada y no se realizó ningún cambio.")
                return
            wb = openpyxl.load_workbook(config.settings.PROVISION_EXCEL_PATH)
            if "Variables" in wb.sheetnames:
                ws_vars = wb["Variables"]
                for row in range(1, 10):
                    var_cell = str(ws_vars.cell(row=row, column=1).value).strip().upper()
                    if var_cell == "CIV":
                        ws_vars.cell(row=row, column=2).value = provisiones_services.parsear_numero_uf(self.input_civ.text())
                    elif var_cell == "UF":
                        ws_vars.cell(row=row, column=2).value = provisiones_services.parsear_numero_uf(self.input_uf.text())

            if "Planes" in wb.sheetnames:
                ws_planes = wb["Planes"]
                for rw in self.row_widgets:
                    if not rw['is_locked']:
                        target_name = rw['inp_nombre'].text().strip()
                        for row in range(1, 20):
                            if str(ws_planes.cell(row=row, column=1).value).strip() == target_name:
                                ws_planes.cell(row=row, column=2).value = provisiones_services.parsear_numero_uf(rw['inp_mult'].text())
                                break
            
            dm = self.data_manager
            dm.is_app_saving = True
            import time
            dm.save_timestamp = time.time()
            
            wb.save(config.settings.PROVISION_EXCEL_PATH)
            wb.close()

            dm.load_provisiones_async()
            if not writer_backup.last_backup_ok:
                QMessageBox.warning(self, "Aviso", "Los valores se guardaron, pero no se pudo crear la copia de seguridad previa. Revisa 'Estado del Sistema' en Configuración.")
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Formato Inválido", "Por favor ingresa solo números en las casillas.")
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))

# =========================================================
# PESTAÑA NUEVA "PROVISIÓN" (tarjetas) -- mismo lenguaje visual que
# EmpresaCard/ContratoCard/ContratoFormDialog de src/ui/contratos.py, con el
# color de acento de Provisiones (MODULE_COLORS). Por debajo sigue usando el
# motor de _ProvisionesModuleLegacy (on_item_edited/confirm_save/pending_changes)
# sin tocarlo: ver ProvisionFormDialog._on_guardar y ProvisionesModule mas
# abajo (patron ya usado en Contratos y en comercial.py con
# _ComercialModuleLegacy).
# =========================================================
MODULE_ACCENT_PROV = MODULE_COLORS.get("Provisiones", PRIMARY)

_PLAN_OPCIONES = ["Basico", "Medio", "Full", "Full + CIV", "Medio + CIV"]

def _formato_moneda_prov(valor):
    try:
        valor = float(valor)
    except (TypeError, ValueError):
        valor = 0.0
    return provisiones_services.formatear_moneda(valor)



class ProvisionFormDialog(QDialog):
    """Formulario de un registro de Provision (VIN + período). El período
    (AÑO - MES) nunca se edita -- igual que en la tabla actual, donde no es
    una columna editable -- por eso aquí es de solo lectura. DYNAFLEET,
    Cantidad de Meses y Plan sí se editan, y Monto Provisionado/Valor
    Plan/VAR se recalculan en vivo con la misma formula que ya usa
    ProvisionesModule.on_item_edited (provisiones_services.calcular_montos_provision),
    para que el usuario vea el resultado antes de guardar. Guardar reenvia
    los campos editados a on_item_edited (una llamada por columna) y termina
    en confirm_save(), igual que ContratoFormDialog en contratos.py."""

    guardado = pyqtSignal(str, str, dict)

    def __init__(self, cliente, fila, planes_data, uf, parent=None, industria="-"):
        super().__init__(parent)
        self.fila = dict(fila)
        self.planes_data = planes_data
        self.uf = uf
        self.setWindowTitle("Editar Provisión")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        card = QFrame()
        card.setObjectName("form_card_prov")
        card.setStyleSheet(f"QFrame#form_card_prov {{ background-color: {SURFACE}; }}")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("background-color: #F5F3FF;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon('fa5s.truck', color=MODULE_ACCENT_PROV).pixmap(16, 16))
        header_layout.addWidget(icon_lbl)
        header_layout.addSpacing(8)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        titulo = QLabel(f"Provisión {self.fila.get('VIN', '-')}")
        titulo.setStyleSheet(f"font-size: 13px; color: {MODULE_ACCENT_PROV}; font-weight: bold; background: transparent;")
        subtitulo = QLabel(f"{cliente}  ·  {self.fila.get('AÑO - MES', '-')}")
        subtitulo.setStyleSheet(f"font-size: 10px; color: {TEXT_SECONDARY}; background: transparent;")
        text_col.addWidget(titulo)
        text_col.addWidget(subtitulo)
        header_layout.addLayout(text_col)
        header_layout.addStretch()
        card_layout.addWidget(header)

        fields_frame = QFrame()
        fields_layout = QVBoxLayout(fields_frame)
        fields_layout.setContentsMargins(16, 14, 16, 16)
        fields_layout.setSpacing(10)

        def _campo(etiqueta, valor, solo_lectura):
            box = QVBoxLayout()
            box.setSpacing(2)
            lbl = QLabel(etiqueta)
            lbl.setStyleSheet(f"font-size: 9px; color: {TEXT_SECONDARY}; font-weight: bold;")
            campo = QLineEdit(str(valor) if valor not in (None, "") else "-")
            campo.setReadOnly(solo_lectura)
            box.addWidget(lbl)
            box.addWidget(campo)
            return box, campo

        row1 = QHBoxLayout(); row1.setSpacing(10)
        box, _ = _campo("VIN", self.fila.get('VIN', '-'), True)
        row1.addLayout(box, 1)
        box, _ = _campo("PERÍODO (AÑO - MES)", self.fila.get('AÑO - MES', '-'), True)
        row1.addLayout(box, 1)
        fields_layout.addLayout(row1)

        row_info = QHBoxLayout(); row_info.setSpacing(10)
        box, _ = _campo("INDUSTRIA", industria, True)
        row_info.addLayout(box, 1)
        box, _ = _campo("OBSERVACIONES", self.fila.get('OBSERVACIONES', '-'), True)
        row_info.addLayout(box, 1)
        fields_layout.addLayout(row_info)

        row2 = QHBoxLayout(); row2.setSpacing(10)
        box, self.input_dynafleet = _campo("DYNAFLEET (COBRO)", self.fila.get('DYNAFLEET', '$-'), False)
        row2.addLayout(box, 1)
        box, self.input_meses = _campo("CANTIDAD DE MESES", self.fila.get('Cantidad de Meses', '-'), False)
        row2.addLayout(box, 1)
        fields_layout.addLayout(row2)

        row3 = QHBoxLayout(); row3.setSpacing(10)
        box_plan = QVBoxLayout(); box_plan.setSpacing(2)
        lbl_plan = QLabel("PLAN")
        lbl_plan.setStyleSheet(f"font-size: 9px; color: {TEXT_SECONDARY}; font-weight: bold;")
        self.combo_plan = estilo_com.ComboTarjeta("Plan")
        self.combo_plan.addItems(_PLAN_OPCIONES)
        ThemeManager.apply_combo_box(self.combo_plan)
        self.combo_plan.setMaxVisibleItems(8)
        valor_plan = str(self.fila.get('Plan', '-')).strip()
        idx_plan = next((i for i, p in enumerate(_PLAN_OPCIONES) if p.upper() == valor_plan.upper()), -1)
        if idx_plan >= 0:
            self.combo_plan.setCurrentIndex(idx_plan)
        box_plan.addWidget(lbl_plan)
        box_plan.addWidget(self.combo_plan)
        row3.addLayout(box_plan, 1)
        fields_layout.addLayout(row3)

        calc_frame = QFrame()
        calc_frame.setStyleSheet(f"background-color: {BACKGROUND}; border-radius: 8px;")
        calc_layout = QHBoxLayout(calc_frame)
        calc_layout.setContentsMargins(12, 10, 12, 10)
        calc_layout.setSpacing(10)

        def _campo_calculado(etiqueta):
            box = QVBoxLayout(); box.setSpacing(2)
            lbl = QLabel(etiqueta)
            lbl.setStyleSheet(f"font-size: 9px; color: {TEXT_SECONDARY}; font-weight: bold; background: transparent;")
            valor = QLabel("$-")
            valor.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {MODULE_ACCENT_PROV}; background: transparent;")
            box.addWidget(lbl)
            box.addWidget(valor)
            calc_layout.addLayout(box, 1)
            return valor

        self.lbl_monto_calc = _campo_calculado("MONTO PROVISIONADO")
        self.lbl_valor_plan_calc = _campo_calculado("VALOR PLAN")
        self.lbl_var_calc = _campo_calculado("VAR")
        fields_layout.addWidget(calc_frame)

        card_layout.addWidget(fields_frame)
        layout.addWidget(card)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(16, 0, 16, 16)
        btn_row.addStretch()
        btn_cancelar = QPushButton("Cancelar")
        ThemeManager.apply_secondary_button(btn_cancelar)
        btn_cancelar.clicked.connect(self.reject)
        btn_guardar = QPushButton(" Guardar")
        btn_guardar.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        ThemeManager.apply_primary_button(btn_guardar)
        btn_guardar.clicked.connect(self._on_guardar)
        btn_row.addWidget(btn_cancelar)
        btn_row.addWidget(btn_guardar)
        layout.addLayout(btn_row)

        self.input_dynafleet.textChanged.connect(self._formatear_dynafleet_en_vivo)
        self.input_meses.textChanged.connect(self._formatear_meses_en_vivo)
        self.combo_plan.currentTextChanged.connect(self._recalcular)
        self._recalcular()

    def _formatear_dynafleet_en_vivo(self, texto):
        """Solo permite digitos o '-' (a pedido del usuario, 20-09-2026):
        cualquier otro caracter se descarta al vuelo, y los digitos se
        reformatean de inmediato como '$XXX.XXX.XXX' mientras se escribe. Un
        '-' inicial se conserva como signo negativo (DYNAFLEET si admite
        valores negativos, ver provisiones_services.parsear_dynafleet);
        un '-' solo (sin digitos) queda tal cual mientras se sigue
        escribiendo."""
        negativo = texto.strip().startswith('-')
        solo_digitos = ''.join(c for c in texto if c.isdigit())
        if not solo_digitos:
            nuevo = '-' if negativo else ''
        else:
            signo = '-' if negativo else ''
            nuevo = f"{signo}${int(solo_digitos):,}".replace(',', '.')
        if nuevo != texto:
            self.input_dynafleet.blockSignals(True)
            self.input_dynafleet.setText(nuevo)
            self.input_dynafleet.setCursorPosition(len(nuevo))
            self.input_dynafleet.blockSignals(False)
        self._recalcular()

    def _formatear_meses_en_vivo(self, texto):
        """Mismo criterio que DYNAFLEET (solo digitos o '-'), pero sin
        formato de miles -- Cantidad de Meses es un numero simple."""
        if texto.strip() == '-':
            nuevo = '-'
        else:
            nuevo = ''.join(c for c in texto if c.isdigit())
        if nuevo != texto:
            self.input_meses.blockSignals(True)
            self.input_meses.setText(nuevo)
            self.input_meses.setCursorPosition(len(nuevo))
            self.input_meses.blockSignals(False)
        self._recalcular()

    def _valores_actuales(self):
        """Mismo parseo que on_item_edited, pero solo para el recalculo en
        vivo del dialogo (no valida ni muestra errores -- eso lo hace
        on_item_edited al guardar de verdad)."""
        _, dato = provisiones_services.parsear_dynafleet(self.input_dynafleet.text())
        val_dynafleet = dato["num"] if dato else 0.0

        val_meses = 1.0
        meses_txt = str(self.input_meses.text()).strip()
        if meses_txt and meses_txt.upper() not in ("-", "MENSUAL"):
            try:
                val_meses = float(meses_txt)
            except ValueError:
                val_meses = 1.0

        return val_dynafleet, val_meses, self.combo_plan.currentText().strip()

    def _recalcular(self):
        val_dynafleet, val_meses, nombre_plan = self._valores_actuales()
        monto_prov, valor_plan_exacto, variacion = provisiones_services.calcular_montos_provision(
            val_dynafleet, val_meses, nombre_plan, self.planes_data, self.uf
        )
        self.lbl_monto_calc.setText(_formato_moneda_prov(monto_prov))
        self.lbl_valor_plan_calc.setText(_formato_moneda_prov(valor_plan_exacto))
        self.lbl_var_calc.setText(_formato_moneda_prov(variacion))

        # Mismo criterio de color que tenia la tabla original
        # (ProvisionesTableModel): rojo si VAR es negativo, verde si es
        # positivo, color neutro si es exactamente cero.
        if variacion < 0:
            color_var = DANGER
        elif variacion > 0:
            color_var = SUCCESS
        else:
            color_var = TEXT_SECONDARY
        self.lbl_var_calc.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {color_var}; background: transparent;")

    def _on_guardar(self):
        cambios = {
            'DYNAFLEET': self.input_dynafleet.text(),
            'Cantidad de Meses': self.input_meses.text(),
            'Plan': self.combo_plan.currentText(),
        }
        vin = str(self.fila.get('VIN', '')).strip()
        periodo = str(self.fila.get('AÑO - MES', '')).strip()
        self.guardado.emit(vin, periodo, cambios)
        self.accept()


class _ProvisionesModuleLegacy(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.data_manager.provisiones_ready.connect(self._on_data_ready)
        self.data_manager.load_provisiones_error.connect(self._on_load_error)
        self.pending_changes = {}
        # Fase 1 de la auditoria de rendimiento (17-09-2026): se evaluo
        # agregar aqui el mismo guard de visibilidad que general.py/
        # comercial.py/contratos.py, pero se revirtio -- a diferencia de
        # data_ready/logs_updated (que se disparan por CUALQUIER guardado en
        # CUALQUIER modulo), provisiones_ready SOLO se emite como consecuencia
        # de una accion propia de este modulo (load_provisiones_async() no lo
        # llama nadie mas, ver DataManager); en uso real, si esta señal llega,
        # es porque el usuario esta usando Provisiones en ese momento. Agregar
        # el guard no evitaba trabajo real (no hay reprocesamiento oculto que
        # prevenir) y sí rompia el refresco esperado tras guardar/recargar.
        self.search_input = QLineEdit()
        self.search_input.hide()
        self._setup_ui()
        # La primera lectura del Excel parte después de la transición de
        # entrada: si corre mientras se arma el grupo le quita el GIL a la UI
        self.btn_reload.setEnabled(False)
        self.btn_save.setEnabled(False)
        QTimer.singleShot(300, self._trigger_reload)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        
        header_layout = QHBoxLayout()

        self.lbl_uf_status = QLabel("")
        self.lbl_uf_status.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {SUCCESS}; padding-left: 15px;")

        self.btn_ajustes = QPushButton(" Ajustes de Costos")
        self.btn_ajustes.setIcon(ThemeManager.icon('fa5s.cog', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(self.btn_ajustes)
        self.btn_ajustes.clicked.connect(self.open_costos_dialog)

        header_layout.addWidget(self.lbl_uf_status)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_ajustes)
        main_layout.addLayout(header_layout)

        self.controls_frame = QFrame()
        ThemeManager.apply_card_style(self.controls_frame)
        controls_layout = QHBoxLayout(self.controls_frame)
        
        self.btn_add_sync = QPushButton()
        self.btn_add_sync.setIcon(ThemeManager.icon('fa5s.plus', color='white')) 
        self.btn_add_sync.setFixedSize(32, 32)
        self.btn_add_sync.setStyleSheet(f"background-color: {SUCCESS}; border-radius: 16px;")
        self.btn_add_sync.clicked.connect(self.open_sync_dialog)

        # --- FILTRO FECHAS ---
        self.combo_fecha = estilo_com.ComboTarjeta("Mes")
        self.combo_fecha.addItem("Todos los Meses")
        ThemeManager.apply_combo_box(self.combo_fecha)
        self.combo_fecha.setMaxVisibleItems(8)                           # <--- LÍNEA NUEVA
        self.combo_fecha.view().setMaximumHeight(250)                    # <--- LÍNEA NUEVA
        self.combo_fecha.currentTextChanged.connect(self.filter_table)
        
        # --- FILTRO PLANES ---
        self.combo_plan = estilo_com.ComboTarjeta("Plan")
        self.combo_plan.addItem("Todos los Planes")
        ThemeManager.apply_combo_box(self.combo_plan)
        self.combo_plan.setMaxVisibleItems(8)                            # <--- LÍNEA NUEVA
        self.combo_plan.view().setMaximumHeight(250)                     # <--- LÍNEA NUEVA
        self.combo_plan.currentTextChanged.connect(self.filter_table)

        from PyQt6.QtWidgets import QCheckBox
        self.chk_ocultar_ceros = QCheckBox("Ocultar Dynafleet = 0")
        self.chk_ocultar_ceros.setChecked(True) 
        self.chk_ocultar_ceros.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {TEXT_SECONDARY}; margin-left: 10px;")
        self.chk_ocultar_ceros.stateChanged.connect(self.filter_table)

        self.btn_export_excel = QPushButton(" Excel")
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='white'))
        ThemeManager.apply_success_button(self.btn_export_excel)
        self.btn_export_excel.clicked.connect(lambda: self.table.export_to_excel("Reporte_Provisiones"))
        
        self.btn_reload = QPushButton(" Recargar")
        self.btn_reload.setIcon(ThemeManager.icon('fa5s.sync-alt', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(self.btn_reload)
        self.btn_reload.clicked.connect(lambda: self._trigger_reload(is_manual_reload=True))

        self.btn_save = QPushButton(" Guardar")
        self.btn_save.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        ThemeManager.apply_primary_button(self.btn_save)
        self.btn_save.clicked.connect(self.confirm_save)

        controls_layout.addWidget(self.btn_add_sync) 
        controls_layout.addWidget(self.combo_fecha) 
        controls_layout.addWidget(self.combo_plan)
        controls_layout.addWidget(self.chk_ocultar_ceros)
        controls_layout.addStretch()
        controls_layout.addWidget(self.btn_export_excel)
        controls_layout.addWidget(self.btn_reload)
        controls_layout.addWidget(self.btn_save) 
        main_layout.addWidget(self.controls_frame)

        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        self.loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.loading_widget)
        loading_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading_layout.addWidget(
            crear_tarjeta_carga("Procesando datos financieros…", "Esto tomará unos segundos."),
            alignment=Qt.AlignmentFlag.AlignCenter)

        self.stack.addWidget(self.loading_widget)

        self.table_widget_container = QWidget()
        table_layout = QVBoxLayout(self.table_widget_container)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.table = VolvoTableWidget()
        self.table.menu_type = "general"  # Provisiones no tiene "Eliminar Camión"
        self.model = ProvisionesTableModel(self)
        self.table.set_model_and_delegate(self.model, {'Plan': ["Basico", "Medio", "Full", "Full + CIV", "Medio + CIV"]})
        self.table.item_edited.connect(self.on_item_edited)
        self.table.sort_changed.connect(self.filter_table)

        original_key_press = self.table.keyPressEvent
        
        def custom_key_press(event):
            if event.matches(QKeySequence.StandardKey.Paste):
                indexes = self.table.selectedIndexes()
                if indexes:
                    df_view = self.model.get_df()
                    if 'Plan' in df_view.columns:
                        plan_col_idx = df_view.columns.get_loc('Plan')
                        selected_plan_cells = [idx for idx in indexes if idx.column() == plan_col_idx]
                        if selected_plan_cells:
                            self.paste_plan_to_selection(selected_plan_cells)
                            return
            original_key_press(event)
            
        self.table.keyPressEvent = custom_key_press
        table_layout.addWidget(self.table)
        self.stack.addWidget(self.table_widget_container)

    def paste_plan_to_selection(self, selected_plan_cells):
        clipboard_text = QApplication.clipboard().text().strip()
        if not clipboard_text:
            return
            
        # 1. Definir los valores permitidos para la columna 'Plan'
        opciones_validas = ["Basico", "Medio", "Full", "Full + CIV", "Medio + CIV"]
        
        # 2. Normalizamos el portapapeles (ignora mayúsculas/minúsculas y espacios extra)
        clipboard_upper = clipboard_text.upper()
        opciones_upper = {opc.upper(): opc for opc in opciones_validas}
        
        # 3. Validación: Si el texto copiado no está en la lista de opciones...
        if clipboard_upper not in opciones_upper:
            QMessageBox.warning(
                self, 
                "Pegado Inválido", 
                f"El valor '{clipboard_text}' no es un Plan válido.\n\nOpciones permitidas:\n- " + "\n- ".join(opciones_validas)
            )
            return # Interrumpe el pegado, conservando el valor original de cada celda

        # 4. Si pasó la validación, usamos el valor exacto del diccionario para evitar problemas de capitalización
        valor_correcto = opciones_upper[clipboard_upper]
            
        for idx in selected_plan_cells:
            self.model.setData(idx, valor_correcto, Qt.ItemDataRole.EditRole)

    def open_sync_dialog(self):
        dialog = SyncTerminalDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted: self._trigger_reload(is_manual_reload=True)

    def on_item_edited(self, row, col_name, new_value):
        if getattr(self, '_is_updating', False): return
        self._is_updating = True
        
        try:
            df_actual = self.model.get_df()
            vin_value = str(df_actual.iat[row, df_actual.columns.get_loc('VIN')]).strip().upper()
            fecha_value = str(df_actual.iat[row, df_actual.columns.get_loc('AÑO - MES')]).strip().upper()

            if col_name in ['Monto Provisionado', 'Valor Plan', 'VAR']: return

            unique_key = f"{vin_value}_{fecha_value}"
            if unique_key not in self.pending_changes: 
                self.pending_changes[unique_key] = {'VIN': vin_value, 'AÑO - MES': fecha_value, 'cambios': {}}
            
            columnas_afectadas = []

            if col_name == 'Cantidad de Meses':
                resultado, valor = provisiones_services.validar_cantidad_meses(new_value)

                if resultado == "invalido":
                    QMessageBox.warning(self, "Error", valor)
                    df_actual.iat[row, df_actual.columns.get_loc(col_name)] = ""

                    col_err_idx = df_actual.columns.get_loc(col_name)
                    idx = self.model.index(row, col_err_idx)
                    self.model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
                    return

                if resultado == "mensual":
                    self.pending_changes[unique_key]['cambios']['Cantidad de Meses'] = '-'
                    df_actual.iat[row, df_actual.columns.get_loc('Cantidad de Meses')] = '-'
                else:  # "vacio" o "numerico"
                    self.pending_changes[unique_key]['cambios'][col_name] = valor

            elif col_name == 'DYNAFLEET':
                resultado, dato = provisiones_services.parsear_dynafleet(new_value)

                if resultado == "invalido":
                    QMessageBox.warning(self, "Error", "El cobro (Dynafleet) debe ser un número válido.")
                    old_row = self.df_base[(self.df_base['VIN'] == vin_value) & (self.df_base['AÑO - MES'] == fecha_value)]
                    old_val_raw = old_row.iloc[0]['DYNAFLEET'] if not old_row.empty else 0
                    try:
                        old_num = float(str(old_val_raw).replace('$', '').replace('.', '').replace(',', '').strip()) if old_val_raw else 0.0
                    except:
                        old_num = 0.0
                    old_formato = provisiones_services.formatear_moneda(old_num)

                    df_actual.iat[row, df_actual.columns.get_loc(col_name)] = old_formato

                    col_err_idx = df_actual.columns.get_loc(col_name)
                    idx = self.model.index(row, col_err_idx)
                    self.model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole])
                    return

                self.pending_changes[unique_key]['cambios'][col_name] = dato["num"]
                df_actual.iat[row, df_actual.columns.get_loc(col_name)] = dato["formato"]
                new_value = dato["formato"]
                columnas_afectadas.append(df_actual.columns.get_loc(col_name))
            else:
                self.pending_changes[unique_key]['cambios'][col_name] = new_value

            try:
                uf, civ = self.data_manager.get_variables()
                planes_data = self.data_manager.get_costos()

                col_dynafleet_idx = df_actual.columns.get_loc('DYNAFLEET') if 'DYNAFLEET' in df_actual.columns else None
                col_meses_idx = df_actual.columns.get_loc('Cantidad de Meses') if 'Cantidad de Meses' in df_actual.columns else None
                col_plan_idx = df_actual.columns.get_loc('Plan') if 'Plan' in df_actual.columns else None

                val_dynafleet = 0.0
                val_meses = 1.0
                nombre_plan = ""

                if col_dynafleet_idx is not None:
                    val_raw = str(df_actual.iat[row, col_dynafleet_idx]).replace('$', '').replace('.', '')
                    if val_raw and val_raw != '$-': val_dynafleet = float(val_raw)
                if col_name == 'DYNAFLEET':
                    val_raw = str(new_value).replace('$', '').replace('.', '')
                    if val_raw and val_raw != '$-': val_dynafleet = float(val_raw)

                if col_meses_idx is not None:
                    val_raw = df_actual.iat[row, col_meses_idx]
                    if pd.notna(val_raw) and str(val_raw).strip() not in ["", "-", "MENSUAL"]: val_meses = float(val_raw)
                if col_name == 'Cantidad de Meses':
                    if str(new_value).strip() not in ["", "-", "MENSUAL"]: val_meses = float(new_value)

                if col_plan_idx is not None:
                    nombre_plan = str(df_actual.iat[row, col_plan_idx]).strip()
                if col_name == 'Plan':
                    nombre_plan = str(new_value).strip()

                monto_prov, valor_plan_exacto, variacion = provisiones_services.calcular_montos_provision(
                    val_dynafleet, val_meses, nombre_plan, planes_data, uf
                )

                if 'Monto Provisionado' in df_actual.columns:
                    df_actual.iat[row, df_actual.columns.get_loc('Monto Provisionado')] = provisiones_services.formatear_moneda(monto_prov)
                    self.pending_changes[unique_key]['cambios']['Monto Provisionado'] = monto_prov
                    columnas_afectadas.append(df_actual.columns.get_loc('Monto Provisionado'))

                if 'Valor Plan' in df_actual.columns:
                    df_actual.iat[row, df_actual.columns.get_loc('Valor Plan')] = provisiones_services.formatear_moneda(valor_plan_exacto)
                    self.pending_changes[unique_key]['cambios']['Valor Plan'] = valor_plan_exacto
                    columnas_afectadas.append(df_actual.columns.get_loc('Valor Plan'))

                if 'VAR' in df_actual.columns:
                    df_actual.iat[row, df_actual.columns.get_loc('VAR')] = provisiones_services.formatear_moneda(variacion)
                    self.pending_changes[unique_key]['cambios']['VAR'] = variacion
                    columnas_afectadas.append(df_actual.columns.get_loc('VAR'))

                col_edit_idx = df_actual.columns.get_loc(col_name)
                if col_edit_idx not in columnas_afectadas:
                    columnas_afectadas.append(col_edit_idx)
                
                for c_idx in set(columnas_afectadas):
                    idx = self.model.index(row, c_idx)
                    self.model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole])

            except Exception as e:
                print(f"Error calculando en vivo: {e}")
        
        finally:
            self._is_updating = False

    def confirm_save(self):
        valid = {k: d for k, d in self.pending_changes.items() if d.get('cambios')}
        if not valid: return QMessageBox.information(self, "Aviso", "No hay cambios.")
        self.btn_save.setEnabled(False)
        self.btn_reload.setEnabled(False)

        mostrar_guardando(self, "Guardando provisiones y sincronizando con Comercial…")

        self.save_thread = SaveProvisionesThread(valid, self.writer, self.data_manager)
        self.save_thread.finished_signal.connect(self._on_save_finished)
        self.save_thread.start()

    def _on_save_finished(self, success, pending_data, vins_huerfanos, cross_updates):
        self.btn_save.setEnabled(True)
        self.btn_reload.setEnabled(True)
        
        if success:
            guardado_listo(self)
            try:
                dm = self.data_manager
                if not dm.df_prov.empty:
                    df_m = dm.df_prov.copy()
                    for key, data in pending_data.items():
                        vin_val = str(data['VIN']).strip()
                        mes_val = str(data['AÑO - MES']).strip()
                        mask = (df_m['VIN'].astype(str).str.strip() == vin_val) & (df_m['AÑO - MES'].astype(str).str.strip() == mes_val)
                        if mask.any():
                            for col, val in data['cambios'].items():
                                if col in df_m.columns:
                                    df_m[col] = df_m[col].astype(object) 
                                    df_m.loc[mask, col] = val
                    dm.df_prov = df_m
                
                if cross_updates and not dm.df_master.empty:
                    dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, cross_updates)
                    # Avisa a Comercial/Vista General que df_master cambió en
                    # RAM (mismo patrón que VincularComercialDialog._on_creado):
                    # sin esto quedaban desactualizados hasta un Recargar
                    # manual, porque el único punto que emitía data_ready era
                    # una recarga completa desde disco (load_data_async),
                    # nunca disparada por este flujo (cross_updates ya evita
                    # esa relectura por rendimiento).
                    dm.data_ready.emit()

                self.pending_changes.clear()
                self._trigger_reload(is_manual_reload=False) 
                
                vins_cerrados = list(getattr(self.save_thread, 'vins_cerrados', []))
                vins_omitidos = list(getattr(self.save_thread, 'vins_omitidos', []))

                def _avisar_resultado():
                    terminar_guardando(self)
                    if vins_huerfanos:
                        self._show_rescue_dialog(vins_huerfanos)
                    if vins_omitidos:
                        self._avisar_vins_omitidos(vins_omitidos)
                    if vins_cerrados:
                        self._ofrecer_contrato_nuevo(vins_cerrados)
                QTimer.singleShot(800, _avisar_resultado)

            except Exception as e:
                print(f"Fallo inyectando RAM en Provisiones: {e}")
                terminar_guardando(self, exito=False)
                self._trigger_reload(global_reload=True, is_manual_reload=False)
        else:
            terminar_guardando(self, exito=False)
            self.stack.setCurrentIndex(1)
            error_msg = pending_data.get('error', 'Error desconocido.')
            QMessageBox.warning(self, "Error", f"No se pudo guardar el archivo:\n{error_msg}")

    def _avisar_vins_omitidos(self, vins_omitidos):
        detalle = "\n".join(f"• {vin} (forma de contrato: {forma or '-'})" for vin, forma in vins_omitidos)
        QMessageBox.information(
            self, "Provisiones guardadas",
            "Se guardó en Provisiones. Los datos no pasaron a Comercial porque el contrato actual de estos VIN "
            "no es de forma Provision:\n\n" + detalle)

    def _ofrecer_contrato_nuevo(self, vins_cerrados):
        detalle = "\n".join(f"• {vin}" for vin, _ in vins_cerrados)
        respuesta = QMessageBox.question(
            self, "Contrato finalizado",
            "Se guardó en Provisiones. Estos VIN tienen su contrato finalizado (Baja), así que no se modificó "
            "Comercial:\n\n" + detalle + "\n\n¿Crear un contrato nuevo de forma Provision para estas unidades?")
        if respuesta == QMessageBox.StandardButton.Yes:
            VincularComercialDialog(vins_cerrados, self.data_manager, self, nuevo_contrato=True).exec()

    def _show_rescue_dialog(self, vins_huerfanos):
        alerta = VinsHuerfanosAlertDialog(vins_huerfanos, self)
        if alerta.exec() == QDialog.DialogCode.Accepted:
            dialog = VincularComercialDialog(vins_huerfanos, self.data_manager, self)
            dialog.exec()

    def _trigger_reload(self, global_reload=False, is_manual_reload=False):
        if is_manual_reload:
            self.pending_changes.clear()


        self.btn_reload.setEnabled(False)
        self.btn_save.setEnabled(False)
        
        self.stack.setCurrentIndex(0)
        QApplication.processEvents() 
        
        self._ejecutar_cargas(global_reload)
        QTimer.singleShot(12000, self._force_unlock_buttons)

    def _force_unlock_buttons(self):
        if not self.btn_reload.isEnabled():
            self.btn_reload.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.stack.setCurrentIndex(1) 

    def _ejecutar_cargas(self, global_reload):
        self.data_manager.load_provisiones_async()
        if global_reload:
            self.data_manager.load_data_async()

    def _on_data_ready(self):
        try:
            self.load_data()
        except Exception as e:
            print(f"Error silencioso matemático en Provisiones: {e}")
        finally:
            self.btn_reload.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.stack.setCurrentIndex(1)

    def _on_load_error(self, error_msg):
        self.btn_reload.setEnabled(True)
        self.stack.setCurrentIndex(1)
        QMessageBox.critical(self, "Error", error_msg)

    def load_data(self):
        uf, _ = self.data_manager.get_variables()
        self.lbl_uf_status.setText(f"UF del día: ${uf:,.2f}".replace(",", "."))
        # Referencia (no copia) del origen, para saber si los datos cambiaron
        # desde esta carga (ver ProvisionesModule._on_new_ui_tab_refresh_if_dirty).
        self._df_prov_origen = self.data_manager.df_prov
        df_raw = self.data_manager.get_provisiones_df()
        self.df_base = df_raw.copy() if not df_raw.empty else df_raw
        
        if not self.df_base.empty and 'Cantidad de Meses' in self.df_base.columns:
            self.df_base['Cantidad de Meses'] = self.df_base['Cantidad de Meses'].apply(provisiones_services.limpiar_cantidad_meses_display)
        
        if not self.df_base.empty and 'AÑO - MES' in self.df_base.columns:
            fechas_str = self.df_base['AÑO - MES'].astype(str)
            fechas_unicas = [f.strip() for f in fechas_str.unique() if f.strip() and f.strip().lower() != 'nan']
            meses_a_num = {'Enero': 1, 'Febrero': 2, 'Marzo': 3, 'Abril': 4, 'Mayo': 5, 'Junio': 6, 'Julio': 7, 'Agosto': 8, 'Septiembre': 9, 'Octubre': 10, 'Noviembre': 11, 'Diciembre': 12}
            fechas_ordenadas = sorted(fechas_unicas, key=lambda f: (int(f.split("-")[0].strip()), meses_a_num.get(f.split("-")[1].strip().capitalize(), 0)) if "-" in f else (0,0), reverse=True)
            fecha_previa = self.combo_fecha.currentText()
            self.combo_fecha.blockSignals(True)
            self.combo_fecha.clear(); self.combo_fecha.addItem("Todos los Meses"); self.combo_fecha.addItems(fechas_ordenadas)
            idx_fecha = self.combo_fecha.findText(fecha_previa)
            self.combo_fecha.setCurrentIndex(idx_fecha if idx_fecha >= 0 else 0)
            self.combo_fecha.blockSignals(False)
        
        if not self.df_base.empty and 'Plan' in self.df_base.columns:
            planes_unicos = [p.strip() for p in self.df_base['Plan'].astype(str).unique() if p.strip() and p.strip().lower() != 'nan']
            plan_previo = self.combo_plan.currentText()
            self.combo_plan.blockSignals(True)
            self.combo_plan.clear(); self.combo_plan.addItem("Todos los Planes"); self.combo_plan.addItems(sorted(planes_unicos))
            idx_plan = self.combo_plan.findText(plan_previo)
            self.combo_plan.setCurrentIndex(idx_plan if idx_plan >= 0 else 0)
            self.combo_plan.blockSignals(False)

        # La tabla (formatea montos de todas las filas) solo se arma si
        # "Vista Completa" está a la vista; al mostrarla se vuelve a llamar
        # load_data (ProvisionesModule._on_internal_tab_changed).
        if self.isVisible():
            self.filter_table()
        else:
            self._tabla_pendiente = True

    def filter_table(self):
        self._tabla_pendiente = False
        if self.df_base.empty: return
        search_text = self.search_input.text().lower()
        f_fecha, f_plan = self.combo_fecha.currentText(), self.combo_plan.currentText()
        ocultar_ceros = getattr(self, 'chk_ocultar_ceros', None) and self.chk_ocultar_ceros.isChecked()
        
        df_f = self.df_base.copy()
        if f_fecha != "Todos los Meses": df_f = df_f[df_f['AÑO - MES'].astype(str).str.strip() == f_fecha]
        if f_plan != "Todos los Planes": df_f = df_f[df_f['Plan'].astype(str).str.strip() == f_plan]
        if ocultar_ceros and 'DYNAFLEET' in df_f.columns: df_f = df_f[pd.to_numeric(df_f['DYNAFLEET'], errors='coerce').fillna(0) > 0]
                
        if search_text:
            cols = [c for c in ['VIN', 'CLIENTE', 'EJECUTIVO'] if c in df_f.columns]
            or_terms = [t.strip() for t in search_text.split(',') if t.strip()]
            
            final_mask = pd.Series(False, index=df_f.index)
            for or_term in or_terms:
                and_terms = [t.strip() for t in or_term.split() if t.strip()]
                and_mask = pd.Series(True, index=df_f.index)
                
                for a_term in and_terms:
                    col_mask = pd.Series(False, index=df_f.index)
                    for col in cols: 
                        col_mask |= df_f[col].astype(str).str.lower().str.contains(a_term, na=False, regex=False)
                    and_mask &= col_mask
                    
                final_mask |= and_mask
                
            df_f = df_f[final_mask]

        if hasattr(self, 'pending_changes') and self.pending_changes:
            for key, data in self.pending_changes.items():
                v_val = str(data['VIN']).strip().upper()
                # AÑADIDO .UPPER() AQUÍ
                m_val = str(data['AÑO - MES']).strip().upper() 
                
                # AÑADIDO .UPPER() A LA MÁSCARA DEL DATAFRAME
                mask = (df_f['VIN'].astype(str).str.strip().str.upper() == v_val) & \
                       (df_f['AÑO - MES'].astype(str).str.strip().str.upper() == m_val)
                
                if mask.any():
                    for col_c, val_c in data['cambios'].items():
                        if col_c in df_f.columns:
                            df_f[col_c] = df_f[col_c].astype(object) 
                            df_f.loc[mask, col_c] = val_c
            
        df_display = df_f.copy()
        for col in ['Monto Provisionado', 'Valor Plan', 'VAR', 'DYNAFLEET']:
            if col in df_display.columns:
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce').fillna(0).apply(provisiones_services.formatear_moneda)

        # Ordenamiento tipo Excel elegido por el usuario (clic de encabezado /
        # menú contextual). No afecta a df_base ni a ningún dato persistido:
        # es un no-op si no hay ordenamiento activo. ProvisionesTableModel
        # calcula el resaltado naranja dinámicamente por VIN+AÑO-MES (no por
        # coordenada fija), así que reordenar filas aquí no lo desincroniza.
        df_display = self.table.apply_sort(df_display)

        self.model.set_data(df_display)

    def open_costos_dialog(self):
        if CostosDialog(self).exec() == QDialog.DialogCode.Accepted: self._trigger_reload(is_manual_reload=True)


# =========================================================
# PANTALLA "PROVISIONES" (clientes -> registros) sobre el esqueleto de
# ingresos_base.py. El motor de datos y guardado sigue siendo
# _ProvisionesModuleLegacy (oculto: on_item_edited/confirm_save/
# pending_changes, sincronización y ajustes de costos); desde el 05-10-2026
# ya no existe la pestaña "Vista Completa", el formulario de registro es la
# única vía de edición.
# =========================================================
_CHIP_VOLVO = ("#E1EAF4", VOLVO_BLUE)
_CHIP_COBRO = {"CON COBRO": ("#D1FAE5", "#065F46"), "SIN COBRO": ("#F3F4F6", "#4B5563")}
_CHIP_VAR_NEGATIVA = ("#FEE2E2", "#991B1B")
_CHIP_VAR_POSITIVA = ("#D1FAE5", "#065F46")

COL_PROV_CLIENTE = "CLIENTE"
COL_PROV_EJECUTIVO = "EJECUTIVO"
COL_PROV_REGISTROS = "REGISTROS"
COL_PROV_CLAVE = "_CLAVE"
COL_PROV_PERIODO = "PERÍODO"
COL_PROV_PLAN = "PLAN"
COL_PROV_DYNAFLEET = "DYNAFLEET"
COL_PROV_MESES = "MESES"
COL_PROV_MONTO = "MONTO PROVISIONADO"
COL_PROV_VALOR_PLAN = "VALOR PLAN"
COL_PROV_VARIACION = "VARIACIÓN"
COL_PROV_COBRO = "COBRO"

COL_PROV_INDUSTRIA = "INDUSTRIA"
COL_UNIDADES = "UNIDADES"
COL_PROV_MODELO = "MODELO"
# Marca invisible: el modelo no admite el CIV del plan elegido (se pinta naranja)
_MARCA_SIN_CIV = "​"
_CHIP_SIN_CIV = ("#FFEDD5", "#C2410C")
COL_PROV_OBS = "OBSERVACIÓN"

_COLUMNAS_CLIENTES_PROV = [COL_PROV_CLIENTE, COL_PROV_EJECUTIVO, COL_PROV_REGISTROS]
# Una sola tabla con todos los registros (sin agrupar por cliente)
_COLUMNAS_REGISTROS_PROV = [COL_PROV_CLAVE, COL_VIN, COL_PROV_CLIENTE, COL_UNIDADES, COL_PROV_INDUSTRIA, COL_PROV_MODELO, COL_PROV_PLAN,
                            COL_PROV_MESES, COL_PROV_DYNAFLEET, COL_PROV_VALOR_PLAN, COL_PROV_MONTO,
                            COL_PROV_VARIACION]
# Fracción del ancho de la tabla de cada columna (sin scroll horizontal; la última ocupa el resto)
_FRACCION_ANCHO_PROV = {
    COL_PROV_CLIENTE: 0.21, COL_PROV_PERIODO: 0.09, COL_UNIDADES: 0.09, COL_PROV_INDUSTRIA: 0.10, COL_PROV_PLAN: 0.09, COL_PROV_MESES: 0.06,
    COL_PROV_DYNAFLEET: 0.085, COL_PROV_VALOR_PLAN: 0.08, COL_PROV_MONTO: 0.095, COL_PROV_VARIACION: 0.085,
}
# Columna editable de la tabla -> columna del motor (df_base / pending_changes)
_EDITABLE_A_MOTOR = {COL_PROV_PLAN: 'Plan', COL_PROV_MESES: 'Cantidad de Meses'}
# Columna del DataFrame de provisiones -> columna de la tabla
_ORIGEN_REGISTRO = {
    COL_VIN: 'VIN', COL_PROV_PERIODO: 'AÑO - MES', COL_PROV_PLAN: 'Plan', COL_PROV_DYNAFLEET: 'DYNAFLEET',
    COL_PROV_MESES: 'Cantidad de Meses', COL_PROV_MONTO: 'Monto Provisionado', COL_PROV_VALOR_PLAN: 'Valor Plan',
    COL_PROV_VARIACION: 'VAR', COL_PROV_EJECUTIVO: 'EJECUTIVO',
}
# Columnas en verde si son positivas y en rojo si son negativas
_COLUMNAS_SIGNO_PROV = (COL_PROV_MONTO, COL_PROV_VALOR_PLAN, COL_PROV_VARIACION)
# Texto de un grupo cuyas unidades no tienen el mismo valor en esa columna
_VARIOS = "Varios"
_TODOS_MESES = "Todos los meses"
_TODOS_PLANES = "Todos los planes"


def _modelos_sin_civ(modelos, plan):
    """Modelos conocidos que no son de la familia F (ej. VM) cuando el plan
    incluye CIV; solo los camiones F pueden llevarlo."""
    if "CIV" not in str(plan).upper():
        return []
    return [m for m in modelos if m not in ("", "-", "N/A") and not m.upper().startswith("F")]


def _texto_modelo(modelos, plan):
    base = ", ".join(modelos) if modelos else "-"
    return base + _MARCA_SIN_CIV if _modelos_sin_civ(modelos, plan) else base


def _texto_celda(valor):
    texto = "" if valor is None or (not isinstance(valor, str) and pd.isna(valor)) else str(valor).strip()
    return texto if texto and texto.lower() != 'nan' else "-"


class ModeloTablaProvisiones(ModeloTablaIngresos):
    """Tabla de registros de solo lectura: la edición se hace en el panel
    derecho. Las celdas con cambios sin guardar (`celdas_pendientes`: {(clave
    en mayúsculas, columna)}) se pintan en ámbar."""

    celdas_pendientes = frozenset()

    def _data_claro(self, index, role):
        if self.celdas_pendientes and index.isValid() and role in (
                Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.FontRole):
            columna = self._df.columns[index.column()]
            if columna in _EDITABLE_A_MOTOR and COL_PROV_CLAVE in self._df.columns:
                clave = str(self._df.iat[index.row(), self._df.columns.get_loc(COL_PROV_CLAVE)]).strip().upper()
                if (clave, columna) in self.celdas_pendientes:
                    if role == Qt.ItemDataRole.BackgroundRole:
                        return QColor("#FEF3C7")
                    if role == Qt.ItemDataRole.ForegroundRole:
                        return QColor("#92400E")
                    fuente = QFont()
                    fuente.setBold(True)
                    return fuente
        return super()._data_claro(index, role)


class ProvisionesModule(PantallaIngresosBase):
    """Pantalla 'Provisiones': clientes -> registros (VIN x período). Los
    accesos que no pertenecen a la pantalla (model, table, combo_plan,
    on_item_edited, confirm_save, btn_save, etc.; ver
    src/tests/test_provisiones.py) se reenvían al motor self.legacy, igual que
    antes con las pestañas."""

    AVATAR = "PR"
    TITULO = "Provisiones"
    CAMPOS_FICHA = [
        ("Monto provisionado", COL_PROV_MONTO), ("Valor plan", COL_PROV_VALOR_PLAN),
        ("Variación", COL_PROV_VARIACION),
    ]
    COLUMNAS_FICHA = 3
    COL_CLAVE = COL_PROV_CLAVE
    COL_EMPRESA = COL_PROV_CLIENTE
    COLUMNAS_OCULTAS = (COL_PROV_CLAVE, COL_VIN)  # el VIN oculto trae todos los del grupo (menú Copiar VIN)
    COL_COPIA = COL_VIN
    ETIQUETA_COPIA = "VIN"
    NIVEL_UNICO = True
    CLASE_MODELO = ModeloTablaProvisiones
    ANCHOS_EMPRESAS = {COL_PROV_CLIENTE: 520, COL_PROV_EJECUTIVO: 240, COL_PROV_REGISTROS: 160}
    ANCHOS_DETALLE = {
        COL_PROV_CLIENTE: 260, COL_UNIDADES: 100, COL_PROV_PERIODO: 120, COL_PROV_INDUSTRIA: 130, COL_PROV_PLAN: 120, COL_PROV_MESES: 80,
        COL_PROV_DYNAFLEET: 110, COL_PROV_VALOR_PLAN: 110, COL_PROV_MONTO: 130, COL_PROV_VARIACION: 120,
    }

    _ATTRS_LEGACY = {'pending_changes', 'df_base'}

    def __init__(self):
        super().__init__()
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)
        # Nace con su padre: reparentarlo ya armado re-aplicaba los estilos a toda la tabla oculta
        self.legacy = _ProvisionesModuleLegacy(self)
        self.legacy.hide()

        self.search_input = QLineEdit()
        self.search_input.hide()
        self.filtro_periodo = ""
        self.filtro_plan = ""
        self._df_filtrado_prov = pd.DataFrame()
        self._grupos = {}
        self._grupo_de_registro = {}
        self._autocompletados = set()
        self._periodos_combo_actuales = []
        self._df_clientes = None

        self._setup_ui()
        self.legacy.data_manager.provisiones_ready.connect(self._refresh_new_ui_data)
        self._refresh_new_ui_data()

    def _setup_ui(self):
        self.construir_base()

        self.combo_periodo_prov = ComboFiltroBarra('fa5s.calendar-alt', "Mes")
        self.combo_periodo_prov.addItem(_TODOS_MESES, "")
        self.combo_plan_prov = ComboFiltroBarra('fa5s.layer-group', "Plan")
        self.combo_plan_prov.addItem(_TODOS_PLANES, "")
        for plan in _PLAN_OPCIONES:
            self.combo_plan_prov.addItem(plan, plan)
        for combo, ancho in ((self.combo_periodo_prov, 160), (self.combo_plan_prov, 150)):
            combo.setMinimumWidth(ancho)
            ThemeManager.apply_combo_box(combo)
            combo.setStyleSheet(estilo_combo_barra())
            combo.setMaxVisibleItems(9)
            self.agregar_filtro_compacto(combo)
        self.combo_periodo_prov.currentIndexChanged.connect(self._on_filtro_cambiado)
        self.combo_plan_prov.currentIndexChanged.connect(self._on_filtro_cambiado)

        self.btn_descartar_prov = boton_barra("", 'fa5s.undo')
        self.btn_descartar_prov.setToolTip("Descartar los cambios sin guardar")
        self.btn_descartar_prov.clicked.connect(self._descartar_cambios)
        self.agregar_capsula(self.btn_descartar_prov)
        self.btn_guardar_prov = boton_barra("", 'fa5s.save')
        self.btn_guardar_prov.setToolTip("Guardar los cambios")
        self.btn_guardar_prov.setFixedWidth(44)
        self.btn_guardar_prov.clicked.connect(self._guardar_cambios)
        self.agregar_capsula(self.btn_guardar_prov)

        self.btn_excel_prov = boton_barra("", 'fa5s.file-excel', 'excel')
        self.btn_excel_prov.setToolTip("Exportar a Excel")
        self.btn_excel_prov.setFixedWidth(44)
        self.btn_excel_prov.setIcon(ThemeManager.icon('fa5s.file-excel', color='#1B2B4E'))
        self.btn_excel_prov.clicked.connect(self._exportar_excel)
        self.agregar_general(self.btn_excel_prov)

        self.btn_copiar_vins_prov = boton_barra("", 'fa5s.copy')
        self.btn_copiar_vins_prov.setIcon(ThemeManager.icon('fa5s.copy', color='#1B2B4E'))
        self.btn_copiar_vins_prov.clicked.connect(self._copiar_vins_filtrados)
        self.agregar_blanco(self.btn_copiar_vins_prov)
        self._actualizar_boton_copiar_vins()

        self.btn_sync_prov = boton_barra("", 'fa5s.plus')
        self.btn_sync_prov.setToolTip("Sincronización de SharePoint (Auto-ETL)")
        self.btn_sync_prov.clicked.connect(self.legacy.open_sync_dialog)
        self.agregar_capsula(self.btn_sync_prov)

        self.btn_ajustes_prov = boton_barra("", 'fa5s.cog')
        self.btn_ajustes_prov.setToolTip("Ajustes de costos")
        self.btn_ajustes_prov.clicked.connect(self.legacy.open_costos_dialog)
        self.agregar_capsula(self.btn_ajustes_prov)

        self.btn_recargar_prov = boton_barra("", 'fa5s.sync-alt')
        self.btn_recargar_prov.setToolTip("Recargar")
        self.btn_recargar_prov.clicked.connect(lambda: self.legacy._trigger_reload(is_manual_reload=True))
        self.agregar_general(self.btn_recargar_prov)

        self.btn_editar_prov = estilo_com.BotonAccionPanel(
            'fa5s.edit', 'Editar provisión',
            "Abre el formulario del registro (Dynafleet, cantidad de meses y plan).", VOLVO_BLUE)
        self.btn_editar_prov.setEnabled(False)
        self.btn_editar_prov.clicked.connect(self._on_editar_clicado)
        self.agregar_accion_panel(self.btn_editar_prov)
        self.btn_editar_prov.hide()
        self._construir_editor_panel()

        self._cache_mapas_prov = (None, {}, {})
        self._cache_modelos = (None, {})
        self._actualizar_estado_guardar()

    # --------------------------------------------- ganchos de la pantalla base
    def resolver_color(self, columna, valor, es_fondo):
        texto = str(valor).strip()
        if columna == COL_PROV_REGISTROS:
            return _CHIP_VOLVO[0 if es_fondo else 1]
        if columna == COL_PROV_COBRO:
            colores = _CHIP_COBRO.get(texto.upper())
            return colores[0 if es_fondo else 1] if colores else None
        if columna in _COLUMNAS_SIGNO_PROV:
            colores = self._colores_variacion(texto)
            return colores[0 if es_fondo else 1] if colores else None
        if columna == COL_PROV_MODELO and texto.endswith(_MARCA_SIN_CIV):
            return _CHIP_SIN_CIV[0 if es_fondo else 1]
        return None

    def colores_chip_ficha(self, columna, valor):
        if columna in _COLUMNAS_SIGNO_PROV:
            return self._colores_variacion(str(valor).strip())
        if columna == COL_PROV_COBRO:
            return _CHIP_COBRO.get(str(valor).strip().upper())
        return None

    @staticmethod
    def _colores_variacion(texto):
        if texto.startswith('-') and texto != '-':
            return _CHIP_VAR_NEGATIVA
        if texto.startswith('$') and texto != '$-':
            return _CHIP_VAR_POSITIVA
        return None

    def on_fila_cambiada(self, fila, cantidad):
        if cantidad == 0:
            self.btn_editar_prov.setEnabled(False)
            self._editor_panel.hide()
            return
        self._pintar_panel(fila, cantidad)
        self.btn_editar_prov.setEnabled(cantidad == 1)
        self._cargar_editor_panel(cantidad == 1)

    # ------------------------------------------- edición directa en el panel
    def _construir_editor_panel(self):
        self._editor_panel = QFrame()
        self._editor_panel.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QVBoxLayout(self._editor_panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._titulo_editor("Editar provisión"))
        self._lbl_unidades_prov = QLabel("")
        self._lbl_unidades_prov.setWordWrap(True)
        self._lbl_unidades_prov.setStyleSheet(
            f"background: transparent; border: none; color: {estilo_com.APAGADO}; font-size: 11px;")
        lay.addWidget(self._lbl_unidades_prov)
        lay.addWidget(self._titulo_editor("Observación", pequeno=True))
        self._lbl_obs_prov = QLabel("-")
        self._lbl_obs_prov.setWordWrap(True)
        self._lbl_obs_prov.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._lbl_obs_prov.setStyleSheet(
            f"background: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA}; border-radius: 10px;"
            f" padding: 6px 10px; color: {estilo_com.TINTA}; font-size: 12px;")
        lay.addWidget(self._lbl_obs_prov)
        estilo_campo = (
            f"QLineEdit, QComboBox {{ background-color: {estilo_com.SUPERFICIE_2}; border: 1px solid {estilo_com.LINEA};"
            f" border-radius: 10px; padding: 4px 10px; min-height: 28px; color: {estilo_com.TINTA}; font-size: 12px; }}"
            f"QLineEdit:focus, QComboBox:focus {{ border: 1px solid {estilo_com.PRIMARIO}; }}")
        self._ed_plan = estilo_com.ComboTarjeta("Plan")
        self._ed_plan.addItems(["—"] + _PLAN_OPCIONES)
        self._ed_meses = QLineEdit()
        self._ed_meses.setPlaceholderText("Varios")
        self._ed_dyna = QLineEdit()
        self._ed_dyna.setReadOnly(True)
        for etiqueta, campo in (("Plan", self._ed_plan), ("Cantidad de meses", self._ed_meses),
                                ("Cobro Dynafleet (solo lectura)", self._ed_dyna)):
            campo.setStyleSheet(estilo_campo)
            lay.addWidget(self._titulo_editor(etiqueta, pequeno=True))
            lay.addWidget(campo)
        self._ed_dyna.setStyleSheet(estilo_campo + f"QLineEdit {{ color: {estilo_com.APAGADO}; }}")
        self._ed_plan.currentIndexChanged.connect(
            lambda i: i > 0 and self._aplicar_desde_panel(COL_PROV_PLAN, self._ed_plan.currentText()))
        for campo, columna in ((self._ed_meses, COL_PROV_MESES),):
            temporizador = QTimer(self)
            temporizador.setSingleShot(True)
            temporizador.setInterval(450)
            temporizador.timeout.connect(lambda c=campo, col=columna: self._aplicar_desde_panel(col, c.text()))
            campo.textEdited.connect(lambda _t, t=temporizador: t.start())
            campo.editingFinished.connect(lambda c=campo, col=columna, t=temporizador: (
                t.stop(), self._aplicar_desde_panel(col, c.text())))
        self.btn_guardar_panel_prov = QPushButton(" Guardar")
        self.btn_guardar_panel_prov.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        self.btn_guardar_panel_prov.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar_panel_prov.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR)
        self.btn_guardar_panel_prov.setEnabled(False)
        self.btn_guardar_panel_prov.clicked.connect(self._guardar_cambios)
        lay.addWidget(self.btn_guardar_panel_prov)
        self._editor_panel.hide()
        self._lay_acciones.insertWidget(0, self._editor_panel)

    @staticmethod
    def _titulo_editor(texto, pequeno=False):
        lbl = QLabel(texto.upper() if not pequeno else texto)
        lbl.setStyleSheet(
            f"background: transparent; border: none; color: {estilo_com.APAGADO}; font-size: {'11' if pequeno else '10'}px;"
            f" font-weight: {'500' if pequeno else '700'};")
        return lbl

    def _fila_seleccionada(self):
        filas = sorted({idx.row() for idx in self.tabla.selectionModel().selectedRows()})
        return filas[0] if len(filas) == 1 else None

    def _vines_de_fila(self, fila):
        df = self.modelo.get_df()
        if fila is None or not (0 <= fila < len(df)):
            return []
        clave = str(df.iat[fila, df.columns.get_loc(COL_PROV_CLAVE)]).strip()
        return [m[0] for m in self._grupos.get(clave, {}).get('miembros', [])]

    def _actualizar_texto_unidades(self, fila, plan):
        df = self.modelo.get_df()
        vines = self._vines_de_fila(fila)
        chasis = [v[-7:] for v in vines[:12]]
        texto = f"Se aplica a {len(vines)} unidad(es): " + ", ".join(chasis) + ("…" if len(vines) > 12 else "")
        clave = str(df.iat[fila, df.columns.get_loc(COL_PROV_CLAVE)]).strip()
        invalidos = _modelos_sin_civ(self._grupos.get(clave, {}).get('modelos', []), plan)
        if invalidos:
            texto += f"\nEl modelo {', '.join(invalidos)} no admite CIV."
        self._lbl_unidades_prov.setText(texto)

    def _copiar_chasis(self):
        vines = self._vines_de_fila(self._fila_seleccionada())
        if vines:
            QApplication.clipboard().setText("\n".join(vines))

    def _cargar_editor_panel(self, visible):
        fila = self._fila_seleccionada()
        df = self.modelo.get_df()
        if not visible or fila is None or not (0 <= fila < len(df)):
            self._editor_panel.hide()
            return
        def valor(col):
            return str(df.iat[fila, df.columns.get_loc(col)]).strip() if col in df.columns else ""
        clave_fila = valor(COL_PROV_CLAVE)
        self._lbl_obs_prov.setText(str(self._fila_por_vin.get(clave_fila, {}).get(COL_PROV_OBS, "-")) or "-")
        self._actualizar_texto_unidades(fila, valor(COL_PROV_PLAN))
        plan = valor(COL_PROV_PLAN)
        pos = next((i for i in range(self._ed_plan.count()) if self._ed_plan.itemText(i).upper() == plan.upper()), -1)
        self._ed_plan.blockSignals(True)
        self._ed_plan.setCurrentIndex(max(pos, 0))
        self._ed_plan.blockSignals(False)
        self._ed_meses.setText("" if valor(COL_PROV_MESES) in ("-", "$-", _VARIOS) else valor(COL_PROV_MESES))
        self._ed_dyna.setText("" if valor(COL_PROV_DYNAFLEET) in ("-", "$-") else valor(COL_PROV_DYNAFLEET))
        self._editor_panel.show()

    def _aplicar_desde_panel(self, columna, texto):
        fila = self._fila_seleccionada()
        df = self.modelo.get_df()
        if fila is None or not (0 <= fila < len(df)):
            return
        actual = str(df.iat[fila, df.columns.get_loc(columna)]).strip()
        if str(texto).strip() == ("" if actual in ("-", "$-") else actual):
            return
        self._registrar_edicion(fila, columna, str(texto))
        registro = dict(self._fila_por_vin.get(str(df.iat[fila, df.columns.get_loc(COL_PROV_CLAVE)]).strip(), {}))
        registro.update({c: df.iat[fila, df.columns.get_loc(c)] for c in df.columns})
        self._pintar_panel(registro, 1)
        self._actualizar_texto_unidades(fila, str(df.iat[fila, df.columns.get_loc(COL_PROV_PLAN)]))

    def al_cambiar_nivel(self):
        self.search_input.clear()
        self._repintar_nivel_prov()

    def _on_filtro_cambiado(self, _i):
        self.filtro_periodo = self.combo_periodo_prov.currentData() or ""
        self.filtro_plan = self.combo_plan_prov.currentData() or ""
        self._refresh_new_ui_data()

    def filter_table(self):
        self._refresh_new_ui_data()

    def refresh_if_dirty(self):
        """Mismo contrato que tenía la pestaña: recarga en cada visita salvo
        que DataManager.df_prov sea el mismo objeto de la última carga. Cada
        vez que se entra a la pantalla el combo de mes vuelve al período más
        reciente."""
        cambio_mes = self._seleccionar_mes_reciente()
        if self.legacy.data_manager.df_prov is getattr(self.legacy, '_df_prov_origen', None):
            if cambio_mes:
                self._refresh_new_ui_data()
            return
        self.legacy.load_data()
        self._refresh_new_ui_data()

    def _seleccionar_mes_reciente(self):
        """Deja el combo en el primer período (el más reciente). Devuelve True
        si cambió la selección."""
        if self.combo_periodo_prov.count() < 2 or self.combo_periodo_prov.currentIndex() == 1:
            return False
        self.combo_periodo_prov.blockSignals(True)
        self.combo_periodo_prov.setCurrentIndex(1)
        self.combo_periodo_prov.blockSignals(False)
        self.filtro_periodo = self.combo_periodo_prov.currentData() or ""
        return True

    def load_data(self):
        self.legacy.load_data()
        self._refresh_new_ui_data()

    def _exportar_excel(self):
        """Exporta los registros del mes seleccionado (uno por unidad, con
        los filtros y cambios pendientes que se ven en pantalla)."""
        df = self._df_filtrado_prov
        if df is None or df.empty:
            QMessageBox.warning(self, "Exportar", "No hay datos visibles.")
            return
        columnas = ['AÑO - MES', 'VIN', 'CLIENTE', 'EJECUTIVO', 'OBSERVACIONES', 'Plan', 'Cantidad de Meses',
                    'DYNAFLEET', 'Valor Plan', 'Monto Provisionado', 'VAR']
        salida = df[[c for c in columnas if c in df.columns]].copy().reset_index(drop=True)
        # El nombre lleva el mes en que se gestiona (hoy), no el de los datos
        hoy = datetime.now()
        nombre_mes = next((m for m, n in provisiones_services.MESES_A_NUM.items() if n == hoy.month), str(hoy.month))
        self.legacy.model.set_data(salida)
        try:
            self.legacy.table.export_to_excel(f"Reporte_Provisiones_{hoy.year}_{nombre_mes}")
        finally:
            self.legacy.filter_table()

    # ------------------------------------------------------------ edición
    def _on_editar_clicado(self):
        claves = self._vins_seleccionados()
        if len(claves) != 1:
            return
        fila = self._fila_por_vin.get(claves[0], {})
        if fila and fila.get('_FILA_FORM'):
            self._abrir_form_provision(fila['_FILA_FORM'], fila.get(COL_RAZON_SOCIAL))

    def _industria_de_razon_social(self, razon_social):
        """Industria de Comercial para la razón social (sin RUT ni CDB, solo
        por nombre normalizado). Si hay varias, la más frecuente; '-' si no
        hay coincidencia."""
        df = self.legacy.data_manager.df_master
        if not isinstance(df, pd.DataFrame) or df.empty or not razon_social \
                or 'RAZÓN SOCIAL' not in df.columns or 'INDUSTRIA' not in df.columns:
            return "-"

        def norm(serie):
            return serie.astype(str).str.upper().str.split().str.join(" ")

        objetivo = " ".join(str(razon_social).upper().split())
        industrias = df.loc[norm(df['RAZÓN SOCIAL']) == objetivo, 'INDUSTRIA'].astype(str).str.strip()
        industrias = industrias[~industrias.isin(['', '-', 'nan', 'None'])]
        return industrias.mode().iloc[0] if not industrias.empty else "-"

    def _abrir_form_provision(self, fila, cliente=None):
        uf, _civ = self.legacy.data_manager.get_variables()
        planes_data = self.legacy.data_manager.get_costos()
        cliente = cliente or self.empresa_actual
        industria = self._industria_de_razon_social(cliente)
        dialog = ProvisionFormDialog(cliente, fila, planes_data, uf, parent=self, industria=industria)
        dialog.guardado.connect(self._aplicar_cambios_formulario)
        dialog.exec()

    def _fila_index_en_legacy_model(self, vin, periodo):
        df = self.legacy.model.get_df()
        if df.empty or 'VIN' not in df.columns:
            return None
        serie_vin = df['VIN'].astype(str).str.strip().str.upper()
        mask = serie_vin == vin.strip().upper()
        if 'AÑO - MES' in df.columns:
            serie_periodo = df['AÑO - MES'].astype(str).str.strip().str.upper()
            mask &= serie_periodo == periodo.strip().upper()
        posiciones = mask.to_numpy().nonzero()[0]
        return int(posiciones[0]) if len(posiciones) else None

    def _aplicar_cambios_formulario(self, vin, periodo, cambios):
        """Aplica los campos del formulario reutilizando on_item_edited (uno
        por columna) + confirm_save() del motor, igual que ContratoFormDialog
        en contratos.py. El registro puede no estar en la vista actual del
        motor si sus propios filtros lo ocultan: en ese caso se amplía el
        modelo momentáneamente a df_base completo y se restaura el filtro al
        terminar."""
        if getattr(self.legacy, '_tabla_pendiente', False):
            self.legacy.filter_table()
        row = self._fila_index_en_legacy_model(vin, periodo)
        restaurar_filtro = False
        if row is None:
            self.legacy.model.set_data(self.legacy.df_base)
            restaurar_filtro = True
            row = self._fila_index_en_legacy_model(vin, periodo)

        if row is None:
            QMessageBox.warning(
                self, "No encontrado",
                "No se pudo ubicar este registro para guardarlo. Recarga Provisiones e intenta de nuevo.",
            )
            if restaurar_filtro:
                self.legacy.filter_table()
            return

        for col_name, new_value in cambios.items():
            self.legacy.on_item_edited(row, col_name, new_value)

        self.legacy.confirm_save()

        if restaurar_filtro:
            self.legacy.filter_table()

    # ------------------------------------------------------------- datos
    def _actualizar_opciones_periodo(self, df_base):
        """Repuebla el combo de mes solo si cambió el conjunto de períodos
        (así no se pierde la selección en cada recálculo)."""
        periodos = provisiones_services.obtener_periodos_disponibles(df_base)
        if periodos == self._periodos_combo_actuales:
            return
        self._periodos_combo_actuales = periodos
        primera_carga = self.combo_periodo_prov.count() < 2
        seleccion_previa = self.combo_periodo_prov.currentData() or ""
        self.combo_periodo_prov.blockSignals(True)
        self.combo_periodo_prov.clear()
        self.combo_periodo_prov.addItem(_TODOS_MESES, "")
        for periodo in periodos:
            self.combo_periodo_prov.addItem(periodo, periodo)
        idx = self.combo_periodo_prov.findData(seleccion_previa)
        if primera_carga and periodos:
            idx = 1
        self.combo_periodo_prov.setCurrentIndex(idx if idx >= 0 else 0)
        self.filtro_periodo = self.combo_periodo_prov.currentData() or ""
        self.combo_periodo_prov.blockSignals(False)

    def _refresh_new_ui_data(self):
        """Recalcula el universo filtrado (búsqueda + cambios pendientes +
        filtros) una sola vez; navegar entre niveles solo repinta."""
        df_base = getattr(self.legacy, 'df_base', pd.DataFrame())
        if df_base is None or df_base.empty:
            self._df_filtrado_prov = pd.DataFrame()
            self._df_clientes = None
            self._actualizar_boton_copiar_vins()
            self._repintar_nivel_prov()
            return

        self._actualizar_opciones_periodo(df_base)
        self._autocompletar_desde_observacion(df_base)
        df = df_base.copy()

        pending = getattr(self.legacy, 'pending_changes', {}) or {}
        if pending and 'VIN' in df.columns and 'AÑO - MES' in df.columns:
            # Una sola pasada: normalizar todas las filas por cada cambio
            # pendiente tardaba segundos con cientos de autocompletados
            cambios_por_col = {}
            for data in pending.values():
                llave = f"{str(data.get('VIN', '')).strip().upper()}|{str(data.get('AÑO - MES', '')).strip().upper()}"
                for col_c, val_c in data.get('cambios', {}).items():
                    if col_c in df.columns:
                        cambios_por_col.setdefault(col_c, {})[llave] = val_c
            if cambios_por_col:
                llaves = (df['VIN'].astype(str).str.strip().str.upper() + '|'
                          + df['AÑO - MES'].astype(str).str.strip().str.upper())
                for col_c, valores in cambios_por_col.items():
                    tiene = llaves.isin(list(valores))
                    if tiene.any():
                        df[col_c] = df[col_c].astype(object)
                        df.loc[tiene, col_c] = llaves[tiene].map(valores).to_numpy()

        texto = self.search_input.text().strip().lower()
        if texto:
            cols = [c for c in ['VIN', 'CLIENTE', 'EJECUTIVO'] if c in df.columns]
            mask = comercial_services.construir_mascara_busqueda(df, texto, cols)
            df = df[mask]

        if 'DYNAFLEET' in df.columns:
            df = df[pd.to_numeric(df['DYNAFLEET'], errors='coerce').fillna(0) > 0]
        if self.filtro_plan and 'Plan' in df.columns:
            df = df[df['Plan'].astype(str).str.strip().str.upper() == self.filtro_plan.upper()]
        if self.filtro_periodo and 'AÑO - MES' in df.columns:
            df = df[df['AÑO - MES'].astype(str).str.strip() == self.filtro_periodo]

        self._df_filtrado_prov = df
        self._df_clientes = None
        self._actualizar_boton_copiar_vins()
        self._repintar_nivel_prov()

    def _vins_filtrados(self):
        """VIN únicos (en orden) del universo filtrado que se ve en pantalla."""
        df = self._df_filtrado_prov
        if df is None or df.empty or 'VIN' not in df.columns:
            return []
        serie = df['VIN'].astype(str).str.strip()
        serie = serie[~serie.str.lower().isin(['', 'nan', 'none', '-'])]
        return serie.drop_duplicates().tolist()

    def _actualizar_boton_copiar_vins(self):
        """Solo se puede copiar con un mes elegido en el filtro."""
        boton = getattr(self, 'btn_copiar_vins_prov', None)
        if boton is None:
            return
        n = len(self._vins_filtrados()) if self.filtro_periodo else 0
        boton.setEnabled(n > 0)
        boton.setToolTip(
            f"Copiar los {n} VIN de {self.filtro_periodo} (con el filtro de plan aplicado) para pegarlos en la búsqueda"
            if n > 0 else "Elige un mes en el filtro para copiar sus VIN")

    def _copiar_vins_filtrados(self):
        vins = self._vins_filtrados()
        if not vins or not self.filtro_periodo:
            return
        QApplication.clipboard().setText(", ".join(vins))
        boton = self.btn_copiar_vins_prov
        boton.setText(" Copiados")
        QTimer.singleShot(2200, lambda: boton.setText(""))
        try:
            from src.ui.main_window import MAX_TERMINOS_BUSQUEDA_GLOBAL as limite
        except Exception:
            limite = 200
        if len(vins) > limite:
            QMessageBox.information(
                self, "Lista larga",
                f"Se copiaron {len(vins)} VIN, pero la barra de búsqueda admite {limite} a la vez al pegar. "
                f"Si pegas la lista completa solo se usarán los primeros {limite}.")

    def _repintar_nivel_prov(self):
        """Una sola tabla con todos los registros filtrados (sin agrupar)."""
        df = self._df_filtrado_prov
        if df is None or df.empty:
            self._fila_por_vin = {}
            self._df_tabla = pd.DataFrame(columns=_COLUMNAS_REGISTROS_PROV)
            self.lbl_subtitulo.setText(self._texto_uf("0 clientes · 0 registros"))
            self.lbl_sin_resultados.setVisible(True)
            self.modelo.celdas_pendientes = self._celdas_pendientes()
            self._pintar_tabla()
            self._actualizar_estado_guardar()
            return

        self._df_tabla = self._armar_tabla_registros(df)
        clientes = df['CLIENTE'].nunique() if 'CLIENTE' in df.columns else 0
        self.lbl_subtitulo.setText(self._texto_uf(f"{clientes} clientes · {len(df)} registros"))
        self.lbl_sin_resultados.setVisible(self._df_tabla.empty)
        self.modelo.celdas_pendientes = self._celdas_pendientes()
        self._pintar_tabla()
        self._ajustar_columnas_prov()
        self._actualizar_estado_guardar()

    def _ajustar_columnas_prov(self):
        """Reparte el ancho de la tabla entre las columnas para que no haya
        scroll horizontal; Cliente ocupa lo que sobra."""
        df = self.modelo.get_df()
        if df.empty:
            return
        total = max(600, self.tabla.viewport().width())
        usado = 0
        for i, col in enumerate(df.columns):
            if col in self.COLUMNAS_OCULTAS or col == COL_PROV_CLIENTE:
                continue
            ancho = int(total * _FRACCION_ANCHO_PROV.get(col, 0.08))
            self.tabla.setColumnWidth(i, ancho)
            usado += ancho
        if COL_PROV_CLIENTE in df.columns:
            self.tabla.setColumnWidth(df.columns.get_loc(COL_PROV_CLIENTE), max(200, total - usado))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'modelo') and self.legacy is not None:
            QTimer.singleShot(0, self._ajustar_columnas_prov)

    # ---------------------------------------- edición en la celda y guardado
    def _celdas_pendientes(self):
        """{(clave VIN|período en mayúsculas, columna de la tabla)} con cambios sin guardar."""
        inverso = {motor: tabla for tabla, motor in _EDITABLE_A_MOTOR.items()}
        celdas = set()
        for datos in (getattr(self.legacy, 'pending_changes', {}) or {}).values():
            registro = f"{str(datos.get('VIN', '')).strip().upper()}|{str(datos.get('AÑO - MES', '')).strip().upper()}"
            clave = self._grupo_de_registro.get(registro, registro).upper()
            for columna_motor in datos.get('cambios', {}):
                if columna_motor in inverso:
                    celdas.add((clave, inverso[columna_motor]))
        return celdas

    def _actualizar_estado_guardar(self):
        n = len(self._celdas_pendientes())
        boton, descartar = getattr(self, 'btn_guardar_prov', None), getattr(self, 'btn_descartar_prov', None)
        if boton is None:
            return
        boton.setEnabled(n > 0)
        descartar.setVisible(n > 0)
        panel = getattr(self, 'btn_guardar_panel_prov', None)
        if panel is not None:
            panel.setEnabled(n > 0)
            panel.setText(f" Guardar ({n})" if n else " Guardar")
        if n > 0:
            boton.setText("")
            boton.setIcon(ThemeManager.icon('fa5s.save', color="#FBBF24"))
            estilo_com.aplicar_estilo_boton_barra(boton, 'naranja')
            boton.setToolTip(f"Guardar: {n} cambio(s) sin guardar")
        else:
            boton.setText("")
            boton.setIcon(ThemeManager.icon('fa5s.save', color=TEXT_SECONDARY))
            estilo_com.aplicar_estilo_boton_barra(boton, 'neutro')
            boton.setToolTip("Guardar: edita Plan o Meses directo en la tabla")

    def _guardar_cambios(self):
        if self.legacy.pending_changes:
            self.legacy.confirm_save()
            self._actualizar_estado_guardar()

    def _descartar_cambios(self):
        self.legacy.pending_changes.clear()
        self._refresh_new_ui_data()

    def _mapa_modelos(self):
        """VIN -> modelo, desde Comercial; si no tiene, se deduce del VIN."""
        df = self.legacy.data_manager.df_master
        clave = (id(df), len(df) if isinstance(df, pd.DataFrame) else 0)
        if self._cache_modelos[0] == clave:
            return self._cache_modelos[1]
        mapa = {}
        if isinstance(df, pd.DataFrame) and not df.empty and 'VIN' in df.columns and COL_PROV_MODELO in df.columns:
            vin = df['VIN'].astype(str).str.strip().str.upper()
            modelo = df[COL_PROV_MODELO].astype(str).str.strip().str.upper()
            validos = ~modelo.isin(['', '-', 'NAN', 'NONE', '<NA>'])
            mapa = dict(zip(vin[validos], modelo[validos]))
        self._cache_modelos = (clave, mapa)
        return mapa

    def _mapas_prov(self):
        """(razón social normalizada -> industria más frecuente, VIN -> observaciones) desde Comercial."""
        df = self.legacy.data_manager.df_master
        clave = (id(df), len(df) if isinstance(df, pd.DataFrame) else 0)
        if self._cache_mapas_prov[0] == clave:
            return self._cache_mapas_prov[1], self._cache_mapas_prov[2]
        industrias, observaciones = {}, {}
        if isinstance(df, pd.DataFrame) and not df.empty:
            def norm(serie):
                return serie.astype(str).str.upper().str.split().str.join(" ")
            vacios = ['', '-', 'nan', 'None', '<NA>']
            if 'RAZÓN SOCIAL' in df.columns and 'INDUSTRIA' in df.columns:
                aux = pd.DataFrame({'r': norm(df['RAZÓN SOCIAL']), 'i': df['INDUSTRIA'].astype(str).str.strip()})
                aux = aux[~aux['i'].isin(vacios)]
                industrias = aux.groupby('r')['i'].agg(lambda s: s.mode().iloc[0]).to_dict()
        self._cache_mapas_prov = (clave, industrias, observaciones)
        return industrias, observaciones

    def _registrar_edicion(self, fila, columna, valor):
        """Una celda editada: valida, deja el cambio pendiente (mismo formato
        que el motor de guardado), recalcula montos y actualiza la fila sin
        repintar toda la tabla."""
        df_tabla = self.modelo.get_df()
        if not (0 <= fila < len(df_tabla)) or COL_PROV_CLAVE not in df_tabla.columns:
            return
        clave = str(df_tabla.iat[fila, df_tabla.columns.get_loc(COL_PROV_CLAVE)])
        grupo = self._grupos.get(clave)
        if not grupo:
            return
        motor = _EDITABLE_A_MOTOR[columna]
        if columna == COL_PROV_MESES:
            resultado, dato = provisiones_services.validar_cantidad_meses(valor)
            if resultado == "invalido":
                QMessageBox.warning(self, "Error", dato)
                return
            nuevo = dato
        else:
            nuevo = str(valor).strip()

        df = self._df_filtrado_prov
        serie_vin = df['VIN'].astype(str).str.strip().str.upper()
        serie_per = df['AÑO - MES'].astype(str).str.strip().str.upper()
        primero = None
        for vin, periodo in grupo['miembros']:
            mascara = (serie_vin == vin.strip().upper()) & (serie_per == periodo.strip().upper())
            if not mascara.any():
                continue
            resumen = self._aplicar_cambio_unidad(df, mascara, vin, periodo, {motor: nuevo})
            primero = primero or resumen
        if primero is None:
            return

        fmt = provisiones_services.formatear_moneda
        visibles = {
            COL_PROV_PLAN: primero['plan'],
            COL_PROV_MESES: primero['cambios'].get('Cantidad de Meses', None),
            COL_PROV_VALOR_PLAN: fmt(primero['valor_plan']), COL_PROV_MONTO: fmt(primero['monto']),
            COL_PROV_VARIACION: fmt(primero['variacion']),
        }
        if COL_PROV_MODELO in df_tabla.columns:
            visibles[COL_PROV_MODELO] = _texto_modelo(grupo.get('modelos', []), primero['plan'])
        for col_tabla, texto in visibles.items():
            if texto is not None and col_tabla in df_tabla.columns:
                df_tabla.iat[fila, df_tabla.columns.get_loc(col_tabla)] = _texto_celda(texto)
        self.modelo.celdas_pendientes = self._celdas_pendientes()
        self.modelo.dataChanged.emit(
            self.modelo.index(fila, 0), self.modelo.index(fila, len(df_tabla.columns) - 1))
        self._actualizar_estado_guardar()

    def _calcular_cambios_unidad(self, actual, cambios):
        """Agrega Monto, Valor plan y Variación a `cambios` para un registro,
        con lo ya guardado en `actual` para lo que no cambia."""
        def numero(valor_celda, defecto):
            try:
                return float(str(valor_celda).replace('$', '').replace('.', '').replace(',', '').strip())
            except ValueError:
                return defecto

        dyna = cambios['DYNAFLEET'] if 'DYNAFLEET' in cambios else pd.to_numeric(actual.get('DYNAFLEET'), errors='coerce')
        dyna = 0.0 if pd.isna(dyna) else float(dyna)
        meses_txt = cambios.get('Cantidad de Meses', actual.get('Cantidad de Meses', ''))
        meses = numero(meses_txt, 1.0) if str(meses_txt).strip() not in ('', '-', 'MENSUAL', 'nan') else 1.0
        plan = cambios.get('Plan', str(actual.get('Plan', '')).strip())
        uf, _civ = self.legacy.data_manager.get_variables()
        monto, valor_plan, variacion = provisiones_services.calcular_montos_provision(
            dyna, meses, plan, self.legacy.data_manager.get_costos(), uf)
        completos = dict(cambios)
        completos.update({'Monto Provisionado': monto, 'Valor Plan': valor_plan, 'VAR': variacion})
        return completos, {'plan': plan, 'dyna': dyna, 'monto': monto, 'valor_plan': valor_plan,
                           'variacion': variacion, 'cambios': completos}

    def _aplicar_cambio_unidad(self, df, mascara, vin, periodo, cambios):
        """Deja pendiente el cambio de un registro (formato del motor de
        guardado) y lo refleja en el DataFrame filtrado."""
        completos, resumen = self._calcular_cambios_unidad(df[mascara].iloc[0], cambios)
        llave = f"{vin.strip().upper()}_{periodo.strip().upper()}"
        pendiente = self.legacy.pending_changes.setdefault(
            llave, {'VIN': vin.strip().upper(), 'AÑO - MES': periodo.strip().upper(), 'cambios': {}})
        pendiente['cambios'].update(completos)
        for col_motor, val in completos.items():
            if col_motor in df.columns:
                if df[col_motor].dtype != object:
                    df[col_motor] = df[col_motor].astype(object)
                df.loc[mascara, col_motor] = val
        return resumen

    def _autocompletar_desde_observacion(self, df):
        """Completa Plan y Meses vacíos con lo que dice la observación del
        propio registro. Quedan como cambios pendientes (en ámbar) para que
        la persona los revise o corrija antes de guardar; cada registro se
        intenta una sola vez."""
        if df is None or df.empty or 'OBSERVACIONES' not in df.columns or 'DYNAFLEET' not in df.columns:
            return
        vacios = ('', '-', '0', 'NAN', 'NONE')
        candidatos = df[(pd.to_numeric(df['DYNAFLEET'], errors='coerce').fillna(0) > 0)
                        & ~df['OBSERVACIONES'].astype(str).str.strip().str.upper().isin(vacios)]
        # Los ya intentados se descartan antes de recorrer fila por fila
        def normalizar(col):
            if col not in candidatos.columns:
                return [""] * len(candidatos)
            return [str(v).strip().upper() for v in candidatos[col]]
        vins, periodos = normalizar('VIN'), normalizar('AÑO - MES')
        nuevos = [f"{v}_{p}" not in self._autocompletados for v, p in zip(vins, periodos)]
        if not any(nuevos):
            return
        for (_i, fila), vin, periodo in zip(candidatos[nuevos].iterrows(),
                                            (v for v, n in zip(vins, nuevos) if n),
                                            (p for p, n in zip(periodos, nuevos) if n)):
            llave = f"{vin}_{periodo}"
            if llave in self._autocompletados:
                continue
            self._autocompletados.add(llave)
            plan_obs, meses_obs = provisiones_services.interpretar_observacion(fila.get('OBSERVACIONES'))
            plan_actual = str(fila.get('Plan', '')).strip().upper()
            meses_actual = pd.to_numeric(fila.get('Cantidad de Meses'), errors='coerce')
            sin_plan = plan_actual in vacios
            sin_meses = pd.isna(meses_actual) or meses_actual <= 0 or (meses_actual == 1 and sin_plan)
            cambios = {}
            if plan_obs and sin_plan:
                cambios['Plan'] = plan_obs
            if meses_obs and sin_meses:
                cambios['Cantidad de Meses'] = meses_obs
            if not cambios:
                continue
            completos, _resumen = self._calcular_cambios_unidad(fila, cambios)
            pendiente = self.legacy.pending_changes.setdefault(
                llave, {'VIN': vin, 'AÑO - MES': periodo, 'cambios': {}})
            for columna, valor in completos.items():
                pendiente['cambios'].setdefault(columna, valor)

    def _texto_uf(self, texto):
        mes = self.combo_periodo_prov.currentText() if self.combo_periodo_prov.currentData() else ""
        try:
            uf, _civ = self.legacy.data_manager.get_variables()
            texto = f"{texto} · UF ${uf:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            pass
        return f"{texto} · {mes}" if mes else texto

    def _armar_tabla_clientes(self, df_clientes):
        self._fila_por_vin = {}
        if df_clientes.empty:
            return pd.DataFrame(columns=_COLUMNAS_CLIENTES_PROV)
        ejecutivos = df_clientes['EJECUTIVO'].tolist() if 'EJECUTIVO' in df_clientes.columns else [""] * len(df_clientes)
        return pd.DataFrame({
            COL_PROV_CLIENTE: [_texto_celda(c) if c not in (None, "") else "Sin cliente" for c in df_clientes['CLIENTE']],
            COL_PROV_EJECUTIVO: [_texto_celda(e) for e in ejecutivos],
            COL_PROV_REGISTROS: df_clientes['REGISTROS'].astype(int).astype(str).tolist(),
        }, columns=_COLUMNAS_CLIENTES_PROV)

    def _columnas_tabla_prov(self):
        columnas = list(_COLUMNAS_REGISTROS_PROV)
        if not self.filtro_periodo:
            columnas.insert(columnas.index(COL_PROV_CLIENTE) + 1, COL_PROV_PERIODO)
        return columnas

    def _armar_tabla_registros(self, df_cliente):
        """Una fila por empresa + período + Dynafleet: las unidades con el
        mismo cobro comparten plan, así que se editan juntas. Si una empresa
        tiene más de un Dynafleet, los grupos menores quedan marcados como
        excepción."""
        self._fila_por_vin = {}
        self._grupos = {}
        self._grupo_de_registro = {}
        columnas = self._columnas_tabla_prov()
        if df_cliente.empty:
            return pd.DataFrame(columns=columnas)

        def texto(col):
            if col in df_cliente.columns:
                return df_cliente[col].map(_texto_celda)
            return pd.Series("-", index=df_cliente.index)

        fmt = provisiones_services.formatear_moneda

        def moneda(col):
            if col in df_cliente.columns:
                return pd.to_numeric(df_cliente[col], errors='coerce').fillna(0).map(fmt)
            return pd.Series("$-", index=df_cliente.index)

        cliente = texto('CLIENTE').replace('-', 'Sin cliente')
        aux = pd.DataFrame({
            'cli': cliente, 'norm': cliente.str.upper().str.split().str.join(" "),
            'per': texto('AÑO - MES'), 'vin': texto('VIN'),
            'dyna': pd.to_numeric(df_cliente.get('DYNAFLEET'), errors='coerce').fillna(0).round(0),
            'plan': texto('Plan'), 'meses': texto('Cantidad de Meses'), 'obs': texto('OBSERVACIONES'),
            'vp': moneda('Valor Plan'), 'monto': moneda('Monto Provisionado'), 'var': moneda('VAR'),
            'dyna_txt': moneda('DYNAFLEET'),
        })
        industrias, _ = self._mapas_prov()
        modelo_de_vin = self._mapa_modelos()
        # Grupos armados en una pasada sobre listas: con pandas por grupo
        # tardaba ~4 ms por empresa
        col = {k: aux[k].tolist() for k in aux.columns}
        posiciones_grupo = {}
        for i, llave in enumerate(zip(col['norm'], col['per'], col['dyna'])):
            posiciones_grupo.setdefault(llave, []).append(i)

        def valor_grupo(nombre, posiciones):
            distintos = dict.fromkeys(col[nombre][p] for p in posiciones)
            return next(iter(distintos)) if len(distintos) == 1 else _VARIOS

        def moda(valores):
            conteo = Counter(valores)
            maximo = max(conteo.values())
            return min(v for v, n in conteo.items() if n == maximo)

        filas = []
        for (norm, per, dyna), posiciones in posiciones_grupo.items():
            primera = posiciones[0]
            clave = f"G|{norm}|{per}|{int(dyna)}"
            miembros = [(col['vin'][p], col['per'][p]) for p in posiciones]
            modelos = sorted({
                modelo_de_vin.get(v.strip().upper()) or obtener_modelo_desde_vin(v) or "-" for v, _ in miembros} - {"-"})
            self._grupos[clave] = {'miembros': miembros, 'modelos': modelos}
            for vin, periodo in miembros:
                self._grupo_de_registro[f"{vin.strip().upper()}|{periodo.strip().upper()}"] = clave
            observaciones = [col['obs'][p] for p in posiciones if col['obs'][p] != '-']
            filas.append({
                COL_PROV_CLAVE: clave, COL_VIN: "\n".join(v for v, _ in miembros), COL_PROV_CLIENTE: col['cli'][primera], '_NORM': norm, '_N': len(posiciones),
                COL_PROV_PERIODO: per, COL_UNIDADES: str(len(posiciones)),
                COL_PROV_INDUSTRIA: industrias.get(norm, "NO DEFINIDO"),
                COL_PROV_MODELO: _texto_modelo(modelos, " ".join(dict.fromkeys(col['plan'][p] for p in posiciones))),
                COL_PROV_PLAN: valor_grupo('plan', posiciones), COL_PROV_MESES: valor_grupo('meses', posiciones),
                COL_PROV_DYNAFLEET: col['dyna_txt'][primera], COL_PROV_VALOR_PLAN: valor_grupo('vp', posiciones),
                COL_PROV_MONTO: valor_grupo('monto', posiciones), COL_PROV_VARIACION: valor_grupo('var', posiciones),
                COL_PROV_OBS: moda(observaciones) if observaciones else "-",
                '_VINES': [m[0] for m in miembros],
            })
        por_cliente_periodo = {}
        for i, fila in enumerate(filas):
            por_cliente_periodo.setdefault((fila['_NORM'], fila[COL_PROV_PERIODO]), []).append(i)
        for indices in por_cliente_periodo.values():
            if len(indices) > 1:
                principal = max(indices, key=lambda i: filas[i]['_N'])
                for i in indices:
                    if i != principal:
                        filas[i][COL_PROV_CLIENTE] = f"{filas[i][COL_PROV_CLIENTE]} · otro Dynafleet"
        df = pd.DataFrame(filas)
        df = df.sort_values(['_NORM', COL_PROV_PERIODO, '_N'], ascending=[True, False, False],
                            kind="stable").reset_index(drop=True)
        for registro in df.to_dict('records'):
            registro[COL_RAZON_SOCIAL] = registro[COL_PROV_CLIENTE]
            vines = registro['_VINES']
            registro[COL_VIN] = vines[0] if len(vines) == 1 else f"{len(vines)} unidades"
            self._fila_por_vin[registro[COL_PROV_CLAVE]] = registro
        return df[columnas]

    # --------------------------------------------- reenvío al motor oculto
    def __getattr__(self, name):
        legacy = self.__dict__.get('legacy')
        if legacy is not None and hasattr(legacy, name):
            return getattr(legacy, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __setattr__(self, name, value):
        if name in ProvisionesModule._ATTRS_LEGACY and 'legacy' in self.__dict__:
            setattr(self.legacy, name, value)
        else:
            super().__setattr__(name, value)
