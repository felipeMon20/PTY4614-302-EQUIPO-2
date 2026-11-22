"""Ventana de sincronización de Provisiones con pasos animados."""
from src.theme.colors import VOLVO_BLUE
import re
import time
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QDialog, QTextEdit, QStackedWidget
from PyQt6.QtCore import Qt, QTimer, QRectF, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from src.ui.compartido.custom_table import VolvoTableWidget
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido import aviso_enlace
from src.ui.ingresos.base import ModeloTablaIngresos, aplicar_estilo_tabla_lectura
from src.core.sharepoint_sync import SharePointSyncWorker
from config.settings import PROVISIONES_SHAREPOINT_URL
from src.theme.theme_manager import ThemeManager


# (título, ayuda) de cada paso del proceso; coinciden con las fases de SharePointSyncWorker
_PASOS_SYNC = [
    ("Descargar archivo", "Abrimos SharePoint en tu navegador y esperamos la descarga."),
    ("Leer y adaptar", "Tomamos la hoja del año en curso y la dejamos con el formato de Provisiones."),
    ("Comparar", "Buscamos los contratos (VIN + mes) que aún no están en tu Excel."),
    ("Revisar", "Confirmas los registros nuevos antes de agregarlos."),
    ("Guardar", "Respaldo, escritura de las filas nuevas y fórmulas."),
]


_MENSAJE_PASO_SYNC = [
    ("Descargando desde SharePoint",
     "Se abrió SharePoint en tu navegador. Si te pide iniciar sesión en Microsoft 365, hazlo: "
     "la descarga empieza sola y la app la detecta en tu carpeta Descargas."),
    ("Leyendo el archivo", "Tomamos la hoja del año en curso y la dejamos con las columnas y el formato de Provisiones."),
    ("Buscando contratos nuevos", "Comparamos cada VIN y mes con tu Excel para no duplicar nada."),
    ("Revisa los registros nuevos", ""),
    ("Guardando en tu Excel",
     "Primero hacemos una copia de seguridad y luego agregamos las filas con sus fórmulas. No cierres la ventana."),
]


_ESPERA_DESCARGA_S = 60

COL_EN_RM = "Registro Maestro"

_RE_PROVISION = re.compile(r"provisi[oó]n", re.IGNORECASE)
_RE_CM = re.compile(r"contrato\s+(blue|gold|silver)|\bCM[BGS]\b", re.IGNORECASE)


def _tipo_desde_observacion(texto):
    """Provision, CM o Provision + CM según lo que dice la observación del contrato; '-' si no menciona ninguno."""
    texto = str(texto or "")
    prov, cm = bool(_RE_PROVISION.search(texto)), bool(_RE_CM.search(texto))
    return "Provision + CM" if prov and cm else "Provision" if prov else "CM" if cm else "-"


def _formato_pesos(valor):
    try:
        numero = round(float(valor))
    except (TypeError, ValueError):
        return "-"
    if numero != numero:
        return "-"
    return f"${numero:,}".replace(",", ".")


class _BotonInfo(QLabel):
    """Círculo con signo de interrogación; avisa cuando el mouse entra o sale."""
    entro = pyqtSignal()
    salio = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("?", parent)
        self.setFixedSize(26, 26)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.WhatsThisCursor)
        self._estilo(False)

    def _estilo(self, activo):
        fondo, texto = ("#1F6FEB", "#FFFFFF") if activo else ("#EEF3FA", "#52607A")
        self.setStyleSheet(f"background: {fondo}; color: {texto}; border-radius: 13px; font-size: 13px; font-weight: 800;")

    def enterEvent(self, evento):
        self._estilo(True)
        self.entro.emit()
        super().enterEvent(evento)

    def leaveEvent(self, evento):
        self._estilo(False)
        self.salio.emit()
        super().leaveEvent(evento)


