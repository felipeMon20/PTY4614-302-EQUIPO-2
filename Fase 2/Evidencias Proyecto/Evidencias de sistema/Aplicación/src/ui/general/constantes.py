"""Constantes, estilos, ayudas y alias de la pantalla General."""
from src.theme.colors import BORDER, BORDE_CAJA, DANGER, FONDO_APP, PRIMARY, SURFACE, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY, VOLVO_BLUE
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QFrame, QLabel, QSizePolicy, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QApplication)
from PyQt6.QtCore import Qt, QSize, QTimer, QRectF
from PyQt6.QtGui import QPalette, QColor, QFont, QFontMetrics, QBrush, QPainter
from src.ui.compartido.icono_tema import fijar_icono_tema
from src.ui.compartido.comercial_estilo import AnimacionHover
from src.core.constants import COL_RAZON_SOCIAL, COL_RUT, COL_INDUSTRIA, COL_CDB, COL_CDB_FLOTA, COL_VIN, COL_CHASIS, COL_FLOTA_VC, COL_TIPO_SERVICIO, COL_ESTADO_ACTIVACION, COL_EJECUTIVO, COL_ETAPA_GESTION, COL_MODELO, COL_FLOTA_VC_2, COL_FORMA_CONTRATO, COL_ESTADO_COMERCIAL, COL_INICIO_CONTRATO, COL_DURACION_MESES, COL_TERMINO_CONTRATO, COL_PERIODO_INTERNO, COL_ESTADO_ENTREGA, COL_FECHA_BAJA, COL_TIPO_FACTURACION, COL_CONTRATO_JUSTTIME, COL_FECHA_INICIO_FACT, COL_FECHA_TERMINO_FACT, COL_ESTADO_CM
from src.theme.theme_manager import ThemeManager
import logging
from src.services import general_services


COLUMNAS_CLIENTES = general_services.COLUMNAS_CLIENTES


COLUMNAS_FLOTAS = general_services.COLUMNAS_FLOTAS


COLUMNAS_HISTORIAL = general_services.COLUMNAS_HISTORIAL


COLUMNAS_UNIDADES = general_services.COLUMNAS_UNIDADES


ESTADO_ACTIVACION_CONECTADO = general_services.ESTADO_ACTIVACION_CONECTADO


_FLOTA_VC_SIN_FLOTA = general_services.FLOTA_VC_SIN_FLOTA


_calcular_vigencia = general_services.calcular_vigencia


_clave_flota_texto = general_services.clave_flota_texto


_flota_valida = general_services.flota_valida


_formatear_fecha_contrato = general_services.formatear_fecha_contrato


_mes_anio = general_services.mes_anio


_texto_duracion = general_services.texto_duracion


logger = logging.getLogger(__name__)


# Azul oscuro Volvo (mismo de las barras de Comercial/Administración) y sus apoyos
AZUL = "#1B2B4E"


AZUL_HOVER = "#2C4170"


TINTE_CLARO = "#EEF1F6"


LINEA_AZUL = "#C9D1E0"


TEXTO_SOBRE_AZUL = "#C9D4EA"


QSS_BOTON_AZUL = (
    f"QPushButton {{ background-color: {AZUL}; color: white; border: 1px solid {AZUL}; border-radius: 9px; "
    "padding: 8px 14px; font-weight: 700; }"
    f"QPushButton:hover {{ background-color: {AZUL_HOVER}; border: 1px solid {AZUL_HOVER}; }}"
    "QPushButton:disabled { background-color: #C5CCDA; border: 1px solid #C5CCDA; color: #F3F5F9; }"
)


def _boton_azul(btn):
    btn.setStyleSheet(QSS_BOTON_AZUL)


QSS_BOTON_MINIMO = (
    f"QPushButton {{ background-color: transparent; color: {AZUL}; border: 1px solid {BORDER}; border-radius: 8px; "
    "padding: 5px 12px; font-size: 11px; font-weight: 700; }"
    f"QPushButton:hover {{ background-color: #F3F5F9; border: 1px solid {AZUL}; }}"
    "QPushButton:disabled { background-color: transparent; border: 1px solid #E4E8F0; color: #B3BBCB; }"
)


