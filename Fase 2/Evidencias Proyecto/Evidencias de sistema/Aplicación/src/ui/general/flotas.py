"""Pestaña Flotas de General: lista, detalle, contactos, unidades y exportación a Excel."""
from src.theme.colors import BORDER, FILA_HOVER_TABLA, FILA_SELECCION_TABLA, SURFACE, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY
import re
import unicodedata
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QStackedWidget, QHeaderView, QScrollArea, QMenu, QGridLayout, QSizePolicy, QTableWidget, QTableWidgetItem, QAbstractItemView
from PyQt6.QtCore import QItemSelectionModel, Qt
from PyQt6.QtGui import QShortcut, QKeySequence, QColor, QFont
from src.core.constants import COL_INDUSTRIA, COL_VIN, COL_TIPO_SERVICIO, COL_EJECUTIVO, COL_MODELO, COL_ESTADO_COMERCIAL
from src.services import cm_bajas_service, comercial_services
from src.ui.compartido.copiar import escribir_portapapeles
from src.ui.compartido.menu_contextual import crear_menu, texto_corto
from src.theme.theme_manager import ThemeManager
from src.services import general_services
from src.ui.general.tarjetas import contar_civ_sz
from src.ui.general.base import (
    AZUL,
    AZUL_HOVER,
    COLUMNAS_FLOTAS,
    CopyableTitulo,
    FiltroValoresBoton,
    GeneralFlotaCard,
    LINEA_AZUL,
    NUM_COLUMNAS_LISTA,
    QSS_CONTENEDOR_PESTANAS_CLARO,
    QSS_PESTANAS_CLARAS,
    QSS_TARJETAS_CLIENTE,
    TEXTO_SOBRE_AZUL,
    _BloqueEstadoFlota,
    _COLUMNAS_EXPORT_FLOTA,
    _COLUMNAS_TABLA_FLOTA,
    _ChipCopiaLista,
    _DelegadoChipsUnidades,
    _FILTROS_UNIDADES,
    _FilaClienteFlota,
    _GrillaTarjetas,
    _GrupoControles,
    _boton_sobre_azul,
    _clave_flota_texto,
    _color_estado_activacion,
    _color_estado_comercial,
    _con_transicion_derecha,
    _crear_invitacion,
    _flota_valida,
    _formatear_fecha_contrato,
    _resumir_celda_flota,
    _tarjeta_blanca,
)


