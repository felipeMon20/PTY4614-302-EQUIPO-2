"""Vista agrupada de la bandeja de Comercial."""
import pandas as pd
from PyQt6.QtWidgets import QAbstractItemView
from src.services import comercial_services
from src.services.powerbi_import_service import trae_volvo_connect
from src.ui.compartido.esqueleto_carga import animar_sobre_tabla
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.comercial.base import NEW_UI_COL_WIDTH_MINIMO
from src.ui.comercial.base import (
    NEW_UI_COL_WIDTH_MINIMO,
)


class _VistaGruposComercialMixin:
    def _clave_grupo_new_ui(self, subtab):
        return 'RAZÓN SOCIAL' if subtab in self._NEW_UI_SUBTABS_AGRUPADAS_POR_RAZON_SOCIAL else 'FLOTA VC'

    def _preparar_vista_agrupada(self, subtab, df, columnas):
        """Devuelve (df, columnas, en_grupos) según el estado de agrupación
        de la sub-pestaña: con un grupo abierto filtra sus unidades y deja
        las columnas normales; sin grupo abierto resume una fila por
        FLOTA VC (o RAZÓN SOCIAL en "Por gestionar") con su cantidad de
        unidades."""
        clave = self._clave_grupo_new_ui(subtab)
        abierto = self._new_ui_grupo_abierto.get(subtab)
        if clave not in df.columns:
            self._actualizar_barra_grupo(None)
            self._new_ui_en_grupos = False
            self.lbl_grupo_abierto.setText(self._con_periodo(f"{len(df)} unidades"))
            return df, columnas, False

        sin_dato = self._NEW_UI_VALOR_SIN_GRUPO
        serie = self._serie_grupo_new_ui(df, clave)

        if abierto is not None:
            self._actualizar_barra_grupo(clave, abierto)
            self._new_ui_en_grupos = False
            self.new_ui_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            df_grupo = df[serie == abierto]
            self.lbl_grupo_abierto.setText(self._con_periodo(f"{len(df_grupo)} unidades · {clave}: {abierto}"))
            if subtab == self._NEW_UI_SUBTAB_POR_GESTIONAR and 'OBSERVACIONES' in df_grupo.columns:
                trae = df_grupo['OBSERVACIONES'].map(trae_volvo_connect)
                df_grupo = df_grupo.assign(**{self._NEW_UI_COL_VOLVO_CONNECT: trae.map({True: 'Trae VC', False: ''})})
                if not self.new_ui_table.has_active_sort():
                    df_grupo = df_grupo.iloc[(~trae).to_numpy().argsort(kind='stable')]
                columnas = list(columnas) + [self._NEW_UI_COL_VOLVO_CONNECT]
                # Las unidades que Operaciones devolvió llevan una marca en OBSERVACIONES: salen primero y con su columna
                devuelto = df_grupo['OBSERVACIONES'].map(comercial_services.fue_devuelto)
                if devuelto.any():
                    df_grupo = df_grupo.assign(**{self._NEW_UI_COL_DEVUELTO: devuelto.map({True: 'Devuelto', False: ''})})
                    if not self.new_ui_table.has_active_sort():
                        df_grupo = df_grupo.iloc[(~devuelto.to_numpy()).argsort(kind='stable')]
                    columnas = columnas + [self._NEW_UI_COL_DEVUELTO]
            return df_grupo, columnas, False

        self._actualizar_barra_grupo(None)
        self._new_ui_en_grupos = True
        # En Oportunidades CM las flotas se seleccionan para marcar su gestión (doble clic abre)
        self.new_ui_table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection if subtab == self._NEW_UI_SUBTAB_REVISION_CM
            else QAbstractItemView.SelectionMode.NoSelection)
        col_unidades = self._NEW_UI_COL_UNIDADES
        grupos = df.assign(_grupo=serie).groupby('_grupo', sort=True)
        resumen = pd.DataFrame({clave: grupos.size().index, col_unidades: grupos.size().values})
        sustantivo = "clientes" if clave == 'RAZÓN SOCIAL' else "flotas"
        self.lbl_grupo_abierto.setText(self._con_periodo(f"{len(df)} unidades en {len(resumen)} {sustantivo}"))
        columnas_vista = [clave]
        if subtab == self._NEW_UI_SUBTAB_RENOVAR_CLIENTES:
            idx = df.index
            masks = self._masks_renovar(df)
            conteos = pd.DataFrame({
                '_g': serie.values,
                'VENCEN EN 30 DÍAS': masks['por_vencer'].values,
                'VIGENTES': masks['vigentes'].values,
                'UNIDADES VENCIDAS': masks['vencidas'].values,
            }).groupby('_g', sort=True).sum()
            for col in ('VENCEN EN 30 DÍAS', 'VIGENTES', 'UNIDADES VENCIDAS'):
                resumen[col] = conteos[col].astype(int).values
            resumen['TOTAL UNIDADES'] = resumen.pop(col_unidades)
            orden = [clave, 'UNIDADES VENCIDAS', 'VENCEN EN 30 DÍAS', 'VIGENTES', 'TOTAL UNIDADES']
            return resumen[orden], orden, True
        if clave != 'RAZÓN SOCIAL' and 'RAZÓN SOCIAL' in df.columns:
            razones = self._valores_distintos_por_grupo(serie, df['RAZÓN SOCIAL'], ('', 'NAN'))
            def _razon(valores):
                return next(iter(valores)) if len(valores) == 1 else (f"Varios clientes ({len(valores)})" if valores else sin_dato)
            resumen['RAZÓN SOCIAL'] = [_razon(razones.get(g, {})) for g in resumen[clave]]
            columnas_vista.append('RAZÓN SOCIAL')
        if subtab == self._NEW_UI_SUBTAB_REVISION_CM and 'MOTIVO' in df.columns:
            motivos = self._valores_distintos_por_grupo(serie, df['MOTIVO'], ('', 'NAN', '-'))
            resumen['MOTIVO'] = [estilo_com.SEPARADOR_CHIPS.join(sorted(motivos.get(g, {}))) for g in resumen[clave]]
            columnas_vista.append('MOTIVO')
        if subtab == self._NEW_UI_SUBTAB_REVISION_CM and 'GESTIÓN' in df.columns:
            presentes = self._valores_distintos_por_grupo(serie, df['GESTIÓN'], ('',))
            resumen['GESTIÓN'] = [
                estilo_com.SEPARADOR_CHIPS.join(e for e in (comercial_services.GESTION_CM_NEGOCIACION,
                                                            comercial_services.GESTION_CM_ESPERA,
                                                            comercial_services.GESTION_CM_SIN)
                                                if e in presentes.get(g, {}))
                for g in resumen[clave]]
            columnas_vista.append('GESTIÓN')
        if subtab == self._NEW_UI_SUBTAB_POR_GESTIONAR:
            # Todos los CDB comerciales del cliente (no solo los de la bandeja)
            if 'RUT' in df.columns:
                ruts = self._valores_distintos_por_grupo(serie, df['RUT'], ('', 'NAN', 'NONE', '-'))
                resumen['RUT'] = [", ".join(ruts.get(g, {})) or "-" for g in resumen[clave]]
                columnas_vista.append('RUT')
            cdbs = self._cdbs_por_razon_actual()
            resumen['CDB COMERCIAL'] = [", ".join(cdbs.get(r, [])) or "-" for r in resumen[clave]]
            columnas_vista.append('CDB COMERCIAL')
            if 'OBSERVACIONES' in df.columns:
                trae = df['OBSERVACIONES'].map(trae_volvo_connect).to_numpy()
                conteo = pd.Series(trae).groupby(serie.to_numpy()).sum()
                resumen[self._NEW_UI_COL_CON_VOLVO_CONNECT] = [int(conteo.get(g, 0)) for g in resumen[clave]]
                columnas_vista.append(self._NEW_UI_COL_CON_VOLVO_CONNECT)
                orden_resumen = [self._NEW_UI_COL_CON_VOLVO_CONNECT]
                devueltas = df['OBSERVACIONES'].map(comercial_services.fue_devuelto).to_numpy()
                if devueltas.any():
                    cuenta = pd.Series(devueltas).groupby(serie.to_numpy()).sum()
                    resumen[self._NEW_UI_COL_DEVUELTAS] = [int(cuenta.get(g, 0)) for g in resumen[clave]]
                    columnas_vista.append(self._NEW_UI_COL_DEVUELTAS)
                    orden_resumen.insert(0, self._NEW_UI_COL_DEVUELTAS)
                if not self.new_ui_table.has_active_sort():
                    resumen = resumen.sort_values(orden_resumen, ascending=False, kind='stable')
        columnas_vista.append(col_unidades)
        return resumen, columnas_vista, True

    def _serie_grupo_new_ui(self, df, clave):
        """Columna de agrupación con los vacíos unificados en el valor "sin grupo"."""
        serie = df[clave].fillna('').astype(str).str.strip()
        return serie.mask(serie.str.upper().isin(['', 'NAN', 'NONE', 'NAT', '-', '<NA>']), self._NEW_UI_VALOR_SIN_GRUPO)

    @staticmethod
    def _valores_distintos_por_grupo(grupos, valores, excluir):
        """{grupo: valores distintos en orden de aparición} con el texto sin
        espacios, sin los que en mayúsculas estén en `excluir`. Una sola pasada:
        un agg de Python por grupo costaba ~100 ms con miles de flotas."""
        por_grupo = {}
        for grupo, valor in zip(grupos, valores):
            valor = str(valor).strip()
            if valor.upper() not in excluir:
                por_grupo.setdefault(grupo, {})[valor] = None
        return por_grupo

    def _anchos_vista_grupos(self, columnas):
        # Reparte el ancho visible: la columna clave (y RAZÓN SOCIAL si está)
        # toman más espacio y las numéricas se reparten el resto por igual.
        total = max(self.new_ui_table.viewport().width(), 900)
        pesos = {c: (3.0 if c == 'RAZÓN SOCIAL' else 3.2 if i == 0 else 2.2 if c in ('CDB COMERCIAL', 'GESTIÓN', 'MOTIVO') else 1.0)
                 for i, c in enumerate(columnas)}
        suma = sum(pesos.values())
        return {c: max(NEW_UI_COL_WIDTH_MINIMO, int(total * p / suma)) for c, p in pesos.items()}
    def _salir_vista_agrupada(self):
        self._actualizar_barra_grupo(None)
        self._new_ui_en_grupos = False
        self._new_ui_grupos_df = None
        self.lbl_grupo_abierto.setText("")
        self.new_ui_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def _actualizar_barra_grupo(self, clave, abierto=None):
        self.btn_volver_grupos.setVisible(clave is not None)

    def _on_new_ui_fila_clicada(self, index):
        if getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM:
            return  # ahí el clic selecciona; abre el doble clic (ver _on_new_ui_doble_clic)
        self._abrir_grupo_new_ui(index)

    def _abrir_grupo_new_ui(self, index):
        if not self._new_ui_en_grupos or self._new_ui_grupos_df is None:
            return
        subtab = getattr(self, '_new_ui_active_subtab', 0)
        clave = self._clave_grupo_new_ui(subtab)
        fila = index.row()
        if fila < 0 or fila >= len(self._new_ui_grupos_df) or clave not in self._new_ui_grupos_df.columns:
            return
        self._new_ui_grupo_abierto[subtab] = str(self._new_ui_grupos_df.iloc[fila][clave])
        animar_sobre_tabla(self.new_ui_table, 350)
        self._refresh_new_ui_data()

    def _on_volver_a_grupos_clicked(self):
        self._new_ui_grupo_abierto.pop(getattr(self, '_new_ui_active_subtab', 0), None)
        animar_sobre_tabla(self.new_ui_table, 350)
        self._refresh_new_ui_data()
