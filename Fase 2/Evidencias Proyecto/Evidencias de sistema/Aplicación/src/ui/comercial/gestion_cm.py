"""Estado de gestión de Oportunidades CM (Negociación, Espera, Sin gestión), guardado en OBSERVACIONES."""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt
from src.services import comercial_services as cs
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.esqueleto_carga import animar_sobre_tabla
import qtawesome as qta

_COLORES_GESTION = {cs.GESTION_CM_NEGOCIACION: estilo_com.AZUL, cs.GESTION_CM_ESPERA: estilo_com.AMBAR,
                    cs.GESTION_CM_SIN: estilo_com.PIZARRA}
_ORDEN_BOTONES = (cs.GESTION_CM_NEGOCIACION, cs.GESTION_CM_ESPERA, cs.GESTION_CM_SIN)
_TEXTO_BARRA_VACIA = ("Selecciona una o varias flotas (Ctrl o Shift + clic) para marcar su gestión. "
                      "Doble clic abre la flota.")


def _qss_boton_barra(color):
    return (f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {color}; border: 1px solid {estilo_com.LINEA};"
            " border-radius: 9px; padding: 6px 12px; font-weight: 600; font-size: 12px; }"
            "QPushButton:hover { border-color: #9FB1CF; }"
            f"QPushButton:disabled {{ color: {estilo_com.APAGADO}; background: {estilo_com.SUPERFICIE_2}; }}")


_QSS_FILTRO = ("QPushButton { background: transparent; color: #DCE4F3; border: 1px solid rgba(255,255,255,0.28);"
               " border-radius: 13px; padding: 4px 11px; font-size: 11px; font-weight: 600; min-height: 18px; }"
               "QPushButton:hover { background: rgba(255,255,255,0.10); }"
               "QPushButton:checked { background: white; color: #1B2B4E; border-color: white; }")


