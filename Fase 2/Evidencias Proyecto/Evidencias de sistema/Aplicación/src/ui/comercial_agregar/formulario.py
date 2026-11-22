"""Formulario de unidad (alta y edición de contratos) compartido por Comercial, General, Contratos CM, JustTime y Facturación Manual."""
import hashlib
import os
import re
from collections import Counter
from datetime import datetime
import pandas as pd
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox, QPushButton, QMessageBox, QFrame, QCompleter, QApplication, QWidget, QTabWidget, QSizePolicy, QListView, QProgressBar, QCheckBox
from PyQt6.QtCore import Qt, QTimer, QRegularExpression, pyqtSignal
from PyQt6.QtGui import QRegularExpressionValidator, QFont, QCursor
from src.ui.compartido.comercial_estilo import ComboTarjeta
from src.ui.compartido.combo_multiple import ComboMultiple
from src.ui.compartido.guardado_overlay import crear_tarjeta_carga
import qtawesome as qta
from src.services import catalogos_service, comercial_services, ejecutivos_service
from src.theme.theme_manager import ThemeManager
from src.theme.colors import DANGER
from src.core.constants import ETAPA_GESTION_COLORES, TIPO_FACTURACION_DISPLAY_MAP, TIPO_CM_OPCIONES, ESTADO_CM_OPCIONES, JUSTTIME_ESTADO_OPCIONES, JUSTTIME_ESTADO_NO_APLICA, VALOR_TIPO_FACT_FACTURACION_MANUAL
from src.ui.comercial_agregar.base import (  # noqa: F401 (se reexportan: otros módulos los importan desde aquí)
    _FiltroHabilitado,
    _partir_tipo_servicio,
    _ORDEN_TIPO_FACTURACION,
    _ORDEN_TIPO_FACTURACION_SIN_GUION,
    _resource_path,
    _COMBO_CHEVRON_PATH,
    _RESUMEN_GRUPOS,
    _EtiquetaElidida,
    _ETIQUETAS_CAMPO,
    _MESES,
    _ANCHO_FIJO,
    _CAMPOS_BLOQUE_JUSTTIME,
    _ESTADOS_COMERCIALES_FIN,
    _ESTADOS_JT_CORREGIBLES,
    _CAMPOS_BLOQUE_CM,
    _CAMPOS_COMERCIAL_BLOQUEABLES_ALTA_GENERAL,
    _CAMPOS_OPERACIONES_BLOQUEABLES_ALTA_GENERAL,
    _CAMPOS_JUSTTIME_CM_BLOQUEABLES_ALTA_GENERAL,
    _CAMPOS_CONDICION_CONTRATO,
    _CAMPOS_RENOVACION_CONSERVADOS,
    _CAMPOS_OBLIGATORIOS,
    _QSS_CHECK_SERVICIO,
    _DEFAULTS_INICIALES,
    COLUMNAS_EXTRA_DEFAULT_GUION,
    _tipo_facturacion_default_para_forma_contrato,
    _SelectorAnio,
)
from src.ui.comercial_agregar.reglas import _ReglasFormularioMixin
from src.ui.comercial_agregar.justtime import _JustTimeFormularioMixin
from src.ui.comercial_agregar.facturacion import _TipoFacturacionFormularioMixin
from src.ui.comercial_agregar.calculos import _CalculosFormularioMixin
from src.ui.comercial_agregar.lote import _LoteFormularioMixin
from src.ui.comercial_agregar.varias_unidades import _VariasUnidadesMixin