def _boton_minimo(btn):
    btn.setStyleSheet(QSS_BOTON_MINIMO)


def _boton_sobre_azul(btn):
    """Botón blanco para la barra azul del encabezado: al pasar el mouse el
    fondo y el borde van pasando a azul claro con la misma animación de hover
    del resto de la app, y al presionarlo se oscurece un poco más."""
    fondo = (QColor("#FFFFFF"), QColor("#CFE0F8"))

    def mezclar(par, p):
        a, b = par
        return QColor(*(round(x + (y - x) * p) for x, y in zip(a.getRgb()[:3], b.getRgb()[:3]))).name()

    def pintar(progreso):
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {mezclar(fondo, progreso)}; color: {AZUL}; "
            "border: none; border-radius: 8px; padding: 6px 13px; "
            "font-size: 11px; font-weight: 700; } "
            "QPushButton:checked { background-color: #CFE0F8; } "
            "QPushButton:pressed { background-color: #AFC8EE; }")

    pintar(0.0)
    btn._animacion_hover = AnimacionHover(btn, pintar)


class _GrupoControles:
    """Controles que van directo en la barra de pestañas y se muestran u ocultan juntos
    (sin un widget contenedor, que dejaba un resto de pintura sobre los botones)."""

    def __init__(self, layout):
        self._layout = layout
        self._widgets = []

    def addWidget(self, widget):
        self._layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self._widgets.append(widget)

    def agregar_existente(self, widget):
        """Suma al grupo un widget que ya está en el layout, al inicio del orden."""
        self._widgets.insert(0, widget)

    def mover_a(self, layout):
        if layout is self._layout:
            return
        for widget in self._widgets:
            self._layout.removeWidget(widget)
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        self._layout = layout

    def compactar(self, compacto):
        for widget in self._widgets:
            if hasattr(widget, 'set_compacto'):
                widget.set_compacto(compacto)

    def ancho_necesario(self):
        espaciado = self._layout.spacing()
        anchos = [w.sizeHint().width() for w in self._widgets]
        return sum(anchos) + espaciado * max(len(anchos) - 1, 0)

    def setVisible(self, visible):
        for widget in self._widgets:
            widget.setVisible(visible)

    def hide(self):
        self.setVisible(False)


def _con_transicion_derecha(metodo):
    """Anima la caja derecha (foto de lo anterior que se funde y contenido
    nuevo que sube un poco) cada vez que cambia el cliente o la unidad."""
    def envoltura(self, *args, **kwargs):
        # Varias vistas cambian en una misma acción (ej. al entrar a Unidades): basta una foto, la del estado anterior
        foto = None
        if not self.__dict__.get('_foto_tomada_en_turno'):
            foto = self._foto_caja_derecha()
            self._foto_tomada_en_turno = True
            QTimer.singleShot(0, lambda: self.__dict__.__setitem__('_foto_tomada_en_turno', False))
        resultado = metodo(self, *args, **kwargs)
        self._animar_caja_derecha(foto)
        return resultado
    envoltura.__name__ = metodo.__name__
    envoltura.__doc__ = metodo.__doc__
    return envoltura


