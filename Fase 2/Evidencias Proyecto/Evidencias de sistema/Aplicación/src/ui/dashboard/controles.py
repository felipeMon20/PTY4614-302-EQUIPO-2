"""Selector múltiple, hilo de cálculo y panel de metas del Dashboard."""
import logging
from PyQt6.QtCore import QEvent, QObject, QThread, pyqtSignal
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)
from src.ui.compartido.comercial_estilo import PopupFiltroValores, ubicar_popup_selector
from src.services import dashboard_services as servicio


class SelectorMultiple(QPushButton):
    """Botón para elegir varios valores a la vez: abre la tarjeta de casillas del resto de la app.
    Imita lo justo de un combo (currentData, setCurrentIndex, currentIndexChanged) para usarlo como
    los demás filtros; sin nada elegido no filtra."""
    currentIndexChanged = pyqtSignal(int)
    _ESTILO = ("QPushButton { background: white; color: #0F1B33; border: 1px solid #D9DEE8; border-radius: 9px; "
               "padding: 7px 12px; font-size: 12px; font-weight: 700; min-width: 40px; text-align: left; } "
               "QPushButton:hover { border-color: #B9C6DA; }")

    def __init__(self, titulo, plural, abreviar=False):
        super().__init__()
        self._titulo = titulo
        self._plural = plural
        self._abreviar = abreviar
        self._opciones = []
        self._elegidos = []
        self._popup = None
        self.setStyleSheet(self._ESTILO)
        self._texto()

    def currentData(self):
        return list(self._elegidos)

    def setCurrentIndex(self, _indice=0):
        if self._elegidos:
            self._elegidos = []
            self._texto()
            self.currentIndexChanged.emit(0)

    def set_opciones(self, pares):
        """pares: [(nombre, valor)]; los elegidos que ya no existen se descartan."""
        self._opciones = list(pares)
        validos = {v for _, v in self._opciones}
        self._elegidos = [v for v in self._elegidos if v in validos]
        self._texto()

    def _texto(self):
        nombres = {v: n for n, v in self._opciones}
        if not self._elegidos:
            texto = self._titulo
        elif len(self._elegidos) == 1:
            texto = nombres.get(self._elegidos[0], self._titulo)
        elif self._abreviar and len(self._elegidos) <= 3:
            texto = ", ".join(nombres.get(v, "")[:3] for v in self._elegidos)
        else:
            texto = f"{len(self._elegidos)} {self._plural}"
        self.setText(texto)

    def mouseReleaseEvent(self, evento):
        super().mouseReleaseEvent(evento)
        if self.rect().contains(evento.position().toPoint()) and self._opciones:
            self._abrir()

    def _abrir(self):
        valores = [(valor, nombre, None) for nombre, valor in self._opciones]
        marcados = {v for _, v in self._opciones} if not self._elegidos else set(self._elegidos)
        popup = PopupFiltroValores(self._titulo, valores, marcados, self._aplicar)
        popup.setFixedWidth(max(self.width(), 250) + 28)
        ubicar_popup_selector(popup, self)
        self._popup = popup
        popup.show()
        popup.buscador.setFocus()

    def _aplicar(self, marcados):
        """Los marcados son los que se muestran; con todos o ninguno marcado no hay filtro."""
        todos = {v for _, v in self._opciones}
        marcados = set(marcados)
        nuevos = [] if not marcados or marcados >= todos else [v for _, v in self._opciones if v in marcados]
        if nuevos == self._elegidos:
            return
        self._elegidos = nuevos
        self._texto()
        self.currentIndexChanged.emit(0)


_ESTILO_CHIP = ("QPushButton { background: #FFFFFF; color: #1B2B4E; border: 1px solid #DCE3EC; border-radius: 9px; "
                "padding: 6px 0; font-size: 12px; font-weight: 700; } "
                "QPushButton:hover { border-color: #1B2B4E; background: #F1F4F9; } "
                "QPushButton:checked { background: #1B2B4E; color: #FFFFFF; border-color: #1B2B4E; } "
                "QPushButton:disabled { color: #B5BFCF; background: #F7F9FC; border-color: #EEF1F6; }")


