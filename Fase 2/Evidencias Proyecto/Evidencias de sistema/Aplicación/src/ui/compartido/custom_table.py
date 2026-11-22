import time
import pandas as pd
import numpy as np
from datetime import datetime
from PyQt6.QtWidgets import (QTableView, QMenu, QApplication, QFileDialog,
                             QMessageBox, QComboBox, QStyledItemDelegate, QHeaderView,
                             QProgressDialog, QStyleOptionViewItem)
from PyQt6.QtCore import Qt, pyqtSignal, QAbstractTableModel, QModelIndex, QSettings, QRect, QRectF, QPoint, QSize, QThread, QTimer
from PyQt6.QtGui import QColor, QAction, QTextDocument, QPageLayout, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath
from PyQt6.QtPrintSupport import QPrinter
import openpyxl
from openpyxl.styles import PatternFill, Font as xlFont, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.cell import WriteOnlyCell
from copy import copy

from src.theme.colors import *
from src.theme.theme_manager import ThemeManager
from src.theme import tema
from src.ui.compartido.menu_contextual import crear_menu, texto_corto
from src.services import comercial_services

_COLUMNAS_CATALOGO = frozenset(['ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL', 'FORMA DE CONTRATO', 'TIPO DE SERVICIO', 'VOLVO CONNECT', 'DEVUELTO', 'GESTIÓN', 'MOTIVO'])
_COLUMNAS_NEGRITA = frozenset(['ESTADO COMERCIAL', 'ESTADO DE ACTIVACIÓN ACTUAL', 'TÉRMINO CONTRATO', 'FECHA DE BAJA',
                               'VOLVO CONNECT', 'CON VOLVO CONNECT', 'DEVUELTO', 'DEVUELTAS', 'Registro Maestro'])
_COLUMNAS_CONTEO_AMBAR = ('CON VOLVO CONNECT', 'DEVUELTAS')
_FONDO_VOLVO_CONNECT, _TEXTO_VOLVO_CONNECT = "#FEF3C7", "#92400E"
# (valores, fondo, texto) en orden de prioridad
_GRUPOS_CATALOGO = [
    (["ACTIVO", "CONECTADO", "ENTREGADO"], "#D1FAE5", "#065F46"),
    (["VENCIDO", "DESCONECTADO", "ERROR", "TERMINADO", "ELIMINADO", "NO ENTREGADO", "SIN PLAN"], "#FEE2E2", "#991B1B"),
    (["ACTIVANDO", "PENDIENTE CORTE", "POR CONECTAR", "PROVISION", "EN TRÁNSITO", "TRAE VC", "DEVUELTO"], "#FEF3C7", "#92400E"),
    (["CM", "VENTA", "FULL", "MEDIO"], "#DBEAFE", "#1E40AF"),
    (["NO APLICA", "SIN FLOTA"], "#F3F4F6", "#4B5563"),
    # Estados de gestión de Oportunidades CM
    (["NEGOCIACIÓN"], "#DBEAFE", "#1E40AF"),
    (["ESPERA"], "#FEF3C7", "#92400E"),
    (["SIN GESTIÓN"], "#E9EDF3", "#475569"),
    # Motivos de Oportunidades CM
    (["CONTRATO EXPIRADO", "TÉRMINO VENCIDO SIN PAGO"], "#FEE2E2", "#991B1B"),
    (["DATOS VACÍOS EN 3PC"], "#FEF3C7", "#92400E"),
    (["POR VENCER SIN PAGO"], "#FFEDD5", "#C2410C"),
    (["AUSENTE DE 3PC"], "#EDE9FE", "#5B21B6"),
    (["DATOS CM ANTIGUOS"], "#F3F4F6", "#4B5563"),
]
_FONDO_CATALOGO = {}
_TEXTO_CATALOGO = {}
for _valores, _fondo, _texto in _GRUPOS_CATALOGO:
    for _v in _valores:
        _FONDO_CATALOGO.setdefault(_v, QColor(_fondo))
        _TEXTO_CATALOGO.setdefault(_v, QColor(_texto))
# Chips de MODELO (solo en los modelos que lo piden con `_chips_modelo`): azules y grises de la marca, sin otros colores
_COLORES_MODELO = {
    "FH": ("#1B365D", "#FFFFFF"), "FHE": ("#2F5597", "#FFFFFF"), "FHL": ("#5B84C4", "#FFFFFF"),
    "FM": ("#D6E4F7", "#1B365D"), "FME": ("#B5CCEB", "#1B365D"), "FML": ("#8FAEDB", "#10264A"),
    "FMX": ("#4B5563", "#FFFFFF"), "FL": ("#E5E7EB", "#374151"), "FE": ("#CBD5E1", "#1F2937"),
    "VM": ("#94A3B8", "#0F172A"), "N/A": ("#F3F4F6", "#6B7280"),
}
_COLOR_MODELO_OTRO = ("#F3F4F6", "#4B5563")
_ROLES_CON_VALOR = frozenset([Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole,
                              Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole])
_ALINEACION_CELDA = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
_QCOLORES = {}
# Padding izquierdo+derecho de QTableView::item (ver VolvoTableWidget._setup_style).
_PADDING_H_CELDA = 12
# Margen extra al decidir, sin medir con el delegate, que un texto cabe en una línea.
_HOLGURA_UNA_LINEA = 16


_COLUMNAS_NOMBRE_CLIENTE = frozenset({'FLOTA VC', 'FLOTA VC 2', 'FLOTA', 'RAZÓN SOCIAL', 'CLIENTE', 'EMPRESA'})


def _qcolor(codigo):
    # Copia de un QColor ya parseado: evita reinterpretar el texto en cada data()
    base = _QCOLORES.get(codigo)
    if base is None:
        base = _QCOLORES[codigo] = QColor(codigo)
    return QColor(base)


