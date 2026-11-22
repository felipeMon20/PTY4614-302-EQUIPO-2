"""Constantes, ayudas y widgets pequeños del formulario de unidad (`comercial_agregar.py`)."""
import hashlib
import os
import re
import sys
from collections import Counter
from datetime import datetime
import pandas as pd
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QLineEdit, QComboBox, QPushButton, QMessageBox,
                             QFrame, QCompleter, QApplication, QSpinBox, QWidget, QTabWidget, QSizePolicy,
                             QScrollArea, QListView, QProgressBar, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, QRegularExpression, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QRegularExpressionValidator, QFont, QCursor
from src.ui.compartido.comercial_estilo import ComboTarjeta
from src.ui.compartido.guardado_overlay import crear_tarjeta_carga
import qtawesome as qta

from src.services.vin_service import obtener_modelo_desde_vin
from src.services import catalogos_service, comercial_services, ejecutivos_service
from src.theme.theme_manager import ThemeManager
from src.theme.colors import DANGER, SUCCESS, BORDER, TEXT_SECONDARY, BACKGROUND, SURFACE, PRIMARY, SECONDARY
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.normalizacion import normalizar_periodo_interno
from src.core.constants import (
    COL_ESTADO_COMERCIAL, COL_TIPO_FACTURACION, COL_ETAPA_GESTION, COL_ESTADO_ACTIVACION, ETAPA_GESTION_COLORES,
    TIPO_FACTURACION_DISPLAY_MAP, TIPO_FACTURACION_DISPLAY_A_REAL,
    TIPO_FACTURACION_HABILITA_JUSTTIME, TIPO_FACTURACION_HABILITA_CM,
    TIPO_CM_OPCIONES, ESTADO_CM_OPCIONES, FORMA_CONTRATO_TIPO_CM_MAP, JUSTTIME_ESTADO_OPCIONES, JUSTTIME_ESTADO_PENDIENTE, JUSTTIME_ESTADO_NO_APLICA,
    JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_ELIMINAR, JUSTTIME_ESTADO_REVISAR_PAGO,
    FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ,
    VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_INTERNO, VALOR_TIPO_FACT_PROVISION_MAS,
    VALOR_TIPO_FACT_CM, VALOR_TIPO_FACT_FACTURACION_MANUAL, VALOR_TIPO_FACT_SIN_REGISTRO,
)

class _FiltroHabilitado(QObject):
    """Copia el estado habilitado/deshabilitado de un widget a otros (los
    checks CIV/SZ siguen al combo de TIPO DE SERVICIO)."""

    def __init__(self, origen, destinos):
        super().__init__(origen)
        self._destinos = destinos
        origen.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.EnabledChange:
            for destino in self._destinos:
                destino.setEnabled(obj.isEnabled())
        return False


def _partir_tipo_servicio(valor):
    """'Medio + CIV + SZ' -> ('Medio', ['CIV', 'SZ']). Si trae algo que no es un
    complemento del catálogo, el valor completo queda como plan base (valor legado)."""
    return catalogos_service.partir_tipo_servicio(valor)


# Orden de presentación del combo TIPO DE FACTURACION en la pestaña "JustTime
# & CM" (definido con Javiera, 16-09-2026): usa los valores reales ya
# centralizados en constants.py, no valores inventados.
_ORDEN_TIPO_FACTURACION = (
    VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_INTERNO, VALOR_TIPO_FACT_PROVISION_MAS,
    VALOR_TIPO_FACT_CM, VALOR_TIPO_FACT_FACTURACION_MANUAL, VALOR_TIPO_FACT_SIN_REGISTRO, '-',
)
# Mismo catálogo sin "-" (25-09-2026, a pedido explícito: "eliminar la
# opción para escoger '-'" en TIPO DE FACTURACION/"Tipo de factura"). "-"
# sigue siendo un valor real que datos legados o el default sin FORMA DE
# CONTRATO reconocida pueden tener -- se sigue mostrando cuando corresponde
# (ver _set_combo_valor_precargado), solo deja de listarse como opción de
# catálogo elegible a mano.
_ORDEN_TIPO_FACTURACION_SIN_GUION = tuple(v for v in _ORDEN_TIPO_FACTURACION if v != '-')