def _crear_estado_vacio(icono, titulo, detalle):
    """Tarjeta para una pestaña sin datos: ocupa todo el espacio disponible y centra un ícono en círculo,
    un título y una línea de explicación."""
    marco = QFrame()
    marco.setObjectName("estadoVacio")
    marco.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    marco.setStyleSheet(f"QFrame#estadoVacio {{ background-color: #F3F5F9; border: 1px dashed {LINEA_AZUL}; border-radius: 16px; }}"
                        "QFrame#estadoVacio QLabel { background: transparent; border: none; }")
    lay = QVBoxLayout(marco)
    lay.setContentsMargins(32, 32, 32, 32)
    lay.setSpacing(10)
    circulo = QLabel()
    circulo.setFixedSize(76, 76)
    circulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    fijar_icono_tema(circulo, icono, AZUL, 30)
    circulo.setStyleSheet("background: #E3E9F4; border: 2px dashed #B5C2DB; border-radius: 38px;")
    lbl_titulo = QLabel(titulo)
    lbl_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 17px; font-weight: bold;")
    lbl_detalle = QLabel(detalle)
    lbl_detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_detalle.setWordWrap(True)
    lbl_detalle.setMaximumWidth(520)
    lbl_detalle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 13px;")
    # Sin alineación en el layout: una etiqueta con varias líneas centrada así se recorta en alto
    fila_detalle = QHBoxLayout()
    fila_detalle.addStretch(1)
    fila_detalle.addWidget(lbl_detalle, 4)
    fila_detalle.addStretch(1)
    lay.addStretch(1)
    lay.addWidget(circulo, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addSpacing(4)
    lay.addWidget(lbl_titulo)
    lay.addLayout(fila_detalle)
    lay.addStretch(1)
    return marco


def _fijar_ancho_chip(chip, *textos_maximos):
    """Ancho fijo para los chips de las tarjetas (9 px, negrita, 8 px de relleno a cada lado): el de mayor
    texto posible (hasta 9999) marca el ancho, así quedan alineados en toda la lista."""
    fuente = QFont(chip.font())
    fuente.setPixelSize(9)
    fuente.setBold(True)
    metricas = QFontMetrics(fuente)
    chip.setFixedWidth(max(metricas.horizontalAdvance(t) for t in textos_maximos) + 16 + 4)
    chip.setAlignment(Qt.AlignmentFlag.AlignCenter)


def _crear_invitacion(titulo, detalle):
    """Cartel de la caja derecha sin selección: ocupa todo el espacio libre, con un ícono y un mensaje grandes."""
    marco = QFrame()
    marco.setObjectName("invitacion")
    marco.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    marco.setStyleSheet(f"QFrame#invitacion {{ background-color: #F3F5F9; border: 1px dashed {LINEA_AZUL}; border-radius: 16px; }}"
                        "QFrame#invitacion QLabel { background: transparent; border: none; }")
    lay = QVBoxLayout(marco)
    lay.setContentsMargins(32, 32, 32, 32)
    lay.setSpacing(12)
    circulo = QLabel()
    circulo.setFixedSize(104, 104)
    circulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    fijar_icono_tema(circulo, 'fa5s.hand-pointer', AZUL, 46)
    circulo.setStyleSheet("background: #E3E9F4; border-radius: 52px;")
    lbl_titulo = QLabel(titulo)
    lbl_titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_titulo.setWordWrap(True)
    lbl_titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 24px; font-weight: 800;")
    lbl_detalle = QLabel(detalle)
    lbl_detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl_detalle.setWordWrap(True)
    lbl_detalle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 15px;")
    fila_detalle = QHBoxLayout()
    fila_detalle.addStretch(1)
    fila_detalle.addWidget(lbl_detalle, 6)
    fila_detalle.addStretch(1)
    lay.addStretch(1)
    lay.addWidget(circulo, 0, Qt.AlignmentFlag.AlignHCenter)
    lay.addSpacing(4)
    lay.addWidget(lbl_titulo)
    lay.addLayout(fila_detalle)
    lay.addStretch(1)
    return marco


_PIXMAP_WIFI_DESCONECTADO = {}


def _pixmap_wifi_desconectado(tamano):
    """Ícono de wifi con una raya roja encima (la fuente no trae 'wifi-slash'): el estado Desconectado
    ya no se ve igual que el Conectado."""
    pixmap = _PIXMAP_WIFI_DESCONECTADO.get(tamano)
    if pixmap is None:
        import qtawesome as qta
        pixmap = qta.icon('fa5s.wifi', 'fa5s.slash', options=[{'color': 'white'}, {'color': '#FF6B6B'}]).pixmap(QSize(tamano, tamano))
        _PIXMAP_WIFI_DESCONECTADO[tamano] = pixmap
    return pixmap


class _KpiCompacto(QFrame):
    """Tarjeta KPI baja del detalle de cliente: título y número a la izquierda, % (o texto de apoyo) a la derecha."""

    def __init__(self, titulo, valor, parent=None):
        super().__init__(parent)
        self.setObjectName("kpiCompacto")
        self.setStyleSheet(f"QFrame#kpiCompacto {{ background-color: #F7F9FC; border: 1px solid {BORDER}; border-radius: 12px; }}"
                           "QFrame#kpiCompacto QLabel { background: transparent; border: none; }")
        self.setFixedHeight(54)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 4, 10, 4)
        lay.setSpacing(8)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        self._lbl_titulo = QLabel(titulo)
        self._lbl_titulo.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 500;")
        self._lbl_valor = QLabel(valor)
        self._lbl_valor.setStyleSheet(f"color: {AZUL}; font-size: 20px; font-weight: 800;")
        textos.addWidget(self._lbl_titulo)
        textos.addWidget(self._lbl_valor)
        self._lbl_extra = QLabel("")
        self._lbl_extra.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl_extra.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 11px; font-weight: bold;")
        lay.addLayout(textos)
        lay.addStretch(1)
        lay.addWidget(self._lbl_extra)

    def actualizar(self, valor, porcentaje, pie):
        self._lbl_valor.setText(str(valor))
        self._lbl_extra.setText(f"{round(porcentaje * 100)} %" if porcentaje is not None else pie)