class _ComercialUnidadFormMixin(_ReglasFormularioMixin, _JustTimeFormularioMixin, _TipoFacturacionFormularioMixin, _CalculosFormularioMixin, _LoteFormularioMixin, _VariasUnidadesMixin):
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
        self.dropdown_options = catalogos_service.opciones_formulario(dropdown_options)
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
        # El ejecutivo sugerido sale solo del contrato actual de cada VIN: uno inactivo cuyos clientes ya se
        # reasignaron no debe volver a ofrecerse por un contrato anterior
        if 'VIN' in df.columns:
            df_aux['_actual'] = df.index.isin(comercial_services.contratos_actuales(df).index)
        else:
            df_aux['_actual'] = True
        df_aux = df_aux[df_aux['RUT'] != ""]

        # Un solo recorrido sobre listas (antes groupby por RUT: ~4x más
        # lento). Claves en orden alfabético, igual que groupby.
        normalizados, grupos = {}, {}
        for rut, razon, cdb, ejecutivo, industria, actual in zip(
                df_aux['RUT'].tolist(), df_aux['RAZÓN SOCIAL'].tolist(), df_aux['CDB'].tolist(),
                df_aux['EJECUTIVO'].tolist(), df_aux['INDUSTRIA'].tolist(), df_aux['_actual'].tolist()):
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
            if ejecutivo and actual: g[2].add(ejecutivo)
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
            presentes = [c for c in cols + ['VIN', 'ID'] if c in df.columns]
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
        if self.modo_edicion and self.cantidad_multiple > 1:
            return f"Editar {self.cantidad_multiple} contratos", (
                "Los datos de Comercial y JustTime & CM se aplican a todas las unidades seleccionadas.")
        if self.modo_nuevo_contrato and self.cantidad_multiple > 1:
            return f"Crear {self.cantidad_multiple} contratos", (
                "Los datos de Comercial y JustTime & CM se aplican a todas las unidades seleccionadas. "
                "Al guardar se crea un contrato nuevo por unidad y entran a Activación de Operaciones.")
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
            return "Editar Contrato", f"{prefijo}Modifique los datos del contrato y guarde los cambios."
        if self.progreso:
            return "Importar desde Power BI", "Complete o revise la información de este registro antes de continuar."
        if self._modo_varias:
            return "Crear varias unidades", "Los datos de la ficha se aplican a todos los VIN de la lista."
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
        tarjeta_unidad = self._build_section(
            'unidad', "2. Información de la unidad", "Datos técnicos del camión.",
            [[('VIN', 'lineedit'), ('CHASIS', 'readonly'), ('MODELO', 'combo'), ('CDB', 'lineedit')]],
            padre=pagina_empresa
        )
        layout_empresa.addWidget(tarjeta_unidad)
        self._construir_boton_varias(tarjeta_unidad)
        self._panel_vins = self._construir_panel_vins(tarjeta_unidad, layout_empresa)
        layout_empresa.addStretch(1)

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
        btn_layout.addWidget(self.btn_save)
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
        """Combo de complementos (CIV, SZ...) bajo el combo de TIPO DE SERVICIO."""
        fila = QVBoxLayout()
        fila.setSpacing(4)
        etiqueta = QLabel("Complementos")
        etiqueta.setStyleSheet("background: transparent; border: none;")
        self.combo_complementos = ComboMultiple("Complementos", catalogos_service.complementos)
        ThemeManager.apply_combo_box(self.combo_complementos)
        self.combo_complementos.setSizePolicy(QSizePolicy.Policy.Ignored, self.combo_complementos.sizePolicy().verticalPolicy())
        fila.addWidget(etiqueta)
        fila.addWidget(self.combo_complementos)
        self._filtro_checks_tipo_servicio = _FiltroHabilitado(combo, [self.combo_complementos])
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
                if not hasattr(self, '_etiquetas_campo'):
                    self._etiquetas_campo = {}
                self._etiquetas_campo[f_name] = label
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
        lay_barra.addSpacing(8)
        lay_barra.addWidget(self._btn_paso_atras)
        lay_barra.addWidget(self._btn_paso_siguiente)
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
        faltan = [c for c in sorted(self._obligatorios_activos())
                  if c in self.inputs and self._PASO_DE_CAMPO.get(c) == paso and not self._valor_widget(c)]
        if paso == 0 and self._modo_varias and not self._unidades_validas():
            faltan.append('VIN')
        return faltan

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
        if self._modo_varias:
            self._resumen_valores['VIN'].setText(f"{len(self._unidades_validas())} unidades")
        obligatorios = [c for c in self._obligatorios_activos() if c in self.inputs]
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
                inds_unicas = catalogos_service.industrias_formulario()
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

    def _validate_and_accept(self):
        # Guarda defensiva: el botón Guardar ya debería estar deshabilitado
        # mientras el VIN esté duplicado (ver _validar_vin_duplicado), pero
        # no se avanza igual si por algún motivo se llegó a llamar esto.
        if self._modo_varias:
            if not self._unidades_validas():
                QMessageBox.warning(self, "Sin unidades", "Pega al menos un VIN válido que no exista todavía en Comercial.")
                return
        elif self._vin_duplicado(self._valor_widget('VIN').upper()):
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

        obligatorios = self._obligatorios_activos()
        faltantes = [c for c in self.inputs.keys() if c in obligatorios and not self._valor_widget(c)]
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

        if self._modo_varias:
            omitidas = self._tabla_vins.rowCount() - len(self._unidades_validas())
            texto = (f"Se crearán {len(self._unidades_validas())} unidades nuevas con los datos de esta ficha.")
            if omitidas > 0:
                texto += f"\n\n{omitidas} línea(s) de la lista no se crearán (VIN incompleto, repetido o que ya existe)."
            confirmar = QMessageBox.question(
                self, "Crear unidades", texto + "\n\n¿Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if confirmar != QMessageBox.StandardButton.Yes:
                return
        elif self.cantidad_multiple > 1:
            if self.modo_edicion:
                titulo_confirmar = "Editar contratos"
                texto_confirmar = (f"Se modificarán {self.cantidad_multiple} contratos con los datos de Comercial y JustTime & CM "
                                   "de este formulario.\n\n¿Continuar?")
            elif self.modo_renovacion:
                titulo_confirmar = "Renovar contratos"
                texto_confirmar = (f"Se renovarán {self.cantidad_multiple} contratos con los datos de Comercial y JustTime & CM "
                                   "de este formulario. Cada contrato actual quedará como Renovado.\n\n¿Continuar?")
            else:
                titulo_confirmar = "Crear contratos"
                texto_confirmar = (f"Se crearán {self.cantidad_multiple} contratos nuevos con los datos de Comercial y JustTime & CM "
                                   "de este formulario y las unidades pasarán a Activación de Operaciones. Los contratos "
                                   "anteriores quedan en el historial.\n\n¿Continuar?")
            confirmar = QMessageBox.question(
                self, titulo_confirmar, texto_confirmar,
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
                base, complementos = _partir_tipo_servicio(valor)
                self._set_combo_valor_precargado(widget, base)
                self.combo_complementos.set_seleccion(complementos, emitir=False)
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
    varias_unidades_confirmadas = pyqtSignal(list)

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
        self._btn_varias.setVisible(not modo_edicion)

    def showEvent(self, event):
        # A propósito NO se llama _fit_to_screen() (heredado del mixin,
        # pensado para una ventana top-level): este widget vive embebido
        # dentro de la pestaña "Unidad nueva", redimensionarse/centrarse
        # contra la pantalla rompería el layout del contenedor.
        QWidget.showEvent(self, event)

    def _on_formulario_confirmado(self):
        if self._modo_varias:
            self.varias_unidades_confirmadas.emit(self._unidades_multiples())
            return
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
        for extra in (self.combo_periodo_mes, self.spin_periodo_anio, self.combo_complementos):
            extra.setEnabled(True)
        self._reiniciar_estado_contrato()
        self._restringir_estado_comercial_alta(False)
        # FORMA DE CONTRATO puede haber quedado con el catálogo recortado
        # por _sincronizar_tipo_facturacion_con_forma_contrato de una edición
        # anterior con restricciones -- _resetear_campos_a_default (llamado
        # justo después por resetear_para_crear/cargar_para_editar) vuelve a
        # dejar TIPO DE FACTURACION en su estado por defecto, así que no
        # hace falta reconstruirlo aquí aparte.

    def _exigir_forma_contrato_real(self, exigir, es_renovacion=False):
        """En "Nuevo contrato" la forma de contrato no puede ser "Sin
        Contrato" (solo entra así desde Power BI): se quita esa opción y el
        combo parte en "-" para obligar a elegir otra. Al renovar tampoco se
        ofrecen Revisar, Test ni Demo. Con `exigir` False vuelve el catálogo
        completo."""
        combo = self.inputs['FORMA DE CONTRATO']
        actual = combo.currentText().strip()
        opciones = [v for v in self.dropdown_options.get('FORMA DE CONTRATO', []) if v != '-']
        if exigir:
            excluidas = {'SIN CONTRATO', 'REVISAR', 'TEST', 'DEMO'} if es_renovacion else {'SIN CONTRATO'}
            opciones = ['-'] + [v for v in opciones if v.strip().upper() not in excluidas]
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
        for extra in (self.combo_periodo_mes, self.spin_periodo_anio, self.combo_complementos):
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
        self._set_modo_varias(False)
        self._btn_varias.setVisible(False)
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
        self._btn_varias.setVisible(True)

    def cargar_para_editar(self, datos_iniciales, restringir_activacion=False,
                            forzar_activacion_pendiente=False, restringir_vigentes=False, cantidad=1):
        """Precarga la unidad `datos_iniciales` en modo edición, con las
        mismas restricciones que antes aplicaba _handle_editar_unidad al
        abrir ComercialAgregarDialog(modo_edicion=True, ...). Con `cantidad`
        mayor a 1 se editan varias unidades a la vez con los mismos valores."""
        self._configurar_modo_multiple(cantidad)
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
        self.tabs.setCurrentIndex(self._primer_paso)
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
        self._configurar_modo_multiple(cantidad)
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
        self._exigir_forma_contrato_real(True, renovacion)
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