class PandasTableModel(QAbstractTableModel):
    def __init__(self, df=pd.DataFrame(), parent=None, alineacion=None):
        super().__init__(parent)
        self._df = df.copy()
        self._edited_cells = set()
        # Alineación de celda por instancia (por defecto _ALINEACION_CELDA,
        # izquierda): permite que una tabla puntual (ej. subpestañas nuevas
        # de Comercial) centre su contenido sin afectar al resto de tablas
        # de la app, que comparten esta misma clase.
        self._alineacion = alineacion if alineacion is not None else _ALINEACION_CELDA
        self._chips_modelo = False
        # Cache vectorizada de comercial_services.clasificar_vigencia_contrato()
        # para la columna TÉRMINO CONTRATO (auditoria de rendimiento, fase 3,
        # 21-09-2026): antes cada celda de esa columna reconstruia un
        # DataFrame de 1 fila y volvia a parsear la fecha en cada data()
        # (ForegroundRole se pide por cada celda visible en cada repintado:
        # scroll, resize, seleccion). Se calcula una sola vez para toda la
        # columna -- misma fuente que ya usan ComercialModule.filter_table()/
        # _refresh_new_ui_data() para los KPI -- y se reutiliza mientras no
        # cambien los datos (set_data) ni el dia calendario (para que
        # 'vencido'/'por vencer' no queden desactualizados si la tabla queda
        # abierta de un dia para otro sin refrescarse).
        self._clasif_termino_df = None
        self._clasif_termino_hoy = None
        self._colores_termino = None
        # Columnas de flota/cliente en negrita y alineadas a la izquierda (opt-in por tabla)
        self._destacar_nombres = False
        self._columnas_cache = {}
        # Quien modifica el DataFrame en el lugar avisa con alguna de estas señales: la caché de celdas se descarta
        for senal in (self.dataChanged, self.layoutChanged, self.modelReset, self.rowsInserted,
                      self.rowsRemoved, self.columnsInserted, self.columnsRemoved):
            senal.connect(self._descartar_cache)

    def destacar_columnas_cliente(self, activo=True):
        self._destacar_nombres = activo

    @staticmethod
    def _cdb_comercial_multiple(val):
        """True si la celda de CDB COMERCIAL lista más de un CDB; None si está vacía."""
        if val.strip() in ('', '-'):
            return None
        return ',' in val

    def _descartar_cache(self, *_):
        self._columnas_cache = {}

    def _valor_celda(self, row, col):
        """Valor de la celda sin pasar por DataFrame.iat, que arma una Series por lectura
        y se pedía por cada celda visible en cada repintado."""
        valores = self._columnas_cache.get(col)
        if valores is None:
            valores = self._columnas_cache[col] = self._df.iloc[:, col].to_numpy(dtype=object)
        return valores[row]

    def set_data(self, df):
        self.beginResetModel()
        self._df = df.copy()
        self._columnas_cache = {}
        self._edited_cells.clear()
        self._clasif_termino_df = None
        self._clasif_termino_hoy = None
        self._colores_termino = None
        self.endResetModel()

    def _color_termino_contrato(self, row):
        """Color de TÉRMINO CONTRATO según clasificar_vigencia_contrato().
        Se calcula para toda la columna solo la primera vez, o si cambió el
        día calendario desde el último cálculo; antes cada celda armaba un
        Series con .iloc[row] en cada repintado."""
        hoy = pd.Timestamp(datetime.now().date())
        if self._clasif_termino_df is None or self._clasif_termino_hoy != hoy or self._colores_termino is None:
            self._clasif_termino_df = comercial_services.clasificar_vigencia_contrato(self._df, hoy=hoy)
            self._clasif_termino_hoy = hoy
            c = self._clasif_termino_df
            self._colores_termino = np.select(
                [c['es_mensual'].astype(bool), ~c['fecha_valida'].astype(bool),
                 c['vencido'].astype(bool), c['por_vencer'].astype(bool)],
                [SUCCESS, TEXT_MUTED, DANGER, WARNING], default=SUCCESS)
        return _qcolor(self._colores_termino[row])

    def get_df(self):
        # Quien pide el DataFrame puede escribirlo en el lugar (Contratos, Contactos, Provisiones)
        self._columnas_cache = {}
        return self._df
    def rowCount(self, parent=QModelIndex()): return len(self._df)
    def columnCount(self, parent=QModelIndex()): return len(self._df.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        valor = self._data_claro(index, role)
        if valor is not None and tema.es_oscuro():
            if role == Qt.ItemDataRole.BackgroundRole: return tema.fondo(valor)
            if role == Qt.ItemDataRole.ForegroundRole: return tema.texto(valor)
        return valor

    def _data_claro(self, index, role):
        if not index.isValid(): return None
        row, col = index.row(), index.column()

        # Roles que no dependen del valor: se resuelven sin leer el DataFrame.
        if role not in _ROLES_CON_VALOR:
            destacada = self._destacar_nombres and str(self._df.columns[col]).upper() in _COLUMNAS_NOMBRE_CLIENTE
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) if destacada else self._alineacion
            if role == Qt.ItemDataRole.FontRole:
                if destacada or (row, col) in self._edited_cells or self._df.columns[col] in _COLUMNAS_NEGRITA:
                    font = QFont(); font.setBold(True); return font
            return None

        col_name = self._df.columns[col]
        raw_val = self._valor_celda(row, col)
        val = "" if pd.isna(raw_val) else str(raw_val)

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole): return val
        elif role == Qt.ItemDataRole.BackgroundRole:
            if col_name == 'CDB COMERCIAL':
                multiple = self._cdb_comercial_multiple(val)
                if multiple is not None:
                    return QColor("#FDE5E5" if multiple else "#D1FAE5")
            if col_name == 'MODELO' and self._chips_modelo and val not in ('', '-'):
                return QColor(_COLORES_MODELO.get(val.upper(), _COLOR_MODELO_OTRO)[0])
            if col_name in _COLUMNAS_CONTEO_AMBAR and val not in ('', '0'):
                return QColor(_FONDO_VOLVO_CONNECT)
            # ESTADO DE ENTREGA (21-09-2026, ver docs/07 §3): no es un catálogo de
            # estados, es una fecha (o '-') -- se excluyó de este coloreado por
            # catálogo porque sus valores reales (DD-MM-YYYY / '-') nunca
            # coinciden con estos textos.
            if col_name in _COLUMNAS_CATALOGO:
                color = _FONDO_CATALOGO.get(val.upper())
                if color is not None: return QColor(color)
                if val != "": return _qcolor(BACKGROUND)
            return None
        # ForegroundRole
        if (row, col) in self._edited_cells: return _qcolor(WARNING)
        if col_name == 'MODELO' and self._chips_modelo and val not in ('', '-'):
            return QColor(_COLORES_MODELO.get(val.upper(), _COLOR_MODELO_OTRO)[1])
        if col_name in _COLUMNAS_CATALOGO:
            color = _TEXTO_CATALOGO.get(val.upper())
            if color is not None: return QColor(color)
            if val != "": return _qcolor(TEXT_SECONDARY)
        elif col_name in _COLUMNAS_CONTEO_AMBAR and val not in ('', '0'):
            return QColor(_TEXTO_VOLVO_CONNECT)
        elif col_name == 'CDB COMERCIAL' and self._cdb_comercial_multiple(val) is not None:
            return _qcolor(DANGER if self._cdb_comercial_multiple(val) else SUCCESS)
        elif col_name == 'TÉRMINO CONTRATO': return self._color_termino_contrato(row)
        elif col_name == 'FECHA DE BAJA' and val: return _qcolor(DANGER)
        elif col_name in ['VIN', 'CHASIS']: return _qcolor(TEXT_MUTED)
        elif col_name == "NUEVO VALOR" and val: return _qcolor(SUCCESS)
        elif col_name == "VALOR ANTERIOR" and val: return _qcolor(DANGER)
        return _qcolor(TEXT_PRIMARY)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        # section puede venir fuera de rango si el header restauró un estado
        # guardado (VolvoTableWidget.set_table_id -> QHeaderView.restoreState)
        # con más columnas de las que trae el DataFrame actual (p.ej. el
        # Excel real perdió una columna desde la última vez que se guardó
        # ese estado): sin este guard, Qt sigue pidiendo secciones viejas y
        # el índice directo sobre self._df.columns lanza IndexError.
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self._df.columns):
                return self._df.columns[section]
            return None
        return None

    def flags(self, index):
        if not index.isValid(): return Qt.ItemFlag.NoItemFlags
        if self._df.columns[index.column()] in ['VIN', 'CHASIS', 'TÉRMINO CONTRATO']: return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsEditable

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and role == Qt.ItemDataRole.EditRole:
            row, col = index.row(), index.column()
            try:
                col_dtype = str(self._df.dtypes.iloc[col])
                if 'float' in col_dtype: value = float(value) if str(value).strip() != "" else np.nan
                elif 'int' in col_dtype: value = int(float(value)) if str(value).strip() != "" else 0
            except Exception: pass
                
            self._columnas_cache = {}
            try: self._df.iat[row, col] = value
            except Exception:
                col_name = self._df.columns[col]
                self._df[col_name] = self._df[col_name].astype(object)
                self._df.iat[row, col] = value
                
            self._edited_cells.add((row, col))
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.FontRole])
            return True
        return False

class ComboBoxDelegate(QStyledItemDelegate):
    def __init__(self, options_dict, parent=None):
        super().__init__(parent)
        self.options_dict = options_dict

    def createEditor(self, parent, option, index):
        col_name = index.model().headerData(index.column(), Qt.Orientation.Horizontal)
        if col_name in self.options_dict:
            editor = QComboBox(parent)
            editor.addItems(self.options_dict[col_name])
            
            # Inyectar la clase CSS corporativa en lugar de quemar estilos
            editor.setProperty("class", "combo_box")
            editor.style().polish(editor)
            
            return editor
        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            text = index.model().data(index, Qt.ItemDataRole.EditRole)
            idx = editor.findText(text)
            if idx >= 0: editor.setCurrentIndex(idx)
            else: editor.setCurrentText(text)
        else: super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox): model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)
        else: super().setModelData(editor, model, index)