def _tarjeta_blanca(frame):
    """Tarjeta blanca para el contenido de la caja derecha (que es azul oscuro)."""
    frame.setObjectName("tarjetaBlanca")
    frame.setStyleSheet(f"QFrame#tarjetaBlanca {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}")


# Listado general de unidades (caja izquierda, apartado "Unidades"): todas
# las VIN de Comercial, una fila por unidad, sin agrupar. Misma fuente que
# Cliente/Flota (self.df_comercial_raw). CDB y Razón Social se incluyen para
# que la tabla derecha de detalle (por CDB) pueda filtrar este mismo df sin
# reconsultar Comercial.
# Anchos máximos de las dos cajas de Clientes y Flota (px)
ANCHO_MAX_CAJA_IZQUIERDA = 600


ANCHO_MAX_CAJA_DERECHA = 1100


# Las listas Cliente y Contratos (caja izquierda) siempre van en una columna
NUM_COLUMNAS_LISTA = 1


# Fondo de la pantalla y borde de las cajas (gris azulado, 28-10-2026): separan las cajas blancas del fondo
FONDO_GENERAL = FONDO_APP


BORDE_CAJA_GENERAL = BORDE_CAJA


COLOR_CDB_FLOTA_MINORITARIO = "#E8740C"


# Columnas visibles en la tabla de la izquierda (caja izquierda, apartado
# "Unidades"): CDB y Flota VC quedan fuera de la vista (a pedido explícito)
# pero se conservan en df_unidades_base porque los filtros y el detalle de
# la caja derecha los siguen necesitando. VIN también
# queda fuera de la vista desde el 10-09-2026 (a pedido de Javiera) pero se
# conserva en df_unidades_base y en COLUMNAS_BUSQUEDA_UNIDADES: el buscador
# global de MainWindow sigue encontrando unidades por VIN exactamente igual
# que antes, solo que la columna no se pinta en pantalla (mismo mecanismo
# que ya se usaba para ocultar CDB/Flota VC). 'Industria/s' (antes visible
# solo en la tabla de Clientes) y 'ETAPA GESTIÓN' (antes no visible en
# ningún lugar de este módulo) se agregan aquí a pedido de Javiera.
COLUMNAS_UNIDADES_VISIBLES = ['CHASIS', 'Razón Social', 'Estado Activación', 'Industria/s', 'ETAPA GESTIÓN']


