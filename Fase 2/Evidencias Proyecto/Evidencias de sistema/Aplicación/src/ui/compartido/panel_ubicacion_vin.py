"""Pantalla que dice dónde está un VIN buscado cuando no está en la pantalla actual, con un botón para ir."""
from PyQt6.QtCore import QEvent, QObject, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from src.theme.theme_manager import ThemeManager
from src.ui.compartido import comercial_estilo as estilo_com
from src.ui.compartido.esqueleto_carga import EsqueletoCarga


class PanelUbicacionVin(QFrame):
    ir_clicked = pyqtSignal()

    def __init__(self, parent, cubre):
        """`cubre`: widgets hermanos que el panel tapa mientras se ve (se ajusta a su unión)."""
        super().__init__(parent)
        self._cubre = list(cubre)
        self.setObjectName("panelUbicacionVin")
        self.setStyleSheet(
            f"QFrame#panelUbicacionVin {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 16px; }}"
            "QFrame#panelUbicacionVin QLabel { background: transparent; border: none; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)
        lay.addStretch(1)

        self._icono = QLabel()
        self._icono.setFixedSize(112, 112)
        self._icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icono.setStyleSheet(f"background-color: {estilo_com.PRIMARIO_SUAVE}; border-radius: 56px;")
        lay.addWidget(self._icono, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(6)

        self._titulo = QLabel()
        self._titulo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._titulo.setWordWrap(True)
        self._titulo.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 15px;")
        lay.addWidget(self._titulo)

        self._destino = QLabel()
        self._destino.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._destino.setWordWrap(True)
        self._destino.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 24px; font-weight: 800;")
        lay.addWidget(self._destino)

        self._detalle = QLabel()
        self._detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detalle.setWordWrap(True)
        self._detalle.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px;")
        lay.addWidget(self._detalle)

        self._boton = QPushButton("Ir")
        self._boton.setCursor(Qt.CursorShape.PointingHandCursor)
        self._boton.setFixedSize(150, 42)
        self._boton.setStyleSheet(
            f"QPushButton {{ background-color: {estilo_com.PRIMARIO}; color: white; border: none; border-radius: 12px; "
            "font-size: 14px; font-weight: 700; }"
            "QPushButton:hover { background-color: #1859C2; }")
        self._boton.clicked.connect(self.ir_clicked)
        lay.addSpacing(8)
        lay.addWidget(self._boton, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(2)

        self._esqueleto = EsqueletoCarga(self, 'tarjetas')
        self._fin_busqueda = QTimer(self)
        self._fin_busqueda.setSingleShot(True)
        self._fin_busqueda.timeout.connect(self._esqueleto.terminar)

        _SigueAlPadre(self, parent)
        self.hide()

    def mostrar_destino(self, vin, destino, detalle=""):
        self._icono.setPixmap(ThemeManager.icon_pixmap('fa5s.map-marker-alt', color=estilo_com.PRIMARIO, size=52))
        self._titulo.setText(f"El VIN {vin} está en")
        self._destino.setText(destino)
        self._detalle.setText(detalle)
        self._detalle.setVisible(bool(detalle))
        self._boton.show()
        self._abrir()

    def mostrar_no_encontrado(self, vin):
        self._icono.setPixmap(ThemeManager.icon_pixmap('fa5s.search', color=estilo_com.APAGADO, size=48))
        self._titulo.setText(f"No se encontró el VIN {vin}")
        self._destino.setText("No está en ninguna bandeja")
        self._detalle.setText("Revisa que esté bien escrito. Una unidad dada de baja y desconectada ya no aparece en las bandejas.")
        self._detalle.show()
        self._boton.hide()
        self._abrir()

    DURACION_BUSQUEDA_MS = 400

    def _abrir(self):
        """Primero se ve el esqueleto de la tabla buscando; luego aparece el aviso con un fundido."""
        self.reposicionar()
        self.show()
        self.raise_()
        self._esqueleto.iniciar_ya()
        self._fin_busqueda.start(self.DURACION_BUSQUEDA_MS)

    def hideEvent(self, evento):
        self._fin_busqueda.stop()
        self._esqueleto._ocultar()
        super().hideEvent(evento)

    def reposicionar(self):
        zonas = [w.geometry() for w in self._cubre if w is not None]
        if not zonas:
            return
        union = zonas[0]
        for z in zonas[1:]:
            union = union.united(z)
        self.setGeometry(QRect(union))


class _SigueAlPadre(QObject):
    def __init__(self, panel, padre):
        super().__init__(panel)
        self._panel = panel
        padre.installEventFilter(self)

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Type.Resize and self._panel.isVisible():
            self._panel.reposicionar()
        return False