class FilterHeaderView(QHeaderView):
    """Header horizontal con un pequeño botón-icono de filtro (estilo Excel)
    dibujado dentro de las secciones marcadas como filtrables. No reemplaza
    ningún comportamiento existente de QHeaderView (resize, move, menú
    contextual de clic derecho, saveState/restoreState) -- solo agrega el
    dibujo del botón y la detección de su clic izquierdo. Qué columnas son
    filtrables y cuáles tienen un filtro activo lo decide quien use la tabla
    (ver VolvoTableWidget.set_header_filterable_columns/set_header_active_columns),
    esta clase no conoce reglas de negocio."""

    filter_button_clicked = pyqtSignal(str, QPoint)

    BUTTON_SIZE = 16
    BUTTON_MARGIN = 6
    # Tamaño LÓGICO (independiente de DPI) del ícono dibujado dentro del
    # botón. No se debe leer QPixmap.width()/height() para centrarlo: en
    # pantallas con escalado de Windows (125%/150%/200%) qtawesome devuelve
    # un QPixmap con devicePixelRatio > 1, así que width()/height() son
    # píxeles de dispositivo (el doble, el triple...) y no la medida lógica
    # que realmente ocupa en pantalla -- usarlos ahí es lo que hacía que el
    # ícono se viera desplazado hacia arriba/izquierda de su botón.
    ICON_SIZE = 10

    # Padding horizontal del texto del encabezado (mismo valor que "padding:
    # 6px 8px" de QHeaderView::section en VolvoTableWidget._setup_style) y
    # margen vertical extra sumado al alto necesario cuando hay varias líneas.
    _WORD_WRAP_PADDING_H = 8
    _WORD_WRAP_PADDING_V = 10

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._filterable_columns = set()
        self._active_columns = set()
        self._icon_pixmap_inactive = None
        self._icon_pixmap_active = None
        # Ajuste de línea del encabezado (30-09-2026, a pedido explícito):
        # desactivado por defecto -- el resto de las tablas de la app sigue
        # con el encabezado en una sola línea con elipsis. Solo
        # ComercialModule.new_ui_table lo activa (ver set_word_wrap_habilitado).
        self._word_wrap_habilitado = False
        # Colores propios del encabezado con ajuste de línea (ver
        # set_estilo_encabezado). None = look estándar de la app.
        self._estilo_encabezado = None
        self.sectionResized.connect(self._actualizar_alto_header)

    def _ensure_icon_cache(self):
        # Se cachea el QPixmap una sola vez (y se regenera solo si cambia el
        # set de columnas activas) en vez de reconstruirlo en cada
        # paintSection, que se llama muy seguido (resize, scroll, hover).
        if self._icon_pixmap_inactive is None:
            self._icon_pixmap_inactive = ThemeManager.icon('fa5s.filter', color=TEXT_SECONDARY).pixmap(QSize(self.ICON_SIZE, self.ICON_SIZE))
        if self._icon_pixmap_active is None:
            self._icon_pixmap_active = ThemeManager.icon('fa5s.filter', color='white').pixmap(QSize(self.ICON_SIZE, self.ICON_SIZE))

    def set_word_wrap_habilitado(self, habilitado):
        """Activa/desactiva que el texto del encabezado se parta en varias
        líneas cuando no entra en el ancho actual de la columna, en vez de
        elidirse en una sola línea con "..." (30-09-2026, a pedido explícito
        para new_ui_table de Comercial: columnas como "ESTADO DE ACTIVACIÓN
        ACTUAL" quedaban con el título cortado al angostarlas). Recalcula el
        alto del header de inmediato; sectionResized (conectado en __init__)
        lo vuelve a recalcular cada vez que el usuario o el código
        redimensionan una columna."""
        self._word_wrap_habilitado = habilitado
        self._actualizar_alto_header()

    def set_estilo_encabezado(self, fondo_superior, fondo_inferior, texto, linea_inferior,
                              separador=None, grosor_linea=3, alto_minimo=0, espaciado_letras=0.0,
                              iconos_orden=False, radio_superior=0, texto_negrita_fuerte=False):
        """Colores propios para el encabezado con ajuste de línea (solo aplica
        con set_word_wrap_habilitado(True)): degradado vertical de fondo,
        línea inferior de acento, separador opcional entre columnas y, si
        `iconos_orden`, el ícono de orden de cada columna (lee el estado de
        orden de la tabla dueña, ver VolvoTableWidget._set_sort). Lo usa solo
        la bandeja de Comercial; el resto de las tablas no lo llama."""
        self._estilo_encabezado = {
            'fondo_superior': QColor(fondo_superior), 'fondo_inferior': QColor(fondo_inferior),
            'texto': QColor(texto), 'linea_inferior': QColor(linea_inferior),
            'separador': QColor(separador) if separador else None,
            'grosor_linea': grosor_linea, 'alto_minimo': alto_minimo,
            'espaciado_letras': espaciado_letras, 'iconos_orden': iconos_orden,
            'radio_superior': radio_superior, 'negrita_fuerte': texto_negrita_fuerte,
        }
        self._iconos_orden_cache = {}
        self._actualizar_alto_header()
        self.viewport().update()

    def _fuente_encabezado(self):
        font = QFont(self.font())
        font.setBold(True)
        estilo = self._estilo_encabezado
        if estilo and estilo.get('negrita_fuerte'):
            font.setWeight(QFont.Weight.Bold)
        if estilo and estilo['espaciado_letras']:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, estilo['espaciado_letras'])
        return font

    def _texto_partido_en_lineas(self, texto, ancho_disponible, fm):
        rect = fm.boundingRect(QRect(0, 0, max(1, ancho_disponible), 10_000),
                                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, texto)
        lineas = max(1, round(rect.height() / fm.lineSpacing()))
        return lineas

    def _actualizar_alto_header(self, *_args):
        if not self._word_wrap_habilitado:
            return
        estilo = self._estilo_encabezado
        fm = QFontMetrics(self._fuente_encabezado() if estilo else self.font())
        max_lineas = 1
        for i in range(self.count()):
            ancho = self.sectionSize(i)
            if ancho <= 0 or self.isSectionHidden(i):
                continue
            texto = self._column_name(i) or ""
            ancho_util = ancho - 2 * self._WORD_WRAP_PADDING_H
            max_lineas = max(max_lineas, self._texto_partido_en_lineas(texto, ancho_util, fm))
        nuevo_alto = max_lineas * fm.lineSpacing() + self._WORD_WRAP_PADDING_V
        if estilo:
            nuevo_alto = max(nuevo_alto + estilo['grosor_linea'], estilo['alto_minimo'])
        if self.height() != nuevo_alto:
            self.setFixedHeight(nuevo_alto)

    def set_filterable_columns(self, column_names):
        self._filterable_columns = set(column_names)
        self.viewport().update()

    def set_active_columns(self, column_names):
        self._active_columns = set(column_names)
        self.viewport().update()

    def _column_name(self, logical_index):
        model = self.model()
        if model is None:
            return None
        return model.headerData(logical_index, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)

    def _button_rect_for_section_rect(self, section_rect):
        # Centrado a partir del rect REAL de la sección (el mismo que Qt usa
        # para pintar, o el equivalente reconstruido en mousePressEvent) en
        # vez de asumir self.height(): así el botón queda centrado incluso si
        # el alto real de la sección no coincide con el alto del header.
        size = self.BUTTON_SIZE
        x = section_rect.x() + section_rect.width() - size - self.BUTTON_MARGIN
        y = section_rect.y() + (section_rect.height() - size) // 2
        return QRect(x, y, size, size)

    def _section_rect(self, logical_index):
        left = self.sectionViewportPosition(logical_index)
        width = self.sectionSize(logical_index)
        return QRect(left, 0, width, self.height())

    def _paint_section_wrapped(self, painter, rect, logical_index):
        # Reemplaza el texto de una sola línea con elipsis que dibuja el
        # QStyle nativo: mismo fondo/borde que QHeaderView::section (ver
        # VolvoTableWidget._setup_style), pero el texto se centra y se parte
        # en varias líneas con Qt.TextFlag.TextWordWrap.
        painter.save()
        estilo = self._estilo_encabezado
        if estilo is None:
            painter.fillRect(rect, tema.fondo("#F8F9FA"))
            painter.setPen(tema.fondo(BORDER))
            painter.drawLine(rect.bottomLeft(), rect.bottomRight())
            painter.setPen(tema.texto(TEXT_SECONDARY))
            font = QFont(self.font())
            font.setBold(True)
            painter.setFont(font)
            text_rect = rect.adjusted(self._WORD_WRAP_PADDING_H, 0, -self._WORD_WRAP_PADDING_H, 0)
        else:
            radio = estilo.get('radio_superior', 0)
            if radio:
                camino = QPainterPath()
                camino.addRoundedRect(QRectF(0, 0, self.viewport().width(), self.height() + 2 * radio), radio, radio)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setClipPath(camino)
            degradado = QLinearGradient(0, rect.top(), 0, rect.bottom())
            degradado.setColorAt(0.0, tema.fondo(estilo['fondo_superior']))
            degradado.setColorAt(1.0, tema.fondo(estilo['fondo_inferior']))
            painter.fillRect(rect, degradado)
            grosor = estilo['grosor_linea']
            painter.fillRect(QRect(rect.left(), rect.bottom() - grosor + 1, rect.width(), grosor),
                             tema.fondo(estilo['linea_inferior']))
            if estilo['separador'] is not None and self.visualIndex(logical_index) > 0:
                painter.setPen(estilo['separador'])
                painter.drawLine(rect.left(), rect.top(), rect.left(), rect.bottom() - grosor)
            painter.setPen(tema.texto(estilo['texto']))
            painter.setFont(self._fuente_encabezado())
            text_rect = rect.adjusted(self._WORD_WRAP_PADDING_H, 0, -self._WORD_WRAP_PADDING_H, -grosor)
            if estilo['iconos_orden']:
                text_rect = self._pintar_icono_orden(painter, rect, logical_index, grosor, text_rect)
        texto = self._column_name(logical_index) or ""
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, texto)
        painter.restore()

    ICONO_ORDEN = 10

    def _pintar_icono_orden(self, painter, rect, logical_index, grosor, text_rect):
        """Ícono de orden a la derecha de la sección (apagado si la columna no
        está ordenada). Devuelve el rect de texto recortado para no pisarlo."""
        tabla = self.parent()
        col_name = self._column_name(logical_index)
        orden = None
        if col_name is not None and getattr(tabla, '_sort_column', None) == col_name:
            orden = getattr(tabla, '_sort_order', None)
        if orden == Qt.SortOrder.AscendingOrder:
            clave, nombre_icono, color = 'asc', 'fa5s.sort-up', '#7DB2FF'
        elif orden == Qt.SortOrder.DescendingOrder:
            clave, nombre_icono, color = 'desc', 'fa5s.sort-down', '#7DB2FF'
        else:
            clave, nombre_icono, color = 'none', 'fa5s.sort', '#5FFFFFFF'
        if (self._estilo_encabezado or {}).get('negrita_fuerte'):
            color = '#2563EB' if clave != 'none' else '#6B7280'
            if tema.es_oscuro():
                color = tema.texto(color).name()
        clave_cache = (clave, color)
        if clave_cache not in self._iconos_orden_cache:
            self._iconos_orden_cache[clave_cache] = ThemeManager.icon(nombre_icono, color=color).pixmap(
                QSize(self.ICONO_ORDEN, self.ICONO_ORDEN))
        derecha = rect.right() - 8
        if col_name in self._filterable_columns:
            derecha -= self.BUTTON_SIZE + self.BUTTON_MARGIN
        x = derecha - self.ICONO_ORDEN
        y = rect.top() + (rect.height() - grosor - self.ICONO_ORDEN) // 2
        painter.drawPixmap(QRect(x, y, self.ICONO_ORDEN, self.ICONO_ORDEN), self._iconos_orden_cache[clave_cache])
        return text_rect.adjusted(0, 0, -(self.ICONO_ORDEN + 4), 0)

    def paintSection(self, painter, rect, logical_index):
        if self._word_wrap_habilitado:
            self._paint_section_wrapped(painter, rect, logical_index)
        else:
            super().paintSection(painter, rect, logical_index)
        col_name = self._column_name(logical_index)
        if col_name not in self._filterable_columns:
            return

        self._ensure_icon_cache()
        btn_rect = self._button_rect_for_section_rect(rect)
        active = col_name in self._active_columns

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing)
        if active:
            painter.setBrush(QColor(PRIMARY))
            painter.setPen(QColor(PRIMARY))
        else:
            painter.setBrush(tema.fondo(SURFACE))
            painter.setPen(tema.fondo(BORDER))
        painter.drawRoundedRect(btn_rect, 4, 4)

        icon_pixmap = self._icon_pixmap_active if active else self._icon_pixmap_inactive
        icon_x = btn_rect.x() + (btn_rect.width() - self.ICON_SIZE) // 2
        icon_y = btn_rect.y() + (btn_rect.height() - self.ICON_SIZE) // 2
        # Rect de DESTINO lógico explícito (no drawPixmap(x, y, pixmap)):
        # así Qt escala/posiciona respetando devicePixelRatio del pixmap sin
        # que tengamos que calcularlo nosotros.
        painter.drawPixmap(QRect(icon_x, icon_y, self.ICON_SIZE, self.ICON_SIZE), icon_pixmap)
        painter.restore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            logical_index = self.logicalIndexAt(event.pos())
            if logical_index >= 0:
                col_name = self._column_name(logical_index)
                if col_name in self._filterable_columns:
                    btn_rect = self._button_rect_for_section_rect(self._section_rect(logical_index))
                    if btn_rect.contains(event.pos()):
                        global_point = self.mapToGlobal(QPoint(btn_rect.left(), btn_rect.bottom()))
                        self.filter_button_clicked.emit(col_name, global_point)
                        event.accept()
                        return
        super().mousePressEvent(event)