# Icono de flecha para los combo box de este formulario (25-09-2026, a pedido
# explícito: "la flechita... se ve muy fea, busca una bonita para que
# combinen") -- la flecha nativa de Qt no combina con el borde redondeado de
# QComboBox[class="combo_box"]. Mismo patrón que get_resource_path en
# main_window.py/mail_dialog.py, para que también funcione empaquetado con
# PyInstaller.
def _resource_path(relative_path):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base_path, relative_path)


_COMBO_CHEVRON_PATH = _resource_path(os.path.join('src', 'assets', 'combo_chevron.png')).replace('\\', '/')

# Agrupación de campos para el resumen de confirmación (_confirmar_resumen,
# 16-09-2026): mismos 4 bloques que las pestañas del formulario, para que el
# resumen se sienta como una versión compacta del mismo formulario en vez de
# una lista plana sin relación visual con él.
_RESUMEN_GRUPOS = [
    ("Cliente", ['RUT', 'RAZÓN SOCIAL', 'CDB', 'CDB FLOTA', 'INDUSTRIA', 'VIN', 'CHASIS', 'MODELO']),
    ("Comercial", ['EJECUTIVO', 'FORMA DE CONTRATO', 'TIPO DE SERVICIO', 'ESTADO COMERCIAL',
                   'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO']),
    ("Operaciones", ['FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ACTIVACIÓN ACTUAL', 'ESTADO DE ENTREGA', 'FECHA DE BAJA']),
    ("JustTime & CM", ['TIPO DE FACTURACION', 'CONTRATO CREADO EN JUSTTIME', 'INICIO', 'TERMINO',
                        'N CONTRATO 3PC', 'TIPO DE CM', 'ESTADO DEL CM', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'PAGO CM']),
]

class _EtiquetaElidida(QLabel):
    """Etiqueta de una línea que acorta su texto con "..." y lo deja completo en la ayuda emergente."""

    def __init__(self, texto="", parent=None):
        super().__init__(parent)
        self._texto = ""
        self.setMinimumWidth(30)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_texto(texto)

    def set_texto(self, texto):
        self._texto = str(texto)
        self.setToolTip(self._texto)
        self._acortar()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._acortar()

    def _acortar(self):
        ancho = max(10, self.width())
        self.setText(self.fontMetrics().elidedText(self._texto, Qt.TextElideMode.ElideRight, ancho))


# Nombre visible de campos cuya columna en PruebasFM se llama distinto
_ETIQUETAS_CAMPO = {'CDB': 'CDB COMERCIAL', 'N CONTRATO 3PC': 'N° CONTRATO 3PC'}

_MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
          "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]

# Renombrado desde add_record_dialog.AddRecordDialog (mismos campos, misma
# lógica de validación/cálculo/guardado; solo cambia la presentación visual,
# reorganizada en secciones con encabezado + icono inspiradas en el nuevo
# diseño de formularios de alta de la app).
#
# Ancho fijo (px) para los campos "cortos" que no necesitan estirarse a lo
# ancho de su fila (a pedido explícito: RUT, VIN, CHASIS, CDB, DURACIÓN
# (MESES), INICIO/TÉRMINO CONTRATO se veían demasiado anchos). El resto de
# los campos no listados aquí se reparten el espacio restante de su fila.
_ANCHO_FIJO = {
    'RUT': 130,
    'CDB': 140,
    'CDB FLOTA': 100,
    'INDUSTRIA': 150,
    'VIN': 190,
    'CHASIS': 100,
    'MODELO': 100,
    'FECHA DE BAJA': 110,
    'ESTADO DE ENTREGA': 110,
    'INICIO': 110,
    'TERMINO': 110,
}

