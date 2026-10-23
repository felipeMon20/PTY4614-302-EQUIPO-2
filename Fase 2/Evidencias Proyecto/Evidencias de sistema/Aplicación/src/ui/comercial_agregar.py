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
from src.ui.comercial_estilo import ComboTarjeta
from src.ui.guardado_overlay import crear_tarjeta_carga
import qtawesome as qta

from src.services.vin_service import obtener_modelo_desde_vin
from src.services import comercial_services, ejecutivos_service
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
    """'Medio + CIV + SZ' -> ('Medio', True, True). Si trae algo distinto de
    CIV/SZ, el valor completo queda como plan base (valor legado)."""
    partes = [p.strip() for p in str(valor).split('+')]
    extras = {p.upper() for p in partes[1:] if p}
    if extras <= {'CIV', 'SZ'}:
        return partes[0], 'CIV' in extras, 'SZ' in extras
    return str(valor).strip(), False, False


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
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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
    "QCheckBox::indicator:checked { background-color: #1B2B4E; border-color: #1B2B4E; }"
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


class _ComercialUnidadFormMixin:
    """Presentación + datos + validaciones del formulario de Gestión de
    Unidades, SIN ciclo de vida modal (sin exec()/accept()/reject(),
    _fit_to_screen ni el overlay de transición del modo lote -- eso queda
    en ComercialAgregarDialog, la única clase que de verdad necesita ser
    una ventana). Refactor 25-09-2026, a pedido explícito: separar la
    presentación del formulario para poder reutilizarla embebida en la
    pestaña "Unidad nueva" de comercial.py (ComercialUnidadFormWidget, ver
    abajo) sin duplicar ~1900 líneas de widgets/validaciones/cálculos.

    Se mezcla (mixin, sin heredar de QWidget/QObject) con la clase base Qt
    real en cada subclase concreta -- ComercialAgregarDialog(QDialog) o
    ComercialUnidadFormWidget(QWidget) -- que son quienes de verdad definen
    accept()/reject() (o las señales equivalentes). Los tres puntos donde
    el formulario original llamaba self.accept()/self.reject() directamente
    (_validate_and_accept, _handle_cancelar) ahora llaman a los hooks
    _on_formulario_confirmado()/_on_formulario_cancelado(), que cada
    subclase implementa a su manera -- ver el final de este archivo."""

    # Cache de un solo slot para _construir_lookups(): (df, firma, rut_lookup,
    # flota_by_cdb) del ULTIMO DataFrame con el que se calcularon; si no es
    # el mismo objeto, se compara una huella de las 6 columnas usadas (ver
    # auditoria de rendimiento B-1, 17-09-2026: ~335ms medidos sobre datos
    # reales, ~95% concentrado en los dos groupby()+construccion de dict de
    # esa funcion). Comparacion por IDENTIDAD (`is`), no por contenido:
    # self.df_base en comercial.py solo se REASIGNA, nunca se muta in-place
    # (load_data()/_on_save_finished() siempre crean un DataFrame nuevo via
    # comercial_services.procesar_df_comercial()), asi que mientras sea el
    # mismo objeto los datos no cambiaron, y cualquier recarga/guardado real
    # invalida el cache automaticamente al crear un objeto distinto -- sin
    # necesidad de una bandera "dirty" aparte. Se guarda una referencia
    # FUERTE al propio df (no solo su id() numerico) para que Python nunca
    # pueda reciclar esa direccion de memoria para otro objeto mientras el
    # cache siga vivo: evita el riesgo de colision de id() de un cache
    # basado solo en id(df). Un solo slot (no un dict creciente): memoria
    # acotada, se sobreescribe con cada dataset nuevo.
    _lookups_cache = None

    # (icono qtawesome, color de acento, color de fondo suave) por sección
    _SECTION_STYLE = {
        'empresa': ('fa5s.building', '#66748D', '#F7F8FC'),
        'unidad': ('fa5s.truck', '#66748D', '#F7F8FC'),
        'comercial': ('fa5s.file-invoice', '#66748D', '#F7F8FC'),
        'operativa': ('fa5s.cogs', '#66748D', '#F7F8FC'),
        'justtime': ('fa5s.stopwatch', '#66748D', '#F7F8FC'),
        'cm': ('fa5s.tools', '#66748D', '#F7F8FC'),
    }

    # Paso "Operaciones" del asistente: se oculta en el formulario embebido de
    # Comercial (ComercialUnidadFormWidget); los campos existen igual y
    # conservan su valor por defecto/precargado.
    _MOSTRAR_PASO_OPERACIONES = True

    _CORP = '#1B2B4E'

    def _init_form(self, flotas_unicas, dropdown_options, df_comercial=None, parent=None,
                    datos_iniciales=None, modo_edicion=False, progreso=None, registros_lote=None,
                    restringir_activacion=False, forzar_activacion_pendiente=False,
                    restringir_alta_desde_general=False, restringir_vigentes=False):
        """Construcción real del formulario -- llamada por __init__ de cada
        subclase concreta DESPUÉS de invocar el __init__ de su base Qt
        (QDialog.__init__ o QWidget.__init__), reemplazando lo que antes era
        el propio __init__ del diálogo.

        `datos_iniciales`: dict con valores ya conocidos para precargar el
        formulario (edicion de una unidad existente, o un registro importado
        desde Power BI). `modo_edicion=True` indica que se esta editando una
        unidad que ya existe en PruebasFM (cambia titulo/subtitulo; el
        guardado en si lo resuelve quien abre el dialogo, no este).

        `restringir_activacion` (22-09-2026, a pedido explícito; ajustado
        25-09-2026): True siempre que se edita una unidad desde la
        sub-pestaña "Por gestionar" o "Gestionar Bajas" de comercial.py, sin
        importar el tipo de unidad. Deja toda la pestaña "Operaciones" de
        solo lectura (sin forzar ningún valor por sí solo) y bloquea la
        edición manual de ETAPA GESTIÓN (solo cambia vía la matriz de
        negocio ya existente, ver _recalcular_etapa_gestion). El resto del
        formulario (Cliente, resto de Comercial, JustTime & CM) no cambia.

        `forzar_activacion_pendiente` (25-09-2026, a pedido explícito):
        True solo cuando, además de lo anterior, la unidad editada es
        realmente "Sin Contrato"/"Sin Registro" (el punto de partida real
        del flujo de activación, ver _es_unidad_sin_contrato_sin_registro en
        comercial.py) -- fuerza ESTADO COMERCIAL="Activación Pendiente"
        (restringiendo el combo a esa única opción, ninguna otra
        seleccionable) y ESTADO DE ACTIVACIÓN ACTUAL="Activando". Sin
        `restringir_activacion=True` no tiene efecto (no tendría sentido
        forzar el valor sin que Operaciones también quede de solo lectura).

        `registros_lote` (lista de dicts, uno por registro mapeado de Power
        BI) activa el "modo lote" de importación: UN SOLO exec() de este
        mismo diálogo recorre todos los registros, reutilizando los mismos
        widgets en vez de cerrar/reabrir una ventana por cada uno (16-09-2026,
        a pedido de Javiera: "que se sienta como un único proceso continuo").
        El diálogo solo llama accept()/reject() una vez, al terminar o
        cancelar el lote completo; el resultado se recupera después con
        `obtener_resultados_lote()`. `progreso` (tupla indice/total) sigue
        existiendo para el caso de un único registro con progreso visual,
        pero `registros_lote` lo reemplaza si ambos se pasan.

        `restringir_alta_desde_general` (23-09-2026, a pedido explícito):
        True cuando el diálogo se abre desde general.py ("+ Nuevo Cliente" o
        "Importar Excel Power BI"). Bloquea (setEnabled(False), sin borrar
        ningún valor) las pestañas Comercial (excepto EJECUTIVO), Operaciones
        y JustTime & CM completas -- ver _CAMPOS_*_BLOQUEABLES_ALTA_GENERAL y
        _aplicar_restriccion_alta_general.

        `restringir_vigentes` (25-09-2026, a pedido explícito): True solo
        cuando se edita una unidad desde la sub-pestaña "Vigentes" de
        comercial.py. Quita "Vencido" y "Activación Pendiente" de las
        opciones del combo ESTADO COMERCIAL (esos dos estados no se fijan a
        mano desde una unidad ya Vigente: "Vencido" lo decide la fecha de
        TÉRMINO CONTRATO o el botón "Marcar como Vencido" en Vencidos, y
        "Activación Pendiente" es el punto de partida del flujo de
        activación, no algo a lo que una unidad Vigente deba "retroceder"),
        y deja de solo lectura toda la pestaña "Operaciones" (a diferencia
        de `restringir_activacion`, no fuerza ningún valor fijo: el combo
        ESTADO COMERCIAL sigue interactivo entre las opciones restantes --
        incluye "Baja"/"Baja Solicitada", que Operaciones debe seguir
        recibiendo según sus propias reglas de negocio). "JustTime & CM" no
        se toca. Ver _aplicar_restriccion_vigentes."""
        self.setWindowIcon(qta.icon('fa5s.truck', color='#003057'))
        self.setMinimumWidth(660)
        # Estilo de campos (25-09-2026, a pedido explícito: "los cuadros los
        # quiero con bordes redondos y llamativos"). Antes QLineEdit/
        # QComboBox heredaban tal cual el QSS global de la app (más fino/
        # discreto, pensado para toda la app); acá se sobreescribe con reglas
        # MÁS ESPECÍFICAS que solo aplican dentro de este formulario (self y
        # sus hijos) -- Qt aplica el stylesheet del ancestro más cercano que
        # matchee cada selector, así que el resto de la app no se ve
        # afectada. QComboBox sigue usando la clase "combo_box" que ya le
        # da ThemeManager.apply_combo_box (ver _create_widget) -- solo se
        # redefine su apariencia, no el mecanismo.
        self.setStyleSheet(f"""
            QDialog {{ background-color: #F4F6FA; }}
            QLabel {{ font-weight: 600; color: #66748D; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 11px; letter-spacing: 0.6px; }}

            QLineEdit {{
                background-color: #FFFFFF;
                border: 1px solid #DCE3EC;
                border-radius: 8px;
                padding: 9px 12px;
                color: #0F1B33;
                font-size: 13px;
                font-weight: 500;
                selection-background-color: {self._CORP};
            }}
            QLineEdit:hover {{ border: 1px solid #B9C6DA; }}
            QLineEdit:focus {{ border: 1px solid {self._CORP}; }}
            QLineEdit:disabled {{ background-color: #F5F7FA; color: #8A97AB; border: 1px solid #E3E8F0; }}
            QLineEdit:read-only {{ background-color: #F5F7FA; color: #66748D; border: 1px solid #E3E8F0; }}

            QComboBox[class="combo_box"] {{
                background-color: #FFFFFF;
                border: 1px solid #DCE3EC;
                border-radius: 8px;
                padding: 8px 10px;
                color: #0F1B33;
                font-weight: 500;
                font-size: 13px;
                combobox-popup: 0;
            }}
            QComboBox[class="combo_box"]:hover {{ border: 1px solid #B9C6DA; }}
            QComboBox[class="combo_box"]:focus, QComboBox[class="combo_box"]:on {{
                border: 1px solid {self._CORP};
            }}
            QComboBox[class="combo_box"]:disabled {{ background-color: #F5F7FA; color: #8A97AB; border: 1px solid #E3E8F0; }}
            QComboBox[class="combo_box"]::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border-left: 1px solid #E3E8F0;
                border-top-right-radius: 7px;
                border-bottom-right-radius: 7px;
                background-color: #F7F8FC;
            }}
            QComboBox[class="combo_box"]:disabled::drop-down {{ background-color: #F5F7FA; border-left: 1px solid #E3E8F0; }}
            QComboBox[class="combo_box"]::down-arrow {{
                image: url({_COMBO_CHEVRON_PATH});
                width: 11px;
                height: 11px;
            }}
            QComboBox[class="combo_box"] QAbstractItemView {{
                background-color: #FFFFFF;
                border: 1px solid #DCE3EC;
                border-radius: 8px;
                selection-background-color: #E8ECF4;
                selection-color: {self._CORP};
                outline: none;
                padding: 2px;
            }}

            QSpinBox {{
                padding: 8px 10px; border: 1px solid #DCE3EC; border-radius: 8px;
                background-color: #FFFFFF; color: #0F1B33; font-weight: 500; font-size: 13px;
            }}
            QSpinBox:hover {{ border: 1px solid #B9C6DA; }}
            QSpinBox:focus {{ border: 1px solid {self._CORP}; }}
        """)

        fuente_form = self.font()
        fuente_form.setCapitalization(QFont.Capitalization.MixedCase)
        self.setFont(fuente_form)

        self.flotas_unicas = sorted(list(set(flotas_unicas)))
        self._combos_flota_pendientes = []
        self.dropdown_options = dropdown_options
        self.inputs = {}
        self.modo_edicion = modo_edicion
        self._restringir_activacion = restringir_activacion
        self._forzar_activacion_pendiente = forzar_activacion_pendiente
        self._restringir_alta_desde_general = restringir_alta_desde_general
        self._restringir_vigentes = restringir_vigentes
        self._modelo_manual = False
        self._tipo_cm_manual = False

        # --- Modo lote (importación Power BI) ---
        self._modo_lote = bool(registros_lote)
        self._lote = list(registros_lote) if registros_lote else []
        self._lote_indice = 0
        self._lote_resultados = []
        self._lote_cancelado = False
        # VIN ya confirmados en este mismo lote (ver _avanzar_lote): además de
        # _vins_existentes (PruebasFM), un VIN repetido DENTRO del propio lote
        # de Power BI también debe marcarse en rojo y bloquear Guardar (ver
        # _vin_duplicado). Vacío y sin efecto fuera del modo lote.
        self._vins_usados_en_lote = set()
        if self._modo_lote:
            datos_iniciales = self._lote[0]
            progreso = (1, len(self._lote))
        self.progreso = progreso

        self._chasis_bi_actual = (datos_iniciales or {}).get('_CHASIS_BI', '') if self._modo_lote else ''
        # Valor REAL vigente de TIPO DE FACTURACION (nunca el texto amigable
        # del combo de la pestaña "JustTime & CM"): alimenta el segundo
        # disparador de ETAPA GESTIÓN y la habilitación de bloques (ver
        # _recalcular_etapa_gestion/_set_tipo_facturacion_actual/
        # _actualizar_habilitacion_justtime_cm). El combo real es la fuente
        # de verdad mientras el diálogo está abierto (ver
        # _on_tipo_facturacion_editado); esta línea solo fija el valor
        # inicial antes de que _setup_ui() construya ese combo.
        _forma_contrato_inicial = (datos_iniciales or {}).get('FORMA DE CONTRATO') or _DEFAULTS_INICIALES['FORMA DE CONTRATO']
        self._tipo_facturacion_actual = (datos_iniciales or {}).get('TIPO DE FACTURACION') or \
            _tipo_facturacion_default_para_forma_contrato(_forma_contrato_inicial)

        # VIN original de la unidad en edición (siempre válido contra sí
        # mismo al validar duplicados) y set de VIN ya existentes en
        # Comercial, para la validación en vivo del punto "Editar VIN".
        self._vin_original = (datos_iniciales or {}).get('VIN', '').strip().upper() if modo_edicion else None
        self._vins_existentes = set()
        if isinstance(df_comercial, pd.DataFrame) and not df_comercial.empty and 'VIN' in df_comercial.columns:
            self._vins_existentes = set(df_comercial['VIN'].dropna().astype(str).str.strip().str.upper())
            self._vins_existentes.discard('')
        self._vins_con_contrato_abierto = comercial_services.vins_con_contrato_abierto(df_comercial)
        self.modo_nuevo_contrato = False
        self.modo_renovacion = False
        self._vin_contrato_nuevo = ''
        self._id_contrato = str((datos_iniciales or {}).get('ID', '')).strip() if modo_edicion else ''
        self._contrato_cerrado = False
        self._puede_nuevo_contrato = False

        # RUT -> {RAZÓN SOCIAL, CDB, EJECUTIVO, INDUSTRIA} (listas/contador de
        # valores vistos en Comercial para ese RUT) y CDB -> lista de FLOTA VC
        # asociadas. Se usan para autocompletar/filtrar al ingresar el RUT.
        self._rut_lookup, self._flota_by_cdb = self._construir_lookups(df_comercial)
        self._ejecutivos_todos = self._construir_lista_ejecutivos(df_comercial)

        self._setup_ui()

        if datos_iniciales:
            self._aplicar_datos_iniciales(datos_iniciales)

        # Debe aplicarse DESPUÉS de _aplicar_datos_iniciales (22-09-2026):
        # ese método precarga ESTADO COMERCIAL/ESTADO DE ACTIVACIÓN ACTUAL
        # con los valores reales de la unidad y recalcula ETAPA GESTIÓN en
        # base a ellos, pisando lo que _aplicar_restriccion_activacion
        # hubiera forzado si se llamaba antes (dentro de _setup_ui).
        if self._restringir_activacion:
            self._aplicar_restriccion_activacion(self._forzar_activacion_pendiente)

        # Mismo criterio que _restringir_activacion arriba: se aplica al
        # final para no depender de qué haga _aplicar_datos_iniciales (que
        # también se reaplica sola en cada registro del lote, ver
        # _aplicar_restriccion_alta_general).
        if self._restringir_alta_desde_general:
            self._aplicar_restriccion_alta_general()

        # Mismo criterio: se aplica al final para no depender del orden de
        # _aplicar_datos_iniciales/_setup_ui.
        if self._restringir_vigentes:
            self._aplicar_restriccion_vigentes()

        if self._modo_lote:
            self._actualizar_boton_chasis_bi()

        self._validar_vin_duplicado()

    # ------------------------------------------------------------------
    # Lookups RUT -> Razón Social / CDB / Ejecutivo, CDB -> Flota VC
    # ------------------------------------------------------------------
    @staticmethod
    def _normalizar_rut(rut):
        """Deja solo dígitos y el dígito verificador (letra K incluida),
        sin puntos/guion/espacios, en mayúsculas. Causa raíz del bug de
        autocompletado reportado el 16-09-2026: PruebasFM guarda el RUT con
        puntos y guion (ej. '12.345.678-9', ver generar_mock_data.py) pero
        la comparación anterior era un match exacto de texto -- cualquier
        diferencia de formato entre lo tipeado y lo almacenado (con/sin
        puntos, con/sin guion, espacios) hacía fallar la búsqueda. Se
        normaliza en ambos lados (aquí y en _on_rut_completado) antes de
        comparar, en vez de exigir que el formato tipeado coincida
        exactamente con el guardado."""
        return re.sub(r'[^0-9A-Z]', '', str(rut).upper())

    @staticmethod
    def _construir_lista_ejecutivos(df):
        """Ejecutivos activos del directorio (Ejecutivos_VC.csv) más los nombres
        de Comercial que el directorio no reconoce, sin repetir alias."""
        directorio = pd.DataFrame()
        try:
            if os.path.exists(ejecutivos_service.get_ejecutivos_csv_path()):
                directorio = ejecutivos_service.leer_ejecutivos()
        except Exception:
            directorio = pd.DataFrame()
        nombres = []
        if not directorio.empty:
            activos = directorio[directorio['activo'].astype(str).str.strip().str.upper() != 'NO']
            nombres = [n.strip() for n in activos['nombre'].tolist() if n.strip()]
        if isinstance(df, pd.DataFrame) and not df.empty and 'EJECUTIVO' in df.columns:
            for nombre in df['EJECUTIVO'].dropna().astype(str).str.strip().unique():
                if nombre.lower() in ejecutivos_service._NOMBRES_IGNORADOS:
                    continue
                if not directorio.empty and ejecutivos_service.buscar_ejecutivo(
                        nombre, directorio, incluir_inactivos=True):
                    continue
                nombres.append(nombre)
        vistos, resultado = set(), []
        for nombre in sorted(nombres, key=str.casefold):
            clave = ejecutivos_service.normalizar_nombre(nombre)
            if clave not in vistos:
                vistos.add(clave)
                resultado.append(nombre)
        return resultado

    def _construir_lookups(self, df):
        rut_lookup, flota_by_cdb = {}, {}
        if df is None or not isinstance(df, pd.DataFrame) or df.empty or 'RUT' not in df.columns:
            return rut_lookup, flota_by_cdb

        cols = ['RUT', 'RAZÓN SOCIAL', 'CDB', 'EJECUTIVO', 'FLOTA VC', 'INDUSTRIA']
        cache = _ComercialUnidadFormMixin._lookups_cache
        if cache is not None and cache[0] is df:
            return cache[2], cache[3]
        # Otra copia con los mismos datos (ej. df_master de JustTime vs.
        # df_base de Comercial): se reconoce por una huella del contenido
        firma = self._firma_lookups(df, cols)
        if cache is not None and firma is not None and cache[1] == firma:
            _ComercialUnidadFormMixin._lookups_cache = (df, firma, cache[2], cache[3])
            return cache[2], cache[3]

        df_aux = pd.DataFrame({c: (df[c] if c in df.columns else "") for c in cols})
        df_aux = df_aux.fillna("").astype(str).apply(lambda s: s.str.strip())
        df_aux = df_aux[df_aux['RUT'] != ""]

        # Un solo recorrido sobre listas (antes groupby por RUT: ~4x más
        # lento). Claves en orden alfabético, igual que groupby.
        normalizados, grupos = {}, {}
        for rut, razon, cdb, ejecutivo, industria in zip(
                df_aux['RUT'].tolist(), df_aux['RAZÓN SOCIAL'].tolist(), df_aux['CDB'].tolist(),
                df_aux['EJECUTIVO'].tolist(), df_aux['INDUSTRIA'].tolist()):
            clave = normalizados.get(rut)
            if clave is None:
                clave = normalizados[rut] = self._normalizar_rut(rut)
            if clave in ('', 'SINRUT'):
                continue
            g = grupos.get(clave)
            if g is None:
                g = grupos[clave] = (set(), set(), set(), [])
            if razon: g[0].add(razon)
            # Solo CDB reales (numéricos): un "-" no cuenta como CDB del RUT
            cdb_valido = re.sub(r'\.0$', '', cdb)
            if cdb_valido.isdigit(): g[1].add(cdb_valido)
            if ejecutivo: g[2].add(ejecutivo)
            if industria: g[3].append(industria)

        for rut_key in sorted(grupos):
            razones, cdbs, ejecutivos, industrias = grupos[rut_key]
            rut_lookup[rut_key] = {
                'RAZÓN SOCIAL': sorted(razones),
                'CDB': sorted(cdbs),
                'EJECUTIVO': sorted(ejecutivos),
                # Industria mas frecuente para este RUT (moda); None si no hay
                # ninguna registrada. Un RUT puede tener varias unidades con
                # industrias distintas -- se usa la mas comun como sugerencia,
                # el usuario puede cambiarla a mano.
                'INDUSTRIA_MODA': Counter(industrias).most_common(1)[0][0] if industrias else None,
            }

        flotas = {}
        for cdb, flota in zip(df_aux['CDB'].tolist(), df_aux['FLOTA VC'].tolist()):
            if cdb and flota:
                flotas.setdefault(cdb.upper(), set()).add(flota)
        for cdb_key in sorted(flotas):
            flota_by_cdb[cdb_key] = sorted(flotas[cdb_key])

        _ComercialUnidadFormMixin._lookups_cache = (df, firma, rut_lookup, flota_by_cdb)
        return rut_lookup, flota_by_cdb

    @staticmethod
    def _firma_lookups(df, cols):
        try:
            presentes = [c for c in cols if c in df.columns]
            hashes = pd.util.hash_pandas_object(df[presentes].astype(str), index=False).to_numpy()
            return (len(df), tuple(presentes), hashlib.blake2b(hashes.tobytes(), digest_size=16).hexdigest())
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Título/subtítulo del encabezado (25-09-2026): extraído a método propio
    # porque ComercialUnidadFormWidget reutiliza la misma instancia del
    # formulario para alternar entre modo crear/editar (ver
    # resetear_para_crear/cargar_para_editar), así que el título ya no se
    # calcula una sola vez al construir -- ver _actualizar_titulo.
    # ------------------------------------------------------------------
    # Renovación de varias unidades a la vez: sin el paso "Empresa & Unidad" (ver
    # ComercialUnidadFormWidget._configurar_modo_multiple)
    _primer_paso = 0
    cantidad_multiple = 1

    def _autocompletar_duracion_mensual(self):
        """Con facturación manual el contrato siempre es mensual: duración "-" y término MENSUAL."""
        if str(self._tipo_facturacion_actual).strip().upper() != VALOR_TIPO_FACT_FACTURACION_MANUAL:
            return
        duracion = self.inputs['DURACIÓN (MESES)']
        if duracion.text().strip() != '-':
            duracion.setText('-')
        self._auto_calculate_termino()

    def _calcular_titulo_subtitulo(self):
        if self.modo_renovacion and self.cantidad_multiple > 1:
            return f"Renovar {self.cantidad_multiple} contratos", (
                "Los cambios de Comercial y JustTime & CM se aplican a todas las unidades seleccionadas. "
                "Al guardar, cada contrato actual queda como Renovado y se crea uno nuevo.")
        if self.modo_renovacion:
            return "Renovar con un contrato nuevo", (
                f"Contrato nuevo para la unidad {self._vin_contrato_nuevo}. Al guardar, el contrato actual queda "
                "como Renovado en el historial y este pasa a ser el vigente.")
        if self.modo_nuevo_contrato:
            return "Nuevo contrato", (f"Nuevo contrato para la unidad {self._vin_contrato_nuevo}. "
                                      "Se crea con un N° Contrato nuevo y el anterior queda en el historial.")
        if self.modo_edicion:
            prefijo = f"N° Contrato {self._id_contrato} · " if self._id_contrato else ""
            if self._contrato_cerrado:
                cierre = ("Para reactivar la unidad cree un nuevo contrato." if self._puede_nuevo_contrato else
                          "Para reactivarla, Operaciones debe dejar la unidad desconectada.")
                return "Contrato finalizado", f"{prefijo}Solo lectura: un contrato en baja no se modifica. {cierre}"
            return "Editar Unidad", f"{prefijo}Modifique los datos de la unidad y guarde los cambios."
        if self.progreso:
            return "Importar desde Power BI", "Complete o revise la información de este registro antes de continuar."
        return "Crear Nueva Unidad", "Ingrese la información de la unidad para agregarla a Comercial."

    def _actualizar_titulo(self):
        titulo, subtitulo = self._calcular_titulo_subtitulo()
        self.setWindowTitle(f" Gestión de Unidades — {titulo}")
        self._title_lbl.setText(titulo)
        self._subtitle_lbl.setText(subtitulo)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _setup_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 4, 8, 8)
        outer_layout.setSpacing(12)

        # --- Encabezado: titulo/subtitulo varian segun el modo (nueva /
        # edicion / importacion en lote via `progreso`). Guardados como
        # self._title_lbl/_subtitle_lbl (25-09-2026): ComercialUnidadFormWidget
        # reutiliza la misma instancia del formulario para alternar entre
        # modo crear/editar (ver _actualizar_titulo), así que el título ya
        # no puede fijarse una sola vez al construir el widget. ---
        titulo, subtitulo = self._calcular_titulo_subtitulo()
        self.setWindowTitle(f" Gestión de Unidades — {titulo}")

        header_row = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background-color: #EEF2F6; border-radius: 10px;")
        icon_lbl.setPixmap(qta.icon('fa5s.truck', color='#66748D').pixmap(18, 18))
        header_texts = QVBoxLayout()
        header_texts.setSpacing(1)
        self._title_lbl = QLabel(titulo)
        self._title_lbl.setStyleSheet("font-size: 18px; color: #0F1B33; font-weight: 700; letter-spacing: 0;")
        self._subtitle_lbl = QLabel(subtitulo)
        self._subtitle_lbl.setStyleSheet("font-size: 12px; color: #66748D; font-weight: 400; letter-spacing: 0;")
        header_texts.addWidget(self._title_lbl)
        header_texts.addWidget(self._subtitle_lbl)
        header_row.addWidget(icon_lbl)
        header_row.addSpacing(10)
        header_row.addLayout(header_texts)
        header_row.addStretch()
        # Chasis de Power BI del registro que se está importando: solo
        # identificador interno del lote (nunca llena CHASIS, que sigue
        # derivándose del VIN), pero se muestra para que la persona lo pueda
        # copiar rápido si lo necesita en otro lado. A pedido del usuario
        # (16-09-2026): en rojo, junto al contador de progreso, con el
        # formato "CHASIS: XXXXXX" en vez de "Chasis Power BI: XXXXXX".
        self._btn_chasis_bi = QPushButton("")
        self._btn_chasis_bi.setFlat(True)
        self._btn_chasis_bi.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_chasis_bi.setStyleSheet(
            f"QPushButton {{ text-align: right; border: none; background: transparent; "
            f"color: {DANGER}; font-weight: bold; font-size: 11px; padding: 0; }}"
        )
        self._btn_chasis_bi.setToolTip("Clic para copiar el Chasis de Power BI al portapapeles.")
        self._btn_chasis_bi.clicked.connect(self._copiar_chasis_bi)
        self._btn_chasis_bi.setVisible(False)
        header_row.addWidget(self._btn_chasis_bi)
        header_row.addSpacing(8)

        self._badge_progreso = QLabel()
        self._badge_progreso.setStyleSheet("background-color: #1C6BBA; color: white; font-size: 12px; font-weight: bold; border-radius: 10px; padding: 3px 4px;")
        self._badge_progreso.setVisible(bool(self.progreso))
        header_row.addWidget(self._badge_progreso)
        outer_layout.addLayout(header_row)

        if self.progreso:
            self._actualizar_progreso_visual()

        # Overlay breve "Cargando siguiente Unidad" entre un registro y el
        # siguiente durante una importación en lote: se muestra encima del
        # mismo diálogo (nunca se cierra ni se vuelve a abrir), para que se
        # sienta como un único proceso continuo. Usa la misma tarjeta de
        # carga con spinner que el resto de la app (gira solo mientras se ve).
        self._overlay_transicion = QWidget()
        overlay_layout = QVBoxLayout(self._overlay_transicion)
        overlay_layout.setContentsMargins(0, 20, 0, 20)
        overlay_layout.addStretch()

        tarjeta_overlay = crear_tarjeta_carga("Cargando siguiente unidad…", "Preparando el siguiente registro del lote.")

        overlay_row_centrado = QHBoxLayout()
        overlay_row_centrado.addStretch()
        overlay_row_centrado.addWidget(tarjeta_overlay)
        overlay_row_centrado.addStretch()
        overlay_layout.addLayout(overlay_row_centrado)
        overlay_layout.addStretch()

        self._overlay_transicion.setVisible(False)
        outer_layout.addWidget(self._overlay_transicion)

        # Contenedor único con el resto del formulario (periodo + secciones):
        # se oculta entero durante el overlay de transición de un registro a
        # otro, y se vuelve a mostrar ya con los datos del siguiente.
        self._contenido_widget = QWidget()
        contenido_layout = QVBoxLayout(self._contenido_widget)
        contenido_layout.setContentsMargins(0, 0, 0, 0)
        contenido_layout.setSpacing(14)
        outer_layout.addWidget(self._contenido_widget, 1)

        # --- Periodo interno de gestión: visible y editable, no solo el mes
        # actual inyectado en silencio (a pedido de Javiera). Se guarda con
        # el mismo formato "Mes - Año" que ya usa el resto del proyecto. ---
        periodo_row = QHBoxLayout()
        periodo_row.setSpacing(8)
        lbl_periodo = QLabel("PERIODO INTERNO:")
        self.combo_periodo_mes = ComboTarjeta("Mes")
        self.combo_periodo_mes.addItems(_MESES)
        ThemeManager.apply_combo_box(self.combo_periodo_mes)
        self.combo_periodo_mes.setMinimumWidth(150)
        self.combo_periodo_mes.setMinimumHeight(40)
        hoy = datetime.now()
        self.spin_periodo_anio = _SelectorAnio(2000, hoy.year)
        ThemeManager.apply_combo_box(self.spin_periodo_anio)
        self.spin_periodo_anio.setMinimumWidth(96)
        self.spin_periodo_anio.setMinimumHeight(40)
        self.combo_periodo_mes.setCurrentText(_MESES[hoy.month - 1])
        self.spin_periodo_anio.setValue(hoy.year)
        periodo_row.addWidget(lbl_periodo)
        periodo_row.addWidget(self.combo_periodo_mes)
        periodo_row.addWidget(self.spin_periodo_anio)

        # --- Indicador ETAPA GESTIÓN (16-09-2026): visible siempre, fuera de
        # las pestañas (igual que el período interno), para que se vea sin
        # importar en qué pestaña esté el usuario. Reutiliza tal cual la
        # regla central de negocio (DataFrameFormatter.calcular_etapa_gestion_esperada)
        # y la paleta de colores existente (ETAPA_GESTION_COLORES, antes en
        # general.py, movida a constants.py para evitar un import circular)
        # -- no se reimplementa la regla ni se inventa una paleta nueva.
        # Bloqueado siempre (22-09-2026, a pedido explícito: la regla de
        # negocio debe respetarse siempre, no solo en el modo restringido
        # de "Por gestionar"/"Gestionar Bajas"): el combo nunca es editable
        # por el usuario, solo cambia vía _recalcular_etapa_gestion.
        # Oculto (07-10-2026, a pedido explícito): la aplicación la
        # calcula sola; el widget sigue existiendo como portador del
        # valor para get_data y las restricciones.
        lbl_etapa = QLabel("ETAPA GESTIÓN:")
        combo_etapa = QComboBox()
        combo_etapa.addItems(sorted(ETAPA_GESTION_COLORES.keys()))
        ThemeManager.apply_combo_box(combo_etapa)
        combo_etapa.setEnabled(False)
        self.inputs['ETAPA GESTIÓN'] = combo_etapa
        periodo_row.addWidget(lbl_etapa)
        periodo_row.addWidget(combo_etapa)
        lbl_etapa.setVisible(False)
        combo_etapa.setVisible(False)

        header_row.insertLayout(header_row.indexOf(self._btn_chasis_bi), periodo_row)

        # --- Cuerpo: pestañas por bloque temático (Cliente / Comercial /
        # Operaciones / JustTime & CM), a pedido explícito del usuario para
        # que el formulario no se sienta como una sola pantalla enorme
        # (16-09-2026). Mismos widgets y misma lógica de siempre: este
        # cambio es solo de distribución visual, no de datos. Mismo QSS de
        # pestañas que ya usa el resto de la app (ver ComercialModule en
        # comercial.py), para no introducir un lenguaje visual nuevo.
        # Pestañas y páginas nacen dentro del formulario y se llenan
        # después: armarlas sueltas y moverlas al final re-aplicaba los
        # estilos a todo su contenido una vez por cada nivel
        self.tabs = QTabWidget(self._contenido_widget)
        self.tabs.tabBar().hide()
        self.tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
        pagina_empresa = QWidget()
        tab_comercial = QWidget()
        tab_justtime_cm = QWidget()
        tab_operaciones = QWidget()
        self.tabs.addTab(pagina_empresa, "Empresa & Unidad")
        self.tabs.addTab(tab_comercial, "Comercial")
        self.tabs.addTab(tab_justtime_cm, "JustTime & CM")
        self.tabs.addTab(tab_operaciones, "Operaciones")

        # --- Pestaña única "Comercial" (25-09-2026, a pedido
        # explícito): fusiona lo que antes eran las pestañas
        # "Cliente" y "Comercial". JustTime & CM SE PROBÓ fusionada
        # acá también, pero con las 5 secciones apiladas el
        # formulario quedaba demasiado alto para resoluciones de
        # pantalla normales y los campos terminaban superpuestos
        # (reportado por el usuario) -- se le devolvió su propia
        # pestaña (ver más abajo), igual que "Operaciones", que
        # nunca tuvo este problema por tener una sola sección.
        # Mismas secciones/_build_section de siempre, solo cambia en
        # qué pestaña viven -- ninguna lógica de datos/validación
        # cambia por esto. ---
        layout_empresa = QVBoxLayout(pagina_empresa)
        layout_empresa.setContentsMargins(0, 0, 0, 0)
        layout_empresa.setSpacing(14)
        layout_empresa.addWidget(self._build_section(
            'empresa', "1. Empresa", "Información del cliente propietario de la unidad.",
            [[('RUT', 'lineedit'), ('RAZÓN SOCIAL', 'lineedit'), ('INDUSTRIA', 'combo_editable')]],
            padre=pagina_empresa
        ))
        layout_empresa.addWidget(self._build_section(
            'unidad', "2. Información de la unidad", "Datos técnicos del camión.",
            [[('VIN', 'lineedit'), ('CHASIS', 'readonly'), ('MODELO', 'combo'), ('CDB', 'lineedit')]],
            padre=pagina_empresa
        ))
        layout_empresa.addStretch()

        layout_comercial = QVBoxLayout(tab_comercial)
        layout_comercial.setContentsMargins(0, 0, 0, 0)
        layout_comercial.setSpacing(14)
        layout_comercial.addWidget(self._build_section(
            'comercial', "3. Información comercial", "Datos de la venta y facturación del servicio.",
            [
                [('EJECUTIVO', 'combo_editable'), ('FORMA DE CONTRATO', 'combo'), ('TIPO DE FACTURACION', 'tipo_facturacion'), ('ESTADO COMERCIAL', 'combo')],
                [('TIPO DE SERVICIO', 'combo'), ('INICIO CONTRATO', 'date'), ('DURACIÓN (MESES)', 'lineedit'), ('TÉRMINO CONTRATO', 'readonly')],
            ],
            padre=tab_comercial
        ))
        layout_comercial.addStretch()

        # --- Pestaña "Operaciones" ---
        layout_operaciones = QVBoxLayout(tab_operaciones)
        layout_operaciones.setContentsMargins(0, 0, 0, 0)
        layout_operaciones.setSpacing(14)
        _section_operativa = self._build_section(
            'operativa', "6. Información operativa", "Estado y flota de la unidad en Volvo Connect.",
            [
                [('FLOTA VC', 'combo_editable'), ('FLOTA VC 2', 'combo_editable'), ('ESTADO DE ACTIVACIÓN ACTUAL', 'combo')],
                [('CDB FLOTA', 'lineedit'), ('ESTADO DE ENTREGA', 'date'), ('FECHA DE BAJA', 'date')],
            ],
            padre=tab_operaciones
        )
        layout_operaciones.addWidget(_section_operativa)
        layout_operaciones.addStretch()
        self._pagina_operaciones = tab_operaciones

        # --- Pestaña "JustTime & CM" (25-09-2026: separada de nuevo
        # de "Comercial" -- ver comentario más arriba). Mismo
        # contenido lado a lado de siempre, solo con pestaña propia
        # en vez de compartida. ---
        layout_justtime_cm = QVBoxLayout(tab_justtime_cm)
        layout_justtime_cm.setContentsMargins(0, 0, 0, 0)
        layout_justtime_cm.setSpacing(14)
        row_justtime_cm = QHBoxLayout()
        row_justtime_cm.setSpacing(14)
        _section_justtime = self._build_section(
            'justtime', "4. JustTime", "Facturación y contrato en JustTime (según Tipo de Facturación).",
            [
                [('CONTRATO CREADO EN JUSTTIME', 'combo'), ('INICIO', 'date'), ('TERMINO', 'date')],
            ],
            padre=tab_justtime_cm
        )
        row_justtime_cm.addWidget(_section_justtime, 1)
        _section_cm = self._build_section(
            'cm', "5. Contrato de Mantenimiento (CM)", "Solo aplica cuando Tipo de Facturación es CM.",
            [
                [('N CONTRATO 3PC', 'lineedit'), ('TIPO DE CM', 'combo'), ('ESTADO DEL CM', 'combo')],
                [('FECHA INICIO CM', 'date'), ('FECHA TERMINO CM', 'date'), ('PAGO CM', 'lineedit')],
            ],
            padre=tab_justtime_cm
        )
        row_justtime_cm.addWidget(_section_cm, 1)
        layout_justtime_cm.addLayout(row_justtime_cm)
        layout_justtime_cm.addStretch()

        self._construir_cuerpo_pasos(contenido_layout)
        # Antes había una lógica de foco distinta para alta vs. edición
        # (pestaña "Cliente" vs. "Comercial", ver historial 25-09-2026);
        # con las fusiones/separaciones de pestañas del 25-09-2026
        # "Comercial" (0) sigue siendo el foco inicial correcto tanto
        # para crear como para editar -- no hace falta elegir índice
        # según el modo.
        self.tabs.setCurrentIndex(0)

        # --- Conexiones en vivo para cálculos y autocompletado ---
        self.inputs['VIN'].textChanged.connect(self._auto_calculate_chasis)
        self.inputs['VIN'].textChanged.connect(self._auto_calculate_modelo)
        # textChanged cubre tanto tipeo como pegado (Ctrl+V) del VIN.
        self.inputs['VIN'].textChanged.connect(self._validar_vin_duplicado)
        # MODELO: si el usuario elige un valor a mano desde el combo
        # (`activated`, no `currentTextChanged`: así no se confunde con los
        # setCurrentText programáticos de _auto_calculate_modelo/precarga),
        # el autocompletado por VIN deja de pisarlo.
        self.inputs['MODELO'].activated.connect(self._on_modelo_editado_manualmente)
        self.inputs['INICIO CONTRATO'].textChanged.connect(self._on_inicio_contrato_changed)
        self.inputs['DURACIÓN (MESES)'].textChanged.connect(self._auto_calculate_termino)
        self.inputs['DURACIÓN (MESES)'].textChanged.connect(self._on_duracion_nuevo_contrato)
        self.inputs['FECHA DE BAJA'].textChanged.connect(self._on_fecha_baja_changed)
        self.inputs['ESTADO DE ENTREGA'].textChanged.connect(self._on_fecha_generica_widget_changed)
        self.inputs['PAGO CM'].textChanged.connect(self._on_pago_cm_changed)
        # textChanged (no editingFinished): autocompletar apenas se escribe o
        # pega el RUT/CDB, sin esperar a que el campo pierda el foco.
        self.inputs['RUT'].textChanged.connect(self._on_rut_completado)
        self.inputs['CDB'].textChanged.connect(self._actualizar_flota_vc_por_cdb)

        # ETAPA GESTIÓN: recalculo automático al cambiar cualquiera de sus 3
        # disparadores (ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL --
        # agregado 21-09-2026, matriz de 2 ejes -- y TIPO DE FACTURACION,
        # este último ya con su combo real, ver
        # _on_tipo_facturacion_editado). Sin edición manual (22-09-2026,
        # ver combo_etapa.setEnabled(False) más arriba): el combo está
        # deshabilitado, así que no hay ninguna interacción de usuario que
        # conectar aquí.
        self.inputs['ESTADO COMERCIAL'].currentTextChanged.connect(self._recalcular_etapa_gestion)
        self.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].currentTextChanged.connect(self._recalcular_etapa_gestion)
        # `activated`: solo cuando la persona elige el estado, no al precargar datos
        self.inputs['ESTADO COMERCIAL'].activated.connect(self._sincronizar_activacion_con_estado_comercial)
        self.inputs['ESTADO COMERCIAL'].currentTextChanged.connect(self._ajustar_justtime_manual)
        self.inputs['CONTRATO CREADO EN JUSTTIME'].activated.connect(self._on_justtime_elegido)

        # Pestaña "JustTime & CM": TIPO DE FACTURACION dispara ETAPA GESTIÓN
        # (arriba) y la habilitación de bloques; FORMA DE CONTRATO autocompleta
        # TIPO DE CM cuando corresponde a un código de mantenimiento.
        self.inputs['TIPO DE FACTURACION'].activated.connect(self._on_tipo_facturacion_editado)
        # Orden importa: primero sincroniza si CM debe habilitarse/deshabilitarse
        # (FORMA DE CONTRATO manda), y recién después autocompleta TIPO DE CM.
        self.inputs['FORMA DE CONTRATO'].currentTextChanged.connect(self._sincronizar_tipo_facturacion_con_forma_contrato)
        self.inputs['FORMA DE CONTRATO'].currentTextChanged.connect(self._autocompletar_tipo_cm)
        self.inputs['FORMA DE CONTRATO'].currentTextChanged.connect(self._sincronizar_estado_con_contrato)
        self.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].currentTextChanged.connect(self._sincronizar_estado_con_contrato)
        self.inputs['TIPO DE CM'].activated.connect(self._on_tipo_cm_editado_manualmente)
        for campo_fecha in ('INICIO', 'TERMINO', 'FECHA INICIO CM', 'FECHA TERMINO CM'):
            self.inputs[campo_fecha].textChanged.connect(self._on_fecha_generica_widget_changed)

        self._recalcular_etapa_gestion()
        self._actualizar_habilitacion_justtime_cm()
        self._actualizar_habilitacion_tipo_facturacion()
        self._conectar_resumen()

        # --- Botones inferiores ---
        # Fila con 2 grupos (25-09-2026, a pedido explícito): a la
        # izquierda "Restablecer"/"Importar Excel Power BI" (ver
        # agregar_boton_pie), a la derecha Cancelar/Guardar Registro,
        # separados por un stretch central.
        btn_layout = QHBoxLayout()

        self._btn_layout_izquierda = QHBoxLayout()
        self._btn_layout_izquierda.setSpacing(8)
        btn_layout.addLayout(self._btn_layout_izquierda)

        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancelar")
        # Rojo con letra blanca (25-09-2026, a pedido explícito) --
        # hover/pressed en tonos de rojo distintos entre sí para que
        # el clic se sienta (a pedido explícito: "no pueden tener el
        # mismo color al cambiar").
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #FFFFFF; border: 1px solid #DCE3EC; color: #A8453F; "
            "padding: 0 18px; min-height: 40px; border-radius: 8px; font-size: 13px; font-weight: 600; } "
            "QPushButton:hover { background-color: #FBF1F0; } "
            "QPushButton:pressed { background-color: #F5E1DF; }"
        )
        # Sin autoDefault: Enter en cualquier campo del formulario (ej. al
        # pegar el RUT) no debe disparar ningun boton ni cerrar el dialogo.
        btn_cancel.setAutoDefault(False)
        btn_cancel.setDefault(False)
        # En modo lote, cancelar pide confirmación (todo el lote se pierde);
        # en los demás modos se mantiene el comportamiento de siempre.
        btn_cancel.clicked.connect(self._handle_cancelar)

        self.btn_save = QPushButton("")
        self.btn_save.setIcon(qta.icon('fa5s.save', color='white'))
        self.btn_save.setStyleSheet(
            f"QPushButton {{ background-color: {self._CORP}; color: white; border: 1px solid {self._CORP}; "
            "padding: 0 20px; min-height: 40px; border-radius: 8px; font-weight: 600; font-size: 13px; } "
            "QPushButton:hover { background-color: #2B3D63; border-color: #2B3D63; } "
            "QPushButton:pressed { background-color: #15213D; } "
            "QPushButton:disabled { background-color: #A9B4C6; border-color: #A9B4C6; }"
        )
        self.btn_save.setAutoDefault(False)
        self.btn_save.setDefault(False)
        self.btn_save.clicked.connect(self._validate_and_accept)

        btn_layout.addWidget(btn_cancel)
        self._nav_layout.addWidget(self.btn_save)
        # Expuesto para que ComercialUnidadFormWidget pueda agregar
        # botones extra al grupo izquierdo de esta misma fila
        # (25-09-2026, a pedido explícito: "Importar Excel Power BI"
        # abajo a la izquierda junto al nuevo botón de restablecer --
        # ver agregar_boton_pie más abajo).
        self._btn_layout_inferior = btn_layout

        outer_layout.addLayout(btn_layout)

        self._actualizar_texto_guardar()

        self._poblar_combos_flota()

    def _poblar_combos_flota(self):
        """Carga el catálogo de flotas una vez armado el formulario, en el
        mismo orden de antes (ítems y luego el valor por defecto)."""
        for w, field_name in self._combos_flota_pendientes:
            w.addItems([""] + self.flotas_unicas)
            if field_name in _DEFAULTS_INICIALES:
                w.setCurrentText(_DEFAULTS_INICIALES[field_name])
        self._combos_flota_pendientes = []

    def _crear_checks_tipo_servicio(self, combo):
        """Checks CIV y SZ bajo el combo de TIPO DE SERVICIO."""
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.chk_civ = QCheckBox("CIV")
        self.chk_sz = QCheckBox("SZ")
        for chk in (self.chk_civ, self.chk_sz):
            chk.setCursor(Qt.CursorShape.PointingHandCursor)
            chk.setStyleSheet(_QSS_CHECK_SERVICIO)
            pastilla = QFrame()
            pastilla.setObjectName("pastillaServicio")
            pastilla.setStyleSheet(
                "QFrame#pastillaServicio { background-color: #EEF2F6; border: 1px solid #DCE3EC; border-radius: 13px; }")
            lay_pastilla = QHBoxLayout(pastilla)
            lay_pastilla.setContentsMargins(8, 3, 8, 3)
            lay_pastilla.setSpacing(0)
            lay_pastilla.addWidget(chk)
            pastilla.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            pastilla.setMinimumWidth(chk.sizeHint().width() + 16)
            fila.addWidget(pastilla)
        fila.addStretch()
        self._filtro_checks_tipo_servicio = _FiltroHabilitado(combo, [self.chk_civ, self.chk_sz])
        return fila

    def _build_section(self, key, title, subtitle, rows, padre=None):
        icon_name, accent, bg = self._SECTION_STYLE[key]

        # Cada contenedor se cuelga antes de llenarlo (ver _setup_ui > 4)
        card = QFrame(padre)
        card.setObjectName("sectionCard")
        card.setStyleSheet(
            "QFrame#sectionCard { background-color: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 12px; }")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(1, 1, 1, 1)
        card_layout.setSpacing(0)

        header = QFrame(card)
        header.setObjectName("sectionHeader")
        header.setStyleSheet(
            f"QFrame#sectionHeader {{ background-color: {bg}; border: none; border-bottom: 1px solid #E3E8F0; "
            "border-top-left-radius: 11px; border-top-right-radius: 11px; }")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        header_layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("background-color: #EEF2F6; border: none; border-radius: 8px;")
        icon_lbl.setPixmap(qta.icon(icon_name, color=accent).pixmap(14, 14))
        header_layout.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 14px; color: #0F1B33; font-weight: 600; letter-spacing: 0; background: transparent; border: none;")
        subtitle_lbl = QLabel(subtitle)
        subtitle_lbl.setWordWrap(True)
        subtitle_lbl.setStyleSheet("font-size: 12px; color: #66748D; font-weight: 400; letter-spacing: 0; background: transparent; border: none;")
        text_col.addWidget(title_lbl)
        text_col.addWidget(subtitle_lbl)
        header_layout.addLayout(text_col, 1)

        # Aviso de bloqueado/editable (ver _set_badge_bloqueo); queda oculto en
        # las secciones que nunca se deshabilitan.
        badge_bloqueo = QFrame()
        badge_bloqueo.setObjectName("badgeBloqueo")
        badge_bloqueo.setStyleSheet("QFrame#badgeBloqueo { background: transparent; border: none; }")
        badge_layout = QHBoxLayout(badge_bloqueo)
        badge_layout.setContentsMargins(8, 3, 10, 3)
        badge_layout.setSpacing(5)
        badge_icon_lbl = QLabel()
        badge_icon_lbl.setStyleSheet("background: transparent; border: none;")
        badge_text_lbl = QLabel()
        badge_text_lbl.setStyleSheet("font-size: 11px; font-weight: 600; letter-spacing: 0; background: transparent; border: none;")
        badge_layout.addWidget(badge_icon_lbl)
        badge_layout.addWidget(badge_text_lbl)
        badge_bloqueo.setVisible(False)
        header_layout.addWidget(badge_bloqueo, 0, Qt.AlignmentFlag.AlignVCenter)
        if key in ('justtime', 'cm'):
            # Van lado a lado: mismo alto de encabezado aunque el subtítulo ocupe 1 o 2 líneas
            header.setFixedHeight(78)
        if not hasattr(self, '_badges_bloqueo'):
            self._badges_bloqueo = {}
        self._badges_bloqueo[key] = {
            'frame': badge_bloqueo, 'icon': badge_icon_lbl, 'texto': badge_text_lbl,
        }

        card_layout.addWidget(header)

        fields_frame = QFrame(card)
        fields_frame.setObjectName("sectionFields")
        fields_frame.setStyleSheet(
            "QFrame#sectionFields { background-color: #FFFFFF; border: none; "
            "border-bottom-left-radius: 11px; border-bottom-right-radius: 11px; }")
        fields_layout = QVBoxLayout(fields_frame)
        fields_layout.setContentsMargins(18, 16, 18, 18)
        fields_layout.setSpacing(14)
        card_layout.addWidget(fields_frame)

        for row_fields in rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(14)
            fields_layout.addLayout(row_layout)
            hay_campo_flexible = False
            for f_name, f_type in row_fields:
                field_box = QVBoxLayout()
                field_box.setSpacing(6)
                row_layout.addLayout(field_box, 0 if f_name in _ANCHO_FIJO else 1)
                if f_name == 'TIPO DE FACTURACION':
                    self._btn_corregir_tipo_fact = self._crear_boton_corregir_tipo_facturacion()
                    field_box.addWidget(self._btn_corregir_tipo_fact)
                texto_etiqueta = _ETIQUETAS_CAMPO.get(f_name, f_name)
                if f_name in _CAMPOS_OBLIGATORIOS:
                    label = QLabel(f'{texto_etiqueta} <span style="color:#A8453F;">*</span>')
                else:
                    label = QLabel(texto_etiqueta)
                label.setStyleSheet("background: transparent; border: none;")
                field_box.addWidget(label)
                widget = self._create_widget(f_name, f_type)
                field_box.addWidget(widget)
                if f_name == 'TIPO DE SERVICIO':
                    field_box.addLayout(self._crear_checks_tipo_servicio(widget))
                if f_name in _ANCHO_FIJO:
                    widget.setMaximumWidth(_ANCHO_FIJO[f_name])
                else:
                    hay_campo_flexible = True
                    # Ignored: el ancho lo da solo el stretch, así los campos de la fila quedan parejos
                    widget.setSizePolicy(QSizePolicy.Policy.Ignored, widget.sizePolicy().verticalPolicy())
                row_layout.setAlignment(field_box, Qt.AlignmentFlag.AlignTop)
            if not hay_campo_flexible:
                row_layout.addStretch()

        return card

    # ------------------------------------------------------------------
    # Asistente por pasos + resumen lateral
    # ------------------------------------------------------------------
    _RESUMEN_CAMPOS = (
        ("RUT", "RUT"), ("Razón social", "RAZÓN SOCIAL"), ("VIN", "VIN"), ("Modelo", "MODELO"),
        ("Ejecutivo", "EJECUTIVO"), ("Estado", "ESTADO COMERCIAL"), ("Contrato", "FORMA DE CONTRATO"),
        ("Facturación", "TIPO DE FACTURACION"), ("Activación", "ESTADO DE ACTIVACIÓN ACTUAL"),
        ("Fecha de entrega", "ESTADO DE ENTREGA"),
    )
    # Paso (índice de self.tabs) donde vive cada campo obligatorio
    _PASO_DE_CAMPO = {'RUT': 0, 'RAZÓN SOCIAL': 0, 'VIN': 0, 'CHASIS': 0}

    def _construir_cuerpo_pasos(self, contenido_layout):
        pasos = [("Empresa & Unidad", "Cliente y camión"), ("Comercial", "Contrato y facturación"),
                 ("JustTime & CM", "Según facturación")]
        if self._MOSTRAR_PASO_OPERACIONES:
            pasos.append(("Operaciones", "Estado y flota"))
        elif self.tabs.count() > len(pasos):
            # El paso queda fuera del recorrido, no se elimina
            self.tabs.setTabVisible(len(pasos), False)

        contenedor = contenido_layout.parentWidget()
        barra = QFrame(contenedor)
        barra.setObjectName("pasosForm")
        barra.setStyleSheet("QFrame#pasosForm { background-color: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 12px; }")
        lay_barra = QHBoxLayout(barra)
        lay_barra.setContentsMargins(6, 6, 6, 6)
        lay_barra.setSpacing(4)
        self._botones_paso = []
        for i, (titulo, sub) in enumerate(pasos):
            btn = QPushButton(barra)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(52)
            lay = QHBoxLayout(btn)
            lay.setContentsMargins(12, 6, 12, 6)
            lay.setSpacing(10)
            num = QLabel(str(i + 1))
            num.setFixedSize(26, 26)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col = QVBoxLayout()
            col.setSpacing(0)
            t = QLabel(titulo)
            st = QLabel(sub)
            col.addWidget(t)
            col.addWidget(st)
            lay.addWidget(num)
            lay.addLayout(col)
            lay.addStretch()
            for w in (num, t, st):
                w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            btn.clicked.connect(lambda _=False, idx=i: self._ir_a_paso(idx))
            btn._partes = (num, t, st)
            self._botones_paso.append(btn)
            lay_barra.addWidget(btn, 1)
        contenido_layout.addWidget(barra)

        fila = QHBoxLayout()
        fila.setSpacing(16)
        izquierda = QVBoxLayout()
        izquierda.setSpacing(14)
        izquierda.addWidget(self.tabs, 1)

        self._nav_layout = QHBoxLayout()
        self._nav_layout.setSpacing(8)
        estilo_sec = (
            "QPushButton { background-color: #FFFFFF; color: #0F1B33; border: 1px solid #DCE3EC; "
            "padding: 0 18px; min-height: 40px; border-radius: 8px; font-size: 13px; font-weight: 600; } "
            "QPushButton:hover { background-color: #F1F4F9; } "
            "QPushButton:disabled { color: #A9B4C6; background-color: #F5F7FA; }")
        self._btn_paso_atras = QPushButton(" Atrás")
        self._btn_paso_atras.setIcon(qta.icon('fa5s.arrow-left', color='#0F1B33'))
        self._btn_paso_siguiente = QPushButton("Siguiente ")
        self._btn_paso_siguiente.setIcon(qta.icon('fa5s.arrow-right', color='#0F1B33'))
        self._btn_paso_siguiente.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        for b in (self._btn_paso_atras, self._btn_paso_siguiente):
            b.setStyleSheet(estilo_sec)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setAutoDefault(False)
            b.setDefault(False)
        self._btn_paso_atras.clicked.connect(lambda: self.tabs.setCurrentIndex(self.tabs.currentIndex() - 1))
        self._btn_paso_siguiente.clicked.connect(lambda: self._ir_a_paso(self.tabs.currentIndex() + 1))
        self._nav_layout.addWidget(self._btn_paso_atras)
        self._nav_layout.addWidget(self._btn_paso_siguiente)
        self._nav_layout.addStretch()
        izquierda.addLayout(self._nav_layout)
        fila.addLayout(izquierda, 1)

        resumen = QFrame(contenedor)
        resumen.setObjectName("resumenForm")
        resumen.setFixedWidth(290)
        resumen.setStyleSheet("QFrame#resumenForm { background-color: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 12px; }")
        lay_res = QVBoxLayout(resumen)
        lay_res.setContentsMargins(18, 16, 18, 16)
        lay_res.setSpacing(10)
        titulo_res = QLabel("Resumen")
        titulo_res.setStyleSheet("font-size: 14px; font-weight: 700; color: #0F1B33; letter-spacing: 0; background: transparent; border: none;")
        lay_res.addWidget(titulo_res)
        self._resumen_valores = {}
        for etiqueta, campo in self._RESUMEN_CAMPOS:
            f = QHBoxLayout()
            f.setSpacing(8)
            l = QLabel(etiqueta)
            l.setStyleSheet("font-size: 12px; font-weight: 500; color: #66748D; letter-spacing: 0; background: transparent; border: none;")
            v = QLabel("—")
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            v.setWordWrap(True)
            v.setStyleSheet("font-size: 12px; font-weight: 600; color: #0F1B33; letter-spacing: 0; background: transparent; border: none;")
            f.addWidget(l)
            f.addWidget(v, 1)
            lay_res.addLayout(f)
            self._resumen_valores[campo] = v
        lay_res.addStretch()
        self._resumen_barra = QProgressBar()
        self._resumen_barra.setTextVisible(False)
        self._resumen_barra.setFixedHeight(6)
        self._resumen_barra.setStyleSheet(
            "QProgressBar { background-color: #E8ECF4; border: none; border-radius: 3px; } "
            f"QProgressBar::chunk {{ background-color: {self._CORP}; border-radius: 3px; }}")
        self._resumen_hint = QLabel("")
        self._resumen_hint.setWordWrap(True)
        self._resumen_hint.setStyleSheet("font-size: 11px; font-weight: 500; color: #66748D; letter-spacing: 0; background: transparent; border: none;")
        lay_res.addWidget(self._resumen_barra)
        lay_res.addWidget(self._resumen_hint)
        fila.addWidget(resumen)
        contenido_layout.addLayout(fila, 1)

        self.tabs.currentChanged.connect(self._sincronizar_pasos)
        self._sincronizar_pasos(self.tabs.currentIndex())

    def _sincronizar_pasos(self, actual):
        n = len(getattr(self, '_botones_paso', []))
        for i, btn in enumerate(getattr(self, '_botones_paso', [])):
            num, t, st = btn._partes
            if i == actual:
                btn.setStyleSheet("QPushButton { background-color: #F7F8FC; border: 1px solid #DCE3EC; border-radius: 9px; text-align: left; }")
                num.setStyleSheet(f"background-color: {self._CORP}; color: white; border-radius: 13px; font-size: 12px; font-weight: 700; letter-spacing: 0;")
                t.setStyleSheet("font-size: 13px; font-weight: 700; color: #0F1B33; letter-spacing: 0; background: transparent;")
            else:
                hecho = i < actual
                btn.setStyleSheet("QPushButton { background: transparent; border: 1px solid transparent; border-radius: 9px; text-align: left; } QPushButton:hover { background-color: #F7F8FC; }")
                num.setStyleSheet(
                    f"background-color: {'#EEF2F6' if hecho else '#FFFFFF'}; color: {self._CORP if hecho else '#66748D'}; "
                    "border: 1px solid #DCE3EC; border-radius: 13px; font-size: 12px; font-weight: 700; letter-spacing: 0;")
                t.setStyleSheet("font-size: 13px; font-weight: 600; color: #66748D; letter-spacing: 0; background: transparent;")
            st.setStyleSheet("font-size: 11px; font-weight: 400; color: #8A97AB; letter-spacing: 0; background: transparent;")
        self._btn_paso_atras.setEnabled(actual > self._primer_paso)
        self._btn_paso_siguiente.setVisible(actual < n - 1)
        self._actualizar_bloqueo_siguiente()

    def _faltantes_paso(self, paso):
        return [c for c in sorted(_CAMPOS_OBLIGATORIOS)
                if c in self.inputs and self._PASO_DE_CAMPO.get(c) == paso and not self._valor_widget(c)]

    def _actualizar_bloqueo_siguiente(self):
        if not hasattr(self, '_btn_paso_siguiente'):
            return
        faltan = self._faltantes_paso(self.tabs.currentIndex())
        self._btn_paso_siguiente.setEnabled(not faltan)
        self._btn_paso_siguiente.setToolTip(
            "Completa los campos obligatorios para continuar: " + ", ".join(faltan) if faltan else "")

    def _ir_a_paso(self, destino):
        actual = self.tabs.currentIndex()
        if destino > actual:
            for paso in range(actual, destino):
                faltan = self._faltantes_paso(paso)
                if faltan:
                    self.tabs.setCurrentIndex(paso)
                    QMessageBox.warning(
                        self, "Campos obligatorios",
                        "Completa los siguientes campos para continuar:\n- " + "\n- ".join(faltan))
                    return
        self.tabs.setCurrentIndex(destino)

    def _conectar_resumen(self):
        campos = [c for _, c in self._RESUMEN_CAMPOS] + [c for c in sorted(_CAMPOS_OBLIGATORIOS)]
        for campo in dict.fromkeys(campos):
            w = self.inputs.get(campo)
            if isinstance(w, QComboBox):
                w.currentTextChanged.connect(self._actualizar_resumen)
            elif isinstance(w, QLineEdit):
                w.textChanged.connect(self._actualizar_resumen)
        self._actualizar_resumen()

    def _sincronizar_estado_con_contrato(self, *_args):
        """Acota las opciones de ESTADO COMERCIAL según la unidad: con FORMA
        DE CONTRATO "Sin Contrato" solo "Revisar"; al editar, con ESTADO DE
        ACTIVACIÓN ACTUAL "CONECTADO" no se ofrece "Activación Pendiente" y
        con "ACTIVANDO" no se ofrece "Vigente". El valor ya cargado se
        conserva. No actúa en el flujo que fuerza "Activación Pendiente".
        Vive en el mixin (05-10-2026) porque _setup_ui la conecta también en
        ComercialAgregarDialog, que la usan JustTime, Contratos y Facturación
        Manual."""
        if self._forzar_activacion_pendiente or 'ESTADO COMERCIAL' not in self.inputs:
            return
        combo = self.inputs['ESTADO COMERCIAL']
        sin_contrato = self._valor_widget('FORMA DE CONTRATO').strip().upper() == 'SIN CONTRATO'
        activacion = self._valor_widget('ESTADO DE ACTIVACIÓN ACTUAL').strip().upper() if 'ESTADO DE ACTIVACIÓN ACTUAL' in self.inputs else ''
        actual = combo.currentText()
        if sin_contrato:
            nuevo = actual if actual and actual not in ('Activación Pendiente', '-') else 'Revisar'
            items = ['Revisar'] if nuevo == 'Revisar' else ['Revisar', nuevo]
        else:
            bloqueados = {'Vigente', 'Vencido', 'Baja', 'Baja Solicitada'} if getattr(self, '_estado_alta_restringido', False) else set()
            if self._restringir_vigentes:
                bloqueados |= {'Vencido', 'Activación Pendiente'}
            if self.modo_edicion and self._restringir_activacion and actual in ('Revisar', 'Activación Pendiente'):
                # Unidad que aún no pasó por activación (Nuevas oportunidades):
                # no puede saltarse Activación Pendiente.
                bloqueados |= {'Vigente', 'Vencido', 'Baja', 'Baja Solicitada'}
            if self.modo_edicion and activacion == 'CONECTADO':
                bloqueados.add('Activación Pendiente')
            elif self.modo_edicion and activacion == 'ACTIVANDO':
                bloqueados.add('Vigente')
            items = [v for v in self.dropdown_options.get('ESTADO COMERCIAL', []) if v != '-' and v not in bloqueados]
            if actual and actual not in items:
                items.append(actual)
            nuevo = actual
        if [combo.itemText(i) for i in range(combo.count())] == items and nuevo == actual:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(items)
        combo.setCurrentText(nuevo)
        combo.blockSignals(False)
        if nuevo != actual:
            self._recalcular_etapa_gestion()
        self._actualizar_resumen()

    def _sincronizar_activacion_con_estado_comercial(self, *_args):
        """Al crear una unidad, "Activación Pendiente" la manda a activar:
        ESTADO DE ACTIVACIÓN ACTUAL pasa de "No aplica" a "Activando" (igual
        que en el flujo de Nuevas oportunidades, ver _aplicar_restriccion_activacion)
        y vuelve a "No aplica" si se cambia a otro estado sin haberlo tocado a
        mano. No actúa al editar, en el alta desde Vista General ni cuando la
        activación ya trae un valor real (p. ej. un registro importado). Operaciones
        está siempre de solo lectura en el formulario de alta, pero el cambio se aplica igual."""
        if self._forzar_activacion_pendiente or 'ESTADO DE ACTIVACIÓN ACTUAL' not in self.inputs:
            return
        if self.modo_edicion and not self._restringir_activacion:
            return
        activacion = self.inputs['ESTADO DE ACTIVACIÓN ACTUAL']
        # Al editar desde Nuevas oportunidades la pestaña Operaciones está
        # bloqueada, pero la activación igual debe acompañar al estado.
        if getattr(self, '_restringir_alta_desde_general', False) \
                or self._valor_widget('FORMA DE CONTRATO').strip().upper() == 'SIN CONTRATO':
            return
        estado = self.inputs['ESTADO COMERCIAL'].currentText().strip().upper()
        actual = activacion.currentText().strip().upper()
        if estado in ('ACTIVACIÓN PENDIENTE', 'ACTIVACION PENDIENTE'):
            if actual == 'NO APLICA':
                activacion.setCurrentText('Activando')
                self._activacion_auto = True
        elif getattr(self, '_activacion_auto', False):
            if actual == 'ACTIVANDO':
                activacion.setCurrentText('No aplica')
            self._activacion_auto = False

    def _actualizar_resumen(self, *_args):
        if not hasattr(self, '_resumen_valores'):
            return
        for _, campo in self._RESUMEN_CAMPOS:
            valor = self._valor_widget(campo) if campo in self.inputs else ''
            self._resumen_valores[campo].setText(valor if valor and valor != '-' else "—")
        obligatorios = [c for c in _CAMPOS_OBLIGATORIOS if c in self.inputs]
        completos = sum(1 for c in obligatorios if self._valor_widget(c))
        self._resumen_barra.setMaximum(max(1, len(obligatorios)))
        self._resumen_barra.setValue(completos)
        self._resumen_hint.setText(f"{completos} de {len(obligatorios)} campos obligatorios completos")
        self._actualizar_bloqueo_siguiente()

    def _ir_a_paso_campo(self, campo):
        paso = self._PASO_DE_CAMPO.get(campo)
        if paso is not None:
            self.tabs.setCurrentIndex(paso)

    def _fit_to_screen(self):
        """Ajusta el tamaño del diálogo al de su contenido y lo centra dentro
        del área útil de la pantalla (sin superponerse a la barra de tareas
        de Windows), sea cual sea la resolución del equipo. Se llama después
        del primer show() (vía showEvent), ya con el layout resuelto, para
        que el tamaño medido sea el real y no una estimación previa."""
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        width = min(self.width(), avail.width() - 40)
        height = min(self.height(), avail.height() - 40)
        self.resize(width, height)
        self.move(
            avail.x() + max(0, (avail.width() - width) // 2),
            avail.y() + max(0, (avail.height() - height) // 2),
        )

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._fit_to_screen)

    def _create_widget(self, field_name, field_type):
        if field_type == 'combo':
            w = ComboTarjeta(field_name.title())
            if field_name == 'TIPO DE CM':
                # "-" quitado de las opciones visibles (25-09-2026, a pedido
                # explícito: "eliminar la opción para escoger '-'" en varios
                # combos) -- sigue siendo un valor válido si ya existe en
                # datos reales/el default inicial (ver _set_combo_valor_precargado
                # más abajo, que lo re-agrega solo cuando hace falta
                # mostrarlo, nunca como opción "de catálogo" para elegir a mano).
                w.addItems([v for v in TIPO_CM_OPCIONES if v != '-'])
            elif field_name == 'ESTADO DEL CM':
                w.addItems(ESTADO_CM_OPCIONES)
            elif field_name == 'CONTRATO CREADO EN JUSTTIME':
                # Lista cerrada (30-09-2026): el texto libre generó variantes
                # del mismo estado; "-" = no aplica
                w.addItems(JUSTTIME_ESTADO_OPCIONES)
            else:
                # "-" quitado de MODELO/FORMA DE CONTRATO/TIPO DE SERVICIO
                # (mismo criterio que TIPO DE CM arriba); ESTADO COMERCIAL/
                # ESTADO DE ACTIVACIÓN ACTUAL nunca tuvieron "-" en su
                # catálogo, no se ven afectados.
                opciones = [v for v in self.dropdown_options.get(field_name, []) if v != '-']
                if field_name == 'TIPO DE SERVICIO':
                    # Solo el plan base: CIV y SZ se eligen con los checks de abajo
                    opciones = list(dict.fromkeys(_partir_tipo_servicio(v)[0] for v in opciones))
                w.addItems(opciones)
            ThemeManager.apply_combo_box(w)
            if field_name in _DEFAULTS_INICIALES:
                # _set_combo_valor_precargado (no setCurrentText directo):
                # el default de MODELO/TIPO DE SERVICIO/TIPO DE CM sigue
                # siendo "-" (sin VIN/sin elegir todavía) aunque ya no esté
                # en la lista de arriba -- se agrega como único ítem "extra"
                # solo mientras sigue siendo el valor vigente, en vez de
                # quedar siempre disponible como opción de catálogo.
                self._set_combo_valor_precargado(w, _DEFAULTS_INICIALES[field_name])

        elif field_type == 'tipo_facturacion':
            # TIPO DE FACTURACION (pestaña "JustTime & CM"): combo NO editable
            # que muestra el texto amigable (TIPO_FACTURACION_DISPLAY_MAP) pero
            # cuyo valor real a guardar se obtiene siempre vía
            # TIPO_FACTURACION_DISPLAY_A_REAL en _valor_widget -- no se guarda
            # nunca el texto amigable tal cual. Es el disparador de ETAPA
            # GESTIÓN (ver _on_tipo_facturacion_editado/_set_tipo_facturacion_actual)
            # y de la habilitación de los bloques JustTime/CM.
            w = ComboTarjeta("Tipo de facturación")
            # "-" quitado de las opciones (25-09-2026, mismo pedido) -- ver
            # _ORDEN_TIPO_FACTURACION_SIN_GUION, reutilizado también en
            # _sincronizar_tipo_facturacion_con_forma_contrato.
            w.addItems([TIPO_FACTURACION_DISPLAY_MAP[v] for v in _ORDEN_TIPO_FACTURACION_SIN_GUION])
            ThemeManager.apply_combo_box(w)
            texto_actual = TIPO_FACTURACION_DISPLAY_MAP.get(self._tipo_facturacion_actual, self._tipo_facturacion_actual)
            self._set_combo_valor_precargado(w, texto_actual)

        elif field_type == 'combo_editable':
            # FLOTA VC / FLOTA VC 2 (1000+ ítems) conservan el desplegable
            # nativo: la tarjeta reconstruye toda la lista en cada apertura
            w = QComboBox() if field_name.startswith('FLOTA VC') else ComboTarjeta(field_name.title())
            w.setEditable(True)
            ThemeManager.apply_combo_box(w)
            # Buscador inteligente sin distinguir mayúsculas/minúsculas
            w.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            w.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

            if field_name == 'INDUSTRIA':
                from src.core.constants import INDUSTRIA_MAP
                inds_unicas = sorted(list(set(INDUSTRIA_MAP.values())))
                # Sin anteponer "" (25-09-2026, a pedido explícito: "eliminar
                # la opción para escoger '-'" -- acá el placeholder era un
                # ítem en blanco, no un guion, mismo criterio). Combo
                # editable: setCurrentText('NO DEFINIDA') funciona igual
                # aunque ese texto no esté en la lista (no hace falta
                # _set_combo_valor_precargado, ese helper es solo para
                # combos NO editables).
                w.addItems(inds_unicas)
                w.setCurrentText(_DEFAULTS_INICIALES.get('INDUSTRIA', ''))
            elif field_name == 'EJECUTIVO':
                w.addItems([""] + self._ejecutivos_todos)
            else:
                # FLOTA VC / FLOTA VC 2 (1000+ flotas): se llenan al final de
                # _setup_ui (_poblar_combos_flota). Con los ítems ya cargados,
                # cada cambio de contenedor durante el armado volvía a aplicar
                # estilos y recalcular la lista completa (0,5-2 s por paso).
                self._combos_flota_pendientes.append((w, field_name))
                # Ancho y alto de fila sin recorrer las miles de flotas: cada
                # cambio de estilo (validación, reinicio, modo oscuro) costaba
                # ~250 ms por combo
                w.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
                w.setMinimumContentsLength(16)
                if isinstance(w.view(), QListView):
                    w.view().setUniformItemSizes(True)

        elif field_type == 'readonly':
            w = QLineEdit()
            w.setReadOnly(True)
            if field_name == 'CHASIS': w.setPlaceholderText("Auto: últimos 7 del VIN")
            if field_name == 'TÉRMINO CONTRATO':
                w.setPlaceholderText("Auto: Calculado al guardar")
                w.setText("-")  # default visible: sin INICIO CONTRATO/DURACIÓN aún no hay término que calcular

        elif field_type == 'date':
            w = QLineEdit()
            w.setPlaceholderText("DD-MM-YYYY")  # Formato chileno
            # Dígitos y guion como tecleo directo (nunca letras). El validador
            # anterior solo admitía dígitos: una vez que el campo mostraba el
            # default "-" (dato aún no informado, mismo criterio que ya usa
            # DURACIÓN (MESES)/TÉRMINO CONTRATO en el resto del proyecto, ver
            # DataFrameFormatter.calcular_termino), cualquier tecleo quedaba
            # bloqueado porque el resultado ("-1", "1-", etc.) nunca calzaba
            # con "solo dígitos". _on_inicio_contrato_changed ya descarta
            # cualquier guion al reconstruir el formato DD-MM-YYYY, así que
            # ensanchar el validador no relaja nada más.
            w.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9\-]{0,10}")))
            if field_name in ('INICIO CONTRATO', 'FECHA DE BAJA', 'ESTADO DE ENTREGA', 'INICIO', 'TERMINO', 'FECHA INICIO CM', 'FECHA TERMINO CM'):
                w.setText("-")
        else:
            w = QLineEdit()
            if field_name in ('N CONTRATO 3PC', 'PAGO CM'):
                w.setText("-")
            if field_name == 'PAGO CM':
                # Solo dígitos tecleables (25-09-2026, a pedido explícito:
                # "solo se pueda colocar número"). El validador solo
                # restringe el TECLEO del usuario, no setText() programático
                # -- el default "-" de arriba y el re-formateo automático a
                # "$X.XXX.XXX" en _on_pago_cm_changed siguen funcionando
                # igual. Antes se limpiaba el texto no numérico recién
                # DESPUÉS de escribirlo (se veía parpadear); ahora una letra
                # directamente no se puede escribir.
                w.setValidator(QRegularExpressionValidator(QRegularExpression(r"[0-9]*")))
            elif field_name == 'DURACIÓN (MESES)':
                # Solo dígitos o un guion: cualquier otro carácter no se puede
                # escribir. Si el campo muestra "-" y se teclea un número, el
                # guion se descarta para no obligar a borrarlo antes. Hasta dos
                # dígitos: el tope es DURACION_MAXIMA_MESES (99)
                w.setValidator(QRegularExpressionValidator(QRegularExpression(r"-?[0-9]{0,2}")))
                w.textEdited.connect(lambda texto, campo=w: self._quitar_guion_si_hay_numero(campo, texto))
            elif field_name == 'CDB':
                # CDB comercial: hasta 10 dígitos (o "-" si no se conoce)
                w.setValidator(QRegularExpressionValidator(QRegularExpression(r"-?[0-9]{0,10}")))
                w.textEdited.connect(lambda texto, campo=w: self._quitar_guion_si_hay_numero(campo, texto))
            elif field_name == 'VIN':
                # Solo letras A-Z (sin tildes ni ñ) y números, siempre en
                # mayúsculas; también limpia lo que se pegue.
                w.textEdited.connect(lambda texto, campo=w: self._normalizar_vin_escrito(campo, texto))

        w.setMinimumHeight(40)
        self.inputs[field_name] = w
        return w

    @staticmethod
    def _quitar_guion_si_hay_numero(campo, texto):
        if len(texto) > 1 and texto.startswith('-'):
            campo.setText(texto.lstrip('-'))

    @staticmethod
    def _normalizar_vin_escrito(campo, texto):
        limpio = re.sub(r'[^A-Za-z0-9]', '', texto).upper()
        if limpio != texto:
            cursor = campo.cursorPosition() - (len(texto) - len(limpio))
            campo.setText(limpio)
            campo.setCursorPosition(max(0, cursor))

    # ------------------------------------------------------------------
    # Autocompletado a partir del RUT
    # ------------------------------------------------------------------
    def _on_rut_completado(self):
        try:
            self._autocompletar_por_rut()
        finally:
            self._actualizar_bloqueo_razon_social()
            self._actualizar_bloqueo_cdb()

    def _actualizar_bloqueo_cdb(self):
        """El CDB comercial es editable en todos los casos, salvo cuando el
        RUT ya tiene un único CDB conocido: entonces debe coincidir con el del
        RUT y no se cambia desde aquí. Con un RUT nuevo o con varios CDB
        queda libre."""
        campo = self.inputs.get('CDB')
        if campo is None:
            return
        entry = self._rut_lookup.get(self._normalizar_rut(self.inputs['RUT'].text().strip()))
        cdbs = entry['CDB'] if entry else []
        bloquear = len(cdbs) == 1
        if getattr(self, '_cdb_bloqueado', False) and not bloquear:
            campo.clear()
        self._cdb_bloqueado = bloquear
        if bloquear and campo.text().strip() != cdbs[0]:
            campo.setText(cdbs[0])
        campo.setEnabled(not bloquear)
        campo.setToolTip("Debe coincidir con el CDB de este RUT." if bloquear else "")

    def _actualizar_bloqueo_razon_social(self):
        """Al editar una unidad, si su RUT ya existe con una única razón
        social, ese nombre es del cliente (todas las unidades de ese RUT) y no
        se cambia desde aquí: se edita en Administración → Clientes. Cambiar
        el RUT mueve solo esta unidad: con un RUT conocido el nombre se
        autocompleta y queda bloqueado; con uno nuevo queda libre."""
        campo = self.inputs.get('RAZÓN SOCIAL')
        if campo is None:
            return
        entry = self._rut_lookup.get(self._normalizar_rut(self.inputs['RUT'].text().strip()))
        bloquear = bool(entry) and len(entry['RAZÓN SOCIAL']) == 1
        if getattr(self, '_razon_bloqueada', False) and not bloquear:
            # Pasó de un RUT con nombre a uno sin nombre conocido: se vacía
            # para no dejar el nombre de otro cliente en el RUT nuevo.
            campo.clear()
        self._razon_bloqueada = bloquear
        campo.setEnabled(not bloquear)
        if bloquear:
            campo.setToolTip("Este RUT ya tiene nombre: se cambia para todas sus unidades en Administración → Clientes.")

    def _autocompletar_por_rut(self):
        """En vivo, con cada cambio en el campo RUT (tipeo o pegado),
        autocompleta RAZÓN SOCIAL y CDB si ese RUT tiene un único valor
        conocido en Comercial (un mismo RUT puede tener varias unidades; si
        hay varias RAZÓN SOCIAL/CDB distintas para el mismo RUT -- datos
        inconsistentes -- no se autocompleta nada, para no sobrescribir con
        un valor arbitrario: se deja una pista visual en el tooltip del
        campo). INDUSTRIA se autocompleta siempre con la más frecuente
        (moda) para ese RUT, editable por el usuario si corresponde otra.
        Para EJECUTIVO: si hay uno solo lo autocompleta; si hay más de uno,
        los deja disponibles como opciones del combo (o se puede escribir
        uno nuevo) en vez de imponer uno. Todo opcional/editable: si el RUT
        es nuevo (no existe en Comercial) no cambia nada y el usuario
        completa todo a mano."""
        rut = self.inputs['RUT'].text().strip()
        entry = self._rut_lookup.get(self._normalizar_rut(rut)) if rut else None
        if not entry:
            return

        razones = entry['RAZÓN SOCIAL']
        campo_razon = self.inputs['RAZÓN SOCIAL']
        if len(razones) == 1:
            campo_razon.setText(razones[0])
            campo_razon.setToolTip("")
        elif len(razones) > 1:
            # Dato inconsistente en Comercial (mismo RUT con más de una razón
            # social registrada): no se elige una al azar, se avisa y se deja
            # que el usuario decida.
            campo_razon.setToolTip("Este RUT tiene varias Razones Sociales registradas en Comercial:\n- " + "\n- ".join(razones))

        cdbs = entry['CDB']
        if len(cdbs) == 1:
            # setText dispara textChanged -> _actualizar_flota_vc_por_cdb
            # automáticamente (misma conexión que si el CDB se escribe/pega
            # a mano), así que no hace falta llamarlo aquí de nuevo.
            self.inputs['CDB'].setText(cdbs[0])

        industria_moda = entry['INDUSTRIA_MODA']
        if industria_moda:
            self.inputs['INDUSTRIA'].setCurrentText(industria_moda)

        ejecutivos = entry['EJECUTIVO']
        combo_ejecutivo = self.inputs['EJECUTIVO']
        combo_ejecutivo.blockSignals(True)
        combo_ejecutivo.clear()
        combo_ejecutivo.addItems([""] + ejecutivos + [e for e in self._ejecutivos_todos if e not in ejecutivos])
        combo_ejecutivo.setCurrentText(ejecutivos[0] if len(ejecutivos) == 1 else "")
        combo_ejecutivo.blockSignals(False)

    def _actualizar_flota_vc_por_cdb(self):
        """FLOTA VC (opcional) se filtra a las flotas ya asociadas al CDB
        ingresado; si el CDB no tiene flotas conocidas (o está vacío),
        vuelve a ofrecer el listado completo. FLOTA VC 2 no se toca:
        también es opcional pero nunca se autocompleta ni se filtra."""
        cdb = self.inputs['CDB'].text().strip()
        opciones = self._flota_by_cdb.get(cdb.upper()) if cdb else None

        combo_flota = self.inputs['FLOTA VC']
        texto_actual = combo_flota.currentText()
        combo_flota.blockSignals(True)
        combo_flota.clear()
        combo_flota.addItems([""] + (opciones if opciones else self.flotas_unicas))
        combo_flota.setCurrentText(texto_actual)
        combo_flota.blockSignals(False)

    # ------------------------------------------------------------------
    # ETAPA GESTIÓN: recálculo automático (reutiliza la regla central de
    # negocio) + edición manual (16-09-2026)
    # ------------------------------------------------------------------
    def _aplicar_color_etapa_gestion(self, valor):
        """Colorea el texto del combo ETAPA GESTIÓN igual que la tabla de
        Unidades (general.py): solo color de texto en negrita, sin fondo,
        usando la misma paleta ETAPA_GESTION_COLORES (sin crear una nueva)."""
        color = ETAPA_GESTION_COLORES.get(str(valor).strip().upper())
        widget = self.inputs['ETAPA GESTIÓN']
        if color:
            widget.setStyleSheet(f"QComboBox {{ color: {color}; font-weight: bold; }}")
        else:
            # Valor legado/no reconocido (ver _set_combo_valor_precargado):
            # se preserva tal cual, sin forzar un color que no le corresponde.
            widget.setStyleSheet("")

    def _set_etapa_gestion_widget(self, valor):
        """Selecciona `valor` en el combo ETAPA GESTIÓN (deshabilitado, sin
        interacción de usuario posible) y aplica su color. Mismo criterio de
        preservar valores legados que _set_combo_valor_precargado: si `valor`
        no está entre las 2 opciones oficiales, se agrega tal cual en vez de
        descartarlo."""
        widget = self.inputs['ETAPA GESTIÓN']
        widget.blockSignals(True)
        self._set_combo_valor_precargado(widget, str(valor))
        widget.blockSignals(False)
        self._aplicar_color_etapa_gestion(valor)

    def _recalcular_etapa_gestion(self, *_args):
        """Recalcula ETAPA GESTIÓN reutilizando tal cual la única fuente de
        verdad de esta regla de negocio (DataFrameFormatter.calcular_etapa_gestion_esperada),
        sin reimplementarla en la UI. Se llama al cambiar cualquiera de sus
        3 disparadores (ESTADO COMERCIAL, ESTADO DE ACTIVACIÓN ACTUAL --
        agregado 21-09-2026 junto con la matriz de 2 ejes -- y TIPO DE
        FACTURACION). El combo está siempre deshabilitado (22-09-2026, a
        pedido explícito: la regla de negocio debe respetarse siempre, sin
        importar desde dónde se abra el formulario), así que este es el
        único lugar que cambia su valor. `*_args` absorbe el argumento que
        Qt pasa en `currentTextChanged` (el texto nuevo), que no se necesita
        acá porque se vuelve a leer el valor actual directamente del widget."""
        row = {
            COL_ESTADO_COMERCIAL: self.inputs['ESTADO COMERCIAL'].currentText(),
            COL_ESTADO_ACTIVACION: self.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].currentText(),
            COL_TIPO_FACTURACION: self._tipo_facturacion_actual,
            COL_ETAPA_GESTION: self.inputs['ETAPA GESTIÓN'].currentText(),
        }
        nueva_etapa = DataFrameFormatter.calcular_etapa_gestion_esperada(row)
        self._set_etapa_gestion_widget(nueva_etapa)

    def _aplicar_restriccion_activacion(self, forzar_activacion_pendiente):
        """Modo restringido al editar una unidad desde "Por gestionar" o
        "Gestionar Bajas" (ver `restringir_activacion` en __init__). Deja
        SIEMPRE de solo lectura toda la pestaña Operaciones, sin importar el
        tipo de unidad (25-09-2026, ajustado a pedido explícito: antes esto
        solo se aplicaba cuando además se forzaba el estado, dejando
        Operaciones editable para el resto de las unidades de "Por
        gestionar" -- ver también _aplicar_restriccion_operaciones_solo_lectura).

        `forzar_activacion_pendiente` (ver el parámetro homónimo en
        __init__) además fuerza ESTADO COMERCIAL="Activación Pendiente"
        (restringiendo el combo a esa única opción) y ESTADO DE ACTIVACIÓN
        ACTUAL="Activando" -- exclusivo de la unidad real "Sin Contrato"/
        "Sin Registro"; el resto de las unidades de "Por gestionar" solo ven
        Operaciones bloqueada, sin que se les fuerce ningún valor.

        ETAPA GESTIÓN no se toca acá: está siempre deshabilitada (ver
        combo_etapa.setEnabled(False) en _setup_ui), sin importar el modo."""
        self._aplicar_restriccion_operaciones_solo_lectura()

        if forzar_activacion_pendiente:
            combo_estado_comercial = self.inputs['ESTADO COMERCIAL']
            combo_estado_comercial.blockSignals(True)
            combo_estado_comercial.clear()
            combo_estado_comercial.addItem('Activación Pendiente')
            combo_estado_comercial.setCurrentText('Activación Pendiente')
            combo_estado_comercial.blockSignals(False)
            combo_estado_comercial.setEnabled(False)

            combo_activacion = self.inputs['ESTADO DE ACTIVACIÓN ACTUAL']
            combo_activacion.setCurrentText('Activando')

    def _aplicar_restriccion_operaciones_solo_lectura(self):
        """Deja de solo lectura toda la pestaña Operaciones (CDB/FLOTA VC/
        FLOTA VC 2/ESTADO DE ACTIVACIÓN ACTUAL/ESTADO DE ENTREGA/FECHA DE
        BAJA), sin forzar ni tocar ningún valor -- separado de
        _aplicar_restriccion_activacion (25-09-2026) porque también lo usa
        el caso "Por gestionar" sin `forzar_activacion_pendiente`. CDB
        agregado 25-09-2026 al moverse de "Empresa" a esta pestaña."""
        self.inputs['ESTADO DE ACTIVACIÓN ACTUAL'].setEnabled(False)
        for campo in ('CDB FLOTA', 'FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ENTREGA', 'FECHA DE BAJA'):
            self.inputs[campo].setEnabled(False)
        # Insignia "🔒 Bloqueado" en el encabezado de la sección (25-09-2026,
        # a pedido explícito: "quiero que cuando esta bloqueada el campo se
        # resalte con algo") -- mismo mecanismo que ya usan JustTime/CM
        # (ver _set_badge_bloqueo), reutilizado acá en vez de inventar un
        # aviso nuevo. Los campos en sí también cambian de color vía QSS
        # (ver QLineEdit:disabled/QComboBox:disabled en _init_form).
        self._set_badge_bloqueo('operativa', False)

    def _aplicar_restriccion_vigentes(self):
        """Modo restringido al editar una unidad desde "Vigentes" (ver
        `restringir_vigentes` en __init__). A diferencia de
        _aplicar_restriccion_activacion, no fuerza ningún valor fijo: solo
        recorta las opciones del combo ESTADO COMERCIAL (una unidad Vigente
        no se marca a mano como "Vencido" -- eso lo decide la fecha de
        TÉRMINO CONTRATO o el botón "Marcar como Vencido" en Vencidos -- ni
        "vuelve" a "Activación Pendiente", el punto de partida del flujo de
        activación) y deja de solo lectura toda la pestaña Operaciones,
        incluido ESTADO DE ACTIVACIÓN ACTUAL, que solo debe cambiar vía las
        acciones de Operaciones (Marcar como CONECTADO/SIN FLOTA/
        DESCONECTADO), nunca a mano desde este formulario. "Baja"/"Baja
        Solicitada" quedan disponibles en el combo: Operaciones debe seguir
        recibiéndolas según sus propias reglas de negocio (ver
        operaciones_services.py) -- ETAPA GESTIÓN se recalcula solo, igual
        que siempre (ver _recalcular_etapa_gestion)."""
        combo_estado_comercial = self.inputs['ESTADO COMERCIAL']
        actual = combo_estado_comercial.currentText()
        for valor in ('Vencido', 'Activación Pendiente'):
            if valor == actual:
                continue
            idx = combo_estado_comercial.findText(valor)
            if idx >= 0:
                combo_estado_comercial.removeItem(idx)

        for campo in ('CDB FLOTA', 'FLOTA VC', 'FLOTA VC 2', 'ESTADO DE ACTIVACIÓN ACTUAL', 'ESTADO DE ENTREGA', 'FECHA DE BAJA'):
            self.inputs[campo].setEnabled(False)
        self._set_badge_bloqueo('operativa', False)

    def _aplicar_restriccion_alta_general(self):
        """Ver `restringir_alta_desde_general` en __init__. Bloquea Comercial
        (excepto EJECUTIVO), Operaciones y JustTime & CM completas, sin
        borrar ningún valor -- una unidad importada de Power BI conserva lo
        que traiga el Excel, solo queda de solo lectura desde este
        formulario. Se llama tanto al final de __init__ como al final de
        _aplicar_datos_iniciales (necesario en modo lote: cada registro nuevo
        pasa por _actualizar_habilitacion_justtime_cm, que reactivaría estos
        mismos campos según TIPO DE FACTURACION si no se re-bloquearan
        después)."""
        for campo in (
            _CAMPOS_COMERCIAL_BLOQUEABLES_ALTA_GENERAL
            + _CAMPOS_OPERACIONES_BLOQUEABLES_ALTA_GENERAL
            + _CAMPOS_JUSTTIME_CM_BLOQUEABLES_ALTA_GENERAL
        ):
            if campo in self.inputs:
                self.inputs[campo].setEnabled(False)

    def _set_tipo_facturacion_actual(self, valor):
        """Punto único para actualizar TIPO DE FACTURACION (siempre el valor
        REAL, ej. 'CLIENTE', nunca el texto amigable del combo) y disparar
        el recálculo de ETAPA GESTIÓN. Único lugar que escribe
        self._tipo_facturacion_actual fuera de la precarga/reset, para no
        tener dos fuentes de verdad independientes (ver
        _on_tipo_facturacion_editado, que es quien lo llama desde el combo
        real de la pestaña "JustTime & CM")."""
        self._tipo_facturacion_actual = valor
        self._recalcular_etapa_gestion()
        self._actualizar_alerta_tipo_facturacion()

    # ------------------------------------------------------------------
    # Pestaña "JustTime & CM": TIPO DE FACTURACION como disparador de la
    # habilitación de bloques, y mapeo FORMA DE CONTRATO -> TIPO DE CM
    # (16-09-2026)
    # ------------------------------------------------------------------
    def _actualizar_habilitacion_justtime_cm(self):
        """Habilita/deshabilita los campos de cada bloque según el valor
        REAL vigente de TIPO DE FACTURACION (self._tipo_facturacion_actual),
        usando los mismos catálogos de habilitación centralizados en
        constants.py (TIPO_FACTURACION_HABILITA_JUSTTIME/_CM) -- no se
        reimplementa la condición aquí. Deshabilitar un bloque NUNCA borra
        ni modifica el valor que ya tenga cada campo (ver conversación con
        el usuario, 16-09-2026): una unidad real con datos de CM/JustTime
        que hoy no corresponden al TIPO DE FACTURACION vigente los conserva
        intactos, solo deja de poder editarlos hasta que vuelvan a
        corresponder."""
        valor = str(self._tipo_facturacion_actual).strip().upper()
        habilita_justtime = valor in TIPO_FACTURACION_HABILITA_JUSTTIME
        habilita_cm = valor in TIPO_FACTURACION_HABILITA_CM
        for campo in _CAMPOS_BLOQUE_JUSTTIME:
            self.inputs[campo].setEnabled(habilita_justtime)
        for campo in _CAMPOS_BLOQUE_CM:
            self.inputs[campo].setEnabled(habilita_cm)
        self._set_badge_bloqueo('justtime', habilita_justtime)
        self._set_badge_bloqueo('cm', habilita_cm)
        if self._justtime_automatico():
            self._aplicar_justtime_nuevo_contrato()
        else:
            self._ajustar_justtime_manual()

    def _tipo_va_a_justtime(self):
        return str(self._tipo_facturacion_actual).strip().upper() in TIPO_FACTURACION_HABILITA_JUSTTIME

    def _poner_estado_justtime(self, estado):
        combo = self.inputs['CONTRATO CREADO EN JUSTTIME']
        combo.blockSignals(True)
        if combo.findText(estado) < 0:
            combo.addItem(estado)
        combo.setCurrentText(estado)
        combo.blockSignals(False)

    def _poner_fechas_justtime(self, inicio, termino):
        for campo, valor in (('INICIO', inicio), ('TERMINO', termino)):
            widget = self.inputs[campo]
            widget.blockSignals(True)
            widget.setText(valor or JUSTTIME_ESTADO_NO_APLICA)
            widget.blockSignals(False)

    def _ajustar_justtime_correccion(self):
        """Unidad cuyo tipo de facturación no va a JustTime pero sigue con
        estado Si, Pendiente o Revisar pago: el estado se puede corregir a lo
        que indica la matriz (Si/Revisar pago -> Eliminar, Pendiente -> "-");
        las fechas siguen bloqueadas."""
        combo = self.inputs['CONTRATO CREADO EN JUSTTIME']
        actual = combo.currentText().strip()
        original = (getattr(self, '_jt_original', None) or {}).get('estado', '')
        base = actual if actual in _ESTADOS_JT_CORREGIBLES else (original if original in _ESTADOS_JT_CORREGIBLES else '')
        if not base:
            combo.setEnabled(False)
            return
        destino = JUSTTIME_ESTADO_NO_APLICA if base == JUSTTIME_ESTADO_PENDIENTE else JUSTTIME_ESTADO_ELIMINAR
        opciones = [base, destino]
        if [combo.itemText(i) for i in range(combo.count())] != opciones:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(opciones)
            combo.setCurrentText(actual if actual in opciones else base)
            combo.blockSignals(False)
        combo.setEnabled(True)
        self._set_badge_bloqueo('justtime', True)
        for campo in ('INICIO', 'TERMINO'):
            self.inputs[campo].setEnabled(False)

    def _completar_fechas_justtime(self):
        """Inicio y término de JustTime vacíos con un estado vigente: el inicio
        es el primer día del mes de INICIO CONTRATO y el término suma la
        duración (queda vacío si el contrato es mensual)."""
        if self.inputs['CONTRATO CREADO EN JUSTTIME'].currentText().strip() not in _ESTADOS_JT_CORREGIBLES:
            return
        vacio = ('', JUSTTIME_ESTADO_NO_APLICA)
        if self.inputs['INICIO'].text().strip() not in vacio or self.inputs['TERMINO'].text().strip() not in vacio:
            return
        inicio = DataFrameFormatter.parsear_fecha_segura(self._valor_widget('INICIO CONTRATO'))
        if pd.isna(inicio):
            return
        inicio = inicio.replace(day=1)
        duracion = self._valor_widget('DURACIÓN (MESES)').strip()
        termino = ''
        if duracion.isdigit() and int(duracion) > 0:
            termino = (inicio + pd.DateOffset(months=int(duracion))).strftime("%d-%m-%Y")
        self._poner_fechas_justtime(inicio.strftime("%d-%m-%Y"), termino)

    def _reconciliar_justtime_por_tipo(self, anterior, nuevo):
        """Edición manual: al cambiar el tipo de facturación, volver al tipo
        original deja JustTime como estaba al abrir; pasar a un tipo que no va
        a JustTime lleva el estado a lo que indica la matriz."""
        if not self.modo_edicion or self._justtime_automatico():
            return
        habilita = TIPO_FACTURACION_HABILITA_JUSTTIME
        if (str(anterior).strip().upper() in habilita) == (str(nuevo).strip().upper() in habilita):
            return
        original = getattr(self, '_jt_original', None)
        if original and str(nuevo).strip().upper() == original['tipo']:
            self._poner_estado_justtime(original['estado'])
            self._poner_fechas_justtime(original['inicio'], original['termino'])
        elif str(nuevo).strip().upper() not in habilita:
            estado = self.inputs['CONTRATO CREADO EN JUSTTIME'].currentText().strip()
            if estado in (JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_REVISAR_PAGO):
                self._poner_estado_justtime(JUSTTIME_ESTADO_ELIMINAR)
            elif estado == JUSTTIME_ESTADO_PENDIENTE:
                self._poner_estado_justtime(JUSTTIME_ESTADO_NO_APLICA)
                self._poner_fechas_justtime('', '')
        self._ajustar_justtime_manual()

    def _ajustar_justtime_manual(self, *_args):
        """JustTime en edición manual: "-" (ya salió de JustTime) solo se
        ofrece si el contrato terminó y las fechas quedan siempre bloqueadas."""
        combo = self.inputs['CONTRATO CREADO EN JUSTTIME']
        if self._justtime_automatico():
            return
        if not self._tipo_va_a_justtime():
            if self.modo_edicion:
                self._ajustar_justtime_correccion()
            return
        if not combo.isEnabled():
            return
        actual = combo.currentText().strip()
        terminado = self.inputs['ESTADO COMERCIAL'].currentText().strip().upper() in _ESTADOS_COMERCIALES_FIN
        opciones = [o for o in JUSTTIME_ESTADO_OPCIONES if o != JUSTTIME_ESTADO_NO_APLICA or terminado or actual == JUSTTIME_ESTADO_NO_APLICA]
        if [combo.itemText(i) for i in range(combo.count())] != opciones:
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(opciones)
            self._set_combo_valor_precargado(combo, actual)
            combo.blockSignals(False)
        for campo in ('INICIO', 'TERMINO'):
            self.inputs[campo].setEnabled(False)
        self._completar_fechas_justtime()

    def _on_justtime_elegido(self, *_args):
        """Las fechas nunca se editan a mano: elegir "-" las limpia (guardando
        las vigentes) y volver a otro estado las recupera."""
        elegido = self.inputs['CONTRATO CREADO EN JUSTTIME'].currentText().strip()
        inicio, termino = self.inputs['INICIO'], self.inputs['TERMINO']
        vacio = ('', JUSTTIME_ESTADO_NO_APLICA)
        if elegido == JUSTTIME_ESTADO_NO_APLICA:
            if inicio.text().strip() not in vacio or termino.text().strip() not in vacio:
                self._fechas_justtime_guardadas = (inicio.text(), termino.text())
            inicio.setText(JUSTTIME_ESTADO_NO_APLICA)
            termino.setText(JUSTTIME_ESTADO_NO_APLICA)
        else:
            guardadas = getattr(self, '_fechas_justtime_guardadas', None)
            if guardadas and inicio.text().strip() in vacio and termino.text().strip() in vacio:
                inicio.setText(guardadas[0])
                termino.setText(guardadas[1])
        self._ajustar_justtime_manual()

    def _justtime_automatico(self):
        """Contrato nuevo (botón Nuevo contrato, alta de unidad o unidad de
        Nuevas oportunidades sin estado de JustTime): JustTime se completa
        solo. En cualquier otra edición, o si la unidad ya trae un estado
        propio, queda manual."""
        if getattr(self, 'modo_nuevo_contrato', False):
            return True
        if self.modo_edicion:
            return getattr(self, '_jt_auto_edicion', False)
        if getattr(self, '_modo_lote', False):
            return False
        actual = self.inputs['CONTRATO CREADO EN JUSTTIME'].currentText().strip()
        return actual in ('', JUSTTIME_ESTADO_NO_APLICA, JUSTTIME_ESTADO_PENDIENTE)

    def _aplicar_justtime_nuevo_contrato(self):
        """En "Nuevo contrato", si el tipo de facturación va a JustTime
        (Cliente o Interno), el contrato nace "Pendiente" y bloqueado, el
        inicio es el primer día del mes actual y el término suma la duración
        en meses a ese día (queda vacío si el contrato es mensual). Los tres
        campos quedan bloqueados. Con otro tipo de facturación no se toca
        nada: el bloque sigue deshabilitado."""
        if str(self._tipo_facturacion_actual).strip().upper() not in TIPO_FACTURACION_HABILITA_JUSTTIME:
            return
        inicio = datetime.now().replace(day=1)
        duracion = self.inputs['DURACIÓN (MESES)'].text().strip()
        termino = ''
        if duracion.isdigit() and int(duracion) > 0:
            from dateutil.relativedelta import relativedelta
            termino = (inicio + relativedelta(months=int(duracion))).strftime("%d-%m-%Y")
        valores = {
            'CONTRATO CREADO EN JUSTTIME': JUSTTIME_ESTADO_PENDIENTE,
            'INICIO': inicio.strftime("%d-%m-%Y"),
            'TERMINO': termino,
        }
        for campo, valor in valores.items():
            widget = self.inputs[campo]
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentText(valor)
            else:
                widget.setText(valor)
            widget.blockSignals(False)
            widget.setEnabled(False)

    def _on_duracion_nuevo_contrato(self, _texto=''):
        if self._justtime_automatico():
            self._aplicar_justtime_nuevo_contrato()

    def _set_badge_bloqueo(self, key, habilitado):
        """Aviso visual explícito de si una sección (JustTime/CM/Operaciones)
        está bloqueada o editable (16-09-2026; rediseñado 25-09-2026 a
        pedido explícito: sin emojis -- ícono qtawesome + "pill" de color en
        vez de 🔒/🔓 como caracteres de texto). El atenuado por
        `setEnabled(False)` de Qt no bastaba para notarlo a simple vista."""
        badge = getattr(self, '_badges_bloqueo', {}).get(key)
        if badge is None:
            return
        color = '#1F7A55' if habilitado else '#66748D'
        bg = '#E7F4EE' if habilitado else '#EEF2F6'
        icono = 'fa5s.unlock' if habilitado else 'fa5s.lock'
        texto = 'Editable' if habilitado else 'Bloqueado'
        badge['icon'].setPixmap(qta.icon(icono, color=color).pixmap(11, 11))
        badge['texto'].setText(texto)
        badge['texto'].setStyleSheet(f"font-size: 11px; font-weight: 600; letter-spacing: 0; background: transparent; border: none; color: {color};")
        badge['frame'].setStyleSheet(f"QFrame#badgeBloqueo {{ background-color: {bg}; border: 1px solid #DCE3EC; border-radius: 8px; }}")
        badge['frame'].setVisible(True)

    def _tipo_facturacion_validos_actual(self):
        """Set de valores REALES de TIPO DE FACTURACION permitidos para el
        FORMA DE CONTRATO vigente, según FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
        (constants.py, matriz entregada por Javiera, 24-09-2026). None si
        FORMA DE CONTRATO no está en la matriz (valor legado/no reconocido):
        en ese caso no se restringe nada, mismo criterio que el resto de las
        matrices de negocio del sistema.

        FORMA DE CONTRATO='-' (placeholder, "todavía sin elegir") es un caso
        especial exclusivo de este diálogo (25-09-2026, a pedido explícito):
        NO se agrega a la matriz de constants.py porque esa matriz también
        alimenta detectar_inconsistencias_forma_contrato_tipo_facturacion()/
        normalizar_tipo_facturacion_por_forma_contrato() en
        comercial_services.py (auditoría de datos históricos y
        sincronización con RM_JAVI), donde FORMA DE CONTRATO='-' nunca
        debe marcarse ni tocarse. Acá, en cambio, mientras el usuario no
        elige una FORMA DE CONTRATO real, TIPO DE FACTURACION tampoco
        debería quedar editable con el catálogo completo."""
        forma = self.inputs['FORMA DE CONTRATO'].currentText().strip().upper()
        if forma == '-':
            return {'-'}
        return FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(forma)

    def _actualizar_habilitacion_tipo_facturacion(self):
        """TIPO DE FACTURACION queda bloqueado cuando FORMA DE CONTRATO solo
        admite un único valor posible en FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
        -- no hay nada que elegir (25-09-2026, a pedido explícito: "no se
        pueda modificar ya que depende de forma de contrato... algunas solo
        tiene una opcion, ahi no es necesario que se pueda modificar").
        Queda editable cuando admite más de una opción (CONVERSION/VENTA:
        Cliente o Facturación Manual) o cuando FORMA DE CONTRATO no está en
        la matriz (valor legado, sin restricción). No pisa un bloqueo ya
        aplicado por _aplicar_restriccion_alta_general -- se llama antes de
        esa restricción en _aplicar_datos_iniciales."""
        validos = self._tipo_facturacion_validos_actual()
        self.inputs['TIPO DE FACTURACION'].setEnabled(validos is None or len(validos) > 1)
        self._actualizar_alerta_tipo_facturacion()

    def _crear_boton_corregir_tipo_facturacion(self):
        btn = QPushButton()
        btn.setIcon(qta.icon('fa5s.exclamation-triangle', color='#B42318'))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setAutoDefault(False)
        btn.setStyleSheet(
            "QPushButton { background-color: #FEF2F2; color: #B42318; border: 1px solid #EF4444; border-radius: 8px;"
            " padding: 5px 10px; font-size: 12px; font-weight: 600; text-align: left; }"
            "QPushButton:hover { background-color: #FEE2E2; }")
        btn.clicked.connect(self._corregir_tipo_facturacion)
        btn.setVisible(False)
        return btn

    def _tipo_facturacion_correcto(self):
        """Valor REAL al que corresponde corregir cuando el TIPO DE FACTURACION
        cargado no cumple la matriz para la FORMA DE CONTRATO vigente; None si
        es coherente (o la forma no está en la matriz, o aún no se elige)."""
        if self.inputs['FORMA DE CONTRATO'].currentText().strip() in ('', '-'):
            return None
        validos = self._tipo_facturacion_validos_actual()
        if not validos or str(self._tipo_facturacion_actual).strip().upper() in validos:
            return None
        return next((v for v in _ORDEN_TIPO_FACTURACION if v in validos), None)

    def _actualizar_alerta_tipo_facturacion(self):
        """Marca en rojo el TIPO DE FACTURACION incoherente con la matriz y
        muestra el botón para corregirlo, solo en ese caso."""
        btn = getattr(self, '_btn_corregir_tipo_fact', None)
        if btn is None or 'TIPO DE FACTURACION' not in self.inputs:
            return
        widget = self.inputs['TIPO DE FACTURACION']
        correcto = self._tipo_facturacion_correcto()
        if correcto is None:
            if btn.isVisible() or widget.styleSheet():
                widget.setStyleSheet("")
                widget.setToolTip("")
            btn.setVisible(False)
            return
        destino = TIPO_FACTURACION_DISPLAY_MAP.get(correcto, correcto)
        widget.setStyleSheet("border: 1px solid #EF4444; background-color: #FEF2F2; color: #B42318;")
        widget.setToolTip(f"No corresponde a la forma de contrato {self.inputs['FORMA DE CONTRATO'].currentText()}. Corrígelo a {destino}.")
        btn.setText(f" Corregir a {destino}")
        btn.setVisible(True)

    def _corregir_tipo_facturacion(self):
        correcto = self._tipo_facturacion_correcto()
        if correcto is None:
            return
        self._sincronizar_tipo_facturacion_con_forma_contrato()
        self._actualizar_alerta_tipo_facturacion()

    def _on_tipo_facturacion_editado(self, index):
        """Se dispara solo cuando el usuario elige un valor del combo TIPO
        DE FACTURACION con el mouse/teclado (señal `activated`, mismo patrón
        que MODELO/ETAPA GESTIÓN). Traduce el texto amigable mostrado al
        valor REAL (TIPO_FACTURACION_DISPLAY_A_REAL) antes de propagarlo.

        FORMA DE CONTRATO manda sobre TIPO DE FACTURACION (generalizado
        24-09-2026 a partir de FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ; antes
        solo cubría el caso 'CM'): si el valor elegido no está entre los
        permitidos para el FORMA DE CONTRATO vigente, la selección se
        revierte sin aplicar ningún cambio. En la práctica el combo ya solo
        ofrece los valores válidos (ver _sincronizar_tipo_facturacion_con_forma_contrato,
        que reconstruye sus ítems), así que esto es una defensa adicional
        para el instante en que FORMA DE CONTRATO aún no se ha tocado en
        vivo. Esto es exclusivo de la interacción en vivo: la precarga de una
        unidad real con esta combinación "inconsistente" ya guardada NUNCA
        pasa por este método (ver _aplicar_datos_iniciales, que setea el
        combo directamente con blockSignals), así que no se pierde ningún
        dato histórico al abrir el formulario."""
        widget = self.inputs['TIPO DE FACTURACION']
        texto_amigable = widget.currentText()
        valor_real = TIPO_FACTURACION_DISPLAY_A_REAL.get(texto_amigable, texto_amigable)

        validos = self._tipo_facturacion_validos_actual()
        if validos is not None and valor_real not in validos:
            widget.blockSignals(True)
            widget.setCurrentText(TIPO_FACTURACION_DISPLAY_MAP.get(self._tipo_facturacion_actual, self._tipo_facturacion_actual))
            widget.blockSignals(False)
            return

        self._aplicar_tipo_facturacion_programatico(valor_real)

    def _aplicar_tipo_facturacion_programatico(self, valor_real):
        """Punto único que aplica un nuevo TIPO DE FACTURACION (ya sea por
        elección real del usuario en el combo, o porque FORMA DE CONTRATO lo
        fuerza -- ver _sincronizar_tipo_facturacion_con_forma_contrato):
        actualiza el combo, el holder, ETAPA GESTIÓN, la habilitación de
        bloques y dispara la limpieza en vivo del bloque que deja de
        corresponder (16-09-2026, decisión explícita del usuario: reemplaza
        la regla "no limpiar" de la Fase 4 -- ver _limpiar_bloques_si_corresponde)."""
        widget = self.inputs['TIPO DE FACTURACION']
        valor_anterior = self._tipo_facturacion_actual
        widget.blockSignals(True)
        widget.setCurrentText(TIPO_FACTURACION_DISPLAY_MAP.get(valor_real, valor_real))
        widget.blockSignals(False)
        self._set_tipo_facturacion_actual(valor_real)
        self._actualizar_habilitacion_justtime_cm()
        self._limpiar_bloques_si_corresponde(valor_anterior, valor_real)
        self._reconciliar_justtime_por_tipo(valor_anterior, valor_real)
        self._autocompletar_duracion_mensual()
        self._actualizar_resumen()

    def _limpiar_bloques_si_corresponde(self, valor_anterior, valor_nuevo):
        """Limpia a '-' los campos de un bloque (JustTime o CM) cuando ese
        bloque pasa de habilitado a deshabilitado por el cambio de TIPO DE
        FACTURACION. Solo actúa en la transición habilitado->deshabilitado;
        si el bloque sigue habilitado (ej. de 'Cliente' a 'Interno') o si ya
        estaba deshabilitado, no toca nada. Exclusivo de cambios EN VIVO
        (nunca se llama durante la precarga), por decisión explícita del
        usuario: los datos reales existentes nunca se limpian solo por abrir
        el formulario."""
        anterior = str(valor_anterior).strip().upper()
        nuevo = str(valor_nuevo).strip().upper()

        edicion_manual = self.modo_edicion and not self._justtime_automatico()
        if anterior in TIPO_FACTURACION_HABILITA_JUSTTIME and nuevo not in TIPO_FACTURACION_HABILITA_JUSTTIME \
                and not edicion_manual:
            self._limpiar_bloque(_CAMPOS_BLOQUE_JUSTTIME)

        if anterior in TIPO_FACTURACION_HABILITA_CM and nuevo not in TIPO_FACTURACION_HABILITA_CM:
            self._limpiar_bloque(_CAMPOS_BLOQUE_CM)
            self._tipo_cm_manual = False

    def _limpiar_bloque(self, campos):
        for campo in campos:
            widget = self.inputs[campo]
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                widget.setCurrentText('-')
            else:
                widget.setText('-')
            widget.setStyleSheet("")
            widget.setToolTip("")
            widget.blockSignals(False)

    def _sincronizar_tipo_facturacion_con_forma_contrato(self):
        """FORMA DE CONTRATO manda sobre TIPO DE FACTURACION (generalizado
        24-09-2026 a partir de FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ; antes
        solo cubría el caso 'CM' -> CMG/CMB/CMS). Reconstruye las opciones
        del combo TIPO DE FACTURACION al subconjunto válido para el FORMA DE
        CONTRATO vigente; si ese subconjunto tiene un único valor posible, lo
        fuerza automáticamente (mismo comportamiento que antes tenía el caso
        CM, ahora generalizado también a DEMO/PROVISION/PROVISION +/REVISAR/
        SIN CONTRATO/TEST). Si tiene más de un valor posible (CONVERSION/
        VENTA: Cliente o Facturación Manual), solo restringe las opciones sin
        forzar ninguna -- el usuario elige entre las válidas. Si FORMA DE
        CONTRATO no está en la matriz, no restringe nada (catálogo completo).
        Solo aplica en vivo: no se conecta a nada durante la precarga (ver
        _aplicar_datos_iniciales, que precarga TIPO DE FACTURACION aparte)."""
        validos = self._tipo_facturacion_validos_actual()
        widget = self.inputs['TIPO DE FACTURACION']
        valor_actual = str(self._tipo_facturacion_actual).strip().upper()

        nuevos_valores = (
            list(_ORDEN_TIPO_FACTURACION_SIN_GUION) if validos is None
            else [v for v in _ORDEN_TIPO_FACTURACION if v in validos]
        )
        # "-" quitado del catálogo elegible (25-09-2026, mismo pedido que en
        # _create_widget), salvo que sea la ÚNICA opción válida para el
        # FORMA DE CONTRATO vigente (ej. datos legados con FORMA DE
        # CONTRATO='-') -- en ese caso se conserva para no dejar el combo
        # sin ninguna opción.
        sin_guion = [v for v in nuevos_valores if v != '-']
        if sin_guion:
            nuevos_valores = sin_guion
        widget.blockSignals(True)
        widget.clear()
        widget.addItems([TIPO_FACTURACION_DISPLAY_MAP[v] for v in nuevos_valores])
        widget.blockSignals(False)

        if validos is None or valor_actual in validos:
            # Sigue siendo válido (o no hay restricción para este FORMA DE
            # CONTRATO): solo se actualizó la lista de opciones, el valor
            # elegido no cambia.
            widget.blockSignals(True)
            widget.setCurrentText(TIPO_FACTURACION_DISPLAY_MAP.get(valor_actual, valor_actual))
            widget.blockSignals(False)
        else:
            # Ya no es válido para el nuevo FORMA DE CONTRATO: se fuerza al
            # primer valor permitido (el único posible si la fila tiene una
            # sola opción; el primero de la lista si tiene más de una, ej.
            # CONVERSION/VENTA -> Cliente).
            self._aplicar_tipo_facturacion_programatico(nuevos_valores[0])

        self._actualizar_habilitacion_tipo_facturacion()

    def _autocompletar_tipo_cm(self):
        """FORMA DE CONTRATO -> TIPO DE CM, vía el único mapa centralizado
        FORMA_CONTRATO_TIPO_CM_MAP (constants.py, Fase 0): no se reimplementa
        la relación CMG/CMB/CMS -> Gold/Blue/Silver aquí. No hace nada si el
        usuario ya eligió TIPO DE CM manualmente (ver
        _on_tipo_cm_editado_manualmente), ni si FORMA DE CONTRATO no
        corresponde a ninguno de los 3 códigos de mantenimiento (en ese caso
        el bloque completo ya quedó en '-' vía
        _sincronizar_tipo_facturacion_con_forma_contrato, así que tampoco
        hay nada que autocompletar)."""
        if self._tipo_cm_manual:
            return
        forma = self.inputs['FORMA DE CONTRATO'].currentText().strip().upper()
        tipo_cm = FORMA_CONTRATO_TIPO_CM_MAP.get(forma)
        if tipo_cm:
            self.inputs['TIPO DE CM'].setCurrentText(tipo_cm)

    def _on_tipo_cm_editado_manualmente(self, index):
        """Se dispara solo cuando el usuario elige TIPO DE CM con el
        mouse/teclado (señal `activated`, mismo patrón que MODELO/ETAPA
        GESTIÓN): a partir de aquí, el autocompletado por FORMA DE CONTRATO
        deja de pisar la elección."""
        self._tipo_cm_manual = True

    # ------------------------------------------------------------------
    # Validación en vivo de VIN duplicado (edición y alta)
    # ------------------------------------------------------------------
    def _vin_duplicado(self, vin_upper):
        """True si `vin_upper` (ya en mayúsculas/strip) ya existe en Comercial
        en OTRA unidad, o ya fue confirmado en un registro anterior de este
        mismo lote de importación Power BI (ver _vins_usados_en_lote /
        _avanzar_lote). El VIN original de la unidad en edición se considera
        válido contra sí mismo."""
        if not vin_upper:
            return False
        if self.modo_edicion and vin_upper == self._vin_original:
            return False
        if self.modo_renovacion:
            return False
        if self.modo_nuevo_contrato:
            return vin_upper in self._vins_con_contrato_abierto
        return vin_upper in self._vins_existentes or vin_upper in self._vins_usados_en_lote

    def _validar_vin_duplicado(self):
        """Marca el campo VIN en rojo y deshabilita Guardar si el VIN ya
        pertenece a otra unidad -- sin QMessageBox ni popups, para no
        interrumpir mientras el usuario escribe o pega el VIN (tanto tecleo
        como Ctrl+V disparan textChanged)."""
        vin_upper = self.inputs['VIN'].text().strip().upper()
        widget = self.inputs['VIN']
        if self._vin_duplicado(vin_upper):
            widget.setStyleSheet("border: 1px solid #EF4444; background-color: #FEF2F2;")
            widget.setToolTip(
                "Esta unidad no admite otro contrato: el actual no está en baja o la unidad sigue Activando o Conectada."
                if self.modo_nuevo_contrato else "Ya existe una unidad con este VIN en Comercial.")
            self.btn_save.setEnabled(False)
        else:
            widget.setStyleSheet("")
            widget.setToolTip("")
            self.btn_save.setEnabled(not self._contrato_cerrado)

    # ------------------------------------------------------------------
    # Cálculos automáticos (idénticos a la versión anterior)
    # ------------------------------------------------------------------
    def _auto_calculate_chasis(self):
        vin_text = self.inputs['VIN'].text().strip()
        if len(vin_text) >= 7:
            self.inputs['CHASIS'].setText(vin_text[-7:])
        else:
            self.inputs['CHASIS'].setText("")

    def _on_modelo_editado_manualmente(self, index):
        """Se dispara solo cuando el usuario elige un valor del combo MODELO
        con el mouse/teclado (señal `activated`, no `currentTextChanged`):
        a partir de aquí, cambiar el VIN ya no vuelve a pisar la elección."""
        self._modelo_manual = True

    def _auto_calculate_modelo(self):
        """Autocompleta MODELO a partir del VIN (ver src/services/vin_service.py:
        solo la posicion 4, y 5-7 para la variante electrica). El combo MODELO
        no es editable, asi que setCurrentText solo tiene efecto si el modelo
        deducido coincide exactamente con una de sus opciones oficiales; si el
        service no reconoce el codigo (o el VIN es muy corto), no se toca el
        campo. No hace nada si el usuario ya eligió MODELO manualmente (ver
        _on_modelo_editado_manualmente)."""
        if self._modelo_manual:
            return
        vin_text = self.inputs['VIN'].text().strip()
        modelo = obtener_modelo_desde_vin(vin_text)
        if modelo:
            self.inputs['MODELO'].setCurrentText(modelo)

    def _on_inicio_contrato_changed(self, texto):
        """Autoformatea INICIO CONTRATO mientras se escribe/pega: deja solo
        dígitos (las letras ya las bloquea el validador del campo) y va
        insertando los guiones DD-MM-YYYY solo, sin que el usuario tenga que
        tipearlos (ej. '09092026' -> '09-09-2026'). Luego dispara el mismo
        cálculo de TÉRMINO CONTRATO de siempre."""
        solo_digitos = ''.join(ch for ch in texto if ch.isdigit())[:8]
        if len(solo_digitos) > 4:
            formateado = f"{solo_digitos[:2]}-{solo_digitos[2:4]}-{solo_digitos[4:]}"
        elif len(solo_digitos) > 2:
            formateado = f"{solo_digitos[:2]}-{solo_digitos[2:]}"
        else:
            formateado = solo_digitos

        widget = self.inputs['INICIO CONTRATO']
        if formateado != texto:
            widget.blockSignals(True)
            widget.setText(formateado)
            widget.blockSignals(False)

        # Con la fecha completa (10 caracteres), valida que exista de verdad
        # en el calendario (ej. 31-02-2026 no existe) y lo marca en rojo al
        # instante, sin esperar a que se presione Guardar.
        if len(formateado) == 10:
            try:
                datetime.strptime(formateado, "%d-%m-%Y")
                widget.setStyleSheet("")
                widget.setToolTip("")
            except ValueError:
                widget.setStyleSheet("border: 1px solid #EF4444; background-color: #FEF2F2;")
                widget.setToolTip("Esa fecha no existe en el calendario (ej. 31 de febrero).")
        else:
            widget.setStyleSheet("")
            widget.setToolTip("")

        self._auto_calculate_termino()

    def _auto_calculate_termino(self):
        """Calcula matemáticamente en tiempo real la fecha de término del contrato."""
        inicio_str = self.inputs['INICIO CONTRATO'].text().strip()
        duracion_str = self.inputs['DURACIÓN (MESES)'].text().strip().upper()

        if not inicio_str:
            self.inputs['TÉRMINO CONTRATO'].setText("")
            self._actualizar_color_termino_contrato()
            return

        if duracion_str == 'MENSUAL' or duracion_str == '-':
            self.inputs['TÉRMINO CONTRATO'].setText("MENSUAL")
            self._actualizar_color_termino_contrato()
            return

        try:
            # Revisa si el usuario tipeó la fecha correcta (DD-MM-YYYY)
            fecha_inicio = datetime.strptime(inicio_str, "%d-%m-%Y")

            # Si hay un número de meses, aplica la matemática
            if duracion_str.isdigit() and int(duracion_str) > 0:
                from dateutil.relativedelta import relativedelta
                meses = int(duracion_str)
                fecha_termino = fecha_inicio + relativedelta(months=meses)
                self.inputs['TÉRMINO CONTRATO'].setText(fecha_termino.strftime("%d-%m-%Y"))
            else:
                self.inputs['TÉRMINO CONTRATO'].setText("")

        except ValueError:
            # Si la fecha no está completa aún, vacía la de término por precaución
            self.inputs['TÉRMINO CONTRATO'].setText("")

        self._actualizar_color_termino_contrato()

    def _actualizar_color_termino_contrato(self):
        """TÉRMINO CONTRATO ya vencido se resalta en rojo (25-09-2026, a
        pedido explícito: "puede haber fechas vencidas y el usuario no se
        entera"), sin importar desde qué pantalla se abrió este formulario
        -- se llama tanto al recalcular (_auto_calculate_termino) como al
        precargar una unidad existente (_aplicar_datos_iniciales). Reutiliza
        comercial_services.clasificar_fecha_termino (misma regla de
        "vencido" que ya usan los KPI de Vista Completa/Comercial: fecha de
        calendario ya pasada; MENSUAL y "-"/vacío nunca cuentan)."""
        widget = self.inputs['TÉRMINO CONTRATO']
        clasif = comercial_services.clasificar_fecha_termino(widget.text().strip())
        widget.setStyleSheet(f"color: {DANGER}; font-weight: bold;" if clasif['vencido'] else "")

    def _on_fecha_generica_widget_changed(self, texto):
        """Wrapper sin lambda para conectar textChanged a _on_fecha_generica_changed:
        identifica el campo por el emisor (self.sender()) en vez de capturarlo en un
        closure. Las lambdas que capturaban self en textChanged.connect() creaban un
        ciclo de referencia (widget hijo -> lambda -> self) que gc.collect() no lograba
        romper, dejando el diálogo y sus widgets vivos tras close()+deleteLater()."""
        sender = self.sender()
        field_name = next(nombre for nombre, widget in self.inputs.items() if widget is sender)
        self._on_fecha_generica_changed(field_name, texto)

    def _on_fecha_generica_changed(self, field_name, texto):
        """Autoformatea un campo de fecha simple (sin cálculo dependiente)
        igual que _on_inicio_contrato_changed: mismo patrón DD-MM-YYYY
        armado solo a partir de los dígitos tipeados/pegados, con una
        diferencia: "-" es un valor válido (significa "sin fecha
        registrada", no un error), así que si el texto es exactamente "-"
        se deja tal cual, sin pasarlo por el armado de dígitos (que lo
        convertiría en cadena vacía). Generalizado (16-09-2026) a partir de
        _on_fecha_baja_changed para reutilizarlo también en INICIO, TERMINO,
        FECHA INICIO CM y FECHA TERMINO CM (pestaña "JustTime & CM"), que
        tienen el mismo comportamiento y ningún campo derivado."""
        widget = self.inputs[field_name]
        if texto.strip() == '-':
            widget.setStyleSheet("")
            widget.setToolTip("")
            return

        solo_digitos = ''.join(ch for ch in texto if ch.isdigit())[:8]
        if len(solo_digitos) > 4:
            formateado = f"{solo_digitos[:2]}-{solo_digitos[2:4]}-{solo_digitos[4:]}"
        elif len(solo_digitos) > 2:
            formateado = f"{solo_digitos[:2]}-{solo_digitos[2:]}"
        else:
            formateado = solo_digitos

        if formateado != texto:
            widget.blockSignals(True)
            widget.setText(formateado)
            widget.blockSignals(False)

        if len(formateado) == 10:
            try:
                datetime.strptime(formateado, "%d-%m-%Y")
                widget.setStyleSheet("")
                widget.setToolTip("")
            except ValueError:
                widget.setStyleSheet("border: 1px solid #EF4444; background-color: #FEF2F2;")
                widget.setToolTip("Esa fecha no existe en el calendario (ej. 31 de febrero).")
        else:
            widget.setStyleSheet("")
            widget.setToolTip("")

    def _on_fecha_baja_changed(self, texto):
        """FECHA DE BAJA no tiene ningún campo derivado (a diferencia de
        INICIO CONTRATO, que recalcula TÉRMINO CONTRATO): delega en el
        formateo genérico de fechas simples."""
        self._on_fecha_generica_changed('FECHA DE BAJA', texto)

    def _on_pago_cm_changed(self, texto):
        """Autoformatea PAGO CM como moneda ("$80.000") mientras se escribe,
        mismo criterio de presentación que ya usa Contratos CM
        (contratos.py, _formatear_pago_cm_para_mostrar): "-" es un valor
        válido (sin pago registrado), no se reformatea. El valor que
        finalmente se guarda (ver _valor_widget) es siempre el número crudo
        sin símbolos, nunca este texto formateado -- PAGO CM sigue siendo
        una columna numérica en PruebasFM, esto es solo presentación."""
        widget = self.inputs['PAGO CM']
        if texto.strip() == '-':
            return
        solo_digitos = ''.join(ch for ch in texto if ch.isdigit())
        if not solo_digitos:
            return  # se deja vacío; get_data() lo normaliza a "-" al guardar
        formateado = f"${int(solo_digitos):,}".replace(",", ".")
        if formateado != texto:
            widget.blockSignals(True)
            widget.setText(formateado)
            widget.blockSignals(False)

    # ------------------------------------------------------------------
    # Validación y datos (idénticos a la versión anterior)
    # ------------------------------------------------------------------
    def _valor_widget(self, campo):
        widget = self.inputs[campo]
        if campo == 'PAGO CM':
            # El widget muestra "$80.000" (presentación); lo que se guarda
            # es siempre el número crudo sin símbolos, porque PAGO CM sigue
            # siendo una columna numérica en PruebasFM (ver contratos.py,
            # que hace lo mismo al guardar: solo formatea para mostrar).
            texto = widget.text().strip()
            if not texto or texto == '-':
                return texto
            return ''.join(ch for ch in texto if ch.isdigit())
        if campo == 'TIPO DE FACTURACION':
            # El combo muestra el texto amigable (Cliente, Provision +...);
            # lo que se guarda/valida es siempre el valor REAL (constants.py
            # TIPO_FACTURACION_DISPLAY_A_REAL), nunca el texto de presentación.
            texto_amigable = widget.currentText().strip()
            return TIPO_FACTURACION_DISPLAY_A_REAL.get(texto_amigable, texto_amigable)
        if campo == 'TIPO DE SERVICIO':
            base = widget.currentText().strip()
            if base in ('', '-'):
                return base
            extras = ''.join(f' + {n}' for n, chk in (('CIV', self.chk_civ), ('SZ', self.chk_sz)) if chk.isChecked())
            return base + extras
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        return widget.text().strip()

    def _validate_and_accept(self):
        # Guarda defensiva: el botón Guardar ya debería estar deshabilitado
        # mientras el VIN esté duplicado (ver _validar_vin_duplicado), pero
        # no se avanza igual si por algún motivo se llegó a llamar esto.
        if self._vin_duplicado(self._valor_widget('VIN').upper()):
            return

        # Bloquea Guardar mientras la unidad sigue "Sin Contrato" (25-09-2026,
        # a pedido explícito): en el flujo de activación de "Por gestionar"
        # (forzar_activacion_pendiente=True, ver _aplicar_restriccion_activacion),
        # guardar con FORMA DE CONTRATO todavía en "Sin Contrato" dejaba la
        # unidad en un estado inconsistente (ESTADO COMERCIAL forzado a
        # "Activación Pendiente" pero sin un contrato real todavía) y el
        # guardado terminaba sin escribir ni actualizar nada (bug reportado).
        # El usuario debe elegir la FORMA DE CONTRATO real antes de poder
        # guardar esta activación.
        if self._forzar_activacion_pendiente and self._valor_widget('FORMA DE CONTRATO').strip().upper() == 'SIN CONTRATO':
            QMessageBox.warning(
                self, "Forma de Contrato pendiente",
                "Esta unidad todavía tiene FORMA DE CONTRATO = \"Sin Contrato\". "
                "Selecciona la forma de contrato real de la unidad antes de guardar la activación."
            )
            return

        if self.modo_nuevo_contrato and self._valor_widget('FORMA DE CONTRATO').strip().upper() in ('', '-', 'SIN CONTRATO'):
            self._ir_a_paso_campo('FORMA DE CONTRATO')
            QMessageBox.warning(
                self, "Forma de Contrato pendiente",
                "Un contrato nuevo necesita una forma de contrato real: elige una distinta de \"Sin Contrato\" antes de guardar."
            )
            return

        if self._tipo_facturacion_correcto() is not None:
            self._ir_a_paso_campo('TIPO DE FACTURACION')
            QMessageBox.warning(
                self, "Tipo de facturación incorrecto",
                "El tipo de facturación no corresponde a la forma de contrato. "
                "Presiona el botón rojo sobre Tipo de facturación para corregirlo antes de guardar."
            )
            return

        # INDUSTRIA vacía se autocompleta con "NO DEFINIDA" en vez de
        # bloquear el guardado (25-09-2026, a pedido explícito) -- combo
        # editable, así que puede quedar vacío si el usuario borra el texto.
        if not self._valor_widget('INDUSTRIA').strip():
            self.inputs['INDUSTRIA'].setCurrentText(_DEFAULTS_INICIALES['INDUSTRIA'])

        faltantes = [c for c in self.inputs.keys() if c in _CAMPOS_OBLIGATORIOS and not self._valor_widget(c)]
        if faltantes:
            self._ir_a_paso_campo(faltantes[0])
            QMessageBox.warning(
                self, "Campos Obligatorios",
                "Completa los siguientes campos obligatorios:\n- " + "\n- ".join(faltantes)
            )
            return

        # Solo se exige lo que el usuario puede editar: en "Importar Excel
        # Power BI"/"+ Nuevo Cliente" estos campos vienen bloqueados (ver
        # _aplicar_restriccion_alta_general) y Power BI no los trae.
        def _editable(campo):
            return campo in self.inputs and self.inputs[campo].isEnabled()

        # TIPO DE SERVICIO siempre debe quedar con un valor real, nunca "-"
        # (25-09-2026, a pedido explícito, aplica a todo guardado -- alta,
        # edición normal, activación desde "Por gestionar").
        tipo_servicio = self._valor_widget('TIPO DE SERVICIO').strip()
        if _editable('TIPO DE SERVICIO') and (not tipo_servicio or tipo_servicio == '-'):
            QMessageBox.warning(self, "Tipo de Servicio pendiente", "Selecciona un TIPO DE SERVICIO real antes de guardar (no puede quedar en \"-\").")
            return

        # INICIO CONTRATO siempre debe quedar con una fecha real, nunca vacío
        # ni "-" (25-09-2026, a pedido explícito, aplica a todo guardado).
        inicio = self._valor_widget('INICIO CONTRATO')
        if _editable('INICIO CONTRATO'):
            if not inicio or inicio == '-':
                QMessageBox.warning(self, "Inicio de Contrato pendiente", "INICIO CONTRATO no puede quedar vacío ni en \"-\": indica la fecha real de inicio antes de guardar.")
                return
            try:
                # --- VALIDACIÓN ESTRICTA DD-MM-YYYY ---
                datetime.strptime(inicio, "%d-%m-%Y")
            except ValueError:
                QMessageBox.warning(self, "Fecha Inválida", "La FECHA DE INICIO debe ser una fecha real del calendario, en formato DD-MM-YYYY (Ej: 14-08-2026).")
                return

        # DURACIÓN (MESES) nunca puede quedar vacía: número entero o "-"
        # (25-09-2026, a pedido explícito -- "Mensual" ya NO es un valor
        # válido de entrada: era un dato legado del Excel de RM_JAVI,
        # corregido; DURACIÓN="-" es el valor real para "contrato mes a
        # mes", que sigue autocompletando TÉRMINO CONTRATO="MENSUAL", ver
        # _auto_calculate_termino).
        # Sin señales: no debe recalcular TÉRMINO CONTRATO a "MENSUAL".
        if _editable('DURACIÓN (MESES)'):
            self._autocompletar_duracion_mensual()
        if not _editable('DURACIÓN (MESES)') and not self._valor_widget('DURACIÓN (MESES)').strip():
            widget_duracion = self.inputs['DURACIÓN (MESES)']
            widget_duracion.blockSignals(True)
            widget_duracion.setText('-')
            widget_duracion.blockSignals(False)
        duracion = self._valor_widget('DURACIÓN (MESES)').strip().upper()
        if not duracion:
            QMessageBox.warning(self, "Duración pendiente", "DURACIÓN (MESES) no puede quedar vacía: indica un número entero de meses o un guion '-'.")
            return
        if duracion != '-' and not duracion.isdigit():
            QMessageBox.warning(self, "Formato Inválido", "La DURACIÓN debe ser un número entero o un guion '-'.")
            return

        fecha_baja = self._valor_widget('FECHA DE BAJA')
        if fecha_baja and fecha_baja != '-':
            try:
                # "-" es el default de "sin fecha de baja registrada", no se valida como fecha.
                datetime.strptime(fecha_baja, "%d-%m-%Y")
            except ValueError:
                QMessageBox.warning(self, "Fecha Inválida", "La FECHA DE BAJA debe ser una fecha real del calendario, en formato DD-MM-YYYY (Ej: 14-08-2026), o un guion '-'.")
                return

        # Fechas simples de JustTime/CM/ESTADO DE ENTREGA: mismo criterio que
        # FECHA DE BAJA ("-" es un valor válido, no se valida como fecha).
        for campo_fecha, etiqueta in (
            ('ESTADO DE ENTREGA', 'ESTADO DE ENTREGA'),
            ('INICIO', 'INICIO (JustTime)'), ('TERMINO', 'TERMINO (JustTime)'),
            ('FECHA INICIO CM', 'FECHA INICIO CM'), ('FECHA TERMINO CM', 'FECHA TERMINO CM'),
        ):
            valor_fecha = self._valor_widget(campo_fecha)
            if valor_fecha and valor_fecha != '-':
                try:
                    datetime.strptime(valor_fecha, "%d-%m-%Y")
                except ValueError:
                    QMessageBox.warning(
                        self, "Fecha Inválida",
                        f"{etiqueta} debe ser una fecha real del calendario, en formato DD-MM-YYYY (Ej: 14-08-2026), o un guion '-'."
                    )
                    return

        if self.cantidad_multiple > 1:
            confirmar = QMessageBox.question(
                self, "Renovar contratos",
                f"Se renovarán {self.cantidad_multiple} contratos con los datos de Comercial y JustTime & CM de este "
                "formulario. Cada contrato actual quedará como Renovado.\n\n¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if confirmar != QMessageBox.StandardButton.Yes:
                return
        elif not self._confirmar_resumen():
            return  # "Volver al formulario": no se toca ni se limpia nada

        if self._modo_lote:
            self._avanzar_lote()
        else:
            self._on_formulario_confirmado()

    # ------------------------------------------------------------------
    # Modo lote (importación Power BI): un solo diálogo para todos los
    # registros, sin cerrar/reabrir ventana entre uno y otro.
    # ------------------------------------------------------------------
    def obtener_resultados_lote(self):
        """Lista de dicts (uno por registro, ya con get_data() aplicado) del
        lote completo. Solo tiene sentido llamarlo después de que exec()
        devolvió Accepted en modo lote."""
        return self._lote_resultados

    def lote_fue_cancelado(self):
        return self._lote_cancelado

    def _actualizar_texto_guardar(self):
        if self._modo_lote:
            es_ultimo = self._lote_indice >= len(self._lote) - 1
            self.btn_save.setText(" Guardar y finalizar" if es_ultimo else " Guardar y continuar")
        elif self.modo_edicion:
            self.btn_save.setText(" Guardar Cambios")
        elif self.modo_nuevo_contrato:
            self.btn_save.setText(" Crear contrato")
        else:
            self.btn_save.setText(" Guardar Registro")

    def _actualizar_progreso_visual(self):
        if not self.progreso:
            self._badge_progreso.setVisible(False)
            return
        indice, total = self.progreso
        self._badge_progreso.setText(f" {indice} / {total} ")
        self._badge_progreso.setVisible(True)

    def _actualizar_boton_chasis_bi(self):
        if self._chasis_bi_actual:
            self._btn_chasis_bi.setText(f"CHASIS: {self._chasis_bi_actual}")
            self._btn_chasis_bi.setVisible(True)
        else:
            self._btn_chasis_bi.setVisible(False)

    def _copiar_chasis_bi(self):
        if not self._chasis_bi_actual:
            return
        QApplication.clipboard().setText(self._chasis_bi_actual)
        self._btn_chasis_bi.setText(f"CHASIS: {self._chasis_bi_actual}  ✓ Copiado")
        QTimer.singleShot(1200, self._actualizar_boton_chasis_bi)

    def _handle_cancelar(self):
        if not self._modo_lote:
            self._on_formulario_cancelado()
            return

        # Confirmación en español, con los botones diferenciados por color
        # (Sí = rojo/destructivo, No = verde/continuar) -- sin usar los
        # Yes/No estándar de Qt. Mismo comportamiento de siempre: "Sí"
        # descarta TODO el lote sin escribir nada; "No" vuelve al registro
        # actual sin tocar nada.
        msg = QMessageBox(self)
        msg.setWindowTitle("Cancelar importación")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText("¿Está seguro de cancelar la importación?")
        msg.setInformativeText(
            f"Se descartarán los {len(self._lote_resultados)} de {len(self._lote)} registro(s) ya "
            "completados en este lote. No se ha escrito nada todavía en PruebasFM."
        )
        btn_si = msg.addButton("Sí", QMessageBox.ButtonRole.YesRole)
        btn_si.setStyleSheet(f"background-color: {DANGER}; color: white; font-weight: bold; padding: 6px 16px; border-radius: 6px;")
        btn_no = msg.addButton("No", QMessageBox.ButtonRole.NoRole)
        btn_no.setStyleSheet(f"background-color: {SUCCESS}; color: white; font-weight: bold; padding: 6px 16px; border-radius: 6px;")
        msg.setDefaultButton(btn_no)
        msg.exec()

        if msg.clickedButton() is btn_si:
            self._cancelar_lote()
        # "No": no hace nada, sigue en el registro actual tal cual estaba.

    def _cancelar_lote(self):
        self._lote_cancelado = True
        self._on_lote_cancelado()

    def _avanzar_lote(self):
        datos_confirmados = self.get_data()
        self._lote_resultados.append(datos_confirmados)
        vin_confirmado = str(datos_confirmados.get('VIN', '')).strip().upper()
        if vin_confirmado:
            self._vins_usados_en_lote.add(vin_confirmado)
        self._lote_indice += 1

        if self._lote_indice >= len(self._lote):
            # Lote completo: cada subclase decide qué hacer (ver
            # _on_lote_completado()/_on_lote_cancelado(), mismo patrón que
            # _on_formulario_confirmado()/_on_formulario_cancelado()).
            self._on_lote_completado()
            return

        self._mostrar_transicion_lote()

    def _mostrar_transicion_lote(self):
        """Overlay breve entre un registro y el siguiente: se oculta el
        formulario y se muestra "Cargando siguiente unidad" (con spinner)
        encima del mismo diálogo (nunca se cierra ni se vuelve a abrir una
        ventana)."""
        self._contenido_widget.setVisible(False)
        self._overlay_transicion.setVisible(True)
        QTimer.singleShot(350, self._cargar_siguiente_registro_lote)

    def _resetear_campos_a_default(self):
        """Vuelve cada campo a su estado inicial (mismos defaults que
        _create_widget) antes de precargar el siguiente registro del lote.
        TIPO DE FACTURACION se excluye del bucle genérico (su primer ítem
        del combo es "Cliente", no "-": ver _ORDEN_TIPO_FACTURACION) y se
        resetea aparte, junto con el estado interno que depende de él."""
        for campo, widget in self.inputs.items():
            if campo == 'TIPO DE FACTURACION':
                continue
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                if campo in _DEFAULTS_INICIALES:
                    # _set_combo_valor_precargado para combos NO editables
                    # (25-09-2026): MODELO/TIPO DE SERVICIO/TIPO DE CM
                    # siguen por defecto en "-" aunque ya no esté en su
                    # catálogo de opciones (ver _create_widget) -- setText
                    # directo silenciosamente no haría nada en un combo no
                    # editable si el texto no es un ítem existente.
                    if widget.isEditable():
                        widget.setCurrentText(_DEFAULTS_INICIALES[campo])
                    else:
                        self._set_combo_valor_precargado(widget, _DEFAULTS_INICIALES[campo])
                else:
                    widget.setCurrentIndex(0)
            elif campo in ('CHASIS', 'DURACIÓN (MESES)'):
                widget.setText("")
            elif campo in (
                'TÉRMINO CONTRATO', 'INICIO CONTRATO', 'FECHA DE BAJA', 'ESTADO DE ENTREGA',
                'INICIO', 'TERMINO', 'FECHA INICIO CM', 'FECHA TERMINO CM',
                'N CONTRATO 3PC', 'PAGO CM',
            ):
                widget.setText("-")
            else:
                widget.setText("")
            # Solo si tenía un estilo propio (ej. borde rojo de validación):
            # reaplicar una hoja vacía igual vuelve a calcular el estilo
            if widget.styleSheet():
                widget.setStyleSheet("")
            widget.setToolTip("")
            widget.blockSignals(False)

        self.chk_civ.setChecked(False)
        self.chk_sz.setChecked(False)

        self._tipo_facturacion_actual = _tipo_facturacion_default_para_forma_contrato(
            _DEFAULTS_INICIALES['FORMA DE CONTRATO']
        )
        widget_tf = self.inputs['TIPO DE FACTURACION']
        widget_tf.blockSignals(True)
        # _set_combo_valor_precargado (25-09-2026): igual que MODELO/TIPO DE
        # SERVICIO/TIPO DE CM, por si el default calculado fuera "-" (ya no
        # está en el catálogo base del combo, ver _create_widget).
        self._set_combo_valor_precargado(widget_tf, TIPO_FACTURACION_DISPLAY_MAP[self._tipo_facturacion_actual])
        widget_tf.setStyleSheet("")
        widget_tf.setToolTip("")
        widget_tf.blockSignals(False)

        self._modelo_manual = False
        self._tipo_cm_manual = False
        self._recalcular_etapa_gestion()
        self._actualizar_habilitacion_justtime_cm()
        self._actualizar_habilitacion_tipo_facturacion()
        hoy = datetime.now()
        self.combo_periodo_mes.setCurrentText(_MESES[hoy.month - 1])
        self.spin_periodo_anio.setValue(hoy.year)

    def _cargar_siguiente_registro_lote(self):
        self._resetear_campos_a_default()

        datos = self._lote[self._lote_indice]
        self._chasis_bi_actual = datos.get('_CHASIS_BI', '')
        _forma_contrato_registro = datos.get('FORMA DE CONTRATO') or _DEFAULTS_INICIALES['FORMA DE CONTRATO']
        self._tipo_facturacion_actual = datos.get('TIPO DE FACTURACION') or \
            _tipo_facturacion_default_para_forma_contrato(_forma_contrato_registro)
        self.progreso = (self._lote_indice + 1, len(self._lote))

        self._aplicar_datos_iniciales(datos)
        self._actualizar_progreso_visual()
        self._actualizar_boton_chasis_bi()
        self._actualizar_texto_guardar()
        self._validar_vin_duplicado()

        self._overlay_transicion.setVisible(False)
        self._contenido_widget.setVisible(True)

    # Color e ícono de cada tarjeta del resumen de confirmación
    _ESTILO_RESUMEN = {
        "Cliente": ('fa5s.building', '#1B2B4E', '#E6ECF6'),
        "Comercial": ('fa5s.file-contract', '#1B2B4E', '#E6ECF6'),
        "Operaciones": ('fa5s.truck', '#1B2B4E', '#E6ECF6'),
        "JustTime & CM": ('fa5s.stopwatch', '#1B2B4E', '#E6ECF6'),
    }
    # Datos del cliente que van en el encabezado del resumen y no se repiten en su tarjeta
    _RESUMEN_EN_ENCABEZADO = ('RUT', 'RAZÓN SOCIAL', 'VIN', 'CHASIS')

    def _crear_tarjeta_resumen(self, titulo, pares):
        """Tarjeta compacta del resumen de confirmación: encabezado y una fila
        por dato con valor (valores largos acortados con "..."). Los datos
        vacíos se juntan en una sola línea al final."""
        icono, color, suave = self._ESTILO_RESUMEN[titulo]
        card = QFrame()
        card.setObjectName("tarjetaResumen")
        card.setStyleSheet("QFrame#tarjetaResumen { background-color: white; border: 1px solid #E3E8F0; border-radius: 10px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(1, 1, 1, 6)
        lay.setSpacing(0)

        enc = QFrame()
        enc.setStyleSheet(f"QFrame {{ background-color: {suave}; border: none; border-top-left-radius: 9px; border-top-right-radius: 9px; }}")
        enc_lay = QHBoxLayout(enc)
        enc_lay.setContentsMargins(12, 5, 12, 5)
        enc_lay.setSpacing(7)
        lbl_icono = QLabel()
        lbl_icono.setPixmap(qta.icon(icono, color=color).pixmap(11, 11))
        lbl_icono.setStyleSheet("background: transparent; border: none;")
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 700; background: transparent; border: none;")
        enc_lay.addWidget(lbl_icono)
        enc_lay.addWidget(lbl_titulo)
        enc_lay.addStretch()
        lay.addWidget(enc)

        def vacio(valor):
            return str(valor).strip() in ('', '-', 'nan')

        llenos = [(c, v) for c, v in pares if not vacio(v)]
        vacios = [c for c, v in pares if vacio(v)]
        for i, (campo, valor) in enumerate(llenos):
            fila = QWidget()
            fila_lay = QHBoxLayout(fila)
            fila_lay.setContentsMargins(12, 3, 12, 3)
            fila_lay.setSpacing(10)
            lbl_campo = QLabel(_ETIQUETAS_CAMPO.get(campo, campo).capitalize())
            lbl_campo.setStyleSheet("color: #66748D; font-size: 10px; background: transparent; border: none;")
            lbl_valor = _EtiquetaElidida(valor)
            lbl_valor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            lbl_valor.setStyleSheet("color: #0F1B33; font-size: 11px; font-weight: 600; background: transparent; border: none;")
            fila_lay.addWidget(lbl_campo)
            fila_lay.addWidget(lbl_valor, 1)
            if i:
                separador = QFrame()
                separador.setFixedHeight(1)
                separador.setStyleSheet("background-color: #EEF1F6; border: none;")
                lay.addWidget(separador)
            lay.addWidget(fila)
        if vacios:
            nombres = ", ".join(_ETIQUETAS_CAMPO.get(c, c).capitalize() for c in vacios)
            lbl_vacios = QLabel(f"Sin dato: {nombres}")
            lbl_vacios.setWordWrap(True)
            lbl_vacios.setContentsMargins(12, 4, 12, 0)
            lbl_vacios.setStyleSheet("color: #A7B1C2; font-size: 10px; background: transparent; border: none;")
            lay.addWidget(lbl_vacios)
        lay.addStretch(1)
        return card

    def _confirmar_resumen(self):
        """Resumen compacto de todos los campos antes de guardar: encabezado
        con la empresa y el VIN y cuatro tarjetas en dos columnas, sin
        desplazamiento. Devuelve True si el usuario confirma ("Confirmar y
        guardar"), o False si elige volver al formulario (en cuyo caso no se
        modifica ni se limpia ningún dato ingresado)."""
        data = self.get_data()

        dialog = QDialog(self)
        dialog.setWindowTitle("Confirmar " + ("cambios" if self.modo_edicion else "nueva unidad"))
        dialog.setStyleSheet("QDialog { background-color: #F6F8FB; }")
        dialog.setFixedWidth(760)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        cabecera = QHBoxLayout()
        cabecera.setSpacing(10)
        icono = QLabel()
        icono.setFixedSize(32, 32)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(qta.icon('fa5s.clipboard-check', color='#1B2B4E').pixmap(15, 15))
        icono.setStyleSheet("background: #E6ECF6; border-radius: 10px;")
        titulo = QLabel("Confirmar " + ("cambios" if self.modo_edicion else "nueva unidad"))
        titulo.setStyleSheet("color: #0F1B33; font-size: 15px; font-weight: 700;")
        chip = QLabel(f"Periodo interno \u00b7 {data.get('PERIODO INTERNO', '')}")
        chip.setStyleSheet("background: #E6ECF6; color: #1B2B4E; font-size: 10px; font-weight: 700; padding: 4px 10px; border-radius: 10px;")
        cabecera.addWidget(icono)
        cabecera.addWidget(titulo, 1)
        cabecera.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(cabecera)

        # Encabezado de la empresa y la unidad
        ident = QFrame()
        ident.setObjectName("identResumen")
        ident.setStyleSheet("QFrame#identResumen { background: white; border: 1px solid #E3E8F0; border-radius: 10px; } "
                            "QLabel { background: transparent; border: none; }")
        ident_lay = QVBoxLayout(ident)
        ident_lay.setContentsMargins(12, 7, 12, 7)
        ident_lay.setSpacing(1)
        nombre = _EtiquetaElidida(data.get('RAZÓN SOCIAL', '') or 'Sin razón social')
        nombre.setStyleSheet("color: #0F1B33; font-size: 13px; font-weight: 700;")
        partes = [f"VIN {data.get('VIN', '')}"]
        for etiqueta, campo in (("Chasis", 'CHASIS'), ("RUT", 'RUT')):
            if data.get(campo):
                partes.append(f"{etiqueta} {data[campo]}")
        detalle = _EtiquetaElidida("  \u00b7  ".join(partes))
        detalle.setStyleSheet("color: #66748D; font-size: 10px;")
        ident_lay.addWidget(nombre)
        ident_lay.addWidget(detalle)
        layout.addWidget(ident)

        grupos = []
        for titulo_g, campos in _RESUMEN_GRUPOS:
            if titulo_g == "Cliente":
                campos = [c for c in campos if c not in self._RESUMEN_EN_ENCABEZADO]
            grupos.append((titulo_g, self._crear_tarjeta_resumen(titulo_g, [(c, data.get(c, '')) for c in campos])))
        tarjetas = dict(grupos)
        # Rejilla de 2 x 2: las tarjetas de una misma fila quedan del mismo alto
        columnas = QGridLayout()
        columnas.setSpacing(8)
        columnas.setColumnStretch(0, 1)
        columnas.setColumnStretch(1, 1)
        for posicion, nombre_g in enumerate(("Cliente", "Operaciones", "Comercial", "JustTime & CM")):
            columnas.addWidget(tarjetas[nombre_g], posicion // 2, posicion % 2)
        layout.addLayout(columnas)

        pie = QHBoxLayout()
        pie.setSpacing(8)
        btn_volver = QPushButton("Volver al formulario")
        btn_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_volver.setStyleSheet("QPushButton { background: white; border: 1px solid #D9DEE8; color: #3B4A66; padding: 7px 14px; border-radius: 8px; font-weight: 600; font-size: 11px; }")
        btn_volver.clicked.connect(dialog.reject)
        btn_confirmar = QPushButton(" Confirmar y guardar")
        btn_confirmar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_confirmar.setIcon(qta.icon('fa5s.check', color='white'))
        btn_confirmar.setStyleSheet("QPushButton { background: #1B2B4E; color: white; border: none; padding: 7px 16px; border-radius: 8px; font-weight: 700; font-size: 11px; }")
        btn_confirmar.clicked.connect(dialog.accept)
        pie.addStretch()
        pie.addWidget(btn_volver)
        pie.addWidget(btn_confirmar)
        layout.addLayout(pie)

        return dialog.exec() == QDialog.DialogCode.Accepted

    def get_data(self):
        data = {key: self._valor_widget(key) for key in self.inputs}

        # VIN y CHASIS siempre en mayúsculas: las bandejas buscan la unidad por
        # el VIN en mayúsculas y uno guardado en minúsculas no se encontraba.
        for campo in ('VIN', 'CHASIS'):
            if data.get(campo):
                data[campo] = data[campo].strip().upper()

        # Campos de fecha simples y de texto de JustTime/CM: si quedaron
        # vacíos, se guardan como "-" (mismo criterio que el resto del
        # proyecto usa para celdas vacías, ver _normalizar_vacios_a_guion en
        # comercial.py). DURACIÓN (MESES) NO entra en esta regla: vacío ahí
        # significa "pendiente", no "-" (ver DataFrameFormatter.calcular_termino).
        for campo in (
            'INICIO CONTRATO', 'TÉRMINO CONTRATO', 'FECHA DE BAJA', 'ESTADO DE ENTREGA',
            'INICIO', 'TERMINO', 'FECHA INICIO CM', 'FECHA TERMINO CM',
            'CONTRATO CREADO EN JUSTTIME', 'N CONTRATO 3PC', 'PAGO CM',
        ):
            if not data.get(campo):
                data[campo] = '-'

        # Periodo interno seleccionado por el usuario (o precargado), no el
        # mes actual inyectado en silencio.
        data['PERIODO INTERNO'] = normalizar_periodo_interno(
            f"{self.combo_periodo_mes.currentText()} - {self.spin_periodo_anio.value()}")

        # Columnas que no viven en este formulario (hoy solo OBSERVACIONES:
        # los campos de JustTime/CM y FECHA DE BAJA ya tienen su propio
        # widget desde las Fases 2 y 4): siempre "-" AL CREAR una unidad
        # nueva (definido con Javiera). En modo edición no se tocan, por si
        # ya tuvieran un dato real que este formulario no muestra ni debe
        # pisar con "-".
        if not self.modo_edicion:
            for campo in COLUMNAS_EXTRA_DEFAULT_GUION:
                data[campo] = '-'

        return data

    # ------------------------------------------------------------------
    # Precarga (modo edición / registro importado de Power BI)
    # ------------------------------------------------------------------
    def _parsear_periodo_interno(self, texto):
        """'Septiembre - 2026' -> (mes, año). Devuelve (None, None) si el
        texto no calza con ese formato (ej. vacío o valor corrupto).
        Comparación de mes insensible a mayúsculas/minúsculas (bug
        reportado 15-09-2026: PruebasFM trae valores como 'agosto - 2022',
        en minúscula, que no calzaban con '_MESES' -- capitalizado -- y la
        precarga fallaba en silencio, dejando el combo en el mes/año actual
        (default de "nueva unidad") en vez del período real de la unidad).
        Devuelve el nombre de mes ya normalizado a la capitalización de
        _MESES, que es la que espera combo_periodo_mes.setCurrentText."""
        if not texto or '-' not in texto:
            return None, None
        mes_txt, _, anio_txt = texto.partition('-')
        mes_txt = mes_txt.strip()
        anio_txt = anio_txt.strip()
        mes_canonico = next((m for m in _MESES if m.lower() == mes_txt.lower()), None)
        if mes_canonico is None or not anio_txt.isdigit():
            return None, None
        return mes_canonico, int(anio_txt)

    def _set_combo_valor_precargado(self, widget, valor_texto):
        """Selecciona `valor_texto` en un QComboBox NO editable al precargar
        datos (edición de unidad existente o registro de Power BI),
        preservando el valor real EXACTO aunque no esté entre las opciones
        oficiales del combo (otra capitalización, ej. 'CONECTADO' vs
        'Conectado', o un valor legado que ya no está en la lista, ej.
        FORMA DE CONTRATO='Revisar'). QComboBox.setCurrentText() en un combo
        NO editable ignora en silencio cualquier texto que no sea un match
        EXACTO (case-sensitive) con un ítem existente, dejando el combo en
        el valor que tuviera antes -- el default de "nueva unidad" (ver
        _DEFAULTS_INICIALES) -- en vez de mostrar el dato real. Esa fue la
        causa raíz del bug reportado 15-09-2026: al editar una unidad con
        un valor legado/con otra capitalización, el campo se guardaba
        silenciosamente con el default en vez de con el valor original,
        generando cambios que el usuario nunca pidió.

        Solo se reutiliza un ítem existente si calza EXACTO (case-sensitive,
        MatchCaseSensitive): reusar un ítem con otra capitalización (ej.
        seleccionar 'Conectado' para un valor guardado como 'CONECTADO')
        normalizaría el texto silenciosamente y generaría igual un cambio
        en el diff de guardado que el usuario no pidió. Si no hay match
        exacto, se agrega el valor tal cual como ítem nuevo en vez de
        descartarlo o normalizarlo."""
        idx = widget.findText(valor_texto, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)
        if idx < 0:
            widget.addItem(valor_texto)
            idx = widget.count() - 1
        widget.setCurrentIndex(idx)

    def _aplicar_datos_iniciales(self, datos):
        """Precarga el formulario con datos ya conocidos: edición de una
        unidad existente, o un registro ya mapeado desde Power BI. El CHASIS
        nunca se toma de `datos` (siempre se deriva del VIN, ver
        _auto_calculate_chasis) aunque `datos` traiga un valor -- p.ej. el
        Chasis que entrega Power BI se usa solo como identificador interno
        del registro durante la importación, nunca para llenar este campo."""
        for campo, widget in self.inputs.items():
            if campo in ('CHASIS', 'TIPO DE FACTURACION'):
                continue
            valor = datos.get(campo)
            if valor is None or valor == '':
                continue
            widget.blockSignals(True)
            if campo == 'TIPO DE SERVICIO':
                base, civ, sz = _partir_tipo_servicio(valor)
                self._set_combo_valor_precargado(widget, base)
                self.chk_civ.setChecked(civ)
                self.chk_sz.setChecked(sz)
            elif isinstance(widget, QComboBox):
                if widget.isEditable():
                    widget.setCurrentText(str(valor))
                else:
                    self._set_combo_valor_precargado(widget, str(valor))
            else:
                widget.setText(str(valor))
            widget.blockSignals(False)

        # TIPO DE FACTURACION se excluye del bucle genérico de arriba porque
        # el combo muestra texto amigable, no el valor REAL que trae `datos`
        # (ver _valor_widget/_on_tipo_facturacion_editado): un match exacto
        # de texto contra 'CLIENTE' nunca calzaría con el ítem 'Cliente'.
        # self._tipo_facturacion_actual ya viene sincronizado desde __init__/
        # _cargar_siguiente_registro_lote, pero se vuelve a fijar aquí de forma
        # explícita para que ambos (combo y estado interno) queden atados al
        # mismo `datos` y no puedan desincronizarse.
        valor_tipo_fact = datos.get('TIPO DE FACTURACION')
        if valor_tipo_fact:
            self._tipo_facturacion_actual = valor_tipo_fact
            widget_tf = self.inputs['TIPO DE FACTURACION']
            widget_tf.blockSignals(True)
            texto_amigable = TIPO_FACTURACION_DISPLAY_MAP.get(valor_tipo_fact)
            if texto_amigable:
                widget_tf.setCurrentText(texto_amigable)
            else:
                # Valor legado/no reconocido: se preserva tal cual como ítem
                # nuevo, mismo criterio que _set_combo_valor_precargado.
                self._set_combo_valor_precargado(widget_tf, str(valor_tipo_fact))
            widget_tf.blockSignals(False)
        self._actualizar_habilitacion_justtime_cm()
        self._actualizar_habilitacion_tipo_facturacion()
        self._actualizar_bloqueo_razon_social()
        self._actualizar_bloqueo_cdb()

        mes, anio = self._parsear_periodo_interno(datos.get('PERIODO INTERNO', ''))
        if mes and anio:
            self.combo_periodo_mes.setCurrentText(mes)
            self.spin_periodo_anio.setValue(min(anio, self.spin_periodo_anio.maximum()))

        # Recalculos que _aplicar_datos_iniciales bloqueó a propósito arriba:
        # CHASIS siempre se deriva del VIN ya precargado; MODELO/TÉRMINO/TIPO
        # DE CM solo se recalculan si `datos` no trajo ya un valor explícito
        # para no pisar lo que vino de Power BI o de la unidad existente.
        self._auto_calculate_chasis()
        if not datos.get('MODELO'):
            self._auto_calculate_modelo()
        if not datos.get('TÉRMINO CONTRATO'):
            self._auto_calculate_termino()
        else:
            # TÉRMINO CONTRATO vino precargado directo (unidad existente o
            # registro de Power BI): _auto_calculate_termino() no corre acá
            # arriba, así que el color de "vencido" se aplica aparte sobre
            # el valor ya precargado.
            self._actualizar_color_termino_contrato()
        if not datos.get('TIPO DE CM'):
            self._autocompletar_tipo_cm()
        # PAGO CM: la precarga (arriba) setea el texto crudo con blockSignals,
        # así que el autoformateo de moneda nunca se disparó -- se aplica
        # aquí explícitamente para que se vea "$X.XXX" también al editar.
        self._on_pago_cm_changed(self.inputs['PAGO CM'].text())
        # ETAPA GESTIÓN: si `datos` ya trae un valor real (unidad existente
        # o registro de Power BI), se preserva tal cual -- igual criterio
        # que MODELO/TÉRMINO CONTRATO arriba, para no recalcular ni pisar un
        # valor real (incluida una corrección manual previa) solo por abrir
        # el formulario. Si no trae nada, se calcula con la regla central
        # (unidad nueva sin ETAPA GESTIÓN propia todavía).
        if datos.get('ETAPA GESTIÓN'):
            self._aplicar_color_etapa_gestion(self.inputs['ETAPA GESTIÓN'].currentText())
        else:
            self._recalcular_etapa_gestion()

        # Re-bloquea tras _actualizar_habilitacion_justtime_cm de arriba (ver
        # docstring de _aplicar_restriccion_alta_general): necesario en modo
        # lote, donde este método se vuelve a llamar por cada registro nuevo.
        if self._restringir_alta_desde_general:
            self._aplicar_restriccion_alta_general()
        self._actualizar_resumen()


# ==========================================================================
# Subclases concretas (25-09-2026): _ComercialUnidadFormMixin de arriba
# concentra toda la presentación/validación/datos; estas dos clases solo
# aportan el ciclo de vida Qt específico de cada contexto de uso.
# ==========================================================================
class ComercialAgregarDialog(_ComercialUnidadFormMixin, QDialog):
    """Ventana modal de Gestión de Unidades. Ya no la usa ningún flujo real
    (25-09-2026: la importación Power BI también pasó a reutilizar
    ComercialUnidadFormWidget -- ver iniciar_lote() más abajo y
    src/ui/importar_powerbi.py -- a pedido explícito: "me abre una pestaña
    en vez de rellenar el formulario que ya tengo al frente"). Se conserva
    la clase (y su capacidad de modo lote, heredada del mixin) por si algún
    consumidor futuro necesitara de nuevo un diálogo bloqueante aparte."""

    def __init__(self, flotas_unicas, dropdown_options, df_comercial=None, parent=None,
                 datos_iniciales=None, modo_edicion=False, progreso=None, registros_lote=None,
                 restringir_activacion=False, forzar_activacion_pendiente=False,
                 restringir_alta_desde_general=False, restringir_vigentes=False):
        QDialog.__init__(self, parent)
        self._init_form(
            flotas_unicas, dropdown_options, df_comercial, parent,
            datos_iniciales, modo_edicion, progreso, registros_lote,
            restringir_activacion, forzar_activacion_pendiente,
            restringir_alta_desde_general, restringir_vigentes,
        )

    def _on_formulario_confirmado(self):
        self.accept()

    def _on_formulario_cancelado(self):
        self.reject()

    def _on_lote_completado(self):
        self.accept()

    def _on_lote_cancelado(self):
        self.reject()


class ComercialUnidadFormWidget(_ComercialUnidadFormMixin, QWidget):
    """Mismo formulario que ComercialAgregarDialog, pero como QWidget
    embebible dentro de la pestaña "Unidad nueva" de comercial.py
    (ComercialModule), en vez de una ventana modal. También soporta modo
    lote (ver iniciar_lote() más abajo) -- la importación Power BI ya no
    abre ComercialAgregarDialog como ventana aparte (25-09-2026, corrección
    a pedido explícito: "me abre una pestaña en vez de rellenar el
    formulario que ya tengo al frente"), reutiliza esta misma instancia.

    En vez de crear una instancia nueva por cada alta/edición/lote (como
    hacía el diálogo modal), esta misma instancia persiste mientras el
    módulo Comercial está abierto y se reconfigura en el lugar entre modo
    "crear"/"editar"/"lote" -- ver resetear_para_crear()/cargar_para_editar()/
    iniciar_lote(). Emite formulario_confirmado(dict)/formulario_cancelado()
    y lote_completado(list)/lote_cancelado() en vez de accept()/reject():
    quien la contiene (ComercialModule/iniciar_importacion_power_bi) decide
    qué hacer con los datos."""

    _MOSTRAR_PASO_OPERACIONES = False

    formulario_confirmado = pyqtSignal(dict)
    formulario_cancelado = pyqtSignal()
    lote_completado = pyqtSignal(list)
    lote_cancelado = pyqtSignal()
    nuevo_contrato_solicitado = pyqtSignal()

    def __init__(self, flotas_unicas, dropdown_options, df_comercial=None, parent=None,
                 datos_iniciales=None, modo_edicion=False,
                 restringir_activacion=False, forzar_activacion_pendiente=False,
                 restringir_vigentes=False):
        QWidget.__init__(self, parent)
        self._btn_nuevo_contrato = None
        self._init_form(
            flotas_unicas, dropdown_options, df_comercial, parent,
            datos_iniciales, modo_edicion, None, None,
            restringir_activacion, forzar_activacion_pendiente,
            False, restringir_vigentes,
        )

    def showEvent(self, event):
        # A propósito NO se llama _fit_to_screen() (heredado del mixin,
        # pensado para una ventana top-level): este widget vive embebido
        # dentro de la pestaña "Unidad nueva", redimensionarse/centrarse
        # contra la pantalla rompería el layout del contenedor.
        QWidget.showEvent(self, event)

    def _on_formulario_confirmado(self):
        self.formulario_confirmado.emit(self.get_data())

    def _on_formulario_cancelado(self):
        self.formulario_cancelado.emit()

    def _on_lote_completado(self):
        self.lote_completado.emit(self._lote_resultados)

    def _on_lote_cancelado(self):
        self.lote_cancelado.emit()

    def iniciar_lote(self, registros_lote, restringir_alta_desde_general=True):
        """Arranca el modo lote (importación Power BI) sobre esta instancia
        ya construida y visible en "Unidad nueva" (25-09-2026, reemplaza a
        pasar `registros_lote` al construir ComercialAgregarDialog -- ver
        docstring de la clase). Replica el mismo estado que antes armaba
        _init_form al recibir `registros_lote`, pero disparado sobre una
        instancia persistente en vez de al crearla: usa la misma maquinaria
        de _avanzar_lote/_mostrar_transicion_lote/_cargar_siguiente_registro_lote
        del mixin (construida siempre en _setup_ui, sin importar el modo),
        solo que el primer registro se precarga aquí en vez de en __init__."""
        self._configurar_modo_multiple(1)
        self.modo_edicion = False
        self._vin_original = None
        self._restringir_activacion = False
        self._forzar_activacion_pendiente = False
        self._restringir_vigentes = False
        self._restringir_alta_desde_general = restringir_alta_desde_general

        self._modo_lote = True
        self._lote = list(registros_lote)
        self._lote_indice = 0
        self._lote_resultados = []
        self._lote_cancelado = False
        self._vins_usados_en_lote = set()

        self._habilitar_todos_los_campos()
        self._resetear_campos_a_default()

        datos = self._lote[0]
        self._chasis_bi_actual = datos.get('_CHASIS_BI', '')
        _forma_contrato_registro = datos.get('FORMA DE CONTRATO') or _DEFAULTS_INICIALES['FORMA DE CONTRATO']
        self._tipo_facturacion_actual = datos.get('TIPO DE FACTURACION') or \
            _tipo_facturacion_default_para_forma_contrato(_forma_contrato_registro)
        self.progreso = (1, len(self._lote))

        self._aplicar_datos_iniciales(datos)
        if self._restringir_alta_desde_general:
            self._aplicar_restriccion_alta_general()

        self._actualizar_progreso_visual()
        self._actualizar_boton_chasis_bi()
        self._actualizar_titulo()
        self._actualizar_texto_guardar()
        self.tabs.setCurrentIndex(0)
        self._validar_vin_duplicado()

    # ----------------------------------------------------------------
    # Alternar entre modo crear / editar sobre la misma instancia
    # ----------------------------------------------------------------
    def actualizar_datos_comercial(self, df_comercial):
        """Refresca los lookups (RUT->Razón Social/CDB/Ejecutivo, CDB->Flota)
        y el set de VIN existentes contra el df_comercial vigente -- se
        llama cada vez que se entra a modo crear/editar, porque a
        diferencia del diálogo modal (que se creaba de nuevo con datos
        frescos cada vez) esta instancia persiste y df_comercial puede
        haber cambiado entretanto (guardados, recargas)."""
        self._rut_lookup, self._flota_by_cdb = self._construir_lookups(df_comercial)
        self._ejecutivos_todos = self._construir_lista_ejecutivos(df_comercial)
        combo_ejecutivo = self.inputs.get('EJECUTIVO')
        if combo_ejecutivo is not None:
            texto = combo_ejecutivo.currentText()
            combo_ejecutivo.blockSignals(True)
            combo_ejecutivo.clear()
            combo_ejecutivo.addItems([""] + self._ejecutivos_todos)
            combo_ejecutivo.setCurrentText(texto)
            combo_ejecutivo.blockSignals(False)
        self._vins_existentes = set()
        if isinstance(df_comercial, pd.DataFrame) and not df_comercial.empty and 'VIN' in df_comercial.columns:
            self._vins_existentes = set(df_comercial['VIN'].dropna().astype(str).str.strip().str.upper())
            self._vins_existentes.discard('')
        self._vins_con_contrato_abierto = comercial_services.vins_con_contrato_abierto(df_comercial)

    def _habilitar_todos_los_campos(self):
        """Deshace cualquier restricción de un modo anterior (Operaciones
        de solo lectura, ESTADO COMERCIAL recortado, etc.) antes de aplicar
        las que correspondan al nuevo modo -- necesario porque esta
        instancia se reutiliza en vez de crearse de nuevo cada vez (ver
        _aplicar_restriccion_activacion/_aplicar_restriccion_vigentes, que
        antes solo se aplicaban una vez sobre un formulario recién creado).
        ETAPA GESTIÓN queda fuera: siempre de solo lectura, en cualquier
        modo (ver combo_etapa.setEnabled(False) en _setup_ui)."""
        for campo, widget in self.inputs.items():
            if campo == 'ETAPA GESTIÓN':
                continue
            widget.setEnabled(True)
            if campo == 'RAZÓN SOCIAL':
                widget.setToolTip("")
                self._razon_bloqueada = False
            elif campo == 'CDB':
                widget.setToolTip("")
                self._cdb_bloqueado = False
        # Insignia de "Operaciones" (ver _aplicar_restriccion_operaciones_solo_lectura/
        # _aplicar_restriccion_vigentes) vuelve a "Editable" -- sin esto,
        # pasar de una edición restringida a modo crear dejaba la insignia
        # "🔒 Bloqueado" pegada aunque los campos ya estuvieran habilitados.
        self._set_badge_bloqueo('operativa', True)
        for extra in (self.combo_periodo_mes, self.spin_periodo_anio, self.chk_civ, self.chk_sz):
            extra.setEnabled(True)
        self._reiniciar_estado_contrato()
        self._restringir_estado_comercial_alta(False)
        # FORMA DE CONTRATO puede haber quedado con el catálogo recortado
        # por _sincronizar_tipo_facturacion_con_forma_contrato de una edición
        # anterior con restricciones -- _resetear_campos_a_default (llamado
        # justo después por resetear_para_crear/cargar_para_editar) vuelve a
        # dejar TIPO DE FACTURACION en su estado por defecto, así que no
        # hace falta reconstruirlo aquí aparte.

    def _exigir_forma_contrato_real(self, exigir):
        """En "Nuevo contrato" la forma de contrato no puede ser "Sin
        Contrato" (solo entra así desde Power BI): se quita esa opción y el
        combo parte en "-" para obligar a elegir otra. Con `exigir` False
        vuelve el catálogo completo."""
        combo = self.inputs['FORMA DE CONTRATO']
        actual = combo.currentText().strip()
        opciones = [v for v in self.dropdown_options.get('FORMA DE CONTRATO', []) if v != '-']
        if exigir:
            opciones = ['-'] + [v for v in opciones if v.strip().upper() != 'SIN CONTRATO']
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(opciones)
        combo.blockSignals(False)
        destino = '-' if exigir else (actual if actual not in ('', '-') else _DEFAULTS_INICIALES['FORMA DE CONTRATO'])
        self._set_combo_valor_precargado(combo, destino)
        self._sincronizar_tipo_facturacion_con_forma_contrato()
        self._autocompletar_tipo_cm()
        self._sincronizar_estado_con_contrato()
        self._actualizar_habilitacion_tipo_facturacion()
        self._actualizar_resumen()

    def _reiniciar_estado_contrato(self):
        era_nuevo_contrato = self.modo_nuevo_contrato
        self.modo_nuevo_contrato = False
        self.modo_renovacion = False
        if era_nuevo_contrato:
            self._exigir_forma_contrato_real(False)
            self._desbloquear_justtime_nuevo_contrato()
        self._vin_contrato_nuevo = ''
        self._id_contrato = ''
        self._contrato_cerrado = False
        self._puede_nuevo_contrato = False
        boton = getattr(self, '_btn_nuevo_contrato', None)
        if boton is not None:
            boton.setVisible(False)

    def _desbloquear_justtime_nuevo_contrato(self):
        for campo in _CAMPOS_BLOQUE_JUSTTIME:
            self.inputs[campo].setEnabled(True)
        self._actualizar_habilitacion_justtime_cm()

    def _bloquear_periodo_interno(self):
        """El periodo interno solo se edita a mano cuando el valor guardado no
        es un 'mes - año' estándar (p. ej. 'No aplica')."""
        for extra in (self.combo_periodo_mes, self.spin_periodo_anio):
            extra.setEnabled(False)

    def _bloquear_contrato_cerrado(self):
        """Contrato en baja: solo lectura, con acceso a crear un contrato nuevo."""
        for widget in self.inputs.values():
            widget.setEnabled(False)
        for extra in (self.combo_periodo_mes, self.spin_periodo_anio, self.chk_civ, self.chk_sz):
            extra.setEnabled(False)
        self.btn_save.setEnabled(False)
        if getattr(self, '_btn_nuevo_contrato', None) is None:
            boton = QPushButton(" Crear nuevo contrato")
            boton.setIcon(qta.icon('fa5s.plus', color='#1F7A55'))
            boton.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            boton.setAutoDefault(False)
            boton.setStyleSheet(
                "QPushButton { background-color: #E7F4EE; color: #1F7A55; border: 1px solid #1F7A55; border-radius: 8px;"
                " padding: 6px 14px; font-weight: 600; }"
                "QPushButton:hover { background-color: #D3EDE0; }")
            boton.clicked.connect(self.nuevo_contrato_solicitado.emit)
            self.agregar_boton_pie(boton)
            self._btn_nuevo_contrato = boton
        self._btn_nuevo_contrato.setVisible(self._puede_nuevo_contrato)

    def _restringir_estado_comercial_alta(self, restringir=True):
        """Reconstruye el combo ESTADO COMERCIAL desde el catálogo. Con
        `restringir` (alta de unidad nueva) excluye Vigente, Vencido, Baja y
        Baja Solicitada (quedan "Revisar" y "Activación Pendiente"); sin él
        restaura el catálogo completo para editar/importar."""
        self._estado_alta_restringido = restringir
        bloqueados = {'Vigente', 'Vencido', 'Baja', 'Baja Solicitada'} if restringir else set()
        combo = self.inputs['ESTADO COMERCIAL']
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([
            v for v in self.dropdown_options.get('ESTADO COMERCIAL', [])
            if v != '-' and v not in bloqueados
        ])
        combo.blockSignals(False)

    def agregar_boton_pie(self, widget):
        """Agrega `widget` al grupo izquierdo de la fila de Cancelar/Guardar
        Registro (25-09-2026, a pedido explícito: "Importar Excel Power BI"
        pasa a vivir abajo a la izquierda junto al botón de restablecer, en
        vez de a la derecha -- ver ComercialModule._asegurar_unidad_nueva_form
        en comercial.py, único llamador)."""
        self._btn_layout_izquierda.addWidget(widget)

    def _configurar_modo_multiple(self, cantidad):
        """Con varias unidades a la vez se oculta el paso "Empresa & Unidad": solo se editan
        Comercial y JustTime & CM, y lo que se cambie vale para todas."""
        multiple = cantidad > 1
        self.cantidad_multiple = cantidad
        self._primer_paso = 1 if multiple else 0
        self.tabs.setTabVisible(0, not multiple)
        if getattr(self, '_botones_paso', None):
            self._botones_paso[0].setVisible(not multiple)

    def resetear_para_crear(self):
        """Deja el formulario listo para dar de alta una unidad nueva:
        mismo estado que tenía ComercialAgregarDialog recién creado sin
        `datos_iniciales` ni `modo_edicion`."""
        self._configurar_modo_multiple(1)
        self.modo_edicion = False
        self._restringir_activacion = False
        self._forzar_activacion_pendiente = False
        self._restringir_vigentes = False
        self._restringir_alta_desde_general = False
        self._vin_original = None
        # Sale del modo lote (25-09-2026, corrección de bug real reportado
        # por el usuario: sin esto, el badge de progreso "N / total" y el
        # botón de CHASIS de Power BI quedaban pegados arriba a la izquierda
        # después de terminar o cancelar una importación -- este es el único
        # punto de salida real de un lote, ver ComercialModule._entrar_modo_crear_unidad).
        self._modo_lote = False
        self.progreso = None
        self._chasis_bi_actual = ''
        self._actualizar_progreso_visual()
        self._actualizar_boton_chasis_bi()
        self._habilitar_todos_los_campos()
        self._restringir_estado_comercial_alta(True)
        self._resetear_campos_a_default()
        self._sincronizar_estado_con_contrato()
        # Operaciones queda siempre de solo lectura en este formulario
        # embebido en Comercial (25-09-2026, a pedido explícito: "es raro
        # que se pueda editar algo de Operaciones en Comercial") -- esos
        # campos se gestionan desde el módulo Operaciones, no desde acá.
        self._aplicar_restriccion_operaciones_solo_lectura()
        self._actualizar_titulo()
        self._actualizar_texto_guardar()
        self.tabs.setCurrentIndex(0)
        self._validar_vin_duplicado()

    def cargar_para_editar(self, datos_iniciales, restringir_activacion=False,
                            forzar_activacion_pendiente=False, restringir_vigentes=False):
        """Precarga la unidad `datos_iniciales` en modo edición, con las
        mismas restricciones que antes aplicaba _handle_editar_unidad al
        abrir ComercialAgregarDialog(modo_edicion=True, ...)."""
        self._configurar_modo_multiple(1)
        self.modo_edicion = True
        self._restringir_activacion = restringir_activacion
        self._forzar_activacion_pendiente = forzar_activacion_pendiente
        self._restringir_vigentes = restringir_vigentes
        self._restringir_alta_desde_general = False
        self._vin_original = (datos_iniciales or {}).get('VIN', '').strip().upper()
        estado_jt = str((datos_iniciales or {}).get('CONTRATO CREADO EN JUSTTIME', '') or '').strip()
        self._jt_auto_edicion = bool(restringir_activacion) and estado_jt in ('', JUSTTIME_ESTADO_NO_APLICA)
        self._fechas_justtime_guardadas = None
        self._jt_original = None

        self._habilitar_todos_los_campos()
        self._resetear_campos_a_default()

        _forma_contrato_inicial = (datos_iniciales or {}).get('FORMA DE CONTRATO') or _DEFAULTS_INICIALES['FORMA DE CONTRATO']
        self._tipo_facturacion_actual = (datos_iniciales or {}).get('TIPO DE FACTURACION') or \
            _tipo_facturacion_default_para_forma_contrato(_forma_contrato_inicial)

        self._aplicar_datos_iniciales(datos_iniciales or {})
        datos_jt = datos_iniciales or {}
        self._jt_original = {
            'tipo': str(datos_jt.get('TIPO DE FACTURACION', '')).strip().upper(),
            'estado': str(datos_jt.get('CONTRATO CREADO EN JUSTTIME', '') or '').strip() or JUSTTIME_ESTADO_NO_APLICA,
            'inicio': str(datos_jt.get('INICIO', '') or '').strip(),
            'termino': str(datos_jt.get('TERMINO', '') or '').strip(),
        }
        self._id_contrato = str((datos_iniciales or {}).get('ID', '')).strip()
        if self._parsear_periodo_interno((datos_iniciales or {}).get('PERIODO INTERNO', ''))[0]:
            self._bloquear_periodo_interno()

        if self._restringir_activacion:
            self._aplicar_restriccion_activacion(self._forzar_activacion_pendiente)
        if self._restringir_vigentes:
            self._aplicar_restriccion_vigentes()
        # Operaciones queda siempre de solo lectura en este formulario
        # embebido en Comercial (25-09-2026, a pedido explícito: "es raro
        # que se pueda editar algo de Operaciones en Comercial") -- ya
        # estaba bloqueada por las 2 restricciones de arriba cuando
        # aplican; esta llamada cubre también la edición sin restricciones
        # especiales, que antes dejaba Operaciones editable. Es idempotente
        # (solo deshabilita campos y fija la insignia), así que repetirla
        # cuando ya se aplicó arriba no tiene efecto adicional.
        self._aplicar_restriccion_operaciones_solo_lectura()
        self._sincronizar_estado_con_contrato()

        self._contrato_cerrado = comercial_services.es_contrato_cerrado((datos_iniciales or {}).get('ESTADO COMERCIAL', ''))
        self._puede_nuevo_contrato = comercial_services.puede_crear_contrato(
            (datos_iniciales or {}).get('ESTADO COMERCIAL', ''), (datos_iniciales or {}).get('ESTADO DE ACTIVACIÓN ACTUAL', ''))
        self._actualizar_titulo()
        self._actualizar_texto_guardar()
        self.tabs.setCurrentIndex(0)
        self._validar_vin_duplicado()
        if self._contrato_cerrado:
            self._bloquear_contrato_cerrado()
        self._actualizar_resumen()

    def cargar_para_nuevo_contrato(self, datos_unidad, renovacion=False, cantidad=1):
        """Formulario para un contrato nuevo sobre una unidad que ya existe
        (reactivación): hereda los datos de la unidad y del cliente, deja las
        condiciones comerciales en blanco y fija el VIN. Entra en Activación
        Pendiente/Activando como una unidad por activar. Solo se permite si el
        contrato actual de la unidad está cerrado (ver _vin_duplicado).

        Con `renovacion` (contrato Vigente o Vencido que se reemplaza por otro,
        20-10-2026) la unidad ya está activa: conserva ejecutivo, tipo de
        servicio y todos los datos de Operaciones (solo lectura); ESTADO
        COMERCIAL queda Vigente y bloqueado; INICIO CONTRATO es hoy; DURACIÓN
        queda vacía y la forma de contrato se elige (sin "Sin Contrato")."""
        datos_unidad = datos_unidad or {}
        self._configurar_modo_multiple(cantidad if renovacion else 1)
        self.modo_edicion = False
        self._restringir_activacion = not renovacion
        self._forzar_activacion_pendiente = not renovacion
        self._restringir_vigentes = False
        self._restringir_alta_desde_general = False
        self._vin_original = None
        self._modo_lote = False
        self.progreso = None
        self._chasis_bi_actual = ''
        self._actualizar_progreso_visual()
        self._actualizar_boton_chasis_bi()

        self._habilitar_todos_los_campos()
        self._restringir_estado_comercial_alta(not renovacion)
        self._resetear_campos_a_default()
        self._tipo_facturacion_actual = _tipo_facturacion_default_para_forma_contrato(_DEFAULTS_INICIALES['FORMA DE CONTRATO'])
        conservados = _CAMPOS_RENOVACION_CONSERVADOS if renovacion else ()
        heredados = {k: v for k, v in datos_unidad.items()
                     if k not in _CAMPOS_CONDICION_CONTRATO or k in conservados}
        self._aplicar_datos_iniciales(heredados)
        self._aplicar_restriccion_activacion(not renovacion)
        self._aplicar_restriccion_operaciones_solo_lectura()
        self._bloquear_periodo_interno()
        self._sincronizar_estado_con_contrato()
        self.inputs['VIN'].setEnabled(False)

        self.modo_nuevo_contrato = True
        self.modo_renovacion = renovacion
        self._vin_contrato_nuevo = str(datos_unidad.get('VIN', '')).strip().upper()
        if renovacion:
            inicio = self.inputs['INICIO CONTRATO']
            inicio.setText(datetime.now().strftime("%d-%m-%Y"))
            duracion = self.inputs['DURACIÓN (MESES)']
            duracion.blockSignals(True)
            duracion.setText('')
            duracion.blockSignals(False)
            self.inputs['TÉRMINO CONTRATO'].setText('')
        else:
            self._set_combo_valor_precargado(self.inputs['TIPO DE SERVICIO'], 'Basico')
            self.inputs['INICIO CONTRATO'].setText('')
        self._exigir_forma_contrato_real(True)
        if renovacion:
            estado = self.inputs['ESTADO COMERCIAL']
            estado.blockSignals(True)
            self._set_combo_valor_precargado(estado, 'Vigente')
            estado.blockSignals(False)
            estado.setEnabled(False)
            self._recalcular_etapa_gestion()
        self._actualizar_titulo()
        self._actualizar_texto_guardar()
        self.tabs.setCurrentIndex(self._primer_paso)
        self._validar_vin_duplicado()
        self._actualizar_resumen()
