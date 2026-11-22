"""Tarjetas y filas de clientes, flotas y unidades de General, con su paleta de estados."""
from src.theme.colors import BACKGROUND, BORDER, DANGER, PRIMARY, SURFACE, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, VOLVO_BLUE, WARNING
from src.ui.compartido.icono_tema import fijar_icono_tema
import html
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QGridLayout, QSizePolicy
from PyQt6.QtCore import Qt, QSize, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from src.core.constants import COL_TIPO_SERVICIO, COL_FORMA_CONTRATO, COL_ESTADO_COMERCIAL, COL_INICIO_CONTRATO, COL_TERMINO_CONTRATO, COL_FECHA_BAJA, COL_ID, FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ
from src.core.dataframe_formatter import DataFrameFormatter
from src.services import comercial_services
from src.theme import tema as _tema
from src.theme.theme_manager import ThemeManager
from src.services import general_services
from src.ui.general.constantes import (
    AZUL,
    COLOR_CDB_FLOTA_MINORITARIO,
    ESTADO_ACTIVACION_COLORES,
    LINEA_AZUL,
    TINTE_CLARO,
    _fijar_ancho_chip,
    _flota_valida,
    _mes_anio,
)
from src.ui.general.etiquetas import (
    _EnlaceLabel,
    _EtiquetaDosLineas,
    _EtiquetaElidida,
)


