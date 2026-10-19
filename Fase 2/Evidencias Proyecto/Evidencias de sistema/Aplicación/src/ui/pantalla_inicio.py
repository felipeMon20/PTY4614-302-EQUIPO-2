"""Pantalla de arranque animada. Todo se dibuja con QPainter y colores fijos:
no usa hojas de estilo ni la paleta, así que el modo oscuro no la afecta."""
import math
import os

from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QPointF, QRectF
from PyQt6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap, QRadialGradient, QTransform)
from PyQt6.QtWidgets import QWidget

ANCHO, ALTO = 760, 430
RADIO_ESQUINA = 14

# Línea de tiempo (ms)
FIN_GIRO = 1100
INICIO_TEXTO, FIN_TEXTO = 850, 1900
INICIO_CAMION, FIN_CAMION = 1900, 3300
INICIO_FOCOS = 2700
INTRO_MINIMA = 3400
DURACION_LLENADO = 2600
DURACION_SALIDA = 320

LADO_LOGO = 300
CENTRO_LOGO = QPointF(ANCHO / 2, 138)
ESCALA_LOGO = 0.52
Y_TEXTO = 262
BARRA = QRectF(150, 352, ANCHO - 300, 12)

MENSAJES = (
    (0.0, "Inicializando sistema..."),
    (0.15, "Cargando motor de datos..."),
    (0.45, "Sincronizando orígenes de datos..."),
    (0.75, "Construyendo interfaz..."),
)


def _ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _ease_in_out(t):
    t = max(0.0, min(1.0, t))
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def _tramo(ms, inicio, fin):
    return max(0.0, min(1.0, (ms - inicio) / (fin - inicio)))


def _fuente_marca(px):
    f = QFont("Georgia")
    f.setPixelSize(px)
    f.setWeight(QFont.Weight.Black)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
    return f


def _plata(y0, y1, oscuro=False):
    g = QLinearGradient(0, y0, 0, y1)
    tonos = ((0.0, '#FFFFFF'), (0.35, '#C9CFD6'), (0.5, '#7D8690'), (0.62, '#E4E8EC'), (1.0, '#8F98A2'))
    for pos, c in tonos:
        color = QColor(c)
        g.setColorAt(pos, color.darker(230) if oscuro else color)
    return g


def _cargar_marca(ruta):
    """Logo nuevo (PNG con fondo transparente, 2x) del lienzo LADO_LOGO."""
    pm = QPixmap(ruta)
    pm.setDevicePixelRatio(pm.width() / LADO_LOGO)
    return pm


def _preparar_camion(ruta, alto):
    """Silueta oscura del camión con los bordes desvanecidos."""
    img = QImage(ruta)
    if img.isNull():
        return None, 1.0
    img = img.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    escala = alto / img.height()
    img = img.scaledToHeight(alto, Qt.TransformationMode.SmoothTransformation)
    p = QPainter(img)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    p.fillRect(img.rect(), QColor(118, 128, 142))
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    w, h = img.width(), img.height()
    centro = QPointF(225 * escala, h * 0.58)
    mascara = QRadialGradient(centro, h * 0.62)
    mascara.setColorAt(0.0, QColor(0, 0, 0, 255))
    mascara.setColorAt(0.55, QColor(0, 0, 0, 200))
    mascara.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(img.rect(), mascara)
    vertical = QLinearGradient(0, 0, 0, h)
    vertical.setColorAt(0.0, QColor(0, 0, 0, 0))
    vertical.setColorAt(0.25, QColor(0, 0, 0, 255))
    vertical.setColorAt(0.85, QColor(0, 0, 0, 255))
    vertical.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(img.rect(), vertical)
    lateral = QLinearGradient(0, 0, w, 0)
    lateral.setColorAt(0.0, QColor(0, 0, 0, 0))
    lateral.setColorAt(0.18, QColor(0, 0, 0, 255))
    lateral.setColorAt(0.82, QColor(0, 0, 0, 255))
    lateral.setColorAt(1.0, QColor(0, 0, 0, 0))
    p.fillRect(img.rect(), lateral)
    p.end()
    return QPixmap.fromImage(img), escala


