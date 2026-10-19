import pandas as pd
from PyQt6.QtWidgets import QLineEdit, QMenu, QMessageBox, QComboBox
from PyQt6.QtCore import Qt

from src.core.data_manager import DataManager
from src.core.excel_writer import ExcelWriter
from src.core.constants import (
    COL_ID, COL_VIN, COL_CHASIS, COL_RAZON_SOCIAL, COL_RUT, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION,
    COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION, COL_ETAPA_GESTION, COL_CONTRATO_JUSTTIME,
    COL_FECHA_INICIO_FACT, COL_FECHA_TERMINO_FACT,
    JUSTTIME_ESTADO_OPCIONES, JUSTTIME_ESTADO_PENDIENTE, JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_ELIMINAR,
    JUSTTIME_ESTADO_REVISAR_PAGO, ETAPA_GESTION_COLORES,
)
from src.services import justtime_service as jt
from src.ui import comercial_estilo as estilo_com
from src.ui.custom_table import AppTableWidget, PandasTableModel
from src.ui.formulario_unidad import GuardadoUnidadesMixin, PESTANA_JUSTTIME_CM
from src.ui.ingresos_base import PantallaIngresosBase, ComboFiltroBarra, boton_barra, estilo_combo_barra
from src.theme.theme_manager import ThemeManager
from src.theme.colors import *

# (título, filtro, color, descripción); el primero es el total y los demás se
# miden contra él, como en las tarjetas de Comercial
_KPI_SPECS = [
    ("Total en JustTime", jt.FILTRO_DEBERIAN_ESTAR, "#0F766E",
     "Unidades cuyo tipo de facturación va a JustTime (Cliente e Interno)."),
    ("JT Interno", jt.FILTRO_JT_INTERNO, "#4338CA", "Unidades con TIPO DE FACTURACION = Interno."),
    ("JT Cliente", jt.FILTRO_JT_CLIENTE, "#1F6FEB", "Unidades con TIPO DE FACTURACION = Cliente."),
    ("Inconsistencias", jt.FILTRO_INCONSISTENCIAS, DANGER,
     "Diferencias entre el tipo de facturación y el estado JustTime, o datos faltantes."),
]

_ETIQUETA_ESTADO = {JUSTTIME_ESTADO_SI: "En JustTime"}
_ESTADO_POR_ETIQUETA = {v: k for k, v in _ETIQUETA_ESTADO.items()}
_ESTADOS_FILTRO = [JUSTTIME_ESTADO_PENDIENTE, JUSTTIME_ESTADO_SI, JUSTTIME_ESTADO_ELIMINAR, JUSTTIME_ESTADO_REVISAR_PAGO]
# Filtros que antes eran tarjetas y ahora viven en el combo de la barra
_FILTROS_EXTRA_COMBO = [
    (jt.FILTRO_POR_CORREGIR, "Por corregir"),
    (jt.FILTRO_CON_ESTADO, "Con estado (sin \"-\")"),
]

# Estado JustTime: (fondo, texto)
_CHIP_ESTADO = {
    JUSTTIME_ESTADO_PENDIENTE: ("#FEF3C7", "#92400E"),
    JUSTTIME_ESTADO_SI: ("#D1FAE5", "#065F46"),
    JUSTTIME_ESTADO_ELIMINAR: ("#FEE2E2", "#991B1B"),
    JUSTTIME_ESTADO_REVISAR_PAGO: ("#EDE9FE", "#5B21B6"),
}
_CHIP_DEFAULT = ("#EEF1F6", "#52607A")
_CHIP_EMPRESA = ("#E1EAF4", BRAND_BLUE)
_CHIP_ROJO = ("#FEE2E2", "#991B1B")

# Colores propios de Tipo de facturación y Etapa de gestión (no están en el
# catálogo de la tabla); el resto usa el catálogo de la tabla
_COLORES_TIPO = {
    'CLIENTE': ("#DBEAFE", "#1E40AF"),
    'INTERNO': ("#EDE9FE", "#5B21B6"),
    'FACTURACIÓN MANUAL': ("#CCFBF1", "#115E59"),
    'PROVISION +': ("#FEF3C7", "#92400E"),
    'CM': ("#FCE7F3", "#9D174D"),
}
_COLORES_ETAPA = {
    clave: (estilo_com.mezclar_con_blanco(color, 0.15), color) for clave, color in ETAPA_GESTION_COLORES.items()
}