class GeneralClienteCard(QFrame):
    """Tarjeta clickeable de un cliente (caja izquierda -> Cliente), mismo
    lenguaje visual que EmpresaCard/ClienteCard de Contratos/Provisiones.
    row_idx es la posición (0-based) de esta fila en
    GeneralModule._df_clientes_visible en el momento del render. Sin
    QGraphicsDropShadowEffect a propósito (lección de rendimiento de
    provisiones.py: puede haber varios cientos de clientes)."""

    clicked = pyqtSignal(int)

    def __init__(self, row_idx, razon_social, rut, cdb, industria, total_unidades, parent=None, duplicado=False,
                 total_flotas=0, aviso_flota=""):
        super().__init__(parent)
        self.row_idx = row_idx
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("general_cliente_card")
        accent = AZUL
        # Estilos en QSS_TARJETAS_CLIENTE, aplicado una sola vez en el
        # contenedor: 5 setStyleSheet por tarjeta costaban segundos con 200.
        # Duplicado (RUT+CDB repetido, ver _calcular_claves_duplicadas_rut_cdb)
        # se marca en rojo, igual que GeneralFlotaCard con Flota VC vacío.
        self.setProperty("duplicado", bool(duplicado))
        self.setProperty("seleccionado", False)

        # Se reparte en 3 columnas (_GrillaTarjetas): ancho ignorado para que
        # el nombre largo no ensanche su columna
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        fila_nombre = QHBoxLayout()
        fila_nombre.setSpacing(7)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(ThemeManager.icon_pixmap(
            'fa5s.exclamation-triangle' if duplicado else 'fa5s.building',
            color=(DANGER if duplicado else accent), size=14,
        ))
        icon_lbl.setFixedWidth(16)
        fila_nombre.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)
        if duplicado:
            self.setToolTip("Este RUT tiene más de una razón social (ver pestaña 'Razones sociales' al seleccionarlo).")

        nombre = str(razon_social).strip() or "Sin razón social"
        lbl_nombre = _EtiquetaDosLineas(nombre)
        lbl_nombre.setObjectName("gc_nombre")
        fila_nombre.addWidget(lbl_nombre, 1)

        if aviso_flota:
            icono_aviso = QLabel()
            icono_aviso.setPixmap(ThemeManager.icon_pixmap('fa5s.exclamation-circle', color=WARNING, size=14))
            icono_aviso.setToolTip(aviso_flota)
            fila_nombre.addWidget(icono_aviso, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(fila_nombre)
        layout.addStretch(1)

        sub_partes = []
        rut_str = str(rut).strip()
        if rut_str and rut_str.lower() != 'nan':
            sub_partes.append(f"RUT {rut_str}")
        cdb_str = str(cdb).strip()
        if cdb_str and cdb_str.lower() not in ('nan', '-', ''):
            sub_partes.append(f"CDB {cdb_str}")
        ind_str = str(industria).strip()
        detalle = "  •  ".join(sub_partes) if sub_partes else "Sin datos adicionales"
        self.lbl_sub = _EtiquetaElidida(detalle)
        self.lbl_sub.setObjectName("gc_sub")
        if ind_str and ind_str.lower() != 'nan':
            self.lbl_sub.setToolTip(f"{detalle}  •  {ind_str}")

        fila_datos = QHBoxLayout()
        fila_datos.setSpacing(4)
        fila_datos.addWidget(self.lbl_sub, 1)
        plural = "unidad" if total_unidades == 1 else "unidades"
        badge = QLabel(f"{total_unidades} {plural}")
        badge.setObjectName("gc_badge")
        _fijar_ancho_chip(badge, "9999 unidades")
        fila_datos.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        if total_flotas:
            badge_flotas = QLabel(f"{total_flotas} {'flota' if total_flotas == 1 else 'flotas'}")
            badge_flotas.setStyleSheet(f"background-color: {VOLVO_BLUE}; color: white; font-size: 9px; "
                                       "font-weight: bold; padding: 3px 8px; border-radius: 8px;")
        else:
            badge_flotas = QLabel("Sin flota")
            badge_flotas.setStyleSheet("background-color: #F1F4F9; color: #66748D; font-size: 9px; "
                                       "font-weight: bold; padding: 3px 8px; border-radius: 8px;")
        _fijar_ancho_chip(badge_flotas, "999 flotas", "Sin flota")
        fila_datos.addWidget(badge_flotas, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(fila_datos)

    def set_selected(self, selected):
        self.setProperty("seleccionado", bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row_idx)
        super().mousePressEvent(event)


class GeneralDuplicadoCard(QFrame):
    """Fila de una razón social de un cliente con varias (caja derecha ->
    pestaña Razones sociales): nombre, cantidad de unidades y, para la más
    usada, la etiqueta "Principal". Al hacer clic se despliegan sus unidades
    (`unidades`: lista de (VIN, chasis, estado de activación, estado comercial))."""

    _MAX_UNIDADES_VISIBLES = 200

    def __init__(self, razon_social, total_unidades, principal=False, parent=None, unidades=None, al_abrir_unidad=None):
        super().__init__(parent)
        self._razon_social = str(razon_social).strip()
        self._unidades = unidades or []
        self._al_abrir_unidad = al_abrir_unidad
        self._detalle = None
        self.setObjectName("general_duplicado_card")
        self.setStyleSheet(f"""
            QFrame#general_duplicado_card {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
            QFrame#general_duplicado_card QLabel {{ border: none; background: transparent; }}
            QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
        """)
        if self._unidades:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Clic para ver las unidades de esta razón social")

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(14, 10, 14, 10)
        raiz.setSpacing(8)
        layout = QHBoxLayout()
        layout.setSpacing(10)
        raiz.addLayout(layout)
        self._flecha = QLabel("▸")
        self._flecha.setStyleSheet(f"font-size: 11px; color: {TEXT_MUTED};")
        layout.addWidget(self._flecha, 0, Qt.AlignmentFlag.AlignVCenter)
        self._flecha.setVisible(bool(self._unidades))

        lbl_nombre = QLabel(self._razon_social or "Sin razón social")
        lbl_nombre.setWordWrap(True)
        lbl_nombre.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY};")
        layout.addWidget(lbl_nombre, 1)

        if principal:
            etiqueta = QLabel("Principal")
            etiqueta.setStyleSheet(f"background-color: {VOLVO_BLUE}; color: white; font-size: 10px; "
                                   "font-weight: bold; padding: 4px 10px; border-radius: 10px;")
            layout.addWidget(etiqueta, 0, Qt.AlignmentFlag.AlignVCenter)

        plural = "unidad" if total_unidades == 1 else "unidades"
        badge = QLabel(f"{total_unidades} {plural}")
        badge.setStyleSheet(f"background-color: {AZUL}; color: white; font-size: 10px; "
                            "font-weight: bold; padding: 4px 10px; border-radius: 10px;")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def _crear_detalle(self):
        detalle = QWidget()
        lay = QVBoxLayout(detalle)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        linea = QFrame()
        linea.setFixedHeight(1)
        linea.setStyleSheet(f"background-color: {BORDER}; border: none;")
        lay.addWidget(linea)
        for vin, chasis, activacion, comercial in self._unidades[:self._MAX_UNIDADES_VISIBLES]:
            fila = QWidget()
            fila_lay = QHBoxLayout(fila)
            fila_lay.setContentsMargins(0, 5, 0, 5)
            fila_lay.setSpacing(10)
            if self._al_abrir_unidad is not None:
                lbl_vin = _EnlaceLabel(vin)
                lbl_vin._base = f"color: {PRIMARY}; font-size: 11px; font-weight: bold; border: none; background: transparent;"
                lbl_vin.setStyleSheet(lbl_vin._base)
                lbl_vin.setToolTip("Clic para ver la unidad en Unidades")
                lbl_vin.clicked.connect(lambda v=vin: self._al_abrir_unidad(v))
            else:
                lbl_vin = QLabel(vin)
                lbl_vin.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {TEXT_PRIMARY};")
            lbl_chasis = QLabel(f"Chasis {chasis}")
            lbl_chasis.setStyleSheet(f"font-size: 10px; color: {TEXT_SECONDARY};")
            estados = " · ".join(e for e in (comercial, activacion) if e and e != '-')
            lbl_estado = QLabel(estados)
            lbl_estado.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
            lbl_estado.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            fila_lay.addWidget(lbl_vin)
            fila_lay.addWidget(lbl_chasis)
            fila_lay.addStretch(1)
            fila_lay.addWidget(lbl_estado)
            lay.addWidget(fila)
        restantes = len(self._unidades) - self._MAX_UNIDADES_VISIBLES
        if restantes > 0:
            mas = QLabel(f"y {restantes} unidades más (ver la pestaña Unidades)")
            mas.setStyleSheet(f"font-size: 10px; color: {TEXT_MUTED};")
            lay.addWidget(mas)
        return detalle

    def mousePressEvent(self, event):
        sobre_enlace = isinstance(self.childAt(event.position().toPoint()), _EnlaceLabel)
        if event.button() == Qt.MouseButton.LeftButton and self._unidades and not sobre_enlace:
            if self._detalle is None:
                self._detalle = self._crear_detalle()
                self.layout().addWidget(self._detalle)
                self._detalle.hide()
            abrir = self._detalle.isHidden()
            self._detalle.setVisible(abrir)
            self._flecha.setText("▾" if abrir else "▸")
        super().mousePressEvent(event)


_PAL_VERDE = ('#D1FAE5', '#065F46')


_PAL_AMARILLO = ('#FEF3C7', '#92400E')


_PAL_ROJO = ('#FEE2E2', '#C41919')


_PAL_GRIS = ('#F1F4F9', '#66748D')


_PAL_NARANJA = ('#FFEDD5', '#C2410C')


# Gris de las tarjetas de Contratos: en el tema oscuro pasa a casi blanco (ver _MAPA_TEXTO en tema.py)
GRIS_TARJETA = '#667489'


def _color_estado_comercial(valor):
    v = str(valor).strip().upper()
    if v == 'VIGENTE':
        return _PAL_VERDE
    if v in ('ACTIVACIÓN PENDIENTE', 'ACTIVACION PENDIENTE'):
        return _PAL_AMARILLO
    if v in ('BAJA', 'VENCIDO', 'BAJA SOLICITADA'):
        return _PAL_ROJO
    return _PAL_GRIS


def _color_estado_activacion(valor):
    v = str(valor).strip().upper()
    if v == 'CONECTADO':
        return _PAL_VERDE
    if v == 'ACTIVANDO':
        return _PAL_AMARILLO
    if v == 'DESCONECTADO':
        return _PAL_ROJO
    return _PAL_GRIS


def _color_forma_facturacion(forma, tipo_facturacion):
    """Verde si la combinación cumple la matriz de negocio, rojo si no;
    gris cuando no hay nada que validar (sin asignar o forma desconocida)."""
    validos = FORMA_CONTRATO_TIPO_FACTURACION_MATRIZ.get(str(forma).strip().upper())
    tf = str(tipo_facturacion).strip().upper()
    if validos is None or tf in ('', '-', 'NAN'):
        return _PAL_GRIS
    return _PAL_VERDE if tf in validos else _PAL_ROJO


def _es_sin_vc(estado_comercial, estado_activacion, forma_contrato, tipo_facturacion):
    """Unidad sin Volvo Connect: estado comercial vacío, '-' o SIN SERVICIO,
    activación NO APLICA, forma de contrato SIN CONTRATO y facturación SIN
    REGISTRO."""
    norm = lambda x: str(x).strip().upper()
    return (norm(estado_comercial) in ('', '-', 'SIN SERVICIO', 'NAN', 'NONE', '<NA>')
            and norm(estado_activacion) == 'NO APLICA'
            and norm(forma_contrato) == 'SIN CONTRATO'
            and norm(tipo_facturacion) == 'SIN REGISTRO')


def _crear_pildora(texto, colores, etiqueta=None, tooltip=None, chip=False):
    """Píldora de color (fondo, texto) con etiqueta opcional en tono apagado.
    Con `chip` queda como chip neutro (borde y fondo claros) y solo el valor
    lleva el color del estado."""
    fondo, tinta = colores
    html = str(texto).replace('&', '&amp;').replace('<', '&lt;')
    if chip:
        html = f"<span style='color:{tinta};'>{html}</span>"
    if etiqueta:
        color_et = f" color:{TEXT_SECONDARY};" if chip else ""
        html = f"<span style='font-weight:normal;{color_et}'>{etiqueta}</span> {html}"
    lbl = QLabel(html)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    if tooltip:
        lbl.setToolTip(f"{tooltip}: {texto}")
    if chip:
        lbl.setStyleSheet(f"background-color: #F7F9FC; color: {tinta}; border: 1px solid {BORDER}; "
                          "font-size: 10px; font-weight: bold; padding: 1px 7px; border-radius: 9px;")
        return lbl
    lbl.setStyleSheet(f"background-color: {fondo}; color: {tinta}; border: 1px solid {fondo}; "
                      "font-size: 9px; font-weight: bold; padding: 1px 7px; border-radius: 9px;")
    return lbl


class GeneralUnidadFila(QFrame):
    """Fila de una unidad en la caja derecha -> detalle de cliente ->
    Unidades. Un clic la resalta; doble clic pide abrirla en la pestaña
    Unidades de la caja izquierda."""

    seleccionada = pyqtSignal(str)
    abrir = pyqtSignal(str)

    def __init__(self, vin, chasis, flota_vc, estado_activacion, parent=None, cdb_flota="", cdb_principal=""):
        super().__init__(parent)
        self._vin = str(vin).strip()
        self.setObjectName("unidad_fila")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Doble clic para abrir la unidad en Unidades")
        self.setProperty("seleccionado", False)
        accent = AZUL
        self.setStyleSheet(f"""
            QFrame#unidad_fila {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
            QFrame#unidad_fila:hover {{ border: 1px solid {accent}; }}
            QFrame#unidad_fila[seleccionado="true"] {{ background-color: #F3F5F9; border: 2px solid {accent}; }}
            QFrame#unidad_fila QLabel {{ border: none; background: transparent; }}
            QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        ids = QVBoxLayout()
        ids.setSpacing(1)
        lbl_vin = QLabel(self._vin or "-")
        lbl_vin.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        chasis_txt = str(chasis).strip()
        lbl_chasis = QLabel(f"Chasis {chasis_txt}" if chasis_txt and chasis_txt.lower() != 'nan' else "Sin chasis")
        lbl_chasis.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 10px;")
        ids.addWidget(lbl_vin)
        ids.addWidget(lbl_chasis)
        layout.addLayout(ids)

        flota_txt = str(flota_vc).strip() if _flota_valida(flota_vc) else "Sin flota"
        lbl_flota = _EtiquetaElidida(flota_txt)
        lbl_flota.setStyleSheet(f"color: {TEXT_SECONDARY if _flota_valida(flota_vc) else TEXT_MUTED}; font-size: 11px;")
        columna_flota = QVBoxLayout()
        columna_flota.setSpacing(1)
        columna_flota.addWidget(lbl_flota)
        cdb_txt = str(cdb_flota).strip()
        if cdb_txt.lower() in ('nan', 'none', '-'):
            cdb_txt = ""
        if cdb_principal:
            # El CDB flota con más unidades del cliente va en negro; los demás, en naranja
            es_principal = cdb_txt == cdb_principal
            lbl_cdb = QLabel(f"CDB flota {cdb_txt}" if cdb_txt else "Sin CDB flota")
            lbl_cdb.setStyleSheet(
                f"color: {TEXT_PRIMARY if es_principal else COLOR_CDB_FLOTA_MINORITARIO}; font-size: 10px; font-weight: bold;")
            if not es_principal:
                lbl_cdb.setToolTip(f"Distinto al CDB flota más frecuente de este cliente ({cdb_principal})")
            columna_flota.addWidget(lbl_cdb)
        layout.addLayout(columna_flota, 1)

        estado = str(estado_activacion).strip()
        colores = ESTADO_ACTIVACION_COLORES.get(estado.upper())
        badge = QLabel(estado or "-")
        if colores:
            badge.setStyleSheet(f"background-color: {colores[0]}; color: {colores[1]}; font-size: 9px; font-weight: bold; padding: 3px 8px; border-radius: 8px;")
        else:
            badge.setStyleSheet(f"background-color: {BACKGROUND}; color: {TEXT_SECONDARY}; border: 1px solid {BORDER}; font-size: 9px; font-weight: bold; padding: 3px 8px; border-radius: 8px;")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected):
        _repulir_seleccion(self, selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.seleccionada.emit(self._vin)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._vin:
            self.abrir.emit(self._vin)
        super().mouseDoubleClickEvent(event)


def _repulir_seleccion(card, selected):
    card.setProperty("seleccionado", bool(selected))
    card.style().unpolish(card)
    card.style().polish(card)
    card.update()


class GeneralFlotaFila(QFrame):
    """Fila de una flota VC en la caja derecha -> detalle de cliente -> Flotas
    VC: nombre y cantidad de unidades. Mismo estilo que GeneralUnidadFila."""

    seleccionada = pyqtSignal(str)

    def __init__(self, flota, total_unidades, cdb_flota="", parent=None):
        super().__init__(parent)
        self._flota = str(flota).strip()
        self.setObjectName("flota_fila")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("seleccionado", False)
        accent = AZUL
        self.setStyleSheet(f"""
            QFrame#flota_fila {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
            QFrame#flota_fila:hover {{ border: 1px solid {accent}; }}
            QFrame#flota_fila[seleccionado="true"] {{ background-color: #F3F5F9; border: 2px solid {accent}; }}
            QFrame#flota_fila QLabel {{ border: none; background: transparent; }}
            QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        lbl_nombre = _EtiquetaElidida(self._flota)
        lbl_nombre.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(lbl_nombre)
        lbl_cdb = QLabel(f"CDB flota: {cdb_flota}" if cdb_flota else "CDB flota: -")
        lbl_cdb.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
        lbl_cdb.setToolTip("CDB flota de las unidades de esta flota VC")
        textos.addWidget(lbl_cdb)
        layout.addLayout(textos, 1)

        plural = "unidad" if total_unidades == 1 else "unidades"
        badge = QLabel(f"{total_unidades} {plural}")
        badge.setStyleSheet(f"background-color: {AZUL}; color: white; font-size: 10px; font-weight: bold; "
                            "padding: 4px 10px; border-radius: 10px;")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected):
        _repulir_seleccion(self, selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.seleccionada.emit(self._flota)
        super().mousePressEvent(event)


class _ContratoAnteriorCard(QFrame):
    """Tarjeta clickeable de un contrato anterior de la unidad seleccionada
    (caja derecha -> Unidades -> Contratos anteriores). `indice` es la posición
    en GeneralModule._contratos_anteriores_df."""

    clicked = pyqtSignal(int)

    def __init__(self, indice, fila, parent=None):
        super().__init__(parent)
        self.indice = indice
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("contratoAnteriorCard")
        self.setStyleSheet(
            f"QFrame#contratoAnteriorCard {{ background-color: #F7F9FC; border: 1px solid {BORDER}; border-radius: 12px; }}"
            f"QFrame#contratoAnteriorCard:hover {{ background-color: {TINTE_CLARO}; border: 1px solid {LINEA_AZUL}; }}"
            "QFrame#contratoAnteriorCard QLabel { border: none; background: transparent; }")
        v = lambda col: general_services.valor_ficha(fila, col)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(3)

        arriba = QHBoxLayout()
        id_contrato = comercial_services._normalizar_id_contrato(fila.get(COL_ID, ''))
        lbl_id = QLabel(f"N° Contrato {id_contrato}" if id_contrato else "Contrato sin N°")
        lbl_id.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: bold;")
        arriba.addWidget(lbl_id)
        arriba.addStretch(1)
        estado = v(COL_ESTADO_COMERCIAL)
        if estado != '-':
            lbl_estado = QLabel(estado.capitalize())
            lbl_estado.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px; font-weight: bold; padding: 2px 9px; "
                                     f"border: 1px solid {BORDER}; border-radius: 9px; background-color: {SURFACE};")
            arriba.addWidget(lbl_estado)
        lay.addLayout(arriba)

        detalle = [t for t in (v(COL_FORMA_CONTRATO), v(COL_TIPO_SERVICIO)) if t != '-']
        if detalle:
            lbl_detalle = QLabel(" · ".join(detalle))
            lbl_detalle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
            lay.addWidget(lbl_detalle)
        fechas = [f"Inicio {v(COL_INICIO_CONTRATO)}", f"Término {v(COL_TERMINO_CONTRATO)}"]
        if v(COL_FECHA_BAJA) != '-':
            fechas.append(f"Baja {v(COL_FECHA_BAJA)}")
        lbl_fechas = QLabel(" · ".join(fechas))
        lbl_fechas.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        lay.addWidget(lbl_fechas)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.indice)
        super().mousePressEvent(event)