class _GestionCmComercialMixin:
    # ------------------------------------------------------------ armado
    def _build_barra_gestion_cm(self):
        """Barra fija sobre la tabla en la lista de flotas: marca la gestión de todas las unidades de las flotas
        seleccionadas. Siempre visible en esa vista para que la tabla no se mueva al seleccionar."""
        barra = QFrame()
        barra.setObjectName("barraGestionCm")
        barra.setStyleSheet(
            f"QFrame#barraGestionCm {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA};"
            " border-left: 4px solid #1B2B4E; border-radius: 12px; }")
        lay = QHBoxLayout(barra)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(8)
        self.lbl_barra_gestion_cm = QLabel(_TEXTO_BARRA_VACIA)
        self.lbl_barra_gestion_cm.setStyleSheet(
            f"color: {estilo_com.TINTA}; font-size: 12px; font-weight: 600; background: transparent; border: none;")
        lay.addWidget(self.lbl_barra_gestion_cm, stretch=1)
        self.botones_barra_gestion_cm = {}
        for estado in _ORDEN_BOTONES:
            color = _COLORES_GESTION[estado]
            btn = QPushButton(f" {estado}")
            btn.setIcon(qta.icon('fa5s.circle', color=color, color_disabled='#C3CCDB'))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_qss_boton_barra(color))
            btn.setToolTip(self._ayuda_gestion_cm(estado))
            btn.setEnabled(False)
            btn.clicked.connect(lambda _c=False, e=estado: self._on_gestion_cm_clicked(e, desde_flotas=True))
            lay.addWidget(btn)
            self.botones_barra_gestion_cm[estado] = btn
        barra.hide()
        self.barra_gestion_cm = barra
        return barra

    def _build_filtros_gestion_cm(self):
        """Pastillas de la banda azul que filtran Oportunidades CM por estado de gestión."""
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(contenedor)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(6)
        self.botones_filtro_gestion_cm = {}
        for clave in (None,) + cs.GESTIONES_CM:
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_QSS_FILTRO)
            btn.clicked.connect(lambda _c=False, k=clave: self._on_filtro_gestion_cm(k))
            lay.addWidget(btn)
            self.botones_filtro_gestion_cm[clave] = btn
        self._filtro_gestion_cm = None
        self._conteo_gestion_cm = {}
        contenedor.hide()
        self.filtros_gestion_cm = contenedor
        return contenedor

    def _build_acciones_rapidas_gestion_cm(self):
        """Grupo "Estado de gestión" de la caja derecha (fase 2), para una o varias unidades."""
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(contenedor)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self._titulo_seccion("Estado de gestión"))
        panel = estilo_com.PanelAcciones(maestro=True)
        grilla = estilo_com.GrillaAcciones(panel, impar_largo=True)
        self.botones_gestion_cm = {}
        subtitulos = {cs.GESTION_CM_NEGOCIACION: "Con los de contrato de mantenimiento",
                      cs.GESTION_CM_ESPERA: "De la respuesta del cliente",
                      cs.GESTION_CM_SIN: "Vuelve al estado inicial"}
        iconos = {cs.GESTION_CM_NEGOCIACION: "fa5s.handshake", cs.GESTION_CM_ESPERA: "fa5s.hourglass-half",
                  cs.GESTION_CM_SIN: "fa5s.undo"}
        for estado in _ORDEN_BOTONES:
            btn = self._build_new_ui_accion_button(iconos[estado], estado, subtitulos[estado],
                                                   color=_COLORES_GESTION[estado])
            btn.setToolTip(self._ayuda_gestion_cm(estado))
            btn.clicked.connect(lambda _c=False, e=estado: self._on_gestion_cm_clicked(e, desde_flotas=False))
            grilla.agregar(btn)
            self.botones_gestion_cm[estado] = btn
        lay.addWidget(panel)
        contenedor.hide()
        self.acciones_rapidas_gestion_cm = contenedor
        return contenedor

    @staticmethod
    def _ayuda_gestion_cm(estado):
        texto = cs.TEXTOS_GESTION_CM.get(estado)
        if texto:
            return f"Guarda en Observaciones: «{texto}»"
        return "Deja la observación en «-» (solo si tenía Negociación o Espera; otras notas no se tocan)"

    # ------------------------------------------------------------ filtro y estado de la vista
    def _aplicar_filtro_gestion_cm(self, df):
        if 'GESTIÓN' not in df.columns:
            self._conteo_gestion_cm = {}
            return df
        # Con una flota abierta las pastillas cuentan solo sus unidades
        base = df
        clave = self._clave_grupo_new_ui(self._NEW_UI_SUBTAB_REVISION_CM)
        abierto = self._new_ui_grupo_abierto.get(self._NEW_UI_SUBTAB_REVISION_CM)
        if abierto is not None and clave in df.columns:
            base = df[(self._serie_grupo_new_ui(df, clave) == abierto).to_numpy()]
        conteo = base['GESTIÓN'].value_counts()
        self._conteo_gestion_cm = {e: int(conteo.get(e, 0)) for e in cs.GESTIONES_CM}
        self._conteo_gestion_cm[None] = len(base)
        filtro = self.__dict__.get('_filtro_gestion_cm')
        return df[df['GESTIÓN'] == filtro] if filtro else df

    def _on_filtro_gestion_cm(self, clave):
        self._filtro_gestion_cm = clave
        animar_sobre_tabla(self.new_ui_table, 250)
        self._refresh_new_ui_data()

    def _actualizar_barra_gestion_cm(self):
        barra = self.__dict__.get('barra_gestion_cm')
        if barra is None:
            return
        es_cm = getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM
        barra.setVisible(es_cm and bool(self.__dict__.get('_new_ui_en_grupos')))
        self.filtros_gestion_cm.setVisible(es_cm)
        if es_cm:
            actual = self.__dict__.get('_filtro_gestion_cm')
            for clave, btn in self.botones_filtro_gestion_cm.items():
                btn.setText(f"{clave or 'Todos'} {self._conteo_gestion_cm.get(clave, 0)}")
                btn.setChecked(clave == actual)
        self._actualizar_seleccion_gestion_cm()

    def _flotas_seleccionadas_gestion_cm(self):
        grupos = self.__dict__.get('_new_ui_grupos_df')
        if not self.__dict__.get('_new_ui_en_grupos') or grupos is None or grupos.empty:
            return []
        clave = self._clave_grupo_new_ui(self._NEW_UI_SUBTAB_REVISION_CM)
        filas = sorted({i.row() for i in self.new_ui_table.selectionModel().selectedRows()})
        return [str(grupos.iloc[f][clave]) for f in filas if f < len(grupos) and clave in grupos.columns]

    def _vins_de_flotas_gestion_cm(self, flotas):
        df = self.__dict__.get('_new_ui_revision_cm_completo')
        clave = self._clave_grupo_new_ui(self._NEW_UI_SUBTAB_REVISION_CM)
        if df is None or df.empty or clave not in df.columns or not flotas:
            return []
        serie = self._serie_grupo_new_ui(df, clave)
        return df.loc[serie.isin(set(flotas)).to_numpy(), 'VIN'].astype(str).str.strip().str.upper().unique().tolist()

    def _actualizar_seleccion_gestion_cm(self):
        barra = self.__dict__.get('barra_gestion_cm')
        if barra is None or not barra.isVisibleTo(self):
            return
        flotas = self._flotas_seleccionadas_gestion_cm()
        for btn in self.botones_barra_gestion_cm.values():
            btn.setEnabled(bool(flotas))
        if flotas:
            n = len(self._vins_de_flotas_gestion_cm(flotas))
            s = "s" if len(flotas) > 1 else ""
            self.lbl_barra_gestion_cm.setText(
                f"{len(flotas)} flota{s} seleccionada{s} · {n} unidades. Doble clic abre la flota.")
        else:
            self.lbl_barra_gestion_cm.setText(_TEXTO_BARRA_VACIA)

    def _on_new_ui_doble_clic(self, index):
        """En Oportunidades CM el clic selecciona flotas (para marcar su gestión) y el doble clic abre la flota."""
        if getattr(self, '_new_ui_active_subtab', 0) != self._NEW_UI_SUBTAB_REVISION_CM:
            return
        self._abrir_grupo_new_ui(index)

    # ------------------------------------------------------------ guardado
    def _on_gestion_cm_clicked(self, estado, desde_flotas):
        if desde_flotas:
            vins = self._vins_de_flotas_gestion_cm(self._flotas_seleccionadas_gestion_cm())
        else:
            vins, _ = self._obtener_vins_seleccionados()
        if not vins:
            return
        cambios, reemplazadas = cs.cambios_gestion_cm(self._filas_base_por_vin(vins), estado)
        if not cambios:
            return  # ya estaban en ese estado
        if reemplazadas and not self._confirmar_accion_cm(
                f"Marcar {estado}", 'fa5s.comment-alt', f"{len(cambios)} unidad(es) pasan a {estado}",
                "Algunas unidades tienen en Observaciones una nota que no es un estado de gestión. "
                "Esa nota se reemplaza por el estado.",
                [f"{reemplazadas} nota(s) se reemplazan", "El cambio queda en el historial"]):
            return
        self._guardar_cambios_oportunidades_cm(
            cambios, "Guardando la gestión…",
            "No se pudo guardar la gestión. SharePoint puede estar bloqueando el archivo. Intenta de nuevo.")
