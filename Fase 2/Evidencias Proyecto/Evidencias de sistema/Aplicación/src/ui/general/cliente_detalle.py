"""Vista de detalle de un cliente en General: resumen, contactos y tarjetas de personas."""
from src.theme.colors import BORDER, PRIMARY, SURFACE, TEXT_MUTED, TEXT_PRIMARY, VOLVO_BLUE
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QStackedWidget, QScrollArea, QGridLayout, QSizePolicy
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon
from src.services import contactos_service
from src.ui.compartido.copiar import copiar_texto
from src.theme.theme_manager import ThemeManager
from src.ui.general.base import (
    AZUL,
    AZUL_HOVER,
    CopyableLabel,
    CopyableTitulo,
    CopyableValueLabel,
    LINEA_AZUL,
    QSS_CONTENEDOR_PESTANAS_CLARO,
    QSS_PESTANAS_CLARAS,
    TEXTO_SOBRE_AZUL,
    TINTE_CLARO,
    _BloqueResumenCliente,
    _EtiquetaElidida,
    _EtiquetaElididaCopiable,
    _KpiCompacto,
    _tarjeta_blanca,
)


class _ClienteDetalleGeneralMixin:
    def _build_cliente_detalle_view(self):
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
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.building', color='white', size=18))
        icono.setStyleSheet("background: rgba(255,255,255,0.12); border: 2px solid rgba(255,255,255,0.45); border-radius: 20px;")

        self.lbl_detalle_title = CopyableTitulo("")
        self.lbl_detalle_title.setWordWrap(True)
        self.lbl_detalle_title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        fila_superior = QHBoxLayout()
        fila_superior.setSpacing(10)
        fila_superior.addWidget(icono)
        fila_superior.addWidget(self.lbl_detalle_title, 1)
        layout.addLayout(fila_superior)
        layout.addSpacing(8)

        # Industria / RUT / CDB como chips copiables
        subtitle_row = QHBoxLayout()
        subtitle_row.setSpacing(6)
        self.lbl_detalle_industria = CopyableLabel()
        self.lbl_detalle_rut = CopyableLabel()
        self.lbl_detalle_cdb = CopyableLabel()
        self.lbl_detalle_cdb_flota = CopyableLabel()
        for chip in (self.lbl_detalle_industria, self.lbl_detalle_rut, self.lbl_detalle_cdb, self.lbl_detalle_cdb_flota):
            chip._BASE_STYLE = (f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; padding: 3px 10px; "
                                "border: 1px solid rgba(255,255,255,0.28); border-radius: 9px; background-color: rgba(255,255,255,0.08);")
            chip._HOVER_STYLE = (f"color: {AZUL}; font-size: 11px; padding: 3px 10px; "
                                 "border: 1px solid white; border-radius: 9px; background-color: white;")
            chip.setStyleSheet(chip._BASE_STYLE)
            if chip is not self.lbl_detalle_industria:
                subtitle_row.addWidget(chip)
        subtitle_row.addStretch()
        layout.addLayout(subtitle_row)
        layout.addStretch(1)

        # Las tarjetas KPI bajan de la portada al inicio del contenido (más abajo, tras agregar la portada a la hoja)
        kpi_layout = QHBoxLayout()
        self.bloque_resumen_cliente = _BloqueResumenCliente()
        kpi_layout.addWidget(self.bloque_resumen_cliente)

        detalle_nav_barra = QFrame()
        detalle_nav_barra.setObjectName("barraPestanasGeneral")
        detalle_nav_barra.setStyleSheet(QSS_CONTENEDOR_PESTANAS_CLARO)
        detalle_nav_layout = QHBoxLayout(detalle_nav_barra)
        detalle_nav_layout.setContentsMargins(0, 0, 0, 0)
        detalle_nav_layout.setSpacing(2)
        self.btn_detalle_resumen = QPushButton("Resumen")
        self.btn_detalle_unidades = QPushButton("Unidades")
        self.btn_detalle_flotas = QPushButton("Flotas VC")
        self.btn_detalle_contactos = QPushButton("Contactos")
        # "Historial" quitado de este detalle (Cliente y Flota comparten esta
        # misma vista, ver _show_cliente_detalle) a pedido explícito
        # (15-09-2026): el historial por VIN de Unidades (caja derecha ->
        # Unidades -> Historial, _build_historial_vin_view) NO se toca.
        # "Duplicados" (23-09-2026, a pedido explícito): solo visible cuando
        # el cliente seleccionado comparte RUT+CDB con otra Razón Social (ver
        # _populate_duplicados_detalle) -- oculto por defecto, igual criterio
        # que btn_filtro_unidades para pestañas condicionales. Icono en vez de
        # emoji en el texto (mismo patrón que el resto de botones de este
        # archivo): un caracter Unicode crudo en un QPushButton.text() rompe
        # la consola de Windows (cp1252) si algún test llega a imprimirlo en
        # un mensaje de fallo -- confirmado con un UnicodeEncodeError real al
        # correr la suite completa.
        self.btn_detalle_duplicados = QPushButton("Razones")
        self.btn_detalle_duplicados.setVisible(False)
        self._detalle_nav_buttons = [self.btn_detalle_resumen, self.btn_detalle_unidades,
                                      self.btn_detalle_flotas, self.btn_detalle_contactos,
                                      self.btn_detalle_duplicados]
        # Mismo estilo tipo pestaña que el grupo Cliente/Flota/Unidades de arriba.
        detalle_tab_style = QSS_PESTANAS_CLARAS
        for i, btn in enumerate(self._detalle_nav_buttons):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(detalle_tab_style)
            btn.clicked.connect(lambda checked, idx=i: self._switch_detalle_view(idx))
            detalle_nav_layout.addWidget(btn)
        detalle_nav_layout.addStretch()
        self.btn_detalle_resumen.setChecked(True)
        layout.addWidget(detalle_nav_barra)
        lay_hoja.addWidget(portada)
        self._portadas_unidad = self.__dict__.get('_portadas_unidad', []) + [portada]
        kpi_layout.setContentsMargins(14, 12, 14, 0)
        lay_hoja.addLayout(kpi_layout)

        self.detalle_stack = QStackedWidget()
        self.detalle_stack.setContentsMargins(14, 12, 14, 14)
        self.detalle_stack.addWidget(self._build_detalle_resumen_view())
        self.detalle_stack.addWidget(self._build_detalle_unidades_view())
        self.detalle_stack.addWidget(self._build_detalle_flotas_view())
        self.detalle_stack.addWidget(self._build_detalle_contactos_view())
        self.detalle_stack.addWidget(self._build_detalle_duplicados_view())

        # Scroll acotado únicamente al contenido de la pestaña activa
        # (Resumen/Unidades/Contactos/Historial): todo lo de arriba (título,
        # Industria/RUT/CDB, KPIs, y las propias pestañas
        # Resumen/Unidades/Contactos/Historial) queda fuera de este
        # QScrollArea y por lo tanto fijo mientras se hace scroll acá abajo.
        # Mismo estilo/transparencia que usaba antes el scroll que envolvía
        # toda la caja derecha (ver comentario histórico en _setup_right_box).
        self.detalle_scroll = QScrollArea()
        self.detalle_scroll.setWidgetResizable(True)
        self.detalle_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detalle_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.detalle_scroll.viewport().setStyleSheet("background: transparent;")
        self.detalle_scroll.setWidget(self.detalle_stack)
        self.detalle_stack.setStyleSheet("background: transparent;")

        # Los filtros quedan fijos arriba mientras se desplaza la tabla (solo en la pestaña Unidades)
        self._contenedor_filtros_cliente = QWidget()
        lay_filtros = QVBoxLayout(self._contenedor_filtros_cliente)
        lay_filtros.setContentsMargins(14, 8, 14, 0)
        lay_filtros.addWidget(self._filtros_cliente_frame)
        self._contenedor_filtros_cliente.hide()
        lay_hoja.addWidget(self._contenedor_filtros_cliente)
        lay_hoja.addWidget(self.detalle_scroll, stretch=1)
        raiz.addWidget(hoja, 1)

        return widget

    def _crear_kpi_comercial(self, titulo, valor, pie):
        """Tarjeta KPI baja (28-10-2026): título, número y, a la derecha, el %
        o la línea de apoyo. Devuelve (tarjeta, etiqueta del número); la
        tarjeta queda en etiqueta._tarjeta."""
        tarjeta = _KpiCompacto(titulo.capitalize(), str(valor))
        tarjeta.actualizar(valor, None, pie)
        tarjeta._lbl_valor._tarjeta = tarjeta
        return tarjeta, tarjeta._lbl_valor

    def _build_detalle_resumen_view(self):
        widget = QWidget()
        columnas = QHBoxLayout(widget)
        columnas.setContentsMargins(0, 0, 0, 0)
        columnas.setSpacing(12)
        layout = QVBoxLayout()
        layout.setSpacing(6)
        columna_contactos = QVBoxLayout()
        columna_contactos.setSpacing(6)
        columnas.addLayout(layout, 1)
        columnas.addLayout(columna_contactos, 1)

        # --- Caja 1: Información del cliente ---
        info_frame = QFrame()
        ThemeManager.apply_card_style(info_frame)
        _tarjeta_blanca(info_frame)
        info_outer_layout = QVBoxLayout(info_frame)
        info_outer_layout.setContentsMargins(10, 8, 10, 10)
        info_outer_layout.setSpacing(4)

        info_header_row = QHBoxLayout()
        lbl_info_title = QLabel("INFORMACIÓN DEL CLIENTE")
        lbl_info_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        info_header_row.addWidget(lbl_info_title)
        info_header_row.addStretch()
        info_outer_layout.addLayout(info_header_row)

        self.info_cliente_layout = QGridLayout()
        self.info_cliente_layout.setHorizontalSpacing(24)
        self.info_cliente_layout.setVerticalSpacing(0)
        self.info_cliente_layout.setColumnStretch(0, 1)
        self.info_cliente_layout.setColumnStretch(1, 1)
        info_outer_layout.addLayout(self.info_cliente_layout)
        layout.addWidget(info_frame)

        # --- Caja 2: Contactos encontrados (cruce por CDB con el módulo Contactos) ---
        contactos_frame = QFrame()
        ThemeManager.apply_card_style(contactos_frame)
        _tarjeta_blanca(contactos_frame)
        contactos_outer_layout = QVBoxLayout(contactos_frame)
        contactos_outer_layout.setContentsMargins(10, 8, 10, 10)
        contactos_outer_layout.setSpacing(6)

        contactos_header_row = QHBoxLayout()
        lbl_contactos_title = QLabel("CONTACTOS")
        lbl_contactos_title.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        contactos_header_row.addWidget(lbl_contactos_title)
        contactos_header_row.addStretch()
        contactos_header_row.setSpacing(6)
        self.btn_agregar_admin_resumen = self._crear_boton_circular('fa5s.plus', "Agregar administrador de flota")
        self.btn_agregar_admin_resumen.clicked.connect(self._handle_agregar_contacto)
        self.btn_agregar_admin_resumen.hide()
        self.lbl_ver_todos_contactos = self._crear_boton_circular('fa5s.arrow-right', "Ver todos")
        self.lbl_ver_todos_contactos.clicked.connect(lambda: self._switch_detalle_view(3))
        contactos_header_row.addWidget(self.btn_agregar_admin_resumen)
        contactos_header_row.addWidget(self.lbl_ver_todos_contactos)
        contactos_outer_layout.addLayout(contactos_header_row)

        fila_conteos = QHBoxLayout()
        fila_conteos.setSpacing(8)
        self._btn_conteo_directores = btn_dir = self._crear_conteo_contactos("Directores", "fa5s.crown", "#D4AF37")
        self._btn_conteo_administradores = btn_adm = self._crear_conteo_contactos("Administradores", "fa5s.user-tie", VOLVO_BLUE)
        fila_conteos.addWidget(btn_dir)
        fila_conteos.addWidget(btn_adm)
        contactos_outer_layout.addLayout(fila_conteos)

        # Sin borde/fondo propio en el QScrollArea ni en su viewport interno
        # (por defecto Qt pinta el viewport con Base del palette, lo que se
        # veía como un recuadro gris "cuadrado" encima del fondo blanco de la
        # tarjeta). Altura mínima en vez de fija + stretch=1 en el layout de
        # abajo: así esta tarjeta crece para ocupar el espacio disponible de
        # la caja derecha en vez de quedar apretada arriba con hueco vacío.
        self.contactos_encontrados_scroll = QScrollArea()
        self.contactos_encontrados_scroll.setWidgetResizable(True)
        self.contactos_encontrados_scroll.setMinimumHeight(90)
        self.contactos_encontrados_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.contactos_encontrados_scroll.viewport().setStyleSheet("background: transparent;")
        self.contactos_encontrados_container = QWidget()
        self.contactos_encontrados_container.setStyleSheet("background: transparent;")
        self.contactos_encontrados_layout = QVBoxLayout(self.contactos_encontrados_container)
        self.contactos_encontrados_layout.setContentsMargins(0, 2, 0, 2)
        self.contactos_encontrados_layout.setSpacing(4)
        self.contactos_encontrados_scroll.setWidget(self.contactos_encontrados_container)
        self.contactos_encontrados_scroll.hide()
        contactos_outer_layout.addWidget(self.contactos_encontrados_scroll)

        columna_contactos.addWidget(contactos_frame)
        columna_contactos.addStretch()
        layout.addStretch()

        # --- Caja 3: preparada, sin contenido todavía (a pedido explícito) ---
        self.tercera_caja_resumen = QFrame()
        ThemeManager.apply_card_style(self.tercera_caja_resumen)
        QVBoxLayout(self.tercera_caja_resumen).setContentsMargins(10, 10, 10, 10)
        self.tercera_caja_resumen.hide()
        layout.addWidget(self.tercera_caja_resumen)

        return widget

    def _crear_boton_circular(self, icono, tooltip):
        """Botón redondo azul Volvo con ícono blanco."""
        btn = QPushButton()
        btn.setFixedSize(26, 26)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(tooltip)
        btn.setIcon(QIcon(ThemeManager.icon_pixmap(icono, color="white", size=12)))
        btn.setIconSize(QSize(12, 12))
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {AZUL}; border: none; border-radius: 13px; }}"
            f"QPushButton:hover {{ background-color: {AZUL_HOVER}; }}")
        return btn

    def _crear_conteo_contactos(self, titulo, icono, color):
        """Botón-tarjeta con un conteo de contactos; al hacer clic abre la pestaña Contactos."""
        btn = QPushButton()
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(56)
        btn.setObjectName("conteoContactos")
        btn.setStyleSheet(
            f"QPushButton#conteoContactos {{ background-color: #F3F5F9; border: 1px solid {BORDER}; border-radius: 12px; }}"
            f"QPushButton#conteoContactos:hover {{ background-color: {TINTE_CLARO}; border: 1px solid {LINEA_AZUL}; }}")
        btn.setToolTip("Abrir la pestaña Contactos")
        btn.clicked.connect(lambda: self._switch_detalle_view(3))
        lay = QHBoxLayout(btn)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(10)
        ico = QLabel()
        ico.setFixedSize(34, 34)
        ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ico.setPixmap(ThemeManager.icon_pixmap(icono, color='white', size=15))
        ico.setStyleSheet(f"background-color: {color}; border-radius: 17px;")
        textos = QVBoxLayout()
        textos.setSpacing(0)
        valor = QLabel("0")
        valor.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: bold; background: transparent; border: none;")
        etiqueta = QLabel(titulo)
        etiqueta.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; background: transparent; border: none;")
        textos.addWidget(valor)
        textos.addWidget(etiqueta)
        lay.addWidget(ico)
        lay.addLayout(textos, 1)
        for w in (ico, valor, etiqueta):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        btn._valor, btn._ico, btn._color = valor, ico, color
        return btn

    def _fijar_conteo_contactos(self, btn, n):
        activo = n > 0
        btn._valor.setText(str(n))
        gris = '#9AA3B5'
        btn._valor.setStyleSheet(f"color: {TEXT_PRIMARY if activo else gris}; font-size: 18px; font-weight: bold; background: transparent; border: none;")
        btn._ico.setStyleSheet(f"background-color: {btn._color if activo else '#C5CCDA'}; border-radius: 17px;")

    def _render_info_cliente(self, razon_social, rut, cdb, industria, ejecutivo, total_unidades, flotas_txt, direccion="", comuna=""):
        while self.info_cliente_layout.count():
            item = self.info_cliente_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # RUT, CDB e Industria ya se ven como chips en la cabecera del detalle.
        # (etiqueta, valor, copiable, ancho completo)
        celdas = []
        if ejecutivo:
            celdas.append(("Ejecutivo", ejecutivo, False, False))
        if industria and str(industria).strip() not in ('', '-', 'nan'):
            celdas.append(("Industria", str(industria), False, False))
        celdas.append(("Total de unidades", str(total_unidades), False, False))
        # Dirección/Comuna: BBDD CLIENTES CM.xlsx (Power BI), mismo cruce por
        # CDB que ya usa _create_director_empresa_card para correo/teléfono
        # (ver _show_cliente_detalle). Solo se agregan si llegó el dato --
        # puede no haber llegado aún (carga async) o no existir para ese CDB.
        if direccion:
            celdas.append(("Dirección", direccion, True, False))
        if comuna:
            celdas.append(("Comuna", comuna, True, False))
        celdas.append(("Flota(s)", flotas_txt, False, True))

        # Dirección y Comuna se copian juntas, sea cual sea la que se pulse
        direccion_y_comuna = ", ".join(t for t in (direccion, comuna) if t)
        fila, columna = 0, 0
        for label, value, copyable, ancho_completo in celdas:
            es_ubicacion = label in ("Dirección", "Comuna")
            celda = self._create_info_celda(
                label, value, copyable,
                tooltip=(getattr(self, '_info_cliente_flotas_tooltip', '') if label == "Flota(s)"
                         else (f"Clic para copiar dirección y comuna:\n{direccion_y_comuna}" if es_ubicacion else str(value))),
                elidir=True, copiar_texto=direccion_y_comuna if es_ubicacion else None)
            if ancho_completo:
                if columna:
                    fila, columna = fila + 1, 0
                self.info_cliente_layout.addWidget(celda, fila, 0, 1, 2)
                fila += 1
            else:
                self.info_cliente_layout.addWidget(celda, fila, columna)
                columna += 1
                if columna == 2:
                    fila, columna = fila + 1, 0

    def _create_info_celda(self, label, value, copyable=False, tooltip="", elidir=False, copiar_texto=None):
        """Celda de "Información del cliente": etiqueta pequeña sobre el valor.
        Con `elidir` el valor va en una línea y se corta con "…" si no cabe."""
        celda = QWidget()
        celda.setStyleSheet(f"QWidget#celdaInfo {{ border-bottom: 1px solid {BORDER}; }}")
        celda.setObjectName("celdaInfo")
        lay = QVBoxLayout(celda)
        lay.setContentsMargins(0, 8, 0, 8)
        lay.setSpacing(1)
        lbl_label = QLabel(label)
        lbl_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; border: none; background: transparent;")
        base_style = f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;"
        if elidir and copiar_texto:
            lbl_value = _EtiquetaElididaCopiable(value, copiar_texto, base_style)
        elif elidir:
            lbl_value = _EtiquetaElidida(value)
            lbl_value.setStyleSheet(base_style)
            if tooltip:
                lbl_value.setToolTip(tooltip)
        else:
            if copyable and value and value != "N/A":
                lbl_value = CopyableValueLabel(value, value, base_style)
            else:
                lbl_value = QLabel(value)
                lbl_value.setStyleSheet(base_style)
            lbl_value.setWordWrap(True)
        lay.addWidget(lbl_label)
        lay.addWidget(lbl_value)
        return celda

    def _create_contacto_card(self, nombre, apellidos, correo, telefono, contact_id=None):
        iniciales = f"{nombre[:1]}{apellidos[:1]}".upper().strip() or "?"
        avatar = QLabel(iniciales)
        avatar.setStyleSheet(f"background-color: {VOLVO_BLUE}; color: white; border-radius: 17px; font-weight: bold; font-size: 12px;")
        frame, row_layout = self._armar_tarjeta_persona(avatar, f"{nombre} {apellidos}".strip(), correo, telefono)

        # Favorito: mismo sistema de favoritos que contactos.py (archivo
        # compartido config/pinned_contacts.json, clave = ID físico del
        # contacto normalizado). Solo se muestra si el llamador identificó
        # el contacto (contact_id); las tarjetas del Director de empresa no
        # pasan contact_id porque no son un contacto individual favoriteable.
        if contact_id:
            es_favorito = contact_id in self.pinned_contacts
            btn_favorito = QPushButton()
            btn_favorito.setFlat(True)
            btn_favorito.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_favorito.setFixedSize(20, 20)
            btn_favorito.setIconSize(QSize(13, 13))
            btn_favorito.setStyleSheet("QPushButton { background: transparent; border: none; }")
            btn_favorito.setIcon(ThemeManager.icon('fa5s.star', color='#F59E0B' if es_favorito else '#D1D5DB'))
            btn_favorito.setToolTip("Quitar de favoritos" if es_favorito else "Marcar como favorito")
            btn_favorito.clicked.connect(lambda checked=False, cid=contact_id: self._toggle_favorito_contacto(cid))
            row_layout.addWidget(btn_favorito)

        return frame

    def _toggle_favorito_contacto(self, contact_id):
        """Marca/desmarca un contacto como favorito y refresca las tarjetas
        del cliente actualmente seleccionado. Mismo archivo/formato que
        contactos.py (contactos_service.cargar_favoritos/guardar_favoritos),
        así el favorito queda sincronizado entre ambos módulos."""
        if contact_id in self.pinned_contacts:
            self.pinned_contacts.remove(contact_id)
        else:
            self.pinned_contacts.append(contact_id)
        contactos_service.guardar_favoritos(self.pinned_file, self.pinned_contacts)
        if self._selected_cdb:
            self._populate_contactos_encontrados(self._selected_cdb)

    def _create_director_empresa_card(self, correo, telefono):
        """Tarjeta del "Director de empresas" en BBDD CLIENTES CM.xlsx
        (Power BI) -- dato de la EMPRESA (un solo registro por CDB), distinto
        de las tarjetas de contactos individuales de contactos.xlsx que arma
        _create_contacto_card. Mismo layout/estilo que esas tarjetas (a
        pedido explícito), salvo el avatar (corona dorada en vez de
        iniciales) y que correo/teléfono son CopyableLabel (clic para
        copiar). Solo se llama cuando hay correo y/o teléfono (ver
        _populate_contact_cards)."""
        DORADO = "#D4AF37"
        avatar = QLabel()
        avatar.setStyleSheet(f"background-color: {DORADO}; border-radius: 17px;")
        avatar.setPixmap(ThemeManager.icon_pixmap('fa5s.crown', color='white', size=14))
        frame, _ = self._armar_tarjeta_persona(avatar, "Director de empresa", correo, telefono, borde=DORADO)
        return frame

    def _armar_tarjeta_persona(self, avatar, nombre, correo, telefono, borde=None):
        """Tarjeta común de contactos (individuales y Director de empresa):
        avatar circular, nombre y, debajo, correo y teléfono copiables con un
        clic. Devuelve (frame, layout horizontal) para que el llamador agregue
        controles a la derecha (ej. favorito)."""
        frame = QFrame()
        frame.setObjectName("tarjetaContacto")
        frame.setStyleSheet(f"""
            QFrame#tarjetaContacto {{ background-color: {SURFACE}; border: 1px solid {borde or BORDER}; border-radius: 12px; }}
            QFrame#tarjetaContacto:hover {{ border: 1px solid {PRIMARY}; }}
            QFrame#tarjetaContacto QLabel {{ border: none; background: transparent; }}
        """)
        row_layout = QHBoxLayout(frame)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(12)

        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(avatar, 0, Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        lbl_nombre = QLabel(nombre)
        lbl_nombre.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold; font-size: 12px;")
        text_layout.addWidget(lbl_nombre)

        contacto_row = QHBoxLayout()
        contacto_row.setSpacing(4)
        for icono, valor in (('fa5s.envelope', correo), ('fa5s.phone-alt', telefono)):
            if not valor or valor in ('-', 'nan'):
                continue
            icon_lbl = QLabel()
            icon_lbl.setPixmap(ThemeManager.icon_pixmap(icono, color=TEXT_MUTED, size=10))
            lbl_valor = CopyableLabel()
            lbl_valor.setText(valor)
            lbl_valor._copy_value = valor
            contacto_row.addWidget(icon_lbl)
            contacto_row.addWidget(lbl_valor)
            contacto_row.addSpacing(10)
        if contacto_row.count() == 0:
            sin_datos = QLabel("Sin correo ni teléfono")
            sin_datos.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            contacto_row.addWidget(sin_datos)
        contacto_row.addStretch()
        text_layout.addLayout(contacto_row)
        row_layout.addLayout(text_layout, stretch=1)
        return frame, row_layout

    def _switch_detalle_view(self, index):
        for i, btn in enumerate(self._detalle_nav_buttons):
            btn.setChecked(i == index)
        # El alto de la pila lo da solo la pestaña que se está viendo (la tabla de Unidades es la más alta)
        for i in range(self.detalle_stack.count()):
            pagina = self.detalle_stack.widget(i)
            politica = pagina.sizePolicy()
            politica.setVerticalPolicy(QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored)
            pagina.setSizePolicy(politica)
        cambio = self.detalle_stack.currentIndex() != index
        self.detalle_stack.setCurrentIndex(index)
        if cambio:
            self._animar_esqueleto_derecha()
        self._contenedor_filtros_cliente.setVisible(index == 1)
        self.detalle_stack.updateGeometry()
        if index == 1:
            self._iniciar_unidades_cliente()
