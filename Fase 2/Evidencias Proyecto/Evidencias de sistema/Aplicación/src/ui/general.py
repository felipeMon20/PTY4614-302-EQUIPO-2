import os
import re
import unicodedata
import pandas as pd
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton,
                             QStackedWidget, QListWidget, QListWidgetItem, QHeaderView, QDialog,
                             QMessageBox, QApplication, QScrollArea, QMenu, QWidgetAction, QLineEdit,
                             QComboBox, QGridLayout, QSizePolicy, QProgressBar, QGraphicsDropShadowEffect, QCheckBox)
from PyQt6.QtCore import Qt, QSize, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QAction, QActionGroup, QPixmap, QIcon
from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.hilos import iniciar_hilo_retenido
from src.core.constants import (COL_RAZON_SOCIAL, COL_RUT, COL_INDUSTRIA, COL_CDB, COL_CDB_FLOTA, COL_VIN, COL_CHASIS,
                                COL_FLOTA_VC, COL_TIPO_SERVICIO, COL_ESTADO_ACTIVACION, COL_EJECUTIVO,
                                COL_ETAPA_GESTION, COL_MODELO, COL_FLOTA_VC_2, COL_FORMA_CONTRATO,
                                COL_ESTADO_COMERCIAL, COL_INICIO_CONTRATO, COL_DURACION_MESES,
                                COL_TERMINO_CONTRATO, COL_PERIODO_INTERNO, COL_ESTADO_ENTREGA,
                                COL_FECHA_BAJA, COL_TIPO_FACTURACION, COL_CONTRATO_JUSTTIME,
                                COL_FECHA_INICIO_FACT, COL_FECHA_TERMINO_FACT, COL_ESTADO_CM, COL_ID,
                                ETAPA_GESTION_COLORES, FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ)
from src.core.dataframe_formatter import DataFrameFormatter
from src.services import comercial_services, contactos_service, powerbi_cache_service
from src.ui.custom_table import VolvoTableWidget, PandasTableModel
from src.ui.comercial import SaveExcelThread
from src.ui.contactos_agregar import ContactosAddDialog
from src.ui.contactos import AddContactoThread
from src.ui.esqueleto_carga import EsqueletoCarga
from src.ui.transiciones import TransicionFundidoSubida
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *
from config.settings import POWERBI_EXCEL_PATH

# Azul oscuro Volvo (mismo de las barras de Comercial/Administración) y sus apoyos
AZUL = "#1B2B4E"
AZUL_HOVER = "#2C4170"
TINTE_CLARO = "#EEF1F6"
LINEA_AZUL = "#C9D1E0"
TEXTO_SOBRE_AZUL = "#C9D4EA"

QSS_BOTON_AZUL = (
    f"QPushButton {{ background-color: {AZUL}; color: white; border: 1px solid {AZUL}; border-radius: 9px; "
    "padding: 8px 14px; font-weight: 700; }"
    f"QPushButton:hover {{ background-color: {AZUL_HOVER}; border: 1px solid {AZUL_HOVER}; }}"
    "QPushButton:disabled { background-color: #C5CCDA; border: 1px solid #C5CCDA; color: #F3F5F9; }"
)


def _boton_azul(btn):
    btn.setStyleSheet(QSS_BOTON_AZUL)


QSS_BOTON_MINIMO = (
    f"QPushButton {{ background-color: transparent; color: {AZUL}; border: 1px solid {BORDER}; border-radius: 8px; "
    "padding: 5px 12px; font-size: 11px; font-weight: 700; }"
    f"QPushButton:hover {{ background-color: #F3F5F9; border: 1px solid {AZUL}; }}"
    "QPushButton:disabled { background-color: transparent; border: 1px solid #E4E8F0; color: #B3BBCB; }"
)


def _boton_minimo(btn):
    btn.setStyleSheet(QSS_BOTON_MINIMO)


def _con_transicion_derecha(metodo):
    """Anima la caja derecha (foto de lo anterior que se funde y contenido
    nuevo que sube un poco) cada vez que cambia el cliente o la unidad."""
    def envoltura(self, *args, **kwargs):
        foto = self._foto_caja_derecha()
        resultado = metodo(self, *args, **kwargs)
        self._animar_caja_derecha(foto)
        return resultado
    envoltura.__name__ = metodo.__name__
    envoltura.__doc__ = metodo.__doc__
    return envoltura


def _tarjeta_blanca(frame):
    """Tarjeta blanca para el contenido de la caja derecha (que es azul oscuro)."""
    frame.setObjectName("tarjetaBlanca")
    frame.setStyleSheet(f"QFrame#tarjetaBlanca {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}")

# 'Industria/s' se muestra en la tarjeta de Cliente (GeneralClienteCard,
# rediseño a tarjetas 20-09-2026, a pedido explícito) además de seguir
# usándose para el filtro por industria de Unidades y el detalle de
# cliente en la caja derecha.
COLUMNAS_CLIENTES = ['Razón Social', 'RUT', 'Industria/s', 'CDB', 'Total unidades', 'Total flotas', 'Clave', 'Busqueda']

# CDB es la entidad principal (regla de negocio confirmada 07-09-2026,
# corregida el mismo día: un CDB SÍ puede tener múltiples valores de Flota
# VC — distintas áreas/agrupaciones internas de la misma empresa — por lo
# que Flota VC nunca identifica de forma única a un CDB. CDB va primero en
# la tabla para reflejar esa jerarquía; cada fila es un par (CDB, Flota VC).

# Listado general de unidades (caja izquierda, apartado "Unidades"): todas
# las VIN de Comercial, una fila por unidad, sin agrupar. Misma fuente que
# Cliente/Flota (self.df_comercial_raw). CDB y Razón Social se incluyen para
# que la tabla derecha de detalle (por CDB) pueda filtrar este mismo df sin
# reconsultar Comercial.
# Anchos máximos de las dos cajas de Clientes y Flota (px)
ANCHO_MAX_CAJA_IZQUIERDA = 940
ANCHO_MAX_CAJA_DERECHA = 690
COLOR_CDB_FLOTA_MINORITARIO = "#E8740C"

COLUMNAS_UNIDADES = ['VIN', 'CHASIS', 'Razón Social', 'CDB', 'RUT', 'Flota VC', 'Estado Activación',
                      'Industria/s', 'ETAPA GESTIÓN', 'Estado Comercial', 'Forma de Contrato',
                      'Tipo de Facturación', 'Inicio Contrato', 'Término Contrato', 'Periodo Interno',
                      'Tipo de Servicio', 'CDB Flota', 'Clave']
# Columnas visibles en la tabla de la izquierda (caja izquierda, apartado
# "Unidades"): CDB y Flota VC quedan fuera de la vista (a pedido explícito)
# pero se conservan en df_unidades_base porque los filtros y el detalle de
# la caja derecha los siguen necesitando. VIN también
# queda fuera de la vista desde el 10-09-2026 (a pedido de Javiera) pero se
# conserva en df_unidades_base y en COLUMNAS_BUSQUEDA_UNIDADES: el buscador
# global de MainWindow sigue encontrando unidades por VIN exactamente igual
# que antes, solo que la columna no se pinta en pantalla (mismo mecanismo
# que ya se usaba para ocultar CDB/Flota VC). 'Industria/s' (antes visible
# solo en la tabla de Clientes) y 'ETAPA GESTIÓN' (antes no visible en
# ningún lugar de este módulo) se agregan aquí a pedido de Javiera.
COLUMNAS_UNIDADES_VISIBLES = ['CHASIS', 'Razón Social', 'Estado Activación', 'Industria/s', 'ETAPA GESTIÓN']

# Buscador global de MainWindow (self.search_bar en main_window.py), aplicado
# únicamente a la caja izquierda -> Unidades (ver GeneralModule.filter_table
# / _aplicar_busqueda_unidades): un término puede coincidir en cualquiera de
# estas 4 columnas. CDB, VIN y RUT (agregado 28-09-2026, a pedido explícito)
# no se muestran en la tabla (ver COLUMNAS_UNIDADES_VISIBLES) pero siguen
# siendo buscables porque df_unidades_base los conserva.
COLUMNAS_BUSQUEDA_UNIDADES = ['Razón Social', 'VIN', 'CDB', 'RUT']

# Agrupación de las 33 columnas de una unidad (df_comercial_raw, ya con las
# ~32 columnas reales de PruebasFM + 'N°' agregado por
# comercial_services.procesar_df_comercial) para la ficha de VIN de la caja
# derecha -> Unidades. NO son categorías inventadas: son exactamente las
# mismas 4 secciones que ya usa el formulario "Gestión de Unidades"
# (comercial_agregar.py: Empresa/Unidad/Comercial/Operativa) más un quinto
# grupo con las columnas que ese formulario no muestra pero sí conserva
# (COLUMNAS_EXTRA_DEFAULT_GUION en comercial_agregar.py). 'N°' es un índice
# de fila agregado por la UI, no un dato real de la unidad, así que no
# aparece en ningún grupo (32 campos reales + N° = 33 columnas totales).
_FICHA_VIN_GRUPOS = [
    ("Empresa", "fa5s.building", [
        (COL_RUT, "RUT"), (COL_RAZON_SOCIAL, "Razón Social"),
        (COL_CDB, "CDB comercial"), (COL_CDB_FLOTA, "CDB flota"), (COL_INDUSTRIA, "Industria"),
    ]),
    ("Información de la unidad", "fa5s.truck", [
        (COL_VIN, "VIN"), (COL_CHASIS, "Chasis"), (COL_MODELO, "Modelo"),
    ]),
    ("Información comercial", "fa5s.file-invoice", [
        (COL_EJECUTIVO, "Ejecutivo"), (COL_FORMA_CONTRATO, "Forma de contrato"),
        (COL_TIPO_SERVICIO, "Tipo de servicio"), (COL_ESTADO_COMERCIAL, "Estado comercial"),
        (COL_INICIO_CONTRATO, "Inicio contrato"), (COL_DURACION_MESES, "Duración (meses)"),
        (COL_TERMINO_CONTRATO, "Término contrato"), (COL_PERIODO_INTERNO, "Periodo interno"),
        (COL_ESTADO_ENTREGA, "Estado de entrega"),
    ]),
    ("Información operativa", "fa5s.cogs", [
        (COL_FLOTA_VC, "Flota VC"), (COL_FLOTA_VC_2, "Flota VC 2"),
        (COL_ESTADO_ACTIVACION, "Estado de activación"), (COL_ETAPA_GESTION, "Etapa gestión"),
    ]),
    ("Facturación y CM", "fa5s.file-invoice-dollar", [
        (COL_FECHA_BAJA, "Fecha de baja"), (COL_TIPO_FACTURACION, "Tipo de facturación"),
        (COL_CONTRATO_JUSTTIME, "Contrato creado en JustTime"),
        (COL_FECHA_INICIO_FACT, "Inicio facturación"), (COL_FECHA_TERMINO_FACT, "Término facturación"),
        ("OBSERVACIONES", "Observaciones"), ("N CONTRATO 3PC", "N° Contrato 3PC"),
        ("FECHA INICIO CM", "Fecha inicio CM"), ("FECHA TERMINO CM", "Fecha término CM"),
        ("TIPO DE CM", "Tipo de CM"), (COL_ESTADO_CM, "Estado del CM"), ("PAGO CM", "Pago CM"),
    ]),
]

# Mismas columnas que escribe ExcelWriter._log_changes (LogApp.csv, ver
# src/core/excel_writer.py: _HEADER_LOG_DEFAULT) -- se reutiliza tal cual
# como columnas de un historial vacío, sin definir un esquema nuevo.
COLUMNAS_HISTORIAL = ["FECHA Y HORA", "MÓDULO", "IDENTIFICADOR", "CAMPO MODIFICADO", "VALOR ANTERIOR", "NUEVO VALOR"]

# Colores llamativos para el badge de 'Estado Activación' en la tabla de
# Unidades (bg, texto), mismas familias de color que ya usa el resto de la
# app (SUCCESS/DANGER/WARNING en colors.py) para que coincidan visualmente;
# 'SIN FLOTA' usa violeta para diferenciarse de los otros 3 estados.
ESTADO_ACTIVACION_COLORES = {
    'CONECTADO': ('#D1FAE5', "#13B889"),
    'DESCONECTADO': ('#FEE2E2', "#C41919"),
    'ACTIVANDO': ('#FEF3C7', "#E1DE08"),
    'SIN FLOTA': ('#EDE9FE', "#4E4E4E"),
    # Naranja agregado a pedido explícito (20-09-2026): antes 'No aplica' no
    # tenía color propio y caía en el estilo genérico sin badge.
    'NO APLICA': ('#FFEDD5', "#C2410C"),
}

# Tarjetas por página en Cliente/Flota/Unidades (caja izquierda, 20-09-2026):
# con varios miles de unidades/clientes reales, construir TODAS las tarjetas
# de una sola vez en load_data()/filter_*() congelaba la app casi un minuto
# al entrar al módulo, y la primera vez que Qt activa el layout de una
# pestaña oculta con miles de widgets volvía a congelarla al cambiar de
# sub-pestaña (reportado por el usuario, 20-09-2026). Se pagina con
# controles "‹ Anterior | Página X de Y | Siguiente ›" (arriba y abajo de
# cada lista) en vez de mostrar todo de golpe.
#
# El tamaño de página es elegible por el usuario (combo "Mostrar", ver
# _crear_selector_tamano_pagina) -- medido con datos sintéticos (12.000
# unidades) que, después de una construcción inicial (costo fijo de motor de
# estilos de Qt que se paga una sola vez por sesión, no por página), el
# costo por tarjeta es ~0.8ms sin importar el tamaño de página, así que 200/
# 500/1000 son igual de viables que un tamaño chico -- no hace falta limitar
# las opciones a un número pequeño.
# Filtros de la pestaña Unidades: (columna de df_unidades_base, título).
_FILTROS_UNIDADES = [
    ('Estado Comercial', "Estado comercial"), ('Estado Activación', "Estado activación"),
    ('Tipo de Facturación', "Tipo de facturación"), ('Forma de Contrato', "Forma de contrato"),
    ('Tipo de Servicio', "Tipo de servicio"), ('Flota VC', "Flota VC"),
]
_OPCIONES_TAMANO_PAGINA = [200, 500, 1000]
_TARJETAS_POR_PAGINA = 200  # valor por defecto, usado solo como fallback

# ETAPA_GESTION_COLORES: movido a src/core/constants.py (16-09-2026) para
# que ComercialAgregarDialog (comercial_agregar.py) pueda reutilizarlo sin
# import circular (este módulo ya importa ComercialAgregarDialog). Se
# importa arriba junto con el resto de constantes; mismo diccionario, sin
# cambios de valores.

ESTADO_ACTIVACION_CONECTADO = "CONECTADO"  # único valor que cuenta para el KPI "Volvo Connect"

# DROPDOWN_OPTIONS_NUEVO_CLIENTE eliminado (25-09-2026, refactor de alta de
# unidades): alimentaba el ComercialAgregarDialog que abría "+ Nuevo
# Cliente", ahora quitado de General. Difería de ComercialModule
# .dropdown_options (comercial.py) solo en que a este le faltaba "Revisar"
# en FORMA DE CONTRATO (gap no intencional: la corrección de negocio del
# 24-09-2026 se aplicó en comercial.py y nunca se replicó acá) -- el
# formulario de alta ahora vive en Comercial y reutiliza directamente
# self.legacy.dropdown_options, sin necesidad de un catálogo aparte.


class PowerBiDirectorEmpresaLoaderThread(QThread):
    """Lee CDB + Correo electrónico + Teléfono + Dirección + Comuna desde BBDD CLIENTES CM.xlsx
    (Power BI, config.settings.POWERBI_EXCEL_PATH) en un hilo secundario
    para no bloquear la UI -- mismo patrón que PowerBiFlotasLoaderThread
    (contactos_agregar.py) y PowerBiSyncWorker (contactos.py), que ya
    expone esta misma fuente bajo la pestaña "Director de empresas (Power
    BI)" de ContactosModule. Solo lectura: nunca escribe en ese Excel. Si
    el archivo no está configurado, no existe o no tiene ninguna de las
    columnas esperadas, emite un mapa vacío en vez de fallar.

    Usa powerbi_cache_service (cache CSV en data/cache/, auditoria de
    rendimiento 23-09-2026) en vez de leer el .xlsx directamente: baja de
    ~11s a ~0.5s por lectura una vez generado el cache."""
    data_loaded_signal = pyqtSignal(dict)

    def __init__(self, ruta_excel):
        super().__init__()
        self.ruta_excel = ruta_excel

    def run(self):
        df_pbi = powerbi_cache_service.leer_bbdd_clientes_cm(
            self.ruta_excel, columnas=['CDB', 'Correo electrónico', 'Teléfono', 'Dirección', 'Comuna'])
        self.data_loaded_signal.emit(GeneralModule._construir_mapa_director_empresa_pbi(df_pbi))


# Precarga del mapa "Director de empresa" durante la pantalla de carga inicial
# (ver precargar_director_empresa_pbi y GeneralModule._load_pbi_director_empresa_async)
_precarga_director_pbi = {'hilo': None, 'mapa': None}


def precargar_director_empresa_pbi():
    """Lanza la lectura de BBDD CLIENTES CM al abrir la app, en paralelo con
    la carga principal, para que no compita después con la navegación."""
    if _precarga_director_pbi['hilo'] is not None:
        return
    if not POWERBI_EXCEL_PATH or not os.path.exists(POWERBI_EXCEL_PATH):
        return
    hilo = PowerBiDirectorEmpresaLoaderThread(POWERBI_EXCEL_PATH)
    hilo.data_loaded_signal.connect(lambda mapa: _precarga_director_pbi.__setitem__('mapa', mapa))
    _precarga_director_pbi['hilo'] = hilo
    hilo.start()


class GeneralDataPrepThread(QThread):
    """Pipeline pesado de GeneralModule.load_data() (procesar_df_comercial +
    los 3 _build_*_df + las listas de filtro derivadas de los datos) movido
    a un hilo secundario para no bloquear la UI (auditoria de rendimiento,
    fase 4, 21-09-2026) -- mismo patron que PowerBiDirectorEmpresaLoaderThread
    de mas arriba: recibe en el constructor un snapshot ya independiente
    (DataManager.get_comercial_df() ya hace .copy()), nunca toca self ni
    ningun widget, y al terminar emite el resultado por señal para que el
    hilo principal lo aplique (guardar los DataFrames, poblar listas de
    filtro con QListWidget, y construir las tarjetas via filter_clientes/
    filter_unidades -- todo eso requiere afinidad con el hilo
    de UI y se queda en GeneralModule._on_prep_finished).

    _build_clientes_df/_build_unidades_df son @staticmethod
    de GeneralModule (no usan self): se llaman aqui via la clase, nunca via
    una instancia de GeneralModule, para que este hilo jamas quede con una
    referencia a un QWidget."""
    data_prepared_signal = pyqtSignal(object)

    def __init__(self, snapshot_df_comercial):
        super().__init__()
        self.snapshot_df_comercial = snapshot_df_comercial

    def run(self):
        df_comercial = comercial_services.contratos_actuales(
            comercial_services.procesar_df_comercial(self.snapshot_df_comercial))
        df_clientes = GeneralModule._build_clientes_df(df_comercial)
        df_unidades = GeneralModule._build_unidades_df(df_comercial)

        self.data_prepared_signal.emit((df_comercial, df_clientes, df_unidades))


class _StackedWidgetTamañoActual(QStackedWidget):
    """QStackedWidget cuyo sizeHint/minimumSizeHint solo considera la página
    actualmente visible, no el máximo entre todas sus páginas (comportamiento
    por defecto de QStackedWidget/QStackedLayout). Usado únicamente por
    vin_detalle_stack (Ficha/Historial de la caja derecha -> Unidades): sin
    esto, la caja derecha crecía siempre según la pestaña con más contenido
    (Historial, con muchos eventos) aunque estuviera mostrando la otra
    (Ficha), a pedido explícito (15-09-2026)."""

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()


class _EtiquetaElidida(QLabel):
    """Etiqueta de una línea que pide su ancho natural (así el badge queda
    pegado al texto) y, si no cabe, corta con "…". text() devuelve el texto
    completo."""

    def __init__(self, texto="", parent=None):
        super().__init__(parent)
        self._completo = str(texto)
        super().setText(self._completo)
        self.setMinimumWidth(40)
        self.margen_extra = 0
        self.setToolTip(self._completo)

    def text(self):
        return self._completo

    def setText(self, texto):
        self._completo = str(texto)
        self.setToolTip(self._completo)
        self._elidir()

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self._completo) + 4 + self.margen_extra, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(40, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elidir()

    def _elidir(self):
        super().setText(self.fontMetrics().elidedText(
            self._completo, Qt.TextElideMode.ElideRight, max(self.width() - self.margen_extra, 1)))


# Pestañas subrayadas, mismo aspecto que las sub-pestañas de Comercial
QSS_PESTANAS_SUBRAYADAS = f"""
    QPushButton {{ background: transparent; color: {TEXT_SECONDARY}; padding: 10px 16px; border: none;
                   border-bottom: 3px solid transparent; border-radius: 0; font-weight: 600; font-size: 13px; }}
    QPushButton:hover:!checked {{ color: {TEXT_PRIMARY}; }}
    QPushButton:checked {{ color: {PRIMARY}; border-bottom: 3px solid {PRIMARY}; }}
"""
QSS_CONTENEDOR_PESTANAS = f"QFrame#barraPestanasGeneral {{ background: transparent; border: none; border-bottom: 1px solid {BORDER}; }}"
QSS_PESTANAS_CLARAS = f"""
    QPushButton {{ background: transparent; color: {TEXTO_SOBRE_AZUL}; padding: 10px 16px; border: none;
                   border-bottom: 3px solid transparent; border-radius: 0; font-weight: 600; font-size: 13px; }}
    QPushButton:hover:!checked {{ color: white; }}
    QPushButton:checked {{ color: white; border-bottom: 3px solid white; }}
"""
QSS_CONTENEDOR_PESTANAS_CLARO = "QFrame#barraPestanasGeneral { background: transparent; border: none; border-bottom: 1px solid rgba(255,255,255,0.22); }"
QSS_BOTON_FILTRO_SOBRE_AZUL = (
    "QPushButton { background-color: rgba(255,255,255,0.10); color: white; border: 1px solid rgba(255,255,255,0.28);"
    " border-radius: 9px; padding: 6px 14px; font-weight: 700; font-size: 12px; }"
    "QPushButton:hover { background-color: rgba(255,255,255,0.20); }"
)
QSS_BOTON_FILTRO_SOBRE_AZUL_ACTIVO = (
    "QPushButton { background-color: rgba(255,255,255,0.28); color: white; border: 1px solid rgba(255,255,255,0.55);"
    " border-radius: 9px; padding: 6px 14px; font-weight: 700; font-size: 12px; }"
)


class CopyableLabel(QLabel):
    """Etiqueta que se resalta al pasar el mouse y copia su texto al
    portapapeles con un clic (usada en el subtítulo del detalle de cliente:
    Industria | RUT | CDB)."""

    _BASE_STYLE = f"color: {TEXT_SECONDARY}; font-size: 10px; padding: 1px 7px; border-radius: 9px; border: 1px solid transparent;"
    _HOVER_STYLE = _BASE_STYLE + f"background-color: {TINTE_CLARO}; color: {AZUL}; border: 1px solid {LINEA_AZUL};"
    _COPIADO_STYLE = _BASE_STYLE + "background-color: #D1FAE5; color: #065F46; border: 1px solid #6EE7B7; font-weight: bold;"
    _DURACION_COPIADO_MS = 1200

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(self._BASE_STYLE)
        self.setToolTip("Clic para copiar")
        self._copiado = False
        self._texto_original = None

    def set_value(self, label, value):
        self._copy_value = str(value) if value not in (None, "") else "N/A"
        self._restaurar_texto()
        self.setText(f"{label}: {self._copy_value}")

    def _restaurar_texto(self):
        if self._copiado:
            self._copiado = False
            if self._texto_original is not None:
                self.setText(self._texto_original)
            self._texto_original = None

    def _fin_copiado(self):
        # El widget pudo reconstruirse mientras corría el temporizador
        try:
            self._restaurar_texto()
            self.setStyleSheet(self._HOVER_STYLE if self.underMouse() else self._BASE_STYLE)
        except RuntimeError:
            pass

    def enterEvent(self, event):
        if not self._copiado:
            self.setStyleSheet(self._HOVER_STYLE)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._copiado:
            self.setStyleSheet(self._BASE_STYLE)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and getattr(self, '_copy_value', None):
            QApplication.clipboard().setText(self._copy_value)
            if not self._copiado:
                self._texto_original = self.text()
                self._copiado = True
            self.setText("✓ Copiado")
            self.setStyleSheet(self._COPIADO_STYLE)
            QTimer.singleShot(self._DURACION_COPIADO_MS, self._fin_copiado)
        super().mousePressEvent(event)


class CopyableChip(CopyableLabel):
    """CopyableLabel con aspecto de chip (borde y fondo visibles en reposo)."""

    _BASE_STYLE = f"color: {TEXT_SECONDARY}; font-size: 10px; padding: 1px 7px; border-radius: 9px; background-color: #F7F9FC; border: 1px solid {BORDER};"
    _HOVER_STYLE = _BASE_STYLE + f"background-color: {TINTE_CLARO}; color: {AZUL}; border: 1px solid {LINEA_AZUL};"
    _COPIADO_STYLE = _BASE_STYLE + "background-color: #D1FAE5; color: #065F46; border: 1px solid #6EE7B7; font-weight: bold;"


class CopyableTitulo(CopyableLabel):
    """VIN grande del detalle: se resalta y se copia con un clic."""

    _BASE_STYLE = "color: white; font-size: 18px; font-weight: bold; padding: 1px 8px; border-radius: 10px; border: 1px solid transparent;"
    _HOVER_STYLE = _BASE_STYLE + f"background-color: white; color: {AZUL}; border: 1px solid white;"
    _COPIADO_STYLE = _BASE_STYLE + "background-color: #D1FAE5; color: #065F46; border: 1px solid #6EE7B7;"

    def set_value(self, label, value):
        self._restaurar_texto()
        self._copy_value = str(value) if value not in (None, "") else "N/A"
        self.setText(f"{label} {self._copy_value}")

    def set_texto(self, valor):
        self._restaurar_texto()
        self._copy_value = str(valor) if valor not in (None, "") else "N/A"
        self.setText(self._copy_value)


class CopyableValueLabel(QLabel):
    """Valor de una fila de "Información del cliente" con clic-para-copiar (Dirección/Comuna,
    ver _render_info_cliente): mismo gesto que CopyableLabel, pero
    conservando el estilo bold/alineado a la derecha propio de las filas
    de la caja "Información del cliente" en vez del estilo fijo de
    CopyableLabel (pensado para el subtítulo Industria | RUT | CDB)."""

    def __init__(self, text, copy_value, base_style, parent=None):
        super().__init__(text, parent)
        self._copy_value = copy_value
        self._base_style = base_style
        self._hover_style = base_style + f" background-color: {TINTE_CLARO}; color: {AZUL};"
        self.setStyleSheet(self._base_style)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clic para copiar")

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._base_style)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._copy_value:
            QApplication.clipboard().setText(self._copy_value)
        super().mousePressEvent(event)


class _EtiquetaElididaCopiable(_EtiquetaElidida):
    """Valor de una sola línea (cortado con "…") que al hacer clic copia
    `copy_value`, que puede ser más que lo que se ve."""

    def __init__(self, text, copy_value, base_style, parent=None):
        super().__init__(text, parent)
        self._copy_value = copy_value
        self._base_style = base_style
        self._hover_style = base_style + f" background-color: {TINTE_CLARO}; color: {AZUL};"
        self.setStyleSheet(self._base_style)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def enterEvent(self, event):
        self.setStyleSheet(self._hover_style)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._base_style)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._copy_value:
            QApplication.clipboard().setText(self._copy_value)
        super().mousePressEvent(event)


_ACCENT_GENERAL = AZUL
QSS_TARJETAS_CLIENTE = f"""
    * {{ background: transparent; }}
    QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
    QFrame#general_cliente_card {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
    QFrame#general_cliente_card:hover {{ border: 1px solid {_ACCENT_GENERAL}; background-color: #F3F5F9; }}
    QFrame#general_cliente_card[seleccionado="true"] {{ background-color: #F3F5F9; border: 2px solid {_ACCENT_GENERAL}; }}
    QFrame#general_cliente_card[duplicado="true"] {{ background-color: #FEE2E2; border: 1px solid #FCA5A5; }}
    QFrame#general_cliente_card[duplicado="true"]:hover {{ border: 1px solid {DANGER}; background-color: #FEE2E2; }}
    QFrame#general_cliente_card[duplicado="true"][seleccionado="true"] {{ background-color: #FEE2E2; border: 2px solid {DANGER}; }}
    QFrame#general_cliente_card QLabel {{ border: none; }}
    QLabel#gc_nombre {{ font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY}; }}
    QLabel#gc_sub {{ font-size: 10px; color: {TEXT_SECONDARY}; }}
    QLabel#gc_badge {{ background-color: {VOLVO_BLUE}; color: white; font-size: 10px; font-weight: bold; padding: 5px 10px; border-radius: 10px; }}
"""


_ANCHOS_CONTADORES = None


def _anchos_contadores_cliente():
    """Ancho fijo de los contadores de la tarjeta de cliente (unidades y
    flotas), para que queden alineados en columna entre tarjetas. Caben hasta
    '9999 unidades' y '999 flotas'."""
    global _ANCHOS_CONTADORES
    if _ANCHOS_CONTADORES is None:
        from PyQt6.QtGui import QFontMetrics
        fuente = QFont()
        fuente.setPixelSize(10)
        fuente.setBold(True)
        metrica = QFontMetrics(fuente)
        _ANCHOS_CONTADORES = (metrica.horizontalAdvance("9999 unidades") + 28,
                              metrica.horizontalAdvance("999 flotas") + 28)
    return _ANCHOS_CONTADORES


class GeneralClienteCard(QFrame):
    """Tarjeta clickeable de un cliente (caja izquierda -> Cliente), mismo
    lenguaje visual que EmpresaCard/ClienteCard de Contratos/Provisiones.
    row_idx es la posición (0-based) de esta fila en
    GeneralModule._df_clientes_visible en el momento del render. Sin
    QGraphicsDropShadowEffect a propósito (lección de rendimiento de
    provisiones.py: puede haber varios cientos de clientes)."""

    clicked = pyqtSignal(int)

    def __init__(self, row_idx, razon_social, rut, cdb, industria, total_unidades, parent=None, duplicado=False,
                 total_flotas=0, aviso_flota=""):
        super().__init__(parent)
        self.row_idx = row_idx
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("general_cliente_card")
        accent = AZUL
        # Estilos en QSS_TARJETAS_CLIENTE, aplicado una sola vez en el
        # contenedor: 5 setStyleSheet por tarjeta costaban segundos con 200.
        # Duplicado (RUT+CDB repetido, ver _calcular_claves_duplicadas_rut_cdb)
        # se marca en rojo, igual que GeneralFlotaCard con Flota VC vacío.
        self.setProperty("duplicado", bool(duplicado))
        self.setProperty("seleccionado", False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap(
            'fa5s.exclamation-triangle' if duplicado else 'fa5s.building',
            color=(DANGER if duplicado else accent), size=16,
        ))
        icon_lbl.setFixedWidth(22)
        layout.addWidget(icon_lbl)
        if duplicado:
            self.setToolTip("Este RUT tiene más de una razón social (ver pestaña 'Razones sociales' al seleccionarlo).")

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        nombre = str(razon_social).strip() or "Sin razón social"
        lbl_nombre = _EtiquetaElidida(nombre)
        lbl_nombre.setObjectName("gc_nombre")
        text_layout.addWidget(lbl_nombre)

        sub_partes = []
        rut_str = str(rut).strip()
        if rut_str and rut_str.lower() != 'nan':
            sub_partes.append(f"RUT {rut_str}")
        cdb_str = str(cdb).strip()
        if cdb_str and cdb_str.lower() not in ('nan', '-', ''):
            sub_partes.append(f"CDB {cdb_str}")
        ind_str = str(industria).strip()
        if ind_str and ind_str.lower() != 'nan':
            sub_partes.append(ind_str)
        self.lbl_sub = _EtiquetaElidida("  •  ".join(sub_partes) if sub_partes else "Sin datos adicionales")
        self.lbl_sub.setObjectName("gc_sub")
        text_layout.addWidget(self.lbl_sub)
        layout.addLayout(text_layout, 1)

        if aviso_flota:
            icono_aviso = QLabel()
            icono_aviso.setPixmap(ThemeManager.icon_pixmap('fa5s.exclamation-circle', color=WARNING, size=16))
            icono_aviso.setToolTip(aviso_flota)
            layout.addWidget(icono_aviso, 0, Qt.AlignmentFlag.AlignVCenter)

        ancho_unidades, ancho_flotas = _anchos_contadores_cliente()
        plural = "unidad" if total_unidades == 1 else "unidades"
        badge = QLabel(f"{total_unidades} {plural}")
        badge.setObjectName("gc_badge")
        badge.setFixedWidth(ancho_unidades)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        if total_flotas:
            badge_flotas = QLabel(f"{total_flotas} {'flota' if total_flotas == 1 else 'flotas'}")
            badge_flotas.setStyleSheet(f"background-color: {VOLVO_BLUE}; color: white; font-size: 10px; "
                                       "font-weight: bold; padding: 5px 10px; border-radius: 10px;")
        else:
            badge_flotas = QLabel("Sin flota")
            badge_flotas.setStyleSheet("background-color: #F1F4F9; color: #66748D; font-size: 10px; "
                                       "font-weight: bold; padding: 5px 10px; border-radius: 10px;")
        badge_flotas.setFixedWidth(ancho_flotas)
        badge_flotas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(badge_flotas, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected):
        self.setProperty("seleccionado", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row_idx)
        super().mousePressEvent(event)