# =========================================================
# EXPORTAR A EXCEL EN HILO DE FONDO (25-09-2026, corrige congelamiento real
# reportado en producción: "Vista Completa" de Comercial con ~12.000 filas
# dejaba la app sin responder varios segundos al armar los datos y podía
# colgarse indefinidamente al escribir el .xlsx, sin ningún aviso visual ni
# forma de seguir usando la app mientras tanto). VolvoTableWidget.
# export_to_excel() es compartido por Comercial, Contactos, Contratos,
# Historial, Instalaciones y Provisiones -- este hilo corrige el problema
# para los seis de una sola vez, sin duplicar la lógica en cada módulo.
#
# Antes, todo el trabajo (extraer ~filas×columnas celda por celda vía
# QModelIndex + reconstruir el Workbook + guardar en disco) corría en el
# hilo principal de Qt, sin QThread -- exactamente el mismo tipo de
# operación pesada que SaveExcelThread (comercial.py/operaciones.py) ya
# saca del hilo principal para los guardados. Se aplica el mismo patrón
# aquí: extraer directo del DataFrame del modelo (get_df(), sin el loop
# celda por celda de _extract_visible_data) y hacer el resto -- parseo
# numérico vectorizado + construcción del Workbook + wb.save() -- en un
# QThread, con progreso real emitido cada cierto número de filas.
# =========================================================
class ExportExcelThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str, str)  # (exito, filepath, mensaje_error)

    # Columnas numéricas/monetarias que llegan como texto formateado para
    # mostrarse en pantalla (ej. "$1.234.567", ver comercial.py filter_table)
    # y deben reconvertirse a número nativo de Excel -- no es un "doble
    # parseo" evitable: el DataFrame del modelo ya perdió el valor numérico
    # crudo al formatearlo para la UI (ver PAGO CM_NUM, que se descarta
    # antes de llegar al modelo), así que hay que reconstruirlo desde el
    # texto. Lo que sí se evita acá es hacerlo celda por celda en un loop
    # Python: se vectoriza con operaciones de pandas sobre la columna
    # completa de una sola vez.
    _COLUMNAS_NUMERICAS = {"DYNAFLEET", "CANTIDAD DE MESES", "MONTO PROVISIONADO", "VALOR PLAN", "VAR", "PAGO CM",
                           "PAGO CM ACTUAL", "PAGO DEL MES ANTERIOR", "UNIDADES", "VIGENTES", "PRECIO UF",
                           "PAGO CLP", "ULTIMO PAGO CM"}
    _COLUMNAS_MONETARIAS = {"DYNAFLEET", "MONTO PROVISIONADO", "VALOR PLAN", "VAR", "PAGO CM",
                            "PAGO CM ACTUAL", "PAGO DEL MES ANTERIOR", "PAGO CLP", "ULTIMO PAGO CM"}
    _VACIOS = {"", "-", "NAN", "NONE", "NAT", "<NA>"}

    _COLUMNAS_SIN_RESUMEN = ("VIN", "CHASIS", "RUT", "ID", "N CONTRATO", "N°", "CORREO", "OBSERVACIONES", "MOTIVO")
    _COLUMNAS_TOP = ("FLOTA VC", "RAZÓN SOCIAL", "CLIENTE", "CDB FLOTA")
    _AZUL = "003057"

    def __init__(self, df, filepath, parent=None, titulo=None, resaltado=None, con_resumen=True, hoja="Detalle",
                 depurar=False):
        """`resaltado`: (columna, {valor: (color_fondo, color_texto)}) pinta la fila completa de esos valores.
        `con_resumen=False` deja un solo libro con la tabla, para listas que se copian y pegan.
        `depurar=True` (export de una flota): no trae las columnas sin ningún dato, y en el resumen omite los
        "sin dato" de las fechas y los bloques de un solo valor."""
        super().__init__(parent)
        self.depurar = depurar
        if depurar:
            vacias = [c for c in df.columns
                      if df[c].astype(str).str.strip().str.upper().isin(self._VACIOS).all()]
            df = df.drop(columns=vacias)
        self.df = df
        self.filepath = filepath
        self.titulo = titulo or "Reporte"
        self.resaltado = resaltado
        self.con_resumen = con_resumen
        self.hoja = hoja

    @staticmethod
    def _parsear_columna_numerica(serie):
        """Misma lógica que la anterior _parse_excel_number, pero aplicada
        a toda la columna de una sola vez (pandas.Series.str.*) en vez de
        con un for por fila -- para miles de filas, una sola pasada
        vectorizada contra miles de llamadas Python individuales."""
        texto = serie.astype(str).str.strip()
        vacios = texto.str.upper().isin(["", "-", "NAN", "NONE", "$-"])

        es_negativo = texto.str.contains("-", regex=False)
        limpio = texto.str.replace("$", "", regex=False).str.replace(" ", "", regex=False).str.replace("-", "", regex=False)

        tiene_coma = limpio.str.contains(",", regex=False)
        # Con coma decimal (formato local: miles con punto, decimales con coma).
        con_coma = limpio.where(tiene_coma).str.replace(".", "", regex=False).str.replace(",", ".", regex=False)

        # Sin coma: punto como separador de miles (grupos de 3 dígitos) o
        # como decimal -- mismo criterio que la versión celda por celda.
        sin_coma = limpio.where(~tiene_coma)

        def _normalizar_sin_coma(v):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                return v
            if v.count(".") > 1:
                return v.replace(".", "")
            if v.count(".") == 1:
                parte_decimal = v.split(".")[1]
                if len(parte_decimal) == 3:
                    return v.replace(".", "")
            return v

        sin_coma = sin_coma.apply(_normalizar_sin_coma)
        normalizado = con_coma.fillna(sin_coma)

        valores = pd.to_numeric(normalizado, errors='coerce')
        valores = valores.where(~es_negativo, -valores)

        # Resultado mixto (numero, "" o el texto original) -- mismo contrato
        # que la función celda por celda anterior: valores vacíos quedan en
        # "", y un valor que no logra parsearse como número (caso raro, no
        # se espera en columnas numéricas reales) se conserva tal cual en
        # vez de perderse silenciosamente como NaN/blanco.
        resultado = pd.Series(index=serie.index, dtype=object)
        fallo_parseo = valores.isna() & ~vacios
        resultado[vacios] = ""
        resultado[fallo_parseo] = texto[fallo_parseo]
        validos = ~vacios & ~fallo_parseo
        resultado[validos] = valores[validos]
        return resultado

    def run(self):
        try:
            wb = openpyxl.Workbook(write_only=True)
            ws_resumen = wb.create_sheet("Resumen") if self.con_resumen else None
            ws_detalle = wb.create_sheet(self.hoja)
            self._estilos = {}
            valores_numericos = self._preparar_numericos()
            if ws_resumen is not None:
                self._escribir_resumen(ws_resumen, valores_numericos)
            self._escribir_detalle(ws_detalle, valores_numericos)
            wb.save(self.filepath)
            self.finished_signal.emit(True, self.filepath, "")
        except PermissionError:
            self.finished_signal.emit(False, self.filepath, "No se pudo guardar. Si el archivo está abierto en Excel, ciérralo e inténtalo de nuevo.")
        except Exception as e:
            self.finished_signal.emit(False, self.filepath, str(e))

    def _preparar_numericos(self):
        columnas_num = [h for h in self.df.columns if str(h).strip().upper() in self._COLUMNAS_NUMERICAS]
        return {col: self._parsear_columna_numerica(self.df[col]) for col in columnas_num}

    def _estilo(self, ws, tamano=10, negrita=False, color="1B2B4E", relleno=None, formato=None,
                horizontal=None, borde=None, ajustar=False):
        """StyleArray reutilizable: se arma una sola vez por combinación y se copia a cada celda
        (asignar fuente, relleno y borde celda por celda es lo que hacía lenta la exportación)."""
        clave = (tamano, negrita, color, relleno, formato, horizontal, borde, ajustar)
        if clave not in self._estilos:
            proto = WriteOnlyCell(ws)
            proto.font = xlFont(name="Calibri", size=tamano, bold=negrita, color=color)
            if relleno:
                proto.fill = PatternFill(start_color=relleno, end_color=relleno, fill_type="solid")
            if formato:
                proto.number_format = formato
            proto.alignment = Alignment(horizontal=horizontal, vertical="center", wrap_text=ajustar)
            if borde == "encabezado":
                proto.border = Border(bottom=Side(style="medium", color="E8A317"))
            elif borde == "fila":
                proto.border = Border(bottom=Side(style="hair", color="C9D3E0"))
            self._estilos[clave] = proto._style
        return self._estilos[clave]

    @staticmethod
    def _celda(ws, valor, estilo):
        celda = WriteOnlyCell(ws, value=valor)
        celda._style = copy(estilo)
        return celda

    @staticmethod
    def _ancho_columna(serie, encabezado):
        muestra = serie.head(400).astype(str)
        mayor = int(muestra.str.len().max()) if len(muestra) else 0
        return max(11, min(46, max(len(str(encabezado)) + 4, mayor + 3)))

    def _escribir_detalle(self, ws, valores_numericos):
        headers = list(self.df.columns)
        total_filas = len(self.df)
        df_export = self.df
        columnas_money = {h for h in headers if str(h).strip().upper() in self._COLUMNAS_MONETARIAS}

        columnas_fecha = {}
        for col in headers:
            if col in valores_numericos:
                continue
            texto = df_export[col].astype(str).str.strip()
            llenos = texto[~texto.str.upper().isin(["", "-", "NAN", "NONE", "NAT"])]
            if len(llenos) and llenos.str.fullmatch(r"\d{2}-\d{2}-\d{4}").all():
                columnas_fecha[col] = pd.to_datetime(texto.where(texto.isin(llenos)), format="%d-%m-%Y", errors="coerce")

        reglas = []
        if self.resaltado:
            lista = self.resaltado if isinstance(self.resaltado, list) else [self.resaltado]
            reglas = [(headers.index(col), valores) for col, valores in lista if col in headers]

        for i, col in enumerate(headers, start=1):
            ws.column_dimensions[get_column_letter(i)].width = self._ancho_columna(df_export[col], col)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{total_filas + 1}"
        ws.sheet_view.zoomScale = 90
        ws.sheet_properties.tabColor = "E8A317"
        ws.row_dimensions[1].height = 32

        estilo_encabezado = self._estilo(ws, 11, True, "FFFFFF", self._AZUL, None, "center", "encabezado", True)
        ws.append([self._celda(ws, h, estilo_encabezado) for h in headers])

        datos = []
        for col in headers:
            if col in valores_numericos:
                datos.append([int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v).is_integer() else v
                              for v in valores_numericos[col].tolist()])
            elif col in columnas_fecha:
                datos.append([None if pd.isna(f) else f.to_pydatetime() for f in columnas_fecha[col]])
            else:
                datos.append(["" if pd.isna(b) else str(b) for b in df_export[col]])

        tipos = []
        for col in headers:
            if col in columnas_fecha:
                tipos.append(("dd-mm-yyyy", "center"))
            elif col in columnas_money:
                tipos.append(('"$" #,##0', "right"))
            elif col in valores_numericos:
                tipos.append((None, "right"))
            else:
                tipos.append((None, None))

        emitir_cada = max(1, total_filas // 100)
        for pos in range(total_filas):
            fila = [columna[pos] for columna in datos]
            color_fila, resaltado_col = None, None
            for col_regla, valores in reglas:
                color_fila = valores.get(str(fila[col_regla]).strip())
                if color_fila:
                    resaltado_col = col_regla
                    break
            relleno = color_fila[0] if color_fila else ("F4F7FB" if pos % 2 else None)
            celdas = []
            for i, valor in enumerate(fila):
                formato, horizontal = tipos[i]
                if color_fila and i == resaltado_col:
                    estilo = self._estilo(ws, 10, True, color_fila[1], relleno, formato, horizontal, "fila")
                else:
                    estilo = self._estilo(ws, 10, False, "1B2B4E", relleno, formato, horizontal, "fila")
                celdas.append(self._celda(ws, valor, estilo))
            ws.append(celdas)
            if pos % 100 == 0:
                time.sleep(0.002)
            if pos % emitir_cada == 0 or pos == total_filas - 1:
                self.progress_signal.emit(int((pos + 1) / total_filas * 98))

    def _bloque_conteo(self, grilla, ws, fila, col, titulo, serie, total):
        """Tabla Valor / Cantidad / % de una columna en la grilla del resumen; devuelve la fila siguiente libre."""
        conteo = serie.value_counts()
        encabezado = self._estilo(ws, 10, True, "FFFFFF", self._AZUL)
        encabezado_der = self._estilo(ws, 10, True, "FFFFFF", self._AZUL, None, "right")
        grilla[(fila, col)] = (titulo, encabezado)
        grilla[(fila, col + 1)] = ("Cantidad", encabezado_der)
        grilla[(fila, col + 2)] = ("%", encabezado_der)
        for k, (valor, cantidad) in enumerate(conteo.items(), start=1):
            relleno = "F4F7FB" if k % 2 else None
            grilla[(fila + k, col)] = (valor, self._estilo(ws, 10, False, "1B2B4E", relleno))
            grilla[(fila + k, col + 1)] = (int(cantidad), self._estilo(ws, 10, False, "1B2B4E", relleno, "#,##0"))
            grilla[(fila + k, col + 2)] = ((cantidad / total) if total else 0, self._estilo(ws, 10, False, "1B2B4E", relleno, "0.0%"))
        return fila + len(conteo) + 2

    def _escribir_resumen(self, ws, valores_numericos):
        df = self.df
        total = len(df)
        ws.sheet_view.showGridLines = False
        ws.sheet_properties.tabColor = self._AZUL
        for letra, ancho in (("A", 38), ("B", 12), ("C", 9), ("D", 4), ("E", 38), ("F", 12), ("G", 9)):
            ws.column_dimensions[letra].width = ancho
        ws.row_dimensions[5].height = 32

        grilla = {}
        grilla[(1, 1)] = (self.titulo, self._estilo(ws, 20, True, self._AZUL))
        grilla[(2, 1)] = (f"Generado el {datetime.now().strftime('%d-%m-%Y %H:%M')} · Gestor SSCC · Hoja Detalle con filtros por columna",
                          self._estilo(ws, 10, False, "607D8B"))

        tarjetas = [("Registros", total)]
        for col, serie in sorted(valores_numericos.items(), key=lambda par: "ACTUAL" not in str(par[0]).upper()):
            if str(col).strip().upper() in self._COLUMNAS_MONETARIAS:
                tarjetas.append((f"Suma de {col}", pd.to_numeric(serie, errors="coerce").fillna(0).sum()))
        for i, (etiqueta, valor) in enumerate(tarjetas[:2]):
            col = 1 + i * 4
            grilla[(4, col)] = (etiqueta, self._estilo(ws, 10, False, "607D8B"))
            formato = '"$" #,##0' if etiqueta.startswith("Suma") else "#,##0"
            grilla[(5, col)] = (int(valor) if float(valor).is_integer() else float(valor),
                                self._estilo(ws, 22, True, self._AZUL, None, formato, "left"))

        bloques = []
        usadas = set()
        if "REVISAR" in df.columns:
            marcadas = df["REVISAR"].astype(str).str.strip()
            marcadas = marcadas[marcadas != ""]
            if len(marcadas):
                bloques.append(("Por revisar", marcadas))
                usadas.add("REVISAR")
        for col in self._COLUMNAS_TOP:
            if col in df.columns:
                serie = df[col].astype(str).str.strip().replace({"": "Sin dato", "-": "Sin dato", "nan": "Sin dato"})
                if self.depurar and serie[serie != "Sin dato"].nunique() < 2:
                    continue
                top = serie[serie != "Sin dato"].value_counts().head(10)
                if len(top) and top.iloc[0] > 1:
                    bloques.append((f"Top 10 · {col}", serie[serie.isin(top.index)]))
                    usadas.add(col)
                    break
        if "EJECUTIVO" in df.columns:
            serie = df["EJECUTIVO"].astype(str).str.strip().replace({"": "Sin dato", "-": "Sin dato", "nan": "Sin dato"})
            if serie.nunique() > 12:
                top = serie[serie != "Sin dato"].value_counts().head(10)
                bloques.append(("Top 10 · EJECUTIVO", serie[serie.isin(top.index)]))
                usadas.add("EJECUTIVO")
        for col in df.columns:
            nombre = str(col).strip().upper()
            if nombre in self._COLUMNAS_NUMERICAS or any(nombre.startswith(p) for p in self._COLUMNAS_SIN_RESUMEN):
                continue
            if col in usadas and (self.depurar or col == "REVISAR"):
                continue
            serie = df[col].astype(str).str.strip().str.upper().replace({"": "SIN DATO", "-": "SIN DATO", "NAN": "SIN DATO", "NAT": "SIN DATO"})
            if self.depurar and "FECHA" in nombre:
                serie = serie[serie != "SIN DATO"]
                if serie.empty:
                    continue
            distintos = serie.nunique()
            if 2 <= distintos <= 12 and not serie.str.fullmatch(r"\d{2}-\d{2}-\d{4}").all():
                bloques.append((f"Por {col}", serie))
            if len(bloques) >= 10:
                break

        fila = 8
        for i in range(0, len(bloques), 2):
            siguientes = [self._bloque_conteo(grilla, ws, fila, 1 + 4 * j, titulo, serie, total)
                          for j, (titulo, serie) in enumerate(bloques[i:i + 2])]
            fila = max(siguientes)

        ultima = max(f for f, _ in grilla)
        for f in range(1, ultima + 1):
            ws.append([self._celda(ws, *grilla[(f, c)]) if (f, c) in grilla else None for c in range(1, 8)])


class VolvoTableWidget(QTableView):
    action_eliminar = pyqtSignal(int, str)
    action_restaurar = pyqtSignal(int, str)
    action_editar_unidad = pyqtSignal(int, str)
    item_edited = pyqtSignal(int, str, str)
    sort_changed = pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.menu_type = "comercial"
        # Resolver opcional (fila -> VIN) para tablas donde la columna VIN
        # no viene en el modelo mostrado (p.ej. sub-pestañas de Comercial o
        # vistas agregadas de General): ver set_vin_resolver/_get_vin_for_row.
        self.vin_resolver = None
        # Estado de ordenamiento tipo Excel (ver apply_sort). None = sin
        # ordenamiento activo -> cada pantalla usa su orden original/por
        # defecto ya calculado en su propio filter_table().
        self._sort_column = None
        self._sort_order = None
        # Columna fijada actualmente (índice lógico) y su posición visual
        # original, para poder devolverla a su lugar al desfijar. Solo se
        # permite una columna fijada a la vez.
        self._pinned_col = None
        self._pinned_original_visual = None
        # False oculta "Fijar columna" del menú del encabezado
        self.permitir_fijar_columna = True
        # Columnas con texto en varias líneas (ver set_columnas_ajuste_texto).
        self._columnas_ajuste = frozenset()
        self._indices_ajuste = frozenset()
        self._cache_alto_ajuste = {}
        self._timer_ajuste_filas = QTimer(self)
        self._timer_ajuste_filas.setSingleShot(True)
        self._timer_ajuste_filas.timeout.connect(self._ajustar_alto_filas_texto)
        self.setHorizontalHeader(FilterHeaderView(Qt.Orientation.Horizontal, self))
        self._setup_style()
        self._setup_frozen_view()

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.horizontalHeader().customContextMenuRequested.connect(self._show_header_context_menu)
        # El ordenamiento por clic izquierdo en el encabezado está desactivado
        # a propósito: ordenar es una acción exclusiva del menú contextual
        # (clic derecho -> "Ordenar A -> Z" / "Ordenar Z -> A").

        self.horizontalHeader().setSectionsMovable(True)
        self.horizontalHeader().sectionDoubleClicked.connect(self.resizeColumnToContents)
        self.horizontalHeader().sectionResized.connect(self._on_section_resized)

    def _setup_style(self):
        self.setShowGrid(False); self.setAlternatingRowColors(True); self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalHeader().setVisible(False); self.verticalHeader().setDefaultSectionSize(38)
        self.horizontalHeader().setSectionsClickable(True)
        # Fuente/relleno reducidos + elide explícito: el contenido de las
        # celdas no debe desbordar el ancho de columna en ninguna tabla de
        # la app (todas comparten este componente).
        self.setTextElideMode(Qt.TextElideMode.ElideRight)

        # Sin QGraphicsDropShadowEffect: obligaba a repintar toda la tabla
        # fuera de pantalla con blur en cada scroll/hover/selección.
        self.setStyleSheet(f"""
            QTableView {{
                background-color: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
                font-family: 'Segoe UI', 'Inter', 'Roboto', sans-serif; font-size: 9pt;
                alternate-background-color: {FILA_ALTERNA_TABLA}; color: {TEXT_PRIMARY};
            }}
            QTableView::item {{ padding: 3px 6px; border-bottom: 1px solid #F3F4F6; border-right: none; }}
            QTableView::item:hover {{ background-color: {FILA_HOVER_TABLA}; }}
            QTableView::item:selected {{ background-color: {FILA_SELECCION_TABLA}; color: #0F172A; }}

            QHeaderView::section {{
                background-color: #F8F9FA; color: {TEXT_SECONDARY}; padding: 6px 8px;
                border: none; border-bottom: 1px solid {BORDER}; font-weight: bold; font-size: 9pt;
            }}
            QHeaderView::section:first {{ border-top-left-radius: 12px; }}
            QHeaderView::section:last {{ border-top-right-radius: 12px; }}
            
            QScrollBar:vertical {{ border: none; background: transparent; width: 8px; margin: 0px; }}
            QScrollBar::handle:vertical {{ background: #CBD5E1; min-height: 30px; border-radius: 4px; }}
            QScrollBar::handle:vertical:hover {{ background: {TEXT_MUTED}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            
            QScrollBar:horizontal {{ border: none; background: transparent; height: 8px; margin: 0px; }}
            QScrollBar::handle:horizontal {{ background: #CBD5E1; min-width: 30px; border-radius: 4px; }}
            QScrollBar::handle:horizontal:hover {{ background: {TEXT_MUTED}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
        """)

    # =========================================================
    # COLUMNA FIJADA (pin/freeze)
    # =========================================================
    # Técnica estándar de Qt para "congelar" una columna: una segunda
    # QTableView superpuesta a la izquierda, comparte modelo y selección con
    # la vista principal, muestra solo la columna fijada y sincroniza su
    # scroll vertical con la vista principal. La columna fijada además se
    # mueve visualmente a la posición 0 del header (moveSection) para que
    # quede a la izquierda; al desfijar vuelve a su posición original.
    def _setup_frozen_view(self):
        self.frozen_view = QTableView(self)
        self.frozen_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.frozen_view.setStyleSheet(self.styleSheet())
        self.frozen_view.setShowGrid(False)
        self.frozen_view.setAlternatingRowColors(True)
        self.frozen_view.verticalHeader().setVisible(False)
        self.frozen_view.verticalHeader().setDefaultSectionSize(38)
        self.frozen_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.frozen_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen_view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.frozen_view.setFrameShape(self.frozen_view.Shape.NoFrame)
        self.frozen_view.horizontalHeader().setSectionsClickable(True)
        self.frozen_view.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.frozen_view.horizontalHeader().customContextMenuRequested.connect(self._show_frozen_header_context_menu)
        self.frozen_view.horizontalHeader().sectionDoubleClicked.connect(self.resizeColumnToContents)
        self.frozen_view.hide()

        self.verticalScrollBar().valueChanged.connect(self.frozen_view.verticalScrollBar().setValue)
        self.frozen_view.verticalScrollBar().valueChanged.connect(self.verticalScrollBar().setValue)
        # Con filas de alto variable, la columna fijada debe seguir el alto de cada fila.
        self.verticalHeader().sectionResized.connect(self._sincronizar_alto_fila_fijada)

    def _sincronizar_alto_fila_fijada(self, fila, _alto_anterior, alto_nuevo):
        if self._pinned_col is not None:
            self.frozen_view.setRowHeight(fila, alto_nuevo)

    def _on_section_resized(self, logical_index, old_size, new_size):
        if logical_index == self._pinned_col:
            self.frozen_view.setColumnWidth(logical_index, new_size)
            self._update_frozen_geometry()
        if logical_index in self._indices_ajuste:
            self._programar_ajuste_filas()

    # =========================================================
    # TEXTO LARGO EN VARIAS LÍNEAS
    # =========================================================
    def set_columnas_ajuste_texto(self, nombres):
        """Cada fila crece lo necesario para que las columnas indicadas (por
        nombre) muestren su texto completo en varias líneas, sin cambiar el
        ancho de la columna. QTableView ya parte el texto en líneas (wordWrap),
        pero solo hasta donde alcanza el alto fijo de la fila."""
        self._columnas_ajuste = frozenset(nombres)
        self.setWordWrap(True)
        self._actualizar_indices_ajuste()
        self._programar_ajuste_filas()

    def setModel(self, model):
        super().setModel(model)
        if model is not None:
            model.modelReset.connect(self._on_modelo_reiniciado)
        self._actualizar_indices_ajuste()

    def _on_modelo_reiniciado(self):
        self._actualizar_indices_ajuste()
        self._programar_ajuste_filas()

    def _actualizar_indices_ajuste(self):
        modelo = self.model()
        if not self._columnas_ajuste or modelo is None:
            self._indices_ajuste = frozenset()
            return
        self._indices_ajuste = frozenset(
            c for c in range(modelo.columnCount())
            if modelo.headerData(c, Qt.Orientation.Horizontal) in self._columnas_ajuste)

    def _programar_ajuste_filas(self):
        if not self._indices_ajuste:
            return
        # Mientras se arrastra el borde de una columna se espera a que se detenga.
        arrastrando = bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
        self._timer_ajuste_filas.start(150 if arrastrando else 0)

    def _ajustar_alto_filas_texto(self):
        """Alto de cada fila = el mayor que necesiten sus columnas de ajuste
        (mínimo: el alto por defecto de la tabla). Se mide una sola vez cada
        texto distinto por ancho de columna, no cada celda: Vista Completa
        de Comercial tiene ~12.000 filas."""
        modelo = self.model()
        if not self._indices_ajuste or modelo is None or not hasattr(modelo, 'get_df'):
            return
        df = modelo.get_df()
        n = len(df)
        vheader = self.verticalHeader()
        if n == 0 or vheader.count() != n:
            return
        alto_base = vheader.defaultSectionSize()
        altos = np.full(n, alto_base, dtype=int)
        delegate = self.itemDelegate()
        opcion = QStyleOptionViewItem()
        self.initViewItemOption(opcion)
        if len(self._cache_alto_ajuste) > 50000:
            self._cache_alto_ajuste.clear()

        for col in self._indices_ajuste:
            if col >= len(df.columns) or self.isColumnHidden(col):
                continue
            nombre = df.columns[col]
            # Ancho útil real: la celda descuenta el padding horizontal de QTableView::item.
            ancho = self.columnWidth(col) - _PADDING_H_CELDA
            opcion.rect = QRect(0, 0, ancho, alto_base)
            fuente = modelo.data(modelo.index(0, col), Qt.ItemDataRole.FontRole)
            metricas = QFontMetrics(fuente.resolve(self.font()) if fuente is not None else self.font())
            limite_una_linea = ancho - _HOLGURA_UNA_LINEA

            textos = ["" if pd.isna(v) else str(v) for v in df.iloc[:, col].tolist()]
            primera_fila = {}
            for fila, texto in enumerate(textos):
                if texto not in primera_fila:
                    primera_fila[texto] = fila
            alto_por_texto = {}
            for texto, fila in primera_fila.items():
                if '\n' not in texto and metricas.horizontalAdvance(texto) <= limite_una_linea:
                    alto_por_texto[texto] = 0
                    continue
                clave = (nombre, ancho, texto)
                alto = self._cache_alto_ajuste.get(clave)
                if alto is None:
                    alto = delegate.sizeHint(opcion, modelo.index(fila, col)).height()
                    self._cache_alto_ajuste[clave] = alto
                alto_por_texto[texto] = alto
            altos = np.maximum(altos, np.fromiter((alto_por_texto[t] for t in textos), dtype=int, count=n))

        for fila in range(n):
            alto = int(altos[fila])
            if vheader.sectionSize(fila) != alto:
                vheader.resizeSection(fila, alto)

    def _update_frozen_geometry(self):
        if self._pinned_col is None:
            return
        border = self.frameWidth()
        width = self.columnWidth(self._pinned_col)
        height = self.viewport().height() + self.horizontalHeader().height()
        self.frozen_view.setGeometry(border, border, width, height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_frozen_geometry()

    def pin_column(self, logical_col):
        """Fija la columna a la izquierda de la tabla: la mueve a la primera
        posición y la mantiene visible al hacer scroll horizontal. Solo se
        permite una columna fijada a la vez."""
        if self._pinned_col == logical_col:
            return
        if self._pinned_col is not None:
            self.unpin_column(self._pinned_col)

        header = self.horizontalHeader()
        self._pinned_original_visual = header.visualIndex(logical_col)
        if self._pinned_original_visual != 0:
            header.moveSection(self._pinned_original_visual, 0)
        self._pinned_col = logical_col

        self.frozen_view.setModel(self.model())
        self.frozen_view.setSelectionModel(self.selectionModel())
        self.frozen_view.setSelectionBehavior(self.selectionBehavior())
        self.frozen_view.setSelectionMode(self.selectionMode())
        for c in range(self.model().columnCount()):
            self.frozen_view.setColumnHidden(c, c != logical_col)
        self.frozen_view.setColumnWidth(logical_col, self.columnWidth(logical_col))
        for fila in range(self.model().rowCount()):
            alto = self.rowHeight(fila)
            if self.frozen_view.rowHeight(fila) != alto:
                self.frozen_view.setRowHeight(fila, alto)
        self._update_frozen_geometry()
        self.frozen_view.show()
        self.frozen_view.raise_()

    def unpin_column(self, logical_col):
        """Quita la fijación de la columna y la devuelve a su posición
        original en el header."""
        if self._pinned_col != logical_col:
            return
        header = self.horizontalHeader()
        current_visual = header.visualIndex(logical_col)
        target_visual = self._pinned_original_visual if self._pinned_original_visual is not None else current_visual
        if current_visual != target_visual:
            header.moveSection(current_visual, target_visual)

        self._pinned_col = None
        self._pinned_original_visual = None
        self.frozen_view.hide()

    def set_table_id(self, table_id):
        self.table_id = table_id
        self.settings = QSettings("VolvoApp", "Dashboard")
        state = self.settings.value(f"table_state_{self.table_id}")
        if not state:
            return

        self.horizontalHeader().restoreState(state)

        # El estado guardado puede traer más (o menos) columnas de las que
        # tiene el modelo actual (p.ej. el Excel real perdió una columna
        # desde la última vez que se guardó ese estado): en ese caso el
        # header queda con secciones "fantasma" -- se descarta el estado
        # viejo y se limpia el QSettings para no repetir el desajuste en
        # cada apertura del módulo.
        modelo = self.model()
        if modelo and self.horizontalHeader().count() != modelo.columnCount():
            self.settings.remove(f"table_state_{self.table_id}")
            self.horizontalHeader().reset()

    def save_state(self):
        if hasattr(self, 'table_id') and self.table_id:
            state = self.horizontalHeader().saveState()
            self.settings.setValue(f"table_state_{self.table_id}", state)

    def set_vin_resolver(self, fn):
        """Registra fn(row_idx) -> str|None, usada por el menú contextual
        para resolver el VIN de una fila cuando la tabla no muestra la
        columna 'VIN' (ver _get_vin_for_row). El dueño de la tabla es quien
        conoce el DataFrame completo detrás de las columnas visibles."""
        self.vin_resolver = fn

    def set_model_and_delegate(self, model, dropdown_options=None):
        self.setModel(model)
        if dropdown_options: self.setItemDelegate(ComboBoxDelegate(dropdown_options, self))
        model.dataChanged.connect(self._on_data_changed)

    # =========================================================
    # FILTROS EN ENCABEZADO (ver FilterHeaderView)
    # =========================================================
    def set_header_filterable_columns(self, column_names):
        """Declara qué columnas (por nombre) muestran el botón de filtro en
        su encabezado. Quien llama es dueño de la lógica de filtrado; esta
        tabla solo dibuja el botón y avisa de los clics."""
        self.horizontalHeader().set_filterable_columns(column_names)

    def set_header_filter_active_columns(self, column_names):
        """Refresca qué columnas filtrables muestran el indicador visual de
        'filtro activo' (llamar cada vez que cambie el estado de filtros)."""
        self.horizontalHeader().set_active_columns(column_names)

    def _auto_adjust_columns(self):
        header = self.horizontalHeader(); self.resizeColumnsToContents()
        for i in range(self.model().columnCount()): self.setColumnWidth(i, max(self.columnWidth(i) + 10, 120)) 
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive); header.setStretchLastSection(True)

    def _on_data_changed(self, top_left, bottom_right, roles):
        if Qt.ItemDataRole.EditRole in roles or Qt.ItemDataRole.DisplayRole in roles:
            self.item_edited.emit(top_left.row(), self.model().headerData(top_left.column(), Qt.Orientation.Horizontal), self.model().data(top_left, Qt.ItemDataRole.EditRole))

    # =========================================================
    # ORDENAMIENTO TIPO EXCEL (clic de encabezado / menú contextual)
    # =========================================================
    # El estado vive aquí (por instancia de tabla), no en PandasTableModel:
    # el modelo se resetea por completo en cada filter_table()/set_data(), así
    # que guardar el orden en el modelo no serviría de nada. Cada pantalla
    # reaplica este estado llamando a self.table.apply_sort(df) dentro de su
    # propio filter_table(), justo antes de set_data() — no se toca ningún
    # DataFrame maestro ni el Excel, solo la copia local que ya arma cada
    # pantalla para pintar la tabla.
    def _set_sort(self, col_name, order):
        self._sort_column = col_name
        self._sort_order = order
        self._update_sort_indicator()
        self.sort_changed.emit()

    def _clear_sort(self):
        self._sort_column = None
        self._sort_order = None
        self._update_sort_indicator()
        self.sort_changed.emit()

    def has_active_sort(self):
        """True si el usuario ya eligió un orden manual (clic en el
        encabezado, ver _set_sort). Permite que una pantalla aplique su
        propio orden por defecto (p. ej. por urgencia) solo mientras no haya
        sido reemplazado por un clic explícito."""
        return self._sort_column is not None

    def _update_sort_indicator(self):
        header = self.horizontalHeader()
        if self._sort_column is None or not self.model():
            header.setSortIndicatorShown(False)
            return
        try:
            col_idx = self.model().get_df().columns.get_loc(self._sort_column)
        except (KeyError, AttributeError):
            header.setSortIndicatorShown(False)
            return
        header.setSortIndicatorShown(True)
        header.setSortIndicator(col_idx, self._sort_order)

    @staticmethod
    def _parse_number_like(val):
        """Interpreta un valor como número, entendiendo el formato usado en
        esta app: '$1.234' (miles con punto), '-$1.234' (negativo), '$-'
        (cero), '-' (sin dato, no es cero) y el texto de la columna calculada
        'DÍAS RESTANTES' ('Vencido hace N días' / 'Vence hoy' / 'N días
        restantes', ver comercial_services.parsear_dias_restantes) para que
        esa columna se pueda ordenar por magnitud numérica y no
        alfabéticamente. Devuelve None si no es numérico."""
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        s = str(val).strip()
        if s == "":
            return None
        if s == "$-":
            return 0.0
        if s.upper() in ["-", "NAN", "NONE", "<NA>"]:
            return None

        dias = comercial_services.parsear_dias_restantes(s)
        if dias is not None:
            return dias

        is_negative = s.startswith("-")
        s_clean = s[1:] if is_negative else s
        s_clean = s_clean.replace("$", "").replace(" ", "").strip()
        if s_clean == "":
            return None

        if "," in s_clean:
            s_clean = s_clean.replace(".", "").replace(",", ".")
        elif s_clean.count(".") > 1:
            s_clean = s_clean.replace(".", "")
        elif s_clean.count(".") == 1 and len(s_clean.split(".")[-1]) == 3:
            s_clean = s_clean.replace(".", "")

        try:
            parsed = float(s_clean)
            return -parsed if is_negative else parsed
        except ValueError:
            return None

    @classmethod
    def _build_sort_key(cls, serie):
        """Clave de orden 'tipo Excel': numérica si la mayoría de los valores
        parecen números, sino fecha si la mayoría parece DD-MM-YYYY, sino
        texto (sin distinguir mayúsculas/minúsculas)."""
        if serie.empty:
            return serie

        numeric_col = pd.to_numeric(serie.apply(cls._parse_number_like), errors='coerce')
        if numeric_col.notna().mean() > 0.5:
            return numeric_col

        date_col = pd.to_datetime(serie.astype(str).str.strip(), dayfirst=True, errors='coerce', format='mixed')
        if date_col.notna().mean() > 0.5:
            return date_col

        return serie.astype(str).str.strip().str.lower()

    def apply_sort(self, df):
        """Aplica sobre una COPIA de df el ordenamiento elegido por el
        usuario. Si no hay ordenamiento activo, o la columna ordenada ya no
        existe en este df (p.ej. cambió el set de columnas), devuelve df sin
        tocar: el 'orden original' es siempre el que ya trae el DataFrame
        que arma cada pantalla en su filter_table()."""
        if self._sort_column is None or self._sort_order is None:
            return df
        if df is None or df.empty or self._sort_column not in df.columns:
            return df

        ascending = self._sort_order == Qt.SortOrder.AscendingOrder
        sort_key = self._build_sort_key(df[self._sort_column])

        df_sorted = df.copy()
        df_sorted['__sort_key__'] = sort_key
        df_sorted = df_sorted.sort_values(by='__sort_key__', ascending=ascending, na_position='last', kind='mergesort')
        return df_sorted.drop(columns='__sort_key__').reset_index(drop=True)

    def _show_header_context_menu(self, pos):
        logical_col = self.horizontalHeader().logicalIndexAt(pos)
        if logical_col < 0: return
        self._show_header_menu_for_column(logical_col, self.horizontalHeader().mapToGlobal(pos))

    def _show_frozen_header_context_menu(self, pos):
        # La vista congelada (columna fijada) tiene su propio header
        # superpuesto: sin este handler, el clic derecho sobre esa columna
        # no abría ningún menú y no había forma de desfijarla.
        logical_col = self.frozen_view.horizontalHeader().logicalIndexAt(pos)
        if logical_col < 0: return
        self._show_header_menu_for_column(logical_col, self.frozen_view.horizontalHeader().mapToGlobal(pos))

    def _show_header_menu_for_column(self, logical_col, global_pos):
        col_name = self.model().headerData(logical_col, Qt.Orientation.Horizontal)

        menu = crear_menu(self)

        action_sort_asc = QAction(ThemeManager.icon('fa5s.sort-alpha-down', color=TEXT_SECONDARY), "Ordenar A → Z", self)
        action_sort_desc = QAction(ThemeManager.icon('fa5s.sort-alpha-up', color=TEXT_SECONDARY), "Ordenar Z → A", self)
        action_copy = QAction(ThemeManager.icon('fa5s.copy', color=TEXT_SECONDARY), f"Copiar columna '{col_name}'", self)
        action_resize_header = QAction(ThemeManager.icon('fa5s.compress-arrows-alt', color=TEXT_SECONDARY), "Ajustar al Encabezado", self)
        action_resize_content = QAction(ThemeManager.icon('fa5s.expand-arrows-alt', color=TEXT_SECONDARY), "Ajustar por Filas", self)

        is_pinned = logical_col == self._pinned_col
        action_pin = QAction(ThemeManager.icon('fa5s.thumbtack', color=TEXT_SECONDARY), "Fijar columna", self)
        action_unpin = QAction(ThemeManager.icon('fa5s.thumbtack', color=TEXT_SECONDARY), "Desfijar columna", self)

        menu.addAction(action_sort_asc)
        menu.addAction(action_sort_desc)
        menu.addSeparator()
        menu.addAction(action_copy)
        menu.addSeparator()
        menu.addAction(action_resize_header)
        menu.addAction(action_resize_content)
        if is_pinned:
            menu.addSeparator()
            menu.addAction(action_unpin)
        elif self.permitir_fijar_columna:
            menu.addSeparator()
            menu.addAction(action_pin)

        selected = menu.exec(global_pos)

        if selected == action_sort_asc:
            self._set_sort(col_name, Qt.SortOrder.AscendingOrder)

        elif selected == action_sort_desc:
            self._set_sort(col_name, Qt.SortOrder.DescendingOrder)

        elif selected == action_copy:
            copied_text = []
            for row in range(self.model().rowCount()):
                if not self.isRowHidden(row):
                    val = self.model().data(self.model().index(row, logical_col), Qt.ItemDataRole.EditRole)
                    copied_text.append(str(val) if val is not None else "")
            QApplication.clipboard().setText("\n".join(copied_text))

        elif selected == action_resize_header:
            fm = QFontMetrics(self.horizontalHeader().font())
            text_width = fm.horizontalAdvance(str(col_name))
            self.setColumnWidth(logical_col, text_width + 45)

        elif selected == action_resize_content:
            self.resizeColumnToContents(logical_col)

        elif selected == action_pin:
            self.pin_column(logical_col)

        elif selected == action_unpin:
            self.unpin_column(logical_col)

    def _get_vin_for_row(self, row):
        """VIN de una fila: primero busca la columna 'VIN' en el modelo
        mostrado; si no existe (columnas recortadas por la pantalla dueña,
        p.ej. sub-pestañas de Comercial o vistas agregadas de General), usa
        el vin_resolver registrado por esa pantalla (ver set_vin_resolver)."""
        for c in range(self.model().columnCount()):
            if self.model().headerData(c, Qt.Orientation.Horizontal) == "VIN":
                val = self.model().data(self.model().index(row, c))
                return str(val) if val not in (None, "") else "Desconocido"
        if callable(self.vin_resolver):
            try:
                val = self.vin_resolver(row)
            except Exception:
                val = None
            if val:
                return str(val)
        return "Desconocido"

    def _show_context_menu(self, pos):
        row = self.rowAt(pos.y())
        if row < 0: return

        vin_val = self._get_vin_for_row(row)

        # Filas objetivo para "Copiar VIN": si el clic cae dentro de una
        # selección múltiple existente, se copian todos los VIN de esa
        # selección (uno por línea); si no, solo la fila bajo el cursor.
        filas_seleccionadas = sorted({idx.row() for idx in self.selectionModel().selectedRows()}) \
            if self.selectionModel() else []
        filas_copiar = filas_seleccionadas if row in filas_seleccionadas and len(filas_seleccionadas) > 1 else [row]

        menu = crear_menu(self)

        # --- OPCIÓN DE COPIAR CELDA INDIVIDUAL ---
        index = self.indexAt(pos)
        action_copy_cell = None
        celda_seleccionada = ""

        if index.isValid():
            celda_seleccionada = str(index.data()).strip()
            if celda_seleccionada and celda_seleccionada != "None":
                action_copy_cell = menu.accion(f"Copiar: '{texto_corto(celda_seleccionada)}'")

        texto_copiar_vin = f"Copiar VIN ({len(filas_copiar)})" if len(filas_copiar) > 1 else "Copiar VIN"
        action_copy = menu.accion(texto_copiar_vin, 'fa5s.barcode')

        action_del, action_res, action_editar = None, None, None
        if self.menu_type == "eliminados":
            menu.addSeparator()
            action_res = QAction(ThemeManager.icon('fa5s.undo', color=SUCCESS), "Restaurar Fila", self)
            # Deshabilitado temporalmente: ExcelWriter no implementa un metodo
            # de restauracion (no existe "restore_row"). Antes esta accion
            # emitia action_restaurar igual y HistorialModule._handle_restaurar
            # terminaba lanzando AttributeError al confirmar. Mismo criterio
            # que HistorialModule.btn_clear (ver historial.py): se bloquea en
            # el punto de entrada en vez de dejar una funcionalidad rota.
            action_res.setEnabled(False)
            action_res.setToolTip("Función temporalmente deshabilitada: aún no existe un mecanismo de restauración seguro por módulo.")
            menu.addAction(action_res)

        selected = menu.exec(self.viewport().mapToGlobal(pos))
        
        if action_copy_cell and selected == action_copy_cell: QApplication.clipboard().setText(celda_seleccionada)
        elif selected == action_copy:
            vins_copiar = [vin_val] if filas_copiar == [row] else [self._get_vin_for_row(r) for r in filas_copiar]
            QApplication.clipboard().setText("\n".join(vins_copiar))
        elif selected == action_editar and action_editar is not None: self.action_editar_unidad.emit(row, str(vin_val))
        elif selected == action_del and action_del is not None: self.action_eliminar.emit(row, str(vin_val))
        elif selected == action_res and action_res is not None: self.action_restaurar.emit(row, str(vin_val))

    def _extract_visible_data(self):
        if not self.model(): return [], []
        headers = [self.model().headerData(c, Qt.Orientation.Horizontal) for c in range(self.model().columnCount()) if not self.isColumnHidden(c)]
        data = [[str(self.model().data(self.model().index(r, c))) for c in range(self.model().columnCount()) if not self.isColumnHidden(c)] for r in range(self.model().rowCount()) if not self.isRowHidden(r)]
        return headers, data

    def _obtener_dataframe_visible(self):
        """Igual que _extract_visible_data (solo columnas no ocultas por el
        usuario, ver isColumnHidden), pero lee directo el DataFrame del
        modelo (PandasTableModel.get_df()) en vez de armar una lista de
        strings celda por celda vía QModelIndex -- eso es lo que dejaba la
        app sin responder varios segundos en tablas de miles de filas (ver
        ExportExcelThread más arriba). Devuelve None si el modelo no expone
        get_df() (no debería pasar hoy: todas las tablas de la app usan
        PandasTableModel o una subclase), para que export_to_excel pueda
        recurrir al camino anterior como respaldo."""
        model = self.model()
        if model is None or not hasattr(model, 'get_df'):
            return None
        columnas_visibles = [
            model.headerData(c, Qt.Orientation.Horizontal)
            for c in range(model.columnCount()) if not self.isColumnHidden(c)
        ]
        if not columnas_visibles:
            return pd.DataFrame()
        return model.get_df()[columnas_visibles].copy()

    def export_to_excel(self, filename_prefix="Reporte"):
        # Export ya en curso (26-09-2026): evita lanzar un segundo hilo
        # sobre el mismo archivo si el usuario alcanza a hacer doble clic
        # mientras el primero todavía está escribiendo.
        if getattr(self, '_export_excel_thread', None) is not None and self._export_excel_thread.isRunning():
            QMessageBox.information(self, "Exportar", "Ya hay una exportación en curso. Espera a que termine.")
            return

        df_visible = self._obtener_dataframe_visible()
        if df_visible is None:
            # Respaldo (modelo sin get_df, no debería ocurrir hoy): mismo
            # comportamiento síncrono de siempre, mejor que no exportar nada.
            headers, data = self._extract_visible_data()
            if not data: return QMessageBox.warning(self, "Exportar", "No hay datos visibles.")
            df_visible = pd.DataFrame(data, columns=headers)
        if df_visible.empty:
            return QMessageBox.warning(self, "Exportar", "No hay datos visibles.")

        filepath, _ = QFileDialog.getSaveFileName(self, "Guardar Excel", f"{filename_prefix}.xlsx", "Archivos Excel (*.xlsx)")
        if not filepath:
            return

        # La construcción del Workbook y el guardado (I/O a disco, lento si la
        # carpeta está en OneDrive/SharePoint) corren en un QThread; el avance
        # se ve en una tarjeta flotante que no bloquea la pantalla.
        from src.ui.compartido.exportacion import iniciar_exportacion
        iniciar_exportacion(self, df_visible, filepath, titulo=str(filename_prefix).replace("_", " "),
                            resaltado=getattr(self, 'resaltado_excel', None))

    def export_to_pdf(self, filename_prefix="Reporte"):
        headers, data = self._extract_visible_data()
        if not data: return QMessageBox.warning(self, "Exportar", "No hay datos visibles.")
        filepath, _ = QFileDialog.getSaveFileName(self, "Guardar PDF", f"{filename_prefix}.pdf", "Archivos PDF (*.pdf)")
        if filepath:
            try:
                printer = QPrinter(QPrinter.PrinterMode.HighResolution); printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat); printer.setOutputFileName(filepath); printer.setPageOrientation(QPageLayout.Orientation.Landscape)
                html = f"<html><head><style>body{{font-family:sans-serif;font-size:9px;}} th{{background-color:#003057;color:white;padding:5px;}} td{{padding:5px;border:1px solid #ddd;}} table{{border-collapse:collapse;width:100%;}}</style></head><body><h2>{filename_prefix}</h2><table><tr>"
                for h in headers: html += f"<th>{h}</th>"
                html += "</tr>" + "".join(["<tr>" + "".join([f"<td>{x}</td>" for x in row]) + "</tr>" for row in data]) + "</table></body></html>"
                doc = QTextDocument(); doc.setHtml(html); doc.print(printer)
            except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            selection = self.selectedIndexes()
            if not selection: return super().keyPressEvent(event)
            selection.sort(key=lambda index: (index.row(), index.column()))
            
            copied_text = ""
            current_row = selection[0].row()
            
            for index in selection:
                if index.row() != current_row:
                    copied_text += "\n"
                    current_row = index.row()
                else:
                    if copied_text and not copied_text.endswith("\n"): copied_text += "\t"
                val = self.model().data(index, Qt.ItemDataRole.EditRole)
                copied_text += str(val) if val is not None else ""

            QApplication.clipboard().setText(copied_text)
            return
        super().keyPressEvent(event)