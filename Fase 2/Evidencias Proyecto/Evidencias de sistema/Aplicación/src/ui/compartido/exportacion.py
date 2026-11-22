import os

import qtawesome as qta
from PyQt6.QtCore import Qt, QEvent, QRectF, QSize, QTimer
from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPainterPath
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

AZUL = "#003057"
AZUL_CLARO = "#1C6BBA"
VERDE = "#15803D"
ROJO = "#B91C1C"
MARGEN_SOMBRA = 14
CIERRE_AUTOMATICO_MS = 7000


class _Barra(QWidget):
    """Barra delgada con relleno degradado y un brillo que la recorre mientras avanza."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._valor = 0.0
        self._fase = 0.0
        self._color = (QColor(AZUL_CLARO), QColor(AZUL))
        self._brillo = True

    def fijar(self, valor, fase):
        self._valor, self._fase = valor, fase
        self.update()

    def fijar_color(self, claro, oscuro, brillo):
        self._color = (QColor(claro), QColor(oscuro))
        self._brillo = brillo
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        radio = self.height() / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#E5EAF2"))
        p.drawRoundedRect(QRectF(self.rect()), radio, radio)
        ancho = max(self.height(), self.width() * self._valor / 100.0)
        if self._valor <= 0:
            p.end()
            return
        relleno = QRectF(0, 0, ancho, self.height())
        degradado = QLinearGradient(0, 0, self.width(), 0)
        degradado.setColorAt(0, self._color[0])
        degradado.setColorAt(1, self._color[1])
        p.setBrush(degradado)
        p.drawRoundedRect(relleno, radio, radio)
        if self._brillo:
            recorte = QPainterPath()
            recorte.addRoundedRect(relleno, radio, radio)
            p.setClipPath(recorte)
            centro = relleno.width() * self._fase
            brillo = QLinearGradient(centro - 40, 0, centro + 40, 0)
            brillo.setColorAt(0, QColor(255, 255, 255, 0))
            brillo.setColorAt(0.5, QColor(255, 255, 255, 110))
            brillo.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(brillo)
            p.drawRect(QRectF(centro - 40, 0, 80, self.height()))
        p.end()


class ProgresoExportacion(QFrame):
    """Tarjeta flotante en la esquina de la ventana que muestra el avance de una exportación.
    No bloquea la pantalla; el avance se suaviza con un temporizador para que se vea fluido."""

    def __init__(self, ventana, nombre_archivo):
        super().__init__(ventana)
        self._ventana = ventana
        self._ruta = None
        self._meta = 0.0
        self._mostrado = 0.0
        self._fase = 0.0
        self._terminado = False
        self._final_mostrado = False
        self._ok = False
        self.setObjectName("progreso_exportacion")
        self.setStyleSheet("QLabel { background: transparent; border: none; }")

        fondo = QFrame(self)
        fondo.setObjectName("tarjeta_exportacion")
        fondo.setStyleSheet("QFrame#tarjeta_exportacion { background-color: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 14px; }")
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(MARGEN_SOMBRA, MARGEN_SOMBRA, MARGEN_SOMBRA, MARGEN_SOMBRA)
        raiz.addWidget(fondo)

        fila = QHBoxLayout(fondo)
        fila.setContentsMargins(16, 14, 18, 14)
        fila.setSpacing(14)

        self.icono = QLabel()
        self.icono.setFixedSize(46, 46)
        self.icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._estilo_icono(VERDE, "#22C55E")
        self.icono.setPixmap(qta.icon('fa5s.file-excel', color='white').pixmap(QSize(22, 22)))
        fila.addWidget(self.icono)

        columna = QVBoxLayout()
        columna.setSpacing(3)
        self.lbl_titulo = QLabel("Generando Excel")
        self.lbl_titulo.setStyleSheet("color: #1B2B4E; font-size: 14px; font-weight: bold;")
        self.lbl_sub = QLabel(nombre_archivo)
        self.lbl_sub.setStyleSheet("color: #64748B; font-size: 11px;")
        self.barra = _Barra()
        columna.addWidget(self.lbl_titulo)
        columna.addWidget(self.lbl_sub)
        columna.addSpacing(4)
        columna.addWidget(self.barra)
        fila.addLayout(columna, stretch=1)

        derecha = QVBoxLayout()
        derecha.setSpacing(4)
        self.lbl_pct = QLabel("0%")
        self.lbl_pct.setStyleSheet(f"color: {AZUL}; font-size: 18px; font-weight: bold;")
        self.lbl_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.btn_abrir = QPushButton("Abrir")
        self.btn_abrir.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_abrir.setStyleSheet(
            "QPushButton { color: #FFFFFF; background: #15803D; border: none; border-radius: 8px; padding: 5px 14px;"
            " font-size: 12px; font-weight: bold; } QPushButton:hover { background: #166534; }")
        self.btn_abrir.clicked.connect(self._abrir)
        self.btn_abrir.hide()
        derecha.addWidget(self.lbl_pct)
        derecha.addWidget(self.btn_abrir)
        fila.addLayout(derecha)

        self.setFixedWidth(400)
        self._reloj = QTimer(self)
        self._reloj.setInterval(16)
        self._reloj.timeout.connect(self._avanzar)
        self._cierre = QTimer(self)
        self._cierre.setSingleShot(True)
        self._cierre.timeout.connect(self.cerrar)

        ventana.installEventFilter(self)
        self.adjustSize()
        self._posicionar()
        self.show()
        self.raise_()
        self._reloj.start()

    def _estilo_icono(self, desde, hasta):
        self.icono.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {desde}, stop:1 {hasta}); border-radius: 12px;")

    def _posicionar(self):
        self.move(self._ventana.width() - self.width() - 10, self._ventana.height() - self.height() - 10)
        self.raise_()

    def eventFilter(self, obj, event):
        if obj is self._ventana and event.type() == QEvent.Type.Resize:
            self._posicionar()
        return False

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        base = QRectF(self.rect()).adjusted(MARGEN_SOMBRA, MARGEN_SOMBRA, -MARGEN_SOMBRA, -MARGEN_SOMBRA).translated(0, 3)
        for i in range(1, 7):
            p.setBrush(QColor(15, 23, 42, 9))
            p.drawRoundedRect(base.adjusted(-i * 2, -i * 2, i * 2, i * 2), 14 + i * 2, 14 + i * 2)
        p.end()

    def actualizar(self, valor):
        self._meta = max(self._meta, float(valor))

    def _avanzar(self):
        # El avance real llega a saltos: la barra lo persigue con suavidad y, si el hilo tarda, sigue avanzando un poco
        objetivo = 100.0 if self._terminado else min(self._meta + 4.0, 97.0)
        factor = 0.18 if self._terminado else 0.08
        paso = max((objetivo - self._mostrado) * factor, 0.05)
        self._mostrado = min(objetivo, self._mostrado + paso)
        self._fase = (self._fase + 0.018) % 1.0
        self.barra.fijar(self._mostrado, self._fase)
        self.lbl_pct.setText(f"{int(self._mostrado)}%")
        if self._terminado and self._mostrado >= 99.5 and not self._final_mostrado:
            self._mostrar_final()

    def terminar(self, ok, ruta, error=""):
        self._terminado = True
        self._ok = ok
        self._ruta = ruta
        self._error = error
        if not ok:
            self._mostrar_final()

    def _mostrar_final(self):
        self._final_mostrado = True
        self._reloj.stop()
        if self._ok:
            self.barra.fijar(100.0, 0.0)
            self.barra.fijar_color("#22C55E", VERDE, False)
            self.lbl_pct.hide()
            self.lbl_titulo.setText("Excel listo")
            self.lbl_sub.setText(os.path.basename(self._ruta or ""))
            self.icono.setPixmap(qta.icon('fa5s.check', color='white').pixmap(QSize(22, 22)))
            self.btn_abrir.show()
            self._cierre.start(CIERRE_AUTOMATICO_MS)
        else:
            self.barra.fijar_color("#F87171", ROJO, False)
            self.lbl_pct.hide()
            self.lbl_titulo.setText("No se pudo exportar")
            self.lbl_sub.setText(str(getattr(self, "_error", ""))[:70])
            self._estilo_icono(ROJO, "#F87171")
            self.icono.setPixmap(qta.icon('fa5s.exclamation', color='white').pixmap(QSize(22, 22)))
            self._cierre.start(CIERRE_AUTOMATICO_MS)

    def _abrir(self):
        if self.__dict__.get('_cerrada'):
            return
        if self._ruta and os.path.exists(self._ruta):
            try:
                os.startfile(self._ruta)
            except OSError:
                pass
        self.cerrar()

    def cerrar(self):
        # Se puede llamar dos veces (doble clic en Abrir, o el cierre automático justo antes): la segunda no hace nada
        if self.__dict__.get('_cerrada'):
            return
        self._cerrada = True
        try:
            self._reloj.stop()
            self._cierre.stop()
            self._ventana.removeEventFilter(self)
            self.hide()
            self.deleteLater()
        except RuntimeError:
            pass


def iniciar_exportacion(widget, df, ruta, atributo_hilo="_export_excel_thread", titulo=None, resaltado=None,
                        con_resumen=True, hoja="Detalle", ventana=None, depurar=False):
    """Lanza ExportExcelThread con la tarjeta de avance. Guarda el hilo en `widget.<atributo_hilo>`;
    `ventana` es donde se dibuja la tarjeta (por defecto la ventana de `widget`)."""
    from src.ui.compartido.custom_table import ExportExcelThread
    tarjeta = ProgresoExportacion(ventana or widget.window(), os.path.basename(ruta))
    hilo = ExportExcelThread(df, ruta, parent=widget, titulo=titulo, resaltado=resaltado,
                             con_resumen=con_resumen, hoja=hoja, depurar=depurar)
    setattr(widget, atributo_hilo, hilo)
    hilo.progress_signal.connect(tarjeta.actualizar)

    def _terminado(ok, ruta_final, error):
        tarjeta.terminar(ok, ruta_final, error)
        if not ok:
            QMessageBox.critical(widget, "Error", error)

    hilo.finished_signal.connect(_terminado)
    hilo.start()
    return hilo
