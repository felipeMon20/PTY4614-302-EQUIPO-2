"""Alta de varias unidades de un mismo cliente: una ficha, una lista de VIN con scroll."""
import os
import re
import tempfile
from PyQt6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QWidget, QAbstractItemView, QComboBox, QGraphicsOpacityEffect,
)
from PyQt6.QtCore import Qt, QTimer, QVariantAnimation, QEasingCurve, QRectF, QPointF
from PyQt6.QtGui import QColor, QPainter, QPen
import qtawesome as qta
from src.services.vin_service import obtener_modelo_desde_vin
from src.ui.compartido.comercial_estilo import ComboTarjeta
from src.ui.comercial_agregar.base import _CAMPOS_OBLIGATORIOS

_LARGO_MINIMO_VIN = 7
_CAMPOS_DE_LA_LISTA = ('VIN', 'CHASIS', 'MODELO')
_COLORES_ESTADO = {
    'Nueva': ('#1F7A55', '#E4F5EC'), 'Ya existe': ('#B3261E', '#FBE4E2'),
    'Repetido': ('#9A6A00', '#FDF1D3'), 'Incompleto': ('#B3261E', '#FBE4E2'),
}
_ALTO_FILA = 30


def _ruta_chevron():
    """Flecha del selector de modelo: se genera una vez como imagen, porque el QSS solo admite archivos."""
    ruta = os.path.join(tempfile.gettempdir(), "gsb_chevron_modelo.png")
    if not os.path.exists(ruta):
        qta.icon('fa5s.chevron-down', color='#66748D').pixmap(18, 18).save(ruta)
    return ruta.replace("\\", "/")


