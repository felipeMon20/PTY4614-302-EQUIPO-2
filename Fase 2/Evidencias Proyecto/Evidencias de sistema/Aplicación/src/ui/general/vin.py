"""Vistas del detalle de una unidad (VIN) en General: ficha, historial, contratos anteriores y vacíos."""
from src.theme.colors import BACKGROUND, BORDER, DANGER, PRIMARY, SUCCESS, SURFACE, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, WARNING
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QScrollArea, QGridLayout, QProgressBar
from PyQt6.QtCore import Qt
from src.core.constants import COL_RAZON_SOCIAL, COL_RUT, COL_INDUSTRIA, COL_CDB, COL_CDB_FLOTA, COL_VIN, COL_CHASIS, COL_FLOTA_VC, COL_TIPO_SERVICIO, COL_ESTADO_ACTIVACION, COL_EJECUTIVO, COL_ETAPA_GESTION, COL_MODELO, COL_FLOTA_VC_2, COL_FORMA_CONTRATO, COL_ESTADO_COMERCIAL, COL_INICIO_CONTRATO, COL_DURACION_MESES, COL_TERMINO_CONTRATO, COL_PERIODO_INTERNO, COL_ESTADO_ENTREGA, COL_FECHA_BAJA, COL_TIPO_FACTURACION, COL_CONTRATO_JUSTTIME, COL_FECHA_INICIO_FACT, COL_FECHA_TERMINO_FACT, COL_ESTADO_CM, COL_ID
from src.services import comercial_services
from src.ui.compartido.icono_tema import fijar_icono_tema
from src.theme.theme_manager import ThemeManager
from src.services import general_services
from src.ui.general import historial_unidad
from src.ui.general.base import (
    AZUL,
    AZUL_HOVER,
    CopyableLabel,
    CopyableTitulo,
    QSS_CONTENEDOR_PESTANAS_CLARO,
    QSS_PESTANAS_CLARAS,
    TEXTO_SOBRE_AZUL,
    _ContratoAnteriorCard,
    _EnlaceLabel,
    _EtiquetaElidida,
    _StackedWidgetTamañoActual,
    _boton_azul,
    _boton_minimo,
    _calcular_vigencia,
    _con_transicion_derecha,
    _crear_estado_vacio,
    _crear_invitacion,
    _flota_valida,
    _pixmap_wifi_desconectado,
)


