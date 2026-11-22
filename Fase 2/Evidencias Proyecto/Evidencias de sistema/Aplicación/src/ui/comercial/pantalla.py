"""Pantalla Comercial: bandejas por sub-pestaña, tarjetas KPI, ficha de unidad y acciones rápidas."""
from src.theme.colors import BACKGROUND, DANGER, PRIMARY, SUCCESS, TEXT_SECONDARY, WARNING
import pandas as pd
import qtawesome as qta
import os
from datetime import datetime
from PyQt6.QtWidgets import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QMessageBox, QLineEdit, QListWidget, QListWidgetItem, QHeaderView, QTextEdit, QApplication, QTabWidget, QTabBar, QAbstractItemView, QScrollArea, QGridLayout, QCheckBox, QSpinBox, QFileDialog
from PyQt6.QtCore import Qt, QSize, QTimer, QStandardPaths, QPropertyAnimation, QDate
from PyQt6.QtGui import QFont
from src.services import comercial_services
from src.services import cm_bajas_service
from src.services.powerbi_import_service import trae_volvo_connect
from src.services import contratos_service as ct_service
from src.services import mail_sync_service
from src.services import mail_service
from src.services import contactos_service
from src.ui.compartido.mail_dialog import MailDialog
from src.ui.comercial_agregar import ComercialUnidadFormWidget
from src.ui.ayuda.importar_powerbi import cerrar_paneles_importacion, iniciar_importacion_power_bi
from src.ui.administracion.contactos_agregar import ContactosAddDialog
from src.ui.administracion.contactos import AddContactoThread
from src.ui.compartido.custom_table import VolvoTableWidget, PandasTableModel
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.transiciones import TransicionFundidoSubida, capturar
from src.ui.compartido.panel_ubicacion_vin import PanelUbicacionVin
from src.ui.compartido.esqueleto_carga import animar_sobre_tabla
from src.ui.compartido.guardado_overlay import mostrar_guardando, guardado_listo, terminar_guardando
from src.ui.compartido.dialogo_accion import DialogoAccion
from src.ui.compartido.copiar import hacer_copiable, escribir_portapapeles
from src.ui.ingresos.base import PantallaIngresosBase
from src.ui.compartido.selector_fecha import SelectorFecha
from src.theme.theme_manager import ThemeManager
import config.settings
from src.core.dataframe_formatter import DataFrameFormatter
from src.core.constants import COL_ESTADO_COMERCIAL, ESTADO_CM_PENDIENTE, VALOR_ESTADO_COMERCIAL_BAJA, VALOR_ESTADO_COMERCIAL_BAJA_SOLICITADA, COL_ETAPA_GESTION, VALOR_ESTADO_COMERCIAL_VENCIDO, COL_ID, ESTADOS_COMERCIAL_CORREGIBLES_A_VENCIDO, COL_TIPO_FACTURACION, COL_FORMA_CONTRATO, COL_ESTADO_ACTIVACION, VALOR_TIPO_FACT_SIN_REGISTRO, VALOR_ESTADO_COMERCIAL_VIGENTE, COL_RAZON_SOCIAL, COL_CHASIS, VALOR_TIPO_FACT_CLIENTE, VALOR_TIPO_FACT_FACTURACION_MANUAL
from src.ui.comercial.panel_kpi import _PanelKpiComercialMixin
from src.ui.comercial.revision_cm import _RevisionCmComercialMixin
from src.ui.comercial.periodo import _PeriodoFiltrosComercialMixin
from src.ui.comercial.busqueda_vin import _BusquedaVinComercialMixin
from src.ui.comercial.base import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    logger,
    SaveExcelThread,
    AddRowThread,
    AddRowRenovacionThread,
    AddRowsRenovacionThread,
    EnviarPapeleraThread,
    COLUMNAS_BUSQUEDA_COMERCIAL,
    COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL,
    COLUMNAS_BUSQUEDA_REVISION_CM,
    COMERCIAL_COL_WIDTH_RAZON_SOCIAL,
    NEW_UI_COL_WIDTH_MINIMO,
    COMERCIAL_COLUMNAS_AJUSTE_TEXTO,
    COMERCIAL_NEW_UI_ROW_HEIGHT,
    ACCION_RAPIDA_BUTTON_STYLE_DEFAULT,
    _NEW_UI_COL_WIDTH_PADDING,
    _NEW_UI_CHASIS_MUESTRA,
    NEW_UI_SUBTAB_COLUMN_WIDTHS,
    _FiltroAnchoViewport,
    _aplicar_anchos_columnas_new_ui,
    _formatear_pago_cm_para_mostrar,
)
from src.ui.comercial.legacy import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    _ComercialModuleLegacy,
)
from src.ui.comercial.dialogos import (  # noqa: F401 (se reexportan: otros módulos y los tests los importan desde aquí)
    DialogoAccionCm,
)
from src.ui.comercial.unidad_nueva import _UnidadNuevaComercialMixin
from src.ui.comercial.ficha import _FichaComercialMixin
from src.ui.comercial.acciones_build import _ArmadoAccionesComercialMixin
from src.ui.comercial.acciones_unidad import _AccionesUnidadComercialMixin
from src.ui.comercial.acciones_estado import _AccionesEstadoComercialMixin
from src.ui.comercial.arreglos import _ArreglosComercialMixin
from src.ui.comercial.renovar import _RenovarComercialMixin
from src.ui.comercial.vista_grupos import _VistaGruposComercialMixin
from src.ui.comercial.gestion_cm import _GestionCmComercialMixin