class _BotonQuitar(QPushButton):
    """Círculo gris con una X que pasa a rojo, con transición corta, al acercar el mouse."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Quitar este VIN de la lista")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._t = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(130)
        self._anim.valueChanged.connect(self._fijar)

    def _fijar(self, valor):
        self._t = float(valor)
        self.update()

    def _ir_a(self, destino):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(destino)
        self._anim.start()

    def enterEvent(self, evento):
        self._ir_a(1.0)
        super().enterEvent(evento)

    def leaveEvent(self, evento):
        self._ir_a(0.0)
        super().leaveEvent(evento)

    @staticmethod
    def _mezcla(a, b, t):
        return QColor(*(int(a.getRgb()[i] + (b.getRgb()[i] - a.getRgb()[i]) * t) for i in range(3)))

    def paintEvent(self, _evento):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._t
        borde = self._mezcla(QColor('#CBD3E1'), QColor('#B3261E'), t)
        trazo = self._mezcla(QColor('#8A97AB'), QColor('#B3261E'), t)
        fondo = self._mezcla(QColor('#FFFFFF'), QColor('#FBE4E2'), t)
        p.setPen(QPen(borde, 1.2))
        p.setBrush(fondo)
        p.drawEllipse(QRectF(1, 1, self.width() - 2, self.height() - 2))
        p.setPen(QPen(trazo, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        m = 7.5
        p.drawLine(QPointF(m, m), QPointF(self.width() - m, self.height() - m))
        p.drawLine(QPointF(self.width() - m, m), QPointF(m, self.height() - m))


_ESTILO_BARRA = (
    "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; } "
    "QScrollBar::handle:vertical { background: #CBD3E1; border-radius: 3px; min-height: 24px; } "
    "QScrollBar::handle:vertical:hover { background: #9AA7BD; } "
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; } "
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
)


class _VariasUnidadesMixin:
    _modo_varias = False
    _vins_validos = ()
    _quitando = False

    def _construir_panel_vins(self, tarjeta_unidad, layout_pagina):
        """La lista vive dentro de la tarjeta de la unidad, a la derecha del CDB, y ocupa el espacio libre."""
        self._tarjeta_unidad = tarjeta_unidad
        self._layout_pagina = layout_pagina
        panel = QFrame(tarjeta_unidad)
        panel.setObjectName("panelVins")
        panel.setStyleSheet("QFrame#panelVins { background: transparent; border: none; }")
        fila_campos = tarjeta_unidad.findChild(QFrame, "sectionFields").layout().itemAt(0).layout()
        fila_campos.addWidget(panel, 1)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        fila = QHBoxLayout()
        titulo = QLabel("VIN de las unidades")
        titulo.setStyleSheet("font-size: 14px; font-weight: 600; color: #0F1B33; background: transparent; border: none;")
        self._lbl_resumen_vins = QLabel("")
        self._lbl_resumen_vins.setStyleSheet("font-size: 12px; color: #66748D; background: transparent; border: none;")
        fila.addWidget(titulo)
        fila.addStretch()
        fila.addWidget(self._lbl_resumen_vins)
        lay.addLayout(fila)

        self._txt_vins = QPlainTextEdit()
        self._txt_vins.setPlaceholderText("Pega aquí los VIN, uno por línea (también desde Excel)")
        self._txt_vins.setFixedWidth(250)
        self._txt_vins.setStyleSheet(
            "QPlainTextEdit { border: 1px solid #E3E8F0; border-radius: 10px; padding: 8px 10px; background: #F9FAFC; "
            "color: #0F1B33; font-size: 12px; selection-background-color: #DCE6F7; selection-color: #0F1B33; } "
            "QPlainTextEdit:focus { border: 1px solid #1B2B4E; background: #FFFFFF; } "
            + _ESTILO_BARRA)
        self._txt_vins.textChanged.connect(self._refrescar_lista_vins)
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(14)
        lay.addLayout(cuerpo, 1)
        cuerpo.addWidget(self._txt_vins)

        marco = QFrame()
        marco.setObjectName("tablaVins")
        marco.setFixedWidth(580)
        marco.setMinimumHeight(110)
        marco.setStyleSheet("QFrame#tablaVins { background: #FFFFFF; border: 1px solid #E3E8F0; border-radius: 10px; }")
        lay_marco = QVBoxLayout(marco)
        lay_marco.setContentsMargins(1, 1, 1, 1)
        self._tabla_vins = QTableWidget(0, 5)
        self._tabla_vins.setHorizontalHeaderLabels(["VIN", "CHASIS", "MODELO", "ESTADO", ""])
        self._tabla_vins.verticalHeader().setVisible(False)
        self._tabla_vins.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tabla_vins.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._tabla_vins.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tabla_vins.setShowGrid(False)
        self._tabla_vins.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._tabla_vins.verticalHeader().setDefaultSectionSize(_ALTO_FILA)
        cabecera = self._tabla_vins.horizontalHeader()
        cabecera.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        cabecera.setHighlightSections(False)
        cabecera.setFixedHeight(30)
        cabecera.setMinimumSectionSize(30)
        self._tabla_vins.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for col, ancho in enumerate((172, 90, 106, 122)):
            cabecera.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            self._tabla_vins.setColumnWidth(col, ancho)
        cabecera.setStretchLastSection(True)
        self._tabla_vins.setStyleSheet(
            "QTableWidget { border: none; background: transparent; font-size: 12px; color: #0F1B33; } "
            "QTableWidget::item { padding: 0 10px; border-bottom: 1px solid #F0F3F8; } "
            "QHeaderView { background: #F7F8FC; border: none; } "
            "QHeaderView::section { background: #F7F8FC; border: none; border-bottom: 1px solid #E3E8F0; "
            "color: #66748D; font-size: 10px; font-weight: 700; letter-spacing: 1px; padding: 7px 10px; } "
            "QTableCornerButton::section { background: #F7F8FC; border: none; } "
            + _ESTILO_BARRA.replace("margin: 2px", "margin: 32px 2px 4px 2px"))
        lay_marco.addWidget(self._tabla_vins)
        cuerpo.addWidget(marco)
        cuerpo.addStretch(1)
        self._modelos_elegidos = {}
        self._lineas_filas = []
        panel.setVisible(False)
        return panel

    def _construir_boton_varias(self, tarjeta_unidad):
        """Interruptor "Varias unidades" en el encabezado de la sección de la unidad."""
        encabezado = tarjeta_unidad.findChild(QFrame, "sectionHeader")
        self._btn_varias = QPushButton(" Varias unidades")
        self._btn_varias.setIcon(qta.icon('fa5s.layer-group', color='#1B2B4E', color_off='#1B2B4E', color_on='#FFFFFF', color_active='#1B2B4E', color_on_active='#FFFFFF'))
        self._btn_varias.setCheckable(True)
        self._btn_varias.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_varias.setAutoDefault(False)
        self._btn_varias.setToolTip("Crea varias unidades del mismo cliente con los mismos datos pegando la lista de VIN.")
        self._btn_varias.setStyleSheet(
            "QPushButton { background: #FFFFFF; color: #1B2B4E; border: 1px solid #DCE3EC; border-radius: 8px; "
            "padding: 5px 12px; font-size: 12px; font-weight: 600; } "
            "QPushButton:hover { background: #F1F4F9; } "
            "QPushButton:checked { background: #1B2B4E; color: #FFFFFF; border-color: #1B2B4E; }")
        self._btn_varias.toggled.connect(self._set_modo_varias)
        lay_enc = encabezado.layout()
        lay_enc.setStretch(1, 0)
        lay_enc.insertSpacing(2, 6)
        lay_enc.insertWidget(3, self._btn_varias, 0, Qt.AlignmentFlag.AlignVCenter)
        lay_enc.insertStretch(4, 1)
        self._btn_varias.setVisible(False)

    def _obligatorios_activos(self):
        if self._modo_varias:
            return _CAMPOS_OBLIGATORIOS - set(_CAMPOS_DE_LA_LISTA)
        return _CAMPOS_OBLIGATORIOS

    def _set_modo_varias(self, activo):
        activo = bool(activo)
        if activo == self._modo_varias:
            return
        self._modo_varias = activo
        if self._btn_varias.isChecked() != activo:
            self._btn_varias.blockSignals(True)
            self._btn_varias.setChecked(activo)
            self._btn_varias.blockSignals(False)
        for campo in _CAMPOS_DE_LA_LISTA:
            self.inputs[campo].setVisible(not activo)
            self._etiquetas_campo[campo].setVisible(not activo)
        self._panel_vins.setVisible(activo)
        self._layout_pagina.setStretchFactor(self._tarjeta_unidad, 10 if activo else 0)
        self._modelos_elegidos.clear()
        self._txt_vins.blockSignals(True)
        self._txt_vins.clear()
        self._txt_vins.blockSignals(False)
        if activo:
            self.inputs['VIN'].setText("")
            self._txt_vins.setFocus()
        self._refrescar_lista_vins()
        self._actualizar_titulo()

    def _filas_lista_vins(self):
        """[(vin, chasis, modelo, estado)] de lo escrito; solo se lee el primer dato de cada línea.
        Deja en `_lineas_filas` el número de línea de cada fila, para poder quitarla de la caja."""
        existentes = getattr(self, '_vins_existentes', set())
        modelos = {self.inputs['MODELO'].itemText(i) for i in range(self.inputs['MODELO'].count())}
        vistos = set()
        filas = []
        self._lineas_filas = []
        for n_linea, linea in enumerate(self._txt_vins.toPlainText().splitlines()):
            partes = [p for p in re.split(r'[\s,;]+', linea.strip()) if p]
            if not partes:
                continue
            vin = partes[0].upper()
            if len(vin) < _LARGO_MINIMO_VIN:
                estado = 'Incompleto'
            elif vin in existentes:
                estado = 'Ya existe'
            elif vin in vistos:
                estado = 'Repetido'
            else:
                estado = 'Nueva'
            vistos.add(vin)
            modelo = self._modelos_elegidos.get(vin)
            if modelo is None:
                modelo = obtener_modelo_desde_vin(vin) if len(vin) >= _LARGO_MINIMO_VIN else None
                if modelo not in modelos:
                    modelo = self.inputs['MODELO'].currentText() or '-'
            filas.append((vin, vin[-_LARGO_MINIMO_VIN:] if len(vin) >= _LARGO_MINIMO_VIN else '', modelo, estado))
            self._lineas_filas.append(n_linea)
        return filas

    def _combo_modelo_fila(self, vin, modelo):
        combo = ComboTarjeta("Modelo")
        combo.addItems([self.inputs['MODELO'].itemText(i) for i in range(self.inputs['MODELO'].count())])
        combo.setCurrentText(modelo)
        combo.setFixedHeight(_ALTO_FILA - 8)
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.setStyleSheet(
            "QComboBox { border: 1px solid #E3E8F0; border-radius: 7px; padding: 0 22px 0 9px; font-size: 12px; "
            "background: #F7F8FC; color: #0F1B33; } "
            "QComboBox:hover { border-color: #B9C4D6; background: #FFFFFF; } "
            "QComboBox::drop-down { border: none; width: 20px; } "
            f"QComboBox::down-arrow {{ image: url({_ruta_chevron()}); width: 9px; height: 9px; }}")
        combo.setToolTip("Cambiar el modelo de esta unidad.")
        combo.currentTextChanged.connect(lambda texto, v=vin: self._elegir_modelo(v, texto))
        contenedor = QWidget()
        lay = QHBoxLayout(contenedor)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.addWidget(combo)
        return contenedor

    def _pastilla_estado(self, estado):
        color, fondo = _COLORES_ESTADO[estado]
        etiqueta = QLabel(estado)
        etiqueta.setStyleSheet(
            f"background: {fondo}; color: {color}; border-radius: 9px; padding: 2px 10px; "
            "font-size: 11px; font-weight: 700;")
        etiqueta.setFixedHeight(20)
        contenedor = QWidget()
        lay = QHBoxLayout(contenedor)
        lay.setContentsMargins(6, 0, 0, 0)
        lay.addWidget(etiqueta, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch()
        return contenedor

    def _elegir_modelo(self, vin, modelo):
        self._modelos_elegidos[vin] = modelo
        QTimer.singleShot(0, self._refrescar_lista_vins)

    def _celda_texto(self, texto, izquierda=10):
        etiqueta = QLabel(texto)
        etiqueta.setStyleSheet(f"background: transparent; color: #0F1B33; font-size: 12px; font-weight: 400; padding-left: {izquierda}px;")
        return etiqueta

    def _quitar_fila_lista(self, fila):
        """Quita el VIN: la fila se desvanece y se pliega; la línea se borra de la caja al terminar."""
        if fila >= len(self._lineas_filas) or self._quitando:
            return
        self._quitando = True
        linea = self._lineas_filas[fila]
        tabla = self._tabla_vins
        efectos = []
        for col in range(5):
            celda = tabla.cellWidget(fila, col)
            efecto = QGraphicsOpacityEffect(celda)
            celda.setGraphicsEffect(efecto)
            efectos.append(efecto)
        animacion = QVariantAnimation(self)
        animacion.setDuration(240)
        animacion.setStartValue(0.0)
        animacion.setEndValue(1.0)
        animacion.setEasingCurve(QEasingCurve.Type.OutCubic)

        def paso(v):
            for efecto in efectos:
                efecto.setOpacity(max(0.0, 1.0 - v / 0.55))
            tabla.setRowHeight(fila, max(1, int(_ALTO_FILA * (1.0 - max(0.0, (v - 0.45) / 0.55)))))
        animacion.valueChanged.connect(paso)
        animacion.finished.connect(lambda: self._terminar_quitar(linea))
        animacion.start()
        self._animacion_quitar = animacion

    def _terminar_quitar(self, linea):
        self._quitando = False
        lineas = self._txt_vins.toPlainText().splitlines()
        if linea < len(lineas):
            del lineas[linea]
            self._txt_vins.setPlainText("\n".join(lineas))

    def _refrescar_lista_vins(self):
        if not self._modo_varias:
            self._vins_validos = ()
            self._actualizar_texto_guardar()
            return
        filas = self._filas_lista_vins()
        self._vins_validos = tuple(f for f in filas if f[3] == 'Nueva')
        tabla = self._tabla_vins
        tabla.setUpdatesEnabled(False)
        tabla.setRowCount(0)
        tabla.setRowCount(len(filas))
        for r, (vin, chasis, modelo, estado) in enumerate(filas):
            tabla.setCellWidget(r, 0, self._celda_texto(vin))
            tabla.setCellWidget(r, 1, self._celda_texto(chasis, 2))
            tabla.setCellWidget(r, 2, self._combo_modelo_fila(vin, modelo))
            tabla.setCellWidget(r, 3, self._pastilla_estado(estado))
            quitar = _BotonQuitar()
            quitar.clicked.connect(lambda _=False, fila=r: self._quitar_fila_lista(fila))
            contenedor = QWidget()
            lay = QHBoxLayout(contenedor)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(quitar, 0, Qt.AlignmentFlag.AlignCenter)
            tabla.setCellWidget(r, 4, contenedor)
        tabla.setUpdatesEnabled(True)
        n, ok = len(filas), len(self._vins_validos)
        self._lbl_resumen_vins.setText(
            f"{n} leídos, {ok} listos, {n - ok} con problema" if n else "Sin VIN todavía")
        self.btn_save.setEnabled(ok > 0)
        self._actualizar_texto_guardar()
        self._actualizar_resumen()

    def _unidades_validas(self):
        return list(self._vins_validos) if self._modo_varias else []

    def _unidades_multiples(self):
        """Una fila de datos por cada VIN listo, con los mismos datos del formulario."""
        base = self.get_data()
        unidades = []
        for vin, chasis, modelo, _ in self._unidades_validas():
            datos = dict(base)
            datos.update({'VIN': vin, 'CHASIS': chasis, 'MODELO': modelo})
            unidades.append(datos)
        return unidades
