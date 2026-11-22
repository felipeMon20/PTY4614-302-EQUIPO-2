"""Diálogo previo a "Generar facturación del mes": si se agrupa por flota y qué flotas se generan."""
import os
import tempfile

import qtawesome as qta
from PyQt6.QtCore import QPointF, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout)

_AZUL = "#1B2B4E"
_TINTA = "#0F1B33"
_APAGADO = "#6B7A90"
_LINEA = "#E3E8F0"
_marca = {}


def _imagen_marca():
    """Ruta de un PNG con la marca de verificación blanca, para pintar las casillas marcadas."""
    if "ruta" not in _marca:
        ruta = os.path.join(tempfile.gettempdir(), "gestor_sscc_marca_check.png")
        try:
            qta.icon("fa5s.check", color="white").pixmap(12, 12).save(ruta)
            _marca["ruta"] = ruta.replace("\\", "/")
        except Exception:
            _marca["ruta"] = ""
    return _marca["ruta"]


def _qss_casillas():
    marca = _imagen_marca()
    imagen = f"image: url({marca});" if marca else ""
    return (
        "QCheckBox { background: transparent; color: #0F1B33; font-size: 13px; font-weight: 700; spacing: 8px; }"
        "QCheckBox::indicator, QListWidget::indicator { width: 16px; height: 16px; border: 2px solid #66748D;"
        " border-radius: 5px; background: #FFFFFF; }"
        "QCheckBox::indicator:hover, QListWidget::indicator:hover { border-color: #1B2B4E; }"
        f"QCheckBox::indicator:checked, QListWidget::indicator:checked {{ background-color: #1B2B4E; border-color: #1B2B4E; {imagen} }}")


def _boton(texto, primario=False):
    btn = QPushButton(texto)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if primario:
        btn.setStyleSheet(
            f"QPushButton {{ background: {_AZUL}; color: white; border: 1px solid {_AZUL}; border-radius: 8px; padding: 8px 20px;"
            " font-size: 13px; font-weight: 700; } QPushButton:hover { background: #2C4A80; border-color: #2C4A80; }"
            " QPushButton:disabled { background: #A9B4C6; border-color: #A9B4C6; }")
    else:
        btn.setStyleSheet(
            f"QPushButton {{ background: #FFFFFF; color: {_TINTA}; border: 1px solid #DCE3EC; border-radius: 8px; padding: 8px 20px;"
            " font-size: 13px; font-weight: 600; } QPushButton:hover { background: #F4F7FB; }")
    return btn


def _enlace(texto, lleno=False):
    btn = QPushButton(texto)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if lleno:
        btn.setStyleSheet("QPushButton { color: #1B2B4E; background: #E8EEF8; border: 1px solid #E8EEF8; border-radius: 13px;"
                          " font-size: 12px; font-weight: 700; padding: 5px 14px; }"
                          " QPushButton:hover { background: #1B2B4E; color: white; border-color: #1B2B4E; }")
    else:
        btn.setStyleSheet("QPushButton { color: #1B2B4E; background: #FFFFFF; border: 1px solid #C9D3E3; border-radius: 13px;"
                          " font-size: 12px; font-weight: 700; padding: 5px 14px; }"
                          " QPushButton:hover { background: #F4F7FB; border-color: #1B2B4E; }")
    return btn