class PopupPeriodo(QFrame):
    """Tarjeta del selector de período: años (uno a la vez) y meses en cuadrícula. Un mes se marca con un
    clic y, sin nada marcado, muestra solo ese; los siguientes se suman o se quitan con normalidad."""

    def __init__(self, selector):
        super().__init__(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._selector = selector
        externo = QVBoxLayout(self)
        externo.setContentsMargins(14, 8, 14, 20)
        tarjeta = QFrame()
        tarjeta.setObjectName("popupPeriodo")
        tarjeta.setStyleSheet("QFrame#popupPeriodo { background: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 14px; }")
        sombra = QGraphicsDropShadowEffect(tarjeta)
        sombra.setBlurRadius(28)
        sombra.setOffset(0, 8)
        sombra.setColor(QColor(27, 43, 78, 70))
        tarjeta.setGraphicsEffect(sombra)
        externo.addWidget(tarjeta)
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        estilo_titulo = ("color: #66748D; font-size: 10px; font-weight: 800; letter-spacing: 1px; "
                         "background: transparent; border: none; padding-left: 2px;")
        titulo = QLabel("PERÍODO DE INICIO DE CONTRATO")
        titulo.setStyleSheet(estilo_titulo)
        lay.addWidget(titulo)
        # `lista` es el cuerpo: ubicar_popup_selector lo usa para medir y acortar la tarjeta si no cabe
        self.lista = QWidget()
        self.lista.setObjectName("cuerpoPeriodo")
        self.lista.setStyleSheet("QWidget#cuerpoPeriodo { background: transparent; }")
        lay_cuerpo = QVBoxLayout(self.lista)
        lay_cuerpo.setContentsMargins(0, 0, 0, 0)
        lay_cuerpo.setSpacing(8)
        lay.addWidget(self.lista)
        lay_cuerpo.addWidget(self._subtitulo("Año", estilo_titulo))
        self._rejilla_anios = QGridLayout()
        self._rejilla_anios.setSpacing(6)
        lay_cuerpo.addLayout(self._rejilla_anios)
        lay_cuerpo.addWidget(self._subtitulo("Mes", estilo_titulo))
        self._rejilla_meses = QGridLayout()
        self._rejilla_meses.setSpacing(6)
        lay_cuerpo.addLayout(self._rejilla_meses)
        pie = QHBoxLayout()
        self._lbl_pie = QLabel("")
        self._lbl_pie.setStyleSheet("color: #8A97AB; font-size: 10px; background: transparent; border: none;")
        self._lbl_pie.setWordWrap(True)
        pie.addWidget(self._lbl_pie, 1)
        self._btn_limpiar = QPushButton("Limpiar")
        self._btn_limpiar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_limpiar.setStyleSheet("QPushButton { border: none; background: transparent; color: #1F6FEB; font-size: 11px; "
                                        "font-weight: 700; padding: 2px 4px; } QPushButton:hover { text-decoration: underline; }")
        self._btn_limpiar.clicked.connect(selector.limpiar_desde_popup)
        pie.addWidget(self._btn_limpiar)
        lay_cuerpo.addLayout(pie)
        self.actualizar()

    @staticmethod
    def _subtitulo(texto, estilo):
        etiqueta = QLabel(texto.upper())
        etiqueta.setStyleSheet(estilo)
        return etiqueta

    @staticmethod
    def _vaciar(rejilla):
        while rejilla.count():
            item = rejilla.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()   # deleteLater tarda: sin ocultarlo se vería duplicado un momento
                item.widget().deleteLater()

    def _chip(self, texto, marcado, habilitado, al_clic, ayuda=""):
        boton = QPushButton(texto)
        boton.setCheckable(True)
        boton.setChecked(marcado)
        boton.setEnabled(habilitado)
        boton.setCursor(Qt.CursorShape.PointingHandCursor)
        boton.setStyleSheet(_ESTILO_CHIP)
        if ayuda:
            boton.setToolTip(ayuda)
        boton.clicked.connect(al_clic)
        return boton

    def actualizar(self):
        """Redibuja los chips con el estado actual del selector (también si cambian las opciones con el popup abierto)."""
        s = self._selector
        self._vaciar(self._rejilla_anios)
        self._vaciar(self._rejilla_meses)
        for i, anio in enumerate(s._anios):
            chip = self._chip(str(anio), s._anio == anio, True, lambda _=False, a=anio: s.elegir_anio(a))
            self._rejilla_anios.addWidget(chip, i // 4, i % 4)
            chip.show()   # los que se agregan con la tarjeta ya abierta no se muestran solos
        for m in range(1, 13):
            chip = self._chip(servicio.MESES[m - 1][:3], m in s._elegidos, m in s._meses,
                              lambda _=False, n=m: s.alternar_mes(n), servicio.MESES[m - 1])
            self._rejilla_meses.addWidget(chip, (m - 1) // 4, (m - 1) % 4)
            chip.show()
        self._lbl_pie.setText("Sin elegir nada se muestran todos los períodos." if not s.currentData()
                              else "Presiona un mes para sumarlo o quitarlo.")
        self._btn_limpiar.setVisible(bool(s.currentData()))
        self.lista.layout().activate()
        self.lista.setFixedHeight(self.lista.layout().sizeHint().height())


class SelectorPeriodo(QPushButton):
    """Un solo botón para Año y Mes de inicio de contrato. Imita lo justo de un combo (currentData,
    setCurrentIndex, currentIndexChanged); el valor es {'anio': int | '', 'meses': [int]} o '' sin filtro."""
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, titulo="Período"):
        super().__init__()
        self._titulo = titulo
        self._anios, self._meses = [], []
        self._anio = ""
        self._elegidos = []
        self._popup = None
        self.setStyleSheet(SelectorMultiple._ESTILO)
        self._texto()

    def currentData(self):
        if not self._anio and not self._elegidos:
            return ""
        return {"anio": self._anio, "meses": list(self._elegidos)}

    def setCurrentIndex(self, _indice=0):
        if self._anio or self._elegidos:
            self._anio, self._elegidos = "", []
            self._cambiado()

    def set_opciones(self, anios, meses):
        """`anios` y `meses` (1-12) con datos según los demás filtros; lo elegido que ya no existe se descarta."""
        self._anios, self._meses = list(anios), list(meses)
        if self._anio and self._anio not in self._anios:
            self._anio = ""
        self._elegidos = [m for m in self._elegidos if m in self._meses]
        self._texto()
        if self._popup is not None and self._popup.isVisible():
            self._popup.actualizar()

    def _texto(self):
        nombres = [servicio.MESES[m - 1] for m in self._elegidos]
        if len(nombres) > 3:
            meses = f"{len(nombres)} meses"
        else:
            meses = ", ".join(n if len(nombres) == 1 else n[:3] for n in nombres)
        partes = [str(self._anio)] if self._anio else []
        if meses:
            partes.append(meses)
        self.setText(" · ".join(partes) if partes else self._titulo)

    def _cambiado(self):
        self._texto()
        if self._popup is not None and self._popup.isVisible():
            self._popup.actualizar()
        self.currentIndexChanged.emit(0)

    def elegir_anio(self, anio):
        self._anio = "" if self._anio == anio else anio
        self._cambiado()

    def alternar_mes(self, mes):
        """Sin meses marcados el clic deja solo ese mes; con otros marcados lo suma o lo quita."""
        if mes in self._elegidos:
            self._elegidos.remove(mes)
        else:
            self._elegidos = sorted(self._elegidos + [mes])
        self._cambiado()

    def limpiar_desde_popup(self):
        self.setCurrentIndex(0)

    def mouseReleaseEvent(self, evento):
        super().mouseReleaseEvent(evento)
        if self.rect().contains(evento.position().toPoint()) and (self._anios or self._meses):
            self._abrir()

    def _abrir(self):
        popup = PopupPeriodo(self)
        popup.setFixedWidth(max(self.width(), 250) + 28)
        ubicar_popup_selector(popup, self)
        self._popup = popup
        popup.show()


class _CalculoPanorama(QThread):
    """Calcula el panorama sin bloquear la ventana; si falla, entrega None."""
    terminado = pyqtSignal(object)

    def __init__(self, df, parent=None):
        super().__init__(parent)
        self._df = df

    def run(self):
        try:
            resultado = servicio.calcular_panorama(self._df)
        except Exception:
            logging.getLogger(__name__).exception("No se pudo calcular el panorama del Dashboard")
            resultado = None
        self.terminado.emit(resultado)


class _IgnorarRueda(QObject):
    """Evita que la rueda del mouse cambie sin querer un combo o un número."""
    def eventFilter(self, objeto, evento):
        return evento.type() == QEvent.Type.Wheel