class _PildoraDato(QFrame):
    """Dato 'etiqueta valor' de alto fijo. Con `relleno` toda la píldora lleva el color
    del estado; si no, es un chip neutro con borde y solo el valor lleva color; con
    `texto` no hay fondo ni borde (solo texto, con un punto de color opcional). Etiqueta y
    valor son QLabel con hoja de estilo, así el tema oscuro los convierte solo. Si no
    cabe, quita la etiqueta y después acorta el valor."""

    ALTO = 18

    def __init__(self, etiqueta, valor, colores, tooltip="", relleno=True, texto=False, punto=None, parent=None):
        super().__init__(parent)
        self._etiqueta = str(etiqueta)
        self._valor = str(valor)
        self._ultimo_ancho = -1
        self._pad = 4 if texto else 22  # relleno lateral y borde
        self._punto = 12 if punto else 0
        fondo, tinta = colores
        self._normal = QFont()
        self._normal.setPixelSize(11 if texto else 10)
        self._negrita = QFont(self._normal)
        self._negrita.setBold(True)
        self.setObjectName("pildora_dato")
        if texto:
            fondo_css, borde_css, color_etiqueta = "transparent", "transparent", GRIS_TARJETA
        elif relleno:
            fondo_css, borde_css, color_etiqueta = fondo, fondo, tinta
        else:
            fondo_css, borde_css, color_etiqueta = "#F7F9FC", BORDER, GRIS_TARJETA
        self.setStyleSheet(f"QFrame#pildora_dato {{ background-color: {fondo_css}; border: 1px solid {borde_css}; "
                           f"border-radius: {self.ALTO // 2}px; }} QLabel {{ background: transparent; border: none; "
                           f"font-size: {self._normal.pixelSize()}px; }}")
        self.setFixedHeight(self.ALTO)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        margen = 2 if texto else 10
        lay.setContentsMargins(margen, 0, margen, 0)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignLeft if texto else Qt.AlignmentFlag.AlignCenter)
        if punto:
            marca = QLabel(self)
            marca.setFixedSize(8, 8)
            marca.setStyleSheet(f"background-color: {punto}; border-radius: 4px;")
            lay.addWidget(marca, 0, Qt.AlignmentFlag.AlignVCenter)
        self._lbl_etiqueta = QLabel(self._etiqueta, self)
        self._lbl_etiqueta.setStyleSheet(f"color: {color_etiqueta}; font-weight: normal;")
        self._lbl_valor = QLabel(self._valor, self)
        self._lbl_valor.setStyleSheet(f"color: {tinta}; font-weight: bold;")
        for lbl in (self._lbl_etiqueta, self._lbl_valor):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._lbl_etiqueta.setVisible(bool(self._etiqueta))
        lay.addWidget(self._lbl_etiqueta)
        lay.addWidget(self._lbl_valor)
        if tooltip:
            self.setToolTip(f"{tooltip}: {self._valor}")

    def _ancho_natural(self):
        ancho = QFontMetrics(self._negrita).horizontalAdvance(self._valor) + self._punto
        if self._etiqueta:
            ancho += QFontMetrics(self._normal).horizontalAdvance(self._etiqueta) + 4
        return ancho + self._pad

    def sizeHint(self):
        return QSize(self._ancho_natural(), self.ALTO)

    def minimumSizeHint(self):
        return QSize(0, self.ALTO)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.width() == self._ultimo_ancho:
            return
        self._ultimo_ancho = self.width()
        disponible = self.width() - self._pad - self._punto
        metrica = QFontMetrics(self._negrita)
        con_etiqueta = bool(self._etiqueta) and self._ancho_natural() - self._pad - self._punto <= disponible
        self._lbl_etiqueta.setVisible(con_etiqueta)
        if con_etiqueta or metrica.horizontalAdvance(self._valor) <= disponible:
            self._lbl_valor.setText(self._valor)
        else:
            self._lbl_valor.setText(metrica.elidedText(self._valor, Qt.TextElideMode.ElideRight, max(disponible, 10)))


