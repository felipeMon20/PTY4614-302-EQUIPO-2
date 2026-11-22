"""Aviso de enlace faltante y acceso directo a Configuración > Enlaces."""
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout
from PyQt6.QtCore import Qt

_INDICE_ENLACES = 1


def abrir_configuracion_enlaces():
    """Abre Configuración en la sección Enlaces; devuelve False si no encuentra la ventana principal."""
    ventana = next((w for w in QApplication.topLevelWidgets() if hasattr(w, "_go_to_configuracion")), None)
    if ventana is None:
        return False
    ventana._go_to_configuracion()
    modulo = ventana.loaded_modules.get("Configuración")
    botones = getattr(modulo, "_botones_seccion", None)
    if botones:
        botones[_INDICE_ENLACES].click()
    return True


def avisar_enlace_faltante(parent, nombre):
    """Alerta con Cancelar o Ir a Configuración > Enlaces; devuelve True si el usuario eligió ir."""
    caja = QMessageBox(parent)
    caja.setIcon(QMessageBox.Icon.Warning)
    caja.setWindowTitle("Falta el enlace")
    caja.setText(f"Falta el enlace de {nombre}.")
    caja.setInformativeText("Agrégalo en Configuración, sección Enlaces, y vuelve a intentarlo.")
    ir = caja.addButton("Ir a Configuración > Enlaces", QMessageBox.ButtonRole.AcceptRole)
    cancelar = caja.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
    caja.setDefaultButton(cancelar)
    caja.exec()
    if caja.clickedButton() is ir:
        abrir_configuracion_enlaces()
        return True
    return False


def boton_ir_a_enlaces(parent=None, estilo=None):
    boton = QPushButton(" Ir a Configuración > Enlaces", parent)
    boton.setCursor(Qt.CursorShape.PointingHandCursor)
    if estilo:
        boton.setStyleSheet(estilo)
    return boton


def crear_aviso_enlace(titulo, texto, al_pulsar, parent=None):
    """Franja ámbar con título, explicación y botón hacia Enlaces."""
    marco = QFrame(parent)
    marco.setObjectName("avisoEnlace")
    marco.setStyleSheet(
        "QFrame#avisoEnlace { background: #FFF4DB; border: 1px solid #F2C46B; border-radius: 12px; }"
        "QFrame#avisoEnlace QLabel { background: transparent; border: none; }")
    lay = QVBoxLayout(marco)
    lay.setContentsMargins(16, 12, 16, 12)
    lay.setSpacing(4)
    t = QLabel(titulo)
    t.setStyleSheet("color: #7A4B00; font-size: 14px; font-weight: 800;")
    d = QLabel(texto)
    d.setWordWrap(True)
    d.setStyleSheet("color: #7A4B00; font-size: 12px;")
    lay.addWidget(t)
    lay.addWidget(d)
    fila = QHBoxLayout()
    boton = boton_ir_a_enlaces(marco, (
        "QPushButton { background: #D98A00; color: #2A1A00; border: none; border-radius: 9px; "
        "padding: 8px 16px; font-weight: 700; font-size: 12px; }"
        "QPushButton:hover { background: #E69A12; }"))
    boton.clicked.connect(al_pulsar)
    fila.addWidget(boton)
    fila.addStretch(1)
    lay.addSpacing(4)
    lay.addLayout(fila)
    return marco