# =========================================================
# CONTENEDOR DE PESTAÑAS COMERCIAL
# =========================================================
class ComercialModule(_UnidadNuevaComercialMixin, _FichaComercialMixin, _ArmadoAccionesComercialMixin, _AccionesUnidadComercialMixin, _AccionesEstadoComercialMixin, _ArreglosComercialMixin, _RenovarComercialMixin, _VistaGruposComercialMixin, _GestionCmComercialMixin, _PanelKpiComercialMixin, _RevisionCmComercialMixin, _PeriodoFiltrosComercialMixin, _BusquedaVinComercialMixin, QWidget):
    """Módulo Comercial: la bandeja con sus sub-pestañas y la pestaña "Gestión
    de unidades".

    Los datos (df_base, DataManager, escritor) viven en self.legacy, un
    _ComercialModuleLegacy oculto. Los accesos que no pertenecen a este
    contenedor (load_data, refresh_if_dirty, df_base, etc.) se reenvían a
    self.legacy vía __getattr__/__setattr__.
    """

    # Columnas de la bandeja de la Nueva interfaz, configuradas por sub-pestaña
    # (config aprobada con el usuario: máx. 6 columnas, informativas para esa
    # vista puntual — VIN queda fuera de las 4 vistas a propósito, pero sigue
    # disponible en self.legacy.df_base para el buscador global). No un
    # dataset ni una carga aparte de self.legacy.df_base. Se dejan con el
    # mismo nombre que trae df_base (mayúsculas) porque PandasTableModel
    # colorea celdas como "ESTADO COMERCIAL" comparando ese nombre exacto de
    # columna. "DÍAS RESTANTES" es la única columna calculada (ver
    # _refresh_new_ui_data): no viene de df_base, se agrega en memoria a
    # partir de comercial_services.clasificar_vigencia_contrato().
    # "Gestionar CM" (antes "Revisión CM") no sale de
    # df_base/PruebasFM como las otras: sale de CasosBajaCM.csv (ver
    # _construir_df_revision_cm). Se usan los nombres de columna reales de
    # cm_bajas_service.CASOS_BAJA_CM_COLUMNS (p.ej. "ESTADO_CASO", no
    # "ESTADO CASO") para no inventar un alias. "MOTIVO" es la única columna
    # calculada de esta sub-pestaña: traduce ORIGEN_CASO
    # (AUSENCIA_3PC/ESTADO_EXPIRED, valores técnicos) a texto amigable
    # ("Ausente de 3PC"/"Contrato expirado") vía
    # cm_bajas_service.ORIGEN_CASO_MOTIVO_MAP -- ORIGEN_CASO en sí no se
    # muestra como columna aparte para no duplicar la misma información.
    # Orden de sub-pestañas (28-09-2026, a pedido explícito): Por gestionar,
    # Renovaciones, Gestionar Bajas (antes "Vencidos"), Vigentes, Ofrecer y
    # reactivar (antes "Gestionar Bajas"), Gestionar CM. Ver los .addTab(...)
    # en _build_new_ui_tab para el orden visual real.
    # EJECUTIVO (0/1/2), ETAPA GESTIÓN (0) y OBSERVACIONES (2) se sacaron de
    # estas listas a pedido del usuario (14-09-2026): quedan ocultas solo en
    # esta bandeja visual -- siguen existiendo en df_base/self.legacy.df_base
    # y en cualquier lógica que las use (filtros de negocio, etc.),
    # que trabajan sobre df_base ANTES de este recorte a columnas
    # visibles (ver _refresh_new_ui_data).
    NEW_UI_SUBTAB_COLUMNS = {
        2: ["RAZÓN SOCIAL", "CHASIS", "MODELO", "FORMA DE CONTRATO", "ESTADO COMERCIAL"],
        # "Renovar clientes": fusión (a pedido explícito) de Renovaciones, Gestionar
        # Bajas (vencidos) y Vigentes; columnas provisorias a redefinir.
        0: ["RAZÓN SOCIAL", "CHASIS", "MODELO", "TIPO DE SERVICIO", "FORMA DE CONTRATO", "INICIO CONTRATO", "TÉRMINO CONTRATO", "ESTADO COMERCIAL", "ESTADO DE ACTIVACIÓN ACTUAL"],
        1: ["RAZÓN SOCIAL", "CHASIS", "MODELO", "TIPO DE SERVICIO", "ESTADO DE ACTIVACIÓN ACTUAL", "FECHA DE BAJA"],
        # Dentro de una flota (fase 2) las mismas columnas que Contratos (CM), más el motivo del caso
        3: ["GESTIÓN", "ACTIVACIÓN", "ESTADO COMERCIAL", "CHASIS", "FECHA INICIO CM", "FECHA TERMINO CM", "TIPO DE CM",
            "ESTADO DEL CM", "PAGO CM", "ULTIMO PAGO CM", "FECHA ULTIMO PAGO CM"],
    }

    # Índice de la sub-pestaña "Gestionar Bajas" (antes "Vencidos") dentro de
    # new_ui_subtabs -- la única, junto con "Gestionar CM", con un panel de
    # acciones rápidas propio además del común (ver
    # _toggle_acciones_rapidas_panel).
    _NEW_UI_SUBTAB_RENOVAR_CLIENTES = 0

    # Índice de la sub-pestaña "Gestionar CM" (antes "Revisión CM") dentro de
    # new_ui_subtabs. Vive aparte (no en _NEW_UI_SUBTAB_FILTERS) porque su
    # fuente de datos es CasosBajaCM.csv, no df_base -- no encaja en el
    # contrato "filtro(df_base) -> subset de df_base" que usan las otras.
    _NEW_UI_SUBTAB_REVISION_CM = 3

    # Pseudo sub-pestaña mientras un aviso (inconsistencias / fechas) está
    # activo: la bandeja muestra esas unidades de toda la base y solo
    # quedan las acciones rápidas comunes
    _NEW_UI_SUBTAB_AVISOS = -1
    _COLUMNAS_BANDEJA_FECHAS = [
        "RAZÓN SOCIAL", "CHASIS", "ESTADO COMERCIAL", "INICIO CONTRATO", "DURACIÓN (MESES)", "TÉRMINO CONTRATO",
        "TÉRMINO EN ARCHIVO",
    ]
    _COLUMNAS_BANDEJA_INCONSISTENCIAS = [
        "RAZÓN SOCIAL", "CHASIS", "ESTADO COMERCIAL", "ESTADO DE ACTIVACIÓN ACTUAL", "FORMA DE CONTRATO", "TIPO DE FACTURACION",
    ]

    # Índices donde "Enviar a operaciones" no corresponde (confirmado con el
    # usuario, 23-09-2026) y queda deshabilitado (ver
    # _actualizar_estado_acciones_rapidas):
    # - "Por gestionar": el camino correcto es Editar Unidad, que ya deriva
    #   la unidad a Operaciones solo vía la matriz de negocio
    #   (ESTADO_COMERCIAL_ACTIVACION_ETAPA_MATRIZ). Usar el botón aquí
    #   marcaría por error ESTADO COMERCIAL = Baja sobre una unidad que en
    #   realidad está entrando en activación, no dándose de baja.
    # - "Gestionar CM": ya tiene su propia acción real ("Confirmar baja",
    #   ver _on_accion_cm_confirmar_baja_clicked); no corresponde además
    #   marcar ESTADO COMERCIAL = Baja con este botón.
    _NEW_UI_SUBTAB_POR_GESTIONAR = 2

    # Columna por la que se agrupa cada sub-pestaña: "Por gestionar" por
    # RAZÓN SOCIAL, las demás por FLOTA VC. Al elegir un grupo la bandeja
    # lista sus unidades con las columnas de NEW_UI_SUBTAB_COLUMNS.
    _NEW_UI_SUBTAB_NOMBRES = ("Renovar contratos", "Recuperar clientes", "Nuevas oportunidades", "Oportunidades CM")
    _NEW_UI_SUBTABS_AGRUPADAS_POR_RAZON_SOCIAL = {_NEW_UI_SUBTAB_POR_GESTIONAR}
    _NEW_UI_VALOR_SIN_GRUPO = "(Sin dato)"
    _NEW_UI_COL_UNIDADES = "UNIDADES"
    _NEW_UI_COL_VOLVO_CONNECT = "VOLVO CONNECT"
    _NEW_UI_COL_CON_VOLVO_CONNECT = "CON VOLVO CONNECT"
    _NEW_UI_COL_DEVUELTO = "DEVUELTO"
    _NEW_UI_COL_DEVUELTAS = "DEVUELTAS"
    _NEW_UI_ANCHOS_VISTA_GRUPOS = {'FLOTA VC': 300, 'RAZÓN SOCIAL': 380}

    # Índice de "Vigentes": única sub-pestaña donde "Enviar a operaciones"
    # representa una baja ANTICIPADA (siniestro u otro problema, unidad
    # todavía Conectada y con contrato vigente) en vez de una baja por
    # vencimiento/rechazo de renovación -- ver
    # _on_accion_enviar_operaciones_clicked, que por eso fija BAJA SOLICITADA
    # en vez de BAJA directo solo para este caso.
    
    # Índice de "Ofrecer y reactivar" (antes "Gestionar Bajas") -- ver
    # _on_accion_editar_unidad_clicked, que activa el mismo modo de edición
    # restringida que "Por gestionar" (caso "cliente interesado en volver").
    _NEW_UI_SUBTAB_OFRECER_REACTIVAR = 1

    # Plantilla que "Enviar correo" deja preseleccionada en cada sub-pestaña
    # (Renovar contratos no preselecciona ninguna).
    _PLANTILLA_CORREO_POR_SUBTAB = {
        _NEW_UI_SUBTAB_OFRECER_REACTIVAR: mail_service.PLANTILLA_REACTIVACION,
        _NEW_UI_SUBTAB_POR_GESTIONAR: mail_service.PLANTILLA_CONOCE_VOLVO_CONNECT,
        _NEW_UI_SUBTAB_REVISION_CM: mail_service.PLANTILLA_AVISO_VENCIMIENTO,
    }

    # Índice de "Renovaciones" -- único uso: calcular_kpis_renovaciones/
    # obtener_masks_kpi_renovaciones necesitan además self.legacy.
    # data_manager.get_contactos_df() (para la tarjeta "Sin contactos"), a
    # diferencia del resto de sub-pestañas (ver _refresh_new_ui_data).
    
    # Filtro de negocio real por cada sub-pestaña de new_ui_subtabs (mismo
    # orden en que se agregan en _build_new_ui_tab). "Ofrecer y reactivar"
    # (antes "Bajas"/"Gestionar Bajas") aqui es exclusivamente ESTADO
    # COMERCIAL = BAJA -- Bajas CM es un proceso aparte y NO debe mezclarse
    # en esta pestaña (ver auditoria).
    _NEW_UI_SUBTAB_FILTERS = {
        2: comercial_services.filtrar_por_gestionar,   # "Nuevas oportunidades"
        0: comercial_services.filtrar_renovar_clientes, # "Renovar clientes"
        1: comercial_services.filtrar_gestionar_bajas, # "Recuperar clientes" (NO Bajas CM)
    }

    # Función que calcula los KPI de cada sub-pestaña (25-09-2026, a pedido
    # explícito: antes las 6 sub-pestañas mostraban siempre las mismas 4
    # tarjetas de calcular_kpis_vigencia(), sin relación con la regla de
    # negocio real de cada una -- ver comercial_services.py, sección "KPI
    # POR SUB-PESTAÑA"). Recibe la bandeja ya filtrada (df_bandeja en
    # _refresh_new_ui_data) y devuelve un dict {clave: valor} que debe
    # calzar con las claves de _NEW_UI_KPI_SPECS para ese mismo índice.
    _NEW_UI_KPI_FUNCS = {
        2: comercial_services.calcular_kpis_por_gestionar,
        0: comercial_services.calcular_kpis_renovar_clientes,
        1: comercial_services.calcular_kpis_gestionar_bajas,
        3: comercial_services.calcular_kpis_gestionar_cm,
    }

    # Contenido de las 4 tarjetas KPI por sub-pestaña: (clave, título,
    # icono, color de fondo del icono, color de texto, tooltip, subtítulo
    # opcional). Las claves deben calzar exactamente con las que devuelve
    # la función correspondiente en _NEW_UI_KPI_FUNCS -- ver
    # _aplicar_kpi_spec_actual. Las tarjetas cuya clave aparece en
    # _NEW_UI_KPI_FILTRABLE_KEYS (28-09-2026, a pedido explícito) son
    # clicables y filtran la tabla -- ver _on_new_ui_kpi_card_clicked.
    _NEW_UI_KPI_SPECS = {
        2: [  # "Nuevas oportunidades" (antes "Por gestionar")
            ("total", "UNIDADES POTENCIALES", "fa5s.tasks", "#D1FAE5", SUCCESS,
             "Unidades con ESTADO DE ACTIVACIÓN ACTUAL = No aplica.", "unidades por gestionar"),
            ("volvo_connect", "CON VOLVO CONNECT", "fa5s.satellite-dish", "#FEF3C7", "#92400E",
             "Unidades que el reporte Notas de Venta marcó con Conectividad = SI al importarlas: gestionarlas primero.",
             "según Notas de Venta"),
            ("clientes_totales", "CLIENTES TOTALES", "fa5s.building", "#DBEAFE", PRIMARY,
             "Número de RAZÓN SOCIAL distintas dentro de esta bandeja.", "cartera de oportunidades"),
            ("contactados", "CLIENTES CONTACTADOS", "fa5s.envelope", "#FEF3C7", WARNING,
             "Clientes con algún correo registrado en Historial_Envios_VC.csv en los últimos 14 días."),
            ("sin_gestionar", "CLIENTES SIN GESTIONAR", "fa5s.user-clock", "#FEE2E2", DANGER,
             "Clientes sin ningún correo registrado en los últimos 14 días (incluye los que no tienen correo cargado)."),
        ],
        0: [  # "Renovar contratos"
            ("total", "TOTAL DE FLOTA", "fa5s.sync-alt", "#DBEAFE", "#64748B",
             "Unión de Renovaciones, Vencidos y Vigentes.", "unidades en cartera"),
            ("vencidas", "UNIDADES VENCIDAS", "fa5s.calendar-times", "#FEE2E2", DANGER,
             "ESTADO COMERCIAL = Vencido o TÉRMINO CONTRATO ya vencido."),
            ("por_vencer", "VENCEN EN 30 DÍAS", "fa5s.exclamation-triangle", "#FEF3C7", WARNING,
             "Unidades vigentes y conectadas cuyo TÉRMINO CONTRATO vence dentro de los próximos 30 días."),
            ("vigentes", "VIGENTES", "fa5s.check-circle", "#D1FAE5", SUCCESS,
             "Unidades Vigente o Activación Pendiente con contrato al día."),
        ],
        1: [  # "Recuperar clientes" (antes "Gestionar Bajas")
            ("total", "UNIDADES POTENCIALES", "fa5s.user-slash", "#D1FAE5", SUCCESS,
             "Unidades con ESTADO COMERCIAL = Baja.", "unidades dadas de baja"),
            ("clientes_totales", "CLIENTES TOTALES", "fa5s.building", "#DBEAFE", PRIMARY,
             "Número de RAZÓN SOCIAL distintas dentro de esta bandeja.", "cartera de oportunidades"),
            ("contactados", "CLIENTES CONTACTADOS", "fa5s.envelope", "#FEF3C7", WARNING,
             "Clientes con algún correo registrado en Historial_Envios_VC.csv en los últimos 14 días."),
            ("sin_gestionar", "CLIENTES SIN GESTIONAR", "fa5s.user-clock", "#FEE2E2", DANGER,
             "Clientes sin ningún correo registrado en los últimos 14 días (incluye los que no tienen correo cargado)."),
        ],
        3: [  # "Oportunidades CM" (antes "Gestionar CM")
            ("clientes_afectados", "CLIENTES AFECTADOS", "fa5s.building", "#E2E8F0", "#64748B",
            "Razones sociales distintas con casos pendientes (ausentes del 3PC, expirados y terminados sin pago).", "con CM por gestionar"),
            ("total", "UNIDADES CM", "fa5s.clipboard-list", "#E2E8F0", "#64748B",
             "Casos pendientes de CasosBajaCM.csv: ausentes del 3PC, expirados y terminados sin pago.", "por gestionar"),
            ("pendientes", "PENDIENTES", "fa5s.hourglass-half", "#EDE9FE", "#6D28D9",
             "Unidades con ESTADO DEL CM = Pendiente: no pagaron y se espera la respuesta de quien administra el CM."),
            ("datos_vacios", "3PC VACÍO", "fa5s.file-alt", "#FEF3C7", WARNING,
             "Contratos CM Vigentes o Vencidos que no traen ningún dato del 3PC (N° de contrato ni estado del CM).",
             "Vigente/Vencidos"),
            ("sin_pago", "TÉRMINO SIN PAGO", "fa5s.hand-holding-usd", "#FEE2E2", DANGER,
             "Contratos que el 3PC aún trae como Running, sin pago este mes, cuyo término ya venció o vence en los próximos 7 días.",
             "Running sin pago"),
            ("expired", "EXPIRED", "fa5s.calendar-times", "#FEE2E2", DANGER,
             "Unidades con ESTADO DEL CM = Expired: el contrato CM llegó a su fin y sigue por gestionar."),
        ],
    }

    # Claves clicables (filtran la tabla) por sub-pestaña -- estático, no se
    # deriva en runtime de las funciones de máscara para no tener que
    # invocarlas solo para conocer sus keys. "Oportunidades CM" (3) se
    # volvió clicable el 05-10-2026, a pedido explícito.
    _NEW_UI_KPI_FILTRABLE_KEYS = {
        0: {'total', 'vencidas', 'por_vencer', 'vigentes'},
        2: {'contactados', 'sin_gestionar', 'total', 'volvo_connect'},
        1: {'contactados', 'sin_gestionar', 'total'},
        3: {'datos_vacios', 'sin_pago', 'expired', 'total', 'pendientes'},
    }

    # Función que calcula las máscaras booleanas por fila detrás de cada
    # tarjeta clicable (mismas funciones que ya usa comercial_services.py
    # para las tarjetas -- ver _NEW_UI_KPI_FUNCS). Se aplican sobre
    # df_bandeja en _refresh_new_ui_data al hacer clic en una tarjeta.
    _NEW_UI_KPI_MASK_FUNCS = {
        0: comercial_services.obtener_masks_kpi_renovar_clientes,
        2: comercial_services.obtener_masks_kpi_por_gestionar,
        1: comercial_services.obtener_masks_kpi_gestionar_bajas,
        3: comercial_services.obtener_masks_kpi_gestionar_cm,
    }

    # Orden por defecto (sin clic manual) del bloque de unidades YA vencidas
    # dentro de "DÍAS RESTANTES": el más vencido va primero. Antes existía
    # una excepción para la sub-pestaña "Vencimientos" (eliminada
    # 14-09-2026); sin esa sub-pestaña no queda ninguna excepción.
    _NEW_UI_VENCIDOS_RECIENTES_PRIMERO = set()

    _OWN_ATTRS = {
        '_panel_ubicacion_vin', '_ubicacion_vin_destino', '_grupo_abierto_por_busqueda',
        'legacy', 'tabs', 'new_ui_tab', 'new_ui_table', 'new_ui_model', 'new_ui_kpi_labels', 'new_ui_subtabs',
        '_new_ui_kpi_cards', '_new_ui_kpi_filtro_por_subtab',
        'new_ui_search_input', 'acciones_rapidas_comunes', 'acciones_rapidas_cm', 'acciones_rapidas_vencidos',
        'acciones_rapidas_vigentes', '_grilla_acciones_vencidos', 'acciones_rapidas_papelera', 'btn_accion_papelera',
        'acciones_rapidas_conversion', '_grilla_maestra', 'btn_accion_a_conversion', '_a_conversion_thread', '_renovacion_multiple_thread',
        'btn_accion_cm_enviar_correo', 'btn_accion_editar_unidad', 'btn_accion_agregar_contacto',
        'btn_accion_enviar_operaciones', 'btn_accion_cm_confirmar_baja', 'btn_accion_cm_exportar_lista',
        'btn_accion_cm_pasar_a_cm', 'btn_accion_cm_limpiar', '_cambios_cm_thread',
        '_layout_tabla_bandeja',
        '_grupo_revision_barra', '_grupo_acciones_barra',
        'btn_accion_marcar_vencido', 'btn_accion_renovar', 'btn_accion_ver_general', 'btn_accion_crear_contrato',
        'btn_accion_marcar_vigente', 'acciones_rapidas_inconsistencias', 'btn_accion_arreglar_tipo_fact',
        'btn_accion_asignar_tipo_fact', 'btn_accion_asignar_tipo_fact_manual',
        'acciones_rapidas_fechas', 'btn_accion_fecha_real', 'btn_arreglar_fechas_barra', '_arreglar_fechas_thread',
        # "Unidad nueva" (25-09-2026, refactor: alta/edición de unidades
        # centralizada en Comercial, ver _build_unidad_nueva_tab).
        'unidad_nueva_tab', 'unidad_nueva_form', 'btn_unidad_nueva_importar_powerbi',
        'btn_unidad_nueva_restablecer',
        '_unidad_nueva_vin_en_edicion', '_unidad_nueva_datos_originales', '_unidad_nueva_restricciones',
        '_unidad_nueva_reactivacion_multiple', '_unidad_nueva_edicion_multiple', '_editar_multiple_thread',
        '_add_unidad_thread', '_importar_powerbi_worker', '_unidad_nueva_form_layout',
        'btn_accion_renovar_nuevo', '_unidad_nueva_renovacion', '_renovacion_thread',
        '_unidad_nueva_loading_lbl',
        # Rediseño visual (comercial_estilo.py)
        'selector_pestanas', '_delegado_celdas', 'btn_ampliar_bandeja',
        '_new_ui_kpi_contenedor', '_new_ui_contenido', '_transicion_kpis', '_transicion_contenido',
        '_ficha', 'txt_observaciones', 'btn_guardar_observaciones', '_observaciones_vin',
        '_observaciones_thread', '_vin_a_reseleccionar',
        '_panel_acciones', '_anim_panel_acciones', '_panel_acciones_abierto', 'btn_cerrar_panel_acciones',
        '_barra_bandeja', '_badges_subtabs',
        '_new_ui_grupo_abierto', '_new_ui_en_grupos', '_new_ui_grupos_df', 'btn_volver_grupos', 'lbl_grupo_abierto', 'lbl_titulo_bandeja', 'btn_unidad_nueva_volver',
        # Estado de gestión de Oportunidades CM (gestion_cm.py)
        'barra_gestion_cm', 'lbl_barra_gestion_cm', 'botones_barra_gestion_cm', 'filtros_gestion_cm',
        'botones_filtro_gestion_cm', '_filtro_gestion_cm', '_conteo_gestion_cm', 'acciones_rapidas_gestion_cm',
        'botones_gestion_cm', '_new_ui_revision_cm_completo',
    }

    def __init__(self):
        super().__init__()
        # Inter para toda la pantalla. setFont no alcanza a los widgets con
        # QSS propio: la familia se declara también en la cascada de estilos
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO)

        self.legacy = _ComercialModuleLegacy()
        # "Editar Unidad" (Vista Completa y Nueva interfaz) ya no abre
        # ComercialAgregarDialog como ventana modal: _handle_editar_unidad
        # (dentro de self.legacy) delega en este callback, que muestra la
        # pestaña "Unidad nueva" en modo edición (ver _iniciar_edicion_unidad).
        self.legacy.on_editar_unidad_solicitado = self._iniciar_edicion_unidad
        # Avisa a ComercialModule cuando una edición se guardó con éxito, para
        # devolver el formulario embebido a un estado coherente de "crear"
        # (25-09-2026, a pedido explícito -- ver _on_edicion_unidad_guardada).
        self.legacy.on_edicion_unidad_guardada = self._on_edicion_unidad_guardada

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        # La barra propia queda oculta: se cambia de pestaña con el control
        # segmentado (estilo_com.SelectorSegmentado), creado más abajo.
        self.tabs.setStyleSheet("QTabWidget::pane { border: none; background: transparent; }")
        self.tabs.tabBar().hide()

        self.new_ui_kpi_labels = {}
        # Filtro de tarjeta KPI activo por sub-pestaña (28-09-2026, a pedido
        # explícito): dict {índice de sub-pestaña -> key|None}. Se recuerda
        # por sub-pestaña, no se resetea al cambiar de sub-pestaña -- ver
        # _on_new_ui_kpi_card_clicked/_actualizar_seleccion_visual_kpi.
        self._new_ui_kpi_filtro_por_subtab = {}
        # Agrupación de la bandeja: grupo abierto por sub-pestaña (None = se
        # ven los grupos) -- ver _preparar_vista_agrupada.
        self._new_ui_grupo_abierto = {}
        self._new_ui_en_grupos = False
        self._new_ui_grupos_df = None
        self.new_ui_tab = self._build_new_ui_tab()
        self.tabs.addTab(self.new_ui_tab, "Comercial")
        self.unidad_nueva_tab = self._build_unidad_nueva_tab()
        self.tabs.addTab(self.unidad_nueva_tab, "Gestión de unidades")
        # "Vista Completa" ya no se muestra: legacy sigue como motor de datos
        # y guardado de la Nueva interfaz, oculto
        self.legacy.setParent(self)
        self.legacy.hide()
        self.legacy.es_visible = self.isVisible

        # MainWindow._get_active_submodule() detecta "modulos con sub-tabs"
        # mirando hasattr(widget, 'tabs') y, si existe, llama refresh_if_dirty/
        # load_data sobre self.tabs.currentWidget() en vez de sobre el
        # contenedor -- ComercialModule cae en ese caso porque tambien expone
        # su propio self.tabs (Comercial / Vista Completa). new_ui_tab es un
        # QWidget sin datos propios, asi que necesita el mismo contrato que
        # _ComercialModuleLegacy para que MainWindow pueda refrescarlo cuando
        # queda como pestaña activa por defecto.
        self.new_ui_tab.refresh_if_dirty = self._on_new_ui_tab_refresh_if_dirty
        self.tabs.currentChanged.connect(self._actualizar_boton_encabezado)

        # MainWindow._on_global_search() maneja el widget activo mirando
        # hasattr(widget, 'search_input') y, si existe, le setea el texto y
        # llama a widget.filter_table() -- exactamente el mismo contrato que
        # ya cumple _ComercialModuleLegacy. new_ui_tab no tenia ninguno de
        # los dos, asi que la barra de busqueda global quedaba sin efecto en
        # esta pestaña. new_ui_search_input es un QLineEdit oculto (mismo
        # patron que self.search_input en _ComercialModuleLegacy): solo
        # guarda el texto, _refresh_new_ui_data() lo lee y arma la mascara de
        # busqueda con comercial_services.construir_mascara_busqueda() sobre
        # los datos completos (VIN incluido) antes de recortar a las columnas
        # visibles de la sub-pestaña activa.
        self.new_ui_search_input = QLineEdit()
        self.new_ui_search_input.hide()
        self.new_ui_tab.search_input = self.new_ui_search_input
        self.new_ui_tab.filter_table = self._on_buscar_new_ui

        # "Comercial" (Nueva interfaz) queda activa por defecto; "Vista
        # Completa" sigue disponible para la funcionalidad completa de edicion.
        self.tabs.setCurrentIndex(0)
        self.tabs.currentChanged.connect(self._on_internal_tab_changed)

        # El selector ya no se muestra: se llega al formulario con los botones
        # "Editar unidad"/"Crear unidad" de la bandeja (ver _build_new_ui_tab).
        self.selector_pestanas = estilo_com.SelectorSegmentado(self.tabs)
        self.selector_pestanas.setParent(self)
        self.selector_pestanas.hide()
        layout.addWidget(self.tabs)

        # "Agregar contacto" pinta su botón azul/rojo según si el CDB del
        # VIN seleccionado ya tiene contacto en contactos.xlsx (ver
        # _actualizar_estado_acciones_rapidas). Tras agregar uno nuevo se
        # recarga contactos.xlsx con data_manager.load_contactos_async()
        # (mismo mecanismo que general.py), que al terminar emite
        # contactos_ready -- sin este connect, el botón seguiría rojo
        # después de agregar el primer contacto de una empresa hasta el
        # próximo cambio de selección.
        self.legacy.data_manager.contactos_ready.connect(self._actualizar_estado_acciones_rapidas)

        # Sin este connect, la bandeja de "Comercial" (Nueva interfaz, incluye
        # "Por gestionar") quedaba desactualizada tras guardar una edición
        # (ej. Editar Unidad) hasta que el usuario cambiaba de módulo y volvía
        # (lo que sí dispara _on_new_ui_tab_refresh_if_dirty). self.legacy ya
        # se conecta a data_ready para refrescar df_base (_on_global_data_ready),
        # y esa conexión se hizo primero (dentro de _ComercialModuleLegacy()
        # más arriba), así que esta se ejecuta después, con df_base ya al día.
        self.legacy.data_manager.data_ready.connect(self._on_data_ready_refrescar_new_ui)
        self.legacy.data_manager.correos_registrados.connect(self._on_correos_registrados)

        self._refresh_new_ui_data()

    def _on_new_ui_tab_refresh_if_dirty(self):
        """Contraparte de _ComercialModuleLegacy.refresh_if_dirty() para
        new_ui_tab (ver comentario en __init__): reenvia a self.legacy,
        que es quien realmente conserva df_base, y luego
        repinta la bandeja de Comercial con lo que haya quedado en memoria."""
        self.legacy.refresh_if_dirty()
        self._refresh_new_ui_data()

    # ---------------------------------------------------------------
    # NUEVA INTERFAZ (en construcción por etapas -- ver conversación con
    # el usuario para el detalle de qué se decidió en cada bloque)
    # ---------------------------------------------------------------
    def boton_encabezado_visible(self):
        return self.tabs.currentWidget() is self.new_ui_tab

    def _actualizar_boton_encabezado(self, *_):
        # Sin padre (antes de que MainWindow lo ubique) no se debe mostrar
        if self.boton_encabezado.parent() is not None:
            self.boton_encabezado.setVisible(self.boton_encabezado_visible())

    def _build_new_ui_tab(self):
        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        estilo_btn = (
            f"QPushButton {{ background-color: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; "
            "border-radius: 12px; padding: 0 18px; min-height: 40px; font-size: 14px; font-weight: 700; } "
            "QPushButton:hover { background-color: #F1F4F9; } "
            f"QPushButton:disabled {{ color: #A9B4C6; background-color: #F5F7FA; }}")
        btn_crear = QPushButton(" Crear unidad")
        btn_crear.setIcon(ThemeManager.icon('fa5s.plus', color=estilo_com.TINTA))
        btn_crear.clicked.connect(self._on_crear_nueva_unidad_clicked)
        btn_crear.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_crear.setStyleSheet(estilo_btn)
        # El botón vive en el encabezado de página de MainWindow, junto al título
        self.boton_encabezado = btn_crear

        # Contenedor propio: "Ampliar" lo oculta y la transición de
        # sub-pestaña lo anima
        self._new_ui_kpi_contenedor = QWidget()
        fila_kpis = self._build_new_ui_kpi_row()
        fila_kpis.setContentsMargins(0, 4, 0, 0)
        self._new_ui_kpi_contenedor.setLayout(fila_kpis)
        main_layout.addWidget(self._new_ui_kpi_contenedor)

        from src.ui.compartido.barra_pestanas import BarraPestanas
        self.new_ui_subtabs = BarraPestanas()
        self._badges_subtabs = []
        for i, nombre in enumerate(self._NEW_UI_SUBTAB_NOMBRES):
            self.new_ui_subtabs.addTab(nombre)
            badge = QLabel("0")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(34, 20)
            self.new_ui_subtabs.setTabButton(i, QTabBar.ButtonPosition.RightSide, badge)
            self._badges_subtabs.append(badge)
        self.new_ui_subtabs.currentChanged.connect(self._estilizar_badges_subtabs)
        self._estilizar_badges_subtabs()
        self.new_ui_subtabs.setTabToolTip(
            self._NEW_UI_SUBTAB_OFRECER_REACTIVAR,
            "Clientes que ya no tienen el servicio activo. Se les puede ofrecer contratar de nuevo.",
        )
        self.new_ui_subtabs.setExpanding(False)
        self.new_ui_subtabs.setDrawBase(False)
        # Sin flechas de desplazamiento: al ocultar y volver a mostrar pestañas (búsqueda por VIN) quedaban a la vista
        self.new_ui_subtabs.setUsesScrollButtons(False)
        self.new_ui_subtabs.setStyleSheet(estilo_com.QSS_SUBPESTANAS + "QTabBar::tab { padding-right: 6px; } "
            "QTabBar::tab:selected { color: #1B2B4E; border-bottom: 3px solid #1B2B4E; }")
        self.new_ui_subtabs.currentChanged.connect(self._on_new_ui_subtab_changed)
        self.new_ui_subtabs.tabBarClicked.connect(self._on_new_ui_subtab_clicked)
        # Contenedor con la línea inferior de ancho completo bajo las sub-pestañas
        contenedor_subtabs = QFrame()
        contenedor_subtabs.setObjectName("contenedorSubpestanasComercial")
        contenedor_subtabs.setStyleSheet(estilo_com.QSS_CONTENEDOR_SUBPESTANAS)
        fila_subtabs = QHBoxLayout(contenedor_subtabs)
        fila_subtabs.setContentsMargins(0, 0, 0, 0)
        fila_subtabs.addWidget(self.new_ui_subtabs)
        fila_subtabs.addStretch()
        main_layout.addWidget(contenedor_subtabs)

        self._new_ui_contenido = QWidget()
        content_row = QHBoxLayout(self._new_ui_contenido)
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(12)
        content_row.addWidget(self._build_new_ui_bandeja())
        main_layout.addWidget(self._new_ui_contenido, stretch=1)

        # Misma transición que al cambiar entre módulos (transiciones.py)
        self._transicion_kpis = TransicionFundidoSubida(tab, self._new_ui_kpi_contenedor, BACKGROUND)
        self._transicion_contenido = TransicionFundidoSubida(tab, self._new_ui_contenido, BACKGROUND)

        # Dónde está el VIN buscado cuando no está en Comercial (ver _localizar_vin_buscado)
        self._ubicacion_vin_destino = None
        self._grupo_abierto_por_busqueda = None
        self._panel_ubicacion_vin = PanelUbicacionVin(tab, [self._new_ui_kpi_contenedor, self._new_ui_contenido])
        self._panel_ubicacion_vin.ir_clicked.connect(self._on_ir_ubicacion_vin)

        # Acciones rápidas: panel flotante fuera del layout (la tabla usa todo
        # el ancho); aparece sobre selector, KPIs y tabla solo con alguna fila
        # seleccionada. Cuelga del módulo para llegar hasta el borde superior
        self._panel_acciones = self._build_new_ui_acciones_rapidas()
        estilo_com.crear_sombra_panel(self._panel_acciones)
        self._panel_acciones.hide()
        self._panel_acciones_abierto = False
        self._anim_panel_acciones = QPropertyAnimation(self._panel_acciones, b"pos", self)
        estilo_com.configurar_animacion_panel(self._anim_panel_acciones)
        self._anim_panel_acciones.finished.connect(self._on_anim_panel_acciones_terminada)
        self._anim_panel_acciones.valueChanged.connect(lambda _v: self._ajustar_barra_bajo_panel())
        return tab

    def _ajustar_anchos_al_viewport(self):
        """Reacomoda las columnas cuando cambia el ancho útil de la tabla: sin
        scroll horizontal, la última columna quedaba cortada si el espacio se
        achicaba. En la vista agrupada se repite el reparto por pesos; en la
        de unidades solo se comprime lo que sobra."""
        tabla = self.new_ui_table
        if tabla._ajustando_anchos_new_ui:
            return
        header = tabla.horizontalHeader()
        n = header.count()
        disponible = tabla.viewport().width()
        if n < 2 or disponible <= 0:
            return
        if getattr(self, '_new_ui_en_grupos', False):
            columnas = [self.new_ui_model.headerData(i, Qt.Orientation.Horizontal) for i in range(n)]
            if all(columnas):
                _aplicar_anchos_columnas_new_ui(tabla, columnas, anchos_fijos=self._anchos_vista_grupos(columnas))
            return
        otras = [i for i in range(n - 1) if not header.isSectionHidden(i)]
        total_otras = sum(header.sectionSize(i) for i in otras)
        maximo = disponible - NEW_UI_COL_WIDTH_MINIMO
        if not otras or total_otras <= maximo:
            return
        objetivo = max(maximo, len(otras) * NEW_UI_COL_WIDTH_MINIMO)
        tabla._ajustando_anchos_new_ui = True
        try:
            for i in otras:
                header.resizeSection(i, max(NEW_UI_COL_WIDTH_MINIMO, int(header.sectionSize(i) * objetivo / total_otras)))
        finally:
            tabla._ajustando_anchos_new_ui = False

    def _on_new_ui_header_resized(self, logical_index, old_size, new_size):
        """Reparte el ancho entre las columnas de new_ui_table para que la
        suma total nunca supere el ancho visible del panel (30-09-2026,
        reportado: al ensanchar una columna a mano, las siguientes quedaban
        empujadas fuera de la vista y, al no haber scroll horizontal
        (ScrollBarAlwaysOff en _build_new_ui_bandeja), no había forma de
        volver a verlas).

        Ajuste (30-09-2026, mismo día): la primera versión solo comprimía las
        demás columnas, así que la que se estaba arrastrando podía terminar
        ocupando toda la pantalla y dejar al resto en el mínimo. Ahora
        primero LIMITA la propia columna que se arrastra a un ancho máximo
        (el que deja a todas las demás, incluida la última, al menos en
        NEW_UI_COL_WIDTH_MINIMO) y recién después reparte lo que sobre/falte
        entre las columnas intermedias (ni la redimensionada ni la última:
        esa la sigue ajustando sola setStretchLastSection)."""
        if self.new_ui_table._ajustando_anchos_new_ui:
            return
        header = self.new_ui_table.horizontalHeader()
        ultima = header.count() - 1
        if header.count() < 3 or logical_index == ultima:
            return

        disponible = self.new_ui_table.viewport().width()
        otras = [i for i in range(header.count()) if i not in (logical_index, ultima)]
        if not otras:
            return

        # Limita la columna arrastrada: no puede crecer más allá de lo que
        # deja a las demás (incluida la última) su ancho mínimo.
        max_para_resized = max(
            NEW_UI_COL_WIDTH_MINIMO,
            disponible - (len(otras) + 1) * NEW_UI_COL_WIDTH_MINIMO,
        )
        tamano_final = new_size
        if new_size > max_para_resized:
            tamano_final = max_para_resized
            self.new_ui_table._ajustando_anchos_new_ui = True
            try:
                header.resizeSection(logical_index, tamano_final)
            finally:
                self.new_ui_table._ajustando_anchos_new_ui = False

        espacio_para_otras = disponible - tamano_final - NEW_UI_COL_WIDTH_MINIMO
        espacio_minimo_otras = len(otras) * NEW_UI_COL_WIDTH_MINIMO
        objetivo_otras = max(espacio_para_otras, espacio_minimo_otras)
        total_otras_actual = sum(header.sectionSize(i) for i in otras)

        if total_otras_actual <= objetivo_otras:
            return  # ya calza, nada que comprimir

        self.new_ui_table._ajustando_anchos_new_ui = True
        try:
            acumulado = 0
            for pos, i in enumerate(otras):
                if pos == len(otras) - 1:
                    nuevo = max(NEW_UI_COL_WIDTH_MINIMO, objetivo_otras - acumulado)
                else:
                    proporcion = header.sectionSize(i) / total_otras_actual
                    nuevo = max(NEW_UI_COL_WIDTH_MINIMO, round(objetivo_otras * proporcion))
                header.resizeSection(i, nuevo)
                acumulado += nuevo
        finally:
            self.new_ui_table._ajustando_anchos_new_ui = False

    def _build_new_ui_bandeja(self):
        # Barra de opciones y tabla en tarjetas separadas
        externo = QWidget()
        layout_externo = QVBoxLayout(externo)
        layout_externo.setContentsMargins(0, 0, 0, 0)
        layout_externo.setSpacing(12)
        frame = QFrame()
        frame.setObjectName("bandejaComercial")
        frame.setStyleSheet(estilo_com.qss_tarjeta("bandejaComercial"))
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        self._layout_tabla_bandeja = layout

        # Botones creados por self.legacy
        contenedor_barra = QFrame()
        contenedor_barra.setObjectName("barraBandejaComercial")
        contenedor_barra.setStyleSheet(
            "QFrame#barraBandejaComercial { background-color: #1B2B4E; border: none; border-radius: 14px; }")
        barra = QHBoxLayout(contenedor_barra)
        barra.setContentsMargins(15, 7, 15, 7)
        barra.setSpacing(8)
        self._barra_bandeja = contenedor_barra
        layout_externo.addWidget(contenedor_barra)
        layout_externo.addWidget(self._build_barra_gestion_cm())
        layout_externo.addWidget(frame, stretch=1)
        self.btn_marcar_vencidos_barra = QPushButton(" 0")
        self.btn_marcar_vencidos_barra.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_marcar_vencidos_barra.setIcon(ThemeManager.icon('fa5s.calendar-times', color=TEXT_SECONDARY))
        self.btn_marcar_vencidos_barra.setMinimumWidth(44)
        self.btn_marcar_vencidos_barra.clicked.connect(self._on_marcar_todos_vencidos_clicked)
        self.btn_arreglar_inconsistencias_barra = QPushButton(" Arreglar (0)")
        self.btn_arreglar_inconsistencias_barra.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_arreglar_inconsistencias_barra.setIcon(ThemeManager.icon('fa5s.magic', color=TEXT_SECONDARY))
        self.btn_arreglar_inconsistencias_barra.clicked.connect(self._on_arreglar_inconsistencias_clicked)
        self.btn_arreglar_inconsistencias_barra.hide()
        self.btn_arreglar_fechas_barra = QPushButton(" Arreglar fechas (0)")
        self.btn_arreglar_fechas_barra.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_arreglar_fechas_barra.setIcon(ThemeManager.icon('fa5s.magic', color=TEXT_SECONDARY))
        self.btn_arreglar_fechas_barra.clicked.connect(self._on_arreglar_fechas_clicked)
        self.btn_arreglar_fechas_barra.hide()
        self.legacy.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='white'))
        self.legacy.btn_export_excel.clicked.connect(self._exportar_excel_bandeja)
        for btn in (self.legacy.btn_revisar_inconsistencias_forma_contrato, self.legacy.btn_revisar_fechas_contrato):
            estilo_com.aplicar_estilo_boton_barra(btn, 'neutro')

        # "Ampliar": oculta las tarjetas KPI para darle más alto a la tabla
        self.btn_ampliar_bandeja = QPushButton(" Ampliar")
        self.btn_ampliar_bandeja.setCheckable(True)
        self.btn_ampliar_bandeja.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ampliar_bandeja.setIcon(ThemeManager.icon('fa5s.expand', color=TEXT_SECONDARY))
        self.btn_ampliar_bandeja.setToolTip("Ampliar tabla (oculta las tarjetas de resumen)")
        estilo_com.aplicar_estilo_boton_barra(self.btn_ampliar_bandeja, 'neutro')
        self.btn_ampliar_bandeja.toggled.connect(self._on_ampliar_bandeja_toggled)
        estilo_com.sincronizar_boton_kpi(self.btn_ampliar_bandeja)

        self.btn_volver_grupos = QPushButton()
        self.btn_volver_grupos.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_volver_grupos.setIcon(ThemeManager.icon('fa5s.arrow-left', color=TEXT_SECONDARY))
        self.btn_volver_grupos.setToolTip("Volver a la lista de grupos")
        self.btn_volver_grupos.setFixedWidth(44)
        self.btn_volver_grupos.setStyleSheet(
            "QPushButton { background-color: rgba(255,255,255,0.10); border: 1px solid rgba(255,255,255,0.18); "
            "border-radius: 10px; min-height: 34px; } QPushButton:hover { background-color: rgba(255,255,255,0.20); }")
        self.btn_volver_grupos.setIcon(ThemeManager.icon('fa5s.arrow-left', color='white'))
        self.btn_volver_grupos.clicked.connect(self._on_volver_a_grupos_clicked)
        self.btn_volver_grupos.hide()

        separador = QFrame()
        separador.setFixedSize(1, 28)
        separador.setStyleSheet("background: rgba(255,255,255,0.22);")
        self.lbl_titulo_bandeja = QLabel()
        self.lbl_titulo_bandeja.setStyleSheet("color: white; font-size: 15px; font-weight: 800; background: transparent;")
        self.lbl_grupo_abierto = QLabel()
        self.lbl_grupo_abierto.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
        bloque_titulo = QWidget()
        lay_titulo = QVBoxLayout(bloque_titulo)
        lay_titulo.setContentsMargins(0, 0, 0, 0)
        lay_titulo.setSpacing(0)
        lay_titulo.addWidget(self.lbl_titulo_bandeja)
        lay_titulo.addWidget(self.lbl_grupo_abierto)

        # Filtro por PERIODO INTERNO: afecta KPIs, contadores y bandeja
        self.combo_periodo_interno = estilo_com.SelectorFiltroPopup("Periodo interno", self._TEXTO_TODOS_PERIODOS)
        self.combo_periodo_interno.cambiado.connect(lambda _v: self._on_periodo_interno_cambiado(self.combo_periodo_interno))
        self.combo_periodo_interno.set_compacto(True)
        self._periodo_interno_df = (None, None, None)
        # Filtros por columna: solo icono, el valor elegido va en la ayuda
        self._filtros_columna = {}
        self._orden_filtros = []
        for columna, titulo, icono in self._FILTROS_COLUMNA:
            selector = estilo_com.SelectorFiltroPopup(titulo, f"Todas ({titulo.lower()})", icono, multiple=True)
            selector.set_compacto(True)
            selector.cambiado.connect(lambda _v, s=selector: self._on_periodo_interno_cambiado(s))
            self._filtros_columna[columna] = selector

        barra.addWidget(self.btn_volver_grupos)
        barra.addWidget(separador)
        barra.addWidget(bloque_titulo)
        barra.addStretch()
        barra.addWidget(self._build_filtros_gestion_cm())
        # Tres grupos con encabezado: filtros, acciones y generales
        grupo_filtros, lay_filtros = PantallaIngresosBase._crear_grupo_barra("Filtros")
        grupo_revision, lay_revision = PantallaIngresosBase._crear_grupo_barra("Revisión")
        grupo_acciones, lay_acciones = PantallaIngresosBase._crear_grupo_barra("Acciones")
        grupo_generales, lay_generales = PantallaIngresosBase._crear_grupo_barra("Generales")
        self.btn_limpiar_filtros = QPushButton()
        self.btn_limpiar_filtros.setFixedWidth(44)
        self.btn_limpiar_filtros.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_limpiar_filtros.setIcon(ThemeManager.icon('fa5s.trash-alt', color=TEXT_SECONDARY))
        self.btn_limpiar_filtros.setToolTip("Quitar los filtros")
        self.btn_limpiar_filtros.clicked.connect(self._limpiar_filtros)
        lay_filtros.addWidget(self.btn_limpiar_filtros)
        estilo_com.preparar_boton_capsula(self.btn_limpiar_filtros)
        self.btn_limpiar_filtros.hide()
        lay_filtros.addWidget(self.combo_periodo_interno)
        for selector in self._filtros_columna.values():
            lay_filtros.addWidget(selector)
        for lay_destino, botones in (
                (lay_revision, (self.legacy.btn_revisar_inconsistencias_forma_contrato,
                                self.legacy.btn_revisar_fechas_contrato)),
                (lay_acciones, (self.btn_marcar_vencidos_barra, self.btn_arreglar_inconsistencias_barra,
                                self.btn_arreglar_fechas_barra)),
                (lay_generales, (self.legacy.btn_export_excel, self.btn_ampliar_bandeja))):
            for btn in botones:
                lay_destino.addWidget(btn)
                estilo_com.preparar_boton_capsula(btn)
        self._grupo_revision_barra = grupo_revision
        self._grupo_acciones_barra = grupo_acciones
        for grupo in (grupo_filtros, grupo_revision, grupo_acciones, grupo_generales):
            barra.addWidget(grupo)
            grupo.show()
        self.legacy.btn_revisar_inconsistencias_forma_contrato.toggled.connect(self._on_aviso_bandeja_toggled)
        self.legacy.btn_revisar_fechas_contrato.toggled.connect(self._on_aviso_bandeja_toggled)

        # Mismo componente de tabla que usan el resto de las pantallas
        # (VolvoTableWidget + PandasTableModel), en vez de un QTableWidget
        # aparte: así se hereda el mismo look (sombra, filas alternadas,
        # badges de color por estado) sin duplicar estilos a mano.
        self.new_ui_table = VolvoTableWidget()
        qss_tabla = estilo_com.QSS_TABLA + (
            "QHeaderView::section { background: #F7F8FC; color: #6B7A90; border-bottom: 1px solid #E3E8F0; }"
            f"QTableView {{ alternate-background-color: {estilo_com.FILA_ALTERNA}; }}"
            "QTableView::item { border-left: none; }")
        self.new_ui_table.setStyleSheet(qss_tabla)
        self.new_ui_table.frozen_view.setStyleSheet(qss_tabla)

        # La barra vertical nace desde el borde superior (junto al encabezado):
        # se baja para que quede alineada con las filas.
        def _bajar_scrollbar():
            h = self.new_ui_table.horizontalHeader().height()
            if self.new_ui_table.property('_alto_scroll') != h:
                self.new_ui_table.setProperty('_alto_scroll', h)
                self.new_ui_table.setStyleSheet(qss_tabla + f"QScrollBar:vertical {{ margin-top: {h}px; }}")
        self.new_ui_table.horizontalHeader().geometriesChanged.connect(_bajar_scrollbar)
        self.new_ui_table.horizontalHeader().sectionResized.connect(lambda *_: _bajar_scrollbar())
        self.new_ui_table.menu_type = "solo_lectura"
        # Sin arrastrar columnas ni "Fijar columna"; clic en el encabezado ordena
        self.new_ui_table.horizontalHeader().setSectionsMovable(False)
        self.new_ui_table.permitir_fijar_columna = False
        # Sin autoajuste de ancho con doble clic (ni en la sección ni en el borde)
        for header in (self.new_ui_table.horizontalHeader(), self.new_ui_table.frozen_view.horizontalHeader()):
            header.sectionDoubleClicked.disconnect()
            header.sectionHandleDoubleClicked.disconnect()
        self.new_ui_table.horizontalHeader().sectionClicked.connect(self._on_new_ui_encabezado_clicado)
        self.new_ui_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # RAZÓN SOCIAL completa sin tener que ensanchar la columna a mano
        # (23-09-2026, a pedido explícito): ajuste de línea + fila más alta
        # (COMERCIAL_NEW_UI_ROW_HEIGHT) en vez del alto/elide estándar de
        # VolvoTableWidget. ElideNone es necesario porque _setup_style()
        # deja ElideRight por defecto (trunca con "..." en una sola línea),
        # lo que impedía el ajuste de línea aunque wordWrap estuviera activo.
        # Se aplica a la instancia (no a la clase VolvoTableWidget), así que
        # el resto de la app conserva el alto/elide estándar de 38px.
        self.new_ui_table.setWordWrap(True)
        self.new_ui_table.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.new_ui_table.verticalHeader().setDefaultSectionSize(COMERCIAL_NEW_UI_ROW_HEIGHT)
        # frozen_view (columna fijada, ver VolvoTableWidget._setup_frozen_view)
        # es una QTableView aparte con su propio verticalHeader -- sin este
        # ajuste, fijar una columna desalinearía sus filas contra las de la
        # vista principal en cuanto RAZÓN SOCIAL ocupara más de una línea.
        self.new_ui_table.frozen_view.verticalHeader().setDefaultSectionSize(COMERCIAL_NEW_UI_ROW_HEIGHT)
        # Interactive (no Stretch): permite fijar un ancho inicial por columna
        # (ver _aplicar_anchos_columnas_new_ui, llamado desde
        # _refresh_new_ui_data) y que el usuario pueda seguir redimensionando
        # a mano -- Stretch bloqueaba el resize manual por completo.
        # setStretchLastSection cubre el espacio restante de la tabla con la
        # última columna en vez de dejarlo en blanco.
        self.new_ui_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.new_ui_table.horizontalHeader().setStretchLastSection(True)
        # Encabezado y celdas centrados + sin scroll lateral (28-09-2026, a
        # pedido explícito), solo en esta tabla (no en VolvoTableWidget en
        # general, que sigue alineada a la izquierda para el resto de la
        # app). Los anchos por columna (ver _aplicar_anchos_columnas_new_ui,
        # llamado desde _refresh_new_ui_data) se ajustan al texto de cada
        # encabezado -- junto con setStretchLastSection de arriba, el total
        # de columnas cabe en el ancho del panel sin necesitar scroll.
        self.new_ui_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        # Encabezado en varias líneas cuando el texto no entra en el ancho
        # actual de la columna (30-09-2026, a pedido explícito), en vez de
        # elidirse en una sola línea -- ver FilterHeaderView.set_word_wrap_habilitado.
        self.new_ui_table.horizontalHeader().set_word_wrap_habilitado(True)
        estilo_com.aplicar_estilo_encabezado(self.new_ui_table.horizontalHeader())
        self.new_ui_table.horizontalHeader().set_estilo_encabezado(
            "#F7F8FC", "#F7F8FC", "#6B7A90", "#E3E8F0",
            separador=None, grosor_linea=1, alto_minimo=44, espaciado_letras=0.8,
            iconos_orden=True, radio_superior=13, texto_negrita_fuerte=True,
        )
        self.new_ui_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Sin scroll horizontal (arriba), si el usuario ensancha una columna a
        # mano el resto puede quedar empujado fuera del panel visible, sin
        # forma de llegar a verlas (reportado 30-09-2026). Se comprimen las
        # demás columnas para que la suma siga calzando en el ancho visible
        # -- ver _on_new_ui_header_resized. El flag vive en la tabla (no en
        # self) porque _aplicar_anchos_columnas_new_ui también lo usa y solo
        # recibe la tabla, no el módulo.
        self.new_ui_table._ajustando_anchos_new_ui = False
        self.new_ui_table.horizontalHeader().sectionResized.connect(self._on_new_ui_header_resized)
        self.new_ui_table._filtro_ancho_viewport = _FiltroAnchoViewport(self.new_ui_table, self._ajustar_anchos_al_viewport)
        self.new_ui_table.viewport().installEventFilter(self.new_ui_table._filtro_ancho_viewport)
        # Selección por fila completa: la bandeja es de solo lectura, y
        # "Revisión CM" necesita saber si hay una fila seleccionada para
        # habilitar/deshabilitar sus acciones rápidas (ver
        # _actualizar_estado_acciones_rapidas).
        self.new_ui_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # El estado de orden ("Ordenar A -> Z" del menú de encabezado) vive en
        # la propia VolvoTableWidget y no se aplica solo: cada pantalla debe
        # reaccionar a sort_changed y llamar a table.apply_sort() antes de
        # set_data(). Sin esta conexión, elegir un orden no hacía nada.
        self.new_ui_table.sort_changed.connect(self._refresh_new_ui_data)

        # Texto centrado (ver arriba): PandasTableModel usa alineación
        # izquierda por defecto para el resto de la app, así que se pasa
        # explícita solo aquí.
        self.new_ui_model = PandasTableModel(alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self.new_ui_model._chips_modelo = True
        self.new_ui_model.destacar_columnas_cliente()
        self.new_ui_table.set_model_and_delegate(self.new_ui_model)
        self._delegado_celdas = estilo_com.DelegadoCeldasComercial([self.new_ui_table, self.new_ui_table.frozen_view])
        self.new_ui_table.setItemDelegate(self._delegado_celdas)
        self.new_ui_table.frozen_view.setItemDelegate(self._delegado_celdas)
        # COMERCIAL_NEW_UI_ROW_HEIGHT pasa a ser el alto mínimo: si el texto necesita más de 2 líneas, la fila crece.
        self.new_ui_table.set_columnas_ajuste_texto(COMERCIAL_COLUMNAS_AJUSTE_TEXTO)
        self.new_ui_table.selectionModel().selectionChanged.connect(self._actualizar_estado_acciones_rapidas)
        self.new_ui_table.clicked.connect(self._on_new_ui_fila_clicada)
        self.new_ui_table.doubleClicked.connect(self._on_new_ui_doble_clic)
        # VIN no se muestra en ninguna de las 4 sub-pestañas (NEW_UI_SUBTAB_
        # COLUMNS), así que "Copiar VIN" del menú contextual (VolvoTableWidget.
        # _get_vin_for_row) necesita este resolver para no mostrar
        # "Desconocido" -- misma fuente y mismo criterio de orden que
        # _obtener_vins_seleccionados.
        self.new_ui_table.set_vin_resolver(self._resolver_vin_por_fila_new_ui)
        layout.addWidget(self.new_ui_table)

        # Solo icono (el texto lo reescriben otros flujos: se ignora)
        for btn, tip in ((self.legacy.btn_export_excel, "Exportar a Excel"),
                         (self.legacy.btn_revisar_inconsistencias_forma_contrato, None),
                         (self.legacy.btn_revisar_fechas_contrato, None),
                         (self.btn_ampliar_bandeja, None)):
            if tip:
                btn.setToolTip(tip)
            btn.setText("")
            btn.setFixedWidth(44)
            btn.setText = lambda *_a: None
        self._actualizar_boton_marcar_vencidos_barra()

        return externo

    def showEvent(self, event):
        super().showEvent(event)
        estilo_com.sincronizar_boton_kpi(getattr(self, 'btn_ampliar_bandeja', None))

    def _on_ampliar_bandeja_toggled(self, ampliada):
        estilo_com.guardar_kpi_ocultos(ampliada)
        self._new_ui_kpi_contenedor.setVisible(not ampliada)
        self.btn_ampliar_bandeja.setText(" Reducir" if ampliada else " Ampliar")
        self.btn_ampliar_bandeja.setIcon(ThemeManager.icon('fa5s.compress' if ampliada else 'fa5s.expand', color=TEXT_SECONDARY))
        self.btn_ampliar_bandeja.setToolTip(
            "Volver a mostrar las tarjetas de resumen" if ampliada else "Ampliar tabla (oculta las tarjetas de resumen)"
        )

    def _on_new_ui_encabezado_clicado(self, logical_index):
        """Clic en un encabezado: ordena por esa columna A→Z; un segundo clic
        en la misma invierte el orden (mismo estado que "Ordenar A → Z" del
        menú de clic derecho)."""
        col_name = self.new_ui_model.headerData(logical_index, Qt.Orientation.Horizontal)
        if not col_name:
            return
        tabla = self.new_ui_table
        if tabla._sort_column == col_name and tabla._sort_order == Qt.SortOrder.AscendingOrder:
            tabla._set_sort(col_name, Qt.SortOrder.DescendingOrder)
        else:
            tabla._set_sort(col_name, Qt.SortOrder.AscendingOrder)

    @staticmethod
    def _titulo_seccion(texto):
        lbl = QLabel(texto)
        fuente = lbl.font()
        fuente.setCapitalization(QFont.Capitalization.AllUppercase)
        lbl.setFont(fuente)
        lbl.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        return lbl

    def _build_new_ui_acciones_rapidas(self):
        # Nace colgado del módulo: armarlo suelto y moverlo después le
        # reaplicaba los estilos a todo el panel
        frame = QFrame(self)
        frame.setObjectName("accionesRapidasComercial")
        frame.setStyleSheet(estilo_com.QSS_PANEL_FLOTANTE)
        marco = QVBoxLayout(frame)
        marco.setContentsMargins(1, 1, 1, 1)

        # Con ficha + acciones + observaciones el panel puede superar el alto
        # disponible en pantallas bajas: se desplaza en vez de cortarse
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(estilo_com.QSS_SCROLL_PANEL)
        scroll.viewport().setAutoFillBackground(False)
        contenido = QWidget()
        contenido.setAutoFillBackground(False)
        contenido.setStyleSheet("background: transparent;")
        scroll.setWidget(contenido)
        marco.addWidget(scroll)

        layout = QVBoxLayout(contenido)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        self._ficha_contenedor = self._build_new_ui_ficha_unidad()
        layout.addWidget(self._ficha_contenedor)
        self._titulo_acciones = self._titulo_seccion("Acciones rápidas")
        layout.addWidget(self._titulo_acciones)

        # Un único panel de acciones comunes a las 4 sub-pestañas (Enviar
        # correo / Editar Unidad / Agregar contacto / Enviar a operaciones,
        # ver _build_new_ui_acciones_rapidas_comunes), más un panel aparte
        # con "Confirmar baja", exclusivo de "Gestionar CM" y que se agrega
        # a continuación del panel común solo en esa sub-pestaña (ver
        # _toggle_acciones_rapidas_panel). Antes existían dos paneles
        # mutuamente excluyentes (uno genérico decorativo y uno propio de
        # CM); se reemplazan aquí por este esquema común + extra.
        self.acciones_rapidas_comunes = self._build_new_ui_acciones_rapidas_comunes()
        self.acciones_rapidas_cm = self._build_new_ui_acciones_rapidas_solo_cm()
        self.acciones_rapidas_vencidos = self._build_new_ui_acciones_rapidas_solo_vencidos()
        self.acciones_rapidas_vigentes = self._build_new_ui_acciones_rapidas_solo_vigentes()
        self.acciones_rapidas_inconsistencias = self._build_new_ui_acciones_rapidas_solo_inconsistencias()
        self.acciones_rapidas_fechas = self._build_new_ui_acciones_rapidas_solo_fechas()
        layout.addWidget(self.acciones_rapidas_fechas)
        self.acciones_rapidas_fechas.hide()
        layout.addWidget(self.acciones_rapidas_comunes)
        layout.addWidget(self.acciones_rapidas_cm)
        layout.addWidget(self._build_acciones_rapidas_gestion_cm())
        layout.addWidget(self.acciones_rapidas_vencidos)
        layout.addWidget(self.acciones_rapidas_inconsistencias)
        self.acciones_rapidas_papelera = self._build_new_ui_acciones_rapidas_solo_papelera()
        layout.addWidget(self.acciones_rapidas_papelera)
        self.acciones_rapidas_conversion = self._build_new_ui_acciones_rapidas_solo_conversion()
        layout.addWidget(self.acciones_rapidas_conversion)
        self.acciones_rapidas_conversion.hide()
        self.acciones_rapidas_cm.hide()
        self.acciones_rapidas_vencidos.hide()
        self.acciones_rapidas_vigentes.hide()
        self.acciones_rapidas_inconsistencias.hide()
        self.acciones_rapidas_papelera.hide()
        self._toggle_acciones_rapidas_panel(self.new_ui_subtabs.currentIndex())

        self._renovar_modo_activo = False
        self._renovar_filas = {}
        self.panel_renovar = self._build_new_ui_panel_renovar()
        layout.addWidget(self.panel_renovar)
        self.panel_renovar.hide()
        self.panel_fecha_baja = self._build_new_ui_panel_fecha_baja()
        layout.addWidget(self.panel_fecha_baja)
        self.panel_fecha_baja.hide()

        # Observaciones de la unidad seleccionada (columna OBSERVACIONES)
        layout.addSpacing(6)
        self.__dict__['_titulo_observaciones'] = self._titulo_seccion("Observaciones")
        layout.addWidget(self.__dict__['_titulo_observaciones'])
        self.txt_observaciones = QTextEdit()
        self.txt_observaciones.setPlaceholderText("Escribe una observación sobre esta unidad…")
        self.txt_observaciones.setAcceptRichText(False)
        self.txt_observaciones.setFixedHeight(88)
        self.txt_observaciones.setStyleSheet(estilo_com.QSS_OBSERVACIONES)
        self.txt_observaciones.textChanged.connect(self._actualizar_boton_guardar_observaciones)
        layout.addWidget(self.txt_observaciones)
        self.btn_guardar_observaciones = QPushButton(" Guardar observación")
        self.btn_guardar_observaciones.setIcon(ThemeManager.icon('fa5s.save', color='white'))
        self.btn_guardar_observaciones.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_guardar_observaciones.setStyleSheet(estilo_com.QSS_BOTON_GUARDAR)
        self.btn_guardar_observaciones.clicked.connect(self._on_guardar_observaciones_clicked)
        layout.addWidget(self.btn_guardar_observaciones)
        self._observaciones_vin = None
        self._cargar_observaciones(None, "")
        self._toggle_acciones_rapidas_panel(self.new_ui_subtabs.currentIndex())

        layout.addStretch()
        return frame

    def _build_new_ui_accion_button(self, icon_name, titulo, subtitulo, color=None):
        color = color or estilo_com.AZUL
        # Fondo/borde animados al pasar el mouse (ver BotonAccionRapida)
        btn = estilo_com.BotonAccionRapida(color, ocultar_si_bloqueado=True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Estilo neutro al que vuelve "Agregar contacto" (ver _aplicar_estilo_agregar_contacto)
        btn._qss_por_defecto = estilo_com.QSS_ACCION_RAPIDA_TRANSPARENTE
        btn.setMinimumHeight(36)
        btn.setToolTip(subtitulo)

        layout = QHBoxLayout(btn)
        layout.setContentsMargins(6, 4, 10, 4)
        layout.setSpacing(8)

        icon_frame = QFrame()
        icon_frame.setFixedSize(26, 26)
        icon_frame.setStyleSheet(estilo_com.qss_icono_accion(color))
        icon_frame_layout = QVBoxLayout(icon_frame)
        icon_frame_layout.setContentsMargins(0, 0, 0, 0)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap(icon_name, color=color, size=12))
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_frame_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_frame)
        btn._icono_frame = icon_frame
        btn._icono_lbl = icon_lbl

        titulo_lbl = QLabel(titulo)
        titulo_lbl.setToolTip(subtitulo)
        titulo_lbl.setStyleSheet(f"color: {estilo_com.TINTA}; font-weight: bold; font-size: 12px; background: transparent; border: none;")
        layout.addWidget(titulo_lbl, stretch=1)
        btn._titulo_lbl = titulo_lbl

        return btn

    def _on_new_ui_subtab_changed(self, index):
        """Cambiar de sub-pestaña en la Nueva interfaz debe filtrar la
        bandeja con la regla de negocio real correspondiente (ver
        _NEW_UI_SUBTAB_FILTERS), no solo cambiar una etiqueta visual."""
        # Elegir una sub-pestaña cierra el aviso que estuviera abierto
        fotos = self._fotos_para_transicion_subtab()
        if self._avisos_activos():
            for btn in (self.legacy.btn_revisar_inconsistencias_forma_contrato,
                        self.legacy.btn_revisar_fechas_contrato):
                btn.setChecked(False)
        self._new_ui_active_subtab = index
        self._new_ui_grupo_abierto.clear()
        self._toggle_acciones_rapidas_panel(index)
        self._ajustar_tabla_bajo_panel()
        self._refresh_new_ui_data()
        for transicion, foto in fotos:
            transicion.iniciar(foto)
        animar_sobre_tabla(self.new_ui_table, 300)
        if getattr(self, '_panel_acciones_abierto', False):
            self._panel_acciones.raise_()

    def _fotos_para_transicion_subtab(self):
        """Foto de los KPI ANTES de repintar la sub-pestaña nueva (solo si están a la vista: con
        "Ampliar" activo no hay KPIs que animar). La tabla usa un esqueleto, no una foto."""
        fotos = []
        for transicion, contenedor in (
            (getattr(self, '_transicion_kpis', None), getattr(self, '_new_ui_kpi_contenedor', None)),
        ):
            if transicion is not None and contenedor is not None and contenedor.isVisible():
                transicion.terminar()
                fotos.append((transicion, capturar(contenedor)))
        return fotos

    def _on_new_ui_subtab_clicked(self, index):
        # Clic en la sub-pestaña ya marcada: currentChanged no se emite
        if index == self.new_ui_subtabs.currentIndex() and self._avisos_activos():
            for btn in (self.legacy.btn_revisar_inconsistencias_forma_contrato,
                        self.legacy.btn_revisar_fechas_contrato):
                btn.setChecked(False)

    def _avisos_activos(self):
        return bool(getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False)
                    or getattr(self.legacy, '_filtro_fechas_contrato_activo', False))

    def _on_aviso_bandeja_toggled(self, _checked=False):
        if self._avisos_activos():
            self._new_ui_active_subtab = self._NEW_UI_SUBTAB_AVISOS
        else:
            self._new_ui_active_subtab = self.new_ui_subtabs.currentIndex()
        self._toggle_acciones_rapidas_panel(self._new_ui_active_subtab)
        self._refresh_new_ui_data()
        self._actualizar_boton_arreglar_inconsistencias()
        self._actualizar_boton_arreglar_fechas()
        self._sincronizar_grupos_barra()

    def _refresh_bandeja_avisos(self):
        """Bandeja con las unidades de toda la base que marcan los avisos
        activos (mismas reglas que filtraban la tabla de Vista Completa)."""
        columnas = self._COLUMNAS_BANDEJA_INCONSISTENCIAS
        solo_fechas = bool(getattr(self.legacy, '_filtro_fechas_contrato_activo', False))
        if solo_fechas:
            columnas = self._COLUMNAS_BANDEJA_FECHAS
        self._salir_vista_agrupada()
        df = getattr(self.legacy, 'df_base', None)
        if df is None or df.empty:
            df = pd.DataFrame(columns=columnas)
        elif solo_fechas:
            df = self.legacy._df_fechas_contrato
            search_text = self.new_ui_search_input.text().strip().lower()
            if search_text and not df.empty:
                df = df[comercial_services.construir_mascara_busqueda(
                    df, search_text, COLUMNAS_BUSQUEDA_COMERCIAL, COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL)]
            df = self.new_ui_table.apply_sort(df)
        else:
            if getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False):
                df = comercial_services.detectar_inconsistencias_forma_contrato_tipo_facturacion(df)
            search_text = self.new_ui_search_input.text().strip().lower()
            if search_text and not df.empty:
                df = df[comercial_services.construir_mascara_busqueda(
                df, search_text, COLUMNAS_BUSQUEDA_COMERCIAL, COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL)]
            df = self.new_ui_table.apply_sort(df)

        self._new_ui_bandeja_actual_df = df
        self.lbl_grupo_abierto.setText(self._con_periodo(f"{len(df)} unidades"))
        cols_presentes = [c for c in columnas if c in df.columns]
        self.new_ui_model.set_data(df[cols_presentes])
        # "Avisos" no es una de las 6 sub-pestañas regulares (no tiene índice
        # en NEW_UI_SUBTAB_COLUMN_WIDTHS): solo RAZÓN SOCIAL recibe un ancho
        # fijo, el resto cae al cálculo por contenido.
        _aplicar_anchos_columnas_new_ui(
            self.new_ui_table, cols_presentes, anchos_fijos={'RAZÓN SOCIAL': COMERCIAL_COL_WIDTH_RAZON_SOCIAL},
        )
        self._actualizar_estado_acciones_rapidas()

    def _toggle_acciones_rapidas_panel(self, index):
        """El panel de acciones comunes (acciones_rapidas_comunes) se
        muestra siempre; "Gestionar CM" agrega además "Confirmar baja"
        (acciones_rapidas_cm), "Vencidos" agrega "Marcar como Vencido"
        (acciones_rapidas_vencidos, 23-09-2026) y "Vigentes" agrega "Marcar
        como Vigente" (acciones_rapidas_vigentes, 24-09-2026), cada uno a
        continuación. Las demás sub-pestañas solo muestran las 4 acciones
        comunes.

        new_ui_table es compartida por las 6 sub-pestañas. Antes solo
        "Gestionar CM" permitía elegir varios VIN a la vez; ahora "Enviar
        correo" y "Enviar a operaciones" también deben soportar selección
        múltiple en todas, así que la selección extendida (Ctrl/Shift+clic)
        queda activa siempre, sin distinción por sub-pestaña."""
        if getattr(self, '_renovar_modo_activo', False):
            if index == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
                return
            self._set_modo_renovar(False)
        if self.__dict__.get('_fecha_baja_modo_activo'):
            self.__dict__['_fecha_baja_modo_activo'] = False
            self.panel_fecha_baja.hide()
            self._titulo_acciones.show()
            self.acciones_rapidas_comunes.show()
            self._mostrar_ficha_y_observaciones(True)
        es_revision_cm = index == self._NEW_UI_SUBTAB_REVISION_CM
        es_vencidos = es_vigentes = index == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
        self.acciones_rapidas_cm.setVisible(es_revision_cm)
        if self.__dict__.get('acciones_rapidas_gestion_cm') is not None:
            self.acciones_rapidas_gestion_cm.setVisible(es_revision_cm)
        # En Oportunidades CM la observación guarda el estado de gestión: solo se cambia con sus botones
        if self.__dict__.get('txt_observaciones') is not None:
            self.txt_observaciones.setReadOnly(es_revision_cm)
            self.txt_observaciones.setPlaceholderText(
                "Sin observación" if es_revision_cm else "Escribe una observación sobre esta unidad…")
            self.btn_guardar_observaciones.setVisible(not es_revision_cm)
        self.acciones_rapidas_vencidos.setVisible(es_vencidos)
        self.acciones_rapidas_vigentes.setVisible(es_vigentes)
        self.acciones_rapidas_papelera.setVisible(index == self._NEW_UI_SUBTAB_POR_GESTIONAR)
        self.acciones_rapidas_conversion.setVisible(
            index in (self._NEW_UI_SUBTAB_OFRECER_REACTIVAR, self._NEW_UI_SUBTAB_RENOVAR_CLIENTES))
        self.acciones_rapidas_inconsistencias.setVisible(
            index == self._NEW_UI_SUBTAB_AVISOS
            and bool(getattr(self.legacy, '_filtro_inconsistencias_forma_contrato_activo', False)))
        self.acciones_rapidas_fechas.setVisible(
            index == self._NEW_UI_SUBTAB_AVISOS
            and bool(getattr(self.legacy, '_filtro_fechas_contrato_activo', False)))
        self.new_ui_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def _actualizar_estado_acciones_rapidas(self):
        """Lee la selección una sola vez y actualiza todas las acciones y la ficha (ver `_calcular_estado_acciones_rapidas`)."""
        # En la lista de flotas las filas no son unidades: su selección solo sirve a la barra de gestión CM
        self.__dict__['_filas_sel_actualizacion'] = () if self.__dict__.get('_new_ui_en_grupos') else tuple(
            i.row() for i in self.new_ui_table.selectionModel().selectedRows())
        try:
            self._calcular_estado_acciones_rapidas()
        finally:
            self.__dict__['_filas_sel_actualizacion'] = None
        self._actualizar_seleccion_gestion_cm()

    def _calcular_estado_acciones_rapidas(self):
        """Habilita/deshabilita las acciones rápidas según la cantidad de
        filas seleccionadas en new_ui_table, sin importar la sub-pestaña
        activa ni la fuente de datos (df_base o CasosBajaCM.csv): alcanza
        con el conteo de filas seleccionadas.

        - 0 seleccionadas: todo deshabilitado.
        - 1 seleccionada: todo habilitado.
        - Varias seleccionadas: "Enviar correo" y "Enviar a operaciones" se
          habilitan (soportan múltiples VIN); "Editar Unidad" y "Agregar
          contacto" se deshabilitan (aplican a una sola unidad/CDB a la
          vez -- ver conversación con el usuario, fases 3 y 4).

        "Enviar a operaciones" queda además siempre deshabilitado en "Por
        gestionar" y "Gestionar CM" (ver _NEW_UI_SUBTAB_POR_GESTIONAR /
        _NEW_UI_SUBTAB_REVISION_CM): en "Por gestionar" el camino correcto
        es Editar Unidad; en "Gestionar CM" ya existe "Confirmar baja". En
        "Ofrecer y reactivar" (28-09-2026, a pedido explícito) queda
        deshabilitado salvo que la tarjeta KPI "Aún Conectada" sea el
        filtro activo de esa sub-pestaña (unidades que todavía no se
        desconectaron físicamente y a las que tiene sentido reofrecer el
        servicio).

        "Confirmar baja" sigue exclusivo de "Gestionar CM", pero además
        (28-09-2026, a pedido explícito) solo se habilita si TODAS las
        filas seleccionadas son casos ORIGEN_CASO = Ausencia de 3PC: el
        equipo no decide la baja de un contrato Expired, solo avisa (ver
        "Exportar lista" y docs/07).

        "Agregar contacto" además cambia de color según si el CDB del VIN
        seleccionado ya tiene contacto en contactos.xlsx (ver
        _cdb_tiene_contacto/_aplicar_estilo_agregar_contacto): azul si
        tiene, rojo si no, neutro si no hay exactamente un VIN
        seleccionado."""
        n_seleccionadas = len(self._filas_seleccionadas())
        self.btn_accion_cm_enviar_correo.setEnabled(n_seleccionadas >= 1)
        self.btn_accion_editar_unidad.setEnabled(n_seleccionadas == 1)
        self.btn_accion_agregar_contacto.setEnabled(n_seleccionadas == 1)

        subtab_activa = getattr(self, '_new_ui_active_subtab', 0)
        activa_por_gestionar = subtab_activa == self._NEW_UI_SUBTAB_POR_GESTIONAR
        activa_cm = subtab_activa == self._NEW_UI_SUBTAB_REVISION_CM
        activa_ofrecer_reactivar = subtab_activa == self._NEW_UI_SUBTAB_OFRECER_REACTIVAR
        filtro_conectada_activo = self._new_ui_kpi_filtro_por_subtab.get(subtab_activa) == 'conectadas'
        permite_ofrecer_reactivar = not activa_ofrecer_reactivar or filtro_conectada_activo
        self.btn_accion_enviar_operaciones.setEnabled(
            n_seleccionadas >= 1 and not activa_por_gestionar and permite_ofrecer_reactivar
        )
        if activa_por_gestionar:
            tooltip_enviar_operaciones = "No corresponde en \"Por gestionar\": usa \"Editar contrato\", que ya deriva la unidad a Operaciones."
        elif activa_ofrecer_reactivar and not filtro_conectada_activo:
            tooltip_enviar_operaciones = "Filtra por la tarjeta \"Aún Conectada\" para habilitar esta acción en \"Ofrecer y reactivar\"."
        else:
            tooltip_enviar_operaciones = ""
        self.btn_accion_enviar_operaciones.setToolTip(tooltip_enviar_operaciones)
        self.btn_accion_enviar_operaciones.setVisible(not activa_ofrecer_reactivar)

        vins_seleccion, casos_seleccion = self._obtener_vins_seleccionados() if n_seleccionadas >= 1 else ([], {})
        editable_en_bloque = self._puede_editar_en_bloque(vins_seleccion) if n_seleccionadas >= 2 else False
        self.btn_accion_editar_unidad.setEnabled(n_seleccionadas == 1 or editable_en_bloque)
        self.btn_accion_editar_unidad._titulo_lbl.setText("Editar contratos" if editable_en_bloque else "Editar contrato")
        self._actualizar_boton_a_conversion(vins_seleccion, casos_seleccion)
        self._actualizar_acciones_contrato_cerrado(vins_seleccion)
        self._actualizar_boton_fecha_baja()
        self._actualizar_ficha_unidad(vins_seleccion)
        self._mostrar_panel_acciones(n_seleccionadas >= 1)

        if n_seleccionadas == 1:
            cdb, _ = self._resolver_cdb_razon_social(vins_seleccion[0]) if vins_seleccion else ('', '')
            self._aplicar_estilo_agregar_contacto(self._cdb_tiene_contacto(cdb) if cdb else False)
        else:
            self._aplicar_estilo_agregar_contacto(None)

        confirmar_baja_permitido = False
        tooltip_confirmar_baja = ""
        if activa_cm and n_seleccionadas >= 1:
            confirmar_baja_permitido = bool(casos_seleccion) and all(
                str(fila.get('ORIGEN_CASO', '')).strip().upper() == cm_bajas_service.ORIGEN_CASO_AUSENCIA_3PC
                for fila in casos_seleccion.values()
            )
            if not confirmar_baja_permitido:
                tooltip_confirmar_baja = "Confirmar baja solo aplica a casos de Ausencia de 3PC. Para Expired, usa \"Editar contrato\" o \"Exportar lista\"."
        self.btn_accion_cm_confirmar_baja.setEnabled(confirmar_baja_permitido)
        self.btn_accion_cm_confirmar_baja.setToolTip(tooltip_confirmar_baja)
        self.btn_accion_cm_marcar_pendiente.setEnabled(
            activa_cm and bool(self._vins_por_marcar_pendiente(casos_seleccion)))

        # En Oportunidades CM no va "Agregar contacto" y arriba de todo van "Pasar a CM" y "Limpiar datos CM"
        self.btn_accion_agregar_contacto.setVisible(not activa_cm)
        filas_cm = self._filas_base_por_vin(vins_seleccion) if activa_cm and n_seleccionadas >= 1 else pd.DataFrame()
        cambios_pasar = self._cambios_pasar_a_cm_de_filas(filas_cm) if not filas_cm.empty else {}
        self.btn_accion_cm_pasar_a_cm.setEnabled(bool(cambios_pasar))
        formas = {c[COL_FORMA_CONTRATO] for c in cambios_pasar.values()}
        self.btn_accion_cm_pasar_a_cm._titulo_lbl.setText(f"Pasar a {formas.pop()}" if len(formas) == 1 else "Pasar a CM")
        self.btn_accion_cm_limpiar.setEnabled(
            not filas_cm.empty and bool(ct_service.construir_cambios_limpieza_cm(filas_cm)))

        self._actualizar_boton_marcar_vencido()
        self._actualizar_boton_marcar_vigente()
        self._actualizar_boton_renovar()
        self._actualizar_boton_papelera()
        self._actualizar_boton_arreglar_tipo_fact()
        self._actualizar_boton_fecha_real()
        self._renovar_actualizar_seleccion()

    def _unidades_pendientes_marcar_vencido(self, df_bandeja):
        # Solo unidades que cumplen la regla de Vencidos (fecha vencida o ya
        # marcadas) y cuyo ESTADO COMERCIAL es corregible a Vencido.
        if df_bandeja is None or df_bandeja.empty or COL_ESTADO_COMERCIAL not in df_bandeja.columns:
            return df_bandeja.iloc[0:0] if df_bandeja is not None else pd.DataFrame()
        estado = df_bandeja[COL_ESTADO_COMERCIAL].astype(str).str.strip().str.upper()
        en_vencidos = df_bandeja.index.isin(comercial_services.filtrar_vencidos(df_bandeja).index)
        return df_bandeja[estado.isin(ESTADOS_COMERCIAL_CORREGIBLES_A_VENCIDO) & en_vencidos]

    def _pendientes_marcar_vencido_seleccionados(self):
        """Subconjunto de las filas seleccionadas que se pueden marcar como
        Vencido (fecha expirada y estado corregible). Las demás filas
        seleccionadas se ignoran."""
        df_bandeja = getattr(self, '_new_ui_bandeja_actual_df', None)
        if df_bandeja is None or df_bandeja.empty or 'VIN' not in df_bandeja.columns:
            return pd.DataFrame()
        vins_seleccion, _ = self._obtener_vins_seleccionados()
        if not vins_seleccion:
            return df_bandeja.iloc[0:0]
        df_pendientes = self._unidades_pendientes_marcar_vencido(df_bandeja)
        vin_norm = df_pendientes['VIN'].astype(str).str.strip().str.upper()
        return df_pendientes[vin_norm.isin(set(vins_seleccion))]

    def _unidad_vigente_en_curso(self, vin):
        # Vigente / Activación Pendiente y con contrato aún no vencido por
        # fecha: el caso que antes vivía en "Vigentes" (baja anticipada,
        # edición restringida).
        df_base = getattr(self.legacy, 'df_base', None)
        if df_base is None or df_base.empty or 'VIN' not in df_base.columns:
            return False
        pos = self._posicion_vin_en_df(df_base, vin)
        if pos is None:
            return False
        fila = df_base.iloc[[pos]]
        return not comercial_services.filtrar_vigentes(fila).empty and comercial_services.filtrar_vencidos(fila).empty

    def _actualizar_boton_marcar_vencido(self):
        """"Marcar como Vencido" se habilita solo si, estando en "Renovar
        clientes", hay al menos una fila seleccionada con fecha de término
        expirada y ESTADO COMERCIAL corregible a Vencido. Se llama tanto
        desde _actualizar_estado_acciones_rapidas (cambios de
        selección/sub-pestaña) como desde _refresh_new_ui_data (cambios de
        datos: búsqueda, guardado, recarga)."""
        activa_vencidos = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
        hay_pendientes = activa_vencidos and not self._pendientes_marcar_vencido_seleccionados().empty
        self.btn_accion_marcar_vencido.setEnabled(hay_pendientes)

    def _actualizar_boton_marcar_vigente(self):
        """"Marcar como Vigente" no depende de la selección de la tabla (ver
        _build_new_ui_acciones_rapidas_solo_vigentes): se habilita solo si,
        estando en "Vigentes", la bandeja actual tiene al menos un vehículo
        con ESTADO COMERCIAL = "Activación Pendiente" Y ESTADO DE
        ACTIVACIÓN ACTUAL = "Conectado". Mismo patrón que
        _actualizar_boton_marcar_vencido."""
        activa_vigentes = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES
        hay_pendientes = False
        if activa_vigentes:
            df_bandeja = getattr(self, '_new_ui_bandeja_actual_df', None)
            if df_bandeja is not None:
                hay_pendientes = not comercial_services.pendientes_marcar_vigente(df_bandeja).empty
        self.btn_accion_marcar_vigente.setEnabled(activa_vigentes and hay_pendientes)

    _TEXTO_TODOS_PERIODOS = "Todos los periodos"
    _FILTROS_COLUMNA = (
        ('ESTADO COMERCIAL', "Estado comercial", 'fa5s.clipboard-check'),
        ('FORMA DE CONTRATO', "Forma de contrato", 'fa5s.file-signature'),
        ('TIPO DE FACTURACION', "Tipo de facturación", 'fa5s.file-invoice-dollar'),
        ('TIPO DE SERVICIO', "Tipo de servicio", 'fa5s.concierge-bell'),
    )

    def _on_correos_registrados(self):
        """Un correo recién registrado cambia los KPI de contacto de
        "Recuperar clientes": se repinta al instante si esa pestaña está a la
        vista (si no, se actualiza al volver a ella)."""
        try:
            if self.new_ui_tab.isVisible() and getattr(self, '_new_ui_active_subtab', 0) in (1, 2, 3):
                self._refresh_new_ui_data()
        except Exception:
            pass

    def _on_data_ready_refrescar_new_ui(self):
        """Conectada a data_manager.data_ready (DataManager es singleton,
        ver __new__ en data_manager.py): como la señal es compartida entre
        instancias, un ComercialModule ya destruido a nivel C++ (ej. el de
        un test anterior) puede seguir conectado cuando otra instancia
        posterior emite data_ready, y llamar a _refresh_new_ui_data sobre
        widgets ya eliminados (o con datos que ya no calzan con lo que esa
        instancia vieja espera) puede lanzar cualquier excepción -- mismo
        riesgo y mismo patrón de defensa (except Exception genérico) que
        _on_global_data_ready en _ComercialModuleLegacy (más arriba).

        Si la pestaña no está visible no se repinta: al volver a ella,
        _on_new_ui_tab_refresh_if_dirty/_on_internal_tab_changed ya la
        refrescan (y con self.legacy.df_base al día)."""
        try:
            if not self.new_ui_tab.isVisible():
                return
            self._refresh_new_ui_data()
        except Exception:
            pass

    def _refresh_new_ui_data(self):
        """Repinta la bandeja; los filtros que se piden varias veces sobre el mismo df_base se calculan una sola vez
        (ver comercial_services.memo_de_refresco)."""
        self.__dict__['_n_refrescos'] = self.__dict__.get('_n_refrescos', 0) + 1
        with comercial_services.memo_de_refresco():
            self._refresh_new_ui_data_sin_memo()

    def _refresh_new_ui_data_sin_memo(self):
        """Repinta KPIs y bandeja de la Nueva interfaz con los datos que
        _ComercialModuleLegacy ya tiene cargados (self.legacy.df_base), sin
        pedirle nada nuevo a DataManager ni duplicar la carga. La bandeja se
        filtra por la regla de negocio de la sub-pestaña activa (ver
        _NEW_UI_SUBTAB_FILTERS), despues por el texto de busqueda (local o
        el que haya dejado MainWindow._on_global_search en
        new_ui_search_input) sobre los datos completos, y solo al final se
        recorta a las columnas configuradas para esa sub-pestaña
        (NEW_UI_SUBTAB_COLUMNS) -- asi una columna oculta como VIN sigue
        siendo buscable aunque no se muestre."""
        active_subtab = getattr(self, '_new_ui_active_subtab', 0)
        if active_subtab != self._NEW_UI_SUBTAB_REVISION_CM:
            self._actualizar_barra_gestion_cm()
        self._actualizar_boton_marcar_vencidos_barra()
        self.lbl_titulo_bandeja.setText(
            "Avisos de gestión" if active_subtab == self._NEW_UI_SUBTAB_AVISOS
            else self._NEW_UI_SUBTAB_NOMBRES[active_subtab]
        )
        if active_subtab == self._NEW_UI_SUBTAB_AVISOS:
            # Las tarjetas KPI conservan los valores de la sub-pestaña real
            self._refresh_bandeja_avisos()
            return
        columnas = self.NEW_UI_SUBTAB_COLUMNS.get(active_subtab, self.NEW_UI_SUBTAB_COLUMNS[0])
        self._aplicar_kpi_spec_actual(active_subtab)
        self._actualizar_seleccion_visual_kpi(active_subtab)

        df_base = self._df_base_por_periodo(getattr(self.legacy, 'df_base', None))
        self._actualizar_contadores_subtabs(df_base)
        if df_base is None or df_base.empty:
            self._salir_vista_agrupada()
            self.new_ui_model.set_data(pd.DataFrame(columns=columnas))
            self._new_ui_revision_cm_df = pd.DataFrame()
            self._new_ui_bandeja_actual_df = pd.DataFrame()
            for lbl in self.new_ui_kpi_labels.values():
                lbl.setText("0")
            self._actualizar_barras_kpi({})
            self._actualizar_estado_acciones_rapidas()
            return

        # "Revisión CM" no sale de df_base (PruebasFM): sale de
        # CasosBajaCM.csv, con su propio esquema de columnas (ver
        # _construir_df_revision_cm), y no tiene TÉRMINO CONTRATO -- no
        # encaja en el contrato "filtro(df_base) -> subset de df_base" de
        # _NEW_UI_SUBTAB_FILTERS ni en calcular_kpis_vigencia(), asi que se
        # resuelve aparte y se corta la funcion aqui.
        if active_subtab == self._NEW_UI_SUBTAB_REVISION_CM:
            df_bandeja = self._construir_df_revision_cm()

            search_text = self.new_ui_search_input.text().strip().lower()
            if search_text and not df_bandeja.empty:
                mascara = comercial_services.construir_mascara_busqueda(df_bandeja, search_text, COLUMNAS_BUSQUEDA_REVISION_CM)
                df_bandeja = df_bandeja[mascara]

            # Los KPI de vigencia (vencidas/activas/x-vencer) no aplican a
            # esta bandeja: no hay TÉRMINO CONTRATO en CasosBajaCM.csv (ver
            # comercial_services.calcular_kpis_gestionar_cm, desglose por
            # ORIGEN_CASO y PAGO CM en riesgo).
            razones_cm = self._razones_contactadas_por_correo()
            kpis_cm = comercial_services.calcular_kpis_gestionar_cm(df_bandeja, razones_cm)
            for key, lbl in self.new_ui_kpi_labels.items():
                lbl.setText(str(kpis_cm.get(key, 0)))
            self._actualizar_barras_kpi(kpis_cm)

            # Las tarjetas conservan sus cifras al filtrar: el filtro por
            # tarjeta se aplica después de calcularlas.
            filtro_cm = self._new_ui_kpi_filtro_por_subtab.get(active_subtab)
            if filtro_cm and filtro_cm != 'total' and not df_bandeja.empty:
                masks_cm = comercial_services.obtener_masks_kpi_gestionar_cm(df_bandeja, razones_cm)
                if filtro_cm in masks_cm:
                    df_bandeja = df_bandeja[masks_cm[filtro_cm]]

            df_bandeja = self._aplicar_filtro_gestion_cm(df_bandeja)
            self._new_ui_revision_cm_completo = df_bandeja
            df_bandeja, columnas_vista, en_grupos = self._preparar_vista_agrupada(active_subtab, df_bandeja, columnas)
            df_bandeja = self.new_ui_table.apply_sort(df_bandeja).reset_index(drop=True)
            # Guardado completo (con VIN y CASO_ID, aunque no se muestren)
            # para que _on_accion_cm_confirmar_baja_clicked pueda resolver
            # la fila seleccionada del modelo (que solo recibe las columnas
            # visibles) a su caso real. El orden coincide con el que recibe
            # el modelo porque se guarda justo antes de recortar columnas.
            self._new_ui_revision_cm_df = pd.DataFrame() if en_grupos else df_bandeja
            self._new_ui_grupos_df = df_bandeja if en_grupos else None
            cols_presentes = [c for c in columnas_vista if c in df_bandeja.columns]
            df_mostrar = df_bandeja[cols_presentes].copy()
            # Solo presentación: PAGO CM llega como texto crudo desde
            # CasosBajaCM.csv (ej. '15000'). _new_ui_revision_cm_df (arriba)
            # guarda el valor original -- _on_accion_cm_confirmar_baja_clicked
            # y el CSV no se ven afectados por este formateo.
            for col_pago in ('PAGO CM', 'ULTIMO PAGO CM'):
                if col_pago in df_mostrar.columns:
                    df_mostrar[col_pago] = df_mostrar[col_pago].apply(_formatear_pago_cm_para_mostrar)
            self.new_ui_model.set_data(df_mostrar)
            _aplicar_anchos_columnas_new_ui(
                self.new_ui_table, cols_presentes,
                anchos_fijos=self._anchos_vista_grupos(cols_presentes) if en_grupos else NEW_UI_SUBTAB_COLUMN_WIDTHS.get(active_subtab),
            )
            self._actualizar_barra_gestion_cm()
            self._actualizar_estado_acciones_rapidas()
            return

        df_bandeja = self._filtrar_subtab_con_cache(active_subtab, df_base)
        if active_subtab == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            self.__dict__['_bandeja_renovar_completa'] = df_bandeja

        # Filtro por tarjeta KPI clicada (28-09-2026, a pedido explícito,
        # reemplaza el antiguo filtro de botones "Todos/Vigente/Vencido/
        # Activación Pendiente" exclusivo de "Vencidos"): se aplica DESPUÉS
        # del filtro de negocio de la sub-pestaña, nunca lo reemplaza -- ver
        # _NEW_UI_KPI_MASK_FUNCS/_on_new_ui_kpi_card_clicked. "Renovaciones"
        # es la única sub-pestaña cuyas máscaras necesitan además
        # contactos.xlsx (tarjeta "Sin contactos").
        kwargs_extra_kpi = {}
        if active_subtab in (1, 2):
            kwargs_extra_kpi['razones_contactadas'] = self._razones_contactadas_por_correo()

        search_text = self.new_ui_search_input.text().strip().lower()
        if search_text:
            mascara = comercial_services.construir_mascara_busqueda(
                df_bandeja, search_text, COLUMNAS_BUSQUEDA_COMERCIAL, COLUMNAS_BUSQUEDA_EXACTAS_COMERCIAL)
            df_bandeja = df_bandeja[mascara]

        # Las tarjetas conservan sus cifras al filtrar: se calculan antes del filtro de tarjeta.
        if active_subtab == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            kpis = comercial_services.calcular_kpis_renovar_clientes(df_bandeja, masks=self._masks_renovar(df_bandeja))
        else:
            kpi_func = self._NEW_UI_KPI_FUNCS.get(active_subtab, comercial_services.calcular_kpis_vigencia)
            kpis = kpi_func(df_bandeja, **kwargs_extra_kpi)
        for key, lbl in self.new_ui_kpi_labels.items():
            lbl.setText(str(kpis.get(key, 0)))

        mask_func = self._NEW_UI_KPI_MASK_FUNCS.get(active_subtab)
        if active_subtab == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            mask_func = lambda d, **_kw: self._masks_renovar(d)
        filtro_key = self._new_ui_kpi_filtro_por_subtab.get(active_subtab)
        if mask_func is not None and filtro_key and filtro_key != 'total':
            masks = mask_func(df_bandeja, **kwargs_extra_kpi)
            if filtro_key in masks:
                df_bandeja = df_bandeja[masks[filtro_key]]
        self._actualizar_barras_kpi(kpis)

        if "DÍAS RESTANTES" in columnas:
            clasif = comercial_services.clasificar_vigencia_contrato(df_bandeja)
            df_bandeja = df_bandeja.copy()
            df_bandeja["DÍAS RESTANTES"] = clasif["dias_restantes"].apply(comercial_services.formatear_dias_restantes)

            # Orden por defecto (config aprobada con el usuario) mientras no
            # haya un orden manual activo (ver VolvoTableWidget.
            # has_active_sort/apply_sort, más abajo). El bloque de "por
            # vencer" (no vencido) siempre va primero, ordenado por el que
            # vence más pronto. El bloque de "ya vencido" va al final,
            # siempre con el más vencido primero (_NEW_UI_VENCIDOS_
            # RECIENTES_PRIMERO queda vacío desde que se eliminó la
            # sub-pestaña "Vencimientos"). Un clic en "Ordenar A -> Z" del
            # encabezado reemplaza todo esto por el orden genérico numérico
            # ascendente (ver comercial_services.parsear_dias_restantes y
            # VolvoTableWidget._parse_number_like).
            if not self.new_ui_table.has_active_sort():
                mask_vencido = clasif['vencido']
                recientes_primero = active_subtab in self._NEW_UI_VENCIDOS_RECIENTES_PRIMERO

                df_por_vencer = df_bandeja[~mask_vencido].assign(_dias=clasif['dias_restantes'][~mask_vencido]) \
                    .sort_values('_dias', na_position='last').drop(columns='_dias')
                df_vencido = df_bandeja[mask_vencido].assign(_dias=clasif['dias_restantes'][mask_vencido]) \
                    .sort_values('_dias', ascending=not recientes_primero, na_position='last').drop(columns='_dias')

                df_bandeja = pd.concat([df_por_vencer, df_vencido])

        bandeja_completa = df_bandeja
        df_bandeja, columnas_vista, en_grupos = self._preparar_vista_agrupada(active_subtab, df_bandeja, columnas)
        df_bandeja = self.new_ui_table.apply_sort(df_bandeja)
        self._new_ui_grupos_df = df_bandeja if en_grupos else None

        # Guardado completo (con VIN, aunque no se muestre) para que
        # _obtener_vins_seleccionados pueda resolver la fila seleccionada
        # del modelo (que solo recibe las columnas visibles) a su VIN real
        # en "Por gestionar"/"Renovaciones"/"Gestionar Bajas" -- mismo
        # mecanismo que _new_ui_revision_cm_df para "Gestionar CM". El
        # orden coincide con el que recibe el modelo porque se guarda justo
        # antes de recortar columnas.
        # En la vista de grupos no hay filas-unidad: las acciones masivas
        # ("Marcar como Vencido/Vigente") siguen viendo toda la bandeja.
        self._new_ui_bandeja_actual_df = bandeja_completa if en_grupos else df_bandeja

        cols_presentes = [c for c in columnas_vista if c in df_bandeja.columns]
        self.new_ui_model.set_data(df_bandeja[cols_presentes])
        _aplicar_anchos_columnas_new_ui(
            self.new_ui_table, cols_presentes,
            anchos_fijos=self._anchos_vista_grupos(cols_presentes) if en_grupos else NEW_UI_SUBTAB_COLUMN_WIDTHS.get(active_subtab),
        )
        self._actualizar_estado_acciones_rapidas()

    def _masks_renovar(self, df):
        """Máscaras de "Renovar contratos" recortadas a `df`. Cada una depende
        solo de su fila, así que se calculan una vez sobre la sub-pestaña
        completa (mientras su filtro siga en caché) y no en cada repintado."""
        completa = self.__dict__.get('_bandeja_renovar_completa')
        if completa is None or not completa.index.is_unique or not df.index.isin(completa.index).all():
            return comercial_services.obtener_masks_kpi_renovar_clientes(df)
        cache = self.__dict__.get('_cache_masks_renovar')
        if cache is None or cache[0] is not completa:
            cache = (completa, comercial_services.obtener_masks_kpi_renovar_clientes(completa))
            self.__dict__['_cache_masks_renovar'] = cache
        return {clave: mascara.loc[df.index] for clave, mascara in cache[1].items()}

    def _cdbs_por_razon_actual(self):
        """CDB comerciales distintos de cada RAZÓN SOCIAL sobre toda la base;
        se recalcula solo cuando cambia df_base."""
        df = getattr(self.legacy, 'df_base', None)
        cache = self.__dict__.get('_cache_cdbs_por_razon')
        if cache is None or cache[0] is not df or cache[1] != (0 if df is None else len(df)):
            cache = (df, 0 if df is None else len(df), comercial_services.cdbs_por_razon_social(df))
            self.__dict__['_cache_cdbs_por_razon'] = cache
        return cache[2]

    def _cdb_referencia_actual(self):
        """CDB más frecuente por RAZÓN SOCIAL sobre toda la base (no solo la
        bandeja); se recalcula solo cuando cambia df_base."""
        df = getattr(self.legacy, 'df_base', None)
        cache = self.__dict__.get('_cache_cdb_referencia')
        if cache is None or cache[0] is not df or cache[1] != (0 if df is None else len(df)):
            cache = (df, 0 if df is None else len(df), comercial_services.cdb_referencia_por_razon_social(df))
            self.__dict__['_cache_cdb_referencia'] = cache
        return cache[2]

    def _razones_contactadas_por_correo(self):
        """Clientes con correo enviado en la ventana de contacto (ver
        comercial_services.DIAS_VENTANA_CONTACTO_CORREO); se vuelve a leer
        el historial solo si cambió el archivo o el día."""
        from src.services import mail_registro
        ruta = mail_registro.get_historial_csv_path()
        try:
            mtime = os.path.getmtime(ruta)
        except OSError:
            mtime = None
        clave = (ruta, mtime, datetime.now().date())
        cache = self.__dict__.get('_cache_razones_contactadas')
        if cache is None or cache[0] != clave:
            razones = comercial_services.obtener_razones_contactadas_por_correo(mail_registro.leer_historial())
            cache = (clave, razones)
            self.__dict__['_cache_razones_contactadas'] = cache
        return cache[1]

    def _actualizar_contadores_subtabs(self, df_base):
        """Unidades de cada sub-pestaña junto a su nombre (sin búsqueda ni
        filtro de tarjeta)."""
        hay_datos = df_base is not None and not df_base.empty
        for i, nombre in enumerate(self._NEW_UI_SUBTAB_NOMBRES):
            n = 0
            if hay_datos:
                try:
                    if i == self._NEW_UI_SUBTAB_REVISION_CM:
                        n = self._contar_casos_cm()
                    else:
                        n = len(self._filtrar_subtab_con_cache(i, df_base))
                except Exception:
                    n = 0
            badge = self._badges_subtabs[i]
            if badge.text() != str(n):
                badge.setText(str(n))
                badge.setFixedWidth(max(34, badge.fontMetrics().horizontalAdvance(str(n)) + 24))
                self.new_ui_subtabs.setTabText(i, nombre)

    def _estilizar_badges_subtabs(self, *_):
        actual = self.new_ui_subtabs.currentIndex()
        for i, badge in enumerate(self._badges_subtabs):
            fondo, texto = ("#E3E8F0", "#1B2B4E") if i == actual else ("#EEF2F6", estilo_com.APAGADO)
            badge.setStyleSheet(
                f"background-color: {fondo}; color: {texto}; border-radius: 10px; "
                "padding: 0px 8px; font-size: 11px; font-weight: bold; min-width: 10px;"
            )

    def _contar_casos_cm(self):
        ruta = config.settings.CASOS_BAJA_CM_PATH
        try:
            mtime = os.path.getmtime(ruta)
        except OSError:
            mtime = None
        base = getattr(self.legacy, 'df_base', None)
        clave = (ruta, mtime, id(base), len(base) if base is not None else 0)
        cache = self.__dict__.get('_cache_contador_cm')
        if cache is None or cache[0] != clave:
            cache = (clave, len(self._construir_df_revision_cm()))
            self.__dict__['_cache_contador_cm'] = cache
        return cache[1]

    def __getattr__(self, name):
        legacy = self.__dict__.get('legacy')
        if legacy is not None and hasattr(legacy, name):
            return getattr(legacy, name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __setattr__(self, name, value):
        if name in ComercialModule._OWN_ATTRS or 'legacy' not in self.__dict__:
            super().__setattr__(name, value)
        else:
            setattr(self.legacy, name, value)

    def __delattr__(self, name):
        # unittest.mock.patch.object() restaura vía delattr (no setattr)
        # cuando el atributo parcheado no vivia en el __dict__ propio del
        # target -- que es siempre el caso aqui, porque __setattr__ ya lo
        # reenvia a self.legacy. Sin este espejo, ese delattr fallaria con
        # AttributeError contra el contenedor en vez de limpiar en legacy.
        if name in ComercialModule._OWN_ATTRS or 'legacy' not in self.__dict__:
            super().__delattr__(name)
        else:
            delattr(self.legacy, name)
