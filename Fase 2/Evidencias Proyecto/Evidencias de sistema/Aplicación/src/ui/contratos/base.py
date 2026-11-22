"""Hilos, constantes de columnas, chips y ayudas de la pantalla Contratos (CM)."""
from src.theme.colors import DANGER, MODULE_COLORS, PRIMARY, TEXT_SECONDARY, VOLVO_BLUE, WARNING
import logging
from PyQt6.QtWidgets import QTableWidgetItem, QAbstractButton
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from src.services import contratos_service as ct_service
from src.core.constants import COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM, COL_RUT, COL_RAZON_SOCIAL, COL_CDB_FLOTA


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
    "PENDIENTE": ("#FEF3C7", "#92400E"),
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


class AnalisisImportacionThread(QThread):
    """Lee y compara el 3PC fuera del hilo principal para que la animación de carga se mueva."""
    terminado = pyqtSignal(object, str)

    def __init__(self, funcion, *args):
        super().__init__()
        self.funcion = funcion
        self.args = args

    def run(self):
        try:
            self.terminado.emit(self.funcion(*self.args), "")
        except Exception as e:
            logger.exception("Falló el análisis del Excel 3PC")
            self.terminado.emit(None, str(e))


# =========================================================
# RESUMEN DE IMPORTACIÓN (reemplaza al QMessageBox.question genérico)
# =========================================================
_TONOS_IMPORTACION = {
    'azul': ("#EAF1FF", "#1D4ED8"), 'ambar': ("#FEF3DC", "#B45309"), 'verde': ("#E3F7EF", "#047857"),
    'rojo': ("#FDE8E8", "#B91C1C"), 'gris': ("#F1F5F9", "#475569"),
}


_COLOR_ACTIVACION = {"CONECTADO": "#047857", "DESCONECTADO": "#B91C1C", "ACTIVANDO": "#B45309"}


_AVISOS_UNIDAD = {
    'forma': ("Cambia de forma", 'azul'),
    'expired': ("Pasa a Expired", 'ambar'),
    'nuevo': ("Contrato nuevo · Operaciones", 'azul'),
    'otra_forma': ("Su forma no es CM", 'gris'),
}


_FILTROS_UNIDAD = (
    ('todas', "Todas"), ('forma', "Cambian de forma"), ('expired', "Pasan a Expired"),
    ('nuevo', "Contrato nuevo"), ('otra_forma', "Su forma no es CM"),
)


_COLUMNAS_UNIDAD = ("APLICAR", "UNIDAD", "ACTIVACIÓN EN EL RM", "FORMA Y FACTURACIÓN", "ESTADO DEL CM", "PAGO CM", "AVISO")


def _dato_o_sin_dato(valor):
    return "Sin dato" if str(valor).strip().lower() in ("", "-", "nan", "none") else str(valor).strip()


def _pago_importacion(valor):
    try:
        return _formato_pago(float(valor))
    except (TypeError, ValueError):
        return "Sin dato"


def _numero_pago(valor):
    try:
        return float(valor)
    except (TypeError, ValueError):
        return float("-inf")


class _ItemOrden(QTableWidgetItem):
    """Celda que ordena por una clave propia (por ejemplo el pago como número y no como texto)."""

    def __init__(self, texto, clave):
        super().__init__(texto)
        self._clave = clave

    def __lt__(self, otro):
        return self._clave < getattr(otro, '_clave', otro.text().lower())