# Buscador global de MainWindow (self.search_bar en main_window.py), aplicado
# únicamente a la caja izquierda -> Unidades (ver GeneralModule.filter_table
# / _aplicar_busqueda_unidades): un término puede coincidir en cualquiera de
# estas 4 columnas. CDB, VIN y RUT (agregado 28-09-2026, a pedido explícito)
# no se muestran en la tabla (ver COLUMNAS_UNIDADES_VISIBLES) pero siguen
# siendo buscables porque df_unidades_base los conserva.
COLUMNAS_BUSQUEDA_UNIDADES = ['Razón Social', 'VIN', 'CDB', 'RUT']


# Agrupación de las 33 columnas de una unidad (df_comercial_raw, ya con las
# ~32 columnas reales de PruebasFM + 'N°' agregado por
# comercial_services.procesar_df_comercial) para la ficha de VIN de la caja
# derecha -> Unidades. NO son categorías inventadas: son exactamente las
# mismas 4 secciones que ya usa el formulario "Gestión de Unidades"
# (comercial_agregar.py: Empresa/Unidad/Comercial/Operativa) más un quinto
# grupo con las columnas que ese formulario no muestra pero sí conserva
# (COLUMNAS_EXTRA_DEFAULT_GUION en comercial_agregar.py). 'N°' es un índice
# de fila agregado por la UI, no un dato real de la unidad, así que no
# aparece en ningún grupo (32 campos reales + N° = 33 columnas totales).
_FICHA_VIN_GRUPOS = [
    ("Empresa", "fa5s.building", [
        (COL_RUT, "RUT"), (COL_RAZON_SOCIAL, "Razón Social"),
        (COL_CDB, "CDB comercial"), (COL_CDB_FLOTA, "CDB flota"), (COL_INDUSTRIA, "Industria"),
    ]),
    ("Información de la unidad", "fa5s.truck", [
        (COL_VIN, "VIN"), (COL_CHASIS, "Chasis"), (COL_MODELO, "Modelo"),
    ]),
    ("Información comercial", "fa5s.file-invoice", [
        (COL_EJECUTIVO, "Ejecutivo"), (COL_FORMA_CONTRATO, "Forma de contrato"),
        (COL_TIPO_SERVICIO, "Tipo de servicio"), (COL_ESTADO_COMERCIAL, "Estado comercial"),
        (COL_INICIO_CONTRATO, "Inicio contrato"), (COL_DURACION_MESES, "Duración (meses)"),
        (COL_TERMINO_CONTRATO, "Término contrato"), (COL_PERIODO_INTERNO, "Periodo interno"),
        (COL_ESTADO_ENTREGA, "Fecha de entrega"),
    ]),
    ("Información operativa", "fa5s.cogs", [
        (COL_FLOTA_VC, "Flota VC"), (COL_FLOTA_VC_2, "Flota VC 2"),
        (COL_ESTADO_ACTIVACION, "Estado de activación"), (COL_ETAPA_GESTION, "Etapa gestión"),
    ]),
    ("Facturación y CM", "fa5s.file-invoice-dollar", [
        (COL_FECHA_BAJA, "Fecha de baja"), (COL_TIPO_FACTURACION, "Tipo de facturación"),
        (COL_CONTRATO_JUSTTIME, "Contrato creado en JustTime"),
        (COL_FECHA_INICIO_FACT, "Inicio facturación"), (COL_FECHA_TERMINO_FACT, "Término facturación"),
        ("OBSERVACIONES", "Observaciones"), ("N CONTRATO 3PC", "N° Contrato 3PC"),
        ("FECHA INICIO CM", "Fecha inicio CM"), ("FECHA TERMINO CM", "Fecha término CM"),
        ("TIPO DE CM", "Tipo de CM"), (COL_ESTADO_CM, "Estado del CM"), ("PAGO CM", "Pago CM"),
    ]),
]


