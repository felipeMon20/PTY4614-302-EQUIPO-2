"""Lista de unidades de General: orden, paginación y tarjetas."""
from src.theme.colors import TEXT_MUTED, TEXT_SECONDARY
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QScrollArea, QGridLayout, QSizePolicy, QCheckBox
from PyQt6.QtCore import Qt
from src.theme.theme_manager import ThemeManager
from src.ui.general.base import (
    FiltroRangoFechaBoton,
    FiltroValoresBoton,
    GeneralUnidadCard,
    NUM_COLUMNAS_LISTA,
    QSS_TARJETAS_UNIDAD,
    TEXTO_SOBRE_AZUL,
    _FILTROS_UNIDADES,
    _GrillaTarjetas,
    _GrupoControles,
    _boton_sobre_azul,
)


class _ListaUnidadesGeneralMixin:
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
        advanced_layout_unidades.setContentsMargins(8, 6, 8, 6)
        advanced_layout_unidades.setSpacing(8)

        # Filtros por columna (09-10-2026): traen las unidades que cumplan los
        # valores marcados; cada lista sale de los datos, sin repetidos ni '-'.
        # En tres columnas (28-10-2026): la caja izquierda es angosta y en una sola fila los títulos se cortaban.
        self._filtros_unidades = {}
        grilla = QGridLayout()
        grilla.setHorizontalSpacing(6)
        grilla.setVerticalSpacing(6)
        columnas_filtros = 3
        for i, (columna, titulo) in enumerate(_FILTROS_UNIDADES):
            boton = FiltroValoresBoton(titulo)
            boton.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            boton.cambiado.connect(self.filter_unidades)
            self._filtros_unidades[columna] = boton
            boton.setMinimumWidth(0)
            grilla.addWidget(boton, i // columnas_filtros, i % columnas_filtros)
        self._filtro_fecha_baja = FiltroRangoFechaBoton("Fecha de baja")
        self._filtro_fecha_baja.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._filtro_fecha_baja.setMinimumWidth(0)
        self._filtro_fecha_baja.cambiado.connect(self.filter_unidades)
        grilla.addWidget(self._filtro_fecha_baja, (len(_FILTROS_UNIDADES) + columnas_filtros - 1) // columnas_filtros, 0, 1, columnas_filtros)
        for c in range(columnas_filtros):
            grilla.setColumnStretch(c, 1)
        advanced_layout_unidades.addLayout(grilla, 1)

        acciones = QFrame()
        acciones.setStyleSheet(
            f"QFrame#accionesFiltros {{ background: #F1F4F9; border: 1px solid #E3E8F0; border-radius: 14px; }}")
        acciones.setObjectName("accionesFiltros")
        acciones_layout = QHBoxLayout(acciones)
        acciones_layout.setContentsMargins(4, 4, 4, 4)
        acciones_layout.setSpacing(2)

        self.btn_limpiar_filtros_unidades = QPushButton()
        self.btn_limpiar_filtros_unidades.setIcon(ThemeManager.icon('fa5s.eraser', color=TEXT_SECONDARY))
        self.btn_limpiar_filtros_unidades.setToolTip("Limpiar filtros")
        self.btn_limpiar_filtros_unidades.setFixedSize(26, 26)
        self.btn_limpiar_filtros_unidades.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_limpiar_filtros_unidades.setStyleSheet(
            "QPushButton { border: none; border-radius: 13px; background: transparent; }"
            "QPushButton:hover { background: #E3E8F0; }")
        self.btn_limpiar_filtros_unidades.clicked.connect(self._limpiar_filtros_unidades)

        btn_close_filtro_unidades = QPushButton()
        btn_close_filtro_unidades.setIcon(ThemeManager.icon('fa5s.chevron-up', color=TEXT_SECONDARY))
        btn_close_filtro_unidades.setToolTip("Ocultar filtros")
        btn_close_filtro_unidades.setFixedSize(26, 26)
        btn_close_filtro_unidades.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close_filtro_unidades.setStyleSheet(
            "QPushButton { border: none; border-radius: 13px; background: transparent; }"
            "QPushButton:hover { background: #E3E8F0; }")
        btn_close_filtro_unidades.clicked.connect(lambda: self.btn_filtro_unidades.setChecked(False))

        acciones_layout.addWidget(self.btn_limpiar_filtros_unidades)
        acciones_layout.addWidget(btn_close_filtro_unidades)
        advanced_layout_unidades.addWidget(acciones, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self.advanced_filters_frame_unidades)

        pag_top, self._lbl_pagina_unidades_top, self._btn_pagina_ant_unidades_top, self._btn_pagina_sig_unidades_top = \
            self._crear_controles_paginacion(self._pagina_anterior_unidades, self._pagina_siguiente_unidades)

        pag_top.setParent(widget)
        pag_top.hide()
        # Van en la barra azul de arriba, a la derecha y en la línea de las pestañas;
        # solo se ven en Contratos (ver _switch_left_view)
        self._controles_unidades = top_row = _GrupoControles(self._barra_nav_layout)
        self._extras_unidades = _GrupoControles(self._fila_subtitulo_layout)
        self._lbl_total_unidades = QLabel("")
        self._lbl_total_unidades.setStyleSheet(
            f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; font-weight: bold; background: transparent; padding-right: 4px;")
        self._extras_unidades.addWidget(self._lbl_total_unidades)
        self.chk_ocultar_sin_vc = QCheckBox("Ocultar sin VC")
        self.chk_ocultar_sin_vc.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_ocultar_sin_vc.setToolTip("Oculta los contratos sin Volvo Connect (la etiqueta gris SIN VC)")
        self.chk_ocultar_sin_vc.setStyleSheet(self.chk_solo_avisos_flota.styleSheet())
        self.chk_ocultar_sin_vc.toggled.connect(lambda _c: (self._animar_carga_breve(solo_izquierda=True), self.filter_unidades()))
        self._extras_unidades.addWidget(self.chk_ocultar_sin_vc)
        self.btn_filtro_vins = QPushButton()
        self.btn_filtro_vins.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filtro_vins.setToolTip("Quitar este filtro y volver a ver todos los contratos")
        _boton_sobre_azul(self.btn_filtro_vins)
        self.btn_filtro_vins.clicked.connect(self._quitar_filtro_vins)
        self._extras_unidades.addWidget(self.btn_filtro_vins)
        self.btn_filtro_vins.hide()
        for boton in (self._crear_selector_tamano_pagina(self._on_cambiar_tamano_pagina_unidades),
                      self._crear_boton_ordenar_unidades()):
            _boton_sobre_azul(boton)
            top_row.addWidget(boton)
        self._controles_unidades.hide()
        self._extras_unidades.hide()

        self.unidades_scroll = QScrollArea()
        self.unidades_scroll.setWidgetResizable(True)
        self.unidades_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.unidades_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.unidades_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.unidades_scroll.viewport().setStyleSheet("background: transparent;")

        unidades_container = QWidget()
        unidades_container.setStyleSheet(QSS_TARJETAS_UNIDAD)
        self.unidades_layout = _GrillaTarjetas(NUM_COLUMNAS_LISTA, unidades_container)
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
        layout.vaciar()
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
            lbl_vacio = QLabel("No hay contratos que coincidan con la búsqueda/filtros.")
            lbl_vacio.setWordWrap(True)
            lbl_vacio.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 12px;")
            layout.addWidget(lbl_vacio, 0, 0, 1, layout.columnas)
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