class AnilloTiempo(QWidget):
    """Anillo con un número al centro: cuenta regresiva durante la espera de la
    descarga y arco giratorio con el tiempo transcurrido en el resto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 132)
        self.fraccion = None
        self.texto = ""
        self.subtexto = ""
        self.color = QColor(VOLVO_BLUE)
        self.quieto = True

    def definir(self, texto, subtexto, fraccion=None, color=None, quieto=False):
        self.texto, self.subtexto, self.fraccion, self.quieto = texto, subtexto, fraccion, quieto
        self.color = QColor(color or VOLVO_BLUE)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        marco = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        p.setPen(QPen(QColor("#E3E8F0"), 9))
        p.drawArc(marco, 0, 360 * 16)
        p.setPen(QPen(self.color, 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        if self.fraccion is not None:
            p.drawArc(marco, 90 * 16, -int(360 * 16 * max(0.0, min(1.0, self.fraccion))))
        elif not self.quieto:
            inicio = 90 - int((time.monotonic() * 220) % 360)
            p.drawArc(marco, inicio * 16, -110 * 16)
        p.setPen(QColor("#0F1B33"))
        fuente = p.font()
        fuente.setPixelSize(26)
        fuente.setBold(True)
        p.setFont(fuente)
        p.drawText(QRectF(self.rect()).adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter, self.texto)
        p.setPen(QColor("#6B7A90"))
        fuente.setPixelSize(10)
        fuente.setBold(False)
        p.setFont(fuente)
        p.drawText(QRectF(self.rect()).adjusted(0, 30, 0, 30), Qt.AlignmentFlag.AlignCenter, self.subtexto)


class PasoSync(QFrame):
    """Una fila del paso a paso: círculo de estado, título y descripción."""

    ESTILOS = {
        "pendiente": ("#EEF1F6", "#6B7A90", "#6B7A90"),
        "activo": (VOLVO_BLUE, "white", "#0F1B33"),
        "hecho": ("#16A34A", "white", "#0F1B33"),
        "error": ("#DC2626", "white", "#0F1B33"),
    }

    def __init__(self, numero, titulo, descripcion, parent=None):
        super().__init__(parent)
        self.numero = numero
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(12)
        self.badge = QLabel(str(numero))
        self.badge.setFixedSize(28, 28)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        textos = QVBoxLayout()
        textos.setSpacing(1)
        self.lbl_titulo = QLabel(titulo)
        self.lbl_desc = QLabel(descripcion)
        self.lbl_desc.setWordWrap(True)
        textos.addWidget(self.lbl_titulo)
        textos.addWidget(self.lbl_desc)
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(textos, 1)
        self.estado = None
        self.definir("pendiente")

    def definir(self, estado):
        if estado == self.estado:
            return
        self.estado = estado
        fondo, texto, titulo = self.ESTILOS[estado]
        simbolo = {"hecho": "✓", "error": "!"}.get(estado, str(self.numero))
        self.badge.setText(simbolo)
        self.badge.setStyleSheet(
            f"background: {fondo}; color: {texto}; border-radius: 14px; font-weight: 800; font-size: 13px;")
        self.lbl_titulo.setStyleSheet(
            f"color: {titulo}; font-size: 13px; font-weight: 700; background: transparent;")
        self.lbl_desc.setStyleSheet("color: #6B7A90; font-size: 11px; background: transparent;")
        activo = estado == "activo"
        self.setStyleSheet(
            f"PasoSync {{ background: {'#EEF3FA' if activo else 'transparent'}; border-radius: 12px; }}")


class SyncTerminalDialog(QDialog):
    """Sincronización con SharePoint explicada paso a paso: lista de pasos,
    anillo de tiempo, previsualización con la tabla de Comercial y resultado.
    El proceso real sigue en SharePointSyncWorker; aquí solo se traducen sus
    mensajes de registro a pasos."""

    PAG_PROGRESO, PAG_REVISION, PAG_RESULTADO = 0, 1, 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sincronización de SharePoint (Auto-ETL)")
        self.resize(1100, 680)
        self.setFont(estilo_com.fuente_comercial(self.font()))
        self.setStyleSheet(estilo_com.QSS_FUENTE_MODULO + "QDialog { background-color: #F4F6FA; }")
        self.sharepoint_url = PROVISIONES_SHAREPOINT_URL
        self.worker = None
        self._paso = -1
        self._t0 = None
        self._inicio_paso = None
        self._finalizado = False
        self._setup_ui()
        self._reloj = QTimer(self)
        self._reloj.setInterval(40)
        self._reloj.timeout.connect(self._tick)
        self._cola = []
        self._paso_pedido = -1
        self._pausa_cola = QTimer(self)
        self._pausa_cola.setSingleShot(True)
        self._pausa_cola.setInterval(450)
        self._pausa_cola.timeout.connect(self._siguiente_en_cola)
        if not (self.sharepoint_url or "").strip():
            self._mostrar_sin_enlace()

    def _mostrar_sin_enlace(self):
        self.anillo.definir("Falta", "el enlace", fraccion=0.9999, color="#D98A00", quieto=True)
        self.lbl_titulo_paso.setText("Falta el enlace de SharePoint")
        self.lbl_ayuda_paso.setText(
            "Para sincronizar hay que indicar dónde está el Excel de Provisiones. "
            "Pega el enlace en Configuración, sección Enlaces, y vuelve a intentarlo.")
        self.btn_ir_enlaces.show()
        self.btn_start.setEnabled(False)

    def _ir_a_enlaces(self):
        self.reject()
        aviso_enlace.abrir_configuracion_enlaces()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(20, 18, 20, 16)
        raiz.setSpacing(14)

        cabecera = QFrame()
        cabecera.setObjectName("cabeceraSync")
        cabecera.setStyleSheet("QFrame#cabeceraSync { background-color: #1B2B4E; border-radius: 14px; }")
        fila = QHBoxLayout(cabecera)
        fila.setContentsMargins(16, 12, 16, 12)
        fila.setSpacing(12)
        titulos = QVBoxLayout()
        titulos.setSpacing(0)
        t = QLabel("Sincronizar con SharePoint")
        t.setStyleSheet("color: white; font-size: 16px; font-weight: 800; background: transparent;")
        s = QLabel("Trae los contratos nuevos del Excel de Provisiones y los agrega a tu archivo.")
        s.setStyleSheet("color: #B8C2D6; font-size: 11px; font-weight: 600; background: transparent;")
        titulos.addWidget(t)
        titulos.addWidget(s)
        fila.addLayout(titulos, 1)
        raiz.addWidget(cabecera)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(14)

        lateral = QFrame()
        lateral.setObjectName("pasosSync")
        lateral.setFixedWidth(300)
        lateral.setStyleSheet(estilo_com.qss_tarjeta("pasosSync"))
        lay_pasos = QVBoxLayout(lateral)
        lay_pasos.setContentsMargins(10, 12, 10, 12)
        lay_pasos.setSpacing(2)
        titulo_pasos = QLabel("PASO A PASO")
        titulo_pasos.setStyleSheet(estilo_com.QSS_TITULO_SECCION)
        lay_pasos.addWidget(titulo_pasos)
        self.pasos = []
        for i, (titulo, desc) in enumerate(_PASOS_SYNC, start=1):
            paso = PasoSync(i, titulo, desc)
            self.pasos.append(paso)
            lay_pasos.addWidget(paso)
        lay_pasos.addStretch()
        cuerpo.addWidget(lateral)

        self.paginas = QStackedWidget()
        self.paginas.addWidget(self._build_pagina_progreso())
        self.paginas.addWidget(self._build_pagina_revision())
        self.paginas.addWidget(self._build_pagina_resultado())
        cuerpo.addWidget(self.paginas, 1)
        raiz.addLayout(cuerpo, 1)

        botones = QHBoxLayout()
        self.btn_cancel = QPushButton(" Cancelar")
        ThemeManager.apply_secondary_button(self.btn_cancel)
        self.btn_cancel.clicked.connect(self.close)

        self.btn_start = QPushButton(" Iniciar descarga")
        self.btn_start.setIcon(ThemeManager.icon('fa5s.cloud-download-alt', color='white'))
        ThemeManager.apply_primary_button(self.btn_start)
        self.btn_start.clicked.connect(self.start_sync)

        self.btn_inject = QPushButton(" Agregar registros")
        self.btn_inject.setIcon(ThemeManager.icon('fa5s.magic', color='white'))
        self.btn_inject.setStyleSheet(
            f"QPushButton {{ background-color: {VOLVO_BLUE}; color: white; border: none; border-radius: 8px;"
            " padding: 9px 18px; font-weight: 700; }"
            "QPushButton:hover { background-color: #0B4276; }"
            "QPushButton:disabled { background-color: #8FA3B8; }")
        self.btn_inject.clicked.connect(self.inject_data)
        self.btn_inject.hide()

        self.btn_cerrar = QPushButton(" Cerrar")
        ThemeManager.apply_primary_button(self.btn_cerrar)
        self.btn_cerrar.clicked.connect(self.accept)
        self.btn_cerrar.hide()

        botones.addStretch()
        botones.addWidget(self.btn_cancel)
        botones.addWidget(self.btn_start)
        botones.addWidget(self.btn_inject)
        botones.addWidget(self.btn_cerrar)
        raiz.addLayout(botones)

    @staticmethod
    def _tarjeta(nombre):
        marco = QFrame()
        marco.setObjectName(nombre)
        marco.setStyleSheet(estilo_com.qss_tarjeta(nombre))
        return marco

    def _build_pagina_progreso(self):
        marco = self._tarjeta("progresoSync")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(24, 22, 24, 16)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.anillo = AnilloTiempo()
        self.anillo.definir("Listo", "para empezar", quieto=True)
        lay.addWidget(self.anillo, 0, Qt.AlignmentFlag.AlignHCenter)

        self.lbl_titulo_paso = QLabel("Todo listo para sincronizar")
        self.lbl_titulo_paso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_titulo_paso.setStyleSheet("color: #0F1B33; font-size: 17px; font-weight: 800; background: transparent;")
        self.lbl_ayuda_paso = QLabel(
            "Al pulsar «Iniciar descarga» se abre SharePoint en tu navegador. Si te pide iniciar sesión, "
            "hazlo; la descarga comienza sola y puedes seguir el avance aquí.")
        self.lbl_ayuda_paso.setWordWrap(True)
        self.lbl_ayuda_paso.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_ayuda_paso.setStyleSheet("color: #52607A; font-size: 12px; background: transparent;")
        lay.addWidget(self.lbl_titulo_paso)
        lay.addWidget(self.lbl_ayuda_paso)
        self.btn_ir_enlaces = QPushButton(" Ir a Configuración > Enlaces")
        ThemeManager.apply_primary_button(self.btn_ir_enlaces)
        self.btn_ir_enlaces.clicked.connect(self._ir_a_enlaces)
        self.btn_ir_enlaces.hide()
        lay.addWidget(self.btn_ir_enlaces, 0, Qt.AlignmentFlag.AlignHCenter)

        lay.addStretch()
        self.btn_detalle = QPushButton("Ver detalle técnico")
        self.btn_detalle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_detalle.setCheckable(True)
        self.btn_detalle.setStyleSheet(
            "QPushButton { color: #6B7A90; font-size: 11px; font-weight: 700; border: none; background: transparent; }"
            "QPushButton:hover { color: #1B2B4E; }")
        self.btn_detalle.toggled.connect(self._alternar_detalle)
        lay.addWidget(self.btn_detalle, 0, Qt.AlignmentFlag.AlignHCenter)

        self.terminal = QTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal.setFixedHeight(120)
        self.terminal.setStyleSheet(
            "background-color: #F7F8FC; color: #334155; border: 1px solid #E3E8F0; border-radius: 10px;"
            " font-family: Consolas; font-size: 11px; padding: 8px;")
        self.terminal.hide()
        lay.addWidget(self.terminal)
        return marco

    def _build_pagina_revision(self):
        marco = self._tarjeta("revisionSync")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        fila = QHBoxLayout()
        fila.setSpacing(10)
        columna_titulo = QVBoxLayout()
        columna_titulo.setSpacing(2)
        self.lbl_titulo_revision = QLabel("Registros nuevos")
        self.lbl_titulo_revision.setStyleSheet(
            "color: #0F1B33; font-size: 22px; font-weight: 800; background: transparent;")
        self.lbl_resumen_revision = QLabel("")
        self.lbl_resumen_revision.setStyleSheet("color: #6B7A90; font-size: 12px; font-weight: 600; background: transparent;")
        self.chip_cantidad = QLabel("0")
        self.chip_cantidad.setStyleSheet(
            f"background: #E1EAF4; color: {VOLVO_BLUE}; border-radius: 11px; padding: 3px 12px;"
            " font-size: 11px; font-weight: 800;")
        self.btn_info = _BotonInfo()
        fila_titulo = QHBoxLayout()
        fila_titulo.setSpacing(10)
        fila_titulo.addWidget(self.lbl_titulo_revision)
        fila_titulo.addWidget(self.chip_cantidad, 0, Qt.AlignmentFlag.AlignVCenter)
        fila_titulo.addStretch()
        columna_titulo.addLayout(fila_titulo)
        columna_titulo.addWidget(self.lbl_resumen_revision)
        fila.addLayout(columna_titulo, 1)
        fila.addWidget(self.btn_info, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(fila)

        self._tarjeta_info = self._crear_tarjeta_info(marco)
        self.btn_info.entro.connect(lambda: self._mostrar_tarjeta_info(marco))
        self.btn_info.salio.connect(self._tarjeta_info.hide)

        self.preview_table = VolvoTableWidget()
        aplicar_estilo_tabla_lectura(self.preview_table, 42)
        self.preview_model = ModeloTablaIngresos(
            alineacion=Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
            resolver=self._color_registro_maestro)
        self.preview_table.set_model_and_delegate(self.preview_model)
        self._delegado_preview = estilo_com.DelegadoCeldasComercial([self.preview_table, self.preview_table.frozen_view])
        self.preview_table.setItemDelegate(self._delegado_preview)
        self.preview_table.frozen_view.setItemDelegate(self._delegado_preview)
        lay.addWidget(self.preview_table, 1)
        return marco

    @staticmethod
    def _crear_tarjeta_info(padre):
        tarjeta = QFrame(padre)
        tarjeta.setObjectName("tarjetaInfoSync")
        tarjeta.setFixedWidth(360)
        tarjeta.setStyleSheet(
            "QFrame#tarjetaInfoSync { background: #FFFFFF; border: 1px solid #D5DDEA; border-radius: 14px; }"
            "QFrame#tarjetaInfoSync QLabel { background: transparent; border: none; }")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        titulo = QLabel("Qué pasa al agregar")
        titulo.setStyleSheet("color: #0F1B33; font-size: 13px; font-weight: 800;")
        lay.addWidget(titulo)
        for punto, texto in (
                ("1", "Los registros se agregan al final de la hoja «Prov» de provisionFelipe.xlsx."),
                ("2", "Entran con Plan vacío y 0 meses. Después defines el plan y los meses en cada registro."),
                ("3", "Antes de escribir se guarda una copia de seguridad."),
                ("RM", "«Registro Maestro» indica si el VIN ya existe ahí.")):
            fila = QHBoxLayout()
            fila.setSpacing(10)
            insignia = QLabel(punto)
            insignia.setFixedSize(26, 22)
            insignia.setAlignment(Qt.AlignmentFlag.AlignCenter)
            insignia.setStyleSheet("background: #E6EFFD; color: #1F6FEB; border-radius: 11px; font-size: 10px; font-weight: 800;")
            cuerpo = QLabel(texto)
            cuerpo.setWordWrap(True)
            cuerpo.setStyleSheet("color: #52607A; font-size: 12px;")
            fila.addWidget(insignia, 0, Qt.AlignmentFlag.AlignTop)
            fila.addWidget(cuerpo, 1)
            lay.addLayout(fila)
        tarjeta.hide()
        return tarjeta

    def _mostrar_tarjeta_info(self, marco):
        tarjeta = self._tarjeta_info
        tarjeta.setFixedHeight(tarjeta.layout().totalHeightForWidth(tarjeta.width()))
        base = self.btn_info.mapTo(marco, QPoint(self.btn_info.width(), self.btn_info.height() + 8))
        tarjeta.move(max(8, min(base.x() - tarjeta.width(), marco.width() - tarjeta.width() - 8)), base.y())
        tarjeta.show()
        tarjeta.raise_()

    def _build_pagina_resultado(self):
        marco = self._tarjeta("resultadoSync")
        lay = QVBoxLayout(marco)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.setSpacing(10)
        lay.addStretch()
        self.icono_resultado = QLabel()
        self.icono_resultado.setFixedSize(76, 76)
        self.icono_resultado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icono_resultado, 0, Qt.AlignmentFlag.AlignHCenter)
        self.lbl_titulo_resultado = QLabel("")
        self.lbl_titulo_resultado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_titulo_resultado.setStyleSheet("color: #0F1B33; font-size: 20px; font-weight: 800; background: transparent;")
        self.lbl_detalle_resultado = QLabel("")
        self.lbl_detalle_resultado.setWordWrap(True)
        self.lbl_detalle_resultado.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_detalle_resultado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_detalle_resultado.setStyleSheet("color: #52607A; font-size: 12px; background: transparent;")
        lay.addWidget(self.lbl_titulo_resultado)
        lay.addWidget(self.lbl_detalle_resultado)
        lay.addStretch()
        return marco

    _CHIPS = {
        (COL_EN_RM, "Sí"): ("#DCFCE7", "#15803D"), (COL_EN_RM, "No"): ("#FEE2E2", "#DC2626"),
        ("Tipo", "Provision"): ("#E0EAFF", "#1D4ED8"), ("Tipo", "CM"): ("#FEF3C7", "#92400E"),
        ("Tipo", "Provision + CM"): ("#EDE9FE", "#6D28D9"),
    }

    @classmethod
    def _color_registro_maestro(cls, columna, valor, es_fondo):
        colores = cls._CHIPS.get((columna, valor))
        return None if colores is None else colores[0 if es_fondo else 1]

    def _vins_en_registro_maestro(self):
        dm = getattr(self.parent(), 'data_manager', None)
        df = getattr(dm, 'df_master', None)
        if df is None or df.empty or 'VIN' not in df.columns:
            return set()
        return set(df['VIN'].astype(str).str.strip().str.upper())

    def _alternar_detalle(self, visible):
        self.terminal.setVisible(visible)
        self.btn_detalle.setText("Ocultar detalle técnico" if visible else "Ver detalle técnico")

    # ------------------------------------------------------------ progreso
    def _set_paso(self, indice, estado="activo"):
        self._paso = indice
        self._inicio_paso = time.monotonic()
        for i, paso in enumerate(self.pasos):
            paso.definir("hecho" if i < indice else ("pendiente" if i > indice else estado))
        titulo, ayuda = _MENSAJE_PASO_SYNC[indice]
        self.lbl_titulo_paso.setText(titulo)
        self.lbl_ayuda_paso.setText(ayuda)

    def _tick(self):
        if self._t0 is None:
            return
        transcurrido = time.monotonic() - self._t0
        if self._paso == 0 and self._inicio_paso is not None:
            restante = max(0, _ESPERA_DESCARGA_S - (time.monotonic() - self._inicio_paso))
            self.anillo.definir(f"{int(restante + 0.99)}s", "espera máxima", fraccion=restante / _ESPERA_DESCARGA_S)
        else:
            minutos, segundos = divmod(int(transcurrido), 60)
            self.anillo.definir(f"{minutos}:{segundos:02d}", "transcurrido")

    def _detener_reloj(self):
        self._reloj.stop()
        if self._t0 is not None:
            minutos, segundos = divmod(int(time.monotonic() - self._t0), 60)
            return f"{minutos}:{segundos:02d}"
        return "0:00"

    def write_log(self, text):
        self.terminal.append(f"> {text}")
        scrollbar = self.terminal.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        paso = (1 if "Archivo atrapado" in text or "[PROCESANDO]" in text else
                2 if "[COMPARANDO]" in text else 4 if "Creando copia" in text else None)
        if paso is not None and paso != self._paso_pedido:
            self._paso_pedido = paso
            self._encolar(lambda: self._set_paso(paso))

    def _encolar(self, accion):
        """Los pasos terminan en milisegundos: se muestran de a uno, con una pausa mínima entre ellos."""
        self._cola.append(accion)
        if not self._pausa_cola.isActive():
            self._siguiente_en_cola()

    def _siguiente_en_cola(self):
        if not self._cola:
            return
        self._cola.pop(0)()
        self._pausa_cola.start()

    def _vaciar_cola(self):
        self._cola.clear()
        self._pausa_cola.stop()

    # --------------------------------------------------------------- flujo
    def start_sync(self):
        self.btn_start.setEnabled(False)
        self.terminal.clear()
        self.paginas.setCurrentIndex(self.PAG_PROGRESO)
        self._t0 = time.monotonic()
        self._paso_pedido = 0
        self._set_paso(0)
        self._reloj.start()
        self.worker = SharePointSyncWorker(self.sharepoint_url)
        self.worker.log_signal.connect(self.write_log)
        self.worker.preview_signal.connect(self.show_preview)
        self.worker.success_signal.connect(self.handle_success)
        self.worker.error_signal.connect(self.handle_error)
        self.worker.start()

    def show_preview(self, df_nuevos):
        self._encolar(lambda: self._mostrar_preview(df_nuevos))

    def _mostrar_preview(self, df_nuevos):
        self._reloj.stop()
        self._set_paso(3)
        columnas = [c for c in ('VIN', 'CLIENTE', 'DYNAFLEET') if c in df_nuevos.columns]
        df_display = df_nuevos[columnas].rename(columns={'CLIENTE': 'Razón social', 'DYNAFLEET': 'Dynafleet'})
        if 'OBSERVACIONES' in df_nuevos.columns:
            df_display.insert(min(2, len(df_display.columns)), 'Tipo', df_nuevos['OBSERVACIONES'].map(_tipo_desde_observacion))
        if 'Dynafleet' in df_display.columns:
            df_display['Dynafleet'] = df_display['Dynafleet'].map(_formato_pesos)
        if 'VIN' in df_display.columns:
            existentes = self._vins_en_registro_maestro()
            df_display.insert(0, COL_EN_RM, df_display['VIN'].map(
                lambda v: "Sí" if str(v).strip().upper() in existentes else "No"))
        if 'AÑO - MES' in df_nuevos.columns:
            periodos = list(dict.fromkeys(str(p).strip() for p in df_nuevos['AÑO - MES'].dropna() if str(p).strip()))
            titulo = " / ".join(periodos) if 0 < len(periodos) <= 3 else f"{len(periodos)} periodos"
            self.lbl_titulo_revision.setText(titulo if periodos else "Registros nuevos")
        total = len(df_nuevos)
        resumen = f"{total} {'contrato nuevo' if total == 1 else 'contratos nuevos'}"
        if COL_EN_RM in df_display.columns:
            en_rm = int((df_display[COL_EN_RM] == "Sí").sum())
            resumen += f"  ·  {en_rm} en el Registro Maestro  ·  {total - en_rm} sin registrar"
        self.lbl_resumen_revision.setText(resumen)
        self.preview_model.set_data(df_display)
        anchos = {COL_EN_RM: 110, 'VIN': 160, 'Razón social': 190, 'Tipo': 145, 'Dynafleet': 100}
        for i, col in enumerate(df_display.columns):
            self.preview_table.setColumnWidth(i, anchos.get(col, 200))
        self.chip_cantidad.setText(f"{len(df_nuevos)} {'registro' if len(df_nuevos) == 1 else 'registros'}")
        self.paginas.setCurrentIndex(self.PAG_REVISION)
        self.btn_start.hide()
        self.btn_inject.setText(f" Agregar {len(df_nuevos)} {'registro' if len(df_nuevos) == 1 else 'registros'}")
        self.btn_inject.show()

    def inject_data(self):
        self.btn_inject.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.paginas.setCurrentIndex(self.PAG_PROGRESO)
        self._t0 = time.monotonic()
        self._vaciar_cola()
        self._paso_pedido = 4
        self._set_paso(4)
        self._pausa_cola.start()
        self._reloj.start()
        self.worker.is_injecting = True
        self.worker.start()

    def _mostrar_resultado(self, icono, color, fondo, titulo, detalle):
        self.icono_resultado.setPixmap(ThemeManager.icon_pixmap(icono, color=color, size=34))
        self.icono_resultado.setStyleSheet(f"background: {fondo}; border-radius: 38px;")
        self.lbl_titulo_resultado.setText(titulo)
        self.lbl_detalle_resultado.setText(detalle)
        self.paginas.setCurrentIndex(self.PAG_RESULTADO)

    def handle_success(self, status):
        self._encolar(lambda: self._mostrar_exito(status))

    def _mostrar_exito(self, status):
        tiempo = self._detener_reloj()
        self._finalizado = True
        self.btn_start.hide()
        self.btn_inject.hide()
        self.btn_cancel.hide()
        self.btn_cerrar.show()
        if status == "ZERO":
            for paso in self.pasos[:3]:
                paso.definir("hecho")
            self._mostrar_resultado('fa5s.check', "#065F46", "#D1FAE5", "Todo al día",
                                    f"No hay contratos nuevos para agregar. Tiempo total: {tiempo}.")
            return
        for paso in self.pasos:
            paso.definir("hecho")
        cantidad = len(self.worker.new_data_df) if self.worker.new_data_df is not None else 0
        self._mostrar_resultado('fa5s.check', "#065F46", "#D1FAE5", "Proceso completado",
                                f"Se agregaron {cantidad} registros a provisionFelipe.xlsx. Tiempo total: {tiempo}.")

    def handle_error(self, error_msg):
        self._vaciar_cola()
        self._detener_reloj()
        if 0 <= self._paso < len(self.pasos):
            self.pasos[self._paso].definir("error")
        self._mostrar_resultado('fa5s.exclamation', "#991B1B", "#FEE2E2", "No se pudo completar", error_msg)
        self.btn_start.setText(" Reintentar")
        self.btn_start.setEnabled(True)
        self.btn_start.show()
        self.btn_inject.hide()
        self.btn_cancel.setEnabled(True)

    def reject(self):
        if self._finalizado:
            self.accept()
        else:
            self._reloj.stop()
            self._vaciar_cola()
            super().reject()
