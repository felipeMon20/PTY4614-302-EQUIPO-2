import qtawesome as qta
from PyQt6.QtCore import Qt, QEvent, QEventLoop, QTimer, QVariantAnimation, QRectF, QSize, QElapsedTimer
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget, QFrame, QLabel, QPushButton, QVBoxLayout

from src.theme.colors import SUCCESS
from src.theme import tema

COLOR_SPINNER = "#1C6BBA"
COLOR_VELO = QColor(15, 23, 42, 97)
PAUSA_EXITO_MS = 600
ESPERA_ANTES_DE_OCULTAR_MS = 45000


class _Spinner(QWidget):
    def __init__(self, parent=None, tamano=44):
        super().__init__(parent)
        self.setFixedSize(tamano, tamano)
        self._angulo = 0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0)
        self._anim.setEndValue(360)
        self._anim.setDuration(800)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._girar)
        self._detenido = False

    def _girar(self, valor):
        self._angulo = valor
        self.update()

    # Solo gira mientras se ve: en páginas de carga ocultas no gasta CPU
    def showEvent(self, event):
        if not self._detenido:
            self._anim.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self._anim.stop()
        super().hideEvent(event)

    def detener(self):
        self._detenido = True
        self._anim.stop()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grosor = 4
        rect = QRectF(grosor / 2, grosor / 2, self.width() - grosor, self.height() - grosor)
        p.setPen(QPen(tema.fondo("#DBEAFE"), grosor))
        p.drawEllipse(rect)
        pen = QPen(QColor(COLOR_SPINNER), grosor)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int((90 - self._angulo) * 16), int(-100 * 16))
        p.end()


