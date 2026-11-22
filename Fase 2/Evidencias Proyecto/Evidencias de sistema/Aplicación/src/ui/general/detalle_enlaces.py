"""Unidades y flotas dentro del detalle de un cliente y navegación entre cliente, flota y unidad."""
from src.theme.colors import TEXT_MUTED, TEXT_SECONDARY
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QScrollArea, QSizePolicy
from PyQt6.QtCore import Qt, QTimer
from src.core.constants import COL_CDB_FLOTA, COL_FLOTA_VC
from src.services import comercial_services
from src.theme.theme_manager import ThemeManager
from src.services import general_services
from src.ui.general.base import (
    FiltroValoresBoton,
    GeneralFlotaFila,
    _FILTROS_UNIDADES,
    _clave_flota_texto,
    _flota_valida,
    _tarjeta_blanca,
)


class _DetalleEnlacesGeneralMixin:
    # ==========================================
    # VISTA "UNIDADES" (caja derecha, detalle de cliente): solo las VIN del
    # CDB seleccionado. El filtrado se hace por CDB, nunca por Flota VC (un
    # CDB puede tener varias Flota VC distintas y todas sus unidades deben
    # listarse igual).
    # ==========================================
    def _build_detalle_unidades_view(self):
        """Contratos del cliente: la misma tabla y los mismos filtros de la ficha de flota."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        filtros_frame = QFrame()
        ThemeManager.apply_card_style(filtros_frame)
        _tarjeta_blanca(filtros_frame)
        fila_filtros = QHBoxLayout(filtros_frame)
        fila_filtros.setContentsMargins(8, 6, 8, 6)
        fila_filtros.setSpacing(6)
        self._filtros_cliente_unidades = {}
        for columna, titulo in _FILTROS_UNIDADES:
            boton = FiltroValoresBoton(titulo)
            boton.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            boton.setMinimumWidth(0)
            boton.cambiado.connect(self._pintar_unidades_cliente)
            self._filtros_cliente_unidades[columna] = boton
            fila_filtros.addWidget(boton, 1)
        btn_limpiar = QPushButton()
        btn_limpiar.setIcon(ThemeManager.icon('fa5s.eraser', color=TEXT_SECONDARY))
        btn_limpiar.setToolTip("Limpiar filtros")
        btn_limpiar.setFixedSize(26, 26)
        btn_limpiar.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_limpiar.setStyleSheet("QPushButton { border: none; border-radius: 13px; background: transparent; }"
                                  "QPushButton:hover { background: #E3E8F0; }")
        btn_limpiar.clicked.connect(self._limpiar_filtros_cliente_unidades)
        fila_filtros.addWidget(btn_limpiar)
        self._filtros_cliente_frame = filtros_frame

        self.lbl_unidades_detalle_resumen = QLabel("")
        self.lbl_unidades_detalle_resumen.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self.lbl_unidades_detalle_resumen)
        self.tabla_cliente_unidades = self._crear_tabla_contratos()
        layout.addWidget(self.tabla_cliente_unidades)
        layout.addStretch()
        self._cliente_df_unidades = pd.DataFrame()
        self._cliente_unidades_construidas = True
        return widget

    def _limpiar_filtros_cliente_unidades(self):
        for boton in self._filtros_cliente_unidades.values():
            boton.limpiar()
        self._pintar_unidades_cliente()

    def _iniciar_unidades_cliente(self):
        if self.__dict__.get('_cliente_unidades_construidas', True):
            return
        self._cliente_unidades_construidas = True
        self._pintar_unidades_cliente()

    def _pintar_unidades_cliente(self):
        self._pintar_tabla_contratos(
            self.tabla_cliente_unidades, self.lbl_unidades_detalle_resumen, self._cliente_df_unidades,
            self._filtros_cliente_unidades, getattr(self, '_vins_busqueda', None),
            "Este cliente no tiene unidades registradas.")

    # ==========================================
    # SUBPESTAÑA "FLOTAS VC" (caja derecha, detalle de cliente): flotas del
    # cliente y cantidad de unidades de cada una; los "-" no cuentan.
    # ==========================================
    def _build_detalle_flotas_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.lbl_flotas_detalle_resumen = QLabel("")
        self.lbl_flotas_detalle_resumen.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self.lbl_flotas_detalle_resumen)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")
        contenedor = QWidget()
        contenedor.setStyleSheet("background: transparent;")
        self.flotas_detalle_layout = QVBoxLayout(contenedor)
        self.flotas_detalle_layout.setContentsMargins(0, 0, 4, 0)
        self.flotas_detalle_layout.setSpacing(6)
        self.flotas_detalle_layout.addStretch()
        scroll.setWidget(contenedor)
        self._flotas_detalle_filas = {}
        layout.addWidget(scroll, stretch=1)
        return widget

    _flotas_de_unidades = staticmethod(general_services.flotas_de_unidades)

    @staticmethod
    def _cdb_por_flota(df_unidades):
        """{clave de flota VC: "CDB1, CDB2"} con los CDB flota de sus unidades."""
        if df_unidades is None or df_unidades.empty or COL_FLOTA_VC not in df_unidades.columns \
                or COL_CDB_FLOTA not in df_unidades.columns:
            return {}
        mapa = {}
        for flota, cdb in zip(df_unidades[COL_FLOTA_VC].astype(str).str.strip(), df_unidades[COL_CDB_FLOTA].astype(str).str.strip()):
            cdb = cdb[:-2] if cdb.endswith(".0") else cdb
            if not _flota_valida(flota) or cdb.upper() in ("", "-", "NAN", "NONE", "<NA>", "NO ENCONTRADO"):
                continue
            lista = mapa.setdefault(_clave_flota_texto(flota), [])
            if cdb not in lista:
                lista.append(cdb)
        return {clave: ", ".join(cdbs) for clave, cdbs in mapa.items()}

    def _pintar_flotas_detalle(self, flotas, cdb_por_flota=None):
        cdb_por_flota = cdb_por_flota or {}
        layout = self.flotas_detalle_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._flotas_detalle_filas = {}
        self.btn_detalle_flotas.setText(f"Flotas VC ({len(flotas)})" if flotas else "Flotas VC")

        if not flotas:
            self.lbl_flotas_detalle_resumen.setText("")
            lbl = QLabel("Este cliente no tiene flotas VC informadas.")
            lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; padding: 12px;")
            layout.addWidget(lbl)
            layout.addStretch()
            return

        total = sum(n for _, n in flotas)
        self.lbl_flotas_detalle_resumen.setText(
            f"{len(flotas)} {'flota' if len(flotas) == 1 else 'flotas'} · {total} "
            f"{'unidad' if total == 1 else 'unidades'} con flota")
        for nombre, cantidad in flotas:
            fila = GeneralFlotaFila(nombre, cantidad, cdb_por_flota.get(_clave_flota_texto(nombre), ""))
            fila.seleccionada.connect(self._on_flota_detalle_seleccionada)
            self._flotas_detalle_filas[nombre] = fila
            layout.addWidget(fila)
        layout.addStretch()

    def _resaltar_flota_detalle(self, flota):
        for clave, fila in self._flotas_detalle_filas.items():
            fila.set_selected(clave == flota)

    def _on_flota_detalle_seleccionada(self, flota):
        """Clic en una flota del cliente: abre la pestaña Flotas con esa flota
        seleccionada (antes filtraba las unidades del cliente)."""
        self._resaltar_flota_detalle(flota)
        self._abrir_flota_desde_unidad('', flota)

    def _abrir_unidad_en_pestana_unidades(self, vin):
        """Doble clic en una unidad del detalle de cliente: abre la pestaña
        Unidades de la caja izquierda en la página donde está esa unidad,
        la resalta y la caja derecha pasa a mostrar su ficha."""
        vin = str(vin).strip()
        if not vin:
            return
        anterior = str(self._vin_seleccionado).strip() if self._vin_seleccionado else None
        self._vin_seleccionado = vin
        df = getattr(self, '_unidades_df_paginado', None)
        if df is not None and not df.empty and 'VIN' in df.columns:
            coincide = (df['VIN'].astype(str).str.strip().str.upper() == vin.upper()).to_numpy().nonzero()[0]
            if len(coincide):
                pagina = int(coincide[0]) // self._unidades_tam_pagina
                # Solo se repinta si la unidad está en otra página; en la misma basta con mover el resaltado
                if pagina != self._unidades_pagina_actual:
                    self._unidades_pagina_actual = pagina
                    self._unidades_pendiente_render = True
        if anterior and anterior != vin and anterior in self._unidad_cards:
            self._unidad_cards[anterior].set_selected(False)
        if vin in self._unidad_cards:
            self._unidad_cards[vin].set_selected(True)
        self._switch_left_view(1)
        if not self._vin_seleccionado:
            # La lista de Unidades tiene filtros/búsqueda que ocultan este
            # VIN: igual se muestra su ficha en la caja derecha.
            self._vin_seleccionado = vin
            self._show_vin_detalle(vin)
        self._switch_vin_detalle_view(0)
        self._desplazar_a_unidad(vin)

    def _desplazar_a_unidad(self, vin, intentos=8):
        self._desplazar_a_tarjeta('_unidad_cards', vin, 'unidades_scroll', intentos)

    def _desplazar_a_tarjeta(self, atributo_cards, clave, atributo_scroll, intentos=8):
        """Las tarjetas se construyen por tandas: reintenta hasta que exista."""
        card = getattr(self, atributo_cards, {}).get(clave)
        if card is not None:
            getattr(self, atributo_scroll).ensureWidgetVisible(card, 0, 40)
        elif intentos > 0:
            QTimer.singleShot(120, lambda: self._desplazar_a_tarjeta(atributo_cards, clave, atributo_scroll, intentos - 1))

    def _abrir_cliente_desde_unidad(self, razon_social, rut=""):
        """Clic en la razón social de la ficha de una unidad: abre la
        pestaña Cliente en la página del cliente (identificado por su RUT),
        lo resalta y la caja derecha pasa a mostrar su detalle."""
        razon = str(razon_social).strip()
        if not razon or razon == '-':
            return
        self._abrir_cliente_por_clave(comercial_services.clave_cliente(rut, razon))

    def mostrar_cliente_de_vins(self, clave, vins):
        """Desde el Dashboard: abre el cliente con su pestaña Unidades a la vista, con los VIN pedidos primero y
        seleccionados (incluye las unidades sin Flota VC). Devuelve False si el cliente no existe."""
        if self._buscar_cliente_por_clave(clave) is None:
            return False
        self._vins_busqueda = {str(v).strip().upper() for v in vins}
        self._abrir_cliente_por_clave(clave)
        self._switch_detalle_view(1)
        if self.__dict__.get('_cliente_unidades_construidas', False):
            self._pintar_unidades_cliente()
        return True

    def _abrir_cliente_por_clave(self, clave):
        df = getattr(self, '_clientes_df_paginado', None)
        if df is not None and not df.empty and 'Clave' in df.columns:
            coincide = (df['Clave'].astype(str) == clave).to_numpy().nonzero()[0]
            if len(coincide):
                pagina = int(coincide[0]) // self._clientes_tam_pagina
                if pagina != self._clientes_pagina_actual:
                    self._clientes_pagina_actual = pagina
                    self._clientes_pendiente_render = True
        # La clave se fija antes de cambiar de pestaña para que la caja derecha arme el detalle de este
        # cliente una sola vez (antes armaba primero el del cliente anterior y luego este)
        anterior = self._selected_cliente_key
        self._selected_cliente_key = clave
        self._switch_left_view(0)
        # (si el cliente no está en la lista filtrada, igual se muestra su
        # detalle en la caja derecha)
        if self.__dict__.get('_clave_detalle_mostrada') != clave or self.right_stack.currentIndex() != 1:
            self._seleccionar_cliente_por_clave(clave)
        self._switch_detalle_view(0)
        if anterior and anterior != clave and anterior in self._cliente_cards:
            self._cliente_cards[anterior].set_selected(False)
        if clave in self._cliente_cards:
            self._cliente_cards[clave].set_selected(True)
        self._desplazar_a_tarjeta('_cliente_cards', clave, 'clientes_scroll')

    def _abrir_flota_desde_unidad(self, cdb, flota_vc, razon_social="", rut=""):
        """Clic en la Flota VC de la ficha de una unidad: abre la pestaña
        Flotas con esa flota seleccionada. Si la flota no existe como tal
        (p. ej. "Sin flota"), cae al comportamiento anterior: pestaña Cliente."""
        cdb, flota = str(cdb).strip(), str(flota_vc).strip()
        if not flota or flota == '-':
            return
        clave_flota = _clave_flota_texto(flota) if _flota_valida(flota) else ''
        if clave_flota and self._buscar_flota_por_clave(clave_flota) is not None:
            df = self._flotas_df_paginado
            if not df.empty and 'Clave' in df.columns:
                coincide = (df['Clave'].astype(str) == clave_flota).to_numpy().nonzero()[0]
                if len(coincide):
                    pagina = int(coincide[0]) // self._flotas_tam_pagina
                    if pagina != self._flotas_pagina_actual:
                        self._flotas_pagina_actual = pagina
                        self._flotas_pendiente_render = True
            anterior = self._selected_flota_key
            self._selected_flota_key = clave_flota
            if anterior and anterior != clave_flota and anterior in self._flota_cards:
                self._flota_cards[anterior].set_selected(False)
            if clave_flota in self._flota_cards:
                self._flota_cards[clave_flota].set_selected(True)
            self._switch_left_view(2)
            self._switch_flota_detalle_view(0)
            self._desplazar_a_tarjeta('_flota_cards', clave_flota, 'flotas_scroll')
            return
        razon = str(razon_social).strip()
        if not razon or razon == '-':
            self._switch_left_view(0)
            self._show_flota_sin_cliente(flota)
            return
        self._abrir_cliente_desde_unidad(razon, rut)
        self._switch_detalle_view(2)
        self._resaltar_flota_detalle(flota)
