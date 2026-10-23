"""Aviso de versión nueva (tarjeta en la esquina de la ventana) y ventana de descarga."""
import qtawesome as qta
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                             QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from src.core.actualizador import ControlActualizacion, HiloDescarga
from src.services import actualizador_service as servicio
from src.theme.colors import DANGER, PRIMARY, SUCCESS
from src.ui import comercial_estilo as estilo_com

_SIN_FONDO = "border: none; background: transparent;"
MARGEN_TARJETA = 24


def _boton(texto, primario=False):
    btn = QPushButton(texto)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if primario:
        qss = (f"QPushButton {{ background: {PRIMARY}; color: white; border: 1px solid {PRIMARY}; }}"
               "QPushButton:hover { background: #1D4ED8; border-color: #1D4ED8; }")
    else:
        qss = (f"QPushButton {{ background: {estilo_com.SUPERFICIE}; color: {estilo_com.TINTA}; border: 1px solid {estilo_com.LINEA}; }}"
               f"QPushButton:hover {{ background: {estilo_com.SUPERFICIE_2}; }}")
    btn.setStyleSheet(qss.replace("QPushButton {", "QPushButton { border-radius: 8px; padding: 7px 16px; "
                                  "font-size: 13px; font-weight: 600;", 1))
    return btn