class _ChipEstados(QFrame):
    """Chip neutro con los estados comercial y de activación, cada uno con su punto de
    color: '● Baja / ● Desconectado'. Los textos son QLabel con hoja de estilo."""

    def __init__(self, estados, tooltip="", marco=True, parent=None):
        """`estados`: lista de (valor, color del punto). Sin `marco` es solo texto, alineado a la izquierda."""
        super().__init__(parent)
        self.setObjectName("chip_estados")
        fondo, borde = ("#F7F9FC", BORDER) if marco else ("transparent", "transparent")
        self.setStyleSheet(f"QFrame#chip_estados {{ background-color: {fondo}; border: 1px solid {borde}; "
                           f"border-radius: {_PildoraDato.ALTO // 2}px; }} QLabel {{ background: transparent; "
                           "border: none; font-size: 10px; }")
        self.setFixedHeight(_PildoraDato.ALTO)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10 if marco else 0, 0, 10 if marco else 0, 0)
        lay.setSpacing(4)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter if marco else Qt.AlignmentFlag.AlignLeft)
        for i, (valor, color) in enumerate(estados):
            if i:
                barra = QLabel("/", self)
                barra.setStyleSheet(f"color: {GRIS_TARJETA};")
                lay.addWidget(barra)
            marca = QLabel(self)
            marca.setFixedSize(8, 8)
            marca.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
            lay.addWidget(marca, 0, Qt.AlignmentFlag.AlignVCenter)
            texto = QLabel(str(valor), self)
            texto.setStyleSheet(f"color: {TEXT_PRIMARY}; font-weight: bold;")
            lay.addWidget(texto)
        if tooltip:
            self.setToolTip(tooltip)

    def minimumSizeHint(self):
        return QSize(0, _PildoraDato.ALTO)


