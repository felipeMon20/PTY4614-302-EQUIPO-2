"""Controles de orden, paginación y selección sincronizada de General."""
from src.theme.colors import DANGER, TEXT_PRIMARY, TEXT_SECONDARY
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from src.theme.theme_manager import ThemeManager
from src.ui.general.base import (
    AZUL,
    _OPCIONES_TAMANO_PAGINA,
    _boton_minimo,
)


class _ControlesGeneralMixin:
    def _toggle_filtro_unidades(self, checked):
        self._animar_filtros_unidades(checked)

    def _animar_filtros_unidades(self, expandir):
        marco = self.advanced_filters_frame_unidades
        anim = self.__dict__.get('_anim_filtros_unidades')
        if anim is None:
            anim = QPropertyAnimation(marco, b"maximumHeight", self)
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._anim_filtros_unidades = anim
        anim.stop()
        try:
            anim.finished.disconnect()
        except TypeError:
            pass
        if expandir:
            marco.setMaximumHeight(0)
            marco.show()
            destino = marco.sizeHint().height()
            anim.setStartValue(0)
            anim.setEndValue(destino)
            anim.finished.connect(lambda: marco.setMaximumHeight(16777215))
        else:
            anim.setStartValue(marco.height())
            anim.setEndValue(0)
            anim.finished.connect(marco.hide)
        anim.start()

    # ==========================================
    # FILTROS DE "UNIDADES" (caja izquierda): ver FiltroValoresBoton.
    # ==========================================
    def _crear_boton_ordenar(self, on_change, on_change_unidades=None, on_change_flotas=None):
        """Botón único 'Ordenar' (menú A-Z/Z-A, y opcionalmente Más/Menos
        unidades) para las tarjetas de Cliente/Flota/Unidades -- reemplaza
        el clic en encabezado de columna que tenían las tablas anteriores
        (VolvoTableWidget.apply_sort), a pedido explícito (20-09-2026: 'todo
        esto en un solo boton'). on_change(is_asc) se invoca al elegir A-Z/
        Z-A. on_change_unidades(is_asc), si se entrega, agrega las opciones
        'Más unidades'/'Menos unidades' (24-09-2026, a pedido explícito) --
        no aplica a la pestaña Unidades, que es una tabla por VIN sin
        conteo que ordenar."""
        from src.ui.compartido.comercial_estilo import BotonOpcionesTarjeta
        opciones = [('asc', "A-Z (ascendente)"), ('desc', "Z-A (descendente)")]
        if on_change_unidades is not None:
            opciones += [('mas', "Más unidades"), ('menos', "Menos unidades")]
        if on_change_flotas is not None:
            opciones += [('flotas_mas', "Más flotas"), ('flotas_menos', "Menos flotas")]

        acciones = {
            'asc': lambda: on_change(True),
            'desc': lambda: on_change(False),
            'mas': lambda: on_change_unidades(False),
            'menos': lambda: on_change_unidades(True),
            'flotas_mas': lambda: on_change_flotas(False),
            'flotas_menos': lambda: on_change_flotas(True),
        }
        btn = BotonOpcionesTarjeta("Ordenar", "Ordenar", opciones, valor='asc',
                                   al_elegir=lambda clave: acciones[clave]())
        btn.setIcon(ThemeManager.icon('fa5s.sort-alpha-down', color=AZUL))
        _boton_minimo(btn)
        return btn

    def _crear_boton_ordenar_unidades(self):
        """Botón 'Ordenar' de Unidades: por estado comercial o por estado de
        activación, ascendente o descendente."""
        from src.ui.compartido.comercial_estilo import BotonOpcionesTarjeta
        opciones = [
            ('Estado Comercial:asc', "Estado comercial (A-Z)"), ('Estado Comercial:desc', "Estado comercial (Z-A)"),
            ('Estado Activación:asc', "Estado activación (A-Z)"), ('Estado Activación:desc', "Estado activación (Z-A)"),
        ]
        btn = BotonOpcionesTarjeta("Ordenar por", "Ordenar", opciones, valor=None,
                                   al_elegir=self._on_cambiar_orden_unidades)
        btn.setIcon(ThemeManager.icon('fa5s.sort-alpha-down', color=AZUL))
        _boton_minimo(btn)
        return btn

    def _crear_controles_paginacion(self, on_anterior, on_siguiente):
        """Fila "‹ Anterior | Página X de Y | Siguiente ›" (ver
        _TARJETAS_POR_PAGINA), reutilizada arriba y abajo de cada lista de
        tarjetas (Cliente/Flota/Unidades) a pedido explícito (20-09-2026).
        Devuelve (widget, lbl_pagina, btn_anterior, btn_siguiente) para que
        el llamador guarde las referencias y las actualice en cada repintado
        de página (ver _actualizar_controles_paginacion)."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        btn_anterior = QPushButton("‹ Anterior")
        btn_anterior.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_minimo(btn_anterior)
        btn_anterior.clicked.connect(on_anterior)

        lbl_pagina = QLabel("Página 1 de 1")
        lbl_pagina.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_pagina.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: bold;")

        btn_siguiente = QPushButton("Siguiente ›")
        btn_siguiente.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_minimo(btn_siguiente)
        btn_siguiente.clicked.connect(on_siguiente)

        layout.addWidget(btn_anterior)
        layout.addWidget(lbl_pagina, 1)
        layout.addWidget(btn_siguiente)
        return widget, lbl_pagina, btn_anterior, btn_siguiente

    def _crear_selector_tamano_pagina(self, on_change):
        """Combo "Mostrar: 200/500/1000" (ver _OPCIONES_TAMANO_PAGINA) para
        elegir cuántas tarjetas trae cada página, a pedido explícito
        (20-09-2026). on_change(nuevo_tamano) se llama al elegir una
        opción."""
        from src.ui.compartido.comercial_estilo import BotonOpcionesTarjeta
        boton = BotonOpcionesTarjeta(
            "Filas por página",
            opciones=[(o, f"Mostrar {o}") for o in _OPCIONES_TAMANO_PAGINA],
            valor=_OPCIONES_TAMANO_PAGINA[0], mostrar_valor=True, al_elegir=on_change)
        _boton_minimo(boton)
        return boton

    @staticmethod
    def _actualizar_controles_paginacion(pagina_actual, total_paginas, *pares_lbl_botones):
        """Sincroniza el texto "Página X de Y" y el habilitado de Anterior/
        Siguiente en los controles de arriba Y abajo de una misma lista
        (cada elemento de *pares_lbl_botones es (lbl_pagina, btn_anterior,
        btn_siguiente))."""
        texto = f"Página {pagina_actual + 1} de {total_paginas}"
        for lbl_pagina, btn_anterior, btn_siguiente in pares_lbl_botones:
            lbl_pagina.setText(texto)
            btn_anterior.setEnabled(pagina_actual > 0)
            btn_siguiente.setEnabled(pagina_actual < total_paginas - 1)

    # ==========================================
    # SELECCIÓN DE CLIENTE -> CAJA DERECHA
    # (los clics de tarjeta llaman directamente _on_cliente_card_clicked /
    # _on_flota_card_clicked / _on_unidad_card_clicked, definidos junto a
    # cada _build_*_view/_render_*_cards; acá solo quedan las funciones de
    # sincronización tras un refiltrado, ver _sincronizar_seleccion_vin /
    # _sincronizar_seleccion_cliente_flota más abajo)
    # ==========================================

    def _sincronizar_seleccion_vin(self):
        """Se llama tras recalcular self._df_unidades_visible (filtro/
        búsqueda/orden) para mantener la ficha/historial de la caja derecha
        sincronizada con el VIN seleccionado, sin reconstruir tarjetas (eso
        ya lo hace _render_unidades_cards, que resalta la tarjeta si el VIN
        sigue presente). Si el VIN ya no está en la lista filtrada, limpia
        la selección y vacía la caja derecha -- mismo comportamiento que la
        tabla anterior (_restaurar_seleccion_vin)."""
        if self._vin_seleccionado and 'VIN' in self._df_unidades_visible.columns:
            vin_upper = self._vin_seleccionado.strip().upper()
            if (self._df_unidades_visible['VIN'].astype(str).str.strip().str.upper() == vin_upper).any():
                self._show_vin_detalle(self._vin_seleccionado)
                return

        self._vin_seleccionado = None
        self._show_vin_vacio()

    def _resolver_texto_flota_vc_sin_cliente(self, flota_vc):
        """Caja derecha, fila de Flota sin cliente asociado: qué texto
        mostrar para el dato de Flota VC. Devuelve None cuando tampoco hay
        Flota VC (la UI lo traduce en el mensaje "No se encontró
        información" en rojo, ver _show_flota_sin_cliente). Función pura
        (no usa self.*)."""
        flota_vc_str = str(flota_vc).strip() if flota_vc is not None else ""
        if flota_vc_str.lower() in ('', 'nan', 'none', '<na>'):
            return None
        return flota_vc_str

    def _show_flota_sin_cliente(self, flota_vc):
        self._selected_cdb = None
        self._selected_cdbs_flota = []
        self._selected_cliente_key = None
        texto = self._resolver_texto_flota_vc_sin_cliente(flota_vc)
        if texto is None:
            self.lbl_flota_sin_cliente_valor.setText("No se encontró información")
            self.lbl_flota_sin_cliente_valor.setStyleSheet(f"color: {DANGER}; font-size: 11px; font-weight: bold;")
        else:
            self.lbl_flota_sin_cliente_valor.setText(texto)
            self.lbl_flota_sin_cliente_valor.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px; font-weight: bold;")
        self.right_stack.setCurrentIndex(2)

    def _buscar_cliente_por_clave(self, clave):
        """Fila de df_clientes_base de una clave de cliente, o None."""
        if not clave or self.df_clientes_base.empty or 'Clave' not in self.df_clientes_base.columns:
            return None
        coincidencias = self.df_clientes_base[self.df_clientes_base['Clave'].astype(str) == str(clave)]
        return None if coincidencias.empty else coincidencias.iloc[0]

    def _sincronizar_seleccion_cliente(self, df_visible):
        """Se llama tras recalcular _df_clientes_visible (filtro/búsqueda/
        orden) para mantener la caja derecha sincronizada con el cliente
        que ya se estaba mostrando (self._selected_cdb), sin depender de
        una tabla -- mismo rol que cumplía _restaurar_seleccion_cliente_
        flota con table.selectRow() antes de pasar a tarjetas. El resaltado
        visual de la tarjeta ya lo resuelve _render_clientes_cards al
        reconstruir la lista.

        Solo actúa si la pestaña izquierda activa es Cliente (índice 0); si
        el usuario está viendo otra pestaña, no la toca -- evita que una
        búsqueda global le borre el contexto que está viendo."""
        if self.left_stack.currentIndex() != 0:
            return

        if self._selected_cliente_key and 'Clave' in df_visible.columns:
            posiciones = (df_visible['Clave'].astype(str) == self._selected_cliente_key).to_numpy().nonzero()[0]
            if len(posiciones):
                self._show_cliente_detalle(df_visible.iloc[int(posiciones[0])])
                return

        self._show_cliente_vacio()