class _FilaFlota(QStyledItemDelegate):
    """Fila de dos líneas: casilla, nombre de la flota y detalle; el clic sobre toda la fila marca o desmarca."""

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), 54)

    def editorEvent(self, event, model, option, index):
        return False

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(2, 2, -2, -2)
        marcada = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value
        if option.state & QStyle.StateFlag.State_MouseOver:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#F4F7FB"))
            painter.drawRoundedRect(r, 8, 8)
        caja = QRectF(r.left() + 10, r.center().y() - 9, 18, 18)
        painter.setPen(QPen(QColor(_AZUL if marcada else "#9AA8BD"), 1.6))
        painter.setBrush(QColor(_AZUL if marcada else "#FFFFFF"))
        painter.drawRoundedRect(caja, 5, 5)
        if marcada:
            pen = QPen(QColor("white"), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline([QPointF(caja.left() + 4.5, caja.center().y() + 0.5),
                                  QPointF(caja.left() + 7.7, caja.center().y() + 3.6),
                                  QPointF(caja.left() + 13.5, caja.center().y() - 3.2)])
        texto = QRectF(caja.right() + 12, r.top() + 5, r.right() - caja.right() - 20, 20)
        fuente = QFont(option.font)
        fuente.setPixelSize(13)
        fuente.setWeight(QFont.Weight.Bold)
        painter.setFont(fuente)
        painter.setPen(QColor(_TINTA))
        nombre = painter.fontMetrics().elidedText(index.data(Qt.ItemDataRole.DisplayRole), Qt.TextElideMode.ElideRight, int(texto.width()))
        painter.drawText(texto, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, nombre)
        fuente.setPixelSize(11)
        fuente.setWeight(QFont.Weight.Normal)
        painter.setFont(fuente)
        painter.setPen(QColor(_APAGADO))
        painter.drawText(texto.translated(0, 19), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         index.data(Qt.ItemDataRole.UserRole + 1))
        painter.restore()


class DialogoGenerarFacturacion(QDialog):
    """`flotas`: lista de (clave, nombre, razones, unidades). Al aceptar, `agrupar` y `claves` traen lo elegido."""

    def __init__(self, padre, etiqueta_periodo, flotas):
        super().__init__(padre)
        self.setWindowTitle("Generar facturación")
        self.setModal(True)
        self.setFixedWidth(780)
        self.setStyleSheet("QDialog { background: #FFFFFF; }" + _qss_casillas())
        self._flotas = list(flotas)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)

        titulo = QLabel("Generar facturación del mes")
        titulo.setStyleSheet(f"font-size: 17px; font-weight: 800; color: {_TINTA};")
        sub = QLabel(f"{etiqueta_periodo} · se crea una carpeta por flota")
        sub.setStyleSheet(f"font-size: 12px; color: {_APAGADO};")
        lay.addWidget(titulo)
        lay.addWidget(sub)

        self.chk_agrupar = QCheckBox("Agrupar por flota (un PDF y un Excel por flota)")
        self.chk_agrupar.setChecked(True)
        self.chk_agrupar.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chk_agrupar.toggled.connect(self._texto_agrupar)
        lay.addWidget(self.chk_agrupar)
        self.lbl_agrupar = QLabel()
        self.lbl_agrupar.setWordWrap(True)
        self.lbl_agrupar.setStyleSheet(f"font-size: 12px; color: {_APAGADO};")
        lay.addWidget(self.lbl_agrupar)
        self._texto_agrupar(True)

        cab = QHBoxLayout()
        cab.setSpacing(6)
        lbl = QLabel("Flotas a generar")
        lbl.setStyleSheet(f"font-size: 13px; font-weight: 800; color: {_TINTA};")
        self.lbl_cuenta = QLabel("")
        self.lbl_cuenta.setStyleSheet(f"font-size: 12px; color: {_APAGADO};")
        todas, ninguna = _enlace("Marcar todas", True), _enlace("Desmarcar todas")
        todas.clicked.connect(lambda: self._marcar_visibles(True))
        ninguna.clicked.connect(lambda: self._marcar_visibles(False))
        cab.addWidget(lbl)
        cab.addWidget(self.lbl_cuenta)
        cab.addStretch(1)
        cab.addWidget(todas)
        cab.addWidget(ninguna)
        lay.addLayout(cab)

        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Buscar flota…")
        self.buscador.setClearButtonEnabled(True)
        self.buscador.setStyleSheet(
            "QLineEdit { background: white; border: 1px solid #E3E8F0; border-radius: 8px; padding: 7px 10px; font-size: 12px;"
            " color: #0F1B33; } QLineEdit:focus { border: 1px solid #1B2B4E; }")
        self.buscador.textChanged.connect(self._filtrar)
        lay.addWidget(self.buscador)

        self.lista = QListWidget()
        self.lista.setFixedHeight(280)
        self.lista.setStyleSheet(
            f"QListWidget {{ background: #FFFFFF; border: 1px solid {_LINEA}; border-radius: 12px; outline: none; padding: 4px; }}"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 2px; }"
            "QScrollBar::handle:vertical { background: #C9D3E3; border-radius: 3px; min-height: 30px; }"
            "QScrollBar::handle:vertical:hover { background: #1B2B4E; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }")
        self.lista.setItemDelegate(_FilaFlota(self.lista))
        self.lista.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lista.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.lista.setMouseTracking(True)
        self.lista.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lista.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.lista.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lista.itemClicked.connect(self._alternar)
        for clave, nombre, razones, unidades in self._flotas:
            detalle = f"{razones} {'razón social' if razones == 1 else 'razones sociales'} · {unidades} u."
            item = QListWidgetItem(nombre)
            item.setData(Qt.ItemDataRole.UserRole + 1, detalle)
            item.setData(Qt.ItemDataRole.UserRole, clave)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.lista.addItem(item)
        self.lista.itemChanged.connect(lambda _i: self._actualizar())
        lay.addWidget(self.lista)

        botones = QHBoxLayout()
        botones.addStretch(1)
        cancelar = _boton("Cancelar")
        cancelar.clicked.connect(self.reject)
        self.btn_continuar = _boton("Continuar", primario=True)
        self.btn_continuar.clicked.connect(self.accept)
        botones.addWidget(cancelar)
        botones.addWidget(self.btn_continuar)
        lay.addLayout(botones)
        self._actualizar()

    def _texto_agrupar(self, agrupar):
        self.lbl_agrupar.setText(
            "Cada flota lleva un solo PDF y un solo Excel con todas sus razones sociales, cada una con sus propios montos."
            if agrupar else
            "La carpeta de cada flota lleva un PDF y un Excel por cada razón social.")

    def showEvent(self, event):
        super().showEvent(event)
        pantalla = self.screen()
        if pantalla is not None:
            centro = pantalla.availableGeometry().center()
            marco = self.frameGeometry()
            marco.moveCenter(centro)
            self.move(marco.topLeft())

    def _alternar(self, item):
        item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def _filtrar(self, texto):
        texto = texto.strip().lower()
        for i in range(self.lista.count()):
            self.lista.item(i).setHidden(bool(texto) and texto not in self.lista.item(i).text().lower())

    def _marcar_visibles(self, marcar):
        self.lista.blockSignals(True)
        for i in range(self.lista.count()):
            item = self.lista.item(i)
            if not item.isHidden():
                item.setCheckState(Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked)
        self.lista.blockSignals(False)
        self._actualizar()

    def _actualizar(self):
        marcadas = len(self.claves)
        self.lbl_cuenta.setText(f"{marcadas} de {self.lista.count()} marcadas")
        self.btn_continuar.setEnabled(marcadas > 0)

    @property
    def agrupar(self):
        return self.chk_agrupar.isChecked()

    @property
    def claves(self):
        return {self.lista.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lista.count())
                if self.lista.item(i).checkState() == Qt.CheckState.Checked}