class _IconoContrato(QLabel):
    """Ícono de la tarjeta de contrato: azul Volvo en claro y su versión aclarada en oscuro;
    se vuelve a pintar al cambiar el tema."""

    def __init__(self, nombre, color, descripcion, parent=None):
        super().__init__(parent)
        self._nombre = nombre
        self._color = color
        self.setFixedWidth(18)
        self.setToolTip(descripcion)
        self.setStyleSheet("background: transparent; border: none;")
        self._pintar()
        _tema.GestorTema.instancia().tema_cambiado.connect(self._pintar)

    def _pintar(self, *_):
        try:
            self.setPixmap(ThemeManager.icon_pixmap(self._nombre, color=_tema.texto(self._color).name(), size=16))
        except RuntimeError:
            pass


def _icono_contrato(estado_activacion, sin_vc):
    """(ícono, color, descripción) del contrato según su activación: conectado, activando,
    desconectado, sin flota o sin Volvo Connect. Todos en azul Volvo; cambia la forma."""
    estado = str(estado_activacion).strip().upper()
    if sin_vc:
        return 'fa5s.ban', VOLVO_BLUE, "Sin Volvo Connect"
    return {
        'CONECTADO': ('fa5s.file-contract', VOLVO_BLUE, "Conectado"),
        'ACTIVANDO': ('fa5s.file-signature', VOLVO_BLUE, "Activando"),
        'DESCONECTADO': ('fa5s.file-excel', VOLVO_BLUE, "Desconectado"),
        'SIN FLOTA': ('fa5s.unlink', VOLVO_BLUE, "Sin flota"),
    }.get(estado, ('fa5s.file-contract', VOLVO_BLUE, str(estado_activacion).strip().capitalize() or "Sin estado"))


def _punto_estado(paleta):
    """Color del punto de un estado, según su paleta (verde, amarillo, rojo o gris)."""
    return {_PAL_VERDE: '#10B981', _PAL_AMARILLO: '#F59E0B', _PAL_ROJO: '#DC2626', _PAL_NARANJA: '#EA580C'}.get(paleta, '#94A3B8')


def _paleta_tarjeta(paleta):
    """El gris de las tarjetas usa GRIS_TARJETA para que en oscuro se lea blanco."""
    return (paleta[0], GRIS_TARJETA) if paleta == _PAL_GRIS else paleta


def _paleta_fechas(estado_comercial, termino):
    """Color de las fechas de un contrato: rojo si está de baja o vencido, amarillo
    si vence dentro de 30 días, verde si está vigente o es mensual, gris sin dato."""
    if str(estado_comercial).strip().upper() in ('BAJA', 'BAJA SOLICITADA', 'VENCIDO'):
        return _PAL_ROJO
    if str(termino).strip().upper() == 'MENSUAL':
        return _PAL_VERDE
    fecha = DataFrameFormatter.parsear_fecha_segura(termino) if _flota_valida(termino) else pd.NaT
    if pd.isna(fecha):
        return _PAL_GRIS
    dias = (fecha.normalize() - pd.Timestamp.now().normalize()).days
    if dias < 0:
        return _PAL_ROJO
    return _PAL_AMARILLO if dias <= 30 else _PAL_VERDE


