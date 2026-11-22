"""Panel flotante de acciones rápidas y tarjetas KPI de la bandeja de Comercial."""
from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QFrame, QLabel
from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QColor
from src.ui.compartido import comercial_estilo as estilo_com
from src.theme.colors import DANGER, PRIMARY, SUCCESS, WARNING
from src.theme.theme_manager import ThemeManager


class _PanelKpiComercialMixin:
    def _geometria_panel_acciones(self, abierto):
        # Mismo borde derecho e inferior que la bandeja; arriba, desde el tope del módulo
        tab = self.new_ui_tab
        margen = 15
        esquina = tab.mapTo(self, QPoint(tab.width(), tab.height()))
        ancho = max(320, min(400, int(tab.width() * 0.3)))
        return estilo_com.geometria_panel_flotante(self, abierto, derecha=esquina.x(), abajo=esquina.y(), ancho=ancho, margen=margen)

    def _ocultar_panel_acciones_al_instante(self):
        if getattr(self, '_panel_acciones', None) is None:
            return
        self._anim_panel_acciones.stop()
        self._panel_acciones_abierto = False
        combo_periodo = getattr(self, 'combo_periodo_interno', None)
        if combo_periodo is not None:
            combo_periodo.set_compacto(True)
        self._panel_acciones.hide()
        self._ajustar_barra_bajo_panel()
        self._ajustar_tabla_bajo_panel()

    def _mostrar_panel_acciones(self, mostrar):
        panel = getattr(self, '_panel_acciones', None)
        if panel is None:
            return
        mostrar = mostrar and self.tabs.currentWidget() is self.new_ui_tab
        if mostrar == self._panel_acciones_abierto:
            return
        self._panel_acciones_abierto = mostrar
        combo_periodo = getattr(self, 'combo_periodo_interno', None)
        if combo_periodo is not None:
            combo_periodo.set_compacto(True)
        anim = self._anim_panel_acciones
        anim.stop()
        if mostrar:
            estilo_com.montar_panel_sobre_encabezado(self, panel, lambda: self._panel_acciones_abierto)
            if not panel.isVisible():
                panel.setGeometry(self._geometria_panel_acciones(False))
                panel.show()
            panel.raise_()
            estilo_com.fijar_sombra_panel(panel, True)
        anim.setStartValue(panel.pos())
        anim.setEndValue(self._geometria_panel_acciones(mostrar).topLeft())
        anim.start()

    def _on_anim_panel_acciones_terminada(self):
        if not self._panel_acciones_abierto:
            self._panel_acciones.hide()
            estilo_com.fijar_sombra_panel(self._panel_acciones, False)
        self._ajustar_barra_bajo_panel()
        self._ajustar_tabla_bajo_panel()

    def _ajustar_barra_bajo_panel(self):
        """Corre los botones de la barra de la bandeja hacia el espacio libre
        de la izquierda para que el panel flotante no los tape."""
        barra, panel = self._barra_bandeja, self._panel_acciones
        solape = 0
        if panel.isVisible():
            borde_derecho = barra.mapTo(panel.parentWidget(), QPoint(barra.width(), 0)).x()
            solape = max(0, borde_derecho - panel.x() + 4)
        barra.layout().setContentsMargins(15, 12, 15 + solape, 12)

    def _ajustar_tabla_bajo_panel(self):
        """En "Oportunidades CM" la tabla se angosta mientras el panel está abierto para que
        este no tape su última columna (MOTIVO). En las otras sub-pestañas el panel flota encima."""
        layout = self.__dict__.get('_layout_tabla_bandeja')
        panel = self.__dict__.get('_panel_acciones')
        if layout is None or panel is None:
            return
        solape = 0
        if (panel.isVisible() and self._panel_acciones_abierto
                and getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM):
            marco = self.new_ui_table.parentWidget()
            borde_derecho = marco.mapTo(panel.parentWidget(), QPoint(marco.width(), 0)).x()
            solape = max(0, borde_derecho - panel.x() + 4)
        if layout.contentsMargins().right() != 1 + solape:
            layout.setContentsMargins(1, 1, 1 + solape, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # El panel flotante cuelga del módulo: se reubica al cambiar el tamaño
        panel = self.__dict__.get('_panel_acciones')
        if panel is not None and panel.isVisible():
            self._anim_panel_acciones.stop()
            # El layout aún no reubicó la pestaña en este evento
            QTimer.singleShot(0, self._reubicar_panel_acciones)

    def _reubicar_panel_acciones(self):
        panel = self._panel_acciones
        if not panel.isVisible():
            return
        panel.setGeometry(self._geometria_panel_acciones(self._panel_acciones_abierto))
        if not self._panel_acciones_abierto:
            panel.hide()
        self._ajustar_barra_bajo_panel()
        self._ajustar_tabla_bajo_panel()

    def _build_new_ui_kpi_row(self):
        """Construye 4 tarjetas "slot" reutilizables (25-09-2026): antes
        cada tarjeta nacía fija con la clave/título de vigencia de
        contrato, igual en las 6 sub-pestañas. Ahora el contenido (título,
        icono, colores, tooltip y qué clave del dict de KPIs muestra cada
        una) se repinta por sub-pestaña en _aplicar_kpi_spec_actual, según
        _NEW_UI_KPI_SPECS -- las tarjetas en sí son el mismo widget durante
        toda la vida del módulo, solo cambia lo que muestran."""
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self._new_ui_kpi_cards = []
        for _ in range(5):
            self._new_ui_kpi_cards.append(self._build_new_ui_kpi_card())
        for slot in self._new_ui_kpi_cards:
            kpi_row.addWidget(slot['card'])
        return kpi_row

    def _build_new_ui_kpi_card(self):
        """Mismo look que los KPI interactivos de la interfaz antigua (ver
        _ComercialModuleLegacy._create_interactive_kpi): QPushButton
        checkable, para que las tarjetas puedan filtrar la tabla al hacer
        clic (28-09-2026, a pedido explícito) -- _aplicar_kpi_spec_actual
        rellena el contenido real de la sub-pestaña activa y decide, por
        tarjeta, si queda clicable o solo informativa (ver
        _NEW_UI_KPI_FILTRABLE_KEYS). Devuelve un dict con las referencias
        que hacen falta para repintarla (card/icon_frame/icon_lbl/
        title_lbl/val_lbl/subtitulo_lbl/key/seleccionable). El clic se
        conecta una sola vez aquí, por posición de slot (0-3): la clave que
        representa cada slot cambia según la sub-pestaña activa, así que
        _on_new_ui_kpi_card_clicked la resuelve en el momento del clic, no
        acá."""
        card = estilo_com.TarjetaKpiComercial()
        card.set_estilo_plano(True)
        card.setFixedHeight(92)
        card.setCheckable(False)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(0)

        icon_frame = QFrame()
        icon_frame.setFixedSize(36, 36)
        icon_layout = QVBoxLayout(icon_frame)
        icon_layout.setContentsMargins(0, 0, 0, 0)

        icon_lbl = QLabel()
        icon_lbl.setStyleSheet("background: transparent; border: none;")
        icon_layout.addWidget(icon_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        title_lbl = QLabel("")
        title_lbl.setWordWrap(True)
        val_lbl = QLabel("0")
        barra = estilo_com.BarraKpi()
        # Pie de la tarjeta: "% del total" + subtítulo del spec o "clic para filtrar"
        subtitulo_lbl = QLabel("")
        subtitulo_lbl.setStyleSheet(estilo_com.QSS_KPI_SUBTITULO)

        pill_lbl = QLabel("")
        pill_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill_lbl.setFixedHeight(20)
        icon_frame.hide()
        barra.hide()

        fila_pie = QHBoxLayout()
        fila_pie.setSpacing(10)
        fila_pie.addWidget(pill_lbl)
        fila_pie.addWidget(subtitulo_lbl, stretch=1)

        layout.addWidget(title_lbl)
        layout.addWidget(val_lbl)
        layout.addStretch()
        layout.addLayout(fila_pie)

        slot_idx = len(self._new_ui_kpi_cards)
        card.clicked.connect(lambda checked=False, i=slot_idx: self._on_new_ui_kpi_card_clicked(i))
        return {
            'card': card, 'icon_frame': icon_frame, 'icon_lbl': icon_lbl,
            'title_lbl': title_lbl, 'val_lbl': val_lbl, 'subtitulo_lbl': subtitulo_lbl,
            'pill_lbl': pill_lbl, 'barra': barra, 'key': None, 'seleccionable': False, 'subtitulo': None, 'color': PRIMARY,
        }

    def _aplicar_kpi_spec_actual(self, active_subtab):
        """Repinta las 4 tarjetas KPI (título, icono, colores, tooltip,
        subtítulo opcional) con el spec de la sub-pestaña activa
        (_NEW_UI_KPI_SPECS) y reconstruye self.new_ui_kpi_labels (clave ->
        QLabel de valor) para que _refresh_new_ui_data pueda seguir
        escribiendo los valores con el mismo `for key, lbl in
        self.new_ui_kpi_labels.items()` de siempre, ahora con las claves
        correctas para esta sub-pestaña. También decide, por tarjeta, si
        queda clicable (ver _NEW_UI_KPI_FILTRABLE_KEYS) -- el estado
        'checked' en sí lo fija _actualizar_seleccion_visual_kpi, llamado
        después de esta función."""
        specs = self._NEW_UI_KPI_SPECS.get(active_subtab, self._NEW_UI_KPI_SPECS[0])
        claves_filtrables = self._NEW_UI_KPI_FILTRABLE_KEYS.get(active_subtab, set())
        self.new_ui_kpi_labels = {}
        for slot in self._new_ui_kpi_cards[len(specs):]:
            slot['key'], slot['seleccionable'] = None, False
            slot['card'].setVisible(False)
        for slot, spec in zip(self._new_ui_kpi_cards, specs):
            slot['card'].setVisible(True)
            key, title, icon_name, icon_bg_color, text_color, tooltip = spec[:6]
            subtitulo = spec[6] if len(spec) > 6 else None
            seleccionable = key in claves_filtrables

            slot['key'] = key
            slot['seleccionable'] = seleccionable
            slot['subtitulo'] = subtitulo
            slot['color'] = text_color
            slot['card'].setToolTip(tooltip)
            slot['icon_frame'].setStyleSheet(estilo_com.qss_icono_kpi(icon_bg_color))
            slot['icon_lbl'].setPixmap(ThemeManager.icon_pixmap(icon_name, color=text_color, size=16))
            slot['title_lbl'].setText(self._titulo_kpi_legible(title))
            slot['title_lbl'].setStyleSheet(
                f"color: {estilo_com.APAGADO}; font-size: 12px; font-weight: 500; background: transparent; border: none;")
            slot['val_lbl'].setStyleSheet(
                f"color: {estilo_com.TINTA}; font-size: 24px; font-weight: 800; background: transparent; border: none;")
            slot['subtitulo_lbl'].setStyleSheet(
                f"color: {estilo_com.APAGADO}; font-size: 11px; background: transparent; border: none;")
            color_pildora = self._COLORES_PILDORA_KPI.get(str(text_color).upper(), text_color)
            color_q = QColor(color_pildora)
            slot['pill_lbl'].setStyleSheet(
                f"color: {color_pildora}; background-color: rgba({color_q.red()},{color_q.green()},{color_q.blue()},0.14); "
                "border-radius: 10px; padding: 0px 8px; font-size: 11px; font-weight: 800; border: none;")

            slot['card'].setCheckable(seleccionable)
            slot['card'].setCursor(Qt.CursorShape.PointingHandCursor if seleccionable else Qt.CursorShape.ArrowCursor)
            slot['card'].configurar(seleccionable, text_color)
            self.new_ui_kpi_labels[key] = slot['val_lbl']

    # Colores de la píldora de % del HTML v2 (verde, rojo, ámbar, azul marino, pizarra)
    _COLORES_PILDORA_KPI = {
        str(SUCCESS).upper(): estilo_com.VERDE,
        str(DANGER).upper(): estilo_com.ROJO,
        str(WARNING).upper(): estilo_com.AMBAR,
        str(PRIMARY).upper(): "#1B2A49",
        "#64748B": estilo_com.PIZARRA,
    }

    # KPIs que no son una parte de las unidades del total (cuentan empresas o
    # suman montos): muestran esta descripción en vez de "% del total".
    _NEW_UI_KPI_SIN_PORCENTAJE = {
        'clientes': "Razones sociales distintas",
        'sin_contactos': "CDB sin contacto registrado",
        'monto_riesgo': "Suma de PAGO CM pendiente",
    }

    @staticmethod
    def _titulo_kpi_legible(titulo):
        texto = titulo.capitalize()
        for a, b in ((" cm", " CM"), ("3pc", "3PC"), ("cdb", "CDB")):
            texto = texto.replace(a, b)
        return texto

    def _actualizar_barras_kpi(self, kpis):
        """Barra de proporción y pie de cada tarjeta KPI (como el HTML de
        referencia): valor / tarjeta "total" de la misma sub-pestaña."""
        def numero(valor):
            try:
                return float(valor)
            except (TypeError, ValueError):
                return None

        total = numero(kpis.get('total'))
        bases = kpis.get('_bases') or {}
        unidad = "casos" if getattr(self, '_new_ui_active_subtab', 0) == self._NEW_UI_SUBTAB_REVISION_CM else "unidades"
        for slot in self._new_ui_kpi_cards:
            key = slot.get('key')
            pill = slot['pill_lbl']
            if key in self._NEW_UI_KPI_SIN_PORCENTAJE:
                pill.hide()
                texto = self._NEW_UI_KPI_SIN_PORCENTAJE[key]
            else:
                base = bases.get(key, total)
                valor = 1.0 if key == 'total' else ((numero(kpis.get(key, 0)) or 0.0) / base if base else 0.0)
                pill.setText(f"{round(valor * 100)} %")
                pill.show()
                if slot.get('subtitulo'):
                    texto = slot['subtitulo']
                elif key == 'total':
                    texto = f"{unidad} en cartera"
                elif key in bases:
                    texto = f"de {int(base or 0)} clientes"
                else:
                    texto = f"de {int(total or 0)} {unidad}"
            slot['subtitulo_lbl'].setText(texto)

    def _actualizar_seleccion_visual_kpi(self, active_subtab):
        """Refleja self._new_ui_kpi_filtro_por_subtab en el estado 'checked'
        de las tarjetas clicables de la sub-pestaña activa: sin filtro
        activo, la tarjeta "Total" queda marcada (mismo criterio que
        _apply_kpi_filter en la vista antigua)."""
        filtro_activo = self._new_ui_kpi_filtro_por_subtab.get(active_subtab)
        for slot in self._new_ui_kpi_cards:
            if not slot.get('seleccionable'):
                continue
            marcado = slot['key'] == filtro_activo or (filtro_activo is None and slot['key'] == 'total')
            slot['card'].blockSignals(True)
            slot['card'].setChecked(marcado)
            slot['card'].blockSignals(False)

    def _on_new_ui_kpi_card_clicked(self, slot_idx):
        """Clic en una tarjeta KPI clicable (28-09-2026, a pedido explícito):
        filtra new_ui_table por esa categoría. Clic repetido sobre la misma tarjeta, o clic en "Total", limpia el
        filtro. El filtro se recuerda por sub-pestaña
        (self._new_ui_kpi_filtro_por_subtab), no se resetea al cambiar de
        sub-pestaña."""
        slot = self._new_ui_kpi_cards[slot_idx]
        key = slot.get('key')
        if not key or not slot.get('seleccionable'):
            return
        subtab = getattr(self, '_new_ui_active_subtab', 0)
        actual = self._new_ui_kpi_filtro_por_subtab.get(subtab)
        self._new_ui_kpi_filtro_por_subtab[subtab] = None if (key == 'total' or actual == key) else key
        self._refresh_new_ui_data()
