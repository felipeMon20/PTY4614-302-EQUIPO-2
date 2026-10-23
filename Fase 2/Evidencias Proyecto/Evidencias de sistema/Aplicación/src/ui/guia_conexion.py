"""Guía visual paso a paso para conectar la aplicación con los archivos de datos."""
import qtawesome as qta
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.theme.theme_manager import ThemeManager
from src.ui import comercial_estilo as estilo_com

_PASOS = (
    ("fa5s.cloud-download-alt", estilo_com.AZUL, "Trae la carpeta compartida a tu equipo",
     "En Teams o SharePoint abre la carpeta de datos del equipo (la que contiene <b>RM_JAVI.csv</b>) y pulsa "
     "<b>Sincronizar</b>. Cuando termine, aparecerá en el Explorador de archivos bajo <b>Volvo Group</b>."),
    ("fa5s.check-circle", estilo_com.VERDE, "Déjala disponible sin internet",
     "En el Explorador, clic derecho sobre la carpeta y elige <b>Mantener siempre en este dispositivo</b>. "
     "Espera a que los archivos muestren la palomita verde."),
    ("fa5s.search", estilo_com.VIOLETA, "Abre la aplicación y deja que busque",
     "Si no encuentra los archivos, aparece este asistente y los <b>busca solo</b>. Verás una lista con ✓ en cada "
     "archivo encontrado."),
    ("fa5s.folder-open", estilo_com.AMBAR, "Si no los encuentra, elige la carpeta",
     "Pulsa <b>Elegir carpeta…</b> y selecciona la carpeta sincronizada. Con eso basta: "
     "<b>no tienes que configurar archivo por archivo</b>."),
    ("fa5s.rocket", estilo_com.PRIMARIO, "Guarda y listo",
     "Pulsa <b>Guardar y continuar</b>. La aplicación se reinicia sola y queda conectada. "
     "Después puedes cambiarla en <b>Configuración › Carpeta de datos</b>."),
)


class GuiaConexionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cómo conectar la aplicación con tus archivos")
        self.setModal(True)
        self.setMinimumWidth(640)
        self.resize(680, 640)
        self.setStyleSheet(f"QDialog {{ background-color: {estilo_com.FONDO}; }}" + estilo_com.QSS_FUENTE_MODULO)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 18, 18, 18)
        raiz.setSpacing(12)

        titulo = QLabel("Conéctate a tus archivos en 5 pasos")
        titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 18px; font-weight: 800;")
        sub = QLabel("Solo necesitas hacerlo una vez por computador.")
        sub.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px;")
        raiz.addWidget(titulo)
        raiz.addWidget(sub)

        contenido = QWidget()
        contenido.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(10)
        for numero, (icono, color, nombre, texto) in enumerate(_PASOS, start=1):
            lay.addWidget(self._tarjeta_paso(numero, icono, color, nombre, texto))
        lay.addStretch()

        zona = QScrollArea()
        zona.setWidgetResizable(True)
        zona.setFrameShape(QFrame.Shape.NoFrame)
        zona.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        zona.setWidget(contenido)
        raiz.addWidget(zona, 1)

        botones = QHBoxLayout()
        botones.addStretch()
        btn = QPushButton("Entendido")
        ThemeManager.apply_primary_button(btn)
        btn.clicked.connect(self.accept)
        botones.addWidget(btn)
        raiz.addLayout(botones)

    def _tarjeta_paso(self, numero, icono, color, nombre, texto):
        tarjeta = QFrame()
        tarjeta.setObjectName(f"pasoGuia{numero}")
        tarjeta.setStyleSheet(estilo_com.qss_tarjeta(f"pasoGuia{numero}"))
        fila = QHBoxLayout(tarjeta)
        fila.setContentsMargins(16, 14, 16, 14)
        fila.setSpacing(14)

        insignia = QLabel()
        insignia.setFixedSize(46, 46)
        insignia.setAlignment(Qt.AlignmentFlag.AlignCenter)
        insignia.setPixmap(qta.icon(icono, color=color).pixmap(22, 22))
        tono = QColor(color)
        insignia.setStyleSheet(
            f"background-color: rgba({tono.red()}, {tono.green()}, {tono.blue()}, 30); "
            "border-radius: 23px; border: none;")
        fila.addWidget(insignia, 0, Qt.AlignmentFlag.AlignTop)

        columna = QVBoxLayout()
        columna.setSpacing(3)
        cabecera = QLabel(f"<span style='color:{color}'>Paso {numero}</span>")
        cabecera.setStyleSheet("font-size: 11px; font-weight: 700; border: none;")
        lbl_nombre = QLabel(nombre)
        lbl_nombre.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 14px; font-weight: 800; border: none;")
        lbl_texto = QLabel(texto)
        lbl_texto.setWordWrap(True)
        lbl_texto.setTextFormat(Qt.TextFormat.RichText)
        lbl_texto.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px; border: none;")
        for w in (cabecera, lbl_nombre, lbl_texto):
            columna.addWidget(w)
        fila.addLayout(columna, 1)
        return tarjeta