# Colores llamativos para el badge de 'Estado Activación' en la tabla de
# Unidades (bg, texto), mismas familias de color que ya usa el resto de la
# app (SUCCESS/DANGER/WARNING en colors.py) para que coincidan visualmente;
# 'SIN FLOTA' usa violeta para diferenciarse de los otros 3 estados.
ESTADO_ACTIVACION_COLORES = {
    'CONECTADO': ('#D1FAE5', "#13B889"),
    'DESCONECTADO': ('#FEE2E2', "#C41919"),
    'ACTIVANDO': ('#FEF3C7', "#E1DE08"),
    'SIN FLOTA': ('#EDE9FE', "#4E4E4E"),
    # Naranja agregado a pedido explícito (20-09-2026): antes 'No aplica' no
    # tenía color propio y caía en el estilo genérico sin badge.
    'NO APLICA': ('#FFEDD5', "#C2410C"),
}


# Tarjetas por página en Cliente/Flota/Unidades (caja izquierda, 20-09-2026):
# con varios miles de unidades/clientes reales, construir TODAS las tarjetas
# de una sola vez en load_data()/filter_*() congelaba la app casi un minuto
# al entrar al módulo, y la primera vez que Qt activa el layout de una
# pestaña oculta con miles de widgets volvía a congelarla al cambiar de
# sub-pestaña (reportado por el usuario, 20-09-2026). Se pagina con
# controles "‹ Anterior | Página X de Y | Siguiente ›" (arriba y abajo de
# cada lista) en vez de mostrar todo de golpe.
#
# El tamaño de página es elegible por el usuario (combo "Mostrar", ver
# _crear_selector_tamano_pagina) -- medido con datos sintéticos (12.000
# unidades) que, después de una construcción inicial (costo fijo de motor de
# estilos de Qt que se paga una sola vez por sesión, no por página), el
# costo por tarjeta es ~0.8ms sin importar el tamaño de página, así que 200/
# 500/1000 son igual de viables que un tamaño chico -- no hace falta limitar
# las opciones a un número pequeño.
# Filtros de la pestaña Unidades: (columna de df_unidades_base, título).
_FILTROS_UNIDADES = [
    ('Estado Comercial', "Comercial"), ('Estado Activación', "Activación"),
    ('Tipo de Facturación', "Facturación"), ('Forma de Contrato', "Contrato"),
    ('Tipo de Servicio', "Servicio"), ('Flota VC', "Flota VC"),
]


_COLUMNAS_TABLA_FLOTA = [('VIN', 'VIN'), ('Modelo', 'Modelo'), ('Tipo de Servicio', 'Servicio'),
                         ('Estado Comercial', 'Comercial'), ('Estado Activación', 'Activación'),
                         ('Forma de Contrato', 'Contrato'), ('Tipo de Facturación', 'Facturación'),
                         ('Término Contrato', 'Término')]


_OPCIONES_TAMANO_PAGINA = [200, 500, 1000]


_TARJETAS_POR_PAGINA = 200  # valor por defecto, usado solo como fallback


# Pestañas subrayadas, mismo aspecto que las sub-pestañas de Comercial
QSS_PESTANAS_SUBRAYADAS = f"""
    QPushButton {{ background: transparent; color: {TEXT_SECONDARY}; padding: 10px 16px; border: none;
                   border-bottom: 3px solid transparent; border-radius: 0; font-weight: 600; font-size: 13px; }}
    QPushButton:hover:!checked {{ color: {TEXT_PRIMARY}; }}
    QPushButton:checked {{ color: {PRIMARY}; border-bottom: 3px solid {PRIMARY}; }}
"""


QSS_CONTENEDOR_PESTANAS = f"QFrame#barraPestanasGeneral {{ background: transparent; border: none; border-bottom: 1px solid {BORDER}; }}"


QSS_PESTANAS_CLARAS = f"""
    QPushButton {{ background: transparent; color: {TEXTO_SOBRE_AZUL}; padding: 10px 13px; border: none;
                   border-bottom: 3px solid transparent; border-radius: 0; font-weight: 600; font-size: 13px; }}
    QPushButton:hover:!checked {{ color: white; }}
    QPushButton:focus:!checked {{ color: white; background: rgba(255,255,255,0.14); }}
    QPushButton:checked {{ color: white; border-bottom: 3px solid white; }}
"""