class _FlotasGeneralMixin:
    # ==========================================
    # PESTAÑA "FLOTA" (28-10-2026, a pedido de Javiera): una tarjeta por Flota
    # VC, que se abre primero. Una flota puede tener varios clientes y un
    # cliente varias flotas. La búsqueda es la del buscador global de MainWindow
    # (filter_table); esta pestaña no tiene buscador propio.
    # ==========================================
    def _build_flota_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        pag_top, self._lbl_pagina_flotas_top, self._btn_pagina_ant_flotas_top, self._btn_pagina_sig_flotas_top = \
            self._crear_controles_paginacion(self._pagina_anterior_flotas, self._pagina_siguiente_flotas)
        pag_top.setParent(widget)
        pag_top.hide()

        # Van en la barra azul de arriba, a la derecha de las pestañas; solo se ven en Flota
        self._controles_flota = top_row = _GrupoControles(self._barra_nav_layout)
        self._extras_flota = _GrupoControles(self._fila_subtitulo_layout)
        self._lbl_total_flotas = QLabel("")
        self._lbl_total_flotas.setStyleSheet(
            f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; font-weight: bold; background: transparent; padding-right: 4px;")
        self._extras_flota.addWidget(self._lbl_total_flotas)
        self.btn_filtro_vins_flotas = QPushButton()
        self.btn_filtro_vins_flotas.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filtro_vins_flotas.setToolTip("Quitar este filtro y volver a ver todas las flotas")
        _boton_sobre_azul(self.btn_filtro_vins_flotas)
        self.btn_filtro_vins_flotas.clicked.connect(self._quitar_filtro_vins_flotas)
        self._extras_flota.addWidget(self.btn_filtro_vins_flotas)
        self.btn_filtro_vins_flotas.hide()
        selector_pagina = self._crear_selector_tamano_pagina(self._on_cambiar_tamano_pagina_flotas)
        boton_orden = self._crear_boton_ordenar(self._on_cambiar_orden_flotas, self._on_cambiar_orden_flotas_unidades)
        for boton in (selector_pagina, boton_orden):
            _boton_sobre_azul(boton)
            top_row.addWidget(boton)

        self.flotas_scroll = QScrollArea()
        self.flotas_scroll.setWidgetResizable(True)
        self.flotas_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.flotas_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.flotas_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.flotas_scroll.viewport().setStyleSheet("background: transparent;")

        flotas_container = QWidget()
        flotas_container.setStyleSheet(QSS_TARJETAS_CLIENTE)
        self.flotas_layout = _GrillaTarjetas(NUM_COLUMNAS_LISTA, flotas_container)
        self.flotas_layout.setContentsMargins(2, 2, 2, 2)
        self.flotas_layout.setSpacing(8)
        self.flotas_layout.addStretch()
        self.flotas_scroll.setWidget(flotas_container)
        layout.addWidget(self.flotas_scroll, stretch=1)

        pag_bottom, self._lbl_pagina_flotas_bottom, self._btn_pagina_ant_flotas_bottom, self._btn_pagina_sig_flotas_bottom = \
            self._crear_controles_paginacion(self._pagina_anterior_flotas, self._pagina_siguiente_flotas)
        layout.addWidget(pag_bottom)
        return widget

    def _on_cambiar_orden_flotas(self, is_asc):
        self._flotas_orden_campo = 'nombre'
        self._flotas_orden_asc = is_asc
        self.filter_flotas()

    def _on_cambiar_orden_flotas_unidades(self, is_asc):
        self._flotas_orden_campo = 'unidades'
        self._flotas_orden_asc = is_asc
        self.filter_flotas()

    def _on_cambiar_tamano_pagina_flotas(self, nuevo_tamano):
        self._flotas_tam_pagina = nuevo_tamano
        self._flotas_pagina_actual = 0
        self._animar_carga_breve(solo_izquierda=True)
        self._pintar_pagina_flotas()

    def _render_flotas_cards(self, df_f):
        """Igual que _render_clientes_cards: vuelve a la página 1 y solo pinta si Flota (índice 2) está visible."""
        self._flotas_df_paginado = df_f
        self._flotas_pagina_actual = 0
        if self.left_stack.currentIndex() == 2:
            self._pintar_pagina_flotas()
            self._flotas_pendiente_render = False
        else:
            self._flotas_pendiente_render = True

    def _pagina_anterior_flotas(self):
        if self._flotas_pagina_actual > 0:
            self._flotas_pagina_actual -= 1
            self._animar_carga_breve(solo_izquierda=True)
            self._pintar_pagina_flotas()

    def _pagina_siguiente_flotas(self):
        total_paginas = max(1, -(-len(self._flotas_df_paginado) // self._flotas_tam_pagina))
        if self._flotas_pagina_actual < total_paginas - 1:
            self._flotas_pagina_actual += 1
            self._animar_carga_breve(solo_izquierda=True)
            self._pintar_pagina_flotas()

    def _pintar_pagina_flotas(self):
        layout = self.flotas_layout
        layout.vaciar()
        self._flota_cards = {}
        self._cancelar_tandas('flotas')

        df_f = self._flotas_df_paginado
        total_paginas = max(1, -(-len(df_f) // self._flotas_tam_pagina))
        self._lbl_total_flotas.setText(f"{len(df_f):,} flota{'' if len(df_f) == 1 else 's'}".replace(",", "."))
        self._actualizar_controles_paginacion(
            self._flotas_pagina_actual, total_paginas,
            (self._lbl_pagina_flotas_top, self._btn_pagina_ant_flotas_top, self._btn_pagina_sig_flotas_top),
            (self._lbl_pagina_flotas_bottom, self._btn_pagina_ant_flotas_bottom, self._btn_pagina_sig_flotas_bottom),
        )

        if df_f.empty:
            lbl_vacio = QLabel("No hay flotas que coincidan con la búsqueda.")
            lbl_vacio.setWordWrap(True)
            lbl_vacio.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 12px;")
            layout.addWidget(lbl_vacio, 0, 0, 1, layout.columnas)
            layout.addStretch()
            return

        inicio = self._flotas_pagina_actual * self._flotas_tam_pagina
        fin = min(inicio + self._flotas_tam_pagina, len(df_f))

        encontrados = self.__dict__.get('_encontrados_por_flota') or {}

        def crear(row_idx):
            fila = df_f.iloc[row_idx]
            clave = str(fila.get('Clave', ''))
            card = GeneralFlotaCard(
                row_idx, fila.get('Flota', ''), fila.get('Cliente', ''), fila.get('RUT', ''), fila.get('CDB Flota', ''),
                int(fila.get('Total unidades', 0) or 0), int(fila.get('Total clientes', 0) or 0),
                encontrados=int(encontrados.get(clave, 0)))
            card.clicked.connect(self._on_flota_card_clicked)
            self._flota_cards[clave] = card
            if self._selected_flota_key and clave == self._selected_flota_key:
                card.set_selected(True)
            return card
        self._construir_tarjetas_por_tandas('flotas', layout, range(inicio, fin), crear)

    def _on_flota_card_clicked(self, row_idx):
        if row_idx < 0 or row_idx >= len(self._df_flotas_visible):
            return
        fila = self._df_flotas_visible.iloc[row_idx]
        anterior = self._selected_flota_key
        if anterior and anterior in self._flota_cards:
            self._flota_cards[anterior].set_selected(False)
        nueva = str(fila.get('Clave', ''))
        if nueva in self._flota_cards:
            self._flota_cards[nueva].set_selected(True)
        self._show_flota_detalle(fila)

    def _buscar_flota_por_clave(self, clave):
        """Fila de df_flotas_base de una clave de flota, o None."""
        if not clave or self.df_flotas_base.empty or 'Clave' not in self.df_flotas_base.columns:
            return None
        coincidencias = self.df_flotas_base[self.df_flotas_base['Clave'].astype(str) == str(clave)]
        return None if coincidencias.empty else coincidencias.iloc[0]

    def _sincronizar_seleccion_flota(self, df_visible):
        """Tras recalcular la lista, mantiene la caja derecha en la flota que ya se estaba viendo.
        Solo actúa si la pestaña izquierda activa es Flota."""
        if self.left_stack.currentIndex() != 2:
            return
        if self._selected_flota_key and 'Clave' in df_visible.columns:
            posiciones = (df_visible['Clave'].astype(str) == self._selected_flota_key).to_numpy().nonzero()[0]
            if len(posiciones):
                self._show_flota_detalle(df_visible.iloc[int(posiciones[0])])
                return
        self._show_flota_vacio()

    _claves_flota = staticmethod(general_services.claves_flota)

    _build_flotas_df = staticmethod(general_services.build_flotas_df)

    @staticmethod
    def _aplicar_busqueda_flotas(df, texto_busqueda):
        """Buscador global sobre la lista de Flota: coincide con la flota, sus clientes, RUT (con o sin
        puntos y guion), CDB, VIN o chasis. Términos separados por coma se combinan con OR."""
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

    def filter_flotas(self):
        # __dict__.get: tolera instancias creadas con __new__ en los tests
        if self.__dict__.get('flotas_layout') is None:
            return
        if self.df_flotas_base.empty:
            self._df_flotas_visible = pd.DataFrame(columns=COLUMNAS_FLOTAS)
            self._render_flotas_cards(self._df_flotas_visible)
            self._sincronizar_seleccion_flota(self._df_flotas_visible)
            return

        df_f = self._aplicar_busqueda_flotas(self.df_flotas_base, self.search_input.text())
        if self._flotas_orden_campo == 'unidades':
            df_f = df_f.sort_values(by=['Total unidades', 'Flota'], ascending=[self._flotas_orden_asc, True], na_position='last')
        else:
            df_f = df_f.sort_values(by='Flota', ascending=self._flotas_orden_asc, na_position='last',
                                    key=lambda s: s.astype(str).map(_clave_flota_texto))
        df_f = df_f.reset_index(drop=True)
        antes = getattr(self, '_vins_busqueda_flota', None)
        filtro_vins = self.__dict__.get('_filtro_vins_flotas')
        if filtro_vins is not None:
            # Desde el Dashboard: solo las flotas de esos VIN, que quedan como los VIN buscados
            claves_vin, self._vins_busqueda_flota = self._claves_flota_de_vins(filtro_vins)
            df_f = df_f[df_f['Clave'].astype(str).isin(claves_vin)].reset_index(drop=True)
        else:
            claves_vin, self._vins_busqueda_flota = self._claves_flota_por_vin_buscado(self.search_input.text())
        self._encontrados_por_flota = self._contar_vins_por_flota(self._vins_busqueda_flota)
        if antes and not claves_vin and self.__dict__.get('_flota_unidades_construidas', False):
            self._pintar_unidades_flota()
        if claves_vin and filtro_vins is None:
            # Un VIN buscado también trae a su flota, aunque el buscador no la haya encontrado por otro dato
            faltantes = self.df_flotas_base[self.df_flotas_base['Clave'].astype(str).isin(claves_vin)
                                            & ~self.df_flotas_base['Clave'].isin(df_f['Clave'])]
            if not faltantes.empty:
                df_f = pd.concat([df_f, faltantes], ignore_index=True)
        self._df_flotas_visible = df_f
        self._render_flotas_cards(df_f)
        self._sincronizar_seleccion_flota(df_f)
        self._abrir_flota_de_vin_buscado(df_f, claves_vin)

    def _claves_flota_por_vin_buscado(self, texto_busqueda):
        """(claves de flota, VIN encontrados) para los términos de la búsqueda que parecen un VIN (8 a 17
        letras o dígitos). Con 17 caracteres debe coincidir completo; con menos, basta que lo contenga."""
        terminos = {t.upper() for t in re.split(r'[,\s;]+', texto_busqueda.strip()) if re.fullmatch(r'[A-Za-z0-9]{8,17}', t)}
        df = self.df_comercial_raw
        if not terminos or df.empty or COL_VIN not in df.columns or '_clave_flota' not in df.columns:
            return set(), set()
        vins = df[COL_VIN].astype(str).str.strip().str.upper()
        mascara = vins.isin([t for t in terminos if len(t) == 17])
        for t in (t for t in terminos if len(t) < 17):
            mascara |= vins.str.contains(t, regex=False)
        if not mascara.any():
            return set(), set()
        return set(df.loc[mascara, '_clave_flota'].astype(str)), set(vins[mascara])

    def _contar_vins_por_flota(self, vins):
        """{clave de flota: cuántos de estos VIN tiene} para el chip «N VIN encontrados» de cada tarjeta."""
        df = self.df_comercial_raw
        if not vins or df.empty or COL_VIN not in df.columns or '_clave_flota' not in df.columns:
            return {}
        v = df[COL_VIN].astype(str).str.strip().str.upper()
        sub = pd.DataFrame({'VIN': v, 'Clave': df['_clave_flota'].astype(str)})[v.isin(vins)]
        conteo = sub.groupby('Clave')['VIN'].nunique().to_dict()
        pedidos = self.__dict__.get('_filtro_vins_flotas')
        if pedidos and '_clave_cliente' in df.columns:
            # Desde el Dashboard la tabla de cada flota suma las unidades pedidas sin flota de sus mismos clientes
            # (ver _con_unidades_sin_flota_pedidas): el chip de la tarjeta las cuenta igual
            flota = df['_clave_flota'].astype(str).str.strip()
            cliente = df['_clave_cliente'].astype(str)
            invalidos = ('', 'RS:', 'nan')
            sin_flota = df[v.isin(pedidos) & (flota == '') & ~cliente.isin(invalidos)]
            if not sin_flota.empty:
                por_cliente = sin_flota.assign(_v=v[sin_flota.index]).groupby('_clave_cliente')['_v'].agg(set)
                con_flota = pd.DataFrame({'Clave': df['_clave_flota'].astype(str), 'Cliente': cliente})
                con_flota = con_flota[(flota != '') & ~cliente.isin(invalidos)]
                clientes_flota = con_flota.groupby('Clave')['Cliente'].agg(set)
                for clave, clientes in clientes_flota.items():
                    extra = set().union(*(por_cliente.get(c, set()) for c in clientes))
                    if extra and clave in conteo:
                        conteo[clave] += len(extra)
        return conteo

    def _claves_flota_de_vins(self, vins):
        """(claves de flota, VIN encontrados) de estas unidades; las que no tienen flota no aportan clave."""
        df = self.df_comercial_raw
        if not vins or df.empty or COL_VIN not in df.columns or '_clave_flota' not in df.columns:
            return set(), set()
        v = df[COL_VIN].astype(str).str.strip().str.upper()
        mascara = v.isin(vins)
        claves = {c for c in df.loc[mascara, '_clave_flota'].astype(str) if c.strip()}
        return claves, set(v[mascara])

    def _abrir_flota_de_vin_buscado(self, df_visible, claves_vin):
        """Con un VIN en la búsqueda: abre la flota que lo tiene y deja su pestaña Unidades a la vista,
        con los VIN buscados primero y seleccionados (ver _pintar_unidades_flota). Si los VIN son de varias
        flotas no abre ninguna: queda la lista de flotas."""
        if len(claves_vin) != 1 or self.left_stack.currentIndex() != 2 or 'Clave' not in df_visible.columns:
            return
        for fila_idx, clave in enumerate(df_visible['Clave'].astype(str)):
            if clave not in claves_vin:
                continue
            if clave != self._selected_flota_key:
                self._on_flota_card_clicked(fila_idx)
            elif self.__dict__.get('_flota_unidades_construidas', False):
                self._pintar_unidades_flota()
            self._switch_flota_detalle_view(1)
            return

    # ---- Caja derecha: ficha de la flota ----
    def _build_flota_vacio_view(self):
        """Ficha de flota sin selección: la portada en blanco y una invitación a elegir una flota."""
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
        lay_p.setContentsMargins(16, 14, 16, 0)
        lay_p.setSpacing(0)

        icono = QLabel()
        icono.setFixedSize(40, 40)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.truck', color=TEXTO_SOBRE_AZUL, size=18))
        icono.setStyleSheet("background: rgba(255,255,255,0.08); border: 2px dashed rgba(255,255,255,0.4); border-radius: 20px;")
        titulo = QLabel("Ninguna flota seleccionada")
        titulo.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 18px; font-weight: bold;")
        fila_superior = QHBoxLayout()
        fila_superior.setSpacing(10)
        fila_superior.addWidget(icono)
        fila_superior.addWidget(titulo, 1)
        lay_p.addLayout(fila_superior)
        lay_p.addSpacing(8)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for texto in ("Cliente: —", "RUT: —", "CDB Comercial: —", "CDB Flota: —"):
            chip = QLabel(texto)
            chip.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; padding: 3px 10px; "
                               "border: 1px solid rgba(255,255,255,0.18); border-radius: 9px; background-color: rgba(255,255,255,0.05);")
            chips.addWidget(chip)
        chips.addStretch()
        lay_p.addLayout(chips)
        lay_p.addStretch(1)

        pestanas = QHBoxLayout()
        pestanas.setSpacing(2)
        for texto in ("Resumen", "Unidades", "Clientes"):
            lbl_tab = QLabel(texto)
            lbl_tab.setStyleSheet("color: rgba(201,212,234,0.45); font-size: 13px; padding: 10px 16px;")
            pestanas.addWidget(lbl_tab)
        pestanas.addStretch()
        lay_p.addLayout(pestanas)
        lay_hoja.addWidget(portada)
        self._portadas_unidad = self.__dict__.get('_portadas_unidad', []) + [portada]

        kpis = QHBoxLayout()
        kpis.setSpacing(8)
        for titulo_k in ("UNIDADES", "VOLVO CONNECT", "CIV", "SAFETY ZONE"):
            card, _ = self._crear_kpi_comercial(titulo_k, "—", "")
            kpis.addWidget(card)
        kpis.setContentsMargins(14, 12, 14, 0)
        lay_hoja.addLayout(kpis)

        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 12, 14, 14)
        cuerpo.addWidget(_crear_invitacion("Presiona una flota de la lista",
                                           "Aquí verás sus clientes, sus unidades y podrás exportar toda la flota a Excel."), 1)
        lay_hoja.addLayout(cuerpo, 1)

        raiz.addWidget(hoja, 1)
        return widget

    def _build_flota_detalle_view(self):
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
        layout.setContentsMargins(16, 14, 16, 0)
        layout.setSpacing(0)

        icono = QLabel()
        icono.setFixedSize(40, 40)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.truck', color='white', size=18))
        icono.setStyleSheet("background: rgba(255,255,255,0.12); border: 2px solid rgba(255,255,255,0.45); border-radius: 20px;")

        self.lbl_flota_title = CopyableTitulo("")
        self.lbl_flota_title.setWordWrap(True)
        self.lbl_flota_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.btn_exportar_flota = QPushButton(" Exportar Excel")
        self.btn_exportar_flota.setIcon(ThemeManager.icon('fa5s.file-excel', color=AZUL))
        self.btn_exportar_flota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_exportar_flota.setToolTip("Excel con toda la flota: resumen por estado y detalle de cada unidad")
        _boton_sobre_azul(self.btn_exportar_flota)
        self.btn_exportar_flota.clicked.connect(self._exportar_excel_flota)
        fila_superior = QHBoxLayout()
        fila_superior.setSpacing(10)
        fila_superior.addWidget(icono)
        fila_superior.addWidget(self.lbl_flota_title, 1)
        fila_superior.addWidget(self.btn_exportar_flota, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(fila_superior)
        layout.addSpacing(8)

        # Con varios clientes, Cliente / RUT / CDB Comercial abren una lista para elegir cuál copiar
        subtitle_row = QHBoxLayout()
        subtitle_row.setSpacing(6)
        self.chip_flota_cliente = _ChipCopiaLista()
        self.chip_flota_rut = _ChipCopiaLista()
        self.chip_flota_cdb = _ChipCopiaLista()
        self.chip_flota_copiar = _ChipCopiaLista()
        self.chip_flota_cdb_flota = _ChipCopiaLista()
        for chip in (self.chip_flota_cliente, self.chip_flota_rut, self.chip_flota_cdb,
                     self.chip_flota_copiar, self.chip_flota_cdb_flota):
            subtitle_row.addWidget(chip)
        subtitle_row.addStretch()
        layout.addLayout(subtitle_row)
        layout.addStretch(1)

        self.bloque_estado_flota = _BloqueEstadoFlota()

        barra = QFrame()
        barra.setObjectName("barraPestanasGeneral")
        barra.setStyleSheet(QSS_CONTENEDOR_PESTANAS_CLARO)
        barra_layout = QHBoxLayout(barra)
        barra_layout.setContentsMargins(0, 0, 0, 0)
        barra_layout.setSpacing(2)
        self.btn_flota_resumen = QPushButton("Resumen")
        self.btn_flota_unidades = QPushButton("Unidades")
        self.btn_flota_contactos = QPushButton("Contactos")
        self._flota_nav_buttons = [self.btn_flota_resumen, self.btn_flota_unidades, self.btn_flota_contactos]
        for i, btn in enumerate(self._flota_nav_buttons):
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(QSS_PESTANAS_CLARAS)
            btn.clicked.connect(lambda checked, idx=i: self._switch_flota_detalle_view(idx))
            barra_layout.addWidget(btn)
        barra_layout.addStretch()
        self.btn_flota_resumen.setChecked(True)
        layout.addWidget(barra)
        lay_hoja.addWidget(portada)
        self._portadas_unidad = self.__dict__.get('_portadas_unidad', []) + [portada]
        contenedor_estado = QWidget()
        lay_estado = QVBoxLayout(contenedor_estado)
        lay_estado.setContentsMargins(14, 12, 14, 0)
        lay_estado.addWidget(self.bloque_estado_flota)
        lay_hoja.addWidget(contenedor_estado)

        self.flota_detalle_stack = QStackedWidget()
        self.flota_detalle_stack.setContentsMargins(14, 12, 14, 14)
        self.flota_detalle_stack.addWidget(self._build_flota_resumen_view())
        self.flota_detalle_stack.addWidget(self._build_flota_unidades_view())
        self.flota_detalle_stack.addWidget(self._build_flota_contactos_view())
        self.flota_detalle_stack.setStyleSheet("background: transparent;")

        # El encabezado y las cifras quedan fijos; solo el contenido de la pestaña se desplaza
        self.flota_detalle_scroll = QScrollArea()
        self.flota_detalle_scroll.setWidgetResizable(True)
        self.flota_detalle_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.flota_detalle_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.flota_detalle_scroll.viewport().setStyleSheet("background: transparent;")
        self.flota_detalle_scroll.setWidget(self.flota_detalle_stack)
        # Los filtros quedan fijos arriba mientras se desplaza la tabla (solo en la pestaña Unidades)
        self._contenedor_filtros_flota = QWidget()
        lay_filtros = QVBoxLayout(self._contenedor_filtros_flota)
        lay_filtros.setContentsMargins(14, 8, 14, 0)
        lay_filtros.addWidget(self._filtros_flota_frame)
        self._contenedor_filtros_flota.hide()
        lay_hoja.addWidget(self._contenedor_filtros_flota)
        lay_hoja.addWidget(self.flota_detalle_scroll, stretch=1)
        raiz.addWidget(hoja, 1)
        return widget

    def _build_flota_resumen_view(self):
        widget = QWidget()
        columnas = QHBoxLayout(widget)
        columnas.setContentsMargins(0, 0, 0, 0)
        columnas.setSpacing(12)
        columna_info = QVBoxLayout()
        columna_info.setSpacing(6)
        layout = columna_info

        info_frame = QFrame()
        ThemeManager.apply_card_style(info_frame)
        _tarjeta_blanca(info_frame)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 8, 10, 10)
        info_layout.setSpacing(4)
        lbl_info = QLabel("INFORMACIÓN DE LA FLOTA")
        lbl_info.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        info_layout.addWidget(lbl_info)
        self.info_flota_layout = QGridLayout()
        self.info_flota_layout.setHorizontalSpacing(24)
        self.info_flota_layout.setVerticalSpacing(0)
        self.info_flota_layout.setColumnStretch(0, 1)
        self.info_flota_layout.setColumnStretch(1, 1)
        info_layout.addLayout(self.info_flota_layout)
        layout.addWidget(info_frame)
        layout.addStretch()
        columnas.addLayout(columna_info, 1)

        # A la derecha, los clientes de la flota: cada fila abre ese cliente en la pestaña Cliente
        clientes_frame = QFrame()
        ThemeManager.apply_card_style(clientes_frame)
        _tarjeta_blanca(clientes_frame)
        clientes_layout = QVBoxLayout(clientes_frame)
        clientes_layout.setContentsMargins(10, 8, 10, 10)
        clientes_layout.setSpacing(6)
        self.lbl_flota_clientes_titulo = QLabel("CLIENTES DE LA FLOTA")
        self.lbl_flota_clientes_titulo.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        clientes_layout.addWidget(self.lbl_flota_clientes_titulo)
        self.flota_clientes_lista = QVBoxLayout()
        self.flota_clientes_lista.setSpacing(6)
        clientes_layout.addLayout(self.flota_clientes_lista)
        self.lbl_flota_clientes_resumen = QLabel("")
        self.lbl_flota_clientes_resumen.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        clientes_layout.addWidget(self.lbl_flota_clientes_resumen)
        columna_clientes = QVBoxLayout()
        columna_clientes.addWidget(clientes_frame)
        columna_clientes.addStretch()
        columnas.addLayout(columna_clientes, 1)
        return widget

    def _build_flota_contactos_view(self):
        """Directores de los clientes de la flota (BBDD CLIENTES CM) y administradores por CDB flota (contactos.xlsx)."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.lbl_flota_contactos_titulo = QLabel("CONTACTOS DE LA FLOTA")
        self.lbl_flota_contactos_titulo.setStyleSheet(
            f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        self.btn_flota_agregar_contacto = QPushButton(" + Agregar contacto")
        self.btn_flota_agregar_contacto.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_flota_agregar_contacto.setToolTip("Abre Administración > Contactos con el CDB y la flota ya completados")
        self.btn_flota_agregar_contacto.setStyleSheet(f"""
            QPushButton {{ background-color: {AZUL}; color: white; border: none;
                          border-radius: 8px; padding: 6px 12px; font-weight: bold; font-size: 11px; }}
            QPushButton:hover {{ background-color: {AZUL_HOVER}; }}
            QPushButton:disabled {{ background-color: {BORDER}; color: {TEXT_MUTED}; }}
        """)
        self.btn_flota_agregar_contacto.clicked.connect(self._agregar_contacto_flota)
        fila_titulo = QHBoxLayout()
        fila_titulo.addWidget(self.lbl_flota_contactos_titulo)
        fila_titulo.addStretch()
        fila_titulo.addWidget(self.btn_flota_agregar_contacto)
        layout.addLayout(fila_titulo)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        scroll.viewport().setStyleSheet("background: transparent;")
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        self.flota_contactos_layout = QVBoxLayout(contenedor)
        self.flota_contactos_layout.setContentsMargins(0, 2, 4, 2)
        self.flota_contactos_layout.setSpacing(8)
        scroll.setWidget(contenedor)
        layout.addWidget(scroll)
        return widget

    def _agregar_contacto_flota(self):
        """Lleva a Administración > Contactos con el formulario de nuevo contacto y el CDB flota y la flota completados."""
        df_u = self._df_flota_actual
        cdbs = self._cdbs_flota_de_unidades(df_u) if df_u is not None and not df_u.empty else []
        abrir = getattr(self.window(), 'abrir_nuevo_contacto_flota', None)
        if abrir is None:
            return
        nombre = self._nombre_flota_actual
        if not cdbs:
            from src.ui.compartido.dialogo_accion import DialogoAccion
            DialogoAccion.aviso(self, "Sin CDB flota", "Esta flota no tiene CDB flota, por eso no se puede agregar un contacto desde aquí.").exec()
            return
        if len(cdbs) == 1:
            abrir(cdbs[0], nombre)
            return
        menu = crear_menu(self.btn_flota_agregar_contacto)
        for cdb in cdbs:
            menu.accion(f"CDB flota {cdb}", 'fa5s.hashtag').triggered.connect(lambda _c=False, c=cdb: abrir(c, nombre))
        menu.exec(self.btn_flota_agregar_contacto.mapToGlobal(self.btn_flota_agregar_contacto.rect().bottomLeft()))

    def _populate_contactos_flota(self, df_u=None):
        """Contactos de la flota seleccionada: un director por cada cliente (CDB comercial) y todos los
        administradores de sus CDB flota."""
        if df_u is None:
            df_u = self._df_flota_actual
        if df_u is None or df_u.empty:
            return
        cdbs_flota = self._cdbs_flota_de_unidades(df_u)
        encontrados = self._filtrar_contactos_por_cdb(self.data_manager.get_contactos_df(), cdbs_flota)
        directores, vistos = [], set()
        for cliente in self._clientes_de_flota(df_u):
            cdb = str(cliente['cdb']).strip()
            datos = self._pbi_director_empresa_por_cdb.get(cdb) or {}
            clave = (datos.get('correo', ''), datos.get('telefono', ''))
            if (clave[0] or clave[1]) and clave not in vistos:
                vistos.add(clave)
                directores.append(datos)
        self._populate_contact_cards(self.flota_contactos_layout, encontrados, directores[0] if directores else None)
        for i, datos in enumerate(directores[1:], start=1):
            self.flota_contactos_layout.insertWidget(
                i, self._create_director_empresa_card(datos.get('correo', ''), datos.get('telefono', '')))
        self.lbl_flota_contactos_titulo.setText(
            f"CONTACTOS DE LA FLOTA ({len(directores)} directores, {len(encontrados)} administradores)")

    def _build_flota_unidades_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        # Mismos filtros de la pestaña Contratos (sin Flota VC, que aquí es siempre la misma)
        filtros_frame = QFrame()
        ThemeManager.apply_card_style(filtros_frame)
        _tarjeta_blanca(filtros_frame)
        fila_filtros = QHBoxLayout(filtros_frame)
        fila_filtros.setContentsMargins(8, 6, 8, 6)
        fila_filtros.setSpacing(6)
        self._filtros_flota_unidades = {}
        for columna, titulo in _FILTROS_UNIDADES:
            if columna == 'Flota VC':
                continue
            boton = FiltroValoresBoton(titulo)
            boton.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            boton.setMinimumWidth(0)
            boton.cambiado.connect(self._pintar_unidades_flota)
            self._filtros_flota_unidades[columna] = boton
            fila_filtros.addWidget(boton, 1)
        btn_limpiar = QPushButton()
        btn_limpiar.setIcon(ThemeManager.icon('fa5s.eraser', color=TEXT_SECONDARY))
        btn_limpiar.setToolTip("Limpiar filtros")
        btn_limpiar.setFixedSize(26, 26)
        btn_limpiar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_limpiar.setStyleSheet("QPushButton { border: none; border-radius: 13px; background: transparent; }"
                                  "QPushButton:hover { background: #E3E8F0; }")
        btn_limpiar.clicked.connect(self._limpiar_filtros_flota_unidades)
        fila_filtros.addWidget(btn_limpiar)
        self._filtros_flota_frame = filtros_frame

        self.lbl_flota_unidades_resumen = QLabel("")
        self.lbl_flota_unidades_resumen.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self.lbl_flota_unidades_resumen)

        self.tabla_flota_unidades = self._crear_tabla_contratos()
        layout.addWidget(self.tabla_flota_unidades)
        layout.addStretch()
        return widget

    def _crear_tabla_contratos(self):
        """Tabla de contratos de la flota y del cliente: sin barras propias (desplaza la caja), con copiar y doble clic."""
        tabla = QTableWidget(0, len(_COLUMNAS_TABLA_FLOTA))
        tabla.setHorizontalHeaderLabels([titulo for _, titulo in _COLUMNAS_TABLA_FLOTA])
        tabla.verticalHeader().setVisible(False)
        tabla.verticalHeader().setDefaultSectionSize(32)
        tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabla.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        tabla.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        tabla.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        QShortcut(QKeySequence.StandardKey.Copy, tabla, lambda: self._copiar_vins_tabla(tabla), context=Qt.ShortcutContext.WidgetShortcut)
        tabla.setShowGrid(False)
        tabla.setWordWrap(False)
        # El desplazamiento lo da la caja de la flota, no la tabla
        tabla.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        encabezado = tabla.horizontalHeader()
        encabezado.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        encabezado.setHighlightSections(False)
        # Solo VIN y Término se ajustan a su texto; el resto reparte el ancho para que la tabla nunca se salga
        encabezado.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        encabezado.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        encabezado.setSectionResizeMode(len(_COLUMNAS_TABLA_FLOTA) - 1, QHeaderView.ResizeMode.ResizeToContents)
        encabezado.setMinimumSectionSize(40)
        encabezado.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        tabla.setColumnWidth(1, 70)
        tabla.setTextElideMode(Qt.TextElideMode.ElideRight)
        tabla.setItemDelegate(_DelegadoChipsUnidades(tabla))
        tabla.setStyleSheet(f"""
            QTableWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; gridline-color: transparent; outline: none; color: {TEXT_PRIMARY}; }}
            QTableWidget::item {{ border-bottom: 1px solid #F1F5F9; padding: 2px 6px; font-size: 12px; }}
            QTableWidget::item:hover {{ background: {FILA_HOVER_TABLA}; }}
            QTableWidget::item:selected {{ background: {FILA_SELECCION_TABLA}; }}
            QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
            QMenu {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER}; padding: 4px; }}
            QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
            QMenu::item:selected {{ background-color: #E8F0FE; color: #1F6FEB; }}
            QHeaderView::section {{ background: #F1F5F9; color: {TEXT_SECONDARY}; border: none; padding: 8px 6px; font-size: 11px; font-weight: 700; }}
        """)
        tabla.cellDoubleClicked.connect(lambda fila, _columna: self._abrir_unidad_desde_tabla(tabla, fila))
        tabla.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tabla.customContextMenuRequested.connect(lambda pos: self._menu_tabla_unidades(tabla, pos))
        return tabla

    def _copiar_vins_tabla(self, tabla):
        filas = sorted({i.row() for i in tabla.selectedItems()})
        if filas:
            escribir_portapapeles("\n".join(tabla.item(f, 0).text() for f in filas))

    def _menu_tabla_unidades(self, tabla, pos):
        item = tabla.itemAt(pos)
        if item is None:
            return
        if not item.isSelected():
            tabla.clearSelection()
            tabla.selectRow(item.row())
        filas = sorted({i.row() for i in tabla.selectedItems()})
        vins = [tabla.item(f, 0).text() for f in filas]
        menu = crear_menu(tabla)
        texto_celda = item.text().strip()
        if len(vins) == 1 and item.column() != 0 and texto_celda:
            menu.accion(f"Copiar: '{texto_corto(texto_celda)}'").triggered.connect(lambda: escribir_portapapeles(texto_celda))
        menu.accion("Copiar VIN" if len(vins) == 1 else f"Copiar VIN ({len(vins)})", 'fa5s.barcode').triggered.connect(
            lambda: escribir_portapapeles("\n".join(vins)))
        if len(vins) == 1:
            menu.addSeparator()
            vin = vins[0]
            menu.accion("Ver en Comercial", 'fa5s.handshake').triggered.connect(lambda: self._ver_vin_en("Comercial", vin))
            menu.accion("Ver en Operaciones", 'fa5s.shipping-fast').triggered.connect(lambda: self._ver_vin_en("Operaciones", vin))
        menu.exec(tabla.viewport().mapToGlobal(pos))

    def _ver_vin_en(self, pantalla, vin):
        abrir = getattr(self.window(), 'abrir_vin_en', None)
        if abrir is not None:
            abrir(pantalla, vin)

    def _abrir_unidad_desde_tabla(self, tabla, fila):
        item = tabla.item(fila, 0)
        vin = item.text() if item is not None else ""
        if vin:
            self._abrir_unidad_en_pestana_unidades(vin)

    def _limpiar_filtros_flota_unidades(self):
        for boton in self._filtros_flota_unidades.values():
            boton.limpiar()
        self._pintar_unidades_flota()

    def _switch_flota_detalle_view(self, index):
        for i, btn in enumerate(self._flota_nav_buttons):
            btn.setChecked(i == index)
        # El alto de la pila lo da la página más alta (Unidades): las demás pestañas quedaban con un
        # desplazamiento enorme. Con alto "Ignored" solo cuenta la pestaña que se está viendo.
        for i in range(self.flota_detalle_stack.count()):
            pagina = self.flota_detalle_stack.widget(i)
            politica = pagina.sizePolicy()
            politica.setVerticalPolicy(QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored)
            pagina.setSizePolicy(politica)
        cambio = self.flota_detalle_stack.currentIndex() != index
        self.flota_detalle_stack.setCurrentIndex(index)
        if cambio:
            self._animar_esqueleto_derecha()
        self._contenedor_filtros_flota.setVisible(index == 1)
        self.flota_detalle_stack.updateGeometry()
        if index == 1:
            self._iniciar_unidades_flota()

    _valor_valido = staticmethod(general_services.valor_valido)

    _clientes_de_flota = staticmethod(general_services.clientes_de_flota)

    @staticmethod
    def _opciones_unicas(clientes, campo_valor, campo_detalle):
        """Opciones [(texto, valor, detalle)] para un chip de copia, sin valores repetidos ni vacíos."""
        opciones, vistos = [], set()
        for c in clientes:
            valor = c[campo_valor]
            if valor and valor not in vistos:
                vistos.add(valor)
                opciones.append((valor, valor, c[campo_detalle]))
        return opciones

    @_con_transicion_derecha
    def _show_flota_vacio(self):
        self._selected_flota_key = None
        self._df_flota_actual = pd.DataFrame()
        if self.left_stack.currentIndex() == 2:
            self.right_stack.setCurrentIndex(5)

    @_con_transicion_derecha
    def _show_flota_detalle(self, fila):
        clave = str(fila['Clave'])
        nombre = str(fila['Flota'])
        self._selected_flota_key = clave
        self._nombre_flota_actual = nombre
        if '_clave_flota' in self.df_comercial_raw.columns:
            df_u = self.df_comercial_raw[self.df_comercial_raw['_clave_flota'] == clave]
        else:
            df_u = pd.DataFrame()
        self._df_flota_actual = df_u
        total = len(df_u)
        clientes = self._clientes_de_flota(df_u)
        cdbs_flota = self._cdbs_flota_de_unidades(df_u)

        self.lbl_flota_title.set_texto(nombre)
        self.chip_flota_cliente.set_opciones("Copiar Cliente", self._opciones_unicas(clientes, 'nombre', 'rut'), "Cliente: -")
        self.chip_flota_rut.set_opciones("Copiar RUT", self._opciones_unicas(clientes, 'rut', 'nombre'), "RUT: -")
        self.chip_flota_cdb.set_opciones("Copiar CDB Comercial", self._opciones_unicas(clientes, 'cdb', 'nombre'), "CDB Comercial: -")
        self.chip_flota_copiar.set_opciones("Copiar Flota", [(nombre, nombre, "")], "Flota: -")
        self.chip_flota_cdb_flota.set_opciones(
            "Copiar CDB Flota",
            [(c, ", ".join(cdbs_flota), "") for c in cdbs_flota[:1]], "CDB Flota: -")

        cantidades = self._estados_de_flota(df_u)
        civ, sz = contar_civ_sz(df_u)
        self.bloque_estado_flota.actualizar(total, cantidades, civ, sz)

        self._render_info_flota(df_u, total, cdbs_flota, clientes)
        self._render_clientes_flota(clientes)
        self._render_unidades_flota(df_u)
        self._populate_contactos_flota(df_u)
        # Al cambiar de flota se mantiene la pestaña que se estaba viendo
        self._switch_flota_detalle_view(self.flota_detalle_stack.currentIndex())
        self.btn_flota_unidades.setText(f"Unidades ({total})")
        self.btn_exportar_flota.setEnabled(total > 0)
        self.right_stack.setCurrentIndex(6)
        self.flota_detalle_scroll.verticalScrollBar().setValue(0)

    _estados_de_flota = staticmethod(general_services.estados_de_flota)

    def _render_info_flota(self, df_u, total, cdbs_flota, clientes):
        while self.info_flota_layout.count():
            item = self.info_flota_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        ejecutivos = self._valor_valido(df_u[COL_EJECUTIVO]) if COL_EJECUTIVO in df_u.columns else []
        industrias = self._valor_valido(df_u[COL_INDUSTRIA]) if COL_INDUSTRIA in df_u.columns else []
        celdas = []
        if ejecutivos:
            celdas.append(("Ejecutivo", ejecutivos[0], False))
        if industrias:
            celdas.append(("Industria", industrias[0], False))
        celdas.append(("Total de unidades", str(total), False))
        celdas.append(("CDB Flota", ", ".join(cdbs_flota) if cdbs_flota else "-", False))
        fila, columna = 0, 0
        for etiqueta, valor, ancho_completo in celdas:
            celda = self._create_info_celda(etiqueta, valor, False, tooltip=valor, elidir=True)
            if ancho_completo:
                if columna:
                    fila, columna = fila + 1, 0
                self.info_flota_layout.addWidget(celda, fila, 0, 1, 2)
                fila += 1
            else:
                self.info_flota_layout.addWidget(celda, fila, columna)
                columna += 1
                if columna == 2:
                    fila, columna = fila + 1, 0

    def _render_clientes_flota(self, clientes):
        while self.flota_clientes_lista.count():
            item = self.flota_clientes_lista.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.lbl_flota_clientes_titulo.setText(f"CLIENTES DE LA FLOTA ({len(clientes)})")
        self.lbl_flota_clientes_resumen.setVisible(not clientes)
        if not clientes:
            self.lbl_flota_clientes_resumen.setText("Esta flota no tiene clientes informados.")
            return
        for c in clientes:
            fila = _FilaClienteFlota(c['nombre'], c['rut'], c['unidades'], c['cdb'])
            fila.abrir.connect(lambda nombre=c['nombre'], rut=c['rut']: self._abrir_cliente_desde_unidad(nombre, rut))
            self.flota_clientes_lista.addWidget(fila)

    def _preparar_df_contratos(self, df_u):
        """Contratos de un conjunto de unidades (de una flota o de un cliente) listos para la tabla, ordenados por VIN."""
        df_base = self.df_unidades_base
        if df_u.empty or df_base.empty or COL_VIN not in df_u.columns or 'VIN' not in df_base.columns:
            return pd.DataFrame()
        vins = set(df_u[COL_VIN].astype(str).str.strip().str.upper())
        df_f = df_base[df_base['VIN'].astype(str).str.strip().str.upper().isin(vins)].sort_values('VIN')
        if COL_MODELO in df_u.columns:
            modelos = (df_u.assign(_vin=df_u[COL_VIN].astype(str).str.strip().str.upper())
                       .drop_duplicates('_vin').set_index('_vin')[COL_MODELO])
            return df_f.assign(Modelo=df_f['VIN'].astype(str).str.strip().str.upper().map(modelos).fillna(''))
        return df_f.assign(Modelo='')

    def _con_unidades_sin_flota_pedidas(self, df_u):
        """Al llegar desde el Dashboard, las unidades pedidas que no tienen Flota VC (por ejemplo sin servicio) se
        suman a la tabla de la flota de su mismo cliente, para ver todas las unidades del gráfico."""
        pedidos = self.__dict__.get('_filtro_vins_flotas')
        df = self.df_comercial_raw
        if (not pedidos or df_u.empty or df.empty or '_clave_cliente' not in df.columns
                or '_clave_flota' not in df.columns or '_clave_cliente' not in df_u.columns):
            return df_u
        vins = df[COL_VIN].astype(str).str.strip().str.upper()
        clientes = {c for c in df_u['_clave_cliente'].astype(str) if c.strip() not in ('', 'RS:', 'nan')}
        if not clientes:
            return df_u
        extra = df[vins.isin(pedidos) & (df['_clave_flota'].astype(str).str.strip() == '')
                   & df['_clave_cliente'].astype(str).isin(clientes)]
        return pd.concat([df_u, extra]) if not extra.empty else df_u

    def _render_unidades_flota(self, df_u):
        """Deja listos los contratos de la flota; la tabla se pinta al abrir la pestaña Unidades."""
        self._flota_unidades_construidas = False
        self._flota_df_unidades = self._preparar_df_contratos(self._con_unidades_sin_flota_pedidas(df_u))
        for boton in self._filtros_flota_unidades.values():
            boton.set_valores([])
            boton.limpiar()
        if self.flota_detalle_stack.currentIndex() == 1:
            self._iniciar_unidades_flota()

    def _iniciar_unidades_flota(self):
        if self.__dict__.get('_flota_unidades_construidas', True):
            return
        self._flota_unidades_construidas = True
        self._poblar_filtros_flota_unidades()
        self._pintar_unidades_flota()

    def _poblar_filtros_flota_unidades(self):
        self._poblar_filtros_tabla(self._flota_df_unidades, self._filtros_flota_unidades)

    @staticmethod
    def _poblar_filtros_tabla(base, filtros):
        """Las opciones de cada filtro salen de los contratos que cumplen los demás filtros."""
        mascaras = {}
        for columna, boton in filtros.items():
            claves = boton.seleccion()
            if claves is not None and columna in base.columns:
                mascaras[columna] = base[columna].astype(str).map(_clave_flota_texto).isin(claves)
        for columna, boton in filtros.items():
            if columna not in base.columns:
                boton.set_valores([])
                continue
            otras = [m for c, m in mascaras.items() if c != columna]
            sub = base[pd.concat(otras, axis=1).all(axis=1)] if otras else base
            boton.set_valores(FiltroValoresBoton.valores_distintos(sub[columna]))

    def _pintar_unidades_flota(self):
        self._pintar_tabla_contratos(
            self.tabla_flota_unidades, self.lbl_flota_unidades_resumen, self._flota_df_unidades,
            self._filtros_flota_unidades, getattr(self, '_vins_busqueda_flota', None),
            "Esta flota no tiene unidades registradas.")

    def _pintar_tabla_contratos(self, tabla, lbl_resumen, base, filtros, buscados, texto_vacio):
        buscados = buscados or set()
        if base.empty:
            tabla.setRowCount(0)
            tabla.setFixedHeight(tabla.horizontalHeader().height() + 2)
            lbl_resumen.setText(texto_vacio)
            return
        self._poblar_filtros_tabla(base, filtros)
        df_f = self._aplicar_filtros_unidades(base, {columna: boton.seleccion() for columna, boton in filtros.items()})
        if buscados and not df_f.empty:
            es_buscado = df_f['VIN'].astype(str).str.strip().str.upper().isin(buscados)
            df_f = pd.concat([df_f[es_buscado], df_f[~es_buscado]])
            n_buscados = int(es_buscado.sum())
        else:
            n_buscados = 0
        n = len(df_f)
        lbl_resumen.setText(
            f"{n} de {len(base)} contratos · clic selecciona, doble clic abre en Contratos"
            if n != len(base) else f"{n} {'contrato' if n == 1 else 'contratos'} · clic selecciona, doble clic abre en Contratos")
        if n_buscados:
            # Llegando desde el Dashboard o buscando VIN, la flota se ve entera: los pedidos van primero y seleccionados
            lbl_resumen.setText(f"{n_buscados} {'seleccionado' if n_buscados == 1 else 'seleccionados'} de {n} contratos · "
                                + lbl_resumen.text().split(' · ', 1)[-1])
        tabla.setUpdatesEnabled(False)
        # Con columnas "ajustar al contenido" cada celda nueva recalcula el ancho sobre todas las filas: con miles de
        # unidades eso tardaba decenas de segundos. Se fijan mientras se llena y se ajustan una sola vez al final.
        encabezado = tabla.horizontalHeader()
        columnas_ajustables = [c for c in range(tabla.columnCount())
                               if encabezado.sectionResizeMode(c) == QHeaderView.ResizeMode.ResizeToContents]
        for c in columnas_ajustables:
            encabezado.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
        tabla.setRowCount(n)
        for i, (_, fila) in enumerate(df_f.iterrows()):
            termino, vencido = _formatear_fecha_contrato(fila.get('Término Contrato', ''), True)
            valores = [str(fila.get('VIN', '')), str(fila.get('Modelo', '')), str(fila.get('Tipo de Servicio', '')),
                       str(fila.get('Estado Comercial', '')), str(fila.get('Estado Activación', '')),
                       str(fila.get('Forma de Contrato', '')), str(fila.get('Tipo de Facturación', '')), termino]
            for j, valor in enumerate(valores):
                valor = '' if valor.strip() in ('-', 'nan', 'None') else valor
                item = QTableWidgetItem(_resumir_celda_flota(j, valor))
                if j > 0 and item.text() != valor:
                    item.setToolTip(valor)
                if j == 0:
                    item.setFont(QFont(item.font().family(), item.font().pointSize(), QFont.Weight.Bold))
                    item.setToolTip(f"VIN {valor}" + (f"  •  Chasis {fila.get('CHASIS')}" if _flota_valida(fila.get('CHASIS', '')) else ""))
                elif j in (3, 4):
                    fondo_chip, texto_chip = (_color_estado_comercial if j == 3 else _color_estado_activacion)(valor)
                    if valor:
                        item.setBackground(QColor(fondo_chip))
                    item.setForeground(QColor(texto_chip))
                elif j == 7 and vencido:
                    item.setForeground(QColor('#C41919'))
                    item.setFont(QFont(item.font().family(), item.font().pointSize(), QFont.Weight.Bold))
                tabla.setItem(i, j, item)
        for c in columnas_ajustables:
            ancho = max(tabla.sizeHintForColumn(c), encabezado.sectionSizeHint(c))
            encabezado.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
            if n > 400:
                encabezado.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
                tabla.setColumnWidth(c, ancho)
        tabla.setFixedHeight(tabla.horizontalHeader().height() + n * tabla.verticalHeader().defaultSectionSize() + 4)
        tabla.clearSelection()
        if n_buscados:
            # Los VIN buscados quedan seleccionados: se pueden copiar o abrir de inmediato
            modelo, seleccion = tabla.model(), tabla.selectionModel()
            for i in range(n_buscados):
                seleccion.select(modelo.index(i, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        tabla.setUpdatesEnabled(True)

    def _exportar_excel_flota(self):
        """Excel con toda la flota (resumen y detalle), igual que el de Comercial y con su misma tarjeta de avance."""
        df = self._df_flota_actual
        from src.ui.administracion.estilo import exportar_excel
        if df is None or df.empty:
            exportar_excel(self, pd.DataFrame(), "Flota")
            return
        # Solo las columnas que se comparten con el cliente; las que no traen ningún dato las omite el exportador
        def _clave(texto):
            return unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode().strip().upper()
        existentes = {_clave(c): c for c in df.columns if not str(c).startswith('_')}
        columnas = [existentes[_clave(c)] for c in _COLUMNAS_EXPORT_FLOTA if _clave(c) in existentes]
        nombre = re.sub(r'[^A-Za-z0-9]+', '_', unicodedata.normalize('NFKD', self._nombre_flota_actual)
                        .encode('ascii', 'ignore').decode()).strip('_') or 'Flota'
        columna_estado = existentes.get(_clave(COL_ESTADO_COMERCIAL))
        rojo = ("FDE2E1", "B91C1C")
        resaltado = []
        if columna_estado:
            resaltado.append((columna_estado, {v: rojo for v in ('Baja', 'Baja Solicitada', 'BAJA', 'BAJA SOLICITADA')}))
        # CM vencidos sin ningún dato del 3PC: van a Oportunidades CM, se marcan en ámbar
        datos = df[columnas].copy()
        vacios_3pc = cm_bajas_service.mascara_datos_3pc_vacios(df)
        if vacios_3pc.any():
            datos['REVISAR'] = vacios_3pc.map({True: "Datos vacíos en 3PC", False: ""})
            resaltado.append(('REVISAR', {"Datos vacíos en 3PC": ("FFEFC2", "B45309")}))
        cdbs = self._cdbs_flota_de_unidades(df)
        titulo = f"Flota {self._nombre_flota_actual}" + (f" · CDB Flota {', '.join(cdbs)}" if cdbs else "")
        exportar_excel(self, datos, f"Flota_{nombre}", depurar=True, resaltado=resaltado or None, titulo=titulo)