# Campos de cada bloque de la pestaña "JustTime & CM" (16-09-2026): se
# habilitan/deshabilitan juntos según TIPO DE FACTURACION (ver
# _actualizar_habilitacion_justtime_cm). TIPO DE FACTURACION no forma parte
# de ningún bloque: es el disparador, siempre editable.
_CAMPOS_BLOQUE_JUSTTIME = ['CONTRATO CREADO EN JUSTTIME', 'INICIO', 'TERMINO']
_ESTADOS_COMERCIALES_FIN = {'BAJA', 'BAJA SOLICITADA', 'VENCIDO'}
_ESTADOS_JT_CORREGIBLES = (JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_PENDIENTE, JUSTTIME_ESTADO_REVISAR_PAGO)
_CAMPOS_BLOQUE_CM = ['N CONTRATO 3PC', 'TIPO DE CM', 'ESTADO DEL CM', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'PAGO CM']

# Campos bloqueados al abrir el formulario desde general.py ("+ Nuevo
# Cliente" e "Importar Excel Power BI", ver `restringir_alta_desde_general`
# en __init__, 23-09-2026): pestañas Comercial (excepto EJECUTIVO),
# Operaciones y JustTime & CM completas. No se limpia ningún valor, solo se
# deshabilita (mismo criterio que _aplicar_restriccion_activacion/
# _actualizar_habilitacion_justtime_cm) -- la carga inicial/precarga de
# Power BI sigue llenando estos campos con lo que traiga el Excel, solo que
# el usuario no puede editarlos desde este formulario.
_CAMPOS_COMERCIAL_BLOQUEABLES_ALTA_GENERAL = [
    'FORMA DE CONTRATO', 'TIPO DE SERVICIO', 'ESTADO COMERCIAL',
    'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO',
]
_CAMPOS_OPERACIONES_BLOQUEABLES_ALTA_GENERAL = [
    'CDB FLOTA', 'FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ACTIVACIÓN ACTUAL', 'ESTADO DE ENTREGA', 'FECHA DE BAJA',
]
_CAMPOS_JUSTTIME_CM_BLOQUEABLES_ALTA_GENERAL = (
    ['TIPO DE FACTURACION'] + _CAMPOS_BLOQUE_JUSTTIME + _CAMPOS_BLOQUE_CM
)

# Condiciones del contrato anterior que NO se precargan en "Nuevo contrato":
# el contrato nuevo parte en blanco; solo se heredan los datos de la unidad y
# del cliente (VIN, chasis, modelo, razón social, RUT, CDB, ejecutivo, flota).
_CAMPOS_CONDICION_CONTRATO = (
    ['FORMA DE CONTRATO', 'TIPO DE SERVICIO', 'ESTADO COMERCIAL', 'INICIO CONTRATO', 'DURACIÓN (MESES)',
     'TÉRMINO CONTRATO', 'TIPO DE FACTURACION', 'FECHA DE BAJA', 'ESTADO DE ENTREGA',
     'ESTADO DE ACTIVACIÓN ACTUAL', 'ETAPA GESTIÓN', 'PERIODO INTERNO', 'ID', 'OBSERVACIONES']
    + _CAMPOS_BLOQUE_JUSTTIME + _CAMPOS_BLOQUE_CM
)

# En una renovación (contrato Vigente/Vencido reemplazado por uno nuevo) la
# unidad sigue activa: se conservan tipo de servicio y los datos de Operaciones.
_CAMPOS_RENOVACION_CONSERVADOS = ('TIPO DE SERVICIO', 'ESTADO DE ACTIVACIÓN ACTUAL', 'ESTADO DE ENTREGA')

# Campos con validación de "obligatorio" en _validate_and_accept: se marcan
# con asterisco rojo en su etiqueta para que sea visible en el formulario.
# CHASIS se completa solo a partir del VIN (ver _auto_calculate_chasis), asi
# que en la practica tambien exige que el VIN tenga largo suficiente.
# Definicion cerrada con Javiera (16-09-2026): RUT, RAZÓN SOCIAL, VIN,
# CHASIS, EJECUTIVO. Reemplaza la version anterior (que incluia ESTADO
# COMERCIAL en vez de RUT/EJECUTIVO). EJECUTIVO dejó de ser obligatorio
# (19-10-2026): vacío se guarda como Desconocido.
_CAMPOS_OBLIGATORIOS = {'RUT', 'RAZÓN SOCIAL', 'VIN', 'CHASIS'}

