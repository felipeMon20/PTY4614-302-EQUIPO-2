"""Búsqueda de un VIN desde la barra global y aviso de su ubicación en Comercial."""
from src.services import cm_bajas_service
from src.services import localizador_vin
import config.settings


class _BusquedaVinComercialMixin:
    # ---------------------------------------------------------------
    # Búsqueda por VIN: lleva a la bandeja donde está la unidad (con su flota abierta si todos los VIN son de
    # la misma; con varias flotas queda la lista) y deja las pestañas visibles; si no está en Comercial,
    # dice dónde está y ofrece ir.
    # ---------------------------------------------------------------
    def _on_buscar_new_ui(self):
        self._localizar_vin_buscado()
        self._refresh_new_ui_data()

    def _restaurar_tras_busqueda_vin(self):
        for i in range(self.new_ui_subtabs.count()):
            self.new_ui_subtabs.setTabVisible(i, True)
        self.new_ui_subtabs.updateGeometry()
        self._panel_ubicacion_vin.hide()
        self._ubicacion_vin_destino = None
        if self._grupo_abierto_por_busqueda is not None:
            self._new_ui_grupo_abierto.pop(self._grupo_abierto_por_busqueda, None)
            self._grupo_abierto_por_busqueda = None

    def _localizar_vin_buscado(self):
        vins_texto = localizador_vin.extraer_vins(self.new_ui_search_input.text())
        if not vins_texto:
            self._restaurar_tras_busqueda_vin()
            return
        # Al llegar desde otra pantalla con el VIN en la búsqueda, los datos pueden estar sin recargar todavía
        if getattr(self.legacy, '_data_dirty', False):
            self.legacy.refresh_if_dirty()
        df_base = getattr(self.legacy, 'df_base', None)
        casos = cm_bajas_service.leer_casos_baja_cm(config.settings.CASOS_BAJA_CM_PATH)
        # Las bandejas se revisan una sola vez con todos los VIN encontrados (por término eran miles de filtrados)
        indice = localizador_vin.IndiceVins(df_base, casos)
        todos = set()
        for termino in vins_texto:
            todos |= indice.buscar(termino)
        pestanas = localizador_vin.pestanas_comercial(todos, df_base, casos) if todos else []
        if pestanas:
            self._mostrar_solo_pestanas_con_vin(pestanas, todos)
        else:
            self._mostrar_ubicacion_fuera_de_comercial(vins_texto[0])

    def _mostrar_solo_pestanas_con_vin(self, pestanas, vins):
        """Va a la bandeja de la unidad buscada y, si todos los VIN son de una misma flota, la abre (fase 2);
        con varias flotas queda la lista de flotas (fase 1). Las pestañas se dejan todas visibles."""
        self._panel_ubicacion_vin.hide()
        self._ubicacion_vin_destino = None
        # Un filtro de periodo, de columna o de tarjeta podría esconder la unidad buscada
        selectores = [self.combo_periodo_interno, *self._filtros_columna.values()]
        for selector in selectores:
            if selector.valor() is not None:
                selector.limpiar()
        for i in range(self.new_ui_subtabs.count()):
            self.new_ui_subtabs.setTabVisible(i, True)
        actual = self.new_ui_subtabs.currentIndex()
        destino = actual if actual in pestanas else pestanas[0]
        if destino != actual:
            self.new_ui_subtabs.setCurrentIndex(destino)
        self._new_ui_kpi_filtro_por_subtab.pop(destino, None)
        self._new_ui_grupo_abierto.pop(destino, None)
        grupo = self._grupo_de_vins(destino, vins)
        if grupo is not None:
            self._new_ui_grupo_abierto[destino] = grupo
            self._grupo_abierto_por_busqueda = destino

    def _grupo_de_vins(self, subtab, vins):
        """Flota (o razón social) de la bandeja a la que pertenece el VIN buscado, para abrirla directo."""
        if subtab == self._NEW_UI_SUBTAB_REVISION_CM:
            df = self._construir_df_revision_cm()
        else:
            df = self._filtrar_subtab_con_cache(subtab, getattr(self.legacy, 'df_base', None))
        clave = self._clave_grupo_new_ui(subtab)
        if df is None or df.empty or clave not in df.columns or 'VIN' not in df.columns:
            return None
        fila = df[df['VIN'].astype(str).str.strip().str.upper().isin(vins)]
        if fila.empty:
            return None
        valores = {self._NEW_UI_VALOR_SIN_GRUPO if str(v).strip().upper() in ('', 'NAN', 'NONE', 'NAT', '-', '<NA>')
                   else str(v).strip() for v in fila[clave]}
        return next(iter(valores)) if len(valores) == 1 else None

    def _mostrar_ubicacion_fuera_de_comercial(self, termino):
        df_ops = self.legacy.data_manager.get_contratos_actuales_df()
        vins = localizador_vin.vins_de_termino(termino, df_ops)
        pestanas = localizador_vin.pestanas_operaciones(vins, df_ops) if vins else []
        for i in range(self.new_ui_subtabs.count()):
            self.new_ui_subtabs.setTabVisible(i, True)
        if pestanas:
            self._ubicacion_vin_destino = ("Operaciones", pestanas[0])
            self._panel_ubicacion_vin.mostrar_destino(
                sorted(vins)[0], localizador_vin.descripcion("Operaciones", pestanas[0]))
        else:
            self._ubicacion_vin_destino = None
            self._panel_ubicacion_vin.mostrar_no_encontrado(sorted(vins)[0] if vins else termino)

    def _on_ir_ubicacion_vin(self):
        destino = self._ubicacion_vin_destino
        ventana = self.window()
        if destino and hasattr(ventana, '_on_menu_clicked'):
            ventana._on_menu_clicked(destino[0])
