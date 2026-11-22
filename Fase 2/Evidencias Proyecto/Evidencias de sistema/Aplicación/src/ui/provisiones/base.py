"""Constantes, modelos de tabla, hilo de guardado y ayudas de la pantalla Provisiones."""
from src.core.constants import COL_ESTADO_ACTIVACION, COL_ESTADO_COMERCIAL, COL_ETAPA_GESTION, COL_TIPO_FACTURACION, COL_VIN
from src.theme.colors import DANGER, MODULE_COLORS, PRIMARY, SUCCESS, VOLVO_BLUE, WARNING
import pandas as pd
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from src.ui.compartido.custom_table import PandasTableModel
from src.ui.ingresos.base import ModeloTablaIngresos
from src.core.dataframe_formatter import DataFrameFormatter
from src.services import provisiones_services
from src.services import comercial_services
from src.services.vin_service import obtener_modelo_desde_vin
import config.settings
from src.theme import tema
import logging


logger = logging.getLogger(__name__)


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
                vin_val = str(self._valor_celda(index.row(), df_view.columns.get_loc('VIN'))).strip().upper()
                fecha_val = str(self._valor_celda(index.row(), df_view.columns.get_loc('AÑO - MES'))).strip().upper()
                unique_key = f"{vin_val}_{fecha_val}"
                
                if unique_key in self.parent_module.pending_changes and col_name in self.parent_module.pending_changes[unique_key]['cambios']:
                    is_pending = True

        if role == Qt.ItemDataRole.ForegroundRole:
            if is_pending: return tema.texto(WARNING) # Texto naranja para celda editada
            
            if col_name == 'VAR':
                val_str = str(self._valor_celda(index.row(), index.column()))
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

    def _dato_en_prov(self, vin, fecha, columna):
        """Valor ya guardado en la fila de Provisiones (vacío si no hay)."""
        df = getattr(self.data_manager, 'df_prov', None)
        if not isinstance(df, pd.DataFrame) or df.empty or columna not in df.columns:
            return ''
        mask = (df['VIN'].astype(str).str.strip().str.upper() == vin) & (df['AÑO - MES'].astype(str).str.strip() == fecha)
        return str(df.loc[mask, columna].iloc[0]).strip() if mask.any() else ''

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
                            except Exception: pass

                if destino['estado'] == 'ok':
                    cross_updates[target_vin] = {'VIN': target_vin, 'ID': destino['id'], 'cambios': cambios_com}
                elif destino['estado'] == 'sin_contrato':
                    # Unidad pendiente: se guarda su provisión en el Registro Maestro con la forma de contrato y la facturación
                    # elegidas (o las sugeridas por la observación), pero sigue Sin Servicio hasta que se envíe a Operaciones
                    observacion = self._dato_en_prov(target_vin, target_fecha, 'OBSERVACIONES')
                    elegido = data.get('rm') or {}
                    if elegido.get('forma'):
                        forma, facturacion = elegido['forma'], elegido.get('facturacion')
                    else:
                        forma, facturacion = provisiones_services.forma_sugerida(observacion)
                        if provisiones_services.es_observacion_solo_cm(observacion):
                            continue
                    plan = cambios.get('Plan') or self._dato_en_prov(target_vin, target_fecha, 'Plan')
                    meses = cambios.get('Cantidad de Meses') or self._dato_en_prov(target_vin, target_fecha, 'Cantidad de Meses')
                    meses = str(meses).strip()
                    try:
                        meses = str(int(float(meses)))
                    except ValueError:
                        pass
                    cambios_rm = provisiones_services.cambios_guardar_provision(plan, meses, forma, facturacion)
                    if cambios_rm:
                        cross_updates[target_vin] = {'VIN': target_vin, 'ID': destino['id'], 'cambios': cambios_rm}
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


COL_PROV_ACTIVIDAD = "ACTIVIDAD"


_COLUMNAS_CLIENTES_PROV = [COL_PROV_CLIENTE, COL_PROV_EJECUTIVO, COL_PROV_REGISTROS]


# Una sola tabla con todos los registros (sin agrupar por cliente)
_COLUMNAS_REGISTROS_PROV = [COL_PROV_CLAVE, COL_VIN, COL_PROV_CLIENTE, COL_UNIDADES, COL_PROV_ACTIVIDAD, COL_PROV_INDUSTRIA, COL_PROV_MODELO, COL_PROV_PLAN,
                            COL_PROV_MESES, COL_PROV_DYNAFLEET, COL_PROV_VALOR_PLAN, COL_PROV_MONTO,
                            COL_PROV_VARIACION]


# Fracción del ancho de la tabla de cada columna (sin scroll horizontal; la última ocupa el resto)
_FRACCION_ANCHO_PROV = {
    COL_PROV_CLIENTE: 0.21, COL_PROV_PERIODO: 0.09, COL_UNIDADES: 0.09, COL_PROV_ACTIVIDAD: 0.10, COL_PROV_INDUSTRIA: 0.10, COL_PROV_PLAN: 0.09, COL_PROV_MESES: 0.06,
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