QSS_PESTANAS_CLARAS_JUSTAS = QSS_PESTANAS_CLARAS.replace("10px 13px", "10px 8px")


# Pestañas de la caja izquierda: la elegida queda como hoja blanca unida al contenido, como en el Dashboard
QSS_PESTANAS_HOJA = f"""
    QPushButton {{ background: transparent; color: {TEXTO_SOBRE_AZUL}; padding: 10px 14px; border: none;
                   border-top-left-radius: 10px; border-top-right-radius: 10px; border-bottom-left-radius: 0;
                   border-bottom-right-radius: 0; font-weight: 600; font-size: 13px; }}
    QPushButton:hover:!checked {{ color: white; background: rgba(255,255,255,0.08); }}
    QPushButton:focus:!checked {{ color: white; background: rgba(255,255,255,0.2); }}
    QPushButton:checked {{ color: {TEXT_PRIMARY}; background: {SURFACE}; }}
"""

QSS_PESTANAS_HOJA_JUSTAS = QSS_PESTANAS_HOJA.replace("10px 14px", "10px 9px")


QSS_CONTENEDOR_PESTANAS_CLARO ="QFrame#barraPestanasGeneral { background: transparent; border: none; }"


_ACCENT_GENERAL = AZUL


QSS_TARJETAS_CLIENTE = f"""
    * {{ background: transparent; }}
    QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
    QFrame#general_cliente_card {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
    QFrame#general_cliente_card:hover {{ border: 1px solid {_ACCENT_GENERAL}; background-color: #F3F5F9; }}
    QFrame#general_cliente_card[seleccionado="true"] {{ background-color: #F3F5F9; border: 2px solid {_ACCENT_GENERAL}; }}
    QFrame#general_cliente_card[duplicado="true"] {{ background-color: #FEE2E2; border: 1px solid #FCA5A5; }}
    QFrame#general_cliente_card[duplicado="true"]:hover {{ border: 1px solid {DANGER}; background-color: #FEE2E2; }}
    QFrame#general_cliente_card[duplicado="true"][seleccionado="true"] {{ background-color: #FEE2E2; border: 2px solid {DANGER}; }}
    QFrame#general_cliente_card QLabel {{ border: none; }}
    QLabel#gc_nombre {{ font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY}; }}
    QLabel#gc_sub {{ font-size: 10px; color: {TEXT_SECONDARY}; }}
    QLabel#gc_badge {{ background-color: {VOLVO_BLUE}; color: white; font-size: 9px; font-weight: bold; padding: 3px 8px; border-radius: 8px; }}
    QLabel#gc_badge_encontrados {{ background-color: #DFF3E6; color: #1E7E43; border: 1px solid #BFE5CB; font-size: 9px; font-weight: bold; padding: 2px 8px; border-radius: 8px; }}
"""


QSS_TARJETAS_UNIDAD = f"""
    * {{ background: transparent; }}
    QToolTip {{ background-color: {SURFACE}; color: {TEXT_PRIMARY}; border: 1px solid {LINEA_AZUL}; padding: 4px 8px; font-size: 12px; }}
    QFrame#general_unidad_card {{ background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
    QFrame#general_unidad_card:hover {{ border: 1px solid {_ACCENT_GENERAL}; }}
    QFrame#general_unidad_card[seleccionado="true"] {{ background-color: #F3F5F9; border: 2px solid {_ACCENT_GENERAL}; }}
    QLabel#gu_nombre {{ font-size: 12px; font-weight: bold; color: {TEXT_PRIMARY}; border: none; }}
    QLabel#gu_industria {{ font-size: 10px; color: {TEXT_SECONDARY}; border: none; }}
"""


_FICHA_VIN_SECCIONES = ("Empresa", "Unidad", "Operativa", "Facturación y CM")