class GeneralUnidadCard(QFrame):
    """Tarjeta clickeable de un contrato (VIN), caja izquierda -> Contratos.
    Todo en chips: VIN con su ícono; estado comercial y de activación;
    contrato y facturación; inicio y término. El VIN ya no se copia desde la
    tarjeta (28-10-2026): se copia desde el encabezado de la ficha.
    row_idx es la posición en GeneralModule._df_unidades_visible."""

    clicked = pyqtSignal(int)

    def __init__(self, row_idx, vin, chasis, razon_social, estado_activacion, industria, etapa_gestion,
                 parent=None, extras=None):
        """`industria` se conserva por compatibilidad pero ya no se muestra
        (07-10-2026). `extras`: dict con cdb, estado_comercial,
        forma_contrato, tipo_facturacion, inicio y termino."""
        super().__init__(parent)
        extras = extras or {}
        self.row_idx = row_idx
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("general_unidad_card")
        # Estilos fijos en QSS_TARJETAS_UNIDAD (una vez en el contenedor); el
        # badge de estado y la etapa conservan el suyo porque su color
        # depende del dato.
        self.setProperty("seleccionado", False)

        # Se reparte en 2 o 3 columnas (_GrillaTarjetas): ancho ignorado para que
        # el contenido no ensanche su columna
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        # Rejilla de 2 columnas iguales: VIN y chasis en las esquinas, los cuatro datos
        # centrales ordenados en 2 x 2 y las fechas, una en cada esquina
        grilla = QGridLayout(self)
        grilla.setContentsMargins(10, 8, 10, 8)
        grilla.setHorizontalSpacing(6)
        grilla.setVerticalSpacing(6)
        grilla.setColumnStretch(0, 5)
        grilla.setColumnStretch(1, 4)
        grilla.setRowStretch(2, 1)

        def poner(fila, columna, widget, alineacion=None):
            widget.setMinimumWidth(0)
            if alineacion is None:
                grilla.addWidget(widget, fila, columna)
            else:
                grilla.addWidget(widget, fila, columna, alineacion)

        # Razón social, etapa y CDB no se muestran en la tarjeta; siguen en la ficha de la caja derecha.
        self.lbl_industria = None
        self.lbl_etapa = None
        self.lbl_inicio = None
        self.lbl_rut = None
        self.lbl_cdb = None
        self.lbl_vigencia = None

        # Estilo de la tarjeta de Cliente: ícono (según la activación) y VIN arriba a la izquierda y,
        # a la derecha, el badge de contrato / facturación; abajo, los estados con su punto de color y
        # las fechas con el color del vencimiento. El chasis queda en el tooltip del VIN y en la ficha.
        estado_comercial = str(extras.get('estado_comercial', '')).strip()
        self.es_sin_vc = _es_sin_vc(estado_comercial, estado_activacion,
                                    extras.get('forma_contrato', ''), extras.get('tipo_facturacion', ''))
        nombre_icono, color_icono, descripcion = _icono_contrato(estado_activacion, self.es_sin_vc)
        # VIN con su ícono en un chip, como los demás datos de la tarjeta; ya no se copia desde aquí
        # (se copia desde el encabezado de la ficha)
        self.lbl_vin = QLabel(str(vin))
        self.lbl_vin.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        chasis_txt = str(chasis).strip()
        self.lbl_chasis = None
        celda_vin = QFrame()
        celda_vin.setObjectName("chip_vin")
        celda_vin.setStyleSheet(f"QFrame#chip_vin {{ background-color: #F7F9FC; border: 1px solid {BORDER}; border-radius: 12px; }} "
                                "QLabel { background: transparent; border: none; }")
        celda_vin.setFixedHeight(24)
        celda_vin.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        celda_vin.setToolTip(f"VIN {vin}" + (f"  •  Chasis {chasis_txt}" if _flota_valida(chasis_txt) else ""))
        fila_vin = QHBoxLayout(celda_vin)
        fila_vin.setContentsMargins(8, 0, 12, 0)
        fila_vin.setSpacing(6)
        fila_vin.addWidget(_IconoContrato(nombre_icono, color_icono, descripcion))
        fila_vin.addWidget(self.lbl_vin)
        celda_vin.setMinimumWidth(0)
        grilla.addWidget(celda_vin, 0, 0, Qt.AlignmentFlag.AlignLeft)

        if self.es_sin_vc:
            self.badge_estado = _PildoraDato("", "SIN VC", _paleta_tarjeta(_PAL_GRIS), "Sin Volvo Connect: sin estado comercial, "
                                             "activación No aplica, Sin contrato y Sin registro")
            poner(1, 0, self.badge_estado, Qt.AlignmentFlag.AlignLeft)
            return

        # Contrato y facturación juntos en un badge azul Volvo con letras blancas, como "Conversion / CLIENTE";
        # en rojo si la combinación no cumple la matriz de negocio
        forma = str(extras.get('forma_contrato', '')).strip()
        tipo_fact = str(extras.get('tipo_facturacion', '')).strip()
        tinta = _paleta_tarjeta(_PAL_ROJO)[1] if _color_forma_facturacion(forma, tipo_fact) == _PAL_ROJO else VOLVO_BLUE
        colores = (_PAL_GRIS[0], tinta)
        partes = [p for p in (forma, tipo_fact) if _flota_valida(p)]
        if partes:
            poner(1, 1, _PildoraDato("", " / ".join(partes), colores, "Contrato / Facturación", relleno=False))

        estado_act = str(estado_activacion).strip()
        estados = []
        if _flota_valida(estado_comercial):
            estados.append((estado_comercial, _punto_estado(_color_estado_comercial(estado_comercial))))
        estados.append((estado_act or "-", _punto_estado(_color_estado_activacion(estado_act))))
        self.badge_estado = _ChipEstados(estados, "Estado comercial / Estado de activación")
        poner(1, 0, self.badge_estado, Qt.AlignmentFlag.AlignLeft)

        # Inicio y término como "12-2025 / 12-2026", con el color del vencimiento del contrato
        termino_crudo = extras.get('termino', '')
        paleta = _paleta_tarjeta(_paleta_fechas(estado_comercial, termino_crudo))
        fechas = [_mes_anio(v) for v in (extras.get('inicio', ''), termino_crudo) if _flota_valida(v)]
        if fechas:
            self.lbl_vigencia = _PildoraDato("", " / ".join(fechas), (_PAL_GRIS[0], paleta[1]),
                                             "Inicio / Término del contrato", relleno=False)
            poner(0, 1, self.lbl_vigencia)

    def set_selected(self, selected):
        _repulir_seleccion(self, selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row_idx)
        super().mousePressEvent(event)


class GeneralFlotaCard(QFrame):
    """Tarjeta clickeable de una flota (caja izquierda -> Flota). Usa el estilo de la tarjeta de
    cliente (QSS_TARJETAS_CLIENTE). row_idx es la posición en GeneralModule._df_flotas_visible."""

    clicked = pyqtSignal(int)

    def __init__(self, row_idx, flota, cliente, rut, cdb_flota, total_unidades, total_clientes, parent=None, encontrados=0):
        super().__init__(parent)
        self.row_idx = row_idx
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("general_cliente_card")
        self.setProperty("duplicado", False)
        self.setProperty("seleccionado", False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        fila_nombre = QHBoxLayout()
        fila_nombre.setSpacing(7)
        icono = QLabel()
        fijar_icono_tema(icono, 'fa5s.truck', AZUL, 14)
        icono.setFixedWidth(16)
        fila_nombre.addWidget(icono, 0, Qt.AlignmentFlag.AlignTop)
        lbl_nombre = _EtiquetaDosLineas(str(flota).strip() or "Sin nombre")
        lbl_nombre.setObjectName("gc_nombre")
        fila_nombre.addWidget(lbl_nombre, 1)
        layout.addLayout(fila_nombre)
        layout.addStretch(1)

        fila_datos = QHBoxLayout()
        fila_datos.setSpacing(4)
        fila_datos.addStretch(1)
        if encontrados:
            # Cuántos de los VIN buscados son de esta flota
            badge_encontrados = QLabel(f"{encontrados} VIN encontrado{'' if encontrados == 1 else 's'}")
            badge_encontrados.setObjectName("gc_badge_encontrados")
            badge_encontrados.setToolTip("VIN de la búsqueda que pertenecen a esta flota")
            fila_datos.addWidget(badge_encontrados, 0, Qt.AlignmentFlag.AlignVCenter)
        badge_clientes = QLabel(f"{total_clientes} {'cliente' if total_clientes == 1 else 'clientes'}")
        badge_clientes.setObjectName("gc_badge")
        _fijar_ancho_chip(badge_clientes, "9999 clientes")
        fila_datos.addWidget(badge_clientes, 0, Qt.AlignmentFlag.AlignVCenter)
        badge = QLabel(f"{total_unidades} {'unidad' if total_unidades == 1 else 'unidades'}")
        badge.setObjectName("gc_badge")
        _fijar_ancho_chip(badge, "9999 unidades")
        fila_datos.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(fila_datos)

    def set_selected(self, selected):
        _repulir_seleccion(self, selected)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row_idx)
        super().mousePressEvent(event)


