"""Selector de fecha con calendario propio (el QCalendarWidget de Qt no admite
esquinas redondeadas ni animaciones). Campo de solo lectura que abre una
tarjeta con vistas de días, meses y años; no se escribe a mano.

El calendario se dibuja entero en un solo paintEvent y maneja el mouse por su
cuenta: con botones hijos sobre una ventana translúcida, Windows dejaba restos
de la vista anterior al pasar el mouse o cambiar de vista."""
import os
import sys

from PyQt6.QtCore import (Qt, QDate, QPoint, QRectF, QPointF, QPropertyAnimation, QEasingCurve, QElapsedTimer,
                          QParallelAnimationGroup, pyqtSignal)
from PyQt6.QtGui import QColor, QPixmap, QPainter, QPainterPath, QPen, QFont, QFontMetrics
from PyQt6.QtWidgets import QFrame, QWidget, QHBoxLayout, QLabel, QApplication

from src.theme.colors import PRIMARY, DANGER, TEXT_PRIMARY, TEXT_SECONDARY

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
DIAS = ['lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom']

ESPERA_REAPERTURA_MS = 350   # evita que un doble clic abra y cierre el calendario
ESPERA_NAVEGACION_MS = 110   # evita saltar varios meses con clics repetidos
DURACION_APERTURA_MS = 170

# Geometría (px)
MARGEN_IZQ, MARGEN_SUP, MARGEN_DER, MARGEN_INF = 14, 8, 14, 20
RELLENO = 12
ANCHO_CELDA, ALTO_CELDA, ESPACIO = 36, 32, 2
ANCHO_INT = 7 * ANCHO_CELDA + 6 * ESPACIO          # 264
ALTO_CABECERA = 34
ALTO_SEMANA = 22
ALTO_REJILLA = 6 * ALTO_CELDA + 5 * ESPACIO         # 202
ALTO_CUERPO = ALTO_SEMANA + 4 + ALTO_REJILLA        # 228
ANCHO_TARJETA = ANCHO_INT + 2 * RELLENO
ALTO_TARJETA = RELLENO + ALTO_CABECERA + 6 + ALTO_CUERPO + RELLENO
ANCHO_VENTANA = ANCHO_TARJETA + MARGEN_IZQ + MARGEN_DER
ALTO_VENTANA = ALTO_TARJETA + MARGEN_SUP + MARGEN_INF

C_HOVER = QColor("#E8F0FE")
C_HOVER_TITULO = QColor("#EEF2F7")
C_BORDE = QColor("#DCE3EC")


def _ruta_recurso(relativa):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, relativa)


_CHEVRON = _ruta_recurso(os.path.join('src', 'assets', 'combo_chevron.png'))