_RESUMEN_CELDA_FLOTA = {
    'ACTIVACIÓN PENDIENTE': 'Act. pendiente', 'ACTIVACION PENDIENTE': 'Act. pendiente', 'BAJA SOLICITADA': 'Baja solic.',
    'FACTURACIÓN MANUAL': 'FactMan', 'FACTURACION MANUAL': 'FactMan', 'NO ENTREGADO': 'No entregado',
}


_SIGLAS_FLOTA = ('CMG', 'CMS', 'CMB', 'CM')


# Excel de una flota (se comparte con el cliente): datos del contrato y, si tiene CM, los del 3PC
_COLUMNAS_EXPORT_FLOTA = (
    'RAZÓN SOCIAL', 'VIN', 'CHASIS', 'MODELO', 'TIPO DE SERVICIO', 'ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL',
    'FORMA DE CONTRATO', 'TIPO DE FACTURACION', 'INICIO CONTRATO', 'DURACIÓN (MESES)', 'TÉRMINO CONTRATO',
    'FECHA DE BAJA', 'N CONTRATO 3PC', 'TIPO DE CM', 'ESTADO DEL CM', 'FECHA INICIO CM', 'FECHA TERMINO CM', 'PAGO CM')


class _DelegadoTextoSinInvertir(QStyledItemDelegate):
    """Al seleccionar una fila el texto conserva su color en vez de volverse blanco."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        color = brush.color() if hasattr(brush, 'color') else QColor(TEXT_PRIMARY)
        option.palette.setColor(QPalette.ColorRole.HighlightedText, color)


class _DelegadoChipsUnidades(_DelegadoTextoSinInvertir):
    """Las celdas con fondo (BackgroundRole) se pintan como chip con punto; el texto sigue en la celda y se puede copiar."""

    def paint(self, painter, option, index):
        fondo = index.data(Qt.ItemDataRole.BackgroundRole)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        texto = opt.text
        if fondo is None or not texto:
            super().paint(painter, option, index)
            return
        opt.text = ""
        opt.backgroundBrush = QBrush()
        widget = opt.widget
        (widget.style() if widget is not None else QApplication.style()).drawControl(
            QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        color = index.data(Qt.ItemDataRole.ForegroundRole)
        color = color.color() if hasattr(color, 'color') else QColor(TEXT_PRIMARY)
        fuente = QFont(opt.font)
        fuente.setBold(True)
        fuente.setPointSizeF(max(7.0, fuente.pointSizeF() - 0.5))
        fm = QFontMetrics(fuente)
        punto, separacion, relleno, alto = 6, 6, 10, 22
        extra = 2 * relleno + punto + separacion
        visible = fm.elidedText(texto, Qt.TextElideMode.ElideRight, max(30, opt.rect.width() - 12) - extra)
        ancho = min(max(30, opt.rect.width() - 12), extra + fm.horizontalAdvance(visible))
        x = opt.rect.x() + 6
        y = opt.rect.y() + (opt.rect.height() - alto) / 2
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(fondo))
        painter.drawRoundedRect(QRectF(x, y, ancho, alto), alto / 2, alto / 2)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(x + relleno, y + (alto - punto) / 2, punto, punto))
        painter.setPen(color)
        painter.setFont(fuente)
        painter.drawText(QRectF(x + relleno + punto + separacion, y, ancho - extra, alto),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, visible)
        painter.restore()


def _resumir_celda_flota(columna, valor):
    """Texto corto para la tabla de Unidades de la flota (el completo queda en el tooltip)."""
    if columna == 1:
        return valor.upper()
    if columna in (0, 7) or not valor:
        return valor
    texto = valor.strip()
    corto = _RESUMEN_CELDA_FLOTA.get(texto.upper())
    if corto:
        return corto
    if texto.upper() in _SIGLAS_FLOTA:
        return texto.upper()
    if texto.isupper():
        texto = texto.capitalize()
    return texto.replace(" + ", "+")