def _icono_descarga(lado=30):
    icono = QLabel()
    icono.setFixedSize(lado, lado)
    icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icono.setPixmap(qta.icon('fa5s.download', color='white').pixmap(lado // 2, lado // 2))
    icono.setStyleSheet(f"background: {PRIMARY}; border-radius: {lado // 2}px; border: none;")
    return icono


def _resumen_notas(notas, limite=150):
    notas = " ".join(notas.split())
    return notas if len(notas) <= limite else notas[:limite - 1].rstrip() + "…"


class TarjetaAviso(QFrame):
    """Tarjeta no bloqueante abajo a la derecha de la ventana principal."""

    def __init__(self, ventana, control):
        super().__init__(ventana)
        self._ventana = ventana
        man = control.manifiesto
        self.setObjectName("tarjetaActualizacion")
        self.setFixedWidth(348)
        self.setStyleSheet(
            f"QFrame#tarjetaActualizacion {{ background: {estilo_com.SUPERFICIE}; border: 1px solid {estilo_com.LINEA}; border-radius: 12px; }}")
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(30)
        sombra.setOffset(0, 6)
        sombra.setColor(QColor(15, 23, 42, 80))
        self.setGraphicsEffect(sombra)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        cab = QHBoxLayout()
        cab.setSpacing(10)
        titulo = QLabel("Hay una versión nueva")
        titulo.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        cerrar = QPushButton("×")
        cerrar.setFlat(True)
        cerrar.setCursor(Qt.CursorShape.PointingHandCursor)
        cerrar.setToolTip("Cerrar")
        cerrar.setFixedSize(24, 24)
        cerrar.setStyleSheet(f"QPushButton {{ border: none; font-size: 18px; color: {estilo_com.APAGADO}; background: transparent; }}"
                             f"QPushButton:hover {{ color: {estilo_com.TINTA}; }}")
        cerrar.clicked.connect(self._cerrar)
        cab.addWidget(_icono_descarga())
        cab.addWidget(titulo, 1)
        cab.addWidget(cerrar)
        lay.addLayout(cab)

        texto = f"Versión {man['version']} disponible (tienes la {control.version_instalada})."
        if man["notas"]:
            texto += f"\n{_resumen_notas(man['notas'])}"
        detalle = QLabel(texto)
        detalle.setWordWrap(True)
        detalle.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        lay.addWidget(detalle)

        fila = QHBoxLayout()
        fila.setSpacing(8)
        ahora_no = _boton("Ahora no")
        ahora_no.clicked.connect(self._cerrar)
        actualizar = _boton("Actualizar ahora", primario=True)
        actualizar.clicked.connect(self._actualizar)
        fila.addStretch()
        fila.addWidget(ahora_no)
        fila.addWidget(actualizar)
        lay.addLayout(fila)

        ventana.installEventFilter(self)

    def mostrar(self):
        # El texto con salto de línea necesita la altura calculada para el ancho fijo
        self.setFixedHeight(max(self.layout().totalHeightForWidth(self.width()), self.sizeHint().height()))
        self._reubicar()
        self.show()
        self.raise_()

    def _reubicar(self):
        self.move(self._ventana.width() - self.width() - MARGEN_TARJETA,
                  self._ventana.height() - self.height() - MARGEN_TARJETA)

    def eventFilter(self, objeto, evento):
        if evento.type() == QEvent.Type.Resize and objeto is self._ventana:
            self._reubicar()
        return False

    def _cerrar(self):
        self._ventana.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def _actualizar(self):
        self._cerrar()
        abrir_dialogo_actualizacion(self._ventana)


def abrir_dialogo_actualizacion(padre):
    control = ControlActualizacion.instancia()
    if not control.disponible():
        return
    if not servicio.puede_instalar():
        QMessageBox.information(padre, "Actualizar Gestor SSCC",
                                "La instalación automática solo funciona en el ejecutable de Gestor SSCC, no al correr desde el código.")
        return
    DialogoActualizacion(padre, control.manifiesto).exec()


class DialogoActualizacion(QDialog):
    PASOS = ("Descargar", "Preparar", "Reiniciar")

    def __init__(self, padre, manifiesto):
        super().__init__(padre)
        self._man = manifiesto
        self._hilo = None
        self._instalando = False
        self.setWindowTitle("Actualizar Gestor SSCC")
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint | Qt.WindowType.CustomizeWindowHint)
        self.setFixedWidth(480)
        self.setStyleSheet(f"QDialog {{ background: {estilo_com.SUPERFICIE}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        cab = QHBoxLayout()
        cab.setSpacing(12)
        self.lbl_titulo = QLabel()
        self.lbl_titulo.setWordWrap(True)
        self.lbl_titulo.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {estilo_com.TINTA}; {_SIN_FONDO}")
        chip = QLabel(f"{self._version_instalada()} → {manifiesto['version']}")
        chip.setStyleSheet(f"font-size: 11px; font-weight: 600; color: {PRIMARY}; background: #DBE7FE; "
                           "border-radius: 9px; padding: 2px 10px; border: none;")
        cab.addWidget(_icono_descarga(34))
        cab.addWidget(self.lbl_titulo, 1)
        cab.addWidget(chip)
        lay.addLayout(cab)

        self.barra = QProgressBar()
        self.barra.setTextVisible(False)
        self.barra.setRange(0, 100)
        self.barra.setStyleSheet(
            f"QProgressBar {{ background: {estilo_com.LINEA_SUAVE}; border: none; border-radius: 4px; min-height: 8px; max-height: 8px; }}"
            f"QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}")
        lay.addWidget(self.barra)

        self.lbl_detalle = QLabel()
        self.lbl_detalle.setWordWrap(True)
        self.lbl_detalle.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        lay.addWidget(self.lbl_detalle)

        self.lbl_pasos = QLabel()
        self.lbl_pasos.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_pasos.setStyleSheet(_SIN_FONDO)
        lay.addWidget(self.lbl_pasos)

        botones = QHBoxLayout()
        botones.setSpacing(8)
        self.btn_cancelar = _boton("Cancelar")
        self.btn_cancelar.clicked.connect(self._cancelar)
        self.btn_reintentar = _boton("Reintentar", primario=True)
        self.btn_reintentar.clicked.connect(self._iniciar)
        self.btn_cerrar = _boton("Cerrar")
        self.btn_cerrar.clicked.connect(self.done_cerrar)
        botones.addStretch()
        for btn in (self.btn_cancelar, self.btn_cerrar, self.btn_reintentar):
            botones.addWidget(btn)
        lay.addLayout(botones)

        QTimer.singleShot(0, self._iniciar)

    @staticmethod
    def _version_instalada():
        return ControlActualizacion.instancia().version_instalada

    def done_cerrar(self):
        self.done(0)

    def reject(self):
        if not self._instalando:
            self._cancelar()

    def _poner_paso(self, actual, error=False):
        partes = []
        for i, nombre in enumerate(self.PASOS):
            if i < actual:
                partes.append(f"<span style='color:{SUCCESS};'>✓ {nombre}</span>")
            elif i == actual:
                color = DANGER if error else estilo_com.TINTA
                partes.append(f"<b style='color:{color};'>{nombre}</b>")
            else:
                partes.append(f"<span style='color:{estilo_com.APAGADO};'>{nombre}</span>")
        self.lbl_pasos.setText("&nbsp;&nbsp;&nbsp;&nbsp;".join(partes))

    def _iniciar(self):
        self.lbl_titulo.setText(f"Descargando la versión {self._man['version']}")
        self.lbl_detalle.setStyleSheet(f"font-size: 12px; color: {estilo_com.APAGADO}; {_SIN_FONDO}")
        self.lbl_detalle.setText("Copiando desde la carpeta compartida…")
        self.barra.setRange(0, 100)
        self.barra.setValue(0)
        self._poner_paso(0)
        self.btn_cancelar.setVisible(True)
        self.btn_cerrar.setVisible(False)
        self.btn_reintentar.setVisible(False)
        self._hilo = HiloDescarga(self._man)
        self._hilo.progreso.connect(self._al_progreso)
        self._hilo.listo.connect(self._al_listo)
        self._hilo.fallo.connect(self._al_fallo)
        self._hilo.start()

    def _al_progreso(self, fase, porcentaje, detalle):
        self.barra.setValue(porcentaje)
        self.lbl_detalle.setText(detalle)
        if fase == "extraccion":
            self.lbl_titulo.setText(f"Preparando la versión {self._man['version']}")
            self._poner_paso(1)

    def _al_listo(self, temporal, raiz):
        self._instalando = True
        self.lbl_titulo.setText(f"Instalando la versión {self._man['version']}")
        self.lbl_detalle.setText("La aplicación se cerrará y volverá a abrir sola.")
        self.barra.setRange(0, 0)
        self._poner_paso(2)
        self.btn_cancelar.setVisible(False)
        QTimer.singleShot(1000, lambda: self._reemplazar(temporal, raiz))

    def _reemplazar(self, temporal, raiz):
        try:
            servicio.lanzar_reemplazo(temporal, raiz)
        except Exception as e:
            self._instalando = False
            self._al_fallo(f"No se pudo iniciar la instalación: {e}")
            return
        self._instalando = False
        QApplication.closeAllWindows()
        QApplication.quit()

    def _al_fallo(self, mensaje):
        if not mensaje:
            self.done(0)
            return
        self.barra.setRange(0, 100)
        self.barra.setValue(0)
        self.lbl_titulo.setText("No se pudo actualizar")
        self.lbl_detalle.setStyleSheet(f"font-size: 12px; color: {DANGER}; {_SIN_FONDO}")
        self.lbl_detalle.setText(mensaje)
        self._poner_paso(0, error=True)
        self.btn_cancelar.setVisible(False)
        self.btn_cerrar.setVisible(True)
        self.btn_reintentar.setVisible(True)
        self.adjustSize()

    def _cancelar(self):
        if self._hilo is not None and self._hilo.isRunning():
            self.btn_cancelar.setEnabled(False)
            self.lbl_detalle.setText("Cancelando…")
            self._hilo.cancelar()
        else:
            self.done(0)