_ESTADOS_FLOTA = (
    # clave, texto, color de la barra, fondo, borde, color del texto, ícono
    ('conectadas', "Conectadas", "#1E9B4F", "#DFF3E6", "#BFE5CB", "#1E7E43", 'fa5s.wifi'),
    ('activando', "Activando", "#E0A100", "#FDF0C7", "#F2DB92", "#9A6200", 'fa5s.sun'),
    ('desconectadas', "Desconectadas", "#D12F2F", "#FBDDDD", "#F2BCBC", "#C62828", 'fa5s.ban'),
)


class _BarraEstadosFlota(QWidget):
    """Barra de una sola pieza con un tramo por estado, proporcional a su cantidad."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(9)
        self._tramos = []

    def set_tramos(self, cantidades, total, colores=None):
        colores = colores or [c for (_k, _t, c, *_r) in _ESTADOS_FLOTA]
        self._tramos = [(c, n / total) for c, n in zip(colores, cantidades)] if total else []
        self.update()

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        marco = QPainterPath()
        marco.addRoundedRect(QRectF(self.rect()), 4.5, 4.5)
        p.setClipPath(marco)
        p.fillRect(self.rect(), QColor("#E9EDF4"))
        x = 0.0
        for color, fraccion in self._tramos:
            ancho = self.width() * fraccion
            if fraccion > 0:
                ancho = max(ancho, 2.0)
            p.fillRect(QRectF(x, 0, ancho, self.height()), QColor(color))
            x += ancho
        p.end()


def _crear_lateral_civ_sz(nombre_objeto, icono_lat, texto):
    """Indicador CIV / Safety Zone con el formato de las tarjetas de estado: ícono, cifra grande y etiqueta en negrita."""
    marco = QFrame()
    marco.setObjectName(nombre_objeto)
    marco.setStyleSheet(f"QFrame#{nombre_objeto} {{ background: #E9F0FA; border: 1px solid #D2DFF0; border-radius: 12px; }}"
                        f"QFrame#{nombre_objeto} QLabel {{ background: transparent; border: none; }}")
    lay = QHBoxLayout(marco)
    lay.setContentsMargins(12, 6, 12, 6)
    lay.setSpacing(9)
    ico = QLabel()
    ico.setFixedSize(28, 28)
    ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
    fijar_icono_tema(ico, icono_lat, "#44536C", 14)
    ico.setStyleSheet("background: white; border-radius: 14px;")
    valor = QLabel("0")
    valor.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 21px; font-weight: 800;")
    detalle = QLabel(texto)
    detalle.setStyleSheet("color: #44536C; font-size: 12px; font-weight: 600;")
    lay.addWidget(ico)
    lay.addWidget(valor)
    lay.addWidget(detalle)
    return marco, valor, detalle


def contar_civ_sz(df):
    """Unidades con CIV y con Safety Zone, sin contar las desconectadas (no sirve saber de ellas)."""
    if df is None or len(df) == 0 or COL_TIPO_SERVICIO not in df.columns:
        return 0, 0
    if 'ESTADO DE ACTIVACIÓN ACTUAL' in df.columns:
        df = df[df['ESTADO DE ACTIVACIÓN ACTUAL'].astype(str).str.strip().str.upper() != 'DESCONECTADO']
    servicio = df[COL_TIPO_SERVICIO].astype(str).str.upper()
    return int(servicio.str.contains('CIV', na=False).sum()), int(servicio.str.contains(r'\bSZ\b', regex=True, na=False).sum())


class _BloqueEstadoFlota(QWidget):
    """Estado de conexión de la flota: total con barra y leyenda, dos indicadores (CIV y Safety Zone) y una
    tarjeta por estado. Diseño compacto aprobado el 28-10-2026."""

    def __init__(self, parent=None):
        super().__init__(parent)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(8)

        arriba = QFrame()
        arriba.setObjectName("estadoFlotaTotal")
        arriba.setStyleSheet(f"QFrame#estadoFlotaTotal {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}"
                             "QFrame#estadoFlotaTotal QLabel { background: transparent; border: none; }")
        fila = QHBoxLayout(arriba)
        fila.setContentsMargins(14, 10, 14, 10)
        fila.setSpacing(14)
        icono = QLabel()
        icono.setFixedSize(40, 40)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fijar_icono_tema(icono, 'fa5s.truck', "#3B6FA8", 18)
        icono.setStyleSheet("background: #DCE8F6; border-radius: 20px;")
        fila.addWidget(icono)
        total = QVBoxLayout()
        total.setSpacing(0)
        self.lbl_total = QLabel("0")
        self.lbl_total.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 28px; font-weight: 800;")
        lbl_total = QLabel("Total flota")
        lbl_total.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        total.addWidget(self.lbl_total)
        total.addWidget(lbl_total)
        fila.addLayout(total)
        centro = QVBoxLayout()
        centro.setSpacing(6)
        self.barra = _BarraEstadosFlota()
        centro.addWidget(self.barra)
        leyenda = QLabel("&nbsp;&nbsp; ".join(
            f"<span style='white-space:nowrap;'><span style='color:{color};'>&#9679;</span>&nbsp;{texto}</span>"
            for _k, texto, color, *_r in _ESTADOS_FLOTA))
        leyenda.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        leyenda.setWordWrap(True)
        centro.addWidget(leyenda)
        fila.addLayout(centro, 1)
        self._laterales = {}
        for clave, icono_lat, texto in (('civ', 'fa5s.crosshairs', "CIV"), ('sz', 'fa5s.shield-alt', "Safety Zone")):
            marco, valor, detalle = _crear_lateral_civ_sz("estadoFlotaLateral", icono_lat, texto)
            fila.addWidget(marco)
            self._laterales[clave] = (valor, detalle, texto)
        raiz.addWidget(arriba)

        tarjetas = QHBoxLayout()
        tarjetas.setSpacing(8)
        self._valores = {}
        for clave, texto, _barra, fondo, borde, color_texto, icono_estado in _ESTADOS_FLOTA:
            tarjeta = QFrame()
            tarjeta.setObjectName("estadoFlotaTarjeta")
            tarjeta.setStyleSheet(f"QFrame#estadoFlotaTarjeta {{ background: {fondo}; border: 1px solid {borde}; border-radius: 12px; }}"
                                  "QFrame#estadoFlotaTarjeta QLabel { background: transparent; border: none; }")
            lay = QHBoxLayout(tarjeta)
            lay.setContentsMargins(12, 6, 12, 6)
            lay.setSpacing(9)
            ico = QLabel()
            ico.setFixedSize(28, 28)
            ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ico.setPixmap(ThemeManager.icon_pixmap(icono_estado, color=color_texto, size=14))
            ico.setStyleSheet("background: white; border-radius: 14px;")
            valor = QLabel("0")
            valor.setStyleSheet(f"color: {color_texto}; font-size: 21px; font-weight: 800;")
            etiqueta = QLabel(texto)
            etiqueta.setStyleSheet(f"color: {color_texto}; font-size: 12px; font-weight: 600;")
            lay.addWidget(ico)
            lay.addWidget(valor)
            lay.addWidget(etiqueta)
            lay.addStretch()
            tarjetas.addWidget(tarjeta, 1)
            self._valores[clave] = valor
        raiz.addLayout(tarjetas)

    def actualizar(self, total, cantidades, civ, sz):
        """`cantidades`: unidades por estado, en el orden de _ESTADOS_FLOTA."""
        self.lbl_total.setText(str(total))
        for (clave, *_resto), n in zip(_ESTADOS_FLOTA, cantidades):
            self._valores[clave].setText(str(n))
        self.barra.set_tramos(cantidades, total)
        for clave, n in (('civ', civ), ('sz', sz)):
            valor, detalle, texto = self._laterales[clave]
            valor.setText(str(n))
            detalle.setText(f"{texto} · {round(100 * n / total) if total else 0} %")


class _BloqueResumenCliente(QFrame):
    """Cifras del cliente con el mismo diseño del bloque de la flota: total de unidades, barra con y sin
    Volvo Connect (unidades conectadas) y los indicadores CIV y Safety Zone."""
    _COLOR_CON, _COLOR_SIN = "#1E9B4F", "#D4D9E3"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resumenCliente")
        self.setStyleSheet(f"QFrame#resumenCliente {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}"
                           "QFrame#resumenCliente QLabel { background: transparent; border: none; }")
        fila = QHBoxLayout(self)
        fila.setContentsMargins(14, 10, 14, 10)
        fila.setSpacing(14)
        icono = QLabel()
        icono.setFixedSize(40, 40)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fijar_icono_tema(icono, 'fa5s.truck', "#3B6FA8", 18)
        icono.setStyleSheet("background: #DCE8F6; border-radius: 20px;")
        fila.addWidget(icono)
        total = QVBoxLayout()
        total.setSpacing(0)
        self.lbl_total = QLabel("0")
        self.lbl_total.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 28px; font-weight: 800;")
        lbl_total = QLabel("Total unidades")
        lbl_total.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px;")
        total.addWidget(self.lbl_total)
        total.addWidget(lbl_total)
        fila.addLayout(total)
        centro = QVBoxLayout()
        centro.setSpacing(6)
        self.barra = _BarraEstadosFlota()
        centro.addWidget(self.barra)
        self.lbl_leyenda = QLabel()
        self.lbl_leyenda.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        self.lbl_leyenda.setWordWrap(True)
        centro.addWidget(self.lbl_leyenda)
        fila.addLayout(centro, 1)
        self._laterales = {}
        for clave, icono_lat, texto in (('civ', 'fa5s.crosshairs', "CIV"), ('sz', 'fa5s.shield-alt', "Safety Zone")):
            marco, valor, detalle = _crear_lateral_civ_sz("resumenClienteLateral", icono_lat, texto)
            fila.addWidget(marco)
            self._laterales[clave] = (valor, detalle, texto)
        self.actualizar(0, 0, 0, 0)

    def actualizar(self, total, conectadas, civ, sz):
        self.lbl_total.setText(str(total))
        sin = max(total - conectadas, 0)
        self.barra.set_tramos([conectadas, sin], total, [self._COLOR_CON, self._COLOR_SIN])
        pct = round(100 * conectadas / total) if total else 0
        self.lbl_leyenda.setText(
            f"<span style='white-space:nowrap;'><span style='color:{self._COLOR_CON};'>&#9679;</span>&nbsp;Con Volvo Connect: {conectadas} ({pct} %)</span>"
            f"&nbsp;&nbsp; <span style='white-space:nowrap;'><span style='color:{self._COLOR_SIN};'>&#9679;</span>&nbsp;Sin Volvo Connect: {sin}</span>")
        for clave, n in (('civ', civ), ('sz', sz)):
            valor, detalle, texto = self._laterales[clave]
            valor.setText(str(n))
            detalle.setText(f"{texto} · {round(100 * n / total) if total else 0} %")


class _FilaClienteFlota(QFrame):
    """Fila de un cliente en la ficha de flota (solo si la flota tiene varios): nombre, RUT y unidades.
    Un clic abre ese cliente en la pestaña Cliente."""

    abrir = pyqtSignal()

    def __init__(self, nombre, rut, unidades, cdb="", parent=None):
        super().__init__(parent)
        self.setObjectName("cliente_flota_fila")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Abrir este cliente")
        self.setStyleSheet(f"""
            QFrame#cliente_flota_fila {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
            QFrame#cliente_flota_fila:hover {{ border: 1px solid {AZUL}; }}
            QFrame#cliente_flota_fila QLabel {{ border: none; background: transparent; }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(12)
        # El nombre se ve completo (baja de línea si es largo) y debajo, más chico, el RUT y el CDB
        textos = QVBoxLayout()
        textos.setSpacing(2)
        lbl_nombre = QLabel(nombre or "Sin razón social")
        lbl_nombre.setWordWrap(True)
        lbl_nombre.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 12px; font-weight: bold;")
        detalle = " • ".join(t for t in (f"RUT {rut}" if rut else "Sin RUT", f"CDB {cdb}" if cdb else "") if t)
        lbl_rut = QLabel(detalle)
        lbl_rut.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        textos.addWidget(lbl_nombre)
        textos.addWidget(lbl_rut)
        layout.addLayout(textos, 1)
        badge = QLabel(f"{unidades} {'unidad' if unidades == 1 else 'unidades'}")
        badge.setStyleSheet(f"background-color: {AZUL}; color: white; font-size: 10px; font-weight: bold; "
                            "padding: 4px 10px; border-radius: 10px;")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.abrir.emit()
        super().mousePressEvent(event)