def crear_tarjeta_carga(mensaje, sub=""):
    """Tarjeta blanca con spinner y mensaje, mismo estilo que el velo de
    guardado, para pantallas de carga embebidas (sin velo)."""
    tarjeta = QFrame()
    tarjeta.setObjectName("tarjeta_carga")
    tarjeta.setStyleSheet("""
        QFrame#tarjeta_carga { background-color: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 12px; }
        QLabel { background: transparent; border: none; }
    """)
    lay = QVBoxLayout(tarjeta)
    lay.setContentsMargins(40, 30, 40, 28)
    lay.setSpacing(12)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

    tarjeta.spinner = _Spinner(tarjeta)
    lbl = QLabel(mensaje)
    tarjeta.lbl = lbl
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet("color: #1E293B; font-size: 15px; font-weight: bold;")
    lay.addWidget(tarjeta.spinner, alignment=Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(lbl)
    if sub:
        lbl_sub = QLabel(sub)
        lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_sub.setStyleSheet("color: #64748B; font-size: 12px;")
        lay.addWidget(lbl_sub)
    tarjeta.setMinimumWidth(360)
    return tarjeta


class OverlayGuardado(QWidget):
    """Velo sobre toda la ventana con una tarjeta de "guardando". Bloquea
    clics y teclado hasta que se cierra.

    Es opaco: dibuja una foto de la ventana tomada al abrirse, así cada
    cuadro del spinner no obliga a Qt a redibujar los módulos de abajo."""

    def __init__(self, ventana, mensaje):
        # La foto se toma antes de crear el velo para que no salga en ella
        foto = ventana.grab()
        super().__init__(ventana)
        self._ventana = ventana
        self._foto = foto
        self._listo = False
        self._reloj_listo = QElapsedTimer()
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.tarjeta = QFrame(self)
        self.tarjeta.setObjectName("tarjeta_guardado")
        self.tarjeta.setStyleSheet("""
            QFrame#tarjeta_guardado { background-color: #FFFFFF; border-radius: 12px; }
            QLabel { background: transparent; }
        """)

        lay = QVBoxLayout(self.tarjeta)
        lay.setContentsMargins(34, 28, 34, 26)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.spinner = _Spinner(self.tarjeta)
        self.icono_ok = QLabel(self.tarjeta)
        self.icono_ok.setPixmap(qta.icon('fa5s.check-circle', color=SUCCESS).pixmap(QSize(52, 52)))
        self.icono_ok.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icono_ok.hide()

        self.lbl_mensaje = QLabel(mensaje, self.tarjeta)
        self.lbl_mensaje.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_mensaje.setStyleSheet("color: #1E293B; font-size: 15px; font-weight: bold;")
        self.lbl_sub = QLabel("No cierres la aplicación mientras se guarda.", self.tarjeta)
        self.lbl_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sub.setStyleSheet("color: #64748B; font-size: 12px;")

        # Salida por si el guardado nunca avisa que terminó: no lo cancela,
        # solo deja volver a usar la ventana
        self.btn_ocultar = QPushButton("Ocultar este aviso", self.tarjeta)
        self.btn_ocultar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ocultar.setStyleSheet(
            "QPushButton { color: #1C6BBA; background: transparent; border: none; font-size: 12px; text-decoration: underline; }"
        )
        self.btn_ocultar.clicked.connect(self._ocultar_por_usuario)
        self.btn_ocultar.hide()
        self._timer_demora = QTimer(self)
        self._timer_demora.setSingleShot(True)
        self._timer_demora.timeout.connect(self._avisar_demora)
        self._timer_demora.start(ESPERA_ANTES_DE_OCULTAR_MS)

        lay.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icono_ok, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_mensaje)
        lay.addWidget(self.lbl_sub)
        lay.addWidget(self.btn_ocultar, alignment=Qt.AlignmentFlag.AlignCenter)
        self.tarjeta.setMinimumWidth(340)

        ventana.installEventFilter(self)
        self._ajustar()
        self.show()
        self.raise_()
        self.setFocus()

    def _ajustar(self):
        self.setGeometry(self._ventana.rect())
        self.tarjeta.adjustSize()
        self.tarjeta.move((self.width() - self.tarjeta.width()) // 2,
                          (self.height() - self.tarjeta.height()) // 2)
        self.update()

    def eventFilter(self, obj, event):
        if obj is self._ventana and event.type() == QEvent.Type.Resize:
            # La foto anterior ya no calza: se vuelve a tomar sin el velo
            self.hide()
            self._foto = self._ventana.grab()
            self.show()
            self._ajustar()
        return False

    def paintEvent(self, event):
        p = QPainter(self)
        p.setClipRect(event.rect())
        p.drawPixmap(0, 0, self._foto)
        p.fillRect(self.rect(), COLOR_VELO)
        # Sombra de la tarjeta: capas translúcidas en vez de un efecto con blur
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        base = QRectF(self.tarjeta.geometry()).translated(0, 6)
        for i in range(1, 9):
            p.setBrush(QColor(15, 23, 42, 7))
            p.drawRoundedRect(base.adjusted(-i * 2, -i * 2, i * 2, i * 2), 12 + i * 2, 12 + i * 2)
        p.end()

    def keyPressEvent(self, event):
        event.accept()

    def _avisar_demora(self):
        self.lbl_sub.setText("Está tardando más de lo normal. El guardado sigue en curso.")
        self.btn_ocultar.show()
        self._ajustar()

    def _ocultar_por_usuario(self):
        # El mensaje final igual llega; terminar_guardando ya no encontrará velo
        dueno = getattr(self, "_dueno", None)
        if dueno is not None and getattr(dueno, "_overlay_guardado", None) is self:
            dueno._overlay_guardado = None
        self.cerrar()

    def marcar_listo(self, texto):
        if self._listo:
            return
        self._listo = True
        self._timer_demora.stop()
        self.btn_ocultar.hide()
        self.spinner.detener()
        self.spinner.hide()
        self.icono_ok.show()
        self.lbl_mensaje.setText(texto)
        self.lbl_sub.setText("Actualizando la pantalla…")
        self._ajustar()
        # Se pinta ya: lo que viene después suele ocupar el hilo principal
        self.repaint()
        self._reloj_listo.start()

    def esperar_resto_pausa(self):
        # Solo si el usuario ve la ventana (en tests no) y solo lo que falte
        if not self._ventana.isVisible():
            return
        restante = PAUSA_EXITO_MS - self._reloj_listo.elapsed()
        if restante > 0:
            espera = QEventLoop()
            QTimer.singleShot(int(restante), espera.quit)
            espera.exec()

    def cerrar(self):
        self._timer_demora.stop()
        self._ventana.removeEventFilter(self)
        self.spinner.detener()
        self.hide()
        self.deleteLater()


def mostrar_guardando(widget, mensaje="Guardando cambios en la nube…"):
    """Muestra el velo sobre la ventana de `widget`. Se cierra con
    terminar_guardando(widget, ...)."""
    terminar_guardando(widget, exito=False)
    overlay = OverlayGuardado(widget.window(), mensaje)
    overlay._dueno = widget
    widget._overlay_guardado = overlay
    return overlay


def guardado_listo(widget, texto="Guardado"):
    """Cambia el velo al ✓ apenas el hilo avisa éxito, antes de que el
    módulo actualice sus datos en el hilo principal."""
    overlay = getattr(widget, "_overlay_guardado", None)
    if overlay is None:
        return
    try:
        overlay.marcar_listo(texto)
    except RuntimeError:
        widget._overlay_guardado = None


def terminar_guardando(widget, exito=True, texto_exito="Guardado"):
    """Cierra el velo de `widget` (si hay uno). Con exito=True asegura que
    el ✓ se vea al menos PAUSA_EXITO_MS. Llamar justo antes del mensaje de
    éxito o error."""
    overlay = getattr(widget, "_overlay_guardado", None)
    if overlay is None:
        return
    widget._overlay_guardado = None
    try:
        if exito:
            overlay.marcar_listo(texto_exito)
            overlay.esperar_resto_pausa()
        overlay.cerrar()
    except RuntimeError:
        pass  # el widget de Qt ya fue destruido
