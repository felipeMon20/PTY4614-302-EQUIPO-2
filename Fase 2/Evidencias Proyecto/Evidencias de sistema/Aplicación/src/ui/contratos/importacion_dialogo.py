"""Resumen de la importación del Excel de contratos CM, con su tabla y filtros."""
from src.theme.colors import BACKGROUND, BORDER, PRIMARY, SURFACE, TEXT_MUTED, TEXT_PRIMARY, TEXT_SECONDARY
import pandas as pd
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QLineEdit, QFileDialog, QApplication, QStackedWidget, QScrollArea, QDialog, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QGuiApplication, QColor
from src.theme.theme_manager import ThemeManager
from src.ui.contratos.base import (
    _AVISOS_UNIDAD,
    _COLOR_ACTIVACION,
    _COLUMNAS_UNIDAD,
    _FILTROS_UNIDAD,
    _Interruptor,
    _ItemOrden,
    _TONOS_IMPORTACION,
    _dato_o_sin_dato,
    _numero_pago,
    _pago_importacion,
)


class ResumenImportacionDialog(QDialog):
    """Panel previo a inyectar un import de Contratos CM a la Base Comercial
    (ver ContratosModule.importar_excel_javiera). Dos pestañas: "Resumen"
    (qué cambia y qué hay que revisar) y "Por unidad" (cada unidad con lo
    relevante que cambia). El interruptor del pie decide si se aplican los
    cambios de forma de contrato y tipo de facturación; los datos del 3PC se
    actualizan siempre."""

    def __init__(self, resumen, nombre_archivo, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Importación de Contratos CM")
        self.setMinimumWidth(940)
        self.setStyleSheet(f"QDialog {{ background-color: {BACKGROUND}; }}")
        self._resumen = resumen
        self._filas = resumen.get('filas_unidad', [])
        self._filtro_actual = 'todas'
        # Unidades con cambio de forma y facturación: True si el cambio está autorizado. Las que pasan siempre
        # parten autorizadas; las de Provisión, Conversión o Venta, no (las marca el interruptor o cada casilla).
        self._autorizados = {f['vin']: 'forma' in f['categorias'] for f in self._filas
                             if 'forma' in f['categorias'] or 'otra_forma' in f['categorias']}
        self._filas_visibles = []

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(26, 20, 26, 0)
        raiz.setSpacing(14)
        raiz.addLayout(self._encabezado(resumen, nombre_archivo))
        raiz.addLayout(self._pestanas())

        self.pila = QStackedWidget()
        self.pila.addWidget(self._pagina_resumen(resumen))
        self.pila.addWidget(self._pagina_por_unidad())
        raiz.addWidget(self.pila, 1)
        raiz.addWidget(self._pie(resumen))

        pantalla = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(min(1320, pantalla.width() - 60), min(860, pantalla.height() - 60))
        self._poblar_tabla()

    # ------------------------------------------------------------ estructura
    def _encabezado(self, resumen, nombre_archivo):
        fila = QHBoxLayout()
        fila.setSpacing(14)
        icono = QLabel()
        icono.setFixedSize(44, 44)
        icono.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icono.setStyleSheet("background: #EAF1FF; border-radius: 12px;")
        icono.setPixmap(ThemeManager.icon('fa5s.file-invoice', color="#1D4ED8").pixmap(QSize(22, 22)))
        fila.addWidget(icono)
        textos = QVBoxLayout()
        textos.setSpacing(2)
        titulo = QLabel(nombre_archivo)
        titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 18px; font-weight: 700;")
        sub = QLabel(f"Comparado contra la Base Comercial actual · {resumen['total_coincidencias']} VIN con coincidencia")
        sub.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        textos.addWidget(titulo)
        textos.addWidget(sub)
        fila.addLayout(textos, 1)
        return fila

    def _pestanas(self):
        caja = QHBoxLayout()
        caja.setSpacing(26)
        self._botones_pestana = []
        for indice, texto in enumerate(("Resumen", f"Por unidad  ({len(self._filas)})")):
            boton = QPushButton(texto)
            boton.setCheckable(True)
            boton.setCursor(Qt.CursorShape.PointingHandCursor)
            boton.setStyleSheet(
                f"QPushButton {{ border: none; border-bottom: 3px solid transparent; background: transparent; padding: 8px 2px 10px;"
                f" color: {TEXT_SECONDARY}; font-size: 14px; font-weight: 600; }}"
                f"QPushButton:checked {{ color: #1D4ED8; border-bottom: 3px solid {PRIMARY}; font-weight: 700; }}")
            boton.clicked.connect(lambda _c=False, i=indice: self._ir_a_pestana(i))
            self._botones_pestana.append(boton)
            caja.addWidget(boton)
        caja.addStretch()
        self._botones_pestana[0].setChecked(True)
        return caja

    def _ir_a_pestana(self, indice):
        self.pila.setCurrentIndex(indice)
        for i, boton in enumerate(self._botones_pestana):
            boton.setChecked(i == indice)

    def _ver_unidades(self, categoria):
        self._ir_a_pestana(1)
        self._elegir_filtro(categoria)

    # ---------------------------------------------------------------- resumen
    def _pagina_resumen(self, resumen):
        ff = resumen.get('forma_facturacion', {})
        expired = resumen['pasan_a_expired']
        nuevos = len(resumen['contratos_nuevos'])
        cambian = ff.get('unidades', 0)
        otra_forma = ff.get('cm_otra_forma', {})
        total_otra = sum(len(v) for v in otra_forma.values())
        ausentes = len(resumen['vins_ausentes'])
        sin_ficha = len(resumen['vins_nuevos'])

        contenido = QWidget()
        contenido.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(contenido)
        lay.setContentsMargins(0, 4, 4, 8)
        lay.setSpacing(14)

        kpis = QHBoxLayout()
        kpis.setSpacing(12)
        for valor, etiqueta, color in (
                (resumen['total_filas_excel'], "Filas en el Excel", "#1D4ED8"),
                (resumen['total_actualizados'], "Se actualizarán", "#047857"),
                (cambian, "Cambian de forma de contrato", TEXT_PRIMARY),
                (expired, "Pasan a Expired", "#B45309")):
            kpis.addWidget(self._tarjeta_kpi(f"{valor:,}".replace(",", "."), etiqueta, color))
        lay.addLayout(kpis)

        columnas = QHBoxLayout()
        columnas.setSpacing(16)
        columnas.setAlignment(Qt.AlignmentFlag.AlignTop)

        if cambian:
            detalle_forma = " y ".join(f"{n} pasan de {a} a {d}" for (a, d), n in ff['forma'])
            detalle_forma += (f". {ff['conectadas']} conectadas, {ff['desconectadas']} desconectadas "
                              f"y {ff['otras']} en otro estado.")
        else:
            detalle_forma = "Ninguna unidad cambia."
        detalle_tipo = (" y ".join(f"{n} pasan de {a} a {d}" for (a, d), n in ff['tipo']) + "."
                        if ff.get('tipo') else "Ninguna unidad cambia.")
        self._desglose_opcional = " · ".join(f"{forma.title()} {len(vins)}" for forma, vins in otra_forma.items())
        filas_cambia = [
            ("Forma de contrato", detalle_forma, cambian, 'azul', None),
            ("Tipo de facturación", detalle_tipo, sum(n for _p, n in ff.get('tipo', [])), 'azul' if ff.get('tipo') else 'gris', None),
        ]
        if total_otra:
            filas_cambia.append(("Provisión, Conversión y Venta con CM en el 3PC", self._texto_opcional(False), total_otra,
                                 'azul', 'otra_forma'))
        filas_cambia += [
            ("Estado del CM", "Pasan a Expired. Sin pago este mes quedan Vencidas; con pago, en Revisar.", expired, 'ambar' if expired else 'gris',
             'expired' if expired else None),
            ("Contratos nuevos para reactivar",
             "Vienen en el 3PC pero están desconectadas en el RM (en Baja). Se crea un contrato nuevo con los mismos "
             "datos del anterior y pasa a Operaciones para activarlo.", nuevos, 'azul' if nuevos else 'gris',
             'nuevo' if nuevos else None),
            ("Datos del 3PC", "Fechas, tipo, estado y pago se actualizan en todas las unidades con coincidencia; "
                              "las que no pagaron este mes quedan con pago 0. "
                              "En las unidades con contrato nuevo se cargan en el contrato nuevo.",
             resumen['total_actualizados'], 'verde', None),
        ]
        columnas.addWidget(self._tarjeta_lista("QUÉ CAMBIA CON ESTA IMPORTACIÓN", filas_cambia), 1)

        filas_revisar = [
            ("Tienen CM en el RM, pero no vienen en este 3PC",
             "No se consideran bajas: quedan como estaban." if ausentes else "Todo en orden: todas vienen en el archivo.",
             ausentes, 'ambar' if ausentes else 'verde', None),
            ("Sin ficha en Comercial", "Se podrán vincular después de importar.", sin_ficha,
             'ambar' if sin_ficha else 'verde', None),
        ]
        columnas.addWidget(self._tarjeta_lista("PARA REVISAR", filas_revisar), 1)
        lay.addLayout(columnas)
        lay.addStretch()

        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.Shape.NoFrame)
        desplazable.setStyleSheet("QScrollArea { background: transparent; }")
        desplazable.setWidget(contenido)
        return desplazable

    def _texto_opcional(self, aplica):
        if aplica:
            return (f"Se pasan a CM: forma CMG, CMB o CMS según su tipo de CM y facturación CM. {self._desglose_opcional}. "
                    "Puedes quitar unidades una a una en Por unidad.")
        return (f"No se tocan, solo se actualizan sus datos del 3PC. {self._desglose_opcional}. "
                "Enciende el interruptor de abajo para pasarlas todas a CM, o autoriza unidad por unidad en Por unidad.")

    def _tarjeta_kpi(self, valor, etiqueta, color):
        tarjeta = QFrame()
        tarjeta.setStyleSheet(f"QFrame {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        lbl_valor = QLabel(valor)
        lbl_valor.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: 800; border: none; background: transparent;")
        lbl_etiqueta = QLabel(etiqueta)
        lbl_etiqueta.setWordWrap(True)
        lbl_etiqueta.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; font-weight: 600; border: none; background: transparent;")
        lay.addWidget(lbl_valor)
        lay.addWidget(lbl_etiqueta)
        return tarjeta

    def _tarjeta_lista(self, titulo, filas):
        tarjeta = QFrame()
        tarjeta.setStyleSheet(f"QFrame#lista {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}")
        tarjeta.setObjectName("lista")
        lay = QVBoxLayout(tarjeta)
        lay.setContentsMargins(16, 10, 16, 8)
        lay.setSpacing(0)
        encabezado = QLabel(titulo)
        encabezado.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 700; letter-spacing: 0.6px;"
                                 " border: none; background: transparent; padding: 4px 0 8px;")
        lay.addWidget(encabezado)
        for titulo_fila, detalle, cantidad, tono, ver in filas:
            lay.addWidget(self._fila_lista(titulo_fila, detalle, cantidad, tono, ver))
        lay.addStretch()
        return tarjeta

    def _fila_lista(self, titulo, detalle, cantidad, tono, ver):
        fondo, texto = _TONOS_IMPORTACION[tono]
        fila = QFrame()
        fila.setStyleSheet(f"QFrame {{ border: none; border-top: 1px solid #F1F5F9; background: transparent; }}")
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 10, 0, 10)
        lay.setSpacing(12)
        textos = QVBoxLayout()
        textos.setSpacing(3)
        lbl_titulo = QLabel(titulo)
        lbl_titulo.setWordWrap(True)
        lbl_titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13.5px; font-weight: 600; border: none;")
        lbl_detalle = QLabel(detalle)
        lbl_detalle.setWordWrap(True)
        if ver == 'otra_forma':
            lbl_detalle.setObjectName("detalle_opcional")
        lbl_detalle.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px; border: none;")
        textos.addWidget(lbl_titulo)
        textos.addWidget(lbl_detalle)
        if ver:
            enlace = QPushButton("Ver las unidades →")
            enlace.setCursor(Qt.CursorShape.PointingHandCursor)
            enlace.setStyleSheet("QPushButton { border: none; color: #1D4ED8; font-size: 12px; font-weight: 600; text-align: left; padding: 0; }")
            enlace.clicked.connect(lambda _c=False, c=ver: self._ver_unidades(c))
            textos.addWidget(enlace, alignment=Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(textos, 1)
        pastilla = QLabel(f"{cantidad:,}".replace(",", "."))
        pastilla.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pastilla.setMinimumWidth(40)
        pastilla.setStyleSheet(f"color: {texto}; background: {fondo}; border: none; border-radius: 12px; padding: 3px 10px;"
                               " font-size: 13px; font-weight: 800;")
        lay.addWidget(pastilla, alignment=Qt.AlignmentFlag.AlignTop)
        return fila

    # -------------------------------------------------------------- por unidad
    def _pagina_por_unidad(self):
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        lay.setContentsMargins(0, 4, 0, 8)
        lay.setSpacing(10)

        barra = QHBoxLayout()
        barra.setSpacing(8)
        self._chips = {}
        for clave, texto in _FILTROS_UNIDAD:
            n = len(self._filas) if clave == 'todas' else sum(1 for f in self._filas if clave in f['categorias'])
            chip = QPushButton(f"{texto}  {n}")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(
                f"QPushButton {{ border: 1px solid #CBD5E1; border-radius: 16px; background: {SURFACE}; color: #334155;"
                f" padding: 6px 12px; font-size: 12.5px; font-weight: 600; }}"
                f"QPushButton:checked {{ background: {PRIMARY}; color: white; border-color: {PRIMARY}; }}")
            chip.clicked.connect(lambda _c=False, k=clave: self._elegir_filtro(k))
            self._chips[clave] = chip
            barra.addWidget(chip)
        barra.addStretch()
        self.buscador = QLineEdit()
        self.buscador.setPlaceholderText("Buscar VIN o cliente")
        self.buscador.setFixedWidth(210)
        self.buscador.setStyleSheet(f"QLineEdit {{ border: 1px solid #CBD5E1; border-radius: 8px; background: {SURFACE};"
                                    f" padding: 7px 12px; font-size: 12.5px; color: {TEXT_PRIMARY}; }}")
        self.buscador.textChanged.connect(self._poblar_tabla)
        barra.addWidget(self.buscador)
        lay.addLayout(barra)
        self._chips['todas'].setChecked(True)

        self.tabla = QTableWidget(0, len(_COLUMNAS_UNIDAD))
        self.tabla.setHorizontalHeaderLabels(_COLUMNAS_UNIDAD)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.verticalHeader().setDefaultSectionSize(48)
        self.tabla.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabla.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tabla.itemChanged.connect(self._on_casilla_cambiada)
        self.tabla.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tabla.setShowGrid(False)
        self.tabla.setWordWrap(False)
        encabezado = self.tabla.horizontalHeader()
        encabezado.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        encabezado.setHighlightSections(False)
        encabezado.setSortIndicatorShown(True)
        encabezado.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        encabezado.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        encabezado.setSectionResizeMode(len(_COLUMNAS_UNIDAD) - 1, QHeaderView.ResizeMode.Fixed)
        for indice, ancho in enumerate((80, 0, 190, 270, 150, 150, 190)):
            if ancho:
                self.tabla.setColumnWidth(indice, ancho)
        self.tabla.setStyleSheet(f"""
            QTableWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; gridline-color: transparent; }}
            QTableWidget::item {{ border-bottom: 1px solid #F1F5F9; padding: 2px 8px; color: {TEXT_PRIMARY}; font-size: 12.5px; }}
            QHeaderView::section {{ background: #F1F5F9; color: {TEXT_SECONDARY}; border: none; padding: 9px 8px;
                                    font-size: 11px; font-weight: 700; }}
            QTableWidget::indicator {{ width: 16px; height: 16px; border: 2px solid #66748D; border-radius: 5px; background: #FFFFFF; }}
            QTableWidget::indicator:hover {{ border-color: #1B2B4E; }}
            QTableWidget::indicator:checked {{ background-color: #1F6FEB; border-color: #1F6FEB; }}
        """)
        lay.addWidget(self.tabla, 1)

        pie = QHBoxLayout()
        pie.setSpacing(8)
        self.lbl_conteo = QLabel("")
        self.lbl_conteo.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        pie.addWidget(self.lbl_conteo, 1)
        btn_autorizar = QPushButton(" Autorizar visibles")
        btn_autorizar.setIcon(ThemeManager.icon('fa5s.check-square', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(btn_autorizar)
        btn_autorizar.setToolTip("Autoriza el cambio de forma y facturación de las unidades que se ven en la lista")
        btn_autorizar.clicked.connect(lambda: self._autorizar_visibles(True))
        pie.addWidget(btn_autorizar)
        btn_quitar = QPushButton(" Quitar visibles")
        btn_quitar.setIcon(ThemeManager.icon('fa5s.square', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(btn_quitar)
        btn_quitar.setToolTip("Quita la autorización de las unidades que se ven en la lista")
        btn_quitar.clicked.connect(lambda: self._autorizar_visibles(False))
        pie.addWidget(btn_quitar)
        btn_copiar = QPushButton(" Copiar VIN de esta lista")
        btn_copiar.setIcon(ThemeManager.icon('fa5s.copy', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(btn_copiar)
        btn_copiar.clicked.connect(self._copiar_vins_visibles)
        pie.addWidget(btn_copiar)
        btn_excel = QPushButton(" Exportar a Excel")
        btn_excel.setIcon(ThemeManager.icon('fa5s.file-excel', color=TEXT_SECONDARY))
        ThemeManager.apply_secondary_button(btn_excel)
        btn_excel.clicked.connect(self._exportar_excel)
        pie.addWidget(btn_excel)
        lay.addLayout(pie)
        return pagina

    def _elegir_filtro(self, clave):
        self._filtro_actual = clave
        for k, chip in self._chips.items():
            chip.setChecked(k == clave)
        self._poblar_tabla()

    def _item_tabla(self, texto, clave, color=None, negrita=False):
        item = _ItemOrden(texto, clave)
        fuente = item.font()
        fuente.setBold(negrita)
        item.setFont(fuente)
        if color:
            item.setForeground(QColor(color))
        return item

    def _forma_final(self, f):
        """(forma, facturación) con la que queda la unidad según su casilla."""
        if self._autorizados.get(f['vin']):
            if 'forma' in f['categorias']:
                return f['forma_despues'], f['tipo_despues']
            if 'otra_forma' in f['categorias']:
                return f['forma_opcional'], f['tipo_opcional']
        return f['forma_antes'], f['tipo_antes']

    def _tiene_cambio_forma(self, f):
        return 'forma' in f['categorias'] or 'otra_forma' in f['categorias']

    def _textos_forma_y_aviso(self, f):
        """Celda de forma y facturación, su color y los avisos de la unidad."""
        autorizado = self._autorizados.get(f['vin'], False)
        forma_final, tipo_final = self._forma_final(f)
        cambia = (forma_final.upper(), tipo_final.upper()) != (f['forma_antes'].upper(), f['tipo_antes'].upper())
        if cambia:
            texto_forma = f"{f['forma_antes']} → {forma_final}"
            if tipo_final.upper() != f['tipo_antes'].upper():
                texto_forma += f"\nFacturación: {f['tipo_antes']} → {tipo_final}"
        else:
            texto_forma = f['forma_antes']
        avisos = []
        for categoria in f['categorias']:
            if categoria == 'forma':
                avisos.append(("Cambia de forma", 'azul') if autorizado else ("Cambio sin autorizar", 'gris'))
            elif categoria == 'otra_forma':
                avisos.append(("Pasa a CM", 'azul') if autorizado else ("Su forma no es CM", 'gris'))
            elif categoria in _AVISOS_UNIDAD:
                avisos.append(_AVISOS_UNIDAD[categoria])
        return texto_forma, cambia, avisos

    def _poner_celdas_forma(self, fila, f):
        texto_forma, cambia, avisos = self._textos_forma_y_aviso(f)
        clave_aviso = "|".join(f['categorias'])
        self.tabla.setItem(fila, 3, self._item_tabla(texto_forma, f['forma_antes'].lower(), "#1D4ED8" if cambia else None, cambia))
        color_aviso = _TONOS_IMPORTACION[avisos[0][1]][1] if avisos else None
        self.tabla.setItem(fila, 6, self._item_tabla("\n".join(t for t, _tono in avisos), clave_aviso, color_aviso, True))

    def _poblar_tabla(self, *_args):
        texto = self.buscador.text().strip().lower()
        filas = [f for f in self._filas
                 if (self._filtro_actual == 'todas' or self._filtro_actual in f['categorias'])
                 and (not texto or texto in f['vin'].lower() or texto in f['cliente'].lower())]
        self._filas_visibles = filas
        self.tabla.blockSignals(True)
        self.tabla.setSortingEnabled(False)
        self.tabla.setUpdatesEnabled(False)
        self.tabla.setRowCount(len(filas))
        for i, f in enumerate(filas):
            if self._tiene_cambio_forma(f):
                casilla = QTableWidgetItem()
                casilla.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                casilla.setCheckState(Qt.CheckState.Checked if self._autorizados.get(f['vin']) else Qt.CheckState.Unchecked)
                casilla.setData(Qt.ItemDataRole.UserRole, f['vin'])
                casilla.setToolTip("Autorizar el cambio de forma de contrato y facturación de esta unidad")
            else:
                casilla = QTableWidgetItem()
                casilla.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tabla.setItem(i, 0, casilla)

            unidad = f"{f['cliente']}\n{f['vin']}"
            item_unidad = self._item_tabla(unidad, f['cliente'].lower() + f['vin'])
            item_unidad.setToolTip(unidad)
            self.tabla.setItem(i, 1, item_unidad)

            if f['activacion_despues']:
                texto_act = f"{f['activacion_antes'].title()} → {f['activacion_despues'].title()}"
                color_act = _COLOR_ACTIVACION.get(f['activacion_despues'].upper())
            else:
                texto_act, color_act = f['activacion_antes'].title(), _COLOR_ACTIVACION.get(f['activacion_antes'].upper())
            self.tabla.setItem(i, 2, self._item_tabla(texto_act, texto_act.lower(), color_act, True))

            self._poner_celdas_forma(i, f)

            cm_cambia = f['cm_antes'].upper() != f['cm_despues'].upper()
            texto_cm = (f"{_dato_o_sin_dato(f['cm_antes'])} → {_dato_o_sin_dato(f['cm_despues'])}" if cm_cambia
                        else _dato_o_sin_dato(f['cm_despues']))
            self.tabla.setItem(i, 4, self._item_tabla(texto_cm, f['cm_despues'].lower(),
                                                      "#B45309" if f['cm_despues'].upper() == "EXPIRED" else None, cm_cambia))

            pago_antes, pago_despues = _pago_importacion(f['pago_antes']), _pago_importacion(f['pago_despues'])
            texto_pago = pago_despues if pago_antes == pago_despues else f"{pago_antes} → {pago_despues}"
            numero_pago = _numero_pago(f['pago_despues'])
            self.tabla.setItem(i, 5, self._item_tabla(texto_pago, numero_pago, "#B91C1C" if numero_pago < 0 else None,
                                                      negrita=pago_antes != pago_despues or numero_pago < 0))
        self.tabla.setUpdatesEnabled(True)
        self.tabla.setSortingEnabled(True)
        self.tabla.blockSignals(False)
        self._actualizar_conteo()

    def _actualizar_conteo(self):
        con_cambio = [f for f in self._filas if self._tiene_cambio_forma(f)]
        autorizados = sum(1 for f in con_cambio if self._autorizados.get(f['vin']))
        self.lbl_conteo.setText(
            f"Mostrando {len(self._filas_visibles)} de {len(self._filas)} unidades  ·  "
            f"Cambios de forma y facturación autorizados: {autorizados} de {len(con_cambio)}")

    def _on_casilla_cambiada(self, item):
        if item.column() != 0 or item.data(Qt.ItemDataRole.UserRole) is None:
            return
        vin = item.data(Qt.ItemDataRole.UserRole)
        self._autorizados[vin] = item.checkState() == Qt.CheckState.Checked
        f = next((x for x in self._filas if x['vin'] == vin), None)
        if f is not None:
            self.tabla.blockSignals(True)
            self.tabla.setSortingEnabled(False)
            fila = item.row()
            self._poner_celdas_forma(fila, f)
            self.tabla.setSortingEnabled(True)
            self.tabla.blockSignals(False)
        self._actualizar_conteo()

    def _autorizar_visibles(self, autorizar):
        for f in self._filas_visibles:
            if self._tiene_cambio_forma(f):
                self._autorizados[f['vin']] = autorizar
        self._poblar_tabla()

    def _copiar_vins_visibles(self):
        QApplication.clipboard().setText("\n".join(f['vin'] for f in self._filas_visibles))

    def _exportar_excel(self):
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar la lista de unidades", "Importacion_3PC_unidades.xlsx", "Excel (*.xlsx)")
        if not ruta:
            return
        filas = [{
            "VIN": f['vin'], "CLIENTE": f['cliente'], "ACTIVACIÓN EN EL RM": f['activacion_antes'],
            "ACTIVACIÓN NUEVA": f['activacion_despues'], "FORMA ANTES": f['forma_antes'], "FORMA DESPUÉS": self._forma_final(f)[0],
            "FACTURACIÓN ANTES": f['tipo_antes'], "FACTURACIÓN DESPUÉS": self._forma_final(f)[1],
            "ESTADO CM ANTES": f['cm_antes'], "ESTADO CM DESPUÉS": f['cm_despues'],
            "PAGO CM ANTES": f['pago_antes'], "PAGO CM DESPUÉS": f['pago_despues'],
            "CAMBIO DE FORMA AUTORIZADO": ("Sí" if self._autorizados.get(f['vin']) else "No") if self._tiene_cambio_forma(f) else "",
            "AVISOS": ", ".join(_AVISOS_UNIDAD[c][0] for c in f['categorias'] if c in _AVISOS_UNIDAD),
        } for f in self._filas_visibles]
        from src.ui.compartido.exportacion import iniciar_exportacion
        iniciar_exportacion(self.parentWidget() or self, pd.DataFrame(filas), ruta, atributo_hilo='_export_importacion_thread',
                            titulo="Importación 3PC unidades", ventana=self)

    # --------------------------------------------------------------------- pie
    def _pie(self, resumen):
        pie = QFrame()
        pie.setStyleSheet(f"QFrame#pie {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}")
        pie.setObjectName("pie")
        lay = QHBoxLayout(pie)
        lay.setContentsMargins(26, 14, 26, 14)
        lay.setSpacing(14)

        cantidad = sum(len(v) for v in resumen.get('forma_facturacion', {}).get('cm_otra_forma', {}).values())
        self.interruptor = _Interruptor(False)
        self.interruptor.toggled.connect(self._on_interruptor)
        if cantidad:
            lay.addWidget(self.interruptor)
            textos = QVBoxLayout()
            textos.setSpacing(2)
            titulo = QLabel(f"Pasar a CM las {cantidad} unidades en Provisión, Conversión o Venta")
            titulo.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px; font-weight: 700;")
            ayuda = QLabel("La forma de contrato pasa a CMG, CMB o CMS según su tipo de CM, y la facturación a CM. "
                           "Apagado, solo se actualizan sus datos del 3PC. Los cambios entre CMG, CMB y CMS y las unidades "
                           "en Revisar pasan siempre.")
            ayuda.setWordWrap(True)
            ayuda.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11.5px;")
            textos.addWidget(titulo)
            textos.addWidget(ayuda)
            lay.addLayout(textos, 1)
        else:
            self.interruptor.hide()
            lay.addStretch(1)

        self.btn_cancelar = QPushButton(" Cancelar")
        ThemeManager.apply_secondary_button(self.btn_cancelar)
        self.btn_cancelar.clicked.connect(self.reject)
        lay.addWidget(self.btn_cancelar)
        self.btn_confirmar = QPushButton(" Inyectar a Comercial")
        self.btn_confirmar.setIcon(ThemeManager.icon('fa5s.check', color='white'))
        ThemeManager.apply_primary_button(self.btn_confirmar)
        self.btn_confirmar.clicked.connect(self.accept)
        lay.addWidget(self.btn_confirmar)
        return pie

    def _on_interruptor(self, marcado):
        """Atajo: marca o desmarca todas las unidades en Provisión, Conversión o Venta."""
        for f in self._filas:
            if 'otra_forma' in f['categorias']:
                self._autorizados[f['vin']] = marcado
        detalle = self.findChild(QLabel, "detalle_opcional")
        if detalle is not None:
            detalle.setText(self._texto_opcional(marcado))
        self._poblar_tabla()

    def vins_autorizados(self):
        """VIN cuyo cambio de forma de contrato y facturación quedó autorizado."""
        return {vin for vin, autorizado in self._autorizados.items() if autorizado}