class GeneralDuplicadoCard(QFrame):
    """Fila de una razón social de un cliente con varias (caja derecha ->
    pestaña Razones sociales): nombre, cantidad de unidades y, para la más
    usada, la etiqueta "Principal". Al hacer clic se despliegan sus unidades
    (`unidades`: lista de (VIN, chasis, estado de activación, estado comercial))."""

    _MAX_UNIDADES_VISIBLES = 200

    def __init__(self, razon_social, total_unidades, principal=False, parent=None, unidades=None, al_abrir_unidad=None):
        super().__init__(parent)
        self._razon_social = str(razon_social).strip()
        self._unidades = unidades or []
        self._al_abrir_unidad = al_abrir_unidad
        self._detalle = None
        self.setObjectName("general_duplicado_card")
        self.setStyleSheet(f"""
            QFrame#general_duplicado_card {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
            QFrame#general_duplicado_card QLabel {{ border: none; background: transparent; }}
            QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
        """)
        if self._unidades:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Clic para ver las unidades de esta razón social")

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(14, 10, 14, 10)
        raiz.setSpacing(8)
        layout = QHBoxLayout()
        layout.setSpacing(10)
        raiz.addLayout(layout)
        self._flecha = QLabel("▸")
        self._flecha.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
        layout.addWidget(self._flecha, 0, Qt.AlignmentFlag.AlignVCenter)
        self._flecha.setVisible(bool(self._unidades))

        lbl_nombre = QLabel(self._razon_social or "Sin razón social")
        lbl_nombre.setWordWrap(True)
        lbl_nombre.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(lbl_nombre, 1)

        if principal:
            etiqueta = QLabel("Principal")
            etiqueta.setStyleSheet(f"background-color: {VOLVO_BLUE}; color: white; font-size: 10px; "
                                   "font-weight: bold; padding: 4px 10px; border-radius: 10px;")
            layout.addWidget(etiqueta, 0, Qt.AlignmentFlag.AlignVCenter)

        plural = "unidad" if total_unidades == 1 else "unidades"
        badge = QLabel(f"{total_unidades} {plural}")
        badge.setStyleSheet(f"background-color: {AZUL}; color: white; font-size: 10px; "
                            "font-weight: bold; padding: 4px 10px; border-radius: 10px;")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def _crear_detalle(self):
        detalle = QWidget()
        lay = QVBoxLayout(detalle)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        linea = QFrame()
        linea.setFixedHeight(1)
        linea.setStyleSheet(f"background-color: {BORDER}; border: none;")
        lay.addWidget(linea)
        for vin, chasis, activacion, comercial in self._unidades[:self._MAX_UNIDADES_VISIBLES]:
            fila = QWidget()
            fila_lay = QHBoxLayout(fila)
            fila_lay.setContentsMargins(0, 5, 0, 5)
            fila_lay.setSpacing(10)
            if self._al_abrir_unidad is not None:
                lbl_vin = _EnlaceLabel(vin)
                lbl_vin._base = f"color: {PRIMARY}; font-size: 11px; font-weight: bold; border: none; background: transparent;"
                lbl_vin.setStyleSheet(lbl_vin._base)
                lbl_vin.setToolTip("Clic para ver la unidad en Unidades")
                lbl_vin.clicked.connect(lambda v=vin: self._al_abrir_unidad(v))
            else:
                lbl_vin = QLabel(vin)
                lbl_vin.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {TEXT_PRIMARY};")
            lbl_chasis = QLabel(f"Chasis {chasis}")
            lbl_chasis.setStyleSheet(f"font-size: 10px; color: {TEXT_SECONDARY};")
            estados = " · ".join(e for e in (comercial, activacion) if e and e != '-')
            lbl_estado = QLabel(estados)
            lbl_estado.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
            lbl_estado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            fila_lay.addWidget(lbl_vin)
            fila_lay.addWidget(lbl_chasis)
            fila_lay.addStretch(1)
            fila_lay.addWidget(lbl_estado)
            lay.addWidget(fila)
        restantes = len(self._unidades) - self._MAX_UNIDADES_VISIBLES
        if restantes > 0:
            mas = QLabel(f"y {restantes} unidades más (ver la pestaña Unidades)")
            mas.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
            lay.addWidget(mas)
        return detalle

    def mousePressEvent(self, event):
        sobre_enlace = isinstance(self.childAt(event.position().toPoint()), _EnlaceLabel)
        if event.button() == Qt.MouseButton.LeftButton and self._unidades and not sobre_enlace:
            if self._detalle is None:
                self._detalle = self._crear_detalle()
                self.layout().addWidget(self._detalle)
                self._detalle.hide()
            abrir = self._detalle.isHidden()
            self._detalle.setVisible(abrir)
            self._flecha.setText("▾" if abrir else "▸")
        super().mousePressEvent(event)


QSS_TARJETAS_UNIDAD = f"""
    * {{ background: transparent; }}
    QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
    QFrame#general_unidad_card {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
    QFrame#general_unidad_card:hover {{ border: 1px solid {_ACCENT_GENERAL}; }}
    QFrame#general_unidad_card[seleccionado="true"] {{ background-color: #F3F5F9; border: 2px solid {_ACCENT_GENERAL}; }}
    QLabel#gu_nombre {{ font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY}; border: none; }}
    QLabel#gu_industria {{ font-size: 10px; color: {TEXT_SECONDARY}; border: none; }}
"""


# Valores de FLOTA VC que indican que la unidad no tiene flota en Volvo Connect
_FLOTA_VC_SIN_FLOTA = ('sin flota', 'no existe en vc')


def _flota_valida(valor):
    return str(valor).strip().lower() not in ('', '-', 'nan', 'none', 'n/a', '<na>') + _FLOTA_VC_SIN_FLOTA


_FICHA_VIN_SECCIONES = ("Empresa", "Unidad", "Operativa", "Facturación y CM")


class _EnlaceLabel(QLabel):
    """Texto en azul que al pasar el mouse se subraya y emite clicked."""
    clicked = pyqtSignal()

    def __init__(self, texto="", parent=None):
        super().__init__(texto, parent)
        self._base = f"color: {PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;"
        self.setStyleSheet(self._base)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clic para abrir")

    def enterEvent(self, event):
        self.setStyleSheet(self._base + " text-decoration: underline;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self._base)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _clave_flota_texto(nombre):
    """Clave para comparar textos (flotas, valores de filtro): sin distinguir
    mayúsculas, tildes ni espacios repetidos."""
    texto = unicodedata.normalize('NFKD', " ".join(str(nombre).split()))
    return "".join(c for c in texto if not unicodedata.combining(c)).upper()


def _texto_duracion(dias):
    dias = abs(int(dias))
    if dias >= 60:
        return f"{dias // 30} meses"
    return f"{dias} día" if dias == 1 else f"{dias} días"


def _calcular_vigencia(inicio, termino, hoy=None, baja=None, finalizado=False):
    """Estado de un contrato para la tarjeta de la ficha. Devuelve inicio y
    termino (DD-MM-YYYY o '-'), estado ('vencido', 'vigente', 'baja',
    'baja_prog' o 'sin'), progreso (0-100 o None), la leyenda a mostrar y
    `baja` (fecha, solo si cae antes del término; None si no). Con
    `finalizado` un contrato pasado de término se informa como 'finalizado'
    en vez de 'vencido'."""
    hoy = (hoy or pd.Timestamp.now()).normalize()
    f_ini = DataFrameFormatter.parsear_fecha_segura(inicio) if _flota_valida(inicio) else pd.NaT
    f_ter = DataFrameFormatter.parsear_fecha_segura(termino) if _flota_valida(termino) else pd.NaT
    f_baja = DataFrameFormatter.parsear_fecha_segura(baja) if _flota_valida(baja) else pd.NaT
    res = {
        'inicio': f_ini.strftime('%d-%m-%Y') if pd.notna(f_ini) else '-',
        'termino': f_ter.strftime('%d-%m-%Y') if pd.notna(f_ter) else '-',
        'estado': 'sin', 'progreso': None, 'texto': '', 'baja': None,
    }
    if pd.isna(f_ter):
        return res
    f_ter = f_ter.normalize()
    ini_valido = pd.notna(f_ini) and f_ter > f_ini.normalize()

    def porcentaje(fecha):
        total = (f_ter - f_ini.normalize()).days
        return max(0, min(100, int(round((fecha.normalize() - f_ini.normalize()).days / total * 100))))

    if pd.notna(f_baja) and f_baja.normalize() < f_ter:
        f_baja = f_baja.normalize()
        res['baja'] = f_baja.strftime('%d-%m-%Y')
        if finalizado and hoy > f_ter:
            res.update(estado='finalizado', texto=f"Contrato finalizado hace {_texto_duracion((hoy - f_ter).days)}",
                       progreso=porcentaje(f_baja) if ini_valido else 100)
        elif hoy >= f_baja:
            res.update(estado='baja', texto=f"De baja hace {_texto_duracion((hoy - f_baja).days)}",
                       progreso=porcentaje(f_baja) if ini_valido else 100)
        else:
            res.update(estado='baja_prog', texto=f"Baja en {_texto_duracion((f_baja - hoy).days)}",
                       progreso=porcentaje(hoy) if ini_valido else None)
        return res
    if hoy > f_ter:
        if finalizado:
            res.update(estado='finalizado', progreso=100,
                       texto=f"Contrato finalizado hace {_texto_duracion((hoy - f_ter).days)}")
        else:
            res.update(estado='vencido', progreso=100, texto=f"Vencido hace {_texto_duracion((hoy - f_ter).days)}")
    else:
        res.update(estado='vigente', texto=f"Vigente · vence en {_texto_duracion((f_ter - hoy).days)}")
        if ini_valido:
            res['progreso'] = porcentaje(hoy)
    return res


def _formatear_fecha_contrato(valor, con_vencimiento=False):
    """Fecha DD-MM-YYYY (o '' si no hay). Con `con_vencimiento` devuelve
    (texto, vencido); sin él, (texto,) en una tupla de un elemento."""
    texto, vencido = "", False
    if _flota_valida(valor):
        fecha = DataFrameFormatter.parsear_fecha_segura(valor)
        if pd.notna(fecha):
            texto = fecha.strftime('%d-%m-%Y')
            vencido = fecha.normalize() < pd.Timestamp.now().normalize()
        else:
            texto = str(valor).strip()
    return (texto, vencido) if con_vencimiento else (texto,)


class _PopupFiltroValores(QFrame):
    """Tarjeta flotante de FiltroValoresBoton: buscador, marcar/desmarcar y
    una casilla por valor distinto."""

    def __init__(self, titulo, valores, seleccion, al_cambiar):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._al_cambiar = al_cambiar
        self._cargando = True
        externo = QVBoxLayout(self)
        externo.setContentsMargins(14, 8, 14, 20)
        tarjeta = QFrame()
        tarjeta.setObjectName("popupFiltro")
        tarjeta.setStyleSheet("QFrame#popupFiltro { background: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 14px; }")
        sombra = QGraphicsDropShadowEffect(tarjeta)
        sombra.setBlurRadius(28)
        sombra.setOffset(0, 8)
        sombra.setColor(QColor(27, 43, 78, 70))
        tarjeta.setGraphicsEffect(sombra)
        externo.addWidget(tarjeta)
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(10, 12, 10, 10)
        lay.setSpacing(6)

        encabezado = QLabel(titulo.upper())
        encabezado.setStyleSheet("color: #66748D; font-size: 10px; font-weight: 800; letter-spacing: 1px; "
                                 "background: transparent; border: none; padding-left: 2px;")
        lay.addWidget(encabezado)

        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Buscar...")
        self.buscador.setClearButtonEnabled(True)
        self.buscador.setStyleSheet("QLineEdit { border: 1px solid #E3E8F0; border-radius: 10px; padding: 6px 10px; "
                                    "background: #F7F9FC; font-size: 12px; color: #0F1B33; }")
        self.buscador.textChanged.connect(self._buscar)
        lay.addWidget(self.buscador)

        acciones = QHBoxLayout()
        acciones.setSpacing(6)
        for texto, valor in (("Marcar todos", True), ("Desmarcar todos", False)):
            b = QPushButton(texto)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("QPushButton { border: 1px solid #E3E8F0; border-radius: 9px; background: #F7F9FC; "
                            "padding: 5px 8px; font-size: 11px; font-weight: 700; color: #0F1B33; }"
                            "QPushButton:hover { border-color: #1F6FEB; }")
            b.clicked.connect(lambda _=False, v=valor: self._marcar_visibles(v))
            acciones.addWidget(b)
        lay.addLayout(acciones)

        self.lista = QListWidget()
        self.lista.setFrameShape(QFrame.Shape.NoFrame)
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { color: #1B2B4E; padding: 4px 6px; border-radius: 8px; font-size: 12px; font-weight: 600; }"
            "QListWidget::item:hover { background: #F1F4F9; }"
            "QListWidget::indicator { width: 15px; height: 15px; border: 1px solid #B8C4D6; border-radius: 4px; background: #FFFFFF; }"
            "QListWidget::indicator:checked { background: #1F6FEB; border: 1px solid #1F6FEB; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }"
            "QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 3px; min-height: 28px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }")
        for clave, etiqueta, n in valores:
            item = QListWidgetItem(f"{etiqueta}   ({n})")
            item.setData(Qt.ItemDataRole.UserRole, clave)
            item.setData(Qt.ItemDataRole.UserRole + 1, etiqueta.lower())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if clave in seleccion else Qt.CheckState.Unchecked)
            self.lista.addItem(item)
        self.lista.setFixedHeight(min(max(len(valores), 1) * 28 + 6, 260))
        self.lista.itemChanged.connect(self._item_cambiado)
        lay.addWidget(self.lista)

        pie = QLabel(f"{len(valores)} valores distintos")
        pie.setStyleSheet("color: #8A97AB; font-size: 10px; background: transparent; border: none; padding-left: 2px;")
        lay.addWidget(pie)
        self._cargando = False

    def _buscar(self, texto):
        t = texto.strip().lower()
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            item.setHidden(bool(t) and t not in item.data(Qt.ItemDataRole.UserRole + 1))

    def _marcar_visibles(self, marcar):
        estado = Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked
        self._cargando = True
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            if not item.isHidden():
                item.setCheckState(estado)
        self._cargando = False
        self._emitir()

    def _item_cambiado(self, _item):
        if not self._cargando:
            self._emitir()

    def _emitir(self):
        marcados = {self.lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lista.count())
                    if self.lista.item(i).checkState() == Qt.CheckState.Checked}
        self._al_cambiar(marcados)


class FiltroValoresBoton(QPushButton):
    """Botón de filtro por columna: muestra "Título: Todos / valor / n de N" y
    abre una tarjeta con los valores distintos de la columna (sin vacíos ni
    '-', sin repetir aunque difieran en mayúsculas). `seleccion()` es None
    cuando no filtra."""
    cambiado = pyqtSignal()

    _ESTILO = ("QPushButton {{ background-color: {bg}; color: {fg}; border: 1px solid {borde}; border-radius: 12px; "
               "padding: 5px 12px; font-size: 11px; font-weight: 600; text-align: left; }}"
               "QPushButton:hover {{ border-color: #1F6FEB; }}")

    def __init__(self, titulo, parent=None):
        super().__init__(parent)
        self._titulo = titulo
        self._valores = []
        self._marcados = set()
        self._popup = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self._actualizar()

    @staticmethod
    def valores_distintos(serie):
        """[(clave, etiqueta, cantidad)] ordenado, sin vacíos ni '-'."""
        cuenta, etiquetas = {}, {}
        texto = serie.astype(str).str.strip()
        repeticiones = texto.value_counts()
        for v in texto.drop_duplicates():
            if v == '' or v == '-' or v.lower() in ('nan', 'none', '<na>'):
                continue
            k = _clave_flota_texto(v)
            cuenta[k] = cuenta.get(k, 0) + int(repeticiones[v])
            etiquetas.setdefault(k, v)
        return [(k, etiquetas[k], cuenta[k]) for k in sorted(cuenta, key=lambda x: x.lower())]

    def set_valores(self, valores):
        claves = {k for k, _, _ in valores}
        todos_antes = not self._valores or self._marcados >= {k for k, _, _ in self._valores}
        self._valores = valores
        self._marcados = set(claves) if todos_antes else (self._marcados & claves)
        self._actualizar()

    def seleccion(self):
        """None si están todos marcados; si no, el conjunto de claves."""
        if not self._valores or len(self._marcados) == len(self._valores):
            return None
        return set(self._marcados)

    def limpiar(self):
        self._marcados = {k for k, _, _ in self._valores}
        self._actualizar()

    def _resumen(self):
        sel = self.seleccion()
        if sel is None:
            return "Todos"
        if len(sel) == 1:
            k = next(iter(sel))
            return next((e for c, e, _ in self._valores if c == k), k)
        return f"{len(sel)} de {len(self._valores)}"

    def _actualizar(self):
        activo = self.seleccion() is not None
        self.setText(f"{self._titulo}: {self._resumen()}  ▾")
        self.setStyleSheet(self._ESTILO.format(
            bg="#E8F0FE" if activo else "#F7F9FC", fg="#1F6FEB" if activo else "#0F1B33",
            borde="#1F6FEB" if activo else "#E3E8F0"))

    def _al_cambiar(self, marcados):
        self._marcados = set(marcados)
        self._actualizar()
        self.cambiado.emit()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self.rect().contains(e.position().toPoint()) and self._valores:
            self._abrir()

    def _abrir(self):
        popup = _PopupFiltroValores(self._titulo, self._valores, self._marcados, self._al_cambiar)
        popup.setFixedWidth(max(self.width(), 260) + 28)
        popup.adjustSize()
        origen = self.mapToGlobal(self.rect().bottomLeft())
        popup.move(origen.x() - 14, origen.y() - 6)
        self._popup = popup
        popup.show()
        popup.buscador.setFocus()


_PAL_VERDE = ('#D1FAE5', '#065F46')
_PAL_AMARILLO = ('#FEF3C7', '#92400E')
_PAL_ROJO = ('#FEE2E2', '#C41919')
_PAL_GRIS = ('#F1F4F9', '#66748D')
_PAL_NARANJA = ('#FFEDD5', '#C2410C')


def _color_estado_comercial(valor):
    v = str(valor).strip().upper()
    if v == 'VIGENTE':
        return _PAL_VERDE
    if v in ('ACTIVACIÓN PENDIENTE', 'ACTIVACION PENDIENTE'):
        return _PAL_AMARILLO
    if v in ('BAJA', 'VENCIDO', 'BAJA SOLICITADA'):
        return _PAL_ROJO
    return _PAL_GRIS


def _color_estado_activacion(valor):
    v = str(valor).strip().upper()
    if v == 'CONECTADO':
        return _PAL_VERDE
    if v == 'ACTIVANDO':
        return _PAL_AMARILLO
    if v == 'DESCONECTADO':
        return _PAL_ROJO
    return _PAL_GRIS


def _color_forma_facturacion(forma, tipo_facturacion):
    """Verde si la combinación cumple la matriz de negocio, rojo si no;
    gris cuando no hay nada que validar (sin asignar o forma desconocida)."""
    validos = FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(str(forma).strip().upper())
    tf = str(tipo_facturacion).strip().upper()
    if validos is None or tf in ('', '-', 'NAN'):
        return _PAL_GRIS
    return _PAL_VERDE if tf in validos else _PAL_ROJO


def _es_sin_vc(estado_comercial, estado_activacion, forma_contrato, tipo_facturacion):
    """Unidad sin Volvo Connect: estado comercial vacío, '-' o SIN SERVICIO,
    activación NO APLICA, forma de contrato SIN CONTRATO y facturación SIN
    REGISTRO."""
    norm = lambda x: str(x).strip().upper()
    return (norm(estado_comercial) in ('', '-', 'SIN SERVICIO', 'NAN', 'NONE', '<NA>')
            and norm(estado_activacion) == 'NO APLICA'
            and norm(forma_contrato) == 'SIN CONTRATO'
            and norm(tipo_facturacion) == 'SIN REGISTRO')


def _crear_pildora(texto, colores, etiqueta=None, tooltip=None, chip=False):
    """Píldora de color (fondo, texto) con etiqueta opcional en tono apagado.
    Con `chip` queda como chip neutro (borde y fondo claros) y solo el valor
    lleva el color del estado."""
    fondo, tinta = colores
    html = str(texto).replace('&', '&amp;').replace('<', '&lt;')
    if chip:
        html = f"<span style='color:{tinta};'>{html}</span>"
    if etiqueta:
        color_et = f" color:{TEXT_SECONDARY};" if chip else ""
        html = f"<span style='font-weight:normal;{color_et}'>{etiqueta}</span> {html}"
    lbl = QLabel(html)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    if tooltip:
        lbl.setToolTip(f"{tooltip}: {texto}")
    if chip:
        lbl.setStyleSheet(f"background-color: #F7F9FC; color: {tinta}; border: 1px solid {BORDER}; "
                          "font-size: 10px; font-weight: bold; padding: 1px 7px; border-radius: 9px;")
        return lbl
    lbl.setStyleSheet(f"background-color: {fondo}; color: {tinta}; border: 1px solid {fondo}; "
                      "font-size: 9px; font-weight: bold; padding: 1px 7px; border-radius: 9px;")
    return lbl


class GeneralUnidadFila(QFrame):
    """Fila de una unidad en la caja derecha -> detalle de cliente ->
    Unidades. Un clic la resalta; doble clic pide abrirla en la pestaña
    Unidades de la caja izquierda."""

    seleccionada = pyqtSignal(str)
    abrir = pyqtSignal(str)

    def __init__(self, vin, chasis, flota_vc, estado_activacion, parent=None, cdb_flota="", cdb_principal=""):
        super().__init__(parent)
        self._vin = str(vin).strip()
        self.setObjectName("unidad_fila")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Doble clic para abrir la unidad en Unidades")
        self.setProperty("seleccionado", False)
        accent = AZUL
        self.setStyleSheet(f"""
            QFrame#unidad_fila {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
            QFrame#unidad_fila:hover {{ border: 1px solid {accent}; }}
            QFrame#unidad_fila[seleccionado="true"] {{ background-color: #F3F5F9; border: 2px solid {accent}; }}
            QFrame#unidad_fila QLabel {{ border: none; background: transparent; }}
            QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        ids = QVBoxLayout()
        ids.setSpacing(1)
        lbl_vin = QLabel(self._vin or "-")
        lbl_vin.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        chasis_txt = str(chasis).strip()
        lbl_chasis = QLabel(f"Chasis {chasis_txt}" if chasis_txt and chasis_txt.lower() != 'nan' else "Sin chasis")
        lbl_chasis.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        ids.addWidget(lbl_vin)
        ids.addWidget(lbl_chasis)
        layout.addLayout(ids)

        flota_txt = str(flota_vc).strip() if _flota_valida(flota_vc) else "Sin flota"
        lbl_flota = _EtiquetaElidida(flota_txt)
        lbl_flota.setStyleSheet(f"color: {TEXT_SECONDARY if _flota_valida(flota_vc) else TEXT_MUTED}; font-size: 11px;")
        columna_flota = QVBoxLayout()
        columna_flota.setSpacing(1)
        columna_flota.addWidget(lbl_flota)
        cdb_txt = str(cdb_flota).strip()
        if cdb_txt.lower() in ('nan', 'none', '-'):
            cdb_txt = ""
        if cdb_principal:
            # El CDB flota con más unidades del cliente va en negro; los demás, en naranja
            es_principal = cdb_txt == cdb_principal
            lbl_cdb = QLabel(f"CDB flota {cdb_txt}" if cdb_txt else "Sin CDB flota")
            lbl_cdb.setStyleSheet(
                f"color: {TEXT_PRIMARY if es_principal else COLOR_CDB_FLOTA_MINORITARIO}; font-size: 10px; font-weight: bold;")
            if not es_principal:
                lbl_cdb.setToolTip(f"Distinto al CDB flota más frecuente de este cliente ({cdb_principal})")
            columna_flota.addWidget(lbl_cdb)
        layout.addLayout(columna_flota, 1)

        estado = str(estado_activacion).strip()
        colores = ESTADO_ACTIVACION_COLORES.get(estado.upper())
        badge = QLabel(estado or "-")
        if colores:
            badge.setStyleSheet(f"background-color: {colores[0]}; color: {colores[1]}; font-size: 9px; font-weight: bold; padding: 3px 8px; border-radius: 8px;")
        else:
            badge.setStyleSheet(f"background-color: {BACKGROUND}; color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; font-size: 9px; font-weight: bold; padding: 3px 8px; border-radius: 8px;")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected):
        _repulir_seleccion(self, selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.seleccionada.emit(self._vin)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._vin:
            self.abrir.emit(self._vin)
        super().mouseDoubleClickEvent(event)


def _repulir_seleccion(card, selected):
    card.setProperty("seleccionado", bool(selected))
    card.style().unpolish(card)
    card.style().polish(card)
    card.update()


class GeneralFlotaFila(QFrame):
    """Fila de una flota VC en la caja derecha -> detalle de cliente -> Flotas
    VC: nombre y cantidad de unidades. Mismo estilo que GeneralUnidadFila."""

    seleccionada = pyqtSignal(str)

    def __init__(self, flota, total_unidades, cdb_flota="", parent=None):
        super().__init__(parent)
        self._flota = str(flota).strip()
        self.setObjectName("flota_fila")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("seleccionado", False)
        accent = AZUL
        self.setStyleSheet(f"""
            QFrame#flota_fila {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
            QFrame#flota_fila:hover {{ border: 1px solid {accent}; }}
            QFrame#flota_fila[seleccionado="true"] {{ background-color: #F3F5F9; border: 2px solid {accent}; }}
            QFrame#flota_fila QLabel {{ border: none; background: transparent; }}
            QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        lbl_nombre = _EtiquetaElidida(self._flota)
        lbl_nombre.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(lbl_nombre)
        lbl_cdb = QLabel(f"CDB flota: {cdb_flota}" if cdb_flota else "CDB flota: -")
        lbl_cdb.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
        lbl_cdb.setToolTip("CDB flota de las unidades de esta flota VC")
        textos.addWidget(lbl_cdb)
        layout.addLayout(textos, 1)

        plural = "unidad" if total_unidades == 1 else "unidades"
        badge = QLabel(f"{total_unidades} {plural}")
        badge.setStyleSheet(f"background-color: {AZUL}; color: white; font-size: 10px; font-weight: bold; "
                            "padding: 4px 10px; border-radius: 10px;")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected):
        _repulir_seleccion(self, selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.seleccionada.emit(self._flota)
        super().mousePressEvent(event)


class _ContratoAnteriorCard(QFrame):
    """Tarjeta clickeable de un contrato anterior de la unidad seleccionada
    (caja derecha -> Unidades -> Contratos anteriores). `indice` es la posición
    en GeneralModule._contratos_anteriores_df."""

    clicked = pyqtSignal(int)

    def __init__(self, indice, fila, parent=None):
        super().__init__(parent)
        self.indice = indice
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("contratoAnteriorCard")
        self.setStyleSheet(
            f"QFrame#contratoAnteriorCard {{ background-color: #F7F9FC; border: 1px solid {BORDER}; border-radius: 12px; }}"
            f"QFrame#contratoAnteriorCard:hover {{ background-color: {TINTE_CLARO}; border: 1px solid {LINEA_AZUL}; }}"
            "QFrame#contratoAnteriorCard QLabel { border: none; background: transparent; }")
        v = lambda col: GeneralModule._valor_ficha(fila, col)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(3)

        arriba = QHBoxLayout()
        id_contrato = comercial_services._normalizar_id_contrato(fila.get(COL_ID, ''))
        lbl_id = QLabel(f"N° Contrato {id_contrato}" if id_contrato else "Contrato sin N°")
        lbl_id.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        arriba.addWidget(lbl_id)
        arriba.addStretch(1)
        estado = v(COL_ESTADO_COMERCIAL)
        if estado != '-':
            lbl_estado = QLabel(estado.capitalize())
            lbl_estado.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px; font-weight: bold; padding: 2px 9px; "
                                     f"border: 1px solid {BORDER}; border-radius: 9px; background-color: {SURFACE};")
            arriba.addWidget(lbl_estado)
        lay.addLayout(arriba)

        detalle = [t for t in (v(COL_FORMA_CONTRATO), v(COL_TIPO_SERVICIO)) if t != '-']
        if detalle:
            lbl_detalle = QLabel(" · ".join(detalle))
            lbl_detalle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
            lay.addWidget(lbl_detalle)
        fechas = [f"Inicio {v(COL_INICIO_CONTRATO)}", f"Término {v(COL_TERMINO_CONTRATO)}"]
        if v(COL_FECHA_BAJA) != '-':
            fechas.append(f"Baja {v(COL_FECHA_BAJA)}")
        lbl_fechas = QLabel(" · ".join(fechas))
        lbl_fechas.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        lay.addWidget(lbl_fechas)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.indice)
        super().mousePressEvent(event)


# Proporción de las 5 columnas de la tarjeta de unidad: VIN/Inicio, Chasis/Término, espacio,
# Comercial/Forma de contrato y Activación/Facturación
_ESTIRAR_COLUMNAS_UNIDAD = (5, 4, 4, 4, 5)


class GeneralUnidadCard(QFrame):
    """Tarjeta clickeable de una unidad (VIN), caja izquierda -> Unidades.
    VIN y Chasis son copiables al pasar el mouse (CopyableLabel) -- único
    lugar donde se puede copiar el VIN ahora que la tabla (y su menú
    contextual "Copiar VIN") fue reemplazada por tarjetas, a pedido
    explícito (20-09-2026). row_idx es la posición en
    GeneralModule._df_unidades_visible."""

    clicked = pyqtSignal(int)

    def __init__(self, row_idx, vin, chasis, razon_social, estado_activacion, industria, etapa_gestion,
                 parent=None, extras=None):
        """`industria` se conserva por compatibilidad pero ya no se muestra
        (07-10-2026). `extras`: dict con cdb, estado_comercial,
        forma_contrato, tipo_facturacion, inicio y termino."""
        super().__init__(parent)
        extras = extras or {}
        self.row_idx = row_idx
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("general_unidad_card")
        # Estilos fijos en QSS_TARJETAS_UNIDAD (una vez en el contenedor); el
        # badge de estado y la etapa conservan el suyo porque su color
        # depende del dato.
        self.setProperty("seleccionado", False)

        # Rejilla de 5 columnas con las mismas proporciones en todas las tarjetas: los chips
        # de una columna quedan alineados entre filas y entre tarjetas
        # (VIN/Inicio, Chasis/Término, espacio, Comercial/Forma, Activación/Facturación)
        grilla = QGridLayout(self)
        grilla.setContentsMargins(12, 8, 12, 8)
        grilla.setHorizontalSpacing(6)
        grilla.setVerticalSpacing(4)
        for columna, estirar in enumerate(_ESTIRAR_COLUMNAS_UNIDAD):
            grilla.setColumnStretch(columna, estirar)

        def poner(fila, columna, widget):
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grilla.addWidget(widget, fila, columna)

        # Razón social, etapa e inicio de contrato ya no se muestran en la
        # tarjeta (09-10-2026); siguen en la ficha de la caja derecha.
        self.lbl_industria = None
        self.lbl_etapa = None
        self.lbl_inicio = None

        self.lbl_vin = CopyableChip()
        base_vin = (f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold; padding: 2px 10px; border-radius: 10px; "
                    f"background-color: #F7F9FC; border: 1px solid {BORDER};")
        self.lbl_vin._BASE_STYLE = base_vin
        self.lbl_vin._HOVER_STYLE = base_vin + f"background-color: {TINTE_CLARO}; color: {AZUL}; border: 1px solid {LINEA_AZUL};"
        self.lbl_vin._COPIADO_STYLE = base_vin + "background-color: #D1FAE5; color: #065F46; border: 1px solid #6EE7B7;"
        self.lbl_vin.setStyleSheet(base_vin)
        self.lbl_vin.set_value("VIN", vin)
        self.lbl_chasis = CopyableChip()
        self.lbl_chasis.set_value("Chasis", chasis)
        poner(0, 0, self.lbl_vin)
        poner(0, 1, self.lbl_chasis)
        self.lbl_rut = None
        self.lbl_cdb = None

        estado_comercial = str(extras.get('estado_comercial', '')).strip()
        self.es_sin_vc = _es_sin_vc(estado_comercial, estado_activacion,
                                    extras.get('forma_contrato', ''), extras.get('tipo_facturacion', ''))
        if self.es_sin_vc:
            self.badge_estado = _crear_pildora("SIN VC", _PAL_GRIS, tooltip="Sin Volvo Connect: sin estado comercial, "
                                               "activación No aplica, Sin contrato y Sin registro")
            poner(0, 4, self.badge_estado)
            self.lbl_vigencia = None
            return
        if _flota_valida(estado_comercial):
            poner(0, 3, _crear_pildora(estado_comercial, _color_estado_comercial(estado_comercial),
                                       "Comercial", "Estado comercial"))
        estado_act = str(estado_activacion).strip()
        self.badge_estado = _crear_pildora(estado_act or "-", _color_estado_activacion(estado_act),
                                           "Activación", "Estado de activación")
        poner(0, 4, self.badge_estado)

        inicio = _formatear_fecha_contrato(extras.get('inicio', ''))[0]
        if inicio:
            poner(1, 0, _crear_pildora(inicio, _PAL_GRIS, "Inicio contrato", "Inicio del contrato", chip=True))
        self.lbl_vigencia = None
        termino, vencido = _formatear_fecha_contrato(extras.get('termino', ''), con_vencimiento=True)
        if termino:
            finalizado = (estado_comercial.upper() in ('BAJA', 'BAJA SOLICITADA')
                          and estado_act.upper() == 'DESCONECTADO')
            color_termino = _PAL_GRIS if (vencido and finalizado) else (_PAL_ROJO if vencido else _PAL_VERDE)
            self.lbl_vigencia = _crear_pildora(termino, color_termino,
                                               "Término contrato", "Término del contrato", chip=True)
            poner(1, 1, self.lbl_vigencia)

        forma = str(extras.get('forma_contrato', '')).strip()
        tipo_fact = str(extras.get('tipo_facturacion', '')).strip()
        color_matriz = _color_forma_facturacion(forma, tipo_fact)
        if _flota_valida(forma):
            poner(1, 3, _crear_pildora(forma, color_matriz, "Forma de contrato", "Forma de contrato", chip=True))
        if _flota_valida(tipo_fact):
            poner(1, 4, _crear_pildora(tipo_fact, color_matriz, "Facturación", "Tipo de facturación", chip=True))

    def set_selected(self, selected):
        _repulir_seleccion(self, selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row_idx)
        super().mousePressEvent(event)