# Columnas de la tabla (nombres para mostrar)
COL_ESTADO_JT_TABLA = "ESTADO JUSTTIME"
COL_INICIO_JT = "INICIO JUSTTIME"
COL_VENCIMIENTO_JT = "VENCIMIENTO JUSTTIME"
COL_SUGERENCIA_TABLA = "SUGERENCIA"
COL_INCONSISTENCIA_TABLA = "INCONSISTENCIA"
COL_UNIDADES = "UNIDADES"
COL_POR_REVISAR = "POR REVISAR"

# Todas las columnas de la unidad; la ficha del panel las usa, la tabla no
_COLUMNAS_UNIDADES = [
    COL_ID, COL_VIN, COL_CHASIS, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION,
    COL_ETAPA_GESTION, COL_ESTADO_JT_TABLA, COL_INICIO_JT, COL_VENCIMIENTO_JT, COL_SUGERENCIA_TABLA,
    COL_INCONSISTENCIA_TABLA,
]
# La tabla muestra solo estas; VIN va oculta (para "Copiar VIN" del clic derecho)
# y el resto se ve en el panel flotante
_COLUMNAS_UNIDADES_VISTA = [
    COL_ID, COL_VIN, COL_CHASIS, COL_FORMA_CONTRATO, COL_TIPO_FACTURACION, COL_ESTADO_COMERCIAL, COL_ESTADO_ACTIVACION,
    COL_ESTADO_JT_TABLA, COL_INICIO_JT, COL_VENCIMIENTO_JT,
]
_COLUMNAS_EMPRESAS = [COL_RAZON_SOCIAL, COL_RUT, COL_UNIDADES, COL_POR_REVISAR]

# Campos de la ficha del panel flotante: (etiqueta, columna)
_CAMPOS_FICHA = [
    ("N° Contrato", COL_ID),
    ("Forma de contrato", COL_FORMA_CONTRATO),
    ("Tipo de facturación", COL_TIPO_FACTURACION),
    ("Estado comercial", COL_ESTADO_COMERCIAL),
    ("Estado de activación", COL_ESTADO_ACTIVACION),
    ("Etapa de gestión", COL_ETAPA_GESTION),
    ("Estado JustTime", COL_ESTADO_JT_TABLA),
]


def _fecha(valor):
    """dd-mm-aaaa de una fecha guardada como texto, '-' si no hay fecha."""
    ts = pd.to_datetime(valor, errors='coerce')
    return ts.strftime("%d-%m-%Y") if pd.notna(ts) else "-"


def _colores_celda(columna, valor):
    """(fondo, texto) del chip de `valor` en `columna`, o None si la celda no
    es un chip propio de JustTime (el resto lo resuelve la tabla)."""
    clave = str(valor).strip().upper()
    if columna == COL_TIPO_FACTURACION:
        return _COLORES_TIPO.get(clave, _CHIP_DEFAULT) if clave not in ("", "-") else None
    if columna == COL_ETAPA_GESTION:
        return _COLORES_ETAPA.get(clave, _CHIP_DEFAULT) if clave not in ("", "-") else None
    if columna == COL_ESTADO_JT_TABLA:
        estado = _ESTADO_POR_ETIQUETA.get(str(valor).strip(), str(valor).strip())
        return _CHIP_ESTADO.get(estado, _CHIP_DEFAULT)
    if columna == COL_UNIDADES:
        return _CHIP_EMPRESA
    if columna == COL_POR_REVISAR:
        return _CHIP_ROJO if clave not in ("", "0") else None
    return None


