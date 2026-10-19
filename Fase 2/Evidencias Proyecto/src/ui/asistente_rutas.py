"""Asistente de primer arranque: si la app no encuentra el Registro Maestro en
la ruta configurada (instalación nueva o carpeta movida), propone buscar la
carpeta de datos sola y completa todas las rutas de una vez."""
import os
import sys

import qtawesome as qta
from PyQt6.QtCore import Qt, QProcess, QTimer
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout)

from config import rutas
from config.settings import load_config, save_config
from src.theme.theme_manager import ThemeManager
from src.ui import comercial_estilo as estilo_com
from src.ui.guia_conexion import GuiaConexionDialog


class AsistenteRutasDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar archivos de la aplicación")
        self.setModal(True)
        self.setMinimumWidth(780)
        self.setStyleSheet(f"QDialog {{ background-color: {estilo_com.FONDO}; }}" + estilo_com.QSS_FUENTE_MODULO)
        self.encontrados = {}
        self.carpeta = ""

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(18, 18, 18, 18)
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaAsistenteRutas")
        tarjeta.setStyleSheet(estilo_com.qss_tarjeta("tarjetaAsistenteRutas"))
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(10)

        titulo = QLabel("Configuremos tus archivos")
        titulo.setStyleSheet(f"color: {estilo_com.TINTA}; font-size: 17px; font-weight: 800; border: none;")
        info = QLabel("No encontré el Registro Maestro en la ruta configurada. Voy a buscar la carpeta de datos "
                      "en tu equipo; si no la encuentro, elígela tú y completo el resto de las rutas.")
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {estilo_com.APAGADO}; font-size: 12px; border: none;")
        lay.addWidget(titulo)
        lay.addWidget(info)

        fila = QHBoxLayout()
        self.txt_carpeta = QLineEdit()
        self.txt_carpeta.setPlaceholderText("Carpeta que contiene RM_CONTRATOS.csv")
        self.txt_carpeta.setReadOnly(True)
        btn_buscar = QPushButton(" Buscar automáticamente")
        ThemeManager.apply_primary_button(btn_buscar)
        btn_buscar.clicked.connect(self._buscar)
        btn_elegir = QPushButton(" Elegir carpeta…")
        ThemeManager.apply_secondary_button(btn_elegir)
        btn_elegir.clicked.connect(self._elegir)
        fila.addWidget(self.txt_carpeta, 1)
        fila.addWidget(btn_buscar)
        fila.addWidget(btn_elegir)
        lay.addLayout(fila)

        self.lbl_estado = QLabel("")
        self.lbl_estado.setWordWrap(True)
        self.lbl_estado.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_estado.setStyleSheet("font-size: 12px; border: none;")
        lay.addWidget(self.lbl_estado)

        botones = QHBoxLayout()
        btn_ayuda = QPushButton(" ¿Cómo me conecto?")
        btn_ayuda.setIcon(qta.icon('fa5s.question-circle', color='#4B5563'))
        ThemeManager.apply_secondary_button(btn_ayuda)
        btn_ayuda.clicked.connect(lambda: GuiaConexionDialog(self).exec())
        botones.addWidget(btn_ayuda)
        botones.addStretch()
        btn_omitir = QPushButton("Abrir sin configurar")
        ThemeManager.apply_secondary_button(btn_omitir)
        btn_omitir.clicked.connect(self.reject)
        self.btn_guardar = QPushButton("Guardar y continuar")
        ThemeManager.apply_primary_button(self.btn_guardar)
        self.btn_guardar.setEnabled(False)
        self.btn_guardar.clicked.connect(self._guardar)
        botones.addWidget(btn_omitir)
        botones.addWidget(self.btn_guardar)
        lay.addLayout(botones)
        raiz.addWidget(tarjeta)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.encontrados:
            QTimer.singleShot(150, self._buscar)

    def _buscar(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            carpeta = rutas.buscar_carpeta_de_datos(os.path.expanduser("~")) or ""
        finally:
            QApplication.restoreOverrideCursor()
        self._aplicar_carpeta(carpeta)

    def _elegir(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Selecciona la carpeta de datos", self.carpeta or "")
        if carpeta:
            self._aplicar_carpeta(carpeta)

    def _aplicar_carpeta(self, carpeta):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.encontrados = rutas.descubrir_archivos(carpeta, subir=2) if carpeta else {}
        finally:
            QApplication.restoreOverrideCursor()
        self.carpeta = os.path.normpath(carpeta) if carpeta else ""
        self.txt_carpeta.setText(self.carpeta)
        lineas = []
        for clave, (etiqueta, _nombre, obligatorio) in rutas.ARCHIVOS_DE_DATOS.items():
            if clave in self.encontrados:
                lineas.append(f"<span style='color:#0F9D6E'>✓</span> {etiqueta}")
            elif obligatorio:
                lineas.append(f"<span style='color:#E04848'>✗</span> {etiqueta}: no encontrado")
        if not carpeta:
            lineas = ["<span style='color:#E04848'>No encontré la carpeta de datos. Elígela con «Elegir carpeta…».</span>"]
        self.lbl_estado.setText("<br>".join(lineas))
        self.btn_guardar.setEnabled("EXCEL_PATH" in self.encontrados)

    def _guardar(self):
        config = load_config()
        config["DATA_DIR"] = self.carpeta
        for clave, ruta in self.encontrados.items():
            config[clave] = os.path.normpath(ruta)
        save_config(config)
        self.accept()


def revisar_rutas_al_arrancar():
    """Devuelve True si se guardó una configuración nueva y la app se reinició
    (quien llama debe terminar); False si el arranque puede continuar."""
    import config.settings as ajustes
    if ajustes.EXCEL_PATH and os.path.exists(ajustes.EXCEL_PATH):
        return False
    dialogo = AsistenteRutasDialog()
    if dialogo.exec() != QDialog.DialogCode.Accepted:
        return False
    QProcess.startDetached(sys.executable, sys.argv)
    return True