class _VinGeneralMixin:
    def _build_cliente_vacio_view(self):
        """Detalle de cliente sin selección: la misma hoja con portada, pero con
        los datos en blanco y una invitación a elegir un cliente."""
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
        icono.setPixmap(ThemeManager.icon_pixmap('fa5s.building', color=TEXTO_SOBRE_AZUL, size=18))
        icono.setStyleSheet("background: rgba(255,255,255,0.08); border: 2px dashed rgba(255,255,255,0.4); border-radius: 20px;")

        titulo = QLabel("Ningún cliente seleccionado")
        titulo.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 18px; font-weight: bold;")
        fila_superior = QHBoxLayout()
        fila_superior.setSpacing(10)
        fila_superior.addWidget(icono)
        fila_superior.addWidget(titulo, 1)
        lay_p.addLayout(fila_superior)
        lay_p.addSpacing(8)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for texto in ("RUT: —", "CDB Comercial: —", "CDB Flota: —"):
            chip = QLabel(texto)
            chip.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; padding: 3px 10px; "
                               "border: 1px solid rgba(255,255,255,0.18); border-radius: 9px; background-color: rgba(255,255,255,0.05);")
            chips.addWidget(chip)
        chips.addStretch()
        lay_p.addLayout(chips)
        lay_p.addStretch(1)

        pestanas = QHBoxLayout()
        pestanas.setSpacing(2)
        for texto in ("Resumen", "Unidades", "Flotas VC", "Contactos"):
            lbl_tab = QLabel(texto)
            lbl_tab.setStyleSheet("color: rgba(201,212,234,0.45); font-size: 13px; padding: 10px 16px;")
            pestanas.addWidget(lbl_tab)
        pestanas.addStretch()
        lay_p.addLayout(pestanas)
        lay_hoja.addWidget(portada)
        self._portadas_unidad = self.__dict__.get('_portadas_unidad', []) + [portada]

        # Las tarjetas KPI bajan de la portada al inicio del contenido
        kpis = QHBoxLayout()
        kpis.setSpacing(8)
        for titulo_k in ("UNIDADES", "VOLVO CONNECT", "CIV", "SAFETY ZONE"):
            card, _ = self._crear_kpi_comercial(titulo_k, "—", "")
            kpis.addWidget(card)
        lay_hoja.addLayout(kpis)
        kpis.setContentsMargins(14, 12, 14, 0)

        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 12, 14, 14)
        cuerpo.addWidget(_crear_invitacion("Presiona un cliente de la lista",
                                           "Aquí verás su información, unidades, flotas y contactos."), 1)
        lay_hoja.addLayout(cuerpo, 1)

        raiz.addWidget(hoja, 1)
        return widget

    # ==========================================
    # CAJA DERECHA: fila de Flota sin CDB asociado a ningún cliente (CDB
    # vacío, "-", o sin match en df_clientes_base). No hay CDB para resolver
    # KPIs/Unidades/Contactos, así que se muestra solo el dato de Flota VC
    # de esa fila; si tampoco hay Flota VC, se indica en rojo que no se
    # encontró información (ver _show_flota_sin_cliente).
    # ==========================================
    def _build_flota_sin_cdb_view(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        lbl_title = QLabel("Sin cliente asociado")
        lbl_title.setStyleSheet("color: white; font-size: 15px; font-weight: bold;")

        lbl_subtitle = QLabel("Esta fila de Flota no tiene un CDB asociado a un cliente, así que no se puede mostrar su detalle completo.")
        lbl_subtitle.setWordWrap(True)
        lbl_subtitle.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px;")

        info_row = QHBoxLayout()
        info_row.setSpacing(6)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap('fa5s.route', color=TEXTO_SOBRE_AZUL, size=11))
        icon_lbl.setFixedWidth(15)
        lbl_label = QLabel("Flota VC")
        lbl_label.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px;")
        self.lbl_flota_sin_cliente_valor = QLabel("")
        self.lbl_flota_sin_cliente_valor.setWordWrap(True)
        self.lbl_flota_sin_cliente_valor.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        info_row.addWidget(icon_lbl)
        info_row.addWidget(lbl_label)
        info_row.addStretch()
        info_row.addWidget(self.lbl_flota_sin_cliente_valor, stretch=1)

        layout.addStretch()
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_subtitle)
        layout.addLayout(info_row)
        layout.addStretch()
        return widget

    # ==========================================
    # CAJA DERECHA: contexto de VIN (caja izquierda -> Unidades). Ficha
    # completa (33 columnas) + Historial del VIN seleccionado, con el mismo
    # patrón visual de pestañas internas que ya usa el detalle de cliente
    # (Resumen/Unidades/Contactos/Historial), pero acotado a estos 2.
    # ==========================================
    def _build_vin_vacio_view(self):
        """Ficha de unidad sin selección: la misma hoja con portada, con los
        datos en blanco y una invitación a elegir una unidad."""
        widget = QWidget()
        raiz = QVBoxLayout(widget)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        hoja = QFrame()
        hoja.setObjectName("hojaUnidad")
        hoja.setStyleSheet(f"QFrame#hojaUnidad {{ background-color: {SURFACE}; border: none; border-radius: 16px; }}")
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

        titulo = QLabel("Ningún contrato")
        titulo.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 16px; font-weight: bold;")
        titulo.setContentsMargins(8, 0, 0, 0)
        sub = QLabel("Sin datos de Volvo Connect")
        sub.setStyleSheet("color: rgba(201,212,234,0.6); font-size: 16px; font-weight: bold;")
        vin = QLabel("VIN —")
        vin.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 18px; font-weight: bold; padding: 1px 8px;")
        bloque_estado = QVBoxLayout()
        bloque_estado.setSpacing(0)
        bloque_estado.addWidget(titulo)
        bloque_estado.addWidget(vin)

        fila_superior = QHBoxLayout()
        fila_superior.setSpacing(10)
        fila_superior.addWidget(icono)
        fila_superior.addLayout(bloque_estado)
        fila_superior.addStretch(1)
        fila_superior.addWidget(sub, 0, Qt.AlignmentFlag.AlignVCenter)
        lay_p.addLayout(fila_superior)
        lay_p.addSpacing(8)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for texto in ("Chasis —", "Modelo —"):
            chip = QLabel(texto)
            chip.setStyleSheet(f"color: {TEXTO_SOBRE_AZUL}; font-size: 11px; font-weight: bold; padding: 3px 11px; "
                               "border-radius: 10px; background-color: rgba(255,255,255,0.08);")
            chips.addWidget(chip)
        chips.addStretch()
        lay_p.addLayout(chips)
        lay_p.addStretch(1)

        pestanas = QHBoxLayout()
        for texto in ("Ficha", "Historial", "Contratos anteriores"):
            lbl_tab = QLabel(texto)
            lbl_tab.setStyleSheet("color: rgba(201,212,234,0.45); font-size: 13px; padding: 10px 16px;")
            pestanas.addWidget(lbl_tab)
        pestanas.addStretch()
        lay_p.addLayout(pestanas)
        lay_hoja.addWidget(portada)
        self._portadas_unidad = self.__dict__.get('_portadas_unidad', []) + [portada]

        cuerpo = QVBoxLayout()
        cuerpo.setContentsMargins(14, 12, 14, 14)
        cuerpo.addWidget(_crear_invitacion("Presiona un contrato de la lista",
                                           "Aquí verás la ficha completa del contrato y su historial."), 1)
        lay_hoja.addLayout(cuerpo, 1)

        raiz.addWidget(hoja, 1)
        return widget

    def _build_vin_detalle_view(self):
        """Detalle de unidad como afiche: una hoja blanca con portada azul
        (estado de Volvo Connect, VIN, chasis y modelo, y las pestañas Ficha/
        Historial) y debajo el contenido de la pestaña activa."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hoja = QFrame()
        hoja.setObjectName("hojaUnidad")
        hoja.setStyleSheet(f"QFrame#hojaUnidad {{ background-color: {SURFACE}; border: none; border-radius: 16px; }}")
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

        # Portada compacta (28-10-2026, a pedido de Javiera): estado de Volvo Connect a la izquierda, VIN a la
        # derecha, chips debajo y pestañas abajo, a la altura de las de la caja izquierda (ver _sincronizar_alto_portadas)
        self._ficha_hero_icono = QLabel()
        self._ficha_hero_icono.setFixedSize(40, 40)
        self._ficha_hero_icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ficha_hero_icono.setStyleSheet(
            "background: rgba(255,255,255,0.12); border: 2px dashed rgba(255,255,255,0.45); border-radius: 20px;")
        self._ficha_hero_titulo = QLabel("")
        self._ficha_hero_titulo.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        self._ficha_hero_titulo.setContentsMargins(9, 0, 0, 0)  # alinea con el VIN, que lleva 8 px de relleno y 1 de borde
        # El nombre de la flota/razón social va a la derecha y el VIN bajo el estado de Volvo Connect
        self._ficha_hero_sub = _EtiquetaElidida("")
        self._ficha_hero_sub.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._ficha_hero_sub.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        self._ficha_alerta = QLabel("")
        self._ficha_alerta.setStyleSheet(
            f"background: {DANGER}; color: white; font-size: 11px; font-weight: bold; padding: 4px 12px; border-radius: 11px;")
        self._ficha_alerta.hide()
        self.lbl_vin_detalle_title = CopyableTitulo("")
        bloque_estado = QVBoxLayout()
        bloque_estado.setSpacing(0)
        bloque_estado.addWidget(self._ficha_hero_titulo)
        bloque_estado.addWidget(self.lbl_vin_detalle_title, 0, Qt.AlignmentFlag.AlignLeft)

        fila_superior = QHBoxLayout()
        fila_superior.setSpacing(10)
        fila_superior.addWidget(self._ficha_hero_icono)
        fila_superior.addLayout(bloque_estado)
        fila_superior.addStretch(1)
        fila_superior.addWidget(self._ficha_alerta)
        fila_superior.addStretch(1)
        fila_superior.addWidget(self._ficha_hero_sub, 0, Qt.AlignmentFlag.AlignVCenter)
        lay_p.addLayout(fila_superior)
        lay_p.addSpacing(8)

        # Se siguen actualizando desde _render_cabecera_vin aunque ya no se muestren aquí
        self.vin_pastillas_layout = QHBoxLayout()
        self.lbl_vin_detalle_rut = CopyableLabel()

        # Chips copiables (28-10-2026, a pedido de Javiera): chasis, flota y los dos CDB; modelo y periodo interno
        # pasaron a la tarjeta Unidad de la ficha
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.lbl_vin_detalle_chasis = CopyableLabel()
        self.lbl_vin_detalle_flota = CopyableLabel()
        self.lbl_vin_detalle_cdb = CopyableLabel()
        self.lbl_vin_detalle_cdb_flota = CopyableLabel()
        for chip in (self.lbl_vin_detalle_chasis, self.lbl_vin_detalle_flota, self.lbl_vin_detalle_cdb,
                     self.lbl_vin_detalle_cdb_flota):
            chip._BASE_STYLE = (f"color: white; font-size: 11px; font-weight: bold; padding: 3px 11px; "
                                "border: none; border-radius: 10px; background-color: rgba(255,255,255,0.16);")
            chip._HOVER_STYLE = (f"color: {AZUL}; font-size: 11px; font-weight: bold; padding: 3px 11px; "
                                 "border: none; border-radius: 10px; background-color: white;")
            chip.setStyleSheet(chip._BASE_STYLE)
            chips.addWidget(chip)
        chips.addStretch()
        lay_p.addLayout(chips)
        lay_p.addStretch(1)

        vin_nav_barra = QFrame()
        vin_nav_barra.setObjectName("barraPestanasGeneral")
        vin_nav_barra.setStyleSheet(QSS_CONTENEDOR_PESTANAS_CLARO)
        vin_nav_layout = QHBoxLayout(vin_nav_barra)
        vin_nav_layout.setContentsMargins(0, 0, 0, 0)
        vin_nav_layout.setSpacing(2)
        self.btn_vin_ficha = QPushButton("Ficha")
        self.btn_vin_historial = QPushButton("Historial")
        self.btn_vin_contratos = QPushButton("Contratos anteriores")
        self._vin_nav_buttons = [self.btn_vin_ficha, self.btn_vin_historial, self.btn_vin_contratos]
        for i, btn in enumerate(self._vin_nav_buttons):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(QSS_PESTANAS_CLARAS)
            btn.clicked.connect(lambda checked, idx=i: self._switch_vin_detalle_view(idx))
            vin_nav_layout.addWidget(btn)
        vin_nav_layout.addStretch()
        self.btn_vin_ficha.setChecked(True)
        lay_p.addWidget(vin_nav_barra)
        lay_hoja.addWidget(portada)
        self._portadas_unidad = self.__dict__.get('_portadas_unidad', []) + [portada]

        self.vin_detalle_stack = _StackedWidgetTamañoActual()
        self.vin_detalle_stack.addWidget(self._build_ficha_vin_view())      # index 0
        self.vin_detalle_stack.addWidget(self._build_historial_vin_view())  # index 1
        self.vin_detalle_stack.addWidget(self._build_contratos_anteriores_view())  # index 2

        # El scroll envuelve el stack: solo la pestaña activa se desplaza
        self.vin_detalle_scroll = QScrollArea()
        self.vin_detalle_scroll.setWidgetResizable(True)
        self.vin_detalle_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.vin_detalle_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.vin_detalle_scroll.viewport().setStyleSheet("background: transparent;")
        self.vin_detalle_scroll.setWidget(self.vin_detalle_stack)
        self.vin_detalle_stack.setStyleSheet("background: transparent;")
        lay_hoja.addWidget(self.vin_detalle_scroll, 1)

        layout.addWidget(hoja, 1)
        return widget

    _FICHA_VIN_TARJETAS = ("Cliente", "Situación de la unidad", "Unidad", "Facturación y CM")

    def _build_ficha_vin_view(self):
        """Ficha de la unidad con formato de afiche: portada con el estado de
        Volvo Connect, vigencia del contrato y tarjetas por tema (cliente,
        situación, unidad, facturación y CM). Se construye una vez con las
        tarjetas vacías; _render_ficha_vin() las repuebla en cada cambio de VIN."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(10)

        self._ficha_aviso_anterior = QFrame()
        self._ficha_aviso_anterior.setObjectName("avisoContratoAnterior")
        self._ficha_aviso_anterior.setStyleSheet(
            f"QFrame#avisoContratoAnterior {{ background-color: #FEF3C7; border: 1px solid #F3D98B; border-radius: 12px; }}"
            "QFrame#avisoContratoAnterior QLabel { border: none; background: transparent; color: #7A5B00; font-size: 11px; font-weight: bold; }")
        lay_aviso = QHBoxLayout(self._ficha_aviso_anterior)
        lay_aviso.setContentsMargins(12, 8, 8, 8)
        self._lbl_aviso_anterior = QLabel("")
        self._lbl_aviso_anterior.setWordWrap(True)
        btn_volver = QPushButton("Ver contrato actual")
        btn_volver.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_minimo(btn_volver)
        btn_volver.clicked.connect(self._volver_a_contrato_actual)
        lay_aviso.addWidget(self._lbl_aviso_anterior, 1)
        lay_aviso.addWidget(btn_volver)
        self._ficha_aviso_anterior.hide()
        layout.addWidget(self._ficha_aviso_anterior)

        self._ficha_contrato_holder = QVBoxLayout()
        self._ficha_contrato_holder.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self._ficha_contrato_holder)

        self._ficha_vin_layouts = {}
        self._ficha_vin_cards = {}
        # Dos columnas (28-10-2026, a pedido de Javiera): Cliente y Situación a la izquierda, el resto a la derecha
        columnas = QHBoxLayout()
        columnas.setSpacing(10)
        columnas_tarjetas = (QVBoxLayout(), QVBoxLayout())
        for columna in columnas_tarjetas:
            columna.setContentsMargins(0, 0, 0, 0)
            columna.setSpacing(10)
            columnas.addLayout(columna, 1)
        layout.addLayout(columnas)
        for posicion, titulo in enumerate(self._FICHA_VIN_TARJETAS):
            tarjeta = QFrame()
            tarjeta.setObjectName("fichaTarjeta")
            tarjeta.setStyleSheet(f"QFrame#fichaTarjeta {{ background: transparent; border: 1px solid {BORDER}; border-radius: 14px; }}"
                                  "QFrame#fichaTarjeta QLabel { border: none; background: transparent; }")
            lay_t = QVBoxLayout(tarjeta)
            lay_t.setContentsMargins(12, 8, 12, 8)
            lay_t.setSpacing(2)
            lbl_t = QLabel(titulo.upper())
            lbl_t.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
            lay_t.addWidget(lbl_t)
            filas = QVBoxLayout()
            filas.setSpacing(0)
            lay_t.addLayout(filas)
            columnas_tarjetas[0 if posicion < 2 else 1].addWidget(tarjeta)
            self._ficha_vin_layouts[titulo] = filas
            self._ficha_vin_cards[titulo] = tarjeta
        for columna in columnas_tarjetas:
            columna.addStretch()

        layout.addStretch()

        self._ficha_cta = QFrame()
        self._ficha_cta.setObjectName("fichaCta")
        self._ficha_cta.setStyleSheet(f"QFrame#fichaCta {{ background-color: #F3F5F9; border: 1px solid {BORDER}; border-radius: 14px; }}"
                                      "QFrame#fichaCta QLabel { border: none; background: transparent; }")
        lay_cta = QHBoxLayout(self._ficha_cta)
        lay_cta.setContentsMargins(14, 10, 14, 10)
        lay_cta.setSpacing(12)
        icono_cta = QLabel()
        fijar_icono_tema(icono_cta, 'fa5s.phone-alt', AZUL, 18)
        texto_cta = QVBoxLayout()
        texto_cta.setSpacing(0)
        lbl_cta1 = QLabel("Ofrécele Volvo Connect")
        lbl_cta1.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        lbl_cta2 = QLabel("Contacta al cliente para activar esta unidad.")
        lbl_cta2.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        lbl_cta2.setWordWrap(True)
        texto_cta.addWidget(lbl_cta1)
        texto_cta.addWidget(lbl_cta2)
        btn_cta = QPushButton("Contactar")
        btn_cta.setCursor(Qt.CursorShape.PointingHandCursor)
        _boton_azul(btn_cta)
        btn_cta.setToolTip("Abre el Gestor de Correos con esta unidad seleccionada")
        btn_cta.clicked.connect(self._contactar_para_ofrecer_vc)
        lay_cta.addWidget(icono_cta)
        lay_cta.addLayout(texto_cta, 1)
        lay_cta.addWidget(btn_cta)
        layout.addWidget(self._ficha_cta)
        return widget

    def _build_historial_vin_view(self):
        """Contenedor del historial (ciclo de vida y cambios por día). Se construye vacío; _render_historial_vin() lo repuebla en cada cambio de VIN."""
        widget = QWidget()
        self.historial_vin_layout = QVBoxLayout(widget)
        self.historial_vin_layout.setContentsMargins(0, 0, 0, 0)
        self.historial_vin_layout.setSpacing(6)
        return widget

    def _build_contratos_anteriores_view(self):
        """Lista de los contratos anteriores del VIN seleccionado; un clic
        muestra su ficha completa en la pestaña Ficha. Se repuebla en cada
        cambio de VIN (_render_contratos_anteriores)."""
        widget = QWidget()
        self.contratos_anteriores_layout = QVBoxLayout(widget)
        self.contratos_anteriores_layout.setContentsMargins(14, 12, 14, 14)
        self.contratos_anteriores_layout.setSpacing(6)
        self._contratos_anteriores_df = pd.DataFrame()
        self._contrato_anterior_mostrado = False
        self._fila_vin_actual = None
        return widget

    def _render_contratos_anteriores(self, df_anteriores):
        self._contratos_anteriores_df = df_anteriores
        layout = self.contratos_anteriores_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        n = len(df_anteriores)
        self.btn_vin_contratos.setText(f"Contratos anteriores ({n})" if n else "Contratos anteriores")
        if df_anteriores.empty:
            layout.addWidget(_crear_estado_vacio(
                'fa5s.file-contract', "Sin contratos anteriores",
                "Esta unidad solo ha tenido un contrato. Si se da de baja y vuelve a contratarse, "
                "los contratos anteriores quedarán listados aquí."), 1)
        else:
            ayuda = QLabel("Elige un contrato para ver su resumen.")
            ayuda.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
            layout.addWidget(ayuda)
            for i in range(n):
                card = _ContratoAnteriorCard(i, df_anteriores.iloc[i])
                card.clicked.connect(self._on_contrato_anterior_clicked)
                layout.addWidget(card)
            layout.addStretch()

    def _obtener_contratos_anteriores(self, vin):
        """Contratos anteriores del VIN, ya procesados igual que la ficha actual."""
        df_todos = self.data_manager.df_master
        anteriores = comercial_services.contratos_anteriores(df_todos, vin)
        if anteriores.empty:
            return anteriores
        return comercial_services.procesar_df_comercial(anteriores.copy())

    def _on_contrato_anterior_clicked(self, indice):
        if indice < 0 or indice >= len(self._contratos_anteriores_df):
            return
        fila = self._contratos_anteriores_df.iloc[indice]
        self._switch_vin_detalle_view(0)
        self._contrato_anterior_mostrado = True
        self._render_cabecera_vin(fila)
        self._render_ficha_vin(fila)
        id_contrato = comercial_services._normalizar_id_contrato(fila.get(COL_ID, ''))
        self._lbl_aviso_anterior.setText(
            f"Contrato anterior{f' N° {id_contrato}' if id_contrato else ''}: es un contrato finalizado de esta unidad.")
        self._ficha_aviso_anterior.show()
        self._ficha_cta.setVisible(False)

    def _volver_a_contrato_actual(self):
        self._contrato_anterior_mostrado = False
        self._ficha_aviso_anterior.hide()
        fila = self._fila_vin_actual
        if fila is not None:
            self._render_cabecera_vin(fila)
            self._render_ficha_vin(fila)

    _formatear_fecha_historial = staticmethod(general_services.formatear_fecha_historial)

    def _switch_vin_detalle_view(self, index):
        if index == 0 and getattr(self, '_contrato_anterior_mostrado', False):
            self._volver_a_contrato_actual()
        for i, btn in enumerate(self._vin_nav_buttons):
            btn.setChecked(i == index)
        cambio = self.vin_detalle_stack.currentIndex() != index
        self.vin_detalle_stack.setCurrentIndex(index)
        if cambio:
            self._animar_esqueleto_derecha()
        # sizeHint/minimumSizeHint de _StackedWidgetTamañoActual cambian con
        # la página actual: sin este aviso explícito, el layout padre (y el
        # QScrollArea que lo envuelve) puede seguir usando el tamaño
        # cacheado de la página anterior hasta el próximo evento de resize.
        self.vin_detalle_stack.updateGeometry()

    _valor_ficha = staticmethod(general_services.valor_ficha)

    def _render_cabecera_vin(self, fila):
        """Pastillas de estado y chips copiables bajo el VIN."""
        v = lambda col: self._valor_ficha(fila, col)
        while self.vin_pastillas_layout.count():
            item = self.vin_pastillas_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def pastilla(texto, fondo, color, borde="none"):
            lbl = QLabel(texto)
            lbl.setStyleSheet(f"background-color: {fondo}; color: {color}; border: {borde}; "
                              "font-size: 10px; font-weight: bold; padding: 3px 10px; border-radius: 10px;")
            return lbl

        if v(COL_PERIODO_INTERNO) != '-':
            self.vin_pastillas_layout.addWidget(pastilla(
                f"Periodo {v(COL_PERIODO_INTERNO)}", BACKGROUND, TEXT_SECONDARY, f"1px solid {BORDER}"))
        self.vin_pastillas_layout.addStretch()

        self.lbl_vin_detalle_chasis.set_value("Chasis", v(COL_CHASIS))
        flota = v(COL_FLOTA_VC)
        self.lbl_vin_detalle_flota.set_texto_copiable("Copiar Flota", flota)
        self.lbl_vin_detalle_flota.setToolTip(f"Copiar la flota: {flota}")
        self.lbl_vin_detalle_flota.setVisible(_flota_valida(flota))
        self.lbl_vin_detalle_cdb.set_value("CDB Comercial", v(COL_CDB))
        self.lbl_vin_detalle_cdb.setVisible(v(COL_CDB) != '-')
        self.lbl_vin_detalle_cdb_flota.set_value("CDB Flota", v(COL_CDB_FLOTA))
        self.lbl_vin_detalle_cdb_flota.setVisible(v(COL_CDB_FLOTA) != '-')
        self.lbl_vin_detalle_rut.set_value("RUT", v(COL_RUT))

    def _crear_celda_ficha(self, etiqueta, valor, al_hacer_clic=None):
        """Celda de la ficha: etiqueta pequeña sobre el valor. Con
        `al_hacer_clic` el valor es un enlace."""
        celda = QWidget()
        celda.setObjectName("celdaInfo")
        celda.setStyleSheet(f"QWidget#celdaInfo {{ border-bottom: 1px solid {BORDER}; }}")
        lay = QVBoxLayout(celda)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(0)
        lbl_label = QLabel(etiqueta)
        lbl_label.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px; border: none; background: transparent;")
        lay.addWidget(lbl_label)
        if al_hacer_clic is not None and valor != '-':
            lbl_valor = _EnlaceLabel(valor)
            lbl_valor.clicked.connect(al_hacer_clic)
        else:
            lbl_valor = QLabel(valor)
            lbl_valor.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;")
        lbl_valor.setWordWrap(True)
        lbl_valor.setMinimumWidth(0)
        lay.addWidget(lbl_valor)
        return celda

    def _contactar_para_ofrecer_vc(self):
        vin = getattr(self, '_vin_seleccionado', None)
        if not vin:
            return
        from src.ui.compartido.mail_dialog import MailDialog
        MailDialog(self, vins_preseleccionados=[vin]).exec()

    def _crear_fila_ficha(self, etiqueta, valor, al_hacer_clic=None):
        """Fila de una tarjeta de la ficha: etiqueta a la izquierda y valor a la derecha."""
        fila = QWidget()
        fila.setObjectName("filaFicha")
        fila.setStyleSheet(f"QWidget#filaFicha {{ border-bottom: 1px dashed {BORDER}; }}")
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(12)
        lbl_e = QLabel(etiqueta)
        lbl_e.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; border: none; background: transparent;")
        if al_hacer_clic is not None:
            lbl_v = _EnlaceLabel(valor)
            lbl_v.clicked.connect(al_hacer_clic)
        else:
            lbl_v = QLabel(valor)
            lbl_v.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none; background: transparent;")
        lbl_v.setWordWrap(True)
        lbl_v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_v.setMinimumWidth(0)
        lay.addWidget(lbl_e, 0)
        lay.addWidget(lbl_v, 1)
        return fila

    def _render_ficha_vin(self, fila):
        v = lambda col: self._valor_ficha(fila, col)
        razon, cdb, flota = v(COL_RAZON_SOCIAL), v(COL_CDB), v(COL_FLOTA_VC)
        sin_vc = not _flota_valida(flota)
        estado_act = v(COL_ESTADO_ACTIVACION)

        # Portada: estado de Volvo Connect
        if sin_vc:
            self._ficha_hero_icono.setPixmap(ThemeManager.icon_pixmap('fa5s.unlink', color='white', size=18))
            self._ficha_hero_titulo.setText("Sin Volvo Connect")
            self._ficha_hero_sub.setText("No aparece en ninguna flota")
        else:
            if estado_act.upper() == 'DESCONECTADO':
                self._ficha_hero_icono.setPixmap(_pixmap_wifi_desconectado(18))
            else:
                self._ficha_hero_icono.setPixmap(ThemeManager.icon_pixmap('fa5s.wifi', color='white', size=18))
            self._ficha_hero_titulo.setText(f"Volvo Connect · {estado_act.capitalize()}" if estado_act != '-' else "Volvo Connect")
            self._ficha_hero_sub.setText(flota)
        self._ficha_cta.setVisible(sin_vc)

        # Alerta: un contrato Vigente no puede estar desconectado (error de datos a corregir)
        urgente = v(COL_ESTADO_COMERCIAL).upper() == 'VIGENTE' and estado_act.upper() == 'DESCONECTADO'
        self._ficha_alerta.setText("ARREGLO URGENTE · Vigente pero desconectado" if urgente else "")
        self._ficha_alerta.setVisible(urgente)

        # Vigencia del contrato (solo si tiene fechas o baja)
        while self._ficha_contrato_holder.count():
            item = self._ficha_contrato_holder.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        tarjeta_vigencia = self._crear_tarjeta_contrato(
            v(COL_INICIO_CONTRATO), v(COL_TERMINO_CONTRATO),
            v(COL_FORMA_CONTRATO), v(COL_TIPO_SERVICIO), v(COL_TIPO_FACTURACION),
            estados=(("Estado comercial", v(COL_ESTADO_COMERCIAL)), ("Estado activación", estado_act),
                     ("Etapa gestión", v(COL_ETAPA_GESTION))),
            baja=v(COL_FECHA_BAJA), solo_vigencia=True, duracion=v(COL_DURACION_MESES))
        if tarjeta_vigencia is not None:
            self._ficha_contrato_holder.addWidget(tarjeta_vigencia)
        # La duración se muestra arriba, junto a las fechas; la tarjeta Unidad la conserva solo si no hay tarjeta de vigencia
        duracion_arriba = tarjeta_vigencia is not None and bool(self._texto_duracion(v(COL_DURACION_MESES)))

        def o_guion(valor, texto):
            return valor if valor != '-' else texto

        # Un contrato en baja siempre muestra su fecha de baja; si no la tiene, lo dice
        en_baja = v(COL_ESTADO_COMERCIAL).upper() in ('BAJA', 'BAJA SOLICITADA')
        fecha_baja = v(COL_FECHA_BAJA) if v(COL_FECHA_BAJA) != '-' else ("Sin fecha registrada" if en_baja else '-')

        # (etiqueta, valor, acción al hacer clic); los "-" no se muestran salvo los estados clave
        tarjetas = {
            "Cliente": [
                ("Razón social", razon, lambda: self._abrir_cliente_desde_unidad(razon, v(COL_RUT))),
                ("Industria", v(COL_INDUSTRIA), None), ("Ejecutivo", v(COL_EJECUTIVO), None), ("RUT", v(COL_RUT), None),
                ("CDB comercial", cdb, None), ("CDB flota", v(COL_CDB_FLOTA), None),
            ],
            "Situación de la unidad": [
                ("N° Contrato", v(COL_ID), None),
                ("Estado comercial", o_guion(v(COL_ESTADO_COMERCIAL), "Sin definir"), None),
                ("Estado de activación", o_guion(estado_act, "Sin definir"), None),
                ("Fecha de baja", fecha_baja, None),
                ("Forma de contrato", o_guion(v(COL_FORMA_CONTRATO), "Sin definir"), None),
                ("Tipo de facturación", o_guion(v(COL_TIPO_FACTURACION), "Sin registro"), None),
                ("Tipo de servicio", v(COL_TIPO_SERVICIO), None),
            ],
            "Unidad": [
                ("Fecha de entrega", v(COL_ESTADO_ENTREGA), None),
                ("Duración (meses)", '-' if duracion_arriba else v(COL_DURACION_MESES), None),
                ("Flota VC", flota, lambda: self._abrir_flota_desde_unidad(cdb, flota, razon, v(COL_RUT))),
                ("Flota VC 2", v(COL_FLOTA_VC_2), None),
                ("Modelo", v(COL_MODELO), None),
                ("Periodo interno", v(COL_PERIODO_INTERNO), None),
            ],
        }
        opcionales = [
            ("Contrato en JustTime", COL_CONTRATO_JUSTTIME),
            ("Inicio facturación", COL_FECHA_INICIO_FACT), ("Término facturación", COL_FECHA_TERMINO_FACT),
            ("N° Contrato 3PC", "N CONTRATO 3PC"), ("Pago CM", "PAGO CM"), ("Tipo de CM", "TIPO DE CM"),
            ("Estado del CM", COL_ESTADO_CM), ("Fecha inicio CM", "FECHA INICIO CM"),
            ("Fecha término CM", "FECHA TERMINO CM"), ("Observaciones", "OBSERVACIONES"),
        ]
        tarjetas["Facturación y CM"] = [(et, v(col), None) for et, col in opcionales]

        for titulo, celdas in tarjetas.items():
            filas = self._ficha_vin_layouts[titulo]
            while filas.count():
                item = filas.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()
            visibles = [c for c in celdas if c[1] != '-' or c[0] == "Razón social"]
            self._ficha_vin_cards[titulo].setVisible(bool(visibles))
            for etiqueta, valor, accion in visibles:
                filas.addWidget(self._crear_fila_ficha(etiqueta, valor, accion if valor != '-' else None))

    @staticmethod
    def _texto_duracion(duracion):
        """'6' -> '6 meses'; vacío o '-' -> ''. Un texto no numérico se muestra tal cual."""
        texto = str(duracion).strip()
        if texto in ('', '-') or texto.lower() == 'nan':
            return ''
        try:
            meses = int(float(texto.replace(',', '.')))
        except ValueError:
            return texto
        return f"{meses} mes" if meses == 1 else f"{meses} meses"

    def _crear_tarjeta_contrato(self, inicio, termino, forma, servicio, facturacion, estados=(), baja=None, solo_vigencia=False,
                                duracion=''):
        """Tarjeta de vigencia del contrato: fechas (con la duración entre
        el inicio y el término), barra de avance y leyenda (rojo si venció),
        con forma de contrato, servicio y facturación al pie."""
        estados_dict = {k: str(v).strip().upper() for k, v in estados}
        finalizado = (estados_dict.get("Estado comercial") in ('BAJA', 'BAJA SOLICITADA')
                      and estados_dict.get("Estado activación") == 'DESCONECTADO')
        vig = _calcular_vigencia(inicio, termino, baja=baja, finalizado=finalizado)
        color = {'vencido': DANGER, 'vigente': SUCCESS, 'baja': DANGER, 'baja_prog': WARNING}.get(vig['estado'], TEXT_SECONDARY)

        sin_fechas = str(inicio).strip() in ('-', '') and str(termino).strip() in ('-', '') and not vig['baja']
        if solo_vigencia and sin_fechas:
            return None

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaContratoVin")
        tarjeta.setStyleSheet(f"QFrame#tarjetaContratoVin {{ background-color: #F7F9FC; border: 1px solid {BORDER}; border-radius: 14px; }}"
                              "QFrame#tarjetaContratoVin QLabel { border: none; background: transparent; }")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(14, 10, 14, 0)
        lay.setSpacing(6)

        fechas = QHBoxLayout()
        columnas_fecha = [("Inicio", vig['inicio'], Qt.AlignmentFlag.AlignLeft, False)]
        texto_duracion = self._texto_duracion(duracion)
        if texto_duracion:
            columnas_fecha.append(("Duración", texto_duracion, Qt.AlignmentFlag.AlignHCenter, False))
        if vig['baja']:
            columnas_fecha.append(("Baja", vig['baja'], Qt.AlignmentFlag.AlignHCenter, True))
        columnas_fecha.append(("Término", vig['termino'], Qt.AlignmentFlag.AlignRight, not vig['baja']))
        for etiqueta, valor, alinear, destacar in columnas_fecha:
            col = QVBoxLayout()
            col.setSpacing(0)
            lbl_e = QLabel(etiqueta)
            lbl_e.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
            lbl_v = QLabel(valor)
            lbl_v.setStyleSheet(f"color: {color if destacar and vig['estado'] in ('vencido', 'baja', 'baja_prog') else TEXT_PRIMARY}; font-size: 14px; font-weight: bold;")
            col.addWidget(lbl_e, 0, alinear)
            col.addWidget(lbl_v, 0, alinear)
            fechas.addLayout(col)
            if etiqueta != "Término":
                fechas.addStretch()
        if not sin_fechas:
            lay.addLayout(fechas)

        if vig['progreso'] is not None and not sin_fechas:
            barra = QProgressBar()
            barra.setRange(0, 100)
            barra.setValue(vig['progreso'])
            barra.setTextVisible(False)
            barra.setFixedHeight(8)
            barra.setStyleSheet(f"QProgressBar {{ background-color: {BORDER}; border: none; border-radius: 4px; }}"
                                f"QProgressBar::chunk {{ background-color: {color}; border-radius: 4px; }}")
            lay.addWidget(barra)
        if vig['texto'] and not sin_fechas:
            lbl_estado = QLabel(vig['texto'])
            lbl_estado.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold;")
            lay.addWidget(lbl_estado)

        if solo_vigencia:
            lay.setContentsMargins(14, 10, 14, 12)
            return tarjeta

        pie = QFrame()
        pie.setStyleSheet("QFrame { background: transparent; border: none; }" if sin_fechas else
                          f"QFrame {{ background: transparent; border: none; border-top: 1px solid {BORDER}; }}")
        pie_lay = QGridLayout(pie)
        pie_lay.setContentsMargins(0, 0, 0, 0)
        pie_lay.setHorizontalSpacing(0)
        pie_lay.setVerticalSpacing(0)
        celdas_pie = [("Contrato", forma), ("Servicio", servicio), ("Facturación", facturacion)] + list(estados)
        for i, (etiqueta, valor) in enumerate(celdas_pie):
            col = QVBoxLayout()
            col.setContentsMargins(14, 7, 8, 7)
            col.setSpacing(0)
            lbl_e = QLabel(etiqueta.upper())
            lbl_e.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 9px; font-weight: bold; letter-spacing: 1px; border: none;")
            lbl_v = QLabel(valor)
            lbl_v.setWordWrap(True)
            lbl_v.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold; border: none;")
            col.addWidget(lbl_e)
            col.addWidget(lbl_v)
            pie_lay.addLayout(col, i // 3, i % 3)
        for c in range(3):
            pie_lay.setColumnStretch(c, 1)
        lay.addSpacing(2)
        lay.addWidget(pie)
        lay.setContentsMargins(14, 10, 14, 4)
        return tarjeta

    def _render_historial_vin(self, df_eventos):
        """Ciclo de vida (activación, conexión y baja) arriba y, debajo, los cambios agrupados por día y por guardado."""
        layout = self.historial_vin_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(16)

        datos = general_services.construir_historial_unidad(df_eventos, getattr(self, '_fila_vin_actual', None))
        layout.addWidget(historial_unidad.crear_ciclo_vida(datos))
        if not datos['dias']:
            layout.addWidget(_crear_estado_vacio(
                'fa5s.history', "Sin historial registrado",
                "Todavía no hay cambios guardados para este VIN. Cada cambio que se guarde sobre la unidad aparecerá aquí."))
            layout.addStretch()
            return
        n = datos['n_cambios']
        layout.addWidget(historial_unidad.titulo_seccion(
            "Historial", f"{datos['n_guardados']} {'guardado' if datos['n_guardados'] == 1 else 'guardados'} · {n} {'cambio' if n == 1 else 'cambios'}"))
        for dia in datos['dias']:
            layout.addWidget(historial_unidad.crear_dia(dia, self.vin_detalle_stack.updateGeometry))
        layout.addStretch()

    _filtrar_historial_por_vin = staticmethod(general_services.filtrar_historial_por_vin)

    def _eventos_historial_de_vin(self, vin):
        """Registros de LogApp de la unidad: los guardados con su VIN y los que Comercial guarda con el ID de cada contrato."""
        ids = general_services.ids_contrato_de_vin(self.data_manager.df_master, vin)
        return self._filtrar_historial_por_vin(self.data_manager.get_logs_df(), vin, ids)

    def _foto_caja_derecha(self):
        """True si la caja derecha está a la vista y vale la pena animarla."""
        return self.right_stack.isVisible() and self.right_stack.width() >= 50

    def _animar_caja_derecha(self, animar):
        if animar:
            self._animar_esqueleto_derecha()

    @_con_transicion_derecha
    def _show_vin_vacio(self):
        if self.left_stack.currentIndex() == 1:
            self.right_stack.setCurrentIndex(3)

    @_con_transicion_derecha
    def _show_vin_detalle(self, vin):
        """VIN seleccionado -> fila completa (33 columnas) desde
        df_comercial_raw -> repuebla ficha + historial. Único punto de
        entrada para ambos paneles: así quedan siempre sincronizados con el
        mismo VIN (ver _vin_seleccionado)."""
        fila = None
        if COL_VIN in self.df_comercial_raw.columns:
            coincidencias = self.df_comercial_raw[
                self.df_comercial_raw[COL_VIN].astype(str).str.strip().str.upper() == str(vin).strip().upper()
            ]
            if not coincidencias.empty:
                fila = coincidencias.iloc[0]

        if fila is None:
            # El VIN seleccionado ya no existe en los datos actuales (ej.
            # tras un refresh que lo eliminó): se limpia la selección en vez
            # de mostrar una ficha con datos viejos/inconsistentes.
            self._vin_seleccionado = None
            self._show_vin_vacio()
            return

        self.lbl_vin_detalle_title.set_value("VIN", vin)
        self._fila_vin_actual = fila
        self._contrato_anterior_mostrado = False
        self._ficha_aviso_anterior.hide()
        self._render_cabecera_vin(fila)
        self._render_ficha_vin(fila)
        self._render_historial_vin(self._eventos_historial_de_vin(vin))
        self._render_contratos_anteriores(self._obtener_contratos_anteriores(vin))

        if self.left_stack.currentIndex() == 1:
            self.right_stack.setCurrentIndex(4)
            self._switch_vin_detalle_view(self.vin_detalle_stack.currentIndex())  # mantiene la pestaña al elegir otro contrato
