"""Periodo interno y filtros por columna de la bandeja de Comercial."""
import pandas as pd
from datetime import datetime
from src.ui.compartido import comercial_estilo as estilo_com
class _PeriodoFiltrosComercialMixin:
    @staticmethod
    def _clave_orden_periodo(texto):
        """'Septiembre - 2026' -> (2026, 9) para ordenar del más reciente al más antiguo."""
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
                 "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        mes, _, anio = str(texto).partition('-')
        mes, anio = mes.strip().lower(), anio.strip()
        return (int(anio) if anio.isdigit() else 0, meses.index(mes) + 1 if mes in meses else 0)

    @classmethod
    def _etiqueta_periodo(cls, texto):
        """'septiembre - 2026' -> 'Septiembre 2026'; otros valores se muestran capitalizados."""
        mes, _, anio = str(texto).partition('-')
        if anio.strip().isdigit():
            return f"{mes.strip().capitalize()} {anio.strip()}"
        return str(texto).strip().capitalize()

    def _base_de_periodos(self, df_base):
        """Unidades de la sub-pestaña activa que cumplen los filtros de forma de
        contrato, facturación y servicio elegidos."""
        if df_base is None:
            return None
        elegidos = tuple(sorted((c, s.valor()) for c, s in self._filtros_columna.items() if s.valor() is not None))
        subtab = getattr(self, '_new_ui_active_subtab', 0)
        clave = (elegidos, subtab, datetime.now().date(), len(df_base))
        cache = self.__dict__.get('_cache_base_periodos')
        if cache is not None and cache[0] is df_base and cache[1] == clave:
            return cache[2]
        base = df_base
        for columna, valor in elegidos:
            if columna in base.columns:
                base = base[base[columna].astype(str).str.strip().isin(valor)]
        filtro = self._NEW_UI_SUBTAB_FILTERS.get(subtab)
        if filtro is not None:
            base = filtro(base)
        self.__dict__['_cache_base_periodos'] = (df_base, clave, base)
        return base

    def _sincronizar_combo_periodo_interno(self, df_base):
        """Ofrece los PERIODO INTERNO presentes agrupados por año (más reciente
        primero) y, al final, los valores que no son una fecha. Solo ofrece los
        que existen con lo elegido en los otros filtros."""
        base = self._base_de_periodos(df_base)
        if base is None or 'PERIODO INTERNO' not in base.columns:
            periodos = []
        else:
            serie = base['PERIODO INTERNO'].dropna().astype(str).str.strip().str.lower()
            periodos = sorted({p for p in serie.unique() if p and p not in ('-', 'nan')},
                              key=self._clave_orden_periodo, reverse=True)
        if periodos == self.__dict__.get('_periodos_combo'):
            return
        self._periodos_combo = periodos
        por_anio, otros = {}, []
        for p in periodos:
            anio = self._clave_orden_periodo(p)[0]
            if anio:
                por_anio.setdefault(anio, []).append((p, self._etiqueta_periodo(p)))
            else:
                otros.append((p, self._etiqueta_periodo(p)))
        grupos = [(str(anio), items) for anio, items in por_anio.items()]
        if otros:
            grupos.append(("Otros", otros))
        self.combo_periodo_interno.set_opciones(grupos)

    def _on_periodo_interno_cambiado(self, selector=None):
        if selector is not None:
            estilo_com.encadenar_filtros(self._orden_filtros, selector)
        self.btn_limpiar_filtros.setVisible(any(s.valor() is not None for s in self._selectores_filtro()))
        self._refresh_new_ui_data()

    def _selectores_filtro(self):
        return (self.combo_periodo_interno, *self._filtros_columna.values())

    def _limpiar_filtros(self):
        for selector in self._selectores_filtro():
            selector.blockSignals(True)
            selector.limpiar()
            selector.blockSignals(False)
        self._orden_filtros.clear()
        self._on_periodo_interno_cambiado()

    def _con_periodo(self, texto):
        """Agrega al subtítulo de la bandeja el periodo interno y los filtros de columna elegidos."""
        if self.combo_periodo_interno.valor() is not None:
            texto = f"{texto} · {self.combo_periodo_interno._etiqueta_actual()}"
        for selector in self._filtros_columna.values():
            if selector.valor() is not None:
                texto = f"{texto} · {selector._etiqueta_actual()}"
        return texto

    def _df_base_por_periodo(self, df_base):
        """df_base restringido al periodo elegido; el resultado se reutiliza
        mientras no cambien df_base ni el periodo, para no invalidar la caché
        de filtros por sub-pestaña."""
        self._sincronizar_combo_periodo_interno(df_base)
        self._sincronizar_filtros_columna(df_base)
        periodo = self.combo_periodo_interno.valor()
        elegidos = {c: s.valor() for c, s in self._filtros_columna.items() if s.valor() is not None}
        if df_base is None or (periodo is None and not elegidos):
            return df_base
        clave = (periodo, tuple(sorted(elegidos.items())))
        origen, clave_cache, filtrado = self._periodo_interno_df
        if origen is df_base and clave_cache == clave:
            return filtrado
        filtrado = df_base
        if periodo is not None and 'PERIODO INTERNO' in df_base.columns:
            filtrado = filtrado[filtrado['PERIODO INTERNO'].astype(str).str.strip().str.lower() == periodo]
        for columna, valor in elegidos.items():
            if columna in filtrado.columns:
                filtrado = filtrado[filtrado[columna].astype(str).str.strip().isin(valor)]
        self._periodo_interno_df = (df_base, clave, filtrado)
        return filtrado

    def _base_de_opciones(self, df_base):
        """Unidades del periodo elegido que pertenecen a la sub-pestaña activa
        (se recuerda mientras no cambien df_base, periodo ni sub-pestaña)."""
        if df_base is None:
            return None
        periodo = self.combo_periodo_interno.valor()
        subtab = getattr(self, '_new_ui_active_subtab', 0)
        clave = (periodo, subtab, datetime.now().date(), len(df_base))
        cache = self.__dict__.get('_cache_base_opciones')
        if cache is not None and cache[0] is df_base and cache[1] == clave:
            return cache[2]
        base = df_base
        if periodo is not None and 'PERIODO INTERNO' in base.columns:
            base = base[base['PERIODO INTERNO'].astype(str).str.strip().str.lower() == periodo]
        filtro = self._NEW_UI_SUBTAB_FILTERS.get(subtab)
        if filtro is not None:
            base = filtro(base)
        self.__dict__['_cache_base_opciones'] = (df_base, clave, base)
        return base

    def _sincronizar_filtros_columna(self, df_base):
        """Ofrece en cada filtro los valores que existen con lo elegido en los
        demás (periodo incluido) y solo entre las unidades de la sub-pestaña
        activa, con su cantidad."""
        df_base = self._base_de_opciones(df_base)
        self._orden_filtros[:] = [s for s in self._orden_filtros if s.valor() is not None]
        series = {c: (df_base[c].astype(str).str.strip() if df_base is not None and c in df_base.columns else None)
                  for c in self._filtros_columna}
        for columna, selector in self._filtros_columna.items():
            if series[columna] is None:
                selector.set_opciones([])
                continue
            mascara = pd.Series(True, index=df_base.index)
            for otra, otro_selector in self._filtros_columna.items():
                if otra != columna and series[otra] is not None and otro_selector.valor() is not None:
                    mascara &= otro_selector.coincide(series[otra])
            conteo = series[columna][mascara].value_counts()
            items = [(v, f"{v} ({n})") for v, n in sorted(conteo.items()) if v and v.lower() not in ('-', 'nan')]
            selector.set_opciones([(None, items)])

    def _filtrar_subtab_con_cache(self, subtab, df_base):
        """Filtro de negocio de la sub-pestaña, recordado mientras df_base sea
        el mismo objeto (solo se reasigna al recargar/guardar) y el día no
        cambie, para que alternar sub-pestañas no refiltre todo cada vez."""
        filtro = self._NEW_UI_SUBTAB_FILTERS.get(subtab)
        if filtro is None:
            return df_base
        clave = (datetime.now().date(), len(df_base))
        cache = self.__dict__.get('_cache_filtro_subtab')
        if cache is None or cache[0] is not df_base or cache[1] != clave:
            cache = (df_base, clave, {})
            self.__dict__['_cache_filtro_subtab'] = cache
        if subtab not in cache[2]:
            cache[2][subtab] = filtro(df_base)
        return cache[2][subtab]