class CalendarioPopup(QWidget):
    fecha_elegida = pyqtSignal(QDate)
    cerrado = pyqtSignal()

    def __init__(self, parent, fecha, maximo):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFixedSize(ANCHO_VENTANA, ALTO_VENTANA)
        self._fecha = fecha
        self._maximo = maximo
        self._mostrado = QDate(fecha.year(), fecha.month(), 1)
        self._vista = 'dias'
        self._pagina_anios = 0
        self._hover = None
        self._ultima_navegacion = QElapsedTimer()
        self._ultima_navegacion.start()
        self._pos_final = None
        self._anim_apertura = QParallelAnimationGroup(self)
        self.ensurePolished()   # toma la tipografía de la hoja de estilos de la app

    # ------------------------------------------------------------------ fuentes
    def _fuente(self, px, peso=QFont.Weight.Normal):
        f = QFont(self.font())
        f.setPixelSize(px)
        f.setWeight(peso)
        return f

    # ------------------------------------------------------------------ elementos
    def _puede_siguiente(self):
        if self._vista == 'dias':
            return QDate(self._mostrado.year(), self._mostrado.month(), 1).addMonths(1) <= self._maximo
        if self._vista == 'meses':
            return self._mostrado.year() < self._maximo.year()
        return self._mostrado.year() - 4 + self._pagina_anios * 12 + 12 <= self._maximo.year()

    def _elementos(self):
        """Lista de elementos del calendario con su rectángulo (coordenadas de
        la ventana). Sirve igual para dibujar y para saber dónde se hizo clic."""
        x0 = MARGEN_IZQ + RELLENO
        y0 = MARGEN_SUP + RELLENO
        elementos = []

        def agregar(tipo, valor, rect, texto='', habilitado=True, **flags):
            elementos.append(dict(tipo=tipo, valor=valor, rect=rect, texto=texto, habilitado=habilitado, **flags))

        agregar('prev', None, QRectF(x0, y0 + 2, 30, 30))
        agregar('next', None, QRectF(x0 + ANCHO_INT - 30, y0 + 2, 30, 30), habilitado=self._puede_siguiente())

        fm = QFontMetrics(self._fuente(13, QFont.Weight.Bold))
        if self._vista == 'dias':
            mes, anio = MESES[self._mostrado.month() - 1], str(self._mostrado.year())
            ancho_mes, ancho_anio = fm.horizontalAdvance(mes) + 20, fm.horizontalAdvance(anio) + 20
            inicio = x0 + (ANCHO_INT - (ancho_mes + 4 + ancho_anio)) / 2
            agregar('titulo_mes', None, QRectF(inicio, y0 + 2, ancho_mes, 30), mes)
            agregar('titulo_anio', None, QRectF(inicio + ancho_mes + 4, y0 + 2, ancho_anio, 30), anio)
        elif self._vista == 'meses':
            anio = str(self._mostrado.year())
            ancho = fm.horizontalAdvance(anio) + 20
            agregar('titulo_anio', None, QRectF(x0 + (ANCHO_INT - ancho) / 2, y0 + 2, ancho, 30), anio)
        else:
            inicio_rango = self._mostrado.year() - 4 + self._pagina_anios * 12
            texto = f"{inicio_rango} – {inicio_rango + 11}"
            ancho = fm.horizontalAdvance(texto) + 20
            agregar('rango', None, QRectF(x0 + (ANCHO_INT - ancho) / 2, y0 + 2, ancho, 30), texto, habilitado=False)

        cuerpo_y = y0 + ALTO_CABECERA + 6
        hoy = QDate.currentDate()
        if self._vista == 'dias':
            for col, nombre in enumerate(DIAS):
                agregar('semana', col, QRectF(x0 + col * (ANCHO_CELDA + ESPACIO), cuerpo_y, ANCHO_CELDA, ALTO_SEMANA), nombre, habilitado=False)
            primero = self._mostrado.dayOfWeek() - 1
            ys = cuerpo_y + ALTO_SEMANA + 4
            for i in range(42):
                dia = self._mostrado.addDays(i - primero)
                rect = QRectF(x0 + (i % 7) * (ANCHO_CELDA + ESPACIO), ys + (i // 7) * (ALTO_CELDA + ESPACIO), ANCHO_CELDA, ALTO_CELDA)
                agregar('dia', dia, rect, str(dia.day()), habilitado=dia <= self._maximo,
                        otro=dia.month() != self._mostrado.month(), finde=dia.dayOfWeek() >= 6,
                        hoy=dia == hoy, sel=dia == self._fecha)
        else:
            ancho_c, alto_c, sep = 84, 52, 6
            for i in range(12):
                rect = QRectF(x0 + (i % 3) * (ancho_c + sep), cuerpo_y + (i // 3) * (alto_c + sep), ancho_c, alto_c)
                if self._vista == 'meses':
                    primero_mes = QDate(self._mostrado.year(), i + 1, 1)
                    agregar('mes', i + 1, rect, MESES[i][:3], habilitado=primero_mes <= self._maximo,
                            sel=(self._fecha.year() == self._mostrado.year() and self._fecha.month() == i + 1),
                            hoy=(hoy.year() == self._mostrado.year() and hoy.month() == i + 1))
                else:
                    anio = self._mostrado.year() - 4 + self._pagina_anios * 12 + i
                    agregar('anio', anio, rect, str(anio), habilitado=anio <= self._maximo.year(),
                            sel=(anio == self._fecha.year()), hoy=(anio == hoy.year()))
        return elementos

    @staticmethod
    def _clave(elemento):
        return (elemento['tipo'], elemento['valor'])

    # ------------------------------------------------------------------ dibujo
    def paintEvent(self, event):
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        pintor.fillRect(self.rect(), Qt.GlobalColor.transparent)
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        tarjeta = QRectF(MARGEN_IZQ, MARGEN_SUP, ANCHO_TARJETA, ALTO_TARJETA)
        # Sombra suave: capas semitransparentes que crecen alrededor de la tarjeta
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(15, 27, 51, 7))
        for i in range(1, 11):
            pintor.drawRoundedRect(tarjeta.translated(0, 3).adjusted(-i, -i, i, i), 14 + i, 14 + i)
        pintor.setPen(QPen(C_BORDE, 1))
        pintor.setBrush(QColor("#FFFFFF"))
        pintor.drawRoundedRect(tarjeta.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)

        for e in self._elementos():
            self._dibujar_elemento(pintor, e)

    def _dibujar_elemento(self, pintor, e):
        tipo, rect, habilitado = e['tipo'], e['rect'], e['habilitado']
        encima = self._hover == self._clave(e) and habilitado
        pintor.setPen(Qt.PenStyle.NoPen)

        if tipo in ('prev', 'next'):
            if encima:
                pintor.setBrush(C_HOVER_TITULO)
                pintor.drawRoundedRect(rect, 8, 8)
            color = QColor(TEXT_SECONDARY) if habilitado else QColor("#D5DCE6")
            pintor.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            c = rect.center()
            signo = -1 if tipo == 'prev' else 1
            ruta = QPainterPath()
            ruta.moveTo(QPointF(c.x() - 2.5 * signo, c.y() - 5))
            ruta.lineTo(QPointF(c.x() + 2.5 * signo, c.y()))
            ruta.lineTo(QPointF(c.x() - 2.5 * signo, c.y() + 5))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawPath(ruta)
            return

        if tipo in ('titulo_mes', 'titulo_anio', 'rango'):
            if encima:
                pintor.setBrush(C_HOVER_TITULO)
                pintor.drawRoundedRect(rect, 8, 8)
            pintor.setPen(QColor(PRIMARY) if encima else QColor(TEXT_PRIMARY))
            pintor.setFont(self._fuente(13, QFont.Weight.Bold))
            pintor.drawText(rect, Qt.AlignmentFlag.AlignCenter, e['texto'])
            return

        if tipo == 'semana':
            pintor.setPen(QColor(DANGER) if e['valor'] >= 5 else QColor(TEXT_SECONDARY))
            pintor.setFont(self._fuente(11, QFont.Weight.DemiBold))
            pintor.drawText(rect, Qt.AlignmentFlag.AlignCenter, e['texto'])
            return

        # dia / mes / anio
        seleccionado = e.get('sel', False)
        if seleccionado:
            pintor.setBrush(QColor(PRIMARY))
            pintor.drawRoundedRect(rect, 9, 9)
        elif encima:
            pintor.setBrush(C_HOVER)
            pintor.drawRoundedRect(rect, 9, 9)
        if e.get('hoy') and not seleccionado:
            pintor.setPen(QPen(QColor(PRIMARY), 1))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)

        if seleccionado:
            color = QColor("#FFFFFF")
        elif not habilitado:
            color = QColor("#D5DCE6")
        elif encima:
            color = QColor(PRIMARY)
        elif tipo == 'dia' and e.get('otro'):
            color = QColor("#F2B8B8") if e.get('finde') else QColor("#B8C2D0")
        elif tipo == 'dia' and e.get('finde'):
            color = QColor(DANGER)
        else:
            color = QColor(TEXT_PRIMARY)
        pintor.setPen(color)
        pintor.setFont(self._fuente(12 if tipo == 'dia' else 13, QFont.Weight.Bold if seleccionado else QFont.Weight.Normal))
        pintor.drawText(rect, Qt.AlignmentFlag.AlignCenter, e['texto'])

    # ------------------------------------------------------------------ mouse
    def _elemento_en(self, pos):
        for e in self._elementos():
            if e['tipo'] != 'semana' and e['rect'].contains(QPointF(pos)):
                return e
        return None

    def mouseMoveEvent(self, event):
        e = self._elemento_en(event.position().toPoint())
        clave = self._clave(e) if e is not None and e['habilitado'] else None
        if clave != self._hover:
            self._hover = clave
            self.setCursor(Qt.CursorShape.PointingHandCursor if clave is not None else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        e = self._elemento_en(event.position().toPoint())
        if e is None or not e['habilitado']:
            return
        tipo = e['tipo']
        if tipo == 'dia':
            self._elegir(e['valor'])
        elif tipo == 'prev':
            self._navegar(-1)
        elif tipo == 'next':
            self._navegar(1)
        elif tipo == 'titulo_mes':
            self._cambiar_vista('meses')
        elif tipo == 'titulo_anio':
            self._cambiar_vista('anios')
        elif tipo == 'mes':
            self._elegir_mes(e['valor'])
        elif tipo == 'anio':
            self._elegir_anio(e['valor'])

    # ------------------------------------------------------------------ navegación
    def _permitir_navegacion(self):
        if self._ultima_navegacion.elapsed() < ESPERA_NAVEGACION_MS:
            return False
        self._ultima_navegacion.restart()
        return True

    def _cambiar_vista(self, vista):
        if not self._permitir_navegacion():
            return
        self._vista = vista
        self._pagina_anios = 0
        self._hover = None
        self.update()

    def _navegar(self, sentido):
        if not self._permitir_navegacion():
            return
        if self._vista == 'dias':
            self._mostrado = self._mostrado.addMonths(sentido)
        elif self._vista == 'meses':
            self._mostrado = self._mostrado.addYears(sentido)
        else:
            self._pagina_anios += sentido
        self.update()

    def _elegir_mes(self, mes):
        if not self._permitir_navegacion():
            return
        self._mostrado = QDate(self._mostrado.year(), mes, 1)
        self._vista = 'dias'
        self._hover = None
        self.update()

    def _elegir_anio(self, anio):
        if not self._permitir_navegacion():
            return
        nuevo = QDate(anio, self._mostrado.month(), 1)
        if nuevo > self._maximo:
            nuevo = QDate(self._maximo.year(), self._maximo.month(), 1)
        self._mostrado = nuevo
        self._vista = 'meses'
        self._pagina_anios = 0
        self._hover = None
        self.update()

    def _elegir(self, dia):
        if dia > self._maximo:
            return
        self._fecha = dia
        self.fecha_elegida.emit(dia)
        self.close()

    # ------------------------------------------------------------------ aparición
    def abrir_en(self, pos_global):
        """Muestra el calendario con la esquina de la tarjeta en `pos_global`."""
        destino = QPoint(pos_global.x() - MARGEN_IZQ, pos_global.y() - MARGEN_SUP)
        pantalla = QApplication.screenAt(pos_global) or QApplication.primaryScreen()
        area = pantalla.availableGeometry()
        if destino.y() + self.height() > area.bottom():
            destino.setY(max(area.top(), pos_global.y() - self.height() - 36))
        destino.setX(min(max(area.left(), destino.x()), area.right() - self.width()))
        self._pos_final = destino
        self.move(destino + QPoint(0, -8))
        self.setWindowOpacity(0.0)
        self.show()

    def showEvent(self, event):
        super().showEvent(event)
        if self._pos_final is None:
            return
        self._anim_apertura.stop()
        self._anim_apertura.clear()
        opacidad = QPropertyAnimation(self, b"windowOpacity")
        opacidad.setDuration(DURACION_APERTURA_MS)
        opacidad.setStartValue(0.0)
        opacidad.setEndValue(1.0)
        opacidad.setEasingCurve(QEasingCurve.Type.OutCubic)
        desplazamiento = QPropertyAnimation(self, b"pos")
        desplazamiento.setDuration(DURACION_APERTURA_MS)
        desplazamiento.setStartValue(self._pos_final + QPoint(0, -8))
        desplazamiento.setEndValue(self._pos_final)
        desplazamiento.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_apertura.addAnimation(opacidad)
        self._anim_apertura.addAnimation(desplazamiento)
        self._anim_apertura.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.cerrado.emit()


class SelectorFecha(QFrame):
    """Campo de fecha compacto y de solo lectura. API mínima, parecida a la de
    QDateEdit: date(), setDate(), setMaximumDate(), dateChanged."""
    dateChanged = pyqtSignal(QDate)

    def __init__(self, fecha=None, maximo=None, parent=None):
        super().__init__(parent)
        self._fecha = fecha or QDate.currentDate()
        self._maximo = maximo or QDate(2100, 12, 31)
        self._popup = None
        self._cierre = QElapsedTimer()   # sin iniciar hasta que se cierre un calendario

        self.setObjectName("selectorFecha")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(138, 30)
        self.setStyleSheet(f"""
            QFrame#selectorFecha {{ background-color: #FFFFFF; border: 1px solid #DCE3EC; border-radius: 8px; }}
            QFrame#selectorFecha:hover {{ border: 1px solid #B9C6DA; }}
            QFrame#selectorFecha:focus {{ border: 1px solid {PRIMARY}; }}
            QLabel {{ background: transparent; border: none; }}
            QLabel#textoFecha {{ color: #0F1B33; font-size: 13px; font-weight: 500; padding-left: 10px; }}
            QLabel#flechaFecha {{ background-color: #F7F8FC; border-left: 1px solid #E3E8F0;
                                  border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
        """)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._texto = QLabel()
        self._texto.setObjectName("textoFecha")
        flecha = QLabel()
        flecha.setObjectName("flechaFecha")
        flecha.setFixedWidth(28)
        flecha.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(_CHEVRON)
        if not pix.isNull():
            flecha.setPixmap(pix.scaled(11, 11, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(self._texto, 1)
        lay.addWidget(flecha)
        self._actualizar_texto()

    # ------------------------------------------------------------------ API
    def date(self):
        return self._fecha

    def setDate(self, fecha):
        if fecha > self._maximo:
            fecha = self._maximo
        if fecha != self._fecha:
            self._fecha = fecha
            self._actualizar_texto()
            self.dateChanged.emit(fecha)

    def setMaximumDate(self, maximo):
        self._maximo = maximo
        self.setDate(self._fecha)

    def _actualizar_texto(self):
        self._texto.setText(self._fecha.toString("dd-MM-yyyy"))

    # ------------------------------------------------------------------ interacción
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._alternar()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Down):
            self._alternar()
        else:
            super().keyPressEvent(event)

    def _alternar(self):
        # El clic que cierra el popup llega también al campo: sin esta espera
        # se cerraría y volvería a abrir al instante.
        if self._cierre.isValid() and self._cierre.elapsed() < ESPERA_REAPERTURA_MS:
            return
        if self._popup is not None and self._popup.isVisible():
            self._popup.close()
            return
        self._popup = CalendarioPopup(self, self._fecha, self._maximo)
        self._popup.fecha_elegida.connect(self.setDate)
        self._popup.cerrado.connect(self._al_cerrar_popup)
        self._popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._popup.abrir_en(self.mapToGlobal(QPoint(0, self.height() + 2)))

    def _al_cerrar_popup(self):
        self._cierre.restart()
        self._popup = None