class _Interruptor(QAbstractButton):
    """Interruptor encendido/apagado (el checkbox de siempre, con otra cara)."""

    def __init__(self, marcado=True, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(marcado)
        self.setFixedSize(44, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(PRIMARY if self.isChecked() else "#94A3B8"))
        p.drawRoundedRect(self.rect(), 13, 13)
        p.setBrush(QColor("white"))
        p.drawEllipse(21 if self.isChecked() else 3, 3, 20, 20)
        p.end()


# =========================================================
# CLASE PRINCIPAL DEL MÓDULO CONTRATOS
# =========================================================
COL_CONTRATOS_TABLA = "CONTRATOS"


COL_VIGENTES_TABLA = "VIGENTES"


COL_DESCONECTADOS_TABLA = "DESCONECTADOS"


COL_ACTIVANDO_TABLA = "ACTIVANDO"


COL_AL_DIA_TABLA = "AL DÍA"


COL_POR_ACTUALIZAR_TABLA = "POR ACTUALIZAR"


COL_SIN_PAGO_TABLA = "SIN PAGO"


COL_CDB_VARIOS = "CDB_VARIOS"


COL_FLOTA_VC_TABLA = "FLOTA VC"


_ETIQUETA_SITUACION_PAGO = {ct_service.SITUACION_AL_DIA: "Al día", ct_service.SITUACION_POR_ACTUALIZAR: "Por actualizar",
                            ct_service.SITUACION_SIN_PAGO: "Sin pago"}


class _FilasPorVin(dict):
    """Busca la fila de un VIN al pedirla, sin convertir toda la base a diccionarios."""

    def __init__(self, df=None):
        super().__init__()
        self._df = df

    def get(self, vin, defecto=None):
        if self._df is None or vin not in self._df.index:
            return defecto
        return self._df.loc[vin].to_dict()

    def __bool__(self):
        return self._df is not None and not self._df.empty


_COLUMNAS_EMPRESAS_CM = [COL_FLOTA_VC_TABLA, COL_RAZON_SOCIAL, COL_RUT, COL_CDB_FLOTA, COL_CONTRATOS_TABLA, COL_AL_DIA_TABLA,
                         COL_POR_ACTUALIZAR_TABLA, COL_SIN_PAGO_TABLA, COL_CDB_VARIOS]


COL_EJECUTIVO_TABLA = "EJECUTIVO"


COL_FORMA_ACTUAL_TABLA = "FORMA ACTUAL"


COL_TIPO_CM_TABLA = "TIPO DE CM"


COL_ESTADO_ACTUAL_TABLA = "ESTADO ACTUAL"


COL_ULTIMO_PAGO_TABLA = "ÚLTIMO PAGO"


_COLUMNAS_FLOTAS_CM = [COL_FLOTA_VC_TABLA, COL_RAZON_SOCIAL, COL_CDB_FLOTA, COL_CONTRATOS_TABLA, COL_CDB_VARIOS]


COL_FACTURACION_ACTUAL_TABLA = "FACTURACIÓN ACTUAL"


_EXTRAS_COLA_CM = {
    "otra_forma": (COL_FORMA_ACTUAL_TABLA, COL_TIPO_CM_TABLA),
    "forma_incorrecta": (COL_FORMA_ACTUAL_TABLA, COL_FACTURACION_ACTUAL_TABLA, COL_TIPO_CM_TABLA),
    "por_actualizar": (COL_ESTADO_ACTUAL_TABLA, COL_ULTIMO_PAGO_TABLA),
    "ausentes": (COL_TIPO_CM_TABLA, COL_ULTIMO_PAGO_TABLA),
    "baja": (COL_TIPO_CM_TABLA, COL_ESTADO_ACTUAL_TABLA, COL_ULTIMO_PAGO_TABLA),
}


_COLAS_CM = ("otra_forma", "ausentes", "por_actualizar", "forma_incorrecta", "baja")


COL_ACTIVACION_TABLA = "ACTIVACIÓN"


_COLUMNAS_DETALLE_CM = [
    'ID', COL_ACTIVACION_TABLA, 'ESTADO COMERCIAL', 'VIN', 'CHASIS', 'N CONTRATO 3PC', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'TIPO DE CM', 'ESTADO DEL CM', 'PAGO CM',
    COL_ULTIMO_PAGO_CM, COL_FECHA_ULTIMO_PAGO_CM,
]


_CHIP_VOLVO = ("#E1EAF4", VOLVO_BLUE)


_CHIP_VIGENTES = ("#E3F6EE", "#0F9D6E")


_CHIP_DESCONECTADOS = ("#FDE5E5", "#E04848")


_CHIP_CDB_VARIOS = ("#FEF3C7", "#92400E")


_CHIP_ACTIVANDO = ("#FFF1D6", "#B45309")


_CHIPS_ACTIVACION = {"CONECTADO": _CHIP_VIGENTES, "DESCONECTADO": _CHIP_DESCONECTADOS, "ACTIVANDO": _CHIP_ACTIVANDO}


_CHIPS_CONTEO_EMPRESAS = {COL_AL_DIA_TABLA: _CHIP_VIGENTES, COL_POR_ACTUALIZAR_TABLA: _CHIP_ACTIVANDO,
                         COL_SIN_PAGO_TABLA: _CHIP_DESCONECTADOS}


# (título, clave, color, descripción)
_KPI_SPECS_CM = [
    ("Total Conectados", "total", "#0F766E",
     "Contratos CM con la unidad Conectada o Activando. Es el 100 %: las cuatro tarjetas siguientes lo reparten "
     "sin repetir unidades."),
    ("Pendientes activación", "pendiente", WARNING, "Contratos CM pagados que siguen en Activación Pendiente."),
    ("Baja de CM", "baja", DANGER,
     "CM Expired o sin pago este mes, ausentes de la última carga del 3PC o con datos 3PC vacíos: los mismos casos "
     "que Comercial > Oportunidades CM."),
    ("Unidades al día", "al_dia", "#1E7E43", "CM Running pagado este mes, con forma de contrato y facturación CM."),
    ("CM Pagado, forma de contrato distinta", "forma_incorrecta", "#6D28D9",
     "CM Running pagado este mes, pero con forma de contrato o facturación que no son de CM (Provisión, "
     "Provisión +, Conversión...). Hay que revisar si corresponde pasarlos a CM."),
    ("Pago CM total", "pago", "#B45309", "Suma de PAGO CM de los contratos mostrados."),
]