class JustTimeModule(GuardadoUnidadesMixin, PantallaIngresosBase):
    """Pantalla JustTime (Ingresos y Conciliación): dos niveles --
    empresas -> unidades -- con el esqueleto de Comercial/Operaciones (ver
    ingresos_base.py). Editar una unidad abre el formulario de
    comercial_agregar.py en la pestaña "JustTime & CM" (con Operaciones
    bloqueado); el estado también se puede cambiar en lote para las unidades
    mostradas."""

    MODULO_LOG = "JustTime"
    AVATAR = "JT"
    TITULO = "JustTime"
    KPI_SPECS = _KPI_SPECS
    CAMPOS_FICHA = _CAMPOS_FICHA
    ANCHOS_EMPRESAS = {COL_RAZON_SOCIAL: 460, COL_RUT: 150, COL_UNIDADES: 140, COL_POR_REVISAR: 150}
    ANCHOS_DETALLE = {
        COL_ID: 80, COL_VIN: 170, COL_CHASIS: 110, COL_FORMA_CONTRATO: 150, COL_TIPO_FACTURACION: 200, COL_ESTADO_COMERCIAL: 150,
        COL_ESTADO_ACTIVACION: 170, COL_ESTADO_JT_TABLA: 160, COL_INICIO_JT: 130, COL_VENCIMIENTO_JT: 150,
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
        self.filtro_actual = jt.FILTRO_TODOS
        self.df_base = pd.DataFrame()
        self._df_visible = pd.DataFrame()
        self._data_dirty = False
        self._save_thread = None

        self.data_manager.data_ready.connect(self._on_global_data_ready)
        self._setup_ui()
        self.load_data()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        self.construir_base()

        # Mismo filtro de Provisiones: combo redondeado
        self.combo_estado = ComboFiltroBarra('fa5s.filter', "Estado")
        self.combo_estado.setMinimumWidth(190)
        ThemeManager.apply_combo_box(self.combo_estado)
        self.combo_estado.setStyleSheet(estilo_combo_barra())
        self.combo_estado.setMaxVisibleItems(9)
        self.combo_estado.currentIndexChanged.connect(self._on_combo_estado)
        self.agregar_filtro(self.combo_estado)

        self.btn_export_excel = boton_barra("Excel", 'fa5s.file-excel', 'excel')
        self.btn_export_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color='#1B2B4E'))
        self.btn_export_excel.clicked.connect(lambda: self.table_export.export_to_excel("Reporte_JustTime"))
        self.agregar_blanco(self.btn_export_excel)

        self.btn_cambiar_estado = boton_barra("", 'fa5s.exchange-alt')
        self.btn_cambiar_estado.setToolTip("Cambiar estado: cambia el estado JustTime de todas las unidades mostradas")
        menu_estados = QMenu(self.btn_cambiar_estado)
        for estado in JUSTTIME_ESTADO_OPCIONES:
            menu_estados.addAction(estado, lambda e=estado: self._cambiar_estado_visibles(e))
        self.btn_cambiar_estado.setMenu(menu_estados)
        self.agregar_capsula(self.btn_cambiar_estado)

        self.btn_aplicar_sugerencias = boton_barra("", 'fa5s.magic')
        self.btn_aplicar_sugerencias.setToolTip("Aplicar sugerencias: pasa los estados con formato antiguo al estado sugerido")
        self.btn_aplicar_sugerencias.clicked.connect(self._aplicar_sugerencias_visibles)
        self.agregar_capsula(self.btn_aplicar_sugerencias)

        self.btn_corregir_matriz = boton_barra("", 'fa5s.broom')
        self.btn_corregir_matriz.setToolTip(
            "Corregir según la matriz: deja las unidades mostradas con el estado que les corresponde por su tipo de facturación")
        self.btn_corregir_matriz.clicked.connect(self._corregir_visibles_segun_matriz)
        self.agregar_capsula(self.btn_corregir_matriz)

        self.btn_limpiar = boton_barra("", 'fa5s.eraser')
        self.btn_limpiar.setToolTip(
            "Limpiar datos de JustTime: deja en \"-\" las unidades mostradas que no van a JustTime y ya salieron de él")
        self.btn_limpiar.clicked.connect(self._limpiar_visibles)
        self.agregar_capsula(self.btn_limpiar)

        self.btn_reload = boton_barra("", 'fa5s.sync-alt')
        self.btn_reload.setToolTip("Recargar")
        self.btn_reload.clicked.connect(self.load_data)
        self.agregar_capsula(self.btn_reload)

        # Tabla oculta: solo alimenta "Excel" con todas las unidades filtradas
        self.table_export = AppTableWidget()
        self.model_export = PandasTableModel()
        self.table_export.setModel(self.model_export)

        self.btn_editar_unidad = estilo_com.BotonAccionPanel(
            'fa5s.edit', 'Editar unidad',
            "Abre el formulario de la unidad en la pestaña JustTime & CM.", BRAND_BLUE)
        self.btn_editar_unidad.setEnabled(False)
        self.btn_editar_unidad.clicked.connect(self._on_editar_unidad_clicked)
        self.agregar_accion_panel(self.btn_editar_unidad)

        self.btn_corregir_panel = estilo_com.BotonAccionPanel(
            'fa5s.broom', 'Corregir según la matriz',
            "Deja las unidades seleccionadas con el estado JustTime que les corresponde por su tipo de facturación.",
            BRAND_BLUE)
        self.btn_corregir_panel.setEnabled(False)
        self.btn_corregir_panel.clicked.connect(self._corregir_seleccion_segun_matriz)
        self.agregar_accion_panel(self.btn_corregir_panel)

        self.btn_limpiar_panel = estilo_com.BotonAccionPanel(
            'fa5s.eraser', 'Limpiar datos de JustTime',
            "Deja en \"-\" el estado, inicio y término de las unidades que no van a JustTime y ya salieron de él.",
            BRAND_BLUE)
        self.btn_limpiar_panel.setEnabled(False)
        self.btn_limpiar_panel.clicked.connect(self._limpiar_seleccion)
        self.agregar_accion_panel(self.btn_limpiar_panel)

    # --------------------------------------------- ganchos de la pantalla base
    def resolver_color(self, columna, valor, es_fondo):
        colores = _colores_celda(columna, valor)
        if colores is not None:
            return colores[0] if es_fondo else colores[1]
        if columna == COL_VENCIMIENTO_JT and not es_fondo:
            ts = pd.to_datetime(valor, format="%d-%m-%Y", errors='coerce')
            if pd.notna(ts) and ts < pd.Timestamp.today().normalize():
                return estilo_com.ROJO
        return None

    def colores_chip_ficha(self, columna, valor):
        return _colores_celda(columna, valor)

    def on_kpi_clicado(self, clave):
        self.filtro_actual = jt.FILTRO_TODOS if self.filtro_actual == clave else clave
        self.filter_table()

    def on_fila_cambiada(self, fila, cantidad):
        if cantidad == 0:
            self.btn_editar_unidad.setEnabled(False)
            self.btn_corregir_panel.setEnabled(False)
            self.btn_limpiar_panel.setEnabled(False)
            return
        self.btn_corregir_panel.setEnabled(bool(self._lote_matriz_seleccion()))
        self.btn_limpiar_panel.setEnabled(bool(self._lote_limpieza_seleccion()))
        problema = str(fila.get(COL_INCONSISTENCIA_TABLA, "") or "")
        sugerencia = str(fila.get(COL_SUGERENCIA_TABLA, "") or "")
        aviso = ""
        if problema and problema != "OK":
            aviso = f"⚠  {problema}" + (f"\nSugerido: {sugerencia}" if sugerencia not in ("", "-") else "")
        self._pintar_panel(fila, cantidad, aviso)
        self.btn_editar_unidad.setEnabled(cantidad == 1)

    def al_cambiar_nivel(self):
        self.filter_table()

    def _on_editar_unidad_clicked(self):
        vins = self._vins_seleccionados()
        if len(vins) == 1:
            self._abrir_formulario_unidad(vins[0])

    # --------------------------------------------------------------- datos
    def _on_global_data_ready(self):
        if self.isVisible():
            self.load_data()
        else:
            self._data_dirty = True

    def refresh_if_dirty(self):
        if self._data_dirty:
            self.load_data()

    def load_data(self):
        self._data_dirty = False
        df_master = self.data_manager.df_master
        self.df_base = jt.preparar_base_justtime(df_master) if not df_master.empty else pd.DataFrame()
        if self.empresa_actual is not None and (
                self.df_base.empty or self.empresa_actual not in set(self.df_base[COL_RAZON_SOCIAL])):
            self.empresa_actual = None
        self.actualizar_titulo()
        self.filter_table()

    def _on_combo_estado(self, _i):
        filtro = self.combo_estado.currentData()
        if filtro is not None and filtro != self.filtro_actual:
            self.filtro_actual = filtro
            self.filter_table()

    def _actualizar_combo(self, kpis):
        self.combo_estado.blockSignals(True)
        self.combo_estado.clear()
        self.combo_estado.addItem("Todos los estados", jt.FILTRO_TODOS)
        for estado in _ESTADOS_FILTRO:
            self.combo_estado.addItem(f"{_ETIQUETA_ESTADO.get(estado, estado)} ({kpis.get(estado, 0)})", estado)
        for filtro, nombre in _FILTROS_EXTRA_COMBO:
            self.combo_estado.addItem(f"{nombre} ({kpis.get(filtro, 0)})", filtro)
        pos = self.combo_estado.findData(self.filtro_actual)
        self.combo_estado.setCurrentIndex(pos if pos >= 0 else 0)
        self.combo_estado.blockSignals(False)

    def filter_table(self, *_args):
        df_busqueda = jt.buscar(self.df_base, self.search_input.text())
        kpis = jt.calcular_kpis(df_busqueda)
        total = float(kpis.get(jt.FILTRO_DEBERIAN_ESTAR, 0) or 0)
        for clave, tarjeta in self.botones_kpi.items():
            valor = kpis.get(clave, 0)
            fraccion = 1.0 if clave == jt.FILTRO_DEBERIAN_ESTAR else ((valor / total) if total else 0.0)
            pie = "unidades que van a JustTime" if clave == jt.FILTRO_DEBERIAN_ESTAR else f"de {int(total)} unidades"
            tarjeta.setChecked(clave == self.filtro_actual)
            tarjeta.actualizar(valor, fraccion, pie)
        self._actualizar_combo(kpis)

        df_filtrado = jt.filtrar(df_busqueda, self.filtro_actual)
        if self.empresa_actual is not None and not df_filtrado.empty:
            df_filtrado = df_filtrado[df_filtrado[COL_RAZON_SOCIAL] == self.empresa_actual]
        self._df_visible = df_filtrado
        columnas_export = [c for c in jt.COLUMNAS_BASE if c in df_filtrado.columns] + [jt.COL_INCONSISTENCIA]
        self.model_export.set_data(df_filtrado[columnas_export].rename(columns={jt.COL_INCONSISTENCIA: "PROBLEMA"})
                                   if not df_filtrado.empty else pd.DataFrame())

        hay_sugerencias = not df_filtrado.empty and bool(
            ((df_filtrado[jt.COL_ESTADO_JT] == jt.POR_CORREGIR) & (df_filtrado[jt.COL_SUGERENCIA] != "")).any())
        self.btn_aplicar_sugerencias.setEnabled(hay_sugerencias)
        self.btn_corregir_matriz.setEnabled(not df_filtrado.empty and bool(jt.construir_cambios_matriz(df_filtrado)))
        self.btn_limpiar.setEnabled(not df_filtrado.empty and bool(jt.construir_cambios_limpieza(df_filtrado)))
        self.btn_cambiar_estado.setEnabled(self.empresa_actual is not None and not df_filtrado.empty)

        if self.empresa_actual is None:
            self._df_tabla = self._armar_tabla_empresas(df_filtrado)
        else:
            self._df_tabla = self._armar_tabla_unidades(df_filtrado)
        self.lbl_sin_resultados.setVisible(self._df_tabla.empty)
        unidades = len(df_filtrado)
        if self.empresa_actual is None:
            self.lbl_subtitulo.setText(f"{len(self._df_tabla)} empresas · {unidades} unidades")
        else:
            self.lbl_subtitulo.setText(f"{unidades} unidades")
        self._pintar_tabla()

    def _armar_tabla_empresas(self, df_filtrado):
        empresas = jt.obtener_empresas(df_filtrado)
        self._fila_por_vin = {}
        return pd.DataFrame({
            COL_RAZON_SOCIAL: empresas[COL_RAZON_SOCIAL].astype(str).tolist(),
            COL_RUT: empresas[COL_RUT].astype(str).tolist(),
            COL_UNIDADES: empresas["UNIDADES"].astype(int).astype(str).tolist(),
            COL_POR_REVISAR: empresas["ATENCION"].astype(int).astype(str).tolist(),
        }, columns=_COLUMNAS_EMPRESAS)

    def _armar_tabla_unidades(self, df_filtrado):
        if df_filtrado.empty:
            self._fila_por_vin = {}
            return pd.DataFrame(columns=_COLUMNAS_UNIDADES_VISTA)
        orden = df_filtrado.assign(_SIN_PROBLEMA=df_filtrado[jt.COL_INCONSISTENCIA] == "").sort_values(
            ["_SIN_PROBLEMA", COL_VIN])
        estado = orden[jt.COL_ESTADO_JT]
        valor_jt = orden[COL_CONTRATO_JUSTTIME].replace("", "-")
        texto_jt = valor_jt.where(estado == jt.POR_CORREGIR, estado.map(lambda e: _ETIQUETA_ESTADO.get(e, e)))
        df = pd.DataFrame({
            COL_ID: orden[COL_ID], COL_VIN: orden[COL_VIN], COL_CHASIS: orden[COL_CHASIS].replace("", "-"),
            COL_FORMA_CONTRATO: orden[COL_FORMA_CONTRATO], COL_TIPO_FACTURACION: orden[COL_TIPO_FACTURACION],
            COL_ESTADO_COMERCIAL: orden[COL_ESTADO_COMERCIAL], COL_ESTADO_ACTIVACION: orden[COL_ESTADO_ACTIVACION],
            COL_ETAPA_GESTION: orden[COL_ETAPA_GESTION], COL_ESTADO_JT_TABLA: texto_jt,
            COL_INICIO_JT: orden[COL_FECHA_INICIO_FACT].map(_fecha),
            COL_VENCIMIENTO_JT: orden[COL_FECHA_TERMINO_FACT].map(_fecha),
            COL_SUGERENCIA_TABLA: orden[jt.COL_SUGERENCIA].replace("", "-"),
            COL_INCONSISTENCIA_TABLA: orden[jt.COL_INCONSISTENCIA].replace("", "OK"),
        }, columns=_COLUMNAS_UNIDADES).reset_index(drop=True)
        df[COL_RAZON_SOCIAL] = orden[COL_RAZON_SOCIAL].tolist()
        self._fila_por_vin = {str(r[COL_VIN]).strip(): r for r in df.to_dict('records')}
        return df[_COLUMNAS_UNIDADES_VISTA]

    # ------------------------------------------------------------ edición
    def _abrir_formulario_unidad(self, vin):
        self.editar_y_guardar_unidad(vin, PESTANA_JUSTTIME_CM)

    def _confirmar_lote(self, cantidad, detalle):
        respuesta = QMessageBox.question(
            self, "Confirmar cambio", f"{detalle}\n\nSe modificarán {cantidad} unidad(es). ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return respuesta == QMessageBox.StandardButton.Yes

    def _cambiar_estado_visibles(self, estado):
        if self._df_visible.empty:
            return
        lote = jt.construir_cambios_estado(self._df_visible[COL_VIN].tolist(), estado)
        if lote and self._confirmar_lote(len(lote), f"Estado JustTime → \"{estado}\" para las unidades mostradas."):
            self.guardar_lote_unidades(lote, f"Cambiando {len(lote)} unidad(es) a \"{estado}\"…")

    def _df_seleccion(self):
        vins = {v.upper() for v in self._vins_seleccionados()}
        if not vins or self.df_base.empty:
            return self.df_base.iloc[0:0]
        return self.df_base[self.df_base[COL_VIN].astype(str).str.strip().str.upper().isin(vins)]

    def _lote_matriz_seleccion(self):
        return jt.construir_cambios_matriz(self._df_seleccion())

    def _lote_limpieza_seleccion(self):
        return jt.construir_cambios_limpieza(self._df_seleccion())

    def _limpiar_seleccion(self):
        lote = self._lote_limpieza_seleccion()
        self._ejecutar_limpieza(lote)

    def _limpiar_visibles(self):
        if not self._df_visible.empty:
            self._ejecutar_limpieza(jt.construir_cambios_limpieza(self._df_visible))

    def _ejecutar_limpieza(self, lote):
        if lote and self._confirmar_lote(
                len(lote), "Se limpian los datos de JustTime (estado, inicio y término quedan en \"-\"). "
                           "El cambio queda registrado en el historial."):
            self.guardar_lote_unidades(lote, f"Limpiando {len(lote)} unidad(es)…")

    def _descripcion_correccion(self, lote):
        destinos = {}
        for item in lote.values():
            nuevo = item['cambios'][COL_CONTRATO_JUSTTIME]
            destinos[nuevo] = destinos.get(nuevo, 0) + 1
        return "\n".join(f"• {cant} → \"{_ETIQUETA_ESTADO.get(e, e)}\"" for e, cant in destinos.items())

    def _ejecutar_correccion_matriz(self, lote):
        if lote and self._confirmar_lote(
                len(lote), "Se corrige el estado JustTime según la matriz:\n" + self._descripcion_correccion(lote)):
            self.guardar_lote_unidades(lote, f"Corrigiendo {len(lote)} unidad(es)…")

    def _corregir_seleccion_segun_matriz(self):
        self._ejecutar_correccion_matriz(self._lote_matriz_seleccion())

    def _corregir_visibles_segun_matriz(self):
        if not self._df_visible.empty:
            self._ejecutar_correccion_matriz(jt.construir_cambios_matriz(self._df_visible))

    def _aplicar_sugerencias_visibles(self):
        lote = jt.construir_cambios_sugeridos(self._df_visible)
        if lote and self._confirmar_lote(len(lote), "Los estados con formato antiguo pasan al estado sugerido."):
            self.guardar_lote_unidades(lote, f"Corrigiendo {len(lote)} unidad(es)…")