class PantallaInicio(QWidget):
    """Solo animación. Quien la usa llama a set_progreso() y a
    terminar(al_terminar) cuando la carga real acaba."""

    def __init__(self, carpeta_assets):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.SplashScreen)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(ANCHO, ALTO)

        self._frente = _cargar_marca(os.path.join(carpeta_assets, 'splash_logo_frente.png'))
        self._reverso = _cargar_marca(os.path.join(carpeta_assets, 'splash_logo_reverso.png'))
        self._camion, esc = _preparar_camion(os.path.join(carpeta_assets, 'sidebar_truck.png'), int(ALTO * 1.08))
        self._camion_pos = QPointF(ANCHO / 2 - 225 * esc, ALTO - self._camion.height() + 30) if self._camion else QPointF()
        # Focos del camión (coordenadas en la imagen original 440x587)
        self._focos = [QPointF(self._camion_pos.x() + x * esc, self._camion_pos.y() + 402 * esc)
                       for x in (96, 342)] if self._camion else []

        self._texto = QPainterPath()
        self._texto.addText(0, 0, _fuente_marca(84), "EMPRESA")
        caja = self._texto.boundingRect()
        self._texto.translate(-caja.center().x(), -caja.center().y())

        self._progreso_objetivo = 0.0
        self._progreso = 0.0
        self._estado = MENSAJES[0][1]
        self._al_terminar = None
        self._ms_salida = None
        self._abriendo = False
        self._ultimo_ms = 0
        self._fondo = self._crear_fondo()

        self._reloj = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # --- API ---------------------------------------------------------
    def iniciar(self):
        self._reloj.start()
        self._timer.start()

    def animando(self):
        return self._reloj.isValid()

    def set_progreso(self, valor):
        self._progreso_objetivo = max(self._progreso_objetivo, min(1.0, valor))

    def terminar(self, al_terminar):
        self._al_terminar = al_terminar

    def detener(self):
        self._timer.stop()

    # --- animación ---------------------------------------------------
    def _ms(self):
        return self._reloj.elapsed() if self._reloj.isValid() else 0

    def _tick(self):
        ms = self._ms()
        if self._al_terminar is None:
            # Avance visual con tope en 95 %: el 100 % lo marca la carga real
            avance = _ease_out(_tramo(ms, INICIO_TEXTO, INICIO_TEXTO + DURACION_LLENADO)) * 0.95
            self.set_progreso(avance)
        elif ms >= INTRO_MINIMA:
            self._progreso_objetivo = 1.0

        dt = ms - self._ultimo_ms
        self._ultimo_ms = ms
        if ms >= FIN_TEXTO or self._progreso_objetivo >= 1.0:
            # Suavizado independiente de los fps
            self._progreso += (self._progreso_objetivo - self._progreso) * (1 - 0.88 ** (dt / 16))

        if not self._abriendo:
            for umbral, texto in MENSAJES:
                if self._progreso >= umbral:
                    self._estado = texto
            if self._al_terminar is None and self._progreso >= 0.94:
                self._estado = "Esperando datos..."

        if self._al_terminar is not None and not self._abriendo and self._progreso >= 0.995:
            # Se pinta "Abriendo..." antes de que el callback (que arma la
            # ventana principal) ocupe el hilo de la interfaz
            self._abriendo = True
            self._estado = "Abriendo la aplicación..."
            self.repaint()
            callback = self._al_terminar

            def _abrir():
                callback()
                self._ms_salida = self._ms()
            QTimer.singleShot(0, _abrir)
            return
        if self._abriendo and self._ms_salida is None:
            return
        if self._ms_salida is not None:
            t = _tramo(ms, self._ms_salida, self._ms_salida + DURACION_SALIDA)
            self.setWindowOpacity(1 - _ease_out(t))
            if t >= 1:
                self._timer.stop()
                self.close()
                return
        self.update()

    def paintEvent(self, _evento):
        ms = self._ms()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        marco = QPainterPath()
        marco.addRoundedRect(QRectF(self.rect()), RADIO_ESQUINA, RADIO_ESQUINA)
        p.setClipPath(marco)
        self._pintar_fondo(p)
        self._pintar_camion(p, ms)
        self._pintar_texto(p, ms)
        self._pintar_logo(p, ms)
        self._pintar_barra(p, ms)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), RADIO_ESQUINA, RADIO_ESQUINA)
        p.end()

    @staticmethod
    def _crear_fondo():
        # Se dibuja una sola vez: cada cuadro solo copia el pixmap
        pm = QPixmap(ANCHO, ALTO)
        p = QPainter(pm)
        vineta = QRadialGradient(QPointF(ANCHO / 2, ALTO * 0.42), ANCHO * 0.62)
        vineta.setColorAt(0.0, QColor('#2C3036'))
        vineta.setColorAt(0.55, QColor('#17191D'))
        vineta.setColorAt(1.0, QColor('#08090B'))
        p.fillRect(pm.rect(), vineta)
        p.end()
        return pm

    def _pintar_fondo(self, p):
        p.drawPixmap(0, 0, self._fondo)

    def _pintar_camion(self, p, ms):
        if self._camion is None:
            return
        t = _ease_in_out(_tramo(ms, INICIO_CAMION, FIN_CAMION))
        if t <= 0:
            return
        p.save()
        p.setOpacity(0.5 * t)
        p.drawPixmap(QPointF(self._camion_pos.x(), self._camion_pos.y() + 14 * (1 - t)), self._camion)
        p.restore()

        brillo = _ease_out(_tramo(ms, INICIO_FOCOS, INICIO_FOCOS + 700))
        if brillo <= 0:
            return
        pulso = 0.92 + 0.08 * math.sin(ms / 260)
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for foco in self._focos:
            halo = QRadialGradient(foco, 70)
            halo.setColorAt(0.0, QColor(235, 244, 255, int(210 * brillo * pulso)))
            halo.setColorAt(0.25, QColor(160, 200, 255, int(70 * brillo)))
            halo.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(foco.x() - 70, foco.y() - 70, 140, 140), halo)
        # Destello horizontal azul a la altura de los focos
        if self._focos:
            y = self._focos[0].y()
            raya = QLinearGradient(0, 0, ANCHO, 0)
            raya.setColorAt(0.0, QColor(0, 0, 0, 0))
            raya.setColorAt(0.5, QColor(90, 150, 255, int(90 * brillo)))
            raya.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(0, y - 1.5, ANCHO, 3), raya)
        p.restore()

    def _pintar_logo(self, p, ms):
        t = _tramo(ms, 0, FIN_GIRO)
        giro = _ease_out(t) * 2 * math.pi
        sx = math.cos(giro)
        aparicion = _ease_out(_tramo(ms, 0, 350))
        escala = ESCALA_LOGO * (0.75 + 0.25 * aparicion)
        p.save()
        p.setOpacity(aparicion)
        p.translate(CENTRO_LOGO)
        p.setTransform(QTransform().scale(max(abs(sx), 0.02) * (1 if sx >= 0 else -1), 1) * QTransform().scale(escala, escala), True)
        pm = self._frente if sx >= 0 else self._reverso
        p.drawPixmap(QPointF(-LADO_LOGO / 2, -LADO_LOGO / 2), pm)
        p.restore()

        # Reflejo que cruza el logo al terminar el giro
        brillo = _tramo(ms, FIN_GIRO - 150, FIN_GIRO + 500)
        if 0 < brillo < 1:
            p.save()
            radio = LADO_LOGO * ESCALA_LOGO / 2
            x = CENTRO_LOGO.x() - radio + brillo * radio * 2
            g = QLinearGradient(x - 30, 0, x + 30, 0)
            g.setColorAt(0, QColor(255, 255, 255, 0))
            g.setColorAt(0.5, QColor(255, 255, 255, 70))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            zona = QPainterPath()
            zona.addEllipse(CENTRO_LOGO + QPointF(-6, 6), radio * 0.72, radio * 0.72)
            p.setClipPath(zona, Qt.ClipOperation.IntersectClip)
            p.fillRect(QRectF(x - 30, 0, 60, ALTO), g)
            p.restore()

    def _pintar_texto(self, p, ms):
        t = _ease_out(_tramo(ms, INICIO_TEXTO, FIN_TEXTO))
        if t <= 0:
            return
        caja = self._texto.boundingRect()
        p.save()
        p.translate(ANCHO / 2, Y_TEXTO)
        p.scale(0.35 + 0.65 * t, 0.35 + 0.65 * t)
        p.setOpacity(t)
        p.setPen(Qt.PenStyle.NoPen)
        # Extrusión para dar volumen
        for i in range(6, 0, -1):
            p.setBrush(QColor(20 + i * 4, 22 + i * 4, 26 + i * 4))
            p.drawPath(self._texto.translated(0, i))
        p.setBrush(_plata(caja.top(), caja.bottom()))
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.drawPath(self._texto)
        p.restore()

        sub = _ease_out(_tramo(ms, FIN_TEXTO - 300, FIN_TEXTO + 300))
        if sub > 0:
            f = QFont("Segoe UI")
            f.setPixelSize(13)
            f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
            p.save()
            p.setOpacity(sub)
            p.setFont(f)
            p.setPen(QColor('#9AA3AD'))
            p.drawText(QRectF(0, Y_TEXTO + 42, ANCHO, 22), Qt.AlignmentFlag.AlignCenter,
                       "SISTEMA DE GESTIÓN Y ANÁLISIS DE FLOTAS")
            p.restore()

    def _pintar_barra(self, p, ms):
        t = _ease_out(_tramo(ms, INICIO_TEXTO + 200, FIN_TEXTO))
        if t <= 0:
            return
        r = BARRA.height() / 2
        p.save()
        p.setOpacity(t)
        p.setPen(QPen(QColor('#A9B1BA'), 1.4))
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(BARRA, r, r)

        interior = BARRA.adjusted(2.5, 2.5, -2.5, -2.5)
        ancho = interior.width() * self._progreso
        if ancho > 1:
            relleno = QRectF(interior.left(), interior.top(), max(ancho, interior.height()), interior.height())
            g = QLinearGradient(0, relleno.top(), 0, relleno.bottom())
            g.setColorAt(0, QColor('#FFFFFF'))
            g.setColorAt(0.5, QColor('#DDE3EA'))
            g.setColorAt(1, QColor('#9EA8B4'))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            ri = interior.height() / 2
            p.drawRoundedRect(relleno, ri, ri)
            # Resplandor en la punta
            punta = QPointF(relleno.right() - ri, relleno.center().y())
            halo = QRadialGradient(punta, 26)
            halo.setColorAt(0, QColor(255, 255, 255, 170))
            halo.setColorAt(1, QColor(255, 255, 255, 0))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.fillRect(QRectF(punta.x() - 26, punta.y() - 26, 52, 52), halo)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        f = QFont("Segoe UI")
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor('#8B949E'))
        p.drawText(QRectF(BARRA.left(), BARRA.bottom() + 10, BARRA.width() - 40, 18),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._estado)
        p.setPen(QColor('#C9D1D9'))
        p.drawText(QRectF(BARRA.left(), BARRA.bottom() + 10, BARRA.width(), 18),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{int(round(self._progreso * 100))} %")
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor('#5C646E'))
        p.drawText(QRectF(0, ALTO - 24, ANCHO - 18, 16),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, "Versión 1.0")
        p.restore()