class GeneralModule(QWidget):
    """Módulo 'Clientes y Flota' (nombre de clase histórico: GeneralModule,
    mapeado desde el Sidebar en main_window.py bajo la clave interna
    'Vista General'). Caja izquierda: navegación Cliente/Flota/Unidades, con
    "Cliente" implementada (tabla resumida + filtro de Industria + alta de
    registro). Caja derecha: detalle del cliente seleccionado en la tabla
    (KPIs + pestañas Resumen/Unidades/Contactos, solo "Resumen"
    implementada por ahora)."""

    # Emitida una única vez, la primera vez que GeneralDataPrepThread termina
    # con datos reales (ver _on_prep_finished) -- usada por
    # MainWindow._cargar_vista_general_inicial (24-09-2026, a pedido
    # explícito) para no mostrar la pestaña vacía mientras arma clientes/
    # flota/unidades, extendiendo en su lugar la pantalla de carga.
    primera_carga_lista = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.data_manager = DataManager()
        self.writer = ExcelWriter()
        self.df_clientes_base = pd.DataFrame(columns=COLUMNAS_CLIENTES)
        self.df_unidades_base = pd.DataFrame(columns=COLUMNAS_UNIDADES)
        self.df_comercial_raw = pd.DataFrame()
        self._df_clientes_visible = pd.DataFrame(columns=COLUMNAS_CLIENTES)

        self._selected_cdb = None
        self._selected_cdbs_flota = []
        self._selected_cliente_key = None
        # Pares (RUT, CDB) normalizados que aparecen en más de una fila de
        # df_clientes_base -- es decir, más de una Razón Social distinta
        # comparte el mismo RUT+CDB (típico error de tipeo/duplicado de
        # carga). Se recalcula en _on_prep_finished junto con df_clientes_base
        # (ver _calcular_claves_duplicadas_rut_cdb). Vacío hasta la primera carga.
        self._clientes_con_varias_razones = set()
        # Clave de cliente -> texto del aviso de flotas incoherentes (ver _calcular_avisos_flota)
        self._clientes_aviso_flota = {}
        # (RUT, CDB) del grupo de duplicados actualmente mostrado en la
        # pestaña Duplicados, o None -- ver _populate_duplicados_detalle /
        # _on_unificar_razon_social_clicked.
        self._grupo_duplicados_actual = None
        # VIN seleccionado en la caja izquierda -> Unidades: único estado
        # compartido entre la ficha y el historial de la caja derecha (ver
        # _show_vin_detalle/_show_vin_vacio) -- nunca dos estados
        # independientes que puedan desincronizarse.
        self._vin_seleccionado = None
        self._df_unidades_visible = pd.DataFrame(columns=COLUMNAS_UNIDADES)

        # Tarjetas de la caja izquierda (Cliente/Flota/Unidades, 20-09-2026):
        # reemplazan las tablas anteriores. Cada dict mapea una clave de
        # negocio estable (CDB / "CDB||Flota VC" / VIN) al widget de tarjeta
        # ya construido en el último render, para poder resaltar/desresaltar
        # solo 2 tarjetas al hacer clic (set_selected) en vez de reconstruir
        # toda la lista -- misma lección de rendimiento que provisiones.py
        # (evitar reconstrucciones masivas de tarjetas en cada clic).
        self._cliente_cards = {}
        self._unidad_cards = {}

        # Paginación de cada lista (ver _TARJETAS_POR_PAGINA): DataFrame
        # filtrado actual + página (0-based) que se está mostrando. Los
        # controles "‹ Anterior | Página X de Y | Siguiente ›" (arriba y
        # abajo de cada lista, ver _crear_controles_paginacion) se
        # inicializan en _build_cliente_view/_build_flota_view/
        # _build_unidades_view, antes de que exista cualquier dato.
        self._clientes_df_paginado = pd.DataFrame()
        self._clientes_pagina_actual = 0
        self._clientes_tam_pagina = _TARJETAS_POR_PAGINA
        self._unidades_df_paginado = pd.DataFrame()
        self._unidades_pagina_actual = 0
        self._unidades_tam_pagina = _TARJETAS_POR_PAGINA

        # Render diferido de pestañas ocultas (auditoria de rendimiento,
        # Fase 5, 21-09-2026): filter_table()/_on_prep_finished() actualizan
        # las 3 listas ante cada búsqueda/orden/refresh de datos, pero solo
        # UNA sub-pestaña de Cliente/Flota/Unidades es visible a la vez
        # (self.left_stack). Reconstruir las tarjetas de las otras 2 -- que
        # nadie está viendo -- medía ~1s (página 200) a ~4.5s (página 1000)
        # de trabajo invisible en cada búsqueda. Ahora _render_clientes_cards/
        # _render_flota_cards/_render_unidades_cards solo pintan si su
        # pestaña está visible; si no, marcan esta bandera True y
        # _switch_left_view pinta recién al entrar (ver
        # _renderizar_pestana_si_pendiente). Los DataFrames/estado lógico
        # (_df_*_visible, paginación) se actualizan siempre, sin importar
        # esta bandera -- solo se difiere la construcción de widgets.
        self._clientes_pendiente_render = False
        self._unidades_pendiente_render = False

        # Orden alfabético de cada lista de tarjetas (botón "Ordenar" por
        # pestaña, reemplaza el clic en encabezado de columna que tenían las
        # tablas anteriores). True = ascendente (A-Z).
        self._clientes_orden_asc = True
        self._unidades_orden_asc = True
        # Columna por la que ordena Unidades ('Estado Comercial' o 'Estado Activación');
        # None = por Razón Social.
        self._unidades_orden_columna = None
        # Campo por el que ordena cada lista: 'nombre' (A-Z/Z-A, por
        # defecto) o 'unidades' (Más unidades/Menos unidades, 24-09-2026,
        # a pedido explícito). Solo aplica a Cliente y Flota -- Unidades
        # es una tabla por VIN, no tiene un conteo que ordenar.
        self._clientes_orden_campo = 'nombre'
        # CDB -> {'correo': ..., 'telefono': ...} del "Director de empresas"
        # (BBDD CLIENTES CM.xlsx, Power BI) -- dato de la EMPRESA, no de cada
        # contacto individual (esos ya traen su propio correo/teléfono desde
        # contactos.xlsx). Se muestra aparte, resaltado, en vez de pisar el
        # correo de cada contacto. Se carga de forma perezosa/asíncrona (ver
        # _load_pbi_director_empresa_async); hasta entonces queda vacío y
        # simplemente no se muestra la tarjeta de Director de empresa.
        self._pbi_director_empresa_por_cdb = {}
        self._pbi_director_empresa_thread = None
        # Argumentos base (sin Dirección/Comuna) del último cliente
        # renderizado en "Información del cliente", para poder refrescar
        # solo esa caja cuando Power BI llega tarde (ver
        # _refrescar_info_cliente_pbi).
        self._info_cliente_base_args = None

        # Favoritos de contactos: mismo archivo compartido y misma lógica
        # (contactos_service) que usa contactos.py, para que marcar/desmarcar
        # un favorito acá se refleje también en el módulo Contactos.
        self.pinned_file = os.path.join(os.getcwd(), 'config', 'pinned_contacts.json')
        self.pinned_contacts = contactos_service.cargar_favoritos(self.pinned_file)

        # Actualizacion diferida por visibilidad: si data_ready llega mientras
        # este modulo no es el widget visible (QStackedWidget/QTabWidget lo
        # tiene oculto), no se reprocesa el DataFrame de inmediato -- solo se
        # marca dirty y se recalcula recien cuando el usuario vuelve a entrar
        # (ver MainWindow._trigger_load_data -> refresh_if_dirty).
        self._data_dirty = False

        # Guard de reentrancia de GeneralDataPrepThread (auditoria de
        # rendimiento, fase 4, 21-09-2026): _prep_thread guarda el worker
        # actualmente en vuelo (o None si todavia no se lanzo ninguno).
        # _prep_en_curso es la bandera que realmente gobierna el guard --
        # se pone en True justo antes de start() y en False al principio de
        # _on_prep_finished(); se usa una bandera propia en vez de
        # self._prep_thread.isRunning() porque QThread no garantiza que
        # isRunning() ya sea False en el instante exacto en que se procesa
        # la señal de finalización en el hilo principal (ventana de carrera
        # teorica entre "el hilo emitio la señal" y "Qt marco el hilo como
        # terminado"); una bandera de Python que nosotros mismos controlamos
        # es determinista sin depender de ese detalle interno.
        # _prep_pendiente es un dirty flag independiente de _data_dirty (ese
        # es por VISIBILIDAD; este es por WORKER OCUPADO -- pueden darse a la
        # vez y son condiciones distintas): si load_data() se llama mientras
        # _prep_en_curso es True, no se lanza un segundo worker, se marca
        # _prep_pendiente y _on_prep_finished vuelve a llamar load_data()
        # (con el snapshot mas reciente de DataManager) apenas el worker
        # actual termine -- asi un resultado viejo nunca puede pisar a uno
        # mas nuevo.
        self._prep_thread = None
        self._prep_en_curso = False
        self._prep_pendiente = False
        self._primera_carga_emitida = False

        # Buscador global de MainWindow (self.search_bar): MainWindow lo
        # detecta vía hasattr(current_widget, 'search_input') y le fija el
        # texto directamente (ver MainWindow._on_global_search), mismo patrón
        # que ComercialModule/ContactosModule/etc. Oculto porque el campo
        # visible es el de MainWindow, no uno propio de este módulo. Solo
        # afecta la caja izquierda -> Unidades (ver filter_table más abajo);
        # nunca toca la caja derecha (selección de cliente/CDB, KPIs,
        # Contactos), que sigue su propio ciclo de vida independiente.
        self.search_input = QLineEdit()
        self.search_input.hide()

        self._setup_ui()

        self.data_manager.data_ready.connect(self._on_data_ready)
        self.data_manager.load_error.connect(self._on_error)
        self.data_manager.contactos_ready.connect(self._on_contactos_ready)
        # Historial por VIN (caja derecha -> Unidades -> Historial): se
        # refresca solo con esta señal ligera (ver DataManager.set_logs_df),
        # sin pasar por data_ready/load_data (que reconstruye clientes/
        # flota/unidades completos y podría perder la selección actual).
        self.data_manager.logs_updated.connect(self._on_logs_updated)

        # Contactos y BBDD CLIENTES CM se lanzan recién tras la primera carga
        # (ver _iniciar_cargas_secundarias): en paralelo competían por el GIL
        # con el armado de tarjetas y congelaban la pantalla de carga.
        self._cargas_secundarias_iniciadas = False
        self.load_data()

    def _iniciar_cargas_secundarias(self):
        # Contactos se carga de forma perezosa (solo el módulo Contactos la
        # disparaba antes): sin esto, "Contactos encontrados" queda vacío
        # hasta que el usuario visita ese módulo al menos una vez.
        # Si ya se está leyendo (precarga de MainWindow), no se pide otra vuelta
        if self.data_manager.get_contactos_df().empty and getattr(self.data_manager, 'is_loading_contactos', False) is not True:
            self.data_manager.load_contactos_async()
        self._load_pbi_director_empresa_async()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(15, 10, 15, 10)
        main_layout.setSpacing(6)

        # ==========================================
        # ENCABEZADO (compacto: el título del módulo ahora vive en el
        # chip del header de main_window.py)
        # ==========================================
        # El encabezado de página de main_window se oculta para este módulo
        # (ver _update_module_chip): el título y las pestañas Cliente/Unidades
        # viven dentro de la caja izquierda (ver _setup_left_box), que lleva el
        # mismo marco azul que la derecha (23-10-2026, a pedido explícito).
        boxes_layout = QHBoxLayout()
        boxes_layout.setSpacing(15)

        self.left_box = QFrame()
        self.right_box = QFrame()
        for caja in (self.left_box, self.right_box):
            ThemeManager.apply_card_style(caja)
            caja.setObjectName("cajaGeneral")
            caja.setStyleSheet(f"QFrame#cajaGeneral {{ background-color: {AZUL}; border: 1px solid {AZUL}; border-radius: 24px; }}")

        # Anchos acotados (07-10-2026, a pedido explícito) y política Ignored:
        # el ancho de cada caja lo fijan estos topes y no el texto que
        # contengan (antes un nombre largo ensanchaba la caja derecha).
        self.left_box.setMaximumWidth(ANCHO_MAX_CAJA_IZQUIERDA)
        self.left_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.right_box.setMaximumWidth(ANCHO_MAX_CAJA_DERECHA)
        self.right_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)

        # Izquierda más ancha / derecha más estrecha y compacta (a pedido
        # explícito, 15/16-09-2026): antes 4:5, ahora 5:3.
        # Espacios con factor 0 a ambos lados: solo reciben lo que sobra cuando
        # las cajas llegan a su tope, y así el bloque queda centrado (20-10-2026)
        boxes_layout.addStretch(0)
        boxes_layout.addWidget(self.left_box, stretch=5)
        boxes_layout.addWidget(self.right_box, stretch=3)
        boxes_layout.addStretch(0)
        main_layout.addLayout(boxes_layout, stretch=1)

        self._setup_left_box()
        self._setup_right_box()

        # Se crean al final para quedar encima del contenido de cada caja
        self._esqueleto_izq = EsqueletoCarga(self._hoja_izquierda, 'tarjetas')
        self._esqueleto_der = EsqueletoCarga(self.right_box, 'ficha')

    def _esqueletos(self):
        # __dict__.get: tolera instancias creadas con __new__ en los tests
        return [e for e in (self.__dict__.get('_esqueleto_izq'), self.__dict__.get('_esqueleto_der')) if e is not None]

    DURACION_ANIMACION_BREVE_MS = 300

    def _animar_carga_breve(self, solo_izquierda=False):
        """Esqueleto corto al cambiar de pestaña o buscar. Si hay una carga
        real en curso ya hay esqueleto y no se toca."""
        if self.__dict__.get('_prep_en_curso'):
            return
        esqueletos = self._esqueletos()
        if not esqueletos:
            return
        if solo_izquierda:
            esqueletos = esqueletos[:1]
        for esqueleto in esqueletos:
            esqueleto.iniciar_ya(rapido=True)
        timer = self.__dict__.get('_timer_animacion_breve')
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._terminar_animacion_breve)
            self._timer_animacion_breve = timer
        self._esqueletos_breves = esqueletos
        timer.start(self.DURACION_ANIMACION_BREVE_MS)

    def _terminar_animacion_breve(self):
        if self.__dict__.get('_prep_en_curso'):
            return
        for esqueleto in self.__dict__.get('_esqueletos_breves', []):
            esqueleto.terminar()

    # ==========================================
    # CONTROLES SUPERIORES (fuera de las cajas)
    # ==========================================
    def _setup_top_controls(self, main_layout):
        barra = QFrame()
        barra.setObjectName("barraPestanasGeneral")
        barra.setStyleSheet(QSS_CONTENEDOR_PESTANAS_CLARO)
        controls_layout = QHBoxLayout(barra)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(2)

        self.btn_nav_cliente = QPushButton("Cliente")
        self.btn_nav_unidades = QPushButton("Unidades")
        self._nav_buttons = [self.btn_nav_cliente, self.btn_nav_unidades]

        # Mismo estilo tipo pestaña que Ingreso y Conciliación / Comercial:
        # borde de color por estado (normal/seleccionada) y hover.
        nav_tab_style = QSS_PESTANAS_CLARAS
        for i, btn in enumerate(self._nav_buttons):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(nav_tab_style)
            btn.clicked.connect(lambda checked, idx=i: self._switch_left_view(idx))
            controls_layout.addWidget(btn)
        self.btn_nav_cliente.setChecked(True)

        # Mismo botón/patrón que btn_advanced_filters en comercial.py (texto
        # " Filtros" + ícono, botón secundario estándar, sin tamaño fijo
        # cuadrado), reimplementado aquí en vez de importado para no tocar
        # comercial.py. Agrupado junto a Cliente/Flota/Unidades (a pedido
        # explícito), en vez de aislado al otro extremo de la fila.
        #
        # Único botón "Filtros" de este módulo: solo visible en la pestaña
        # "Unidades" (ver _switch_left_view). El filtro de Industria vivía
        # antes en un botón propio de Cliente; se movió acá junto a Razón
        # Social/Estado Activación a pedido explícito (15-09-2026), ya que
        # 'Industria/s' es visible como columna en Unidades, no en Cliente.
        self.btn_filtro_unidades = QPushButton(" Filtros")
        self.btn_filtro_unidades.setIcon(ThemeManager.icon('fa5s.filter', color='white'))
        self.btn_filtro_unidades.setCheckable(True)
        self.btn_filtro_unidades.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filtro_unidades.setStyleSheet(QSS_BOTON_FILTRO_SOBRE_AZUL)
        self.btn_filtro_unidades.toggled.connect(self._toggle_filtro_unidades)
        self.btn_filtro_unidades.hide()
        controls_layout.addWidget(self.btn_filtro_unidades)

        # "+ Nuevo Cliente" / "Importar Excel Power BI" (alta de unidades)
        # quitados de General (25-09-2026, refactor: esa responsabilidad
        # quedó centralizada en Comercial -> pestaña "Unidad nueva", ver
        # ComercialModule._build_unidad_nueva_tab/_abrir_importar_powerbi en
        # comercial.py). General conserva solo consulta/ficha/historial de
        # clientes y unidades.
        controls_layout.addStretch()

        main_layout.addWidget(barra)

    # ==========================================
    # CAJA DERECHA: detalle del cliente seleccionado
    # ==========================================
    def _setup_right_box(self):
        layout = QVBoxLayout(self.right_box)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self._build_cliente_vacio_view())     # index 0
        # index 1 (detalle de cliente: KPIs + pestañas Resumen/Unidades/
        # Contactos/Historial) es el subárbol más pesado del módulo y el
        # estado inicial SIEMPRE es el índice 0 ("selecciona un cliente");
        # se construye recién la primera vez que el usuario selecciona una
        # fila (ver _ensure_detalle_view_built, llamado desde
        # _show_cliente_detalle), no durante el primer render de la ventana.
        self._detalle_view_built = False
        self.right_stack.addWidget(QWidget())                            # index 1 (placeholder)
        self.right_stack.addWidget(self._build_flota_sin_cdb_view())     # index 2
        # index 3/4: contexto de VIN (caja izquierda -> Unidades), separado
        # del contexto de cliente (índices 0/1/2) -- ver _switch_left_view,
        # que decide cuál mostrar según la pestaña izquierda activa.
        self.right_stack.addWidget(self._build_vin_vacio_view())         # index 3
        self.right_stack.addWidget(self._build_vin_detalle_view())       # index 4

        # El scroll ya NO envuelve toda la caja derecha (encabezado + KPIs +
        # pestañas Resumen/Unidades/Contactos quedaban desplazándose junto
        # con el contenido, a pedido explícito se corrige): ahora vive
        # únicamente alrededor de self.detalle_stack, dentro de
        # _build_cliente_detalle_view (ver self.detalle_scroll ahí), para
        # que solo el contenido de la pestaña activa se desplace y el resto
        # quede fijo.
        layout.addWidget(self.right_stack, stretch=1)

    def _ensure_detalle_view_built(self):
        """Construye el detalle de cliente (índice 1 de right_stack) la
        primera vez que hace falta, reemplazando el placeholder vacío que
        dejó _setup_right_box(). Reemplazo en el MISMO índice (remove +
        insert en la posición 1) para no correr el índice 2
        (_build_flota_sin_cdb_view), que ya existe desde el arranque."""
        if self._detalle_view_built:
            return
        placeholder = self.right_stack.widget(1)
        self.right_stack.removeWidget(placeholder)
        placeholder.deleteLater()
        self.right_stack.insertWidget(1, self._build_cliente_detalle_view())
        self._detalle_view_built = True

    def _build_cliente_vacio_view(self):
        """Detalle de cliente sin selección: la misma hoja con portada, pero con
        los datos en blanco y una invitación a elegir un cliente."""
        widget = QWidget()
        raiz = QVBoxLayout(widget)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        hoja = QFrame()
        hoja.setObjectName("hojaCliente")
        hoja.setStyleSheet(f"QFrame#hojaCliente {{ background-color: {SURFACE}; border: none; border-radius: 16px; }}")
        lay_hoja = QVBoxLayout(hoja)
        lay_hoja.setContentsMargins(0, 0, 0, 0)
        lay_hoja.setSpacing(0)

        portada = QFrame()
        portada.setObjectName("fichaPortada")
        portada.setStyleSheet(
            f"QFrame#fichaPortada {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {AZUL_HOVER}, stop:1 {AZUL}); "
            "border-top-left-radius: 16px; border-top-right-radius: 16px; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }"
            "QFrame#fichaPortada QLabel { background: transparent; border: none; }")
        lay_p = QVBoxLayout(portada)
        lay_p.setContentsMargins(10, 16, 10, 0)
        lay_p.setSpacing(6)

        icono = QLabel()
        icono.setFixedSize(46, 46)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.building', color=TEXTO_SOBRE_AZUL, size=20))
        icono.setStyleSheet("background: rgba(255,255,255,0.08); border: 2px dashed rgba(255,255,255,0.4); border-radius: 23px;")
        lay_p.addWidget(icono, 0, Qt.AlignmentFlag.AlignHCenter)

        titulo = QLabel("Ningún cliente seleccionado")
        titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulo.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 18px; font-weight: bold;")
        lay_p.addWidget(titulo)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addStretch()
        for texto in ("RUT: —", "CDB Comercial: —", "CDB Flota: —"):
            chip = QLabel(texto)
            chip.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; padding: 3px 10px; "
                               "border: 1px solid rgba(255,255,255,0.18); border-radius: 9px; background-color: rgba(255,255,255,0.05);")
            chips.addWidget(chip)
        chips.addStretch()
        lay_p.addLayout(chips)

        kpis = QHBoxLayout()
        kpis.setSpacing(8)
        for titulo_k, icono_k, fondo, color in (
                ("UNIDADES", "fa5s.truck", "#E8ECF4", TEXT_MUTED), ("VOLVO CONNECT", "fa5s.wifi", "#F1F5F9", TEXT_MUTED),
                ("CIV", "fa5s.video", "#F1F5F9", TEXT_MUTED), ("SAFETY ZONE", "fa5s.shield-alt", "#F1F5F9", TEXT_MUTED)):
            card, _ = self._crear_kpi_comercial(titulo_k, "—", "")
            kpis.addWidget(card)
        lay_p.addLayout(kpis)

        pestanas = QHBoxLayout()
        pestanas.setSpacing(2)
        pestanas.addStretch()
        for texto in ("Resumen", "Unidades", "Flotas VC", "Contactos"):
            lbl_tab = QLabel(texto)
            lbl_tab.setStyleSheet("color: rgba(201,212,234,0.45); font-size: 13px; padding: 10px 16px;")
            pestanas.addWidget(lbl_tab)
        pestanas.addStretch()
        lay_p.addSpacing(2)
        lay_p.addLayout(pestanas)
        lay_hoja.addWidget(portada)

        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 12, 14, 14)
        invitacion = QFrame()
        invitacion.setObjectName("invitacionCliente")
        invitacion.setStyleSheet(f"QFrame#invitacionCliente {{ background-color: #F3F5F9; border: 1px dashed {LINEA_AZUL}; border-radius: 14px; }}"
                                 "QFrame#invitacionCliente QLabel { background: transparent; border: none; }")
        lay_i = QVBoxLayout(invitacion)
        lay_i.setContentsMargins(20, 26, 20, 26)
        lay_i.setSpacing(6)
        mano = QLabel()
        mano.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mano.setPixmap(ThemeManager.icon_pixmap('fa5s.hand-pointer', color=AZUL, size=26))
        lbl1 = QLabel("Presiona un cliente de la lista")
        lbl1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl1.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        lbl2 = QLabel("Aquí verás su información, unidades, flotas y contactos.")
        lbl2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl2.setWordWrap(True)
        lbl2.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        lay_i.addWidget(mano)
        lay_i.addWidget(lbl1)
        lay_i.addWidget(lbl2)
        cuerpo.addWidget(invitacion)
        cuerpo.addStretch()
        lay_hoja.addLayout(cuerpo, 1)

        raiz.addWidget(hoja, 1)
        return widget

    # ==========================================
    # CAJA DERECHA: fila de Flota sin CDB asociado a ningún cliente (CDB
    # vacío, "-", o sin match en df_clientes_base). No hay CDB para resolver
    # KPIs/Unidades/Contactos, así que se muestra solo el dato de Flota VC
    # de esa fila; si tampoco hay Flota VC, se indica en rojo que no se
    # encontró información (ver _show_flota_sin_cliente).
    # ==========================================
    def _build_flota_sin_cdb_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl_title = QLabel("Sin cliente asociado")
        lbl_title.setStyleSheet("color: white; font-size: 15px; font-weight: bold;")

        lbl_subtitle = QLabel("Esta fila de Flota no tiene un CDB asociado a un cliente, así que no se puede mostrar su detalle completo.")
        lbl_subtitle.setWordWrap(True)
        lbl_subtitle.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px;")

        info_row = QHBoxLayout()
        info_row.setSpacing(6)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap('fa5s.route', color=TEXTO_SOBRE_AZUL, size=11))
        icon_lbl.setFixedWidth(15)
        lbl_label = QLabel("Flota VC")
        lbl_label.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px;")
        self.lbl_flota_sin_cliente_valor = QLabel("")
        self.lbl_flota_sin_cliente_valor.setWordWrap(True)
        self.lbl_flota_sin_cliente_valor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_row.addWidget(icon_lbl)
        info_row.addWidget(lbl_label)
        info_row.addStretch()
        info_row.addWidget(self.lbl_flota_sin_cliente_valor, stretch=1)

        layout.addStretch()
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_subtitle)
        layout.addLayout(info_row)
        layout.addStretch()
        return widget

    # ==========================================
    # CAJA DERECHA: contexto de VIN (caja izquierda -> Unidades). Ficha
    # completa (33 columnas) + Historial del VIN seleccionado, con el mismo
    # patrón visual de pestañas internas que ya usa el detalle de cliente
    # (Resumen/Unidades/Contactos/Historial), pero acotado a estos 2.
    # ==========================================
    def _build_vin_vacio_view(self):
        """Ficha de unidad sin selección: la misma hoja con portada, con los
        datos en blanco y una invitación a elegir una unidad."""
        widget = QWidget()
        raiz = QVBoxLayout(widget)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        hoja = QFrame()
        hoja.setObjectName("hojaUnidad")
        hoja.setStyleSheet(f"QFrame#hojaUnidad {{ background-color: {SURFACE}; border: none; border-radius: 16px; }}")
        lay_hoja = QVBoxLayout(hoja)
        lay_hoja.setContentsMargins(0, 0, 0, 0)
        lay_hoja.setSpacing(0)

        portada = QFrame()
        portada.setObjectName("fichaPortada")
        portada.setStyleSheet(
            f"QFrame#fichaPortada {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {AZUL_HOVER}, stop:1 {AZUL}); "
            "border-top-left-radius: 16px; border-top-right-radius: 16px; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }"
            "QFrame#fichaPortada QLabel { background: transparent; border: none; }")
        lay_p = QVBoxLayout(portada)
        lay_p.setContentsMargins(16, 16, 16, 0)
        lay_p.setSpacing(2)

        icono = QLabel()
        icono.setFixedSize(52, 52)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.truck', color=TEXTO_SOBRE_AZUL, size=22))
        icono.setStyleSheet("background: rgba(255,255,255,0.08); border: 2px dashed rgba(255,255,255,0.4); border-radius: 26px;")
        lay_p.addWidget(icono, 0, Qt.AlignmentFlag.AlignHCenter)
        lay_p.addSpacing(4)

        titulo = QLabel("Ninguna unidad seleccionada")
        titulo.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 16px; font-weight: bold;")
        sub = QLabel("Sin datos de Volvo Connect")
        sub.setStyleSheet("color: rgba(201,212,234,0.6); font-size: 11px;")
        lay_p.addWidget(titulo, 0, Qt.AlignmentFlag.AlignHCenter)
        lay_p.addWidget(sub, 0, Qt.AlignmentFlag.AlignHCenter)
        lay_p.addSpacing(8)

        vin = QLabel("VIN —")
        vin.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 18px; font-weight: bold;")
        lay_p.addWidget(vin, 0, Qt.AlignmentFlag.AlignHCenter)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addStretch()
        for texto in ("Chasis —", "Modelo —"):
            chip = QLabel(texto)
            chip.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; font-weight: bold; padding: 3px 11px; "
                               "border-radius: 10px; background-color: rgba(255,255,255,0.08);")
            chips.addWidget(chip)
        chips.addStretch()
        lay_p.addSpacing(6)
        lay_p.addLayout(chips)

        pestanas = QHBoxLayout()
        pestanas.addStretch()
        for texto in ("Ficha", "Historial", "Contratos anteriores"):
            lbl_tab = QLabel(texto)
            lbl_tab.setStyleSheet("color: rgba(201,212,234,0.45); font-size: 13px; padding: 10px 16px;")
            pestanas.addWidget(lbl_tab)
        pestanas.addStretch()
        lay_p.addSpacing(4)
        lay_p.addLayout(pestanas)
        lay_hoja.addWidget(portada)

        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 12, 14, 14)
        invitacion = QFrame()
        invitacion.setObjectName("invitacionUnidad")
        invitacion.setStyleSheet(f"QFrame#invitacionUnidad {{ background-color: #F3F5F9; border: 1px dashed {LINEA_AZUL}; border-radius: 14px; }}"
                                 "QFrame#invitacionUnidad QLabel { background: transparent; border: none; }")
        lay_i = QVBoxLayout(invitacion)
        lay_i.setContentsMargins(20, 26, 20, 26)
        lay_i.setSpacing(6)
        mano = QLabel()
        mano.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mano.setPixmap(ThemeManager.icon_pixmap('fa5s.hand-pointer', color=AZUL, size=26))
        lbl1 = QLabel("Presiona una unidad de la lista")
        lbl1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl1.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
        lbl2 = QLabel("Aquí verás su ficha completa y su historial.")
        lbl2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl2.setWordWrap(True)
        lbl2.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        lay_i.addWidget(mano)
        lay_i.addWidget(lbl1)
        lay_i.addWidget(lbl2)
        cuerpo.addWidget(invitacion)
        cuerpo.addStretch()
        lay_hoja.addLayout(cuerpo, 1)

        raiz.addWidget(hoja, 1)
        return widget

    def _build_vin_detalle_view(self):
        """Detalle de unidad como afiche: una hoja blanca con portada azul
        (estado de Volvo Connect, VIN, chasis y modelo, y las pestañas Ficha/
        Historial) y debajo el contenido de la pestaña activa."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hoja = QFrame()
        hoja.setObjectName("hojaUnidad")
        hoja.setStyleSheet(f"QFrame#hojaUnidad {{ background-color: {SURFACE}; border: none; border-radius: 16px; }}")
        lay_hoja = QVBoxLayout(hoja)
        lay_hoja.setContentsMargins(0, 0, 0, 0)
        lay_hoja.setSpacing(0)

        portada = QFrame()
        portada.setObjectName("fichaPortada")
        portada.setStyleSheet(
            f"QFrame#fichaPortada {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {AZUL_HOVER}, stop:1 {AZUL}); "
            "border-top-left-radius: 16px; border-top-right-radius: 16px; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }"
            "QFrame#fichaPortada QLabel { background: transparent; border: none; }")
        lay_p = QVBoxLayout(portada)
        lay_p.setContentsMargins(16, 14, 16, 0)
        lay_p.setSpacing(2)

        self._ficha_hero_icono = QLabel()
        self._ficha_hero_icono.setFixedSize(44, 44)
        self._ficha_hero_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ficha_hero_icono.setStyleSheet(
            "background: rgba(255,255,255,0.12); border: 2px dashed rgba(255,255,255,0.45); border-radius: 22px;")
        self._ficha_hero_titulo = QLabel("")
        self._ficha_hero_titulo.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        self._ficha_hero_sub = QLabel("")
        self._ficha_hero_sub.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px;")
        lay_p.addWidget(self._ficha_hero_icono, 0, Qt.AlignmentFlag.AlignHCenter)
        lay_p.addSpacing(4)
        lay_p.addWidget(self._ficha_hero_titulo, 0, Qt.AlignmentFlag.AlignHCenter)
        lay_p.addWidget(self._ficha_hero_sub, 0, Qt.AlignmentFlag.AlignHCenter)
        self._ficha_alerta = QLabel("")
        self._ficha_alerta.setStyleSheet(
            f"background: {DANGER}; color: white; font-size: 11px; font-weight: bold; padding: 4px 12px; border-radius: 11px;")
        self._ficha_alerta.hide()
        lay_p.addSpacing(4)
        lay_p.addWidget(self._ficha_alerta, 0, Qt.AlignmentFlag.AlignHCenter)
        lay_p.addSpacing(4)

        self.lbl_vin_detalle_title = CopyableTitulo("")
        lay_p.addWidget(self.lbl_vin_detalle_title, 0, Qt.AlignmentFlag.AlignHCenter)

        # Se siguen actualizando desde _render_cabecera_vin aunque ya no se muestren aquí
        self.vin_pastillas_layout = QHBoxLayout()
        self.lbl_vin_detalle_cdb = CopyableLabel()
        self.lbl_vin_detalle_rut = CopyableLabel()

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addStretch()
        self.lbl_vin_detalle_chasis = CopyableLabel()
        self.lbl_vin_detalle_modelo = CopyableLabel()
        self.lbl_vin_detalle_periodo = CopyableLabel()
        for chip in (self.lbl_vin_detalle_chasis, self.lbl_vin_detalle_modelo, self.lbl_vin_detalle_periodo):
            chip._BASE_STYLE = (f"color: white; font-size: 11px; font-weight: bold; padding: 3px 11px; "
                                "border: none; border-radius: 10px; background-color: rgba(255,255,255,0.16);")
            chip._HOVER_STYLE = (f"color: {AZUL}; font-size: 11px; font-weight: bold; padding: 3px 11px; "
                                 "border: none; border-radius: 10px; background-color: white;")
            chip.setStyleSheet(chip._BASE_STYLE)
            chips.addWidget(chip)
        chips.addStretch()
        lay_p.addSpacing(6)
        lay_p.addLayout(chips)

        vin_nav_barra = QFrame()
        vin_nav_barra.setObjectName("barraPestanasGeneral")
        vin_nav_barra.setStyleSheet(QSS_CONTENEDOR_PESTANAS_CLARO)
        vin_nav_layout = QHBoxLayout(vin_nav_barra)
        vin_nav_layout.setContentsMargins(0, 0, 0, 0)
        vin_nav_layout.setSpacing(2)
        self.btn_vin_ficha = QPushButton("Ficha")
        self.btn_vin_historial = QPushButton("Historial")
        self.btn_vin_contratos = QPushButton("Contratos anteriores")
        self._vin_nav_buttons = [self.btn_vin_ficha, self.btn_vin_historial, self.btn_vin_contratos]
        vin_nav_layout.addStretch()
        for i, btn in enumerate(self._vin_nav_buttons):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(QSS_PESTANAS_CLARAS)
            btn.clicked.connect(lambda checked, idx=i: self._switch_vin_detalle_view(idx))
            vin_nav_layout.addWidget(btn)
        vin_nav_layout.addStretch()
        self.btn_vin_ficha.setChecked(True)
        lay_p.addSpacing(4)
        lay_p.addWidget(vin_nav_barra)
        lay_hoja.addWidget(portada)

        self.vin_detalle_stack = _StackedWidgetTamañoActual()
        self.vin_detalle_stack.addWidget(self._build_ficha_vin_view())      # index 0
        self.vin_detalle_stack.addWidget(self._build_historial_vin_view())  # index 1
        self.vin_detalle_stack.addWidget(self._build_contratos_anteriores_view())  # index 2

        # El scroll envuelve el stack: solo la pestaña activa se desplaza
        self.vin_detalle_scroll = QScrollArea()
        self.vin_detalle_scroll.setWidgetResizable(True)
        self.vin_detalle_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.vin_detalle_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.vin_detalle_scroll.viewport().setStyleSheet("background: transparent;")
        self.vin_detalle_scroll.setWidget(self.vin_detalle_stack)
        self.vin_detalle_stack.setStyleSheet("background: transparent;")
        lay_hoja.addWidget(self.vin_detalle_scroll, 1)

        layout.addWidget(hoja, 1)
        return widget

    _FICHA_VIN_TARJETAS = ("Cliente", "Situación de la unidad", "Unidad", "Facturación y CM")

    def _build_ficha_vin_view(self):
        """Ficha de la unidad con formato de afiche: portada con el estado de
        Volvo Connect, vigencia del contrato y tarjetas por tema (cliente,
        situación, unidad, facturación y CM). Se construye una vez con las
        tarjetas vacías; _render_ficha_vin() las repuebla en cada cambio de VIN."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        self._ficha_aviso_anterior = QFrame()
        self._ficha_aviso_anterior.setObjectName("avisoContratoAnterior")
        self._ficha_aviso_anterior.setStyleSheet(
            f"QFrame#avisoContratoAnterior {{ background-color: #FEF3C7; border: 1px solid #F3D98B; border-radius: 12px; }}"
            "QFrame#avisoContratoAnterior QLabel { border: none; background: transparent; color: #7A5B00; font-size: 11px; font-weight: bold; }")
        lay_aviso = QHBoxLayout(self._ficha_aviso_anterior)
        lay_aviso.setContentsMargins(12, 8, 8, 8)
        self._lbl_aviso_anterior = QLabel("")
        self._lbl_aviso_anterior.setWordWrap(True)
        btn_volver = QPushButton("Ver contrato actual")
        btn_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_minimo(btn_volver)
        btn_volver.clicked.connect(self._volver_a_contrato_actual)
        lay_aviso.addWidget(self._lbl_aviso_anterior, 1)
        lay_aviso.addWidget(btn_volver)
        self._ficha_aviso_anterior.hide()
        layout.addWidget(self._ficha_aviso_anterior)

        self._ficha_contrato_holder = QVBoxLayout()
        self._ficha_contrato_holder.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._ficha_contrato_holder)

        self._ficha_vin_layouts = {}
        self._ficha_vin_cards = {}
        for titulo in self._FICHA_VIN_TARJETAS:
            tarjeta = QFrame()
            tarjeta.setObjectName("fichaTarjeta")
            tarjeta.setStyleSheet(f"QFrame#fichaTarjeta {{ background: transparent; border: 1px solid {BORDER}; border-radius: 14px; }}"
                                  "QFrame#fichaTarjeta QLabel { border: none; background: transparent; }")
            lay_t = QVBoxLayout(tarjeta)
            lay_t.setContentsMargins(12, 8, 12, 8)
            lay_t.setSpacing(2)
            lbl_t = QLabel(titulo.upper())
            lbl_t.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
            lay_t.addWidget(lbl_t)
            filas = QVBoxLayout()
            filas.setSpacing(0)
            lay_t.addLayout(filas)
            layout.addWidget(tarjeta)
            self._ficha_vin_layouts[titulo] = filas
            self._ficha_vin_cards[titulo] = tarjeta

        layout.addStretch()

        self._ficha_cta = QFrame()
        self._ficha_cta.setObjectName("fichaCta")
        self._ficha_cta.setStyleSheet(f"QFrame#fichaCta {{ background-color: #F3F5F9; border: 1px solid {BORDER}; border-radius: 14px; }}"
                                      "QFrame#fichaCta QLabel { border: none; background: transparent; }")
        lay_cta = QHBoxLayout(self._ficha_cta)
        lay_cta.setContentsMargins(14, 10, 14, 10)
        lay_cta.setSpacing(12)
        icono_cta = QLabel()
        icono_cta.setPixmap(ThemeManager.icon_pixmap('fa5s.phone-alt', color=AZUL, size=18))
        texto_cta = QVBoxLayout()
        texto_cta.setSpacing(0)
        lbl_cta1 = QLabel("Ofrécele Volvo Connect")
        lbl_cta1.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        lbl_cta2 = QLabel("Contacta al cliente para activar esta unidad.")
        lbl_cta2.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        lbl_cta2.setWordWrap(True)
        texto_cta.addWidget(lbl_cta1)
        texto_cta.addWidget(lbl_cta2)
        btn_cta = QPushButton("Contactar")
        btn_cta.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_azul(btn_cta)
        btn_cta.setToolTip("Abre el Gestor de Correos con esta unidad seleccionada")
        btn_cta.clicked.connect(self._contactar_para_ofrecer_vc)
        lay_cta.addWidget(icono_cta)
        lay_cta.addLayout(texto_cta, 1)
        lay_cta.addWidget(btn_cta)
        layout.addWidget(self._ficha_cta)
        return widget

    def _build_historial_vin_view(self):
        """Contenedor vertical de tarjetas de evento (_create_evento_historial_card),
        más reciente primero -- nunca una tabla horizontal. Se construye
        vacío; _render_historial_vin() lo repuebla en cada cambio de VIN."""
        widget = QWidget()
        self.historial_vin_layout = QVBoxLayout(widget)
        self.historial_vin_layout.setContentsMargins(0, 0, 0, 0)
        self.historial_vin_layout.setSpacing(6)
        return widget

    def _build_contratos_anteriores_view(self):
        """Lista de los contratos anteriores del VIN seleccionado; un clic
        muestra su ficha completa en la pestaña Ficha. Se repuebla en cada
        cambio de VIN (_render_contratos_anteriores)."""
        widget = QWidget()
        self.contratos_anteriores_layout = QVBoxLayout(widget)
        self.contratos_anteriores_layout.setContentsMargins(14, 12, 14, 14)
        self.contratos_anteriores_layout.setSpacing(6)
        self._contratos_anteriores_df = pd.DataFrame()
        self._contrato_anterior_mostrado = False
        self._fila_vin_actual = None
        return widget

    def _render_contratos_anteriores(self, df_anteriores):
        self._contratos_anteriores_df = df_anteriores
        layout = self.contratos_anteriores_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        n = len(df_anteriores)
        self.btn_vin_contratos.setText(f"Contratos anteriores ({n})" if n else "Contratos anteriores")
        if df_anteriores.empty:
            lbl_vacio = QLabel("Esta unidad no tiene contratos anteriores.")
            lbl_vacio.setWordWrap(True)
            lbl_vacio.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 8px 0;")
            layout.addWidget(lbl_vacio)
        else:
            ayuda = QLabel("Elige un contrato para ver su resumen.")
            ayuda.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            layout.addWidget(ayuda)
            for i in range(n):
                card = _ContratoAnteriorCard(i, df_anteriores.iloc[i])
                card.clicked.connect(self._on_contrato_anterior_clicked)
                layout.addWidget(card)
        layout.addStretch()

    def _obtener_contratos_anteriores(self, vin):
        """Contratos anteriores del VIN, ya procesados igual que la ficha actual."""
        df_todos = self.data_manager.df_master
        anteriores = comercial_services.contratos_anteriores(df_todos, vin)
        if anteriores.empty:
            return anteriores
        return comercial_services.procesar_df_comercial(anteriores.copy())

    def _on_contrato_anterior_clicked(self, indice):
        if indice < 0 or indice >= len(self._contratos_anteriores_df):
            return
        fila = self._contratos_anteriores_df.iloc[indice]
        self._switch_vin_detalle_view(0)
        self._contrato_anterior_mostrado = True
        self._render_cabecera_vin(fila)
        self._render_ficha_vin(fila)
        id_contrato = comercial_services._normalizar_id_contrato(fila.get(COL_ID, ''))
        self._lbl_aviso_anterior.setText(
            f"Contrato anterior{f' N° {id_contrato}' if id_contrato else ''}: es un contrato finalizado de esta unidad.")
        self._ficha_aviso_anterior.show()
        self._ficha_cta.setVisible(False)

    def _volver_a_contrato_actual(self):
        self._contrato_anterior_mostrado = False
        self._ficha_aviso_anterior.hide()
        fila = self._fila_vin_actual
        if fila is not None:
            self._render_cabecera_vin(fila)
            self._render_ficha_vin(fila)

    def _create_evento_historial_card(self, evento):
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{ background-color: {BACKGROUND}; border-radius: 8px; border: 1px solid {BORDER}; }}
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        top_row = QHBoxLayout()
        top_row.setSpacing(5)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap('fa5s.history', color=PRIMARY, size=10))
        top_row.addWidget(icon_lbl)
        lbl_fecha = QLabel(self._formatear_fecha_historial(evento.get('FECHA Y HORA', '')))
        lbl_fecha.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 10px; font-weight: bold;")
        top_row.addWidget(lbl_fecha)
        top_row.addStretch()
        modulo = str(evento.get('MÓDULO', '')).strip()
        if modulo:
            lbl_modulo = QLabel(modulo)
            lbl_modulo.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9px; font-weight: bold; background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 4px; padding: 1px 6px;")
            top_row.addWidget(lbl_modulo)
        layout.addLayout(top_row)

        lbl_campo = QLabel(str(evento.get('CAMPO MODIFICADO', '')).strip() or "—")
        lbl_campo.setWordWrap(True)
        lbl_campo.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px; font-weight: bold;")
        layout.addWidget(lbl_campo)

        cambio_row = QHBoxLayout()
        cambio_row.setSpacing(4)
        lbl_anterior = QLabel(str(evento.get('VALOR ANTERIOR', '')).strip() or "-")
        lbl_anterior.setWordWrap(True)
        lbl_anterior.setStyleSheet(f"color: {DANGER}; font-size: 10px;")
        icon_arrow = QLabel()
        icon_arrow.setPixmap(ThemeManager.icon_pixmap('fa5s.long-arrow-alt-right', color=TEXT_MUTED, size=9))
        lbl_nuevo = QLabel(str(evento.get('NUEVO VALOR', '')).strip() or "-")
        lbl_nuevo.setWordWrap(True)
        lbl_nuevo.setStyleSheet(f"color: {SUCCESS}; font-size: 10px; font-weight: bold;")
        cambio_row.addWidget(lbl_anterior, stretch=1)
        cambio_row.addWidget(icon_arrow)
        cambio_row.addWidget(lbl_nuevo, stretch=1)
        layout.addLayout(cambio_row)

        return frame

    @staticmethod
    def _formatear_fecha_historial(valor):
        """'2026-09-15 17:15:00' -> '15-09-2026 17:15'. Mismo criterio
        robusto (format='mixed' + dayfirst=True) que ya usa HistorialModule
        (historial.py) para tolerar registros migrados desde el .xlsx legado
        con otro formato. Si no se puede parsear, se muestra el valor tal
        cual en vez de esconderlo. Función pura."""
        texto = str(valor).strip()
        if not texto:
            return "-"
        parsed = pd.to_datetime(texto, format='mixed', dayfirst=True, errors='coerce')
        if pd.isna(parsed):
            return texto
        return parsed.strftime('%d-%m-%Y %H:%M')

    def _switch_vin_detalle_view(self, index):
        if index == 0 and getattr(self, '_contrato_anterior_mostrado', False):
            self._volver_a_contrato_actual()
        for i, btn in enumerate(self._vin_nav_buttons):
            btn.setChecked(i == index)
        self.vin_detalle_stack.setCurrentIndex(index)
        # sizeHint/minimumSizeHint de _StackedWidgetTamañoActual cambian con
        # la página actual: sin este aviso explícito, el layout padre (y el
        # QScrollArea que lo envuelve) puede seguir usando el tamaño
        # cacheado de la página anterior hasta el próximo evento de resize.
        self.vin_detalle_stack.updateGeometry()

    @staticmethod
    def _valor_ficha(fila, col_name):
        """Valor de una columna de la fila de df_comercial_raw ya listo para
        mostrar en la ficha: '-' para vacío/NaN/None, texto tal cual en caso
        contrario. Función pura (no usa self.*)."""
        valor = fila.get(col_name, '') if hasattr(fila, 'get') else ''
        if valor is None or (isinstance(valor, float) and pd.isna(valor)):
            return '-'
        texto = str(valor).strip()
        return texto if texto and texto.lower() not in ('nan', 'none', '<na>') else '-'

    def _render_cabecera_vin(self, fila):
        """Pastillas de estado y chips copiables bajo el VIN."""
        v = lambda col: self._valor_ficha(fila, col)
        while self.vin_pastillas_layout.count():
            item = self.vin_pastillas_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def pastilla(texto, fondo, color, borde="none"):
            lbl = QLabel(texto)
            lbl.setStyleSheet(f"background-color: {fondo}; color: {color}; border: {borde}; "
                              "font-size: 10px; font-weight: bold; padding: 3px 10px; border-radius: 10px;")
            return lbl

        if v(COL_PERIODO_INTERNO) != '-':
            self.vin_pastillas_layout.addWidget(pastilla(
                f"Periodo {v(COL_PERIODO_INTERNO)}", BACKGROUND, TEXT_SECONDARY, f"1px solid {BORDER}"))
        self.vin_pastillas_layout.addStretch()

        self.lbl_vin_detalle_chasis.set_value("Chasis", v(COL_CHASIS))
        self.lbl_vin_detalle_modelo.set_value("Modelo", v(COL_MODELO))
        self.lbl_vin_detalle_modelo.setVisible(v(COL_MODELO) != '-')
        self.lbl_vin_detalle_periodo.set_value("Periodo interno", v(COL_PERIODO_INTERNO))
        self.lbl_vin_detalle_periodo.setVisible(v(COL_PERIODO_INTERNO) != '-')
        self.lbl_vin_detalle_cdb.set_value("CDB", v(COL_CDB))
        self.lbl_vin_detalle_rut.set_value("RUT", v(COL_RUT))

    def _crear_celda_ficha(self, etiqueta, valor, al_hacer_clic=None):
        """Celda de la ficha: etiqueta pequeña sobre el valor. Con
        `al_hacer_clic` el valor es un enlace."""
        celda = QWidget()
        celda.setObjectName("celdaInfo")
        celda.setStyleSheet(f"QWidget#celdaInfo {{ border-bottom: 1px solid {BORDER}; }}")
        lay = QVBoxLayout(celda)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)
        lbl_label = QLabel(etiqueta)
        lbl_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; border: none; background: transparent;")
        lay.addWidget(lbl_label)
        if al_hacer_clic is not None and valor != '-':
            lbl_valor = _EnlaceLabel(valor)
            lbl_valor.clicked.connect(al_hacer_clic)
        else:
            lbl_valor = QLabel(valor)
            lbl_valor.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;")
        lbl_valor.setWordWrap(True)
        lbl_valor.setMinimumWidth(0)
        lay.addWidget(lbl_valor)
        return celda

    def _contactar_para_ofrecer_vc(self):
        vin = getattr(self, '_vin_seleccionado', None)
        if not vin:
            return
        from src.ui.mail_dialog import MailDialog
        MailDialog(self, vins_preseleccionados=[vin]).exec()

    def _crear_fila_ficha(self, etiqueta, valor, al_hacer_clic=None):
        """Fila de una tarjeta de la ficha: etiqueta a la izquierda y valor a la derecha."""
        fila = QWidget()
        fila.setObjectName("filaFicha")
        fila.setStyleSheet(f"QWidget#filaFicha {{ border-bottom: 1px dashed {BORDER}; }}")
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(12)
        lbl_e = QLabel(etiqueta)
        lbl_e.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; border: none; background: transparent;")
        if al_hacer_clic is None and etiqueta.startswith("CDB") and valor and valor != '-':
            lbl_v = CopyableValueLabel(
                valor, valor, f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;")
        elif al_hacer_clic is not None:
            lbl_v = _EnlaceLabel(valor)
            lbl_v.clicked.connect(al_hacer_clic)
        else:
            lbl_v = QLabel(valor)
            lbl_v.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;")
        lbl_v.setWordWrap(True)
        lbl_v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_v.setMinimumWidth(0)
        lay.addWidget(lbl_e, 0)
        lay.addWidget(lbl_v, 1)
        return fila

    def _render_ficha_vin(self, fila):
        v = lambda col: self._valor_ficha(fila, col)
        razon, cdb, flota = v(COL_RAZON_SOCIAL), v(COL_CDB), v(COL_FLOTA_VC)
        sin_vc = not _flota_valida(flota)
        estado_act = v(COL_ESTADO_ACTIVACION)

        # Portada: estado de Volvo Connect
        if sin_vc:
            self._ficha_hero_icono.setPixmap(ThemeManager.icon_pixmap('fa5s.unlink', color='white', size=18))
            self._ficha_hero_titulo.setText("Sin Volvo Connect")
            self._ficha_hero_sub.setText("No aparece en ninguna flota")
        else:
            self._ficha_hero_icono.setPixmap(ThemeManager.icon_pixmap('fa5s.wifi', color='white', size=18))
            self._ficha_hero_titulo.setText(f"Volvo Connect · {estado_act.capitalize()}" if estado_act != '-' else "Volvo Connect")
            self._ficha_hero_sub.setText(flota)
        self._ficha_cta.setVisible(sin_vc)

        # Alerta: un contrato Vigente no puede estar desconectado (error de datos a corregir)
        urgente = v(COL_ESTADO_COMERCIAL).upper() == 'VIGENTE' and estado_act.upper() == 'DESCONECTADO'
        self._ficha_alerta.setText("ARREGLO URGENTE · Vigente pero desconectado" if urgente else "")
        self._ficha_alerta.setVisible(urgente)

        # Vigencia del contrato (solo si tiene fechas o baja)
        while self._ficha_contrato_holder.count():
            item = self._ficha_contrato_holder.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        tarjeta_vigencia = self._crear_tarjeta_contrato(
            v(COL_INICIO_CONTRATO), v(COL_TERMINO_CONTRATO),
            v(COL_FORMA_CONTRATO), v(COL_TIPO_SERVICIO), v(COL_TIPO_FACTURACION),
            estados=(("Estado comercial", v(COL_ESTADO_COMERCIAL)), ("Estado activación", estado_act),
                     ("Etapa gestión", v(COL_ETAPA_GESTION))),
            baja=v(COL_FECHA_BAJA), solo_vigencia=True)
        if tarjeta_vigencia is not None:
            self._ficha_contrato_holder.addWidget(tarjeta_vigencia)

        def o_guion(valor, texto):
            return valor if valor != '-' else texto

        # (etiqueta, valor, acción al hacer clic); los "-" no se muestran salvo los estados clave
        tarjetas = {
            "Cliente": [
                ("Razón social", razon, lambda: self._abrir_cliente_desde_unidad(razon, v(COL_RUT))),
                ("Industria", v(COL_INDUSTRIA), None), ("Ejecutivo", v(COL_EJECUTIVO), None), ("RUT", v(COL_RUT), None),
                ("CDB comercial", cdb, None), ("CDB flota", v(COL_CDB_FLOTA), None),
            ],
            "Situación de la unidad": [
                ("N° Contrato", v(COL_ID), None),
                ("Estado comercial", o_guion(v(COL_ESTADO_COMERCIAL), "Sin definir"), None),
                ("Estado de activación", o_guion(estado_act, "Sin definir"), None),
                ("Forma de contrato", o_guion(v(COL_FORMA_CONTRATO), "Sin definir"), None),
                ("Tipo de facturación", o_guion(v(COL_TIPO_FACTURACION), "Sin registro"), None),
                ("Tipo de servicio", v(COL_TIPO_SERVICIO), None),
            ],
            "Unidad": [
                ("Estado de entrega", v(COL_ESTADO_ENTREGA), None),
                ("Duración (meses)", v(COL_DURACION_MESES), None),
                ("Flota VC", flota, lambda: self._abrir_flota_desde_unidad(cdb, flota, razon, v(COL_RUT))),
                ("Flota VC 2", v(COL_FLOTA_VC_2), None),
            ],
        }
        opcionales = [
            ("Fecha de baja", COL_FECHA_BAJA), ("Contrato en JustTime", COL_CONTRATO_JUSTTIME),
            ("Inicio facturación", COL_FECHA_INICIO_FACT), ("Término facturación", COL_FECHA_TERMINO_FACT),
            ("N° Contrato 3PC", "N CONTRATO 3PC"), ("Pago CM", "PAGO CM"), ("Tipo de CM", "TIPO DE CM"),
            ("Estado del CM", COL_ESTADO_CM), ("Fecha inicio CM", "FECHA INICIO CM"),
            ("Fecha término CM", "FECHA TERMINO CM"), ("Observaciones", "OBSERVACIONES"),
        ]
        baja_en_tarjeta = _calcular_vigencia(v(COL_INICIO_CONTRATO), v(COL_TERMINO_CONTRATO), baja=v(COL_FECHA_BAJA))['baja']
        tarjetas["Facturación y CM"] = [(et, v(col), None) for et, col in opcionales
                                        if not (col == COL_FECHA_BAJA and baja_en_tarjeta)]

        for titulo, celdas in tarjetas.items():
            filas = self._ficha_vin_layouts[titulo]
            while filas.count():
                item = filas.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()
            visibles = [c for c in celdas if c[1] != '-' or c[0] == "Razón social"]
            self._ficha_vin_cards[titulo].setVisible(bool(visibles))
            for etiqueta, valor, accion in visibles:
                filas.addWidget(self._crear_fila_ficha(etiqueta, valor, accion if valor != '-' else None))

    def _crear_tarjeta_contrato(self, inicio, termino, forma, servicio, facturacion, estados=(), baja=None, solo_vigencia=False):
        """Tarjeta de vigencia del contrato: fechas, barra de avance y
        leyenda (rojo si venció), con forma de contrato, servicio y
        facturación al pie."""
        estados_dict = {k: str(v).strip().upper() for k, v in estados}
        finalizado = (estados_dict.get("Estado comercial") in ('BAJA', 'BAJA SOLICITADA')
                      and estados_dict.get("Estado activación") == 'DESCONECTADO')
        vig = _calcular_vigencia(inicio, termino, baja=baja, finalizado=finalizado)
        color = {'vencido': DANGER, 'vigente': SUCCESS, 'baja': DANGER, 'baja_prog': WARNING}.get(vig['estado'], TEXT_SECONDARY)

        sin_fechas = str(inicio).strip() in ('-', '') and str(termino).strip() in ('-', '') and not vig['baja']
        if solo_vigencia and sin_fechas:
            return None

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaContratoVin")
        tarjeta.setStyleSheet(f"QFrame#tarjetaContratoVin {{ background-color: #F7F9FC; border: 1px solid {BORDER}; border-radius: 14px; }}"
                              "QFrame#tarjetaContratoVin QLabel { border: none; background: transparent; }")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(14, 10, 14, 0)
        lay.setSpacing(6)

        fechas = QHBoxLayout()
        columnas_fecha = [("Inicio", vig['inicio'], Qt.AlignmentFlag.AlignLeft, False)]
        if vig['baja']:
            columnas_fecha.append(("Baja", vig['baja'], Qt.AlignmentFlag.AlignHCenter, True))
        columnas_fecha.append(("Término", vig['termino'], Qt.AlignmentFlag.AlignRight, not vig['baja']))
        for etiqueta, valor, alinear, destacar in columnas_fecha:
            col = QVBoxLayout()
            col.setSpacing(0)
            lbl_e = QLabel(etiqueta)
            lbl_e.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
            lbl_v = QLabel(valor)
            lbl_v.setStyleSheet(f"color: {color if destacar and vig['estado'] in ('vencido', 'baja', 'baja_prog') else TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
            col.addWidget(lbl_e, 0, alinear)
            col.addWidget(lbl_v, 0, alinear)
            fechas.addLayout(col)
            if etiqueta != "Término":
                fechas.addStretch()
        if not sin_fechas:
            lay.addLayout(fechas)

        if vig['progreso'] is not None and not sin_fechas:
            barra = QProgressBar()
            barra.setRange(0, 100)
            barra.setValue(vig['progreso'])
            barra.setTextVisible(False)
            barra.setFixedHeight(8)
            barra.setStyleSheet(f"QProgressBar {{ background-color: {BORDER}; border: none; border-radius: 4px; }}"
                                f"QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}")
            lay.addWidget(barra)
        if vig['texto'] and not sin_fechas:
            lbl_estado = QLabel(vig['texto'])
            lbl_estado.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
            lay.addWidget(lbl_estado)

        if solo_vigencia:
            lay.setContentsMargins(14, 10, 14, 12)
            return tarjeta

        pie = QFrame()
        pie.setStyleSheet("QFrame { background: transparent; border: none; }" if sin_fechas else
                          f"QFrame {{ background: transparent; border: none; border-top: 1px solid {BORDER}; }}")
        pie_lay = QGridLayout(pie)
        pie_lay.setContentsMargins(0, 0, 0, 0)
        pie_lay.setHorizontalSpacing(0)
        pie_lay.setVerticalSpacing(0)
        celdas_pie = [("Contrato", forma), ("Servicio", servicio), ("Facturación", facturacion)] + list(estados)
        for i, (etiqueta, valor) in enumerate(celdas_pie):
            col = QVBoxLayout()
            col.setContentsMargins(14, 7, 8, 7)
            col.setSpacing(0)
            lbl_e = QLabel(etiqueta.upper())
            lbl_e.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9px; font-weight: bold; letter-spacing: 1px; border: none;")
            lbl_v = QLabel(valor)
            lbl_v.setWordWrap(True)
            lbl_v.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none;")
            col.addWidget(lbl_e)
            col.addWidget(lbl_v)
            pie_lay.addLayout(col, i // 3, i % 3)
        for c in range(3):
            pie_lay.setColumnStretch(c, 1)
        lay.addSpacing(2)
        lay.addWidget(pie)
        lay.setContentsMargins(14, 10, 14, 4)
        return tarjeta

    def _render_historial_vin(self, df_eventos):
        layout = self.historial_vin_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if df_eventos.empty:
            lbl_vacio = QLabel("No hay eventos de historial registrados para este VIN.")
            lbl_vacio.setWordWrap(True)
            lbl_vacio.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 8px 0;")
            layout.addWidget(lbl_vacio)
        else:
            for _, evento in df_eventos.iterrows():
                layout.addWidget(self._create_evento_historial_card(evento))

        layout.addStretch()

    @staticmethod
    def _filtrar_historial_por_vin(df_logs, vin):
        """LogApp.csv (self.data_manager.get_logs_df(), ver
        config.settings.LOG_CSV_PATH) filtrado por la columna identificadora
        == VIN, más reciente primero. Misma fuente que ya usa HistorialModule
        (src/ui/historial.py) -- no crea ninguna fuente de historial nueva
        ni toca excel_writer.py.

        La columna identificadora se llama 'IDENTIFICADOR' en cualquier
        LogApp.csv creado desde cero (ver _HEADER_LOG_DEFAULT en
        excel_writer.py), pero en instalaciones migradas desde el LogApp.xlsx
        legado se llama literalmente 'VIN': migrar_historial_legacy() copia
        el encabezado ORIGINAL del archivo legado tal cual venía (no lo
        normaliza a 'IDENTIFICADOR'), así que en producción esa columna
        puede tener cualquiera de los dos nombres. Bug reportado 15-09-2026:
        con un LogApp.csv migrado (columna 'VIN'), este filtro buscaba solo
        'IDENTIFICADOR' y nunca encontraba nada -- por eso historial.py
        (que no depende del nombre exacto de la columna) sí mostraba los
        cambios y el historial por VIN de esta pantalla no. Función pura (no
        usa self.*)."""
        vacio = pd.DataFrame(columns=COLUMNAS_HISTORIAL)
        if df_logs is None or df_logs.empty or not vin:
            return vacio

        columna_id = 'IDENTIFICADOR' if 'IDENTIFICADOR' in df_logs.columns else (
            'VIN' if 'VIN' in df_logs.columns else None)
        if columna_id is None:
            return vacio

        vin_str = str(vin).strip().upper()
        df_f = df_logs[df_logs[columna_id].astype(str).str.strip().str.upper() == vin_str].copy()
        if df_f.empty:
            return df_f

        if 'FECHA Y HORA' in df_f.columns:
            df_f['_fecha_parsed'] = pd.to_datetime(df_f['FECHA Y HORA'], format='mixed', dayfirst=True, errors='coerce')
            df_f = df_f.sort_values('_fecha_parsed', ascending=False, na_position='last').drop(columns=['_fecha_parsed'])

        return df_f.reset_index(drop=True)

    def _foto_caja_derecha(self):
        if not self.right_stack.isVisible() or self.right_stack.width() < 50:
            return None
        foto = QPixmap(self.right_stack.size())
        foto.fill(Qt.GlobalColor.transparent)
        self.right_stack.render(foto)
        return foto

    def _animar_caja_derecha(self, foto):
        if foto is None:
            return
        if getattr(self, '_transicion_derecha', None) is None:
            transicion = TransicionFundidoSubida(self.right_stack.parentWidget(), self.right_stack)
            transicion.DESPLAZAMIENTO_PX = 8
            transicion._anim.setDuration(170)
            self._transicion_derecha = transicion
        self.right_stack.parentWidget().layout().activate()
        self._transicion_derecha.iniciar(foto)

    @_con_transicion_derecha
    def _show_vin_vacio(self):
        if self.left_stack.currentIndex() == 1:
            self.right_stack.setCurrentIndex(3)

    @_con_transicion_derecha
    def _show_vin_detalle(self, vin):
        """VIN seleccionado -> fila completa (33 columnas) desde
        df_comercial_raw -> repuebla ficha + historial. Único punto de
        entrada para ambos paneles: así quedan siempre sincronizados con el
        mismo VIN (ver _vin_seleccionado)."""
        fila = None
        if COL_VIN in self.df_comercial_raw.columns:
            coincidencias = self.df_comercial_raw[
                self.df_comercial_raw[COL_VIN].astype(str).str.strip().str.upper() == str(vin).strip().upper()
            ]
            if not coincidencias.empty:
                fila = coincidencias.iloc[0]

        if fila is None:
            # El VIN seleccionado ya no existe en los datos actuales (ej.
            # tras un refresh que lo eliminó): se limpia la selección en vez
            # de mostrar una ficha con datos viejos/inconsistentes.
            self._vin_seleccionado = None
            self._show_vin_vacio()
            return

        self.lbl_vin_detalle_title.set_value("VIN", vin)
        self._fila_vin_actual = fila
        self._contrato_anterior_mostrado = False
        self._ficha_aviso_anterior.hide()
        self._render_cabecera_vin(fila)
        self._render_ficha_vin(fila)
        df_logs = self.data_manager.get_logs_df()
        self._render_historial_vin(self._filtrar_historial_por_vin(df_logs, vin))
        self._render_contratos_anteriores(self._obtener_contratos_anteriores(vin))

        if self.left_stack.currentIndex() == 1:
            self.right_stack.setCurrentIndex(4)
            self._switch_vin_detalle_view(0)  # siempre inicia en Ficha al elegir un VIN nuevo

    def _build_cliente_detalle_view(self):
        widget = QWidget()
        raiz = QVBoxLayout(widget)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        hoja = QFrame()
        hoja.setObjectName("hojaCliente")
        hoja.setStyleSheet(f"QFrame#hojaCliente {{ background-color: {SURFACE}; border: none; border-radius: 16px; }}")
        lay_hoja = QVBoxLayout(hoja)
        lay_hoja.setContentsMargins(0, 0, 0, 0)
        lay_hoja.setSpacing(0)

        portada = QFrame()
        portada.setObjectName("fichaPortada")
        portada.setStyleSheet(
            f"QFrame#fichaPortada {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {AZUL_HOVER}, stop:1 {AZUL}); "
            "border-top-left-radius: 16px; border-top-right-radius: 16px; border-bottom-left-radius: 0; border-bottom-right-radius: 0; }"
            "QFrame#fichaPortada QLabel { background: transparent; border: none; }")
        layout = QVBoxLayout(portada)
        layout.setContentsMargins(10, 16, 10, 0)
        layout.setSpacing(6)

        icono = QLabel()
        icono.setFixedSize(46, 46)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.building', color='white', size=20))
        icono.setStyleSheet("background: rgba(255,255,255,0.12); border: 2px solid rgba(255,255,255,0.45); border-radius: 23px;")
        layout.addWidget(icono, 0, Qt.AlignmentFlag.AlignHCenter)

        self.lbl_detalle_title = CopyableTitulo("")
        self.lbl_detalle_title.setWordWrap(True)
        self.lbl_detalle_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_detalle_title)

        # Industria / RUT / CDB como chips copiables
        subtitle_row = QHBoxLayout()
        subtitle_row.setSpacing(6)
        self.lbl_detalle_industria = CopyableLabel()
        self.lbl_detalle_rut = CopyableLabel()
        self.lbl_detalle_cdb = CopyableLabel()
        self.lbl_detalle_cdb_flota = CopyableLabel()
        for chip in (self.lbl_detalle_industria, self.lbl_detalle_rut, self.lbl_detalle_cdb, self.lbl_detalle_cdb_flota):
            chip._BASE_STYLE = (f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; padding: 3px 10px; "
                                "border: 1px solid rgba(255,255,255,0.28); border-radius: 9px; background-color: rgba(255,255,255,0.08);")
            chip._HOVER_STYLE = (f"color: {AZUL}; font-size: 11px; padding: 3px 10px; "
                                 "border: 1px solid white; border-radius: 9px; background-color: white;")
            chip.setStyleSheet(chip._BASE_STYLE)
            if chip is not self.lbl_detalle_industria:
                subtitle_row.addWidget(chip)
        subtitle_row.insertStretch(0)
        subtitle_row.addStretch()
        layout.addLayout(subtitle_row)

        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(8)
        card, self.lbl_kpi_unidades = self._crear_kpi_comercial("UNIDADES", "0", "en total")
        kpi_layout.addWidget(card)
        card, self.lbl_kpi_connect = self._crear_kpi_comercial("VOLVO CONNECT", "0", "")
        kpi_layout.addWidget(card)
        card, self.lbl_kpi_civ = self._crear_kpi_comercial("CIV", "0", "")
        kpi_layout.addWidget(card)
        card, self.lbl_kpi_safety = self._crear_kpi_comercial("SAFETY ZONE", "0", "")
        kpi_layout.addWidget(card)
        layout.addLayout(kpi_layout)

        detalle_nav_barra = QFrame()
        detalle_nav_barra.setObjectName("barraPestanasGeneral")
        detalle_nav_barra.setStyleSheet(QSS_CONTENEDOR_PESTANAS_CLARO)
        detalle_nav_layout = QHBoxLayout(detalle_nav_barra)
        detalle_nav_layout.setContentsMargins(0, 0, 0, 0)
        detalle_nav_layout.setSpacing(2)
        detalle_nav_layout.addStretch()
        self.btn_detalle_resumen = QPushButton("Resumen")
        self.btn_detalle_unidades = QPushButton("Unidades")
        self.btn_detalle_flotas = QPushButton("Flotas VC")
        self.btn_detalle_contactos = QPushButton("Contactos")
        # "Historial" quitado de este detalle (Cliente y Flota comparten esta
        # misma vista, ver _show_cliente_detalle) a pedido explícito
        # (15-09-2026): el historial por VIN de Unidades (caja derecha ->
        # Unidades -> Historial, _build_historial_vin_view) NO se toca.
        # "Duplicados" (23-09-2026, a pedido explícito): solo visible cuando
        # el cliente seleccionado comparte RUT+CDB con otra Razón Social (ver
        # _populate_duplicados_detalle) -- oculto por defecto, igual criterio
        # que btn_filtro_unidades para pestañas condicionales. Icono en vez de
        # emoji en el texto (mismo patrón que el resto de botones de este
        # archivo): un caracter Unicode crudo en un QPushButton.text() rompe
        # la consola de Windows (cp1252) si algún test llega a imprimirlo en
        # un mensaje de fallo -- confirmado con un UnicodeEncodeError real al
        # correr la suite completa.
        self.btn_detalle_duplicados = QPushButton("Razones")
        self.btn_detalle_duplicados.setVisible(False)
        self._detalle_nav_buttons = [self.btn_detalle_resumen, self.btn_detalle_unidades,
                                      self.btn_detalle_flotas, self.btn_detalle_contactos,
                                      self.btn_detalle_duplicados]
        # Mismo estilo tipo pestaña que el grupo Cliente/Flota/Unidades de arriba.
        detalle_tab_style = QSS_PESTANAS_CLARAS
        for i, btn in enumerate(self._detalle_nav_buttons):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(detalle_tab_style)
            btn.clicked.connect(lambda checked, idx=i: self._switch_detalle_view(idx))
            detalle_nav_layout.addWidget(btn)
        detalle_nav_layout.addStretch()
        self.btn_detalle_resumen.setChecked(True)
        layout.addSpacing(2)
        layout.addWidget(detalle_nav_barra)
        lay_hoja.addWidget(portada)

        self.detalle_stack = QStackedWidget()
        self.detalle_stack.setContentsMargins(14, 12, 14, 14)
        self.detalle_stack.addWidget(self._build_detalle_resumen_view())
        self.detalle_stack.addWidget(self._build_detalle_unidades_view())
        self.detalle_stack.addWidget(self._build_detalle_flotas_view())
        self.detalle_stack.addWidget(self._build_detalle_contactos_view())
        self.detalle_stack.addWidget(self._build_detalle_duplicados_view())

        # Scroll acotado únicamente al contenido de la pestaña activa
        # (Resumen/Unidades/Contactos/Historial): todo lo de arriba (título,
        # Industria/RUT/CDB, KPIs, y las propias pestañas
        # Resumen/Unidades/Contactos/Historial) queda fuera de este
        # QScrollArea y por lo tanto fijo mientras se hace scroll acá abajo.
        # Mismo estilo/transparencia que usaba antes el scroll que envolvía
        # toda la caja derecha (ver comentario histórico en _setup_right_box).
        self.detalle_scroll = QScrollArea()
        self.detalle_scroll.setWidgetResizable(True)
        self.detalle_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detalle_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.detalle_scroll.viewport().setStyleSheet("background: transparent;")
        self.detalle_scroll.setWidget(self.detalle_stack)
        self.detalle_stack.setStyleSheet("background: transparent;")

        lay_hoja.addWidget(self.detalle_scroll, stretch=1)
        raiz.addWidget(hoja, 1)

        return widget

    def _crear_kpi_comercial(self, titulo, valor, pie):
        """Tarjeta KPI con el diseño de Comercial: título, número grande y,
        abajo, la píldora con el % más una línea de apoyo. Devuelve
        (tarjeta, etiqueta del número); la tarjeta queda en etiqueta._tarjeta."""
        from src.ui.comercial_estilo import TarjetaKpiResumen
        tarjeta = TarjetaKpiResumen()
        tarjeta.setFixedHeight(88)
        tarjeta.setCheckable(False)
        tarjeta.setCursor(Qt.CursorShape.ArrowCursor)
        tarjeta.layout().setContentsMargins(12, 8, 4, 8)
        tarjeta.definir(titulo.capitalize(), AZUL)
        tarjeta._lbl_titulo.setWordWrap(False)
        tarjeta._lbl_titulo.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 500; background: transparent; border: none;")
        tarjeta._lbl_valor.setStyleSheet(
            f"color: {AZUL}; font-size: 24px; font-weight: 800; background: transparent; border: none;")
        tarjeta.actualizar(valor, None, pie)
        tarjeta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        tarjeta._lbl_valor._tarjeta = tarjeta
        return tarjeta, tarjeta._lbl_valor

    def _build_detalle_resumen_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # --- Caja 1: Información del cliente ---
        info_frame = QFrame()
        ThemeManager.apply_card_style(info_frame)
        _tarjeta_blanca(info_frame)
        info_outer_layout = QVBoxLayout(info_frame)
        info_outer_layout.setContentsMargins(10, 8, 10, 10)
        info_outer_layout.setSpacing(4)

        info_header_row = QHBoxLayout()
        lbl_info_title = QLabel("INFORMACIÓN DEL CLIENTE")
        lbl_info_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        info_header_row.addWidget(lbl_info_title)
        info_header_row.addStretch()
        info_outer_layout.addLayout(info_header_row)

        self.info_cliente_layout = QGridLayout()
        self.info_cliente_layout.setHorizontalSpacing(24)
        self.info_cliente_layout.setVerticalSpacing(0)
        self.info_cliente_layout.setColumnStretch(0, 1)
        self.info_cliente_layout.setColumnStretch(1, 1)
        info_outer_layout.addLayout(self.info_cliente_layout)
        layout.addWidget(info_frame)

        # --- Caja 2: Contactos encontrados (cruce por CDB con el módulo Contactos) ---
        contactos_frame = QFrame()
        ThemeManager.apply_card_style(contactos_frame)
        _tarjeta_blanca(contactos_frame)
        contactos_outer_layout = QVBoxLayout(contactos_frame)
        contactos_outer_layout.setContentsMargins(10, 8, 10, 10)
        contactos_outer_layout.setSpacing(6)

        contactos_header_row = QHBoxLayout()
        lbl_contactos_title = QLabel("CONTACTOS")
        lbl_contactos_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        contactos_header_row.addWidget(lbl_contactos_title)
        contactos_header_row.addStretch()
        contactos_header_row.setSpacing(6)
        self.btn_agregar_admin_resumen = self._crear_boton_circular('fa5s.plus', "Agregar administrador de flota")
        self.btn_agregar_admin_resumen.clicked.connect(self._handle_agregar_contacto)
        self.btn_agregar_admin_resumen.hide()
        self.lbl_ver_todos_contactos = self._crear_boton_circular('fa5s.arrow-right', "Ver todos")
        self.lbl_ver_todos_contactos.clicked.connect(lambda: self._switch_detalle_view(3))
        contactos_header_row.addWidget(self.btn_agregar_admin_resumen)
        contactos_header_row.addWidget(self.lbl_ver_todos_contactos)
        contactos_outer_layout.addLayout(contactos_header_row)

        fila_conteos = QHBoxLayout()
        fila_conteos.setSpacing(8)
        self._btn_conteo_directores = btn_dir = self._crear_conteo_contactos("Directores", "fa5s.crown", "#D4AF37")
        self._btn_conteo_administradores = btn_adm = self._crear_conteo_contactos("Administradores", "fa5s.user-tie", VOLVO_BLUE)
        fila_conteos.addWidget(btn_dir)
        fila_conteos.addWidget(btn_adm)
        contactos_outer_layout.addLayout(fila_conteos)

        # Sin borde/fondo propio en el QScrollArea ni en su viewport interno
        # (por defecto Qt pinta el viewport con Base del palette, lo que se
        # veía como un recuadro gris "cuadrado" encima del fondo blanco de la
        # tarjeta). Altura mínima en vez de fija + stretch=1 en el layout de
        # abajo: así esta tarjeta crece para ocupar el espacio disponible de
        # la caja derecha en vez de quedar apretada arriba con hueco vacío.
        self.contactos_encontrados_scroll = QScrollArea()
        self.contactos_encontrados_scroll.setWidgetResizable(True)
        self.contactos_encontrados_scroll.setMinimumHeight(90)
        self.contactos_encontrados_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.contactos_encontrados_scroll.viewport().setStyleSheet("background: transparent;")
        self.contactos_encontrados_container = QWidget()
        self.contactos_encontrados_container.setStyleSheet("background: transparent;")
        self.contactos_encontrados_layout = QVBoxLayout(self.contactos_encontrados_container)
        self.contactos_encontrados_layout.setContentsMargins(0, 2, 0, 2)
        self.contactos_encontrados_layout.setSpacing(4)
        self.contactos_encontrados_scroll.setWidget(self.contactos_encontrados_container)
        self.contactos_encontrados_scroll.hide()
        contactos_outer_layout.addWidget(self.contactos_encontrados_scroll)

        layout.addWidget(contactos_frame)
        layout.addStretch()

        # --- Caja 3: preparada, sin contenido todavía (a pedido explícito) ---
        self.tercera_caja_resumen = QFrame()
        ThemeManager.apply_card_style(self.tercera_caja_resumen)
        QVBoxLayout(self.tercera_caja_resumen).setContentsMargins(10, 10, 10, 10)
        self.tercera_caja_resumen.hide()
        layout.addWidget(self.tercera_caja_resumen)

        return widget

    def _crear_boton_circular(self, icono, tooltip):
        """Botón redondo azul Volvo con ícono blanco."""
        btn = QPushButton()
        btn.setFixedSize(26, 26)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setIcon(QIcon(ThemeManager.icon_pixmap(icono, color="white", size=12)))
        btn.setIconSize(QSize(12, 12))
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {AZUL}; border: none; border-radius: 13px; }}"
            f"QPushButton:hover {{ background-color: {AZUL_HOVER}; }}")
        return btn

    def _crear_conteo_contactos(self, titulo, icono, color):
        """Botón-tarjeta con un conteo de contactos; al hacer clic abre la pestaña Contactos."""
        btn = QPushButton()
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(56)
        btn.setObjectName("conteoContactos")
        btn.setStyleSheet(
            f"QPushButton#conteoContactos {{ background-color: #F3F5F9; border: 1px solid {BORDER}; border-radius: 12px; }}"
            f"QPushButton#conteoContactos:hover {{ background-color: {TINTE_CLARO}; border: 1px solid {LINEA_AZUL}; }}")
        btn.setToolTip("Abrir la pestaña Contactos")
        btn.clicked.connect(lambda: self._switch_detalle_view(3))
        lay = QHBoxLayout(btn)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)
        ico = QLabel()
        ico.setFixedSize(34, 34)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setPixmap(ThemeManager.icon_pixmap(icono, color='white', size=15))
        ico.setStyleSheet(f"background-color: {color}; border-radius: 17px;")
        textos = QVBoxLayout()
        textos.setSpacing(0)
        valor = QLabel("0")
        valor.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: bold; background: transparent; border: none;")
        etiqueta = QLabel(titulo)
        etiqueta.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;")
        textos.addWidget(valor)
        textos.addWidget(etiqueta)
        lay.addWidget(ico)
        lay.addLayout(textos, 1)
        for w in (ico, valor, etiqueta):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn._valor, btn._ico, btn._color = valor, ico, color
        return btn

    def _fijar_conteo_contactos(self, btn, n):
        activo = n > 0
        btn._valor.setText(str(n))
        gris = '#9AA3B5'
        btn._valor.setStyleSheet(f"color: {TEXT_PRIMARY if activo else gris}; font-size: 18px; font-weight: bold; background: transparent; border: none;")
        btn._ico.setStyleSheet(f"background-color: {btn._color if activo else '#C5CCDA'}; border-radius: 17px;")

    def _render_info_cliente(self, razon_social, rut, cdb, industria, ejecutivo, total_unidades, flotas_txt, direccion="", comuna=""):
        while self.info_cliente_layout.count():
            item = self.info_cliente_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # RUT, CDB e Industria ya se ven como chips en la cabecera del detalle.
        # (etiqueta, valor, copiable, ancho completo)
        celdas = []
        if ejecutivo:
            celdas.append(("Ejecutivo", ejecutivo, False, False))
        if industria and str(industria).strip() not in ('', '-', 'nan'):
            celdas.append(("Industria", str(industria), False, False))
        celdas.append(("Total de unidades", str(total_unidades), False, False))
        # Dirección/Comuna: BBDD CLIENTES CM.xlsx (Power BI), mismo cruce por
        # CDB que ya usa _create_director_empresa_card para correo/teléfono
        # (ver _show_cliente_detalle). Solo se agregan si llegó el dato --
        # puede no haber llegado aún (carga async) o no existir para ese CDB.
        if direccion:
            celdas.append(("Dirección", direccion, True, False))
        if comuna:
            celdas.append(("Comuna", comuna, True, False))
        celdas.append(("Flota(s)", flotas_txt, False, True))

        # Dirección y Comuna se copian juntas, sea cual sea la que se pulse
        direccion_y_comuna = ", ".join(t for t in (direccion, comuna) if t)
        fila, columna = 0, 0
        for label, value, copyable, ancho_completo in celdas:
            es_ubicacion = label in ("Dirección", "Comuna")
            celda = self._create_info_celda(
                label, value, copyable,
                tooltip=(getattr(self, '_info_cliente_flotas_tooltip', '') if label == "Flota(s)"
                         else (f"Clic para copiar dirección y comuna:\n{direccion_y_comuna}" if es_ubicacion else str(value))),
                elidir=True, copiar_texto=direccion_y_comuna if es_ubicacion else None)
            if ancho_completo:
                if columna:
                    fila, columna = fila + 1, 0
                self.info_cliente_layout.addWidget(celda, fila, 0, 1, 2)
                fila += 1
            else:
                self.info_cliente_layout.addWidget(celda, fila, columna)
                columna += 1
                if columna == 2:
                    fila, columna = fila + 1, 0

    def _create_info_celda(self, label, value, copyable=False, tooltip="", elidir=False, copiar_texto=None):
        """Celda de "Información del cliente": etiqueta pequeña sobre el valor.
        Con `elidir` el valor va en una línea y se corta con "…" si no cabe."""
        celda = QWidget()
        celda.setStyleSheet(f"QWidget#celdaInfo {{ border-bottom: 1px solid {BORDER}; }}")
        celda.setObjectName("celdaInfo")
        lay = QVBoxLayout(celda)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(1)
        lbl_label = QLabel(label)
        lbl_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; border: none; background: transparent;")
        base_style = f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;"
        if elidir and copiar_texto:
            lbl_value = _EtiquetaElididaCopiable(value, copiar_texto, base_style)
        elif elidir:
            lbl_value = _EtiquetaElidida(value)
            lbl_value.setStyleSheet(base_style)
            if tooltip:
                lbl_value.setToolTip(tooltip)
        else:
            if copyable and value and value != "N/A":
                lbl_value = CopyableValueLabel(value, value, base_style)
            else:
                lbl_value = QLabel(value)
                lbl_value.setStyleSheet(base_style)
            lbl_value.setWordWrap(True)
        lay.addWidget(lbl_label)
        lay.addWidget(lbl_value)
        return celda

    def _create_contacto_card(self, nombre, apellidos, correo, telefono, contact_id=None):
        iniciales = f"{nombre[:1]}{apellidos[:1]}".upper().strip() or "?"
        avatar = QLabel(iniciales)
        avatar.setStyleSheet(f"background-color: {VOLVO_BLUE}; color: white; border-radius: 17px; font-weight: bold; font-size: 12px;")
        frame, row_layout = self._armar_tarjeta_persona(avatar, f"{nombre} {apellidos}".strip(), correo, telefono)

        # Favorito: mismo sistema de favoritos que contactos.py (archivo
        # compartido config/pinned_contacts.json, clave = ID físico del
        # contacto normalizado). Solo se muestra si el llamador identificó
        # el contacto (contact_id); las tarjetas del Director de empresa no
        # pasan contact_id porque no son un contacto individual favoriteable.
        if contact_id:
            es_favorito = contact_id in self.pinned_contacts
            btn_favorito = QPushButton()
            btn_favorito.setFlat(True)
            btn_favorito.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_favorito.setFixedSize(20, 20)
            btn_favorito.setIconSize(QSize(13, 13))
            btn_favorito.setStyleSheet("QPushButton { background: transparent; border: none; }")
            btn_favorito.setIcon(ThemeManager.icon('fa5s.star', color='#F59E0B' if es_favorito else '#D1D5DB'))
            btn_favorito.setToolTip("Quitar de favoritos" if es_favorito else "Marcar como favorito")
            btn_favorito.clicked.connect(lambda checked=False, cid=contact_id: self._toggle_favorito_contacto(cid))
            row_layout.addWidget(btn_favorito)

        return frame

    def _toggle_favorito_contacto(self, contact_id):
        """Marca/desmarca un contacto como favorito y refresca las tarjetas
        del cliente actualmente seleccionado. Mismo archivo/formato que
        contactos.py (contactos_service.cargar_favoritos/guardar_favoritos),
        así el favorito queda sincronizado entre ambos módulos."""
        if contact_id in self.pinned_contacts:
            self.pinned_contacts.remove(contact_id)
        else:
            self.pinned_contacts.append(contact_id)
        contactos_service.guardar_favoritos(self.pinned_file, self.pinned_contacts)
        if self._selected_cdb:
            self._populate_contactos_encontrados(self._selected_cdb)

    def _create_director_empresa_card(self, correo, telefono):
        """Tarjeta del "Director de empresas" en BBDD CLIENTES CM.xlsx
        (Power BI) -- dato de la EMPRESA (un solo registro por CDB), distinto
        de las tarjetas de contactos individuales de contactos.xlsx que arma
        _create_contacto_card. Mismo layout/estilo que esas tarjetas (a
        pedido explícito), salvo el avatar (corona dorada en vez de
        iniciales) y que correo/teléfono son CopyableLabel (clic para
        copiar). Solo se llama cuando hay correo y/o teléfono (ver
        _populate_contact_cards)."""
        DORADO = "#D4AF37"
        avatar = QLabel()
        avatar.setStyleSheet(f"background-color: {DORADO}; border-radius: 17px;")
        avatar.setPixmap(ThemeManager.icon_pixmap('fa5s.crown', color='white', size=14))
        frame, _ = self._armar_tarjeta_persona(avatar, "Director de empresa", correo, telefono, borde=DORADO)
        return frame

    def _armar_tarjeta_persona(self, avatar, nombre, correo, telefono, borde=None):
        """Tarjeta común de contactos (individuales y Director de empresa):
        avatar circular, nombre y, debajo, correo y teléfono copiables con un
        clic. Devuelve (frame, layout horizontal) para que el llamador agregue
        controles a la derecha (ej. favorito)."""
        frame = QFrame()
        frame.setObjectName("tarjetaContacto")
        frame.setStyleSheet(f"""
            QFrame#tarjetaContacto {{ background-color: {SURFACE}; border: 1px solid {borde or BORDER}; border-radius: 12px; }}
            QFrame#tarjetaContacto:hover {{ border: 1px solid {PRIMARY}; }}
            QFrame#tarjetaContacto QLabel {{ border: none; background: transparent; }}
        """)
        row_layout = QHBoxLayout(frame)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(12)

        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(avatar, 0, Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        lbl_nombre = QLabel(nombre)
        lbl_nombre.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold; font-size: 12px;")
        text_layout.addWidget(lbl_nombre)

        contacto_row = QHBoxLayout()
        contacto_row.setSpacing(4)
        for icono, valor in (('fa5s.envelope', correo), ('fa5s.phone-alt', telefono)):
            if not valor or valor in ('-', 'nan'):
                continue
            icon_lbl = QLabel()
            icon_lbl.setPixmap(ThemeManager.icon_pixmap(icono, color=TEXT_MUTED, size=10))
            lbl_valor = CopyableLabel()
            lbl_valor.setText(valor)
            lbl_valor._copy_value = valor
            contacto_row.addWidget(icon_lbl)
            contacto_row.addWidget(lbl_valor)
            contacto_row.addSpacing(10)
        if contacto_row.count() == 0:
            sin_datos = QLabel("Sin correo ni teléfono")
            sin_datos.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            contacto_row.addWidget(sin_datos)
        contacto_row.addStretch()
        text_layout.addLayout(contacto_row)
        row_layout.addLayout(text_layout, stretch=1)
        return frame, row_layout

    def _switch_detalle_view(self, index):
        for i, btn in enumerate(self._detalle_nav_buttons):
            btn.setChecked(i == index)
        self.detalle_stack.setCurrentIndex(index)

    # ==========================================
    # CAJA IZQUIERDA: navegación Cliente / Flota / Unidades
    # ==========================================
    def _setup_left_box(self):
        layout = QVBoxLayout(self.left_box)
        layout.setContentsMargins(15, 18, 15, 15)
        layout.setSpacing(2)

        lbl_titulo = QLabel("Clientes y Flota")
        lbl_titulo.setStyleSheet("color: white; font-size: 24px; font-weight: 800; background: transparent; border: none;")
        lbl_subtitulo = QLabel("Clientes, unidades y su estado en la flota.")
        lbl_subtitulo.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 13.5px; background: transparent; border: none;")
        for lbl in (lbl_titulo, lbl_subtitulo):
            lbl.setContentsMargins(16, 0, 0, 0)
            layout.addWidget(lbl)
        layout.addSpacing(8)
        self._setup_top_controls(layout)
        layout.addSpacing(10)

        self._hoja_izquierda = QFrame()
        self._hoja_izquierda.setObjectName("hojaIzquierda")
        self._hoja_izquierda.setStyleSheet(f"QFrame#hojaIzquierda {{ background-color: {SURFACE}; border: none; border-radius: 16px; }}")
        lay_hoja = QVBoxLayout(self._hoja_izquierda)
        lay_hoja.setContentsMargins(15, 15, 15, 15)
        lay_hoja.setSpacing(10)
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self._build_cliente_view())
        self.left_stack.addWidget(self._build_unidades_view())
        lay_hoja.addWidget(self.left_stack, stretch=1)
        layout.addWidget(self._hoja_izquierda, stretch=1)

    def _switch_left_view(self, index):
        cambio = self.left_stack.currentIndex() != index
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index)
        self.left_stack.setCurrentIndex(index)
        if cambio:
            self._animar_carga_breve()
        # Único botón de filtros del módulo (Razón Social/Estado Activación/
        # Industria): solo aplica a Unidades, se oculta en las demás pestañas
        # en vez de dejarlo inerte.
        self.btn_filtro_unidades.setVisible(index == 1)
        self._renderizar_pestana_si_pendiente(index)

    def _renderizar_pestana_si_pendiente(self, index):
        """Pinta las tarjetas de la pestaña recién mostrada solo si quedó
        pendiente (ver _render_clientes_cards/_render_flota_cards/
        _render_unidades_cards): mientras esa pestaña no era visible,
        filter_table()/_on_prep_finished() actualizaron el DataFrame/página
        pero no construyeron widgets. Si no hay nada pendiente, no hace
        nada -- volver a una pestaña sin cambios no debe reconstruir sus
        tarjetas (Fase 5, 21-09-2026)."""
        if index == 0 and self._clientes_pendiente_render:
            self._pintar_pagina_clientes()
            self._clientes_pendiente_render = False
            self._sincronizar_seleccion_cliente(self._df_clientes_visible)
        elif index == 1 and self._unidades_pendiente_render:
            self._pintar_pagina_unidades()
            self._unidades_pendiente_render = False
            self._sincronizar_seleccion_vin()

        if index == 1:
            # Unidades: la caja derecha pasa a mostrar el contexto de VIN
            # (ficha + historial de la unidad seleccionada, o el estado
            # vacío si todavía no se eligió ninguna).
            if self._vin_seleccionado:
                self._show_vin_detalle(self._vin_seleccionado)
            else:
                self._show_vin_vacio()
        elif self.right_stack.currentIndex() in (3, 4):
            # Se sale de Unidades y la caja derecha estaba mostrando el
            # contexto de VIN: vuelve a reflejar la última selección de
            # cliente (o el estado vacío original) en vez de dejar la ficha
            # de VIN visible fuera de su pestaña.
            cliente_row = self._buscar_cliente_por_clave(self._selected_cliente_key)
            if cliente_row is not None:
                self._show_cliente_detalle(cliente_row)
            else:
                self._show_cliente_vacio()

    # ==========================================
    # VISTA "CLIENTE": tabla resumida (sin filtros propios -- el filtro de
    # Industria que vivía acá se movió a Unidades, ver _build_unidades_view,
    # a pedido explícito 15-09-2026)
    # ==========================================
    def _build_cliente_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        pag_top, self._lbl_pagina_clientes_top, self._btn_pagina_ant_clientes_top, self._btn_pagina_sig_clientes_top = \
            self._crear_controles_paginacion(self._pagina_anterior_clientes, self._pagina_siguiente_clientes)

        pag_top.setParent(widget)
        pag_top.hide()
        top_row = QHBoxLayout()
        self.chk_solo_avisos_flota = QCheckBox("Solo con aviso de flotas")
        self.chk_solo_avisos_flota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_solo_avisos_flota.setToolTip("Muestra solo los clientes con flotas incoherentes (el ícono amarillo de la tarjeta)")
        self.chk_solo_avisos_flota.setStyleSheet(f"QCheckBox {{ color: {TEXT_SECONDARY}; font-size: 11px; font-weight: bold; spacing: 6px; }}")
        self.chk_solo_avisos_flota.toggled.connect(lambda _c: (self._animar_carga_breve(solo_izquierda=True), self.filter_clientes()))
        top_row.addWidget(self.chk_solo_avisos_flota)
        top_row.addStretch(1)
        top_row.addWidget(self._crear_selector_tamano_pagina(self._on_cambiar_tamano_pagina_clientes))
        top_row.addWidget(self._crear_boton_ordenar(self._on_cambiar_orden_clientes, self._on_cambiar_orden_clientes_unidades,
                                                    self._on_cambiar_orden_clientes_flotas))
        layout.addLayout(top_row)

        self.clientes_scroll = QScrollArea()
        self.clientes_scroll.setWidgetResizable(True)
        self.clientes_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.clientes_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.clientes_scroll.viewport().setStyleSheet("background: transparent;")

        clientes_container = QWidget()
        clientes_container.setStyleSheet(QSS_TARJETAS_CLIENTE)
        self.clientes_layout = QVBoxLayout(clientes_container)
        self.clientes_layout.setContentsMargins(2, 2, 2, 2)
        self.clientes_layout.setSpacing(8)
        self.clientes_layout.addStretch()
        self.clientes_scroll.setWidget(clientes_container)

        layout.addWidget(self.clientes_scroll, stretch=1)

        pag_bottom, self._lbl_pagina_clientes_bottom, self._btn_pagina_ant_clientes_bottom, self._btn_pagina_sig_clientes_bottom = \
            self._crear_controles_paginacion(self._pagina_anterior_clientes, self._pagina_siguiente_clientes)
        layout.addWidget(pag_bottom)

        return widget

    def _on_cambiar_orden_clientes(self, is_asc):
        self._clientes_orden_campo = 'nombre'
        self._clientes_orden_asc = is_asc
        self.filter_clientes()

    def _on_cambiar_orden_clientes_unidades(self, is_asc):
        self._clientes_orden_campo = 'unidades'
        self._clientes_orden_asc = is_asc
        self.filter_clientes()

    def _on_cambiar_orden_clientes_flotas(self, is_asc):
        self._clientes_orden_campo = 'flotas'
        self._clientes_orden_asc = is_asc
        self.filter_clientes()

    def _on_cambiar_tamano_pagina_clientes(self, nuevo_tamano):
        self._clientes_tam_pagina = nuevo_tamano
        self._clientes_pagina_actual = 0
        self._animar_carga_breve(solo_izquierda=True)
        self._pintar_pagina_clientes()

    def _render_clientes_cards(self, df_f):
        """Repuebla la lista de tarjetas de Cliente desde df_f (ya filtrado/
        ordenado/reindexado): vuelve a la página 1 y pinta solo esa página
        (ver _pintar_pagina_clientes) -- con varios miles de clientes,
        construir todas las tarjetas de golpe congelaba la app al entrar al
        módulo (reportado por el usuario, 20-09-2026).

        Si la pestaña Cliente (índice 0) no está visible, no pinta ahora --
        solo deja el DataFrame/página listos y marca _clientes_pendiente_
        render, que _switch_left_view resuelve al entrar (Fase 5,
        21-09-2026)."""
        self._clientes_df_paginado = df_f
        self._clientes_pagina_actual = 0
        if self.left_stack.currentIndex() == 0:
            self._pintar_pagina_clientes()
            self._clientes_pendiente_render = False
        else:
            self._clientes_pendiente_render = True

    def _pagina_anterior_clientes(self):
        if self._clientes_pagina_actual > 0:
            self._clientes_pagina_actual -= 1
            self._animar_carga_breve(solo_izquierda=True)
            self._pintar_pagina_clientes()

    def _pagina_siguiente_clientes(self):
        total_paginas = max(1, -(-len(self._clientes_df_paginado) // self._clientes_tam_pagina))
        if self._clientes_pagina_actual < total_paginas - 1:
            self._clientes_pagina_actual += 1
            self._animar_carga_breve(solo_izquierda=True)
            self._pintar_pagina_clientes()

    def _pintar_pagina_clientes(self):
        layout = self.clientes_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cliente_cards = {}
        self._cancelar_tandas('clientes')

        df_f = self._clientes_df_paginado
        total_paginas = max(1, -(-len(df_f) // self._clientes_tam_pagina))
        self._actualizar_controles_paginacion(
            self._clientes_pagina_actual, total_paginas,
            (self._lbl_pagina_clientes_top, self._btn_pagina_ant_clientes_top, self._btn_pagina_sig_clientes_top),
            (self._lbl_pagina_clientes_bottom, self._btn_pagina_ant_clientes_bottom, self._btn_pagina_sig_clientes_bottom),
        )

        if df_f.empty:
            lbl_vacio = QLabel("No hay clientes que coincidan con la búsqueda.")
            lbl_vacio.setWordWrap(True)
            lbl_vacio.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 12px;")
            layout.addWidget(lbl_vacio)
            layout.addStretch()
            return

        inicio = self._clientes_pagina_actual * self._clientes_tam_pagina
        fin = min(inicio + self._clientes_tam_pagina, len(df_f))

        def crear(row_idx):
            fila = df_f.iloc[row_idx]
            card = GeneralClienteCard(
                row_idx, fila.get('Razón Social', ''), fila.get('RUT', ''),
                fila.get('CDB', ''), fila.get('Industria/s', ''), fila.get('Total unidades', 0),
                duplicado=str(fila.get('Clave', '')) in self._clientes_con_varias_razones,
                total_flotas=int(fila.get('Total flotas', 0) or 0),
                aviso_flota=getattr(self, '_clientes_aviso_flota', {}).get(str(fila.get('Clave', '')), ''),
            )
            card.clicked.connect(self._on_cliente_card_clicked)
            cdb_key = self._clave_cliente(fila)
            self._cliente_cards[cdb_key] = card
            if self._selected_cliente_key and cdb_key == self._selected_cliente_key:
                card.set_selected(True)
            return card
        self._construir_tarjetas_por_tandas('clientes', layout, range(inicio, fin), crear)

    # Tarjetas por tandas: las primeras se construyen de inmediato y el resto
    # recién cuando el scroll se acerca al final, así una página de 200-1000
    # no congela la pantalla ni gasta tiempo en tarjetas que nadie mira.
    _PRIMERA_TANDA_TARJETAS = 40
    _TANDA_TARJETAS = 40

    def _cancelar_tandas(self, lista):
        generaciones = self.__dict__.setdefault('_generacion_tandas', {})
        generaciones[lista] = generaciones.get(lista, 0) + 1
        self.__dict__.setdefault('_tanda_pendiente', {}).pop(lista, None)
        return generaciones

    def _scroll_de_lista(self, lista):
        return {'clientes': 'clientes_scroll', 'unidades': 'unidades_scroll'}.get(lista)

    def _construir_tarjetas_por_tandas(self, lista, layout, indices, crear):
        generaciones = self._cancelar_tandas(lista)
        generacion = generaciones[lista]
        pendientes = self.__dict__['_tanda_pendiente']
        indices = list(indices)

        def tanda(desde, cantidad):
            # Otra página/búsqueda empezó a pintar esta lista: se abandona
            if generaciones.get(lista) != generacion:
                return
            pendientes.pop(lista, None)
            try:
                hasta = min(desde + cantidad, len(indices))
                for i in indices[desde:hasta]:
                    layout.addWidget(crear(i))
                if hasta < len(indices):
                    pendientes[lista] = lambda: tanda(hasta, self._TANDA_TARJETAS)
                    QTimer.singleShot(0, lambda: self._revisar_tanda_por_scroll(lista))
                else:
                    layout.addStretch()
            except RuntimeError:
                pass  # el módulo se destruyó entre tandas

        self._conectar_scroll_tandas(lista)
        tanda(0, self._PRIMERA_TANDA_TARJETAS)

    def _conectar_scroll_tandas(self, lista):
        conectadas = self.__dict__.setdefault('_scroll_tandas_conectado', set())
        nombre = self._scroll_de_lista(lista)
        scroll = getattr(self, nombre, None) if nombre else None
        if scroll is None or lista in conectadas:
            return
        conectadas.add(lista)
        barra = scroll.verticalScrollBar()
        barra.valueChanged.connect(lambda _v: self._revisar_tanda_por_scroll(lista))
        barra.rangeChanged.connect(lambda _a, _b: QTimer.singleShot(0, lambda: self._revisar_tanda_por_scroll(lista)))

    def _revisar_tanda_por_scroll(self, lista):
        """Construye la siguiente tanda si el final de la lista está a menos
        de dos pantallas de distancia (o si la lista aún no llena la vista)."""
        try:
            continuar = self.__dict__.get('_tanda_pendiente', {}).get(lista)
            nombre = self._scroll_de_lista(lista)
            scroll = getattr(self, nombre, None) if nombre else None
            if continuar is None or scroll is None or not scroll.isVisible():
                return
            barra = scroll.verticalScrollBar()
            if barra.maximum() - barra.value() <= 2 * scroll.viewport().height():
                continuar()
        except RuntimeError:
            pass

    def _on_cliente_card_clicked(self, row_idx):
        if row_idx < 0 or row_idx >= len(self._df_clientes_visible):
            return
        row = self._df_clientes_visible.iloc[row_idx]
        cdb_anterior = self._selected_cliente_key
        if cdb_anterior and cdb_anterior in self._cliente_cards:
            self._cliente_cards[cdb_anterior].set_selected(False)
        cdb_nuevo = self._clave_cliente(row)
        if cdb_nuevo in self._cliente_cards:
            self._cliente_cards[cdb_nuevo].set_selected(True)
        self._show_cliente_detalle(row)

    @staticmethod
    def _clave_cliente(fila):
        """Identidad de un cliente (fila de df_clientes_base): su RUT, o su
        razón social si no tiene un RUT utilizable."""
        clave = str(fila.get('Clave', '')).strip()
        return clave or comercial_services.clave_cliente(fila.get('RUT', ''), fila.get('Razón Social', ''))

    # ==========================================
    # VISTA "FLOTA": CDB es la entidad principal; cada fila es un par (CDB,
    # Flota VC) con su conteo de unidades. Un mismo CDB puede tener varias
    # filas (una por cada Flota VC/área distinta que use) — eso es válido,
    # no un conflicto. Las filas con Flota VC vacío (unidad sin Flota VC
    # informado, no inferible) se marcan en rojo.
    # ==========================================
    # ==========================================
    # VISTA "UNIDADES" (caja izquierda): listado general de todas las VIN
    # disponibles en Comercial (misma fuente que Cliente/Flota, sin agrupar
    # ni filtrar). Es la base que luego filtra por CDB la caja derecha.
    # ==========================================
    def _build_unidades_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Filtro de Unidades (Razón Social / Estado Activación): mismo
        # patrón visual que el bloque de filtros avanzados de Comercial
        # (botón + menú desplegable con checklist), oculto hasta que se
        # activa btn_filtro_unidades (ver _toggle_filtro_unidades).
        self.advanced_filters_frame_unidades = QFrame()
        ThemeManager.apply_card_style(self.advanced_filters_frame_unidades)
        self.advanced_filters_frame_unidades.hide()

        advanced_layout_unidades = QHBoxLayout(self.advanced_filters_frame_unidades)
        advanced_layout_unidades.setContentsMargins(10, 8, 10, 8)
        advanced_layout_unidades.setSpacing(12)

        # Filtros por columna (09-10-2026): traen las unidades que cumplan los
        # valores marcados; cada lista sale de los datos, sin repetidos ni '-'.
        self._filtros_unidades = {}
        grilla = QGridLayout()
        grilla.setHorizontalSpacing(8)
        grilla.setVerticalSpacing(6)
        for i, (columna, titulo) in enumerate(_FILTROS_UNIDADES):
            boton = FiltroValoresBoton(titulo)
            boton.cambiado.connect(self.filter_unidades)
            self._filtros_unidades[columna] = boton
            grilla.addWidget(boton, i // 3, i % 3)
        self.btn_limpiar_filtros_unidades = QPushButton("Limpiar filtros")
        self.btn_limpiar_filtros_unidades.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_limpiar_filtros_unidades.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; color: {TEXT_SECONDARY}; font-size: 11px; "
            "font-weight: 700; text-decoration: underline; padding: 5px 8px; }")
        self.btn_limpiar_filtros_unidades.clicked.connect(self._limpiar_filtros_unidades)
        grilla.addWidget(self.btn_limpiar_filtros_unidades, (len(_FILTROS_UNIDADES) + 2) // 3, 0,
                         alignment=Qt.AlignmentFlag.AlignLeft)
        advanced_layout_unidades.addLayout(grilla, 1)

        btn_close_filtro_unidades = QPushButton()
        btn_close_filtro_unidades.setIcon(ThemeManager.icon('fa5s.times', color=DANGER))
        btn_close_filtro_unidades.setFixedSize(30, 30)
        btn_close_filtro_unidades.setStyleSheet(f"border: 1px solid {DANGER}; border-radius: 6px; background-color: #FEF2F2;")
        btn_close_filtro_unidades.clicked.connect(lambda: self.btn_filtro_unidades.setChecked(False))

        advanced_layout_unidades.addStretch()
        advanced_layout_unidades.addWidget(btn_close_filtro_unidades, alignment=Qt.AlignmentFlag.AlignBottom)

        layout.addWidget(self.advanced_filters_frame_unidades)

        pag_top, self._lbl_pagina_unidades_top, self._btn_pagina_ant_unidades_top, self._btn_pagina_sig_unidades_top = \
            self._crear_controles_paginacion(self._pagina_anterior_unidades, self._pagina_siguiente_unidades)

        pag_top.setParent(widget)
        pag_top.hide()
        top_row = QHBoxLayout()
        self._lbl_total_unidades = QLabel("")
        self._lbl_total_unidades.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: bold;")
        top_row.addStretch(1)
        top_row.addWidget(self._lbl_total_unidades)
        top_row.addWidget(self._crear_selector_tamano_pagina(self._on_cambiar_tamano_pagina_unidades))
        top_row.addWidget(self._crear_boton_ordenar_unidades())
        layout.addLayout(top_row)

        self.unidades_scroll = QScrollArea()
        self.unidades_scroll.setWidgetResizable(True)
        self.unidades_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.unidades_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.unidades_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.unidades_scroll.viewport().setStyleSheet("background: transparent;")

        unidades_container = QWidget()
        unidades_container.setStyleSheet(QSS_TARJETAS_UNIDAD)
        self.unidades_layout = QVBoxLayout(unidades_container)
        self.unidades_layout.setContentsMargins(2, 2, 2, 2)
        self.unidades_layout.setSpacing(8)
        self.unidades_layout.addStretch()
        self.unidades_scroll.setWidget(unidades_container)

        layout.addWidget(self.unidades_scroll, stretch=1)

        pag_bottom, self._lbl_pagina_unidades_bottom, self._btn_pagina_ant_unidades_bottom, self._btn_pagina_sig_unidades_bottom = \
            self._crear_controles_paginacion(self._pagina_anterior_unidades, self._pagina_siguiente_unidades)
        layout.addWidget(pag_bottom)

        return widget

    def _on_cambiar_orden_unidades(self, orden):
        """`orden`: bool (A-Z/Z-A por Razón Social) o una clave de
        _crear_boton_ordenar_unidades."""
        if isinstance(orden, bool):
            self._unidades_orden_columna = None
            self._unidades_orden_asc = orden
        else:
            columna, _, sentido = str(orden).partition(':')
            self._unidades_orden_columna = columna
            self._unidades_orden_asc = sentido == 'asc'
        self.filter_unidades()

    def _on_cambiar_tamano_pagina_unidades(self, nuevo_tamano):
        self._unidades_tam_pagina = nuevo_tamano
        self._unidades_pagina_actual = 0
        self._animar_carga_breve(solo_izquierda=True)
        self._pintar_pagina_unidades()

    def _render_unidades_cards(self, df_f):
        """Paginado igual que _render_clientes_cards/_pintar_pagina_clientes,
        ver ese docstring -- Unidades es la lista que más crece en
        producción (una fila por VIN, sin agrupar), así que es la que más
        se beneficia de no construir todo de golpe. Incluye el mismo render
        diferido si Unidades (índice 2) no es la pestaña visible (Fase 5,
        21-09-2026)."""
        self._unidades_df_paginado = df_f
        self._unidades_pagina_actual = 0
        if self.left_stack.currentIndex() == 1:
            self._pintar_pagina_unidades()
            self._unidades_pendiente_render = False
        else:
            self._unidades_pendiente_render = True

    def _pagina_anterior_unidades(self):
        if self._unidades_pagina_actual > 0:
            self._unidades_pagina_actual -= 1
            self._animar_carga_breve(solo_izquierda=True)
            self._pintar_pagina_unidades()

    def _pagina_siguiente_unidades(self):
        total_paginas = max(1, -(-len(self._unidades_df_paginado) // self._unidades_tam_pagina))
        if self._unidades_pagina_actual < total_paginas - 1:
            self._unidades_pagina_actual += 1
            self._animar_carga_breve(solo_izquierda=True)
            self._pintar_pagina_unidades()

    def _pintar_pagina_unidades(self):
        layout = self.unidades_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._unidad_cards = {}
        self._cancelar_tandas('unidades')

        df_f = self._unidades_df_paginado
        total_paginas = max(1, -(-len(df_f) // self._unidades_tam_pagina))
        self._lbl_total_unidades.setText(f"{len(df_f):,} contrato{'' if len(df_f) == 1 else 's'}".replace(",", "."))
        self._actualizar_controles_paginacion(
            self._unidades_pagina_actual, total_paginas,
            (self._lbl_pagina_unidades_top, self._btn_pagina_ant_unidades_top, self._btn_pagina_sig_unidades_top),
            (self._lbl_pagina_unidades_bottom, self._btn_pagina_ant_unidades_bottom, self._btn_pagina_sig_unidades_bottom),
        )

        if df_f.empty:
            lbl_vacio = QLabel("No hay unidades que coincidan con la búsqueda/filtros.")
            lbl_vacio.setWordWrap(True)
            lbl_vacio.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 12px;")
            layout.addWidget(lbl_vacio)
            layout.addStretch()
            return

        inicio = self._unidades_pagina_actual * self._unidades_tam_pagina
        fin = min(inicio + self._unidades_tam_pagina, len(df_f))

        def crear(row_idx):
            fila = df_f.iloc[row_idx]
            card = GeneralUnidadCard(
                row_idx, fila.get('VIN', ''), fila.get('CHASIS', ''), fila.get('Razón Social', ''),
                fila.get('Estado Activación', ''), fila.get('Industria/s', ''), fila.get('ETAPA GESTIÓN', ''),
                extras={
                    'cdb': fila.get('CDB', ''), 'estado_comercial': fila.get('Estado Comercial', ''),
                    'forma_contrato': fila.get('Forma de Contrato', ''),
                    'tipo_facturacion': fila.get('Tipo de Facturación', ''),
                    'inicio': fila.get('Inicio Contrato', ''), 'termino': fila.get('Término Contrato', ''),
                    'periodo': fila.get('Periodo Interno', ''), 'rut': fila.get('RUT', ''),
                },
            )
            card.clicked.connect(self._on_unidad_card_clicked)
            vin_key = str(fila.get('VIN', '')).strip()
            self._unidad_cards[vin_key] = card
            if self._vin_seleccionado and vin_key.upper() == str(self._vin_seleccionado).strip().upper():
                card.set_selected(True)
            return card
        self._construir_tarjetas_por_tandas('unidades', layout, range(inicio, fin), crear)

    def _on_unidad_card_clicked(self, row_idx):
        if row_idx < 0 or row_idx >= len(self._df_unidades_visible):
            return
        vin_anterior = str(self._vin_seleccionado).strip() if self._vin_seleccionado else None
        if vin_anterior and vin_anterior in self._unidad_cards:
            self._unidad_cards[vin_anterior].set_selected(False)

        vin = str(self._df_unidades_visible.iloc[row_idx].get('VIN', '')).strip()
        if not vin:
            self._vin_seleccionado = None
            self._show_vin_vacio()
            return

        self._vin_seleccionado = vin
        if vin in self._unidad_cards:
            self._unidad_cards[vin].set_selected(True)
        self._show_vin_detalle(vin)

    # ==========================================
    # VISTA "UNIDADES" (caja derecha, detalle de cliente): solo las VIN del
    # CDB seleccionado. El filtrado se hace por CDB, nunca por Flota VC (un
    # CDB puede tener varias Flota VC distintas y todas sus unidades deben
    # listarse igual).
    # ==========================================
    def _build_detalle_unidades_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Lista de filas (antes una tabla): doble clic abre la unidad en la
        # pestaña Unidades de la caja izquierda (_abrir_unidad_en_pestana_unidades).
        self.lbl_unidades_detalle_resumen = QLabel("")
        self.lbl_unidades_detalle_resumen.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self.lbl_unidades_detalle_resumen)

        # Filtro por flota (se activa al hacer clic en una flota de Flotas VC)
        self.fila_filtro_flota_detalle = QFrame()
        self.fila_filtro_flota_detalle.setStyleSheet(
            f"QFrame {{ background-color: {AZUL_HOVER}; border: none; border-radius: 12px; }}"
            "QLabel { background: transparent; color: white; font-size: 11px; font-weight: bold; border: none; }")
        fila_filtro = QHBoxLayout(self.fila_filtro_flota_detalle)
        fila_filtro.setContentsMargins(12, 4, 6, 4)
        self.lbl_filtro_flota_detalle = _EtiquetaElidida("")
        fila_filtro.addWidget(self.lbl_filtro_flota_detalle, 1)
        btn_quitar = QPushButton("Quitar filtro")
        btn_quitar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_quitar.setStyleSheet("QPushButton { background-color: white; color: " + VOLVO_BLUE + "; border: none; "
                                 "border-radius: 9px; padding: 3px 10px; font-size: 10px; font-weight: bold; }")
        btn_quitar.clicked.connect(self._quitar_filtro_flota_detalle)
        fila_filtro.addWidget(btn_quitar)
        self.fila_filtro_flota_detalle.hide()
        layout.addWidget(self.fila_filtro_flota_detalle, 0, Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        self.unidades_detalle_layout = QVBoxLayout(contenedor)
        self.unidades_detalle_layout.setContentsMargins(0, 0, 4, 0)
        self.unidades_detalle_layout.setSpacing(6)
        self.unidades_detalle_layout.addStretch()
        scroll.setWidget(contenedor)
        self._unidades_detalle_filas = {}
        layout.addWidget(scroll, stretch=1)
        return widget

    def _pintar_unidades_detalle(self, df_display, cdb_principal=""):
        layout = self.unidades_detalle_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._unidades_detalle_filas = {}

        total = len(df_display)
        if total == 0:
            self.lbl_unidades_detalle_resumen.setText("")
            lbl = QLabel("Este cliente no tiene unidades registradas.")
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 12px;")
            layout.addWidget(lbl)
            layout.addStretch()
            return

        self.lbl_unidades_detalle_resumen.setText(
            f"{total} {'unidad' if total == 1 else 'unidades'} · doble clic para abrir en Unidades")
        for _, fila in df_display.iterrows():
            widget_fila = GeneralUnidadFila(
                fila.get('VIN', ''), fila.get('CHASIS', ''), fila.get('Flota VC', ''), fila.get('Estado Activación', ''),
                cdb_flota=fila.get('CDB Flota', ''), cdb_principal=cdb_principal)
            widget_fila.seleccionada.connect(self._on_unidad_detalle_seleccionada)
            widget_fila.abrir.connect(self._abrir_unidad_en_pestana_unidades)
            self._unidades_detalle_filas[widget_fila._vin] = widget_fila
            if widget_fila._vin.upper() in getattr(self, '_vins_busqueda', ()):
                widget_fila.set_selected(True)
            layout.addWidget(widget_fila)
        layout.addStretch()

    # ==========================================
    # SUBPESTAÑA "FLOTAS VC" (caja derecha, detalle de cliente): flotas del
    # cliente y cantidad de unidades de cada una; los "-" no cuentan.
    # ==========================================
    def _build_detalle_flotas_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.lbl_flotas_detalle_resumen = QLabel("")
        self.lbl_flotas_detalle_resumen.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self.lbl_flotas_detalle_resumen)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        self.flotas_detalle_layout = QVBoxLayout(contenedor)
        self.flotas_detalle_layout.setContentsMargins(0, 0, 4, 0)
        self.flotas_detalle_layout.setSpacing(6)
        self.flotas_detalle_layout.addStretch()
        scroll.setWidget(contenedor)
        self._flotas_detalle_filas = {}
        layout.addWidget(scroll, stretch=1)
        return widget

    @staticmethod
    def _flotas_de_unidades(df_unidades, columna=None):
        """[(flota, cantidad de unidades)] de un cliente, de mayor a menor,
        sin contar vacíos ni '-'."""
        columna = columna or COL_FLOTA_VC
        if df_unidades is None or df_unidades.empty or columna not in df_unidades.columns:
            return []
        nombres = df_unidades[columna].dropna().astype(str).str.strip()
        nombres = nombres[[_flota_valida(n) for n in nombres]]
        # Mismo nombre escrito distinto (mayúsculas/espacios) cuenta como una
        # sola flota; se muestra la escritura más frecuente.
        grupos = {}
        for n in nombres:
            grupos.setdefault(_clave_flota_texto(n), []).append(n)
        flotas = []
        for variantes in grupos.values():
            conteo = pd.Series(variantes).value_counts()
            flotas.append((conteo.index[0], len(variantes)))
        return sorted(flotas, key=lambda x: (-x[1], x[0].lower()))

    @staticmethod
    def _cdb_por_flota(df_unidades):
        """{clave de flota VC: "CDB1, CDB2"} con los CDB flota de sus unidades."""
        if df_unidades is None or df_unidades.empty or COL_FLOTA_VC not in df_unidades.columns \
                or COL_CDB_FLOTA not in df_unidades.columns:
            return {}
        mapa = {}
        for flota, cdb in zip(df_unidades[COL_FLOTA_VC].astype(str).str.strip(), df_unidades[COL_CDB_FLOTA].astype(str).str.strip()):
            cdb = cdb[:-2] if cdb.endswith(".0") else cdb
            if not _flota_valida(flota) or cdb.upper() in ("", "-", "NAN", "NONE", "<NA>", "NO ENCONTRADO"):
                continue
            lista = mapa.setdefault(_clave_flota_texto(flota), [])
            if cdb not in lista:
                lista.append(cdb)
        return {clave: ", ".join(cdbs) for clave, cdbs in mapa.items()}

    def _pintar_flotas_detalle(self, flotas, cdb_por_flota=None):
        cdb_por_flota = cdb_por_flota or {}
        layout = self.flotas_detalle_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._flotas_detalle_filas = {}
        self.btn_detalle_flotas.setText(f"Flotas VC ({len(flotas)})" if flotas else "Flotas VC")

        if not flotas:
            self.lbl_flotas_detalle_resumen.setText("")
            lbl = QLabel("Este cliente no tiene flotas VC informadas.")
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 12px;")
            layout.addWidget(lbl)
            layout.addStretch()
            return

        total = sum(n for _, n in flotas)
        self.lbl_flotas_detalle_resumen.setText(
            f"{len(flotas)} {'flota' if len(flotas) == 1 else 'flotas'} · {total} "
            f"{'unidad' if total == 1 else 'unidades'} con flota")
        for nombre, cantidad in flotas:
            fila = GeneralFlotaFila(nombre, cantidad, cdb_por_flota.get(_clave_flota_texto(nombre), ""))
            fila.seleccionada.connect(self._on_flota_detalle_seleccionada)
            self._flotas_detalle_filas[nombre] = fila
            layout.addWidget(fila)
        layout.addStretch()

    def _resaltar_flota_detalle(self, flota):
        for clave, fila in self._flotas_detalle_filas.items():
            fila.set_selected(clave == flota)

    def _on_flota_detalle_seleccionada(self, flota):
        """Clic en una flota: abre la subpestaña Unidades con solo las
        unidades de esa flota."""
        self._resaltar_flota_detalle(flota)
        self._flota_filtro_detalle = flota
        self._populate_unidades_detalle(self._selected_cliente_key)
        self._switch_detalle_view(1)

    def _quitar_filtro_flota_detalle(self):
        self._flota_filtro_detalle = None
        self._populate_unidades_detalle(self._selected_cliente_key)

    def _on_unidad_detalle_seleccionada(self, vin):
        for clave, fila in self._unidades_detalle_filas.items():
            fila.set_selected(clave == vin)

    def _abrir_unidad_en_pestana_unidades(self, vin):
        """Doble clic en una unidad del detalle de cliente: abre la pestaña
        Unidades de la caja izquierda en la página donde está esa unidad,
        la resalta y la caja derecha pasa a mostrar su ficha."""
        vin = str(vin).strip()
        if not vin:
            return
        self._vin_seleccionado = vin
        df = getattr(self, '_unidades_df_paginado', None)
        if df is not None and not df.empty and 'VIN' in df.columns:
            coincide = (df['VIN'].astype(str).str.strip().str.upper() == vin.upper()).to_numpy().nonzero()[0]
            if len(coincide):
                self._unidades_pagina_actual = int(coincide[0]) // self._unidades_tam_pagina
                self._unidades_pendiente_render = True
        self._switch_left_view(1)
        if not self._vin_seleccionado:
            # La lista de Unidades tiene filtros/búsqueda que ocultan este
            # VIN: igual se muestra su ficha en la caja derecha.
            self._vin_seleccionado = vin
            self._show_vin_detalle(vin)
        self._desplazar_a_unidad(vin)

    def _desplazar_a_unidad(self, vin, intentos=8):
        self._desplazar_a_tarjeta('_unidad_cards', vin, 'unidades_scroll', intentos)

    def _desplazar_a_tarjeta(self, atributo_cards, clave, atributo_scroll, intentos=8):
        """Las tarjetas se construyen por tandas: reintenta hasta que exista."""
        card = getattr(self, atributo_cards, {}).get(clave)
        if card is not None:
            getattr(self, atributo_scroll).ensureWidgetVisible(card, 0, 40)
        elif intentos > 0:
            QTimer.singleShot(120, lambda: self._desplazar_a_tarjeta(atributo_cards, clave, atributo_scroll, intentos - 1))

    def _abrir_cliente_desde_unidad(self, razon_social, rut=""):
        """Clic en la razón social de la ficha de una unidad: abre la
        pestaña Cliente en la página del cliente (identificado por su RUT),
        lo resalta y la caja derecha pasa a mostrar su detalle."""
        razon = str(razon_social).strip()
        if not razon or razon == '-':
            return
        clave = comercial_services.clave_cliente(rut, razon)
        df = getattr(self, '_clientes_df_paginado', None)
        if df is not None and not df.empty and 'Clave' in df.columns:
            coincide = (df['Clave'].astype(str) == clave).to_numpy().nonzero()[0]
            if len(coincide):
                self._clientes_pagina_actual = int(coincide[0]) // self._clientes_tam_pagina
                self._clientes_pendiente_render = True
        self._switch_left_view(0)
        # (si el cliente no está en la lista filtrada, igual se muestra su
        # detalle en la caja derecha)
        self._seleccionar_cliente_por_clave(clave)
        self._desplazar_a_tarjeta('_cliente_cards', clave, 'clientes_scroll')

    def _abrir_flota_desde_unidad(self, cdb, flota_vc, razon_social="", rut=""):
        """Clic en la Flota VC de la ficha de una unidad: abre la pestaña
        Cliente con el dueño de la flota y su subpestaña Flotas VC, con esa
        flota resaltada."""
        cdb, flota = str(cdb).strip(), str(flota_vc).strip()
        if not flota or flota == '-':
            return
        razon = str(razon_social).strip()
        if not razon or razon == '-':
            self._switch_left_view(0)
            self._show_flota_sin_cliente(flota)
            return
        self._abrir_cliente_desde_unidad(razon, rut)
        self._switch_detalle_view(2)
        self._resaltar_flota_detalle(flota)

    # ==========================================
    # PESTAÑA "CONTACTOS" (caja derecha, detalle de cliente): mismos
    # contactos que la caja "Contactos encontrados" del Resumen (mismo cruce
    # por CDB, mismo correo desde Power BI), pero sin el límite de alto de
    # esa caja -- este es el destino del botón "Ver todos". Se puebla en
    # _populate_contactos_encontrados(), que llena ambos contenedores.
    # ==========================================
    def _build_detalle_contactos_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        self.lbl_detalle_contactos_titulo = QLabel("CONTACTOS DEL CLIENTE")
        self.lbl_detalle_contactos_titulo.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        header_row.addWidget(self.lbl_detalle_contactos_titulo)
        header_row.addStretch()

        # Movido desde la caja "Contactos encontrados" del Resumen (a pedido
        # explícito): arriba de la pestaña, fuera del QScrollArea de abajo,
        # para que quede fijo al hacer scroll en vez de desplazarse con las
        # tarjetas.
        self.btn_agregar_contacto = QPushButton(" + Agregar contacto")
        self.btn_agregar_contacto.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_agregar_contacto.setStyleSheet(f"""
            QPushButton {{ background-color: {AZUL}; color: white; border: none;
                          border-radius: 8px; padding: 6px 12px; font-weight: bold; font-size: 11px; }}
            QPushButton:hover {{ background-color: {AZUL_HOVER}; }}
            QPushButton:disabled {{ background-color: {BORDER}; color: {TEXT_MUTED}; }}
        """)
        self.btn_agregar_contacto.clicked.connect(self._handle_agregar_contacto)
        header_row.addWidget(self.btn_agregar_contacto)
        layout.addLayout(header_row)

        contactos_tab_scroll = QScrollArea()
        contactos_tab_scroll.setWidgetResizable(True)
        contactos_tab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        contactos_tab_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        contactos_tab_scroll.viewport().setStyleSheet("background: transparent;")

        contactos_tab_container = QWidget()
        contactos_tab_container.setStyleSheet("background: transparent;")
        self.contactos_tab_layout = QVBoxLayout(contactos_tab_container)
        self.contactos_tab_layout.setContentsMargins(0, 2, 4, 2)
        self.contactos_tab_layout.setSpacing(8)
        contactos_tab_scroll.setWidget(contactos_tab_container)

        layout.addWidget(contactos_tab_scroll, stretch=1)
        return widget

    # ==========================================
    # PESTAÑA "DUPLICADOS" (23-09-2026, a pedido explícito): lista los otros
    # clientes (Razón Social) que comparten el mismo RUT+CDB que el
    # actualmente seleccionado -- ver _calcular_claves_duplicadas_rut_cdb /
    # _populate_duplicados_detalle. Solo se muestra cuando corresponde (ver
    # btn_detalle_duplicados.setVisible en _populate_duplicados_detalle).
    # ==========================================
    def _build_detalle_duplicados_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        aviso = QFrame()
        aviso.setObjectName("avisoRazones")
        aviso.setStyleSheet("QFrame#avisoRazones { background-color: #FFF7ED; border: 1px solid #FED7AA; border-radius: 10px; }"
                            "QFrame#avisoRazones QLabel { background: transparent; border: none; }")
        aviso_layout = QVBoxLayout(aviso)
        aviso_layout.setContentsMargins(14, 10, 14, 10)
        aviso_layout.setSpacing(2)
        lbl_aviso_titulo = QLabel("Este RUT tiene más de una razón social")
        lbl_aviso_titulo.setStyleSheet("color: #9A3412; font-size: 12px; font-weight: bold;")
        lbl_aviso_texto = QLabel("Puede ser el mismo cliente escrito de formas distintas. "
                                 "La principal es la que tiene más unidades.")
        lbl_aviso_texto.setWordWrap(True)
        lbl_aviso_texto.setStyleSheet("color: #9A3412; font-size: 11px;")
        aviso_layout.addWidget(lbl_aviso_titulo)
        aviso_layout.addWidget(lbl_aviso_texto)
        layout.addWidget(aviso)

        # Unificación manual (23-09-2026, a pedido explícito): conserva la
        # Razón Social con más unidades del grupo (mismo criterio que
        # RMJaviSyncWorker aplica automáticamente en cada sincronización,
        # ver comercial_services.detectar_grupos_razon_social_duplicada) y
        # renombra las demás a esa misma. Reescribe PruebasFM de verdad, por
        # eso pide confirmación antes de ejecutar.
        self.btn_unificar_razon_social = QPushButton("Unificar en una sola razón social")
        self.btn_unificar_razon_social.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_unificar_razon_social.setStyleSheet(f"""
            QPushButton {{ background-color: {AZUL}; color: white; border: 1px solid {AZUL};
                          border-radius: 10px; padding: 8px 14px; font-weight: bold; font-size: 11px; }}
            QPushButton:hover {{ background-color: {AZUL_HOVER}; border: 1px solid {AZUL_HOVER}; }}
            QPushButton:disabled {{ background-color: #C5CCDA; border: 1px solid #C5CCDA; color: #F3F5F9; }}
        """)
        self.btn_unificar_razon_social.clicked.connect(self._on_unificar_razon_social_clicked)
        layout.addWidget(self.btn_unificar_razon_social)

        duplicados_scroll = QScrollArea()
        duplicados_scroll.setWidgetResizable(True)
        duplicados_scroll.setFrameShape(QFrame.Shape.NoFrame)
        duplicados_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        duplicados_scroll.viewport().setStyleSheet("background: transparent;")

        duplicados_container = QWidget()
        duplicados_container.setStyleSheet("background: transparent;")
        self.duplicados_tab_layout = QVBoxLayout(duplicados_container)
        self.duplicados_tab_layout.setContentsMargins(0, 2, 0, 2)
        self.duplicados_tab_layout.setSpacing(4)
        duplicados_scroll.setWidget(duplicados_container)

        layout.addWidget(duplicados_scroll, stretch=1)
        return widget

    def _razones_del_cliente(self, clave):
        """[(razón social, unidades)] de un cliente, de mayor a menor."""
        if self.df_comercial_raw.empty or '_clave_cliente' not in self.df_comercial_raw.columns:
            return []
        filas = self.df_comercial_raw[self.df_comercial_raw['_clave_cliente'] == clave]
        conteo = filas[COL_RAZON_SOCIAL].astype(str).str.strip().value_counts()
        return [(r, int(n)) for r, n in conteo.items()]

    def _unidades_por_razon(self, clave):
        """{razón social: [(VIN, chasis, estado de activación, estado comercial)]}
        de las unidades de un cliente."""
        df = self.df_comercial_raw
        if df.empty or '_clave_cliente' not in df.columns or COL_VIN not in df.columns:
            return {}
        filas = df[df['_clave_cliente'] == clave]

        def texto(col):
            return filas[col].astype(str).str.strip() if col in filas.columns else pd.Series('-', index=filas.index)

        tabla = pd.DataFrame({'razon': texto(COL_RAZON_SOCIAL), 'vin': texto(COL_VIN), 'chasis': texto(COL_CHASIS),
                              'act': texto(COL_ESTADO_ACTIVACION), 'com': texto(COL_ESTADO_COMERCIAL)})
        resultado = {}
        for razon, grupo in tabla.groupby('razon', sort=False):
            resultado[razon] = list(zip(grupo['vin'], grupo['chasis'], grupo['act'], grupo['com']))
        return resultado

    def _populate_duplicados_detalle(self, clave):
        """Puebla la pestaña Duplicados con las razones sociales que tiene el
        cliente seleccionado (mismo RUT) y muestra/oculta btn_detalle_duplicados
        según corresponda. Se llama desde _show_cliente_detalle."""
        layout = self.duplicados_tab_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        hay_duplicados = clave in self._clientes_con_varias_razones
        self.btn_detalle_duplicados.setVisible(hay_duplicados)
        # None cuando no hay duplicados, para que el botón nunca actúe sobre
        # un cliente obsoleto.
        self._grupo_duplicados_actual = clave if hay_duplicados else None
        if not hay_duplicados:
            # Si el usuario estaba viendo esta pestaña y el nuevo cliente ya
            # no tiene duplicados, vuelve a Resumen.
            if self.detalle_stack.currentIndex() == 4:
                self._switch_detalle_view(0)
            layout.addStretch()
            return

        razones = self._razones_del_cliente(clave)
        self.btn_detalle_duplicados.setText(f"Razones ({len(razones)})")
        unidades_por_razon = self._unidades_por_razon(clave)
        for i, (razon, unidades) in enumerate(razones):
            layout.addWidget(GeneralDuplicadoCard(razon, unidades, principal=(i == 0),
                                                  unidades=unidades_por_razon.get(razon, []),
                                                  al_abrir_unidad=self._abrir_unidad_en_pestana_unidades))
        layout.addStretch()

    def _seleccionar_cliente_por_clave(self, clave):
        """Navega al cliente indicado: actualiza la caja derecha siempre, y
        la tarjeta resaltada de la caja izquierda si está en la lista
        visible (mismo mecanismo que _on_cliente_card_clicked)."""
        df_v = self._df_clientes_visible
        if 'Clave' in df_v.columns:
            posiciones = (df_v['Clave'].astype(str) == str(clave)).to_numpy().nonzero()[0]
            if len(posiciones):
                self._on_cliente_card_clicked(int(posiciones[0]))
                return

        # El cliente no está en la lista filtrada (ej. el buscador lo
        # excluye): se actualiza igual la caja derecha.
        fila = self._buscar_cliente_por_clave(clave)
        if fila is not None:
            self._show_cliente_detalle(fila)

    # ==========================================
    # UNIFICACIÓN MANUAL DE RAZÓN SOCIAL DUPLICADA (23-09-2026, a pedido
    # explícito): botón "Unificar en una sola Razón Social" de la pestaña
    # Duplicados. Misma lógica de detección/ganadora que aplica
    # automáticamente RMJaviSyncWorker en cada sincronización con RM_JAVI
    # (comercial_services.detectar_grupos_razon_social_duplicada), pero
    # acotada al grupo (RUT, CDB) que el usuario está viendo y con
    # confirmación explícita antes de escribir.
    # ==========================================
    def _on_unificar_razon_social_clicked(self):
        clave = self._grupo_duplicados_actual
        if not clave or self.df_comercial_raw.empty:
            return

        razones = self._razones_del_cliente(clave)
        if len(razones) < 2:
            QMessageBox.information(self, "Nada que unificar",
                "Este RUT tiene una sola Razón Social en este momento.")
            return

        ganadora = razones[0][0]
        perdedoras = [r for r, _ in razones[1:]]
        detalle_perdedoras = "\n".join(f"  • \"{r}\" ({n} unidad(es))" for r, n in razones[1:])
        mensaje = (
            f"Se va a unificar este cliente en una sola Razón Social:\n\n"
            f"Se conserva: \"{ganadora}\" ({razones[0][1]} unidad(es), la de más unidades)\n\n"
            f"Se renombrarán a esa misma Razón Social:\n{detalle_perdedoras}\n\n"
            f"Esto modifica PruebasFM de verdad (con copia de seguridad previa, como cualquier guardado). ¿Confirmar?"
        )
        respuesta = QMessageBox.question(self, "Unificar Razón Social", mensaje,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes:
            return

        df_grupo = self.df_comercial_raw[self.df_comercial_raw['_clave_cliente'] == clave]
        filas_a_cambiar = df_grupo[df_grupo[COL_RAZON_SOCIAL].astype(str).str.strip().isin(perdedoras)]
        changes_dict = {
            str(vin): {'VIN': vin, 'cambios': {'RAZÓN SOCIAL': ganadora}}
            for vin in filas_a_cambiar['VIN']
        }
        if not changes_dict:
            return
        comercial_services.agregar_id_a_cambios(changes_dict, self.df_comercial_raw)

        self.btn_unificar_razon_social.setEnabled(False)
        self._unificar_razon_social_thread = SaveExcelThread(self.writer, changes_dict, module_name="Vista General (Unificación de duplicados)")
        self._unificar_razon_social_thread.finished_signal.connect(
            lambda success: self._on_unificar_razon_social_finished(success, changes_dict, ganadora)
        )
        self._unificar_razon_social_thread.logs_actualizados_signal.connect(self.data_manager.set_logs_df)
        self._unificar_razon_social_thread.start()

    def _on_unificar_razon_social_finished(self, success, changes_dict, ganadora):
        self.btn_unificar_razon_social.setEnabled(True)
        if not success:
            QMessageBox.critical(self, "Error", "No se pudo guardar la unificación de Razón Social en PruebasFM.")
            return

        dm = self.data_manager
        if not dm.df_master.empty:
            # aplicar_cambios_pendientes compara la llave tal cual contra
            # VIN ya normalizado (mayúsculas/sin espacios) del propio
            # df_master -- la llave debe venir normalizada igual (ver su
            # docstring), a diferencia de 'VIN' dentro de 'cambios' (usado
            # por ExcelWriter.update_cells más arriba), que no lo requiere.
            pending = {
                str(data['VIN']).strip().upper(): {'cambios': data['cambios'], 'ID': data.get('ID')}
                for data in changes_dict.values()
            }
            dm.df_master = comercial_services.aplicar_cambios_pendientes(dm.df_master, pending)
            dm.data_ready.emit()


    def _toggle_filtro_unidades(self, checked):
        self.advanced_filters_frame_unidades.setVisible(checked)
        # Mismo feedback visual que _toggle_advanced_filters en comercial.py
        self.btn_filtro_unidades.setStyleSheet(QSS_BOTON_FILTRO_SOBRE_AZUL_ACTIVO if checked else QSS_BOTON_FILTRO_SOBRE_AZUL)
        self.btn_filtro_unidades.setIcon(ThemeManager.icon('fa5s.filter', color='white'))

    # ==========================================
    # FILTROS DE "UNIDADES" (caja izquierda): ver FiltroValoresBoton.
    # ==========================================
    def _crear_boton_ordenar(self, on_change, on_change_unidades=None, on_change_flotas=None):
        """Botón único 'Ordenar' (menú A-Z/Z-A, y opcionalmente Más/Menos
        unidades) para las tarjetas de Cliente/Flota/Unidades -- reemplaza
        el clic en encabezado de columna que tenían las tablas anteriores
        (VolvoTableWidget.apply_sort), a pedido explícito (20-09-2026: 'todo
        esto en un solo boton'). on_change(is_asc) se invoca al elegir A-Z/
        Z-A. on_change_unidades(is_asc), si se entrega, agrega las opciones
        'Más unidades'/'Menos unidades' (24-09-2026, a pedido explícito) --
        no aplica a la pestaña Unidades, que es una tabla por VIN sin
        conteo que ordenar."""
        from src.ui.comercial_estilo import BotonOpcionesTarjeta
        opciones = [('asc', "A-Z (ascendente)"), ('desc', "Z-A (descendente)")]
        if on_change_unidades is not None:
            opciones += [('mas', "Más unidades"), ('menos', "Menos unidades")]
        if on_change_flotas is not None:
            opciones += [('flotas_mas', "Más flotas"), ('flotas_menos', "Menos flotas")]

        acciones = {
            'asc': lambda: on_change(True),
            'desc': lambda: on_change(False),
            'mas': lambda: on_change_unidades(False),
            'menos': lambda: on_change_unidades(True),
            'flotas_mas': lambda: on_change_flotas(False),
            'flotas_menos': lambda: on_change_flotas(True),
        }
        btn = BotonOpcionesTarjeta("Ordenar", "Ordenar", opciones, valor='asc',
                                   al_elegir=lambda clave: acciones[clave]())
        btn.setIcon(ThemeManager.icon('fa5s.sort-alpha-down', color=AZUL))
        _boton_minimo(btn)
        return btn

    def _crear_boton_ordenar_unidades(self):
        """Botón 'Ordenar' de Unidades: por estado comercial o por estado de
        activación, ascendente o descendente."""
        from src.ui.comercial_estilo import BotonOpcionesTarjeta
        opciones = [
            ('Estado Comercial:asc', "Estado comercial (A-Z)"), ('Estado Comercial:desc', "Estado comercial (Z-A)"),
            ('Estado Activación:asc', "Estado activación (A-Z)"), ('Estado Activación:desc', "Estado activación (Z-A)"),
        ]
        btn = BotonOpcionesTarjeta("Ordenar por", "Ordenar", opciones, valor=None,
                                   al_elegir=self._on_cambiar_orden_unidades)
        btn.setIcon(ThemeManager.icon('fa5s.sort-alpha-down', color=AZUL))
        _boton_minimo(btn)
        return btn

    def _crear_controles_paginacion(self, on_anterior, on_siguiente):
        """Fila "‹ Anterior | Página X de Y | Siguiente ›" (ver
        _TARJETAS_POR_PAGINA), reutilizada arriba y abajo de cada lista de
        tarjetas (Cliente/Flota/Unidades) a pedido explícito (20-09-2026).
        Devuelve (widget, lbl_pagina, btn_anterior, btn_siguiente) para que
        el llamador guarde las referencias y las actualice en cada repintado
        de página (ver _actualizar_controles_paginacion)."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        btn_anterior = QPushButton("‹ Anterior")
        btn_anterior.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_minimo(btn_anterior)
        btn_anterior.clicked.connect(on_anterior)

        lbl_pagina = QLabel("Página 1 de 1")
        lbl_pagina.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_pagina.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: bold;")

        btn_siguiente = QPushButton("Siguiente ›")
        btn_siguiente.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_minimo(btn_siguiente)
        btn_siguiente.clicked.connect(on_siguiente)

        layout.addWidget(btn_anterior)
        layout.addWidget(lbl_pagina, 1)
        layout.addWidget(btn_siguiente)
        return widget, lbl_pagina, btn_anterior, btn_siguiente

    def _crear_selector_tamano_pagina(self, on_change):
        """Combo "Mostrar: 200/500/1000" (ver _OPCIONES_TAMANO_PAGINA) para
        elegir cuántas tarjetas trae cada página, a pedido explícito
        (20-09-2026). on_change(nuevo_tamano) se llama al elegir una
        opción."""
        from src.ui.comercial_estilo import BotonOpcionesTarjeta
        boton = BotonOpcionesTarjeta(
            "Filas por página",
            opciones=[(o, f"Mostrar {o}") for o in _OPCIONES_TAMANO_PAGINA],
            valor=_OPCIONES_TAMANO_PAGINA[0], mostrar_valor=True, al_elegir=on_change)
        _boton_minimo(boton)
        return boton

    @staticmethod
    def _actualizar_controles_paginacion(pagina_actual, total_paginas, *pares_lbl_botones):
        """Sincroniza el texto "Página X de Y" y el habilitado de Anterior/
        Siguiente en los controles de arriba Y abajo de una misma lista
        (cada elemento de *pares_lbl_botones es (lbl_pagina, btn_anterior,
        btn_siguiente))."""
        texto = f"Página {pagina_actual + 1} de {total_paginas}"
        for lbl_pagina, btn_anterior, btn_siguiente in pares_lbl_botones:
            lbl_pagina.setText(texto)
            btn_anterior.setEnabled(pagina_actual > 0)
            btn_siguiente.setEnabled(pagina_actual < total_paginas - 1)

    # ==========================================
    # SELECCIÓN DE CLIENTE -> CAJA DERECHA
    # (los clics de tarjeta llaman directamente _on_cliente_card_clicked /
    # _on_flota_card_clicked / _on_unidad_card_clicked, definidos junto a
    # cada _build_*_view/_render_*_cards; acá solo quedan las funciones de
    # sincronización tras un refiltrado, ver _sincronizar_seleccion_vin /
    # _sincronizar_seleccion_cliente_flota más abajo)
    # ==========================================

    def _sincronizar_seleccion_vin(self):
        """Se llama tras recalcular self._df_unidades_visible (filtro/
        búsqueda/orden) para mantener la ficha/historial de la caja derecha
        sincronizada con el VIN seleccionado, sin reconstruir tarjetas (eso
        ya lo hace _render_unidades_cards, que resalta la tarjeta si el VIN
        sigue presente). Si el VIN ya no está en la lista filtrada, limpia
        la selección y vacía la caja derecha -- mismo comportamiento que la
        tabla anterior (_restaurar_seleccion_vin)."""
        if self._vin_seleccionado and 'VIN' in self._df_unidades_visible.columns:
            vin_upper = self._vin_seleccionado.strip().upper()
            if (self._df_unidades_visible['VIN'].astype(str).str.strip().str.upper() == vin_upper).any():
                self._show_vin_detalle(self._vin_seleccionado)
                return

        self._vin_seleccionado = None
        self._show_vin_vacio()

    def _resolver_texto_flota_vc_sin_cliente(self, flota_vc):
        """Caja derecha, fila de Flota sin cliente asociado: qué texto
        mostrar para el dato de Flota VC. Devuelve None cuando tampoco hay
        Flota VC (la UI lo traduce en el mensaje "No se encontró
        información" en rojo, ver _show_flota_sin_cliente). Función pura
        (no usa self.*)."""
        flota_vc_str = str(flota_vc).strip() if flota_vc is not None else ""
        if flota_vc_str.lower() in ('', 'nan', 'none', '<na>'):
            return None
        return flota_vc_str

    def _show_flota_sin_cliente(self, flota_vc):
        self._selected_cdb = None
        self._selected_cdbs_flota = []
        self._selected_cliente_key = None
        texto = self._resolver_texto_flota_vc_sin_cliente(flota_vc)
        if texto is None:
            self.lbl_flota_sin_cliente_valor.setText("No se encontró información")
            self.lbl_flota_sin_cliente_valor.setStyleSheet(f"color: {DANGER}; font-size: 11px; font-weight: bold;")
        else:
            self.lbl_flota_sin_cliente_valor.setText(texto)
            self.lbl_flota_sin_cliente_valor.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px; font-weight: bold;")
        self.right_stack.setCurrentIndex(2)

    def _buscar_cliente_por_clave(self, clave):
        """Fila de df_clientes_base de una clave de cliente, o None."""
        if not clave or self.df_clientes_base.empty or 'Clave' not in self.df_clientes_base.columns:
            return None
        coincidencias = self.df_clientes_base[self.df_clientes_base['Clave'].astype(str) == str(clave)]
        return None if coincidencias.empty else coincidencias.iloc[0]

    def _sincronizar_seleccion_cliente(self, df_visible):
        """Se llama tras recalcular _df_clientes_visible (filtro/búsqueda/
        orden) para mantener la caja derecha sincronizada con el cliente
        que ya se estaba mostrando (self._selected_cdb), sin depender de
        una tabla -- mismo rol que cumplía _restaurar_seleccion_cliente_
        flota con table.selectRow() antes de pasar a tarjetas. El resaltado
        visual de la tarjeta ya lo resuelve _render_clientes_cards al
        reconstruir la lista.

        Solo actúa si la pestaña izquierda activa es Cliente (índice 0); si
        el usuario está viendo otra pestaña, no la toca -- evita que una
        búsqueda global le borre el contexto que está viendo."""
        if self.left_stack.currentIndex() != 0:
            return

        if self._selected_cliente_key and 'Clave' in df_visible.columns:
            posiciones = (df_visible['Clave'].astype(str) == self._selected_cliente_key).to_numpy().nonzero()[0]
            if len(posiciones):
                self._show_cliente_detalle(df_visible.iloc[int(posiciones[0])])
                return

        self._show_cliente_vacio()

    @staticmethod
    def _cdbs_flota_de_unidades(df_unidades):
        """CDB flota distintos de las unidades de un cliente, en orden de aparición."""
        cdbs = []
        if COL_CDB_FLOTA in df_unidades.columns:
            for valor in df_unidades[COL_CDB_FLOTA].astype(str).str.strip():
                valor = valor[:-2] if valor.endswith('.0') else valor
                if valor.upper() not in ('', '-', 'NAN', 'NONE', '<NA>', 'NO ENCONTRADO') and valor not in cdbs:
                    cdbs.append(valor)
        return cdbs

    def _pintar_chip_cdb_flota(self, df_unidades):
        """Chip copiable con el CDB flota del cliente; si sus unidades tienen
        varios, muestra el primero y copia todos separados por coma."""
        cdbs = self._cdbs_flota_de_unidades(df_unidades)
        chip = self.lbl_detalle_cdb_flota
        if not cdbs:
            chip.set_value("CDB Flota", "-")
            chip.setToolTip("Este cliente no tiene CDB flota")
        elif len(cdbs) == 1:
            chip.set_value("CDB Flota", cdbs[0])
            chip.setToolTip("Clic para copiar")
        else:
            chip.set_value("CDB Flota", ", ".join(cdbs))
            chip.setText(f"CDB Flota: {cdbs[0]} (+{len(cdbs) - 1})")
            chip.setToolTip("Clic para copiar todos:\n" + "\n".join(cdbs))

    @_con_transicion_derecha
    def _show_cliente_vacio(self):
        self._selected_cdb = None
        self._selected_cdbs_flota = []
        self._selected_cliente_key = None
        if hasattr(self, 'unidades_detalle_layout'):
            self._pintar_unidades_detalle(pd.DataFrame(columns=['VIN', 'CHASIS', 'Flota VC', 'Estado Activación']))
        if hasattr(self, 'flotas_detalle_layout'):
            self._pintar_flotas_detalle([])
        if hasattr(self, 'contactos_encontrados_layout'):
            df_vacio = pd.DataFrame(columns=['CDB', 'Nombre', 'Apellidos', 'Número móvil'])
            self.lbl_ver_todos_contactos.setToolTip("Ver todos (0)")
            self._fijar_conteo_contactos(self._btn_conteo_directores, 0)
            self._fijar_conteo_contactos(self._btn_conteo_administradores, 0)
            self.btn_agregar_admin_resumen.hide()
            self.lbl_detalle_contactos_titulo.setText("CONTACTOS DEL CLIENTE (0)")
            self._populate_contact_cards(self.contactos_encontrados_layout, df_vacio, "")
            self._populate_contact_cards(self.contactos_tab_layout, df_vacio, "")
        self.right_stack.setCurrentIndex(0)

    @_con_transicion_derecha
    def _show_cliente_detalle(self, cliente_row):
        self._ensure_detalle_view_built()
        razon_social = str(cliente_row['Razón Social'])
        self._razon_detalle_actual = razon_social
        self._flota_filtro_detalle = None
        rut = cliente_row['RUT']
        industria = cliente_row['Industria/s']
        cdb = cliente_row['CDB']

        self.lbl_detalle_title.set_texto(razon_social)
        self.lbl_detalle_industria.set_value("Industria", industria)
        self.lbl_detalle_rut.set_value("RUT", rut)
        self.lbl_detalle_cdb.set_value("CDB Comercial", cdb)

        clave = self._clave_cliente(cliente_row)
        if '_clave_cliente' in self.df_comercial_raw.columns:
            df_unidades = self.df_comercial_raw[self.df_comercial_raw['_clave_cliente'] == clave]
        else:
            df_unidades = pd.DataFrame()

        total_unidades = len(df_unidades)
        self.lbl_kpi_unidades.setText(str(total_unidades))
        self._pintar_chip_cdb_flota(df_unidades)

        if total_unidades > 0 and COL_ESTADO_ACTIVACION in df_unidades.columns:
            conectadas = int((df_unidades[COL_ESTADO_ACTIVACION].astype(str).str.strip().str.upper() == ESTADO_ACTIVACION_CONECTADO).sum())
            pct_connect = (conectadas / total_unidades) * 100
        else:
            conectadas, pct_connect = 0, 0
        self.lbl_kpi_connect._tarjeta.actualizar(str(conectadas), pct_connect / 100, "")

        if total_unidades > 0 and COL_TIPO_SERVICIO in df_unidades.columns:
            civ_count = int(df_unidades[COL_TIPO_SERVICIO].astype(str).str.upper().str.contains('CIV', na=False).sum())
            pct_civ = (civ_count / total_unidades) * 100
        else:
            civ_count, pct_civ = 0, 0
        self.lbl_kpi_civ._tarjeta.actualizar(str(civ_count), pct_civ / 100, "")

        if total_unidades > 0 and COL_TIPO_SERVICIO in df_unidades.columns:
            sz_count = int(df_unidades[COL_TIPO_SERVICIO].astype(str).str.upper().str.contains(r'\bSZ\b', regex=True, na=False).sum())
            pct_sz = (sz_count / total_unidades) * 100
        else:
            sz_count, pct_sz = 0, 0
        self.lbl_kpi_safety._tarjeta.actualizar(str(sz_count), pct_sz / 100, "")

        flotas = sorted(n for n, _ in self._flotas_de_unidades(df_unidades))
        # Una sola flota: su nombre; varias: solo el conteo (la lista completa
        # queda en el tooltip); ninguna: aviso. Los "-" no cuentan.
        if not flotas:
            flotas_txt = "Sin flota asignada"
        elif len(flotas) == 1:
            flotas_txt = flotas[0]
        else:
            flotas_txt = f"{len(flotas)} flotas"
        self._info_cliente_flotas_tooltip = "\n".join(flotas) if len(flotas) > 1 else (flotas[0] if flotas else "")

        ejecutivo = ""
        if COL_EJECUTIVO in df_unidades.columns:
            ejecutivos_validos = [str(e).strip() for e in df_unidades[COL_EJECUTIVO].dropna().unique() if str(e).strip()]
            ejecutivo = ejecutivos_validos[0] if ejecutivos_validos else ""

        director_empresa = self._pbi_director_empresa_por_cdb.get(str(cdb).strip(), {})
        direccion = director_empresa.get('direccion', '')
        comuna = director_empresa.get('comuna', '')

        # Guardado para poder re-renderizar Dirección/Comuna si Power BI
        # (async, ver _load_pbi_director_empresa_async) termina de cargar
        # DESPUÉS de que el usuario ya seleccionó este cliente -- mismo caso
        # que ya resolvía _on_pbi_director_empresa_loaded para "Contactos
        # encontrados", ver _refrescar_info_cliente_pbi.
        self._info_cliente_base_args = (razon_social, rut, cdb, industria, ejecutivo, total_unidades, flotas_txt)
        self._render_info_cliente(*self._info_cliente_base_args, direccion=direccion, comuna=comuna)
        self._selected_cdb = cdb
        self._selected_cdbs_flota = self._cdbs_flota_de_unidades(df_unidades)
        self._selected_cliente_key = clave
        self._populate_contactos_encontrados(cdb)
        self._populate_unidades_detalle(self._selected_cliente_key)
        self._pintar_flotas_detalle(self._flotas_de_unidades(df_unidades), self._cdb_por_flota(df_unidades))
        self._populate_duplicados_detalle(self._selected_cliente_key)

        self.right_stack.setCurrentIndex(1)
        self._switch_detalle_view(0)  # siempre inicia en Resumen al elegir un cliente

    def _filtrar_contactos_por_cdb(self, df_contactos, cdb):
        """Razón Social seleccionada -> CDB -> Contactos asociados (caja
        derecha, apartado Contactos). Devuelve TODOS los contactos de ese
        CDB (sin limitar cantidad ni elegir uno solo) y ninguno de otro CDB.
        Función pura (no usa self.*)."""
        if df_contactos.empty or 'CDB' not in df_contactos.columns:
            return df_contactos.iloc[0:0].copy()

        # `cdb` puede ser un código o una lista (cliente con varios CDB flota)
        codigos = [cdb] if isinstance(cdb, str) else list(cdb)
        validos = {str(c).strip() for c in codigos
                   if str(c).strip().lower() not in ('', '-', 'nan', 'none', '<na>')}
        if not validos:
            return df_contactos.iloc[0:0].copy()

        return df_contactos[df_contactos['CDB'].astype(str).str.strip().isin(validos)]

    def _populate_contact_cards(self, layout, encontrados, director_empresa=None):
        """Llena `layout` con una tarjeta por contacto (_create_contacto_card),
        cada una con su PROPIO Nombre + Apellido | Correo | Número móvil
        desde contactos.xlsx (no se pisa con ningún dato de Power BI). Si
        `director_empresa` trae correo y/o teléfono (BBDD CLIENTES CM.xlsx,
        Power BI), se antepone una tarjeta aparte y resaltada para ese dato
        de la EMPRESA (_create_director_empresa_card) -- distinto de los
        contactos individuales. Usado tanto por la caja "Contactos
        encontrados" del Resumen como por la pestaña "Contactos" completa
        (mismos datos, dos contenedores distintos porque un QWidget no
        puede vivir en dos layouts a la vez)."""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if director_empresa and (director_empresa.get('correo') or director_empresa.get('telefono')):
            layout.addWidget(self._create_director_empresa_card(
                director_empresa.get('correo', ''), director_empresa.get('telefono', ''),
            ))

        if encontrados.empty:
            lbl_vacio = QLabel("No se encontraron contactos para este CDB flota.")
            lbl_vacio.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 8px 0;")
            lbl_vacio.setWordWrap(True)
            layout.addWidget(lbl_vacio)
        else:
            # Favoritos primero (mismo criterio que contactos.py), luego por
            # ID ascendente.
            if 'ID' in encontrados.columns:
                encontrados = contactos_service.ordenar_por_favoritos_e_id(encontrados, self.pinned_contacts)
            for _, fila in encontrados.iterrows():
                contact_id = contactos_service.normalizar_id_contacto(fila.get('ID', '')) or None
                tarjeta = self._create_contacto_card(
                    str(fila.get('Nombre', '')).strip(),
                    str(fila.get('Apellidos', '')).strip(),
                    str(fila.get('Correo electrónico', '')).strip(),
                    str(fila.get('Número móvil', '')).strip(),
                    contact_id=contact_id,
                )
                layout.addWidget(tarjeta)

        layout.addStretch()

    def _populate_contactos_encontrados(self, cdb):
        df_contactos = self.data_manager.get_contactos_df()
        cdb_str = str(cdb).strip()
        # Los contactos se cruzan por CDB flota; el director de empresa y la
        # dirección (Power BI) siguen por el CDB comercial.
        encontrados = self._filtrar_contactos_por_cdb(df_contactos, getattr(self, '_selected_cdbs_flota', []))

        self.lbl_ver_todos_contactos.setToolTip(f"Ver todos ({len(encontrados)})")
        self.lbl_detalle_contactos_titulo.setText(f"CONTACTOS DEL CLIENTE ({len(encontrados)})")

        director_empresa = self._pbi_director_empresa_por_cdb.get(cdb_str)
        hay_director = bool(director_empresa and (director_empresa.get('correo') or director_empresa.get('telefono')))
        self._fijar_conteo_contactos(self._btn_conteo_directores, 1 if hay_director else 0)
        self._fijar_conteo_contactos(self._btn_conteo_administradores, len(encontrados))
        self.btn_agregar_admin_resumen.setVisible(len(encontrados) == 0)

        self._populate_contact_cards(self.contactos_encontrados_layout, encontrados, director_empresa)
        self._populate_contact_cards(self.contactos_tab_layout, encontrados, director_empresa)

    # ==========================================
    # ALTA DE CONTACTO (Ficha de cliente -> pestaña Contactos -> "Agregar
    # contacto"): mismo ContactosAddDialog, AddContactoThread,
    # contactos_service.generar_nuevo_id_contacto y ExcelWriter.add_new_row
    # que ya usa ContactosModule (contactos.py). Un contacto se relaciona
    # con la empresa por CDB, nunca por VIN (ver conversación con el
    # usuario, Fase 4) -- cdb_prefill/flota_prefill usan el CDB y la Razón
    # Social del cliente actualmente seleccionado. Se permiten
    # explícitamente contactos duplicados (mismo correo/nombre en otra
    # empresa): decisión de negocio confirmada, no se agrega ninguna
    # validación nueva de duplicados ni de formato.
    # ==========================================
    def _handle_agregar_contacto(self):
        if self._selected_cliente_key is None:
            return
        cliente_row = self._buscar_cliente_por_clave(self._selected_cliente_key)
        razon_social = str(cliente_row['Razón Social']) if cliente_row is not None else ''
        cdb_flota = self._selected_cdbs_flota[0] if self._selected_cdbs_flota else None

        dialog = ContactosAddDialog(self, cdb_prefill=cdb_flota, flota_prefill=razon_social)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        new_data = dialog.get_data()
        new_data['ID'] = contactos_service.generar_nuevo_id_contacto(self.data_manager.get_contactos_df())

        self.btn_agregar_contacto.setEnabled(False)
        self._add_contacto_thread = AddContactoThread(self.writer, new_data)
        self._add_contacto_thread.finished_signal.connect(self._on_agregar_contacto_finished)
        self._add_contacto_thread.start()

    def _on_agregar_contacto_finished(self, success, new_data):
        self.btn_agregar_contacto.setEnabled(True)
        if not success:
            QMessageBox.warning(self, "Error", "No se pudo agregar el contacto. Verifica si contactos.xlsx está abierto.")
            return
        # Recarga contactos.xlsx desde disco (mismo mecanismo que
        # ContactosModule.load_data): al terminar emite contactos_ready, ya
        # conectado a _on_contactos_ready, que repuebla la pestaña Contactos
        # del cliente activo -- no se duplica ese refresco aquí.
        self.data_manager.load_contactos_async()

    # Alta de registro (ComercialAgregarDialog -> AddRowThread) e importación
    # Power BI, ambas movidas a Comercial -> pestaña "Unidad nueva"
    # (25-09-2026, refactor: ver comercial.py, ComercialModule
    # ._on_unidad_nueva_confirmada / _abrir_importar_powerbi). General ya no
    # tiene responsabilidad de creación de unidades.

    # ==========================================
    # DATOS
    # ==========================================
    def _on_data_ready(self):
        try:
            if self.isVisible():
                self.load_data()
            else:
                self._data_dirty = True
        except Exception as e:
            print(f"Error silencioso en Clientes y Flota: {e}")

    def refresh_if_dirty(self):
        """Llamado por MainWindow._trigger_load_data al navegar a este modulo.
        Sin pending_changes que proteger (vista de solo lectura): si quedo
        marcado dirty por un data_ready recibido mientras estaba oculto,
        recalcula ahora; si no, no hace nada (evita un load_data() de mas)."""
        if self._data_dirty:
            self.load_data()

    def _on_error(self, error_msg):
        print(f"Error al cargar Clientes y Flota: {error_msg}")

    def _on_logs_updated(self):
        """LogApp.csv se actualizó en RAM (DataManager.set_logs_df, ej. tras
        guardar un cambio en Comercial): repuebla únicamente el historial
        del VIN actualmente seleccionado, si hay uno -- no toca la ficha, no
        pierde la selección, no reconstruye clientes/flota/unidades (eso
        sigue siendo trabajo de data_ready/load_data)."""
        if self._vin_seleccionado:
            df_logs = self.data_manager.get_logs_df()
            self._render_historial_vin(self._filtrar_historial_por_vin(df_logs, self._vin_seleccionado))

    def _on_contactos_ready(self):
        # Si ya había un cliente seleccionado cuando Contactos terminó de
        # cargar en segundo plano, refresca su caja de "Contactos encontrados"
        # con los datos recién llegados en vez de dejarla vacía.
        if self._selected_cdb is not None:
            self._populate_contactos_encontrados(self._selected_cdb)

    # ==========================================
    # DIRECTOR DE EMPRESA: BBDD CLIENTES CM.xlsx (Power BI)
    # ==========================================
    def _load_pbi_director_empresa_async(self):
        # Si MainWindow ya lo precargó, se reutiliza en vez de leer de nuevo
        precarga = _precarga_director_pbi
        if precarga['mapa'] is not None:
            self._on_pbi_director_empresa_loaded(precarga['mapa'])
            return
        if precarga['hilo'] is not None and precarga['hilo'].isRunning():
            precarga['hilo'].data_loaded_signal.connect(self._on_pbi_director_empresa_loaded)
            return
        if not POWERBI_EXCEL_PATH or not os.path.exists(POWERBI_EXCEL_PATH):
            return
        self._pbi_director_empresa_thread = PowerBiDirectorEmpresaLoaderThread(POWERBI_EXCEL_PATH)
        self._pbi_director_empresa_thread.data_loaded_signal.connect(self._on_pbi_director_empresa_loaded)
        iniciar_hilo_retenido(self._pbi_director_empresa_thread)

    def _on_pbi_director_empresa_loaded(self, mapa_director_empresa):
        self._pbi_director_empresa_por_cdb = mapa_director_empresa
        # Igual que _on_contactos_ready: si ya había un cliente seleccionado
        # cuando Power BI terminó de cargar en segundo plano, refresca la
        # caja de "Contactos encontrados" para que muestre la tarjeta de
        # Director de empresa recién llegada en vez de esperar a una nueva
        # selección.
        if self._selected_cdb is not None:
            self._populate_contactos_encontrados(self._selected_cdb)
            self._refrescar_info_cliente_pbi(self._selected_cdb)

    def _refrescar_info_cliente_pbi(self, cdb):
        """Re-renderiza SOLO la caja "Información del cliente" con
        Dirección/Comuna una vez que Power BI termina de cargar (ver
        _on_pbi_director_empresa_loaded). No reutiliza _show_cliente_detalle
        completo a propósito: eso también resetea right_stack/detalle_view a
        "Resumen", perdiendo la pestaña en la que el usuario esté parado."""
        if getattr(self, '_info_cliente_base_args', None) is None:
            return
        if str(self._info_cliente_base_args[2]).strip() != str(cdb).strip():
            return
        director_empresa = self._pbi_director_empresa_por_cdb.get(str(cdb).strip(), {})
        self._render_info_cliente(
            *self._info_cliente_base_args,
            direccion=director_empresa.get('direccion', ''),
            comuna=director_empresa.get('comuna', ''),
        )

    @staticmethod
    def _construir_mapa_director_empresa_pbi(df_pbi):
        """CDB -> {'correo', 'telefono', 'direccion', 'comuna'} del
        "Director de empresas", leído desde BBDD CLIENTES CM.xlsx (Power BI,
        mismas columnas 'Correo electrónico'/'Teléfono'/'Dirección'/'Comuna'
        que usa PowerBiSyncWorker en contactos.py para la pestaña "Director
        de empresas (Power BI)" de ContactosModule). Es un dato de la
        EMPRESA (un registro por CDB en Power BI), no de cada contacto
        individual -- por eso se muestra aparte en una tarjeta resaltada
        (_create_director_empresa_card) en vez de pisar el correo propio de
        cada contacto de contactos.xlsx; Dirección/Comuna se muestran en la
        caja "Información del cliente" (_render_info_cliente). CDB
        normalizado con str().strip() (mismo criterio que el resto de
        General). Si un CDB aparece en varias filas, se conserva el primer
        valor no vacío de cada campo. Función pura (no usa self.*), fuente
        de solo lectura -- nunca se escribe en ese Excel."""
        mapa = {}
        if df_pbi.empty or 'CDB' not in df_pbi.columns:
            return mapa

        columnas_pbi = {
            'correo': 'Correo electrónico',
            'telefono': 'Teléfono',
            'direccion': 'Dirección',
            'comuna': 'Comuna',
        }
        columnas_presentes = {k: v for k, v in columnas_pbi.items() if v in df_pbi.columns}
        if not columnas_presentes:
            return mapa

        # Vectorizado (antes iterrows): corre en un hilo, pero un bucle Python
        # largo le quitaba el GIL a la UI mientras el usuario abría otro módulo
        def _normalizar(serie):
            v = serie.astype(str).str.strip().fillna('')
            return v.mask(v.str.lower().isin(('nan', 'none', '<na>')), '')

        datos = pd.DataFrame({k: _normalizar(df_pbi[col]).values for k, col in columnas_presentes.items()})
        datos = datos.mask(datos == '')
        datos['_cdb'] = _normalizar(df_pbi['CDB']).values
        datos = datos[datos['_cdb'] != '']

        # Por CDB, el primer valor no vacío de cada campo, en orden de aparición
        primeros = datos.groupby('_cdb', sort=False).first()
        for cdb, fila in zip(primeros.index, primeros.to_dict('records')):
            registro = {'correo': '', 'telefono': '', 'direccion': '', 'comuna': ''}
            registro.update({k: ('' if pd.isna(v) else v) for k, v in fila.items()})
            mapa[cdb] = registro

        return mapa

    @staticmethod
    def _build_clientes_df(df_comercial):
        """Un cliente por RUT (sin RUT utilizable, por razón social). Su razón
        social es la más frecuente entre sus filas."""
        if df_comercial.empty or COL_RAZON_SOCIAL not in df_comercial.columns:
            return pd.DataFrame(columns=COLUMNAS_CLIENTES)

        df = df_comercial.copy()
        df[COL_RAZON_SOCIAL] = df[COL_RAZON_SOCIAL].astype(str).str.strip()
        df = df[df[COL_RAZON_SOCIAL] != '']
        if df.empty:
            return pd.DataFrame(columns=COLUMNAS_CLIENTES)

        rut_serie = df[COL_RUT] if COL_RUT in df.columns else pd.Series('', index=df.index)
        df['_clave'] = comercial_services.clave_cliente_serie(rut_serie, df[COL_RAZON_SOCIAL])

        agg_dict = {COL_RAZON_SOCIAL: lambda s: s.value_counts().index[0]}
        if COL_RUT in df.columns: agg_dict[COL_RUT] = 'first'
        if COL_INDUSTRIA in df.columns: agg_dict[COL_INDUSTRIA] = 'first'
        if COL_CDB in df.columns: agg_dict[COL_CDB] = 'first'
        if COL_VIN in df.columns: agg_dict[COL_VIN] = 'count'

        grouped = df.groupby('_clave', as_index=False, sort=False).agg(agg_dict)
        grouped = grouped.rename(columns={
            '_clave': 'Clave', COL_RAZON_SOCIAL: 'Razón Social', COL_RUT: 'RUT',
            COL_INDUSTRIA: 'Industria/s', COL_CDB: 'CDB', COL_VIN: 'Total unidades',
        })

        # Texto de búsqueda: todas las razones sociales, el RUT sin formato y
        # el CDB de las filas del cliente
        rut_plano = rut_serie.astype(str).str.upper().str.replace(r'[\.\-\s]', '', regex=True)
        cdb_serie = df[COL_CDB].astype(str).str.strip() if COL_CDB in df.columns else pd.Series('', index=df.index)
        texto = (df[COL_RAZON_SOCIAL] + ' ' + rut_plano + ' ' + rut_serie.astype(str) + ' ' + cdb_serie).str.lower()
        busqueda = texto.groupby(df['_clave']).agg(lambda s: ' '.join(dict.fromkeys(s)))
        grouped['Busqueda'] = grouped['Clave'].map(busqueda).fillna('')

        # Flotas distintas por cliente (sin vacíos ni '-')
        if COL_FLOTA_VC in df.columns:
            flota = df[COL_FLOTA_VC].astype(str).str.strip()
            validas = ~flota.str.lower().isin(['', '-', 'nan', 'none', '<na>', *_FLOTA_VC_SIN_FLOTA])
            clave_flota = flota[validas].map(_clave_flota_texto)
            conteo = clave_flota.groupby(df.loc[validas, '_clave']).nunique()
            grouped['Total flotas'] = grouped['Clave'].map(conteo).fillna(0).astype(int)

        for col in COLUMNAS_CLIENTES:
            if col not in grouped.columns:
                grouped[col] = 0 if col in ('Total unidades', 'Total flotas') else ""

        return grouped[COLUMNAS_CLIENTES]

    @staticmethod
    def _calcular_claves_con_varias_razones(df_comercial):
        """Claves de cliente (por RUT) que aparecen con más de una razón
        social distinta en sus filas."""
        if df_comercial.empty or COL_RUT not in df_comercial.columns or COL_RAZON_SOCIAL not in df_comercial.columns:
            return set()
        razon = df_comercial[COL_RAZON_SOCIAL].astype(str).str.strip()
        clave = comercial_services.clave_cliente_serie(df_comercial[COL_RUT], razon)
        con_rut = clave.str.startswith('RUT:')
        if not con_rut.any():
            return set()
        conteo = razon[con_rut].groupby(clave[con_rut]).nunique()
        return set(conteo[conteo > 1].index)

    @staticmethod
    def _calcular_avisos_flota(df):
        """{clave de cliente: texto} de los clientes con datos de flota
        incoherentes: un CDB flota con varias Flota VC, una Flota VC con varios
        CDB flota, o unidades con solo uno de los dos datos."""
        if df.empty or '_clave_cliente' not in df.columns or COL_FLOTA_VC not in df.columns \
                or COL_CDB_FLOTA not in df.columns:
            return {}
        vacios = {'', 'NAN', 'NONE', '-', 'NAT', '<NA>'}
        cdb = df[COL_CDB_FLOTA].astype(str).str.strip().str.upper()
        flota = df[COL_FLOTA_VC].astype(str).str.strip().map(_clave_flota_texto)
        flota_vacia = flota.isin(vacios)
        cdb_ok = ~cdb.isin(vacios)
        flota_ok = ~flota_vacia & ~flota.str.lower().isin(_FLOTA_VC_SIN_FLOTA)
        clave = df['_clave_cliente']

        ambos = cdb_ok & flota_ok
        pares = pd.DataFrame({'clave': clave[ambos], 'cdb': cdb[ambos], 'flota': flota[ambos]})
        if pares.empty:
            cdb_varias = flota_varios = pd.Series(dtype=int)
        else:
            cdb_varias = (pares.groupby(['clave', 'cdb'])['flota'].nunique() > 1).groupby(level=0).sum()
            flota_varios = (pares.groupby(['clave', 'flota'])['cdb'].nunique() > 1).groupby(level=0).sum()
        incompletas = (cdb_ok ^ ~flota_vacia).groupby(clave).sum()

        avisos = {}
        for k in set(cdb_varias[cdb_varias > 0].index) | set(flota_varios[flota_varios > 0].index) \
                | set(incompletas[incompletas > 0].index):
            partes = []
            if cdb_varias.get(k, 0):
                partes.append(f"{int(cdb_varias[k])} CDB flota con varias Flota VC")
            if flota_varios.get(k, 0):
                partes.append(f"{int(flota_varios[k])} Flota VC con varios CDB flota")
            if incompletas.get(k, 0):
                partes.append(f"{int(incompletas[k])} unidad(es) con solo CDB flota o solo Flota VC")
            avisos[k] = "Revisar flotas: " + " · ".join(partes)
        return avisos

    @staticmethod
    def _build_unidades_df(df_comercial):
        """Listado general de unidades (caja izquierda, apartado "Unidades"):
        una fila por VIN, sin agrupar ni filtrar. Misma fuente que
        Cliente (df_comercial, ya procesado por
        comercial_services.procesar_df_comercial) -- no crea una fuente de
        datos nueva. Incluye Clave, CDB y Razón Social aunque no siempre se
        muestren, porque el detalle de la caja derecha reutiliza este mismo df."""
        if df_comercial.empty or COL_VIN not in df_comercial.columns:
            return pd.DataFrame(columns=COLUMNAS_UNIDADES)

        df = df_comercial.copy()

        def _normalizar_texto(val):
            if pd.isna(val):
                return ""
            v = str(val).strip()
            return "" if v.lower() in ['nan', 'none', '<na>'] else v

        rename_map = {
            COL_VIN: 'VIN', COL_CHASIS: 'CHASIS', COL_RAZON_SOCIAL: 'Razón Social',
            COL_CDB: 'CDB', COL_RUT: 'RUT', COL_FLOTA_VC: 'Flota VC', COL_ESTADO_ACTIVACION: 'Estado Activación',
            COL_INDUSTRIA: 'Industria/s', COL_ETAPA_GESTION: 'ETAPA GESTIÓN',
            COL_ESTADO_COMERCIAL: 'Estado Comercial', COL_FORMA_CONTRATO: 'Forma de Contrato',
            COL_TIPO_FACTURACION: 'Tipo de Facturación', COL_INICIO_CONTRATO: 'Inicio Contrato',
            COL_TERMINO_CONTRATO: 'Término Contrato', COL_PERIODO_INTERNO: 'Periodo Interno',
            COL_TIPO_SERVICIO: 'Tipo de Servicio', COL_CDB_FLOTA: 'CDB Flota',
        }
        cols_presentes = [c for c in rename_map if c in df.columns]
        df = df[cols_presentes].rename(columns=rename_map)
        for col in df.columns:
            df[col] = comercial_services.aplicar_por_valor_unico(df[col], _normalizar_texto)

        if 'RUT' in df.columns and 'Razón Social' in df.columns:
            df['Clave'] = comercial_services.clave_cliente_serie(df['RUT'], df['Razón Social'])

        for col in COLUMNAS_UNIDADES:
            if col not in df.columns:
                df[col] = ""

        return df[COLUMNAS_UNIDADES]

    def load_data(self):
        """Dispara GeneralDataPrepThread (procesar_df_comercial + los 3
        _build_*_df + listas de filtro, ver esa clase) en vez de calcularlo
        aca mismo de forma sincrona (auditoria de rendimiento, fase 4,
        21-09-2026). El snapshot (get_comercial_df() ya hace .copy()) se toma
        aca, en el hilo de UI, antes de pasarlo al worker.

        Guard de reentrancia: si ya hay un worker corriendo, no se lanza uno
        nuevo -- se marca _prep_pendiente y _on_prep_finished se encarga de
        volver a llamar load_data() (con el snapshot mas reciente) apenas
        el worker actual termine, para que un resultado viejo nunca pueda
        pisar a uno mas nuevo."""
        self._data_dirty = False

        if self._prep_en_curso:
            self._prep_pendiente = True
            return

        self._prep_en_curso = True
        for esqueleto in self._esqueletos():
            esqueleto.iniciar()
        snapshot = self.data_manager.get_comercial_df()
        self._prep_thread = GeneralDataPrepThread(snapshot)
        self._prep_thread.data_prepared_signal.connect(self._on_prep_finished)
        iniciar_hilo_retenido(self._prep_thread)

    def _on_prep_finished(self, resultado):
        """Hilo de UI: aplica el resultado de GeneralDataPrepThread. Mismo
        trabajo que antes hacia load_data() despues del calculo pesado
        (guardar los DataFrames, poblar listas de filtro con QListWidget, y
        construir las tarjetas), sin cambios de comportamiento."""
        self._prep_en_curso = False
        self.df_comercial_raw, self.df_clientes_base, self.df_unidades_base = resultado

        if COL_RUT in self.df_comercial_raw.columns and COL_RAZON_SOCIAL in self.df_comercial_raw.columns:
            self.df_comercial_raw = self.df_comercial_raw.assign(_clave_cliente=comercial_services.clave_cliente_serie(
                self.df_comercial_raw[COL_RUT], self.df_comercial_raw[COL_RAZON_SOCIAL]))
        self._clientes_con_varias_razones = self._calcular_claves_con_varias_razones(self.df_comercial_raw)
        self._clientes_aviso_flota = self._calcular_avisos_flota(self.df_comercial_raw)
        try:
            chk_avisos = self.chk_solo_avisos_flota
        except (AttributeError, RuntimeError):
            chk_avisos = None
        if chk_avisos is not None:
            chk_avisos.setText(f"Solo con aviso de flotas ({len(self._clientes_aviso_flota)})")

        self._poblar_filtros_unidades()

        self.filter_clientes()
        self.filter_unidades()

        try:
            if not self._primera_carga_emitida:
                self._primera_carga_emitida = True
                self.primera_carga_lista.emit()
        except (AttributeError, RuntimeError):
            # Instancias creadas con GeneralModule.__new__ (sin pasar por
            # __init__, ver TestLoadDataGuardDeReentrancia) no tienen el
            # QObject subyacente inicializado y no pueden emitir señales --
            # no aplica en producción, donde siempre se pasa por __init__.
            pass

        # En la app ya vienen precargadas desde MainWindow (pantalla de carga);
        # esto solo lee lo que falte
        if not self.__dict__.get('_cargas_secundarias_iniciadas', True):
            self._cargas_secundarias_iniciadas = True
            QTimer.singleShot(300, self._iniciar_cargas_secundarias)

        if self._prep_pendiente:
            # El esqueleto sigue a la vista hasta que termine la carga nueva
            self._prep_pendiente = False
            self.load_data()
        else:
            for esqueleto in self._esqueletos():
                esqueleto.terminar()

    def filter_clientes(self):
        if self.df_clientes_base.empty:
            self._df_clientes_visible = pd.DataFrame(columns=COLUMNAS_CLIENTES)
            self._render_clientes_cards(self._df_clientes_visible)
            self._sincronizar_seleccion_cliente(self._df_clientes_visible)
            return

        # El filtro de Industria se movió a la pestaña Unidades (junto a
        # Razón Social/Estado Activación, a pedido explícito 15-09-2026):
        # esta lista ya no filtra por Industria/s.
        df_f = self.df_clientes_base.copy()

        texto_busqueda = self.search_input.text()
        df_filtrado = self._aplicar_busqueda_clientes(df_f, texto_busqueda)
        claves_vin, self._vins_busqueda = self._claves_por_vin_buscado(texto_busqueda)
        if claves_vin:
            # Un VIN buscado también trae a su cliente
            df_f = df_f[df_f.index.isin(df_filtrado.index) | df_f['Clave'].astype(str).isin(claves_vin)]
        else:
            df_f = df_filtrado

        chk_avisos = getattr(self, 'chk_solo_avisos_flota', None)
        if chk_avisos is not None and chk_avisos.isChecked():
            df_f = df_f[df_f['Clave'].astype(str).isin(self._clientes_aviso_flota)]

        columna_orden = {'unidades': 'Total unidades', 'flotas': 'Total flotas'}.get(self._clientes_orden_campo, 'Razón Social')
        df_f = df_f.sort_values(by=columna_orden, ascending=self._clientes_orden_asc, na_position='last')
        df_f = df_f.reset_index(drop=True)

        # Fuente que usa _on_cliente_card_clicked/_sincronizar_seleccion_
        # cliente para mapear fila -> cliente.
        self._df_clientes_visible = df_f

        self._render_clientes_cards(df_f)
        self._sincronizar_seleccion_cliente(df_f)
        self._abrir_cliente_de_vin_buscado(df_f, claves_vin)

    def _claves_por_vin_buscado(self, texto_busqueda):
        """(claves de cliente, VIN encontrados) para los términos de la
        búsqueda que parecen un VIN (8 a 17 letras/dígitos). Con 17 caracteres
        el VIN debe coincidir completo; con menos, basta que lo contenga."""
        terminos = {t.upper() for t in re.split(r'[,\s;]+', texto_busqueda.strip()) if re.fullmatch(r'[A-Za-z0-9]{8,17}', t)}
        df = self.df_unidades_base
        if not terminos or df.empty or 'VIN' not in df.columns or 'Clave' not in df.columns:
            return set(), set()
        vins = df['VIN'].astype(str).str.strip().str.upper()
        completos = [t for t in terminos if len(t) == 17]
        parciales = [t for t in terminos if len(t) < 17]
        mascara = vins.isin(completos)
        for t in parciales:
            mascara |= vins.str.contains(t, regex=False)
        if not mascara.any():
            return set(), set()
        return set(df.loc[mascara, 'Clave'].astype(str)), set(vins[mascara])

    def _abrir_cliente_de_vin_buscado(self, df_visible, claves_vin):
        """Con un VIN en la búsqueda: abre el primer cliente que lo tiene y
        deja su pestaña Unidades a la vista (el VIN sale primero y resaltado,
        ver _populate_unidades_detalle)."""
        if not claves_vin or self.left_stack.currentIndex() != 0 or 'Clave' not in df_visible.columns:
            return
        for clave in df_visible['Clave'].astype(str):
            if clave in claves_vin:
                self._seleccionar_cliente_por_clave(clave)
                self._switch_detalle_view(1)
                return

    @staticmethod
    def _aplicar_filtros_unidades(df_unidades, filtros):
        """Deja las unidades que cumplen todos los filtros activos.
        `filtros`: {columna: None | conjunto de valores en mayúsculas}; None no
        filtra. Con un filtro activo, un valor vacío o '-' no coincide. Función
        pura (no usa self.*)."""
        df_f = df_unidades
        for columna, claves in filtros.items():
            if claves is None or columna not in df_f.columns:
                continue
            df_f = df_f[df_f[columna].astype(str).map(_clave_flota_texto).isin(claves)]
        return df_f

    def _poblar_filtros_unidades(self):
        for columna, boton in self._filtros_unidades.items():
            if columna in self.df_unidades_base.columns:
                boton.set_valores(FiltroValoresBoton.valores_distintos(self.df_unidades_base[columna]))
            else:
                boton.set_valores([])

    def _limpiar_filtros_unidades(self):
        for boton in self._filtros_unidades.values():
            boton.limpiar()
        self.filter_unidades()

    @staticmethod
    def _aplicar_busqueda_clientes(df, texto_busqueda):
        """Buscador global sobre la lista de Cliente: coincide con cualquiera
        de las razones sociales del cliente, su RUT (con o sin puntos y
        guion) o su CDB. Términos separados por coma se combinan con OR."""
        texto = texto_busqueda.strip().lower()
        if not texto or df.empty or 'Busqueda' not in df.columns:
            return df
        terminos = []
        for termino in texto.split(','):
            termino = termino.strip()
            plano = re.sub(r'[\.\-]', '', termino)
            terminos.append(plano if re.fullmatch(r'[0-9k]{5,}', plano) else termino)
        mascara = comercial_services.construir_mascara_busqueda(df, ','.join(terminos), ['Busqueda'])
        return df[mascara]

    @staticmethod
    def _aplicar_busqueda_unidades(df_unidades, texto_busqueda):
        """Buscador global de MainWindow (self.search_bar) sobre la caja
        izquierda -> Unidades: cada término puede coincidir en Razón Social,
        VIN, CDB o RUT (COLUMNAS_BUSQUEDA_UNIDADES) indistintamente. Reutiliza
        comercial_services.construir_mascara_busqueda (auditoria de
        rendimiento B-2, 18-09-2026) en vez del loop propio anterior
        (O(términos x columnas) con un .str.contains() por cada uno): medido
        ~1.4-1.9s al pegar 200 VINs (límite de MAX_TERMINOS_BUSQUEDA_GLOBAL
        en main_window.py) contra ~47ms de construir_mascara_busqueda para
        el mismo caso en comercial.py, que ya resuelve esto con una sola
        regex de alternancia por columna. Efecto colateral (bug real
        corregido, no solo de rendimiento): el loop anterior separaba solo
        por espacio, así que un texto pegado con comas (MultiSearchLineEdit
        pega listas separadas por coma) quedaba con las comas pegadas a cada
        VIN y los exigía todos con AND -- en la práctica 0 resultados al
        pegar más de un término. construir_mascara_busqueda interpreta ','
        como OR entre términos (igual que en comercial.py), por lo que pegar
        varios VINs ahora sí encuentra cada uno. Para un solo término o
        varias palabras sin coma (el caso de tipeo normal) el resultado es
        idéntico al de antes: AND entre esas palabras, OR entre columnas.
        Función pura (no usa self.*): no modifica df_unidades ni el
        DataFrame original, devuelve una copia filtrada."""
        texto = texto_busqueda.strip().lower()
        if not texto or df_unidades.empty:
            return df_unidades

        columnas = [c for c in COLUMNAS_BUSQUEDA_UNIDADES if c in df_unidades.columns]
        if not columnas:
            return df_unidades

        mask = comercial_services.construir_mascara_busqueda(df_unidades, texto, columnas)
        return df_unidades[mask]

    def filter_table(self):
        """Punto de enganche del buscador global de MainWindow
        (self.search_bar en main_window.py): MainWindow detecta
        search_input + filter_table vía hasattr y llama esto después de
        fijarle el texto (ver MainWindow._on_global_search). Reaplica el
        filtrado de las 2 sub-pestañas de la caja izquierda (Cliente/Unidades):
        Cliente busca en todas sus razones sociales, RUT y CDB (ver
        _aplicar_busqueda_clientes) y Unidades en Razón Social, VIN, CDB o RUT
        (ver COLUMNAS_BUSQUEDA_UNIDADES). Nunca toca
        ningún estado de la caja derecha (selección de cliente/CDB, KPIs,
        Contactos, filtros), que sigue su propio ciclo de vida independiente
        del buscador."""
        self._animar_carga_breve(solo_izquierda=True)
        self.filter_clientes()
        self.filter_unidades()

    def filter_unidades(self):
        if self.df_unidades_base.empty:
            self._df_unidades_visible = pd.DataFrame(columns=COLUMNAS_UNIDADES)
            self._render_unidades_cards(self._df_unidades_visible)
            self._vin_seleccionado = None
            self._show_vin_vacio()
            return

        filtros = {columna: boton.seleccion() for columna, boton in self._filtros_unidades.items()}
        df_f = self._aplicar_filtros_unidades(self.df_unidades_base, filtros)
        df_f = self._aplicar_busqueda_unidades(df_f, self.search_input.text())

        columna = self._unidades_orden_columna
        if columna and columna in df_f.columns:
            # Vacíos y '-' van siempre al final
            df_f = df_f.assign(_orden=df_f[columna].astype(str).str.strip().replace({'': None, '-': None}))
            df_f = df_f.sort_values(by=['_orden', 'Razón Social', 'VIN'],
                                    ascending=[self._unidades_orden_asc, True, True], na_position='last')
            df_f = df_f.drop(columns='_orden')
        else:
            df_f = df_f.sort_values(by=['Razón Social', 'VIN'], ascending=self._unidades_orden_asc, na_position='last')
        df_f = df_f.reset_index(drop=True)

        # Fuente que usa _on_unidad_card_clicked/_sincronizar_seleccion_vin
        # para mapear fila -> VIN (mismo rol que _df_clientes_visible para Cliente).
        self._df_unidades_visible = df_f

        self._render_unidades_cards(df_f)
        self._sincronizar_seleccion_vin()

    def _populate_unidades_detalle(self, clave):
        """Caja derecha, apartado "Unidades": las unidades del cliente
        seleccionado (identificado por su clave, ver _clave_cliente), desde
        self.df_unidades_base. CDB/Razón Social se ocultan en esta tabla
        porque ya son contexto conocido."""
        if 'Clave' in self.df_unidades_base.columns:
            df_f = self.df_unidades_base[self.df_unidades_base['Clave'].astype(str) == str(clave)]
        else:
            df_f = self.df_unidades_base.iloc[0:0]
        # El CDB flota principal se calcula sobre todas las unidades del cliente, aunque se filtre por flota
        cdb_principal = ""
        if 'CDB Flota' in df_f.columns:
            cdbs = df_f['CDB Flota'].astype(str).str.strip()
            cdbs = cdbs[~cdbs.str.lower().isin(['', 'nan', 'none', '-'])]
            if not cdbs.empty:
                cdb_principal = cdbs.value_counts().index[0]
        flota_filtro = getattr(self, '_flota_filtro_detalle', None)
        if hasattr(self, 'fila_filtro_flota_detalle'):
            self.fila_filtro_flota_detalle.setVisible(bool(flota_filtro))
            self.lbl_filtro_flota_detalle.setText(f"Flota VC: {flota_filtro}" if flota_filtro else "")
        if flota_filtro and 'Flota VC' in df_f.columns:
            df_f = df_f[df_f['Flota VC'].astype(str).map(_clave_flota_texto) == _clave_flota_texto(flota_filtro)]
        # Caja derecha (detalle por CDB): fuera de alcance del cambio de
        # Unidades de la caja izquierda (10-09-2026) -- se excluyen
        # 'Industria/s' y 'ETAPA GESTIÓN' explícitamente para que esta tabla
        # siga mostrando exactamente las mismas columnas de antes.
        cols_detalle = [c for c in COLUMNAS_UNIDADES
                         if c not in ('CDB', 'Razón Social', 'RUT', 'Industria/s', 'ETAPA GESTIÓN', 'Tipo de Servicio', 'Clave')]
        df_display = df_f[cols_detalle].reset_index(drop=True)
        if 'Estado Activación' in df_display.columns:
            estado = df_display['Estado Activación'].astype(str).str.strip().str.upper()
            vacios = estado.isin(['', '-', 'NAN', 'NONE'])
            buscados = ~df_display['VIN'].astype(str).str.strip().str.upper().isin(getattr(self, '_vins_busqueda', set()))
            df_display = df_display.assign(_buscado=buscados, _vacio=vacios, _estado=estado) \
                .sort_values(['_buscado', '_vacio', '_estado'], kind='stable') \
                .drop(columns=['_buscado', '_vacio', '_estado']).reset_index(drop=True)
        self._pintar_unidades_detalle(df_display, cdb_principal)
