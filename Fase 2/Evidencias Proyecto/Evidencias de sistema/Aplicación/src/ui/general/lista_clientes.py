"""Lista de clientes de General: orden, paginación y armado de tarjetas por tandas."""
from src.theme.colors import TEXT_MUTED
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QFrame, QLabel, QScrollArea, QCheckBox
from PyQt6.QtCore import Qt, QTimer
from src.services import comercial_services
from src.ui.general.base import (
    GeneralClienteCard,
    NUM_COLUMNAS_LISTA,
    QSS_TARJETAS_CLIENTE,
    TEXTO_SOBRE_AZUL,
    _GrillaTarjetas,
    _GrupoControles,
    _boton_sobre_azul,
)


class _ListaClientesGeneralMixin:
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
        # Van en la barra azul de arriba, a la derecha y en la línea de las pestañas;
        # solo se ven en Cliente (ver _switch_left_view)
        self._controles_cliente = top_row = _GrupoControles(self._barra_nav_layout)
        self._extras_cliente = _GrupoControles(self._fila_subtitulo_layout)
        self.chk_solo_avisos_flota = QCheckBox("Solo con aviso de flotas")
        self.chk_solo_avisos_flota.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_solo_avisos_flota.setToolTip("Muestra solo los clientes con flotas incoherentes (el ícono amarillo de la tarjeta)")
        self.chk_solo_avisos_flota.setStyleSheet(
            f"QCheckBox {{ color: {TEXTO_SOBRE_AZUL}; font-size: 11px; font-weight: bold; spacing: 6px; "
            "background: transparent; padding-right: 8px; } "
            "QCheckBox::indicator { width: 14px; height: 14px; border: 1.5px solid rgba(255,255,255,150); "
            "border-radius: 4px; background: transparent; } "
            "QCheckBox::indicator:checked { background: #6AA6FF; border: 1.5px solid #6AA6FF; }")
        self.chk_solo_avisos_flota.toggled.connect(lambda _c: (self._animar_carga_breve(solo_izquierda=True), self.filter_clientes()))
        self._extras_cliente.addWidget(self.chk_solo_avisos_flota)
        selector_pagina = self._crear_selector_tamano_pagina(self._on_cambiar_tamano_pagina_clientes)
        boton_orden = self._crear_boton_ordenar(self._on_cambiar_orden_clientes, self._on_cambiar_orden_clientes_unidades,
                                                self._on_cambiar_orden_clientes_flotas)
        for boton in (selector_pagina, boton_orden):
            _boton_sobre_azul(boton)
            top_row.addWidget(boton)

        self.clientes_scroll = QScrollArea()
        self.clientes_scroll.setWidgetResizable(True)
        self.clientes_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.clientes_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.clientes_scroll.viewport().setStyleSheet("background: transparent;")

        clientes_container = QWidget()
        clientes_container.setStyleSheet(QSS_TARJETAS_CLIENTE)
        self.clientes_layout = _GrillaTarjetas(NUM_COLUMNAS_LISTA, clientes_container)
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
        layout.vaciar()
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
            layout.addWidget(lbl_vacio, 0, 0, 1, layout.columnas)
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
    _PRIMERA_TANDA_TARJETAS = 42
    _TANDA_TARJETAS = 42

    def _cancelar_tandas(self, lista):
        generaciones = self.__dict__.setdefault('_generacion_tandas', {})
        generaciones[lista] = generaciones.get(lista, 0) + 1
        self.__dict__.setdefault('_tanda_pendiente', {}).pop(lista, None)
        return generaciones

    def _scroll_de_lista(self, lista):
        return {'clientes': 'clientes_scroll', 'unidades': 'unidades_scroll', 'flotas': 'flotas_scroll',
                'unidades_detalle': 'unidades_detalle_scroll'}.get(lista)

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