# Valores por defecto que deben verse en el formulario desde que se abre (no
# recien al guardar), definidos junto a Javiera. EJECUTIVO no tiene default:
# es obligatorio. MODELO usa "-" (agregado a las opciones oficiales del
# combo, ver general.py/comercial.py) hasta que exista un VIN válido que
# permita deducirlo (ver _auto_calculate_modelo).
_QSS_CHECK_SERVICIO = (
    "QCheckBox { background: transparent; border: none; color: #0F1B33; font-weight: 600; spacing: 8px; }"
    "QCheckBox:disabled { color: #8A96AB; }"
    "QCheckBox::indicator { width: 16px; height: 16px; border: 2px solid #66748D; border-radius: 5px; background: #FFFFFF; }"
    "QCheckBox::indicator:hover { border-color: #1B2B4E; }"
    "QCheckBox::indicator:checked { background-color: #1F6FEB; border-color: #1F6FEB; }"
    "QCheckBox::indicator:disabled { border-color: #C5CCDA; background: #F3F5F9; }"
)

_DEFAULTS_INICIALES = {
    'INDUSTRIA': 'NO DEFINIDA',
    'MODELO': '-',
    'FORMA DE CONTRATO': 'Sin Contrato',
    'TIPO DE SERVICIO': '-',
    'ESTADO COMERCIAL': 'Revisar',
    'ESTADO DE ACTIVACIÓN ACTUAL': 'No aplica',
    'FLOTA VC': '-',
    'FLOTA VC 2': '-',
    'TIPO DE CM': '-',
    'ESTADO DEL CM': '-',
    'CONTRATO CREADO EN JUSTTIME': '-',
}

# Columnas de PruebasFM que no aparecen en este formulario y que deben
# quedar en "-" al crear una unidad nueva, tal como se definio con Javiera.
# FECHA DE BAJA (16-09-2026) y los campos de JustTime/CM (16-09-2026,
# pestaña "JustTime & CM") salieron de esta lista: ahora tienen su propio
# widget. Solo queda OBSERVACIONES, que no forma parte de ninguna pestaña.
COLUMNAS_EXTRA_DEFAULT_GUION = ['OBSERVACIONES']


def _tipo_facturacion_default_para_forma_contrato(forma_contrato):
    """TIPO DE FACTURACION que corresponde por defecto a una FORMA DE
    CONTRATO sin TIPO DE FACTURACION propio todavía (25-09-2026, a pedido
    explícito: FORMA DE CONTRATO='Sin Contrato' quedaba con TIPO DE
    FACTURACION='-' en vez de 'Sin Registro' al crear una unidad nueva).
    Mismo criterio que comercial_services.normalizar_tipo_facturacion_por_forma_contrato:
    si FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ tiene una única opción válida
    para esa FORMA DE CONTRATO, esa es el default; si tiene 2+ opciones o
    la FORMA DE CONTRATO no está en la matriz, no hay un único valor que
    forzar y se deja '-'."""
    validos = FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(str(forma_contrato).strip().upper())
    if validos and len(validos) == 1:
        return next(iter(validos))
    return '-'


class _SelectorAnio(ComboTarjeta):
    """Año del periodo interno: lista desplegable en tarjeta (más reciente
    primero) con la misma API mínima que tenía el QSpinBox anterior."""

    def __init__(self, minimo, maximo, parent=None):
        super().__init__("Año", parent)
        self._minimo, self._maximo = minimo, maximo
        self.addItems([str(a) for a in range(maximo, minimo - 1, -1)])

    def minimum(self):
        return self._minimo

    def maximum(self):
        return self._maximo

    def value(self):
        return int(self.currentText())

    def setValue(self, anio):
        anio = max(self._minimo, min(int(anio), self._maximo))
        self.setCurrentText(str(anio))
